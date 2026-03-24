import re
from io import BytesIO
import time
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT

from utils import (
    clean_markdown_symbol,
    is_markdown_table_line,
    parse_markdown_table_rows,
    normalize_analysis_tables,
)

# ==========================================
# 字型設定
# ==========================================

def set_font_style(run, size=12, bold=False, color=None):
    """設定字體為標楷體 + Times New Roman"""
    run.font.name = 'Times New Roman'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), '標楷體')
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color

# ==========================================
# 標題識別與正規化
# ==========================================

def is_main_section_header(line):
    clean = clean_markdown_symbol(line.strip())
    main_headers = [
        "總結與建議",
        "題幹與邏輯品質",
        "素養導向深度審查",
        "公平性與敏感度審查",
        "雙向細目表核算",
        "難易度與負擔分析",
        "評量診斷與補救教學"
    ]
    return clean in main_headers

SUB_HEADER_ALIASES = {
    "最優先修正": "最優先修正",
    "最優先修正 (Critical)": "最優先修正",
    "難度與鑑別度點評": "難度與鑑別度點評",
    "值得讚許之處": "值得讚許之處",
    "後續優化建議": "後續優化建議",
    "優良試題": "優良試題",
    "待確認試題及修改建議": "待確認試題及修改建議",
    "真素養": "真素養",
    "假素養/待確認": "假素養/待確認",
    "通過 (無敏感議題)": "通過 (無敏感議題)",
    "潛在爭議 (具體指出問題)": "潛在爭議 (具體指出問題)",
    "整體作答負擔觀察": "整體作答負擔觀察",
    "閱讀負擔": "閱讀負擔",
    "圖表判讀負擔": "圖表判讀負擔",
    "運算負擔": "運算負擔"
}

TEXT_MODE_SUBHEADERS = {
    "閱讀負擔",
    "圖表判讀負擔",
    "運算負擔"
}

def normalize_sub_header_text(text):
    text = clean_markdown_symbol(text.strip())
    text = re.sub(r'^[✏️📖📊🧮🔴⚖️👍💡🟢🟡⚠️📌]+\s*', '', text)
    text = re.sub(r'\s*[:：]\s*$', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def canonical_sub_header(text):
    normalized = normalize_sub_header_text(text)
    if normalized.startswith("最優先修正"):
        return "最優先修正"
    if normalized.startswith("難度與鑑別度點評"):
        return "難度與鑑別度點評"
    if normalized.startswith("值得讚許之處"):
        return "值得讚許之處"
    if normalized.startswith("後續優化建議"):
        return "後續優化建議"
    if normalized.startswith("待確認試題及修改建議"):
        return "待確認試題及修改建議"
    for alias, canonical in SUB_HEADER_ALIASES.items():
        if normalized.startswith(alias):
            return canonical
    return normalized

def is_sub_section_header(line):
    normalized = normalize_sub_header_text(line)
    allowed_headers = set(SUB_HEADER_ALIASES.values())
    for header in allowed_headers:
        if re.fullmatch(rf'{re.escape(header)}\s*[：:]?\s*', normalized):
            return True
    return False

def normalize_compare_text(text):
    text = clean_markdown_symbol(text.strip())
    text = re.sub(r'\s+', '', text)
    text = re.sub(r'[：:，,。．、；;（）()]', '', text)
    return text.strip()

# ==========================================
# Word 段落輸出函式
# ==========================================

def add_main_section_title(doc, text):
    doc.add_paragraph()
    p = doc.add_paragraph()
    run = p.add_run(text)
    set_font_style(run, size=16, bold=True, color=RGBColor(91, 124, 153))
    run.font.underline = True

def add_sub_section_title(container, text):
    spacer = container.add_paragraph()
    spacer.paragraph_format.space_after = Pt(6)
    p = container.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.75)
    run = p.add_run(canonical_sub_header(text))
    set_font_style(run, size=13, bold=True, color=RGBColor(111, 133, 158))
    return p

def add_bullet_to_cell(container, text):
    """第一層列點（題號行）"""
    p = container.add_paragraph()
    p.paragraph_format.left_indent = Cm(1.0)
    p.paragraph_format.first_line_indent = Cm(0)
    run_bullet = p.add_run("• ")
    set_font_style(run_bullet, size=12)
    run_text = p.add_run(text)
    set_font_style(run_text, size=12)
    return p

def add_indented_sub_bullet_to_cell(container, text):
    """第二層列點（問題點／修改方向／修改範例），以內容特徵【】判斷"""
    p = container.add_paragraph()
    p.paragraph_format.left_indent = Cm(2.0)
    p.paragraph_format.first_line_indent = Cm(0)
    run_bullet = p.add_run("－ ")
    set_font_style(run_bullet, size=12, color=RGBColor(111, 133, 158))
    # 【標籤】部分加粗
    label_match = re.match(r'^(【[^】]+】：?)(.*)', text, re.DOTALL)
    if label_match:
        run_label = p.add_run(label_match.group(1))
        set_font_style(run_label, size=12, bold=True)
        run_content = p.add_run(label_match.group(2))
        set_font_style(run_content, size=12)
    else:
        run_text = p.add_run(text)
        set_font_style(run_text, size=12)
    return p

def add_plain_text_to_cell(container, text):
    p = container.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.75)
    run = p.add_run(text)
    set_font_style(run, size=12)
    return p

# ==========================================
# 表格輔助
# ==========================================

def set_cell_shading(cell, fill="D9D9D9"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), fill)
    tc_pr.append(shd)

def prevent_row_break(row):
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement('w:cantSplit')
    tr_pr.append(cant_split)

def _render_word_table(container, data):
    if not data:
        return
    rows_data = parse_markdown_table_rows(data) if isinstance(data[0], str) else data
    if not rows_data:
        return

    rows = len(rows_data)
    cols = max(len(row) for row in rows_data)

    table = container.add_table(rows=rows, cols=cols)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    header_texts = [str(x).strip() for x in rows_data[0]]
    if header_texts == ["認知向度", "對應題號", "比重"]:
        width_map = [Cm(4.0), Cm(10.0), Cm(4.0)]
    elif header_texts == ["難易度", "對應題號", "比重"]:
        width_map = [Cm(4.0), Cm(10.0), Cm(4.0)]
    else:
        width_map = [Cm(6.0)] * cols

    for r in range(rows):
        row = table.rows[r]
        prevent_row_break(row)
        for c in range(cols):
            cell = table.cell(r, c)
            text = rows_data[r][c] if c < len(rows_data[r]) else ""
            cell.text = text
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if c < len(width_map):
                cell.width = width_map[c]
            for p in cell.paragraphs:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.line_spacing = 1.5
                p.paragraph_format.keep_together = True
                p.paragraph_format.keep_with_next = True if r < rows - 1 else False
                for run in p.runs:
                    set_font_style(run, size=12)
            if r == 0:
                set_cell_shading(cell, "D9D9D9")
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.bold = True

# ==========================================
# Word 報告主函式
# ==========================================

def create_word_report(analysis_text, metadata):
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(1.27)
        section.bottom_margin = Cm(1.27)
        section.left_margin = Cm(1.27)
        section.right_margin = Cm(1.27)

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

    # 卷頭資訊表格
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

    # 命題教師修改及說明
    p = doc.add_paragraph()
    run = p.add_run("命題教師修改及說明")
    set_font_style(run, size=14, bold=True, color=RGBColor(91, 124, 153))

    feedback_table = doc.add_table(rows=1, cols=1)
    feedback_table.style = 'Table Grid'
    cell = feedback_table.cell(0, 0)
    checkbox_items = [
        "無需修改試題。",
        "經命題老師確認，以下試題為AI幻覺，已判斷無需修正。\n   試題：_______________________________________________________",
        "經命題老師確認，以下試題已修正。\n   試題：_______________________________________________________"
    ]
    for item_text in checkbox_items:
        p_check = cell.add_paragraph()
        p_check.paragraph_format.line_spacing = 2.0
        run_box = p_check.add_run("□ ")
        set_font_style(run_box, size=18)
        run_text = p_check.add_run(item_text)
        set_font_style(run_text, size=12)

    p_other = cell.add_paragraph("其他說明：")
    set_font_style(p_other.runs[0] if p_other.runs else p_other.add_run("其他說明："), size=12)
    p_other.paragraph_format.line_spacing = 2.0
    for _ in range(5):
        p_empty = cell.add_paragraph()
        p_empty.paragraph_format.line_spacing = 2.0
    doc.add_paragraph()

    # 系統免責聲明
    warning_text = "⚠️ 系統限制與聲明：本系統僅針對試題內容進行深度分析，未檢核「命題範圍」與「試卷形式」（如題號連貫性、配分加總正確性），請老師務必自行審閱。"
    p_warn = doc.add_paragraph()
    run_warn = p_warn.add_run(warning_text)
    set_font_style(run_warn, size=11, bold=True, color=RGBColor(255, 0, 0))

    doc.add_page_break()

    # --- 內容解析主迴圈 ---
    analysis_text = normalize_analysis_tables(analysis_text)
    lines = analysis_text.split('\n')
    table_mode = False
    table_data = []
    current_sub_header = None

    for raw_line in lines:
        stripped_line = raw_line.strip()

        if not stripped_line:
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            continue

        clean_text = clean_markdown_symbol(stripped_line)
        clean_text = re.sub(r'\s*[:：]\s*$', '', clean_text)

        if is_main_section_header(stripped_line):
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            current_sub_header = None
            add_main_section_title(doc, clean_text)
            continue

        if is_sub_section_header(stripped_line):
            if table_mode and table_data:
                _render_word_table(doc, table_data)
                table_mode = False
                table_data = []
            matched_sub_header = canonical_sub_header(stripped_line)
            add_sub_section_title(doc, matched_sub_header)
            current_sub_header = matched_sub_header
            continue

        if is_markdown_table_line(stripped_line):
            table_mode = True
            table_data.append(stripped_line)
            continue

        if table_mode and table_data:
            _render_word_table(doc, table_data)
            table_mode = False
            table_data = []

        if not clean_text:
            continue

        clean_text = re.sub(r'^\d+\.\s*', '', clean_text)

        # 副標文字模式（閱讀負擔等）
        if current_sub_header in TEXT_MODE_SUBHEADERS:
            normalized_clean = normalize_compare_text(clean_text)
            normalized_header = normalize_compare_text(current_sub_header)
            if normalized_clean.startswith(normalized_header):
                clean_text = re.sub(
                    rf'^\s*{re.escape(current_sub_header)}\s*[：:，,。．、；;（）()]*\s*',
                    '', clean_text
                ).strip()
                if not clean_text:
                    continue
            clean_text = re.sub(r'^[•\*\-]\s*', '', clean_text).strip()
            if clean_text:
                add_plain_text_to_cell(doc, clean_text)
            continue

        # 一般副標內容：去除重複標題字樣
        if current_sub_header is not None:
            normalized_clean = normalize_compare_text(clean_text)
            normalized_header = normalize_compare_text(current_sub_header)
            if normalized_clean.startswith(normalized_header):
                clean_text = re.sub(
                    rf'^\s*{re.escape(current_sub_header)}\s*[：:，,。．、；;（）()]*\s*',
                    '', clean_text
                ).strip()
                if not clean_text:
                    continue

        if re.match(r'^[\*\-]\s+', stripped_line) or re.match(r'^\d+\.\s*', stripped_line):
            # 「待確認試題及修改建議」區塊：
            # 以內容特徵【】判斷第二層，不依賴 AI 縮排格式
            if (current_sub_header == "待確認試題及修改建議"
                    and re.match(r'^【[^】]+】', clean_text)):
                add_indented_sub_bullet_to_cell(doc, clean_text)
            else:
                add_bullet_to_cell(doc, clean_text)
        else:
            if current_sub_header is not None:
                add_bullet_to_cell(doc, clean_text)
            else:
                add_plain_text_to_cell(doc, clean_text)

    if table_mode and table_data:
        _render_word_table(doc, table_data)

    doc.add_page_break()

    # 評量診斷與補救教學
    add_main_section_title(doc, "評量診斷與補救教學")
    remedial_table = doc.add_table(rows=1, cols=1)
    remedial_table.style = 'Table Grid'
    remedial_cell = remedial_table.cell(0, 0)
    remedial_lines = [
        "僅針對錯誤率較高的題目（一至二題）進行試題分析／學習診斷。",
        "",
        "【題目】 第（   ）大題第（   ）題",
        "",
        "【學習表現／學習內容】",
        "",
        "",
        "【評量結果分析】（為何此題錯誤率高？可從試題內容、教學方法等層面分析）",
        "",
        "",
        "",
        "",
        "【可行補救教學策略】（請列舉具體可行之策略）",
        "",
        "",
        "",
        "",
    ]
    for line in remedial_lines:
        p_rem = remedial_cell.add_paragraph()
        run = p_rem.add_run(line)
        set_font_style(run, size=12)

    f = BytesIO()
    doc.save(f)
    return f.getvalue()
