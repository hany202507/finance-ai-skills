# -*- coding: utf-8 -*-
"""사실관계 JSON 하나로 판정·세액을 계산하고 계산근거 워크북(양도소득세_계산근거.xlsx)을 만든다.

  python scripts/run.py --사실관계 facts.json --출력 out/ [--오늘 YYYY-MM-DD] [--rules rules/]

종료코드: 0 완료, 1 검산 실패, 2 질문 또는 다루지않음(사실관계 파일을 못 읽거나 값의 형식이 틀리거나 인적사항이 든 경우 포함),
3 기준정보 오류, 4 출력 파일 쓰기 실패(이전 통합 문서를 엑셀이 열어 둔 경우 등. 파일을 닫고 다시 실행한다)

edition.PUBLIC 이 참이면 출력 폴더에 양도소득세_계산근거.xlsx 만 남긴다. 상태, 합계, 자산별 판정, 확인사항, 경고, 검산, 질문,
다루지않음은 화면에 낸다(outputs.report_text).

같은 출력 폴더에 다시 실행하면 먼저 이전 결과를 지우고 시작한다. 지우는 것은 이 도구가 쓰는 이름의 파일(result.json, 질문.md,
양도소득세_검토.md, 양도소득세_계산근거.xlsx, 신고값.json, 신고서 PDF 두 벌, 홈택스_입력안내.md, 부속서류.md, 신고_확인.md,
전자신고 파일 <8자리>C116300.<2자리>)뿐이다(yangdo/outputs.py 의 clear_all). 이번 결과가 질문이어도 이전 완료 결과가 옆에 남지 않고,
계산만 다시 돌려도 옛 신고서가 새 계산 결과 옆에 남지 않는다. 다른 파일은 건드리지 않는다.
신고서 단계 파일을 먼저 지우고 계산 결과는 통합 문서부터 지운다. 지워지지 않는 파일이 있으면 종료코드 4 로 멈춘다.
엑셀이 통합 문서를 열어 두었으면 계산 결과 파일은 그대로 남는다. 종료코드 4 로 멈출 때는 남은 파일 이름을 표준오류에 적고
이전 실행의 것이라고 알린다.
"""
import argparse
import os
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import ruleset  # noqa: E402
from yangdo import facts as F  # noqa: E402
# 출력 함수는 yangdo/outputs.py 에 있다(mcp_server.py, make_return.py 와 함께 쓴다). 이름을 그대로 다시 내보내 run.review_md 처럼 불러도 된다
from yangdo import outputs  # noqa: E402
from yangdo.outputs import (OUTPUT_NAMES, QUESTIONS, RESULT, REVIEW, TAIL, WORKBOOK, calculate_to, cell,  # noqa: E402,F401
                            clear_previous, questions_md, review_md, won, write_outputs)


# 명령줄 날짜 읽기와 사실관계 파일 읽기는 yangdo/outputs.py 에 있다(make_return.py 도 그것을 쓴다). 옛 이름으로도 부를 수 있다
iso_date = _iso_date = outputs.iso_date
read_facts = outputs.read_facts


def _tell_tmp_left(out):
    """지우지 못했거나 다른 파일이 함께 있어 지우지 않은 전자신고 임시 폴더를 표준오류로 알린다(인적사항이 든 신고값 사본이 있을 수 있다)."""
    for note in outputs.tmp_left_notes(out):
        print(note, file=sys.stderr)


def _print_utf8(text):
    """Windows 기본 cp949 표준출력에서도 깨지지 않게 쓴다(화면 출력에 확인사항 문장 전체가 나간다)."""
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode(sys.stdout.encoding or "utf-8", "replace"))
        sys.stdout.buffer.flush()


def _tell_write_failure(e, out):
    print("출력 파일을 쓰지 못했습니다: %s (%s). 파일을 닫고 다시 실행하십시오." % (e.filename or out, outputs.why(e)),
          file=sys.stderr)


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
        # 이전 결과 지우기를 여기서 먼저 한다(calculate_to 도 같은 것을 다시 하지만 그때는 지울 것이 없다). 지우다 막혔을 때만
        # 남은 파일이 이전 실행의 것이라고 말할 수 있어서다. 새 파일을 쓰다 막힌 경우의 파일은 이번 실행이 쓴 것이다
        os.makedirs(a.출력, exist_ok=True)
        clear_previous(a.출력)
    except OSError as e:
        _tell_write_failure(e, a.출력)
        stale = outputs.stale_names(a.출력)
        if stale:       # 이 스크립트는 확인 문서를 쓰지 않으므로 남은 파일이 이전 실행의 것임을 여기서 알린다
            print(outputs.STALE_NOTE % ", ".join(stale), file=sys.stderr)
        _tell_tmp_left(a.출력)
        return 4
    try:
        try:
            res, _ = calculate_to(facts, a.출력, rules_dir=a.rules, today=a.오늘)
        except ruleset.RuleError as e:
            print("기준정보 오류: %s" % e)
            return 3
        except F.FactsError as e:
            print(e)
            return 2
    except OSError as e:  # 새 파일을 쓰지 못한 경우. 1 은 검산 실패 전용이다
        _tell_write_failure(e, a.출력)
        _tell_tmp_left(a.출력)
        return 4
    _tell_tmp_left(a.출력)
    code = 2 if res["상태"] == "질문" else 0 if res["상태"] == "완료" else 1
    _print_utf8(outputs.report_text(res))       # 결과 파일 대신 화면에 낸다
    return code


if __name__ == "__main__":
    sys.exit(main())
