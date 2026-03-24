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
# Google Sheets
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
