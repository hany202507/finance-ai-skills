"""스캔 PDF OCR(kordoc) 저장본과 PDF 글자 얻기(2026-10-18, 「스캔본 AI 판독할 때 kordoc 을 우선 적용」).

글자 층이 없는 PDF 는 kordoc(`npx -y kordoc@^4 <pdf> --ocr`)로 읽어 감사 폴더 `_색인/ocr/<파일 sha256 앞 16자>.md` 에 둔다.
쪽 그림은 그 옆 `images/<같은 16자>/` 에 떨어진다. 해시가 같으면 다시 돌리지 않는다.

PDF 글자를 얻는 곳은 하나다(pdf_pages): 글자 층 → OCR 저장본. 출처를 「text」 · 「ocr」 로 돌려준다.
OCR 글은 판독이고 엔진 판독이 아니다. 숫자 · 날짜는 확인 전(confirmed false)이며, 확인 전 OCR 숫자만으로 이슈 금액을 만들지 않는다.
실측 오독(2026-10-18 실제 회사 자료): 잔고증명 ₩ 를 # 로, 주주명부 숫자 쉼표 · 점(「33,46」 「5.55」), 약정서 손글씨 연도(2024 → 2029).

  ensure(d, docs, enabled)   글자 없는 받은자료 · 영구조서 PDF 에 OCR 을 돌려 저장한다. npx · kordoc 이 없거나 실패하면 한 줄 경고
  find(pdf)                  그 PDF 의 OCR 저장본(md). 감사 폴더의 _색인/ocr 을 위로 올라가며 찾는다(영구조서는 옆 폴더)
  pdf_pages(pdf)             ([(쪽, 글자)], 'text' | 'ocr' | None)
  rows(markdown)             표 줄은 칸 목록, 나머지 줄은 칸 하나인 목록

끄기: `index read --no-ocr` 또는 환경변수 AUDIT_OCR=off. 흉내: 환경변수 AUDIT_OCR_CMD("{pdf}" · "{out}" 자리가 있는 명령,
{out} 에 Markdown 이나 kordoc json 을 쓴다) 또는 모듈 변수 runner(pdf, out_md) -> None. 시험은 실제 kordoc 을 부르지 않는다.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

STORE = "ocr"
HEAD = "OCR(kordoc) 판독, 확인 전"
KORDOC = ["-y", "kordoc@^4"]
TIMEOUT = 600                        # 파일 하나(쪽이 많은 약정서 12쪽이 1분 안쪽, 2026-10-18 실측)
ENV_OFF = "AUDIT_OCR"
ENV_CMD = "AUDIT_OCR_CMD"
PAGE_RE = re.compile(r"^<!--\s*쪽\s*(\d+)\s*-->\s*$", re.M)
IMAGE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")
runner = None                        # 시험 · 다른 OCR: callable(pdf: Path, out_md: Path) -> None


def key(sha: str) -> str:
    return sha[:16]


def store(d: Path) -> Path:
    return Path(d) / "_색인" / STORE


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def enabled() -> bool:
    return os.environ.get(ENV_OFF, "").strip().lower() not in ("off", "0", "no", "false")


# ---------------------------------------------------------------- 돌리기
def _npx() -> str | None:
    return shutil.which("npx") or shutil.which("npx.cmd")


def _write_md(out_md: Path, raw: str, name: str, sha: str) -> None:
    """kordoc 결과(json 또는 Markdown)를 쪽 표시가 있는 Markdown 으로 쓴다."""
    pages, low = [], []
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("pages"), list) and data["pages"]:
        pages = [(int(p.get("pageNumber") or n), p.get("markdown") or "") for n, p in enumerate(data["pages"], 1)]
        low = sorted({int(w["page"]) for w in data.get("warnings") or [] if isinstance(w, dict) and w.get("code") == "OCR_LOW_CONF"
                      and str(w.get("page", "")).isdigit()})
    elif isinstance(data, dict) and isinstance(data.get("markdown"), str):
        pages = [(1, data["markdown"])]
    else:
        pages = _split_images(raw)
    head = [f"<!-- {HEAD}. 원본 {name} · sha256 {key(sha)} · 쪽 {len(pages)} -->"]
    if low:
        head.append(f"<!-- kordoc 낮은 신뢰 쪽: {', '.join(map(str, low))} -->")
    body = [f"<!-- 쪽 {no} -->\n{text.strip()}\n" for no, text in pages]
    out_md.write_text("\n".join(head) + "\n\n" + "\n".join(body), encoding="utf-8")


def _split_images(md: str) -> list[tuple[int, str]]:
    """쪽 표시가 없는 kordoc Markdown. 쪽마다 끝에 쪽 그림 링크가 붙으므로 그 줄로 나눈다(2026-10-18 실측)."""
    if PAGE_RE.search(md):
        return pages_of(md)
    out, cur = [], []
    for ln in md.splitlines():
        cur.append(ln)
        if IMAGE_RE.match(ln.strip()):
            out.append("\n".join(cur))
            cur = []
    if any(x.strip() for x in cur):
        if out:
            out[-1] += "\n" + "\n".join(cur)
        else:
            out.append("\n".join(cur))
    return [(n, t) for n, t in enumerate(out, 1)] or [(1, md)]


def _kordoc(pdf: Path, out_md: Path, sha: str) -> None:
    """실제 kordoc. 한글 경로가 cmd 배치 파일(npx.cmd)을 거치며 깨지지 않게 ASCII 임시 폴더에서 상대 이름으로 돌린다."""
    npx = _npx()
    if not npx:
        raise RuntimeError("npx 가 없습니다(Node.js 설치 필요)")
    with tempfile.TemporaryDirectory(prefix="audit-ocr-") as tmp:
        t = Path(tmp)
        stem = key(sha)
        shutil.copyfile(pdf, t / "in.pdf")
        cmd = [npx, *KORDOC, "in.pdf", "--ocr", "--format", "json", "--image-refs", "-o", f"{stem}.json"]
        r = subprocess.run(cmd, cwd=t, capture_output=True, timeout=TIMEOUT)
        js = t / f"{stem}.json"
        if r.returncode != 0 or not js.exists():
            tail = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or ["출력 없음"]
            raise RuntimeError(f"kordoc 실패(코드 {r.returncode}): {tail[0][:200]}")
        _write_md(out_md, js.read_text(encoding="utf-8"), pdf.name, sha)
        img = t / "images" / stem
        if img.is_dir():
            dst = out_md.parent / "images" / stem
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(img, dst)


def _command(pdf: Path, out_md: Path, sha: str) -> None:
    """환경변수 AUDIT_OCR_CMD 로 준 명령(시험 · 다른 OCR). {out} 에 Markdown 이나 kordoc json 을 쓴다."""
    tmp = out_md.with_suffix(".out")
    toks = shlex.split(os.environ[ENV_CMD], posix=os.name != "nt")
    toks = [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in toks]     # Windows 는 따옴표가 낱말에 남는다
    cmd = [x.replace("{pdf}", str(pdf)).replace("{out}", str(tmp)) for x in toks]
    r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT)
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"OCR 명령 실패(코드 {r.returncode})")
    raw = tmp.read_text(encoding="utf-8")
    tmp.unlink()
    _write_md(out_md, raw, pdf.name, sha)


def run_one(pdf: Path, out_md: Path, sha: str) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    if runner is not None:
        runner(Path(pdf), out_md)
        if not out_md.exists():
            raise RuntimeError("OCR 결과 파일이 없습니다")
        raw = out_md.read_text(encoding="utf-8")
        if not raw.startswith(f"<!-- {HEAD}"):
            _write_md(out_md, raw, Path(pdf).name, sha)
        return
    if os.environ.get(ENV_CMD):
        return _command(Path(pdf), out_md, sha)
    return _kordoc(Path(pdf), out_md, sha)


def ensure(d: Path, docs: dict, on: bool = True, pdfs: list[str] | None = None) -> dict:
    """글자 층이 없는 PDF(pdfs, 감사 폴더 상대 경로)에 OCR 을 돌려 저장한다. 해시가 같은 저장본이 있으면 다시 돌리지 않는다.
    {'made': [...], 'cached': [...], 'failed': [(경로, 까닭)], 'off': bool, 'warning': str | None}"""
    d = Path(d)
    out = {"made": [], "cached": [], "failed": [], "off": False, "warning": None}
    by = {f["path"]: f for f in docs.get("files", [])}
    todo = []
    for rel in pdfs or []:
        f = by.get(rel)
        if not f:
            continue
        md = store(d) / f"{key(f['sha256'])}.md"
        (out["cached"] if md.exists() else todo).append(rel)
    if not todo:
        return out
    if not (on and enabled()):
        out["off"] = True
        out["warning"] = f"OCR 을 끈 채 돌려 글자 없는 PDF {len(todo)}건은 AI 판독 필요로 남깁니다(--no-ocr · AUDIT_OCR=off)"
        return out
    if runner is None and not os.environ.get(ENV_CMD) and not _npx():
        out["failed"] = [(rel, "npx 없음") for rel in todo]
        out["warning"] = f"npx(Node.js)가 없어 kordoc OCR 을 돌리지 못했습니다. 글자 없는 PDF {len(todo)}건은 AI 판독 필요로 남깁니다"
        return out
    for rel in todo:
        f = by[rel]
        p = (d / rel).resolve()
        md = store(d) / f"{key(f['sha256'])}.md"
        try:
            run_one(p, md, f["sha256"])
            out["made"].append(rel)
        except Exception as e:  # noqa: BLE001  kordoc 이 못 읽은 파일은 지금처럼 AI 판독 필요로 남긴다
            if md.exists():
                md.unlink()
            out["failed"].append((rel, str(e)[:200]))
    if out["failed"]:
        out["warning"] = (f"kordoc OCR 이 {len(out['failed'])}건을 읽지 못해 AI 판독 필요로 남깁니다: "
                          + ", ".join(Path(p).name for p, _ in out["failed"][:3]) + (" 외" if len(out["failed"]) > 3 else ""))
    _PAGES.clear()
    return out


# ---------------------------------------------------------------- 찾기 · 읽기
def find(pdf: Path, sha: str | None = None) -> Path | None:
    """그 PDF 의 OCR 저장본. 위로 올라가며 <폴더>/_색인/ocr 와 <폴더>/<하위>/_색인/ocr(영구조서는 감사 폴더 옆이다)를 본다."""
    pdf = Path(pdf).resolve()
    if not pdf.is_file():
        return None
    name = f"{key(sha or sha256(pdf))}.md"
    for anc in list(pdf.parents)[:6]:
        p = anc / "_색인" / STORE / name
        if p.exists():
            return p
        try:
            subs = [c for c in anc.iterdir() if c.is_dir() and not c.name.startswith(".")]
        except OSError:
            continue
        for c in subs:
            p = c / "_색인" / STORE / name
            if p.exists():
                return p
    return None


def pages_of(md: str) -> list[tuple[int, str]]:
    """저장본 Markdown 을 쪽마다 나눈다. 쪽 표시가 없으면 한 쪽으로 본다."""
    marks = list(PAGE_RE.finditer(md))
    if not marks:
        return [(1, md)]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        out.append((int(m.group(1)), md[m.end():end].strip("\n")))
    return out


TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
TD_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.S | re.I)
TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
CUR_RE = re.compile(r"^[#₩￦]\s*(?=\d)")


def _clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = html.unescape(TAG_RE.sub("", s))
    s = s.replace("\\*", "*").replace("\\_", "_").replace("**", "")
    s = CUR_RE.sub("", s.strip())            # 잔고증명 ₩ 를 # 로 읽은 칸(「#968,357」). 금액은 여전히 OCR 값이다
    return re.sub(r"[ \t]+", " ", s).strip()


def rows(md: str) -> list[list[str]]:
    """표 줄(GFM 파이프 · HTML table)은 칸 목록, 나머지 글줄은 칸 하나인 목록. 주석 · 쪽 그림 줄은 뺀다."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out: list[list[str]] = []
    pos = 0
    for m in TABLE_RE.finditer(md):
        out += _text_rows(md[pos:m.start()])
        for tr in TR_RE.findall(m.group(0)):
            out.append([_clean(c) for c in TD_RE.findall(tr)])
        pos = m.end()
    out += _text_rows(md[pos:])
    return [r for r in out if any(c for c in r)]


def _text_rows(s: str) -> list[list[str]]:
    out = []
    for ln in s.splitlines():
        t = ln.strip()
        if not t or IMAGE_RE.match(t):
            continue
        if t.startswith("|"):
            cells = [c.strip() for c in t.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            out.append([_clean(c) for c in cells])
            continue
        t = re.sub(r"^#{1,6}\s+", "", t)
        out.append([_clean(t)])
    return out


def plain(md: str) -> str:
    """pdfread 가 읽는 꼴: 표 칸 하나가 한 줄(PDF 글자 층을 칸마다 줄로 뽑은 것과 같은 꼴)."""
    return "\n".join(c for r in rows(md) for c in r if c)


_PAGES: dict = {}


def ocr_pages(pdf: Path, sha: str | None = None) -> list[tuple[int, str]] | None:
    md = find(pdf, sha)
    if md is None:
        return None
    return [(no, plain(t)) for no, t in pages_of(md.read_text(encoding="utf-8"))]


def pdf_pages(pdf: Path) -> tuple[list[tuple[int, str]], str | None]:
    """PDF 글자. 글자 층이 있으면 그것(text), 없으면 OCR 저장본(ocr), 둘 다 없으면 빈 쪽들과 None."""
    from . import index, reader

    pdf = Path(pdf)
    try:
        st = pdf.stat()
        ck = (str(pdf.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        ck = None
    if ck and ck in _PAGES:
        return _PAGES[ck]
    pages = reader.pdf_text(pdf)
    if any(len(re.sub(r"\s+", "", t)) >= index.NO_TEXT_MIN for _, t in pages):
        got = (pages, "text")
    else:
        o = ocr_pages(pdf)
        got = (o, "ocr") if o else (pages, None)
    if ck:
        _PAGES[ck] = got
    return got
