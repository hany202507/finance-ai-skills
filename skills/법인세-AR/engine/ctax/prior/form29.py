"""전기 신고서 29호(업무용승용차관련비용명세서) 2절 합계 줄과 51호(중소기업등기준검토표) 규모 기준 칸 읽기.

29호 2절 「업무용승용차관련비용 손금불산입 계산」 합계 줄이 전기.json `cells["29"]` 가 된다(CONTRACT.md 13절).
AR 이 전기 15호에 업무외사용금액 손금불산입 줄이 빠졌는지 보는 데 쓴다.

  cells["29"]  {"25": 업무사용 감가상각비(상당액), "26": 업무사용 관련비용, "27": 업무사용 합계,
                "28": 업무외 감가상각비(상당액), "29": 업무외 관련비용, "30": 업무외사용금액 합계,
                "31": 감가상각비(상당액) 한도초과금액, "32": 손금불산입 합계, "33": 손금산입 합계}
               란 번호는 forms/defs/29.json 과 같다.

읽는 법. 쪽 글에서 「2. 업무용승용차관련비용손금불산입계산」 뒤 마지막 「합계」 다음 금액들을 읽는다. 빈 칸은 글에 찍히지 않아
금액 수가 9 보다 적으면 0 인 칸을 넣어 보며 27 = 25 + 26, 30 = 28 + 29, 32 = 30 + 31 이 맞는 꼴이 하나뿐일 때만 쓴다.
맞는 꼴이 둘 이상이면(한도초과 없이 업무사용분만 있는 줄 등) 합계 줄 금액 낱말의 가로 위치를 2절 머리(업무사용금액 ·
업무외사용금액 · 한도초과금액 · 손금불산입 · 손금산입)에 대 본다.

3절 「감가상각비(상당액) 한도초과금액이월명세」 차량별 줄은 전기.json `rows["29"]` 가 된다(10-21). 당기 업무용승용차 조서의
「전기 이월액」 기본값이다.

  rows["29"]   [{"car": 차량번호, "model": 차종, "start": 취득일(임차 시작), "end": 임차 끝 날(없으면 빈 글),
                 "opening": 전기이월액, "excess": 당기 한도초과금액, "cum": 한도초과금액 누계, "reversal": 손금추인(산입)액,
                 "closing": 차기이월액}]

빈 칸은 글에 찍히지 않으므로 금액 낱말의 가로 위치를 3절 머리 다섯(전기이월액 · 당기감가상각비(상당액) · 감가상각비(상당액) ·
손금추인(산입)액 · 차기이월액)에 대 본다. 금액 가운데가 가장 가까운 머리의 란이다. 누계 = 전기이월 + 당기, 차기 = 누계 - 추인이
맞지 않는 줄은 problems 로 낸다. 「합계」 줄과 「별지출력」 쪽의 합계만 있는 줄은 뺀다(차량별 줄은 별지 쪽에 같은 꼴로 있다).

51호는 사업요건 표 아래 「당회사(10)」 · 「규모기준(11)」 · 「자산총액(12)」 · 「당회사(14)」 · 「규모기준(15)」 칸의 억원 숫자다.
숫자는 표제와 같은 높이이거나 바로 아래 줄(25pt 안)에 찍힌다.

  cells["51"]  {"10": 당회사 매출액(억원, 별표1 기준용), "11": 중소기업기본법 시행령 별표1 규모기준(억원), "12": 자산총액(억원),
                "14": 당회사 매출액(억원, 별표3 기준용), "15": 별표3 소기업 규모기준(억원)}
"""
from __future__ import annotations

import re
from itertools import combinations

AMT = re.compile(r"^[△\-]?\d{1,3}(?:,\d{3})+$|^[△\-]?\d+$")
SECTION_2 = re.compile(r"2\.\s*업무용승용차관련비용손금불산입계산")
SECTION_3 = re.compile(r"3\.\s*감가상각비\(상당액\)\s*한도초과금액이월명세")
CODES = ("25", "26", "27", "28", "29", "30", "31", "32", "33")
CHECKS = (("27", "25", "26"), ("30", "28", "29"), ("32", "30", "31"))


def _i(s: str) -> int:
    t = s.replace(",", "")
    neg = t.startswith(("△", "-"))
    t = t.lstrip("△-")
    return -int(t) if neg else int(t)


def total_row(text: str, words: list | None = None) -> tuple[dict | None, str | None]:
    """29호 쪽 글 → (cells, 문제 글). 2절이 없으면 (None, None). 금액으로 란이 하나로 안 정해지면 낱말 좌표(words)로 가린다."""
    m = SECTION_2.search(text)
    if not m:
        return None, None
    body = text[m.end():]
    end = SECTION_3.search(body)
    if end:
        body = body[:end.start()]
    tokens = [t.strip() for t in body.splitlines() if t.strip()]
    heads = [k for k, t in enumerate(tokens) if re.sub(r"\s", "", t) == "합계"]
    if not heads:
        return None, "29호 2절 합계 줄을 찾지 못했습니다"
    nums = []
    for t in tokens[heads[-1] + 1:]:
        if not AMT.match(t):
            break
        nums.append(_i(t))
    if not nums or len(nums) > len(CODES):
        return None, f"29호 2절 합계 줄 금액 {len(nums)}개를 란에 맞추지 못했습니다"
    fits = []
    for blanks in combinations(range(len(CODES)), len(CODES) - len(nums)):
        it = iter(nums)
        cells = {c: (0 if k in blanks else next(it)) for k, c in enumerate(CODES)}
        if all(cells[a] == cells[b] + cells[c] for a, b, c in CHECKS):
            fits.append(cells)
    if len(fits) > 1 and words:
        fits = [f for f in fits if _fits_columns(f, nums, words)] or fits
    if len(fits) != 1:
        return None, f"29호 2절 합계 줄 금액({', '.join(f'{n:,}' for n in nums)})을 란에 하나로 맞추지 못했습니다"
    return fits[0], None


# 2절 머리 낱말 → 그 아래 열의 란. 금액 낱말의 가운데가 어느 머리와 가까운지(머리 가운데 사이의 중간값으로 나눔)로 란 묶음을 정한다
HEADS_2 = (("업무사용금액", ("25", "26", "27")), ("업무외사용금액", ("28", "29", "30")), ("한도초과금액", ("31",)),
           ("손금불산입", ("32",)), ("손금산입", ("33",)))


def _fits_columns(cells: dict, nums: list[int], words: list) -> bool:
    """금액이 0 이 아닌 란이 금액 낱말의 가로 위치(2절 머리 열)와 맞는가. 위치를 못 정하면 True(거르지 않는다)."""
    heads = []
    for name, codes in HEADS_2:
        w = next((w for w in words if w[4] == name), None)
        if w is None:
            return True
        heads.append(((w[0] + w[2]) / 2, codes, w[3]))
    top = max(h[2] for h in heads)
    total = [w for w in words if w[4] == "합계" and w[1] > top and w[2] < heads[0][0]]
    if not total:
        return True
    yc = (total[-1][1] + total[-1][3]) / 2
    row = sorted((w for w in words if abs((w[1] + w[3]) / 2 - yc) < 3 and AMT.match(w[4]) and w[0] > total[-1][2]),
                 key=lambda w: w[0])
    if len(row) != len(nums):
        return True
    cuts = [(a[0] + b[0]) / 2 for a, b in zip(heads, heads[1:])]
    filled = [c for c in CODES if cells[c] != 0]
    if len(filled) != len(row):
        return True
    for w, code in zip(row, filled):
        xc = (w[0] + w[2]) / 2
        group = sum(1 for cut in cuts if xc > cut)
        if code not in heads[group][1]:
            return False
    return True


def read_29(pages: list[dict]) -> tuple[dict, list[str]]:
    """29호 쪽들(쪽 dict: text · words) → (cells["29"], 문제 글 목록). 29호 쪽이 없거나 2절 금액이 없으면 ({}, [])."""
    problems = []
    for p in pages:
        got, why = total_row(p.get("text") or "", p.get("words"))
        if got:
            return got, []
        if why:
            problems.append(why)
    return {}, problems


LABELS_51 = (("10", r"당회사\(10\)"), ("11", r"규모기준\(11\)"), ("12", r"자산총액\(12\)"), ("14", r"당회사\(14\)"),
             ("15", r"규모기준\(15\)"))
NUM_51 = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$")


def scale_51(words: list) -> dict:
    """51호 첫 쪽 낱말(x0, y0, x1, y1, word, ...) → {란: 억원}. 표제 오른쪽에서 같은 높이 또는 바로 아래 줄의 가장 가까운 숫자."""
    out = {}
    nums = [w for w in words if NUM_51.match(w[4]) and not re.fullmatch(r"\d{6}", w[4])]
    for code, rx in LABELS_51:
        head = next((w for w in words if re.search(rx, w[4])), None)
        if head is None:
            continue
        yc = (head[1] + head[3]) / 2
        near = [(abs((w[1] + w[3]) / 2 - yc), w) for w in nums
                if (w[0] + w[2]) / 2 > head[0] and -4 <= (w[1] + w[3]) / 2 - yc <= 25]
        if near:
            out[code] = float(min(near, key=lambda x: x[0])[1][4].replace(",", ""))
    return out


# 3절 머리 낱말 → 란. 같은 이름(감가상각비(상당액))이 3절 제목에도 있어 제목 줄보다 아래 낱말만 본다
HEADS_3 = (("전기이월액", "opening"), ("당기감가상각비(상당액)", "excess"), ("감가상각비(상당액)", "cum"),
           ("손금추인(산입)액", "reversal"), ("차기이월액(", "closing"))
DATE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")


def carry_rows(pages: list[dict]) -> tuple[list[dict], list[str]]:
    """29호 쪽들 → (3절 차량별 줄, 문제 글). 같은 차량번호가 두 쪽(본문 · 별지)에 있으면 앞의 것만."""
    out, problems, seen = [], [], set()
    for p in pages:
        got, why = _carry_page(p.get("words") or [])
        problems += why
        for r in got:
            if r["car"] not in seen:
                seen.add(r["car"])
                out.append(r)
    return out, problems


def _carry_page(words: list) -> tuple[list[dict], list[str]]:
    top = next((w for w in words if "한도초과금액이월명세" in w[4]), None)
    if top is None:
        return [], []
    bottom = next((w[1] for w in words if w[1] > top[3] and ("처분손실및" in w[4] or w[4] == "4.")), 10 ** 6)
    body = [w for w in words if top[3] <= w[1] < bottom]
    heads = []
    for name, key in HEADS_3:
        w = next((w for w in body if w[4] == name), None)
        if w is None:
            return [], ["29호 3절 머리를 찾지 못했습니다"]
        heads.append(((w[0] + w[2]) / 2, key, w[3]))
    kind = next((w for w in body if w[4] == "차종"), None)
    when = next((w for w in body if w[4] in ("취득일", "(임차기간)")), None)
    if kind is None or when is None:
        return [], ["29호 3절 차종 · 취득일 머리를 찾지 못했습니다"]
    head_bottom = max(h[2] for h in heads)
    yc = lambda w: (w[1] + w[3]) / 2                              # noqa: E731
    xc = lambda w: (w[0] + w[2]) / 2                              # noqa: E731
    lower = [w for w in body if w[1] > head_bottom]
    # 차량번호 열(차종 머리 왼쪽)의 낱말이 줄의 닻이다. 「합계」 도 닻이지만 줄로 내지 않는다
    anchors = sorted((w for w in lower if w[2] <= kind[0] + 2), key=yc)
    out, problems = [], []
    for i, a in enumerate(anchors):
        y0, y1 = yc(a), (yc(anchors[i + 1]) if i + 1 < len(anchors) else 10 ** 6)
        car = re.sub(r"\s", "", a[4])
        if car.startswith(("합계", "별지")):
            continue
        same = [w for w in lower if abs(yc(w) - y0) < 4]
        amounts = [w for w in same if AMT.match(w[4]) and xc(w) > when[2] + 2]
        if not amounts:
            continue
        cells = {k: 0 for _, k, _ in heads}
        for w in amounts:
            cells[min(heads, key=lambda h: abs(h[0] - xc(w)))[1]] += _i(w[4])
        model = " ".join(w[4] for w in sorted(same, key=lambda w: w[0]) if a[2] < xc(w) < when[0] - 2)
        dates = [w[4] for w in sorted(lower, key=yc) if DATE.match(w[4]) and y0 - 6 < yc(w) < y1 - 4
                 and when[0] - 15 < xc(w) < when[2] + 15]
        row = {"car": car, "model": model, "start": dates[0] if dates else "", "end": dates[1] if len(dates) > 1 else "",
               **cells}
        if row["cum"] != row["opening"] + row["excess"] or row["closing"] != row["cum"] - row["reversal"]:
            problems.append(f"29호 3절 {car} 줄 금액(전기이월 {row['opening']:,} · 당기 {row['excess']:,} · 누계 {row['cum']:,} · "
                            f"추인 {row['reversal']:,} · 차기 {row['closing']:,})이 누계 = 전기 + 당기, 차기 = 누계 - 추인에 맞지 않습니다")
        out.append(row)
    return out, problems
