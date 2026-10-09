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

from yangdo import QUESTIONS_PATH, dates, engine, ruleset  # noqa: E402
from yangdo import facts as F  # noqa: E402

TAIL = "이 결과는 검토용입니다. 신고 전 최종 판단은 세무 전문가가 합니다."

RESULT, QUESTIONS, REVIEW, WORKBOOK = "result.json", "질문.md", "양도소득세_검토.md", "양도소득세_계산근거.xlsx"
OUTPUT_NAMES = (RESULT, QUESTIONS, REVIEW, WORKBOOK)


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
        plan = "계획 %s 에서 다룬다" % o["계획"] if o["계획"] != "없음" else "이 스킬이 다루지 않는다"
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
              "| 취득일 · 양도일 | %s · %s |" % (v["취득일"], v["양도일"]),
              "| 보유 · 거주 | %d년 · %d년 |" % (v["보유년"], v["거주년"]),
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


def clear_previous(out):
    """이 스크립트가 쓰는 파일 이름만 지운다. 폴더 안의 다른 파일은 그대로 둔다.

    통합 문서를 먼저 지운다. 엑셀이 열어 둔 파일은 지워지지 않아서(PermissionError), 막히면 다른 이전 결과를 지우기 전에 멈춘다.
    """
    for name in (WORKBOOK,) + tuple(n for n in OUTPUT_NAMES if n != WORKBOOK):
        p = os.path.join(out, name)
        if os.path.isfile(p):
            os.remove(p)


def write_outputs(res, out):
    os.makedirs(out, exist_ok=True)
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
    wb = os.path.join(out, WORKBOOK)
    return paths + ([wb] if os.path.exists(wb) else [])


def _iso_date(s):
    """--오늘 의 값. 다른 날짜 입력과 같은 dates.to_date 로 읽어 YYYY-MM-DD 글자만 받는다(파이썬 3.10 과 3.11 이상이 같다)."""
    try:
        d = dates.to_date(s)
    except ValueError:
        d = None
    if d is None:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 로 적습니다: %s" % s)
    return d.isoformat()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--사실관계", required=True)
    ap.add_argument("--출력", required=True)
    ap.add_argument("--오늘", type=_iso_date)
    ap.add_argument("--rules")
    a = ap.parse_args(argv)
    try:
        with open(a.사실관계, encoding="utf-8") as f:
            facts = json.load(f)
    except (OSError, ValueError) as e:
        print("사실관계 파일을 읽지 못했다: %s" % e)
        return 2
    if not isinstance(facts, dict):
        print("사실관계 파일의 맨 위는 JSON 객체여야 한다")
        return 2
    try:
        os.makedirs(a.출력, exist_ok=True)
        clear_previous(a.출력)
        try:
            res = engine.calculate(facts, rules_dir=a.rules, today=a.오늘,
                                   workbook_path=os.path.join(a.출력, WORKBOOK))
        except ruleset.RuleError as e:
            print("기준정보 오류: %s" % e)
            return 3
        except F.FactsError as e:
            print(e)
            return 2
        write_outputs(res, a.출력)
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
