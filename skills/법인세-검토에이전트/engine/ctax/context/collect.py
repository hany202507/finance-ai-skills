"""신고 건 하나에서 회사 맥락으로 남길 회계사 답을 모은다(`ctax context save`).

모으는 곳:
1. `_색인/조서입력.json`: 조서 노란 칸에 회계사가 적은 값 가운데 catalog.ENGINE 에 있는 것. 기업업무추진비 증빙 종류는 줄마다
   고른 값을 전표.csv 의 거래처로 묶는다.
2. `_색인/맥락확인.json`: 작년 답을 올해 회계사가 확인한 칸(`ctax context confirm`). 확인하지 않은 작년 답은 올해 답으로 남기지 않는다.
3. `_색인/신고건.json`: 회사정보 주업종코드, 주주 · 발행주식수(사업연도마다 한 벌, 주식변동을 해마다 남기려는 것).
4. AR 이슈 회계사 결론(AR 엑셀 결론 칸 · `ctax set issue`)과 서식 제출 선택(`ctax set form`). 다음 해 엔진 기본값으로 쓰지 않고 보여 주기만 한다.

금액을 계산하지 않는다. 회계사가 적은 값을 출처(사업연도 · 누가 · 언제 · 어느 파일)와 함께 옮긴다.

내년메모(10-30 설계안 5.3절): `add_next_year_memo` 가 클로징 마감 설명 next_year[] 나 `context add --kind 내년메모` 의 글을
`회사|내년메모/<제목>` 으로 적고(AI 가 쓰면 confirmed false), `last_year_memos` 가 다음 해 계획서(ctax plan)에 「작년 메모」 후보로 돌려준다.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..case import Case
from . import apply, catalog, store

ACCOUNTANT = "회계사"


def _json(case: Case, name: str) -> dict:
    try:
        return case.read_json(name) if case.has(name) else {}
    except ValueError:
        return {}


def _partners(case: Case) -> dict[str, str]:
    """줄 열쇠(일자|전표|계정|금액) → 거래처. 같은 열쇠의 둘째 줄부터는 #2 · #3 을 붙인다(wp.model.line_keys 와 같은 규칙)."""
    ledger = _json(case, "장부.json")
    journal = case.root / (ledger.get("journal_csv") or "_색인/전표.csv")
    if not journal.exists():
        return {}
    from ..wp.books import read_journal

    out, seen = {}, Counter()
    for ln in read_journal(journal):
        base = f"{ln.date}|{ln.no}|{ln.account}|{ln.amount}"
        seen[base] += 1
        out[base if seen[base] == 1 else f"{base}#{seen[base]}"] = str(ln.partner or "").strip()
    return out


def _entry(case: Case, value, by: str, at: str, frm: str, note: str = "") -> dict:
    return {"fy": case.fy, "value": value, "by": by, "at": at, "from": frm, "case": case.root.name, "note": note}


def gather(case: Case) -> list[dict]:
    """[{id, kind, paper, key, target, entry}] 이 신고 건의 사업연도 답."""
    out: list[dict] = []
    cells = [c for c in (_json(case, "조서입력.json").get("cells") or []) if c.get("paper") and c.get("key")]
    seen = set()
    evidence: dict[str, list[dict]] = {}
    partners = None
    for c in cells:
        paper, key = str(c["paper"]), str(c["key"])
        if paper == catalog.EVIDENCE_PAPER and key.startswith(f"{catalog.EVIDENCE_PICK}/"):
            partners = _partners(case) if partners is None else partners
            who = partners.get(key[len(catalog.EVIDENCE_PICK) + 1:], "")
            if who and str(c.get("value") or "").strip():
                evidence.setdefault(who, []).append(c)
            continue
        hit = catalog.engine_kind(paper, key)
        if hit is None or str(c.get("value") or "").strip() == "":
            continue
        fid = catalog.fact_id(paper, key)
        seen.add(fid)
        out.append({"id": fid, "kind": hit[0], "paper": paper, "key": key, "target": hit[1],
                    "entry": _entry(case, c["value"], ACCOUNTANT, str(c.get("at") or ""), str(c.get("from") or "조서.xlsx"))})
    for who, rows in sorted(evidence.items()):
        count = Counter(str(r["value"]).strip() for r in rows)
        value = next(iter(count)) if len(count) == 1 else "섞임: " + " · ".join(f"{k} {n}건" for k, n in count.most_common())
        key = f"{catalog.EVIDENCE_PREFIX}{who}"
        out.append({"id": catalog.fact_id(catalog.EVIDENCE_PAPER, key), "kind": catalog.EVIDENCE_KIND,
                    "paper": catalog.EVIDENCE_PAPER, "key": key, "target": who,
                    "entry": _entry(case, value, ACCOUNTANT, max(str(r.get("at") or "") for r in rows),
                                    str(rows[0].get("from") or "조서.xlsx"), f"줄 {len(rows)}개")})
    for fid, row in apply.read_confirm(case).items():
        paper, _, key = fid.partition("|")
        hit = catalog.engine_kind(paper, key)
        if hit is None or fid in seen:
            continue
        out.append({"id": fid, "kind": hit[0], "paper": paper, "key": key, "target": hit[1],
                    "entry": _entry(case, row.get("value"), str(row.get("by") or ACCOUNTANT), str(row.get("at") or ""),
                                    "작년 답 확인", f"{row.get('fy', '')} 사업연도 답을 확인")})
    out += _company(case)
    return out


def _company(case: Case) -> list[dict]:
    info = case.info()
    at = str((info.get("steps") or {}).get("read", {}).get("at") or "")
    out = []

    def add(kind: str, target: str, value, by: str, frm: str, at_: str = "", note: str = "") -> None:
        key = f"{kind}/{target}" if target else kind
        out.append({"id": catalog.fact_id(catalog.COMPANY, key), "kind": kind, "paper": catalog.COMPANY, "key": key,
                    "target": target, "entry": _entry(case, value, by, at_ or at, frm, note)})

    code = str((info.get("회사정보") or {}).get("주업종코드") or "").strip()
    prior_co = (_json(case, "전기.json").get("company") or {})
    if code:
        add("업종코드", "", code, "신고건.json", "회사정보")
    elif str(prior_co.get("industry_code") or "").strip():      # 회사정보가 없으면 전기 신고서에서 읽은 업종코드(그 사업연도 값으로 둔다)
        add("업종코드", "", str(prior_co["industry_code"]).strip(), "전기 신고서", "전기.json",
            note=f"전기({_json(case, '전기.json').get('fy') or ''}) 신고서에서 읽음")
    for s in info.get("주주") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("성명") or s.get("법인명") or "").strip()
        if name:
            add("주주", name, f"{int(s.get('주식수') or 0):,}주" + (f" ({s['구분']})" if s.get("구분") else ""), "신고건.json", "주주")
    if info.get("발행주식수"):
        add("발행주식수", "", f"{int(info['발행주식수']):,}주", "신고건.json", "발행주식수")
    from ..choice import store as picks

    chosen = picks.read(case.root)
    ar = _json(case, "AR.json")
    issues = [dict(i) for i in ar.get("issues") or [] if isinstance(i, dict)]
    picks.merge_conclusions(issues, chosen)
    for i in issues:
        c = i.get("conclusion") or {}
        if str(c.get("text") or "").strip():
            add("이슈 결론", str(i.get("title") or i.get("no")), str(c["text"]).strip(), str(c.get("by") or ACCOUNTANT),
                "AR 결론 칸" if c.get("from") != picks.ORIGIN else "ctax set issue", str(c.get("at") or ""),
                f"이슈 {i.get('no')} · {i.get('key') or ''}")
    for code_, row in chosen.get("form", {}).items():
        add("서식 제출", code_, row.get("value"), str(row.get("by") or ""), "ctax set form", str(row.get("at") or ""),
            str(row.get("note") or ""))
    return out


def save(case_dir: str | Path) -> dict:
    """신고 건의 답을 맥락.json 에 넣는다. {"path", "새로", "바뀜", "같음", "rows"}."""
    case = Case(case_dir)
    if not case.fy:
        raise ValueError(f"사업연도를 폴더 이름에서 읽지 못했습니다: {case.root.name}(「2025 법인세」 꼴이어야 합니다)")
    data = store.read(case.root)
    counts = Counter()
    rows = gather(case)
    for r in rows:
        _fact, how = store.put(data, r["id"], kind=r["kind"], paper=r["paper"], key=r["key"], target=r["target"],
                               entry=r["entry"])
        counts[how] += 1
    p = store.write(case.root, data)
    return {"path": str(p), **{k: counts.get(k, 0) for k in ("새로", "바뀜", "같음")}, "rows": len(rows)}


def add_next_year_memo(folder: str | Path, fy: str, title: str, text: str, *, by: str = "AI", basis: list[str] | None = None,
                       case_name: str = "", at: str = "", frm: str = "ctax context add", note: str = "") -> tuple[dict, str]:
    """내년메모 한 줄을 맥락.json 에 넣는다. (사실, 「새로」 · 「바뀜」 · 「같음」). by 가 AI 면 confirmed false, 사람이면 true."""
    from datetime import datetime

    target = str(title or "").strip()
    key = f"{catalog.NEXT_YEAR}/{target}"
    entry = {"fy": str(fy), "value": str(text or "").strip(), "by": by, "at": at or datetime.now().isoformat(timespec="seconds"),
             "from": frm, "case": case_name, "note": note or (" · ".join(basis) if basis else ""), "confirmed": by != catalog.AI}
    data = store.read(folder)
    fact, how = store.put(data, catalog.fact_id(catalog.COMPANY, key), kind=catalog.NEXT_YEAR, paper=catalog.COMPANY, key=key,
                          target=target, entry=entry)
    store.write(folder, data)
    return fact, how


def last_year_memos(folder: str | Path, fy: str) -> list[dict]:
    """사업연도 fy 보다 앞선 해에 적힌 내년메모 사실 목록(제목 차례). 다음 해 계획서의 「작년 메모」 후보다."""
    data = store.read(folder)
    out = []
    for fact in data["facts"].values():
        if fact.get("kind") != catalog.NEXT_YEAR:
            continue
        if store.before(fact, fy) is None:
            continue
        out.append(fact)
    return sorted(out, key=lambda f: str(f.get("target") or ""))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
