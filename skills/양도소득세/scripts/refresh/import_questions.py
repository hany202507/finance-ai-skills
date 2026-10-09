# -*- coding: utf-8 -*-
"""질문지 문항 은행(조사 결과)을 질문지/문항.json 으로 옮긴다. 선택지에 코드를 달고 facts키 를 경로로 바꾼다.

  python scripts/refresh/import_questions.py --입력 <질문지_문항은행.json> [--출력 질문지/문항.json]
"""
import argparse
import copy
import json
import os
import re

CODE_MAP = {
    "P02": ["주택", "토지", "건물", "겸용주택", "입주권", "분양권", "기타자산"],
    "P03": ["매매", "교환", "수용", "경매", "부담부증여", "기타"],
    "P04": ["단독", "공동"],
    "A02": ["예", "아니오", "모름"],
    "A04": ["아파트", "연립다세대", "단독주택", "다가구주택", "주거용오피스텔", "주거용근생"],
    "A06": ["일괄", "호실별"],
    "A08": ["장기할부", "법률상불가", "무허가1주택", "도시개발미완료", "체비지", "농지교환자경", "미이행"],
    "A15": ["매매", "분양", "신축", "경매", "공공매입", "상속", "증여", "부담부증여", "조합원", "기타"],
    "A21": ["주택부수토지", "자경농지", "비자경농지", "임야", "사업용", "나대지", "기타"],
    "H02": ["30세이상", "배우자사망이혼", "소득독립", "해당없음"],
    "H05": ["상속주택", "임대등록", "혼인합가", "동거봉양", "농어촌주택", "없음"],
    "H10": ["공공임대5년", "수용", "해외이주", "해외취학근무", "부득이1년", "해당없음"],
    "T02": ["매매", "분양", "신축", "조합원"],
    "T03": ["자산관리공사", "경매신청", "공매", "현금청산소송", "해당없음"],
    "M02": ["타인", "배우자", "직계", "친족", "법인", "기타특수관계"],
    "M05": ["계약서", "기타자료", "모름"],
    "M09": ["발코니확장", "샷시", "보일러", "승강기냉난방", "용도변경개조", "재해복구", "기타가치증가", "일반수선"],
    "M20": ["개인", "분양", "공공기관", "경매", "모름"],
    "X02": ["예", "아니오", "모름"],
    "X03": ["소형신축", "준공후미분양", "인구감소지역", "해당없음"],
    "X04": ["장기임대등록", "조특법감면주택", "사원용", "문화유산", "상속5년", "저당권3년", "어린이집", "부득이3억",
            "소송3년", "해당없음"],
    "X05": ["예", "아니오", "모름"],
}
RENAME = {"자산[].양도원인": "자산[].양도.원인", "자산[].보유거주예외.일자": "자산[].보유거주예외일자",
          "자산[].토지거래허가.대상": "자산[].토지거래허가대상"}
# 시험에서 원문 선택지 없이 변환을 확인하려고 둔 표본. 실제 변환은 원본 파일의 선택지를 쓴다
SOURCE_OPTIONS_FOR_TEST = {
    "P02": ["주택(아파트·빌라·단독·사람이 사는 오피스텔 포함)", "토지", "주택이 아닌 건물(상가·사무실·공장 등)",
            "주택과 가게가 한 건물에 있는 겸용주택", "재개발·재건축 조합원입주권", "아파트 분양권", "주식·회원권 등 그 밖의 자산"],
    "A08": ["장기할부로 사서 계약상 아직 등기할 수 없었음", "법률이나 법원 결정 때문에 등기할 수 없었음",
            "건축허가 없이 지은 집이라 등기할 수 없었고 1세대1주택 요건을 갖춤", "도시개발사업이 끝나지 않아 토지 등기를 못 함",
            "건설사업자가 공사대금으로 받은 체비지", "농지 교환·8년 자경 감면 대상 토지", "등기할 수 있었지만 하지 않음"],
}


def keys_of(raw):
    raw = str(raw or "")
    if raw.startswith("(서식 전용)"):
        return []
    while re.search(r"\{[^{}]*\}", raw):
        raw = re.sub(r"\{[^{}]*\}", "", raw)
    raw = re.sub(r"\[\[[^\]]*\]\]", "", raw)
    out, prefix = [], ""
    for tok in [t.strip() for t in raw.split(",") if t.strip()]:
        if "." not in tok and prefix:
            tok = prefix + tok
        if tok.endswith("[]"):
            tok = tok[:-2]
        tok = RENAME.get(tok, tok)
        prefix = tok.rsplit(".", 1)[0] + "." if "." in tok else ""
        out.append(tok)
    return out


def _plan5(s):
    return None if s is None else str(s).replace("계획3", "계획5").replace("계획 3", "계획 5")


def _value(maps, kinds, qid, v):
    if kinds.get(qid) == "예아니오" and v in ("예", "아니오"):
        return v == "예"
    m = maps.get(qid)
    if not m:
        return v
    if isinstance(v, list):
        return [m.get(x, x) for x in v]
    return m.get(v, v)


def _cond(c, maps, kinds):
    if c == "항상" or c is None:
        return "항상"
    out = {}
    for k in ("모두", "하나라도"):
        if k in c:
            out[k] = [_cond(it, maps, kinds) if isinstance(it, dict) else [it[0], it[1], _value(maps, kinds, it[0], it[2])]
                      for it in c[k]]
    return out


def convert(src):
    src = copy.deepcopy(src)
    maps, kinds = {}, {q["id"]: q["답형식"] for q in src["문항"]}
    for q in src["문항"]:
        if q.get("선택지"):
            codes = CODE_MAP.get(q["id"])
            if codes is None or len(codes) != len(q["선택지"]):
                raise ValueError("%s 선택지 %d개에 맞는 코드가 없다" % (q["id"], len(q["선택지"])))
            maps[q["id"]] = dict(zip(q["선택지"], codes))
    out = {k: v for k, v in src.items() if k not in ("문항", "계획3목록")}
    out["계획5목록"] = src.get("계획3목록", [])
    out["코드"] = CODE_MAP
    qs = []
    for q in src["문항"]:
        q2 = dict(q)
        q2["키"] = keys_of(q.get("facts키"))
        if q.get("선택지"):
            q2["선택지"] = [{"코드": maps[q["id"]][s], "표시": s} for s in q["선택지"]]
        q2["보이는조건"] = _cond(q.get("보이는조건"), maps, kinds)
        q2["범위"] = _plan5(q.get("범위"))
        q2["모를때처리"] = _plan5(q.get("모를때처리"))
        qs.append(q2)
    out["문항"] = qs
    return out


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--입력", required=True)
    ap.add_argument("--출력", default=os.path.join(os.path.dirname(os.path.dirname(here)), "질문지", "문항.json"))
    a = ap.parse_args(argv)
    with open(a.입력, encoding="utf-8") as f:
        out = convert(json.load(f))
    os.makedirs(os.path.dirname(a.출력), exist_ok=True)
    with open(a.출력, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("문항 %d개 → %s" % (len(out["문항"]), a.출력))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
