import streamlit as st
import google.generativeai as genai
from io import BytesIO
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# --- 1. 環境設定與套件載入 ---
st.set_page_config(page_title="國小試卷 AI 審題系統 (旗艦版)", page_icon="💯", layout="wide")

# 嘗試匯入 PDF 處理套件 (相容性處理)
try:
    from pypdf import PdfReader
except ImportError:
    import PyPDF2 as PdfReader

# --- 2. 側邊欄：設定與資訊 ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2997/2997292.png", width=80)
    st.title("⚙️ 審題控制台")
    
    st.markdown("### 🎯 審題重點")
    check_zhuyin = st.checkbox("國語：檢查注音與字詞", value=True)
    check_logic = st.checkbox("數理：檢查圖表邏輯", value=True)
    check_rec = st.checkbox("建議：提供優化推薦", value=True)
    
    st.markdown("---")
    strictness = st.slider("嚴格程度 (1=鼓勵為主, 5=極度嚴格)", 1, 5, 4)
    
    st.markdown("---")
    st.success("🧠 模型載入中：\nGemini 3.0 Pro (Preview)")
    st.caption("目前使用您帳號中最強大的 Index 27 模型，具備最先進的邏輯推理能力。")

# --- 3. 主畫面設計 ---
st.title("💯 國小試卷 AI 審題系統")
st.markdown(
    """
    <style>
    .big-font { font-size:18px !important; color: #555; }
    </style>
    <div class='big-font'>
    專為國小老師打造的智慧助手。上傳 PDF 試卷，AI 將針對<b>「國語注音」</b>、<b>「圖形邏輯」</b>與<b>「試題品質」</b>進行深度健檢。
    </div>
    """, 
    unsafe_allow_html=True
)

# --- 4. API 連線設定 (從 Secrets 讀取) ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    # 【關鍵修改】鎖定您清單中的第 27 項：最強 3.0 Pro 預覽版
    model = genai.GenerativeModel('models/gemini-3-pro-preview')
except Exception as e:
    st.error("❌ API Key 設定錯誤，請檢查 Streamlit Secrets。")
    st.stop()

# --- 5. 檔案處理核心 ---
uploaded_file = st.file_uploader("📂 請將試卷 PDF 拖曳至此 (支援國語、數學、自然、社會)", type=['pdf'])

if uploaded_file is not None:
    st.info(f"📄 已讀取檔案：{uploaded_file.name}，準備進行 AI 分析...")

    # 建立分析按鈕
    if st.button("🚀 啟動 Gemini 3.0 深度審題", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            # 階段 A: 讀取 PDF 文字
            status_text.text("🔍 正在進行光學字元分析 (OCR)...")
            progress_bar.progress(20)
            
            try:
                reader = PdfReader(uploaded_file)
                text_content = ""
                for page in reader.pages:
                    text_content += page.extract_text() + "\n"
            except Exception as e:
                st.error(f"PDF 讀取失敗：{e}")
                st.stop()

            # 階段 B: 建構超級提示詞 (Prompt Engineering)
            status_text.text("🧠 Gemini 3.0 正在進行深度邏輯推理...")
            progress_bar.progress(50)

            # 根據側邊欄勾選，動態調整指令
            focus_areas = []
            if check_zhuyin: focus_areas.append("【國語科重點】：嚴格檢查注音符號使用是否規範、是否有錯別字、語句是否通順。")
            if check_logic: focus_areas.append("【數理科重點】：檢查題目敘述與圖表（若文字有描述）的邏輯一致性，確認數據合理性。")
            if check_rec: focus_areas.append("【優化推薦】：針對題目鑑別度提供具體修改建議。")
            
            focus_text = "\n".join(focus_areas)

            prompt = f"""
            你是一位擁有 20 年經驗的國小資深教務主任與命題教授。
            請使用目前最強大的 'Gemini 3.0 Pro' 邏輯能力，針對這份試卷進行「逐題審查」。

            🎯 **審題目標與要求：**
            1. **嚴格度**：{strictness} 分 (滿分 5 分)
            2. **分析重點**：
            {focus_text}

            ---
            
            📝 **請輸出結構化的審題報告 (請直接使用繁體中文)：**

            ### 1. 試卷整體概況
            * **適用年級推測**：(請依內容判斷)
            * **難易度分析**：(太簡單/適中/偏難)
            * **知識點分佈**：(涵蓋了哪些單元)

            ### 2. 深度問題審查 (請列點說明)
            * **❌ 潛在錯誤與風險**：
                * (例如：第 3 題的題意敘述不清，容易造成學生誤解...)
                * (例如：國語注音 'ㄅ' 的使用情境似乎有誤...)
                * (例如：數學應用題的數字邏輯不合理...)
            
            * **⚠️ 圖形與排版檢核 (文字邏輯推論)**：
                * (請根據題目文字，檢查是否有 '如圖所示' 但敘述不完整的情況)
            
            ### 3. 優點與亮點
            * (這份試卷出得好的地方)

            ### 4. 具體修改建議 (Action Items)
            * (請針對上述錯誤，給出具體的改寫範例)

            ---
            **試卷原始文字內容：**
            {text_content[:20000]}
            """

            # 階段 C: 呼叫 AI
            response = model.generate_content(prompt)
            ai_report = response.text
            
            progress_bar.progress(90)
            status_text.text("📝 正在生成 Word 報表...")

            # 階段 D: 製作精美 Word 檔
            doc = Document()
            
            # Word 標題樣式
            title = doc.add_heading('國小試卷 AI 審題報告', 0)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER
            
            doc.add_paragraph(f"審題模型：Gemini 3.0 Pro Preview (Index 27)")
            doc.add_paragraph(f"檔案名稱：{uploaded_file.name}")
            doc.add_paragraph(f"審題時間：{strictness}/5 嚴格度")
            doc.add_paragraph("-" * 40)
            
            # 寫入 AI 內容
            doc.add_paragraph(ai_report)
            
            # 存入記憶體
            bio = BytesIO()
            doc.save(bio)
            
            progress_bar.progress(100)
            status_text.text("✅ 分析完成！")
            st.balloons()

            # --- 6. 顯示結果與下載 ---
            st.markdown("---")
            st.subheader("📊 審題報告預覽")
            st.write(ai_report)
            
            st.markdown("### 📥 下載專區")
            st.download_button(
                label="下載 Word 完整報告 (.docx)",
                data=bio.getvalue(),
                file_name=f"審題報告_{uploaded_file.name}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary"
            )

        except Exception as e:
            st.error(f"分析過程發生錯誤：{e}")
            st.warning("💡 若長時間無回應，可能是 3.0 Pro 預覽版正忙碌，請稍後再試。")
