"""전기 신고서 21호(기부금조정명세서) 뒤쪽 읽기. 5절 기부금 이월액 명세와 6절 해당 사업연도 기부금 지출액 명세 줄이 전기.json
`rows["21"]` 가 된다(CONTRACT.md 13절). 당기 기부금 조서(wp/papers/donation.py prior_carry)가 이월 기부금 노란 줄의 기본값으로 쓴다.

  rows["21"]  [{절: 5, 사업연도, 종류, "21", "22", "23", "24", "25"}, {절: 6, 사업연도, 종류, "26", "27", "28"}]
              란 이름은 서식의 동그라미 번호(㉑한도초과 손금불산입액 · ㉒기공제액 · ㉓공제가능 잔액 · ㉔해당사업연도 손금추인액 ·
              ㉕차기이월액, ㉖지출액 합계금액 · ㉗해당 사업연도 손금산입액 · ㉘차기 이월액). 정의는 prior/defs/21.json.
              사업연도는 인쇄된 연도 글(「202412」 · 「2023」 · 「2023.01.01~2023.12.31」)의 끝 날 연도 4자리, 종류는 특례 · 일반
              (옛 이름 법정 → 특례, 지정 → 일반, 「제24조제2항」 → 특례, 「제24조제3항」 → 일반). 금액이 하나도 없는 줄은 넣지 않는다.
              2026. 3. 20. 개정 서식의 5절 합계 줄(사업연도 칸 「합계」)은 줄로 넣지 않고 줄 합계와 맞춰 본다.

앞쪽(① ~ ⑳)은 읽지 않는다. 당기 한도는 당기 소득으로 다시 계산하므로 전기 값이 필요 없다.

읽는 법(54호와 같이 낱말 좌표). 쪽마다 5절 · 6절 제목 줄을 찾고, 제목 아래 머리 줄 낱말을 가로로 겹치는 것끼리 묶어 열을 정한다
(「손금불산입」 ㉑ · 「기공제」 ㉒ · 「공제가능」 ㉓ · 「손금추인」 ㉔ · 「차기이월」 ㉕, 6절은 「지출액」 ㉖ · 「손금산입액」 ㉗ ·
「차기이월」 ㉘, 「사업연도」 · 「기부금종류」). 금액 낱말은 가운데가 가까운 열에, 위아래로 가장 가까운 기부금 종류 글 덩이와
사업연도 글 덩이에 붙인다. 서식마다 종류 글이 두세 줄이고 금액은 그 가운데에 찍혀서 줄이 아니라 덩이의 가운데로 맞춘다
(종류 덩이는 「…기부금」 으로 끝나는 줄에서 닫는다).
"""
from __future__ import annotations

import re

AMT = re.compile(r"^[△\-]?\d{1,3}(?:,\d{3})+$|^[△\-]?\d{4,}$")    # 쉼표 금액 또는 네 자리 이상(쪽 번호는 뺀다)
YEAR_WORD = re.compile(r"^[\d.\-~∼/()년월일]*\d[\d.\-~∼/()년월일]*$|^(합|계|합계|총계|~|∼|～)$")
TITLE_5 = "기부금이월액명세"
TITLE_6 = "기부금지출액명세"
HEAD_BAND = 34                       # 제목 줄 아래 머리 줄이 있는 높이(pt)
NEAR_KIND = 12                       # 금액과 기부금 종류 글 덩이 가운데의 위아래 거리 한도(pt)
NEAR_YEAR = 30                       # 금액과 사업연도 글 덩이 가운데의 거리 한도(pt). 사업연도 칸은 종류 두 줄에 걸친다
COLS_5 = (("21", ("손금불산입", "한도초과")), ("22", ("기공제",)), ("23", ("공제가능",)), ("24", ("손금추인",)),
          ("25", ("차기이월",)))
COLS_6 = (("26", ("지출액",)), ("27", ("손금산입액",)), ("28", ("차기이월",)))


def _n(s) -> str:
    return re.sub(r"[\s·ㆍ]", "", str(s or ""))


def _i(s) -> int:
    t = str(s).replace(",", "")
    neg = t.startswith(("△", "-"))
    t = t.lstrip("△-")
    return -int(t) if neg else int(t)


def _lines(words: list) -> list[list]:
    """낱말을 높이로 묶은 줄(위 → 아래, 줄 안은 왼쪽 → 오른쪽)."""
    rows: list[list] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if rows and abs((rows[-1][0][1] + rows[-1][0][3]) / 2 - yc) < 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w[0]) for r in rows]


def _title(words: list, key: str) -> tuple[float, float] | None:
    """제목 줄(띄어쓰기 상관없이 key 가 든 줄)의 (위, 아래)."""
    for line in _lines(words):
        if key in _n("".join(w[4] for w in line)):
            return min(w[1] for w in line), max(w[3] for w in line)
    return None


def _columns(words: list, top: float, bottom: float) -> list[dict]:
    """머리 줄 낱말을 가로로 겹치는(6pt 안) 것끼리 묶은 열 [{x0, x1, text}] (왼쪽 → 오른쪽)."""
    heads = sorted((w for w in words if top < w[1] and w[3] <= bottom and _n(w[4])), key=lambda w: w[0])
    cols: list[dict] = []
    for w in heads:
        hit = next((c for c in cols if w[0] <= c["x1"] + 6 and w[2] >= c["x0"] - 6), None)
        if hit:
            hit["x0"], hit["x1"] = min(hit["x0"], w[0]), max(hit["x1"], w[2])
            hit["words"].append(w)
        else:
            cols.append({"x0": w[0], "x1": w[2], "words": [w]})
    for c in cols:
        c["text"] = _n("".join(w[4] for w in sorted(c["words"], key=lambda w: (w[1], w[0]))))
    return sorted(cols, key=lambda c: c["x0"])


def _pick(cols: list[dict], spec) -> dict:
    """금액 열 code → 열 dict. 열 글에 spec 의 낱말이 든 첫 열(6절 ㉗ 은 「불산입」 이 없는 열)."""
    out = {}
    for code, keys in spec:
        c = next((c for c in cols if any(k in c["text"] for k in keys) and not (code == "27" and "불산입" in c["text"])
                  and all(c is not v for v in out.values())), None)
        if c is not None:
            out[code] = c
    return out


def _blocks(words: list) -> list[dict]:
    """낱말을 위아래로 붙은(4pt 안) 덩이로 묶는다. [{y0, y1, yc, text}] (위 → 아래)."""
    out: list[dict] = []
    for w in sorted(words, key=lambda w: w[1]):
        if out and w[1] <= out[-1]["y1"] + 4:
            out[-1]["y1"] = max(out[-1]["y1"], w[3])
            out[-1]["words"].append(w)
        else:
            out.append({"y0": w[1], "y1": w[3], "words": [w]})
    for b in out:
        b["text"] = _n("".join(w[4] for w in sorted(b["words"], key=lambda w: (round(w[1]), w[0]))))
        b["yc"] = (b["y0"] + b["y1"]) / 2
    return out


def _kind_blocks(words: list) -> list[dict]:
    """기부금 종류 칸 낱말 → 종류 글 덩이. 줄(높이)로 묶은 뒤 위에서부터 이어 붙이고, 「…기부금」 으로 끝나는 줄에서 덩이를
    닫는다(종류 글이 두세 줄이고 이웃 줄의 글과 붙어 찍히는 서식이 있어 간격만으로는 못 나눈다). 4pt 넘게 떨어지면 새 덩이."""
    out: list[dict] = []
    for line in _lines(words):
        y0, y1 = min(w[1] for w in line), max(w[3] for w in line)
        text = _n("".join(w[4] for w in line))
        if not out or out[-1]["done"] or y0 > out[-1]["y1"] + 4:
            out.append({"y0": y0, "y1": y1, "text": text, "done": False})
        else:
            out[-1]["y1"] = max(out[-1]["y1"], y1)
            out[-1]["text"] += text
        if text.endswith("기부금"):
            out[-1]["done"] = True
    for b in out:
        b["yc"] = (b["y0"] + b["y1"]) / 2
    return out


def kind_of(text: str) -> str | None:
    """기부금 종류 글 → 특례 · 일반. 비지정 · 모름은 None."""
    t = _n(text)
    if "비지정" in t:
        return None
    if "특례" in t or "법정" in t or "제24조제2항" in t:
        return "특례"
    if "일반" in t or "지정" in t or "제24조제3항" in t:
        return "일반"
    return None


def year_of(text: str) -> str:
    """사업연도 글 → 끝 날의 연도 4자리(「202412」 → 2024, 「2023.04.01~2024.03.31」 → 2024). 합계 줄은 「합계」."""
    t = _n(text)
    if re.fullmatch(r"합계|계|총계", t):
        return "합계"
    nums = re.findall(r"\d{4,8}", t)
    return nums[-1][:4] if nums else ""


def section(words: list, top: float, bottom: float, spec, no: int) -> tuple[list[dict], list[str]]:
    """한 절(머리 줄이 top 아래, 줄은 bottom 위) → (줄, 문제)."""
    cols = _pick(_columns(words, top, top + HEAD_BAND), spec)
    if not cols:
        return [], [f"21호 {no}절 머리 줄(금액 열)을 찾지 못했습니다"]
    head_bottom = max(w[3] for c in cols.values() for w in c["words"])
    first_amt = min(c["x0"] for c in cols.values())
    body = [w for w in words if head_bottom < (w[1] + w[3]) / 2 < bottom]
    left = [w for w in body if (w[0] + w[2]) / 2 < first_amt - 2]
    years = _blocks([w for w in left if YEAR_WORD.match(_n(w[4]))])      # 사업연도 칸(날짜 · 「합계」)
    kinds = _kind_blocks([w for w in left if not YEAR_WORD.match(_n(w[4]))])  # 기부금 종류 칸
    centers = {code: (c["x0"] + c["x1"]) / 2 for code, c in cols.items()}
    lines: dict = {}
    problems = []
    for w in body:
        yc, xc = (w[1] + w[3]) / 2, (w[0] + w[2]) / 2
        if xc < first_amt - 2 or not AMT.match(w[4].replace(" ", "")):
            continue
        code = min(centers, key=lambda c: abs(centers[c] - xc))
        kb = min(kinds, key=lambda b: abs(b["yc"] - yc), default=None)
        if kb is None or abs(kb["yc"] - yc) > NEAR_KIND:
            problems.append(f"21호 {no}절 금액 {w[4]}(높이 {yc:.0f})의 기부금 종류를 찾지 못했습니다")
            continue
        kind = kind_of(kb["text"])
        if kind is None:
            problems.append(f"21호 {no}절 금액 {w[4]} 의 기부금 종류 「{kb['text'][:20]}」 를 특례 · 일반으로 가리지 못했습니다")
            continue
        yb = min(years, key=lambda b: abs(b["yc"] - yc), default=None)
        if yb is not None and abs(yb["yc"] - yc) > NEAR_YEAR:
            yb = None
        row = lines.setdefault((id(yb), id(kb)), {"절": no, "사업연도": year_of(yb["text"]) if yb else "", "종류": kind,
                                                  **{c: 0 for c, _ in spec}})
        row[code] += _i(w[4])
    rows = [r for r in lines.values() if any(r[c] for c, _ in spec)]
    total = [r for r in rows if r["사업연도"] == "합계"]
    rows = [r for r in rows if r["사업연도"] != "합계"]
    for t in total:
        if any(sum(r[c] for r in rows if r["종류"] == t["종류"]) != t[c] for c, _ in spec):
            problems.append(f"21호 {no}절 {t['종류']} 합계 줄이 사업연도 줄의 합과 다릅니다")
    for r in rows:
        if not r["사업연도"]:
            problems.append(f"21호 {no}절 {r['종류']} 줄의 사업연도를 찾지 못했습니다")
        if no == 5 and (r["21"] - r["22"] != r["23"] or r["23"] - r["24"] != r["25"]):
            problems.append(f"21호 5절 {r['사업연도']} {r['종류']} 줄이 ㉓ = ㉑ - ㉒, ㉕ = ㉓ - ㉔ 와 맞지 않습니다")
        if no == 6 and r["26"] - r["27"] != r["28"]:
            problems.append(f"21호 6절 {r['사업연도']} {r['종류']} 줄이 ㉘ = ㉖ - ㉗ 과 맞지 않습니다")
    return rows, problems


def rows_from_words(words: list) -> tuple[list[dict], list[str]]:
    """쪽 하나 → (5절 · 6절 줄, 문제). 제목이 없으면 빈 결과."""
    t5, t6 = _title(words, TITLE_5), _title(words, TITLE_6)
    rows, problems = [], []
    bottom = max((w[3] for w in words), default=0) + 1
    if t5:
        got, why = section(words, t5[1], t6[0] if t6 and t6[0] > t5[1] else bottom, COLS_5, 5)
        rows += got
        problems += why
    if t6:
        got, why = section(words, t6[1], bottom, COLS_6, 6)
        rows += got
        problems += why
    return rows, problems


def read_21(pages: list[dict]) -> tuple[list[dict], list[str]]:
    """21호 쪽들(쪽 dict: words) → (rows["21"], 문제 글 목록). 21호 쪽이 없으면 ([], [])."""
    if not pages:
        return [], []
    rows, problems, seen = [], [], False
    for p in pages:
        words = p.get("words") or []
        if _title(words, TITLE_5) or _title(words, TITLE_6):
            seen = True
        got, why = rows_from_words(words)
        rows += got
        problems += why
    if not seen:
        problems.append("21호 뒤쪽(5. 기부금 이월액 명세 · 6. 해당 사업연도 기부금 지출액 명세)을 찾지 못했습니다")
    rows.sort(key=lambda r: (r["절"], r["사업연도"], 0 if r["종류"] == "특례" else 1))
    return rows, problems
