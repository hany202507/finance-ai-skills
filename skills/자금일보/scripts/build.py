# -*- coding: utf-8 -*-
"""자금일보: 은행 계좌 거래내역 CSV 3종과 분류규칙.md 로 자금일보 대시보드(HTML)와 자금일보(md)를 만든다.

입력 폴더  bank_accounts.csv · bank_transactions.csv · cash_schedule.csv(선택)
           (fc_ 접두사가 붙은 이름도 읽는다. --계좌 --거래 --예정 으로 파일을 하나씩 줄 수도 있다)
규칙       분류규칙.md 의 「규칙」 표(순서 · 구분 · 찾는 말 · 자금코드 · 비고)와 「예측」 표(선택)
출력       대시보드 HTML 한 파일. 주소 끝 #YYYY-MM-DD 로 날짜를 고른다. 같은 폴더에 자금일보_<기준일>.md
검산       1) 계좌마다 거래 한 줄씩: 직전 잔액 + 입금 - 출금 = 그 줄 잔액
           2) 날마다: 전일 계좌 잔액 합계 + 입금 - 출금(계좌 간 이체 제외) = 당일 계좌 잔액 합계
           3) 계좌 표에 기말 잔액 열이 있으면 마지막 거래 잔액과 대조
           하나라도 1원이 어긋나면 아무것도 쓰지 않고 종료코드 2 로 멈춘다. 입력 오류는 종료코드 1.

python build.py --입력 ../examples --규칙 ../assets/분류규칙_예시.md --출력 out/자금일보_대시보드.html \
    [--기준일 2026-09-30] [--회사 "글로우빔(주)"] [--출처 "은행 거래내역"] [--휴일 2026-10-05,2026-10-09] \
    [--큰출금 30000000] [--평균일수 20] [--예측일수 14] [--md 경로 | --md없음]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
TPL = HERE.parent / "assets" / "template.html"
UNK_IN, UNK_OUT = "기타 입금(확인 필요)", "기타 출금(확인 필요)"
WD = "월화수목금토일"


class InputError(Exception):
    pass


# ───────────────────────────── 입력 ─────────────────────────────
def read_csv(path, **kw):
    last = None
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError as e:
            last = e
    raise InputError(f"{path} 를 읽지 못했다: {last}")


def find(folder, names):
    if folder is None:
        return None
    for n in names:
        p = Path(folder) / n
        if p.exists():
            return p
    return None


def need(df, cols, what):
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise InputError(f"{what} 에 열이 없다: {', '.join(miss)} (있는 열: {', '.join(df.columns)})")


def money(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip().replace({"": "0", "nan": "0", "None": "0"}),
                         errors="raise").fillna(0).round().astype("int64")


def ymd(s):
    return pd.to_datetime(s.astype(str).str.strip()).dt.strftime("%Y-%m-%d")


def load(a):
    p_acc = Path(a.계좌) if a.계좌 else find(a.입력, ["bank_accounts.csv", "fc_bank_accounts.csv"])
    p_tx = Path(a.거래) if a.거래 else find(a.입력, ["bank_transactions.csv", "fc_bank_transactions.csv"])
    p_sch = Path(a.예정) if a.예정 else find(a.입력, ["cash_schedule.csv", "fc_cash_schedule.csv"])
    if not p_acc or not p_acc.exists():
        raise InputError("계좌 파일(bank_accounts.csv)을 찾지 못했다")
    if not p_tx or not p_tx.exists():
        raise InputError("거래 파일(bank_transactions.csv)을 찾지 못했다")

    acc = read_csv(p_acc, dtype=str)
    need(acc, ["account_id", "bank", "account_alias", "account_no"], p_acc.name)
    ob = [c for c in acc.columns if c.startswith("opening_balance")]
    if not ob:
        raise InputError(f"{p_acc.name} 에 기초 잔액 열(opening_balance…)이 없다")
    acc["opening"] = money(acc[ob[0]])
    cb = [c for c in acc.columns if c.startswith("closing_balance")]
    acc["closing"] = money(acc[cb[0]]) if cb else None
    if acc.account_id.duplicated().any():
        raise InputError(f"{p_acc.name} 에 account_id 가 겹친다")

    t = read_csv(p_tx, dtype=str, keep_default_na=False)
    need(t, ["account_id", "tx_date", "description", "counterparty", "deposit", "withdrawal", "balance"], p_tx.name)
    if "tx_time" not in t.columns:
        t["tx_time"] = ""
    t["tx_date"] = ymd(t.tx_date)
    t["tx_time"] = t.tx_time.astype(str).str.strip()
    for c in ("deposit", "withdrawal", "balance"):
        t[c] = money(t[c])
    unknown = sorted(set(t.account_id) - set(acc.account_id))
    if unknown:
        raise InputError(f"계좌 표에 없는 account_id: {', '.join(unknown)}")
    both = t[(t.deposit > 0) & (t.withdrawal > 0)]
    if len(both):
        raise InputError(f"입금과 출금이 한 줄에 같이 있다: {len(both)}줄 (첫 줄 {both.iloc[0].to_dict()})")
    if len(t) and t.tx_date.iloc[0] > t.tx_date.iloc[-1]:  # 최신 거래가 위에 오는 은행 내보내기
        t = t.iloc[::-1]
    t = t.sort_values(["tx_date", "tx_time"], kind="mergesort").reset_index(drop=True)
    alias = dict(zip(acc.account_id, acc.account_alias))
    t["account_alias"] = t.account_id.map(alias)

    if p_sch and p_sch.exists():
        sch = read_csv(p_sch, dtype=str, keep_default_na=False)
        need(sch, ["due_date", "direction", "item", "counterparty", "amount", "account_id"], p_sch.name)
        sch["due_date"] = ymd(sch.due_date)
        sch["amount"] = money(sch.amount)
        if "plan_id" not in sch.columns:
            sch["plan_id"] = ""
        bad = sorted(set(sch.direction) - {"입금", "출금"})
        if bad:
            raise InputError(f"{p_sch.name} direction 은 입금·출금만 쓴다: {bad}")
        unknown = sorted(set(sch.account_id) - set(acc.account_id))
        if unknown:
            raise InputError(f"{p_sch.name} 에 계좌 표에 없는 account_id: {', '.join(unknown)}")
    else:
        sch = pd.DataFrame(columns=["plan_id", "due_date", "direction", "item", "counterparty", "amount", "account_id"])
    return acc, t, sch


def read_rules(path):
    """「규칙」 표는 첫 칸이 숫자인 줄. 「예측」 표는 ## 예측 제목 아래 표."""
    rules, est, sec = [], [], ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#"):
            sec = s.lstrip("#").strip()
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) >= 4 and cells[0].isdigit():
            if cells[1] not in ("입금", "출금", "양쪽"):
                raise InputError(f"규칙 {cells[0]}번 구분은 입금·출금·양쪽 중 하나여야 한다: {cells[1]}")
            words = [w.strip().lower() for w in cells[2].split("·") if w.strip()]
            if not words:
                raise InputError(f"규칙 {cells[0]}번 찾는 말이 비었다")
            rules.append((cells[1], words, cells[3]))
        elif sec.startswith("예측") and len(cells) >= 3 and cells[1] in ("입금", "출금"):
            # 자금코드 이름에 · 가 들어 있으므로(원료·제품 매입) 예측 표는 쉼표로 나눈다
            codes = [w.strip() for w in cells[2].split(",") if w.strip()]
            skip = [w.strip() for w in cells[3].split(",") if w.strip()] if len(cells) > 3 else []
            est.append((cells[0], cells[1], codes, skip))
    if not rules:
        raise InputError(f"{path} 에서 규칙을 못 읽었다(첫 칸이 순서 숫자인 표 줄)")
    return rules, est


# ───────────────────────────── 계산 ─────────────────────────────
def build(a):
    acc, t, sch = load(a)
    RULES, ESTR = read_rules(a.규칙)
    sch = classify_schedule(sch, RULES)
    INTERNAL = a.내부이체코드
    N, LOOK, BIG = a.평균일수, a.예측일수, a.큰출금

    def code(desc, cp, inn):
        side, text = ("입금" if inn > 0 else "출금"), f"{desc} {cp}".lower()
        for dirn, words, name in RULES:  # 처음 맞은 줄 하나만
            if dirn in (side, "양쪽") and any(w in text for w in words):
                return name
        return UNK_IN if inn > 0 else UNK_OUT

    t["code"] = [code(d, c, i) for d, c, i in zip(t.description, t.counterparty, t.deposit)]
    ext = t[t.code != INTERNAL]
    days = sorted(t.tx_date.unique())
    if not days:
        raise InputError("거래가 한 줄도 없다")
    ACC = acc.account_id.tolist()
    OPEN = int(acc.opening.sum())
    CODES = list(dict.fromkeys([n for d_, _, n in RULES if d_ == "입금"] + [n for d_, _, n in RULES if d_ == "양쪽" and n != INTERNAL]
                               + [UNK_IN] + [n for d_, _, n in RULES if d_ == "출금"] + [UNK_OUT]))

    # ── 검산 1: 계좌마다 줄 단위 잔액 연속
    fails = []
    for a_id in ACC:
        prev = int(acc.loc[acc.account_id == a_id, "opening"].iloc[0])
        for r in t[t.account_id == a_id].itertuples():
            exp = prev + int(r.deposit) - int(r.withdrawal)
            if exp != int(r.balance):
                fails.append(f"[줄 잔액] {r.tx_date} {a_id} {r.description}: 직전 {prev:,} + 입금 {int(r.deposit):,} - 출금 {int(r.withdrawal):,}"
                             f" = {exp:,} 인데 잔액 열은 {int(r.balance):,} (차이 {int(r.balance) - exp:,})")
                break  # 계좌마다 첫 어긋남만
            prev = int(r.balance)

    # 계좌별 일말 잔액 (거래 없는 날은 전일 잔액)
    end_acc, cur = {}, dict(zip(acc.account_id, acc.opening))
    for d in days:
        g = t[t.tx_date == d]
        for a_id in ACC:
            ga = g[g.account_id == a_id]
            if len(ga):
                cur[a_id] = int(ga.balance.iloc[-1])
        end_acc[d] = dict(cur)

    # ── 검산 3: 계좌 표의 기말 잔액
    if acc.closing.notna().all():
        for r in acc.itertuples():
            if int(r.closing) != int(end_acc[days[-1]][r.account_id]):
                fails.append(f"[기말 잔액] {r.account_id} 계좌 표 {int(r.closing):,} · 거래 마지막 잔액 {int(end_acc[days[-1]][r.account_id]):,}"
                             f" (차이 {int(r.closing) - int(end_acc[days[-1]][r.account_id]):,})")

    by, prev, checks = {}, OPEN, []
    for k, d in enumerate(days):
        g, ge = t[t.tx_date == d], ext[ext.tx_date == d]
        inn, out, end = int(ge.deposit.sum()), int(ge.withdrawal.sum()), int(sum(end_acc[d].values()))
        # ── 검산 2: 날마다 1원 등식 (계좌 간 이체는 양쪽에서 같이 빠지므로 등식이 그대로 선다)
        diff = end - (prev + inn - out)
        checks.append((d, prev, inn, out, end, diff))
        if diff:
            fails.append(f"[날짜 합계] {d}: 전일 {prev:,} + 입금 {inn:,} - 출금 {out:,} = {prev + inn - out:,} 인데 계좌 잔액 합계는 {end:,}"
                         f" (차이 {diff:,}. 계좌 간 이체 한쪽만 있거나 내부이체 규칙이 한쪽을 놓쳤을 수 있다)")
        gg = ge.groupby("code").agg(i=("deposit", "sum"), o=("withdrawal", "sum"), n=("code", "size"))
        codes = []
        for c in CODES:
            if c in gg.index and (gg.loc[c, "i"] or gg.loc[c, "o"]):
                top = ge[ge.code == c].assign(v=lambda x: x.deposit + x.withdrawal).nlargest(3, "v")
                codes.append({"name": c, "i": int(gg.loc[c, "i"]), "o": int(gg.loc[c, "o"]), "n": int(gg.loc[c, "n"]),
                              "top": [[r.description, int(r.v)] for r in top.itertuples()]})
        big = ge.assign(v=lambda x: x.deposit + x.withdrawal).nlargest(6, "v")
        prev_acc = end_acc[days[k - 1]] if k else dict(zip(acc.account_id, acc.opening))
        accs = [[r.bank, r.account_alias, r.account_no, int(end_acc[d][r.account_id]),
                 int(g[g.account_id == r.account_id].deposit.sum()), int(g[g.account_id == r.account_id].withdrawal.sum()),
                 int(end_acc[d][r.account_id] - prev_acc[r.account_id])] for r in acc.itertuples()]
        # 앞으로 LOOK 일 알려진 큰 출금: 마지막 거래일 이전 날짜는 이후 실제 거래, 그 뒤는 입출금 예정표
        lim = (pd.Timestamp(d) + pd.Timedelta(days=LOOK)).strftime("%Y-%m-%d")
        f1 = ext[(ext.tx_date > d) & (ext.tx_date <= lim) & (ext.withdrawal >= BIG)]
        f1 = f1.groupby(["tx_date", "code"], as_index=False).withdrawal.sum().rename(columns={"tx_date": "dd", "withdrawal": "amt"})
        f2 = sch[(sch.direction == "출금") & (sch.fcode != INTERNAL) & (sch.due_date > d) & (sch.due_date <= lim)] if len(sch) else sch
        f2 = f2.rename(columns={"due_date": "dd", "item": "code", "amount": "amt"})[["dd", "code", "amt"]]
        plan = pd.concat([x for x in (f1, f2) if len(x)] or [f1]).nlargest(6, "amt").sort_values("dd")
        gt = ge.assign(v=lambda x: x.deposit + x.withdrawal).sort_values("v", ascending=False)
        tx = [[r.tx_time[:5], r.account_alias, r.counterparty, r.description, int(r.deposit), int(r.withdrawal), r.code]
              for r in gt.itertuples()]
        by[d] = {"tx": tx, "prev": int(prev), "in": inn, "out": out, "end": int(end), "n": int(len(g)), "codes": codes, "accs": accs,
                 "big": [[r.description, int(r.deposit), int(r.withdrawal), r.code] for r in big.itertuples()],
                 "plan": [[r.dd, r.code, int(r.amt)] for r in plan.itertuples()],
                 "flag": [[r.description, int(r.deposit), int(r.withdrawal), r.code] for r in ge[ge.code.isin([UNK_IN, UNK_OUT])].itertuples()]}
        prev = end
    return acc, t, sch, ext, days, by, checks, fails, RULES, ESTR, OPEN


def classify_schedule(sch, RULES):
    def code(item, cp, dirn):
        text = f"{item} {cp}".lower()
        for d_, words, name in RULES:
            if d_ in (dirn, "양쪽") and any(w in text for w in words):
                return name
        return UNK_IN if dirn == "입금" else UNK_OUT
    sch = sch.copy()
    sch["fcode"] = [code(i, c, d) for i, c, d in zip(sch.item, sch.counterparty, sch.direction)] if len(sch) else []
    return sch


def forecast(acc, sch, ext, days, by, ESTR, a):
    """마지막 거래일 다음 날부터 LOOK 일. 확정 예정은 예정표 그대로, 반복 흐름은 최근 N영업일 평균."""
    N, LOOK, INTERNAL = a.평균일수, a.예측일수, a.내부이체코드
    holi = set(a.휴일)
    base = pd.Timestamp(days[-1])
    fdays = [x.strftime("%Y-%m-%d") for x in pd.date_range(base + pd.Timedelta(days=1), base + pd.Timedelta(days=LOOK))
             if x.weekday() < 5 and x.strftime("%Y-%m-%d") not in holi]
    lastN = ext[ext.tx_date.isin(days[-N:])]
    div = len(days[-N:])
    mdk = lambda x: f"{int(x[5:7])}/{int(x[8:10])}"
    ALIAS = dict(zip(acc.account_id, acc.account_alias))

    def avg(codes, col):
        return int(round(lastN[lastN.code.isin(codes)][col].sum() / div, -5))

    def est_basis(codes, col, by_col):
        g = lastN[lastN.code.isin(codes) & (lastN[col] > 0)]
        tot = int(g[col].sum())
        sh = g.groupby(by_col)[col].sum().sort_values(ascending=False)
        top = ("거래처 비중 " if by_col == "counterparty" else "구성 ") + " · ".join(f"{k} {v / tot * 100:.0f}%" for k, v in sh.head(4).items()) if tot else "실적 없음"
        accs = " · ".join(dict.fromkeys(g.account_alias))
        return accs, f"최근 {div}영업일({mdk(days[-div])}~{mdk(days[-1])}) 실적 {tot:,}원({len(g)}건) ÷ {div}, 10만원 단위 반올림", top

    EST = []
    for name, dirn, codes, skip in ESTR:
        col = "deposit" if dirn == "입금" else "withdrawal"
        EST.append((name, dirn, avg(codes, col), est_basis(codes, col, "counterparty" if len(codes) == 1 else "code"), skip))
    roll = lambda x: next(f for f in fdays + ["2099-12-31"] if f >= x)
    items = {f: [] for f in fdays}
    for r in sch[sch.fcode != INTERNAL].itertuples():
        f = roll(r.due_date)
        if f in items:
            moved = "" if f == r.due_date else f" ({int(r.due_date[5:7])}/{int(r.due_date[8:10])} 휴일→)"
            src = (f"{r.plan_id} " if r.plan_id else "") + "입출금 예정표"
            items[f].append([r.item + moved, r.direction, int(r.amount), "예정", ALIAS[r.account_id],
                             src + (f" · 원래 예정일 {mdk(r.due_date)}(휴일)" if moved else ""), r.counterparty])
    for f in fdays:
        for name, dirn, amt, (ea, eb, ec), skip in EST:
            if skip and any(any(w in it[0] for w in skip) for it in items[f]):
                continue
            items[f].append([name, dirn, amt, "추정", ea, eb, ec])
    fc, bal = [], by[days[-1]]["end"]
    for f in fdays:
        fi = sum(it[2] for it in items[f] if it[1] == "입금")
        fo = sum(it[2] for it in items[f] if it[1] == "출금")
        bal += fi - fo
        fc.append([f, fi, fo, bal, sorted(items[f], key=lambda it: (it[1] != "입금", -it[2]))])
    return fc, fdays, [e[0] for e in EST]


def finish_by(days, by):
    def top_items(d):
        c = by[d]["codes"]
        ti = sorted([x for x in c if x["i"]], key=lambda x: -x["i"])[:3]
        to = sorted([x for x in c if x["o"]], key=lambda x: -x["o"])[:3]
        return [[x["name"], x["i"]] for x in ti], [[x["name"], x["o"]] for x in to]

    for k, d in enumerate(days):
        by[d]["recent"] = [[x, by[x]["in"], by[x]["out"], *top_items(x)] for x in days[max(0, k - 9):k + 1]]
        w = days[max(0, k - 5):k]
        by[d]["avg5_in"] = sum(by[x]["in"] for x in w) / len(w) if w else 0
        by[d]["avg5_out"] = sum(by[x]["out"] for x in w) / len(w) if w else 0


# ───────────────────────────── HTML ─────────────────────────────
STRIP_CAL = '''
<div class="dbar">
  <div class="dpick" id="dpick">
    <button type="button" class="dbtn" id="dbtn" aria-haspopup="dialog" aria-expanded="false" aria-controls="dpop">
      <span class="dlab">기준일</span><b id="dval">-</b><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
    </button>
    <div class="dpop" id="dpop" role="dialog" aria-label="기준일 고르기" hidden>
      <div class="dhd"><button type="button" class="mnav" id="mprev" aria-label="이전 달">&lsaquo;</button><b id="mlab"></b><button type="button" class="mnav" id="mnext" aria-label="다음 달">&rsaquo;</button></div>
      <div class="cal" id="cal"></div>
      <ul class="lgd"><li><i style="--c:var(--a1)"></i>순유입</li><li><i style="--c:var(--risk)"></i>순유출</li><li><i style="--c:var(--line)"></i>자료 없음</li></ul>
    </div>
  </div>
  <div class="dstep"><button type="button" id="dprev">&lsaquo; 이전 영업일</button><button type="button" id="dnext">다음 영업일 &rsaquo;</button></div>
  <span class="dmeta" id="dmeta"></span>
  <button type="button" class="dpdf" id="dpdf" title="인쇄 창에서 대상: PDF로 저장"><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>PDF 다운로드</button>
</div>
<section class="kpis" id="kpis"></section>
'''
STRIP_TABLES = '''
<section class="card">
  <div class="chd"><div><div class="ck" style="--ct:var(--a1t)">ACCOUNTS</div>
    <h2>계좌별 마감 잔액</h2><p class="cs">계좌마다 그날 마지막 거래의 잔액. 증감은 전일 대비</p></div></div>
  <div class="tw"><table><thead><tr><th>은행</th><th>용도</th><th>계좌번호</th><th class="num">입금</th><th class="num">출금</th><th class="num">마감 잔액</th><th class="num">전일 대비</th></tr></thead>
  <tbody id="acct"></tbody></table></div>
</section>
<section class="card">
  <div class="chd"><div><div class="ck" style="--ct:var(--a2t)">TOP 6</div>
    <h2>오늘 큰 거래</h2><p class="cs">금액이 큰 순서. 확인이 필요한 거래는 아래에 따로 모읍니다</p></div></div>
  <div class="tw"><table><thead><tr><th>적요</th><th>자금코드</th><th class="num">입금</th><th class="num">출금</th></tr></thead>
  <tbody id="bigt"></tbody></table></div>
  <div class="tw"><table><thead><tr><th>확인 필요 거래</th><th>자금코드</th><th class="num">입금</th><th class="num">출금</th></tr></thead>
  <tbody id="flagt"></tbody></table></div>
</section>
'''
CAL_CSS = '''
.dbar{display:flex; align-items:center; gap:10px; flex-wrap:wrap}
.dpick{position:relative}
.dbtn,.dstep button{appearance:none; font:inherit; cursor:pointer; color:var(--ink); background:var(--card);
  border:1px solid var(--line); border-radius:10px; box-shadow:var(--sh-sm)}
.dbtn{display:flex; align-items:center; gap:10px; padding:9px 14px}
.dbtn .dlab{font-size:11px; font-weight:800; letter-spacing:.12em; color:var(--a1t)}
.dbtn b{font-size:15px; font-weight:800}
.dbtn svg{color:var(--muted)}
.dbtn:hover,.dbtn[aria-expanded="true"]{border-color:var(--a1)}
.dstep{display:flex; gap:6px}
.dstep button{padding:9px 12px; font-size:13px; font-weight:700; color:var(--body)}
.dstep button:hover:not(:disabled){border-color:var(--a1); color:var(--a1t)}
.dstep button:disabled{color:var(--faint); cursor:not-allowed; box-shadow:none}
.dmeta{margin-left:auto; font-size:12.5px; color:var(--muted)}
.dpop{position:absolute; top:calc(100% + 8px); left:0; z-index:30; width:336px; max-width:calc(100vw - 32px); background:var(--card);
  border:1px solid var(--line); border-radius:14px; padding:14px 14px 12px; box-shadow:var(--sh), 0 18px 40px -14px var(--faint)}
.dpop[hidden]{display:none}
.dhd{display:flex; align-items:center; justify-content:space-between; margin-bottom:8px}
.dhd b{font-size:15px; font-weight:800}
.mnav{appearance:none; width:32px; height:32px; border-radius:8px; border:1px solid var(--line2); background:var(--tint);
  font:inherit; font-size:18px; line-height:1; color:var(--ink); cursor:pointer}
.mnav:hover{border-color:var(--a1)}
.cal{display:grid; grid-template-columns:repeat(7,1fr); gap:4px}
.cal .dw{font-size:11px; font-weight:800; color:var(--faint); text-align:center; padding:2px 0 4px}
.cal button{appearance:none; border:1px solid var(--line2); background:var(--tint); border-radius:8px; height:38px;
  font:inherit; font-size:13.5px; font-weight:750; color:var(--ink); cursor:pointer; position:relative}
.cal button i{position:absolute; left:50%; bottom:4px; width:5px; height:5px; margin-left:-2.5px; border-radius:50%; background:var(--c)}
.cal button:hover:not(:disabled){border-color:var(--a1)}
.cal button[aria-pressed="true"]{background:var(--a1); color:var(--card); border-color:var(--a1)}
.cal button[aria-pressed="true"] i{background:var(--card)}
.cal button:disabled{background:transparent; border-color:transparent; color:var(--line); cursor:not-allowed}
.dpop .lgd{margin-top:10px}
.txw{max-height:300px; overflow:auto; margin-top:2px; border:1px solid var(--line2); border-radius:8px; background:var(--card)}
.txt{width:100%; border-collapse:collapse; font-size:12.5px; color:var(--body)}
.txt th{position:sticky; top:0; background:var(--tint); font-size:11px; font-weight:800; color:var(--muted); text-align:left; padding:6px 8px; border-bottom:1px solid var(--line2); white-space:nowrap}
.txt td{padding:6px 8px; border-top:0; border-bottom:1px solid var(--line2); vertical-align:top; white-space:normal; word-break:keep-all; overflow-wrap:anywhere}
.txt tr:last-child td{border-bottom:0}
.txt .tm{color:var(--faint); white-space:nowrap; font-variant-numeric:tabular-nums}
.txt .ds{color:var(--ink); font-weight:650}
.txt .cp{color:var(--muted); font-size:11.5px}
.txt .cd{display:inline-block; margin-top:2px; font-size:11px; color:var(--a1t)}
.txt .am{text-align:right; white-space:nowrap; font-weight:750; font-variant-numeric:tabular-nums}
.txt .am.pos{color:var(--a1t)} .txt .am.neg{color:var(--riskT)}
.txt .acm{display:none}
.txt .kd.kdm{display:none}
@media (max-width:640px){.txt .ac,.txt .kc{display:none} .txt .kd.kdm{display:inline-block; margin-right:5px; vertical-align:1px} .txt .acm{display:block} .txw{max-height:340px}}
.txt .kd{display:inline-block; font-size:10.5px; font-weight:800; padding:1px 6px; border-radius:6px; white-space:nowrap}
.txt .kd.plan{background:var(--a1); color:var(--card)} .txt .kd.est{border:1px solid var(--line); color:var(--muted)}
.dpdf{appearance:none; display:flex; align-items:center; gap:7px; font:inherit; font-size:13px; font-weight:800; cursor:pointer;
  color:var(--card); background:var(--a1); border:1px solid var(--a1); border-radius:10px; padding:9px 14px; box-shadow:var(--sh-sm)}
.dpdf:hover{background:var(--a1t); border-color:var(--a1t)}
@page{size:A4 landscape; margin:9mm}
@media print{.dstep,.dpdf,.dpop,.dbtn svg{display:none !important} .dbtn{border:0; box-shadow:none; padding:0}
  .kpis,.calrow .kpis{grid-template-columns:repeat(4,1fr) !important}
  .row{grid-template-columns:1fr 1fr !important}
  .dmeta{margin-left:16px} .dtl .ph{display:none}}
'''
JS = r'''
var DATA = __DATA__;
var CFG = __CFG__;
function eok(v){return (v/1e8).toFixed(1)+"억";}
function md(d){return (+d.slice(5,7))+"/"+(+d.slice(8,10));}
function current(){var h=decodeURIComponent(location.hash.slice(1));return DATA.by[h]?h:(DATA.by[CFG.def]?CFG.def:DATA.days[DATA.days.length-1]);}
var SEL=current(), VM=SEL.slice(0,7), WD="일월화수목금토";
function ymd(y,m,d){return y+"-"+(m<10?"0":"")+m+"-"+(d<10?"0":"")+d;}
function longd(d){return d.slice(0,4)+"년 "+(+d.slice(5,7))+"월 "+(+d.slice(8,10))+"일 ("+WD[new Date(d).getDay()]+")";}
function drawCal(){
  var y=+VM.slice(0,4), m=+VM.slice(5,7), el=document.getElementById("cal"), out="";
  document.getElementById("mlab").textContent=y+"년 "+m+"월";
  for(var k=0;k<7;k++) out+='<div class="dw">'+WD[k]+'</div>';
  var first=new Date(y,m-1,1).getDay(), last=new Date(y,m,0).getDate();
  for(var b=0;b<first;b++) out+='<span></span>';
  for(var day=1;day<=last;day++){
    var d=ymd(y,m,day), o=DATA.by[d];
    if(o){var net=o.end-o.prev;
      out+='<button type="button" data-d="'+d+'" aria-pressed="'+(d===SEL)+'" aria-label="'+longd(d)+'">'+day+'<i style="--c:var('+(net>=0?"--a1":"--risk")+')"></i></button>';}
    else out+='<button type="button" disabled aria-label="'+longd(d)+' 자료 없음">'+day+'</button>';}
  el.innerHTML=out;
  el.querySelectorAll("button[data-d]").forEach(function(bt){bt.addEventListener("click",function(){go(bt.dataset.d);closePop();});});
}
function openPop(){VM=SEL.slice(0,7);drawCal();document.getElementById("dpop").hidden=false;document.getElementById("dbtn").setAttribute("aria-expanded","true");}
function closePop(){document.getElementById("dpop").hidden=true;document.getElementById("dbtn").setAttribute("aria-expanded","false");}
function shiftMonth(n){var y=+VM.slice(0,4), m=+VM.slice(5,7)+n; if(m<1){m=12;y--;} if(m>12){m=1;y++;} VM=y+"-"+(m<10?"0":"")+m; drawCal();}
function go(d){if(!DATA.by[d])return; history.replaceState(null,"","#"+d); render(d);}
document.getElementById("dbtn").addEventListener("click",function(e){e.stopPropagation();document.getElementById("dpop").hidden?openPop():closePop();});
document.getElementById("mprev").addEventListener("click",function(e){e.stopPropagation();shiftMonth(-1);});
document.getElementById("mnext").addEventListener("click",function(e){e.stopPropagation();shiftMonth(1);});
document.getElementById("dpop").addEventListener("click",function(e){e.stopPropagation();});
document.addEventListener("click",closePop);
document.addEventListener("keydown",function(e){if(e.key==="Escape")closePop();});
document.getElementById("dprev").addEventListener("click",function(){var i=DATA.days.indexOf(SEL);if(i>0)go(DATA.days[i-1]);});
document.getElementById("dnext").addEventListener("click",function(){var i=DATA.days.indexOf(SEL);if(i<DATA.days.length-1)go(DATA.days[i+1]);});
document.getElementById("dmeta").textContent="자료 "+DATA.days[0]+" ~ "+DATA.days[DATA.days.length-1]+" · 영업일 "+DATA.days.length+"일 · "+CFG.src;
addEventListener("hashchange",function(){SEL=current();render(SEL);});
/* PDF: 브라우저 인쇄 창에서 「PDF로 저장」. 파일 이름이 기준일로 잡히게 제목을 잠시 바꾼다 */
document.getElementById("dpdf").addEventListener("click",function(e){e.stopPropagation();closePop();
  var t0=document.title; document.title=CFG.file+"_자금일보_"+SEL;
  var back=function(){document.title=t0;removeEventListener("afterprint",back);}; addEventListener("afterprint",back);
  window.print();});
function sign(v){return (v>=0?"+":"")+eok(v);}
function fcTable(list){
  return '<div class="txw"><table class="txt"><thead><tr><th class="kc">구분</th><th class="ac">계좌</th><th>항목 · 근거</th><th style="text-align:right">금액</th></tr></thead><tbody>'
    +list.map(function(it){var inn=it[1]==="입금";
      var kd='<span class="kd '+(it[3]==="예정"?"plan":"est")+'">'+it[3]+'</span>';
      return '<tr><td class="kc">'+kd+'</td><td class="ac">'+esc(it[4])+'</td><td><div class="ds">'+kd.replace('class="kd ','class="kd kdm ')+esc(it[0])+'</div><div class="cp acm">'+esc(it[4])+'</div>'
        +'<div class="cp">'+esc(it[6])+'</div><div class="cp">'+esc(it[5])+'</div></td>'
        +'<td class="am '+(inn?"pos":"neg")+'">'+(inn?"+":"-")+won(it[2])+'</td></tr>';}).join("")
    +'</tbody></table></div>';}
function txTable(list,showCode){
  return '<div class="txw"><table class="txt"><thead><tr><th>시각</th><th class="ac">계좌</th><th>적요 · 거래처</th><th style="text-align:right">금액</th></tr></thead><tbody>'
    +list.map(function(x){var inn=x[4]>0;
      return '<tr><td class="tm">'+x[0]+'</td><td class="ac">'+esc(x[1])+'</td><td><div class="ds">'+esc(x[3])+'</div><div class="cp">'+esc(x[2])+'</div><div class="cp acm">'+esc(x[1])+'</div>'
        +(showCode?'<span class="cd">'+esc(x[6])+'</span>':'')+'</td><td class="am '+(inn?"pos":"neg")+'">'+(inn?"+":"-")+won(inn?x[4]:x[5])+'</td></tr>';}).join("")
    +'</tbody></table></div>';}
function render(d){
  SEL=d; var o=DATA.by[d];
  var di=DATA.days.indexOf(d), mon=d.slice(0,7), MD=DATA.days.filter(function(x){return x.slice(0,7)===mon;});
  document.getElementById("dval").textContent=longd(d);
  document.getElementById("dprev").disabled=di<=0; document.getElementById("dnext").disabled=di>=DATA.days.length-1;
  document.getElementById("c1t").textContent=(+d.slice(5,7))+"월 마감 잔액 추이";
  document.getElementById("chipv").textContent=won(o.end)+"원";
  document.getElementById("chipm").textContent=md(d)+" 마감 · 거래 "+o.n+"건";
  var net=o.end-o.prev, fromOpen=o.prev-DATA.by[MD[0]].prev;
  function vs(v,a){if(!a) return "직전 영업일 없음"; var r=v/a-1; return "최근 5영업일 평균 대비 <b>"+(r>=0?"+":"")+(r*100).toFixed(0)+"%</b>";}
  renderKPI("kpis",[
    {ax:"시작",label:"전일 마감 잔액",value:eok(o.prev),unit:"",color:"var(--a2)",colorT:"var(--a2t)",desc:"월초 대비 <b>"+sign(fromOpen)+"</b>"},
    {ax:"들어온 돈",label:"당일 입금",value:eok(o.in),unit:"",color:"var(--a1)",colorT:"var(--a1t)",desc:vs(o.in,o.avg5_in)},
    {ax:"나간 돈",label:"당일 출금",value:eok(o.out),unit:"",color:"var(--risk)",colorT:"var(--riskT)",desc:vs(o.out,o.avg5_out)},
    {ax:"마감",label:"당일 마감 잔액",value:eok(o.end),unit:"",color:net>=0?"var(--a1)":"var(--risk)",colorT:net>=0?"var(--a1t)":"var(--riskT)",
     desc:'전일 대비 <b style="color:'+(net>=0?"var(--a1t)":"var(--riskT)")+'">'+sign(net)+'</b>'}]);
  var J=MD, ends=J.map(function(x){return DATA.by[x].end;});
  CHART.line({host:"p1",tip:"t1",dtl:"d1",cats:J.map(function(x){return x.slice(8,10);}),series:[{name:"마감 잔액",color:"--a1",data:ends}],
    label:(+d.slice(5,7))+"월 마감 잔액 추이",detail:function(i){var q=DATA.by[J[i]];
      return {title:md(J[i])+" 자금",pairs:[["시작",won(q.prev)],["입금",won(q.in)],["출금",won(q.out)],["마감",won(q.end)]]};}});
  legend("g1",[{name:CFG.nacc+"개 계좌 마감 잔액",color:"--a1",type:"ln"}]);
  document.getElementById("b1").textContent=md(d);
  var rows=o.codes.map(function(c){return {name:c.name,a:c.o,b:c.i,right:(c.i-c.o>=0?"+":"-")+man(Math.abs(c.i-c.o)),
    rightColor:c.i-c.o>=0?"--a1t":"--riskT",right2:c.n+"건"};});
  CHART.hbar({host:"p2",tip:"t2",dtl:"d2",rows:rows,colorA:"--risk",colorB:"--a1",nameA:"나간 돈",nameB:"들어온 돈",mL:132,
    label:"오늘 자금코드별 유입·유출",detail:function(i){var c=o.codes[i];
      return {title:md(d)+" "+c.name,pairs:[["들어온 돈",won(c.i)],["나간 돈",won(c.o)],["건수",c.n+"건"]],
        note:txTable(o.tx.filter(function(x){return x[6]===c.name;}),false)};}});
  legend("g2",[{name:"들어온 돈",color:"--a1"},{name:"나간 돈",color:"--risk"}]);
  document.getElementById("b2").textContent=o.codes.length+"개 코드";
  var F=DATA.fc, wd="일월화수목금토";
  if(F.length){
  CHART.bars({host:"p3",tip:"t3",dtl:"d3",cats:F.map(function(f){return md(f[0])+"("+wd[new Date(f[0]).getDay()]+")";}),
    series:[{name:"입금 예측",color:"--a1",data:F.map(function(f){return f[1];})},{name:"출금 예측",color:"--risk",data:F.map(function(f){return f[2];})}],
    label:"앞으로 일자별 입출금 예측",
    detail:function(i){var f=F[i];
      return {title:md(f[0])+" 예상 입출금 "+f[4].length+"건",pairs:[["입금 예측",won(f[1]),"pos"],["출금 예측",won(f[2]),"neg"],["예상 마감 잔액",won(f[3])]],
        note:fcTable(f[4])};}});
  legend("g3",[{name:"입금 예측",color:"--a1"},{name:"출금 예측",color:"--risk"}]);
  var fnet=F[F.length-1][3]-DATA.fc_base;
  document.getElementById("b3").textContent="예측 기간 순액 "+sign(fnet);}
  else document.getElementById("b3").textContent="예측 없음";
  var R=o.recent;
  CHART.bars({host:"p4",tip:"t4",dtl:"d4",cats:R.map(function(r){return md(r[0]);}),
    series:[{name:"입금",color:"--a1",data:R.map(function(r){return r[1];})},{name:"출금",color:"--risk",data:R.map(function(r){return r[2];})}],
    label:"최근 10영업일 입금·출금",detail:function(i){var r=R[i], q=DATA.by[r[0]];
      return {title:md(r[0])+" 거래 "+q.tx.length+"건",pairs:[["입금",won(r[1]),"pos"],["출금",won(r[2]),"neg"],["순액",(r[1]-r[2]>=0?"+":"")+won(r[1]-r[2])]],
        note:txTable(q.tx,true)};}});
  legend("g4",[{name:"입금",color:"--a1"},{name:"출금",color:"--risk"}]);
  document.getElementById("b4").textContent="~"+md(d);
  document.getElementById("acct").innerHTML=o.accs.map(function(a){
    return '<tr><td>'+esc(a[0])+'</td><td>'+esc(a[1])+'</td><td>'+esc(a[2])+'</td><td class="num pos">'+(a[4]?won(a[4]):"")+'</td><td class="num neg">'+(a[5]?won(a[5]):"")+'</td><td class="num">'+won(a[3])+'</td><td class="num '+(a[6]>=0?"pos":"neg")+'">'+(a[6]>=0?"+":"")+won(a[6])+'</td></tr>';}).join("")
    +'<tr><td><b>합계</b></td><td></td><td></td><td></td><td></td><td class="num"><b>'+won(o.end)+'</b></td><td class="num"><b>'+(net>=0?"+":"")+won(net)+'</b></td></tr>';
  document.getElementById("bigt").innerHTML=o.big.map(function(r){
    return '<tr><td>'+esc(r[0])+'</td><td>'+esc(r[3])+'</td><td class="num pos">'+(r[1]?won(r[1]):"")+'</td><td class="num neg">'+(r[2]?won(r[2]):"")+'</td></tr>';}).join("");
  document.getElementById("flagt").innerHTML=o.flag.length?o.flag.map(function(r){
    return '<tr><td>'+esc(r[0])+'</td><td>'+esc(r[3])+'</td><td class="num pos">'+(r[1]?won(r[1]):"")+'</td><td class="num neg">'+(r[2]?won(r[2]):"")+'</td></tr>';}).join(""):'<tr><td colspan="4">없음</td></tr>';
  ["d1","d2"].forEach(function(id){placeholder(id,"그래프를 누르면 금액이 나옵니다");});
  ["d3","d4"].forEach(function(id){placeholder(id,"막대를 누르면 그날의 항목이 나옵니다");});
}
'''


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(a, acc, t, days, by, fc, est_names, RULES, OPEN, n_flag, default_day):
    nacc = len(acc)
    mdk = lambda x: f"{int(x[5:7])}/{int(x[8:10])}"
    banks = " · ".join(dict.fromkeys(acc.bank))
    company = a.회사
    est_txt = (f"{'·'.join(est_names)} 은 최근 {min(a.평균일수, len(days))}영업일 평균으로 잡았습니다" if est_names
               else "예정표에 있는 항목만 잡았습니다")
    fill = {
        "TITLE": esc(f"{company} 자금일보"),
        "EYEBROW": esc(f"{company} · {a.출처} {nacc}개 계좌"),
        "SUBTITLE": "",
        "CHIP_LABEL": f"{nacc}개 계좌 마감 잔액", "CHIP_VALUE": '<span id="chipv">-</span>', "CHIP_META": '<span id="chipm">-</span>',
        "CARD1_EN": "BALANCE", "CARD1_TITLE": '<span id="c1t">마감 잔액 추이</span>', "CARD1_SUB": f"{nacc}개 계좌 합계. 점을 누르면 그날의 입금·출금이 나옵니다", "CARD1_BADGE": '<span id="b1">-</span>',
        "CARD2_EN": "TODAY", "CARD2_TITLE": "오늘 자금코드별 유입·유출", "CARD2_SUB": "계좌 간 이체는 뺐습니다. 행을 누르면 그 코드의 거래가 한 건씩 나옵니다", "CARD2_BADGE": '<span id="b2">-</span>',
        "CARD3_EN": f"FORECAST · NEXT {a.예측일수} DAYS", "CARD3_TITLE": f"앞으로 {a.예측일수}일 일자별 입출금 예측",
        "CARD3_SUB": esc(f"{mdk(days[-1])} 마감 기준. 예정표 항목은 그대로, {est_txt}. 휴일에 잡힌 예정은 다음 영업일로 옮깁니다. 막대를 누르면 그날 항목과 근거가 나옵니다"),
        "CARD3_BADGE": '<span id="b3">-</span>',
        "CARD4_EN": "LAST 10 DAYS", "CARD4_TITLE": "최근 10영업일 입금·출금", "CARD4_SUB": "막대를 누르면 그날 거래가 금액 순으로 한 건씩 나옵니다", "CARD4_BADGE": '<span id="b4">-</span>',
        "BASIS": esc(f"{a.출처} {len(t):,}건({days[0]}~{days[-1]}, {banks} {nacc}개 계좌). 시작 잔액은 {nacc}개 계좌 기초 합계 {OPEN:,}원. "
                     f"계좌마다 거래 한 줄씩 직전 잔액 + 입금 - 출금 = 잔액이 맞고, 날마다 전일 잔액 + 입금 - 출금 = 계좌 잔액 합계가 {len(days)}영업일 전부 1원까지 맞는다. "
                     f"계좌 간 이체는 양쪽에서 같이 빠지므로 등식이 그대로 선다. 자금코드는 {Path(a.규칙).name} 표({len(RULES)}줄)로 붙였다."),
        "LIMITS": esc(f"분류규칙 어느 줄에도 안 맞은 거래 {n_flag}건은 기타 입금·출금(확인 필요)으로 따로 모았다. "
                      f"검산은 금액이 맞는지만 본다. 자금코드가 이 회사 거래 성격에 맞는지는 사람이 판단한다. "
                      f"예측의 예정 항목은 입력한 예정표 그대로이고, 추정 항목은 최근 평균이라 정산 주기와 계절성을 반영하지 않는다."
                      + (f" {a.메모}" if a.메모 else "")),
        "DRAW": "*/ render(current()); /*",
    }
    html = TPL.read_text(encoding="utf-8")
    for k, v in fill.items():
        html = html.replace("{{" + k + "}}", v)
    html = re.sub(r"\s*<p class=\"hs\"></p>", "", html, count=1)
    left = re.findall(r"\{\{\w+\}\}", html)
    if left:
        raise RuntimeError(f"틀에 채우지 못한 {{…}}: {left}")
    html = html.replace('<section class="kpis" id="kpis"></section>', STRIP_CAL, 1)
    html = html.replace('<footer class="foot">', STRIP_TABLES + '\n<footer class="foot">', 1)
    html = html.replace('</style>', CAL_CSS + '</style>', 1)
    DATA = {"days": days, "by": by, "fc": fc, "fc_base": by[days[-1]]["end"]}
    CFG = {"def": default_day, "src": a.출처, "file": re.sub(r"[\\/:*?\"<>|()\s]", "", company) or "회사", "nacc": nacc}
    js = JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("</", "<\\/")) \
           .replace("__CFG__", json.dumps(CFG, ensure_ascii=False).replace("</", "<\\/"))
    html = html.replace("function drawAll(){", js + "\nfunction drawAll(){", 1)
    head = '<!doctype html>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    return head + html


# ───────────────────────────── 자금일보 md ─────────────────────────────
def w(v):
    return f"{int(v):,}"


def sw(v):
    return ("+" if v >= 0 else "") + f"{int(v):,}"


def render_md(a, acc, t, ext, sch, days, by, fc, d):
    o = by[d]
    k = days.index(d)
    net = o["end"] - o["prev"]
    dt = pd.Timestamp(d)
    L = [f"# {a.회사} 자금일보 {d}({WD[dt.weekday()]})", ""]
    L += [f"{len(acc)}개 계좌 마감 잔액 {w(o['end'])}원, 전일 대비 {sw(net)}원({'+' if net >= 0 else ''}{net / 1e8:.1f}억).", ""]
    L += ["## 잔액", "", "| 전일 잔액 | 입금 | 출금 | 당일 잔액 |", "|--:|--:|--:|--:|",
          f"| {w(o['prev'])} | {w(o['in'])} | {w(o['out'])} | {w(o['end'])} |", "",
          f"검산: {w(o['prev'])} + {w(o['in'])} - {w(o['out'])} = {w(o['end'])} (차이 0). 입금·출금은 계좌 간 이체를 뺀 금액이다.", ""]
    L += ["## 계좌별 잔액", "", "| 은행 | 용도 | 계좌번호 | 입금 | 출금 | 마감 잔액 | 전일 대비 |", "|---|---|---|--:|--:|--:|--:|"]
    for r in o["accs"]:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {w(r[4])} | {w(r[5])} | {w(r[3])} | {sw(r[6])} |")
    L += ["", "입금·출금 칸은 계좌 간 이체를 포함한 그 계좌의 실제 입출금이다.", ""]
    L += ["## 자금코드별 입금·출금", "", "| 자금코드 | 건수 | 입금 | 출금 |", "|---|--:|--:|--:|"]
    for c in o["codes"]:
        L.append(f"| {c['name']} | {c['n']} | {w(c['i'])} | {w(c['o'])} |")
    L.append(f"| 합계 | {sum(c['n'] for c in o['codes'])} | {w(o['in'])} | {w(o['out'])} |")
    L += [""]
    # 앞으로 큰 출금
    lim = (dt + pd.Timedelta(days=a.예측일수)).strftime("%Y-%m-%d")
    rows = []
    if d == days[-1]:
        for f in fc:
            for it in f[4]:
                if it[1] == "출금" and it[3] == "예정" and it[2] >= a.큰출금:
                    rows.append((f[0], it[0], it[2], it[4]))
    else:
        f1 = ext[(ext.tx_date > d) & (ext.tx_date <= lim) & (ext.withdrawal >= a.큰출금)]
        for r in f1.groupby(["tx_date", "code"], as_index=False).withdrawal.sum().itertuples():
            rows.append((r.tx_date, f"{r.code} (실제 거래)", int(r.withdrawal), ""))
        if len(sch):
            for r in sch[(sch.direction == "출금") & (sch.fcode != a.내부이체코드) & (sch.due_date > d) & (sch.due_date <= lim) & (sch.amount >= a.큰출금)].itertuples():
                rows.append((r.due_date, r.item, int(r.amount), dict(zip(acc.account_id, acc.account_alias))[r.account_id]))
    rows.sort(key=lambda x: x[0])
    L += [f"## 앞으로 {a.예측일수}일 큰 출금 ({w(a.큰출금)}원 이상)", ""]
    if rows:
        L += ["| 날짜 | 항목 | 금액 | 계좌 |", "|---|---|--:|---|"] + [f"| {x[0]} | {x[1]} | {w(x[2])} | {x[3]} |" for x in rows]
        if d == days[-1]:
            L += ["", "휴일에 잡힌 예정은 다음 영업일로 옮겨 적었다(항목 끝 「휴일→」)."]
    else:
        L.append("없음")
    L += ["", "## 확인 필요 거래", ""]
    fl = [x for x in o["tx"] if x[6] in (UNK_IN, UNK_OUT)]
    if fl:
        L += ["| 시각 | 계좌 | 적요 | 거래처 | 입금 | 출금 |", "|---|---|---|---|--:|--:|"]
        L += [f"| {x[0]} | {x[1]} | {x[3]} | {x[2]} | {w(x[4])} | {w(x[5])} |" for x in fl]
        L += ["", "분류규칙 어느 줄에도 안 맞았다. 비슷한 코드에 억지로 넣지 않았다. 새 규칙이 필요하면 분류규칙.md 에 줄을 더하고 다시 돌린다."]
    else:
        L.append("없음")
    L.append("")
    return "\n".join(L)


# ───────────────────────────── 실행 ─────────────────────────────
def parse(argv=None):
    p = argparse.ArgumentParser(description="은행 거래내역 CSV 로 자금일보 대시보드를 만든다")
    p.add_argument("--입력", help="bank_accounts.csv · bank_transactions.csv · cash_schedule.csv 가 있는 폴더")
    p.add_argument("--계좌"); p.add_argument("--거래"); p.add_argument("--예정")
    p.add_argument("--규칙", required=True, help="분류규칙.md")
    p.add_argument("--출력", required=True, help="대시보드 HTML 경로")
    p.add_argument("--기준일", help="대시보드를 처음 열 때 보이는 날짜, 자금일보 md 의 날짜. 기본은 마지막 거래일")
    p.add_argument("--회사", default="회사")
    p.add_argument("--출처", default="은행 거래내역", help="화면에 적을 데이터 출처")
    p.add_argument("--휴일", default="", help="예측 기간의 평일 휴일. 2026-10-05,2026-10-09 처럼 쉼표로, 또는 한 줄에 하나씩 적은 파일")
    p.add_argument("--큰출금", type=int, default=30_000_000)
    p.add_argument("--평균일수", type=int, default=20)
    p.add_argument("--예측일수", type=int, default=14)
    p.add_argument("--내부이체코드", default="계좌 간 이체")
    p.add_argument("--메모", default="", help="대시보드 한계 칸 끝에 붙일 문장")
    p.add_argument("--md", help="자금일보 md 경로. 기본은 출력 폴더의 자금일보_<기준일>.md")
    p.add_argument("--md없음", action="store_true")
    a = p.parse_args(argv)
    if not a.입력 and not (a.계좌 and a.거래):
        p.error("--입력 폴더 또는 --계좌 · --거래 파일을 준다")
    h = a.휴일.strip()
    if h and Path(h).exists():
        h = ",".join(x.strip() for x in Path(h).read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#"))
    a.휴일 = [pd.Timestamp(x.strip()).strftime("%Y-%m-%d") for x in h.split(",") if x.strip()]
    return a


def main(argv=None):
    a = parse(argv)
    try:
        acc, t, sch, ext, days, by, checks, fails, RULES, ESTR, OPEN = build(a)
        if fails:
            print("검산 FAIL. 자금일보를 만들지 않았다.")
            for f in fails[:30]:
                print("  " + f)
            if len(fails) > 30:
                print(f"  외 {len(fails) - 30}건")
            return 2
        fc, fdays, est_names = forecast(acc, sch, ext, days, by, ESTR, a)
        finish_by(days, by)
        d = a.기준일 or days[-1]
        if d not in by:
            raise InputError(f"기준일 {d} 에 거래가 없다. 자료 기간 {days[0]} ~ {days[-1]}")
    except InputError as e:
        print(f"입력 오류: {e}")
        return 1
    n_flag = int(t.code.isin([UNK_IN, UNK_OUT]).sum())
    out = Path(a.출력)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(a, acc, t, days, by, fc, est_names, RULES, OPEN, n_flag, d), encoding="utf-8")
    if not a.md없음:
        mp = Path(a.md) if a.md else out.parent / f"자금일보_{d}.md"
        mp.write_text(render_md(a, acc, t, ext, sch, days, by, fc, d), encoding="utf-8")
    o = by[d]
    print(f"검산 PASS. {len(acc)}개 계좌 · 거래 {len(t):,}건 · {len(days)}영업일({days[0]} ~ {days[-1]}) 전부 1원까지 맞음")
    print(f"규칙 {len(RULES)}줄 · 자금코드별 건수 {t.code.value_counts().to_dict()}")
    print(f"{d}: 전일 {o['prev']:,} + 입금 {o['in']:,} - 출금 {o['out']:,} = {o['end']:,}")
    print(f"{d} 확인 필요 {len(o['flag'])}건: {o['flag']}")
    print(f"전체 확인 필요 {n_flag}건")
    print(f"저장: {out}" + ("" if a.md없음 else f" · {Path(a.md) if a.md else out.parent / f'자금일보_{d}.md'}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
