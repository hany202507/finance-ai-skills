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
        m = re.match(r"^- (.+?) \(([^,]+), 시행 (\d{4})\.(\d{2})\.(\d{2})\)\s*$", line.strip())
        if m:
            out[norm(m.group(1))] = m.group(3) + m.group(4) + m.group(5)
    return out


def _all_rows(search, name, key_root, key_rows, max_pages=10):
    rows = []
    for page in range(1, max_pages + 1):
        d = search(name, page) or {}
        root = d.get(key_root) or {}
        got = [r for r in as_list(root.get(key_rows)) if isinstance(r, dict)]
        rows.extend(got)
        total = int(root.get("totalCnt") or len(rows))
        if not got or len(rows) >= total:
            break
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
    oc = os.environ.get("LAW_OC")
    if oc:
        return oc
    out = subprocess.run("claude mcp get korean-law", capture_output=True, text=True, encoding="utf-8", errors="replace", shell=True).stdout
    m = re.search(r"LAW_OC=(\S+)", out)
    if not m:
        raise RuntimeError("LAW_OC 를 찾지 못했다. 환경변수로 넣거나 korean-law MCP 를 등록한다")
    return m.group(1)


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


def _rpc(method, params, sid=None, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": "finance-ai-skills coverage_check"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(TAXDOCTOR, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "replace")
        sid2 = r.headers.get("Mcp-Session-Id")
    if raw.lstrip().startswith("event:") or "data:" in raw[:20]:
        raw = "\n".join(line[5:].strip() for line in raw.splitlines() if line.startswith("data:"))
    return json.loads(raw), sid2


def taxdoctor_names():
    _, sid = _rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "coverage_check", "version": "1"}})
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
    listing = json.loads(Path(a.목록).read_text(encoding="utf-8"))
    aliases = json.loads(Path(a.별칭).read_text(encoding="utf-8"))
    date8 = a.기준일 or today_seoul()
    try:
        search, search_admrul, td = make_sources(not a.TaxDoctor생략)
        rep = check(listing, aliases, search, search_admrul, td, date8)
    except Exception as e:  # noqa: BLE001
        print(f"수집 실패: {str(e)[:300]}", file=sys.stderr)
        return 2
    out = Path(a.출력)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    return 0 if rep["요약"]["미해소"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
