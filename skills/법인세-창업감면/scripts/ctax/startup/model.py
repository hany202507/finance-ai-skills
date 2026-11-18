"""창업감면 입력(`00 받은자료/창업감면/창업감면_입력.xlsx`)을 읽는다. 시트 둘: 회사(항목 · 값) · 연도별.

값을 지어내지 않는다. 빈 칸은 기본값(Y · N 은 N, 금액은 0)이고, 필수 칸이 비면 InputError(시트 · 행 · 열)를 낸다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
INPUT_DIR = "00 받은자료/창업감면"
INPUT_NAME = "창업감면_입력.xlsx"
S_CO, S_YEARS = "회사", "연도별"

REGIONS = ("수도권과밀억제권역", "수도권(과밀억제권역 · 인구감소지역 제외)", "수도권 인구감소지역", "수도권 밖")
CHOICES = ("창업감면", "다른 공제감면")

# (항목, 종류, 기본값, 설명). 종류: date · yn · won · num · rate · pick:<목록 이름> · text. 필수는 기본값 None
COMPANY_ROWS = [
    ("과세연도 시작일", "date", None, "해당 과세연도 개시일"),
    ("과세연도 종료일", "date", None, "해당 과세연도 종료일"),
    ("중소기업", "yn", "Y", "조특령 제2조 중소기업이면 Y"),
    ("중소기업 아니게 된 날", "date", "", "중소기업이 아닌 기업과 합병하는 등으로 중소기업에 해당하지 않게 된 날(조특법 제6조 제11항). 없으면 비움"),
    ("창업일", "date", None, "법인설립등기일(기획재정부 조세특례제도과-507, 2024.06.19.). 창업 기한, 감면율 시기(2024-12-31 · 2025-12-31 경계), "
     "청년 나이, 5억원 한도와 통합고용 배제(2025-01-01 이후 창업)를 이 날로 본다"),
    ("사업 개시일", "date", "", "사업자등록증 개업연월일. 제6조 제1항 괄호(사업 개시일부터 5년이 되는 날까지 소득이 없는 경우)에만 쓴다. 비우면 창업일"),
    ("업종", "pick:industry", None, "조특법 제6조 제3항 각 호 중 주된 업종. 해당이 없으면 「그 밖의 업종」"),
    ("업종 단서 제외 업종", "yn", "N", "각 호 단서의 제외 업종(뉴스제공업 · 가상자산 매매 · 변호사업 · 공인회계사업 · 세무사업 · 오락장 운영업 등)이면 Y"),
    ("창업 지역", "pick:region", None, "창업일 당시 본점 · 사업장이 있는 곳. 수도권과밀억제권역 · 수도권(과밀억제권역 · 인구감소지역 제외) · 수도권 인구감소지역 · 수도권 밖"),
    ("이전 · 지점 지역", "pick:region0", "", "창업 뒤 사업장을 옮기거나 지점 · 사업장을 둔 지역(시행령 제5조 제25항). 창업 지역보다 감면율이 낮은 지역일 때만 "
     "그 지역에서 창업한 것으로 보고, 낮지 않으면 계산에 쓰지 않는다. 없으면 비움"),
    ("이전 · 지점 설치일", "date", "", "위 지역으로 옮기거나 지점을 둔 날. 지역을 넣으면 꼭 넣는다"),
    ("대표자 생년월일", "date", "", "청년창업 판정. 주민등록번호는 넣지 않는다"),
    ("대표자 병역 개월 수", "num", 0, "현역병(상근예비역 · 의무경찰 · 의무소방원 포함) · 사회복무요원 · 현역 장교 · 준사관 · 부사관으로 복무한 기간(개월). 6년까지 뺀다(시행령 제5조 제1항 제1호, 제27조 제1항 제1호). 그 밖의 병역은 넣지 않는다"),
    ("대표자 최대주주", "yn", "N", "창업 당시 대표자가 지배주주등으로서 최대주주(최대출자자)이면 Y(시행령 제5조 제1항 제2호 나목). "
     "그 뒤 최대주주가 아니게 되어도 Y 로 두고 그 날을 「청년 요건 상실일」 에 넣는다(같은 조 제2항)"),
    ("청년 요건 상실일", "date", "", "감면기간 중 대표자가 최대주주가 아니게 된 날(시행령 제5조 제2항). 청년이 아닌 사람이 공동대표로 취임한 날도 "
     "여기에 넣는다(서면-2021-법령해석법인-4313). 없으면 비움"),
    ("신성장 서비스업", "yn", "N", "주된 사업이 시행령 제5조 제12항 신성장 서비스업이면 Y(2024년 이전 과밀억제권역 밖 창업만 의미가 있다)"),
    ("합병 · 분할 · 현물출자 · 사업양수로 종전 사업 승계", "yn", "N", "조특법 제6조 제10항 제1호 본문"),
    ("종전 사업 자산 인수 · 매입", "yn", "N", "종전 사업에 쓰던 자산을 인수 · 매입해 같은 종류 사업을 하면 Y"),
    ("인수 자산 비율", "rate", 0, "인수 · 매입 자산가액 ÷ 사업 개시 당시 토지 · 감가상각자산 총가액(30% 이하면 창업으로 본다). "
     "「종전 사업 자산 인수 · 매입」 이 Y 면 꼭 넣는다"),
    ("사업 분리 임직원 창업", "yn", "N", "사업 분리 계약 + 임직원이 대표자 겸 최대주주(제10항 제1호 나목, 시행령 제5조 제21항)이면 Y. 2026-02-27 이후 사업을 시작했으면 회사와 그 임직원이 친족관계 · 경영지배관계가 아니어야 한다(같은 항 제3호)"),
    ("법인전환", "yn", "N", "거주자가 하던 사업을 법인으로 전환(제10항 제2호)"),
    ("폐업 후 같은 종류 사업 재개", "yn", "N", "제10항 제3호"),
    ("사업 확장 · 업종 추가", "yn", "N", "제10항 제4호"),
    ("최초 소득 발생 과세연도 종료일", "date", "", "비우면 연도별 시트에서 찾는다. 넣으면 이 값을 쓰고, 연도별 시트에 빠진 과세연도가 있어도 멈추지 않는다"),
    ("산출세액", "won", None, "법인세 산출세액(토지등 양도소득 법인세 제외)"),
    ("과세표준", "won", None, "법인세 과세표준"),
    ("감면소득", "won", None, "감면사업에서 생긴 소득(공제한 이월결손금 · 비과세 · 소득공제를 뺀 금액, 법인세법 시행령 제96조)"),
    ("수입금액", "won", None, "해당 과세연도 수입금액(기업회계기준 매출액)"),
    ("상시근로자 수(해당)", "num", "", "비우면 연도별 시트 해당 과세연도 줄"),
    ("상시근로자 수(직전)", "num", "", "비우면 연도별 시트 직전 과세연도 줄, 창업한 과세연도면 0"),
    ("최저한세 과세표준", "won", "", "손금산입 · 소득공제를 하지 않은 과세표준. 비우면 과세표준"),
    ("최저한세율", "rate", 0.07, "중소기업 7%"),
    ("먼저 적용할 다른 최저한세 대상 감면 · 공제", "won", 0, "최저한세 여지에서 창업감면보다 먼저 받을 금액. 이월되는 세액공제를 먼저 깎으려면 0"),
    ("통합고용 · 고용증대 세액공제", "won", 0, "같은 과세연도에 받으려는 조특법 제29조의7 · 제29조의8 공제액"),
    ("제127조 제4항 세액공제", "won", 0, "통합투자(제24조) 등 제127조 제4항 본문 세액공제액"),
    ("중소기업특별세액감면", "won", 0, "같은 사업장 조특법 제7조 감면액(제127조 제5항)"),
    ("적용 선택", "pick:choice", "창업감면", "중복 배제로 하나만 받을 때 고른 쪽: 창업감면 · 다른 공제감면"),
]
YEAR_COLS = ("과세연도 시작일", "과세연도 종료일", "감면사업 소득금액", "수입금액", "상시근로자 수")

# 항목마다 받는 곳(원천 서류). 빈 양식 D 열과 스킬 꾸러미의 references/입력정의.md 가 이것을 쓴다
SOURCE = {
    "과세연도 시작일": "법인등기부 · 정관의 사업연도",
    "과세연도 종료일": "법인등기부 · 정관의 사업연도",
    "중소기업": "중소기업 등 기준검토표(법인세법 시행규칙 별지 제51호서식)",
    "중소기업 아니게 된 날": "합병 등기, 중소기업 등 기준검토표(51호)",
    "창업일": "법인등기부 회사성립연월일(법인설립등기일)",
    "사업 개시일": "사업자등록증 개업연월일",
    "업종": "사업자등록증 업태 · 종목과 매출 구성, 한국표준산업분류(회계사 판정)",
    "업종 단서 제외 업종": "사업자등록증 종목, 매출 구성",
    "창업 지역": "사업자등록증 · 법인등기부 본점 소재지",
    "이전 · 지점 지역": "법인등기부 본점 이전 · 지점 설치 등기, 지점 사업자등록증",
    "이전 · 지점 설치일": "법인등기부 본점 이전 · 지점 설치 등기일",
    "대표자 생년월일": "법인등기부 대표이사 란",
    "대표자 병역 개월 수": "대표자 병적증명서",
    "대표자 최대주주": "주주명부 · 주식등변동상황명세서",
    "청년 요건 상실일": "주식등변동상황명세서(대표자 지분 변동일)",
    "신성장 서비스업": "사업자등록증 · 매출 구성(조특법 시행령 제5조 제12항 업종)",
    "합병 · 분할 · 현물출자 · 사업양수로 종전 사업 승계": "설립 경위 확인(설립 등기 · 정관 · 사업양수도 계약서 · 현물출자 내역)",
    "종전 사업 자산 인수 · 매입": "사업양수도 · 자산 매매 계약서, 개시 당시 유형자산 명세",
    "인수 자산 비율": "사업양수도 · 자산 매매 계약서, 개시 당시 토지 · 감가상각자산 명세",
    "사업 분리 임직원 창업": "사업 분리 계약서, 주주명부, 종전 회사와 임직원의 관계(2026-02-27 이후 개시분)",
    "법인전환": "개인사업자 폐업 사실 · 법인전환 내역",
    "폐업 후 같은 종류 사업 재개": "대표자 · 주주의 이전 사업자등록 내역(회사 확인)",
    "사업 확장 · 업종 추가": "회사 확인(기존 사업과의 관계)",
    "최초 소득 발생 과세연도 종료일": "전기 법인세 과세표준 및 세액조정계산서(3호). 비우면 연도별 시트",
    "산출세액": "당기 법인세 과세표준 및 세액조정계산서(3호)",
    "과세표준": "당기 법인세 과세표준 및 세액조정계산서(3호)",
    "감면소득": "당기 3호 · 소득구분계산서(48호), 이월결손금 관리대장",
    "수입금액": "손익계산서 매출액, 수입금액조정명세서(16호)",
    "상시근로자 수(해당)": "법인세-통합고용 결과(종전 범위 인원) 또는 급여대장",
    "상시근로자 수(직전)": "법인세-통합고용 결과(종전 범위 인원) 또는 급여대장",
    "최저한세 과세표준": "최저한세조정계산서(4호)",
    "최저한세율": "최저한세조정계산서(4호)",
    "먼저 적용할 다른 최저한세 대상 감면 · 공제": "공제감면세액계산서, 회계사 판단(공제 순서는 납세자가 고름)",
    "통합고용 · 고용증대 세액공제": "공제세액계산서(조특 10호의9), 법인세-통합고용 결과",
    "제127조 제4항 세액공제": "통합투자세액공제 등 공제세액계산서",
    "중소기업특별세액감면": "법인세-중소감면 결과",
    "적용 선택": "회사 · 회계사 결정",
}
YEAR_SOURCE = {
    "과세연도 시작일": "각 과세연도 세무조정계산서",
    "과세연도 종료일": "각 과세연도 세무조정계산서",
    "감면사업 소득금액": "각 과세연도 3호 각 사업연도 소득금액(감면사업분, 결손이면 음수)",
    "수입금액": "각 과세연도 손익계산서 매출액",
    "상시근로자 수": "각 과세연도 급여대장 또는 법인세-통합고용 결과",
}


class InputError(Exception):
    pass


@dataclass
class Year:
    start: date
    end: date
    income: int
    revenue: int
    staff: float | None


@dataclass
class Inputs:
    values: dict
    years: list[Year] = field(default_factory=list)
    path: str = ""
    notes: list[str] = field(default_factory=list)      # 읽으며 알게 된 확인 줄(계산 확인 줄 앞에 붙는다)

    def __getitem__(self, k):
        return self.values[k]


def load_rules() -> dict:
    """rules.yaml 을 읽는다. 같은 이름의 json 이 옆에 있으면 그것을 읽는다(스킬 꾸러미, PyYAML 없이 돌게)."""
    path = HERE / "rules.yaml"
    alt = path.with_suffix(".json")
    if alt.exists():
        return json.loads(alt.read_text(encoding="utf-8"))
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def industries(rules: dict) -> list[str]:
    return list(rules["industry"]["list"]["value"]) + ["그 밖의 업종"]


def picks(rules: dict) -> dict[str, tuple]:
    return {"industry": tuple(industries(rules)), "region": REGIONS, "region0": ("",) + REGIONS, "choice": CHOICES}


YEAR_KINDS = {"과세연도 시작일": "date", "과세연도 종료일": "date", "감면사업 소득금액": "won", "수입금액": "won", "상시근로자 수": "num"}
YEAR_REQUIRED = ("과세연도 시작일", "과세연도 종료일", "감면사업 소득금액", "수입금액")
YEAR_NOTES = {"과세연도 시작일": "창업한 과세연도부터 해당 과세연도까지 빠짐 없이 한 줄씩. 해당 과세연도 직전까지 이어지지 않으면 멈춘다"
                              "(회사 시트 「최초 소득 발생 과세연도 종료일」 을 넣었으면 확인 줄만 낸다)",
              "감면사업 소득금액": "각 사업연도 소득금액 중 감면사업분. 결손이면 음수. 처음 0 보다 큰 해가 최초 소득 과세연도",
              "상시근로자 수": "고용증가 추가감면에만 쓴다. 회사 시트에 넣으면 그 값이 먼저다"}
DEF_INTRO = ("창업감면 입력 정의. 회사 시트는 한 항목 한 줄(B 열에 값), 연도별 시트는 과세연도 한 줄. "
             "엔진은 이 시트를 읽지 않는다. 주민등록번호는 넣지 않는다.")


def definitions(rules: dict | None = None) -> list[tuple]:
    """입력 정의(시트, 항목, 형식, 비면, 받는 곳, 설명). 양식 「정의」 시트와 references/입력정의.md 가 이것을 쓴다."""
    from ..inputdef import column_rows, rows
    rules = load_rules() if rules is None else rules
    return (rows(S_CO, COMPANY_ROWS, SOURCE, picks(rules))
            + column_rows(S_YEARS, YEAR_COLS, YEAR_SOURCE, YEAR_KINDS, YEAR_REQUIRED, YEAR_NOTES))


def _date(v, where: str):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip().replace(".", "-").replace("/", "-")
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise InputError(f"{where}: 날짜를 읽지 못했습니다(「{v}」, YYYY-MM-DD)") from None


def _num(v, where: str):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(",", "").replace("원", "").strip()
    pct = s.endswith("%")
    try:
        x = float(s.rstrip("%"))
    except ValueError:
        raise InputError(f"{where}: 숫자를 읽지 못했습니다(「{v}」)") from None
    return x / 100 if pct else x


def parse(kind: str, v, where: str, rules: dict):
    if kind == "date":
        return _date(v, where)
    if kind == "yn":
        s = str(v or "").strip().upper()
        if s in ("", "N", "부", "NO", "X"):
            return "N"
        if s in ("Y", "여", "YES", "O"):
            return "Y"
        raise InputError(f"{where}: Y 나 N 을 넣으십시오(「{v}」)")
    if kind in ("won", "num", "rate"):
        x = _num(v, where)
        if x is None:
            return None
        if kind == "won":
            return int(round(x))
        if kind == "rate" and x > 1:
            return x / 100
        return x
    if kind.startswith("pick:"):
        opts = picks(rules)[kind[5:]]
        s = "" if v is None else str(v).strip()
        if s not in opts:
            raise InputError(f"{where}: 「{s}」 는 고를 수 있는 값이 아닙니다({' · '.join(o for o in opts if o)})")
        return s
    return "" if v is None else str(v).strip()


def read_inputs(path: Path, rules: dict, fy_start: str = "", fy_end: str = "") -> Inputs:
    if not Path(path).exists():
        raise InputError(f"입력 파일이 없습니다: {path}")
    wb = load_workbook(path, data_only=True)
    if S_CO not in wb.sheetnames:
        raise InputError(f"「{S_CO}」 시트가 없습니다: {path}")
    raw: dict[str, tuple] = {}
    for i, row in enumerate(wb[S_CO].iter_rows(min_row=2, max_col=2, values_only=True), start=2):
        if row[0] not in (None, ""):
            raw[str(row[0]).strip()] = (row[1], i)
    vals: dict = {}
    blank: set[str] = set()
    for key, kind, default, _desc in COMPANY_ROWS:
        v, r = raw.get(key, (None, "-"))
        x = parse(kind, v, f"{S_CO} 시트 {r}행 「{key}」", rules)
        if x in (None, ""):
            blank.add(key)
            if key == "과세연도 시작일" and fy_start:
                x = _date(fy_start, "신고건.json fy_start")
            elif key == "과세연도 종료일" and fy_end:
                x = _date(fy_end, "신고건.json fy_end")
            elif default is None:
                raise InputError(f"{S_CO} 시트 「{key}」 가 비었습니다({_desc})")
            else:
                x = parse(kind, default, key, rules) if default != "" else None
        vals[key] = x
    if vals["종전 사업 자산 인수 · 매입"] == "Y" and "인수 자산 비율" in blank:
        raise InputError(f"{S_CO} 시트 「인수 자산 비율」 이 비었습니다. 「종전 사업 자산 인수 · 매입」 이 Y 면 인수 자산가액 ÷ 사업 개시 당시"
                         " 토지 · 감가상각자산 총가액을 넣으십시오(비우면 0 으로 읽혀 창업으로 보게 됩니다)")
    if bool(vals["이전 · 지점 지역"]) != bool(vals["이전 · 지점 설치일"]):
        have, miss = ("이전 · 지점 지역", "이전 · 지점 설치일") if vals["이전 · 지점 지역"] else ("이전 · 지점 설치일", "이전 · 지점 지역")
        raise InputError(f"{S_CO} 시트 「{have}」 만 넣고 「{miss}」 가 비었습니다. 둘 다 넣거나 둘 다 비우십시오")
    years: list[Year] = []
    if S_YEARS in wb.sheetnames:
        ws = wb[S_YEARS]
        head = [str(c or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
        miss = [c for c in YEAR_COLS if c not in head]
        if miss:
            raise InputError(f"{S_YEARS} 시트 1행에 열이 없습니다: {', '.join(miss)}")
        ix = {c: head.index(c) for c in YEAR_COLS}
        for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if all(v in (None, "") for v in row):
                continue
            w = f"{S_YEARS} 시트 {i}행"
            s, e = _date(row[ix["과세연도 시작일"]], w + " 시작일"), _date(row[ix["과세연도 종료일"]], w + " 종료일")
            if not s or not e:
                raise InputError(f"{w}: 과세연도 시작일 · 종료일을 넣으십시오")
            staff = _num(row[ix["상시근로자 수"]], w + " 상시근로자 수")
            years.append(Year(s, e, int(round(_num(row[ix["감면사업 소득금액"]], w) or 0)),
                              int(round(_num(row[ix["수입금액"]], w) or 0)), None if staff is None else float(staff)))
    years.sort(key=lambda y: y.end)
    if vals["과세연도 종료일"] <= vals["과세연도 시작일"]:
        raise InputError(f"{S_CO} 시트: 과세연도 종료일이 시작일보다 앞섭니다")
    notes = []
    gaps = year_gaps(vals["창업일"], vals["과세연도 시작일"], years)
    if gaps:
        span = ", ".join(f"{a} ~ {b}" for a, b in gaps)
        if not vals["최초 소득 발생 과세연도 종료일"]:
            raise InputError(f"{S_YEARS} 시트: 창업한 과세연도부터 해당 과세연도 직전까지 과세연도가 이어지지 않습니다(빠진 기간 {span})."
                             " 빠진 과세연도 줄을 넣거나, 최초 소득 과세연도를 알면 회사 시트 「최초 소득 발생 과세연도 종료일」 을 넣으십시오")
        notes.append(f"연도별 시트에 빠진 기간이 있습니다({span}). 회사 시트 「최초 소득 발생 과세연도 종료일」 을 넣어 그 값으로 감면기간을"
                     " 정했습니다. 직전 과세연도 줄이 빠졌으면 고용증가 추가감면에 쓸 「상시근로자 수(직전)」 를 회사 시트에 넣으십시오")
    return Inputs(vals, years, str(path), notes)


def year_gaps(found: date, fs: date, years: list[Year]) -> list[tuple[date, date]]:
    """창업일이 속하는 과세연도부터 해당 과세연도 직전 날까지 연도별 시트 줄이 덮지 않는 기간. 창업한 과세연도면 빈 목록."""
    if found >= fs:
        return []
    day = timedelta(days=1)
    gaps, cur = [], found          # cur: 다음 줄이 덮어야 할 첫날
    for y in sorted((y for y in years if found <= y.end < fs), key=lambda y: y.end):
        if y.start > cur:
            gaps.append((cur, y.start - day))
        cur = max(cur, y.end + day)
    if cur < fs:
        gaps.append((cur, fs - day))
    return gaps


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
