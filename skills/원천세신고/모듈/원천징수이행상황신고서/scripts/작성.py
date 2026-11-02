# -*- coding: utf-8 -*-
"""받은자료 폴더 → 원천징수집계 워크북 + 신고값 JSON.

손으로 메우던 자리를 전부 없앤다. 회사 dict 를 치지 않고(회사기초정보 엑셀에서 읽는다),
기한을 세지 않고(법정기한을 계산한다), 확인사항을 떠올리지 않고(규칙으로 세운다),
계산값 심는 것을 잊지 않는다(저장 직후 한 번 계산시킨다).

    python -m 작성 --받은자료 <폴더> --출력 <폴더> [--귀속연월 202607] [--기준 <정답.xlsx>]

귀속연월을 안 주면 급여대장 파일명(급여대장_2026-07.xlsx)에서 읽는다. 못 읽으면 묻는다 —
엉뚱한 달로 신고서를 만드는 것보다 한 번 묻는 편이 싸다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import 기한 as _기한          # noqa: E402
import 대조 as _대조          # noqa: E402
import 재계산 as _재계산      # noqa: E402
import 집계 as A              # noqa: E402
import 확인사항 as _확인      # noqa: E402
import 회사정보 as _회사      # noqa: E402

확인필요 = A.확인필요


def _찾기(폴더, 말들, 무엇):
    후보 = [p for p in Path(폴더).glob("*.xls*")
            if not p.name.startswith("~$") and any(m in p.name for m in 말들)]
    if len(후보) == 1:
        return 후보[0]
    if not 후보:
        raise 확인필요(f"{폴더} 에서 {무엇} 파일을 못 찾았습니다 "
                       f"(파일명에 {'·'.join(말들)} 중 하나가 있어야 합니다)")
    raise 확인필요(f"{무엇} 후보가 여럿입니다: {', '.join(p.name for p in 후보)}. 하나만 두세요")


def _귀속연월(대장경로, 시트목록=()):
    m = re.search(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])", Path(대장경로).name)
    if m:
        return m.group(1) + m.group(2)
    raise 확인필요(f"{Path(대장경로).name} 에서 귀속연월을 못 읽었습니다. "
                   f"--귀속연월 202607 처럼 적어 주세요 (시트: {', '.join(시트목록)})")


def _추가행파일(폴더, 귀속연월):
    """입퇴사처리 스킬이 남긴 추가행_YYYY-MM.json. 중도퇴사 정산 · 퇴직소득 · 기타소득이 들어 있다."""
    p = Path(폴더) / f"추가행_{귀속연월[:4]}-{귀속연월[4:6]}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _전월소득세합(대장, 정보, 귀속연월):
    """전월 시트가 같이 있으면 그 달 소득세 합을 본다. 전액 양수면 이월 환급이 없다고 본다.
    전월 신고서를 대신하지는 못하지만, 「확인 요」와 「없음」을 가르는 근거는 된다."""
    import openpyxl
    y, m = int(귀속연월[:4]), int(귀속연월[4:6])
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    후보 = {f"{pm}월", f"{pm:02d}월", f"{py}-{pm:02d}", f"{py}{pm:02d}"}
    이름 = next((n for n in 정보.get("시트목록", [])
                 if any(h in n.replace(" ", "") for h in 후보)), None)
    if not 이름:
        return None
    try:
        행 = A.read_ledger(대장, sheet=이름)
    except Exception:
        return None
    return sum(r["소득세"] for r in 행)


def 실행(받은자료, 출력, 귀속연월=None, 지급연월=None, 시트=None, 기준=None,
         추가행=(), 행수정=None, 환급=None, 계산값=True):
    대장 = _찾기(받은자료, ("급여대장", "대장", "payroll"), "급여대장")
    회사표 = _찾기(받은자료, ("회사기초정보", "기초정보", "회사정보"), "회사기초정보")

    회사, 플래그, 환급계좌, 납부주기 = _회사.읽기(회사표)
    ym = 귀속연월 or _귀속연월(대장)
    기간 = _기한.산출(ym, 납부주기, 지급연월)

    정보 = {}
    행들 = [dict(r) for r in A.read_ledger(대장, sheet=시트, 귀속연월=ym, 정보=정보)]
    if 행수정:
        행들 = [행수정(r) or r for r in 행들]
    행들 = 행들 + [dict(r) for r in 추가행] + _추가행파일(받은자료, ym)
    묶음 = A.집계(행들)

    확인 = _확인.세우기(행들, 기간, 대장정보=정보, 납부주기=납부주기,
                        지급항목=정보.get("지급항목", ()),
                        전월소득세합=_전월소득세합(대장, 정보, ym))

    out = Path(출력); out.mkdir(parents=True, exist_ok=True)
    xlsx = A.write_workbook(out / f"원천징수집계_{ym}.xlsx", 회사, 기간, 행들, 묶음,
                            확인, 환급=환급)
    if 계산값:
        _재계산.심기(xlsx)
    전체, 빈칸 = _재계산.확인(xlsx)

    값 = A.신고값(묶음, 회사, 기간, 환급, 플래그)
    값["환급계좌"] = 환급계좌
    값["확인사항"] = [{"항목": a, "왜": b, "정한값": c} for a, b, c in 확인]
    js = out / f"신고값_{ym}.json"
    js.write_text(json.dumps(값, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{회사['상호']} · {ym} 귀속 · {기간['신고구분']}납부")
    print(f"신고·납부기한 {기간['_실제기한']}" + (f"  ({기간['_이월사유']})" if 기간["_이월사유"] else ""))
    print(f"대장 {대장.name} 「{정보['시트']}」 시트 · 인별 {len(행들)}행")
    for c in sorted(묶음):
        g = 묶음[c]
        print(f"  {c} {A.소득구분명.get(c,''):<16} 인원{g['인원']:>3}  "
              f"총지급 {g['총지급액']:>13,}  소득세 {g['소득세']:>11,}")
    print(f"  납부할 세액 {max(묶음['A99']['소득세'], 0):,} 원 · "
          f"위택스 지방소득세 {묶음['A99']['지방소득세']:,} 원")
    print(f"  계산값 {전체-빈칸}/{전체}" + ("" if 빈칸 == 0 else "  ⚠ 엑셀에서 한 번 열었다 저장하세요"))
    빈확인 = [a for a, _, c in 확인 if not c]
    print(f"  확인사항 {len(확인)}건" + (f" · 아직 안 정한 것: {', '.join(빈확인)}" if 빈확인 else " · 전부 정함"))
    print(f"\n  {xlsx}\n  {js}")

    결과 = {"엑셀": str(xlsx), "신고값": str(js), "묶음": 묶음, "기간": 기간,
            "확인사항": 확인, "행수": len(행들), "계산값빈칸": 빈칸}
    if 기준:
        print()
        결과["대조"] = _대조.출력(str(xlsx), 기준)
    return 결과


def main():
    ap = argparse.ArgumentParser(description="급여대장 + 회사기초정보 → 원천징수집계")
    ap.add_argument("--받은자료", required=True)
    ap.add_argument("--출력", required=True)
    ap.add_argument("--귀속연월")
    ap.add_argument("--지급연월", help="귀속과 다를 때만. 예) 12월분을 2월에 지급")
    ap.add_argument("--시트", help="대장 시트를 직접 고를 때")
    ap.add_argument("--기준", help="맞춰볼 기준 파일(전월 확정본·정답본)")
    ap.add_argument("--계산값-생략", action="store_true", help="엑셀 재계산을 건너뛴다")
    a = ap.parse_args()
    try:
        r = 실행(a.받은자료, a.출력, a.귀속연월, a.지급연월, a.시트, a.기준,
                 계산값=not getattr(a, "계산값_생략"))
    except 확인필요 as e:
        print(f"\n멈췄습니다 — {e}", file=sys.stderr)
        return 2
    return r.get("대조", 0)


if __name__ == "__main__":
    sys.exit(main())
