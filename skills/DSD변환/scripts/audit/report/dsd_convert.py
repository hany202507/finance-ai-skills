"""공시 원문 xml → 편집기 dsd(2026-11-05, DSD변환). `python -m audit dsd convert <접수번호 | PDF | xml> [--roll] [--bare] [--out 폴더]`.

DART 공시서류원본(xml)은 편집기 dsd 의 contents.xml 과 같은 dart4 꼴인데 편집기용 요소를 걷어 낸 판이다(규격 5.1절).
같은 보고서의 공시 원문 ↔ 편집기 저장 dsd 짝 두 건(한 회사의 두 해)을 견주어 다른 곳을 다섯으로 정리했고, 변환은 그 다섯만 되돌린다.
본문(문단 · 표 · 칸 · 숫자 · 서식 표시)은 바이트 그대로 둔다. 원고로 쪼개 틀에 다시 붓는 틀로 쓰기(dsd_frame)와 다르다.

  1. DOCUMENT-HEADER     원문은 DOCUMENT-NAME · FORMULA-VERSION · COMPANY-NAME · SUMMARY 를 감싸개 없이 둔다 → <DOCUMENT-HEADER AEXT-CLASS="Y"> 로 감싼다
  2. TOC                 원문은 목차 제목(TITLE ATOC="N")부터 쪽 나눔까지를 감싸개 없이 둔다 → <TOC> 로 감싼다
  3. INSERTION           원문은 LIBRARY 만 남겼다 → 틀(definitions/dart_dsd_frame.xml, 편집기 샘플)의 삽입 위치 13곳을 같은 차례로 되살리고,
                         원문 LIBRARY 는 맞는 삽입 위치 안에 FILENAME 을 붙여 넣는다(AFREQUENCY="1"). 빈 삽입 위치는 AFREQUENCY="0"
  4. WARNING             편집기 안내문 둘(IFRS 적용기업 · 내부회계관리제도 감사의견 대상)을 틀 자리에 둔다
  5. ENG                 공시 때 붙는 영문 이름 속성. LIBRARY 밖의 ENG 는 뺀다(편집기 샘플에는 라이브러리가 넣은 재무제표 제목의 ENG 만 있다)

엄밀하지 않은 원문(&cr; 개체, 글자 안 꺾쇠)은 dsd.lenient_xml 로 먼저 고친다. 원문의 빈 문단 줄바꿈(&cr;)은 공시 때 빠져 되살리지 않는다.
요약 코드(SUMMARY)는 원문 값 그대로 둔다(원문 그대로 변환이 목적이다. 다음 기수 초안(--roll)은 원고 검사에 「요약 코드」 를 적는다).

연결 감사보고서(서식 00761)는 편집기 샘플이 없어 별도(00760) 틀의 서식 코드 · 이름을 연결로 바꾼 추정 틀을 쓴다. 결과에 「추정」 으로 적는다.
--bare 는 1번과 meta.xml 만 하고 나머지는 원문 그대로 둔다(편집기가 뼈대 없는 파일을 받는지 견줄 때).

    r = convert(raw)          Result. r.contents · r.meta(바이트), r.form(00760 · 00761), r.notes, r.counts
    write(path, r, src_sha)   dsd 로 쓴다(zip 주석에 「원문변환」 표시)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import dsd
from .dsd_build import zip_dsd
from .dsd_source import Node, Source

STAMP = "원문변환"
FORMS = {"00760": "감사보고서", "00761": "연결감사보고서"}
HEADER_TAGS = ("DOCUMENT-NAME", "FORMULA-VERSION", "COMPANY-NAME", "SUMMARY")
_ENG = re.compile(rb'\s+ENG="[^"]*"')
_FS = re.compile(r"^[PL](BS|IS|EF|CF)")             # 재무제표 표 묶음 ACLASS(P 별도 · L 연결) → 틀 삽입 위치
FS_SLOT = {"BS": "BS", "IS": "IS", "EF": "PEF", "CF": "CF"}
LINK_NAMES = (("재무상태표", "연결재무상태표"), ("손익계산서", "연결손익계산서"), ("포괄손익계산서", "연결포괄손익계산서"),
              ("자본변동표", "연결자본변동표"), ("현금흐름표", "연결현금흐름표"))


@dataclass
class Slot:
    key: str                     # 정정 · 감사보고서 · BS · NOTE · BS-1 · IS · IS-1 · PEF · CF · CF-1 · 부속명세서 · 내부회계 · 중요성
    place: str                   # BODY · FS(재무제표 절 안) · EXT(외부감사 실시내용 절 끝)
    open_tag: bytes              # <INSERTION …>(AFREQUENCY 는 쓸 때 정한다)
    comment: bytes               # <COMMENT>…</COMMENT>
    liblist: bytes               # <LIBRARYLIST>…</LIBRARYLIST>
    filename: bytes | None       # <FILENAME ATYPE="dsl">…</FILENAME>(틀에 LIBRARY 가 있던 곳)


@dataclass
class Frame:
    slots: list
    warn_ifrs: bytes
    warn_iacs: bytes


@dataclass
class Result:
    contents: bytes
    meta: bytes
    form: str
    company: str
    period_end: str
    notes: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    breaks: str = "없음"                  # 줄바꿈: 화면(공시 화면으로 되살림) · 없음(2026-11-08 D1)


# ---------------------------------------------------------------- 틀
def _slot_key(liblist: str, place: str) -> str:
    m = re.search(r"_([A-Z]+(?:-1)?)#", liblist)
    if m:
        return m.group(1)
    for k in ("정정", "감사보고서", "부속명세서", "내부회계", "중요성"):
        if k in liblist:
            return k
    return liblist


def frame(form: str = "00760") -> Frame:
    """틀의 삽입 위치 13곳과 안내문 둘. 연결(00761)은 서식 코드와 재무제표 이름을 연결로 바꾼 추정 틀."""
    raw = dsd.FRAME.read_bytes()
    src = Source(raw)
    slots, warns = [], []
    for n in src.nodes:
        if n.tag == "WARNING":
            warns.append(src.outer(n))
        if n.tag != "INSERTION":
            continue
        title = n.parent.find("TITLE") if n.parent is not None else None
        assoc = title.get("AASSOCNOTE") if title is not None else None
        place = {"D-0-0-0-0": "FS", "D-0-2-0-0": "EXT"}.get(assoc or "", "BODY")
        lib = n.find("LIBRARY")
        fn = lib.find("FILENAME") if lib is not None else None
        liblist = src.text(n.find("LIBRARYLIST"))
        slots.append(Slot(_slot_key(liblist, place), place, raw[n.s:n.se], src.outer(n.find("COMMENT")),
                          src.outer(n.find("LIBRARYLIST")), src.outer(fn) if fn is not None else None))
    fr = Frame(slots, warns[0], warns[1])
    if form == "00761":
        fr = _link_frame(fr)
    return fr


def _link_frame(fr: Frame) -> Frame:
    def sub(b: bytes | None) -> bytes | None:
        if b is None:
            return None
        s = b.decode("utf-8").replace("00760", "00761")
        for a, c in LINK_NAMES:
            s = re.sub(rf"(?<!연결)(?<!포괄){a}", c, s)
        return s.encode("utf-8")

    return Frame([Slot(x.key, x.place, x.open_tag, sub(x.comment), sub(x.liblist), sub(x.filename)) for x in fr.slots],
                 fr.warn_ifrs, fr.warn_iacs)


# ---------------------------------------------------------------- 원문 읽기
def _lib_key(src: Source, lib: Node) -> str | None:
    """원문 LIBRARY 가 들어갈 틀 삽입 위치."""
    kid = next((c for c in lib.kids), None)
    if kid is None:
        return None
    if kid.tag == "CORRECTION":
        return "정정"
    if kid.tag == "TABLE-GROUP":
        m = _FS.match(kid.get("ACLASS") or "")
        return FS_SLOT[m.group(1)] if m else None
    if kid.tag == "SECTION-1":
        t = kid.find("TITLE")
        if t is None:
            return None
        if t.get("AASSOCNOTE") == "D-0-0-1-0":
            return "감사보고서"
        text = re.sub(r"\s+", "", src.text(t))
        for k in ("내부회계", "부속명세서", "중요성"):
            if k in text:
                return k
    if kid.tag == "SECTION-2":
        # 「5. 감사인의 중요성 금액」 은 편집기 라이브러리(00760@6_0#70_감사인의중요성금액.dsl)가 LIBRARY > SECTION-2 꼴이다.
        # SECTION-1 만 보던 때는 삽입 위치 밖에 남아 편집기 규격이 막았다(2026-11-09 공개 원문 표본 FY2025 20건 중 1건)
        t = kid.find("TITLE")
        if t is not None and (t.get("AASSOCNOTE") == "D-0-2-5-0" or "중요성금액" in re.sub(r"\s+", "", src.text(t))):
            return "중요성"
    return None


def _section(body: Node, assoc: str) -> Node | None:
    for c in body.kids:
        if c.tag == "SECTION-1":
            t = c.find("TITLE")
            if t is not None and t.get("AASSOCNOTE") == assoc:
                return c
    return None


def _eol(raw: bytes) -> bytes:
    crlf = raw.count(b"\r\n")
    return b"\r\n" if crlf * 2 >= raw.count(b"\n") else b"\n"


def _set_freq(tag: bytes, filled: bool) -> bytes:
    return re.sub(rb'AFREQUENCY="\d"', b'AFREQUENCY="%s"' % (b"1" if filled else b"0"), tag)


# ---------------------------------------------------------------- 변환
def convert(raw: bytes, bare: bool = False, view: str | None = None) -> Result:
    """view 는 같은 보고서의 공시 화면 HTML 글이다. 있으면 원문에서 빠진 문단 · 칸 안 줄바꿈을 화면대로 되살린다(dsd_breaks.restore)."""
    from . import dsd_breaks

    fixed = dsd.lenient_xml(raw)
    restored = None
    if view:
        fixed, restored = dsd_breaks.restore(fixed, view)
    src = Source(fixed)
    root = src.root
    if root is None or root.tag != "DOCUMENT":
        raise ValueError("DART 원문 xml 이 아닙니다(루트가 DOCUMENT 가 아님)")
    if "dart3" in (root.get("xsi:noNamespaceSchemaLocation") or ""):
        raise ValueError("옛 dart3 꼴 원문(2019년 무렵 이전 공시)은 바꾸지 않는다. 지금 편집기 서식(dart4)과 절 구성이 다르다")
    name =root.find("DOCUMENT-NAME") or (root.find("DOCUMENT-HEADER").find("DOCUMENT-NAME") if root.find("DOCUMENT-HEADER") else None)
    form = (name.get("ACODE") if name is not None else "") or ""
    if form not in FORMS:
        raise ValueError(f"감사보고서(00760) · 연결감사보고서(00761) 원문만 바꾼다. 이 원문의 서식 코드: {form or '없음'}"
                         + (" (사업 · 반기 · 분기보고서 안의 감사보고서는 편집기 서식이 다르다)" if form else ""))
    eol = _eol(fixed)
    edits: list[tuple[int, int, bytes]] = []
    notes: list[str] = []
    counts = {"ENG 뺌": 0, "삽입 위치": 0, "넣은 LIBRARY": 0, "맞는 자리 없는 LIBRARY": 0}

    # 1. DOCUMENT-HEADER
    if root.find("DOCUMENT-HEADER") is None:
        hd = [c for c in root.kids if c.tag in HEADER_TAGS]
        if hd:
            edits.append((hd[0].s, hd[0].s, b'<DOCUMENT-HEADER AEXT-CLASS="Y">' + eol))
            edits.append((hd[-1].e, hd[-1].e, eol + b"</DOCUMENT-HEADER>"))
    company = src.text(root.find("COMPANY-NAME") or Node("", {}, 0)).strip() if root.find("COMPANY-NAME") is not None else ""
    if not company:
        hdr = root.find("DOCUMENT-HEADER")
        cn = hdr.find("COMPANY-NAME") if hdr is not None else None
        company = src.text(cn).strip() if cn is not None else ""
    period_end = _period_end(src)
    meta = _meta(src, form, company, eol)
    if bare:
        notes.append("뼈대 없이(--bare): DOCUMENT-HEADER 와 meta.xml 만 더했다. 편집기 삽입 위치 · 목차 감싸개 · 안내문이 없다")
        return Result(src.apply(edits), meta, form, company, period_end, notes, counts, "화면" if restored else "없음")

    body = root.find("BODY")
    if body is None:
        raise ValueError("원문에 BODY 가 없습니다")
    fr = frame(form)
    if form == "00761":
        notes.append("연결 감사보고서: 편집기 샘플이 없어 별도 틀의 삽입 위치 이름을 연결로 바꾼 추정 틀을 썼다. 편집기로 열어 확인한다")

    # 5. ENG(LIBRARY 밖)
    for n in src.nodes:
        if b"ENG=" not in fixed[n.s:n.se]:
            continue
        p, inside = n.parent, False
        while p is not None:
            if p.tag == "LIBRARY":
                inside = True
                break
            p = p.parent
        if not inside:
            tag = fixed[n.s:n.se]
            new = _ENG.sub(b"", tag)
            if new != tag:
                edits.append((n.s, n.se, new))
                counts["ENG 뺌"] += 1

    # 원문 LIBRARY → 삽입 위치
    libs: dict[str, Node] = {}
    for n in src.nodes:
        if n.tag == "LIBRARY":
            if n.find("FILENAME") is not None:
                continue
            k = _lib_key(src, n)
            if k is None or k in libs:
                counts["맞는 자리 없는 LIBRARY"] += 1
                kid = n.kids[0] if n.kids else None
                notes.append(f"맞는 삽입 위치를 찾지 못한 LIBRARY 를 그대로 두었다: {kid.tag if kid else '빈 LIBRARY'} "
                             f"{(kid.get('ACLASS') or '') if kid else ''}".rstrip())
                continue
            libs[k] = n

    def slot_bytes(sl: Slot, lib: Node | None) -> tuple[bytes, bytes]:
        """(여는 쪽, 닫는 쪽). lib 이 있으면 그 앞뒤에, 없으면 빈 삽입 위치 하나(닫는 쪽 b"")."""
        counts["삽입 위치"] += 1
        head = _set_freq(sl.open_tag, lib is not None) + eol + sl.comment + eol + sl.liblist + eol
        if lib is None:
            return head + b"</INSERTION>" + eol + eol, b""
        counts["넣은 LIBRARY"] += 1
        return head, b"</INSERTION>"

    def put(sl: Slot, at: int) -> None:
        lib = libs.pop(sl.key, None)
        if lib is None:
            a, _ = slot_bytes(sl, None)
            edits.append((at, at, a))
            return
        a, b = slot_bytes(sl, lib)
        fn = sl.filename
        if fn is None:
            fn = b'<FILENAME ATYPE="dsl">' + _file_guess(sl) + b"</FILENAME>"
            notes.append(f"「{sl.key}」 삽입 위치의 라이브러리 파일 이름(FILENAME)은 편집기 샘플에 없어 추정했다")
        edits.append((lib.s, lib.s, a))
        edits.append((lib.se, lib.se, eol + fn))
        edits.append((lib.e, lib.e, eol + b))

    by = {sl.key: sl for sl in fr.slots}
    fs_sec = _section(body, "D-0-0-0-0")
    ext_sec = _section(body, "D-0-2-0-0")
    cover = body.find("COVER")
    if cover is None or fs_sec is None or ext_sec is None:
        raise ValueError("원문에서 표지 · (첨부)재무제표 · 외부감사 실시내용 절을 찾지 못했다")

    # BODY 앞: 정오표(정정 LIBRARY 가 있으면 그것을 넣는다)
    first = body.kids[0]
    corr = libs.get("정정")
    put(by["정정"], corr.s if corr is not None else first.s)

    # 2. TOC 와 감사인의 감사보고서
    toc = next((c for c in body.kids if c.tag == "TITLE" and c.get("ATOC") == "N"), None)
    after_toc = None
    if toc is not None and body.find("TOC") is None:
        i = body.kids.index(toc)
        end = None
        for c in body.kids[i + 1:]:
            if c.tag in ("LIBRARY", "SECTION-1", "INSERTION"):
                break
            end = c
            if c.tag == "PGBRK":
                break
        last = end or toc
        edits.append((toc.s, toc.s, b"<TOC>" + eol))
        edits.append((last.e, last.e, eol + b"</TOC>" + eol))
        after_toc = last.e
    elif body.find("TOC") is not None:
        after_toc = body.find("TOC").e
    else:
        notes.append("목차(TITLE ATOC=\"N\")가 없어 목차 감싸개를 두지 않았다")
        after_toc = cover.e
    rep = libs.get("감사보고서")
    put(by["감사보고서"], rep.s if rep is not None else (after_toc if after_toc is not None else fs_sec.s))

    # 재무제표 절 안: 안내문 · 재무제표 삽입 위치 8곳
    fs_keys = [sl.key for sl in fr.slots if sl.place == "FS"]
    fs_libs = [libs[k] for k in fs_keys if k in libs and libs[k].parent is fs_sec]
    notes_sec = fs_sec.find("SECTION-2")
    anchor = min((x.s for x in fs_libs), default=(notes_sec.s if notes_sec is not None else fs_sec.es))
    # 안내문은 재무제표 표지 쪽 나눔 바로 뒤(편집기 샘플: PGBRK · WARNING · 빈 P · 재무상태표 삽입 위치)
    cover2 = next((c for c in fs_sec.kids if c.tag == "TABLE-GROUP" and c.get("ACLASS") == "COVER2"), None)
    brk = next((c for c in fs_sec.kids if c.tag == "PGBRK" and (cover2 is None or c.s > cover2.s) and c.e <= anchor), None)
    warn_at = brk.e if brk is not None else anchor
    edits.append((warn_at, warn_at, (eol if brk is not None else b"") + fr.warn_ifrs + (b"" if brk is not None else eol + eol)))
    if not fs_libs:
        notes.append("재무제표가 라이브러리 표가 아니라 직접 만든 표다(K-IFRS 적용 회사가 흔하다). 재무제표 삽입 위치는 비워 두었다")
    pos = anchor
    for k in fs_keys:
        lib = libs.get(k)
        if lib is not None and lib.parent is fs_sec:
            put(by[k], lib.s)
            pos = lib.e
        else:
            if lib is not None:
                libs.pop(k)
                notes.append(f"「{k}」 라이브러리가 재무제표 절 밖에 있어 삽입 위치에 넣지 않았다")
            put(by[k], pos)

    # 재무제표 절 뒤: 부속명세서 · 내부회계 · 안내문
    tail = fs_sec.e
    for k in ("부속명세서", "내부회계"):
        lib = libs.get(k)
        if lib is not None:
            put(by[k], lib.s)
            tail = lib.e
        else:
            put(by[k], tail)
    edits.append((ext_sec.s, ext_sec.s, fr.warn_iacs + eol + eol))

    # 외부감사 실시내용 절 끝: 중요성 금액
    lib = libs.get("중요성")
    if lib is not None:
        put(by["중요성"], lib.s)
    else:
        put(by["중요성"], ext_sec.es)

    contents = src.apply(edits)
    if libs:
        for k in libs:
            notes.append(f"「{k}」 라이브러리를 삽입 위치에 넣지 못했다")
    imgs = [m.decode("utf-8", "replace").strip() for m in re.findall(rb"<IMG\b[^>]*>([^<]*)</IMG>", contents)]
    if imgs:                                 # 공시서류원본 zip 에는 그림 파일이 없다(2026-11-07 한 상장사 내부회계 운영실태보고서)
        counts["images"] = len(imgs)
        notes.append(f"그림 {len(imgs)}개({', '.join(imgs[:2])}{' 등' if len(imgs) > 2 else ''})는 공시 원문에 그림 파일이 없어 dsd 에 들어가지 않았다. "
                     "편집기 파일형식 검사가 「이미지 파일 형식이 올바르지 않습니다」 로 막는다. 회사에서 그림 파일을 받아 편집기에서 다시 넣는다")
    if restored:
        counts["줄바꿈 되살림"] = restored.get("넣은 줄바꿈", 0)
        counts["빈칸 되살림"] = restored.get("넣은 빈칸", 0)
    else:
        notes.append("공시 화면이 없어 문단 · 칸 안 줄바꿈을 되살리지 못했다(공시 원문 xml 에는 줄바꿈이 없다). 문장 검토는 붙음 · 띄어쓰기 규칙을 줄여 돈다")
    return Result(contents, meta, form, company, period_end, notes, counts, "화면" if restored else "없음")


def _file_guess(sl: Slot) -> bytes:
    m = re.search(rb"#\*([^<]*?)\.dsl", sl.liblist)
    return m.group(1) if m else sl.key.encode("utf-8")


def _period_end(src: Source) -> str:
    for n in src.nodes:
        if n.tag == "TU" and n.get("AUNIT") == "PERIODTO":
            return n.get("AUNITVALUE") or ""
    return ""


def _meta(src: Source, form: str, company: str, eol: bytes) -> bytes:
    def q(s):
        return str(s or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    cik, docver = "", dsd.FORMULA[1]
    for n in src.nodes:
        if n.tag == "COMPANY-NAME":
            cik = n.get("AREGCIK") or ""
        if n.tag == "FORMULA-VERSION":
            docver = src.text(n).strip() or docver
    corr = "Y" if any(n.tag == "CORRECTION" for n in src.nodes) else "N"
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', "<METAINFO>",
             f'\t<GENERATOR schema="dart4.xsd" editver="{dsd.EDITVER}"/>',
             f'\t<DOCUMENT-HEADER regcik="{q(cik)}" regname="{q(company)}"/>',
             f'\t<DOCUMENT-INFO docver="{q(docver)}" bsn-id="{form}" rpt-id="{form}" doc-id="{form}" iscorrection="{corr}"/>',
             '\t<FILE-INFO date="" size="" rnnumber="" rncheck="" rnimgfile=""/>', "</METAINFO>"]
    return ("\r\n".join(lines)).encode("utf-8")


# ---------------------------------------------------------------- 쓰기 · 검사
def write(path: Path, r: Result, src_sha: str) -> Path:
    stamp = json.dumps({STAMP: src_sha, "서식": r.form, "줄바꿈": r.breaks}, ensure_ascii=False).encode("utf-8")
    return zip_dsd(Path(path), r.contents, r.meta, stamp)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strip_editor(contents: bytes) -> bytes:
    """변환이 더한 것을 걷어 낸 본문(검사용). 결과가 lenient_xml(원문) 에서 ENG 만 뺀 것과 같아야 한다."""
    s = contents
    s = re.sub(rb"<INSERTION [^>]*>\s*<COMMENT>[^<]*</COMMENT>\s*<LIBRARYLIST>[^<]*</LIBRARYLIST>\s*</INSERTION>\s*", b"", s)
    s = re.sub(rb"<INSERTION [^>]*>\s*<COMMENT>[^<]*</COMMENT>\s*<LIBRARYLIST>[^<]*</LIBRARYLIST>\s*", b"", s)
    s = re.sub(rb"\s*</INSERTION>", b"", s)
    s = re.sub(rb"(<LIBRARY>)\s*<FILENAME [^>]*>[^<]*</FILENAME>", rb"\1", s)
    s = re.sub(rb"<WARNING>.*?</WARNING>\s*", b"", s, flags=re.S)
    s = re.sub(rb"<TOC>\s*", b"", s)
    s = re.sub(rb"\s*</TOC>", b"", s)
    s = re.sub(rb'<DOCUMENT-HEADER AEXT-CLASS="Y">\s*', b"", s)
    s = re.sub(rb"\s*</DOCUMENT-HEADER>", b"", s)
    return s


def same_body(raw: bytes, contents: bytes) -> bool:
    """본문이 원문 그대로인지: 공백 · 줄바꿈 표시(&amp;cr;, 공시 화면으로 되살린 것)와 ENG 를 빼고 견준다. 글자 · 숫자 · 요소는 같아야 한다."""
    def k(b: bytes) -> bytes:
        return re.sub(rb"\s+|&amp;cr;", b"", _ENG.sub(b"", b)).strip()

    return k(strip_editor(contents)) == k(dsd.lenient_xml(raw))


def skeleton(contents: bytes) -> list[str]:
    """뼈대 차례: 삽입 위치(LIBRARYLIST 글) · 안내문 · 목차 · 머리. 편집기 샘플과 견주는 데 쓴다."""
    out = []
    for m in re.finditer(rb"<LIBRARYLIST>([^<]*)</LIBRARYLIST>|<(WARNING|TOC|DOCUMENT-HEADER)[ >]", contents):
        out.append(m.group(1).decode("utf-8") if m.group(1) is not None else m.group(2).decode())
    return out


def file_stem(company: str, year: str, form_name: str) -> str:
    """결과 파일 이름 앞부분: <회사>_<결산연도>_<보고서>. 회사명의 「주식회사」 · 「(주)」 와 파일 이름에 못 쓰는 글자는 뺀다."""
    c = re.sub(r"주식회사|\(주\)|㈜", "", company or "")
    c = re.sub(r'[\/:*?"<>|\s]+', "", c) or "회사"
    return f"{c}_{year or '연도미상'}_{form_name}"
