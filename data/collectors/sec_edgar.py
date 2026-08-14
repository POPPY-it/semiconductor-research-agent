"""SEC EDGAR 官方 API 采集器原型（数据源 1/5：上市公司财报提交）。

SEC 要求请求携带自定义 User-Agent（否则 403），官方限速约 10 req/s。
本模块在 W3（M1 数据管道）将被重构成统一适配器接口。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

UA = "SemiconductorResearchAgent/0.1 (campus recruiting project; contact: research@example.com)"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# 美国本土公司：10-K/10-Q/8-K；外国发行人（如台积电/ASML）：20-F/6-K
FORM_TYPES = ("10-K", "10-Q", "8-K", "20-F", "6-K")

# 半导体代表公司（CIK 为 EDGAR 唯一标识）
COMPANIES = {
    "NVIDIA": "0001045810",
    "TSMC": "0001046179",
    "Intel": "0000050863",
    "ASML": "0000937966",
}

RAW_DIR = Path(__file__).resolve().parents[1] / "raw"


def fetch_submissions(cik: str) -> dict:
    resp = requests.get(
        SUBMISSIONS_URL.format(cik=int(cik)),
        headers={"User-Agent": UA},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def recent_periodic_filings(data: dict, limit: int = 8) -> list[dict]:
    """从 EDGAR submissions JSON 中提取近期定期披露（10-K/10-Q/8-K）。"""
    recent = data["filings"]["recent"]
    rows: list[dict] = []
    for i in range(len(recent["form"])):
        form = recent["form"][i]
        if form not in FORM_TYPES:
            continue
        accession = recent["accessionNumber"][i]
        rows.append(
            {
                "company": data["name"],
                "cik": data["cik"],
                "form": form,
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "accession": accession,
                "document_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{int(data['cik'])}/"
                    f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}"
                ),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    result = {"collected_at": time.strftime("%Y-%m-%d %H:%M:%S"), "filings": []}
    for name, cik in COMPANIES.items():
        data = fetch_submissions(cik)
        rows = recent_periodic_filings(data)
        result["filings"].extend(rows)
        print(f"[SEC EDGAR] {name}: {len(rows)} 条近期财报披露")
        time.sleep(0.5)  # 礼貌限速，避免触发 SEC 限流
    out_path = RAW_DIR / "sec_edgar_sample.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存 -> {out_path}")


if __name__ == "__main__":
    main()
