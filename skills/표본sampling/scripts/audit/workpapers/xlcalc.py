"""조서 엑셀의 `_검산` 수식을 엔진이 다시 계산한다(R4, 2026-10-05).

openpyxl 로 저장한 조서는 엑셀이 계산하기 전이라 수식 결과가 없다. wp.check 는 그런 줄을 건너뛰므로,
`python -m audit wp check` 는 이 모듈로 수식을 직접 계산해 엔진 기대값과 맞춘다. 엑셀을 열 필요가 없다.

조서 생성기가 쓰는 수식만 계산한다: 숫자 · 문자열 · 셀 참조(시트 이름 포함, $ 허용) · 범위,
+ - * / & 와 비교(= <> < > <= >=), 함수 SUM · ABS · IF(앞 조건만 보고 한쪽만 계산) · AND · OR · COUNTIF · SUMIF · ROUND · MIN · MAX.
그 밖의 수식은 Unsupported 를 올리고 그 검산 줄은 계산하지 않은 것으로 보고한다(결과를 지어내지 않는다).

  verify(path) -> [{"label", "formula", "expected", "got", "ok"}]   ok 는 True · False · None(계산 못 함)
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries

CHECK_SHEET = "_검산"


class Unsupported(Exception):
    pass


TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<ref>(?:'(?:[^']|'')+'|[A-Za-z_가-힣][\w가-힣.]*)?!?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?
           |(?:'(?:[^']|'')+'|[A-Za-z_가-힣][\w가-힣.]*)!\$?[A-Z]{1,3}:\$?[A-Z]{1,3})
  | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<func>[A-Z][A-Z0-9.]*)\(
  | (?P<op><>|<=|>=|[-+*/&=<>(),:%])
""", re.VERBOSE)


def _tokens(s: str):
    pos, out = 0, []
    while pos < len(s):
        m = TOKEN.match(s, pos)
        if not m:
            raise Unsupported(f"읽을 수 없는 수식 조각: {s[pos:pos + 15]}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        text = m.group(kind)
        if kind == "ref" and "!" not in text and not re.fullmatch(r"\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?", text):
            raise Unsupported(f"이름 참조는 계산하지 않음: {text}")
        out.append((kind, text))
    return out


class Calc:
    def __init__(self, path: Path):
        self.wb = load_workbook(path, data_only=False)
        self.memo: dict[tuple, object] = {}
        self.stack: set[tuple] = set()

    # ------------------------------------------------------------ 셀
    def cell(self, sheet: str, ref: str):
        key = (sheet, ref.replace("$", ""))
        if key in self.memo:
            return self.memo[key]
        if key in self.stack:
            raise Unsupported(f"순환 참조: {sheet}!{ref}")
        if sheet not in self.wb.sheetnames:
            raise Unsupported(f"없는 시트: {sheet}")
        v = self.wb[sheet][key[1]].value
        if isinstance(v, str) and v.startswith("="):
            self.stack.add(key)
            try:
                v = self.formula(v, sheet)
            finally:
                self.stack.discard(key)
        self.memo[key] = v
        return v

    def _split(self, text: str, sheet: str):
        if "!" in text:
            sh, ref = text.rsplit("!", 1)
            sh = sh[1:-1].replace("''", "'") if sh.startswith("'") else sh
            return sh, ref.replace("$", "")
        return sheet, text.replace("$", "")

    def rng(self, text: str, sheet: str) -> list:
        sh, ref = self._split(text, sheet)
        if sh not in self.wb.sheetnames:
            raise Unsupported(f"없는 시트: {sh}")
        if re.fullmatch(r"[A-Z]{1,3}:[A-Z]{1,3}", ref):
            a, b = ref.split(":")
            ref = f"{a}1:{b}{self.wb[sh].max_row}"
        if ":" not in ref:
            return [self.cell(sh, ref)]
        c1, r1, c2, r2 = range_boundaries(ref)
        return [self.cell(sh, f"{get_column_letter(c)}{r}") for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]

    # ------------------------------------------------------------ 수식 → 나무 → 값
    def formula(self, f: str, sheet: str):
        return self.ev(parse(f), sheet)

    def ev(self, n, sheet: str):
        k = n[0]
        if k in ("num", "str"):
            return n[1]
        if k == "ref":
            return self.cell(*self._split(n[1], sheet))
        if k == "range":
            raise Unsupported("범위를 값으로 씀")
        if k == "neg":
            return -_num(self.ev(n[1], sheet))
        if k == "bin":
            op, a, b = n[1], self.ev(n[2], sheet), self.ev(n[3], sheet)
            if op == "&":
                return _text(a) + _text(b)
            if op in ("=", "<>", "<", ">", "<=", ">="):
                return _compare(a, b, op)
            a, b = _num(a), _num(b)
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if b == 0:
                raise Unsupported("0 으로 나눔")
            return a / b
        if k == "func":
            return self._call(n[1], n[2], sheet)
        raise Unsupported(f"모르는 마디: {k}")

    def _vals(self, n, sheet: str) -> list:
        if n[0] == "range":
            return self.rng(n[1], sheet)
        return [self.ev(n, sheet)]

    def _call(self, name: str, args: list, sheet: str):
        if name == "IF":
            cond = self.ev(args[0], sheet)
            if isinstance(cond, str):
                raise Unsupported("IF 조건이 문자열")
            if cond:
                return self.ev(args[1], sheet) if len(args) > 1 else True
            return self.ev(args[2], sheet) if len(args) > 2 else False
        if name in ("AND", "OR"):
            vs = [bool(_num(v)) for a in args for v in self._vals(a, sheet)]
            return all(vs) if name == "AND" else any(vs)
        if name == "SUM":
            return sum(v for a in args for v in self._vals(a, sheet) if isinstance(v, (int, float)) and not isinstance(v, bool))
        if name in ("MIN", "MAX"):
            vs = [v for a in args for v in self._vals(a, sheet) if isinstance(v, (int, float)) and not isinstance(v, bool)]
            return (min if name == "MIN" else max)(vs) if vs else 0
        if name == "ABS":
            return abs(_num(self.ev(args[0], sheet)))
        if name == "ROUND":
            return round(_num(self.ev(args[0], sheet)), int(_num(self.ev(args[1], sheet))) if len(args) > 1 else 0)
        if name == "COUNTIF":
            crit = self.ev(args[1], sheet)
            return sum(1 for v in self._vals(args[0], sheet) if _match(v, crit))
        if name == "SUMIF":
            crit = self.ev(args[1], sheet)
            cv = self._vals(args[0], sheet)
            sv = self._vals(args[2], sheet) if len(args) > 2 else cv
            return sum(s for c, s in zip(cv, sv) if _match(c, crit) and isinstance(s, (int, float)) and not isinstance(s, bool))
        raise Unsupported(f"계산하지 않는 함수: {name}")


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, text=None):
        tok = self.peek()
        if text is not None and tok[1] != text:
            raise Unsupported(f"'{text}' 가 있어야 함")
        self.i += 1
        return tok

    def expr(self):
        a = self.concat()
        k, t = self.peek()
        if k == "op" and t in ("=", "<>", "<", ">", "<=", ">="):
            self.take()
            return ("bin", t, a, self.concat())
        return a

    def concat(self):
        a = self.add()
        while self.peek() == ("op", "&"):
            self.take()
            a = ("bin", "&", a, self.add())
        return a

    def add(self):
        a = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            a = ("bin", op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            a = ("bin", op, a, self.unary())
        return a

    def unary(self):
        k, t = self.peek()
        if k == "op" and t in ("+", "-"):
            self.take()
            v = self.unary()
            return ("neg", v) if t == "-" else v
        return self.primary()

    def primary(self):
        k, t = self.take()
        if k == "num":
            return ("num", float(t) if ("." in t or "e" in t.lower()) else int(t))
        if k == "str":
            return ("str", t[1:-1].replace('""', '"'))
        if k == "ref":
            return ("range", t) if ":" in t.split("!")[-1] else ("ref", t)
        if k == "op" and t == "(":
            v = self.expr()
            self.take(")")
            return v
        if k == "func":
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    args.append(self.expr())
                    if self.peek() == ("op", ","):
                        self.take()
                        continue
                    break
            self.take(")")
            return ("func", t, args)
        raise Unsupported(f"읽을 수 없는 부분: {t}")


def parse(f: str):
    p = _Parser(_tokens(f[1:] if f.startswith("=") else f))
    n = p.expr()
    if p.i != len(p.t):
        raise Unsupported(f"수식 끝을 읽지 못함: {f}")
    return n


def _num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    raise Unsupported(f"숫자가 아닌 값으로 계산: {v!r}")


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _compare(a, b, op: str) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        a, b = _text(a).lower(), _text(b).lower()
    else:
        a, b = _num(a), _num(b)
    return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _match(v, crit) -> bool:
    if isinstance(crit, str):
        m = re.match(r"(<>|<=|>=|<|>|=)(.*)", crit)
        if m:
            op, rhs = m.groups()
            if rhs == "" and op in ("<>", "="):          # 「"<>"」 는 빈 칸이 아닌 칸, 「"="」 는 빈 칸(엑셀과 같다)
                blank = v is None or (isinstance(v, str) and v == "")
                return not blank if op == "<>" else blank
            try:
                return isinstance(v, (int, float)) and _compare(v, float(rhs), op)
            except ValueError:
                return _compare(_text(v), rhs, op)
        if "*" in crit or "?" in crit:
            return isinstance(v, str) and fnmatch.fnmatchcase(v.lower(), crit.lower())
        return _text(v).lower() == crit.lower()
    if v is None or isinstance(v, str):
        return False
    return _num(v) == _num(crit)


def verify(path: Path) -> list[dict]:
    """`_검산` 시트의 줄마다 수식을 계산해 엔진 기대값과 맞춘다."""
    calc = Calc(Path(path))
    if CHECK_SHEET not in calc.wb.sheetnames:
        return []
    ws = calc.wb[CHECK_SHEET]
    out = []
    for r in range(2, ws.max_row + 1):
        label, formula, expected = (ws.cell(r, c).value for c in (1, 2, 3))
        if not label:
            continue
        item = {"label": label, "formula": formula, "expected": expected, "got": None, "ok": None}
        try:
            got = calc.cell(CHECK_SHEET, f"B{r}")
            item["got"] = got
            if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
                item["ok"] = abs(got - expected) <= 0.5
            elif expected is not None:
                item["ok"] = _text(got) == _text(expected)
        except Unsupported as e:
            item["error"] = str(e)
        out.append(item)
    return out
