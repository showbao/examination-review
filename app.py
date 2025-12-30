import streamlit as st
import google.generativeai as genai
import os
import time
from docx import Document  # 預留給 Word 生成模組

# ==========================================
# 0. 視覺風格設定 (莫蘭迪色系 & CSS)
# ==========================================
st.set_page_config(page_title="北屯區建功國小AI審題系統", page_icon="📝", layout="wide")

# 定義莫蘭迪色系
# 主色 (Sage Green): #8DA399
# 深色 (Slate Blue): #5B7C99
# 背景 (Mist Grey): #F5F7F7
morandi_css = """
<style>
    .stApp { background-color: #F5F7F7; }
    h1, h2, h3 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; }
    
    /* 按鈕樣式 */
    div.stButton > button {
        background-color: #8DA399;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
    }
    div.stButton > button:hover {
        background-color: #6E8B7F;
        color: white;
        border: 1px solid #6E8B7F;
    }
    
    /* 資訊看板樣式 */
    .dashboard-card {
        background-color: #E8ECEC;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #8DA399;
        margin-bottom: 20px;
        color: #4A4A4A;
    }
    
    /* 頁尾樣式 */
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #F5F7F7;
        color: #888;
        text-align: center;
        padding: 10px;
        font-size: 12px;
        border-top: 1px solid #ddd;
        z-index: 999;
    }
    .footer-spacer { height: 50px; }
</style>
"""
st.markdown(morandi_css, unsafe_allow_html=True)

# ==========================================
# 1. 登入與免責聲明
# ==========================================

def render_footer():
    st.markdown('<div class="footer-spacer"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer">Designed for 臺中市北屯區建功國小 | Powered by Gemini 3.0</div>', 
        unsafe_allow_html=True
    )

def check_password():
    """帶有免責聲明的登入系統"""
    if st.session_state.get("password_correct", False):
        return True

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🔒 北屯區建功國小 AI 審題系統")
        
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
    
    render_footer()
    return False

if not check_password():
    st.stop()

# ==========================================
# 2. 核心邏輯：模型管理 (嚴格白名單)
# ==========================================

def get_smart_model_list(api_key):
    """
    智慧篩選模型：
    1. 嚴格過濾：剔除 Nano, Banana, Legacy, Experimental
    2. 智慧排序：Gemini 3.0 > 2.0 > Pro > Flash
    """
    genai.configure(api_key=api_key)
    models = []
    try:
        all_models = genai.list_models()
        for m in all_models:
            if 'generateContent' in m.supported_generation_methods:
                name = m.name.lower()
                
                # [嚴格白名單檢查]
                # 必須是 gemini 系列，且包含 pro, flash 或 thinking
                if "gemini" not in name: continue
                if not any(t in name for t in ["pro", "flash", "thinking"]): continue
                
                # [黑名單檢查] 雙重保險，絕對踢除手機版與舊版
                if any(x in name for x in ["nano", "banana", "pixel", "vision-legacy", "001"]):
                    continue
                
                # 權重計分
                score = 0
                if "gemini-3" in name: score += 10000
                elif "gemini-2.5" in name: score += 8000
                elif "gemini-2.0" in name: score += 6000
                elif "gemini-1.5" in name: score += 2000
                
                if "thinking" in name: score += 1500
                if "pro" in name: score += 1000
                if "flash" in name: score += 500
                
                models.append((m.display_name, m.name, score))
        
        models.sort(key=lambda x: x[2], reverse=True)
        return [(m[0], m[1]) for m in models[:5]] # 只回傳前5名
    except:
        return [("Gemini 1.5 Pro (Fallback)", "models/gemini-1.5-pro")]

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
# 3. 主畫面設計 (Main Dashboard)
# ==========================================

# 初始化 Session State (用於結果保留)
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

st.title("北屯區建功國小AI審題系統")

# --- A. 智慧控制儀表板 (取代側邊欄) ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
    model_options = get_smart_model_list(api_key)
else:
    st.error("請設定 Secrets: GEMINI_API_KEY")
    st.stop()

# 儀表板 UI
with st.container():
    col_dash_1, col_dash_2 = st.columns([3, 1])
    with col_dash_1:
        st.markdown("""
        <div class="dashboard-card">
            <b>⚪ 系統狀態：</b>待命中... 請上傳試卷以啟動 AI 自動識別<br>
            <small>預設啟用：自動科目路由 (數學科優先掛載 Gemini 3.0 Pro)</small>
        </div>
        """, unsafe_allow_html=True)
    with col_dash_2:
        with st.expander("⚙️ 手動模型設定"):
            model_mode = st.radio("模式", ["自動路由", "手動指定"], label_visibility="collapsed")
            if model_mode == "手動指定":
                selected_model_tuple = st.selectbox("核心", model_options, label_visibility="collapsed")
                selected_model_id = selected_model_tuple[1]
            else:
                selected_model_id = model_options[0][1] # 自動模式預設拿最高分的

# --- B. 雙欄上傳區 (左：試卷 / 右：教材) ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("1️⃣ 上傳試卷 (必選)")
    st.caption("支援 PDF/圖片，AI 將自動判讀科目與數學公式")
    exam_file = st.file_uploader("請拖曳檔案至此", type=["pdf", "jpg", "png"], key="exam_uploader")

with col2:
    st.subheader("2️⃣ 上傳課本、習作 (可選)")
    st.caption("若未上傳，系統將跳過「命題範圍」檢核")
    context_files = st.file_uploader("請拖曳檔案至此", type=["pdf"], accept_multiple_files=True, key="context_uploader")

# --- C. 單元設定區 (移至主畫面) ---
st.markdown("---")
st.subheader("📝 雙向細目表設定")
col_unit_1, col_unit_2 = st.columns([1, 4])
with col_unit_1:
    unit_count = st.number_input("單元數量", min_value=1, max_value=10, value=3)
with col_unit_2:
    unit_list = []
    # 動態產生輸入框 (橫向排列)
    cols = st.columns(unit_count)
    for i in range(unit_count):
        with cols[i]:
            u_name = st.text_input(f"單元 {i+1}", placeholder=f"單元名稱", key=f"unit_{i}")
            if u_name:
                unit_list.append(u_name)

# ==========================================
# 4. 審查邏輯與 Prompt (含素養標準)
# ==========================================

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

st.markdown("---")

# 當按下開始按鈕，執行分析並存入 session_state
if st.button("🚀 開始全方位審查", type="primary", use_container_width=True):
    if not exam_file:
        st.warning("❌ 請務必上傳一份「試卷」！")
    else:
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
            
            # 2. 建構超級 Prompt
            status_box.info("🧠 AI 正在識別科目並建構指令...")
            
            units_str = ", ".join(unit_list) if unit_list else "未提供 (請自行判斷)"
            
            base_prompt = f"""
你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。請依照以下步驟審查這份【待審試卷】。

**【重要輸出規範】：**
1. **嚴禁**在標題後方加上「(模組A)」、「(模組B)」等內部代號。
2. **燈號置前**：所有的燈號（🟢、🟡、🔴、⚠️）或圖示，必須放在每一行的**最前面**。例如：「🔴 第 5 題：...」。

**前置作業：**
1. 請先判斷這份試卷的科目。若是數學/自然科，請啟動深度推理模式。

請嚴格依照以下 6 大步驟輸出 Markdown 報告：

---
### Step 1: 命題範圍與合規性
* 若有上傳教材：請比對並標示 🟢通過 / 🔴超綱。
* **若無上傳教材，請直接輸出警語：「⚠️ 未檢查命題範圍：未上傳教材，故未檢查命題範圍，請老師務必自行審示題目的適切性。」** (不需輸出其他內容)

### Step 2: 題幹與邏輯品質
* 檢查語意歧義、邏輯謬誤。
* 輸出格式範例：
    * 🟡 **第 3 題**：題幹語意不清，建議修改...

### Step 3: 素養導向深度審查
**請依據下列標準執行「剝皮測試」，並挑選 5-10 題具代表性題目進行分析：**
{LITERACY_STANDARDS}

* 輸出格式範例：
    * 🔴 **第 X 題 [假素養]**：(原因說明...)
    * 🟢 **第 Y 題 [真素養]**：(原因說明...)

### Step 4: 雙向細目表核算
**指定單元範圍：** {units_str}

* **情況 A (若有提供單元名稱 且 有上傳教材)：** 請製作標準雙向細目表 (含單元名稱 vs 知識向度)。
* **情況 B (若缺一)：** 請製作簡易向度分析表 (知識向度 | 對應題號 | 題數佔比)。

### Step 5: 難易度與負擔分析
* 請以表格呈現：難易度分佈、預估閱讀量、作答步驟數。

### Step 6: 總結與建議
* 👍 **值得讚許之處：** (條列)
* 💡 **具體修改建議：** (條列)

---
"""
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
            
            # 儲存結果到 Session State
            st.session_state.analysis_result = response.text
            
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e):
                st.warning("💡 提示：目前 AI 忙線中，請稍後再試。")

# ==========================================
# 5. 顯示結果與下載區 (Result Persistence)
# ==========================================

if st.session_state.analysis_result:
    st.markdown("## 📊 審查報告")
    st.markdown(st.session_state.analysis_result)
    
    # Word 生成預留函式
    def generate_word_report(text_content):
        # 這裡未來會實作 Markdown 轉 Word 邏輯
        return text_content.encode("utf-8")
        
    word_data = generate_word_report(st.session_state.analysis_result)
    
    st.download_button(
        label="📥 下載 Word 報告 (.docx)",
        data=word_data,
        file_name="建功國小_AI審題報告.docx",
        mime="text/plain",
        key="download_btn" # 給予 key 避免重複刷新導致問題
    )

render_footer()
