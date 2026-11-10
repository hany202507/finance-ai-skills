# -*- coding: utf-8 -*-
"""DSD변환 실행기. DART 에 공시된 감사보고서 · 연결감사보고서를 DART 편집기 파일(dsd)로 바꾼다.

    python run.py convert <접수번호 | DART PDF | 공시 원문 xml> [--out 폴더] [--bare] [--view 공시 화면 html]
    python run.py check   <공시 원문 xml> <변환.dsd>        본문이 원문 그대로인지 다시 본다

convert 는 본문(문단 · 표 · 칸 · 숫자 · 서식 표시)을 원문 바이트 그대로 두고, 공시 때 빠진 편집기 요소(삽입 위치 13곳 · 목차 감싸개 ·
안내문 둘 · 문서 머리 감싸개 · meta.xml)만 되살린다. --bare 는 문서 머리 감싸개와 meta.xml 만 더한 판이다(편집기가 뼈대 없는 파일을 받는지 견줄 때).
접수번호 · PDF 는 OpenDART 에서 원문을 받는다(인증키는 환경변수 DART_API_KEY). 이때 같은 보고서의 DART 공시 화면(<이름>.view.html)도
받아, 공시 원문 xml 에서 빠진 문단 · 칸 안 줄바꿈을 화면대로 되살린다. 원문 xml 을 직접 주면 옆에 있는 <이름>.view.html 이나 --view 를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _source(src: str, out: str | None) -> tuple[Path | None, str]:
    from audit.report import dart_fetch as F

    if re.fullmatch(r"\d{14}", src) or (src.lower().endswith(".pdf") and Path(src).exists()):
        rcept = src if re.fullmatch(r"\d{14}", src) else F.from_pdf(Path(src))[0]
        base = Path(out) if out else (Path.cwd() if re.fullmatch(r"\d{14}", src) else Path(src).resolve().parent)
        try:
            return Path(F.fetch_one(rcept, base)["main"]), ""
        except F.FetchError as e:                       # 오류 글에는 인증키가 없다
            return None, f"원문을 받지 못함: {e}"
    if src.lower().endswith(".xml") and Path(src).exists():
        return Path(src), ""
    return None, f"바꿀 것을 알지 못함: {src}. 접수번호(14자리), DART 에서 받은 PDF, 공시 원문 xml 중 하나를 주십시오"


def convert(a) -> int:
    from xml.parsers.expat import ExpatError

    from audit.report import dsd_convert as C

    xp, err = _source(a.src.strip(), a.out)
    if xp is None:
        print(err)
        return 2
    out = Path(a.out) if a.out else xp.resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    raw = xp.read_bytes()
    from audit.report import dsd_breaks

    vp = Path(a.view) if a.view else dsd_breaks.view_for(xp)
    view = vp.read_text(encoding="utf-8", errors="replace") if vp and vp.exists() else None
    try:
        r = C.convert(raw, bare=a.bare, view=view)
    except (ValueError, ExpatError) as e:
        print(f"바꾸지 못함: {e}")
        return 2
    year = r.period_end[:4]
    stem = C.file_stem(r.company, year, C.FORMS[r.form])
    path = C.write(out / f"{stem}_변환{'_뼈대없음' if a.bare else ''}.dsd", r, C.sha(raw))
    same = C.same_body(raw, r.contents)
    print(f"{xp.name} → {path}: {C.FORMS[r.form]}({r.form}) · {r.company} · 결산 {r.period_end or '?'} · "
          f"삽입 위치 {r.counts.get('삽입 위치', 0)}(넣은 LIBRARY {r.counts.get('넣은 LIBRARY', 0)}) · ENG 뺌 {r.counts.get('ENG 뺌', 0)} · "
          f"본문 원문과 {'같음' if same else '다름'} · 줄바꿈 "
          + (f"{r.counts.get('줄바꿈 되살림', 0)}곳 · 빈칸 {r.counts.get('빈칸 되살림', 0)}곳 되살림(공시 화면 {vp.name})" if r.breaks == "화면" else "없음(공시 화면 없음)"))
    for x in r.notes:
        print(f"  {x}")
    print("  편집기에서: 재무제표마다 [재무제표 > 재무제표 검사] 를 돌린 뒤 파일형식 검사를 한다(공시 원문에는 그 검사 기록이 없다)")
    code = 0 if same else 1
    print("  다음 기수 초안(당기 숫자 → 전기 칸, 기수 · 해 +1, 기초 채우기, 원고 엑셀 · 초안 검산)은 DSD초안 스킬의 `python scripts/run.py draft <변환.dsd>` 로 만든다")
    return code


def check(a) -> int:
    import zipfile

    from audit.report import dsd_convert as C

    raw = Path(a.xml).read_bytes()
    with zipfile.ZipFile(a.dsd) as z:
        contents = z.read("contents.xml")
    same = C.same_body(raw, contents)
    print(f"본문 원문과 {'같음' if same else '다름'} · 뼈대 {len(C.skeleton(contents))}개")
    return 0 if same else 1


def build(a) -> int:
    from audit.report import dsd_build

    res = dsd_build.build(Path(a.xlsx), Path(a.out) if a.out else None)
    print(f"{a.xlsx} → {res['path']}: 고친 요소 {res['changed']} · 더한 것 {res['added']} · 뺀 것 {res['removed']} · 원고 검사 {len(res['issues'])}")
    for x in res["issues"][:40]:
        print(f"  [{x['수준']} · {x['분류']}] {x['시트']} {x['칸']} {x['내용']}".rstrip())
    return 1 if any(x["수준"] == "막음" for x in res["issues"]) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="DSD변환")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="공시 원문 → 편집기 dsd")
    c.add_argument("src", help="접수번호(14자리), DART 에서 받은 PDF, 또는 공시 원문 xml(감사보고서 · 연결감사보고서)")
    c.add_argument("--out", default=None, help="결과 폴더. 없으면 원문 xml 이 있는 폴더(접수번호면 지금 폴더)")
    c.add_argument("--bare", action="store_true", help="뼈대 없이: 문서 머리 감싸개와 meta.xml 만 더한다")
    c.add_argument("--view", default=None, help="같은 보고서의 DART 공시 화면 HTML. 없으면 원문 옆 <이름>.view.html 을 쓴다. 원문에서 빠진 줄바꿈을 되살린다")
    c.set_defaults(func=convert)
    k = sub.add_parser("check", help="변환한 dsd 의 본문이 원문 그대로인지 다시 본다")
    k.add_argument("xml")
    k.add_argument("dsd")
    k.set_defaults(func=check)
    b = sub.add_parser("build", help="고친 원고 엑셀로 dsd 를 다시 만든다")
    b.add_argument("xlsx")
    b.add_argument("--out", default=None)
    b.set_defaults(func=build)
    a = ap.parse_args(argv)
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
