# -*- coding: utf-8 -*-
import copy
import json
import os
import random
import re
import shutil
import subprocess
import sys

import pytest

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(SKILL, "질문지", "양도소득세_질문지.html")

sys.path.insert(0, os.path.join(SKILL, "scripts"))
import make_questionnaire_html as mq  # noqa: E402
from cases import CASES  # noqa: E402
from yangdo import facts as F  # noqa: E402
from yangdo import questions as Qs  # noqa: E402
from yangdo.calc import OK_EVIDENCE  # noqa: E402


def _env():
    """자식 프로세스의 표준 입출력과 파일을 UTF-8 로 고정한다(윈도 기본 cp949 에 기대지 않는다)."""
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def test_generated_html_is_up_to_date(tmp_path):
    out = tmp_path / "q.html"
    subprocess.run([sys.executable, os.path.join(SKILL, "scripts", "make_questionnaire_html.py"), "--출력", str(out)], check=True,
                   env=_env())
    assert out.read_bytes() == open(HTML, "rb").read()


def _html():
    with open(HTML, encoding="utf-8") as f:
        return f.read()


def _questions():
    with open(os.path.join(SKILL, "질문지", "문항.json"), encoding="utf-8") as f:
        return json.load(f)["문항"]


def _embedded(s, block):
    """HTML 에 넣은 JSON 블록(defs, conditions)."""
    m = re.search(r'<script id="%s" type="application/json">(.*?)</script>' % block, s, re.S)
    return json.loads(m.group(1))


def test_no_network_and_no_personal_questions():
    s = _html()
    assert not re.search(r"https?://(?!www\.law\.go\.kr)", s)      # 외부 스크립트·전송 없음. 근거 링크만 허용
    assert "fetch(" not in s and "XMLHttpRequest" not in s
    # 서식단계 문항(F0x, 인적사항 등)은 화면이 그리는 정의와 조건 목록에 아예 없다. 화면은 정의 JSON 에서만 문항을 만든다
    form_ids = {q["id"] for q in _questions() if q.get("범위") == "서식단계"}
    assert form_ids and all(i.startswith("F") for i in form_ids)
    defs, conds = _embedded(s, "defs"), _embedded(s, "conditions")
    shown = {q["id"] for q in defs["questions"]}
    assert shown and not shown & form_ids and not set(conds) & form_ids
    assert not [i for i in shown | set(conds) if re.fullmatch(r"F0\d", i)]
    for i in form_ids:                                       # 정의가 아닌 곳에도 문항 id 가 실리지 않았다
        assert ('"%s"' % i) not in s, i


def _csp(s):
    """CSP meta 의 지시문 {이름: [값]} 과 meta 가 시작하는 위치."""
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', s)
    assert m, "CSP meta 가 없다"
    policy = {}
    for part in m.group(1).split(";"):
        words = part.split()
        if words:
            assert words[0] not in policy
            policy[words[0]] = words[1:]
    return policy, m.start()


def test_csp_allows_only_what_the_page_uses():
    """외부 요청이 없다는 것을 브라우저가 지키게 한다. 기본은 모두 막고 이 파일 안의 스크립트와 스타일만 허용한다."""
    s = _html()
    policy, at = _csp(s)
    assert policy == {"default-src": ["'none'"], "script-src": ["'unsafe-inline'"], "style-src": ["'unsafe-inline'"],
                      "base-uri": ["'none'"], "form-action": ["'none'"]}
    # 정책은 스타일과 스크립트보다 앞에 있어야 그것들에 적용된다
    assert at < s.index("<style>") and at < s.index("<script")
    # 허용하지 않은 것을 페이지가 쓰지 않는다: 외부 스크립트·스타일·그림·글꼴·틀·양식, 문자열 실행
    assert not re.search(r"<script[^>]*\ssrc=|<link\b|<img\b|<iframe\b|<object\b|<embed\b|<form\b|<base\b", s)
    assert "@import" not in s and "url(" not in s and "@font-face" not in s
    assert not re.search(r"\beval\(|new Function\(|WebSocket|EventSource|sendBeacon|importScripts|new Worker", s)
    # 스크립트 블록은 넷뿐이다. 실행되는 것은 core 와 app 이고 나머지 둘은 자료(JSON)다
    assert re.findall(r"<script([^>]*)>", s) == [' id="defs" type="application/json"', ' id="conditions" type="application/json"',
                                                  ' id="core"', ' id="app"']


def test_csp_is_in_the_template_not_patched_into_the_output():
    assert "Content-Security-Policy" in mq.read("page.html") and _csp(mq.render())[0] == _csp(_html())[0]


def test_condition_table_matches_python():
    """HTML 에 넣은 조건 목록이 문항.json 의 보이는조건과 같다."""
    embedded = _embedded(_html(), "conditions")
    assert embedded == {q["id"]: q["보이는조건"] for q in _questions() if q.get("범위") != "서식단계"}


# ---- 생성물 점검 ---------------------------------------------------------------------------------
def test_html_does_not_depend_on_format_stage_questions(tmp_path):
    """서식단계 문항(인적사항 등)이 바뀌어도 생성물이 달라지지 않는다. 문항.json 전체의 해시나 판 정보를 넣지 않았다는 뜻이다."""
    doc = _doc()
    base = mq.render()
    doc2 = copy.deepcopy(doc)
    for q in doc2["문항"]:
        if q["범위"] == "서식단계":
            q["질문"] += " 바뀐 문장"
    doc2["문항"].append(dict(copy.deepcopy(doc2["문항"][-1]), id="F99", 질문="새 서식 문항"))
    doc2["작성일"] = "2030-01-01"
    p = tmp_path / "문항.json"
    p.write_text(json.dumps(doc2, ensure_ascii=False), encoding="utf-8")
    assert mq.render(str(p)) == base


def test_generated_html_has_no_banned_marks_in_screen_copy():
    """화면 문구에 줄표, 비유 명사, 한글 제품명을 쓰지 않았다. 문항 원문은 정의에서 그대로 온 것이라 이 점검에 넣지 않는다."""
    tpl = "".join(mq.read(n) for n in ("page.html", "app.js", "style.css"))
    assert chr(0x2014) not in tpl and "그리디" not in tpl
    assert not re.search(r"갈래|계단|사다리|행선지", tpl)
    assert "Gridie" in tpl


# ---- 화면 논리(core.js)를 node 로 돌려 파이썬과 견준다 -----------------------------------------------
NODE = shutil.which("node")
# CI(환경 변수 CI 가 있을 때)에서는 node 가 없어도 건너뛰지 않는다. 화면 논리 시험이 조용히 빠진 채 통과하지 않게 하려는 것이다.
# 건너뛰지 않은 시험은 _node 가 node 가 없다는 문장으로 실패시킨다
IN_CI = bool(os.environ.get("CI"))
needs_node = pytest.mark.skipif(NODE is None and not IN_CI, reason="node 가 없어 화면 논리 시험을 건너뛴다")
HARNESS = os.path.join(SKILL, "tests", "questionnaire_harness.js")
UNSET = object()


def _doc():
    with open(os.path.join(SKILL, "질문지", "문항.json"), encoding="utf-8") as f:
        return json.load(f)


def _node(payload):
    assert NODE, "node 가 없다. CI 에서는 화면 논리 시험을 건너뛰지 않는다. 작업에 node 를 깔아 준다"
    p = subprocess.run([NODE, HARNESS], input=json.dumps(payload).encode("utf-8"), capture_output=True, check=True, env=_env())
    return json.loads(p.stdout.decode("utf-8"))


def test_evidence_codes_cover_what_the_engine_accepts():
    """영수증 종류 선택지의 코드에 엔진이 경비로 받는 글자가 모두 있고, 선택지 코드는 엔진이 받는 증빙종류와 같다."""
    codes = {c for c, _ in mq.EVIDENCE}
    assert set(OK_EVIDENCE) <= codes
    assert [c for c, _ in mq.EVIDENCE] == list(F.EVIDENCE_KINDS)


def _referenced(cond, out):
    if cond == "항상":
        return out
    (_, items), = cond.items()
    for it in items:
        if isinstance(it, dict):
            _referenced(it, out)
        elif not it[0].startswith(("엔진.", "주택.")):
            out.add(it[0])
    return out


def _has_engine(cond):
    if cond == "항상":
        return False
    (_, items), = cond.items()
    return any(_has_engine(it) if isinstance(it, dict) else it[0].startswith(("엔진.", "주택.")) for it in items)


@needs_node
def test_condition_interpreter_matches_python():
    """문항.json 의 보이는조건 전부를 앞 답의 여러 조합으로 판정해 yangdo/questions.py 와 같은 결과인지 본다.

    파이썬은 참, 거짓, 모름(None)이고 화면은 T, F, U(앞 답을 기다림), E(엔진 값이 필요)다. 엔진 값은 두 쪽 모두 모른다.
    """
    doc = _doc()
    qmap = {q["id"]: q for q in doc["문항"]}
    defs, conds = mq.build(doc)
    shown = [q for q in doc["문항"] if q["범위"] != "서식단계"]
    cands = {}
    for q in shown:
        for qid in _referenced(q["보이는조건"], set()):
            r = qmap[qid]
            assert r["답형식"] in ("예아니오", "선택"), "조건이 이 형식의 답을 가리키면 이 시험의 후보 값을 늘려야 한다: " + qid
            cands[qid] = [True, False] if r["답형식"] == "예아니오" else [o["코드"] for o in r["선택지"]]
    rng = random.Random(20261011)
    cases, expected = [], []
    for q in shown:
        refs = _referenced(q["보이는조건"], set())
        for _ in range(60 if refs else 1):
            values = {r: rng.choice(cands[r] + [UNSET]) for r in sorted(refs)}
            f, asset = {}, {"id": "a1"}
            for r, v in values.items():
                if v is not UNSET:
                    Qs.write(f, qmap[r]["키"][0], v, asset=asset)
            py = Qs._visible(q["보이는조건"], f, {}, asset, None, qmap, q["id"])
            cases.append({"qid": q["id"], "values": {r: v for r, v in values.items() if v is not UNSET}})
            expected.append((q["id"], py, _has_engine(q["보이는조건"])))
    got = _node({"mode": "cond", "defs": defs, "conds": conds, "cases": cases})["states"]
    assert len(got) == len(expected)
    seen = set()
    for (qid, py, engine), js in zip(expected, got):
        seen.add(js)
        if py is True:
            assert js == "T", (qid, py, js)
        elif py is False:
            assert js == "F", (qid, py, js)
        else:
            assert js in ("U", "E"), (qid, py, js)
            assert js == "U" or engine, (qid, "엔진 항목이 없는데 E", js)
    assert seen == {"T", "F", "U", "E"}


@needs_node
def test_condition_operators_match_python():
    """조건표기의 연산자 여덟 가지와 모두·하나라도를 가짜 문항으로 견준다."""
    qmap = {"Z1": {"id": "Z1", "키": ["연간.z1"]}, "Z2": {"id": "Z2", "키": ["연간.z2"]}}
    items = [["Z1", "==", 3], ["Z1", "!=", 3], ["Z1", "in", [1, 2]], ["Z1", "not_in", [1, 2]], ["Z1", ">=", 3], ["Z1", "<=", 3],
             ["Z1", "<", 3], ["Z1", ">", 3], ["Z2", "==", "가"], ["Z2", ">=", "나"]]
    conds = {"C%d" % i: {"모두": [it]} for i, it in enumerate(items)}
    conds["ALL"] = {"모두": [["Z1", ">=", 2], ["Z2", "==", "가"], ["엔진.x", "==", True]]}
    conds["ANY"] = {"하나라도": [["Z1", ">=", 2], ["Z2", "==", "가"], ["엔진.x", "==", True]]}
    conds["NEST"] = {"모두": [["Z1", ">=", 1], {"하나라도": [["Z2", "==", "가"], ["Z1", ">", 5]]}]}
    conds["ALWAYS"] = "항상"
    vals = [UNSET, 1, 2, 3, 4, 9, "가", "나"]
    cases, exp = [], []
    for cid, cond in conds.items():
        for z1 in vals:
            for z2 in vals:
                f, values = {"연간": {}}, {}
                if z1 is not UNSET:
                    f["연간"]["z1"] = values["Z1"] = z1
                if z2 is not UNSET:
                    f["연간"]["z2"] = values["Z2"] = z2
                cases.append({"qid": cid, "values": values})
                exp.append(Qs._visible(cond, f, {}, None, None, qmap, cid))
    got = _node({"mode": "cond", "defs": {"questions": []}, "conds": conds, "cases": cases})["states"]
    for e, g, c in zip(exp, got, cases):
        if e is True:
            assert g == "T", (e, g, c)
        elif e is False:
            assert g == "F", (e, g, c)
        else:
            assert g in ("U", "E"), (e, g, c)


def _value_of(q, root, asset=None, house=None):
    """문항 하나의 답을 사실관계에서 읽는다. 키가 여럿이면 {이름: 값} 묶음. 없으면 None."""
    keys = q["keys"]
    if len(keys) == 1:
        return Qs.read(root, keys[0], asset, house)
    out = {k.rsplit(".", 1)[-1]: Qs.read(root, k, asset, house) for k in keys}
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def _to_ui(spec, v, pick_none=False):
    """사실관계 값을 화면 입력값으로(core.js 의 toOut 의 거꾸로)."""
    t = spec["t"]
    if t == "multi" and pick_none and not v and spec.get("alone"):
        return [spec["alone"][0]]
    if t in ("bool", "choice", "sido", "text", "date", "multi", "addr"):
        return v
    if t in ("int", "num"):
        return str(v)
    if t == "share":
        return {"kind": "단독"} if v == "단독" else {"kind": "공동", "n": str(v["분자"]), "d": str(v["분모"])}
    if t == "obj":
        return {fd["n"]: _to_ui(fd["s"], v[fd["n"]]) for fd in spec["fields"] if v.get(fd["n"]) is not None}
    if t == "list":
        if not v:
            return {"rows": [], "none": True}
        if spec["as"] == "pairs":
            return {"rows": [{"a": p[0], "b": p[1]} for p in v], "none": False}
        if spec["as"] == "scalars":
            return {"rows": [str(x) for x in v], "none": False}
        return {"rows": [_to_ui(spec["row"], r) for r in v], "none": False}
    raise AssertionError(t)


def _store_from_facts(f, defs, pick_none=False):
    """pick_none: 복수선택의 빈 목록을 화면에서는 「해당 없음」 류를 골라 나타낸다(빈 채로 두면 답하지 않은 것이다)."""
    qs = defs["questions"]
    store = {"v": 1, "nextAsset": 99, "nextHouse": 99, "hidePending": False, "glob": {"ans": {}, "mo": {}}, "assets": [], "houses": []}
    for q in qs:
        if q["unit"] == "전역" and q["spec"]["t"] != "houses":
            v = _value_of(q, f)
            if v is not None:
                store["glob"]["ans"][q["id"]] = _to_ui(q["spec"], v, pick_none)
    for a in f["자산"]:
        holder = {"id": a["id"], "ans": {}, "mo": {}}
        for q in qs:
            if q["unit"] == "자산":
                v = _value_of(q, f, asset=a)
                if v is not None:
                    holder["ans"][q["id"]] = _to_ui(q["spec"], v, pick_none)
        store["assets"].append(holder)
    hr = defs["houseRow"]
    names = {fd["n"]: fd for fd in hr["main"] + hr["extra"]}
    for h in F.get(f, "세대.주택목록") or []:
        row = {"id": h["id"], "asset": h.get("자산id"), "f": {}}
        for n, fd in names.items():
            if h.get(n) is not None and not (n == "제12호해당" and h[n] == "해당없음"):
                row["f"][n] = _to_ui(fd["s"], h[n])
        store["houses"].append(row)
    if store["houses"]:
        store["glob"]["ans"]["H04"] = {"done": True}
    return store


def _subset(out, orig, path=""):
    """out 의 값이 모두 orig 에 같은 자리로 있다."""
    if isinstance(out, dict):
        assert isinstance(orig, dict), (path, out, orig)
        for k, v in out.items():
            assert k in orig, (path + "." + k, v)
            _subset(v, orig[k], path + "." + k)
    elif isinstance(out, list):
        assert isinstance(orig, list) and len(out) == len(orig), (path, out, orig)
        for i, (x, y) in enumerate(zip(out, orig)):
            _subset(x, y, "%s[%d]" % (path, i))
    else:
        assert out == orig, (path, out, orig)


@needs_node
def test_html_facts_reproduce_python_cases():
    """합성 사례의 사실관계를 화면 입력값으로 옮겨 화면 논리로 사실관계를 다시 만들면, 화면이 묻는 문항의 값이 같다."""
    doc = _doc()
    defs, conds = mq.build(doc)
    names = sorted(CASES)
    stores = [_store_from_facts(CASES[n], defs) for n in names]
    results = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": stores})["results"]
    asked = 0
    for n, res in zip(names, results):
        orig, out = CASES[n], res["facts"]
        assert res["errors"] == [], (n, res["errors"])
        # 1) 화면이 만든 값은 모두 원래 사실관계에 있다
        _subset({k: v for k, v in out.items() if k not in ("자산", "세대")}, orig, n)
        _subset(out.get("세대", {}), orig["세대"], n + ".세대")
        assert [a["id"] for a in out["자산"]] == [a["id"] for a in orig["자산"]]
        for oa, a in zip(out["자산"], orig["자산"]):
            _subset(oa, a, n + "." + a["id"])
        # 2) 화면이 묻는 문항(보이거나 회계사 확인)에 원래 값이 있으면 화면 결과에도 있다
        st = res["states"]
        for q in defs["questions"]:
            if q["spec"]["t"] == "houses" or q["zone"] == "row":
                continue
            units = [a["id"] for a in orig["자산"]] if q["unit"] == "자산" else [""]
            for u in units:
                if st[q["id"]][u] not in ("T", "E"):
                    continue
                a = next((x for x in orig["자산"] if x["id"] == u), None)
                want = _value_of(q, orig, asset=a)
                if want is None or (q["spec"]["t"] == "multi" and not want):   # 복수선택의 빈 목록은 화면에서 고르지 않은 것이다
                    continue
                got_a = next((x for x in out["자산"] if x["id"] == u), None)
                got = _value_of(q, out, asset=got_a)
                asked += 1
                assert got is not None, (n, q["id"], u, "화면 결과에 값이 없다")
                _subset(got, want, "%s.%s" % (n, q["id"]))
    assert asked > 100


@needs_node
def test_html_blocks_wrong_inputs_and_keeps_empty_ones_out():
    doc = _doc()
    defs, conds = mq.build(doc)
    store = _store_from_facts(CASES["S1"], defs)
    a = store["assets"][0]["ans"]
    a["A11"] = "2026-02-30"                                    # 달력에 없는 날
    a["M01"] = "1.5억"                                         # 정수가 아닌 금액
    a["H07"] = {"rows": [{"a": "2025-01-02", "b": "2024-01-02"}], "none": False}   # 끝이 시작보다 앞
    a["P04"] = {"kind": "공동", "n": "3", "d": "2"}             # 분자가 분모보다 크다
    a["A01"] = {"시도": "서울특별시", "시군구": "", "읍면동": "성수동"}   # 시군구 없음
    a["M08"] = {"rows": [{"내용": "중개수수료", "금액": "100"}], "none": False}   # 증빙종류 없음
    a["M10"] = {"rows": [{}], "none": False}                    # 빈 줄은 건너뛴다
    del a["M12"]
    store["houses"][1]["f"]["취득일"] = ""                       # 판 집이 아닌 집에 산 날이 없다
    out = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
    errs = {(e["qid"], e["unit"]) for e in out["errors"]}
    sid = store["assets"][0]["id"]
    assert errs >= {("A11", sid), ("M01", sid), ("H07", sid), ("P04", sid), ("A01", sid), ("M08", sid), ("H04", "")}
    assert ("M10", sid) not in errs
    fa = out["facts"]["자산"][0]
    assert "감가상각비" not in fa
    assert "기타" not in fa.get("필요경비", {})


def test_expense_rows_have_an_optional_business_number_cell():
    """M08~M11 의 지출 줄에 지급처 사업자번호 칸이 있다. 전자신고 07 레코드의 필수 구분코드 지출에 쓰이고(질문 F07), 비워도 된다."""
    defs, _ = mq.build(_doc())
    seen = []
    for q in defs["questions"]:
        if q["id"] not in ("M08", "M09", "M10", "M11"):
            continue
        row = q["spec"]["row"]
        cell = next(f for f in row["fields"] if f["n"] == "사업자번호")
        assert cell["s"]["t"] == "text" and cell["s"]["digits"] == 10 and "사업자번호" not in row["req"], q["id"]
        seen.append(q["id"])
    assert seen == ["M08", "M09", "M10", "M11"]
    assert '"n":"사업자번호"' in open(HTML, encoding="utf-8").read()


@needs_node
def test_html_business_number_cell_drops_hyphens_and_blocks_wrong_input():
    defs, conds = mq.build(_doc())

    def run(number):
        store = _store_from_facts(CASES["S1"], defs)
        store["assets"][0]["ans"]["M08"]["rows"][0]["사업자번호"] = number
        out = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
        return out, store["assets"][0]["id"]

    out, sid = run("000-00-00015 ")
    assert out["errors"] == [] and out["facts"]["자산"][0]["필요경비"]["취득부대"][0]["사업자번호"] == "0000000015"
    out, sid = run("")                                           # 비워도 된다
    assert out["errors"] == [] and "사업자번호" not in out["facts"]["자산"][0]["필요경비"]["취득부대"][0]
    for bad in ("12345", "00000000150", "0000000015".replace("0", chr(0xFF10)), "abcdefghij"):
        out, sid = run(bad)
        assert [(e["qid"], e["unit"]) for e in out["errors"]] == [("M08", sid)], bad
        assert "숫자 10자리" in out["errors"][0]["msg"]


@needs_node
def test_html_marks_unknown_answers_and_drops_hidden_ones():
    doc = _doc()
    defs, conds = mq.build(doc)
    store = _store_from_facts(CASES["S1"], defs)
    a = store["assets"][0]
    sid = a["id"]
    a["mo"]["A12"] = True                                       # 모르겠어요
    a["ans"]["A05"] = "2020-01-01"                              # A04 가 아파트라 보이지 않는 문항의 옛 답
    store["glob"]["ans"]["P07"] = True                          # P05 가 아니오라 보이지 않는다
    res = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
    assert "A12:%s" % sid in res["facts"]["모름"]
    assert "주거사용개시일" not in res["facts"]["자산"][0]
    assert "같은날양도순서" not in res["facts"].get("연간", {})
    assert res["states"]["A05"][sid] == "F" and res["states"]["P07"][""] in ("F", "U")


@needs_node
def test_two_assets_follow_python_unit_rule():
    """자산이 둘이면 세대·주택 문항은 자산 하나라도 조건이 참일 때 묻는다(questions.py 의 _units 규칙)."""
    doc = _doc()
    defs, conds = mq.build(doc)
    store = _store_from_facts(CASES["BF"], defs)             # 주택 B 와 토지 F
    res = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
    st = res["states"]
    assert st["H01"][""] == "T" and st["A04"]["B"] == "T" and st["A04"]["F"] == "F"
    store["assets"][0]["ans"]["P02"] = "토지"                   # 둘 다 토지가 되면 세대 문항이 사라진다
    res = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
    assert res["states"]["H01"][""] == "F"
    assert "주택목록" not in res["facts"].get("세대", {})


@needs_node
def test_condition_states_tell_waiting_from_engine_needed():
    """앞 답을 기다리는 문항(U)과 엔진 값이 있어야 정해지는 문항(E)을 가른다. 앞 것은 숨기고 뒤 것은 회계사 확인으로 둔다."""
    conds = {"A": {"모두": [["Z1", ">=", 2], ["엔진.x", "==", True]]},
             "B": {"하나라도": [["엔진.x", "==", True], ["Z1", "==", 5]]},
             "C": {"모두": [["Z1", ">=", 2], ["Z2", "==", "가"], ["엔진.x", "==", True]]}}
    cases = [{"qid": "A", "values": {}}, {"qid": "A", "values": {"Z1": 3}}, {"qid": "A", "values": {"Z1": 1}},
             {"qid": "B", "values": {}}, {"qid": "B", "values": {"Z1": 5}}, {"qid": "B", "values": {"Z1": 4}},
             {"qid": "C", "values": {"Z1": 3}}, {"qid": "C", "values": {"Z1": 3, "Z2": "가"}}, {"qid": "C", "values": {"Z1": 3, "Z2": "나"}}]
    got = _node({"mode": "cond", "defs": {"questions": []}, "conds": conds, "cases": cases})["states"]
    assert got == ["U", "E", "F", "U", "T", "E", "U", "E", "F"]


@needs_node
def test_html_writes_composite_answers_in_facts_shape():
    """지분, 면적, 환산 입력(매매사례가액·감정가액·기준시가), 신축·증축, 토지거래허가 같은 묶음 답이 사실관계 모양으로 나온다."""
    doc = _doc()
    defs, conds = mq.build(doc)
    store = _store_from_facts(CASES["S1"], defs)
    sid = store["assets"][0]["id"]
    a = store["assets"][0]["ans"]
    a["P04"] = {"kind": "공동", "n": "1", "d": "2"}
    a["A20"] = {"토지": "30.5", "건물": "84"}
    a["M05"] = "모름"
    a["M21"] = {"매매사례가액": "1,200,000,000", "감정가액": {"rows": ["100", "200"], "none": False}}
    a["M22"] = {"취득": {"주택": "400,000,000"}, "양도": {"주택": "650000000"}}
    a["M23"] = {"사용승인일": "2020-01-01"}
    a["X05"] = "예"
    a["X06"] = {"신청일": "2026-06-01", "허가일": "2026-06-20"}
    a["M24"] = {"개별공시지가": "50000", "토지등급": "30"}
    res = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
    assert res["errors"] == []
    fa = res["facts"]["자산"][0]
    assert fa["지분"] == {"구분": "공동", "분자": 1, "분모": 2}
    assert fa["면적"] == {"토지": 30.5, "건물": 84}
    assert fa["매매사례가액"] == 1200000000 and fa["감정가액"] == [100, 200]
    assert fa["기준시가"] == {"취득": {"주택": 400000000}, "양도": {"주택": 650000000}}
    assert fa["신축증축"] == {"사용승인일": "2020-01-01"}
    assert fa["토지거래허가대상"] == "예" and fa["토지거래허가"] == {"신청일": "2026-06-01", "허가일": "2026-06-20"}
    assert fa["토지등급"] == {"개별공시지가": 50000, "토지등급": 30}
    assert "전체취득가액" not in fa and "취득가액_확인" in fa      # M05 가 모름이라 M06~M11 이 숨는다
    assert sid == fa["id"]
    # 같은 결과를 파이썬 쪽 검사도 받아들인다(형식 검사: 예아니오·선택·복수선택·목록, 부수토지 등)
    f2 = copy.deepcopy(res["facts"])
    F.check_personal(f2)
    for q in doc["문항"]:
        if q["범위"] == "서식단계" or q["답형식"] != "선택":
            continue
        for key in q["키"]:
            where, parts = F.split_key(key)
            if where == "자산":
                v = F.get(fa, ".".join(parts))
                if v is not None:
                    assert F.form_problem(q, v) is None, (q["id"], v)


@needs_node
def test_html_facts_give_the_same_tax_as_the_cases():
    """화면이 만든 사실관계를 엔진에 넣으면 합성 사례와 같은 산출세액이 나온다(S1 포함). 화면이 묻는 문항만으로 계산이 되는지 본다."""
    from yangdo import engine
    doc = _doc()
    defs, conds = mq.build(doc)
    names = [n for n in sorted(CASES) if engine.calculate(CASES[n], today="2026-10-11")["상태"] == "완료"]
    assert "S1" in names and len(names) >= 15
    stores = [_store_from_facts(CASES[n], defs, pick_none=True) for n in names]
    results = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": stores})["results"]
    for n, res in zip(names, results):
        want = engine.calculate(CASES[n], today="2026-10-11")
        got = engine.calculate(res["facts"], today="2026-10-11")
        assert got["상태"] == "완료", (n, got["질문"], got["다루지않음"])
        assert got["계산"]["합계"]["산출세액"] == want["계산"]["합계"]["산출세액"], n
        assert got["계산"]["합계"]["지방소득세"] == want["계산"]["합계"]["지방소득세"], n


def test_default_screen_shows_engine_condition_questions():
    """엔진 값이 있어야 필요 여부가 정해지는 문항(필요경비, 거주 기간 등)도 기본 화면에 보인다. 끄는 선택만 남겼다."""
    s = open(HTML, encoding="utf-8").read()
    assert "hidePending: false" in s and "showPending" not in s
    assert 'id="hide-pending"' in s and "회계사가 확인하는 항목 숨기기" in s
    assert "이 질문이 필요한지는 회계사가 확인합니다. 해당하면 답해 주세요." in s
    assert "!store.hidePending" in s       # 엔진 조건 문항(상태 E)은 숨기기를 켜지 않는 한 보인다


@needs_node
def test_s1_filled_on_default_screen_gives_38349466(tmp_path):
    """기본 화면에서 S1 을 끝까지 넣어 받은 JSON 으로 run.py 가 38,349,466원을 낸다. 필요경비와 거주 기간은 엔진 조건 문항이다."""
    defs, conds = mq.build(_doc())
    store = _store_from_facts(CASES["S1"], defs, pick_none=True)
    res = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [store]})["results"][0]
    assert res["errors"] == []
    sid = store["assets"][0]["id"]
    for qid in ("M05", "M06", "M07", "M08", "M09", "M11", "H07"):
        assert res["states"][qid][sid] in ("T", "E"), qid          # 화면이 이 문항을 묻는다(상태 E 는 기본으로 보인다)
    assert any(res["states"][q][sid] == "E" for q in ("M06", "M08", "H07"))
    path = tmp_path / "양도소득세_답변.json"
    path.write_text(json.dumps(res["facts"], ensure_ascii=False, indent=2), encoding="utf-8")
    p = subprocess.run([sys.executable, os.path.join(SKILL, "scripts", "run.py"), "--사실관계", str(path), "--출력", str(tmp_path / "out"),
                        "--오늘", "2026-10-11"], capture_output=True, encoding="utf-8", env=_env())
    assert p.returncode == 0, p.stdout + p.stderr
    assert "38,349,466" in p.stdout


@needs_node
def test_unanswered_engine_condition_questions_stay_out_of_the_json():
    """답하지 않은 문항은 빈 값으로 사실관계에 들어가지 않는다. 엔진 조건 문항도 같다."""
    defs, conds = mq.build(_doc())
    # 판 집(주택) 하나만 고르고 아무것도 답하지 않은 화면
    empty = {"v": 1, "nextAsset": 2, "nextHouse": 2, "hidePending": False, "glob": {"ans": {}, "mo": {}},
             "assets": [{"id": "자산1", "ans": {"P02": "주택"}, "mo": {}}], "houses": [{"id": "H1", "asset": "자산1", "f": {}}]}
    # 합성 사례에서 엔진 조건 문항의 답만 지운 화면
    names = sorted(CASES)
    full = [_store_from_facts(CASES[n], defs, pick_none=True) for n in names]
    stores = [empty]
    for st in full:
        base = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": [st]})["results"][0]["states"]
        cut = copy.deepcopy(st)
        for q in defs["questions"]:
            if q["zone"] == "row":
                continue
            for unit, state in base[q["id"]].items():
                if state == "E":
                    holder = next(a for a in cut["assets"] if a["id"] == unit) if q["unit"] == "자산" else cut["glob"]
                    holder["ans"].pop(q["id"], None)
        for row in cut["houses"]:
            for fd in defs["houseRow"]["extra"]:
                row["f"].pop(fd["n"], None)
        stores.append(cut)
    results = _node({"mode": "facts", "defs": defs, "conds": conds, "stores": stores})["results"]
    assert results[0]["facts"] == {"세대": {"주택목록": [{"id": "H1", "자산id": "자산1"}]}, "자산": [{"id": "자산1", "종류": "주택"}]}
    assert "모름" not in results[0]["facts"]
    for n, st, res in zip(["빈 화면"] + names, stores, results):
        out = res["facts"]
        for q in defs["questions"]:
            if q["zone"] == "row" or q["spec"]["t"] == "houses":
                continue
            for unit, state in res["states"][q["id"]].items():
                if state != "E":
                    continue
                a = next((x for x in out["자산"] if x["id"] == unit), None)
                assert _value_of(q, out, asset=a) is None, (n, q["id"], unit, "답하지 않은 엔진 조건 문항이 JSON 에 있다")
        for row in out.get("세대", {}).get("주택목록", []):
            for fd in defs["houseRow"]["extra"]:
                assert fd["n"] not in row, (n, row["id"], fd["n"])
        assert not [m for m in out.get("모름", []) if m.split(":")[0] in {q["id"] for q in defs["questions"] if q["zone"] != "row"} and
                    res["states"][m.split(":")[0]].get(m.split(":", 1)[1]) == "E"]
