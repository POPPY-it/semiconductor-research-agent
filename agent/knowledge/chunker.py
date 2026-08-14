"""文档切分：按句子边界切块，带重叠。长文档（财报全文）必须先分块再索引。"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;.])")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """按句子边界切分为约 chunk_size 字符的块，块间 overlap 字符重叠。"""
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if not cur:
            cur = s
        elif len(cur) + len(s) + 1 <= chunk_size:
            cur += s
        else:
            chunks.append(cur)
            cur = (cur[-overlap:] + s) if overlap else s
    if cur:
        chunks.append(cur)
    return chunks
