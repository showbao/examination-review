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
# 模型管理（版本號解析 + 智慧選擇）
# ==========================================

_EXCLUDED_KEYWORDS = ["thinking", "experimental", "exp-", "lite", "8b", "nano"]


def _parse_model_version(name: str) -> tuple:
    match = re.search(r'gemini[- ](\d+)\.(\d+)', name.lower())
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (0, 0)


def _prefer_latest(name: str) -> int:
    return 1 if "latest" in name.lower() else 0


def _get_best_model(api_key: str, model_type: str) -> str:
    genai.configure(api_key=api_key)
    fallback = f"models/gemini-1.5-{model_type}"
    try:
        all_models = genai.list_models()
        candidates = [
            m for m in all_models
            if 'generateContent' in m.supported_generation_methods
            and model_type in m.name.lower()
            and "gemini" in m.name.lower()
            and not any(kw in m.name.lower() for kw in _EXCLUDED_KEYWORDS)
        ]
        if not candidates:
            return fallback
        candidates.sort(
            key=lambda m: (_parse_model_version(m.name), _prefer_latest(m.name), m.name),
            reverse=True,
        )
        return candidates[0].name
    except Exception:
        return fallback


def get_best_flash_model(api_key: str) -> str:
    cache_key = "_cached_flash_model"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    model = _get_best_model(api_key, "flash")
    st.session_state[cache_key] = model
    return model


def get_best_pro_model(api_key: str) -> str:
    cache_key = "_cached_pro_model"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    model = _get_best_model(api_key, "pro")
    st.session_state[cache_key] = model
    return model


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
    # 移除成對和殘留的 Markdown 粗體/底線標記
    text = re.sub(r'\*{1,2}', '', text)
    text = re.sub(r'_{1,2}', '', text)
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


# ==========================================
# 重複表格去重
# ==========================================

def _normalize_table_header(header_line: str) -> str:
    cells = [c.strip().lower() for c in header_line.strip().strip("|").split("|")]
    return "|".join(cells)


def deduplicate_markdown_tables(text: str) -> str:
    lines = text.split("\n")
    table_blocks = []
    i = 0
    while i < len(lines):
        if is_markdown_table_line(lines[i]):
            start = i
            first_line = lines[i]
            while i < len(lines) and (is_markdown_table_line(lines[i]) or is_markdown_separator_line(lines[i])):
                i += 1
            table_blocks.append({"start": start, "end": i, "header_norm": _normalize_table_header(first_line)})
        else:
            i += 1
    if not table_blocks:
        return text
    header_counts = Counter(tb["header_norm"] for tb in table_blocks)
    duplicate_headers = {h for h, c in header_counts.items() if c > 1}
    if not duplicate_headers:
        return text
    last_occurrence = {}
    for tb in table_blocks:
        if tb["header_norm"] in duplicate_headers:
            last_occurrence[tb["header_norm"]] = tb["start"]
    remove_lines = set()
    for tb in table_blocks:
        if tb["header_norm"] in duplicate_headers and tb["start"] != last_occurrence[tb["header_norm"]]:
            for j in range(tb["start"], tb["end"]):
                remove_lines.add(j)
    for line_idx in sorted(remove_lines):
        check = line_idx + 1
        while check < len(lines) and check not in remove_lines:
            stripped = lines[check].strip()
            if not stripped:
                remove_lines.add(check)
                check += 1
            elif re.match(r'^[\(（]?(?:修正|調整|更新|重新計算)', stripped):
                remove_lines.add(check)
                check += 1
            else:
                break
    result_lines = [lines[i] for i in range(len(lines)) if i not in remove_lines]
    result = "\n".join(result_lines)
    return re.sub(r'\n{3,}', '\n\n', result)


# ==========================================
# AI 輸出清洗
# ==========================================

def clean_ai_hallucinations(text):
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

    text = deduplicate_markdown_tables(text)
    return normalize_analysis_tables(text)


# ==========================================
# JSON 解析防禦
# ==========================================

def safe_parse_json(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    text = text.strip()
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        start = text.index('{')
        end = text.rindex('}') + 1
        return json.loads(text[start:end])
    except Exception:
        return None


# ==========================================
# API 呼叫重試機制
# ==========================================

def call_with_retry(model, prompt_parts, generation_config,
                    max_retries: int = 2, base_wait: int = 15,
                    status_callback=None):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return model.generate_content(prompt_parts, generation_config=generation_config)
        except Exception as e:
            last_error = e
            if "429" in str(e) and attempt < max_retries:
                wait_time = base_wait * (attempt + 1)
                if status_callback:
                    status_callback(f"⏳ AI 忙線中，{wait_time} 秒後自動重試（第 {attempt+1}/{max_retries} 次）...")
                time.sleep(wait_time)
                continue
            raise last_error


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

EXAM_TYPE_MAP = {
    "第一次月考": "第一次月考", "第一次定期評量": "第一次月考",
    "月考一": "第一次月考", "期中評量": "第一次月考", "期中考": "第一次月考",
    "第二次月考": "第二次月考", "第二次定期評量": "第二次月考",
    "月考二": "第二次月考", "期末評量": "第二次月考", "期末考": "第二次月考",
}


def normalize_exam_type(raw_exam_type: str) -> str:
    raw = raw_exam_type.strip()
    if raw in EXAM_TYPE_MAP:
        return EXAM_TYPE_MAP[raw]
    for key, value in EXAM_TYPE_MAP.items():
        if key in raw:
            return value
    return ""


def get_curriculum_standards(grade, subject, semester, exam_type):
    result = {"standards": "", "match_type": "none", "label": ""}
    if not grade or not subject or not semester:
        return result
    normalized_exam = normalize_exam_type(exam_type)
    try:
        client = get_gspread_client()
        ws = client.open_by_key(st.secrets["GOOGLE_SHEET_ID"]).worksheet("curriculum")
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return result
        data_rows = rows[1:]
        exact_match = None
        semester_matches = []
        for row in data_rows:
            if len(row) < 5:
                continue
            rg, rs, rse, re_, rc = [row[i].strip() for i in range(5)]
            if not rc:
                continue
            if rg == grade and rs == subject and rse == semester:
                if normalized_exam and re_ == normalized_exam:
                    exact_match = rc
                    break
                semester_matches.append(rc)
        if exact_match:
            result = {"standards": exact_match, "match_type": "exact",
                      "label": f"{grade} {subject} {semester} {normalized_exam}"}
        elif semester_matches:
            result = {"standards": "\n".join(dict.fromkeys(semester_matches)),
                      "match_type": "semester",
                      "label": f"{grade} {subject} {semester}（完整學期）"}
    except Exception as e:
        print(f"curriculum read error: {e}")
    return result


def build_curriculum_prompt_text(curriculum: dict) -> str:
    if not curriculum or not curriculum.get("standards"):
        return ""
    lines = [
        f"【本次評量對應教學重點 — {curriculum['label']}】：",
        curriculum["standards"], "",
        "⚠️ 以下審查請全程參照上方教學重點清單：",
        "1. 若試題考查的知識點不在清單內，於「待確認試題及修改建議」標記「⚠️ 疑似超出命題範圍」。",
        "2. 雙向細目表的認知向度分類，請以清單中各知識點的認知層次為依據。",
        "3. 難易度評估請以清單為基準：",
        "   - 易：學生已學且概念單純（直接對應單一教學重點）",
        "   - 中：需整合清單中兩個以上教學重點",
        "   - 難：超出教學重點範圍，或需高階推理（同時標記疑似超出範圍）",
    ]
    return "\n".join(lines) + "\n\n"
