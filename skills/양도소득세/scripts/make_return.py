# -*- coding: utf-8 -*-
"""사실관계 JSON 과 신고인 JSON 으로 신고서 PDF(양도소득세 별지 제84호, 지방소득세 별지 제40호의11)를 만든다.

  python scripts/make_return.py --사실관계 facts.json --신고인 신고인.json --출력 out/ [--오늘 YYYY-MM-DD] [--rules rules/]

차례: 계산(run.py 와 같은 outputs.calculate_to) → 과세 자산이 있는지 → 신고인 정보 검사(filing.load) → 신고인 질문 F01~F08
(filing.questions) → 작성일이 오늘이나 양도일보다 앞서는지 → 신고값(return_values.build, 메모리에만) → 서식 검산(forms_check.check)
→ 신고서 PDF(forms.render). 앞 단계가 막히면 뒤 단계는 하지 않는다.

출력 폴더에는 양도소득세_신고서.pdf, 지방소득세_신고서.pdf, 양도소득세_계산근거.xlsx 만 남긴다. 결과 JSON, 검토 문서, 질문 문서,
신고값 JSON, 확인 문서는 쓰지 않는다. 확인 문서에 적을 내용(요약, 단계, 알림, 질문, 신고인 질문, 검산, 서식 검산, 확인사항, 경고,
만든 파일, 사람이 할 일)은 화면에 내고(main 이 confirm_md 를 낸다) make 가 돌려주는 보고(MCP 응답)에 싣는다.

종료코드
  0 완료
  1 서식 검산 실패(엔진 검산 실패, 신고값이나 신고서 PDF 를 만들지 못한 경우, 예상하지 못한 오류 포함). 결과를 신고에 쓰지 않는다.
    예상하지 못한 오류면 이미 만든 신고서 PDF 를 지운다
  2 질문(계산 질문, 신고인 질문 F01~F08) 또는 다루지않음(신고 범위가 아닌 건, 전액 비과세 자산뿐이라 과세 자산이 없는 건,
    가산세를 계산하지 못한 확정신고, 읽을 수 없거나 형식이 틀린 입력 파일, 작성일이 오늘이나 양도일보다 앞선 신고인 파일)
  3 기준정보·서식판 오류
  4 출력 파일 쓰기 실패(이전 파일을 다른 프로그램이 열어 둔 경우 등. 파일을 닫고 다시 실행한다)

작성일(신고인 파일의 신고.작성일)은 신고서를 제출하는 날이다. 신고기한 판정이 작성일만 보므로 작성일이 오늘보다 앞서면
신고값을 만들지 않고 종료코드 2 로 멈춘다. 오늘은 --오늘 로 준 날이고, 없으면 계산이 쓴 한국 시간 오늘이다.

같은 출력 폴더에 다시 실행하면 이 도구가 쓰는 이름의 파일만 먼저 지운다(yangdo/outputs.py 의 clear_all). 다른 파일은 건드리지 않는다.
전액 비과세 자산은 신고서에 넣지 않는다(return_values). 확정신고의 납부일은 작성일로 본다.
인적사항(성명, 주민등록번호, 주소, 전화, 계좌, 양수인, 자산 지번, 매도인 성명)은 신고서 PDF 에만 들어간다. 화면 출력과
make 가 돌려주는 값(MCP 응답)에는 싣지 않는다. 홈택스·위택스 로그인과 제출은 사람이 한다. 이 스크립트는 파일만 만든다.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import bjd, dates, edition, filing, forms, forms_check, outputs, return_values, ruleset  # noqa: E402
from yangdo import facts as F  # noqa: E402


# 명령줄 날짜 읽기와 사실관계 파일 읽기. run.py 와 같은 것을 쓴다(진입점 스크립트끼리는 가져다 쓰지 않는다)
iso_date, read_facts = outputs.iso_date, outputs.read_facts

# 이 스크립트가 쓰는 파일 이름과 옛 전자신고 파일 이름 꼴. 지울 이름 목록은 yangdo/outputs.py 한 곳에 있고 여기서는 가져다 쓴다
# (run.py 와 MCP 계산 도구도 같은 이름을 지운다)
RV_FILE, GUIDE_FILE, ATTACH_FILE, CONFIRM_FILE = outputs.RETURN_VALUES, outputs.GUIDE, outputs.ATTACHMENTS, outputs.CONFIRM
OWN_NAMES = outputs.RETURN_NAMES
EFILE_NAME = outputs.EFILE_NAME
FORMS, EFILE = "forms", "efile"                             # 어디까지 만드는지. forms 는 신고서 PDF 까지, efile 은 전자신고 파일까지
NOT_DONE = "하지 않음"
PUBLIC_STEPS = ("계산", "신고인 정보", "신고값", "서식 검산", "신고서 PDF")     # PUBLIC 이 참인 판의 단계
STEPS = PUBLIC_STEPS
PUBLIC_NOT_MADE = "신고서를 만들지 않았다"
NOT_MADE = PUBLIC_NOT_MADE
NO_TAXABLE = return_values.NO_TAXABLE                       # 전액 비과세 자산뿐인 건의 요약 줄
# 같은 해 다른 양도가 있다고 답했는데(사실관계 연간.다른양도, 문항 P05) 기신고 금액은 없는 건. 문항이 팔 예정인 건도 받아서 막지 않고 알린다
OTHER_SALE = ("같은 해 다른 양도가 있다고 답했다(사실관계 연간.다른양도). 그 양도는 이 계산에 들어가지 않았다. "
              "그 양도를 먼저 신고했다면 이 신고서의 기본공제와 세액이 달라진다")
OTHER_SALE_TODO = ("같은 해 다른 양도를 먼저 신고했는지 확인한다. 먼저 신고했다면 기본공제와 세액이 달라지니 이 실행의 값으로 신고하지 않고, "
                   "사실관계 연간.기신고 에 그 신고의 금액을 적어 다시 실행한다")
TAIL = outputs.TAIL                                         # 검토 문서와 같은 맺음말


def _dedupe(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


_why = outputs.why


def _inside(path, folder):
    """path 가 folder 안(또는 folder 자신)인지. 경로가 없으면 쓰던 파일로 본다."""
    if not path:
        return True
    try:
        a, b = os.path.realpath(os.fspath(path)), os.path.realpath(folder)
        return os.path.normcase(a) == os.path.normcase(b) or os.path.normcase(a).startswith(os.path.normcase(b) + os.sep)
    except (TypeError, ValueError):
        return True


_is_tmp_dir, _clear_order = outputs.is_tmp_dir, outputs.clear_order


def clear_previous(out):
    """이전 실행이 남긴 파일을 지운다. (알릴 문장 목록, 첫 OSError 또는 None).

    지울 이름과 차례는 outputs.clear_all 에 있다. 이 스크립트가 쓰는 이름, 옛 전자신고 파일, 앞선 실행의 임시 폴더를 먼저 지우고
    run.py 의 파일(통합 문서부터)을 마지막에 지운다. 하나가 막혀도 나머지를 끝까지 지운다. 지우지 못한 파일이 있으면 처음 난
    OSError 를 돌려주고, 부른 쪽이 종료코드 4 로 멈춘다. 지우지 못한 임시 폴더는 문장으로 알린다. 폴더 안의 다른 파일은 그대로 둔다.
    """
    _, first = outputs.clear_all(out)
    # 지우지 못해 남은 임시 폴더와, 다른 파일이 함께 있어 지우지 않은 임시 폴더 꼴의 폴더를 같은 함수로 알린다
    return outputs.tmp_left_notes(out), first


def _leftovers(out):
    """출력 폴더에 남아 있는, 이 스크립트와 run.py 가 쓰는 이름의 파일(신고_확인.md 제외)."""
    return outputs.stale_names(out, skip=(CONFIRM_FILE,))


def _clear_all(rep, out):
    """이전 결과를 지운다. 제출용 파일부터 지우고 run.py 의 파일(통합 문서부터)은 마지막에 지운다.

    지우지 못한 것이 있으면 남은 파일 이름을 이전 실행의 것이라고 알림에 적고 처음 난 OSError 를 다시 낸다(종료코드 4).
    """
    notes, first = clear_previous(out)   # 계산 결과는 통합 문서부터 지운다. 엑셀이 열어 두었으면 계산 결과 파일은 그대로 남는다
    rep["알림"] += notes
    if first is not None:
        stale = _leftovers(out)
        if stale:
            rep["알림"].append(outputs.STALE_NOTE % ", ".join(stale))
        raise first


def _left_submittable(out):
    """출력 폴더에 남은 신고서 PDF 와 제출용 이름의 전자신고 파일의 이름. 종료코드 4 로 끝날 때 쓰다 만 파일을 알리는 데 쓴다."""
    try:
        names = sorted(os.listdir(out))
    except OSError:
        return []
    return [n for n in names if _clear_order(n) in (0, 2) and (n in OWN_NAMES or EFILE_NAME.match(n)) and os.path.isfile(os.path.join(out, n))]


def _tell_left_files(rep, out):
    """종료코드 4 에서 신고서 PDF 나 전자신고 파일이 남았으면 그 이름과 쓰지 말라는 말을 알림에 적는다(종료코드 1·3 과 같은 말을 한다)."""
    head, tail = outputs.STALE_NOTE.split("%s")        # 이전 실행의 것으로 이미 알린 이름은 쓰다 만 파일로 다시 알리지 않는다
    told = {n for x in rep["알림"] if x.startswith(head) for n in x[len(head):].split(tail[:2])[0].split(", ")}
    left = [n for n in _left_submittable(out) if n not in told]
    if left:
        rep["알림"].append("출력 폴더에 쓰다 만 신고서 PDF 나 전자신고 파일이 남아 있다: %s. 이번 실행이 끝까지 가지 못했으니 "
                         "다시 실행하기 전에는 쓰지 않는다" % ", ".join(left))


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
        if not (_clear_order(name) in (0, 2) and (name in OWN_NAMES or EFILE_NAME.match(name)) and os.path.isfile(path)):
            continue
        try:
            os.remove(path)
        except OSError:
            pass
        if os.path.lexists(path):
            left.append(name)
    rep["파일"] = [x for x in rep["파일"] if os.path.exists(x)]
    return left


def _not_made():
    """신고서를 만들지 않았다는 문장. PUBLIC 이 참이면 전자신고 파일이 없어 신고서만 말한다."""
    return PUBLIC_NOT_MADE if edition.PUBLIC else NOT_MADE


def _report(out, upto):
    return {"종료코드": 0, "상태": "완료", "요약": "", "범위": upto, "출력": out,
            "단계": {name: NOT_DONE for name in (PUBLIC_STEPS if edition.PUBLIC else STEPS)}, "파일": [], "기준정보": None, "판": None, "합계": None,
            "질문": [], "다루지않음": [], "신고인질문": [], "검산": [], "서식검산": None, "전자신고": None,
            "확인사항": [], "경고": [], "알림": [], "사람이할일": [], "안내서머리": None, "보류사유": [], "가산세": None, "분납": None, "작성일고침": None,
            "제외자산": [], "과세자산없음": False}


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
        words = outputs.question_counts(res)        # 요약, 단계 칸, 확인 문서의 계산 질문 절이 같은 말을 쓴다(run.py 도 같다)
        summary = words if edition.PUBLIC else "%s. %s 에 적었다" % (words, outputs.QUESTIONS)     # 공개본은 질문.md 를 쓰지 않는다
        _stop(rep, 2, "질문" if res["질문"] else "다루지않음", summary, "계산", words)
    rep["합계"] = {k: res["계산"]["합계"][k] for k in ("산출세액", "지방소득세")}
    if res["상태"] != "완료":
        _stop(rep, 1, "검산실패", "계산 검산 실패 %d건. 이 결과를 신고에 쓰지 않는다" % len(res["검산"]), "계산", "검산 실패 %d건" % len(res["검산"]))
    step["계산"] = "완료"
    return facts, res


def _taxable(rep, res):
    """과세 자산이 하나도 없으면(전액 비과세 자산뿐) 신고인 파일을 읽기 전에 끝낸다. 신고서를 만들지 않으니 신고인 정보가 필요 없다."""
    left = return_values.exempt_ids(res)
    if len(left) < len(res["계산"]["자산"]):
        return
    rep.update(과세자산없음=True, 제외자산=left)
    what = "신고서" if edition.PUBLIC else "신고서·전자신고 파일"
    rep["다루지않음"] = rep["다루지않음"] + [{"자산": None, "내용": "전액 비과세 자산뿐인 건의 %s" % what, "계획": "없음"}]
    made = "신고서 PDF 를" if edition.PUBLIC else "신고값과 신고서 PDF, 전자신고 파일을"
    _stop(rep, 2, "다루지않음", NO_TAXABLE, "신고값", "만들지 않음(과세 자산 없음)",
          "전액 비과세로 판정한 자산(%s)뿐이라 %s. %s 만들지 않았다. 비과세 요건을 과세관청이 "
          "달리 보면 그 자산은 신고하지 않은 것이 된다. 비과세 판정은 세무 전문가와 확인한다" % (", ".join(left), NO_TAXABLE, made))


def _old_return_date(f, res):
    """작성일이 오늘보다 앞서면 알릴 문장, 아니면 None. 오늘은 계산이 쓴 날짜다(--오늘, 없으면 한국 시간 오늘).

    작성일이 없거나 날짜로 읽을 수 없으면 None 이다. 그 경우는 신고인 질문 F05 나 신고값 단계가 알린다.
    """
    made, today = (f.get("신고") or {}).get("작성일"), (res.get("기준정보") or {}).get("오늘")
    try:
        late = dates.to_date(made) < dates.to_date(today)
    except (ValueError, TypeError):
        return None
    if not late:
        return None
    return ("신고인 파일의 신고.작성일 %s 이 오늘 %s 보다 앞선다. 작성일은 신고서를 제출하는 날이다. "
            "제출할 날짜로 고쳐 다시 실행한다" % (made, today))


def _return_before_sale(f, res):
    """작성일이 가장 늦은 양도일보다 앞서면 알릴 문장, 아니면 None.

    신고값 단계(return_values.build)도 같은 경우에 멈추지만 다른 내부 오류와 같은 ValueError 라 입력 오류로 가르지 못한다.
    그래서 신고값을 만들기 전에 여기서 본다. 날짜를 읽을 수 없으면 None 이고 그때는 신고값 단계가 알린다.
    """
    made = (f.get("신고") or {}).get("작성일")
    try:
        left_out = set(return_values.exempt_ids(res))      # 신고값 단계처럼 신고서에 넣지 않는 전액 비과세 자산은 보지 않는다
        last = max(r["판정"]["양도일"] for r in res["계산"]["자산"] if r["id"] not in left_out)
        early = dates.to_date(made) < dates.to_date(last)
    except (ValueError, TypeError, KeyError):
        return None
    if not early:
        return None
    return ("신고인 파일의 신고.작성일 %s 이 양도일 %s 보다 앞선다. 작성일은 신고서를 제출하는 날이라 양도일보다 앞설 수 없다. "
            "날짜를 고쳐 다시 실행한다" % (made, last))


def _filer(rep, filer, facts, res):
    step = rep["단계"]
    try:
        f = filing.load(filer)
    except filing.FilingError as e:
        _stop(rep, 2, "입력오류", "신고인 파일을 읽지 못했거나 형식이 틀렸다", "신고인 정보", "형식 오류", "신고인 정보: %s" % e)
    for w in f.get("_경고") or []:
        (rep["알림"] if w.startswith(filing.UNKNOWN_KEYS_HEAD) else rep["경고"]).append(w)    # 모르는 키는 알림으로 알린다
    # filing.questions 의 efile_dir 는 주지 않는다. 이 진입점은 efile 폴더를 따로 받지 않고 신고값 생성, 전자신고 파일, 검증기가
    # 모두 기본 폴더(efile/)를 읽으므로 질문도 같은 코드표와 법정동코드 표를 본다
    qs = _reference(rep, "신고인 정보", lambda: filing.questions(f, facts, res))
    old = _old_return_date(f, res)
    if qs:
        rep["신고인질문"] = qs      # 작성일도 고쳐야 하면 함께 알려 신고인 파일을 한 번에 고치게 한다
        _stop(rep, 2, "질문", "신고인 정보 질문 %d개. 신고인 파일(F07 은 사실관계)을 채운 뒤 다시 실행한다" % len(qs),
              "신고인 정보", "질문 %d개" % len(qs), old)
    step["신고인 정보"] = "갖춤"
    if old:
        _stop(rep, 2, "입력오류", "작성일이 오늘보다 앞서 신고값을 만들지 않았다", "신고값", "만들지 않음(작성일이 오늘보다 앞섬)", old)
    early = _return_before_sale(f, res)
    if early:
        _stop(rep, 2, "입력오류", "작성일이 양도일보다 앞서 신고값을 만들지 않았다", "신고값", "만들지 않음(작성일이 양도일보다 앞섬)", early)
    return f


def _values(rep, res, facts, f, rules_dir):
    try:
        rv = _reference(rep, "신고값", lambda: return_values.build(res, facts, f, rules_dir=rules_dir))
    except return_values.NoTaxableAsset:      # _taxable 이 먼저 걸러 여기 오지 않는다. 와도 같은 문장으로 끝낸다
        _taxable(rep, res)
        raise
    except return_values.FinalPeriodNotStarted as u:
        # 다루지 않는 거래가 아니라 작성일을 고치면 되는 입력이다. 맨 위 줄, 알림, 사람이 할 일이 같은 말을 한다
        fix = ("신고인 파일의 신고.작성일을 확정신고 기간(%s부터 %s까지) 안의 신고·납부 예정일로 고쳐 다시 실행한다"
               % (u.start.isoformat(), u.end.isoformat()))
        rep["작성일고침"] = fix
        _stop(rep, 2, "입력오류", "작성일이 확정신고 기간 전이라 신고값을 만들지 않았다. %s" % fix, "신고값", "작성일 오류", str(u))
    except return_values.Unsupported as u:
        plan = outputs.plan_text(u.계획)
        text = str(u).rstrip(". ")
        rep["다루지않음"] = rep["다루지않음"] + [{"자산": None, "내용": str(u), "계획": u.계획}]
        # 신고값 모듈의 문장이 이미 어느 계획에서 다루는지 말했으면 같은 말을 한 번 더 붙이지 않는다
        _stop(rep, 2, "다루지않음", "신고 범위가 아니라 신고값을 만들지 않았다", "신고값", "다루지않음",
              text if plan in text else "%s. %s" % (text, plan))
    except return_values.InputError as e:
        _stop(rep, 2, "입력오류", "사실관계 파일의 값이 틀려 신고값을 만들지 않았다", "신고값", "사실관계 오류", str(e))
    except filing.FilingError as e:
        _stop(rep, 2, "입력오류", "신고인 파일의 값이 틀려 신고값을 만들지 않았다", "신고값", "신고인 정보 오류", "신고인 정보: %s" % e)
    except ValueError as e:
        _stop(rep, 1, "신고값실패", "신고값을 만들지 못했다", "신고값", "만들지 못함", "신고값을 만들지 못했다. %s" % e)
    rep["단계"]["신고값"] = "만듦"
    rep["판"] = rv.get("판")
    pen = rv.get("가산세")
    if isinstance(pen, dict) and pen.get("계산") and pen.get("계"):      # 가산세를 넣은 확정신고. 납부일(작성일)과 금액만 싣는다
        local = pen.get("지방") or {}
        rep["가산세"] = {"계": pen["계"], "납부일": pen.get("납부일"), "감면적용금액": pen.get("무신고_감면적용"),
                      "지방계": local.get("계") or 0}
        # 무신고가산세를 감면 없이 넣었다. 금액이 절반으로 달라질 수 있는 문장이라 확인사항에만 두지 않고 알림에도 올린다(국세, 지방소득세)
        rep["알림"] += [x for x in (pen.get("감면안내"), local.get("감면안내")) if x]
        # 요약에도 가산세와 납부할 세액을 싣는다(신고서 본지 ⑱, 지방 서식 ⑮). 값은 신고값의 값을 그대로 읽는다
        if rep["합계"] is not None:
            nat, loc = rv["본지"]["열"]["합계"], rv["지방"]["열"]["합계"]
            rep["합계"].update(가산세=nat["가산세"], 납부할세액=nat["납부할세액"], 지방가산세=loc["가산세"], 지방납부할세액=loc["납부할세액"])
    if rv.get("분납기한"):        # 분납할 세액이 있다. 금액은 신고값의 값이고 새로 세지 않는다
        total = rv["본지"]["열"]["합계"]
        rep["분납"] = dict(rv["분납기한"], 분납액=total["분납"], 작성일내=total["신고기한내납부"],
                         지방=rv["지방"]["열"]["합계"]["납부할세액"])
    if (facts.get("연간") or {}).get("다른양도") is True:      # 기신고 금액이 있으면 위에서 다루지않음으로 끝났다
        rep["알림"].append(OTHER_SALE)
    left = [x["자산"] for x in rv.get("제외자산") or []]
    if left:        # 전액 비과세 자산을 신고서에서 뺐다. 신고하지 않은 것이 될 수 있는 문장이라 확인사항에만 두지 않고 알림에도 올린다
        rep["제외자산"] = left
        rep["알림"].append(return_values.left_out_note(left))
    return rv


def withheld(rv, res):
    """신고값을 만든 뒤 신고서와 전자신고 파일을 만들지 않는 사유 목록. 비면 만든다. 사유를 더하거나 걷어낼 때는 이 함수만 고친다.
    전액 비과세 자산은 사유가 아니다. 신고값이 그 자산을 빼고 과세 자산만 싣는다(과세 자산이 없는 건은 _taxable 이 먼저 끝낸다).

    사유마다 {"이름": 단계 표에 적는 짧은 이름, "까닭": 요약 줄의 앞 구절, "알림": 신고_확인.md 와 보고에 적는 문장,
    "안내": 입력 안내서·부속서류 맨 위에 붙이는 문장, "다루지않음": 보고의 다루지않음에 더할 항목}.
    """
    out = []
    pen = rv.get("가산세")
    if isinstance(pen, dict) and pen.get("계산") is False:
        # 확정신고의 가산세를 계산하지 못한 건. 사유는 penalty.Unsupported 의 문장이다(자산 id 와 금액만 담는다)
        why = str(pen.get("사유") or "").rstrip(". ")
        # 공개본은 신고값과 입력 안내서를 쓰지 않는다. 참고용으로 남는 것은 계산근거 워크북이다
        ref = "계산근거 워크북은" if edition.PUBLIC else "계산 결과, 신고값, 입력 안내서는"
        out.append({
            "이름": "확정신고 가산세", "까닭": "확정신고의 가산세를 계산하지 못해",
            "알림": "확정신고의 가산세를 계산하지 못해 %s. 계산하지 못한 까닭: %s. 예정신고를 하지 않은 확정신고에는 예정신고 "
                    "무신고가산세와 납부지연가산세가 붙는데, 이 건은 가산세가 빠져 납부할 세액이 실제보다 적게 나온다. "
                    "가산세를 더한 신고는 세무 전문가와 한다. %s 참고용으로 냈다" % (_not_made(), why, ref),
            "안내": "확정신고의 가산세를 계산하지 못해 %s. 아래는 참고용이고 납부할 세액에 가산세(예정신고 무신고, 납부지연)가 "
                    "빠져 있다." % _not_made(),
            "다루지않음": [{"자산": None, "내용": "확정신고의 가산세(예정신고 무신고가산세, 납부지연가산세). %s" % why,
                        "계획": pen.get("계획") or "없음"}]})
    return out


def _forms_and_file(rep, rv, res, facts, out, rules_dir, upto):
    """서식 검산 → 신고서 PDF. 막힌 곳에서 보고에 적고 돌아온다.
    서식 검산은 확정신고 가산세를 다시 계산할 때 사실관계의 허가일을 읽는다."""
    step = rep["단계"]
    fails = forms_check.check(rv, res, rules_dir=rules_dir, facts=facts)
    rep["서식검산"] = fails
    if fails:
        step["서식 검산"] = "실패 %d건" % len(fails)
        rep.update(종료코드=1, 상태="서식검산실패", 요약="서식 검산 실패 %d건. %s" % (len(fails), _not_made()))
        return
    step["서식 검산"] = "통과"
    held = withheld(rv, res)
    if held:
        rep["알림"] += [w["알림"] for w in held]
        rep["다루지않음"] = rep["다루지않음"] + [x for w in held for x in w["다루지않음"]]
        rep["안내서머리"] = " ".join(w["안내"] for w in held)
        rep["보류사유"] = [w["이름"] for w in held]
        rep.update(종료코드=2, 상태="다루지않음", 요약="%s %s" % (", ".join(w["까닭"] for w in held), _not_made()))
        for name in [n for n in ("신고서 PDF", "전자신고 파일") if n in step]:
            step[name] = "만들지 않음(%s)" % ", ".join(w["이름"] for w in held)
        return
    try:
        rep["파일"] += forms.render(rv, out)
    except ValueError as e:          # 칸 넘침(forms_pdf.Overflow), 코드표·매핑에 없는 값. 문장에는 칸 이름만 있다
        step["신고서 PDF"] = "만들지 못함"
        rep["알림"].append("신고서 PDF 를 만들지 못했다. %s" % e)
        rep.update(종료코드=1, 상태="서식실패",
                   요약="신고서 PDF 를 만들지 못했다" + ("" if edition.PUBLIC else ". 전자신고 파일도 만들지 않았다"))
        return
    step["신고서 PDF"] = "만듦"
    if upto != EFILE:
        if "전자신고 파일" in step:
            step["전자신고 파일"] = "요청하지 않음"
        return


def _pipeline(rep, facts, filer, out, today, rules_dir, upto):
    os.makedirs(out, exist_ok=True)
    _clear_all(rep, out)
    facts, res = _calculate(rep, facts, out, today, rules_dir)
    _taxable(rep, res)
    f = _filer(rep, filer, facts, res)
    rv = _values(rep, res, facts, f, rules_dir)
    try:
        _forms_and_file(rep, rv, res, facts, out, rules_dir, upto)
    finally:
        # 신고값은 forms.render 가 확인사항을 덧붙인 뒤의 값으로 쓴다(render 전에 끝났으면 그때의 값)
        notes = rep["확인사항"] + list(rv.get("확인사항") or [])
        # 전자신고 파일을 만들지 않았으면(PUBLIC 이 참이면 늘) 그 파일의 칸 번호·형식검증 문장은 싣지 않는다
        if rep["보류사유"] or edition.PUBLIC:
            notes = [x for x in notes if not return_values.is_file_only_note(x)]
        rep["확인사항"] = _dedupe(notes)
    if rep["종료코드"] == 0:    # 신고값은 메모리에만 둔다
        rep["요약"] = "신고서 PDF 두 벌(%s, %s)을 만들었다" % (forms.OUT_NATIONAL, forms.OUT_LOCAL)


def _todo(rep):
    """사람이 할 일. 홈택스·위택스 로그인과 제출은 사람이 한다. 같은 해 다른 양도를 알린 실행이면 그 확인을 맨 앞에 둔다."""
    steps = _todo_steps_public(rep)
    return ([OTHER_SALE_TODO] if OTHER_SALE in rep["알림"] else []) + steps


def _todo_payment(rep):
    """종료코드 0 의 사람이 할 일 가운데 지방소득세 신고와 납부 줄. 두 판이 같은 줄을 쓴다."""
    out = []
    local = "위택스에서 지방소득세(양도소득분)를 따로 신고한다. 값은 %s 에 있다" % forms.OUT_LOCAL
    if rep["가산세"] and rep["가산세"]["지방계"]:        # 작성일이 지방소득세 예정신고기한 이전이면 지방소득세 가산세가 없어 이 문장을 붙이지 않는다
        local += (". 지방소득세 가산세는 지방소득세 예정신고기한과 끝수를 가정해 계산했다. 위택스 화면이 계산한 가산세와 다르면 "
                  "위택스 값을 따른다")
    out.append(local)
    if rep["분납"]:
        out += _installment_todo(rep)
    elif rep["가산세"]:
        out.append("국세와 지방소득세는 작성일 %s 에 납부한다. 납부지연가산세는 그 날 내는 것으로 셌다. 다른 날 내면 신고인 파일의 "
                   "작성일을 그 날로 바꿔 다시 만든다" % rep["가산세"]["납부일"])
    else:
        out.append("신고기한 안에 국세와 지방소득세를 납부한다")
    return out


# 사람이 할 일의 고정 문장. 전자신고 파일, 입력 안내서, 부속서류 목록 이야기가 없다
PUBLIC_LOGIN = "홈택스·위택스 로그인과 제출은 사람이 한다. 신고서가 만들어진 뒤에 한다"
PUBLIC_FILE = ("홈택스에 사람이 로그인해 %s 의 값으로 양도소득세를 신고하고 접수증을 보관한다. 에이전트는 로그인하거나 제출하지 않는다"
               % forms.OUT_NATIONAL)
PUBLIC_EVIDENCE = ("취득가액과 필요경비를 보이는 증빙(매매계약서, 영수증, 세금계산서 등)을 보관한다. 신고할 때 함께 낼 서류는 "
                   "세무 전문가와 확인한다")


def _todo_steps_public(rep):
    """사람이 할 일(PUBLIC 이 참인 판). 전자신고 파일, 입력 안내서, 부속서류 목록 줄이 없다.
    신고는 신고서 PDF 의 값으로 사람이 한다."""
    code = rep["종료코드"]
    if code != 0:
        if code == 2 and rep["상태"] == "다루지않음":
            if rep["과세자산없음"]:
                return ["과세 자산이 없어 신고서를 만들지 않았다. 전액 비과세로 판정한 자산(%s)의 비과세 요건을 보이는 "
                        "증빙(매매계약서, 보유 기간과 거주 기간, 세대의 주택 수를 확인할 수 있는 서류)을 보관하고, 비과세 판정을 "
                        "세무 전문가와 확인한다. 판정이 달라지면 사실관계를 고쳐 다시 실행한다" % ", ".join(rep["제외자산"])]
            if rep["보류사유"]:
                return ["신고서가 없다(%s). 이 사유를 세무 전문가와 확인한다. 이 스킬은 이 건의 신고서를 만들지 않으니 "
                        "참고용으로 낸 계산근거 워크북의 값으로 신고하지 않는다" % ", ".join(rep["보류사유"])]
            return ["이 건은 이 스킬이 다루지 않는 경우라 신고서가 없다. 알림에 적힌 사유를 세무 전문가와 확인한다"]
        if rep["작성일고침"]:
            return [rep["작성일고침"], PUBLIC_LOGIN]
        asked = {"질문": "위 질문에 답을 채운 뒤 다시 실행한다. 계산 질문은 사실관계 파일에, 신고인 정보 질문은 신고인 파일에 채운다(F07 은 사실관계 파일)",
                 "입력오류": "알림의 문장대로 입력 파일을 고친 뒤 다시 실행한다"}
        failed = ("이 실행의 결과로 신고하지 않는다. 표준오류에 나온 오류 기록과 함께 운영자에게 알린다" if rep["상태"] == "오류" else
                  "검산 실패 문장을 확인한다. 이 실행의 결과로 신고하지 않는다. 입력이 틀렸으면 고쳐서 다시 실행하고, 아니면 운영자에게 알린다")
        first = {1: failed,
                 2: asked.get(rep["상태"], asked["질문"]),
                 3: "기준정보·서식판 문제는 운영자에게 알린다. 사용자 작업에서 고치지 않는다",
                 4: "출력 폴더의 파일을 연 프로그램(엑셀, PDF 보기 등)을 닫고 같은 명령을 다시 실행한다"}[code]
        return [first, PUBLIC_LOGIN]
    out = ["%s, %s 를 계약서·증빙과 대조해 검토한다. 신고 전 최종 판단은 세무 전문가가 한다" % (forms.OUT_NATIONAL, forms.OUT_LOCAL)]
    if rep["가산세"] and rep["가산세"]["감면적용금액"] is not None:
        out.append("예정신고분을 확정신고기한까지 기한 후 신고로 내는 방법과 비교한다. 그렇게 내서 감면이 적용되면 무신고가산세가 "
                   "%s원으로 줄어든다. 이 신고서는 감면 없이 만들었다. 어느 쪽으로 신고할지 세무 전문가와 정한다"
                   % outputs.won(rep["가산세"]["감면적용금액"]))
    out += [PUBLIC_FILE, PUBLIC_EVIDENCE]
    if rep["제외자산"]:
        out.append("신고서에 넣지 않은 자산(%s)의 비과세 요건을 보이는 증빙을 보관한다. 비과세 판정은 세무 전문가와 확인한다"
                   % ", ".join(rep["제외자산"]))
    return out + _todo_payment(rep)


def _installment_todo(rep):
    """분납을 신청해 분납할 세액이 있는 실행의 납부 줄 둘. (가) 처음에 낼 금액, (나) 분납할 세액과 그 기한.
    금액은 신고값의 값이다. 기한은 dates.installment_deadline 이 센 날짜다(소득세법 제112조)."""
    inst = rep["분납"]
    won = outputs.won
    day = dates.to_date(inst["기한"])
    if rep["가산세"]:
        first = ("작성일 %s 에 국세 %s원(납부할 세액에서 분납할 세액을 뺀 금액)과 지방소득세 %s원을 납부한다. 납부지연가산세는 그 날 내는 것으로 "
                 "셌다. 다른 날 내면 신고인 파일의 작성일을 그 날로 바꿔 다시 만든다"
                 % (rep["가산세"]["납부일"], won(inst["작성일내"]), won(inst["지방"])))
    else:
        first = ("신고기한 안에 국세 %s원(납부할 세액에서 분납할 세액을 뺀 금액)과 지방소득세 %s원을 납부한다"
                 % (won(inst["작성일내"]), won(inst["지방"])))
    second = ("분납할 세액 %s원은 %s(%s요일)까지 납부한다. 소득세법 제112조의 「납부기한이 지난 후 2개월 이내」를 신고기한 %s 에서 "
              "2개월 뒤 날짜로 읽고 그날이 토요일·일요일·공휴일이면 다음 평일로 옮겼다. 이 날짜 계산은 이 스킬의 가정이다. 홈택스 분납 납부서에 적힌 기한을 따른다"
              % (won(inst["분납액"]), inst["기한"], dates.WEEKDAY_KO[day.weekday()], inst["신고기한"]))
    if inst["건너뛴날"]:
        second += ". 건너뛴 날은 %s 이다" % inst["건너뛴날"]
    return [first, second]


def _totals_line(t):
    """요약 줄. 가산세를 넣은 확정신고는 국세 납부할 세액(본지 ⑱)과 가산세, 지방소득세 납부할 세액(지방 서식 ⑮)과 가산세를 함께 적는다.
    예정신고(가산세 없음)의 줄은 그대로다."""
    won = outputs.won
    if "납부할세액" in t:
        return ("산출세액 %s원, 가산세 %s원, 납부할 세액 %s원, 지방소득세 산출세액 %s원, 지방소득세 가산세 %s원, 지방소득세 납부할 세액 %s원"
                % (won(t["산출세액"]), won(t["가산세"]), won(t["납부할세액"]), won(t["지방소득세"]), won(t["지방가산세"]), won(t["지방납부할세액"])))
    return "산출세액 %s원, 지방소득세 %s원" % (won(t["산출세액"]), won(t["지방소득세"]))


def _bullets(xs):
    return ["- " + x for x in xs]


def confirm_md(rep):
    """확인 글. 인적사항 값은 싣지 않는다. PUBLIC 이 참이면 파일로 쓰지 않고 화면에 낸다(main)."""
    public = edition.PUBLIC
    L = ["# 양도소득세 신고 확인", "", "%s (종료코드 %d)" % (rep["요약"], rep["종료코드"]), ""]
    info, ed = rep["기준정보"], rep["판"]
    if info:
        eds = (", 서식판 %s" % ed.get("서식")) if ed else ""
        L += ["기준정보 판 %s, 확인일 %s%s" % (info["판"], info["확인일"], eds), ""]
    if rep["합계"]:
        L += [_totals_line(rep["합계"]), ""]
    L += ["## 단계", "", "| 단계 | 결과 |", "|---|---|"] + ["| %s | %s |" % kv for kv in rep["단계"].items()] + [""]
    if rep["알림"]:
        L += ["## 알림", ""] + _bullets(rep["알림"]) + [""]
    if rep["질문"] or (rep["다루지않음"] and rep["단계"]["계산"] != "완료"):
        counts = outputs.QUESTION_COUNTS % (len(rep["질문"]), len(rep["다루지않음"]))
        # 질문 문서를 쓰지 않으므로 문항을 여기 싣는다(questions_md 와 같은 줄)
        body = outputs.questions_md({"질문": rep["질문"], "다루지않음": rep["다루지않음"]}).splitlines()[2:]
        section = ["## 계산 질문", "", "%s." % counts, ""] + body + [""]
        L += section
    if rep["신고인질문"]:
        L += ["## 신고인 정보 질문", ""]
        L += ["- [%s] %s%s" % (q["문항"], ("자산 %s: " % q["자산"]) if q.get("자산") else "", q["내용"]) for q in rep["신고인질문"]]
        L += [""]
    if rep["검산"]:
        L += ["## 계산 검산", ""] + _bullets(rep["검산"]) + [""]
    if rep["서식검산"] is not None:
        L += ["## 서식 검산", ""] + (_bullets(rep["서식검산"]) if rep["서식검산"] else ["통과"]) + [""]
    if rep["확인사항"]:
        L += ["## 확인사항", ""] + _bullets(rep["확인사항"]) + [""]
    if rep["경고"]:
        L += ["## 경고", ""] + _bullets(rep["경고"]) + [""]
    if rep["파일"]:
        L += ["## 만든 파일", ""] + _bullets([os.path.basename(p) for p in rep["파일"]]) + [""]
        personal = ["이 가운데 신고서 PDF 에는 인적사항이 들어 있다. 공유하지 않는다.", ""]
        if not any(os.path.basename(p) in (forms.OUT_NATIONAL, forms.OUT_LOCAL) for p in rep["파일"]):
            personal = []
        L += personal
    L += ["## 사람이 할 일", ""] + ["%d. %s" % (i, x) for i, x in enumerate(rep["사람이할일"], 1)] + ["", TAIL, ""]
    return "\n".join(L)


def make(facts, filer, out, today=None, rules_dir=None, upto=None):
    """신고서를 out 폴더에 만들고 보고(dict)를 돌려준다. 예외 대신 보고의 종료코드로 알린다.
    예상하지 못한 예외도 잡아 종료코드 1 로 돌려준다(표준오류에는 예외 형 이름과 호출 위치, 보고에는 예외 형 이름만).

    facts 는 사실관계 dict 또는 파일 경로, filer 는 신고인 JSON 파일 경로(dict 도 받는다). upto 는 어디까지 만드는지다.
    PUBLIC 이 참이면 FORMS(신고서 PDF 까지)만 받는다(다른 값은 ValueError).
    보고의 키: 종료코드, 상태, 요약, 범위(upto 값), 출력(out 값), 단계, 파일(경로), 기준정보, 판, 합계, 질문, 다루지않음,
    신고인질문, 검산, 서식검산(하지 않았으면 None), 확인사항, 경고, 알림, 사람이할일, 보류사유(신고서를 만들지 않은 사유 이름
    목록, withheld), 가산세(가산세를 넣은 확정신고면 계·납부일·감면적용금액·지방계, 아니면 None), 제외자산(신고서에 넣지 않은
    전액 비과세 자산 id 목록), 과세자산없음(전액 비과세 자산뿐이라 끝낸 실행이면 참). 보고에는 인적사항 값을 싣지 않는다.
    """
    if upto is None:
        upto = FORMS
    if edition.PUBLIC and upto != FORMS:
        raise ValueError("신고서 PDF 까지만 만든다(upto=%r)" % (upto,))
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
    except Exception as e:      # 예상하지 못한 오류. 확인 글 없이 제출용 파일만 남지 않게 한다
        kind = type(e).__name__                  # 예외 문장에는 인적사항이 실릴 수 있어 형 이름만 적는다
        # 운영자가 볼 수 있게 표준오류에 남긴다. 예외 문장은 빼고 형 이름과 호출 위치만 찍는다(MCP 서버도 같은 함수를 쓴다)
        outputs.log_call_sites(e, "예상하지 못한 오류")
        left = _drop_submittable(rep, out)
        rep.update(종료코드=1, 상태="오류", 요약="예상하지 못한 오류(%s)로 멈췄다. 이 실행의 결과로 신고하지 않는다" % kind)
        made = "신고서 PDF 는"
        rep["알림"].append("예상하지 못한 오류(%s)로 멈췄다. 이번 실행이 만든 %s %s. "
                         "오류 기록은 표준오류에 있다" % (kind, made, "지우려 했지만 일부가 남았다" if left else "지웠다"))
        if left:
            rep["알림"].append("지우지 못한 파일: %s. 이번 실행이 끝까지 가지 못했으니 신고에 쓰지 않는다" % ", ".join(left))
        # 단계 칸은 실제로 지워졌을 때만 「지움」이라 적는다. 남은 것이 있으면 지우지 못했다고 적는다
        stuck = {"신고서 PDF": any(n.startswith((forms.OUT_NATIONAL, forms.OUT_LOCAL)) for n in left),
                 "전자신고 파일": any(EFILE_NAME.match(n) or n.startswith(outputs.EFILE_TMP_PREFIX) for n in left)}
        for name in ("신고서 PDF", "전자신고 파일"):
            if rep["단계"].get(name, "").startswith("만듦"):      # 전자신고 파일 단계가 없는 판도 있다
                rep["단계"][name] = ("지우지 못함(예상하지 못한 오류, 신고에 쓰지 않는다)" if stuck[name]
                                   else "지움(예상하지 못한 오류)")
    if rep["종료코드"] == 4:
        _tell_left_files(rep, out)
    rep["사람이할일"] = _todo(rep)
    return rep


def main(argv=None):
    description = "양도소득세 신고서 PDF 를 만든다"
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--사실관계", required=True)
    ap.add_argument("--신고인", required=True, help="신고인 JSON 파일 경로(인적사항)")
    ap.add_argument("--출력", required=True)
    ap.add_argument("--오늘", type=iso_date)
    ap.add_argument("--rules")
    a = ap.parse_args(argv)
    rep = make(a.사실관계, a.신고인, a.출력, today=a.오늘, rules_dir=a.rules)
    code = rep["종료코드"]
    print(confirm_md(rep), file=sys.stderr if code == 4 else sys.stdout)       # 확인 글(인적사항 없음)을 화면에 낸다
    return code


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")       # Windows 기본 cp949 로 깨지지 않게 한다
        except AttributeError:
            pass
    sys.exit(main())
