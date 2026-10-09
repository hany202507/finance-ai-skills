import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coverage_check as cc  # noqa: E402


def row(name, mst, ef, prom="20260101", no="1"):
    return {"법령명한글": name, "법령일련번호": mst, "시행일자": ef, "공포일자": prom, "공포번호": no}


def pages(*rows_per_page):
    total = sum(len(r) for r in rows_per_page)
    def search(name, page):
        rows = rows_per_page[page - 1] if page <= len(rows_per_page) else []
        return {"LawSearch": {"totalCnt": str(total), "law": rows}}
    return search


def test_norm():
    assert cc.norm("댐건설·관리 및 주변지역지원") == cc.norm("댐건설ㆍ관리 및  주변지역지원")


def test_parse_taxdoctor_list():
    text = "수록 현행 법령 2건 (국세 2):\n- 소득세법 (법률, 시행 2026.07.01)\n- 소득세법 시행령 (대통령령, 시행 2026.10.01)\n"
    got = cc.parse_taxdoctor_list(text)
    assert got == {cc.norm("소득세법"): "20260701", cc.norm("소득세법 시행령"): "20261001"}


def test_parse_taxdoctor_list_reads_local_tax_tag_at_line_end():
    text = ("수록 현행 법령 2건:\n"
            "- 소득세법 (법률, 시행 2026.07.01)\n"
            "- 지방세법 (법률, 시행 2026.07.01) [지방세]\n"
            "- 지방세법 시행령 (대통령령, 시행 2026.10.01) [지방세]\n")
    got = cc.parse_taxdoctor_list(text)
    assert got == {cc.norm("소득세법"): "20260701", cc.norm("지방세법"): "20260701", cc.norm("지방세법 시행령"): "20261001"}


def test_resolve_finds_exact_on_second_page_and_in_force_version():
    search = pages([row("민간임대주택에 관한 특별법", "1", "20260101")],
                   [row("주택법", "289171", "20270309", "20260901"), row("주택법", "289171", "20260908", "20260301")])
    hit = cc.resolve(search, "주택법", "20261009")
    assert (hit["법령일련번호"], hit["시행일자"]) == ("289171", "20260908")


def test_resolve_none_when_no_exact_name():
    assert cc.resolve(pages([row("공영주택법", "9", "19630101")]), "주택법", "20261009") is None


def test_find_admrul():
    def search_admrul(name, page):
        return {"AdmRulSearch": {"totalCnt": "1", "admrul": [{"행정규칙ID": "85055", "행정규칙명": "조정대상지역 지정", "행정규칙일련번호": "2100000281588", "발령일자": "20260701"}]}}
    assert cc.find_admrul(search_admrul, "조정대상지역", "85055")["행정규칙일련번호"] == "2100000281588"
    assert cc.find_admrul(search_admrul, "조정대상지역", "99999") is None


LISTING = {
    "주제": "시험",
    "법령": [
        {"이름": "소득세법", "구분": "세법"},
        {"이름": "주택법", "구분": "비세법"},
        {"이름": "토지수용법", "구분": "비세법"},
        {"이름": "채권은행협의회 운영협약", "구분": "비세법"},
        {"이름": "없는법", "구분": "비세법"},
    ],
    "고시": [
        {"이름": "조정대상지역 지정·해제 공고", "분류": "지역목록", "출처": {"종류": "행정규칙", "행정규칙ID": "85055", "검색어": "조정대상지역"}},
        {"이름": "개별공시지가", "분류": "개별사실", "출처": {"종류": "확인처", "곳": ["부동산공시가격알리미"]}},
        {"이름": "빈 확인처", "분류": "개별사실", "출처": {"종류": "확인처", "곳": []}},
    ],
}
ALIASES = {"별칭": [
    {"인용명": "토지수용법", "현행명": "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률", "종류": "폐지대체", "근거": "2002 공익사업법 제정으로 폐지", "등급": "★★★"},
    {"인용명": "채권은행협의회 운영협약", "현행명": "", "종류": "비법령", "근거": "은행 간 협약. 법령 아님", "등급": "★★☆"},
]}


def fake_search(name, page):
    table = {
        "소득세법": [row("소득세법", "280405", "20260701")],
        "주택법": [row("주택법", "289171", "20260908")],
        "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률": [row("공익사업을 위한 토지 등의 취득 및 보상에 관한 법률", "1", "20260101")],
    }
    rows = table.get(name, []) if page == 1 else []
    return {"LawSearch": {"totalCnt": str(len(table.get(name, []))), "law": rows}}


def fake_admrul(name, page):
    return {"AdmRulSearch": {"totalCnt": "1", "admrul": [{"행정규칙ID": "85055", "행정규칙명": "조정대상지역 지정", "행정규칙일련번호": "1", "발령일자": "20260701"}]}}


def test_check_report():
    rep = cc.check(LISTING, ALIASES, fake_search, fake_admrul, {cc.norm("소득세법"): "20260701"}, "20261009")
    by = {x["이름"]: x for x in rep["항목"]}
    assert by["소득세법"]["해소"] and by["소득세법"]["TaxDoctor"] is True
    assert by["주택법"]["해소"] and by["주택법"]["TaxDoctor"] is None
    assert by["토지수용법"]["해소"] and by["토지수용법"]["현행명"].startswith("공익사업")
    assert by["채권은행협의회 운영협약"]["해소"] and "법령 아님" in by["채권은행협의회 운영협약"]["사유"]
    assert not by["없는법"]["해소"]
    assert by["조정대상지역 지정·해제 공고"]["해소"]
    assert by["개별공시지가"]["해소"]
    assert not by["빈 확인처"]["해소"]
    assert rep["요약"] == {"전체": 8, "해소": 6, "미해소": 2, "경고": 0}


def test_check_warns_when_tax_law_not_in_taxdoctor():
    listing = {"주제": "시험", "법령": [{"이름": "소득세법", "구분": "세법"}], "고시": []}
    rep = cc.check(listing, {"별칭": []}, fake_search, fake_admrul, {}, "20261009")
    item = rep["항목"][0]
    assert item["해소"] and item["TaxDoctor"] is False
    assert rep["요약"]["경고"] == 1


def test_main_exit_codes(tmp_path, monkeypatch):
    lp = tmp_path / "l.json"; ap = tmp_path / "a.json"; op = tmp_path / "o.json"
    import json
    lp.write_text(json.dumps(LISTING, ensure_ascii=False), encoding="utf-8")
    ap.write_text(json.dumps(ALIASES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (fake_search, fake_admrul, None))
    code = cc.main(["--목록", str(lp), "--별칭", str(ap), "--출력", str(op), "--기준일", "20261009", "--TaxDoctor생략"])
    assert code == 1
    assert json.loads(op.read_text(encoding="utf-8"))["요약"]["미해소"] == 2


# ---- 수정 1: TaxDoctor JSON-RPC 응답 처리 ----

SSE_NOTE = 'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info"}}\n\n'
SSE_RESULT = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"content":[]}}\n\n'
SSE_ERROR = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"error":{"code":-32602,"message":"Invalid params"}}\n\n'


def test_parse_rpc_body_single_json():
    msg = cc.parse_rpc_body('{"jsonrpc":"2.0","id":1,"result":{"ok":true}}', 1)
    assert msg["result"] == {"ok": True}


def test_parse_rpc_body_sse_skips_notification_event_before_result():
    msg = cc.parse_rpc_body(SSE_NOTE + SSE_RESULT, 2)
    assert msg["id"] == 2 and msg["result"] == {"content": []}


def test_parse_rpc_body_sse_with_crlf_line_endings():
    msg = cc.parse_rpc_body((SSE_NOTE + SSE_RESULT).replace("\n", "\r\n"), 2)
    assert msg["id"] == 2


def test_parse_rpc_body_sse_error_raises():
    with pytest.raises(RuntimeError, match="TaxDoctor 오류: -32602 Invalid params"):
        cc.parse_rpc_body(SSE_NOTE + SSE_ERROR, 2)


def test_parse_rpc_body_plain_json_error_raises():
    with pytest.raises(RuntimeError, match="TaxDoctor 오류: -32000 boom"):
        cc.parse_rpc_body('{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"boom"}}', 1)


def test_parse_rpc_body_raises_when_no_message_has_the_request_id():
    with pytest.raises(RuntimeError, match="id 2"):
        cc.parse_rpc_body(SSE_NOTE, 2)


def _tools_call_body(text):
    result = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": text}]}}
    return SSE_NOTE + "event: message\ndata: " + json.dumps(result, ensure_ascii=False) + "\n\n"


def test_taxdoctor_names_sends_initialized_notification_with_session(monkeypatch):
    calls = []

    def fake_post(payload, sid=None):
        calls.append((payload["method"], sid, "id" in payload))
        if payload["method"] == "initialize":
            return '{"jsonrpc":"2.0","id":1,"result":{}}', "SID-1"
        if payload["method"] == "notifications/initialized":
            return "", None
        return _tools_call_body("수록 현행 법령 1건 (국세 1):\n- 소득세법 (법률, 시행 2026.07.01)\n"), None

    monkeypatch.setattr(cc, "_post", fake_post)
    assert cc.taxdoctor_names() == {cc.norm("소득세법"): "20260701"}
    assert calls == [("initialize", None, True), ("notifications/initialized", "SID-1", False), ("tools/call", "SID-1", True)]


def test_taxdoctor_names_reports_rpc_error_instead_of_generic_message(monkeypatch):
    def fake_post(payload, sid=None):
        if payload["method"] == "initialize":
            return '{"jsonrpc":"2.0","id":1,"result":{}}', "SID-1"
        if payload["method"] == "notifications/initialized":
            return "", None
        return SSE_ERROR, None

    monkeypatch.setattr(cc, "_post", fake_post)
    with pytest.raises(RuntimeError, match="TaxDoctor 오류: -32602"):
        cc.taxdoctor_names()


# ---- 수정 2: 종료코드와 출력 인코딩 ----

def _inputs(tmp_path, listing=LISTING, aliases=ALIASES):
    lp = tmp_path / "l.json"; ap = tmp_path / "a.json"; op = tmp_path / "o.json"
    lp.write_text(json.dumps(listing, ensure_ascii=False), encoding="utf-8")
    ap.write_text(json.dumps(aliases, ensure_ascii=False), encoding="utf-8")
    return lp, ap, op


def _run(lp, ap, op):
    return cc.main(["--목록", str(lp), "--별칭", str(ap), "--출력", str(op), "--기준일", "20261009", "--TaxDoctor생략"])


def test_main_exit_code_0_when_everything_resolves(tmp_path, monkeypatch):
    listing = {"주제": "시험", "법령": [{"이름": "소득세법", "구분": "세법"}, {"이름": "주택법", "구분": "비세법"}], "고시": []}
    lp, ap, op = _inputs(tmp_path, listing, {"별칭": []})
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (fake_search, fake_admrul, None))
    assert _run(lp, ap, op) == 0
    assert json.loads(op.read_text(encoding="utf-8"))["요약"]["미해소"] == 0


def test_main_exit_code_2_when_list_file_is_missing(tmp_path, monkeypatch, capsys):
    lp, ap, op = _inputs(tmp_path)
    lp.unlink()
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (fake_search, fake_admrul, None))
    assert _run(lp, ap, op) == 2
    err = capsys.readouterr().err
    assert "입력 파일을 읽지 못했다" in err and str(lp) in err
    assert not op.exists()


def test_main_exit_code_2_when_alias_file_is_invalid_json(tmp_path, monkeypatch, capsys):
    lp, ap, op = _inputs(tmp_path)
    ap.write_text("{ 깨진 json", encoding="utf-8")
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (fake_search, fake_admrul, None))
    assert _run(lp, ap, op) == 2
    err = capsys.readouterr().err
    assert "입력 파일을 읽지 못했다" in err and str(ap) in err


def test_main_exit_code_2_when_response_shape_is_unexpected(tmp_path, monkeypatch):
    lp, ap, op = _inputs(tmp_path)
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (lambda name, page: {"result": "OC 인증 확인 바랍니다"}, fake_admrul, None))
    assert _run(lp, ap, op) == 2


def test_main_prints_utf8_even_when_stdout_cannot_encode_korean(tmp_path, monkeypatch):
    lp, ap, op = _inputs(tmp_path)
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (fake_search, fake_admrul, None))
    pipe = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stdout", pipe)
    assert _run(lp, ap, op) == 1
    pipe.flush()
    assert "누락 검사" in pipe.buffer.getvalue().decode("utf-8")


# ---- 수정 3: 응답 형식 검사 ----

@pytest.mark.parametrize("bad", [{"result": "OC 인증 확인 바랍니다"}, {}, None])
def test_resolve_raises_when_law_search_root_is_missing(bad):
    with pytest.raises(RuntimeError, match="법제처 응답 형식이 다르다"):
        cc.resolve(lambda name, page: bad, "주택법", "20261009")


def test_resolve_error_names_the_keys_it_got():
    with pytest.raises(RuntimeError, match="result"):
        cc.resolve(lambda name, page: {"result": "OC 인증 확인 바랍니다"}, "주택법", "20261009")


def test_find_admrul_raises_when_root_is_missing():
    with pytest.raises(RuntimeError, match="법제처 응답 형식이 다르다"):
        cc.find_admrul(lambda name, page: {"LawSearch": {"totalCnt": "0"}}, "조정대상지역", "85055")


def test_resolve_accepts_empty_result_with_root_present():
    assert cc.resolve(lambda name, page: {"LawSearch": {"totalCnt": "0"}}, "주택법", "20261009") is None


# ---- 최종 검토 I2: 10쪽(1000행) 한도 ----

def test_all_rows_raises_when_pages_run_out_before_total():
    many = [row(f"다른법{i}", str(i), "20260101") for i in range(100)]
    calls = []

    def search(name, page):
        calls.append(page)
        return {"LawSearch": {"totalCnt": "1500", "law": many}}

    with pytest.raises(RuntimeError, match="검색 결과가 1500건이라 다 읽지 못했다. 이름을 더 정확히 준다"):
        cc.resolve(search, "주택법", "20261009")
    assert calls == list(range(1, 11))


def test_all_rows_does_not_raise_when_everything_is_read():
    search = pages([row("주택법", "1", "20260101")] * 100, [row("주택법", "2", "20260201")] * 20)
    assert cc.resolve(search, "주택법", "20261009")["법령일련번호"] == "2"


# ---- 최종 검토 C1: 옛 이름은 별칭이 없으면 미해소로 남는다 ----

OLD = "지방자치분권 및 지역균형발전에 관한 특별법"
NEW = "지방자치분권 및 균형성장에 관한 특별법"


def _renamed_search(name, page):
    # 2026-10-09 법제처 현행·시행예정 검색(nw=2,3)의 모양: 옛 이름에는 개칭 전에 공포된 시행예정 판 하나만 있다
    table = {
        OLD: [row(NEW, "286737", "20260910", "20260609"), row(OLD, "285293", "20261015", "20260414")],
        NEW: [row(NEW, "286737", "20260910", "20260609"), row(NEW, "286503", "20261203", "20260602")],
    }
    rows = table.get(name, []) if page == 1 else []
    return {"LawSearch": {"totalCnt": str(len(table.get(name, []))), "law": rows}}


def test_old_name_without_alias_stays_unresolved():
    listing = {"주제": "시험", "법령": [{"이름": OLD, "구분": "비세법"}], "고시": []}
    rep = cc.check(listing, {"별칭": []}, _renamed_search, fake_admrul, None, "20261009")
    assert rep["요약"]["미해소"] == 1 and not rep["항목"][0]["해소"]


def test_old_name_with_alias_resolves_to_current_name():
    listing = {"주제": "시험", "법령": [{"이름": OLD, "구분": "비세법"}], "고시": []}
    aliases = {"별칭": [{"인용명": OLD, "현행명": NEW, "종류": "개칭", "근거": "시험"}]}
    rep = cc.check(listing, aliases, _renamed_search, fake_admrul, None, "20261009")
    item = rep["항목"][0]
    assert item["해소"] and item["현행명"] == NEW and item["MST"] == "286737"


# ---- OC 가림 ----

def test_mask_hides_oc_value_and_oc_parameter():
    text = "GET https://www.law.go.kr/DRF/lawSearch.do?OC=hany123&type=JSON 실패, hany123 거절"
    out = cc._mask(text, "hany123")
    assert "hany123" not in out and "OC=***&type=JSON" in out


def test_mask_without_known_oc_still_masks_parameter(monkeypatch):
    monkeypatch.delenv("LAW_OC", raising=False)
    monkeypatch.setattr(cc, "_OC_SEEN", None)
    assert cc._mask("?OC=zzz&type=JSON LAW_OC=zzz") == "?OC=***&type=JSON LAW_OC=***"


def test_main_masks_oc_in_collection_failure(tmp_path, monkeypatch, capsys):
    lp, ap, op = _inputs(tmp_path)

    def boom(use_td):
        raise RuntimeError("urlopen 실패 https://www.law.go.kr/DRF/lawSearch.do?OC=secret99&type=JSON, 값 secret99")

    monkeypatch.setattr(cc, "make_sources", boom)
    monkeypatch.setattr(cc, "_OC_SEEN", "secret99")
    assert _run(lp, ap, op) == 2
    err = capsys.readouterr().err
    assert "수집 실패" in err and "secret99" not in err
