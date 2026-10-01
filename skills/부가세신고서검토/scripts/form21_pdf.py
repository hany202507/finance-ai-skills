# -*- coding: utf-8 -*-
"""**서식 원본 PDF 에 값만 얹어** 부가가치세 신고서를 만든다.

HTML 로 서식을 다시 그리지 않는다. 폰트·자간·선 굵기·칸 병합을 아무리 맞춰도
원본과 같아지지 않는다. 국가법령정보센터에서 받은 별지 제21호서식 PDF 를 그대로 깔고
숫자와 글자만 칸에 써 넣는다. **서식은 100퍼센트 원본이다.**

  제1쪽 본지 + 제4쪽 (36)~(90) 두 장을 뽑는다. 홈택스 출력물이 그 모양이다.

## 어떻게 칸을 찾나

서식 PDF 가 벡터라 글자와 표 선이 살아 있다. 란 번호 「(1)」「(44)」를 낱말로 찾아
그 줄의 y 를 잡고, 표의 세로선에서 뽑은 열 경계로 x 를 잡는다.
**좌표를 손으로 박지 않는다.** 서식이 개정돼 칸이 밀려도 란 번호만 그대로면 따라간다.

서식 원본은 스킬 폴더 `assets/별지21호_일반과세자_부가가치세신고서.pdf` 다.
개정판이 나오면 `python assets/_받기.py` 로 다시 받는다.

한글 글꼴은 맑은 고딕(윈도우) · Apple SD Gothic Neo(맥) · 나눔고딕·Noto Sans CJK(리눅스)
순서로 찾고, 하나도 없으면 PyMuPDF 에 든 CJK 글꼴(Droid Sans Fallback)을 쓴다.
`VAT_FONT` 환경변수에 글꼴 파일 경로를 주면 그것을 먼저 쓴다.
"""
import os
import re
import sys

import fitz

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
FORM_NAME = "별지21호_일반과세자_부가가치세신고서.pdf"
FORM = os.path.normpath(os.path.join(HERE, "..", "assets", FORM_NAME))

RAN = re.compile(r"^\(\d{1,2}\)$")


def _font_candidates():
    """운영체제별 한글 글꼴 후보. 앞에 있는 것부터 쓴다."""
    env = os.environ.get("VAT_FONT")
    out = [env] if env else []
    win = os.environ.get("WINDIR", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    out += [os.path.join(win, "Fonts", "malgun.ttf"),
            os.path.join(local, "Microsoft", "Windows", "Fonts", "malgun.ttf") if local else "",
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
            "/Library/Fonts/NanumGothic.ttf",
            os.path.expanduser("~/Library/Fonts/NanumGothic.ttf"),
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/nanum/NanumGothic.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"]
    return [p for p in out if p]


def load_font():
    """(fitz.Font, 글꼴 바이트, 출처) 를 돌려준다.

    재는 글꼴과 쓰는 글꼴이 같아야 숫자가 옆 칸을 침범하지 않는다. 그래서 한 벌을
    정해 두 곳에 같이 쓴다. 시스템 글꼴이 없으면 PyMuPDF 에 든 CJK 글꼴을 쓴다."""
    for p in _font_candidates():
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    buf = f.read()
                return fitz.Font(fontbuffer=buf), buf, p
            except Exception:  # noqa: BLE001  글꼴을 못 읽으면 다음 후보
                continue
    f = fitz.Font("cjk")
    return f, f.buffer, "PyMuPDF 내장 CJK"


def find_form(extra=None):
    """서식 원본을 찾는다. 못 찾으면 None."""
    for p in [extra, FORM]:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    return None


def _cols(page):
    """표의 세로선에서 열 경계를 뽑는다. 손으로 박은 좌표를 쓰지 않는다."""
    xs = {}
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 0.6:
                xs[round(it[1].x, 1)] = xs.get(round(it[1].x, 1), 0) \
                    + abs(it[1].y - it[2].y)
            elif it[0] == "re" and it[1].width < 0.6:
                xs[round(it[1].x0, 1)] = xs.get(round(it[1].x0, 1), 0) \
                    + it[1].height
    return sorted(x for x, ln in xs.items() if ln > 40)


def _anchors(page):
    out = {}
    for w in page.get_text("words"):
        if RAN.match(w[4]) and w[4] not in out:
            out[w[4]] = (w[0], w[1], w[2], w[3])
    return out


class Sheet:
    """한 쪽에 글자를 얹는다. 좌표는 란 번호와 열 경계에서 나온다."""

    def __init__(self, page, font, buf):
        self.p = page
        self.f = font
        page.insert_font(fontname="F0", fontbuffer=buf)
        self.a = _anchors(page)
        self.cols = _cols(page)

    def col_after(self, x):
        """x 오른쪽의 첫 세로선. 그 칸의 오른쪽 끝이다."""
        for c in self.cols:
            if c > x + 1:
                return c
        return self.p.rect.x1 - 10

    def right(self, x0, y0, y1, text, size=8, pad=5):
        """칸 오른쪽에 붙여 쓴다. 금액은 전부 오른쪽 정렬이다."""
        if text in ("", None):
            return
        w = self.f.text_length(str(text), fontsize=size)
        self.p.insert_text((x0 - pad - w, (y0 + y1) / 2 + size * 0.35),
                           str(text), fontsize=size, fontname="F0")

    def at(self, x, y, text, size=8):
        if text in ("", None):
            return
        self.p.insert_text((x, y), str(text), fontsize=size, fontname="F0")

    def fit(self, text, size, width):
        """칸 폭에 맞게 자른다. 넘치면 옆 칸을 덮어 둘 다 못 읽게 된다."""
        t = str(text)
        while t and self.f.text_length(t, fontsize=size) > width - 2:
            t = t[:-1]
        return t

    def center(self, x0, x1, y0, y1, text, size=8):
        if text in ("", None):
            return
        text = self.fit(text, size, x1 - x0)
        w = self.f.text_length(str(text), fontsize=size)
        self.p.insert_text(((x0 + x1) / 2 - w / 2, (y0 + y1) / 2 + size * 0.35),
                           str(text), fontsize=size, fontname="F0")

    def row(self, no):
        return self.a.get(no)


def won(v):
    if v in ("", None):
        return ""
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def biz(no):
    d = "".join(c for c in str(no) if c.isdigit())
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if len(d) == 10 else str(no)


# ── 칸 찾기 ──────────────────────────────────────────────────
def _vlines(page):
    """세로선을 (x, y0, y1) 로 모은다. 줄마다 어느 칸인지 알아야 해서 y 가 필요하다."""
    out = []
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 0.6:
                y0, y1 = sorted((it[1].y, it[2].y))
                if y1 - y0 > 2:
                    out.append((round(it[1].x, 1), y0, y1))
            elif it[0] == "re" and it[1].width < 0.6 and it[1].height > 2:
                out.append((round(it[1].x0, 1), it[1].y0, it[1].y1))
    return out


def _edge(page):
    import collections
    c = collections.Counter()
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) < 0.6:
                c[round(max(it[1].x, it[2].x), 1)] += 1
            elif it[0] == "re" and it[1].height < 0.6:
                c[round(it[1].x1, 1)] += 1
    return c.most_common(1)[0][0]


def _headcols(page):
    """표 머리의 「금액」「세율」「세액」으로 열 오른쪽 끝을 잡는다.

    세로선을 세어 짐작하지 않는다. 머리 글자가 어느 칸에 있는지가 정답이다."""
    words = page.get_text("words")
    hdr = {}
    for w in words:
        if w[4] in ("금액", "세율", "세액") and w[4] not in hdr:
            hdr[w[4]] = (w[0] + w[2]) / 2
    if "세율" not in hdr:
        return None
    # **짧은 선을 쓰면 안 된다.** 세율 칸 안에도 눈금 같은 짧은 세로선이 있어서
    # 그걸 열 경계로 잡으면 금액이 세율 칸으로 넘어간다. 한 번 그렇게 냈다.
    # 열을 가르는 선은 표 높이만큼 길다. `_cols` 가 길이로 거른 것만 본다
    xs = _cols(page)
    amt_r = max((x for x in xs if x < hdr["세율"] - 2), default=None)
    return {"amt_r": amt_r, "tax_r": _edge(page)}


def _cell_right(page, x_from, y):
    """(x_from, y) 오른쪽에서 그 줄을 지나는 첫 세로선. 그 칸의 오른쪽 끝이다."""
    cand = [x for x, y0, y1 in _vlines(page)
            if x > x_from + 1 and y0 - 1 <= y <= y1 + 1]
    return min(cand) if cand else _edge(page)


def _erase_line(page, key, x_max=None):
    """그 낱말이 든 줄을 흰색으로 덮는다.

    홈택스 출력물에는 「※ 제2쪽 및 제3쪽의 작성방법을…」 줄이 없다. 서식 원본을
    그대로 깔고 있어서 남는다. **1쪽은 쪽 표기가 같은 줄에 있어** x_max 로 왼쪽만 덮는다."""
    hit = next((w for w in page.get_text("words") if key in w[4]), None)
    if not hit:
        return
    y = (hit[1] + hit[3]) / 2
    line = [w for w in page.get_text("words")
            if abs((w[1] + w[3]) / 2 - y) < 3
            and (x_max is None or w[2] <= x_max)]
    if not line:
        return
    page.draw_rect(fitz.Rect(min(w[0] for w in line) - 2,
                             min(w[1] for w in line) - 1,
                             max(w[2] for w in line) + 2,
                             max(w[3] for w in line) + 1),
                   color=None, fill=(1, 1, 1))


def _page_label(page, sheet, text):
    """쪽 표기를 덮어쓴다. 서식 원본은 「(6쪽 중 제1쪽)」이고 홈택스는 「(제1장 앞쪽)」이다."""
    ws = [w for w in page.get_text("words") if w[4].endswith("쪽)") or w[4] == "중"
          or w[4].startswith("(6쪽")]
    ws = [w for w in ws if w[1] < 95]
    if not ws:
        return
    x0 = min(w[0] for w in ws) - 2
    x1 = max(w[2] for w in ws) + 2
    y0 = min(w[1] for w in ws) - 1
    y1 = max(w[3] for w in ws) + 1
    page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=None, fill=(1, 1, 1))
    sheet.right(x1, y0, y1, text, 7, pad=0)


def _biz_boxes(page, label="사업자등록번호"):
    """사업자등록번호는 한 자리씩 칸이다. 하이픈이 든 칸을 빼고 열 칸을 고른다."""
    hits = [w for w in page.get_text("words") if w[4] == label]
    if not hits:
        return []
    lb = hits[0]
    y = (lb[1] + lb[3]) / 2
    xs = sorted({x for x, y0, y1 in _vlines(page)
                 if y0 - 1 <= y <= y1 + 1 and x > lb[2] - 1})
    if len(xs) < 10:
        return []
    cells = list(zip(xs, xs[1:])) + [(xs[-1], _edge(page))]
    hy = [w for w in page.get_text("words")
          if w[4] == "-" and abs((w[1] + w[3]) / 2 - y) < 5]
    digits = [c for c in cells
              if not any(c[0] <= (h[0] + h[2]) / 2 <= c[1] for h in hy)]
    return [(c[0], c[1], lb[1], lb[3]) for c in digits[:10]]


def _put_biz(page, sheet, no):
    d = "".join(c for c in str(no) if c.isdigit())
    boxes = _biz_boxes(page)
    if len(d) != 10 or len(boxes) < 10:
        return False
    for ch, (x0, x1, y0, y1) in zip(d, boxes):
        sheet.center(x0, x1, y0, y1, ch, 8)
    return True


# ── 본문 ─────────────────────────────────────────────────────
def build(out_path, *, company, rows, p2=None, 확정=True,
          사업자번호="", 대표자="", 주소="", 생년월일="", 사업장전화="",
          주소지전화="", 휴대전화="", 전자우편="", 업태="", 종목="",
          업종코드="", 세무서="", 기간=None, 면세업태="", 면세종목="",
          면세업종코드="", form_path=None):
    """서식 원본 제1쪽·제4쪽을 깔고 값만 써 넣는다.

    `기간` 은 (연도, 기, 시작월, 시작일, 종료월, 종료일) 여섯이다.
    서식에 「년 제 기 ( 월 일 ~ 월 일)」이 이미 인쇄돼 있어 숫자만 사이에 끼운다."""
    src_path = find_form(form_path)
    if not src_path:
        return None, ("서식 원본을 못 찾았습니다. python assets/_받기.py 로 받으십시오 · "
                      + FORM)
    src = fitz.open(src_path)
    doc = fitz.open()
    doc.insert_pdf(src, from_page=0, to_page=0)
    doc.insert_pdf(src, from_page=3, to_page=3)
    # 재는 폰트와 쓰는 폰트가 다르면 숫자가 옆 칸을 침범한다. 한 벌로 재고 쓴다
    font, buf, _ = load_font()

    d = {r[0]: r for r in rows}

    def val(k, i):
        v = d[k][i] if k in d else ""
        return "" if v in ("", None) else v

    g = (p2 or {}).get
    p, q = doc[0], doc[1]
    s, s2 = Sheet(p, font, buf), Sheet(q, font, buf)
    lay, lay2 = _headcols(p), _headcols(q)

    # ── ① 신고내용 ───────────────────────────────────────
    SUP_BLANK = {"(11)", "(19)", "(21)", "(22)", "(23)", "(24)", "(25)",
                 "(26)", "(27)", "(28)", "(29)", "(30)"}
    for no, _, sup, tax in rows:
        r = s.row(no)
        if not r:
            continue
        if no not in SUP_BLANK and sup not in ("", None):
            s.right(lay["amt_r"], r[1], r[3], won(sup), 8)
        if tax not in ("", None):
            s.right(lay["tax_r"], r[1], r[3], won(tax), 8)

    # ㉰ 는 란 번호가 없다. (18) 아래 · (19) 위 줄이다
    r18, r19 = s.row("(18)"), s.row("(19)")
    if r18 and r19:
        s.right(lay["tax_r"], r18[3] + 1, r19[1] - 1, won(val("㉰", 3)), 8)

    # ── 예정·확정 체크 ─────────────────────────────────
    # 서식에서 낱말이 「[」「]예정[」「]확정」으로 쪼개져 있다. 찍을 자리는
    # 「예정」·「확정」이 든 낱말의 왼쪽 대괄호 안이다
    want = "확정" if 확정 else "예정"
    for w in p.get_text("words"):
        if w[1] < 90 and want in w[4] and w[4].startswith("]"):
            s.at(w[0] - 7.5, w[3] - 5.5, "√", 9)
            break

    # ── 신고기간 · 서식에 인쇄된 글자 사이에 숫자만 끼운다 ──
    if 기간:
        row = [w for w in p.get_text("words") if 100 <= w[1] <= 113]
        by = {}
        for w in row:
            by.setdefault(w[4], []).append(w)
        y0, y1 = 102.8, 111.5
        slots = [("년", 0, 0), ("제", 1, 1), ("월", 0, 2), ("일", 0, 3),
                 ("월", 1, 4), ("일)", 0, 5)]
        for tok, nth, idx in slots:
            hits = by.get(tok, [])
            if len(hits) <= nth:
                continue
            w = hits[nth]
            if tok == "제":
                nxt = by.get("기", [None])[0]
                if nxt:
                    s.center(w[2], nxt[0], y0, y1, str(기간[idx]), 8)
            else:
                s.right(w[0], y0, y1, str(기간[idx]), 8, pad=2)

    # ── 사업자 블록 ──────────────────────────────────────
    def fill(label, text, size=8, nth=0, pad=4):
        if not text:
            return
        hits = [w for w in p.get_text("words") if w[4] == label]
        if len(hits) <= nth:
            return
        w = hits[nth]
        y = (w[1] + w[3]) / 2
        s.at(w[2] + pad, w[3] - 1.5, text, size)

    BIZ_Y = (112, 160)

    def word(name, lo=BIZ_Y[0], hi=BIZ_Y[1], nth=0):
        hits = [w for w in p.get_text("words")
                if w[4] == name and lo <= w[1] <= hi]
        return hits[nth] if len(hits) > nth else None

    def put_after(name, text, dx=6, size=8, **kw):
        w = word(name, **kw)
        if w and text:
            s.at(w[2] + dx, w[3] - 1.5, text, size)

    put_after("(법인명)", company)
    put_after("(대표자명)", 대표자)
    put_after("생년월일", 생년월일)
    if not _put_biz(p, s, 사업자번호):
        put_after("사업자등록번호", biz(사업자번호), dx=10)
    put_after("주소", 주소, dx=6, nth=0)          # 사업장 주소
    put_after("전자우편주소", 전자우편, dx=6, size=7.5)
    # 전화번호 세 칸은 머리 아래 줄에 쓴다
    for lbl, tel in (("사업장", 사업장전화), ("주소지", 주소지전화),
                     ("휴대전화", 휴대전화)):
        w = word(lbl)
        if w and tel:
            s.center(w[0] - 6, w[2] + 6, w[3] + 1, w[3] + 12, tel, 7.5)

    # ── ⑤ 과세표준명세 ───────────────────────────────────
    # 업종코드가 한 자리씩 칸이라 한 칸씩 걸으면 거기서 막힌다. 줄의 세로선을
    # 통째로 받아 앞에서부터 업태·종목·생산요소, 끝에서 금액을 잡는다
    def five(row_word, 업, 종, 코, 금):
        r = None
        for w in p.get_text("words"):
            if w[4].startswith(row_word):
                r = (w[0], w[1], w[2], w[3])
                break
        if not r:
            return
        y = (r[1] + r[3]) / 2
        xs = sorted({x for x, y0, y1 in _vlines(p)
                     if y0 - 1 <= y <= y1 + 1 and r[2] - 1 < x < 300})
        if len(xs) < 4:
            return
        money_r, money_l = xs[-1], xs[-2]
        s.center(r[2], xs[0], r[1], r[3], 업, 6.5)
        s.center(xs[0], xs[1], r[1], r[3], 종, 5)
        s.center(xs[2], money_l, r[1], r[3], 코, 7)
        s.right(money_r, r[1], r[3], 금, 7)

    five("(31)", 업태, 종목, 업종코드, won(val("(9)", 2)))
    five("(35)", "", "", "", won(val("(9)", 2)))

    hits = p.search_for("세무서장")
    if hits and 세무서:
        b = hits[0]
        w = font.text_length(세무서, fontsize=9)
        s.at(b.x0 - w - 5, b.y1 - 1.5, 세무서, 9)

    # ── 제2쪽 (서식 제4쪽) ───────────────────────────────
    l15s, l15t = val("(15)", 2) or 0, val("(15)", 3) or 0
    fs, ft = g("고정자산 카드매입", (0, 0))
    l17s, l17t = val("(17)", 2) or 0, val("(17)", 3) or 0
    l19v = val("(19)", 3) or 0
    free = val("면세", 2) or 0

    def put2(no, sup=None, tax=None, size=7.5):
        r = s2.row(no)
        if not r:
            return
        if sup not in (None, ""):
            s2.right(lay2["amt_r"], r[1], r[3], won(sup), size)
        if tax not in (None, ""):
            s2.right(lay2["tax_r"], r[1], r[3], won(tax), size)

    for no in ["(36)", "(37)", "(40)", "(41)", "(42)", "(43)"]:
        put2(no, 0, 0)
    put2("(38)", 0)
    put2("(39)", 0)
    put2("(44)", l15s - fs, l15t - ft)
    put2("(45)", fs, ft)
    put2("(46)", 0, 0)
    put2("(47)", 0, 0)
    for no in ["(48)", "(49)", "(50)", "(51)"]:
        put2(no, None, 0)
    put2("(52)", l15s, l15t)
    put2("(53)", l17s, l17t)
    put2("(54)", 0, 0)
    put2("(55)", 0, 0)
    put2("(56)", l17s, l17t)
    put2("(57)", None, l19v)
    for n in range(58, 63):
        put2(f"({n})", None, 0)
    put2("(63)", None, l19v)
    for n in range(64, 84):
        put2(f"({n})", 0, 0)
    put2("(84)", None, 0)

    # 면세사업 수입금액 (85). 코드번호가 한 자리씩 칸이라 앞뒤에서 잡는다
    r85 = s2.row("(85)")
    if r85:
        y = (r85[1] + r85[3]) / 2
        xs = sorted({x for x, y0, y1 in _vlines(q)
                     if y0 - 1 <= y <= y1 + 1 and x > r85[2] - 1})
        # (85) 는 란 번호가 제 칸을 따로 갖는다. 그래서 한 칸 건너뛰고 센다
        if len(xs) >= 4:
            s2.center(xs[0], xs[1], r85[1], r85[3], 면세업태, 7)
            s2.center(xs[1], xs[2], r85[1], r85[3], 면세종목, 7)
            s2.center(xs[2], xs[-1], r85[1], r85[3], 면세업종코드, 7)
            s2.right(_edge(q), r85[1], r85[3], won(free), 7.5)

    for no, amt in [("(88)", free), ("(89)", g("계산서 발급", 0)),
                    ("(90)", g("계산서 수취", 0))]:
        r = s2.row(no)
        if r:
            s2.right(_edge(q), r[1], r[3], won(amt), 7.5)

    if not _put_biz(q, s2, 사업자번호):
        for w in q.get_text("words"):
            if w[4] == "사업자등록번호":
                s2.at(w[2] + 14, w[3] - 1.5, biz(사업자번호), 8)
                break

    # 쪽 표기와 군더더기 줄을 홈택스 출력물과 맞춘다
    _erase_line(p, "작성방법을", x_max=300)
    _erase_line(q, "작성방법을")
    _page_label(p, s, "(제1장 앞쪽)")
    _page_label(q, s2, "(제2장 앞쪽)")

    doc.save(out_path)
    doc.close()
    src.close()
    return out_path, None
