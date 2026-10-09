# -*- coding: utf-8 -*-
"""양도소득세 로컬 MCP 서버. stdio 로 JSON-RPC 메시지를 한 줄에 하나씩 주고받는다.

  claude mcp add yangdo -- python <스킬 경로>/scripts/mcp_server.py

엔진은 외부를 조회하지 않는다. 신고인 인적사항은 받지 않는다(사실관계에 있으면 오류).
도구가 실패하면 서버는 죽지 않고 isError 결과에 이유를 적어 돌려준다. 프로토콜 줄만 표준출력에 쓴다.
"""
import contextlib
import json
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
for p in (SKILL, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import run as RUN  # noqa: E402
from yangdo import engine, questions, regions, ruleset  # noqa: E402
from yangdo.dates import to_date  # noqa: E402
from yangdo import facts as F  # noqa: E402

PROTOCOL = "2025-03-26"
INSTRUCTIONS = ("사실관계 JSON 에는 신고인 인적사항(성명, 주민등록번호, 주소, 전화번호, 계좌)을 넣지 않는다. "
                '새 사건은 facts: {"자산": [{"id": "A"}]} 로 시작한다. 판 자산마다 항목 하나를 두고 id 는 A, B, ... 로 붙인다. '
                "이 값을 yangdo_answer 의 facts 로 주고(같은 내용의 파일이면 facts_path), 돌려받은 사실관계를 다음 호출에 이어 쓴다. "
                "yangdo_next_questions 로 다음 문항을 받고, 사용자의 답을 yangdo_answer 로 넣고, "
                "남은 문항이 없으면 yangdo_calculate 를 부른다. 계산 결과는 검토용이며 신고 전 최종 판단은 세무 전문가가 한다.")
FACTS = {"facts_path": {"type": "string", "description": "사실관계 JSON 파일 경로(로컬)"},
         "facts": {"type": "object", "description": "사실관계 JSON. facts_path 대신 쓴다. 둘을 함께 주지 않는다"}}
TOOLS = [
    {"name": "yangdo_next_questions", "description": "사실관계에 비어 있는 것 중 다음에 물을 문항(왜 묻는지, 근거 조문, 증빙, 모를 때 확인하는 곳 포함)",
     "inputSchema": {"type": "object", "properties": dict(FACTS, 서식={"type": "boolean"}, limit={"type": "integer", "minimum": 1})},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "yangdo_answer", "description": "문항 답을 사실관계에 넣는다. 값에 문자열 「모름」을 주면 모름으로 기록한다. facts_path 를 주면 그 파일을 고쳐 쓴다",
     "inputSchema": {"type": "object", "required": ["문항", "값"],
                     "properties": dict(FACTS, 문항={"type": "string"}, 값={}, 자산={"type": "string"}, 주택={"type": "string"})},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "yangdo_calculate", "description": "판정·세액·근거·규격서 코드. out_dir 를 주면 검토 문서·워크북·결과 JSON 을 쓴다(그 폴더의 이전 결과 파일은 지운다)",
     "inputSchema": {"type": "object",
                     "properties": dict(FACTS, out_dir={"type": "string"}, 오늘={"type": "string", "description": "YYYY-MM-DD. 비우면 오늘(한국 시간)"})},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}},
    {"name": "regulated_area", "description": "기준일에 조정대상지역·투기과열지구·투기지역인지(공고 이력 재적용)",
     "inputSchema": {"type": "object", "required": ["시도", "시군구", "기준일"],
                     "properties": {k: {"type": "string"} for k in ("시도", "시군구", "읍면동", "기준일", "지구해당")}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "ruleset_info", "description": "기준정보 판 id, 확인일, 시행예정 개정, 계류 개정",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
]
VERDICT_KEYS = ("비과세", "고가주택", "전액비과세", "미등기", "중과", "단기", "장특공", "보유년", "거주년")
SUM_NOTE = ("자산별 산출세액은 자산마다 따로 계산한 참고값이다. 산출세액은 같은 세율 자산 합산 세액(호별합산세액)과 "
            "합산 비교 세액 중 큰 값이다")


class ToolError(Exception):
    """클라이언트에 그대로 보여 줄 문장을 든 오류."""


def _why(e):
    return " ".join(str(getattr(e, "strerror", None) or e).split())


def _malformed(e):
    traceback.print_exception(type(e), e, e.__traceback__, file=sys.stderr)  # 엔진 버그인지 입력 탓인지 운영자가 가를 수 있게 남긴다
    return ToolError("사실관계의 값을 처리하지 못했다(%s: %s). 날짜는 YYYY-MM-DD, 금액은 원 단위 정수, 목록 모양은 질문지 문항.json 의 facts키 대로인지 확인한다"
                     % (type(e).__name__, e))


def _write_error(e, fallback):
    return ToolError("출력 파일을 쓰지 못했다: %s (%s). 파일을 닫고 다시 실행한다" % (e.filename or fallback, _why(e)))


def _text(args, key, required=False):
    v = args.get(key)
    if v is None:
        if required:
            raise ToolError("%s 값이 필요하다" % key)
        return None
    if not isinstance(v, str):
        raise ToolError("%s 값은 문자열이어야 한다" % key)
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
    addr = {"시도": _text(args, "시도", True), "시군구": _text(args, "시군구", True), "읍면동": _text(args, "읍면동") or ""}
    on = _date(args.get("기준일"), "기준일")
    district = _text(args, "지구해당")
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
    form = args.get("서식")
    if form is not None and not isinstance(form, bool):
        raise ToolError("서식 값은 true 또는 false 여야 한다")
    try:
        r = questions.next_questions(f, 서식=bool(form), limit=limit)
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise _malformed(e) from e
    return {"다음": r["다음"], "남은": r["남은"]}


def _answer(args):
    f = _facts(args)
    qid = _text(args, "문항", True)
    if args.get("값") is None:
        raise ToolError("값이 필요하다. 모르면 「모름」 으로 답한다")
    asset, house = _text(args, "자산"), _text(args, "주택")
    try:
        f2 = questions.answer(f, qid, args["값"], 자산=asset, 주택=house)
    except ValueError as e:
        raise ToolError(str(e)) from e
    except (TypeError, KeyError, AttributeError) as e:
        raise _malformed(e) from e
    if args.get("facts_path"):
        _write_json(args["facts_path"], f2)
        return {"저장": args["facts_path"]}
    return {"사실관계": f2}


def _calculate(args):
    f = _facts(args)
    today = args.get("오늘")
    if today is not None:
        _date(today, "오늘")
    out_dir = _text(args, "out_dir")
    wb = None
    if out_dir:
        out_dir = os.path.expanduser(out_dir)
        try:
            os.makedirs(out_dir, exist_ok=True)
            RUN.clear_previous(out_dir)  # 이전 완료 결과가 이번 질문 결과 옆에 남지 않게 한다
        except OSError as e:
            raise _write_error(e, out_dir) from e
        wb = os.path.join(out_dir, RUN.WORKBOOK)
    try:
        res = engine.calculate(f, today=today, workbook_path=wb)
    except OSError as e:
        if not out_dir:
            raise
        raise _write_error(e, out_dir) from e
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        raise _malformed(e) from e
    s = {k: res[k] for k in ("상태", "기준정보", "질문", "다루지않음", "확인사항", "경고", "검산")}
    try:
        s["파일"] = RUN.write_outputs(res, out_dir) if out_dir else []
    except OSError as e:
        raise _write_error(e, out_dir) from e
    cal = res["계산"]
    if cal:
        s["합계"] = cal["합계"]
        s["자산"] = [{"id": r["id"], "판정": {k: r["판정"][k] for k in VERDICT_KEYS}, "코드": r["계산"]["코드"],
                    "합산묶음": r["계산"].get("합산묶음"), "산출세액": r["계산"]["산출세액"],
                    "지방소득세": r["계산"]["지방소득세"]} for r in cal["자산"]]
        if cal["합계"]["산출세액"] != cal["합계"]["자산별세액"]:
            s["참고"] = SUM_NOTE
    return s


HANDLERS = {"yangdo_next_questions": _next_questions, "yangdo_answer": _answer, "yangdo_calculate": _calculate,
            "regulated_area": _regulated_area, "ruleset_info": _ruleset_info}


def call_tool(name, args):
    if name not in HANDLERS:
        raise ToolError("없는 도구: %s" % name)
    if not isinstance(args, dict):
        raise ToolError("arguments 값은 JSON 객체여야 한다")
    return HANDLERS[name](args)


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
    traceback.print_exc(file=sys.stderr)  # 예상하지 못한 오류는 운영자가 볼 수 있게 표준오류에 남긴다
    return "도구 실행 중 예상하지 못한 오류가 났다(%s: %s)" % (type(e).__name__, e)


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
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "yangdo", "version": "0.1.0"},
                  "instructions": INSTRUCTIONS}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "ping":
        result = {}
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in HANDLERS:
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
                traceback.print_exc(file=sys.stderr)
                resp = _error(req.get("id") if isinstance(req, dict) else None, -32603, "내부 오류(%s)" % type(e).__name__)
        if resp is not None:
            try:
                out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            except UnicodeEncodeError:  # 응답에 짝 없는 대리 문자가 섞였으면 ASCII 이스케이프로 보낸다
                out.write(json.dumps(resp) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
