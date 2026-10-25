"""전기 신고서 16호의2 · 40호(갑) · 47호(갑) 읽기(10-25). 낱말 좌표로 읽는다(글자 순서는 PDF 마다 달라 쓰지 않는다).

  rows["16의2"]  2절 배당금지급법인현황 줄 [{name, biz_no, shares, share}]. share 는 인쇄된 지분율(%) 글 그대로(「11.05」).
                 소재지 · 대표자는 읽지 않는다. 당기 수입배당금 조서가 지급법인 이름으로 잇고 지분율 기본값으로 쓴다
  cells["40갑"]  1절 손익조정금액 가 · 나 · 계 줄의 ② 당기손익금 해당액 · ③ 회사손익금 계상액 · ④ 차익조정 · ⑤ 차손조정 ·
                 ⑥ 손익조정금액. 란 이름은 「가_2」 · 「계_6」 꼴(forms/defs/40갑.json 과 같은 꼴)
  cells["47갑"]  코드 줄마다 ③ 회사계상금액 · ④ 세무상부인(조정)금액 · ⑤ 차가감금액. 란 이름은 코드(③) · 「코드_4」 · 「코드_5」
                 (forms/defs/47갑.json 과 같다). 맨 아래 상여 · 배당 등(97) · 이익처분금액(98) 줄은 꼴이 달라 읽지 않는다

AR 신고 점검(ar/engine.py check_prior_fx_forms)이 40호(갑) ③ 이 빈 줄과 47호(갑) ④ 가 15호와 어긋나는 줄을 찾는 데 쓴다.
"""
from __future__ import annotations

import re

BIZ = re.compile(r"^\d{3}-\d{2}-\d{5}$")
RATE = re.compile(r"^\d{1,3}(?:\.\d+)?$")
AMT = re.compile(r"^[△\-]?\d{1,3}(?:,\d{3})+$|^[△\-]?\d+$")
CODE = re.compile(r"^\d{2,3}$")


def _i(s: str) -> int:
    t = str(s).replace(",", "")
    neg = t.startswith(("△", "-"))
    t = t.lstrip("△-")
    return -int(t) if neg else int(t)


def _mid(w) -> float:
    return (w[1] + w[3]) / 2


def _cx(w) -> float:
    return (w[0] + w[2]) / 2


def _nearest(x: float, cols: dict) -> str:
    return min(cols, key=lambda k: abs(cols[k] - x))


# ---------------------------------------------------------------- 16호의2

def read_16_2(pages: list[dict]) -> tuple[list[dict], list[str]]:
    """줄은 ⑪ 지분율 열에 숫자가 있는 가로줄이다(사업자등록번호는 가린 PDF 가 있어 줄 찾기에 쓰지 않는다). 법인명은 ⑦ 사업자등록번호
    머리 왼쪽 낱말, 사업자등록번호는 그 머리 아래 낱말을 이은 것(가렸으면 빈 글), 주식수는 ⑩ 발행주식총수 머리 아래 숫자다."""
    rows, why = [], []
    for pg in pages:
        words = pg.get("words") or []
        top = next((w[1] for w in words if "배당금지급법인현황" in w[4]), None)
        if top is None:
            continue
        bottom = next((w[1] for w in words if "수입배당금액및익금불산입" in w[4] and w[1] > top), 10 ** 6)
        band = [w for w in words if top < w[1] < bottom]
        share_h = next((w for w in band if "지분율" in w[4]), None)
        biz_h = next((w for w in band if "사업자등록번호" in w[4]), None)
        count_h = next((w for w in band if "주식총수" in w[4] or w[4].startswith("⑩")), None)
        if share_h is None or biz_h is None:
            why.append(f"{pg.get('page_no')}쪽 16호의2 2절 머리(지분율 · 사업자등록번호)를 찾지 못했다")
            continue
        head_bottom = max(share_h[3], biz_h[3], count_h[3] if count_h else 0)
        for s in band:
            if not (s[1] > head_bottom and RATE.match(s[4]) and s[2] >= share_h[0] - 5):
                continue
            line = sorted((w for w in band if abs(_mid(w) - _mid(s)) <= 4), key=lambda w: w[0])
            name = "".join(w[4] for w in line if w[2] <= biz_h[0] + 2)
            biz = "".join(w[4] for w in line if biz_h[0] - 8 <= _cx(w) <= biz_h[2] + 8)
            shares = next((w[4] for w in line if count_h is not None and AMT.match(w[4]) and "," in w[4]
                           and count_h[0] - 15 <= _cx(w) <= count_h[2] + 15), "")
            if not name:
                why.append(f"{pg.get('page_no')}쪽 16호의2 지분율 {s[4]} 줄의 법인명을 읽지 못했다")
                continue
            rows.append({"name": name, "biz_no": biz if BIZ.match(biz) else "", "shares": _i(shares) if shares else 0,
                         "share": s[4]})
    return rows, why


# ---------------------------------------------------------------- 40호(갑)

COLS_40 = (("2", "당기손익금"), ("3", "회사손익금"), ("4", "차익조정"), ("5", "차손조정"), ("6", "손익조정금액"))


def read_40(pages: list[dict]) -> tuple[dict, list[str]]:
    out, why = {}, []
    for pg in pages:
        words = pg.get("words") or []
        cols = {}
        for code, label in COLS_40:
            w = next((w for w in words if label in w[4]), None)
            if w is not None:
                cols[code] = _cx(w)
        rows = {}
        for w in words:
            if w[0] > 100:
                continue
            if w[4].startswith("가.") and "가" not in rows:
                rows["가"] = w[1]
            elif w[4].startswith("나.") and "나" not in rows:
                rows["나"] = w[1]
            elif w[4].startswith("다.") and "다" not in rows:
                rows["다"] = w[1]
        if len(cols) < 3 or "가" not in rows:
            continue
        # 2절(환율조정계정손익계산명세) 머리 위의 「계」 가 1절 계 줄이다
        part2 = min((w[1] for w in words if w[4] == "2." and w[0] < 80 and w[1] > rows["가"]), default=10 ** 6)
        total = next((w for w in words if w[4] == "계" and w[0] < 150 and rows["가"] < w[1] < part2), None)
        bands = {"가": (rows["가"] - 4, rows.get("나", rows["가"] + 25) - 2)}
        if "나" in rows:
            bands["나"] = (rows["나"] - 4, rows.get("다", rows["나"] + 25) - 2)
        if total is not None:
            bands["계"] = (_mid(total) - 6, _mid(total) + 6)
        for w in words:
            if not AMT.match(w[4]) or "," not in w[4] or w[0] < 150:
                continue
            row = next((k for k, (lo, hi) in bands.items() if lo <= _mid(w) <= hi), None)
            if row is None:
                continue
            key = f"{row}_{_nearest(_cx(w), cols)}"
            if key in out:
                why.append(f"{pg.get('page_no')}쪽 40호(갑) {key} 에 금액이 둘이다")
                continue
            out[key] = _i(w[4])
    return out, why


# ---------------------------------------------------------------- 47호(갑)

COLS_47 = (("", "③회사"), ("_4", "④세무상부인"), ("_5", "⑤차가감금액"))
SKIP_47 = {"97", "98"}


def read_47(pages: list[dict]) -> tuple[dict, list[str]]:
    out, why = {}, []
    for pg in pages:
        words = pg.get("words") or []
        cols = {}
        for suffix, label in COLS_47:
            w = next((w for w in words if w[4].startswith(label)), None)
            if w is not None:
                cols[suffix] = _cx(w)
        head = next((w for w in words if w[4] == "코드"), None)
        if len(cols) < 3 or head is None:
            continue
        lo, hi = head[0] - 10, head[2] + 10
        for c in words:
            if not (CODE.match(c[4]) and lo <= _cx(c) <= hi and c[1] > head[3]) or c[4] in SKIP_47:
                continue
            for w in words:
                if w[0] <= c[2] or abs(_mid(w) - _mid(c)) > 5 or not AMT.match(w[4]) or "," not in w[4]:
                    continue
                key = c[4] + _nearest(_cx(w), cols)
                if key in out:
                    why.append(f"{pg.get('page_no')}쪽 47호(갑) {key} 에 금액이 둘이다")
                    continue
                out[key] = _i(w[4])
    return out, why
