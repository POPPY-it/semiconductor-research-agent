"""文章正文采集：对新闻 URL 抓取正文（stdlib html.parser，零新依赖）。

用途：M2 需要"正文语料"做 RAG；Google News 链接会自动跳转到原站。
反爬/JS 渲染站会失败，采集器对此保持健壮（跳过失败项）。
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    )
}

SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "header", "form", "iframe", "noscript"}


class _ParagraphExtractor(HTMLParser):
    """收集块级文本：兼容 <p> 页面与 Workiva 财报的 <div> 布局（嵌套深度跟踪）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._capture = False
        self._buf: list[str] = []
        self._skip_depth = 0
        self._div_depth = 0

    def _flush(self, min_len: int) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if len(text) >= min_len:
            self.paragraphs.append(text)
        self._capture = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "div":
            if not self._capture:
                self._capture = True
                self._buf = []
                self._div_depth = 1
            else:
                self._div_depth += 1
            return
        if tag in ("p", "h1", "h2", "h3", "td", "li") and not self._capture:
            self._capture = True
            self._buf = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if not self._capture or self._skip_depth:
            return
        if tag == "div" and self._div_depth:
            self._div_depth -= 1
            if self._div_depth == 0:
                self._flush(min_len=30)
            return
        if tag in ("p", "h1", "h2", "h3", "td", "li") and self._div_depth == 0:
            self._flush(min_len=20)

    def handle_data(self, data):
        if self._capture and not self._skip_depth:
            self._buf.append(data)


def fetch_content_advanced(
    url: str,
    timeout: int = 20,
    max_chars: int = 8000,
    headers: dict | None = None,
) -> str:
    """专业正文提取（trafilatura）：对新闻/博客类网页效果远好于段落启发式；
    失败时回退到 fetch_content 的 html.parser 实现。"""
    try:
        import trafilatura

        resp = requests.get(
            url, headers=headers or UA, timeout=timeout, allow_redirects=True
        )
        resp.raise_for_status()
        text = trafilatura.extract(
            resp.content, include_comments=False, include_tables=True, favor_recall=True
        )
        if text and len(text.strip()) >= 80:
            return re.sub(r"\n{3,}", "\n\n", text).strip()[:max_chars]
    except Exception:  # noqa: BLE001
        pass
    return fetch_content(url, timeout=timeout, max_chars=max_chars, headers=headers)


def fetch_content(
    url: str,
    timeout: int = 15,
    max_paragraphs: int = 60,
    max_chars: int = 6000,
    headers: dict | None = None,
) -> str:
    """抓取 URL 并提取正文文本；失败返回空串。"""
    try:
        resp = requests.get(
            url, headers=headers or UA, timeout=timeout, allow_redirects=True
        )
        resp.raise_for_status()
    except Exception:
        return ""

    # 仅处理 HTML
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and not resp.text.lstrip().lower().startswith("<"):
        return ""

    # EDGAR 包装格式：真实 HTML 转义后嵌在 <TEXT> 段内，需先解出再解析
    raw = resp.text
    if "<DOCUMENT>" in raw and "<TEXT>" in raw:
        m = re.search(r"<TEXT>(.*?)</TEXT>", raw, flags=re.S)
        if m:
            raw = html.unescape(m.group(1))

    try:
        parser = _ParagraphExtractor()
        parser.feed(raw)
    except Exception:
        return ""

    text = "\n".join(parser.paragraphs[:max_paragraphs])
    return html.unescape(text)[:max_chars]
