# -*- coding: utf-8 -*-
"""양도소득세 로컬 MCP 서버. stdio 로 JSON-RPC 메시지를 한 줄에 하나씩 주고받는다.

  claude mcp add yangdo -- python <스킬 경로>/scripts/mcp_server.py

엔진은 외부를 조회하지 않는다. 신고인 인적사항은 받지 않는다(사실관계에 있으면 오류).
신고서 도구(yangdo_forms)는 신고인 JSON 을 파일 경로로만 받고, 응답에 인적사항 값을 싣지 않는다.
도구가 실패하면 서버는 죽지 않고 isError 결과에 이유를 적어 돌려준다. 프로토콜 줄만 표준출력에 쓴다.
예상하지 못한 예외는 표준오류에 예외 형 이름과 호출 위치만 남기고 오류 응답에는 형 이름만 싣는다. 예외 문장에는 사실관계나
신고인의 값이 실릴 수 있어 어디에도 싣지 않는다(make_return.py 와 같다). 검사 문장처럼 값이 실리지 않게 지은 문장
(ToolError, 사실관계 검사 FactsError)은 그대로 낸다.

입력 스키마의 속성 이름은 ASCII 로만 쓴다(^[a-zA-Z0-9_.-]{1,64}$). Claude 클라이언트는 이 꼴이 아닌 속성 이름을 가진
도구를 목록에서 통째로 뺀다. 옛 한글 이름(오늘, 문항, 값, 자산, 주택, 서식, 시도, 시군구, 읍면동, 기준일, 지구해당)으로 온
인자도 받는다(ALIASES). 사실관계처럼 한글 키를 가진 값은 속성을 나열하지 않는 자유 객체로 둔다.
스키마에 없는 인자가 오면 버리지 않고 오류로 답한다(문장에는 인자 이름만 싣는다). 이름을 잘못 적은 인자가 조용히 빠져
out_dir 없이 계산만 되는 일을 막는다.

신고서 도구가 쓰는 make_return(과 pymupdf)은 그 도구를 처음 부를 때 읽는다(_load_make_return). 서버를 띄울 때 읽지 않으므로
pymupdf 가 없어도 계산 도구는 그대로 뜨고, 신고서 도구만 설치 안내 오류를 낸다. 읽은 뒤에는 MuPDF 메시지를 표준오류로 돌려
프로토콜 줄에 섞이지 않게 한다.

edition.PUBLIC 이 참이면 yangdo_calculate 는 out_dir 에 계산근거 워크북만, yangdo_forms 는 신고서 PDF 두 벌과 계산근거 워크북만
남기고, 상태·합계·확인사항·경고·질문·다루지않음·사람이 할 일은 응답으로만 낸다.
"""
import contextlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
for _p in (SKILL, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from yangdo import edition, engine, evidence, outputs, questions, regions, ruleset  # noqa: E402
from yangdo.dates import to_date  # noqa: E402
from yangdo import facts as F  # noqa: E402

PROTOCOL = "2025-03-26"
SERVER_VERSION = "0.14.2"       # 플러그인 버전(.claude-plugin/plugin.json)과 같은 값. 어긋나면 시험이 실패한다
NAME_SHOWN = 40                # 오류 문장에 적는 인자 이름의 최대 길이
INSTRUCTIONS_HEAD = ("사실관계 JSON 에는 신고인 인적사항(성명, 주민등록번호, 주소, 전화번호, 계좌)을 넣지 않는다. "
                '새 사건은 facts: {"자산": [{"id": "A"}]} 로 시작한다. 판 자산마다 항목 하나를 두고 id 는 A, B, ... 로 붙인다. '
                "이 값을 yangdo_answer 의 facts 로 주고(같은 내용의 파일이면 facts_path), 돌려받은 사실관계를 다음 호출에 이어 쓴다. "
                "yangdo_next_questions 로 다음 문항을 받고, 사용자의 답을 yangdo_answer 로 넣고, "
                "남은 문항이 없으면 yangdo_calculate 를 부른다. 계산 결과는 검토용이며 신고 전 최종 판단은 세무 전문가가 한다. ")
RETURN_SENTENCE = ("신고서 PDF 는 yangdo_forms 로 만든다. 출력 폴더에는 신고서 PDF 두 벌과 계산근거 워크북만 남고, 상태·확인사항·경고·"
                   "사람이 할 일은 응답으로 온다. 신고인 정보(인적사항)는 신고인 JSON 파일의 경로(filer_path)로만 주고 내용을 대화나 "
                   "인자에 옮기지 않는다. 응답에는 인적사항이 없다. ")
INSTRUCTIONS_TAIL = ("홈택스·위택스 로그인과 제출은 사람이 한다. 사용자가 매매계약서나 경비 영수증 파일을 주면 문항을 묻기 전에 먼저 "
                "yangdo_evidence_inventory 로 목록을 만들고, 문서를 읽어 증빙추출 JSON 으로 적은 뒤 yangdo_evidence_apply 로 넣는다. "
                "넣은 값, 넣지 못한 값(확인필요·충돌), 가정한 값을 한 표로 보여 주고 한 번에 확인받은 뒤, 남은 문항만 묻는다. "
                "남은 문항은 limit 를 10 안팎으로 받아 같은 섹션끼리 한 메시지로 묻는다. 사용자가 하나씩 묻기를 원할 때만 limit 1 로 묻는다. "
                     "생략에 오는 문항은 묻지 않고, 사용자가 그 값을 먼저 말하면 넣는다.")
INSTRUCTIONS = INSTRUCTIONS_HEAD + RETURN_SENTENCE + INSTRUCTIONS_TAIL      # initialize 가 돌려주는 안내(instructions)
FACTS = {"facts_path": {"type": "string", "description": "사실관계 JSON 파일 경로(로컬)"},
         "facts": {"type": "object", "description": "사실관계 JSON. facts_path 대신 쓴다. 둘을 함께 주지 않는다"}}
TODAY = {"type": "string", "description": "오늘 날짜 YYYY-MM-DD(오늘). 비우면 오늘(한국 시간)"}
RETURN = dict(FACTS, filer_path={"type": "string", "description": "신고인 JSON 파일 경로(로컬). 인적사항이 든 파일이라 경로로만 받는다"},
              out_dir={"type": "string", "description": "출력 폴더. 이 도구들이 쓰는 이름의 이전 결과 파일은 지운다"}, today=TODAY)
# 스키마가 알리는 이름(ASCII) → 옛 한글 이름. 처리기는 두 이름을 모두 받는다
ALIASES = {"today": "오늘", "question": "문항", "value": "값", "asset": "자산", "house": "주택", "forms": "서식",
           "sido": "시도", "sigungu": "시군구", "eupmyeondong": "읍면동", "as_of": "기준일", "in_district": "지구해당"}
TOOLS = [
    {"name": "yangdo_next_questions", "description": "사실관계에 비어 있는 것 중 다음에 물을 문항(섹션, 왜 묻는지, 근거 조문, 증빙, 모를 때 확인하는 곳, "
                                               "흔한 값의 가정 포함). 생략에는 묻지 않는 선택 문항과 그 안내가 온다",
     "inputSchema": {"type": "object",
                     "properties": dict(FACTS, forms={"type": "boolean", "description": "서식 단계 문항도 낸다(서식)"},
                                        limit={"type": "integer", "minimum": 1, "description": "한 번에 받을 문항 수. 기본 1. 섹션끼리 묶어 물을 때는 10 안팎"})},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "yangdo_answer", "description": "문항 답을 사실관계에 넣는다. value 에 문자열 「모름」을 주면 모름으로 기록한다. facts_path 를 주면 그 파일을 고쳐 쓴다",
     "inputSchema": {"type": "object", "required": ["question", "value"],
                     "properties": dict(FACTS, question={"type": "string", "description": "문항 id(문항). 예: P01, A11"},
                                        value={"description": "답(값). 형식은 문항의 답형식을 따른다. 모르면 문자열 「모름」"},
                                        asset={"type": "string", "description": "자산마다 묻는 문항이면 자산 id(자산)"},
                                        house={"type": "string", "description": "주택마다 묻는 문항이면 주택 id(주택)"})},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "yangdo_calculate", "description": "판정·세액·근거·규격서 코드. out_dir 를 주면 계산근거 워크북(양도소득세_계산근거.xlsx)만 쓴다(그 폴더에 "
                                                "이 도구들이 쓰는 이름의 이전 파일은 지운다). 상태·질문·확인사항·경고는 응답으로 온다",
     "inputSchema": {"type": "object", "properties": dict(FACTS, out_dir={"type": "string", "description": "출력 폴더"}, today=TODAY)},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "yangdo_forms", "description": "계산 뒤 신고인 정보를 검사하고 서식 검산을 거쳐 신고서 PDF(양도소득세 별지 제84호, 지방소득세 별지 "
                                            "제40호의11)를 out_dir 에 만든다. 출력 폴더에는 신고서 PDF 두 벌과 계산근거 워크북만 남는다. 응답은 "
                                            "상태·단계·파일 경로·검산 문장·확인사항·경고·알림·사람이 할 일이고 인적사항은 싣지 않는다",
     "inputSchema": {"type": "object", "required": ["filer_path", "out_dir"], "properties": RETURN},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "yangdo_evidence_inventory", "description": "증빙 폴더(매매계약서, 영수증, 세금계산서 파일)의 문서 목록을 만든다. 문서마다 id(D01...)와 글자층 여부를 돌려준다. "
                                                   "목록 파일(증빙_목록.json)은 yangdo_evidence_apply 가 쓴다",
     "inputSchema": {"type": "object", "required": ["folder", "out_dir"],
                     "properties": {"folder": {"type": "string", "description": "증빙 파일이 든 폴더 경로(로컬)"},
                                    "out_dir": {"type": "string", "description": "증빙_목록.json 을 쓸 폴더"}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "yangdo_evidence_apply", "description": "문서를 읽어 적은 값(증빙추출)을 원문과 대조해, 통과한 값만 사실관계에 넣는다. 스캔본이나 사진에서 읽은 값, 확신이 불확실한 값, "
                                                  "이미 다른 값이 있는 값은 넣지 않고 확인표(증빙_확인표.md)에 올린다. facts 를 주지 않으면 자산 A 하나로 시작한다",
     "inputSchema": {"type": "object", "required": ["inventory_path", "out_dir"],
                     "properties": dict(FACTS, inventory_path={"type": "string", "description": "yangdo_evidence_inventory 가 쓴 증빙_목록.json 경로"},
                                        extractions={"type": "array", "description": "추출 목록. 항목: {문항, 자산, 값, 출처:{문서, 쪽, 발췌}, 확신, 비고}. extractions_path 대신 쓴다"},
                                        extractions_path={"type": "string", "description": "증빙추출 JSON 파일 경로"},
                                        out_dir={"type": "string", "description": "증빙_확인표.md 와 증빙_결과.json 을 쓸 폴더"})},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "regulated_area", "description": "기준일에 조정대상지역·투기과열지구·투기지역인지(공고 이력 재적용)",
     "inputSchema": {"type": "object", "required": ["sido", "sigungu", "as_of"],
                     "properties": {"sido": {"type": "string", "description": "시도 이름(시도). 예: 서울특별시"},
                                    "sigungu": {"type": "string", "description": "시군구 이름(시군구). 예: 마포구"},
                                    "eupmyeondong": {"type": "string", "description": "읍면동 이름(읍면동). 예: 공덕동"},
                                    "as_of": {"type": "string", "description": "기준일 YYYY-MM-DD(기준일)"},
                                    "in_district": {"type": "string", "description": "읍면동 일부만 지정된 지구에 드는지(지구해당). 질문이 돌아왔을 때 그 후보 가운데 하나"}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "ruleset_info", "description": "기준정보 판 id, 확인일, 시행예정 개정, 계류 개정",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]
# 신고서 도구 응답에 싣는 보고 키(make_return.make 의 결과에서 고른다). 신고인 값은 없다
PUBLIC_RETURN_KEYS = ("상태", "종료코드", "요약", "단계", "기준정보", "판", "합계", "가산세", "파일", "질문", "신고인질문", "다루지않음",
                      "검산", "서식검산", "확인사항", "경고", "알림", "사람이할일")
RETURN_KEYS = PUBLIC_RETURN_KEYS
VERDICT_KEYS = ("비과세", "고가주택", "전액비과세", "미등기", "중과", "단기", "장특공", "보유년", "거주년")
SUM_NOTE = ("자산별 산출세액은 자산마다 따로 계산한 참고값이다. 산출세액은 같은 세율 자산 합산 세액(호별합산세액)과 "
            "합산 비교 세액 중 큰 값이다")


class ToolError(Exception):
    """클라이언트에 그대로 보여 줄 문장을 든 오류."""


_why = outputs.why


def _malformed(e):
    # 엔진 버그인지 입력 탓인지 운영자가 가를 수 있게 표준오류에 남긴다. 예외 문장은 응답에도 표준오류에도 싣지 않는다
    outputs.log_call_sites(e, "사실관계의 값을 처리하지 못했다")
    return ToolError("사실관계의 값을 처리하지 못했다(%s). 날짜는 YYYY-MM-DD, 금액은 원 단위 정수, 목록 모양은 질문지 문항.json 의 facts키 대로인지 확인한다"
                     % type(e).__name__)


def _write_error(e, fallback, notes=()):
    """출력 파일 쓰기 실패. notes 는 뒤에 붙일 문장(지우지 못한 임시 폴더 알림)이다."""
    text = "출력 파일을 쓰지 못했다: %s (%s). 파일을 닫고 다시 실행한다" % (e.filename or fallback, _why(e))
    return ToolError(". ".join([text] + list(notes)))


def _label(key):
    """오류 문장에 쓰는 인자 이름. 옛 한글 이름이 있으면 함께 적는다: today(오늘)."""
    return "%s(%s)" % (key, ALIASES[key]) if key in ALIASES else key


def _normalize(args):
    """옛 한글 인자 이름을 스키마의 ASCII 이름으로 바꾼 새 dict. 두 이름을 함께 주면 오류."""
    out = dict(args)
    for new, old in ALIASES.items():
        if old in out:
            if new in out:
                raise ToolError("%s 와 %s 는 같은 인자다. 하나만 준다" % (new, old))
            out[new] = out.pop(old)
    return out


def _text(args, key, required=False):
    v = args.get(key)
    if v is None:
        if required:
            raise ToolError("%s 값이 필요하다" % _label(key))
        return None
    if not isinstance(v, str):
        raise ToolError("%s 값은 문자열이어야 한다" % _label(key))
    return v


def _date(v, name):
    ok = isinstance(v, str)
    if ok:
        try:
            ok = to_date(v) is not None   # YYYY-MM-DD 이고 달력에 있는 날만 받는다
        except ValueError:
            ok = False
    if not ok:
        raise ToolError("%s 값은 실제 있는 날짜를 YYYY-MM-DD 로 적어야 한다. 받은 값: %s" % (name, json.dumps(v, ensure_ascii=False)[:40]))
    return v


def _read_json(path):
    if not isinstance(path, str) or not path:
        raise ToolError("facts_path 값은 파일 경로 문자열이어야 한다")
    try:
        with open(os.path.expanduser(path), encoding="utf-8-sig") as fp:
            obj = json.load(fp)
    except OSError as e:
        raise ToolError("사실관계 파일을 읽지 못했다: %s (%s)" % (path, _why(e))) from e
    except ValueError as e:
        raise ToolError("사실관계 파일이 JSON 이 아니다: %s (%s)" % (path, e)) from e
    if not isinstance(obj, dict):
        raise ToolError("사실관계 파일의 맨 위는 JSON 객체여야 한다: %s" % path)
    return obj


def _write_json(path, obj):
    """같은 폴더에 새 임시 파일을 만들어 쓴 뒤 바꿔 넣는다. 남의 파일을 건드리지 않고, 실패하면 임시 파일을 지운다."""
    real = os.path.expanduser(path)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real) or ".", prefix=os.path.basename(real) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(obj, fp, ensure_ascii=False, indent=1)
        with contextlib.suppress(OSError):
            shutil.copymode(real, tmp)  # mkstemp 는 소유자만 읽는 권한으로 만든다. 원래 파일의 권한을 잇는다
        os.replace(tmp, real)
    except BaseException as e:
        if tmp:
            with contextlib.suppress(OSError):
                os.remove(tmp)
        if isinstance(e, OSError):
            raise ToolError("사실관계 파일을 쓰지 못했다: %s (%s). 파일을 닫고 다시 실행한다" % (path, _why(e))) from e
        if isinstance(e, UnicodeEncodeError):
            raise ToolError("사실관계에 파일로 저장할 수 없는 문자가 있다(짝 없는 대리 문자). 값을 다시 확인한다") from e
        raise


def _facts(args):
    f, path = args.get("facts"), args.get("facts_path")
    if f is not None and path is not None:
        raise ToolError("facts 와 facts_path 는 하나만 준다")
    if f is None and path is None:
        raise ToolError("facts 또는 facts_path 가 필요하다")
    if f is None:
        f = _read_json(path)
    elif not isinstance(f, dict):
        raise ToolError("facts 값은 JSON 객체여야 한다")
    F.check_personal(f)
    return f


def _load_rules(fn):
    """기준정보 파일을 읽는다. 깨졌으면 무엇이 원인이든 RuleError 계열로 알린다."""
    try:
        return fn()
    except ruleset.RuleError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ruleset.RuleError("파일을 읽지 못했다: %s" % e) from e


def _ruleset_info(args):
    rs = _load_rules(ruleset.load)
    up = sorted({(u["시행일"], u["법령"], u["조"]) for r in rs.data["규칙"].values()
                 for e in r["이력"] for u in e.get("예정변경", [])})
    return {"판": rs.판id, "확인일": rs.확인일, "기준시작": rs.기준시작,
            "시행예정": [{"시행일": a, "법령": b, "조": c} for a, b, c in up], "계류": rs.data.get("계류", [])}


def _regulated_area(args):
    addr = {"시도": _text(args, "sido", True), "시군구": _text(args, "sigungu", True), "읍면동": _text(args, "eupmyeondong") or ""}
    on = _date(args.get("as_of"), _label("as_of"))
    district = _text(args, "in_district")
    reg = _load_rules(regions.load)
    out = {}
    for regime in regions.REGIMES:
        try:
            out[regime] = reg.status(regime, addr, on, district)
        except regions.NeedAnswer as e:
            out[regime] = {"질문": e.문항, "내용": e.내용, "후보": e.후보}
    return out


def _next_questions(args):
    f = _facts(args)
    limit = args.get("limit")
    if limit is None:
        limit = 1
    elif isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ToolError("limit 값은 1 이상의 정수여야 한다")
    form = args.get("forms")
    if form is not None and not isinstance(form, bool):
        raise ToolError("%s 값은 true 또는 false 여야 한다" % _label("forms"))
    try:
        r = questions.next_questions(f, 서식=bool(form), limit=limit)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise _malformed(e) from e
    return {"다음": r["다음"], "남은": r["남은"], "생략": r["생략"]}


def _answer(args):
    f = _facts(args)
    qid = _text(args, "question", True)
    if args.get("value") is None:
        raise ToolError("%s 값이 필요하다. 모르면 「모름」 으로 답한다" % _label("value"))
    asset, house = _text(args, "asset"), _text(args, "house")
    try:
        f2 = questions.answer(f, qid, args["value"], 자산=asset, 주택=house)
    except ValueError as e:
        raise ToolError(str(e)) from e
    except (TypeError, KeyError, AttributeError) as e:
        raise _malformed(e) from e
    if args.get("facts_path"):
        _write_json(args["facts_path"], f2)
        return {"저장": args["facts_path"]}
    return {"사실관계": f2}


def _today(args):
    today = args.get("today")
    if today is not None:
        _date(today, _label("today"))
    return today


def _calculate(args):
    f = _facts(args)
    today = _today(args)
    out_dir = _text(args, "out_dir")
    try:
        if out_dir:
            # 이전 결과 지움 → 계산 → 파일 쓰기는 run.py, make_return.py 와 같은 outputs.calculate_to 가 한다
            out_dir = os.path.expanduser(out_dir)
            res, files = outputs.calculate_to(f, out_dir, today=today)
        else:
            res, files = engine.calculate(f, today=today), []
    except OSError as e:
        if not out_dir:
            raise
        # 쓰기 실패로 끝나도 남은 임시 폴더는 알린다(run.py 와 같다). 인적사항이 든 신고값 사본이 있을 수 있다
        raise _write_error(e, out_dir, outputs.tmp_left_notes(out_dir)) from e
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise _malformed(e) from e
    s = {k: res[k] for k in ("상태", "기준정보", "질문", "다루지않음", "확인사항", "경고", "검산")}
    s["파일"] = files
    left = outputs.tmp_left_notes(out_dir) if out_dir else []
    if left:        # 지우지 못했거나 다른 파일이 함께 있어 지우지 않은 전자신고 임시 폴더. 인적사항이 든 신고값 사본이 있을 수 있어 계산 도구도 알린다(폴더 이름만 싣는다)
        s["알림"] = left
    cal = res["계산"]
    if cal:
        s["합계"] = cal["합계"]
        s["자산"] = [{"id": r["id"], "판정": {k: r["판정"][k] for k in VERDICT_KEYS}, "코드": r["계산"]["코드"],
                    "합산묶음": r["계산"].get("합산묶음"), "산출세액": r["계산"]["산출세액"],
                    "지방소득세": r["계산"]["지방소득세"]} for r in cal["자산"]]
        if cal["합계"]["산출세액"] != cal["합계"]["자산별세액"]:
            s["참고"] = SUM_NOTE
    return s


_RETURN_MODULE = []


def _load_make_return():
    """make_return 모듈. 처음 부를 때 읽는다(pymupdf 가 이때 올라온다). 읽지 못하면 설치 안내를 든 ToolError.

    pymupdf 는 메시지를 읽을 때의 표준출력에 쓰도록 잡아 두므로, 읽은 뒤 표준오류로 돌린다(set_messages 가 없는 판은 건너뛴다).
    """
    if not _RETURN_MODULE:
        try:
            import make_return
        except ImportError as e:
            raise ToolError("신고서·전자신고 도구에 필요한 모듈(%s)을 읽지 못했다. pymupdf 가 없으면 스킬 폴더에서 "
                            "pip install -r requirements.txt 를 돌린 뒤 서버를 다시 띄운다. 계산 도구는 그대로 쓸 수 있다"
                            % (e.name or "pymupdf")) from e
        pymupdf = sys.modules.get("pymupdf")
        redirect = getattr(pymupdf, "set_messages", None)
        if callable(redirect):
            try:
                redirect(stream=sys.__stderr__ or sys.stderr)
            except Exception as e:      # 메시지 설정 방법이 다른 판. 건너뛴다
                outputs.log_call_sites(e, "MuPDF 메시지를 표준오류로 돌리지 못했다")
        _RETURN_MODULE.append(make_return)
    return _RETURN_MODULE[0]


def _make_return(args, with_efile=False):
    """신고서를 만든다. 신고인 정보는 파일 경로로만 받고, 응답에는 보고 가운데 RETURN_KEYS 만 싣는다."""
    make_return = _load_make_return()      # 모듈을 읽지 못하면 인자를 보거나 출력 폴더를 건드리기 전에 알린다
    upto = make_return.EFILE if with_efile else make_return.FORMS
    f = _facts(args)
    filer_path = _text(args, "filer_path", True)
    out_dir = _text(args, "out_dir", True)
    today = _today(args)
    if not filer_path or not out_dir:
        raise ToolError("filer_path 와 out_dir 는 빈 글자일 수 없다")
    rep = make_return.make(f, os.path.expanduser(filer_path), os.path.expanduser(out_dir), today=today, upto=upto)
    if rep["종료코드"] == 4:
        raise ToolError(" ".join(rep["알림"]) or rep["요약"])
    return {k: rep[k] for k in (PUBLIC_RETURN_KEYS if edition.PUBLIC else RETURN_KEYS)}


def _forms(args):
    return _make_return(args, with_efile=False)


def _evidence_inventory(args):
    folder, out = _text(args, "folder", True), _text(args, "out_dir", True)
    try:
        inv = evidence.inventory(os.path.expanduser(folder))
        path = os.path.join(os.path.expanduser(out), "증빙_목록.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(inv, fp, ensure_ascii=False, indent=1)
    except evidence.EvidenceError as e:
        raise ToolError(str(e)) from e
    except OSError as e:
        raise _write_error(e, out) from e
    return {"문서": inv["문서"], "목록파일": path}


def _evidence_apply(args):
    if args.get("facts") is None and args.get("facts_path") is None:
        f, path = {"자산": [{"id": "A"}]}, None
    else:
        f, path = _facts(args), args.get("facts_path")
    inv = _read_json(_text(args, "inventory_path", True))
    items = args.get("extractions")
    if items is None:
        ep = _text(args, "extractions_path")
        if ep is None:
            raise ToolError("extractions 또는 extractions_path 가 필요하다")
        try:
            with open(os.path.expanduser(ep), encoding="utf-8-sig") as fp:
                items = json.load(fp)
        except OSError as e:
            raise ToolError("증빙추출 파일을 읽지 못했다: %s (%s)" % (ep, _why(e))) from e
        except ValueError as e:
            raise ToolError("증빙추출 파일이 JSON 이 아니다: %s" % ep) from e
    out = os.path.expanduser(_text(args, "out_dir", True))
    try:
        new, rep = evidence.apply(f, items, inv)
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "증빙_결과.json"), "w", encoding="utf-8", newline="\n") as fp:
            json.dump(rep, fp, ensure_ascii=False, indent=1)
        with open(os.path.join(out, "증빙_확인표.md"), "w", encoding="utf-8", newline="\n") as fp:
            fp.write(evidence.confirm_markdown(rep, inv))
    except evidence.EvidenceError as e:
        raise ToolError(str(e)) from e
    except OSError as e:
        raise _write_error(e, out) from e
    F.check_personal(new)
    if path is not None:
        _write_json(path, new)
    res = {"반영": len(rep["반영"]), "넣은값": rep["반영"], "일치": len(rep["일치"]), "충돌": rep["충돌"],
           "확인필요": rep["확인필요"], "가정": rep["가정"], "생략": rep["생략"], "거절": rep["거절"],
           "남은문항": rep["남은문항"][:15], "남은문항수": len(rep["남은문항"]), "확인표": os.path.join(out, "증빙_확인표.md")}
    if path is None:
        res["사실관계"] = new
    return res


HANDLERS = {"yangdo_next_questions": _next_questions, "yangdo_answer": _answer, "yangdo_calculate": _calculate,
            "yangdo_forms": _forms,
            "yangdo_evidence_inventory": _evidence_inventory,
            "yangdo_evidence_apply": _evidence_apply, "regulated_area": _regulated_area, "ruleset_info": _ruleset_info}


PROPERTIES = {t["name"]: tuple(t["inputSchema"]["properties"]) for t in TOOLS}


def tool_list():
    """tools/list 가 알리는 도구 목록."""
    return TOOLS


def handler_map():
    """부를 수 있는 도구 이름 → 처리기."""
    return HANDLERS


def instructions():
    """initialize 가 돌려주는 안내."""
    return INSTRUCTIONS


def _unknown_arguments(name, args):
    """도구 name 의 입력 스키마에 없는 인자 이름(받은 이름 그대로, 이름순). 옛 한글 이름은 스키마 이름으로 바꿔서 본다."""
    known = set(PROPERTIES[name])
    old = {v: k for k, v in ALIASES.items()}
    return sorted(k for k in args if old.get(k, k) not in known)


def call_tool(name, args):
    handlers = handler_map()
    if name not in handlers:
        raise ToolError("없는 도구: %s" % name)
    if not isinstance(args, dict):
        raise ToolError("arguments 값은 JSON 객체여야 한다")
    unknown = _unknown_arguments(name, args)
    if unknown:     # 인자 이름만 싣는다(값은 싣지 않는다). 이름이 길면 잘라 적는다
        raise ToolError("%s 가 받지 않는 인자: %s. 받는 인자: %s" % (
            name, ", ".join(str(k)[:NAME_SHOWN] for k in unknown[:10]),
            ", ".join(_label(k) for k in PROPERTIES[name]) or "없음"))
    return handlers[name](_normalize(args))


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _tool_failure(e):
    """도구가 던진 예외를 클라이언트에 보일 문장으로 바꾼다. 서버는 계속 돈다."""
    if isinstance(e, (ToolError, F.FactsError)):
        return str(e)
    if isinstance(e, ruleset.RuleError):
        return "기준정보 오류: %s" % e
    if isinstance(e, OSError):
        return "파일을 처리하지 못했다: %s (%s)" % (e.filename or "", _why(e))
    # 예상하지 못한 오류는 운영자가 볼 수 있게 표준오류에 남긴다. 예외 문장에는 사실관계나 신고인의 값이 실릴 수 있어
    # 표준오류에는 형 이름과 호출 위치만, 응답에는 형 이름만 싣는다
    outputs.log_call_sites(e, "도구 실행 중 예상하지 못한 오류")
    return "도구 실행 중 예상하지 못한 오류가 났다(%s). 오류 기록은 서버의 표준오류에 있다" % type(e).__name__


def handle(req):
    if not isinstance(req, dict):
        return _error(None, -32600, "요청은 JSON 객체여야 한다")
    method, rid = req.get("method"), req.get("id")
    if rid is None:
        return None
    params = req.get("params")
    params = params if isinstance(params, dict) else {}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion": version if isinstance(version, str) and version else PROTOCOL,
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "yangdo", "version": SERVER_VERSION},
                  "instructions": instructions()}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "ping":
        result = {}
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in handler_map():
            return _error(rid, -32602, "없는 도구: %s" % (name,))
        try:
            data = call_tool(name, params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=1)}]}
        except Exception as e:  # 도구 오류는 결과로 돌려준다(서버는 계속 돈다)
            result = {"content": [{"type": "text", "text": _tool_failure(e)}], "isError": True}
    else:
        return _error(rid, -32601, "method not found: %s" % method)
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main():
    for stream, errors in ((sys.stdin, "surrogateescape"), (sys.stdout, "strict")):
        try:
            # 입력의 잘못된 UTF-8 바이트는 예외 대신 짝 없는 대리 문자로 받아 아래에서 parse error 로 돌려준다
            stream.reconfigure(encoding="utf-8", errors=errors)
        except AttributeError:
            pass
    try:
        sys.stdout.reconfigure(newline="\n")  # 윈도우에서 줄 끝이 CRLF 로 바뀌지 않게 한다
    except AttributeError:
        pass
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            line.encode("utf-8")  # surrogateescape 로 들어온 잘못된 바이트는 여기서 걸린다
            req = json.loads(line)
        except UnicodeEncodeError:
            resp = _error(None, -32700, "UTF-8 로 읽을 수 없는 바이트가 든 줄이다")
        except (ValueError, RecursionError):  # 중첩이 지나치게 깊은 줄도 읽지 못한 줄로 다룬다
            resp = _error(None, -32700, "JSON 으로 읽을 수 없는 줄이다")
        else:
            try:
                with contextlib.redirect_stdout(sys.stderr):  # 라이브러리가 표준출력에 쓴 글이 프로토콜 줄에 섞이지 않게 한다
                    resp = handle(req)
            except Exception as e:  # handle 은 던지지 않게 짜여 있다. 그래도 서버는 죽지 않는다
                outputs.log_call_sites(e, "요청을 처리하다 예상하지 못한 오류")
                resp = _error(req.get("id") if isinstance(req, dict) else None, -32603, "내부 오류(%s)" % type(e).__name__)
        if resp is not None:
            try:
                out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            except UnicodeEncodeError:  # 응답에 짝 없는 대리 문자가 섞였으면 ASCII 이스케이프로 보낸다
                out.write(json.dumps(resp) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
