"""받은자료 xlsx 를 행 목록으로 읽는다. 숫자 · 이름 정리 도우미도 여기 둔다.

Drive 에서 받은 xlsx 는 styles.xml 의 `<xf ... count="n">` 때문에 openpyxl 이 TypeError 를 내는 일이 있어
그 속성만 지운 사본으로 다시 연다(corptax-impl `xlsx_io` 에서 옮김).
"""
from __future__ import annotations

import io
import re
import warnings
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook


class Unreadable(Exception):
    """파일이 깨졌거나 xlsx 가 아니다."""


CONTENT_ERRORS = (zipfile.BadZipFile, KeyError, OSError, zlib.error, EOFError, SyntaxError)


def _repair_bytes(path: Path) -> bytes:
    with zipfile.ZipFile(path) as src:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
            for it in src.infolist():
                data = src.read(it.filename)
                if it.filename == "xl/styles.xml":
                    data = re.sub(rb'(<xf\b[^>]*?)\s+count="\d+"', rb"\1", data)
                out.writestr(it.filename, data)
    return buf.getvalue()


OOXML_SUFFIXES = (".xlsx", ".xlsm", ".xltx", ".xltm")


def _open(path: Path):
    # openpyxl 은 확장자를 본다. 이름이 .xls 인데 속이 xlsx 인 파일은 바이트로 넘긴다(11-08)
    src = path if path.suffix.lower() in OOXML_SUFFIXES else io.BytesIO(path.read_bytes())
    try:
        return load_workbook(src, read_only=True, data_only=True)
    except TypeError:
        pass
    except CONTENT_ERRORS as e:
        raise Unreadable(f"{path.name}: {e}") from e
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return load_workbook(io.BytesIO(_repair_bytes(path)), read_only=True, data_only=True)
    except (*CONTENT_ERRORS, TypeError) as e:
        raise Unreadable(f"{path.name}: {e}") from e


def file_format(path) -> str:
    """앞 바이트로 가린 엑셀 꼴: zip 서명 `PK` 면 xlsx, OLE 복합 문서 서명이면 xls, 둘 다 아니면 빈 글(11-08, 제품 vfs.sniff).
    확장자는 믿지 않는다. 받은 파일 중에 이름은 .xls 인데 속은 xlsx 인 것(그 반대도)이 있다."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return ""
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "xlsx"
    if head == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls"
    return ""


def _real_format(path: Path) -> str:
    """읽을 때 쓸 꼴. 서명으로 못 가리면 확장자대로(지금까지와 같다)."""
    return file_format(path) or ("xls" if path.suffix.lower() == ".xls" else "xlsx")


def _xls_sheet(sh) -> list[list]:
    out = []
    for r in range(sh.nrows):
        row = []
        for c in range(sh.ncols):
            v = sh.cell_value(r, c)
            if v == "":
                v = None
            elif isinstance(v, float) and v.is_integer():
                v = int(v)
            row.append(v)
        out.append(row)
    return out


def _xls_book(path: Path):
    try:
        import xlrd
    except ImportError as e:        # pragma: no cover - requirements.txt 에 있다
        raise Unreadable(f"{path.name}: xls 를 읽으려면 xlrd 가 필요합니다") from e
    try:
        return xlrd.open_workbook(str(path))
    except Exception as e:          # xlrd 는 깨진 파일마다 다른 예외를 낸다
        raise Unreadable(f"{path.name}: {e}") from e


def xls_rows(path) -> list[list]:
    """BIFF xls(더존 ERP 계정명세서 · 합계잔액시산표) 첫 시트의 행. 빈 칸은 None, 정수인 실수는 정수로."""
    path = Path(path)
    return _xls_sheet(_xls_book(path).sheet_by_index(0))


def _xlsx_sheets(path: Path, limit: int | None, first_only: bool) -> list[tuple[str, list[list]]]:
    out: list[tuple[str, list[list]]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        wb = _open(path)
        try:
            for ws in wb.worksheets[:1] if first_only else wb.worksheets:
                rs = []
                for r in ws.iter_rows(values_only=True):
                    rs.append(list(r))
                    if limit is not None and len(rs) >= limit:
                        break
                out.append((ws.title, rs))
        except CONTENT_ERRORS as e:
            raise Unreadable(f"{path.name}: {e}") from e
        finally:
            wb.close()
    return out


def rows(path, limit: int | None = None) -> list[list]:
    """첫 시트의 행을 목록으로. limit 이 있으면 그 행 수까지만. xls 는 xlrd 로 읽는다(꼴은 앞 바이트로, 11-08)."""
    path = Path(path)
    if _real_format(path) == "xls":
        out = xls_rows(path)
        return out[:limit] if limit is not None else out
    return _xlsx_sheets(path, limit, True)[0][1]


def sheets(path) -> list[tuple[str, list[list]]]:
    """모든 시트 [(시트 이름, 행)]. 시트 순서대로(11-08, 제품 files/sheet.py). xls · xlsx 는 앞 바이트로 가린다."""
    path = Path(path)
    if _real_format(path) == "xls":
        book = _xls_book(path)
        return [(sh.name, _xls_sheet(sh)) for sh in book.sheets()]
    return _xlsx_sheets(path, None, False)


def col_name(c: int) -> str:
    """0 부터 센 열 번호 → 엑셀 열 이름(0 → A)."""
    s, c = "", c + 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------- 값 정리

MINUS = "-−－‐‑–"            # 빼기: ASCII · U+2212 · 전각 · 하이픈 꼴(11-08, 제품 values.AMOUNT)
DIGIT = re.compile(r"\d")


def num(v) -> int | None:
    """셀 값을 정수(원)로. 쉼표 문자열, `△` · `▲` · 유니코드 빼기(−, －) 음수, 괄호 음수, 끝의 「원」, 앞뒤 · 가운데 공백,
    정수 · 실수를 안다. 빈 값은 None. 읽지 못한 글도 None 이다(bad_num 으로 가린다)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(round(v))
    s = re.sub(r"\s+", "", str(v)).replace(",", "")
    if s.endswith("원"):
        s = s[:-1]
    if s in ("", "-"):
        return None
    neg = False
    if s[0] in "△▲":
        neg, s = True, s[1:]
    elif s[0] in MINUS[1:]:
        neg, s = True, s[1:]
    elif s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    try:
        x = int(s)
    except ValueError:
        try:
            x = int(round(float(s)))
        except (ValueError, OverflowError):
            return None
    return -x if neg else x


def n0(v) -> int:
    x = num(v)
    return 0 if x is None else x


def bad_num(v) -> bool:
    """숫자처럼 보이는데(숫자가 든 글) 금액으로 읽지 못한 칸. 「12a」 같은 것. 숫자가 없는 글(「메모」)은 아니다."""
    return isinstance(v, str) and bool(DIGIT.search(v)) and num(v) is None


SHOW_BAD = 5


@dataclass
class Cells:
    """읽는 시트의 자리와 금액으로 읽지 못한 칸(11-08). 읽기 함수가 칸을 0 으로 바꿀 때 주소와 원래 글을 남긴다.

    sheet: 시트 이름 · off: 머리줄 위에서 건너뛴 행 수(rows[0] 이 엑셀 off + 1 행) · bad: [(주소, 원래 글)]."""
    sheet: str = ""
    off: int = 0
    bad: list = field(default_factory=list)

    def row(self, n: int) -> int:
        """읽은 행 목록 기준 행 번호(1부터) → 엑셀 행 번호."""
        return n + self.off

    def addr(self, row_no: int, col: int | None) -> str:
        cell = f"{col_name(col) if col is not None else '?'}{row_no}"
        return f"{self.sheet}!{cell}" if self.sheet else cell

    def num(self, v, row_no: int, col: int) -> int | None:
        """num 과 같고, 읽지 못한 칸이면 남긴다. row_no 는 엑셀 행 번호."""
        x = num(v)
        if x is None and bad_num(v):
            self.bad.append((self.addr(row_no, col), str(v).strip()))
        return x

    def n0(self, v, row_no: int, col: int) -> int:
        x = self.num(v, row_no, col)
        return 0 if x is None else x

    def note(self) -> str | None:
        if not self.bad:
            return None
        shown = ", ".join(f"{a} 「{t[:20]}」" for a, t in self.bad[:SHOW_BAD])
        more = f" 외 {len(self.bad) - SHOW_BAD}칸" if len(self.bad) > SHOW_BAD else ""
        return f"금액으로 읽지 못한 칸 {len(self.bad)}칸을 0(빈 값)으로 두었습니다: {shown}{more}. 받은 파일의 그 칸을 확인합니다"


def compact(s) -> str:
    """공백(전각 포함)을 모두 지운 글."""
    return re.sub(r"[\s　]+", "", str(s or ""))


SUFFIX = re.compile(r"\((판|제|도|분|보|운|공|임|건|용|기|관)\)$")
ROMAN = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\.")
PAREN = re.compile(r"^\(\d+\)")


def norm(s) -> str:
    """계정 이름 비교용. 공백과 `(판)` · `(제)` · `(도)` 같은 끝 꼬리를 지운다."""
    return SUFFIX.sub("", compact(s))


def strip_no(s) -> str:
    """`Ⅳ. 판매비와 관리비` → `판매비와관리비`, `(1) 당좌자산` → `당좌자산`."""
    c = compact(s)
    c = ROMAN.sub("", c, count=1)
    c = PAREN.sub("", c, count=1)
    return c.lstrip(".")


def text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def date_text(v) -> str | None:
    """전표일자를 `YYYY-MM-DD` 로. 날짜가 아니면 None(합계 줄 등)."""
    if isinstance(v, (datetime, date)):
        return text(v)
    s = text(v)
    m = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None
