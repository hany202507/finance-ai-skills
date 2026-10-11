# -*- coding: utf-8 -*-
"""결과 JSON, 검토 문서, 질문 문서를 쓰는 출력 함수. scripts/run.py, scripts/mcp_server.py, scripts/make_return.py 가 함께 쓴다.

이 모듈이 쓰는 파일 이름은 RESULT, QUESTIONS, REVIEW, WORKBOOK 넷이다(OUTPUT_NAMES). 통합 문서(WORKBOOK)는 engine 이 쓰고
이 모듈은 있으면 경로만 돌려준다. 출력 폴더에 계산 결과를 내는 차례(이전 결과 지움 → 계산 → 파일 쓰기)는 calculate_to 하나에 있다.
"""
import json
import os

from yangdo import QUESTIONS_PATH, engine

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


def clear_previous(out):
    """이 모듈이 쓰는 파일 이름만 지운다. 폴더 안의 다른 파일은 그대로 둔다.

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


def calculate_to(facts, out, rules_dir=None, today=None):
    """출력 폴더에 계산 결과를 낸다. (engine.calculate 결과, 쓴 파일 경로 목록).

    폴더를 만들고 이 모듈이 쓰는 이전 결과를 지운 뒤 계산하고(통합 문서 포함) 결과 파일을 쓴다. 이번 결과가 질문이어도
    이전 완료 결과가 옆에 남지 않는다. run.py, mcp_server.py, make_return.py 가 이 함수 하나를 같이 쓴다.
    기준정보가 깨졌으면 ruleset.RuleError, 사실관계가 틀렸으면 facts.FactsError, 폴더나 파일을 쓰지 못하면 OSError 가 그대로 나온다.
    """
    os.makedirs(out, exist_ok=True)
    clear_previous(out)
    res = engine.calculate(facts, rules_dir=rules_dir, today=today, workbook_path=os.path.join(out, WORKBOOK))
    return res, write_outputs(res, out)
