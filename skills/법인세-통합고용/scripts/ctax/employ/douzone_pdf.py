"""더존(위하고 · 아마란스) 「급여대장」 PDF 를 통합고용 입력의 급여대장 줄로 옮기는 보조 도구.

`python -m ctax.employ.douzone_pdf <급여대장 PDF 폴더> <통합고용_입력.xlsx>`

PDF 는 kordoc(`npx -y kordoc@^4`, Node.js 18 이상)으로 표를 읽는다. 머리글 네 줄 · 사람마다 세 줄인 양식만 읽는다.
머리글 칸 이름(사원번호 · 성명 · 국민연금 · 건강보험 · 소득세 · 입사일 · 퇴사일 · 지급합계)이 놓인 줄과 열로 값을 가린다.
달마다 읽은 사람 수를 「합계(N명)」 과 맞춰 보이고, 다르면 그 달은 넣지 않는다.
사원명부에 없는 사람은 사번 · 성명 · 입사일만 든 줄로 더한다(생년월일 · 고용형태는 사람이 채운다).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from .model import PAY_COLS, STAFF_COLS

NUM = re.compile(r"^-?[\d,]+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SID = re.compile(r"^\d{3,10}$")
KORDOC = ["npx", "-y", "kordoc@^4"]
FIELDS = {"사원번호": "사번", "성명": "성명", "입사일": "입사일", "퇴사일": "퇴사일",
          "국민연금": "국민연금", "건강보험": "건강보험", "소득세": "소득세", "지급합계": "지급액"}


class KordocError(RuntimeError):
    pass


def run_kordoc(pdfs: list[Path]) -> dict[Path, dict]:
    """PDF 여러 개를 kordoc 한 번으로 읽어 {PDF: kordoc JSON} 을 돌려준다."""
    npx = shutil.which("npx")
    if not npx:
        raise KordocError("kordoc 을 돌릴 npx 가 없습니다. Node.js 18 이상을 설치하십시오(https://nodejs.org)")
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [npx, *KORDOC[1:], *map(str, pdfs), "-d", tmp, "--format", "json", "--silent", "--no-images"]
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = {}
        for p in pdfs:
            got = Path(tmp) / f"{p.stem}.json"
            if not got.exists():
                raise KordocError(f"kordoc 이 {p.name} 을 읽지 못했습니다: {(done.stderr or done.stdout).strip()[-400:]}")
            out[p] = json.loads(got.read_text(encoding="utf-8"))
    return out


def _num(s: str) -> int:
    s = (s or "").strip()
    return int(s.replace(",", "")) if NUM.match(s) else 0


def parse(doc: dict) -> tuple[list[dict], int | None]:
    """kordoc JSON 하나에서 (사람별 줄, 「합계(N명)」 의 N).
    줄: month · 사번 · 성명 · 입사일 · 퇴사일 · 지급액 · 소득세 · 국민연금 · 건강보험."""
    texts = [b.get("text", "") for b in doc.get("blocks", []) if b.get("type") != "table"]
    flat = re.sub(r"\s+", "", " ".join(texts))
    got = re.search(r"귀속[:：]?(\d{4})년(\d{1,2})월", flat) or re.search(r"(\d{4})년(\d{1,2})월", flat)
    month = f"{got.group(1)}-{int(got.group(2)):02d}" if got else None
    out, total = [], None
    for block in doc.get("blocks", []):
        if block.get("type") != "table":
            continue
        rows = [[re.sub(r"\s+", "", c.get("text") or "") for c in r] for r in block["table"]["cells"]]
        for r in rows:
            m = re.search(r"합계\(?(\d+)명", "".join(r))
            if m:
                total = int(m.group(1))
        top = next((i for i, r in enumerate(rows) if "사원번호" in r), None)
        if top is None:
            continue
        at = {}                                          # 머리글 이름 → (사람 첫 줄에서 몇째 줄, 열)
        for k in range(3):
            if top + k >= len(rows):
                break
            for j, t in enumerate(rows[top + k]):
                if t in FIELDS and t not in at:
                    at[t] = (k, j)
        if any(f not in at for f in FIELDS):
            raise ValueError(f"더존 급여대장 머리글에 {' · '.join(f for f in FIELDS if f not in at)} 이 없습니다")
        i = top + 3
        while i < len(rows):
            r = rows[i]
            k0, j0 = at["사원번호"]
            if k0 == 0 and j0 < len(r) and SID.match(r[j0]):
                cell = lambda f: rows[i + at[f][0]][at[f][1]] if i + at[f][0] < len(rows) and at[f][1] < len(rows[i + at[f][0]]) else ""
                hired, left = cell("입사일"), cell("퇴사일")
                out.append({"month": month, "사번": r[j0], "성명": cell("성명"),
                            "입사일": hired if DATE.match(hired) else "", "퇴사일": left if DATE.match(left) else "",
                            "지급액": _num(cell("지급합계")), "소득세": _num(cell("소득세")),
                            "국민연금": _num(cell("국민연금")), "건강보험": _num(cell("건강보험"))})
                i += 3
            else:
                i += 1
    return out, total


def read_pdf(path: Path) -> tuple[list[dict], int | None]:
    """PDF 하나를 kordoc 으로 읽어 parse 한다. 여러 개면 read_folder 가 kordoc 을 한 번만 부른다."""
    return parse(run_kordoc([Path(path)])[Path(path)])


def read_folder(folder: Path) -> list[tuple[Path, list[dict], int | None]]:
    pdfs = sorted(Path(folder).glob("*.pdf"))
    docs = run_kordoc(pdfs) if pdfs else {}
    return [(p, *parse(docs[p])) for p in pdfs]


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
    code, new_staff = 0, 0
    try:
        read = read_folder(folder)
    except (KordocError, ValueError) as e:
        print(f"급여대장 PDF 를 읽지 못했습니다: {e}")
        return 2
    if not read:
        print(f"{folder} 에 PDF 가 없습니다")
        return 2
    for pdf, rows, total in read:
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
                new_staff += 1
        print(f"{pdf.name}: {rows[0]['month']} {len(rows)}명(합계 줄 {total}명), 더한 줄 {added}")
    wb.save(target)
    if new_staff:
        print(f"사원명부에 없던 {new_staff}명을 더했습니다. 생년월일 · 고용형태 · 퇴사일을 채워야 ctax employ 가 돕니다")
    return code


if __name__ == "__main__":
    sys.exit(main())
