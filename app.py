import streamlit as st
import google.generativeai as genai
from io import BytesIO
from docx import Document
import re # 用於解析 AI 回傳的 Markdown 結構

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

# 自訂 CSS (卡片式風格核心 + 去除空白)
st.markdown("""
    <style>
    /* 1. 全局背景與字體 */
    .stApp { background-color: #f8f9fa; }
    
    /* 2. 去除標題上下的預設空白 (針對需求 1) */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
    }
    
    /* 3. 卡片容器樣式 (針對需求 2, 3) */
    .card-container {
        background-color: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
        margin-bottom: 1.5rem;
        border: 1px solid #e0e0e0;
        border-top: 4px solid #4CAF50; /* 頂部綠色識別線 */
    }
    
    /* 警示卡片樣式 (用於 Action Plan) */
    .alert-card {
        border-top: 4px solid #FF5252 !important;
        background-color: #fff8f8;
    }
    
    /* 步驟卡片標題 */
    .step-header {
        color: #2c3e50;
        font-weight: 700;
        font-size: 1.2rem;
        margin-bottom: 1rem;
        border-bottom: 1px solid #eee;
        padding-bottom: 0.5rem;
    }

    /* 4. 免責聲明文字 */
    .disclaimer-box {
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
        color: #856404;
        padding: 15px;
        border-radius: 5px;
        font-size: 0.9rem;
        line-height: 1.6;
    }
    
    /* 5. 隱藏 Streamlit 預設漢堡選單與 Footer (選擇性) */
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
        # 使用卡片容器
        st.markdown("<div class='card-container'>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center;'>🔐 建功國小智慧審題系統</h1>", unsafe_allow_html=True)
        st.markdown("---")
        
        # 專屬免責聲明
        st.markdown("""
        <div class='disclaimer-box'>
            <b>⚠️ 使用前請詳閱以下說明：</b><br>
            本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。<br>
            <b>1. 人工查核機制：</b>AI 生成內容可能存在誤差或不可預期的錯誤（幻覺），最終試卷定稿請務必回歸教師專業判斷。<br>
            <b>2. 資料隱私安全：</b>嚴禁上傳包含學生個資、隱私或機密敏感內容之文件。<br>
            <b>3. 資料留存規範：</b>本系統不永久留存檔案，上傳之文件將於系統重啟或對話結束後自動銷毀。<br>
            <b>4. 風險承擔同意：</b>使用本服務即代表您理解並同意自行評估相關使用風險。<br>
            <b>5. 授權使用範圍：</b>本系統由昭旭無償提供予臺中市北屯區建功國小教師使用，為避免增加多餘經費，僅提供校內教師使用。
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        password = st.text_input("請輸入校內授權密碼", type="password")
        
        if st.button("我同意以上聲明並登入", type="primary"):
            secret_pass = st.secrets.get("LOGIN_PASSWORD", "school123")
            if password == secret_pass:
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤，請洽詢教務處或資訊組。")
        st.markdown("</div>", unsafe_allow_html=True)

# --- 3. 主應用程式 ---
def main_app():
    # 隱藏側邊欄展開按鈕的 CSS hack
    st.markdown("""<style>[data-testid="collapsedControl"] {display: none}</style>""", unsafe_allow_html=True)
    
    # --- 側邊欄設計 ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/3426/3426653.png", width=60)
        st.title("⚙️ 審題參數設定")
        st.markdown("---")
        st.info("👇 請依序完成設定")

        st.subheader("A. AI 大腦版本")
        st.success("🧠 GEMINI 3.0 PRO\n(建功國小旗艦版)")
        
        st.subheader("B. 選擇年級")
        grade = st.selectbox("適用對象", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        
        st.subheader("C. 選擇科目")
        subject = st.selectbox("測驗科目", ["國語", "數學", "英語", "自然", "社會", "生活"])
        
        st.subheader("D. 考試範圍")
        exam_scope = st.text_input("輸入單元或頁數", placeholder="例如：康軒版 第3-4單元")
        
        st.subheader("F. 嚴格程度")
        strictness = st.select_slider("AI 審查力道", options=["溫柔", "標準", "嚴格", "魔鬼"], value="嚴格")
        
        st.markdown("---")
        if st.button("登出系統"):
            st.session_state['logged_in'] = False
            st.rerun()

    # --- 主畫面設計 ---
    st.markdown("<h1 style='text-align: center; color: #2c3e50;'>🏫 台中市北屯區建功國小智慧審題系統</h1>", unsafe_allow_html=True)
    
    if st.sidebar.state == "collapsed": 
        st.warning("👈 **老師請注意：請先點擊畫面左上角的「>」箭頭，展開設定年級與科目！**")

    # --- 資料上傳區 (卡片式 - 需求 2) ---
    st.markdown("<div class='card-container'>", unsafe_allow_html=True)
    st.markdown("<div class='step-header'>📁 資料上傳區</div>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.info("📄 **1. 上傳試卷 (必要)**")
        uploaded_exam = st.file_uploader("請拖曳試卷 PDF", type=['pdf'], key="exam")
    
    with col2:
        st.success(f"📘 **2. 上傳 {grade}{subject} 課本/習作 (選填)**")
        uploaded_refs = st.file_uploader("供 AI 比對範圍 (可多選)", type=['pdf'], key="ref", accept_multiple_files=True)
        # 加註提示
        st.caption("💡 **小提示：** 若有上傳課本/習作，AI 在「範圍審查」與「名詞檢核」將更加精確！")
        
    st.markdown("</div>", unsafe_allow_html=True)

    # 執行按鈕
    if uploaded_exam:
        if st.button("🚀 啟動 AI 專家審題 (Gemini 3.0 Pro)", type="primary", use_container_width=True):
            process_review(uploaded_exam, uploaded_refs, grade, subject, strictness, exam_scope)

# --- 4. 核心邏輯 (專家版) ---
def process_review(exam_file, ref_files, grade, subject, strictness, exam_scope):
    
    # 建立進度條容器
    progress_container = st.empty()
    status = progress_container.status("🔍 AI 專家啟動中...", expanded=True)
    
    try:
        # 設定 API
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-1.5-pro") # 若 3.0 還不能用，建議先用 1.5 Pro，或維持您原本的設定
        
        # 讀取檔案
        status.write("📄 正在分析試卷結構...")
        exam_text = extract_pdf_text(exam_file)
        
        # 建立參考資料 Prompt
        ref_prompt = ""
        if ref_files:
            status.write(f"📘 正在分析 {len(ref_files)} 份教材，建立比對基準...")
            ref_text = ""
            for f in ref_files:
                ref_text += extract_pdf_text(f) + "\n"
            
            # 情境 A Prompt
            scenario_prompt = f"""
            * **情境 A：使用者有上傳「課本、習作或學習單」**
                * **基準：** 以使用者上傳的教材檔案為「絕對標準」。
                * **動作：** 檢查試卷內容是否超出這些上傳教材的範圍。
            
            【使用者上傳的參考教材內容】：
            {ref_text[:50000]}
            """
        else:
            status.write("📚 未偵測到教材，正在調用「教育部 108 課綱」知識庫...")
            # 情境 B Prompt
            scenario_prompt = f"""
            * **情境 B：使用者僅上傳「試卷」，未上傳教材**
                * **基準：** 啟動你內建的知識庫，調用「台灣教育部 108 課綱」中【{subject}】領域、【{grade}】的「學習內容」與「學習表現」。
                * **動作：** 以課綱條目為標準，判斷試卷是否符合該年段的學習目標。
            """

        status.write("🧠 Gemini 正在進行五大步驟深度審查...")
        
        # --- 組合最終 Prompt (使用您提供的最新版本) ---
        prompt = f"""
        # Role: 台灣國小教育評量暨素養導向命題專家 (Taiwan Elementary Education & Competency-Based Assessment Expert)

        ## 1. 任務目標
        你是一位精通台灣教育部「108課綱」與測驗編製理論的專家。請針對使用者上傳的「試卷檔案」，進行全面性的審題與品質分析。

        ## 2. 輸入資料處理規則 (Data Handling Logic)
        請先確認使用者提供了哪些檔案，並依據以下邏輯決定「比對基準」：

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
        請繪製一個表格，將試卷中的**「題號」**填入對應的格子中。
        * **表格結構要求：**
            * **第一欄（縱軸）：** 單元名稱 (依據試卷或課本單元劃分)。
            * **第二至七欄（橫軸）：** 認知歷程向度，依序為「記憶」、「了解」、「應用」、「分析」、「評鑑」、「創造」。
            * **最末列：** 請統計各認知向度的「分數比重 (%)」。
        * **填寫內容：** 請在格子內填寫該題的**題號**（例如：Q1, Q5, 應用題2）。

        **表格範例參考：**
        | 單元名稱 | 記憶 | 了解 | 應用 | 分析 | 評鑑 | 創造 |
        | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
        | 單元一 | Q1, Q2 | Q3 | Q10 | | | |
        | 單元二 | Q4 | Q5, Q6 | | Q25 | | |
        | **分數比重** | **20%** | **30%** | **30%** | **15%** | **5%** | **0%** |

        ### Step 4: 【難易度與負擔分析】 (Difficulty & Load)
        * **難度預測：** 分析整份試卷的難易度配置（直球題 vs. 變形題）。
        * **成績分佈預測：** 請依據題目難度，預測班級學生的成績分佈比例，並以表格呈現：

        | 分數區間 | 預測人數佔比 (%) | 簡要說明 |
        | :--- | :--- | :--- |
        | **60分以下** | (請填寫) | (預測哪些題型導致低分) |
        | **60-80分** | (請填寫) | (預測中等程度學生的落點) |
        | **90分以上** | (請填寫) | (預測具鑑別度的關鍵題號) |

        ### Step 5: 【素養導向深度審查 (分科版)】 (Subject-Specific Competency Review)

        請先讀取本次審查的「科目」，並依據該科目的**專屬檢核標準**進行素養題審查：

        #### 1. 若為【國語文】(Chinese Language Arts)：
        * **檢核重點：** 是否評量「閱讀策略」與「表達能力」，而非僅是內容記憶。
        * **防偽快篩：**
            * **⚠️ 假素養警示：** 題目雖然引用課外文章，但問題僅是「圈出錯字」或「直接摘錄文中句子」，未涉及推論、比較或主旨判斷。
            * **✅ 真素養特徵：** 需運用「預測、推論、摘要、監控」等策略，或要求學生結合自身經驗進行表達。

        #### 2. 若為【數學】(Mathematics)：
        * **檢核重點：** 是否具備「數學建模」過程，且數據符合現實邏輯。
        * **防偽快篩：**
            * **⚠️ 假素養警示 (裝飾性情境)：** 題目情境（如小明買菜）與算式無關，刪除情境後不影響作答；或是數據不合理（如：跑步速度每秒 100 公尺）。
            * **✅ 真素養特徵：** 學生需要從情境中「轉譯」出數學算式，且情境中的條件（如打折規則、火車時刻）是解題的必要資訊。

        #### 3. 若為【自然科學】(Science)：
        * **檢核重點：** 是否評量「探究歷程」（觀察、假設、實驗設計、數據分析）。
        * **防偽快篩：**
            * **⚠️ 假素養警示 (純閱讀測驗)：** 題目提供一篇科普文章，答案完全可從文中「複製貼上」，學生無需具備該單元的科學先備知識。
            * **✅ 真素養特徵：** 題目提供實驗數據或現象圖表，學生需運用科學原理進行「解釋」或「預測」。

        #### 4. 若為【社會】(Social Studies)：
        * **檢核重點：** 是否評量「多重觀點」、「史料判讀」或「社會參與」。
        * **防偽快篩：**
            * **⚠️ 假素養警示 (碎片化記憶)：** 雖然有地圖或年表，但考的只是「這是哪裡」或「發生在幾年」，未涉及因果關係或變遷分析。
            * **✅ 真素養特徵：** 提供不同立場的觀點（如開發案的正反意見），要求學生分析差異或做出價值判斷。

        #### 5. 若為【英語文】(English)：
        * **檢核重點：** 是否符合「真實語用」(Pragmatics) 與「溝通功能」。
        * **防偽快篩：**
            * **⚠️ 假素養警示 (文法代換)：** 對話情境生硬（不像真人對話），僅為了考特定的文法規則。
            * **✅ 真素養特徵：** 模擬真實生活任務（如：點餐、看時刻表、寫邀請卡），且語言使用符合母語人士習慣。

        **評定輸出要求：**
        請針對該科目，列出試卷中符合上述「真素養特徵」的優良試題題號，並對「假素養警示」的題目提出修改建議。

        ## 4. 輸出產出 (Final Output)
        請彙整以上五步驟分析，提供一份結構清晰的**「試卷審查總結報告」**，並包含具體的**「修改建議」**（請獨立一個章節，條列具體的修正建議 Action Plan）。

        ---
        **現在，請接收我上傳的檔案，並開始執行審查。**
        **本次試卷資訊：**
        * **年級：** {grade}
        * **科目：** {subject}
        * **版本/範圍：** {exam_scope if exam_scope else "未指定"}
        
        【試卷文字內容】：
        {exam_text[:30000]}
        """
        
        # 呼叫 AI
        response = model.generate_content(prompt)
        full_report = response.text
        
        # --- 後處理：解析報告以進行分卡片顯示 & 紅字標註 ---
        # 1. 產生 Word 下載檔 (保留原始 Markdown)
        bio = generate_word_report(full_report, "Gemini AI", grade, subject, exam_scope)
        
        status.update(label="✅ 分析完成！", state="complete", expanded=False)
        progress_container.empty() # 清除狀態列

        # --- 顯示結果區 ---
        
        # 下載按鈕區
        st.markdown("<div style='text-align:right; margin-bottom:10px;'>", unsafe_allow_html=True)
        st.download_button(
            label="📥 下載完整 Word 報告",
            data=bio.getvalue(),
            file_name=f"{grade}{subject}_專家審題報告.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary"
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # 2. 解析報告結構 (簡單的字串分割)
        # 目標：提取「修改建議」與「Step 1~5」
        
        # 先處理紅字警告：將 ⚠️ 替換為 Streamlit 的紅色語法
        formatted_report = full_report.replace("⚠️", " :red[**⚠️**] ").replace("假素養", ":red[**假素養**]")

        # 嘗試抓取「修改建議」 (通常在最後，但我們要在 UI 上移到最前)
        # 注意：AI 輸出可能不完全一致，這裡用簡單的關鍵字分割
        
        sections = {}
        
        # 定義切割點
        split_patterns = [
            ("STEP_1", "### Step 1"),
            ("STEP_2", "### Step 2"),
            ("STEP_3", "### Step 3"),
            ("STEP_4", "### Step 4"),
            ("STEP_5", "### Step 5"),
            ("SUGGESTIONS", "修改建議") # 或是 "Action Plan"
        ]
        
        # 簡單分割邏輯
        remaining_text = formatted_report
        action_plan_text = ""
        
        # 尋找 Action Plan (通常在最後)
        if "修改建議" in remaining_text:
            parts = remaining_text.split("修改建議")
            if len(parts) > 1:
                # 假設最後一部分是建議
                action_plan_text = "### 修改建議" + parts[-1]
                remaining_text = parts[0] # 剩下的部分是步驟分析
        
        # --- 顯示區塊 1: 具體修改建議 (需求 4: 移到最上面) ---
        if action_plan_text:
            st.markdown(f"""
            <div class='card-container alert-card'>
                <div class='step-header' style='color:#d32f2f;'>🚨 專家總結與具體修改建議 (Action Plan)</div>
                {action_plan_text.replace('### 修改建議', '')}
            </div>
            """, unsafe_allow_html=True)
        
        # --- 顯示區塊 2: 逐步分析 (需求 3: 卡片式呈現) ---
        
        # 利用 Markdown 的 header 來分割 Step (這裡簡化處理，直接用原始字串的 find)
        steps_content = []
        for i in range(1, 6):
            start_marker = f"### Step {i}"
            end_marker = f"### Step {i+1}" if i < 5 else None
            
            start_idx = formatted_report.find(start_marker)
            if start_idx != -1:
                if end_marker:
                    end_idx = formatted_report.find(end_marker)
                    content = formatted_report[start_idx:end_idx]
                else:
                    # Step 5 到最後 (如果前面已經切掉修改建議，這裡要注意範圍)
                    # 簡單起見，我們重新在 formatted_report 找，忽略 action plan 的切割
                    # 若 formatted_report 包含 Action Plan，Step 5 會包含它，我們暫不處理這個重疊，
                    # 因為主要目標是讓 Step 顯示在卡片中
                    content = formatted_report[start_idx:]
                    if "修改建議" in content:
                        content = content.split("修改建議")[0]
                
                # 移除標題本身，因為我們會在卡片 header 顯示
                clean_content = content.replace(start_marker, "")
                # 移除標題後的冒號或文字直到換行
                clean_content = re.sub(r"^.*?\n", "", clean_content, count=1)
                
                step_titles = [
                    "命題範圍檢核", "題幹與邏輯品質審查", 
                    "雙向細目表核算", "難易度與負擔分析", 
                    "素養導向深度審查 (分科版)"
                ]
                
                st.markdown(f"""
                <div class='card-container'>
                    <div class='step-header'>Step {i}: {step_titles[i-1]}</div>
                    {clean_content}
                </div>
                """, unsafe_allow_html=True)
        
        # 若分割失敗 (AI 沒照格式)，則顯示原始全文
        if not steps_content and not action_plan_text:
             st.markdown(f"<div class='card-container'>{formatted_report}</div>", unsafe_allow_html=True)

    except Exception as e:
        progress_container.empty()
        st.error(f"發生錯誤：{e}")
        st.error("請檢查 API Key 或網路連線。")

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
