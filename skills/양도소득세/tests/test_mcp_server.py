# -*- coding: utf-8 -*-
import ast
import copy
import json
import os
import re
import subprocess
import sys

import pytest

import mcp_server as M
from cases import CASES
from yangdo import edition, ruleset

# 신고서 도구 이름
RETURN_TOOLS = ("yangdo_forms",)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "scripts", "mcp_server.py")
RRN = "900101-1234567"
DASH = chr(0x2014)  # 문체 규칙으로 금지한 줄표. 소스에 글자를 직접 적지 않는다
WRONG_NAME = "".join(chr(c) for c in (0xADF8, 0xB9AC, 0xB514))  # 제품명은 Gridie 로만 쓴다


def rpc(name, args, rid=7):
    return M.handle({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}})


def call(name, args):
    r = rpc(name, args)
    assert "isError" not in r["result"], r
    return json.loads(r["result"]["content"][0]["text"])


def err(name, args):
    """도구 오류. 결과 본문(오류 문구)을 돌려준다. 서버가 죽지 않고 isError 로 답해야 한다."""
    r = rpc(name, args)
    assert r["result"].get("isError") is True, r
    text = r["result"]["content"][0]["text"]
    assert "Traceback" not in text and DASH not in text
    return text


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_initialize_and_list():
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["protocolVersion"] == "2025-03-26" and "tools" in r["result"]["capabilities"]
    names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert names == {"yangdo_next_questions", "yangdo_answer", "yangdo_calculate", *RETURN_TOOLS,
                     "yangdo_evidence_inventory", "yangdo_evidence_apply", "regulated_area", "ruleset_info"}
    assert M.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert M.handle({"jsonrpc": "2.0", "id": 3, "method": "없는메서드"})["error"]["code"] == -32601


def test_ruleset_info_and_area():
    info = call("ruleset_info", {})
    assert len(info["판"]) == 16 and info["계류"]
    a = call("regulated_area", {"sido": "서울특별시", "sigungu": "마포구", "eupmyeondong": "공덕동", "as_of": "2026-10-09"})
    assert a["조정대상지역"]["지정"] is True
    b = call("regulated_area", {"sido": "경기도", "sigungu": "화성시", "eupmyeondong": "반송동", "as_of": "2018-01-01"})
    assert b["조정대상지역"]["질문"] == "A02"


def test_bad_optional_date_is_a_question_and_the_value_is_not_in_the_response(tmp_path):
    f = copy.deepcopy(CASES["K"])
    f["자산"][0]["양도"]["계약일"] = "ZZ비밀값ZZ"
    out = M.call_tool("yangdo_calculate", {"facts": f, "out_dir": str(tmp_path / "o")})
    assert out["상태"] == "질문" and [q["문항"] for q in out["질문"]] == ["A09"]
    assert "ZZ비밀값ZZ" not in json.dumps(out, ensure_ascii=False)


def test_personal_data_is_an_error(tmp_path):
    f = dict(CASES["A"], 신고인={"거주자": True, "주민등록번호": "000000-0000000"})
    r = M.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                  "params": {"name": "yangdo_calculate", "arguments": {"facts": f}}})
    assert r["result"].get("isError") is True


def test_stdio_roundtrip():
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "mcp_server.py")],
                       input="\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n",
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    lines = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    assert [x["id"] for x in lines] == [1, 2], p.stderr


# ---- 아래는 브리프에 없는 시험: 오류 경로, 합계 키, 출력 폴더, stdio 위생 ----

def test_calculate_summary_keeps_both_sum_keys():
    out = call("yangdo_calculate", {"facts": CASES["A"]})
    t = out["합계"]
    for k in ("호별합산세액", "합산비교세액", "산출세액", "지방_호별합산", "지방_합산비교", "지방소득세"):
        assert k in t, k
    assert t["산출세액"] == max(t["호별합산세액"], t["합산비교세액"])
    assert t["지방소득세"] == max(t["지방_호별합산"], t["지방_합산비교"])
    a = out["자산"][0]
    assert a["id"] == "A" and a["합산묶음"] == "기본" and a["산출세액"] == 2_565_000
    assert out["파일"] == []


def test_personal_data_messages_do_not_echo_values(tmp_path):
    p = write_json(tmp_path / "p.json", dict(CASES["A"], 신고인={"거주자": True, "주민등록번호": RRN}))
    assert "인적사항" in err("yangdo_calculate", {"facts_path": p})
    assert "인적사항" in err("yangdo_next_questions", {"facts_path": p})
    assert "인적사항" in err("yangdo_answer", {"facts_path": p, "question": "P01", "value": True})
    memo = copy.deepcopy(CASES["A"])
    memo["메모"] = "연락처 " + RRN
    t = err("yangdo_calculate", {"facts": memo})
    assert "주민등록번호" in t and RRN not in t
    addr = copy.deepcopy(CASES["A"])
    addr["자산"][0]["소재지"] = "서울특별시 송파구 잠실동 1-1"
    assert "주소" in err("yangdo_calculate", {"facts": addr})
    assert "주소" in err("yangdo_next_questions", {"facts": addr})


def test_answer_with_personal_value_is_an_error_and_leaves_file_alone(tmp_path):
    f = {"자산": [{"id": "A"}]}
    p = write_json(tmp_path / "f.json", f)
    before = (tmp_path / "f.json").read_text(encoding="utf-8")
    bad = {"시도": "서울특별시", "시군구": "마포구", "읍면동": RRN}
    t = err("yangdo_answer", {"facts_path": p, "question": "A01", "value": bad, "asset": "A"})
    assert "주민등록번호" in t and RRN not in t
    assert (tmp_path / "f.json").read_text(encoding="utf-8") == before


def test_malformed_value_comes_back_as_question():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["양도"]["잔금일"] = "2026-13-45"
    out = call("yangdo_calculate", {"facts": f})
    assert out["상태"] == "질문" and out["질문"][0]["문항"] == "A11"
    assert "합계" not in out


def test_today_is_validated_and_accepted():
    for bad in ("2026-13-01", "26", "오늘", 20261009, "20261009", "2026-W41-5", ""):
        assert "오늘" in err("yangdo_calculate", {"facts": CASES["A"], "today": bad})
    ok = call("yangdo_calculate", {"facts": CASES["A"], "today": "2026-10-09"})
    assert ok["기준정보"]["오늘"] == "2026-10-09"


def test_invalid_answers_are_tool_errors():
    f = {"자산": [{"id": "A"}]}
    assert "P01" in err("yangdo_answer", {"facts": f, "question": "P01", "value": "예"})
    assert "ZZZ" in err("yangdo_answer", {"facts": f, "question": "ZZZ", "value": True})
    assert "자산 id" in err("yangdo_answer", {"facts": f, "question": "A11", "value": "2026-11-15"})
    assert "YYYY-MM-DD" in err("yangdo_answer", {"facts": f, "question": "A11", "value": "2026/11/15", "asset": "A"})
    assert "값" in err("yangdo_answer", {"facts": f, "question": "P01"})
    assert "문항" in err("yangdo_answer", {"facts": f, "value": True})
    assert "문자열" in err("yangdo_answer", {"facts": f, "question": "A11", "value": "2026-11-15", "asset": 1})


def test_answer_in_memory_and_moreum():
    f = {"자산": [{"id": "A"}]}
    r = call("yangdo_answer", {"facts": f, "question": "P01", "value": True})
    assert r["사실관계"]["신고인"]["거주자"] is True and "신고인" not in f
    m = call("yangdo_answer", {"facts": f, "question": "A11", "value": "모름", "asset": "A"})
    assert "A11:A" in m["사실관계"]["모름"]


def test_next_questions_options():
    f = {"자산": [{"id": "A"}]}
    three = call("yangdo_next_questions", {"facts": f, "limit": 3})
    assert len(three["다음"]) == 3 and three["남은"] >= 3
    assert "limit" in err("yangdo_next_questions", {"facts": f, "limit": "abc"})
    assert "limit" in err("yangdo_next_questions", {"facts": f, "limit": -1})
    assert "limit" in err("yangdo_next_questions", {"facts": f, "limit": 0})
    assert "limit" in err("yangdo_next_questions", {"facts": f, "limit": True})
    assert call("yangdo_next_questions", {"facts": f, "forms": True})["다음"]


def test_next_questions_gives_sections_and_skipped_optional_questions():
    f = {"자산": [{"id": "A", "양도": {"잔금일": "2026-10-30"}}]}
    r = call("yangdo_next_questions", {"facts": f, "limit": 10})
    assert all(q["섹션"] and q["섹션이름"] for q in r["다음"])
    assert [s["id"] for s in r["생략"]] == ["A12"] and "A12" not in [q["id"] for q in r["다음"]]


def test_facts_input_errors(tmp_path):
    assert "facts" in err("yangdo_calculate", {})
    assert "facts" in err("yangdo_calculate", {"facts": "문자열"})
    missing = str(tmp_path / "없는파일.json")
    assert missing in err("yangdo_calculate", {"facts_path": missing})
    bad = tmp_path / "bad.json"
    bad.write_text("{ 깨진 json", encoding="utf-8")
    assert str(bad) in err("yangdo_next_questions", {"facts_path": str(bad)})
    lst = write_json(tmp_path / "list.json", [1, 2])
    assert "객체" in err("yangdo_next_questions", {"facts_path": lst})
    assert "facts_path" in err("yangdo_calculate", {"facts_path": 5})


def test_out_dir_that_cannot_be_written_names_the_path(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    out = str(blocker / "out")
    t = err("yangdo_calculate", {"facts": CASES["A"], "out_dir": out})
    assert "쓰지 못했다" in t and str(blocker) in t


def test_output_write_failure_names_the_file(tmp_path, monkeypatch):
    target = str(tmp_path / "out" / "양도소득세_계산근거.xlsx")

    def locked(*a, **k):
        raise PermissionError(13, "Permission denied", target)

    monkeypatch.setattr(M.outputs, "write_outputs", locked)
    t = err("yangdo_calculate", {"facts": CASES["A"], "out_dir": str(tmp_path / "out")})
    assert target in t and "닫고" in t


def test_answer_write_failure_keeps_original(tmp_path, monkeypatch):
    p = write_json(tmp_path / "f.json", {"자산": [{"id": "A"}]})
    before = (tmp_path / "f.json").read_text(encoding="utf-8")

    def locked(src, dst):
        raise PermissionError(13, "Permission denied", dst)

    monkeypatch.setattr(M.os, "replace", locked)
    assert p in err("yangdo_answer", {"facts_path": p, "question": "P01", "value": True})
    assert (tmp_path / "f.json").read_text(encoding="utf-8") == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["f.json"]


def test_regulated_area_input_errors():
    base = {"sido": "서울특별시", "sigungu": "마포구", "as_of": "2026-10-09"}
    assert "기준일" in err("regulated_area", dict(base, as_of="2026-13-01"))
    assert "as_of" in err("regulated_area", dict(base, as_of="20261009"))
    assert "시도" in err("regulated_area", {"sigungu": "마포구", "as_of": "2026-10-09"})
    assert "sigungu" in err("regulated_area", {"sido": "서울특별시", "as_of": "2026-10-09"})
    assert "sido" in err("regulated_area", dict(base, sido=1))
    unknown = call("regulated_area", dict(base, sido="없는도"))
    assert {v["질문"] for v in unknown.values()} == {"A01"}


def test_unknown_tool_and_bad_requests():
    r = rpc("없는도구", {})
    assert r["error"]["code"] == -32602 and "없는도구" in r["error"]["message"]
    assert M.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}})["error"]["code"] == -32602
    assert "arguments" in err("ruleset_info", [1, 2])
    assert M.handle([1, 2])["error"]["code"] == -32600
    assert M.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})["result"] == {}
    assert M.handle({"jsonrpc": "2.0", "id": 0, "method": "ping"})["id"] == 0


def test_source_style_rules():
    path = os.path.join(ROOT, "scripts", "mcp_server.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert DASH not in src and WRONG_NAME not in src
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "?" not in node.value, node.value


def _run_stdio(data):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.run([sys.executable, SERVER], input=data, capture_output=True, env=env, timeout=240)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    return [json.loads(x) for x in p.stdout.decode("utf-8").split("\n") if x.strip()], p


def _stdio(msgs, raw_lines=()):
    text = "\n".join(list(raw_lines) + [json.dumps(m, ensure_ascii=False) for m in msgs]) + "\n"
    return _run_stdio(text.encode("utf-8"))


def test_stdio_ruleset_info_and_clean_stdout(tmp_path):
    facts = write_json(tmp_path / "a.json", CASES["A"])
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ruleset_info", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "yangdo_calculate", "arguments": {"facts_path": facts, "out_dir": str(tmp_path / "o")}}}]
    lines, p = _stdio(msgs, raw_lines=["이건 JSON 이 아니다"])
    assert lines[0]["id"] is None and lines[0]["error"]["code"] == -32700
    by_id = {x["id"]: x for x in lines[1:]}
    assert sorted(by_id) == [1, 2, 3, 4]
    info = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert info["판"] == ruleset.load().판id
    done = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert done["상태"] == "완료" and done["합계"]["산출세액"] == 2_565_000
    assert b"\r" not in p.stdout


def test_sum_note_only_when_combined_tax_differs():
    out = call("yangdo_calculate", {"facts": CASES["BF"]})
    t = out["합계"]
    assert t["산출세액"] == max(t["호별합산세액"], t["합산비교세액"])
    assert t["산출세액"] == t["합산비교세액"] > t["자산별세액"]
    assert "합산 비교 세액" in out["참고"]
    assert "참고" not in call("yangdo_calculate", {"facts": CASES["A"]})


def test_both_facts_and_path_is_rejected(tmp_path):
    p = write_json(tmp_path / "f.json", CASES["A"])
    assert "하나만" in err("yangdo_calculate", {"facts": CASES["A"], "facts_path": p})


SECRET = "김합성 %s" % RRN       # 예외 문장에는 사실관계나 신고인 값이 실릴 수 있다


def test_unexpected_error_is_still_a_tool_error(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(M.engine, "calculate", boom)
    t = err("yangdo_calculate", {"facts": CASES["A"]})
    assert "예상하지 못한" in t and "RuntimeError" in t
    logged = capsys.readouterr().err
    # 응답에도 표준오류에도 예외 문장은 없다. 표준오류에는 예외 형 이름과 호출 위치(파일, 줄, 함수)만 남는다
    assert "김합성" not in t and RRN not in t
    assert "김합성" not in logged.replace('RuntimeError(SECRET)', "") and RRN not in logged
    assert "RuntimeError" in logged and "호출 위치" in logged and "mcp_server.py" in logged and "in boom" in logged
    assert "Traceback (most recent call last)" not in logged


# ---- Fix 1: 깨진 입력에도 서버가 살아 있다, 임시 파일은 mkstemp, 오류 기록 ----

PING2 = {"jsonrpc": "2.0", "id": 2, "method": "ping"}


def test_stdio_lone_surrogate_in_error_reply_does_not_kill_server():
    raw = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"\\ud800"}}'
    lines, p = _stdio([PING2], raw_lines=[raw])
    by_id = {x["id"]: x for x in lines}
    assert by_id[1]["error"]["code"] == -32602 and "\ud800" in by_id[1]["error"]["message"]
    assert by_id[2]["result"] == {}
    assert p.stdout.split(b"\n")[0].isascii()


def test_stdio_lone_surrogate_in_tool_result_does_not_kill_server():
    raw = ('{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"yangdo_answer","arguments":'
           '{"facts":{"자산":[{"id":"A"}],"메모":"\\ud800"},"question":"P01","value":true}}}')
    lines, _ = _stdio([PING2], raw_lines=[raw])
    by_id = {x["id"]: x for x in lines}
    body = json.loads(by_id[1]["result"]["content"][0]["text"])
    assert body["사실관계"]["메모"] == "\ud800" and body["사실관계"]["신고인"]["거주자"] is True
    assert by_id[2]["result"] == {}


def test_stdio_invalid_utf8_is_a_parse_error_and_server_stays_alive():
    korean = "한".encode("utf-8")
    data = (b'\xff\xfe{"jsonrpc":"2.0","id":9,"method":"ping"}\n'
            b'{"jsonrpc":"2.0","id":8,"method":"ping","params":{"x":"\xff"}}\n'
            b'{"jsonrpc":"2.0","id":7,"method":"ping","params":{"x":"' + korean[:2] + b'"}}\n'
            + json.dumps(PING2).encode("ascii") + b"\n"
            + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {"x": "한글"}},
                         ensure_ascii=False).encode("utf-8") + b"\n")
    lines, _ = _run_stdio(data)
    assert [x["id"] for x in lines] == [None, None, None, 2, 3]
    assert [x["error"]["code"] for x in lines[:3]] == [-32700] * 3
    assert lines[3]["result"] == {} and lines[4]["result"] == {}


def test_stdio_deeply_nested_line_is_a_parse_error_and_server_stays_alive():
    data = b"[" * 200000 + b"]" * 200000 + b"\n" + json.dumps(PING2).encode("ascii") + b"\n"
    lines, _ = _run_stdio(data)
    assert [x["id"] for x in lines] == [None, 2]
    assert lines[0]["error"]["code"] == -32700 and lines[1]["result"] == {}


@pytest.mark.parametrize("name,owner,attr,exc,args", [
    ("yangdo_next_questions", M.questions, "next_questions", KeyError(SECRET), {"facts": CASES["A"]}),
    ("yangdo_answer", M.questions, "answer", TypeError(SECRET),
     {"facts": {"자산": [{"id": "A"}]}, "question": "P01", "value": True}),
    ("yangdo_calculate", M.engine, "calculate", AttributeError(SECRET), {"facts": CASES["A"]}),
])
def test_malformed_value_is_logged_to_stderr(monkeypatch, capsys, name, owner, attr, exc, args):
    """표준오류에는 예외 형 이름과 호출 위치만 남기고, 오류 응답에는 형 이름만 싣는다. 예외 문장은 어디에도 싣지 않는다."""
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(owner, attr, boom)
    t = err(name, args)
    kind = type(exc).__name__
    assert "사실관계의 값을 처리하지 못했다" in t and kind in t
    logged = capsys.readouterr().err
    assert kind in logged and "호출 위치" in logged and "in boom" in logged
    for text in (t, logged):
        assert "김합성" not in text and RRN not in text
    assert "Traceback (most recent call last)" not in logged


def test_validation_sentences_made_as_tool_errors_are_kept():
    """사실관계 검사 문장처럼 값이 실리지 않게 지은 문장은 그대로 낸다."""
    t = err("yangdo_answer", {"facts": {"자산": [{"id": "A"}]}, "question": "없는문항", "value": True})
    assert "없는문항" in t or "문항" in t
    t = err("yangdo_calculate", {"facts": dict(CASES["A"], 메모=RRN)})
    assert "주민등록번호" in t and RRN not in t


# ---- 스키마에 없는 인자 ----

def test_unknown_argument_is_an_error_naming_only_the_argument(tmp_path):
    """스키마에 없는 인자가 오면 조용히 버리지 않고 오류로 답한다. 문장에는 인자 이름만 싣고 값은 싣지 않는다."""
    t = err("yangdo_calculate", {"facts": CASES["A"], "outdir": str(tmp_path / "o"), "today": "2026-10-09"})
    assert "outdir" in t and "out_dir" in t and "받지 않는 인자" in t
    assert str(tmp_path) not in t and not os.path.exists(tmp_path / "o")
    t = err("ruleset_info", {"verbose": "김합성"})
    assert "verbose" in t and "김합성" not in t
    t = err("yangdo_next_questions", {"facts": {"자산": [{"id": "A"}]}, "filer_path": RRN})
    assert "filer_path" in t and RRN not in t
    # 다른 도구의 인자를 옛 한글 이름으로 줘도 걸린다. 문장에는 받은 이름을 적는다
    t = err("yangdo_calculate", {"facts": CASES["A"], "문항": "P01"})
    assert "문항" in t and "받지 않는 인자" in t
    # 긴 이름은 잘라 적는다
    t = err("ruleset_info", {"x" * 300: 1})
    assert "x" * 41 not in t


def test_every_schema_property_and_old_name_is_accepted():
    """스키마가 알리는 이름과 그 옛 한글 이름은 모두 받는다(모르는 인자 검사에 걸리지 않는다)."""
    for tool in M.TOOLS:
        props = set(tool["inputSchema"]["properties"])
        assert M._unknown_arguments(tool["name"], {k: None for k in props}) == []
        old = {M.ALIASES[k]: None for k in props if k in M.ALIASES}
        assert M._unknown_arguments(tool["name"], old) == []
    assert M._unknown_arguments("ruleset_info", {}) == []


# ---- serverInfo.version ----

def test_server_version_matches_plugin_version():
    """serverInfo.version 은 플러그인 버전(.claude-plugin/plugin.json)과 같다. 플러그인 버전을 올리면 이 값도 올린다."""
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["result"]["serverInfo"] == {"name": "yangdo", "version": M.SERVER_VERSION}
    assert re.fullmatch(r"\d+\.\d+\.\d+", M.SERVER_VERSION)
    plugin = os.path.join(os.path.dirname(os.path.dirname(ROOT)), ".claude-plugin", "plugin.json")
    if not os.path.exists(plugin):
        pytest.skip("플러그인 저장소 없이 스킬 폴더만 있다")
    with open(plugin, encoding="utf-8") as fh:
        assert json.load(fh)["version"] == M.SERVER_VERSION


def test_answer_keeps_unrelated_tmp_sibling(tmp_path):
    p = write_json(tmp_path / "f.json", {"자산": [{"id": "A"}]})
    other = tmp_path / "f.json.tmp"
    other.write_text("남의 파일", encoding="utf-8")
    call("yangdo_answer", {"facts_path": p, "question": "P01", "value": True})
    assert other.read_text(encoding="utf-8") == "남의 파일"
    assert sorted(x.name for x in tmp_path.iterdir()) == ["f.json", "f.json.tmp"]
    assert json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))["신고인"]["거주자"] is True


def test_answer_failure_keeps_unrelated_tmp_sibling(tmp_path, monkeypatch):
    p = write_json(tmp_path / "f.json", {"자산": [{"id": "A"}]})
    other = tmp_path / "f.json.tmp"
    other.write_text("남의 파일", encoding="utf-8")

    def locked(src, dst):
        raise PermissionError(13, "Permission denied", dst)

    monkeypatch.setattr(M.os, "replace", locked)
    assert p in err("yangdo_answer", {"facts_path": p, "question": "P01", "value": True})
    assert other.read_text(encoding="utf-8") == "남의 파일"
    assert sorted(x.name for x in tmp_path.iterdir()) == ["f.json", "f.json.tmp"]


def test_unencodable_value_is_a_tool_error_and_leaves_no_temp_file(tmp_path):
    p = write_json(tmp_path / "f.json", {"자산": [{"id": "A"}]})
    before = (tmp_path / "f.json").read_text(encoding="utf-8")
    with pytest.raises(M.ToolError) as e:
        M._write_json(p, {"메모": "\ud800"})
    assert "저장할 수 없는 문자" in str(e.value)
    assert (tmp_path / "f.json").read_text(encoding="utf-8") == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["f.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 비트는 윈도우에 없다")
def test_answer_keeps_file_mode(tmp_path):
    import stat
    p = write_json(tmp_path / "f.json", {"자산": [{"id": "A"}]})
    os.chmod(p, 0o640)
    call("yangdo_answer", {"facts_path": p, "question": "P01", "value": True})
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o640


def test_calculate_keeps_unrelated_files_in_out_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    keep = {"메모.txt": "내 파일", "고객자료.csv": "a,b"}
    for n, body in keep.items():
        (out / n).write_text(body, encoding="utf-8")
    done = call("yangdo_calculate", {"facts": CASES["A"], "out_dir": str(out)})
    assert done["상태"] == "완료" and done["파일"]
    for n, body in keep.items():
        assert (out / n).read_text(encoding="utf-8") == body
    asked = call("yangdo_calculate", {"facts": CASES["L"], "out_dir": str(out)})
    assert asked["상태"] == "질문"
    for n, body in keep.items():
        assert (out / n).read_text(encoding="utf-8") == body


def test_instructions_say_how_to_start_a_new_case(tmp_path):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    ins = r["result"]["instructions"]
    assert 'facts: {"자산": [{"id": "A"}]}' in ins and "facts_path" in ins and "사실관계" in ins
    start = {"자산": [{"id": "A"}]}
    started = call("yangdo_answer", {"facts": start, "question": "P01", "value": True})
    assert started["사실관계"] == {"신고인": {"거주자": True}, "자산": [{"id": "A"}]}
    asked = call("yangdo_next_questions", {"facts": started["사실관계"], "limit": 10})["다음"]
    assert any(q["자산"] == "A" and q["id"].startswith("A") for q in asked)
    p = write_json(tmp_path / "new.json", start)
    call("yangdo_answer", {"facts_path": p, "question": "P01", "value": False})
    assert json.loads((tmp_path / "new.json").read_text(encoding="utf-8"))["신고인"]["거주자"] is False


# ---- 입력 스키마의 속성 이름은 ASCII, 옛 한글 이름으로 온 인자도 받는다 ----

SCHEMA_KEY = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")     # Claude 클라이언트가 받는 속성 이름 꼴. 다르면 도구를 통째로 뺀다


def _property_keys(node, path):
    """스키마 어느 깊이에 있든 properties 의 키를 (경로, 키) 로 모은다."""
    out = []
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            out += [(path, k) for k in props]
        for k, v in node.items():
            out += _property_keys(v, "%s.%s" % (path, k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _property_keys(v, "%s[%d]" % (path, i))
    return out


def test_schema_property_names_are_ascii():
    tools = M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert len(tools) == 7 + len(RETURN_TOOLS)
    seen = set()
    for t in tools:
        schema = t["inputSchema"]
        keys = _property_keys(schema, t["name"])
        for path, k in keys:
            assert SCHEMA_KEY.match(k), "%s: %s" % (path, k)
        seen |= {k for _, k in keys}
        for k in schema.get("required", []):
            assert k in schema["properties"], "%s: required %s" % (t["name"], k)
        assert "properties" not in schema["properties"].get("facts", {})      # 사실관계는 한글 키를 가진 자유 객체다
        for name, prop in schema["properties"].items():
            assert prop.get("description"), "%s.%s 에 설명이 없다" % (t["name"], name)
    assert set(M.ALIASES) <= seen                                              # 옛 이름마다 새 이름이 스키마에 있다
    for old in M.ALIASES.values():
        assert not SCHEMA_KEY.match(old)


def test_property_key_walk_reaches_nested_schemas():
    nested = {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "object", "properties": {"한글": {}}}}},
              "anyOf": [{"properties": {"b-1.c": {}}}]}
    assert sorted(k for _, k in _property_keys(nested, "t")) == ["a", "b-1.c", "한글"]


def test_old_korean_argument_names_still_work(tmp_path):
    f = {"자산": [{"id": "A"}]}
    r = call("yangdo_answer", {"facts": f, "문항": "A11", "값": "모름", "자산": "A"})
    assert "A11:A" in r["사실관계"]["모름"]
    assert call("yangdo_next_questions", {"facts": f, "서식": True})["다음"]
    assert call("yangdo_calculate", {"facts": CASES["A"], "오늘": "2026-10-09"})["기준정보"]["오늘"] == "2026-10-09"
    a = call("regulated_area", {"시도": "서울특별시", "시군구": "마포구", "읍면동": "공덕동", "기준일": "2026-10-09"})
    assert a["조정대상지역"]["지정"] is True
    b = call("regulated_area", {"시도": "경기도", "시군구": "화성시", "읍면동": "반송동", "기준일": "2018-01-01", "지구해당": "아니오"})
    assert "질문" not in b["조정대상지역"]
    assert "문항" in err("yangdo_answer", {"facts": f, "값": True})
    assert "기준일" in err("regulated_area", {"시도": "서울특별시", "시군구": "마포구", "기준일": "20261009"})


def test_old_and_new_name_together_is_an_error():
    t = err("yangdo_calculate", {"facts": CASES["A"], "today": "2026-10-09", "오늘": "2026-10-09"})
    assert "today" in t and "오늘" in t and "하나만" in t
    t = err("yangdo_answer", {"facts": {"자산": [{"id": "A"}]}, "question": "P01", "문항": "P01", "value": True})
    assert "question" in t and "하나만" in t


def test_arguments_are_not_changed_in_place():
    args = {"facts": CASES["A"], "오늘": "2026-10-09"}
    call("yangdo_calculate", args)
    assert sorted(args) == ["facts", "오늘"]


def test_instructions_name_the_return_tools():
    ins = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})["result"]["instructions"]
    assert all(t in ins for t in RETURN_TOOLS) and "filer_path" in ins
    for old in M.ALIASES.values():
        assert "%s=" % old not in ins and "`%s`" % old not in ins


def test_empty_facts_is_not_a_start():
    ids = [q["id"] for q in call("yangdo_next_questions", {"facts": {}, "limit": 10})["다음"]]
    assert ids == ["P01", "P05"]
    assert call("yangdo_calculate", {"facts": {}})["질문"][0]["문항"] == "P02"


# ---- 검토 반영: pymupdf 는 신고서 도구를 부를 때만 읽고, 없어도 계획 1 도구는 뜬다 ----

def _py(code, *argv):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-c", code, os.path.join(ROOT, "scripts")] + list(argv), capture_output=True,
                          text=True, encoding="utf-8", env=env, timeout=240)


def test_server_start_does_not_load_pymupdf():
    p = _py("import sys; sys.path.insert(0, sys.argv[1]); import mcp_server\n"
            "print(sorted(m for m in ('pymupdf', 'fitz', 'make_return') if m in sys.modules))")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "[]"


def test_plan1_tools_work_without_pymupdf(tmp_path):
    facts = write_json(tmp_path / "a.json", CASES["A"])
    filer = write_json(tmp_path / "g.json", {})
    code = ("import sys, json; sys.path.insert(0, sys.argv[1])\n"
            "sys.modules['pymupdf'] = None\n"                 # import pymupdf 가 ImportError 를 내게 한다
            "import mcp_server as M\n"
            "def rpc(name, args):\n"
            "    return M.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}})['result']\n"
            "out = {'tools': len(M.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']['tools'])}\n"
            "out['info'] = 'isError' not in rpc('ruleset_info', {})\n"
            "out['calc'] = json.loads(rpc('yangdo_calculate', {'facts_path': sys.argv[2]})['content'][0]['text'])['상태']\n"
            "for name in %r:\n"
            "    r = rpc(name, {'facts_path': sys.argv[2], 'filer_path': sys.argv[3], 'out_dir': sys.argv[4]})\n"
            "    out[name] = [r.get('isError'), r['content'][0]['text']]\n"
            "print(json.dumps(out, ensure_ascii=False))") % (RETURN_TOOLS,)
    p = _py(code, facts, filer, str(tmp_path / "o"))
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["tools"] == 7 + len(RETURN_TOOLS) and out["info"] is True and out["calc"] == "완료"
    for name in RETURN_TOOLS:
        is_error, text = out[name]
        assert is_error is True and "pymupdf" in text and "pip install" in text and "Traceback" not in text
    assert not os.path.exists(tmp_path / "o")


def test_mupdf_messages_go_to_stderr_after_return_tool_loads():
    code = ("import sys; sys.path.insert(0, sys.argv[1])\n"
            "import mcp_server as M\n"
            "M._load_make_return()\n"
            "import pymupdf\n"
            "pymupdf.message('MUPDF-표지')")
    p = _py(code)
    assert p.returncode == 0, p.stderr
    assert "MUPDF-표지" not in p.stdout and "MUPDF-표지" in p.stderr


def test_stdio_return_tool_keeps_stdout_clean(tmp_path):
    """pymupdf 가 올라오는 신고서 도구를 stdio 로 불러도 표준출력에는 프로토콜 줄만 나온다(_run_stdio 가 줄마다 JSON 으로 읽는다)."""
    import filers
    f = filers.get("A")
    facts = write_json(tmp_path / "a.json", CASES["A"])
    filer = write_json(tmp_path / "g.json", f)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": RETURN_TOOLS[-1], "arguments": {"facts_path": facts, "filer_path": filer,
                                                                "out_dir": str(tmp_path / "o"), "today": "2026-10-11"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"}]
    lines, p = _stdio(msgs)
    assert [x["id"] for x in lines] == [1, 2, 3]
    done = json.loads(lines[1]["result"]["content"][0]["text"])
    assert done["종료코드"] == 0
    if edition.PUBLIC:      # 공개본은 신고서 도구만 있고 응답에 전자신고 절이 없다
        assert "전자신고" not in done
    else:
        assert done["전자신고"]["파일명"] == "20261220C116300.01"
    text = lines[1]["result"]["content"][0]["text"]
    assert f["신고인"]["성명"] not in text and f["신고인"]["주민등록번호"] not in text
    assert b"\r" not in p.stdout
