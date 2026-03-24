import os
import re
import time
import tempfile
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================
# 模型管理
# ==========================================

def get_best_flash_model(api_key):
    genai.configure(api_key=api_key)
    try:
        models = [
            m for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
            and "flash" in m.name.lower()
            and "gemini" in m.name.lower()
        ]
        models.sort(key=lambda x: x.name, reverse=True)
        return models[0].name if models else "models/gemini-1.5-flash"
    except Exception:
        return "models/gemini-1.5-flash"

def get_best_pro_model(api_key):
    genai.configure(api_key=api_key)
    try:
        models = [
            m for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
            and "pro" in m.name.lower()
            and "gemini" in m.name.lower()
        ]
        models.sort(key=lambda x: x.name, reverse=True)
        return models[0].name if models else "models/gemini-1.5-pro"
    except Exception:
        return "models/gemini-1.5-pro"

# ==========================================
# PDF 上傳
# ==========================================

def upload_to_gemini(file_obj):
    filename = file_obj.name.lower()
    if not filename.endswith(".pdf"):
        raise ValueError("目前僅支援 PDF 檔案上傳。")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_obj.getvalue())
        tmp_path = tmp.name

    file_ref = genai.upload_file(tmp_path, mime_type="application/pdf")

    while file_ref.state.name == "PROCESSING":
        time.sleep(1)
        file_ref = genai.get_file(file_ref.name)

    os.remove(tmp_path)
    return file_ref

# ==========================================
# 文字清洗與正規化
# ==========================================

def clean_markdown_symbol(text):
    text = text.replace("**", "").replace("__", "")
    text = text.replace("<br>", "").replace("<br/>", "").replace("<br />", "")
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'^[\*\-]\s+', '', text)
    for icon in ["✏️", "🟢", "🔴", "🟡", "⚠️", "👍", "💡", "📊", "⚖️", "📖", "🧮"]:
        text = text.replace(icon, "")
    text = text.lstrip("*- ")
    return text.strip()

def is_markdown_table_line(line):
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3

def is_markdown_separator_line(line):
    compact = line.strip().replace(" ", "")
    return bool(re.fullmatch(r'\|?[:\-\|]+\|?', compact)) and "-" in compact

def parse_markdown_table_rows(table_lines):
    rows = []
    max_cols = 0
    for raw in table_lines:
        if is_markdown_separator_line(raw):
            continue
        cells = [clean_markdown_symbol(c.strip()) for c in raw.strip().strip("|").split("|")]
        rows.append(cells)
        max_cols = max(max_cols, len(cells))
    for row in rows:
        if len(row) < max_cols:
            row.extend([""] * (max_cols - len(row)))
    return rows

def normalize_analysis_tables(text):
    lines = text.split("\n")
    normalized = []
    i = 0
    while i < len(lines):
        if is_markdown_table_line(lines[i]):
            block = []
            while i < len(lines) and is_markdown_table_line(lines[i]):
                block.append(lines[i])
                i += 1
            rows = parse_markdown_table_rows(block)
            if rows:
                header = rows[0]
                col_count = len(header)
                normalized.append("| " + " | ".join(header) + " |")
                normalized.append("| " + " | ".join(["---"] * col_count) + " |")
                for row in rows[1:]:
                    normalized.append("| " + " | ".join(row[:col_count]) + " |")
            continue
        normalized.append(lines[i])
        i += 1
    return "\n".join(normalized)

def clean_ai_hallucinations(text):
    """針對 AI 輸出進行清洗，但保護 Markdown 表格區塊"""
    table_blocks = []

    def protect_table(match):
        table_blocks.append(match.group(0))
        return f"@@TABLE_BLOCK_{len(table_blocks)-1}@@"

    text = re.sub(r'((?:^\|.*\|\s*$\n?){2,})', protect_table, text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[一二三四五六七八九十0-9]+[、\.][\u4e00-\u9fa5]+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'([。；：])\s*([一二三四五六七八九十\d]+-[\d]+)', r'\1\n* \2', text)

    def truncate_list(match):
        header = match.group(1)
        content = match.group(2)
        lines = [line for line in content.split('\n') if line.strip()]
        if len(lines) > 5:
            new_content = "\n".join(lines[:5]) + "\n* (其餘優良試題略)..."
            return f"{header}\n{new_content}\n"
        return match.group(0)

    text = re.sub(r'(###\s*🟢\s*優良試題.*?)((\n\s*[\*\-].*?)+)(?=\n###)', truncate_list, text, flags=re.DOTALL)
    text = re.sub(r'(###\s*🟢\s*真素養.*?)((\n\s*[\*\-].*?)+)(?=\n###)', truncate_list, text, flags=re.DOTALL)
    text = re.sub(r'(###\s*🟢\s*通過.*?)((\n\s*[\*\-].*?)+)(?=\n###)', truncate_list, text, flags=re.DOTALL)

    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    for idx, block in enumerate(table_blocks):
        text = text.replace(f"@@TABLE_BLOCK_{idx}@@", normalize_analysis_tables(block))

    return normalize_analysis_tables(text)

# ==========================================
# Google Sheets：使用記錄
# ==========================================

@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)

def log_usage(email, action):
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(st.secrets["GOOGLE_SHEET_ID"]).worksheet("logs")
        now_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([email, action, now_str])
    except Exception as e:
        print(f"log write error: {e}")
        st.warning("⚠️ 使用紀錄暫時無法寫入，但不影響本次審查。")

# ==========================================
# Google Sheets：課程教學重點
# ==========================================

# 評量類別正規化對照表
# AI 萃取的文字 → Sheet 查詢值
EXAM_TYPE_MAP = {
    "第一次月考":   "第一次月考",
    "第一次定期評量": "第一次月考",
    "月考一":      "第一次月考",
    "期中評量":    "第一次月考",
    "期中考":      "第一次月考",
    "第二次月考":   "第二次月考",
    "第二次定期評量": "第二次月考",
    "月考二":      "第二次月考",
    "期末評量":    "第二次月考",
    "期末考":      "第二次月考",
}

def normalize_exam_type(raw_exam_type: str) -> str:
    """將 AI 萃取的評量類別正規化為 Sheet 查詢值，找不到回傳空字串"""
    raw = raw_exam_type.strip()
    if raw in EXAM_TYPE_MAP:
        return EXAM_TYPE_MAP[raw]
    # 模糊比對：只要包含關鍵字
    for key, value in EXAM_TYPE_MAP.items():
        if key in raw:
            return value
    return ""

def get_curriculum_standards(grade: str, subject: str, semester: str, exam_type: str) -> dict:
    """
    從 Google Sheets 的 curriculum 工作表查詢教學重點。

    回傳 dict：
        {
            "standards": str,       # 教學重點文字（空字串表示查無資料）
            "match_type": str,      # "exact" | "semester" | "none"
            "label": str            # 供 UI 顯示用的說明文字
        }

    Sheet 欄位順序（A~E）：
        A: 年級　B: 科目　C: 學期　D: 評量類別　E: 教學重點
    """
    result = {"standards": "", "match_type": "none", "label": ""}

    if not grade or not subject or not semester:
        return result

    normalized_exam = normalize_exam_type(exam_type)

    try:
        client = get_gspread_client()
        ws = client.open_by_key(st.secrets["GOOGLE_SHEET_ID"]).worksheet("curriculum")
        rows = ws.get_all_values()

        if len(rows) <= 1:
            return result  # 只有標題列或空表

        header = rows[0]  # 跳過標題列
        data_rows = rows[1:]

        # 欄位索引（依 A~E 順序）
        COL_GRADE    = 0
        COL_SUBJECT  = 1
        COL_SEMESTER = 2
        COL_EXAM     = 3
        COL_CONTENT  = 4

        exact_match = None
        semester_matches = []

        for row in data_rows:
            if len(row) < 5:
                continue

            row_grade    = row[COL_GRADE].strip()
            row_subject  = row[COL_SUBJECT].strip()
            row_semester = row[COL_SEMESTER].strip()
            row_exam     = row[COL_EXAM].strip()
            row_content  = row[COL_CONTENT].strip()

            if not row_content:
                continue

            # 年級、科目、學期三者都符合
            if row_grade == grade and row_subject == subject and row_semester == semester:
                # 精確比對（含評量類別）
                if normalized_exam and row_exam == normalized_exam:
                    exact_match = row_content
                    break
                # 寬鬆比對（整學期備用）
                semester_matches.append(row_content)

        if exact_match:
            result["standards"]  = exact_match
            result["match_type"] = "exact"
            result["label"]      = f"{grade} {subject} {semester} {normalized_exam}"
        elif semester_matches:
            # 合併整學期所有列的教學重點（去重）
            combined = "\n".join(dict.fromkeys(semester_matches))
            result["standards"]  = combined
            result["match_type"] = "semester"
            result["label"]      = f"{grade} {subject} {semester}（完整學期）"
        # else: match_type 維持 "none"

    except Exception as e:
        print(f"curriculum read error: {e}")
        # 靜默失敗，不影響審查流程

    return result

def build_curriculum_prompt_text(curriculum: dict) -> str:
    """將教學重點 dict 轉為注入 Prompt 的文字段落，查無資料時回傳空字串"""
    if not curriculum or not curriculum.get("standards"):
        return ""

    lines = [
        f"【本次評量對應教學重點 — {curriculum['label']}】：",
        curriculum["standards"],
        "",
        "⚠️ 以下審查請全程參照上方教學重點清單：",
        "1. 若試題考查的知識點不在清單內，於「待確認試題及修改建議」標記「⚠️ 疑似超出命題範圍」。",
        "2. 雙向細目表的認知向度分類，請以清單中各知識點的認知層次為依據。",
        "3. 難易度評估請以清單為基準：",
        "   - 易：學生已學且概念單純（直接對應單一教學重點）",
        "   - 中：需整合清單中兩個以上教學重點",
        "   - 難：超出教學重點範圍，或需高階推理（同時標記疑似超出範圍）",
    ]
    return "\n".join(lines) + "\n\n"
