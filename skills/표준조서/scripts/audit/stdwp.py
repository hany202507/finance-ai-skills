"""계정별 표준조서(2026-11-24). 설계 문서

전기조서가 없거나 회계사가 만든 신규 양식으로 바꾸고 싶을 때 쓰는 4000 계정별 조서다. 엔진 4000 조서(wp make)와 따로 있고
`4000 계정별/표준조서/<조서번호>_<이름>_표준.xlsx` 에 둔다. 양식은 예시 조서 가 · 나 · 다 · 라 공통(표지 · Lead · 절차 시트 · 주석),
정의는 definitions/std_workpapers.yaml 이다.

정산표 잇기: 조서마다 「정산표」 시트를 두고 엔진이 그 시트의 값만 새로 씌운다(파일 사이 외부 연결 없음). Lead 는 같은 파일 안
수식으로 키(BS-1, PL-3)를 찾아 읽는다. 키는 계정마다 한 번 정하면 바뀌지 않으므로 계정이 늘거나 줄어도 회계사가 적은
증감 사유가 다른 계정 옆으로 밀리지 않는다. 사라진 계정은 금액 0 · 비고 「정산표에 없음」 으로 남는다.

  load_defs() · areas()                정의
  read_tb(path)                        8100B 정산표(계정별 · 수정 제안 반영 여부 「예」)
  make(d, codes, wtb, force)           표준조서를 만든다. 있으면 건너뛴다(force 면 다시 그리고 기입란 · AI 칸 글을 옮긴다)
  refresh(d, codes, wtb)               정산표 시트만 다시 씌운다. 예비 줄이 모자라면 그 조서는 멈추고 알린다
  fill(d, code, patch)                 에이전트 글(메모 · 증감 사유 · 표지 해당 여부 제안)을 AI 칸으로 넣는다. 금액 꼴 글은 거부
  check(d)                             정산표 판 · 대사 차이 · 확인 전 AI 칸 · 빈 해당 여부
  roll(prev, d)                        작년 표준조서를 올해 폴더로 옮겨 머리 · 서명 · 그해 글을 비우고 올해 정산표를 씌운다

엔진은 Lead · 주석 숫자를 정산표에서 가져온다. 절차 시트 표는 정의에 feed 가 있으면 엔진 4000 조서와 같은 함수가 받은자료에서
읽은 값을 채운다(2026-11-25 결정 D1, audit/stdfeed.py, 설계 문서 7절).
AI 글에는 금액을 쓰지 못한다(audit.workpapers.suggest.amount_in_text). 엑셀에서 열린 파일은 쓰지 않고 건너뛴다(busy).
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, PatternFill, Side
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import stdfeed, stdmode, style
from .errors import IntakeError

ROOT = Path(__file__).resolve().parents[1]
DEFS = ROOT / "definitions" / "std_workpapers.yaml"
PROC1 = ROOT / "tools" / "proto_data" / "kicpa_4000_part1.json"
PROC2 = ROOT / "tools" / "proto_data" / "kicpa_4000_part2.json"
PROC_PUBLIC = ROOT / "definitions" / "std_procedures_public.json"   # 공개판 표지 절차 목록(한공회 원문 없음, 2026-11-26)
SUB = Path("4000 계정별") / "표준조서"
TB = "정산표"
META = "_표준"
AI = "AI 작성"
COVER = "표지"
LEAD = "Lead"
NUM = '#,##0;[Red]\\(#,##0\\);\\-'          # 예시 조서 그대로 괄호 음수
PCT = '0.0%;[Red]\\(0.0%\\);\\-'
BS_KINDS = ("자산", "부채", "자본")
SIGN = {"자산": 1, "비용": 1, "부채": -1, "자본": -1, "수익": -1}
STEP_NO = re.compile(r"^\s*(\d+)\s*[.)]")
# 정산표 시트 열(1부터)
T_KEY, T_BLOCK, T_CODE, T_NAME, T_LINE, T_AREA, T_KIND, T_SIGN, T_PRIOR, T_CUR, T_DR, T_CR, T_FINAL, T_SHOW, T_SHOWP, T_NOTE = range(1, 17)
F_KEY, F_LINE, F_SHOW, F_SHOWP = 18, 19, 20, 21          # 표시과목 목록(주석 시트가 읽는다)
TB_HEAD = ["키", "블록", "코드", "계정명", "표시과목", "영역", "구분", "부호", "전기", "당기(회사제시)", "수정 차변", "수정 대변",
           "당기(최종)", "표시 금액(최종)", "표시 금액(전기)", "비고"]
TB_ROW0 = 7                                              # 정산표 시트 머리줄
# Lead 열
L_ACC, L_PRE, L_TM1, L_DR, L_CR, L_FIN, L_TM2, L_PRIOR, L_DIFF, L_PCT, L_WHY, L_KEY, L_SIGN = 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15


class Problem(IntakeError):
    """명령을 받아들이지 않았다. 아무것도 쓰지 않았다."""


# ---------------------------------------------------------------- 정의
def load_defs() -> dict:
    return yaml.safe_load(DEFS.read_text(encoding="utf-8"))


def areas() -> dict:
    return load_defs()["areas"]


def _kicpa(part: int) -> dict:
    """한공회 4000 Part 1 · Part 2 절차. 공개판(stdmode.STANDALONE)과 원문 파일이 없는 곳은 원문 없는 목록을 쓴다
    (번호 · 경영진 주장 · 잇는 시트, 4000C 만 요약 문장, 2026-11-26 설계 4절)."""
    p = PROC1 if part == 1 else PROC2
    if not stdmode.STANDALONE and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    if PROC_PUBLIC.exists():
        return json.loads(PROC_PUBLIC.read_text(encoding="utf-8")).get(str(part)) or {}
    return {}


def file_for(d: Path, code: str) -> Path:
    return Path(d) / SUB / f"{code}_{areas()[code]['name']}_표준.xlsx"


def _asrt_names(codes: list[str]) -> str:
    names = dict(load_defs()["assertions"])
    return " · ".join(f"{c} {names.get(c, '')}".strip() for c in codes)


# ---------------------------------------------------------------- 정산표 읽기
def source(d: Path, wtb: str | None = None) -> Path:
    if wtb:
        p = Path(wtb)
        if not p.exists():
            raise Problem(f"정산표 파일이 없습니다: {p}")
        return p
    from . import wp
    try:
        p = wp.path_for(d, "8100B")
        if p.exists():
            return p
    except Exception:
        pass
    cands = sorted((Path(d) / "8000 감사완결").glob("8100B_*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True)
    cands = [c for c in cands if not c.name.startswith("~$")]
    if not cands:
        raise Problem("8100B 정산표가 없습니다. 먼저 "
                      + ("`python scripts/run.py make <자료 폴더>` 로 정산표와 표준조서를 만드십시오" if stdmode.STANDALONE
                         else "`python -m audit wtb` 로 정산표를 만들거나 --wtb 로 파일을 주십시오"))
    return cands[0]


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _months(s: date, e: date) -> int:
    return (e.year - s.year) * 12 + e.month - s.month + 1


def _span(s: date, e: date) -> str:
    """손익 기간 머리: 「2026.01~09」, 해를 넘으면 「2025.04~2026.03」."""
    return f"{s:%Y.%m}~{e:%m}" if s.year == e.year else f"{s:%Y.%m}~{e:%Y.%m}"


def period(d: Path | None, tb: dict) -> dict:
    """당기 · 전기 기간(2026-11-25). 결산일을 1년 빼서 전기를 만들지 않는다.
    당기말은 정산표 결산일(중간감사면 기준일), 당기 시작은 감사건.json 사업연도 시작(folder.fiscal_start, 반기 · 짧은 사업연도 R8).
    재무상태표 전기는 전기말(당기 시작 전날), 손익 전기는 전기 사업연도(전기말까지 12개월).
    중간감사 · 반기 · 짧은 사업연도처럼 손익 당기와 전기의 개월 수가 다르면 손익 증감을 내지 않는다."""
    from . import folder
    case: dict = {}
    if d is not None:
        f = Path(d) / "_색인" / "감사건.json"
        if f.exists():
            try:
                case = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                case = {}
    try:
        end = date.fromisoformat(str(tb.get("ye") or case.get("fiscal_year_end") or "")[:10])
    except ValueError:
        return {"ok": False, "bs_cur": tb.get("ye") or "당기", "bs_prior": "전기", "pl_cur": tb.get("ye") or "당기",
                "pl_prior": "전기", "comparable": True, "kind": "", "head": str(tb.get("ye") or "")}
    c = dict(case)
    c["fiscal_year_end"] = str(c.get("fiscal_year_end") or end.isoformat())[:10]
    start = folder.fiscal_start(c)
    if start > end:                                    # 감사건 사업연도가 정산표와 다른 해(옛 감사건)면 결산일 기준 12개월
        start = folder.fiscal_start({"fiscal_year_end": end.isoformat()})
    pe = start - timedelta(days=1)
    ps = folder.fiscal_start({"fiscal_year_end": pe.isoformat()})
    name = Path(d).name if d is not None else ""
    mc, mp = _months(start, end), _months(ps, pe)
    kind = "중간감사" if "중간" in name else "반기검토" if "반기" in name else ("짧은 사업연도" if mc < 12 else "")
    head = end.isoformat() if not kind else f"{end.isoformat()}({kind}, {start.isoformat()} ~ {end.isoformat()})"
    return {"ok": True, "start": start.isoformat(), "end": end.isoformat(), "prior_start": ps.isoformat(), "prior_end": pe.isoformat(),
            "bs_cur": end.isoformat(), "bs_prior": pe.isoformat(), "pl_cur": _span(start, end), "pl_prior": _span(ps, pe),
            "months": mc, "prior_months": mp, "comparable": mc == mp, "kind": kind, "head": head}


def _per(tb: dict) -> dict:
    return tb.get("period") or period(None, tb)


def read_tb(path: Path) -> dict:
    """8100B 「계정별」 시트와 「수정 제안」 반영 여부 「예」 줄. 금액은 시산표 부호(차변 +)."""
    wb = load_workbook(path, data_only=False)
    try:
        if "계정별" not in wb.sheetnames:
            raise Problem(f"「계정별」 시트가 없습니다: {path.name}")
        ws = wb["계정별"]
        company = ye = None
        hi = None
        for r in range(1, 25):
            for c in range(1, 8):
                v = ws.cell(r, c).value
                if v == "회사명" and company is None:
                    company = ws.cell(r, c + 1).value
                elif v == "결산일" and ye is None:
                    ye = ws.cell(r, c + 1).value
            if ws.cell(r, 1).value == "코드":
                hi = r
                break
        if hi is None:
            raise Problem(f"「계정별」 시트에서 「코드」 머리줄을 찾지 못했습니다: {path.name}")
        head = {str(ws.cell(hi, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}

        def col(*names):
            for n in names:
                for h, c in head.items():
                    if h.startswith(n):
                        return c
            return None

        c_name, c_line, c_area, c_kind = col("계정명"), col("비교 줄", "표시과목"), col("영역"), col("구분")
        c_prior, c_cur = col("전기"), col("당기(회사"),
        adj_dr: dict[str, float] = {}
        adj_cr: dict[str, float] = {}
        if "수정 제안" in wb.sheetnames:
            sj = wb["수정 제안"]
            for r in range(1, sj.max_row + 1):
                code, dr, cr, ok = sj.cell(r, 2).value, sj.cell(r, 5).value, sj.cell(r, 6).value, sj.cell(r, 7).value
                if code not in (None, "") and str(ok or "").strip() == "예":
                    adj_dr[str(code)] = adj_dr.get(str(code), 0) + _num(dr)
                    adj_cr[str(code)] = adj_cr.get(str(code), 0) + _num(cr)
        rows = []
        for r in range(hi + 1, ws.max_row + 1):
            code = ws.cell(r, 1).value
            if code in (None, "") or not re.fullmatch(r"[0-9A-Za-z_.-]+", str(code)):
                continue
            code = str(code)
            cur = ws.cell(r, c_cur).value if c_cur else None
            prior = ws.cell(r, c_prior).value if c_prior else None
            if not isinstance(cur, (int, float)) and not isinstance(prior, (int, float)):
                continue
            kind = str(ws.cell(r, c_kind).value or "").strip() if c_kind else ""
            rows.append({"code": code, "name": str(ws.cell(r, c_name).value or "").strip(),
                         "line": str(ws.cell(r, c_line).value or "").strip() if c_line else "",
                         "area": str(ws.cell(r, c_area).value or "").strip() if c_area else "",
                         "kind": kind, "sign": SIGN.get(kind, 1), "block": "BS" if kind in BS_KINDS else "PL",
                         "prior": _num(prior) if isinstance(prior, (int, float)) and not isinstance(prior, bool) else None,
                         "cur": _num(cur), "dr": adj_dr.get(code, 0.0), "cr": adj_cr.get(code, 0.0)})
        if isinstance(ye, datetime):
            ye = ye.strftime("%Y-%m-%d")
        return {"file": path.name, "company": str(company or ""), "ye": str(ye or "")[:10], "rows": rows,
                "fs_prior": _fs_prior(wb), "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
    finally:
        wb.close()


def _fs_prior(wb) -> dict[str, float]:
    """8100B 「재무제표」 시트의 과목별 전기(전기 재무제표, 부채 · 자본 · 수익은 양수). 계정별 전기가 없는 손익 표시과목에 쓴다."""
    if "재무제표" not in wb.sheetnames:
        return {}
    ws = wb["재무제표"]
    hi = c_prior = None
    for r in range(1, 25):
        if str(ws.cell(r, 1).value or "").strip() == "과목":
            hi = r
            for c in range(2, ws.max_column + 1):
                if str(ws.cell(r, c).value or "").strip().startswith("전기"):
                    c_prior = c
                    break
            break
    if not hi or not c_prior:
        return {}
    out = {}
    for r in range(hi + 1, ws.max_row + 1):
        name, v = ws.cell(r, 1).value, ws.cell(r, c_prior).value
        if isinstance(name, str) and name.strip() and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault(name.strip(), float(v))
    return out


def _zero(r: dict) -> bool:
    """전기 · 당기 · 수정이 모두 없는 계정. 새로 실을 때 건너뛴다(앞서 키를 받은 계정은 그대로 둔다)."""
    return not r["cur"] and not r.get("prior") and not r["dr"] and not r["cr"]


def _line_owner() -> dict[str, str]:
    """표시과목 → 조서 영역 글자(정의 lines, 4000S 처럼 8100B 영역과 상관없이 표시과목으로 가져가는 조서)."""
    out = {}
    for a in areas().values():
        for l in a.get("lines") or []:
            out.setdefault(l, a["letter"])
    return out


def eff_area(r: dict, owner: dict[str, str] | None = None) -> str:
    """이 계정을 자기 계정으로 싣는 조서의 영역 글자. 손익 계정이고 표시과목이 정의 lines 에 있으면 그 영역, 아니면 8100B 영역."""
    owner = _line_owner() if owner is None else owner
    if r.get("block") == "PL" and r.get("line") in owner:
        return owner[r["line"]]
    return r["area"]


def pick(tb: dict, code: str) -> list[dict]:
    """이 조서에 실을 계정: 영역이 같은 계정(표시과목으로 가져가는 4000S 는 빼고 더함), 그리고 영역이 달라도 손익 낱말이 맞는 손익 계정."""
    a = areas()[code]
    owner = _line_owner()
    own = [r for r in tb["rows"] if eff_area(r, owner) == a["letter"]]
    seen = {r["code"] for r in own}
    words = a.get("pl_words") or []
    more = [dict(r, borrowed=True) for r in tb["rows"]
            if r["code"] not in seen and r["block"] == "PL" and any(w in r["name"] for w in words)]
    return own + more


def default_codes(tb: dict) -> list[str]:
    owner = _line_owner()
    letters = {eff_area(r, owner) for r in tb["rows"] if not _zero(r)}
    out = [c for c, a in areas().items() if a["letter"] in letters or c == "4000CL"]
    return out


def unassigned(tb: dict) -> list[dict]:
    letters = {a["letter"] for a in areas().values()}
    owner = _line_owner()
    return [r for r in tb["rows"] if eff_area(r, owner) not in letters and not _zero(r)]


# ---------------------------------------------------------------- 블록 부호
def block_signs(rows: list[dict], old: dict | None = None) -> dict[str, int | None]:
    """Lead 블록마다 보일 부호 하나. 블록 안 자기 계정 가운데 금액이 가장 큰 계정의 구분 부호(자산 · 비용 +1, 부채 · 자본 · 수익 −1).
    수익과 비용(또는 자산과 부채)이 한 블록에 섞여도 합계가 순액이 되게 한다(4000S 기타손익, 4000T 선납세금 · 미지급법인세 등).
    한 번 정한 부호는 앞 조서의 것을 잇는다. 계정이 없는 블록은 None(처음 계정이 생길 때 정한다)."""
    out: dict[str, int | None] = {}
    for b in ("BS", "PL"):
        if old and old.get(b) in (1, -1):
            out[b] = old[b]
            continue
        cand = [x for x in rows if x.get("key", "").startswith(b + "-") and not x.get("borrowed") and not x.get("gone")]
        cand = cand or [x for x in rows if x.get("key", "").startswith(b + "-") and not x.get("gone")]
        if not cand:
            out[b] = None
            continue
        top = max(cand, key=lambda x: (abs(x["cur"]) or abs(x.get("prior") or 0)))
        out[b] = SIGN.get(top.get("kind"), 1)
    return out


def _apply_signs(rows: list[dict], signs: dict) -> list[dict]:
    for x in rows:
        b = x["key"].split("-")[0]
        x["dsign"] = signs.get(b) if signs.get(b) in (1, -1) else x.get("sign", 1)
    return rows


def _sign_note(block: str, sign: int | None) -> str:
    if sign not in (1, -1):
        return ""
    if block == "BS":
        return "(자산 양수)" if sign == 1 else "(부채 · 자본 양수)"
    return "(비용 양수, 수익은 괄호)" if sign == 1 else "(수익 양수, 비용은 괄호)"


# ---------------------------------------------------------------- 키
def assign_keys(rows: list[dict], old: dict[str, dict]) -> list[dict]:
    """계정마다 키. 앞 정산표 시트의 키를 잇고, 새 계정은 블록마다 다음 번호. 사라진 계정은 0 · 「정산표에 없음」 으로 남긴다.
    old = {코드: {key, block, name, line, kind, sign}}"""
    out: list[dict] = []
    used = {"BS": 0, "PL": 0}
    for o in old.values():
        b, n = o["key"].split("-")
        used[b] = max(used[b], int(n))
    now = {r["code"]: r for r in rows}
    for code, o in sorted(old.items(), key=lambda kv: (kv[1]["key"].split("-")[0], int(kv[1]["key"].split("-")[1]))):
        if code in now:
            r = dict(now[code], key=o["key"], block=o["key"].split("-")[0])
            r["note"] = "블록이 바뀐 계정(구분 확인)" if r["block"] != ("BS" if r["kind"] in BS_KINDS else "PL") else ""
            out.append(r)
        else:
            out.append({**o, "code": code, "prior": 0.0, "cur": 0.0, "dr": 0.0, "cr": 0.0, "note": "정산표에 없음", "gone": True})
    for r in rows:
        if r["code"] in old or _zero(r):
            continue
        used[r["block"]] += 1
        out.append(dict(r, key=f"{r['block']}-{used[r['block']]}", note=""))
    return out


def _fs_keys(rows: list[dict], old: dict[str, str]) -> list[tuple[str, str]]:
    """표시과목 키(FS-n). 자기 영역 계정의 표시과목만."""
    lines = []
    for r in rows:
        if r.get("borrowed") or r.get("gone") or not r.get("line"):
            continue
        if r["line"] not in lines:
            lines.append(r["line"])
    n = max([int(k.split("-")[1]) for k in old.values()] or [0])
    out = [(old[l], l) for l in sorted(old, key=lambda x: int(old[x].split("-")[1]))]
    for l in lines:
        if l not in old:
            n += 1
            out.append((f"FS-{n}", l))
    return out


# ---------------------------------------------------------------- 서식 도움
F = style.font
THIN = Side(style="thin", color=style.BORDER)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TOP = Border(top=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _put(ws, r, c, v, bold=False, size=None, color=None, fill=None, fmt=None, align=None, border=None):
    cell = ws.cell(r, c, v)
    k = {"bold": True} if bold else {}
    if size:
        k["size"] = size
    if color:
        k["color"] = color
    cell.font = F(**k)
    if fill is not None:
        cell.fill = fill
    if fmt:
        cell.number_format = fmt
    if align is not None:
        cell.alignment = align
    if border is not None:
        cell.border = border
    return cell


def _input(ws, r, c, v=None, merge_to: int | None = None, height: float | None = None):
    cell = _put(ws, r, c, v, fill=style.FILL_IN, align=WRAP, border=BOX)
    if merge_to and merge_to > c:
        ws.merge_cells(start_row=r, start_column=c, end_row=r, end_column=merge_to)
    if height:
        ws.row_dimensions[r].height = height
    return cell


def _sheet_base(ws, widths: dict[str, float]):
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 85
    for k, w in widths.items():
        ws.column_dimensions[k].width = w
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0


def _head(ws, tb: dict, title: str, index: str, box_col: int, sign_box: bool = True):
    """예시 조서 공통 머리: A1 회사 · A2 「A: 결산일」 · A3 제목, 오른쪽 위 Index · Date · Prepared · Reviewed."""
    _put(ws, 1, 1, tb["company"], bold=True)
    _put(ws, 2, 1, f"A: {_per(tb)['head']}", bold=True)
    _put(ws, 3, 1, title, bold=True, size=11)
    _put(ws, 1, box_col, "Index", color=style.MUTED)
    _put(ws, 1, box_col + 1, index, bold=True, align=CENTER, border=BOX)
    if sign_box:
        for i, lab in enumerate(("Date", "Prepared", "Reviewed"), 2):
            _put(ws, i, box_col, lab, color=style.MUTED)
            _input(ws, i, box_col + 1)


def _ref(sheet: str, cell: str) -> str:
    return f"'{sheet}'!{cell}"


def _label(letter: str, sheet: str) -> str:
    """링크 칸에 보일 짧은 번호: Lead 는 그대로, 「.02 취득 · 처분 증빙」 은 「G.02」."""
    m = re.match(r"^\.(\d+)\s", sheet or "")
    return f"{letter}.{m.group(1)}" if m else (sheet or "")


def _tbr(col: int) -> str:
    L = get_column_letter(col)
    return f"'{TB}'!${L}:${L}"


# ---------------------------------------------------------------- 정산표 시트
def _write_tb(wb, tb: dict, rows: list[dict], fs: list[tuple[str, str]], code: str):
    if TB in wb.sheetnames:
        ws = wb[TB]
        ws.delete_rows(1, ws.max_row + 5)
        for m in list(ws.merged_cells.ranges):
            ws.unmerge_cells(str(m))
    else:
        ws = wb.create_sheet(TB)
    _sheet_base(ws, {"A": 8, "B": 6, "C": 9, "D": 26, "E": 20, "F": 6, "G": 6, "H": 5, "I": 15, "J": 15, "K": 13, "L": 13,
                     "M": 15, "N": 15, "O": 15, "P": 18, "R": 7, "S": 22, "T": 15, "U": 15})
    a = areas()[code]
    _put(ws, 1, 1, tb["company"], bold=True)
    _put(ws, 2, 1, f"A: {_per(tb)['head']}", bold=True)
    _put(ws, 3, 1, f"정산표({code} {a['name']})", bold=True, size=11)
    _put(ws, 4, 1, f"원천: {tb['file']}(저장 {tb['mtime']}) · 씌운 시각: {datetime.now():%Y-%m-%d %H:%M}", color=style.MUTED)
    _put(ws, 5, 1, f"엔진이 `{stdmode.cmd('refresh', True)}` 로 통째로 다시 씌우는 시트입니다. 고칠 숫자는 8100B 정산표에서 고칩니다. "
                   "Lead · 주석 시트가 이 시트를 키로 읽습니다.", color=style.MUTED)
    for i, h in enumerate(TB_HEAD, 1):
        _put(ws, TB_ROW0, i, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
    for i, h in enumerate(("키", "표시과목", "표시 금액(최종)", "표시 금액(전기)"), F_KEY):
        _put(ws, TB_ROW0, i, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
    r = TB_ROW0
    names: dict[str, int] = {}
    for x in rows:
        names[x["name"]] = names.get(x["name"], 0) + 1
    for x in rows:
        r += 1
        fin = x["cur"] + x["dr"] - x["cr"]
        pr = x.get("prior")
        name = f"{x['name']}({x['code']})" if names.get(x["name"], 0) > 1 and not x["name"].endswith(f"({x['code']})") else x["name"]
        ds = x.get("dsign", x.get("sign", 1))
        vals = [x["key"], x["key"].split("-")[0], x["code"], name, x.get("line", ""), x.get("area", ""), x.get("kind", ""),
                ds, pr, x["cur"], x["dr"], x["cr"], fin, fin * ds, None if pr is None else pr * ds,
                x.get("note") or ("다른 영역 손익 계정" if x.get("borrowed") else "")]
        for c, v in enumerate(vals, 1):
            _put(ws, r, c, v, fmt=NUM if c >= T_PRIOR and c <= T_SHOWP else None, border=BOX,
                 color=style.RED if c == T_NOTE and v else None)
    rr = TB_ROW0
    for k, line in fs:
        rr += 1
        own = [x for x in rows if x.get("line") == line and not x.get("borrowed")]
        show = sum((x["cur"] + x["dr"] - x["cr"]) * x.get("sign", 1) for x in own)
        known = [x for x in own if x.get("prior") is not None]
        if known:
            showp = sum(x["prior"] * x.get("sign", 1) for x in known)
        else:
            # 계정별 전기가 없으면(전기 손익 등) 8100B 재무제표 시트의 표시과목 전기. 그 표시과목 계정이 모두 이 조서에 있을 때만
            mine = {x["code"] for x in own}
            whole = all(y["code"] in mine for y in tb["rows"] if y.get("line") == line and not _zero(y))
            showp = (tb.get("fs_prior") or {}).get(line) if whole else None
        for c, v in ((F_KEY, k), (F_LINE, line), (F_SHOW, show), (F_SHOWP, showp)):
            _put(ws, rr, c, v, fmt=NUM if c >= F_SHOW else None, border=BOX)
    ws.freeze_panes = ws.cell(TB_ROW0 + 1, 1)
    return ws


def _old_keys(wb) -> tuple[dict, dict]:
    """앞 정산표 시트의 키. ({코드: 줄 정보}, {표시과목: FS 키})"""
    acc, fs = {}, {}
    if TB not in wb.sheetnames:
        return acc, fs
    ws = wb[TB]
    for r in range(TB_ROW0 + 1, ws.max_row + 1):
        k, code = ws.cell(r, T_KEY).value, ws.cell(r, T_CODE).value
        if k and code and re.fullmatch(r"(BS|PL)-\d+", str(k)):
            acc[str(code)] = {"key": str(k), "block": str(k).split("-")[0], "name": ws.cell(r, T_NAME).value or "",
                              "line": ws.cell(r, T_LINE).value or "", "area": ws.cell(r, T_AREA).value or "",
                              "kind": ws.cell(r, T_KIND).value or "", "sign": ws.cell(r, T_SIGN).value or 1}
        fk, line = ws.cell(r, F_KEY).value, ws.cell(r, F_LINE).value
        if fk and line and re.fullmatch(r"FS-\d+", str(fk)):
            fs[str(line)] = str(fk)
    return acc, fs


# ---------------------------------------------------------------- 메타
META_CHUNK = 30000          # 엑셀 칸 하나에 글자 32,767자까지. 메타가 길면 A1 · A2 … 로 나눠 쓴다(엔진 채움 값이 들어간 뒤)


def _meta(wb) -> dict:
    if META not in wb.sheetnames:
        return {}
    ws = wb[META]
    parts, r = [], 1
    while ws.cell(r, 1).value not in (None, ""):
        parts.append(str(ws.cell(r, 1).value))
        r += 1
    try:
        return json.loads("".join(parts)) if parts else {}
    except ValueError:
        return {}


def _set_meta(wb, m: dict):
    ws = wb[META] if META in wb.sheetnames else wb.create_sheet(META)
    s = json.dumps(m, ensure_ascii=False)
    chunks = [s[i:i + META_CHUNK] for i in range(0, len(s), META_CHUNK)] or [""]
    old = ws.max_row
    for i, c in enumerate(chunks, 1):
        ws.cell(i, 1, c)
    for r in range(len(chunks) + 1, old + 1):
        ws.cell(r, 1).value = None
    ws.sheet_state = "hidden"


def busy(path: Path) -> bool:
    """엑셀에서 열려 있는지(설계 7.4). 같은 폴더에 잠금 파일(~$이름)이 있거나 쓰기로 열 수 없으면 열린 것으로 본다."""
    p = Path(path)
    if not p.exists():
        return False
    if any((p.parent / f"~${n}").exists() for n in (p.name, p.name[2:])):
        return True
    try:
        with open(p, "r+b"):
            pass
    except PermissionError:
        return True
    except OSError:
        return False
    return False


BUSY = "엑셀에서 열려 있어 건너뜀. 파일을 닫고 다시 돌리십시오"


def _calc_ref(d: Path | None, code: str) -> str | None:
    """같은 영역 엔진 4000 조서(계산 근거)의 감사 폴더 상대 경로. 조서목록에 파일이 없으면 None."""
    if d is None:
        return None
    p = Path(d) / "_색인" / "조서목록.json"
    try:
        wps = json.loads(p.read_text(encoding="utf-8")).get("workpapers", []) if p.is_file() else []
    except ValueError:
        return None
    f = next((w.get("file") for w in wps if w.get("no") == code and w.get("file")), None)
    return f if f and (Path(d) / f).exists() and "/표준조서/" not in f else None


# ---------------------------------------------------------------- 표지
def _cover(wb, tb: dict, code: str, sheet_refs: dict[int, str], notes_ref: str, slots: dict, calc_ref: str | None = None):
    a = areas()[code]
    ws = wb.create_sheet(COVER)
    _sheet_base(ws, {"A": 2, "B": 7, "C": 62, "D": 13, "E": 11, "F": 11, "G": 10, "H": 34})
    ws.merge_cells("B1:H1")
    _put(ws, 1, 2, "실 증 절 차", bold=True, size=14, align=Alignment(horizontal="center"))
    ws.row_dimensions[1].height = 28
    _put(ws, 3, 2, "회사명", color=style.MUTED)
    _put(ws, 3, 3, tb["company"], bold=True)
    _put(ws, 4, 2, "기준일" if _per(tb)["kind"] == "중간감사" else "결산일", color=style.MUTED)
    _put(ws, 4, 3, _per(tb)["head"])
    _put(ws, 5, 2, "조서", color=style.MUTED)
    _put(ws, 5, 3, f"{code} {a['name']}", bold=True)
    for i, lab in enumerate(("작성자", "검토자"), 3):
        _put(ws, i, 6, lab, color=style.MUTED)
        _input(ws, i, 7, merge_to=8)
    _put(ws, 6, 2, _calc_note(calc_ref), color=style.MUTED)
    _put(ws, 7, 2, "경영진 주장: " + " · ".join(f"{c} {n}" for c, n in load_defs()["assertions"]), color=style.MUTED)
    _put(ws, 8, 2, "해당 여부와 수행자는 회계사가 적습니다. 「AI 제안(확인 전)」 은 에이전트가 "
         f"`{stdmode.cmd('fill')}` 로 넣은 제안이며 기입란이 아닙니다.",
         color=style.MUTED)
    dv = DataValidation(type="list", formula1='"해당,해당없음"', allow_blank=True)
    ws.add_data_validation(dv)
    r = 9
    for part, title in ((1, "Part 1 기본 절차"), (2, "Part 2 추가 고려 절차")):
        items = (_kicpa(part).get(a["kicpa"]) or {}).get("items") or []
        if not items:
            continue
        r += 1
        _put(ws, r, 2, title, bold=True, size=11)
        r += 1
        for c, h in enumerate(("No", "감사절차", "경영진 주장", "해당 여부", "조서번호", "수행자", "AI 제안(확인 전)"), 2):
            _put(ws, r, c, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
        for it in items:
            r += 1
            text = str(it.get("step") or "").strip()
            m = STEP_NO.match(text)
            no = int(m.group(1)) if m else None
            body = text[m.end():].strip() if m else text
            if not body and no is not None:          # 공개판 목록(원문 없음): 서식 번호만 적는다
                body = f"한공회 감사조서서식 {code} Part {part} {no}번 절차(문장은 서식에서 봅니다)"
            _put(ws, r, 2, no, align=CENTER, border=BOX)
            _put(ws, r, 3, body, align=WRAP, border=BOX)
            _put(ws, r, 4, " · ".join(it.get("assertions") or []), align=CENTER, border=BOX)
            c_in = _input(ws, r, 5)
            dv.add(c_in)
            ref = None
            if part == 1 and no is not None:
                link = it.get("link")                # 공개판 목록은 원문 대신 잇는 곳을 적어 둔다
                if link == "lead" or (link is None and ("감사결론" in body or no == 1)):
                    ref = LEAD
                elif link == "notes" or (link is None and "공시" in body):
                    ref = notes_ref
                else:
                    ref = sheet_refs.get(no)
            cr = _put(ws, r, 6, _label(a["letter"], ref) if ref else "", align=CENTER, border=BOX)
            if ref:
                style.link(cr, _ref(ref, "A1"))
            _input(ws, r, 7)
            _put(ws, r, 8, None, align=WRAP, border=BOX)
            if no is not None:
                slots[f"cover.p{part}.{no}"] = [COVER, f"H{r}"]
                slots[f"apply.p{part}.{no}"] = [COVER, f"E{r}"]
        r += 1
    return ws


def _calc_note(calc_ref: str | None) -> str | None:
    return (f"계산 근거: 엔진 조서 {calc_ref}(분석 · 표본 평가). 편철 · 서명은 이 표준조서에 합니다(2026-11-25 D1)"
            if calc_ref else None)


# ---------------------------------------------------------------- Lead
def _block_heads(per: dict, block: str) -> tuple[str, str, bool]:
    """블록 머리 기간(당기, 전기, 증감을 내는지). 재무상태표는 시점(기준일 · 전기말), 손익은 기간(2026.01~09 · 2025.01~12)."""
    if block == "BS":
        return per["bs_cur"], per["bs_prior"], True
    return per["pl_cur"], per["pl_prior"], per["comparable"]


def _diff_note(per: dict, block: str) -> str:
    if block == "PL" and not per["comparable"]:
        return (f"당기 {per['months']}개월 · 전기 {per['prior_months']}개월이라 증감을 내지 않습니다. "
                "같은 기간 전기 금액은 증감 사유 칸에 적습니다")
    return ""


def _diff_cells(ws, r: int, on: bool, total: bool = False):
    """증감 · 증감률 칸. on 이 거짓(기간이 다른 손익)이면 빈칸."""
    G, I, J = get_column_letter(L_FIN), get_column_letter(L_PRIOR), get_column_letter(L_DIFF)
    kw = {"bold": True, "fill": style.FILL_SUB} if total else {}
    _put(ws, r, L_DIFF, f'=IF({I}{r}="","",{G}{r}-{I}{r})' if on else None, fmt=NUM, border=BOX, **kw)
    if not total:
        _put(ws, r, L_PCT, f'=IF(OR({I}{r}="",{I}{r}=0),"",{J}{r}/ABS({I}{r}))' if on else None, fmt=PCT, border=BOX)


def _lead_block(ws, r: int, label: str, block: str, n: int, per: dict, sign: int | None = None) -> tuple[int, dict]:
    _put(ws, r, L_ACC, f"{label} {_sign_note(block, sign)}".strip(), bold=True)
    r += 1
    cur, prior, on = _block_heads(per, block)
    h1 = {L_ACC: "Account", L_PRE: "Preliminary", L_TM1: "t/m", L_DR: "Adjustment", L_FIN: "Final", L_TM2: "t/m",
          L_PRIOR: "Final", L_DIFF: "Diff", L_PCT: "Diff(%)", L_WHY: "증감 사유"}
    h2 = {L_PRE: cur, L_DR: "Dr", L_CR: "Cr", L_FIN: cur, L_PRIOR: prior}
    for c in range(L_ACC, L_WHY + 1):
        _put(ws, r, c, h1.get(c), bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
        _put(ws, r + 1, c, h2.get(c), bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
    ws.merge_cells(start_row=r, start_column=L_DR, end_row=r, end_column=L_CR)
    for c in (L_ACC, L_TM1, L_TM2, L_DIFF, L_PCT, L_WHY):
        ws.merge_cells(start_row=r, start_column=c, end_row=r + 1, end_column=c)
    r += 2
    first = r
    key_col, sg = get_column_letter(L_KEY), get_column_letter(L_SIGN)
    for i in range(1, n + 1):
        key = f"{block}-{i}"
        k = f"${key_col}{r}"
        _put(ws, r, L_KEY, key, color=style.WHITE)
        _put(ws, r, L_SIGN, f"=SUMIFS({_tbr(T_SIGN)},{_tbr(T_KEY)},{k})", color=style.WHITE)
        _put(ws, r, L_ACC, f'=IFERROR(INDEX({_tbr(T_NAME)},MATCH({k},{_tbr(T_KEY)},0)),"")', border=BOX)
        s = f"${sg}{r}"
        _put(ws, r, L_PRE, f"=SUMIFS({_tbr(T_CUR)},{_tbr(T_KEY)},{k})*{s}", fmt=NUM, border=BOX)
        _put(ws, r, L_DR, f"=SUMIFS({_tbr(T_DR)},{_tbr(T_KEY)},{k})", fmt=NUM, border=BOX)
        _put(ws, r, L_CR, f"=SUMIFS({_tbr(T_CR)},{_tbr(T_KEY)},{k})", fmt=NUM, border=BOX)
        P, D, C = (get_column_letter(x) for x in (L_PRE, L_DR, L_CR))
        _put(ws, r, L_FIN, f"={P}{r}+({D}{r}-{C}{r})*{s}", fmt=NUM, border=BOX)
        # 전기: 정산표 전기 칸이 비어 있으면(계정별 전기 손익이 없는 회사) 0 이 아니라 빈칸
        pidx = f"INDEX({_tbr(T_PRIOR)},MATCH({k},{_tbr(T_KEY)},0))"
        _put(ws, r, L_PRIOR, f'=IFERROR(IF({pidx}="","",{pidx}*{s}),"")', fmt=NUM, border=BOX)
        _diff_cells(ws, r, on)
        for c in (L_TM1, L_TM2):
            _put(ws, r, c, None, border=BOX, align=CENTER)
        _input(ws, r, L_WHY)
        r += 1
    last = r - 1
    _put(ws, r, L_ACC, "합계", bold=True, fill=style.FILL_SUB, border=BOX, align=CENTER)
    G, I, J = get_column_letter(L_FIN), get_column_letter(L_PRIOR), get_column_letter(L_DIFF)
    for c in (L_PRE, L_DR, L_CR, L_FIN):
        L = get_column_letter(c)
        _put(ws, r, c, f"=SUM({L}{first}:{L}{last})", bold=True, fill=style.FILL_SUB, fmt=NUM, border=BOX)
    _put(ws, r, L_PRIOR, f'=IF(COUNT({I}{first}:{I}{last})=0,"",SUM({I}{first}:{I}{last}))', bold=True, fill=style.FILL_SUB, fmt=NUM,
         border=BOX)
    _diff_cells(ws, r, on, total=True)
    for c in (L_TM1, L_TM2, L_PCT, L_WHY):
        _put(ws, r, c, None, fill=style.FILL_SUB, border=BOX)
    total = r
    r += 1
    _put(ws, r, L_ACC, "정산표 대사(차이, 0 이어야 함)", color=style.MUTED)
    _put(ws, r, L_FIN, f'={G}{total}-SUMIFS({_tbr(T_SHOW)},{_tbr(T_BLOCK)},"{block}")', fmt=NUM, color=style.RED)
    _put(ws, r, L_PRIOR, f'=IF({I}{total}="","",{I}{total}-SUMIFS({_tbr(T_SHOWP)},{_tbr(T_BLOCK)},"{block}"))', fmt=NUM, color=style.RED)
    _put(ws, r, L_WHY, f'=IF(AND(COUNT({I}{first}:{I}{last})=0,{G}{total}<>0),"계정별 전기 없음(표시과목 전기는 주석 시트)","")',
         color=style.MUTED)
    _put(ws, r + 1, L_ACC, _diff_note(per, block), color=style.MUTED)
    info = {"first": first, "n": n, "total": total, "check": r, "sign": sign, "label": first - 3}
    return r + 2, info


def _reserve(rows: list[dict], block: str, main: bool) -> int:
    n = sum(1 for x in rows if x["key"].startswith(block + "-"))
    return max(n + (5 if main else 3), 8 if main else 4)


def _lead(wb, tb: dict, code: str, rows: list[dict], proc: list[tuple[str, str, str, str]], slots: dict, reserve: dict,
          signs: dict | None = None) -> dict:
    a = areas()[code]
    ws = wb.create_sheet(LEAD)
    _sheet_base(ws, {"A": 2.5, "B": 30, "C": 15, "D": 4.5, "E": 13, "F": 13, "G": 15, "H": 4.5, "I": 15, "J": 14, "K": 10,
                     "L": 40, "N": 6, "O": 4})
    ws.column_dimensions["N"].hidden = True
    ws.column_dimensions["O"].hidden = True
    letter = a["letter"]
    _head(ws, tb, a["name"], letter, box_col=L_PCT)
    for i in range(2, 5):
        slots[["", "", "date", "prepared", "reviewed"][i]] = [LEAD, f"{get_column_letter(L_WHY)}{i}"]
    per = _per(tb)
    r = 6
    blocks = {}
    sec = 1
    if a["main"] != "none":
        _put(ws, r, L_ACC, f"{sec}. Lead Sheet", bold=True, size=11)
        r += 1
        order = ("BS", "PL") if a["main"] == "bs" else ("PL", "BS")
        for b in order:
            label = "재무상태표 계정" if b == "BS" else "손익 계정"
            n = reserve.get(b) or _reserve(rows, b, b == order[0])
            r, info = _lead_block(ws, r, label, b, n, per, (signs or {}).get(b))
            blocks[b] = info
            r += 1
        _put(ws, r, L_ACC, "<tickmark>", bold=True)
        for t, (sym, text) in enumerate(load_defs()["ticks"]):
            _put(ws, r + t, L_PRE, sym, bold=True, color=style.RED, align=CENTER)
            _put(ws, r + t, L_TM1, text)
        r += len(load_defs()["ticks"]) + 1
        sec += 1
    # 감사 절차
    _put(ws, r, L_ACC, f"{sec}. 감사 절차", bold=True, size=11)
    r += 1
    for c, h in ((L_ACC, "Procedure"), (L_FIN, "경영진 주장"), (L_TM2, None), (L_PRIOR, "Reference"), (L_DIFF, "결과")):
        _put(ws, r, c, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
    ws.merge_cells(start_row=r, start_column=L_FIN, end_row=r, end_column=L_TM2)
    ws.merge_cells(start_row=r, start_column=L_ACC, end_row=r, end_column=L_CR)
    ws.merge_cells(start_row=r, start_column=L_DIFF, end_row=r, end_column=L_WHY)
    if a["main"] == "none":
        items = [(f"{i}. {t}", "", "", f"check.{i}") for i, t in enumerate(a.get("checks") or [], 1)]
        refs = {s: rr for s, _, rr, _ in proc}
        items += [(f"{t}", asr, ref, f"result.{sid}") for sid, t, ref, asr in [(p[0], p[1], p[2], p[3]) for p in proc]]
    else:
        items = [(t, asr, ref, f"result.{sid}") for sid, t, ref, asr in proc]
    for text, asr, ref, slot in items:
        r += 1
        _put(ws, r, L_ACC, text, align=WRAP, border=BOX)
        ws.merge_cells(start_row=r, start_column=L_ACC, end_row=r, end_column=L_CR)
        _put(ws, r, L_FIN, asr, align=CENTER, border=BOX)
        _put(ws, r, L_TM2, None, border=BOX)
        ws.merge_cells(start_row=r, start_column=L_FIN, end_row=r, end_column=L_TM2)
        cr = _put(ws, r, L_PRIOR, _label(letter, ref) if ref else "", align=CENTER, border=BOX)
        if ref:
            style.link(cr, _ref(ref, "A1"))
        _input(ws, r, L_DIFF, merge_to=L_WHY)
        slots[slot] = [LEAD, f"{get_column_letter(L_DIFF)}{r}"]
    r += 2
    sec += 1
    _put(ws, r, L_ACC, f"{sec}. Audit memo", bold=True, size=11)
    for key, label in load_defs()["memo"]:
        r += 1
        _put(ws, r, L_ACC, label, bold=True)
        r += 1
        _input(ws, r, L_ACC, merge_to=L_WHY, height=72)
        slots[f"memo.{key}"] = [LEAD, f"B{r}"]
    r += 2
    sec += 1
    for key, label in (("finding", "발견사항"), ("conclusion", "결론")):
        _put(ws, r, L_ACC, f"{sec}. {label}", bold=True, size=11)
        r += 1
        _input(ws, r, L_ACC, merge_to=L_WHY, height=36 if key == "finding" else 30)
        slots[key] = [LEAD, f"B{r}"]
        r += 2
        sec += 1
    return blocks


# ---------------------------------------------------------------- 절차 · 주석 시트
def _sheet_name(sid: str, title: str) -> str:
    name = f".{sid} {title}"
    name = re.sub(r"[\\/?*\[\]:]", " ", name)
    return name[:31]


# 절차 시트 표(엔진 채움, 2026-11-25 D1)
FEED_NOTES = 4          # 엔진이 채운 표 아래 글 자리. 다시 씌울 때 결과 · 결론 칸이 밀리지 않게 미리 잡는다
MIN_ROWS, SPARE = 15, 5
GONE = "엔진 명세에 없음"
NOFILL = PatternFill(fill_type=None)


def _fmt_of(s: dict, col: str) -> str:
    return {"pct": PCT, "text": "@"}.get((s.get("fmts") or {}).get(col), NUM)


def _cl(spec: dict, col: str) -> str:
    return get_column_letter(2 + spec["cols"].index(col))


def _sub(tpl: str, row: int | None, spec: dict) -> str:
    """수식 틀의 {열}(같은 줄) · {p:이름}(표 위 줄 값) · {rng:열}(표 범위) · {a:이름:열}(표 아래 줄)을 칸 주소로 바꾼다."""
    def rep(m):
        t = m.group(1)
        if t.startswith("p:"):
            return f"$D${spec['prow'][t[2:]]}"
        if t.startswith("rng:"):
            L = _cl(spec, t[4:])
            return f"{L}{spec['first']}:{L}{spec['first'] + spec['n'] - 1}"
        if t.startswith("a:"):
            lab, col = t[2:].rsplit(":", 1)
            return f"{_cl(spec, col)}{spec['arow'][lab]}"
        return f"{_cl(spec, t)}{row}"
    return re.sub(r"\{([^{}]+)\}", rep, tpl)


def _k(v) -> str | None:
    return None if v in (None, "") else str(v).strip()


DUP = "\x1f"                      # 같은 이름 줄이 둘 이상이면 두 번째부터 「이름 DUP 2」 로 키를 나눠 차례대로 짝짓는다
PRIOR_ONLY = "전기에만 있음(올해 명세에 없음)"


def _dk(k: str | None, seen: dict) -> str | None:
    if k is None:
        return None
    seen[k] = seen.get(k, 0) + 1
    return k if seen[k] == 1 else f"{k}{DUP}{seen[k]}"


def _isf(v) -> bool:
    return isinstance(v, str) and v.startswith("=")


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _same(a, b) -> bool:
    """회계사가 고쳤는지 가르는 비교. 숫자는 정확히(100 과 100.4 는 다르다), 글자는 앞뒤 빈칸만 뺀다. 숫자와 글자는 다르다."""
    if a in (None, "") and b in (None, ""):
        return True
    if _isnum(a) and _isnum(b):
        return abs(a - b) < 1e-9
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    return a == b


def _tpl_cells(s: dict | None, spec: dict | None, r: int) -> dict:
    """엔진이 그 줄에 쓴 계산 수식. 회계사가 넣거나 고친 수식과 가르는 데 쓴다. 쓸 때의 틀(메타 spec calc)을 먼저 보고,
    없으면(그 전에 만든 조서) 지금 정의를 본다. 정의의 수식을 고쳐도 지난 엔진 수식을 회계사 수식으로 읽지 않게 한다."""
    if not spec:
        return {}
    tpls = spec.get("calc") if spec.get("calc") is not None else (s or {}).get("calc")
    out = {}
    for c, tpl in (tpls or {}).items():
        try:
            out[c] = _sub(tpl, r, spec)
        except (KeyError, ValueError):
            pass
    return out


def _read_table(ws, first: int, n: int, head: int, key: str | None, s: dict | None = None, spec: dict | None = None) -> dict:
    """표의 지금 값. {"rows": [(키, 칸)] 차례대로, "keyed": {키: 칸}, "free": [칸]}. 칸은 {머리 이름: 값, "_src": 줄}.
    엔진이 쓴 계산 수식(정의 calc 그대로)은 읽지 않고, 회계사가 넣거나 고친 수식은 글 그대로 읽는다(옮길 때 줄 주소를 맞춘다)."""
    heads = {str(ws.cell(head, c).value): c for c in range(2, ws.max_column + 1) if ws.cell(head, c).value not in (None, "")}
    calc_cols = set((spec or {}).get("calc") or (s or {}).get("calc") or {})
    rows, keyed, free, seen = [], {}, [], {}
    for r in range(first, first + n):
        tpl = _tpl_cells(s, spec, r)
        cells = {}
        for h, c in heads.items():
            v = ws.cell(r, c).value
            if _isf(v) and tpl.get(h) == v:
                continue
            cells[h] = v
        if all(v in (None, "") or (h in calc_cols and _isf(v)) for h, v in cells.items()):
            continue                            # 계산 열 수식만 있는 줄은 빈 줄이다
        cells["_src"] = r
        k = _dk(_k(cells.get(key)), seen) if key else None
        rows.append((k, cells))
        if k:
            keyed[k] = cells
        else:
            free.append(cells)
    return {"rows": rows, "keyed": keyed, "free": free}


def _read_extras(ws, spec: dict) -> dict:
    """표 위 표본 설계 값 · 표 아래 엔진 값 · 글. 엔진이 못 읽은 채 다시 그릴 때 지난 값을 남기려고 읽는다."""
    params = {lab: ws.cell(r, 4).value for lab, r in (spec.get("prow") or {}).items()}
    after = {}
    for lab, r in (spec.get("arow") or {}).items():
        vals = {}
        for j, c in enumerate(spec["cols"]):
            v = ws.cell(r, 2 + j).value
            if j and v not in (None, "") and not _isf(v):
                vals[c] = v
        after[lab] = vals
    notes = [ws.cell(r, 2).value for r in spec.get("note_rows") or [] if ws.cell(r, 2).value not in (None, "")]
    return {"params": params, "after": after, "notes": notes}


def _ungone(v):
    if not isinstance(v, str) or GONE not in v:
        return v
    t = v.replace(f" · {GONE}", "").replace(GONE, "").strip()
    return t or None


def _mine_v(cells: dict, c: str):
    return _ungone(cells.get(c)) if c == "비고" else cells.get(c)


def _prior_rows(prior: dict, consumed: set, key: str, cols: list, wrote: dict) -> list[dict]:
    """std roll 뒤 올해 명세에 없는 작년 거래처(설계 7.2). 작년 「기타 (n곳)」 은 올해 거래처와 나눌 수 없어 한 줄로 둔다.
    전기말 열 합계가 작년 당기말 합계와 같게 남긴다. 5곳이 넘으면 금액 큰 4곳과 나머지 합계 한 줄로 줄인다."""
    out = []

    def add(k: str, label: str, v, note: str):
        cells = {key: label, "전기말": v}
        if "비고" in cols:
            cells["비고"] = note
        out.append({"cells": cells, "fed": False})
        wrote[k] = {key: label, "비고": note, "_prior_only": True}

    for k, v in prior.items():
        if k.startswith("기타 (") and k not in consumed:
            add(f"전기 {k}", f"전기 {k.split(DUP)[0]}", v, "작년 금액 상위가 아닌 거래처 합계(올해 거래처와 나누지 못함)")
    left = sorted(((k, v) for k, v in prior.items() if k not in consumed and not k.startswith("기타 (")), key=lambda x: -abs(x[1]))
    if len(left) <= SPARE:
        for k, v in left:
            add(k, k.split(DUP)[0], v, PRIOR_ONLY)
    else:
        for k, v in left[:SPARE - 1]:
            add(k, k.split(DUP)[0], v, PRIOR_ONLY)
        rest = left[SPARE - 1:]
        lab = f"전기에만 있던 거래처 ({len(rest):,}곳)"
        add(lab, lab, sum(v for _, v in rest), "작년에만 있던 거래처 합계(올해 명세에 없음)")
    return out


def _merge(s: dict, feed: dict, old: dict | None, wrote_old: dict, prior: dict | None = None) -> tuple[list[dict], dict]:
    """다시 채울 줄 [{"cells", "fed"}] 과 엔진이 쓴 값(줄 키별). 설계 7.2: 엔진 칸이라도 지난번 엔진 값과 다르면 회계사가 고친 것이라
    그대로 두고, 회계사 열 · 회계사가 고친 계산 칸은 줄 키로 옮긴다. 엔진 명세에서 없어진 줄에 회계사 글이 있으면 끝에 남기고
    비고에 GONE 을 붙인다. prior(std roll)가 있으면 작년 당기말을 전기말에 넣는다."""
    cols, calc = list(s.get("cols") or []), s.get("calc") or {}
    old = old or {"rows": [], "keyed": {}, "free": []}
    if feed.get("error"):                 # 엔진이 이번에 못 읽었으면 지난 표를 차례 그대로 둔다
        rows = [{"cells": c, "fed": bool(k) and k in wrote_old} for k, c in old.get("rows") or []]
        return rows, dict(wrote_old)
    key = feed.get("key") or cols[0]
    own = [c for c in feed.get("own") or [] if c in cols]
    acc = [c for c in cols if c not in own and c not in calc]
    groups = feed.get("groups") or {}
    out, wrote, used, seen = [], {}, set(), {}
    for fr in feed.get("rows") or []:
        base = _k(fr.get(key))
        k = _dk(base, seen)
        prev, pw = old["keyed"].get(k), wrote_old.get(k) or {}
        cells, w = {}, {}
        for c in cols:
            if c in calc:
                if prev and prev.get(c) not in (None, ""):
                    cells[c] = prev[c]          # 회계사가 고친 계산 칸
                continue
            if c in own:
                v = fr.get(c)
                w[c] = v
                pv = prev.get(c) if prev else None
                if c == "비고":                  # 지난번에 붙인 「엔진 명세에 없음」 은 회계사 글이 아니다
                    pv = _ungone(pv)
                if pv not in (None, "") and not (c in pw and _same(pv, pw[c])):
                    v = pv                      # 회계사가 고친 엔진 칸
                cells[c] = v
            else:
                cells[c] = prev.get(c) if prev else None
        if prev:
            cells["_src"] = prev["_src"]
        if prior and "전기말" in cols and cells.get("전기말") in (None, ""):
            pv = prior.get(k)
            if pv is None and base in groups:   # 올해 「기타 (n곳)」 은 그 거래처들의 작년 금액 합
                hit = [prior[x] for x in groups[base] if x in prior]
                pv = sum(hit) if hit else None
            if pv is not None:
                cells["전기말"] = pv
        out.append({"cells": cells, "fed": True})
        wrote[k] = w
        used.add(k)
    for k, prev in old["keyed"].items():
        if k in used:
            continue
        pw = wrote_old.get(k)
        if pw is None:                          # 회계사가 적은 줄
            out.append({"cells": prev, "fed": False})
            continue
        if pw.get("_prior_only"):               # std roll 이 남긴 작년 거래처 줄
            out.append({"cells": prev, "fed": False})
            wrote[k] = pw
            continue
        mine = any(prev.get(c) not in (None, "") for c in acc if c in prev) or \
            any(prev.get(c) not in (None, "") for c in calc if c in prev) or \
            any(_mine_v(prev, c) not in (None, "") and not _same(_mine_v(prev, c), pw[c]) for c in pw if c != key)
        if mine:
            cells = dict(prev)
            if "비고" in cols:
                t = str(cells.get("비고") or "")
                cells["비고"] = t if GONE in t else (f"{t} · {GONE}" if t else GONE)
            out.append({"cells": cells, "fed": False})
            wrote[k] = pw                       # 다음에 그 줄이 돌아오면 엔진 값으로 바꿀 수 있게 지난 엔진 값을 남긴다
    out += [{"cells": c, "fed": False} for c in old["free"]]
    if prior and "전기말" in cols:
        consumed = used | {x for xs in groups.values() for x in xs} | {k for k in old["keyed"] if (wrote_old.get(k) or {}).get("_prior_only")}
        out += _prior_rows(prior, consumed, key, cols, wrote)
    return out, wrote


def _moved(v, src: int | None, r: int, col: str):
    """회계사 수식을 다른 줄로 옮길 때 상대 주소를 맞춘다(엑셀에서 줄을 복사해 붙인 것과 같게)."""
    if not _isf(v) or not src or src == r:
        return v
    try:
        return Translator(v, origin=f"{col}{src}").translate_formula(f"{col}{r}")
    except Exception:                    # noqa: BLE001  번역하지 못하면 글 그대로 둔다
        return v


def _write_table(ws, s: dict, spec: dict, rows: list[dict]):
    calc = s.get("calc") or {}
    own = set(spec.get("own") or [])
    for i in range(spec["n"]):
        r = spec["first"] + i
        x = rows[i] if i < len(rows) else None
        cells = (x or {}).get("cells") or {}
        src = cells.get("_src")
        for j, c in enumerate(spec["cols"]):
            col = get_column_letter(2 + j)
            if c in calc and cells.get(c) in (None, ""):
                v = _sub(calc[c], r, spec)
            else:
                v = _moved(cells.get(c), src, r, col)
            fill = style.FILL_IN if x and x["fed"] and c not in own and c not in calc else NOFILL
            _put(ws, r, 2 + j, v, fmt=_fmt_of(s, c), border=BOX, fill=fill)


def _write_head(ws, spec: dict, feed: dict, kept: bool = False):
    err = feed.get("error")
    if err and kept:
        head = f"엔진이 이번에 이 표를 채우지 못했습니다: {err}. 지난번 표와 값을 그대로 두었습니다"
    elif err:
        head = f"엔진이 이 표를 채우지 못했습니다: {err}. 표는 회사 제시 명세를 붙이거나 회계사가 적습니다"
    else:
        head = (f"엔진이 받은자료({feed.get('source') or '엔진 계산'})에서 채운 표입니다. 흰 칸은 엔진 값, 노랑 칸은 회계사가 적습니다. "
                "다시 씌우면 엔진 칸은 새 값이 되고 회계사가 고친 칸은 그대로입니다")
    _put(ws, spec["src_row"], 2, head, color=style.RED if err else style.MUTED)


def _write_extras(ws, s: dict, spec: dict, feed: dict, kept: bool = False):
    """표 위 표본 설계 값 · 표 아래 줄 · 출처와 글. 엔진이 못 읽었으면 feed 에 지난 값이 들어 온다(kept)."""
    for lab, r in spec["prow"].items():
        v = (feed.get("params") or {}).get(lab)
        fmt = ("0.00" if lab == "신뢰계수" else NUM) if isinstance(v, (int, float)) else None
        _put(ws, r, 4, v, fmt=fmt, border=BOX)
    yaml_after = s.get("after") or {}
    for lab, r in spec["arow"].items():
        vals = dict((feed.get("after") or {}).get(lab) or {})
        for col, tpl in (yaml_after.get(lab) or {}).items():
            vals[col] = _sub(tpl, r, spec)
        for j, c in enumerate(spec["cols"][1:], 1):
            v = vals.get(c)
            _put(ws, r, 2 + j, v, fmt=_fmt_of(s, c), border=BOX if v is not None else None,
                 color=style.RED if "차이" in lab and v is not None else None)
    _write_head(ws, spec, feed, kept)
    notes = list(feed.get("notes") or [])
    if len(notes) > FEED_NOTES:
        notes = notes[:FEED_NOTES - 1] + [" ".join(notes[FEED_NOTES - 1:])]
    for i, r in enumerate(spec["note_rows"]):
        _put(ws, r, 2, notes[i] if i < len(notes) else None, color=style.MUTED)


def _lead_tie(code: str, s: dict, lead_total: str) -> tuple[str, str]:
    """(Lead 대사 줄 이름, 견줄 금액 수식). lead_excl 이 있으면 정산표 시트에서 그 낱말이 든 계정(충당금 등)을 뺀 합이다."""
    if not s.get("lead_excl"):
        return "Lead 대사(차이)", lead_total
    blk = "BS" if areas()[code]["main"] == "bs" else "PL"
    crit = "".join(f',{_tbr(T_NAME)},"<>*{w}*"' for w in s["lead_excl"])
    return (f"Lead 대사(차이, {' · '.join(s['lead_excl'])} 계정 뺌)",
            f'SUMIFS({_tbr(T_SHOW)},{_tbr(T_BLOCK)},"{blk}"{crit})')


def _proc_sheet(wb, tb: dict, code: str, s: dict, lead_total: str | None, slots: dict, feed: dict | None = None,
                old: dict | None = None, wrote_old: dict | None = None, prior: dict | None = None,
                extras: dict | None = None) -> tuple[str, dict | None]:
    """절차 시트 하나. 정의에 feed 가 있으면 엔진 계산을 표에 채우고 표 위치 · 엔진 값을 spec 으로 돌려준다(메타 feeds)."""
    a = areas()[code]
    name = _sheet_name(s["id"], s["title"])
    ws = wb.create_sheet(name)
    cols = list(s.get("cols") or [])
    widths = {"A": 2.5, "B": 14}
    for i, _ in enumerate(cols):
        widths[get_column_letter(2 + i)] = 16 if i else 22
    width_end = max(2 + len(cols), 9)
    _sheet_base(ws, widths)
    _head(ws, tb, f".{s['id']} {s['title']}", f"{a['letter']}.{s['id']}", box_col=width_end, sign_box=False)
    _put(ws, 4, 1, a["name"], color=style.MUTED)
    for r, (lab, text) in enumerate((("목적", s.get("purpose", "")), ("감사 절차", s.get("proc", "")),
                                     ("경영진 주장", _asrt_names(s.get("asrt") or []))), 6):
        _put(ws, r, 2, lab, bold=True)
        _put(ws, r, 3, text)
    r = 10
    spec = None
    if cols and s.get("feed"):
        lay = stdfeed.LAYOUT.get(s["feed"]) or {"params": [], "after": []}
        feed = feed or {"error": "엔진 채움을 돌리지 않았습니다"}
        kept = bool(feed.get("error") and (old or {}).get("rows"))
        if feed.get("error") and extras:       # 엔진이 못 읽었으면 지난 표 위 · 아래 값과 글을 그대로 옮긴다
            feed = {**feed, "params": extras.get("params"), "after": extras.get("after"), "notes": extras.get("notes")}
        spec = {"sheet": name, "feed": s["feed"], "cols": cols, "own": [c for c in feed.get("own") or [] if c in cols],
                "key": feed.get("key") or cols[0], "prow": {}, "arow": {}, "error": feed.get("error"), "source": feed.get("source"),
                "calc": dict(s.get("calc") or {})}
        if feed.get("error"):
            spec["own"] = list((extras or {}).get("own") or [])
            if extras and extras.get("source"):
                spec["source"] = extras["source"]
            if prior:
                spec["prior"] = prior                # 엔진이 읽을 때까지 작년 당기말을 남긴다
        if lay["params"]:
            _put(ws, r, 2, "표본 설계(엔진)", bold=True)
            r += 1
            for lab in lay["params"]:
                _put(ws, r, 2, lab, color=style.MUTED)
                spec["prow"][lab] = r
                r += 1
            r += 1
        spec["src_row"] = r
        r += 1
    if cols:
        for i, h in enumerate(cols):
            _put(ws, r, 2 + i, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
        first = r + 1
        if spec is not None:
            rows, wrote = _merge(s, feed, old, wrote_old or {}, prior)
            spec.update(head=r, first=first, n=max(MIN_ROWS, len(rows) + SPARE), wrote=wrote)
            _write_table(ws, s, spec, rows)
            n = spec["n"]
        else:
            n = MIN_ROWS
            for rr in range(first, first + n):
                for i, _ in enumerate(cols):
                    _put(ws, rr, 2 + i, None, border=BOX, fmt=NUM)
        last = first + n - 1
        r = last + 1
        tie = s.get("tie")
        if tie and tie in cols:
            c = 2 + cols.index(tie)
            L = get_column_letter(c)
            _put(ws, r, 2, "합계", bold=True, fill=style.FILL_SUB, border=BOX, align=CENTER)
            for i in range(1, len(cols)):
                _put(ws, r, 2 + i, None, fill=style.FILL_SUB, border=BOX)
            _put(ws, r, c, f"=SUM({L}{first}:{L}{last})", bold=True, fill=style.FILL_SUB, fmt=NUM, border=BOX)
            if lead_total and s.get("lead", True):
                lab, ref = _lead_tie(code, s, lead_total)
                r += 1
                _put(ws, r, 2, lab, color=style.MUTED)
                _put(ws, r, c, f'=IF({L}{r - 1}=0,"",{L}{r - 1}-{ref})', fmt=NUM, color=style.RED)
            r += 1
        if spec is not None:
            labels = (stdfeed.LAYOUT.get(s["feed"]) or {}).get("after") or []
            if labels:
                r += 1
                for lab in labels:
                    _put(ws, r, 2, lab, color=style.MUTED)
                    spec["arow"][lab] = r
                    r += 1
            spec["note_rows"] = list(range(r, r + FEED_NOTES))
            _write_extras(ws, s, spec, feed, kept)
            r += FEED_NOTES - 1
        else:
            _put(ws, r, 2, "표는 회사 제시 명세를 붙이거나 회계사가 적습니다. 엔진은 표에 숫자를 넣지 않습니다.", color=style.MUTED)
    r += 2
    _put(ws, r, 2, "결과", bold=True)
    _input(ws, r + 1, 2, merge_to=width_end + 1, height=48)
    slots[f"sheet.{s['id']}.result"] = [name, f"B{r + 1}"]
    r += 3
    _put(ws, r, 2, "Conclusion", bold=True)
    _input(ws, r + 1, 2, merge_to=width_end + 1, height=30)
    slots[f"sheet.{s['id']}.conclusion"] = [name, f"B{r + 1}"]
    return name, spec


def _refeed(wb, code: str, meta: dict, feeds: dict) -> list[str]:
    """다시 씌울 때 엔진 채움 표를 다시 채운다. 예비 줄이 모자라거나 정의 열이 바뀌면 그 까닭을 돌려준다(아무것도 쓰지 않음)."""
    sheets = {s["id"]: s for s in areas()[code].get("sheets") or []}
    specs = meta.get("feeds") or {}
    plan, over = [], []
    for sid, spec in specs.items():
        s = sheets.get(sid)
        if not s or spec.get("sheet") not in wb.sheetnames:
            continue
        if list(s.get("cols") or []) != spec["cols"]:
            over.append(f".{sid} 표 열 정의가 바뀌었습니다")
            continue
        ws = wb[spec["sheet"]]
        old = _read_table(ws, spec["first"], spec["n"], spec["head"], spec.get("key"), s, spec)
        feed = feeds.get(sid) or {"error": "엔진 채움을 돌리지 않았습니다"}
        if feed.get("error"):                  # 지난 표 · 표 위 · 아래 값은 건드리지 않고 머리 글만 바꾼다
            plan.append((s, spec, ws, feed, None, None))
            continue
        rows, wrote = _merge(s, feed, old, spec.get("wrote") or {}, spec.get("prior"))
        if len(rows) > spec["n"]:
            over.append(f".{sid} 표 줄 {len(rows)}개 > 예비 줄 {spec['n']}줄")
            continue
        plan.append((s, spec, ws, feed, rows, wrote))
    if over:
        return over
    for s, spec, ws, feed, rows, wrote in plan:
        if feed.get("error"):
            spec["error"] = feed["error"]
            _write_head(ws, spec, feed, kept=True)
            continue
        spec.update(own=[c for c in feed.get("own") or [] if c in spec["cols"]] or spec.get("own") or [], wrote=wrote,
                    error=feed.get("error"), source=feed.get("source") or spec.get("source"), calc=dict(s.get("calc") or {}))
        if not feed.get("error"):
            spec.pop("prior", None)
            spec["key"] = feed.get("key") or spec["key"]
        _write_table(ws, s, spec, rows)
        _write_extras(ws, s, spec, feed)
    return []


def _notes_sheet(wb, tb: dict, code: str, sid: str, nfs: int, slots: dict) -> str:
    a = areas()[code]
    name = _sheet_name(sid, "주석")
    ws = wb.create_sheet(name)
    _sheet_base(ws, {"A": 2.5, "B": 28, "C": 15, "D": 15, "E": 12, "F": 15, "G": 15, "H": 12, "I": 32, "K": 6})
    ws.column_dimensions["K"].hidden = True
    _head(ws, tb, f".{sid} 주석 검토", f"{a['letter']}.{sid}", box_col=8, sign_box=False)
    _put(ws, 4, 1, a["name"], color=style.MUTED)
    _put(ws, 6, 2, "목적", bold=True)
    _put(ws, 6, 3, "조서 확정 금액과 회사 제시 주석 · 재무제표 금액이 맞는지 확인한다")
    _put(ws, 7, 2, "감사 절차", bold=True)
    _put(ws, 7, 3, "표시과목별 조서 금액(Lead Final)과 전기 금액을 주석의 당기 · 전기 금액과 대사하고 공시사항 점검표로 기재 사항을 확인한다")
    _put(ws, 9, 9, "(단위: 천원)", color=style.MUTED, align=Alignment(horizontal="right"))
    r = 10
    per = _per(tb)
    for c, h in ((3, f"당기({per['bs_cur']})"), (6, f"전기({per['bs_prior']})")):
        _put(ws, r, c, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
        ws.merge_cells(start_row=r, start_column=c, end_row=r, end_column=c + 2)
    for c in (2, 9):
        _put(ws, r, c, "표시과목" if c == 2 else "비고", bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
        ws.merge_cells(start_row=r, start_column=c, end_row=r + 1, end_column=c)
    r += 1
    for c, h in enumerate(("조서 금액", "주석 금액", "차이", "조서 금액", "주석 금액", "차이"), 3):
        _put(ws, r, c, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
    for i in range(1, nfs + 1):
        r += 1
        k = f"$K{r}"
        _put(ws, r, 11, f"FS-{i}", color=style.WHITE)
        _put(ws, r, 2, f'=IFERROR(INDEX({_tbr(F_LINE)},MATCH({k},{_tbr(F_KEY)},0)),"")', border=BOX)
        _put(ws, r, 3, f'=IF(B{r}="","",ROUND(SUMIFS({_tbr(F_SHOW)},{_tbr(F_KEY)},{k})/1000,0))', fmt=NUM, border=BOX)
        pidx = f"INDEX({_tbr(F_SHOWP)},MATCH({k},{_tbr(F_KEY)},0))"
        _put(ws, r, 6, f'=IFERROR(IF({pidx}="","",ROUND({pidx}/1000,0)),"")', fmt=NUM, border=BOX)
        for c in (4, 7):
            _input(ws, r, c)
            ws.cell(r, c).number_format = NUM
        _put(ws, r, 5, f'=IF(OR(C{r}="",D{r}=""),"",C{r}-D{r})', fmt=NUM, border=BOX, color=style.RED)
        _put(ws, r, 8, f'=IF(OR(F{r}="",G{r}=""),"",F{r}-G{r})', fmt=NUM, border=BOX, color=style.RED)
        _put(ws, r, 9, None, border=BOX)
    r += 1
    _put(ws, r, 2, "전기 조서 금액은 정산표 계정별 전기, 없으면 8100B 재무제표 시트의 표시과목 전기(그 과목 계정이 모두 이 조서에 있을 때)입니다. "
                   "손익 과목 금액의 기간은 Lead 손익 블록 머리에 있습니다.",
         color=style.MUTED)
    r += 2
    _put(ws, r, 2, "결과", bold=True)
    _input(ws, r + 1, 2, merge_to=9, height=40)
    slots[f"sheet.{sid}.result"] = [name, f"B{r + 1}"]
    r += 3
    _put(ws, r, 2, "Conclusion", bold=True)
    _input(ws, r + 1, 2, merge_to=9, height=30)
    slots[f"sheet.{sid}.conclusion"] = [name, f"B{r + 1}"]
    return name


# ---------------------------------------------------------------- 만들기
def _build(tb: dict, code: str, rows: list[dict], fs: list[tuple[str, str]], reserve: dict | None = None,
           old_signs: dict | None = None, feeds: dict | None = None, tables: dict | None = None,
           calc_ref: str | None = None) -> tuple[Workbook, dict]:
    a = areas()[code]
    wb = Workbook()
    wb.remove(wb.active)
    slots: dict = {}
    sheets = list(a.get("sheets") or [])
    names = [_sheet_name(s["id"], s["title"]) for s in sheets]
    has_tb = a["main"] != "none"
    nid = f"{len(sheets) + 1:02d}"
    notes_name = _sheet_name(nid, "주석") if has_tb else ""
    step_ref: dict[int, str] = {}
    for s, n in zip(sheets, names):
        for st in s.get("steps") or []:
            step_ref.setdefault(int(st), n)
    _cover(wb, tb, code, step_ref, notes_name or LEAD, slots, calc_ref)
    proc = [(s["id"], f".{s['id']} {s['title']}", n, " · ".join(s.get("asrt") or [])) for s, n in zip(sheets, names)]
    if has_tb:
        proc.append((nid, f".{nid} 주석 검토", notes_name, "CL · P"))
    reserve = dict(reserve or {})
    if has_tb:
        main = "BS" if a["main"] == "bs" else "PL"
        for b in ("BS", "PL"):
            reserve.setdefault(b, _reserve(rows, b, b == main))
    signs = block_signs(rows, old_signs)
    _apply_signs(rows, signs)
    blocks = _lead(wb, tb, code, rows, proc, slots, reserve, signs)
    main_b = "BS" if a["main"] == "bs" else "PL"
    lead_total = _ref(LEAD, f"${get_column_letter(L_FIN)}${blocks[main_b]['total']}") if has_tb else None
    specs = {}
    for s in sheets:
        t = (tables or {}).get(s["id"]) or {}
        _, spec = _proc_sheet(wb, tb, code, s, lead_total if s.get("tie") else None, slots, (feeds or {}).get(s["id"]),
                              t.get("old"), t.get("wrote"), t.get("prior"), t.get("extras"))
        if spec:
            specs[s["id"]] = spec
    nfs = 0
    if has_tb:
        nfs = max(len(fs) + 3, 6)
        _notes_sheet(wb, tb, code, nid, nfs, slots)
        _write_tb(wb, tb, rows, fs, code)
    meta = {"code": code, "made": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": tb["file"], "refreshed": None,
            "blocks": blocks, "nfs": nfs, "slots": slots, "ai": [], "feeds": specs}
    _set_meta(wb, meta)
    return wb, meta


def _save(wb, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    style.finish(wb)
    tmp = path.with_name(path.stem + ".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)


# 한글 수로 쓴 금액(「오천 원」 · 「삼억」 · 「십오만 원」). suggest.AMOUNT_RES 는 숫자 표기만 보고 다른 모듈과 같아야 해서 여기 따로 둔다
KOR_AMOUNT = (re.compile(r"(?<![가-힣])[일이삼사오육칠팔구십백천]+[만억조](?=원|\s|$|[.,)이을은도과의에])"),
              re.compile(r"(?<![가-힣])[일이삼사오육칠팔구]?[십백천]\s?원(?=$|\s|[.,)이을은도과의에])"))
SIGN_LABELS = ("Date", "Prepared", "Reviewed", "작성자", "검토자")          # 머리 서명 칸 · 표지 G3 · G4


def _kor_amount(text: str) -> str | None:
    for rx in KOR_AMOUNT:
        m = rx.search(text or "")
        if m:
            return m.group(0).strip()
    return None


def _signs(wb) -> dict:
    """시트마다 머리 오른쪽 위 Date · Prepared · Reviewed 칸과 표지 작성자 · 검토자 칸 {(시트, 라벨): (행, 열)}. 라벨 오른쪽 칸이 감사인 기입란이다."""
    out = {}
    for ws in wb.worksheets:
        for r in range(1, 6):
            for c in range(1, min(ws.max_column, 40) + 1):
                v = ws.cell(r, c).value
                if v in SIGN_LABELS:
                    out[(ws.title, v)] = (r, c + 1)
    return out


def _carry(old_path: Path) -> dict:
    """다시 그릴 때 옮길 글: 기입란 · AI 칸(칸 키별), 증감 사유(계정 키별), 해당 여부 · 수행자."""
    wb = load_workbook(old_path)
    try:
        m = _meta(wb)
        out = {"slots": {}, "why": {}, "ai": m.get("ai") or []}
        for k, (sh, ref) in (m.get("slots") or {}).items():
            if sh in wb.sheetnames:
                v = wb[sh][ref].value
                if v not in (None, ""):
                    out["slots"][k] = v
        if LEAD in wb.sheetnames:
            ws = wb[LEAD]
            for r in range(1, ws.max_row + 1):
                k, v = ws.cell(r, L_KEY).value, ws.cell(r, L_WHY).value
                if k and re.fullmatch(r"(BS|PL)-\d+", str(k)) and v not in (None, ""):
                    out["why"][str(k)] = v
        out["tables"] = _old_tables(wb, m)
        out["signs"] = {k: wb[k[0]].cell(*rc).value for k, rc in _signs(wb).items()
                        if wb[k[0]].cell(*rc).value not in (None, "")}
        return out
    finally:
        wb.close()


def _old_tables(wb, m: dict) -> dict:
    """다시 그릴 때 옮길 절차 시트 표. 엔진 채움 표는 메타 위치로, 그 전에 만든 조서(엔진 채움 없음)는 옛 자리(10행 머리 · 15줄)로 읽는다."""
    out = {}
    code = m.get("code")
    sheets = {s["id"]: s for s in (areas().get(code) or {}).get("sheets") or []} if code else {}
    specs = m.get("feeds") or {}
    for sid, s in sheets.items():
        if not s.get("feed") or not s.get("cols"):
            continue
        spec = specs.get(sid)
        name = (spec or {}).get("sheet") or _sheet_name(sid, s["title"])
        if name not in wb.sheetnames:
            continue
        if spec:
            ws = wb[name]
            old = _read_table(ws, spec["first"], spec["n"], spec["head"], spec.get("key"), s, spec)
            ex = {**_read_extras(ws, spec), "own": spec.get("own"), "source": spec.get("source")}
            out[sid] = {"old": old, "wrote": spec.get("wrote") or {}, "prior": spec.get("prior"), "extras": ex}
        else:
            out[sid] = {"old": _read_table(wb[name], 11, MIN_ROWS, 10, s["cols"][0]), "wrote": {}}
    return out


def _apply_carry(wb, meta: dict, carry: dict):
    at = _signs(wb)
    for k, v in (carry.get("signs") or {}).items():
        if k in at:
            wb[k[0]].cell(*at[k]).value = v
    for k, v in carry["slots"].items():
        if k in meta["slots"]:
            sh, ref = meta["slots"][k]
            wb[sh][ref].value = v
    ws = wb[LEAD]
    for r in range(1, ws.max_row + 1):
        k = ws.cell(r, L_KEY).value
        if k in carry["why"]:
            ws.cell(r, L_WHY).value = carry["why"][k]
    keep = []
    for x in carry["ai"]:
        if x.get("slot") in meta["slots"]:
            sh, ref = meta["slots"][x["slot"]]
            keep.append(dict(x, sheet=sh, cell=ref))
        elif x.get("lead_key"):
            for r in range(1, ws.max_row + 1):
                if ws.cell(r, L_KEY).value == x["lead_key"]:
                    keep.append(dict(x, sheet=LEAD, cell=f"{get_column_letter(L_WHY)}{r}"))
    meta["ai"] = keep
    _paint_ai(wb, meta)


def make(d: Path, codes: list[str] | None = None, wtb: str | None = None, force: bool = False) -> dict:
    d = Path(d)
    src = source(d, wtb)
    tb = read_tb(src)
    tb["period"] = period(d, tb)
    defs = areas()
    codes = codes or default_codes(tb)
    bad = [c for c in codes if c not in defs]
    if bad:
        raise Problem(f"정의에 없는 조서번호입니다: {', '.join(bad)}. `{stdmode.cmd('list', True)}` 로 확인하십시오")
    made, skipped = [], []
    for code in codes:
        path = file_for(d, code)
        carry = None
        old_acc, old_fs, reserve, old_signs = {}, {}, {}, {}
        if path.exists():
            if not force:
                skipped.append({"code": code, "file": str(path), "why": "이미 있음. 숫자만 바꾸려면 " + stdmode.cmd("refresh")})
                continue
            if busy(path):
                skipped.append({"code": code, "file": str(path), "why": BUSY, "busy": True})
                continue
            carry = _carry(path)
            wb0 = load_workbook(path)
            old_acc, old_fs = _old_keys(wb0)
            old_signs = {b: (i or {}).get("sign") for b, i in (_meta(wb0).get("blocks") or {}).items()}
            wb0.close()
            bak = d / "_보관" / f"{path.stem}_{datetime.now():%Y%m%d-%H%M%S}.xlsx"
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, bak)
        rows = assign_keys(pick(tb, code), old_acc)
        fs = _fs_keys(rows, old_fs)
        feeds = stdfeed.collect(d, code, defs[code].get("sheets") or [])
        wb, meta = _build(tb, code, rows, fs, reserve, old_signs, feeds, (carry or {}).get("tables"), _calc_ref(d, code))
        meta["refreshed"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if carry:
            _apply_carry(wb, meta, carry)
        _set_meta(wb, meta)
        _save(wb, path)
        made.append({"code": code, "file": str(path), "accounts": sum(1 for r in rows if not r.get("gone")),
                     "filled": sorted(k for k, v in (meta.get("feeds") or {}).items() if not v.get("error")),
                     "feed_errors": {k: v["error"] for k, v in (meta.get("feeds") or {}).items() if v.get("error")}})
    return {"source": str(src), "made": made, "skipped": skipped,
            "unassigned": [{"code": r["code"], "name": r["name"], "area": r["area"]} for r in unassigned(tb)]}


# ---------------------------------------------------------------- 씌우기
def _existing(d: Path, codes: list[str] | None) -> list[tuple[str, Path]]:
    out = []
    for code in areas():
        if codes and code not in codes:
            continue
        p = file_for(d, code)
        if p.exists():
            out.append((code, p))
    return out


def refresh(d: Path, codes: list[str] | None = None, wtb: str | None = None) -> dict:
    d = Path(d)
    src = source(d, wtb)
    tb = read_tb(src)
    tb["period"] = period(d, tb)
    done, stopped = [], []
    for code, path in _existing(d, codes):
        if busy(path):
            stopped.append({"code": code, "file": str(path), "why": BUSY, "busy": True})
            continue
        if areas()[code]["main"] == "none":
            done.append({"code": code, "file": str(path), "added": [], "gone": [], "note": "금액 표 없는 조서"})
            continue
        wb = load_workbook(path)
        try:
            meta = _meta(wb)
            old_acc, old_fs = _old_keys(wb)
            rows = assign_keys(pick(tb, code), old_acc)
            fs = _fs_keys(rows, old_fs)
            over = []
            for b, info in (meta.get("blocks") or {}).items():
                n = sum(1 for x in rows if x["key"].startswith(b + "-"))
                if n > info["n"]:
                    over.append(f"{'재무상태표' if b == 'BS' else '손익'} 계정 {n}개 > 예비 줄 {info['n']}줄")
            if len(fs) > (meta.get("nfs") or 0):
                over.append(f"표시과목 {len(fs)}개 > 주석 예비 줄 {meta.get('nfs')}줄")
            if over:
                stopped.append({"code": code, "file": str(path),
                                "why": "; ".join(over) + f". `{stdmode.cmd('make')} --area {code} --force` 로 다시 그리십시오(기입란 글은 옮깁니다)"})
                continue
            old_signs = {b: (i or {}).get("sign") for b, i in (meta.get("blocks") or {}).items()}
            signs = block_signs(rows, old_signs)
            _apply_signs(rows, signs)
            for b, info in (meta.get("blocks") or {}).items():
                if info.get("sign") not in (1, -1) and signs.get(b) in (1, -1):
                    info["sign"] = signs[b]
                    lab = info.get("label")
                    if lab and LEAD in wb.sheetnames:
                        cell = wb[LEAD].cell(lab, L_ACC)
                        cell.value = f"{str(cell.value or '').split(' (')[0]} {_sign_note(b, signs[b])}".strip()
            _write_tb(wb, tb, rows, fs, code)
            note = None
            sheets = areas()[code].get("sheets") or []
            if meta.get("feeds"):
                over = _refeed(wb, code, meta, stdfeed.collect(d, code, sheets))
                if over:
                    stopped.append({"code": code, "file": str(path),
                                    "why": "; ".join(over) + f". `{stdmode.cmd('make')} --area {code} --force` 로 다시 그리십시오(회계사 글은 옮깁니다)"})
                    continue
            elif any(s.get("feed") for s in sheets):
                note = f"엔진 채움 전에 만든 조서입니다. `{stdmode.cmd('make')} --area {code} --force` 로 다시 그리면 절차 시트 표를 채웁니다(회계사 글은 옮깁니다)"
            if COVER in wb.sheetnames:
                wb[COVER].cell(6, 2).value = _calc_note(_calc_ref(d, code))
            _heads(wb, tb)
            meta["source"] = tb["file"]
            meta["refreshed"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            _set_meta(wb, meta)
            # 정산표 시트를 지웠다 다시 쓰면 시트 순서가 바뀌지 않으므로 그대로 둔다
            _save(wb, path)
            done.append({"code": code, "file": str(path),
                         "added": [x["code"] for x in rows if x["code"] not in old_acc],
                         "gone": [x["code"] for x in rows if x.get("gone")],
                         "filled": sorted(k for k, v in (meta.get("feeds") or {}).items() if not v.get("error")),
                         "feed_errors": {k: v["error"] for k, v in (meta.get("feeds") or {}).items() if v.get("error")},
                         **({"note": note} if note else {})})
        finally:
            wb.close()
    return {"source": str(src), "done": done, "stopped": stopped,
            "unassigned": [{"code": r["code"], "name": r["name"], "area": r["area"]} for r in unassigned(tb)]}


def _heads(wb, tb: dict):
    """엔진 시트의 머리(A1 회사 · A2 결산일)를 정산표 값으로 맞춘다(작년 조서를 옮긴 뒤 등)."""
    for ws in wb.worksheets:
        if ws.title in (META, AI, COVER):
            continue
        if isinstance(ws["A2"].value, str) and ws["A2"].value.startswith("A: "):
            ws["A1"].value = tb["company"]
            ws["A2"].value = f"A: {_per(tb)['head']}"
    if COVER in wb.sheetnames:
        wb[COVER]["C3"].value = tb["company"]
        wb[COVER]["B4"].value = "기준일" if _per(tb)["kind"] == "중간감사" else "결산일"
        wb[COVER]["C4"].value = _per(tb)["head"]
    # Lead 블록 기간 머리 · 증감 칸(작년 · 중간감사 조서를 옮긴 뒤 기간이 바뀐다)
    per = _per(tb)
    blocks = (_meta(wb).get("blocks") or {}) if META in wb.sheetnames else {}
    if LEAD in wb.sheetnames:
        ws = wb[LEAD]
        for b, info in blocks.items():
            if not info or not info.get("label"):
                continue
            cur, prior, on = _block_heads(per, b)
            h2 = info["label"] + 2
            for c, v in ((L_PRE, cur), (L_FIN, cur), (L_PRIOR, prior)):
                ws.cell(h2, c).value = v
            for r in range(info["first"], info["first"] + info["n"]):
                _diff_cells(ws, r, on)
            _diff_cells(ws, info["total"], on, total=True)
            ws.cell(info["check"] + 1, L_ACC).value = _diff_note(per, b) or None
    for ws in wb.worksheets:
        if ws.title.startswith(".") and ws.title.endswith("주석") and str(ws.cell(10, 3).value or "").startswith("당기"):
            ws.cell(10, 3).value = f"당기({per['bs_cur']})"
            ws.cell(10, 6).value = f"전기({per['bs_prior']})"


# ---------------------------------------------------------------- AI 칸
def _paint_ai(wb, meta: dict):
    """확인 전 AI 칸을 연보라로 칠하고 「AI 작성」 시트를 다시 쓴다. 확인 값(O · X)은 옮긴다."""
    marks = {}
    if AI in wb.sheetnames:
        ws = wb[AI]
        for r in range(4, ws.max_row + 1):
            k = ws.cell(r, 8).value
            if k:
                marks[str(k)] = ws.cell(r, 6).value
        wb.remove(ws)
    for x in meta["ai"]:
        sid = f"{x['sheet']}!{x['cell']}"
        if sid in marks and marks[sid] not in (None, ""):
            x["mark"] = str(marks[sid]).strip().upper()
        c = wb[x["sheet"]][x["cell"]]
        if x.get("mark") == "O":
            c.fill = style.FILL_IN if x.get("input") else PatternFill(fill_type=None)
            c.font = F()
            c.border = BOX
        else:
            c.fill = style.FILL_AI
            c.font = F(color=style.AI_INK)
            c.border = style.AI_BOX
    if not meta["ai"]:
        return
    ws = wb.create_sheet(AI)
    _sheet_base(ws, {"A": 2.5, "B": 16, "C": 10, "D": 60, "E": 36, "F": 9, "H": 4})
    ws.column_dimensions["H"].hidden = True
    _put(ws, 1, 2, "AI 작성 칸", bold=True, size=11)
    _put(ws, 2, 2, "에이전트가 쓴 글입니다(확인 전). 읽고 「확인」 에 O(맞음) 또는 X(고칠 것)를 적습니다. O 를 적고 "
                   f"`{stdmode.cmd('refresh')}` 나 `{stdmode.cmd('fill')}` 을 다시 돌리면 그 칸의 연보라가 풀립니다.", color=style.MUTED)
    for c, h in enumerate(("시트", "칸", "AI 가 쓴 글", "근거", "확인"), 2):
        _put(ws, 3, c, h, bold=True, fill=style.FILL_NONE, align=CENTER, border=BOX)
    for i, x in enumerate(meta["ai"], 4):
        _put(ws, i, 2, x["sheet"], border=BOX, align=WRAP)
        cl = _put(ws, i, 3, x["cell"], border=BOX, align=Alignment(horizontal="center", vertical="top"))
        style.link(cl, _ref(x["sheet"], x["cell"]))
        _put(ws, i, 4, x.get("what") or x.get("text"), align=WRAP, border=BOX)
        _put(ws, i, 5, x.get("basis"), align=WRAP, border=BOX)
        _input(ws, i, 6, x.get("mark"))
        _put(ws, i, 8, f"{x['sheet']}!{x['cell']}", color=style.WHITE)


def fill(d: Path, code: str, patch: dict) -> dict:
    """에이전트 패치. {"slots": [{slot, text, basis}], "reasons": [{code, text, basis}], "suggest": [{part, no, pick, why}]}
    slot 은 memo.main · memo.change · memo.risk · finding · sheet.<id>.result · check.<n> · result.<id> 등(std check --slots).
    글에 금액 꼴 숫자가 있으면 패치 전체를 거부한다. 해당 여부 · 결론 칸은 회계사 몫이라 받지 않는다."""
    from .workpapers.suggest import amount_in_text

    d = Path(d)
    path = file_for(d, code)
    if not path.exists():
        raise Problem(f"표준조서가 없습니다: {path}. 먼저 `{stdmode.cmd('make')} --area {code}`")
    if busy(path):
        raise Problem(f"{path.name} 이 엑셀에서 열려 있습니다. 파일을 닫고 다시 돌리십시오(아무것도 쓰지 않음)")
    wb = load_workbook(path)
    try:
        meta = _meta(wb)
        slots = meta.get("slots") or {}
        probs, todo = [], []
        for x in patch.get("slots") or []:
            k, t = x.get("slot"), str(x.get("text") or "").strip()
            if k not in slots:
                probs.append(f"없는 칸입니다: {k}")
                continue
            if k in ("conclusion", "date", "prepared", "reviewed") or k.startswith("apply."):
                probs.append(f"{k} 는 회계사 기입란입니다. 에이전트가 쓰지 않습니다")
                continue
            todo.append((k, slots[k][0], slots[k][1], t, x.get("basis"), True, None))
        ws = wb[LEAD] if LEAD in wb.sheetnames else None
        keyrow = {}
        if ws is not None and TB in wb.sheetnames:
            acc, _ = _old_keys(wb)
            for r in range(1, ws.max_row + 1):
                k = ws.cell(r, L_KEY).value
                if k:
                    keyrow[str(k)] = r
            code2key = {c: v["key"] for c, v in acc.items()}
        else:
            code2key = {}
        for x in patch.get("reasons") or []:
            c, t = str(x.get("code") or ""), str(x.get("text") or "").strip()
            key = code2key.get(c)
            if not key or key not in keyrow:
                probs.append(f"Lead 에 없는 계정코드입니다: {c}")
                continue
            todo.append((None, LEAD, f"{get_column_letter(L_WHY)}{keyrow[key]}", t, x.get("basis"), True, key))
        for x in patch.get("suggest") or []:
            k = f"cover.p{x.get('part', 1)}.{x.get('no')}"
            pick_ = str(x.get("pick") or "").strip()
            if k not in slots:
                probs.append(f"표지에 없는 절차입니다: Part {x.get('part', 1)} {x.get('no')}")
                continue
            if pick_ not in ("해당", "해당없음"):
                probs.append(f"제안은 「해당」 또는 「해당없음」 입니다: {pick_}")
                continue
            t = f"{pick_}: {str(x.get('why') or '').strip()}"
            todo.append((k, slots[k][0], slots[k][1], t, x.get("why"), False, None))
        for k, sh, ref, t, basis, _inp, _key in todo:
            if not t:
                probs.append(f"빈 글입니다: {k or ref}")
            if t.lstrip().startswith("="):
                probs.append(f"{k or ref}: 「=」 로 시작하는 글은 엑셀이 수식으로 읽어 받지 않습니다")
            for s_ in (t, str(basis or "")):
                amt = amount_in_text(s_) or _kor_amount(s_)
                if amt:
                    probs.append(f"{k or sh + '!' + ref}: 금액으로 보이는 「{amt}」 가 있습니다. 금액은 Lead 가 보이고 글은 Lead 를 가리킵니다")
        if probs:
            raise Problem("패치를 받지 않았습니다(아무것도 쓰지 않음).\n" + "\n".join(probs))
        cur = {(x["sheet"], x["cell"]): x for x in meta.get("ai") or []}
        for k, sh, ref, t, basis, inp, key in todo:
            wb[sh][ref].value = t
            wb[sh][ref].alignment = WRAP
            cur[(sh, ref)] = {"slot": k, "lead_key": key, "sheet": sh, "cell": ref, "what": t, "basis": basis, "input": inp,
                              "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        meta["ai"] = list(cur.values())
        _paint_ai(wb, meta)
        _set_meta(wb, meta)
        _save(wb, path)
        return {"code": code, "file": str(path), "written": len(todo), "ai_total": len(meta["ai"])}
    finally:
        wb.close()


# ---------------------------------------------------------------- 점검
def check(d: Path) -> list[dict]:
    d = Path(d)
    try:
        src = source(d)
        src_m = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except Problem:
        src_m = None
    return [check_file(code, path, src_m) for code, path in _existing(d, None)]


def check_file(code: str, path: Path, src_m: str | None = None) -> dict:
    """표준조서 한 파일의 점검. 정산표 판 · Lead 대사 차이 · 확인 전 AI 칸 · 빈 해당 여부 · 빈 결론(Lead 와 「해당」 절차 시트) ·
    엔진이 채우지 못한 표."""
    from .workpapers.xlcalc import Calc, Unsupported

    wb = load_workbook(path)
    try:
        meta = _meta(wb)
        item = {"code": code, "file": str(path), "source": meta.get("source"), "refreshed": meta.get("refreshed"),
                "stale": bool(src_m and meta.get("refreshed") and src_m > meta["refreshed"]), "diff": [], "ai_open": 0,
                "apply_blank": 0, "conclusion_blank": [], "slots": sorted((meta.get("slots") or {}).keys()),
                "feed_errors": {k: v["error"] for k, v in (meta.get("feeds") or {}).items() if v.get("error")}, "busy": busy(path)}
        for x in meta.get("ai") or []:
            if x.get("mark") != "O":
                item["ai_open"] += 1
        if AI in wb.sheetnames:
            ws = wb[AI]
            item["ai_open"] = sum(1 for r in range(4, ws.max_row + 1)
                                  if ws.cell(r, 8).value and str(ws.cell(r, 6).value or "").strip().upper() != "O")
        slots = meta.get("slots") or {}

        def val(k):
            sh, ref = slots[k]
            return wb[sh][ref].value if sh in wb.sheetnames else None

        applies = {}
        for k in slots:
            if k.startswith("apply.p1."):
                v = val(k)
                if v in (None, ""):
                    item["apply_blank"] += 1
                applies[k.split(".")[-1]] = str(v or "").replace(" ", "")
        if "conclusion" in slots and val("conclusion") in (None, ""):
            item["conclusion_blank"].append("Lead")
        for s in (areas().get(code) or {}).get("sheets") or []:
            k = f"sheet.{s['id']}.conclusion"
            on = any(applies.get(str(n)) == "해당" for n in s.get("steps") or [])
            if k in slots and on and val(k) in (None, ""):
                item["conclusion_blank"].append(f".{s['id']}")
    finally:
        wb.close()
    if meta.get("blocks"):
        calc = Calc(path)
        for b, info in meta["blocks"].items():
            for col in (L_FIN, L_PRIOR):
                ref = f"{get_column_letter(col)}{info['check']}"
                try:
                    v = calc.cell(LEAD, ref)
                except Unsupported as e:
                    item["diff"].append({"block": b, "cell": ref, "error": str(e)})
                    continue
                if isinstance(v, (int, float)) and abs(v) >= 1:
                    item["diff"].append({"block": b, "cell": ref, "diff": v})
    return item


def problems(item: dict) -> list[str]:
    """check_file 결과를 조서 검사(wp check) 문제 글로. 비어 있으면 표준조서는 검사를 통과한다."""
    out = []
    for x in item["diff"]:
        if "error" in x:
            out.append(f"표준조서 Lead 대사 칸 {x['cell']} 을 계산하지 못했습니다({x['error']})")
        else:
            out.append(f"표준조서 Lead {'재무상태표' if x['block'] == 'BS' else '손익'} 대사 차이 {x['diff']:,.0f}원({x['cell']})")
    if item["stale"]:
        out.append(f"정산표(8100B)가 표준조서보다 새롭습니다. `{stdmode.cmd('refresh', True)}` 로 다시 씌우십시오")
    if item["ai_open"]:
        out.append(f"표준조서 확인 전 AI 칸 {item['ai_open']}곳(「AI 작성」 시트 확인 칸에 O · X)")
    if item["apply_blank"]:
        out.append(f"표준조서 표지 해당 여부 빈 칸 {item['apply_blank']}곳")
    if item["conclusion_blank"]:
        out.append("표준조서 결론 빈 칸: " + " · ".join(item["conclusion_blank"]))
    return out


# ---------------------------------------------------------------- 작년 조서 옮기기
def roll(prev: Path, d: Path, wtb: str | None = None) -> dict:
    """작년 감사 폴더의 표준조서를 올해 폴더로 옮긴다. 머리 · 서명 · AI 제안 · 그해 결과 · 결론 · 증감 사유 · 절차 표를 비우고
    메모(주요 내용 · 증감 분석 · 이슈 대응)와 해당 여부는 남긴다. 남긴 메모는 노랑 기입란이고 맨 앞에 「[전기]」 를 붙여 고칠 곳을 보인다."""
    prev, d = Path(prev), Path(d)
    files = sorted((prev / SUB).glob("4000*_표준.xlsx"))
    if not files:
        raise Problem(f"작년 표준조서가 없습니다: {prev / SUB}")
    moved = []
    for f in files:
        dst = d / SUB / f.name
        if dst.exists():
            moved.append({"file": str(dst), "skip": "올해 조서가 이미 있음"})
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        wb = load_workbook(f)
        meta = _meta(wb)
        keep = {"memo.main", "memo.change", "memo.risk"}
        for k, (sh, ref) in (meta.get("slots") or {}).items():
            c = wb[sh][ref]
            if k.startswith("apply."):
                continue
            if k in keep and c.value not in (None, ""):
                v = str(c.value)
                c.value = v if v.startswith("[전기]") else f"[전기] {v}"
                c.fill, c.font, c.border = style.FILL_IN, F(), BOX
                continue
            c.value = None
            c.fill = style.FILL_IN if not k.startswith("cover.") else PatternFill(fill_type=None)
            c.font, c.border = F(), BOX
        if COVER in wb.sheetnames:
            for ref in ("G3", "G4"):
                wb[COVER][ref].value = None
        if LEAD in wb.sheetnames:
            ws = wb[LEAD]
            for r in range(1, ws.max_row + 1):
                if ws.cell(r, L_KEY).value:
                    ws.cell(r, L_WHY).value = None
        fed = {}
        sdefs = {s["id"]: s for s in (areas().get(meta.get("code")) or {}).get("sheets") or []}
        for sid, spec in (meta.get("feeds") or {}).items():
            if spec.get("sheet") not in wb.sheetnames:
                continue
            ws = wb[spec["sheet"]]
            s = sdefs.get(sid)
            old = _read_table(ws, spec["first"], spec["n"], spec["head"], spec.get("key"), s, spec)
            if "당기말" in spec["cols"] and "전기말" in spec["cols"]:
                # 작년 거래처별 당기말이 올해 전기말이 된다(설계 7.2). 「기타 (n곳)」 · 거래처 아닌 줄도 키 그대로 옮기고,
                # 올해 명세에 없는 거래처는 「전기에만 있음」 줄로 남긴다(_prior_rows)
                spec["prior"] = {k: c.get("당기말") for k, c in old["keyed"].items() if _isnum(c.get("당기말"))}
            for r in range(spec["first"], spec["first"] + spec["n"]):
                tpl = _tpl_cells(s, spec, r)
                for j, h in enumerate(spec["cols"]):
                    cell = ws.cell(r, 2 + j)
                    if _isf(cell.value) and tpl.get(h) == cell.value:
                        continue                      # 엔진 계산 수식은 남긴다
                    cell.value = None
                    cell.fill = NOFILL
            spec["wrote"] = {}
            fed[spec["sheet"]] = True
        for ws in wb.worksheets:
            if ws.title.startswith(".") and "주석" not in ws.title and ws.title not in fed:
                for r in range(11, 26):
                    for c in range(2, ws.max_column + 1):
                        if not (isinstance(ws.cell(r, c).value, str) and str(ws.cell(r, c).value).startswith("=")):
                            ws.cell(r, c).value = None
        meta["ai"] = []
        if AI in wb.sheetnames:
            wb.remove(wb[AI])
        meta["rolled_from"] = str(f)
        _set_meta(wb, meta)
        _save(wb, dst)
        wb.close()
        moved.append({"file": str(dst)})
    res = refresh(d, None, wtb)
    return {"moved": moved, "refresh": res}


def list_defs() -> list[dict]:
    out = []
    for code, a in areas().items():
        out.append({"code": code, "name": a["name"], "letter": a["letter"], "main": a["main"],
                    "sheets": [f".{s['id']} {s['title']}" for s in a.get("sheets") or []]})
    return out
