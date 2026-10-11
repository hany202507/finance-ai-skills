# -*- coding: utf-8 -*-
"""사실관계 JSON 과 신고인 JSON 으로 신고서 PDF, 전자신고 변환파일, 홈택스 입력 안내서, 부속서류 목록까지 만든다.

  python scripts/make_return.py --사실관계 facts.json --신고인 신고인.json --출력 out/ [--오늘 YYYY-MM-DD] [--rules rules/]

차례: 계산(run.py 와 같은 outputs.calculate_to) → 신고인 정보 검사(filing.load) → 신고인 질문 F01~F08(filing.questions)
→ 신고값(return_values.build) → 서식 검산(forms_check.check) → 신고서 PDF(forms.render) → 전자신고 파일(efile.write, 독립 검증기 통과분만)
→ 입력 안내서·부속서류(guide) → 신고_확인.md. 앞 단계가 막히면 뒤 단계는 하지 않는다.

종료코드
  0 완료
  1 서식 검산 또는 전자신고 검증 실패(엔진 검산 실패, 신고값이나 신고서 PDF 를 만들지 못한 경우 포함). 결과를 신고에 쓰지 않는다
  2 질문(계산 질문, 신고인 질문 F01~F08) 또는 다루지않음(신고 범위가 아닌 건, 전액 비과세 자산이 있는 건, 확정신고,
    읽을 수 없거나 형식이 틀린 입력 파일)
  3 기준정보·서식판·규격판 오류(규격판 잠금 포함)
  4 출력 파일 쓰기 실패(이전 파일을 다른 프로그램이 열어 둔 경우 등. 파일을 닫고 다시 실행한다)

출력 폴더에 쓰는 파일
  result.json, 양도소득세_검토.md, 양도소득세_계산근거.xlsx   계산이 끝났을 때(질문이면 result.json, 질문.md)
  신고값.json                                              신고인 정보까지 갖춰졌을 때. 인적사항이 들어 있다(맨 위 키 _주의)
  양도소득세_신고서.pdf, 지방소득세_신고서.pdf              서식 검산 통과
  <작성일자>C116300.01                                     서식 검산과 전자신고 검증 모두 통과
  홈택스_입력안내.md, 부속서류.md                           신고값이 있을 때
  신고_확인.md                                             항상. 단계별 결과, 검산·검증 문장, 확인사항, 사람이 할 일

같은 출력 폴더에 다시 실행하면 이 스크립트와 run.py 가 쓰는 이름만 먼저 지운다. 옛 전자신고 파일(<8자리>C116300.<2자리>)과
앞선 실행이 남긴 임시 폴더(.efile-*)도 지운다. 이번에 새 파일을 만들지 못했을 때 옛 파일이 새 결과처럼 남지 않게 하려는 것이다.
지우는 차례는 전자신고 파일, 임시 폴더, 신고서 PDF, 나머지 이 스크립트의 파일, 마지막이 run.py 의 파일(통합 문서부터)이다.
하나가 다른 프로그램에 잡혀 지워지지 않아도 나머지를 끝까지 지운 뒤 종료코드 4 로 멈추고, 남은 파일 이름을 신고_확인.md 에
이전 실행의 것이라고 적는다. 엑셀이 계산근거를 열어 둔 채 다시 돌려도 옛 전자신고 파일은 남지 않는다. 다른 파일은 건드리지 않는다.

예상하지 못한 오류가 나면 트레이스백은 표준오류에 쓰고, 이미 만든 신고서 PDF 와 전자신고 파일을 지운 뒤 예외 형 이름만
신고_확인.md 에 적고 종료코드 1 로 끝낸다(예외 문장에는 인적사항이 실릴 수 있어 싣지 않는다).

신고서와 전자신고 파일을 만들지 않는 사유는 withheld 한 곳에서 모은다. 지금은 둘이다(둘 다 잠정).
  전액 비과세 자산   신고값이 05 레코드 값을 비워 두어 전자신고 파일을 만들 수 없다. 비과세 양도의 신고 여부는 세무 전문가가 정한다
  확정신고           예정신고를 하지 않은 확정신고에는 예정신고 무신고가산세와 납부지연가산세가 붙는데 신고값이 가산세를 계산하지
                     않아(0) 납부할 세액이 실제보다 적다. 가산세 계산이 들어오면 withheld 의 이 가지만 걷어낸다
사유가 있으면 서식 검산까지 하고 종료코드 2 로 끝낸다. 계산 결과, 신고값.json, 안내서는 참고용으로 낸다.

인적사항(성명, 주민등록번호, 주소, 전화, 계좌, 양수인, 자산 지번, 매도인 성명)은 신고값.json, 신고서 PDF, 전자신고 파일,
입력 안내서·부속서류에만 들어간다. 화면 출력, 신고_확인.md, make 가 돌려주는 값(MCP 응답)에는 싣지 않는다.
홈택스·위택스 로그인과 제출은 사람이 한다. 이 스크립트는 파일만 만든다.
"""
import argparse
import json
import os
import re
import shutil
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
for _p in (SKILL, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from yangdo import bjd, efile, filing, forms, forms_check, guide, outputs, return_values, ruleset  # noqa: E402
from yangdo import facts as F  # noqa: E402
from run import iso_date, read_facts  # noqa: E402

RV_FILE, GUIDE_FILE, ATTACH_FILE, CONFIRM_FILE = "신고값.json", "홈택스_입력안내.md", "부속서류.md", "신고_확인.md"
# 이 스크립트가 쓰는 파일 이름. 신고서 PDF 는 forms 가 임시 이름(.tmp)으로 만든 뒤 바꾸므로 그 이름도 지운다
OWN_NAMES = (RV_FILE, forms.OUT_NATIONAL, forms.OUT_LOCAL, forms.OUT_NATIONAL + ".tmp", forms.OUT_LOCAL + ".tmp",
             GUIDE_FILE, ATTACH_FILE, CONFIRM_FILE)
EFILE_NAME = re.compile(r"^[0-9]{8}C116300\.[0-9]{2}$")     # 양도소득세 전자신고 파일 이름 꼴(규격서 p20). 다른 세목 파일은 건드리지 않는다
FORMS, EFILE = "forms", "efile"                             # 어디까지 만드는지. forms 는 신고서 PDF 까지, efile 은 전자신고 파일까지
NOT_DONE = "하지 않음"
STEPS = ("계산", "신고인 정보", "신고값", "서식 검산", "신고서 PDF", "전자신고 파일", "입력 안내서·부속서류")

RV_NOTICE = ("이 파일에는 신고인과 양수인의 인적사항(성명, 주민등록번호, 주소, 전화, 계좌), 자산 지번, 매도인 성명이 들어 있다. "
             "메일·메신저·저장소·채팅에 올리거나 붙여 넣지 않는다. 신고가 끝나면 신고서 PDF, 전자신고 파일과 함께 안전한 곳에 두거나 지운다")
NOT_MADE = "신고서와 전자신고 파일을 만들지 않았다"
FINAL_KIND = "확정"                                         # 신고값 「신고.구분」 의 확정신고 값(신고인 JSON 신고.구분 그대로)
# 끝까지 가지 못한 실행의 입력 안내서·부속서류 맨 위에 붙이는 줄(보고의 상태 → 문장). 없는 상태는 붙이지 않는다
GUIDE_HEAD = {
    "서식검산실패": "이 실행은 서식 검산에 실패해 신고서와 전자신고 파일을 만들지 않았다. 아래 값으로 신고하지 않는다. 까닭은 신고_확인.md 에 있다.",
    "서식실패": "이 실행은 신고서 PDF 를 만들지 못해 전자신고 파일도 만들지 않았다. 아래 값으로 신고하지 않는다. 까닭은 신고_확인.md 에 있다.",
    "전자신고검증실패": "이 실행은 전자신고 검증에 실패해 전자신고 파일을 남기지 않았다. 아래 값으로 신고하지 않는다. 까닭은 신고_확인.md 에 있다.",
}
NO_SENTENCE = "전자신고 파일을 만들지 못했다. 생성기가 까닭을 알리지 않았다"
# 규격서 원문만으로 정하지 못해 홈택스 형식검증으로 확정할 칸 가운데 레이아웃 FIXUPS 에 없는 것(global.md 「정한 것」·「실행 중 정한 것」)
UNCONFIRMED = (
    "01-23 세무프로그램코드: 규격서 p27~28 표에 없는 프로그램이라 9000(기타)을 썼다",
    "01-18~22·26·27 세무대리인 칸: 본인 신고라 공란으로 두었다",
    "03-31 주민세_세율: 합계 행만 10.00, 나머지 행은 0. 03-30·32·33 주민세 금액 칸은 0 이다",
)
TAIL = "이 결과는 검토용입니다. 신고 전 최종 판단은 세무 전문가가 합니다."


def _dedupe(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def _why(e):
    return " ".join(str(getattr(e, "strerror", None) or e).split())


def _inside(path, folder):
    """path 가 folder 안(또는 folder 자신)인지. 경로가 없으면 쓰던 파일로 본다."""
    if not path:
        return True
    try:
        a, b = os.path.realpath(os.fspath(path)), os.path.realpath(folder)
        return os.path.normcase(a) == os.path.normcase(b) or os.path.normcase(a).startswith(os.path.normcase(b) + os.sep)
    except (TypeError, ValueError):
        return True


def _is_tmp_dir(out, name):
    path = os.path.join(out, name)
    return name.startswith(efile.TMP_PREFIX) and os.path.isdir(path) and not os.path.islink(path)


def _clear_order(name):
    """지우는 차례. 제출용 이름의 전자신고 파일, 임시 폴더, 신고서 PDF 를 다른 파일보다 먼저 지운다."""
    if EFILE_NAME.match(name):
        return 0
    if name.startswith(efile.TMP_PREFIX):
        return 1
    return 2 if name.startswith((forms.OUT_NATIONAL, forms.OUT_LOCAL)) else 3


def clear_previous(out):
    """이 스크립트가 쓰는 이름과 옛 전자신고 파일, 앞선 실행의 임시 폴더만 지운다. (알릴 문장 목록, 첫 OSError 또는 None).

    하나가 막혀도 나머지를 끝까지 지운다. 지우지 못한 파일이 있으면 처음 난 OSError 를 돌려주고, 부른 쪽이 종료코드 4 로 멈춘다.
    지우지 못한 임시 폴더는 문장으로 알린다. 폴더 안의 다른 파일은 그대로 둔다.
    """
    left, first = [], None
    for name in sorted(os.listdir(out), key=lambda n: (_clear_order(n), n)):
        path = os.path.join(out, name)
        if _is_tmp_dir(out, name):
            shutil.rmtree(path, ignore_errors=True)
            if os.path.lexists(path):
                left.append("앞선 실행이 남긴 임시 폴더 %s 를 지우지 못했다. 인적사항이 든 임시 파일이 남아 있을 수 있으니 직접 지운다" % name)
        elif (name in OWN_NAMES or EFILE_NAME.match(name)) and (os.path.isfile(path) or os.path.islink(path)):
            try:
                os.remove(path)
            except OSError as e:
                first = first or e
    return left, first


def _leftovers(out):
    """출력 폴더에 남아 있는, 이 스크립트와 run.py 가 쓰는 이름의 파일(신고_확인.md 제외)."""
    known = set(OWN_NAMES + tuple(outputs.OUTPUT_NAMES)) - {CONFIRM_FILE}
    try:
        return [n for n in sorted(os.listdir(out)) if n in known or EFILE_NAME.match(n)]
    except OSError:
        return []


def _clear_all(rep, out):
    """이전 결과를 지운다. 제출용 파일부터 지우고 run.py 의 파일(통합 문서부터)은 마지막에 지운다.

    지우지 못한 것이 있으면 남은 파일 이름을 이전 실행의 것이라고 알림에 적고 처음 난 OSError 를 다시 낸다(종료코드 4).
    """
    notes, first = clear_previous(out)
    rep["알림"] += notes
    try:
        outputs.clear_previous(out)      # 통합 문서부터 지운다. 엑셀이 열어 두었으면 계산 결과 파일은 그대로 남는다
    except OSError as e:
        first = first or e
    if first is not None:
        stale = _leftovers(out)
        if stale:
            rep["알림"].append("지우지 못해 남은 파일: %s. 이 파일은 이전 실행의 것이다. 이번 실행의 결과가 아니니 신고에 쓰지 않는다"
                             % ", ".join(stale))
        raise first


def _drop_submittable(rep, out):
    """예상하지 못한 오류로 끝날 때, 이번 실행이 만든 신고서 PDF 와 제출용 이름의 전자신고 파일, 임시 폴더를 지운다.

    확인 문서 없이 제출용 파일만 남는 일을 막는다. 지우지 못한 이름을 돌려준다.
    """
    left = []
    try:
        names = sorted(os.listdir(out))
    except OSError:
        return left
    for name in names:
        path = os.path.join(out, name)
        if _is_tmp_dir(out, name):
            shutil.rmtree(path, ignore_errors=True)
        elif _clear_order(name) in (0, 2) and (name in OWN_NAMES or EFILE_NAME.match(name)) and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            continue
        if os.path.lexists(path):
            left.append(name)
    rep["파일"] = [x for x in rep["파일"] if os.path.exists(x)]
    return left


def _report(out, upto):
    return {"종료코드": 0, "상태": "완료", "요약": "", "범위": upto, "출력": out,
            "단계": {name: NOT_DONE for name in STEPS}, "파일": [], "기준정보": None, "판": None, "합계": None,
            "질문": [], "다루지않음": [], "신고인질문": [], "검산": [], "서식검산": None, "전자신고": None,
            "확인사항": [], "경고": [], "알림": [], "사람이할일": [], "안내서머리": None}


class _Stop(Exception):
    """뒤 단계를 하지 않고 끝낸다. 보고에 이미 적었다."""


def _stop(rep, code, state, summary, step=None, result=None, note=None):
    rep.update(종료코드=code, 상태=state, 요약=summary)
    if step:
        rep["단계"][step] = result or summary
    if note:
        rep["알림"].append(note)
    raise _Stop()


def _reference(rep, step, fn):
    """기준정보·코드표·법정동코드 표를 읽는 단계. 표가 깨졌으면 종료코드 3."""
    try:
        return fn()
    except (ruleset.RuleError, bjd.BjdError) as e:
        _stop(rep, 3, "기준정보오류", "기준정보 오류로 멈췄다", step, "기준정보 오류", "기준정보 오류: %s" % e)


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _write_rv(rep, rv, out):
    path = os.path.join(out, RV_FILE)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict({"_주의": RV_NOTICE}, **rv), fh, ensure_ascii=False, indent=1)
    rep["파일"].append(path)


def _write_guides(rep, rv, facts, res, out):
    """입력 안내서와 부속서류 목록. 끝까지 가지 못한 실행이면 무슨 일이 있었는지를 맨 위 한 줄로 적는다."""
    note = rep["안내서머리"] or (GUIDE_HEAD.get(rep["상태"]) if rep["종료코드"] == 1 else None)
    head = "> %s\n\n" % note if note else ""
    rep["파일"].append(_write_text(os.path.join(out, GUIDE_FILE), head + guide.hometax_input(rv)))
    rep["파일"].append(_write_text(os.path.join(out, ATTACH_FILE), head + guide.attachments(rv, facts, res)))
    rep["단계"]["입력 안내서·부속서류"] = {1: "만듦(신고에 쓰지 않는다)", 2: "만듦(참고용)"}.get(rep["종료코드"], "만듦")


def _calculate(rep, facts, out, today, rules_dir):
    step = rep["단계"]
    if not isinstance(facts, dict):
        facts, why = read_facts(facts)
        if why:
            _stop(rep, 2, "입력오류", "사실관계 파일을 읽지 못했다", "계산", "사실관계 파일을 읽지 못함", why)
    try:
        res, paths = outputs.calculate_to(facts, out, rules_dir=rules_dir, today=today)
    except ruleset.RuleError as e:
        _stop(rep, 3, "기준정보오류", "기준정보 오류로 계산하지 않았다", "계산", "기준정보 오류", "기준정보 오류: %s" % e)
    except F.FactsError as e:
        _stop(rep, 2, "입력오류", "사실관계 파일의 값이 틀려 계산하지 않았다", "계산", "사실관계 오류", str(e))
    rep["파일"] += paths
    rep.update(기준정보=res["기준정보"], 질문=res["질문"], 다루지않음=res["다루지않음"], 검산=res["검산"])
    rep["확인사항"] += res["확인사항"]
    rep["경고"] += res["경고"]
    if res["상태"] == "질문":
        n, m = len(res["질문"]), len(res["다루지않음"])
        _stop(rep, 2, "질문" if n else "다루지않음", "계산 질문 %d개, 다루지않음 %d개. %s 에 적었다" % (n, m, outputs.QUESTIONS),
              "계산", "질문 %d개, 다루지않음 %d개" % (n, m))
    rep["합계"] = {k: res["계산"]["합계"][k] for k in ("산출세액", "지방소득세")}
    if res["상태"] != "완료":
        _stop(rep, 1, "검산실패", "계산 검산 실패 %d건. 이 결과를 신고에 쓰지 않는다" % len(res["검산"]), "계산", "검산 실패 %d건" % len(res["검산"]))
    step["계산"] = "완료"
    return facts, res


def _filer(rep, filer, facts, res):
    step = rep["단계"]
    try:
        f = filing.load(filer)
    except filing.FilingError as e:
        _stop(rep, 2, "입력오류", "신고인 파일을 읽지 못했거나 형식이 틀렸다", "신고인 정보", "형식 오류", "신고인 정보: %s" % e)
    rep["경고"] += f.get("_경고") or []
    qs = _reference(rep, "신고인 정보", lambda: filing.questions(f, facts, res))
    if qs:
        rep["신고인질문"] = qs
        _stop(rep, 2, "질문", "신고인 정보 질문 %d개. 신고인 파일(F07 은 사실관계)을 채운 뒤 다시 실행한다" % len(qs),
              "신고인 정보", "질문 %d개" % len(qs))
    step["신고인 정보"] = "갖춤"
    return f


def _values(rep, res, facts, f, rules_dir):
    try:
        rv = _reference(rep, "신고값", lambda: return_values.build(res, facts, f, rules_dir=rules_dir))
    except return_values.Unsupported as u:
        plan = "계획 %s 에서 다룬다" % u.계획 if u.계획 != "없음" else "이 스킬이 다루지 않는다"
        rep["다루지않음"] = rep["다루지않음"] + [{"자산": None, "내용": str(u), "계획": u.계획}]
        _stop(rep, 2, "다루지않음", "신고 범위가 아니라 신고값을 만들지 않았다", "신고값", "다루지않음", "%s. %s" % (u, plan))
    except filing.FilingError as e:
        _stop(rep, 2, "입력오류", "신고인 파일의 값이 틀려 신고값을 만들지 않았다", "신고값", "신고인 정보 오류", "신고인 정보: %s" % e)
    except ValueError as e:
        _stop(rep, 1, "신고값실패", "신고값을 만들지 못했다", "신고값", "만들지 못함", "신고값을 만들지 못했다. %s" % e)
    rep["단계"]["신고값"] = "만듦"
    rep["판"] = rv.get("판")
    return rv


def withheld(rv, res):
    """신고서와 전자신고 파일을 만들지 않는 사유 목록. 비면 만든다. 사유를 더하거나 걷어낼 때는 이 함수만 고친다.

    사유마다 {"이름": 단계 표에 적는 짧은 이름, "까닭": 요약 줄의 앞 구절, "알림": 신고_확인.md 와 보고에 적는 문장,
    "안내": 입력 안내서·부속서류 맨 위에 붙이는 문장, "다루지않음": 보고의 다루지않음에 더할 항목}.
    """
    out = []
    exempt = [r["id"] for r in res["계산"]["자산"] if r["판정"].get("전액비과세")]
    if exempt:
        # 잠정. 신고값이 전액 비과세 자산의 05 레코드 값(취득가액종류 등)을 비워 두어 전자신고 파일을 만들 수 없다
        out.append({
            "이름": "전액 비과세 자산", "까닭": "전액 비과세 자산이 있어",
            "알림": "전액 비과세 자산(%s)이 있어 %s. 비과세 양도의 신고 여부와 방법은 세무 전문가가 정한다. "
                    "계산 결과, 신고값, 입력 안내서는 참고용으로 냈다" % (", ".join(exempt), NOT_MADE),
            "안내": "전액 비과세 자산이 있어 %s. 아래는 참고용이다. 비과세 양도의 신고 여부와 방법은 세무 전문가가 정한다." % NOT_MADE,
            "다루지않음": [{"자산": a, "내용": "전액 비과세 자산의 신고서·전자신고 파일", "계획": "없음"} for a in exempt]})
    if (rv.get("신고") or {}).get("구분") == FINAL_KIND:
        # 잠정. 가산세 계산이 들어오면 이 가지만 걷어낸다(yangdo 모듈의 확정신고 코드는 그대로 있다)
        out.append({
            "이름": "확정신고 가산세", "까닭": "확정신고의 가산세를 계산하지 않아",
            "알림": "확정신고라 %s. 예정신고를 하지 않은 확정신고에는 예정신고 무신고가산세와 납부지연가산세가 붙는데, "
                    "이 도구는 가산세를 계산하지 않아 납부할 세액이 실제보다 적게 나온다. 가산세를 더한 신고는 세무 전문가와 한다. "
                    "계산 결과, 신고값, 입력 안내서는 참고용으로 냈다" % NOT_MADE,
            "안내": "확정신고는 이 도구가 가산세를 계산하지 않아 %s. 아래는 참고용이고 납부할 세액에 가산세(예정신고 무신고, 납부지연)가 "
                    "빠져 있다." % NOT_MADE,
            "다루지않음": [{"자산": None, "내용": "예정신고를 하지 않은 확정신고의 가산세(예정신고 무신고가산세, 납부지연가산세) 계산",
                        "계획": "미정"}]})
    return out


def _forms_and_file(rep, rv, res, out, rules_dir, upto):
    """서식 검산 → 신고서 PDF → 전자신고 파일. 막힌 곳에서 보고에 적고 돌아온다(신고값과 안내서는 부른 쪽이 쓴다)."""
    step = rep["단계"]
    fails = forms_check.check(rv, res, rules_dir=rules_dir)
    rep["서식검산"] = fails
    if fails:
        step["서식 검산"] = "실패 %d건" % len(fails)
        rep.update(종료코드=1, 상태="서식검산실패", 요약="서식 검산 실패 %d건. 신고서와 전자신고 파일을 만들지 않았다" % len(fails))
        return
    step["서식 검산"] = "통과"
    held = withheld(rv, res)
    if held:
        rep["알림"] += [w["알림"] for w in held]
        rep["다루지않음"] = rep["다루지않음"] + [x for w in held for x in w["다루지않음"]]
        rep["안내서머리"] = " ".join(w["안내"] for w in held)
        rep.update(종료코드=2, 상태="다루지않음", 요약="%s %s" % (", ".join(w["까닭"] for w in held), NOT_MADE))
        step["신고서 PDF"] = step["전자신고 파일"] = "만들지 않음(%s)" % ", ".join(w["이름"] for w in held)
        return
    try:
        rep["파일"] += forms.render(rv, out)
    except ValueError as e:          # 칸 넘침(forms_pdf.Overflow), 코드표·매핑에 없는 값. 문장에는 칸 이름만 있다
        step["신고서 PDF"] = "만들지 못함"
        rep["알림"].append("신고서 PDF 를 만들지 못했다. %s" % e)
        rep.update(종료코드=1, 상태="서식실패", 요약="신고서 PDF 를 만들지 못했다. 전자신고 파일도 만들지 않았다")
        return
    step["신고서 PDF"] = "만듦"
    if upto != EFILE:
        step["전자신고 파일"] = "요청하지 않음"
        return
    try:
        w = efile.write(rv, out)
    except efile.Locked as e:
        step["전자신고 파일"] = "만들지 않음(규격판 잠금)"
        rep["알림"].append("전자신고 파일을 만들지 않았다. %s" % e)
        rep.update(종료코드=3, 상태="규격판잠금", 요약="규격판이 잠겨 있어 전자신고 파일을 만들지 않았다")
        return
    except (ValueError, KeyError) as e:      # 파일명을 만들 수 없거나(BuildError) 신고값 행과 레이아웃이 어긋났다
        text = e.args[0] if isinstance(e, KeyError) and e.args else e
        w = {"경로": None, "검증": ["전자신고 레코드를 만들지 못했다. %s" % text], "파일명": None, "경고": []}
    fails = list(w["검증"]) or ([] if w["경로"] else [NO_SENTENCE])
    rep["전자신고"] = {"파일명": w["파일명"], "검증": fails, "경고": list(w["경고"])}
    if not w["경로"]:
        step["전자신고 파일"] = "검증 실패 %d건" % len(fails)
        rep.update(종료코드=1, 상태="전자신고검증실패", 요약="전자신고 검증 실패 %d건. 전자신고 파일을 남기지 않았다" % len(fails))
        return
    rep["파일"].append(w["경로"])
    step["전자신고 파일"] = "만듦(%s)" % w["파일명"]


def _pipeline(rep, facts, filer, out, today, rules_dir, upto):
    os.makedirs(out, exist_ok=True)
    _clear_all(rep, out)
    facts, res = _calculate(rep, facts, out, today, rules_dir)
    f = _filer(rep, filer, facts, res)
    rv = _values(rep, res, facts, f, rules_dir)
    try:
        _forms_and_file(rep, rv, res, out, rules_dir, upto)
    finally:
        # 신고값은 forms.render 가 확인사항을 덧붙인 뒤의 값으로 쓴다(render 전에 끝났으면 그때의 값)
        rep["확인사항"] = _dedupe(rep["확인사항"] + list(rv.get("확인사항") or []))
    _write_rv(rep, rv, out)
    _write_guides(rep, rv, facts, res, out)
    if rep["종료코드"] == 0:
        rep["요약"] = ("신고서 PDF 와 전자신고 파일 %s 을 만들었다" % rep["전자신고"]["파일명"] if rep["전자신고"]
                     else "신고서 PDF 를 만들었다(전자신고 파일은 요청하지 않았다)")


def _unconfirmed():
    """규격서 미확인 칸. 레이아웃 FIXUPS 가운데 홈택스 형식검증으로 확정할 것과 UNCONFIRMED."""
    try:
        with open(os.path.join(efile.EFILE_DIR, efile.LAYOUT_FILE), encoding="utf-8") as fh:
            fixups = json.load(fh).get("FIXUPS") or []
    except (OSError, ValueError):
        return ["레이아웃 파일을 읽지 못해 규격서 미확인 칸 목록을 싣지 못했다"]
    out = []
    for x in fixups:
        if "형식검증" in str(x.get("확인") or ""):
            where = "%s 레코드%s" % (x.get("레코드"), (" %s" % x["name"]) if x.get("name") else "")
            out.append("%s: %s" % (where, x.get("내용")))
    return out + list(UNCONFIRMED)


def _todo(rep):
    """사람이 할 일. 홈택스·위택스 로그인과 제출은 사람이 한다."""
    code, sent = rep["종료코드"], rep["전자신고"]
    out = []
    if code != 0:
        asked = {"질문": "위 질문에 답을 채운 뒤 다시 실행한다. 계산 질문은 사실관계 파일에, 신고인 정보 질문은 신고인 파일에 채운다(F07 은 사실관계 파일)",
                 "다루지않음": "다루지않음 사유를 세무 전문가와 확인한다. 이 스킬은 이 건의 신고서와 전자신고 파일을 만들지 않는다. "
                           "참고용으로 낸 값으로 신고하지 않는다",
                 "입력오류": "알림의 문장대로 입력 파일을 고친 뒤 다시 실행한다"}
        failed = ("이 실행의 결과로 신고하지 않는다. 표준오류에 나온 오류 기록과 함께 운영자에게 알린다" if rep["상태"] == "오류" else
                  "검산·검증 실패 문장을 확인한다. 이 실행의 결과로 신고하지 않는다. 입력이 틀렸으면 고쳐서 다시 실행하고, 아니면 운영자에게 알린다")
        first = {1: failed,
                 2: asked.get(rep["상태"], asked["질문"]),
                 3: "기준정보·서식판·규격판 문제는 운영자에게 알린다. 사용자 작업에서 고치지 않는다",
                 4: "출력 폴더의 파일을 연 프로그램(엑셀, PDF 보기 등)을 닫고 같은 명령을 다시 실행한다"}[code]
        out.append(first)
        if code == 3 and rep["단계"]["신고서 PDF"] == "만듦":
            out.append("전자신고 파일 없이 신고하려면 홈택스에 사람이 로그인해 %s 순서로 화면에 직접 입력한다" % GUIDE_FILE)
        out.append("홈택스·위택스 로그인과 제출은 사람이 한다. 신고서와 전자신고 파일이 만들어진 뒤에 한다")
        return out
    out.append("%s, %s 과 %s 을 계약서·증빙과 대조해 검토한다. 신고 전 최종 판단은 세무 전문가가 한다"
               % (forms.OUT_NATIONAL, forms.OUT_LOCAL, RV_FILE))
    if sent:
        out.append("홈택스에 사람이 로그인해 양도소득세 변환파일 %s 을 올리고 형식검증과 내용검증을 돌린다. "
                   "오류가 나오면 제출하지 않고 오류 문장을 그대로 알린다" % sent["파일명"])
        out.append("형식검증이 막히면 %s 순서로 홈택스 화면에 직접 입력한다" % GUIDE_FILE)
    else:
        out.append("홈택스에 사람이 로그인해 %s 순서로 화면에 직접 입력한다. 전자신고 파일이 필요하면 전자신고 단계까지 다시 실행한다" % GUIDE_FILE)
    out.append("홈택스 형식검증·내용검증이 통과하면 사람이 제출하고 접수증을 보관한다. 에이전트는 로그인하거나 제출하지 않는다")
    out.append("%s 의 서류를 홈택스 「신고 부속·증빙서류 제출」로 올린다" % ATTACH_FILE)
    out.append("위택스에서 지방소득세(양도소득분)를 따로 신고한다. 값은 %s 에 있다" % forms.OUT_LOCAL)
    out.append("신고기한 안에 국세와 지방소득세를 납부한다")
    return out


def _bullets(xs):
    return ["- " + x for x in xs]


def confirm_md(rep):
    """신고_확인.md. 인적사항 값은 싣지 않는다."""
    L = ["# 양도소득세 신고 확인", "", "%s (종료코드 %d)" % (rep["요약"], rep["종료코드"]), ""]
    info, ed = rep["기준정보"], rep["판"]
    if info:
        L += ["기준정보 판 %s, 확인일 %s%s" % (info["판"], info["확인일"],
                                          (", 서식판 %s, 규격서 %s" % (ed.get("서식"), ed.get("규격"))) if ed else ""), ""]
    if rep["합계"]:
        L += ["산출세액 %s원, 지방소득세 %s원" % (outputs.won(rep["합계"]["산출세액"]), outputs.won(rep["합계"]["지방소득세"])), ""]
    L += ["## 단계", "", "| 단계 | 결과 |", "|---|---|"] + ["| %s | %s |" % kv for kv in rep["단계"].items()] + [""]
    if rep["알림"]:
        L += ["## 알림", ""] + _bullets(rep["알림"]) + [""]
    if rep["질문"] or (rep["다루지않음"] and rep["단계"]["계산"] != "완료"):
        L += ["## 계산 질문", "", "계산 질문 %d개, 다루지않음 %d개. 문항은 %s 에 있다." % (len(rep["질문"]), len(rep["다루지않음"]), outputs.QUESTIONS), ""]
    if rep["신고인질문"]:
        L += ["## 신고인 정보 질문", ""]
        L += ["- [%s] %s%s" % (q["문항"], ("자산 %s: " % q["자산"]) if q.get("자산") else "", q["내용"]) for q in rep["신고인질문"]]
        L += [""]
    if rep["검산"]:
        L += ["## 계산 검산", ""] + _bullets(rep["검산"]) + [""]
    if rep["서식검산"] is not None:
        L += ["## 서식 검산", ""] + (_bullets(rep["서식검산"]) if rep["서식검산"] else ["통과"]) + [""]
    sent = rep["전자신고"]
    if sent is not None:
        L += ["## 전자신고 검증", ""] + (_bullets(sent["검증"]) if sent["검증"] else ["통과 (%s)" % sent["파일명"]]) + [""]
        if sent["경고"]:
            L += ["경고", ""] + _bullets(sent["경고"]) + [""]
    if rep["확인사항"]:
        L += ["## 확인사항", ""] + _bullets(rep["확인사항"]) + [""]
    if rep["경고"]:
        L += ["## 경고", ""] + _bullets(rep["경고"]) + [""]
    if sent is not None and not sent["검증"]:
        L += ["## 규격서 미확인 칸", "", "규격서 원문만으로 정하지 못해 홈택스 형식검증으로 확정할 칸이다. 형식검증 오류가 이 칸에서 나오면 운영자에게 알린다.", ""]
        L += _bullets(_unconfirmed()) + [""]
    if rep["파일"]:
        L += ["## 만든 파일", ""] + _bullets([os.path.basename(p) for p in rep["파일"]]) + [""]
        if any(os.path.basename(p) == RV_FILE for p in rep["파일"]):
            L += ["이 가운데 %s, 신고서 PDF, 전자신고 파일, %s, %s 에는 인적사항이 들어 있다. 공유하지 않는다." % (RV_FILE, GUIDE_FILE, ATTACH_FILE), ""]
    L += ["## 사람이 할 일", ""] + ["%d. %s" % (i, x) for i, x in enumerate(rep["사람이할일"], 1)] + ["", TAIL, ""]
    return "\n".join(L)


def make(facts, filer, out, today=None, rules_dir=None, upto=EFILE):
    """신고서·전자신고 파일을 out 폴더에 만들고 보고(dict)를 돌려준다. 예외 대신 보고의 종료코드로 알린다.
    예상하지 못한 예외도 잡아 종료코드 1 로 돌려주고 신고_확인.md 를 쓴다(트레이스백은 표준오류, 보고에는 예외 형 이름만).

    facts 는 사실관계 dict 또는 파일 경로, filer 는 신고인 JSON 파일 경로(dict 도 받는다). upto 가 FORMS 면 신고서 PDF 까지,
    EFILE 이면 전자신고 파일까지 만든다. 보고의 키: 종료코드, 상태, 요약, 단계, 파일(경로), 기준정보, 판, 합계, 질문, 다루지않음,
    신고인질문, 검산, 서식검산(하지 않았으면 None), 전자신고(하지 않았으면 None, 했으면 파일명·검증·경고), 확인사항, 경고, 알림,
    사람이할일. 보고와 신고_확인.md 에는 인적사항 값을 싣지 않는다.
    """
    rep = _report(out, upto)
    try:
        _pipeline(rep, facts, filer, out, today, rules_dir, upto)
    except _Stop:
        pass
    except OSError as e:
        name = os.path.basename(os.fspath(e.filename)) if e.filename else os.path.basename(os.path.normpath(out))
        if _inside(e.filename, out):
            rep.update(종료코드=4, 상태="쓰기실패", 요약="출력 파일을 쓰지 못했다")
            rep["알림"].append("출력 파일을 쓰지 못했다: %s (%s). 파일을 닫고 다시 실행한다" % (name, _why(e)))
        else:       # 스킬의 서식 원본·매핑·레이아웃 같은 기준 파일을 읽지 못했다
            rep.update(종료코드=3, 상태="기준정보오류", 요약="기준 파일을 읽지 못해 멈췄다")
            rep["알림"].append("기준 파일을 읽지 못했다: %s (%s)" % (name, _why(e)))
    except Exception as e:      # 예상하지 못한 오류. 확인 문서 없이 제출용 파일만 남지 않게 한다
        traceback.print_exc(file=sys.stderr)     # 운영자가 볼 수 있게 표준오류에 남긴다
        kind = type(e).__name__                  # 예외 문장에는 인적사항이 실릴 수 있어 형 이름만 적는다
        left = _drop_submittable(rep, out)
        rep.update(종료코드=1, 상태="오류", 요약="예상하지 못한 오류(%s)로 멈췄다. 이 실행의 결과로 신고하지 않는다" % kind)
        rep["알림"].append("예상하지 못한 오류(%s)로 멈췄다. 이번 실행이 만든 신고서 PDF 와 전자신고 파일은 지웠다. "
                         "오류 기록은 표준오류에 있다" % kind)
        if left:
            rep["알림"].append("지우지 못한 파일: %s. 이번 실행이 끝까지 가지 못했으니 신고에 쓰지 않는다" % ", ".join(left))
        for name in ("신고서 PDF", "전자신고 파일"):
            if rep["단계"][name].startswith("만듦"):
                rep["단계"][name] = "지움(예상하지 못한 오류)"
        if rep["전자신고"] and not rep["전자신고"]["검증"]:
            rep["전자신고"]["검증"] = ["예상하지 못한 오류로 전자신고 파일을 지웠다"]
    rep["사람이할일"] = _todo(rep)
    try:
        os.makedirs(out, exist_ok=True)
        path = _write_text(os.path.join(out, CONFIRM_FILE), confirm_md(rep))
        rep["파일"].append(path)
    except OSError as e:
        if rep["종료코드"] != 4:
            rep.update(종료코드=4, 상태="쓰기실패", 요약="출력 파일을 쓰지 못했다")
            rep["알림"].append("출력 파일을 쓰지 못했다: %s (%s). 파일을 닫고 다시 실행한다" % (CONFIRM_FILE, _why(e)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="양도소득세 신고서 PDF, 전자신고 파일, 홈택스 입력 안내서를 만든다")
    ap.add_argument("--사실관계", required=True)
    ap.add_argument("--신고인", required=True, help="신고인 JSON 파일 경로(인적사항)")
    ap.add_argument("--출력", required=True)
    ap.add_argument("--오늘", type=iso_date)
    ap.add_argument("--rules")
    a = ap.parse_args(argv)
    rep = make(a.사실관계, a.신고인, a.출력, today=a.오늘, rules_dir=a.rules)
    code = rep["종료코드"]
    print("%s (종료코드 %d)" % (rep["요약"], code), file=sys.stderr if code == 4 else sys.stdout)
    for note in rep["알림"]:
        print(note, file=sys.stderr if code == 4 else sys.stdout)
    if code != 4:
        if rep["합계"]:
            print("산출세액 %s원, 지방소득세 %s원" % (outputs.won(rep["합계"]["산출세액"]), outputs.won(rep["합계"]["지방소득세"])))
        print("자세한 내용은 %s 에 적었다" % CONFIRM_FILE)
    return code


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")       # Windows 기본 cp949 로 깨지지 않게 한다
        except AttributeError:
            pass
    sys.exit(main())
