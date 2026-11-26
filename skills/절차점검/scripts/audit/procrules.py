"""절차 점검 규칙. 파일 방식(procfile.py)이 쓴다.

표준 라이브러리와 openpyxl 만 쓴다.
조서를 어떻게 여는지, 받은자료가 어디 있는지는 부르는 쪽이 Books 로 넘긴다.

  check_item(item, i, rs, books, seen, find)   판정 한 줄 검사 → (문제 목록, 받아들인 줄)
  same_cites(items)                            「수행됨」 여러 줄이 똑같은 근거를 든 것
  sig(x)                                       판정 한 줄의 식별값
  stale(root, rec, memo)                       점검 뒤에 바뀐 파일
  write_sheet(out, rec, notes, hint, ...)      점검표 엑셀
  sheet_rows(ws, rec) · picks(path, rec)       점검표에서 고른 번호

판정이 옳은지는 여기서 보지 않는다. 근거 칸이 실제로 있는지, 판정이 줄마다 있는지, 글이 규칙에 맞는지만 본다.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import range_boundaries
from openpyxl.worksheet.datavalidation import DataValidation

from .errors import IntakeError

SHEET = "절차 점검"
MAX_MISSING = 80                    # 「빠진 것」 글자 수
ISSUE, PART1, PART2, AREA = "이슈", 1, 2, "영역"
DONE, NA, OPEN, SKIP = "수행", "해당 없음", "미정", "수행 안 함"
OK_DONE, OK_NA = "수행됨", "사유 맞음"
SHORT, MISMATCH, NO_CITE = "수행 부족", "사유 어긋남", "판단 못 함"   # NO_CITE 는 근거 없이 받는 판정
VERDICTS = (OK_DONE, OK_NA, "일부 빠짐", SHORT, "수행 기록 없음", MISMATCH, NO_CITE)
OK = (OK_DONE, OK_NA)
ASPECTS = ("범위", "증거", "차이 처리", "결론")      # 「수행 부족」 의 빠진 것은 이 가운데 하나로 시작한다
FILE_ONLY = (MISMATCH,)             # 받은자료 파일만 근거로 들어도 받는 판정(NO_CITE 는 근거가 없어도 받는다)
RECEIVED = "받은자료:"
FRESH, STALE, NEVER = "최신", "조서 바뀜", "점검 안 함"
MAX_CITE_CELLS = 5000               # 근거 범위에서 값을 읽는 칸 수 상한
ABSENT = "없음"                     # deps 값: 점검 때 그 파일이 없었다
MAX_SAME_CITE = 3                   # 「수행됨」 줄이 똑같은 근거를 되풀이할 수 있는 줄 수
PICK = "예"
ITEM_KEYS = {"part", "key", "verdict", "missing", "cites"}
WP_NO = re.compile(r"^[0-9]{4}[0-9A-Za-z가-힣-]*")
STEP_NO = re.compile(r"^\s*(\d+)\s*[.)]")
HEAD = ["번호", "절차", "판정", "빠진 것", "근거", "반영", "반영 결과"]
HEAD_ROW = 5
YELLOW = PatternFill("solid", fgColor="FFF2CC")

# 금액으로 보는 숫자.
# 쉼표 낀 숫자, 바로 뒤에 원 · 천원 · 백만원 · 억원이 붙은 숫자, 억 · 천만 · 백만 단위 숫자, 7자리 이상 숫자.
AMOUNT_RES = (re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
              re.compile(r"(?<!제)(?<![\d.])\d[\d.]*\s*(?:조|억|천만|백만|십만|만|천|백)\s*원"),
              re.compile(r"\d[\d.]*원"),
              re.compile(r"(?<!제)(?<![\d.])\d[\d.]*\s*(?:억|천만|백만)"),
              re.compile(r"\d{7,}"))


class Rejected(IntakeError):
    """판정을 받아들이지 않았다. problems 에 까닭이 있다. 아무것도 쓰지 않았다."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def text(v) -> str:
    return str(v).strip() if v is not None else ""


def amount_in_text(s: str) -> str | None:
    """글에 금액으로 보이는 숫자가 있으면 그 부분을 돌려준다."""
    for rx in AMOUNT_RES:
        m = rx.search(s)
        if m:
            return m.group(0).strip()
    return None


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_or_none(p: Path, memo: dict | None = None) -> str:
    """파일 지문. 없으면 ABSENT. memo 를 주면 한 번 읽은 파일을 다시 읽지 않는다."""
    key = str(p)
    if memo is not None and key in memo:
        return memo[key]
    out = sha(p) if Path(p).is_file() else ABSENT
    if memo is not None:
        memo[key] = out
    return out


class Books:
    """근거가 가리키는 조서 파일을 한 번씩만 연다(값으로 읽는다). 끝나면 close.

    no          점검하는 조서의 이름(감사 폴더 방식은 조서번호, 파일 방식은 파일 이름)
    root        기록의 파일 경로를 재는 기준 폴더
    path        점검하는 조서 파일
    listed      근거로 쓸 수 있는 다른 조서 {이름: {"file": root 기준 경로 또는 절대 경로}}
    received    받은자료 폴더. None 이면 받은자료 근거를 받지 않는다
    covers      절차 표가 있는 시트의 표시 {"<no>:<시트>"}. 「수행됨」 의 근거는 여기 아닌 시트의 칸이 하나 이상 있어야 한다
    outside     받은자료가 root 밖에 있어도 받는다(파일 방식). 기록에는 절대 경로로 남긴다
    words       오류 글에 쓰는 낱말"""

    WORDS = {"received": "00 받은자료", "rows_from": "표지", "rows_cmd": "`wp procs` 가 보인 key 를 그대로 적습니다",
             "work_cell": "표지가 아닌 수행 시트의 칸", "other": "조서번호가", "listed": "조서목록",
             "cite_forms": "「시트!칸」 · 「<조서번호>:시트!칸」 · 「받은자료:<경로>」"}

    def __init__(self, no: str, root: Path, path: Path, listed: dict | None = None, received: Path | None = None,
                 covers: set | None = None, outside: bool = False, words: dict | None = None):
        self.no, self.root = no, Path(root)
        self.listed = dict(listed or {})
        self.paths = {no: Path(path)}
        self.received = Path(received) if received else None
        self.covers = set(covers or ())
        self.outside = outside
        self.words = {**self.WORDS, **(words or {})}
        self.open: dict = {}
        self.deps: dict = {}                            # 근거로 든 다른 파일 {기록에 남길 경로: 파일}

    def file_of(self, no: str) -> Path | None:
        if no in self.paths:
            return self.paths[no]
        w = self.listed.get(no)
        return (self.root / w["file"]) if w and w.get("file") else None

    def book(self, no: str):
        if no not in self.open:
            p = self.file_of(no)
            self.open[no] = load_workbook(p, data_only=True) if p and p.is_file() else None
        return self.open[no]

    def dep_key(self, target: Path) -> str | None:
        """기록에 남길 경로. root 안이면 root 기준, 밖이면 outside 일 때만 절대 경로."""
        try:
            return target.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return target.resolve().as_posix() if self.outside else None

    def is_cover(self, tag: str, box: tuple) -> bool:
        """그 근거 칸이 절차 표 안인지. 「수행됨」 은 절차 표 아닌 칸이 하나 이상 있어야 한다."""
        return tag in self.covers

    def close(self) -> None:
        for wb in self.open.values():
            if wb is not None:
                wb.close()


def find(rs: list[dict], part, key) -> dict | None:
    cands = [r for r in rs if r["part"] == part]
    if isinstance(key, bool):
        return None
    if isinstance(key, int) or (isinstance(key, str) and re.fullmatch(r"\d+\s*[.)]?", key.strip())):
        n = int(re.match(r"\d+", str(key).strip()).group(0))
        if part == ISSUE:
            return next((r for r in cands if r["key"] == f"이슈 {n}"), None)
        return next((r for r in cands if (m := STEP_NO.match(r["step"])) and int(m.group(1)) == n), None)
    if not isinstance(key, str) or not key.strip():
        return None
    hit = [r for r in cands if key.strip() in (r["key"], r["step"])]
    return hit[0] if len(hit) == 1 else None


def cite_check(cite, books: Books) -> tuple[str | None, str | None, list]:
    """근거 하나 → (까닭, 종류, [(조서:시트, 빈칸뿐인지, 근거 글)]). 까닭이 None 이면 받는다. 종류는 "cell"(조서 칸) · "file"(받은자료 파일).
    빈칸을 가리키는 근거는 볼 것 줄에서는 받는다(빈칸이 곧 문제일 때). 문제없음 줄에서는 받지 않는다(check_item).

      시트!칸                이 조서
      <이름>:시트!칸         listed 의 다른 조서
      받은자료:<상대 경로>   받은자료 폴더 아래 파일"""
    w = books.words
    if not isinstance(cite, str) or not cite.strip():
        return f"근거는 글입니다: {cite}", None, []
    cite = cite.strip()
    if cite.startswith(RECEIVED):
        whole = cite[len(RECEIVED):].strip().replace("\\", "/")
        if books.received is None:
            return f"받은자료 폴더를 주지 않아 받은자료 근거를 받을 수 없습니다: {cite}", None, []
        base = books.received.resolve()
        rel = whole.split("#", 1)[0].strip()                  # 「#쪽 · 표」 는 사람이 볼 위치
        if whole and "#" in whole and (base / whole).is_file():   # 파일 이름에 「#」 이 든 경우
            if rel and (base / rel).is_file():
                return f"근거의 받은자료 경로가 두 파일로 읽힙니다(「{rel}」 과 「{whole}」). 파일 이름에서 「#」 을 빼고 다시 적습니다: {cite}", None, []
            rel = whole
        target = (base / rel).resolve() if rel else base
        if not rel or base not in target.parents or not target.is_file():
            return f"근거의 받은자료 파일이 「{w['received']}」 아래에 없습니다: {cite}", None, []
        if target.stat().st_size == 0:
            return f"근거의 받은자료 파일이 빈 파일입니다: {cite}", None, []
        key = books.dep_key(target)
        if key is None:
            return f"근거의 받은자료 파일이 감사 폴더 안에 있지 않습니다(「{w['received']}」 가 다른 곳을 가리킴): {cite}", None, []
        books.deps[key] = target
        return None, "file", []
    if "!" not in cite:
        return f"근거는 {w['cite_forms']} 꼴입니다: {cite}", None, []
    left, ref = cite.rsplit("!", 1)
    no, sheet = books.no, left.strip().strip("'")
    here = books.book(books.no).sheetnames if books.book(books.no) else []
    if ":" in left and sheet in here and left.split(":", 1)[0].strip() in books.listed:
        return f"근거가 이 조서의 시트 이름으로도, 다른 조서의 칸으로도 읽힙니다. 시트 이름에 「:」 가 든 조서는 근거로 쓸 수 없습니다: {cite}", None, []
    if sheet not in here and ":" in left:
        head, tail = left.split(":", 1)
        if head.strip() == books.no or head.strip() in books.listed:
            no, sheet = head.strip(), tail.strip().strip("'")
        elif WP_NO.fullmatch(head.strip()):
            return f"근거의 {w['other']} {w['listed']}에 없습니다: {cite}", None, []
    wb = books.book(no)
    if wb is None:
        return f"근거의 조서 {no} 파일이 없습니다: {cite}", None, []
    if sheet.startswith("_") or sheet not in wb.sheetnames:
        return f"근거의 시트가 조서 {no} 에 없습니다: {cite}", None, []
    try:
        c1, r1, c2, r2 = range_boundaries(ref.strip().replace("$", ""))
    except (ValueError, TypeError):
        return f"근거의 칸 주소를 읽지 못했습니다: {cite}", None, []
    ws = wb[sheet]
    if None in (c1, r1, c2, r2) or r2 > ws.max_row or c2 > ws.max_column:
        return f"근거의 칸이 그 시트의 쓰인 범위(~{ws.max_row}행)에 없습니다. 행 · 열 전체가 아니라 쓰인 칸을 가리킵니다: {cite}", None, []
    if (r2 - r1 + 1) * (c2 - c1 + 1) > MAX_CITE_CELLS:
        return f"근거 범위가 너무 넓습니다({MAX_CITE_CELLS}칸까지): {cite}", None, []
    empty = not any(text(v) for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True) for v in row)
    if no != books.no:
        p = books.file_of(no)
        books.deps[books.dep_key(p) or books.listed[no]["file"]] = p
    return None, "cell", [(f"{no}:{sheet}", empty, cite, (c1, r1, c2, r2))]


def check_item(item, i: int, rs: list[dict], books: Books, seen: set, finder=find) -> tuple[list[str], dict | None]:
    """판정 한 줄. rs 의 줄은 {part, key, step, state, applies} 를 가진다."""
    w = books.words
    where = f"{i + 1}번째 판정"
    if not isinstance(item, dict):
        return [f"{where}: 객체여야 합니다"], None
    probs = []
    extra = sorted(set(item) - ITEM_KEYS)
    if extra:
        probs.append(f"{where}: 쓸 수 없는 항목입니다: {', '.join(extra)}")
    part, key, verdict = item.get("part"), item.get("key"), item.get("verdict")
    row = None
    if part == AREA:
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > 30:
            probs.append(f"{where}: 영역 줄의 key 는 30자 안의 이름입니다: {key}")
        elif (AREA, key.strip()) in seen:
            probs.append(f"{where}: 같은 영역 줄이 두 번 있습니다: {key}")
        else:
            seen.add((AREA, key.strip()))
    elif isinstance(part, bool) or part not in (ISSUE, PART1, PART2):
        probs.append(f"{where}: part 는 1 · 2 · \"이슈\" · \"영역\" 가운데 하나입니다: {part}")
    else:
        row = finder(rs, part, key)
        if row is None:
            probs.append(f"{where}: {w['rows_from']}에 없는 절차입니다(part {part}): {key}. {w['rows_cmd']}")
        elif (row["part"], row["key"]) in seen:
            probs.append(f"{where}: 같은 절차의 판정이 두 번 있습니다: {row['key']}")
        else:
            seen.add((row["part"], row["key"]))
    name = row["key"] if row else key
    if verdict not in VERDICTS:
        probs.append(f"{where}({name}): verdict 는 {' · '.join(VERDICTS)} 가운데 하나입니다: {verdict}")
    missing = item.get("missing") or ""
    cites = item.get("cites") or []
    if not isinstance(missing, str):
        probs.append(f"{where}({name}): missing 은 글입니다")
        missing = ""
    missing = missing.strip()
    if not isinstance(cites, list):
        probs.append(f"{where}({name}): cites 는 「시트!칸」 목록입니다")
        cites = []
    if verdict in OK:
        if part == AREA:
            probs.append(f"{where}({name}): 영역 줄은 볼 것만 적습니다. 문제없으면 줄을 넣지 않습니다")
        if missing:
            probs.append(f"{where}({name}): 「{verdict}」 줄에는 의견(missing)을 쓰지 않습니다. 근거 칸만 적습니다")
        if row and verdict == OK_DONE and row["state"] != DONE:
            probs.append(f"{where}({name}): 해당 여부가 「{row['applies'] or '빈칸'}」 인 줄은 「{OK_DONE}」 으로 판정할 수 없습니다")
        if row and verdict == OK_NA and row["state"] != NA:
            probs.append(f"{where}({name}): 「{OK_NA}」 은 해당 여부가 「해당 없음」 인 줄에만 씁니다")
    elif verdict in VERDICTS:
        if not missing:
            probs.append(f"{where}({name}): 「{verdict}」 줄은 빠진 것(missing)을 한 줄로 적습니다")
        elif "\n" in missing or len(missing) > MAX_MISSING:
            probs.append(f"{where}({name}): missing 은 한 줄, {MAX_MISSING}자까지입니다(지금 {len(missing)}자)")
        if verdict == SHORT:
            if row and row["state"] != DONE:
                probs.append(f"{where}({name}): 「{SHORT}」 은 해당 여부가 「해당」 인 줄에만 씁니다")
            if missing and not any(missing.startswith(f"{a}:") for a in ASPECTS):
                probs.append(f"{where}({name}): 「{SHORT}」 의 missing 은 {' · '.join(a + ':' for a in ASPECTS)} 가운데 하나로 시작합니다")
    kinds, values = set(), []
    for c in cites:
        bad, kind, vals = cite_check(c, books)
        if bad:
            probs.append(f"{where}({name}): {bad}")
        else:
            kinds.add(kind)
            values += vals
    if verdict in VERDICTS and verdict != NO_CITE and "cell" not in kinds and not (verdict in FILE_ONLY and "file" in kinds):
        probs.append(f"{where}({name}): 근거(cites)에 조서 칸(「시트!칸」)이 하나 이상 있어야 합니다"
                     + (f". 받은자료 파일만 근거로 드는 것은 「{MISMATCH}」 · 「{NO_CITE}」 에서만 받습니다" if "file" in kinds else ""))
    if missing and verdict in VERDICTS and verdict not in OK and (amt := amount_in_text(missing)):
        probs.append(f"{where}({name}): missing 에 금액으로 보이는 숫자 '{amt}' 가 있습니다. 숫자는 근거 칸으로 가리킵니다")
    if verdict in OK:
        for _, empty, c, _box in values:
            if empty:
                probs.append(f"{where}({name}): 「{verdict}」 의 근거로 든 칸이 모두 빈칸입니다: {c}")
    if verdict == OK_DONE and cites and not probs and not any(not books.is_cover(tag, box) for tag, _, _, box in values):
        probs.append(f"{where}({name}): 「{OK_DONE}」 의 근거에 {w['work_cell']}이 하나 이상 있어야 합니다")
    if probs:
        return probs, None
    return [], {"part": part, "key": row["key"] if row else key.strip(), "step": row["step"] if row else key.strip(),
                "state": row["state"] if row else AREA, "verdict": verdict, "missing": missing,
                "cites": [c.strip() for c in dict.fromkeys(cites)]}


def norm_cite(c: str, own: str | None = None) -> str:
    """근거 글의 표기 차이(따옴표 · $ · 소문자 칸 주소 · 빈칸 · 「A1:A1」 · 제 조서 이름을 앞에 붙인 것)를 없앤 꼴.
    같은 근거인지 견줄 때만 쓴다. 범위를 조금 넓히거나 칸을 하나 더한 것은 가르지 못한다(회계사가 점검표의 근거 칸에서 본다)."""
    c = c.strip()
    if c.startswith(RECEIVED) or "!" not in c:
        return c
    left, ref = c.rsplit("!", 1)
    parts = [t.strip().strip("'") for t in left.split(":", 1)]
    if own and len(parts) == 2 and parts[0] == own:
        parts = parts[1:]
    ref = ref.replace("$", "").replace(" ", "").upper()
    a, _, b = ref.partition(":")
    return ":".join(parts) + "!" + (a if b == a else ref)


def same_cites(items: list[dict], own: str | None = None) -> list[str]:
    """「수행됨」 줄 여럿이 똑같은 근거를 들었으면 문제로 낸다. 표기만 다른 같은 근거도 센다(2026-11-25 부터)."""
    same: dict = {}
    for x in items:
        if x["verdict"] == OK_DONE:
            same.setdefault(tuple(sorted({norm_cite(c, own) for c in x["cites"]})), []).append(x["key"])
    return [f"「{OK_DONE}」 {len(keys)}줄이 똑같은 근거({' · '.join(cites_)})를 들었습니다. 줄마다 그 절차를 수행한 칸을 가리킵니다"
            f"({MAX_SAME_CITE}줄까지 같은 근거를 받습니다)" for cites_, keys in same.items() if len(keys) > MAX_SAME_CITE]


def carry(items: list[dict], old: dict | None) -> int:
    """앞 판의 반영 기록을 새 판정에 잇는다. 판정 · 의견 · 근거가 모두 같을 때만 「반영함」 으로 남긴다.
    돌려주는 값은 앞 판에서 반영한 줄 가운데 문제없음으로 바뀐 줄 수."""
    was = {(x["part"], x["key"]): x for x in (old or {}).get("items", []) if x.get("applied") or x.get("prior")}
    fixed = 0
    for x in items:
        x.setdefault("n", None)
        prev = was.get((x["part"], x["key"]))
        got = (prev or {}).get("applied") or (prev or {}).get("prior")
        keep = bool(got and x["verdict"] not in OK and got.get("sig", sig(prev)) == sig(x))
        if got and "sig" not in got:
            got = {**got, "sig": sig(prev)}
        x["applied"] = got if keep else None            # 앞 판에서 옮긴 줄이 그대로면 두 번 옮기지 않는다
        x["prior"] = got if got and not keep and x["verdict"] not in OK else None   # 내용이 바뀌었으면 다시 고를 수 있다
        fixed += bool(got and x["verdict"] in OK)
    return fixed


def sig(x: dict) -> str:
    """판정 한 줄의 식별값(판정 · 빠진 것 · 근거). 다시 점검했을 때 같은 결함인지, 검토의견에 이미 옮겼는지 가른다."""
    return hashlib.sha256("\x1f".join([str(x["part"]), x["key"], x["verdict"], x["missing"], *sorted(x["cites"])]).encode("utf-8")).hexdigest()[:10]


def stale(root: Path, rec: dict, memo: dict | None = None) -> list[str]:
    """점검 뒤에 바뀌었거나 없어졌거나 새로 생긴 파일(조서와, 근거로 든 다른 조서 · 받은자료). 비어 있으면 최신이다."""
    root = Path(root)
    files = {rec["workpaper_file"]: rec["workpaper_sha256"], **(rec.get("deps") or {})}
    return [f for f, s in files.items() if sha_or_none(root / f, memo) != s]


# ---------------------------------------------------------------- 점검표 엑셀
def summary(rec: dict) -> str:
    c = rec["counts"]
    area = c.get("area", 0)
    s = (f"절차 {c['rows']}줄 가운데 볼 것 {c['todo'] - area}줄 · 문제없음 {c['ok']}줄 · 수행 안 함 {c['skipped']}줄"
         + (f" · 영역 전체에 걸린 볼 것 {area}줄" if area else ""))
    s += f" · 볼 것 가운데 판단 못 함 {c['unknown']}줄" if c.get("unknown") else ""
    return s + (f" · 앞 판에서 반영한 줄 가운데 문제없음으로 바뀐 줄 {c['fixed']}줄" if c.get("fixed") else "")


def applied_text(a: dict | None, prior: dict | None = None) -> str | None:
    if a:
        return f"반영함(검토의견 {a['opinion']}번, {a['by']} {a['at']})"
    return f"앞 판에서 검토의견 {prior['opinion']}번으로 반영함. 이번에 내용이 바뀜" if prior else None


def write_sheet(out: Path, rec: dict, notes: list[str] | None, hint: str, title: str | None = None,
                skipped_head: str | None = "수행 안 함(Part 2 에서 비워 둔 줄)", notes_head: str = "엔진이 표지에서 읽은 것(참고)") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    for col, w in zip("ABCDEFG", (6, 44, 16, 60, 30, 8, 34)):
        ws.column_dimensions[col].width = w
    ws["A1"] = title or f"절차 점검표 {rec['no']}"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = summary(rec)
    ws["A3"] = hint
    ws["A3"].font = Font(size=9, color="666666")
    for c, h in enumerate(HEAD, 1):
        ws.cell(HEAD_ROW, c, h).font = Font(bold=True)
    dv = DataValidation(type="list", formula1=f'"{PICK}"', allow_blank=True)
    ws.add_data_validation(dv)
    r = HEAD_ROW + 1
    for x in (x for x in rec["items"] if x["n"]):
        vals = [x["n"], x["step"], x["verdict"], x["missing"], "\n".join(x["cites"]), None, applied_text(x["applied"], x.get("prior"))]
        for c, val in enumerate(vals, 1):
            ws.cell(r, c, val).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(r, 6).fill = YELLOW
        dv.add(ws.cell(r, 6).coordinate)
        r += 1
    if r == HEAD_ROW + 1:
        ws.cell(r, 2, "볼 것 없음")
        r += 1
    r += 1
    ws.cell(r, 1, "문제없음").font = Font(bold=True)
    for x in (x for x in rec["items"] if not x["n"]):
        r += 1
        ws.cell(r, 2, x["step"])
        ws.cell(r, 3, x["verdict"])
        ws.cell(r, 5, " · ".join(x["cites"]))
    if skipped_head:
        r += 2
        ws.cell(r, 1, skipped_head).font = Font(bold=True)
        for x in rec.get("skipped") or []:
            r += 1
            ws.cell(r, 2, x["step"])
    if notes:
        r += 2
        ws.cell(r, 1, notes_head).font = Font(bold=True)
        for f in notes:
            r += 1
            ws.cell(r, 2, f)
    wb.save(out)
    return out


def sheet_rows(ws, rec: dict) -> dict[int, int]:
    """점검표 「볼 것」 표의 {번호: 행}. 번호 칸이 글로 저장돼도 읽는다. 표가 기록과 다르면 Rejected."""
    want = sorted(x["n"] for x in rec["items"] if x["n"])
    out = {}
    for i, n in enumerate(want):
        r = HEAD_ROW + 1 + i
        v = ws.cell(r, 1).value
        got = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() else \
            int(v.strip()) if isinstance(v, str) and v.strip().isdigit() else None
        if got != n:
            raise Rejected([f"점검표 {r}행의 번호가 색인과 다릅니다({v} · 있어야 할 번호 {n}). 점검표의 줄을 지우거나 옮기지 않습니다. "
                            f"점검을 다시 돌려 점검표를 새로 씁니다"])
        x = next(i for i in rec["items"] if i["n"] == n)
        shown = [text(ws.cell(r, c).value) for c in (2, 3, 4, 5)]
        if shown != [x["step"], x["verdict"], x["missing"], "\n".join(x["cites"])]:
            raise Rejected([f"점검표 {n}번 줄의 내용(절차 · 판정 · 빠진 것 · 근거)이 색인과 다릅니다. 점검표의 글은 고치지 않습니다. "
                            f"보신 내용과 다른 의견이 들어가지 않게 옮기지 않았습니다. 점검을 다시 돌려 점검표를 새로 씁니다"])
        out[n] = r
    return out


def picks(path: Path, rec: dict) -> set[int]:
    """점검표 「반영」 칸에 「예」 가 적힌 번호."""
    if not Path(path).is_file():
        return set()
    wb = load_workbook(path, data_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
    out = {n for n, r in sheet_rows(ws, rec).items() if text(ws.cell(r, 6).value) == PICK}
    wb.close()
    return out


def tag(x: dict) -> str:
    """검토의견에 남기는 식별값. 끊긴 실행을 다시 돌릴 때 이것으로 찾는다."""
    return f"[절차점검 {sig(x)}]"
