"""전기 신고서 54호(주식등변동상황명세서) 주요 란 읽기. 전기.json `cells["54"]` 와 `rows["54"]` 가 된다(CONTRACT.md 13절).

서식 단계가 전기 PDF 를 직접 열지 않고 이 값으로 당기 54호 기초를 채우게 하려는 것이다. 란 이름은 서식 정의
`ctax/forms/defs/54.json` 의 란 코드와 같다.

  cells["54"]  1절 제출법인 기본사항: 기초 · 기말 × 보통주 · 우선주 × 주식수 · 액면가 · 자본금, 기초 · 기말 자본금 계,
               3절 합계 줄의 기초 · 기말 주식수(합계_기초_주식수 · 합계_기말_주식수)
  rows["54"]   3절 주주 줄 [{번호, 구분, 성명, 국코드, 기초_주식수, 기초_지분율, 증가, 감소, 기말_주식수, 기말_지분율, 관계}].
               증가 · 감소는 변동 란(양수 · 유상증자 · 양도 · 감자 등)의 합. 지분율은 인쇄된 글 그대로(「18.4」).
               개인 주주의 성명 · 주민등록번호는 읽지 않는다(성명 빈 글). 법인 주주는 법인명만 읽는다

1절은 쪽 글자(띄어쓰기 · 줄바꿈 무시)에서 「기초 보통주 … 우선주 … 기말 보통주 … 우선주 …」 꼴로 읽는다. 3절은 낱말 좌표로 읽는다.
머리 줄의 「지분율」 두 낱말(기초 · 기말)과 「양도」(감소 첫 열) · 기말 「주식수」 의 가로 위치로 열을 나누고, 숫자 낱말은 오른쪽 끝이
든 열에 넣는다. 글자 순서는 PDF 마다 다르지만(성명이 쪽 끝에 몰려 나오는 신고본이 있다) 좌표는 같아서다. 이어진 쪽은 쪽마다 머리 줄을
다시 찾는다.

판(2026. 3. 20. 개정, 법인세법 시행규칙 부칙 <제7호, 2026.3.20> 제3조로 그 뒤 제출분)은 쪽 글자로 가린다(`edition`: 「개정 2026」
머리 또는 3절 ㊶ 「이익소각」 열이 있으면 2026 판, 아니면 지금까지의 2021 판 읽기 그대로). 2026 판은 1절에 보통주 · 우선주 줄이
없고 기초 · 기말이 2절 ⑯ · ⑰ 줄(⑫ 주식수 · ⑬ 주당 액면가액 · ⑮ 자본금)이며, 3절 변동 열이 원인별(㉖ ~ ㉞ 증가, ㉟ ~ ㊷ 감소)이다.
`read_54_2026` 이 서식 정의(forms/defs/54.json)의 새 란 코드로 읽고, 같은 뜻의 옛 이름(별칭)도 함께 넣는다.

  cells["54"]  판 「2026」, 16_12 · 16_13 · 16_15 · 17_12 · 17_13 · 17_15, 합계_24 · 합계_26 ~ 합계_43(값이 있는 것),
               옛 이름 기초_자본금(= 16_15) · 기말_자본금(= 17_15) · 합계_기초_주식수(= 합계_24) · 합계_기말_주식수(= 합계_43).
               보통주 · 우선주로 나눈 옛 1절 란(기말_보통주_주식수 등)은 2026 판에 없어 넣지 않는다
  rows["54"]   새 란 코드 19 · 20 · 22 · 23 · 24 · 25 · 26 ~ 42 · 43 · 44 · 45 와 옛 이름(번호 · 구분 · 성명 · 국코드 ·
               기초_주식수 · 기초_지분율 · 증가(26 ~ 34 합) · 감소(35 ~ 42 합) · 기말_주식수 · 기말_지분율 · 관계). 개인 성명 ·
               주민등록번호는 넣지 않는다(21 은 읽지 않음)
"""
from __future__ import annotations

import re

KINDS = ("개인", "영리법인", "비영리법인", "외국법인", "외국인", "기타")
COUNTRY = {"대한민국", "한국"}
ID_NO = re.compile(r"^\d{6}-?\d{7}$|^\d{3}-?\d{2}-?\d{5}$|^\d{6}-?\*+$")
NUM = re.compile(r"^\d{1,3}(?:,\d{3})*$|^\d+$")
RATE = re.compile(r"^\d+(?:\.\d+)?$")
SHARE_NUM = r"(\d[\d,]*(?![\d,.]))? ?"          # 「2. 자본금」 의 2 같은 절 번호는 숫자로 읽지 않는다


def _i(s) -> int:
    try:
        return int(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def basic_from_text(text: str) -> dict:
    """1절 기초 · 기말 보통주 · 우선주(주식수 · 액면가 · 자본금). 못 읽으면 빈 dict."""
    txt = " ".join((text or "").split())
    m = re.search(r"기 ?초 ?보통주 ?" + SHARE_NUM * 3 + r"우선주 ?" + SHARE_NUM * 3 + r"기 ?말 ?보통주 ?" + SHARE_NUM * 3
                  + r"우선주 ?" + SHARE_NUM * 3, txt)
    if not m:
        return {}
    g = [_i(x or 0) for x in m.groups()]
    out = {}
    for k, (when, kind) in enumerate((("기초", "보통주"), ("기초", "우선주"), ("기말", "보통주"), ("기말", "우선주"))):
        shares, par, capital = g[k * 3:(k + 1) * 3]
        out[f"{when}_{kind}_주식수"] = shares
        out[f"{when}_{kind}_액면가"] = par
        out[f"{when}_{kind}_자본금"] = capital
    for when in ("기초", "기말"):
        out[f"{when}_자본금"] = out[f"{when}_보통주_자본금"] + out[f"{when}_우선주_자본금"]
    return out


def _header(words: list) -> dict | None:
    """3절 머리 줄의 열 경계. 「지분율」 두 낱말이 같은 높이에 있는 줄을 찾는다."""
    rates = [w for w in words if w[4] == "지분율"]
    for a in rates:
        pair = sorted((w for w in rates if abs(w[1] - a[1]) < 3), key=lambda w: w[0])
        if len(pair) < 2:
            continue
        left, right = pair[0], pair[-1]
        sell = [w for w in words if w[4] == "양도" and abs(w[1] - a[1]) < 3 and left[2] < w[0] < right[0]]
        end_shares = [w for w in words if "주식수" in w[4] and abs(w[1] - a[1]) < 8 and sell and w[0] > sell[0][2]
                      and w[2] < right[0]]
        code = [w for w in words if w[4] in ("국코드", "코드") and w[2] < left[0] and abs(w[1] - a[1]) < 8]
        if not sell or not end_shares:
            continue
        return {"y": max(left[3], right[3]), "left": left, "right": right, "sell": sell[0], "end": end_shares[0],
                "code_x": code[0][0] if code else None}
    return None


def _lines(words: list, top: float) -> list[list]:
    """머리 줄 아래 낱말을 줄(높이)로 묶는다. 일련번호로 시작하는 줄만."""
    rows: list[list] = []
    for w in sorted((w for w in words if w[1] > top), key=lambda w: (w[1], w[0])):
        if rows and abs(rows[-1][0][1] - w[1]) < 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        if r[0][0] < 40 and re.fullmatch(r"\d{1,3}", r[0][4]):
            out.append(r)
    return out


def rows_from_words(words: list) -> tuple[list[dict], dict | None]:
    """쪽 하나의 3절 줄(합계 줄은 따로). (주주 줄 목록, 합계 줄 또는 None)."""
    h = _header(words)
    if h is None:
        return [], None
    left, right, sell, end = h["left"], h["right"], h["sell"], h["end"]
    out, total = [], None
    for line in _lines(words, h["y"]):
        no = int(line[0][4])
        rest = line[1:]
        label = next((w[4] for w in rest if w[0] < 100), "")
        kind = next((k for k in KINDS if label == k), None)
        r = {"번호": no, "구분": kind or label, "성명": "", "국코드": "", "기초_주식수": 0, "기초_지분율": "", "증가": 0, "감소": 0,
             "기말_주식수": 0, "기말_지분율": "", "관계": ""}
        names = []
        for w in rest:
            t, x0, x1 = w[4], w[0], w[2]
            if x1 <= left[0] - 25 and re.fullmatch(r"[A-Z]{2}", t):
                r["국코드"] = t
            elif x1 <= left[0] - 25:
                if w[0] > 65 and t != label and t not in COUNTRY and not ID_NO.match(t):
                    names.append(t)
            elif x1 <= left[0] + 2 and NUM.match(t):
                r["기초_주식수"] = _i(t)
            elif x1 <= left[2] + 4 and RATE.match(t):
                r["기초_지분율"] = t
            elif x1 < sell[0] - 2 and NUM.match(t):
                r["증가"] += _i(t)
            elif x1 < end[0] - 2 and NUM.match(t):
                r["감소"] += _i(t)
            elif x1 <= right[0] + 2 and NUM.match(t):
                r["기말_주식수"] = _i(t)
            elif x1 <= right[2] + 4 and RATE.match(t):
                r["기말_지분율"] = t
            elif x0 > right[2] and re.fullmatch(r"\d{2}", t):
                r["관계"] = t
        if kind and kind != "개인":
            r["성명"] = " ".join(names)
        if label == "합계":
            total = r
            continue
        has_numbers = r["기초_주식수"] or r["기말_주식수"] or r["증가"] or r["감소"]
        if kind is None and not has_numbers:
            continue                    # 2 제출의무면제주주소계 처럼 빈 줄
        if kind is None:
            r["구분"] = re.sub(r"\s+", "", "".join(w[4] for w in rest if w[0] < 200 and not NUM.match(w[4]))) or label
        out.append(r)
    return out, total


def edition(text: str) -> str:
    """54호 쪽 글자 → 서식 판 「2026」 · 「2021」. 2026. 3. 20. 개정 서식은 머리에 「개정 2026」, 3절에 ㊶ 「이익소각」 열이 있다.
    2021 판(과 그 앞 판)은 1절에 「기초 보통주 … 우선주」 줄이 있다. 둘 다 없으면 2021 판으로 읽는다(지금까지와 같이)."""
    t = re.sub(r"\s+", "", text or "")
    if "개정2026" in t or "이익소각" in t:
        return "2026"
    return "2021"


def read_54(pages: list[dict]) -> tuple[dict, list[dict], list[str]]:
    """54호 쪽들(쪽 dict: text · words) → (cells["54"], rows["54"], 문제 글 목록). 54호 쪽이 없으면 ({}, [], []).
    첫 쪽 글자로 판을 가려 2026 판이면 read_54_2026, 아니면 아래 2021 판 읽기."""
    if not pages:
        return {}, [], []
    if edition(pages[0].get("text", "")) == "2026":
        return read_54_2026(pages)
    problems = []
    cells = basic_from_text(pages[0].get("text", ""))
    if not cells:
        problems.append("54호 1절(기초 · 기말 주식수 · 액면가 · 자본금)을 읽지 못했습니다")
    rows, total = [], None
    for p in pages:
        got, tot = rows_from_words(p.get("words") or [])
        rows += got
        total = total or tot
    if total:
        cells["합계_기초_주식수"] = total["기초_주식수"]
        cells["합계_기말_주식수"] = total["기말_주식수"]
        s_begin = sum(r["기초_주식수"] for r in rows)
        s_end = sum(r["기말_주식수"] for r in rows)
        if (s_begin, s_end) != (total["기초_주식수"], total["기말_주식수"]):
            problems.append(f"54호 주주 줄 합계(기초 {s_begin:,} · 기말 {s_end:,})가 합계 줄(기초 {total['기초_주식수']:,} · "
                            f"기말 {total['기말_주식수']:,})과 다릅니다")
    if not rows:
        problems.append("54호 3절 주주 줄을 읽지 못했습니다")
    for r in rows:
        if r["기초_주식수"] + r["증가"] - r["감소"] != r["기말_주식수"]:
            problems.append(f"54호 {r['번호']}번 줄의 기초 {r['기초_주식수']:,} + 증가 {r['증가']:,} − 감소 {r['감소']:,}가 "
                            f"기말 {r['기말_주식수']:,}과 다릅니다")
    return cells, rows, problems


# ---------------------------------------------------------------- 2026. 3. 20. 개정 서식

COLS_2 = (("12", ("주식수",)), ("13", ("액면",)), ("14", ("발행",)), ("15", ("자본금",)))
# 3절 열: 머리 글에 든 낱말. 왼쪽부터 차례로 맞춘다(상속 · 증여 · 명의신탁 · 신탁 · 기타 · 주식수 · 지분율은 두 번 나온다)
COLS_3 = (("19", ("구분",)), ("20", ("성명",)), ("21", ("등록번호",)), ("22", ("거주지국",)), ("23", ("코드",)),
          ("24", ("주식수",)), ("25", ("지분율",)), ("26", ("양수",)), ("27", ("유상",)), ("28", ("무상",)), ("29", ("상속",)),
          ("30", ("증여",)), ("31", ("전환",)), ("32", ("명의",)), ("33", ("신탁",)), ("34", ("기타",)), ("35", ("양도",)),
          ("36", ("상속",)), ("37", ("증여",)), ("38", ("감자",)), ("39", ("명의",)), ("40", ("신탁",)), ("41", ("소각",)),
          ("42", ("기타",)), ("43", ("주식수",)), ("44", ("지분율",)), ("45", ("관계",)))
UP = tuple(str(n) for n in range(26, 35))
DOWN = tuple(str(n) for n in range(35, 43))
NUM_WORD = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d+$")


def _n(s) -> str:
    return re.sub(r"[\s·ㆍ]", "", str(s or ""))


def _lines_of(words: list) -> list[list]:
    """낱말을 높이로 묶은 줄(위 → 아래, 줄 안은 왼쪽 → 오른쪽)."""
    rows: list[list] = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if rows and abs((rows[-1][0][1] + rows[-1][0][3]) / 2 - yc) < 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w[0]) for r in rows]


def _line_with(words: list, key: str, top: float = -1, bottom: float = 1e9) -> list | None:
    """top ~ bottom 사이에서 띄어쓰기 상관없이 key 가 든 첫 줄."""
    for line in _lines_of([w for w in words if top < (w[1] + w[3]) / 2 < bottom]):
        if key in _n("".join(w[4] for w in line)):
            return line
    return None


def _clusters(words: list, gap: float = 3) -> list[dict]:
    """머리 낱말을 가로로 겹치는(gap 안) 것끼리 묶은 열 [{x0, x1, xc, text}] (왼쪽 → 오른쪽)."""
    out: list[dict] = []
    for w in sorted(words, key=lambda w: w[0]):
        hit = next((c for c in out if w[0] <= c["x1"] + gap and w[2] >= c["x0"] - gap), None)
        if hit:
            hit["x0"], hit["x1"] = min(hit["x0"], w[0]), max(hit["x1"], w[2])
            hit["words"].append(w)
        else:
            out.append({"x0": w[0], "x1": w[2], "words": [w]})
    for c in out:
        c["text"] = _n("".join(w[4] for w in sorted(c["words"], key=lambda w: (round(w[1]), w[0]))))
        c["xc"] = (c["x0"] + c["x1"]) / 2
    return sorted(out, key=lambda c: c["x0"])


def _match(clusters: list[dict], spec) -> dict:
    """열 묶음 → {란 코드: 열}. 왼쪽부터, spec 차례를 거스르지 않게 맞춘다."""
    out, k = {}, 0
    for c in clusters:
        for j in range(k, len(spec)):
            code, keys = spec[j]
            if any(key in c["text"] for key in keys):
                out[code] = c
                k = j + 1
                break
    return out


def _nearest(cols: dict, xc: float) -> str | None:
    return min(cols, key=lambda code: abs(cols[code]["xc"] - xc)) if cols else None


def _label_x(line: list) -> float:
    """⑯ 기초 · ⑰ 기말 줄의 이름 낱말 왼쪽 끝."""
    return min((w[0] for w in line if re.search(r"[기초말]", w[4])), default=line[0][0])


def _basic_2026(words: list) -> tuple[dict, list[str]]:
    """2절 ⑯ 기초 · ⑰ 기말 줄(⑫ 주식수 · ⑬ 주당 액면가액 · ⑮ 자본금). 2절은 좌우 두 쪽이고 ⑯ 은 왼쪽 첫 줄, ⑰ 은 오른쪽 끝 줄이다."""
    t2 = _line_with(words, "자본금(출자금)변동상황")
    t3 = _line_with(words, "세부변동내역")
    if t2 is None:
        return {}, ["54호(2026 판) 2절 자본금 변동상황을 찾지 못했습니다"]
    top = max(w[3] for w in t2)
    bottom = min(w[1] for w in t3) if t3 else 1e9
    begin = _line_with(words, "기초", top, bottom)
    end = _line_with(words, "기말", top, bottom)
    if begin is None:
        return {}, ["54호(2026 판) 2절 ⑯ 기초 줄을 찾지 못했습니다"]
    head_top = max(w[3] for w in (_line_with(words, "주식의내용", top, bottom) or t2))
    clusters = _clusters([w for w in words if head_top < w[1] and w[3] < min(x[1] for x in begin)])
    mid = _label_x(end) - 5 if end else max(w[2] for w in words) / 2
    out, problems = {}, []
    for tag, line, left in (("16", begin, True), ("17", end, False)):
        if line is None:
            problems.append("54호(2026 판) 2절 ⑰ 기말 줄을 찾지 못했습니다")
            continue
        cols = _match([c for c in clusters if (c["xc"] < mid) == left], COLS_2)
        lx = _label_x(line)
        for w in line:
            xc = (w[0] + w[2]) / 2
            if xc <= lx or (xc < mid) != left or not NUM_WORD.match(w[4]):
                continue
            code = _nearest(cols, xc)
            if code in ("12", "13", "15"):
                out[f"{tag}_{code}"] = _i(w[4])
    for tag, name in (("16", "⑯ 기초"), ("17", "⑰ 기말")):
        shares, par, cap = out.get(f"{tag}_12"), out.get(f"{tag}_13"), out.get(f"{tag}_15")
        if shares and par and cap is not None and shares * par != cap:
            problems.append(f"54호(2026 판) {name} 주식수 {shares:,} × 주당 액면가액 {par:,} 가 자본금 {cap:,} 과 다릅니다"
                            "(무액면주식이면 맞습니다)")
    if "16_15" not in out:
        problems.append("54호(2026 판) ⑯ 기초 자본금을 읽지 못했습니다")
    return out, problems


def _holders_2026(words: list) -> tuple[list[dict], dict | None, str]:
    """3절 주주 줄(쪽 하나) → (주주 줄, 01 합계 줄, 문제). 머리 줄은 「증가 주식수 · 감소 주식수」 줄 아래 낱말을 열로 묶는다
    (그 위의 「변동 상황」 · 「증가 주식수」 글은 여러 열에 걸쳐 열을 가르지 못한다)."""
    t3 = _line_with(words, "세부변동내역")
    if t3 is None:
        return [], None, ""
    top = max(w[3] for w in t3)
    split = _line_with(words, "증가주식수", top) or _line_with(words, "감소주식수", top)
    band_top = max(w[3] for w in split) if split else top
    tail = (_line_with(words, "지배주주와의관계코드본인", band_top) or _line_with(words, "자기주식보유현황", band_top)
            or _line_with(words, "주식신탁현황", band_top))
    bottom = min(w[1] for w in tail) if tail else 1e9
    lines = _lines_of([w for w in words if band_top < (w[1] + w[3]) / 2 < bottom])
    first = next((i for i, ln in enumerate(lines) if re.fullmatch(r"\d{1,3}", ln[0][4]) and len(ln) > 1), None)
    if first is None:
        return [], None, "54호(2026 판) 3절 주주 줄을 찾지 못했습니다"
    first_y = min(w[1] for w in lines[first])
    cols = _match(_clusters([w for w in words if band_top < w[1] and w[3] <= first_y]), COLS_3)
    if not {"24", "43"} <= set(cols):
        return [], None, "54호(2026 판) 3절 머리 줄(기초 · 기말 주식수 열)을 찾지 못했습니다"
    rows, total = [], None
    for ln in lines[first:]:
        if not re.fullmatch(r"\d{1,3}", ln[0][4]):
            continue
        r = {"번호": int(ln[0][4]), **{c: "" for c in ("19", "20", "22", "23", "25", "44", "45")},
             **{c: 0 for c in ("24", *UP, *DOWN, "43")}}
        texts: dict = {}
        for w in ln[1:]:
            code, t = _nearest(cols, (w[0] + w[2]) / 2), w[4]
            if code in ("24", "43", *UP, *DOWN) and NUM_WORD.match(t):
                r[code] += _i(t)
            elif code in ("25", "44") and RATE.match(t):
                r[code] = t
            elif code == "45" and re.fullmatch(r"\d{2}", t):
                r[code] = t
            elif code == "23" and re.fullmatch(r"[A-Z]{2}", t):
                r[code] = t
            elif code in ("19", "20", "22"):
                texts.setdefault(code, []).append(t)
        label = _n("".join(texts.get("19", [])))
        kind = next((k for k in KINDS if label == k), None)
        r["19"] = kind or label
        r["22"] = " ".join(texts.get("22", []))
        names = [t for t in texts.get("20", []) if not ID_NO.match(t)]
        r["20"] = " ".join(names) if kind and kind != "개인" else ""
        r.update({"구분": r["19"], "성명": r["20"], "국코드": r["23"], "기초_주식수": r["24"], "기초_지분율": r["25"],
                  "증가": sum(r[c] for c in UP), "감소": sum(r[c] for c in DOWN), "기말_주식수": r["43"],
                  "기말_지분율": r["44"], "관계": r["45"]})
        if label in ("합계", "계"):
            total = r
        elif "면제" in label or "소계" in label:
            continue                    # 02 제출의무면제 주주소계
        elif kind or r["24"] or r["43"] or r["증가"] or r["감소"]:
            rows.append(r)
    return rows, total, ""


def read_54_2026(pages: list[dict]) -> tuple[dict, list[dict], list[str]]:
    """2026. 3. 20. 개정 54호 쪽들 → (cells["54"], rows["54"], 문제). 2절은 첫 쪽, 3절은 쪽마다 머리 줄을 다시 찾는다."""
    basic, problems = _basic_2026(pages[0].get("words") or [])
    cells = {"판": "2026", **basic}
    if "16_15" in cells:
        cells["기초_자본금"] = cells["16_15"]
    if "17_15" in cells:
        cells["기말_자본금"] = cells["17_15"]
    rows, total = [], None
    for k, p in enumerate(pages):
        got, tot, why = _holders_2026(p.get("words") or [])
        rows += got
        total = total or tot
        if why and k == 0:
            problems.append(why)
    if total:
        for code in (*UP, *DOWN):
            if total.get(code):
                cells[f"합계_{code}"] = total[code]
        cells["합계_24"] = cells["합계_기초_주식수"] = total["24"]
        cells["합계_43"] = cells["합계_기말_주식수"] = total["43"]
        s_begin, s_end = sum(r["24"] for r in rows), sum(r["43"] for r in rows)
        if (s_begin, s_end) != (total["24"], total["43"]):
            problems.append(f"54호 주주 줄 합계(기초 {s_begin:,} · 기말 {s_end:,})가 합계 줄(기초 {total['24']:,} · "
                            f"기말 {total['43']:,})과 다릅니다")
    for r in rows:
        if r["24"] + r["증가"] - r["감소"] != r["43"]:
            problems.append(f"54호 {r['번호']}번 줄의 기초 {r['24']:,} + 증가 {r['증가']:,} − 감소 {r['감소']:,}가 "
                            f"기말 {r['43']:,}과 다릅니다")
    return cells, rows, problems
