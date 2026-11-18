"""중소기업특별세액감면 입력(`00 받은자료/중소기업감면/중소감면_입력.xlsx`)을 읽는다. 시트 하나: 회사(항목 · 값).

값을 지어내지 않는다. 빈 칸은 기본값(Y · N 은 N, 금액은 0)이고, 필수 칸이 비면 InputError(시트 · 행 · 열)를 낸다.
"""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
INPUT_DIR = "00 받은자료/중소기업감면"
INPUT_NAME = "중소감면_입력.xlsx"
S_CO = "회사"

NOT_LISTED = "감면 업종 아님"
EXCLUDED = "업종 괄호 제외 · 한정 요건 미충족"
STARTUP_YEAR = "창업 · 분할 · 합병 과세연도"
ALIASES = {"업종 괄호 제외 업종": EXCLUDED}          # 0.29.x 까지의 항목 이름도 읽는다
SOURCES = ("불분명", "감면사업", "그 밖의 사업")
CHOICES = ("중소기업특별세액감면", "다른 공제감면")

# (항목, 종류, 기본값, 설명). 종류: date · yn · won · num · rate · int · pick:<목록 이름> · text. 필수는 기본값 None
COMPANY_ROWS = [
    ("과세연도 시작일", "date", None, "해당 과세연도 개시일"),
    ("과세연도 종료일", "date", None, "해당 과세연도 종료일"),
    ("중소기업", "yn", "Y", "조특령 제2조 중소기업(유예기간 포함)이면 Y"),
    ("업종", "pick:industry", None, "조특법 제7조 제1항 제1호 감면 업종 중 감면 사업장의 업종. 해당이 없으면 「감면 업종 아님」"),
    (EXCLUDED, "yn", "N", "각 목 괄호의 제외 업종(비디오물 감상실 · 가상자산 매매 및 중개 · 자영예술가 · 카지노 · 관광유흥음식점 · "
     "외국인전용유흥음식점 · 독서실)이거나 각 목의 한정 요건(직업기술 학원은 직업능력개발훈련이 주된 사업, 의원 · 치과의원 · 한의원은 "
     "요양급여비용 비율 100분의 80 이상 등, 무형재산권 임대는 지식재산 임대, 자동차 임대는 전기 · 수소 자동차 100분의 50 이상)을 채우지 못하면 Y"),
    ("일반 서적 출판업", "yn", "N", "업종이 출판업이고 그중 일반 서적 출판업이면 Y(제7조 제1항 제2호 마목, 시행령 제6조 제5항)"),
    ("별표 3 업종 호", "int", None, "중소기업기본법 시행령 별표 3 의 주된 업종 번호(1 ~ 43). 0기준 시트 표를 본다"),
    ("소기업 규모 기준 직접 입력", "won", "", "별표 3 비고 2 처럼 표와 다른 기준이면 원 단위로 넣는다. 비우면 호의 기준"),
    ("매출액", "won", None, "해당 과세연도 손익계산서 매출액(시행령 제6조 제4항, 시행규칙 제5조 · 제2조 제4항). 1년 미만 과세연도도 그대로 넣는다"),
    (STARTUP_YEAR, "yn", "N", "창업일(분할 · 합병은 등기일의 다음 날)이 속하는 과세연도면 Y. 1년 미만이면 엔진이 매출액을 연으로 환산해 소기업을 "
     "가린다(시행규칙 제2조 제4항 단서). 사업연도 변경 · 법인 전환 첫 과세연도도 환산한다는 해석(법인세과-641, 서면법규과-568)이 있고, "
     "합병 · 분할의 존속법인은 환산하지 않는다(사전-2020-법령해석법인-0139)"),
    ("본점 수도권", "yn", None, "본점 또는 주사무소가 서울 · 인천 · 경기에 있으면 Y(제7조 제1항 단서: 모든 사업장을 수도권으로 본다)"),
    ("감면 사업장 수도권", "yn", "N", "본점이 수도권 외 지역일 때 감면 사업장이 수도권에 있으면 Y"),
    ("각 사업연도 소득금액", "won", None, "법인세 과세표준 및 세액조정계산서(3호) 각 사업연도 소득금액"),
    ("감면 제외 소득", "won", 0, "각 사업연도 소득 중 감면 사업장 · 감면 업종 소득이 아닌 것(영업외 이자 · 배당 · 임대료 · 처분손익, 비감면 사업 소득)"),
    ("이월결손금 · 비과세 · 소득공제", "won", 0, "과세표준 계산 때 공제한 금액 합계(법인세법 시행령 제96조 「공제액등」)"),
    ("공제액등이 생긴 사업", "pick:source", "불분명", "불분명(소득금액 비례 안분) · 감면사업(전액 뺌) · 그 밖의 사업(빼지 않음)"),
    ("과세표준", "won", None, "법인세 과세표준"),
    ("산출세액", "won", None, "법인세 산출세액(토지등 양도소득 법인세 제외)"),
    ("상시근로자 수(해당)", "num", "", "비우면 신고건.json 「상시근로자」(ctax employ 종전 범위)를 쓴다"),
    ("상시근로자 수(직전)", "num", "", "비우면 신고건.json 「상시근로자」 직전"),
    ("최저한세 과세표준", "won", "", "손금산입 · 소득공제를 하지 않은 과세표준. 비우면 과세표준"),
    ("최저한세율", "rate", 0.07, "중소기업 7%. 유예기간 중인 기업도 중소기업이라 7% 다(시행령 제2조 제2항). 7% 보다 크면 읽지 않는다"
     "(8 · 9% 는 중소기업이 아니게 된 뒤의 율이라 이 감면과 함께 나오지 않는다)"),
    ("먼저 적용할 다른 최저한세 대상 감면 · 공제", "won", 0, "최저한세 여지에서 중소기업특별세액감면보다 먼저 받을 금액. 감면을 먼저 받으려면 0"),
    ("통합고용 세액공제", "won", 0, "같은 과세연도 조특법 제29조의8(또는 제29조의7) 공제액. 제7조와 함께 받는다(제127조 제4항)"),
    ("제127조 제4항 세액공제", "won", 0, "통합투자(제24조) 등 제127조 제4항 본문 세액공제 중 이 과세연도에 생긴 공제액. 제7조와 하나만 고른다. "
     "앞 과세연도에서 넘어온 이월 공제액을 함께 견줄지는 회계사 확인"),
    ("같은 사업장 다른 감면", "won", 0, "같은 사업장의 창업중소기업 감면(제6조) 등 제127조 제5항 감면액. 제7조와 하나만 고른다"),
    ("적용 선택", "pick:choice", "중소기업특별세액감면", "중복 배제로 하나만 받을 때 고른 쪽: 중소기업특별세액감면 · 다른 공제감면"),
]


# 항목마다 받는 곳(원천 서류). 빈 양식 D 열과 스킬 꾸러미의 references/입력정의.md 가 이것을 쓴다
SOURCE = {
    "과세연도 시작일": "법인등기부 · 정관의 사업연도",
    "과세연도 종료일": "법인등기부 · 정관의 사업연도",
    "중소기업": "중소기업 등 기준검토표(법인세법 시행규칙 별지 제51호서식)",
    "업종": "사업자등록증 업태 · 종목과 매출 구성, 한국표준산업분류(회계사 판정)",
    EXCLUDED: "사업자등록증 종목, 매출 구성, 업종별 요건 자료(요양급여 비율 · 훈련 실적 · 차량 등록 등)",
    "일반 서적 출판업": "사업자등록증 종목, 매출 구성",
    "별표 3 업종 호": "주된 업종의 한국표준산업분류(51호 업종 코드), 중소기업기본법 시행령 별표 3",
    "소기업 규모 기준 직접 입력": "중소기업기본법 시행령 별표 3 비고(회계사 판정)",
    "매출액": "손익계산서 매출액",
    STARTUP_YEAR: "법인등기부(설립 · 분할 · 합병 등기일), 사업자등록증 개업일",
    "본점 수도권": "법인등기부 본점 소재지",
    "감면 사업장 수도권": "사업자등록증(사업장 소재지)",
    "각 사업연도 소득금액": "당기 법인세 과세표준 및 세액조정계산서(3호)",
    "감면 제외 소득": "손익계산서 영업외수익 · 비용, 소득구분계산서(48호)",
    "이월결손금 · 비과세 · 소득공제": "당기 3호, 이월결손금 관리대장",
    "공제액등이 생긴 사업": "이월결손금 발생 연도의 소득구분계산서(48호), 회사 확인",
    "과세표준": "당기 법인세 과세표준 및 세액조정계산서(3호)",
    "산출세액": "당기 법인세 과세표준 및 세액조정계산서(3호)",
    "상시근로자 수(해당)": "법인세-통합고용 결과(종전 범위 인원) 또는 급여대장",
    "상시근로자 수(직전)": "법인세-통합고용 결과(종전 범위 인원) 또는 급여대장",
    "최저한세 과세표준": "최저한세조정계산서(4호)",
    "최저한세율": "최저한세조정계산서(4호), 중소기업 등 기준검토표(51호)",
    "먼저 적용할 다른 최저한세 대상 감면 · 공제": "공제감면세액계산서, 회계사 판단(공제 순서는 납세자가 고름)",
    "통합고용 세액공제": "공제세액계산서(조특 10호의9), 법인세-통합고용 결과",
    "제127조 제4항 세액공제": "통합투자세액공제 등 공제세액계산서",
    "같은 사업장 다른 감면": "법인세-창업감면 결과 등 세액감면신청서",
    "적용 선택": "회사 · 회계사 결정",
}

class InputError(Exception):
    pass


@dataclass
class Inputs:
    values: dict
    path: str = ""
    staff_from: str = "회사 시트"

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
    return list(rules["industry"]["list"]["value"]) + [NOT_LISTED]


def picks(rules: dict) -> dict[str, tuple]:
    return {"industry": tuple(industries(rules)), "source": SOURCES, "choice": CHOICES}


DEF_INTRO = ("중소감면 입력 정의. 회사 시트는 한 항목 한 줄(B 열에 값). "
             "엔진은 정의 시트를 읽지 않는다. 주민등록번호는 넣지 않는다.")


def definitions(rules: dict | None = None) -> list[tuple]:
    """입력 정의(시트, 항목, 형식, 비면, 받는 곳, 설명). 양식 「정의」 시트와 references/입력정의.md 가 이것을 쓴다."""
    from ..inputdef import rows
    rules = load_rules() if rules is None else rules
    return rows(S_CO, COMPANY_ROWS, SOURCE, picks(rules))


def period_end(fs: date, m: int) -> date:
    """과세연도 시작일부터 m개월이 끝나는 날(태양력, 민법 제160조 꼴). 끝 달에 같은 날이 없으면 그 달 말일."""
    y, mo = divmod(fs.month - 1 + m, 12)
    y, mo = fs.year + y, mo + 1
    last = calendar.monthrange(y, mo)[1]
    return date(y, mo, last) if fs.day > last else date(y, mo, fs.day) - timedelta(days=1)


def months(fs: date, fe: date) -> int:
    """과세연도 개월 수. 1개월 미만은 1개월(법인세법 시행령 제92조를 빌린 엔진 규칙). 워크북 수식과 같은 두 후보 방식."""
    m0 = (fe.year - fs.year) * 12 + fe.month - fs.month
    return m0 if m0 >= 1 and period_end(fs, m0) >= fe else m0 + 1


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
    s = str(v).replace(",", "").replace("원", "").replace("명", "").strip()
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
        if s == "":
            return None
        if s in ("N", "부", "NO", "X"):
            return "N"
        if s in ("Y", "여", "YES", "O"):
            return "Y"
        raise InputError(f"{where}: Y 나 N 을 넣으십시오(「{v}」)")
    if kind in ("won", "num", "rate", "int"):
        x = _num(v, where)
        if x is None:
            return None
        if kind == "won":
            return int(round(x))
        if kind == "int":
            return int(round(x))
        if kind == "rate" and x > 1:
            return x / 100
        return x
    if kind.startswith("pick:"):
        opts = picks(rules)[kind[5:]]
        s = "" if v is None else str(v).strip()
        if s == "":
            return None
        if s not in opts:
            raise InputError(f"{where}: 「{s}」 는 고를 수 있는 값이 아닙니다({' · '.join(opts)})")
        return s
    return "" if v is None else str(v).strip()


def staff_from_info(info: dict) -> tuple[float | None, float | None]:
    """ctax employ 가 신고건.json 「상시근로자」 에 넣은 종전 범위 인원(청년등 + 청년등 외)."""
    block = info.get("상시근로자") if isinstance(info, dict) else None
    if not isinstance(block, dict):
        return None, None

    def one(per):
        x = block.get(per)
        if not isinstance(x, dict):
            return None
        return round(float(x.get("청년등") or 0) + float(x.get("청년등 외") or 0), 2)
    return one("해당"), one("직전")


def read_inputs(path: Path, rules: dict, info: dict | None = None) -> Inputs:
    info = info or {}
    if not Path(path).exists():
        raise InputError(f"입력 파일이 없습니다: {path}")
    wb = load_workbook(path, data_only=True)
    if S_CO not in wb.sheetnames:
        raise InputError(f"「{S_CO}」 시트가 없습니다: {path}")
    raw: dict[str, tuple] = {}
    for i, row in enumerate(wb[S_CO].iter_rows(min_row=2, max_col=2, values_only=True), start=2):
        if row[0] not in (None, ""):
            raw[str(row[0]).strip()] = (row[1], i)
    for old, new in ALIASES.items():
        if old in raw and raw.get(new, (None,))[0] in (None, ""):
            raw[new] = raw[old]
    vals: dict = {}
    for key, kind, default, desc in COMPANY_ROWS:
        v, r = raw.get(key, (None, "-"))
        x = parse(kind, v, f"{S_CO} 시트 {r}행 「{key}」", rules)
        if x in (None, ""):
            if key == "과세연도 시작일" and info.get("fy_start"):
                x = _date(info["fy_start"], "신고건.json fy_start")
            elif key == "과세연도 종료일" and info.get("fy_end"):
                x = _date(info["fy_end"], "신고건.json fy_end")
            elif default is None:
                raise InputError(f"{S_CO} 시트 「{key}」 가 비었습니다({desc})")
            else:
                x = parse(kind, default, key, rules) if default != "" else None
        vals[key] = x
    fs, fe = vals["과세연도 시작일"], vals["과세연도 종료일"]
    if fe <= fs:
        raise InputError(f"{S_CO} 시트: 과세연도 종료일이 시작일보다 앞섭니다")
    if fe > period_end(fs, 12):
        raise InputError(f"{S_CO} 시트: 과세연도가 1년을 넘습니다({fs} ~ {fe}). 법인세 사업연도는 1년을 넘지 못합니다(법인세법 제6조 제1항 단서)")
    since = date.fromisoformat(str(rules["scope"]["from"]))
    if fs < since:
        raise InputError(f"{S_CO} 시트 「과세연도 시작일」 {fs} 는 {since} 앞입니다. 그 앞에 개시한 과세연도는 종전 규정"
                         "(제7조 제1항 제2호 마목 지식기반산업, 부칙 <법률 제19199호> 제28조)이라 이 스킬 범위가 아닙니다")
    mt_max = rules["min_tax"]["rate_sme"]["value"]
    if vals["최저한세율"] is not None and vals["최저한세율"] > mt_max + 1e-9:
        raise InputError(f"{S_CO} 시트 「최저한세율」 {vals['최저한세율'] * 100:g}% 는 중소기업 율 {mt_max * 100:g}% 보다 큽니다. "
                         "제7조 감면을 받는 법인은 유예기간 중에도 중소기업이라 7% 입니다(제132조 제1항, 시행령 제2조 제2항)")
    n = len(rules["small"]["table"]["value"])
    if not 1 <= vals["별표 3 업종 호"] <= n:
        raise InputError(f"{S_CO} 시트 「별표 3 업종 호」 는 1 ~ {n} 사이 번호입니다(「{vals['별표 3 업종 호']}」)")
    inp = Inputs(vals, str(path))
    cur, prev = staff_from_info(info)
    used = []
    if vals["상시근로자 수(해당)"] is None and cur is not None:
        vals["상시근로자 수(해당)"] = cur
        used.append("해당")
    if vals["상시근로자 수(직전)"] is None and prev is not None:
        vals["상시근로자 수(직전)"] = prev
        used.append("직전")
    if used:
        inp.staff_from = f"신고건.json 「상시근로자」({' · '.join(used)}, ctax employ 종전 범위)"
    for key in ("상시근로자 수(해당)", "상시근로자 수(직전)"):
        if vals[key] is not None and vals[key] < 0:
            raise InputError(f"{S_CO} 시트 「{key}」 가 음수입니다(「{vals[key]:g}」, {inp.staff_from})")
    return inp


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
