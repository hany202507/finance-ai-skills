# -*- coding: utf-8 -*-
"""고시 이력 조사 결과(조정대상지역_이력.json)를 rules/고시/ 로 옮긴다. 공고 이벤트는 고치지 않고 그대로 옮긴다.

  python scripts/refresh/import_notices.py --입력 <조정대상지역_이력.json> [--출력 rules/고시]
"""
import argparse
import json
import os

REGIMES = ("조정대상지역", "투기과열지구", "투기지역")
DROP = ("증거파일",)  # 조사 PC 의 로컬 파일 경로라 공개 저장소에 넣지 않는다


def convert(src):
    asof = src["as_of"]
    out = {}
    for name in REGIMES:
        events = [{k: v for k, v in e.items() if k not in DROP} for e in src["regimes"][name]]
        out[name] = {"이름": name, "기준일": asof, "해석_규칙": src["해석_규칙"], "이벤트": events}
    out["현황_" + asof] = dict({"기준일": asof}, **src["현재_" + asof])
    return out


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--입력", required=True)
    ap.add_argument("--출력", default=os.path.join(os.path.dirname(os.path.dirname(here)), "rules", "고시"))
    a = ap.parse_args(argv)
    with open(a.입력, encoding="utf-8") as f:
        src = json.load(f)
    os.makedirs(a.출력, exist_ok=True)
    for name, doc in convert(src).items():
        with open(os.path.join(a.출력, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(name, len(doc.get("이벤트", [])) or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
