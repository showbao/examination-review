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
    page_title="臺中市北屯區建功國小試卷智慧審題系統",
    page_icon="🎓",
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
    /* 優化表格顯示 */
    table { width: 100%; }
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
    
    # --- 側邊欄 ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 審題參數設定")
        st.markdown("---")
        
        # A. 選擇模型
        st.subheader("A. 選擇模型")
        model_choice = st.selectbox(
            "AI 大腦版本",
            ["Gemini 2.5 Pro (最新付費版)", "Gemini 2.0 Flash (快速免費版)", "Gemini 3.0 Pro (預覽旗艦版)"],
            index=0
        )
        st.caption("💡 建議使用 2.5 Pro 或 3.0 Pro 以獲得最佳的邏輯推演能力。")
        
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
            placeholder="例如：康軒版 第3-4單元",
            help="AI 將依此範圍檢查是否超綱"
        )
        
        # F. 嚴格程度
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
        if uploaded_exam and uploaded_exam.size > 10 * 1024 * 1024:
            st.error("⚠️ 檔案過大，請上傳 10MB 以下的檔案。")
            st.stop()
    
    with col2:
        st.success(f"📘 **2. 上傳 {grade}{subject} 課本/習作 (選填)**")
        uploaded_refs = st.file_uploader(
            "供 AI 比對範圍 (可多選)", 
            type=['pdf'], 
            key="ref", 
            accept_multiple_files=True 
        )
        # 動態提示文字
        ref_status_msg = "情境 A：以您上傳的課本為標準" if uploaded_refs else "情境 B：啟動 108 課綱知識庫"
        st.caption(f"💡 目前模式：**{ref_status_msg}**")
        
    st.markdown("</div>", unsafe_allow_html=True)

    # 執行按鈕
    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題", type="primary"):
            process_review(uploaded_exam, uploaded_refs, model_choice, grade, subject, strictness, exam_scope)

# --- 4. 核心邏輯 (專家版 Prompt) ---
def process_review(exam_file, ref_files, model_choice, grade, subject, strictness, exam_scope):
    
    with st.container():
        st.markdown("<div class='card-container'>", unsafe_allow_html=True)
        st.subheader("📊 108課綱 專家分析報告")
        status = st.status("🔍 AI 專家啟動中...", expanded=True)
        
        try:
            # 設定 API Key
            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            
            model_map = {
                "Gemini 2.5 Pro (最新付費版)": "models/gemini-2.5-pro",
                "Gemini 2.0 Flash (快速免費版)": "models/gemini-2.0-flash",
                "Gemini 3.0 Pro (預覽旗艦版)": "models/gemini-3-pro-preview"
            }
            model = genai.GenerativeModel(model_map[model_choice])
            
            # 讀取試卷
            status.write("📄 正在分析試卷結構...")
            exam_text = extract_pdf_text(exam_file)
            
            # 讀取參考教材 & 決定情境
            ref_prompt = ""
            scenario_prompt = ""
            
            if ref_files:
                status.write(f"📘 正在分析 {len(ref_files)} 份教材，建立比對基準...")
                ref_text = ""
                for f in ref_files:
                    ref_text += extract_pdf_text(f) + "\n"
                
                # 設定為情境 A
                scenario_prompt = f"""
                * **情境 A (使用者有上傳教材)：**
                * **基準：** 請嚴格以本提示詞下方提供的【參考教材內容】為絕對標準。
                * **動作：** 檢查試卷題目是否超出這些教材的教學範圍。
                
                【參考教材內容】：
                {ref_text[:60000]}
                """
            else:
                # 設定為情境 B
                status.write("📚 未偵測到教材，正在調用「教育部 108 課綱」知識庫...")
                scenario_prompt = f"""
                * **情境 B (使用者未上傳教材)：**
                * **基準：** 請啟動你內建的知識庫，調用「台灣教育部 108 課綱」中【{subject}】領域、【{grade}】的「學習內容」與「學習表現」。
                * **動作：** 以課綱條目為標準，判斷試卷是否符合該年段的學習目標。
                """

            # 組合終極 Prompt (融合您的專家邏輯)
            status.write(f"🧠 {model_choice} 正在執行雙向細目表核算與素養檢測...")
            
            prompt = f"""
            # Role: 台灣國小教育評量審查專家 (Taiwan Elementary Education Assessment Expert)

            ## 1. 任務目標
            你是一位精通台灣教育部「108課綱」與測驗編製理論的專家。請針對使用者上傳的「試卷檔案」，進行全面性的審題與品質分析。
            
            本次審查資訊：
            * **年級：** {grade}
            * **科目：** {subject}
            * **版本/範圍：** {exam_scope if exam_scope else "未指定"}
            * **審查嚴格度：** {strictness}

            ## 2. 輸入資料處理規則 (Data Handling Logic)
            依據使用者上傳狀態，請執行以下情境邏輯：
            {scenario_prompt}

            ## 3. 前置檢查：課綱對應性 (Curriculum Alignment Check)
            * 請讀取試卷內容，嚴格核對 {grade}{subject} 在 108 課綱中的規範。
            * 若發現試卷內容明顯屬於高年級課程（例如小三數學出現代數符號），請立即標註警告。

            ## 4. 試卷分析流程 (Analysis Workflow) - 請依序產出以下章節：

            ### Step 1: 【命題範圍檢核】 (Scope Check)
            * 檢查試題是否「超綱」。
            * 若是情境 A，指出哪一題超出教材範圍；若是情境 B，指出哪一題超出 108 課綱該年段的學習內容。

            ### Step 2: 【雙向細目表核算】 (Two-Way Specification Table)
            **請務必繪製 Markdown 表格**，欄位包含：
            * 題號
            * 對應單元/概念
            * 認知目標層次（請依據 Bloom 分類法判定：記憶、了解、應用、分析、評鑑、創造）
            * 該題配分
            * **統計總結：** 請在表後計算整張試卷在各認知層次的配分百分比（例如：記憶 30%, 應用 40%...）。

            ### Step 3: 【難易度與成績分佈預測】 (Difficulty Analysis)
            * **變形度分析：** 題目是「直球對決」(基本題) 還是「高度變形」(需多層轉折)？
            * **成績預測：** 基於題目難度分佈，預測成績曲線（例如：常態分佈、左偏、右偏）。

            ### Step 4: 【素養導向審查】 (Competency-Based Assessment)
            * 計算「素養題」的題數與配分佔比。
            * **嚴格抓漏：** 審查素養題是否為「真素養」（真實情境）或是「假包裝」（僅套用人名但仍考死背）。

            ### Step 5: 【題幹與邏輯品質審查】 (Quality Control)
            * **定義一致性：** 專有名詞、符號是否與課本/課綱一致？
            * **誘答項合理性：** 選擇題的錯誤選項是否具備誘答力？有無邏輯漏洞？

            ## 5. 輸出產出 (Final Output)
            請彙整以上分析，提供一份結構清晰的「試卷審查總結報告」，並包含具體的「修改建議」。

            ---
            【試卷原始內容】：
            {exam_text[:25000]}
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            # 產生 Word
            status.write("📝 正在製作專家審查報告...")
            bio = generate_word_report(ai_report, model_choice, grade, subject, exam_scope)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"<div style='background:#f0f2f6;padding:15px;border-radius:10px;'>{ai_report}</div>", unsafe_allow_html=True)
            with col2:
                st.download_button(
                    label="📥 下載 Word 報告",
                    data=bio.getvalue(),
                    file_name=f"{grade}{subject}_專家審題報告.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary"
                )

        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "404" in str(e):
                st.warning("⚠️ 模型找不到，可能是您的帳號權限變動。請嘗試切換至 Flash 模型。")
            elif "429" in str(e):
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
    doc.add_heading(f'{grade} {subject} 專家審題報告', 0)
    doc.add_paragraph(f"範圍：{scope}")
    doc.add_paragraph(f"模型：{model}")
    doc.add_paragraph("-" * 30)
    # 因為細目表通常有 Markdown 表格，直接寫入 Word 格式可能跑掉，這裡維持純文字寫入
    # 如果未來需要 Word 內建表格，需使用更複雜的 Markdown 解析器
    doc.add_paragraph(text)
    bio = BytesIO()
    doc.save(bio)
    return bio

if __name__ == "__main__":
    if st.session_state['logged_in']:
        main_app()
    else:
        login_page()
