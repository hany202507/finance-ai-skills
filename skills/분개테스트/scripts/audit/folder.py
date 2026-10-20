"""감사 폴더 표준과 _색인(R0, 2026-10-05).

정본은 회계사 Drive 의 감사 폴더다(definitions/folder_standard.yaml). 이 모듈은 결정적으로 알 수 있는 것만 다룬다:
폴더 구조, 파일명 규칙, 회사제시 판, 해시, 조서번호. 문서 내용 판독(AI)과 다음 할 일 판단은 R1 의 맥락 색인·지휘 스킬 몫이다.

  scaffold(dir, company, fy_end, kind)  감사 폴더와 빈 _색인 을 만든다. 이미 있으면 건드리지 않는다
  scan(dir)                             파일을 훑어 _색인 을 다시 쓰고 보고를 돌려준다. 사람이 정한 상태·서명은 지킨다
  check(dir)                            표준과 다른 곳을 문장 목록으로 돌려준다
  validate_index(dir)                   _색인 네 파일을 definitions/index_schema.json 으로 검사한다
"""
import copy
import fnmatch
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from .errors import DefinitionError

DEFS = Path(__file__).resolve().parent.parent / "definitions"
INDEX_FILES = ("감사건.json", "문서목록.json", "조서목록.json", "이슈.json")
VERSION_RE = re.compile(r"_v(\d+\.\d+)(?=$|[_ .])")
PERIOD_RE = re.compile(r"(20\d\d)(?:[-.](0[1-9]|1[0-2]))?")
DONE = ("검사 통과", "검토 끝")


_YAML: dict = {}


def read_yaml(path: Path):
    """정의 파일(YAML)을 읽는다. 파일이 바뀌지 않았으면 다시 풀지 않고 사본을 돌려준다.
    엔진 명령 하나가 같은 정의 파일을 수백 번 읽는다(wp.path_for 가 조서마다 폴더 표준을 읽는다, 2026-10-12)."""
    p = Path(path)
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _YAML:
        _YAML[key] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return copy.deepcopy(_YAML[key])


def load_standard() -> dict:
    p = DEFS / "folder_standard.yaml"
    if not p.exists():
        raise DefinitionError(f"폴더 표준이 없습니다: {p}")
    return read_yaml(p)


def _schema() -> dict:
    """_색인 파일 이름 → JSON Schema. 단계마다 새 색인 파일은 index_schema_<단계>.json 에 따로 둔다(R2~R5)."""
    out = json.loads((DEFS / "index_schema.json").read_text(encoding="utf-8"))
    for extra in sorted(DEFS.glob("index_schema_*.json")):
        out.update(json.loads(extra.read_text(encoding="utf-8")))
    return out


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _folders(std: dict) -> list[dict]:
    return std["folders"]


def _wp_folder_map(std: dict) -> dict[str, str]:
    """조서번호 → 하위 폴더 이름."""
    out = {}
    for f in _folders(std):
        for no in f.get("workpapers", []):
            out[str(no)] = f["path"]
    return out


AREA_NO = r"4000[A-Z]+\d*"          # 4000 영역 조서번호. 영문 코드 뒤 숫자도 받는다(한공회 영역 E100 재고실사입회, 2026-10-12)


def _is_area(no: str) -> bool:
    return bool(re.fullmatch(AREA_NO, no))


def match_workpaper(stem: str, numbers: list[str]) -> str | None:
    """파일 이름(확장자 뺀)에서 조서번호를 찾는다. 긴 번호부터 본다(3600-JET 이 3600 보다 먼저)."""
    for no in sorted(numbers, key=len, reverse=True):
        if not stem.startswith(no):
            continue
        rest = stem[len(no):]
        if rest == "" or rest[0] in "_ .-" or not re.match(r"[0-9A-Za-z]", no[-1]):
            return no
    m = re.match(rf"({AREA_NO})(?=$|[_ .])", stem)
    return m.group(1) if m else None


def _ignored(name: str, std: dict) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in std.get("ignore", []))


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _received_kind(sub: dict | None, name: str) -> tuple[str, str, bool]:
    """받은자료 파일의 종류. (kind, basis, confirmed). 하위 폴더의 종류가 하나면 폴더로, 여럿이면 파일 이름의 열쇠말로 정한다."""
    if sub is None:
        return "분류 전", "폴더", False
    kinds = [k if isinstance(k, dict) else {"name": k, "keys": [k.split()[0]]} for k in sub["kinds"]]
    if len(kinds) == 1:
        return kinds[0]["name"], "폴더", True
    for k in kinds:
        if any(key and key in name for key in k.get("keys", [])):
            return k["name"], "파일명", True
    return f"{sub['path']} (종류 판독 필요)", "폴더", False


def _carry(entry: dict, old: dict) -> None:
    """내용이 같은 파일이면 앞서 붙인 판독을 이어받는다: 엔진 · AI 판별과 사람이 확인한 것, 사실, 연결 조서, 기간, 다시 확인 표시.
    받은자료와 영구조서가 같은 규칙을 쓴다(영구조서 AI 판독이 다음 index read 때 지워지던 것을 고침, 2026-10-18)."""
    if old.get("kind_basis") in ("엔진", "AI") or (old.get("confirmed") and not entry["confirmed"]):
        entry.update(kind=old["kind"], kind_basis=old["kind_basis"], confirmed=old["confirmed"])
    elif any(x.get("basis") == "AI" for x in old.get("facts") or []):
        entry["confirmed"] = old["confirmed"]  # AI 사실이 붙은 파일은 회계사 확인 여부를 그대로 둔다
    for k in ("facts", "linked_workpapers", "read_error", "needs_recheck"):
        if old.get(k):
            entry[k] = old[k]
    # 회계사가 확인한 OCR 값은 같은 파일(해시)일 때만 잇는다. 파일이 바뀌면 확인이 풀린다(2026-10-18)
    if old.get("ocr_confirmed") and old.get("sha256") == entry.get("sha256"):
        entry["ocr_confirmed"] = old["ocr_confirmed"]
    # 같은 파일이면 앞서 엔진 · AI · 사람이 바로잡은 기간을 지킨다(파일 이름 기간으로 되돌리지 않는다)
    if old.get("period"):
        entry["period"] = old["period"]


def _has_reading(old: dict) -> bool:
    """사람 · AI 가 판독을 넣은 파일인가. AI 사실이 있거나, 판독으로 종류를 정했거나, 연결 조서가 붙어 있다."""
    return bool(any(x.get("basis") == "AI" for x in old.get("facts") or []) or old.get("kind_basis") == "AI"
                or old.get("linked_workpapers"))


def _active(f: dict, d: Path) -> bool:
    """선택 폴더(그룹감사 등)는 만들어져 있을 때만 표준에 든다."""
    return not f.get("optional") or (d / f["path"]).is_dir()


def _conditional_ok(no: str, std: dict, case: dict) -> bool:
    cond = {str(k): v for k, v in std.get("conditional", {}).items()}.get(no)
    if cond is None:
        return True
    return cond == "초도감사" and case.get("engagement_kind") == "초도감사"


REVIEW_RE = re.compile(r"^검토의견_(.+?)\.(xlsx|xlsm)$")
INPUT_FILES = ("감사반인원.xlsx",)
EXT_RANK = {".xlsx": 3, ".xlsm": 3, ".docx": 2, ".html": 1}


def _main_key(entry: dict, no: str, names: dict) -> tuple:
    """같은 조서번호 파일이 여럿일 때 조서 본체를 고르는 순서: 회사제시 판 → 엑셀 · 워드 · HTML(검사할 수 있는 엑셀이 본체) → 표준 이름 → 이름순."""
    stem = Path(entry["path"]).stem
    std_name = f"{no}_{names[no]}" if names.get(no) else no
    standard = stem == std_name or stem.startswith(std_name + "_v")
    return (_version_key((entry["version"] or "v0")[1:]), EXT_RANK.get(Path(entry["path"]).suffix.lower(), 0), standard,
            tuple(-ord(c) for c in Path(entry["path"]).name))


def _version_key(v: str | None) -> tuple:
    return tuple(int(x) for x in v.split(".")) if v else (0,)


# ---------------------------------------------------------------- 만들기
def fiscal_start(case: dict) -> date:
    """사업연도 시작일. 감사건.json 의 fiscal_year_start(반기 · 짧은 사업연도, R8)가 있으면 그것, 없으면 결산일 1년 전 다음 날."""
    if case.get("fiscal_year_start"):
        return date.fromisoformat(case["fiscal_year_start"])
    e = date.fromisoformat(case["fiscal_year_end"])
    try:
        return e.replace(year=e.year - 1) + timedelta(days=1)
    except ValueError:                       # 2월 29일 결산
        return date(e.year - 1, 3, 1)


def periods(case: dict) -> dict:
    """당기 · 전기 기간(R9). 당기 시작은 fiscal_start, 전기말은 그 전날, 전기 시작은 전기말 1년 전 다음 날.
    분석(audit.analysis.data)과 같은 규칙이라 보고 문서 · dsd · 시작 자료의 기간이 분석 기간과 어긋나지 않는다."""
    e = date.fromisoformat(str(case["fiscal_year_end"])[:10])
    s = fiscal_start(case)
    pe = s - timedelta(days=1)
    try:
        ps = pe.replace(year=pe.year - 1) + timedelta(days=1)
    except ValueError:                       # 2월 29일
        ps = date(pe.year - 1, 3, 1)
    return {"cur_start": s, "cur_end": e, "prior_start": ps, "prior_end": pe}


def scaffold(engagement_dir: Path, company: str, fiscal_year_end: str, kind: str = "계속감사", now: str | None = None,
             fiscal_year_start: str | None = None) -> Path:
    """fiscal_year_start: 반기 · 짧은 사업연도의 시작일(없으면 결산일 1년 전 다음 날로 본다, R8)."""
    std = load_standard()
    d = Path(engagement_dir)
    for f in _folders(std):
        if f.get("optional"):
            continue
        (d / f["path"]).mkdir(parents=True, exist_ok=True)
        for c in f.get("children", []):
            (d / f["path"] / c["path"]).mkdir(parents=True, exist_ok=True)
    (d / std["permanent"]["path"]).resolve().mkdir(parents=True, exist_ok=True)   # 회사 단위 영구조서
    idx = d / "_색인"
    at = now or _now()
    init = {
        "감사건.json": {"format_version": 1, "company": {"name": company, "dart_corp_code": None, "industry": None, "basis": "폴더 이름"},
                      "fiscal_year_end": fiscal_year_end, "engagement_kind": kind, "company_version": None, "stage": "준비",
                      "indexed_at": at, "next_actions": [], "log": [{"at": at, "who": "폴더", "what": "감사 폴더를 표준대로 만들었습니다"}]},
        "문서목록.json": {"format_version": 1, "indexed_at": at, "files": [], "missing": [], "warnings": []},
        "조서목록.json": {"format_version": 1, "workpapers": []},
        "이슈.json": {"format_version": 1, "issues": []},
    }
    if fiscal_year_start:
        if not date.fromisoformat(fiscal_year_start) <= date.fromisoformat(fiscal_year_end):
            raise ValueError(f"사업연도 시작일 {fiscal_year_start} 이 결산일 {fiscal_year_end} 보다 뒤입니다")
        init["감사건.json"]["fiscal_year_start"] = fiscal_year_start
    for name, data in init.items():
        if not (idx / name).exists():
            _write(idx / name, data)
    scan(d, now=at, quiet_log=True)
    return d


# ---------------------------------------------------------------- 훑기
def scan(engagement_dir: Path, now: str | None = None, quiet_log: bool = False) -> dict:
    std = load_standard()
    d = Path(engagement_dir)
    idx = d / "_색인"
    idx.mkdir(exist_ok=True)
    at = now or _now()
    case = _read(idx / "감사건.json", None)
    if case is None:
        raise DefinitionError(f"_색인/감사건.json 이 없습니다. 먼저 scaffold 로 감사 폴더를 만드십시오: {d}")
    old_docs = {f["path"]: f for f in _read(idx / "문서목록.json", {"files": []})["files"]}
    old_wps = {w["no"]: w for w in _read(idx / "조서목록.json", {"workpapers": []})["workpapers"]}
    old_missing = _read(idx / "문서목록.json", {"missing": []}).get("missing", [])

    folders = {f["path"]: f for f in _folders(std)}
    wp_folder = _wp_folder_map(std)
    numbers = list(wp_folder)
    names = {str(k): v for k, v in std.get("workpaper_names", {}).items()}
    uses = {str(x) for x in std.get("uses_company_figures", [])}

    files, warnings, found_wp = [], [], {}
    perm = (d / std["permanent"]["path"]).resolve()
    perm_items = {str(k): v for k, v in std["permanent"]["items"].items()}
    if perm.is_dir():
        for p in sorted(perm.rglob("*")):
            if p.is_dir() or _ignored(p.name, std):
                continue
            rel = "../영구조서/" + p.relative_to(perm).as_posix()
            m = re.match(r"(\d{3})(?=$|[_ .])", p.stem)
            ym = re.search(r"_(20\d\d)(?=$|[_ .])", p.stem)
            known = bool(m and m.group(1) in perm_items)
            entry = {"path": rel, "sha256": _sha(p), "size": p.stat().st_size,
                     "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                     "role": "permanent", "folder_kind": None, "kind": perm_items[m.group(1)] if known else "영구조서(번호 없음)",
                     "kind_basis": "파일명", "confirmed": known, "version": None, "period": ym.group(1) if ym else None,
                     "workpaper": None, "facts": [], "linked_workpapers": []}
            old = old_docs.get(rel)
            if old and old["sha256"] == entry["sha256"]:
                _carry(entry, old)
            elif old and _has_reading(old):
                # 판독한 뒤 파일이 바뀌었다. 앞 판독은 지우지 않고 확인 전으로 돌려 「다시 확인」 을 붙인다(2026-10-18)
                _carry(entry, old)
                entry.update(confirmed=False, needs_recheck=True)
                warnings.append(f"영구조서 파일 내용이 판독 뒤에 바뀌었습니다. 앞 판독을 다시 확인해 주십시오: {rel}")
            files.append(entry)
            if not known:
                warnings.append(f"영구조서 파일은 한공회 번호(110~450)로 시작하게 해 주십시오: {rel}")
    for p in sorted(d.rglob("*")):
        if p.is_dir() or _ignored(p.name, std):
            continue
        rel = p.relative_to(d).as_posix()
        parts = rel.split("/")
        top = parts[0]
        if top == "_색인" or (folders.get(top) or {}).get("role") == "versions":
            continue                         # _판(수정 반영 판)은 받은자료도 조서도 아니다
        entry = {"path": rel, "sha256": _sha(p), "size": p.stat().st_size,
                 "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                 "role": "unknown", "folder_kind": None, "kind": "알 수 없음", "kind_basis": "폴더", "confirmed": False,
                 "version": None, "period": None, "workpaper": None, "facts": [], "linked_workpapers": []}
        vm = VERSION_RE.search(p.stem)
        entry["version"] = f"v{vm.group(1)}" if vm else None
        f = folders.get(top)
        if len(parts) == 1:
            warnings.append(f"감사 폴더 맨 위에 파일이 있습니다. 알맞은 하위 폴더로 옮겨 주십시오: {rel}")
        elif f is None:
            warnings.append(f"표준에 없는 폴더의 파일입니다: {rel}")
        elif f["role"] == "received":
            sub = next((c for c in f.get("children", []) if len(parts) > 2 and c["path"] == parts[1]), None)
            if sub is None:
                warnings.append(f"받은자료는 하위 폴더(회사제시 · 분개장 · 세무신고 등)에 넣어 주십시오: {rel}")
            kind, basis, ok = _received_kind(sub, p.name)
            pm = PERIOD_RE.search(p.stem)
            entry.update(role="received", folder_kind=sub["path"] if sub else None, kind=kind, kind_basis=basis, confirmed=ok,
                         period=(pm.group(1) + (f"-{pm.group(2)}" if pm.group(2) else "")) if pm else None)
            if sub and sub.get("versioned") and not entry["version"]:
                warnings.append(f"회사제시 파일 이름 끝에 판을 붙여 주십시오(_v1.1 등): {rel}")
        elif f["role"] == "workpapers":
            rm = REVIEW_RE.match(p.name)
            sub_no = match_workpaper(parts[1], numbers) if len(parts) > 2 else None
            no = match_workpaper(p.stem, numbers) or sub_no
            if rm:
                # 감사반 동료 검토의견(naming.review). 조서 본체가 아니라 그 조서의 검토 기록이다
                entry.update(role="workpapers", workpaper=None, kind="검토의견", kind_basis="파일명", confirmed=True,
                             linked_workpapers=[rm.group(1)])
            elif p.name in INPUT_FILES:
                entry.update(role="workpapers", workpaper=None, kind="입력 자료", kind_basis="파일명", confirmed=True)
            elif len(parts) > 2 or p.suffix.lower() in (".txt", ".csv"):
                # 조서 하위 폴더의 초안(조회서 워드 · 메일 초안)과 메일 초안 .txt 는 그 조서의 부속 파일이다
                entry.update(role="workpapers", workpaper=None, kind="조서 부속" if no else "조서 아님", kind_basis="파일명",
                             confirmed=bool(no), linked_workpapers=[no] if no else [])
                if no is None:
                    warnings.append(f"조서번호로 시작하지 않는 파일입니다: {rel}")
            else:
                entry.update(role="workpapers", workpaper=no, kind="조서" if no else "조서 아님", kind_basis="파일명", confirmed=bool(no))
                if no is None:
                    warnings.append(f"조서번호로 시작하지 않는 파일입니다: {rel}")
                else:
                    if not _is_area(no) and wp_folder.get(no) != top:
                        warnings.append(f"{no} 는 '{wp_folder.get(no)}' 폴더 조서입니다: {rel}")
                    cur = found_wp.get(no)
                    if cur is None or _main_key(entry, no, names) > _main_key(cur, no, names):
                        found_wp[no] = entry
        elif f["role"] == "archive":
            entry.update(role="archive", kind="보관본", kind_basis="폴더", confirmed=True)
        old = old_docs.get(rel)
        if old and old["sha256"] == entry["sha256"]:
            _carry(entry, old)
        files.append(entry)

    # 회사제시 판: 회사제시 폴더 파일 중 가장 높은 판
    vers = [f["version"] for f in files if f["role"] == "received" and f["folder_kind"] == "회사제시" and f["version"]]
    company_version = max(vers, key=lambda v: _version_key(v[1:])) if vers else None

    # 조서목록
    wps = []
    seen = set()
    for top_path, f in folders.items():
        if not _active(f, d):
            continue
        for no in [str(x) for x in f.get("workpapers", [])]:
            if _is_area(no) and no not in found_wp and no not in old_wps:
                continue
            if not _conditional_ok(no, std, case) and no not in found_wp:
                continue
            wps.append(no)
            seen.add(no)
    for no in found_wp:
        if no not in seen:
            wps.append(no)
    out_wps, rechecked = [], []
    assigned = (_read(idx / "배정.json", {}) or {}).get("assignments") or {}      # 스태프 배정(audit/assign.py, 2026-10-12)
    for no in wps:
        old = old_wps.get(no, {})
        fe = found_wp.get(no)
        w = {"no": no, "name": names.get(no, old.get("name", no)), "folder": wp_folder.get(no, "30 실행"),
             "file": fe["path"] if fe else None, "sha256": fe["sha256"] if fe else None, "version": fe["version"] if fe else None,
             "status": old.get("status", "없음"), "status_basis": old.get("status_basis", ""), "signs": old.get("signs", {"작성": None, "검토": None}),
             "why": old.get("why", "필수" if not _is_area(no) else ""), "needs_recheck": old.get("needs_recheck", False)}
        if fe is None:
            if w["status"] != "없음":
                w.update(status="없음", status_basis="파일 없음", needs_recheck=False, signs={"작성": None, "검토": None})
        elif w["status"] == "없음":
            w.update(status="초안", status_basis="파일 있음")
        elif old.get("sha256") and old["sha256"] != fe["sha256"] and w["status"] in DONE:
            # 검사·검토가 끝난 뒤 파일이 바뀌었으면 다시 확인한다
            w.update(status="작성중", status_basis="파일이 바뀜", needs_recheck=True, signs={"작성": None, "검토": None})
            rechecked.append(no)
        if company_version and case.get("company_version") and company_version != case["company_version"] and no in uses and w["status"] in DONE:
            w.update(status="작성중", status_basis=f"회사제시 {company_version}", needs_recheck=True, signs={"작성": None, "검토": None})
            rechecked.append(no)
        if assigned.get(no):
            w["assign"] = assigned[no]
        out_wps.append(w)

    new_files = [f["path"] for f in files if f["path"] not in old_docs]
    changed = [f["path"] for f in files if f["path"] in old_docs and old_docs[f["path"]]["sha256"] != f["sha256"]]
    gone = [p for p in old_docs if p not in {f["path"] for f in files}]
    version_changed = bool(case.get("company_version") and company_version and company_version != case["company_version"])

    docs = {"format_version": 1, "indexed_at": at, "files": files, "missing": old_missing, "warnings": warnings}
    _write(idx / "문서목록.json", docs)
    _write(idx / "조서목록.json", {"format_version": 1, "workpapers": out_wps})
    prev_version = case.get("company_version")
    case["company_version"] = company_version
    case["indexed_at"] = at
    if not quiet_log:
        what = f"파일 {len(files)}개를 훑었습니다. 새 파일 {len(new_files)}, 바뀐 파일 {len(changed)}, 없어진 파일 {len(gone)}, 확인 필요 {sum(1 for f in files if not f['confirmed'])}"
        if version_changed:
            what += f". 회사제시 판이 {prev_version} 에서 {company_version} 가 됐습니다"
        if rechecked:
            what += f". 다시 확인으로 돌린 조서 {', '.join(sorted(set(rechecked)))}"
        case["log"].insert(0, {"at": at, "who": "색인", "what": what, "read": new_files + changed, "wrote": [f"_색인/{n}" for n in INDEX_FILES[:3]]})
    _write(idx / "감사건.json", case)
    validate_index(d)
    return {"files": len(files), "new": new_files, "changed": changed, "gone": gone, "warnings": warnings,
            "company_version": company_version, "version_changed": version_changed, "rechecked": sorted(set(rechecked)),
            "unconfirmed": [f["path"] for f in files if not f["confirmed"]]}


# ---------------------------------------------------------------- 점검
def check(engagement_dir: Path) -> list[str]:
    std = load_standard()
    d = Path(engagement_dir)
    problems = []
    if not (d / std["permanent"]["path"]).resolve().is_dir():
        problems.append("회사 폴더에 영구조서 폴더가 없습니다: ../영구조서")
    for f in _folders(std):
        if not _active(f, d):
            continue
        if not (d / f["path"]).is_dir():
            problems.append(f"폴더가 없습니다: {f['path']}")
        for c in f.get("children", []):
            if not (d / f["path"] / c["path"]).is_dir():
                problems.append(f"폴더가 없습니다: {f['path']}/{c['path']}")
    for name in INDEX_FILES:
        if not (d / "_색인" / name).exists():
            problems.append(f"색인 파일이 없습니다: _색인/{name}")
    if not problems:
        problems += _read(d / "_색인" / "문서목록.json", {"warnings": []}).get("warnings", [])
    return problems


def validate_index(engagement_dir: Path) -> None:
    import jsonschema

    schema = _schema()
    d = Path(engagement_dir) / "_색인"
    for name in schema:
        p = d / name
        if p.exists():
            try:
                jsonschema.validate(_read(p, None), schema[name])
            except jsonschema.ValidationError as e:
                path = "/".join(str(x) for x in e.absolute_path)
                raise DefinitionError(f"_색인/{name} 형식 오류({path}): {e.message}") from None
