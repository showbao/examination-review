import streamlit as st
import google.generativeai as genai
from io import BytesIO
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

# 嘗試匯入 PDF 套件
try:
    from pypdf import PdfReader
except ImportError:
    import PyPDF2 as PdfReader

# --- 0. 全局設定與 CSS 美化 ---
st.set_page_config(
    page_title="國小試卷智慧審題系統 V3.2",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 自訂 CSS
st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; }
    .card-container {
        background-color: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 2rem;
    }
    h1, h2, h3 { color: #2c3e50; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: 600; }
    .disclaimer { font-size: 0.8rem; color: #7f8c8d; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. Session State 管理 ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

# --- 2. 登入頁面 ---
def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='card-container'>", unsafe_allow_html=True)
        st.title("🔐 試卷審題系統登入")
        st.markdown("---")
        st.warning("⚠️ **免責聲明**：本系統由 AI 輔助，結果僅供參考。請勿上傳機密個資。")
        st.markdown("---")
        
        password = st.text_input("請輸入授權密碼", type="password")
        if st.button("同意聲明並登入"):
            # 從 Secrets 讀取密碼 (若未設定則預設 school123)
            secret_pass = st.secrets.get("LOGIN_PASSWORD", "school123")
            if password == secret_pass:
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤")
        st.markdown("</div>", unsafe_allow_html=True)

# --- 3. 主應用程式 ---
def main_app():
    # 強制展開側邊欄
    st.markdown("""<style>[data-testid="collapsedControl"] {display: none}</style>""", unsafe_allow_html=True)
    
    # --- 側邊欄：依照您的順位編排 ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 審題參數設定")
        st.markdown("---")
        
        # A. 選擇模型
        st.subheader("A. 選擇模型")
        model_choice = st.selectbox(
            "AI 大腦版本",
            ["Gemini 1.5 Pro (付費穩定版)", "Gemini 2.0 Flash (快速免費版)", "Gemini 3.0 Pro (預覽旗艦版)"],
            index=0
        )
        
        # B. 選擇年級
        st.subheader("B. 選擇年級")
        grade = st.selectbox(
            "適用對象",
            ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"]
        )
        
        # C. 選擇科目
        st.subheader("C. 選擇科目")
        subject = st.selectbox(
            "測驗科目",
            ["國語", "數學", "英語", "自然", "社會", "生活"]
        )
        
        # D. 考試範圍
        st.subheader("D. 考試範圍")
        exam_scope = st.text_input(
            "輸入單元或頁數",
            placeholder="例如：第1單元～第3單元",
            help="AI 將依此範圍檢查是否超綱"
        )
        
        # F. 嚴格程度 (跳過 E)
        st.subheader("F. 嚴格程度")
        strictness = st.select_slider(
            "AI 審查力道",
            options=["溫柔 (鼓勵)", "標準", "嚴格 (高標)", "魔鬼 (找碴)"],
            value="嚴格 (高標)"
        )
        
        st.markdown("---")
        if st.button("登出系統"):
            st.session_state['logged_in'] = False
            st.rerun()

    # --- 主畫面 ---
    st.title(f"🏫 {subject}試卷智慧審題 ({grade})")
    
    st.markdown("<div class='card-container'>", unsafe_allow_html=True)
    st.subheader("📁 資料上傳區")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("📄 **1. 上傳試卷 (必要)**")
        uploaded_exam = st.file_uploader("請拖曳試卷 PDF", type=['pdf'], key="exam")
        # 檔案大小檢查 (10MB)
        if uploaded_exam and uploaded_exam.size > 10 * 1024 * 1024:
            st.error("⚠️ 檔案過大，請上傳 10MB 以下的檔案。")
            st.stop()
    
    with col2:
        # 動態標題：讓老師知道該傳哪個年級科目的課本
        st.success(f"📘 **2. 上傳 {grade}{subject} 課本/習作 (選填)**")
        uploaded_refs = st.file_uploader(
            "供 AI 比對範圍 (可多選)", 
            type=['pdf'], 
            key="ref", 
            accept_multiple_files=True 
        )
        st.caption(f"💡 AI 將依據此教材，檢查題目是否超出 **{exam_scope if exam_scope else '全冊'}** 範圍。")
        
    st.markdown("</div>", unsafe_allow_html=True)

    # 執行按鈕
    if uploaded_exam:
        if st.button("🚀 啟動 AI 審題", type="primary"):
            process_review(uploaded_exam, uploaded_refs, model_choice, grade, subject, strictness, exam_scope)

# --- 4. 核心邏輯 ---
def process_review(exam_file, ref_files, model_choice, grade, subject, strictness, exam_scope):
    
    with st.container():
        st.markdown("<div class='card-container'>", unsafe_allow_html=True)
        st.subheader("📊 分析報告")
        status = st.status("🔍 AI 助教啟動中...", expanded=True)
        
        try:
            # 設定 API Key
            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            
            model_map = {
                "Gemini 1.5 Pro (付費穩定版)": "models/gemini-1.5-pro",
                "Gemini 2.0 Flash (快速免費版)": "models/gemini-2.0-flash",
                "Gemini 3.0 Pro (預覽旗艦版)": "models/gemini-3-pro-preview"
            }
            model = genai.GenerativeModel(model_map[model_choice])
            
            # 讀取試卷
            status.write("📄 正在讀取試卷...")
            exam_text = extract_pdf_text(exam_file)
            
            # 讀取參考教材
            ref_prompt = ""
            if ref_files:
                status.write(f"📘 正在分析 {len(ref_files)} 份參考教材...")
                ref_text = ""
                for f in ref_files:
                    ref_text += extract_pdf_text(f) + "\n"
                
                ref_prompt = f"""
                【參考教材內容 (課本/習作)】：
                {ref_text[:60000]} 
                
                【本次考試範圍】：{exam_scope if exam_scope else "未指定 (請參考全部教材)"}
                (請嚴格比對：題目是否超出上述範圍？)
                """
            else:
                ref_prompt = "【參考教材】：未提供 (請依據該年級課綱常識判斷)"

            # 組合 Prompt
            status.write(f"🧠 {model_choice} 正在進行 {grade}{subject} 深度審查...")
            
            prompt = f"""
            你是一位台灣資深國小教師與命題委員。
            任務：審查 **{grade} {subject}** 試卷。
            嚴格度：**{strictness}**。
            考試範圍：**{exam_scope}**。

            請執行以下檢查：
            1. **範圍檢查 (Critical)**：題目是否超出「{exam_scope}」的教學範圍？(若有上傳教材，請嚴格比對)。
            2. **適齡檢查**：文字與題意是否符合 {grade} 學生程度？
            3. **邏輯與排版**：檢查是否有注音錯誤、圖表數據矛盾、選項誘答力不足等問題。

            ---
            {ref_prompt}
            ---
            【試卷內容】：
            {exam_text[:25000]}
            ---
            
            請輸出專業報告 (繁體中文)：
            1. **整體評語** (難易度、範圍符合度)
            2. **❌ 超綱與重大瑕疵** (請列出題號)
            3. **逐題優化建議**
            4. **優點亮點**
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            # 產生 Word
            status.write("📝 排版報告中...")
            bio = generate_word_report(ai_report, model_choice, grade, subject, exam_scope)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"<div style='background:#f0f2f6;padding:15px;border-radius:10px;'>{ai_report}</div>", unsafe_allow_html=True)
            with col2:
                st.download_button(
                    label="📥 下載 Word 報告",
                    data=bio.getvalue(),
                    file_name=f"{grade}{subject}_審題報告.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary"
                )

        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "429" in str(e):
                st.warning("⚠️ 配額已滿，請切換至 Flash 模型。")
        
        st.markdown("</div>", unsafe_allow_html=True)

# --- 輔助函數 ---
def extract_pdf_text(file):
    try:
        reader = PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except:
        return "[PDF 讀取失敗]"

def generate_word_report(text, model, grade, subject, scope):
    doc = Document()
    doc.add_heading(f'{grade} {subject} 審題報告', 0)
    doc.add_paragraph(f"範圍：{scope}")
    doc.add_paragraph(f"模型：{model}")
    doc.add_paragraph("-" * 30)
    doc.add_paragraph(text)
    bio = BytesIO()
    doc.save(bio)
    return bio

if __name__ == "__main__":
    if st.session_state['logged_in']:
        main_app()
    else:
        login_page()
