"""법제처 별지 서식 PDF 원본 위에 값만 얹는다. → 2 조서/통합고용_법정서식.pdf

서식 쪽은 법제처 국가법령정보센터 파일을 그대로 쓴다(forms/*.pdf, 법령 서식이라 저작권 보호 대상이 아니다, 저작권법 제7조).
칸 좌표는 forms/coords.json(forms/build.py 가 만든다). 여기서는 PDF 를 읽지 않고 좌표에 글자를 넣기만 한다.
값은 엔진 결과(calc.compute)다. 워크북 수식 값과 같은지는 8엔진대조 시트가 본다.

- 2025년 12월 31일이 속하는 과세연도까지: 서식(1) 3쪽 + 명세서
- 2026 과세연도부터: 서식(2) 3쪽(신규공제 · 추가공제) + 기존공제(2 · 3차 연도)가 있으면 서식(1) 3쪽 + 명세서
  (기존공제는 종전 규정이라 종전 서식으로 신청한다. 시행규칙 부칙 <제23호, 2026. 3. 20.> 제6조, 2026-10-15 회계사 확인)
- 명세서 사람별 줄이 한 쪽(해당 10줄 · 직전 11줄)을 넘으면 같은 쪽을 한 장 더 붙인다
- 작성방법만 있는 쪽은 넣지 않는다. 사업자등록번호 · 대표자 · 생년월일 · 주소 · 날짜 · 서명은 사람이 적는다
"""
from __future__ import annotations

import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import fitz

from .calc import FAR, age_limits, deemed_until, is_senior, youth_cutoff
from .model import Inputs

HERE = Path(__file__).resolve().parent
FORMS = HERE / "forms"
FONT = "korea"            # PyMuPDF 내장 CJK 글꼴(Droid Sans Fallback)
SIZE, ROW_SIZE = 9.0, 7.0
OUT_PDF = "통합고용_법정서식.pdf"
KIND_CODE = {"청년": "4", "장애인": "5", "고령자": "6", "경력단절": "7", "북한이탈주민": "8"}


def coords() -> dict:
    return json.loads((FORMS / "coords.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 글자 꼴

def n2(x) -> str:
    return f"{float(x):,.2f}"


def won(x) -> str:
    return f"{int(round(float(x))):,}"


def num(x) -> str:
    """개월수 · 인원: 정수면 정수, 아니면 소수 둘째 자리."""
    f = float(x)
    return str(int(f)) if f == int(f) else f"{f:.2f}"


def ymd(d: date | None) -> str:
    return d.strftime("%Y%m%d") if d else ""


def yn(v) -> str:
    return "Y" if v in (True, "Y") else "N"


# ---------------------------------------------------------------- 값

def _size_key(co) -> str:
    if co.size == "중소기업":
        return "중소수도권밖" if co.capital == "N" else "중소수도권내"
    return "중견" if co.size == "중견기업" else "일반"


def _head(co, company: str) -> dict:
    s, e = co.fy_start, co.fy_end
    return {"company": company, "fy_y1": str(s.year), "fy_m1": f"{s.month:02d}", "fy_d1": f"{s.day:02d}",
            "fy_y2": str(e.year), "fy_m2": f"{e.month:02d}", "fy_d2": f"{e.day:02d}"}


def _judge_vals(res: dict, names: tuple, per_worker: bool) -> list:
    src = res["used"] if per_worker else res["legacy"]
    return [src[n] for n in names]


def form1(inp: Inputs, res: dict, company: str, legacy: bool) -> dict:
    """별지 제10호의9서식(1). legacy 면 2026 과세연도부터의 기존공제(2 · 3차 연도)만 적는다."""
    co, u, src = inp.company, res["used"], res["source"]
    v = _head(co, company)
    for per in ("직전전", "직전", "해당"):
        if per != "해당" and src[per] == "없음":
            continue
        t, y = u[per]
        v[f"6_{per}"], v[f"7_{per}"], v[f"8_{per}"] = n2(t), n2(y), n2(t - y)
    size = _size_key(co)
    if not legacy:
        if res["returned"]:
            v["10_해당"] = num(res["returned"])
        if src["직전"] != "없음":
            (tc, yc), (tp, yp) = u["해당"], u["직전"]
            v.update({"11": n2(tc), "12": n2(tp), "13": n2(tc - tp), "14": n2(yc), "15": n2(yp), "16": n2(yc - yp),
                      "17": n2(tc - yc), "18": n2(tp - yp), "19": n2((tc - yc) - (tp - yp))})
        if res["first"] or res["n_y"] or res["n_o"]:
            grp = "중소" if size.startswith("중소") else size
            v[f"1차_{size}_청년등"], v[f"1차_{size}_청년등_20"] = n2(res["n_y"]), won(res["first_y"])
            v[f"1차_{size}_청년등외"] = n2(res["n_o"])
            if size != "일반":
                v[f"1차_{size}_청년등외_20"] = won(res["first_o"])
            v[f"1차_{grp}_계"], v[f"1차_{grp}_계_20"] = n2(res["n_y"] + res["n_o"]), won(res["first"])
    f1, f2 = (co.first_prev_youth, co.first_prev_other), (co.first_prev2_youth, co.first_prev2_other)
    if any(f1) and co.consumer != "Y" and res["second_cut"] not in ("직전 인원 없음",) and "신규공제" not in res["second_cut"]:
        (tc, yc), (tp, yp) = _judge_vals(res, ("해당", "직전"), res["second_pw"])
        v.update({"21": n2(tc), "22": n2(tp), "23": n2(tc - tp)})
        if tc >= tp:
            if yc < yp:
                v.update({"2차_부여_25": won(f1[1]), "2차_부여_26": won(res["second"])})
            else:
                v.update({"2차_부부_24": won(f1[0]), "2차_부부_25": won(f1[1]), "2차_부부_26": won(res["second"])})
    if any(f2) and co.consumer != "Y" and res["third_cut"] not in ("일반기업", "직전전 인원 없음") and "신규공제" not in res["third_cut"]:
        (tc, yc), (tp, yp), (tpp, ypp) = _judge_vals(res, ("해당", "직전", "직전전"), res["third_pw"])
        v.update({"27": n2(tc), "28": n2(tpp), "29": n2(tc - tpp)})
        if not (tp < tpp or tc < tpp):
            if yp < ypp or yc < ypp:
                v.update({"3차_부여_31": won(f2[1]), "3차_부여_32": won(res["third"])})
            else:
                v.update({"3차_부부_30": won(f2[0]), "3차_부부_31": won(f2[1]), "3차_부부_32": won(res["third"])})
    if not legacy:
        if src["직전"] != "없음":
            tc, tp = u["해당"][0], u["직전"][0]
            v.update({"33": n2(tc), "34": n2(tp), "35": n2(tc - tp)})
        if res["returned"] and co.size in ("중소기업", "중견기업"):
            g = "중소" if co.size == "중소기업" else "중견"
            v.update({f"추가_{g}_인원": num(res["returned"]), f"추가_{g}_36": won(res["extra"]),
                      f"추가_{g}_계_인원": num(res["returned"]), f"추가_{g}_계_36": won(res["extra"])})
        v["total"] = won(res["first"] + res["second"] + res["third"] + res["extra"])
    else:
        v["total"] = won(res["second"] + res["third"])
    return v


def form2(inp: Inputs, res: dict, company: str) -> dict:
    """별지 제10호의9서식(2)(2026 과세연도부터): 신규공제와 추가공제."""
    co, u, src = inp.company, res["used"], res["source"]
    v = _head(co, company)
    for per, col in (("직전전", "전전"), ("직전", "직전"), ("해당", "해당")):
        if per != "해당" and src[per] == "없음":
            continue
        t, y = u[per]
        v[f"6_{col}"], v[f"7_{col}"], v[f"8_{col}"] = n2(t), n2(y), n2(t - y)
    if res["returned"]:
        v["10_해당"] = num(res["returned"])
    size = _size_key(co)
    new = res["new"]
    if new:
        for t in new["terms"]:
            if not t:
                continue
            k = t["term"]
            v[f"y_{k}_{size}"], v[f"y_{k}_{size}_amt"] = n2(t["n_y"]), won(t["amt_y"])
            v[f"o_{k}_{size}"], v[f"o_{k}_{size}_amt"] = n2(t["n_o"]), won(t["amt_o"])
            if t["ded"] or t["min_rule"]:
                m = new["min_hire"]
                if "이상" in t["min_rule"]:
                    v[f"ge_{k}_{size}_min"], v[f"ge_{k}_{size}_amt"] = str(m), won(t["ded"])
                elif "미만" in t["min_rule"]:
                    v[f"lt_{k}_{size}_n"], v[f"lt_{k}_{size}_min"], v[f"lt_{k}_{size}_amt"] = n2(t["n_o"]), str(m), won(t["ded"])
        v[f"y_sum_{size}"], v[f"o_sum_{size}"] = won(new["youth"]), won(new["other"])
        got = [t for t in new["terms"] if t]
        ge = sum(t["ded"] for t in got if "이상" in t["min_rule"])
        lt = sum(t["ded"] for t in got if "미만" in t["min_rule"])
        if ge:
            v[f"ge_sum_{size}"] = won(ge)
        if lt:
            v[f"lt_sum_{size}"] = won(lt)
        v["56"] = won(new["credit"])
    if src["직전"] != "없음":
        tc, tp = u["해당"][0], u["직전"][0]
        v.update({"57": n2(tc), "58": n2(tp), "59": n2(tc - tp)})
    if res["returned"] and co.size in ("중소기업", "중견기업"):
        g = "중소" if co.size == "중소기업" else "중견"
        v.update({f"추가_{g}_인원": num(res["returned"]), f"추가_{g}_60": won(res["extra"]),
                  f"추가_{g}_계_인원": num(res["returned"]), f"추가_{g}_계_60": won(res["extra"])})
    v["total"] = won(res["new_total"] + res["extra"])
    return v


def _rows_of(inp: Inputs, res: dict, rules: dict, per: str) -> list[list[str]]:
    co, period, cnt = inp.company, res["periods"][per], res["counts"][per]
    by_id = {r.person.id: r for r in cnt.rows}
    out = []
    for p in inp.staff:
        if not (p.hired <= period.end and (p.left or FAR) >= period.start):
            continue
        r = by_id.get(p.id)
        if r is None:
            continue
        deem = period.deemed
        m_y, n_y = (r.m_youth_deem, r.n_youth_deem) if deem else (r.m_youth_age, r.n_youth_age)
        lo, hi = age_limits(p, rules)
        worked = sum(r.worked)
        span = ""
        if worked:
            a, b = max(p.hired, period.start), min(p.left or FAR, period.end)
            span = f"{a.month:02d}~{b.month:02d}"
        young = r.regular and period.start < hi and period.end >= lo
        cut = (youth_cutoff(p, co.size, rules, True) if deem else hi) if r.regular else None
        out.append([
            ymd(p.birth), p.name, yn(r.regular), (r.reason[:1] if r.reason else ""), (num(r.weight) if r.weight < 1 else ""),
            yn(p.resident), yn(p.capital or co.capital), ymd(p.hired), span, num(r.m_work), n2(r.n_work), num(m_y), n2(n_y),
            yn(young), yn(deem and deemed_until(p, co.size, rules) is not None), ymd(cut),
            yn(p.disabled), yn(is_senior(p, rules)), yn(p.career), yn(p.defector), yn(p.converted), yn(p.returned),
        ])
    return out


def roster(inp: Inputs, res: dict, rules: dict, company: str) -> tuple[dict, dict]:
    """별지 제10호의10서식. (칸 값, 사람별 줄)."""
    v = _head(inp.company, company)
    rows = {}
    for per in ("해당", "직전"):
        period, cnt = res["periods"][per], res["counts"][per]
        if per == "직전" and not period.has_payroll:
            continue
        kinds = {k: Fraction(0) for k in KIND_CODE}
        for r in cnt.rows:
            n = r.n_youth_deem if period.deemed else r.n_youth_age
            if r.regular and r.kind in kinds:
                kinds[r.kind] += n
        total, youth = cnt.total, sum(kinds.values(), Fraction(0))
        v[f"{per}_1"], v[f"{per}_2"] = str(period.months), n2(total)
        for k, code in KIND_CODE.items():
            v[f"{per}_{code}"] = n2(kinds[k])
        v[f"{per}_9"], v[f"{per}_10"] = n2(youth), n2(total - youth)
        rows[per] = _rows_of(inp, res, rules, per)
    return v, rows


# ---------------------------------------------------------------- 쓰기

_FONT = None


def _font():
    global _FONT
    if _FONT is None:
        _FONT = fitz.Font(FONT)
    return _FONT


def put(page, box, text: str, align: str = "r", size: float = SIZE, pad: float = 1.6, min_sx: float = 0.55) -> None:
    """칸(box) 안에 글자를 넣는다. 넘치면 가로로 0.55 배까지 줄이고, 그래도 넘치면 글자 크기를 줄인다.
    폭을 잰 글꼴로 그대로 그린다(TextWriter). insert_text 의 내장 CJK 이름 글꼴은 숫자를 전각 폭으로 그려 칸을 넘친다."""
    if text in (None, ""):
        return
    font = _font()
    x0, y0, x1, y1 = box
    room = max(1.0, (x1 - x0) - 2 * pad)
    size = min(size, (y1 - y0) * 0.8)
    w = font.text_length(text, fontsize=size)
    sx = 1.0
    if w > room:
        sx = max(min_sx, room / w)
        if w * sx > room:
            size = size * room / (w * sx)
            w = font.text_length(text, fontsize=size)
    width = w * sx
    if align == "l":
        x = x0 + pad
    elif align == "c":
        x = (x0 + x1 - width) / 2
    else:
        x = x1 - pad - width
    y = (y0 + y1) / 2 + size * 0.36
    pt = fitz.Point(x, y)
    tw = fitz.TextWriter(page.rect)
    tw.append(pt, text, font=font, fontsize=size)
    tw.write_text(page, color=(0, 0, 0), morph=(pt, fitz.Matrix(sx, 1)) if sx < 1 else None)


def _fill(page, fields: dict, values: dict, page_no: int) -> int:
    n = 0
    for key, val in values.items():
        f = fields.get(key)
        if f is None or f["page"] != page_no:
            continue
        if key.startswith("fy_"):
            # 과세연도 칸은 「년 월 일」 또는 「. . .」 사이 빈자리에 넣는다. 명세서 둘째 연도 자리(「~」 와 「.」 사이)는 9pt 라 좁다
            put(page, f["box"], val, "r" if key.startswith("fy_y") else "c", 8.0, 0.3, 0.42)
        else:
            put(page, f["box"], val, f["align"])
        n += 1
    return n


def write(path: Path, inp: Inputs, res: dict, rules: dict, company: str, stamp: str = "") -> dict:
    """법정서식 PDF 를 쓴다. 쓴 서식과 쪽 수, 넣은 칸 수를 돌려준다. 공제액을 계산하지 않은 과세연도면 쓰지 않는다."""
    if res["unsupported"]:
        return {"written": False, "why": res["unsupported"]}
    c = coords()
    src = {k: fitz.open(FORMS / p["file"]) for k, p in c["pdfs"].items()}
    out = fitz.open()
    plan = []
    co = inp.company
    legacy_need = any((co.first_prev_youth, co.first_prev_other, co.first_prev2_youth, co.first_prev2_other))
    if res["regime"] == "2026":
        plan.append(("form2", form2(inp, res, company)))
        if legacy_need:
            plan.append(("form1", form1(inp, res, company, legacy=True)))
    else:
        plan.append(("form1", form1(inp, res, company, legacy=False)))
    filled, made = 0, []
    for form, values in plan:
        spec = c["forms"][form]
        for i, pno in enumerate(spec["pages"], start=1):
            out.insert_pdf(src[spec["pdf"]], from_page=pno - 1, to_page=pno - 1)
            filled += _fill(out[-1], c["fields"][form], values, i)
        made.append(form)
    head, rows = roster(inp, res, rules, company)
    spec = c["forms"]["roster"]
    for per in ("해당", "직전"):
        if per not in rows:
            rows[per] = []          # 직전 급여대장이 없어도 2쪽(제출 문구)은 넣는다. 직전 명세는 전기 신고서의 것을 쓴다
        grid = c["rows"][per]
        page_no = grid["page"]
        people = rows[per] or [[]]
        per_page = len(grid["cells"])
        for start in range(0, len(people), per_page):
            pno = spec["pages"][page_no - 1]
            out.insert_pdf(src[spec["pdf"]], from_page=pno - 1, to_page=pno - 1)
            page = out[-1]
            if page_no == 1:
                # 1쪽 머리(과세연도 · 상호)는 장마다, 1. 상시근로자 수 계산은 첫 장에만
                vals = {k: v for k, v in head.items() if start == 0 or k.startswith(("fy_", "company"))}
                filled += _fill(page, c["fields"]["roster"], vals, 1)
            for line, cells in zip(people[start:start + per_page], grid["cells"]):
                for text, box in zip(line, cells):
                    put(page, box, text, "c", ROW_SIZE)
                    filled += 1 if text else 0
        made.append(f"roster_{per}")
    if stamp:                                                  # 잠정치는 쪽마다 맨 위에 표시한다
        for page in out:
            put(page, (20, 3, page.rect.width - 20, 17), stamp, "c", 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.subset_fonts()
    out.save(path, garbage=3, deflate=True)
    return {"written": True, "forms": made, "pages": out.page_count, "cells": filled, "path": str(path)}
