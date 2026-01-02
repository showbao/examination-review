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
# 0. 視覺風格設定 (莫蘭迪色系 & CSS)
# ==========================================
st.set_page_config(page_title="北屯區建功國小AI審題系統", page_icon="📝", layout="wide")

morandi_css = """
<style>
    /* 全站字體放大 */
    html, body, [class*="css"] {
        font-size: 20px; 
    }
    
    .stApp { background-color: #F5F7F7; }
    
    /* 標題層級與大小調整 */
    h1 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 2.5rem !important; }
    h2 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 2.2rem !important; font-weight: bold !important; }
    h3 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 1.3rem !important; font-weight: normal !important; }
    
    /* 針對總結區塊的特別樣式 */
    .summary-box {
        background-color: #E3F2FD;
        border-left: 5px solid #2196F3;
        padding: 20px;
        border-radius: 5px;
        margin-bottom: 20px;
    }

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
# 1. 系統全域設定 (Global Config)
# ==========================================

# --- 進階功能開關 ---
# 若要顯示「系統狀態、課本上傳、單元編輯、AI模型手動選擇」，請將此變數改為 True
ENABLE_ADVANCED_FEATURES = False 

# ==========================================
# 2. 輔助函式：模型管理與 Word 生成
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

# --- Word 生成核心邏輯 ---
def set_font_style(run, size=12, bold=False, color=None):
    """設定字體為標楷體 + Times New Roman"""
    run.font.name = 'Times New Roman'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '標楷體')
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color

def clean_markdown_symbol(text):
    text = text.replace("**", "").replace("__", "")
    text = text.replace("<br>", "").replace("<br/>", "").replace("<br />", "")
    text = re.sub(r'#+\s*', '', text) 
    for icon in ["🟢", "🔴", "🟡", "⚠️", "👍", "💡", "📊", "⚖️"]:
        text = text.replace(icon, "")
    text = text.lstrip("*- ")
    return text.strip()

def create_word_report(analysis_text, metadata):
    doc = Document()
    
    # 設定邊界 (1.27 cm)
    for section in doc.sections:
        section.top_margin = Cm(1.27)
        section.bottom_margin = Cm(1.27)
        section.left_margin = Cm(1.27)
        section.right_margin = Cm(1.27)

    # 預設樣式
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

    # --- 命題老師修改及說明 ---
    p = doc.add_paragraph()
    run = p.add_run("命題教師修改及說明")
    set_font_style(run, size=14, bold=True, color=RGBColor(91, 124, 153))
    
    feedback_table = doc.add_table(rows=1, cols=1)
    feedback_table.style = 'Table Grid'
    cell = feedback_table.cell(0, 0)
    
    # 定義純文字列表 (修正重複問題)
    checkbox_items = [
        "無需修改試題。",
        "經命題老師確認，以下試題為AI幻覺，已判斷無需修正。\n   試題：_______________________________________________________",
        "經命題老師確認，以下試題已修正。\n   試題：_______________________________________________________"
    ]
    
    for item_text in checkbox_items:
        p_check = cell.add_paragraph()
        p_check.paragraph_format.line_spacing = 1.5
        
        # 獨立渲染大方框
        run_box = p_check.add_run("□ ")
        set_font_style(run_box, size=18) 
        
        # 渲染後方文字
        run_text = p_check.add_run(item_text)
        set_font_style(run_text, size=12)

    # 新增「其他說明」與留白
    p_other = cell.add_paragraph("其他說明：")
    set_font_style(p_other.runs[0] if p_other.runs else p_other.add_run("其他說明："), size=12)
    p_other.paragraph_format.line_spacing = 1.5
    
    # 預留 5 行空行供手寫
    for _ in range(5):
        p_empty = cell.add_paragraph()
        p_empty.paragraph_format.line_spacing = 1.5

    doc.add_paragraph() # 空行分隔

    # --- 內容解析 ---
    lines = analysis_text.split('\n')
    table_mode = False
    table_data = []

    FORCE_HEADER_KEYWORDS = ["最優先修正", "難度與鑑別度", "值得讚許", "後續優化", "總結與建議"]

    for line in lines:
        line = line.strip()
        if not line: continue

        is_force_header = any(k in line for k in FORCE_HEADER_KEYWORDS)
        is_status_header = ("##" in line) and any(x in line for x in ["🟢", "🔴", "🟡", "👍", "💡", "📊", "⚖️"])
        should_be_h3 = is_status_header or is_force_header

        if line.startswith("## ") and not any(x in line for x in ["🟢", "🔴", "🟡", "👍", "💡", "📊", "⚖️"]) and not is_force_header:
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            clean_text = clean_markdown_symbol(line)
            p = doc.add_paragraph()
            run = p.add_run(clean_text)
            set_font_style(run, size=16, bold=True, color=RGBColor(91, 124, 153)) 
        
        elif should_be_h3:
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []

            is_green = "🟢" in line or "優良" in line or "真素養" in line or "形式合規" in line or "通過" in line or "值得讚許" in line
            is_red = "🔴" in line or "待改善" in line or "假素養" in line or "形式錯誤" in line or "優先修正" in line
            is_yellow = "🟡" in line or "建議" in line or "待確認" in line or "潛在爭議" in line
            
            clean_text = clean_markdown_symbol(line)
            p = doc.add_paragraph()
            run = p.add_run(clean_text)
            
            if is_force_header and not (is_green or is_red or is_yellow):
                 set_font_style(run, size=13, bold=True)
            elif is_green: set_font_style(run, size=13, bold=True, color=RGBColor(0, 100, 0))
            elif is_red: set_font_style(run, size=13, bold=True, color=RGBColor(200, 0, 0))
            elif is_yellow: set_font_style(run, size=13, bold=True, color=RGBColor(204, 153, 0))
            else: set_font_style(run, size=13, bold=True)

        elif line.startswith("|"):
            table_mode = True
            if "---" in line: continue
            row_cells = [clean_markdown_symbol(c) for c in line.split("|") if c.strip()]
            table_data.append(row_cells)
            
        elif line.startswith("*") or line.startswith("-"):
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            
            if not should_be_h3:
                clean_text = clean_markdown_symbol(line)
                if not clean_text: continue
                p = doc.add_paragraph(style='List Bullet')
                run = p.add_run(clean_text)
                set_font_style(run, size=12)
            
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
# 3. 登入與介面
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
        st.markdown("### ⚠️ 使用前請務必詳閱免責聲明")
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
# 4. 主流程與 Prompt
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

# --- [修正點 1] 介面佈局重構：將上傳區置中，移除左側系統狀態欄 (移至隱藏區) ---
st.subheader("1️⃣ 上傳試卷 (必選)")
exam_file = st.file_uploader("請拖曳檔案至此", type=["pdf", "jpg", "png"], key="exam_uploader")

# --- 進階功能區 (預設隱藏，移至最下方) ---
# 初始化變數
context_files = None
unit_list = []
manual_model = "Gemini 3.0 Flash"
model_mode = "智慧分流"

if ENABLE_ADVANCED_FEATURES:
    st.markdown("---")
    st.markdown("#### ⚙️ 進階設定 (系統狀態、教材、單元、模型)")
    
    # 將「系統狀態」移至此處
    st.markdown("""
    <div class="dashboard-card">
        <b>⚪ 系統狀態：</b>待命中... 請上傳試卷，並於檔名標註「科目領域」以啟動 AI 雙階段識別<br>
        <small>啟用檔名路由：檔名含「數/理/化/生」➔ Pro | 其餘 ➔ Flash</small>
    </div>
    """, unsafe_allow_html=True)
    
    with st.expander("📂 參考教材與單元設定", expanded=False):
        col_adv_1, col_adv_2 = st.columns(2)
        with col_adv_1:
            st.markdown("**上傳課本、習作 (可選)**")
            context_files = st.file_uploader("拖曳參考教材", type=["pdf"], accept_multiple_files=True, key="context_uploader")
        with col_adv_2:
            st.markdown("**雙向細目表單元設定**")
            if context_files:
                unit_count = st.number_input("單元數量", min_value=1, max_value=10, value=3)
                cols = st.columns(unit_count)
                for i in range(unit_count):
                    with cols[i]:
                        u_name = st.text_input(f"單元 {i+1}", key=f"unit_{i}")
                        if u_name: unit_list.append(u_name)
            else:
                st.info("💡 請先上傳教材以啟用單元編輯")

    with st.expander("🧠 AI 模型核心設定", expanded=False):
        model_mode = st.radio("模式", ["智慧分流 (建議)", "手動指定"], label_visibility="collapsed")
        if model_mode == "手動指定":
            manual_model = st.selectbox("核心", ["Gemini 3.0 Pro", "Gemini 3.0 Flash"])

# --- 審查標準 (隱藏) ---
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
            # Phase 1: 智慧分流路由 (Smart Routing)
            # ----------------------------------------------------
            filename = exam_file.name
            status_box.info(f"🔍 正在解析試卷資訊... (檔名：{filename})")
            progress_bar.progress(10)

            # 1. 判斷科目屬性
            is_science = False
            if any(k in filename for k in ["數學", "自然", "理化", "物理", "化學", "生物"]):
                is_science = True
            
            # 2. 決定模型 (核心路由邏輯)
            target_model_name = ""
            routing_msg = ""

            if model_mode == "手動指定" and ENABLE_ADVANCED_FEATURES:
                if "Pro" in manual_model: 
                    target_model_name = get_best_pro_model(api_key)
                else: 
                    target_model_name = get_best_flash_model(api_key)
            else:
                if context_files:
                    target_model_name = get_best_flash_model(api_key)
                    routing_msg = "📚 偵測到參考教材，啟用快速分析模式"
                elif is_science:
                    target_model_name = get_best_pro_model(api_key)
                    routing_msg = "📐 純試卷理科分析，啟用深度推理模式"
                else:
                    target_model_name = get_best_flash_model(api_key)
                    routing_msg = "📝 純試卷文科分析，啟用標準模式"

            status_box.info(f"🔄 Phase 2: {routing_msg}...")

            # 3. 資訊提取 (Metadata)
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
            # Phase 2: 深度審查 (Updated Prompt v5.3 - Conditional Rendering)
            # ----------------------------------------------------
            main_model = genai.GenerativeModel(target_model_name)
            
            prompt_parts = []
            if context_files:
                for cf in context_files: prompt_parts.append(upload_to_gemini(cf))
            
            units_str = ", ".join(unit_list) if unit_list else "未提供"

            if context_files:
                step1_scope_instruction = """
                * **範圍比對**：請依據上傳的參考教材內容，判斷試題是否符合教學範圍。
                * **請分組**：### 🟢 符合範圍  與  ### 🔴 超出範圍 (若有)。
                """
            else:
                step1_scope_instruction = """
                * **範圍比對**：無需進行範圍比對，亦不可輸出「符合範圍」或「超出範圍」的紅綠燈標題。
                * **強制輸出**：請直接輸出警語：「⚠️ 未檢查命題範圍：未上傳教材，故未檢查命題範圍，請老師務必自行審示題目的適切性。」
                """

            base_prompt = f"""
你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。
目前正在審查：{metadata.get('year')}學年度 {metadata.get('subject')} 試卷。

**【台灣試卷三大排版閱讀協定】**：
1. **Mode 1 不分欄**：Z 字型閱讀。
2. **Mode 2 左右雙欄**：先讀左欄再讀右欄 (數學/自然/英文)。
3. **Mode 3 上下分欄**：先讀上欄再讀下欄 (國語直書)。

**【排版與精準度憲法】：**
1. 嚴禁開場白。
2. 禁止頁碼，精準對應題號。
3. 強制換行。

請嚴格依照以下順序輸出 Markdown 報告：

---

## 總結與建議
* **請分組**：
    * ### 🔴 最優先修正 (Critical) : (若有重大形式錯誤或答案錯誤，請務必在此標示；若無則填寫「無，試卷品質極佳」)
    * ### ⚖️ 難度與鑑別度點評 : (預估試卷難度分佈與鑑別度建議)
    * ### 👍 值得讚許之處 : (列出試卷優點，若超過 5 點請擇優列出)
    * ### 💡 後續優化建議 : (錦上添花的建議)

## Step 1: 命題範圍與形式檢查
**1. 形式審查 (請遵循『有錯才報，無錯隱藏』原則)**：
* **執行策略**：讀取各大題配分說明並加總。
* **輸出規則 (嚴格執行)**：
    * ### 🟢 形式合規 : **(只有當「總分等於 100 分」且「題號無跳號」時才輸出此標題)**。內容請回報「分數加總正確」及「題號銜接正常 (無明顯跳號或跨欄中斷)」。
    * ### 🔴 形式錯誤 : **(只有當「總分不等於 100 分」或「題號有跳號」時才輸出此標題)**。內容請具體指出是哪一個大題算錯，或是哪裡跳號。**若無錯誤，絕對不要輸出此標題及內容。**
    * ### 🟡 無法判定 : **(只有當「排版過於混亂」導致無法辨識時才輸出此標題)**。**若版面清晰，絕對不要輸出此標題及內容。**

**2. 範圍審查**：
{step1_scope_instruction}

## Step 2: 題幹與邏輯品質
* **請分組**：
    * ### 🟢 優良試題 (若超過5題，請擇優列出5題並註明「(其餘略)...」)
    * ### 🟡 待確認試題 (包含誘答力不足、邏輯瑕疵)
    
* **⚠️ 強制豁免守則**：
    * 是非題/改錯題/選錯題：若錯誤敘述對應標準答案為「X」或「選出錯誤選項」，視為 **🟢 優良試題**。

## Step 3: 素養導向深度審查
**依據標準執行剝皮測試：**
{LITERACY_STANDARDS}
* **請分組**：### 🟢 真素養 (擇優列出) 、 ### 🟡 假素養/待確認。

## Step 4: 公平性與敏感度審查
* **請分組**：
    * ### 🟢 通過 (無敏感議題)
    * ### 🟡 潛在爭議 (具體指出問題)

## Step 5: 雙向細目表核算
**指定單元範圍：** {units_str}
**上傳課本狀態：** {"已上傳" if context_files else "未上傳"}

* **情況 A (已上傳課本)：** 製作標準雙向細目表。
* **情況 B (未上傳課本)：** 製作向度分析表。
    * **統計：** 務必計算百分比重，總和需為 100%。

## Step 6: 難易度與負擔分析
* **表格排版嚴格規定**：
* 製作一個表格，欄位依序為：難易度(易/中/難) | 佔比 | 對應題號/說明。

---
"""
            if context_files: prompt_parts.append("【參考教材】：")
            prompt_parts.append(base_prompt)
            prompt_parts.append("【待審查試卷】：")
            prompt_parts.append(exam_ref)
            
            progress_bar.progress(60)
            response = main_model.generate_content(prompt_parts)
            
            progress_bar.progress(100)
            
            cleaned_text = response.text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            
            status_box.success(f"✅ 分析完成！")
            
            st.session_state.analysis_result = cleaned_text
            st.session_state.used_model_name = target_model_name
            
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e): st.warning("💡 提示：目前 AI 忙線中，請稍後再試。")

# --- 結果顯示與 Word 生成 ---
if st.session_state.analysis_result:
    if "## Step 1" in st.session_state.analysis_result:
        summary_part, body_part = st.session_state.analysis_result.split("## Step 1", 1)
        body_part = "## Step 1" + body_part 
        st.info(summary_part.replace("## 總結與建議", "### 📊 總結與建議")) 
        st.markdown(body_part)
    else:
        st.markdown("## 📊 審查報告")
        st.markdown(st.session_state.analysis_result)
    
    word_binary = create_word_report(st.session_state.analysis_result, st.session_state.metadata)
    
    st.download_button(
        label="📥 下載 Word 報告 (.docx)",
        data=word_binary,
        file_name=f"建功國小_{st.session_state.metadata.get('subject','科目')}_審題報告.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_btn"
    )

render_footer()
