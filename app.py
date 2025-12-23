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
from reportlab.lib.fonts import addMapping # 【關鍵修正】引入字型對應功能

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
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; }
    
    /* 登入頁樣式 */
    .login-spacer { height: 5vh; }
    input[type="password"] { border: 2px solid #2563eb !important; border-radius: 8px !important; padding: 10px !important; }
    
    /* 卡片優化 */
    div[data-testid="stInfo"], div[data-testid="stError"], .card-box {
        background-color: white; border: none; 
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); 
        color: #333; padding: 1.5rem; border-radius: 12px;
    }
    div[data-testid="stInfo"] { border-left: 6px solid #4CAF50; }
    div[data-testid="stError"] { border-left: 6px solid #FF5252; }

    /* 上傳區簡化 */
    .upload-label { font-size: 1.1rem; font-weight: 700; color: #334155; margin-bottom: 0.5rem; display: block; }
    .upload-sub { font-size: 0.9rem; color: #64748b; margin-bottom: 0.5rem; display: block; }
    
    h1 { color: #1e3a8a; font-weight: 800; font-size: 2rem; }
    h2, h3 { color: #2c3e50; font-weight: 600; }
    
    /* 按鈕美化 */
    .stButton>button { 
        width: 100%; border-radius: 50px !important; font-weight: 700 !important; height: 3.5em !important; 
        background: linear-gradient(90deg, #2563eb, #1d4ed8) !important; color: white !important; 
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3) !important; border: none !important;
        transition: all 0.3s ease !important; font-size: 1.1rem !important;
    }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(37, 99, 235, 0.4) !important; }
    
    .disclaimer-box {
        background-color: #fff3cd; border: 1px solid #ffeeba; color: #856404;
        padding: 15px; border-radius: 8px; font-size: 0.9rem; line-height: 1.6;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .disclaimer-title { font-weight: bold; margin-bottom: 5px; font-size: 1rem; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. 字型註冊 (本地讀取 + 家族對應修復版) ---
@st.cache_resource
def setup_chinese_fonts():
    """直接讀取專案內的字型檔，並建立粗體對應"""
    font_name = "NotoSerifTC-Regular.ttf"
    
    # 檢查檔案是否存在
    if not os.path.exists(font_name):
        st.error(f"⚠️ 找不到字型檔：{font_name}。請確認您已將該檔案上傳至 GitHub 專案根目錄。")
        return False

    try:
        # 1. 註冊實體字型檔
        pdfmetrics.registerFont(TTFont('ChineseFont', font_name))
        pdfmetrics.registerFont(TTFont('ChineseFont-Bold', font_name)) 
        
        # 2. 【關鍵修正】建立字型家族對應 (Mapping)
        # 告訴 ReportLab：當遇到 <b> 標籤時，請使用 ChineseFont-Bold
        addMapping('ChineseFont', 0, 0, 'ChineseFont')    # normal
        addMapping('ChineseFont', 0, 1, 'ChineseFont-Bold') # italic (這裡借用 bold 當 italic 用，避免缺字)
        addMapping('ChineseFont', 1, 0, 'ChineseFont-Bold') # bold
        addMapping('ChineseFont', 1, 1, 'ChineseFont-Bold') # bold italic
        
        return True
    except Exception as e:
        st.error(f"字型註冊失敗: {e}")
        return False

# 初始化字型
has_font = setup_chinese_fonts()

# --- 2. PDF 生成引擎 (修復標籤解析問題) ---
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
    
    style_normal = ParagraphStyle(
        'ChineseNormal', parent=styles['Normal'], fontName=font_name, fontSize=11, leading=16, spaceAfter=6
    )
    style_title = ParagraphStyle(
        'ChineseTitle', parent=styles['Heading1'], fontName=font_name_bold, 
        fontSize=20, leading=24, alignment=1, spaceAfter=20, textColor=colors.HexColor("#1e3a8a")
    )
    style_heading = ParagraphStyle(
        'ChineseHeading', parent=styles['Heading2'], fontName=font_name_bold, 
        fontSize=14, leading=18, spaceBefore=15, spaceAfter=10, textColor=colors.HexColor("#2c3e50")
    )

    story = []

    # A. 檔頭
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
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('BACKGROUND', (2,1), (2,-1), colors.whitesmoke),
        ('SPAN', (1,0), (3,0)),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 1*cm))

    # B. 內容解析
    lines = ai_content.split('\n')
    in_table = False
    table_data = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith('###') or line.startswith('##'):
            clean_text = line.replace('#', '').strip()
            story.append(Paragraph(clean_text, style_heading))
            
        elif line.startswith('|'):
            if not in_table:
                in_table = True
                table_data = []
            cells = [cell.strip() for cell in line.split('|') if cell]
            if '---' in cells[0]: continue
            table_data.append(cells)
            
        else:
            if in_table and table_data:
                try:
                    col_count = len(table_data[0])
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
                except: pass
                in_table = False
                table_data = []
            
            # 【關鍵修正】使用 Regex 正確替換成對的粗體符號
            # 舊寫法: replace('**', '<b>') 會導致標籤不閉合
            # 新寫法: re.sub 確保成對替換
            formatted_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            
            # 處理警示顏色
            if '❌' in formatted_line or '⚠️' in formatted_line:
                formatted_line = f'<font color="red">{formatted_line}</font>'
            
            try:
                story.append(Paragraph(formatted_line, style_normal))
            except Exception:
                # 【防呆機制】如果標籤解析依然失敗（例如內容含有 < > 符號），則清除所有標籤，只顯示純文字
                clean_text = re.sub(r'<[^>]+>', '', formatted_line) 
                story.append(Paragraph(clean_text, style_normal))

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
        st.markdown("<div class='login-spacer'></div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("""
            <div class='card-box'>
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
            if st.button("我同意以上聲明並登入"):
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

    st.markdown("<h1 style='text-align: center; margin-bottom: 20px;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    if st.sidebar.state == "collapsed": st.warning("👈 **老師請注意：請先點擊左上角「>」展開設定年級與科目！**")

    # 資料上傳區
    st.markdown("<h3 style='margin-top: 20px; border-left: 5px solid #2563eb; padding-left: 10px;'>📂 資料上傳區</h3>", unsafe_allow_html=True)
    st.markdown("<hr style='margin-top:0; margin-bottom: 20px;'>", unsafe_allow_html=True)

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
            
            prompt = f"""
            # Role: 台灣國小教育評量專家
            ## 任務
            針對 {grade}{subject} 試卷進行審查。
            範圍：{exam_scope if exam_scope else "未指定"}
            嚴格度：{strictness}
            資料基準：{scenario_prompt}
            ## 參考資料
            {ref_text[:30000]}
            ## 試卷內容
            {exam_text[:20000]}
            ## 輸出指令
            請直接輸出報告內容，使用 Markdown 格式 (含表格)：
            1. **【修改具體建議 (Action Plan)】** (列出 3-5 點具體建議，重大錯誤用 ❌ 標示)
            2. **Step 1: 命題範圍檢核**
            3. **Step 2: 題幹與邏輯品質審查**
            4. **Step 3: 雙向細目表** (表格欄位：單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造)
            5. **Step 4: 難易度分析**
            6. **Step 5: 素養導向審查**
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            status.write("📝 排版 PDF 正式報告...")
            pdf_file = create_pdf_report(ai_report, exam_meta)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
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
