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

# ---------------------------------------------------------------- 来源分级（差距收敛第 3 项）

# 官方/监管/公司披露（L0）
_OFFICIAL_DOMAINS = {
    "sec.gov", "tsmc.com", "nvidia.com", "intc.com", "asml.com", "intel.com",
    "samsung.com", "skhynix.com", "micron.com", "investor.tsmc.com", "pr.tsmc.com",
    "nasa.gov", "trendforce.com", "macrotrends.net", "companiesmarketcap.com",
    "semiconductors.org", "semi.org", "w3.org", "github.com",
}
# 学术/文献（L1）
_ACADEMIC_DOMAINS = {
    "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "semanticscholar.org", "springer.com",
    "ieee.org", "acm.org", "nature.com", "science.org", "doi.org", "ssrn.com",
    "osf.io", "researchgate.net",
}
# 主流媒体/行业媒体（L2）
_MEDIA_DOMAINS = {
    "ithome.com", "sina.com.cn", "sina.cn", "21jingji.com", "wallstreetcn.com",
    "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "ft.com", "nytimes.com",
    "eet-china.com", "36kr.com", "jiemian.com", "yicai.com", "cls.cn", "sohu.com",
    "qq.com", "qq.com.cn", "163.com", "eastmoney.com", "investing.com", "wccftech.com",
    "techpowerup.com", "semiwiki.com", "tomshardware.com", "anandtech.com",
    "yahoofinance.com", "finance.yahoo.com", "moomoo.com", "tradingkey.com",
}


def source_level(url: str) -> int:
    """来源可信度分级：0=官方披露 1=学术文献 2=主流媒体 3=聚合/未知。

    规则：取注册域（最后两级），白名单匹配；未命中视为聚合/未知。
    """
    host = (urlparse(url).netloc or "").lower()
    if not host:
        return 3
    # 去掉 www 前缀
    if host.startswith("www."):
        host = host[4:]
    if host in _OFFICIAL_DOMAINS:
        return 0
    if host in _ACADEMIC_DOMAINS:
        return 1
    if host in _MEDIA_DOMAINS:
        return 2
    # 尾缀匹配（如 xxx.sec.gov 子域、sina 子域）
    for d in _OFFICIAL_DOMAINS:
        if host.endswith("." + d):
            return 0
    for d in _ACADEMIC_DOMAINS:
        if host.endswith("." + d):
            return 1
    for d in _MEDIA_DOMAINS:
        if host.endswith("." + d):
            return 2
    return 3


_LEVEL_LABELS = {0: "官方", 1: "学术", 2: "媒体", 3: "聚合"}


def source_level_label(url: str) -> str:
    return _LEVEL_LABELS.get(source_level(url), "聚合")


def report_source_levels(md: str) -> dict:
    """报告引用的来源等级分布：{counts: {0: n, ...}, official_ratio: 官方+学术占比}。"""
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    total = 0
    for u in report_urls(md or ""):
        counts[source_level(u)] += 1
        total += 1
    official = counts[0] + counts[1]
    return {
        "counts": counts,
        "total": total,
        "official_ratio": round(official / total, 3) if total else 1.0,
    }


# ---------------------------------------------------------------- claim→source→span（差距收敛第 5 项）

# 有意义的数字：带单位/百分比的金额、增速、占比（排除年份/编号等 4 位纯数字）
_MEANINGFUL_NUMBER_RE = re.compile(
    r"(?<!\d)\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:%|％|亿|万|千|百万|美元|欧元|新台币|"
    r"亿元|亿美元|亿元人民币|亿新台币|片|座|倍)"
)
# 句号/换行切句
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；\n])")


def extract_numeric_claims(md: str) -> list[dict]:
    """从报告提取**带单位数字的论断**（claim→source 的 claim 侧）。

    每条：{"claim": 含数字的句子, "numbers": 句中的有意义数字列表, "section": 所在节标题}。
    过滤：纯年份/编号（4 位无单位数字）不计入——只盯"金额/增速/占比"类论断。
    """
    claims: list[dict] = []
    section = ""
    for raw in _SENT_SPLIT_RE.split(md or ""):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip()[:30]
            continue
        nums = _MEANINGFUL_NUMBER_RE.findall(line)
        if not nums:
            continue
        # 去重且只保留"金额/百分比/倍"类（过滤单位后）
        meaningful = [n for n in nums if n.strip()]
        if meaningful:
            claims.append(
                {
                    "claim": line[:160],
                    "numbers": meaningful,
                    "section": section,
                }
            )
    return claims


def build_evidence_index(tool_outputs: list[str]) -> dict[str, list[dict]]:
    """证据池索引（source→span 侧）：数字 -> [证据条目]。

    每个证据条目：{"url": 出处, "span": URL 前 80 字符的原文片段}。
    对未截断的工具返回，按 URL 切证据块，块内出现的有意义数字建立倒排。
    """
    index: dict[str, list[dict]] = {}
    for text in tool_outputs or []:
        for m in _URL_RE.finditer(text or ""):
            url = m.group(0).rstrip(".,;")
            start = max(0, m.start() - 80)
            span = re.sub(r"\s+", " ", text[start : m.start()]).strip()[-80:]
            nums = _MEANINGFUL_NUMBER_RE.findall(span)
            for n in set(nums):
                index.setdefault(n, []).append({"url": url, "span": span})
    return index


def build_url_span_index(tool_outputs: list[str]) -> dict[str, list[str]]:
    """按 URL 索引证据 span：url -> [span 文本]（claim 精确绑定用）。"""
    index: dict[str, list[str]] = {}
    for text in tool_outputs or []:
        for m in _URL_RE.finditer(text or ""):
            url = m.group(0).rstrip(".,;")
            start = max(0, m.start() - 80)
            span = re.sub(r"\s+", " ", text[start : m.start()]).strip()[-80:]
            if span:
                index.setdefault(url, []).append(span)
    return index


def _norm_number(n: str) -> str:
    """数字标准化：去逗号与空格（"4,675.8 亿" → "4675.8亿"），用于 span 比对。"""
    return re.sub(r"[\s,]", "", n)


def _bind_numbers_to_urls(report_md: str) -> list[dict]:
    """报告全文：每个有意义数字 → 紧邻 URL（数字后 120 字符内的第一个链接）。

    返回 [{number, url|None, section}]——这是 claim 精确绑定的基础：
    "数字 → 紧邻 URL"（复审 §6.2：从"URL ∈ 工具池"升级为"数字绑定其紧邻引用 URL"）。
    """
    out: list[dict] = []
    section = ""
    for line in (report_md or "").split("\n"):
        if line.strip().startswith("#"):
            section = line.strip().lstrip("#").strip()[:30]
        for m in _MEANINGFUL_NUMBER_RE.finditer(line):
            window = line[m.end() : m.end() + 120]
            um = re.search(r"\[[^\]]*\]\((https?://[^\)\s]+)\)", window) or re.search(
                r"https?://[^\s\)\]\}，。；、]+", window
            )
            url = um.group(1).rstrip(".,;") if um else None
            out.append({"number": m.group(0).strip(), "url": url, "section": section})
    return out


def claim_support_rate(report_md: str, tool_outputs: list[str]) -> dict:
    """数字级 claim 支持率（复审 §6.1/6.2 整改：精确绑定，替代旧的 any-match）。

    判定链（all-match，每个数字独立判定）：
    1. 数字必须有**紧邻 URL**（数字后 120 字符内，来自报告自身的 Markdown 链接）；
    2. 该 URL 必须在检索证据池中出现（grounding）；
    3. **该 URL 对应的证据 span 必须包含该数字**（标准化后比对）——
       防"报告中 100 亿 链接到 B、999 亿 链接到 A，证据池 A/B 反向含数字"的交叉错配。

    返回 {"total": 数字数, "supported": 支持数, "unsupported": 抽样,
    "rate": 支持率, "coverage": 数字覆盖率（total>0 时为 1）}。
    """
    numbers = _bind_numbers_to_urls(report_md or "")
    total = len(numbers)
    if not total:
        return {"total": 0, "supported": 0, "unsupported": [], "rate": 1.0, "coverage": 0.0}
    url_spans = build_url_span_index(tool_outputs)
    supported = 0
    unsupported: list[str] = []
    for item in numbers:
        num = item["number"]
        url = item["url"]
        norm = _norm_number(num)
        # 1) 无紧邻 URL → 不支持；2) URL 不在证据池 → 不支持
        if url and url in url_spans:
            # 3) 该 URL 的任一 span 含该数字（标准化）→ 支持
            if any(norm in _norm_number(span) for span in url_spans[url]):
                supported += 1
                continue
            unsupported.append(f"{num}→{url}（span 无此数）")
        elif url is None:
            unsupported.append(f"{num}（无紧邻 URL）")
        else:
            unsupported.append(f"{num}→{url}（URL 不在证据池）")
    return {
        "total": total,
        "supported": supported,
        "unsupported": unsupported[:10],
        "rate": round(supported / total, 3) if total else 1.0,
        "coverage": 1.0,
    }


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
