"""시험용 합성 회사(스무 명) 입력을 만든다. `python -m ctax employ "<신고 건>" --sample`.

실제 회사 · 사람과 무관한 값이다. 2025 과세연도, 중소기업, 수도권. 급여대장은 2024 · 2025 두 해이고 직전전(2023) 인원은
전기 신고 인원으로 넣었다. 사람마다 한 가지씩 판정 경우를 넣었고 기대값은 README.md 「시험용 예시」 와 시험 `test_sample_twenty` 에 있다.
"""
from __future__ import annotations

from datetime import date as D
from pathlib import Path

from openpyxl import Workbook

from .calc import month_end
from .model import COMPANY_ROWS, PAY_COLS, STAFF_COLS

COMPANY = {"과세연도 시작일": D(2025, 1, 1), "과세연도 종료일": D(2025, 12, 31), "기업 구분": "중소기업", "증가 지역 수도권": "Y",
           "소비성서비스업": "N", "해당 과세연도 창업": "N",
           "직전 1차년도 공제액 청년등": 29_000_000, "직전 1차년도 공제액 청년등 외": 8_500_000,
           "직전전 1차년도 공제액 청년등": 14_500_000, "직전전 1차년도 공제액 청년등 외": 0,
           "전기 신고 직전전 상시근로자 수": 9.5, "전기 신고 직전전 청년등 수": 5.0}

# 사번, 성명, 생년월일, 입사일, 퇴사일, 고용형태, 월 급여, 그 밖의 열, 무엇을 보는 사람인지
STAFF = [
    ("S01", "강도윤", D(1975, 4, 2), D(2018, 3, 1), None, "정규직", 7_000_000, {"임원": "Y", "최대주주·친족": "Y"}, "대표이사(임원 · 최대주주)"),
    ("S02", "문서연", D(1978, 8, 17), D(2019, 1, 2), None, "정규직", 3_800_000, {"최대주주·친족": "Y"}, "최대주주의 배우자"),
    ("S03", "박준호", D(1980, 5, 20), D(2018, 3, 1), None, "정규직", 5_200_000, {}, "청년등 외, 두 해 모두 열두 달"),
    ("S04", "이수민", D(1987, 9, 9), D(2019, 7, 1), None, "정규직", 4_300_000, {"육아휴직 복귀자": "Y"}, "육아휴직 복귀자(추가공제 1명)"),
    ("S05", "김하늘", D(1996, 3, 15), D(2022, 1, 10), None, "정규직", 3_400_000, {}, "청년, 두 해 모두 열두 달"),
    ("S06", "정우진", D(1998, 11, 2), D(2023, 6, 1), None, "정규직", 3_100_000, {}, "청년"),
    ("S07", "최예린", D(1990, 8, 20), D(2021, 4, 1), None, "정규직", 4_000_000, {}, "2025년 8월에 35세. 그 달부터 청년이 아니다"),
    ("S08", "한지호", D(1999, 1, 25), D(2025, 3, 10), None, "정규직", 2_900_000, {}, "2025년 3월 입사 청년(열 달)"),
    ("S09", "오세영", D(1990, 12, 5), D(2025, 2, 3), None, "정규직", 3_900_000, {}, "2025년 계약 때 34세. 12월에 35세지만 청년 간주 3년"),
    ("S10", "윤태경", D(1985, 2, 14), D(2025, 5, 12), None, "정규직", 4_800_000, {}, "2025년 5월 입사 청년등 외(여덟 달)"),
    ("S11", "서다은", D(1997, 7, 7), D(2024, 9, 2), None, "정규직", 3_000_000, {}, "2024년 9월 입사 청년(직전 넉 달)"),
    ("S12", "임현우", D(1995, 10, 10), D(2022, 8, 1), D(2025, 6, 20), "정규직", 3_300_000, {}, "2025년 6월 20일 퇴사(월말 재직은 5월까지)"),
    ("S13", "조미라", D(1982, 4, 4), D(2020, 2, 1), D(2024, 12, 31), "정규직", 4_500_000, {}, "2024년 말 퇴사"),
    ("S14", "백승현", D(2000, 6, 6), D(2025, 7, 1), D(2025, 12, 31), "기간제", 2_600_000, {"계약 1년 미만": "Y"}, "근로계약기간 1년 미만"),
    ("S15", "신가영", D(1999, 9, 9), D(2024, 3, 1), None, "기간제", 2_800_000, {}, "1년 이상 기간제. 상시근로자지만 청년에서 빠진다"),
    ("S16", "권동민", D(1978, 1, 1), D(2023, 5, 1), None, "단시간", 1_400_000, {"월 소정근로시간": 80}, "단시간 80시간(0.5명)"),
    ("S17", "황유나", D(2001, 2, 2), D(2025, 1, 6), None, "단시간", 600_000, {"월 소정근로시간": 40}, "단시간 40시간(상시근로자가 아니다)"),
    ("S18", "안병철", D(1962, 3, 3), D(2024, 5, 1), None, "정규직", 3_200_000, {}, "계약 때 62세(고령자, 청년등)"),
    ("S19", "송지아", D(1984, 12, 12), D(2021, 11, 1), None, "정규직", 3_600_000, {"장애인 등": "Y"}, "장애인(청년등)"),
    ("S20", "류성훈", D(1989, 6, 30), D(2023, 2, 1), None, "정규직", 4_100_000,
     {"입대일": D(2010, 1, 11), "전역일": D(2011, 10, 10)}, "병역 21개월을 빼면 2025년 내내 청년 나이"),
]
YEARS = (2024, 2025)


def write(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "회사"
    ws.append(["항목", "값", "설명"])
    for label, _, _, text in COMPANY_ROWS:
        ws.append([label, COMPANY.get(label), text])
    ws = wb.create_sheet("사원명부")
    head = [c[0] for c in STAFF_COLS]
    ws.append(head)
    for sid, name, birth, hired, left, kind, _, more, memo in STAFF:
        row = {"사번": sid, "성명": name, "생년월일": birth, "입사일": hired, "퇴사일": left, "고용형태": kind, "비고": memo, **more}
        ws.append([row.get(h) for h in head])
    ws = wb.create_sheet("급여대장")
    ws.append([c[0] for c in PAY_COLS])
    for year in YEARS:
        for month in range(1, 13):
            first, last = D(year, month, 1), month_end(D(year, month, 1))
            for sid, name, _, hired, left, _, pay, _, _ in STAFF:
                if hired <= last and (left is None or left >= first):
                    ws.append([f"{year}-{month:02d}", sid, name, pay, int(pay * 0.03) // 10 * 10, int(pay * 0.045) // 10 * 10,
                               int(pay * 0.03545) // 10 * 10])
    for sheet in wb.worksheets:
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 16
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, D):
                    c.number_format = "yyyy-mm-dd"
                elif isinstance(c.value, int) and c.value >= 1000:
                    c.number_format = "#,##0"
    wb["회사"].column_dimensions["A"].width = 34
    wb["회사"].column_dimensions["C"].width = 90
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
