"""칸 테두리 선으로 칸을 만들고 글자를 칸에 넣는 결정론 격자(단계 B B2, 사전 조사 §5).

전기 세무조정계산서 PDF(국세청 일괄출력, 아마란스)는 표마다 칸 테두리 선이 그려져 있다. 머리글 x 로 열을 정하고 y 로 행을
묶는 방식은 한 줄짜리 표에서만 믿을 만하고(꺾인 글자·오른쪽 정렬 숫자·병합 칸에서 깨진다) 단어 단위 읽기(get_text('words'))는
이웃 span 을 붙이거나('…2501등록면허세구청') 숫자를 쪼갠다('161'+',690,000'). 그래서 선으로 칸을 만들고 글자 하나하나를
중심점으로 칸에 넣는다. AI 는 쓰지 않는다.

  lines(page)          (V, H). V=[(x, y0, y1)] 세로선, H=[(y, x0, x1)] 가로선. get_drawings 의 선(l), 한 변이 SEG_THIN 보다
                       얇은 사각형(선으로 그린 것), 그 밖의 사각형은 네 변이다. SEG_MIN 보다 짧은 선은 버린다.
  chars(page)          [(x0, y0, x1, y1, 글자)]. rawdict 글자 단위이고 공백은 뺀다.
  page_data(page)      {"V", "H", "chars"}. 쪽 분리(prior_pdf.split_pages)가 격자 서식 쪽에만 붙인다(fitz 객체를 들고 다니지
                       않게 튜플 목록으로).
  Grid(V, H, chars)    칸(Box) → 글. 글자 중심을 둘러싼 가장 가까운 왼쪽·오른쪽 세로선과 위·아래 가로선이 칸이다. 선이 빠진
                       곳(50갑 왼쪽 외곽, 23을·32 왼쪽 이름칸, 8부표3 20쪽 머리글 아래)은 세로선 끝점을 위·아래로, 칸 위·아래
                       가로선의 끝점을 왼쪽·오른쪽으로 쓴다. 칸 안 글은 reading_order 순으로 잇는다(꺾인 글자가 한 값이 된다).
  reading_order(items) 글자·단어를 y 중심으로 정렬해 앞 것과 LINE_BAND/2 넘게 벌어지면 새 줄, 줄 안은 x 순.
  norm(text)           공백을 지우고 전각 괄호·가운뎃점을 맞춘 글. 머리글·과목 비교에 쓴다.
  amount(text)         금액이면 정수(음수는 '-'·'△'·'▲'·U+2212·'(1,234)'), 아니면 None.

Grid 의 도우미(전부 공개 이름, 파서 prior_grid 가 쓴다)
  text(box)·bbox(box)   칸 글·칸 안 글자들의 테두리.
  find(pattern, ...)    norm(글)이 정규식에 맞는 칸(위→아래, 왼쪽→오른쪽). 위치 범위로 거른다.
  head(pattern, ...)    find 중 가장 좁은 칸(머리글은 병합된 넓은 칸과 좁은 칸이 겹친다).
  band(top, bottom, ..) 칸 위쪽 y 가 [top, bottom) 안인 칸을 위쪽 y(ROW_TOL 안)로 묶은 줄 목록.
  column(box, heads)    칸 가운데 x 가 머리글 x 범위(COL_TOL 여유)에 드는 머리글 중 가장 좁은 것의 이름.
"""
import re
from typing import NamedTuple

SEG_MIN = 4.0          # 선으로 보는 최소 길이(pt)
SEG_THIN = 2.0         # 이보다 얇은 사각형은 선이다
SEG_MERGE = 1.0        # 같은 선이 0.1~0.4pt 어긋나 두세 번 그려진다. 이 안이면 한 선이다
EDGE_TOL = 1.0         # 선 끝이 글자 중심을 지나는지 볼 때의 여유
LINE_BAND = 3.0        # 줄 간격 기준. 앞 글자와 y 중심이 LINE_BAND/2 넘게 벌어지면 새 줄이다(reading_order)
ROW_TOL = 2.0          # 같은 줄로 보는 칸 위쪽 y 차이
COL_TOL = 1.0          # 머리글 x 범위 여유

_AMOUNT = re.compile(r"^[△-]?(\d{1,3}(,\d{3})+|\d+)$")
_PAREN = re.compile(r"^\((\d{1,3}(?:,\d{3})+)\)$")     # 괄호 음수. 천 단위 쉼표가 있을 때만('(16)' 같은 칸 번호와 가른다)
_FULLWIDTH = str.maketrans({"（": "(", "）": ")", "＋": "+", "－": "-", "−": "-", "▲": "△", "ㆍ": "·", "∙": "·",
                            "・": "·", "，": ","})


class Box(NamedTuple):
    top: float
    bottom: float
    left: float
    right: float

    @property
    def xc(self) -> float:
        return (self.left + self.right) / 2

    @property
    def yc(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def width(self) -> float:
        return self.right - self.left


def norm(text: str) -> str:
    """비교용 글. 공백을 지우고 전각 괄호·기호, 빼기 부호(U+2212 → -)·▲(→ △), 가운뎃점(ㆍ∙・ → ·)을 맞춘다."""
    return re.sub(r"\s+", "", (text or "").translate(_FULLWIDTH))


def amount(text: str):
    """금액 글이면 정수. '1,234'·'-1,234'·'△1,234'·'1234', 음수 표시 '▲'·U+2212(norm 이 맞춘다)와 괄호 '(1,234)'(리뷰 M2).
    괄호는 천 단위 쉼표가 있을 때만 금액이다. 아니면 None(빈칸도 None)."""
    t = norm(text)
    m = _PAREN.match(t)
    if m:
        return -int(m.group(1).replace(",", ""))
    if not _AMOUNT.match(t):
        return None
    n = int(t.lstrip("△-").replace(",", ""))
    return -n if t[0] in "△-" else n


def _merge(segs: list) -> list:
    """(위치, 시작, 끝) 목록에서 위치가 SEG_MERGE 안이고 구간이 겹치는 선을 하나로. 합친 선이 앞서 따로 남은 선과 새로
    겹칠 수 있어(뒤 선이 두 선을 잇는 경우) 결과가 바뀌지 않을 때까지 다시 훑는다(리뷰 M5)."""
    out = sorted(segs)
    while True:
        nxt: list = []
        for p, a, b in out:
            for i, (q, c, d) in enumerate(nxt):
                if abs(p - q) <= SEG_MERGE and a <= d + SEG_MERGE and c <= b + SEG_MERGE:
                    nxt[i] = (q, min(a, c), max(b, d))
                    break
            else:
                nxt.append((p, a, b))
        nxt.sort()
        if nxt == out:
            return out
        out = nxt


def lines(page) -> tuple:
    """쪽의 (세로선, 가로선)."""
    V, H = [], []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.x - b.x) < SEG_THIN / 2 and abs(a.y - b.y) >= SEG_MIN:
                    V.append((a.x, min(a.y, b.y), max(a.y, b.y)))
                elif abs(a.y - b.y) < SEG_THIN / 2 and abs(a.x - b.x) >= SEG_MIN:
                    H.append((a.y, min(a.x, b.x), max(a.x, b.x)))
            elif it[0] == "re":
                r = it[1]
                if r.width < SEG_THIN and r.height >= SEG_MIN:
                    V.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif r.height < SEG_THIN and r.width >= SEG_MIN:
                    H.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif r.width >= SEG_MIN and r.height >= SEG_MIN:
                    V += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
                    H += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
    return _merge(V), _merge(H)


def chars(page) -> list:
    """쪽의 글자 [(x0, y0, x1, y1, 글자)]. 공백은 뺀다."""
    out = []
    for b in page.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                for c in s["chars"]:
                    if not c["c"].isspace():
                        x0, y0, x1, y1 = c["bbox"]
                        out.append((x0, y0, x1, y1, c["c"]))
    return out


def reading_order(items: list, gap: float = LINE_BAND / 2) -> list:
    """글자·단어 [(x0, y0, x1, y1, 글, ...)] 를 읽는 순서로. y 중심으로 정렬한 뒤 앞 것과 gap 넘게 벌어지면 새 줄이고, 줄 안은
    x 순이다. y 를 구간으로 반올림하면 같은 줄 글자 y 가 0.001~0.006pt 흔들리다 구간 경계에 걸릴 때 한 줄이 둘로 갈려 순서가
    뒤섞인다('16B' 가 '61B', '10,000,000' 이 '0000010,0,', 리뷰 I1). 칸 글(Grid), 8부표3 2절 값(prior_grid), 쪽 머리 글
    (prior_pdf) 이 같이 쓴다."""
    out, line, last = [], [], None
    for it in sorted(items, key=lambda c: ((c[1] + c[3]) / 2, c[0])):
        y = (it[1] + it[3]) / 2
        if last is not None and y - last > gap:
            out += sorted(line, key=lambda c: c[0])
            line = []
        line.append(it)
        last = y
    return out + sorted(line, key=lambda c: c[0])


def page_data(page) -> dict:
    """격자 서식 쪽 하나를 읽는 데 필요한 것(선·글자). split_pages 가 쪽 dict 의 'grid' 에 둔다."""
    V, H = lines(page)
    return {"V": V, "H": H, "chars": chars(page)}


def _cell_of(xc: float, yc: float, V: list, H: list):
    L = [v[0] for v in V if v[0] <= xc and v[1] - EDGE_TOL <= yc <= v[2] + EDGE_TOL]
    R = [v[0] for v in V if v[0] > xc and v[1] - EDGE_TOL <= yc <= v[2] + EDGE_TOL]
    T = [h[0] for h in H if h[0] <= yc and h[1] - EDGE_TOL <= xc <= h[2] + EDGE_TOL]
    B = [h[0] for h in H if h[0] > yc and h[1] - EDGE_TOL <= xc <= h[2] + EDGE_TOL]
    if not (T and B):
        # 가로선이 빠진 곳: 글자 높이를 지나는 세로선 중 이 칸의 왼쪽·오른쪽 세로선(max(L)·min(R) 위치)의 끝점을 위·아래
        # 경계로 쓴다. 다른 열의 세로선 끝점을 쓰면 한 칸이 둘로 갈린다(리뷰 M1)
        sides = [x for x in (max(L, default=None), min(R, default=None)) if x is not None]
        own = [v for v in V if any(abs(v[0] - x) <= SEG_MERGE for x in sides)]
        T = T or [v[1] for v in own if v[1] <= yc <= v[2] + EDGE_TOL]
        B = B or [v[2] for v in own if v[1] <= yc < v[2]]
    if T and B and not (L and R):
        # 세로선이 빠진 곳: 칸 위·아래 가로선의 끝점을 왼쪽·오른쪽 경계로 쓴다
        t, b = max(T), min(B)
        ends = [h for h in H if abs(h[0] - t) < 1.5 or abs(h[0] - b) < 1.5]
        L = L or [h[1] for h in ends if h[1] <= xc]
        R = R or [h[2] for h in ends if h[2] > xc]
    if not (L and R and T and B):
        return None
    return Box(round(max(T)), round(min(B)), round(max(L)), round(min(R)))


class Grid:
    """쪽 하나의 칸. boxes 는 {Box: 글}, loose 는 칸에 들지 않은 글자(쪽 머리 표시·쪽 번호). V·H·chars 는 받은 그대로다
    (8부표3 2절처럼 칸이 아니라 글자를 띠로 나누는 파서가 쓴다)."""

    def __init__(self, V: list, H: list, chars_: list, page_no: int | None = None):
        self.page_no = page_no
        self.V, self.H, self.chars = V, H, chars_
        members: dict = {}
        self.loose = []
        for c in chars_:
            box = _cell_of((c[0] + c[2]) / 2, (c[1] + c[3]) / 2, V, H)
            if box is None:
                self.loose.append(c)
            else:
                members.setdefault(box, []).append(c)
        self._chars = members
        self.boxes = {box: "".join(c[4] for c in reading_order(cs)) for box, cs in members.items()}

    @classmethod
    def from_page(cls, page_dict: dict) -> "Grid":
        """split_pages 쪽 dict(격자 서식 쪽이면 'grid' 가 있다)."""
        g = page_dict["grid"]
        return cls(g["V"], g["H"], g["chars"], page_dict.get("page_no"))

    def text(self, box: Box) -> str:
        return self.boxes.get(box, "")

    def chars_in(self, box: Box) -> list:
        """칸 안 글자 [(x0, y0, x1, y1, 글자)]."""
        return list(self._chars.get(box, []))

    def bbox(self, box: Box) -> tuple:
        cs = self._chars.get(box, [])
        if not cs:
            return (box.left, box.top, box.right, box.bottom)
        return (round(min(c[0] for c in cs), 1), round(min(c[1] for c in cs), 1),
                round(max(c[2] for c in cs), 1), round(max(c[3] for c in cs), 1))

    def find(self, pattern: str, top: float = -1e9, bottom: float = 1e9, left: float = -1e9,
             right: float = 1e9) -> list:
        """norm(글)이 pattern(re.search)에 맞고 칸 위쪽 y 가 [top, bottom], 가운데 x 가 [left, right] 인 칸."""
        rx = re.compile(pattern)
        out = [b for b, t in self.boxes.items()
               if top <= b.top <= bottom and left <= b.xc <= right and rx.search(norm(t))]
        return sorted(out, key=lambda b: (b.top, b.left))

    def head(self, pattern: str, **where) -> Box | None:
        """find 중 가장 좁은 칸. 없으면 None."""
        found = self.find(pattern, **where)
        return min(found, key=lambda b: (b.width, b.top)) if found else None

    def band(self, top: float, bottom: float, left: float = -1e9, right: float = 1e9) -> list:
        """위쪽 y 가 [top, bottom) 이고 가운데 x 가 [left, right] 인 칸을 줄로 묶는다. [[Box, ...], ...] 위에서 아래로,
        줄 안은 왼쪽에서 오른쪽으로. 칸 높이가 달라도(병합 칸) 위쪽 y 가 ROW_TOL 안이면 같은 줄이다."""
        cells = sorted((b for b in self.boxes if top <= b.top < bottom and left <= b.xc <= right),
                       key=lambda b: (b.top, b.left))
        rows: list = []
        for b in cells:
            if rows and abs(rows[-1][0].top - b.top) <= ROW_TOL:
                rows[-1].append(b)
            else:
                rows.append([b])
        return [sorted(r, key=lambda b: b.left) for r in rows]


def column(box: Box, heads: dict):
    """칸이 속한 열 이름. heads 는 {이름: 머리글 Box}. 칸 가운데 x 가 머리글 x 범위(COL_TOL 여유)에 드는 것 중 가장 좁은
    머리글. 없으면 None."""
    hit = [(h.width, name) for name, h in heads.items() if h.left - COL_TOL <= box.xc <= h.right + COL_TOL]
    return min(hit)[1] if hit else None
