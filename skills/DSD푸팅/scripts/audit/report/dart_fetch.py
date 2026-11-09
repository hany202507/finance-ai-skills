"""OpenDART 원문 받기와 정기보고서 나누기(2026-10-22 DSD푸팅 실행 시간 P7).

    python -m audit dsd fetch <접수번호 | PDF> [--out 폴더] [--no-prior]

접수번호(14자리)나 DART 에서 받은 PDF(「[한 상장사]반기검토보고서(2026.08.14).pdf」)를 받아 공시서류원본(xml)을 내려받는다.
사업 · 반기 · 분기보고서면 본문에서 연결과 별도의 재무제표 · 주석을 떼어 <접수번호>_연결.xml · <접수번호>_별도.xml 을 쓴다.
작년 비교 보고서(직전 사업보고서, 작년 같은 기간 보고서)도 함께 받아 나눈다(--no-prior 면 받지 않는다).
한 상장사 2026 반기(10-21)에서 세션이 이 일을 스크립트로 그때그때 짜느라 2분이 들었다.

인증키는 환경변수 DART_API_KEY 에서만 읽는다(윈도우는 사용자 환경변수도 본다, tools/dart_api.py 와 같다). 키를 화면 · 파일 · 오류 글에 적지 않는다.
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from . import dsd
from .base import norm

BASE = "https://opendart.fss.or.kr/api/"
PERIODIC = ("사업보고서", "반기보고서", "분기보고서")


class FetchError(Exception):
    """받기 실패. 글에 인증키를 넣지 않는다."""


# ---------------------------------------------------------------- OpenDART
def _key() -> str:
    k = os.environ.get("DART_API_KEY")
    if not k:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                k = winreg.QueryValueEx(h, "DART_API_KEY")[0]
        except (ImportError, OSError):
            k = None
    if not k:
        raise FetchError("DART_API_KEY 가 없습니다. opendart.fss.or.kr 에서 발급받아 환경변수로 넣어 주십시오")
    return k


def _get(name: str, params: dict, tries: int = 3) -> bytes:
    url = BASE + name + "?" + urllib.parse.urlencode({"crtfc_key": _key(), **params})
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except OSError as e:                           # 오류 글에 주소(키가 든)를 넣지 않는다
            if n == tries - 1:
                raise FetchError(f"OpenDART {name} 호출 실패: {type(e).__name__}") from None
            time.sleep(2 + 2 * n)
    return b""


def _call(name: str, **params) -> dict:
    try:
        d = json.loads(_get(name + ".json", params).decode("utf-8"))
    except ValueError:
        raise FetchError(f"OpenDART {name}: 응답을 읽지 못했습니다") from None
    if d.get("status") not in ("000", "013"):
        raise FetchError(f"OpenDART {name}: {d.get('status')} {d.get('message')}")
    return d


def _zipped(name: str, **params) -> zipfile.ZipFile:
    raw = _get(name + ".xml", params)
    if raw[:2] != b"PK":
        raise FetchError(f"OpenDART {name}: {raw[:200].decode('utf-8', 'replace')}")
    return zipfile.ZipFile(io.BytesIO(raw))


def _cache_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "audit-dart"


def corp_code(name: str) -> str:
    """회사 이름 → OpenDART 고유번호. 회사 목록(CORPCODE.xml)은 30일 동안 캐시에 두고 쓴다. 같은 이름이 여럿이면 상장사를 고른다."""
    p = _cache_dir() / "CORPCODE.xml"
    if not p.exists() or time.time() - p.stat().st_mtime > 30 * 86400:
        z = _zipped("corpCode")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(z.read(z.namelist()[0]))
    want = norm(name).replace("(주)", "").replace("㈜", "").replace("주식회사", "")
    hits = []
    for e in ET.fromstring(p.read_bytes()).iter("list"):
        n = norm(e.findtext("corp_name")).replace("(주)", "").replace("㈜", "").replace("주식회사", "")
        if n == want:
            hits.append((bool((e.findtext("stock_code") or "").strip()), e.findtext("corp_code")))
    if not hits:
        raise FetchError(f"OpenDART 회사 목록에 「{name}」 이 없습니다. 접수번호를 주십시오")
    return sorted(hits, reverse=True)[0][1]


def filings(corp: str, start: date, end: date, kind: str = "") -> list[dict]:
    """그 회사의 공시 목록(최종 판만). [{rcept_no, rcept_dt, report_nm}]. kind 를 주면 공시 종류로 거른다(정기공시 A, 외부감사관련 F).
    큰 회사는 한 해 공시가 수백 건이라 여러 쪽을 읽는다(한 상장사 2026 은 첫 100건에 사업보고서가 없었다)."""
    ty = {"사업보고서": "A", "반기보고서": "A", "분기보고서": "A", "감사보고서": "F", "연결감사보고서": "F"}.get(kind)
    out, page = [], 1
    while page <= 20:
        d = _call("list", corp_code=corp, bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"), last_reprt_at="Y", page_count=100,
                  page_no=page, **({"pblntf_ty": ty} if ty else {}))
        out += [{k: x.get(k, "") for k in ("rcept_no", "rcept_dt", "report_nm", "corp_name")} for x in d.get("list", [])]
        if page >= int(d.get("total_page") or 1):
            break
        page += 1
    return out


def download(rcept_no: str, out: Path) -> list[Path]:
    """공시서류원본 zip 을 풀어 out 에 둔다. 본문 xml 이 맨 앞이다."""
    z = _zipped("document", rcept_no=rcept_no)
    out.mkdir(parents=True, exist_ok=True)
    got = []
    for n in z.namelist():
        p = out / Path(n).name
        p.write_bytes(z.read(n))
        got.append(p)
    return sorted(got, key=lambda p: (p.stem != rcept_no, p.name))


# ---------------------------------------------------------------- 접수번호 찾기
_RCEPT = re.compile(r"(?<!\d)(20\d{12})(?!\d)")
_PDF_NAME = re.compile(r"\[(?P<corp>[^\]]+)\]\s*(?P<report>[^(]+?)\s*\((?P<y>\d{4})\.(?P<m>\d{1,2})\.(?P<d>\d{1,2})\)")


def _kind(report: str) -> str:
    """보고서 이름의 종류. 「반기검토보고서」 는 반기보고서에 붙은 검토보고서다."""
    r = norm(report)
    for k in ("사업보고서", "반기", "분기", "연결감사보고서", "감사보고서"):
        if k in r:
            return {"반기": "반기보고서", "분기": "분기보고서"}.get(k, k)
    return r


def from_pdf(path: Path) -> tuple[str, str]:
    """DART 에서 받은 PDF 의 접수번호. (접수번호, 찾은 방법). 파일 이름이나 PDF 글에 접수번호가 있으면 그것을,
    없으면 파일 이름의 「[회사]보고서(접수일)」 로 그날 그 회사의 공시를 찾는다."""
    path = Path(path)
    m = _RCEPT.search(path.name)
    if m:
        return m.group(1), "파일 이름의 접수번호"
    try:
        from ..reader import pdf_text

        head = " ".join(t for _, t in pdf_text(path)[:3])
    except Exception:                                 # 글이 없는 PDF(스캔)도 파일 이름으로는 찾는다
        head = ""
    m = re.search(r"rcpNo=(\d{14})", head) or _RCEPT.search(head)
    if m:
        return m.group(1), "PDF 글의 접수번호"
    m = _PDF_NAME.search(path.stem)
    if not m:
        raise FetchError(f"{path.name}: 접수번호를 찾지 못했습니다. 파일 이름이 「[회사]보고서(접수일).pdf」 꼴이 아니면 접수번호(14자리)를 주십시오")
    day = date(int(m["y"]), int(m["m"]), int(m["d"]))
    kind = _kind(m["report"])
    hits = [x for x in filings(corp_code(m["corp"]), day, day, kind) if _kind(x["report_nm"]) == kind]
    if len(hits) != 1:
        raise FetchError(f"{path.name}: {day} 에 「{m['corp']}」 의 {kind} 가 {len(hits)}건입니다. 접수번호를 주십시오"
                         + (" (" + ", ".join(f"{x['rcept_no']} {x['report_nm']}" for x in hits) + ")" if hits else ""))
    return hits[0]["rcept_no"], f"파일 이름의 회사 · 접수일({m['corp']} {day})"


_PERIOD = re.compile(r"\((\d{4})\.(\d{2})\)")


def priors(corp: str, report_nm: str, rcept_dt: str) -> list[dict]:
    """작년 비교 보고서. 반기 · 분기보고서는 직전 사업보고서와 작년 같은 기간 보고서, 사업 · 감사보고서는 작년 같은 보고서.
    dsd foot --prior 에 이 차례로 준다. 보고 기간(「(2025.06)」)으로 찾고 접수일 창은 넉넉히 둔다. 정정 공시는 최종 판(last_reprt_at)만 온다."""
    m = _PERIOD.search(report_nm)
    kind = _kind(report_nm)
    if not m or not rcept_dt:
        return []
    y, mon = int(m.group(1)), int(m.group(2))
    filed = date(int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))
    want = []
    if kind in ("반기보고서", "분기보고서"):
        want.append(("사업보고서", f"({y - 1}.12)", date(y, 1, 1), filed))
    want.append((kind, f"({y - 1}.{mon:02d})", date(y - 1, mon, 1), min(filed, date(y, mon, 1) + timedelta(days=365))))
    out = []
    for k, period, a, b in want:
        hits = [x for x in filings(corp, a, b, k) if _kind(x["report_nm"]) == k and period in x["report_nm"]]
        if hits:
            out.append(max(hits, key=lambda x: x["rcept_no"]))
    return out


# ---------------------------------------------------------------- 정기보고서 나누기(tools/dart_periodic_split.py 에서 옮김)
_NUM = re.compile(r"^\s*\d+(?:-\d+)?\.\s*")              # 「2-1. 」 「25. 」
_KIND = re.compile(r"\s*\((?:연결|별도)\)\s*$")          # 「25. 재무위험관리 (연결)」


def _title(e) -> str:
    t = e.find("TITLE")
    return dsd._text(t) if t is not None else ""


def _sections(root) -> dict:
    """{(연결|별도, 재무제표|주석): SECTION-2}"""
    out = {}
    for s in root.iter("SECTION-2"):
        t = norm(_NUM.sub("", _title(s)))
        kind = "연결" if t.startswith("연결") else "별도"
        t = t.replace("연결", "")
        if t == "재무제표":
            out[(kind, "재무제표")] = s
        elif t in ("재무제표주석", "재무제표에대한주석"):
            out[(kind, "주석")] = s
    return out


def _clean_titles(sec, statements: bool) -> None:
    for t in sec.iter("TITLE"):
        text = dsd._text(t)
        new = _KIND.sub("", text)
        if statements:
            new = _NUM.sub("", new)                       # 「2-1. 연결 재무상태표」 → 「연결 재무상태표」
        if new != text:
            for c in list(t):
                t.remove(c)
            t.text = new


def split(path: Path) -> dict:
    """정기보고서 본문 → {연결|별도: xml bytes}. 그 재무제표가 없으면 그 키가 없다. 숫자와 글자는 바꾸지 않는다."""
    root = ET.fromstring(dsd.lenient_xml(Path(path).read_bytes()))
    secs = _sections(root)
    out = {}
    for kind in ("연결", "별도"):
        fs, notes = secs.get((kind, "재무제표")), secs.get((kind, "주석"))
        if fs is None or not any(True for _ in fs.iter("TABLE")):
            continue
        doc = ET.Element("DOCUMENT")
        name = root.find("DOCUMENT-NAME")
        if name is not None:
            doc.append(copy.deepcopy(name))
        body = ET.SubElement(doc, "BODY")
        for src, title in ((fs, "재무제표"), (notes, "주석")):
            if src is None:
                continue
            s1 = ET.SubElement(body, "SECTION-1")
            ET.SubElement(s1, "TITLE").text = title
            for c in src:
                if c.tag != "TITLE":
                    s1.append(copy.deepcopy(c))
            _clean_titles(s1, title == "재무제표")
        out[kind] = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding="utf-8")
    return out


def doc_name(path: Path) -> str:
    m = re.search(rb"<DOCUMENT-NAME[^>]*>([^<]*)<", Path(path).read_bytes()[:8000])
    return m.group(1).decode("utf-8", "replace").strip() if m else ""


def corp_of(path: Path) -> str:
    """원문 머리의 회사 고유번호(COMPANY-NAME AREGCIK)."""
    m = re.search(rb'AREGCIK="(\d{8})"', Path(path).read_bytes()[:8000])
    return m.group(1).decode() if m else ""


def fetch(rcept_no: str, out: Path, with_prior: bool = True) -> dict:
    """접수번호 하나와(with_prior 면) 작년 비교 보고서를 받는다. 각각 out/원문_<접수번호>/ 에 둔다.
    {main: fetch_one 결과, priors: [fetch_one 결과 + report_nm]}"""
    main = fetch_one(rcept_no, Path(out) / f"원문_{rcept_no}")
    res = {"main": main, "priors": []}
    corp = corp_of(main["main"])
    if with_prior and corp:
        day = date(int(rcept_no[:4]), int(rcept_no[4:6]), int(rcept_no[6:8]))
        me = next((x for x in filings(corp, day, day) if x["rcept_no"] == rcept_no), None)
        main["report_nm"] = me["report_nm"] if me else main["name"]
        for x in priors(corp, me["report_nm"], me["rcept_dt"]) if me else []:
            res["priors"].append(dict(fetch_one(x["rcept_no"], Path(out) / f"원문_{x['rcept_no']}"), report_nm=x["report_nm"]))
    return res


def fetch_one(rcept_no: str, out: Path) -> dict:
    """하나를 받아 정기보고서면 나눈다. {rcept_no, files, main, name, split: {연결|별도: 경로}}"""
    files = download(rcept_no, out)
    main = files[0]
    name = doc_name(main)
    parts = {}
    if any(k in name for k in PERIODIC):
        for kind, raw in split(main).items():
            p = out / f"{rcept_no}_{kind}.xml"
            p.write_bytes(raw)
            parts[kind] = p
    return {"rcept_no": rcept_no, "files": files, "main": main, "name": name, "split": parts}
