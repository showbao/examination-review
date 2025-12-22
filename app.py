import streamlit as st
import google.generativeai as genai
import sys

st.set_page_config(page_title="系統診斷模式", page_icon="🕵️‍♀️")
st.title("🕵️‍♀️ 系統診斷模式 (Diagnostics)")

# --- 1. 檢查套件版本 ---
st.subheader("1. 環境版本檢查")
try:
    st.write(f"**Python 版本:** `{sys.version.split()[0]}`")
    # 嘗試讀取 SDK 版本
    try:
        st.write(f"**Google GenAI SDK 版本:** `{genai.__version__}`")
    except:
        st.error("⚠️ 無法讀取 SDK 版本 (可能版本過舊)")
except Exception as e:
    st.error(f"環境讀取錯誤: {e}")

# --- 2. 測試 API 連線與模型列表 ---
st.subheader("2. 模型清單掃描")
st.write("正在嘗試詢問 Google 伺服器有哪些模型可用...")

try:
    # 讀取 Key
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)

    # 列出所有可用模型
    available_models = []
    for m in genai.list_models():
        # 只列出可以生成文字的模型
        if 'generateContent' in m.supported_generation_methods:
            available_models.append(m.name)
    
    if available_models:
        st.success(f"✅ 連線成功！共找到 {len(available_models)} 個可用模型：")
        st.json(available_models) # 直接把清單印出來
    else:
        st.warning("⚠️ 連線成功，但回傳的模型列表是空的 (可能區域限制或 Key 權限問題)。")

except Exception as e:
    st.error("❌ 連線失敗！錯誤訊息如下：")
    st.code(str(e))

# --- 3. 測試最基本的舊模型 ---
st.subheader("3. 最終測試")
if st.button("嘗試用 gemini-pro (舊版穩定款) 測試對話"):
    try:
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content("Hello")
        st.success(f"回覆成功: {response.text}")
    except Exception as e:
        st.error(f"測試失敗: {e}")
