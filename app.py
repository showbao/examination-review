import streamlit as st
import google.generativeai as genai
import json
import re
import time
import pandas as pd
from datetime import timedelta, datetime

from utils import (
    get_best_flash_model, get_best_pro_model, upload_to_gemini,
    normalize_analysis_tables, clean_ai_hallucinations,
    safe_parse_json, call_with_retry, log_usage,
    get_curriculum_standards, build_curriculum_prompt_text,
    get_all_curriculum, save_curriculum_filtered,
    get_all_logs, get_announcement, save_announcement,
    METADATA_MODEL, PDF_FLASH_MODELS, PDF_PRO_MODELS, is_input_modality_error,
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
CN_NUMBERS = ["一","二","三","四","五","六","七","八","九","十"]

GRADES = ["一年級","二年級","三年級","四年級","五年級","六年級"]
SUBJECTS = ["國語","數學","英語","社會","自然"]
SEMESTERS = ["第一學期","第二學期"]
EXAM_TYPES = ["第一次月考","第二次月考"]

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
def _group_key(label): return label.split("（")[0]

TYPE_STANDARDS = {
    "判斷類": (
        "【判斷類（是非題）】\n"
        "- 豁免規則：若錯誤敘述對應標準答案為「✕」，視為優良試題，嚴禁列為待改善。\n"
        "  僅當錯誤觀念被標示為正確答案「○」時，才視為命題錯誤。\n"
        "- 審查重點：題幹敘述是否明確（避免「通常」「大部分」等模糊用語）、一題只測一個概念、有無爭議性判斷。\n"
        "- 常見問題：雙重否定致語意混淆、題幹過長致理解困難。\n"
    ),
    "選擇類": (
        "【選擇類（選擇題、配合題、連連看）】\n"
        "- 審查重點：選項干擾品質（誘答是否合理）、選項長度是否一致、有無明顯送分選項、「以上皆是/皆非」是否濫用。\n"
        "- 配合題/連連看：配對數量是否對等、有無多對一造成消去法送分。\n"
        "- 常見問題：正確選項明顯較長或較精確、選項間互相提示。\n"
    ),
    "填寫類": (
        "【填寫類（填充、造詞、造句、照樣造句）】\n"
        "- 審查重點：填空位置是否明確、預期答案是否唯一或有合理範圍、題幹是否提供足夠線索。\n"
        "- 造句/照樣造句：指定用語或句型是否清楚、評分標準是否可操作。\n"
        "- 常見問題：答案過於開放（多個合理答案但只設一個）、缺乏上下文線索。\n"
    ),
    "語文基礎類": (
        "【語文基礎類（國字注音、部首筆畫、標點符號、改錯）— 全年級適用】\n"
        "- 豁免規則：語文基礎類屬課綱規定的基本語文能力檢核，是正常且必要的題型，\n"
        "  不可判定為「缺乏素養導向」或「低階記憶題」。此豁免適用所有年級，非僅低年級。\n"
        "- 改錯題：若錯誤敘述對應標準答案為錯誤，視為優良試題。僅檢查錯誤設計是否可能誤導學習。\n"
        "- 審查重點：注音是否符合教育部標準、國字是否在該年級教學範圍、一字多音是否標示語境、破音字處理。\n"
        "- 常見問題：罕見字超出年級範圍、破音字未標明語境。\n"
    ),
    "計算應用類": (
        "【計算應用類（計算題、應用題、看圖列式）】\n"
        "- 審查重點：計算條件是否完整（有無缺少已知數據）、是否可唯一求解、數字是否合理、單位是否一致。\n"
        "- 應用題：情境敘述是否清楚、多餘資訊屬素養設計可加分、是否需分步驟且有引導。\n"
        "- 常見問題：資訊不足無法求解、計算結果不合常理（如負數距離）。\n"
    ),
    "閱讀理解類": (
        "【閱讀理解類（閱讀測驗、閱讀題組）】\n"
        "- 審查重點：文本長度是否適合該年級、子題是否緊扣文本（能從文本找到依據）、有無需推論的高層次題目。\n"
        "- 題組處理：以題組為單位審查，先評估文本品質，再逐一審查子題。題號用大題-小題格式，文本不另編號。\n"
        "- 常見問題：文本過長致閱讀負擔、子題答案不需讀文本即可回答（若是則為假素養）。\n"
    ),
    "圖表操作類": (
        "【圖表操作類（看圖回答、畫圖題）】\n"
        "- 審查限制：若無法從 PDF 確認圖表細節，必須標記「⚠️ 含圖表，建議人工確認」，不可自行推測。\n"
        "- 審查重點（若可辨識）：圖表是否清晰、圖表與題目指令是否一致、有無足夠圖例或說明。\n"
        "- 常見問題：圖片解析度不足、圖表數據與題目描述矛盾。\n"
    ),
    "排序組合類": (
        "【排序組合類（排序題、句子重組、分類題）】\n"
        "- 審查重點：排序指令是否明確（遞增/遞減/時間順序）、是否有唯一正確排序、分類標準是否清楚。\n"
        "- 常見問題：有多種合理答案但未說明、分類標準模糊致爭議。\n"
    ),
    "問答類": (
        "【問答類（問答題、簡答題、短文寫作）】\n"
        "- 審查重點：問題指令是否清楚（問什麼、答什麼、字數要求）、評分標準是否可操作、是否適合紙筆測驗的時間限制。\n"
        "- 常見問題：問題過於開放致難以客觀評分、字數要求與配分不成比例。\n"
    ),
    "聽力類": (
        "【聽力類（聽力題）】\n"
        "- 審查限制：本系統不支援音檔比對，僅能就文字稿審查。\n"
        "- 審查重點：文字稿與試卷題目是否對應、題號是否一致、選項設計是否合理。\n"
        "- 常見問題：文字稿缺漏、題號對應錯誤。\n"
    ),
}

# ==========================================
# 3. Prompt 常數
# ==========================================
LITERACY_STANDARDS = """
檢核標準：將題目中的「情境敘述」移除後，依下方 4 個向度檢核：
1. 情境真實性：情境是否真實、貼近學生生活經驗。
2. 推理需求：學生是否需要推論、判斷或解釋，而非直接記憶。
3. 跨概念整合：是否整合多個概念或學習單元。
4. 情境包裝程度：情境是否只是包裝知識，而非解題必要條件。

【各科真假素養審查標準】：
1. 國語科：(真) 閱讀依存、高階思維、多元表徵；(假) 情境脫節、低階提問。
2. 數學科：(真) 功能性情境、真實解題(含雜訊)、數學建模；(假) 文字堆砌、數據完美、套路解題。
3. 英語科：(真) 真實語料、語用溝通、資訊素養；(假) 去脈絡化、死記硬背、文化真空。
4. 社會科：(真) 史料判讀、多重觀點、因果探究；(假) 瑣碎記憶、單一觀點、結論背誦。
5. 自然科：(真) 探究歷程、解釋現象、證據論述；(假) 名詞解釋、結果背誦、違背常理。
6. 生活課程：(真) 感官體驗、情境應變、實作導向；(假) 規訓教條、知識超載、文字負擔。

⚠️ 並非所有題目都需要是素養題。基礎知識題在試卷中佔一定比例是合理的。
僅針對「有使用情境但情境只是裝飾、移除後不影響解題」的題目才判定為假素養。
"""

TEACHING_RULES = """**【台灣國小教學情境守則】：**
1. **在地化教學標準**：讀音、定義或格式以台灣國小教學現場慣例為準。
2. **圖表審查限制**：若題目含圖表且無法從 PDF 確認細節，標記「⚠️ 含圖表，建議人工確認」，不可自行推測。
3. **答案卷處理**：若試卷附有答案卷或解答頁，請用答案來交叉驗證題目正確性，但不要將答案頁本身視為試題進行審查。
"""

FORMAT_RULES = """**【排版與精準度規則】：**
1. 嚴禁開場白。
2. 禁止頁碼，精準對應題號。
3. 強制換行。
4. 題號格式統一：使用「大題-小題」格式（如 二-7）；含子題用「大題-小題-(子題)」格式（如 三-1-(1)）。
5. 題目錨點：題號後括號摘錄該題開頭約 5~7 個字。
6. 拒絕模糊論述：每項分析必須列出具體題號。
7. 除指定表格外，禁止自行發明其他表格或格式。
8. 題號錨點驗證：若找不到對應題目文字，標記「⚠️ 題號存疑，請人工確認」，嚴禁強行對應。
9. 輸出前務必執行下方【自檢步驟】。

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
# 4. 動態 Prompt 建構
# ==========================================
def build_section_structure_text(sections, total_items=None):
    if not sections: return ""
    lines = ["【大題結構（系統掃描）】："]
    for s in sections:
        p = [f"第{s.get('number','')}大題（{s.get('type','')}）"]
        if s.get("range"): p.append(f"題號{s['range']}")
        if s.get("count"): p.append(f"共{s['count']}題")
        if s.get("first_item_text"): p.append(f"起始：「{s['first_item_text']}」")
        lines.append(p[0]+"，"+"，".join(p[1:]) if len(p)>1 else p[0])
    if total_items: lines.append(f"📌全卷：{total_items}題")
    lines += ["","⚠️題號對應與上表不符，請優先相信上表並標記。"]
    return "\n".join(lines)+"\n\n"

def build_teacher_sections_text(ts):
    if not ts: return ""
    lines = ["【教師確認大題結構（不可推翻）】："]; total = 0
    for s in ts:
        n,t,c = s["number"],s["type_display"],s["count"]; total+=c
        sub = f"（含子題，以子題為最小單位，題號如{n}-1-(1)）" if s.get("has_sub_items") else ""
        lines.append(f"第{n}大題（{t}）：共{c}題{sub}")
    lines += [f"📌全卷：{total}題","","⚠️以上為教師確認，不可推翻。"]
    return "\n".join(lines)+"\n\n"

def build_type_standards_text(ts):
    if ts:
        used = {s.get("type_group_key","") for s in ts} - {"","其他"}
    else:
        used = set(TYPE_STANDARDS.keys())
    if not used: used = set(TYPE_STANDARDS.keys())
    blocks = [TYPE_STANDARDS[k] for k in TYPE_STANDARDS if k in used]
    return "**【各題型審查標準】：**\n" + "\n".join(blocks) + "\n" if blocks else ""

def build_layout_protocol(cl):
    m1="Mode1不分欄：Z字型（左→右，上→下）。\n"
    m2="Mode2左右雙欄：先左欄再右欄，禁跨欄。\n"
    m3="Mode3上下分欄：先上欄(右→左)再下欄(右→左)。\n"
    cross="跨欄/頁：以題號導航，找不到標記「內容不完整」，不可編造。\n"
    h="**【版面閱讀協定】**\n"
    if cl=="不分欄": return h+"教師指定Mode1。\n"+m1+cross
    if cl=="左右雙欄": return h+"教師指定Mode2。\n"+m2+cross
    if cl=="上下兩列": return h+"教師指定Mode3。\n"+m3+cross
    return h+"請掃描版面擇一：\n"+m1+m2+m3+cross

def build_layout_info_text(pd_,cl,td,nb):
    a="自動偵測"
    if all(v==a for v in [pd_,cl,td,nb]): return ""
    lines=["【教師版面資訊（不可推翻）】："]
    if pd_!=a: lines.append(f"- 紙張：{pd_}")
    if td!=a:  lines.append(f"- 文字：{td}")
    if nb!=a:
        lines.append(f"- 題號：{nb}")
        lines.append("  → 每大題從1開始，用大題-小題格式" if nb=="各大題獨立編號" else "  → 全卷連續")
    return "\n".join(lines)+"\n\n"

def determine_model(subj, fn, api_key):
    if any(k in (subj or "")+(fn or "") for k in SCIENCE_KEYWORDS):
        return get_best_pro_model(api_key)
    return get_best_flash_model(api_key)

def render_system_notice(cur):
    mt = cur.get("match_type","none"); parts = []
    if mt == "none":
        parts += ["📚 **注意**：比對教學重點查無資料，請教務處確認。命題範圍請老師自行確認。",""]
    parts.append("⚠️ **系統限制**：僅針對試題內容分析，未檢核試卷形式（題號連貫性、配分加總），請老師自行審閱。")
    st.info("\n\n".join(parts))

def render_footer():
    st.markdown('<div class="footer-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div class="footer">Designed for 臺中市北屯區建功國小 | Powered by Gemini 3.0</div>', unsafe_allow_html=True)

# ==========================================
# 5. 登入
# ==========================================
def check_session_timeout():
    if not st.user.is_logged_in: return
    if "last_activity" not in st.session_state:
        st.session_state["last_activity"]=time.time(); return
    rem = SESSION_TIMEOUT-(time.time()-st.session_state["last_activity"])
    if rem<=0:
        for k in ["login_logged","user_email","last_activity","timeout_warning_shown"]:
            st.session_state.pop(k,None)
        st.logout()
    if rem<=WARNING_BEFORE_TIMEOUT:
        if not st.session_state.get("timeout_warning_shown"):
            st.warning(f"⚠️ {max(1,int(rem//60))}分鐘後自動登出。")
            st.session_state["timeout_warning_shown"]=True
    else: st.session_state["timeout_warning_shown"]=False

@st.fragment(run_every=timedelta(seconds=30))
def session_watchdog(): check_session_timeout()

def check_login():
    # 管理員模式不需要 Google 登入
    if st.query_params.get("admin") == "1":
        return False  # 讓主流程跳到管理頁面

    if st.user.is_logged_in:
        email = st.user.get("email","").strip().lower()
        st.session_state["user_email"] = email
        if not email.endswith(ALLOWED_EMAIL_DOMAIN):
            st.error("❌ 此帳號未被授權")
            st.info(f"僅限 {ALLOWED_EMAIL_DOMAIN}")
            if st.button("登出", key="unauth_logout"):
                st.session_state.update(login_logged=False, user_email=""); st.logout()
            st.stop()
        if "last_activity" not in st.session_state:
            st.session_state["last_activity"] = time.time()
        if not st.session_state.get("login_logged"):
            log_usage(email, "login"); st.session_state["login_logged"] = True
        return True

    # 未登入：顯示登入頁
    c1,c2,c3 = st.columns([1,2,1])
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
    b1,b2,b3 = st.columns([1,2,1])
    with b2:
        if st.button("我同意聲明並使用 建功國小信箱 登入", use_container_width=True):
            st.login(); st.stop()

    # 管理員入口（不顯眼的小連結）
    st.markdown("---")
    ac1, ac2, ac3 = st.columns([1, 2, 1])
    with ac2:
        st.markdown(
            '<div style="text-align:center;margin-top:10px">'
            '<a href="?admin=1" target="_self" style="color:#aaa;font-size:0.8rem;text-decoration:none">⚙️ 管理員入口</a>'
            '</div>', unsafe_allow_html=True)

    render_footer()
    return False

# ==========================================
# 6. 管理員介面
# ==========================================

def render_admin_page():
    """管理員後台頁面"""
    st.title("⚙️ 管理員後台")

    # 密碼驗證
    if not st.session_state.get("admin_authenticated"):
        ac1, ac2, ac3 = st.columns([1, 2, 1])
        with ac2:
            st.markdown("### 請輸入管理員密碼")
            pwd = st.text_input("密碼", type="password", key="admin_pwd")
            if st.button("登入管理後台", key="admin_login_btn"):
                if pwd == st.secrets.get("ADMIN_PASSWORD", ""):
                    st.session_state["admin_authenticated"] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")
            st.markdown("")
            st.markdown('<a href="/" target="_self" style="color:#5B7C99;font-size:0.9rem">← 返回審題系統</a>',
                        unsafe_allow_html=True)
        render_footer()
        return

    # 已驗證：顯示管理頁面
    col_back, col_logout = st.columns([3, 1])
    with col_back:
        st.markdown('<a href="/" target="_self" style="color:#5B7C99;font-size:0.9rem">← 返回審題系統</a>',
                    unsafe_allow_html=True)
    with col_logout:
        if st.button("登出管理", key="admin_logout"):
            st.session_state["admin_authenticated"] = False
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["📚 教學重點管理", "📊 使用紀錄", "📢 系統公告"])

    # --- Tab 1：教學重點管理 ---
    with tab1:
        st.subheader("教學重點管理")
        st.caption("可篩選後編輯，或顯示全部資料。編輯完成後按「儲存」覆蓋至 Google Sheets。")

        fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
        with fc1:
            f_grade = st.selectbox("年級", ["全部"] + GRADES, key="f_grade")
        with fc2:
            f_subject = st.selectbox("科目", ["全部"] + SUBJECTS, key="f_subject")
        with fc3:
            f_semester = st.selectbox("學期", ["全部"] + SEMESTERS, key="f_semester")
        with fc4:
            st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
            load_btn = st.button("📥 載入資料", key="load_cur", use_container_width=True)

        if load_btn or st.session_state.get("cur_loaded"):
            st.session_state["cur_loaded"] = True

            all_data = get_all_curriculum()

            # 篩選
            filtered = all_data
            g_filter = None if f_grade == "全部" else f_grade
            s_filter = None if f_subject == "全部" else f_subject
            se_filter = None if f_semester == "全部" else f_semester

            if g_filter:
                filtered = [r for r in filtered if r["年級"] == g_filter]
            if s_filter:
                filtered = [r for r in filtered if r["科目"] == s_filter]
            if se_filter:
                filtered = [r for r in filtered if r["學期"] == se_filter]

            st.markdown(f"**共 {len(filtered)} 筆資料**（篩選條件：{f_grade} / {f_subject} / {f_semester}）")

            # 轉為 DataFrame
            if filtered:
                df = pd.DataFrame(filtered)
            else:
                df = pd.DataFrame(columns=["年級", "科目", "學期", "評量類別", "教學重點"])

            # 可編輯表格
            edited_df = st.data_editor(
                df,
                column_config={
                    "年級": st.column_config.SelectboxColumn("年級", options=GRADES, width="small"),
                    "科目": st.column_config.SelectboxColumn("科目", options=SUBJECTS, width="small"),
                    "學期": st.column_config.SelectboxColumn("學期", options=SEMESTERS, width="small"),
                    "評量類別": st.column_config.SelectboxColumn("評量類別", options=EXAM_TYPES, width="small"),
                    "教學重點": st.column_config.TextColumn("教學重點", width="large"),
                },
                num_rows="dynamic",
                use_container_width=True,
                key="cur_editor",
            )

            # 儲存按鈕
            st.markdown("")
            sc1, sc2 = st.columns([1, 3])
            with sc1:
                save_btn = st.button("💾 儲存變更", key="save_cur", type="primary")
            with sc2:
                st.caption("⚠️ 儲存後將覆蓋篩選範圍內的舊資料（自動備份至 curriculum_backup）")

            if save_btn:
                data_list = edited_df.to_dict("records")
                ok, msg = save_curriculum_filtered(data_list, g_filter, s_filter, se_filter)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    # --- Tab 2：使用紀錄 ---
    with tab2:
        st.subheader("使用紀錄查詢")
        logs = get_all_logs()

        if not logs:
            st.info("目前無使用紀錄。")
        else:
            df_logs = pd.DataFrame(logs)

            # 確保欄位名稱
            if "timestamp" not in df_logs.columns and len(df_logs.columns) >= 3:
                df_logs.columns = ["email", "action", "timestamp"]

            # 解析日期欄位
            df_logs["datetime"] = pd.to_datetime(df_logs["timestamp"], errors="coerce")
            df_logs["date"] = df_logs["datetime"].dt.date

            # 篩選列
            lc1, lc2, lc3 = st.columns(3)
            with lc1:
                actions = ["全部"] + sorted(df_logs["action"].unique().tolist())
                f_action = st.selectbox("動作類型", actions, key="f_action")
            with lc2:
                emails = ["全部"] + sorted(df_logs["email"].unique().tolist())
                f_email = st.selectbox("教師帳號", emails, key="f_email")
            with lc3:
                valid_dates = df_logs["date"].dropna()
                if len(valid_dates) > 0:
                    min_date = valid_dates.min()
                    max_date = valid_dates.max()
                else:
                    min_date = datetime.today().date()
                    max_date = datetime.today().date()
                f_date_range = st.date_input(
                    "日期範圍", value=(min_date, max_date),
                    min_value=min_date, max_value=max_date, key="f_date_range")

            # 套用篩選
            display = df_logs.copy()
            if f_action != "全部":
                display = display[display["action"] == f_action]
            if f_email != "全部":
                display = display[display["email"] == f_email]
            # 日期篩選（f_date_range 可能是 tuple 或單一日期）
            if isinstance(f_date_range, tuple) and len(f_date_range) == 2:
                d_start, d_end = f_date_range
                display = display[display["date"].notna() & (display["date"] >= d_start) & (display["date"] <= d_end)]

            # 統計（基於篩選後結果）
            st.markdown(f"**篩選結果：共 {len(display)} 筆紀錄**")

            mc1, mc2, mc3 = st.columns(3)
            total_reviews = len(display[display["action"] == "ai_review"])
            total_logins = len(display[display["action"] == "login"])
            unique_users = display["email"].nunique()
            mc1.metric("審查次數", total_reviews)
            mc2.metric("登入次數", total_logins)
            mc3.metric("不重複使用者", unique_users)

            # 使用最多者前 5 名
            if total_reviews > 0:
                st.markdown("**🏆 使用最多者前 5 名**")
                top5 = (display[display["action"] == "ai_review"]["email"]
                        .value_counts().head(5)
                        .reset_index())
                top5.columns = ["教師帳號", "審查次數"]
                top5.index = range(1, len(top5) + 1)
                top5.index.name = "排名"
                st.dataframe(top5, use_container_width=True)

            # 詳細紀錄（僅近 1 個月）
            with st.expander("📋 查看詳細紀錄（近 1 個月）"):
                one_month_ago = (datetime.today() - timedelta(days=30)).date()
                recent = display[display["date"].notna() & (display["date"] >= one_month_ago)]
                if len(recent) > 0:
                    show_cols = ["email", "action", "timestamp"]
                    st.dataframe(
                        recent[show_cols].sort_values("timestamp", ascending=False).reset_index(drop=True),
                        use_container_width=True, hide_index=True)
                else:
                    st.info("近 1 個月無紀錄。")

    # --- Tab 3：系統公告 ---
    with tab3:
        st.subheader("系統公告管理")
        st.caption("設定的公告會顯示在審題頁面頂部，清空內容即可取消公告。")

        current = get_announcement()
        new_text = st.text_area("公告內容", value=current, height=150, key="ann_text",
                                placeholder="例如：本學期教學重點已更新至第二次月考範圍")

        if st.button("💾 儲存公告", key="save_ann"):
            ok, msg = save_announcement(new_text.strip())
            if ok:
                st.success(msg)
            else:
                st.error(msg)

        if current:
            st.markdown("**目前公告預覽：**")
            st.info(f"📢 {current}")
        else:
            st.markdown("*目前無公告*")

    render_footer()


# ==========================================
# 7. 路由判斷
# ==========================================

if st.query_params.get("admin") == "1":
    render_admin_page()
    st.stop()

# ==========================================
# 8. 主流程：登入檢查
# ==========================================
if "logout" in st.query_params:
    st.session_state.update(login_logged=False, user_email=""); st.logout()

if not check_login():
    st.stop()

session_watchdog()

for key, default in [("analysis_result",None),("used_model_name",""),
                     ("metadata",{}),("curriculum_info",{}),("teacher_sections",[])]:
    if key not in st.session_state: st.session_state[key] = default

st.title("北屯區建功國小AI審題系統")
user_email = st.session_state.get("user_email","")
if user_email:
    st.markdown(f'<div style="margin-top:6px;margin-bottom:10px;font-size:.95rem;color:#666">'
                f'目前登入者：{user_email}'
                f' <a href="?logout=1" target="_self" style="margin-left:8px;color:#5B7C99;text-decoration:none">[登出]</a></div>',
                unsafe_allow_html=True)

# 系統公告
announcement = get_announcement()
if announcement:
    st.info(f"📢 {announcement}")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("請設定 Secrets: GEMINI_API_KEY"); st.stop()
api_key = st.secrets["GEMINI_API_KEY"]

# ==========================================
# 9. 兩欄 UI
# ==========================================
upload_col, setting_col = st.columns([1, 3], gap="large")

with upload_col:
    st.subheader("📤 上傳試卷")
    st.caption("上傳 1 份 PDF。英語聽力請將文字稿放在同一份 PDF 後面。不支援音檔。")
    exam_file = st.file_uploader("上傳試卷", type=["pdf"], key="exam_uploader", label_visibility="collapsed")

with setting_col:
    st.subheader("📐 試卷資訊設定")
    cc1, cc2 = st.columns([1, 3])
    with cc1: use_curriculum = st.checkbox("📋 比對教學重點", key="use_curriculum")
    with cc2: st.caption("勾選後，將比對課程計畫中的教學重點，建議數學、自然、社會可以勾選")

    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
    st.caption("以下選填，可提升 AI 判讀準確度。")

    sc1, sc2 = st.columns(2)
    with sc1:
        paper_direction = st.selectbox("紙張方向", ["自動偵測","直式（A4）","橫式（B4/A3）"], key="paper_dir")
        column_layout = st.selectbox("分欄方式", ["自動偵測","不分欄","左右雙欄","上下兩列"], key="col_layout")
    with sc2:
        text_direction = st.selectbox("文字方向", ["自動偵測","橫書","直書"], key="text_dir")
        numbering_style = st.selectbox("題號編排", ["自動偵測","各大題獨立編號","全卷連續編號"], key="numbering")

    st.markdown("**大題結構**（選填）")
    for i, sec in enumerate(st.session_state.teacher_sections):
        tc1,tc2,tc3,tc4 = st.columns([1,2,1,1])
        with tc1:
            sec["number"] = st.selectbox("第幾大題" if i==0 else " ", CN_NUMBERS,
                index=CN_NUMBERS.index(sec["number"]) if sec["number"] in CN_NUMBERS else 0, key=f"sn_{i}")
        with tc2:
            sel = st.selectbox("題型" if i==0 else " ", QUESTION_TYPE_GROUPS,
                index=QUESTION_TYPE_GROUPS.index(sec.get("type_group",QUESTION_TYPE_GROUPS[1])) if sec.get("type_group") in QUESTION_TYPE_GROUPS else 0, key=f"st_{i}")
            sec["type_group"]=sel; sec["type_group_key"]=_group_key(sel)
            if sec["type_group_key"]=="其他":
                sec["custom_type"]=st.text_input("請說明",value=sec.get("custom_type",""),key=f"sc_{i}",placeholder="如：連連看")
                sec["type_display"]=sec.get("custom_type") or "其他"
            else: sec["type_display"]=sel; sec["custom_type"]=""
        with tc3:
            sec["count"]=st.number_input("小題數" if i==0 else " ",min_value=1,max_value=100,value=sec["count"],key=f"sq_{i}")
        with tc4:
            sec["has_sub_items"]=st.checkbox("含子題" if i==0 else " ",value=sec.get("has_sub_items",False),key=f"ss_{i}")

    bc1,bc2,_ = st.columns([1,1,2])
    with bc1:
        if st.button("➕ 新增大題",key="add_sec"):
            idx=len(st.session_state.teacher_sections)
            st.session_state.teacher_sections.append({"number":CN_NUMBERS[idx] if idx<len(CN_NUMBERS) else CN_NUMBERS[-1],
                "type_group":QUESTION_TYPE_GROUPS[1],"type_group_key":"選擇類","type_display":QUESTION_TYPE_GROUPS[1],
                "custom_type":"","count":10,"has_sub_items":False}); st.rerun()
    with bc2:
        if st.session_state.teacher_sections and st.button("🗑️ 刪除最後一大題",key="del_sec"):
            st.session_state.teacher_sections.pop(); st.rerun()

# ==========================================
# 10. 開始審查
# ==========================================
st.markdown('<div style="height:15px"></div>', unsafe_allow_html=True)
start_btn = st.button("開始 AI 審查", type="primary", use_container_width=True)
st.markdown("---")

if start_btn:
    st.session_state["last_activity"] = time.time()
    if not exam_file:
        st.warning("❌ 請上傳 PDF 試卷！")
    else:
        if user_email: log_usage(user_email, "ai_review")
        status_box=st.empty(); progress_bar=st.progress(0)
        ts = st.session_state.teacher_sections
        try:
            fn=exam_file.name
            status_box.info(f"🔍 上傳試卷... ({fn})")
            progress_bar.progress(5)
            exam_ref=upload_to_gemini(exam_file)
            progress_bar.progress(20)

            status_box.info("🔍 辨識試卷結構...")
            lh=""
            if paper_direction!="自動偵測": lh+=f"紙張：{paper_direction}。"
            if column_layout!="自動偵測": lh+=f"分欄：{column_layout}。"
            if text_direction!="自動偵測": lh+=f"文字：{text_direction}。"
            if numbering_style!="自動偵測": lh+=f"題號：{numbering_style}。"
            meta_prompt=f"""{lh}
請閱讀試卷，輸出純JSON：
{{"year":"學年度","semester":"學期","grade":"年級","subject":"科目","exam_type":"評量類別","total_items":總題數,
"sections":[{{"number":"一","type":"是非題","range":"1-10","count":10,"first_item_text":"開頭5-7字"}}]}}
            sections用中文數字,找不到填空字串,sections填[],total_items填0。"""
            progress_bar.progress(25)
            metadata_model_names = [METADATA_MODEL] + [
                m for m in PDF_FLASH_MODELS + PDF_PRO_MODELS if m != METADATA_MODEL
            ]
            metadata_generated = False
            last_metadata_error = None
            metadata = None
            for metadata_model_name in metadata_model_names:
                try:
                    flash_model=genai.GenerativeModel(metadata_model_name)
                    meta_resp=flash_model.generate_content([meta_prompt,exam_ref])
                    metadata=safe_parse_json(meta_resp.text)
                    metadata_generated = True
                    break
                except Exception as e:
                    last_metadata_error = e
                    if is_input_modality_error(e):
                        status_box.info("🔁 目前模型無法讀取 PDF，改用備援模型重新辨識...")
                        continue
                    raise
            if not metadata_generated and last_metadata_error:
                raise last_metadata_error
            if metadata is None:
                metadata={"year":"","semester":"","grade":"","subject":"","exam_type":"","sections":[],"total_items":0}
                st.warning("⚠️ 試卷資訊擷取失敗。")
            metadata.setdefault("sections",[]); metadata.setdefault("total_items",0)
            st.session_state.metadata=metadata
            progress_bar.progress(35)

            target_model=determine_model(metadata.get("subject",""),fn,api_key)
            status_box.info(f"🤖 模型：{target_model.split('/')[-1]}")

            if use_curriculum:
                status_box.info("📚 比對教學重點...")
                cur_info=get_curriculum_standards(metadata.get("grade",""),metadata.get("subject",""),
                    metadata.get("semester",""),metadata.get("exam_type",""))
            else: cur_info={"standards":"","match_type":"skipped","label":""}
            st.session_state.curriculum_info=cur_info
            mt=cur_info.get("match_type","none"); lb=cur_info.get("label","")
            if mt=="exact": metadata["curriculum_display"]=f"比對範圍：{lb}（精確）"
            elif mt=="semester": metadata["curriculum_display"]=f"比對範圍：{lb}（整學期）"
            elif mt=="skipped": metadata["curriculum_display"]=""
            else: metadata["curriculum_display"]="⚠️ 比對教學重點查無資料"
            progress_bar.progress(45); status_box.info("🔄 AI 審查中（約1~3分鐘）...")

            gen_cfg={"temperature":0.0,"top_p":1.0,"top_k":32}
            main_model=genai.GenerativeModel(target_model)

            # 動態 Prompt 組件
            li=build_layout_info_text(paper_direction,column_layout,text_direction,numbering_style)
            lp=build_layout_protocol(column_layout)
            st_=build_teacher_sections_text(ts) if ts else build_section_structure_text(metadata.get("sections",[]),metadata.get("total_items"))
            ct=build_curriculum_prompt_text(cur_info)
            tst=build_type_standards_text(ts)
            hc=bool(cur_info.get("standards"))
            cc=("4. 命題範圍符合性：對照上方教學重點清單，若超出範圍標記「⚠️ 疑似超出命題範圍」。" if hc else "")
            ctn=("6. 認知向度的分類請同時參照上方教學重點清單。" if hc else "")
            cdn=("5. 難易度請以上方教學重點清單為基準。" if hc else "")
            exempt_keys={s.get("type_group_key","") for s in ts if s.get("type_group_key") in ("判斷類","語文基礎類")} if ts else set()
            exempt_note=f"\n⚠️ 以下題型不納入素養導向審查，直接略過：{'、'.join(exempt_keys)}。其審查依據請參照上方【各題型審查標準】。\n" if exempt_keys else ""

            # 組裝順序：版面→大題結構→題型標準→教學守則→教學重點→排版規則→自檢→輸出格式
            base_prompt=f"""你是一位精通「台灣 108 課綱素養導向評量」的試題審查專家。
目前正在審查：{metadata.get('year','')}學年度 {metadata.get('subject','')} 試卷。

{li}{lp}

{st_}{tst}
{TEACHING_RULES}
{ct}{FORMAT_RULES}
{SELF_CHECK}

請嚴格依照以下順序輸出 Markdown 報告：

## 總結與建議
### 🔴 最優先修正 (Critical)
若存在重大錯誤（如答案錯誤、題意錯誤、無法作答題目），請列出並說明；若無，請寫「無重大錯誤」。

### ⚖️ 難度與鑑別度點評
請依據試題認知層次分布、易中難比例、是否有足夠鑑別度（非全是易題或全是難題）來評估。
理想比例參考：易 30%、中 50%、難 20%，可依科目彈性調整。

### 👍 值得讚許之處
列出試卷優點（最多 5 點），**每一點必須引用具體題號**說明。

### 💡 後續優化建議
針對本試卷實際狀況提出建議，**禁止使用通用建議**，每條必須引用具體題號或具體現象。

## 題幹與邏輯品質
評估每一題時，請從以下面向進行內部檢查：
1. 題幹完整性（題幹資訊是否完整、是否缺乏必要條件、是否存在無法作答情形）
2. 選項與干擾品質（選項是否具有合理干擾性、是否存在明顯錯誤選項或選項長度差異過大）
3. 是否存在提示線索（題幹或選項是否提供過度提示）
{cc}

輸出時在每一題的說明中自然說明優點或問題，不必逐項列出。

### 🟢 優良試題
列出具有代表性的優良題目（3～5 題）。
(**強制清單**：每一題務必換行，使用列點符號 (*) 開頭，每一點包含「題號 + 題目錨點 + 具體說明原因」。)

### ✏️ 待確認試題及修改建議
針對所有有問題的題目，每一題依序輸出以下結構：

* 四-2（題目開頭）
  - 【問題點】：題幹未說明計算條件，導致學生無從判斷。
  - 【修改方向】：補充前提條件，使題幹資訊完整。
  - 【修改範例】：（直接寫出可替換使用的完整題幹或選項文字）

**硬性規定**：
1. 【修改範例】必須是**完整可直接使用**的題目文字，嚴禁只寫模糊方向。
2. 若本次試卷無待確認試題，請寫：「本次試卷無待確認試題。」
3. 每一題務必換行，使用列點符號 (*) 開頭。

## 素養導向深度審查
{LITERACY_STANDARDS}{exempt_note}
### 🟢 真素養
列出代表性題目（3～5 題），並簡述其情境與能力要求。
(**強制清單**：(*) 開頭，含「題號 + 題目錨點 + 具體說明原因」。)

### 🟡 假素養/待確認
**完整列出所有問題題目**，說明原因。
(**強制清單**：(*) 開頭，含「題號 + 題目錨點 + 具體說明原因」。)

## 公平性與敏感度審查
請逐題檢查以下兩個面向：
1. 文化公平：是否涉及文化偏見或刻板印象。
2. 情境熟悉度：題目情境是否可能造成背景知識差異。

逐題檢查後，若全卷確實無敏感議題，以一句話說明即可。
若有爭議則完整列出相關題目（(*) 開頭，含題號 + 錨點 + 原因）。

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
1. 六列，比重用百分比，總和 100%。
2. 比重以**題數**計算。若試卷上可明確看到各題配分且差異顯著，請改以**配分**計算，並在表格下方註明計算方式。
3. 以試卷上標示的最小作答單位為一題。
4. 若有註解說明，請寫在表格下方，不可寫入表格儲存格內。
{ctn}

## 難易度與負擔分析
僅輸出最終版表格（禁止草稿）：

| 難易度 | 對應題號 | 比重 |
| --- | --- | --- |
| 易 |  |  |
| 中 |  |  |
| 難 |  |  |

硬性規定：
1. 三列，比重用百分比，總和 100%。
2. 對應題號寫具體題號，不可只寫「略」或「多題」。
3. 計算方式同上（題數或配分）。
4. 註解寫在表格下方。
{cdn}

接著輸出整體作答負擔觀察：

### 📖 閱讀負擔
簡述試卷整體閱讀量是否適中。

### 📊 圖表判讀負擔
分析是否需要解讀圖表。

### 🧮 運算負擔
分析是否需要多步驟計算。

若整體負擔適中，簡要說明即可，不需過度分析。
"""
            prompt_parts=[base_prompt,"【待審查試卷】：",exam_ref]
            progress_bar.progress(55)
            response=call_with_retry(main_model,prompt_parts,gen_cfg,2,15,lambda m:status_box.info(m))
            progress_bar.progress(95)
            raw=response.text.replace("<br>","\n").replace("<br/>","\n").replace("<br />","\n")
            final=clean_ai_hallucinations(raw)
            progress_bar.progress(100); status_box.success("✅ 分析完成！")
            st.session_state.analysis_result=final; st.session_state.used_model_name=target_model
        except Exception as e:
            st.error(f"發生錯誤: {e}")
            if "429" in str(e): st.warning("💡 已重試仍失敗，請稍後再試。")

# ==========================================
# 11. 結果顯示
# ==========================================
if st.session_state.analysis_result:
    nr=normalize_analysis_tables(st.session_state.analysis_result)
    render_system_notice(st.session_state.curriculum_info)
    if "## 題幹與邏輯品質" in nr:
        summary,body=nr.split("## 題幹與邏輯品質",1)
        body="## 題幹與邏輯品質"+body
        summary=re.sub(r'^\s*[\*\-]\s+(###)',r'\1',summary,flags=re.MULTILINE)
        summary=re.sub(r'\n\s*---\s*$','',summary).strip()
        st.info(summary); st.markdown("---"); st.markdown(body)
    else: st.markdown("## 📊 審查報告"); st.markdown(nr)
    word_bin=create_word_report(nr,st.session_state.metadata)
    st.download_button("📥 下載 Word 報告",word_bin,
        file_name=f"建功國小_{st.session_state.metadata.get('subject','科目')}_審題報告.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",key="dl_btn")

render_footer()
