import streamlit as st
import google.generativeai as genai

# --- 設定頁面資訊 ---
st.set_page_config(page_title="試題審題系統 - 連線測試", page_icon="📝")

st.title("📝 試題審題系統 (MVP)")
st.subheader("系統連線狀態檢查")

# --- 1. 檢查 API Key 是否設定 ---
# 我們使用 Streamlit Secrets 來管理密碼，避免直接暴露在程式碼中
api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.success("✅ API Key 設定檢測通過")
except FileNotFoundError:
    st.error("❌ 尚未設定 API Key。請在 Streamlit Cloud 的 Secrets 設定中添加。")
    st.stop() # 停止執行後續程式
except Exception as e:
    st.error(f"❌ 發生未預期的錯誤: {e}")
    st.stop()

# --- 2. 設定 Gemini 模型 ---
# 使用目前穩定的 Pro 版本，若未來有新版，修改 model_name 即可
MODEL_NAME = "gemini-2.5-pro" 

try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    st.info(f"🤖 目前使用的 AI 模型: {MODEL_NAME}")
except Exception as e:
    st.error(f"❌ Gemini 設定失敗: {e}")
    st.stop()

# --- 3. 介面互動區 ---
st.markdown("---")
st.write("請輸入一段測試文字，確認 AI 能否回應：")

user_input = st.text_area("輸入測試內容", "你好，請幫我分析這是一個什麼樣的系統？")

if st.button("開始分析"):
    if not user_input:
        st.warning("請輸入內容！")
    else:
        with st.spinner("Gemini 正在思考中..."):
            try:
                # 呼叫 Gemini
                response = model.generate_content(user_input)
                
                # 顯示結果
                st.success("分析完成！")
                st.markdown("### AI 回應結果：")
                st.write(response.text)
                
            except Exception as e:
                st.error(f"連線發生錯誤: {e}")
                st.write("建議檢查 API Key 是否正確，或配額是否用完。")

# --- 底部版權資訊 ---
st.markdown("---")
st.caption("全能技術長 (CTO) 協助建置 | v0.1.0 Connection Test")
