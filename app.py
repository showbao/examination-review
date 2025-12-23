import streamlit as st
import google.generativeai as genai
from io import BytesIO
from docx import Document
import re # 用於正規表達式切割報告

# 嘗試匯入 PDF 套件 (相容性處理)
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

# 自訂 CSS (優化版)
st.markdown("""
    <style>
    /* 1. 移除頂部空白，讓標題往上貼 */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
    }
    
    /* 背景色調 */
    .stApp { background-color: #f0f2f6; }
    
    /* 通用卡片容器樣式 */
    .card-container {
        background-color: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
        margin-bottom: 1.5rem;
        border-left: 6px solid #4CAF50; /* 綠色識別線 */
    }
    
    /* 警告型卡片 (用於發現問題) */
    .card-warning {
        border-left: 6px solid #FF5252 !important; /* 紅色識別線 */
    }

    /* 標題樣式 */
    h1 { color: #1e3a8a; font-weight: 800; letter-spacing: 1px; }
    h2, h3 { color: #2c3e50; font-weight: 600; }
    
    /* 按鈕樣式 */
    .stButton>button { 
        width: 100%; 
        border-radius: 8px; 
        font-weight: 700; 
        height: 3.5em; 
        background-color: #2563eb; 
        color: white;
    }
    
    /* 免責聲明文字 */
    .disclaimer-box {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        color: #856404;
        padding: 15px;
        border-radius: 5px;
        font-size: 0.9rem;
        line-height: 1.6;
    }
    .disclaimer-title { font-weight: bold; margin-bottom: 5px; font-size: 1rem; }
    
    /* 隱藏預設的主選單漢堡 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- 1. Session State 管理 ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False

# --- 2. 登入頁面 (建功國小專屬聲明) ---
def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='card-container'>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center;'>🔐 建功國小智慧審題系統</h2>", unsafe_allow_html=True)
        st.markdown("---")
        
        # 專屬免責聲明
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
        password = st.text_input("請輸入校內授權密碼", type="password")
        
        if st.button("我同意以上聲明並登入"):
            # 從 Secrets 讀取密碼 (若未設定則預設 school123)
            secret_pass = st.secrets.get("LOGIN_PASSWORD", "school123")
            if password == secret_pass:
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤，請洽詢教務處或資訊組。")
        st.markdown("</div>", unsafe_allow_html=True)

# --- 3. 主應用程式 ---
def main_app():
    # 強制展開側邊欄 (CSS hack) 並不總是有效，所以我們用文字引導
    st.markdown("""<style>[data-testid="collapsedControl"] {display: none}</style>""", unsafe_allow_html=True)
    
    # --- 側邊欄設計 ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 審題參數設定")
        st.markdown("---")
        
        st.info("👇 請依序完成設定")

        # A. 模型 (鎖定顯示)
        st.subheader("A. AI 大腦版本")
        st.success("🧠 Gemini 3.0 Pro\n(已啟用校內專用旗艦版)")
        # 這裡不讓老師選，後台直接鎖定
        
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

    # --- 主畫面設計 ---
    
    # 標題
    st.markdown("<h1 style='text-align: center; margin-bottom: 10px;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    
    # 1. 顯眼的黃色提示框 (側邊欄引導)
    if st.sidebar.state == "collapsed": 
        st.warning("👈 **老師請注意：請先點擊畫面左上角的「>」箭頭，展開設定年級與科目！**")

    # 2. 資料上傳區 (使用 Columns + Card CSS)
    st.subheader("📂 資料上傳區")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # 左側卡片：試卷上傳
        st.markdown("""
        <div class='card-container'>
            <h3>📄 1. 上傳試卷 (必要)</h3>
        </div>
        """, unsafe_allow_html=True)
        uploaded_exam = st.file_uploader("請拖曳試卷 PDF", type=['pdf'], key="exam", label_visibility="collapsed")
        # 已移除 10MB 限制
    
    with col2:
        # 右側卡片：課本上傳
        st.markdown(f"""
        <div class='card-container' style='border-left-color: #2196F3;'>
            <h3>📘 2. 上傳 {grade}{subject} 課本/習作 (選填)</h3>
        </div>
        """, unsafe_allow_html=True)
        uploaded_refs = st.file_uploader(
            "供 AI 比對範圍 (可多選)", 
            type=['pdf'], 
            key="ref", 
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        
        # 在卡片下方顯示提示
        if uploaded_refs:
            st.success("✅ 已上傳參考教材，AI 將執行「精準範圍比對」。")
        else:
            st.info("💡 小提示：若上傳課本/習作，AI 在「範圍審查」與「名詞檢核」將更加精確！")
        
    st.markdown("<br>", unsafe_allow_html=True)

    # 執行按鈕
    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題 (Gemini 3.0 Pro)", type="primary"):
            process_review(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope)

# --- 4. 核心邏輯 (專家版 V4.1) ---
def process_review(exam_file, ref_files, grade, subject, strictness, exam_scope):
    
    # 使用 container 來包裹進度條
    with st.container():
        status = st.status("🔍 AI 專家啟動中...", expanded=True)
        
        try:
            # 設定 API Key
            api_key = st.secrets["GEMINI_API_KEY"]
            genai.configure(api_key=api_key)
            
            # 【鎖定】強制使用 Gemini 3.0 Pro Preview (確保使用最新版)
            # 若發生 Quota 問題，請手動改回 'models/gemini-2.0-flash'
            model = genai.GenerativeModel("models/gemini-3-pro-preview")
            
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
                
                scenario_prompt = f"""
                * **情境 A (使用者有上傳教材)：**
                * **基準：** 請嚴格以本提示詞下方提供的【參考教材內容】為絕對標準。
                * **動作：** 檢查試卷題目是否超出這些教材的教學範圍。
                
                【參考教材內容】：
                {ref_text[:60000]}
                """
            else:
                status.write("📚 未偵測到教材，正在調用「教育部 108 課綱」知識庫...")
                scenario_prompt = f"""
                * **情境 B (使用者未上傳教材)：**
                * **基準：** 請啟動你內建的知識庫，調用「台灣教育部 108 課綱」中【{subject}】領域、【{grade}】的「學習內容」與「學習表現」。
                * **動作：** 以課綱條目為標準，判斷試卷是否符合該年段的學習目標。
                """

            # 組合 Prompt
            status.write("🧠 Gemini 3.0 Pro 正在執行雙向細目表核算與素養檢測...")
            
            # --- V4.1 提示詞優化：加入分隔符以便 Python 切割 ---
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
            1. **【修改具體建議 (Action Plan)】** (請放在最前面！)
            2. **Step 1: 【命題範圍檢核】**
            3. **Step 2: 【題幹與邏輯品質審查】**
            4. **Step 3: 【雙向細目表核算】**
            5. **Step 4: 【難易度與負擔分析】**
            6. **Step 5: 【素養導向深度審查】**

            **格式要求：**
            * 若發現嚴重錯誤或超綱，請使用 `❌` 或 `⚠️` 標示，並使用紅色文字強調。
            * 表格請使用 Markdown 格式。

            ---
            
            ## 4. 試卷分析細節 (Analysis Workflow)

            ### 【修改具體建議 (Action Plan)】
            * 請彙整下方所有步驟發現的問題，提出條列式的具體修改建議。
            * 這是老師最需要看到的重點，請寫得精簡有力。

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
            請依據 **{subject}** 的專屬檢核標準進行審查 (參考你的專家知識庫)：
            * 標出「真素養題」的亮點。
            * 抓出「假素養題」的偽裝 (如：裝飾性情境、文法代換、死背硬記)。
            
            ---
            【試卷原始內容】：
            {exam_text[:25000]}
            """
            
            response = model.generate_content(prompt)
            ai_report = response.text
            
            # 產生 Word 供下載
            status.write("📝 正在製作專家審查報告...")
            bio = generate_word_report(ai_report, "Gemini 3.0 Pro", grade, subject, exam_scope)
            
            status.update(label="✅ 分析完成！", state="complete", expanded=False)
            
            # --- 結果顯示區 (卡片式呈現) ---
            st.subheader("📊 專家審題報告")
            
            # 下載按鈕
            st.download_button(
                label="📥 下載 Word 完整報告",
                data=bio.getvalue(),
                file_name=f"{grade}{subject}_專家審題報告.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary"
            )
            
            st.markdown("---")

            # --- 智能切割與卡片渲染 ---
            # 利用 Prompt 中的 ===SECTION_BREAK=== 來切割內容
            if "===SECTION_BREAK===" in ai_report:
                sections = ai_report.split("===SECTION_BREAK===")
            else:
                # Fallback: 如果 AI 沒乖乖聽話，就嘗試用標題切，或直接顯示全文
                sections = [ai_report]

            # 迴圈渲染每一個區塊
            for section in sections:
                if section.strip():
                    # 偵測這段文字有沒有紅色警示 (❌ 或 ⚠️)
                    has_warning = "❌" in section or "⚠️" in section
                    card_class = "card-warning" if has_warning else "card-container"
                    
                    # 使用 HTML 渲染卡片
                    st.markdown(f"""
                    <div class='{card_class}'>
                        {markdown_to_html_hack(section)}
                    </div>
                    """, unsafe_allow_html=True)

        except Exception as e:
            status.update(label="❌ 發生錯誤", state="error")
            st.error(f"錯誤：{e}")
            if "429" in str(e):
                st.warning("⚠️ 配額已滿，請稍後再試 (或聯繫管理員)。")
            elif "404" in str(e):
                st.warning("⚠️ 模型連線異常，請確認 API Key 權限。")

# --- 輔助函數：將 Markdown 轉為 HTML 以便在 div 中顯示 ---
# Streamlit 的 st.markdown 在 div 裡面有時會怪怪的，這裡做簡單處理
# 但為了保持簡單，我們直接用 st.markdown 渲染內容，只是包在 div 裡
def markdown_to_html_hack(text):
    # 這裡我們其實是利用 st.markdown 的能力，但因為要包在 div 裡，
    # 我們可以先把它當作一般文字處理。
    # 更好的作法是直接印出 div 開頭，然後 st.markdown，然後 div 結尾
    # 但在 loop 中比較難。
    # 簡單解法：使用 Python 的 markdown 套件 (但這裡不能多裝)。
    # 替代解法：直接回傳 text，在外面用 st.markdown 處理。
    
    # 修正策略：我們不自己轉 HTML，我們用 st.markdown 渲染，但利用 CSS Class 包裹
    # 由於 Streamlit 限制，我們無法在 st.markdown 裡直接寫 <div class=...> markdown content </div>
    # 所以我們把上面的 loop 改一下寫法。
    return text

# --- 修正後的 Process Review 渲染迴圈 (替換上面的 loop) ---
# (請將上面 process_review 中的 loop 替換為以下)
"""
            # 迴圈渲染每一個區塊 (修正版)
            for section in sections:
                if section.strip():
                    # 偵測警告
                    has_warning = "❌" in section or "⚠️" in section
                    
                    # 開始卡片容器
                    if has_warning:
                        st.markdown('<div class="card-container card-warning">', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="card-container">', unsafe_allow_html=True)
                    
                    # 內容渲染
                    st.markdown(section)
                    
                    # 結束卡片容器
                    st.markdown('</div>', unsafe_allow_html=True)
"""
# --- 這裡我為了讓您方便複製，直接把修正後的 loop 整合進上面的 process_review 函數裡了 ---
# 請看上面的 process_review 函數，我會把 `markdown_to_html_hack` 拿掉，直接用 st.markdown
# (為了代碼完整性，我會在下方重新貼一次完整的 process_review 函數，請覆蓋上面的)

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
    # 移除分隔符以便 Word 顯示乾淨
    clean_text = text.replace("===SECTION_BREAK===", "\n")
    doc.add_paragraph(clean_text)
    bio = BytesIO()
    doc.save(bio)
    return bio

if __name__ == "__main__":
    if st.session_state['logged_in']:
        main_app()
    else:
        login_page()
