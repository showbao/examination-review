import streamlit as st
import google.generativeai as genai
from io import BytesIO
from docx import Document

# 嘗試匯入 PDF 套件
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

# 自訂 CSS (介面微調核心)
st.markdown("""
    <style>
    /* 1. 全局字體與背景 */
    .stApp { background-color: #f0f2f6; }
    
    /* 2. 登入畫面優化 */
    /* 讓登入卡片往下移一點，不要貼頂 */
    .login-spacer { height: 5vh; }
    
    /* 密碼輸入框加強框線 */
    input[type="password"] {
        border: 2px solid #2563eb !important; /* 藍色框線 */
        border-radius: 8px !important;
        padding: 10px !important;
        background-color: #f8fafc !important;
    }
    
    /* 3. 卡片式風格重構 (針對 st.info / st.error / st.markdown) */
    /* 移除原生 st.info 的背景色，改為白色卡片 */
    div[data-testid="stInfo"] {
        background-color: white;
        border: none;
        border-left: 6px solid #4CAF50; /* 綠色識別線 */
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); /* 增加陰影 */
        color: #333;
        padding: 1.5rem;
        border-radius: 12px;
    }
    /* 警告卡片 */
    div[data-testid="stError"] {
        background-color: white;
        border: none;
        border-left: 6px solid #FF5252; /* 紅色識別線 */
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        color: #333;
        padding: 1.5rem;
        border-radius: 12px;
    }

    /* 4. 上傳區視覺整合 (關鍵 CSS) */
    /* 上半部：標題區 (由 HTML 生成) */
    .upload-card-header {
        background-color: white;
        padding: 1.5rem 1.5rem 0.5rem 1.5rem; /* 下方 padding 減少，接合下半部 */
        border-radius: 12px 12px 0 0; /* 只圓上面兩個角 */
        border-top: 5px solid #2196F3;
        margin-bottom: 0px !important; /* 貼緊下方元件 */
    }
    .upload-card-header-green {
        border-top: 5px solid #4CAF50;
    }

    /* 下半部：Streamlit 上傳元件 (由 st.file_uploader 生成) */
    div[data-testid="stFileUploader"] {
        background-color: white;
        padding: 0 1.5rem 1.5rem 1.5rem; /* 上方 padding 0，接合上半部 */
        border-radius: 0 0 12px 12px; /* 只圓下面兩個角 */
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); /* 統一陰影 */
        margin-top: -16px; /* 負邊距，強制向上吸附標題區 */
    }
    
    /* 微調上傳按鈕區域，讓它看起來像在卡片內 */
    section[data-testid="stFileUploader"] > div {
        padding-top: 0px;
    }

    /* 標題樣式 */
    h1 { color: #1e3a8a; font-weight: 800; letter-spacing: 1px; font-size: 2rem; }
    h2, h3 { color: #2c3e50; font-weight: 600; }
    
    /* 按鈕樣式 */
    .stButton>button { 
        width: 100%; 
        border-radius: 8px; 
        font-weight: 700; 
        height: 3.5em; 
        background-color: #2563eb; 
        color: white;
        box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2);
        margin-top: 10px;
    }
    .stButton>button:hover {
        background-color: #1d4ed8;
    }
    
    /* 免責聲明文字 */
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
    
    /* 隱藏選單 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. Session State 管理 ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

# --- 2. 登入頁面 ---
def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # 增加頂部間距
        st.markdown("<div class='login-spacer'></div>", unsafe_allow_html=True)
        
        # 使用 container 配合 CSS
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
                secret_pass = st.secrets.get("LOGIN_PASSWORD", "school123")
                if password == secret_pass:
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤，請洽詢教務處或資訊組。")

# --- 3. 主應用程式 ---
def main_app():
    # CSS Hack 隱藏側邊欄箭頭
    st.markdown("""<style>[data-testid="collapsedControl"] {display: none}</style>""", unsafe_allow_html=True)
    
    # --- 側邊欄 ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 審題參數設定")
        st.markdown("---")
        
        st.info("👇 請依序完成設定")

        # A. 模型 (鎖定)
        st.subheader("A. AI 大腦版本")
        st.success("🧠 Gemini 3.0 Pro\n(已啟用校內專用旗艦版)")
        
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
    
    # 標題區
    st.markdown("<h1 style='text-align: center; margin-bottom: 20px;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    
    # 1. 顯眼的設定引導提示
    if st.sidebar.state == "collapsed": 
        st.warning("👈 **老師請注意：請先點擊畫面左上角的「>」箭頭，展開設定年級與科目！**")

    # 2. 資料上傳區 (卡片整合版)
    st.markdown("<h3 style='margin-top: 20px;'>📂 資料上傳區</h3>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    # 左側：試卷上傳卡片
    with col1:
        # 上半部：標題與說明 (使用 CSS class upload-card-header)
        st.markdown("""
        <div class='upload-card-header'>
            <b>📄 1. 上傳試卷 (必要)</b><br>
            <small style='color:gray;'>檔案大小上限為 100MB</small>
        </div>
        """, unsafe_allow_html=True)
        # 下半部：上傳元件 (CSS 會自動將其變為卡片下半部，包含檔案列表)
        uploaded_exam = st.file_uploader("上傳試卷", type=['pdf'], key="exam", label_visibility="collapsed")
    
    # 右側：教材上傳卡片
    with col2:
        # 上半部：標題與說明 (綠色頂邊)
        st.markdown(f"""
        <div class='upload-card-header upload-card-header-green'>
            <b>📘 2. 上傳 {grade}{subject} 課本/習作 (選填)</b><br>
            <small style='color:gray;'>如上傳可使用 AI 精準比對，未上傳則依據 108 課綱比對。</small>
        </div>
        """, unsafe_allow_html=True)
        # 下半部：上傳元件
        uploaded_refs = st.file_uploader(
            "上傳教材", 
            type=['pdf'], 
            key="ref", 
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        
    st.markdown("<br>", unsafe_allow_html=True)

    # 執行按鈕
    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題 (Gemini 3.0 Pro)", type="primary"):
            process_review(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope)

# --- 4. 核心邏輯 ---
def process_review(exam_file, ref_files, grade, subject, strictness, exam_scope):
    
    with st.container():
        status = st.status("🔍 AI 專家啟動中...", expanded=True)
        
        try:
            # 設定 API Key
            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            
            # 鎖定模型
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
            # 讀取試卷
            status.write("📄 正在分析試卷結構...")
            exam_text = extract_pdf_text(exam_file)
            
            # 讀取參考教材
            scenario_prompt = ""
            ref_text = ""
            
            if ref_files:
                status.write(f"📘 正在分析 {len(ref_files)} 份教材...")
                for f in ref_files:
                    ref_text += extract_pdf_text(f) + "\n"
                
                scenario_prompt = f"""
                * **情境 A (使用者有上傳教材)：**
                * **基準：** 請嚴格以本提示詞下方提供的【參考教材內容】為絕對標準。
                * **動作：** 檢查試卷題目是否超出這些教材的教學範圍。
                
                【參考教材內容】：
                {ref_text[:60000]}
                """
            else:
                status.write("📚 調用「教育部 108 課綱」知識庫...")
                scenario_prompt = f"""
                * **情境 B (使用者未上傳教材)：**
                * **基準：** 請啟動你內建的知識庫，調用「台灣教育部 108 課綱」中【{subject}】領域、【{grade}】的「學習內容」與「學習表現」。
                * **動作：** 以課綱條目為標準，判斷試卷是否符合該年段的學習目標。
                """

            status.write("🧠 Gemini 3.0 Pro 正在執行深度審查...")
            
            # --- Prompt: Action Plan 移至最底端 ---
            prompt = f"""
            # Role: 台灣國小教育評量暨素養導向命題專家
            
            ## 1. 任務目標
            你是一位精通台灣教育部「108課綱」與測驗編製理論的專家。請針對「試卷檔案」，進行全面性的審題與品質分析。
            
            本次審查資訊：
            * **年級：** {grade}
            * **科目：** {subject}
            * **版本/範圍：** {exam_scope if exam_scope else "未指定"}
            * **審查嚴格度：** {strictness}

            ## 2. 輸入資料處理規則
            {scenario_prompt}

            ## 3. 輸出規範 (Output Format) - 重要！
            請務必依照以下順序輸出，並使用 `===SECTION_BREAK===` 作為每個區塊的分隔線。
            
            **輸出順序如下：**
            1. **Step 1: 【命題範圍檢核】**
            2. **Step 2: 【題幹與邏輯品質審查】**
            3. **Step 3: 【雙向細目表核算】**
            4. **Step 4: 【難易度與負擔分析】**
            5. **Step 5: 【素養導向深度審查】**
            6. **【修改具體建議 (Action Plan)】** (請放在最後總結！)

            **格式要求：**
            * 若發現嚴重錯誤或超綱，請使用 `❌` 或 `⚠️` 標示。
            * 表格請使用 Markdown 格式。

            ---
            
            ## 4. 試卷分析細節 (Analysis Workflow)

            ### Step 1: 【命題範圍檢核】 (Scope Check)
            * 檢查試題是否「超綱」。
            * 若有參考教材，指出哪一題超出教材範圍；若無教材，指出哪一題超出 108 課綱該年段的學習內容。

            ### Step 2: 【題幹與邏輯品質審查】 (Quality Control)
            * **定義一致性：** 檢查專有名詞、符號使用是否與課本/課綱一致。
            * **誘答項合理性：** 針對選擇題，檢查錯誤選項是否具備誘答力，或是有明顯邏輯漏洞。
            * **題意清晰度：** 檢查是否有語意不清、雙重否定或容易產生歧義的敘述。

            ### Step 3: 【雙向細目表核算】 (Two-Way Specification Table)
            請繪製一個表格，將試卷中的**「題號」**填入對應的格子中。
            * **表格結構要求：**
                * 第一欄（縱軸）：單元名稱。
                * 第二至七欄（橫軸）：認知歷程向度 (記憶、了解、應用、分析、評鑑、創造)。
                * 最末列：請統計各認知向度的「分數比重 (%)」。
            * **填寫內容：** 請在格子內填寫該題的**題號**。

            ### Step 4: 【難易度與負擔分析】 (Difficulty & Load)
            * **難度預測：** 分析整份試卷的難易度配置。
            * **成績分佈預測：** 請依據題目難度，預測班級學生的成績分佈比例 (使用表格呈現 60分以下, 60-80分, 90分以上)。

            ### Step 5: 【素養導向深度審查 (分科版)】 (Subject-Specific Competency Review)
            請依據 **{subject}** 的專屬檢核標準進行審查：
            * 標出「真素養題」的亮點。
            * 抓出「假素養題」的偽裝。

            ### 【修改具體建議 (Action Plan)】
            * 請彙整上方所有步驟發現的問題，提出條列式的具體修改建議。
            * 針對紅色警示的題目優先處理。
            
            ---
            【試卷原始內容】：
            {exam_text[:25000]}
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            # 產生 Word
            status.write("📝 正在製作專家審查報告...")
            # 移除分隔符後再存入 Word
            word_content = ai_report.replace("===SECTION_BREAK===", "\n")
            bio = generate_word_report(word_content, "Gemini 3.0 Pro", grade, subject, exam_scope)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            # --- 結果顯示區 (卡片渲染) ---
            st.subheader("📊 專家審題報告")
            
            st.download_button(
                label="📥 下載 Word 完整報告",
                data=bio.getvalue(),
                file_name=f"{grade}{subject}_專家審題報告.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary"
            )
            
            st.markdown("<br>", unsafe_allow_html=True)

            # 切割報告區塊
            if "===SECTION_BREAK===" in ai_report:
                sections = ai_report.split("===SECTION_BREAK===")
            else:
                sections = [ai_report]

            # 迴圈渲染每一個區塊 (使用 st.info/st.error 替代 raw HTML)
            for section in sections:
                if section.strip():
                    # 偵測這段文字有沒有紅色警示
                    has_warning = "❌" in section or "⚠️" in section
                    
                    if has_warning:
                        # 使用 st.error 呈現紅色邊條卡片 (CSS 已改成白色底)
                        st.error(section, icon="⚠️")
                    else:
                        # 使用 st.info 呈現綠色邊條卡片 (CSS 已改成白色底)
                        st.info(section, icon="✅")

        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "429" in str(e):
                st.warning("⚠️ 配額已滿，請稍後再試 (或聯繫管理員)。")
            elif "404" in str(e):
                st.warning("⚠️ 模型連線異常，請確認 API Key 權限。")

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
    doc.add_heading(f'【建功國小】{grade} {subject} 專家審題報告', 0)
    doc.add_paragraph(f"範圍：{scope}")
    doc.add_paragraph(f"審查模型：{model}")
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
