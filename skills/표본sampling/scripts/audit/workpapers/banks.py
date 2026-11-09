"""3320 금융기관 완전성 · 은행 control sheet · 조회 종류 · 채권채무 거래처별 계정(R9 묶음 B5, 2026-10-06).

샘플 진단 §6.2(샘플 G): 사람 조서는 전기 금융기관 목록 · 잔액증명 · 장부를 견줘 빠진 금융기관을 찾고(완전성), 금융기관마다
금융상품 · 계좌 · 이율 · 만기 · 인출제한과 대출 약정한도 · 담보를 한 장(control sheet)에 모은다. 조회 종류도 은행 말고 보험 ·
증권 · 비은행 여신 · 변호사 · 타처보관재고가 있고, 채권채무 조회서 한 장에 거래처의 채권 · 채무 계정을 모두 적는다.
엔진은 파일에서 읽은 사실만 쓰고, 조회 여부 · 처리 · 인출제한 확인은 감사인 기입란이다.

  institutions(d, ctx, banks)   금융기관마다 원천(전기 목록 · 잔액증명 · 조회회신 · 분개장 · 계정명세서 · 의사록 · 약정서)과 판정
  control_rows(d)               계정명세서 예금 · 차입금 시트와 잔액증명 · 약정서 PDF 로 control sheet 줄
  kinds(d, ctx)                 조회 종류마다 엔진이 찾은 근거
  party_accounts(d)             거래처 → [(구분, 계정, 금액)] (계정명세서 거래처 시트, 채권채무 조회서용)
  add_sheets(bk, d, ctx, t)     3320 Book 에 「금융기관 완전성」 · 「은행 control」 · 「조회 종류」 시트
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import figures, reader, wp
from . import common
from .common import ask

COMPLETE = "잔액증명 있음"
MISSING = "잔액증명 없음"
COLS = ["전기 목록", "잔액증명", "조회회신", "분개장", "계정명세서", "의사록 · 약정서", "그 밖의 받은자료"]
CLAIM = {"채권": ["외상매출금", "매출채권", "받을어음", "미수금", "선급금", "대여금", "미수수익"],
         "채무": ["외상매입금", "매입채무", "지급어음", "미지급금", "선수금", "예수보증금", "미지급비용"]}


def _defs() -> dict:
    return common.load_def("confirm_kinds.yaml")


def _bank_keys(ctx: dict) -> list[str]:
    return (ctx["defs"].get("confirmations") or {}).get("bank_name_keys", ["은행"])


def _pattern(keys: list[str]) -> re.Pattern:
    return re.compile(r"([가-힣A-Za-z]{1,12}(?:" + "|".join(map(re.escape, keys)) + r"))")


def _names(text: str, pat: re.Pattern, keys: list[str]) -> list[str]:
    out = []
    for m in pat.finditer(text or ""):
        n = m.group(1)
        if n in keys or "거래은행" in n:
            continue
        out.append(n)
    return out


def _prior_list(d: Path) -> tuple[set[str], str | None]:
    """전기 금융기관 목록: 작년 감사 폴더 _색인/조회.json 의 은행 대상. 없으면 (빈 집합, None)."""
    from .. import prior

    try:
        prev = prior.prior_engagement(d)
    except Exception:  # noqa: BLE001
        prev = None
    if prev is None:
        return set(), None
    p = prev / "_색인" / "조회.json"
    if not p.exists():
        return set(), f"작년 감사 폴더({prev.name})에 조회.json 이 없음"
    data = json.loads(p.read_text(encoding="utf-8"))
    return {e["target"] for e in data.get("confirmations", []) if e.get("kind") == "은행"}, prior._rel(d, p)


def institutions(d: Path, ctx: dict, banks: list[dict]) -> dict:
    """금융기관 완전성 표. banks 는 confirm.targets 의 은행 대상(분개장 · 계정명세서 · 파일 이름 · 사실 문장에서 모은 것)."""
    d = Path(d)
    keys = _bank_keys(ctx)
    pat = _pattern(keys)
    kinds = _defs()["source_kinds"]
    rows: dict[str, dict] = {}

    def add(name: str, col: str, why: str):
        e = rows.setdefault(name, {"name": name, **{c: [] for c in COLS}})
        if why not in e[col]:
            e[col].append(why)

    prior_names, prior_src = _prior_list(d)
    for n in prior_names:
        add(n, "전기 목록", prior_src)
    for b in banks:
        for w in b["why"]:
            if w.startswith("계정명세서"):
                add(b["target"], "계정명세서", w.replace("계정명세서 ", ""))
            elif w == "당기 분개장 거래":
                add(b["target"], "분개장", f"거래 {b['lines']}행")
            elif w.startswith("영구조서"):
                add(b["target"], "전기 목록", w)
    docs = common.idx(d, "문서목록.json", {"files": []})
    for f in docs["files"]:
        if f.get("role") != "received":
            continue
        kind = f.get("kind") or ""
        col = ("잔액증명" if kind in kinds["잔액증명"] else "의사록 · 약정서" if kind in kinds["의사록 · 약정서"]
               else "조회회신" if f["path"].startswith("00 받은자료/조회회신/") else None)
        if col is None and kind in ("계정명세서", reader.JOURNAL):
            continue                       # 계정명세서 · 분개장은 위(confirm.targets)에서 시트 · 거래 단위로 봤다
        name = Path(f["path"]).name
        for n in _names(Path(f["path"]).stem, pat, keys):
            add(n, col or "그 밖의 받은자료", name)
        for x in f.get("facts") or []:
            ai = x.get("basis") == "AI" and not f.get("confirmed")
            for n in _names(x.get("text", ""), pat, keys):
                add(n, col or "그 밖의 받은자료", name + (" (AI 판독, 확인 전)" if ai else ""))
    out = []
    for e in sorted(rows.values(), key=lambda e: e["name"]):
        has = bool(e["잔액증명"] or e["조회회신"])
        e["verdict"] = COMPLETE if has else MISSING
        e["sources"] = sum(1 for c in COLS if e[c])
        out.append(e)
    return {"rows": out, "prior_source": prior_src, "missing": [e["name"] for e in out if e["verdict"] == MISSING]}


# ---------------------------------------------------------------- control sheet
HEAD = {"bank": ("거래처", "은행", "금융기관", "대주", "차입처"), "kind": ("계좌구분", "구분", "상품", "종류", "과목"),
        "amount": ("기말잔액", "잔액", "금액", "차입금액"), "rate": ("이율", "금리", "이자율"), "due": ("만기", "만기일", "상환기일"),
        "limit": ("인출제한", "사용제한", "담보"), "start": ("실행일", "기표일", "차입일"), "line": ("약정액", "한도", "약정한도")}


def _sheet_rows(ws) -> list[dict]:
    rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    for hi, r in enumerate(rows[:10]):
        hs = [reader._norm(x) for x in r]
        col = {}
        for k, names in HEAD.items():
            j = next((i for i, h in enumerate(hs) if h in names), None)
            if j is None:
                j = next((i for i, h in enumerate(hs) if h and any(n in h for n in names) and i not in col.values()), None)
            if j is not None:
                col[k] = j
        if "bank" not in col or "amount" not in col:
            continue
        out = []
        for row in rows[hi + 1:]:
            name = reader._cell(row, col["bank"])
            v = reader._num(reader._cell(row, col["amount"]))
            if name in (None, "") or v is None or reader._is_total_row(row):
                continue
            g = lambda k: reader._cell(row, col[k]) if k in col else None  # noqa: E731
            out.append({"bank": str(name).strip(), "kind": g("kind"), "amount": reader._int(v), "rate": g("rate"), "due": g("due"),
                        "limit": g("limit"), "start": g("start"), "line": g("line")})
        return out
    return []


def control_rows(d: Path, ctx: dict) -> dict:
    """계정명세서 예금 · 차입금 시트 줄에 잔액증명 · 약정서 PDF 값을 붙인다."""
    from ..analysis import pdfread

    d = Path(d)
    dep_keys = (ctx["defs"].get("confirmations") or {}).get("bank_schedule_sheets", [])
    loan_keys = _defs()["loan_sheets"]
    rows, src = [], []
    for rel in figures.received(d, reader.SCHEDULE):
        if Path(rel).suffix.lower() not in reader.EXCEL:
            continue
        wb = reader._open(d / rel)
        try:
            for ws in wb.worksheets:
                t = reader._norm(ws.title)
                is_loan = any(k in t for k in loan_keys)
                is_dep = not is_loan and any(k in t for k in dep_keys)
                if not (is_loan or is_dep):
                    continue
                got = _sheet_rows(ws)
                for x in got:
                    x.update(type="차입" if is_loan else "예금", sheet=ws.title, wp="4000BBDD" if is_loan else "4000A", path=rel)
                rows += got
                if got:
                    src.append(f"{rel} '{ws.title}'")
        finally:
            wb.close()
    keys = _bank_keys(ctx)
    pat = _pattern(keys)
    conf: dict[str, dict] = {}
    for rel in figures.received(d, "금융기관 잔액증명·거래내역"):
        if not rel.lower().endswith(".pdf"):
            continue
        names = _names(Path(rel).stem, pat, keys)
        try:
            r = pdfread.bank(d / rel)
        except Exception:  # noqa: BLE001
            continue
        if r.get("source") == "ocr":          # OCR(kordoc) 값은 확인 전이라 조서 숫자로 쓰지 않는다(2026-10-18)
            r["values"] = {}
        for n in names[:1]:
            conf[n] = {"예금": r["values"].get("예금"), "대출금": r["values"].get("대출금"), "file": Path(rel).name, "path": rel}
    loans: dict[str, dict] = {}
    for rel in figures.received(d, "차입·담보·보증 약정"):
        if not rel.lower().endswith(".pdf"):
            continue
        try:
            r = pdfread.loan(d / rel)
        except Exception:  # noqa: BLE001
            continue
        if r.get("source") == "ocr":
            r["values"], r["rates"] = {}, []
        n = r.get("lender") or next(iter(_names(Path(rel).stem, pat, keys)), None)
        if n:
            loans[n] = {"limit": r["values"].get("약정합계"), "rates": r["rates"], "file": Path(rel).name}
    return {"rows": rows, "sources": src, "confirmations": conf, "loans": loans}


# ---------------------------------------------------------------- 조회 종류
def kinds(d: Path, ctx: dict, journal_lines: list) -> list[dict]:
    d = Path(d)
    spec = _defs()["kinds"]
    tb = ctx["tb"]
    docs = common.idx(d, "문서목록.json", {"files": []})["files"]
    out = []
    for k in spec:
        ev, targets = [], []
        parties: dict[str, int] = {}
        for x in journal_lines:
            if x.party and any(w in x.party for w in k.get("party_keys", [])):
                parties[x.party] = parties.get(x.party, 0) + 1
        for p, n in sorted(parties.items(), key=lambda kv: -kv[1]):
            ev.append(f"분개장 거래처 '{p}' {n}행")
            targets.append(p)
        for r in tb:
            if any(w in reader._norm(r["name"]) for w in k.get("account_keys", [])):
                ev.append(f"시산표 계정 {r['code']} {r['name']} {common.won(r['disp'])}")
        for f in docs:
            if f.get("role") != "received":
                continue
            for x in f.get("facts") or []:
                if any(w in x.get("text", "") for w in k.get("fact_keys", [])):
                    ev.append(f"{Path(f['path']).name}: {common.short(x['text'], 40)}" + (" (AI 판독, 확인 전)" if x.get("basis") == "AI" and not f.get("confirmed") else ""))
                    break
        out.append({"kind": k["kind"], "evidence": ev, "targets": targets})
    return out


# ---------------------------------------------------------------- 채권채무 거래처별 계정
def party_accounts(d: Path) -> dict[str, list[tuple]]:
    """계정명세서의 거래처 시트(외상매출금 · 미수금 · 외상매입금 · 미지급금 …)에서 거래처 → [(채권 · 채무, 계정, 금액)]."""
    d = Path(d)
    out: dict[str, list[tuple]] = {}
    for rel in figures.received(d, reader.SCHEDULE):
        if Path(rel).suffix.lower() not in reader.EXCEL:
            continue
        for sh in reader.schedule_sheets(d / rel):
            t = reader._norm(sh["sheet"])
            side = next((s for s, names in CLAIM.items() for n in names if n in t), None)
            if side is None:
                continue
            acct = next(n for n in CLAIM[side] if n in t)
            for name, v in sh["rows"]:
                out.setdefault(str(name).strip(), []).append((side, acct, reader._int(v)))
    return out


# ---------------------------------------------------------------- 시트
def add_sheets(bk: wp.Book, d: Path, ctx: dict, t: dict, old: dict) -> dict:
    """3320 Book 에 시트 셋을 더하고 {"completeness": ..., "control": ..., "kinds": ...} 를 돌려준다."""
    from . import lead

    comp = institutions(d, ctx, t["banks"])
    ws, row = bk.sheet("금융기관 완전성", widths=[16] + [20] * len(COLS) + [14, 34])
    ws.cell(6, 1, "전기 금융기관 목록(작년 감사 폴더 조회.json · 영구조서 180) · 잔액증명 · 조회회신 · 당기 분개장 · 계정명세서 · 의사록 · 약정서를 "
                  "견줘 잔액증명(또는 조회 회신)이 없는 금융기관을 표시한다. 잔액이 0 이거나 해지한 계좌도 조회 대상인지 감사인이 정한다"
            ).font = wp.font(size=9, color=wp.MUTED)
    row = bk.section(ws, row, f"금융기관 {len(comp['rows'])}곳 · 잔액증명 없음 {len(comp['missing'])}곳"
                     + ("" if comp["prior_source"] else " (전기 금융기관 목록 원천 없음: 작년 감사 폴더가 없음)"))
    row = bk.head(ws, row, ["금융기관"] + COLS + ["판정", "처리(조회서 발송 · 해지 확인 · 신용정보 조회 대사)"])
    for e in comp["rows"]:
        bk.put(ws, row, 1, e["name"], bold=True, flag=e["verdict"] == MISSING)
        for i, c in enumerate(COLS, 2):
            bk.text(ws, row, i, "; ".join(e[c]) or "", what=f"{e['name']} {c} 근거(받은자료 판독)", basis="_색인/문서목록.json 판독 사실", wrap=True)
        bk.put(ws, row, len(COLS) + 2, e["verdict"], flag=e["verdict"] == MISSING)
        lab = f"처리: {e['name']}"
        ask(bk, ws, row, len(COLS) + 3, lab, rule="required" if e["verdict"] == MISSING else "optional", value=old.get(("금융기관 완전성", lab)))
        ws.row_dimensions[row].height = 30
        row += 1
    bk.verify("3320 잔액증명 없는 금융기관 수", f"=COUNTIF('금융기관 완전성'!{chr(ord('A') + len(COLS) + 1)}:{chr(ord('A') + len(COLS) + 1)},\"{MISSING}\")",
              len(comp["missing"]))
    row += 1
    ws.cell(row, 1, "신용정보조회서(금융거래 확인서)를 받았으면 그 금융기관 목록과도 대사해 처리 칸에 적는다").font = wp.font(size=9, color=wp.MUTED)

    ctl = control_rows(d, ctx)
    wc, rc = bk.sheet("은행 control", widths=[14, 8, 22, 18, 18, 8, 12, 14, 18, 30, 10, 26])
    wc.cell(6, 1, "계정명세서(" + (" · ".join(ctl["sources"]) or "예금 · 차입금 시트 없음") + ") 와 잔액증명 · 약정서 PDF 를 엔진이 읽어 모았다. "
                  "빈 칸은 자료에 없는 것이다. 회신과 대사한 결과는 확인 칸에 적는다").font = wp.font(size=9, color=wp.MUTED)
    rc = bk.head(wc, rc, ["금융기관", "구분", "상품 · 계좌", "장부 잔액(명세서)", "잔액증명", "이율", "만기", "실행일",
                          "약정한도(약정서)", "인출제한 · 담보", "관련 조서", "회신 대사 확인"])
    for x in ctl["rows"]:
        cf = ctl["confirmations"].get(x["bank"]) or {}
        ln = ctl["loans"].get(x["bank"]) or {}
        bk.put(wc, rc, 1, x["bank"], bold=True)
        bk.put(wc, rc, 2, x["type"])
        bk.put(wc, rc, 3, x["kind"], wrap=True)
        bk.put(wc, rc, 4, x["amount"], wp.WON)
        conf_v = cf.get("예금") if x["type"] == "예금" else cf.get("대출금")
        bk.put(wc, rc, 5, conf_v if cf else "잔액증명 없음", wp.WON if cf else None, flag=not cf)
        bk.put(wc, rc, 6, x["rate"], "0.00%" if isinstance(x["rate"], (int, float)) else None)
        bk.put(wc, rc, 7, x["due"])
        bk.put(wc, rc, 8, x["start"])
        bk.put(wc, rc, 9, ln.get("limit") if x["type"] == "차입" else None, wp.WON)
        bk.put(wc, rc, 10, x["limit"], wrap=True)
        bk.put(wc, rc, 11, x["wp"])
        lab = f"회신 대사: {x['bank']} {x['type']} {x['kind'] or ''}".strip()
        ask(bk, wc, rc, 12, lab, rule="optional", value=old.get(("은행 control", lab)))
        rc += 1
    if not ctl["rows"]:
        bk.put(wc, rc, 1, "계정명세서에 예금 · 차입금 시트가 없습니다. 금융기관별 예금 · 차입 명세를 받아 주십시오", wrap=True, flag=True)
        wc.merge_cells(start_row=rc, start_column=1, end_row=rc, end_column=12)
        rc += 1
    rc += 1
    wc.cell(rc, 1, "잔액증명 칸: 예금 줄은 잔액증명 예금 합계, 차입 줄은 대출금 합계(금융기관 단위)다. 계좌 단위 대사는 은행조회 회신으로 한다"
            ).font = wp.font(size=9, color=wp.MUTED)

    ks = kinds(d, ctx, lead._journals(ctx)["cur"])
    wk, rk = bk.sheet("조회 종류", widths=[16, 60, 30, 14, 34])
    wk.cell(6, 1, "은행 · 매출채권 말고 필요한 조회 종류. 엔진은 자료에서 흔적만 찾는다(definitions/confirm_kinds.yaml). 조회할지는 감사인이 정한다"
            ).font = wp.font(size=9, color=wp.MUTED)
    rk = bk.head(wk, rk, ["조회 종류", "엔진이 찾은 근거", "후보 대상", "조회 여부", "대상 · 비고"])
    bk.put(wk, rk, 1, "은행(등기 · 전자)", bold=True)
    bk.put(wk, rk, 2, f"은행조회 대상 {len(t['banks'])}곳(조회 대장 · 은행조회 대상 시트)", wrap=True)
    bk.put(wk, rk, 3, ", ".join(b["target"] for b in t["banks"]), wrap=True)
    bk.put(wk, rk, 4, "예" if t["banks"] else "")
    rk += 1
    bk.put(wk, rk, 1, "채권채무", bold=True)
    bk.put(wk, rk, 2, f"매출채권 조회 대상 {len(t['ar'])}곳. 조회서 한 장에 거래처의 채권 · 채무 계정을 모두 적는다", wrap=True)
    bk.put(wk, rk, 3, ", ".join(x["party"] for x in t["ar"][:10]) + (" …" if len(t["ar"]) > 10 else ""), wrap=True)
    bk.put(wk, rk, 4, "예" if t["ar"] else "")
    rk += 1
    for k in ks:
        bk.put(wk, rk, 1, k["kind"], bold=True)
        bk.put(wk, rk, 2, "\n".join(k["evidence"][:6]) or "자료에서 흔적을 찾지 못함", wrap=True, flag=bool(k["evidence"]))
        bk.put(wk, rk, 3, ", ".join(k["targets"][:6]), wrap=True)
        lab = f"조회 여부: {k['kind']}"
        ask(bk, wk, rk, 4, lab, rule="yesno" if k["evidence"] else "optional", value=old.get(("조회 종류", lab)))
        lab2 = f"대상 · 비고: {k['kind']}"
        ask(bk, wk, rk, 5, lab2, rule="optional", value=old.get(("조회 종류", lab2)))
        wk.row_dimensions[rk].height = 15 * max(1, min(6, len(k["evidence"])))
        rk += 1
    return {"completeness": comp, "control": ctl, "kinds": ks}
