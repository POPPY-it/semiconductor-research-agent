"""证据包（Evidence Pack）——差距收敛第 1 项（对标千问/Deep Research 样本）。

核心承诺：**输出引用只能指向实际检索记录，不允许模型自由生成 URL**（GPT 审查 §4.11 同款建议）。

落地为两层：
1. `extract_urls_with_context`：从工具返回文本提取 (url, 上下文片段) 条目——证据的
   source_url + source_span；
2. `check_url_grounding`：把报告中的所有 URL 与该任务轨迹里全部工具返回的 URL 比对，
   计算"URL 落地率"（grounded 比例）——模型编造的 URL 会被确定性检出。

说明（诚实口径）：claim 级语义抽取（LLM 提炼"论断→证据"）暂未做，先做
URL 级确定性 grounding——这是"每个数字都能查"的最小可验证版。
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s\)\]\}>\"'，。；、]+")


def extract_urls_with_context(text: str, window: int = 80) -> list[dict]:
    """从一段文本提取 (url, 上下文片段) 条目。

    每条：{"url": 规范化 URL, "snippet": URL 前 window 字符的上下文（source_span 近似）,
    "retrieved_at": ISO 时间}。
    """
    out: list[dict] = []
    now = datetime.now().isoformat(timespec="seconds")
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;")
        start = max(0, m.start() - window)
        snippet = re.sub(r"\s+", " ", text[start : m.start()]).strip()
        out.append({"url": url, "snippet": snippet[-window:], "retrieved_at": now})
    return out


def report_urls(md: str) -> list[str]:
    """报告中的 Markdown 链接 URL（排除本地 /charts 图片引用）。"""
    urls = []
    for m in re.finditer(r"\[[^\]]*\]\((https?://[^\)\s]+)\)", md or ""):
        u = m.group(1).rstrip(".,;")
        if u:
            urls.append(u)
    return urls


def _normalize(url: str) -> str:
    """去掉协议与结尾斜杠，用于宽松比对。"""
    u = urlparse(url)
    return (u.netloc + u.path).rstrip("/").lower()


def check_url_grounding(report_md: str, tool_outputs: list[str]) -> dict:
    """报告 URL 是否都能在工具返回中找到（宽松：前缀 60 字符包含即 grounded）。

    返回 {"total": 报告 URL 数, "grounded": 命中数, "ungrounded": 编造 URL 列表,
    "rate": 落地率}。工具输出被截断时（2500 字符）URL 可能被切断——用前缀包含避免误报。
    """
    pool: list[str] = []
    for t in tool_outputs or []:
        pool.extend(u.rstrip(".,;") for u in _URL_RE.findall(t or ""))
    pool_norm = {_normalize(u) for u in pool}

    grounded = 0
    ungrounded: list[str] = []
    for u in report_urls(report_md or ""):
        if _normalize(u) in pool_norm:
            grounded += 1
            continue
        # 前缀宽松：工具输出含该 URL 的前 60 字符（防截断误报）
        prefix = _normalize(u)[:60]
        if prefix and any(p.startswith(prefix) for p in pool_norm):
            grounded += 1
            continue
        ungrounded.append(u)
    total = len(report_urls(report_md or ""))
    return {
        "total": total,
        "grounded": grounded,
        "ungrounded": ungrounded[:10],
        "rate": round(grounded / total, 3) if total else 1.0,
    }
