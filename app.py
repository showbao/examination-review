import streamlit as st
import google.generativeai as genai
from io import BytesIO
from docx import Document # 改回使用 python-docx
from docx.shared import Pt # 用於設定 Word 字體大小
from docx.enum.text import WD_ALIGN_PARAGRAPH # 用於設定 Word 對齊

# 嘗試匯入 PDF 讀取套件
try:
    from pypdf import PdfReader
except ImportError:
    import PyPDF2 as PdfReader

# --- 0. 全局設定與 CSS 美化 ---
st.set_page_config(
    page_title="台中市北屯區建功國小智慧審題系統",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 自訂 CSS (針對您要求的白底灰邊簡約風格)
st.markdown("""
    <style>
    /* 全局背景 */
    .stApp { background-color: #f8f9fa; }
    .block-container { padding-top: 1.5rem !important; padding-bottom: 3rem !important; }
    
    /* 標題樣式 */
    h1 { color: #2c3e50; font-weight: 800; font-size: 2.2rem; margin-bottom: 0.5rem; text-align: center; }
    h2, h3 { color: #34495e; font-weight: 700; }
    
    /* 1. 登入區卡片 (白底灰邊) */
    .login-card {
        background-color: white;
        padding: 2.5rem;
        border-radius: 12px;
        border: 1px solid #d1d5db; /* 灰色邊框 */
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    /* 2. 上傳區樣式 */
    .upload-label { font-size: 1.1rem; font-weight: 700; color: #2c3e50; margin-bottom: 0.5rem; display: block; }
    .upload-sub { font-size: 0.9rem; color: #6b7280; margin-bottom: 0.8rem; display: block; }
    
    div[data-testid="stFileUploader"] {
        background-color: white;
        border: 1px solid #d1d5db; /* 灰色邊框 */
        border-radius: 10px;
        padding: 1.5rem;
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
        transition: border-color 0.3s;
    }
    div[data-testid="stFileUploader"]:hover {
        border-color: #6b7280;
    }

    /* 3. 審題報告容器 (單一整合卡片，解決跑版問題) */
    .report-card {
        background-color: white;
        padding: 3rem;
        border-radius: 12px;
        border: 1px solid #d1d5db; /* 灰色邊框 */
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        margin-top: 1.5rem;
        margin-bottom: 2rem;
        line-height: 1.8; /* 增加行距，提升閱讀體驗 */
    }
    
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
    
    /* 5. 免責聲明 (復原為完整版樣式) */
    .disclaimer-box {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        color: #856404;
        padding: 15px;
        border-radius: 8px;
        font-size: 0.9rem;
        line-height: 1.6;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .disclaimer-title { font-weight: bold; margin-bottom: 5px; font-size: 1rem; }
    
    /* 隱藏預設元素 */
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    
    /* 輸入框美化 */
    input[type="password"], input[type="text"] {
        border: 1px solid #d1d5db !important;
        border-radius: 6px !important;
        padding: 10px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. Word 生成引擎 (取代 PDF) ---
def generate_word_report(text, exam_meta):
    doc = Document()
    
    # 標題
    heading = doc.add_heading('台中市北屯區建功國小 智慧審題報告', 0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # 試卷資訊區塊
    p_info = doc.add_paragraph()
    p_info.add_run(f"試卷資訊：{exam_meta['info_str']}\n").bold = True
    p_info.add_run(f"審查日期：{exam_meta['date_str']}\n")
    p_info.add_run(f"AI 模型：Gemini 3.0 Pro\n")
    p_info.add_run("-" * 30)
    
    # 簽核欄位
    table = doc.add_table(rows=1, cols=2)
    table.autofit = True
    c1 = table.cell(0, 0)
    c1.text = "命題教師：__________________"
    c2 = table.cell(0, 1)
    c2.text = "審題教師：__________________"
    
    doc.add_paragraph("\n") # 空行
    
    # 寫入 AI 報告內容
    # 簡單處理：將 Markdown 的標題符號 (#) 轉換為 Word 格式，其餘保留文字
    for line in text.split('\n'):
        line = line.strip()
        if not line: continue
        
        if line.startswith('### '):
            doc.add_heading(line.replace('### ', ''), level=2)
        elif line.startswith('## '):
            doc.add_heading(line.replace('## ', ''), level=1)
        elif line.startswith('**') and line.endswith('**'):
            p = doc.add_paragraph()
            p.add_run(line.replace('**', '')).bold = True
        else:
            doc.add_paragraph(line)
            
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
    
    sample = text[:500]
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

# --- 3. 登入頁 (還原完整版免責聲明) ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div style='height: 5vh;'></div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("""
            <div class='login-card'>
                <h2 style='text-align: center; color: #1e3a8a; margin-bottom: 20px;'>🔐 建功國小智慧審題系統</h2>
                <div class='disclaimer-box'>
                    <div class='disclaimer-title'>⚠️ 使用前請詳閱以下說明：</div>
                    本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。<br><br>
                    <b>1. 人工查核機制：</b>AI 生成內容可能存在誤差或不可預期的錯誤（幻覺），最終試卷定稿請務必回歸教師專業判斷。<br>
                    <b>2. 資料隱私安全：</b>嚴禁上傳包含學生個資、隱私或機密敏感內容之文件。<br>
                    <b>3. 資料留存規範：</b>本系統不永久留存檔案，上傳之文件將於系統重啟或對話結束後自動銷毀。<br>
                    <b>4. 風險承擔同意：</b>使用本服務即代表您理解並同意自行評估相關使用風險。<br>
                    <b>5. 授權使用範圍：</b>本系統無償提供予臺中市北屯區建功國小教師使用，為確保資源永續與經費控管，僅限校內教師內部使用。
                </div>
                <br>
            """, unsafe_allow_html=True)
            
            password = st.text_input("請輸入校內授權密碼", type="password")
            if st.button("同意聲明並登入"):
                if password == st.secrets.get("LOGIN_PASSWORD", "school123"):
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")
            st.markdown("</div>", unsafe_allow_html=True)

# --- 4. 主程式 ---
def main_app():
    st.markdown("""<style>[data-testid="collapsedControl"] {display: none}</style>""", unsafe_allow_html=True)
    
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 參數設定")
        st.info("👇 請依序完成設定")
        st.success("🧠 Gemini 3.0 Pro\n(校內旗艦版)")
        
        grade = st.selectbox("適用對象", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("測驗科目", ["國語", "數學", "英語", "自然", "社會", "生活"])
        exam_scope = st.text_input("考試範圍", placeholder="例如：康軒版 第3-4單元")
        strictness = st.select_slider("AI 審查力道", options=["溫柔", "標準", "嚴格", "魔鬼"], value="嚴格")
        st.divider()
        if st.button("登出系統"):
            st.session_state['logged_in'] = False
            st.rerun()

    st.markdown("<h1>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    if st.sidebar.state == "collapsed": st.warning("👈 **老師請注意：請先點擊左上角「>」展開設定年級與科目！**")

    # 資料上傳區
    st.markdown("### 📂 資料上傳區")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("<span class='upload-label'>📄 1. 上傳試卷 (必要)</span>", unsafe_allow_html=True)
        st.markdown("<span class='upload-sub'>支援 PDF 格式，上限 100MB</span>", unsafe_allow_html=True)
        uploaded_exam = st.file_uploader("上傳試卷", type=['pdf'], key="exam", label_visibility="collapsed")
    
    with col2:
        st.markdown(f"<span class='upload-label'>📘 2. 上傳 {grade}{subject} 課本/習作 (選填)</span>", unsafe_allow_html=True)
        st.markdown("<span class='upload-sub'>如上傳可使用 AI 精準比對，未上傳則依據 108 課綱比對。</span>", unsafe_allow_html=True)
        uploaded_refs = st.file_uploader("上傳教材", type=['pdf'], key="ref", accept_multiple_files=True, label_visibility="collapsed")

    st.markdown("<br>", unsafe_allow_html=True)

    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題 (生成 Word 報告)", type="primary"):
            process_review(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope)

def process_review(exam_file, ref_files, grade, subject, strictness, exam_scope):
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
                scenario_prompt = f"""
                * **情境 A (使用者有上傳教材)：**
                * **基準：** 請嚴格以本提示詞下方提供的【參考教材內容】為絕對標準。
                * **動作：** 檢查試卷題目是否超出這些教材的教學範圍。
                
                【參考教材內容】：
                {ref_text[:60000]}
                """
            else:
                status.write("📚 調用 108 課綱知識庫...")
                scenario_prompt = f"""
                * **情境 B (使用者未上傳教材)：**
                * **基準：** 請啟動你內建的知識庫，調用「台灣教育部 108 課綱」中【{subject}】領域、【{grade}】的「學習內容」與「學習表現」。
                * **動作：** 以課綱條目為標準，判斷試卷是否符合該年段的學習目標。
                """

            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
            status.write("🧠 Gemini 3.0 Pro 正在執行雙向細目表分析...")
            
            # --- 調整後的順序：Action Plan 移至最後 ---
            prompt = f"""
            # Role: 台灣國小教育評量暨素養導向命題專家
            
            ## 1. 任務目標
            你是一位精通台灣教育部「108課綱」與測驗編製理論的專家。請針對使用者上傳的「試卷檔案」，進行全面性的審題與品質分析。
            
            本次審查資訊：
            * **年級：** {grade}
            * **科目：** {subject}
            * **版本/範圍：** {exam_scope if exam_scope else "未指定"}
            * **審查嚴格度：** {strictness}

            ## 2. 輸入資料處理規則
            {scenario_prompt}

            ## 3. 試卷分析流程 (Analysis Workflow)
            請依序執行以下步驟，並產出報告：

            ### Step 1: 【命題範圍檢核】 (Scope Check)
            * 檢查試題是否「超綱」。
            * 若有參考教材，指出哪一題超出教材範圍；若無教材，指出哪一題超出 108 課綱該年段的學習內容。

            ### Step 2: 【題幹與邏輯品質審查】 (Quality Control)
            * **定義一致性：** 檢查專有名詞、符號使用是否與課本/課綱一致。
            * **誘答項合理性：** 針對選擇題，檢查錯誤選項是否具備誘答力，或是有明顯邏輯漏洞。
            * **題意清晰度：** 檢查是否有語意不清、雙重否定或容易產生歧義的敘述。

            ### Step 3: 【雙向細目表核算】 (Two-Way Specification Table)
            請繪製一個 Markdown 表格，將試卷中的**「題號」**填入對應的格子中。
            * 欄位包含：單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造
            * 最末列：請統計各認知向度的「分數比重 (%)」。

            ### Step 4: 【難易度與負擔分析】 (Difficulty & Load)
            * **難度預測：** 分析整份試卷的難易度配置（直球題 vs. 變形題）。
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
            【試卷原始內容】：
            {exam_text[:25000]}
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            status.write("📝 正在製作 Word 報告...")
            # 使用 docx 生成報告
            word_file = generate_word_report(ai_report, exam_meta)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            st.subheader("📊 審題報告預覽")
            
            # 下載按鈕 (改回 Word)
            st.download_button(
                label="📥 下載 Word 報告 (.docx)",
                data=word_file.getvalue(),
                file_name=f"{exam_meta['grade']}{exam_meta['subject']}_審題報告.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary"
            )
            
            # 報告卡片呈現 (單一整合卡片，解決跑版問題)
            # 使用 st.markdown 渲染 HTML 容器，內部再渲染 Markdown 文字
            st.markdown(f"""
            <div class='report-card'>
                {st.markdown(ai_report) or ""} 
            </div>
            """, unsafe_allow_html=True)
            # 注意：st.markdown() 回傳 None，這裡我們稍微調整寫法以正確顯示
            # 改為先印 div 頭，再印 markdown，再印 div 尾，這是 Streamlit 的標準做法
            
        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "429" in str(e): st.warning("⚠️ 配額已滿，請稍後再試。")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()
