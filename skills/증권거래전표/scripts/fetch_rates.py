"""한국은행 ECOS 일별 매매기준율(731Y001)을 받아 환율표 CSV(일자,통화,환율,출처)로 쓴다.

키: 환경변수 ECOS_API_KEY. 없으면 공개 sample 키로 10건씩 나눠 받는다(느리다).
731Y001 의 작성기관은 서울외국환중개다. 회사 내부 장부 작성용으로만 쓰고 재배포하지 않는다.
기말 환율은 decisions 대로 ECOS 731Y004 말일자료 또는 회계사 입력값을 쓴다(SKILL.md).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request

ITEMS = {"USD": "0000001", "JPY": "0000002", "EUR": "0000003", "CNY": "0000053", "HKD": "0000015", "GBP": "0000012", "VND": "0000063"}
UNIT = {"JPY": 100, "VND": 100}   # ECOS 는 100엔·100동 기준


def fetch(ccy, start: dt.date, end: dt.date):
    key = os.environ.get("ECOS_API_KEY") or "sample"
    item = ITEMS[ccy]
    out = []
    step = 10 if key == "sample" else 1000
    cur = start
    while cur <= end:
        # sample 키는 한 번에 10건만 준다. 14일 창으로 자르면 영업일 10개 안쪽이다.
        span = dt.timedelta(days=13) if key == "sample" else (end - cur)
        stop = min(end, cur + span)
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/{step}/731Y001/D/"
               f"{cur:%Y%m%d}/{stop:%Y%m%d}/{item}")
        with urllib.request.urlopen(url, timeout=30) as r:
            js = json.loads(r.read().decode("utf-8"))
        rows = js.get("StatisticSearch", {}).get("row", [])
        if key == "sample" and js.get("StatisticSearch", {}).get("list_total_count", 0) > 10:
            raise SystemExit("sample 키 창이 10건을 넘었다. 창을 줄인다")
        for x in rows:
            d = dt.datetime.strptime(x["TIME"], "%Y%m%d").date()
            v = float(x["DATA_VALUE"]) / UNIT.get(ccy, 1)
            out.append((d, ccy, v, "ECOS 731Y001 매매기준율"))
        cur = stop + dt.timedelta(days=1)
        time.sleep(0.2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--ccy", default="USD")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    s = dt.date.fromisoformat(a.start) - dt.timedelta(days=10)   # 첫 거래일 직전 영업일까지
    e = dt.date.fromisoformat(a.end)
    rows = []
    for c in a.ccy.split(","):
        rows += fetch(c.strip().upper(), s, e)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["일자", "통화", "환율", "출처"])
        for d, c, v, src in rows:
            w.writerow([d.isoformat(), c, v, src])
    print(f"{len(rows)}건 → {a.out}")


if __name__ == "__main__":
    sys.exit(main())
