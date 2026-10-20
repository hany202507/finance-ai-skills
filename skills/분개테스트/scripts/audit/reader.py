"""받은자료 엔진 판독(R1 T2, 2026-10-05).

엑셀 받은자료에서 숫자 사실을 결정적으로 뽑는다. 숫자 사실은 이 모듈만 만든다(basis "엔진", value).
PDF 는 글자만 쪽 번호와 함께 돌려주고 사실은 만들지 않는다. PDF 의 종류 · 기간 · 사실(문장)은 AI 판독 몫이고
`python -m audit index apply` 로만 들어간다.

  read(path, kind, fy_end=None)   종류별 판독. 사실 목록 [{text, basis: "엔진", value, source_page}]
  sniff_kind(path)                엑셀 머리줄로 종류를 판별한다(기타 폴더 · 분류 전 · 판독 필요 파일용)
  journal_parties(path)           분개장의 거래처 집합(전기에 없던 거래처 계산용)
  period_from_facts(facts)        엔진 사실의 기간 · 기준일에서 문서목록 period 를 만든다
  period_from_journal(path)       분개장 일자에서 period 를 만든다
  pdf_text(path)                  [(쪽 번호, 글자)]

머리줄은 각 시트의 첫 10행에서 알려진 열 이름을 찾아 정한다. 제목 행이 위에 있어도 된다.
합계 · 소계 · 월계 · 누계 행은 더하지 않는다(이카운트 · 더존 출력물에 섞여 들어와 두 배가 되는 것을 막는다).
"""
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from itertools import zip_longest
from pathlib import Path

TB = "회사제시 재무제표·시산표"
JOURNAL = "분개장"
AGING = "연령분석표"
PAYROLL = "급여대장"
FIXED = "고정자산대장"
EXCEL = (".xlsx", ".xlsm")
XLS = (".xls",)
READABLE = EXCEL + XLS                    # 엔진 판독기가 여는 확장자(.xls 는 xlrd, 2026-10-18)
HEADER_SCAN = 10
TOTAL_LABELS = ("합계", "총계", "소계", "월계", "누계", "계")
PERIOD_FACT = "기간 "
ASOF_FACT = "기준일 "
NEW_PARTY_FACT = "전기 분개장에 없던 거래처"

# 열 이름 후보. 앞의 것이 먼저다. 정확히 같은 이름을 먼저 보고, 없으면 포함하는 이름을 본다
COLS = {
    "code": ["계정코드", "코드", "계정과목코드"],
    "name": ["계정명", "계정과목", "과목명", "계정"],
    "line": ["표시과목", "재무제표표시과목", "보고과목"],
    "cur": ["당기", "당기말", "당기잔액", "잔액", "금액"],
    "dr_bal": ["차변잔액"],
    "cr_bal": ["대변잔액"],
    # 일자: 더존 분개장 「년/월/일」, ERP 내보내기 「승인일」 · 「작성일」 · 「기표일」(R8). 앞의 것이 먼저다
    "date": ["일자", "전표일자", "회계일자", "날짜", "거래일자", "년/월/일", "년월일", "기표일자", "기표일", "승인일자", "승인일",
             "전표일", "작성일자", "작성일"],
    "voucher": ["전표번호", "전표", "승인번호", "기표번호", "번호"],
    "row": ["행번호", "순번"],
    "dr": ["차변", "차변금액"],
    "cr": ["대변", "대변금액"],
    "memo": ["적요"],
    "party": ["거래처", "거래처명", "상호"],
    # 금융기관 명세(차입금 · 예금 시트의 은행 열, 2026-10-18). 계정명세서 거래처 칸이 없는 꼴에서 거래처 대신 쓴다
    "inst": ["은행", "은행명", "금융기관", "금융기관명", "차입처", "대주"],
    "ar_total": ["채권잔액", "잔액", "합계", "총액", "미수금액", "금액"],
    "over90": ["90일초과", "91일이상", "90일이상", "91일초과", "3개월초과"],
    "month": ["월", "지급월", "귀속월", "급여월", "지급연월", "귀속연월"],
    "emp": ["성명", "사원명", "이름"],
    "pay": ["지급합계", "총지급액", "지급총액", "급여합계", "급여총액", "지급액", "합계"],
    "unpaid": ["미지급", "미지급액", "미지급금", "미지급급여"],
    "heads": ["인원", "인원수", "월인원"],
    "asset": ["자산명", "자산", "품명", "자산명칭"],
    "acq_date": ["취득일", "취득일자", "취득년월일"],
    "acq_cost": ["취득가", "취득가액", "취득원가", "취득금액"],
    "acq_cur": ["당기취득", "당기증가", "당기취득액"],
    "dep_cur": ["당기감가상각비", "감가상각비", "당기상각비"],
    "dep_end": ["기말감가상각누계액", "당기말상각누계액", "당기말감가상각누계액", "감가상각누계액", "상각누계액"],
    # 변동 꼴 자산대장(기초가액 · 당기증가 · 당기감소 · 기말잔액, 2026-10-18): 취득가 열이 없으면 기말잔액이 기말 취득가액이다
    "acq_beg": ["기초가액", "기초취득가액", "기초취득원가"],
    "acq_end": ["기말잔액", "기말가액", "기말취득가액", "기말취득원가"],
    "book_end": ["미상각잔액", "기말장부가액", "기말장부금액", "당기말장부가액"],
    "fa_acct": ["과목", "계정과목", "계정명", "계정"],
    # 비교식 시산표의 전기 열(R7, 2026-10-06). 차변 · 대변으로 나뉜 꼴은 prior_dr · prior_cr
    "prior": ["전기", "전기말", "전기잔액", "전기금액", "전기말잔액"],
    "prior_dr": ["전기차변잔액", "전기차변"],
    "prior_cr": ["전기대변잔액", "전기대변"],
    # 두 계정 칸 꼴 분개장(한 행에 차변 계정 · 금액, 대변 계정 · 금액. 계정은 '[코드]이름', R8)
    "dr_acc": ["차변계정과목", "차변계정", "차변과목", "차변계정명"],
    "cr_acc": ["대변계정과목", "대변계정", "대변과목", "대변계정명"],
    # 금액 하나와 차대 구분 열 꼴, 「차변-대변」 한 열 꼴(R8)
    "side": ["차대구분", "대차구분", "차/대", "차대"],
    "amount": ["금액"],
    "signed": ["차변-대변", "차변−대변", "차변대변차액"],
    "year": ["년", "연도", "회계연도"], "mon": ["월"], "day": ["일"],
    # 계정과목표의 상위 계정 코드(더존 LINK_CD) · 계정그룹(2026-10-09)
    "parent": ["LINK_CD", "상위계정코드", "상위코드", "상위계정", "관리계정코드"],
    "acc_group": ["계정그룹", "계정구분", "그룹명"],
    # 특수관계자 목록(2026-10-16, 3500)
    "rp_name": ["특수관계자명", "특수관계자", "회사명", "성명", "상호", "이름"],
    "relation": ["관계", "특수관계구분", "관계내용", "관계구분"],
    # 계약별 진행률 명세(2026-10-16, 4000P 진행기준 매출)
    "contract": ["계약명", "공사명", "계약번호", "공사번호", "프로젝트명", "프로젝트"],
    "contract_amt": ["계약금액", "총계약금액", "도급금액", "계약수익"],
    "est_cost": ["총예정원가", "추정총원가", "총추정원가", "예정원가", "총공사예정원가"],
    "cost_todate": ["누적발생원가", "누적원가", "발생원가누계", "누적투입원가", "누적공사원가"],
    "rev_prior": ["전기누적매출", "전기까지인식매출", "전기누적수익", "전기말누적매출", "전기누적공사수익"],
    "rev_cur": ["당기인식매출", "당기매출", "당기수익", "당기공사수익"],
    "billed": ["누적청구액", "청구누계", "누적청구", "누적청구금액"],
}
EXCLUDE = {"dep_end": ("기초", "전기"), "acq_end": ("상각", "장부"), "fa_acct": ("코드", "번호"), "cur": ("전기", "차변", "대변"), "pay": ("차인", "실지급", "공제"), "ar_total": ("전기",), "name": ("코드",),
           "prior": ("차변", "대변", "이월"), "dr": ("계정", "과목", "코드", "잔액", "-", "−"), "cr": ("계정", "과목", "코드", "잔액", "-", "−"),
           "voucher": ("거래처", "사업자", "프로젝트", "카드", "계좌", "주민", "등록"), "party": ("코드", "번호", "분류", "유형"),
           "amount": ("차변", "대변", "공급", "세액"), "cost_todate": ("전기",), "rev_cur": ("누적", "전기"), "contract_amt": ("변경전",), "relation": ("명", "이름"),
           "rp_name": ("코드", "번호")}
EXACT_ONLY = {"year", "mon", "day", "side"}       # 짧은 이름이라 포함 비교를 하지 않는다
PRIOR_TB = "전기 시산표"
TB_NO_CODE = "코드 없는 더존 합계잔액시산표"


# ---------------------------------------------------------------- 공통
def _norm(v) -> str:
    if v is None:
        return ""
    s = str(v)
    s = re.sub(r"\(.*?\)|\[.*?\]", "", s)
    return re.sub(r"\s+", "", s)


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("원", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _int(x: float) -> int | float:
    return int(round(x)) if abs(x - round(x)) < 1e-6 else x


def _won(x: float) -> str:
    x = _int(x)
    return f"{x:,}원" if isinstance(x, int) else f"{x:,.2f}원"


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 <= v <= 80000:               # 엑셀 날짜 일련번호
            return date(1899, 12, 30) + timedelta(days=int(v))
        v = str(int(v))
    if v is None:
        return None
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})일?(?:\s.*)?", s) or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _is_total_row(row, loose: bool = True) -> bool:
    """합계 · 소계 · 월계 · 누계 행. loose 면 '12월 합계' 처럼 끝이 합계인 칸도 본다(분개장은 적요와 겹쳐 정확히 같은 칸만 본다)."""
    for v in row:
        if isinstance(v, str):
            s = re.sub(r"[\s\[\]<>()]", "", v)
            if s in TOTAL_LABELS:
                return True
            if loose and len(s) <= 12 and any(s.startswith(t) or s.endswith(t) for t in TOTAL_LABELS[:-1]):
                return True
    return False


def _find_col(headers: list[str], key: str) -> int | None:
    cands = COLS[key]
    excl = EXCLUDE.get(key, ())
    for c in cands:
        for i, h in enumerate(headers):
            if h == c:
                return i
    if key in EXACT_ONLY:
        return None
    for c in cands:
        if len(c) < 2:
            continue
        for i, h in enumerate(headers):
            if c in h and not any(x in h for x in excl):
                return i
    return None


def _open(path: Path):
    """읽기 전용 통합문서. 옛 엑셀(.xls)은 xlrd 로 열어 openpyxl 과 같은 꼴(worksheets · title · iter_rows · close)로 준다(2026-10-18)."""
    if Path(path).suffix.lower() in XLS:
        return _XlsBook(Path(path))
    from openpyxl import load_workbook

    return load_workbook(path, read_only=True, data_only=True)


class _XlsSheet:
    def __init__(self, sh, datemode):
        self.title, self._sh, self._mode = sh.name, sh, datemode

    def iter_rows(self, values_only=True, max_row=None, min_row=None, max_col=None, **_):
        import xlrd

        n = self._sh.nrows if max_row is None else min(max_row, self._sh.nrows)
        for i in range((min_row or 1) - 1, n):
            out = []
            for c in self._sh.row(i)[:max_col]:
                if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    out.append(None)
                elif c.ctype == xlrd.XL_CELL_DATE:
                    try:
                        out.append(xlrd.xldate_as_datetime(c.value, self._mode))
                    except Exception:  # noqa: BLE001  깨진 날짜 칸은 숫자로 둔다
                        out.append(c.value)
                elif c.ctype == xlrd.XL_CELL_TEXT:
                    out.append(c.value if c.value.strip() else None)
                elif c.ctype == xlrd.XL_CELL_BOOLEAN:
                    out.append(bool(c.value))
                elif c.ctype == xlrd.XL_CELL_NUMBER:
                    v = c.value
                    out.append(int(v) if float(v).is_integer() else v)
                else:
                    out.append(None)
            yield tuple(out)


class _XlsBook:
    """xlrd 통합문서를 openpyxl 읽기 전용 꼴로 감싼다. xlrd 가 없으면 ImportError 를 그대로 낸다."""

    def __init__(self, path: Path):
        import xlrd

        self._bk = xlrd.open_workbook(str(path), on_demand=True)
        self.worksheets = [_XlsSheet(self._bk.sheet_by_index(i), self._bk.datemode) for i in range(self._bk.nsheets)]

    def close(self):
        self._bk.release_resources()


_DEFINED_NAMES = re.compile(rb"<definedNames>.*?</definedNames>|<definedNames\s*/>", re.S)


def open_plain(path: Path):
    """이름 정의를 뺀 사본으로 통합문서를 연다(읽기 전용 · 값만). 원본은 건드리지 않는다.
    손으로 만든 조서는 옛 서식에서 물려받은 이름 정의가 수천~수만 개 남아 있고 깨진 것이 섞여 있다. 그대로 열면
    openpyxl 이 「could not assign names」 로 멈추거나 여는 데 수십 초가 걸린다(예시 조서 25개 가운데 1개가 열리지 않았다, 2026-10-12).
    이름 정의는 엔진이 읽는 칸의 값과 상관이 없으므로 xl/workbook.xml 에서 빼고 연다."""
    import io
    import zipfile

    from openpyxl import load_workbook

    buf = io.BytesIO()
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/workbook.xml":
                data = _DEFINED_NAMES.sub(b"", data)
            dst.writestr(item, data)
    buf.seek(0)
    return load_workbook(buf, read_only=True, data_only=True)


def _compose(upper, lower) -> list[str]:
    """두 줄 머리를 한 줄 이름으로 붙인다. 위 줄이 병합 칸이면(오른쪽이 빈 칸) 그 이름을 오른쪽 아래 칸까지 이어 쓴다.
    예) 더존 합계잔액시산표 「차 변 | | 계정과목 | 대 변 |」 / 「잔 액 | 합 계 | | 합 계 | 잔 액」 → 차변잔액 · 차변합계 · 계정과목 · 대변합계 · 대변잔액"""
    out, grp = [], ""
    for a, b in zip_longest(upper, lower):
        a, b = _norm(a), _norm(b)
        if a:
            grp = a
        elif not b:
            grp = ""
        g = a or grp
        out.append(b if not g or g == b else (g if not b else g + b))
    return out


def _group_row(row) -> bool:
    """두 줄 머리의 위 줄로 볼 수 있는 행: 글자 칸이 둘 이상이고 숫자 · 날짜 칸이 없다."""
    texts = [v for v in row if isinstance(v, str) and v.strip()]
    nums = [v for v in row if isinstance(v, (int, float, datetime, date)) and not isinstance(v, bool)]
    return len(texts) >= 2 and not nums


def _match(headers: list[str], required: list[list[str]], optional: list[str]) -> dict | None:
    cols = {}
    for group in required:
        found = None
        for key in group:
            i = _find_col(headers, key)
            if i is not None and i not in cols.values():
                found = (key, i)
                break
        if found is None:
            return None
        cols[found[0]] = found[1]
    for key in optional:
        if key not in cols:
            i = _find_col(headers, key)
            if i is not None and i not in cols.values():
                cols[key] = i
    return cols


def _header_candidates(rows, hi):
    """hi 행을 머리줄로 볼 때의 이름들. 한 줄 그대로가 먼저, 다음은 위 줄과 붙인 두 줄 머리(R8).
    한 줄에 같은 이름이 둘 이상 있고(「잔액 | 합계 | 계정과목 | 합계 | 잔액」) 붙이면 겹침이 없어지면 두 줄 머리가 먼저다.
    한 줄만 보면 「잔액」 이 차변 잔액 칸 하나로 읽혀 대변 잔액이 빠진다(2026-10-18, 더존 감사후 시산표)."""
    single = [_norm(v) for v in rows[hi]]
    if not (hi > 0 and _group_row(rows[hi - 1])):
        yield single
        return
    comp = _compose(rows[hi - 1], rows[hi])

    def dup(hs):
        names = [h for h in hs if h]
        return len(names) != len(set(names))

    if dup(single) and not dup(comp):
        yield comp
        yield single
    else:
        yield single
        yield comp


def _tables(path: Path, required: list[list[str]], optional: list[str], reject: tuple[str, ...] = ()):
    """시트마다 첫 10행에서 머리줄을 찾는다. required 는 '이 가운데 하나' 묶음의 목록이다. 한 줄 머리가 맞지 않으면
    바로 위 줄과 붙인 두 줄 머리도 본다. reject 의 열이 있는 머리줄은 쓰지 않는다(시산표 판독이 분개장을 받아들이지 않게).
    돌려주는 것: [(시트 이름, {열 키: 열 번호}, 머리줄 아래 행들, 머리줄 위 행들, 머리줄 이름들)]"""
    wb = _open(path)
    out = []
    try:
        for ws in wb.worksheets:
            head = [tuple(r) for r in ws.iter_rows(values_only=True, max_row=HEADER_SCAN)]
            hit = None
            for hi in range(len(head)):
                for headers in _header_candidates(head, hi):
                    if any(_find_col(headers, k) is not None for k in reject):
                        continue
                    cols = _match(headers, required, optional)
                    if cols is not None:
                        hit = (hi, cols, headers)
                        break
                if hit:
                    break
            if hit:
                hi, cols, headers = hit
                rows = [tuple(r) for r in ws.iter_rows(values_only=True)]     # 머리줄을 찾은 시트만 끝까지 읽는다
                out.append((ws.title, cols, rows[hi + 1:], rows[:hi], headers))
    finally:
        wb.close()
    return out


def _cell(row, i):
    return row[i] if i is not None and i < len(row) else None


def _fact(text: str, value, sheet: str | None = None) -> dict:
    f = {"text": text, "basis": "엔진", "value": None if value is None else _int(float(value))}
    if sheet:
        f["source_page"] = f"{sheet} 시트"
    return f


def _code(v) -> int | None:
    """계정코드 3~7자리(R8: 7자리 보조계정 코드도 자르지 않는다). 8자리 이상 숫자(날짜 등)는 코드로 보지 않는다."""
    if v is None:
        return None
    m = re.match(r"\s*(\d{3,7})(?!\d)", str(v).split(".")[0] if isinstance(v, float) else str(v))
    return int(m.group(1)) if m else None


CODE_IN_NAME = re.compile(r"^\s*[\[(]\s*(\d{3,7})\s*[\])]\s*(.+?)\s*$")


def name_code(v) -> tuple[int | None, str]:
    """계정과목 칸 안의 코드. '[10100]현금' → (10100, '현금'). 코드가 없으면 (None, 이름)."""
    if v is None:
        return None, ""
    m = CODE_IN_NAME.match(str(v))
    if m:
        return int(m.group(1)), _norm(m.group(2))
    return None, _norm(v)


def _k3(code: int) -> int:
    return code if code < 1000 else int(str(code)[:3])


# ---------------------------------------------------------------- 회사제시 시산표
def _tb_group(raw) -> tuple[int, str] | None:
    """더존 합계잔액시산표의 묶음 줄. (단계, 이름) 또는 None. '<< 자 산 >>' 1 대분류, '[ 유동자산 ]' 2 중분류,
    '< 당좌자산 >' 3 소분류. '[10100]현금' 처럼 코드가 든 칸은 묶음 줄이 아니다."""
    if not isinstance(raw, str):
        return None
    t = raw.strip()
    if not t or CODE_IN_NAME.match(t):
        return None
    if t.startswith("<<") and t.endswith(">>"):
        return 1, _norm(t.strip("<> "))
    if t.startswith("[") and t.endswith("]"):
        return 2, _norm(t.strip("[] "))
    if t.startswith("<") and t.endswith(">"):
        return 3, _norm(t.strip("<> "))
    return None


# 재무제표 묶음별 더존 계정코드 범위(앞 3자리)와, 코드를 정하지 못한 계정에 붙이는 범위 코드(끝 3자리 + 순번 2자리)
FS_RANGES = {"유동자산": (101, 175), "비유동자산": (176, 250), "유동부채": (251, 290), "비유동부채": (291, 330), "자본": (331, 399),
             "매출액": (401, 450), "매출원가": (451, 500), "판매비와관리비": (801, 900), "영업외수익": (901, 930),
             "영업외비용": (931, 997), "법인세비용": (998, 999)}
FS_PLACEHOLDER = {"유동자산": "175", "비유동자산": "250", "유동부채": "290", "비유동부채": "330", "자본": "399", "매출액": "450",
                  "매출원가": "500", "판매비와관리비": "900", "영업외수익": "930", "영업외비용": "997", "법인세비용": "999"}
CURRENT_ASSET_SUBS = ("당좌자산", "재고자산")


def _tb_fs_group(top: str | None, mid: str | None, sub: str | None) -> str | None:
    """묶음 줄 이름으로 정한 재무제표 묶음(FS_RANGES 의 키). 정하지 못하면 None."""
    top, mid, sub = top or "", mid or "", sub or ""
    if "자산" in top:
        if "비유동" in mid or "비유동" in sub:
            return "비유동자산"
        if "유동" in mid or sub in CURRENT_ASSET_SUBS:
            return "유동자산"
        return "비유동자산" if sub else "유동자산"
    if "부채" in top:
        return "비유동부채" if "비유동" in (mid + sub) else "유동부채"
    if "자본" in top:
        return "자본"
    key = sub or mid
    if not key:
        return None
    if "외수익" in key:
        return "영업외수익"
    if "외비용" in key:
        return "영업외비용"
    if "법인세" in key:
        return "법인세비용"
    if "원가" in key:
        return "매출원가"
    if key in ("매출액", "매출", "영업수익"):
        return "매출액"
    if "판매" in key or "관리비" in key:
        return "판매비와관리비"
    return None


def _coa_key(name) -> str:
    """계정과목표와 시산표의 계정명을 맞추는 열쇠: 공백 · 마침표 · 가운뎃점을 뺀다(괄호 안 글자는 둔다)."""
    return re.sub(r"[\s.．·・]", "", str(name or ""))


def assign_codes(rows: list[dict], coa: dict | None = None) -> list[dict]:
    """코드가 없는 시산표 계정 줄에 계정코드를 붙인다(2026-10-18, 더존 합계잔액시산표 코드 없는 출력).
    rows 는 위에서 아래 순서이고 줄마다 name · raw_name · fs_group · subgroup 이 있다. 코드를 붙이는 순서:
      1 회사 계정과목표(coa_table 결과)에서 같은 이름. 같은 이름이 여럿이면(대손충당금 · 감가상각누계액 · 판관비와 원가의 같은 이름)
        계정그룹이 소분류 줄(< 당좌자산 > · < 판매관리비 >)과 같은 것, 그중 바로 위 계정 코드보다 큰 가장 작은 코드
        (더존 계정과목표는 차감 계정을 본 계정 바로 다음 코드에 둔다)
      2 계정 사전(accounts.yaml)의 코드 가운데 재무제표 묶음 범위 안의 것
      3 둘 다 없으면 묶음 범위 코드(FS_PLACEHOLDER + 순번). code_basis 에 '재무제표 위치(회계사 확인 필요)' 로 남긴다"""
    by: dict[str, list[dict]] = {}
    for x in (coa or {}).get("rows", []):
        for k in {_coa_key(x.get("full") or x["name"]), _coa_key(x["name"])}:
            by.setdefault(k, []).append(x)
    accs = None
    seq: dict[str, int] = {}
    used: dict[str, str] = {}
    prev = 0
    for r in rows:
        if r.get("code") is not None:
            prev = int(str(r["code"]))
            continue
        group = r.get("fs_group")
        lo, hi = FS_RANGES.get(group, (0, 999))
        code, basis = None, None
        cands = by.get(_coa_key(r.get("raw_name") or r["name"])) or by.get(_coa_key(r["name"])) or []
        cands = [x for x in cands if not group or lo <= int(str(x["code"])[:3]) <= hi] or cands
        if cands:
            sub = r.get("subgroup")
            same = [x for x in cands if sub and _norm(x.get("group")) == sub]
            pool = sorted(same or cands, key=lambda x: int(x["code"]))
            pick = next((x for x in pool if int(x["code"]) > prev), pool[0])
            code, basis = str(pick["code"]), "계정과목표"
        if code is None and group:
            from .analysis import defs

            if accs is None:
                accs = defs.load("accounts")["accounts"]
            n = defs.norm(r["name"])
            # 이름이 맞는 사전 계정 가운데 묶음 범위 안의 코드가 있는 첫 계정(「경상연구개발비」 는 무형자산 「개발비」 와도 맞는다)
            code = next((c for a in accs if any(re.search(p, n) for p in a.get("names", []))
                         for c in a.get("codes", []) if lo <= int(c) <= hi), None)
            basis = "계정 사전"
            if code is not None and used.get(code, r["name"]) != r["name"]:
                seq[code] = seq.get(code, 0) + 1
                code = f"{code}{seq[code]:02d}"
        if code is None:
            base = FS_PLACEHOLDER.get(group, "999")
            seq[base] = seq.get(base, 0) + 1
            code, basis = f"{base}{seq[base]:02d}", "재무제표 위치(회계사 확인 필요)"
        used.setdefault(code, r["name"])
        r["code"], r["code_basis"] = int(code), basis
        prev = int(code)
    return rows


def tb_table(path: Path, coa: dict | None = None) -> dict | None:
    """시산표 한 파일의 계정 행. {"rows": [{code, name, line, amount}], "sheet", "column", "form", "above"} (차변 +, 대변 −).
    꼴 셋을 읽는다(R8, 2026-10-18).
      계정코드 열     계정코드 · 계정명 · (표시과목) · 당기 또는 차변잔액 · 대변잔액. 더존 감사후 판의 「세목코드」 열도 여기다
      계정과목 칸 안   더존 합계잔액시산표처럼 코드가 계정과목 칸에 '[10100]현금' 으로 들어 있고 머리가 두 줄
                      (차변 잔액 · 합계 | 계정과목 | 대변 합계 · 잔액). 코드가 없는 줄(<< 자산 >> · [ 유동자산 ] · 합계)은 묶음 줄이라 뺀다
      코드 없는 더존   같은 두 줄 머리인데 계정과목 칸에 코드가 없다('제      예      금'). 묶음 줄(<< >> · [ ] · < >)이 있어야 이 꼴로 본다.
                      계정 줄의 코드는 assign_codes 가 붙인다(coa: 회사 계정과목표 coa_table 결과)
    같은 시트가 분개장으로 읽히면(일자 · 차변 · 대변 열) 시산표로 보지 않는다."""
    path = Path(path)
    forms = (("계정코드 열", [["code"], ["name"], ["cur", "dr_bal"]]), ("계정과목 칸 안 코드", [["name"], ["cur", "dr_bal"]]),
             (TB_NO_CODE, [["name"], ["dr_bal"], ["cr_bal"]]))
    for form, req in forms:
        tabs = _tables(path, req, ["line", "cr_bal", "cur"])
        for sheet, c, rows, above, headers in tabs:
            out = []
            top = mid = sub = None
            groups = 0
            for r in rows:
                # 더존 합계잔액시산표의 묶음 줄. '<< 자 산 >>' 대분류, '[ 유동자산 ]' 중분류, '< 당 좌 자 산 >' 소분류(R8)
                raw = _cell(r, c["name"])
                g = _tb_group(raw)
                if g:
                    groups += 1
                    level, key = g
                    if level == 1:
                        top, mid, sub = key, None, None
                    elif level == 2:
                        mid, sub = key, None
                    else:
                        sub = key
                    continue
                if form == TB_NO_CODE:
                    name = _norm(raw)
                    if not name or _is_total_row(r) or not isinstance(raw, str):
                        continue
                    code = None
                elif "code" in c:
                    code, name = _code(_cell(r, c["code"])), _norm(_cell(r, c["name"]))
                    if code is None:
                        code2, name2 = name_code(_cell(r, c["name"]))
                        code, name = (code2, name2) if code2 is not None else (None, name)
                else:
                    code, name = name_code(_cell(r, c["name"]))
                if code is None and form != TB_NO_CODE:
                    continue
                if "cur" in c:
                    amt = _num(_cell(r, c["cur"])) or 0.0
                else:
                    amt = (_num(_cell(r, c["dr_bal"])) or 0.0) - (_num(_cell(r, c.get("cr_bal"))) or 0.0)
                line = _norm(_cell(r, c.get("line"))) if "line" in c else ""
                row = {"code": code, "name": name, "line": line, "amount": _int(amt), "subgroup": sub}
                if top:
                    row["fs_group"] = _tb_fs_group(top, mid, sub)
                if form == TB_NO_CODE:
                    row["raw_name"] = re.sub(r"\s+", "", str(raw))
                out.append(row)
            if not out:
                continue
            if form == TB_NO_CODE and not groups:
                continue                      # 묶음 줄이 없는 표는 시산표로 단정하지 않는다(계정명세서 · 거래처 표와 겹친다)
            if sheet in {t["sheet"] for t in journal_tables(path)}:
                continue                      # 분개장 시트(거래처 코드 · 금액 열을 시산표로 읽지 않는다, 진단 #15)
            if form == TB_NO_CODE:
                assign_codes(out, coa)
                for x in out:
                    x.pop("raw_name", None)
            col = headers[c["cur"]] if "cur" in c else "차변잔액 − 대변잔액"
            return {"rows": out, "sheet": sheet, "column": col, "form": form, "above": above}
    return None


def _tb_facts(rows: list[dict], sheet: str | None, above=()) -> list[dict]:
    total = sales = ar = assets = liab = equity = pl = 0.0
    for r in rows:
        amt, name, line, k = r["amount"], r["name"], r["line"], _k3(r["code"])
        total += amt
        # 묶음 줄(<< 자산 >> · < 매출액 >)로 정한 재무제표 묶음이 있으면 그것을, 없으면 더존 계정코드 범위를 본다.
        # 더존 계정코드: 101~250 자산, 251~330 부채, 331~400 자본, 401~ 손익. 매출 401~430
        grp = r.get("fs_group")
        if grp:
            sec = "자산" if grp.endswith("자산") else "부채" if grp.endswith("부채") else "자본" if grp == "자본" else "손익"
            is_sales = grp == "매출액"
        else:
            sec = "자산" if 101 <= k <= 250 else "부채" if 251 <= k <= 330 else "자본" if 331 <= k <= 400 else "손익"
            is_sales = 401 <= k <= 430 and "원가" not in name
        assets += amt if sec == "자산" else 0.0
        liab += -amt if sec == "부채" else 0.0
        equity += -amt if sec == "자본" else 0.0
        pl += -amt if sec == "손익" else 0.0
        if (line == "매출액") if line else is_sales:
            sales += amt
        if (line == "매출채권") if line else (name in ("외상매출금", "받을어음") or (k in (108, 110) and not name)):
            ar += amt
    facts = [_fact(f"시산표 합계 {_won(total)}({'차대 일치' if abs(total) < 0.5 else '차대 불일치'})", total, sheet),
             _fact(f"계정 수 {len(rows)}개", len(rows), sheet),
             _fact(f"매출액 {_won(-sales)}", -sales, sheet),
             _fact(f"매출채권 {_won(ar)}", ar, sheet),
             _fact(f"자산총계 {_won(assets)}", assets, sheet),
             _fact(f"부채총계 {_won(liab)}", liab, sheet),
             # 마감 전 시산표라 자본 계정에 당기 손익이 아직 없다. 재무상태표 자본총계와 맞추려고 손익 계정 순액을 더한 값이다
             _fact(f"자본총계(손익 계정 순액 포함) {_won(equity + pl)}", equity + pl, sheet),
             _fact(f"손익 계정 순액(대변 +) {_won(pl)}", pl, sheet)]
    asof = _asof(above)
    if asof:
        facts.insert(0, _fact(f"{ASOF_FACT}{asof.isoformat()}", None, sheet))
    return facts


def _read_tb(path: Path, fy_end=None) -> list[dict]:
    got = tb_table(path)
    if got:
        return _tb_facts(got["rows"], got["sheet"], got["above"])
    fs = fs_accounts(path)                    # 시산표가 아니면 계정 단위 재무제표로 읽는다(R8, 진단 #4)
    if not fs:
        return []
    return _fs_facts(fs)


def _asof(rows) -> date | None:
    for r in rows:
        for v in r:
            if isinstance(v, (datetime, date)):
                return _date(v)
            if isinstance(v, str):
                m = re.search(r"(20\d\d)\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", v)
                if m:
                    try:
                        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    except ValueError:
                        pass
    return None


def tb_rows(path: Path) -> dict | None:
    """시산표 한 파일의 계정 행. {"rows": [{code, name, line, amount}], "sheet", "column"} (차변 +, 대변 −).
    금액 열은 당기 · 잔액 · 금액(또는 차변잔액 − 대변잔액)이고, 없으면 전기 열을 읽는다(전기 시산표만 따로 받은 파일).
    line 은 표시과목 열 값이고, 열이 없으면 계정명이다."""
    got = tb_table(Path(path))
    if not got:
        return prior_columns(Path(path))
    rows = [dict(r, line=r["line"] or r["name"]) for r in got["rows"]]
    return {"rows": rows, "sheet": got["sheet"], "column": got["column"]}


def prior_columns(path: Path) -> dict | None:
    """비교식 시산표(당기 · 전기 두 열)의 전기 열. {"rows": [{code, name, line, amount}], "sheet", "column"} 없으면 None.
    전기 열 이름: 전기 · 전기말 · 전기잔액 · 전기금액, 또는 전기차변(잔액) − 전기대변(잔액)."""
    path = Path(path)
    tabs = _tables(path, [["code"], ["name"], ["prior", "prior_dr"]], ["line", "prior_cr"])
    if not tabs:
        return None
    sheet, c, rows, _, headers = tabs[0]
    out = []
    for r in rows:
        code = _code(_cell(r, c["code"]))
        if code is None:
            continue
        if "prior" in c:
            v = _num(_cell(r, c["prior"]))
            amt = 0.0 if v is None else v
        else:
            amt = (_num(_cell(r, c["prior_dr"])) or 0.0) - (_num(_cell(r, c.get("prior_cr"))) or 0.0)
        name = _norm(_cell(r, c["name"]))
        line = _norm(_cell(r, c.get("line"))) if "line" in c else ""
        out.append({"code": code, "name": name, "line": line or name, "amount": _int(amt)})
    col = headers[c["prior"]] if "prior" in c else "전기차변 − 전기대변"
    return {"rows": out, "sheet": sheet, "column": col} if out else None


# ---------------------------------------------------------------- 계정 단위 재무제표(R8, 진단 #4)
ROMAN_PREFIX = re.compile(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\s*[.．]?\s*")
NUM_PREFIX = re.compile(r"^\s*(?:\(\s*\d+\s*\)|\d+\s*[.．])\s*")
FS_SECTIONS = ("자산", "부채", "자본")
FS_TOTALS = {"자산총계", "부채총계", "자본총계", "부채와자본총계", "부채및자본총계", "부채와자본의총계"}
FS_CALCS = {"매출총이익", "매출총손실", "영업이익", "영업손실", "법인세비용차감전순이익", "법인세비용차감전순손실", "법인세차감전순이익",
            "법인세차감전순손실", "당기순이익", "당기순손실", "영업외손익"}
# 자본에서 차변 성격인 계정(일반기업회계기준 자본조정 차감 항목과 결손금), 자산에서 대변 성격인 차감 계정
EQUITY_DEBIT = ("결손금", "자기주식", "주식할인발행차금", "감자차손", "처분손실")
CONTRA_ASSET = ("대손충당금", "누계액", "현재가치할인차금", "정부보조금")


def _fs_header(rows):
    """재무제표 머리줄: '과목' 칸과 당기 칸. (머리줄 행, 과목 열, 당기 열들, 전기 열들) 또는 None."""
    for hi, r in enumerate(rows[:HEADER_SCAN]):
        cells = [_norm(v) for v in r]
        lab = next((j for j, x in enumerate(cells) if x in ("과목", "계정과목")), None)
        if lab is None:
            continue
        heads = [(j, re.sub(r"\s+", "", str(r[j]))) for j in range(lab + 1, len(r)) if isinstance(r[j], str) and r[j].strip()]
        cur = next((j for j, h in heads if "(당)" in h or "당기" in h), None)
        pri = next((j for j, h in heads if "(전)" in h or "전기" in h), None)
        if cur is None:
            nums = [(int(m.group(1)), j) for j, h in heads if (m := re.match(r"제(\d+)기", h))]
            if len(nums) >= 2:
                cur, pri = max(nums)[1], min(nums)[1]
            elif heads:
                cur = heads[0][0]
        if cur is None:
            continue
        text = dict(heads)
        first = lambda j: min(k for k, h in heads if h == text[j] and k <= j)  # noqa: E731  같은 머리의 가장 왼쪽 칸
        cur = first(cur)
        pri = first(pri) if pri is not None else None

        def span(start):
            # 병합 칸을 풀어 저장한 출력물은 같은 머리 글자가 옆 칸에도 있다(「제 11 (당)기 | 제 11 (당)기」). 같은 글자는 한 기의 두 칸이다
            stops = sorted(j for j, h in heads if j > start and h != text[start])
            return list(range(start, stops[0] if stops else start + 2))[:2]

        cur_cols = span(cur)
        pri_cols = span(pri) if pri is not None else []
        return hi, lab, cur_cols, pri_cols
    return None


def _fs_lines(rows, lab: int, cols: list[int]) -> list[tuple]:
    """(종류, 이름, 금액, 들여쓰기). 종류: section · total · h1 · h2 · acct."""
    seq = []
    for r in rows:
        raw = _cell(r, lab)
        if not isinstance(raw, str) or not raw.strip():
            continue
        if ":" in raw or re.fullmatch(r"\s*\(.*\)\s*", raw):     # 「당기 : …」 메모, 「( 당 기 순 손 실 )」
            continue
        vals = [_num(_cell(r, j)) for j in cols]
        inner = vals[0] if vals else None
        outer = vals[-1] if len(vals) > 1 else None
        # 빈 칸을 0 으로 채운 출력물이 있다. 한 칸만 0 이 아니면 그 칸이 금액이다
        if inner == 0 and outer:
            inner = None
        elif outer == 0 and inner:
            outer = None
        indent = len(raw) - len(raw.lstrip(" "))
        if ROMAN_PREFIX.match(raw):
            level, text = 1, ROMAN_PREFIX.sub("", raw)
        elif NUM_PREFIX.match(raw):
            level, text = 2, NUM_PREFIX.sub("", raw)
        else:
            level, text = 0, raw
        key = _norm(re.sub(r"\(주석[^)]*\)|\(주\s*[\d,\s]+\)", "", text))
        if not key:
            continue
        if level == 0 and key in FS_SECTIONS:
            seq.append(("section", key, None, indent))
        elif key in FS_TOTALS or key in FS_CALCS:
            seq.append(("total", key, outer if outer is not None else inner, indent))
        elif level:
            seq.append((f"h{level}", key, outer if outer is not None else inner, indent))
        else:
            seq.append(("acct", key, inner if inner is not None else outer, indent))
    return seq


def _fs_items(seq: list[tuple], stmt: str) -> list[dict]:
    """계정 줄. 아래에 계정 줄이 없는 제목 줄에 금액이 있으면 그 제목 줄이 계정이다(예: Ⅸ. 법인세비용).
    같은 제목 아래에서 들여쓰기가 더 깊은 줄은 계산 내역(기초 재고 · 당기 매입 등)이라 뺀다."""
    items = []
    section, h1, h2 = ("자산" if stmt == "bs" else None), None, None
    for i, (kind, key, v, ind) in enumerate(seq):
        if kind == "section":
            section, h1, h2 = key, None, None
        elif kind == "total":
            h2 = None
            if stmt == "is":
                h1 = None
        elif kind in ("h1", "h2"):
            if kind == "h1":
                h1, h2 = key, None
            else:
                h2 = key
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            leaf = nxt is None or (nxt[0] != "acct" and not (kind == "h1" and nxt[0] == "h2"))
            if leaf and v not in (None, 0):
                items.append({"name": key, "section": section, "h1": h1, "heading": key, "value": v, "indent": -1})
        else:
            items.append({"name": key, "section": section, "h1": h1, "heading": h2 or h1, "value": v, "indent": ind})
    groups: dict = {}
    for it in items:
        groups.setdefault((it["section"], it["h1"], it["heading"]), []).append(it)
    drop = set()
    for g in groups.values():
        lv = min((x["indent"] for x in g if x["indent"] >= 0), default=-1)
        drop |= {id(x) for x in g if x["indent"] >= 0 and x["indent"] != lv}
    return [x for x in items if id(x) not in drop and x["value"] is not None]


def _fs_group(stmt: str, it: dict) -> tuple[str, int]:
    """(재무제표 묶음, 시산표 부호). 묶음 이름은 report_fs.yaml groups 의 key 와 같다."""
    name, h1 = it["name"], it.get("h1") or it["heading"] or ""
    if stmt == "bs":
        sec = it["section"] or "자산"
        if sec == "자산":
            return ("비유동자산" if "비유동" in h1 else "유동자산"), (-1 if any(k in name for k in CONTRA_ASSET) else 1)
        if sec == "부채":
            return ("비유동부채" if "비유동" in h1 else "유동부채"), -1
        return "자본", (1 if any(k in name for k in EQUITY_DEBIT) else -1)
    if "원가" in h1:
        return "매출원가", 1
    if "외수익" in h1:
        return "영업외수익", -1
    if "외비용" in h1:
        return "영업외비용", 1
    if "법인세" in h1:
        return "법인세비용", 1
    if h1 in ("매출액", "매출", "영업수익") or h1.endswith("수익"):
        return "매출액", -1
    return "판매비와관리비", 1


def fs_layout(path: Path) -> dict | None:
    """공시 재무제표 엑셀의 **순서와 계층을 그대로** 돌려준다(2026-10-08).

    fs_accounts 는 계정 줄만 남기고 계층을 버린다. 공시 꼴 재무제표를 만들려면 소계 · 합계 줄과 과목 순서가 필요하다.

      {"sheets": [{"sheet", "stmt", "rows": [{kind, label, level, indent, cur, prior, contra_of}]}]}
        kind     section · h1 · h2 · acct · total
        cur      당기 금액(시산표 부호 아님. 공시에 적힌 값 그대로)
        prior    전기 금액. 전기 열이 없으면 None
        contra_of  바로 위 과목의 차감 짝이면 그 과목 이름(대손충당금 · 감가상각누계액 등)

    차감 짝은 이름(CONTRA_ASSET)으로 가린다. 공시 BS 는 위 과목과 차감 과목을 안쪽 칸에 쓰고 순액을 바깥 칸에 쓴다.
    """
    path = Path(path)
    if path.suffix.lower() not in EXCEL:
        return None
    wb = _open(path)
    out = []
    try:
        for ws in wb.worksheets:
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            h = _fs_header(rows[:HEADER_SCAN])
            if h is None:
                continue
            hi, lab, cur_cols, pri_cols = _fs_header(rows)
            body = rows[hi + 1:]
            cur = _fs_lines(body, lab, cur_cols)
            # 전기 열은 같은 행에서 오므로 _fs_lines 가 거르는 행도 같다. 이름으로 맞추면 같은 이름 두 줄(대손충당금)이 섞인다
            pri = _fs_lines(body, lab, pri_cols) if pri_cols else []
            if len(pri) != len(cur):
                pri = []
            keys = {x[1] for x in cur}
            stmt = "bs" if ("자산총계" in keys or "자산" in keys) else "is"
            seq, last_acct = [], None
            for i, (kind, key, v, ind) in enumerate(cur):
                contra = None
                if kind == "acct" and last_acct and any(k in key for k in CONTRA_ASSET):
                    contra = last_acct
                elif kind == "acct":
                    last_acct = key
                seq.append({"kind": kind, "label": key, "level": {"h1": 1, "h2": 2}.get(kind, 0), "indent": ind,
                            "cur": _int(v) if v is not None else None,
                            "prior": _int(pri[i][2]) if pri and pri[i][2] is not None else None,
                            "contra_of": contra})
            if any(x["kind"] == "acct" for x in seq):
                out.append({"sheet": ws.title, "stmt": stmt, "rows": seq})
    finally:
        wb.close()
    return {"sheets": out} if out else None


def fs_accounts(path: Path) -> dict | None:
    """계정 단위 재무제표 엑셀(과목 · 제 n (당)기 · 제 n-1 (전)기, 기마다 안쪽 · 바깥 두 칸)의 당기 계정 줄.
    {"sheets": [{"sheet", "stmt", "items": [{name, group, amount, heading}], "totals"}]}. 코드는 없다(figures 가 붙인다).
    금액은 시산표 부호(차변 +)다. 계정 줄은 안쪽 칸이 먼저, 비면 바깥 칸. 묶음 · 합계 줄과 계산 내역 줄은 뺀다."""
    path = Path(path)
    if path.suffix.lower() not in EXCEL:
        return None
    wb = _open(path)
    out = []
    try:
        for ws in wb.worksheets:
            if _fs_header([tuple(r) for r in ws.iter_rows(values_only=True, max_row=HEADER_SCAN)]) is None:
                continue
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            h = _fs_header(rows)
            hi, lab, cur_cols, _ = h
            seq = _fs_lines(rows[hi + 1:], lab, cur_cols)
            keys = {x[1] for x in seq}
            stmt = "bs" if ("자산총계" in keys or "자산" in keys) else "is"
            items = []
            for it in _fs_items(seq, stmt):
                g, sign = _fs_group(stmt, it)
                items.append({"name": it["name"], "group": g, "amount": _int(sign * it["value"]), "heading": it["heading"]})
            if items:
                out.append({"sheet": ws.title, "stmt": stmt, "items": items, "totals": {k: v for t, k, v, _ in seq if t == "total"}})
    finally:
        wb.close()
    return {"sheets": out} if out else None


# ---------------------------------------------------------------- 계정과목표(2026-10-09)
def coa_table(path: Path) -> dict | None:
    """회사 계정과목표의 상위 계정 연결. {"rows": [{code, name, parent, group}], "sheet", "column"}.

    더존 계정과목표는 하위 계정(보통예금 10301 · 외화예금 10302)의 `LINK_CD` 에 상위 계정 코드(제예금 10300)를 둔다.
    맨 위 계정의 `LINK_CD` 는 계정그룹 코드(1110 당좌자산)라 표에 계정으로 없다. 그런 값은 상위 계정이 아니므로 parent 를 비운다.
    금액 열이 있는 표(시산표 · 분개장)는 계정과목표로 보지 않는다."""
    path = Path(path)
    if path.suffix.lower() not in EXCEL:
        return None
    for sheet, c, rows, _, headers in _tables(path, [["code"], ["name"], ["parent"]], ["acc_group"],
                                              reject=("cur", "dr_bal", "dr", "date")):
        out = []
        for r in rows:
            code = _code(_cell(r, c["code"]))
            if code is None:
                continue
            parent = _code(_cell(r, c["parent"]))
            out.append({"code": str(code), "name": _norm(_cell(r, c["name"])), "parent": None if parent is None else str(parent),
                        "group": _norm(_cell(r, c.get("acc_group"))) if "acc_group" in c else "",
                        "full": re.sub(r"\s+", "", str(_cell(r, c["name"]) or ""))})
        codes = {x["code"] for x in out}
        for x in out:
            if x["parent"] not in codes or x["parent"] == x["code"]:
                x["parent"] = None
        # 하위 계정이 없는 평평한 계정과목표(LINK_CD 가 모두 계정그룹 코드)도 코드 원천이다(2026-10-19 가상 회사 세트).
        # 다른 표를 계정과목표로 잘못 읽지 않게, 상위 연결이 없으면 계정그룹 열이 있고 계정이 열 개 이상일 때만 받는다
        if out and (any(x["parent"] for x in out) or ("acc_group" in c and len(out) >= 10)):
            return {"rows": out, "sheet": sheet, "column": headers[c["parent"]]}
    return None


def _fs_facts(fs: dict) -> list[dict]:
    facts = []
    for s in fs["sheets"]:
        sheet = s["sheet"]
        title = "재무상태표" if s["stmt"] == "bs" else "손익계산서"
        facts.append(_fact(f"{title}(계정 단위) 계정 수 {len(s['items'])}개", len(s["items"]), sheet))
        if s["stmt"] == "bs":
            for k in ("자산총계", "부채총계", "자본총계"):
                if s["totals"].get(k) is not None:
                    facts.append(_fact(f"{k} {_won(s['totals'][k])}", s["totals"][k], sheet))
        else:
            sales = -sum(x["amount"] for x in s["items"] if x["group"] == "매출액")
            facts.append(_fact(f"매출액 {_won(sales)}", sales, sheet))
    return facts


# ---------------------------------------------------------------- 분개장
JOURNAL_OPT = ["code", "name", "voucher", "row", "memo", "party"]
JOURNAL_EXTRA = ("입력구분", "전표구분", "입력방법", "작성구분", "작성자", "입력자", "승인자")
# 분개장 꼴. 같은 머리줄에서 앞의 꼴이 먼저다(두 계정 칸 꼴은 차변금액 · 대변금액 열도 있어 한 줄 한 계정 꼴보다 먼저 본다)
JOURNAL_FORMS = (("두 계정 칸", [["dr_acc"], ["cr_acc"], ["dr"], ["cr"]]),
                 ("차변 · 대변 열", [["dr"], ["cr"]]),
                 ("금액 · 차대 구분", [["side"], ["amount"]]),
                 ("차변-대변 한 열", [["signed"]]))
SIDE_DR = {"차", "차변", "借", "D", "DR"}
SIDE_CR = {"대", "대변", "貸", "C", "CR"}
_JCACHE: dict = {}


def _jkey(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def journal_tables(path: Path) -> list[dict]:
    """분개장 시트마다 머리줄 · 꼴. [{"sheet", "form", "cols", "rows", "above", "headers"}]. 일자는 한 열(일자 · 년/월/일 ·
    승인일 등)이거나 년 · 월 · 일 세 열이다(R8). 마지막으로 읽은 파일 하나는 기억해 두고 다시 열지 않는다."""
    path = Path(path)
    key = _jkey(path)
    if key is None:
        return []
    if key in _JCACHE:
        return _JCACHE[key]["tabs"]
    wb = _open(path)
    out = []
    try:
        for ws in wb.worksheets:
            hit = _journal_header(ws.title, [tuple(r) for r in ws.iter_rows(values_only=True, max_row=HEADER_SCAN + 1)])
            if hit:
                rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
                n = len(hit["above"])
                hit.update(rows=rows[n + 1:], above=rows[:n])
                out.append(hit)
    finally:
        wb.close()
    _JCACHE.clear()
    _JCACHE[key] = {"tabs": out, "lines": None}
    return out


def _journal_header(sheet: str, rows) -> dict | None:
    for hi in range(min(HEADER_SCAN, len(rows))):
        for headers in _header_candidates(rows, hi):
            for date_req in ([["date"]], [["year"], ["mon"], ["day"]]):
                # 계정 열 이름이 둘 다 「계정과목」 이고 금액 열이 차변금액 · 대변금액이면 두 계정 칸 꼴이다.
                # 차변금액 옆 계정 칸이 차변, 대변금액 옆 계정 칸이 대변이다
                accs = [j for j, h in enumerate(headers) if h in ("계정과목", "계정명", "계정", "과목")]
                if len(accs) == 2:
                    cols = _match(headers, date_req + [["dr"], ["cr"]], ["voucher", "row", "memo", "party"])
                    if cols is not None and cols["dr"] < cols["cr"]:
                        cols.update(dr_acc=min(accs, key=lambda j: abs(j - cols["dr"])), cr_acc=min(accs, key=lambda j: abs(j - cols["cr"])))
                        if cols["dr_acc"] != cols["cr_acc"]:
                            return {"sheet": sheet, "form": "두 계정 칸", "cols": cols, "rows": rows[hi + 1:], "above": rows[:hi],
                                    "headers": headers}
                for form, req in JOURNAL_FORMS:
                    cols = _match(headers, date_req + req, JOURNAL_OPT)
                    if cols is None:
                        continue
                    if form != "두 계정 칸" and "code" not in cols and "name" not in cols and form != "차변 · 대변 열":
                        continue
                    return {"sheet": sheet, "form": form, "cols": cols, "rows": rows[hi + 1:], "above": rows[:hi], "headers": headers}
    return None


def _jdate(r, c):
    if "date" in c:
        return _date(_cell(r, c["date"]))
    y, m, dd = (_num(_cell(r, c[k])) for k in ("year", "mon", "day"))
    try:
        return date(int(y), int(m), int(dd)) if None not in (y, m, dd) else None
    except ValueError:
        return None


def journal_rows(path: Path) -> list[dict]:
    """분개장 한 파일의 계정 줄 전부. [{sheet, i, date, dr, cr, code(문자열|None), name, voucher, row, memo, party, extra}]
    꼴(R8): 차변 · 대변 열(한 줄 한 계정), 두 계정 칸(한 행을 차변 줄 · 대변 줄로 펼친다, 계정은 '[코드]이름'),
    금액 · 차대 구분 열, 차변-대변 한 열. 합계 · 소계 행과 일자가 없는 행은 뺀다."""
    path = Path(path)
    tabs = journal_tables(path)
    key = _jkey(path)
    if key in _JCACHE and _JCACHE[key]["lines"] is not None:
        return _JCACHE[key]["lines"]
    out = []
    for t in tabs:
        c, form, sheet = t["cols"], t["form"], t["sheet"]
        extra_i = {h: i for i, h in enumerate(t["headers"]) if h in JOURNAL_EXTRA}
        for i, r in enumerate(t["rows"]):
            dt = _jdate(r, c)
            if dt is None or _is_total_row(r, loose=False):
                continue
            g = lambda k: _cell(r, c[k]) if k in c else None  # noqa: E731
            vno, party, memo = g("voucher"), g("party"), g("memo")
            base = {"sheet": sheet, "i": i, "date": dt, "voucher": None if vno in (None, "") else str(vno).strip(),
                    "row": _num(g("row")), "memo": None if memo in (None, "") else str(memo).strip(),
                    "party": None if party in (None, "") else str(party).strip(),
                    "extra": {h: _cell(r, j) for h, j in extra_i.items()}}
            sides = []
            if form == "두 계정 칸":
                for acc_k, amt_k in (("dr_acc", "dr"), ("cr_acc", "cr")):
                    acc, amt = g(acc_k), _num(g(amt_k))
                    if acc in (None, "") or not amt:
                        continue
                    code, name = name_code(acc)
                    sides.append((code, name, amt if amt_k == "dr" else 0.0, amt if amt_k == "cr" else 0.0))
            else:
                code = _code(g("code")) if "code" in c else None
                name = _norm(g("name")) if "name" in c else ""
                if code is None and "name" in c:
                    code2, name2 = name_code(g("name"))
                    if code2 is not None:
                        code, name = code2, name2
                if form == "차변 · 대변 열":
                    dr, cr = _num(g("dr")) or 0.0, _num(g("cr")) or 0.0
                elif form == "금액 · 차대 구분":
                    amt, side = _num(g("amount")) or 0.0, re.sub(r"\s+", "", str(g("side") or "")).upper()
                    if side in SIDE_DR:
                        dr, cr = amt, 0.0
                    elif side in SIDE_CR:
                        dr, cr = 0.0, amt
                    else:
                        continue
                else:
                    v = _num(g("signed")) or 0.0
                    dr, cr = (v, 0.0) if v >= 0 else (0.0, -v)
                sides.append((code, name, dr, cr))
            for code, name, dr, cr in sides:
                out.append(dict(base, code=None if code is None else str(code), name=name, dr=dr, cr=cr))
    if key in _JCACHE:
        _JCACHE[key]["lines"] = out
    return out


def _journal(path: Path):
    """분개장 시트를 모두 모은다. (머리줄 표들, [(시트, 일자, 차변, 대변, 거래처, 전표번호, 계정코드)])
    머리줄 표는 _tables 와 같은 (시트, 열, 아래 행들, 위 행들, 머리줄 이름들) 꼴이다."""
    tabs = journal_tables(Path(path))
    lines = journal_rows(Path(path))
    out = [(x["sheet"], x["date"], x["dr"], x["cr"], x["party"], x["voucher"], None if x["code"] is None else int(x["code"]))
           for x in lines]
    return [(t["sheet"], t["cols"], t["rows"], t["above"], t["headers"]) for t in tabs], out


def _period_str(first: date, last: date) -> str:
    if first.year == last.year and first.month == 1 and last.month == 12:
        return str(first.year)
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.year}-{first.month:02d}"
    return f"{first.year}-{first.month:02d}~{last.year}-{last.month:02d}"


def _read_journal(path: Path, fy_end=None) -> list[dict]:
    tabs, lines = _journal(path)
    if not tabs or not lines:
        return []
    sheet = tabs[0][0] if len(tabs) == 1 else None
    dr = sum(x[2] for x in lines)
    cr = sum(x[3] for x in lines)
    first, last = min(x[1] for x in lines), max(x[1] for x in lines)
    parties = {x[4] for x in lines if x[4]}
    facts = [_fact(f"{PERIOD_FACT}{first.isoformat()} ~ {last.isoformat()}", None, sheet),
             _fact(f"행 수 {len(lines):,}행", len(lines), sheet)]
    vouchers = {(x[1], x[5]) for x in lines if x[5]}
    if vouchers:
        facts.append(_fact(f"전표 수 {len(vouchers):,}건", len(vouchers), sheet))
    facts += [_fact(f"차변 합계 {_won(dr)}", dr, sheet),
              _fact(f"대변 합계 {_won(cr)}", cr, sheet),
              _fact(f"차대 차이 {_won(dr - cr)}", dr - cr, sheet),
              _fact(f"거래처 수 {len(parties)}곳", len(parties), sheet)]
    # 매출(더존 401~430): 대변 순액과, 매출 계정 차변(취소 · 환입)
    sales = [x for x in lines if x[6] is not None and 401 <= (x[6] if x[6] < 1000 else int(str(x[6])[:3])) <= 430]
    if sales:
        net = sum(x[3] - x[2] for x in sales)
        facts.append(_fact(f"매출 순액 {_won(net)}", net, sheet))
        back = sum(x[2] for x in sales)
        if back:
            facts.append(_fact(f"매출 차변 합계(취소 · 환입) {_won(back)}", back, sheet))
    return facts


def journal_parties(path: Path) -> set[str]:
    return {x[4] for x in _journal(Path(path))[1] if x[4]}


def period_from_journal(path: Path) -> str | None:
    lines = _journal(Path(path))[1]
    if not lines:
        return None
    return _period_str(min(x[1] for x in lines), max(x[1] for x in lines))


def journal_range(facts: list[dict]) -> tuple[date, date] | None:
    for f in facts:
        if f.get("basis") == "엔진" and f["text"].startswith(PERIOD_FACT):
            m = re.findall(r"\d{4}-\d{2}-\d{2}", f["text"])
            if len(m) == 2:
                return date.fromisoformat(m[0]), date.fromisoformat(m[1])
    return None


def period_from_facts(facts: list[dict], kind: str | None = None) -> str | None:
    """엔진 사실에 기간(분개장) · 기준일이 있으면 문서목록 period 를 만든다.
    시산표는 회계연도(12월 결산이면 2025), 그 밖의 명세서는 기준일 그대로(2025-12-31)."""
    rng = journal_range(facts)
    if rng:
        return _period_str(*rng)
    if kind == PAYROLL:              # 월별 급여 합계 사실(「2026-01 급여 합계」)의 첫 달 ~ 끝 달(2026-10-19, 1 ~ 9월 급여대장을 1월분으로 봤다)
        ms = sorted(m.group(1) for f in facts if (m := re.match(r"^(\d{4}-\d{2}) 급여 합계", f.get("text", ""))))
        if ms:
            y1, m1 = (int(x) for x in ms[0].split("-"))
            y2, m2 = (int(x) for x in ms[-1].split("-"))
            return _period_str(date(y1, m1, 1), date(y2, m2, monthrange(y2, m2)[1]))
    for f in facts:
        if f.get("basis") == "엔진" and f["text"].startswith(ASOF_FACT):
            d = date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", f["text"]).group(0))
            if kind not in (TB, None):
                return d.isoformat()
            return str(d.year) if d.month == 12 else f"{d.year}-{d.month:02d}"
    return None


# ---------------------------------------------------------------- 명세서
BUCKET_RE = re.compile(r"^\d+일이내$|^\d+~\d+일$|^\d+일(?:초과|이상)$")


def asof_tabs(tabs: list, fy_end) -> list:
    """결산일 기준표만 남긴다(2026-10-16, Roll-Rate 용 분기 연령표가 함께 들어올 때).
    머리줄 위에 기준일이 있고 결산일과 다른 표는 뺀다. 기준일이 결산일인 표를 앞에, 기준일이 없는 표는 그 뒤에 둔다.
    fy_end 가 없으면 그대로 둔다."""
    if not fy_end:
        return list(tabs)
    fy = _date(fy_end)
    hit, plain = [], []
    for t in tabs:
        a = _asof(t[3])
        if a is None:
            plain.append(t)
        elif a == fy:
            hit.append(t)
    return hit + plain


def _read_aging(path: Path, fy_end=None) -> list[dict]:
    tabs = asof_tabs(_tables(path, [["ar_total"]], ["over90", "party"]), fy_end)
    if not tabs:
        return []
    sheet, c, rows, above, hdr = tabs[0]
    total = over = 0.0
    n = 0
    buckets = {}
    for i, h in enumerate(hdr):
        if BUCKET_RE.match(h) and i != c.get("over90"):
            buckets[i] = (h, 0.0)
    for r in rows:
        if _is_total_row(r):
            continue
        v = _num(_cell(r, c["ar_total"]))
        if v is None:
            continue
        n += 1
        total += v
        if "over90" in c:
            over += _num(_cell(r, c["over90"])) or 0.0
        for i, (h, s) in buckets.items():
            buckets[i] = (h, s + (_num(_cell(r, i)) or 0.0))
    facts = [_fact(f"연령분석표 합계 {_won(total)}", total, sheet), _fact(f"거래처 수 {n}곳", n, sheet)]
    for h, s in buckets.values():
        facts.append(_fact(f"{h} {_won(s)}", s, sheet))
    if "over90" in c:
        facts.append(_fact(f"90일 초과 {_won(over)}", over, sheet))
    asof = _asof(above)
    if asof:
        facts.insert(0, _fact(f"{ASOF_FACT}{asof.isoformat()}", None, sheet))
    return facts


def _month_key(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return f"{v.year}-{v.month:02d}"
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 12:
        return f"{int(v)}월"
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4})[-./년]\s*(\d{1,2})월?", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})\s*월?", s)
    return f"{int(m.group(1))}월" if m and 1 <= int(m.group(1)) <= 12 else (s or None)


def _payroll_wide(path: Path):
    """가로형 급여대장: 사람마다 한 행, 1월 ~ 12월 열. 찾으면 (시트, 행들, {열: 월}, 미지급 열)"""
    wb = _open(path)
    try:
        for ws in wb.worksheets:
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            for hi, row in enumerate(rows[:HEADER_SCAN]):
                months = {i: int(m.group(1)) for i, h in enumerate(row)
                          if (m := re.fullmatch(r"(\d{1,2})월", _norm(h))) and 1 <= int(m.group(1)) <= 12}
                if len(months) >= 2:
                    return ws.title, rows[hi + 1:], months, _find_col([_norm(h) for h in row], "unpaid")
    finally:
        wb.close()
    return None


def _read_payroll(path: Path, fy_end=None) -> list[dict]:
    total = unpaid = 0.0
    by_month: dict[str, float] = {}
    wide = _payroll_wide(path)
    if wide:
        sheet, rows, months, unpaid_i = wide
        c, heads = {}, {}
        for r in rows:
            if _is_total_row(r):
                continue
            for i, mo in months.items():
                v = _num(_cell(r, i))
                if v is not None:
                    total += v
                    by_month[f"{mo}월"] = by_month.get(f"{mo}월", 0.0) + v
            if unpaid_i is not None:
                unpaid += _num(_cell(r, unpaid_i)) or 0.0
        has_unpaid = unpaid_i is not None
    else:
        tabs = _tables(path, [["pay"]], ["month", "emp", "unpaid", "heads"])
        if not tabs:
            return []
        # 달마다 시트를 둔 급여대장(시트 「2026-01」 · 「1월」, 월 열 없음)은 모든 달 시트를 더하고 시트 이름을 월로 쓴다.
        # 첫 시트만 읽어 9개월 급여대장이 한 달 합계가 됐다(2026-10-19 가상 회사 세트)
        monthly = [t for t in tabs if "month" not in t[1] and _sheet_month(t[0])]
        use = monthly if len(monthly) >= 2 else tabs[:1]
        sheet = use[0][0] if len(use) == 1 else f"{use[0][0]} ~ {use[-1][0]}"
        heads: dict[str, set | float] = {}
        has_unpaid = any("unpaid" in t[1] for t in use)
        c = use[0][1]
        for tab_sheet, c, rows, _, _ in use:
            sheet_k = _sheet_month(tab_sheet) if len(use) > 1 else None
            for r in rows:
                if _is_total_row(r):
                    continue
                v = _num(_cell(r, c["pay"]))
                if v is None:
                    continue
                total += v
                if "unpaid" in c:
                    unpaid += _num(_cell(r, c["unpaid"])) or 0.0
                elif _is_unpaid_row(r):
                    # 미지급 열이 없고 '미지급' 이라고 적힌 행(연말 성과급 계상 등): 지급 월별 합에서 빼고 미지급으로 모은다
                    unpaid += v
                    has_unpaid = True
                    continue
                k = _month_key(_cell(r, c["month"])) if "month" in c else sheet_k
                if k:
                    by_month[k] = by_month.get(k, 0.0) + v
                    if "heads" in c:
                        heads[k] = max(heads.get(k, 0.0), _num(_cell(r, c["heads"])) or 0.0)
                    elif "emp" in c and _cell(r, c["emp"]):
                        heads.setdefault(k, set()).add(str(_cell(r, c["emp"])).strip())
        if heads:
            n = max(len(x) if isinstance(x, set) else x for x in heads.values())
            by_month_heads = _fact(f"월 인원 최대 {_int(n)}명", n, sheet)
    facts = [_fact(f"급여 연간 합계 {_won(total)}", total, sheet)]
    if has_unpaid and not wide and "unpaid" not in c:
        facts.append(_fact(f"지급 합계 {_won(total - unpaid)}", total - unpaid, sheet))
    for k in sorted(by_month, key=_month_sort):
        facts.append(_fact(f"{k} 급여 합계 {_won(by_month[k])}", by_month[k], sheet))
    if has_unpaid:
        facts.append(_fact(f"미지급 {_won(unpaid)}", unpaid, sheet))
    if not wide and heads:
        facts.append(by_month_heads)
    return facts


def _sheet_month(name: str) -> str | None:
    """시트 이름의 연월(「2026-01」 · 「2026년 1월」 · 「202601」 → 2026-01, 「1월」 · 「1월분」 → 1월). 아니면 None."""
    s = str(name or "").strip()
    m = re.fullmatch(r"(\d{4})\s*[-./년_]?\s*(\d{1,2})\s*월?(분)?", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})\s*월(분)?", s)
    return f"{int(m.group(1))}월" if m and 1 <= int(m.group(1)) <= 12 else None


def _is_unpaid_row(row) -> bool:
    return any(isinstance(v, str) and re.sub(r"[\s\[\]<>()]", "", v) in ("미지급", "미지급분", "미지급금", "미지급계상") for v in row)


def _month_sort(k: str):
    m = re.fullmatch(r"(\d{4})-(\d{2})", k)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"(\d{1,2})월", k)
    return (0, int(m.group(1))) if m else (9999, k)


FIXED_OPT = ["asset", "acq_date", "acq_cur", "dep_cur", "dep_end", "acq_beg", "acq_end", "book_end", "fa_acct"]
INTANGIBLE_PREFIX = "무형자산 "          # 무형자산 명세(상각비 명세 · 대장)의 사실 앞말. 유형자산 사실과 섞이지 않게 한다(2026-10-18)
DISPOSAL_SHEET = ("매각", "처분", "폐기", "실사", "요약")


def _yymm_in(name: str) -> set[str]:
    """시트 이름 속 기준 연월(「2412_자산대장」 · 「자산매각_241231」 → {'2412'})."""
    return {m[:4] for m in re.findall(r"(?<!\d)(\d{4}(?:\d{2})?)(?!\d)", name) if 1 <= int(m[2:4]) <= 12}


def fixed_table(path: Path, fy_end=None):
    """고정자산대장 · 상각비 명세에서 자산별 표 하나(시트, 열, 행들, 위 행들, 머리줄). 없으면 None.
    꼴 둘: 취득가(취득원가) 열이 있는 대장, 기초가액 · 당기증가 · 당기감소 · 기말잔액 변동 꼴(기말잔액이 기말 취득가액).
    표가 여럿이면(월별 · 연도별 시트) 기준일이 결산일인 표, 시트 이름 연월이 결산 연월인 표, 매각 · 실사 · 요약이 아닌 표,
    맞은 열이 많은 표 순으로 하나를 고른다."""
    tabs = [t for t in _tables(Path(path), [["acq_cost", "acq_end"]], FIXED_OPT) if "acq_cost" in t[1] or "acq_beg" in t[1]]
    if not tabs:
        return None
    fy = _date(fy_end) if fy_end else None
    want = f"{fy.year % 100:02d}{fy.month:02d}" if fy else None

    def rank(t):
        sheet, c, rows, above, _ = t
        a = _asof(above)
        names = _yymm_in(sheet)
        if fy and a == fy:
            when = 0
        elif want and want in names:
            when = 1
        elif (a is None and not names) or not fy:
            when = 2
        else:
            when = 3
        # 매각 · 실사 · 요약 시트는 날짜가 맞아도 본 대장 뒤다. 「자산매각_251231」 이 결산 연월을 이름에 달고 있어
        # 본 대장 「유형자산」 보다 먼저 골라졌다(2026-10-19 가상 회사 세트, 실제 회사 자료 산출내역과 같은 시트 구성)
        return (any(k in sheet for k in DISPOSAL_SHEET), when, -len(c), -len(rows))

    return min(tabs, key=rank)


def _total_label(v) -> bool:
    """과목 · 자산 이름 칸이 소계 · 합계 줄 이름인지(길이와 상관없이 끝이 소계 · 합계 · 총계 · 월계 · 누계)."""
    if not isinstance(v, str):
        return False
    s = _norm(v)
    return bool(s) and any(s.endswith(t) for t in TOTAL_LABELS[:-1])


def _fa_class(name: str | None) -> str | None:
    """자산대장 과목 칸으로 유형 · 무형을 가린다(accounts.yaml). 모르면 None."""
    if not name:
        return None
    from .analysis import defs

    m = defs.map_account(None, name)
    if m["id"] == "intangibles":
        return "무형"
    if m["id"] in ("ppe", "accumulated_depreciation"):
        return "유형"
    return None


def _read_fixed(path: Path, fy_end: date | None = None) -> list[dict]:
    """고정자산대장 · 상각비 명세. 유형 · 무형을 가려 사실을 따로 낸다(2026-10-18). 무형자산 사실은 '무형자산 ' 으로 시작한다.
    과목 칸이 있으면 줄마다 계정 사전으로 가르고, 없거나 모르는 이름이면 파일 · 시트 이름(「무형」)으로 가른다."""
    path = Path(path)
    got = fixed_table(path, fy_end)
    if not got:
        return []
    sheet, c, rows, _, hdr = got
    cost_k = "acq_cost" if "acq_cost" in c else "acq_end"
    default = "무형" if "무형" in (path.stem + sheet) else "유형"
    start = None
    if fy_end:
        try:
            start = date(fy_end.year - 1, fy_end.month, fy_end.day) + timedelta(days=1)
        except ValueError:                       # 2월 29일 결산
            start = date(fy_end.year - 1, 3, 1)
    heads = {h for h in hdr if h}
    acc: dict[str, dict] = {}
    for r in rows:
        if len(heads & {_norm(x) for x in r if isinstance(x, str)}) >= 4:
            break                                # 같은 시트 아래의 다른 표(「[매각 리스트]」 머리줄)부터는 읽지 않는다
        if _is_total_row(r):
            continue
        v = _num(_cell(r, c[cost_k]))
        if v is None:
            continue
        named = any(isinstance(_cell(r, c[k]), str) and _cell(r, c[k]).strip() for k in ("asset", "fa_acct") if k in c)
        dated = "acq_date" in c and _date(_cell(r, c["acq_date"])) is not None
        if ("asset" in c or "fa_acct" in c or "acq_date" in c) and not (named or dated):
            continue                             # 자산 이름 · 과목이 비고 취득일 칸에 날짜가 없는 줄은 소계 · 요약 줄이다
        if any(_total_label(_cell(r, c[k])) for k in ("fa_acct", "asset") if k in c):
            continue                             # 「산업재산권 소계」 · 「무형자산(800번대) 경비소계」 처럼 이름이 긴 소계 줄
        acct = _cell(r, c.get("fa_acct")) if "fa_acct" in c else None
        cls = _fa_class(_norm(acct)) or default
        s = acc.setdefault(cls, {"n": 0, "total": 0.0, "cur": 0.0, "n_cur": 0, "dep": 0.0, "acc": 0.0, "book": 0.0})
        s["n"] += 1
        s["total"] += v
        s["dep"] += _num(_cell(r, c.get("dep_cur"))) or 0.0
        s["acc"] += _num(_cell(r, c.get("dep_end"))) or 0.0
        if "book_end" in c:
            s["book"] += _num(_cell(r, c["book_end"])) or 0.0
        if "acq_cur" in c:
            x = _num(_cell(r, c["acq_cur"])) or 0.0
            s["cur"] += x
            s["n_cur"] += 1 if x else 0
        elif "acq_date" in c and fy_end:
            d = _date(_cell(r, c["acq_date"]))
            if d and start <= d <= fy_end:
                s["cur"] += v
                s["n_cur"] += 1
    facts = []
    for cls in ("유형", "무형"):
        s = acc.get(cls)
        if not s:
            continue
        p = INTANGIBLE_PREFIX if cls == "무형" else ""
        facts.append(_fact(f"{p}취득가 합계 {_won(s['total'])}({s['n']}건)", s["total"], sheet))
        if "acq_cur" in c or ("acq_date" in c and fy_end):
            facts.append(_fact(f"{p}당기 취득 {_won(s['cur'])}({s['n_cur']}건)", s["cur"], sheet))
        if "dep_cur" in c:
            facts.append(_fact(f"{p}당기 {'상각비' if p else '감가상각비'} {_won(s['dep'])}", s["dep"], sheet))
        if "dep_end" in c:
            a = abs(s["acc"])                    # 누계액을 음수로 적은 대장도 있다
            facts.append(_fact(f"{p}기말 {'상각누계액' if p else '감가상각누계액'} {_won(a)}", a, sheet))
        if "book_end" in c or "dep_end" in c:
            book = s["book"] if "book_end" in c else s["total"] - abs(s["acc"])
            facts.append(_fact(f"{p}기말 장부금액 {_won(book)}", book, sheet))
    return facts


def _read_prior_tb(path: Path, fy_end=None) -> list[dict]:
    """받은자료 전기 시산표(계정별). 당기 시산표와 같은 사실(합계 · 계정 수 · 매출액 · 매출채권 · 자산총계)을 전기 열에서 뽑는다."""
    got = tb_rows(path)
    if not got:
        return []
    sheet, rows = got["sheet"], got["rows"]
    total = sum(r["amount"] for r in rows)
    k3 = lambda c: c if c < 1000 else int(str(c)[:3])  # noqa: E731
    sales = -sum(r["amount"] for r in rows if 401 <= k3(r["code"]) <= 430 and "원가" not in r["name"])
    assets = sum(r["amount"] for r in rows if 101 <= k3(r["code"]) <= 250)
    return [_fact(f"시산표 합계 {_won(total)}({'차대 일치' if abs(total) < 0.5 else '차대 불일치'})", total, sheet),
            _fact(f"계정 수 {len(rows)}개", len(rows), sheet), _fact(f"매출액 {_won(sales)}", sales, sheet),
            _fact(f"자산총계 {_won(assets)}", assets, sheet)]


SCHEDULE = "계정명세서"


def schedule_sheets(path: Path) -> list[dict]:
    """계정명세서(시트마다 계정 하나, 거래처별 잔액). [{"sheet", "rows": [(거래처, 잔액)]}] (R8, 진단 #17)."""
    out = []
    for sheet, c, rows, _, _ in _tables(Path(path), [["party"], ["ar_total"]], []):
        got = []
        for r in rows:
            if _is_total_row(r):
                continue
            p, v = _cell(r, c["party"]), _num(_cell(r, c["ar_total"]))
            if p in (None, "") or v is None:
                continue
            got.append((str(p).strip(), v))
        if got:
            out.append({"sheet": sheet, "rows": got})
    return out


def schedule_parties(path: Path) -> list[dict]:
    """계정명세서 시트마다 거래처 코드 · 이름 · 잔액(2026-10-18, 분석적 검토 거래처 잔액 규칙 · 금융기관별 대사).
    [{"sheet", "rows": [{"code", "party", "balance"}]}]. 거래처 칸이 없고 은행 · 금융기관 칸이 있는 차입금 · 예금 명세도 읽는다.
    잔액 부호는 파일에 적힌 그대로다(계정 방향 양수인지 차변 양수인지는 쓰는 쪽이 시산표와 맞춰 정한다)."""
    out = []
    for sheet, c, rows, _, _ in _tables(Path(path), [["party", "inst"], ["ar_total"]], ["code"]):
        pc = c.get("party", c.get("inst"))
        got = []
        for r in rows:
            if _is_total_row(r):
                continue
            p, v = _cell(r, pc), _num(_cell(r, c["ar_total"]))
            if p in (None, "") or v is None:
                continue
            code = _cell(r, c.get("code"))
            code = None if code in (None, "") else (str(int(code)) if isinstance(code, float) else str(code).strip())
            got.append({"code": code, "party": str(p).strip(), "balance": v})
        if got:
            out.append({"sheet": sheet, "rows": got})
    return out


def _read_schedule(path: Path, fy_end=None) -> list[dict]:
    """계정명세서 시트마다 거래처 수와 잔액 합계. 재고 품목 시트(품목 · 수량 · 금액)가 있으면 품목 수와 장부 금액 합계도
    (2026-10-16: 분석적 검토가 재고 명세 ↔ 시산표를 대사하게. 4000E 재고실사 시트와 같은 판독 규칙 recalc.yaml inventory)."""
    out = [_fact(f"{s['sheet']} 거래처 {len(s['rows'])}곳 · 잔액 합계 {_won(sum(v for _, v in s['rows']))}",
                 sum(v for _, v in s["rows"]), s["sheet"]) for s in schedule_sheets(path)]
    inv = inventory_items(path)
    if inv:
        out.append(_fact(f"재고자산 품목 {inv['count']}개 · 장부 금액 합계 {_won(inv['total'])}", inv["total"], inv["sheet"]))
    return out


def inventory_items(path: Path) -> dict | None:
    """재고 품목 시트의 품목 수와 장부 금액 합계 {sheet, count, total}. 품목 · 수량 열이 있는 첫 표. 없으면 None."""
    from .workpapers import recalc

    ic = recalc.defs()["inventory"]
    try:
        tables = recalc.find_tables(Path(path), ic["columns"], ["item", "qty"], ic["sheets"])
    except Exception:  # noqa: BLE001  명세서 꼴이 아니면 재고 사실 없이 넘어간다
        return None
    for t in tables:
        c, n, total = t["col"], 0, 0
        for r in t["rows"]:
            if _is_total_row(r):
                continue
            qty, name = _num(_cell(r, c["qty"])), _cell(r, c["item"])
            if qty is None or name in (None, ""):
                continue
            amt = _num(_cell(r, c.get("amount")))
            price = _num(_cell(r, c.get("price")))
            total += amt if amt is not None else (qty * price if price is not None else 0)
            n += 1
        if n:
            return {"sheet": t["sheet"], "count": n, "total": _int(total)}
    return None


READERS = {TB: _read_tb, JOURNAL: _read_journal, AGING: _read_aging, PAYROLL: _read_payroll, FIXED: _read_fixed,
           PRIOR_TB: _read_prior_tb, SCHEDULE: _read_schedule}


def read(path: Path, kind: str, fy_end: date | None = None) -> list[dict]:
    """받은자료 한 파일의 엔진 사실. 판독할 수 없는 종류 · 형식이면 빈 목록."""
    path = Path(path)
    fn = READERS.get(kind)
    if fn is None or path.suffix.lower() not in READABLE:
        return []
    try:
        return fn(path, fy_end)
    except ImportError:                       # .xls 인데 xlrd 가 없다. read_failure 가 까닭을 적는다
        if path.suffix.lower() in XLS:
            return []
        raise


# ---------------------------------------------------------------- 판독 실패 까닭(R8, 2026-10-06)
COL_LABELS = {"code": "계정코드", "name": "계정명", "cur": "당기 금액", "dr_bal": "차변잔액", "date": "일자", "dr": "차변",
              "cr": "대변", "ar_total": "채권 잔액", "pay": "지급 합계", "acq_cost": "취득가", "prior": "전기 금액",
              "prior_dr": "전기 차변", "dr_acc": "차변 계정", "cr_acc": "대변 계정", "side": "차대 구분", "amount": "금액",
              "signed": "차변-대변", "party": "거래처", "acq_end": "기말잔액", "cr_bal": "대변잔액"}
# 종류마다 머리줄 요건(여러 꼴이면 꼴마다 하나). 판독 실패 까닭을 찾을 때 쓴다
REQUIRED = {TB: [[["code"], ["name"], ["cur", "dr_bal"]], [["name"], ["cur", "dr_bal"]]],
            PRIOR_TB: [[["code"], ["name"], ["cur", "dr_bal", "prior", "prior_dr"]]],
            JOURNAL: [[["date"]] + req for _, req in JOURNAL_FORMS],
            AGING: [[["ar_total"]]], PAYROLL: [[["pay"]]], FIXED: [[["acq_cost", "acq_end"]]], "계정명세서": [[["party"], ["ar_total"]]]}
READ_FAIL = "판독 실패"


def read_failure(path: Path, kind: str) -> str | None:
    """엔진 판독기가 사실을 내지 못한 까닭 한 줄. 판독할 종류가 아니면 None.
    머리줄 후보(시트마다 첫 10행) 가운데 필요한 열이 가장 많이 맞는 행을 골라 못 찾은 열 이름을 적는다."""
    path = Path(path)
    req = REQUIRED.get(kind)
    if req is None:
        return None
    if path.suffix.lower() not in READABLE:
        return f"{READ_FAIL}: 엑셀(.xlsx · .xlsm · .xls)이 아니라 엔진이 열지 않음({path.suffix})"
    try:
        wb = _open(path)
    except ImportError:
        return f"{READ_FAIL}: 옛 엑셀 형식(.xls)을 열 xlrd 가 설치되어 있지 않음(pip install xlrd). 엑셀에서 .xlsx 로 다시 저장해 넣어도 됩니다"
    except Exception as e:  # noqa: BLE001  깨진 파일
        return f"{READ_FAIL}: 파일을 열지 못함({type(e).__name__})"
    best = None
    try:
        for ws in wb.worksheets:
            rows = [tuple(r) for r in ws.iter_rows(values_only=True, max_row=HEADER_SCAN + 1)]
            for hi in range(min(HEADER_SCAN, len(rows))):
                for hs in _header_candidates(rows, hi):
                    for alt in req:
                        miss = [g for g in alt if not any(_find_col(hs, k) is not None for k in g)]
                        score = (len(alt) - len(miss), len(alt))
                        if best is None or score > best[0]:
                            best = (score, ws.title, hi + 1, miss)
    finally:
        wb.close()
    if kind == TB and journal_tables(path):
        return f"{READ_FAIL}: 분개장 꼴(일자 · 차변 · 대변 열)이라 시산표로 읽지 않음. 분개장 폴더로 옮겨 주십시오"
    if best is None:
        return f"{READ_FAIL}: 값이 있는 시트가 없음"
    _, sheet, row, miss = best
    if not miss:
        what = "계정코드가 있는 계정 행" if kind == TB else "일자가 있는 행" if kind == JOURNAL else "금액이 든 행"
        return f"{READ_FAIL}: 머리줄은 찾았으나 {what}이 없음('{sheet}' 시트 {row}행)"
    names = " · ".join("/".join(COL_LABELS.get(k, k) for k in g) for g in miss)
    return f"{READ_FAIL}: 머리줄에서 못 찾은 열 {names}(가장 가까운 머리줄: '{sheet}' 시트 {row}행)"


def sniff_kind(path: Path) -> str | None:
    """엑셀 머리줄로 종류를 판별한다. 분개장 · 연령분석표 · 고정자산대장 · 급여대장 순으로 본다.
    시산표는 회사제시 폴더와 판 규칙으로만 정한다(계정명세서와 머리줄이 겹친다)."""
    path = Path(path)
    if path.suffix.lower() not in READABLE:
        return None
    if any(t["form"] == "두 계정 칸" or "code" in t["cols"] or "name" in t["cols"] for t in journal_tables(path)):
        return JOURNAL
    if any("over90" in t[1] for t in _tables(path, [["ar_total"], ["over90"]], [])):
        return AGING
    for _, c, _, _, _ in _tables(path, [["acq_cost", "acq_end"]], FIXED_OPT):
        cost = "acq_cost" in c or ("acq_beg" in c and ("dep_cur" in c or "dep_end" in c))     # 변동 꼴 대장은 상각 열이 있어야 한다
        if cost and ("acq_date" in c or "asset" in c):
            return FIXED
    if _tables(path, [["pay"], ["emp"]], []):
        return PAYROLL
    return None


# ---------------------------------------------------------------- PDF
def pdf_text(path: Path) -> list[tuple[int, str]]:
    """PDF 쪽마다 글자. 쪽 번호는 1 부터. 사실은 만들지 않는다(AI 판독 몫)."""
    import fitz

    doc = fitz.open(str(path))
    try:
        return [(i + 1, page.get_text()) for i, page in enumerate(doc)]
    finally:
        doc.close()
