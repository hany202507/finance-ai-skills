# -*- coding: utf-8 -*-
"""결과 JSON, 검토 문서, 질문 문서를 쓰는 출력 함수. scripts/run.py, scripts/mcp_server.py, scripts/make_return.py 가 함께 쓴다.
진입점이 함께 쓰는 작은 도우미(명령줄 날짜 읽기 iso_date, 사실관계 파일 읽기 read_facts, 오류 기록 log_call_sites)도 여기 둔다.
진입점 스크립트끼리는 서로 가져다 쓰지 않는다.

이 모듈이 쓰는 파일 이름은 RESULT, QUESTIONS, REVIEW, WORKBOOK 넷이다(OUTPUT_NAMES). 통합 문서(WORKBOOK)는 engine 이 쓰고
이 모듈은 있으면 경로만 돌려준다. 출력 폴더에 계산 결과를 내는 차례(이전 결과 지움 → 계산 → 파일 쓰기)는 calculate_to 하나에 있다.

같은 출력 폴더에 다시 돌릴 때 지우는 이름도 이 모듈 한 곳에 있다. 계산 결과 넷(OUTPUT_NAMES)과 신고서 단계
(scripts/make_return.py)가 쓰는 이름(RETURN_NAMES), 양도소득세 전자신고 파일 이름 꼴(EFILE_NAME)이다. 계산만 다시 돌려도
옛 신고서 PDF, 전자신고 파일, 신고값, 안내서, 확인 문서가 새 계산 결과 옆에 남지 않는다.

edition.PUBLIC 이 참이면 통합 문서만 남긴다. 결과 JSON, 질문 문서, 검토 문서는 쓰지 않고(write_outputs), 부른 쪽이 결과를
화면 출력(report_text, questions_md)이나 MCP 응답으로 낸다. 지우는 이름 목록은 그대로다. 같은 폴더에 예전에 남은 결과 JSON,
신고값, 전자신고 파일이 새 결과 옆에 남지 않게 하려는 것이다.
"""
import argparse
import json
import os
import re
import sys
import traceback

from yangdo import QUESTIONS_PATH, dates, edition, engine

TMP_LEFT_NOTE = None    # 지우지 못한 전자신고 임시 폴더를 알리는 문장(폴더 이름 하나를 넣는다). 임시 폴더를 만들지 않는 판에는 없다

TAIL = "이 결과는 검토용입니다. 신고 전 최종 판단은 세무 전문가가 합니다."

RESULT, QUESTIONS, REVIEW, WORKBOOK = "result.json", "질문.md", "양도소득세_검토.md", edition.WORKBOOK
OUTPUT_NAMES = (RESULT, QUESTIONS, REVIEW, WORKBOOK)

# 신고서 단계(scripts/make_return.py)가 같은 출력 폴더에 쓰는 이름. make_return.py 가 이 이름을 가져다 쓴다.
# 신고서 PDF 이름은 forms.OUT_NATIONAL·OUT_LOCAL 과 같은 글자다. forms 는 pymupdf 를 읽어서
# 계산만 하는 run.py 와 MCP 계산 도구가 쓰는 이 모듈이 import 하지 않는다(같은 글자인지는 시험이 본다).
# 신고서 PDF 는 forms 가 임시 이름(.tmp)으로 만든 뒤 바꾸므로 그 이름도 지운다
RETURN_VALUES, GUIDE, ATTACHMENTS, CONFIRM = "신고값.json", "홈택스_입력안내.md", "부속서류.md", "신고_확인.md"
FORM_NATIONAL, FORM_LOCAL = edition.FORM_NATIONAL, edition.FORM_LOCAL
RETURN_NAMES = (RETURN_VALUES, FORM_NATIONAL, FORM_LOCAL, FORM_NATIONAL + ".tmp", FORM_LOCAL + ".tmp", GUIDE, ATTACHMENTS, CONFIRM)
EFILE_NAME = re.compile(r"^[0-9]{8}C116300\.[0-9]{2}$")     # 양도소득세 전자신고 파일 이름 꼴(규격서 p20). 다른 세목 파일은 건드리지 않는다
EFILE_TMP_PREFIX = ".efile-"                                # 전자신고 임시 폴더 이름의 머리. 지우는 차례를 정할 때 쓴다
# 여러 진입점(run.py, make_return.py, MCP)이 같이 쓰는 문장
QUESTION_COUNTS = "계산 질문 %d개, 이 스킬이 다루지 않는 경우 %d개"
STALE_NOTE = "지우지 못해 남은 파일: %s. 이 파일은 이전 실행의 것이다. 이번 실행의 결과가 아니니 신고에 쓰지 않는다"


def won(n):
    return "{:,}".format(n or 0)


def cell(n):
    """계산하지 않은 값(전액비과세 자산의 취득가액 등)은 0 이 아니라 「해당 없음」으로 적는다."""
    return "해당 없음" if n is None else won(n)


def _question_text():
    try:
        with open(QUESTIONS_PATH, encoding="utf-8") as f:
            return {q["id"]: q for q in json.load(f)["문항"]}
    except (OSError, ValueError, KeyError):
        return {}


def plan_text(plan):
    """다루지않음의 「계획」 값을 사람에게 말하는 문장. 값은 계획 번호, 「미정」(다루려고 하지만 어느 계획에도 없다),
    「없음」(다룰 계획이 없다) 가운데 하나다(references/적용한계.md 의 표)."""
    if plan == "없음":
        return "이 스킬이 다루지 않는다"
    if plan == "미정":
        return "다룰 계획이 정해지지 않았다"
    return "계획 %s 에서 다룬다" % plan


def questions_md(res):
    qs = _question_text()
    L = ["# 계산 전에 확인할 것", ""]
    for q in res["질문"]:
        d = qs.get(q["문항"], {})
        L.append("- [%s] %s%s" % (q["문항"], ("자산 %s: " % q["자산"]) if q.get("자산") else "", d.get("질문") or q["내용"]))
        if d.get("질문"):
            L.append("  - %s" % q["내용"])
        if d.get("모를때확인처"):
            L.append("  - 모를 때 확인하는 곳: %s" % ", ".join(d["모를때확인처"]))
    for o in res["다루지않음"]:
        plan = plan_text(o["계획"])
        L.append("- %s%s. %s" % (("자산 %s: " % o["자산"]) if o.get("자산") else "", o["내용"], plan))
    return "\n".join(L) + "\n"


ROWS = [("양도가액", "양도가액"), ("취득가액", "취득가액"), ("필요경비", "필요경비"), ("양도차익", "양도차익"),
        ("과세양도차익", "과세양도차익"), ("장기보유특별공제", "장특공"), ("양도소득금액", "양도소득금액"),
        ("기본공제", "기본공제"), ("과세표준", "과세표준"), ("산출세액", "산출세액"), ("지방소득세", "지방소득세")]


def _cite_lines(cites):
    out, seen = [], set()
    for g in cites:
        k = (g["법령"], g["조항"])
        if k in seen:
            continue
        seen.add(k)
        out.append("- %s %s (시행 %s) %s" % (g["법령"], g["조항"], g["시행일"], " · ".join("「%s」" % e for e in g["발췌"])))
    return out


def _designated(st):
    """조정대상지역 판정 한 건(판정의 조정_취득일, 조정_양도일)을 글자로. 판정이 없거나 지정 값이 없으면 「해당 없음」."""
    d = (st or {}).get("지정")
    return "해당 없음" if d is None else ("예" if d else "아니오")


def review_md(res):
    info = res["기준정보"]
    L = ["# 양도소득세 검토", ""]
    if info["낡음"]:
        L += ["기준정보 확인일이 7일 넘게 지났습니다. 갱신한 뒤 다시 계산하십시오.", ""]
    L += ["기준정보 판 %s, 확인일 %s" % (info["판"], info["확인일"]), ""]
    cal = res["계산"]
    for row in cal["자산"]:
        v, c = row["판정"], row["계산"]
        L += ["## 자산 %s (%s)" % (row["id"], v["종류"]), "",
              "| 판정 | 결과 |", "|---|---|",
              "| 취득일 · 양도일 | %s · %s |" % (v["취득일"], v["양도일"])]
        if v["종류"] == "주택":   # 토지·건물은 조정대상지역을 판정하지 않으므로 줄을 쓰지 않는다
            L.append("| 조정대상지역(취득일 · 양도일) | %s · %s |" % (_designated(v.get("조정_취득일")), _designated(v.get("조정_양도일"))))
        L += ["| 보유 · 거주 | %d년 · %d년 |" % (v["보유년"], v["거주년"]),
              "| 1세대1주택(일시적 2주택 포함) | %s |" % ("예" if v["일세대일주택"] else "아니오"),
              "| 비과세 · 고가주택 · 전액비과세 | %s · %s · %s |" % tuple("예" if v[k] else "아니오" for k in ("비과세", "고가주택", "전액비과세")),
              "| 미등기 · 중과 · 단기 | %s · %s · %s |" % ("예" if v["미등기"] else "아니오", v["중과"] or "없음", v["단기"] or "없음"),
              "| 장기보유특별공제 | %s (%s) |" % (v["장특공"], c["장특공률"]),
              "| 세율구분 코드 | %s |" % c["코드"]["세율구분"], "",
              "| 계산 | 금액(원) |", "|---|---:|"]
        L += ["| %s | %s |" % (label, cell(c[key])) for label, key in ROWS]
        if c.get("취득가액방법"):
            L += ["", "취득가액 방법: %s" % c["취득가액방법"]]
        if c.get("필요경비_제외"):
            L += ["", "필요경비에서 뺀 항목", ""] + ["- " + m for m in c["필요경비_제외"]]
        L += ["", "근거", ""] + _cite_lines(v["근거"]) + [""]
    t = cal["합계"]
    L += ["## 합계", "", "| 항목 | 금액(원) |", "|---|---:|",
          "| 자산별 산출세액 합 | %s |" % won(t["자산별세액"]),
          "| 같은 세율 자산 합산 세액(소득세법 제104조⑤2호) | %s |" % won(t["호별합산세액"]),
          "| 합산 비교 세액(소득세법 제104조⑤) | %s |" % won(t["합산비교세액"]),
          "| 산출세액 | %s |" % won(t["산출세액"]),
          "| 지방소득세 | %s |" % won(t["지방소득세"]), ""]
    if t["산출세액"] != t["자산별세액"]:
        L += ["자산별 산출세액은 자산마다 따로 계산한 참고값입니다. 산출세액은 같은 세율 자산 합산 세액과 합산 비교 세액 중 큰 값입니다.", ""]
    cites = _cite_lines(cal.get("근거") or [])
    if cites:
        L += ["## 계산 근거", ""] + cites + [""]
    if res["확인사항"]:
        L += ["## 확인사항", ""] + ["- " + m for m in res["확인사항"]] + [""]
    if res["경고"]:
        L += ["## 경고", ""] + ["- " + m for m in res["경고"]] + [""]
    L += ["## 검산", "", "통과" if not res["검산"] else "\n".join("- " + m for m in res["검산"]), "", TAIL, ""]
    return "\n".join(L)


def report_text(res):
    """공개본 run.py 가 화면에 내는 글. 공개본은 결과 JSON, 질문 문서, 검토 문서를 쓰지 않으므로 상태, 합계, 확인사항, 경고,
    검산, 질문, 다루지않음을 여기 모아 화면에 낸다. 질문으로 끝난 결과는 questions_md 의 문항을 그대로 싣는다.
    사실관계에는 인적사항이 없다(facts.check_personal 이 막는다). 판정표와 근거 조문은 통합 문서의 요약·근거 시트에 있다."""
    info = res["기준정보"]
    L = ["기준정보 판 %s, 확인일 %s" % (info["판"], info["확인일"]), ""]
    if res["상태"] == "질문":
        L += [question_counts(res), "", questions_md(res).rstrip("\n"), ""]
    else:
        t = res["계산"]["합계"]
        L += ["산출세액 %s원, 지방소득세 %s원, 검산 %s" % (won(t["산출세액"]), won(t["지방소득세"]),
                                                    "통과" if not res["검산"] else "실패 %d건" % len(res["검산"])), ""]
        for r in res["계산"]["자산"]:
            v, c = r["판정"], r["계산"]
            L.append("자산 %s(%s, 양도일 %s): 1세대1주택 %s, 비과세 %s, 중과 %s, 장기보유특별공제 %s, 산출세액 %s원, 지방소득세 %s원"
                     % (r["id"], v["종류"], v["양도일"], "예" if v["일세대일주택"] else "아니오",
                        "전액" if v["전액비과세"] else ("예" if v["비과세"] else "아니오"), v["중과"] or "없음", v["장특공"],
                        cell(c["산출세액"]), cell(c["지방소득세"])))
        L.append("")
        if t["산출세액"] != t["자산별세액"]:
            L += ["자산별 산출세액은 자산마다 따로 계산한 참고값입니다. 산출세액은 같은 세율 자산 합산 세액과 합산 비교 세액 중 큰 값입니다.", ""]
    for title, xs in (("확인사항", res["확인사항"]), ("경고", res["경고"]), ("검산", res["검산"])):
        if xs:
            L += ["## %s" % title, ""] + ["- " + m for m in xs] + [""]
    if res["상태"] != "질문":
        L += ["판정표, 계산 흐름, 근거 조문은 %s 에 있다." % WORKBOOK, ""]
    return "\n".join(L + [TAIL]) + "\n"


def why(e):
    """OSError 를 한 줄 까닭으로. 운영체제 문장이 있으면 그것만 쓴다."""
    return " ".join(str(getattr(e, "strerror", None) or e).split())


def iso_date(s):
    """명령줄 --오늘 의 값. 다른 날짜 입력과 같은 dates.to_date 로 읽어 YYYY-MM-DD 글자만 받는다(파이썬 3.10 과 3.11 이상이 같다).

    run.py 와 make_return.py 가 함께 쓴다."""
    try:
        d = dates.to_date(s)
    except ValueError:
        d = None
    if d is None:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 로 적습니다: %s" % s)
    return d.isoformat()


def read_facts(path):
    """사실관계 파일을 읽는다. (사실관계, None) 또는 (None, 읽지 못한 까닭). run.py 와 make_return.py 가 함께 쓴다."""
    try:
        with open(path, encoding="utf-8") as f:
            facts = json.load(f)
    except (OSError, ValueError) as e:
        return None, "사실관계 파일을 읽지 못했다: %s" % e
    if not isinstance(facts, dict):
        return None, "사실관계 파일의 맨 위는 JSON 객체여야 한다"
    return facts, None


def log_call_sites(e, head, stream=None):
    """예상하지 못한 예외를 운영자가 볼 수 있게 표준오류에 남긴다. head 뒤에 예외 형 이름을 붙이고 호출 위치(파일, 줄, 함수)만 찍는다.

    예외 문장에는 사실관계나 신고인의 값이 실릴 수 있어 싣지 않는다. make_return.py 와 MCP 서버가 같은 꼴로 남긴다.
    """
    stream = stream or sys.stderr
    print("%s(%s). 예외 문장은 싣지 않는다. 호출 위치:" % (head, type(e).__name__), file=stream)
    traceback.print_tb(e.__traceback__, file=stream)


def question_counts(res):
    """질문으로 끝난 계산 결과의 문항 수 문장. run.py, make_return.py 가 같은 말을 쓴다."""
    return QUESTION_COUNTS % (len(res["질문"]), len(res["다루지않음"]))


def is_tmp_dir(out, name):
    """출력 폴더 안의 name 이 이 도구가 만든 전자신고 임시 폴더인지. 임시 폴더를 만들지 않는 판(edition.PUBLIC)은 늘 거짓이다."""
    return False


def tmp_left_notes(out):
    """남은 전자신고 임시 폴더마다 알릴 문장. 임시 폴더를 만들지 않는 판(edition.PUBLIC)은 빈 목록이다.
    인적사항이 든 신고값 사본이 있을 수 있어 계산만 돌린 쪽(run.py, MCP 계산 도구)도 알린다."""
    return []


def stale_names(out, skip=()):
    """출력 폴더에 남아 있는, 이 도구가 쓰는 이름의 파일(계산 결과, 신고서 단계 파일, 전자신고 파일). skip 의 이름은 뺀다."""
    known = set(RETURN_NAMES + OUTPUT_NAMES) - set(skip)
    try:
        return [n for n in sorted(os.listdir(out)) if n in known or EFILE_NAME.match(n)]
    except OSError:
        return []


def clear_order(name):
    """신고서 단계 이름을 지우는 차례. 제출용 이름의 전자신고 파일, 임시 폴더, 신고서 PDF 를 다른 파일보다 먼저 지운다."""
    if EFILE_NAME.match(name):
        return 0
    if name.startswith(EFILE_TMP_PREFIX):
        return 1
    return 2 if name.startswith((FORM_NATIONAL, FORM_LOCAL)) else 3


def clear_all(out):
    """이전 실행이 남긴 파일을 지운다. (지우지 못한 임시 폴더 이름 목록, 처음 난 OSError 또는 None).

    지우는 것은 신고서 단계 이름(RETURN_NAMES), 옛 전자신고 파일(EFILE_NAME), 이 도구가 만든 임시 폴더(is_tmp_dir),
    계산 결과 넷(OUTPUT_NAMES)뿐이다. 다른 세목의 전자신고 파일과 사용자 파일, 폴더는 그대로 둔다. 이름이 「.efile-」 로
    시작하는 사용자 폴더도 그대로 둔다.
    차례는 전자신고 파일, 임시 폴더, 신고서 PDF, 나머지 신고서 단계 파일, 마지막이 계산 결과(통합 문서부터)다. 제출용 파일이
    새 계산 결과 옆에 남는 일부터 막으려는 차례다. 신고서 단계 파일은 하나가 다른 프로그램에 잡혀 지워지지 않아도 나머지를
    끝까지 지운다. 계산 결과는 통합 문서를 먼저 지우고, 엑셀이 열어 두어 막히면(PermissionError) 나머지 계산 결과는 그대로 둔다.
    """
    left, first = [], None
    for name in sorted(os.listdir(out), key=lambda n: (clear_order(n), n)):
        path = os.path.join(out, name)
        if (name in RETURN_NAMES or EFILE_NAME.match(name)) and (os.path.isfile(path) or os.path.islink(path)):
            try:
                os.remove(path)
            except OSError as e:
                first = first or e
    try:
        for name in (WORKBOOK,) + tuple(n for n in OUTPUT_NAMES if n != WORKBOOK):
            p = os.path.join(out, name)
            if os.path.isfile(p):
                os.remove(p)
    except OSError as e:
        first = first or e
    return left, first


def clear_previous(out):
    """이전 실행이 남긴 파일을 지운다(clear_all). 지우지 못한 파일이 있으면 처음 난 OSError 를 다시 낸다.

    지우지 못한 임시 폴더 이름 목록을 돌려준다(임시 폴더는 오류로 보지 않는다). run.py, MCP 계산 도구, make_return.py 가
    calculate_to 로 이 함수를 같이 쓴다. 폴더 안의 다른 파일은 그대로 둔다.
    """
    left, first = clear_all(out)
    if first is not None:
        raise first
    return left


def write_outputs(res, out):
    """계산 결과 파일을 쓰고 경로 목록을 돌려준다. 공개본은 아무것도 쓰지 않고 engine 이 쓴 통합 문서의 경로만 돌려준다."""
    os.makedirs(out, exist_ok=True)
    wb = os.path.join(out, WORKBOOK)
    if edition.PUBLIC:
        return [wb] if res["상태"] != "질문" and os.path.exists(wb) else []
    paths = []
    with open(os.path.join(out, RESULT), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    paths.append(os.path.join(out, RESULT))
    if res["상태"] == "질문":
        p = os.path.join(out, QUESTIONS)
        with open(p, "w", encoding="utf-8") as f:
            f.write(questions_md(res))
        return paths + [p]
    p = os.path.join(out, REVIEW)
    with open(p, "w", encoding="utf-8") as f:
        f.write(review_md(res))
    paths.append(p)
    return paths + ([wb] if os.path.exists(wb) else [])


def calculate_to(facts, out, rules_dir=None, today=None):
    """출력 폴더에 계산 결과를 낸다. (engine.calculate 결과, 쓴 파일 경로 목록).

    폴더를 만들고 이전 결과(계산 결과와 신고서 단계 파일, clear_previous)를 지운 뒤 계산하고(통합 문서 포함) 결과 파일을 쓴다.
    이번 결과가 질문이어도 이전 완료 결과가 옆에 남지 않고, 계산만 다시 돌려도 옛 신고서와 전자신고 파일이 남지 않는다.
    run.py, mcp_server.py, make_return.py 가 이 함수 하나를 같이 쓴다.
    기준정보가 깨졌으면 ruleset.RuleError, 사실관계가 틀렸으면 facts.FactsError, 폴더나 파일을 쓰지 못하면 OSError 가 그대로 나온다.
    """
    os.makedirs(out, exist_ok=True)
    clear_previous(out)
    res = engine.calculate(facts, rules_dir=rules_dir, today=today, workbook_path=os.path.join(out, WORKBOOK))
    return res, write_outputs(res, out)
