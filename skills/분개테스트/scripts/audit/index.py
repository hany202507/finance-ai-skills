"""받은자료 색인 갱신(R1 T2, 2026-10-05).

  read_all(dir)            folder.scan 뒤 엑셀 받은자료를 엔진으로 판독해 문서목록의 사실 · 기간 · 연결 조서를 채운다
  apply_patch(dir, patch)  AI · 사람 판독을 문서목록에 넣는 유일한 길. 하나라도 어긋나면 아무것도 쓰지 않는다

숫자 사실은 엔진(audit.reader)만 만든다. AI 판독 사실은 문장만 받고, 금액으로 보이는 숫자가 있으면 거부한다.
"""
import copy
import json
import re
from datetime import date
from pathlib import Path

import yaml

from . import figures, folder, ocr, priorwp, reader, shareholders
from .errors import DefinitionError, IntakeError

LINKS_FILE = folder.DEFS / "received_links.yaml"
PATCH_KEYS = {"path", "kind", "period", "facts", "linked_workpapers", "confirmed", "basis", "ocr_confirm"}
OCR_CONFIRM_KEYS = {"item", "value", "by"}
FACT_KEYS = {"text", "basis", "source_page", "value"}
PERIOD_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?(~\d{4}(-\d{2}(-\d{2})?)?)?$")
SNIFF_FROM = ("기타", "분류 전")
# 글자 층이 없는 스캔 PDF(2026-10-18 실제 회사 자료: 스캔 12건을 index text 로 읽으면 빈 쪽만 나오고 경고가 없었다)
NO_TEXT_NOTE = "글자 없는 PDF {n}건(스캔본), 그 가운데 AI 판독 필요 {m}건. index text 로는 빈 쪽만 나오니 쪽 그림으로 읽습니다"
# 2026-10-18 kordoc OCR 저장본이 있으면 index text 가 OCR 글을 보인다. AI 는 그 글을 먼저 읽고 숫자 · 날짜만 쪽 그림과 대조한다
OCR_NOTE = ("글자 없는 PDF {n}건(스캔본) 가운데 OCR(kordoc) 저장본 {k}건(_색인/ocr), AI 판독 필요 {m}건. "
            "index text 가 OCR 글을 보이니 먼저 읽고 숫자 · 날짜 · 손글씨만 쪽 그림과 대조합니다")


def no_text_note(n: int, m: int, k: int) -> str:
    return OCR_NOTE.format(n=n, m=m, k=k) if k else NO_TEXT_NOTE.format(n=n, m=m)

# AI 사실 문장의 숫자 규칙. 금액 단위가 붙은 숫자, 네 자리 이상 숫자(1,000 이상)는 거부한다.
# 날짜(2025-10-15, 2025년 10월), 연도(1990~2099), 조서번호(4000BBDD, 3600-JET, 2100), 조문(제15조)은 허용한다.
UNIT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s+(?:조|억|천만|백만|만\s*원|천\s*원|원)(?![가-힣])|(?<![제\d])\d+(?:조|억|천|백|만|원)")
DATE_RE = re.compile(r"(?:19|20)\d\d\s*[-./년]\s*\d{1,2}(?:\s*[-./월]\s*\d{1,2}\s*일?)?")
WP_RE = re.compile(r"\d{4}(?:[A-Z]+|-[A-Za-z가-힣]+)")
NUM_RE = re.compile(r"(?<![\d,.])\d[\d,]*(?:\.\d+)?")


class PatchRejected(IntakeError):
    """patch 를 받아들이지 않았다. problems 에 까닭이 한국어 문장으로 있다. 아무것도 쓰지 않았다."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def _now() -> str:
    return folder._now()


def _idx(d: Path, name: str):
    return json.loads((d / "_색인" / name).read_text(encoding="utf-8"))


def _put(d: Path, name: str, data) -> None:
    folder._write(d / "_색인" / name, data)


def _received_kinds(std: dict) -> dict[str, str]:
    """받은자료 종류 이름 → 하위 폴더."""
    out = {}
    for f in std["folders"]:
        for c in f.get("children", []):
            for k in c["kinds"]:
                out[k["name"] if isinstance(k, dict) else k] = c["path"]
    return out


def _wp_numbers(std: dict) -> set[str]:
    return set(folder._wp_folder_map(std))


def _known_wp(no: str, numbers: set[str]) -> bool:
    return no in numbers or folder._is_area(no)


def load_links() -> dict[str, list[str]]:
    """received_links.yaml. 종류 이름과 조서번호가 폴더 표준과 맞지 않으면 DefinitionError."""
    std = folder.load_standard()
    if not LINKS_FILE.exists():
        raise DefinitionError(f"기본 연결 표가 없습니다: {LINKS_FILE}")
    links = {str(k): [str(x) for x in (v or [])] for k, v in yaml.safe_load(LINKS_FILE.read_text(encoding="utf-8"))["links"].items()}
    kinds, numbers = _received_kinds(std), _wp_numbers(std)
    bad = [k for k in links if k not in kinds] + [f"{k}: {no}" for k, v in links.items() for no in v if not _known_wp(no, numbers)]
    if bad:
        raise DefinitionError(f"received_links.yaml 이 폴더 표준과 맞지 않습니다: {', '.join(bad)}")
    return links


def _fy_end(case: dict) -> date | None:
    try:
        return date.fromisoformat(case.get("fiscal_year_end", ""))
    except ValueError:
        return None


def _engine(facts):
    return [f for f in facts or [] if f.get("basis") == "엔진"]


def _ai(facts):
    return [f for f in facts or [] if f.get("basis") != "엔진"]


NO_TEXT_MIN = 20          # 한 쪽에서 공백을 뺀 글자가 이보다 적으면 글자 층이 없는 쪽으로 본다(「Page 1」 같은 머리글만 있는 스캔본)
_TEXT_CACHE: dict[str, bool] = {}


def pdf_has_text(path: Path, sha: str | None = None) -> bool:
    """PDF 에 글자 층이 있는지. 모든 쪽의 글자가 NO_TEXT_MIN 보다 적으면 스캔본(글자 없음)이다. 열지 못하면 있는 것으로 본다."""
    key = sha or str(path)
    if key not in _TEXT_CACHE:
        try:
            pages = reader.pdf_text(Path(path))
        except Exception:  # noqa: BLE001  깨진 PDF 는 판독 실패로 따로 다룬다
            pages = None
        _TEXT_CACHE[key] = pages is None or any(len(re.sub(r"\s+", "", t)) >= NO_TEXT_MIN for _, t in pages)
    return _TEXT_CACHE[key]


def no_text_pdfs(d: Path, docs: dict) -> tuple[list[str], list[str]]:
    """(글자 층이 없는 받은자료 · 영구조서 PDF, 그 가운데 OCR 저장본도 AI 판독 사실도 없는 것).
    OCR 저장본이 없으면 index text 로는 빈 쪽만 나오니 쪽 그림으로 읽어야 한다."""
    every, todo = [], []
    for f in docs["files"]:
        if f["role"] not in ("received", "permanent") or Path(f["path"]).suffix.lower() != ".pdf":
            continue
        p = (Path(d) / f["path"]).resolve()
        if not p.is_file() or pdf_has_text(p, f.get("sha256")):
            continue
        every.append(f["path"])
        if not _ai(f.get("facts")) and not ocr_saved(d, f):
            todo.append(f["path"])
    return every, todo


def ocr_saved(d: Path, f: dict) -> bool:
    return bool(f.get("sha256")) and (ocr.store(d) / f"{ocr.key(f['sha256'])}.md").exists()


HOLDER_FACTS = ("기준일 ", shareholders.FACT_PREFIX)
# 잔액증명 · 약정서 PDF 의 엔진 판독 사실(2026-10-18). 지휘가 분석 요청이 풀렸는지 볼 때 쓴다(결산일 기준 잔액증명인지 · 약정서인지)
BANK_KINDS = ("금융기관 잔액증명·거래내역", "은행조회 회신")
LOAN_KIND = "차입·담보·보증 약정"
# 금융기관 사실에 「잔액증명」 낱말을 쓰지 않는다. pbc_match period_words 가 그 낱말로 증명서를 가려 기준일을 보기 때문이다
DOC_FACTS = ("기준일 ", "금융기관 이름 ", "약정서 종류 ", "약정서 금융기관 ")


def _doc_fact(f: dict) -> bool:
    return f.get("basis") == "엔진" and f["text"].startswith(DOC_FACTS)


def _read_pdf_docs(d: Path, docs: dict, touched: set, made: set) -> list[str]:
    """잔액증명 · 약정서 PDF(글자 층 또는 OCR 저장본)에서 기준일 · 금융기관 · 약정서 종류를 사실로 붙인다. 금액은 분석 몫이라 적지 않는다."""
    from .analysis import pdfread

    out = []
    for f in docs["files"]:
        if f["role"] != "received" or f["kind"] not in BANK_KINDS + (LOAN_KIND,) or Path(f["path"]).suffix.lower() != ".pdf":
            continue
        if any(_doc_fact(x) for x in f.get("facts") or []) and f["path"] not in touched and f["path"] not in made:
            continue
        try:
            r = (pdfread.loan if f["kind"] == LOAN_KIND else pdfread.bank)((d / f["path"]).resolve())
        except Exception:  # noqa: BLE001  깨진 PDF 는 분석이 따로 알린다
            continue
        if r.get("source") is None:
            continue
        tag = " (OCR, 확인 전)" if r["source"] == "ocr" else ""
        new = []

        def add(text):
            x = {"text": text, "basis": "엔진", "value": None}
            if r["source"] == "ocr":
                x.update(source="ocr", confirmed=False)
            new.append(x)
        if f["kind"] == LOAN_KIND:
            add(f"약정서 종류 {'보증료 영수증' if r.get('kind') == '보증료' else '약정'}{tag}")
            if r.get("lender"):
                add(f"약정서 금융기관 {r['lender']}{tag}")
        else:
            if r.get("as_of"):
                add(f"기준일 {r['as_of']}(PDF 글자{', OCR, 확인 전' if tag else ''})")
                f["period"] = r["as_of"]
            if r.get("institution"):
                add(f"금융기관 이름 {r['institution']}{tag}")
        if not new:
            continue
        keep = [x for x in f.get("facts") or [] if not _doc_fact(x)]
        f["facts"] = [x for x in keep if x.get("basis") == "엔진"] + new + _ai(keep)
        out.append(f["path"])
    return out


def _read_shareholders(d: Path, docs: dict, touched: set, made: set, fy_end) -> list[str]:
    """주주명부(영구조서 140 · 받은자료)를 엔진이 판독해 사실과 기간(기준일)을 붙인다(2026-10-18).
    AI 판독이 없어도 기준일을 안다. OCR 글에서 읽은 사실은 source ocr · confirmed false 다."""
    years = {fy_end.year - 1, fy_end.year, fy_end.year + 1} if fy_end else None
    out = []
    for f in docs["files"]:
        if f["role"] not in ("received", "permanent"):
            continue
        p = Path(f["path"])
        named = shareholders.KIND == f["kind"] or ("주주명부" in p.name and f["kind"] not in reader.READERS)
        if not named or p.suffix.lower() not in (".pdf",) + reader.READABLE:
            continue
        # 주주명부는 몇 개뿐이라 index read 마다 다시 읽는다(판독 규칙이 바뀌어도 사실이 따라 바뀐다)
        try:
            r = shareholders.read((d / f["path"]).resolve(), years, f.get("period"))
        except Exception as e:  # noqa: BLE001  깨진 파일은 판독 실패로 남긴다
            docs.setdefault("warnings", []).append(f"주주명부 판독 실패({e}): {f['path']}")
            continue
        if not r:
            continue
        keep = [x for x in f.get("facts") or [] if not (x.get("basis") == "엔진" and x["text"].startswith(HOLDER_FACTS))]
        f["facts"] = [x for x in keep if x.get("basis") == "엔진"] + shareholders.facts(r) + _ai(keep)
        if r.get("as_of") and r.get("as_of_basis") != "색인 period":
            f["period"] = r["as_of"]
        out.append(f["path"])
    return out


# ---------------------------------------------------------------- 엔진 판독
def read_all(engagement_dir: Path, now: str | None = None, use_ocr: bool = True) -> dict:
    """use_ocr: 글자 없는 PDF 에 kordoc OCR 을 돌려 _색인/ocr 에 둔다(2026-10-18). False 나 AUDIT_OCR=off 면 지금처럼 AI 판독 필요로 남긴다."""
    d = Path(engagement_dir)
    at = now or _now()
    rep = folder.scan(d, now=at)
    std = folder.load_standard()
    links = load_links()
    kinds = _received_kinds(std)
    docs = _idx(d, "문서목록.json")
    case = _idx(d, "감사건.json")
    fy_end = _fy_end(case)
    touched = set(rep["new"]) | set(rep["changed"])
    scans, _ = no_text_pdfs(d, docs)
    ocr_rep = ocr.ensure(d, docs, on=use_ocr, pdfs=scans)
    if ocr_rep["warning"]:
        docs.setdefault("warnings", []).append(ocr_rep["warning"])

    read, sniffed, unread, linked = [], [], [], []
    for f in docs["files"]:
        if f["role"] != "received":
            continue
        p = d / f["path"]
        excel = p.suffix.lower() in reader.EXCEL
        kind = f["kind"]
        need = f["path"] in touched or not _engine(f["facts"])
        if excel and need and "판독 필요" in kind and f.get("folder_kind") == priorwp.PRIOR_FOLDER and priorwp.looks_like_workpaper(p):
            # 전기 폴더의 손 조서(Lead · 감사절차 · Conclusion 라벨이 있는 엑셀). 원장 발췌 시트 때문에 분개장으로 읽히기 전에 먼저 본다
            f.update(kind=priorwp.PRIOR_WP, kind_basis="엔진", confirmed=True)
            sniffed.append(f["path"])
            kind = priorwp.PRIOR_WP
        readable = p.suffix.lower() in reader.READABLE            # .xls 도 엔진이 연다(xlrd, 2026-10-18)
        if readable and need and kind not in reader.READERS and (kind in SNIFF_FROM or "판독 필요" in kind):
            k = reader.sniff_kind(p)
            if k:
                f.update(kind=k, kind_basis="엔진", confirmed=True)
                sniffed.append(f["path"])
                kind = k
        if need and kind in reader.READERS and readable:
            facts = reader.read(p, kind, fy_end)
            f["facts"] = facts + _ai(f["facts"])
            (read if facts else unread).append(f["path"])
            # 판독 실패는 「파일 없음」 과 다르다. 까닭을 색인에 남기고 확인 전으로 둔다(R8)
            if facts:
                if f.pop("read_error", None) and f["kind_basis"] in ("폴더", "파일명", "엔진"):
                    f["confirmed"] = True
            else:
                f["read_error"] = reader.read_failure(p, kind) or reader.READ_FAIL
                f["confirmed"] = False
                docs.setdefault("warnings", []).append(f"{f['kind']} {f['read_error']}: {f['path']}")
        per = reader.period_from_facts(f["facts"], f["kind"])
        if per:
            f["period"] = per
        if not f.get("linked_workpapers") and links.get(f["kind"]):
            f["linked_workpapers"] = list(links[f["kind"]])
            linked.append(f["path"])

    if read:
        _new_parties(d, docs["files"])
    holders = _read_shareholders(d, docs, touched, set(ocr_rep["made"]), fy_end)
    pdf_docs = _read_pdf_docs(d, docs, touched, set(ocr_rep["made"]))

    # 엔진이 정한 종류가 들어 있는 폴더와 다르면 옮기기를 권한다
    for f in docs["files"]:
        if f["role"] == "received" and f["kind_basis"] == "엔진" and kinds.get(f["kind"]) and kinds[f["kind"]] != f.get("folder_kind"):
            docs.setdefault("warnings", []).append(
                f"엔진 판독 종류는 {f['kind']} 입니다. '00 받은자료/{kinds[f['kind']]}' 폴더로 옮겨 주십시오: {f['path']}")

    # 분개장끼리 기간이 겹치면 어느 것을 합치지 않는지 알린다(2026-10-18, 권한 검토용 분기 분개장이 1년 분개장과 함께 들어온 경우)
    _put(d, "문서목록.json", docs)
    overlap = [f"분개장 겹침: {x['path']} {x['why']}" for x in figures.journal_plan(d, reader.READABLE) if x["why"]]
    docs.setdefault("warnings", []).extend(overlap)

    docs["indexed_at"] = at
    _put(d, "문서목록.json", docs)
    need_ai = [f["path"] for f in docs["files"] if f["role"] == "received" and not [x for x in _engine(f["facts"]) if not _doc_fact(x)]
               and (not f["confirmed"] or Path(f["path"]).suffix.lower() not in reader.EXCEL) and not _ai(f["facts"])]
    # 판독한 뒤 내용이 바뀐 영구조서는 다시 판독한다(앞 판독은 남아 있고 확인 전이다, 2026-10-18)
    need_ai += [f["path"] for f in docs["files"] if f["role"] == "permanent" and f.get("needs_recheck")]
    no_text, no_text_todo = no_text_pdfs(d, docs)
    by = {f["path"]: f for f in docs["files"]}
    saved = [p for p in no_text if ocr_saved(d, by[p])]
    what = (f"엔진 판독 {len(read)}개, 엔진이 종류를 정한 파일 {len(sniffed)}개, 기본 연결 조서를 붙인 파일 {len(linked)}개, "
            f"머리줄을 찾지 못한 파일 {len(unread)}개, AI 판독이 필요한 파일 {len(need_ai)}개")
    if holders:
        what += f", 주주명부 판독 {len(holders)}개"
    if pdf_docs:
        what += f", 잔액증명 · 약정서 기준일 · 종류 판독 {len(pdf_docs)}개"
    if no_text:
        what += f", {no_text_note(len(no_text), len(no_text_todo), len(saved))}"
        if ocr_rep["made"]:
            what += f". 이번에 OCR 한 파일 {len(ocr_rep['made'])}개"
    if ocr_rep["warning"]:
        what += f". 주의: {ocr_rep['warning']}"
    wrote = ["_색인/문서목록.json"] + (["_색인/ocr"] if ocr_rep["made"] else [])
    case["log"].insert(0, {"at": at, "who": "색인", "what": what, "read": read + unread + holders, "wrote": wrote})
    _put(d, "감사건.json", case)
    folder.validate_index(d)
    return {"scan": rep, "read": read, "sniffed": sniffed, "unread": unread, "linked": linked, "need_ai": need_ai, "overlap": overlap,
            "facts": {f["path"]: _engine(f["facts"]) for f in docs["files"] if f["path"] in read or f["path"] in holders},
            "no_text_pdf": no_text, "no_text_pdf_todo": no_text_todo, "ocr_saved": saved, "ocr": ocr_rep, "shareholders": holders}


def _new_parties(d: Path, files: list[dict]) -> None:
    """분개장마다 바로 앞 연도 분개장에 없던 거래처. 앞 연도 분개장이 없으면 사실을 두지 않는다."""
    journals = []
    for f in files:
        if f["role"] == "received" and f["kind"] == reader.JOURNAL and Path(f["path"]).suffix.lower() in reader.EXCEL:
            rng = reader.journal_range(f["facts"])
            if rng:
                journals.append((f, rng[0].year))
    cache: dict[str, set[str]] = {}

    def parties(f):
        if f["path"] not in cache:
            cache[f["path"]] = reader.journal_parties(d / f["path"])
        return cache[f["path"]]

    for f, y in journals:
        f["facts"] = [x for x in f["facts"] if not (x.get("basis") == "엔진" and x["text"].startswith(reader.NEW_PARTY_FACT))]
        prior = [g for g, gy in journals if gy == y - 1]
        if not prior:
            continue
        before = set().union(*(parties(g) for g in prior))
        new = sorted(parties(f) - before)
        shown = ", ".join(new[:10]) + (f" 외 {len(new) - 10}곳" if len(new) > 10 else "")
        text = f"{reader.NEW_PARTY_FACT} {len(new)}곳" + (f": {shown}" if new else "")
        pos = max((i for i, x in enumerate(f["facts"]) if x.get("basis") == "엔진"), default=-1) + 1
        f["facts"].insert(pos, {"text": text, "basis": "엔진", "value": len(new)})


# ---------------------------------------------------------------- AI · 사람 판독
def amount_in_text(text: str) -> str | None:
    """사실 문장에 금액으로 보이는 숫자가 있으면 그 부분을 돌려준다."""
    m = UNIT_RE.search(text)
    if m:
        return m.group(0).strip()
    t = WP_RE.sub(" ", DATE_RE.sub(" ", text))
    numbers = _wp_numbers(folder.load_standard())
    for m in NUM_RE.finditer(t):
        tok = m.group(0)
        if len(tok.replace(",", "").split(".")[0]) < 4:
            continue
        if tok in numbers or re.fullmatch(r"(?:199\d|20\d\d)", tok):
            continue
        return tok
    return None


def _check(item, i: int, files: dict, kinds: dict, numbers: set[str], seen: set) -> list[str]:
    where = f"{i + 1}번째 항목"
    if not isinstance(item, dict):
        return [f"{where}: 객체여야 합니다"]
    probs = []
    extra = sorted(set(item) - PATCH_KEYS)
    if extra:
        probs.append(f"{where}: patch 에 쓸 수 없는 항목입니다: {', '.join(extra)} (쓸 수 있는 것: {', '.join(sorted(PATCH_KEYS))})")
    path = item.get("path")
    basis = item.get("basis")
    if basis not in ("AI", "사람"):
        probs.append(f"{where}: basis 는 AI 또는 사람 이어야 합니다")
    if not isinstance(path, str) or path not in files:
        return probs + [f"{where}: 문서목록에 없는 파일입니다: {path}"]
    where = f"{where}({path})"
    if path in seen:
        probs.append(f"{where}: 같은 파일이 patch 에 두 번 있습니다")
    seen.add(path)
    f = files[path]
    if "kind" in item:
        if f["role"] != "received":
            probs.append(f"{where}: 종류는 받은자료만 바꿀 수 있습니다")
        elif item["kind"] not in kinds:
            probs.append(f"{where}: 폴더 표준에 없는 종류입니다: {item['kind']}")
    if "period" in item and item["period"] is not None and (not isinstance(item["period"], str) or not PERIOD_RE.match(item["period"])):
        probs.append(f"{where}: 기간은 2025, 2025-12, 2025-12-31, 2025-07~2025-12 꼴로 적습니다: {item['period']}")
    if "confirmed" in item:
        if not isinstance(item["confirmed"], bool):
            probs.append(f"{where}: confirmed 는 true 나 false 입니다")
        elif item["confirmed"] and basis == "AI":
            probs.append(f"{where}: AI 판독은 확인 표시를 할 수 없습니다. 회계사가 basis 사람 으로 확인합니다")
    if "linked_workpapers" in item:
        lw = item["linked_workpapers"]
        if not isinstance(lw, list) or not all(isinstance(x, str) for x in lw):
            probs.append(f"{where}: linked_workpapers 는 조서번호 목록입니다")
        else:
            bad = [x for x in lw if not _known_wp(x, numbers)]
            if bad:
                probs.append(f"{where}: 폴더 표준에 없는 조서번호입니다: {', '.join(bad)}")
    if "ocr_confirm" in item:
        oc = item["ocr_confirm"]
        if basis != "사람":
            probs.append(f"{where}: OCR 값 확인(ocr_confirm)은 회계사만 넣습니다. basis 사람 으로 넣어 주십시오")
        elif not isinstance(oc, list) or not oc:
            probs.append(f"{where}: ocr_confirm 은 [{{\"item\": 항목, \"value\": 값}}] 목록입니다")
        else:
            for j, x in enumerate(oc):
                if not isinstance(x, dict) or set(x) - OCR_CONFIRM_KEYS or not isinstance(x.get("item"), str) or not x["item"].strip() \
                        or not isinstance(x.get("value"), (int, float)) or isinstance(x.get("value"), bool):
                    probs.append(f"{where} OCR 확인 {j + 1}: item(글) · value(숫자) · by(확인자, 글) 만 씁니다: {x}")
    if "facts" in item:
        if not isinstance(item["facts"], list):
            probs.append(f"{where}: facts 는 목록입니다")
        else:
            for j, fact in enumerate(item["facts"]):
                fw = f"{where} 사실 {j + 1}"
                if not isinstance(fact, dict) or not isinstance(fact.get("text"), str) or not fact["text"].strip():
                    probs.append(f"{fw}: text 가 있는 객체여야 합니다")
                    continue
                if fact.get("basis", "AI") != "AI":
                    probs.append(f"{fw}: patch 사실의 basis 는 AI 뿐입니다. 엔진 사실은 index read 가 씁니다")
                if fact.get("value") is not None:
                    probs.append(f"{fw}: 숫자 값(value)은 엔진만 씁니다. 문장으로만 적어 주십시오")
                amt = amount_in_text(fact["text"])
                if amt:
                    probs.append(f"{fw}: 금액으로 보이는 숫자 '{amt}' 가 있습니다. 숫자는 엔진 판독만 씁니다: {fact['text']}")
    return probs


def apply_patch(engagement_dir: Path, patch: dict, now: str | None = None, source: str | None = None) -> dict:
    """patch 를 문서목록에 넣는다. 하나라도 어긋나면 PatchRejected 를 올리고 아무것도 쓰지 않는다."""
    import jsonschema

    d = Path(engagement_dir)
    at = now or _now()
    std = folder.load_standard()
    kinds, numbers, links = _received_kinds(std), _wp_numbers(std), load_links()
    docs = _idx(d, "문서목록.json")
    if not isinstance(patch, dict) or not isinstance(patch.get("files"), list) or not patch["files"]:
        raise PatchRejected(['patch 는 {"files": [...]} 꼴이고 항목이 하나 이상 있어야 합니다'])
    extra = sorted(set(patch) - {"files"})
    probs = [f"patch 맨 위에 쓸 수 없는 항목입니다: {', '.join(extra)}"] if extra else []
    new = copy.deepcopy(docs)
    files = {f["path"]: f for f in new["files"]}
    seen: set = set()
    for i, item in enumerate(patch["files"]):
        probs += _check(item, i, files, kinds, numbers, seen)
    if probs:
        raise PatchRejected(probs)

    counts = {"종류": 0, "기간": 0, "사실": 0, "연결 조서": 0, "확인": 0, "OCR 값 확인": 0}
    for item in patch["files"]:
        f = files[item["path"]]
        human = item["basis"] == "사람"
        if "kind" in item and item["kind"] != f["kind"]:
            old_default = links.get(f["kind"], [])
            f.update(kind=item["kind"], kind_basis="AI", confirmed=human)
            if "linked_workpapers" not in item and f.get("linked_workpapers", []) in ([], old_default):
                f["linked_workpapers"] = list(links.get(item["kind"], []))
            counts["종류"] += 1
        if "period" in item:
            f["period"] = item["period"]
            counts["기간"] += 1
        if "facts" in item:
            ai = [{k: v for k, v in x.items() if k in ("text", "source_page")} | {"basis": "AI"} for x in item["facts"]]
            f["facts"] = _engine(f.get("facts")) + ai
            counts["사실"] += len(ai)
        if "linked_workpapers" in item:
            f["linked_workpapers"] = list(dict.fromkeys(item["linked_workpapers"]))
            counts["연결 조서"] += 1
        if "ocr_confirm" in item:
            # 회계사가 쪽 그림과 대조해 확인한 OCR 값. 같은 항목은 새 값으로 바꾼다. 파일 해시를 함께 적어 파일이 바뀌면 풀린다
            keep = [x for x in f.get("ocr_confirmed") or [] if x["item"] not in {c["item"] for c in item["ocr_confirm"]}]
            f["ocr_confirmed"] = keep + [{"item": c["item"].strip(), "value": c["value"], "by": str(c.get("by") or "회계사"), "at": at,
                                          "sha256": f["sha256"]} for c in item["ocr_confirm"]]
            counts["OCR 값 확인"] += len(item["ocr_confirm"])
        if human or "facts" in item:
            f.pop("needs_recheck", None)      # 바뀐 영구조서를 다시 판독했거나 사람이 확인했다
        if human:
            f["confirmed"] = item.get("confirmed", True)
            counts["확인"] += 1 if f["confirmed"] else 0
        else:
            # AI 가 종류 · 기간 · 사실 · 연결 중 무엇을 넣었든 회계사가 확인하기 전까지는 확인 전이다
            f["confirmed"] = False
    try:
        jsonschema.validate(new, folder._schema()["문서목록.json"])
    except jsonschema.ValidationError as e:
        path = "/".join(str(x) for x in e.absolute_path)
        raise PatchRejected([f"적용하면 문서목록 형식이 깨집니다({path}): {e.message}"]) from None

    new["indexed_at"] = at
    _put(d, "문서목록.json", new)
    case = _idx(d, "감사건.json")
    who = "사람" if any(x["basis"] == "사람" for x in patch["files"]) else "AI"
    what = f"{who} 판독 {len(patch['files'])}건을 반영했습니다: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v)
    case["log"].insert(0, {"at": at, "who": "색인", "what": what, "read": [source] if source else [],
                           "wrote": ["_색인/문서목록.json"]})
    _put(d, "감사건.json", case)
    folder.validate_index(d)
    return {"applied": len(patch["files"]), "counts": counts}
