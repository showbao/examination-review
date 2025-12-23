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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

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

# 自訂 CSS (優化視覺體驗)
st.markdown("""
    <style>
    /* 全局背景 */
    .stApp { background-color: #f4f6f9; }
    
    /* 頂部留白調整 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 3rem !important;
    }

    /* 標題樣式 */
    h1 { color: #1e3a8a; font-weight: 800; font-size: 2.2rem; text-shadow: 1px 1px 2px rgba(0,0,0,0.1); }
    h2, h3 { color: #2c3e50; font-weight: 700; }
    
    /* 卡片通用樣式 (白色底 + 深陰影) */
    .card {
        background-color: white;
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.08); /* 加深陰影 */
        margin-bottom: 1.5rem;
        border: 1px solid #eef2f6;
    }
    
    /* 上傳區卡片頭部 */
    .upload-header {
        background: linear-gradient(90deg, #f8fafc 0%, #ffffff 100%);
        padding: 1rem 1.5rem;
        border-radius: 12px 12px 0 0;
        border-bottom: 2px solid #e2e8f0;
        font-weight: bold;
        color: #334155;
        display: flex;
        align-items: center;
    }
    .upload-header-icon { margin-right: 8px; font-size: 1.2rem; }
    
    /* Streamlit 上傳元件微調 */
    div[data-testid="stFileUploader"] {
        padding: 1rem 1.5rem;
        background-color: white;
        border-radius: 0 0 12px 12px;
    }
    
    /* 按鈕美化 (Google 風格) */
    .stButton>button { 
        width: 100%; 
        border-radius: 50px; /* 圓角 */
        font-weight: 700; 
        height: 3.5em; 
        background: linear-gradient(45deg, #2563eb, #1d4ed8);
        color: white;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3);
        border: none;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.4);
    }
    
    /* 報告卡片偽裝 */
    div[data-testid="stInfo"], div[data-testid="stError"] {
        background-color: white;
        border: none;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        border-radius: 10px;
        padding: 1.2rem;
        border-left-width: 6px;
    }
    
    /* 隱藏元素 */
    #MainMenu, footer {visibility: hidden;}
    
    /* 登入頁美化 */
    input[type="password"] {
        border: 2px solid #cbd5e1 !important;
        border-radius: 8px !important;
        padding: 12px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 字型下載與註冊 (確保 PDF 有中文) ---
# 使用思源宋體 (Noto Serif TC) 作為標楷體的替代品，看起來最正式
@st.cache_resource
def setup_chinese_fonts():
    font_dir = "fonts"
    if not os.path.exists(font_dir):
        os.makedirs(font_dir)
    
    # 下載字型 (GitHub Raw Link)
    fonts = {
        "NotoSerifTC-Regular": "https://github.com/google/fonts/raw/main/ofl/notoseriftc/NotoSerifTC-Regular.ttf",
        "NotoSerifTC-Bold": "https://github.com/google/fonts/raw/main/ofl/notoseriftc/NotoSerifTC-Bold.ttf"
    }
    
    for name, url in fonts.items():
        path = os.path.join(font_dir, f"{name}.ttf")
        if not os.path.exists(path):
            try:
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
            except Exception:
                pass # 如果下載失敗，將使用預設字型 (可能會亂碼，但在雲端通常會成功)

    try:
        pdfmetrics.registerFont(TTFont('ChineseFont', os.path.join(font_dir, 'NotoSerifTC-Regular.ttf')))
        pdfmetrics.registerFont(TTFont('ChineseFont-Bold', os.path.join(font_dir, 'NotoSerifTC-Bold.ttf')))
        return True
    except:
        return False

# 初始化字型
has_font = setup_chinese_fonts()

# --- 2. 輔助函數：PDF 生成引擎 ---
def create_pdf_report(ai_content, exam_meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, 
        topMargin=2*cm, bottomMargin=2*cm
    )
    
    styles = getSampleStyleSheet()
    # 定義中文樣式
    style_normal = ParagraphStyle(
        'ChineseNormal', 
        parent=styles['Normal'], 
        fontName='ChineseFont', 
        fontSize=11, 
        leading=16,
        spaceAfter=6
    )
    style_title = ParagraphStyle(
        'ChineseTitle', 
        parent=styles['Heading1'], 
        fontName='ChineseFont-Bold', 
        fontSize=18, 
        leading=22, 
        alignment=1, # Center
        spaceAfter=20
    )
    style_heading = ParagraphStyle(
        'ChineseHeading', 
        parent=styles['Heading2'], 
        fontName='ChineseFont-Bold', 
        fontSize=14, 
        leading=18, 
        spaceBefore=12, 
        spaceAfter=6,
        textColor=colors.HexColor("#1e3a8a")
    )
    style_action_plan = ParagraphStyle(
        'ActionPlan',
        parent=style_normal,
        backColor=colors.HexColor("#fff3cd"),
        borderColor=colors.HexColor("#ffeeba"),
        borderPadding=10,
        borderRadius=5,
        spaceAfter=15
    )

    story = []

    # --- A. 檔頭表格 (Header Table) ---
    story.append(Paragraph("台中市北屯區建功國小 試卷審題報告", style_title))
    
    # 建立檔頭資料
    header_data = [
        ["試卷資訊", exam_meta['info_str']],
        ["命題教師", "____________________ (簽章)", "審題教師", "____________________ (簽章)"],
        ["審查日期", exam_meta['date_str'], "審查系統", "Gemini 3.0 Pro AI 協作"]
    ]
    
    # 表格樣式
    t_header = Table(header_data, colWidths=[2.5*cm, 6*cm, 2.5*cm, 6*cm])
    t_header.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'ChineseFont'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey), # 格線
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke), # 第一欄背景
        ('BACKGROUND', (2,1), (2,-1), colors.whitesmoke), # 第三欄背景
        ('SPAN', (1,0), (3,0)), # 合併第一列的試卷資訊
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 1*cm))

    # --- B. 內容解析與渲染 ---
    # 簡單的 Markdown 解析器
    lines = ai_content.split('\n')
    
    in_table = False
    table_data = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # 1. 偵測標題 (###, ##)
        if line.startswith('###') or line.startswith('##'):
            clean_text = line.replace('#', '').strip()
            story.append(Paragraph(clean_text, style_heading))
        
        # 2. 偵測 Action Plan (特殊樣式)
        elif "修改具體建議" in line and "Action Plan" in line:
             story.append(Paragraph(line, style_heading))
             # 下面的內容會自動用 normal，但我們希望它醒目一點，這裡簡化處理
             
        # 3. 偵測表格 (雙向細目表)
        elif line.startswith('|'):
            if not in_table:
                in_table = True
                table_data = []
            
            # 處理 Markdown 表格列
            cells = [cell.strip() for cell in line.split('|') if cell]
            # 過濾掉分隔線 (---)
            if '---' in cells[0]:
                continue
            table_data.append(cells)
            
        else:
            # 如果之前的表格結束了，先畫表格
            if in_table:
                if table_data:
                    # 建立 ReportLab 表格
                    col_count = len(table_data[0])
                    # 自動調整欄寬
                    t = Table(table_data, colWidths=[17*cm/col_count]*col_count)
                    t.setStyle(TableStyle([
                        ('FONTNAME', (0,0), (-1,-1), 'ChineseFont'),
                        ('FONTSIZE', (0,0), (-1,-1), 9),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.black), # 黑色格線
                        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey), # 標題列背景
                        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                        ('WORDWRAP', (0,0), (-1,-1), True),
                    ]))
                    story.append(t)
                    story.append(Spacer(1, 0.5*cm))
                in_table = False
                table_data = []
            
            # 一般文字
            # 處理粗體 **text** -> <b>text</b>
            formatted_line = line.replace('**', '<b>').replace('**', '</b>')
            # 處理警示符號顏色
            if '❌' in formatted_line or '⚠️' in formatted_line:
                formatted_line = f'<font color="red">{formatted_line}</font>'
                
            story.append(Paragraph(formatted_line, style_normal))

    # 處理文末若還有表格未輸出的情況
    if in_table and table_data:
        col_count = len(table_data[0])
        t = Table(table_data, colWidths=[17*cm/col_count]*col_count)
        t.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'ChineseFont'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        story.append(t)

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 3. 試卷資訊擷取 (Regex) ---
def extract_exam_meta(text, grade, subject):
    """嘗試從文字中抓取學年度與考試名稱，抓不到就用側邊欄資訊"""
    import datetime
    today = datetime.date.today().strftime("%Y/%m/%d")
    
    # 預設值
    meta = {
        "year": "113學年度", # 預設
        "semester": "下學期",
        "exam_name": "定期評量",
        "grade": grade,
        "subject": subject,
        "date_str": today
    }
    
    # 嘗試抓取 (例如：112學年度、第二次定期評量)
    # 取前 500 字分析即可
    sample = text[:500]
    
    match_year = re.search(r'(\d{3})\s*學年度', sample)
    if match_year: meta['year'] = f"{match_year.group(1)}學年度"
    
    match_sem = re.search(r'(上|下)\s*學期', sample)
    if match_sem: meta['semester'] = f"{match_sem.group(1)}學期"
    
    match_exam = re.search(r'(期中|期末|第[一二三]次|定期)評量', sample)
    if match_exam: meta['exam_name'] = match_exam.group(0)
    elif "期末" in sample: meta['exam_name'] = "期末評量"
    elif "期中" in sample: meta['exam_name'] = "期中評量"
    
    # 組合完整字串
    meta['info_str'] = f"{meta['year']} {meta['semester']} {meta['grade']} {meta['subject']} {meta['exam_name']}"
    return meta

# --- 4. Session State & Login ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div style='height: 5vh;'></div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("""
            <div class='card'>
                <h2 style='text-align: center; color: #1e3a8a; margin-bottom: 20px;'>🔐 建功國小智慧審題系統</h2>
                <div style='background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 8px; font-size: 0.9rem; line-height: 1.6;'>
                    <b>⚠️ 使用前請詳閱：</b><br>
                    1. <b>人工查核：</b>AI 結果僅供參考，請回歸專業判斷。<br>
                    2. <b>隱私安全：</b>嚴禁上傳個資或機密文件。<br>
                    3. <b>資料留存：</b>系統重啟後檔案自動銷毀。<br>
                    4. <b>授權範圍：</b>限建功國小校內教師使用。
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

# --- 5. Main App ---
def main_app():
    # 側邊欄
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 參數設定")
        st.info("👇 請依序完成設定")

        st.success("🧠 Gemini 3.0 Pro\n(校內旗艦版)")
        
        grade = st.selectbox("適用對象", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("測驗科目", ["國語", "數學", "英語", "自然", "社會", "生活"])
        exam_scope = st.text_input("考試範圍", placeholder="例：康軒版 第3-4單元")
        strictness = st.select_slider("AI 審查力道", options=["溫柔", "標準", "嚴格", "魔鬼"], value="嚴格")
        
        st.divider()
        if st.button("登出系統"):
            st.session_state['logged_in'] = False
            st.rerun()

    # 主標題
    st.markdown("<h1 style='text-align: center; margin-bottom: 10px;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    
    if st.sidebar.state == "collapsed": 
        st.warning("👈 **老師請注意：請先點擊左上角「>」展開設定年級與科目！**")

    # 上傳區 (卡片式)
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <div class='card' style='padding:0; overflow:hidden;'>
            <div class='upload-header'>
                <span class='upload-header-icon'>📄</span> 1. 上傳試卷 (必要)
            </div>
            <div style='padding: 10px 20px 0px 20px;'>
                <small style='color:gray;'>支援 PDF，上限 100MB</small>
            </div>
        </div>
        """, unsafe_allow_html=True)
        uploaded_exam = st.file_uploader("上傳試卷", type=['pdf'], key="exam", label_visibility="collapsed")

    with col2:
        st.markdown(f"""
        <div class='card' style='padding:0; overflow:hidden;'>
            <div class='upload-header' style='border-bottom-color: #4CAF50;'>
                <span class='upload-header-icon'>📘</span> 2. 上傳 {grade}{subject} 課本/習作 (選填)
            </div>
            <div style='padding: 10px 20px 0px 20px;'>
                 <small style='color:gray;'>未上傳則依據 108 課綱比對</small>
            </div>
        </div>
        """, unsafe_allow_html=True)
        uploaded_refs = st.file_uploader("上傳教材", type=['pdf'], key="ref", accept_multiple_files=True, label_visibility="collapsed")

    # 執行按鈕
    if uploaded_exam:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 啟動 AI 專家審題 (生成 PDF 報告)", type="primary"):
            process_review(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope)

# --- 6. 核心處理邏輯 ---
def process_review(exam_file, ref_files, grade, subject, strictness, exam_scope):
    
    # 狀態容器
    status_container = st.status("🔍 AI 專家審題中...", expanded=True)
    
    try:
        # A. 讀取檔案
        status_container.write("📄 正在分析 PDF 結構與提取試卷資訊...")
        exam_text = extract_pdf_text(exam_file)
        
        # 提取試卷 metadata (用於 PDF Header)
        exam_meta = extract_exam_meta(exam_text, grade, subject)
        status_container.write(f"✅ 識別資訊：{exam_meta['info_str']}")
        
        ref_text = ""
        scenario_prompt = ""
        if ref_files:
            status_container.write(f"📘 讀取參考教材 ({len(ref_files)} 份)...")
            for f in ref_files: ref_text += extract_pdf_text(f) + "\n"
            scenario_prompt = f"情境 A：以使用者上傳的教材 (共 {len(ref_text)} 字) 為絕對標準。"
        else:
            status_container.write("📚 調用 108 課綱知識庫...")
            scenario_prompt = f"情境 B：未上傳教材，請嚴格依據「教育部 108 課綱」{grade}{subject} 學習內容。"

        # B. 設定 AI
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-3-pro-preview")
        
        status_container.write("🧠 Gemini 3.0 Pro 正在進行雙向細目表分析...")
        
        # C. Prompt
        prompt = f"""
        # Role: 台灣國小教育評量專家
        
        ## 任務
        請針對 {grade}{subject} 試卷進行審查。
        範圍：{exam_scope if exam_scope else "未指定"}
        嚴格度：{strictness}
        資料基準：{scenario_prompt}
        
        ## 參考資料 (若有)
        {ref_text[:30000]}
        
        ## 試卷內容
        {exam_text[:20000]}
        
        ## 輸出指令 (重要！)
        請直接輸出審題報告內容，不要有多餘的問候語。
        請務必包含以下章節，並使用 Markdown 格式 (包含表格)：

        1. **【修改具體建議 (Action Plan)】** (請放在最前面，列出 3-5 點關鍵修改建議，若有重大錯誤請用 ❌ 標示)
        2. **Step 1: 命題範圍檢核** (是否超綱？)
        3. **Step 2: 題幹與邏輯品質審查**
        4. **Step 3: 雙向細目表** (請務必繪製 Markdown 表格：欄位為 單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造)
        5. **Step 4: 難易度分析**
        6. **Step 5: 素養導向審查**
        """
        
        response = model.generate_content(prompt)
        ai_report = response.text
        
        # D. 生成 PDF
        status_container.write("📝 正在排版並生成 PDF 正式報告...")
        pdf_file = create_pdf_report(ai_report, exam_meta)
        
        status_container.update(label="✅ 分析完成！", state="complete", expanded=False)
        
        # E. 顯示結果
        st.markdown("### 📊 審題報告預覽")
        
        # PDF 下載按鈕
        st.download_button(
            label="📥 下載 PDF 正式報告 (含簽核欄)",
            data=pdf_file,
            file_name=f"{exam_meta['grade']}{exam_meta['subject']}_審題報告.pdf",
            mime="application/pdf",
            type="primary"
        )
        
        # 卡片式預覽
        sections = re.split(r'(Step \d:|【修改具體建議)', ai_report)
        # 簡單渲染
        current_text = ""
        for part in sections:
            if re.match(r'(Step \d:|【修改具體建議)', part):
                if current_text.strip():
                     display_card(current_text)
                current_text = "### " + part 
            else:
                current_text += part
        if current_text.strip():
            display_card(current_text)

    except Exception as e:
        status_container.update(label="❌ 發生錯誤", state="error")
        st.error(f"執行失敗：{str(e)}")

def display_card(text):
    has_warning = "❌" in text or "⚠️" in text
    if has_warning:
        st.error(text, icon="⚠️")
    else:
        st.info(text, icon="✅")

def extract_pdf_text(file):
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages: text += page.extract_text() + "\n"
        return text
    except: return ""

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()
