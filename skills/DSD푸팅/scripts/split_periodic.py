"""정기보고서(사업 · 반기 · 분기보고서) 본문에서 재무제표와 주석을 꺼내 DSD 푸팅이 읽는 원문으로 만든다(2026-10-13).

    python scripts/split_periodic.py <정기보고서.xml> [--out <폴더>]

정기보고서 본문에는 「2. 연결재무제표」 「3. 연결재무제표 주석」 「4. 재무제표」 「5. 재무제표 주석」 절이 한 파일에 있다.
감사보고서 원문과 달리 연결과 별도가 함께 있고 절 제목에 번호가 붙는다. 연결과 별도를 따로 떼어
「재무제표」 절과 「주석」 절만 있는 원문 두 개(<이름>_연결.xml, <이름>_별도.xml)를 쓴다. 숫자와 글자는 바꾸지 않는다.
반기 · 분기보고서의 검토보고서는 첨부로 따로 오지 않아 이 방법으로 읽는다.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit.report import dsd  # noqa: E402
from audit.report.base import norm  # noqa: E402

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
    """{연결|별도: xml bytes}. 그 재무제표가 없으면 그 키가 없다."""
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    src = Path(a.report)
    out = Path(a.out) if a.out else src.parent
    out.mkdir(parents=True, exist_ok=True)
    got = split(src)
    if not got:
        print(f"{src.name}: 재무제표 절을 찾지 못했습니다")
        return 1
    from audit.report import dsd_grid

    for kind, raw in got.items():
        p = out / f"{src.stem}_{kind}.xml"
        p.write_bytes(raw)
        doc = dsd_grid.read_grid(p)
        print(f"{p.name}: 부분 {len(doc.parts)}(주석 {sum(1 for x in doc.parts if x.key.startswith('주석'))}) · 표 {len(doc.tables())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
