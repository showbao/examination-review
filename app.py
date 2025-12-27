import streamlit as st
import google.generativeai as genai
from io import BytesIO
import re
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

# --- Google Drive 相關套件 ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# 嘗試匯入 PDF 讀取套件
try:
    from pypdf import PdfReader
except ImportError:
    import PyPDF2 as PdfReader

# --- 0. 全局設定與 CSS 美化 ---
st.set_page_config(
    page_title="北屯區建功國小智慧審題系統V2",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自訂 CSS
st.markdown("""
    <style>
    /* 全局背景 */
    .stApp { background-color: #f8f9fa; }
    
    /* 調整主內容區塊的頂部間距 */
    .block-container { padding-top: 1.5rem !important; padding-bottom: 3rem !important; }
    
    /* 隱藏側邊欄收合按鈕 */
    [data-testid="collapsedControl"] { display: none; }
    
    /* 側邊欄頂部完全除白 */
    section[data-testid="stSidebar"] .block-container {
        padding-top: 0rem !important;
        margin-top: 0rem !important;
    }

    /* 標題樣式 */
    h1 { color: #2c3e50; font-weight: 800; font-size: 2.2rem; margin-bottom: 0.5rem; text-align: center; }
    h2, h3 { color: #34495e; font-weight: 700; }
    
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

    /* 3. 審題報告卡片 */
    div[data-testid="stInfo"] {
        background-color: white !important;
        padding: 2rem !important;
        border-radius: 12px !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05) !important;
        color: #333 !important;
        border: 1px solid #d1d5db !important;
        border-left: 6px solid #4CAF50 !important;
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
        border: 1px solid #d1d5db !important;
        border-radius: 6px !important;
        padding: 10px !important;
        color: #333333 !important;
        background-color: #ffffff !important;
        position: relative !important;
        z-index: 1 !important;
    }
    
    /* 側邊欄標題美化 */
    .sidebar-header {
        font-size: 1.1rem;
        font-weight: 700;
        color: #1e3a8a;
        margin-top: 15px;
        margin-bottom: 5px;
        padding-bottom: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. Google Drive API 模組 ---
@st.cache_resource
def init_drive_service():
    try:
        service_account_info = st.secrets["gcp_service_account"]
        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=['https://www.googleapis.com/auth/drive.readonly'])
        return build('drive', 'v3', credentials=creds)
    except: return None

def get_drive_files(folder_id):
    service = init_drive_service()
    if not service: return []
    try:
        query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
        results = service.files().list(q=query, pageSize=100, fields="nextPageToken, files(id, name)").execute()
        return results.get('files', [])
    except: return []

def download_drive_file(file_id):
    service = init_drive_service()
    if not service: return None
    try:
        request = service.files().get_media(fileId=file_id)
        file_io = BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        file_io.seek(0)
        return file_io
    except: return None

# --- 2. Word 生成引擎 ---
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

# --- 3. 強化版試卷資訊擷取 (自動偵測) ---
def extract_exam_meta_enhanced(text):
    import datetime
    today = datetime.date.today().strftime("%Y/%m/%d")
    
    meta = {
        "year": "113學年度", "semester": "下學期", "exam_name": "定期評量",
        "grade": "未偵測", "subject": "未偵測", "date_str": today
    }
    
    sample = text[:1000] 
    m_year = re.search(r'(\d{3})\s*學年度', sample)
    if m_year: meta['year'] = f"{m_year.group(1)}學年度"
    m_sem = re.search(r'(上|下)\s*學期', sample)
    if m_sem: meta['semester'] = f"{m_sem.group(1)}學期"
    
    # 偵測年級 (擴充關鍵字)
    m_grade = re.search(r'([一二三四五六])\s*年級', sample)
    if m_grade: meta['grade'] = f"{m_grade.group(1)}年級"
    
    # 偵測科目
    subjects = ["國語", "數學", "英語", "英文", "自然", "社會", "生活"]
    for sub in subjects:
        if sub in sample:
            meta['subject'] = sub
            break
            
    m_exam = re.search(r'(期中|期末|第[一二三]次|定期)評量', sample)
    if m_exam: meta['exam_name'] = m_exam.group(0)
    elif "期末" in sample: meta['exam_name'] = "期末評量"
    elif "期中" in sample: meta['exam_name'] = "期中評量"
    
    meta['info_str'] = f"{meta['year']} {meta['semester']} {meta['grade']} {meta['subject']} {meta['exam_name']}"
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
                    <div class='disclaimer-title'>⚠️ 使用前請詳閱以下說明：</div>
                    本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。<br><br>
                    <b>1. 人工查核機制：</b>AI 生成內容可能存在誤差或不可預期的錯誤（幻覺），最終試卷定稿請務必回歸教師專業判斷。<br>
                    <b>2. 資料隱私安全：</b>嚴禁上傳包含學生個資、隱私或機密敏感內容之文件。<br>
                    <b>3. 資料留存規範：</b>本系統不永久留存檔案，上傳之文件將於系統重啟或對話結束後自動銷毀。<br>
                    <b>4. 風險承擔同意：</b>使用本服務即代表您理解並同意自行評估相關使用風險。<br>
                    <b>5. 授權使用範圍：</b>本系統無償提供予臺中市北屯區建功國小教師使用，為確保資源永續與經費控管，僅限校內教師內部使用。
                </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
            
            password = st.text_input("請輸入校內授權密碼", type="password", placeholder="請輸入校內授權密碼", label_visibility="collapsed")
            if st.button("同意聲明並登入"):
                if password == st.secrets.get("LOGIN_PASSWORD", "school123"):
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")
            st.markdown("</div>", unsafe_allow_html=True)

# --- 5. 主程式 ---
def main_app():
    if 'ai_report' not in st.session_state: st.session_state['ai_report'] = None
    if 'word_file' not in st.session_state: st.session_state['word_file'] = None
    if 'exam_meta' not in st.session_state: st.session_state['exam_meta'] = None

    # --- 側邊欄設定區 ---
    with st.sidebar:
        # 1. 試卷上傳
        st.markdown("<div class='sidebar-header'>📂 試卷上傳</div>", unsafe_allow_html=True)
        uploaded_exam = st.file_uploader("選擇試卷 PDF", type=['pdf'], key="exam", label_visibility="collapsed")
        
        # 2. 課本習作上傳 (新增功能)
        st.markdown("<div class='sidebar-header'>📘 課本、習作上傳 (可多選)</div>", unsafe_allow_html=True)
        uploaded_refs = st.file_uploader("選擇課本或習作 PDF", type=['pdf'], key="ref", accept_multiple_files=True, label_visibility="collapsed")
        
        # 3. 考試範圍 (保留，方便AI判斷)
        st.markdown("<div class='sidebar-header'>📖 考試範圍</div>", unsafe_allow_html=True)
        exam_scope = st.text_input("輸入範圍", placeholder="如：康軒版 第3-4單元", label_visibility="collapsed")
        
        # 啟動按鈕
        st.markdown("<br>", unsafe_allow_html=True)
        start_btn = st.button("🚀 AI 教授審題", type="primary", use_container_width=True)
        
        if st.button("登出系統"):
            st.session_state['logged_in'] = False
            st.rerun()

    # --- 主畫面 ---
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<h1>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)

    # 執行邏輯
    if start_btn:
        if not uploaded_exam:
            st.warning("⚠️ 請先在左側上傳試卷 PDF")
        else:
            # 審查程度強制設為 "嚴格"
            strictness = "嚴格"
            report, word_data, meta = process_review_logic(
                uploaded_exam, uploaded_refs, strictness, exam_scope
            )
            st.session_state['ai_report'] = report
            st.session_state['word_file'] = word_data
            st.session_state['exam_meta'] = meta

    # 結果顯示區
    if st.session_state['ai_report']:
        st.markdown("---")
        st.subheader("📊 審題報告預覽")
        st.download_button(
            label="📥 下載 Word 報告 (.docx)",
            data=st.session_state['word_file'],
            file_name=f"{st.session_state['exam_meta']['grade']}{st.session_state['exam_meta']['subject']}_審題報告.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )
        st.info(st.session_state['ai_report'])

# --- 核心邏輯 (V12.1 嚴格Prompt修正版) ---
def process_review_logic(exam_file, local_ref_files, strictness, exam_scope):
    with st.container():
        status = st.status("🔍 AI 教授正在審題中...", expanded=True)
        try:
            status.write("📄 讀取並分析試卷內容...")
            exam_text = extract_pdf_text(exam_file)
            
            # 自動偵測試卷資訊
            exam_meta = extract_exam_meta_enhanced(exam_text)
            status.write(f"✅ 試卷識別：{exam_meta['info_str']}")
            
            ref_text = ""
            ref_source_list = []
            scenario_msg = ""
            ref_block = ""

            # --- 核心判斷邏輯 ---
            if local_ref_files:
                # 情境 A：使用者有上傳課本/習作
                status.write(f"📘 使用者已上傳 {len(local_ref_files)} 份教材，以使用者檔案為準。")
                for f in local_ref_files: 
                    ref_text += extract_pdf_text(f) + "\n"
                    ref_source_list.append(f"上傳：{f.name}")
                
                ref_block = f"【比對基準 (使用者上傳)】：\n{ref_text[:60000]}\n"
                scenario_msg = "請以【比對基準】為絕對標準，檢查試卷是否超綱。"
                
            else:
                # 情境 B：無上傳，啟動自動撈取機制 (只搜科目)
                detected_grade = exam_meta.get('grade', '')
                detected_subject = exam_meta.get('subject', '')
                
                if "未偵測" in detected_grade or "未偵測" in detected_subject:
                    status.warning("⚠️ 無法自動識別年級或科目，將改用通用課綱標準審查。")
                    ref_block = "【比對基準】：未找到特定教材，請依據台灣教育部 108 課綱標準審查。\n"
                    scenario_msg = "請依據台灣教育部 108 課綱之該年級/科目標準進行審查。"
                else:
                    status.write(f"☁️ 啟動雲端比對：正在搜尋【{detected_subject}】領域課綱...")
                    
                    # 搜尋 Google Drive (只搜科目)
                    drive_files = []
                    folder_id = st.secrets.get("google_drive_folder_id")
                    if folder_id:
                        all_files = get_drive_files(folder_id)
                        # 邏輯修正 V12：只比對「科目」
                        matched_files = [f for f in all_files if detected_subject in f['name']]
                        
                        if matched_files:
                            status.write(f"✅ 找到 {len(matched_files)} 份【{detected_subject}】領域檔案，正在提取【{detected_grade}】內容...")
                            for f in matched_files:
                                f_stream = download_drive_file(f['id'])
                                if f_stream:
                                    ref_text += extract_pdf_text(f_stream) + "\n"
                                    ref_source_list.append(f"雲端：{f['name']}")
                            
                            ref_block = f"【比對基準 (雲端資料庫)】：\n{ref_text[:60000]}\n"
                            # 關鍵 Prompt 修正：命令 AI 在檔案中找特定年級
                            scenario_msg = f"請務必先閱讀【比對基準】檔案，並在其中搜尋對應【{detected_grade}】的「學習表現」與「學習內容」，以此為絕對標準檢查試卷。"
                        else:
                            status.warning(f"📭 資料庫中未找到 {detected_subject} 的檔案，改用通用標準。")
                            ref_block = "【比對基準】：未提供 (資料庫無對應檔)\n"
                            scenario_msg = f"請依據台灣教育部 108 課綱之【{detected_grade}】【{detected_subject}】標準進行審查。"

            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
            status.write("🧠 Gemini 3.0 Pro 正在進行深度比對...")
            
            # --- V12.1 嚴格格式化 Prompt ---
            prompt = f"""
# Role: 台灣國小教育評量暨素養導向命題專家

# 角色定義
你是一位精通「台灣教育部 108 課綱」與各版本教科書的資深教材審題專家。你的任務是審查使用者上傳的試卷，確保其符合教學進度、邏輯嚴謹，且具備真實的素養評量功能。

## 1. 任務目標
針對上傳的試卷進行專業審題，產出一份符合 Markdown 格式的審查報告。
**試卷資訊：** {exam_meta['info_str']}
**考試範圍：** {exam_scope if exam_scope else "未指定"}
**審查嚴格度：** {strictness}

## 2. 審查基準 (Ground Truth)
{scenario_msg}

## 3. 輸出規範 (Strict Output Rules)
你必須嚴格遵守以下輸出規則，否則任務失敗：
1. **例外報告 (Exception Reporting)**：在 Step 1 和 Step 2，**僅列出有問題** (❌超綱、⚠️疑義) 的題目。
   - ⛔ **若該大項無任何問題，請直接輸出單行文字：「✅ 本大項全數通過，無異常試題。」**
   - ⛔ **嚴禁**在無問題時繪製空表格或列出「通過」的題目。
2. **格式要求**：
   - 必須使用 Markdown 語法。
   - 不要使用 Code Block (```) 包覆報告。
   - 標題層級清楚 (###)。

## 4. 審查流程 (Analysis Workflow)
請依序填寫以下報告內容：

### Step 1: 【命題範圍與合規性檢核】 (Scope & Compliance)
**[資料來源判定邏輯]**
請依照以下**優先順序**決定審查基準：
1.  **優先 (User Upload)**：若 `[使用者上傳教材]` 區塊有內容，以此為「唯一真理」進行比對。
2.  **次要 (Database Fallback)**：若使用者未上傳，讀取 `[資料庫課綱基準]` 區塊。
    * **解析與比對**：確認題目是否符合該年級/科目的「學習內容」與「學習表現」。

**[檢核重點]**
* **超綱判斷**：題目概念是否超出上述基準？
* **課綱對應**：題目是否符合該領域的學習表現。
* **輸出內容**：僅列出違規題目。若全數符合，請依「例外報告」規則處理。

### Step 2: 【題幹與邏輯品質審查】 (Logic & Quality)
* **邏輯封閉性**：單選題是否僅有唯一正解？選項間是否互斥？
* **語意清晰度**：是否存在雙重否定、語意歧義或條件不足。
* **誘答項檢核**：錯誤選項是否具備合理的誘答力。
* **輸出內容**：僅列出有瑕疵題目。若全數符合，請依「例外報告」規則處理。

### Step 3: 【素養導向深度審查】
請依據科目類別，執行「真偽素養」辨識（生活課程請依內容屬性併入自然或社會判斷）：

* **國語文**：
    * ✅ **真素養**：需運用預測、推論、摘要策略；含連續/非連續文本。
    * ⚠️ **假素養**：僅圈錯字或直接摘錄句子，未涉及層次思考。
* **數學**：
    * ✅ **真素養**：具備「數學建模」過程；情境數據符合現實邏輯。
    * ⚠️ **假素養**：情境與算式無關（裝飾性）；數據違背常理。
* **自然科學** (含生活-觀察體驗)：
    * ✅ **真素養**：評量觀察、假設、實驗設計或數據解釋。
    * ⚠️ **假素養**：答案可直接從文中複製，無需先備知識。
* **社會** (含生活-人際環境)：
    * ✅ **真素養**：評量多重觀點、史料判讀或社會參與。
    * ⚠️ **假素養**：僅考碎片化記憶，缺乏因果分析。
* **英語文**：
    * ✅ **真素養**：符合真實語用 (Pragmatics)，模擬真實溝通。
    * ⚠️ **假素養**：對話生硬，僅為考文法規則而堆砌。

* **輸出內容**：列出具代表性的「✅ 真素養題」與「⚠️ 假素養題」並給予簡評。

### Step 4: 【雙向細目表核算】
請務必繪製 Markdown 表格：
| 單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造 |
|---|---|---|---|---|---|---|
| (填入) | (填題號) | ... | ... | ... | ... | ... |
| **分數比重** | % | % | % | % | % | % |
*(注意：分數比重加總須為 100%)*

### Step 5: 【難易度與負擔分析】
* **無效難度檢查**：標註「計算過度繁瑣」但觀念簡單的題目。
* **成績分佈預測**：依據題目難度 (L1易/L2中/L3難) 預測三種分數區間的學生表現。

### Step 6: 【總結與建議】
* 針對紅色警示 (❌) 的題目提出具體修改建議。
* 給予命題教師 3-5 點總體優化建議。

---
{ref_block}

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
    if st.session_state['logged_in']: main_app()
    else: login_page()
