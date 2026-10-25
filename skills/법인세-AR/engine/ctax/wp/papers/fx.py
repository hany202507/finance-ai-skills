"""15 외화환산: 화폐성 외화자산 · 부채 평가손익(40호(갑)(을)).

금융회사 외 법인은 사업연도 종료일 매매기준율 평가방법을 신고해야 그 방법을 쓰고, 신고하기 전에는 취득일 · 발생일 환율로
둔다(법인세법 시행령 제76조 제2항 단서 · 제6항). 그래서 노란 칸 「평가방법 신고」 가
- 「부」 면 장부의 외화환산이익은 익금불산입(△유보), 외화환산손실은 손금불산입(유보)
- 「여」 면 화폐성 항목의 환산손익은 그대로 두고, 선급금 · 선수금 같은 비화폐성 항목의 환산손익만 부인한다(시행령 제73조 제3호)
전기 외화환산 유보는 노란 칸 「전기 유보 추인/<과목>」(기본 전액)으로 추인한다.

전기 유보 처리(노란 칸 「전기 유보 처리/<과목>」, 그대로 · 추인. `prior_compare.carry`)
  추인    전기 유보를 노란 칸 추인액만큼 추인한다. 기본값이다. 근거 전표는 둘이다. 환산 역분개(외화환산이익 계정 차변 · 외화환산손실
          계정 대변 줄, 회사가 전기 환산을 되돌림)와 상환 · 회수 전표(외환차익 · 외환차손 계정 줄). 둘 다 없으면 확인 줄을 낸다.
          상환 · 회수 전표가 전기 유보가 붙은 외화 항목의 것인지는 가리지 않는다.
  그대로  추인하지 않는다. 전기 신고서가 그 유보를 한 해 동안 그대로 두었을 때(전기 50호(을) 기초 = 기말 · 증감 0, 전기 15호에
          외화환산 줄 없음)만 기본값이고 조서는 「확인 필요」 다.
  평가방법을 신고하지 않은 법인은 취득일 · 발생일 환율로 두므로(시행령 제76조 제2항 단서) 환산 유보는 그 외화 항목을 상환받거나
  상환하는 사업연도에 익금 · 손금이 된다(같은 조 제5항). 신고한 법인은 사업연도 종료일 환율로 평가한 차손익이 그해 익금 · 손금이다
  (같은 조 제4항). 신고 전에 생긴 유보를 신고 뒤 언제 추인하는지는 엔진이 정하지 않는다.

외환차익 · 외환차손 계정의 기말 환산 줄(translation_lines). 회사가 기말 외화 환산손익을 외환차손익 계정에 적은 줄이다.
적요에 「기말」 이 있거나, 날짜가 사업연도 종료일이고 적요에 환산 · 평가 · 결산 · 기준 환율 · 환율 적용 표기가 있으면 환산분으로
보고 외화환산이익 · 손실에 더한다(확인 필요). 기중 날짜의 「환산차손」 적요 줄은 거래일 차손익으로 보아 넣지 않는다.

기본값: 전기 신고서에 외화환산 조정이 있으면 「부」, 조정 없이 40호를 냈으면 「여」, 둘 다 아니면 시행령 제76조 제2항 단서대로 「부」.
"""
from __future__ import annotations

import re

from ... import xlsx as X
from ..books import Books
from ..model import Adj, LineRow, Paper
from ..prior_compare import KEEP, carry, carry_head, carry_notes
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes
from .securities import match_prior, prior_reserves, vouchers

NAME = "외화환산"
FORMS = ["40갑", "40을", "15", "50을"]
LEDGER_CHECK = False

FX_PL = re.compile(r"외화환산|외화평가|환산이익|환산손실|환산차익|환산차손")
NOT_FX = re.compile(r"해외사업|해외산업")
FX_RESERVE = re.compile(r"외화|환산")
FX_ADJ = re.compile(r"외화환산|외화평가|환산이익|환산손실")
FX_NOTE = re.compile(r"외화.{0,8}(환산|평가)")
NON_MONETARY = re.compile(r"선급|선수|재고|상품|제품|원재료|유형|무형|투자부동산|건설중")
METHOD = "평가방법 신고"
SETTLE = re.compile(r"외환차익|외환차손|외환차|환차익|환차손")      # 상환 · 회수 차손익 계정(환산 계정은 뺀다)
# 외환차손익 계정 줄의 기말 환산 표기. 「기말」 은 날짜와 상관없이, 나머지는 사업연도 종료일 줄만 본다
YEAR_END_WORD = re.compile(r"기말")
TRANSLATE_WORD = re.compile(r"환산|평가|결산|기준\s*환율|환율\s*적용")
LAW = ("평가방법을 신고하지 않은 법인의 외화환산 유보는 그 외화 항목을 상환받거나 상환하는 사업연도에 익금 · 손금이 됩니다"
       "(법인세법 시행령 제76조 제2항 단서 · 제5항).")


def basis(rates: dict) -> list[tuple]:
    f = rates["fx"]
    return [(f"외화 {k}", f[key]["value"], f[key]["basis"], f[key]["grade"], None)
            for k, key in (("평가방법(신고 전)", "default_method"), ("평가방법(신고)", "reported_method"),
                           ("평가 대상", "monetary_only"), ("상환 차손익", "settlement"))]


def _default_method(b: Books) -> tuple[str, str]:
    prior = b.prior or {}
    adj = [a for a in prior.get("adjustments", []) or []
           if (FX_ADJ.search(a.get("subject") or "") or FX_NOTE.search(a.get("note") or ""))
           and not NOT_FX.search(a.get("subject") or "")]
    if adj:
        return "부", "전기 신고서에 외화환산 조정이 있어 평가방법을 신고하지 않은 것으로 보았습니다"
    filed = {f.get("code") for f in prior.get("forms", []) or [] if not f.get("blank")}
    if filed & {"40갑", "40을"}:
        return "여", "전기 신고서에 40호(외화자산등평가차손익조정명세서)가 있고 외화환산 조정이 없어 매매기준율 평가방법을 신고한 것으로 보았습니다"
    return "부", "평가방법 신고 이력을 모르므로 시행령 제76조 제2항 단서(신고 전에는 취득일 · 발생일 환율)대로 「부」 로 두었습니다"


def _related(a: dict) -> bool:
    """전기 15호 줄이 외화환산 줄인가(과목 · 조정내용)."""
    subj = a.get("subject") or ""
    return bool(FX_ADJ.search(subj) or FX_NOTE.search(a.get("note") or "")) and not NOT_FX.search(subj)


def is_translation(memo: str, day: str, fy_end: str) -> bool:
    """외환차익 · 외환차손 계정 줄이 기말 외화 환산 줄인가(적요 · 날짜). AR(ctax.ar.engine rule_fx)도 이 함수를 쓴다."""
    memo = str(memo or "")
    if YEAR_END_WORD.search(memo):
        return True
    return bool(fy_end) and str(day or "")[:10] == str(fy_end)[:10] and bool(TRANSLATE_WORD.search(memo))


def settle_accounts(b: Books) -> list[dict]:
    """외환차익 · 외환차손 계정(환산 계정과 해외사업환산은 뺀다)."""
    return [a for a in b.accounts(cls=("수익", "비용")) if SETTLE.search(a["name"]) and not FX_PL.search(a["name"])
            and not NOT_FX.search(a["name"])]


def translation_lines(b: Books) -> list[tuple]:
    """외환차손익 계정 줄 가운데 기말 환산 줄 [(줄, 계정)]."""
    fy_end = b.info.get("fy_end") or (f"{b.fy}-12-31" if b.fy else "")
    out = []
    for a in settle_accounts(b):
        for ln in b.lines_of([a]):
            if is_translation(ln.memo, ln.date, fy_end):
                out.append((ln, a))
    return out


def settled(b: Books, pl: list[dict], skip=frozenset()) -> dict:
    """전기 외화환산 유보를 추인할 근거 전표. 환산 역분개는 외화환산이익(수익) 계정의 차변 줄과 외화환산손실(비용) 계정의 대변
    줄이고, 상환 · 회수는 외환차익 · 외환차손 계정 줄이다. {역분개 줄, 역분개, 상환 줄, 상환}."""
    out = {"역분개 줄": 0, "역분개": 0, "상환 줄": 0, "상환": 0}
    for a in pl:
        for ln in b.lines_of([a]):
            net = ln.debit - ln.credit
            back = net if a["class"] == "수익" else -net
            if back > 0:
                out["역분개 줄"] += 1
                out["역분개"] += back
    for ln in b.lines_of(settle_accounts(b)):
        if id(ln) in skip:
            continue
        out["상환 줄"] += 1
        out["상환"] += abs(ln.debit - ln.credit)
    return out


def compute(p: Paper, b: Books) -> None:
    pl = [a for a in b.accounts(cls=("수익", "비용")) if FX_PL.search(a["name"]) and not NOT_FX.search(a["name"])]
    gains = [a for a in pl if a["class"] == "수익"]
    losses = [a for a in pl if a["class"] == "비용"]
    tl = translation_lines(b)
    t_gain = sum(ln.credit - ln.debit for ln, a in tl if a["class"] == "수익")
    t_loss = sum(ln.debit - ln.credit for ln, a in tl if a["class"] == "비용")
    gain = sum(int(a.get("amount") or 0) for a in gains) + t_gain
    loss = sum(int(a.get("amount") or 0) for a in losses) + t_loss
    prior = prior_reserves(b)
    old = {k: v for k, v in prior.items() if v and FX_RESERVE.search(k) and not NOT_FX.search(k)}
    default, why = _default_method(b)
    method = p.take(b, METHOD, default, "text")
    if method not in ("여", "부"):
        p.confirm.append(f"평가방법 신고 칸 「{method}」 을 읽지 못해 「{default}」 로 보았습니다(여 · 부)")
        method = default
    reported = method == "여"

    # 평가 전표의 반대쪽 줄 = 평가한 외화 항목(40호(을) 줄)
    vs = vouchers(b)
    codes = {a["code"] for a in pl} | {a["code"] for _ln, a in tl}
    items: dict[tuple[str, str], dict] = {}
    seen = set()
    for ln in b.lines_of(pl) + [ln for ln, _a in tl]:
        k = (ln.date, ln.no)
        if k in seen:
            continue
        seen.add(k)
        for o in vs.get(k, []):
            if o.account in codes:
                continue
            a = b.by_code.get(o.account) or {}
            if a.get("class") not in ("자산", "부채"):
                continue
            e = items.setdefault((o.account, o.partner), {"code": o.account, "name": a.get("name", o.account_name),
                                                          "partner": o.partner, "class": a.get("class"), "평가손익": 0,
                                                          "monetary": not NON_MONETARY.search(a.get("name", ""))})
            e["평가손익"] += o.debit - o.credit
    rows = []
    for e in items.values():
        e["기말"] = _closing(b, e)
        rows.append(e)
    rows.sort(key=lambda e: (e["class"] != "자산", e["code"], e["partner"]))
    nm = sum(e["평가손익"] for e in rows if not e["monetary"])
    monetary = sum(e["평가손익"] for e in rows if e["monetary"])
    book_net = gain - loss
    if rows and monetary + nm != book_net:
        p.confirm.append(f"평가 전표의 외화 항목 합계 {monetary + nm:,}원이 환산손익 순액 {book_net:,}원과 다릅니다. 평가 전표를 확인하세요")

    adjs: list[Adj] = []
    reversals = []
    carries = []
    for k, (subj, R) in enumerate(old.items()):
        key = f"전기 유보 추인/{subj}"
        c = carry(p, b, subj, R, key, _related)
        carries.append(c)
        # 반영은 처리가 「그대로」 면 0, 「추인」 이면 노란 칸 추인액이다
        reversals.append({"subject": subj, "기초유보": R, "추인": c.asked, "처리": c.shown, "반영": c.amount, "key": key,
                          "mode_key": c.key_mode})
        for name in (c.key_mode, key, c.key_applied):       # values 에는 reversals 로만 둔다(앞선 꼴 그대로)
            p.values.pop(name, None)
        if R < 0:
            adjs.append(Adj("가산", subj, c.amount, "유보", f"{subj} 전기분 추인", "전기 익금불산입한 외화환산이익 추인(익금산입)",
                            f"r{k}.반영", subj, "감소", -1))
        else:
            adjs.append(Adj("차감", subj, c.amount, "유보", f"{subj} 전기분 추인", "전기 손금불산입한 외화환산손실 추인(손금산입)",
                            f"r{k}.반영", subj, "감소", 1))
    t_gains = list({a["code"]: a for ln, a in tl if a["class"] == "수익"}.values())
    t_losses = list({a["code"]: a for ln, a in tl if a["class"] == "비용"}.values())
    gain_subj = (match_prior([a["name"] for a in gains + t_gains] + ["외화환산이익"], prior)
                 or (gains or t_gains or [{"name": "외화환산이익"}])[0]["name"])
    loss_subj = (match_prior([a["name"] for a in losses + t_losses] + ["외화환산손실"], prior)
                 or (losses or t_losses or [{"name": "외화환산손실"}])[0]["name"])
    if reported:
        dis_gain, dis_loss = max(0, nm), max(0, -nm)
        tax_val = monetary if rows else book_net
    else:
        dis_gain, dis_loss = gain, loss
        tax_val = 0
    adjs.append(Adj("차감", gain_subj, dis_gain, "유보", "외화환산이익 익금불산입",
                    "외화환산이익 익금불산입(평가방법 미신고)" if not reported else "비화폐성 항목 외화환산이익 익금불산입",
                    "환산이익 부인", gain_subj, "증가", -1))
    adjs.append(Adj("가산", loss_subj, dis_loss, "유보", "외화환산손실 손금불산입",
                    "외화환산손실 손금불산입(평가방법 미신고)" if not reported else "비화폐성 항목 외화환산손실 손금불산입",
                    "환산손실 부인", loss_subj, "증가", 1))
    p.adjustments = adjs
    p.accounts = pl
    for ln in b.lines_of(pl):
        p.lines.append(LineRow(ln, "외화환산", ""))
    for ln, a in tl:
        p.lines.append(LineRow(ln, "외화환산(외환차손익 계정 기말 환산)", ""))
    p.values = {"평가방법 신고": method, "외화환산이익": gain, "외화환산손실": loss, "회사계상 순액": book_net,
                "화폐성 평가손익": monetary, "비화폐성 평가손익": nm, "세법상 평가손익": tax_val,
                "손익조정금액": tax_val - book_net, "환산이익 부인": dis_gain, "환산손실 부인": dis_loss,
                "전기 유보 추인": sum(r["반영"] for r in reversals), "items": rows, "reversals": reversals,
                "외환차손익 계정 환산이익": t_gain, "외환차손익 계정 환산손실": t_loss}
    got = settled(b, pl, frozenset(id(ln) for ln, _a in tl)) if carries else {"역분개 줄": 0, "역분개": 0, "상환 줄": 0, "상환": 0}
    found = bool(carries) and bool(got["역분개 줄"] or got["상환 줄"])
    p.values["전기 유보 대조"] = [{**c.json(), "근거": got, "근거 있음": found} for c in carries]
    p.extra.update({"rows": rows, "reversals": reversals, "why": why, "translation": tl})
    if tl:
        names = " · ".join(dict.fromkeys(a["name"] for _ln, a in tl))
        p.confirm.append(f"{names} 계정에서 적요 · 날짜로 기말 외화 환산으로 보이는 줄 {len(tl)}줄(이익 {t_gain:,}원 · 손실 {t_loss:,}원)을 "
                         "외화환산이익 · 손실에 더했습니다. 거래일에 생긴 차손익(상환 · 회수)이면 원장 줄을 확인해 빼세요")
    if pl or tl:
        if METHOD in p.overridden:
            p.notes.append(f"평가방법 신고 「{method}」 는 회계사 값입니다")
        else:
            p.confirm.append(f"{why}. 화폐성외화자산등평가방법신고서 제출 여부를 확인하세요(노란 칸 여 · 부)")
    if reported and nm:
        p.notes.append(f"비화폐성 항목(선급금 · 선수금 등)의 환산손익 {nm:,}원은 평가 대상에서 빠져 부인했습니다(시행령 제73조 제3호)")
    law = LAW if not reported else (
        "매매기준율 평가방법을 신고한 법인은 사업연도 종료일 환율로 평가한 차손익이 그해 익금 · 손금입니다(법인세법 시행령 제76조 제4항). "
        "신고 전에 생긴 유보를 언제 추인하는지는 엔진이 정하지 않았습니다.")
    for c in carries:
        side = "가산" if c.closing < 0 else "차감"
        carry_notes(p, c, law=law, if_reverse=f"그 외화 항목을 당기에 갚았거나 받았으면 추인합니다. 그렇게 하면 {side} {c.asked:,}원입니다.")
    if carries:
        head = carry_head(carries)
        reversal = sum(c.amount for c in carries)
        parts = []
        if got["역분개 줄"]:
            parts.append(f"환산 역분개 {got['역분개 줄']}줄 {got['역분개']:,}원")
        if got["상환 줄"]:
            parts.append(f"상환 · 회수(외환차익 · 외환차손) {got['상환 줄']}줄 {got['상환']:,}원")
        if found:
            p.notes.append(f"{head}. 근거 전표: {' · '.join(parts)}. 이 전표가 전기 유보가 붙은 외화 항목의 것인지는 가리지 않았습니다. "
                           "기말에도 그대로 남은 항목이 있으면 노란 칸 「전기 유보 추인」 에서 그 금액을 빼세요")
        elif reversal:
            p.confirm.append(f"{head}. 환산 역분개와 상환 · 회수 전표(외환차익 · 외환차손)를 찾지 못해 추인의 근거 전표가 없습니다. {law} "
                             "외화 항목이 기말에도 그대로 남아 있으면 노란 칸 「전기 유보 추인」 에서 그 금액을 빼세요")
        else:
            p.notes.append(f"{head}. 환산 역분개와 상환 · 회수 전표(외환차익 · 외환차손)가 없습니다")
    p.settle(bool(pl or reversals or tl))


def _closing(b: Books, e: dict) -> int | None:
    """평가 뒤 원화 장부가(자산은 차변 잔액, 부채는 대변 잔액). 거래처 잔액이 있으면 그것, 없으면 계정 잔액(거래처 없는 줄)."""
    for r in b.ledger.get("partners", []) or []:
        if r.get("account") == e["code"] and (r.get("partner") or "").strip() == e["partner"]:
            c = int(r.get("closing") or 0)
            return c if e["class"] == "자산" else -c
    if not e["partner"]:
        a = b.by_code.get(e["code"]) or {}
        return int(a.get("amount") or 0)
    return None


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    v = p.values
    row = 5
    row = s.section(row, "1. 계정")
    X.header(s.ws, row, ["코드", "계정", "", "", "", "", "금액"], col=1)
    row += 1
    for a in p.accounts:
        s.put(row, 1, a["code"])
        s.put(row, 2, a["name"])
        s.put(row, 7, int(a.get("amount") or 0), money=True)
        row += 1
    t_rows = {}
    for ln, a in p.extra.get("translation") or []:
        t_rows[a["code"]] = (a, t_rows.get(a["code"], (a, 0))[1] + ((ln.credit - ln.debit) if a["class"] == "수익" else (ln.debit - ln.credit)))
    for code, (a, amt) in t_rows.items():
        s.put(row, 1, code)
        s.put(row, 2, f"{a['name']} 중 기말 환산분(적요 · 날짜)")
        s.put(row, 7, amt, money=True)
        row += 1
    if not p.accounts and not t_rows:
        s.put(row, 2, "외화환산손익 계정이 없습니다")
        row += 1
    row += 1
    row, _, _ = ledger(bk, s, row, p, "", title="2. 원장 검토(외화환산 줄)")
    row = s.section(row, "3. 평가한 외화 항목(평가 전표의 반대쪽 줄, 40호(을))")
    X.header(s.ws, row, ["구분", "코드", "계정", "거래처", "화폐성", "", "평가손익", "평가 뒤 장부가"], col=1)
    row += 1
    first = row
    for e in p.extra["rows"]:
        s.put(row, 1, "외화자산" if e["class"] == "자산" else "외화부채")
        s.put(row, 2, e["code"])
        s.put(row, 3, e["name"])
        s.put(row, 4, e["partner"])
        s.put(row, 5, "O" if e["monetary"] else "X")
        s.put(row, 7, e["평가손익"], money=True)
        s.put(row, 8, e["기말"], money=True)
        row += 1
    if not p.extra["rows"]:
        s.put(row, 3, "평가 전표에서 외화 항목을 찾지 못했습니다")
        row += 1
    last = row - 1
    row += 1
    row = s.section(row, "3-1. 손익조정(40호(갑))")
    X.note(s.ws, row, f"노란 칸: 평가방법 신고(여 · 부). {p.extra['why']}")
    row += 1
    r = Rows(bk, s, p, row)
    g = r.g
    r.put(METHOD, "사업연도 종료일 매매기준율 평가방법 신고(여 · 부)", p.inputs[METHOD], kind="input", input_kind="text", fmt="@")
    r.put("외화환산이익", "장부 외화환산이익", v["외화환산이익"])
    r.put("외화환산손실", "장부 외화환산손실", v["외화환산손실"])
    r.put("회사계상 순액", "③ 회사손익금 계상액(이익 - 손실)", f"={g('외화환산이익')}-{g('외화환산손실')}")
    r.put("화폐성 평가손익", "화폐성 항목 평가손익", f'=SUMIF(E{first}:E{last},"O",G{first}:G{last})')
    r.put("비화폐성 평가손익", "비화폐성 항목 평가손익(선급금 · 선수금 등)", f'=SUMIF(E{first}:E{last},"X",G{first}:G{last})')
    on = f'{g(METHOD)}="여"'
    r.put("세법상 평가손익", "② 당기손익금 해당액(신고 여: 화폐성 평가손익, 부: 0)",
          f"=IF({on},{g('화폐성 평가손익') if p.extra['rows'] else g('회사계상 순액')},0)")
    r.put("손익조정금액", "⑥ 손익조정금액(② - ③)", f"={g('세법상 평가손익')}-{g('회사계상 순액')}")
    r.put("환산이익 부인", "외화환산이익 익금불산입(차감 · △유보)",
          f"=IF({on},MAX(0,{g('비화폐성 평가손익')}),{g('외화환산이익')})")
    r.put("환산손실 부인", "외화환산손실 손금불산입(가산 · 유보)",
          f"=IF({on},MAX(0,-{g('비화폐성 평가손익')}),{g('외화환산손실')})")
    if p.extra["reversals"]:
        r.row = s.section(r.row + 1, "3-2. 전기 외화환산 유보 추인")
        for k, e in enumerate(p.extra["reversals"]):
            r.put(f"r{k}.기초유보", f"{e['subject']} 기초 유보(전기 50호(을))", e["기초유보"])
            r.put(e["mode_key"], f"{e['subject']} 전기 유보 처리({KEEP} · 추인)", p.inputs[e["mode_key"]], kind="input",
                  note="전기 중 증감이 없던 유보는 기본값이 「그대로」 입니다")
            r.put(e["key"], f"{e['subject']} 추인액(노란 칸, 기본 전액)", p.inputs[e["key"]], kind="input", input_kind="int")
            r.put(f"r{k}.반영", f"{e['subject']} 당기 추인 반영액(처리가 「{KEEP}」 면 0)",
                  f'=IF({g(e["mode_key"])}="{KEEP}",0,{g(e["key"])})')
        r.put("전기 유보 추인", "추인액 합계", "=" + "+".join(g(f"r{k}.반영") for k in range(len(p.extra["reversals"]))))
    row = adj_table(bk, s, r.row + 1, p, title="3-3. 세무조정 · 소득처분")
    row = forms_table(bk, s, row, p, [("40갑", "② 당기손익금 해당액", "세법상 평가손익"), ("40갑", "③ 회사손익금 계상액", "회사계상 순액"),
                                      ("40갑", "⑥ 손익조정금액", "손익조정금액")])
    notes(s, row, p)
