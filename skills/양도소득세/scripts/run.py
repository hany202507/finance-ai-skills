# -*- coding: utf-8 -*-
"""사실관계 JSON 하나로 결과 JSON, 검토 문서, 계산근거 워크북을 만든다.

  python scripts/run.py --사실관계 facts.json --출력 out/ [--오늘 YYYY-MM-DD] [--rules rules/]

종료코드: 0 완료, 1 검산 실패, 2 질문 또는 다루지않음(사실관계 파일을 못 읽거나 값의 형식이 틀리거나 인적사항이 든 경우 포함),
3 기준정보 오류, 4 출력 파일 쓰기 실패(이전 통합 문서를 엑셀이 열어 둔 경우 등. 파일을 닫고 다시 실행한다)

같은 출력 폴더에 다시 실행하면 먼저 이 스크립트가 쓰는 파일 네 개(result.json, 질문.md, 양도소득세_검토.md, 양도소득세_계산근거.xlsx)만
지우고 시작한다. 이번 결과가 질문이어도 이전 완료 결과가 옆에 남지 않는다. 다른 파일은 건드리지 않는다.
통합 문서를 맨 먼저 지운다. 엑셀이 열어 둔 파일은 지워지지 않으므로, 그 경우 종료코드 4 로 멈추고 폴더는 그대로 남는다.
"""
import argparse
import json
import os
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import dates, ruleset  # noqa: E402
from yangdo import facts as F  # noqa: E402
# 출력 함수는 yangdo/outputs.py 에 있다(mcp_server.py, make_return.py 와 함께 쓴다). 이름을 그대로 다시 내보내 run.review_md 처럼 불러도 된다
from yangdo.outputs import (OUTPUT_NAMES, QUESTIONS, RESULT, REVIEW, TAIL, WORKBOOK, calculate_to, cell,  # noqa: E402,F401
                            clear_previous, questions_md, review_md, won, write_outputs)


def iso_date(s):
    """--오늘 의 값. 다른 날짜 입력과 같은 dates.to_date 로 읽어 YYYY-MM-DD 글자만 받는다(파이썬 3.10 과 3.11 이상이 같다).

    make_return.py 도 이 함수를 쓴다."""
    try:
        d = dates.to_date(s)
    except ValueError:
        d = None
    if d is None:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 로 적습니다: %s" % s)
    return d.isoformat()


_iso_date = iso_date


def read_facts(path):
    """사실관계 파일을 읽는다. (사실관계, None) 또는 (None, 읽지 못한 까닭). make_return.py 도 이 함수를 쓴다."""
    try:
        with open(path, encoding="utf-8") as f:
            facts = json.load(f)
    except (OSError, ValueError) as e:
        return None, "사실관계 파일을 읽지 못했다: %s" % e
    if not isinstance(facts, dict):
        return None, "사실관계 파일의 맨 위는 JSON 객체여야 한다"
    return facts, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--사실관계", required=True)
    ap.add_argument("--출력", required=True)
    ap.add_argument("--오늘", type=iso_date)
    ap.add_argument("--rules")
    a = ap.parse_args(argv)
    facts, why = read_facts(a.사실관계)
    if why:
        print(why)
        return 2
    try:
        try:
            res, _ = calculate_to(facts, a.출력, rules_dir=a.rules, today=a.오늘)
        except ruleset.RuleError as e:
            print("기준정보 오류: %s" % e)
            return 3
        except F.FactsError as e:
            print(e)
            return 2
    except OSError as e:  # 폴더를 못 만들거나 이전 파일을 못 지우거나 새 파일을 못 쓴 경우. 1 은 검산 실패 전용이다
        print("출력 파일을 쓰지 못했습니다: %s (%s). 파일을 닫고 다시 실행하십시오." % (
            e.filename or a.출력, " ".join(str(e.strerror or e).split())), file=sys.stderr)
        return 4
    if res["상태"] == "질문":
        print("질문 %d개, 다루지않음 %d개. 질문.md 에 적었다" % (len(res["질문"]), len(res["다루지않음"])))
        return 2
    t = res["계산"]["합계"]
    print("산출세액 %s원, 지방소득세 %s원, 검산 %s" % (won(t["산출세액"]), won(t["지방소득세"]),
                                                 "통과" if not res["검산"] else "실패 %d건" % len(res["검산"])))
    return 0 if res["상태"] == "완료" else 1


if __name__ == "__main__":
    sys.exit(main())
