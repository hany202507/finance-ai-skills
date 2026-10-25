"""전기 PDF 의 격자 서식 파서(단계 B B2, 설계 §4 B2, 사전 조사 §5).

코드가 인쇄되지 않은 서식(15·15부표1·15부표2·50을·50갑 Ⅱ·8부표3 2절·32·34·23을·세금공과금명세서·선급비용명세서)과 격자에서
코드 칸을 줄 열쇠로 쓰는 코드 서식(50갑 Ⅰ·20_4·8을·8부표3 1절)을 engine.intake.grid 의 칸으로 읽는다. AI 는 쓰지 않는다.
21(기부금조정명세서)은 틀만 있다. 기준 신고본 두 해 모두 그 쪽이 없어 읽는 규칙을 검증할 수 없으므로, 그 쪽이 나오면 읽지 않았다는
확인사항 하나를 낸다(값이 조용히 빠지지 않게).

란 코드는 서식 정의(forms/defs)와 단계 B 채점기(engine.stage_b.normalize)의 규칙 그대로다(B1 계획 Global Constraints).
  줄 란          (서식, 란, 줄 번호 1 부터). 합계·계·소계 줄은 줄 번호를 세지 않는다
  합계 줄        '<인쇄 이름>_<열 코드>'(15 합계_2, 50을 합계_5, 세금공과금 계_5·손금불산입계_5, 50갑 Ⅱ 계_7)
  코드 줄의 열    '<코드><접미>'(50갑 14_2 기초, 20_4 01_5 기타자산). 주 열(⑤기말·②합계액·(104))은 접미가 없다
  절 이름 접두    50갑 Ⅱ 결손_6~결손_18

  TITLES              {서식: 인쇄 제목(norm)}. 쪽 분류가 쪽 머리 표시보다 먼저 본다(FY2024 28쪽은 머리 표시가 '15호부표1' 로
                      잘못 인쇄됐다). 8을 은 제목이 두 줄로 나뉘어 머리 표시로만 찾는다(HINTS).
  HINTS               {쪽 머리 표시: 서식}. 제목이 없는 이어진 쪽(8을 15쪽, 34 50쪽)은 prior_pdf.split_pages 가 앞 쪽 표시를 잇는다.
  FORMS               격자 서식 코드 모음.
  parse(fc, pages)    서식 하나의 쪽들(split_pages 의 dict, 'grid' 가 있다) → (Cell 목록, Problem 목록).
  credit_code(name)   8부표3 2절 (105)구분 글 → 8부표3 1절 공제 코드(정의의 란 이름에서 근거 조항을 떼고 맞춘다). 없거나 둘 이상이면 None.
  column_name·cell_label  란을 인쇄된 서식의 열 이름·줄로 부르는 말(검산 제목과 전기 PDF 확인사항 카드가 쓴다, 태스크 7 리뷰 I2·M1).

자체 검산(사전 조사 §5, 설계 §4 B2)은 Problem 'check.<서식>.<란>=<서식>.<란>' 이다(prior_pdf._checks 와 같은 모양, 확인사항
문구도 같다). 줄 합계 = 합계 줄, 50을 기초 - 감소 + 증가 = 기말, 8부표3 2절 (125) = (107)+(108)-(123)-(124). 읽은 칸 밖에 금액이
남으면 '<서식>.이름없음.<금액>' 이다(어느 란인지 정하지 못한 금액, 조용히 버리지 않는다). 머리글을 찾지 못해 표 시작이 서지
않은 쪽에 금액 칸이 있으면 '<서식>.p<쪽>' 이다(표를 찾지 못했다). 일부러 읽지 않는 쪽은 파서가 Reader.skip 으로 밝힌다.
"""
import json
import re

from ctax.prior.grid import Box, Grid, amount, column, norm, reading_order
from ctax.prior.pdf import Cell, Problem
from ctax.prior.defs import form_name, item_name

TITLES = {
    "15": "소득금액조정합계표", "15부표1": "과목별소득금액조정명세서(1)", "15부표2": "과목별소득금액조정명세서(2)",
    "50갑": "자본금과적립금조정명세서(갑)", "50을": "자본금과적립금조정명세서(을)", "20_4": "감가상각비조정명세서합계표",
    "8부표3": "세액공제조정명세서(3)", "32": "퇴직급여충당금조정명세서", "34": "대손충당금및대손금조정명세서",
    "23을": "기업업무추진비조정명세서(을)", "세금공과금명세서": "세금공과금명세서", "선급비용명세서": "선급비용명세서",
    "21": "기부금조정명세서",
}
HINTS = {"15호": "15", "15호부표1": "15부표1", "15호부표2": "15부표2", "50호(갑)": "50갑", "50호(을)": "50을",
         "20호(4)": "20_4", "8호부표3": "8부표3", "8호(을)": "8을", "32호": "32", "34호": "34", "23호(을)": "23을",
         "6-11호": "세금공과금명세서", "6-12호": "선급비용명세서", "21호": "21"}
FORMS = tuple(dict.fromkeys(list(TITLES) + list(HINTS.values())))

TOTAL = re.compile(r"^(합계|계|소계|손금불산입계)$")
NTS_CODE = r"\d[0-9A-Z]{2}"             # 국세청 영숫자 공제·감면 코드(16B·18F·1A1·601)
HEAD_ROW_TOL = 2.5                      # 값 칸 바로 위 이름표 칸으로 보는 세로 간격(32·34)


def _fmt(v) -> str:
    return "없음" if v is None else f"{v:,}"


_NUMERIC = re.compile(r"[\d,.\-△()]*\d[\d,.\-△()]*")


def _numeric(text: str) -> bool:
    """금액이거나 숫자와 금액 부호(쉼표·마침표·-·△·괄호)만으로 된 글. amount 가 못 읽는 금액 꼴('1.234.567', '(500)')도
    leftovers 가 보게 한다(리뷰 M2). 숫자가 든 칸 전부로 넓히지 않는 까닭: 기준 신고본 표 안에는 쓰지 않는 글 칸('1.자본금',
    '제10조제1항', 8부표3 1절 계산기준 '금액x50/100')이 두 해 합해 수십 개 있어 모두 거짓 확인사항이 된다."""
    return amount(text) is not None or bool(_NUMERIC.fullmatch(norm(text)))


class Reader:
    """서식 하나를 읽는 동안의 상태. 칸을 쓸 때마다(put) 그 칸을 '쓴 칸' 으로 표시해 두고 끝에(leftovers) 쓰지 않은 금액 칸을
    문제로 남긴다. region 은 쪽마다 표가 시작하는 y 다(그 위 쪽 머리의 사업자등록번호 숫자 칸은 보지 않는다). 파서는 읽는
    쪽마다 region 을 세우고, 일부러 읽지 않는 쪽은 skip 으로 밝힌다. 둘 다 없는 쪽은 머리글을 찾지 못한 쪽이다(leftovers)."""

    def __init__(self, form_code: str, pages: list):
        self.fc = form_code
        self.grids = [Grid.from_page(p) for p in pages]
        self.cells: list = []
        self.problems: list = []
        self.used: set = set()
        self.region: dict = {}
        self.skipped: set = set()

    def skip(self, g: Grid) -> None:
        """파서가 일부러 읽지 않는 쪽(당기로 넘기지 않는 표만 있는 쪽). leftovers 가 그 쪽을 보지 않는다. 표 일부라도 읽는 쪽은
        skip 이 아니라 region 을 세운다(읽지 않은 금액이 '이름없음' 으로 드러나게)."""
        self.skipped.add(g.page_no)

    def mark(self, g: Grid, *boxes) -> None:
        for b in boxes:
            if b is not None:
                self.used.add((g.page_no, b))

    def put(self, g: Grid, box: Box, item: str, row: int = 0, kind: str = "won"):
        """칸 하나를 란으로. kind 'won' 이면 금액(빈칸·금액 아닌 글은 넣지 않는다), 'text' 면 글. 넣은 값(없으면 None)."""
        self.mark(g, box)
        raw = g.text(box)
        if kind == "text":
            if not raw:
                return None
            self.cells.append(Cell(self.fc, item, row, None, raw, g.bbox(box), g.page_no))
            return raw
        v = amount(raw)
        if v is None:
            if raw:
                self.problems.append(Problem(f"{self.fc}.{item}.{row}.값", f"{self.fc} ({item}) 금액을 읽지 못했다",
                                             f"{g.page_no}쪽. 인쇄 문자열 {raw!r}"))
            return None
        self.cells.append(Cell(self.fc, item, row, v, None, g.bbox(box), g.page_no))
        return v

    def check(self, left: tuple, right: tuple, a, b, what: str) -> None:
        """검산 a == b(None 은 0). left·right 는 (서식, 란) 이고 target_ref 는 check.<서식>.<란>=<서식>.<란> 이다."""
        if (a or 0) != (b or 0):
            self.problems.append(Problem(f"check.{left[0]}.{left[1]}={right[0]}.{right[1]}", f"검산 불일치: {what}",
                                         f"{left[0]} ({left[1]}) {_fmt(a)} / {right[0]} ({right[1]}) {_fmt(b)}"))

    def leftovers(self) -> None:
        """쓰지 않은 금액을 문제로. region 이 선 쪽은 region 아래에서 쓰지 않은 금액·숫자 칸(_numeric)마다 '이름없음' 하나.
        region 도 skip 도 없는 쪽은 금액 칸이 하나라도 있으면 '<서식> <쪽>쪽에서 표를 찾지 못했다' 하나다(머리글을 못 찾은
        쪽의 금액이 조용히 빠지지 않게, 리뷰 I2). 그 쪽은 쪽 머리(사업자등록번호·사업연도)까지 보므로 금액(amount)만 세고,
        파서가 그 쪽을 이미 '<서식>.p<쪽>' 문제로 올렸으면 더하지 않는다."""
        for g in self.grids:
            if g.page_no in self.skipped:
                continue
            top = self.region.get(g.page_no)
            if top is None:
                ref = f"{self.fc}.p{g.page_no}"
                money = sorted(((b, t) for b, t in g.boxes.items() if amount(t) is not None),
                               key=lambda bt: (bt[0].top, bt[0].left))
                if money and not any(q.target_ref == ref for q in self.problems):
                    b, t = money[0]
                    self.problems.append(Problem(ref, f"{self.fc} {g.page_no}쪽에서 표를 찾지 못했다",
                                                 f"{g.page_no}쪽. 금액 란 {len(money)}개(첫 란 {t}, y={b.top} "
                                                 f"x={b.left}~{b.right})"))
                continue
            for b, t in g.boxes.items():
                if b.top >= top and (g.page_no, b) not in self.used and _numeric(t):
                    self.problems.append(Problem(f"{self.fc}.이름없음.{norm(t)}", f"{self.fc} 어느 란인지 정하지 못한 금액 {t}",
                                                 f"{g.page_no}쪽 y={b.top} x={b.left}~{b.right}"))

    def value(self, item: str, row: int = 0):
        return next((c.value for c in self.cells if c.item_code == item and c.row_no == row), None)

    def column_sum(self, item: str):
        vals = [c.value for c in self.cells if c.item_code == item and c.row_no >= 1 and c.value is not None]
        return sum(vals) if vals else None


def _heads(g: Grid, specs: dict, **where) -> dict:
    """{란: 정규식} → {란: 가장 좁은 머리글 칸}. 못 찾은 란은 뺀다."""
    out = {}
    for item, rx in specs.items():
        b = g.head(rx, **where)
        if b is not None:
            out[item] = b
    return out


def _rows(r: Reader, g: Grid, heads: dict, top: float, bottom: float = 1e9, left=None, right=None):
    """머리글 아래 [top, bottom) 의 줄. 줄마다 (합계 이름 또는 None, {란: 칸}). 합계 이름은 줄 안 칸 중 글이 합계·계·소계·
    손금불산입계인 것이다(병합 칸이라 어느 열에 떨어져도 된다). 칸이 하나도 열에 들지 않는 줄은 뺀다."""
    left = min(h.left for h in heads.values()) - 1 if left is None else left
    right = max(h.right for h in heads.values()) + 1 if right is None else right
    out = []
    for line in g.band(top, bottom, left, right):
        name, cols = None, {}
        for b in line:
            t = norm(g.text(b))
            if TOTAL.match(t):
                name = t
                r.mark(g, b)
                continue
            col = column(b, heads)
            if col is not None and col not in cols:
                cols[col] = b
        if name or cols:
            out.append((name, cols))
    return out


def _simple_table(r: Reader, g: Grid, heads: dict, text_items: set, total_items: dict, n: int = 0, top=None,
                  bottom: float = 1e9) -> int:
    """한 줄에 란이 하나씩인 표(15부표·50을·세금공과금·선급비용). total_items 는 {합계 줄 이름: [란, ...]} 이고 합계 줄의
    란은 '<이름>_<란>' 이다. 줄 번호는 n 다음부터 매기고 마지막 줄 번호를 돌려준다."""
    top = max(h.bottom for h in heads.values()) if top is None else top
    r.region[g.page_no] = min(r.region.get(g.page_no, 1e9), min(h.top for h in heads.values()))
    r.mark(g, *heads.values())
    for name, cols in _rows(r, g, heads, top, bottom):
        if name:
            for item in total_items.get(name, ()):
                if item in cols:
                    r.put(g, cols[item], f"{name}_{item}")
            continue
        n += 1
        for item, b in cols.items():
            r.put(g, b, item, n, "text" if item in text_items else "won")
    return n


def _sum_check(r: Reader, total: str, item: str, what: str) -> None:
    got = r.value(total)
    if got is not None or r.column_sum(item) is not None:
        r.check((r.fc, total), (r.fc, item), got, r.column_sum(item), what)


# ---------------------------------------------------------------- 15·15부표1·15부표2

def _p15(r: Reader) -> None:
    """15호. 익금산입(①~③)·손금산입(④~⑥) 두 표가 나란하다. 양쪽 줄 번호는 쪽을 넘어 잇는다(쪽마다 1 부터 세면 같은 란이
    두 벌이 된다, 태스크 3·4 리뷰 I1). 한쪽 머리글을 하나도 찾지 못하면 그쪽만 건너뛴다(그쪽 금액은 leftovers 가 올린다, M1)."""
    n = {"2": 0, "5": 0}
    for g in r.grids:
        left = g.head(r"^익금산입및손금불산입$")
        right = g.head(r"^손금산입및익금불산입$")
        if left is None or right is None:
            continue
        sides = ((left, {"1": r"^①과목", "2": r"^②금액", "3": r"^처분$", "3_2": r"^코드$"}, "2"),
                 (right, {"4": r"^④과목", "5": r"^⑤금액", "6": r"^처분$", "6_2": r"^코드$"}, "5"))
        for sec, specs, money in sides:
            r.mark(g, sec)
            heads = _heads(g, specs, top=sec.bottom - 1, left=sec.left, right=sec.right)
            if not heads:
                continue
            texts = {k for k in heads if k != money}
            n[money] = _simple_table(r, g, heads, texts, {"합계": [money]}, n[money],
                                     top=max(h.bottom for h in heads.values()))
    _sum_check(r, "합계_2", "2", "15호 익금산입 합계 = 줄 합계")
    _sum_check(r, "합계_5", "5", "15호 손금산입 합계 = 줄 합계")


def _p15sub(r: Reader) -> None:
    specs = {"1": r"^①과목", "2": r"^②금액", "3": r"^③영업손익", "4": r"^④처분", "5": r"^⑤조정내용"}
    n = 0
    for g in r.grids:
        heads = _heads(g, specs)
        if len(heads) < 2:
            continue
        n = _simple_table(r, g, heads, {"1", "4", "5"}, {"합계": ["2"]}, n)
    _sum_check(r, "합계_2", "2", f"{form_name(r.fc)} 합계 = 줄 합계")


# ---------------------------------------------------------------- 50을·세금공과금·선급비용

def _p50eul(r: Reader) -> None:
    specs = {"1": r"과목또는사항", "2": r"②?기초잔액", "3": r"^③감소", "4": r"^④증가", "5": r"^⑤?기말잔액", "비고": r"^비고$"}
    n = 0
    for g in r.grids:
        heads = _heads(g, specs)
        if "1" not in heads or "5" not in heads:
            continue
        n = _simple_table(r, g, heads, {"1", "비고"}, {"합계": ["2", "3", "4", "5"]}, n)
    col = {i: column_name("50을", i) for i in ("2", "3", "4", "5")}
    for row in range(1, n + 1):
        vals = [r.value(i, row) for i in ("2", "3", "4", "5")]
        if any(v is not None for v in vals):
            # 제목은 왼쪽(⑤기말)을 먼저 적는다. 카드 사실의 '(왼쪽 대 오른쪽)' 값 순서와 같게(전에는 거꾸로 적었다)
            r.check(("50을", f"5.{row}"), ("50을", f"2-3+4.{row}"), vals[3],
                    (vals[0] or 0) - (vals[1] or 0) + (vals[2] or 0),
                    f"50호(을) {row}줄 {col['5']} = {col['2']} - {col['3']} + {col['4']}")
    for i in ("2", "3", "4", "5"):
        _sum_check(r, f"합계_{i}", i, f"50호(을) 합계 {col[i]} = 줄 합계")


def _p_dues(r: Reader) -> None:
    specs = {"1": r"^①과목", "2": r"^②일자", "3": r"^③적요", "4": r"^④지급처", "5": r"^⑤금액", "비고": r"^비고$"}
    n = 0
    for g in r.grids:
        heads = _heads(g, specs)
        if len(heads) < 5:
            continue
        n = _simple_table(r, g, heads, {"1", "2", "3", "4", "비고"}, {"계": ["5"], "손금불산입계": ["5"]}, n)
    _sum_check(r, "계_5", "5", "세금공과금명세서 계 = 줄 합계")


def _p_prepaid(r: Reader) -> None:
    specs = {"1": r"^①구분", "2": r"^②적요", "3": r"^③거래처", "4": r"^④금액", "비고": r"^비고"}
    n = 0
    for g in r.grids:
        heads = _heads(g, specs)
        if len(heads) < 4:
            continue
        n = _simple_table(r, g, heads, {"1", "2", "3", "비고"}, {"계": ["4"], "손금불산입계": ["4"]}, n)
    _sum_check(r, "계_4", "4", "선급비용명세서 계 = 줄 합계")


# ---------------------------------------------------------------- 코드 줄 서식(50갑 Ⅰ·20_4·8부표3 1절)

def _coded(r: Reader, g: Grid, code_head: Box, heads: dict, top: float, bottom: float, code_rx: str = r"\d{2}") -> None:
    """코드 칸을 줄 열쇠로 읽는다. heads 는 {접미: 머리글 칸}(주 열은 ''). 코드 칸 글이 code_rx 에 맞는 줄만."""
    r.region[g.page_no] = min(r.region.get(g.page_no, 1e9), code_head.top)
    r.mark(g, code_head, *heads.values())
    for line in g.band(top, bottom):
        code_box = next((b for b in line if code_head.left - 1 <= b.xc <= code_head.right + 1
                         and re.fullmatch(code_rx, norm(g.text(b)))), None)
        if code_box is None:
            continue
        code = norm(g.text(code_box))
        r.mark(g, code_box)
        for b in line:
            sfx = column(b, heads)
            if sfx is not None and b != code_box:
                r.put(g, b, code + sfx)


def _p50gap(r: Reader) -> None:
    """50갑. 쪽마다 Ⅰ(자본금과 적립금 계산서, 코드 줄)과 Ⅱ(이월결손금 계산서, 사업연도 줄)를 찾아 읽는다. Ⅱ 는 사업연도마다
    한 줄이라 다음 쪽으로 넘어갈 수 있고, 이어진 쪽은 'Ⅱ.' 없이 ⑥사업연도 머리글만 다시 찍힐 수 있다. Ⅱ 줄 번호는 쪽을 넘어
    잇는다(태스크 3·4 리뷰 I2. 전에는 첫 쪽만 읽었다). 'Ⅰ 표를 찾지 못했다' 는 어느 쪽에도 Ⅰ 이 없을 때 첫 쪽에 하나다."""
    found, n = False, 0
    for g in r.grids:
        one, two = g.head(r"^Ⅰ\."), g.head(r"^Ⅱ\.")
        code = g.head(r"^코드$", bottom=two.top if two else 1e9) if one is not None else None
        if code is not None:
            found = True
            heads = _heads(g, {"_2": r"^②기초잔액", "_3": r"^③감소", "_4": r"^④증가", "": r"^⑤기말잔액"},
                           top=one.bottom - 1, bottom=code.bottom)
            _coded(r, g, code, heads, code.bottom - 1, two.top if two else 1e9)
            r.mark(g, one)
        n = _p50gap_loss(r, g, two, n)
    if not found:
        g = r.grids[0]
        r.problems.append(Problem(f"50갑.p{g.page_no}", "50갑 Ⅰ 표를 찾지 못했다", f"{g.page_no}쪽"))
    for sfx in ("_2", "_3", "_4", ""):
        vals = [r.value(c + sfx) for c in ("01", "02", "15", "18", "14", "17")]
        if any(v is not None for v in vals) or r.value("20" + sfx) is not None:
            r.check(("50갑", "20" + sfx), ("50갑", "01~17" + sfx), r.value("20" + sfx), sum(v or 0 for v in vals),
                    f"50호(갑) {column_name('50갑', '20' + sfx)}의 계 = 1~5·12 합")


def _p50gap_loss(r: Reader, g: Grid, two: Box | None, n: int = 0) -> int:
    """50갑 Ⅱ 결손금 계산서 한 쪽. two 는 'Ⅱ.' 칸(이어진 쪽이면 None, 쪽 전체에서 ⑥사업연도 머리글을 찾는다). ⑥사업연도
    머리글 칸의 높이가 머리글 띠다. 줄은 ⑥ 글이 '계' 면 합계 줄(계_<n>). 줄 번호는 n 다음부터 매기고 마지막 번호를 돌려준다.
    이 쪽에 표가 있으면 region 을 세운다(Ⅱ 만 있는 쪽도 leftovers 가 '표를 찾지 못했다' 로 보지 않게)."""
    anchor = g.head(r"^⑥사업연도", top=two.top if two is not None else -1e9)
    if anchor is None:
        return n
    start = (two if two is not None else anchor).top
    r.region[g.page_no] = min(r.region.get(g.page_no, 1e9), start)
    band = {"top": anchor.top - 1, "bottom": anchor.bottom}
    specs = {"결손_7": r"^⑦계$", "결손_8": r"^⑧일반결손금", "결손_9": r"^⑨배분", "결손_10": r"^⑩소급공제",
             "결손_11": r"^⑪차감계", "결손_12": r"^⑫기공제액", "결손_13": r"^⑬당기공제액", "결손_14": r"^⑭보전",
             "결손_15": r"^⑮계", "결손_16": r"^기한내$", "결손_17": r"^기한경과$"}
    heads = {"결손_6": anchor, **_heads(g, specs, **band)}
    tail = g.head(r"^계$", left=heads["결손_17"].right if "결손_17" in heads else 1e9, **band)
    if tail is not None:
        heads["결손_18"] = tail
    r.mark(g, two, *heads.values())
    stop = next(iter(g.find(r"^2\.", top=anchor.bottom)), None)
    for line in g.band(anchor.bottom - 1, stop.top if stop else 1e9, anchor.left - 1, 1e9):
        cols = {}
        for b in line:
            col = column(b, heads)
            if col is not None and col not in cols:
                cols[col] = b
        if "결손_6" not in cols:
            continue
        label = norm(g.text(cols["결손_6"]))
        if not label:
            continue
        if label == "계":
            r.mark(g, cols.pop("결손_6"))
            for item, b in cols.items():
                r.put(g, b, item.replace("결손_", "계_"))
            continue
        n += 1
        for item, b in cols.items():
            r.put(g, b, item, n, "text" if item == "결손_6" else "won")
    return n


def _p20_4(r: Reader) -> None:
    for g in r.grids:
        code = g.head(r"^코드$")
        if code is None:
            continue
        heads = _heads(g, {"": r"^②합계액", "_3": r"^③건축물", "_4": r"^④기계장치", "_5": r"^⑤기타자산",
                           "_6": r"^⑥무형자산"}, bottom=code.bottom)
        stop = g.head(r"^작성방법$")
        _coded(r, g, code, heads, code.bottom - 1, stop.top if stop else 1e9)
        for row in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
            parts = [r.value(row + s) for s in ("_3", "_4", "_5", "_6")]
            if r.value(row) is not None or any(v is not None for v in parts):
                r.check(("20_4", row), ("20_4", row + "_3~6"), r.value(row), sum(v or 0 for v in parts),
                        f"20호(4) {cell_label('20_4', row, 0)} = 자산별 합")


# ---------------------------------------------------------------- 8부표3

def _p8bu3(r: Reader) -> None:
    carry = {"parts": [], "pending": [], "done": []}
    for g in r.grids:
        code, head104 = g.head(r"^코드$"), g.head(r"^\(104\)")
        if code is not None and head104 is not None:
            _coded(r, g, code, {"": head104}, code.bottom - 1, 1e9, NTS_CODE)
        elif g.head(r"^\(105\)") is not None:
            _p8bu3_part2(r, g, carry)
    _flush(carry)
    _p8bu3_finish(r, carry["done"])


_PART2 = re.compile(r"^\((1(?:0[5-9]|1\d|2[0-5]))\)")


def _flush(carry: dict) -> None:
    """소계(또는 표 끝)까지 모은 줄에 이어 붙인 구분 글을 단다."""
    label = "".join(carry["parts"])
    for row in carry["pending"]:
        row["label"] = label
    carry["done"] += carry["pending"]
    carry["pending"], carry["parts"] = [], []


def _p8bu3_part2(r: Reader, g: Grid, carry: dict) -> None:
    """8부표3 2절 한 쪽(사전 조사 §5 규칙 넷). (110)~(114)·(115)~(119) 는 같은 x 에서 위아래 반칸이라 글자 y 로 고른다.
    머리글 아래 경계는 칸이 아니라 머리글 글자의 y 다(FY2025 20쪽은 머리글과 합계 줄 사이 선이 빠져 머리글 칸이 합계 값을
    삼킨다). 그래서 이 절은 칸이 아니라 글자를 줄 띠·열로 나눈다. 줄 띠는 (120) 열의 가로선이다. 구분 글은 소계가 나올
    때까지 이어 붙이고(쪽을 넘어도 잇는다), 합계는 (105)·(106) 에 '합'·'계' 로 나뉘어 찍힌다."""
    found: dict = {}
    for b, t in g.boxes.items():
        m = _PART2.match(norm(t))
        if m:
            found.setdefault(m.group(1), []).append(b)
    hd = {c: min(bs, key=lambda b: (b.width * (b.bottom - b.top), b.top)) for c, bs in found.items()}
    if "105" not in hd or "106" not in hd or "120" not in hd:
        r.problems.append(Problem(f"8부표3.p{g.page_no}", "8부표3 2절 머리글을 찾지 못했다", f"{g.page_no}쪽"))
        return
    r.mark(g, *hd.values())
    r.region[g.page_no] = min(r.region.get(g.page_no, 1e9), min(b.top for b in hd.values()))
    hb = max(c[3] for b in hd.values() for c in g.chars_in(b) if _header_char(g, b, c)) + 0.5
    col120 = hd["120"]
    ys = sorted({round(h[0]) for h in g.H if h[1] - 1 <= col120.xc <= h[2] + 1 and h[0] > hb + 2})
    pairs = {}
    for c, b in hd.items():
        same = [k for k, x in hd.items() if abs(x.left - b.left) < 2 and abs(x.right - b.right) < 2]
        if len(same) == 2:
            pairs[c] = "U" if b.top == min(hd[k].top for k in same) else "L"
    left, right = min(b.left for b in hd.values()) - 1, max(b.right for b in hd.values()) + 1
    # 이 절은 글자로 읽으므로 표 몸통(머리글 아래부터 마지막 줄 띠까지)의 칸을 쓴 칸으로 둔다. 표 아래 칸은 두어 leftovers 가
    # 본다(선이 빠진 마지막 줄·표 아래 다른 표, 태스크 3·4 리뷰 I3)
    end = ys[-1] - 1 if ys else hb
    r.mark(g, *[b for b in g.boxes if hb - 1 <= b.top < end and left <= b.xc <= right])
    owner = {c: b for b in g.boxes for c in g.chars_in(b)}
    lost: dict = {}
    for i, (t, bt) in enumerate(zip([hb] + ys, ys)):
        parts: dict = {}
        for c in g.chars:
            yc, xc = (c[1] + c[3]) / 2, (c[0] + c[2]) / 2
            if not (t < yc < bt) or c[4] == "※":
                continue
            cand = [k for k, b in hd.items() if b.left - 1 <= xc <= b.right + 1]
            if len(cand) > 1:
                want = "U" if yc < (t + bt) / 2 else "L"
                cand = [k for k in cand if pairs.get(k) == want] or cand
            if cand:
                parts.setdefault(cand[0], []).append(c)
            elif left <= xc <= right:
                lost.setdefault((i, owner.get(c)), []).append(c)     # 알아본 머리글 열 밖의 글자
        text = {k: "".join(c[4] for c in reading_order(cs)) for k, cs in parts.items()}
        bbox = {k: (round(min(c[0] for c in cs), 1), round(min(c[1] for c in cs), 1), round(max(c[2] for c in cs), 1),
                    round(max(c[3] for c in cs), 1)) for k, cs in parts.items()}
        lab, yr = text.pop("105", ""), text.pop("106", "")
        vals = {k: (amount(v), v, bbox[k]) for k, v in text.items()}
        if "합계" in norm(lab + yr):
            _flush(carry)
            carry["done"].append({"kind": "합계", "vals": vals, "page": g.page_no})
        elif "소계" in (norm(lab), norm(yr), norm(lab + yr)):     # '소'·'계' 가 (105)·(106) 에 나뉘어도(리뷰 M6)
            _flush(carry)
        else:
            if lab:
                carry["parts"].append(lab)
            if vals or yr:
                carry["pending"].append({"kind": "row", "year": yr, "vals": vals, "page": g.page_no,
                                         "bbox": bbox.get("106") or bbox.get("105")})
    # 머리글을 알아보지 못한 열((121) 의 '(' 가 빠진 인쇄, 서식 개정으로 생긴 열)의 숫자 글은 조용히 버리지 않는다(리뷰 I3)
    for (_, box), cs in lost.items():
        t = "".join(c[4] for c in reading_order(cs))
        if _numeric(t):
            x0, y0, x1 = min(c[0] for c in cs), min(c[1] for c in cs), max(c[2] for c in cs)
            r.problems.append(Problem(f"{r.fc}.이름없음.{norm(t)}", f"{r.fc} 어느 란인지 정하지 못한 금액 {t}",
                                      f"{g.page_no}쪽 y={round(y0)} x={round(x0)}~{round(x1)}"))


def _header_char(g: Grid, box: Box, ch) -> bool:
    """머리글 칸 안 글자가 머리글 글인가(그 칸이 삼킨 합계 값이 아닌가). 같은 줄 글이 금액이 아니면 머리글이다."""
    line = [c for c in g.chars_in(box) if abs((c[1] + c[3]) / 2 - (ch[1] + ch[3]) / 2) <= 1.5]
    t = "".join(c[4] for c in sorted(line, key=lambda c: c[0]))
    return amount(t.replace("※", "")) is None and norm(t) not in ("합", "계", "합계", "소계")


def _p8bu3_finish(r: Reader, rows: list) -> None:
    """모은 줄을 란으로 쓴다. 보통 줄은 1 부터 줄 번호, 합계 줄은 합계_<열>. 검산은 합계 = 줄 합, 줄마다 (125) = (107)+(108)
    -(123)-(124)."""
    n = 0
    for row in rows:
        if row["kind"] == "row":
            n += 1
            _row_values(r, row, n)
        else:
            for code, (v, raw, bbox) in row["vals"].items():
                _value(r, f"합계_{code}", 0, v, raw, bbox, row["page"])
    for code in ("107", "108", "109", "110", "111", "112", "113", "114", "115", "116", "117", "118", "119", "120",
                 "121", "122", "123", "124", "125"):
        _sum_check(r, f"합계_{code}", code, f"8호 부표3 2절 합계 {column_name('8부표3', code)} = 줄 합계")
    for row in range(1, n + 1):
        v = {c: r.value(c, row) or 0 for c in ("107", "108", "123", "124", "125")}
        if any(v.values()):
            r.check(("8부표3", f"125.{row}"), ("8부표3", f"107+108-123-124.{row}"), v["125"],
                    v["107"] + v["108"] - v["123"] - v["124"], f"8호 부표3 2절 {row}줄 이월액 = 당기분 + 이월분 - 공제 - 소멸")


def _row_values(r: Reader, row: dict, n: int) -> None:
    page = row["page"]
    r.cells.append(Cell(r.fc, "105", n, None, row["label"], row.get("bbox"), page))
    if row["year"]:
        r.cells.append(Cell(r.fc, "106", n, None, row["year"], row.get("bbox"), page))
    if credit_code(row["label"]) is None:
        r.problems.append(Problem(f"8부표3.105.{n}", f"8부표3 (105) 구분 {row['label']} 에 맞는 공제 코드가 없다",
                                  f"{page}쪽. 1절 정의의 구분 이름과 같은 것이 없거나 둘 이상이다"))
    for code, (v, raw, bbox) in row["vals"].items():
        _value(r, code, n, v, raw, bbox, page)


def _value(r: Reader, item: str, row: int, v, raw: str, bbox, page) -> None:
    if v is None:
        r.problems.append(Problem(f"8부표3.{item}.{row}.값", f"8부표3 ({item}) 금액을 읽지 못했다",
                                  f"{page}쪽. 인쇄 문자열 {raw!r}"))
        return
    r.cells.append(Cell(r.fc, item, row, v, None, bbox, page))


_LAW = re.compile(r"\s+(구\s*)?(제\s*)?\d+조.*$")
_CREDIT_NAMES: dict = {}


def credit_names() -> dict:
    """{norm(8부표3 1절 구분 이름): [코드, ...]}. 정의의 란 이름에서 ' (104)공제대상세액' 과 근거 조항('제10조 …', '구 제5조',
    '104조의8①')을 뗀다."""
    if not _CREDIT_NAMES:
        from ctax.prior.defs import DEFS
        doc = json.loads((DEFS / "8부표3.json").read_text(encoding="utf-8"))
        for it in doc["items"]:
            if not re.fullmatch(NTS_CODE, it["code"]) or it["code"] == "1A1":
                continue
            name = norm(_LAW.sub("", it["label"].split(" (104)")[0]))
            _CREDIT_NAMES.setdefault(name, []).append(it["code"])
    return _CREDIT_NAMES


def credit_code(label: str):
    codes = credit_names().get(norm(label), [])
    return codes[0] if len(codes) == 1 else None


# ---------------------------------------------------------------- 8을

_8EUL_COLS = {"": r"^(③금액|⑧합계|⑪이월과세|⑮세액)", "_6": r"^⑥결산조정액", "_7": r"^⑦세무조정액", "_14": r"^⑭대상금액"}


def _p8eul(r: Reader) -> None:
    """8(을). 줄 열쇠는 '코드' 머리글 열의 코드 칸이다. 값 칸은 그 줄에서 바로 위(가장 가까운) 금액 머리글의 열이다(절마다
    머리글 줄이 따로 있다). ③⑧⑪⑮ 는 주 열, ⑥·⑦·⑭ 는 '_<열 번호>' 다(8갑과 같은 규칙). 기준 신고본 두 해 모두 값이 없다(사전
    조사 §5). '코드' 머리글이 없는 쪽은 읽지 않고 region 도 세우지 않는다(그 쪽 금액은 leftovers 가 '표를 찾지 못했다' 로 올린다)."""
    for g in r.grids:
        codes = g.find(r"^코드$")
        if not codes:
            continue
        heads = [(sfx, b) for sfx, rx in _8EUL_COLS.items() for b in g.find(rx)]
        r.region[g.page_no] = min(b.top for b in codes)
        r.mark(g, *codes, *(b for _, b in heads))
        for line in g.band(min(b.bottom for b in codes) - 1, 1e9):
            top = line[0].top
            code_box = next((b for b in line if re.fullmatch(NTS_CODE, norm(g.text(b)))
                             and any(h.top < top and h.left - 1 <= b.xc <= h.right + 1 for h in codes)), None)
            if code_box is None:
                continue
            code = norm(g.text(code_box))
            r.mark(g, code_box)
            for b in line:
                if b == code_box or amount(g.text(b)) is None:
                    continue
                above = [(h.top, sfx) for sfx, h in heads if h.top < top and h.left - 1 <= b.xc <= h.right + 1]
                if above:
                    r.put(g, b, code + max(above)[1])


# ---------------------------------------------------------------- 칸마다 번호가 붙은 서식(32·34·23을)

def _above(g: Grid, box: Box):
    """값 칸 바로 위(HEAD_ROW_TOL 안)의 이름표 칸 중 가운데 x 를 덮는 가장 좁은 칸."""
    cand = [b for b, t in g.boxes.items() if box.top - 40 <= b.bottom <= box.top + HEAD_ROW_TOL and b.top < box.top
            and b.left - 1 <= box.xc <= b.right + 1 and amount(t) is None and t]
    if not cand:
        return None
    low = max(b.bottom for b in cand)
    return min((b for b in cand if b.bottom >= low - HEAD_ROW_TOL), key=lambda b: b.width)


def _labelled(r: Reader, g: Grid, labels: list, top: float = -1e9, bottom: float = 1e9) -> None:
    """금액 칸마다 바로 위 이름표를 찾아 labels [(란, 이름표 정규식, 위 머리글 정규식 또는 None)] 의 첫 맞는 란으로 넣는다.
    위 머리글은 이름표 칸(인원·금액 같은 짧은 이름표)의 바로 위 칸이다."""
    for b, t in sorted(g.boxes.items()):
        if not (top <= b.top < bottom) or amount(t) is None and not re.fullmatch(r"\d+/\d+", norm(t)):
            continue
        head = _above(g, b)
        if head is None:
            continue
        span = _above(g, head)
        for item, rx, span_rx in labels:
            if re.search(rx, norm(g.text(head))) and (span_rx is None or (span is not None
                                                                         and re.search(span_rx, norm(g.text(span))))):
                r.mark(g, head)
                if re.fullmatch(r"\d+/\d+", norm(t)):
                    a, c = norm(t).split("/")
                    r.mark(g, b)
                    r.cells.append(Cell(r.fc, item, 0, int(a) / int(c), None, g.bbox(b), g.page_no))
                else:
                    r.put(g, b, item)
                break


_32 = [("2", r"^②설정률", None), ("3", r"^③한도액", None), ("4", r"^④장부상", None), ("5", r"^⑤확정기여형", None),
       ("6", r"^⑥기중", None), ("7", r"^⑦기초충당금", None), ("8", r"^⑧기중퇴직금", None), ("9", r"^⑨차감액", None),
       ("10", r"^⑩추계액", None), ("11", r"^⑪퇴직금전환금", None), ("12", r"^⑫설정률감소", None),
       ("13", r"^⑬누적한도액", None), ("14", r"^⑭한도액", None), ("15", r"^⑮회사계상액", None), ("16", r"^(\(16\))?한도초과액", None),
       ("1", r"^①퇴직급여", None), ("22", r"세법상추계액", None),
       ("20_1", r"^인원$", r"기말현재"), ("20", r"^금액$", r"기말현재"),
       ("21_1", r"^인원$", r"근로자퇴직급여보장"), ("21", r"^금액$", r"근로자퇴직급여보장")]


def _p32(r: Reader) -> None:
    """32 1절(①~(16) 칸)과 2절((17)~(19) 계정명 줄, (20)~(22) 추계액 칸). 1절이 없고 2절만 있는 이어진 쪽도 2절 제목에
    region 을 세워 읽는다(쪽마다 region, 리뷰 I2 뒤 규약)."""
    for g in r.grids:
        one = g.head(r"^1\.퇴직급여충당금조정")
        two = g.head(r"^2\.총급여액")
        start = one if one is not None else two
        if start is None:
            continue
        r.region[g.page_no] = start.top
        _labelled(r, g, _32, start.bottom)
        if two is not None:
            _p32_rows(r, g, two)


def _p32_rows(r: Reader, g: Grid, two: Box) -> None:
    """32 2절 계정명 줄((17)·(18)·(19) 인원·금액). 머리글은 세 묶음(총급여액·지급대상 아닌·지급대상)의 인원·금액이다."""
    groups = [("17", r"^총급여액$"), ("18", r"^퇴직급여지급대상이아닌"), ("19", r"^퇴직급여지급대상이되는")]
    heads = {}
    for code, rx in groups:
        top = g.head(rx, top=two.bottom - 1)
        if top is None:
            continue
        for sub, srx in (("_1", r"^인원$"), ("", r"^금액$")):
            b = g.head(srx, top=top.bottom - 1, bottom=top.bottom + 1, left=top.left, right=top.right)
            if b is not None:
                heads[code + sub] = b
    # 첫 열 머리글은 대각선으로 나뉜 칸이라 글이 '구분계정명' 이다(태스크 5·6 리뷰 I2. 전에는 '^계정명' 이라 줄을 하나도 읽지 않았다)
    name = g.head(r"^(구분)?계정명", top=two.bottom - 1)
    if name is None or not heads:
        return
    heads["계정명"] = name
    r.mark(g, *heads.values())
    n = 0
    for line in g.band(max(h.bottom for h in heads.values()) - 1, 1e9, name.left - 1, heads.get("19", name).right + 1):
        cols = {}
        for b in line:
            col = column(b, heads)
            if col is not None:
                cols.setdefault(col, b)
        label = norm(g.text(cols["계정명"])) if "계정명" in cols else ""
        if not label:
            continue
        if label == "계":
            r.mark(g, cols.pop("계정명"))
            for item, b in cols.items():
                r.put(g, b, f"계_{item}")
            continue
        n += 1
        for item, b in cols.items():
            r.put(g, b, item, n, "text" if item == "계정명" else "won")


_34 = [("1", r"^①채권잔액", None), ("3", r"^③한도액", None), ("4", r"^④당기계상액", None), ("5", r"^⑤보충액", None),
       ("6", r"^⑥계$", None), ("7", r"^⑦한도초과액", None), ("8", r"^⑧장부상", None), ("9", r"^⑨기중", None),
       ("10", r"^⑩충당금", None), ("11", r"^⑪당기대손금", None), ("12", r"^⑫당기설정", None), ("13", r"^⑬환입할금액", None),
       ("14", r"^⑭회사", None), ("15", r"^⑮과소환입", None)]
# 34 절 제목. 쪽마다 가장 위 절 제목이 표 시작(region)이다
_34_SECTIONS = r"^[1-5]\.(대손충당금조정|대손금조정|한국채택국제회계기준|해외건설자회사)"


def _rate_cells(r: Reader, g: Grid, rate: Box) -> None:
    """율 머리글(34 ② 설정률, 4절 손금산입률) 아래 칸을 읽고 버린다. 율은 금액이 아니고 당기 수식 란이다."""
    r.mark(g, *[b for b in g.boxes if rate.left - 1 <= b.xc <= rate.right + 1 and rate.bottom - 1 <= b.top
                and b.bottom <= rate.bottom + 70])


def _p34(r: Reader) -> None:
    """34 1절(①~⑮ 칸)과 채권잔액 표((16)~(21) 줄, 계 줄). ② 설정률은 (ㄱ)·(ㄴ)·(ㄷ) 세 칸과 '1'·'100' 로 쌓인 분수라 읽지
    않는다(② 는 당기 수식 란이고 채점도 뺀다, 사전 조사 §9.2). 2절 대손금 표와 4·5절 해외건설자회사 표는 당기 기초로 쓰지 않아
    읽지 않는다. 금액이 있으면 '이름없음' 확인사항이 된다. 채권잔액 표의 비고 열은 34 정의에 란이 없어 읽지 않는다(B2 계획 H1)."""
    for g in r.grids:
        one = g.head(r"^1\.대손충당금조정")
        sections = g.find(_34_SECTIONS)
        if sections:
            # 4·5절만 있는 쪽(FY2025 50쪽)도 skip 하지 않고 region 을 세운다. 그 표에 회사가 적은 금액은 읽지 않지만 조용히 빠지면
            # 안 되므로 '이름없음' 으로 올린다(B2 계획 H12). 그 쪽의 금액 모양 칸은 손금산입률 칸의 인쇄 율(작은 글자 '10')
            # 뿐이라 아래 _rate_cells 가 1절 ② 설정률처럼 읽고 버린다
            r.region[g.page_no] = min(b.top for b in sections)
        for rate in g.find(r"^손금산입률$"):
            _rate_cells(r, g, rate)
        if one is not None:
            rate = g.head(r"^②설정률")
            if rate is not None:
                _rate_cells(r, g, rate)
            _labelled(r, g, _34, one.bottom)
        heads34 = g.find(r"^계정과목$", top=(one.bottom if one else -1e9))
        head = heads34[0] if heads34 else None
        if head is not None and one is not None:
            specs = {"16": r"^계정과목$", "17": r"^채권잔액의장부가액", "18": r"^기말현재대손금부인누계", "19": r"^합계",
                     "20": r"^충당금설정제외", "21": r"^채권잔액\("}
            heads = _heads(g, specs, top=head.top - 1, bottom=head.top + 1)
            stop = next(iter(g.find(r"^2\.", top=head.bottom)), None)
            _simple_table(r, g, heads, {"16"}, {"계": ["17", "18", "19", "20", "21"]},
                          bottom=stop.top if stop else 1e9)
    for i in ("17", "19", "21"):
        _sum_check(r, f"계_{i}", i, f"34호 채권잔액 표 계 {column_name('34', i)} = 줄 합계")
    if r.value("1") is not None or r.value("계_21") is not None:
        r.check(("34", "1"), ("34", "계_21"), r.value("1"), r.value("계_21"),
                f"34호 {column_name('34', '1')} = 채권잔액 표 계 {column_name('34', '21')}")


def _p23eul(r: Reader) -> None:
    """23(을). 1. 수입금액명세(①②③ 머리글 아래 값)와 2. 계정과목 열 표(④ 줄의 계정명 칸이 열, 합계 열). ⑯ 은 번호가 글자층에
    없어 '총초과금액' 이름으로 정한다(사전 조사 §5). region 은 두 표 중 위의 머리글이다(2절만 있는 쪽도 region 이 선다). 계정 열
    번호는 쪽을 넘어 잇는다(계정이 많아 2절이 두 쪽이 되면 쪽마다 1 부터 세어 같은 란이 두 벌이 됐다, 태스크 5·6 리뷰 I3)."""
    rows = [("5", r"^⑤계정금액"), ("6", r"^⑥기업업무추진비계상액"), ("7", r"^⑦기업업무추진비해당금액"),
            ("9", r"^⑨"), ("10", r"^⑩"), ("11", r"^⑪"), ("12", r"^⑫"), ("13", r"^⑬"), ("14", r"^⑭"), ("15", r"^⑮"),
            ("16", r"^(\(16\))?총초과금액$"), ("17", r"^(\(17\))?신용카드등미사용부인액"), ("18", r"^(\(18\))?기업업무추진비부인액")]
    n = 0
    for g in r.grids:
        income = _heads(g, {"1": r"^①일반수입금액", "2": r"^②특수관계인간", "3": r"^③합계"})
        if income:
            r.region[g.page_no] = min(h.top for h in income.values())
            r.mark(g, *income.values())
            for b, t in g.boxes.items():
                col = column(b, income)
                if col is not None and b.top >= max(h.bottom for h in income.values()) - 1 and amount(t) is not None \
                        and b.top < max(h.bottom for h in income.values()) + 60:
                    r.put(g, b, col)
        acct = g.head(r"^④계정과목")
        if acct is None:
            continue
        r.region[g.page_no] = min(r.region.get(g.page_no, 1e9), acct.top)
        r.mark(g, acct)
        line = g.band(acct.top - 1, acct.top + 1)
        cols = sorted((b for b in (line[0] if line else []) if b != acct and g.text(b)), key=lambda b: b.left)
        heads = {}
        for b in cols:
            if norm(g.text(b)) == "합계":
                heads["합계"] = b
                r.mark(g, b)
            else:
                n += 1
                heads[str(n)] = b
                r.put(g, b, "4", n, "text")
        labels = {}
        for b, t in g.boxes.items():
            if b.right <= acct.right + 1 and b.top >= acct.bottom - 1:
                for item, rx in rows:
                    if re.search(rx, norm(t)) and item not in labels:
                        labels[item] = b
                        r.mark(g, b)
                        break
        for item, lab in labels.items():
            for b, t in g.boxes.items():
                if abs(b.top - lab.top) > 2 or b.left < acct.right - 1:
                    continue
                col = column(b, heads)
                if col is None or amount(t) is None:
                    continue
                if col == "합계":
                    r.put(g, b, f"합계_{item}")
                else:
                    r.put(g, b, item, int(col))
    for i in ("5", "7", "16"):
        _sum_check(r, f"합계_{i}", i, f"23호(을) 합계 {column_name('23을', i)} = 계정 합")


# ---------------------------------------------------------------- 란 이름(검산 제목·확인사항 카드)

_COL_MARK = re.compile(r"^([①-⑳]|\(\d+\))")         # 인쇄된 열 번호(원문자·(번호))
_COL_END = re.compile(r"\s*(?:\(|\{|MAX\(|MIN\()")      # 열 이름 뒤에 붙은 계산식·덧붙임 괄호
_TOTAL_PREFIX = ("손금불산입계", "합계", "계")               # 합계 줄 란 '<인쇄 이름>_<열 코드>' 의 앞 토막
CODED = ("50갑", "20_4", "8을", "8부표3")                     # 코드 칸이 줄 열쇠인 격자 서식(인쇄된 '코드' 열로 줄을 찾는다)


def column_name(fc: str, code: str, short: bool = False) -> str:
    """란의 인쇄된 열 이름(태스크 7 리뷰 I2·M1). 서식 정의의 란 이름(values.item_name)에서 마지막 원문자·(번호) 토막부터이고,
    뒤에 붙은 계산식·덧붙임 괄호('③한도액 (①×②)' 의 '(①×②)', '⑤기말잔액(익기초현재)', 'MAX(…)')는 뗀다. 계산식 괄호 안의
    번호('⑩추계액 대비 설정액 ( (22) × 설정률)' 의 (22))는 열 번호가 아니다. 원문자·번호가 없으면 마지막 토막(계정명·비고),
    정의에 없는 란이면 란 코드 그대로. short 면 열 번호만 남긴다(인원·금액으로 끝나면 그것은 둔다)."""
    toks = item_name(fc, code).split()
    if not toks:
        return code
    depth, start = 0, None
    for i, t in enumerate(toks):
        if depth == 0 and _COL_MARK.match(t):
            start = i
        depth += t.count("(") + t.count("{") - t.count(")") - t.count("}")
    if start is None:
        return toks[-1]
    text = " ".join(toks[start:])
    mark = _COL_MARK.match(text).group(1)
    if short:
        return mark + (f" {toks[-1]}" if toks[-1] in ("인원", "금액") and len(toks) > start + 1 else "")
    return (mark + _COL_END.split(text[len(mark):], maxsplit=1)[0]).strip()


def cell_label(fc: str, code: str, row: int, short: bool = False) -> str:
    """란 하나를 인쇄된 서식에서 찾을 수 있게 부르는 말(태스크 7 리뷰 I2. 전에는 '2 란'·'합계_2 란' 처럼 내부 코드로 불렀다).
    줄 란은 '3줄 ②금액'(23을 은 계정이 열이라 '2번째 계정 ⑤계정금액'), 합계 줄 란은 '합계 ②금액', 코드 줄 란은 인쇄된 코드로
    '코드 01 ②기초잔액', 칸마다 번호가 붙은 란(32·34·23을 1절)은 열 이름 그대로다. short 는 column_name 과 같다(제목 40자)."""
    col = column_name(fc, code, short)
    total = next((t for t in _TOTAL_PREFIX if code.startswith(t + "_")), None)
    if total:
        return f"{total} {col}"
    if row >= 1:
        return f"{row}번째 계정 {col}" if fc == "23을" else f"{row}줄 {col}"
    if fc in CODED and not code.startswith("결손_"):
        return f"코드 {code.split('_')[0]} {col}"
    return col


# ---------------------------------------------------------------- 21

def _p21(r: Reader) -> None:
    """격자로는 읽지 않는다. 뒤쪽 5 · 6절(기부금 이월액)은 form21.py 가 낱말 좌표로 읽어 rows["21"] 에 넣고(read.build),
    앞쪽 ① ~ ⑳ 은 당기 소득으로 다시 계산하므로 읽지 않는다(fx4). 전에는 「21 서식은 아직 읽지 않는 서식이다」 확인사항을 냈다."""


PARSERS = {"15": _p15, "15부표1": _p15sub, "15부표2": _p15sub, "50을": _p50eul, "50갑": _p50gap, "20_4": _p20_4,
           "8부표3": _p8bu3, "8을": _p8eul, "32": _p32, "34": _p34, "23을": _p23eul, "세금공과금명세서": _p_dues,
           "선급비용명세서": _p_prepaid, "21": _p21}


def parse(form_code: str, pages: list) -> tuple:
    """서식 하나의 쪽들(split_pages dict 에 'grid' 가 있다) → (Cell 목록, Problem 목록). 파서가 없는 서식이나 격자 자료가 없는
    쪽뿐이면 빈 결과다. 쪽 번호는 Reader 가 Problem.why 에 이미 적는다. 21(틀만)을 뺀 서식은 끝에 쓰지 않은 금액 칸을 본다."""
    fn = PARSERS.get(form_code)
    r = Reader(form_code, [p for p in pages if p.get("grid")])
    if fn is None or not r.grids:
        return [], []
    fn(r)
    if form_code != "21":
        r.leftovers()
    return r.cells, r.problems
