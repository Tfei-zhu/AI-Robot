# -*- coding: utf-8 -*-
"""文档解析：PDF / Word / Markdown / 纯文本 -> 纯文本。
延迟导入第三方库：未安装 pypdf / python-docx 时仅对应格式不可用，其余功能不受影响。
"""
from pathlib import Path


def parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in (".md", ".txt", ".markdown"):
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    raise ValueError(f"暂不支持的文件类型: {suffix}（支持 pdf/docx/md/txt）")


def _parse_pdf(path: Path) -> str:
    from pypdf import PdfReader  # 延迟导入
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(p.strip() for p in pages if p.strip())


def _parse_docx(path: Path) -> str:
    from docx import Document  # 延迟导入
    doc = Document(str(path))
    return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
