"""결론에 쓴 판이 기준일에 맞는지, 개정안이 있는지 법제처 판 목록과 맞춰 본다.

  python scripts/freshness_check.py --기준 기준.json --출력 최신화점검.json
  python scripts/freshness_check.py --기준 기준.json --조사 개정안.json --출력 최신화점검.json

기준.json 은 결론에 쓴 법령마다 쓴 판(MST@시행일)과 korean-law amendment_track 이 준 판 목록(DB판)을 담는다.
조사 파일은 없어도 된다. 판 목록 대조만으로 기준일 판을 썼는지, 기준일 뒤 시행 판이 있는지 나온다.
개정안 조사(국회 계류·입법예고·정부안)나 관보 공포 조사를 했으면 그 파일을 --조사 로 넘긴다. 모양은 references/최신화점검.md.

종료코드: 0 조치할 것 없음, 1 조치 필요, 2 입력 오류.
"""
import argparse
import json
import re
import sys
from pathlib import Path

개정안구분 = ("계류", "입법예고", "정부안")
조치, 경고, 참고 = "조치", "경고", "참고"


def norm(name):
    return re.sub(r"\s+", "", str(name or "")).replace("·", "ㆍ").replace("・", "ㆍ")


def date10(v):
    """YYYY-MM-DD · YYYYMMDD · YYYY.MM.DD 를 YYYY-MM-DD 로 바꾼다. 날짜 꼴이 아니면 None."""
    s = re.sub(r"[.\-/\s]", "", str(v or ""))
    if not re.fullmatch(r"\d{8}", s):
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def jo(v):
    """「제159조의4 제1항」 같은 표기를 조 단위 키 「159의4」로 바꾼다. 항·호는 버린다."""
    m = re.search(r"(\d+)\s*조?\s*(?:의\s*(\d+))?", str(v or ""))
    if not m:
        return None
    return m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")


def parse_pan(v):
    """「290841@20261001」 을 (MST, 시행일) 로 바꾼다."""
    mst, _, ef = str(v or "").partition("@")
    return mst.strip(), date10(ef)


def check_db(db, used, 기준일):
    """판 목록만으로 본다. 기준일에 시행 중인 판을 썼는지, 기준일 뒤에 시행될 판이 있는지."""
    out = []
    in_force = [d for d in db if d["시행일"] and d["시행일"] <= 기준일]
    if not in_force:
        out.append({"조사처": "판 목록", "판정": "확인 불가", "등급": 조치,
                    "까닭": f"판 목록에 기준일 {기준일} 이전 시행 판이 없다. amendment_track 의 display 를 늘린다"})
    elif used:
        # 같은 시행일이면 가장 늦게 공포된 판이 그날의 본문이다
        top = max(in_force, key=lambda d: (d["시행일"], d["공포일"] or ""))
        if (top["MST"], top["시행일"]) != (used["MST"], used["시행일"]):
            out.append({"조사처": "판 목록", "판정": "판 다시 고르기", "등급": 조치, "시행일": top["시행일"],
                        "까닭": f"기준일 {기준일} 에 시행 중인 판은 {top['MST']}@{top['시행일']}(공포 {top['공포일']}) 이다. 그 판으로 조문과 부칙을 다시 읽는다"})
    future = {}
    for d in db:
        if d["시행일"] and d["시행일"] > 기준일:
            future.setdefault(d["시행일"], []).append(d)
    for ef, ds in sorted(future.items()):
        names = ", ".join(f"{d['MST']}(공포 {d['공포일']})" for d in ds)
        out.append({"조사처": "판 목록", "판정": "기준일 뒤 시행", "등급": 경고, "시행일": ef,
                    "까닭": f"{ef} 에 시행될 판이 있다: {names}. 결론을 그 뒤 사건에도 쓰면 그 판과 부칙 적용례를 본다"})
    return out


def judge(it, 조사처, db, 조항, 기준일, 오늘):
    구분 = it.get("구분")
    prom, ef = date10(it.get("공포일")), date10(it.get("시행일"))
    if 구분 in (*개정안구분, "국회통과") and prom:
        구분 = "공포"  # 공포일이 적힌 개정안은 이미 공포됐다. 공포로 판 목록과 맞춘다
    대상 = sorted({k for k in (jo(x) for x in it.get("대상조문", [])) if k})
    row = {"조사처": 조사처, "구분": 구분, "번호": it.get("번호", ""), "공포일": prom, "시행일": ef,
           "대상조문": 대상, "확인": it.get("확인", ""), "URL": it.get("URL", "")}

    def out(판정, 등급, 까닭):
        return {**row, "판정": 판정, "등급": 등급, "까닭": 까닭}

    if 구분 == "공포":
        if not prom:
            return out("확인 불가", 조치, "공포일이 날짜 꼴이 아니다")
        hits = [d for d in db if d["공포일"] == prom]
        if not hits:
            # 공포문 본문을 읽고 대상조문이 결론 조문과 겹치지 않는다고 적은 경우만 참고로 내린다
            if 대상 and 조항 and not set(대상) & 조항 and it.get("확인") == "본문":
                return out("다른 조문 개정", 참고, "판 목록에 아직 없는 판이지만 결론에 쓴 조문은 바뀌지 않았다")
            return out("DB 미반영", 조치, "법제처 판 목록에 이 공포일 판이 없다. 관보 원문을 읽는다")
        hit_efs = sorted({d["시행일"] for d in hits if d["시행일"]})
        if ef and ef not in hit_efs:
            return out("시행일 불일치", 조치, "판 목록의 시행일 " + (", ".join(hit_efs) or "?") + " 과 다르다")
        row["시행일"] = ef or (hit_efs[-1] if hit_efs else None)
        return out("판 목록에 있음", 참고, "판 목록 대조가 이 판을 본다")
    if 구분 == "국회통과":
        뒤 = f"{ef} 시행 예정이라 기준일 {기준일} 에 적용될 수 있다. 공포 뒤 다시 점검한다" if ef and ef <= 기준일 else "적용하지 않는다"
        return out("공포 대기", 경고, f"국회를 통과했고 공포 전이다. {뒤}")
    if 구분 in 개정안구분:
        if not ef:
            뒤 = "예정 시행일은 의안 원문 부칙에 있다. 기준일 전 시행인지 보려면 원문을 연다. 적용하지 않는다"
        elif ef <= 오늘:
            뒤 = f"예정 시행일 {ef} 이 지났다. 공포됐으면 판 목록에 있고, 없으면 아직 계류 중이다"
        elif ef <= 기준일:
            뒤 = f"{ef} 시행 예정이라 확정되면 기준일 {기준일} 에 적용될 수 있다"
        else:
            뒤 = "적용하지 않는다"
        return out("개정안", 경고, f"{구분} 단계의 개정안이다. {뒤}. 결론 옆에 적는다")
    if 구분 == "고시":
        return out("고시 변경", 조치, "고시 원문과 첨부 목록을 다시 본다")
    return out("확인 불가", 조치, f"모르는 구분이다: {구분}")


def check_law(law, by조사처, 필수, 기준일, 오늘):
    name = law.get("법령", "")
    key = norm(name)
    조항 = {k for k in (jo(x) for x in law.get("조항", [])) if k}
    mst, used_ef = parse_pan(law.get("판"))
    db = [{"MST": str(d.get("MST", "")), "공포일": date10(d.get("공포일")), "시행일": date10(d.get("시행일"))}
          for d in law.get("DB판", [])]
    used = next((d for d in db if d["MST"] == mst and d["시행일"] == used_ef), None)
    판정 = []
    if used is None:
        판정.append({"조사처": "기준", "판정": "기준 오류", "등급": 조치, "까닭": f"쓴 판 {law.get('판')} 이 판 목록에 없다"})
    판정 += check_db(db, used, 기준일)

    for g in list(필수) + sorted(set(by조사처) - set(필수)):
        s = by조사처.get(g)
        if s is None:
            판정.append({"조사처": g, "판정": "확인 불가", "등급": 조치, "까닭": "조사 파일이 없다"})
            continue
        if s.get("상태") != "완료":
            판정.append({"조사처": g, "판정": "확인 불가", "등급": 조치, "까닭": s.get("까닭") or "조사를 끝내지 못했다"})
            continue
        검색 = s.get("검색") or {}
        # 검색어가 법령명의 앞부분이거나, 검색 문장 안에 법령명이 들어 있으면 그 법령을 찾은 것으로 본다
        if not any(t and (t in key or key in t) for t in (norm(x) for x in 검색.get("검색어", []))):
            판정.append({"조사처": g, "판정": "확인 불가", "등급": 조치, "까닭": "검색어에 이 법령이 없다"})
        if g == "공포":
            기간 = 검색.get("기간") or []
            start = date10(기간[0]) if len(기간) > 0 else None
            end = date10(기간[1]) if len(기간) > 1 else None
            if used and (not start or start > used["공포일"]):
                판정.append({"조사처": g, "판정": "확인 불가", "등급": 조치, "까닭": f"검색 기간이 쓴 판 공포일 {used['공포일']} 부터가 아니다"})
            if not end or end < 오늘:
                판정.append({"조사처": g, "판정": "확인 불가", "등급": 조치, "까닭": f"검색 기간이 오늘 {오늘} 까지가 아니다"})
        for it in s.get("항목", []):
            if norm(it.get("법령")) == key:
                판정.append(judge(it, g, db, 조항, 기준일, 오늘))

    # 같은 개정(번호)을 조사처마다 다른 시행일로 적었으면 어느 쪽도 쓰지 않는다
    by번호 = {}
    for p in 판정:
        if p.get("번호") and p.get("시행일"):
            by번호.setdefault(p["번호"], set()).add(p["시행일"])
    for 번호, efs in sorted(by번호.items()):
        if len(efs) > 1:
            판정.append({"조사처": "대조", "번호": 번호, "판정": "불일치", "등급": 조치, "까닭": "시행일이 " + ", ".join(sorted(efs)) + " 로 다르다"})

    등급들 = {p["등급"] for p in 판정}
    결과 = "조치 필요" if 조치 in 등급들 else "경고" if 경고 in 등급들 else "변경 없음"
    return {"법령": name, "판": law.get("판"), "조항": law.get("조항", []), "결과": 결과, "판정": 판정}


def check(base, surveys):
    기준일, 오늘 = date10(base.get("기준일")), date10(base.get("오늘"))
    if not 기준일 or not 오늘:
        raise ValueError("기준일·오늘이 날짜 꼴이 아니다")
    필수 = tuple(base.get("필수조사처") or ())
    by조사처 = {}
    for s in surveys:
        g = s.get("조사처")
        if not g:
            raise ValueError("조사처가 없는 조사 파일이 있다")
        if g in by조사처:
            raise ValueError(f"조사처가 두 번 왔다: {g}")
        by조사처[g] = s
    laws = [check_law(law, by조사처, 필수, 기준일, 오늘) for law in base.get("법령", [])]
    if not laws:
        raise ValueError("기준에 법령이 없다")
    keys = {norm(x["법령"]) for x in laws}
    밖 = [{"조사처": g, "법령": it.get("법령"), "번호": it.get("번호", "")}
         for g, s in by조사처.items() for it in s.get("항목", []) if norm(it.get("법령")) not in keys]
    요약 = {"전체": len(laws)}
    for k in ("변경 없음", "경고", "조치 필요"):
        요약[k] = sum(1 for x in laws if x["결과"] == k)
    return {"기준일": 기준일, "오늘": 오늘,
            "조사처": {g: {"상태": s.get("상태"), "검색": s.get("검색")} for g, s in by조사처.items()},
            "법령": laws, "목록에 없음": 밖, "요약": 요약}


def to_markdown(rep):
    s = rep["요약"]
    lines = [f"# 최신화 점검 {rep['오늘']} (기준일 {rep['기준일']})", "",
             f"전체 {s['전체']} · 변경 없음 {s['변경 없음']} · 경고 {s['경고']} · 조치 필요 {s['조치 필요']}", ""]
    for law in rep["법령"]:
        lines.append(f"## {law['법령']} ({law['판']}): {law['결과']}")
        shown = [p for p in law["판정"] if p["등급"] != 참고]
        for p in shown:
            what = " ".join(x for x in (p.get("번호"), p.get("시행일") and f"시행 {p['시행일']}") if x)
            lines.append(f"- [{p['등급']}] {p['판정']} · {p['조사처']}" + (f" · {what}" if what else "") + f": {p['까닭']}")
        if not shown:
            lines.append("- 조치·경고 없음")
        lines.append("")
    if rep["목록에 없음"]:
        lines += ["## 기준 목록에 없는 법령의 개정", ""] + [f"- {x['법령']} {x['번호']} ({x['조사처']})" for x in rep["목록에 없음"]] + [""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="결론에 쓴 법령의 최신화 점검")
    ap.add_argument("--기준", required=True)
    ap.add_argument("--조사", nargs="*", default=[])
    ap.add_argument("--출력", required=True)
    if hasattr(sys.stdout, "reconfigure"):  # --help 한글이 깨지지 않게 parse_args 전에 바꾼다
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    a = ap.parse_args(argv)
    try:
        base = json.loads(Path(a.기준).read_text(encoding="utf-8"))
        surveys = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.조사]
        rep = check(base, surveys)
    except (OSError, ValueError, AttributeError, TypeError, KeyError) as e:  # JSONDecodeError 는 ValueError
        print(f"입력 오류: {e}"[:300], file=sys.stderr)
        return 2
    out = Path(a.출력)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    return 1 if rep["요약"]["조치 필요"] else 0


if __name__ == "__main__":
    sys.exit(main())
