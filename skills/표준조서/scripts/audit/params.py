"""감사방법론 설정(2700B)과 정의 파일 겹쳐 읽기 (2026-10-07).

정의 파일(definitions/*.yaml)의 판단값은 기본값이다. 감사 건마다 2700B 감사방법론 설정 조서의 「감사인 값」 이 그 기본값을 덮는다.
목록은 definitions/parameters.yaml. 이 감사에 적용한 값은 이 감사 파일(2700B)에 남아 보관(8700)과 함께 고정된다.

  use(d)                  with 문. 그 안에서 정의 파일을 읽으면(analysis.defs.load · workpapers.common.load_def · 8700 정의)
                          d 의 2700B 값이 겹쳐진다. 같은 d 로 다시 들어가면 아무것도 하지 않는다
  engaged                 첫 인자가 감사 폴더인 함수에 붙이는 장식자(use 를 대신 연다)
  overlay(file, data)     정의 파일 dict 에 지금 감사 건의 값을 겹친 사본
  overrides(d)            2700B 감사인 값 {key: 값}
  make_wp(d)              2700B 조서를 만든다(감사인 값 · 변경 사유는 이어받는다)
  view(d)                 화면 「방법론」 의 표(2700A 중요성 선택 · 2120A 유의성 기준 · 2700B 묶음)
  save(d, values, who)    화면에서 고친 값을 2700A · 2120A · 2700B 노란 칸에 적는다(엑셀에서 고친 것과 같다)
"""
from __future__ import annotations

import contextvars
import copy
import functools
import re
from contextlib import contextmanager
from pathlib import Path

import yaml

DEFS = Path(__file__).resolve().parents[1] / "definitions"
NO = "2700B"
SHEET = "2700B"
VALUE = "감사인 값: "
REASON = "변경 사유: "
_ACTIVE: contextvars.ContextVar = contextvars.ContextVar("audit_params", default=None)
_CAT: dict | None = None
_OVR_CACHE: dict = {}


# ---------------------------------------------------------------- 카탈로그 · 경로
def catalog() -> dict:
    global _CAT
    if _CAT is None:
        _CAT = yaml.safe_load((DEFS / "parameters.yaml").read_text(encoding="utf-8"))
        _CAT["by_key"] = {p["key"]: p for p in _CAT["params"]}
    return _CAT


def _tokens(path: str) -> list:
    out = []
    for part in re.findall(r"[^.\[\]]+(?:\[[^\]]+\])?", path):
        m = re.match(r"^(.*?)\[(\w+)=([^\]]+)\]$", part)
        if m:
            out += [m.group(1), (m.group(2), m.group(3))]
        else:
            out.append(part)
    return out


def _walk(data, toks: list, create: bool = False):
    cur = data
    for t in toks:
        if isinstance(t, tuple):
            cur = next((x for x in cur if isinstance(x, dict) and str(x.get(t[0])) == t[1]), None)
        else:
            cur = cur.get(t) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def get_path(data: dict, path: str):
    return _walk(data, _tokens(path))


def set_path(data: dict, path: str, value) -> bool:
    toks = _tokens(path)
    parent = _walk(data, toks[:-1])
    if not isinstance(parent, dict):
        return False
    parent[toks[-1]] = value
    return True


def _raw(file: str) -> dict:
    return yaml.safe_load((DEFS / f"{file}.yaml").read_text(encoding="utf-8"))


def default_of(p: dict):
    return get_path(_raw(p["file"]), p["path"])


# ---------------------------------------------------------------- 값 읽기 · 형식
def parse(p: dict, v):
    """기입란 글자 → 값. 못 읽으면 None."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    u = p["unit"]
    if u == "yesno":
        s = str(v).strip()
        return True if s in ("예", "Y", "y", "True", "true", "1") else False if s in ("아니오", "N", "n", "False", "false", "0") else None
    if u == "choice":
        s = str(v).strip()
        return s if s in (p.get("choices") or []) else None
    if isinstance(v, bool):
        return None
    s = str(v).strip().replace(",", "").replace("원", "").replace("일", "").replace("배", "").replace("개월", "").replace("개", "")
    pct = s.endswith("%") or s.endswith("%p")
    s = s.rstrip("p").rstrip("%")
    try:
        x = float(s)
    except ValueError:
        return None
    if u in ("ratio", "pp"):
        return x / 100 if pct or x > 1 else x
    if u in ("days", "count", "months", "won", "int"):
        return int(round(x))
    return x


def show(p: dict, v) -> str:
    if v is None:
        return ""
    u = p["unit"]
    if u == "yesno":
        return "예" if v else "아니오"
    if u in ("ratio",):
        return f"{v * 100:g}%"
    if u == "pp":
        return f"{v * 100:g}%p"
    if u == "days":
        return f"{v}일"
    if u == "months":
        return f"{v}개월"
    if u == "count":
        return f"{v}"
    if u == "won":
        return f"{v:,}원"
    if u == "multiple":
        return f"{v:g}배"
    return f"{v}"


def overrides(d: Path) -> dict:
    """2700B 의 감사인 값 {key: 값}. 파일이 그대로면 다시 읽지 않는다."""
    from . import wp

    p = wp.path_for(Path(d), NO)
    if not p.exists():
        return {}
    k = (str(p), p.stat().st_mtime_ns)
    if k not in _OVR_CACHE:
        by = catalog()["by_key"]
        out = {}
        try:
            for x in wp.readback(p):
                lab = str(x["label"])
                if lab.startswith(VALUE) and lab[len(VALUE):] in by:
                    v = parse(by[lab[len(VALUE):]], x["value"])
                    if v is not None:
                        out[lab[len(VALUE):]] = v
        except Exception:  # noqa: BLE001  회계사가 다른 꼴로 저장한 파일은 감사인 값 없음으로 본다
            pass
        _OVR_CACHE.clear()
        _OVR_CACHE[k] = out
    return dict(_OVR_CACHE[k])


# ---------------------------------------------------------------- 겹쳐 읽기
@contextmanager
def use(d: Path):
    d = Path(d).resolve()
    cur = _ACTIVE.get()
    if cur is not None and cur["d"] == d:
        yield cur
        return
    by = catalog()["by_key"]
    files: dict = {}
    for key, v in overrides(d).items():
        files.setdefault(by[key]["file"], []).append((by[key]["path"], v))
    token = _ACTIVE.set({"d": d, "files": files})
    try:
        yield _ACTIVE.get()
    finally:
        _ACTIVE.reset(token)


def engaged(fn):
    """첫 인자가 감사 폴더(d)인 함수 안에서 그 감사 건의 2700B 값을 겹쳐 읽게 한다."""
    @functools.wraps(fn)
    def wrap(d, *a, **k):
        with use(d):
            return fn(d, *a, **k)
    return wrap


def overlay(file: str, data: dict) -> dict:
    act = _ACTIVE.get()
    if not act or file not in act["files"] or not isinstance(data, dict):
        return data
    data = copy.deepcopy(data)
    for path, v in act["files"][file]:
        set_path(data, path, v)
    return data


def active_dir() -> Path | None:
    act = _ACTIVE.get()
    return act["d"] if act else None


# ---------------------------------------------------------------- 2700B 조서
def make_wp(d: Path) -> Path:
    from . import wp
    from .analysis.wp_util import carry_values

    d = Path(d)
    cat = catalog()
    carry = carry_values(d, NO)
    b = wp.Book(d, NO, title="감사방법론 설정", standard="감사기준서 230 · 320 · 530 · 520")
    ws, row = b.sheet(SHEET, [34, 14, 14, 14, 14, 10, 34, 30])
    ws.cell(6, 1, "이 감사에 적용한 판단값이다. 감사인 값을 비우면 기본값(definitions 정의 파일)을 쓴다. 바꾸면 변경 사유를 적고 "
                  "오른쪽 명령을 다시 돌린다. 중요성은 2700A, 유의성 기준은 2120A 에서 정한다").font = wp.font(size=9, color=wp.MUTED)
    ovr = overrides(d)
    for g in cat["groups"]:
        ps = [p for p in cat["params"] if p["group"] == g["key"]]
        if not ps:
            continue
        row = b.section(ws, row, f"{g['title']}  (바꾸면: python -m audit {g['rerun']} <폴더>)")
        row = b.head(ws, row, ["항목", "영향 조서", "기본값", "감사인 값", "적용값", "근거 수준", "근거", "변경 사유"])
        for p in ps:
            dv = default_of(p)
            ov = ovr.get(p["key"])
            b.put(ws, row, 1, p["name"], wrap=True)
            b.put(ws, row, 2, p["wp"])
            b.put(ws, row, 3, show(p, dv))
            b.ask(ws, row, 4, VALUE + p["key"], rule="optional", value=carry.get((SHEET, VALUE + p["key"])))
            b.put(ws, row, 5, show(p, ov if ov is not None else dv), flag=ov is not None and ov != dv)
            b.put(ws, row, 6, p["grade"])
            b.put(ws, row, 7, p.get("basis") or "", wrap=True)
            b.ask(ws, row, 8, REASON + p["key"], rule="optional", value=carry.get((SHEET, REASON + p["key"])))
            row += 1
        row += 1
    ws.cell(row, 1, "감사인 값은 「20%」 · 「0.2」 · 「15」 · 「예」 처럼 적는다. 근거 수준: 기준서 · 법정은 근거 문서의 값, 실무 관행은 흔히 쓰는 범위의 값, "
                    "초기값은 대표 블라인드 대조로 조정할 값이다").font = wp.font(size=9, color=wp.MUTED)
    return b.save()


# ---------------------------------------------------------------- 화면
MAT_FIELDS = [  # (조서, 기입란, 단위, 보이는 이름)
    ("2700A", "중요성 기준", "text", "중요성 기준"),
    ("2700A", "중요성 백분율", "ratio", "중요성 백분율"),
    ("2700A", "수행중요성 비율", "ratio", "수행중요성 비율"),
    ("2700A", "명백히 사소한 금액 비율", "ratio", "명백히 사소한 금액 비율"),
    ("2700A", "재무제표 전체 중요성", "won", "재무제표 전체 중요성(금액을 적으면 위 선택보다 앞섬)"),
    ("2700A", "수행중요성", "won", "수행중요성(금액)"),
    ("2700A", "명백히 사소한 금액", "won", "명백히 사소한 금액(금액)"),
    ("2120A", "유의성 기준 금액", "won", "유의성 기준 금액"),
    ("2120A", "유의성 기준 비율", "ratio", "유의성 기준 비율"),
    ("2120A", "설명 후 허용 차이", "won", "설명 후 허용 차이"),
]
APPLIED_KEY = {"재무제표 전체 중요성": "materiality.overall", "수행중요성": "materiality.performance",
               "명백히 사소한 금액": "materiality.trivial", "유의성 기준 금액": "analytics.sig_amount",
               "유의성 기준 비율": "analytics.sig_ratio", "설명 후 허용 차이": "analytics.tolerable_diff"}


def _inputs(d: Path, no: str) -> dict:
    from . import wp

    p = wp.path_for(Path(d), no)
    if not p.exists():
        return {}
    try:
        return {x["label"]: x["value"] for x in wp.readback(p)}
    except Exception:  # noqa: BLE001
        return {}


def view(d: Path) -> dict:
    """화면 「방법론」 한 장. {"sections": [{title, wp, rerun, rows: [...]}], "exists": {조서: bool}}."""
    from . import methodology, wp

    d = Path(d)
    ap = methodology.applied(d)
    M = methodology.load()["materiality"]
    choices = {"중요성 기준": [b["name"] for b in M["benchmarks"]],
               "수행중요성 비율": [f"{x * 100:g}%" for x in M["performance"]["choices"]],
               "명백히 사소한 금액 비율": [f"{x * 100:g}%" for x in M["trivial"]["choices"]]}
    secs = []
    for no, title in (("2700A", "2700A 중요성"), ("2120A", "2120A 유의성 기준")):
        vals = _inputs(d, no)
        rows = []
        for wno, label, unit, name in MAT_FIELDS:
            if wno != no:
                continue
            a = ap.get(APPLIED_KEY.get(label, "")) or {}
            rows.append({"key": f"{no}:{label}", "name": name, "unit": unit, "value": _plain(vals.get(label)),
                         "choices": choices.get(label), "applied": _plain(a.get("value")), "applied_from": a.get("from"),
                         "default": bool(a.get("default")), "wp": no})
        secs.append({"title": title, "wp": no, "rerun": "analyze", "rows": rows,
                     "exists": wp.path_for(d, no).exists()})
    cat = catalog()
    ovr = overrides(d)
    reasons = _inputs(d, NO)
    for g in cat["groups"]:
        rows = []
        for p in (x for x in cat["params"] if x["group"] == g["key"]):
            dv = default_of(p)
            ov = ovr.get(p["key"])
            rows.append({"key": p["key"], "name": p["name"], "unit": p["unit"], "choices": p.get("choices"),
                         "default_value": show(p, dv), "value": show(p, ov) if ov is not None else "",
                         "applied": show(p, ov if ov is not None else dv), "changed": ov is not None and ov != dv,
                         "grade": p["grade"], "basis": p.get("basis") or "", "wp": p["wp"],
                         "reason": _plain(reasons.get(REASON + p["key"]))})
        secs.append({"title": g["title"], "wp": NO, "rerun": g["rerun"], "rows": rows, "exists": wp.path_for(d, NO).exists()})
    return {"sections": secs}


def _plain(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer() and abs(v) >= 1:
        return int(v)
    return v


def save(d: Path, values: dict, reasons: dict | None = None, who: str = "화면") -> dict:
    """화면에서 고친 값을 노란 칸에 적는다. values 열쇠: 「2700A:<기입란>」 · 「2120A:<기입란>」 · 2700B key. 빈 글자는 칸을 비운다.
    {"wrote": [...], "errors": [...]}. 엑셀에서 열려 있어 저장하지 못하면 errors 에 그 뜻을 적는다."""
    from openpyxl import load_workbook

    from . import wp

    d = Path(d)
    by = catalog()["by_key"]
    plan: dict = {}
    errors = []
    for k, v in (values or {}).items():
        if ":" in k and k.split(":", 1)[0] in ("2700A", "2120A"):
            no, label = k.split(":", 1)
            plan.setdefault(no, {})[label] = v
        elif k in by:
            if v not in (None, "") and parse(by[k], v) is None:
                errors.append(f"{by[k]['name']}: 「{v}」 를 읽지 못했습니다({by[k]['unit']})")
                continue
            plan.setdefault(NO, {})[VALUE + k] = v
        else:
            errors.append(f"모르는 항목입니다: {k}")
    for k, v in (reasons or {}).items():
        if k in by:
            plan.setdefault(NO, {})[REASON + k] = v
    if NO in plan and not wp.path_for(d, NO).exists():
        make_wp(d)
    wrote = []
    for no, cells in plan.items():
        p = wp.path_for(d, no)
        if not p.exists():
            errors.append(f"{no} 조서가 아직 없습니다. 먼저 python -m audit analyze 를 돌려 주십시오")
            continue
        wb = load_workbook(p)
        at = {row[2]: (row[0], row[1]) for row in wb[wp.INPUT_SHEET].iter_rows(min_row=2, values_only=True) if row[0]}
        n = 0
        for label, v in cells.items():
            if label not in at:
                errors.append(f"{p.name} 에 「{label}」 칸이 없습니다")
                continue
            sh, ref = at[label]
            wb[sh][ref].value = None if v in (None, "") else v
            n += 1
        try:
            wb.save(p)
        except PermissionError:
            errors.append(f"{p.name} 이 엑셀에서 열려 있어 저장하지 못했습니다. 엑셀을 닫고 다시 저장해 주십시오")
            continue
        wrote.append(f"{p.relative_to(d).as_posix()} {n}칸({who})")
    if NO in plan and not any(e.startswith(f"{NO}") for e in errors):
        try:
            make_wp(d)                 # 적용값 열을 새 감사인 값으로 다시 그린다(감사인 값 · 사유는 이어받는다)
        except Exception as e:  # noqa: BLE001
            errors.append(f"2700B 를 다시 그리지 못했습니다: {e}")
    return {"wrote": wrote, "errors": errors}
