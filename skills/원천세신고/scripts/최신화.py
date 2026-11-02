# -*- coding: utf-8 -*-
"""근거목록(references/근거목록.json)의 값이 지금 법령 판과 맞는지 본다. 값은 바꾸지 않는다.

    python scripts/최신화.py 목록                       조회할 조문 · 별표 목록(JSON)
    python scripts/최신화.py 비교 --조회 <조회.json> [--보고 <보고.md>]
    python scripts/최신화.py 반영 --조회 <조회.json> --근거 "소득세법 제129조" [--근거 ...]

차례
  1. 「목록」 이 조회할 것을 낸다. Claude 가 TaxDoctor(get_article · get_annex · get_reference_article · list_upcoming)와
     korean-law(TaxDoctor 에 없는 법령)로 하나씩 읽어 조회 파일에 적는다. 꼴은 references/최신화.md.
  2. 「비교」 가 근거마다 같음 · 판만 바뀜 · 조문 바뀜 · 시행예정 · 조회 없음 을 가르고, 그 근거를 쓰는 값을 고칠 후보로 보인다.
  3. 사람이 확인한 뒤에만 고친다. 값이 바뀌면 엔진 코드와 근거목록 「값」 을 함께 고치고 시험을 돌린다
     (tests/test_근거목록.py 가 둘이 같은지 본다). 값이 그대로면 「반영」 으로 판 기록만 새로 적는다.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

근거목록 = Path(__file__).resolve().parent.parent / "references" / "근거목록.json"
비교키 = ("스냅샷", "시행일", "최근개정")


def 읽기(경로=근거목록):
    return json.loads(Path(경로).read_text(encoding="utf-8"))


def 쓰기(목록, 경로=근거목록):
    Path(경로).write_text(json.dumps(목록, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def 조회목록(목록):
    """조회할 것. 근거 하나가 조문 · 별표 하나다. 시행예정은 법령마다 list_upcoming 한 번."""
    줄, 사람 = [], []
    for 키, g in 목록["근거"].items():
        if g["출처"] == "사람 확인":
            사람.append({"근거": 키, "메모": g.get("메모", "")})
            continue
        줄.append({"근거": 키, "출처": g["출처"], "도구": g["도구"], "법령": g["법령"], "조문": g["조문"],
                   "기록": {k: g.get(k, "") for k in 비교키}})
    법령들 = sorted({g["법령"] for g in 목록["근거"].values() if g["출처"] == "TaxDoctor" and g["도구"] != "get_reference_article"})
    return {"조회": 줄, "시행예정": [{"도구": "list_upcoming", "법령": 이름} for 이름 in 법령들], "사람확인": 사람}


def _값들(목록, 키):
    return [v for v in 목록["값"] if 키 in v["근거"]]


def 비교(목록, 조회):
    """근거마다 상태를 정한다. 조회 파일 꼴: {"조회": {근거키: {스냅샷, 시행일, 최근개정, 시행예정: [...]}}}."""
    결과 = []
    본 = 조회.get("조회", {})
    for 키, g in 목록["근거"].items():
        q = 본.get(키)
        if g["출처"] == "사람 확인":
            상태 = "사람 확인"
        elif q is None:
            상태 = "조회 없음"
        elif q.get("열지못함"):
            상태 = "열지 못함"
        elif q.get("최근개정", "") != g.get("최근개정", "") or (g["도구"] == "get_annex" and q.get("스냅샷") != g.get("스냅샷")):
            상태 = "조문 바뀜"
        elif any(q.get(k, "") != g.get(k, "") for k in ("스냅샷", "시행일")):
            상태 = "판만 바뀜"
        else:
            상태 = "같음"
        예정 = (q or {}).get("시행예정") or []
        결과.append({"근거": 키, "상태": 상태, "시행예정": 예정, "기록": {k: g.get(k, "") for k in 비교키},
                     "조회": {k: (q or {}).get(k, "") for k in 비교키},
                     "값": [{"id": v["id"], "이름": v["이름"], "값": v["값"], "구절": v.get("구절", "")} for v in _값들(목록, 키)]})
    return 결과


def 보고글(결과, 목록, 조회):
    오늘 = 조회.get("조회일") or datetime.date.today().isoformat()
    센 = {}
    for r in 결과:
        센[r["상태"]] = 센.get(r["상태"], 0) + 1
    예정수 = sum(1 for r in 결과 if r["시행예정"])
    줄 = [f"# 근거목록 최신화 보고 ({오늘})", "",
          f"근거 {len(결과)}건: " + " · ".join(f"{k} {v}" for k, v in sorted(센.items())) + f" · 시행예정 개정이 걸린 근거 {예정수}",
          f"근거목록 기준일 {목록.get('기준일', '')}. 값은 바꾸지 않았다.", ""]
    고칠 = [r for r in 결과 if r["상태"] in ("조문 바뀜", "열지 못함", "조회 없음")]
    판만 = [r for r in 결과 if r["상태"] == "판만 바뀜"]
    예정 = [r for r in 결과 if r["시행예정"]]
    줄.append("## 고칠 후보(값 확인 필요)")
    줄 += [f"- {r['근거']} · {r['상태']} · 기록 {r['기록']['최근개정'] or r['기록']['스냅샷'][:40]} → 조회 "
           f"{r['조회']['최근개정'] or r['조회']['스냅샷'][:40]} · 값: " + ", ".join(f"{v['이름']} {v['값']}" for v in r["값"])
           for r in 고칠] or ["- 없음"]
    줄 += ["", "## 판만 바뀜(조문 개정일 그대로, 값 영향 없음으로 본다)"]
    줄 += [f"- {r['근거']} · {r['기록']['시행일']} → {r['조회']['시행일']}" for r in 판만] or ["- 없음"]
    줄 += ["", "## 시행예정 개정"]
    for r in 예정:
        for e in r["시행예정"]:
            줄.append(f"- {r['근거']} · {e.get('시행일', '')} 시행 · {e.get('바뀌는점', '')} · 값: "
                      + (", ".join(f"{v['이름']} {v['값']}" for v in r["값"]) or "없음"))
    if not 예정:
        줄.append("- 없음")
    줄 += ["", "## 사람 확인(TaxDoctor · korean-law 로 볼 수 없는 고시 · 규격서)"]
    줄 += [f"- {r['근거']} · {목록['근거'][r['근거']].get('메모', '')} · 값: " + (", ".join(f"{v['이름']} {v['값']}" for v in r["값"]) or "없음")
           for r in 결과 if r["상태"] == "사람 확인"] or ["- 없음"]
    줄 += ["", "## 근거목록에 적어 둔 확인할 사항"]
    줄 += [f"- {v['이름']}({v['id']}): {v['확인']}" for v in 목록["값"] if v.get("확인")] or ["- 없음"]
    줄 += ["", "## 다음", "- 고칠 후보는 근거 원문을 보이고 확인받은 뒤 엔진 코드와 근거목록 「값」 을 함께 고친다. 그다음 `python -m pytest -q tests`.",
           "- 판만 바뀐 근거는 확인받은 뒤 `python scripts/최신화.py 반영 --조회 <조회.json> --근거 \"<근거>\"` 로 판 기록만 고친다."]
    return "\n".join(줄) + "\n"


def 반영(목록, 조회, 키들, 오늘=None):
    오늘 = 오늘 or 조회.get("조회일") or datetime.date.today().isoformat()
    for 키 in 키들:
        if 키 not in 목록["근거"]:
            raise SystemExit(f"근거목록에 없는 근거입니다: {키}")
        q = 조회["조회"].get(키)
        if not q or q.get("열지못함"):
            raise SystemExit(f"조회 파일에 {키} 결과가 없습니다")
        for k in 비교키:
            if q.get(k):
                목록["근거"][키][k] = q[k]
        목록["근거"][키]["확인일"] = 오늘
    return 목록


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="근거목록 최신화")
    sub = ap.add_subparsers(dest="일", required=True)
    sub.add_parser("목록")
    b = sub.add_parser("비교"); b.add_argument("--조회", required=True); b.add_argument("--보고")
    r = sub.add_parser("반영"); r.add_argument("--조회", required=True); r.add_argument("--근거", action="append", required=True)
    a = ap.parse_args(argv)
    목록 = 읽기()
    if a.일 == "목록":
        print(json.dumps(조회목록(목록), ensure_ascii=False, indent=1))
        return 0
    조회 = json.loads(Path(a.조회).read_text(encoding="utf-8"))
    if a.일 == "비교":
        결과 = 비교(목록, 조회)
        글 = 보고글(결과, 목록, 조회)
        if a.보고:
            Path(a.보고).write_text(글, encoding="utf-8")
        print(글)
        return 0
    쓰기(반영(목록, 조회, a.근거))
    print("판 기록을 고쳤습니다: " + ", ".join(a.근거) + ". 이어서 python -m pytest -q tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
