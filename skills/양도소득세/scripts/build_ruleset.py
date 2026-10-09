# -*- coding: utf-8 -*-
"""추출규칙.json 의 값마다 원문 발췌가 판 본문에 있는지 대조해 ruleset.json 과 기준정보판.json 을 만든다.

  python scripts/build_ruleset.py build [--rules rules]
  python scripts/build_ruleset.py 판 [--rules rules]
  python scripts/build_ruleset.py 찾기 --법령 "소득세법 시행령" --조 167의10 --발췌 "2026년 5월 9일까지"

값을 원문에서 자동으로 뽑지 않는다. 발췌가 원문에 없으면 아무 파일도 쓰지 않는다(종료코드 1).
"""
import argparse
import json
import os
import re
import sys
from datetime import timedelta

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import RULES_DIR  # noqa: E402
from yangdo import ruleset as R  # noqa: E402
from yangdo.dates import to_date  # noqa: E402

BOX = set("│┌┐└┘├┤┬┴┼─|")


def squash(s):
    return re.sub(r"\s+", "", "".join(ch for ch in str(s) if ch not in BOX))


def url(법령, 조):
    base = "https://www.law.go.kr/법령/" + 법령.replace(" ", "%20")
    return base if 조 == "부칙" else base + "/" + R._label(조)


def load_pans(rules_dir):
    with open(os.path.join(rules_dir, "조문", "판목록.json"), encoding="utf-8") as f:
        listing = json.load(f)
    out = {}
    for law, vers in listing["법령"].items():
        pans = []
        for i, v in enumerate(vers):
            with open(os.path.join(rules_dir, "조문", v["파일"]), encoding="utf-8") as f:
                doc = json.load(f)
            end = to_date(vers[i + 1]["시행일"]) - timedelta(days=1) if i + 1 < len(vers) else None
            pans.append(dict(doc, 상태=v["상태"], 구간시작=to_date(v["시행일"]), 구간끝=end))
        out[law] = pans
    return listing["기준시작"], out


def _overlap(a0, a1, b0, b1):
    return (b1 is None or a0 <= b1) and (a1 is None or b0 <= a1)


def check_ground(g, entry, 기준시작, pans):
    law = g["법령"]
    if law not in pans:
        return [], [], ["%s: 받은 판이 없다(감시조문.json 에 넣고 fetch 를 다시 돌려라)" % law]
    if g["조"] == "부칙":
        no = str(g["공포번호"])
        hit = [p for p in pans[law] if str(p["공포번호"]) == no and no in p.get("부칙", {})]
        if not hit:
            return [], [], ["%s 부칙 제%s호를 받은 판이 없다" % (law, no)]
        add = hit[0]["부칙"][no]
        lost = [e for e in g["발췌"] if squash(e) not in squash(add["text"])]
        if lost:
            return [], [], ["%s 부칙 제%s호에 없는 발췌 %s" % (law, no, lost)]
        return [{"MST": hit[0]["MST"], "시행일": hit[0]["시행일"], "sha256": add["sha256"]}], [], []
    w = g.get("판구간")
    w0 = to_date((w[0] if w else None) or entry["시작"] or 기준시작)
    w1 = to_date(w[1] if w else entry["끝"])
    refs, upcoming, fails = [], [], []
    for p in pans[law]:
        if not _overlap(w0, w1, p["구간시작"], p["구간끝"]):
            continue
        art = p["조문"].get(g["조"])
        if art is None:
            fails.append("%s %s 판에 %s 가 없다(감시조문.json 에 넣고 fetch 를 다시 돌려라)" % (law, p["시행일"], R._label(g["조"])))
            continue
        lost = [e for e in g["발췌"] if squash(e) not in squash(art["text"])]
        if p["상태"] == "시행예정":
            if lost:
                upcoming.append({"시행일": p["시행일"], "법령": law, "조": g["조"], "내용": "발췌 %s 가 시행예정 본문에 없다" % lost})
            continue
        if lost:
            fails.append("%s %s %s 판에 없는 발췌 %s" % (law, R._label(g["조"]), p["시행일"], lost))
        else:
            refs.append({"MST": p["MST"], "시행일": p["시행일"], "sha256": art["sha256"]})
    if not refs and not fails:
        fails.append("%s %s: %s~%s 에 시행된 판이 없다" % (law, R._label(g["조"]), w0, w1 or "현재"))
    return refs, upcoming, fails


def build(rules_dir):
    with open(os.path.join(rules_dir, "추출규칙.json"), encoding="utf-8") as f:
        spec = json.load(f)
    기준시작, pans = load_pans(rules_dir)
    rec_path = os.path.join(rules_dir, "확인기록.json")
    if not os.path.exists(rec_path):
        return 1, ["확인기록.json 이 없다. scripts/refresh/fetch_articles.py 를 먼저 돌려라"]
    with open(rec_path, encoding="utf-8") as f:
        rec = json.load(f)
    fails = ["TaxDoctor 대조 불일치: %s %s DRF %s / TaxDoctor %s" % (r["법령"], R._label(r["조"]), r["DRF"], r["TaxDoctor"])
             for r in rec.get("TaxDoctor", []) if not r.get("일치")]
    rules = {}
    for rule in spec["규칙"]:
        key, hist, prev_end = rule["key"], [], "처음"
        for e in rule["이력"]:
            if rule["단위"] != "근거" and e.get("값") is None:
                fails.append("%s: 값이 비었다" % key)
            s = to_date(e["시작"])
            if prev_end != "처음" and (prev_end is None or s is None or s <= prev_end):
                fails.append("%s: 이력 구간이 겹친다" % key)
            prev_end = to_date(e["끝"])
            grounds, upcoming = [], []
            for g in e["근거"]:
                refs, up, fs = check_ground(g, e, 기준시작, pans)
                fails += ["%s: %s" % (key, x) for x in fs]
                upcoming += up
                gg = {k: g[k] for k in ("법령", "조", "항", "발췌") if k in g}
                if g["조"] == "부칙":
                    gg["공포번호"] = str(g["공포번호"])
                gg["판"] = refs
                gg["URL"] = url(g["법령"], g["조"])
                grounds.append(gg)
            hist.append({"시작": e["시작"], "끝": e["끝"], "기준일": e.get("기준일", "양도일"), "값": e.get("값"),
                         "근거": grounds, "예정변경": upcoming})
        rules[key] = {"설명": rule.get("설명", ""), "단위": rule["단위"], "이력": hist}
    if fails:
        return 1, ["규칙세트를 만들지 않았다. 값은 고치지 말고 발췌와 원문을 사람이 확인하라"] + fails
    data = {"기준시작": 기준시작, "확인일": rec["확인일"],
            "법령판": {law: ["%s@%s" % (p["MST"], p["시행일"]) for p in ps] for law, ps in pans.items()},
            "규칙": rules, "계류": spec.get("계류", [])}
    with open(os.path.join(rules_dir, "ruleset.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    ed = R.write_edition(rules_dir, rec["확인일"])
    return 0, ["규칙세트: 규칙 %d개, 기준정보 판 %s, 확인일 %s" % (len(rules), ed["id"], rec["확인일"])]


def find(rules_dir, 법령, 조, 발췌):
    _, pans = load_pans(rules_dir)
    out = []
    for p in pans.get(법령, []):
        art = p["조문"].get(조)
        hit = art is not None and squash(발췌) in squash(art["text"])
        out.append("%s MST %s %s" % (p["시행일"], p["MST"], "있음" if hit else "없음"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "판", "찾기"])
    ap.add_argument("--rules", default=RULES_DIR)
    ap.add_argument("--법령")
    ap.add_argument("--조")
    ap.add_argument("--발췌")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        code, msgs = build(a.rules)
    elif a.cmd == "판":
        with open(os.path.join(a.rules, "ruleset.json"), encoding="utf-8") as f:
            ed = R.write_edition(a.rules, json.load(f)["확인일"])
        code, msgs = 0, ["기준정보 판 %s" % ed["id"]]
    else:
        code, msgs = 0, find(a.rules, a.법령, a.조, a.발췌)
    print("\n".join(msgs))
    return code


if __name__ == "__main__":
    sys.exit(main())
