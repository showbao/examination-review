import streamlit as st
import google.generativeai as genai
from io import BytesIO
import re
import os
import requests

# --- PDF 報告生成庫 ---
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

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

# 自訂 CSS (符合您要求的白底灰邊風格)
st.markdown("""
    <style>
    /* 全局背景 */
    .stApp { background-color: #f8f9fa; }
    .block-container { padding-top: 1.5rem !important; padding-bottom: 3rem !important; }
    
    /* 標題樣式 */
    h1 { color: #2c3e50; font-weight: 800; font-size: 2.2rem; margin-bottom: 0.5rem; }
    h2, h3 { color: #34495e; font-weight: 700; }
    
    /* 1. 登入區卡片 */
    .login-card {
        background-color: white;
        padding: 2.5rem;
        border-radius: 12px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    }
    
    /* 2. 上傳區樣式 (非卡片式，避免重疊) */
    .upload-label { font-size: 1.1rem; font-weight: 700; color: #2c3e50; margin-bottom: 0.5rem; display: block; }
    .upload-sub { font-size: 0.9rem; color: #666; margin-bottom: 0.8rem; display: block; }
    div[data-testid="stFileUploader"] {
        background-color: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1rem;
    }

    /* 3. 審題報告卡片 (白底 + 灰邊 + 陰影) */
    .report-card {
        background-color: white;
        padding: 2rem;
        border-radius: 12px;
        border: 1px solid #d1d5db; /* 灰色邊框 */
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); /* 柔和陰影 */
        margin-bottom: 1.5rem;
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
        border: 1px solid #ccc !important;
        border-radius: 6px !important;
        padding: 10px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 字型註冊 (本地讀取) ---
@st.cache_resource
def setup_chinese_fonts():
    font_name = "NotoSerifTC-Regular.ttf"
    
    # 檢查根目錄
    if os.path.exists(font_name):
        font_path = font_name
    else:
        # 檢查 fonts 資料夾
        font_dir = "fonts"
        if not os.path.exists(font_dir): os.makedirs(font_dir)
        font_path = os.path.join(font_dir, font_name)
        
        # 下載備用
        if not os.path.exists(font_path):
            url = "https://github.com/google/fonts/raw/main/ofl/notoseriftc/static/NotoSerifTC-Regular.ttf"
            try:
                with requests.get(url, stream=True, timeout=20) as r:
                    r.raise_for_status()
                    with open(font_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
            except:
                return False # 下載失敗就用預設

    try:
        pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
        pdfmetrics.registerFont(TTFont('ChineseFont-Bold', font_path))
        addMapping('ChineseFont', 0, 0, 'ChineseFont')
        addMapping('ChineseFont', 0, 1, 'ChineseFont-Bold')
        addMapping('ChineseFont', 1, 0, 'ChineseFont-Bold')
        addMapping('ChineseFont', 1, 1, 'ChineseFont-Bold')
        return True
    except:
        return False

has_font = setup_chinese_fonts()

# --- 2. PDF 生成引擎 (表格轉文字版) ---
def create_pdf_report(ai_content, exam_meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, 
        topMargin=2*cm, bottomMargin=2*cm
    )
    
    styles = getSampleStyleSheet()
    font_name = 'ChineseFont' if has_font else 'Helvetica'
    font_name_bold = 'ChineseFont-Bold' if has_font else 'Helvetica-Bold'
    
    style_normal = ParagraphStyle('CN_Normal', parent=styles['Normal'], fontName=font_name, fontSize=11, leading=16, spaceAfter=6)
    style_title = ParagraphStyle('CN_Title', parent=styles['Heading1'], fontName=font_name_bold, fontSize=20, leading=24, alignment=1, spaceAfter=20, textColor=colors.HexColor("#2c3e50"))
    style_h2 = ParagraphStyle('CN_H2', parent=styles['Heading2'], fontName=font_name_bold, fontSize=14, leading=18, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1e3a8a"))
    
    story = []

    # 標題區
    story.append(Paragraph("台中市北屯區建功國小 智慧審題報告", style_title))
    
    # 檔頭表格
    header_data = [
        ["試卷資訊", exam_meta['info_str']],
        ["命題教師", "__________________", "審題教師", "__________________"],
        ["審查日期", exam_meta['date_str'], "AI 模型", "Gemini 3.0 Pro"]
    ]
    t = Table(header_data, colWidths=[2.5*cm, 6*cm, 2.5*cm, 6*cm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), font_name),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('BACKGROUND', (2,1), (2,-1), colors.whitesmoke),
        ('SPAN', (1,0), (3,0)),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 1*cm))

    # 內容解析
    lines = ai_content.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # 標題
        if line.startswith('###') or line.startswith('##'):
            text = line.replace('#', '').strip()
            story.append(Paragraph(text, style_h2))
            
        # 表格列處理 (轉為文字，避免跑版)
        elif line.startswith('|'):
            # 去除 Markdown 表格語法，改為純文字顯示
            clean_text = line.replace('|', '  ').strip()
            if '---' in clean_text: continue # 跳過分隔線
            story.append(Paragraph(clean_text, style_normal))
            
        # 一般內容
        else:
            # 處理粗體與警示
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            if '❌' in text or '⚠️' in text:
                text = f'<font color="red">{text}</font>'
            try:
                story.append(Paragraph(text, style_normal))
            except:
                clean = re.sub(r'<[^>]+>', '', text)
                story.append(Paragraph(clean, style_normal))

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 3. 輔助函數 ---
def extract_exam_meta(text, grade, subject):
    import datetime
    today = datetime.date.today().strftime("%Y/%m/%d")
    meta = {"year": "113學年度", "semester": "下學期", "exam_name": "定期評量", "date_str": today}
    
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
        for page in reader.pages: text += page.extract_text() + "\n"
        return text
    except: return ""

# --- 4. 登入頁 ---
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
                    <b>⚠️ 使用前請詳閱：</b><br>
                    1. <b>人工查核：</b>AI 結果僅供參考，請回歸專業判斷。<br>
                    2. <b>隱私安全：</b>嚴禁上傳個資或機密文件。<br>
                    3. <b>資料留存：</b>系統重啟後檔案自動銷毀。<br>
                    4. <b>授權範圍：</b>限校內教師內部使用。
                </div>
            """, unsafe_allow_html=True)
            
            password = st.text_input("請輸入校內授權密碼", type="password")
            if st.button("同意聲明並登入"):
                if password == st.secrets.get("LOGIN_PASSWORD", "school123"):
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")
            st.markdown("</div>", unsafe_allow_html=True)

# --- 5. 主程式 ---
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

    st.markdown("<h1 style='text-align: center;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
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
        if st.button("🚀 啟動 AI 專家審題 (生成 PDF 報告)", type="primary"):
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
                scenario_prompt = f"情境 A：以使用者上傳教材 (共 {len(ref_text)} 字) 為絕對標準。"
            else:
                status.write("📚 調用 108 課綱知識庫...")
                scenario_prompt = f"情境 B：未上傳教材，嚴格依據「教育部 108 課綱」{grade}{subject} 學習內容。"

            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
            status.write("🧠 Gemini 3.0 Pro 正在執行雙向細目表分析...")
            
            # --- 恢復專家級提示詞 ---
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
            請依序執行以下五大步驟，並產出報告：

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

            ## 4. 輸出產出 (Final Output)
            請彙整以上分析，提供一份結構清晰的報告。
            **請務必將【修改具體建議 (Action Plan)】放在報告的最前面！**
            若有嚴重錯誤，請用 ❌ 標示；若有建議，請用 ⚠️ 標示。
            
            ---
            【試卷原始內容】：
            {exam_text[:25000]}
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            status.write("📝 排版 PDF 正式報告...")
            pdf_file = create_pdf_report(ai_report, exam_meta)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            st.subheader("📊 審題報告預覽")
            
            # 下載按鈕
            st.download_button(
                label="📥 下載 PDF 正式報告 (含簽核欄)",
                data=pdf_file,
                file_name=f"{exam_meta['grade']}{exam_meta['subject']}_審題報告.pdf",
                mime="application/pdf",
                type="primary"
            )
            
            # 報告卡片呈現 (修正版：直接渲染，不切割，避免跑版)
            st.markdown(f"""
            <div class='report-card'>
                {ai_report.replace('❌', '❌ ').replace('⚠️', '⚠️ ')}
            </div>
            """, unsafe_allow_html=True)

        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "429" in str(e): st.warning("⚠️ 配額已滿，請稍後再試。")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()
