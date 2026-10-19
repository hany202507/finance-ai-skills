# -*- coding: utf-8 -*-
"""부가세 판단 엔진 셀프체크 — 샘플 케이스 판정 요약 출력."""
from vat_engine import JudgmentInput, Purpose, summarize


def demo():
    cases = [
        JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=1000, 세액=100, 지출목적=Purpose.일반경비),
        JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=1000, 세액=100, 지출목적=Purpose.접대),
    ]
    print(summarize(cases))


if __name__ == "__main__":
    demo()
