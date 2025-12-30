import streamlit as st
import google.generativeai as genai
import os
import time
import json
import re
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

# ==========================================
# 0. 視覺風格設定 (莫蘭迪色系 & CSS - 放大與層級修正版)
# ==========================================
st.set_page_config(page_title="北屯區建功國小AI審題系統", page_icon="📝", layout="wide")

morandi_css = """
<style>
    /* 全站字體放大 */
    html, body, [class*="css"] {
        font-size: 20px; 
    }
    
    .stApp { background-color: #F5F7F7; }
    
    /* 標題層級與大小調整 (v3.3) */
    /* H1: 主標題 */
    h1 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 2.5rem !important; }
    
    /* H2: 用於 Step 1~6 大步驟標題 (放大) */
    h2 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 2.2rem !important; font-weight: bold !important; }
    
    /* H3: 用於紅綠燈區塊標題 (縮小) */
    h3 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 1.3rem !important; font-weight: normal !important; }
    
    /* 按鈕樣式放大 */
    div.stButton > button {
        background-color: #8DA399; color: white; border-radius: 8px; border: none; 
        padding: 12px 28px; 
        font-weight: bold;
        font-size: 1.1rem; 
    }
    div.stButton > button:hover { background-color: #6E8B7F; color: white; border: 1px solid #6E8B7F; }
    
    /* 資訊看板樣式放大 */
    .dashboard-card {
        background-color: #E8ECEC; padding: 20px; border-radius: 10px; border-left: 6px solid #8DA399; 
        margin-bottom: 25px; color: #4A4A4A;
        font-size: 1.1rem; 
    }
    
    .footer {
        position: fixed; left: 0; bottom: 0; width: 100%; background-color: #F5F7F7; color: #888; text-align: center; padding: 15px; font-size: 14px; border-top: 1px solid #ddd; z-index: 999;
    }
    .footer-spacer { height: 60px; }
</style>
"""
st.markdown(morandi_css, unsafe_allow_html=True)

# ==========================================
# 1. 輔助函式：模型管理與 Word 生成
# ==========================================

def get_best_flash_model(api_key):
    genai.configure(api_key=api_key)
    try:
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and "flash" in m.name.lower() and "gemini" in m.name.lower()]
        models.sort(key=lambda x: x.name, reverse=True)
        return models[0].name if models else "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

def get_best_pro_model(api_key):
    genai.configure(api_key=api_key)
    try:
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and "pro" in m.name.lower() and "gemini" in m.name.lower()]
        models.sort(key=lambda x: x.name, reverse=True)
        return models[0].name if models else "models/gemini-1.5-pro"
    except: return "models/gemini-1.5-pro"

def upload_to_gemini(file_obj):
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

# --- Word 生成核心邏輯 (v3.3 修正版) ---
def set_font_style(run, size=12, bold=False, color=None):
    """設定字體為標楷體 + Times New Roman"""
    run.font.name = 'Times New Roman'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '標楷體')
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color

def clean_markdown_symbol(text):
    """移除 Markdown 符號與燈號圖示，只保留純文字，並再次確保無 <br>"""
    # 移除 <br> (雙重保險)
    text = text.replace("<br>", "").replace("<br/>", "").replace("<br />", "")
    
    # 移除 Markdown 強調
    text = text.replace("**", "")
    text = text.replace("##", "")
    text = text.replace("###", "") # v3.3 新增移除三級標題符號
    text = text.lstrip("#")
    
    # 移除燈號圖示 (Word 不顯示圖示，改用顏色區分)
    for icon in ["🟢", "🔴", "🟡", "⚠️", "👍", "💡"]:
        text = text.replace(icon, "")
        
    return text.strip()

def create_word_report(analysis_text, metadata):
    doc = Document()
    
    # 1. 設定邊界 (1.27 cm)
    for section in doc.sections:
        section.top_margin = Cm(1.27)
        section.bottom_margin = Cm(1.27)
        section.left_margin = Cm(1.27)
        section.right_margin = Cm(1.27)

    # 設定預設樣式
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '標楷體')
    style.font.size = Pt(12)

    # 標題
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_p.add_run("臺中市北屯區建功國小評量AI審題報告")
    set_font_style(run, size=18, bold=True)
    doc.add_paragraph()

    # 卷頭資訊
    table = doc.add_table(rows=4, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    info_data = [
        ("學年度：", metadata.get("year", "   "), "學期：", metadata.get("semester", "   ")),
        ("年級：", metadata.get("grade", "   "), "科目：", metadata.get("subject", "   ")),
        ("評量類別：", metadata.get("exam_type", "   "), "審查日期：", time.strftime("%Y/%m/%d")),
        ("命題者簽名：", "          ", "審題者簽名：", "          ")
    ]
    for row_idx, row_data in enumerate(info_data):
        row = table.rows[row_idx]
        for col_idx, text in enumerate(row_data):
            cell = row.cells[col_idx]
            p = cell.paragraphs[0]
            run = p.add_run(text)
            set_font_style(run, size=12, bold=(col_idx % 2 == 0))
            
    doc.add_paragraph()

    # 內容解析
    lines = analysis_text.split('\n')
    table_mode = False
    table_data = []

    for line in lines:
        line = line.strip()
        if not line: continue

        # 處理 Step 標題 (Markdown ##)
        # v3.3 邏輯：Step 標題在 Prompt 中改為 ## (H2)
        if line.startswith("## ") and not any(x in line for x in ["🟢", "🔴", "🟡", "👍", "💡"]):
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            
            clean_text = clean_markdown_symbol(line)
            p = doc.add_paragraph()
            run = p.add_run(clean_text)
            set_font_style(run, size=16, bold=True, color=RGBColor(91, 124, 153)) # 標題藍色，大字
        
        # 處理分類小標題 (Markdown ### 🟢 / 🔴 / 🟡)
        # v3.3 邏輯：紅綠燈標題在 Prompt 中改為 ### (H3)
        elif line.startswith("###") or (line.startswith("##") and any(x in line for x in ["🟢", "🔴", "🟡", "👍", "💡"])):
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []

            is_green = "🟢" in line or "優良" in line or "真素養" in line
            is_red = "🔴" in line or "待改善" in line or "假素養" in line
            is_yellow = "🟡" in line or "建議" in line

            clean_text = clean_markdown_symbol(line)
            p = doc.add_paragraph()
            run = p.add_run(clean_text)
            
            # 依據燈號給顏色
            if is_green:
                set_font_style(run, size=13, bold=True, color=RGBColor(0, 100, 0)) # 深綠
            elif is_red:
                set_font_style(run, size=13, bold=True, color=RGBColor(200, 0, 0)) # 深紅
            elif is_yellow:
                set_font_style(run, size=13, bold=True, color=RGBColor(204, 153, 0)) # 深黃
            else:
                set_font_style(run, size=13, bold=True)

        # 處理表格
        elif line.startswith("|"):
            table_mode = True
            if "---" in line: continue
            row_cells = [clean_markdown_symbol(c) for c in line.split("|") if c.strip()]
            table_data.append(row_cells)
            
        # 處理列表
        elif line.startswith("*") or line.startswith("-"):
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            
            clean_text = clean_markdown_symbol(line.lstrip("*- "))
            
            # 檢查是否為空字串
            if not clean_text:
                continue

            p = doc.add_paragraph(style='List Bullet')
            run = p.add_run(clean_text)
            set_font_style(run, size=12)
            
        # 一般文字
        else:
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            clean_text = clean_markdown_symbol(line)
            if not clean_text: continue 
            
            p = doc.add_paragraph(clean_text)
            set_font_style(p.runs[0] if p.runs else p.add_run(clean_text), size=12)

    if table_mode and table_data:
        _render_word_table(doc, table_data)

    # 教師回饋區
    doc.add_paragraph() 
    p = doc.add_paragraph()
    run = p.add_run("命題教師修改及說明")
    set_font_style(run, size=14, bold=True, color=RGBColor(91, 124, 153))
    
    feedback_table = doc.add_table(rows=1, cols=1)
    feedback_table.style = 'Table Grid'
    cell = feedback_table.cell(0, 0)
    for _ in range(8): 
        cell.add_paragraph()

    from io import BytesIO
    f = BytesIO()
    doc.save(f)
    return f.getvalue()

def _render_word_table(doc, data):
    if not data: return
    rows = len(data)
    cols = len(data[0])
    table = doc.add_table(rows=rows, cols=cols)
    table.style = 'Table Grid'
    for r in range(rows):
        for c in range(min(cols, len(data[r]))):
            cell = table.cell(r, c)
            cell.text = data[r][c]
            for p in cell.paragraphs:
                for run in p.runs:
                    set_font_style(run, size=10)
            if r == 0:
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.bold = True

# ==========================================
# 2. 登入與介面
# ==========================================
def render_footer():
    st.markdown('<div class="footer-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div class="footer">Designed for 臺中市北屯區建功國小 | Powered by Gemini 3.0</div>', unsafe_allow_html=True)

def check_password():
    if st.session_state.get("password_correct", False): return True
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🔒 北屯區建功國小 AI 審題系統")
        with st.expander("⚠️ 使用前請務必詳閱免責聲明 (點擊展開)", expanded=True):
            st.markdown("""
            **使用前請詳閱以下說明：**
            1. **本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。**
            2. **人工查核機制**：AI 生成內容可能存在誤差，最終試卷定稿請務必回歸教師專業判斷。
            3. **資料隱私安全**：嚴禁上傳包含學生個資、隱私或機密敏感內容之文件。
            4. **授權使用範圍**：本系統無償提供予臺中市北屯區建功國小教師使用，僅限校內使用。
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

if not check_password(): st.stop()

# ==========================================
# 3. 主流程與 Prompt
# ==========================================

if "analysis_result" not in st.session_state: st.session_state.analysis_result = None
if "used_model_name" not in st.session_state: st.session_state.used_model_name = ""
if "metadata" not in st.session_state: st.session_state.metadata = {}

st.title("北屯區建功國小AI審題系統")

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("請設定 Secrets: GEMINI_API_KEY")
    st.stop()

# --- 儀表板 ---
with st.container():
    col_dash_1, col_dash_2 = st.columns([3, 1])
    with col_dash_1:
        st.markdown("""
        <div class="dashboard-card">
            <b>⚪ 系統狀態：</b>待命中... 請上傳試卷，並於檔名標註「科目領域」以啟動 AI 雙階段識別<br>
            <small>啟用檔名路由：檔名含「數/理/化/生」➔ Pro | 其餘 ➔ Flash</small>
        </div>
        """, unsafe_allow_html=True)
    with col_dash_2:
        with st.expander("⚙️ 手動模型設定"):
            model_mode = st.radio("模式", ["依檔名自動路由", "手動指定"], label_visibility="collapsed")
            if model_mode == "手動指定":
                manual_model = st.selectbox("核心", ["Gemini 3.0 Pro", "Gemini 3.0 Flash"], label_visibility="collapsed")

# --- 上傳區 ---
col1, col2 = st.columns(2)
with col1:
    st.subheader("1️⃣ 上傳試卷 (必選)")
    exam_file = st.file_uploader("請拖曳檔案至此", type=["pdf", "jpg", "png"], key="exam_uploader")
with col2:
    st.subheader("2️⃣ 上傳課本、習作 (可選)")
    context_files = st.file_uploader("請拖曳檔案至此", type=["pdf"], accept_multiple_files=True, key="context_uploader")

# --- 單元設定 ---
st.markdown("---")
st.subheader("📝 雙向細目表設定")
col_unit_1, col_unit_2 = st.columns([1, 4])
with col_unit_1:
    unit_count = st.number_input("單元數量", min_value=1, max_value=10, value=3)
with col_unit_2:
    unit_list = []
    cols = st.columns(unit_count)
    for i in range(unit_count):
        with cols[i]:
            u_name = st.text_input(f"單元 {i+1}", placeholder=f"名稱", key=f"unit_{i}")
            if u_name: unit_list.append(u_name)

# --- 審查標準 ---
LITERACY_STANDARDS = """
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

if st.button("🚀 開始全方位審查", type="primary", use_container_width=True):
    if not exam_file:
        st.warning("❌ 請務必上傳一份「試卷」！")
    else:
        status_box = st.empty()
        progress_bar = st.progress(0)
        
        try:
            # ----------------------------------------------------
            # Phase 1: 路由判斷 (依檔名) + 資訊提取 (Flash)
            # ----------------------------------------------------
            filename = exam_file.name
            status_box.info(f"🔍 正在解析試卷資訊... (檔名：{filename})")
            progress_bar.progress(10)

            # 1. 決定模型 (檔名優先)
            is_science = False
            if any(k in filename for k in ["數學", "自然", "理化", "物理", "化學", "生物"]):
                is_science = True
            
            target_model_name = ""
            if model_mode == "手動指定":
                if "Pro" in manual_model: target_model_name = get_best_pro_model(api_key)
                else: target_model_name = get_best_flash_model(api_key)
            else:
                # 檔名路由邏輯
                if is_science:
                    target_model_name = get_best_pro_model(api_key)
                    routing_msg = "📐 檔名含理科關鍵字，強制切換 Gemini 3.0 Pro"
                else:
                    target_model_name = get_best_flash_model(api_key)
                    routing_msg = "📚 預設文科模式，切換 Gemini 3.0 Flash"
                status_box.info(f"🔄 Phase 2: {routing_msg} 進行深度分析...")

            # 2. 資訊提取 (還是跑一下 Flash 抓 Metadata 給 Word 用)
            flash_model = genai.GenerativeModel(get_best_flash_model(api_key))
            exam_ref = upload_to_gemini(exam_file)
            
            meta_prompt = """
            請閱讀這份試卷，並擷取以下資訊，輸出為純 JSON 格式：
            {
                "year": "學年度 (例如 113)",
                "semester": "學期 (例如 第一學期)",
                "grade": "年級 (例如 六年級)",
                "subject": "科目 (例如 數學)",
                "exam_type": "評量類別 (例如 期末評量)"
            }
            如果找不到某些資訊，請填入空白。
            """
            meta_response = flash_model.generate_content([meta_prompt, exam_ref])
            try:
                json_str = meta_response.text.strip()
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                metadata = json.loads(json_str)
            except:
                metadata = {"year":"", "semester":"", "grade":"", "subject":"", "exam_type":""}
            st.session_state.metadata = metadata

            # ----------------------------------------------------
            # Phase 2: 深度審查 (Prompt 升級：強制分組 + 免責條款)
            # ----------------------------------------------------
            main_model = genai.GenerativeModel(target_model_name)
            
            prompt_parts = []
            if context_files:
                for cf in context_files: prompt_parts.append(upload_to_gemini(cf))
            
            units_str = ", ".join(unit_list) if unit_list else "未提供"

            base_prompt = f"""
你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。
目前正在審查：{metadata.get('year')}學年度 {metadata.get('subject')} 試卷。

**【台灣國小教學情境守則 (Contextual Rules)】：**
1. **是非題免責**：在審查「是非題」或「改錯題」時，若題目敘述的錯誤是為了測驗學生觀念（且標準答案正確），**不應視為邏輯誤導**。
2. **在地化教學標準**：針對讀音（如小數讀法）、定義或格式，請以**台灣國小教學現場慣例**為準（例如 3.60015 讀作三點六零零一五是標準，但若通俗讀法不影響數學觀念檢核，請採寬容標準，勿列為嚴重錯誤，除非造成評量爭議）。

**【排版憲法 (Strict Output Rules)】：**
1. **嚴禁開場白**：禁止輸出「依據...」等引言。
2. **禁止頁碼**：題目敘述中**嚴禁提及**「第x頁」。
3. **強制分組歸類 (Grouping)**：
   - 針對 Step 1~3，請務必使用 **二級標題 (##)** 將分析結果歸類。
   - 格式範例：
     ## 🟢 符合範圍 / 優良試題 / 真素養
     * ...
     ## 🔴 超出範圍 / 待改善試題 / 假素養
     * ...
     ## 🟡 建議確認
     * ...
4. **標題層級規範**：
   - 使用 **## (H2)** 作為 Step 1~6 的大標題。
   - 使用 **### (H3)** 作為紅綠燈分類的小標題 (例如 ### 🟢 優良試題)。
5. **強制換行**：每一個項目都必須是獨立的 Bullet Point。

請嚴格依照以下 6 大步驟輸出 Markdown 報告：

---
## Step 1: 命題範圍與合規性
* **請分組**：### 🟢 符合範圍  與  ### 🔴 超出範圍 (若有)。
* 若無上傳教材，請直接輸出警語：「⚠️ 未檢查命題範圍：未上傳教材，故未檢查命題範圍，請老師務必自行審示題目的適切性。」

## Step 2: 題幹與邏輯品質
* **請分組**：### 🟢 優良試題 、 ### 🔴 待改善試題 、 ### 🟡 建議確認。

## Step 3: 素養導向深度審查
**依據下列標準執行「剝皮測試」：**
{LITERACY_STANDARDS}
* **請分組**：### 🟢 真素養 (具體題目分析) 、 ### 🔴 假素養 (具體題目分析)。

## Step 4: 雙向細目表核算
**指定單元範圍：** {units_str}

* **情況 A (若有提供單元名稱)：** 製作標準雙向細目表。
    * 表頭：知識、理解、應用、分析、綜合、評鑑 + 總計
    * 側欄：單元名稱 + 總計
    * 請將對應題號填入表格內。
    * **統計：** 計算百分比重，**務必確認總計為 100%**。

* **情況 B (若無提供單元名稱)：** 製作向度分析表。
    * 表格欄位：知識向度 | 對應題號 | 題數佔比
    * 側欄：(知識/理解/應用/分析/綜合/評鑑) + 總計
    * 請將對應題號填入表格內。
    * **統計：** 務必計算百分比重，總和需為 100%。

## Step 5: 難易度與負擔分析
* 以表格呈現：難易度分佈、預估閱讀量、作答步驟數。

## Step 6: 總結與建議
* **請分組**：### 👍 值得讚許之處 、 ### 💡 具體修改建議。

---
"""
            if context_files: prompt_parts.append("【參考教材】：")
            prompt_parts.append(base_prompt)
            prompt_parts.append("【待審查試卷】：")
            prompt_parts.append(exam_ref)
            
            progress_bar.progress(60)
            response = main_model.generate_content(prompt_parts)
            
            progress_bar.progress(100)
            
            # v3.3 修正：全域清洗 <br> 符號，確保網頁與 Word 顯示正常
            cleaned_text = response.text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            
            status_box.success(f"✅ 分析完成！ (目前使用 AI 模組：{target_model_name})")
            
            st.session_state.analysis_result = cleaned_text
            st.session_state.used_model_name = target_model_name
            
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e): st.warning("💡 提示：目前 AI 忙線中，請稍後再試。")

# --- 結果顯示與 Word 生成 ---
if st.session_state.analysis_result:
    st.markdown("## 📊 審查報告")
    if st.session_state.used_model_name:
        st.caption(f"由 {st.session_state.used_model_name} 執行分析")
    st.markdown(st.session_state.analysis_result)
    
    # 產生 Word
    word_binary = create_word_report(st.session_state.analysis_result, st.session_state.metadata)
    
    st.download_button(
        label="📥 下載 Word 報告 (.docx)",
        data=word_binary,
        file_name=f"建功國小_{st.session_state.metadata.get('subject','科目')}_審題報告.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_btn"
    )

render_footer()
