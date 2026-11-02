# -*- coding: utf-8 -*-
"""한 달치 급여대장을 만든다.

    python run.py <키트폴더> <귀속연월> -o <산출폴더> [--근태 근태.xlsx]

키트폴더에 hr_card.csv · pay_contract.csv · pay_item_rule.csv 가 있어야 한다.
"""
import argparse
import calendar
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import 급여대장 as G      # noqa: E402
import 워크북 as B        # noqa: E402
import simple_tax_table as T  # noqa: E402  (급여대장 이 경로를 열어 둔다)


def 말일(연월):
    y, m = int(연월[:4]), int(연월[5:7])
    return f"{연월}-{calendar.monthrange(y, m)[1]:02d}"


def 조견표(경로=None):
    import db
    conn = db.connect(경로 or ":memory:")
    d = T.DATA_DIR
    T.load_official(conn, os.path.join(d, "gani_2024-03-01.json"), eff_to="2026-02-28")
    T.load_official(conn, os.path.join(d, "gani_2026-03-01.json"))
    return conn


def 일할확인(카드, 연월, 기준일):
    """일할 계산은 넣지 않았다. 한 달치로 나간 것을 표시해 사람이 고치게 한다."""
    입, 퇴 = 카드["입사일"], 카드["퇴사일"]
    if 입[:7] == 연월 and 입 != f"{연월}-01":
        return [f"확인필요: {입} 월 중 입사. 일할 계산이 없어 한 달치로 나왔습니다. 금액을 고쳐 다시 돌리세요"]
    if 퇴 and 퇴[:7] == 연월 and 퇴 != 기준일:
        return [f"확인필요: {퇴} 월 중 퇴사. 일할 계산이 없어 한 달치로 나왔습니다. 금액을 고쳐 다시 돌리세요"]
    return []


def 근태읽기(경로, 연월):
    """근태기록에서 사번별 일급 목록을 뽑는다."""
    import openpyxl
    wb = openpyxl.load_workbook(경로, data_only=True)
    ws = wb["근태기록"] if "근태기록" in wb.sheetnames else wb.worksheets[0]
    머리 = [c.value for c in ws[1]]
    i일자, i사번, i일급 = 머리.index("일자"), 머리.index("사번"), 머리.index("일급")
    묶음 = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        일자 = row[i일자]
        s = 일자.strftime("%Y-%m") if hasattr(일자, "strftime") else str(일자)[:7]
        if s != 연월:
            continue
        묶음.setdefault(row[i사번], []).append(int(row[i일급] or 0))
    return 묶음


def run(키트, 연월, 산출, 근태=None, 회사=None, 확인사항=()):
    if not 회사:
        raise ValueError("회사 이름이 필요합니다(--회사)")
    키트, 산출 = Path(키트), Path(산출)
    산출.mkdir(parents=True, exist_ok=True)
    기준일 = 말일(연월)

    규칙 = G.load_rules(키트 / "pay_item_rule.csv")
    카드들 = G.load_cards(키트 / "hr_card.csv")
    계약 = G.load_contracts(키트 / "pay_contract.csv", 기준일)
    일급표 = 근태읽기(근태, 연월) if 근태 else {}
    conn = 조견표()

    행들, 뺀사람 = [], []
    for 사번, 카드 in 카드들.items():
        if 카드["입사일"] > 기준일:
            뺀사람.append((카드["성명"], "입사 전")); continue
        if 카드["퇴사일"] and 카드["퇴사일"] < f"{연월}-01":
            뺀사람.append((카드["성명"], "퇴사")); continue
        항목 = 계약.get(사번, {})
        구분 = 카드["소득구분"]
        if 구분 == "일용":
            일급들 = 일급표.get(사번)
            if not 일급들:
                뺀사람.append((카드["성명"], "그 달 근태 없음")); continue
            행들.append(G.계산_일용(카드, 일급들, 기준일))
        elif 구분 == "사업":
            행들.append(G.계산_사업(카드, 항목.get("SERVICE", 0), 기준일))
        else:
            지급 = {k: v for k, v in 항목.items() if k not in ("HOURLY", "SERVICE")}
            행 = G.계산_상용(conn, 카드, 지급, 규칙, 기준일)
            행.근거 += 일할확인(카드, 연월, 기준일)
            행들.append(행)

    순서 = {"상용": 0, "일용": 1, "사업": 2}
    행들.sort(key=lambda x: (순서.get(x.소득구분, 9), x.사번))

    확인 = list(확인사항)
    for x in 행들:
        for g in x.근거:
            if g.startswith("확인필요"):
                확인.append((x.성명, g, ""))

    xlsx = B.build(산출 / f"급여대장_{연월}.xlsx", 회사, 연월, 행들,
                   [카드들[x.사번] for x in 행들], 확인)

    js = 산출 / f"급여대장_{연월}.json"
    js.write_text(json.dumps(
        [{"사번": x.사번, "성명": x.성명, "소득구분": x.소득구분, "소득코드": x.소득코드, "지급": x.지급,
          "총지급액": x.총지급액, "표준": x.표준, "비과세": x.비과세,
          "국민연금": x.국민연금, "건강보험": x.건강보험, "장기요양보험": x.장기요양보험,
          "고용보험": x.고용보험, "소득세": x.소득세, "지방소득세": x.지방소득세,
          "공제합계": x.공제합계, "실지급액": x.실지급액, "근거": x.근거}
         for x in 행들], ensure_ascii=False, indent=2), encoding="utf-8")
    return {"엑셀": str(xlsx), "json": str(js), "행들": 행들, "뺀사람": 뺀사람}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("키트"); ap.add_argument("연월")
    ap.add_argument("-o", "--out", default="산출")
    ap.add_argument("--근태", default=None)
    ap.add_argument("--회사", required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    r = run(a.키트, a.연월, a.out, 근태=a.근태, 회사=a.회사)
    행 = r["행들"]
    print(f"{r['엑셀']}  {len(행)}명")
    print(f"{'사번':<7}{'성명':<8}{'구분':<6}{'총지급':>12}{'소득세과표':>12}"
          f"{'연금과표':>12}{'소득세':>10}{'실지급':>12}")
    for x in 행:
        print(f"{x.사번:<7}{x.성명:<8}{x.소득구분:<6}{x.총지급액:>12,}"
              f"{x.표준['소득세']:>12,}{x.표준['국민연금']:>12,}"
              f"{x.소득세:>10,}{x.실지급액:>12,}")
    print(f"{'':<21}{'합계':<6}{sum(x.총지급액 for x in 행):>12,}"
          f"{'':>24}{sum(x.소득세 for x in 행):>10,}"
          f"{sum(x.실지급액 for x in 행):>12,}")
    if r["뺀사람"]:
        print("뺀 사람:", ", ".join(f"{n}({w})" for n, w in r["뺀사람"]))


if __name__ == "__main__":
    main()
