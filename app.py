import streamlit as st
import google.generativeai as genai
from io import BytesIO
import re
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

# 嘗試匯入 PDF 讀取套件
try:
    from pypdf import PdfReader
except ImportError:
    import PyPDF2 as PdfReader

# --- 0. 全局設定與 CSS 美化 ---
st.set_page_config(
    page_title="北屯區建功國小智慧審題系統V1",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自訂 CSS (白底灰邊簡約風格)
st.markdown("""
    <style>
    /* 全局背景與文字顏色強制設定 */
    .stApp { 
        background-color: #f8f9fa; 
        color: #333333 !important;
    }
    
    /* 強制所有 Markdown 文字顏色 */
    .stMarkdown p, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown li {
        color: #333333 !important;
    }
    
    /* 強制輸入框標籤顏色 */
    label[data-testid="stLabel"] {
        color: #333333 !important;
        font-weight: 600;
    }
    
    /* 標題樣式 */
    h1 { color: #2c3e50 !important; font-weight: 800; font-size: 2.2rem; margin-bottom: 0.5rem; text-align: center; }
    h2, h3 { color: #34495e !important; font-weight: 700; }
    
    /* 1. 登入區卡片 */
    .login-card {
        background-color: white;
        padding: 2.5rem;
        border-radius: 12px;
        border: 1px solid #d1d5db;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    /* 2. 上傳區樣式 */
    .upload-label { font-size: 1.1rem; font-weight: 700; color: #2c3e50; margin-bottom: 0.5rem; display: block; }
    .upload-sub { font-size: 0.9rem; color: #6b7280; margin-bottom: 0.8rem; display: block; }
    
    div[data-testid="stFileUploader"] {
        background-color: white;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        padding: 1rem;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }

    /* 3. 審題報告卡片 (魔改 st.info 為白色卡片) */
    div[data-testid="stInfo"] {
        background-color: white !important;
        padding: 2rem !important;
        border-radius: 12px !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05) !important;
        color: #333 !important;
        border: 1px solid #d1d5db !important;
        border-left: 6px solid #4CAF50 !important; /* 綠色識別線 */
    }
    /* 隱藏 st.info 的預設圖示 (可選) */
    /* div[data-testid="stInfo"] > div:first-child { display: none; } */
    
    /* 4. 按鈕美化 */
    .stButton>button { 
        width: 100%; border-radius: 8px !important; font-weight: 700 !important; height: 3.2em !important; 
        background: linear-gradient(135deg, #2563eb, #1e40af) !important; color: white !important; 
        border: none !important; box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2) !important;
        transition: transform 0.2s, box-shadow 0.2s !important;
    }
    .stButton>button:hover { 
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(37, 99, 235, 0.3) !important;
    }
    
    /* 5. 提示框優化 */
    .disclaimer-box {
        background-color: #fff8e1; border-left: 5px solid #ffc107; color: #856404;
        padding: 15px; border-radius: 4px; font-size: 0.95rem; line-height: 1.6;
        margin-bottom: 20px;
    }
    
    /* 隱藏預設元素 */
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    
    /* 輸入框美化 */
    input[type="password"], input[type="text"] {
        border: 1px solid #d1d5db !important;
        border-radius: 6px !important;
        padding: 10px !important;
        color: #333 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 進階 Word 生成引擎 ---
def parse_markdown_to_word(doc, text):
    lines = text.split('\n')
    table_buffer = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith('|'):
            table_buffer.append(line)
            continue
        else:
            if table_buffer:
                create_word_table(doc, table_buffer)
                table_buffer = [] 

        if line.startswith('### '):
            doc.add_heading(line.replace('### ', ''), level=2)
        elif line.startswith('## '):
            doc.add_heading(line.replace('## ', ''), level=1)
        elif line.startswith('#### '):
            p = doc.add_paragraph()
            run = p.add_run(line.replace('#### ', ''))
            run.bold = True
            run.font.size = Pt(12)
        else:
            p = doc.add_paragraph()
            clean_line = line
            
            if line.startswith('* ') or line.startswith('- '):
                clean_line = line[2:].strip()
                if re.match(r'^(\*\*)?(問題|建議|現狀|分析|依據|結論|優點)', clean_line):
                    pass 
                else:
                    p.style = 'List Bullet'
            
            parts = re.split(r'(\*\*.*?\*\*)', clean_line)
            for part in parts:
                if part.startswith('**') and part.endswith('**'):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)

    if table_buffer:
        create_word_table(doc, table_buffer)

def create_word_table(doc, markdown_lines):
    try:
        rows = [line for line in markdown_lines if '---' not in line]
        if not rows: return

        header_line = rows[0].strip().strip('|')
        headers = [h.strip() for h in header_line.split('|')]
        col_count = len(headers)
        
        table = doc.add_table(rows=1, cols=col_count)
        table.style = 'Table Grid'
        
        hdr_cells = table.rows[0].cells
        for i, header_text in enumerate(headers):
            if i < len(hdr_cells):
                hdr_cells[i].text = header_text
                for paragraph in hdr_cells[i].paragraphs:
                    for run in paragraph.runs:
                        run.bold = True

        for line in rows[1:]:
            clean_line = line.strip().strip('|')
            cells_data = clean_line.split('|')
            
            row_cells = table.add_row().cells
            for i, cell_text in enumerate(cells_data):
                if i < col_count and i < len(row_cells):
                    final_text = cell_text.strip().replace('**', '')
                    row_cells[i].text = final_text
                    
    except Exception as e:
        doc.add_paragraph(f"[表格轉換異常]")

def generate_word_report_doc(text, exam_meta):
    doc = Document()
    try:
        doc.styles['Normal'].font.name = 'Microsoft JhengHei'
        doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft JhengHei')
    except: pass
    
    heading = doc.add_heading('北屯區建功國小 智慧審題報告', 0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    p_info = doc.add_paragraph()
    p_info.add_run(f"試卷資訊：{exam_meta['info_str']}\n").bold = True
    p_info.add_run(f"審查日期：{exam_meta['date_str']}\n")
    p_info.add_run(f"AI 模型：Gemini 3.0 Pro\n")
    p_info.add_run("-" * 30)
    
    table = doc.add_table(rows=1, cols=2)
    table.autofit = True
    c1 = table.cell(0, 0)
    c1.text = "命題教師："
    c2 = table.cell(0, 1)
    c2.text = "審題教師："
    
    doc.add_paragraph("\n") 
    parse_markdown_to_word(doc, text)
    bio = BytesIO()
    doc.save(bio)
    return bio

# --- 2. 輔助函數 ---
def extract_exam_meta(text, grade, subject):
    import datetime
    today = datetime.date.today().strftime("%Y/%m/%d")
    
    meta = {
        "year": "113學年度", 
        "semester": "下學期", 
        "exam_name": "定期評量", 
        "date_str": today,
        "grade": grade,
        "subject": subject
    }
    
    sample = text[:800]
    m_year = re.search(r'(\d{3})\s*學年度', sample)
    if m_year: meta['year'] = m_year.group(0)
    
    m_sem = re.search(r'(上|下)\s*學期', sample)
    if m_sem: meta['semester'] = m_sem.group(0)
    
    if "期末" in sample: meta['exam_name'] = "期末評量"
    elif "期中" in sample: meta['exam_name'] = "期中評量"
    
    meta['info_str'] = f"{meta['year']} {meta['semester']} {grade} {subject} {meta['exam_name']}"
    return meta

def extract_pdf_text(file):
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except:
        return "[PDF 讀取失敗]"

# --- 3. 登入頁 ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div style='height: 5vh;'></div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("""
            <div class='login-card'>
                <h2 style='text-align: center; color: #1e3a8a; margin-bottom: 20px;'>🔐 北屯區建功國小智慧審題系統</h2>
                <div class='disclaimer-box'>
                    <div class='disclaimer-title'>⚠️ 使用前請詳閱以下說明：</div><br>
                    本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。<br><br>
                    <b>1. 人工查核機制：</b>AI 生成內容可能存在誤差或不可預期的錯誤（幻覺），最終試卷定稿請務必回歸教師專業判斷。<br>
                    <b>2. 資料隱私安全：</b>嚴禁上傳包含學生個資、隱私或機密敏感內容之文件。<br>
                    <b>3. 資料留存規範：</b>本系統不永久留存檔案，上傳之文件將於系統重啟或對話結束後自動銷毀。<br>
                    <b>4. 風險承擔同意：</b>使用本服務即代表您理解並同意自行評估相關使用風險。<br>
                    <b>5. 授權使用範圍：</b>本系統無償提供予臺中市北屯區建功國小教師使用，為確保資源永續與經費控管，僅限校內教師內部使用。
                </div>
            """, unsafe_allow_html=True)
            
            # 【修正 2】增加間距 (使用兩個 <br>)
            st.markdown("<br><br>", unsafe_allow_html=True)
            
            password = st.text_input("請輸入校內授權密碼", type="password", placeholder="請輸入校內授權密碼", label_visibility="collapsed")
            
            if st.button("同意聲明並登入"):
                if password == st.secrets.get("LOGIN_PASSWORD", "school123"):
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")
            st.markdown("</div>", unsafe_allow_html=True)

# --- 4. 主程式 ---
def main_app():
    # 初始化 Session State (確保報告不會因為點擊下載而消失)
    if 'ai_report' not in st.session_state:
        st.session_state['ai_report'] = None
    if 'word_file' not in st.session_state:
        st.session_state['word_file'] = None
    if 'exam_meta' not in st.session_state:
        st.session_state['exam_meta'] = None

    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 參數設定")
        st.markdown("---")
        st.info("👇 請依序完成設定")

        st.subheader("A. AI 大腦版本")
        st.success("🧠 Gemini 3.0 Pro\n(校內旗艦版)")
        
        st.subheader("B. 選擇年級")
        school_year = st.text_input("學年度", placeholder="113")
        grade = st.selectbox("適用對象", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        
        st.subheader("C. 選擇科目")
        subject = st.selectbox("測驗科目", ["國語", "數學", "英語", "自然", "社會", "生活"])
        version = st.text_input("使用版本", placeholder="例如：康軒")
        
        st.subheader("D. 考試範圍")
        exam_scope = st.text_input("輸入單元或頁數", placeholder="例如：第3-4單元")
        
        st.subheader("F. 嚴格程度")
        strictness = st.select_slider("AI 審查力道", options=["溫柔", "標準", "嚴格", "魔鬼"], value="嚴格")
        st.markdown("---")
        if st.button("登出系統"):
            st.session_state['logged_in'] = False
            st.rerun()

    st.markdown("<h1>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    
    if st.sidebar.state == "collapsed": st.warning("👈 **老師請注意：請先點擊左上角「>」展開設定年級與科目！**")

    st.markdown("### 📂 資料上傳區")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("<span class='upload-label'>📄 1. 上傳試卷 (必要)</span>", unsafe_allow_html=True)
        st.markdown("<span class='upload-sub'>支援 PDF 格式，上限 100MB</span>", unsafe_allow_html=True)
        uploaded_exam = st.file_uploader("上傳試卷", type=['pdf'], key="exam", label_visibility="collapsed")
    
    with col2:
        st.markdown(f"<span class='upload-label'>📘 2. 上傳 {grade}{subject} 課本/習作 (選填)</span>", unsafe_allow_html=True)
        st.markdown("<span class='upload-sub'>如未上傳檔案，請務必確認左邊參數設定是否勾選正確，以避免比對錯誤。</span>", unsafe_allow_html=True)
        uploaded_refs = st.file_uploader("上傳教材", type=['pdf'], key="ref", accept_multiple_files=True, label_visibility="collapsed")

    st.markdown("<br>", unsafe_allow_html=True)

    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題 (生成 Word 報告)", type="primary"):
            # 執行審題邏輯並獲取結果
            report, word_data, meta = process_review_logic(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope, school_year, version)
            
            # 將結果存入 Session State (持久化)
            st.session_state['ai_report'] = report
            st.session_state['word_file'] = word_data
            st.session_state['exam_meta'] = meta

    # --- 結果顯示區 (從 Session State 讀取，確保刷新後不消失) ---
    if st.session_state['ai_report']:
        st.markdown("---")
        st.subheader("📊 審題報告預覽")
        
        # 下載按鈕
        st.download_button(
            label="📥 下載 Word 報告 (.docx)",
            data=st.session_state['word_file'],
            file_name=f"{st.session_state['exam_meta']['grade']}{st.session_state['exam_meta']['subject']}_審題報告.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )
        
        # 【修正 1】使用 st.info 完美替代 HTML div，解決白框問題，且樣式一致
        st.info(st.session_state['ai_report'])

# --- 核心邏輯 (重構為回傳數據的函數) ---
def process_review_logic(exam_file, ref_files, grade, subject, strictness, exam_scope, school_year, version):
    with st.container():
        status = st.status("🔍 AI 專家啟動中...", expanded=True)
        try:
            status.write("📄 分析試卷結構...")
            exam_text = extract_pdf_text(exam_file)
            exam_meta = extract_exam_meta(exam_text, grade, subject)
            status.write(f"✅ 識別資訊：{exam_meta['info_str']}")
            
            ref_text = ""
            scenario_prompt = ""
            if ref_files:
                status.write(f"📘 讀取教材 ({len(ref_files)} 份)...")
                for f in ref_files: ref_text += extract_pdf_text(f) + "\n"
                ref_data_block = f"【教材參考檔案 (Ground Truth)】：\n{ref_text[:60000]}\n"
                scenario_prompt = "**情況 A（有上傳教材）：** 請以本提示詞下方提供的【教材參考檔案】為絕對標準。"
            else:
                status.write("📚 無教材，準備調用知識庫...")
                ref_data_block = "【教材參考檔案】：未上傳 (請執行情況 B 的搜尋策略)\n"
                scenario_prompt = "**情況 B（無上傳教材）：** 請啟動 Google Search 功能搜尋該版本課綱。"

            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
            status.write("🧠 Gemini 3.0 Pro 正在執行雙向細目表分析...")
            
            prompt = f"""
# Role: 台灣國小教育評量暨素養導向命題專家

## 1. 任務目標
你是一位精通台灣教育部「108課綱」與測驗編製理論的專家。請針對使用者上傳的「試卷檔案」，進行全面性的審題與品質分析。

**本次審查資訊：**
* **學年度：** {school_year}
* **年級：** {grade}
* **科目：** {subject}
* **版本：** {version}
* **範圍：** {exam_scope if exam_scope else "未指定"}
* **審查嚴格度：** {strictness}

## 2. 輸入資料處理規則
{scenario_prompt}
* 若無教材，請根據【元數據】（版本、年級、科目）搜尋教學進度表，判斷是否超綱。

## 3. 試卷分析流程 (Analysis Workflow)
請依序執行以下步驟，並產出報告：

### Step 1: 【命題範圍檢核】 (Scope Check)
* 檢查試題是否「超綱」。
* 若有參考教材，指出哪一題超出教材範圍；若無教材，指出哪一題超出 108 課綱該年段的學習內容。

### Step 2: 【題幹與邏輯品質審查】 (Quality Control)
* **定義一致性：** 檢查專有名詞、符號使用是否與課本/課綱一致。
* **誘答項合理性：** 針對選擇題，檢查錯誤選項是否具備誘答力。
* **題意清晰度：** 檢查是否有語意不清、雙重否定或容易產生歧義的敘述。

### Step 3: 【雙向細目表核算】 (Two-Way Specification Table)
請繪製一個 Markdown 表格，將試卷中的**「題號」**填入對應的格子中。
* 欄位包含：單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造
* 最末列：請統計各認知向度的「分數比重 (%)」。

### Step 4: 【難易度與負擔分析】 (Difficulty & Load)
* **難度預測：** 分析整份試卷的難易度配置。
* **成績分佈預測：** 請依據題目難度，預測班級學生的成績分佈比例。

### Step 5: 【素養導向深度審查】 (Competency Review)
* **防偽快篩：** 抓出「假素養警示」（題目情境與解題無關，或純閱讀測驗）。
* **真素養特徵：** 標註符合真實生活情境且需運用知識解決問題的優良試題。

### 【修改具體建議 (Action Plan)】
* 請彙整以上所有分析，提出具體的修改建議。
* 針對紅色警示的題目優先處理，並列出具體優化方案。

## 4. 輸出產出 (Final Output)
請彙整以上分析，提供一份結構清晰的報告。
若有嚴重錯誤，請用 ❌ 標示；若有建議，請用 ⚠️ 標示。

---
{ref_data_block}

---
【試卷原始內容】：
{exam_text[:25000]}
"""
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            status.write("📝 正在製作 Word 報告...")
            word_file = generate_word_report_doc(ai_report, exam_meta)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            return ai_report, word_file.getvalue(), exam_meta
            
        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            return None, None, None

if __name__ == "__main__":
    if st.session_state['logged_in']:
        main_app()
    else:
        login_page()
