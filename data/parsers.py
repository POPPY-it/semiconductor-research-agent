"""文档解析：上传文件 → 纯文本（PDF 用 pymupdf，HTML 用 trafilatura，txt/md 直读）。"""
from __future__ import annotations

from pathlib import Path


def parse_document(data: bytes, filename: str, max_chars: int = 20000) -> str:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            import fitz  # pymupdf

            doc = fitz.open(stream=data, filetype="pdf")
            try:
                text = "\n".join(page.get_text() for page in doc)
            finally:
                doc.close()
            return text[:max_chars]
        if ext in (".txt", ".md", ".csv", ".json"):
            return data.decode("utf-8", errors="replace")[:max_chars]
        # html/htm 及其他：trafilatura 正文提取
        import trafilatura

        text = trafilatura.extract(data, include_comments=False, include_tables=True)
        return (text or "")[:max_chars]
    except Exception:  # noqa: BLE001 —— 解析失败返回空串，由上层报错
        return ""
