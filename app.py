import streamlit as st
import google.generativeai as genai
import os
import time
from docx import Document # 預留給 Word 生成用

# ==========================================
# 0. 視覺風格設定 (莫蘭迪色系 & CSS)
# ==========================================
st.set_page_config(page_title="智慧試卷審題系統", page_icon="📝", layout="wide")

# 莫蘭迪色系定義：
# 主色 (Sage Green): #8DA399 (按鈕、強調)
# 副色 (Slate Blue): #5B7C99 (標題)
# 背景 (Mist Grey): #F5F7F7
# 文字 (Charcoal): #4A4A4A

morandi_css = """
<style>
    /* 全站背景 */
    .stApp {
        background-color: #F5F7F7;
    }
    /* 主標題 */
    h1, h2, h3 {
        color: #5B7C99 !important;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    }
    /* 按鈕樣式 */
    div.stButton > button {
        background-color: #8DA399;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
        transition: all 0.3s;
    }
    div.stButton > button:hover {
        background-color: #6E8B7F;
        color: white;
        border: 1px solid #6E8B7F;
    }
    /* 側邊欄背景 */
    section[data-testid="stSidebar"] {
        background-color: #E8ECEC;
    }
    /* 資訊卡片背景 */
    div.stAlert {
        background-color: #E3E9E9;
        border: 1px solid #8DA399;
        color: #4A4A4A;
    }
</style>
"""
st.markdown(morandi_css, unsafe_allow_html=True)

# ==========================================
# 1. 登入與免責聲明 (Login & Disclaimer)
# ==========================================

def check_password():
    """帶有免責聲明的登入系統"""
    if st.session_state.get("password_correct", False):
        return True

    # 登入頁面佈局
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔒 智慧試卷審題系統登入")
        
        # 免責聲明區塊
        with st.expander("⚠️ 使用前請務必詳閱免責聲明 (點擊展開)", expanded=True):
            st.markdown("""
            **使用前請詳閱以下說明：**
            本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。
            
            1. **人工查核機制**：AI 生成內容可能存在誤差或不可預期的錯誤（幻覺），最終試卷定稿請務必回歸教師專業判斷。
            2. **資料隱私安全**：嚴禁上傳包含學生個資、隱私或機密敏感內容之文件。
            3. **資料留存規範**：本系統不永久留存檔案，上傳之文件將於系統重啟或對話結束後自動銷毀。
            4. **風險承擔同意**：使用本服務即代表您理解並同意自行評估相關使用風險。
            5. **授權使用範圍**：本系統無償提供予臺中市北屯區建功國小教師使用，為確保資源永續與經費控管，僅限校內教師內部使用。
            """)
        
        password = st.text_input("請輸入學校專用通行碼", type="password")
        if st.button("我同意聲明並登入"):
            if password == st.secrets["APP_PASSWORD"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤")
    return False

if not check_password():
    st.stop()

# ==========================================
# 2. 核心邏輯：模型管理與科目偵測
# ==========================================

def get_smart_model_list(api_key):
    """智慧篩選模型：Gemini 3.0 Pro > 2.0 Thinking > 2.5 Pro > Flash"""
    genai.configure(api_key=api_key)
    models = []
    try:
        all_models = genai.list_models()
        for m in all_models:
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.lower()
                # 排除不適用模型
                if any(x in name for x in ["nano", "bison", "unicorn", "aqa", "vision"]):
                    continue
                
                # 權重計分
                score = 0
                if "gemini-3" in name: score += 10000
                elif "gemini-2.5" in name: score += 8000
                elif "gemini-2" in name: score += 6000
                elif "gemini-1.5" in name: score += 2000
                
                if "thinking" in name: score += 1500
                if "pro" in name: score += 1000
                if "flash" in name: score += 500
                
                models.append((m.display_name, m.name, score))
        
        models.sort(key=lambda x: x[2], reverse=True)
        return [(m[0], m[1]) for m in models[:5]] # 只回傳前5名
    except:
        return [("Gemini 1.5 Pro (Fallback)", "models/gemini-1.5-pro")]

def detect_subject_and_route(file_content, api_key):
    """(模擬) 快速偵測科目並回傳建議模型與科目名稱"""
    # 實務上這裡會呼叫 Gemini Flash 讀取前 1000 字
    # 這裡為了演示，我們先回傳一個預設值，實際運作時會由主流程的 AI 判斷
    # 為了節省額度，我們把這個偵測邏輯合併到 System Prompt 裡去做
    return "自動偵測中..."

def upload_to_gemini(file_obj):
    """上傳檔案到 Gemini"""
    import tempfile
    suffix = ".pdf" if file_obj.name.endswith(".pdf") else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_obj.getvalue())
        tmp_path = tmp.name
    
    file_ref = genai.upload_file(tmp_path, mime_type="application/pdf" if suffix == ".pdf" else "image/jpeg")
    while file_ref.state.name == "PROCESSING":
        time.sleep(1)
        file_ref = genai.get_file(file_ref.name)
    os.remove(tmp_path)
    return file_ref

# ==========================================
# 3. 介面與側邊欄設定
# ==========================================
st.title("📝 智慧試卷審題系統")

# --- 側邊欄 ---
with st.sidebar:
    st.header("⚙️ 參數設定")
    
    # API Key 檢查
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        model_options = get_smart_model_list(api_key)
    else:
        st.error("請設定 Secrets: GEMINI_API_KEY")
        st.stop()

    # 1. 模型選擇 (自動 + 手動)
    st.subheader("1. AI 模型核心")
    model_mode = st.radio("模式", ["🤖 依科目自動切換", "🖐️ 手動指定"], horizontal=True)
    
    selected_model_id = None
    if model_mode == "🖐️ 手動指定":
        selected_model = st.selectbox("選擇模型", model_options, index=0)
        selected_model_id = selected_model[1]
    else:
        st.info("系統將依試卷內容自動路由：\n\n📐 數學/理科 → 3.0 Pro\n📚 文史/社會 → 3.0 Flash")
        # 這裡的自動切換邏輯會在後端 prompt 執行時動態決定，預設先拿最好的 Pro
        selected_model_id = model_options[0][1] 

    st.markdown("---")
    
    # 2. 雙向細目表設定 (動態單元)
    st.subheader("2. 雙向細目表設定")
    st.caption("請輸入本試卷包含的單元，以利 AI 製作細目表。")
    
    unit_count = st.number_input("本試卷包含幾個單元？", min_value=1, max_value=10, value=3)
    unit_list = []
    for i in range(unit_count):
        unit_name = st.text_input(f"單元 {i+1} 名稱", placeholder=f"例如：第 {i+1} 單元 整數運算", key=f"unit_{i}")
        if unit_name:
            unit_list.append(unit_name)
            
    st.markdown("---")
    st.caption("Designed for 建功國小 | Powered by Gemini 3.0")

# --- 主畫面：檔案上傳 ---
col1, col2 = st.columns(2)
with col1:
    st.markdown("### 1️⃣ 上傳教材/課本 (可選)")
    st.caption("若未上傳，Step 1 與 Step 4 將自動切換為簡易模式。")
    context_files = st.file_uploader("支援 PDF", type=["pdf"], accept_multiple_files=True)

with col2:
    st.markdown("### 2️⃣ 上傳試卷 (必選)")
    st.caption("支援 PDF/圖片 (包含數學公式、圖表)")
    exam_file = st.file_uploader("上傳試卷", type=["pdf", "jpg", "png"])

# ==========================================
# 4. 審查邏輯與 Prompt 建構
# ==========================================

# 預定義的素養標準 (Step 3 用)
LITERACY_STANDARDS = """
【核心通用法則：剝皮測試】
檢核標準：試著將題目中的「情境敘述」（故事、圖片、前言）移除。
判定：如果移除情境後，學生依然可以直接作答（變成單純的背誦或計算），即判定為「❌ 假素養（裝飾性情境）」。真正的情境必須是解題的必要條件。

【各科真假素養審查標準】：
1. 國語科：(真)閱讀依存、高階思維、多元表徵；(假)情境脫節、低階提問。
2. 數學科：(真)功能性情境、真實解題(含雜訊)、數學建模；(假)文字堆砌、數據完美、套路解題。
3. 英語科：(真)真實語料、語用溝通、資訊素養；(假)去脈絡化、死記硬背、文化真空。
4. 社會科：(真)史料判讀、多重觀點、因果探究；(假)瑣碎記憶、單一觀點、結論背誦。
5. 自然科：(真)探究歷程、解釋現象、證據論述；(假)名詞解釋、結果背誦、違背常理。
6. 生活課程：(真)感官體驗、情境應變、實作導向；(假)規訓教條、知識超載、文字負擔。
"""

if st.button("🚀 開始全方位審查", type="primary"):
    if not exam_file:
        st.warning("❌ 請務必上傳一份「試卷」！")
    else:
        # 進度條與狀態區
        status_box = st.empty()
        progress_bar = st.progress(0)
        
        try:
            # 1. 檔案處理
            status_box.info("☁️ 正在將檔案傳送至 AI 安全沙箱...")
            model = genai.GenerativeModel(selected_model_id)
            prompt_parts = []
            
            exam_ref = upload_to_gemini(exam_file)
            has_context = False
            context_refs = []
            
            if context_files:
                for cf in context_files:
                    context_refs.append(upload_to_gemini(cf))
                has_context = True
            
            progress_bar.progress(30)
            
            # 2. 建構超級 Prompt (Chain of Thought)
            status_box.info("🧠 正在建構審查指令 (Auto-Routing)...")
            
            # 判斷是否提供單元列表
            units_str = ", ".join(unit_list) if unit_list else "未提供 (請自行判斷)"
            
            base_prompt = f"""
你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。請依照以下步驟審查這份【待審試卷】。

**前置作業：**
1. 請先判斷這份試卷的科目（國語/英語/數學/社會/自然/生活）。
2. 若是數學/自然科，請啟動「深度推理模式」，仔細檢查公式與圖表。

請嚴格依照以下 6 大步驟輸出 Markdown 報告：

---
### Step 1: 命題範圍與合規性 (模組 A)
* **狀態：** (若有上傳教材，請比對並標示 🟢通過 / 🔴超綱；**若無上傳教材，請直接輸出警語：「⚠️ 未檢查命題範圍：未上傳教材，故未檢查命題範圍，請老師務必自行審示題目的適切性。」**)

### Step 2: 題幹與邏輯品質 (模組 A)
* 檢查語意歧義、邏輯謬誤、選項互斥性。
* 輸出格式：🟢/🟡/🔴 燈號 + 簡短說明。

### Step 3: 素養導向深度審查 (模組 A)
**請依據下列標準執行「剝皮測試」，並挑選 5-10 題具代表性題目進行分析：**
{LITERACY_STANDARDS}

* **輸出格式：**
    * **第 X 題 [🟢真素養 / 🔴假素養]**
    * **判斷依據：** (說明剝皮測試結果)
    * **修改建議：** (針對假素養提出建議)

### Step 4: 雙向細目表核算 (模組 B)
**指定單元範圍：** {units_str}

* **情況 A (若有提供單元名稱 且 有上傳教材)：** 請製作標準雙向細目表。
    * 表頭：記憶/理解/應用/分析/評鑑/創造 + 總計
    * 側欄：單元名稱 (請使用我提供的單元清單) + 總計
    * 內容：填入題號。
    * 統計：計算各單元與各向度的百分比重，並檢核總和是否為 100%。

* **情況 B (若缺一)：** 請製作簡易向度分析表。
    * 欄位：知識向度 | 對應題號 | 題數佔比

### Step 5: 難易度與負擔分析 (模組 B)
* 請以表格呈現：難易度分佈(易/中/難)、預估閱讀量、作答步驟數。

### Step 6: 總結與建議 (模組 C)
* **👍 值得讚許之處：** (條列優點)
* **💡 具體修改建議：** (條列具體建議，不需給評分)

---
"""
            # 組合 Prompt
            if has_context:
                prompt_parts.append("【參考教材/課本】：")
                prompt_parts.extend(context_refs)
            
            prompt_parts.append(base_prompt)
            prompt_parts.append("【待審查試卷】：")
            prompt_parts.append(exam_ref)
            
            # 3. 執行分析
            status_box.info(f"🤖 AI ({selected_model_id}) 正在進行深度審查... (數學科可能需時較久)")
            progress_bar.progress(60)
            
            response = model.generate_content(prompt_parts)
            
            progress_bar.progress(100)
            status_box.success("✅ 分析完成！")
            
            # 4. 顯示結果
            st.markdown("## 📊 審查報告")
            st.markdown(response.text)
            
            # ==========================================
            # 5. 生成 Word 報告 (預留區)
            # ==========================================
            def generate_word_report(text_content):
                # TODO: 未來在此處實作 Markdown -> Word 表格的轉換邏輯
                # 1. 解析 text_content 抓出 Step 4 的表格 Markdown
                # 2. 使用 python-docx 建立 Table
                # 3. 填入資料
                # 4. 回傳 binary data
                return text_content.encode("utf-8") # 暫時回傳純文字
                
            # 下載按鈕
            word_data = generate_word_report(response.text)
            st.download_button(
                label="📥 下載 Word 報告 (.docx)",
                data=word_data,
                file_name="智慧審題報告.docx", # 未來改為 .docx
                mime="text/plain" # 未來改為 application/vnd.openxmlformats...
            )

        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e):
                st.warning("💡 提示：目前 AI 忙線中，請稍後再試，或於側邊欄切換其他模型。")
