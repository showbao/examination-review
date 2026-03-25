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
    "判斷類": "【判斷類】豁免：答案為✕視為優良試題。審查：敘述是否明確、一題一概念、有無爭議判斷。注意：雙重否定、題幹過長。\n",
    "選擇類": "【選擇類】審查：選項干擾品質、長度一致性、有無送分選項、「以上皆是」濫用。配合/連連看：配對是否對等。注意：正確選項明顯較長、選項互相提示。\n",
    "填寫類": "【填寫類】審查：填空位置明確、答案唯一或合理範圍、線索充足。造句：指定用語/句型是否清楚。注意：答案過於開放、缺乏線索。\n",
    "語文基礎類": "【語文基礎類（全年級豁免）】不可判為「缺乏素養」或「低階記憶」。改錯題答案為錯誤視為優良。審查：注音正確性、國字年級範圍、一字多音語境、破音字。\n",
    "計算應用類": "【計算應用類】審查：計算條件完整、可唯一求解、數字合理、單位一致。應用題：情境清楚、多餘資訊屬素養加分。注意：資訊不足、結果不合理。\n",
    "閱讀理解類": "【閱讀理解類】審查：文本長度適合年級、子題緊扣文本、有無高層次題。題組以題組為單位審查。注意：文本過長、答案不需讀文本。\n",
    "圖表操作類": "【圖表操作類】限制：無法確認圖表細節必須標記「⚠️ 含圖表，建議人工確認」。若可辨識：圖表清晰、與題目一致、有圖例。\n",
    "排序組合類": "【排序組合類】審查：指令明確（遞增/遞減/時間）、唯一正確排序、分類標準清楚。注意：多種合理答案、標準模糊。\n",
    "問答類": "【問答類】審查：指令清楚（問什麼答什麼）、評分標準可操作、適合時間限制。注意：過於開放、字數與配分不成比例。\n",
    "聽力類": "【聽力類】限制：不支援音檔，僅審文字稿。審查：文字稿與題目對應、題號一致、選項合理。\n",
}

# ==========================================
# 3. Prompt 常數
# ==========================================
LITERACY_STANDARDS = """
檢核：移除情境敘述後，依4項度檢核。
1.情境真實性 2.推理需求 3.跨概念整合 4.情境包裝程度
各科標準：國語(真:閱讀依存/高階思維;假:情境脫節/低階提問)、數學(真:功能性情境/數學建模;假:文字堆砌/套路)、
英語(真:真實語料/語用溝通;假:去脈絡化/死記)、社會(真:史料判讀/多重觀點;假:瑣碎記憶/單一觀點)、
自然(真:探究歷程/證據論述;假:名詞解釋/結果背誦)、生活(真:感官體驗/實作;假:規訓教條/知識超載)。
"""
TEACHING_RULES = "**【教學情境守則】**\n1. 在地化標準：以台灣國小教學現場慣例為準。\n2. 圖表限制：無法確認細節標記「⚠️ 含圖表，建議人工確認」。\n"
FORMAT_RULES = """**【排版規則】**
1.嚴禁開場白 2.禁頁碼 3.強制換行
4.題號格式：大題-小題（二-7）；含子題：大題-小題-(子題)（三-1-(1)）
5.題目錨點：題號後摘錄開頭5~7字 6.每項分析列具體題號
7.禁自行發明表格 8.找不到對應文字標記「⚠️ 題號存疑」9.輸出前執行自檢步驟
✅正確：一-3、二-7、三-1-(1) ❌錯誤：第一大題第3小題、1-3、壹-3
"""
SELF_CHECK = """**【自檢步驟】**
1.確認所有題號都能在試卷找到對應文字 2.未超出各大題range
3.細目表題號總數與實際一致 4.無法確認標記「⚠️ 題號存疑」
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

            # 篩選
            lc1, lc2 = st.columns(2)
            with lc1:
                actions = ["全部"] + sorted(df_logs["action"].unique().tolist())
                f_action = st.selectbox("動作類型", actions, key="f_action")
            with lc2:
                emails = ["全部"] + sorted(df_logs["email"].unique().tolist())
                f_email = st.selectbox("教師帳號", emails, key="f_email")

            display = df_logs
            if f_action != "全部":
                display = display[display["action"] == f_action]
            if f_email != "全部":
                display = display[display["email"] == f_email]

            # 統計
            st.markdown(f"**共 {len(display)} 筆紀錄**")

            mc1, mc2, mc3 = st.columns(3)
            total_reviews = len(df_logs[df_logs["action"] == "ai_review"])
            total_logins = len(df_logs[df_logs["action"] == "login"])
            unique_users = df_logs["email"].nunique()
            mc1.metric("總審查次數", total_reviews)
            mc2.metric("總登入次數", total_logins)
            mc3.metric("不重複使用者", unique_users)

            # 每位教師審查次數
            if total_reviews > 0:
                st.markdown("**各教師審查次數**")
                review_counts = df_logs[df_logs["action"] == "ai_review"]["email"].value_counts()
                st.dataframe(review_counts.reset_index().rename(
                    columns={"index": "email", "email": "教師帳號", "count": "審查次數"}),
                    use_container_width=True, hide_index=True)

            # 詳細紀錄
            with st.expander("📋 查看詳細紀錄"):
                st.dataframe(display.sort_index(ascending=False), use_container_width=True, hide_index=True)

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
            flash_name=get_best_flash_model(api_key)
            flash_model=genai.GenerativeModel(flash_name)
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
            meta_resp=flash_model.generate_content([meta_prompt,exam_ref])
            metadata=safe_parse_json(meta_resp.text)
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
            li=build_layout_info_text(paper_direction,column_layout,text_direction,numbering_style)
            lp=build_layout_protocol(column_layout)
            st_=build_teacher_sections_text(ts) if ts else build_section_structure_text(metadata.get("sections",[]),metadata.get("total_items"))
            ct=build_curriculum_prompt_text(cur_info)
            tst=build_type_standards_text(ts)
            hc=bool(cur_info.get("standards"))
            cc=("4.命題範圍：對照教學重點，超出標記「⚠️疑似超出命題範圍」。" if hc else "")
            ctn=("6.認知向度參照教學重點清單。" if hc else "")
            cdn=("5.難易度以教學重點為基準。" if hc else "")
            exempt_keys={s.get("type_group_key","") for s in ts if s.get("type_group_key") in ("判斷類","語文基礎類")} if ts else set()
            exempt_note=f"\n⚠️不納入素養審查：{'、'.join(exempt_keys)}。\n" if exempt_keys else ""

            base_prompt=f"""你是精通「台灣108課綱素養導向評量」的試題審查專家。
審查：{metadata.get('year','')}學年度 {metadata.get('subject','')} 試卷。

{li}{st_}{ct}{lp}

{tst}
{TEACHING_RULES}
{FORMAT_RULES}
{SELF_CHECK}

請嚴格依序輸出Markdown報告：

## 總結與建議
### 🔴 最優先修正 (Critical)
有重大錯誤列出；無則寫「無重大錯誤」。
### ⚖️ 難度與鑑別度點評
### 👍 值得讚許之處
最多5點，**每點引用具體題號**。
### 💡 後續優化建議
針對本試卷，**禁止通用建議**，每條引用具體題號或現象。

## 題幹與邏輯品質
面向：1.題幹完整性 2.選項干擾品質 3.提示線索 {cc}
### 🟢 優良試題
3~5題，(*)開頭，題號+錨點+原因。
### ✏️ 待確認試題及修改建議
每題：* 題號（錨點）
  - 【問題點】：...  - 【修改方向】：...  - 【修改範例】：完整可用文字
無則寫「無待確認試題。」

## 素養導向深度審查
{LITERACY_STANDARDS}{exempt_note}
### 🟢 真素養
3~5題，(*)開頭。
### 🟡 假素養/待確認
完整列出，(*)開頭。

## 公平性與敏感度審查
全卷無敏感議題一句話即可。有爭議才完整列出。

## 雙向細目表核算
僅最終版：
| 認知向度 | 對應題號 | 比重 |
| --- | --- | --- |
| 記憶 |  |  |
| 理解 |  |  |
| 應用 |  |  |
| 分析 |  |  |
| 評鑑 |  |  |
| 創造 |  |  |
規定：六列,百分比,總和100%。以題數計算；配分差異大改用配分並註明。最小作答單位為一題。註解寫表格下方。
{ctn}

## 難易度與負擔分析
僅最終版：
| 難易度 | 對應題號 | 比重 |
| --- | --- | --- |
| 易 |  |  |
| 中 |  |  |
| 難 |  |  |
規定：三列,百分比,具體題號。計算方式同上。註解寫下方。
{cdn}

### 📖 閱讀負擔
### 📊 圖表判讀負擔
### 🧮 運算負擔
負擔適中簡述即可。
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
