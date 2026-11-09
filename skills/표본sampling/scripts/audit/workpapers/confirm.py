"""3320 외부조회: 대상 선정 · 조회 대장 · 조회서 워드 초안 · 메일 초안 · 회신 대사(R4, 2026-10-05).

대상: 매출채권 거래처(잔액 상위 · 전기 분개장에 없던 거래처 · 수행중요성 이상 · 4000C 금액 단위 표본)와 은행.
대장은 _색인/조회.json(definitions/index_schema_workpapers.json)과 3320 엑셀 '조회 대장' 시트에 같이 둔다.
회계사가 엑셀에 적은 발송일 · 회신일 · 회신 금액 · 결과는 다음 make 때 되읽어 조회.json 에 합친다.
조회서 컨트롤 시트(2026-10-26)는 대상마다 발송 · 회신 · 차이 · 차이 사유 · 대체 절차 상태 · 상태를 한 표로 보이고, 현황은 그 건수를 센다.
회신 파일이 `00 받은자료/조회회신/` 에 들어오면 이름에 대상이 든 파일로 대사한다. 엑셀은 엔진이 금액을 읽고, PDF 는 AI 판독 필요로 남긴다.
은행조회는 별도 은행조회 회신 프로그램이 정본이라 대상 목록(CSV)만 내보내고 결과 확인 칸을 둔다.
조회서 · 메일은 초안만 만든다. 보내기는 회계사가 한다.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

from .. import figures, folder, reader, wp
from . import banks, common, lead
from .common import ask, won

DRAFT_DIR = "3320_조회서 초안"
REPLY_DIR = "00 받은자료/조회회신"
REPLY_LABELS = ("귀사확인금액", "확인금액", "회신금액", "귀사장부금액", "귀사잔액")

# 조회서 컨트롤(2026-10-26): 대상마다 발송 · 회신 · 차이 · 대체 절차 상태를 한 표로
LEDGER, CONTROL = "조회 대장", "조회서 컨트롤"
KIND_LABEL = {"매출채권": "매출채권", "매입채무": "채무", "은행": "은행"}
ALT_STATES = ("필요 없음", "진행 중", "끝남")
CONTROL_STATES = ("발송 전", "발송", "회신", "차이 확인", "대체 절차", "끝")


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def targets(d: Path, ctx: dict) -> dict:
    """조회 대상. {"ar": [...], "banks": [...], "pop": 매출채권 모집단}"""
    defs = ctx["defs"].get("confirmations", {})
    pop = lead.ar_population(ctx)
    pm = ctx["mat"]["performance"]
    rows = sorted(pop["rows"], key=lambda r: -r["amount"])
    sm = lead.ar_sample(ctx) if defs.get("ar_sample", True) else None
    picked = {r["key"] for r in sm["s"]["selected"]} if sm else set()
    top = {r["party"] for r in rows[: defs.get("ar_top_n", 5)]}
    issues = ctx["issues"]
    ar = []
    for r in rows:
        why = []
        if r["party"] in top:
            why.append("잔액 상위")
        if defs.get("ar_new_parties", True) and r["new"]:
            why.append("신규 거래처")
        if defs.get("ar_over_performance", True) and pm and r["amount"] >= pm:
            why.append("수행중요성 이상")
        if r["party"] in picked:
            why.append("4000C 표본")
        if defs.get("ar_opposite", True) and r["amount"] < 0:
            why.append("반대 잔액(대변)")
        if why and r["new"]:
            for i in issues:
                if i.get("area") in ("C", "P") and i.get("status") != "닫힘" and ("신규" in i.get("title", "") or "매출" in i.get("title", "")):
                    tag = f"이슈 {i['no']}"
                    if tag not in why:
                        why.append(tag)
        if why:
            ar.append({**r, "why": why})
    # 은행: 분개장 거래처 · 잔액증명 · 조회회신 파일 이름 · 색인 사실 문장에서 은행 이름
    keys = defs.get("bank_name_keys", ["은행"])
    pat = re.compile(r"([가-힣A-Za-z]{1,12}(?:" + "|".join(map(re.escape, keys)) + r"))")
    banks: dict[str, dict] = {}

    def add(name: str, why: str):
        if not any(name.endswith(k) for k in keys) or name in keys or "거래은행" in name:
            return
        e = banks.setdefault(name, {"target": name, "why": [], "lines": 0})
        if why not in e["why"]:
            e["why"].append(why)

    # 계정명세서의 예금 · 차입금 시트는 거래처가 곧 금융기관이다(R8, 진단 #17)
    bank_sheets = defs.get("bank_schedule_sheets", [])
    for rel in figures.received(d, reader.SCHEDULE):
        if Path(rel).suffix.lower() not in reader.EXCEL:
            continue
        for sh in reader.schedule_sheets(d / rel):
            if any(k in reader._norm(sh["sheet"]) for k in bank_sheets):
                for name, _ in sh["rows"]:
                    # 거래처 칸이 '(기업123)운영비' 처럼 계좌 이름이면 괄호 안 글자(숫자 뺌)를 금융기관으로 본다. 회계사가 확인한다
                    m = re.match(r"^\s*[(\[]([^)\]]+)[)\]]", name)
                    inst = (re.sub(r"[\d\-\s]+", "", m.group(1)) if m else "") or name
                    e = banks.setdefault(inst, {"target": inst, "why": [], "lines": 0})
                    why = f"계정명세서 '{sh['sheet']}' 시트" + (" 계좌 이름(금융기관 이름 확인 필요)" if m else "")
                    if why not in e["why"]:
                        e["why"].append(why)
    j = lead._journals(ctx)
    for x in j["cur"]:
        if x.party and any(x.party.endswith(k) for k in keys):
            add(x.party, "당기 분개장 거래")
            banks[x.party]["lines"] += 1
    docs = common.idx(d, "문서목록.json", {"files": []})
    for f in docs["files"]:
        if f.get("role") not in ("received", "permanent"):
            continue
        for m in pat.finditer(Path(f["path"]).stem):
            add(m.group(1), "받은자료 파일 이름")
        for fact in f.get("facts") or []:
            for m in pat.finditer(fact.get("text", "")):
                add(m.group(1), "받은자료 판독" + (" (AI, 확인 전)" if fact.get("basis") == "AI" else ""))
        if f.get("role") == "permanent" and f.get("kind") == "주요거래은행" and Path(f["path"]).suffix.lower() in reader.EXCEL:
            p = (d / f["path"]).resolve()
            if p.exists():
                from openpyxl import load_workbook

                wb = load_workbook(p, data_only=True, read_only=True)
                try:
                    for ws in wb.worksheets:
                        for row in ws.iter_rows(values_only=True):
                            v = str(row[0]).strip() if row and row[0] not in (None, "") else ""
                            if v:
                                add(v, "영구조서 180 주요거래은행")
                finally:
                    wb.close()
    return {"ar": ar, "banks": sorted(banks.values(), key=lambda b: (-b["lines"], b["target"])), "pop": pop}


# ---------------------------------------------------------------- 회신
def _reply_amount(path: Path) -> float | None:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = list(row)
                for i, v in enumerate(cells):
                    if reader._norm(v) in REPLY_LABELS:
                        for w in cells[i + 1:]:
                            n = reader._num(w)
                            if n is not None:
                                return n
    finally:
        wb.close()
    return None


def replies(d: Path, names: list[str]) -> dict:
    """대상 이름 → 회신 파일 판독 {file, amount, basis}. 이름이 긴 대상부터 맞춘다."""
    d = Path(d)
    root = d / REPLY_DIR
    out: dict[str, dict] = {}
    if not root.is_dir():
        return out
    std = folder.load_standard()
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and not folder._ignored(p.name, std)]
    for name in sorted(names, key=len, reverse=True):
        for p in files:
            if name in p.stem and p not in [x["path"] for x in out.values()]:
                rel = p.relative_to(d).as_posix()
                if p.suffix.lower() in reader.EXCEL:
                    amt = _reply_amount(p)
                    out[name] = {"path": p, "file": rel, "amount": reader._int(amt) if amt is not None else None,
                                 "basis": "엔진" if amt is not None else "AI 판독 필요"}
                else:
                    out[name] = {"path": p, "file": rel, "amount": None, "basis": "AI 판독 필요"}
                break
    return out


# ---------------------------------------------------------------- 초안
def _docx(path: Path, company: str, target: str, as_of: str, amount, account: str, others: list[tuple] | None = None) -> None:
    """채권 · 채무 잔액 조회서. 거래처의 채권 · 채무 계정(계정명세서 거래처 시트)을 한 장에 모두 적는다(R9 B5).
    others: [(채권 · 채무, 계정, 금액)] 조회 계정(account) 말고 같은 거래처의 다른 계정."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "맑은 고딕"
    st.font.size = Pt(10)
    doc.add_heading("채권 · 채무 잔액 조회서", level=1)
    doc.add_paragraph(f"{target} 귀중")
    doc.add_paragraph(f"발신: {company} 대표이사")
    doc.add_paragraph(f"기준일: {as_of}")
    doc.add_paragraph(
        "당사 외부감사인의 감사를 위하여 귀사와 당사 사이의 채권 · 채무 잔액을 확인하고자 합니다. "
        "아래 금액이 귀사 장부와 같은지 확인하시고, 다르면 귀사 금액과 차이 내역을 적어 아래 감사인에게 직접 회신해 주십시오. "
        "이 조회는 지급을 요청하는 것이 아닙니다.")
    t = doc.add_table(rows=1, cols=5)
    t.style = "Table Grid"
    for c, h in zip(t.rows[0].cells, ["구분(당사 기준)", "계정", "당사 장부 금액", "귀사 확인 금액", "차이 내역"]):
        c.text = h
    for side, acct, amt in [("채권", account, amount)] + list(others or []):
        c = t.add_row().cells
        c[0].text, c[1].text, c[2].text = side, acct, f"{won(amt)}원"
    t2 = doc.add_table(rows=0, cols=2)
    t2.style = "Table Grid"
    for a, b in [("그 밖의 채권 · 채무", "위에 없는 거래(선급 · 선수 · 대여 · 차입 · 보증 등)가 있으면 적어 주십시오"),
                 ("회신처(감사인)", "감사인 주소 · 전자우편(감사인 기입)"), ("확인자 · 날인", "")]:
        c = t2.add_row().cells
        c[0].text, c[1].text = a, b
    doc.add_paragraph("")
    doc.add_paragraph(f"{company} 대표이사 (인)")
    doc.add_paragraph("이 문서는 감사 엔진이 만든 초안이다. 회사 날인과 발송은 감사인이 확인한 뒤 한다.").runs[0].italic = True
    doc.save(path)


def _mail(path: Path, company: str, target: str, as_of: str, amount) -> None:
    body = f"""받는 사람: {target} 담당자 (전자우편 주소는 감사인이 적는다)
제목: [{company}] {as_of} 기준 채권 잔액 확인 요청

{target} 담당자님께

{company} 외부감사를 맡은 감사인입니다.
{company} 의 {as_of} 현재 귀사에 대한 채권 잔액 {won(amount)}원을 확인하고자 조회서를 첨부해 드립니다.
첨부 조회서의 귀사 확인 금액 칸에 귀사 장부 금액을 적고 날인하신 뒤, 이 전자우편 주소(감사인)로 직접 회신해 주십시오.
금액이 다르면 차이 내역을 함께 적어 주십시오. 이 조회는 지급을 요청하는 것이 아닙니다.

회신 기한: (감사인이 적는다)

감사인 (이름 · 연락처)

첨부: 3320_조회서_{_safe(target)}.docx
"""
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- 만들기
def _parse_date(v) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (date, datetime)):
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    dd = reader._date(v)
    return dd.isoformat() if dd else str(v)


def payables(d: Path, ctx: dict) -> list[dict]:
    """채무 조회 대상(2026-10-24): 계정명세서의 외상매입금 · 미지급금 거래처 가운데 잔액 상위 · 수행중요성 이상 · 반대(차변) 잔액.
    금융기관 이름이 든 거래처는 은행조회로, 거래처가 아닌 줄(non_party_keywords)은 뺀다."""
    defs = ctx["defs"].get("confirmations", {})
    if not defs.get("ap", True):
        return []
    names = defs.get("ap_accounts", ["외상매입금", "매입채무", "지급어음", "미지급금"])
    bank_keys = defs.get("bank_name_keys", ["은행"])
    skip = defs.get("non_party_keywords", [])
    pm = ctx["mat"]["performance"]
    rows = []
    for party, accs in banks.party_accounts(d).items():
        mine = [(a, v) for side, a, v in accs if side == "채무" and a in names]
        if not mine or any(k in party for k in bank_keys) or any(k in reader._norm(party) for k in skip):
            continue
        rows.append({"party": party, "amount": sum(v for _, v in mine), "accounts": sorted({a for a, _ in mine})})
    top = {r["party"] for r in sorted(rows, key=lambda r: -r["amount"])[: defs.get("ap_top_n", 3)] if r["amount"] > 0}
    out = []
    for r in sorted(rows, key=lambda r: -abs(r["amount"])):
        why = []
        if r["party"] in top:
            why.append("잔액 상위")
        if pm and r["amount"] >= pm:
            why.append("수행중요성 이상")
        if r["amount"] < 0:
            why.append("반대 잔액(차변)")
        if why:
            out.append({**r, "why": why})
    return out


def alt_candidates(d: Path, ctx: dict, ar: list[dict], ap: list[dict]) -> dict:
    """대체 절차 후보(2026-10-24). 회신이 안 올 때 쓸 증빙을 분개장에서 미리 찾아 둔다. 판단은 회계사.
    매출채권: 기말 후 입금(입금 증빙), 결산월 청구 가운데 부가세가 없는 것(세금계산서 발행 전일 수 있음), 반대 잔액.
    채무: 기말 후 지급, 반대 잔액. {거래처: [문장]}"""
    from . import lead
    defs = ctx["defs"].get("confirmations", {})
    j = lead._journals(ctx)
    acc = common.load_def("jet.yaml")["accounts"]
    end = date.fromisoformat(str(common.case(d).get("fiscal_year_end")))
    nov: dict[str, float] = {}
    for v in common.vouchers(j["cur"]):
        if (end - v.date).days > defs.get("alt_days", 31):
            continue
        vat = any(lead._is(x.code, x.name, acc["vat_output"]) for x in v.lines if x.cr)
        for x in v.lines:
            if x.dr and x.party and lead._is(x.code, x.name, acc["receivable"]) and not vat:
                nov[x.party] = nov.get(x.party, 0) + x.dr
    paid: dict[str, float] = {}
    for v in common.vouchers(j["post"]):
        if not any(lead._is(x.code, x.name, acc["cash"]) for x in v.lines if x.cr):
            continue
        for x in v.lines:
            if x.dr and x.party and any(n in (x.name or "") for n in defs.get("ap_accounts", ["외상매입금", "미지급금"])):
                paid[x.party] = paid.get(x.party, 0) + x.dr
    out: dict[str, list[str]] = {}
    for r in ar:
        amt, col, s = r["amount"], r.get("collected") or 0, []
        n = nov.get(r["party"]) or 0
        if n:
            # 부가세 없는 결산월 청구가 있으면 그 경고가 먼저다. 기말 후 입금이 그 청구분이면 다음 기간 대금이라 기말 채권의 증거가 못 된다
            s.append(f"결산월 청구 {won(n)} 에 부가세가 없음(세금계산서 발행 전 · 다음 기간 대금일 수 있음). 계약서 · 청구 기간 · 세금계산서 확인")
            if amt > 0 and col:
                s.append(f"기말 후 입금 {won(col)} 은 그 청구분이면 다음 기간 대금이라 기말 채권의 증거로 쓰기 전에 청구 기간 확인")
        elif amt > 0:
            s.append(f"기말 후 입금 {won(col)}(잔액의 {col / amt:.0%})" if col else "기말 후 입금 없음. 세금계산서 · 용역 제공 증빙 요청")
        if amt < 0:
            s.append("반대 잔액. 이중 입금 · 선수 여부를 입금 증빙과 기말 후 환불로 확인")
        out[r["party"]] = s
    for r in ap:
        s = []
        if r["amount"] > 0:
            p = paid.get(r["party"], 0)
            s.append(f"기말 후 지급 {won(p)}(잔액의 {p / r['amount']:.0%})" if p else "기말 후 지급 없음. 거래명세서 · 세금계산서 요청")
        else:
            s.append("반대 잔액. 선급 · 이중 지급 여부를 지급 증빙과 기말 후 환급으로 확인")
        out.setdefault(r["party"], []).extend(s)
    return out


def make(d: Path, ctx: dict, force: bool = False) -> dict:
    d = Path(d)
    c = common.case(d)
    company = (c.get("company") or {}).get("name", "")
    as_of = c.get("fiscal_year_end", "")
    t = targets(d, ctx)
    ar_names = {x["party"] for x in t["ar"]}
    ap = [x for x in payables(d, ctx) if x["party"] not in ar_names]   # 매출채권 조회서에 채무 줄이 함께 들어가는 거래처는 뺀다
    alts = alt_candidates(d, ctx, t["ar"], ap)
    old = common.old_inputs(d, "3320")
    prev = {(x["kind"], x["target"]): x for x in (common.idx(d, "조회.json", {}) or {}).get("confirmations", [])}
    rep = replies(d, [x["party"] for x in t["ar"]] + [x["target"] for x in t["banks"]] + [x["party"] for x in ap])
    accts = banks.party_accounts(d)

    wpdir = wp.path_for(d, "3320").parent
    draft = wpdir / DRAFT_DIR
    draft.mkdir(parents=True, exist_ok=True)

    entries = []
    for n, r in enumerate(t["ar"], 1):
        name = r["party"]
        sent = old.get(("조회 대장", f"발송일: {name}")) or (prev.get(("매출채권", name)) or {}).get("sent_at")
        replied = old.get(("조회 대장", f"회신일: {name}")) or (prev.get(("매출채권", name)) or {}).get("replied_at")
        acct_amt = old.get(("조회 대장", f"회신 금액: {name}"))
        e = {"no": n, "kind": "매출채권", "target": name, "why": r["why"], "account": "매출채권", "amount": r["amount"],
             "amount_basis": "엔진(" + (t["pop"]["source"] or "") + ")", "method": None, "sent_at": _parse_date(sent),
             "replied_at": _parse_date(replied), "reply_amount": None, "reply_basis": None, "reply_file": None, "difference": None,
             "alternative": old.get(("조회 대장", f"대체 절차: {name}")), "result": old.get(("조회 대장", f"확인 결과: {name}")),
             "status": "발송 전", "issue": (prev.get(("매출채권", name)) or {}).get("issue"), "drafts": [],
             "alt_candidates": alts.get(name, [])}
        rp = rep.get(name)
        if rp:
            e["reply_file"] = rp["file"]
            if rp["amount"] is not None:
                e.update(reply_amount=rp["amount"], reply_basis="엔진")
            elif isinstance(acct_amt, (int, float)):
                e.update(reply_amount=acct_amt, reply_basis="회계사")
            else:
                e["reply_basis"] = "AI 판독 필요"
        elif isinstance(acct_amt, (int, float)):
            e.update(reply_amount=acct_amt, reply_basis="회계사")
        if e["reply_amount"] is not None:
            e["difference"] = common.reader._int(e["reply_amount"] - e["amount"])
            e["status"] = "회신 일치" if abs(e["difference"]) < 1 else "회신 차이"
        elif e["reply_basis"] == "AI 판독 필요":
            e["status"] = "AI 판독 필요"
        elif e["sent_at"]:
            e["status"] = "발송"
        doc = draft / f"3320_조회서_{_safe(name)}.docx"
        mail = draft / f"3320_메일초안_{_safe(name)}.txt"
        others = [x for x in accts.get(name, []) if not (x[0] == "채권" and x[1] in ("외상매출금", "매출채권"))]
        _docx(doc, company, name, as_of, r["amount"], "외상매출금(매출채권)", others)
        e["accounts"] = ([{"side": "채권", "account": "외상매출금(매출채권)", "amount": r["amount"]}]
                         + [{"side": x[0], "account": x[1], "amount": x[2]} for x in others])
        _mail(mail, company, name, as_of, r["amount"])
        e["drafts"] = [doc.relative_to(d).as_posix(), mail.relative_to(d).as_posix()]
        entries.append(e)
    for b in t["banks"]:
        name = b["target"]
        p = prev.get(("은행", name)) or {}
        e = {"no": len(entries) + 1, "kind": "은행", "target": name, "why": b["why"], "account": "예금 · 차입금 · 담보 · 보증",
             "amount": None, "amount_basis": "은행조회 회신 프로그램 결과와 대사", "method": "은행조회 프로그램",
             "sent_at": _parse_date(old.get(("조회 대장", f"발송일: {name}")) or p.get("sent_at")),
             "replied_at": _parse_date(old.get(("조회 대장", f"회신일: {name}")) or p.get("replied_at")),
             "reply_amount": None, "reply_basis": None, "reply_file": rep[name]["file"] if name in rep else None,
             "difference": None, "alternative": old.get(("조회 대장", f"대체 절차: {name}")),
             "result": old.get(("조회 대장", f"확인 결과: {name}")), "status": "은행조회 프로그램", "issue": None, "drafts": []}
        entries.append(e)
    for r in ap:                                   # 채무 조회(2026-10-24)
        name = r["party"]
        p = prev.get(("매입채무", name)) or {}
        acct_amt = old.get(("조회 대장", f"회신 금액: {name}"))
        e = {"no": len(entries) + 1, "kind": "매입채무", "target": name, "why": r["why"], "account": " · ".join(r["accounts"]),
             "amount": r["amount"], "amount_basis": "엔진(계정명세서 " + " · ".join(r["accounts"]) + ")", "method": None,
             "sent_at": _parse_date(old.get(("조회 대장", f"발송일: {name}")) or p.get("sent_at")),
             "replied_at": _parse_date(old.get(("조회 대장", f"회신일: {name}")) or p.get("replied_at")),
             "reply_amount": None, "reply_basis": None, "reply_file": None, "difference": None,
             "alternative": old.get(("조회 대장", f"대체 절차: {name}")), "result": old.get(("조회 대장", f"확인 결과: {name}")),
             "status": "발송 전", "issue": p.get("issue"), "drafts": [], "alt_candidates": alts.get(name, [])}
        rp = rep.get(name)
        if rp:
            e["reply_file"] = rp["file"]
            if rp["amount"] is not None:
                e.update(reply_amount=rp["amount"], reply_basis="엔진")
            else:
                e["reply_basis"] = "AI 판독 필요"
        if e["reply_amount"] is None and isinstance(acct_amt, (int, float)):
            e.update(reply_amount=acct_amt, reply_basis="회계사")
        if e["reply_amount"] is not None:
            e["difference"] = common.reader._int(e["reply_amount"] - e["amount"])
            e["status"] = "회신 일치" if abs(e["difference"]) < 1 else "회신 차이"
        elif e["reply_basis"] == "AI 판독 필요":
            e["status"] = "AI 판독 필요"
        elif e["sent_at"]:
            e["status"] = "발송"
        doc = draft / f"3320_조회서_{_safe(name)}.docx"
        mail = draft / f"3320_메일초안_{_safe(name)}.txt"
        others = [x for x in accts.get(name, []) if not (x[0] == "채무" and x[1] in r["accounts"])]
        _docx(doc, company, name, as_of, r["amount"], " · ".join(r["accounts"]), others)
        e["accounts"] = ([{"side": "채무", "account": a, "amount": sum(v for side, aa, v in accts.get(name, []) if side == "채무" and aa == a)}
                          for a in r["accounts"]] + [{"side": x[0], "account": x[1], "amount": x[2]} for x in others])
        _mail(mail, company, name, as_of, r["amount"])
        e["drafts"] = [doc.relative_to(d).as_posix(), mail.relative_to(d).as_posix()]
        entries.append(e)
    bank_csv = draft / "3320_은행조회대상.csv"
    with bank_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["금융기관", "선정 이유", "당기 분개장 거래 행 수", "조회 기준일", "회사"])
        for b in t["banks"]:
            w.writerow([b["target"], " · ".join(b["why"]), b["lines"], as_of, company])

    for e in entries:                              # 조회서 컨트롤(2026-10-26): 사람이 적은 차이 사유 · 대체 절차 상태를 옮기고 상태를 정한다
        nm = e["target"]
        reason, alt = old.get((CONTROL, f"차이 사유: {nm}")), old.get((CONTROL, f"대체 절차 상태: {nm}"))
        reason = str(reason) if _filled(reason) else None
        alt = str(alt).strip() if _filled(alt) else None
        e["control"] = {"state": control_state(e["kind"], e["amount"], e["sent_at"], e["replied_at"], e["reply_amount"],
                                               e["reply_file"], e["result"], reason, alt),
                        "diff_reason": reason, "alt_state": alt}

    new_issues = _raise_issues(d, entries, ctx)

    # 엑셀
    bk = wp.Book(d, "3320", standard="감사기준서 505 외부조회 · 한공회 3320 · 발송 · 회수는 감사인이 직접 한다")
    ws, row = bk.sheet("조회 대장", widths=[6, 10, 16, 26, 16, 13, 13, 16, 16, 30, 30, 14, 44])
    ws.cell(6, 1, f"조회 기준일 {as_of} · 초안 폴더 {draft.relative_to(d).as_posix()} · 대장 사본 _색인/조회.json").font = wp.font(size=9, color=wp.MUTED)
    row = bk.head(ws, row, ["#", "종류", "대상", "선정 이유", "장부 금액", "발송일", "회신일", "회신 금액", "차이", "확인 결과", "대체 절차", "상태",
                            "대체 절차 후보(엔진)"])
    first = row
    ledger_rows: dict[int, int] = {}
    for e in entries:
        nm = e["target"]
        ledger_rows[e["no"]] = row
        bk.put(ws, row, 1, e["no"])
        bk.put(ws, row, 2, e["kind"])
        bk.put(ws, row, 3, nm, flag="신규 거래처" in e["why"])
        bk.text(ws, row, 4, " · ".join(e["why"]), what=f"{e['target']} 조회 대상 선정 이유(받은자료 판독)", basis="_색인/문서목록.json 판독 사실",
                wrap=True, flag=any(w.startswith("이슈") for w in e["why"]))
        bk.put(ws, row, 5, e["amount"], fmt=wp.WON)
        ask(bk, ws, row, 6, f"발송일: {nm}", rule="date", value=_as_date(e["sent_at"]), fmt="yyyy-mm-dd")
        ask(bk, ws, row, 7, f"회신일: {nm}", rule="optional", value=_as_date(e["replied_at"]), fmt="yyyy-mm-dd")
        if e["reply_basis"] == "엔진":
            bk.put(ws, row, 8, e["reply_amount"], fmt=wp.WON)
        elif e["kind"] == "은행":
            bk.put(ws, row, 8, None)
        else:
            ask(bk, ws, row, 8, f"회신 금액: {nm}", rule="optional", value=e["reply_amount"] if e["reply_basis"] == "회계사" else None, fmt=wp.WON)
        bk.put(ws, row, 9, f'=IF(OR(H{row}="",E{row}=""),"",H{row}-E{row})', fmt=wp.WON, flag=e["status"] == "회신 차이")
        ask(bk, ws, row, 10, f"확인 결과: {nm}", value=e["result"])
        ask(bk, ws, row, 11, f"대체 절차: {nm}", rule="optional", value=e["alternative"])
        tail = f" · 이슈 {e['issue']}" if e.get("issue") else ""
        if e["kind"] == "매출채권":
            # 상태는 발송일 · 회신 금액 칸을 보는 수식이다(2026-10-09). 감사인이 발송일을 적고 다시 만들기 전에도 바로 바뀐다
            wait = '"AI 판독 필요"' if e["status"] == "AI 판독 필요" else f'IF(F{row}<>"","발송","발송 전")'
            st = f'=IF(H{row}<>"",IF(ABS(I{row})<1,"회신 일치","회신 차이"),{wait})' + (f'&"{tail}"' if tail else "")
            bk.put(ws, row, 12, st, flag=e["status"] in ("회신 차이", "AI 판독 필요"))
        else:
            bk.put(ws, row, 12, e["status"] + tail, flag=e["status"] in ("회신 차이", "AI 판독 필요"))
        bk.put(ws, row, 13, " / ".join(e.get("alt_candidates") or []), wrap=True,
               flag=any(("부가세가 없음" in x) or ("반대 잔액" in x) for x in e.get("alt_candidates") or []))
        row += 1
    ar_rows = [e for e in entries if e["kind"] == "매출채권"]
    if ar_rows:
        last_ar = first + len(ar_rows) - 1
        bk.put(ws, row, 3, "매출채권 조회 대상 합계", bold=True)
        bk.put(ws, row, 5, f"=SUM(E{first}:E{last_ar})", fmt=wp.WON, bold=True)
        bk.verify("3320 매출채권 조회 대상 장부 금액 합", f"='조회 대장'!E{row}", sum(e["amount"] for e in ar_rows))
        row += 1
        bk.put(ws, row, 3, "매출채권 잔액 대비 조회 비율")
        tot = sum(r["amount"] for r in t["pop"]["rows"]) or 0
        bk.put(ws, row, 5, (sum(e["amount"] for e in ar_rows) / tot) if tot else None, fmt=wp.PCT)
        row += 1
    ws.cell(row, 1, "회신 금액: 엑셀 회신은 엔진이 읽는다. PDF 회신은 AI 판독 필요로 남고, 회계사가 회신 금액 칸에 적으면 다음 make 때 조회.json 에 들어간다").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    ws.cell(row, 1, "은행조회는 은행조회 회신 프로그램이 정본이다. 대상 목록은 초안 폴더의 3320_은행조회대상.csv 이고 결과는 확인 결과 칸에 적는다").font = wp.font(size=9, color=wp.MUTED)
    row += 2
    # 대상별 칸으로 드러나지 않는 필수 절차(2026-11-02 스킬 리뷰). 엔진은 칸만 두고 내용은 회계사가 적는다. 없으면 없음이라고 적는다
    row = bk.section(ws, row, "조회 전체 평가 (감사기준서 505)")
    for lab, what in [("경영진 발송 거부", "경영진이 발송을 거부한 대상과 사유 · 타당성 증거 · 위험 평가 시사점 · 대체 절차, 비합리적이면 지배기구 커뮤니케이션 · 의견 시사점. 없으면 없음(문단 8 · 9)"),
                      ("회신 신뢰성 의문", "간접 전달 · 발신자 의심 등 신뢰성에 의문이 있는 회신과 추가 증거 · 위험 평가 시사점. 없으면 없음(문단 10 · 11)"),
                      ("회신이 꼭 필요한 대상", "대체 절차로 증거를 얻을 수 없어 적극적 조회 회신이 필요한 대상과 회신 여부, 못 받으면 의견 시사점(감사기준서 705). 없으면 없음(문단 13)")]:
        bk.put(ws, row, 3, lab, bold=True)
        bk.put(ws, row, 4, what, wrap=True)
        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=9)
        ask(bk, ws, row, 10, lab)
        ws.row_dimensions[row].height = 45
        row += 1
    bk.conclusion(ws, row, 12)
    _control_sheet(bk, entries, ledger_rows)

    wt, rt = bk.sheet("대상 선정", widths=[18, 18, 10, 12, 12, 30, 44])
    rt = bk.section(wt, rt, f"매출채권 거래처 ({t['pop']['source'] or '거래처별 잔액 자료 없음'})")
    rt = bk.head(wt, rt, ["거래처", "기말 잔액", "신규", "기말 후 입금", "기말 후 취소", "선정 이유", "대체 절차 후보(엔진)"])
    f2 = rt
    sel = {e["target"]: e for e in ar_rows}
    for r in sorted(t["pop"]["rows"], key=lambda r: -r["amount"]):
        bk.put(wt, rt, 1, r["party"], flag=bool(r["new"]))
        bk.put(wt, rt, 2, r["amount"], fmt=wp.WON)
        bk.put(wt, rt, 3, "신규" if r["new"] else "")
        bk.put(wt, rt, 4, r["collected"], fmt=wp.WON)
        bk.put(wt, rt, 5, r["cancelled"], fmt=wp.WON, flag=bool(r["cancelled"]))
        bk.put(wt, rt, 6, " · ".join(sel[r["party"]]["why"]) if r["party"] in sel else "", wrap=True)
        bk.put(wt, rt, 7, " / ".join(alts.get(r["party"], [])) if r["party"] in sel else "", wrap=True)
        rt += 1
    if t["pop"]["rows"]:
        bk.put(wt, rt, 1, "합계", bold=True)
        bk.put(wt, rt, 2, f"=SUM(B{f2}:B{rt - 1})", fmt=wp.WON, bold=True)
        bk.verify("3320 매출채권 거래처 잔액 합", f"='대상 선정'!B{rt}", sum(r["amount"] for r in t["pop"]["rows"]))
        rt += 1
    cf = ctx["defs"].get("confirmations", {})
    wt.cell(rt + 1, 1, f"선정 기준(definitions/workpapers.yaml): 잔액 상위 {cf.get('ar_top_n', 5)}곳 · 전기 분개장에 없던 거래처 · "
                       f"수행중요성({won(ctx['mat']['performance'])}) 이상 · 4000C 표본 · 반대(대변) 잔액. 감사인이 대상을 더하거나 뺄 수 있다").font = wp.font(size=9, color=wp.MUTED)
    rt += 3
    rt = bk.section(wt, rt, f"채무 거래처 조회 대상 ({len(ap)}곳, 계정명세서 {' · '.join(cf.get('ap_accounts', []))})")
    rt = bk.head(wt, rt, ["거래처", "기말 잔액", "계정", "", "", "선정 이유", "대체 절차 후보(엔진)"])
    for r in ap:
        bk.put(wt, rt, 1, r["party"], flag=r["amount"] < 0)
        bk.put(wt, rt, 2, r["amount"], fmt=wp.WON, flag=r["amount"] < 0)
        bk.put(wt, rt, 3, " · ".join(r["accounts"]))
        bk.put(wt, rt, 6, " · ".join(r["why"]), wrap=True)
        bk.put(wt, rt, 7, " / ".join(alts.get(r["party"], [])), wrap=True)
        rt += 1
    if not ap:
        wt.cell(rt, 1, "채무 조회 대상이 없습니다(계정명세서에 외상매입금 · 미지급금 거래처 시트가 없거나 기준에 맞는 거래처가 없음)").font = wp.font(color=wp.MUTED)
        rt += 1
    wt.cell(rt + 1, 1, f"채무 선정 기준: 잔액 상위 {cf.get('ap_top_n', 3)}곳 · 수행중요성 이상 · 반대(차변) 잔액. 매출채권 조회 대상인 거래처는 그 조회서에 채무 줄을 함께 적는다"
            ).font = wp.font(size=9, color=wp.MUTED)

    wb_, rb = bk.sheet("은행조회 대상", widths=[18, 40, 14, 30])
    rb = bk.head(wb_, rb, ["금융기관", "선정 이유", "분개장 거래 행", "비고"])
    for b in t["banks"]:
        bk.put(wb_, rb, 1, b["target"])
        bk.text(wb_, rb, 2, " · ".join(b["why"]), what=f"{b['target']} 은행조회 대상 근거(받은자료 판독)", basis="_색인/문서목록.json 판독 사실",
                wrap=True, flag=b["lines"] == 0)
        bk.put(wb_, rb, 3, b["lines"])
        bk.put(wb_, rb, 4, "분개장 거래 없음. 기중 거래 · 결의만 있는 곳인지 확인" if b["lines"] == 0 else "")
        rb += 1
    wb_.cell(rb + 1, 1, "은행조회 회신 프로그램에 올릴 목록: " + bank_csv.relative_to(d).as_posix()).font = wp.font(size=9, color=wp.MUTED)

    extra = banks.add_sheets(bk, d, ctx, t, old)       # 금융기관 완전성 · 은행 control · 조회 종류(R9 B5)
    out = common.save(bk, force=force)
    data = {"format_version": 1, "updated_at": folder._now(), "as_of": as_of,
            "bank_list_file": bank_csv.relative_to(d).as_posix(), "confirmations": entries}
    common.put_idx(d, "조회.json", data)
    folder.validate_index(d)
    out.update(missing_institutions=extra["completeness"]["missing"], institutions=[e["name"] for e in extra["completeness"]["rows"]])
    out.update(targets=[e["target"] for e in entries], ar_targets=ar_rows, banks=[b["target"] for b in t["banks"]],
               new_issues=new_issues, drafts=sum(len(e["drafts"]) for e in entries) + 1,
               control=control_counts([_control_row(e, {}) for e in entries]))
    return out


# ---------------------------------------------------------------- 조회서 컨트롤
def _filled(v) -> bool:
    return v is not None and not (isinstance(v, str) and not v.strip())


def control_state(kind: str, amount, sent, replied, reply_amount, reply_file, result, reason, alt) -> str:
    """조회서 컨트롤 상태(발송 전 · 발송 · 회신 · 차이 확인 · 대체 절차 · 끝). 엑셀 수식(_control_formula)과 같은 순서로 본다.
    회신 금액이 장부와 같으면 끝. 다르면 차이 사유를 적었거나 대체 절차가 끝났을 때 끝이고, 그 전에는 차이 확인(대체 절차 진행 중이면 대체 절차).
    회신 금액이 없으면 대체 절차 상태 → 은행은 회신과 확인 결과 → 회신(날짜 · 파일) → 발송일 순서."""
    alt = str(alt).strip() if _filled(alt) else ""
    if isinstance(reply_amount, (int, float)) and isinstance(amount, (int, float)):
        if abs(reply_amount - amount) < 1:
            return "끝"
        if _filled(reason) or alt == "끝남":
            return "끝"
        return "대체 절차" if alt == "진행 중" else "차이 확인"
    if alt == "끝남":
        return "끝"
    if alt == "진행 중":
        return "대체 절차"
    got = _filled(replied) or bool(reply_file)
    if kind == "은행" and got and _filled(result):
        return "끝"
    if got:
        return "회신"
    return "발송" if _filled(sent) else "발송 전"


def _control_formula(kind: str, r: int, lr: int, has_file: bool) -> str:
    """control_state 와 같은 판정을 엑셀 수식으로. r 은 컨트롤 시트 행, lr 은 조회 대장 행."""
    led = f"'{LEDGER}'!"
    # 회신 파일이 이미 있으면(엔진이 붙임) 회신일이 비어도 회신이다. 엑셀 TRUE 상수 대신 수식 모양을 나눈다(xlcalc 가 계산하게)
    rest = '"회신"' if has_file else f'IF(E{r}<>"","회신",IF(D{r}<>"","발송","발송 전"))'
    if kind == "은행":
        done = f'{led}J{lr}<>""'
        rest = f'IF({done},"끝",{rest})' if has_file else f'IF(AND(E{r}<>"",{done}),"끝",{rest})'
    no_reply = f'IF(I{r}="끝남","끝",IF(I{r}="진행 중","대체 절차",{rest}))'
    diff = f'IF(ABS(G{r})<1,"끝",IF(OR(H{r}<>"",I{r}="끝남"),"끝",IF(I{r}="진행 중","대체 절차","차이 확인")))'
    return f'=IF(AND(F{r}<>"",G{r}<>""),{diff},{no_reply})'


def control_counts(rows: list[dict]) -> dict:
    """조회서 컨트롤 줄 → 건수(금액 없음). 대상 · 발송 · 회신 · 남은(끝이 아닌) · 차이 미해결(차이 확인) · 상태별 · 구분별."""
    by_kind: dict[str, dict] = {}
    for x in rows:
        k = by_kind.setdefault(x["kind"], {"targets": 0, "remaining": 0})
        k["targets"] += 1
        k["remaining"] += x["state"] != "끝"
    states = {s: sum(1 for x in rows if x["state"] == s) for s in CONTROL_STATES}
    return {"targets": len(rows), "sent": sum(1 for x in rows if x["sent"]), "replied": sum(1 for x in rows if x["replied"]),
            "remaining": sum(1 for x in rows if x["state"] != "끝"), "diff_open": states["차이 확인"],
            "by_state": {k: v for k, v in states.items() if v}, "by_kind": by_kind}


def _control_row(e: dict, inp: dict) -> dict:
    """조회.json 대상 한 줄과 엑셀 기입값 {(시트, 항목): 값} → 컨트롤 줄(금액은 상태 판정에만 쓰고 돌려주지 않는다)."""
    nm = e["target"]
    sent = inp.get((LEDGER, f"발송일: {nm}"), e.get("sent_at"))
    replied = inp.get((LEDGER, f"회신일: {nm}"), e.get("replied_at"))
    amt = e.get("reply_amount") if e.get("reply_basis") == "엔진" else inp.get((LEDGER, f"회신 금액: {nm}"), e.get("reply_amount"))
    result = inp.get((LEDGER, f"확인 결과: {nm}"), e.get("result"))
    c = e.get("control") or {}
    reason = inp.get((CONTROL, f"차이 사유: {nm}"), c.get("diff_reason"))
    alt = inp.get((CONTROL, f"대체 절차 상태: {nm}"), c.get("alt_state"))
    st = control_state(e["kind"], e.get("amount"), sent, replied, amt, e.get("reply_file"), result, reason, alt)
    return {"no": e.get("no"), "kind": KIND_LABEL.get(e["kind"], e["kind"]), "target": nm, "state": st,
            "sent": _filled(sent) or _filled(replied) or bool(e.get("reply_file")) or isinstance(amt, (int, float)),
            "replied": _filled(replied) or bool(e.get("reply_file")) or isinstance(amt, (int, float))}


def control_live(d: Path) -> dict | None:
    """현황용(2026-10-26): _색인/조회.json 대상에 3320 엑셀의 지금 기입값(발송일 · 회신일 · 회신 금액 · 확인 결과 · 차이 사유 ·
    대체 절차 상태)을 얹어 건수를 다시 센다. 담당자가 엑셀을 고치고 make 를 다시 돌리기 전에도 바로 맞는다. 3320 이 없으면 None."""
    d = Path(d)
    conf = (common.idx(d, "조회.json", {}) or {}).get("confirmations", [])
    if not conf:
        return None
    inp = common.old_inputs(d, "3320")
    inp = {k: (v.date().isoformat() if isinstance(v, datetime) else v.isoformat() if isinstance(v, date) else v) for k, v in inp.items()}
    return control_counts([_control_row(e, inp) for e in conf])


def _control_sheet(bk, entries: list[dict], ledger_rows: dict) -> None:
    """3320 「조회서 컨트롤」 시트. 발송일 · 회신일 · 회신 금액 · 차이는 조회 대장 칸을 끌어오고(기입은 조회 대장에서),
    차이 사유 · 대체 절차 상태가 이 시트의 기입란이다. 상태는 수식이라 기입하면 바로 바뀐다."""
    from openpyxl.worksheet.datavalidation import DataValidation

    ws, row = bk.sheet(CONTROL, widths=[6, 10, 20, 12, 12, 16, 16, 30, 14, 48, 12])
    ws.cell(6, 1, "발송일 · 회신일 · 회신 금액은 조회 대장에 적는다. 이 시트에는 차이 사유와 대체 절차 상태(필요 없음 · 진행 중 · 끝남)를 적는다"
            ).font = wp.font(size=9, color=wp.MUTED)
    row = bk.head(ws, row, ["#", "구분", "대상", "발송일", "회신일", "회신 금액", "차이", "차이 사유", "대체 절차 상태",
                            "대체 절차 후보(엔진)", "상태"])
    first = row
    dv = DataValidation(type="list", formula1='"' + ",".join(ALT_STATES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    led = f"'{LEDGER}'!"
    for e in entries:
        nm, lr, c = e["target"], ledger_rows[e["no"]], e.get("control") or {}
        bk.put(ws, row, 1, e["no"])
        bk.put(ws, row, 2, KIND_LABEL.get(e["kind"], e["kind"]))
        bk.put(ws, row, 3, nm)
        for col, src, fmt in ((4, "F", "yyyy-mm-dd"), (5, "G", "yyyy-mm-dd"), (6, "H", wp.WON), (7, "I", wp.WON)):
            bk.put(ws, row, col, f'=IF({led}{src}{lr}="","",{led}{src}{lr})', fmt=fmt)
        ask(bk, ws, row, 8, f"차이 사유: {nm}", rule="optional", value=c.get("diff_reason"))
        cell = ask(bk, ws, row, 9, f"대체 절차 상태: {nm}", rule="optional", value=c.get("alt_state"))
        dv.add(cell.coordinate)
        cands = e.get("alt_candidates") or []
        bk.put(ws, row, 10, " / ".join(cands), wrap=True, flag=any(("부가세가 없음" in x) or ("반대 잔액" in x) for x in cands))
        bk.put(ws, row, 11, _control_formula(e["kind"], row, lr, bool(e.get("reply_file"))),
               flag=c.get("state") in ("차이 확인", "대체 절차"))
        row += 1
    last = row - 1
    row += 1
    if entries:
        rng = f"K{first}:K{last}"
        # 건수는 기입값에 따라 바뀌므로 _검산 에 넣지 않는다(기입할 때마다 검산 불일치로 보이지 않게)
        for lab, f in (("대상", f'=COUNTIF(B{first}:B{last},"*")'), ("발송 전", f'=COUNTIF({rng},"발송 전")'),
                       ("남은 건수(끝이 아닌 것)", f'=COUNTIF({rng},"<>끝")'), ("차이 미해결(차이 확인)", f'=COUNTIF({rng},"차이 확인")'),
                       ("대체 절차 진행 중", f'=COUNTIF({rng},"대체 절차")')):
            bk.put(ws, row, 3, lab, bold=True)
            bk.put(ws, row, 4, f)
            row += 1
    ws.cell(row + 1, 1, "상태: 회신 금액이 장부와 같으면 끝. 다르면 차이 사유를 적거나 대체 절차가 끝나야 끝이고 그 전에는 차이 확인. "
                        "회신 금액이 없으면 대체 절차 상태(진행 중 · 끝남) → 회신(회신일 · 회신 파일, 은행은 확인 결과까지 적으면 끝) → 발송일 순서로 본다"
            ).font = wp.font(size=9, color=wp.MUTED)


def _as_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return v


def _issue_area(e: dict, ctx: dict | None) -> tuple[str, str, list[str]]:
    """회신 차이 이슈의 (영역, 계정, 경영진 주장). 매출채권은 C · 외상매출금 · 실재성과 평가.
    채무 조회는 대상 계정의 시산표 영역(외상매입금 AA · 미지급금 CC)이고 부채라 완전성과 권리와 의무다(2026-11-03 스킬 재검토.
    전에는 채무 회신 차이도 외상매출금 · 4000C 로 올렸다). 영역을 시산표에서 못 찾으면 accounts.yaml 의 영역, 그것도 없으면 AA."""
    if e.get("kind") != "매입채무":
        return "C", "외상매출금", ["E/O", "A/V"]
    names = [x.strip() for x in str(e.get("account") or "").split("·") if x.strip()]
    area = None
    for r in (ctx or {}).get("tb") or []:
        if names and reader._norm(r.get("name")) == reader._norm(names[0]) and r.get("area"):
            area = r["area"]
            break
    if not area and names:
        for a in common.load_def("accounts.yaml").get("accounts", []):
            if a.get("area") and any(re.search(pat, names[0]) for pat in a.get("names") or []):
                area = a["area"]
                break
    return area or "AA", " · ".join(names) or "외상매입금", ["C", "RO"]


def _raise_issues(d: Path, entries: list[dict], ctx: dict | None = None) -> list[int]:
    """회신 차이(엔진 · 회계사 금액)를 이슈 대장에 '절차 예외' 로 올린다. 이미 올린 것은 다시 올리지 않는다.
    대응 조서는 그 대상의 영역 조서다(매출채권 4000C, 채무 4000AA · 4000CC)."""
    data = common.idx(d, "이슈.json", {"format_version": 1, "issues": []}) or {"format_version": 1, "issues": []}
    issues = data["issues"]
    made = []
    for e in entries:
        if e["status"] != "회신 차이" or e.get("issue"):
            continue
        title = f"{e['target']} 조회 회신 금액이 장부와 다름"
        found = next((i for i in issues if i.get("origin_wp") == "3320" and i.get("title") == title), None)
        if found:
            e["issue"] = found["no"]
            continue
        no = max((i["no"] for i in issues), default=0) + 1
        area, account, assertions = _issue_area(e, ctx)
        issues.append({"no": no, "source": "절차 예외", "origin_wp": "3320", "area": area, "account": account,
                       "assertions": assertions, "amount": int(abs(e["difference"])), "title": title,
                       "response_wp": f"4000{area}", "status": "열림", "close_method": None, "conclusion": None})
        e["issue"] = no
        made.append(no)
    if made:
        common.put_idx(d, "이슈.json", data)
    return made
