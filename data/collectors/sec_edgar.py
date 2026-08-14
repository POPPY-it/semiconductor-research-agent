"""SEC EDGAR 官方 API 采集器（数据源 1/5：上市公司财报提交）。

SEC 要求请求携带自定义 User-Agent（否则 403），官方限速约 10 req/s。
"""
from __future__ import annotations

import time

import requests

from .base import BaseCollector

UA = "SemiconductorResearchAgent/0.1 (campus recruiting project; contact: research@example.com)"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# 美国本土公司：10-K/10-Q/8-K；外国发行人（如台积电/ASML）：20-F/6-K
FORM_TYPES = ("10-K", "10-Q", "8-K", "20-F", "6-K")

COMPANIES = {
    "NVIDIA": "0001045810",
    "TSMC": "0001046179",
    "Intel": "0000050863",
    "ASML": "0000937966",
}


class SECEdgarCollector(BaseCollector):
    name = "sec_edgar"

    def __init__(self, companies: dict[str, str] | None = None):
        self.companies = companies or COMPANIES

    def fetch(self) -> list[dict]:
        items: list[dict] = []
        for company, cik in self.companies.items():
            resp = requests.get(
                SUBMISSIONS_URL.format(cik=int(cik)),
                headers={"User-Agent": UA},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items.extend(self._extract(data))
            time.sleep(0.5)  # 礼貌限速
        return items

    @staticmethod
    def _extract(data: dict, limit: int = 8) -> list[dict]:
        recent = data["filings"]["recent"]
        rows: list[dict] = []
        for i in range(len(recent["form"])):
            form = recent["form"][i]
            if form not in FORM_TYPES:
                continue
            accession = recent["accessionNumber"][i]
            rows.append(
                {
                    "source": "SEC_EDGAR",
                    "title": f"{data['name']} {form} 财报披露",
                    "url": (
                        f"https://www.sec.gov/Archives/edgar/data/{int(data['cik'])}/"
                        f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}"
                    ),
                    "published_at": recent["filingDate"][i],
                    "extra": {
                        "company": data["name"],
                        "cik": data["cik"],
                        "form": form,
                        "report_date": recent["reportDate"][i],
                        "accession": accession,
                    },
                }
            )
            if len(rows) >= limit:
                break
        return rows
