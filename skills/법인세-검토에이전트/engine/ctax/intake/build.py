"""장부.json 조립. 분개장 · 재무제표 · 거래처원장을 계정코드로 잇고 대사 다섯을 돌린다(CONTRACT.md 3 · 5절).

부호
- debit · credit · opening · closing: 차변 양수(잔액 = 차변 − 대변).
- amount · prior_amount: 자연 부호(자산 · 비용 = 차변 잔액 양수, 부채 · 자본 · 수익 = 대변 잔액 양수).
- 손익 계정 debit · credit 은 손익대체(400 이 든 전표)를 뺀 값이다.
  500~799 원가 계정은 재고 · 매출원가로 넘긴 대체 줄도 뺀다(그 금액은 `transfer`). 계약과 다른 점이라 NOTES.md 에 적었다.
- 더존 ERP 는 계정 단위 코드(앞 3자 + 0000)로 묶고 세분류는 `subaccounts` 에 둔다(douzone.py).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .fs import FsLine, LIAB_CONTRA_ASSETS, RE_NAMES, IS_SECTIONS, find_head
from .journal import Journal, c3
from .partners import PartnerFile
from .xlsxread import norm

CASH = 101


# ---------------------------------------------------------------- 코드 범위

def code_class(code: str) -> tuple[str, str]:
    """위하고 코드 범위로 정한 (class, section). 재무제표에 이어지면 재무제표 구역이 이긴다."""
    k = c3(code)
    if 101 <= k <= 145:
        return "자산", "유동자산"
    if 146 <= k <= 175:
        return "자산", "유동자산"
    if 176 <= k <= 250:
        return "자산", "비유동자산"
    if 251 <= k <= 290:
        return "부채", "유동부채"
    if 291 <= k <= 330:
        return "부채", "비유동부채"
    if 331 <= k <= 340:
        return "자본", "자본금"
    if 341 <= k <= 350:
        return "자본", "자본잉여금"
    if 351 <= k <= 399:
        return "자본", "이익잉여금" if 371 <= k <= 380 else "자본조정"
    if k == 400:
        return "손익대체", "손익"
    if 401 <= k <= 450:
        return "수익", "매출액"
    if 451 <= k <= 500:
        return "비용", "매출원가"
    if 501 <= k <= 600:
        return "비용", "제조원가"
    if 601 <= k <= 650:
        return "비용", "도급원가"
    if 651 <= k <= 700:
        return "비용", "보관원가"
    if 701 <= k <= 750:
        return "비용", "분양원가"
    if 751 <= k <= 799:
        return "비용", "운송원가"
    if 801 <= k <= 900:
        return "비용", "판매비와관리비"
    if 901 <= k <= 930:
        return "수익", "영업외수익"
    if 931 <= k <= 960:
        return "비용", "영업외비용"
    if 961 <= k <= 997:
        return "자산", "비유동자산"
    if 998 <= k <= 999:
        return "비용", "법인세등"
    return "자산", ""


BS_CLASSES = ("자산", "부채", "자본")
PL_CLASSES = ("수익", "비용")


def is_cost(code: str) -> bool:
    return 500 <= c3(code) <= 799


def is_re(code: str) -> bool:
    return 375 <= c3(code) <= 378


def natural(cls: str, dp: int) -> int:
    return dp if cls in ("자산", "비용", "손익대체") else -dp


def check(cid: str, ok: bool, title: str, detail: str, amounts: dict | None = None, warn: bool = False) -> dict:
    """warn: 통과로 두되 사람이 볼 것이 남았다(대사 줄에 [경고] 로 찍는다)."""
    out = {"id": cid, "ok": bool(ok), "title": title, "detail": detail, "amounts": amounts or {}}
    if warn:
        out["warn"] = True
    return out


def w(n) -> str:
    return f"{int(n):,}"


# ---------------------------------------------------------------- 분개장 집계

class Agg:
    def __init__(self, j: Journal):
        self.dr = Counter()
        self.cr = Counter()
        self.dr_pre = Counter()          # 마감 · 원가 대체 줄을 뺀 것
        self.cr_pre = Counter()
        self.net_noclose = Counter()     # 마감 전표만 뺀 것(원가 대체 포함)
        self.transfer = Counter()
        self.n = Counter()
        self.names: dict[str, Counter] = defaultdict(Counter)        # 계정 단위 줄의 이름
        self.member_names: dict[str, Counter] = defaultdict(Counter)  # 세분류 줄의 이름(더존 ERP)
        self.raw_names: dict[str, Counter] = defaultdict(Counter)
        self.partner = defaultdict(lambda: [0, 0])
        self.partner_names: dict[tuple, Counter] = defaultdict(Counter)
        self.sub: dict[tuple, dict] = {}                             # (계정, 세분류 코드) → 집계
        for ln in j.lines:
            k = ln.account
            self.dr[k] += ln.debit
            self.cr[k] += ln.credit
            self.n[k] += 1
            if ln.sub_account and ln.sub_account != k:
                self.member_names[k][norm(ln.account_name)] += 1
            else:
                self.names[k][norm(ln.account_name)] += 1
            self.raw_names[k][ln.account_name] += 1
            if ln.sub_account:
                sb = self.sub.setdefault((k, ln.sub_account), {"names": Counter(), "dr": 0, "cr": 0, "dr_pre": 0,
                                                               "cr_pre": 0, "n": 0})
                sb["names"][ln.account_name] += 1
                sb["dr"] += ln.debit
                sb["cr"] += ln.credit
                sb["n"] += 1
                if not ln.closing and not ln.transfer:
                    sb["dr_pre"] += ln.debit
                    sb["cr_pre"] += ln.credit
            if not ln.closing:
                self.net_noclose[k] += ln.debit - ln.credit
                if ln.transfer:
                    self.transfer[k] += ln.credit
                else:
                    self.dr_pre[k] += ln.debit
                    self.cr_pre[k] += ln.credit
            pc = ln.partner_code or "000000"
            self.partner[(k, pc)][0] += ln.debit
            self.partner[(k, pc)][1] += ln.credit
            if ln.partner:
                self.partner_names[(k, pc)][ln.partner] += 1

    def name(self, k: str) -> str | None:
        """계정 이름(공백 · 꼬리 지움). 더존 ERP 에서 계정 단위 줄이 없고 세분류 줄만 있으면 None."""
        return self.names[k].most_common(1)[0][0] if self.names.get(k) else None

    def label(self, k: str) -> str:
        """메시지용 이름. 계정 단위 이름이 없으면 세분류 이름들."""
        if self.name(k):
            return self.name(k)
        return "/".join(n for n, _ in self.member_names[k].most_common(3)) if self.member_names.get(k) else ""

    def named(self, k: str, name: str) -> bool:
        """계정 k 가 이름 name 인가. 계정 단위 이름이 없으면 세분류 이름으로 본다."""
        nm = self.name(k)
        return nm == name if nm else name in self.member_names.get(k, {})

    def partner_name(self, k: str, pc: str) -> str:
        c = self.partner_names.get((k, pc))
        return c.most_common(1)[0][0] if c else ""

    def net(self, k: str) -> int:
        return self.dr[k] - self.cr[k]

    def pre(self, k: str) -> int:
        return self.dr_pre[k] - self.cr_pre[k]


# ---------------------------------------------------------------- 거래처 파일 계정 정하기

def _one_char_off(a: str, names) -> list[str]:
    """길이가 같고 한 글자만 다른 이름들(더존 계정명세서 제목 오타 `선납세급` → `선납세금`)."""
    return [n for n in names if len(n) == len(a) and n != a and sum(x != y for x, y in zip(a, n)) == 1]


def _by_name(title: str, agg: Agg) -> tuple[list[str], str]:
    """계정명세서 블록 제목으로 분개장 계정을 찾는다. (후보 코드, 방법)."""
    t = norm(title)
    codes = sorted(agg.n)
    found = [k for k in codes if agg.name(k) == t]
    if found:
        return found, "블록 제목 = 분개장 계정 이름"
    found = [k for k in codes if t in agg.member_names.get(k, {})]
    if found:
        return found, "블록 제목 = 분개장 세분류 이름"
    names = {agg.name(k) for k in codes if agg.name(k)}
    alt = _one_char_off(t, names)
    if len(alt) == 1:
        return [k for k in codes if agg.name(k) == alt[0]], f"블록 제목 한 글자 차이({title} → {alt[0]})"
    return [], ""


def resolve_partner_files(pfs: list[PartnerFile], agg: Agg, five: bool) -> None:
    codes = set(agg.n)
    seen: dict[tuple, str] = {}
    for pf in pfs:
        if pf.form == "B" and not pf.account and pf.hint_name:
            found, how = _by_name(pf.hint_name, agg)
            if len(found) == 1:
                pf.account, pf.how = found[0], how
            elif found:
                s_amt = sum(x["amount"] for x in pf.rows)
                fit = [k for k in found if abs(agg.net(k)) == abs(s_amt)]
                if len(fit) == 1:
                    pf.account, pf.how = fit[0], how + "(같은 이름 여럿, 금액으로 고름)"
                else:
                    pf.how = f"같은 이름 계정이 여럿이라 정하지 못함({', '.join(found)})"
            else:
                pf.how = "블록 제목과 같은 이름의 계정이 분개장에 없음"
            for x in pf.rows:
                x["account"] = pf.account or ""
        if pf.form == "A":
            code = None
            if pf.hint:
                h = pf.hint
                code = h if (five or len(h) == 3) else (str(int(h) // 100) if h.endswith("00") else h)
            fdr = sum(x["dr"] for x in pf.rows)
            fcr = sum(x["cr"] for x in pf.rows)
            if code and code in codes and (agg.dr[code], agg.cr[code]) == (fdr, fcr):
                pf.account, pf.how = code, "파일 이름 코드 · 분개장 합계 일치"
            elif code and c3(code) == CASH:
                pf.account, pf.how = code, "파일 이름 코드(현금 거래처원장은 분개장과 맞지 않음)"
            else:
                found = [k for k in codes if (agg.dr[k], agg.cr[k]) == (fdr, fcr)] if fdr or fcr else []
                if len(found) == 1:
                    pf.account, pf.how = found[0], "분개장 차변 · 대변 합계로 찾음"
                    if code and code != found[0]:
                        pf.notes.append(f"파일 이름 코드 {code} 와 내용이 다릅니다. 내용으로 {found[0]} 로 봤습니다")
                elif code:
                    pf.account = code
                    pf.how = "파일 이름 코드(분개장에 거래 없음)" if not (fdr or fcr) else "파일 이름 코드(분개장 합계와 다름)"
                else:
                    pf.how = "계정을 정하지 못함"
        key = (pf.account, pf.digest)
        if pf.account and key in seen:
            pf.duplicate_of = seen[key]
        elif pf.account:
            seen[key] = pf.key


# ---------------------------------------------------------------- B 꼴 거래처 줄

def _src(p: PartnerFile, x: dict) -> dict:
    """거래처 줄의 원본 파일 · 엑셀 행(11-01). 행 번호를 모르는 줄(더존 계정명세서 블록)은 붙이지 않는다."""
    return {"src_file": p.path, "src_row": x["row"]} if x.get("row") else {}


def _b_rows(p: PartnerFile, acc: dict | None, agg: Agg, complete: bool, stats: dict) -> list[dict]:
    """B 꼴(기말만 있는 계정명세서) → 거래처 줄. 기초는 (기말 − 분개장 거래처별 순증감)으로 추정한다.

    - 잔액 부호: 명세 합계가 장부 기말과 같은 쪽으로, 못 맞추면 계정 class 로.
    - 계정 단위 파일(거래처코드가 모두 빈 줄 · 계정과목 블록)은 계정 전체 증감을 첫 줄에 붙인다.
    - complete 이면 분개장에 거래가 있는데 명세에 없는 거래처(기말 0 이라 빠진 거래처)를 기말 0 줄로 더한다(`in_file: false`).
      그래야 추정 기초 합계가 장부 기초와 맞는다.
    """
    cls = acc["class"] if acc else code_class(p.account)[0]
    s_amt = sum(x["amount"] for x in p.rows)
    if acc and s_amt and s_amt == acc["closing"]:
        sg = 1
    elif acc and s_amt and -s_amt == acc["closing"]:
        sg = -1
    else:
        sg = 1 if cls == "자산" and not (acc and acc["amount"] < 0) else -1
    out = []
    natural_sign = 1 if (acc["closing"] if acc else sg) >= 0 else -1
    if p.account_level:
        jd, jc = agg.dr[p.account], agg.cr[p.account]
        for i, x in enumerate(p.rows):
            d_, c_ = (jd, jc) if i == 0 else (0, 0)
            closing = sg * x["amount"]
            out.append({"account": p.account, "partner_code": x["code"], "partner": x["name"],
                        "opening": closing - d_ + c_, "debit": d_, "credit": c_, "closing": closing,
                        "estimated_opening": True, **_src(p, x)})
        return out
    seen: set[str] = set()
    for x in p.rows:
        pc = x["code"] or "000000"
        jd, jc = agg.partner.get((p.account, pc), (0, 0)) if pc not in seen else (0, 0)
        seen.add(pc)
        closing = sg * x["amount"]
        row = {"account": p.account, "partner_code": x["code"], "partner": x["name"],
               "opening": closing - jd + jc, "debit": jd, "credit": jc, "closing": closing, "estimated_opening": True,
               **_src(p, x)}
        if row["opening"] * natural_sign < 0:
            stats["negative"] += 1
        out.append(row)
    if complete:
        for (a, pc) in sorted(k for k in agg.partner if k[0] == p.account and k[1] not in seen):
            jd, jc = agg.partner[(a, pc)]
            if not jd and not jc:
                continue
            out.append({"account": a, "partner_code": "" if pc == "000000" else pc, "partner": agg.partner_name(a, pc),
                        "opening": jc - jd, "debit": jd, "credit": jc, "closing": 0, "estimated_opening": True,
                        "in_file": False})
            stats["added"] += 1
    return out


# ---------------------------------------------------------------- 조립

def build(*, journal: Journal, bs: list[FsLine], is_: list[FsLine], pfs: list[PartnerFile], files: list[dict],
          tb: list[dict] | None = None) -> dict:
    agg = Agg(journal)
    five = journal.five
    lens = Counter(len(k) for k in agg.n if k.isdigit())
    code_len = lens.most_common(1)[0][0] if lens else 3
    resolve_partner_files(pfs, agg, five)
    live_pfs = [p for p in pfs if p.account and not p.duplicate_of]
    pf_by_code: dict[str, PartnerFile] = {}
    for p in live_pfs:
        pf_by_code.setdefault(p.account, p)

    jcodes = set(agg.n)
    code_cls = {k: code_class(k) for k in jcodes}
    bs_codes = [k for k in sorted(jcodes) if code_cls[k][0] in BS_CLASSES and not is_re(k)]

    # ---- 재무상태표 줄 → 코드
    groups: list[list[FsLine]] = []
    merged: dict[str, list[FsLine]] = {}
    re_lines: list[FsLine] = []
    for ln in bs:
        if ln.kind != "account":
            continue
        if ln.side == "E" and RE_NAMES.search(ln.name):
            re_lines.append(ln)
            continue
        if any(ln.name.startswith(x) for x in LIAB_CONTRA_ASSETS):
            key = ln.name
            if key in merged:
                merged[key].append(ln)
                continue
            merged[key] = [ln]
            groups.append(merged[key])
            continue
        groups.append([ln])

    used: set[str] = set()
    link: dict[str, list[FsLine]] = {}      # code → 재무상태표 줄들

    def gsum(g):
        return sum(x.dp_cur for x in g), sum(x.dp_prior for x in g)

    def flip(g):
        for x in g:
            x.dp_cur, x.dp_prior = -x.dp_cur, -x.dp_prior
            x.extra["sign"] = -x.extra.get("sign", 1)

    def assign(g, k, how):
        for x in g:
            x.code, x.how = k, how
        link[k] = g
        used.add(k)

    def fits(k: str, cls: str) -> bool:
        """코드 범위가 재무상태표 구역과 맞는가. 961~997 은 회사마다 자산(보증금 · 출자금) · 자본(기타포괄손익)이 섞여 가리지 않는다."""
        return code_class(k)[0] == cls or 961 <= c3(k) <= 997

    def want_class(x: FsLine) -> str:
        if x.side == "A" or any(x.name.startswith(y) for y in LIAB_CONTRA_ASSETS):
            return "자산"
        return "부채" if x.side == "L" else "자본"

    for g in groups:                           # 1차: 이름 + 같은 구역 코드 + (전기 + 증감 = 당기)
        name = g[0].name
        cands = [k for k in bs_codes if agg.named(k, name) and k not in used and fits(k, want_class(g[0]))]
        cur, pri = gsum(g)
        for k in cands:
            if pri + agg.net(k) == cur:
                assign(g, k, "이름 · 증감 일치")
                break
            if -pri + agg.net(k) == -cur and cur != 0:
                flip(g)
                assign(g, k, "이름 · 증감 일치(부호 반대)")
                break
    for g in groups:                           # 2차: 이름만, 무변동은 거래처원장 · 명세서 파일로
        if g[0].code:
            continue
        name = g[0].name
        cur, pri = gsum(g)
        cands = [k for k in bs_codes if agg.named(k, name) and k not in used and fits(k, want_class(g[0]))]
        if cands and cur != pri:
            assign(g, cands[0], "이름만 일치(증감 다름)")
            continue
        if cur == 0 and pri == 0:
            for x in g:
                x.how = "0 줄(코드 없음)"
            continue
        want_cls = want_class(g[0])
        wc = abs(sum(x.cur or 0 for x in g))
        wp = abs(sum(x.prior or 0 for x in g))
        found = []
        for p in live_pfs:
            if p.account in used or p.account in jcodes and agg.n[p.account] and agg.net(p.account) != cur - pri:
                continue
            if not fits(p.account, want_cls) or is_re(p.account):
                continue
            if (agg.name(p.account) or agg.member_names.get(p.account)) and not agg.named(p.account, name):
                continue
            if p.form == "A":
                if abs(sum(x["op"] for x in p.rows)) == wp and abs(sum(x["bal"] for x in p.rows)) == wc:
                    found.append(p.account)
            else:
                if abs(sum(x["amount"] for x in p.rows)) == wc:
                    found.append(p.account)
        found = list(dict.fromkeys(found))
        if found:
            assign(g, found[0], "거래처원장 · 명세서 파일 금액 일치" + ("" if len(found) == 1 else f"(후보 {len(found)})"))
        else:
            for x in g:
                x.how = "코드 없음"

    # ---- 이익잉여금(375~378) 묶음
    re_codes = sorted({k for k in jcodes if is_re(k)} | {p.account for p in live_pfs if is_re(p.account)})
    re_cur = sum(x.dp_cur for x in re_lines)
    re_pri = sum(x.dp_prior for x in re_lines)
    re_open: dict[str, int] = {}
    led = {p.account: p for p in live_pfs if p.form == "A" and is_re(p.account)}
    led_open = {}
    for k, p in led.items():
        s = sum(x["op"] for x in p.rows)
        nat = p.nature or ("debit" if c3(k) in (376, 378) else "credit")
        led_open[k] = s if nat == "debit" else -s
    if led_open and sum(led_open.values()) == re_pri:
        re_open = {k: v for k, v in led_open.items() if v}
        re_how = "거래처원장 전기이월"
    elif re_lines:
        base = "376" if re_pri > 0 else "375"
        k = base + "0" * max(code_len - 3, 0)
        re_open = {k: re_pri} if re_pri else {}
        re_how = "결손이면 이월결손금(376), 이익이면 이월이익잉여금(375)"
    else:
        re_how = ""
    for k in re_open:
        if k not in re_codes:
            re_codes.append(k)
    re_codes.sort()
    re_close = {k: re_open.get(k, 0) + agg.net(k) for k in re_codes}
    re_holder = next((k for k in re_codes if re_close[k] == re_cur and re_cur), None) or \
        next(iter(re_open), None) or (re_codes[0] if re_codes else None)
    for x in re_lines:
        x.code, x.how = re_holder, "이익잉여금 묶음(375~378)"

    # ---- 손익계산서 줄 → 코드
    pl_codes = [k for k in sorted(jcodes) if code_cls[k][0] in PL_CLASSES and not is_cost(k) and k not in used]
    used_is: set[str] = set()
    is_link: dict[str, FsLine] = {}
    for ln in is_:
        if ln.kind != "account":
            continue
        cls, lo, hi = IS_SECTIONS[ln.section]
        sign = -1 if cls == "수익" else 1
        cands = [k for k in pl_codes if agg.named(k, ln.name) and k not in used_is]
        inr = [k for k in cands if lo <= c3(k) <= hi]
        pool = inr or cands
        pick = next((k for k in pool if sign * agg.pre(k) == (ln.cur or 0)), None) or (pool[0] if pool else None)
        how = "구역 · 이름" if pick in inr else "이름(구역 밖 코드)"
        if not pick and ln.cur:
            # 이름이 다른 계정(더존 ERP 에서 세분류만 쓰인 계정 등): 같은 구역 코드 중 금액이 같은 것이 하나뿐이면 잇는다
            same = [k for k in pl_codes if k not in used_is and lo <= c3(k) <= hi and not agg.name(k)
                    and sign * agg.pre(k) == ln.cur]
            if len(same) == 1:
                pick, how = same[0], "구역 · 금액 일치(계정 이름 없음, 세분류만)"
        if pick:
            ln.code, ln.how = pick, how
            used_is.add(pick)
            is_link[pick] = ln
        else:
            ln.how = "코드 없음"

    # ---- 계정 목록
    subs_of: dict[str, list[str]] = defaultdict(list)
    for (k, sc) in sorted(agg.sub):
        subs_of[k].append(sc)
    all_codes = set(jcodes) | set(link) | set(re_codes) | {p.account for p in live_pfs}
    accounts = []
    acc_map: dict[str, dict] = {}
    for k in sorted(all_codes, key=lambda s: (c3(s), s)):
        cls, section = code_class(k)
        sub = ""
        fs_label = None
        prior_amount = 0
        prior_known = True
        if k in link:
            g = link[k]
            x = g[0]
            cls = "자산" if x.side == "A" or any(x.name.startswith(y) for y in LIAB_CONTRA_ASSETS) else \
                ("부채" if x.side == "L" else "자본")
            section, sub, fs_label = x.section, x.sub, x.label
        elif k in is_link:
            x = is_link[k]
            cls = IS_SECTIONS[x.section][0]
            section, fs_label = x.section, x.label
            prior_amount = x.prior or 0
        elif is_re(k) and re_lines:
            cls, section, fs_label = "자본", re_lines[0].section, re_lines[0].label
        name = agg.name(k)
        if not name:
            if k in link:
                name = link[k][0].name
            elif k in is_link:
                name = is_link[k].name
            elif k in pf_by_code and pf_by_code[k].form == "B" and pf_by_code[k].rows:
                name = pf_by_code[k].rows[0]["account_name"]
            elif is_re(k) and re_lines:
                name = {375: "이월이익잉여금", 376: "이월결손금", 377: "미처분이익잉여금", 378: "미처리결손금"}[c3(k)]
            else:
                name = ""
        rec = {"code": k, "name": name, "class": cls, "section": section}
        if cls in BS_CLASSES:
            if k in link:
                opening = sum(x.dp_prior for x in link[k])
            elif is_re(k):
                opening = re_open.get(k, 0)
            else:
                opening = 0
            debit, credit = agg.dr[k], agg.cr[k]
            closing = opening + debit - credit
            prior_amount = natural(cls, opening)
        elif cls == "손익대체":
            opening, debit, credit = 0, agg.dr[k], agg.cr[k]
            closing = debit - credit
        else:
            opening, debit, credit = 0, agg.dr_pre[k], agg.cr_pre[k]
            closing = debit - credit
            if k not in is_link:
                prior_known = False
        rec.update({"opening": opening, "debit": debit, "credit": credit, "closing": closing,
                    "amount": natural(cls, closing), "prior_amount": prior_amount, "fs_label": fs_label,
                    "lines": agg.n[k]})
        if sub:
            rec["subsection"] = sub
        sc = subs_of.get(k, [])
        if sc and (len(sc) > 1 or sc[0] != k):
            pre = cls in PL_CLASSES
            rec["subaccounts"] = [{"code": c, "name": agg.sub[(k, c)]["names"].most_common(1)[0][0],
                                   "debit": agg.sub[(k, c)]["dr_pre" if pre else "dr"],
                                   "credit": agg.sub[(k, c)]["cr_pre" if pre else "cr"],
                                   "lines": agg.sub[(k, c)]["n"]} for c in sc]
        if is_cost(k):
            rec["transfer"] = agg.transfer[k]
        if cls in PL_CLASSES and not prior_known:
            rec["prior_known"] = False
        accounts.append(rec)
        acc_map[k] = rec

    # ---- 거래처(파일마다 기초 · 기말 합계를 함께 남겨 대사에 쓴다)
    partners = []
    file_sums: dict[str, tuple[int, int, bool]] = {}     # 파일 → (기초 합, 기말 합, 기초를 대사하는가)
    a_accounts = {p.account for p in live_pfs if p.form == "A"}
    completed: set[str] = set()
    b_stats = {"added": 0, "negative": 0}
    for p in live_pfs:
        acc = acc_map.get(p.account)
        rows_out = []
        if p.form == "A":
            nat = p.nature
            if nat is None:
                s = sum(x["bal"] for x in p.rows)
                if acc and s == acc["closing"] and s != 0:
                    nat = "debit"
                elif acc and -s == acc["closing"] and s != 0:
                    nat = "credit"
                else:
                    cls = acc["class"] if acc else code_class(p.account)[0]
                    contra = bool(acc) and acc["amount"] < 0 and cls == "자산"
                    nat = "debit" if (cls == "자산" and not contra) or c3(p.account) in (376, 378) else "credit"
            p.nature = nat
            sg = 1 if nat == "debit" else -1
            for x in p.rows:
                rows_out.append({"account": p.account, "partner_code": x["code"], "partner": x["name"],
                                 "opening": sg * x["op"], "debit": x["dr"], "credit": x["cr"],
                                 "closing": sg * x["bal"], **_src(p, x)})
            check_open = True
        else:
            # B 꼴: 분개장에만 있는 거래처를 채운 파일(계정마다 첫 파일)은 추정 기초 합계 = 장부 기초도 본다
            check_open = p.account not in completed
            rows_out = _b_rows(p, acc, agg, complete=check_open, stats=b_stats)
            completed.add(p.account)
        file_sums[p.key] = (sum(r["opening"] for r in rows_out), sum(r["closing"] for r in rows_out), check_open)
        if p.form == "A" or p.account not in a_accounts:    # A 꼴이 있는 계정은 B 꼴 줄을 겹쳐 넣지 않는다
            partners.extend(rows_out)

    # ---- 재무제표 줄
    def fs_out(ln: FsLine, bs_side: bool) -> dict:
        d = {"label": ln.label, "cur": ln.cur, "prior": ln.prior, "code": ln.code if ln.kind == "account" else None,
             "kind": ln.kind, "section": ln.section, "src_row": ln.src_row}
        if bs_side and ln.contra:
            d["contra"] = True
            d["net_cur"], d["net_prior"] = ln.net_cur, ln.net_prior
        return d

    fs = {"bs": [fs_out(x, True) for x in bs], "is": [fs_out(x, False) for x in is_]}

    # ---- 합계
    def totals_for(prior: bool) -> dict:
        def g(lines, pat):
            v = find_head(lines, pat, prior)
            return 0 if v is None else v
        return {"revenue": g(is_, r"^(매출액|매출|영업수익)$"),
                "net_income": g(is_, r"당기순(이익|손실|손익)$"),
                "income_before_tax": g(is_, r"차감전(순)?(이익|손실|손익)$"),
                "corporate_tax": g(is_, r"^법인세(등|비용)$"),
                "assets": g(bs, r"^자산총계$"), "liabilities": g(bs, r"^부채총계$"), "equity": g(bs, r"^자본총계$"),
                "cogs": g(is_, r"^매출원가$"), "gross_profit": g(is_, r"^매출총(이익|손실)$"),
                "sga": g(is_, r"^판매(비(와|및일반|와일반))?관리비$"), "operating_income": g(is_, r"^영업(이익|손실)$"),
                "non_operating_income": g(is_, r"^영업외수익$"), "non_operating_expense": g(is_, r"^영업외비용$")}

    totals = totals_for(False)
    totals["prior"] = totals_for(True)

    # 손익(400)에 당기순손익이 그대로 남았는가(손익 → 미처분이익잉여금 대체 전표만 분개장에 없음, 더존 ERP)
    pl_residual = sum(agg.net(k) for k in agg.n if c3(k) == 400)
    unposted = pl_residual if pl_residual and pl_residual == -totals["net_income"] else 0
    unresolved = [p for p in pfs if not p.account]
    checks = [
        _check_balanced(journal),
        _check_bs(groups, re_lines, re_codes, re_open, re_how, agg, link, bs_codes, bs, totals, unposted),
        _check_pl(is_, agg, pl_codes, used_is, code_cls, totals),
        _check_closing(journal, agg, code_cls, unposted),
        _check_partners(live_pfs, acc_map, file_sums, sum(1 for p in pfs if p.duplicate_of), unresolved, b_stats),
        _check_partner_lines(live_pfs, agg, acc_map),
        _check_is_footing(is_),
    ]
    from .journal import returned_to_stock
    back = returned_to_stock(journal.lines)
    cost_by: dict[str, int] = defaultdict(int)
    for k in agg.n:
        if is_cost(k):
            cost_by[cost_range(k)] += agg.dr_pre[k] - agg.cr_pre[k] - back.get(k, 0)
    cost = check_cost_flow(is_, bs, dict(cost_by))
    if cost is not None:
        checks.append(cost)
    if tb:
        loose = [{"name": x.name, "closing": x.dp_cur} for x in bs if x.kind == "account" and not x.code and x.dp_cur]
        checks.append(_check_tb(tb, accounts, agg, loose))
    return {"source": journal.source, "files": files, "accounts": accounts, "partners": partners, "fs": fs,
            "totals": totals, "checks": checks, "journal_csv": "_색인/전표.csv"}


# ---------------------------------------------------------------- 대사

def _check_balanced(j: Journal) -> dict:
    dr = sum(x.debit for x in j.lines)
    cr = sum(x.credit for x in j.lines)
    bad = []
    for key, v in j.vouchers.items():
        d = sum(x.debit for x in v) - sum(x.credit for x in v)
        if d:
            bad.append((key, d))
    ok = dr == cr and not bad
    detail = f"차변 {w(dr)} · 대변 {w(cr)} · 전표 {w(len(j.vouchers))}장"
    amounts = {"debit": dr, "credit": cr, "diff": dr - cr}
    if bad:
        detail += f" · 차대가 맞지 않는 전표 {len(bad)}장(예 {bad[0][0][0]} #{bad[0][0][1]} {w(bad[0][1])})"
        amounts["unbalanced_vouchers"] = len(bad)
    if j.total_row:
        t = j.total_row
        same = t["debit"] == dr and t["credit"] == cr
        detail += " · 파일 합계 줄과 같음" if same else f" · 파일 합계 줄과 다름(차변 {w(t['debit'])} · 대변 {w(t['credit'])})"
        ok = ok and same
        if t.get("count") is not None and t["count"] != len(j.vouchers):
            detail += f" · 합계 줄 건수 {w(t['count'])} 와 전표 수가 다름"
    return check("balanced", ok, "차변합 = 대변합", detail, amounts)


def _check_bs(groups, re_lines, re_codes, re_open, re_how, agg, link, bs_codes, bs, totals, unposted=0) -> dict:
    diffs = {}
    msgs = []
    n_ok = 0
    nomove = 0
    for g in groups:
        x = g[0]
        cur, pri = sum(y.dp_cur for y in g), sum(y.dp_prior for y in g)
        net = agg.net(x.code) if x.code else 0
        d = cur - (pri + net)
        if d:
            diffs[x.label] = d
            msgs.append(f"{x.label}({x.code or '코드 없음'}) 전기 {w(pri)} + 증감 {w(net)} ≠ 당기 {w(cur)}")
        else:
            n_ok += 1
            if not net:
                nomove += 1
    if re_lines:
        cur = sum(y.dp_cur for y in re_lines)
        pri = sum(y.dp_prior for y in re_lines)
        net = sum(agg.net(k) for k in re_codes) + unposted
        d = cur - (pri + net)
        if d:
            diffs["이익잉여금"] = d
            msgs.append(f"이익잉여금(375~378) 전기 {w(pri)} + 증감 {w(net)} ≠ 당기 {w(cur)}")
        else:
            n_ok += 1
    left = [(k, agg.name(k), agg.net(k)) for k in bs_codes if k not in link and agg.net(k) != 0]
    for k, nm, v in left:
        diffs[f"{k} {nm}"] = v
        msgs.append(f"재무상태표에 없는 계정 {k} {nm} 잔액 {w(v)}")
    # 줄 합계 = 총계(읽기 검산)
    side_sum = {s: sum(x.dp_cur for x in bs if x.kind == "account" and x.side == s) for s in "ALE"}
    tot = {"A": totals["assets"], "L": -totals["liabilities"], "E": -totals["equity"]}
    for s, nm in (("A", "자산총계"), ("L", "부채총계"), ("E", "자본총계")):
        if side_sum[s] != tot[s]:
            diffs[nm] = side_sum[s] - tot[s]
            msgs.append(f"{nm}: 계정 줄 합계 {w(abs(side_sum[s]))} ≠ 총계 {w(abs(tot[s]))}")
    if totals["assets"] != totals["liabilities"] + totals["equity"]:
        diffs["자산 - 부채 - 자본"] = totals["assets"] - totals["liabilities"] - totals["equity"]
        msgs.append("자산총계 ≠ 부채총계 + 자본총계")
    nlines = len(groups) + (1 if re_lines else 0)
    detail = f"계정 줄 {nlines}개 중 {n_ok}개 일치(무변동 {nomove})"
    if re_lines:
        detail += f" · 이익잉여금 기초 배분: {re_how}"
        if unposted:
            detail += (f" · 손익(400)에 남은 당기순손익 {w(-unposted)} 을 이익잉여금 증감에 더했습니다"
                       "(손익을 미처분이익잉여금으로 넘기는 전표가 분개장에 없음)")
    if msgs:
        detail += " · " + " / ".join(msgs[:8]) + (f" 외 {len(msgs) - 8}건" if len(msgs) > 8 else "")
    return check("bs_rollforward", not diffs, "재무상태표 전기 + 분개장 증감 = 당기", detail, diffs)


def _check_pl(is_, agg, pl_codes, used_is, code_cls, totals) -> dict:
    diffs = {}
    msgs = []
    n = n_ok = 0
    for ln in is_:
        if ln.kind != "account":
            continue
        n += 1
        cls = IS_SECTIONS[ln.section][0]
        ours = 0 if not ln.code else (-agg.pre(ln.code) if cls == "수익" else agg.pre(ln.code))
        d = (ln.cur or 0) - ours
        if d:
            diffs[ln.label] = d
            msgs.append(f"{ln.label}({ln.code or '코드 없음'}) 손익계산서 {w(ln.cur or 0)} · 분개장 {w(ours)}")
        else:
            n_ok += 1
    for k in pl_codes:
        if k not in used_is and agg.pre(k) != 0:
            diffs[f"{k} {agg.name(k)}"] = agg.pre(k)
            msgs.append(f"손익계산서에 없는 계정 {k} {agg.name(k)} {w(agg.pre(k))}")
    ni = -sum(v for k, v in agg.net_noclose.items() if code_class(k)[0] in PL_CLASSES)
    if ni != totals["net_income"]:
        diffs["당기순이익"] = totals["net_income"] - ni
        msgs.append(f"당기순이익 손익계산서 {w(totals['net_income'])} · 분개장(마감 전) {w(ni)}")
    detail = f"계정 줄 {n}개 중 {n_ok}개 일치 · 당기순이익 분개장(마감 전) {w(ni)}"
    if msgs:
        detail += " · " + " / ".join(msgs[:8]) + (f" 외 {len(msgs) - 8}건" if len(msgs) > 8 else "")
    return check("pl_match", not diffs, "마감 전 분개장 집계 = 손익계산서", detail, diffs)


def _check_closing(j: Journal, agg, code_cls, unposted: int = 0) -> dict:
    pl = [k for k in agg.n if c3(k) == 400]
    residual = sum(agg.net(k) for k in pl) - unposted
    n_close = sum(1 for x in j.lines if x.closing)
    vouchers = sorted({(x.date, x.no) for x in j.lines if x.closing})
    left = {k: agg.net(k) for k in agg.n if code_class(k)[0] in PL_CLASSES and agg.net(k) != 0}
    amounts = {"손익 400 잔액": residual}
    if not pl:
        return check("closing_residual", True, "손익(400) 계정 잔액 0",
                     "분개장에 손익대체 전표가 없습니다(마감 전 분개장으로 봅니다)", amounts)
    detail = (f"손익대체 전표 {len(vouchers)}장 {n_close}줄"
              f"({', '.join(f'{d} #{no}' for d, no in vouchers[:4])}) · 손익 400 잔액 {w(residual + unposted)}")
    if unposted:
        detail += (f" · 이 잔액은 당기순손익 {w(-unposted)} 과 같습니다. 손익을 미처분이익잉여금으로 넘기는 전표만 분개장에 없고"
                   " 재무상태표 미처분이익잉여금에는 들어 있습니다(더존 ERP 는 재무제표에서 당기순손익을 더해 보여 줍니다)."
                   " 마감 누락이 아니므로 남은 금액을 0 으로 봅니다")
    if left:
        parts = [f"{k} {agg.name(k)} {w(v)}" for k, v in sorted(left.items())]
        detail += (" · 마감 뒤에도 잔액이 남은 손익 계정: " + ", ".join(parts[:8])
                   + (f" 외 {len(parts) - 8}개" if len(parts) > 8 else ""))
        for k, v in left.items():
            amounts[f"{k} {agg.name(k)}"] = v
        if residual == 0:
            detail += (f" · 계정별 잔여 합계 {w(sum(left.values()))} 로 서로 상쇄되어 손익 400 은 "
                       + ("당기순손익을 빼면 " if unposted else "") + "0 입니다."
                       " 마감 전표를 만든 뒤 계정 사이 금액이 바뀐 것으로 보이며 손익계산서는 마감 전 집계와 맞으므로 통과로 봅니다"
                       "(계정별 손익대체 금액 확인 필요)")
    if residual and left and residual + sum(left.values()) == 0:
        # 손익 400 에 남은 금액이 마감 전표에 없는 손익 계정 잔액과 꼭 같다: 재무제표는 분개장과 맞고
        # 마감 전표의 꼴만 안 맞는 경우다(10-29 대표 기준). 통과 + 경고
        detail += (f" · 마감 전표에 없는 손익 계정 {len(left)}개를 마감 전 집계대로 손익에 넣었다(경고)."
                   f" 손익 400 잔액 {w(residual)} 이 그 계정 잔액 합계와 같아 재무제표 숫자는 분개장과 맞습니다"
                   "(계정별 손익대체 금액 확인)")
        return check("closing_residual", True, "손익(400) 계정 잔액 0", detail, amounts, warn=True)
    return check("closing_residual", residual == 0, "손익(400) 계정 잔액 0", detail, amounts)


def _code_key(code) -> str:
    s = str(code or "").strip()
    return s.lstrip("0") or s


def _check_partner_lines(live_pfs, agg: Agg, acc_map: dict) -> dict:
    """거래처원장(A 꼴) 줄마다 (1) 잔액 = 이월 ± 차변 · 대변, (2) 차변 · 대변 = 분개장 그 거래처(코드) 합계(11-01 PBC 대조).
    파일 합계만 보는 partner_match 는 거래처끼리 잔액을 옮겨도 통과한다. 코드 없는 거래처는 분개장과 같이 000000 으로 본다.
    분개장에 거래처 없는 줄이 있는데 파일에 000000(미등록거래처) 줄이 없으면 코드 있는 줄만 견주고 그 금액을 적는다. 분개장에
    움직임이 없는 계정은 줄마다 0 과 견준다. 분개장 줄에 거래처가 하나도 없거나 파일 코드가 분개장 거래처 코드와 하나도 맞지
    않는 계정만 (2) 를 하지 않고 그 사실을 적는다. B 꼴(기말만)은 줄 산식이 없어 보지 않는다(11-01 평가세트 사본 실행에서 고침)."""
    title = "거래처원장 줄마다 잔액 산식 · 분개장 거래처별 차변 · 대변"
    a_files = [p for p in live_pfs if p.form == "A" and c3(p.account) != CASH and p.rows]
    if not a_files:
        return check("partner_lines", True, title, "A 꼴 거래처원장이 없습니다(B 꼴 계정명세서는 기말만 있어 줄 대사를 하지 않습니다)")
    msgs, diffs, skipped, noted, n = [], {}, [], [], 0
    for p in a_files:
        acc = acc_map.get(p.account) or {}
        cls = acc.get("class") or code_class(p.account)[0]
        nat = p.nature or ("debit" if cls == "자산" else "credit")
        name = acc.get("name") or ""
        for x in p.rows:
            n += 1
            want = x["op"] + (x["dr"] - x["cr"] if nat == "debit" else x["cr"] - x["dr"])
            if x["bal"] != want:
                diffs[f"{p.account} {x['name']} 잔액"] = x["bal"] - want
                msgs.append(f"{p.account} {name} {x['name']}: 잔액 {w(x['bal'])} ≠ 이월 {w(x['op'])} "
                            f"{'+ 차변 - 대변' if nat == 'debit' else '+ 대변 - 차변'} {w(want)}({p.path} {x.get('row') or '?'}행)")
        jp: dict[str, list[int]] = {}
        for (a, pc), v in agg.partner.items():          # 분기 파일끼리 코드 꼴(00101 · 101)이 달라도 한 거래처로 더한다
            if a == p.account:
                s_ = jp.setdefault(_code_key(pc), [0, 0])
                s_[0] += v[0]
                s_[1] += v[1]
        none_key = _code_key("000000")
        no_partner = jp.get(none_key, [0, 0])
        file_codes = {_code_key(x["code"] or "000000") for x in p.rows}
        if (no_partner[0] or no_partner[1]) and none_key not in file_codes:
            jp.pop(none_key)
            if not jp:                                  # 분개장 줄에 거래처가 하나도 없다(내보내기에서 거래처가 빠진 꼴)
                skipped.append(f"{p.account} {name}(분개장 줄에 거래처가 없음)")
                continue
            noted.append(f"{p.account} {name}(분개장에 거래처 없는 줄 차변 {w(no_partner[0])} · 대변 {w(no_partner[1])}, "
                         "원장에 미등록거래처 줄이 없어 코드 있는 거래처만 견줌)")
        if jp and not (file_codes & set(jp)):
            skipped.append(f"{p.account} {name}(파일 거래처 코드가 분개장 코드와 맞지 않음)")
            continue
        for x in p.rows:
            jd, jc = jp.get(_code_key(x["code"] or "000000"), [0, 0])
            if (x["dr"], x["cr"]) != (jd, jc):
                diffs[f"{p.account} {x['name']} 분개장"] = (x["dr"] - jd) - (x["cr"] - jc)
                msgs.append(f"{p.account} {name} {x['name']}: 원장 차변 {w(x['dr'])} · 대변 {w(x['cr'])} ≠ 분개장 차변 {w(jd)} · "
                            f"대변 {w(jc)}({p.path} {x.get('row') or '?'}행)")
        for code, (jd, jc) in jp.items():
            if code not in file_codes and (jd or jc):
                diffs[f"{p.account} {code} 원장에 없음"] = jd - jc
                msgs.append(f"{p.account} {name}: 분개장 거래처 {code} 차변 {w(jd)} · 대변 {w(jc)} 가 원장 파일에 없습니다")
    detail = f"A 꼴 파일 {len(a_files)}개 · 거래처 줄 {n}개"
    if skipped:
        detail += " · 분개장 거래처별 대사를 하지 않은 계정: " + ", ".join(skipped[:6])
    if noted:
        detail += " · " + ", ".join(noted[:6]) + (f" 외 {len(noted) - 6}개" if len(noted) > 6 else "")
    if msgs:
        detail += " · " + " / ".join(msgs[:8]) + (f" 외 {len(msgs) - 8}건" if len(msgs) > 8 else "")
    return check("partner_lines", not diffs, title, detail, diffs)


IS_HEADS = {"rev": r"^(매출액|매출|영업수익)$", "cogs": r"^매출원가$", "gp": r"^매출총(이익|손실)$",
            "sga": r"^판매(비(와|및일반|와일반))?관리비$", "opex": r"^영업비용$", "op": r"^영업(이익|손실)$",
            "noi": r"^영업외수익$", "noe": r"^영업외비용$", "ebt": r"차감전(순)?(이익|손실|손익)$",
            "tax": r"^법인세(등|비용)$", "ni": r"당기순(이익|손실|손익)$"}


def _check_is_footing(is_: list[FsLine]) -> dict:
    """손익계산서 당기 · 전기 열의 머리 줄 산식(11-01 PBC 대조). 구역 머리 줄 = 그 구역 계정 줄 합계(계산 줄이 있는 매출원가는 뺌),
    매출총이익 = 매출액 - 매출원가, 영업이익 = 매출총이익 - 판매비와관리비(또는 매출액 - 영업비용), 법인세차감전이익 = 영업이익 +
    영업외수익 - 영업외비용, 당기순이익 = 법인세차감전이익 - 법인세등. 전기 열은 분개장과 견주는 대사가 없어 이 산식이 유일한 검사다."""
    title = "손익계산서 당기 · 전기 머리 줄 산식"
    msgs, diffs = [], {}
    for col, label in (("cur", "당기"), ("prior", "전기")):
        val = (lambda ln: ln.cur) if col == "cur" else (lambda ln: ln.prior)
        if col == "prior" and not any(val(ln) for ln in is_):
            continue                                       # 첫 사업연도 · 전기 열 없음
        for h in is_:
            if h.kind != "subtotal" or h.section not in IS_SECTIONS or val(h) is None:
                continue
            acc = [ln for ln in is_ if ln.kind == "account" and ln.section == h.section]
            memo = [ln for ln in is_ if ln.kind == "memo" and ln.section == h.section]
            if not acc or memo:
                continue
            s = sum(val(a) or 0 for a in acc)
            if s != val(h):
                diffs[f"{label} {h.section}"] = val(h) - s
                msgs.append(f"{label} {h.section}: 머리 줄 {w(val(h))} ≠ 계정 줄 합계 {w(s)}")
        hv = {k: find_head(is_, pat, col == "prior") for k, pat in IS_HEADS.items()}

        def eq(name, left, right):
            if left is None or right is None:
                return
            if left != right:
                diffs[f"{label} {name}"] = left - right
                msgs.append(f"{label} {name}: {w(left)} ≠ {w(right)}")
        if hv["gp"] is not None and hv["rev"] is not None:
            eq("매출총이익 = 매출액 - 매출원가", hv["gp"], hv["rev"] - (hv["cogs"] or 0))
        if hv["op"] is not None:
            if hv["gp"] is not None and hv["sga"] is not None:
                eq("영업이익 = 매출총이익 - 판매비와관리비", hv["op"], hv["gp"] - hv["sga"])
            elif hv["rev"] is not None and hv["opex"] is not None:
                eq("영업이익 = 영업수익 - 영업비용", hv["op"], hv["rev"] - hv["opex"])
        if hv["ebt"] is not None and hv["op"] is not None:
            eq("법인세차감전이익 = 영업이익 + 영업외수익 - 영업외비용", hv["ebt"], hv["op"] + (hv["noi"] or 0) - (hv["noe"] or 0))
        if hv["ni"] is not None and hv["ebt"] is not None:
            eq("당기순이익 = 법인세차감전이익 - 법인세등", hv["ni"], hv["ebt"] - (hv["tax"] or 0))
    detail = "당기 · 전기 열 머리 줄 산식 " + ("모두 맞음" if not msgs else " / ".join(msgs[:8]) + (f" 외 {len(msgs) - 8}건" if len(msgs) > 8 else ""))
    return check("is_footing", not diffs, title, detail, diffs)


COST_LINE = re.compile(r"^당기(총)?(제품)?(제조|공사)(원가|비용)$")
CONSTRUCTION_COGS = re.compile(r"공사(매출)?원가$")
# 원가 명세서 범위(forms/stdmap.COST_RANGES 와 같다). 제조 · 공사만 손익계산서 계산 줄과 견준다
COST_RANGES = [(500, 600, "제조"), (601, 650, "공사"), (651, 799, "기타")]
WIP_NAMES = {"제조": ("재공품",), "공사": ("미성공사", "미완성")}


def cost_range(code: str) -> str:
    n = c3(code)
    return next((name for lo, hi, name in COST_RANGES if lo <= n <= hi), "기타")


def check_cost_flow(is_: list[FsLine], bs: list[FsLine], cost) -> dict | None:
    """원가 계정(500~799) 합계 대사(11-01 PBC 대조). 손익계산서 매출원가 구역의 「당기제품제조원가 · 당기공사원가」 계산 줄 =
    분개장 원가 계정 합계(마감 · 원가 대체 줄 빼고, 결산 때 저장품 · 원재료로 되돌린 금액도 뺌) + 기초 - 기말 재공품(공사는 미성공사).
    「당기총제조비용 · 당기총공사비용」 줄이면 원가 계정 합계와 바로 견준다. cost 는 {제조 · 공사 · 기타: 합계} 또는 합계 하나.
    제조 · 공사 줄이 둘 다 있으면 줄마다 그 범위(501~600 · 601~650)와 견준다. 줄이 하나인데 원가 계정이 여러 범위에 걸쳐 맞지 않으면
    실패가 아니라 경고다(손익계산서에 다른 원가 줄이 없을 수 있다). 원가 계정 · 계산 줄이 없으면 대사하지 않는다(None).
    계정 사이 배분은 제조원가명세서가 있어야 보므로 보지 않는다."""
    by = cost if isinstance(cost, dict) else {"제조": int(cost or 0)}
    total = sum(by.values())
    if not total:
        return None
    lines = [ln for ln in is_ if ln.kind == "memo" and ln.section == "매출원가" and ln.cur is not None and COST_LINE.search(ln.name)]
    if not lines:
        lines = _construction_cogs(is_, by)
    if not lines:
        return None

    def wip(kinds):
        names = [n for k in kinds for n in WIP_NAMES.get(k, ())]
        got = [ln for ln in bs if ln.kind == "account" and any(n in ln.name for n in names)]
        return sum(ln.prior or 0 for ln in got), sum(ln.cur or 0 for ln in got), bool(got)

    kinds_of = {id(ln): ("공사" if "공사" in ln.name else "제조") for ln in lines}
    split = len({kinds_of[id(ln)] for ln in lines}) > 1
    msgs, diffs = [], {}
    for ln in lines:
        kind = kinds_of[id(ln)]
        scope = [kind] if split else [k for k in ("제조", "공사") if by.get(k)] or [kind]
        base = by.get(kind, 0) if split else total
        o, c, has = wip(scope)
        want = base if "총" in ln.name else base + o - c
        part = f"{ln.label} {w(ln.cur)} · 원가 계정 {'(' + kind + ') ' if split else ''}합계 {w(base)}"
        if "총" not in ln.name and has:
            part += f" + 기초 {w(o)} - 기말 {w(c)} {'·'.join(n for k in scope for n in WIP_NAMES.get(k, ()))} = {w(want)}"
        if ln.cur != want:
            diffs[ln.label] = ln.cur - want
            part += f" · 차이 {w(ln.cur - want)}"
        msgs.append(part)
    detail = "손익계산서 " + " / ".join(msgs)
    multi = sum(1 for k in ("제조", "공사", "기타") if by.get(k)) > 1
    if diffs and not split and multi:
        detail += (" · 원가 계정이 여러 원가 명세서 범위(제조 · 공사 · 기타)에 걸치는데 손익계산서 계산 줄은 하나라 맞추지 못했습니다(경고, "
                   "원가 명세서로 확인합니다)")
        return check("cost_flow", True, "원가 계정 합계 = 손익계산서 당기 제조 · 공사원가", detail, diffs, warn=True)
    if diffs:
        detail += " · 타계정대체가 있으면 제조원가명세서로 확인합니다"
    return check("cost_flow", not diffs, "원가 계정 합계 = 손익계산서 당기 제조 · 공사원가", detail, diffs)


def _construction_cogs(is_: list[FsLine], by: dict) -> list[FsLine]:
    """「당기공사원가」 계산 줄 없이 매출원가 구역에 「도급공사매출원가」 같은 계정 줄만 있는 공사 회사(11-01 평가세트 사본 실행).
    원가 계정이 공사 범위(601~650)뿐이고 그런 계정 줄이 하나일 때만 그 줄을 당기공사원가로 본다. 공사는 제품 재고 단계 없이
    미성공사만 거치므로 공사원가 합계 + 기초 - 기말 미성공사 = 공사매출원가다. 제조는 제품 재고를 한 번 더 거쳐 여기서 보지 않는다."""
    if not by.get("공사") or any(v for k, v in by.items() if k != "공사"):
        return []
    got = [ln for ln in is_ if ln.kind == "account" and ln.section == "매출원가" and ln.cur is not None
           and CONSTRUCTION_COGS.search(ln.name)]
    return got if len(got) == 1 else []


def _check_partners(live_pfs, acc_map, file_sums, n_dup: int = 0, unresolved=(), b_stats=None) -> dict:
    title = "거래처원장 합계 = 재무상태표(현금 101 제외)"
    if not live_pfs and not unresolved:
        return check("partner_match", True, title, "거래처원장 · 계정명세서가 없습니다")
    diffs = {}
    msgs = []
    n = n_ok = 0
    skipped = []
    for p in live_pfs:
        k = p.account
        if c3(k) == CASH:
            skipped.append(k)
            continue
        n += 1
        acc = acc_map.get(k, {"opening": 0, "closing": 0, "name": ""})
        op, cl, check_open = file_sums[p.key]
        dc = cl - acc["closing"]
        do = op - acc["opening"] if check_open else 0
        if dc or do:
            key = k if k not in diffs else f"{k} {p.key.split('/')[-1]}"
            diffs[key] = dc or do
            msgs.append(f"{k} {acc.get('name', '')} 원장 기말 {w(cl)} · 장부 {w(acc['closing'])}"
                        + (f" · 원장 기초 {w(op)} · 장부 {w(acc['opening'])}" if do else ""))
        else:
            n_ok += 1
    detail = f"파일 {n}개 중 {n_ok}개 일치(A 꼴은 기초 · 기말, B 꼴은 기말과 추정 기초 합계)"
    if skipped:
        detail += " · 현금 101 은 대사에서 뺐습니다(현금 원장은 출금 · 입금 전표의 현금 줄이 빠져 잔액이 아닙니다)"
    if n_dup:
        detail += f" · 같은 내용 파일 {n_dup}개는 하나로 셌습니다"
    if b_stats and any(p.form == "B" for p in live_pfs):
        detail += (f" · B 꼴 기초는 기말 − 분개장 거래처별 증감으로 추정했고, 분개장에만 있는 거래처 {b_stats['added']}곳을"
                   " 기말 0 줄로 더했습니다")
        if b_stats["negative"]:
            detail += f"(추정 기초가 계정 잔액과 반대 방향인 거래처 {b_stats['negative']}곳)"
    for p in unresolved:
        diffs[f"계정 못 정함 {p.key.split('/')[-1]}"] = sum(x.get("amount", x.get("bal", 0)) for x in p.rows)
        msgs.append(f"{p.key.split('/')[-1]} 의 계정을 정하지 못했습니다({p.how or '이유 없음'})")
    if msgs:
        detail += " · " + " / ".join(msgs[:8]) + (f" 외 {len(msgs) - 8}건" if len(msgs) > 8 else "")
    return check("partner_match", not diffs, title, detail, diffs)


def _check_tb(tb: list[dict], accounts: list[dict], agg: Agg, loose: list[dict]) -> dict:
    """합계잔액시산표(더존 ERP) ↔ 장부. 분기 분개장이 빠짐없이 이어졌는지 보는 대사다.

    손익 구역 계정은 차변 · 대변 합계(손익대체 포함)가 분개장 합계와 같은지, 재무상태표 구역 계정은 잔액이 장부 기말과
    같은지 본다. 이름으로 잇고 같은 이름이 여러 줄이면(감가상각누계액) 합쳐서 본다. 분개장에 없는 재무상태표 줄(무변동)은
    재무상태표 금액과 견준다.
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    for a in accounts:
        if a["class"] != "손익대체":
            by_name[norm(a["name"])].append(a)
    loose_by: dict[str, int] = defaultdict(int)
    for x in loose:
        loose_by[norm(x["name"])] += x["closing"]
    tb_by: dict[str, dict] = {}
    for r in tb:
        t = tb_by.setdefault(norm(r["name"]), {"dr": 0, "cr": 0, "bal": 0, "pl": r["group"] == "손익"})
        t["dr"] += r["dr_tot"]
        t["cr"] += r["cr_tot"]
        t["bal"] += r["dr_bal"] - r["cr_bal"]
    diffs, msgs = {}, []
    n_ok = 0
    for name, t in tb_by.items():
        accs = by_name.get(name, [])
        if t["pl"]:
            ours = (sum(agg.dr[a["code"]] for a in accs), sum(agg.cr[a["code"]] for a in accs))
            theirs = (t["dr"], t["cr"])
            if ours != theirs:
                diffs[name] = (theirs[0] - ours[0]) or (theirs[1] - ours[1])
                msgs.append(f"{name} 시산표 차변 {w(theirs[0])} · 대변 {w(theirs[1])}, 분개장 {w(ours[0])} · {w(ours[1])}")
                continue
        else:
            ours = sum(a["closing"] for a in accs) + loose_by.get(name, 0)
            if ours != t["bal"]:
                diffs[name] = t["bal"] - ours
                msgs.append(f"{name} 시산표 잔액 {w(t['bal'])}, 장부 {w(ours)}")
                continue
        n_ok += 1
    tb_names = set(tb_by)
    for name, accs in by_name.items():
        if name in tb_names:
            continue
        for a in accs:
            v = a["closing"] if a["class"] in BS_CLASSES else a["debit"] - a["credit"]
            if v:
                diffs[f"{a['code']} {name}"] = v
                msgs.append(f"시산표에 없는 계정 {a['code']} {name} {w(v)}")
    pl_dr = sum(t["dr"] for t in tb_by.values() if t["pl"])
    detail = (f"시산표 계정 {len(tb_by)}개 중 {n_ok}개 일치 · 손익 계정 차변 합계 {w(pl_dr)}"
              " (손익 계정은 손익대체를 포함한 차변 · 대변 합계, 재무상태표 계정은 잔액)")
    if msgs:
        detail += " · " + " / ".join(msgs[:8]) + (f" 외 {len(msgs) - 8}건" if len(msgs) > 8 else "")
    return check("tb_match", not diffs, "합계잔액시산표 = 장부(분개장 이어 붙이기 확인)", detail, diffs)
