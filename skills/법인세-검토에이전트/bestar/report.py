# -*- coding: utf-8 -*-
"""AR 보고서(1 AR/AR_보고서.md). 화면과 같은 자료(review.build)로 쓴다.

차례: 머리 → 훑은 범위 → 가장 중요한 3가지 · 먼저 받을 자료 → 1 전사 기준 → 2 재무제표 계정별(+ 소득금액 계산, 엔진 규칙에 안 걸린 계정)
      → 3 세액공제 → 회계사에게 물을 것 → 이 보고서의 한계.
묶음 표에는 이슈 줄(조정 예상 · 판단 필요 · 자료 필요)을 싣고, 확인 · 해당 없음 줄은 묶음 끝에 이름만 모은다.
"""
from __future__ import annotations

import re
from pathlib import Path

JD = {"조정 필요": "조정 예상"}
WON_SIGN = re.compile(r"(△)?₩(\d{1,3}(?:,\d{3})*)")


def _won(n) -> str:
    if not isinstance(n, (int, float)):
        return ""
    n = int(round(n))
    return ("△" if n < 0 else "") + f"{abs(n):,}원"


def _cell(x) -> str:
    return str(x or "").replace("|", "／").replace("\n", " ").strip() or "-"


def _plain(text: str, facts: dict[str, dict]) -> str:
    """₩1,000 → 1,000원, 합계 · PDF 값 id(s2 · p1)는 금액을 붙여 풀어 쓴다."""
    text = WON_SIGN.sub(lambda m: f"{m.group(1) or ''}{m.group(2)}원", str(text or ""))

    def fact(m):
        f = facts.get(m.group(0))
        if not f:
            return m.group(0)
        v = f.get("net") if f.get("type") == "합계" else f.get("amount")
        v = abs(v) if isinstance(v, (int, float)) else v           # 대변 합계(수익)도 크기로 적는다
        return f"{f.get('what')} {_won(v)}" + ("(전기 PDF 판독, 확인 전)" if f.get("type") != "합계" else "")
    text = re.sub(r"합계\s+(?=[sp]\d{1,3}(?![A-Za-z0-9]))", "", text)  # 「합계 s1」 의 「합계」 가 겹치지 않게
    return re.sub(r"(?<![A-Za-z0-9])[sp]\d{1,3}(?![A-Za-z0-9])", fact, text)


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def build(d: dict) -> str:
    facts = {f["id"]: f for f in d.get("facts") or []}
    return _plain(_build(d), facts)


def _build(d: dict) -> str:
    sh = d.get("ar_sheet") or {}
    cov = sh.get("coverage") or {}
    L = []
    L.append(f"# {d.get('company')} {d.get('fy')} 사업연도 법인세 분석적 검토")
    L.append("")
    sme = d.get("sme") or {}
    pr = d.get("progress") or {}
    L.append(f"- 사업연도: {d.get('period') or ''}{d.get('fy_start')} ~ {d.get('fy_end')}")
    L.append(f"- 기업 구분 전제: {sme.get('premise')} ({sme.get('status')})")
    L.append(f"- 진행: 1-(1) ~ 2-(2) 단계 {pr.get('steps_done')}/{pr.get('steps_total')} · AI 메모 {pr.get('memos')}/{pr.get('issues')} · "
             f"회계사 결론 {pr.get('conclusions')} · 공제 제안 {pr.get('credits')}건")
    L.append(f"- 만든 때: {str(d.get('generated_at') or '').replace('T', ' ')}. 초안입니다. 조정 금액은 엔진 조서 계산값이고, 확정과 공제 적용은 회계사가 정합니다.")
    if d.get("gaps"):
        L.append("")
        L.append("> 덜 끝난 것: " + " / ".join(d["gaps"]))
    L.append("")
    inc = d.get("income") or {}
    if inc.get("tax_base") is not None:
        pend = d.get("pending_adjustments") or []
        pay = inc.get("payable") or 0
        L.append("## 세액 한눈에 (조서 계산, 확정 전)")
        L.append("")
        L += _table(["과세표준", "산출세액", "결정세액", "차감납부할세액" if pay >= 0 else "환급받을 세액"],
                    [[_won(inc.get("tax_base")), _won(inc.get("computed_tax") or 0), _won(inc.get("determined_tax") or 0), _won(abs(pay))]])
        L.append("")
        L.append("위 숫자는 조서가 계산한 조정만 넣은 것입니다. 아래 표는 조서에 아직 들어가지 않은 금액과, 그 금액만 바뀔 때의 산출세액 차이(엔진 세율로 추정, 공제 · 감면 · 최저한세 변화 제외)입니다.")
        L.append("")
        rows = [[f"{x['paper']} (조서가 확인 필요로 둠)", f"가산 {_won(x['amount'])}", _won(x["tax"]) if x.get("tax") else "0원"] for x in pend]
        s_ = d.get("summary") or {}
        seen = set()
        for t in ("top", "check", "detail"):
            for u in s_.get(t) or []:
                st = u.get("stake")
                if not st or u["uid"] in seen:
                    continue
                seen.add(u["uid"])
                rows.append([f"{u['title']} ({u.get('judgment') or ''})", f"{st.get('side')} {_won(abs(st.get('amount') or 0))}",
                             _won(u["tax_delta"]) if u.get("tax_delta") else "0원"])
        if rows:
            L += _table(["조서에 아직 없는 것", "걸린 금액", "산출세액 차이(추정)"], rows)
        else:
            L.append("조서에 아직 들어가지 않은 금액을 메모에 적은 것이 없습니다(메모 stake).")
        missing = d.get("adjust_without_paper") or []
        if missing:
            L.append("")
            L.append(f"조정 필요로 판단했는데 조서 금액이 없는 항목 {len(missing)}건: " + ", ".join(missing[:6]) + (" 외" if len(missing) > 6 else "")
                     + ". 금액은 조서 「직접 조정」 줄이나 노란 칸에서 넣습니다.")
        if (inc.get("tax_base") or 0) < 0 and d.get("prior_tax") is not None:
            L.append("")
            L.append(f"결손 사업연도입니다. 소급공제를 판단할 숫자: 당기 결손 {_won(abs(inc.get('tax_base')))}, 직전 사업연도 산출세액 {_won(d['prior_tax'])}(전기 신고서 3호). 환급액은 68호에서 계산합니다.")
        L.append("")

    # 훑은 범위
    L.append("## 훑은 범위")
    L.append("")
    if cov.get("guide_lines"):
        L.append(f"- AR 가이드 {cov['guide_lines']}줄(계정 {cov.get('account_groups')}묶음 포함): 해당 {cov.get('issue')} · 해당 없음 {cov.get('na')} · 자료 필요 {cov.get('need')}")
    acc = cov.get("accounts") or {}
    if acc:
        L.append(f"- 시산표 계정 {acc.get('total')}개(금액 있는 것): 엔진 규칙 · 엔진 이슈 · AI 가 다룬 계정 {acc.get('covered')}개, 나머지 {len(acc.get('outside') or [])}개는 2-(1) 에서 한 줄씩 훑음(아래 2절 끝)")
    fm = cov.get("forms") or {}
    if fm:
        chk = fm.get("check") or []
        L.append(f"- 신고 서식 {fm.get('total')}종: 해당 {fm.get('yes')} · 낼지 확인 {len(chk)}" + (f"({', '.join(str(x['code']) for x in chk[:12])}{' …' if len(chk) > 12 else ''})" if chk else ""))
    L.append(f"- 엔진 이슈 {cov.get('issues', 0)}건 · AI 추가 이슈 {cov.get('added', 0)}건 · 공제 제안 {cov.get('credits', 0)}건 · 조서 조정 {cov.get('adjustments', 0)}건이 아래 세 묶음에 모두 들어 있습니다.")
    L.append("")

    # 가장 중요한 3가지
    s = d.get("summary") or {}
    if s.get("top"):
        L.append("## 가장 중요한 3가지")
        L.append("")
        for n, u in enumerate(s["top"], 1):
            eff = ""
            pend_u = [x for x in d.get("pending_adjustments") or [] if x.get("paper_id") in (u.get("papers") or [])]
            if pend_u and not u.get("stake"):
                x = pend_u[0]
                eff = f" 조서가 확인 필요로 둔 {x['paper']} {_won(x['amount'])}" + (f", 산출세액 차이(추정) {_won(x['tax'])}" if x.get("tax") else "") + "."
            if u.get("stake"):
                st = u["stake"]
                eff = f" 걸린 금액 {st.get('side')} {_won(abs(st.get('amount') or 0))}"
                if u.get("tax_delta") is not None:
                    eff += f", 산출세액 차이(추정) {_won(u['tax_delta'])}" if u["tax_delta"] else ", 당기 산출세액 차이 없음(결손금이 그만큼 바뀜)"
                eff += "."
            L.append(f"{n}. **{u['title']}**: {u.get('line') or ''}{eff} ({u.get('where')} · {u.get('judgment') or '메모 없음'} · 위험 {u.get('risk')})")
        if s.get("first_asks"):
            L.append("")
            L.append("먼저 받을 자료")
            L.append("")
            L += [f"- {q}" for q in s["first_asks"]]
        L.append("")

    # 세 묶음
    for k, g in enumerate(sh.get("groups") or [], 1):
        rows = g.get("rows") or []
        issues = [r for r in rows if r.get("issue")]
        rest = [r for r in rows if not r.get("issue")]
        L.append(f"## {k}. {g['label']} (이슈 {len(issues)} / 전체 {len(rows)})")
        L.append("")
        L.append(g.get("desc") or "")
        L.append("")
        if issues:
            L += _table(["항목", "관련(장부 · 전기)", "추정 판단", "추가 요청"],
                        [[r["title"], r.get("relation"),
                          f"**{JD.get(r['judgment'], r['judgment'])}**" + (f" {_won(r['amount'])}" if isinstance(r.get("amount"), (int, float)) else "")
                          + (f". {r['judgment_text']}" if r.get("judgment_text") else ""),
                          " / ".join(r.get("asks") or []) or "없음"] for r in issues])
        else:
            L.append("이슈 없음.")
        if rest:
            L.append("")
            L.append("확인 · 해당 없음: " + ", ".join(f"{r['title']}({JD.get(r['judgment'], r['judgment'])})" for r in rest))
        if g["key"] == "accounts":
            inc = d.get("income") or {}
            if inc.get("net_income") is not None:
                L.append("")
                L.append("소득금액 계산(조서)")
                L.append("")
                rows = [["결산서상 당기순이익", _won(inc.get("net_income"))],
                        [f"+ 익금산입 · 손금불산입 {inc.get('add_count')}건", _won(inc.get("add") or 0)],
                        [f"- 손금산입 · 익금불산입 {inc.get('deduct_count')}건", _won(inc.get("deduct") or 0)]]
                if inc.get("donation_excess"):
                    rows.append(["+ 기부금 한도초과액", _won(inc.get("donation_excess"))])
                rows.append(["각사업연도소득금액", _won(inc.get("income"))])
                if inc.get("loss_used"):
                    rows.append(["- 이월결손금", _won(inc.get("loss_used"))])
                rows += [["과세표준", _won(inc.get("tax_base"))], ["산출세액", _won(inc.get("computed_tax") or 0)]]
                if inc.get("credits"):
                    rows.append(["- 공제 · 감면세액", _won(inc.get("credits"))])
                if inc.get("penalty"):
                    rows.append(["+ 가산세", _won(inc.get("penalty"))])
                rows.append(["결정세액(지방소득세 제외)", _won(inc.get("determined_tax") or 0)])
                if inc.get("prepaid"):
                    rows.append(["- 기납부세액", _won(inc.get("prepaid"))])
                rows.append(["차감납부할세액", _won(inc.get("payable") or 0)])
                L += _table(["구분(3호 흐름, 조서 계산)", "금액"], rows)
                pend = d.get("pending_adjustments") or []
                if pend:
                    L.append("")
                    L.append("회계사 답에 따라 더해질 수 있는 조정(위 표에 들어 있지 않음)")
                    L.append("")
                    L += _table(["조서", "답에 따라 생길 금액", "산출세액 차이(추정)", "조서 설명"],
                                [[x["paper"], _won(x["amount"]), _won(x["tax"]) if x.get("tax") else "0원(결손 안에서 줄어듦)", x.get("why") or ""] for x in pend])
            res = [r for r in d.get("reserves") or [] if any(r.get(k) for k in ("opening", "decrease", "increase", "closing"))]
            if res:
                L.append("")
                L.append("50호(을) 유보 이월(조서). 당기 변동이 없는 기초 유보는 그대로 두는 것이 맞는지 봅니다")
                L.append("")

                def state(r):
                    o, dec, inc = r.get("opening") or 0, r.get("decrease") or 0, r.get("increase") or 0
                    if o and not dec and not inc:
                        return "변동 없음(확인)"
                    parts = []
                    if o and dec:
                        parts.append("전액 추인" if dec == o else "일부 추인")
                    if inc:
                        parts.append("새로 생김" if not o else "증가")
                    return " · ".join(parts) or "-"
                L += _table(["과목", "기초", "감소", "증가", "기말", "상태"],
                            [[r.get("subject"), _won(r.get("opening") or 0), _won(r.get("decrease") or 0), _won(r.get("increase") or 0),
                              _won(r.get("closing") or 0), state(r)] for r in res])
            rev = d.get("others_reviewed") or []
            if rev or acc.get("outside"):
                L.append("")
                L.append(f"엔진 규칙에 안 걸린 계정 {len(acc.get('outside') or [])}개를 2-(1) 에서 훑은 결과")
                L.append("")
                L += _table(["계정", "본 것", "조정 단서"], [[", ".join(x.get("accounts") or []), x.get("note"), x.get("clue") or ""] for x in rev] or [["-", "아직 없음", ""]])
                clues = [x for x in rev if x.get("clue")]
                if clues:
                    L.append("")
                    L.append(f"훑다가 나온 조정 단서 {len(clues)}건은 회계사가 먼저 볼 것입니다.")
        L.append("")

    asks = d.get("company_asks") or []
    if asks:
        L.append("## 회사에 보낼 자료 요청")
        L.append("")
        L.append(f"위 표의 추가 요청을 겹치지 않게 모은 {len(asks)}건입니다. 회계사가 고를 것(답변 필요)은 다음 절에 따로 있습니다.")
        L.append("")
        L.append("「먼저」 는 가장 중요한 3가지에서 나온 요청입니다.")
        L.append("")
        L += [f"{n}. {'**먼저** ' if x.get('tier') == 0 else ''}{x['ask']} ({', '.join(x['from'][:3])}{' 외' if len(x['from']) > 3 else ''})"
              for n, x in enumerate(asks, 1)]
        L.append("")

    # 물을 것
    qs = [q for q in d.get("questions") or [] if not q.get("answer")]
    if qs:
        L.append("## 회계사에게 물을 것")
        L.append("")
        for q in qs:
            L.append(f"- **{q['title']}** ({q.get('kind')}) {q.get('description') or ''}")
            for o in q.get("options") or []:
                L.append(f"  - {o.get('label')}: {o.get('effect')}")
        L.append("")
    laws = [x for x in d.get("laws") or [] if x.get("law")]
    if laws:
        L.append("## 근거 조문")
        L.append("")
        L.append("조정 필요 · 판단 필요 항목의 근거 조문과 확인 등급입니다. ★★★ 두 곳 원문 확인, ★★☆ 한 곳 원문, ☆ 원문 미확인.")
        L.append("")
        L += _table(["항목", "판단", "근거 조문(등급)"],
                    [[x["title"], x.get("judgment") or "",
                      " / ".join((f"[{l.get('ref')}]({l['url']})" if l.get("url") else str(l.get("ref"))) + (f" {l['grade']}" if l.get("grade") else "")
                                 for l in x["law"] if isinstance(l, dict))]
                     for x in laws])
        L.append("")
    L.append("## 이 보고서의 한계")
    L.append("")
    L.append("- AR 가이드와 엔진 규칙, 시산표 계정 전수, 신고 서식 목록으로 훑었습니다. 장부에 없는 사실(특수관계, 계약, 실사, 인원 명부)은 위 추가 요청을 받아야 정해집니다.")
    L.append("- 조정 금액은 엔진 조서 계산(조서 엑셀 노란 칸 기본값)입니다. 노란 칸을 고치면 금액이 바뀝니다.")
    L.append("- 「세액 한눈에」 의 조서에 아직 없는 금액은 조서가 확인 필요로 둔 금액과 메모에 적은 걸린 금액입니다. 답을 고르거나(화면 · ar.py answer) 조서 노란 칸 · 직접 조정 줄에 넣어야 세액에 들어갑니다.")
    return "\n".join(L).rstrip() + "\n"


def write(d: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(d), encoding="utf-8")
