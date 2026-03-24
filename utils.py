import streamlit as st
import google.generativeai as genai
import json
import re
import time
from datetime import timedelta

from utils import (
    get_best_flash_model,
    get_best_pro_model,
    upload_to_gemini,
    normalize_analysis_tables,
    clean_ai_hallucinations,
    safe_parse_json,
    call_with_retry,
    log_usage,
    get_curriculum_standards,
    build_curriculum_prompt_text,
)
from word_report import create_word_report

# ==========================================
# 0. 視覺風格設定 (莫蘭迪色系 & CSS)
# ==========================================
st.set_page_config(page_title="北屯區建功國小AI審題系統", page_icon="📝", layout="wide")

MORANDI_CSS = """
<style>
    html, body, [class*="css"] { font-size: 20px; }

    .stApp { background-color: #F5F7F7; }
    .stApp, .stApp p, .stApp li, .stApp span, .stApp label, .stApp div,
    [data-testid="stMarkdownContainer"],
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stText"],
    [data-testid="stInfo"] *,
    [data-testid="stWarning"] *,
    [data-testid="stAlert"] * { color: #4A4A4A !important; }

    table, th, td { color: #4A4A4A !important; }

    h1 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 2.5rem !important; }
    h2 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 2.2rem !important; font-weight: bold !important; }
    h3 { color: #5B7C99 !important; font-family: 'Helvetica Neue', sans-serif; font-size: 1.3rem !important; font-weight: normal !important; }

    div.stButton > button {
        background-color: #FFFFFF !important;
        color: #5B7C99 !important;
        border: 1px solid #E0E0E0 !important;
        border-radius: 12px;
        box-shadow: 3px 3px 8px rgba(0,0,0,0.05), -2px -2px 6px #FFFFFF !important;
        height: auto !important; width: auto !important;
        padding: 10px 25px !important; margin-top: 10px;
        font-weight: bold; font-size: 1.1rem;
        transition: all 0.3s ease;
        display: flex; align-items: center; justify-content: center;
    }
    div.stButton > button:hover {
        background-color: #FDFDFD !important;
        color: #8DA399 !important;
        border: 1px solid #8DA399 !important;
        transform: translateY(-2px);
        box-shadow: 5px 5px 12px rgba(0,0,0,0.1), -3px -3px 8px #FFFFFF !important;
    }

    .footer {
        position: fixed; left: 0; bottom: 0; width: 100%;
        background-color: #F5F7F7; color: #888; text-align: center;
        padding: 15px; font-size: 14px; border-top: 1px solid #ddd; z-index: 999;
    }
    .footer-spacer { height: 60px; }
</style>
"""
st.markdown(MORANDI_CSS, unsafe_allow_html=True)

# ==========================================
# 1. 系統全域設定
# ==========================================

ALLOWED_EMAIL_DOMAIN = "@mail.jkes.tc.edu.tw"
SESSION_TIMEOUT = 0.5 * 60 * 60
WARNING_BEFORE_TIMEOUT = 5 * 60

# 數理科目關鍵字（使用 Pro 模型）
SCIENCE_KEYWORDS = ["數學", "自然", "理化", "物理", "化學", "生物"]

# ==========================================
# 2. Prompt 模組化常數
# ==========================================

LITERACY_STANDARDS = """
檢核標準：試著將題目中的「情境敘述」（故事、圖片、前言）移除，並依下方4個項度及各科真假素養審查標準檢核。
1.情境真實性：判斷情境是否真實、是否貼近學生生活經驗。
2.推理需求：分析學生是否需要進行推論、判斷或解釋，而非直接記憶。
3.跨概念整合：檢查是否整合多個概念或學習單元。
4.情境包裝程度：判斷情境是否只是包裝知識，而非解題必要條件。

【各科真假素養審查標準】：
1. 國語科：(真)閱讀依存、高階思維、多元表徵；(假)情境脫節、低階提問。
2. 數學科：(真)功能性情境、真實解題(含雜訊)、數學建模；(假)文字堆砌、數據完美、套路解題。
3. 英語科：(真)真實語料、語用溝通、資訊素養；(假)去脈絡化、死記硬背、文化真空。
4. 社會科：(真)史料判讀、多重觀點、因果探究；(假)瑣碎記憶、單一觀點、結論背誦。
5. 自然科：(真)探究歷程、解釋現象、證據論述；(假)名詞解釋、結果背誦、違背常理。
6. 生活課程：(真)感官體驗、情境應變、實作導向；(假)規訓教條、知識超載、文字負擔。
"""

LAYOUT_PROTOCOL = """**【台灣試卷三大排版閱讀協定 (Taiwan Exam Layout Protocol)】：**
請先掃描整份試卷的幾何結構，並嚴格依照下列 **3 種模式** 擇一執行閱讀：

**Mode 1: 不分欄 (Single Column)**
* **特徵**：A4或A3版面，整頁無明顯分隔線。
* **閱讀順序**：標準 Z 字型（由左至右 ➡，由上而下 ⬇）。

**Mode 2: 左右雙欄 (Left-Right Split)**
* **特徵**：B4版面，中間有一條「垂直分隔線」，文字橫書（常見於數學、自然、社會、英文）。
* **閱讀順序**：
    1. **先讀左欄**：在左半頁範圍內，由左至右、由上而下讀取。
    2. **再讀右欄**：移至右半頁，由左至右、由上而下讀取。
    * *注意：嚴禁跨欄閱讀。*

**Mode 3: 上下分欄 (Top-Bottom Split)**
* **特徵**：B4版面，中間有一條「水平分隔線」，文字為**直書**（常見於國語文）。
* **閱讀順序**：
    1. **先讀上欄**：**由右至左 ⬅** 掃描直行文字。
    2. **再讀下欄**：**由右至左 ⬅** 掃描直行文字。

**跨欄/跨頁拼接技術**：
* 以「題號」為唯一導航，追蹤題號連續性。
* 若一題只有題幹沒有選項，立即去下一欄頂端或下一頁開頭尋找。
* 嚴禁幻覺：找不到接續內容，標記「題目內容不完整」，絕對不可自行編造選項。
"""

TEACHING_RULES = """**【台灣國小教學情境守則】：**
1. **是非題/改錯題 絕對豁免**：是非題或改錯題若錯誤敘述對應標準答案為「X」，視為**優良試題**，嚴禁列為待改善。只有當錯誤觀念被標示為「正確答案 (O)」時，才視為命題錯誤。
2. **在地化教學標準**：讀音、定義或格式以台灣國小教學現場慣例為準。
3. **圖表審查限制**：若題目含有圖表（折線圖、幾何圖形、統計表等），且無法從 PDF 中確認圖表數值或細節，請標記為「⚠️ 含圖表，建議人工確認」，不可自行推測圖表內容後給出判斷。
"""

FORMAT_RULES = """**【排版與精準度憲法】：**
1. 嚴禁開場白。
2. 禁止頁碼，精準對應題號。
3. 強制換行。
4. **題號格式統一**：使用「**大題-小題**」格式（例如：**二-7**、**三-1**），嚴禁冗贅寫法。
5. **題目錨點**：題號後方括號摘錄該題題目開頭約 5~7 個字。
6. **拒絕模糊論述**：每項分析必須具體列出是哪幾題。
7. **先在內部完成檢查，再輸出**：自行檢查題號前後一致、表格完整、百分比合理後再輸出。
8. **除指定表格外，禁止自行發明其他表格或格式。**
9. **題號錨點驗證**：若找不到對應題目開頭文字，請標記「⚠️ 題號存疑，請人工確認」，嚴禁強行對應。

**【題號格式範例】：**
✅ 正確：一-3、二-7、三-12
❌ 錯誤：第一大題第3小題、1-3、壹-3、二(7)
"""

SELF_CHECK_INSTRUCTIONS = """
**【輸出前自檢步驟（不可跳過）】：**
1. 列出你在報告中引用的所有題號，逐一確認每個題號都能在試卷中找到對應文字。
2. 確認沒有引用超出各大題 range 的題號（例如第一大題只有 1-10，不可出現一-11）。
3. 確認雙向細目表和難易度表的題號總數與試卷實際題數一致。
4. 若任何題號無法確認，標記「⚠️ 題號存疑，請人工確認」。
"""


# ==========================================
# 3. 輔助函式
# ==========================================

def render_footer():
    st.markdown('<div class="footer-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div class="footer">Designed for 臺中市北屯區建功國小 | Powered by Gemini 3.0</div>', unsafe_allow_html=True)


def build_section_structure_text(sections, total_items=None):
    """將大題結構清單轉為 Prompt 注入文字（強化版）"""
    if not sections:
        return ""
    lines = ["【本試卷大題結構（由系統預先掃描，請以此為準）】："]

    for s in sections:
        number     = s.get("number", "")
        stype      = s.get("type", "")
        rng        = s.get("range", "")
        count      = s.get("count", "")
        first_text = s.get("first_item_text", "")

        parts = [f"第{number}大題（{stype}）"]
        if rng:
            parts.append(f"題號 {rng}")
        if count:
            parts.append(f"共 {count} 題")
        if first_text:
            parts.append(f"起始文字：「{first_text}」")
        lines.append("：".join(parts[:1]) + "，" + "，".join(parts[1:]) if len(parts) > 1 else parts[0])

    if total_items:
        lines.append(f"📌 全卷合計：{total_items} 題")

    lines.append("")
    lines.append("⚠️ 審查時若你的題號對應與上表不符，請優先相信上表，並標記「⚠️ 題號存疑，請人工確認」。")
    return "\n".join(lines) + "\n\n"


def build_layout_prompt_text(paper_dir, col_layout, text_dir, numbering):
    """將老師填寫的版面資訊轉為 Prompt 注入文字"""
    auto = "自動偵測"
    if all(v == auto for v in [paper_dir, col_layout, text_dir, numbering]):
        return ""

    lines = ["【教師確認的試卷版面資訊（優先於自動偵測，不可推翻）】："]

    if paper_dir != auto:
        lines.append(f"- 紙張方向：{paper_dir}")
    if col_layout != auto:
        mode_map = {"不分欄": "Mode 1 (Single Column)", "左右雙欄": "Mode 2 (Left-Right Split)", "上下兩列": "Mode 3 (Top-Bottom Split)"}
        mode = mode_map.get(col_layout, "")
        lines.append(f"- 分欄方式：{col_layout} → 請強制使用 {mode} 閱讀順序")
    if text_dir != auto:
        lines.append(f"- 文字方向：{text_dir}")
    if numbering != auto:
        lines.append(f"- 題號編排：{numbering}")
        if numbering == "各大題獨立編號":
            lines.append("  → 每大題小題從 1 開始，請使用「大題-小題」格式（如 一-1、二-3）")
        else:
            lines.append("  → 全卷題號連續，第二大題接續第一大題的題號")

    lines.append("⚠️ 以上為教師確認的版面資訊，請優先依此閱讀試卷，不可自行推翻。")
    return "\n".join(lines) + "\n\n"


def render_system_notice(curriculum: dict):
    """合併顯示：教學重點比對狀態 + 系統限制聲明（單一區塊）"""
    match_type = curriculum.get("match_type", "none")
    label = curriculum.get("label", "")

    parts = []

    if match_type == "exact":
        parts.append(f"📚 **比對範圍：{label}**（精確比對成功，已帶入教學重點作為命題範圍參考。）")
    elif match_type == "semester":
        parts.append(
            f"📚 **比對範圍：{label}**（系統未能精確比對評量類別，已改用整學期範圍。"
            "建議老師確認題目範圍是否符合本次評量進度。）"
        )
    elif match_type == "skipped":
        parts.append("📚 本次審查未啟用教學重點比對，命題範圍請老師自行確認。")
    else:
        parts.append("📚 已嘗試比對教學重點，但查無對應資料，請教務處確認是否已建置。命題範圍請老師自行確認。")

    parts.append("")
    parts.append("⚠️ **系統限制**：本系統僅針對試題內容進行深度分析，未檢核試卷形式（如題號連貫性、配分加總正確性），請老師務必自行審閱。")

    st.info("\n\n".join(parts))


# ==========================================
# 4. 登入與 Session 管理
# ==========================================

def check_session_timeout():
    if not st.user.is_logged_in:
        return
    if "last_activity" not in st.session_state:
        st.session_state["last_activity"] = time.time()
        return

    now     = time.time()
    elapsed = now - st.session_state["last_activity"]
    remaining = SESSION_TIMEOUT - elapsed

    if remaining <= 0:
        st.session_state["login_logged"] = False
        st.session_state["user_email"]   = ""
        st.session_state.pop("last_activity", None)
        st.session_state.pop("timeout_warning_shown", None)
        st.logout()

    if remaining <= WARNING_BEFORE_TIMEOUT:
        if not st.session_state.get("timeout_warning_shown", False):
            minutes_left = max(1, int(remaining // 60))
            st.warning(f"⚠️ 系統將在 {minutes_left} 分鐘後因閒置自動登出。")
            st.session_state["timeout_warning_shown"] = True
    else:
        st.session_state["timeout_warning_shown"] = False


@st.fragment(run_every=timedelta(seconds=30))
def session_watchdog():
    check_session_timeout()


def check_login():
    if st.user.is_logged_in:
        user_email = st.user.get("email", "").strip().lower()
        st.session_state["user_email"] = user_email

        if not user_email.endswith(ALLOWED_EMAIL_DOMAIN):
            st.error("❌ 此帳號未被授權使用本系統")
            st.info(f"本系統僅限 {ALLOWED_EMAIL_DOMAIN} 網域帳號使用。")
            if st.button("登出並重新登入", key="unauthorized_logout"):
                st.session_state["login_logged"] = False
                st.session_state["user_email"]   = ""
                st.logout()
            st.stop()

        if "last_activity" not in st.session_state:
            st.session_state["last_activity"] = time.time()

        if not st.session_state.get("login_logged", False):
            log_usage(user_email, "login")
            st.session_state["login_logged"] = True

        return True

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
        4. **授權使用範圍**：本系統無償提供予臺中市北屯區建功國小教師使用。
        """)

    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        if st.button("我同意聲明並使用 建功國小信箱 登入", use_container_width=True):
            st.login()
            st.stop()

    render_footer()
    return False


# ==========================================
# 5. 登入檢查與 Session 啟動
# ==========================================

if "logout" in st.query_params:
    st.session_state["login_logged"] = False
    st.session_state["user_email"]   = ""
    st.logout()

if not check_login():
    st.stop()

session_watchdog()

# ==========================================
# 6. 主流程
# ==========================================

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "used_model_name" not in st.session_state:
    st.session_state.used_model_name = ""
if "metadata" not in st.session_state:
    st.session_state.metadata = {}
if "curriculum_info" not in st.session_state:
    st.session_state.curriculum_info = {}

st.title("北屯區建功國小AI審題系統")
user_email = st.session_state.get("user_email", "")

if user_email:
    st.markdown(
        f"""
<div style="margin-top:6px; margin-bottom:10px; font-size:0.95rem; color:#666666;">
目前登入者：{user_email}
<a href="?logout=1" target="_self" style="margin-left:8px; color:#5B7C99; text-decoration:none;">[登出]</a>
</div>
""",
        unsafe_allow_html=True
    )

if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("請設定 Secrets: GEMINI_API_KEY")
    st.stop()

# --- 上傳區 ---
st.subheader(" 上傳試卷 ")
st.caption("請上傳 1 份 PDF 試卷。若為英語聽力題，請將英聽文字稿整理在同一份 PDF 試卷後面，並清楚標示對應題號（例如：第一大題第1～5題）。本系統目前不支援音檔比對，請勿上傳 mp3、wav 等音訊檔。")
exam_file = st.file_uploader("📤 上傳試卷", type=["pdf"], key="exam_uploader", label_visibility="collapsed")

# --- 試卷版面設定（選填） ---
with st.expander("📐 試卷版面設定（選填，可提升 AI 判讀準確度）"):
    st.caption("若您了解試卷的版面配置，填寫後可大幅減少 AI 讀題錯誤。不確定可全部留「自動偵測」。")
    layout_col1, layout_col2 = st.columns(2)
    with layout_col1:
        paper_direction = st.selectbox(
            "紙張方向",
            ["自動偵測", "直式（A4）", "橫式（B4/A3）"],
            key="paper_direction",
        )
        column_layout = st.selectbox(
            "分欄方式",
            ["自動偵測", "不分欄", "左右雙欄", "上下兩列"],
            key="column_layout",
        )
    with layout_col2:
        text_direction = st.selectbox(
            "文字方向",
            ["自動偵測", "橫書", "直書"],
            key="text_direction",
        )
        numbering_style = st.selectbox(
            "題號編排",
            ["自動偵測", "各大題獨立編號", "全卷連續編號"],
            key="numbering_style",
        )

# 教學重點比對勾選
col_check, col_hint = st.columns([1, 3])
with col_check:
    use_curriculum = st.checkbox("📋 比對教學重點", value=False, key="use_curriculum")
with col_hint:
    st.caption("建議數學、自然、社會勾選")

st.markdown('<div style="height: 15px;"></div>', unsafe_allow_html=True)
start_btn = st.button(" 開始\n AI 審查", type="primary", use_container_width=True)

st.markdown("---")

if start_btn:
    st.session_state["last_activity"] = time.time()

    if not exam_file:
        st.warning("❌ 請務必上傳至少一份 PDF 試卷！")
    else:
        if user_email:
            log_usage(user_email, "ai_review")

        status_box   = st.empty()
        progress_bar = st.progress(0)

        try:
            # --------------------------------------------------
            # Phase 1：智慧分流路由
            # --------------------------------------------------
            filename = exam_file.name
            status_box.info(f"🔍 正在解析試卷資訊... (檔名：{filename})")
            progress_bar.progress(5)

            flash_model_name = get_best_flash_model(api_key)
            is_science = any(k in filename for k in SCIENCE_KEYWORDS)
            target_model_name = get_best_pro_model(api_key) if is_science else flash_model_name

            progress_bar.progress(10)

            # --------------------------------------------------
            # Phase 2：資訊提取（Metadata + 大題結構）
            # --------------------------------------------------
            status_box.info("📄 正在上傳試卷並提取資訊...")
            flash_model = genai.GenerativeModel(flash_model_name)
            exam_ref    = upload_to_gemini(exam_file)
            progress_bar.progress(20)

            # 組合教師提供的版面資訊（注入 meta_prompt）
            layout_hints = ""
            if paper_direction != "自動偵測":
                layout_hints += f"教師確認紙張方向為：{paper_direction}。"
            if column_layout != "自動偵測":
                layout_hints += f"教師確認分欄方式為：{column_layout}。"
            if text_direction != "自動偵測":
                layout_hints += f"教師確認文字方向為：{text_direction}。"
            if numbering_style != "自動偵測":
                layout_hints += f"教師確認題號編排為：{numbering_style}。"

            meta_prompt = f"""{layout_hints}
請閱讀這份試卷，擷取以下資訊，輸出為**純 JSON 格式**，不可加任何說明文字或 markdown：
{{
    "year": "學年度 (例如 113)",
    "semester": "學期 (例如 第一學期)",
    "grade": "年級 (例如 六年級)",
    "subject": "科目 (例如 數學)",
    "exam_type": "評量類別 (例如 期末評量)",
    "total_items": 全卷總題數 (整數),
    "sections": [
        {{"number": "一", "type": "是非題", "range": "1-10", "count": 10, "first_item_text": "該大題第一小題開頭5-7字"}},
        {{"number": "二", "type": "選擇題", "range": "1-12", "count": 12, "first_item_text": "該大題第一小題開頭5-7字"}}
    ]
}}

說明：
- sections 請依試卷實際大題順序填寫，number 使用中文數字（一、二、三...）。
- type 填寫該大題的題型（如是非題、選擇題、填充題、計算題、問答題等）。
- range 填寫該大題的小題範圍（如 1-10）。
- count 填寫該大題的小題總數（整數）。
- first_item_text 填寫該大題第一小題的題目開頭約 5~7 個字（作為定位錨點）。
- total_items 填寫全卷所有小題加總的總題數。
- 若試卷無法辨識大題結構，sections 填空陣列 []，total_items 填 0。
- 找不到的其他欄位填入空字串。
"""
            status_box.info("🔍 AI 正在辨識試卷結構...")
            progress_bar.progress(25)

            meta_response = flash_model.generate_content([meta_prompt, exam_ref])

            metadata = safe_parse_json(meta_response.text)
            if metadata is None:
                metadata = {
                    "year": "", "semester": "", "grade": "",
                    "subject": "", "exam_type": "", "sections": [],
                    "total_items": 0,
                }
                st.warning("⚠️ 試卷資訊自動擷取失敗，審查仍會繼續但部分資訊可能缺漏。")

            # 確保 sections 和 total_items 存在
            if "sections" not in metadata:
                metadata["sections"] = []
            if "total_items" not in metadata:
                metadata["total_items"] = 0

            st.session_state.metadata = metadata
            progress_bar.progress(35)

            # --------------------------------------------------
            # Phase 2b：查詢 Google Sheets 教學重點（依勾選狀態）
            # --------------------------------------------------
            if use_curriculum:
                status_box.info("📚 正在比對教學重點資料...")
                curriculum_info = get_curriculum_standards(
                    grade     = metadata.get("grade", ""),
                    subject   = metadata.get("subject", ""),
                    semester  = metadata.get("semester", ""),
                    exam_type = metadata.get("exam_type", ""),
                )
            else:
                curriculum_info = {"standards": "", "match_type": "skipped", "label": ""}

            st.session_state.curriculum_info = curriculum_info

            # 將比對結果文字寫入 metadata，供 Word 報告使用
            match_type = curriculum_info.get("match_type", "none")
            label      = curriculum_info.get("label", "")
            if match_type == "exact":
                metadata["curriculum_display"] = f"比對範圍：{label}（精確比對）"
            elif match_type == "semester":
                metadata["curriculum_display"] = f"比對範圍：{label}（整學期範圍）"
            elif match_type == "skipped":
                metadata["curriculum_display"] = "未啟用教學重點比對，命題範圍請老師自行確認"
            else:
                metadata["curriculum_display"] = "已嘗試比對但查無資料，請教務處確認是否已建置"

            progress_bar.progress(45)
            status_box.info("🔄 AI 審查中，請稍候（通常需要 1~3 分鐘）...")

            # --------------------------------------------------
            # Phase 3：深度審查
            # --------------------------------------------------
            generation_config = {
                "temperature": 0.0,
                "top_p": 1.0,
                "top_k": 32,
            }

            main_model = genai.GenerativeModel(target_model_name)

            # 動態注入：版面資訊 + 大題結構 + 教學重點
            layout_prompt_text     = build_layout_prompt_text(paper_direction, column_layout, text_direction, numbering_style)
            section_structure_text = build_section_structure_text(metadata.get("sections", []), metadata.get("total_items"))
            curriculum_prompt_text = build_curriculum_prompt_text(curriculum_info)

            # 有教學重點時的額外指令（合併判斷）
            has_curriculum = bool(curriculum_info.get("standards"))
            curriculum_check_point = ""
            curriculum_taxonomy_note = ""
            curriculum_difficulty_note = ""
            if has_curriculum:
                curriculum_check_point = (
                    "4. 命題範圍符合性：對照上方教學重點清單，"
                    "檢查該題考查的知識點是否在本次評量範圍內。"
                    "若超出範圍，於「待確認試題及修改建議」標記「⚠️ 疑似超出命題範圍」。"
                )
                curriculum_taxonomy_note = (
                    "6. 認知向度的分類請同時參照上方教學重點清單，"
                    "確認各題對應的知識點後再判斷認知層次，不可僅憑題目文字猜測。"
                )
                curriculum_difficulty_note = (
                    "5. 難易度請以上方教學重點清單為基準（詳見清單說明）。"
                )

            base_prompt = f"""你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。
目前正在審查：{metadata.get('year')}學年度 {metadata.get('subject')} 試卷。

{layout_prompt_text}{section_structure_text}{curriculum_prompt_text}{LAYOUT_PROTOCOL}

{TEACHING_RULES}

{FORMAT_RULES}

{SELF_CHECK_INSTRUCTIONS}

請嚴格依照以下順序輸出 Markdown 報告：

## 總結與建議
### 🔴 最優先修正 (Critical)
若存在重大錯誤（如答案錯誤、題意錯誤、無法作答題目），請列出並說明；若無，請寫「無重大錯誤」。

### ⚖️ 難度與鑑別度點評
整體評估試卷難度分布與鑑別度是否合理。

### 👍 值得讚許之處
列出試卷優點（最多 5 點即可）。

### 💡 後續優化建議
提出可提升試卷品質的建議。

## 題幹與邏輯品質
評估每一題時，請從以下面向進行內部檢查：
1. 題幹完整性（題幹資訊是否完整、是否缺乏必要條件、是否存在無法作答情形）
2. 選項與干擾品質（選項是否具有合理干擾性，是否存在明顯錯誤選項或選項長度差異過大）
3. 是否存在提示線索（題幹或選項是否提供過度提示）
{curriculum_check_point}

輸出時在每一題的說明中自然說明優點或問題，不必逐項列出。

### 🟢 優良試題
列出具有代表性的優良題目（3～5題）。
* 一-2（題目開頭）— 題幹清楚、選項干擾合理，能有效檢核學生概念理解。
* (其餘優良試題略)...
(**強制清單**：每一題務必換行，使用列點符號 (*) 開頭，每一點包含「題號 + 題目錨點 + 具體說明原因」。)

### ✏️ 待確認試題及修改建議
針對所有有問題的題目，每一題依序輸出以下結構，一題都不可省略：

* 四-2（題目開頭）
  - 【問題點】：題幹未說明計算條件，導致學生無從判斷。
  - 【修改方向】：補充前提條件，使題幹資訊完整，縮小解讀空間。
  - 【修改範例】：（直接寫出可替換使用的完整題幹或選項文字）

**硬性規定**：
1. 【修改範例】必須是**完整可直接使用**的題目文字，嚴禁只寫模糊方向。
2. 若本次試卷無待確認試題，請寫：「本次試卷無待確認試題。」
3. (**強制清單**：每一題務必換行，使用列點符號 (*) 開頭。)

* **⚠️ 強制豁免守則**：
    * 是非題/改錯題/選錯題：若錯誤敘述對應標準答案為「X」，視為 **🟢 優良試題**。

## 素養導向深度審查
{LITERACY_STANDARDS}
### 🟢 真素養
列出代表性題目（3～5題），並簡述其情境與能力要求。
(**強制清單**：每一題務必換行，使用列點符號 (*) 開頭，每一點包含「題號 + 題目錨點 + 具體說明原因」。)

### 🟡 假素養/待確認
**完整列出所有問題題目**，說明原因（情境只是裝飾、不需要推理、未整合概念等）。
(**強制清單**：每一題務必換行，使用列點符號 (*) 開頭，每一點包含「題號 + 題目錨點 + 具體說明原因」。)

## 公平性與敏感度審查
評估每一題時，請從以下兩個面向進行內部檢查：
1. 文化公平：是否涉及文化偏見或刻板印象（性別、種族、語文、文化、職業等）。
2. 情境熟悉度：題目情境是否可能造成背景知識差異。

### 🟢 通過 (無敏感議題)
列出代表性題目（1～3題），最後可加：
* (其餘通過試題略)...
(**強制清單**：每一題務必換行，使用列點符號 (*) 開頭，每一點包含「題號 + 題目錨點 + 具體說明原因」。)

### 🟡 潛在爭議 (具體指出問題)
若存在文化偏見、情境背景差異等問題，**完整列出所有相關題目**。
(**強制清單**：每一題務必換行，使用列點符號 (*) 開頭，每一點包含「題號 + 題目錨點 + 具體說明原因」。)

## 雙向細目表核算
請**只能**輸出以下 Markdown 表格（**僅輸出最終版，禁止輸出草稿或中間修正版本**）：

| 認知向度 | 對應題號 | 比重 |
| --- | --- | --- |
| 記憶 |  |  |
| 理解 |  |  |
| 應用 |  |  |
| 分析 |  |  |
| 評鑑 |  |  |
| 創造 |  |  |

硬性規定：
1. 六列，比重用百分比，總和 100%，不可留空整列。
2. 本段除上表外，僅可在表格下方以一行文字簡要說明比重調整方式（如有調整的話），不可輸出其他內容。
3. 若需調整比重，請在內部完成計算後僅輸出最終結果，禁止輸出草稿表格。
{curriculum_taxonomy_note}

## 難易度與負擔分析
請**只能**輸出以下 Markdown 表格（**僅輸出最終版，禁止輸出草稿或中間修正版本**）：

| 難易度 | 對應題號 | 比重 |
| --- | --- | --- |
| 易 |  |  |
| 中 |  |  |
| 難 |  |  |

硬性規定：
1. 三列，比重用百分比，總和 100%。
2. 對應題號寫具體題號，不可只寫「略」或「多題」。
3. 若需調整比重，請在內部完成計算後僅輸出最終結果，禁止輸出草稿表格。
{curriculum_difficulty_note}

接著輸出整體作答負擔觀察：

### 📖 閱讀負擔
簡述試卷整體閱讀量是否適中，是否有長題幹或大量閱讀題。

### 📊 圖表判讀負擔
分析是否需要解讀圖表、數據或圖像資訊。

### 🧮 運算負擔
分析是否需要多步驟計算或複雜推理。

若整體負擔適中，簡要說明即可，不需過度分析。

"""
            prompt_parts = [base_prompt, "【待審查試卷】：", exam_ref]
            progress_bar.progress(55)

            response = call_with_retry(
                model=main_model,
                prompt_parts=prompt_parts,
                generation_config=generation_config,
                max_retries=2,
                base_wait=15,
                status_callback=lambda msg: status_box.info(msg),
            )
            progress_bar.progress(95)

            raw_text = response.text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            final_cleaned_text = clean_ai_hallucinations(raw_text)

            progress_bar.progress(100)
            status_box.success("✅ 分析完成！")
            st.session_state.analysis_result  = final_cleaned_text
            st.session_state.used_model_name  = target_model_name

        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e):
                st.warning("💡 提示：已自動重試仍失敗，請稍後再試。")

# --- 結果顯示與 Word 生成 ---
if st.session_state.analysis_result:
    normalized_result = normalize_analysis_tables(st.session_state.analysis_result)

    # 整合通知：教學重點比對 + 系統限制（單一區塊）
    render_system_notice(st.session_state.curriculum_info)

    if "## 題幹與邏輯品質" in normalized_result:
        summary_part, body_part = normalized_result.split("## 題幹與邏輯品質", 1)
        body_part    = "## 題幹與邏輯品質" + body_part
        summary_part = re.sub(r'^\s*[\*\-]\s+(###)', r'\1', summary_part, flags=re.MULTILINE)
        summary_part = re.sub(r'\n\s*---\s*$', '', summary_part).strip()
        st.info(summary_part)
        st.markdown("---")
        st.markdown(body_part)
    else:
        st.markdown("## 📊 審查報告")
        st.markdown(normalized_result)

    word_binary = create_word_report(normalized_result, st.session_state.metadata)

    st.download_button(
        label="📥 下載 Word 報告 (.docx)",
        data=word_binary,
        file_name=f"建功國小_{st.session_state.metadata.get('subject','科目')}_審題報告.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_btn"
    )

render_footer()
