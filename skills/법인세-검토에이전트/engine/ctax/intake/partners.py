"""거래처원장 잔액(A 꼴 6열)과 계정명세서(B 꼴 7열) 읽기. 더존 ERP 계정명세서 블록은 douzone.py 가 B 꼴로 바꾼다.

A 꼴: Code · 거래처 · 전기(월)이월 · 차변 · 대변 · 잔액. 계정코드는 파일 안에 없고 파일 이름(`_10100_`)에만 있다.
  그래서 이름의 코드는 힌트로만 쓰고, 파일 차변 · 대변 합계가 분개장 그 계정 합계와 맞는지로 확인한다.
  맞지 않으면 차변 · 대변 합계가 같은 계정을 분개장에서 찾는다(현금 101 은 원래 맞지 않는다).
  잔액 부호는 계정 성격대로다(잔액 = 이월 + 차 − 대 이면 차변 성격, 이월 + 대 − 차 이면 대변 성격).
B 꼴: 코드 · 계정과목명 · 적요 · 코드 · 거래처명 · 금액 · 비고. 기말 금액만 있다.
  계정은 파일 이름이 아니라 파일 안 첫 코드 열로 정한다(이름과 내용이 다른 `_2` 파일이 있다). 한 파일에 계정이 여럿이면
  계정마다 PartnerFile 을 하나씩 만든다. 기초는 build 가 (기말 − 분개장 거래처별 순증감)으로 추정한다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .xlsxread import compact, n0, num, text


@dataclass
class PartnerFile:
    path: str
    form: str                      # A · B
    hint: str | None               # 파일 이름 계정코드 힌트
    rows: list[dict] = field(default_factory=list)   # A: code, name, op, dr, cr, bal / B: account, code, name, amount
    total: dict | None = None
    account: str | None = None
    how: str = ""                  # 계정을 정한 방법
    nature: str | None = None      # A 꼴 잔액 성격 debit · credit
    digest: str = ""
    duplicate_of: str | None = None
    notes: list[str] = field(default_factory=list)
    hint_name: str | None = None   # 계정 이름 힌트(더존 계정명세서 블록 제목)
    part: str = ""                 # 한 파일 안의 조각(블록 · 계정) 표시
    account_level: bool = False    # 거래처가 아니라 계정 단위 줄(거래처코드가 모두 빈 B 꼴, 계정과목 블록)

    @property
    def key(self) -> str:
        """파일 · 조각을 가리키는 이름(대사 차이 표시 · 중복 표시에 쓴다)."""
        return f"{self.path}#{self.part}" if self.part else self.path


def digest(rows) -> str:
    h = hashlib.sha1()
    for r in rows:
        h.update(repr(tuple(r)).encode("utf-8"))
    return h.hexdigest()


def parse_a(path: str, rows: list[list], hint: str | None) -> PartnerFile:
    pf = PartnerFile(path=path, form="A", hint=hint)
    body = []
    for r in rows[1:]:
        r = list(r) + [None] * 6
        first = text(r[0])
        if first == "" and all(x in (None, "") for x in r[1:6]):
            continue
        if compact(first).startswith("합계"):
            pf.total = {"op": n0(r[2]), "dr": n0(r[3]), "cr": n0(r[4]), "bal": num(r[5])}
            continue
        body.append({"code": first, "name": text(r[1]), "op": n0(r[2]), "dr": n0(r[3]), "cr": n0(r[4]),
                     "bal": n0(r[5])})
    pf.rows = body
    pf.digest = digest([(x["code"], x["name"], x["op"], x["dr"], x["cr"], x["bal"]) for x in body])
    deb = all(x["bal"] == x["op"] + x["dr"] - x["cr"] for x in body)
    cre = all(x["bal"] == x["op"] + x["cr"] - x["dr"] for x in body)
    if deb and not cre:
        pf.nature = "debit"
    elif cre and not deb:
        pf.nature = "credit"
    elif not deb and not cre:
        pf.nature = None
        pf.notes.append("행마다 잔액 = 이월 ± 증감 검산이 맞지 않습니다")
    return pf


def parse_b(path: str, rows: list[list]) -> list[PartnerFile]:
    """B 꼴 한 파일 → 계정마다 PartnerFile. 계정코드가 빈 줄은 바로 앞 계정에 붙인다."""
    body = []
    last = ""
    for r in rows[1:]:
        r = list(r) + [None] * 7
        if all(x in (None, "") for x in r[:7]):
            continue
        acc = text(r[0]) or last
        last = acc
        body.append({"account": acc, "account_name": text(r[1]), "code": text(r[3]), "name": text(r[4]),
                     "amount": n0(r[5])})
    accs = list(dict.fromkeys(x["account"] for x in body if x["account"]))
    out = []
    if not accs:
        pf = PartnerFile(path=path, form="B", hint=None, rows=body, how="계정을 정하지 못함")
        pf.digest = digest([(x["account"], x["code"], x["name"], x["amount"]) for x in body])
        return [pf]
    for acc in accs:
        part = [x for x in body if x["account"] == acc]
        pf = PartnerFile(path=path, form="B", hint=None, rows=part, account=acc,
                         how="파일 안 코드 열" if len(accs) == 1 else f"파일 안 코드 열(한 파일에 계정 {len(accs)}개)",
                         part="" if len(accs) == 1 else acc)
        pf.account_level = all(not x["code"] for x in part)
        pf.digest = digest([(x["account"], x["code"], x["name"], x["amount"]) for x in part])
        out.append(pf)
    return out
