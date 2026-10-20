"""공시 꼴 재무제표 양식 (2026-10-08).

설계: `docs/specs/2026-10-08-감사-공시재무제표-WTB-design.md`

8100B 「재무제표」 시트는 표시과목을 한 줄씩 늘어놓는다. 공시 재무제표에 필요한 유동 · 비유동 구분, 소계와 합계 줄,
과목 순서, 차감 짝이 없다. 이 모듈은 **양식을 추정하지 않고 자료에서 가져온다.**

양식 출처는 이 순서다(과목마다 어디서 왔는지 `source` 에 남긴다).
  1 받은자료의 공시 꼴 재무제표(회사가 실제로 공시한 꼴. 당기 · 전기 비교식이면 전기 열까지 온다)
  2 전기 재무제표
  3 둘 다 없으면 양식을 세우지 못한다(`rows` 가 비고 `basis` 에 까닭을 적는다). 엔진이 과목 순서를 지어내지 않는다.

  layout(d, accounts)  {"rows": [...], "basis", "source_path", "unmatched_lines", "unmatched_accounts", "unmatched_zero",
                        "coa", "rolled"}

rows 한 줄
  {"kind": section|h1|h2|acct|total, "label", "level", "codes": [계정코드], "contra_of", "prior", "prior_signed",
   "negative", "rolled", "source"}
  codes 는 그 과목으로 묶이는 당기 계정의 코드다. 8100B 공시 시트가 이 코드로 계정별 시트를 SUMIF 한다.
  prior_signed 는 시산표 부호 쪽으로 맞춘 공시 전기 금액이다(차감 짝 · 결손금은 음수).

계정과목표(`LINK_CD`)가 받은자료에 있으면 자리가 없는 하위 계정을 상위 계정의 과목에 묶는다(2026-10-09).
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import figures, reader

CURRENT_FS = "회사제시 재무제표·시산표"       # folder_standard.yaml 의 받은자료 종류 이름


def _codenum(code) -> int:
    try:
        return int(str(code))
    except (TypeError, ValueError):
        return 0


def _norm(s: str) -> str:
    return re.sub(r"[\s·()\[\]]", "", str(s or ""))


def _disclosure_like(path: Path) -> int:
    """공시 꼴 점수. 더존 시산표에도 「계정과목」 칸이 있어 재무제표로 읽힌다. 그것을 양식으로 쓰면 안 된다.

    시산표로 읽히는 파일은 0 점이다. 나머지는 묶음 줄(Ⅰ · (1))과 합계 줄(자산총계 등) 수를 센다."""
    if reader.tb_table(path):
        return 0
    got = reader.fs_layout(path)
    if not got:
        return 0
    n = 0
    for sheet in got["sheets"]:
        n += sum(1 for r in sheet["rows"] if r["kind"] in ("h1", "h2", "total"))
    return n


def _source(d: Path) -> tuple[Path | None, str]:
    """(공시 꼴 재무제표 파일, 어디서 왔는지). 회사제시를 먼저 보고, 없으면 전기 재무제표를 본다.
    같은 종류에 여러 파일이 있으면 공시 꼴 점수가 가장 높은 것을 쓴다."""
    d = Path(d)
    for kind, label in ((CURRENT_FS, "회사제시 재무제표"), (figures.PRIOR_FS, "전기 재무제표")):
        best, score = None, 0
        for rel in figures.received(d, kind):
            p = d / rel
            if p.suffix.lower() not in reader.EXCEL:
                continue
            n = _disclosure_like(p)
            if n > score:
                best, score = (p, rel), n
        if best:
            return best[0], f"{label} {best[1]}"
    return None, ""


def _coa(d: Path) -> tuple[dict | None, str | None]:
    """받은자료 가운데 계정과목표로 읽히는 첫 파일. (판독 결과, 상대 경로). figures.coa 와 같다."""
    return figures.coa(d)


def _negative(stmt: str, kind: str, label: str, contra_of) -> bool:
    """공시 재무제표가 크기로 적었지만 자산 · 자본을 줄이는 줄. 차감 짝(대손충당금 · 감가상각누계액)과 자본의 차감 줄
    (결손금 · 자기주식). 시산표에서 묶은 당기 금액은 부호가 있으므로(대손충당금은 음수) 공시 금액도 같은 부호로 맞춰야
    증감이 맞는다. 손익계산서의 「처분손실」 은 비용 과목이라 뒤집지 않는다."""
    if stmt != "bs" or kind not in ("acct", "h1", "h2"):
        return False
    if contra_of:
        return True
    return "잉여금" not in label and any(w in label for w in reader.EQUITY_DEBIT)


def _signed(v, neg: bool):
    return None if v is None else (-abs(v) if neg else v)


def layout(d: Path, accounts: list[dict], lines: list[dict] | None = None) -> dict:
    """공시 양식에 당기 계정을 붙인다.

    계정 → 과목 대응은 분석이 정한 표시과목(`line`)을 쓴다. 양식의 과목 이름이 표시과목과 다를 수 있으므로
    분석 결과의 `lines[].prior_labels`(전기 재무제표 과목 이름 맞춤)로도 찾는다. 새 대응 규칙을 만들지 않는다.

    그래도 자리가 없는 하위 계정은 회사 계정과목표의 상위 계정 연결(`LINK_CD`)을 따라 올라가 상위 계정의 과목에 묶는다
    (2026-10-09). 보통예금 10301 · 외화예금 10302 → 제예금 10300. 묶은 것은 줄마다 `rolled` 에 남긴다."""
    d = Path(d)
    path, basis = _source(d)
    if path is None:
        return {"rows": [], "basis": "공시 꼴 재무제표(회사제시 또는 전기)가 받은자료에 없어 공시 양식을 세우지 못했습니다",
                "source_path": None, "unmatched_lines": [], "unmatched_accounts": [], "unmatched_zero": [], "coa": None, "rolled": []}
    got = reader.fs_layout(path)
    from_prior_fs = basis.startswith("전기")
    acct_labels = {_norm(r["label"]) for sh in got["sheets"] for r in sh["rows"] if r["kind"] == "acct"}
    by_line: dict[str, list[dict]] = {}
    for a in accounts:
        if a.get("line"):
            by_line.setdefault(_norm(a["line"]), []).append(a)
    for a in accounts:                                   # 양식 줄이 표시과목 대신 계정 이름을 쓴 경우(「예수금」)
        k = _norm(a.get("name"))
        if not k:
            continue
        if k in by_line and any(x["code"] == a["code"] for x in by_line[k]):
            continue
        by_line.setdefault(k, []).append(a)               # 이름이 같은 계정이 여럿이다(대손충당금). 전부 담는다
    for ln in lines or []:                               # 양식 과목 이름 → 표시과목(분석이 맞춘 전기 과목 이름)
        for lab in ln.get("prior_labels") or []:
            k = _norm(lab)
            if k not in by_line and _norm(ln["label"]) in by_line:
                by_line[k] = by_line[_norm(ln["label"])]
    used, rows, taken, parent_code = set(), [], set(), None
    for sheet in got["sheets"]:
        # 전기 재무제표에 한 해 열만 있으면 그 열이 곧 전기다(비교식이면 전기 열을 쓴다. figures.prior_excel 과 같은 규칙)
        one_col = from_prior_fs and all(r["prior"] is None for r in sheet["rows"])
        # 비교식 재무제표에서 과목 줄의 빈 전기 칸은 잔액 0 이다(당기에 새로 생긴 과목). None 으로 두면 증감 판정에서 빠진다
        has_prior = not one_col and any(r["prior"] is not None for r in sheet["rows"])
        for r in sheet["rows"]:
            key = _norm(r["label"])
            codes = []
            if r["kind"] == "acct":                   # 차감 짝(대손충당금)도 제 계정을 붙인다
                # 공시 줄 하나에 표시과목 여럿이 중점으로 묶인 경우가 있다(「예수금 · 부가세예수금 · 미지급법인세」).
                # 줄 이름이 스스로 묶음을 밝히므로 통째로 먼저 찾고, 없으면 나눈 조각으로 찾는다
                parts = [key] if key in by_line else [_norm(x) for x in re.split(r"[·,/]", r["label"]) if _norm(x)]
                for k in parts:
                    # 표시과목이 같아도 제 이름의 줄이 양식에 따로 있는 계정은 그 줄로 간다
                    # (자본금 줄이 우선주자본금을 담으면 우선주자본금 줄과 두 번 더해진다)
                    cand = [a for a in by_line.get(k, []) if _norm(a.get("name")) == k or _norm(a.get("name")) not in acct_labels]
                    if r["contra_of"] and len(cand) > 1:
                        # 「대손충당금」 처럼 이름이 같은 차감 계정이 여럿이다. 아직 안 쓴 것 가운데
                        # 위 과목 코드에 가장 가까운 것을 고른다(더존 계정 체계는 위 과목 바로 뒤에 차감 계정을 둔다)
                        free = [a for a in cand if a["code"] not in taken] or cand
                        cand = sorted(free, key=lambda a: abs(_codenum(a["code"]) - (parent_code or 0)))[:1]
                    for a in cand:
                        if a["code"] not in codes:
                            codes.append(a["code"])
                        used.add(k)
                if codes:
                    taken.update(codes)
                    if not r["contra_of"]:
                        parent_code = _codenum(codes[0])
            prior = r["cur"] if one_col else r["prior"]
            if prior is None and has_prior and r["kind"] == "acct":
                prior = 0
            neg = _negative(sheet["stmt"], r["kind"], key, r["contra_of"])
            rows.append({"kind": r["kind"], "label": r["label"], "level": r["level"], "stmt": sheet["stmt"],
                         "codes": codes, "contra_of": r["contra_of"], "prior": prior,
                         "cur_disclosed": None if one_col else r["cur"], "source": basis,
                         # 시산표 부호 쪽으로 맞춘 공시 금액(차감 줄은 음수). 8100B · 2120A 의 증감은 이 값으로 낸다
                         "negative": neg, "prior_signed": _signed(prior, neg),
                         "cur_disclosed_signed": None if one_col else _signed(r["cur"], neg), "rolled": []})
    coa, coa_path = _coa(d)
    rolled = _roll_up(rows, accounts, taken, coa) if coa else []
    unmatched_lines = [r["label"] for r in rows if r["kind"] == "acct" and not r["codes"] and not r["contra_of"]]
    left = [a for a in accounts if a["code"] not in taken]
    return {"rows": rows, "basis": basis, "source_path": path.relative_to(d).as_posix(),
            "unmatched_lines": unmatched_lines,
            # 양식에 자리가 없는 계정. 잔액이 있는 것과 당기 · 전기 모두 0 인 것을 나눈다(0 인 계정까지 띄우면 볼 것이 묻힌다)
            "unmatched_accounts": [f"{a['code']} {a['name']}" for a in left if a.get("cur") or a.get("prior")],
            "unmatched_zero": [f"{a['code']} {a['name']}" for a in left if not (a.get("cur") or a.get("prior"))],
            "coa": coa_path, "rolled": rolled}


def _roll_up(rows: list[dict], accounts: list[dict], taken: set, coa: dict) -> list[dict]:
    """자리가 없는 계정을 계정과목표의 상위 계정으로 올려 묶는다. 상위 계정이 이미 어느 과목에 붙었으면 그 과목으로,
    상위 계정이 시산표에 없으면(제예금은 하위 계정에만 잔액이 있다) 상위 계정 이름과 같은 과목 줄로 간다.
    차감 짝 줄로는 올리지 않는다(이름이 같은 차감 계정이 여럿이라 자리가 갈리지 않는다)."""
    info = {x["code"]: x for x in coa["rows"]}
    at_code = {str(c): i for i, r in enumerate(rows) for c in r["codes"]}
    at_label: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r["kind"] == "acct" and not r["contra_of"]:
            at_label.setdefault(_norm(r["label"]), i)
    out = []
    for a in accounts:
        code = a["code"]
        if code in taken:
            continue
        p, seen = (info.get(str(code)) or {}).get("parent"), set()
        while p and p not in seen:
            seen.add(p)
            i = at_code.get(p)
            if i is None:
                i = at_label.get(_norm(info[p]["name"]))
            if i is not None and not rows[i]["contra_of"]:
                rows[i]["codes"].append(code)
                taken.add(code)
                at_code[str(code)] = i
                note = {"code": code, "name": a["name"], "parent": p, "parent_name": info[p]["name"], "label": rows[i]["label"]}
                rows[i]["rolled"].append(note)
                out.append(note)
                break
            p = info[p]["parent"]
    return out
