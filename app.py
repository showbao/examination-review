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

/* [修改區塊] 按鈕樣式：簡約細框 + 自適應大小 (非正方形) */
    div.stButton > button {
        background-color: #FFFFFF !important;      /* 內部留白 (無填滿) */
        color: #5B7C99 !important;                 /* 文字顏色 (莫蘭迪藍灰) */
        border: 1px solid #E0E0E0 !important;      /* 極細灰框線 */
        border-radius: 12px;                       /* 圓角 */
        
        /* 核心設計：灰白陰影 (創造浮起感) */
        box-shadow: 3px 3px 8px rgba(0, 0, 0, 0.05), -2px -2px 6px #FFFFFF !important;
        
        /* [修改點] 改為自適應大小 */
        height: auto !important;    /* 高度自動，不再強制 120px */
        width: auto !important;     /* 寬度自動，包住文字即可 */
        padding: 10px 25px !important; /* 內距：讓文字周圍留有舒適空間 */
        margin-top: 10px;           /* 稍微與上方拉開距離 */
        
        font-weight: bold;
        font-size: 1.1rem;          /* 字體稍微縮回標準大小 */
        
        /* 動畫過渡 */
        transition: all 0.3s ease;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* 滑鼠懸停效果 (Hover) */
    div.stButton > button:hover {
        background-color: #FDFDFD !important;
        color: #8DA399 !important;
        border: 1px solid #8DA399 !important;
        transform: translateY(-2px);
        box-shadow: 5px 5px 12px rgba(0, 0, 0, 0.1), -3px -3px 8px #FFFFFF !important;
    }
    
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
    
    # 定義純文字列表
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
        st.markdown("## 北屯區建功國小 AI 審題系統")
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

# --- 介面佈局：上傳區 (單欄流式排版) ---
# [修改 1] 移除分欄，改為直式排列
st.subheader("1️⃣ 上傳試卷 ")
exam_file = st.file_uploader("上傳試卷", type=["pdf", "jpg", "png"], key="exam_uploader", label_visibility="collapsed")

# --- 按鈕區 (位於上傳區正下方) ---
# [修改 2] 按鈕直接緊接在上傳區下方
st.markdown('<div style="height: 15px;"></div>', unsafe_allow_html=True) 
start_btn = st.button("🚀 開始\n全方位審查", type="primary", use_container_width=True)

# --- 進階功能區 (預設隱藏) ---
# 初始化變數 (避免未開啟時報錯)
context_files = None
unit_list = []
manual_model = "Gemini 3.0 Flash"
model_mode = "智慧分流"

if ENABLE_ADVANCED_FEATURES:
    st.markdown("---")
    st.markdown("#### ⚙️ 進階設定 (系統狀態、教材、單元、模型)")
    
    st.markdown("""
    <div class="dashboard-card">
        <b>⚪ 系統狀態：</b>待命中... 請上傳試卷<br>
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
            manual_model = st.selectbox("核心", ["Gemini 3.0 Pro", "Gemini 3.0 Flash"], label_visibility="collapsed")

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

if start_btn:
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
                # [修正點 1] 強制全線使用 Flash，但保留邏輯結構方便未來切換
                if context_files:
                    target_model_name = get_best_flash_model(api_key)
                    routing_msg = "📚 偵測到參考教材，啟用快速分析模式"
                elif is_science:
                    # target_model_name = get_best_pro_model(api_key)  <-- 原本邏輯 (暫時停用)
                    target_model_name = get_best_flash_model(api_key) # <-- 強制使用 Flash
                    routing_msg = "📐 理科試卷分析 (強制啟用 Flash 模式)"
                else:
                    target_model_name = get_best_flash_model(api_key)
                    routing_msg = "📝 文科試卷分析 (啟用標準模式)"

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
            # Phase 2: 深度審查 (Updated Prompt v5.4 - Flash Optimized)
            # ----------------------------------------------------
            
            # [修正點 3] 設定生成參數：Temperature = 0 (強制理性，降低幻覺)
            generation_config = {
                "temperature": 0.0,
                "top_p": 1.0,
                "top_k": 32,
            }
            
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

**【台灣試卷三大排版閱讀協定 (Taiwan Exam Layout Protocol)】：**
請先掃描整份試卷的幾何結構，並嚴格依照下列 **3 種模式** 擇一執行閱讀：

**Mode 1: 不分欄 (Single Column)**
* **特徵**：A4或A3版面，整頁無明顯分隔線。
* **閱讀順序**：標準 Z 字型（由左至右 ➡，由上而下 ⬇）。

**Mode 2: 左右雙欄 (Left-Right Split)**
* **特徵**：B4版面，中間有一條「垂直分隔線」，文字橫書（常見於數學、自然、社會、英文）。
* **閱讀順序**：
    1.  **先讀左欄**：在左半頁範圍內，由左至右、由上而下讀取。
    2.  **再讀右欄**：移至右半頁，由左至右、由上而下讀取。
    * *注意：嚴禁跨欄閱讀（即不可直接從左欄第一行讀到右欄第一行）。*

**Mode 3: 上下分欄 (Top-Bottom Split)**
* **特徵**：B4版面，中間有一條「水平分隔線」，文字為**直書**（由上而下排列，常見於國語文）。
* **閱讀順序**：
    1.  **先讀上欄**：在上半頁範圍內，**由右至左 ⬅** 掃描直行文字。
    2.  **再讀下欄**：移至下半頁，**由右至左 ⬅** 掃描直行文字。

**2. 跨欄/跨頁拼接技術 (Cross-Page Stitching)**：
* **「題號」是你的唯一導航**：在閱讀時，請隨時追蹤題號（1, 2, 3...）。
* **斷點偵測**：當一個欄位或頁面結束時，若最後一題（例如第 5 題）只有題幹沒有選項，**請立即去「下一欄頂端」或「下一頁開頭」尋找該題的剩餘部分**。
* **嚴禁幻覺**：如果找不到接續的內容，請標記該題為「題目內容不完整」，絕對不可自行編造選項。

**【台灣國小教學情境守則 (Contextual Rules)】：**
1. **是非題/改錯題 絕對豁免**：在審查「是非題」或「改錯題」時，若題目敘述的錯誤是為了測驗學生觀念（且標準答案為「X」或「不正確」），這是**正確的命題設計**。請將其歸類為 **優良試題**，**嚴禁**列為待改善或假素養。只有當「錯誤觀念」被標示為「正確答案 (O)」時，才視為命題錯誤。
2. **在地化教學標準**：針對讀音、定義或格式，以台灣國小教學現場慣例為準。

**【排版與精準度憲法】：**
1. **嚴禁開場白**。
2. **禁止頁碼**：題目敘述中**嚴禁提及**「第x頁」。
3. **精準對應題號**：嚴禁編造題號。
4. **題號格式統一**：請務必使用「**大題-小題**」格式 (例如：**二-7**、**三-1**)，嚴禁使用「題二-第7題」這種冗贅寫法。
5. **題目錨點 (關鍵)**：在Step 1 ~ Step 3列出每一題時，**務必於題號後方，括號摘錄該題題目開頭約 5~10 個字**，方便老師對照。
6. **拒絕模糊論述**：每一項分析都必須具體列出是哪幾題。
7. **強制換行**：每一個項目都必須是獨立的 Bullet Point。

請嚴格依照以下順序輸出 Markdown 報告：

---

## 總結與建議
* **請分組**：
    * ### 🔴 最優先修正 (Critical) : (若有重大形式錯誤或答案錯誤，請務必在此標示；若無則填寫「無，試卷品質極佳」)
    * ### ⚖️ 難度與鑑別度點評 : (預估試卷難度分佈與鑑別度建議)
    * ### 👍 值得讚許之處 : (列出試卷優點，若超過 5 點請擇優列出)
    * ### 💡 後續優化建議 : (錦上添花的建議)

## Step 1: 命題範圍與形式檢查
**1. 形式審查 (Logic Check - Mutually Exclusive)**：
* **執行策略**：由於排版複雜，請勿逐題點數。請改為讀取各大題的「文字說明」來進行驗證。
* **檢查步驟**：
    1.  **排版識別**：簡單描述是直書/橫書、單欄/雙欄/上下欄。
    2.  **大題配分抓取**：請找出試卷中各大題的標題（例如：「一、選擇題」、「二、填充題」），讀取其後方的配分說明（例如：「每題2分，共20分」）。
    3.  **總分估算**：將你抓取到的「各大題總分說明」相加，確認是否為 100 分。
    4.  **跳號抽查**：請只檢查「危險區域」的連號狀況（例如：左欄最後一題 vs 右欄第一題；或是第一頁最後一題 vs 第二頁第一題），確認是否有明顯斷層。
    
* **輸出指令**：請依據檢查結果，**從下列三種情況中「擇一」輸出**，嚴禁同時輸出多個標題：
    * **情況 A (總分=100 且 題號無誤)**：
        ### 🟢 形式合規
        * 分數加總正確 (100分)。
        * 題號銜接正常 (無明顯跳號或跨欄中斷)。
    * **情況 B (總分!=100 或 題號跳號)**：
        ### 🔴 形式錯誤
        * (請具體列出哪一個大題配分算錯，或哪裡跳號)。
    * **情況 C (排版混亂無法辨識)**：
        ### 🟡 無法判定
        * (請說明原因)。

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

* **情況 A (已上傳課本 且 有提供單元名稱)：** 製作標準雙向細目表。
    * 建立二維表格：直欄為單元名稱，橫列為認知向度。
    * **統計：** 計算百分比重，確認總計 100%。

* **情況 B (未上傳課本 或 無提供單元名稱)：** 製作向度分析表。
    * **表格排版嚴格規定**：
    * 第一欄標題為「認知歷程向度」，且內容**只能**填寫「知識、理解、應用、分析、綜合、評鑑」這六個詞，**嚴禁**填寫題號或題型。
    * 第二欄標題為「對應題號」，請在此欄填寫題號與題型（如：是非 1, 3, 5）。
    * 第三欄標題為「佔比」。
    * **統計：** 務必計算百分比重，總和需為 100%。

## Step 6: 難易度與負擔分析
* **表格排版嚴格規定**：
* 製作一個表格，欄位依序為：難易度(易/中/難) | 佔比 | 對應題號/說明。
* **嚴禁**在第一欄填寫長篇大論，第一欄只能填「易、中、難」。

---
"""
            if context_files: prompt_parts.append("【參考教材】：")
            prompt_parts.append(base_prompt)
            prompt_parts.append("【待審查試卷】：")
            prompt_parts.append(exam_ref)
            
            progress_bar.progress(60)
            
            # [修正點 3] 帶入 generation_config 以鎖定 Temperature
            response = main_model.generate_content(
                prompt_parts,
                generation_config=generation_config
            )
            
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
    # 網頁版：將總結與建議區塊獨立渲染 (UI Separation)
    # 嘗試切割 "## Step 1" 來分離總結與正文
    if "## Step 1" in st.session_state.analysis_result:
        summary_part, body_part = st.session_state.analysis_result.split("## Step 1", 1)
        body_part = "## Step 1" + body_part # 補回 Step 1 標題
        
        # 1. 渲染上方總結區 (使用 st.info 藍色區塊)
        st.info(summary_part.replace("## 總結與建議", "### 📊 總結與建議")) 
        
        # 2. 渲染下方正文區
        st.markdown(body_part)
    else:
        # 如果格式不如預期，則回退到標準渲染
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
