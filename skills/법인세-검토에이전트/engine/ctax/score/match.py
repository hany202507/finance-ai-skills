"""정답지(신고본)와 우리 산출을 영역별로 맞춘다. 채점.json 의 줄(rows)과 요약(summary)을 만든다(CONTRACT.md 10절).

정답지는 ctax.prior.read 가 읽은 dict(전기.json 본문과 같은 꼴)다. 우리 산출은 AR.json · 조정.json · 서식.json dict 다. 모든 함수는
PDF 없이 dict 만 받는다.

영역과 짝짓는 법
  서식      정답지 목차의 별지 서식(known) ↔ AR.json forms 의 status 해당 또는 서식.json 에서 만든 서식. 정답지의 빈 서식과
            조정반 지정서 같은 행정 서식은 채점 제외
  15호      side · 금액 · 처분이 같으면 일치, side · 금액만 같으면 처분 다름, 그다음 side · 과목 묶음(기업업무추진비 · 업무용승용차 등)이
            같으면 금액 다름. 과목 이름은 회사마다 달라(「접대비」 · 「기업업무추진비 한도초과」) 짝짓는 데 쓰지 않고 묶음만 본다.
            우리 줄 여럿의 합이 정답지 한 줄과 같으면(같은 묶음) 일치로 본다. 우리 줄은 조정.json adjustments 와 direct(회계사가
            조서 「직접 조정」 줄에 넣은 것)다
  3호       01 · 02 · 03 · 05 · 06 · 07 · 10 · 12 · 30 란. 서식.json 3호 items 가 있으면 그것, 없으면 조정.json summary
  50호(갑)  자본금 · 이익잉여금 · 계 · 차가감계의 기초 · 기말(서식.json 50갑 items), 결손금 줄(조정.json losses)
  50호(을)  과목(공백 · 괄호 뺀 글)으로, 없으면 기말 금액으로 짝짓고 기초 · 감소 · 증가 · 기말을 견준다

채점 제외(정답지 오류, 계약 10절): 23호(을) 신용카드 미사용 금액이 음수인 줄, 21호 ① 소득금액계, 정답지가 결손인데 50호(갑)
결손금 표에 그해 줄을 적지 않은 경우 우리의 당기 결손금 줄.
"""
from __future__ import annotations

import re

RESULTS = ("일치", "금액 다름", "처분 다름", "빠짐", "더 있음", "채점 제외")

ITEMS_3 = {"01": ("결산서상 당기순손익", "net_income"), "02": ("익금산입", "add"), "03": ("손금산입", "deduct"),
           "05": ("기부금한도초과액", "donation_excess"), "06": ("각사업연도소득금액", "income"),
           "07": ("이월결손금", "loss_used"), "10": ("과세표준", "tax_base"), "12": ("산출세액", "computed_tax"),
           "30": ("차감납부할세액", "payable")}
ITEMS_50GAP = {"01": "1. 자본금", "14": "5. 이익잉여금", "20": "6. 계", "31": "11. 차가감계"}
# 장부 · 조정으로 정하는 서식이 아니라 채점하지 않는 서식(조정반 지정서는 외부조정이면 붙이지만 9곳 중 6곳에만 있다)
ADMIN_FORMS = {"63의13", "77"}
TOPICS = (("기업업무추진비", ("기업업무추진비", "접대비")),
          ("업무용승용차", ("업무용승용차", "승용차", "차량")),
          ("법인세비용", ("법인세",)),
          ("퇴직연금", ("퇴직연금", "퇴직보험")),
          ("퇴직급여충당금", ("퇴직급여",)),
          ("가산세 · 벌과금", ("잡손실", "가산세", "벌과금", "과태료", "세금과공과")),
          ("기부금", ("기부금",)),
          ("감가상각", ("감가상각",)),
          ("대손", ("대손",)),
          ("미수이자", ("미수이자", "미수수익")),
          ("연차수당", ("연차", "미지급비용", "미지급급여")),
          ("유가증권", ("단기매매", "단기투자", "매도가능", "평가이익", "평가손실", "평가손익")))


def won(n) -> str:
    return "" if n is None else f"{int(n):,}"


def row(area: str, key: str, answer, ours, result: str, note: str = "") -> dict:
    return {"area": area, "key": key, "answer": answer, "ours": ours, "result": result, "note": note}


def _i(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def topic(subject: str) -> str:
    s = re.sub(r"\s+", "", subject or "")
    for name, keys in TOPICS:
        if any(k in s for k in keys):
            return name
    return ""


def norm_subject(s: str) -> str:
    return re.sub(r"[\s()（）·ㆍ.,\-]", "", s or "")


def norm_code(code) -> str:
    """서식 코드를 계약 6절 꼴로. `23호(갑)` · `20호(1)` 처럼 별지 표시로 적어도 `23갑` · `20_1` 로 맞춘다."""
    from ctax.prior.pdf import norm_hint
    from ctax.prior.read import hint_code
    c = str(code or "").strip()
    if re.match(r"^(조특|지방|농특|국조)?\s*\d+(-\d+)?\s*호", c):
        got, known = hint_code(norm_hint(c))
        if known:
            return got
    return re.sub(r"\s+", "", c)


# ---------------------------------------------------------------- 서식

def made_forms(forms_json: dict | None) -> dict[str, dict]:
    """서식.json 에서 실제로 만든 서식(forms 목록 = 서식 단계가 고른 selected) {code: 서식}."""
    out: dict[str, dict] = {}
    for f in (forms_json or {}).get("forms", []) or []:
        if f.get("code"):
            out.setdefault(norm_code(f.get("code")), f)
    return out


def score_forms(answer_forms: list[dict], ar_forms: list[dict] | None, made: dict[str, dict] | None = None
                ) -> tuple[list[dict], dict]:
    """정답지 서식 목록(전기.json forms 꼴) ↔ 우리 서식. 정답지에 금액이 있는 서식이 정답이다.

    우리 답은 AR.json forms 의 status 「해당」 이거나 서식.json 에서 실제로 만든 서식(made)이다. AR 이 「확인」 으로 남겼어도
    조서 값으로 서식 단계가 만들었으면 「해당」 으로 본다(계약 13절 서식 에이전트 제안).
    """
    ans = {f["code"]: f for f in answer_forms if f.get("known")}
    ours = {}
    for f in ar_forms or []:
        ours.setdefault(norm_code(f.get("code")), f)
    made = made or {}
    for code, f in made.items():
        if code not in ours:
            ours[code] = {"code": code, "name": f.get("name") or code, "status": None}
    rows, tp, fp, fn, ask = [], 0, 0, 0, 0
    for code in list(ans) + [c for c in ours if c not in ans]:
        a, o = ans.get(code), ours.get(code)
        status = (o or {}).get("status")
        by_forms = code in made and status != "해당"
        if by_forms:
            status = "해당"
        name = (a or o or {}).get("name") or code
        key = f"{code} {name}" if name != code else code
        if code in ADMIN_FORMS:
            rows.append(row("서식", key, "있음" if a else "없음", status or "없음", "채점 제외",
                            "행정 서식이라 장부로 해당 여부를 정하지 않는다"))
            continue
        if a and a.get("blank"):
            rows.append(row("서식", key, "빈 서식", status or "없음", "채점 제외",
                            "정답지에 금액 없이 붙은 서식이라 해당 여부를 가리지 않는다"))
            continue
        note = "서식.json 에서 만듦(AR " + ((o or {}).get("status") or "목록에 없음") + ")" if by_forms else ""
        if a and status == "해당":
            tp += 1
            rows.append(row("서식", key, "있음", status, "일치", note))
        elif a:
            fn += 1
            ask += status == "확인"
            rows.append(row("서식", key, "있음", status or "없음", "빠짐",
                            "AR 이 확인으로 남겼고 서식.json 에서 만들지 않았다" if status == "확인" else ""))
        elif status == "해당":
            fp += 1
            rows.append(row("서식", key, "없음", status, "더 있음", note))
        else:
            rows.append(row("서식", key, "없음", status, "일치", "둘 다 해당 없음"))
    return rows, {"tp": tp, "fp": fp, "fn": fn, "fn_ask": ask}     # fn_ask: 빠짐 가운데 AR 이 「확인」 으로 남긴 서식


# ---------------------------------------------------------------- 15호

def _adj(a: dict) -> dict:
    return {"side": a.get("side", ""), "subject": str(a.get("subject") or ""), "amount": _i(a.get("amount")),
            "disposition": str(a.get("disposition") or ""), "topic": topic(str(a.get("subject") or "") + " "
                                                                             + str(a.get("note") or ""))}


def score_adjustments(answer: list[dict], ours: list[dict]) -> tuple[list[dict], dict]:
    A = [_adj(a) for a in answer]
    O = [_adj(o) for o in ours if _i(o.get("amount")) or o.get("subject")]
    used_a, used_o = set(), set()
    pairs = []                                   # (정답 i, [우리 j], 결과)

    def take(cond, result):
        for i, a in enumerate(A):
            if i in used_a:
                continue
            j = next((j for j, o in enumerate(O) if j not in used_o and cond(a, o)), None)
            if j is not None:
                used_a.add(i)
                used_o.add(j)
                pairs.append((i, [j], result))

    take(lambda a, o: a["side"] == o["side"] and a["amount"] == o["amount"] and a["disposition"] == o["disposition"], "일치")
    take(lambda a, o: a["side"] == o["side"] and a["amount"] == o["amount"], "처분 다름")
    # 같은 묶음의 우리 줄 여럿 합이 정답 한 줄
    for i, a in enumerate(A):
        if i in used_a or not a["topic"]:
            continue
        js = [j for j, o in enumerate(O) if j not in used_o and o["side"] == a["side"] and o["topic"] == a["topic"]]
        if len(js) > 1 and sum(O[j]["amount"] for j in js) == a["amount"]:
            used_a.add(i)
            used_o.update(js)
            pairs.append((i, js, "일치"))
    take(lambda a, o: a["side"] == o["side"] and a["topic"] and a["topic"] == o["topic"], "금액 다름")
    # 채점 묶음이 없는 과목은 과목 이름이 같으면 금액 다름으로 짝짓는다(보험료기간미경과액 등)
    take(lambda a, o: a["side"] == o["side"] and norm_subject(a["subject"]) == norm_subject(o["subject"]), "금액 다름")

    rows = []
    s = {"match": 0, "amount_diff": 0, "disposition_diff": 0, "missing": 0, "extra": 0}
    for i, js, result in sorted(pairs, key=lambda p: p[0]):
        a, os_ = A[i], [O[j] for j in js]
        total = sum(o["amount"] for o in os_)
        notes = []
        subj = " + ".join(o["subject"] for o in os_)
        if norm_subject(subj) != norm_subject(a["subject"]):
            notes.append(f"우리 과목 {subj}")
        if len(os_) > 1:
            notes.append(f"우리 {len(os_)}줄 합")
        if result == "처분 다름" or (result != "일치" and os_[0]["disposition"] != a["disposition"]):
            notes.append(f"처분 정답 {a['disposition']} · 우리 {os_[0]['disposition']}")
        if result == "일치" and any(o["disposition"] != a["disposition"] for o in os_):
            result = "처분 다름"
            notes.append(f"처분 정답 {a['disposition']} · 우리 {'·'.join(o['disposition'] for o in os_)}")
        s[{"일치": "match", "처분 다름": "disposition_diff", "금액 다름": "amount_diff"}[result]] += 1
        rows.append(row("15호", f"{a['side']} {a['subject']}", a["amount"], total, result, " · ".join(notes)))
    for i, a in enumerate(A):
        if i not in used_a:
            s["missing"] += 1
            rows.append(row("15호", f"{a['side']} {a['subject']}", a["amount"], None, "빠짐",
                            f"처분 {a['disposition']}" + (f" · 묶음 {a['topic']}" if a["topic"] else "")))
    for j, o in enumerate(O):
        if j not in used_o:
            s["extra"] += 1
            rows.append(row("15호", f"{o['side']} {o['subject']}", None, o["amount"], "더 있음", f"처분 {o['disposition']}"))
    return rows, s


# ---------------------------------------------------------------- 3호

def ours_items_3(forms_json: dict | None, adjust_json: dict | None) -> tuple[dict, str]:
    """우리 3호 란 {코드: 값}과 출처. 서식.json 3호 items 가 먼저, 없으면 조정.json summary."""
    for f in (forms_json or {}).get("forms", []):
        if norm_code(f.get("code")) == "3" and f.get("items"):
            got = {str(it.get("code")): it.get("value") for it in f["items"]}
            if any(c in got for c in ITEMS_3):
                return got, "서식.json"
    summ = (adjust_json or {}).get("summary")
    if summ:
        return {code: summ.get(key) for code, (_, key) in ITEMS_3.items()}, "조정.json summary"
    return {}, ""


def score_items_3(answer3: dict, ours: dict) -> tuple[list[dict], dict]:
    rows, s = [], {"match": 0, "diff": 0}
    for code, (name, _) in ITEMS_3.items():
        a = _i(answer3.get(code))
        o = ours.get(code)                      # 란이 있고 값이 비었으면 0(빈 란), 란이 없으면 None
        if isinstance(o, str):
            o = o.replace(",", "")
        o = _i(o) if code in ours else None
        note = ""
        if o is None:
            note = "우리 산출에 이 란이 없다"
        elif code in ("06", "10") and a < 0 and o == 0:
            note = "정답지는 결손을 음수로 적었다"
        ok = o is not None and o == a
        s["match" if ok else "diff"] += 1
        rows.append(row("3호", f"{code} {name}", a, o, "일치" if ok else "금액 다름", note))
    return rows, s


# ---------------------------------------------------------------- 표준재무제표(칸 대조)

STD_FORMS = (("std_bs", "표준재무상태표"), ("std_is", "표준손익계산서"), ("std_cogs", "원가명세서"))


def ours_std(forms_json: dict | None) -> dict[str, dict[str, int]]:
    """서식.json 의 표준재무제표 란 {서식: {란 코드: 금액}}. 0 인 란은 뺀다."""
    out = {}
    for f in (forms_json or {}).get("forms", []):
        if f.get("code") in dict(STD_FORMS):
            cells = {}
            for it in f.get("items") or []:
                v = _i(it.get("value"))
                if v:
                    # 제조 말고 원가명세서(공사 · 임대 · 분양 · 운송 · 기타)는 「공사_53」 꼴이다. 정답지는 같은 란을 「53」 으로 읽는다.
                    c = str(it.get("code"))
                    cells[c.split("_", 1)[1] if f["code"] == "std_cogs" and "_" in c else c] = v
            out[f["code"]] = cells
    return out


def score_std(answer_cells: dict, ours: dict[str, dict[str, int]]) -> tuple[list[dict], dict]:
    """정답지 표준재무제표 란과 우리 란을 코드별로 견준다. 정답지에 금액이 있는 란만 센다.

    summary: {서식: {"cells": 정답 란 수, "match": 같음, "diff": 금액 다름, "missing": 빠짐, "extra": 우리만 있음}}
    """
    rows, summary = [], {}
    for code, name in STD_FORMS:
        a = {str(k): _i(v) for k, v in (answer_cells.get(code) or {}).items() if _i(v)}
        if not a:
            continue
        o = ours.get(code) or {}
        s = {"cells": len(a), "match": 0, "diff": 0, "missing": 0, "extra": sum(1 for c in o if c not in a)}
        for c, v in sorted(a.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            if c not in o:
                s["missing"] += 1
                rows.append(row(name, f"({c})", v, None, "빠짐"))
            elif o[c] == v:
                s["match"] += 1
            else:
                s["diff"] += 1
                rows.append(row(name, f"({c})", v, o[c], "금액 다름"))
        for c in o:
            if c not in a:
                rows.append(row(name, f"({c})", None, o[c], "더 있음"))
        summary[code] = s
    return rows, summary


# ---------------------------------------------------------------- 50호(갑) · 결손금

def ours_items_50gap(forms_json: dict | None) -> dict:
    for f in (forms_json or {}).get("forms", []):
        if norm_code(f.get("code")) == "50갑" and f.get("items"):
            return {str(it.get("code")): it.get("value") for it in f["items"]}
    return {}


def score_50gap(answer50: dict, ours: dict, answer_losses: list[dict], our_losses: list[dict] | None, fy: str,
                answer_income) -> tuple[list[dict], dict]:
    rows, s = [], {"match": 0, "diff": 0, "missing": 0, "extra": 0, "excluded": 0}
    if ours:
        for code, name in ITEMS_50GAP.items():
            for suffix, col in (("_2", "기초"), ("", "기말")):
                k = code + suffix
                a = _i(answer50.get(k))
                o = _i(ours.get(k)) if k in ours else None
                ok = o == a
                s["match" if ok else "diff"] += 1
                rows.append(row("50호(갑)", f"{name} {col}", a, o, "일치" if ok else "금액 다름",
                                "" if o is not None else "우리 산출에 이 란이 없다"))
    if our_losses is not None:
        # 정답지 쪽은 인쇄된 결손금 줄만 본다(3호 06 으로 채운 derived 줄은 정답이 아니다)
        ans = {str(x.get("year")): x for x in answer_losses if not x.get("derived")}
        ours_l = {str(x.get("year")): x for x in our_losses if _i(x.get("incurred")) or _i(x.get("remaining"))}
        for y in sorted(set(ans) | set(ours_l)):
            a, o = ans.get(y), ours_l.get(y)
            key = f"결손금 {y}"
            if a is None and y == fy and answer_income is not None and _i(answer_income) < 0:
                s["excluded"] += 1
                rows.append(row("50호(갑)", key, None, _i(o.get("remaining")), "채점 제외",
                                "정답지가 결손인데 결손금 표에 그해 줄을 적지 않았다(정답지 오류, 계약 10절)"))
            elif a is None:
                s["extra"] += 1
                rows.append(row("50호(갑)", key, None, _i(o.get("remaining")), "더 있음"))
            elif o is None:
                s["missing"] += 1
                rows.append(row("50호(갑)", key, _i(a.get("remaining")), None, "빠짐"))
            else:
                diffs = [k for k in ("incurred", "used", "remaining") if _i(a.get(k)) != _i(o.get(k))]
                s["diff" if diffs else "match"] += 1
                rows.append(row("50호(갑)", key, _i(a.get("remaining")), _i(o.get("remaining")),
                                "금액 다름" if diffs else "일치",
                                ("다른 칸: " + ", ".join(diffs)) if diffs else ""))
    return rows, s


# ---------------------------------------------------------------- 50호(을)

COLS = (("opening", "기초"), ("decrease", "감소"), ("increase", "증가"), ("closing", "기말"))


def score_reserves(answer: list[dict], ours: list[dict]) -> tuple[list[dict], dict]:
    O = [o for o in ours if o.get("subject") or any(_i(o.get(k)) for k, _ in COLS)]
    used, rows = set(), []
    s = {"match": 0, "amount_diff": 0, "missing": 0, "extra": 0}
    for a in answer:
        j = next((j for j, o in enumerate(O) if j not in used and norm_subject(o.get("subject")) == norm_subject(a["subject"])),
                 None)
        if j is None:
            j = next((j for j, o in enumerate(O) if j not in used and _i(o.get("closing")) == _i(a.get("closing"))
                      and _i(a.get("closing"))), None)
        if j is None:
            s["missing"] += 1
            rows.append(row("50호(을)", a["subject"], _i(a.get("closing")), None, "빠짐"))
            continue
        used.add(j)
        o = O[j]
        diffs = [name for k, name in COLS if _i(a.get(k)) != _i(o.get(k))]
        notes = [f"우리 과목 {o.get('subject')}"] if norm_subject(o.get("subject")) != norm_subject(a["subject"]) else []
        if diffs:
            notes.append("다른 칸: " + ", ".join(f"{name} 정답 {won(_i(a.get(k)))} · 우리 {won(_i(o.get(k)))}"
                                              for k, name in COLS if name in diffs))
        s["amount_diff" if diffs else "match"] += 1
        rows.append(row("50호(을)", a["subject"], _i(a.get("closing")), _i(o.get("closing")),
                        "금액 다름" if diffs else "일치", " · ".join(notes)))
    for j, o in enumerate(O):
        if j not in used:
            s["extra"] += 1
            rows.append(row("50호(을)", str(o.get("subject") or ""), None, _i(o.get("closing")), "더 있음"))
    return rows, s


# ---------------------------------------------------------------- 채점 제외(정답지 오류)

def answer_exclusions(answer: dict) -> list[dict]:
    """정답지에서 채점하지 않는 란(계약 10절). 23호(을) 신용카드 미사용 금액이 음수면, 21호가 있으면 ① 소득금액계."""
    rows = []
    c23 = answer.get("cells", {}).get("23을", {})
    for k in ("합계_15", "15", "합계_17", "17"):
        v = c23.get(k)
        if v is not None and _i(v) < 0:
            rows.append(row("23호", "신용카드 등 미사용 금액", _i(v), None, "채점 제외",
                            "정답지 23호(을) 신용카드 미사용 금액이 음수다(정답지 오류, 계약 10절)"))
            break
    if any(f.get("code") == "21" for f in answer.get("forms", [])):
        rows.append(row("21호", "① 소득금액계", None, None, "채점 제외",
                        "정답지 21호 ① 이 3호 04 차가감소득금액 + 기부금과 맞지 않을 수 있다(계약 10절). 21호는 아직 읽지 않는다"))
    return rows
