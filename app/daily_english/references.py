from __future__ import annotations

import re
from pathlib import Path


def read_reference_text(path: str | Path) -> str:
    reference_path = Path(path)
    if not reference_path.is_file():
        raise ValueError(f"参考文稿不存在：{reference_path}")
    suffix = reference_path.suffix.lower()
    if suffix == ".txt":
        text = _read_text(reference_path)
    elif suffix == ".docx":
        from docx import Document

        document = Document(reference_path)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(reference_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise ValueError("参考文稿仅支持 TXT、DOCX 或可提取文字的 PDF")
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        raise ValueError("参考文稿中没有可提取的文字")
    return normalized


def whisper_reference_prompt(text: str, max_characters: int = 1800) -> str:
    """Keep the prompt useful while staying well below Whisper's prompt budget."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_characters:
        return text
    shortened = text[:max_characters]
    boundary = max(shortened.rfind("."), shortened.rfind("!"), shortened.rfind("?"), shortened.rfind("。"))
    return shortened[:boundary + 1] if boundary >= max_characters // 2 else shortened


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    raise ValueError(f"无法识别参考文稿编码：{path}")
