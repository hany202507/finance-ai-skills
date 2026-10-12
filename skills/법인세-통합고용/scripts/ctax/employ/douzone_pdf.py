"""더존(위하고 · 아마란스) 「급여대장」 PDF 를 통합고용 입력의 급여대장 줄로 옮기는 보조 도구.

`python -m ctax.employ.douzone_pdf <급여대장 PDF 폴더> <통합고용_입력.xlsx>`

사람마다 세 줄(사원번호 · 성명 · 입사일)로 찍힌 양식만 읽는다. 열은 머리글 낱말(국민연금 · 건강보험 · 고용보험 · 소득세 ·
지방소득세 · 지급합계)의 가로 좌표로 가린다. 달마다 읽은 사람 수를 「합계(N명)」 과 맞춰 보이고, 다르면 그 달은 넣지 않는다.
사원명부에 없는 사람은 사번 · 성명 · 입사일만 든 줄로 더한다(생년월일 · 고용형태는 사람이 채운다).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from openpyxl import load_workbook

from .model import PAY_COLS, STAFF_COLS

NUM = re.compile(r"^-?[\d,]+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADS = ("국민연금", "건강보험", "고용보험", "소득세", "지방소득세", "지급합계")


def read_pdf(path: Path) -> tuple[list[dict], int | None]:
    """(사람별 줄, 「합계(N명)」 의 N). 줄: month · 사번 · 성명 · 입사일 · 퇴사일 · 지급액 · 소득세 · 국민연금 · 건강보험."""
    import fitz
    doc = fitz.open(path)
    out, month = [], None
    flat = re.sub(r"\s+", "", "".join(pg.get_text() for pg in doc))
    m = re.search(r"합계\(?(\d+)명", flat)
    for pg in doc:
        words = [(x0, y0, w) for x0, y0, _, _, w, *_ in pg.get_text("words")]
        for _, _, w in words:
            got = re.search(r"귀속:(\d{4})년(\d{2})월", w)
            if got:
                month = f"{got.group(1)}-{got.group(2)}"
        hx = {w: x0 for x0, _, w in words if w in HEADS}
        if any(h not in hx for h in HEADS):
            continue
        col = {"pension": (hx["국민연금"] - 8, hx["건강보험"] - 8), "health": (hx["건강보험"] - 8, hx["고용보험"] - 8),
               "tax": (hx["소득세"] - 8, hx["지방소득세"] - 3), "pay": (hx["지급합계"] - 12, hx["지급합계"] + 60)}
        head_y = max(y0 for _, y0, w in words if w == "지급합계")
        starts = sorted((y0, w) for x0, y0, w in words if 28 <= x0 <= 48 and re.fullmatch(r"\d{3,6}", w) and y0 > head_y)
        for i, (ys, sid) in enumerate(starts):
            ye = starts[i + 1][0] - 4 if i + 1 < len(starts) else ys + 40
            mine = [(x0, y0, w) for x0, y0, w in words if ys - 4 <= y0 < ye]
            name = next((w for x0, y0, w in mine if 60 <= x0 <= 110 and abs(y0 - ys) <= 3 and not NUM.match(w)), "")
            dates = [w for x0, y0, w in sorted(mine, key=lambda t: t[1]) if DATE.match(w) and x0 < 60]

            def val(key: str, top: bool) -> int:
                lo, hi = col[key]
                return sum(int(w.replace(",", "")) for x0, y0, w in mine if NUM.match(w) and lo <= x0 < hi
                           and ((abs(y0 - ys) <= 3) if top else (y0 > ys + 15)))
            out.append({"month": month, "사번": sid, "성명": name, "입사일": dates[0] if dates else "",
                        "퇴사일": dates[1] if len(dates) > 1 else "", "지급액": val("pay", False), "소득세": val("tax", True),
                        "국민연금": val("pension", True), "건강보험": val("health", True)})
    return out, int(m.group(1)) if m else None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(__doc__)
        return 2
    folder, target = Path(argv[0]), Path(argv[1])
    if not target.exists():
        print(f"{target} 가 없습니다. 먼저 「ctax employ <신고 건> --template」 으로 빈 양식을 만드십시오")
        return 2
    wb = load_workbook(target)
    pay, staff = wb["급여대장"], wb["사원명부"]
    p_head = [c.value for c in pay[1]]
    s_head = [c.value for c in staff[1]]
    if p_head[:len(PAY_COLS)] != [c[0] for c in PAY_COLS] or s_head[:len(STAFF_COLS)] != [c[0] for c in STAFF_COLS]:
        print("입력 양식의 머리글이 1행에 없습니다(--template 으로 만든 양식에만 붙입니다)")
        return 2
    known = {str(staff.cell(row=r, column=1).value) for r in range(2, staff.max_row + 1) if staff.cell(row=r, column=1).value}
    have = {(str(pay.cell(row=r, column=1).value), str(pay.cell(row=r, column=2).value)) for r in range(2, pay.max_row + 1)}
    code = 0
    for pdf in sorted(folder.glob("*.pdf")):
        rows, total = read_pdf(pdf)
        if not rows or (total is not None and total != len(rows)):
            print(f"넣지 않음 {pdf.name}: 읽은 사람 {len(rows)}명, 합계 줄 {total}명")
            code = 1
            continue
        added = 0
        for x in rows:
            if (x["month"], x["사번"]) in have:
                continue
            pay.append([x["month"], x["사번"], x["성명"], x["지급액"], x["소득세"], x["국민연금"], x["건강보험"]])
            have.add((x["month"], x["사번"]))
            added += 1
            if x["사번"] not in known:
                row = {"사번": x["사번"], "성명": x["성명"], "입사일": x["입사일"], "퇴사일": x["퇴사일"] or None}
                staff.append([row.get(h) for h in s_head[:len(STAFF_COLS)]])
                known.add(x["사번"])
        print(f"{pdf.name}: {rows[0]['month']} {len(rows)}명(합계 줄 {total}명), 더한 줄 {added}")
    wb.save(target)
    print("사원명부에 새로 더한 사람은 생년월일 · 고용형태 · 퇴사일을 채워야 ctax employ 가 돕니다")
    return code


if __name__ == "__main__":
    sys.exit(main())
