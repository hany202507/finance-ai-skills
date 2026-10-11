# -*- coding: utf-8 -*-
"""서식 원본 PDF 위에 값만 얹는다.

서식을 다시 그리지 않는다. 국가법령정보센터에서 받은 원본(`forms/원본/`)을 그대로 두고
필드목록(`forms/필드목록/*.json`)의 칸 좌표에 글자만 쓴다. 좌표는 PyMuPDF pt, 원점 왼쪽 위.

필드목록에서 이 모듈이 읽는 키:

- `좌표.값_칸_해석`: {열 이름: [x0, y0, x1, y1]}. 체크 칸은 열 이름이 선택지이고 칸은 「[ ]」 안쪽이다.
- `기준점`: [{"패턴": "-", "쓰는곳": "앞"|"뒤"|"사이", "부분": "국내외분", "순번": 0, "열": [...]}].
  칸 안에 인쇄된 글자(패턴)를 찾아 그 옆에 쓴다. 「앞」은 패턴 왼쪽(바로 앞 인쇄 글자 또는 칸 끝부터)에
  오른쪽 맞춤, 「뒤」는 패턴 오른쪽(다음 인쇄 글자 또는 칸 끝까지)에 왼쪽 맞춤, 「사이」는 「뒤」와 같은
  자리에 가운데 맞춤이다(「( )」「[ ]」처럼 두 인쇄 글자 사이). 「순번」은 칸 안에서 같은 패턴의 몇 번째인지
  (0부터), 「열」은 그 기준점이 걸리는 열이다(없으면 모든 열). 값_칸_해석이 없는 필드는 라벨 상자에서 찾는다.
- `음영_열`: 음영이라 적지 않는 열. `음영: true` 는 모든 열이 음영인 필드다.
- `쓰지않음`: 신고인이 적지 않는 필드(관리번호, 인쇄된 목록 등)와 그 이유.

함수: `load_font`·`put`·`anchor`·`save`(계획 2 계약 C9)와, 필드목록을 그대로 받아 쓰는 `put_anchored`·`put_field`.

글꼴은 `YANGDO_FONT` 환경변수 → 맑은 고딕 → Apple SD Gothic Neo → 나눔고딕 → Noto Sans CJK →
PyMuPDF 내장 CJK(Droid Sans Fallback) 순서로 고른다(부가세신고서검토 `form21_pdf.py` 와 같은 순서).
글자 폭을 재는 글꼴과 쓰는 글꼴이 같아야 칸을 넘지 않으므로 고른 한 벌을 두 곳에 같이 쓴다.
"""
import glob
import os
import re

import pymupdf

MIN_SIZE = 5.0      # 이보다 작게는 줄이지 않는다
STEP = 0.5
PAD = 3.0           # 칸 끝에서 띄우는 여백
GAP = 1.0           # 인쇄 글자에서 띄우는 여백
_FONTS = {}
_BUFFERS = {}
_ALIGN = {"앞": "right", "뒤": "left", "사이": "center"}


class Overflow(ValueError):
    """글자가 칸에 들어가지 않는다(5pt 까지 줄이고 줄을 나눠도 넘친다). 다른 ValueError(음영 칸·없는 열·기준점 못 찾음)와 구분한다."""

# 오른쪽 맞춤 자료형. 한 문자열로 둔다(키 이름을 따옴표로 쓰면 test_scope_contract 가 엔진이 읽는 키로 본다)
_RIGHT_KINDS = "금액 비율 면적".split()


def _font_candidates():
    """운영체제별 한글 글꼴 후보. 앞에 있는 것부터 쓴다."""
    env = os.environ.get("YANGDO_FONT")
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
            "/usr/share/fonts/nanum/NanumGothic.ttf"]
    noto = glob.glob("/usr/share/fonts/**/NotoSansCJK*", recursive=True)
    out += sorted(noto, key=lambda p: ("Regular" not in p, p))
    out += ["/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"]
    return [p for p in out if p]


def _resource_name(label):
    return "YD" + re.sub(r"[^A-Za-z0-9]", "", label)[:24]


def load_font():
    """(pymupdf.Font, 쪽 자원 이름, 글꼴 파일 경로 또는 None) 을 돌려준다.

    시스템 글꼴이 하나도 없으면(리눅스 CI 등) PyMuPDF 내장 CJK 글꼴을 쓰고 경로는 None 이다."""
    cands = tuple(_font_candidates())
    if cands in _FONTS:
        return _FONTS[cands]
    got = None
    for p in cands:
        if not os.path.isfile(p):
            continue
        try:
            f = pymupdf.Font(fontfile=p)
        except Exception:  # noqa: BLE001  글꼴을 못 읽으면 다음 후보
            continue
        if f.has_glyph(ord("가")):
            got = (f, _resource_name(os.path.splitext(os.path.basename(p))[0]), p)
            break
    if got is None:
        f = pymupdf.Font("korea")
        got = (f, "YDkorea", None)
    _FONTS[cands] = got
    return got


def _font(font):
    if font is None:
        return load_font()
    if isinstance(font, pymupdf.Font):
        return (font, _resource_name(font.name), None)
    return tuple(font)


def _ensure(page, font):
    f, name, path = font
    if path:
        page.insert_font(fontname=name, fontfile=path)
        return
    if name not in _BUFFERS:
        _BUFFERS[name] = f.buffer
    page.insert_font(fontname=name, fontbuffer=_BUFFERS[name])


def _wrap(f, text, size, avail, n):
    """text 를 폭 avail 안에서 n 줄 이하로 나눈다. 안 되면 None."""
    def w(t):
        return f.text_length(t, fontsize=size)
    if w(text) <= avail:
        return [text]
    if n == 1:
        return None
    rows, cur = [], ""
    for word in text.split(" "):
        cand = word if not cur else cur + " " + word
        if w(cand) <= avail:
            cur = cand
            continue
        if cur:
            rows.append(cur)
            cur = ""
        while word and w(word) > avail:      # 낱말 하나가 칸보다 길면 글자 단위로 자른다
            k = len(word)
            while k > 1 and w(word[:k]) > avail:
                k -= 1
            rows.append(word[:k])
            word = word[k:]
        cur = word
    if cur:
        rows.append(cur)
    if len(rows) > n or any(w(r) > avail for r in rows):
        return None
    return rows


def _draw(page, rect, rows, size, align, pad, font):
    f, name, _ = font
    _ensure(page, font)
    asc, desc = f.ascender, f.descender
    lh = (asc - desc) * size
    top = rect.y0 + (rect.height - lh * len(rows)) / 2
    used = None
    for i, row in enumerate(rows):
        width = f.text_length(row, fontsize=size)
        if align == "left":
            x = rect.x0 + pad
        elif align == "center":
            x = rect.x0 + (rect.width - width) / 2
        else:
            x = rect.x1 - pad - width
        base = top + i * lh + asc * size
        page.insert_text((x, base), row, fontsize=size, fontname=name, color=(0, 0, 0))
        r = pymupdf.Rect(x, base - asc * size, x + width, base - desc * size)
        used = r if used is None else used | r
    return used


def _fit(rect, text, align, size, font, lines, pad):
    """글자가 칸에 들어가는 줄 나눔과 크기를 잰다. 쓰지는 않는다. (칸, 줄 목록, 크기, 맞춤, 여백, 글꼴) 또는 빈 글자면 None.

    폭이나 높이가 넘치면 5pt 까지 0.5pt 씩 줄이고, lines 가 2 이상이면 줄을 나눠 본다. 그래도 넘치면 Overflow.
    문장에는 글자를 싣지 않는다(성명·주소 같은 인적사항이 오류 문장으로 새지 않게). 글자 수와 칸 크기만 적는다."""
    text = "" if text is None else str(text).strip()
    if not text:
        return None
    font = _font(font)
    f = font[0]
    rect = pymupdf.Rect(rect)
    if pad is None:
        pad = PAD if align in ("left", "right") else GAP
    avail = rect.width - 2 * pad
    lh1 = f.ascender - f.descender
    s = float(size)
    while s >= MIN_SIZE - 1e-9:
        for n in range(1, max(1, int(lines)) + 1):
            if n * lh1 * s > rect.height:
                break
            rows = _wrap(f, text, s, avail, n)
            if rows is not None:
                return rect, rows, s, align, pad, font
        s = round(s - STEP, 2)
    raise Overflow("글자 %d자가 칸에 들어가지 않는다(칸 폭 %.1fpt, 높이 %.1fpt, %.1fpt 까지 줄여도 넘친다)"
                   % (len(text), rect.width, rect.height, MIN_SIZE))


def put(page, rect, text, align="right", size=7.5, font=None, lines=1, pad=None):
    """칸(rect) 안에 글자를 쓰고 실제로 쓴 상자를 돌려준다. 빈 글자는 쓰지 않고 None.

    세로는 칸 가운데. 폭이나 높이가 넘치면 5pt 까지 0.5pt 씩 줄이고, lines 가 2 이상이면 줄을 나눠 본다.
    그래도 넘치면 Overflow(ValueError)이고 쪽에는 아무것도 쓰지 않는다. 좌우 여백은 기본 3pt(가운데 맞춤은 1pt)."""
    job = _fit(rect, text, align, size, font, lines, pad)
    if job is None:
        return None
    rect, rows, s, align, pad, font = job
    return _draw(page, rect, rows, s, align, pad, font)


def _center_in(rect, r):
    return rect.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))


def _anchors(page, rect, pattern):
    rect = pymupdf.Rect(rect)
    hits = [pymupdf.Rect(w[:4]) for w in page.get_text("words") if w[4] == pattern]
    hits = [r for r in hits if _center_in(rect, r)]
    if not hits:
        hits = [r for r in page.search_for(pattern, clip=rect) if _center_in(rect, r)]
    hits.sort(key=lambda r: (round(r.y0), r.x0))
    return hits


def anchor(page, rect, pattern, nth=0):
    """칸(rect) 안에 인쇄된 글자 pattern(「-」「(」「년」 등)의 상자. 없으면 None.

    낱말이 pattern 과 같은 것을 먼저 찾고, 없으면 낱말 안의 일부(search_for)로 찾는다.
    nth 는 칸 안에서 위에서 아래, 왼쪽에서 오른쪽 순서로 센 번호(0부터)다."""
    hits = _anchors(page, rect, pattern)
    return hits[nth] if len(hits) > nth else None


def _same_line(w, a):
    ov = min(w.y1, a.y1) - max(w.y0, a.y0)
    return ov >= 0.5 * min(w.height, a.height)


def _gap(gap, where):
    """put_anchored 의 gap 인자에서 쓰는 곳(앞·뒤)의 여백. 주지 않으면 GAP."""
    if gap is None:
        return GAP
    return gap.get(where, GAP) if isinstance(gap, dict) else gap


def _box(rect, a, where, words, gap=GAP):
    """기준점 a 옆의 빈 자리. 같은 줄의 다른 인쇄 글자와 칸 끝에서 멈춘다. gap 은 인쇄 글자에서 띄우는 여백이다."""
    line = [w for w in words if _same_line(w, a) and not (w & a).get_area() > 0.5 * a.get_area()]
    cy = (a.y0 + a.y1) / 2
    half = min(cy - rect.y0, rect.y1 - cy)
    if where == "앞":
        left = max((w.x1 for w in line if w.x1 <= a.x0 + 0.1), default=None)
        x0 = left + gap if left is not None else rect.x0 + PAD
        x1 = a.x0 - gap
    else:
        right = min((w.x0 for w in line if w.x0 >= a.x1 - 0.1), default=None)
        x0 = a.x1 + gap
        x1 = right - gap if right is not None else rect.x1 - PAD
    return pymupdf.Rect(x0, cy - half, x1, cy + half)


def _slots(slots):
    if not slots:
        return []
    return [slots] if isinstance(slots, dict) else list(slots)


def _slot_values(slots, values):
    if isinstance(values, dict):
        return [values.get(s.get("부분")) for s in slots]
    if isinstance(values, (list, tuple)):
        if len(values) != len(slots):
            raise ValueError("기준점 %d 개에 값 %d 개" % (len(slots), len(values)))
        return list(values)
    if len(slots) == 1:
        return [values]
    raise ValueError("기준점이 여럿이면 값을 부분 이름(%s)으로 준다"
                     % ", ".join(str(s.get("부분")) for s in slots))


def put_anchored(page, rect, slots, values, size=7.5, font=None, gap=None):
    """칸(rect) 안의 기준점 옆에 값을 쓴다. 쓴 상자 목록(빈 값은 건너뜀).

    gap 은 기준점과 옆 인쇄 글자에서 띄우는 여백(기본 GAP)이다. 숫자 하나는 앞뒤 모두, {"앞": 숫자, "뒤": 숫자} 는 쓰는 곳마다 다르다.
    음수는 인쇄 글자의 상자(글자 앞뒤 빈 자리 포함)에 조금 걸쳐 쓰는 것을 허용한다. 인쇄된 괄호가 좁은 칸에서 글자를 덜 줄이려고 쓴다.
    values 는 {부분: 글자}, 기준점 순서의 목록, 또는 기준점이 하나일 때 글자 하나다.
    모든 자리를 먼저 계산하고 모든 부분이 제 자리에 들어가는지 잰 뒤에 쓴다. 앞에서 쓴 값이 뒤 자리 계산에 끼어들지 않고,
    한 부분이라도 넘치면(Overflow) 쪽에는 아무것도 쓰지 않는다(앞 부분만 남은 칸 위에 다음 후보를 겹쳐 쓰지 않게)."""
    rect = pymupdf.Rect(rect)
    slots = _slots(slots)
    vals = _slot_values(slots, values)
    words = [pymupdf.Rect(w[:4]) for w in page.get_text("words")]
    words = [w for w in words if _center_in(rect, w)]
    jobs = []
    for s, v in zip(slots, vals):
        if v is None or str(v).strip() == "":
            continue
        a = anchor(page, rect, s["패턴"], nth=s.get("순번", 0))
        if a is None:
            raise ValueError("기준점 %r 을 칸 %s 안에서 찾지 못했다" % (s["패턴"], [round(x, 1) for x in rect]))
        jobs.append((_box(rect, a, s["쓰는곳"], words, _gap(gap, s["쓰는곳"])), v, _ALIGN[s["쓰는곳"]]))
    fitted = [_fit(box, v, al, size, font, 1, 0) for box, v, al in jobs]       # 하나라도 넘치면 여기서 멈춘다
    return [_draw(page, r, rows, sz, al, pad, fnt) for r, rows, sz, al, pad, fnt in fitted]


def _default_align(field, col=None):
    """맞춤을 주지 않았을 때의 기본값. 열 이름(지급금액, 증빙종류(코드), 상호)을 먼저 보고 자료형을 본다."""
    col = col or ""
    if "금액" in col:
        return "right"
    if "코드" in col:
        return "center"
    if any(k in col for k in ("상호", "성명", "소재지", "번호", "관계", "지급일")):
        return "left"
    kind = field.get("자료형") or ""
    if any(k in kind for k in _RIGHT_KINDS):
        return "right"
    if "체크" in kind or kind.startswith("코드"):
        return "center"
    return "left"


def put_field(page, field, value, col=None, align=None, size=7.5, font=None, lines=1, pad=None, gap=None):
    """필드목록의 필드 하나에 값을 쓴다. 쓴 상자 목록.

    기준점이 그 열에 걸리면 put_anchored, 아니면 put 으로 쓴다. 음영 칸, 쓰지않음 필드,
    없는 열은 ValueError. 기준점이 없는 칸에 dict·list 값을 주어도 ValueError(묶음 값을 글자로 바꿔 찍지 않는다).
    글자가 들어가지 않으면 Overflow 이고 문장에 필드 id 와 열 이름을 적는다(값은 적지 않는다).
    pad 는 기준점이 없는 칸의 좌우 여백(put 과 같다). 좁은 칸에서 글자를 덜 줄이려고 줄여 쓴다.
    gap 은 기준점이 있는 칸에서 인쇄 글자에서 띄우는 여백이다(put_anchored)."""
    fid = field.get("id")
    if field.get("쓰지않음"):
        raise ValueError("%s: 적지 않는 칸이다(%s)" % (fid, field["쓰지않음"]))
    c = field.get("좌표") or {}
    g = c.get("값_칸_해석") or {}
    if g:
        if col is None:
            if len(g) != 1:
                raise ValueError("%s: 열을 골라야 한다(%s)" % (fid, ", ".join(g)))
            col = next(iter(g))
        if col not in g:
            raise ValueError("%s: 열 %r 이 없다(%s)" % (fid, col, ", ".join(g)))
        rect = g[col]
    elif field.get("기준점"):
        rect = c["라벨_bbox"]
    else:
        raise ValueError("%s: 값을 쓸 칸이 없다" % fid)
    if field.get("음영") or col in field.get("음영_열", []):
        raise ValueError("%s %s: 음영 칸이라 적지 않는다" % (fid, col))
    slots = [s for s in _slots(field.get("기준점")) if not s.get("열") or col in s["열"]]
    try:
        if slots:
            return put_anchored(page, rect, slots, value, size=size, font=font, gap=gap)
        if isinstance(value, (dict, list, tuple)):
            raise ValueError("%s %s: 기준점이 없는 칸이라 값 하나만 쓴다(묶음 값을 받았다)" % (fid, col))
        used = put(page, rect, value, align=align or _default_align(field, col), size=size, font=font, lines=lines,
                   pad=pad)
    except Overflow as e:
        raise Overflow("%s %s: %s" % (fid, col, e)) from None
    return [used] if used is not None else []


def save(doc, path):
    """글꼴 부분집합을 만들고 압축해 저장한다. 저장한 파일의 바이트 수를 돌려준다."""
    doc.subset_fonts()
    doc.save(path, garbage=4, deflate=True)
    return os.path.getsize(path)
