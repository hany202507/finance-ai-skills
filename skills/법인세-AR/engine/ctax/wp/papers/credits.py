"""20 공제감면: 중소기업특별세액감면 · 통합고용세액공제 · 연구 · 인력개발비 세액공제 · 이월공제 · 최저한세.
서식 4 · 8갑 · 8을 · 8부표2 · 8부표3 · 조특2 · 조특10의9 · 조특3_1 · 48.

계산이 두 번이다. `compute` 가 회사 판정(업종 · 수도권 · 소기업)과 노란 칸(당기분 · 이월액)을 읽고, 3호 산출세액이 나온 뒤
`after_tax` 가 감면세액 · 최저한세 · 공제 순서를 계산해 3호 17 · 19 기본값을 넘긴다(summary.py 공제감면 부분, CONTRACT.md 15절).
엑셀도 계산 부분은 3호 시트가 생긴 뒤 `write_after` 가 쓴다.

기초자료로 계산하는 것은 중소기업특별세액감면(조특법 제7조)과 전기에서 넘어온 이월공제다. 통합고용세액공제(제29조의8)는
사람이 상시근로자 수를 넣으면 계산하고, 일반 연구 · 인력개발비 세액공제(제10조 제1항 제3호)는 사람이 대상 금액을 넣으면
계산한다(아래). 그 밖에 자료가 필요한 공제(창업감면 · 통합투자 · 고용증대)는 계산하지 않고 노란 칸(기본 0)에 「자료 필요」.

감면 소득(fx3). 중소기업특별세액감면은 감면 업종 사업장에서 생긴 소득에만 준다(조특법 제7조 제1항, 법인세법 제59조 제2항:
산출세액 × 감면 소득 / 과세표준). 수입이자 · 유가증권 처분손익 · 고정자산 처분손익은 감면 업종 소득에 더하거나 빼지 않는다(국세청
법인46012-1560, 2000.7.13). 그래서 노란 칸 「감면 제외 소득」 기본값을 영업외수익 중 이자 · 배당 · 임대료 · 유가증권 · 유형자산
처분손익의 순액으로 둔다. 잡이익 · 외환차익은 감면 사업과 관련 있는지 따라 갈려 넣지 않는다.
이월결손금 · 비과세 · 소득공제는 감면 소득과 다른 소득에 비례해 나눈다(법인세법 시행령 제96조 제2호).

소득 구분계산(r6, 48호 소득구분계산서). 감면 사업과 그 밖의 사업을 함께 하면 구분경리하고, 나눌 수 없는 공통 익금 · 공통 손금은
안분한다(조특법 제143조 제1항, 법인세법 시행규칙 제75조 제2항 · 제76조 제6항). 장부만으로는 두 사업의 개별 손익을 가를 수 없어
회계사가 노란 칸 「소득구분/…」 에 그 밖의 사업의 매출액 · 매출원가 · 판관비 개별분 · 세무조정 순액과 판관비 · 영업외수익 ·
영업외비용의 공통분을 넣는다. 엔진은 넣은 값으로만 계산한다.
  공통 익금의 그 밖의 사업 몫 = 공통 익금 × 그 밖의 사업 수입금액 / 수입금액 합계(제76조 제6항 제1호)
  공통 손금의 그 밖의 사업 몫 = 공통 손금 × 그 밖의 사업 수입금액 / 수입금액 합계(업종이 같을 때, 제2호)
                              또는 공통 손금 × 그 밖의 사업 개별 손금 / 개별 손금 합계(업종이 다를 때, 제3호)
  그 밖의 사업 소득 = 감면 제외 소득 + 그 밖의 사업 매출액 - 매출원가 - 판관비 개별분 + 세무조정 순액 + 공통 익금 몫 - 공통 손금 몫
  감면 사업 소득 = 각사업연도소득 - 그 밖의 사업 소득(그 밖의 사업이 결손이면 각사업연도소득, 조특법 제143조 제3항)
  감면 대상 소득 = 감면 사업 소득 × 과세표준 / 각사업연도소득
노란 칸을 모두 기본값(0)으로 두면 그 밖의 사업 소득 = 감면 제외 소득이라 fx3 계산과 같다. 수입금액은 매출액이고, 매출액이 아닌
수입을 안분 기준에 넣을지는 회계사가 「소득구분/안분 기준 가산/기타」 로 정한다. 업종이 같은지(한국표준산업분류 소분류,
제75조 제2항 후단)도 회계사가 「소득구분/공통 손금 안분 기준」(수입금액 · 개별손금)으로 고른다.

통합고용세액공제(r6, 조특법 제29조의8, 조특 10호의9). 상시근로자 수는 급여 자료가 있어야 해서 사람이 넣는다. 넣는 곳은
`_색인/신고건.json` 의 선택 키 「상시근로자」 이고(9호 「가산세」 와 같은 방식) 조서 노란 칸 「통합고용/…」 으로도 고친다:

    "상시근로자": {"해당":   {"청년등": 3.5, "청년등 외": 9},      해당 과세연도(소수 둘째 자리까지, 「전체」 로 적어도 된다)
                   "직전":   {"청년등": 2,   "청년등 외": 9},      직전 과세연도. 창업 첫 해라 0 이면 0 으로 적는다
                   "직전전": {"청년등": 2,   "청년등 외": 8},      3차 연도 공제를 볼 때만
                   "1차년도 공제액": {"직전":   {"청년등": 14500000, "청년등 외": 0},     전기 조특 10호의9 의 1차년도 세액공제액
                                      "직전전": {"청년등": 0, "청년등 외": 8500000}},
                   "기업 구분": "중소기업", "증가 지역 수도권": "여",
                   "정규직 전환 인원": 0, "육아휴직 복귀 인원": 1}     추가공제(r8, 아래)

  1차 연도 = min(청년등 증가, 전체 증가) × 1인당 금액 + min(청년등 외 증가, 전체 증가) × 1인당 금액(전체가 늘었을 때만, 제1항)
  2차 연도 = 직전 과세연도 1차년도 공제액(전체가 직전보다 줄면 0, 청년등만 줄면 청년등 몫 0, 제3항)
  3차 연도 = 직전전 과세연도 1차년도 공제액(중소 · 중견기업만, 직전 · 해당 어느 해든 직전전보다 줄었으면 위와 같이 끊김)
1인당 금액은 2025년 12월 31일이 속하는 과세연도까지의 것이다(rates_2025/credits.yaml employment_integrated, 그 뒤 과세연도의
1차 연도는 계산하지 않는다). 계산한 금액은 노란 칸 「당기분/통합고용세액공제」 의 기본값이 되어 18S 줄(최저한세 · 이월)로 간다.
인원을 넣지 않으면 0 이고 「자료 필요」 다. 전기.json `employment["10의9"]["headcount"]` 가 있으면 직전 · 직전전 인원 기본값으로 쓴다.

통합고용 추가공제(r8, 조특법 제29조의8 제4항 · 제5항). 「상시근로자」 에 「정규직 전환 인원」 · 「육아휴직 복귀 인원」 을 적으면
인원 × 1,300만원(중견기업 900만원)을 계산한다. 중소 · 중견기업만 받고, 해당 과세연도 상시근로자 수가 직전보다 줄었으면 0 이다.
정규직 전환은 2024년 1월 1일부터 2024년 12월 31일까지 전환한 인원만이라 과세연도가 그 기간에 걸칠 때만 계산하고, 육아휴직
복귀는 2026년 12월 31일까지 복직한 인원이다. 8호(갑) 줄이 기본공제(18S)와 따로라(1B4 · 1B5) 노란 칸
「당기분/통합고용세액공제(정규직 전환)」 · 「당기분/통합고용세액공제(육아휴직 복귀)」 의 기본값이 된다. 전환일 · 복직일부터 2년 안에
근로관계를 끝냈을 때의 납부(제7항)는 계산하지 않는다.

추가 납부세액(r8, 조특법 제29조의8 제3항 후단 · 시행령 제26조의8 제4항, 고용증대는 제29조의7 제2항 후단 · 시행령 제26조의7 제5항).
최초 공제 과세연도보다 전체 또는 청년등 상시근로자 수가 줄면 공제받은 세액을 낸다. `clawback` 이 시행령의 식을 그대로 계산한다:
  D전 · D청 · D외 = 최초 공제 과세연도 대비 전체 · 청년등 · 청년등 외 감소 인원, A1 · A2 = 제1항 제1호 · 제2호의 1인당 금액
  전체 감소, D청 ≥ D전   [min(D청, 최초 연도 청년등 증가 인원) - D전] × (A1 - A2) + D전 × A1          (가목 1))
  전체 감소, 그 밖        min(D청, D전) × A1 + min(D외, D전) × A2                                      (가목 2))
  청년등만 감소           min(D청, 최초 연도 청년등 증가 인원) × (A1 - A2)                              (나목)
당기가 최초 공제 다음 해(2차 연도)면 제1호라 위 금액이고 직전 1년 이내 공제받은 세액이 한도다. 그다음 해(3차 연도)면 제2호라 직전
2년 이내 공제받은 횟수를 곱하고, 제1호로 계산한 금액을 빼고, 직전 2년 이내 공제받은 세액 합계가 한도다. 통합고용은 이월된 금액을
뺀다(제3항 후단 괄호, 노란 칸 「이월 차감」). 당기 인원 · 최초 공제 연도 인원 · 그해 공제액 · 최초 연도 청년등 증가 인원 가운데
하나라도 없으면 계산하지 않고 확인 줄만 낸다. 계산한 금액의 합은 3호 (133) 감면분 추가납부세액(조서 3호 29 노란 칸) 기본값이 된다.

일반 연구 · 인력개발비 세액공제 당기 발생분(r7, 조특법 제10조 제1항 제3호, 조특 3호(1)). 장부의 연구개발비 계정에는 공제 대상이
아닌 비용이 섞여 있어(시행령 제9조 제1항 · 별표 6) 엔진은 계정 금액을 대상 금액으로 쓰지 않는다. 사람이 `_색인/신고건.json` 의
선택 키 「연구인력개발비」 에 넣고 조서 노란 칸 「연구인력개발비/…」 으로도 고친다:

    "연구인력개발비": {"해당": 600000000,                      해당 과세연도 일반 연구 · 인력개발비 발생액(원)
                       "직전 1년": 400000000, "직전 2년": 0,    직전 4개 과세연도 발생액(발생하지 않은 해는 0 이나 비움)
                       "직전 3년": 0, "직전 4년": 0,
                       "기업 구분": "중소기업",                 중소기업 · 중견기업 · 일반기업(없으면 기준 시트 중소기업 여부)
                       "방식": "큰 쪽",                         큰 쪽 · 당기분 · 증가분(없으면 큰 쪽)
                       "수입금액": 0,                           일반기업 공제율 산식에만 쓴다(없으면 손익계산서 매출액)
                       "발생명세": [{"계정과목": "경상연구개발비",  조특 3호(1) ⑥ ~ ⑩ 줄(r8). 합계가 「해당」 기본값
                                     "인건비": 0, "인건비 인원": 0, "재료비": 0, "재료비 건수": 0, "위탁": 0, "위탁 건수": 0,
                                     "기타": 0, "기타 건수": 0, "인력개발비": 0, "인력개발비 건수": 0}]}

  당기분 방식(나목) = 해당 발생액 × 공제율(중소기업 25%, 중견기업 8%, 일반기업 min(2%, 해당 발생액 / 수입금액 × 1/2))
  증가분 방식(가목) = (해당 발생액 - 직전 1년 발생액) × 공제율(중소기업 50%, 중견기업 40%, 일반기업 25%)
  증가분 요건(제3호 단서) = 직전 4년 발생액 합계 > 0 이고 직전 1년 발생액 ≥ 연평균 발생액
  연평균 발생액 = 직전 4년 발생액 합계 / 발생한 과세연도 수 × 해당 과세연도 개월 수 / 12(시행령 제9조 제9항 · 제11항)
직전 1년 ~ 4년 발생액은 신고건.json 에 없으면 전기.json `rnd`(전기 신고서 조특 3호(1))의 ⑫ · ⑭ · ⑮ · ⑯ 을 기본값으로 쓴다(r8).
「해당」 발생액은 신고건.json 「연구인력개발비」 「발생명세」(계정과목별 인건비 · 재료비 · 위탁 · 기타 · 인력개발비, 노란 칸
「연구인력개발비/발생명세 N/…」)를 넣으면 그 합계가 기본값이다(r8, 조특 3호(1) ⑥ ~ ⑪ 줄). 「해당」 을 직접 넣으면 그 값이 이긴다.
요건을 채우지 못하면 당기분 방식만 쓴다. 계산한 금액은 노란 칸 「당기분/연구 · 인력개발비 세액공제」 의 기본값이 되어 중소기업은
16B(최저한세 적용제외, 제132조 제1항 제3호), 그 밖의 법인은 13M(적용대상) 줄로 간다. 금액을 넣지 않으면 0 이고 「자료 필요」 이며
장부의 연구 · 인력개발 계정 합계와 전기 공제액을 참고 줄로만 보인다. 신성장 · 원천기술(16A · 13L) · 국가전략기술(10D · 10E)
연구개발비와 중소기업 졸업 뒤 5년 안의 율(나목 2))은 계산하지 않고 확인 줄만 낸다.

고용증대 세액공제 2 · 3차 연도(fx3). 2024년이 속하는 과세연도까지 상시근로자가 늘어 공제받은 회사는 중소 · 중견기업이면 그 뒤
2년 더 같은 금액을 공제받는다(조특법 제29조의7 제1항). 최초 공제 연도보다 상시근로자가 줄면 그해부터 끊기고(청년등만 줄면
청년등 몫만), 공제받은 세액을 낸다(제2항). 당기 인원으로 판정해야 해서 노란 칸 「당기분/고용증대 세액공제(2 · 3차 연도)」 는
기본 0 이고, 전기에 고용증대 공제가 있으면 확인 줄에 넣을 금액(전기 조특 10호의8 의 1차년도 ⑮ 계 + 2차년도 세액공제액)을 적는다.
그 금액은 전기.json cells["조특10의8"] 에 `1차_계` · `2차_계` 가 있으면 쓰고, 없으면 ctax forms 가 전기 신고서 PDF 에서 읽어
서식.json 알림에 적는다.

순서(법인세법 제59조 제1항, 조특법 제132조 · 제144조 제2항)
  1. 감면: 최저한세 적용대상 감면은 산출세액 - 최저한세 안에서만 받는다.
  2. 최저한세 적용대상 세액공제: 이월분(먼저 생긴 해부터) → 당기분. 산출세액 - 최저한세 - 감면 안에서 받고, 최저한세로 못 받은 것은
     「최저한세 미공제」, 낼 세액이 없어 못 받은 것은 「그 밖의 미공제」 로 다음 해에 넘긴다.
  3. 최저한세 적용제외 세액공제(중소기업 연구 · 인력개발비 등): 남은 세액 안에서 이월분 → 당기분.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from fractions import Fraction

from openpyxl.utils import get_column_letter

from ... import xlsx as X
from ..books import Books, frac, rate, rd
from ..model import Paper
from ..sheet import Book, Rows, calc_row, forms_table, head, local, notes

NAME = "공제감면"
FORMS = ["8갑", "8을", "8부표2", "8부표3", "4", "조특2", "조특10의9", "조특3_1", "48"]
LEDGER_CHECK = False

# 8호(갑) 코드: (이름, 감면 · 공제, 최저한세 적용 대상 · 제외, 근거)
CODES = {
    "112": ("중소기업에 대한 특별세액감면", "감면", "대상", "조세특례제한법 제7조"),
    "111": ("창업중소기업에 대한 세액감면(최저한세 적용대상)", "감면", "대상", "조세특례제한법 제6조"),
    "16A": ("신성장 · 원천기술 연구개발비 세액공제(최저한세 적용제외)", "공제", "제외", "조세특례제한법 제10조 제1항 제1호"),
    "10D": ("국가전략기술 연구개발비 세액공제(최저한세 적용제외)", "공제", "제외", "조세특례제한법 제10조 제1항 제2호"),
    "16B": ("일반 연구 · 인력개발비 세액공제(최저한세 적용제외)", "공제", "제외", "조세특례제한법 제10조 제1항 제3호"),
    "13L": ("신성장 · 원천기술 연구개발비 세액공제(최저한세 적용대상)", "공제", "대상", "조세특례제한법 제10조 제1항 제1호"),
    "10E": ("국가전략기술 연구개발비 세액공제(최저한세 적용대상)", "공제", "대상", "조세특례제한법 제10조 제1항 제2호"),
    "13M": ("일반 연구 · 인력개발비 세액공제(최저한세 적용대상)", "공제", "대상", "조세특례제한법 제10조 제1항 제3호"),
    "13W": ("통합투자세액공제(일반)", "공제", "대상", "조세특례제한법 제24조"),
    "18S": ("통합고용세액공제", "공제", "대상", "조세특례제한법 제29조의8"),
    "1B4": ("통합고용세액공제(정규직 전환)", "공제", "대상", "조세특례제한법 제29조의8 제4항"),
    "1B5": ("통합고용세액공제(육아휴직 복귀)", "공제", "대상", "조세특례제한법 제29조의8 제5항"),
    "18F": ("고용을 증대시킨 기업에 대한 세액공제", "공제", "대상", "조세특례제한법 제29조의7"),
    "14Q": ("중소기업 고용증가 인원에 대한 사회보험료 세액공제", "공제", "대상", "조세특례제한법 제30조의4 제1항"),
    "184": ("전자신고에 대한 세액공제", "공제", "대상", "조세특례제한법 제104조의8 제1항"),
}

# 당기분 노란 칸(자료 필요). (칸 이름, 중소기업 코드, 그 밖의 법인 코드, 필요한 자료)
CURRENT = [
    ("창업중소기업 세액감면", "111", "111", "창업일 · 감면 기간(최초 소득 발생 과세연도부터 5년) · 지역 · 감면율(조특 2호의2)"),
    ("연구 · 인력개발비 세액공제", "16B", "13M", "해당 과세연도 일반 연구 · 인력개발비 발생액(신고건.json 「연구인력개발비」 또는 노란 칸 "
                                              "「연구인력개발비/…」, 연구소 · 전담부서 인정서, 조특 3호(1) · 부표(1))"),
    ("통합투자세액공제", "13W", "13W", "투자 자산 명세 · 직전 3년 투자액(조특 8호의9)"),
    ("통합고용세액공제", "18S", "18S", "상시근로자 · 청년등 상시근로자 수(신고건.json 「상시근로자」 또는 노란 칸 「통합고용/…」, "
                                      "조특 10호의9 · 10호의10)"),
    ("고용증대 세액공제(2 · 3차 연도)", "18F", "18F", "최초 공제 연도 · 상시근로자 인원(조특 10호의8)"),
]
# 사람이 인원을 넣으면 엔진이 계산하는 줄(「자료 필요」 목록에는 넣지 않는다). 통합고용 추가공제는 8호(갑) 줄이 따로다
CURRENT_EXTRA = [
    ("통합고용세액공제(정규직 전환)", "1B4", "1B4", "정규직 전환 인원(신고건.json 「상시근로자」 「정규직 전환 인원」 또는 노란 칸 "
                                                  "「통합고용/정규직 전환 인원」)"),
    ("통합고용세액공제(육아휴직 복귀)", "1B5", "1B5", "육아휴직 복귀 인원(신고건.json 「상시근로자」 「육아휴직 복귀 인원」 또는 노란 칸 "
                                                    "「통합고용/육아휴직 복귀 인원」, 조특 10호의9 ⑩ · ㊱)"),
]
CARRY_MANUAL = 2          # 이월 수동 노란 줄 수
INDUSTRY = ("도매업등", "감면업종", "출판업", "비감면")
EMPLOY_KEY = "당기분/고용증대 세액공제(2 · 3차 연도)"

# 감면 소득에서 뺄 영업외 손익(국세청 법인46012-1560). 평가손익은 세무조정으로 빠지는 일이 많아 넣지 않는다
EXCLUDE_GAIN = re.compile(r"이자수익|이자수입|배당금수익|배당금수입|배당수익|임대료|처분이익|처분익|상환이익")
EXCLUDE_LOSS = re.compile(r"처분손실|처분손|상환손실")
# 매출 구역 계정 중 감면 업종 수입이 아닐 수 있는 것(알림에만 쓴다. 기본값은 바꾸지 않는다)
SALES_OTHER = re.compile(r"임대|이자|배당")


def _non_operating(a: dict) -> bool:
    return "영업외" in (a.get("section") or "") or str(a.get("code") or "")[:3] >= "901"


def excluded_income(b: Books) -> tuple[int, list[tuple[str, int]]]:
    """감면 제외 소득 기본값과 내역. 영업외수익 중 이자 · 배당 · 임대료 · 처분이익에서 영업외비용 처분손실을 뺀 순액(0 아래면 0)."""
    parts = [(a["name"], int(a.get("amount") or 0)) for a in b.accounts(cls="수익")
             if _non_operating(a) and EXCLUDE_GAIN.search(a.get("name") or "")]
    parts += [(a["name"], -int(a.get("amount") or 0)) for a in b.accounts(cls="비용")
              if _non_operating(a) and EXCLUDE_LOSS.search(a.get("name") or "")]
    parts = [x for x in parts if x[1]]
    return max(0, sum(v for _, v in parts)), parts


def reduced_income(income: int, base: int, exclude: int) -> int:
    """감면 소득 = (각사업연도소득 - 감면 제외 소득) × 과세표준 / 각사업연도소득(법인세법 시행령 제96조 제2호 비례 안분)."""
    if income <= 0 or base <= 0:
        return 0
    return rd(Fraction(max(0, income - exclude) * base, income))


# 소득 구분계산(48호) ------------------------------------------------------------------------------

SPLIT = "소득구분"
SPLIT_BASIS = ("수입금액", "개별손금")
# 노란 칸: (key, 종류, 조서 줄 이름, 48호 란)
SPLIT_INPUTS = [
    ("매출액/기타", "int", "그 밖의 사업 매출액", "(1) 기타분"),
    ("매출원가/기타", "int", "그 밖의 사업 매출원가", "(2) 기타분"),
    ("판관비 개별/기타", "int", "그 밖의 사업 판매비와관리비 개별분", "(4) 개별분 기타분"),
    ("판관비 공통", "int", "판매비와관리비 공통분(두 사업에 함께 쓴 것)", "(4) 공통분 합계"),
    ("영업외수익 공통", "int", "영업외수익 공통분", "(6) 공통분 합계"),
    ("영업외비용 개별/기타", "int", "그 밖의 사업 영업외비용 개별분(감면 제외 소득에서 이미 뺀 것)", "(7) 개별분 기타분"),
    ("영업외비용 공통", "int", "영업외비용 공통분", "(7) 공통분 합계"),
    ("세무조정/기타", "int", "그 밖의 사업 세무조정 순액(가산 +, 차감 -)", "작성방법 2"),
    ("안분 기준 가산/기타", "int", "안분 기준 수입금액에 더할 그 밖의 사업 수입(매출액이 아닌 것)", "작성방법 3 · 4"),
]
BOOK_PARTS = ("매출액", "매출원가", "판관비", "영업외수익", "영업외비용")


def book_split(b: Books) -> dict:
    """손익계산서 다섯 과목(48호 (1) · (2) · (4) · (6) · (7) 합계). 장부 totals 에 있으면 그 값, 없으면 계정 구역으로 더한다."""
    t = b.totals
    keys = ("revenue", "cogs", "sga", "non_operating_income", "non_operating_expense")
    if all(t.get(k) is not None for k in keys):
        return dict(zip(BOOK_PARTS, (int(t[k]) for k in keys)))
    out = dict.fromkeys(BOOK_PARTS, 0)
    for a in b.accounts(cls=("수익", "비용")):
        amt, sec = int(a.get("amount") or 0), a.get("section") or ""
        if a["class"] == "수익":
            out["영업외수익" if _non_operating(a) else "매출액"] += amt
        elif "법인세" in sec or "법인세" in (a.get("name") or ""):
            continue
        elif "영업외" in sec or (not sec and _non_operating(a)):
            out["영업외비용"] += amt
        elif sec == "매출원가":
            out["매출원가"] += amt
        elif "원가" not in sec:                       # 제조 · 도급 원가 계정은 매출원가로 대체된 금액과 겹친다
            out["판관비"] += amt
    return out


def _share(common: int, part: int, whole: int) -> int:
    """공통분 × 그 밖의 사업 기준 금액 / 기준 금액 합계(원 미만 버림). 합계가 0 이하면 0, 그 밖의 사업 기준 금액은
    0 과 합계 사이로 맞춘다."""
    if whole <= 0:
        return 0
    return rd(Fraction(common * max(0, min(part, whole)), whole))


def split_income(book: dict, exclude: int, y: dict) -> dict:
    """그 밖의 사업 소득(세무조정 · 공통 손익 안분 뒤)과 공통분 안분액.
    `y` 는 노란 칸 값(SPLIT_INPUTS 의 key 와 「기준」). 공통 익금은 수입금액 비례, 공통 손금은 기준에 따라 수입금액 또는
    개별 손금 비례다(법인세법 시행규칙 제76조 제6항 제1호 ~ 제3호)."""
    rev_o, rev_t = y["매출액/기타"] + y["안분 기준 가산/기타"], book["매출액"] + y["안분 기준 가산/기타"]
    exp_o = y["매출원가/기타"] + y["판관비 개별/기타"] + y["영업외비용 개별/기타"]
    exp_t = book["매출원가"] + book["판관비"] - y["판관비 공통"] + book["영업외비용"] - y["영업외비용 공통"]
    by_exp = y["기준"] == "개별손금"
    part, whole = (exp_o, exp_t) if by_exp else (rev_o, rev_t)
    a_nr = _share(y["영업외수익 공통"], rev_o, rev_t)
    a_g = _share(y["판관비 공통"], part, whole)
    a_ne = _share(y["영업외비용 공통"], part, whole)
    other = (exclude + y["매출액/기타"] - y["매출원가/기타"] - y["판관비 개별/기타"] + y["세무조정/기타"]
             + a_nr - a_g - a_ne)
    return {"rev_o": rev_o, "rev_t": rev_t, "exp_o": exp_o, "exp_t": exp_t, "a_nr": a_nr, "a_g": a_g, "a_ne": a_ne,
            "other": other, "cost_part": part, "cost_whole": whole}


# 통합고용세액공제(조특법 제29조의8) ----------------------------------------------------------------

EMP = "통합고용"
EMP_KEY = "당기분/통합고용세액공제"
PERIODS = ("해당", "직전", "직전전")
SIZES = ("중소기업", "중견기업", "일반기업")
INFO_KEY = "상시근로자"


def q2(v) -> Fraction:
    """인원 수: 100분의 1 미만은 버린다(조특령 제26조의8 제6항)."""
    try:
        f = Fraction(str(v if v not in (None, "") else 0))
    except (ValueError, ZeroDivisionError):
        return Fraction(0)
    return Fraction(int(f * 100), 100) if f > 0 else Fraction(0)


def _pair(d) -> tuple | None:
    """{"청년등", "청년등 외"}(또는 「전체」) → (청년등, 청년등 외). 읽지 못하면 None."""
    if not isinstance(d, dict):
        return None
    get = lambda *ks: next((d[k] for k in ks if d.get(k) not in (None, "")), None)   # noqa: E731
    youth, other, total = get("청년등", "youth"), get("청년등 외", "청년등외", "other"), get("전체", "상시", "total")
    try:
        if other is None and total is not None:
            other = float(total) - float(youth or 0)
        if youth is None and other is None:
            return None
        return float(youth or 0), float(other or 0)
    except (TypeError, ValueError):
        return None


def headcount_defaults(b: Books) -> dict:
    """노란 칸 기본값. 신고건.json 「상시근로자」(사람 입력)가 먼저고, 직전 · 직전전 인원은 전기.json
    employment["10의9"]["headcount"](전기 조특 10호의9 의 해당 · 직전 과세연도 인원)가 있으면 그 값이다.
    {"hc": {기간: (청년등, 청년등 외)}, "given": {기간: 어디서 왔는지}, "first": {기간: (청년등, 청년등 외)}, "size", "capital", "bad"}"""
    info = (b.info or {}).get(INFO_KEY)
    bad = []
    if info is not None and not isinstance(info, dict):
        bad.append(f"신고건.json 「{INFO_KEY}」 가 {{\"해당\": {{\"청년등\": 0, \"청년등 외\": 0}}, …}} 꼴이 아닙니다")
        info = None
    info = info or {}
    hc, given, first = {}, {}, {}
    prior_hc = ((((b.prior or {}).get("employment") or {}).get("10의9") or {}).get("headcount") or {})
    from_prior = {"직전": _pair(prior_hc.get("current")), "직전전": _pair(prior_hc.get("prior"))} \
        if isinstance(prior_hc, dict) else {}
    for per in PERIODS:
        got = _pair(info.get(per))
        if per in info and got is None:
            bad.append(f"신고건.json 「{INFO_KEY}」 「{per}」 의 인원을 읽지 못했습니다")
        if got is not None:
            hc[per], given[per] = got, "신고건.json"
        elif from_prior.get(per) is not None:
            hc[per], given[per] = from_prior[per], "전기 조특 10호의9"
        else:
            hc[per] = (0.0, 0.0)
    amounts = info.get("1차년도 공제액") if isinstance(info.get("1차년도 공제액"), dict) else {}
    prior_first = _prior_first((b.prior or {}).get("employment"))
    for per in PERIODS[1:]:
        got = _pair(amounts.get(per))
        if got:
            first[per] = (int(got[0]), int(got[1]))
        elif prior_first.get(per):
            first[per], given[f"1차년도 공제액/{per}"] = prior_first[per], "전기 조특 10호의9"
        else:
            first[per] = (0, 0)
    size = str(info.get("기업 구분") or "").strip()
    capital = str(info.get("증가 지역 수도권") or "").strip()
    extra = {}
    for kind, name, _code, _law in EXTRA:
        raw = info.get(f"{name} 인원")
        try:
            extra[kind] = int(round(float(raw))) if raw not in (None, "") else 0
            if extra[kind] < 0:
                raise ValueError(raw)
        except (TypeError, ValueError):
            extra[kind] = 0
            bad.append(f"신고건.json 「{INFO_KEY}」 「{name} 인원」 을 읽지 못했습니다")
    return {"hc": hc, "given": given, "first": first, "size": size if size in SIZES else "",
            "capital": capital if capital in ("여", "부") else "", "bad": bad, "extra": extra}


def carry_by_year(prior: dict) -> dict:
    """전기.json credit_years(전기 8호 부표3 2절 연도별 줄) → {공제 코드: [(발생 연도, 이월액), …]}(먼저 생긴 해부터).
    코드나 연도를 못 읽은 줄이 있는 코드는 뺀다(그 코드는 전기 연도 한 줄로 둔다)."""
    out: dict = {}
    bad = set()
    for r in prior.get("credit_years") or []:
        if not isinstance(r, dict) or not int(r.get("carryforward") or 0):
            continue
        code = str(r.get("code") or "")
        year = r.get("year")
        if not code or not isinstance(year, int):
            bad.add(code)
            continue
        out.setdefault(code, {}).setdefault(year, 0)
        out[code][year] += int(r["carryforward"])
    return {c: sorted(y.items()) for c, y in out.items() if c not in bad}


def _prior_first(employment) -> dict:
    """전기 조특 10호의9 의 차수별 금액 → 당기에 이어질 1차년도 공제액 {직전 · 직전전: (청년등, 청년등 외)}.

    전기의 1차년도 금액(전기 증가분)이 당기 2차 연도, 전기의 2차년도 금액(전전기 증가분)이 당기 3차 연도다. 청년등 · 청년등 외로
    나뉜 금액이 둘 다 있을 때만 쓴다(못 읽은 값을 0 으로 두지 않는다)."""
    e = employment.get("10의9") if isinstance(employment, dict) else None
    out = {}
    for r in (e or {}).get("by_year") or []:
        per = {1: "직전", 2: "직전전"}.get(r.get("차수")) if isinstance(r, dict) else None
        if per and r.get("청년등") is not None and r.get("청년등외") is not None and (r["청년등"] or r["청년등외"]):
            out[per] = (int(r["청년등"]), int(r["청년등외"]))
    return out


def per_head(size: str, capital: str, rates: dict) -> tuple[int, int]:
    """(청년등, 청년등 외) 1인당 공제금액(조특법 제29조의8 제1항 제1호 · 제2호)."""
    r = lambda k: int(rate(rates, "employment_integrated", k))   # noqa: E731
    if size == "중소기업":
        tail = "capital" if capital == "여" else "local"
        return r(f"youth_sme_{tail}"), r(f"other_sme_{tail}")
    if size == "중견기업":
        return r("youth_mid"), r("other_mid")
    return r("youth_general"), r("other_general")


def integrated_credit(hc: dict, first: dict, size: str, capital: str, rates: dict, fy_year: int,
                      prev_known: bool) -> dict:
    """통합고용세액공제 1 · 2 · 3차 연도 금액. `hc` 는 {기간: (청년등, 청년등 외)}, `first` 는 {직전 · 직전전: 그해 1차년도
    공제액 (청년등, 청년등 외)}. `prev_known` 은 직전 인원 0 이 사람이 적은 값인지(창업 첫 해)."""
    n = {per: (q2(hc[per][0]), q2(hc[per][1])) for per in PERIODS}
    tot = {per: n[per][0] + n[per][1] for per in PERIODS}
    y_c, y_p, y_pp = (n[per][0] for per in PERIODS)
    t_c, t_p, t_pp = (tot[per] for per in PERIODS)
    d_t, d_y, d_o = t_c - t_p, y_c - y_p, n["해당"][1] - n["직전"][1]
    a_y, a_o = per_head(size, capital, rates)
    in_time = bool(fy_year) and fy_year <= int(rate(rates, "employment_integrated", "first_year_until"))
    prev_ok = t_p > 0 or prev_known
    out = {"used": t_c > 0, "tot": tot, "n": n, "d_t": d_t, "d_y": d_y, "d_o": d_o, "a_y": a_y, "a_o": a_o,
           "in_time": in_time, "prev_ok": prev_ok, "n_y": Fraction(0), "n_o": Fraction(0),
           "first_y": 0, "first_o": 0, "second": 0, "third": 0, "second_cut": "", "third_cut": ""}
    if t_c > 0 and in_time and prev_ok and d_t > 0:
        out["n_y"], out["n_o"] = max(Fraction(0), min(d_y, d_t)), max(Fraction(0), min(d_o, d_t))
        out["first_y"], out["first_o"] = rd(out["n_y"] * a_y), rd(out["n_o"] * a_o)
    f1, f2 = first["직전"], first["직전전"]
    if t_c > 0 and any(f1):
        if t_p <= 0:
            out["second_cut"] = "직전 인원 없음"
        elif t_c < t_p:
            out["second_cut"] = "전체 감소"
        else:
            cut = y_c < y_p
            out["second"] = (0 if cut else f1[0]) + f1[1]
            out["second_cut"] = "청년등 감소" if cut and f1[0] else ""
    if t_c > 0 and any(f2):
        if size == "일반기업":
            out["third_cut"] = "일반기업"
        elif t_pp <= 0:
            out["third_cut"] = "직전전 인원 없음"
        elif t_p < t_pp or t_c < t_pp:
            out["third_cut"] = "전체 감소"
        else:
            cut = y_p < y_pp or y_c < y_pp
            out["third"] = (0 if cut else f2[0]) + f2[1]
            out["third_cut"] = "청년등 감소" if cut and f2[0] else ""
    out["first"] = out["first_y"] + out["first_o"]
    out["total"] = out["first"] + out["second"] + out["third"]
    return out


# 통합고용 추가공제(조특법 제29조의8 제4항 · 제5항) --------------------------------------------------

EXTRA = (("convert", "정규직 전환", "1B4", "제4항"), ("back", "육아휴직 복귀", "1B5", "제5항"))
EXTRA_LABEL = {kind: f"통합고용세액공제({name})" for kind, name, _, _ in EXTRA}
EXTRA_WHY = {"일반기업": "중소기업 · 중견기업만 받습니다", "과세연도 모름": "과세연도 시작 · 끝 날을 읽지 못했습니다",
             "해당 인원 없음": "해당 과세연도 상시근로자 수가 없어 계산하지 않았습니다",
             "직전 인원 없음": "직전 과세연도 상시근로자 수가 없어 계산하지 않았습니다",
             "전체 감소": "해당 과세연도 상시근로자 수가 직전 과세연도보다 줄어 공제하지 않습니다"}


def _day(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def extra_credit(convert: int, back: int, size: str, t_c, t_p, prev_ok: bool, start: str, end: str, rates: dict) -> dict:
    """정규직 전환(제4항) · 육아휴직 복귀(제5항) 추가공제 = 인원 × 1인당 금액(중소기업 1,300만원, 중견기업 900만원).

    해당 과세연도 상시근로자 수(`t_c`)가 직전 과세연도(`t_p`)보다 줄었으면 공제하지 않는다(각 항 단서). 정규직 전환은 전환 기간
    (2024. 1. 1. ~ 2024. 12. 31.)에 걸친 과세연도만, 육아휴직 복귀는 복직 기한(2025. 12. 31.) 전에 시작한 과세연도만 계산한다.
    {"unit", "convert", "back", "total", "convert_why", "back_why", "back_late"(과세연도가 복직 기한 뒤에 끝남)}"""
    r = lambda k: rate(rates, "employment_integrated_extra", k)   # noqa: E731
    unit = int(r("extra_sme")) if size == "중소기업" else int(r("extra_mid")) if size == "중견기업" else 0
    s, e = _day(start), _day(end)

    def one(n: int, lo: date | None, hi: date | None) -> tuple[int, str]:
        if n <= 0:
            return 0, ""
        if not unit:
            return 0, "일반기업"
        if s is None or e is None:
            return 0, "과세연도 모름"
        if (hi is not None and s > hi) or (lo is not None and e < lo):
            return 0, "기간 아님"
        if t_c <= 0:
            return 0, "해당 인원 없음"
        if t_p <= 0 and not prev_ok:
            return 0, "직전 인원 없음"
        if t_c < t_p:
            return 0, "전체 감소"
        return n * unit, ""
    conv, conv_why = one(int(convert), _day(r("convert_from")), _day(r("convert_until")))
    back_amt, back_why = one(int(back), None, _day(r("return_until")))
    late = bool(back_amt) and e is not None and e > _day(r("return_until"))
    return {"unit": unit, "convert_n": int(convert), "back_n": int(back), "convert": conv, "back": back_amt,
            "total": conv + back_amt, "convert_why": conv_why, "back_why": back_why, "back_late": late}


# 추가 납부세액(조특령 제26조의8 제4항 · 제26조의7 제5항) --------------------------------------------

ADD = "추가납부"
ADD_KEY = f"{ADD}/합계"
ADD_CASE = {"가1": "가목 1)", "가2": "가목 2)", "나": "나목"}
INCREASE_BASIS = [("고용증대 청년등 중소기업 수도권", "youth_sme_capital"), ("고용증대 청년등 중소기업 수도권이 아닌 지역", "youth_sme_local"),
                  ("고용증대 청년등 중견기업", "youth_mid"), ("고용증대 청년등 일반기업", "youth_general"),
                  ("고용증대 청년등 외 중소기업 수도권", "other_sme_capital"),
                  ("고용증대 청년등 외 중소기업 수도권이 아닌 지역", "other_sme_local"),
                  ("고용증대 청년등 외 중견기업", "other_mid"), ("고용증대 청년등 외 일반기업", "other_general"),
                  ("고용증대 2021 · 2022 수도권이 아닌 지역 청년등", "special_2021_2022")]
EXTRA_BASIS = [("통합고용 추가공제 중소기업", "extra_sme"), ("통합고용 추가공제 중견기업", "extra_mid"),
               ("통합고용 정규직 전환 기간 시작", "convert_from"), ("통합고용 정규직 전환 기간 끝", "convert_until"),
               ("통합고용 육아휴직 복귀 기한", "return_until"), ("통합고용 추가공제 요건", "no_decrease"),
               ("통합고용 추가공제 사후관리", "followup"), ("통합고용 추가공제 최저한세 · 이월", "min_tax")]
CLAWBACK_BASIS = [("추가 납부세액 통합고용", "integrated"), ("추가 납부세액 1년 이내", "first_period"),
                  ("추가 납부세액 2년 이내", "second_period"), ("추가 납부세액 2년 이내 그 밖의 전체 감소", "second_period_other"),
                  ("추가 납부세액 청년등 인원", "same_person"), ("추가 납부세액 고용증대", "increase"),
                  ("추가 납부세액 납부 방법", "payment"), ("추가 납부세액 8호(을) 줄", "form_row")]


def per_head_increase(size: str, capital: str, rates: dict) -> tuple[int, int]:
    """고용증대 세액공제 (청년등, 청년등 외) 1인당 공제금액(조특법 제29조의7 제1항 제1호 · 제2호). 추가 납부세액 식에만 쓴다."""
    r = lambda k: int(rate(rates, "employment_increase", k))   # noqa: E731
    if size == "중소기업":
        tail = "capital" if capital == "여" else "local"
        return r(f"youth_sme_{tail}"), r(f"other_sme_{tail}")
    if size == "중견기업":
        return r("youth_mid"), r("other_mid")
    return r("youth_general"), r("other_general")


def clawback(first: tuple, cur: tuple, inc, a1: int, a2: int, period: int = 1, times: int = 1, paid: int = 0) -> dict:
    """인원이 줄었을 때 납부할 세액(한도 적용 전). 조특령 제26조의8 제4항(고용증대는 제26조의7 제5항)의 식 그대로다.

    `first` · `cur` 는 최초 공제 과세연도와 해당 과세연도의 (청년등, 청년등 외) 상시근로자 수, `inc` 는 최초 공제 과세연도의 청년등
    증가 인원 수(모르면 None), `a1` · `a2` 는 제1항 제1호 · 제2호의 1인당 금액. `period` 1 은 최초 공제 과세연도 종료일부터 1년이
    되는 날이 속하는 과세연도(제1호), 2 는 그다음 과세연도(제2호)다. 제2호는 직전 2년 이내 공제받은 횟수(`times`)를 곱하고 제1호로
    계산한 금액(`paid`)을 뺀다. 제2호 가목 2)에는 계산식이 없고 「감소 인원 수에 대해 공제받은 세액의 합계액」 이라고만 적혀 있어
    감소 인원 × 1인당 금액 × 횟수로 계산한다.
    {"case": 가1 · 가2 · 나 · 빈 글, "d_t", "d_y", "d_o", "raw": 식의 금액(원 미만 버림, 식에 `inc` 가 필요한데 없으면 None),
     "amount": raw - paid(0 아래면 0)}"""
    f_y, f_o, c_y, c_o = q2(first[0]), q2(first[1]), q2(cur[0]), q2(cur[1])
    d_y, d_o = f_y - c_y, f_o - c_o
    d_t = d_y + d_o
    n = max(0, int(times)) if period == 2 else 1
    gap = a1 - a2
    need = False
    if d_t > 0 and d_y >= d_t:
        case, need = "가1", True
        raw = None if inc is None else ((min(d_y, q2(inc)) - d_t) * gap + d_t * a1) * n
    elif d_t > 0:
        case = "가2"
        raw = (min(max(d_y, Fraction(0)), d_t) * a1 + min(max(d_o, Fraction(0)), d_t) * a2) * n
    elif d_y > 0:
        case, need = "나", True
        raw = None if inc is None else min(d_y, q2(inc)) * gap * n
    else:
        case, raw = "", Fraction(0)
    out = {"case": case, "d_t": d_t, "d_y": d_y, "d_o": d_o, "need_inc": need, "times": n,
           "raw": None if raw is None else rd(Fraction(raw))}
    out["amount"] = None if out["raw"] is None else max(0, out["raw"] - (int(paid) if period == 2 else 0))
    return out


def _inc_youth(cells, code: str):
    """전기 고용 서식 1차년도 표의 청년등 증가 인원 합(`<란>_<법인 구분>[_<지역>]_청년등_인원`). 표를 읽지 못했으면 None."""
    if not isinstance(cells, dict) or f"{code}_계" not in cells:
        return None
    return sum(float(v) for k, v in cells.items() if re.fullmatch(rf"{code}_.*_청년등_인원", k))


# 일반 연구 · 인력개발비 세액공제(조특법 제10조 제1항 제3호) ---------------------------------------

RND = "연구인력개발비"
RND_KEY = "당기분/연구 · 인력개발비 세액공제"
RND_INFO = "연구인력개발비"
RND_YEARS = ("직전 1년", "직전 2년", "직전 3년", "직전 4년")
RND_METHODS = ("큰 쪽", "당기분", "증가분")
RND_CODES = ("16B", "13M")
RND_DETAIL = "발생명세"
RND_DETAIL_ROWS = 3       # 발생명세 노란 줄 수(신고건.json 에 더 많이 적으면 그만큼)
# 발생명세 구분: (이름, 인원 · 건수 이름, 조특 3호(1) 2025. 11. 28. 개정 서식의 란 번호)
RND_PARTS = (("인건비", "인원", "6"), ("재료비", "건수", "7"), ("위탁", "건수", "8"), ("기타", "건수", "9"),
             ("인력개발비", "건수", "10"))
RND_PART_LABEL = {"인건비": "자체 연구개발비 인건비 및 사회보험료", "재료비": "자체 연구개발비 재료비 등", "위탁": "위탁 및 공동 연구개발비",
                  "기타": "기타 연구개발비", "인력개발비": "인력개발비"}
# 전기 조특 3호(1) 에서 옮기는 값: 당기 키 → (전기 란, 전기.json rnd 에서 읽는 법)
RND_PRIOR = (("직전 1년", "⑫"), ("직전 2년", "⑭"), ("직전 3년", "⑮"), ("직전 4년", "⑯"))
# 장부에서 참고로 보일 계정(대상 금액으로 쓰지 않는다)
RND_ACCOUNT = re.compile(r"연구|개발비|교육훈련|인력개발|훈련비")


def rnd_months(start: str, end: str) -> int:
    """연평균 발생액 계산에 쓰는 해당 과세연도 개월 수(조특령 제9조 제11항): 월력으로 세고, 개시일이 속하는 달은 1개월,
    끝나는 날이 그 달의 마지막 날이 아니면 그 달은 넣지 않는다. 날짜를 읽지 못하면 12."""
    try:
        s, e = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except ValueError:
        return 12
    n = (e.year - s.year) * 12 + e.month - s.month + 1
    if (e + timedelta(days=1)).month == e.month:
        n -= 1
    return max(1, min(12, n))


def _won(v) -> int | None:
    """원 금액. 비었으면 None, 숫자가 아니거나 음수면 ValueError."""
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        raise ValueError(v)
    n = int(round(float(str(v).replace(",", ""))))
    if n < 0:
        raise ValueError(v)
    return n


def rnd_prior(b: Books) -> tuple[list, str, str]:
    """전기.json `rnd`(전기 신고서 조특 3호(1)) → (당기 직전 1년 ~ 4년 발생액 [없으면 None], 어디서 왔는지, 쓰지 못한 까닭).
    전기 ⑫ 해당 과세연도 발생액이 당기 직전 1년, 전기 ⑭ · ⑮ · ⑯ 이 당기 직전 2 ~ 4년이다. 전기 과세연도가 당기 바로 앞이
    아니면(끝 날 다음 날이 당기 시작 날이 아님) 쓰지 않는다."""
    r = (b.prior or {}).get("rnd")
    if not isinstance(r, dict):
        return [None] * 4, "", ""
    end, start = _day(r.get("fy_end") or (b.prior or {}).get("fy_end")), _day((b.info or {}).get("fy_start"))
    if end is not None and start is not None and end + timedelta(days=1) != start:
        return [None] * 4, "", (f"전기 신고서 조특 3호(1) 의 과세연도 끝 날 {end.isoformat()} 다음 날이 당기 시작 날 {start.isoformat()} 과 "
                                "달라 직전 과세연도 발생액 기본값으로 쓰지 않았습니다")
    prev = r.get("직전") if isinstance(r.get("직전"), list) else []
    by = {x.get("차수"): x.get("amount") for x in prev if isinstance(x, dict)}
    got = [r.get("발생액"), by.get(1), by.get(2), by.get(3)]
    out = [int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None for v in got]
    where = f"전기 조특 3호(1)({r.get('page')}쪽)" if r.get("page") else "전기 조특 3호(1)"
    return out, where, ""


def _detail_rows(info: dict, bad: list) -> list[dict]:
    """신고건.json 「연구인력개발비」 「발생명세」 줄 [{계정과목, 인건비, 인건비 인원, 재료비, 재료비 건수, …}]. 읽지 못한 값은 0."""
    raw = info.get(RND_DETAIL)
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        bad.append(f"신고건.json 「{RND_INFO}」 「{RND_DETAIL}」 가 [{{\"계정과목\": \"\", \"인건비\": 0, …}}] 꼴이 아닙니다")
        return []
    rows = []
    for i, x in enumerate(raw, 1):
        row = {"계정과목": str(x.get("계정과목") or "").strip()}
        for part, unit, _code in RND_PARTS:
            for key in (part, f"{part} {unit}"):
                try:
                    row[key] = _won(x.get(key)) or 0
                except (TypeError, ValueError):
                    row[key] = 0
                    bad.append(f"신고건.json 「{RND_INFO}」 「{RND_DETAIL}」 {i}줄 「{key}」 를 읽지 못했습니다")
        rows.append(row)
    return rows


def rnd_defaults(b: Books) -> dict:
    """노란 칸 기본값. 신고건.json 「연구인력개발비」(사람 입력)가 먼저다. 직전 1년 ~ 4년 발생액은 신고건.json 에 없으면 전기.json
    `rnd`(전기 신고서 조특 3호(1))에서 옮긴다. 해당 과세연도 발생액은 장부 계정이나 전기 서식에서 가져오지 않는다.
    {"cur", "cur_given", "prev": [직전 1년 ~ 4년], "given": {키: 어디서 왔는지}, "detail": 발생명세 줄, "size", "method",
     "revenue"(없으면 None), "bad": [읽지 못한 것], "prior_why"}"""
    info = (b.info or {}).get(RND_INFO)
    bad = []
    if info is not None and not isinstance(info, dict):
        bad.append(f"신고건.json 「{RND_INFO}」 가 {{\"해당\": 0, \"직전 1년\": 0, …}} 꼴이 아닙니다")
        info = None
    info = info or {}

    def money(key):
        try:
            return _won(info.get(key))
        except (TypeError, ValueError):
            bad.append(f"신고건.json 「{RND_INFO}」 「{key}」 의 금액을 읽지 못했습니다")
            return None
    cur_raw = money("해당")
    cur = cur_raw or 0
    from_prior, where, prior_why = rnd_prior(b)
    prev, given = [], {}
    for i, k in enumerate(RND_YEARS):
        v = money(k)
        if v is None and k not in info and from_prior[i] is not None:
            v, given[k] = from_prior[i], f"{where} {RND_PRIOR[i][1]}"
        prev.append(v or 0)
    detail = _detail_rows(info, bad)
    revenue = money("수입금액")
    size = str(info.get("기업 구분") or "").strip()
    method = str(info.get("방식") or "").strip()
    if size and size not in SIZES:
        bad.append(f"신고건.json 「{RND_INFO}」 「기업 구분」 「{size}」 을 읽지 못했습니다(중소기업 · 중견기업 · 일반기업)")
    if method and method not in RND_METHODS:
        bad.append(f"신고건.json 「{RND_INFO}」 「방식」 「{method}」 을 읽지 못했습니다(큰 쪽 · 당기분 · 증가분)")
    return {"cur": cur, "cur_given": cur_raw is not None, "prev": prev, "given": given, "detail": detail,
            "prior_why": prior_why, "size": size if size in SIZES else "",
            "method": method if method in RND_METHODS else "", "revenue": revenue, "bad": bad}


def rnd_credit(cur: int, prev: list[int], size: str, method: str, revenue: int, months: int, rates: dict) -> dict:
    """일반 연구 · 인력개발비 세액공제 당기 발생분(조특법 제10조 제1항 제3호).
    `cur` 해당 과세연도 발생액, `prev` 직전 1년 ~ 4년 발생액(발생하지 않은 해는 0), `revenue` 수입금액(일반기업 공제율에만 씀),
    `months` 해당 과세연도 개월 수. 증가분 방식(가목)은 단서의 요건을 채울 때만 계산한다."""
    r = lambda k: frac(rate(rates, "rnd_credit", k))   # noqa: E731
    cur = max(0, int(cur))
    prev = [max(0, int(x)) for x in prev]
    total4 = sum(prev)
    years = sum(1 for x in prev if x > 0)
    average = rd(Fraction(total4 * months, years * 12)) if years else 0
    if size == "중소기업":
        rate_cur = r("current_sme")
    elif size == "중견기업":
        rate_cur = r("current_mid")
    elif revenue > 0:
        rate_cur = min(r("current_general_cap"), Fraction(cur, revenue) * r("current_general_factor"))
    else:
        rate_cur = Fraction(0)
    rate_inc = r({"중소기업": "incremental_sme", "중견기업": "incremental_mid"}.get(size, "incremental_general"))
    increase = max(0, cur - prev[0])
    # 단서: 소급 4년간 발생액이 없거나 직전 과세연도 발생액이 연평균 발생액보다 적으면 나목만(원 미만 버림에 흔들리지 않게 정수로 견준다)
    if not cur:
        why = "해당 발생액 없음"
    elif not years:
        why = "직전 4년 발생액 없음"
    elif prev[0] * years * 12 < total4 * months:
        why = "직전 1년 발생액이 연평균보다 적음"
    else:
        why = ""
    eligible = bool(cur) and not why
    amount_cur = rd(cur * rate_cur)
    amount_inc = rd(increase * rate_inc) if eligible else 0
    if method == "당기분":
        used, total = "당기분", amount_cur
    elif method == "증가분":
        used, total = ("증가분", amount_inc) if eligible else ("당기분", amount_cur)
    else:
        used, total = ("증가분", amount_inc) if amount_inc > amount_cur else ("당기분", amount_cur)
    return {"used": cur > 0, "cur": cur, "prev": prev, "total4": total4, "years": years, "average": average,
            "increase": increase, "eligible": eligible, "why": why, "rate_cur": rate_cur, "rate_inc": rate_inc,
            "amount_cur": amount_cur, "amount_inc": amount_inc, "method_used": used if cur else "", "total": total,
            "months": months}


WHOLESALE = re.compile(r"도매|소매|도소매|상품중개")
NOT_REDUCED = re.compile(r"부동산|임대업|금융|보험|숙박|음식|주점|유흥|카지노|골프|오락")
REDUCED = re.compile(r"제조|건설|폐기물|하수|폐수|환경복원|원료재생|광고|연구개발|소프트웨어|컴퓨터|정보서비스|엔지니어링|"
                     r"디자인|물류|여객|방송|통신|출판|포장|작물|축산|어업|광업|임업|창작|예술")
SEOUL_GU = re.compile(r"(종로|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|구로|금천|영등포|동작|관악|"
                      r"서초|강남|송파|강동)구")
GYEONGGI = re.compile(r"(수원|성남|의정부|안양|부천|광명|평택|동두천|안산|고양|과천|구리|남양주|오산|시흥|군포|의왕|하남|용인|"
                      r"파주|이천|안성|김포|화성|양주|포천|여주)시|(연천|가평|양평|강화|옹진)군")
LOCAL = re.compile(r"^\s*(부산|대구|광주|대전|울산|세종|강원|충북|충남|충청|전북|전남|전라|경북|경남|경상|제주)")
CAPITAL = re.compile(r"^\s*(서울|인천|경기)")

# 국세청 업종코드 앞 두 자리 → 감면 업종 구분(업태 · 종목 글로 못 정할 때만 쓴다)
CODE_PREFIX = [(range(1, 6), "감면업종"), (range(10, 15), "감면업종"), (range(15, 38), "감면업종"),
               (range(45, 47), "감면업종"), (range(50, 53), "도매업등"), (range(55, 56), "비감면"),
               (range(64, 65), "감면업종"), (range(65, 68), "비감면"), (range(70, 72), "비감면"),
               (range(72, 74), "감면업종"), (range(90, 91), "감면업종")]


def basis(rates: dict) -> list[tuple]:
    sr, mt = rates["sme_reduction"], rates["min_tax"]

    def one(name, item, fmt):
        return (name, item["value"], item["basis"], item["grade"], fmt)
    out = [one("감면율 소기업 · 도매업등", sr["wholesale_small"], "0%"),
           one("감면율 소기업 · 수도권 · 그 밖의 감면 업종", sr["other_small_capital"], "0%"),
           one("감면율 소기업 · 수도권 외 · 그 밖의 감면 업종", sr["other_small_local"], "0%"),
           one("감면율 중기업 · 수도권 외 · 도매업등", sr["wholesale_medium_local"], "0%"),
           one("감면율 중기업 · 수도권 · 일반 서적 출판업", sr["publish_medium_capital"], "0%"),
           one("감면율 중기업 · 수도권 외 · 그 밖의 감면 업종", sr["other_medium_local"], "0%"),
           one("중소기업특별세액감면 한도", sr["limit"], None),
           one("한도 감소 상시근로자 1명당", sr["per_worker"], None),
           one("최저한세율(중소기업)", mt["sme_rate"], "0%")]
    br = mt["general_brackets"]
    for i, (cap, rt) in enumerate(br["value"], start=1):
        if cap is not None:
            out.append((f"최저한세 구간{i} 상한", cap, br["basis"], br["grade"], None))
        out.append((f"최저한세 구간{i}", rt, br["basis"], br["grade"], "0%"))
    out.append(one("세액공제 이월 연수", mt["carry_years"], "0"))
    ri, ec = (rates.get("reduced_income") or {}).get("excluded"), (rates.get("employment_credit") or {}).get("followup")
    if ri:
        out.append(one("감면 제외 소득 범위", ri, None))
    if ec:
        out.append(one("고용증대 · 통합고용 2 · 3차 연도", ec, None))
    ei = rates.get("employment_integrated") or {}
    for name, key in EMP_BASIS:
        if key in ei:
            out.append(one(name, ei[key], "0" if key == "first_year_until" else None))
    for group, names in (("employment_integrated_extra", EXTRA_BASIS), ("employment_increase", INCREASE_BASIS),
                         ("employment_clawback", CLAWBACK_BASIS)):
        for name, key in names:
            if key in (rates.get(group) or {}):
                out.append(one(name, rates[group][key], None))
    rc = rates.get("rnd_credit") or {}
    for name, key, fmt in RND_BASIS:
        if key in rc:
            out.append(one(name, rc[key], fmt))
    for name, key in (("소득 구분계산 범위", "scope"), ("공통 익금 안분", "common_income"),
                      ("공통 손금 안분(업종이 같을 때)", "common_expense_same"),
                      ("공통 손금 안분(업종이 다를 때)", "common_expense_diff"), ("업종 구분", "industry"),
                      ("결손이 난 사업", "loss_offset"), ("이월결손금 등 안분", "deduction_split")):
        if key in (rates.get("income_split") or {}):
            out.append(one(name, rates["income_split"][key], None))
    return out


# 기준 시트 줄 이름 ↔ rates employment_integrated 키(엑셀 수식이 이 이름으로 1인당 금액을 부른다)
EMP_BASIS = [("통합고용 청년등 중소기업 수도권", "youth_sme_capital"), ("통합고용 청년등 중소기업 수도권 밖", "youth_sme_local"),
             ("통합고용 청년등 중견기업", "youth_mid"), ("통합고용 청년등 일반기업", "youth_general"),
             ("통합고용 청년등 외 중소기업 수도권", "other_sme_capital"),
             ("통합고용 청년등 외 중소기업 수도권 밖", "other_sme_local"),
             ("통합고용 청년등 외 중견기업", "other_mid"), ("통합고용 청년등 외 일반기업", "other_general"),
             ("통합고용 1인당 금액을 쓰는 마지막 과세연도", "first_year_until"), ("통합고용 증가 인원 한도", "cap"),
             ("통합고용 상시근로자 수 계산", "headcount"), ("통합고용 2 · 3차 연도", "followup")]


# 기준 시트 줄 이름 ↔ rates rnd_credit 키(엑셀 수식이 이 이름으로 공제율을 부른다)
RND_BASIS = [("연구 · 인력개발비 당기분 공제율 중소기업", "current_sme", "0%"),
             ("연구 · 인력개발비 당기분 공제율 중견기업", "current_mid", "0%"),
             ("연구 · 인력개발비 당기분 일반기업 비율 배수", "current_general_factor", "0.0"),
             ("연구 · 인력개발비 당기분 일반기업 한도", "current_general_cap", "0%"),
             ("연구 · 인력개발비 증가분 공제율 중소기업", "incremental_sme", "0%"),
             ("연구 · 인력개발비 증가분 공제율 중견기업", "incremental_mid", "0%"),
             ("연구 · 인력개발비 증가분 공제율 일반기업", "incremental_general", "0%"),
             ("연구 · 인력개발비 방식 선택 · 증가분 요건", "choice", None), ("연구 · 인력개발비 연평균 발생액", "average", None),
             ("연구 · 인력개발비 중소기업 졸업 뒤 율", "graduation", None),
             ("신성장 · 원천기술 · 국가전략기술 연구개발비", "new_growth", None), ("연구 · 인력개발비 대상 비용", "scope", None),
             ("연구 · 인력개발비 최저한세", "min_tax", None), ("연구 · 인력개발비 이월공제", "carry", None),
             ("연구 · 인력개발비 농어촌특별세", "rural_tax", None), ("연구 · 인력개발비 서식", "form", None)]


# 회사 판정 -----------------------------------------------------------------------------------------

def industry(company: dict, c1: dict) -> tuple[str, str]:
    """(감면 업종 구분, 까닭). 업태 첫 낱말을 먼저 보고, 글로 못 정하면 주업종코드 앞 두 자리로 본다."""
    biz = str(company.get("biz_type") or c1.get("8") or "")
    item = re.sub(r"⑩.*", "", str(company.get("item") or c1.get("9") or ""))
    text = f"{biz} {item}".strip()
    first = re.split(r"[,·ㆍ/]", biz)[0]
    if text:
        if NOT_REDUCED.search(text) and not REDUCED.search(first) and not WHOLESALE.search(first):
            return "비감면", f"업태 · 종목 「{text}」"
        if WHOLESALE.search(first) or (not REDUCED.search(first) and WHOLESALE.search(item)):
            return "도매업등", f"업태 · 종목 「{text}」"
        if "출판" in text and "서적" in text:
            return "출판업", f"업태 · 종목 「{text}」"
        if REDUCED.search(text):
            return "감면업종", f"업태 · 종목 「{text}」"
    digits = re.sub(r"\D", "", str(company.get("industry_code") or c1.get("10") or ""))
    if not digits:
        m = re.search(r"주업종코드\s*(\d{6})", str(c1.get("9") or ""))
        digits = m.group(1) if m else ""
    if len(digits) >= 2:
        head2 = int(digits[:2])
        for rng, kind in CODE_PREFIX:
            if head2 in rng:
                return kind, f"주업종코드 {digits}"
    return "비감면", "업태 · 종목 · 주업종코드를 읽지 못했습니다"


def capital_region(address: str) -> str:
    """본점 소재지가 수도권(서울 · 인천 · 경기)이면 「여」, 아니면 「부」, 모르면 빈 글."""
    a = str(address or "")
    if not a.strip():
        return ""
    if CAPITAL.search(a):
        return "여"
    if LOCAL.search(a):
        return "부"
    if SEOUL_GU.search(a) or GYEONGGI.search(a):
        return "여"
    return ""


def reduction_rate(sme: bool, small: str, region: str, kind: str, rates: dict) -> float:
    """조특법 제7조 제1항 제2호 감면율."""
    if not sme or kind not in ("도매업등", "감면업종", "출판업"):
        return 0
    r = lambda k: rate(rates, "sme_reduction", k)   # noqa: E731
    if kind == "도매업등":
        if small == "여":
            return r("wholesale_small")
        return 0 if region == "여" else r("wholesale_medium_local")
    if small == "여":
        return r("other_small_capital") if region == "여" else r("other_small_local")
    if region == "여":
        return r("publish_medium_capital") if kind == "출판업" else 0
    return r("other_medium_local")


def min_tax(base: int, sme: bool, rates: dict) -> int:
    """조특법 제132조 제1항 최저한세액(감면 전 과세표준 × 율)."""
    if base <= 0:
        return 0
    if sme:
        return rd(Fraction(base) * frac(rate(rates, "min_tax", "sme_rate")))
    tax, prev = Fraction(0), 0
    for cap, r in rate(rates, "min_tax", "general_brackets"):
        top = base if cap is None else min(base, cap)
        if top > prev:
            tax += (top - prev) * frac(r)
        if cap is None or base <= cap:
            break
        prev = cap
    return rd(tax)


def code_info(code: str, name: str = "") -> tuple[str, str, str, str]:
    if code in CODES:
        return CODES[code]
    cls = "제외" if "적용제외" in (name or "") else "대상"
    return (name or f"세액공제({code})", "공제", cls, "")


# 계산 ----------------------------------------------------------------------------------------------

def compute(p: Paper, b: Books) -> None:
    prior = b.prior or {}
    company = prior.get("company") or {}
    c1 = (prior.get("cells") or {}).get("1") or {}
    kind0, why_kind = industry(company, c1)
    region0 = capital_region(c1.get("7") or company.get("address") or "")
    small0 = "여" if company.get("small") else "부"

    small = p.take(b, "소기업 여부", small0)
    region = p.take(b, "수도권 여부", region0 or "여")
    kind = p.take(b, "감면 업종", kind0)
    apply = p.take(b, "적용 여부", "O", "pick")
    exclude0, exclude_parts = excluded_income(b)
    exclude = p.take(b, "감면 제외 소득", exclude0, "int")
    split = _take_split(p, b, exclude, exclude_parts)
    w_prev = p.take(b, "상시근로자 수/직전", 0, "ratio")
    w_cur = p.take(b, "상시근로자 수/당기", 0, "ratio")
    sme = b.sme
    rr = reduction_rate(sme, small, region, kind, b.rates)
    drop = max(Fraction(0), Fraction(str(w_prev)) - Fraction(str(w_cur)))
    limit = max(0, rate(b.rates, "sme_reduction", "limit") - rd(drop * rate(b.rates, "sme_reduction", "per_worker")))

    emp = _take_employment(p, b, region)
    fy = int(b.fy) if str(b.fy).isdigit() else 0
    follow = employment_followup(prior, fy, b.sme, *_follow_inputs(b, emp), mid=emp["size"] == "중견기업")
    rnd = _take_rnd(p, b)
    add = _take_additional(p, b, emp, follow, *_follow_inputs(b, emp))
    defaults = {EMP_KEY: emp["calc"]["total"], EMPLOY_KEY: (follow or {}).get("default", 0), RND_KEY: rnd["calc"]["total"],
                **{f"당기분/{EXTRA_LABEL[kind]}": emp["extra"][kind] for kind, _n, _c, _l in EXTRA}}
    current = []
    for label, code_sme, code_gen, need in CURRENT + CURRENT_EXTRA:
        code = code_sme if sme else code_gen
        name, kd, cls, law = code_info(code)
        amt = p.take(b, f"당기분/{label}", defaults.get(f"당기분/{label}", 0), "int")
        current.append({"key": f"당기분/{label}", "label": label, "code": code, "name": name, "kind": kd, "class": cls,
                        "law": law, "amount": amt, "need": need})

    prior_fy = int(prior.get("fy")) if str(prior.get("fy") or "").isdigit() else fy - 1
    carry = []
    seen: dict[str, int] = {}
    by_year = carry_by_year(prior)
    for c in prior.get("credits") or []:
        cf = int(c.get("carryforward") or 0)
        code = str(c.get("code") or "")
        if cf <= 0 or not code:
            continue
        name, kd, cls, law = code_info(code, c.get("name") or "")
        # 전기 8호 부표3 의 연도별 줄 합이 이월액과 같으면 발생 연도마다 한 줄, 아니면 전기 연도 한 줄
        years = by_year.get(code) or []
        if sum(a for _y, a in years) != cf:
            years = [(prior_fy, cf)]
        for year0, cf0 in years:
            n = seen.get(code, 0) + 1
            seen[code] = n
            tag = code if n == 1 else f"{code}#{n}"
            year = p.take(b, f"이월/{tag}/연도", year0, "int")
            amt = p.take(b, f"이월/{tag}/금액", cf0, "int")
            carry.append({"key": f"이월/{tag}", "code": code, "name": name, "kind": kd, "class": cls, "law": law,
                          "year": year, "amount": amt, "manual": 0, "by_year": len(years) > 1 or year0 != prior_fy})
    for n in range(1, CARRY_MANUAL + 1):
        code = p.take(b, f"이월 수동 {n}/코드", "")
        year = p.take(b, f"이월 수동 {n}/연도", 0, "int")
        amt = p.take(b, f"이월 수동 {n}/금액", 0, "int")
        name, kd, cls, law = code_info(code.upper() if code else "", "")
        carry.append({"key": f"이월 수동 {n}", "code": code, "name": name if code else "", "kind": "공제", "class": cls,
                      "law": law, "year": year, "amount": amt, "manual": n})

    p.extra["calc"] = {"small": small, "region": region, "kind": kind, "apply": apply, "exclude": exclude,
                       "w_prev": w_prev, "w_cur": w_cur, "rate": rr, "limit": limit, "current": current, "carry": carry,
                       "fy": fy, "kind_why": why_kind, "region_known": bool(region0),
                       "exclude_parts": exclude_parts, "exclude_default": exclude0, "split": split, "emp": emp,
                       "rnd": rnd, "add": add}
    p.values = {"감면율": rr, "감면 한도": limit, "감면 제외 소득": exclude,
                **{c["key"]: c["amount"] for c in current},
                **{f"{c['key']}/금액": c["amount"] for c in carry},
                **_split_values(split), **_employment_values(emp), **_rnd_values(rnd), **_additional_values(add)}

    # 확인할 것 · 알릴 것
    prior_codes = {str(c.get("code") or ""): c for c in prior.get("credits") or []}
    if not region0:
        p.confirm.append("본점 소재지를 전기 1호에서 읽지 못해 수도권으로 두었습니다(노란 칸 「수도권 여부」)")
    if kind0 == "비감면" and "읽지 못했" in why_kind:
        p.confirm.append("감면 업종을 업태 · 종목으로 정하지 못해 비감면으로 두었습니다(노란 칸 「감면 업종」)")
    if "112" in prior_codes and rr == 0:
        p.confirm.append(f"전기에는 중소기업특별세액감면 {int(prior_codes['112'].get('amount') or 0):,}원을 받았는데 당기 감면율이 0 입니다"
                         f"(소기업 {small} · 수도권 {region} · {kind}). 2025 사업연도부터 중기업 · 수도권 감면은 일반 서적 출판업만"
                         " 남았습니다(부칙 <제20778호> 제2조)")
    if "111" in prior_codes:
        p.confirm.append("전기에 창업중소기업 세액감면을 받았습니다. 감면 기간(최초 소득 발생 과세연도부터 5년) 안이면 당기분 노란 칸에 넣으십시오."
                         " 같은 사업장에 중소기업특별세액감면과 함께 받을 수 없습니다(조특법 제127조 제5항)")
    cur = {c["code"]: c["amount"] for c in current}
    if apply == "O" and rr and cur.get("13W"):
        p.confirm.append("통합투자세액공제와 중소기업특별세액감면은 같은 해에 함께 받을 수 없습니다(조특법 제127조 제4항). 하나를 0 으로 하십시오")
    if cur.get("111") and (cur.get("18S") or cur.get("18F")):
        p.confirm.append("창업중소기업 세액감면을 받으면 통합고용 · 고용증대 세액공제를 함께 받을 수 없습니다(조특법 제127조 제4항 단서)")
    p.notes.append(f"감면 업종 「{kind}」 은 {why_kind} 로 추정했습니다. 한국표준산업분류로 감면 업종(조특법 제7조 제1항 제1호)인지 확인하십시오")
    p.notes.append("소기업 여부는 전기 51호 판정을 옮겼습니다. 감면의 소기업은 해당 과세연도 매출액이 중소기업기본법 시행령 별표 3 기준"
                   " 이내인지로 봅니다(조특령 제6조 제4항)")
    if any(c["amount"] and not c["manual"] and not c.get("by_year") for c in carry):
        p.notes.append("전기 이월액은 공제 종류마다 한 줄(발생 연도 = 전기)로 넣었습니다. 여러 해에서 생긴 이월액이면 수동 줄로 연도마다"
                       " 나누십시오(이월 기간 10년, 먼저 생긴 것부터 공제)")
    if any(c.get("by_year") for c in carry):
        p.notes.append("전기 이월액 발생 연도는 전기 8호 부표3 의 연도별 줄에서 옮겼습니다(먼저 생긴 것부터 공제)")
    extra_labels = {label for label, _a, _b, _c in CURRENT_EXTRA}
    need = [c for c in current if not c["amount"] and c["label"] not in extra_labels]
    if need:
        p.notes.append("자료 필요(계산하지 않음, 노란 칸 기본 0): " + " · ".join(f"{c['label']}({c['need']})" for c in need))
    if exclude_parts and rr and "감면 제외 소득" not in p.overridden:
        p.notes.append(f"감면 제외 소득 기본값 {exclude0:,}원 = " + " · ".join(f"{n} {v:,}" for n, v in exclude_parts)
                       + "(영업외수익 중 이자 · 배당 · 임대료 · 처분손익, 국세청 법인46012-1560)")
    _employment_followup(p, b, cur.get("18F", 0), cur.get("18S", 0), follow)
    _split_notes(p, b, split)
    _employment_notes(p, emp, cur.get("18S", 0))
    _extra_notes(p, emp, {c["key"]: c["amount"] for c in current})
    _additional_notes(p, b, add)
    _rnd_notes(p, b, rnd, next(c["amount"] for c in current if c["key"] == RND_KEY))
    p.status = "작성"


def _take_split(p: Paper, b: Books, exclude: int, exclude_parts: list) -> dict:
    """소득 구분계산 노란 칸을 읽고 그 밖의 사업 소득을 계산한다(각사업연도소득이 필요 없는 부분)."""
    book = book_split(b)
    loss0 = 0
    if "감면 제외 소득" not in p.overridden and sum(v for _, v in exclude_parts) >= 0:
        loss0 = -sum(v for _, v in exclude_parts if v < 0)      # 기본값에 든 처분손실(영업외비용 개별분)
    y = {}
    for key, kind, _, _ in SPLIT_INPUTS:
        y[key] = p.take(b, f"{SPLIT}/{key}", loss0 if key == "영업외비용 개별/기타" else 0, kind)
    basis_in = p.take(b, f"{SPLIT}/공통 손금 안분 기준", SPLIT_BASIS[0])
    y["기준"] = basis_in if basis_in in SPLIT_BASIS else SPLIT_BASIS[0]
    make = p.take(b, f"{SPLIT}/48호 작성", "X", "pick")
    got = split_income(book, exclude, y)
    used = any(k.startswith(f"{SPLIT}/") for k in p.overridden)
    return {**got, "book": book, "y": y, "basis_in": basis_in, "make": make, "used": used, "exclude": exclude}


def _split_values(sp: dict) -> dict:
    return {**{f"{SPLIT}/{k}": sp["book"][k] for k in BOOK_PARTS},
            **{f"{SPLIT}/{k}": sp["y"][k] for k, _, _, _ in SPLIT_INPUTS},
            f"{SPLIT}/안분 수입금액 기타": sp["rev_o"], f"{SPLIT}/안분 수입금액 합계": sp["rev_t"],
            f"{SPLIT}/개별 손금 기타": sp["exp_o"], f"{SPLIT}/개별 손금 합계": sp["exp_t"],
            f"{SPLIT}/공통 영업외수익 기타 안분": sp["a_nr"], f"{SPLIT}/공통 판관비 기타 안분": sp["a_g"],
            f"{SPLIT}/공통 영업외비용 기타 안분": sp["a_ne"], "그 밖의 사업 소득": sp["other"]}


def _split_notes(p: Paper, b: Books, sp: dict) -> None:
    y, book = sp["y"], sp["book"]
    if sp["basis_in"] not in SPLIT_BASIS:
        p.confirm.append(f"노란 칸 「{SPLIT}/공통 손금 안분 기준」 「{sp['basis_in']}」 을 읽지 못해 수입금액 기준으로 계산했습니다"
                         "(수입금액 · 개별손금)")
    common_cost = y["판관비 공통"] + y["영업외비용 공통"]
    if common_cost or y["영업외수익 공통"]:
        how = "개별 손금" if y["기준"] == "개별손금" else "수입금액"
        p.confirm.append(f"공통 손금 {common_cost:,}원은 {how} 비례로 그 밖의 사업에 {sp['a_g'] + sp['a_ne']:,}원"
                         f"({sp['cost_part']:,} / {sp['cost_whole']:,}), 공통 익금 {y['영업외수익 공통']:,}원은 수입금액 비례로 "
                         f"{sp['a_nr']:,}원을 나눴습니다. 두 사업의 업종(한국표준산업분류 소분류)이 같으면 수입금액, 다르면 개별 손금 "
                         "기준입니다(법인세법 시행규칙 제75조 제2항 · 제76조 제6항). 업종이 같은지는 회계사가 확인합니다")
        if (common_cost and sp["cost_whole"] <= 0) or (y["영업외수익 공통"] and sp["rev_t"] <= 0):
            p.confirm.append("안분 기준 금액이 0 이라 공통분을 그 밖의 사업에 나누지 못했습니다. 국세청장이 정하는 작업시간 · 사용시간 · "
                             "사용면적 기준(법인세법 시행규칙 제76조 제6항 단서)은 엔진이 계산하지 않으니 그 밖의 사업 개별분에 "
                             "직접 넣으십시오")
        elif common_cost and sp["cost_part"] <= 0:
            p.confirm.append("그 밖의 사업의 안분 기준 금액이 0 이라 공통 손금을 모두 감면 사업 손금으로 계산했습니다. 그 밖의 사업 매출액 · "
                             f"개별 손금이나 「{SPLIT}/안분 기준 가산/기타」 를 확인하십시오")
    over = (y["매출액/기타"] > book["매출액"] or y["매출원가/기타"] > book["매출원가"]
            or y["판관비 개별/기타"] + y["판관비 공통"] > book["판관비"] or y["영업외수익 공통"] > book["영업외수익"]
            or y["영업외비용 개별/기타"] + y["영업외비용 공통"] > book["영업외비용"])
    if over:
        p.confirm.append("소득구분 노란 칸에 넣은 그 밖의 사업분 · 공통분이 손익계산서 합계보다 큽니다. 금액을 확인하십시오")
    if sp["used"] and sp["other"] < 0:
        p.confirm.append(f"그 밖의 사업 소득이 {sp['other']:,}원(결손)입니다. 결손금은 소득이 난 사업의 소득에서 빼므로 감면 사업 소득을 "
                         "각사업연도소득으로 계산했습니다(조특법 제143조 제3항)")
    rent = [(a["name"], int(a.get("amount") or 0)) for a in b.accounts(cls="수익")
            if not _non_operating(a) and SALES_OTHER.search(a.get("name") or "") and int(a.get("amount") or 0)]
    if rent and not y["매출액/기타"] and p.values.get("감면율"):
        p.notes.append("매출 계정 중 감면 업종이 아닐 수 있는 것: " + " · ".join(f"{n} {v:,}" for n, v in rent)
                       + f". 그 밖의 사업 수입금액이면 노란 칸 「{SPLIT}/매출액/기타」 에 넣고 그 사업의 매출원가 · 판관비 개별분도 "
                       "함께 넣으십시오(법인세법 시행규칙 제75조 제1항). 넣지 않으면 매출액 전부를 감면 사업 수입금액으로 봅니다")


def _take_employment(p: Paper, b: Books, region: str) -> dict:
    """통합고용세액공제 노란 칸을 읽고 1 · 2 · 3차 연도 금액을 계산한다."""
    d = headcount_defaults(b)
    hc, first = {}, {}
    for per in PERIODS:
        hc[per] = (p.take(b, f"{EMP}/{per}/청년등", d["hc"][per][0], "ratio"),
                   p.take(b, f"{EMP}/{per}/청년등 외", d["hc"][per][1], "ratio"))
    for per in PERIODS[1:]:
        first[per] = (p.take(b, f"{EMP}/1차년도 공제액/{per}/청년등", d["first"][per][0], "int"),
                      p.take(b, f"{EMP}/1차년도 공제액/{per}/청년등 외", d["first"][per][1], "int"))
    size0 = d["size"] or ("중소기업" if b.sme else "일반기업")
    size_in = p.take(b, f"{EMP}/기업 구분", size0)
    size = size_in if size_in in SIZES else "일반기업"
    cap_in = p.take(b, f"{EMP}/증가 지역 수도권 여부", d["capital"] or region)
    capital = "부" if cap_in == "부" else "여"
    start = str((b.info or {}).get("fy_start") or "")
    fy_year = int(start[:4]) if start[:4].isdigit() else (int(b.fy) if str(b.fy).isdigit() else 0)
    prev_known = d["given"].get("직전") == "신고건.json"
    calc = integrated_credit(hc, first, size, capital, b.rates, fy_year, prev_known)
    extra_n = {kind: p.take(b, f"{EMP}/{name} 인원", d["extra"][kind], "int") for kind, name, _c, _l in EXTRA}
    info = b.info or {}
    extra = extra_credit(extra_n["convert"], extra_n["back"], size, calc["tot"]["해당"], calc["tot"]["직전"],
                         calc["prev_ok"], info.get("fy_start") or "", info.get("fy_end") or "", b.rates)
    return {"hc": hc, "first": first, "size": size, "size_in": size_in, "capital": capital, "cap_in": cap_in,
            "fy_year": fy_year, "prev_known": prev_known, "given": d["given"], "bad": d["bad"], "calc": calc,
            "extra": extra,
            "size_guess": not d["size"] and f"{EMP}/기업 구분" not in p.overridden and not b.sme}


def _employment_values(e: dict) -> dict:
    c, x = e["calc"], e["extra"]
    out = {}
    for per in PERIODS:
        out[f"{EMP}/{per}/청년등"], out[f"{EMP}/{per}/청년등 외"] = e["hc"][per]
        out[f"{EMP}/{per}/전체"] = float(c["tot"][per])
    for per in PERIODS[1:]:
        out[f"{EMP}/1차년도 공제액/{per}/청년등"], out[f"{EMP}/1차년도 공제액/{per}/청년등 외"] = e["first"][per]
    out.update({f"{EMP}/전체 증가": float(c["d_t"]), f"{EMP}/청년등 증가": float(c["d_y"]),
                f"{EMP}/청년등 외 증가": float(c["d_o"]), f"{EMP}/청년등 공제 인원": float(c["n_y"]),
                f"{EMP}/청년등 외 공제 인원": float(c["n_o"]), f"{EMP}/청년등 1인당": c["a_y"],
                f"{EMP}/청년등 외 1인당": c["a_o"], f"{EMP}/1차 청년등": c["first_y"],
                f"{EMP}/1차 청년등 외": c["first_o"], f"{EMP}/1차": c["first"], f"{EMP}/2차": c["second"],
                f"{EMP}/3차": c["third"], f"{EMP}/계산액": c["total"],
                **{f"{EMP}/{name} 인원": x[f"{kind}_n"] for kind, name, _c, _l in EXTRA},
                f"{EMP}/추가공제 1인당": x["unit"],
                **{f"{EMP}/추가공제/{name}": x[kind] for kind, name, _c, _l in EXTRA},
                f"{EMP}/추가공제 계": x["total"],
                EMP: {"used": c["used"], "size": e["size"], "capital": e["capital"], "fy_year": e["fy_year"],
                      "extra": {"unit": x["unit"], "convert_n": x["convert_n"], "back_n": x["back_n"],
                                "convert": x["convert"], "back": x["back"], "convert_why": x["convert_why"],
                                "back_why": x["back_why"]},
                      # 100분의 1 미만을 버린 인원 {기간: [청년등, 청년등 외, 전체]}(조특 10호의9 ⑥ ~ ⑧)
                      "headcount": {per: [float(c["n"][per][0]), float(c["n"][per][1]), float(c["tot"][per])]
                                    for per in PERIODS},
                      "first": {per: list(e["first"][per]) for per in PERIODS[1:]},
                      "second_cut": c["second_cut"], "third_cut": c["third_cut"], "in_time": c["in_time"],
                      "prev_ok": c["prev_ok"]}})
    return out


def _employment_notes(p: Paper, e: dict, cur18s: int) -> None:
    c = e["calc"]
    for msg in e["bad"]:
        p.confirm.append(msg)
    if not c["used"]:
        if any(e["first"]["직전"]) or any(e["first"]["직전전"]) or c["tot"]["직전"] > 0:
            p.confirm.append("통합고용세액공제: 해당 과세연도 상시근로자 수가 없어 계산하지 않았습니다"
                             f"(신고건.json 「{INFO_KEY}」 「해당」 또는 노란 칸 「{EMP}/해당/…」)")
        return
    if e["size_in"] not in SIZES:
        p.confirm.append(f"노란 칸 「{EMP}/기업 구분」 「{e['size_in']}」 을 읽지 못해 일반기업 금액으로 계산했습니다"
                         "(중소기업 · 중견기업 · 일반기업)")
    if e["cap_in"] not in ("여", "부"):
        p.confirm.append(f"노란 칸 「{EMP}/증가 지역 수도권 여부」 「{e['cap_in']}」 을 읽지 못해 수도권 금액으로 계산했습니다(여 · 부)")
    if e["size_guess"]:
        p.confirm.append(f"통합고용세액공제: 기준 시트 중소기업 여부가 「부」 라 일반기업 금액으로 계산했습니다. 중견기업이면 노란 칸 "
                         f"「{EMP}/기업 구분」 을 고치십시오(1인당 금액이 다릅니다, 조특법 제29조의8 제1항)")
    f = lambda x: f"{float(x):.2f}"   # noqa: E731
    if not c["in_time"]:
        p.confirm.append(f"통합고용세액공제 1차 연도: 1인당 금액은 2025년 12월 31일이 속하는 과세연도까지만 적용해 {e['fy_year']} 과세연도 "
                         "증가분은 계산하지 않았습니다(2026년 12월 31일이 속하는 과세연도부터 산식이 바뀜, 조특법 제29조의8 제1항). "
                         "2 · 3차 연도분만 입력한 값으로 계산했습니다(부칙 <제21223호> 제34조)")
    elif not c["prev_ok"]:
        p.confirm.append("통합고용세액공제 1차 연도: 직전 과세연도 상시근로자 수가 없어 계산하지 않았습니다. 해당 과세연도에 창업해 직전 "
                         f"인원이 0 이면(조특령 제23조 제13항 제1호) 신고건.json 「{INFO_KEY}」 「직전」 에 0 을 적으십시오")
    elif c["d_t"] <= 0:
        p.notes.append(f"통합고용세액공제 1차 연도: 전체 상시근로자가 직전 {f(c['tot']['직전'])}명, 해당 {f(c['tot']['해당'])}명으로 늘지 않아 "
                       "당기 증가분 공제가 없습니다(조특법 제29조의8 제1항)")
    else:
        p.notes.append(f"통합고용세액공제 1차 연도 {c['first']:,}원 = 청년등 {f(c['n_y'])}명 × {c['a_y']:,} + 청년등 외 {f(c['n_o'])}명 × "
                       f"{c['a_o']:,}({e['size']} · 증가 지역 수도권 {e['capital']}, 전체 증가 {f(c['d_t'])}명 한도, "
                       "조특법 제29조의8 제1항)")
    for name, per, key in (("2차", "직전", "second"), ("3차", "직전전", "third")):
        first, cut = e["first"][per], c[f"{key}_cut"]
        if not any(first):
            continue
        if cut in ("직전 인원 없음", "직전전 인원 없음"):
            p.confirm.append(f"통합고용세액공제 {name} 연도: {per} 과세연도 상시근로자 수가 없어 계산하지 않았습니다"
                             f"(노란 칸 「{EMP}/{per}/…」)")
        elif cut == "일반기업":
            p.notes.append("통합고용세액공제 3차 연도는 중소 · 중견기업만 받습니다(조특법 제29조의8 제1항 본문)")
        elif cut == "전체 감소":
            p.confirm.append(f"통합고용세액공제 {name} 연도: 전체 상시근로자 수가 최초 공제 연도({per})보다 줄어 {sum(first):,}원을 "
                             "공제하지 않았습니다. 공제받은 세액을 내야 합니다(조특법 제29조의8 제3항). 금액은 「추가 납부세액」 "
                             "확인 줄을 보십시오(조특령 제26조의8 제4항)")
        elif cut == "청년등 감소":
            p.confirm.append(f"통합고용세액공제 {name} 연도: 청년등 상시근로자 수가 최초 공제 연도({per})보다 줄어 청년등 몫 "
                             f"{first[0]:,}원을 빼고 {c[key]:,}원만 넣었습니다(조특법 제29조의8 제3항). 금액은 「추가 납부세액」 "
                             "확인 줄을 보십시오(조특령 제26조의8 제4항). 청년등 증가 인원에 청년등 외 금액을 적용할지는 반영하지 "
                             "않았습니다. 회계사 확인 필요")
        else:
            p.notes.append(f"통합고용세액공제 {name} 연도 {c[key]:,}원({per} 과세연도 증가분의 1차 연도 공제액, 인원이 줄지 않음)")
    p.confirm.append("통합고용세액공제 인원은 넣은 값을 그대로 썼습니다. 상시근로자 범위(조특령 제23조 제10항) · 청년등 범위(제26조의8 "
                     "제3항) · 인원 계산방법(제6항. 2025년 1월 1일 이후 개시 과세연도를 최초 공제연도로 하면 근로자별 근무개월 수 ÷ "
                     "과세연도 개월 수의 합, 그 전 증가분의 2 · 3차 연도 판정은 매월 말 인원 평균. 급여대장이 있으면 ctax employ 가 "
                     "셉니다)과 소비성서비스업이 아닌지(제1항)는 회계사가 확인합니다. 정규직 전환 · 육아휴직 "
                     f"복귀 추가공제(조특법 제29조의8 제4항 · 제5항)는 인원을 넣으면 계산합니다(노란 칸 「{EMP}/정규직 전환 인원」 · "
                     f"「{EMP}/육아휴직 복귀 인원」)")
    if EMP_KEY in p.overridden and cur18s != c["total"]:
        p.confirm.append(f"노란 칸 「{EMP_KEY}」 회계사 값 {cur18s:,}원이 인원으로 계산한 {c['total']:,}원과 다릅니다. 회계사 값으로 "
                         "8호(갑) 18S 를 채웁니다")


def _take_rnd(p: Paper, b: Books) -> dict:
    """연구 · 인력개발비 노란 칸을 읽고 당기분 방식 · 증가분 방식 금액을 계산한다."""
    d = rnd_defaults(b)
    k = lambda name: f"{RND}/{name}"   # noqa: E731
    # 발생명세 줄(조특 3호(1) ⑥ ~ ⑪). 넣은 줄의 합계가 「해당」 발생액 기본값이다(신고건.json 「해당」 이 있으면 그 값)
    detail = []
    for n in range(1, max(RND_DETAIL_ROWS, len(d["detail"])) + 1):
        d0 = d["detail"][n - 1] if n <= len(d["detail"]) else {}
        row = {"no": n, "계정과목": p.take(b, k(f"{RND_DETAIL} {n}/계정과목"), d0.get("계정과목", ""))}
        for part, unit, _code in RND_PARTS:
            row[f"{part} {unit}"] = p.take(b, k(f"{RND_DETAIL} {n}/{part} {unit}"), d0.get(f"{part} {unit}", 0), "int")
            row[part] = max(0, p.take(b, k(f"{RND_DETAIL} {n}/{part}"), d0.get(part, 0), "int"))
        row["계"] = sum(row[part] for part, _u, _c in RND_PARTS)
        detail.append(row)
    detail_total = sum(r["계"] for r in detail)
    cur = p.take(b, k("해당"), d["cur"] if d["cur_given"] else detail_total, "int")
    prev = [p.take(b, k(y), d["prev"][i], "int") for i, y in enumerate(RND_YEARS)]
    size0 = d["size"] or ("중소기업" if b.sme else "일반기업")
    size_in = p.take(b, k("기업 구분"), size0)
    size = size_in if size_in in SIZES else "일반기업"
    method_in = p.take(b, k("방식"), d["method"] or RND_METHODS[0])
    method = method_in if method_in in RND_METHODS else RND_METHODS[0]
    book_revenue = int(book_split(b)["매출액"])
    revenue = p.take(b, k("수입금액"), d["revenue"] if d["revenue"] is not None else book_revenue, "int")
    info = b.info or {}
    months = rnd_months(info.get("fy_start") or "", info.get("fy_end") or "")
    calc = rnd_credit(cur, prev, size, method, revenue, months, b.rates)
    given = {y: src for y, src in d["given"].items() if k(y) not in p.overridden}
    return {"cur": cur, "prev": prev, "size": size, "size_in": size_in, "method": method, "method_in": method_in,
            "revenue": revenue, "book_revenue": book_revenue, "months": months, "bad": d["bad"], "calc": calc,
            "detail": detail, "detail_total": detail_total, "given": given, "prior_why": d["prior_why"],
            "cur_from_detail": bool(detail_total) and not d["cur_given"] and k("해당") not in p.overridden,
            "size_guess": not d["size"] and k("기업 구분") not in p.overridden and not b.sme}


def _rnd_values(r: dict) -> dict:
    c = r["calc"]
    k = lambda name: f"{RND}/{name}"   # noqa: E731
    out = {k("해당"): r["cur"], **{k(y): r["prev"][i] for i, y in enumerate(RND_YEARS)},
           k("수입금액"): r["revenue"], k("직전 4년 합계"): c["total4"], k("발생 연도 수"): c["years"],
           k("연평균"): c["average"], k("증가발생액"): c["increase"], k("증가분 요건"): "여" if c["eligible"] else "부",
           k("당기분 공제율"): float(c["rate_cur"]), k("당기분 금액"): c["amount_cur"],
           k("증가분 공제율"): float(c["rate_inc"]), k("증가분 금액"): c["amount_inc"], k("계산액"): c["total"]}
    out[k(f"{RND_DETAIL} 합계")] = r["detail_total"]
    out[RND] = {"used": c["used"], "size": r["size"], "method": r["method"], "method_used": c["method_used"],
                "eligible": c["eligible"], "why": c["why"], "months": c["months"], "given": r["given"],
                # 발생명세 줄(값이 있는 줄만). 서식 조특 3호(1) ⑥ ~ ⑪ 줄이 된다
                "detail": [{x: v for x, v in row.items() if x != "no"} for row in r["detail"] if row["계"] or row["계정과목"]],
                "detail_total": r["detail_total"]}
    return out


def rnd_reference(b: Books) -> tuple[list[tuple[str, int]], dict | None]:
    """대상 금액을 넣지 않았을 때 참고로 보일 것: 장부의 연구 · 인력개발 비용 계정과 전기 신고서의 일반 연구 · 인력개발비 세액공제.
    ([(계정 이름, 금액)], {"code", "used", "carry", "due"} 또는 None). 대상 금액으로 쓰지 않는다."""
    accounts = [(a.get("name") or "", int(a.get("amount") or 0)) for a in b.accounts(cls="비용")
                if RND_ACCOUNT.search(a.get("name") or "") and int(a.get("amount") or 0)]
    prior = b.prior or {}
    got = None
    for c in prior.get("credits") or []:
        code = str(c.get("code") or "")
        if code in RND_CODES and (int(c.get("amount") or 0) or int(c.get("carryforward") or 0)):
            got = got or {"code": code, "used": 0, "carry": 0, "due": 0}
            got["used"] += int(c.get("amount") or 0)
            got["carry"] += int(c.get("carryforward") or 0)
    prior_fy = int(prior.get("fy")) if str(prior.get("fy") or "").isdigit() else None
    for row in prior.get("credit_years") or []:
        if (isinstance(row, dict) and str(row.get("code") or "") in RND_CODES and int(row.get("due_current") or 0)
                and (prior_fy is None or row.get("year") == prior_fy)):
            got = got or {"code": str(row["code"]), "used": 0, "carry": 0, "due": 0}
            got["due"] += int(row["due_current"])
    return accounts, got


def _rnd_notes(p: Paper, b: Books, r: dict, cur_amount: int) -> None:
    c = r["calc"]
    for msg in r["bad"]:
        p.confirm.append(msg)
    if r["prior_why"]:
        p.confirm.append(f"연구 · 인력개발비 세액공제: {r['prior_why']}")
    if r["given"]:
        p.notes.append("연구 · 인력개발비 직전 과세연도 발생액 기본값은 전기 신고서에서 옮겼습니다: "
                       + " · ".join(f"{y} {r['prev'][RND_YEARS.index(y)]:,}원({src})" for y, src in r["given"].items())
                       + f". 신고건.json 「{RND_INFO}」 나 노란 칸 「{RND}/직전 1년」 ~ 「직전 4년」 에 넣은 값이 있으면 그 값이 이깁니다")
        if any((q.get("ref") or "") == "rnd.read" for q in (b.prior or {}).get("problems") or [] if isinstance(q, dict)):
            p.confirm.append("연구 · 인력개발비 세액공제: 전기 신고서 조특 3호(1) 을 읽으면서 확인사항이 있었습니다(전기.json problems). "
                             "직전 과세연도 발생액 기본값을 전기 신고서와 맞춰 보십시오")
    if r["detail_total"]:
        if r["cur_from_detail"]:
            p.notes.append(f"연구 · 인력개발비 해당 과세연도 발생액 {r['cur']:,}원은 발생명세 줄의 합계입니다(조특 3호(1) ⑪ = ⑫)")
        elif r["cur"] != r["detail_total"]:
            p.confirm.append(f"연구 · 인력개발비 세액공제: 「해당」 발생액 {r['cur']:,}원이 발생명세 줄의 합계 {r['detail_total']:,}원과 "
                             "다릅니다. 「해당」 값으로 계산했습니다. 조특 3호(1) 은 ⑫ 해당 과세연도 발생액이 ⑪ 총계와 같아야 합니다")
    where = f"신고건.json 「{RND_INFO}」 「해당」 · 「{RND_DETAIL}」 또는 노란 칸 「{RND}/해당」 · 「{RND}/{RND_DETAIL} N/…」"
    if not c["used"]:
        accounts, prior = rnd_reference(b)
        if RND_KEY in p.overridden:
            return
        tail = (f"대상 금액은 연구소 · 전담부서 인건비 등으로 따로 가려 넣으십시오({where}). 계정 금액에는 공제 대상이 아닌 비용이 섞여 있어 "
                "엔진이 대상 금액으로 쓰지 않습니다(조특령 제9조 제1항 · 별표 6)")
        book = ("장부의 연구 · 인력개발 비용 계정 합계 " + f"{sum(v for _, v in accounts):,}원("
                + " · ".join(f"{n} {v:,}" for n, v in accounts) + ")") if accounts else ""
        if prior:
            before = (f"전기 8호(갑) {prior['code']} 일반 연구 · 인력개발비 세액공제 공제세액 {prior['used']:,}원 · 이월액 {prior['carry']:,}원"
                      + (f" · 전기 당기분 요공제세액 {prior['due']:,}원" if prior["due"] else ""))
            p.confirm.append("연구 · 인력개발비 세액공제 당기분: 전기에 공제가 있는데 당기 대상 금액을 넣지 않아 계산하지 않았습니다. 당기 발생분이 "
                             f"빠지면 다음 해로 넘기는 이월액이 작게 나옵니다. 참고: {before}" + (f", {book}" if book else "") + f". {tail}")
        elif book:
            p.notes.append(f"연구 · 인력개발비 세액공제 당기분 참고: {book}. 세액공제를 신청하면 {tail}")
        return
    if r["size_in"] not in SIZES:
        p.confirm.append(f"노란 칸 「{RND}/기업 구분」 「{r['size_in']}」 을 읽지 못해 일반기업 율로 계산했습니다(중소기업 · 중견기업 · 일반기업)")
    if r["method_in"] not in RND_METHODS:
        p.confirm.append(f"노란 칸 「{RND}/방식」 「{r['method_in']}」 을 읽지 못해 큰 쪽으로 계산했습니다(큰 쪽 · 당기분 · 증가분)")
    if r["size_guess"]:
        p.confirm.append(f"연구 · 인력개발비 세액공제: 기준 시트 중소기업 여부가 「부」 라 일반기업 율로 계산했습니다. 중견기업(조특령 제9조 "
                         f"제4항)이면 노란 칸 「{RND}/기업 구분」 을 고치십시오(당기분 8%, 증가분 40%)")
    if (r["size"] == "중소기업") != bool(b.sme):
        p.confirm.append(f"연구 · 인력개발비 세액공제: 노란 칸 「{RND}/기업 구분」 「{r['size']}」 이 기준 시트 중소기업 여부와 다릅니다. 8호(갑) "
                         "코드(16B · 13M)와 최저한세 적용 여부는 기준 시트 값을 따릅니다")
    pct = lambda x: f"{float(x) * 100:.4f}".rstrip("0").rstrip(".") + "%"   # noqa: E731
    p.notes.append(f"연구 · 인력개발비 세액공제 당기분 방식 {c['amount_cur']:,}원 = 해당 발생액 {c['cur']:,}원 × {pct(c['rate_cur'])}"
                   f"({r['size']}, 조특법 제10조 제1항 제3호 나목)")
    if r["size"] == "일반기업":
        if r["revenue"] <= 0:
            p.confirm.append(f"연구 · 인력개발비 세액공제: 수입금액이 없어 일반기업 공제율을 계산하지 못했습니다(노란 칸 「{RND}/수입금액」)")
        else:
            p.confirm.append(f"연구 · 인력개발비 세액공제: 일반기업 공제율은 해당 발생액 / 수입금액 {r['revenue']:,}원 × 1/2 (2% 한도)를 "
                             "반올림하지 않고 썼습니다(조특법 제10조 제1항 제3호 나목 4)). 수입금액은 기업회계기준 매출액입니다")
    if r["size"] != "중소기업":
        p.confirm.append("연구 · 인력개발비 세액공제: 중소기업이었다가 처음 중소기업에 해당하지 않게 된 과세연도부터 5년 안이면 당기분 공제율이 "
                         "다릅니다(3년 안 20%, 그 뒤 2년 안 15%, 2025년 1월 1일 전에 개시한 과세연도에 해당하지 않게 됐으면 15% · 10%, "
                         "조특법 제10조 제1항 제3호 나목 2) · 부칙 <제20617호> 제3조 제1항). 엔진은 계산하지 않으니 해당하면 노란 칸 "
                         f"「{RND_KEY}」 에 직접 넣으십시오")
    if c["eligible"]:
        p.notes.append(f"연구 · 인력개발비 세액공제 증가분 방식 {c['amount_inc']:,}원 = (해당 발생액 {c['cur']:,}원 - 직전 1년 {c['prev'][0]:,}원) × "
                       f"{pct(c['rate_inc'])}(직전 1년 발생액이 연평균 {c['average']:,}원 이상, 조특법 제10조 제1항 제3호 가목)")
    elif c["why"] == "직전 4년 발생액 없음":
        p.notes.append("연구 · 인력개발비 세액공제 증가분 방식: 직전 4년 발생액이 없어 당기분 방식만 씁니다(조특법 제10조 제1항 제3호 단서). "
                       f"직전 과세연도에 발생액이 있으면 노란 칸 「{RND}/직전 1년」 ~ 「직전 4년」 에 넣으십시오")
    else:
        p.notes.append(f"연구 · 인력개발비 세액공제 증가분 방식: 직전 1년 발생액 {c['prev'][0]:,}원이 직전 4년 연평균 {c['average']:,}원"
                       f"(합계 {c['total4']:,}원 / 발생한 과세연도 {c['years']}개 × {c['months']}개월 / 12)보다 적어 당기분 방식만 씁니다"
                       "(조특법 제10조 제1항 제3호 단서, 조특령 제9조 제9항)")
    if r["method"] == "증가분" and not c["eligible"]:
        p.confirm.append("연구 · 인력개발비 세액공제: 방식을 증가분으로 골랐지만 요건을 채우지 못해 당기분 방식 금액을 넣었습니다")
    if c["months"] != 12:
        p.confirm.append(f"연구 · 인력개발비 세액공제: 해당 과세연도가 {c['months']}개월이라 연평균 발생액에 {c['months']}/12 를 곱했습니다(조특령 "
                         "제9조 제9항). 직전 과세연도가 1년이 아니면 직전 발생액 넣은 값을 확인하십시오")
    p.confirm.append("연구 · 인력개발비 발생액은 넣은 값을 그대로 썼습니다(0 으로 둔 해는 발생하지 않은 해로 봄). 대상 비용 범위(조특령 별표 6: "
                     "연구소 · 전담부서 연구원 인건비 · 재료비 · 위탁 연구개발비 등), 출연금 등으로 쓴 금액 제외(제9조 제1항), 연구소 · "
                     "전담부서 인정은 회계사가 확인합니다. 신성장 · 원천기술 · 국가전략기술 연구개발비(조특법 제10조 제1항 제1호 · 제2호)는 "
                     "계산하지 않습니다. 이 공제에는 농어촌특별세가 없습니다(농어촌특별세법 시행령 제4조 제7항 제1호)")
    if RND_KEY in p.overridden and cur_amount != c["total"]:
        p.confirm.append(f"노란 칸 「{RND_KEY}」 회계사 값 {cur_amount:,}원이 발생액으로 계산한 {c['total']:,}원과 다릅니다. 회계사 값으로 "
                         "8호(갑) · 8호 부표3 을 채웁니다")


FOLLOW_INFO = "고용증대 청년등"      # 신고건.json 「상시근로자」 「해당」 안의 키(제29조의7 기준 청년등 상시근로자 수)


def employment_followup(prior: dict, fy: int, sme: bool, total: float | None = None, youth: float | None = None,
                        mid: bool = False) -> dict | None:
    """전기 신고서로 본 고용증대 세액공제(제29조의7) 2 · 3차 연도 금액. 전기에 고용증대 공제가 없으면 None.

    {"prior_current": 전기 8호(갑) 18F ⑥ 당기발생액, "second": 전기 1차년도 ⑮ 계(→ 당기 2차 연도), "third": 전기 2차년도 공제액(→ 당기
    3차 연도, 중소 · 중견), "amount": second + third(중소 · 중견기업일 때), "known": 조특 10호의8 금액을 읽었는지,
    "parts": 연차별 판정, "default": 노란 칸 기본값}

    `total` 은 당기 전체 상시근로자 수, `youth` 는 당기 청년등 상시근로자 수(제29조의7 기준: 시행령 제26조의7 제3항, 통합고용의
    청년등과 범위가 다르다). 전기.json employment["10의8"] 에 연차별 금액과 최초 공제 연도 인원이 있고 `total` 이 있으면 제2항대로
    판정해 기본값을 낸다. 전체가 최초 공제 연도보다 줄었으면 그 연차는 0, 줄지 않았으면 청년등 외 몫을 넣고, 청년등 몫은 `youth` 가
    최초 공제 연도보다 줄지 않았을 때만 넣는다. 인원이 없으면 기본값은 0 이다(추정하지 않는다)."""
    credits = {str(c.get("code") or "") for c in prior.get("credits") or []}
    cells = prior.get("cells") or {}
    cur6 = int((cells.get("8갑") or {}).get("18F_6") or 0)
    if "18F" not in credits and not cur6:
        return None
    # 고용증대는 2024년이 속하는 과세연도까지 늘어난 인원만 대상이고 그 뒤 2년(중소 · 중견)이 끝이다(제29조의7 제1항)
    if fy and fy > 2026:
        return None
    long = bool(sme or mid)
    c108 = cells.get("조특10의8") or {}
    second, third = int(c108.get("1차_계") or 0), int(c108.get("2차_계") or 0)
    known = bool(second or third)
    e8 = prior["employment"].get("10의8") if isinstance(prior.get("employment"), dict) else None
    by = {r.get("차수"): r for r in (e8 or {}).get("by_year") or [] if isinstance(r, dict)}
    hc = (e8 or {}).get("headcount") or {}
    parts, default = [], 0
    for n, base_key in ((1, "current"), (2, "prior")):
        r = by.get(n) or {}
        amount = r.get("amount")
        if not amount or (n == 2 and not long):
            continue
        base = hc.get(base_key) or {}
        base_total = base.get("상시") if base.get("상시") is not None else r.get("first_headcount")
        part = {"차수": n + 1, "year": r.get("year"), "amount": int(amount), "청년등": r.get("청년등"), "청년등외": r.get("청년등외"),
                "base_total": base_total, "base_youth": base.get("청년등"), "used": 0, "state": ""}
        if total is None:
            part["state"] = "인원 없음"
        elif base_total is None or part["청년등"] is None or part["청년등외"] is None:
            part["state"] = "전기 서식 못 읽음"
        elif q2(total) < q2(base_total):
            part["state"] = "전체 감소"
        else:
            part["used"] = int(part["청년등외"])
            if not part["청년등"]:
                part["state"] = "유지"
            elif youth is None or part["base_youth"] is None:
                part["state"] = "청년등 인원 없음"
            elif q2(youth) < q2(part["base_youth"]):
                part["state"] = "청년등 감소"
            else:
                part["used"] += int(part["청년등"])
                part["state"] = "유지"
        default += part["used"]
        parts.append(part)
    return {"prior_current": cur6, "second": second, "third": third, "amount": second + (third if long else 0),
            "known": known, "parts": parts, "default": default}


def _follow_inputs(b: Books, emp: dict) -> tuple[float | None, float | None]:
    """(당기 전체 상시근로자 수, 제29조의7 기준 청년등 상시근로자 수). 전체는 통합고용 노란 칸 「해당」 의 합(같은 상시근로자 범위,
    시행령 제23조 제10항)이고, 청년등은 신고건.json 「상시근로자」 「해당」 「고용증대 청년등」 이다. 없으면 None."""
    total = float(emp["calc"]["tot"]["해당"]) if emp["calc"]["used"] else None
    info = (b.info or {}).get(INFO_KEY)
    cur = info.get("해당") if isinstance(info, dict) else None
    raw_youth = cur.get(FOLLOW_INFO) if isinstance(cur, dict) else None
    try:
        youth = float(raw_youth) if raw_youth not in (None, "") else None
    except (TypeError, ValueError):
        youth = None
    return total, youth


def _employment_followup(p: Paper, b: Books, cur18f: int, cur18s: int, f: dict | None) -> None:
    prior = b.prior or {}
    p.extra["employment"] = f
    judged = [x for x in (f or {}).get("parts") or [] if x["state"] != "인원 없음"]
    if f and judged and EMPLOY_KEY not in p.overridden:
        for x in judged:
            name = f"고용증대 세액공제 {x['차수']}차 연도({x['year']} 과세연도 증가분)"
            if x["state"] == "전체 감소":
                p.confirm.append(f"{name}: 전체 상시근로자 수가 최초 공제 연도의 {float(x['base_total']):.2f}명보다 줄어 {x['amount']:,}원을 "
                                 "공제하지 않았습니다. 공제받은 세액을 내야 합니다(조특법 제29조의7 제2항). 금액은 「추가 납부세액」 "
                                 "확인 줄을 보십시오(조특령 제26조의7 제5항)")
            elif x["state"] == "전기 서식 못 읽음":
                p.confirm.append(f"{name}: 전기 조특 10호의8 에서 최초 공제 연도 인원이나 청년등 · 청년등 외 금액을 읽지 못해 넣지 않았습니다. "
                                 f"확인해 노란 칸 「{EMPLOY_KEY}」 에 넣으십시오")
            elif x["state"] == "청년등 인원 없음":
                p.confirm.append(f"{name}: 청년등 외 몫 {x['used']:,}원만 넣었습니다. 청년등 몫 {int(x['청년등']):,}원은 청년등 상시근로자 수가 "
                                 "최초 공제 연도보다 줄지 않았을 때만 받습니다(조특법 제29조의7 제2항). 이 공제의 청년등은 29세 이하 기준이라 "
                                 "통합고용세액공제의 청년등과 범위가 다릅니다(조특령 제26조의7 제3항). 인원을 신고건.json "
                                 f"「{INFO_KEY}」 「해당」 「{FOLLOW_INFO}」 에 적으십시오")
            elif x["state"] == "청년등 감소":
                p.confirm.append(f"{name}: 청년등 상시근로자 수가 최초 공제 연도의 {float(x['base_youth']):.2f}명보다 줄어 청년등 몫 "
                                 f"{int(x['청년등']):,}원을 빼고 {x['used']:,}원만 넣었습니다(조특법 제29조의7 제2항). 금액은 "
                                 "「추가 납부세액」 확인 줄을 보십시오(조특령 제26조의7 제5항)")
            else:
                p.notes.append(f"{name} {x['used']:,}원(전기 조특 10호의8, 전체 · 청년등 상시근로자 수가 최초 공제 연도보다 줄지 않음)")
        p.confirm.append("고용증대 세액공제 2 · 3차 연도 판정에 쓴 인원은 넣은 값 그대로입니다. 상시근로자 범위(조특령 제23조 제10항)와 "
                         "최초 공제 연도에 청년등이던 사람을 이후에도 청년등으로 세는지(제26조의7 제6항)는 회계사가 확인합니다")
    elif f and not cur18f and EMPLOY_KEY not in p.overridden:
        head = (f"전기에 고용증대 세액공제가 있습니다(전기 8호(갑) 18F 당기발생 {f['prior_current']:,}원). 상시근로자 · 청년등 상시근로자가 "
                "최초 공제 연도보다 줄지 않았으면 당기에 2차 연도(전기에 늘어난 인원) · 3차 연도(그 전 해 인원, 중소 · 중견기업) 공제가 "
                "이어집니다(조특법 제29조의7 제1항 · 제2항)")
        if f["known"]:
            p.confirm.append(head + f". 넣으면 「{EMPLOY_KEY}」 {f['amount']:,}원(전기 조특 10호의8 1차년도 ⑮ 계 {f['second']:,}원 + "
                             f"2차년도 세액공제액 {f['third']:,}원)입니다. 줄었으면 0 이고 추가 납부를 봅니다. 당기 인원을 신고건.json "
                             f"「{INFO_KEY}」 「해당」 에 적으면 엔진이 판정해 넣습니다")
        else:
            p.confirm.append(head + ". 금액은 전기 조특 10호의8 의 1차년도 ⑮ 계 + 2차년도 세액공제액이고 ctax forms 가 서식.json 알림에 "
                             f"적습니다. 인원을 확인해 노란 칸 「{EMPLOY_KEY}」 에 넣으십시오")
    prior18s = int(((prior.get("cells") or {}).get("8갑") or {}).get("18S_6") or 0)
    if prior18s and not cur18s and "당기분/통합고용세액공제" not in p.overridden:
        p.confirm.append(f"전기에 통합고용세액공제 당기발생 {prior18s:,}원이 있습니다. 상시근로자가 줄지 않았으면 2 · 3차 연도 공제가 이어집니다"
                         "(조특법 제29조의8 제1항 · 제3항, 2024 · 2025 증가분은 부칙 <제21223호> 제34조로 종전 규정). 전기 조특 10호의9 로 "
                         "금액을 확인해 노란 칸 「당기분/통합고용세액공제」 에 더하십시오")


def _extra_notes(p: Paper, e: dict, cur: dict) -> None:
    """통합고용 추가공제(정규직 전환 · 육아휴직 복귀) 알림. `cur` 는 {당기분 노란 칸 key: 금액}."""
    x = e["extra"]
    for kind, name, code, law in EXTRA:
        n, amt, why = x[f"{kind}_n"], x[kind], x[f"{kind}_why"]
        key = f"당기분/{EXTRA_LABEL[kind]}"
        if not n:
            continue
        head = f"통합고용 {name} 추가공제"
        if why == "기간 아님" and kind == "convert":
            p.confirm.append(f"{head}: 2024년 1월 1일부터 2024년 12월 31일까지 전환한 인원만 대상이라 이 과세연도에는 계산하지 "
                             "않았습니다(조특법 제29조의8 제4항). 2026. 3. 20. 개정 조특 10호의9서식(1)에도 정규직 전환 줄이 없습니다")
        elif why == "기간 아님":
            p.confirm.append(f"{head}: 2026년 12월 31일까지 복직한 인원이 대상인 판(법률 제21223호 개정 판)으로 계산해 이 과세연도에는 "
                             "넣지 않았습니다. 이 과세연도가 끝난 뒤에도 복직 기한이 늘었다면 해당하는 인원을 노란 칸 "
                             f"「{key}」 에 직접 넣으십시오(조특법 제29조의8 제5항)")
        elif why:
            p.confirm.append(f"{head}: {EXTRA_WHY[why]}(조특법 제29조의8 {law}). 넣은 인원 {n}명")
        else:
            p.notes.append(f"{head} {amt:,}원 = {n}명 × {x['unit']:,}원({e['size']}, 해당 과세연도 상시근로자 수가 직전 과세연도보다 "
                           f"줄지 않음, 조특법 제29조의8 {law}). 8호(갑) 코드 {code} 줄로 갑니다")
            if kind == "convert":
                p.confirm.append(f"{head}: 인원은 넣은 값을 그대로 썼습니다. 2023년 6월 30일 당시 고용하던 기간제 · 단시간 · 파견 근로자를 "
                                 "2024년 중 전환했는지, 최대주주와 그 친족이 아닌지는 회계사가 확인합니다. 2026. 3. 20. 개정 조특 "
                                 "10호의9서식(1)에 정규직 전환 줄이 없어 그 서식에는 넣지 않았습니다")
            else:
                p.confirm.append(f"{head}: 인원은 넣은 값을 그대로 썼습니다. 그 기업에서 1년 이상 근무했는지, 육아휴직이 연속 6개월 "
                                 "이상인지, 자녀 1명당 한 차례인지, 최대주주와 그 친족이 아닌지(조특법 제29조의8 제5항 · 제6항)는 "
                                 "회계사가 확인합니다" + (". 과세연도가 2025년 12월 31일 뒤에 끝나니 그날까지 복직한 인원만 넣으십시오"
                                                   if x["back_late"] else ""))
        if key in p.overridden and cur.get(key, 0) != amt:
            p.confirm.append(f"노란 칸 「{key}」 회계사 값 {cur.get(key, 0):,}원이 인원으로 계산한 {amt:,}원과 다릅니다. 회계사 값으로 "
                             f"8호(갑) {code} 를 채웁니다")
    if x["total"]:
        p.confirm.append("통합고용 추가공제: 전환일 · 복직일부터 2년이 지나기 전에 그 근로자와 근로관계를 끝내면 그 과세연도 신고 때 공제받은 "
                         "세액을 납부합니다(조특법 제29조의8 제7항). 엔진은 계산하지 않습니다")


def _cohorts(b: Books, emp: dict, follow: dict | None, total, youth) -> list[dict]:
    """당기가 사후관리 기간(최초 공제 과세연도 종료일부터 2년)에 드는 공제 묶음. 계산에 필요한 인원 · 공제액이 다 있는 묶음만 낸다.

    통합고용은 노란 칸 「통합고용/…」 의 직전 · 직전전 인원과 그해 1차년도 공제액, 고용증대는 전기 조특 10호의8 에서 읽은 최초
    공제 연도 인원 · 공제액(`follow["parts"]`)과 당기 전체 · 29세 이하 기준 청년등 인원(`total` · `youth`)이다.
    `inc0` 은 최초 공제 과세연도의 청년등 증가 인원(전기 서식 1차년도 표, 그해 청년등 공제액이 0 이면 0, 모르면 None),
    `mid` 는 3차 연도 묶음의 직전 과세연도 인원(제1호로 계산한 금액 · 공제받은 횟수 기본값에 쓴다)."""
    out = []
    c = emp["calc"]
    prior_emp = (b.prior or {}).get("employment")
    prior_emp = prior_emp if isinstance(prior_emp, dict) else {}
    fy = emp["fy_year"]
    if c["used"]:
        e9 = prior_emp.get("10의9") or {}
        first9 = next((r for r in e9.get("by_year") or [] if isinstance(r, dict) and r.get("차수") == 1), {})
        for tag, per, period in (("2차", "직전", 1), ("3차", "직전전", 2)):
            credit = tuple(int(v) for v in emp["first"][per])
            if not any(credit) or c["tot"][per] <= 0:
                continue
            inc = _inc_youth(e9.get("cells"), "20") if period == 1 and first9.get("amount") else None
            if inc is None and not credit[0]:
                inc = 0.0
            mid = c["n"]["직전"] if period == 2 and c["tot"]["직전"] > 0 else None
            out.append({"scheme": EMP, "name": "통합고용세액공제", "code": "18S", "tag": tag, "period": period,
                        "year": fy - period if fy else None, "first": c["n"][per], "cur": c["n"]["해당"], "mid": mid,
                        "credit": credit, "mid_credit": None, "inc0": inc, "a1": c["a_y"], "a2": c["a_o"], "carry_cut": True,
                        "law": "조특법 제29조의8 제3항 · 조특령 제26조의8 제4항", "same": "조특령 제26조의8 제5항"})
    e8 = prior_emp.get("10의8") or {}
    hc8 = (e8.get("headcount") or {}).get("current") or {}
    for part in (follow or {}).get("parts") or []:
        vals = (total, youth, part.get("base_total"), part.get("base_youth"), part.get("청년등"), part.get("청년등외"))
        if any(v is None for v in vals):
            continue
        first = (q2(part["base_youth"]), q2(part["base_total"]) - q2(part["base_youth"]))
        cur = (q2(youth), q2(total) - q2(youth))
        if first[1] < 0 or cur[1] < 0:
            continue
        period = int(part["차수"]) - 1
        credit = (int(part["청년등"]), int(part["청년등외"]))
        inc = _inc_youth(e8.get("cells"), "15") if period == 1 else None
        if inc is None and not credit[0]:
            inc = 0.0
        mid = None
        if period == 2 and hc8.get("상시") is not None and hc8.get("청년등") is not None:
            mid = (q2(hc8["청년등"]), q2(hc8["상시"]) - q2(hc8["청년등"]))
        a1, a2 = per_head_increase(emp["size"], emp["capital"], b.rates)
        out.append({"scheme": "고용증대", "name": "고용증대 세액공제", "code": "18F", "tag": f"{part['차수']}차", "period": period,
                    "year": part.get("year"), "first": first, "cur": cur, "mid": mid, "credit": credit,
                    "mid_credit": int(part.get("amount") or 0) if period == 2 else None, "inc0": inc, "a1": a1, "a2": a2,
                    "carry_cut": False, "law": "조특법 제29조의7 제2항 · 조특령 제26조의7 제5항", "same": "조특령 제26조의7 제6항"})
    return out


def _take_additional(p: Paper, b: Books, emp: dict, follow: dict | None, total, youth) -> dict:
    """추가 납부세액. 묶음마다 노란 칸(최초 청년등 증가 인원 · 공제받은 횟수 · 제1호 금액 · 공제받은 세액 · 이월 차감)을 읽고
    `clawback` 으로 계산한다. {"rows": [...], "total"}"""
    rows = []
    for co in _cohorts(b, emp, follow, total, youth):
        k = f"{ADD}/{co['scheme']}/{co['tag']}"
        first, cur, credit, period, a1, a2 = co["first"], co["cur"], co["credit"], co["period"], co["a1"], co["a2"]
        inc = p.take(b, f"{k}/최초 청년등 증가 인원", co["inc0"] or 0, "ratio")
        inc_known = co["inc0"] is not None or f"{k}/최초 청년등 증가 인원" in p.overridden
        times, paid, limit0 = 1, 0, sum(credit)
        if period == 2:
            mid = co["mid"]
            if co["mid_credit"] is not None:              # 고용증대: 전기 서식의 2차년도 세액공제액이 직전 과세연도에 받은 금액
                credited = co["mid_credit"]
            elif mid is not None and sum(mid) >= sum(first):   # 통합고용: 직전 과세연도에 전체가 줄지 않았으면 받았다
                credited = (0 if mid[0] < first[0] else credit[0]) + credit[1]
            else:
                credited = 0
            paid0 = 0
            if mid is not None:
                before = clawback(first, mid, inc if inc_known else None, a1, a2, 1)
                paid0 = min(before["amount"], sum(credit)) if before["amount"] is not None else 0
            times = p.take(b, f"{k}/공제받은 횟수", 2 if credited else 1, "int")
            paid = p.take(b, f"{k}/제1호 금액", paid0, "int")
            limit0 += credited
        limit = p.take(b, f"{k}/공제받은 세액", limit0, "int")
        cut = p.take(b, f"{k}/이월 차감", 0, "int") if co["carry_cut"] else 0
        res = clawback(first, cur, inc if inc_known else None, a1, a2, period, times, paid)
        ok = res["amount"] is not None
        pay = max(0, min(res["amount"], limit) - cut) if ok else 0
        rows.append({**co, "key": k, "inc": inc, "inc_known": inc_known, "times": times, "paid": paid, "limit": limit,
                     "cut": cut, "case": res["case"], "d_t": res["d_t"], "d_y": res["d_y"], "d_o": res["d_o"],
                     "raw": res["raw"] or 0, "ok": ok, "amount": pay})
    return {"rows": rows, "total": sum(r["amount"] for r in rows)}


def _additional_values(add: dict) -> dict:
    out = {}
    shown = []
    for r in add["rows"]:
        k = r["key"]
        out[f"{k}/최초 청년등 증가 인원"] = r["inc"]
        if r["period"] == 2:
            out[f"{k}/공제받은 횟수"], out[f"{k}/제1호 금액"] = r["times"], r["paid"]
        out[f"{k}/공제받은 세액"] = r["limit"]
        if r["carry_cut"]:
            out[f"{k}/이월 차감"] = r["cut"]
        out.update({f"{k}/전체 감소": float(r["d_t"]), f"{k}/청년등 감소": float(r["d_y"]), f"{k}/청년등 외 감소": float(r["d_o"]),
                    f"{k}/1인당 청년등": r["a1"], f"{k}/1인당 청년등 외": r["a2"], f"{k}/산식 금액": r["raw"],
                    f"{k}/납부세액": r["amount"]})
        shown.append({"scheme": r["scheme"], "code": r["code"], "tag": r["tag"], "year": r["year"], "period": r["period"],
                      "case": r["case"], "ok": r["ok"], "d_t": float(r["d_t"]), "d_y": float(r["d_y"]), "d_o": float(r["d_o"]),
                      "first": [float(v) for v in r["first"]], "cur": [float(v) for v in r["cur"]], "credit": list(r["credit"]),
                      "inc": r["inc"] if r["inc_known"] else None, "a1": r["a1"], "a2": r["a2"], "times": r["times"],
                      "paid": r["paid"], "raw": r["raw"], "limit": r["limit"], "cut": r["cut"], "amount": r["amount"]})
    out[ADD_KEY] = add["total"]
    out[ADD] = {"total": add["total"], "rows": shown}
    return out


def _additional_notes(p: Paper, b: Books, add: dict) -> None:
    f = lambda x: f"{float(x):.2f}"   # noqa: E731
    prior = b.prior or {}
    for r in add["rows"]:
        k, a1, a2 = r["key"], r["a1"], r["a2"]
        head = f"{r['name']} 추가 납부세액 {r['tag']} 연도" + (f"({r['year']} 과세연도 증가분)" if r["year"] else "")
        if not r["case"]:
            p.notes.append(f"{head}: 전체 · 청년등 상시근로자 수가 최초 공제 과세연도보다 줄지 않아 납부할 세액이 없습니다({r['law']})")
            continue
        drop = (f"최초 공제 과세연도보다 전체 {f(r['d_t'])}명 · 청년등 {f(r['d_y'])}명 · 청년등 외 {f(r['d_o'])}명 감소"
                "(음수는 증가)")
        where = f"제{r['period']}호 {ADD_CASE[r['case']]}"
        if not r["ok"]:
            p.confirm.append(f"{head}: {drop}. 납부할 세액이 있으나 최초 공제 과세연도의 청년등 증가 인원 수가 없어 계산하지 "
                             f"않았습니다({r['law']} {where}). 그해 신고서 공제세액계산서 1차년도 표의 청년등 증가 인원을 노란 칸 "
                             f"「{k}/최초 청년등 증가 인원」 에 넣으십시오")
            continue
        if r["case"] == "가1":
            expr = (f"[min(청년등 감소 {f(r['d_y'])}, 최초 연도 청년등 증가 {f(r['inc'])}) - 전체 감소 {f(r['d_t'])}] × "
                    f"({a1:,} - {a2:,}) + 전체 감소 {f(r['d_t'])} × {a1:,}")
        elif r["case"] == "가2":
            expr = (f"min(청년등 감소, 전체 감소) {f(min(max(r['d_y'], 0), r['d_t']))} × {a1:,} + min(청년등 외 감소, 전체 감소) "
                    f"{f(min(max(r['d_o'], 0), r['d_t']))} × {a2:,}")
        else:
            expr = f"min(청년등 감소 {f(r['d_y'])}, 최초 연도 청년등 증가 {f(r['inc'])}) × ({a1:,} - {a2:,})"
        if r["period"] == 2:
            expr = f"({expr}) × 공제받은 횟수 {r['times']}"
        tail = (f" - 제1호로 계산한 금액 {r['paid']:,}원" if r["paid"] else "") + (f" - 이월 차감 {r['cut']:,}원" if r["cut"] else "")
        msg = (f"{head} {r['amount']:,}원: {drop}. {expr} = {r['raw']:,}원{tail}, 한도 {r['limit']:,}원(직전 {r['period']}년 이내 "
               f"과세연도에 공제받은 세액, {r['law']} {where}). 조서 3호 29 란(3호 (133) 감면분 추가납부세액) 기본값에 더했습니다. "
               f"회계사 확인 필요: 1인당 금액 {a1:,}원 · {a2:,}원은 지금 넣은 기업 구분 · 증가 지역으로 정했습니다(최초 공제 과세연도 "
               f"기준인지), 최초 공제 과세연도에 청년등이던 사람을 그 뒤에도 청년등으로 센 인원인지({r['same']}), 공제받은 세액 한도"
               f"(노란 칸 「{k}/공제받은 세액」)")
        if r["case"] == "가2" and r["period"] == 2:
            msg += (". 제2호 가목 2)에는 계산식이 없고 감소 인원에 대해 공제받은 세액의 합계액이라고만 적혀 있어 감소 인원 × 1인당 "
                    "금액 × 공제받은 횟수로 계산했습니다")
        p.confirm.append(msg)
        carry = sum(int(c.get("carryforward") or 0) for c in prior.get("credits") or [] if str(c.get("code") or "") == r["code"])
        if carry and r["carry_cut"]:
            p.confirm.append(f"{head}: 전기 8호 부표3 에 {r['name']} 이월액 {carry:,}원이 있습니다. 공제받지 못하고 이월된 금액은 납부할 "
                             "금액에서 빼고(조특법 제29조의8 제3항 후단 괄호) 이월액도 그만큼 줄여야 합니다. 엔진은 빼지 않았으니 "
                             f"노란 칸 「{k}/이월 차감」 과 이월 줄 금액(「이월/{r['code']}/금액」)을 고치십시오")
        elif carry:
            p.confirm.append(f"{head}: 전기 8호 부표3 에 {r['name']} 이월액 {carry:,}원이 있습니다. 이월된 금액은 공제받은 세액이 "
                             f"아니니 노란 칸 「{k}/공제받은 세액」 한도와 이월 줄 금액(「이월/{r['code']}/금액」)을 확인하십시오")
    if add["total"]:
        p.confirm.append(f"추가 납부세액 합계 {add['total']:,}원은 8호(을) 5절 공제감면세액에 대한 법인세 추가납부(코드 773)와 3호 (133) "
                         "감면분 추가납부세액에 들어갑니다(법인세법 시행규칙 별지 제3호서식 작성방법 14 · 제8호서식(을) 작성방법 3). "
                         "8호(을) 그 줄의 별표 조문 목록에 제29조의7 · 제29조의8 이 없어 (185) 기타 줄에 적을지는 회계사가 확인합니다. "
                         "8호 부표6(추가납부세액계산서)은 엔진이 만들지 않고, 법인지방소득세 · 농어촌특별세에 미치는 영향은 계산하지 "
                         "않았습니다")


def _allocate(rows: list[dict], room: int, tax_room: int) -> int:
    """줄 차례로 room 안에서 공제한다. room 을 넘고 tax_room 안인 몫은 최저한세 미공제, 나머지는 그 밖의 미공제(8호 부표3 (122))."""
    cum = 0
    for r in rows:
        a = r["avail"]
        r["used"] = max(0, min(a, room - cum))
        r["cut_min"] = max(0, min(cum + a, tax_room) - max(cum, room))
        r["cut_other"] = a - r["used"] - r["cut_min"]
        cum += a
    return sum(r["used"] for r in rows)


def after_tax(p: Paper, b: Books, flow: dict) -> None:
    """3호 과세표준 · 산출세액이 나온 뒤 감면 · 공제 · 최저한세를 계산하고 3호 17 · 19 기본값을 flow 에 넣는다."""
    x = p.extra["calc"]
    T, B = int(flow["computed_tax"]), int(flow["tax_base"])
    M = min_tax(B, b.sme, b.rates)
    I = int(flow.get("income", B))
    sp = x["split"]
    # 그 밖의 사업이 결손이면 그 결손금은 감면 사업 소득에서 빠지므로(조특법 제143조 제3항) 감면 사업 소득은 각사업연도소득이다
    other = max(0, sp["other"])
    own = max(0, I - other)
    inc = reduced_income(I, B, other)
    rr = x["rate"]

    def target(income_):
        if x["apply"] == "O" and T > 0 and B > 0 and rr > 0:
            return rd(Fraction(T) * min(Fraction(1), Fraction(income_, B)) * frac(rr))
        return 0
    raw = target(inc)
    raw_all = target(reduced_income(I, B, 0))
    su = next(c["amount"] for c in x["current"] if c["code"] == "111")
    room_m = max(0, T - M)
    sme_in = min(raw, x["limit"], room_m)
    su_in = min(su, room_m - sme_in)
    rm_in = sme_in + su_in

    carry_years = rate(b.rates, "min_tax", "carry_years")
    rows = []
    for c in sorted([c for c in x["carry"] if c["amount"]], key=lambda c: (c["year"] or 0, c["key"])):
        expired = bool(c["year"]) and x["fy"] - c["year"] > carry_years
        rows.append({**c, "carried": True, "avail": 0 if expired else c["amount"], "expired": c["amount"] if expired else 0})
    for c in x["current"]:
        if c["kind"] == "공제":
            rows.append({**c, "year": x["fy"], "carried": False, "avail": c["amount"], "expired": 0})
    grp_min = [r for r in rows if r["class"] == "대상"]
    grp_ex = [r for r in rows if r["class"] != "대상"]
    room1 = max(0, T - M - rm_in)
    tax1 = max(0, T - rm_in)
    cm_in = _allocate(grp_min, room1, tax1)
    room2 = max(0, T - rm_in - cm_in)
    cx_in = _allocate(grp_ex, room2, room2)
    ordered = grp_min + grp_ex
    for r in ordered:
        r["carry_out"] = r["amount"] - r["used"] - r["expired"]

    credits_min, credits_ex = rm_in + cm_in, cx_in
    flow["credits_min"], flow["credits_ex"] = credits_min, credits_ex
    # 인원이 줄어 납부할 세액은 3호 (133) 감면분 추가납부세액(조서 3호 29 노란 칸)의 기본값이 된다
    flow["additional_tax"] = x["add"]["total"]
    carry_out = sum(r["carry_out"] for r in ordered)
    items = []
    if raw or sme_in:
        items.append({"code": "112", "name": CODES["112"][0], "kind": "감면", "class": "대상", "law": CODES["112"][3],
                      "target": raw, "after_min": min(raw, room_m), "used": sme_in, "rate": rr, "cut": raw - sme_in,
                      "income": inc, "limit": x["limit"]})
    if su or su_in:
        items.append({"code": "111", "name": CODES["111"][0], "kind": "감면", "class": "대상", "law": CODES["111"][3],
                      "target": su, "after_min": min(su, room_m - sme_in), "used": su_in, "rate": None, "cut": su - su_in,
                      "income": None, "limit": None})
    for r in ordered:
        items.append({"code": r["code"], "name": r["name"], "kind": "공제", "class": r["class"], "law": r["law"],
                      "year": r["year"], "carried": r["carried"], "amount": r["amount"], "avail": r["avail"],
                      "used": r["used"], "cut_min": r["cut_min"], "cut_other": r["cut_other"], "expired": r["expired"],
                      "carry_out": r["carry_out"], "key": r["key"]})
    p.extra["rows"] = ordered
    p.values.update({
        "과세표준": B, "산출세액": T, "최저한세": M, "각사업연도소득": I, "감면 사업 소득": own, "감면 대상 소득": inc,
        "세무조정 순액": I - _book_net(sp["book"]),
        "중소기업특별세액감면 대상세액": raw, "최저한세 한도 안 감면": room_m, "중소기업특별세액감면": sme_in,
        "창업중소기업 세액감면 적용": su_in, "감면 배제": raw + su - sme_in - su_in, "최저한세 적용대상 감면": rm_in,
        "최저한세 적용대상 공제": cm_in, "최저한세 적용제외 공제": cx_in,
        "최저한세 적용대상": credits_min, "최저한세 적용제외": credits_ex, "공제감면 합계": credits_min + credits_ex,
        "최저한세 미공제": sum(r["cut_min"] for r in ordered), "이월액 합계": carry_out,
        "items": items,
    })
    for r in ordered:
        p.values[f"공제세액/{r['key']}"] = r["used"]
        p.values[f"이월액/{r['key']}"] = r["carry_out"]

    if raw_all != raw and "감면 제외 소득" not in p.overridden and not sp["used"]:
        p.confirm.append(f"중소기업특별세액감면 대상세액은 감면 제외 소득 {x['exclude']:,}원을 빼고 {raw:,}원으로 계산했습니다(빼지 않으면 "
                         f"{raw_all:,}원). 감면은 감면 업종 사업장 소득에만 줍니다(조특법 제7조 제1항, 법인세법 제59조 제2항). 잡이익 · "
                         "외환차익 중 감면 사업과 관련 없는 것, 그 밖의 사업의 매출 · 개별 손금, 두 사업의 공통 손금은 계산에 반영하지 않았습니다. "
                         f"노란 칸 「{SPLIT}/…」 에 넣으면 안분해 계산하고 48호 소득구분계산서를 만듭니다(조특법 제143조, 법인세법 "
                         "시행규칙 제75조 제2항 · 제76조 제6항)")
    if sp["used"]:
        p.confirm.append(f"감면 사업 소득 {own:,}원 = 각사업연도소득 {I:,}원 - 그 밖의 사업 소득 {other:,}원(감면 제외 소득 "
                         f"{x['exclude']:,}원과 노란 칸 「{SPLIT}/…」 값, 공통 익금 · 공통 손금 안분 뒤). 대상세액은 {raw:,}원이고 "
                         f"구분하지 않으면 {raw_all:,}원입니다. 그 밖의 사업분과 공통분 금액은 회계사가 넣은 값입니다")
    _split_rows(p, x, flow, own, inc)
    op = b.totals.get("operating_income")
    if raw and op is not None and int(op) <= 0:
        p.confirm.append(f"영업이익이 {int(op):,}원인데 중소기업특별세액감면 대상세액 {raw:,}원을 계산했습니다. 과세표준이 영업외수익에서 "
                         "나왔으면 감면 업종 소득이 없을 수 있으니 소득구분계산서(48호)로 감면 소득을 확인하십시오")
    if T <= 0 and any(r["amount"] for r in ordered):
        p.notes.append(f"산출세액이 없어 세액공제 {sum(r['amount'] for r in ordered):,}원을 모두 다음 해로 넘깁니다(조특법 제144조 제1항)")
    _carry_gap(p, b, x, T, carry_out)
    if raw and sme_in < raw:
        p.notes.append(f"중소기업특별세액감면 {raw:,}원 중 {raw - sme_in:,}원은 최저한세 · 한도로 받지 못합니다(감면은 이월되지 않음)")
    if any(r["cut_min"] for r in ordered):
        p.notes.append("최저한세에 걸려 공제받지 못한 세액공제는 「최저한세 미공제」 로 다음 해에 넘깁니다(8호 부표3 (121))")
    if any(r["expired"] for r in ordered):
        p.confirm.append("이월 기간 10년이 지난 세액공제는 소멸로 두었습니다(8호 부표3 (124)). 연도를 확인하십시오")
    p.notes.append("3호 17(최저한세 적용대상) · 19(최저한세 적용제외) 란 기본값은 이 조서 값입니다. 3호 시트 노란 칸을 고치면 그 값이 이깁니다")
    # 전기에 공제감면이 있었으면 당기 0 이어도 확인할 것이 남는다
    p.settle(bool(credits_min or credits_ex or carry_out or raw or su or x["add"]["total"] or (b.prior or {}).get("credits")))


def _carry_gap(p: Paper, b: Books, x: dict, T: int, carry_out: int) -> None:
    """결손 등으로 산출세액이 없으면 당기 발생 세액공제는 전액 이월된다. 통합고용 · 연구 · 인력개발비 당기분은 사람 입력(상시근로자 수 ·
    연구개발비 명세)이 없으면 0 이라 이월액에서 빠진다. 입력 없이 금액을 만들지 않고 그 사실을 확인 줄로 남긴다(10-20)."""
    if T > 0:
        return
    names = " ".join(str(a.get("name") or "") for a in b.accounts(cls="비용"))
    miss = []
    if not x["emp"]["calc"]["used"] and EMP_KEY not in p.overridden and "급여" in names:
        miss.append(f"통합고용세액공제(상시근로자 수, 신고건.json 「{INFO_KEY}」)")
    accounts, prior_rnd = rnd_reference(b)
    if not x["rnd"]["calc"]["used"] and RND_KEY not in p.overridden and (accounts or prior_rnd):
        miss.append(f"연구 · 인력개발비 세액공제(연구개발비 명세, 신고건.json 「{RND_INFO}」)")
    if miss:
        p.confirm.append(f"산출세액이 없어 당기에 생기는 세액공제는 전액 다음 해로 넘어갑니다(조특법 제144조 제1항). 그런데 {' · '.join(miss)} "
                         f"당기분은 사람 입력이 없어 0원으로 두었습니다. 「이월액 합계」 {carry_out:,}원에 당기 발생분이 빠져 있을 수 있습니다. "
                         "입력하면 당기분이 8호 부표3 (125) 이월액에 들어갑니다")


def _book_net(book: dict) -> int:
    return book["매출액"] - book["매출원가"] - book["판관비"] + book["영업외수익"] - book["영업외비용"]


def _split_rows(p: Paper, x: dict, flow: dict, own: int, inc: int) -> None:
    """48호 소득구분계산서 줄(합계 · 감면분 · 기타분). 과목 금액은 손익계산서 금액이고, 과목별 세무조정 가감(작성방법 2)은
    「세무조정」 한 줄에 모았다(서식에 없는 보조 줄). 이월결손금 · 비과세소득 · 소득공제액은 소득금액에 비례해 나눈다
    (법인세법 시행령 제96조 제2호)."""
    sp, y, book = x["split"], x["split"]["y"], x["split"]["book"]
    I, B = int(flow.get("income", 0)), int(flow["tax_base"])
    k_tot = I - _book_net(book)
    # 영업외수익 개별분 기타 = 감면 제외 소득(순액) + 그 밖의 사업 영업외비용 개별분
    nr_o = sp["exclude"] + y["영업외비용 개별/기타"]
    rows = []

    def row(code, label, total, other, ratio=None):
        r = {"code": code, "label": label, "total": total, "other": other, "reduced": total - other}
        if ratio is not None:
            r["ratio_other"] = ratio
        rows.append(r)
        return r

    def ratio_of(part, whole):
        return round(max(0, min(part, whole)) / whole, 6) if whole > 0 else 0.0
    r_rev = ratio_of(sp["rev_o"], sp["rev_t"])
    r_cost = ratio_of(sp["cost_part"], sp["cost_whole"])
    row("01", "(1) 매출액", book["매출액"], y["매출액/기타"])
    row("02", "(2) 매출원가", book["매출원가"], y["매출원가/기타"])
    row("04", "(4) 판매비와관리비 개별분", book["판관비"] - y["판관비 공통"], y["판관비 개별/기타"])
    row("05", "(4) 판매비와관리비 공통분", y["판관비 공통"], sp["a_g"], r_cost)
    row("08", "(6) 영업외수익 개별분", book["영업외수익"] - y["영업외수익 공통"], nr_o)
    row("09", "(6) 영업외수익 공통분", y["영업외수익 공통"], sp["a_nr"], r_rev)
    row("11", "(7) 영업외비용 개별분", book["영업외비용"] - y["영업외비용 공통"], y["영업외비용 개별/기타"])
    row("12", "(7) 영업외비용 공통분", y["영업외비용 공통"], sp["a_ne"], r_cost)
    row("세무조정", "세무조정 순액(과목별 가감 전, 서식에 없는 보조 줄)", k_tot, y["세무조정/기타"])
    row("21", "(8) 각 사업연도 소득", I, sp["other"])
    # 공제액 안분: 감면분 몫의 합이 감면 사업 소득 - 감면 대상 소득이 되게 마지막 줄에서 맞춘다
    ded = [("22", "(9) 이월결손금", int(flow.get("loss_used", 0))), ("23", "(10) 비과세소득", int(flow.get("nontax", 0))),
           ("24", "(11) 소득공제액", int(flow.get("deduction", 0)))]
    left = own - inc
    live = [d for d in ded if d[2]]
    for code, label, amt in ded:
        if I > 0 and amt and live:
            mine = left if (code, label, amt) == live[-1] else min(left, rd(Fraction(amt * own, I)))
            mine = max(0, min(mine, amt))
            left -= mine
        else:
            mine = 0
        row(code, label, amt, amt - mine)
    row("25", "(12) 과세표준", B, B - inc)
    p.values[SPLIT] = {"make": sp["make"] == "O" or sp["used"], "used": sp["used"], "basis": y["기준"], "rows": rows,
                       "ratio_income": r_rev, "ratio_cost": r_cost,
                       "loss_netted": sp["other"] < 0}


# 엑셀 ----------------------------------------------------------------------------------------------

def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    x = p.extra["calc"]
    R = bk.ref
    row = s.section(5, "1. 중소기업특별세액감면 판정(조세특례제한법 제7조)")
    s.put(row, 1, "중소기업 여부(기준 시트)")
    s.put(row, 7, f"={R['중소기업 여부']}", kind="link")
    p.extra["sme_at"] = f"$G${row}"
    r = Rows(bk, s, p, row + 1)
    r.put("소기업 여부", "소기업 여부(여 · 부, 전기 51호)", p.inputs["소기업 여부"], kind="input", input_kind="text",
          note="매출액이 중소기업기본법 시행령 별표 3 기준 이내(조특령 제6조 제4항)")
    r.put("수도권 여부", "본점 수도권 여부(여 · 부, 전기 1호 소재지)", p.inputs["수도권 여부"], kind="input", input_kind="text",
          note="본점이 수도권이면 모든 사업장을 수도권으로 봅니다(제7조 제1항 단서)")
    r.put("감면 업종", "감면 업종(도매업등 · 감면업종 · 출판업 · 비감면)", p.inputs["감면 업종"], kind="input", input_kind="text",
          note=x["kind_why"])
    r.put("적용 여부", "감면 신청(O · X)", p.inputs["적용 여부"], kind="input", input_kind="pick")
    g = r.g
    sme, sm, rg, kd = p.extra["sme_at"], g("소기업 여부"), g("수도권 여부"), g("감면 업종")
    rate_f = (f'=IF({sme}<>"여",0,IF({kd}="도매업등",IF({sm}="여",{R["감면율 소기업 · 도매업등"]},'
              f'IF({rg}="여",0,{R["감면율 중기업 · 수도권 외 · 도매업등"]})),'
              f'IF(OR({kd}="감면업종",{kd}="출판업"),IF({sm}="여",IF({rg}="여",{R["감면율 소기업 · 수도권 · 그 밖의 감면 업종"]},'
              f'{R["감면율 소기업 · 수도권 외 · 그 밖의 감면 업종"]}),IF({rg}="여",IF({kd}="출판업",'
              f'{R["감면율 중기업 · 수도권 · 일반 서적 출판업"]},0),{R["감면율 중기업 · 수도권 외 · 그 밖의 감면 업종"]})),0)))')
    r.put("감면율", "감면율(제7조 제1항 제2호)", rate_f, fmt="0%")
    parts = x.get("exclude_parts") or []
    r.put("감면 제외 소득", "각사업연도소득 중 감면 대상이 아닌 소득(이자수익 등, 48호 소득구분)", p.inputs["감면 제외 소득"],
          kind="input", input_kind="int",
          note=("기본값 " + " · ".join(f"{n} {v:,}" for n, v in parts)) if parts else "영업외 이자 · 배당 · 임대료 · 처분손익 없음")
    r.put("상시근로자 수/직전", "직전 과세연도 상시근로자 수", p.inputs["상시근로자 수/직전"], kind="input", input_kind="ratio",
          fmt="0.00")
    r.put("상시근로자 수/당기", "해당 과세연도 상시근로자 수", p.inputs["상시근로자 수/당기"], kind="input", input_kind="ratio",
          fmt="0.00", note="둘 다 0 이면 한도 1억원")
    r.put("감면 한도", "감면 한도(1억원 - 감소 인원 × 5백만원)",
          f"=MAX(0,{R['중소기업특별세액감면 한도']}-ROUNDDOWN({R['한도 감소 상시근로자 1명당']}"
          f"*MAX(0,{g('상시근로자 수/직전')}-{g('상시근로자 수/당기')}),0))")

    row = _write_split(bk, s, p, r.row + 1, g("감면 제외 소득"))
    row = s.section(row + 1, "2. 당기분 공제 · 감면(자료 필요, 노란 칸 기본 0)")
    for col, label in ((1, "구분"), (3, "8호(갑)"), (5, "최저한세"), (7, "금액"), (8, "필요한 자료")):
        X.header(s.ws, row, [label], col=col)
    row += 1
    for c in x["current"]:
        s.put(row, 3, c["code"])
        s.put(row, 5, f"적용{c['class']}")
        row = calc_row(bk, s, row, p, c["key"], c["label"], c["amount"], kind="input", input_kind="int", note=c["need"])
    row = _write_employment(bk, s, p, row + 1)
    row = _write_rnd(bk, s, p, row + 1)
    row = _write_additional(bk, s, p, row + 1)

    row = s.section(row + 1, "3. 이월 세액공제(전기 8호 부표3 (125), 노란 칸)")
    for col, label in ((1, "구분"), (3, "8호(갑)"), (5, "최저한세"), (6, "발생 연도"), (7, "이월액")):
        X.header(s.ws, row, [label], col=col)
    row += 1
    p.extra["carry_cells"] = {}
    for c in x["carry"]:
        s.put(row, 1, c["name"] or f"이월 수동 {c['manual']}(코드를 넣으면 이름이 붙습니다)")
        if c["manual"]:
            s.inp(row, 3, c["code"] or None, pid=p.id, key=f"{c['key']}/코드", default=p.defaults.get(f"{c['key']}/코드") or None)
        else:
            s.put(row, 3, c["code"])
        s.put(row, 5, f"적용{c['class']}")
        s.inp(row, 6, c["year"] or None, pid=p.id, key=f"{c['key']}/연도", default=p.defaults.get(f"{c['key']}/연도") or None,
              kind="int", fmt="0")
        s.inp(row, 7, c["amount"], pid=p.id, key=f"{c['key']}/금액", default=p.defaults.get(f"{c['key']}/금액", 0),
              kind="int", money=True)
        bk.reg(p.id, f"{c['key']}/금액", s.addr(row, 7))
        p.extra["carry_cells"][c["key"]] = (f"$F${row}", f"$G${row}")
        row += 1
    p.extra["after_row"] = row + 1
    p.extra["sheet"] = s


def _write_split(bk: Book, s, p: Paper, row: int, excl: str) -> int:
    """1-1. 소득 구분계산. 노란 칸(그 밖의 사업분 · 공통분)과 공통분 안분 수식. 다음 행을 돌려준다."""
    sp = p.extra["calc"]["split"]
    row = s.section(row, "1-1. 소득 구분계산(48호 소득구분계산서, 노란 칸을 비우면 감면 제외 소득만 뺍니다)")
    r = Rows(bk, s, p, row)
    g = r.g
    k = lambda name: f"{SPLIT}/{name}"   # noqa: E731
    for name in BOOK_PARTS:
        r.put(k(name), f"손익계산서 {name}(합계)", sp["book"][name], note="장부.json 손익계산서 합계")
    for key, kind, label, where in SPLIT_INPUTS:
        r.put(k(key), label, p.inputs[k(key)], kind="input", input_kind=kind, note=f"48호 {where}")
    r.put(k("공통 손금 안분 기준"), "공통 손금 안분 기준(수입금액 · 개별손금)", p.inputs[k("공통 손금 안분 기준")], kind="input",
          input_kind="text", note="두 사업의 업종(한국표준산업분류 소분류)이 같으면 수입금액, 다르면 개별손금(법인세법 시행규칙 제76조 제6항)")
    r.put(k("48호 작성"), "48호 소득구분계산서 작성(O · X)", p.inputs[k("48호 작성")], kind="input", input_kind="pick",
          note="위 노란 칸에 값이 있으면 X 여도 만듭니다")
    r.put(k("안분 수입금액 기타"), "안분 기준 수입금액: 그 밖의 사업", f"={g(k('매출액/기타'))}+{g(k('안분 기준 가산/기타'))}")
    r.put(k("안분 수입금액 합계"), "안분 기준 수입금액: 합계", f"={g(k('매출액'))}+{g(k('안분 기준 가산/기타'))}")
    r.put(k("개별 손금 기타"), "안분 기준 개별 손금: 그 밖의 사업(매출원가 + 판관비 개별분 + 영업외비용 개별분)",
          f"={g(k('매출원가/기타'))}+{g(k('판관비 개별/기타'))}+{g(k('영업외비용 개별/기타'))}")
    r.put(k("개별 손금 합계"), "안분 기준 개별 손금: 합계(공통분을 뺀 손금)",
          f"={g(k('매출원가'))}+{g(k('판관비'))}-{g(k('판관비 공통'))}+{g(k('영업외비용'))}-{g(k('영업외비용 공통'))}")
    rev_o, rev_t = g(k("안분 수입금액 기타")), g(k("안분 수입금액 합계"))
    by_exp = f'{g(k("공통 손금 안분 기준"))}="개별손금"'
    part = f"IF({by_exp},{g(k('개별 손금 기타'))},{rev_o})"
    whole = f"IF({by_exp},{g(k('개별 손금 합계'))},{rev_t})"

    def share(common, a, w):
        return f"=IF({w}<=0,0,ROUNDDOWN({common}*MAX(0,MIN({a},{w}))/{w},0))"
    r.put(k("공통 영업외수익 기타 안분"), "공통 익금 중 그 밖의 사업 몫(수입금액 비례)", share(g(k("영업외수익 공통")), rev_o, rev_t),
          note="법인세법 시행규칙 제76조 제6항 제1호")
    r.put(k("공통 판관비 기타 안분"), "판매비와관리비 공통분 중 그 밖의 사업 몫", share(g(k("판관비 공통")), part, whole),
          note="법인세법 시행규칙 제76조 제6항 제2호 · 제3호")
    r.put(k("공통 영업외비용 기타 안분"), "영업외비용 공통분 중 그 밖의 사업 몫", share(g(k("영업외비용 공통")), part, whole))
    r.put("그 밖의 사업 소득", "그 밖의 사업 소득(감면 제외 소득 + 매출액 - 매출원가 - 판관비 개별분 + 세무조정 + 공통 익금 몫 - 공통 손금 몫)",
          f"={excl}+{g(k('매출액/기타'))}-{g(k('매출원가/기타'))}-{g(k('판관비 개별/기타'))}+{g(k('세무조정/기타'))}"
          f"+{g(k('공통 영업외수익 기타 안분'))}-{g(k('공통 판관비 기타 안분'))}-{g(k('공통 영업외비용 기타 안분'))}", kind="total")
    return r.row


def _write_employment(bk: Book, s, p: Paper, row: int) -> int:
    """2-1. 통합고용세액공제 계산. 인원 · 전기 1차년도 공제액 노란 칸과 1 · 2 · 3차 연도 수식. 다음 행을 돌려준다."""
    e = p.extra["calc"]["emp"]
    c, R = e["calc"], bk.ref
    row = s.section(row, "2-1. 통합고용세액공제 계산(조세특례제한법 제29조의8, 인원은 사람이 넣습니다)")
    r = Rows(bk, s, p, row)
    g = r.g
    k = lambda name: f"{EMP}/{name}"   # noqa: E731
    for per in PERIODS:
        src = e["given"].get(per)
        for part in ("청년등", "청년등 외"):
            r.put(k(f"{per}/{part}"), f"{per} 과세연도 {part} 상시근로자 수", p.inputs[k(f"{per}/{part}")], kind="input",
                  input_kind="ratio", fmt="0.00", note=f"기본값 {src}" if src else "소수 둘째 자리까지(조특 10호의9)")
        r.put(k(f"{per}/전체"), f"{per} 과세연도 상시근로자 수(청년등 + 청년등 외)",
              f"=ROUND(ROUNDDOWN({g(k(f'{per}/청년등'))},2)+ROUNDDOWN({g(k(f'{per}/청년등 외'))},2),2)", fmt="0.00")
    for per in PERIODS[1:]:
        for part in ("청년등", "청년등 외"):
            key = k(f"1차년도 공제액/{per}/{part}")
            r.put(key, f"{per} 과세연도 증가분의 1차 연도 공제액({part})", p.inputs[key], kind="input", input_kind="int",
                  note="그해 신고서 조특 10호의9 의 「1차년도 세액공제액」 란")
    r.put(k("기업 구분"), "기업 구분(중소기업 · 중견기업 · 일반기업)", p.inputs[k("기업 구분")], kind="input", input_kind="text")
    r.put(k("증가 지역 수도권 여부"), "인원이 늘어난 지역이 수도권인지(여 · 부)", p.inputs[k("증가 지역 수도권 여부")], kind="input",
          input_kind="text", note="기본값은 본점 수도권 여부. 수도권 밖 사업장에서 늘었으면 부(제29조의8 제1항)")
    y = {per: f"ROUNDDOWN({g(k(f'{per}/청년등'))},2)" for per in PERIODS}
    o = {per: f"ROUNDDOWN({g(k(f'{per}/청년등 외'))},2)" for per in PERIODS}
    t = {per: g(k(f"{per}/전체")) for per in PERIODS}
    r.put(k("전체 증가"), "전체 상시근로자 증가 인원(해당 - 직전)", f"=ROUND({t['해당']}-{t['직전']},2)", fmt="0.00")
    r.put(k("청년등 증가"), "청년등 상시근로자 증가 인원", f"=ROUND({y['해당']}-{y['직전']},2)", fmt="0.00")
    r.put(k("청년등 외 증가"), "청년등 외 상시근로자 증가 인원", f"=ROUND({o['해당']}-{o['직전']},2)", fmt="0.00")
    d_t = g(k("전체 증가"))
    guard = f"AND({t['해당']}>0,{d_t}>0" + ("" if e["prev_known"] else f",{t['직전']}>0") + ")"
    for key, label, d in ((k("청년등 공제 인원"), "청년등 공제 인원(전체 증가 인원 한도)", g(k("청년등 증가"))),
                          (k("청년등 외 공제 인원"), "청년등 외 공제 인원(전체 증가 인원 한도)", g(k("청년등 외 증가")))):
        r.put(key, label, f"=IF({guard},MAX(0,MIN({d},{d_t})),0)" if c["in_time"] else 0, fmt="0.00",
              note="" if c["in_time"] else "1인당 금액은 2025년 12월 31일이 속하는 과세연도까지")
    size, cap = g(k("기업 구분")), g(k("증가 지역 수도권 여부"))
    for part in ("청년등", "청년등 외"):
        r.put(k(f"{part} 1인당"), f"{part} 1인당 공제금액",
              f'=IF({size}="중소기업",IF({cap}="부",{R[f"통합고용 {part} 중소기업 수도권 밖"]},{R[f"통합고용 {part} 중소기업 수도권"]}),'
              f'IF({size}="중견기업",{R[f"통합고용 {part} 중견기업"]},{R[f"통합고용 {part} 일반기업"]}))')
    r.put(k("1차 청년등"), "1차 연도 청년등 공제액", f"=ROUND({g(k('청년등 공제 인원'))}*{g(k('청년등 1인당'))},0)")
    r.put(k("1차 청년등 외"), "1차 연도 청년등 외 공제액", f"=ROUND({g(k('청년등 외 공제 인원'))}*{g(k('청년등 외 1인당'))},0)")
    r.put(k("1차"), "1차 연도 공제액(당기 증가분, 조특 10호의9 ⑳)", f"={g(k('1차 청년등'))}+{g(k('1차 청년등 외'))}")
    f1 = [g(k(f"1차년도 공제액/직전/{part}")) for part in ("청년등", "청년등 외")]
    f2 = [g(k(f"1차년도 공제액/직전전/{part}")) for part in ("청년등", "청년등 외")]
    r.put(k("2차"), "2차 연도 공제액(직전 과세연도 증가분, 인원이 줄지 않았을 때)",
          f"=IF(OR({t['해당']}<=0,{t['직전']}<=0,{t['해당']}<{t['직전']}),0,IF({y['해당']}<{y['직전']},0,{f1[0]})+{f1[1]})",
          note="전체가 줄면 0, 청년등만 줄면 청년등 몫 0(제29조의8 제3항)")
    r.put(k("3차"), "3차 연도 공제액(직전전 과세연도 증가분, 중소 · 중견기업)",
          f'=IF(OR(AND({size}<>"중소기업",{size}<>"중견기업"),{t["해당"]}<=0,{t["직전전"]}<=0,{t["직전"]}<{t["직전전"]},'
          f'{t["해당"]}<{t["직전전"]}),0,IF(OR({y["직전"]}<{y["직전전"]},{y["해당"]}<{y["직전전"]}),0,{f2[0]})+{f2[1]})')
    r.put(k("계산액"), "통합고용세액공제 계산액(1차 + 2차 + 3차, 「당기분/통합고용세액공제」 기본값)",
          f"={g(k('1차'))}+{g(k('2차'))}+{g(k('3차'))}", kind="total")
    # 추가공제(제4항 · 제5항). 기간 요건은 과세연도로 정해져 있어 맞지 않으면 0 을 적는다
    x = e["extra"]
    for kind, name, code, law in EXTRA:
        r.put(k(f"{name} 인원"), f"{name} 인원(명)", p.inputs[k(f"{name} 인원")], kind="input", input_kind="int", fmt="0",
              note=f"조특법 제29조의8 {law}. 넣으면 8호(갑) {code} 줄에 인원 × 1인당 금액")
    r.put(k("추가공제 1인당"), "추가공제 1인당 공제금액(중소기업 1,300만원, 중견기업 900만원)",
          f'=IF({size}="중소기업",{R["통합고용 추가공제 중소기업"]},IF({size}="중견기업",{R["통합고용 추가공제 중견기업"]},0))')
    keep = f"AND({t['해당']}>0,{t['해당']}>={t['직전']}" + ("" if e["prev_known"] else f",{t['직전']}>0") + ")"
    for kind, name, _code, law in EXTRA:
        blocked = x[f"{kind}_why"] in ("기간 아님", "과세연도 모름")
        r.put(k(f"추가공제/{name}"), f"{name} 추가공제(인원 × 1인당 금액, 상시근로자 수가 직전보다 줄지 않았을 때)",
              0 if blocked else f"=IF({keep},MAX(0,{g(k(f'{name} 인원'))})*{g(k('추가공제 1인당'))},0)",
              note="이 과세연도는 대상 기간이 아닙니다" if blocked else f"「당기분/{EXTRA_LABEL[kind]}」 기본값(조특법 제29조의8 {law})")
    r.put(k("추가공제 계"), "추가공제 계(조특 10호의9 ㊱ 은 육아휴직 복귀만)",
          "=" + "+".join(g(k(f"추가공제/{name}")) for _kd, name, _c, _l in EXTRA))
    return r.row


def _write_rnd(bk: Book, s, p: Paper, row: int) -> int:
    """2-2. 일반 연구 · 인력개발비 세액공제 계산. 발생액 노란 칸과 당기분 방식 · 증가분 방식 수식. 다음 행을 돌려준다."""
    x = p.extra["calc"]["rnd"]
    R = bk.ref
    row = s.section(row, "2-2. 일반 연구 · 인력개발비 세액공제 계산(조세특례제한법 제10조 제1항 제3호, 대상 금액은 사람이 넣습니다)")
    k = lambda name: f"{RND}/{name}"   # noqa: E731
    # 발생명세 줄(조특 3호(1) ⑥ ~ ⑪). 줄마다 계정과목 · 구분별 인원(건수) · 금액 노란 칸, L 열이 줄의 계
    s.put(row, 1, "발생명세(조특 3호(1) ⑥ ~ ⑪, 계정과목별로 넣으면 합계가 해당 과세연도 발생액 기본값이 됩니다)")
    row += 1
    heads = ["계정과목"]
    for part, unit, code in RND_PARTS:
        heads += [f"{part} {unit}", f"{'⑥⑦⑧⑨⑩'[int(code) - 6]} {part}"]
    X.header(s.ws, row, heads + ["⑪ 계"])
    row += 1
    first = row
    for d in x["detail"]:
        base = k(f"{RND_DETAIL} {d['no']}")
        s.inp(row, 1, d["계정과목"] or None, pid=p.id, key=f"{base}/계정과목", default=p.defaults.get(f"{base}/계정과목") or None)
        col, money = 2, []
        for part, unit, _code in RND_PARTS:
            s.inp(row, col + 1, p.inputs[f"{base}/{part}"], pid=p.id, key=f"{base}/{part}", default=p.defaults.get(f"{base}/{part}", 0),
                  kind="int", money=True)
            s.inp(row, col, d[f"{part} {unit}"], pid=p.id, key=f"{base}/{part} {unit}", default=p.defaults.get(f"{base}/{part} {unit}", 0),
                  kind="int", fmt="0")
            money.append(f"MAX(0,{get_column_letter(col + 1)}{row})")
            col += 2
        s.put(row, col, "=" + "+".join(money), money=True)
        row += 1
    r = Rows(bk, s, p, row)
    g = r.g
    r.put(k(f"{RND_DETAIL} 합계"), "발생명세 합계(조특 3호(1) ⑪ 총계)", f"=SUM(L{first}:L{row - 1})",
          note="「해당」 을 직접 넣지 않으면 이 금액이 기본값")
    r.put(k("해당"), "해당 과세연도 일반 연구 · 인력개발비 발생액(조특 3호(1) ⑫)", p.inputs[k("해당")], kind="input", input_kind="int",
          note="조특령 별표 6 의 비용만. 계정 금액을 그대로 넣지 않습니다")
    for i, y in enumerate(RND_YEARS):
        r.put(k(y), f"{y} 발생액(조특 3호(1) {'⑭⑮⑯⑰'[i]})", p.inputs[k(y)], kind="input", input_kind="int",
              note=f"기본값 {x['given'][y]}" if y in x["given"] else ("발생하지 않은 해는 0" if i == 0 else ""))
    r.put(k("기업 구분"), "기업 구분(중소기업 · 중견기업 · 일반기업)", p.inputs[k("기업 구분")], kind="input", input_kind="text",
          note="중견기업 범위는 조특령 제9조 제4항")
    r.put(k("방식"), "방식(큰 쪽 · 당기분 · 증가분)", p.inputs[k("방식")], kind="input", input_kind="text",
          note="가목과 나목 중 고른 하나(제10조 제1항 제3호)")
    r.put(k("수입금액"), "수입금액(기업회계기준 매출액, 일반기업 공제율에만 씁니다)", p.inputs[k("수입금액")], kind="input",
          input_kind="int", note="기본값 손익계산서 매출액")
    cur, prev = g(k("해당")), [g(k(y)) for y in RND_YEARS]
    size, method, months = g(k("기업 구분")), g(k("방식")), x["months"]
    r.put(k("직전 4년 합계"), "직전 4년 발생액 합계(조특 3호(1) ⑬)", "=" + "+".join(f"MAX(0,{c})" for c in prev))
    r.put(k("발생 연도 수"), "직전 4년 중 발생한 과세연도 수", "=" + "+".join(f"IF({c}>0,1,0)" for c in prev), fmt="0")
    total4, years = g(k("직전 4년 합계")), g(k("발생 연도 수"))
    r.put(k("연평균"), f"직전 4년 연평균 발생액(합계 / 발생한 과세연도 수 × {months}개월 / 12)",
          f"=IF({years}=0,0,ROUNDDOWN({total4}*{months}/(MAX(1,{years})*12),0))", note="조특령 제9조 제9항 · 제11항")
    r.put(k("증가발생액"), "증가발생액(해당 - 직전 1년, 조특 3호(1) ㉑)", f"=MAX(0,MAX(0,{cur})-MAX(0,{prev[0]}))")
    r.put(k("증가분 요건"), "증가분 방식 요건(직전 4년 발생액이 있고 직전 1년이 연평균 이상이면 여)",
          f'=IF(AND({cur}>0,{years}>0,MAX(0,{prev[0]})*{years}*12>={total4}*{months}),"여","부")',
          note="제10조 제1항 제3호 단서")
    ok = g(k("증가분 요건"))
    r.put(k("당기분 공제율"), "당기분 방식 공제율(나목)",
          f'=IF({size}="중소기업",{R["연구 · 인력개발비 당기분 공제율 중소기업"]},IF({size}="중견기업",'
          f'{R["연구 · 인력개발비 당기분 공제율 중견기업"]},IF({g(k("수입금액"))}>0,MIN({R["연구 · 인력개발비 당기분 일반기업 한도"]},'
          f'MAX(0,{cur})/MAX(1,{g(k("수입금액"))})*{R["연구 · 인력개발비 당기분 일반기업 비율 배수"]}),0)))', fmt="0.00%")
    r.put(k("당기분 금액"), "당기분 방식 금액(해당 발생액 × 공제율)", f"=ROUNDDOWN(MAX(0,{cur})*{g(k('당기분 공제율'))},0)")
    r.put(k("증가분 공제율"), "증가분 방식 공제율(가목)",
          f'=IF({size}="중소기업",{R["연구 · 인력개발비 증가분 공제율 중소기업"]},IF({size}="중견기업",'
          f'{R["연구 · 인력개발비 증가분 공제율 중견기업"]},{R["연구 · 인력개발비 증가분 공제율 일반기업"]}))', fmt="0%")
    r.put(k("증가분 금액"), "증가분 방식 금액(증가발생액 × 공제율, 요건을 채울 때만)",
          f'=IF({ok}="여",ROUNDDOWN({g(k("증가발생액"))}*{g(k("증가분 공제율"))},0),0)')
    a_cur, a_inc = g(k("당기분 금액")), g(k("증가분 금액"))
    r.put(k("계산액"), "연구 · 인력개발비 세액공제 계산액(「당기분/연구 · 인력개발비 세액공제」 기본값, 조특 3호(1) ㊶)",
          f'=IF({method}="당기분",{a_cur},IF({method}="증가분",IF({ok}="여",{a_inc},{a_cur}),MAX({a_cur},{a_inc})))', kind="total")
    return r.row


def _write_additional(bk: Book, s, p: Paper, row: int) -> int:
    """2-3. 인원이 줄었을 때의 추가 납부세액. 묶음(당기가 2차 · 3차 연도인 공제)마다 노란 칸과 시행령 식. 다음 행을 돌려준다."""
    add = p.extra["calc"]["add"]
    mine = bk.cells[p.id]
    L = lambda key: local(mine[key])   # noqa: E731
    row = s.section(row, "2-3. 추가 납부세액(조특법 제29조의8 제3항 · 제29조의7 제2항, 최초 공제 과세연도보다 인원이 줄었을 때)")
    r = Rows(bk, s, p, row)
    g = r.g
    pays = []
    for x in add["rows"]:
        k = lambda name, x=x: f"{x['key']}/{name}"   # noqa: E731
        title = f"{x['name']} {x['tag']} 연도" + (f"({x['year']} 과세연도 증가분)" if x["year"] else "")
        r.put(None, f"[{title}] 최초 공제 과세연도 상시근로자 수(청년등 · 청년등 외)", f"{float(x['first'][0]):.2f} · {float(x['first'][1]):.2f}")
        r.put(None, f"[{title}] 해당 과세연도 상시근로자 수(청년등 · 청년등 외)", f"{float(x['cur'][0]):.2f} · {float(x['cur'][1]):.2f}")
        if x["scheme"] == EMP:
            per = "직전" if x["period"] == 1 else "직전전"
            fy_, ft = f"ROUNDDOWN({L(f'{EMP}/{per}/청년등')},2)", L(f"{EMP}/{per}/전체")
            cy, ct = f"ROUNDDOWN({L(f'{EMP}/해당/청년등')},2)", L(f"{EMP}/해당/전체")
            d_t, d_y = f"=ROUND({ft}-{ct},2)", f"=ROUND({fy_}-{cy},2)"
            d_o = f"=ROUND(({ft}-{fy_})-({ct}-{cy}),2)"
            a1, a2 = f"={L(f'{EMP}/청년등 1인당')}", f"={L(f'{EMP}/청년등 외 1인당')}"
        else:
            # 고용증대: 최초 공제 연도 인원은 전기 신고서 값, 당기 청년등 인원은 신고건.json 값이라 숫자로 적는다
            d_t, d_y, d_o = float(x["d_t"]), float(x["d_y"]), float(x["d_o"])
            a1, a2 = x["a1"], x["a2"]
        r.put(k("전체 감소"), "전체 상시근로자 감소 인원(최초 공제 과세연도 - 해당 과세연도)", d_t, fmt="0.00")
        r.put(k("청년등 감소"), "청년등 상시근로자 감소 인원", d_y, fmt="0.00")
        r.put(k("청년등 외 감소"), "청년등 외 상시근로자 감소 인원", d_o, fmt="0.00")
        r.put(k("1인당 청년등"), "1인당 금액(제1항 제1호, 청년등)", a1)
        r.put(k("1인당 청년등 외"), "1인당 금액(제1항 제2호, 청년등 외)", a2, note="지금 넣은 기업 구분 · 증가 지역 기준")
        r.put(k("최초 청년등 증가 인원"), "최초 공제 과세연도의 청년등 증가 인원 수", p.inputs[k("최초 청년등 증가 인원")], kind="input",
              input_kind="ratio", fmt="0.00",
              note="전기 공제세액계산서 1차년도 표" if x["inc0"] is not None else "그해 공제세액계산서 1차년도 표의 청년등 증가 인원을 넣으십시오")
        n = "1"
        if x["period"] == 2:
            r.put(k("공제받은 횟수"), "직전 2년 이내 과세연도에 공제받은 횟수", p.inputs[k("공제받은 횟수")], kind="input",
                  input_kind="int", fmt="0")
            r.put(k("제1호 금액"), "제1호(1년 이내)로 계산한 금액(뺌)", p.inputs[k("제1호 금액")], kind="input", input_kind="int")
            n = f"MAX(0,{g(k('공제받은 횟수'))})"
        r.put(k("공제받은 세액"), f"직전 {x['period']}년 이내 과세연도에 공제받은 세액(한도)", p.inputs[k("공제받은 세액")], kind="input",
              input_kind="int", note="이월된 금액은 공제받은 세액이 아닙니다")
        if x["carry_cut"]:
            r.put(k("이월 차감"), "공제받지 못하고 이월된 금액(뺌)", p.inputs[k("이월 차감")], kind="input", input_kind="int",
                  note="조특법 제29조의8 제3항 후단 괄호. 이월 줄 금액도 그만큼 줄입니다")
        T, Y, O = g(k("전체 감소")), g(k("청년등 감소")), g(k("청년등 외 감소"))
        A1, A2, INC = g(k("1인당 청년등")), g(k("1인당 청년등 외")), f"ROUNDDOWN(MAX(0,{g(k('최초 청년등 증가 인원'))}),2)"
        formula = (f"=ROUNDDOWN(IF({T}>0,IF({Y}>={T},(MIN({Y},{INC})-{T})*({A1}-{A2})+{T}*{A1},"
                   f"MIN(MAX({Y},0),{T})*{A1}+MIN(MAX({O},0),{T})*{A2}),IF({Y}>0,MIN({Y},{INC})*({A1}-{A2}),0))*{n},0)")
        where = f"제{x['period']}호 {ADD_CASE[x['case']]}" if x["case"] else "감소 없음"
        r.put(k("산식 금액"), f"시행령 식의 금액({where})", formula if x["ok"] else 0,
              note="" if x["ok"] else "최초 공제 과세연도의 청년등 증가 인원이 없어 계산하지 않았습니다")
        paid = g(k("제1호 금액")) if x["period"] == 2 else "0"
        cut = g(k("이월 차감")) if x["carry_cut"] else "0"
        r.put(k("납부세액"), f"[{title}] 추가 납부세액(식의 금액 - 제1호 금액, 한도 안, 이월 차감 뒤)",
              f"=MAX(0,MIN(MAX(0,{g(k('산식 금액'))}-{paid}),{g(k('공제받은 세액'))})-{cut})" if x["ok"] else 0, kind="total")
        pays.append(g(k("납부세액")))
    if not add["rows"]:
        s.put(r.row, 1, "해당 줄 없음(당기 인원과 최초 공제 과세연도 인원 · 공제액이 있을 때 계산합니다)")
        r.row += 1
    r.put(ADD_KEY, "추가 납부세액 합계(조서 3호 29 란 기본값, 3호 (133) 감면분 추가납부세액)", "=" + ("+".join(pays) or "0"),
          kind="total", note="조특령 제26조의8 제4항 · 제26조의7 제5항. 회계사 확인 필요")
    return r.row


def write_after(bk: Book, p: Paper) -> None:
    """감면 · 공제 계산은 3호 시트(과세표준 · 산출세액)가 생긴 뒤에 건다."""
    s = p.extra.pop("sheet")
    R, cells = bk.ref, bk.cells
    mine = cells[p.id]
    L = lambda key: local(mine[key])   # noqa: E731
    row = s.section(p.extra.pop("after_row"), "4. 감면 · 공제 계산(3호 · 최저한세)")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("과세표준", "과세표준(3호 10)", f"={cells['tax_3']['10']}", kind="link")
    r.put("산출세액", "산출세액(3호 12)", f"={cells['tax_3']['12']}", kind="link")
    B, T = g("과세표준"), g("산출세액")
    sme = p.extra["sme_at"]
    Bp = f"MAX(0,{B})"
    general = (f"IF({Bp}<={R['최저한세 구간1 상한']},{Bp}*{R['최저한세 구간1']},IF({Bp}<={R['최저한세 구간2 상한']},"
               f"{R['최저한세 구간1 상한']}*{R['최저한세 구간1']}+({Bp}-{R['최저한세 구간1 상한']})*{R['최저한세 구간2']},"
               f"{R['최저한세 구간1 상한']}*{R['최저한세 구간1']}+({R['최저한세 구간2 상한']}-{R['최저한세 구간1 상한']})"
               f"*{R['최저한세 구간2']}+({Bp}-{R['최저한세 구간2 상한']})*{R['최저한세 구간3']}))")
    r.put("최저한세", "최저한세(과세표준 × 최저한세율, 4호 (122) ③)",
          f'=ROUNDDOWN(IF({sme}="여",{Bp}*{R["최저한세율(중소기업)"]},{general}),0)')
    M = g("최저한세")
    r.put("각사업연도소득", "각사업연도소득(3호 06)", f"={cells['tax_3']['06']}", kind="link")
    I = g("각사업연도소득")
    r.put("세무조정 순액", "세무조정 순액(각사업연도소득 - 손익계산서 다섯 과목 순액, 48호 작성방법 2)",
          f"={I}-({L(f'{SPLIT}/매출액')}-{L(f'{SPLIT}/매출원가')}-{L(f'{SPLIT}/판관비')}+{L(f'{SPLIT}/영업외수익')}"
          f"-{L(f'{SPLIT}/영업외비용')})")
    r.put("감면 사업 소득", "감면 사업 소득(각사업연도소득 - 그 밖의 사업 소득, 그 밖의 사업이 결손이면 각사업연도소득)",
          f"=MAX(0,{I}-MAX(0,{L('그 밖의 사업 소득')}))", note="조세특례제한법 제143조 제3항")
    r.put("감면 대상 소득", "감면 대상 소득(감면 사업 소득 × 과세표준 / 각사업연도소득)",
          f"=IF(OR({I}<=0,{B}<=0),0,ROUNDDOWN({g('감면 사업 소득')}*{B}/{I},0))",
          note="법인세법 제59조 제2항 · 시행령 제96조 제2호")
    r.put("중소기업특별세액감면 대상세액", "중소기업특별세액감면 대상세액(산출세액 × 감면 소득 / 과세표준 × 감면율)",
          f'=IF(AND({L("적용 여부")}="O",{T}>0,{B}>0,{L("감면율")}>0),'
          f"ROUNDDOWN({T}*MIN(1,{g('감면 대상 소득')}/MAX(1,{B}))*{L('감면율')},0),0)")
    r.put("최저한세 한도 안 감면", "최저한세 적용대상 감면 · 공제 한도(산출세액 - 최저한세)", f"=MAX(0,{T}-{M})")
    room_m = g("최저한세 한도 안 감면")
    r.put("중소기업특별세액감면", "중소기업특별세액감면(감면 한도 · 최저한세 반영, 8호(갑) 112)",
          f"=MIN({g('중소기업특별세액감면 대상세액')},{L('감면 한도')},{room_m})")
    su = L("당기분/창업중소기업 세액감면")
    r.put("창업중소기업 세액감면 적용", "창업중소기업 세액감면(최저한세 반영, 8호(갑) 111)",
          f"=MIN({su},{room_m}-{g('중소기업특별세액감면')})")
    r.put("감면 배제", "최저한세 · 한도로 받지 못한 감면(이월 없음)",
          f"={g('중소기업특별세액감면 대상세액')}+{su}-{g('중소기업특별세액감면')}-{g('창업중소기업 세액감면 적용')}")
    r.put("최저한세 적용대상 감면", "최저한세 적용대상 감면 계",
          f"={g('중소기업특별세액감면')}+{g('창업중소기업 세액감면 적용')}")
    RM = g("최저한세 적용대상 감면")

    # 세액공제 표: 최저한세 적용대상(이월 → 당기) 다음 적용제외(이월 → 당기)
    row = s.section(r.row + 1, "4-1. 세액공제 순서(이월분 먼저, 먼저 생긴 해부터)")
    X.header(s.ws, row, ["구분", "8호(갑)", "연도", "최저한세", "이월 · 당기", "공제 가능액", "공제세액", "최저한세 미공제",
                         "그 밖의 미공제", "소멸", "이월액"])
    row += 1
    ordered = p.extra["rows"]
    groups = [[x for x in ordered if x["class"] == "대상"], [x for x in ordered if x["class"] != "대상"]]
    carry_years = R["세액공제 이월 연수"]
    fy = p.extra["calc"]["fy"]
    tot: list[dict] = []          # 묶음마다 {"used", "carry", "cut_min"} 계 칸
    for gi, grp in enumerate(groups):
        if gi == 0:
            s.put(row, 1, "적용대상 한도: G 산출세액 - 최저한세 - 감면, H 감면 뒤 낼 세액")
            s.put(row, 7, f"=MAX(0,{T}-{M}-{RM})", money=True)
            s.put(row, 8, f"=MAX(0,{T}-{RM})", money=True)
            room, troom = f"$G${row}", f"$H${row}"
        else:
            s.put(row, 1, "적용제외 한도: 감면 · 적용대상 공제 뒤 남은 세액")
            s.put(row, 7, f"=MAX(0,{T}-{RM}-{tot[0]['used']})", money=True)
            room = troom = f"$G${row}"
        row += 1
        first = row
        for it in grp:
            s.put(row, 1, it["name"])
            s.put(row, 2, it["code"])
            s.put(row, 4, f"적용{it['class']}")
            if it["carried"]:
                ycell, acell = p.extra["carry_cells"][it["key"]]
                s.put(row, 3, f"={ycell}", fmt="0")
                s.put(row, 5, "이월")
                amount = f"{acell}"
                s.put(row, 6, f"=IF(AND({ycell}>0,{fy}-{ycell}>{carry_years}),0,{amount})", money=True)
                s.put(row, 10, f"=IF(AND({ycell}>0,{fy}-{ycell}>{carry_years}),{amount},0)", money=True)
            else:
                s.put(row, 3, fy, fmt="0")
                s.put(row, 5, "당기")
                amount = L(it["key"])
                s.put(row, 6, f"={amount}", money=True)
                s.put(row, 10, 0, money=True)
            cum = f"SUM($F${first}:F{row - 1})" if row > first else "0"
            s.put(row, 7, f"=MAX(0,MIN(F{row},{room}-{cum}))", money=True)
            s.put(row, 8, f"=MAX(0,MIN({cum}+F{row},{troom})-MAX({cum},{room}))", money=True)
            s.put(row, 9, f"=F{row}-G{row}-H{row}", money=True)
            s.put(row, 11, f"={amount}-G{row}-J{row}", money=True)
            bk.reg(p.id, f"공제세액/{it['key']}", s.addr(row, 7))
            bk.reg(p.id, f"이월액/{it['key']}", s.addr(row, 11))
            row += 1
        if not grp:
            s.put(row, 1, "해당 줄 없음")
            row += 1
        last = row - 1
        s.put(row, 1, "적용대상 계" if gi == 0 else "적용제외 계")
        s.put(row, 7, f"=SUM(G{first}:G{last})", kind="total", money=True)
        s.put(row, 8, f"=SUM(H{first}:H{last})", kind="total", money=True)
        s.put(row, 11, f"=SUM(K{first}:K{last})", kind="total", money=True)
        tot.append({"used": f"$G${row}", "cut_min": f"$H${row}", "carry": f"$K${row}"})
        row += 2
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("최저한세 적용대상 공제", "최저한세 적용대상 세액공제 계", f"={tot[0]['used']}")
    r.put("최저한세 적용제외 공제", "최저한세 적용제외 세액공제 계", f"={tot[1]['used']}")
    r.put("최저한세 적용대상", "최저한세 적용대상 공제감면세액(3호 17)", f"={RM}+{g('최저한세 적용대상 공제')}", kind="total")
    r.put("최저한세 적용제외", "최저한세 적용제외 공제감면세액(3호 19)", f"={g('최저한세 적용제외 공제')}", kind="total")
    r.put("공제감면 합계", "공제감면세액 합계", f"={g('최저한세 적용대상')}+{g('최저한세 적용제외')}")
    r.put("최저한세 미공제", "최저한세로 받지 못한 세액공제(다음 해로 넘김)", f"={tot[0]['cut_min']}+{tot[1]['cut_min']}")
    r.put("이월액 합계", "다음 해로 넘기는 세액공제(8호 부표3 (125))", f"={tot[0]['carry']}+{tot[1]['carry']}")
    row = forms_table(bk, s, r.row + 1, p, [("3", "17 최저한세 적용대상 공제감면세액", "최저한세 적용대상"),
                                            ("3", "19 최저한세 적용제외 공제감면세액", "최저한세 적용제외"),
                                            ("4", "(122) 최저한세 ③", "최저한세"),
                                            ("8부표2", "중소기업특별세액감면 ⑥감면세액", "중소기업특별세액감면"),
                                            ("8부표3", "(125) 이월액 합계", "이월액 합계"),
                                            ("48", "(12) 과세표준 감면분", "감면 대상 소득"),
                                            ("조특10의9", "세액공제액(1차 + 2차 + 3차 연도)", f"{EMP}/계산액"),
                                            ("조특10의9", "㊱ 추가공제 세액공제액(육아휴직 복귀)", f"{EMP}/추가공제/육아휴직 복귀"),
                                            ("8을", "공제감면세액에 대한 법인세 추가납부(코드 773) ⑮ 세액", ADD_KEY),
                                            ("조특3_1", "㊶ 해당 연도에 공제받을 세액", f"{RND}/계산액")])
    notes(s, row, p)
