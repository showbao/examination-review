import streamlit as st
import google.generativeai as genai

# --- 1. 設定頁面 ---
st.set_page_config(page_title="國小試卷審題系統", page_icon="📝")
st.title("📝 國小試卷審題系統 (AI 連線測試版)")

# --- 2. 連結 AI 大腦 (從 Secrets 拿鑰匙) ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash') # 使用最新快速模型
    st.success("✅ AI 大腦連線成功！")
except Exception as e:
    st.error("❌ API Key 設定失敗，請檢查 Streamlit Secrets。")
    st.stop() # 若沒鑰匙，程式停止執行

# --- 3. 簡單的測試介面 ---
st.markdown("### 🤖 AI 對話測試")
st.info("這裡是用來測試你的 API Key 是否有效的，請隨便輸入一句話。")

user_input = st.text_input("請輸入測試訊息 (例如：用一句話形容國小老師的辛酸)：")

if st.button("送出測試"):
    if user_input:
        with st.spinner("AI 正在思考中..."):
            try:
                # 呼叫 AI
                response = model.generate_content(user_input)
                st.write("### 💡 AI 回覆：")
                st.success(response.text)
            except Exception as e:
                st.error(f"連線錯誤：{e}")
    else:
        st.warning("請先輸入文字喔！")
