"""더존 ERP 꼴 읽기: 분개장 10열(7자 코드), 계정명세서(BIFF xls, 계정 블록), 합계잔액시산표(xls).

corptax-impl `engine/intake/journal_parser.py` · `tools/oracle_account_detail.py` 에서 옮겨 고쳤다(corptax 를 import 하지 않는다).

분개장 열: 승인일 · 승인번호 · 차변금액 · 차변계정과목 · 대변계정과목 · 대변금액 · 적요 · 거래처코드 · 거래처명 · 작성일.
- 한 행에 차변 또는 대변 한쪽만 있다. 계정과목은 `[8260000]도서인쇄비` 꼴이다.
- 분기마다 파일이 따로 오고 승인번호는 날짜마다 1부터 다시 매긴다. 이어 붙여도 전표 키(승인일, 승인번호)가 겹치지 않는다.
- 끝의 `합계` 줄은 파일 합계 대조에만 쓴다.

7자 계정코드 = 계정 3자 + 세분류 4자. 재무제표(계정별) · 합계잔액시산표 · 계정명세서는 계정 단위(뒤 4자 0000)로 나온다.
그래서 장부 계정은 `앞 3자 + 0000` 으로 묶고(7자 그대로, 3자로 줄이지 않는다), 원래 코드는 줄의 `sub_account` 에 둔다.
class 는 위하고와 같은 표로 앞 3자 범위로 정한다(CONTRACT.md 3절 · 13절).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .journal import Journal, Line, mark
from .partners import PartnerFile, digest
from .xlsxread import compact, date_text, n0, num, text

HEAD = ("승인일", "승인번호", "차변금액", "차변계정과목", "대변계정과목", "대변금액")
ACC = re.compile(r"^\[(\d{5,8})\]\s*(.*)$")
PL_CODE = "4000000"


def family(code: str) -> str:
    """7자 코드의 계정 단위 코드(앞 3자 + 0000). 7자가 아니면 그대로."""
    return code[:3] + "0000" if len(code) == 7 and code.isdigit() else code


def is_journal_head(head: list[str]) -> bool:
    return all(k in head for k in HEAD)


# ---------------------------------------------------------------- 분개장

def parse_journal(rows: list[list]) -> Journal:
    head = [compact(x) for x in rows[0]]
    ix = {k: head.index(k) for k in head if k}

    def get(r, key):
        i = ix.get(key)
        return r[i] if i is not None and i < len(r) else None

    lines: list[Line] = []
    total = None
    for r in rows[1:]:
        r = list(r)
        d = date_text(get(r, "승인일"))
        if d is None:
            first = text(r[0] if r else None)
            if compact(first).startswith("합계"):
                total = {"debit": n0(get(r, "차변금액")), "credit": n0(get(r, "대변금액")), "count": None}
            continue
        dr_acc, cr_acc = text(get(r, "차변계정과목")), text(get(r, "대변계정과목"))
        if dr_acc:
            m, debit, credit, side = ACC.match(dr_acc), n0(get(r, "차변금액")), 0, "차변"
        elif cr_acc:
            m, debit, credit, side = ACC.match(cr_acc), 0, n0(get(r, "대변금액")), "대변"
        else:
            continue
        if not m:
            continue
        code, name = m.group(1), m.group(2).strip()
        lines.append(Line(date=d, no=text(get(r, "승인번호")), kind=side, account=family(code), account_name=name,
                          debit=debit, credit=credit, partner_code=text(get(r, "거래처코드")),
                          partner=text(get(r, "거래처명")), memo_code="", memo=text(get(r, "적요")), sub_account=code))
    j = Journal(lines=lines, total_row=total, five=False, pl_code=PL_CODE, source="douzone_erp")
    mark(j)
    return j


# ---------------------------------------------------------------- 계정명세서(블록)

SKIP_PREFIX = ("작성기간", "회사명", "회계단위")
PARTNER_HEADS = ("거래처", "금융거래처", "계정과목")


@dataclass
class Block:
    title: str
    partner_header: str = ""          # 거래처 · 금융거래처 · 계정과목
    lines: list[dict] = field(default_factory=list)    # code, name, memo, amount
    total: int | None = None

    @property
    def by_account(self) -> bool:
        return self.partner_header == "계정과목"


def _cell(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return text(v)


def is_detail_rows(rows: list[list]) -> bool:
    """계정명세서 블록 꼴: 앞쪽에 `코드 | 거래처(금융거래처 · 계정과목)` 머리 줄이 있고 `계` 줄이 있다."""
    head = False
    for r in rows[:40]:
        r = list(r) + [None] * 2
        if compact(_cell(r[0])) == "코드" and compact(_cell(r[1])) in PARTNER_HEADS:
            head = True
            break
    return head and any(r and compact(_cell(r[0])) == "계" for r in rows)


def parse_blocks(rows: list[list]) -> list[Block]:
    """제목 줄(0열 빈칸, 4열 계정명) → 머리 줄(코드 · 거래처) → 거래처 줄 → 계 줄. 쪽이 바뀌면 머리 줄이 다시 나온다."""
    blocks: list[Block] = []
    cur: Block | None = None
    for raw in rows:
        r = list(raw) + [None] * (7 - len(raw))
        c0, c1, c4 = _cell(r[0]), _cell(r[1]), r[4]
        rest = [_cell(x) for j, x in enumerate(r[:7]) if j != 4]
        if not c0 and isinstance(c4, str) and c4.strip() and not any(rest):
            t = c4.strip()
            if not compact(t).startswith(SKIP_PREFIX):
                cur = Block(title=compact(t))
                blocks.append(cur)
            continue
        if cur is None or compact(c0).startswith(SKIP_PREFIX):
            continue
        if compact(c0) == "코드":
            cur.partner_header = compact(c1)
            continue
        if compact(c0) == "계":
            cur.total = n0(c4)
            continue
        amt = num(c4)
        if not c0 and amt is None:
            continue
        if not cur.partner_header:
            continue
        cur.lines.append({"code": c0, "name": c1, "memo": _cell(r[3]), "amount": amt or 0})
    return blocks


def blocks_to_files(path: str, blocks: list[Block]) -> list[PartnerFile]:
    """블록 하나를 B 꼴 PartnerFile 하나로. 계정은 계정과목 블록이면 줄의 7자 코드로, 거래처 블록이면 제목 이름으로
    build 가 분개장 계정 이름에서 찾는다(hint_name). 기말 금액만 있다."""
    out = []
    for i, b in enumerate(blocks):
        pf = PartnerFile(path=path, form="B", hint=None, hint_name=b.title, part=f"{i + 1} {b.title}")
        if b.by_account:
            codes = {family(x["code"]) for x in b.lines if re.fullmatch(r"\d{7}", x["code"])}
            rows = [{"account": family(x["code"]), "account_name": x["name"] or b.title, "code": "", "name": x["name"],
                     "amount": x["amount"]} for x in b.lines]
            if len(codes) == 1:
                pf.account, pf.how = codes.pop(), "계정명세서 계정과목 코드"
            pf.account_level = True
        else:
            rows = [{"account": "", "account_name": b.title, "code": x["code"], "name": x["name"], "amount": x["amount"]}
                    for x in b.lines]
        pf.rows = rows
        s = sum(x["amount"] for x in rows)
        if b.total is not None and b.total != s:
            pf.notes.append(f"블록 {b.title} 의 계 줄 {b.total:,} 와 줄 합계 {s:,} 가 다릅니다")
        pf.digest = digest([(b.title, x["code"], x["name"], x["amount"]) for x in rows])
        out.append(pf)
    return out


# ---------------------------------------------------------------- 합계잔액시산표

def is_tb_rows(rows: list[list]) -> bool:
    return any("합계잔액시산표" in compact(_cell(c)) for r in rows[:5] for c in (r or []))


def parse_tb(rows: list[list]) -> list[dict]:
    """계정 줄만: {name, group, dr_bal, dr_tot, cr_tot, cr_bal}. group 은 `<<자산>>` 같은 큰 구역(자산 · 부채 · 자본 · 손익).
    열: 차변 잔액 · 차변 합계 · 계정과목 · 대변 합계 · 대변 잔액."""
    out = []
    group = ""
    started = False
    for r in rows:
        r = list(r) + [None] * 5
        name = compact(_cell(r[2]))
        if not started:
            started = compact(_cell(r[0])) == "잔액" and compact(_cell(r[4])) == "잔액"
            continue
        if not name:
            continue
        m = re.fullmatch(r"<<(.+)>>", name)
        if m:
            group = m.group(1)
            continue
        if name.startswith(("[", "<")) or name == "합계":
            continue
        out.append({"name": name, "group": group, "dr_bal": n0(r[0]), "dr_tot": n0(r[1]), "cr_tot": n0(r[3]),
                    "cr_bal": n0(r[4])})
    return out
