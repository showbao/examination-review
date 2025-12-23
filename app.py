import streamlit as st
import google.generativeai as genai
from io import BytesIO
import re
import os
import requests
import shutil

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

# 自訂 CSS
st.markdown("""
    <style>
    .stApp { background-color: #f0f2f6; }
    .block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }
    
    /* 登入頁樣式 */
    .login-spacer { height: 5vh; }
    input[type="password"] { border: 2px solid #2563eb !important; border-radius: 8px !important; padding: 10px !important; }
    
    /* 卡片優化 */
    div[data-testid="stInfo"] {
        background-color: white; border: none; border-left: 6px solid #4CAF50;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); color: #333; padding: 1.5rem; border-radius: 12px;
    }
    div[data-testid="stError"] {
        background-color: white; border: none; border-left: 6px solid #FF5252;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); color: #333; padding: 1.5rem; border-radius: 12px;
    }

    /* 上傳區視覺整合 */
    .upload-card-header {
        background-color: white; padding: 1.5rem 1.5rem 0.5rem 1.5rem;
        border-radius: 12px 12px 0 0; border-top: 5px solid #2196F3; margin-bottom: 0px !important;
    }
    .upload-card-header-green { border-top: 5px solid #4CAF50; }
    div[data-testid="stFileUploader"] {
        background-color: white; padding: 0 1.5rem 1.5rem 1.5rem;
        border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); margin-top: -16px;
    }
    section[data-testid="stFileUploader"] > div { padding-top: 0px; }

    h1 { color: #1e3a8a; font-weight: 800; font-size: 2rem; }
    h2, h3 { color: #2c3e50; font-weight: 600; }
    
    .stButton>button { 
        width: 100%; border-radius: 8px; font-weight: 700; height: 3.5em; 
        background-color: #2563eb; color: white; box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2); margin-top: 10px;
    }
    .stButton>button:hover { background-color: #1d4ed8; }
    
    .disclaimer-box {
        background-color: #fff3cd; border: 1px solid #ffeeba; color: #856404;
        padding: 15px; border-radius: 8px; font-size: 0.9rem; line-height: 1.6;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .disclaimer-title { font-weight: bold; margin-bottom: 5px; font-size: 1rem; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. 字型下載與註冊 (穩定版：單一字型策略) ---
@st.cache_resource
def setup_chinese_fonts():
    """下載並註冊中文字型 (使用單一字型檔避免粗體缺失錯誤)"""
    font_dir = "fonts"
    if not os.path.exists(font_dir):
        os.makedirs(font_dir)
    
    # 使用 Google Noto Serif TC (Regular)
    # 備用連結：如果 Google 連結失敗，可更換為其他 CDN
    font_url = "https://github.com/google/fonts/raw/main/ofl/notoseriftc/NotoSerifTC-Regular.ttf"
    font_path = os.path.join(font_dir, "NotoSerifTC-Regular.ttf")
    
    # 下載字型
    if not os.path.exists(font_path):
        try:
            with requests.get(font_url, stream=True, timeout=10) as r:
                r.raise_for_status()
                with open(font_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
        except Exception as e:
            st.warning(f"⚠️ 字型下載失敗，PDF 可能無法正確顯示中文。({e})")
            return False

    # 註冊字型 (關鍵修正：將粗體也指向同一個檔案，防止 crash)
    try:
        pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
        # 【重要】這裡將 Bold 也註冊為同一個檔案，解決 "Can't map determine family" 錯誤
        pdfmetrics.registerFont(TTFont('ChineseFont-Bold', font_path)) 
        return True
    except Exception as e:
        st.error(f"字型註冊失敗: {e}")
        return False

# 初始化字型
has_font = setup_chinese_fonts()

# --- 2. PDF 生成引擎 ---
def create_pdf_report(ai_content, exam_meta):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm, 
        topMargin=2*cm, bottomMargin=2*cm
    )
    
    styles = getSampleStyleSheet()
    
    # 檢查字型是否載入成功，若失敗則退回預設 (可能會亂碼，但不會當機)
    font_name = 'ChineseFont' if has_font else 'Helvetica'
    font_name_bold = 'ChineseFont-Bold' if has_font else 'Helvetica-Bold'
    
    # 定義樣式
    style_normal = ParagraphStyle(
        'ChineseNormal', 
        parent=styles['Normal'], 
        fontName=font_name, 
        fontSize=11, 
        leading=16,
        spaceAfter=6
    )
    style_title = ParagraphStyle(
        'ChineseTitle', 
        parent=styles['Heading1'], 
        fontName=font_name_bold, # 這裡現在安全了
        fontSize=20, 
        leading=24, 
        alignment=1, # Center
        spaceAfter=20,
        textColor=colors.HexColor("#1e3a8a")
    )
    style_heading = ParagraphStyle(
        'ChineseHeading', 
        parent=styles['Heading2'], 
        fontName=font_name_bold, 
        fontSize=14, 
        leading=18, 
        spaceBefore=15, 
        spaceAfter=10,
        textColor=colors.HexColor("#2c3e50")
    )

    story = []

    # --- A. 檔頭 ---
    story.append(Paragraph("台中市北屯區建功國小 試卷審題報告", style_title))
    
    header_data = [
        ["試卷資訊", exam_meta['info_str']],
        ["命題教師", "____________________", "審題教師", "____________________"],
        ["審查日期", exam_meta['date_str'], "審查系統", "Gemini 3.0 Pro AI"]
    ]
    
    t_header = Table(header_data, colWidths=[2.5*cm, 6*cm, 2.5*cm, 6*cm])
    t_header.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), font_name),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke), # 第一欄背景
        ('BACKGROUND', (2,1), (2,-1), colors.whitesmoke), # 第三欄背景
        ('SPAN', (1,0), (3,0)),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 1*cm))

    # --- B. 內容解析 ---
    lines = ai_content.split('\n')
    in_table = False
    table_data = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # 標題偵測
        if line.startswith('###') or line.startswith('##'):
            clean_text = line.replace('#', '').strip()
            story.append(Paragraph(clean_text, style_heading))
            
        # 表格偵測
        elif line.startswith('|'):
            if not in_table:
                in_table = True
                table_data = []
            
            cells = [cell.strip() for cell in line.split('|') if cell]
            if '---' in cells[0]: continue # 跳過分隔線
            table_data.append(cells)
            
        else:
            # 輸出之前的表格
            if in_table and table_data:
                try:
                    col_count = len(table_data[0])
                    # 避免空表格錯誤
                    if col_count > 0:
                        t = Table(table_data, colWidths=[17*cm/col_count]*col_count)
                        t.setStyle(TableStyle([
                            ('FONTNAME', (0,0), (-1,-1), font_name),
                            ('FONTSIZE', (0,0), (-1,-1), 9),
                            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                        ]))
                        story.append(t)
                        story.append(Spacer(1, 0.5*cm))
                except:
                    pass # 表格解析失敗則跳過，避免 crash
                in_table = False
                table_data = []
            
            # 處理文字樣式
            formatted_line = line.replace('**', '<b>').replace('**', '</b>')
            if '❌' in formatted_line or '⚠️' in formatted_line:
                formatted_line = f'<font color="red">{formatted_line}</font>'
            
            story.append(Paragraph(formatted_line, style_normal))

    # 收尾表格
    if in_table and table_data:
        try:
            col_count = len(table_data[0])
            if col_count > 0:
                t = Table(table_data, colWidths=[17*cm/col_count]*col_count)
                t.setStyle(TableStyle([
                    ('FONTNAME', (0,0), (-1,-1), font_name),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                    ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ]))
                story.append(t)
        except: pass

    doc.build(story)
    buffer.seek(0)
    return buffer

# --- 3. 試卷資訊擷取 ---
def extract_exam_meta(text, grade, subject):
    import datetime
    today = datetime.date.today().strftime("%Y/%m/%d")
    
    meta = {
        "year": "113學年度", "semester": "下學期", "exam_name": "定期評量",
        "grade": grade, "subject": subject, "date_str": today
    }
    
    sample = text[:800]
    match_year = re.search(r'(\d{3})\s*學年度', sample)
    if match_year: meta['year'] = f"{match_year.group(1)}學年度"
    match_sem = re.search(r'(上|下)\s*學期', sample)
    if match_sem: meta['semester'] = f"{match_sem.group(1)}學期"
    match_exam = re.search(r'(期中|期末|第[一二三]次|定期)評量', sample)
    if match_exam: meta['exam_name'] = match_exam.group(0)
    elif "期末" in sample: meta['exam_name'] = "期末評量"
    elif "期中" in sample: meta['exam_name'] = "期中評量"
    
    meta['info_str'] = f"{meta['year']} {meta['semester']} {meta['grade']} {meta['subject']} {meta['exam_name']}"
    return meta

# --- 4. 輔助函數 ---
def extract_pdf_text(file):
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages: text += page.extract_text() + "\n"
        return text
    except: return ""

# --- 5. 登入頁 ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='login-spacer'></div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("<h2 style='text-align: center; color: #1e3a8a; margin-bottom: 30px;'>🔐 建功國小智慧審題系統</h2>", unsafe_allow_html=True)
            st.markdown("""
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
            st.markdown("<br>", unsafe_allow_html=True)
            password = st.text_input("請輸入校內授權密碼", type="password", placeholder="請在此輸入密碼...")
            if st.button("我同意以上聲明並登入"):
                if password == st.secrets.get("LOGIN_PASSWORD", "school123"):
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")

# --- 6. 主程式 ---
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

    st.markdown("<h1 style='text-align: center; margin-bottom: 20px;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    if st.sidebar.state == "collapsed": st.warning("👈 **老師請注意：請先點擊左上角「>」展開設定年級與科目！**")

    st.markdown("<h3 style='margin-top: 20px;'>📂 資料上傳區</h3>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <div class='upload-card-header'>
            <b>📄 1. 上傳試卷 (必要)</b><br>
            <small style='color:gray;'>檔案大小上限為 100MB</small>
        </div>
        """, unsafe_allow_html=True)
        uploaded_exam = st.file_uploader("上傳試卷", type=['pdf'], key="exam", label_visibility="collapsed")
    
    with col2:
        st.markdown(f"""
        <div class='upload-card-header upload-card-header-green'>
            <b>📘 2. 上傳 {grade}{subject} 課本/習作 (選填)</b><br>
            <small style='color:gray;'>如上傳可使用 AI 精準比對，未上傳則依據 108 課綱比對。</small>
        </div>
        """, unsafe_allow_html=True)
        uploaded_refs = st.file_uploader("上傳教材", type=['pdf'], key="ref", accept_multiple_files=True, label_visibility="collapsed")

    st.markdown("<br>", unsafe_allow_html=True)

    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題 (生成 PDF 報告)", type="primary"):
            process_review(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope)

def process_review(exam_file, ref_files, grade, subject, strictness, exam_scope):
    with st.container():
        status = st.status("🔍 AI 專家啟動中...", expanded=True)
        try:
            # A. 讀取
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

            # B. AI
            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
            status.write("🧠 Gemini 3.0 Pro 正在執行雙向細目表分析...")
            
            prompt = f"""
            # Role: 台灣國小教育評量專家
            
            ## 任務
            請針對 {grade}{subject} 試卷進行審查。
            範圍：{exam_scope if exam_scope else "未指定"}
            嚴格度：{strictness}
            資料基準：{scenario_prompt}
            
            ## 參考資料
            {ref_text[:30000]}
            
            ## 試卷內容
            {exam_text[:20000]}
            
            ## 輸出指令
            請輸出專業審題報告，務必包含以下章節 (使用 Markdown)：
            
            1. **Step 1: 命題範圍檢核**
            2. **Step 2: 題幹與邏輯品質審查**
            3. **Step 3: 雙向細目表** (務必繪製 Markdown 表格：單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造)
            4. **Step 4: 難易度分析**
            5. **Step 5: 素養導向審查**
            6. **【修改具體建議 (Action Plan)】** (列出 3-5 點具體建議，若有嚴重問題請用 ❌ 標示)
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            # C. PDF
            status.write("📝 排版 PDF 正式報告...")
            pdf_file = create_pdf_report(ai_report, exam_meta)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            # D. 結果
            st.subheader("📊 審題報告預覽")
            st.download_button(
                label="📥 下載 PDF 正式報告 (含簽核欄)",
                data=pdf_file,
                file_name=f"{exam_meta['grade']}{exam_meta['subject']}_審題報告.pdf",
                mime="application/pdf",
                type="primary"
            )
            
            # 卡片預覽
            sections = re.split(r'(Step \d:|【修改具體建議)', ai_report)
            current_text = ""
            for part in sections:
                if re.match(r'(Step \d:|【修改具體建議)', part):
                    if current_text.strip(): display_card(current_text)
                    current_text = "### " + part
                else:
                    current_text += part
            if current_text.strip(): display_card(current_text)

        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "429" in str(e): st.warning("⚠️ 配額已滿，請稍後再試。")

def display_card(text):
    has_warning = "❌" in text or "⚠️" in text
    if has_warning: st.error(text, icon="⚠️")
    else: st.info(text, icon="✅")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()
