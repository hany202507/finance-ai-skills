"""사람이 정한 기록(_기록, 2026-10-22). 설계: docs/specs/2026-10-22-감사-실행폴더-기획.md 2 · 4절.

감사 폴더(회계사 Drive) `_기록/확인_<이름>.jsonl` 에 사람마다 줄을 더하기만 한다. Drive 는 두 사람이 같은 파일을 동시에 고치면
「(1)」 사본을 만들기 때문에 각자 자기 파일에만 쓴다. `_색인` 은 지워도 다시 만드는 사본이고, 사람이 정한 것은 여기에 남는다.
엔진은 `_색인` 을 다시 만들 때(folder.scan) 이 줄을 읽어 확인을 다시 입힌다. 파일 해시가 바뀌었으면 입히지 않고 「다시 확인」 으로 둔다.
`_기록` 은 색인 · 조서목록에 넣지 않고 보관본에는 넣는다(누가 언제 무엇을 확인했는지는 감사조서의 일부다). AI 는 여기에 쓰지 않는다.

줄 하나: at · by · what · target · sha256(확인한 파일이나 정산표 숫자의 해시) · value(확인 · 고친 내용)

  add(d, by, what, target, sha256=None, value=None)   줄 하나. by 는 감사반 인원(1000 감사계약/감사반인원.xlsx)에 있는 이름만
  lines(d)                                            모든 사람 파일의 줄, 시각 순
  reapply(d, files)                                   folder.scan 이 만든 파일 항목에 판독 확인 · 고침 · OCR 값 확인을 다시 입힌다
  questions(d)                                        답이 없는 「회사에 묻기」(빠진 자료로 간다)
  sent_items(d)                                       「요청 메일 보냄」 줄의 항목별 보낸 날(색인을 다시 만들 때 요청한 날을 되살린다)
  company_fields(d)                                   회사정보 확인 · 고침(start 가 AI 판독 자리에 사람 판독으로 넣는다)
  wtb_hash(res) · wtb_confirmed(d, res)               정산표 숫자(계정 · 표시과목 · 당기 · 전기) 해시와 그 해시의 「정산표 확인」 줄
  confirm_files · confirm_ocr · confirm_company · ask_company · confirm_wtb   화면 「판독 확인」 단추가 부르는 엔진 함수

이벤트(2026-10-23, 에이전트 구성 계획 T2): 누가 무엇을 시켰고 누가 끝냈는지를 `_기록/이벤트_<PC>.jsonl` 에 PC 마다 더하기만 한다.
사람 기록(확인_*)과 달리 화면 · 감시기 · 에이전트가 쓴다. 엔진 명령 자체의 기록은 그대로 `_색인/실행기록.json` · 감사건.json log 에 있고,
화면 기록 탭이 둘을 시각순으로 합쳐 보인다. `_작업` 을 지워도 이벤트의 work_dir 은 그대로 둔다(폴더는 없고 기록만 남는다).

줄 하나: at · pc · from · to · type(요청 · 결과 · 알림 · 실패 · 취소) · target · text · cost_usd · seconds · work_dir · denied

  event(d, src, dst, type, text, target=None, cost_usd=None, seconds=None, work_dir=None, denied=None)   줄 하나
  events(d)                                           모든 PC 파일의 이벤트, 시각 순
  month_cost(d, month=None)                           그 달(YYYY-MM, 기본 이번 달) 이벤트 cost_usd 합
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

DIR = "_기록"
PREFIX = "확인_"
FILE_WHATS = ("판독 확인", "판독 고침", "회사에 묻기")
WHATS = FILE_WHATS + ("OCR 값 확인", "회사정보 확인", "정산표 확인", "요청 메일 보냄")
NAME_RE = re.compile(r"^[^\\/:*?\"<>|\s.]{1,20}$")
WTB = "8100B"
EVENT_PREFIX = "이벤트_"
EVENT_TYPES = ("요청", "결과", "알림", "실패", "취소")
PARTIES = ("회계사", "화면", "감시기", "지휘", "판독", "묶음", "점검", "문안", "엔진")
_CACHE: dict = {}


class RecordError(ValueError):
    pass


def _now() -> str:
    """밀리초까지 둔다. 사람마다 파일이 따로라 줄 순서를 시각으로만 정한다(나중 줄이 이긴다)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:23]


def _stamp(paths) -> tuple:
    out = []
    for p in paths:
        try:
            s = p.stat()
            out.append((str(p), s.st_mtime_ns, s.st_size))
        except OSError:
            out.append((str(p), None, None))
    return tuple(out)


def _cached(key: str, paths, load):
    """파일 시각 · 크기가 같으면 다시 읽지 않는다(화면 /api/case 가 매번 xlsx 와 _기록 을 읽어 2초 걸렸다, 2026-10-23 T3)."""
    stamp = _stamp(paths)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    val = load()
    _CACHE[key] = (stamp, val)
    return val


def people(d: Path) -> list[str]:
    from . import checklists

    d = Path(d)
    p = checklists.people_path(d)
    return list(_cached(f"people:{d.resolve()}", [p], lambda: [x["name"] for x in checklists.people(d)[0]]))


def check_name(d: Path, by) -> str:
    """기록에 남길 이름. 감사반 인원에 있는 이름만 받는다."""
    if not isinstance(by, str) or not by.strip():
        raise RecordError("「내 이름」 이 없습니다. 화면 맨 위 「내 이름」 에서 감사반 인원 가운데 하나를 골라 주십시오")
    by = by.strip()
    names = people(d)
    if not names:
        raise RecordError("감사반 인원이 없습니다. 1000 감사계약/감사반인원.xlsx 에 성명을 적어 주십시오")
    if by not in names or not NAME_RE.match(by):
        raise RecordError(f"「{by}」 은 이 감사의 감사반 인원({' · '.join(names)})에 없습니다")
    return by


def path_for(d: Path, by: str) -> Path:
    return Path(d) / DIR / f"{PREFIX}{by}.jsonl"


def add(d: Path, by: str, what: str, target: str, sha256: str | None = None, value=None, at: str | None = None) -> dict:
    if what not in WHATS:
        raise RecordError(f"기록할 수 없는 일입니다: {what}")
    if not isinstance(target, str) or not target:
        raise RecordError("기록 대상이 없습니다")
    by = check_name(d, by)
    line = {"at": at or _now(), "by": by, "what": what, "target": target}
    if sha256:
        line["sha256"] = sha256
    if value is not None:
        line["value"] = value
    p = path_for(d, by)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:      # 더하기만 한다
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def lines(d: Path) -> list[dict]:
    """`_기록/확인_*.jsonl` 의 줄 전부(Drive 충돌 사본 「확인_김 (1).jsonl」 도 읽고 같은 줄은 하나로). 깨진 줄은 건너뛴다."""
    base = Path(d) / DIR
    if not base.is_dir():
        return []
    paths = sorted(base.glob(f"{PREFIX}*.jsonl"))
    return [dict(x) for x in _cached(f"lines:{base.resolve()}", paths, lambda: _read_lines(paths, WHATS))]


def _read_lines(paths: list[Path], whats) -> list[dict]:
    out, seen = [], set()
    for p in paths:
        try:
            raw_lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in raw_lines:
            if not raw.strip() or raw in seen:
                continue
            seen.add(raw)
            try:
                x = json.loads(raw)
            except ValueError:
                continue
            if whats is None:
                if isinstance(x, dict) and x.get("type") in EVENT_TYPES and isinstance(x.get("at"), str):
                    out.append(x)
            elif isinstance(x, dict) and x.get("what") in whats and isinstance(x.get("target"), str):
                out.append(x)
    out.sort(key=lambda x: str(x.get("at") or ""))
    return out


# ---------------------------------------------------------------- 이벤트 (2026-10-23 T2)
def event_path(d: Path, pc: str | None = None) -> Path:
    if pc is None:
        from .ui import settings

        pc = settings.pc_name()
    return Path(d) / DIR / f"{EVENT_PREFIX}{pc}.jsonl"


def event(d: Path, src: str, dst: str, type: str, text: str, target: str | None = None, cost_usd=None, seconds=None,  # noqa: A002
          work_dir: str | None = None, denied: int | None = None, at: str | None = None, pc: str | None = None) -> dict:
    """이벤트 한 줄을 `_기록/이벤트_<PC>.jsonl` 에 더한다. src · dst 는 회계사 · 화면 · 감시기 · 지휘 · 판독 · 묶음 · 점검 · 문안 · 엔진.
    회계사는 이름을 함께 적을 수 있다(「회계사 김하늘」). 숫자(cost_usd · seconds · denied)는 있을 때만 적는다."""
    if type not in EVENT_TYPES:
        raise RecordError(f"이벤트 종류가 아닙니다: {type} ({' · '.join(EVENT_TYPES)})")
    for who in (src, dst):
        if not isinstance(who, str) or not who.strip() or who.split()[0] not in PARTIES:
            raise RecordError(f"이벤트의 누가(from · to)는 {' · '.join(PARTIES)} 가운데 하나여야 합니다: {who}")
    if not isinstance(text, str):
        raise RecordError("이벤트 내용(text)은 글자여야 합니다")
    p = event_path(d, pc)
    line = {"at": at or _now(), "pc": p.name[len(EVENT_PREFIX):-len(".jsonl")], "from": src.strip(), "to": dst.strip(), "type": type,
            "target": target if isinstance(target, str) and target else None, "text": text.strip()[:500]}
    for k, v in (("cost_usd", cost_usd), ("seconds", seconds), ("denied", denied)):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            line[k] = round(float(v), 4) if k == "cost_usd" else int(v)
    if isinstance(work_dir, str) and work_dir:
        line["work_dir"] = work_dir
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:      # 더하기만 한다
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def events(d: Path) -> list[dict]:
    """`_기록/이벤트_*.jsonl` 전부(여러 PC · Drive 충돌 사본 포함, 같은 줄은 하나로), 시각 순."""
    base = Path(d) / DIR
    if not base.is_dir():
        return []
    paths = sorted(base.glob(f"{EVENT_PREFIX}*.jsonl"))
    return [dict(x) for x in _cached(f"events:{base.resolve()}", paths, lambda: _read_lines(paths, None))]


def month_cost(d: Path, month: str | None = None) -> float:
    """그 달 이벤트의 cost_usd 합(달러). month 는 YYYY-MM, 기본 이번 달."""
    month = month or datetime.now().strftime("%Y-%m")
    return round(sum(float(x.get("cost_usd") or 0) for x in events(d) if str(x.get("at") or "").startswith(month)), 4)


def _last_by_target(recs: list[dict], whats) -> dict[str, dict]:
    last: dict[str, dict] = {}
    for x in recs:
        if x["what"] in whats:
            last[x["target"]] = x            # 시각 순이라 나중 줄이 이긴다
    return last


def _texts(facts) -> list[str]:
    return sorted(str(x.get("text") or "") for x in facts or [] if x.get("basis") == "AI")


def reapply(d: Path, files: list[dict]) -> dict:
    """색인을 다시 만들 때 사람 기록을 다시 입힌다. {applied, recheck, ocr}.
    - 판독 확인 · 고침: 기록의 해시가 지금 파일과 같고 지금 항목이 확인 전이면, 기록한 종류 · 기간 · AI 사실을 되살리고 확인으로 둔다.
      지금 항목에 기록과 다른 AI 사실이 있으면(AI 가 뒤에 다시 읽음) 그 새 판독은 사람이 아직 안 봤으므로 확인으로 두지 않는다.
    - 해시가 다르면(확인한 뒤 파일이 바뀜) 확인하지 않고 「다시 확인」 으로 둔다.
    - OCR 값 확인: 해시가 같을 때만 ocr_confirmed 로 되살린다(파일이 바뀌면 풀린다, folder._carry 와 같은 규칙)."""
    recs = lines(d)
    out = {"applied": [], "recheck": [], "ocr": 0}
    if not recs:
        return out
    by_path = {f["path"]: f for f in files}
    for path, x in _last_by_target(recs, FILE_WHATS).items():
        f = by_path.get(path)
        if f is None or x["what"] == "회사에 묻기":
            continue
        if x.get("sha256") and x["sha256"] != f.get("sha256"):
            if f.get("confirmed") and f.get("confirmed_by"):
                f["confirmed"] = False
            f["needs_recheck"] = True
            out["recheck"].append(path)
            continue
        v = x.get("value") if isinstance(x.get("value"), dict) else {}
        rec_facts = [{"text": t.get("text"), "source_page": t.get("source_page"), "basis": "AI"} for t in v.get("facts") or []
                     if isinstance(t, dict) and t.get("text")]
        now_ai = _texts(f.get("facts"))
        if now_ai and now_ai != _texts(rec_facts):
            continue                         # AI 가 확인 뒤에 다시 읽었다. 새 판독은 확인 전으로 둔다
        if not now_ai and rec_facts:
            f["facts"] = [x2 for x2 in f.get("facts") or [] if x2.get("basis") == "엔진"] + [
                {k: val for k, val in t.items() if val is not None} for t in rec_facts]
        if v.get("kind") and f.get("kind_basis") != "엔진":
            f["kind"] = v["kind"]
            if f.get("kind_basis") not in ("폴더", "파일명"):
                f["kind_basis"] = "AI"
        if v.get("period"):
            f["period"] = v["period"]
        if not f.get("confirmed") or not f.get("confirmed_by"):
            f.update(confirmed=True, confirmed_by=x["by"], confirmed_at=x["at"])
            f.pop("needs_recheck", None)
            out["applied"].append(path)
    ocr: dict[tuple, dict] = {}
    for x in recs:
        v = x.get("value")
        if x["what"] == "OCR 값 확인" and isinstance(v, dict) and isinstance(v.get("item"), str):
            ocr[(x["target"], v["item"])] = x
    for (path, item), x in ocr.items():
        f = by_path.get(path)
        if f is None or x.get("sha256") != f.get("sha256"):
            continue
        if any(c.get("item") == item for c in f.get("ocr_confirmed") or []):
            continue                         # 색인에 이미 있다(같은 해시면 folder._carry 가 이었다)
        f["ocr_confirmed"] = list(f.get("ocr_confirmed") or []) + [
            {"item": item, "value": x["value"]["value"], "by": x["by"], "at": x["at"], "sha256": f["sha256"]}]
        out["ocr"] += 1
    return out


def questions(d: Path) -> list[dict]:
    """「회사에 묻기」 가운데 아직 답이 없는 것. 같은 파일에 뒤에 판독 확인 · 고침 줄이 있으면 답한 것으로 본다."""
    out = []
    for path, x in _last_by_target(lines(d), FILE_WHATS).items():
        if x["what"] != "회사에 묻기":
            continue
        v = x.get("value") if isinstance(x.get("value"), dict) else {}
        out.append({"target": path, "question": str(v.get("question") or "").strip(), "by": x["by"], "at": x["at"],
                    "workpaper": v.get("workpaper")})
    return out


def question_item(q: dict) -> str:
    """빠진 자료 줄 글. 요청 메일에 그대로 들어간다."""
    name = Path(q["target"]).name
    return f"{name} 확인 요청: {q['question']}" if q["question"] else f"{name} 내용 확인 요청"


def sent_items(d: Path) -> dict[str, str]:
    """「요청 메일 보냄」 줄의 항목 → 처음 보낸 날."""
    out: dict[str, str] = {}
    for x in lines(d):
        v = x.get("value")
        if x["what"] == "요청 메일 보냄" and isinstance(v, dict):
            for it in v.get("items") or []:
                if isinstance(it, str):
                    out.setdefault(it, str(v.get("date") or x["at"][:10]))
    return out


def company_fields(d: Path) -> list[dict]:
    """회사정보 확인 · 고침 줄을 start 의 사람 판독 꼴로. 같은 칸은 나중 줄."""
    out = []
    for field, x in _last_by_target([r for r in lines(d) if r["what"] == "회사정보 확인"], ("회사정보 확인",)).items():
        v = x.get("value") if isinstance(x.get("value"), dict) else {}
        if "value" in v:
            out.append({"field": field, "value": v["value"], "basis": "사람", "source_page": v.get("source_page") or f"{x['by']} {x['at'][:10]}"})
    return out


# ---------------------------------------------------------------- 정산표
def wtb_rows(res: dict) -> list[list]:
    return sorted([str(a.get("code") or ""), str(a.get("name") or ""), str(a.get("line") or ""), a.get("cur"), a.get("prior")]
                  for a in (res or {}).get("accounts") or [])


def wtb_hash(res: dict) -> str | None:
    """정산표 숫자(계정코드 · 계정 · 표시과목 · 당기 · 전기)의 해시. 엔진이 8100B 엑셀을 다시 써도 숫자가 같으면 같다."""
    rows = wtb_rows(res)
    if not rows:
        return None
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def wtb_confirmed(d: Path, res: dict | None = None, h: str | None = None) -> dict | None:
    """지금 정산표 숫자를 확인한 마지막 줄(없으면 None). 해시(h)를 바로 줄 수도 있다."""
    h = h or wtb_hash(res or {})
    if not h:
        return None
    last = None
    for x in lines(d):
        if x["what"] == "정산표 확인" and x["target"] == WTB and x.get("sha256") == h:
            last = x
    return last


# ---------------------------------------------------------------- 화면 단추가 부르는 엔진 함수
def _docs(d: Path) -> dict:
    return json.loads((Path(d) / "_색인" / "문서목록.json").read_text(encoding="utf-8"))


def confirm_files(d: Path, by: str, paths: list[str], fix: dict | None = None) -> dict:
    """판독 확인(맞음) · 고침. index apply(basis 사람, confirmed true, by) → 파일마다 `_기록` 한 줄.
    fix 는 고침(한 파일): {"kind": 종류, "period": 기간}. 하나라도 어긋나면 아무것도 쓰지 않는다(apply_patch 와 같다)."""
    from . import index

    by = check_name(d, by)
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise RecordError("확인할 받은자료를 골라 주십시오")
    if fix and len(paths) != 1:
        raise RecordError("고침은 한 파일씩 합니다")
    fix = {k: v for k, v in (fix or {}).items() if k in ("kind", "period") and v not in (None, "")}
    items = [{"path": p, "basis": "사람", "confirmed": True, "by": by} | fix for p in paths]
    r = index.apply_patch(d, {"files": items}, source=f"{DIR}/{PREFIX}{by}.jsonl")
    files = {f["path"]: f for f in _docs(d)["files"]}
    what = "판독 고침" if fix else "판독 확인"
    for p in paths:
        f = files[p]
        value = {"kind": f.get("kind"), "period": f.get("period"),
                 "facts": [{"text": x.get("text"), "source_page": x.get("source_page")} for x in f.get("facts") or [] if x.get("basis") == "AI"]}
        if fix:
            value["fixed"] = fix
        add(d, by, what, p, f.get("sha256"), value)
    return {"applied": r["applied"], "what": what}


def ask_company(d: Path, by: str, path: str, question: str, workpaper: str | None = None) -> dict:
    """회사에 묻기. `_기록` 한 줄. 지휘가 빠진 자료(질문)로 올려 다음 요청 메일에 들어간다. 판독 확인은 하지 않는다."""
    by = check_name(d, by)
    files = {f["path"]: f for f in _docs(d)["files"]}
    if path not in files:
        raise RecordError(f"문서목록에 없는 파일입니다: {path}")
    q = (question or "").strip()
    if len(q) > 300:
        raise RecordError("질문은 300자 안으로 적어 주십시오")
    wp = workpaper or next(iter(files[path].get("linked_workpapers") or []), None)
    return add(d, by, "회사에 묻기", path, files[path].get("sha256"), {"question": q, "workpaper": wp})


def confirm_ocr(d: Path, by: str, checks: list[dict]) -> dict:
    """OCR 값 확인 · 고침. checks: [{"path", "item", "value"}]. index apply(ocr_confirm, basis 사람) → 값마다 `_기록` 한 줄."""
    from . import index

    by = check_name(d, by)
    if not isinstance(checks, list) or not checks:
        raise RecordError("확인할 OCR 값을 골라 주십시오")
    per: dict[str, list] = {}
    for c in checks:
        if not isinstance(c, dict) or not isinstance(c.get("path"), str) or not isinstance(c.get("item"), str) \
                or not isinstance(c.get("value"), (int, float)) or isinstance(c.get("value"), bool):
            raise RecordError(f"OCR 확인은 파일 · 항목 · 숫자 값이어야 합니다: {c}")
        per.setdefault(c["path"], []).append({"item": c["item"], "value": c["value"], "by": by})
    # OCR 값 몇 개를 확인한 것이 그 파일의 판독(종류 · AI 사실) 전체를 확인한 것은 아니다. 파일의 확인 여부는 그대로 둔다
    now = {f["path"]: bool(f.get("confirmed")) for f in _docs(d)["files"]}
    r = index.apply_patch(d, {"files": [{"path": p, "basis": "사람", "ocr_confirm": oc, "confirmed": now.get(p, False)}
                                        for p, oc in per.items()]},
                          source=f"{DIR}/{PREFIX}{by}.jsonl")
    files = {f["path"]: f for f in _docs(d)["files"]}
    for c in checks:
        add(d, by, "OCR 값 확인", c["path"], files[c["path"]].get("sha256"), {"item": c["item"], "value": c["value"]})
    return {"applied": r["applied"], "values": len(checks)}


def confirm_company(d: Path, by: str, field: str, value) -> dict:
    """회사정보 AI 값(업종 등) 확인 · 고침. start --apply(basis 사람) → `_기록` 한 줄."""
    from . import start

    by = check_name(d, by)
    if field not in start.AI_FIELDS:
        raise RecordError(f"확인할 수 없는 회사정보입니다: {field}")
    r = start.apply(d, {"fields": [{"field": field, "value": value, "basis": "사람", "source_page": f"{by} 확인"}]})
    add(d, by, "회사정보 확인", field, None, {"value": value})
    return r


def confirm_wtb(d: Path, by: str) -> dict:
    """정산표 확인. 지금 분석의 정산표 숫자 해시로 `_기록` 한 줄."""
    by = check_name(d, by)
    p = Path(d) / "_색인" / "분석.json"
    if not p.exists():
        raise RecordError("분석 결과가 없습니다. 「분석 다시 돌리기」 를 먼저 눌러 주십시오")
    res = json.loads(p.read_text(encoding="utf-8"))
    h = wtb_hash(res)
    if not h:
        raise RecordError("정산표에 계정이 없습니다")
    return add(d, by, "정산표 확인", WTB, h, {"rows": len(wtb_rows(res))})
