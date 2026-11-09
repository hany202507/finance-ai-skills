"""판독 전 본문 손질: 줄바꿈 되살리기 · SPAN 줄 정리 · 원본 종류(2026-11-08, DSD 시험 1단계 D1 · D2).

OpenDART 공시서류원본 xml 은 문단 · 칸 안 줄바꿈(편집기의 &cr;)을 뺀다. 같은 보고서의 공시 화면 HTML(viewer.do)에는 그 자리에
<BR/> 이 있다. 판독 글은 줄바꿈 자리에 경계가 없어 「있습니다.우리의」 처럼 붙고, 문장 검토가 틀린 띄어쓰기 지적을 냈다
(공개 원문 125건에서 화면 줄바꿈의 28% 만 판독에 남았다).

  restore(xml, html)       공시 화면의 줄바꿈 · 빈칸 자리를 xml 글에 되살린다(줄바꿈은 &amp;cr;, 빈칸은 「 」). 숫자 · 글자는 그대로
  glue_span_lines(xml)     SPAN 과 SPAN 사이의 줄 정리용 xml 줄바꿈을 지운다. 편집기는 서식이 다른 글을 SPAN 으로 나눠 한 줄씩 쓰고
                           빈칸은 <SPAN> </SPAN> 으로 따로 적는다. 공시 원문 125건에서 그 자리의 공시 화면은 <BR/> 227 · 붙음 92 · 빈칸 10 이었다
                           (붙음 예: 「2,195,567」 + 「천원을」). 줄바꿈 정보가 있는 본문에만 쓴다. 화면 없는 xml 은 그 줄바꿈이 유일한 경계라 둔다
  hide_white(xml)          흰 글자(USERMARK 0XFFFFFF, 배경색 없음) SPAN 의 글을 비운다. 화면에 보이지 않는 줄 맞춤 글(「반기」 · 「-유동」)이다.
                           문장 검토 판독에만 쓴다(숫자 판독의 줄 이름은 그대로 둔다)
  view_for(path)           원문 옆 공시 화면 파일(<이름>.view.html)
  kind_of(path)            {"원본": dsd | xml | 변환, "줄바꿈": 있음 | 화면 | 없음}
  prepare(path, text=False) -> (contents 바이트, kind)   read_dsd · read_grid · 문장 검토가 쓰는 본문
  fetch_view(rcp, acode, dest)  공시 화면 받기(dart_fetch 가 원문과 함께 받는다)

AUDIT_DSD_NO_VIEW=1 이면 공시 화면을 쓰지 않는다(되살리기 전과 견주는 시험용).
"""
from __future__ import annotations

import html as H
import json
import os
import re
import zipfile
from pathlib import Path

CR_BYTES = b"&amp;cr;"
CONTAINERS = {"P", "TD", "TH", "TE", "TU", "TITLE"}
_BR = re.compile(r"<BR\s*/?>", re.I)
_BLOCK = re.compile(r"</(P|TD|TH|TR|TABLE|DIV|H\d|LI|TITLE)\s*>|<(P|TR|TABLE|DIV|H\d|LI)\b[^>]*>", re.I)
# SPAN 태그끼리 사이(닫고 열기 · 열고 열기 · 닫고 닫기)의 줄 정리 공백. 겹친 SPAN 「<SPAN F-10>⏎<SPAN F-11>주는」 도 같다(2026-11-08 회사 dsd S843)
_SPAN_NL = re.compile(rb"(</SPAN>|<SPAN\b[^>]*>)[ \t]*\r?\n[ \t\r\n]*(?=<SPAN\b|</SPAN>)")
_WHITE = re.compile(rb'(<SPAN\b[^>]*\bUSERMARK="([^"]*)"[^>]*>)([^<]*)(</SPAN>)')


# ---------------------------------------------------------------- 공시 화면 글
def view_stream(html: str) -> tuple[str, dict[int, str]]:
    """공시 화면 → 빈칸 뺀 글자와 {글자 위치: 경계 종류(줄바꿈 · 칸 · 빈칸)}. 경계는 그 위치 글자 앞에 있다."""
    body = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", html)
    body = _BR.sub("\x01", body)
    body = _BLOCK.sub("\x02", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = H.unescape(body).replace("\xa0", " ")
    chars: list[str] = []
    gaps: dict[int, str] = {}
    for ch in body:
        if ch == "\x01":
            gaps[len(chars)] = "줄바꿈" if gaps.get(len(chars)) in (None, "빈칸") else gaps[len(chars)]
        elif ch == "\x02":
            gaps[len(chars)] = "칸" if gaps.get(len(chars)) in (None, "빈칸") else gaps[len(chars)]
        elif ch.isspace():
            gaps.setdefault(len(chars), "빈칸")
        else:
            chars.append(ch)
    return "".join(chars), gaps


# ---------------------------------------------------------------- xml 글을 칸(용기) 단위로
_ENT = {b"amp": "&", b"lt": "<", b"gt": ">", b"quot": '"', b"apos": "'"}


def _tag_end(raw: bytes, i: int) -> int:
    q = None
    n = len(raw)
    while i < n:
        ch = raw[i]
        if q is not None:
            if ch == q:
                q = None
        elif ch in (0x22, 0x27):
            q = ch
        elif ch == 0x3E:
            return i + 1
        i += 1
    return n


def _tag_name(tag: bytes) -> tuple[str, bool, bool]:
    """「<P ...>」 → (이름, 닫는 태그, 빈 요소)."""
    m = re.match(rb"<\s*(/?)\s*([A-Za-z0-9_:\-]+)", tag)
    if not m:
        return "", False, False
    return m.group(2).decode("ascii", "replace").upper(), bool(m.group(1)), tag.rstrip().endswith(b"/>")


def _units(raw: bytes):
    """가장 안쪽 글 칸(P · TD · TH · TE · TU · TITLE)마다 글 조각 [(바이트 시작, 바이트)] 와 조각이 태그 사이 줄 정리 공백뿐인지."""
    stack: list[list] = []          # [이름, 조각들, 안쪽 칸이 있음]
    out = []
    i, n = 0, len(raw)
    while i < n:
        j = raw.find(b"<", i)
        if j < 0:
            j = n
        if j > i and stack:
            stack[-1][1].append((i, raw[i:j]))
        if j >= n:
            break
        if raw.startswith(b"<!--", j):
            k = raw.find(b"-->", j)
            i = n if k < 0 else k + 3
            continue
        if raw.startswith(b"<?", j) or raw.startswith(b"<!", j):
            i = _tag_end(raw, j)
            continue
        e = _tag_end(raw, j)
        name, closing, empty = _tag_name(raw[j:e])
        if name in CONTAINERS and not empty:
            if closing:
                if stack and stack[-1][0] == name:
                    top = stack.pop()
                    if not top[2]:
                        out.append(top[1])
                    if stack:
                        stack[-1][2] = True
            else:
                if stack:
                    stack[-1][2] = True
                stack.append([name, [], False])
        elif stack:
            stack[-1][1].append((j, None))           # 태그 자리(조각 사이 경계를 셀 때 쓴다)
        i = e
    return out


def _chars(pieces):
    """조각 → [(글자, 바이트 위치)] 과 {핵심 글자 차례: 경계}. 경계: 빈칸 · 줄바꿈(&cr;) · 정리(태그 사이 줄 정리 공백)."""
    core: list[tuple[str, int]] = []
    gaps: dict[int, str] = {}
    prev_tag = False
    for k, (start, b) in enumerate(pieces):
        if b is None:
            prev_tag = True
            continue
        nxt_tag = k + 1 < len(pieces) and pieces[k + 1][1] is None
        if prev_tag and nxt_tag and not b.strip(b" \t\r\n") and b"\n" in b:
            gaps.setdefault(len(core), "정리")          # 태그와 태그 사이 줄 정리 공백
            prev_tag = False
            continue
        prev_tag = False
        p, L = 0, len(b)
        while p < L:
            if b.startswith(CR_BYTES, p):
                gaps[len(core)] = "줄바꿈"
                p += len(CR_BYTES)
                continue
            c = b[p]
            if c == 0x26:                              # 개체
                q = b.find(b";", p, p + 12)
                if q > 0:
                    name = b[p + 1:q]
                    if name.startswith(b"#x"):
                        ch = chr(int(name[2:], 16))
                    elif name.startswith(b"#"):
                        ch = chr(int(name[1:]))
                    else:
                        ch = _ENT.get(name, "&")
                    if ch.isspace() or ch == "\xa0":
                        gaps.setdefault(len(core), "빈칸")
                    else:
                        core.append((ch, start + p))
                    p = q + 1
                    continue
            ln = 1 if c < 0x80 else 2 if c < 0xE0 else 3 if c < 0xF0 else 4
            ch = b[p:p + ln].decode("utf-8", "replace")
            if ch.isspace() or ch == "\xa0":
                if gaps.get(len(core)) in (None, "정리"):
                    gaps[len(core)] = "빈칸"
            else:
                core.append((ch, start + p))
            p += ln
    return core, gaps


def restore(raw: bytes, html: str) -> tuple[bytes, dict]:
    """xml 바이트(lenient_xml 뒤)에 공시 화면의 줄바꿈(&amp;cr;) · 빈칸을 되살린다. 칸 글을 차례대로 화면 글에서 찾고, 찾은 칸 안에서
    화면에 줄바꿈 · 빈칸이 있는데 xml 에는 경계가 없거나 줄 정리 공백뿐인 자리에 넣는다. 칸 글이 화면에 없으면(4글자 미만, 다른 글) 손대지 않는다."""
    vc, vg = view_stream(html)
    edits: list[tuple[int, bytes]] = []
    st = {"칸": 0, "찾은 칸": 0, "넣은 줄바꿈": 0, "넣은 빈칸": 0}
    cur = 0
    for pieces in _units(raw):
        core, gaps = _chars(pieces)
        if not core:
            continue
        s = "".join(c for c, _ in core)
        # 칸은 문서 차례대로 찾는다. 짧은 칸(「자본잉여금」 · 숫자)은 바로 앞에서만 찾아야 앞쪽 다른 자리(재무상태표의 같은 과목)에 맞대지 않는다.
        # 짧은 칸도 찾으면 위치를 앞으로 옮겨 다음 칸의 기준점이 된다(2026-11-08: 표 머리 칸 안 줄바꿈이 남은 까닭)
        p = vc.find(s, cur, cur + (4000 if len(s) < 12 else 400000) + len(s))
        if p < 0:
            if len(s) < 12:
                continue
            p = vc.find(s)
            if p < 0:
                continue
        cur = p + len(s)
        if len(core) < 2:
            continue
        st["칸"] += 1
        st["찾은 칸"] += 1
        for k in range(1, len(core)):
            v = vg.get(p + k)
            if v not in ("줄바꿈", "빈칸", "칸"):
                continue
            g = gaps.get(k)
            # xml 에 이미 줄바꿈이 있으면 둔다. 빈칸만 있는데 화면이 줄을 바꿨으면 줄바꿈을 넣는다(원문 「부동산  투자신탁」 ↔ 화면
            # 「부동산<BR/> 투자신탁」, 2026-11-09 한 상장사 별도 S808: 칸 안 줄바꿈을 빈칸으로 읽어 띄어쓰기 지적이 났다)
            if g == "줄바꿈" or (g == "빈칸" and v != "줄바꿈"):
                continue
            if v in ("줄바꿈", "칸"):
                edits.append((core[k][1], CR_BYTES))
                st["넣은 줄바꿈"] += 1
            else:
                edits.append((core[k][1], b" "))
                st["넣은 빈칸"] += 1
    if not edits:
        return raw, st
    out, pos = [], 0
    for at, ins in sorted(edits):
        out.append(raw[pos:at])
        out.append(ins)
        pos = at
    out.append(raw[pos:])
    return b"".join(out), st


def glue_span_lines(raw: bytes) -> bytes:
    return _SPAN_NL.sub(rb"\1", raw)


def hide_white(raw: bytes) -> bytes:
    def sub(m):
        toks = m.group(2).decode("ascii", "replace").upper().split()
        if "0XFFFFFF" in toks and not any(t.startswith("BC") for t in toks):
            return m.group(1) + m.group(4)
        return m.group(0)

    return _WHITE.sub(sub, raw)


# ---------------------------------------------------------------- 원본 종류
def view_for(path: Path) -> Path | None:
    if os.environ.get("AUDIT_DSD_NO_VIEW"):
        return None
    path = Path(path)
    for cand in (path.with_name(path.stem + ".view.html"), path.with_suffix(".view.html")):
        if cand.exists():
            return cand
    return None


def _stamp(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            c = z.comment.decode("utf-8", "replace")
        return json.loads(c) if c.strip().startswith("{") else {}
    except (zipfile.BadZipFile, OSError, ValueError):
        return {}


def kind_of(path: Path) -> dict:
    path = Path(path)
    if path.suffix.lower() == ".xml":
        return {"원본": "xml", "줄바꿈": "화면" if view_for(path) else "없음"}
    st = _stamp(path)
    if "원문변환" in st:
        return {"원본": "변환", "줄바꿈": st.get("줄바꿈") or "없음"}
    # 편집기로 다시 저장하면 zip 주석(원문변환 표시)이 사라진다. 회사 dsd 는 본문에 &cr; 가 수백 개(11-08: 250 ~ 344)이고,
    # 공시 xml 을 바꾼 dsd 는 변환기가 넣은 안내문 · 표지의 것뿐이다. 그 둘을 뺀 본문에 &cr; 가 없으면 줄바꿈이 빠진 변환본으로 본다
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
            raw = z.read(name) if name else b""
    except (zipfile.BadZipFile, OSError):
        raw = b""
    body = re.sub(rb"(?s)<(WARNING|COVER|TOC)\b.*?</\1>", b"", raw)
    if raw and body.count(CR_BYTES) == 0 and len(re.findall(rb"<P\b", body)) >= 30:
        return {"원본": "변환(추정)", "줄바꿈": "없음"}
    return {"원본": "dsd", "줄바꿈": "있음"}


def prepare(path: Path, text: bool = False) -> tuple[bytes, dict]:
    """read_dsd · read_grid 가 쓰는 contents 바이트. xml 은 lenient_xml 뒤 공시 화면이 있으면 줄바꿈을 되살린다. 줄바꿈 정보가 있는 본문
    (회사 dsd, 화면으로 되살린 xml, 화면으로 되살려 바꾼 dsd)은 SPAN 줄 정리 공백을 지운다. text 면 흰 글자를 비운다."""
    from . import dsd

    path = Path(path)
    kind = kind_of(path)
    if kind["원본"] == "xml":
        raw = dsd.lenient_xml(path.read_bytes())
        v = view_for(path)
        if v is not None:
            raw, st = restore(raw, v.read_text(encoding="utf-8", errors="replace"))
            kind["되살림"] = st
    else:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
            if name is None:
                raise ValueError(f"dsd 안에 contents.xml 이 없습니다: {path}")
            raw = z.read(name)
    if kind["줄바꿈"] != "없음":
        raw = glue_span_lines(raw)
    if text:
        raw = hide_white(raw)
    return raw, kind


def signature(path: Path) -> bytes:
    """판독 캐시 열쇠에 넣을 바이트: 파일과 옆 공시 화면."""
    path = Path(path)
    b = path.read_bytes()
    v = view_for(path) if path.suffix.lower() == ".xml" else None
    return b + (v.read_bytes() if v is not None else b"") + (b"NOVIEW" if os.environ.get("AUDIT_DSD_NO_VIEW") else b"")


# ---------------------------------------------------------------- 공시 화면 받기
BASE = "https://dart.fss.or.kr"


def _get(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")


def dcm_no(page: str, acode: str | None) -> str | None:
    """공시 페이지에서 문서번호. 사업보고서면 첨부 목록에서 감사보고서 · 연결감사보고서를, 단독 감사보고서면 첫 문서를."""
    want = {"00760": "감사보고서", "00761": "연결감사보고서"}.get(acode or "")
    opts = re.findall(r'<option value="rcpNo=\d+&amp;dcmNo=(\d+)"[^>]*>(.*?)</option>', page, flags=re.S)
    if want:
        for no, body in opts:
            name = re.sub(r"&nbsp;|[\d.]|\s|\[[^\]]*\]", "", body)
            if name == want:
                return no
        title = re.search(r"<title>(.*?)</title>", page, flags=re.S)
        doc = re.sub(r"\s|\[[^\]]*\]", "", title.group(1)).split("/")[1] if title and "/" in title.group(1) else ""
        if doc != want:
            return None
    m = re.search(r'viewDoc\("\d+",\s*"(\d+)"', page)
    return m.group(1) if m else None


def fetch_view(rcp: str, acode: str | None, dest: Path) -> Path:
    """공시 화면 HTML 을 dest 로 받는다. 한 번 요청에 문서 전체가 온다(eleId=1 · offset=0 · length=0). 못 받으면 RuntimeError."""
    import time

    page = _get(f"{BASE}/dsaf001/main.do?rcpNo={rcp}")
    time.sleep(1)
    dcm = dcm_no(page, acode)
    if not dcm:
        raise RuntimeError("공시 화면의 문서번호를 찾지 못함")
    html = _get(f"{BASE}/report/viewer.do?rcpNo={rcp}&dcmNo={dcm}&eleId=1&offset=0&length=0&dtd=dart4.xsd")
    if len(html) < 2000:
        raise RuntimeError(f"공시 화면이 비었음({len(html)}자)")
    Path(dest).write_text(html, encoding="utf-8")
    return Path(dest)
