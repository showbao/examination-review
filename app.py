import streamlit as st
import google.generativeai as genai
import json
import re
import time
from datetime import timedelta

from utils import (
    get_best_flash_model, get_best_pro_model, upload_to_gemini,
    normalize_analysis_tables, clean_ai_hallucinations,
    safe_parse_json, call_with_retry, log_usage,
    get_curriculum_standards, build_curriculum_prompt_text,
)
from word_report import create_word_report

# ==========================================
# 0. CSS
# ==========================================
st.set_page_config(page_title="北屯區建功國小AI審題系統", page_icon="📝", layout="wide")
MORANDI_CSS = """
<style>
html,body,[class*="css"]{font-size:20px}
.stApp{background-color:#F5F7F7}
.stApp,.stApp p,.stApp li,.stApp span,.stApp label,.stApp div,
[data-testid="stMarkdownContainer"],[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,[data-testid="stText"],
[data-testid="stInfo"] *,[data-testid="stWarning"] *,[data-testid="stAlert"] *{color:#4A4A4A!important}
table,th,td{color:#4A4A4A!important}
h1{color:#5B7C99!important;font-family:'Helvetica Neue',sans-serif;font-size:2.5rem!important}
h2{color:#5B7C99!important;font-family:'Helvetica Neue',sans-serif;font-size:2.2rem!important;font-weight:bold!important}
h3{color:#5B7C99!important;font-family:'Helvetica Neue',sans-serif;font-size:1.3rem!important;font-weight:normal!important}
div.stButton>button{background-color:#FFF!important;color:#5B7C99!important;border:1px solid #E0E0E0!important;
border-radius:12px;box-shadow:3px 3px 8px rgba(0,0,0,.05),-2px -2px 6px #FFF!important;
height:auto!important;width:auto!important;padding:10px 25px!important;margin-top:10px;
font-weight:bold;font-size:1.1rem;transition:all .3s ease;display:flex;align-items:center;justify-content:center}
div.stButton>button:hover{background-color:#FDFDFD!important;color:#8DA399!important;
border:1px solid #8DA399!important;transform:translateY(-2px);
box-shadow:5px 5px 12px rgba(0,0,0,.1),-3px -3px 8px #FFF!important}
.footer{position:fixed;left:0;bottom:0;width:100%;background-color:#F5F7F7;color:#888;
text-align:center;padding:15px;font-size:14px;border-top:1px solid #ddd;z-index:999}
.footer-spacer{height:60px}
</style>
"""
st.markdown(MORANDI_CSS, unsafe_allow_html=True)

# ==========================================
# 1. 全域設定
# ==========================================
ALLOWED_EMAIL_DOMAIN = "@mail.jkes.tc.edu.tw"
SESSION_TIMEOUT = 0.5 * 60 * 60
WARNING_BEFORE_TIMEOUT = 5 * 60
SCIENCE_KEYWORDS = ["數學", "自然", "理化", "物理", "化學", "生物"]
CN_NUMBERS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

# ==========================================
# 2. 題型分組 & 審查標準
# ==========================================
QUESTION_TYPE_GROUPS = [
    "判斷類（是非題）",
    "選擇類（選擇題、配合題、連連看）",
    "填寫類（填充、造詞、造句、照樣造句）",
    "語文基礎類（國字注音、部首筆畫、標點符號、改錯）",
    "計算應用類（計算題、應用題、看圖列式）",
    "閱讀理解類（閱讀測驗、閱讀題組）",
    "圖表操作類（看圖回答、畫圖題）",
    "排序組合類（排序題、句子重組、分類題）",
    "問答類（問答題、簡答題、短文寫作）",
    "聽力類（聽力題）",
    "其他（請在右方說明）",
]

def _group_key(label: str) -> str:
    return label.split("（")[0]

# 各題型審查標準——依 group key 索引
TYPE_STANDARDS = {
    "判斷類": (
        "【判斷類（是非題）審查標準】\n"
        "- 豁免規則：若錯誤敘述對應標準答案為「✕」，視為優良試題，嚴禁列為待改善。僅當錯誤觀念被標為正確答案「○」時才視為命題錯誤。\n"
        "- 審查重點：題幹敘述是否明確（避免「通常」「大部分」等模糊用語）、一題只測一個概念、有無爭議性判斷。\n"
        "- 常見問題：雙重否定致語意混淆、題幹過長致理解困難。\n"
    ),
    "選擇類": (
        "【選擇類（選擇題、配合題、連連看）審查標準】\n"
        "- 審查重點：選項干擾品質（誘答選項是否合理）、選項長度是否一致、有無明顯送分選項、「以上皆是/皆非」是否濫用。\n"
        "- 配合題/連連看：配對數量是否對等、有無多對一造成消去法送分。\n"
        "- 常見問題：正確選項明顯較長或較精確、選項間存在互相提示。\n"
    ),
    "填寫類": (
        "【填寫類（填充、造詞、造句、照樣造句）審查標準】\n"
        "- 審查重點：填空位置是否明確、預期答案是否唯一或有合理範圍、題幹是否提供足夠線索。\n"
        "- 造句/照樣造句：指定用語或句型是否清楚、評分標準是否可操作。\n"
        "- 常見問題：答案過於開放、缺乏上下文線索。\n"
    ),
    "語文基礎類": (
        "【語文基礎類（國字注音、部首筆畫、標點符號、改錯）審查標準】\n"
        "- 豁免規則（全年級適用）：語文基礎類屬課綱基本語文能力檢核，是正常且必要的題型，不可判定為「缺乏素養導向」或「低階記憶題」。\n"
        "- 改錯題：若錯誤敘述對應標準答案為錯誤，視為優良試題。僅檢查錯誤設計是否可能誤導學習。\n"
        "- 審查重點：注音是否符合教育部標準、國字是否在該年級教學範圍、一字多音是否有標示語境、破音字處理。\n"
        "- 常見問題：罕見字超出年級範圍、破音字未標明語境。\n"
    ),
    "計算應用類": (
        "【計算應用類（計算題、應用題、看圖列式）審查標準】\n"
        "- 審查重點：計算條件是否完整（有無缺少已知數據）、是否可唯一求解、數字是否合理（避免非預期負數或非整數）、單位是否一致。\n"
        "- 應用題：情境敘述是否清楚、多餘資訊屬素養設計可加分、是否需分步驟且有合理引導。\n"
        "- 常見問題：資訊不足無法求解、計算結果不合常理。\n"
    ),
    "閱讀理解類": (
        "【閱讀理解類（閱讀測驗、閱讀題組）審查標準】\n"
        "- 審查重點：文本長度是否適合該年級、子題是否緊扣文本（能從文本找到依據）、有無需推論的高層次題目、能否不讀文本直接作答（若是則為假素養）。\n"
        "- 題組處理：以題組為單位審查，先評估文本品質再逐一審查子題。題號用大題-小題格式，文本不另編號。\n"
        "- 常見問題：文本過長致閱讀負擔、子題答案與文本無關。\n"
    ),
    "圖表操作類": (
        "【圖表操作類（看圖回答、畫圖題）審查標準】\n"
        "- 審查限制：若無法從 PDF 確認圖表細節，必須標記「⚠️ 含圖表，建議人工確認」，不可自行推測。\n"
        "- 審查重點（若可辨識）：圖表是否清晰、圖表與題目指令是否一致、有無足夠圖例或說明。\n"
        "- 常見問題：圖片解析度不足、圖表數據與題目矛盾。\n"
    ),
    "排序組合類": (
        "【排序組合類（排序題、句子重組、分類題）審查標準】\n"
        "- 審查重點：排序指令是否明確（遞增/遞減/時間順序）、是否有唯一正確排序、分類標準是否清楚。\n"
        "- 常見問題：有多種合理答案但未說明、分類標準模糊致爭議。\n"
    ),
    "問答類": (
        "【問答類（問答題、簡答題、短文寫作）審查標準】\n"
        "- 審查重點：問題指令是否清楚（問什麼、答什麼、字數要求）、評分標準是否可操作、是否適合紙筆測驗的時間限制。\n"
        "- 常見問題：問題過於開放致難以客觀評分、字數要求與配分不成比例。\n"
    ),
    "聽力類": (
        "【聽力類（聽力題）審查標準】\n"
        "- 審查限制：本系統不支援音檔比對，僅能就文字稿審查。\n"
        "- 審查重點：文字稿與試卷題目是否對應、題號是否一致、選項設計是否合理。\n"
        "- 常見問題：文字稿缺漏、題號對應錯誤。\n"
    ),
}

# ==========================================
# 3. Prompt 模組化常數
# ==========================================

LITERACY_STANDARDS = """
檢核標準：試著將題目中的「情境敘述」移除，依下方4項度及各科標準檢核。
1.情境真實性：是否真實、貼近學生生活。
2.推理需求：是否需推論/判斷/解釋，而非直接記憶。
3.跨概念整合：是否整合多個概念或學習單元。
4.情境包裝程度：情境是否只是裝飾，而非解題必要條件。

【各科真假素養標準】：
1. 國語科：(真)閱讀依存、高階思維、多元表徵；(假)情境脫節、低階提問。
2. 數學科：(真)功能性情境、真實解題(含雜訊)、數學建模；(假)文字堆砌、數據完美、套路解題。
3. 英語科：(真)真實語料、語用溝通、資訊素養；(假)去脈絡化、死記硬背、文化真空。
4. 社會科：(真)史料判讀、多重觀點、因果探究；(假)瑣碎記憶、單一觀點、結論背誦。
5. 自然科：(真)探究歷程、解釋現象、證據論述；(假)名詞解釋、結果背誦、違背常理。
6. 生活課程：(真)感官體驗、情境應變、實作導向；(假)規訓教條、知識超載、文字負擔。
"""

TEACHING_RULES = """**【台灣國小教學情境守則】：**
1. **在地化教學標準**：讀音、定義或格式以台灣國小教學現場慣例為準。
2. **圖表審查限制**：若題目含圖表且無法從 PDF 確認細節，標記「⚠️ 含圖表，建議人工確認」，不可自行推測。
"""

FORMAT_RULES = """**【排版與精準度規則】：**
1. 嚴禁開場白。
2. 禁止頁碼，精準對應題號。
3. 強制換行。
4. **題號格式統一**：「**大題-小題**」（如 二-7）；含子題用「**大題-小題-(子題)**」（如 三-1-(1)）。
5. **題目錨點**：題號後括號摘錄該題開頭約 5~7 字。
6. **拒絕模糊論述**：每項分析必須列出具體題號。
7. **除指定表格外，禁止自行發明其他表格或格式。**
8. **題號錨點驗證**：找不到對應文字請標記「⚠️ 題號存疑，請人工確認」，嚴禁強行對應。
9. **輸出前務必執行下方【自檢步驟】。**

**【題號格式範例】：**
✅ 正確：一-3、二-7、三-12、三-1-(1)、三-1-(2)
❌ 錯誤：第一大題第3小題、1-3、壹-3、二(7)、三-1(1)
"""

SELF_CHECK = """
**【輸出前自檢步驟（不可跳過）】：**
1. 逐一確認報告中引用的所有題號都能在試卷中找到對應文字。
2. 確認沒有引用超出各大題 range 的題號。
3. 確認雙向細目表和難易度表的題號總數與試卷實際題數一致。
4. 若任何題號無法確認，標記「⚠️ 題號存疑，請人工確認」。
"""


# ==========================================
# 4. 動態 Prompt 建構函式
# ==========================================

def build_section_structure_text(sections, total_items=None):
    if not sections:
        return ""
    lines = ["【本試卷大題結構（由系統預先掃描，請以此為準）】："]
    for s in sections:
        parts = [f"第{s.get('number','')}大題（{s.get('type','')}）"]
        if s.get("range"):  parts.append(f"題號 {s['range']}")
        if s.get("count"):  parts.append(f"共 {s['count']} 題")
        if s.get("first_item_text"): parts.append(f"起始：「{s['first_item_text']}」")
        lines.append(parts[0] + "，" + "，".join(parts[1:]) if len(parts) > 1 else parts[0])
    if total_items:
        lines.append(f"📌 全卷合計：{total_items} 題")
    lines += ["", "⚠️ 若題號對應與上表不符，請優先相信上表並標記「⚠️ 題號存疑，請人工確認」。"]
    return "\n".join(lines) + "\n\n"


def build_teacher_sections_text(teacher_sections):
    if not teacher_sections:
        return ""
    lines = ["【教師確認的大題結構（優先於自動偵測，不可推翻）】："]
    total = 0
    for s in teacher_sections:
        number, stype, count = s["number"], s["type_display"], s["count"]
        has_sub = s.get("has_sub_items", False)
        total += count
        sub = f"（含子題，以子題為最小單位審查，題號如 {number}-1-(1)）" if has_sub else ""
        lines.append(f"第{number}大題（{stype}）：共 {count} 題{sub}")
    lines += [f"📌 全卷合計：{total} 題", "",
              "⚠️ 以上為教師確認，審查時請嚴格以此為準，不可推翻。"]
    return "\n".join(lines) + "\n\n"


def build_type_standards_text(teacher_sections):
    """動態注入題型審查標準：有填大題結構就只注入用到的，否則注入精簡全部。"""
    if teacher_sections:
        used_keys = set(s.get("type_group_key", "") for s in teacher_sections)
        used_keys.discard("")
        used_keys.discard("其他")
    else:
        used_keys = set(TYPE_STANDARDS.keys())

    if not used_keys:
        used_keys = set(TYPE_STANDARDS.keys())

    blocks = [TYPE_STANDARDS[k] for k in TYPE_STANDARDS if k in used_keys]
    if not blocks:
        return ""
    return "**【各題型審查標準規範】：**\n\n" + "\n".join(blocks) + "\n"


def build_layout_protocol(column_layout):
    """根據教師選擇動態產生版面閱讀協定。"""
    auto = "自動偵測"
    header = "**【台灣試卷排版閱讀協定】：**\n"

    mode1 = (
        "**Mode 1: 不分欄**\n"
        "* 特徵：A4或A3版面，整頁無明顯分隔線。\n"
        "* 閱讀順序：標準 Z 字型（左→右，上→下）。\n"
    )
    mode2 = (
        "**Mode 2: 左右雙欄**\n"
        "* 特徵：B4版面，中間垂直分隔線，文字橫書。\n"
        "* 閱讀順序：先讀左欄（左→右，上→下），再讀右欄。嚴禁跨欄閱讀。\n"
    )
    mode3 = (
        "**Mode 3: 上下分欄**\n"
        "* 特徵：B4版面，中間水平分隔線，文字直書。\n"
        "* 閱讀順序：先讀上欄（右→左），再讀下欄（右→左）。\n"
    )
    cross = (
        "**跨欄/跨頁拼接**：以題號為導航追蹤連續性。找不到接續內容標記「題目內容不完整」，絕不可自行編造。\n"
    )

    if column_layout == "不分欄":
        return header + "教師指定 Mode 1，請強制使用。\n\n" + mode1 + cross
    elif column_layout == "左右雙欄":
        return header + "教師指定 Mode 2，請強制使用。\n\n" + mode2 + cross
    elif column_layout == "上下兩列":
        return header + "教師指定 Mode 3，請強制使用。\n\n" + mode3 + cross
    else:
        return header + "請先掃描試卷幾何結構，擇一執行：\n\n" + mode1 + "\n" + mode2 + "\n" + mode3 + "\n" + cross


def build_layout_info_text(paper_dir, col_layout, text_dir, numbering):
    auto = "自動偵測"
    if all(v == auto for v in [paper_dir, col_layout, text_dir, numbering]):
        return ""
    lines = ["【教師確認的版面資訊（不可推翻）】："]
    if paper_dir != auto:   lines.append(f"- 紙張方向：{paper_dir}")
    if text_dir != auto:    lines.append(f"- 文字方向：{text_dir}")
    if numbering != auto:
        lines.append(f"- 題號編排：{numbering}")
        if numbering == "各大題獨立編號":
            lines.append("  → 每大題小題從 1 開始，用「大題-小題」格式")
        else:
            lines.append("  → 全卷題號連續")
    return "\n".join(lines) + "\n\n"


def determine_model(subject_text, filename, api_key):
    source = (subject_text or "") + (filename or "")
    if any(k in source for k in SCIENCE_KEYWORDS):
        return get_best_pro_model(api_key)
    return get_best_flash_model(api_key)


def render_system_notice(curriculum):
    match_type = curriculum.get("match_type", "none")
    parts = []
    if match_type == "none":
        parts.append("📚 **注意**：已嘗試比對教學重點但查無資料，請教務處確認是否已建置。命題範圍請老師自行確認。")
        parts.append("")
    parts.append("⚠️ **系統限制**：本系統僅針對試題內容進行深度分析，未檢核試卷形式（如題號連貫性、配分加總正確性），請老師務必自行審閱。")
    st.info("\n\n".join(parts))


def render_footer():
    st.markdown('<div class="footer-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div class="footer">Designed for 臺中市北屯區建功國小 | Powered by Gemini 3.0</div>', unsafe_allow_html=True)


# ==========================================
# 5. 登入
# ==========================================

def check_session_timeout():
    if not st.user.is_logged_in:
        return
    if "last_activity" not in st.session_state:
        st.session_state["last_activity"] = time.time()
        return
    remaining = SESSION_TIMEOUT - (time.time() - st.session_state["last_activity"])
    if remaining <= 0:
        for k in ["login_logged", "user_email", "last_activity", "timeout_warning_shown"]:
            st.session_state.pop(k, None)
        st.logout()
    if remaining <= WARNING_BEFORE_TIMEOUT:
        if not st.session_state.get("timeout_warning_shown"):
            st.warning(f"⚠️ 系統將在 {max(1,int(remaining//60))} 分鐘後自動登出。")
            st.session_state["timeout_warning_shown"] = True
    else:
        st.session_state["timeout_warning_shown"] = False

@st.fragment(run_every=timedelta(seconds=30))
def session_watchdog():
    check_session_timeout()

def check_login():
    if st.user.is_logged_in:
        email = st.user.get("email", "").strip().lower()
        st.session_state["user_email"] = email
        if not email.endswith(ALLOWED_EMAIL_DOMAIN):
            st.error("❌ 此帳號未被授權使用本系統")
            st.info(f"僅限 {ALLOWED_EMAIL_DOMAIN} 網域帳號。")
            if st.button("登出並重新登入", key="unauth_logout"):
                st.session_state.update(login_logged=False, user_email="")
                st.logout()
            st.stop()
        if "last_activity" not in st.session_state:
            st.session_state["last_activity"] = time.time()
        if not st.session_state.get("login_logged"):
            log_usage(email, "login")
            st.session_state["login_logged"] = True
        return True
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 北屯區建功國小 AI 審題系統")
        st.markdown("### ⚠️ 使用前請務必詳閱免責聲明")
        st.markdown("""
**使用前請詳閱以下說明：**
1. **本系統運用 AI 技術輔助教師審閱試題，分析結果僅供教學參考。**
2. **人工查核**：AI 可能存在誤差，最終定稿請回歸教師專業判斷。
3. **資料隱私**：嚴禁上傳含學生個資、隱私或機密之文件。
4. **授權範圍**：無償提供予臺中市北屯區建功國小教師使用。
""")
    b1, b2, b3 = st.columns([1, 2, 1])
    with b2:
        if st.button("我同意聲明並使用 建功國小信箱 登入", use_container_width=True):
            st.login(); st.stop()
    render_footer()
    return False

# ==========================================
# 6. 啟動
# ==========================================
if "logout" in st.query_params:
    st.session_state.update(login_logged=False, user_email=""); st.logout()
if not check_login():
    st.stop()
session_watchdog()

for key, default in [("analysis_result", None), ("used_model_name", ""),
                     ("metadata", {}), ("curriculum_info", {}), ("teacher_sections", [])]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title("北屯區建功國小AI審題系統")
user_email = st.session_state.get("user_email", "")
if user_email:
    st.markdown(f'<div style="margin-top:6px;margin-bottom:10px;font-size:.95rem;color:#666">'
                f'目前登入者：{user_email}'
                f' <a href="?logout=1" target="_self" style="margin-left:8px;color:#5B7C99;text-decoration:none">[登出]</a></div>',
                unsafe_allow_html=True)

if "GEMINI_API_KEY" not in st.secrets:
    st.error("請設定 Secrets: GEMINI_API_KEY"); st.stop()
api_key = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 7. 兩欄 UI（1:3）
# ==========================================
upload_col, setting_col = st.columns([1, 3], gap="large")

with upload_col:
    st.subheader("📤 上傳試卷")
    st.caption("請上傳 1 份 PDF 試卷。英語聽力請將文字稿放在同一份 PDF 後面並標示題號。不支援音檔。")
    exam_file = st.file_uploader("上傳試卷", type=["pdf"], key="exam_uploader", label_visibility="collapsed")

with setting_col:
    st.subheader("📐 試卷資訊設定")

    # 比對教學重點（最上方）
    cc1, cc2 = st.columns([1, 3])
    with cc1:
        use_curriculum = st.checkbox("📋 比對教學重點", value=False, key="use_curriculum")
    with cc2:
        st.caption("勾選後，將比對課程計畫中的教學重點，建議數學、自然、社會可以勾選")

    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
    st.caption("以下為選填，可提升 AI 判讀準確度，不確定可留「自動偵測」。")

    sc1, sc2 = st.columns(2)
    with sc1:
        paper_direction = st.selectbox("紙張方向", ["自動偵測", "直式（A4）", "橫式（B4/A3）"], key="paper_dir")
        column_layout   = st.selectbox("分欄方式", ["自動偵測", "不分欄", "左右雙欄", "上下兩列"], key="col_layout")
    with sc2:
        text_direction  = st.selectbox("文字方向", ["自動偵測", "橫書", "直書"], key="text_dir")
        numbering_style = st.selectbox("題號編排", ["自動偵測", "各大題獨立編號", "全卷連續編號"], key="numbering")

    # 大題結構
    st.markdown("**大題結構**（選填，可大幅減少題號判讀錯誤）")

    for i, sec in enumerate(st.session_state.teacher_sections):
        tc1, tc2, tc3, tc4 = st.columns([1, 2, 1, 1])
        with tc1:
            sec["number"] = st.selectbox(
                "第幾大題" if i == 0 else " ", CN_NUMBERS,
                index=CN_NUMBERS.index(sec["number"]) if sec["number"] in CN_NUMBERS else 0,
                key=f"sn_{i}")
        with tc2:
            sel = st.selectbox(
                "題型" if i == 0 else " ", QUESTION_TYPE_GROUPS,
                index=QUESTION_TYPE_GROUPS.index(sec.get("type_group", QUESTION_TYPE_GROUPS[1])) if sec.get("type_group") in QUESTION_TYPE_GROUPS else 0,
                key=f"st_{i}")
            sec["type_group"] = sel
            sec["type_group_key"] = _group_key(sel)
            if sec["type_group_key"] == "其他":
                sec["custom_type"] = st.text_input("請說明題型", value=sec.get("custom_type", ""), key=f"sc_{i}",
                                                    placeholder="如：連連看、看圖回答...")
                sec["type_display"] = sec.get("custom_type") or "其他"
            else:
                sec["type_display"] = sel
                sec["custom_type"] = ""
        with tc3:
            sec["count"] = st.number_input(
                "小題數" if i == 0 else " ", min_value=1, max_value=100,
                value=sec["count"], key=f"sq_{i}")
        with tc4:
            sec["has_sub_items"] = st.checkbox(
                "含子題" if i == 0 else " ",
                value=sec.get("has_sub_items", False), key=f"ss_{i}")

    bc1, bc2, _ = st.columns([1, 1, 2])
    with bc1:
        if st.button("➕ 新增大題", key="add_sec"):
            idx = len(st.session_state.teacher_sections)
            st.session_state.teacher_sections.append({
                "number": CN_NUMBERS[idx] if idx < len(CN_NUMBERS) else CN_NUMBERS[-1],
                "type_group": QUESTION_TYPE_GROUPS[1], "type_group_key": "選擇類",
                "type_display": QUESTION_TYPE_GROUPS[1], "custom_type": "",
                "count": 10, "has_sub_items": False})
            st.rerun()
    with bc2:
        if st.session_state.teacher_sections and st.button("🗑️ 刪除最後一大題", key="del_sec"):
            st.session_state.teacher_sections.pop(); st.rerun()

# ==========================================
# 8. 開始審查
# ==========================================
st.markdown('<div style="height:15px"></div>', unsafe_allow_html=True)
start_btn = st.button("開始 AI 審查", type="primary", use_container_width=True)
st.markdown("---")

if start_btn:
    st.session_state["last_activity"] = time.time()
    if not exam_file:
        st.warning("❌ 請上傳至少一份 PDF 試卷！")
    else:
        if user_email: log_usage(user_email, "ai_review")
        status_box = st.empty(); progress_bar = st.progress(0)
        teacher_secs = st.session_state.teacher_sections
        try:
            # Phase 1
            filename = exam_file.name
            status_box.info(f"🔍 正在上傳試卷... ({filename})")
            progress_bar.progress(5)
            flash_name = get_best_flash_model(api_key)
            flash_model = genai.GenerativeModel(flash_name)
            exam_ref = upload_to_gemini(exam_file)
            progress_bar.progress(20)

            # Phase 2: metadata
            status_box.info("🔍 AI 正在辨識試卷結構...")
            lh = ""
            if paper_direction != "自動偵測": lh += f"紙張方向：{paper_direction}。"
            if column_layout != "自動偵測":   lh += f"分欄：{column_layout}。"
            if text_direction != "自動偵測":  lh += f"文字：{text_direction}。"
            if numbering_style != "自動偵測": lh += f"題號：{numbering_style}。"

            meta_prompt = f"""{lh}
請閱讀試卷，輸出**純 JSON**，不可加說明或 markdown：
{{
  "year":"學年度","semester":"學期","grade":"年級","subject":"科目",
  "exam_type":"評量類別","total_items":總題數,
  "sections":[{{"number":"一","type":"是非題","range":"1-10","count":10,"first_item_text":"開頭5-7字"}}]
}}
sections 用中文數字，找不到填空字串，sections 填 []，total_items 填 0。"""
            progress_bar.progress(25)
            meta_resp = flash_model.generate_content([meta_prompt, exam_ref])
            metadata = safe_parse_json(meta_resp.text)
            if metadata is None:
                metadata = {"year":"","semester":"","grade":"","subject":"","exam_type":"","sections":[],"total_items":0}
                st.warning("⚠️ 試卷資訊擷取失敗，審查仍會繼續。")
            metadata.setdefault("sections", []); metadata.setdefault("total_items", 0)
            st.session_state.metadata = metadata
            progress_bar.progress(35)

            # Phase 2b: model selection
            target_model = determine_model(metadata.get("subject",""), filename, api_key)
            status_box.info(f"🤖 已選模型：{target_model.split('/')[-1]}")

            # Phase 2c: curriculum
            if use_curriculum:
                status_box.info("📚 比對教學重點...")
                cur_info = get_curriculum_standards(
                    metadata.get("grade",""), metadata.get("subject",""),
                    metadata.get("semester",""), metadata.get("exam_type",""))
            else:
                cur_info = {"standards":"", "match_type":"skipped", "label":""}
            st.session_state.curriculum_info = cur_info
            mt = cur_info.get("match_type","none"); lb = cur_info.get("label","")
            if mt == "exact":    metadata["curriculum_display"] = f"比對範圍：{lb}（精確比對）"
            elif mt == "semester": metadata["curriculum_display"] = f"比對範圍：{lb}（整學期）"
            elif mt == "skipped":  metadata["curriculum_display"] = ""
            else: metadata["curriculum_display"] = "⚠️ 比對教學重點查無資料，請教務處確認"
            progress_bar.progress(45)
            status_box.info("🔄 AI 審查中（約 1~3 分鐘）...")

            # Phase 3: 組裝 prompt
            gen_cfg = {"temperature": 0.0, "top_p": 1.0, "top_k": 32}
            main_model = genai.GenerativeModel(target_model)

            layout_info = build_layout_info_text(paper_direction, column_layout, text_direction, numbering_style)
            layout_proto = build_layout_protocol(column_layout)
            sec_text = build_teacher_sections_text(teacher_secs) if teacher_secs else \
                       build_section_structure_text(metadata.get("sections",[]), metadata.get("total_items"))
            cur_text = build_curriculum_prompt_text(cur_info)
            type_std = build_type_standards_text(teacher_secs)

            has_cur = bool(cur_info.get("standards"))
            cur_check = ("4. 命題範圍符合性：對照教學重點清單，若超出範圍標記「⚠️ 疑似超出命題範圍」。" if has_cur else "")
            cur_tax = ("6. 認知向度分類請同時參照教學重點清單。" if has_cur else "")
            cur_diff = ("5. 難易度請以教學重點清單為基準。" if has_cur else "")

            # 判斷哪些題型需排除素養審查
            exempt_keys = set()
            if teacher_secs:
                for s in teacher_secs:
                    if s.get("type_group_key") in ("判斷類", "語文基礎類"):
                        exempt_keys.add(s.get("type_group_key"))
            exempt_note = ""
            if exempt_keys:
                names = "、".join(exempt_keys)
                exempt_note = f"\n⚠️ 以下題型不納入素養導向審查，直接略過：{names}。其審查依據請參照上方【各題型審查標準規範】。\n"

            base_prompt = f"""你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。
正在審查：{metadata.get('year','')}學年度 {metadata.get('subject','')} 試卷。

{layout_info}{sec_text}{cur_text}{layout_proto}

{type_std}
{TEACHING_RULES}

{FORMAT_RULES}

{SELF_CHECK}

請嚴格依照以下順序輸出 Markdown 報告：

## 總結與建議
### 🔴 最優先修正 (Critical)
若有重大錯誤（答案錯誤、題意錯誤、無法作答），列出並說明；若無，寫「無重大錯誤」。

### ⚖️ 難度與鑑別度點評
整體評估難度分布與鑑別度。

### 👍 值得讚許之處
列出試卷優點（最多 5 點），**每點必須引用具體題號**說明。

### 💡 後續優化建議
針對本試卷實際狀況提出建議，**禁止使用通用建議**，每條必須引用具體題號或具體現象。

## 題幹與邏輯品質
評估每一題，從以下面向內部檢查：
1. 題幹完整性
2. 選項與干擾品質
3. 是否存在提示線索
{cur_check}

輸出時自然說明優點或問題，不逐項列出。

### 🟢 優良試題
3～5題代表性優良題目。
(**強制清單**：每題換行，(*) 開頭，含「題號 + 錨點 + 原因」。)

### ✏️ 待確認試題及修改建議
每一題依序：
* 四-2（題目開頭）
  - 【問題點】：...
  - 【修改方向】：...
  - 【修改範例】：（完整可直接使用的文字）

硬性規定：
1. 【修改範例】必須完整可用，嚴禁模糊方向。
2. 無待確認試題請寫「本次試卷無待確認試題。」

## 素養導向深度審查
{LITERACY_STANDARDS}{exempt_note}
### 🟢 真素養
3～5題，簡述情境與能力要求。
(**強制清單**：(*) 開頭，含「題號 + 錨點 + 原因」。)

### 🟡 假素養/待確認
完整列出所有問題題目。
(**強制清單**：(*) 開頭，含「題號 + 錨點 + 原因」。)

## 公平性與敏感度審查
檢查文化公平與情境熟悉度。
若全卷無敏感議題，以一句話說明即可，不需逐題列出。
僅在有爭議時完整列出相關題目（(*) 開頭，含題號 + 錨點 + 原因）。

## 雙向細目表核算
僅輸出最終版表格（禁止草稿）：

| 認知向度 | 對應題號 | 比重 |
| --- | --- | --- |
| 記憶 |  |  |
| 理解 |  |  |
| 應用 |  |  |
| 分析 |  |  |
| 評鑑 |  |  |
| 創造 |  |  |

硬性規定：
1. 六列，比重百分比，總和 100%。
2. 比重以**題數**計算。若試卷上可明確看到各題配分且差異顯著，請改以**配分**計算，並在表格下方註明計算方式。
3. 以試卷上標示的最小作答單位為一題。
4. 註解說明請寫在表格下方，不可寫入表格儲存格內。
{cur_tax}

## 難易度與負擔分析
僅輸出最終版表格（禁止草稿）：

| 難易度 | 對應題號 | 比重 |
| --- | --- | --- |
| 易 |  |  |
| 中 |  |  |
| 難 |  |  |

硬性規定：
1. 三列，比重百分比，總和 100%。
2. 對應題號寫具體題號。
3. 計算方式同上（題數或配分）。
4. 註解寫在表格下方，不可寫入儲存格。
{cur_diff}

接著輸出：

### 📖 閱讀負擔
簡述整體閱讀量是否適中。

### 📊 圖表判讀負擔
分析是否需解讀圖表。

### 🧮 運算負擔
分析是否需多步驟計算。

若負擔適中，簡要說明即可。
"""
            prompt_parts = [base_prompt, "【待審查試卷】：", exam_ref]
            progress_bar.progress(55)
            response = call_with_retry(main_model, prompt_parts, gen_cfg, 2, 15,
                                       lambda msg: status_box.info(msg))
            progress_bar.progress(95)
            raw = response.text.replace("<br>","\n").replace("<br/>","\n").replace("<br />","\n")
            final = clean_ai_hallucinations(raw)
            progress_bar.progress(100)
            status_box.success("✅ 分析完成！")
            st.session_state.analysis_result = final
            st.session_state.used_model_name = target_model
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e): st.warning("💡 已自動重試仍失敗，請稍後再試。")

# ==========================================
# 10. 結果顯示
# ==========================================
if st.session_state.analysis_result:
    nr = normalize_analysis_tables(st.session_state.analysis_result)
    render_system_notice(st.session_state.curriculum_info)
    if "## 題幹與邏輯品質" in nr:
        summary, body = nr.split("## 題幹與邏輯品質", 1)
        body = "## 題幹與邏輯品質" + body
        summary = re.sub(r'^\s*[\*\-]\s+(###)', r'\1', summary, flags=re.MULTILINE)
        summary = re.sub(r'\n\s*---\s*$', '', summary).strip()
        st.info(summary); st.markdown("---"); st.markdown(body)
    else:
        st.markdown("## 📊 審查報告"); st.markdown(nr)

    word_bin = create_word_report(nr, st.session_state.metadata)
    st.download_button("📥 下載 Word 報告 (.docx)", word_bin,
        file_name=f"建功國小_{st.session_state.metadata.get('subject','科目')}_審題報告.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="dl_btn")

render_footer()
