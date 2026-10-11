"""Bounded local document readers; no executable or remote document content."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import json
import subprocess
import sys
import tempfile
import time
import zipfile


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_CHUNKS = 20_000
MAX_PDF_PAGES = 2000
OCR_TIMEOUT_SECONDS = 300
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".docx", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@dataclass(frozen=True)
class TextPart:
    text: str
    location: str


def check_cancel(cancel=None):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("操作已取消，未保存本次解析结果。")


def validate_file(path: Path):
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("不支持此文件格式；请使用 TXT、MD、DOCX、XLSX、PDF 或图片，不支持脚本和宏文件。")
    if not path.is_file():
        raise ValueError("文件不存在或不是普通文件。")
    size = path.stat().st_size
    if size == 0:
        raise ValueError("文件为空，未导入任何内容。")
    if size > MAX_FILE_BYTES:
        raise ValueError("文件超过 50 MB 限制，请拆分后导入。")


def _check_archive(path, cancel):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10_000 or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                raise ValueError("文档解压后内容过大，请拆分后导入。")
            for entry in entries:
                check_cancel(cancel)
                if entry.flag_bits & 1:
                    raise ValueError("不支持加密文档，请先解除密码保护。")
                lowered = entry.filename.lower()
                if "vbaproject" in lowered or "/macrosheets/" in lowered:
                    raise ValueError("文档包含宏，知识库不接受宏文件。")
    except zipfile.BadZipFile as exc:
        raise ValueError("Office 文档已损坏或已加密，请用办公软件打开并另存为未加密文件。") from exc


def _plain_text(path, cancel):
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError("文件包含二进制内容，不是支持的 UTF-8 或 GB18030 文本。")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("文本编码无法识别，请另存为 UTF-8 或 GB18030。")
    if len(content) > MAX_TEXT_CHARS:
        raise ValueError("文档文本超过 200 万字符，请拆分后导入。")
    # Keep real line ranges while combining nearby lines into a useful context.
    lines, start, size = [], 1, 0
    for line_number, line in enumerate(content.splitlines(), 1):
        check_cancel(cancel)
        if lines and (size + len(line) > 1100 or not line.strip()):
            yield TextPart("\n".join(lines), f"第{start}—{line_number - 1}行")
            lines, size = [], 0
        if line.strip():
            if not lines:
                start = line_number
            lines.append(line)
            size += len(line)
    if lines:
        yield TextPart("\n".join(lines), f"第{start}—{line_number}行")


def _docx(path, cancel):
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_archive(path, cancel)
    document = Document(path)
    section, paragraph_number, table_number = "正文", 0, 0
    for element in document.element.body:
        check_cancel(cancel)
        if isinstance(element, CT_P):
            paragraph_number += 1
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style else ""
            if re.match(r"^(Heading|标题)\s*\d", style, re.I):
                section = text[:200]
            yield TextPart(text, f"{section} · 段落{paragraph_number}")
        elif isinstance(element, CT_Tbl):
            table_number += 1
            table = Table(element, document)
            first_row = ''
            for row_number, row in enumerate(table.rows, 1):
                check_cancel(cancel)
                cells = [cell.text.strip() for cell in row.cells]
                if not any(cells):
                    continue
                text = ' | '.join(f'第{index}列={value}' for index, value in enumerate(cells, 1))
                location = f"{section} · 表{table_number}第{row_number}行"
                if row_number == 1:
                    first_row = text[:600]
                elif first_row:
                    # The first row may be a title, so retain it as context, not an inferred schema.
                    text = f'参考首行（不自动判定为表头）：{first_row}\n当前行：{text}'
                    location += f'；参考表{table_number}第1行'
                yield TextPart(text, location)


def _xlsx(path, cancel):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    _check_archive(path, cancel)
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    visited = 0
    try:
        for sheet in workbook.worksheets:
            first_row, first_location = '', ''
            if (sheet.max_row or 0) > 100_000 or (sheet.max_column or 0) > 512:
                raise ValueError("工作表范围过大，请删除多余格式或拆分为不超过 10 万行、512 列的文件。")
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), 1):
                check_cancel(cancel)
                visited += len(row)
                if visited > 500_000:
                    raise ValueError("工作簿超过 50 万单元格解析限制，请拆分后导入。")
                nonempty = [(index, str(value).strip()) for index, value in enumerate(row, 1) if value is not None and str(value).strip()]
                if nonempty:
                    first, last = nonempty[0][0], nonempty[-1][0]
                    location = f"工作表「{sheet.title}」{get_column_letter(first)}{row_number}:{get_column_letter(last)}{row_number}"
                    # Formulas remain literal expressions; they are never evaluated.
                    text = ' | '.join(f'{get_column_letter(index)}{row_number}={value}' for index, value in nonempty)
                    if not first_row:
                        first_row, first_location = text[:600], location
                    else:
                        text = f'参考首行（不自动判定为表头）：{first_row}\n当前行：{text}'
                        location += f'；参考{first_location}'
                    yield TextPart(text, location)
    finally:
        workbook.close()


def _pdf_reader_class():
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('当前运行环境缺少 pypdf。请关闭软件，通过 V1.07/start-v1.07.cmd 重新启动；'
                           '仍有提示时运行 V1.07/安装OCR.ps1 修复依赖。') from exc
    return PdfReader


def _pdf(path, cancel):
    PdfReader = _pdf_reader_class()
    with path.open("rb") as stream:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            raise ValueError("PDF 已加密，请解除密码保护后导入。")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError("PDF 超过 2000 页限制，请拆分后导入。")
        for page_number, page in enumerate(reader.pages, 1):
            check_cancel(cancel)
            yield TextPart(page.extract_text() or "", f"第{page_number}页")


def _docling_in_process(path, cancel):
    """Use the installed local Chinese OCR models without first-import downloads."""
    from .ocr_runtime import create_converter
    check_cancel(cancel)
    converter = create_converter()
    result = converter.convert(path, max_num_pages=MAX_PDF_PAGES, max_file_size=MAX_FILE_BYTES)
    check_cancel(cancel)
    status = str(getattr(result.status, "value", result.status))
    if status != "success":
        raise ValueError("OCR 未完整成功，请检查文件或拆分后重试。")
    document = result.document
    for item, _ in document.iterate_items():
        check_cancel(cancel)
        text = getattr(item, "text", "")
        if not text and hasattr(item, "export_to_markdown"):
            text = item.export_to_markdown(doc=document)
        if text:
            pages = sorted({prov.page_no for prov in getattr(item, "prov", []) if getattr(prov, "page_no", None) is not None})
            location = "、".join(f"第{page}页" for page in pages) if pages else "OCR 内容（无页码）"
            yield TextPart(text, location + " · OCR")


def _docling(path, cancel):
    """Own the OCR process so a canceled desktop job cannot leave conversion running."""
    check_cancel(cancel)
    with tempfile.TemporaryDirectory(prefix='monitoring-ocr-') as temporary:
        output = Path(temporary) / 'result.json'
        project_dir = Path(__file__).resolve().parents[2]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        process = subprocess.Popen(
            [sys.executable, '-m', 'monitoring_daily.analysis.ocr_worker', str(path.resolve()), str(output)],
            cwd=project_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        deadline = time.monotonic() + OCR_TIMEOUT_SECONDS
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise RuntimeError('OCR 解析超时，请将扫描件拆分后重试。')
                time.sleep(.05)
            check_cancel(cancel)
            if not output.exists() or output.stat().st_size > 16_000_000:
                raise RuntimeError('OCR 进程未返回有效结果，请检查可选 OCR 依赖和文件。')
            payload = json.loads(output.read_text(encoding='utf-8'))
            if payload.get('error'):
                raise RuntimeError(payload['error'])
            if process.returncode != 0:
                raise RuntimeError('OCR 进程处理失败，请检查文档。')
            for part in payload.get('parts', []):
                check_cancel(cancel)
                yield TextPart(part['text'], part['location'])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def parse_document(path: Path, *, parser="auto", cancel=None) -> list[TextPart]:
    """Return bounded source chunks, preserving actual document locations."""
    path = Path(path)
    check_cancel(cancel)
    validate_file(path)
    if parser not in {"auto", "basic", "docling", "ocr"}:
        raise ValueError("未知解析器，请选择自动解析或 Docling OCR。")
    suffix = path.suffix.lower()
    if parser in {"docling", "ocr"} and suffix not in IMAGE_EXTENSIONS | {".pdf"}:
        raise ValueError("Docling OCR 仅用于 PDF 和图片，请为此文件选择自动解析。")
    if suffix in IMAGE_EXTENSIONS and parser not in {"docling", "ocr"}:
        raise ValueError("图片需要 Docling OCR，请安装可选 OCR 依赖并选择 Docling OCR 解析。")
    if parser in {"docling", "ocr"} and suffix == ".pdf":
        # Also reject protected PDFs on the optional path before starting OCR.
        PdfReader = _pdf_reader_class()
        with path.open("rb") as stream:
            if PdfReader(stream).is_encrypted:
                raise ValueError("PDF 已加密，请解除密码保护后导入。")
    reader = _docling if parser in {"docling", "ocr"} else {".txt": _plain_text, ".md": _plain_text, ".markdown": _plain_text, ".docx": _docx, ".xlsx": _xlsx, ".pdf": _pdf}[suffix]
    parts, total = [], 0
    try:
        for part in reader(path, cancel):
            check_cancel(cancel)
            text = part.text.replace("\x00", "").strip()
            if not text or not re.search(r"\w", text):
                continue
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise ValueError("文档文本超过 200 万字符，请拆分后导入。")
            start, fragment = 0, 1
            while start < len(text):
                end = min(start + 1400, len(text))
                location = part.location if len(text) <= 1400 else f"{part.location} · 片段{fragment}"
                parts.append(TextPart(text[start:end], location))
                if len(parts) > MAX_CHUNKS:
                    raise ValueError("文档切片过多，请拆分后导入。")
                if end == len(text):
                    break
                start, fragment = end - 120, fragment + 1
    except (InterruptedError, ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise ValueError(f"文档解析失败，请检查文件是否损坏、加密或格式不符（{type(exc).__name__}）。") from exc
    if not parts:
        if suffix == ".pdf" and parser not in {"docling", "ocr"}:
            raise ValueError("PDF 未提取到文字，可能是扫描件；请安装可选 Docling OCR 后重试。")
        raise ValueError("文档没有可检索文本，未导入任何内容。")
    return parts
