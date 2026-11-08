"""검증 워크북 수식을 엑셀 없이 다시 계산해 엔진 값과 칸마다 맞춰 보고, 엔진 값을 수식 칸의 저장값으로 넣는다.

검증 워크북은 회계사가 엑셀에서 계산을 따라가도록 수식으로 잇는다(2026-11-09). 수식이 엔진과 다른 값을 내면
위하고 업로드 파일(엔진 값)과 검증 파일 화면이 달라지므로 만들 때마다 여기서 다시 계산해 본다.

쓸 수 있는 함수는 FUNCS 뿐이다. 모두 엑셀 2007 부터 있다. 2026-11-08 처럼 엑셀 2016 에 없는 함수(MAXIFS)가
들어가면 여기서 멈춘다. 숫자는 Decimal 로 계산한다(엔진과 같다). 엑셀의 부동소수 계산과 다를 수 있는 곳은
실물 파일을 엑셀로 다시 계산해 따로 본다.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import zipfile
from bisect import bisect_right
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from openpyxl.utils import column_index_from_string

FUNCS = ("ROUND", "IF", "SUM", "SUMIF", "SUMIFS", "COUNTIF")
TOL = Decimal("1e-9")
D0 = Decimal(0)


class FormulaError(ValueError):
    pass


_TOK = re.compile(r"""\s*(?:
   (?P<str>"(?:[^"]|"")*")
  |(?P<ref>(?:'(?:[^']|'')+'!)?\$?[A-Z]{1,3}\$?[0-9]+(?::\$?[A-Z]{1,3}\$?[0-9]+)?)
  |(?P<num>[0-9]+(?:\.[0-9]+)?)
  |(?P<func>[A-Z][A-Z0-9]*)\(
  |(?P<op><>|<=|>=|[-+*/=<>(),])
)""", re.X)
_CELL = re.compile(r"\$?([A-Z]{1,3})\$?([0-9]+)")
_CMP = ("=", "<>", "<", ">", "<=", ">=")


def tokens(text):
    out, i = [], 0
    while i < len(text):
        if text[i:].strip() == "":
            break
        m = _TOK.match(text, i)
        if not m or m.end() == i:
            raise FormulaError(f"읽지 못하는 수식 조각: {text[i:i + 20]!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


def _ref(text):
    sheet = None
    if text.startswith("'"):
        q = text.index("'!", 1)
        sheet, text = text[1:q].replace("''", "'"), text[q + 2:]
    parts = []
    for p in text.split(":"):
        m = _CELL.fullmatch(p)
        parts.append((int(m.group(2)), column_index_from_string(m.group(1))))
    if len(parts) == 1:
        return ("ref", sheet, *parts[0])
    (r1, c1), (r2, c2) = parts
    if r2 < r1 or c2 < c1:
        raise FormulaError(f"범위가 거꾸로다: {text}")
    return ("rng", sheet, r1, c1, r2, c2)


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, v):
        k, x = self.take()
        if (k, x) != ("op", v):
            raise FormulaError(f"'{v}' 가 와야 하는데 {x!r}")

    def is_op(self, *ops):
        k, x = self.peek()
        return k == "op" and x in ops

    def expr(self):
        a = self.add()
        if self.is_op(*_CMP):
            op = self.take()[1]
            return ("cmp", op, a, self.add())
        return a

    def add(self):
        a = self.mul()
        while self.is_op("+", "-"):
            op = self.take()[1]
            a = ("bin", op, a, self.mul())
        return a

    def mul(self):
        a = self.unary()
        while self.is_op("*", "/"):
            op = self.take()[1]
            a = ("bin", op, a, self.unary())
        return a

    def unary(self):
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        if self.is_op("+"):
            self.take()
            return self.unary()
        return self.atom()

    def atom(self):
        k, x = self.take()
        if k == "num":
            return ("num", Decimal(x))
        if k == "str":
            return ("str", x[1:-1].replace('""', '"'))
        if k == "ref":
            return _ref(x)
        if k == "func":
            if x not in FUNCS:
                raise FormulaError(f"{x} 는 쓰지 않는다(쓸 수 있는 함수: {', '.join(FUNCS)})")
            args = []
            if not self.is_op(")"):
                args.append(self.expr())
                while self.is_op(","):
                    self.take()
                    args.append(self.expr())
            self.expect(")")
            return ("call", x, args)
        if (k, x) == ("op", "("):
            e = self.expr()
            self.expect(")")
            return e
        raise FormulaError(f"수식이 여기서 끊겼다: {x!r}")


def parse(text):
    p = _Parser(tokens(text))
    e = p.expr()
    if p.i != len(p.t):
        raise FormulaError(f"수식 끝에 남은 조각: {p.t[p.i:]}")
    return e


def _norm(v):
    if v is None or isinstance(v, (bool, Decimal, str)):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, dt.datetime):
        return v.date()
    return v


def _num(v):
    if v is None:
        return D0
    if isinstance(v, bool):
        return Decimal(int(v))
    if isinstance(v, Decimal):
        return v
    raise FormulaError(f"숫자가 아닌 값 {v!r} 으로 계산했다")


def _truthy(v):
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        return v != 0
    raise FormulaError(f"참 · 거짓이 아닌 조건 {v!r}")


def _compare(a, b, op):
    if a is None:
        a = "" if isinstance(b, str) else D0
    if b is None:
        b = "" if isinstance(a, str) else D0
    if isinstance(a, bool):
        a = Decimal(int(a))
    if isinstance(b, bool):
        b = Decimal(int(b))
    if isinstance(a, str) and isinstance(b, str):
        a, b = a.casefold(), b.casefold()
    elif isinstance(a, str) or isinstance(b, str):
        if op in ("=", "<>"):
            return op == "<>"
        a, b = (1, 0) if isinstance(a, str) else (0, 1)     # 엑셀은 글자를 숫자보다 크게 본다
    return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _round(x, n):
    q = Decimal(1).scaleb(-int(n))
    r = abs(x).quantize(q, rounding=ROUND_HALF_UP)
    return r if x >= 0 else -r


_CRIT = re.compile(r"^(<=|>=|<>|<|>|=)(.*)$", re.S)


def _key(v):
    if isinstance(v, str):
        return ("s", v.casefold())
    if isinstance(v, Decimal):
        return ("n", v)
    if isinstance(v, dt.date):
        return ("d", v)
    return None


def _matcher(crit):
    """SUMIF · COUNTIF 조건. 글자 조건의 * ? 는 엑셀에서 와일드카드라 검증 워크북 값에 쓰지 않는다(build_workbook._text)."""
    if isinstance(crit, str):
        m = _CRIT.match(crit)
        if m:
            op, rhs = m.groups()
            try:
                rv = Decimal(rhs)
                return lambda v: isinstance(v, Decimal) and _compare(v, rv, op)
            except ArithmeticError:
                return lambda v: isinstance(v, str) and _compare(v, rhs, op)
        k = _key(crit)
        return lambda v: _key(v) == k
    if crit is None:
        raise FormulaError("빈 칸을 SUMIF 조건으로 썼다")
    k = _key(crit)
    return lambda v: _key(v) == k


class Book:
    """openpyxl 워크북(저장 전)의 수식을 계산한다. 앞 행부터 계산하면 SUMIF 누계를 한 번씩만 훑는다."""

    def __init__(self, wb):
        self.cells = {}
        for ws in wb.worksheets:
            for (r, c), cell in ws._cells.items():      # iter_rows 는 빈 칸을 새로 만든다
                self.cells[(ws.title, r, c)] = cell.value
        self.memo, self.busy = {}, set()
        self._sumif, self._sum = {}, {}

    def formulas(self):
        return [(k, v) for k, v in self.cells.items() if isinstance(v, str) and v.startswith("=")]

    def value(self, sheet, row, col):
        key = (sheet, row, col)
        if key in self.memo:
            return self.memo[key]
        v = self.cells.get(key)
        if isinstance(v, str) and v.startswith("="):
            if key in self.busy:
                raise FormulaError(f"순환 참조: {sheet}!{row},{col}")
            self.busy.add(key)
            try:
                out = self.ev(parse(v[1:]), sheet)
            finally:
                self.busy.discard(key)
            if out is None:
                out = D0            # 엑셀은 빈 칸을 가리키는 수식(=L15)을 0 으로 보인다
        else:
            out = _norm(v)
        self.memo[key] = out
        return out

    # ------------------------------------------------------------------
    def ev(self, n, sheet):
        k = n[0]
        if k in ("num", "str"):
            return n[1]
        if k == "ref":
            return self.value(n[1] or sheet, n[2], n[3])
        if k == "rng":
            raise FormulaError("범위는 함수 안에서만 쓴다")
        if k == "neg":
            return -_num(self.ev(n[1], sheet))
        if k == "bin":
            a, b = _num(self.ev(n[2], sheet)), _num(self.ev(n[3], sheet))
            if n[1] == "/" and b == 0:
                raise FormulaError("0 으로 나눴다(#DIV/0!)")
            return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else D0}[n[1]]
        if k == "cmp":
            return _compare(self.ev(n[2], sheet), self.ev(n[3], sheet), n[1])
        if k == "call":
            return getattr(self, "f_" + n[1])(n[2], sheet)
        raise FormulaError(f"모르는 마디 {k}")

    def _rng(self, n, sheet):
        if n[0] != "rng":
            raise FormulaError("범위 자리에 범위가 아닌 값이 왔다")
        s, r1, c1, r2, c2 = n[1] or sheet, n[2], n[3], n[4], n[5]
        return s, r1, c1, r2, c2

    def _cells(self, n, sheet):
        s, r1, c1, r2, c2 = self._rng(n, sheet)
        return [self.value(s, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]

    def f_ROUND(self, a, sheet):
        return _round(_num(self.ev(a[0], sheet)), _num(self.ev(a[1], sheet)))

    def f_IF(self, a, sheet):
        if _truthy(self.ev(a[0], sheet)):
            return self.ev(a[1], sheet)
        return self.ev(a[2], sheet) if len(a) > 2 else False

    def f_SUM(self, a, sheet):
        total = D0
        for x in a:
            if x[0] != "rng":
                total += _num(self.ev(x, sheet))
                continue
            s, r1, c1, r2, c2 = self._rng(x, sheet)
            if c1 == c2:
                total += self._prefix_sum(s, c1, r1, r2)
            else:
                total += sum((v for v in self._cells(x, sheet) if isinstance(v, Decimal)), D0)
        return total

    def _prefix_sum(self, s, c, r1, r2):
        st = self._sum.setdefault((s, c, r1), {"upto": r1 - 1, "cum": [D0]})
        while st["upto"] < r2:
            r = st["upto"] + 1
            v = self.value(s, r, c)
            st["cum"].append(st["cum"][-1] + (v if isinstance(v, Decimal) else D0))
            st["upto"] = r
        return st["cum"][r2 - r1 + 1]

    def f_SUMIF(self, a, sheet):
        crit = self.ev(a[1], sheet)
        sc, r1, c1, r2, c2 = self._rng(a[0], sheet)
        ss, q1, d1, q2, d2 = self._rng(a[2], sheet)
        plain = not (isinstance(crit, str) and _CRIT.match(crit))
        if plain and c1 == c2 and d1 == d2 and (r1, r2) == (q1, q2) and _key(crit) is not None:
            return self._prefix_sumif(sc, c1, ss, d1, r1, r2, crit)
        m = _matcher(crit)
        cv, sv = self._cells(a[0], sheet), self._cells(a[2], sheet)
        if len(cv) != len(sv):
            raise FormulaError("SUMIF 의 두 범위 크기가 다르다")
        return sum((v for c, v in zip(cv, sv) if m(c) and isinstance(v, Decimal)), D0)

    def _prefix_sumif(self, sc, cc, ss, cs, r1, r2, crit):
        st = self._sumif.setdefault((sc, cc, ss, cs, r1), {"upto": r1 - 1, "hist": {}})
        while st["upto"] < r2:
            r = st["upto"] + 1
            k, v = _key(self.value(sc, r, cc)), self.value(ss, r, cs)
            if k is not None and isinstance(v, Decimal):
                rows, cums = st["hist"].setdefault(k, ([], []))
                cums.append((cums[-1] if cums else D0) + v)
                rows.append(r)
            st["upto"] = r
        rows, cums = st["hist"].get(_key(crit), ([], []))
        i = bisect_right(rows, r2) - 1
        return cums[i] if i >= 0 else D0

    def f_SUMIFS(self, a, sheet):
        sv = self._cells(a[0], sheet)
        ok = [True] * len(sv)
        for j in range(1, len(a), 2):
            cv = self._cells(a[j], sheet)
            if len(cv) != len(sv):
                raise FormulaError("SUMIFS 범위 크기가 다르다")
            m = _matcher(self.ev(a[j + 1], sheet))
            ok = [o and m(c) for o, c in zip(ok, cv)]
        return sum((v for o, v in zip(ok, sv) if o and isinstance(v, Decimal)), D0)

    def f_COUNTIF(self, a, sheet):
        m = _matcher(self.ev(a[1], sheet))
        return Decimal(sum(1 for v in self._cells(a[0], sheet) if m(v)))


def _same(got, exp):
    if isinstance(exp, bool) or isinstance(got, bool):
        return got == exp
    if isinstance(exp, (int, float, Decimal)) and isinstance(got, Decimal):
        return abs(got - Decimal(str(exp))) <= TOL
    if exp is None:
        return got is None
    return got == exp


def check(wb, expected):
    """수식 칸마다 다시 계산한 값이 엔진 값(expected[(시트, 칸)])과 같은지 본다. [(시트, 칸, 수식, 계산값, 엔진 값)]."""
    from openpyxl.utils import get_column_letter
    book = Book(wb)
    order = {ws.title: i for i, ws in enumerate(wb.worksheets)}
    bad = []
    formulas = sorted(book.formulas(), key=lambda kv: (order[kv[0][0]] != order.get("거래원장", -1), order[kv[0][0]],
                                                       kv[0][1], kv[0][2]))
    seen = set()
    for (s, r, c), f in formulas:
        coord = f"{get_column_letter(c)}{r}"
        seen.add((s, coord))
        try:
            got = book.value(s, r, c)
        except FormulaError as e:
            bad.append((s, coord, f, f"오류: {e}", expected.get((s, coord))))
            continue
        if (s, coord) not in expected:
            bad.append((s, coord, f, got, "엔진 값 없음"))
        elif not _same(got, expected[(s, coord)]):
            bad.append((s, coord, f, got, expected[(s, coord)]))
    for (s, coord) in expected:
        if (s, coord) not in seen:
            bad.append((s, coord, "", "수식 없음", expected[(s, coord)]))
    return bad


# ---------------------------------------------------------------------- 저장값 넣기
_CELL_XML = re.compile(r'<c r="([A-Z]+[0-9]+)"([^>]*)><f>(.*?)</f><v\s*(?:/>|>\s*</v>)</c>', re.S)


def _xml_num(v):
    d = Decimal(str(v)) if not isinstance(v, Decimal) else v
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def write_cached(path, expected):
    """openpyxl 이 빈 칸으로 남긴 수식 저장값(<v>)에 엔진 값을 넣는다. 미리보기 · 휴대폰처럼 수식을 계산하지 않는
    화면에서도 숫자가 보이고, 엑셀은 열 때 다시 계산한다(fullCalcOnLoad)."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        files = {n: z.read(n) for n in names}
    wbx = files["xl/workbook.xml"].decode("utf-8")
    rels = files["xl/_rels/workbook.xml.rels"].decode("utf-8")
    target = {}
    for attrs in re.findall(r"<Relationship\b([^>]*)/?>", rels):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        t = a.get("Target", "").lstrip("/")
        target[a.get("Id")] = t if t.startswith("xl/") else "xl/" + t
    by_sheet = {}
    for (s, coord), v in expected.items():
        by_sheet.setdefault(s, {})[coord] = v
    for attrs in re.findall(r"<sheet\b([^>]*)/>", wbx):
        a = dict(re.findall(r'([\w:]+)="([^"]*)"', attrs))
        name = html.unescape(a.get("name", ""))
        part = target.get(a.get("r:id"))
        vals = by_sheet.get(name)
        if not vals or part not in files:
            continue

        def put(m):
            coord, at, f = m.group(1), m.group(2), m.group(3)
            if coord not in vals:
                return m.group(0)
            v = vals[coord]
            if isinstance(v, str):
                if " t=" not in at:
                    at += ' t="str"'
                return f'<c r="{coord}"{at}><f>{f}</f><v>{escape(v)}</v></c>'
            if isinstance(v, bool):
                return f'<c r="{coord}"{at} t="b"><f>{f}</f><v>{int(v)}</v></c>'
            return f'<c r="{coord}"{at}><f>{f}</f><v>{_xml_num(v)}</v></c>'
        files[part] = _CELL_XML.sub(put, files[part].decode("utf-8")).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, files[n])
