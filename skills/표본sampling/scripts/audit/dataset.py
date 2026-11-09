"""표본을 뽑을 데이터 파일 판독(2026-11-09).

매출 원장 · 세금계산서 목록 · 채권 명세처럼 한 줄에 금액 하나가 있는 표를 읽는다. 엑셀(xlsx · xlsm · xls)과 csv.

  read(path, sheet=None, cols=None, raw=False) -> {path, sheet, header_row, headers, cols, idx, rows, skipped, sha[, raw]}

cols 는 {역할: 열 이름} 이다. 역할은 amount(금액) · date(일자) · party(거래처) · desc(적요) · ref(전표번호) · strata(계층) · group(묶기).
주지 않은 역할은 머리줄 이름으로 찾는다(amount · date · party · desc · ref 만, strata · group 은 감사인이 고른다).
rows 는 [{"row": 원본 행 번호(1부터), "amount", "date", "party", "desc", "ref", "strata", "group"}].
합계 · 소계 행(합계 글자가 있고 일자가 빈 행)과 금액이 숫자가 아닌 행은 빼고 그 수를 skipped 에 적는다.
idx 는 {역할: 열 순번}, raw=True 면 raw 에 rows 와 같은 순서로 원본 행(값 튜플)을 함께 준다(sample scan 이 계층 후보를 찾을 때).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date
from pathlib import Path

from . import reader

ROLES = ("amount", "date", "party", "desc", "ref", "strata", "group")
ROLE_NAMES = {"amount": "금액", "date": "일자", "party": "거래처", "desc": "적요", "ref": "전표번호", "strata": "계층", "group": "묶기"}
# 머리줄 이름 후보(앞이 먼저). 금액은 부가세 뺀 공급가액을 합계금액보다 먼저 본다(매출과 맞는 금액)
CANDIDATES = {
    "amount": ["공급가액", "매출액", "매출금액", "금액", "원화금액", "채권계", "기말잔액", "잔액", "대변", "차변", "합계금액", "합계", "amount"],
    "date": ["작성일자", "전표일자", "거래일자", "매출일자", "일자", "날짜", "거래일", "발행일자", "date"],
    "party": ["거래처명", "거래처", "공급받는자상호", "상호", "고객명", "고객", "매출처", "업체명", "customer"],
    "desc": ["적요", "품목", "품명", "내용", "계정과목", "비고", "description"],
    "ref": ["전표번호", "승인번호", "문서번호", "번호", "no"],
}
# 이름에 들어 있으면 그 역할로 보지 않는다(부가세 칸을 금액으로 잡지 않게)
EXCLUDE = {"amount": ("세액", "부가세", "율", "수량", "단가", "번호", "코드"), "date": ("기간",), "party": ("번호", "코드", "사업자")}
SCAN = 15
TOTAL_RE = re.compile(r"^(?:\d{1,2}월)?(?:합계|총계|소계|월계|누계|계)(?::.*)?$")


class DataError(ValueError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _csv_rows(path: Path) -> list[tuple]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DataError(f"{Path(path).name}: 글자 인코딩을 읽지 못했습니다(utf-8 · cp949 아님)")
    out = []
    for r in csv.reader(io.StringIO(text)):
        out.append(tuple(x if x.strip() else None for x in r))
    return out


def _sheets(path: Path, sheet: str | None):
    """[(시트 이름, 행들)]. sheet 를 주면 그 시트만."""
    if Path(path).suffix.lower() == ".csv":
        return [(Path(path).stem, _csv_rows(path))]
    wb = reader._open(path)
    try:
        names = [ws.title for ws in wb.worksheets]
        if sheet and sheet not in names:
            raise DataError(f"{Path(path).name} 에 「{sheet}」 시트가 없습니다. 있는 시트: {', '.join(names)}")
        return [(ws.title, [tuple(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets if not sheet or ws.title == sheet]
    finally:
        wb.close()


def _find(headers: list[str], role: str, want: str | None, used: set) -> int | None:
    if want:
        w = reader._norm(want)
        for i, h in enumerate(headers):
            if h == w and i not in used:
                return i
        for i, h in enumerate(headers):
            if w and w in h and i not in used:
                return i
        return None
    excl = EXCLUDE.get(role, ())
    for c in CANDIDATES.get(role, ()):
        for i, h in enumerate(headers):
            if h.lower() == c and i not in used:
                return i
    for c in CANDIDATES.get(role, ()):
        if len(c) < 2 or c.isascii():          # 영어 후보(no · amount)는 같은 이름일 때만
            continue
        for i, h in enumerate(headers):
            if c in h.lower() and i not in used and not any(x in h for x in excl):
                return i
    return None


def _match(headers: list[str], cols: dict) -> dict | None:
    """머리줄 하나에서 역할별 열 번호. 금액 열이 없거나 감사인이 준 열이 없으면 None."""
    out, used = {}, set()
    for role in ROLES:
        want = cols.get(role)
        if role in ("strata", "group") and not want:
            continue
        # 층 · 묶기 열은 거래처 · 적요 열과 같아도 된다(거래처별 묶기)
        i = _find(headers, role, want, set() if role in ("strata", "group") else used)
        if i is None:
            if want or role == "amount":
                return None
            continue
        out[role] = i
        used.add(i)
    return out


def _numeric_share(rows, col: int) -> float:
    vals = [r[col] for r in rows[:50] if col < len(r) and r[col] not in (None, "")]
    if not vals:
        return 0.0
    return sum(1 for v in vals if reader._num(v) is not None) / len(vals)


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, date):
        return v.isoformat()[:10]
    return str(v).strip()


def _is_total(row, cols: dict) -> bool:
    if "date" in cols and cols["date"] < len(row) and reader._date(row[cols["date"]]):
        return False
    for v in row:
        if isinstance(v, str) and TOTAL_RE.match(re.sub(r"[\s\[\]<>()]", "", v)):
            return True
    return False


def read(path: Path, sheet: str | None = None, cols: dict | None = None, raw: bool = False) -> dict:
    path = Path(path)
    if not path.exists():
        raise DataError(f"데이터 파일이 없습니다: {path}")
    cols = {k: v for k, v in (cols or {}).items() if v}
    best = None
    for name, rows in _sheets(path, sheet):
        for hi in range(min(SCAN, len(rows))):
            for headers in reader._header_candidates(rows, hi):
                m = _match(headers, cols)
                if m is None:
                    continue
                body = rows[hi + 1:]
                share = _numeric_share(body, m["amount"])
                if share < 0.6:            # 금액 열 아래가 숫자가 아니면 머리줄이 아니다
                    continue
                score = (len(m), len(body))
                if best is None or score > best[0]:
                    best = (score, name, hi, headers, m, body, rows[hi])
                break
    if best is None:
        want = ", ".join(f"{ROLE_NAMES[k]}={v}" for k, v in cols.items())
        raise DataError(f"{path.name}: 금액 열이 있는 표를 찾지 못했습니다"
                        + (f"(준 열: {want})" if want else "") + ". --amount 로 금액 열 이름을 주십시오")
    _, name, hi, headers, m, body, raw_head = best
    out_rows, raws, skipped = [], [], {"합계 행": 0, "금액 없음": 0}
    for i, r in enumerate(body, start=hi + 2):
        if not any(v not in (None, "") for v in r):
            continue
        if _is_total(r, m):
            skipped["합계 행"] += 1
            continue
        amt = reader._num(r[m["amount"]]) if m["amount"] < len(r) else None
        if amt is None:
            skipped["금액 없음"] += 1
            continue
        x = {"row": i, "amount": amt}
        for role in ("party", "desc", "ref", "strata", "group"):
            x[role] = _text(r[m[role]]) if role in m and m[role] < len(r) else ""
        x["date"] = reader._date(r[m["date"]]) if "date" in m and m["date"] < len(r) else None
        out_rows.append(x)
        if raw:
            raws.append(r)
    names = [_text(v) for v in raw_head]
    return {"path": path, "sheet": name, "header_row": hi + 1, "headers": names,
            "cols": {role: names[i] if i < len(names) and names[i] else headers[i] for role, i in m.items()}, "idx": dict(m),
            "rows": out_rows, "skipped": skipped, "sha": _sha(path), **({"raw": raws} if raw else {})}
