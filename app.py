import streamlit as st
import google.generativeai as genai
import time

# ==========================================
# 1. 系統初始化與登入驗證 (Auth)
# ==========================================
st.set_page_config(page_title="智慧試卷審題系統", page_icon="📝", layout="wide")

def check_password():
    """簡易密碼驗證"""
    # 如果已經登入成功，直接回傳 True
    if st.session_state.get("password_correct", False):
        return True

    # 顯示登入介面
    st.markdown("## 🔒 請登入系統")
    password = st.text_input("請輸入學校專用通行碼", type="password")
    
    if st.button("登入"):
        # 比對 Streamlit Cloud 設定的密碼
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("❌ 密碼錯誤，請重新輸入。")
    return False

# 如果還沒登入，就卡在這裡，不執行後續程式
if not check_password():
    st.stop()

# ==========================================
# 2. 核心邏輯函式 (Backend Logic)
# ==========================================

def get_available_models(api_key):
    """自動偵測帳號可用的 Gemini 模型"""
    genai.configure(api_key=api_key)
    models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                # 只抓取 1.5 和 2.0/3.0 系列
                if "gemini" in m.name:
                    models.append((m.display_name, m.name))
        # 排序：讓新模型排前面
        models.sort(key=lambda x: x[1], reverse=True)
    except Exception as e:
        st.error(f"模型列表獲取失敗: {e}")
        # 萬一失敗，給一個預設值
        models = [("Gemini 1.5 Flash", "models/gemini-1.5-flash")]
    return models

def upload_to_gemini(file_obj):
    """將檔案上傳到 Gemini"""
    try:
        # 寫入暫存
        import tempfile
        import os
        suffix = ".pdf" if file_obj.name.endswith(".pdf") else ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_obj.getvalue())
            tmp_path = tmp.name

        # 上傳
        file_ref = genai.upload_file(tmp_path, mime_type="application/pdf" if suffix == ".pdf" else "image/jpeg")
        
        # 等待處理
        while file_ref.state.name == "PROCESSING":
            time.sleep(1)
            file_ref = genai.get_file(file_ref.name)
        
        os.remove(tmp_path) # 刪除本地暫存
        return file_ref
    except Exception as e:
        st.error(f"上傳失敗: {e}")
        return None

# ==========================================
# 3. 使用者介面 (UI)
# ==========================================
st.title("📝 AI 智慧試卷審題系統 (雲端版)")

# --- 側邊欄：模型選擇 ---
with st.sidebar:
    st.header("⚙️ 系統設定")
    
    # 從 Secrets 讀取 API Key
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        
        # 自動抓取模型清單
        available_models = get_available_models(api_key)
        selected_model_name, selected_model_id = st.selectbox(
            "🧠 選擇 AI 模型",
            available_models,
            format_func=lambda x: x[0], # 顯示顯示名稱
            index=0
        )
        st.caption(f"目前使用核心: `{selected_model_id}`")
    else:
        st.error("⚠️ 未偵測到 API Key，請在 Streamlit Secrets 設定。")
        st.stop()

# --- 主畫面：檔案上傳 ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("1️⃣ 上傳教材/課本 (可選)")
    st.info("若未上傳，將自動跳過「範圍檢核」。")
    context_files = st.file_uploader(
        "支援 PDF (可多選)", 
        type=["pdf"], 
        accept_multiple_files=True
    )

with col2:
    st.subheader("2️⃣ 上傳試卷 (必選)")
    exam_file = st.file_uploader("支援 PDF/圖片", type=["pdf", "jpg", "png"])

# --- 分析按鈕與邏輯 ---
st.markdown("---")

if st.button("🚀 開始全方位審查", type="primary"):
    if not exam_file:
        st.warning("❌ 請務必上傳一份「試卷」！")
    else:
        status_text = st.empty()
        status_bar = st.progress(0)
        
        try:
            # 1. 準備 AI
            model = genai.GenerativeModel(selected_model_id)
            prompt_parts = []
            
            # 2. 處理試卷 (必選)
            status_text.text("正在讀取試卷內容...")
            status_bar.progress(20)
            exam_ref = upload_to_gemini(exam_file)
            
            # 3. 處理教材 (可選)
            has_context = False
            if context_files:
                status_text.text(f"正在讀取 {len(context_files)} 份教材內容...")
                status_bar.progress(40)
                
                prompt_parts.append("【參考教材/課本範圍】：")
                for c_file in context_files:
                    c_ref = upload_to_gemini(c_file)
                    prompt_parts.append(c_ref)
                has_context = True
            
            # 4. 構建動態提示詞 (Prompt Engineering)
            status_text.text("正在組裝分析指令...")
            status_bar.progress(60)
            
            base_prompt = """
你是一位擁有 20 年經驗的資深教育專家與試卷審查委員。請針對這份【待審查試卷】進行深度分析。

請嚴格依照以下架構輸出分析報告：

"""
            # 邏輯分支：有沒有教材？
            if has_context:
                base_prompt += """
### 1. 命題範圍與合規性檢核
* **任務**：請嚴格比對試卷題目是否超出提供的【參考教材】範圍。
* **輸出**：若有超綱，請列出題號、題目摘要，以及它屬於哪個未教學的單元。若無，請明確標示「符合教學範圍」。
"""
            else:
                base_prompt += """
### 1. 命題範圍與合規性檢核
* *(註：因使用者未提供參考教材，本項略過不計)*
"""

            # 接續其餘通用指標
            base_prompt += """
### 2. 題幹與邏輯品質審查
* 檢查題目敘述是否語意不清、有歧義？
* 檢查選項設計是否有邏輯謬誤？
* 檢查標準答案是否有爭議？

### 3. 素養導向深度審查
* 評估題目是否符合「素養導向」設計（情境化、跨領域、解決問題能力）？
* 指出哪些題目僅是死背記憶，缺乏素養成分。

### 4. 雙向細目表核算 (預估)
* 請嘗試分析整份試卷的知識向度（記憶、理解、應用、分析、評鑑、創造）分佈比例。
* 以表格呈現分佈情形。

### 5. 難易度與負擔分析
* 預估這份試卷對該年級學生的作答負擔量（閱讀量、計算量）。
* 預估整份試卷的難易度分佈（易/中/難 比例）。

### 6. 總結與優化建議
* 給予命題老師的具體修改建議（條列式）。
* 總體評分（1-10分）與短評。

請以 Markdown 格式輸出，確保標題清晰，重點文字請加粗。
"""
            # 組合最終請求
            prompt_parts.append(base_prompt)
            prompt_parts.append("【待審查試卷】：")
            prompt_parts.append(exam_ref)
            
            # 5. 發送給 Gemini
            status_text.text("AI 正在進行深度審查 (可能需要 30~60 秒)...")
            status_bar.progress(80)
            
            response = model.generate_content(prompt_parts)
            
            status_bar.progress(100)
            status_text.text("分析完成！")
            
            # 6. 顯示結果
            st.markdown("### 📊 審查報告結果")
            st.markdown(response.text)
            
            # 下載按鈕 (暫存 Markdown，後續可升級 Word)
            st.download_button(
                label="📥 下載報告 (Markdown)",
                data=response.text,
                file_name="審題分析報告.md",
                mime="text/markdown"
            )

        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e):
                st.warning("💡 提示：目前使用人數過多，請稍等 1 分鐘後再試。")
