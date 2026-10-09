# -*- coding: utf-8 -*-
"""감시 조문의 판을 법제처 DRF 에서 받아 정규화 본문으로 저장하고, 현행 판을 TaxDoctor 와 대조한다.

  python scripts/refresh/fetch_articles.py [--rules rules] [--오늘 YYYY-MM-DD]

2025-01-01 에 시행 중이던 판부터 시행예정 판까지 받는다. 이미 받은 판 파일은 다시 받지 않는다.
OC 는 환경변수 LAW_OC 또는 `claude mcp get korean-law` 에서 읽고 출력하지 않는다.
종료코드: 0 정상, 1 수집 실패 또는 TaxDoctor 불일치.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(os.path.dirname(HERE))
TEXT_KEYS = ("조문내용", "항내용", "호내용", "목내용")


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def norm_text(s):
    s = re.sub(r"<[^>]+>", "", str(s))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"[ \t　]+", " ", s)
    return unicodedata.normalize("NFC", s).strip()


def _collect(node, out):
    if isinstance(node, list):
        for n in node:
            _collect(n, out)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k in TEXT_KEYS and isinstance(v, str):
                t = norm_text(v)
                if t:
                    out.append(t)
            elif k in TEXT_KEYS and isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        t = norm_text(x)
                        if t:
                            out.append(t)
                    else:
                        _collect(x, out)
            elif isinstance(v, (dict, list)):
                _collect(v, out)
    return out


def _flat(v):
    if isinstance(v, list):
        return "\n".join(_flat(x) for x in v)
    return str(v or "")


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def article_units(law_json):
    law = (law_json or {}).get("법령", {})
    out = {}
    for u in as_list((law.get("조문") or {}).get("조문단위")):
        if u.get("조문여부") != "조문":
            continue
        b = u.get("조문가지번호")
        key = str(u.get("조문번호")) + ("의%s" % b if b not in (None, "", "0") else "")
        text = "\n".join(_collect(u, []))
        out[key] = {"제목": norm_text(u.get("조문제목", "")), "sha256": _sha(text), "text": text}
    return out


def own_addenda(law_json, 공포번호):
    law = (law_json or {}).get("법령", {})
    out = {}
    for r in as_list((law.get("부칙") or {}).get("부칙단위")):
        if str(r.get("부칙공포번호")) != str(공포번호):
            continue
        text = norm_text(_flat(r.get("부칙내용")))
        out[str(공포번호)] = {"공포일": _iso(r.get("부칙공포일자")), "sha256": _sha(text), "text": text}
    return out


def _iso(d8):
    d8 = str(d8 or "")
    return "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:8]) if len(d8) == 8 else d8


def _norm_name(s):
    return re.sub(r"\s+", "", str(s or "")).replace("·", "ㆍ").replace("・", "ㆍ")


def pick_versions(rows, name, 기준시작8, today8):
    want = _norm_name(name)
    by_ef = {}
    for r in rows:
        if _norm_name(r.get("법령명한글")) != want:
            continue
        ef = str(r.get("시행일자", ""))
        key = (str(r.get("공포일자", "")), int(r.get("공포번호") or 0))
        cur = by_ef.get(ef)
        if cur is None or key > (str(cur.get("공포일자", "")), int(cur.get("공포번호") or 0)):
            by_ef[ef] = r
    efs = sorted(by_ef)
    start = max([i for i, ef in enumerate(efs) if ef <= 기준시작8] or [0])
    cur = max([i for i, ef in enumerate(efs) if ef <= today8] or [-1])
    out = []
    for i in range(start, len(efs)):
        r = by_ef[efs[i]]
        state = "시행예정" if efs[i] > today8 else ("현행" if i == cur else "연혁")
        out.append({"MST": str(r["법령일련번호"]), "시행일": _iso(efs[i]), "공포일": _iso(r.get("공포일자")),
                    "공포번호": str(r.get("공포번호") or ""), "법령ID": r.get("법령ID"), "상태": state})
    return out


def td_key(text):
    m = re.search(r"moleg-eflaw:(\d+)@(\d{8})", str(text or ""))
    return "%s@%s" % (m.group(1), m.group(2)) if m else None


def _label(조):
    if "의" in 조:
        a, b = 조.split("의", 1)
        return "제%s조의%s" % (a, b)
    return "제%s조" % 조


def _search_all(api, name):
    rows = []
    for page in range(1, 11):
        j = api("lawSearch.do", {"target": "eflaw", "query": name, "nw": "1,2,3", "display": 100, "page": page})
        got = as_list((j.get("LawSearch") or {}).get("law"))
        rows += got
        if len(got) < 100:
            break
    return rows


def fetch(rules_dir, api, td, today):
    with open(os.path.join(rules_dir, "감시조문.json"), encoding="utf-8") as f:
        watch = json.load(f)
    start8 = watch["기준시작"].replace("-", "")
    today8 = today.replace("-", "")
    base = os.path.join(rules_dir, "조문")
    listing = {"기준시작": watch["기준시작"], "받은날": today, "법령": {}}
    record = {"확인일": today, "법령": {}, "TaxDoctor": []}
    report = {"새판": 0, "오류": [], "불일치": 0, "갱신": 0}
    for law, arts in watch["법령"].items():
        try:
            vers = pick_versions(_search_all(api, law), law, start8, today8)
            if not vers:
                raise RuntimeError("%s: 판이 0건이다" % law)
            for v in vers:
                rel = "%s/%s@%s.json" % (law, v["MST"], v["시행일"])
                path = os.path.join(base, rel)
                v["파일"] = rel
                if os.path.exists(path) and v["상태"] != "시행예정":
                    continue
                j = api("lawService.do", {"target": "eflaw", "MST": v["MST"], "efYd": v["시행일"].replace("-", "")})
                got = str(((j.get("법령") or {}).get("기본정보") or {}).get("시행일자", ""))
                if got != v["시행일"].replace("-", ""):
                    raise RuntimeError("%s %s 본문 시행일자가 %s 다" % (law, v["MST"], got))
                units = article_units(j)
                missing = [a for a in arts if a not in units]
                if missing:
                    raise RuntimeError("%s %s 판에 감시 조문 %s 가 없다" % (law, v["시행일"], missing))
                doc = {"법령": law, "MST": v["MST"], "시행일": v["시행일"], "공포일": v["공포일"],
                       "공포번호": v["공포번호"], "조문": {a: units[a] for a in arts},
                       "부칙": own_addenda(j, v["공포번호"])}
                text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True)
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        if f.read() != text:
                            report["갱신"] += 1
                else:
                    report["새판"] += 1
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
            listing["법령"][law] = [{k: v[k] for k in ("MST", "시행일", "공포일", "공포번호", "상태", "파일")}
                                   for v in vers]
            cur = [v for v in vers if v["상태"] == "현행"][0]
            drf = "%s@%s" % (cur["MST"], cur["시행일"].replace("-", ""))
            record["법령"][law] = {"현행": drf, "판수": len(vers)}
            for a in arts:
                k = td_key(td(law, _label(a)))
                record["TaxDoctor"].append({"법령": law, "조": a, "DRF": drf, "TaxDoctor": k, "일치": k == drf})
                report["불일치"] += int(k != drf)
        except Exception as e:  # 법령 하나가 실패해도 나머지를 계속 본다
            report["오류"].append(str(e))
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "판목록.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(listing, f, ensure_ascii=False, indent=1)
    with open(os.path.join(rules_dir, "확인기록.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    return report


def _real_sources():
    sys.path.insert(0, os.path.join(os.path.dirname(SKILL), "법령조회", "scripts"))
    import coverage_check as cc  # 계획 0. DRF 인증·마스킹·TaxDoctor JSON-RPC 를 같이 쓴다

    oc = cc.get_oc()

    def api(path, params):
        q = urllib.parse.urlencode(dict({"OC": oc, "type": "JSON"}, **params))
        return cc._get_json("https://www.law.go.kr/DRF/%s?%s" % (path, q))

    _, sid = cc._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "yangdo-fetch", "version": "1"}})
    cc._notify("notifications/initialized", sid)
    counter = [10]

    def td(law, label):
        counter[0] += 1
        res, _ = cc._rpc("tools/call", {"name": "get_article",
                                        "arguments": {"law_name": law, "article_number": label}}, sid, counter[0])
        return "\n".join(c.get("text", "") for c in res.get("result", {}).get("content", []) if c.get("type") == "text")

    return api, td, cc._mask


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default=os.path.join(SKILL, "rules"))
    ap.add_argument("--오늘", default=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%d"))
    a = ap.parse_args(argv)
    try:
        api, td, mask = _real_sources()
    except Exception as e:
        print("수집 준비 실패: %s" % e)
        return 1
    rep = fetch(a.rules, api, td, a.오늘)
    print("새 판 %d개, 시행예정 판 갱신 %d개, TaxDoctor 불일치 %d건" % (rep["새판"], rep["갱신"], rep["불일치"]))
    for e in rep["오류"]:
        print("오류: %s" % mask(e))
    return 1 if rep["오류"] or rep["불일치"] else 0


if __name__ == "__main__":
    sys.exit(main())
