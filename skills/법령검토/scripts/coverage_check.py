"""주제별 법령 목록의 누락 검사.

목록의 법령마다 이름이 정확히 같은 현행 판을 법제처에서 찾고, 세법은 TaxDoctor 수록 여부를 적는다.
옛 이름은 별칭의 현행 이름으로 찾는다. 고시는 행정규칙ID 또는 확인처가 있어야 해소로 본다.

  python scripts/coverage_check.py --목록 rules/법령목록.json --별칭 rules/법령별칭.json --출력 rules/누락검사.json

종료코드: 0 전부 해소, 1 미해소 있음, 2 수집 실패.
OC 는 환경변수 LAW_OC 또는 `claude mcp get korean-law` 에서 읽고 출력하지 않는다.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DRF = "https://www.law.go.kr/DRF/lawSearch.do"
TAXDOCTOR = "https://mcp.taxdoctorai.com/mcp"

_OC_SEEN = None  # get_oc 가 읽은 값. 오류 메시지에서 가리는 데만 쓴다


def _mask(text, oc=None):
    """메시지에서 법제처 OC 값과 `OC=...` 를 `***` 로 바꾼다."""
    s = str(text)
    oc = oc or _OC_SEEN or os.environ.get("LAW_OC")
    if oc:
        s = s.replace(oc, "***")
    return re.sub(r"OC=[^&\s'\"]*", "OC=***", s)


def norm(name):
    return re.sub(r"\s+", "", str(name or "")).replace("·", "ㆍ").replace("・", "ㆍ")


def today_seoul():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y%m%d")


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def parse_taxdoctor_list(text):
    out = {}
    for line in str(text).splitlines():
        m = re.match(r"^- (.+?) \(([^,]+), 시행 (\d{4})\.(\d{2})\.(\d{2})\)(?:\s*\[[^\]]*\])?\s*$", line.strip())
        if m:
            out[norm(m.group(1))] = m.group(3) + m.group(4) + m.group(5)
    return out


def _all_rows(search, name, key_root, key_rows, max_pages=10):
    rows = []
    total = 0
    for page in range(1, max_pages + 1):
        d = search(name, page)
        root = d.get(key_root) if isinstance(d, dict) else None
        if not isinstance(root, dict):
            keys = sorted(d) if isinstance(d, dict) else type(d).__name__
            raise RuntimeError(f"법제처 응답 형식이 다르다: {keys}")
        got = [r for r in as_list(root.get(key_rows)) if isinstance(r, dict)]
        rows.extend(got)
        total = int(root.get("totalCnt") or len(rows))
        if not got or len(rows) >= total:
            break
    # 1000행에서 끊긴 결과로 「찾지 못함」을 적으면 틀린다
    if len(rows) < total:
        raise RuntimeError(f"검색 결과가 {total}건이라 다 읽지 못했다. 이름을 더 정확히 준다: {name}")
    return rows


def resolve(search, name, date8):
    rows = _all_rows(search, name, "LawSearch", "law")
    exact = [r for r in rows if norm(r.get("법령명한글")) == norm(name)]
    ok = [r for r in exact if str(r.get("시행일자", "")) <= date8]
    ok.sort(key=lambda r: (str(r.get("시행일자", "")), str(r.get("공포일자", "")), int(r.get("공포번호") or 0)), reverse=True)
    return ok[0] if ok else None


def find_admrul(search_admrul, name, rule_id):
    rows = _all_rows(search_admrul, name, "AdmRulSearch", "admrul")
    hits = [r for r in rows if str(r.get("행정규칙ID")) == str(rule_id)]
    return hits[0] if hits else None


def _law_item(entry, alias, search, td_names, date8):
    name = entry["이름"]
    item = {"이름": name, "구분": entry.get("구분", ""), "해소": False, "현행명": name, "MST": None, "시행일자": None, "TaxDoctor": None, "사유": ""}
    target = name
    if alias:
        if alias.get("종류") == "비법령":
            item.update(해소=bool(alias.get("근거")), 현행명="", 사유=f"법령 아님: {alias.get('근거', '')}".strip())
            return item
        target = alias.get("현행명") or name
        item["현행명"] = target
        item["사유"] = f"별칭({alias.get('종류')}): {alias.get('근거', '')}"
    hit = resolve(search, target, date8)
    if hit:
        item.update(해소=True, MST=str(hit.get("법령일련번호")), 시행일자=str(hit.get("시행일자")))
    else:
        item["사유"] = (item["사유"] + " / " if item["사유"] else "") + f"이름이 정확히 같은 현행 법령을 찾지 못함: {target}"
    if entry.get("구분") == "세법" and td_names is not None:
        item["TaxDoctor"] = norm(target) in td_names
    return item


def _notice_item(entry, search_admrul):
    src = entry.get("출처") or {}
    item = {"이름": entry["이름"], "구분": f"고시·{entry.get('분류', '')}", "해소": False, "현행명": entry["이름"], "MST": None, "시행일자": None, "TaxDoctor": None, "사유": ""}
    if src.get("종류") == "행정규칙":
        hit = find_admrul(search_admrul, src.get("검색어") or entry["이름"], src.get("행정규칙ID"))
        if hit:
            item.update(해소=True, 시행일자=str(hit.get("발령일자")), 사유=f"행정규칙 {src.get('행정규칙ID')} 현행 일련번호 {hit.get('행정규칙일련번호')}")
        else:
            item["사유"] = f"행정규칙ID {src.get('행정규칙ID')} 를 찾지 못함"
    else:
        places = [p for p in as_list(src.get("곳")) if str(p).strip()] or ([src["검색어"]] if src.get("검색어") else [])
        item["해소"] = bool(places)
        item["사유"] = ("확인처: " + ", ".join(map(str, places))) if places else "확인처가 비어 있음"
    return item


def check(listing, aliases, search, search_admrul, td_names, date8):
    amap = {norm(a["인용명"]): a for a in (aliases or {}).get("별칭", [])}
    items = [_law_item(e, amap.get(norm(e["이름"])), search, td_names, date8) for e in listing.get("법령", [])]
    items += [_notice_item(e, search_admrul) for e in listing.get("고시", [])]
    warn = sum(1 for x in items if x["구분"] == "세법" and x["TaxDoctor"] is False)
    solved = sum(1 for x in items if x["해소"])
    return {"기준일": date8, "요약": {"전체": len(items), "해소": solved, "미해소": len(items) - solved, "경고": warn}, "항목": items}


def get_oc():
    global _OC_SEEN
    oc = os.environ.get("LAW_OC")
    if not oc:
        out = subprocess.run("claude mcp get korean-law", capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True).stdout
        m = re.search(r"LAW_OC=(\S+)", out)
        if not m:
            raise RuntimeError("LAW_OC 를 찾지 못했다. 환경변수로 넣거나 korean-law MCP 를 등록한다")
        oc = m.group(1)
    _OC_SEEN = oc
    return oc


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "finance-ai-skills coverage_check"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    for enc in ("utf-8", "euc-kr"):
        try:
            d = json.loads(raw.decode(enc))
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            d = None
    if d is None:
        raise RuntimeError("법제처가 JSON 이 아닌 응답을 줬다")
    if isinstance(d, dict) and "실패" in str(d.get("result", "")):
        raise RuntimeError(f"법제처 인증 실패: {d.get('result')}")
    return d


def make_sources(use_td):
    oc = get_oc()

    def search(name, page):
        q = urllib.parse.urlencode({"OC": oc, "type": "JSON", "target": "eflaw", "query": name, "nw": "2,3", "display": 100, "page": page})
        return _get_json(f"{DRF}?{q}")

    def search_admrul(name, page):
        q = urllib.parse.urlencode({"OC": oc, "type": "JSON", "target": "admrul", "query": name, "nw": 1, "display": 100, "page": page})
        return _get_json(f"{DRF}?{q}")

    td = taxdoctor_names() if use_td else None
    return search, search_admrul, td


def parse_rpc_body(raw, rid):
    """JSON-RPC 응답 본문(JSON 하나 또는 SSE 이벤트 여러 개)에서 id 가 rid 인 메시지를 돌려준다.

    그 메시지에 error 가 있으면 RuntimeError("TaxDoctor 오류: <code> <message>").
    """
    text = str(raw).strip()
    if text[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"TaxDoctor 응답이 JSON 이 아니다: {e}") from e
        msgs = [m for m in as_list(data) if isinstance(m, dict)]
        found = data if isinstance(data, dict) else next((m for m in msgs if str(m.get("id")) == str(rid)), None)
    else:
        msgs, event = [], []
        for line in text.splitlines() + [""]:
            if line.startswith("data:"):
                piece = line[5:]
                event.append(piece[1:] if piece.startswith(" ") else piece)
            elif not line.strip():
                payload = "\n".join(event).strip()
                event = []
                if payload:
                    try:
                        m = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(m, dict):
                        msgs.append(m)
        found = next((m for m in msgs if str(m.get("id")) == str(rid)), None)
    if found is None:
        raise RuntimeError(f"TaxDoctor 응답에서 id {rid} 결과를 찾지 못했다 (메시지 {len(msgs)}개)")
    err = found.get("error")
    if err:
        err = err if isinstance(err, dict) else {"message": err}
        raise RuntimeError(f"TaxDoctor 오류: {err.get('code', '')} {err.get('message', '')}".rstrip())
    return found


def _post(payload, sid=None):
    """JSON-RPC 메시지 하나를 보내고 (응답 본문, 새 세션 ID) 를 돌려준다."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "finance-ai-skills coverage_check"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(TAXDOCTOR, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "replace")
        sid2 = r.headers.get("Mcp-Session-Id")
    return raw, sid2


def _rpc(method, params, sid=None, rid=1):
    raw, sid2 = _post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, sid)
    return parse_rpc_body(raw, rid), sid2


def _notify(method, sid=None):
    _post({"jsonrpc": "2.0", "method": method}, sid)  # 202 · 빈 본문이 정상이라 본문은 읽지 않는다


def taxdoctor_names():
    _, sid = _rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "coverage_check", "version": "1"}})
    _notify("notifications/initialized", sid)
    res, _ = _rpc("tools/call", {"name": "list_laws", "arguments": {}}, sid, 2)
    text = "\n".join(c.get("text", "") for c in res.get("result", {}).get("content", []) if c.get("type") == "text")
    names = parse_taxdoctor_list(text)
    if not names:
        raise RuntimeError("TaxDoctor list_laws 응답에서 법령명을 읽지 못했다")
    return names


def to_markdown(rep):
    lines = [f"# 누락 검사 {rep['기준일']}", "", f"전체 {rep['요약']['전체']} · 해소 {rep['요약']['해소']} · 미해소 {rep['요약']['미해소']} · TaxDoctor 미수록 세법 {rep['요약']['경고']}", ""]
    bad = [x for x in rep["항목"] if not x["해소"]]
    warn = [x for x in rep["항목"] if x["구분"] == "세법" and x["TaxDoctor"] is False]
    if bad:
        lines += ["## 미해소", ""] + [f"- {x['이름']}: {x['사유']}" for x in bad] + [""]
    if warn:
        lines += ["## TaxDoctor 에 없는 세법 (두 곳 대조 불가)", ""] + [f"- {x['현행명']}" for x in warn] + [""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="주제별 법령 목록의 누락 검사")
    ap.add_argument("--목록", required=True)
    ap.add_argument("--별칭", required=True)
    ap.add_argument("--출력", required=True)
    ap.add_argument("--기준일", default=None)
    ap.add_argument("--TaxDoctor생략", action="store_true")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    loaded = []
    for p in (a.목록, a.별칭):
        try:
            loaded.append(json.loads(Path(p).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:  # JSONDecodeError · UnicodeDecodeError 는 ValueError
            print(_mask(f"입력 파일을 읽지 못했다: {p}: {e}")[:300], file=sys.stderr)
            return 2
    listing, aliases = loaded
    date8 = a.기준일 or today_seoul()
    try:
        search, search_admrul, td = make_sources(not a.TaxDoctor생략)
        rep = check(listing, aliases, search, search_admrul, td, date8)
    except Exception as e:  # noqa: BLE001
        print(f"수집 실패: {_mask(e)[:300]}", file=sys.stderr)
        return 2
    out = Path(a.출력)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    return 0 if rep["요약"]["미해소"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
