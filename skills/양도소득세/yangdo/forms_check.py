# -*- coding: utf-8 -*-
"""서식 검산. 신고값(C8)의 서식 값이 서로 맞는지, 엔진 결과(C4)와 맞는지를 따로 다시 검사한다.

신고값 생성기(return_values), 가산세 계산(penalty), 서식 렌더러(forms, forms_pdf)를 부르지 않는다. 신고값이 틀린 채로
서식 PDF가 만들어지는 것을 막으려는 검사라서, 생성기와 같은 코드를 쓰면 같이 틀린다.
날짜 도우미(dates: 신고기한과 토·일·공휴일 보정)와 규칙세트만 함께 쓴다. 읽는 표는 셋이다.
  efile/codes_c116300.json 의 필요경비구분: 부표3 행의 전자코드가 취득가액·차감·기타필요경비 중 어느 묶음인지(코드 앞자리로 가르지 않는다)
                           세율별특수행: 신고값 전자신고.세율별 의 국내 소계 행과 합계 행의 국내외분·세율구분
  forms/서식판.json 의 부표1_장특공코드: 판정의 장특공(없음·표1·표2)에 맞는 부표1 ⑯ 코드
  rules/ruleset.json: 분납 기준금액·상한, 전자신고세액공제 금액(국세·지방), 가산세율·감면율·일이자율, 신고기한, 기본세율표
                      (엔진과 같이 규칙세트에서만 읽는다)

    forms_check.check(rv, result, facts=사실관계) -> [실패 문장]      빈 목록이면 통과

검사하는 것:
  넣지 않은 자산      엔진이 전액 비과세로 판정한 자산은 신고서와 전자신고 파일에 넣지 않는다. 신고값 「제외자산」 절이 엔진 판정과
                      같아야 하고, 부표1·부표3·양수인·계산명세(05)·필요경비명세(07)에 그 자산이 있으면 실패다.
                      과세 자산이 하나도 없는 결과는 어떤 신고값도 통과하지 못한다(한 문장으로 실패)
  인적사항 필수 칸    신고인 성명·주민등록번호·주소, 양수인(성명·번호·지분 합 1), 부표1 소재지·양도일·취득일
  부표3               행의 전자코드·구분코드, 취득가액 묶음 합 = ⑤ 계, 기타필요경비 묶음 합 = ⑬ 계
  부표3 → 부표1       ⑤ 계 = ⑫ 취득가액, ⑬ 계 = ⑭ 기타 필요경비, 실지거래가액 자산에는 부표3이 있어야 한다
  부표1 행 산식       양도차익 = ⑪-⑫-⑬-⑭, ⑮ = 양도차익-비과세양도차익, ⑱ = ⑮-⑯, 합계 행 = 자산 행 합, ⑦ 양도면적 = ⑥ 총면적 × 지분
  부표1 → 본지        부표1 ⑱ 합 = 본지 ④(합계, 세율구분 열별, 국내소계)
  본지 산식           ⑧ = ④+⑤-⑥-⑦, ⑯ 계, ⑱ = ⑩-⑪-⑫-⑬-⑭-⑮+⑯-⑰, ⑳ = ⑱-⑲, ⑮ 전자신고세액공제(합계 열은 기대값과 같아야 하고 다른 열은 한도 이하)
                      ⑲ 분납 한도는 ⑱ 에서 ⑯ 가산세를 뺀 세액으로 센다(소득세법 제112조의 납부할 세액은 제106조·제111조의 세액)
                      합계 열의 ⑰~⑳(지방은 납부할 총세액·신고기한내 납부)은 비어 있으면 실패.
                      국내소계와 세율구분 열의 ⑱(지방은 ⑮)은 합산 비교세액이 이기지 않았는데 비어 있으면 실패
  본지 ⑯ 가산세       예정신고는 0. 확정신고는 예정신고 무신고가산세와 납부지연가산세를 다시 계산해 대조한다(아래 「가산세 다시 계산」).
                      합계 열은 다시 계산한 값과 같아야 한다. 국내소계와 세율구분 열은 적혀 있으면 그 열의 값과 같아야 하고,
                      합산 비교세액이 이기지 않았는데 비어 있으면 실패다(이긴 신고서는 합계 열에만 적는다).
                      신고값 「가산세」 절의 금액과, 전자신고 절 03 행의 가산세 칸(15·16·17·35)도 다시 계산한 값과 대조한다
  세율구분 열 합      합계 열·국내소계 = 세율구분 열의 합. 합산 비교세액이 이기면 합계 열의 ⑩·⑮·⑱~⑳ 은 열 합과 다르다(빼고 본다)
  본지 → 지방         지방 과세표준 = 본지 ⑧(열마다), 지방 납부할 세액 산식, 지방 열 합,
                      지방 ⑫ 전자신고세액공제(예정신고 합계 열은 min(규칙세트 금액, ⑦-⑧-⑨-⑩-⑪), 확정신고는 0)
  엔진 대조           부표1 자산 목록과 순서 = 엔진 결과의 과세 자산(전액 비과세가 아닌 자산) 목록과 순서.
                      자산별 양도일·취득일·양도가액·양도차익·비과세양도차익·과세양도차익·장특공·양도소득금액, 취득가액+필요경비,
                      지분으로 나눈 양도가액, 서식에 옮겨 적은 자산종류·장특공 코드·취득가액종류,
                      합계 과세표준·산출세액·지방소득세, 세율구분 열별 과세표준·산출세액·양도소득금액·기본공제.
                      지방 세율구분 열의 산출세액은 엔진이 열별로 내지 않아, 과세 자산의 과세표준을 합산 묶음마다 더해
                      엔진 결과의 지방 적용세율과 규칙세트 지방소득세 세율표로 다시 구한 값과 열마다 대조한다
  기준일              이 검산이 규칙세트를 읽는 날짜는 신고값 「신고」 절에서 온다(분납은 양도일자, 전자신고세액공제와 가산세는 작성일).
                      양도일자 = 엔진 결과 과세 자산의 마지막 양도일, 작성일은 그 날 이후, 신고값 「판」의 기준정보 = 엔진 결과의 판.
                      작성일 자체는 신고인 파일의 값이라 엔진 결과와 견줄 값이 없다
  전자신고 절         신고값에 「전자신고」 절(03·05 레코드 값)이 있으면(edition.PUBLIC 이 거짓) 이 절을 본지·부표1 과 대조한다.
                      이 절은 생성기가 본지와 다른 경로로 만든다.
                      세율별 합계 행의 양도소득금액·양도소득기본공제·과세표준·산출세액·전자신고세액공제·자진납부할세액·분납할세액·
                      자진납부세액 = 본지 합계 열 ④ ⑦ ⑧ ⑩ ⑮ ⑱ ⑲ ⑳. 국내 소계 행과 세율구분 행의 ④ ⑦ ⑧ = 본지 같은 열.
                      산출세액은 합산 비교세액이 이기지 않으면 본지 같은 열과 같고, 세율구분 행 합 = 본지 합계 ⑩.
                      합산 비교세액이 이기면 엔진의 합계 산출세액을 엔진 세율별 과세표준 비율로 다시 나눠 행마다 대조한다
                      (원 미만 버림, 남는 원은 과세표준이 가장 큰 행. 규격서 p40 10번).
                      세율구분 행의 전자신고세액공제·자진납부할세액은 합산 비교세액이 이기지 않고 본지 칸이 비어 있지 않을 때 대조한다.
                      계산명세 행의 양도가액·취득가액·기타필요경비·양도차익(전체·비과세·과세대상)·장기보유특별공제·양도소득금액
                      = 부표1 같은 자산의 행. 부표1 칸이 비어 있으면 계산명세의 그 칸은 0 이어야 한다.
                      필요경비명세(07) 행의 자산은 부표1 에 있어야 한다.

가산세 다시 계산(국세청 확정신고 작성 사례 09 의 계산 근거와 같은 방식, references/정답지.md 「가산세 대조」):
  건            예정신고 기한의 말일이 같은 과세 자산(양도일이 속한 달, 허가 전에 대금을 청산한 허가구역 토지는 허가일이 속한 달)
  예정신고세액  건 안에서 합산 묶음마다 과세표준을 더해 엔진 결과의 적용세율(단일·가산)과 규칙세트 기본세율표로 세액을 구한 합
  무신고        기한이 지난 건의 세액 합 × 율, 원 미만 버림. 건별은 건마다 버리고 남는 원을 세액이 가장 큰 건에.
                확정신고기한까지 신고한 경우의 감면율은 곱하지 않는다. 신고값이 확정신고서의 값이라서다(국세·지방 모두,
                감면 조문의 문구가 바뀌기 전 구간의 신고도 같다)
  납부지연      건마다 세액 × 일수 × 일이자율, 10원 미만 버림. 일수 = 납부기한 다음 날부터 작성일 전날까지(규칙 납부일산입이 1 이면 작성일까지)
  열            건의 금액을 그 건의 세율구분별 세액 비율로 나눔(원 미만 버리고 남는 원은 세액이 가장 큰 열에)
  한 건 안에 합산 묶음이 둘 이상이고 합산 비교세액이 더 크거나, 허가구역 토지의 허가일을 읽지 못하면 정할 수 없다. 그때는 가산세 칸이
  0 이어야 하고 신고값 「가산세」 절이 계산하지 못했다고 적어야 한다. 허가일은 사실관계(facts)에서 읽는다.
  지방소득세 가산세도 같은 건으로 다시 계산한다. 세액은 지방소득세 세율, 납부기한은 dates.local_filing_deadline(소득세법 기한에
  지방.신고기한.가산개월 을 더한 날), 일수는 납부일까지, 끝수는 원 미만 버림이다. 감면율은 국세와 같이 곱하지 않는다.
  지방 서식 ⑬ 과 「가산세.지방」 을 대조한다.
  국세와 지방 가운데 한쪽이라도 정할 수 없으면 둘 다 0 이어야 한다.

검산하지 않는 것: ⑨ 세율 표기, ⑨⑩ 보유·거주기간 글자, 부표3 상호·사업자번호·지급일·증빙코드, 양도·취득 원인,
신고 절의 코드와 날짜(양도일자와 기준정보 판은 본다. 위 「기준일」),
전자신고 절의 세율·코드·날짜·면적·법정동코드·지번 칸과 필요경비명세(07), 합산 비교세액이 이길 때 세율구분 행에 나눈 전자신고세액공제.
세율과 기간 글자는 생성기의 표기 규칙을 되풀이해야 해서 뺐다(세액은 엔진과 대조한다).
감면율은 감면이 이번 신고 범위가 아니라 항상 0 이다.

열의 칸이 None 이면 서식에서 비워 두는 칸이다. 합하지 않고 산식에도 넣지 않는다. 열과 소계의 ⑲·⑳ 은 늘 비어 있고,
합산 비교세액이 이긴 신고서는 열과 소계의 ⑯·⑰·⑱ 도 비어 있다(국세청 확정신고 작성 사례 09 하위 1·2·7).
확정신고는 facts(사실관계)를 주어야 한다. 주지 않으면 「확정신고 검산에는 사실관계가 필요하다」 한 문장으로 실패한다.
합산 비교세액이 이기는지는 신고값이 아니라 엔진 결과로 정한다.

문장은 「부표1 ⑱ 합계 155,893,335 ≠ 본지 ④ 155,893,334」 꼴이다. 성명, 주민등록번호, 양수인 번호, 소재지, 상호 같은
인적사항 값은 문장에 넣지 않는다. 칸 이름과 금액, 코드, 자산 id 만 쓴다.
"""
import json
import os
from decimal import ROUND_DOWN, ROUND_FLOOR, Decimal
from fractions import Fraction

from yangdo import SKILL_DIR, dates, edition, ruleset

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
FORMS_DIR = os.path.join(SKILL_DIR, "forms")
CODES_FILE = "codes_c116300.json"
# 부표1 취득가액 종류 칸에 적는 말. 엔진 취득가액방법 → 서식 표기
ACQ_LABEL = {"실지거래가액": "실지거래가액", "매매사례가액": "매매사례가액", "감정가액": "감정가액", "환산가액": "환산취득가액"}

# 본지(별지 84) 금액 칸. (신고값 키, 서식 번호, 이름)
NAT = (("양도소득금액", "④", "양도소득금액"), ("기신고양도소득금액", "⑤", "기신고 양도소득금액"),
       ("감면소득금액", "⑥", "감면소득금액"), ("기본공제", "⑦", "기본공제"), ("과세표준", "⑧", "과세표준"),
       ("산출세액", "⑩", "산출세액"), ("감면세액", "⑪", "감면세액"), ("외국납부", "⑫", "외국납부세액공제"),
       ("원천징수", "⑬", "원천징수세액공제"), ("연금계좌", "⑭", "연금계좌세액공제"), ("전자신고공제", "⑮", "전자신고세액공제"),
       ("가산세", "⑯", "가산세 계"), ("기신고세액", "⑰", "기신고세액"), ("납부할세액", "⑱", "납부할 세액"),
       ("분납", "⑲", "분납할 세액"), ("신고기한내납부", "⑳", "납부세액"))
# 지방소득세(별지 40의11) 금액 칸
LOCAL = (("과세표준", "⑤", "과세표준"), ("산출세액", "⑦", "산출세액"), ("감면세액", "⑧", "감면세액"),
         ("외국납부", "⑨", "외국납부세액공제"), ("원천징수", "⑩", "특별징수세액공제"), ("연금계좌", "⑪", "연금계좌세액공제"),
         ("전자신고공제", "⑫", "전자신고세액공제"), ("가산세", "⑬", "가산세 합계"), ("기신고세액", "⑭", "기신고세액"),
         ("납부할세액", "⑮", "납부할 총세액"), ("신고기한내납부", "", "신고기한내 납부"))
# 합계 열은 납부 칸이 반드시 숫자여야 한다. 세율구분 열·소계는 ⑲ 분납·⑳ 납부세액을 비워 두고, ⑰·⑱(지방 ⑭·⑮)은
# 합산 비교세액이 이길 때만 비운다(서식 열 납부 행 계약, forms/서식판.json 본지_열납부)
NAT_TOTAL_REQUIRED = ("기신고세액", "납부할세액", "분납", "신고기한내납부")
LOCAL_TOTAL_REQUIRED = ("납부할세액", "신고기한내납부")
# 합산 비교세액이 이기면 합계 열이 세율구분 열의 합과 달라지는 칸(산출세액과 그에 딸린 칸)
NAT_WIN = ("산출세액", "전자신고공제", "납부할세액", "분납", "신고기한내납부")
LOCAL_WIN = ("산출세액", "전자신고공제", "납부할세액", "신고기한내납부")
NAT_PENALTY = ("가산세_신고", "가산세_납부", "가산세_기장")
LOCAL_PENALTY = ("가산세_신고", "가산세_납부", "가산세_기타")
# 본지 ⑯ 가산세 네 줄. (신고값 키, 서식 번호, 이름). 세율구분 열 합 검사와 다시 계산한 값 대조에 쓴다
NAT_PENALTY_ROWS = (("가산세_신고", "⑯", "가산세 무(과소)신고"), ("가산세_납부", "⑯", "가산세 납부지연"),
                    ("가산세_기장", "⑯", "가산세 기장불성실 등"))
# 가산세 규칙 키(무신고 율, 일이자율, 납부일산입)와 납부지연가산세의 끝수 단위(원). 끝수 단위는 법령 값이 아니라 국세청 확정신고
# 작성 사례의 계산 근거가 쓴 처리다. 확정신고기한까지 신고한 경우의 감면율은 읽지 않는다(확정신고서의 가산세에는 감면을 넣지 않는다)
PENALTY_KEYS = ("가산세.무신고.율", "가산세.납부지연.일이자율", "가산세.납부지연.납부일산입")
PENALTY_LATE_UNIT = 10
# 지방 서식 ⑬ 가산세 네 줄과 지방소득세 가산세 규칙 키(무신고 율, 일이자율, 납부일산입). 지방은 원 미만을 버린다
LOCAL_PENALTY_ROWS = (("가산세_신고", "⑬", "가산세 무(과소)신고"), ("가산세_납부", "⑬", "가산세 납부지연"),
                      ("가산세_기타", "⑬", "가산세 기타"))
LOCAL_PENALTY_KEYS = ("지방.가산세.무신고.율", "지방.가산세.납부지연.일이자율", "지방.가산세.납부지연.납부일산입")
LOCAL_PENALTY_UNIT = 1
# 신고값 전자신고.세율별 행(03 레코드)의 가산세 칸 → 다시 계산한 값의 자리(0 무신고, 1 납부지연, 2 계)
EFILE_PENALTY = (("가산세-신고불성실", 0), ("가산세-납부불성실", 1), ("가산세-계", 2))
EFILE_PENALTY_OTHER = "가산세-기장불성실등"

# 신고값 전자신고.세율별 행(03 레코드)의 금액 키 → 본지 열의 키. 03 쪽 키는 레이아웃 필드 name 그대로다
EFILE_TOTAL = (("양도소득금액", "양도소득금액"), ("양도소득기본공제", "기본공제"), ("과세표준", "과세표준"), ("산출세액", "산출세액"),
               ("전자신고세액공제", "전자신고공제"), ("자진납부할세액", "납부할세액"), ("분납할세액", "분납"),
               ("자진납부세액", "신고기한내납부"))
EFILE_BASE = EFILE_TOTAL[:3]                       # 소계 행과 세율구분 행이 본지 같은 열과 언제나 같아야 하는 칸
EFILE_TAX = EFILE_TOTAL[3]                         # 합산 비교세액이 이기면 세율구분 행이 본지 열과 달라지는 칸
EFILE_RATE_PAYMENT = EFILE_TOTAL[4:6]              # 세율구분 행의 전자신고세액공제·자진납부할세액(본지 칸이 비어 있으면 보지 않는다)
# 신고값 전자신고.계산명세 행(05 레코드)의 금액 키 → 부표1 행의 키
EFILE_ASSET = (("거래금액_양도가액", "양도가액"), ("거래금액_취득가액", "취득가액"), ("기타필요경비", "기타필요경비"),
               ("양도차익_전체양도차익", "양도차익"), ("양도차익_비과세양도차익", "비과세양도차익"),
               ("양도차익_과세대상양도차익", "과세양도차익"), ("장기보유특별공제", "장특공"), ("양도소득금액", "양도소득금액"))

# 부표1 행 금액 칸. (신고값 키, 서식 번호, 이름)
SHEET1_MONEY = (("양도가액", "⑪", "양도가액"), ("취득가액", "⑫", "취득가액"), ("토초세", "⑬", "기납부 토지초과이득세"),
                ("기타필요경비", "⑭", "기타 필요경비"), ("양도차익", "", "양도차익"), ("비과세양도차익", "", "비과세양도차익"),
                ("과세양도차익", "⑮", "과세대상양도차익"), ("장특공", "⑯", "장기보유특별공제"),
                ("양도소득금액", "⑱", "양도소득금액"), ("감면소득금액", "⑳", "감면소득금액"))


# ---------------------------------------------------------------- 낱개 도우미

def _i(x):
    """칸 값 → 정수. 빈 칸(None)은 0."""
    return 0 if x is None else int(x)


def _w(x):
    """문장에 쓰는 값. 정수는 천 단위 쉼표, 빈 칸은 「빈칸」."""
    if x is None or x == "":
        return "빈칸"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return format(x, ",")
    return str(x)


def _blank(x):
    return x is None or (isinstance(x, str) and not x.strip())


def _iso(s):
    """YYYYMMDD → YYYY-MM-DD. 이미 그 꼴이면 그대로."""
    s = str(s)
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]) if len(s) == 8 and s.isdigit() else s


def _col(name):
    return name if name in ("합계", "국내소계", "국외소계") else name + " 열"


def _group(entry):
    """필요경비구분 한 항목 → 취득 | 차감 | 기타 | None. 코드표의 묶음 이름으로 가른다."""
    g = entry.get("묶음") or ""
    if g.startswith("취득가액"):
        return "차감" if "차감항목" in g else "취득"
    if g.startswith("기타필요경비"):
        return "기타"
    return None


def _expense_table(efile_dir):
    with open(os.path.join(efile_dir, CODES_FILE), encoding="utf-8") as f:
        table = json.load(f)["필요경비구분"]
    return {v["전자코드"]: v for v in table.values()}


def _special_rows(efile_dir):
    """전자신고 세율별의 (국내 소계 행, 합계 행). 각각 (국내외분, 세율구분)."""
    with open(os.path.join(efile_dir, CODES_FILE), encoding="utf-8") as f:
        table = json.load(f)["세율별특수행"]
    return tuple((table[k]["국내외분"], table[k]["세율구분"]) for k in ("국내소계", "합계"))


def _named(table):
    """금액 칸 표 (키, 서식 번호, 이름) → {키: 「⑩ 산출세액」}."""
    return {key: (no + " " if no else "") + name for key, no, name in table}


def _floor(x):
    return int(Decimal(x).to_integral_value(rounding=ROUND_FLOOR))


def _share(total, weights):
    """총액을 가중치 비율로 나눈다. 원 미만은 버리고 남는 원은 가중치가 가장 큰 칸(같으면 앞 칸)에 더한다."""
    whole = sum(weights)
    if not whole:
        return [total] + [0] * (len(weights) - 1)
    parts = [total * w // whole for w in weights]
    top = max(range(len(weights)), key=lambda j: (weights[j], -j))
    parts[top] += total - sum(parts)
    return parts


def _progressive(base, table):
    """누진세율표 [[하한, 기준액, 세율], ...] 의 세액. 기준액 + (과세표준 - 하한) × 세율."""
    row = table[0]
    for r in table:
        if base > r[0]:
            row = r
    return Decimal(row[1]) + (Decimal(base) - row[0]) * Decimal(str(row[2]))


class _Undetermined(Exception):
    """가산세를 다시 계산할 수 없는 건. 문장은 까닭이다."""


class _Check:
    def __init__(self, rv, result, rules_dir, efile_dir, forms_dir, facts=None):
        self.rv, self.result, self.facts = rv, result, facts
        self._penalty = None          # {False: 국세 가산세 기대값, True: 지방소득세 가산세 기대값}
        self.rules_dir = rules_dir
        self.efile_dir = efile_dir or EFILE_DIR
        self.forms_dir = forms_dir or FORMS_DIR
        self.out = []
        self._rs = None
        self._rs_failed = False
        self.calc = (result or {}).get("계산") or {}
        self.eng = {r["id"]: r for r in self.calc.get("자산") or []}
        # 엔진이 전액 비과세로 판정한 자산과 나머지(과세 자산). 신고서에는 과세 자산만 있어야 한다
        self.exempt = [r["id"] for r in self.calc.get("자산") or [] if (r.get("판정") or {}).get("전액비과세")]
        self.taxed = [r["id"] for r in self.calc.get("자산") or [] if r["id"] not in self.exempt]
        total = self.calc.get("합계") or {}
        # 합산 비교세액이 이기는지는 엔진 결과로 정한다
        self.nat_win = total.get("합산비교세액", 0) > total.get("호별합산세액", 0)
        self.local_win = total.get("지방_합산비교", 0) > total.get("지방_호별합산", 0)

    # ------------------------------------------------------------ 공통

    def fail(self, text):
        if text not in self.out:
            self.out.append(text)

    def same(self, a, b, left, right):
        if _i(a) != _i(b):
            self.fail("%s %s ≠ %s %s" % (left, _w(a), right, _w(b)))

    def rules(self):
        """규칙세트. 못 읽으면 한 번만 알리고 None."""
        if self._rs is None and not self._rs_failed:
            try:
                self._rs = ruleset.load(self.rules_dir)
            except ruleset.RuleError:
                self._rs_failed = True
                self.fail("규칙세트를 읽지 못해 분납 한도와 전자신고세액공제 한도를 검사하지 못했다")
        return self._rs

    def rule(self, key, on):
        rs = self.rules()
        if rs is None:
            return None
        try:
            return rs.value(key, on)
        except ruleset.RuleError:
            self.fail("규칙세트에 %s 의 %s 값이 없어 한도를 검사하지 못했다" % (key, on))
            return None

    def asset_ids(self):
        return [x["자산"] for x in self.rv["부표1"]]

    def is_exempt(self, aid):
        e = self.eng.get(aid)
        return bool(e and e["판정"].get("전액비과세"))

    def column(self, form, cols, name):
        c = cols.get(name)
        if c is None:
            self.fail("%s 열 목록에 %s 열이 없다" % (form, name))
        return c

    def run(self):
        if not self.result or self.result.get("상태") != "완료" or not self.calc:
            return ["엔진 결과가 완료 상태가 아니라 서식 값을 엔진과 대조하지 못했다"]
        if not self.taxed:
            return ["과세 자산이 없다. 전액 비과세 자산(%s)뿐인 건은 %s 만들지 않는다"
                    % (", ".join(self.exempt), "신고서를" if edition.PUBLIC else "신고서와 전자신고 파일을")]
        if (self.rv.get("신고") or {}).get("구분") == "확정" and self.facts is None:
            # 가산세를 다시 계산할 때 허가구역 토지의 허가일을 사실관계에서 읽는다. 없이 계산하면 틀린 값과 대조하게 된다
            return ["확정신고 검산에는 사실관계가 필요하다. forms_check.check 에 facts 를 준다"]
        steps = (("넣지 않은 자산", self.left_out), ("신고인·양수인", self.required), ("부표3", self.schedule3),
                 ("부표1", self.schedule1),
                 ("본지", self.main), ("본지 ⑯ 가산세", self.penalty), ("지방", self.local),
                 ("엔진 대조(부표1)", self.engine_assets),
                 ("엔진 대조(본지)", self.engine_main), ("엔진 대조(지방)", self.engine_local),
                 ("엔진 대조(기준일)", self.engine_dates))
        if not edition.PUBLIC:      # 공개본 신고값에는 전자신고 절이 없다(return_values)
            steps += (("전자신고 절", self.efile_section),)
        for name, step in steps:
            try:
                step()
            except (KeyError, TypeError, AttributeError, ValueError, IndexError, OSError) as e:
                what = type(e).__name__ + (" " + str(e.args[0]) if isinstance(e, KeyError) and e.args else "")
                self.fail("%s 검사를 하지 못했다. 신고값에 필요한 칸이 없거나 모양이 다르다(%s)" % (name, what))
        return self.out

    # ------------------------------------------------------------ 넣지 않은 자산(전액 비과세)

    def left_out(self):
        """전액 비과세 자산은 신고서와 전자신고 파일에 없어야 하고, 신고값 「제외자산」 절은 엔진 판정과 같아야 한다."""
        rv = self.rv
        got = [x.get("자산") for x in rv.get("제외자산") or []]
        if got != self.exempt:
            self.fail("신고값 제외자산 [%s] ≠ 엔진이 전액 비과세로 판정한 자산 [%s]"
                      % (", ".join(map(str, got)), ", ".join(self.exempt)))
        sec = rv.get("전자신고") or {}
        places = (("부표1", rv.get("부표1")), ("부표3", rv.get("부표3")), ("본지 ② 양수인", rv.get("양수인")),
                  ("전자신고 계산명세", sec.get("계산명세")), ("전자신고 필요경비명세", sec.get("필요경비명세")))
        for name, rows in places:
            for aid in dict.fromkeys(x.get("자산") for x in rows or []):
                if aid in self.exempt:
                    self.fail("%s 에 전액 비과세 자산 %s 가 있다. 전액 비과세 자산은 %s에 넣지 않는다"
                              % (name, aid, "신고서" if edition.PUBLIC else "신고서와 전자신고 파일"))

    # ------------------------------------------------------------ 필수 칸

    def required(self):
        rv = self.rv
        p = rv.get("신고인") or {}
        if _blank(p.get("성명")):
            self.fail("본지 ① 신고인 성명이 비어 있다")
        if _blank(p.get("주민등록번호")):
            self.fail("본지 ① 신고인 주민등록번호가 비어 있다")
        addr = p.get("주소") or {}
        if not any(not _blank(addr.get(k)) for k in ("시도", "시군구", "읍면동")):
            self.fail("본지 ① 신고인 주소가 비어 있다")
        ids = self.asset_ids()
        buyers = rv.get("양수인") or []
        for b in buyers:
            if b.get("자산") not in ids:
                self.fail("본지 ② 양수인의 자산 %s 가 부표1 에 없다" % _w(b.get("자산")))
        for aid in ids:
            mine = [b for b in buyers if b.get("자산") == aid]
            if not mine:
                self.fail("본지 ② 양수인이 없다(자산 %s)" % aid)
                continue
            share = Fraction(0)
            for b in mine:
                if _blank(b.get("성명")):
                    self.fail("본지 ② 양수인 성명이 비어 있다(자산 %s)" % aid)
                if _blank(b.get("번호")):
                    self.fail("본지 ② 양수인 번호가 비어 있다(자산 %s)" % aid)
                if not b.get("지분분모") or b.get("지분분자") is None:
                    self.fail("본지 ② 양수인 지분이 비어 있다(자산 %s)" % aid)
                else:
                    share += Fraction(int(b["지분분자"]), int(b["지분분모"]))
            if share != 1:
                self.fail("본지 ② 양수인 지분 합 %s ≠ 1 (자산 %s)" % (share, aid))
        for row in rv["부표1"]:
            aid = row["자산"]
            for key, no, name in (("소재지", "②", "소재지"), ("양도일", "④", "양도일"), ("취득일", "⑤", "취득일")):
                if _blank(row.get(key)):
                    self.fail("부표1 %s %s %s가 비어 있다" % (aid, no, name))

    # ------------------------------------------------------------ 부표3

    def schedule3(self):
        table = _expense_table(self.efile_dir)
        rows1 = {x["자산"]: x for x in self.rv["부표1"]}
        seen = set()
        for s in self.rv["부표3"]:
            aid = s["자산"]
            if aid in seen:
                self.fail("부표3 이 자산 %s 에 둘 이상 있다" % aid)
            seen.add(aid)
            row1 = rows1.get(aid)
            if row1 is None:
                self.fail("부표3 의 자산 %s 가 부표1 에 없다" % aid)
            acq = other = 0
            for x in s["행"]:
                e = table.get(x["전자코드"])
                if e is None:
                    self.fail("부표3 %s 구분 전자코드 %s 가 코드표에 없다" % (aid, _w(x["전자코드"])))
                    continue
                if x["구분코드"] != e["코드"]:
                    self.fail("부표3 %s 구분코드 %s 가 전자코드 %s 의 코드 %s 와 다르다"
                              % (aid, _w(x["구분코드"]), x["전자코드"], e["코드"]))
                if x.get("구분") != e["이름"]:
                    self.fail("부표3 %s 전자코드 %s 의 구분 이름이 코드표와 다르다" % (aid, x["전자코드"]))
                g = _group(e)
                if g == "취득":
                    acq += _i(x["금액"])
                elif g == "차감":
                    acq -= _i(x["금액"])
                elif g == "기타":
                    other += _i(x["금액"])
                else:
                    self.fail("부표3 %s 전자코드 %s 의 묶음을 알 수 없다" % (aid, x["전자코드"]))
            self.same(s["취득가액계"], acq, "부표3 %s ⑤ 계" % aid, "행 합")
            self.same(s["기타필요경비계"], other, "부표3 %s ⑬ 기타 필요경비 계" % aid, "행 합")
            if row1 is not None:
                self.same(s["취득가액계"], row1["취득가액"], "부표3 %s ⑤ 계" % aid, "부표1 %s ⑫ 취득가액" % aid)
                self.same(s["기타필요경비계"], row1["기타필요경비"], "부표3 %s ⑬ 기타 필요경비 계" % aid,
                          "부표1 %s ⑭ 기타 필요경비" % aid)
        for aid, e in self.eng.items():
            if e["계산"].get("취득가액방법") == "실지거래가액" and aid not in seen and aid in rows1:
                self.fail("부표1 %s ⑫ 취득가액이 실지거래가액인데 부표3 이 없다" % aid)

    # ------------------------------------------------------------ 부표1

    def schedule1(self):
        rows = self.rv["부표1"]
        for r in rows:
            aid = r["자산"]
            if self.is_exempt(aid):                 # 있으면 안 되는 행이다. 「넣지 않은 자산」 검사가 알렸다
                continue
            gain = _i(r.get("양도가액")) - _i(r.get("취득가액")) - _i(r.get("토초세")) - _i(r.get("기타필요경비"))
            self.same(r.get("양도차익"), gain, "부표1 %s 양도차익" % aid, "⑪-⑫-⑬-⑭")
            taxable = _i(r.get("양도차익")) - _i(r.get("비과세양도차익"))
            self.same(r.get("과세양도차익"), taxable, "부표1 %s ⑮ 과세대상양도차익" % aid, "양도차익-비과세양도차익")
            income = _i(r.get("과세양도차익")) - _i(r.get("장특공"))
            self.same(r.get("양도소득금액"), income, "부표1 %s ⑱ 양도소득금액" % aid, "⑮-⑯")

        for r in rows:
            self.area_share(r)

        # 합계 행 = 자산 행 합
        total = self.rv["부표1합계"]
        for key, no, name in SHEET1_MONEY:
            self.same(total.get(key), sum(_i(r.get(key)) for r in rows), "부표1 합계 행 %s%s" % (no + " " if no else "", name),
                      "자산 행 합")
        for k, v in (total.get("기준시가") or {}).items():
            self.same(v, sum(_i((r.get("기준시가") or {}).get(k)) for r in rows), "부표1 합계 행 기준시가 %s" % k, "자산 행 합")

        # 부표1 ⑱ → 본지 ④
        main = self.rv["본지"]["열"]
        labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        income_sum = sum(_i(r.get("양도소득금액")) for r in rows)
        if "합계" in main:
            self.same(income_sum, main["합계"].get("양도소득금액"), "부표1 ⑱ 합계", "본지 ④")
        taxed = [r for r in rows if not self.is_exempt(r["자산"])]
        for r in taxed:
            if r.get("세율구분표기") not in labels:
                self.fail("부표1 %s ① 세율구분 %s 에 해당하는 본지 열이 없다" % (r["자산"], _w(r.get("세율구분표기"))))
        for label in labels:
            if label in main:
                self.same(sum(_i(r.get("양도소득금액")) for r in taxed if r.get("세율구분표기") == label),
                          main[label].get("양도소득금액"), "부표1 ⑱ %s 열 합" % label, "본지 %s 열 ④" % label)
        if "국내소계" in main:
            self.same(sum(_i(r.get("양도소득금액")) for r in taxed if str(r.get("세율구분표기")).startswith("1-")),
                      main["국내소계"].get("양도소득금액"), "부표1 ⑱ 국내분 합", "본지 국내소계 ④")

    def area_share(self, r):
        """⑦ 양도면적 = ⑥ 총면적 × 양도 지분. 면적은 소수 셋째 자리까지 쓰므로 0.001 미만 차이는 같게 본다."""
        if r.get("지분분자") is None or not r.get("지분분모"):
            self.fail("부표1 %s 양도 지분이 비어 있다" % r["자산"])
            return
        share = Fraction(int(r["지분분자"]), int(r["지분분모"]))
        for kind in ("토지", "건물"):
            total, sold = Fraction(str(r.get("총면적_" + kind) or 0)), Fraction(str(r.get("양도면적_" + kind) or 0))
            if abs(total * share - sold) >= Fraction(1, 1000):
                self.fail("부표1 %s ⑦ 양도면적 %s %s ≠ ⑥ 총면적 %s × 지분 %s" % (r["자산"], kind, float(sold), float(total), share))

    def check_labels(self, form, labels):
        for x in labels:
            if x["표기"] != "%s-%s" % (x["국내외분"], x["세율구분"]):
                self.fail("%s 세율구분 표기 %s ≠ 국내외분 %s, 세율구분 %s" % (form, x["표기"], x["국내외분"], x["세율구분"]))

    # ------------------------------------------------------------ 본지

    def main(self):
        form = self.rv["본지"]
        cols = form["열"]
        self.check_labels("본지", form["세율구분"])
        labels = [x["표기"] for x in form["세율구분"]]
        names = ["합계", "국내소계"] + labels + ["국외소계"]
        for n in names:
            c = self.column("본지", cols, n)
            if c is not None:
                self.main_column(n, c)
        self.sums("본지", cols, labels, NAT + NAT_PENALTY_ROWS, NAT_WIN, self.nat_win)
        self.column_due_filled("본지", cols, labels, self.nat_win, "⑱ 납부할 세액")
        self.payment_limits(cols, [n for n in names if n in cols])

    def column_due_filled(self, form, cols, labels, win, name):
        """국내소계와 세율구분 열의 납부할 세액. 합산 비교세액이 이기지 않았는데 비어 있으면 알린다(열 합 검사와 03 행 대조가
        빈 칸을 건너뛰기 때문이다). 이긴 신고서는 비워 두는 것이 맞다."""
        if win:
            return
        for n in ["국내소계"] + labels:
            c = cols.get(n)
            if c is not None and c.get("납부할세액") is None:
                self.fail("%s %s %s 칸이 비어 있다(합산 비교세액이 크지 않으면 세율구분 열과 소계에도 적는다)" % (form, _col(n), name))

    def total_payment_filled(self, form, c, keys, table):
        """합계 열의 납부 칸이 비어 있으면 알린다. 비어 있으면 산식 검사를 건너뛰어 틀린 값을 놓치기 때문이다."""
        names = {key: (no, name) for key, no, name in table}
        for key in keys:
            if c.get(key) is None:
                no, name = names[key]
                self.fail("%s 합계 %s%s 칸이 비어 있다(합계 열의 납부 칸은 숫자여야 한다)" % (form, no + " " if no else "", name))

    def main_column(self, n, c):
        cn = "본지 " + _col(n)
        if n == "합계":
            self.total_payment_filled("본지", c, NAT_TOTAL_REQUIRED, NAT)
        base = _i(c.get("양도소득금액")) + _i(c.get("기신고양도소득금액")) - _i(c.get("감면소득금액")) - _i(c.get("기본공제"))
        self.same(c.get("과세표준"), base, cn + " ⑧ 과세표준", "④+⑤-⑥-⑦")
        self.same(c.get("가산세"), sum(_i(c.get(k)) for k in NAT_PENALTY), cn + " ⑯ 가산세 계", "세 칸 합")
        if c.get("납부할세액") is not None:
            due = (_i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                   - _i(c.get("연금계좌")) - _i(c.get("전자신고공제")) + _i(c.get("가산세")) - _i(c.get("기신고세액")))
            self.same(c.get("납부할세액"), due, cn + " ⑱ 납부할 세액", "⑩-⑪-⑫-⑬-⑭-⑮+⑯-⑰")
            if c.get("분납") is not None and c.get("신고기한내납부") is not None:
                self.same(c.get("신고기한내납부"), _i(c.get("납부할세액")) - _i(c.get("분납")), cn + " ⑳ 납부세액", "⑱-⑲")

    def sums(self, form, cols, labels, keys, win_keys, win):
        """소계와 합계 열이 세율구분 열의 합과 같은가. 열의 칸이 None 이면 그 칸은 합하지 않는다."""
        groups = (("국내소계", [x for x in labels if x.startswith("1")]), ("국외소계", [x for x in labels if not x.startswith("1")]),
                  ("합계", labels))
        for sub, members in groups:
            if sub not in cols:
                continue
            for key, no, name in keys:
                vals = [cols[x].get(key) for x in members if x in cols]
                if any(v is None for v in vals) or cols[sub].get(key) is None:
                    continue
                if sub == "합계" and win and key in win_keys:
                    continue
                self.same(cols[sub].get(key), sum(_i(v) for v in vals), "%s %s %s%s" % (form, sub, no + " " if no else "", name),
                          "세율구분 열 합")

    def filing_credit(self, cols, names, kind, sin):
        """⑮ 전자신고세액공제. 합계 열은 기대값과 같아야 하고(빠뜨려도 잡는다), 다른 열은 기대값 이하이면 된다.
        기대값은 예정신고 min(규칙세트 금액, ⑩-⑪-⑫-⑬-⑭) (음수면 0), 확정신고 0. 확정신고에서는 규칙 키를 부르지 않는다."""
        if kind == "예정":
            cap, why = self.rule("전자신고세액공제.예정", _iso(sin["작성일"])), "예정신고 한도"
        else:
            cap, why = 0, "확정신고에는 전자신고세액공제가 없다"
        for n in names:
            c = cols[n]
            got = _i(c.get("전자신고공제"))
            if n != "합계" and got == 0:
                continue
            room = max(0, _i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                       - _i(c.get("연금계좌")))
            if got < 0:
                self.fail("본지 %s ⑮ 전자신고세액공제 %s 가 음수다" % (_col(n), _w(c.get("전자신고공제"))))
            elif cap is None:
                continue
            elif n == "합계" and got != min(int(cap), room):
                self.fail("본지 합계 ⑮ 전자신고세액공제 %s ≠ %s (%s %s, 산출세액에서 ⑪~⑭ 를 뺀 %s)"
                          % (_w(c.get("전자신고공제")), _w(min(int(cap), room)), why, _w(int(cap)), _w(room)))
            elif n != "합계" and got > min(int(cap), room):
                self.fail("본지 %s ⑮ 전자신고세액공제 %s 이 한도 %s 를 넘는다(%s, 산출세액에서 ⑪~⑭ 를 뺀 %s)"
                          % (_col(n), _w(c.get("전자신고공제")), _w(min(int(cap), room)), why, _w(room)))

    def payment_limits(self, cols, names):
        """⑮ 전자신고세액공제와 ⑲ 분납 한도. 한도는 규칙세트 값이다. 확정신고의 ⑮ 는 규칙을 부르지 않고 0 으로 본다.
        분납 규칙은 ⑲ 에 값이 있는 칸이 있을 때만 읽는다. 분납 한도를 세는 세액은 ⑱ 에서 ⑯ 가산세를 뺀 금액이다
        (소득세법 제112조가 가리키는 제106조·제111조의 납부할 세액은 산출세액에서 감면세액과 세액공제액을 뺀 금액)."""
        sin = self.rv["신고"]
        kind = sin["구분"]
        if kind not in ("예정", "확정"):
            self.fail("신고 구분 %s 이 예정이나 확정이 아니다" % _w(kind))
        if kind in ("예정", "확정"):
            self.filing_credit(cols, names, kind, sin)
        installments = [n for n in names if _i(cols[n].get("분납")) != 0]
        if not installments:
            return
        on = _iso(sin["양도일자"])
        base, top, rate = (self.rule("분납.기준금액", on), self.rule("분납.상한기준", on), self.rule("분납.상한율", on))
        for n in installments:
            c = cols[n]
            inst, due = _i(c.get("분납")), _i(c.get("납부할세액")) - _i(c.get("가산세"))
            if inst < 0:
                self.fail("본지 %s ⑲ 분납할 세액 %s 가 음수다" % (_col(n), _w(inst)))
                continue
            if "분납신청" in sin and not sin["분납신청"]:
                self.fail("본지 %s ⑲ 분납할 세액 %s 인데 신고에서 분납을 신청하지 않았다" % (_col(n), _w(inst)))
            if base is None or top is None or rate is None:
                continue
            if due <= int(base):
                limit = 0
            elif due <= int(top):
                limit = due - int(base)
            else:
                limit = int((Decimal(due) * Decimal(str(rate))).to_integral_value(rounding=ROUND_DOWN))
            if inst > limit:
                self.fail("본지 %s ⑲ 분납할 세액 %s 이 한도 %s 를 넘는다(⑱ 납부할 세액에서 ⑯ 가산세를 뺀 %s)"
                          % (_col(n), _w(inst), _w(limit), _w(due)))

    # ------------------------------------------------------------ 본지 ⑯ 가산세(다시 계산)

    def penalty_rule(self, key, on):
        v = self.rule(key, on)
        if v is None:
            raise _Undetermined("규칙세트에서 %s 를 읽지 못했다" % key)
        return v

    def deadline_base(self, row):
        """예정신고 기한을 세는 기준일. 허가 전에 대금을 청산한 허가구역 토지는 허가일이다(확정신고는 사실관계가 있어야 검산한다)."""
        sold = dates.to_date(row["판정"]["양도일"])
        asset = next((a for a in (self.facts or {}).get("자산") or [] if a.get("id") == row["id"]), None) or {}
        if asset.get("토지거래허가대상") != "예":
            return sold
        try:
            permit = dates.to_date((asset.get("토지거래허가") or {}).get("허가일"))
        except ValueError:
            permit = None
        if permit is None:
            raise _Undetermined("%s 의 허가일 값이 없거나 읽을 수 없어 예정신고 납부기한을 정할 수 없다" % row["id"])
        return permit if permit > sold else sold

    @staticmethod
    def column_tax(members, rs, local=False):
        """자산들의 세율구분 표기별 세액. 합산 묶음마다 과세표준을 더해 세율을 적용한다. 합산 비교세액은 보지 않는다.
        local 이면 엔진 결과의 지방 적용세율과 규칙세트의 지방소득세 세율표를 쓴다."""
        single_key, extra_key, table_key = (("지방단일", "지방가산", "지방.기본세율") if local else ("단일", "가산", "기본세율"))
        groups = {}
        for m in members:
            groups.setdefault(m["계산"]["합산묶음"], []).append(m)
        cols = {}
        for g in groups.values():
            anchor = min(g, key=lambda m: (m["판정"]["양도일"], m["id"]))
            base = sum(_i(m["계산"]["과세표준"]) for m in g)
            rate = anchor["계산"]["적용세율"]
            single, extra = rate.get(single_key), rate.get(extra_key)
            if extra is None:
                tax = _floor(Decimal(base) * Decimal(single))
            else:
                table = rs.value(table_key, anchor["판정"]["양도일"])
                tax = _progressive(base, table) + Decimal(base) * Decimal(extra)
                if single is not None and Decimal(base) * Decimal(single) >= tax:
                    tax = Decimal(base) * Decimal(single)
                tax = _floor(tax)
            code = anchor["계산"]["코드"]
            name = "%s-%s" % (code["국내외분"], code["세율구분"])
            cols[name] = cols.get(name, 0) + tax
        return cols

    def case_tax(self, members, rs, local=False):
        """한 건(한 번에 예정신고하는 자산들)의 세율구분 표기별 세액(column_tax). 합산 묶음이 둘 이상이고 합산 비교세액이
        더 크면 예정신고 세액을 정할 수 없다."""
        table_key = "지방.기본세율" if local else "기본세율"
        cols = self.column_tax(members, rs, local)
        if len({m["계산"]["합산묶음"] for m in members}) >= 2:
            first = min(m["판정"]["양도일"] for m in members)
            whole = sum(_i(m["계산"]["과세표준"]) for m in members)
            if _floor(_progressive(whole, rs.value(table_key, first))) > sum(cols.values()):
                raise _Undetermined("자산 %s 의 %s합산 비교세액이 세율별 세액의 합보다 커서 예정신고 세액을 정할 수 없다"
                                    % (", ".join(m["id"] for m in members), "지방소득세 " if local else ""))
        return cols

    def expected_penalty(self, local=False):
        """다시 계산한 가산세. {"합계": (무신고, 납부지연), "열": {표기: (무신고, 납부지연)}} 또는 {"불가": 까닭}.
        local 이면 지방소득세 가산세다. 예정신고와 과세 자산이 없는 신고는 모두 0 이다. 한 번만 계산한다.
        국세와 지방 가운데 한쪽이라도 정할 수 없으면 신고값이 둘 다 0 으로 두므로 둘 다 「불가」다."""
        if self._penalty is None:
            labels = ["%s-%s" % (x["국내외분"], x["세율구분"]) for x in self.calc.get("세율별") or []]
            both = {}
            for side in (False, True):
                try:
                    total, cols = self._recalculate(labels, side)
                    both[side] = {"합계": total, "열": cols}
                except _Undetermined as e:
                    both[side] = {"불가": str(e)}
                except ruleset.RuleError as e:      # 기한·세율표 규칙이 그 날짜에 없다. 검산을 건너뛰지 않고 실패로 알린다
                    self.fail("규칙세트에서 %s가산세를 다시 계산할 값을 읽지 못했다(%s)" % ("지방소득세 " if side else "", e))
                    both[side] = {"불가": "규칙세트 값을 읽지 못했다"}
            blocked = next((both[side] for side in (False, True) if "불가" in both[side]), None)
            self._penalty = {False: blocked or both[False], True: blocked or both[True]}
        return self._penalty[local]

    def _recalculate(self, labels, local=False):
        cols = {name: [0, 0] for name in labels}
        sin = self.rv["신고"]
        taxed = [r for r in self.calc["자산"] if not r["판정"].get("전액비과세")]
        if sin["구분"] != "확정" or not taxed:
            return (0, 0), {k: (0, 0) for k in cols}
        rs = self.rules()
        if rs is None:
            raise _Undetermined("규칙세트를 읽지 못했다")
        paid = dates.to_date(_iso(sin["작성일"]))
        rate_key, daily_key, paid_day_key, unit = (LOCAL_PENALTY_KEYS + (LOCAL_PENALTY_UNIT,) if local else
                                                   PENALTY_KEYS + (PENALTY_LATE_UNIT,))
        factor = Decimal(str(self.penalty_rule(rate_key, paid)))        # 감면율은 곱하지 않는다
        daily, paid_day = Decimal(str(self.penalty_rule(daily_key, paid))), int(self.penalty_rule(paid_day_key, paid))
        deadline = dates.local_filing_deadline if local else dates.filing_deadline
        grouped = {}
        for r in sorted(taxed, key=lambda r: (r["판정"]["양도일"], r["id"])):
            base = self.deadline_base(r)
            # 건은 국세 예정신고 기한의 말일이 같은 자산의 묶음이다. 지방소득세도 같은 묶음으로 세고 납부기한만 지방 기한을 쓴다
            grouped.setdefault(dates.filing_deadline("예정", base, rs)[0], (deadline("예정", base, rs)[1], []))[1].append(r)
        cases = []
        for nominal in sorted(grouped):
            adjusted, members = grouped[nominal]
            by_col = self.case_tax(members, rs, local)
            days = None if paid <= adjusted else (paid - adjusted).days - 1 + paid_day
            cases.append((by_col, sum(by_col.values()), days))
        due = [i for i, c in enumerate(cases) if c[2] is not None]
        total = _floor(Decimal(sum(cases[i][1] for i in due)) * factor)
        nonfiling, late = [0] * len(cases), [0] * len(cases)
        for i in due:
            nonfiling[i] = _floor(Decimal(cases[i][1]) * factor)
            late[i] = _floor(Decimal(cases[i][1]) * cases[i][2] * daily) // unit * unit
        if due:
            top = max(due, key=lambda i: (cases[i][1], -i))
            nonfiling[top] += total - sum(nonfiling)
        for (by_col, _, _), a, b in zip(cases, nonfiling, late):
            names, weights = list(by_col), list(by_col.values())
            for k, amount in ((0, a), (1, b)):
                for name, part in zip(names, _share(amount, weights)):
                    cols.setdefault(name, [0, 0])[k] += part
        return (total, sum(late)), {k: tuple(v) for k, v in cols.items()}

    def penalty(self):
        """본지 ⑯ 가산세 네 줄과 신고값 「가산세」 절을 다시 계산한 값과 대조한다. 지방 서식 ⑬ 과 「가산세.지방」 도 같다."""
        section = self.rv.get("가산세")
        self.penalty_cells("본지", self.rv["본지"], self.expected_penalty(False), section, self.nat_win, "⑯",
                           NAT_PENALTY_ROWS, "신고값 가산세 절")
        local_section = section.get("지방") if isinstance(section, dict) else None
        self.penalty_cells("지방", self.rv["지방"], self.expected_penalty(True), local_section, self.local_win, "⑬",
                           LOCAL_PENALTY_ROWS, "신고값 가산세 절 지방")

    def penalty_cells(self, form_name, form, exp, section, win, no, rows, section_name):
        cols = form["열"]
        labels = [x["표기"] for x in form["세율구분"]]
        kind = self.rv["신고"]["구분"]
        why = "예정신고에는 예정신고 무신고·납부지연 가산세가 없다" if kind != "확정" else "다시 계산한 값"
        other = rows[2]
        if "불가" in exp:
            for n in ["합계", "국내소계"] + labels:
                c = cols.get(n) or {}
                for key, _, name in rows + (("가산세", no, "가산세 계"),):
                    if _i(c.get(key)):
                        self.fail("%s %s %s %s %s ≠ 0 (가산세를 정할 수 없는 건이라 0 이어야 한다. %s)"
                                  % (form_name, _col(n), no, name, _w(c.get(key)), exp["불가"]))
            whole = self.rv.get("가산세")
            if rows is NAT_PENALTY_ROWS and (not isinstance(whole, dict) or whole.get("계산") is not False):
                self.fail("신고값 가산세 절이 계산하지 못했다고 적지 않았다(가산세를 정할 수 없는 건이다. %s)" % exp["불가"])
            return
        total = exp["합계"]
        domestic = [x for x in labels if x.startswith("1")]
        want = {"합계": total, "국내소계": (sum(exp["열"].get(x, (0, 0))[0] for x in domestic),
                                      sum(exp["열"].get(x, (0, 0))[1] for x in domestic)), "국외소계": (0, 0)}
        want.update({x: exp["열"].get(x, (0, 0)) for x in labels})
        for n in ["합계", "국내소계"] + labels + ["국외소계"]:
            c = cols.get(n)
            if c is None:
                continue
            a, b = want[n]
            for (key, _, name), value in zip(rows, (a, b, 0)):
                got = c.get(key)
                if got is None and n != "합계":
                    # 합산 비교세액이 이긴 신고서는 가산세를 합계 열에만 적는다. 이기지 않았는데 비어 있으면 열 합 검사가 건너뛴다
                    if value and not win:
                        self.fail("%s %s %s %s 칸이 비어 있다(%s %s)" % (form_name, _col(n), no, name, why, _w(value)))
                    continue
                if _i(got) != value:
                    self.fail("%s %s %s %s %s ≠ %s %s" % (form_name, _col(n), no, name, _w(got), why, _w(value)))
        whole = self.rv.get("가산세")
        if kind != "확정":
            if whole is not None and rows is NAT_PENALTY_ROWS:
                self.fail("%s이 예정신고인데 비어 있지 않다" % section_name)
            return
        if rows is not NAT_PENALTY_ROWS:
            if not isinstance(whole, dict) or whole.get("계산") is not True:
                return                      # 국세 쪽 검사가 이미 알렸다
            if not isinstance(section, dict):
                self.fail("신고값 가산세 절에 지방이 없다(다시 계산한 지방소득세 가산세는 무신고 %s, 납부지연 %s, 계 %s 이다)"
                          % (_w(total[0]), _w(total[1]), _w(sum(total))))
                return
        elif not isinstance(section, dict) or section.get("계산") is not True:
            if sum(total) or not isinstance(section, dict):
                self.fail("%s이 계산하지 못했다고 적었는데 다시 계산한 가산세는 무신고 %s, 납부지연 %s, 계 %s 이다"
                          % (section_name, _w(total[0]), _w(total[1]), _w(sum(total))))
            return
        for key, value in (("무신고", total[0]), ("납부지연", total[1]), ("계", sum(total))):
            if _i(section.get(key)) != value:
                self.fail("%s %s %s ≠ 다시 계산한 값 %s" % (section_name, key, _w(section.get(key)), _w(value)))

    # ------------------------------------------------------------ 지방

    def local(self):
        form = self.rv["지방"]
        cols = form["열"]
        main = self.rv["본지"]["열"]
        self.check_labels("지방", form["세율구분"])
        labels = [x["표기"] for x in form["세율구분"]]
        main_labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        if labels != main_labels:
            self.fail("지방 세율구분 열 %s 이 본지 %s 와 다르다" % (", ".join(labels) or "없음", ", ".join(main_labels) or "없음"))
        names = ["합계", "국내소계"] + labels + ["국외소계"]
        for n in names:
            c = self.column("지방", cols, n)
            if c is None:
                continue
            cn = "지방 " + _col(n)
            if n == "합계":
                self.total_payment_filled("지방", c, LOCAL_TOTAL_REQUIRED, LOCAL)
            m = main.get(n)
            if m is not None:
                self.same(c.get("과세표준"), m.get("과세표준"), cn + " ⑤ 과세표준", "본지 %s ⑧" % _col(n))
            self.same(c.get("가산세"), sum(_i(c.get(k)) for k in LOCAL_PENALTY), cn + " ⑬ 가산세 합계", "세 칸 합")
            if c.get("납부할세액") is not None:
                due = (_i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                       - _i(c.get("연금계좌")) - _i(c.get("전자신고공제")) + _i(c.get("가산세")) - _i(c.get("기신고세액")))
                self.same(c.get("납부할세액"), due, cn + " ⑮ 납부할 총세액", "⑦-⑧-⑨-⑩-⑪-⑫+⑬-⑭")
                if c.get("신고기한내납부") is not None:
                    self.same(c.get("신고기한내납부"), c.get("납부할세액"), cn + " 신고기한내 납부", "⑮ 납부할 총세액")
        self.sums("지방", cols, labels, LOCAL + LOCAL_PENALTY_ROWS, LOCAL_WIN, self.local_win)
        self.column_due_filled("지방", cols, labels, self.local_win, "⑮ 납부할 총세액")
        self.local_filing_credit(cols, [n for n in names if n in cols])

    def local_filing_credit(self, cols, names):
        """지방 ⑫ 전자신고세액공제. 예정신고 합계 열은 min(규칙세트 금액, ⑦-⑧-⑨-⑩-⑪)(음수면 0)와 같아야 하고 다른 열은
        그 이하이면 된다. 확정신고는 0 이고 규칙 키를 부르지 않는다."""
        sin = self.rv["신고"]
        if sin["구분"] == "예정":
            cap, why = self.rule("지방.전자신고세액공제.예정", _iso(sin["작성일"])), "예정신고 한도"
        elif sin["구분"] == "확정":
            cap, why = 0, "확정신고에는 지방소득세 전자신고세액공제가 없다"
        else:
            return
        for n in names:
            c = cols[n]
            got = _i(c.get("전자신고공제"))
            if n != "합계" and got == 0:
                continue
            room = max(0, _i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                       - _i(c.get("연금계좌")))
            if got < 0:
                self.fail("지방 %s ⑫ 전자신고세액공제 %s 가 음수다" % (_col(n), _w(c.get("전자신고공제"))))
            elif cap is None:
                continue
            elif n == "합계" and got != min(int(cap), room):
                self.fail("지방 합계 ⑫ 전자신고세액공제 %s ≠ %s (%s %s, 산출세액에서 ⑧~⑪ 을 뺀 %s)"
                          % (_w(c.get("전자신고공제")), _w(min(int(cap), room)), why, _w(int(cap)), _w(room)))
            elif n != "합계" and got > min(int(cap), room):
                self.fail("지방 %s ⑫ 전자신고세액공제 %s 이 한도 %s 를 넘는다(%s, 산출세액에서 ⑧~⑪ 을 뺀 %s)"
                          % (_col(n), _w(c.get("전자신고공제")), _w(min(int(cap), room)), why, _w(room)))

    # ------------------------------------------------------------ 엔진 대조

    def engine_assets(self):
        rows = self.rv["부표1"]
        ids = [r["자산"] for r in rows]
        eng_ids = self.taxed                               # 전액 비과세 자산은 신고서에 넣지 않는다
        if ids != eng_ids:
            self.fail("부표1 자산 [%s] ≠ 엔진 자산 [%s]" % (", ".join(ids), ", ".join(eng_ids)))
        for r in rows:
            e = self.eng.get(r["자산"])
            if e is None:
                continue
            aid, v, c = r["자산"], e["판정"], e["계산"]
            for key, label, no in (("양도일", "양도일", "④"), ("취득일", "취득일", "⑤")):
                if r.get(key) != v.get(key):
                    self.fail("부표1 %s %s %s %s ≠ 엔진 %s" % (aid, no, label, _w(r.get(key)), _w(v.get(key))))
            for key, no, name in (("양도가액", "⑪", "양도가액"), ("양도차익", "", "양도차익"), ("비과세양도차익", "", "비과세양도차익"),
                                  ("과세양도차익", "⑮", "과세양도차익"), ("장특공", "⑯", "장기보유특별공제"),
                                  ("양도소득금액", "⑱", "양도소득금액")):
                if c.get(key) is not None:
                    self.same(r.get(key), c[key], "부표1 %s %s%s" % (aid, no + " " if no else "", name), "엔진")
            if c.get("취득가액") is not None:
                self.same(_i(r.get("취득가액")) + _i(r.get("기타필요경비")), _i(c["취득가액"]) + _i(c.get("필요경비")),
                          "부표1 %s ⑫ 취득가액 + ⑭ 기타필요경비" % aid, "엔진 취득가액 + 필요경비")
            self.engine_codes(r, v, c)
            if r.get("지분분모") and r.get("지분분자") is not None and c.get("전체양도가액") is not None:
                mine = Fraction(int(r["지분분자"]), int(r["지분분모"])) * Fraction(int(c["전체양도가액"]))
                self.same(mine.numerator // mine.denominator, c["양도가액"],
                          "부표1 %s 지분 %s/%s 로 나눈 전체양도가액" % (aid, r["지분분자"], r["지분분모"]), "엔진 양도가액")

    def engine_codes(self, r, v, c):
        """서식에 코드나 말로 옮겨 적은 칸이 엔진 판정과 맞는가. 값을 서식 표기로 바꾸는 표는 forms/서식판.json 과 이 파일 위쪽의 표다."""
        aid = r["자산"]
        try:
            kind = str(int(c["코드"]["자산종류"]))
        except (KeyError, ValueError):
            kind = None
        if kind is not None and r.get("자산종류") != kind:
            self.fail("부표1 %s ③ 자산종류 %s ≠ 엔진 자산종류 코드 %s 의 서식 표기 %s" % (aid, _w(r.get("자산종류")), c["코드"]["자산종류"], kind))
        label = ACQ_LABEL.get(c.get("취득가액방법"), "")
        if (r.get("취득가액종류") or "") != label:
            self.fail("부표1 %s 취득가액종류 %s ≠ 엔진 취득가액방법 %s 의 서식 표기 %s" % (aid, _w(r.get("취득가액종류")), _w(c.get("취득가액방법")), _w(label)))
        codes = self.ltd_codes()
        if codes is not None and v.get("장특공") in codes and r.get("장특공코드") != codes[v["장특공"]]:
            self.fail("부표1 %s ⑯ 장기보유특별공제 코드 %s ≠ 엔진 판정 %s 의 서식 코드 %s"
                      % (aid, _w(r.get("장특공코드")), v["장특공"], codes[v["장특공"]]))

    def ltd_codes(self):
        """판정의 장특공 값(없음, 표1, 표2) → 부표1 ⑯ 코드."""
        if not hasattr(self, "_ltd"):
            with open(os.path.join(self.forms_dir, "서식판.json"), encoding="utf-8") as f:
                self._ltd = json.load(f)["부표1_장특공코드"]["코드"]
        return self._ltd

    def engine_columns(self):
        """엔진 결과를 세율구분 표기별로 모은다. 전액비과세 자산은 열이 없다."""
        out = {}
        for r in self.calc["자산"]:
            if r["판정"].get("전액비과세"):
                continue
            k = "%s-%s" % (r["계산"]["코드"]["국내외분"], r["계산"]["코드"]["세율구분"])
            x = out.setdefault(k, {"양도소득금액": 0, "기본공제": 0})
            x["양도소득금액"] += _i(r["계산"]["양도소득금액"])
            x["기본공제"] += _i(r["계산"]["기본공제"])
        return out

    def engine_main(self):
        cols = self.rv["본지"]["열"]
        labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        eng_rates = {"%s-%s" % (x["국내외분"], x["세율구분"]): x for x in self.calc["세율별"]}
        if labels != list(eng_rates):
            self.fail("본지 세율구분 열 [%s] ≠ 엔진 세율별 [%s]" % (", ".join(labels), ", ".join(eng_rates)))
        eng_cols = self.engine_columns()
        for label in labels:
            c, e, g = cols.get(label), eng_rates.get(label), eng_cols.get(label)
            if c is None or e is None:
                continue
            self.same(c.get("과세표준"), e["과세표준"], "본지 %s 열 ⑧ 과세표준" % label, "엔진 세율별")
            self.same(c.get("산출세액"), e["산출세액"], "본지 %s 열 ⑩ 산출세액" % label, "엔진 세율별")
            if g is not None:
                self.same(c.get("양도소득금액"), g["양도소득금액"], "본지 %s 열 ④ 양도소득금액" % label, "엔진")
                self.same(c.get("기본공제"), g["기본공제"], "본지 %s ⑦ 기본공제" % label, "엔진")
        t = self.calc["합계"]
        total = cols.get("합계")
        if total is not None:
            self.same(total.get("과세표준"), t["과세표준"], "본지 합계 ⑧ 과세표준", "엔진")
            self.same(total.get("산출세액"), t["산출세액"], "본지 합계 ⑩ 산출세액", "엔진")
            self.same(total.get("양도소득금액"), sum(g["양도소득금액"] for g in eng_cols.values()), "본지 합계 ④ 양도소득금액", "엔진")
            self.same(total.get("기본공제"), sum(g["기본공제"] for g in eng_cols.values()), "본지 합계 ⑦ 기본공제", "엔진")
        sub = cols.get("국내소계")
        if sub is not None:
            self.same(sub.get("산출세액"), sum(e["산출세액"] for k, e in eng_rates.items() if k.startswith("1-")),
                      "본지 국내소계 ⑩ 산출세액", "엔진 세율별 합")

    def engine_local(self):
        cols = self.rv["지방"]["열"]
        t = self.calc["합계"]
        total = cols.get("합계")
        if total is not None:
            self.same(total.get("과세표준"), t["과세표준"], "지방 합계 ⑤ 과세표준", "엔진")
            self.same(total.get("산출세액"), t["지방소득세"], "지방 합계 ⑦ 산출세액", "엔진 지방소득세")
        labels = [x["표기"] for x in self.rv["지방"]["세율구분"]]
        if all(x in cols for x in labels):
            self.same(sum(_i(cols[x].get("산출세액")) for x in labels), t["지방_호별합산"], "지방 세율구분 열 ⑦ 합",
                      "엔진 호별합산")
        # 열마다: 엔진은 지방소득세를 합계로만 내므로 과세 자산의 과세표준과 적용세율로 열의 세액을 다시 구한다.
        # 합만 보면 두 열 사이에서 옮긴 금액을 놓친다. 합산 비교세액이 이겨도 열은 세율구분별 세액이다
        rs = self.rules()
        if rs is None:
            return
        taxed = [x for x in self.calc["자산"] if not x["판정"].get("전액비과세")]
        try:
            want = self.column_tax(taxed, rs, local=True)
        except ruleset.RuleError as e:
            self.fail("규칙세트에서 지방 세율구분 열의 세액을 다시 계산할 값을 읽지 못했다(%s)" % e)
            return
        for x in labels:
            if x in cols and x in want:
                self.same(cols[x].get("산출세액"), want[x], "지방 %s 열 ⑦ 산출세액" % x, "엔진 과세표준에 지방소득세 세율을 적용한 값")

    def engine_dates(self):
        """규칙세트를 읽는 날짜와 판이 엔진 결과와 맞는가. 신고 절의 양도일자가 틀리면 분납 한도를 다른 날의 규칙으로 읽는다."""
        sin = self.rv["신고"]
        last = max(self.eng[aid]["판정"]["양도일"] for aid in self.taxed)
        got = _iso(sin["양도일자"])
        if got != last:
            self.fail("신고 절 양도일자 %s ≠ 엔진 과세 자산의 마지막 양도일 %s" % (_w(got), last))
        made = _iso(sin["작성일"])
        if dates.to_date(made) < dates.to_date(last):
            self.fail("신고 절 작성일 %s 이 엔진 과세 자산의 마지막 양도일 %s 보다 앞선다" % (_w(made), last))
        want = (self.result.get("기준정보") or {}).get("판")
        have = (self.rv.get("판") or {}).get("기준정보")
        if have != want:
            self.fail("신고값 판의 기준정보 %s ≠ 엔진 결과의 기준정보 판 %s" % (_w(have), _w(want)))

    # ------------------------------------------------------------ 전자신고 절 ↔ 본지·부표1

    def efile_section(self):
        """신고값 「전자신고」 절의 03·05 금액을 본지·부표1 과 대조한다. 07 행은 자산이 부표1 에 있는지만 본다. 신고값만 읽는다."""
        sec = self.rv["전자신고"]
        self.efile_rates(sec["세율별"])
        self.efile_assets(sec["계산명세"])
        form_ids = [r["자산"] for r in self.rv["부표1"]]
        for aid in dict.fromkeys(x.get("자산") for x in sec.get("필요경비명세") or []):
            if aid not in form_ids:
                self.fail("전자신고 필요경비명세의 자산 %s 가 부표1 에 없다" % _w(aid))

    def efile_rates(self, rows):
        cols = self.rv["본지"]["열"]
        labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        names = _named(NAT)
        sub_key, total_key = _special_rows(self.efile_dir)
        by = {}
        for x in rows:
            k = (str(x["국내외분"]), str(x["세율구분"]))
            if k in by:
                self.fail("전자신고 세율별에 %s/%s 행이 둘 이상 있다" % k)
            by[k] = x

        def compare(x, row_name, col_name, pairs):
            c = cols.get(col_name)
            if c is None:
                return
            for key, main_key in pairs:
                self.same(x[key], c.get(main_key), "전자신고 세율별 %s %s" % (row_name, key),
                          "본지 %s %s" % (_col(col_name), names[main_key]))

        total = by.get(total_key)
        if total is None:
            self.fail("전자신고 세율별에 합계 행(%s/%s)이 없다" % total_key)
        else:
            compare(total, "합계 행", "합계", EFILE_TOTAL)
        sub = by.get(sub_key)
        if sub is None:
            self.fail("전자신고 세율별에 국내소계 행(%s/%s)이 없다" % sub_key)
        else:
            compare(sub, "국내소계 행", "국내소계", EFILE_BASE + (() if self.nat_win else (EFILE_TAX,)))
        rate = {"%s-%s" % k: x for k, x in by.items() if k not in (sub_key, total_key)}
        for label in labels:
            if label not in rate:
                self.fail("전자신고 세율별에 본지 %s 열의 행이 없다" % label)
        for label, x in rate.items():
            if label not in labels or label not in cols:
                self.fail("전자신고 세율별 %s 행에 맞는 본지 열이 없다" % label)
                continue
            pairs = EFILE_BASE
            if not self.nat_win:      # 합산 비교세액이 이기면 03 행은 합계 산출세액을 나눠 적어 본지 열과 다르다
                pairs += (EFILE_TAX,) + tuple(p for p in EFILE_RATE_PAYMENT if cols[label].get(p[1]) is not None)
            compare(x, label + " 행", label, pairs)
        if rate and "합계" in cols:
            self.same(sum(_i(x[EFILE_TAX[0]]) for x in rate.values()), cols["합계"].get("산출세액"),
                      "전자신고 세율별 세율구분 행 산출세액 합", "본지 합계 %s" % names["산출세액"])
        if self.nat_win:
            self.efile_allocation(rate)
        self.efile_penalty(total, sub, rate)

    def efile_allocation(self, rate):
        """합산 비교세액이 이긴 신고서의 03 세율구분 행 산출세액. 합계 행 = 세율구분 행 합이어야 해서(규격서 p40 10번
        「합계와 세율구분별 산출세액 합계와 일치」) 합계 산출세액을 세율구분 행에 과세표준 비율로 나눠 적는다. 같은 10번의
        「각각의 8.과세표준 기준으로 안분함」은 세율구분 1-10 과 1-11(지정지역)의 과세표준을 합산해 계산한 경우를 두고 한
        말이다. 합산 비교세액이 이긴 경우를 어떻게 나누는지는 규격서에 없어, 생성기가 그 지정지역 문장의 방법을 이 경우에도
        같게 썼다. 원 미만은 버리고 남는 원은 과세표준이 가장 큰 행(같으면 엔진 세율별의 앞 행)에 더한다. 행 합만 보면 두 행
        사이에서 옮긴 금액을 놓치므로 엔진 결과의 합계 산출세액과 세율별 과세표준으로 다시 나눠 행마다 대조한다."""
        eng = self.calc["세율별"]
        labels = ["%s-%s" % (x["국내외분"], x["세율구분"]) for x in eng]
        parts = _share(_i(self.calc["합계"]["산출세액"]), [_i(x["과세표준"]) for x in eng])
        for label, part in zip(labels, parts):
            x = rate.get(label)
            if x is not None:
                self.same(x[EFILE_TAX[0]], part, "전자신고 세율별 %s 행 산출세액" % label, "합계 산출세액을 과세표준 비율로 나눈 값")

    def efile_penalty(self, total, sub, rate):
        """03 행의 가산세 칸(15 신고불성실, 16 납부불성실, 17 계, 35 기장불성실등)을 다시 계산한 값과 대조한다.
        합계·국내소계 행은 합계, 세율구분 행은 그 열의 값이다. 본지 열이 비어 있어도(합산 비교세액이 이긴 신고서) 03 행은 적는다.
        행 안의 산식 19 자진납부할세액 = 10 산출세액 - 36 전자신고세액공제 + 17 가산세-계 도 본다."""
        exp = self.expected_penalty(False)
        zero = "불가" in exp
        rows = [("합계 행", total, (0, 0) if zero else exp["합계"]), ("국내소계 행", sub, (0, 0) if zero else exp["합계"])]
        rows += [(label + " 행", x, (0, 0) if zero else exp["열"].get(label, (0, 0))) for label, x in rate.items()]
        why = "가산세를 정할 수 없는 건이라 0 이어야 한다" if zero else "다시 계산한 가산세"
        for name, x, (a, b) in rows:
            if x is None:
                continue
            want = (a, b, a + b)
            for key, k in EFILE_PENALTY:
                if _i(x[key]) != want[k]:
                    self.fail("전자신고 세율별 %s %s %s ≠ %s %s" % (name, key, _w(x[key]), why, _w(want[k])))
            if _i(x[EFILE_PENALTY_OTHER]):
                self.fail("전자신고 세율별 %s %s %s ≠ 0 (기장불성실 등 가산세는 계산하지 않는다)"
                          % (name, EFILE_PENALTY_OTHER, _w(x[EFILE_PENALTY_OTHER])))
            due = _i(x["산출세액"]) - _i(x["전자신고세액공제"]) + _i(x["가산세-계"])
            self.same(x["자진납부할세액"], due, "전자신고 세율별 %s 자진납부할세액" % name, "산출세액-전자신고세액공제+가산세-계")

    def efile_assets(self, rows):
        sheet = self.rv["부표1"]
        names = _named(SHEET1_MONEY)
        ids, form_ids = [x["자산"] for x in rows], [r["자산"] for r in sheet]
        if ids != form_ids:
            self.fail("전자신고 계산명세 자산 [%s] ≠ 부표1 자산 [%s]" % (", ".join(map(str, ids)), ", ".join(map(str, form_ids))))
        by = {r["자산"]: r for r in sheet}
        for x in rows:
            r = by.get(x["자산"])
            if r is None:
                continue
            for key, form_key in EFILE_ASSET:      # 부표1 칸이 비어 있으면 0 과 견준다
                self.same(x[key], r.get(form_key), "전자신고 계산명세 %s %s" % (x["자산"], key),
                          "부표1 %s %s" % (x["자산"], names[form_key]))


def check(rv, result, rules_dir=None, efile_dir=None, forms_dir=None, facts=None):
    """신고값 rv(C8)와 엔진 결과 result(C4)로 서식 값을 검산한다. 실패 문장 목록을 돌려주고, 비면 통과.

    facts 는 사실관계(C1)다. 확정신고 가산세를 다시 계산할 때 허가구역 토지의 허가일을 여기서 읽는다. 확정신고에 주지 않으면
    검산하지 않고 한 문장으로 실패한다. 예정신고는 없어도 된다."""
    return _Check(rv, result, rules_dir, efile_dir, forms_dir, facts).run()
