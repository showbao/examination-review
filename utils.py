import os
import re
import time
import json
import tempfile
from collections import Counter
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================
# 模型管理
# ==========================================

PDF_FLASH_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-1.5-flash",
]
PDF_PRO_MODELS = [
    "models/gemini-2.5-pro",
    "models/gemini-1.5-pro",
]
METADATA_MODEL = PDF_FLASH_MODELS[0]

def _parse_model_version(name: str) -> tuple:
    match = re.search(r'gemini[- ](\d+)\.(\d+)', name.lower())
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

def _prefer_latest(name: str) -> int:
    return 1 if "latest" in name.lower() else 0

def _available_generate_content_models(api_key: str) -> set:
    genai.configure(api_key=api_key)
    return {
        m.name for m in genai.list_models()
        if 'generateContent' in m.supported_generation_methods
    }

def _get_best_model(api_key: str, model_type: str) -> str:
    allowed = PDF_PRO_MODELS if model_type == "pro" else PDF_FLASH_MODELS
    try:
        available = _available_generate_content_models(api_key)
        for model_name in allowed:
            if model_name in available:
                return model_name
        return allowed[-1]
    except Exception:
        return allowed[0]

def get_best_flash_model(api_key: str) -> str:
    k = "_cached_flash_model"
    if k in st.session_state: return st.session_state[k]
    m = _get_best_model(api_key, "flash"); st.session_state[k] = m; return m

def get_best_pro_model(api_key: str) -> str:
    k = "_cached_pro_model"
    if k in st.session_state: return st.session_state[k]
    m = _get_best_model(api_key, "pro"); st.session_state[k] = m; return m

def is_input_modality_error(error) -> bool:
    msg = str(error).lower()
    return any(token in msg for token in [
        "image input modality",
        "input modality",
        "modality is not enabled",
        "does not support image",
        "does not support pdf",
    ])

# ==========================================
# PDF 上傳
# ==========================================

def upload_to_gemini(file_obj):
    if not file_obj.name.lower().endswith(".pdf"):
        raise ValueError("目前僅支援 PDF 檔案上傳。")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_obj.getvalue()); tmp_path = tmp.name
    ref = genai.upload_file(tmp_path, mime_type="application/pdf")
    while ref.state.name == "PROCESSING":
        time.sleep(1); ref = genai.get_file(ref.name)
    os.remove(tmp_path)
    return ref

# ==========================================
# 文字清洗
# ==========================================

def clean_markdown_symbol(text):
    text = re.sub(r'\*{1,2}', '', text)
    text = re.sub(r'_{1,2}', '', text)
    text = text.replace("<br>", "").replace("<br/>", "").replace("<br />", "")
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'^[\*\-]\s+', '', text)
    for icon in ["✏️","🟢","🔴","🟡","⚠️","👍","💡","📊","⚖️","📖","🧮"]:
        text = text.replace(icon, "")
    return text.lstrip("*- ").strip()

def is_markdown_table_line(line):
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 3

def is_markdown_separator_line(line):
    c = line.strip().replace(" ", "")
    return bool(re.fullmatch(r'\|?[:\-\|]+\|?', c)) and "-" in c

def parse_markdown_table_rows(table_lines):
    rows, mx = [], 0
    for raw in table_lines:
        if is_markdown_separator_line(raw): continue
        cells = [clean_markdown_symbol(c.strip()) for c in raw.strip().strip("|").split("|")]
        rows.append(cells); mx = max(mx, len(cells))
    for r in rows:
        if len(r) < mx: r.extend([""] * (mx - len(r)))
    return rows

def normalize_analysis_tables(text):
    lines, norm, i = text.split("\n"), [], 0
    while i < len(lines):
        if is_markdown_table_line(lines[i]):
            block = []
            while i < len(lines) and is_markdown_table_line(lines[i]):
                block.append(lines[i]); i += 1
            rows = parse_markdown_table_rows(block)
            if rows:
                h = rows[0]; nc = len(h)
                norm.append("| " + " | ".join(h) + " |")
                norm.append("| " + " | ".join(["---"]*nc) + " |")
                for r in rows[1:]: norm.append("| " + " | ".join(r[:nc]) + " |")
            continue
        norm.append(lines[i]); i += 1
    return "\n".join(norm)

# ==========================================
# 表格去重
# ==========================================

def _normalize_table_header(header_line: str) -> str:
    return "|".join(c.strip().lower() for c in header_line.strip().strip("|").split("|"))

def deduplicate_markdown_tables(text: str) -> str:
    lines = text.split("\n"); blocks, i = [], 0
    while i < len(lines):
        if is_markdown_table_line(lines[i]):
            s = i; fl = lines[i]
            while i < len(lines) and (is_markdown_table_line(lines[i]) or is_markdown_separator_line(lines[i])): i += 1
            blocks.append({"start":s,"end":i,"header_norm":_normalize_table_header(fl)})
        else: i += 1
    if not blocks: return text
    hc = Counter(b["header_norm"] for b in blocks)
    dups = {h for h,c in hc.items() if c > 1}
    if not dups: return text
    last = {}
    for b in blocks:
        if b["header_norm"] in dups: last[b["header_norm"]] = b["start"]
    rm = set()
    for b in blocks:
        if b["header_norm"] in dups and b["start"] != last[b["header_norm"]]:
            rm.update(range(b["start"], b["end"]))
    for li in sorted(rm):
        ck = li + 1
        while ck < len(lines) and ck not in rm:
            s = lines[ck].strip()
            if not s: rm.add(ck); ck += 1
            elif re.match(r'^[\(（]?(?:修正|調整|更新|重新計算)', s): rm.add(ck); ck += 1
            else: break
    return re.sub(r'\n{3,}', '\n\n', "\n".join(lines[i] for i in range(len(lines)) if i not in rm))

# ==========================================
# AI 輸出清洗
# ==========================================

def clean_ai_hallucinations(text):
    tbs = []
    def _protect(m): tbs.append(m.group(0)); return f"@@TB_{len(tbs)-1}@@"
    text = re.sub(r'((?:^\|.*\|\s*$\n?){2,})', _protect, text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[一二三四五六七八九十0-9]+[、\.][\u4e00-\u9fa5]+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'([。；：])\s*([一二三四五六七八九十\d]+-[\d]+)', r'\1\n* \2', text)
    def _trunc(m):
        h, c = m.group(1), m.group(2)
        ls = [l for l in c.split('\n') if l.strip()]
        if len(ls) > 5: return f"{h}\n" + "\n".join(ls[:5]) + "\n* (其餘優良試題略)...\n"
        return m.group(0)
    for pat in [r'優良試題', r'真素養', r'通過']:
        text = re.sub(rf'(###\s*🟢\s*{pat}.*?)((\n\s*[\*\-].*?)+)(?=\n###)', _trunc, text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    for idx, b in enumerate(tbs): text = text.replace(f"@@TB_{idx}@@", normalize_analysis_tables(b))
    return normalize_analysis_tables(deduplicate_markdown_tables(text))

# ==========================================
# JSON / API
# ==========================================

def safe_parse_json(text: str) -> dict:
    t = text.strip()
    if "```json" in t: t = t.split("```json")[1].split("```")[0]
    elif "```" in t: t = t.split("```")[1].split("```")[0]
    t = re.sub(r',\s*}', '}', re.sub(r',\s*]', ']', t.strip()))
    try: return json.loads(t)
    except Exception: pass
    try: return json.loads(t[t.index('{'):t.rindex('}')+1])
    except Exception: return None

def call_with_retry(model, prompt_parts, generation_config,
                    max_retries=2, base_wait=15, status_callback=None):
    for attempt in range(max_retries + 1):
        try:
            return model.generate_content(prompt_parts, generation_config=generation_config)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                w = base_wait * (attempt + 1)
                if status_callback: status_callback(f"⏳ AI 忙線中，{w}秒後重試（{attempt+1}/{max_retries}）...")
                time.sleep(w); continue
            raise

# ==========================================
# Google Sheets 共用
# ==========================================

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)

def _open_sheet():
    return get_gspread_client().open_by_key(st.secrets["GOOGLE_SHEET_ID"])

# ==========================================
# 使用紀錄
# ==========================================

def log_usage(email, action):
    try:
        ws = _open_sheet().worksheet("logs")
        now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([email, action, now])
    except Exception as e:
        print(f"log write error: {e}")
        st.warning("⚠️ 使用紀錄暫時無法寫入，但不影響本次審查。")

def get_all_logs():
    """讀取所有使用紀錄，回傳 list of dict"""
    try:
        ws = _open_sheet().worksheet("logs")
        rows = ws.get_all_values()
        if len(rows) <= 1: return []
        header = rows[0] if rows[0] else ["email", "action", "timestamp"]
        return [dict(zip(header, r)) for r in rows[1:] if len(r) >= 3]
    except Exception:
        return []

# ==========================================
# 教學重點 CRUD
# ==========================================

EXAM_TYPE_MAP = {
    "第一次月考":"第一次月考","第一次定期評量":"第一次月考",
    "月考一":"第一次月考","期中評量":"第一次月考","期中考":"第一次月考",
    "第二次月考":"第二次月考","第二次定期評量":"第二次月考",
    "月考二":"第二次月考","期末評量":"第二次月考","期末考":"第二次月考",
}

SUBJECT_MAP = {
    "國語": "國語", "國語文": "國語", "國語科": "國語", "語文": "國語",
    "語文領域": "國語", "國語文領域": "國語", "國語領域": "國語",
    "數學": "數學", "數學科": "數學", "數學領域": "數學",
    "英語": "英語", "英文": "英語", "英語科": "英語", "英語文": "英語",
    "英語領域": "英語", "英語文領域": "英語",
    "社會": "社會", "社會科": "社會", "社會領域": "社會",
    "自然": "自然", "自然科": "自然", "自然科學": "自然",
    "自然科學領域": "自然", "自然領域": "自然", "自然與生活科技": "自然",
}

_CN_DIGITS = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6}
_NUM_TO_GRADE = {1:"一年級",2:"二年級",3:"三年級",4:"四年級",5:"五年級",6:"六年級"}

def normalize_exam_type(raw):
    raw = raw.strip()
    if raw in EXAM_TYPE_MAP: return EXAM_TYPE_MAP[raw]
    for k, v in EXAM_TYPE_MAP.items():
        if k in raw: return v
    return ""

def normalize_subject(raw):
    """正規化科目名稱，如「自然科學領域」→「自然」"""
    raw = raw.strip()
    if raw in SUBJECT_MAP: return SUBJECT_MAP[raw]
    # 模糊比對：只要包含關鍵字
    for k, v in SUBJECT_MAP.items():
        if k in raw: return v
    return raw  # 找不到就原樣回傳

def normalize_grade(raw):
    """正規化年級名稱，如「5年級」→「五年級」、「四」→「四年級」"""
    raw = raw.strip()
    # 已經是標準格式
    if raw in _NUM_TO_GRADE.values():
        return raw
    # 「四」→「四年級」
    if raw in _CN_DIGITS:
        return f"{raw}年級"
    # 「4年級」「5 年級」→ 阿拉伯數字轉中文
    m = re.match(r'^(\d)[年]?級?$', raw.replace(" ", ""))
    if m:
        n = int(m.group(1))
        return _NUM_TO_GRADE.get(n, raw)
    # 「四年級」但帶有額外空白或字元
    for cn, num in _CN_DIGITS.items():
        if cn in raw and "年" in raw:
            return f"{cn}年級"
    return raw  # 找不到就原樣回傳

def get_all_curriculum():
    """讀取全部教學重點資料，回傳 list of dict"""
    try:
        ws = _open_sheet().worksheet("curriculum")
        rows = ws.get_all_values()
        if len(rows) <= 1: return []
        return [{"年級": r[0], "科目": r[1], "學期": r[2], "評量類別": r[3],
                 "教學重點": r[4] if len(r) > 4 else ""} for r in rows[1:]]
    except Exception:
        return []

def save_curriculum_filtered(data_list, grade=None, subject=None, semester=None):
    """
    儲存教學重點。
    1. 先備份到 curriculum_backup
    2. 刪除符合篩選條件的舊資料
    3. 寫入新資料
    若 grade/subject/semester 為 None 表示全部覆蓋。
    """
    try:
        sh = _open_sheet()
        ws = sh.worksheet("curriculum")
        all_rows = ws.get_all_values()
        header = all_rows[0] if all_rows else ["年級", "科目", "學期", "評量類別", "教學重點"]
        old_data = all_rows[1:] if len(all_rows) > 1 else []

        # 備份
        try:
            bk = sh.worksheet("curriculum_backup")
        except gspread.exceptions.WorksheetNotFound:
            bk = sh.add_worksheet("curriculum_backup", rows=1, cols=5)
        bk.clear()
        if all_rows:
            bk.update(range_name="A1", values=all_rows)

        # 判斷哪些舊列要保留（不在篩選範圍內的）
        keep = []
        for r in old_data:
            if len(r) < 4: continue
            match = True
            if grade and r[0].strip() != grade: match = False
            if subject and r[1].strip() != subject: match = False
            if semester and r[2].strip() != semester: match = False
            if not match:
                keep.append(r)

        # 組合新資料
        new_rows = []
        for d in data_list:
            row = [d.get("年級",""), d.get("科目",""), d.get("學期",""),
                   d.get("評量類別",""), d.get("教學重點","")]
            if any(c.strip() for c in row):  # 跳過全空列
                new_rows.append(row)

        final = [header] + keep + new_rows

        # 寫入
        ws.clear()
        if final:
            ws.update(range_name="A1", values=final)

        return True, f"✅ 已儲存 {len(new_rows)} 筆教學重點（備份已建立於 curriculum_backup）"
    except Exception as e:
        return False, f"❌ 儲存失敗：{e}"

def get_curriculum_standards(grade, subject, semester, exam_type):
    result = {"standards": "", "match_type": "none", "label": ""}
    if not grade or not subject or not semester: return result
    norm_grade = normalize_grade(grade)
    norm_subject = normalize_subject(subject)
    norm_semester = semester.strip()
    norm_exam = normalize_exam_type(exam_type)
    try:
        ws = _open_sheet().worksheet("curriculum")
        rows = ws.get_all_values()
        if len(rows) <= 1: return result
        exact, sem_matches = None, []
        for r in rows[1:]:
            if len(r) < 5: continue
            rg, rs, rse, re_, rc = [r[i].strip() for i in range(5)]
            if not rc: continue
            # 正規化 Sheets 端的值再比對
            if normalize_grade(rg) == norm_grade and normalize_subject(rs) == norm_subject and rse == norm_semester:
                if norm_exam and re_ == norm_exam: exact = rc; break
                sem_matches.append(rc)
        if exact:
            result = {"standards": exact, "match_type": "exact",
                      "label": f"{norm_grade} {norm_subject} {norm_semester} {norm_exam}"}
        elif sem_matches:
            result = {"standards": "\n".join(dict.fromkeys(sem_matches)),
                      "match_type": "semester",
                      "label": f"{norm_grade} {norm_subject} {norm_semester}（完整學期）"}
    except Exception as e:
        print(f"curriculum read error: {e}")
    return result

def build_curriculum_prompt_text(curriculum):
    if not curriculum or not curriculum.get("standards"): return ""
    lines = [
        f"【本次評量對應教學重點 — {curriculum['label']}】：",
        curriculum["standards"], "",
        "⚠️ 以下審查請全程參照上方教學重點清單：",
        "1. 若知識點不在清單內，標記「⚠️ 疑似超出命題範圍」。",
        "2. 雙向細目表認知向度以清單知識點認知層次為依據。",
        "3. 難易度以清單為基準：易＝單一教學重點；中＝整合兩個以上；難＝超出範圍或高階推理。",
    ]
    return "\n".join(lines) + "\n\n"

# ==========================================
# 系統公告
# ==========================================

def get_announcement() -> str:
    """從 settings 工作表讀取公告文字"""
    try:
        ws = _open_sheet().worksheet("settings")
        rows = ws.get_all_values()
        for r in rows:
            if len(r) >= 2 and r[0].strip() == "announcement":
                return r[1]
        return ""
    except Exception:
        return ""

def save_announcement(text: str) -> tuple:
    """儲存公告文字到 settings 工作表"""
    try:
        sh = _open_sheet()
        try:
            ws = sh.worksheet("settings")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet("settings", rows=10, cols=2)
            ws.update(range_name="A1", values=[["key", "value"]])

        rows = ws.get_all_values()
        found = False
        for i, r in enumerate(rows):
            if len(r) >= 1 and r[0].strip() == "announcement":
                ws.update_cell(i + 1, 2, text)
                found = True
                break
        if not found:
            ws.append_row(["announcement", text])

        return True, "✅ 公告已更新"
    except Exception as e:
        return False, f"❌ 儲存失敗：{e}"
