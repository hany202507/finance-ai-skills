"""받은자료가 엔진이 읽은 뒤로 바뀌었는지(2026-10-31, 법인세실장 QA 결함 1). chief 현황과 review · std 가 같이 쓴다.

바뀐 것으로 보는 경우는 셋이다.
- 받은자료에 장부 파일(이름에 분개장 · 재무상태표 · 손익계산서 · 거래처원장 · 계정명세서 · 시산표)이나 전기 PDF 가 있는데
  장부.json · 전기.json 이 읽은 파일 목록에 없다. 전기 PDF 는 prior 가 읽는 `00 받은자료/전기` 바로 아래 PDF 뿐이다
  (「전기요금」 · 「전기 감사보고서」 폴더의 PDF 는 전기 신고서가 아니다, 10-31 변경 검토).
- 받은기록.json 에 read(전기 PDF 는 prior) 뒤에 넣거나 저장한 엔진 입력이 있다. 「저장됨」 줄은 종류가 비어 있어 파일로 정한다.
- 보류했던 파일(받은기록 「보류」, 해시가 적혀 있음)이 보류 폴더에서 빠져 같은 이름으로 받은자료에 들어왔는데, 장부.json ·
  전기.json 이 적은 그 파일 해시와 다르다(같은 이름으로 바꿔 넣은 경우). 해시는 이 경우의 파일 하나만 다시 계산한다.
파일 시각은 복사 · 동기화로 바뀌므로 보지 않는다. 받은기록 없이 같은 이름 파일을 덮어쓴 경우는 잡지 못한다.

  changed(case) -> {"books": [...], "prior": [...]}   다시 읽을 장부 파일 · 전기 PDF(신고 건 기준 경로). 둘 다 비면 바뀐 것 없음
  is_prior_pdf(case, path)                             prior 가 읽는 전기 PDF 인지
  sha1(path)                                           파일 해시(intake · prior 가 장부.json · 전기.json 에 적는다)
"""
from __future__ import annotations

import json
from pathlib import Path

from ..case import INDEX, PRIOR, RECEIVED
from ..case import file_sha1 as sha1

BOOK_WORDS = ("분개장", "재무상태표", "손익계산서", "거래처원장", "계정명세서", "시산표")
BOOK_KINDS = ("journal", "bs", "is", "partner_ledger", "account_detail", "trial_balance")
ADDED, SAVED, HELD = "넣음", "저장됨", "보류"


def _json(case: Path, name: str):
    try:
        return json.loads((case / INDEX / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def received(case: Path) -> list[Path]:
    recv = Path(case) / RECEIVED
    if not recv.is_dir():
        return []
    return [p for p in recv.rglob("*") if p.is_file() and not p.name.startswith("~$") and p.name.lower() != "desktop.ini"]


def is_prior_pdf(case: Path, p: Path) -> bool:
    """prior 가 읽는 전기 PDF: `00 받은자료/전기` 바로 아래 .pdf(prior.cli.pick_pdf 와 같은 범위)."""
    if p.suffix.lower() != ".pdf" or p.name.startswith("~$"):
        return False
    try:
        return Path(p).relative_to(case).parent.as_posix() == PRIOR
    except ValueError:
        return False


def _at(steps: dict, *names: str) -> str:
    return max((str(s.get("at") or "") for n in names if isinstance(s := steps.get(n), dict)), default="")


def _kind(case: Path, e: dict) -> str:
    """받은기록 줄의 종류. 「저장됨」 줄은 종류가 비어 있어(메일 첨부를 사람이 저장) 파일 이름 · 머리줄로 정한다."""
    k = str(e.get("kind") or "")
    if k or not e.get("path"):
        return k
    p = case / str(e["path"])
    if not p.is_file():
        return ""
    try:
        from ..inbox.build import kind_of

        return kind_of(p)
    except Exception:                      # noqa: BLE001
        return ""


def changed(case: str | Path, files: list[Path] | None = None) -> dict:
    case = Path(case)
    files = received(case) if files is None else files
    info = _json(case, "신고건.json") or {}
    steps = info.get("steps") if isinstance(info.get("steps"), dict) else {}
    ledger, prior = _json(case, "장부.json"), _json(case, "전기.json")
    read_at, prior_at = _at(steps, "read"), _at(steps, "prior", "prev")
    entries = [e for e in (_json(case, "받은기록.json") or {}).get("entries") or [] if isinstance(e, dict)]

    def rel(p: Path) -> str:
        return p.relative_to(case).as_posix()

    def label(e: dict) -> str:
        return str(e.get("path") or e.get("name") or "")

    by_name: dict[str, list[Path]] = {}
    for p in files:
        by_name.setdefault(p.name, []).append(p)

    def swapped(e: dict, recorded: dict[str, str]) -> list[str]:
        """보류했던 파일이 같은 이름으로 받은자료에 들어왔고, 읽은 판(recorded 의 해시)과 다른 것."""
        if e.get("state") != HELD or not e.get("sha1"):
            return []
        held = case / str(e.get("path") or "")
        if e.get("path") and held.is_file():
            return []                                   # 아직 보류 폴더에 있다
        out = []
        for p in by_name.get(str(e.get("name") or ""), []):
            r = rel(p)
            if recorded.get(r) == e["sha1"]:
                continue                                # 그 판을 이미 읽었다
            try:
                if sha1(p) == e["sha1"]:
                    out.append(r)
            except OSError:
                continue
        return out

    books: list[str] = []
    if ledger is not None:
        seen = {str(f.get("path")) for f in ledger.get("files") or [] if isinstance(f, dict)}
        hashes = {str(f.get("path")): str(f.get("sha1") or "") for f in ledger.get("files") or [] if isinstance(f, dict)}
        names = {Path(x).name for x in seen}
        books = [rel(p) for p in files if any(w in p.name for w in BOOK_WORDS) and not is_prior_pdf(case, p)
                 and rel(p) not in seen and p.name not in names]
        for e in entries:
            if e.get("state") in (ADDED, SAVED):
                when = str(e.get("saved_at") or e.get("at") or "")
                new = str(e.get("path") or "") not in seen or bool(read_at and when > read_at)   # 읽은 목록에 없거나 read 뒤
                if new and e.get("path") and (case / str(e["path"])).is_file() and _kind(case, e) in BOOK_KINDS \
                        and label(e) not in books:
                    books.append(label(e))
            elif _kind(case, e) in BOOK_KINDS or any(w in str(e.get("name") or "") for w in BOOK_WORDS):
                books += [r for r in swapped(e, hashes) if r not in books]
    pdfs: list[str] = []
    if prior is not None:
        pdf = str(prior.get("pdf") or "")
        # 전기 폴더에 PDF 가 여럿이면 prior 는 하나만 읽고 나머지를 problems 에 「읽지 않았다」 로 적는다. 그것도 이미 본 파일이다
        passed = " ".join(str(q.get("why") or "") for q in prior.get("problems") or []
                          if isinstance(q, dict) and q.get("title") == "전기 폴더에 PDF 가 여럿이다")
        pdfs = [rel(p) for p in files if is_prior_pdf(case, p) and rel(p) != pdf and p.name != Path(pdf).name
                and f"{p.name} 는 읽지 않았다" not in passed]
        recorded = {pdf: str(prior.get("pdf_sha1") or "")} if pdf else {}
        for e in entries:
            if _kind(case, e) != "prior_pdf":
                continue
            if e.get("state") in (ADDED, SAVED) and prior_at:
                when = str(e.get("saved_at") or e.get("at") or "")
                if when > prior_at and label(e) not in pdfs:
                    pdfs.append(label(e))
            else:
                pdfs += [r for r in swapped(e, recorded) if r not in pdfs and is_prior_pdf(case, case / r)]
    return {"books": [b for b in books if b], "prior": [p for p in pdfs if p]}
