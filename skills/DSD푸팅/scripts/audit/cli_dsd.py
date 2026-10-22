"""DSD 푸팅 명령줄(2026-10-12). 감사 폴더 없이 dsd 한 파일로 돈다.

  python -m audit dsd read <dsd> [--out 폴더]
      격자로 읽어 dsd_표.json 을 쓴다
  python -m audit dsd foot <dsd> [--prev 기존 판] [--prior 작년 보고서] [--wtb 정산표] [--pair 다른 보고서] [--out 폴더] [--defs 파일]
      검증 엑셀을 만든다. 오버뷰에 합계 · 레퍼 · 전기 · 버전 네 가지가 신호등으로 보인다.
      --prev 를 주면 기존 판 대비 바뀐 곳을, --prior 를 주면 전기 숫자가 작년 보고서와 같은지를 본다.
      FALSE 나 풀지 못한 연결이 있으면 1 로 끝난다. 바뀐 곳, 확인, 전기 대사에서 못 찾은 줄은 종료 코드에 넣지 않는다.
      --wtb 는 8100B · WTB 양식 · 감사 법인 양식(BS · IS · WBS · WIS · AJE)을 읽는다. 읽지 못하는 양식이면 「이 WTB 양식을 읽지 못함: …」 한 줄로 2 로 끝난다.
  python -m audit dsd links <dsd> [--out 폴더] [--defs 파일]
      AI 가 읽을 자료를 낸다: dsd_읽기자료.md(재무제표와 주석 전부), dsd_연결요청.json(아직 주석과 이어지지 않은 과목, 금액 대조가 찾은 참고,
      엔진의 연결 후보 proposals). 연결 후보(2026-10-22)는 위치 · 이름 · XBRL 코드로 내고 금액은 보지 않는다. 읽기 자료의 표 아래 「후보 P0001」 줄로도 보인다
  python -m audit dsd links <dsd> --apply <연결.json> [--add] [--out 폴더] [--defs 파일]
      AI 가 적은 연결을 검사해 dsd_연결정의.json 에 넣는다. 이름이 칸으로 풀리지 않는 연결이 하나라도 있으면 아무것도 쓰지 않고 1 로 끝난다.
      연결.json 은 AI 연결의 전체 목록이다. 앞서 넣은 AI 연결은 이 목록으로 바뀐다(--add 면 두고 더한다). 넣은 뒤 dsd_연결요청.json 을 다시 쓴다
      연결.json 에 proposals(후보 번호의 O · X · 고침)가 있으면 후보 전부에 판정이 있어야 넣는다(--add 면 앞서 판정한 후보는 판정한 것으로 본다)

  python -m audit dsd fetch <접수번호 | PDF> [--out 폴더] [--no-prior]
      OpenDART 공시서류원본(xml)을 받는다(2026-10-22). PDF 는 DART 에서 받은 「[회사]보고서(접수일).pdf」 꼴이면 그날 그 회사의 공시를 찾는다.
      사업 · 반기 · 분기보고서면 <접수번호>_연결.xml · _별도.xml 로 나누고, 작년 비교 보고서(직전 사업보고서, 작년 같은 기간 보고서)도 받아 나눈다.
      끝에 foot 명령(--prior · --pair 를 채운 것)을 적어 준다. 인증키는 환경변수 DART_API_KEY 에서만 읽는다. 받지 못하면 한 줄로 2 로 끝난다

  python -m audit dsd text <dsd> [--facts 기준사실.json] [--case 감사 폴더] [--prior 작년 보고서] [--apply 문장.json] [--out 폴더]
      문장 검토(2026-10-17): 표가 아닌 글과 표 안 글자를 읽어 문장읽기.md(AI 가 읽을 글 전부와 엔진이 찾은 것)와 문장검토.json 을 쓴다.
      --apply 로 AI 가 적은 문장.json 을 넣으면 발췌가 원문에 있는지 본다. foot 은 폴더의 기준사실.json · 문장.json 을 함께 읽어 「문장 검토」 시트를 만든다

dsd 자리에는 DART 편집기 파일(.dsd)이나 OpenDART 공시서류원본파일(.xml)을 준다.
"""
from __future__ import annotations

import re
from pathlib import Path


def register(sub) -> None:
    p = sub.add_parser("dsd", help="회사 제시 dsd 푸팅: 격자 판독과 수식 검증 엑셀")
    ps = p.add_subparsers(dest="dcmd", required=True)
    r = ps.add_parser("read", help="dsd 를 재무제표와 주석 번호별 격자로 읽는다")
    r.add_argument("dsd")
    r.add_argument("--out", default=None)
    r.set_defaults(func=_read)
    f = ps.add_parser("foot", help="수식 검증 엑셀을 만든다")
    f.add_argument("dsd")
    f.add_argument("--prev", default=None, help="기존 판(dsd · xml). 바뀐 곳을 본다")
    f.add_argument("--prior", default=None, nargs="+",
                   help="작년 보고서(dsd · xml). 전기 숫자가 같은지 본다. 반기 · 분기보고서는 둘을 준다(직전 사업보고서, 작년 같은 기간의 보고서)")
    f.add_argument("--wtb", default=None, help="정산표 엑셀(8100B · WTB 양식 · 감사 법인 양식 BS · IS · WBS · WIS · AJE). 본표 과목을 감사한 금액과 견준다. "
                                                 "엑셀에서 계산된 값이 저장된 파일이어야 한다. 읽지 못하는 양식이면 한 줄 오류로 2 로 끝난다")
    f.add_argument("--pair", default=None, help="함께 낸 다른 보고서(연결이면 별도, 별도면 연결). 자본금처럼 두 보고서에 같은 금액과 「짝:」 으로 적은 연결을 견준다")
    f.add_argument("--out", default=None)
    f.add_argument("--defs", default=None)
    f.add_argument("--amount-links", action="store_true", help="금액이 같은 칸을 엔진이 찾아 함께 건다(기본은 AI 가 정의한 연결만)")
    f.add_argument("--facts", default=None, help="문장 검토의 기준 사실 json(없으면 --out 폴더의 기준사실.json)")
    f.add_argument("--case", default=None, help="감사 폴더. 회사명 · 결산일과 공시 확인 대상(의사록 · 등기부 판독 사실)을 읽는다")
    f.add_argument("--text", default=None, help="AI 가 적은 문장 검토 json(없으면 --out 폴더의 문장.json)")
    f.set_defaults(func=_foot)
    t = ps.add_parser("text", help="문장 검토: 오타 · 표현 · 사실 불일치(주소 · 대표이사 · 감사기간 · 보고서일) · 공시 누락")
    t.add_argument("dsd")
    t.add_argument("--facts", default=None)
    t.add_argument("--case", default=None)
    t.add_argument("--prior", default=None, help="작년 보고서. 같은 문장에 작년 날짜가 남은 곳을 본다")
    t.add_argument("--apply", default=None, help="AI 가 적은 문장.json. 폴더에 문장.json 으로 옮겨 둔다")
    t.add_argument("--out", default=None)
    t.set_defaults(func=_text)
    k = ps.add_parser("links", help="AI 가 정할 연결의 요청 자료를 내거나(--apply 없이) AI 가 적은 연결을 넣는다(--apply)")
    k.add_argument("dsd")
    k.add_argument("--apply", default=None, help="AI 가 적은 연결 json. 앞서 넣은 AI 연결은 이 파일의 것으로 바뀐다")
    k.add_argument("--add", action="store_true", help="--apply 와 함께: 앞서 넣은 AI 연결을 두고 더한다")
    k.add_argument("--carry", default=None, help="--apply 와 함께: --apply 의 연결을 적은 판(dsd · xml). 표 번호와 줄 이름을 이 판에 맞게 옮겨서 넣는다")
    k.add_argument("--out", default=None)
    k.add_argument("--defs", default=None)
    k.set_defaults(func=_links)
    g = ps.add_parser("fetch", help="OpenDART 원문 xml 을 받아 정기보고서면 연결 · 별도로 나눈다(작년 비교 보고서도)")
    g.add_argument("src", help="접수번호(14자리) 또는 DART 에서 받은 PDF")
    g.add_argument("--out", default=None, help="받을 폴더. 없으면 PDF 가 있는 폴더(접수번호면 지금 폴더). 그 아래 원문_<접수번호>/ 에 둔다")
    g.add_argument("--no-prior", action="store_true", help="작년 비교 보고서를 받지 않는다")
    g.set_defaults(func=_fetch)


def _out_dir(a) -> Path:
    d = Path(a.out) if a.out else Path(a.dsd).resolve().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(a) -> int:
    import json

    from .report import dsd_grid

    doc = dsd_grid.read_grid(Path(a.dsd))
    out = _out_dir(a) / "dsd_표.json"
    out.write_text(json.dumps(dsd_grid.to_json(doc), ensure_ascii=False, indent=1), encoding="utf-8")
    notes = sum(1 for p in doc.parts if p.key.startswith("주석"))
    print(f"{doc.source}: 재무제표 {len(doc.parts) - notes}개 · 주석 {notes}개 · 표 {len(doc.tables())}개 → {out}")
    return 0


def foot(src: Path, out: Path, prev: Path | None = None, prior: Path | None = None, defs_path: Path | None = None, amount_links: bool = False,
         wtb: Path | None = None, pair: Path | None = None, facts: Path | None = None, case: Path | None = None, text: Path | None = None) -> dict:
    """검증 엑셀을 만들고 요약을 돌려준다. {book, doc, checks, unresolved, changes, consistency}"""
    import json

    from .report import dsd_book, dsd_compare, dsd_grid, dsd_links

    defs_path = defs_path or out / "dsd_연결정의.json"
    book = out / f"DSD푸팅_{src.stem}.xlsx"
    defs = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.exists() else {}
    marks = dict(defs.get("marks", {}))
    for old in sorted(out.glob("DSD푸팅_*.xlsx"), key=lambda p: p.stat().st_mtime):
        marks.update(dsd_book.read_marks(old))
    defs["marks"] = marks
    cache = dsd_grid.cache_dir()                      # 넣기마다 foot 을 다시 돌려도 같은 파일은 다시 판독하지 않는다(2026-10-22 P5)
    doc = dsd_grid.read_cached(src, cache)
    pdoc = dsd_grid.read_cached(prev, cache) if prev else None
    priors = [prior] if isinstance(prior, (str, Path)) else list(prior or [])
    ydocs = [dsd_grid.read_cached(Path(p), cache) for p in priors]
    odoc = dsd_grid.read_cached(Path(pair), cache) if pair else None
    checks, new_defs, unresolved = dsd_links.build(doc, defs, amount_links=amount_links, other=odoc)
    ydoc = None
    prior_matches: list = []                          # (작년 문서, 앞머리, 짝) 차이 설명 후보의 「작년 이름」 에 쓴다(11단계)
    if ydocs:
        ydoc, groups = dsd_links.join_priors(ydocs)       # 둘째 보고서의 표는 이름 앞에 ② 를 붙여 한 문서로 잇는다
        for y, tag in groups:
            ym = dsd_compare.match(doc, y)
            prior_matches.append((y, tag, ym))
            more, missing = dsd_links.prior_checks(doc, y, ym, tag, defs.get("prior_pairs", []))
            dsd_links.apply_marks(more, marks)
            dsd_links.apply_prior_verdicts(more, defs.get("prior", []))
            notes = {x["id"]: x for x in defs.get("findings", [])}       # 전기 대사 차이를 「확인」 으로 판정한 근거도 「볼 것」 시트에 보인다
            for c in more:
                if not c.finding and c.id in notes:
                    dsd_links.apply_finding(c, notes[c.id])
            checks, unresolved = checks + more, unresolved + missing
    wdoc = None
    if wtb:                                          # 정산표와 본표 과목의 대사
        from .report import dsd_wtb

        wdoc = dsd_wtb.read_wtb(Path(wtb))             # 읽지 못하면 WtbFormatError(_foot 이 한 줄로 끝낸다)
        more, missing = dsd_wtb.checks(doc, wdoc, {(c.table, c.r) for c in checks if c.kind == "세로합"})
        dsd_links.apply_marks(more, marks)
        notes = {x["id"]: x for x in defs.get("findings", [])}
        for c in more:
            if c.id in notes:
                dsd_links.apply_finding(c, notes[c.id])
        checks, unresolved = checks + more, unresolved + missing
    dsd_links.evaluate(doc, checks, ydoc, wdoc, odoc)
    from .report import dsd_diff, dsd_verify          # 11단계: 고칠 칸 근거 · 독립 검증 · 차이 설명 후보 · 판정자료

    dsd_verify.apply_fixes(checks, defs.get("findings", []), doc, ydoc, wdoc, odoc)
    review_problems = dsd_verify.apply_review(checks, dsd_verify.load_review(out / dsd_verify.REVIEW), doc, ydoc, wdoc, odoc)
    tabs = dsd_diff.tables(doc, ydoc, wdoc, odoc)
    dsd_diff.explain(doc, checks, tabs, prior_matches)
    (out / dsd_verify.PACK).write_text(dsd_verify.pack(doc, checks, tabs, dsd_book.causes(doc, checks), dsd_book.last_year(doc, tabs, checks)), encoding="utf-8")
    m = dsd_compare.match(doc, pdoc, fuzzy=True) if pdoc is not None else None
    old_checks = None
    if pdoc is not None:                             # 기존 판에도 같은 연결을 걸어 검증 결과가 달라진 것을 본다(고쳐 달라고 한 곳이 고쳐졌는지)
        old_checks, _, _ = dsd_links.build(pdoc, dict(defs, marks={}), amount_links=amount_links)
        dsd_links.evaluate(pdoc, old_checks)
    from .report import dsd_ai

    gaps = dsd_ai.request(doc, [c for c in checks if c.group != "전기"], new_defs, with_evidence=False)
    same = dsd_ai.consistency(doc)
    if wdoc is not None and (wdoc.stats or {}).get("과목에 잇지 못한 수정 계정"):
        lost_acc = wdoc.stats["과목에 잇지 못한 수정 계정"]
        same.append({"what": "정산표 과목에 잇지 못한 수정 계정", "n": len(lost_acc),
                     "why": f"{', '.join(lost_acc[:8])}. 감사 법인 WTB 의 계정별 시트에서 수정이 있는 계정을 공시 과목에 잇지 못해 그 과목의 회사제시 금액을 구하지 못했다. "
                            "수정 후 금액 대사는 그대로 된다."})
    if wdoc is not None and dsd_wtb.no_adjustments(wdoc):
        same.append({"what": "정산표 수정분개 0건", "n": 0, "why": "정산표의 당기(회사제시)와 당기(최종)이 모든 과목에서 같다. 수정분개를 넣기 전의 정산표라면 "
                     "정산표 대사는 회사 장부와 맞춘 것일 뿐이다. 수정분개를 다 넣은 정산표로 다시 돌린다."})
    from .report import dsd_text                     # 문장 검토(2026-10-17). 기준사실.json · 문장.json 은 폴더에 있으면 읽는다

    tres = dsd_text.review(src, dsd_text.load_facts(facts or out / "기준사실.json", case), priors[0] if priors else None,
                           text or out / "문장.json", case)
    dsd_text.mark_stale(tres, out / "문장검토.json")    # dsd text 가 AI 에게 준 공시 확인 대상과 지금 대상이 같은지(2026-10-18 B-7)
    dsd_book.write(book, doc, checks, unresolved, pdoc, ydoc, m,
                   {"unlinked": gaps["unlinked"], "unchecked_totals": gaps["unchecked_totals"], "skipped": new_defs.get("skipped", []),
                    "workpapers": new_defs.get("workpapers", []), "consistency": same, "text": tres}, wdoc, odoc, old_checks)
    defs_path.write_text(json.dumps(new_defs, ensure_ascii=False, indent=1), encoding="utf-8")
    changed = dsd_compare.changes(doc, pdoc, m) if pdoc is not None else None
    return {"book": book, "doc": doc, "checks": checks, "unresolved": unresolved, "changes": changed, "match": m, "consistency": same, "text": tres,
            "review_problems": review_problems,
            "wtb": wdoc}


def _foot(a) -> int:
    from .report import dsd_links

    from .report import dsd_wtb

    src = Path(a.dsd)
    try:
        r = foot(src, _out_dir(a), Path(a.prev) if a.prev else None, [Path(p) for p in a.prior] if a.prior else None, Path(a.defs) if a.defs else None, a.amount_links,
                 Path(a.wtb) if a.wtb else None, Path(a.pair) if a.pair else None, Path(a.facts) if a.facts else None,
                 Path(a.case) if a.case else None, Path(a.text) if a.text else None)
    except dsd_wtb.WtbFormatError as e:               # 정산표 양식을 못 읽으면 역추적 없이 한 줄(2026-10-18 실제 회사 자료 B-1)
        print(f"이 WTB 양식을 읽지 못함: {e}")
        return 2
    doc, checks, unresolved = r["doc"], r["checks"], r["unresolved"]
    live = [c for c in checks if not c.excluded and not c.dropped]
    n_drop = sum(1 for c in checks if c.dropped)
    bad = [c for c in live if dsd_links.failed(c)]
    minor = [c for c in live if c.minor]
    ask = [c for c in live if dsd_links.asks(c)]
    by = {g: sum(1 for c in live if c.group == g) for g in ("합계", "레퍼", "전기")}
    n_calc = sum(1 for c in live if c.expr)
    lost = [u for u in unresolved if u.get("kind") == "전기"]       # 작년 보고서에서 줄을 찾지 못한 전기 금액. 풀지 못한 연결과 따로 센다
    nowtb = [u for u in unresolved if u.get("kind") == "조서"]      # 정산표에서 과목을 찾지 못한 본표 줄
    unresolved = [u for u in unresolved if u.get("kind") not in ("전기", "조서")]
    line = (f"{src.name}: 검증 {len(live)}(합계 {by['합계']} · 레퍼 {by['레퍼']}" + (f"(계산 {n_calc})" if n_calc else "") + f" · 전기 {by['전기']}) · FALSE {len(bad)} · 확인 {len(ask)} · 단수 차이 {len(minor)} · "
            f"판정으로 뺌 {n_drop} · 제외(X) {len(checks) - len(live) - n_drop} · 풀지 못한 연결 {len(unresolved)}" + (f" · 전기 대사에서 못 찾은 줄 {len(lost)}" if lost else "")
            + (f" · 정산표에서 못 찾은 과목 {len(nowtb)}" if nowtb else ""))
    if r["changes"] is not None:
        line += f" · 바뀐 곳 {sum(r['changes'].values())}"
    kinds = [dsd_links.kind_of(c) for c in live]      # 11단계: 숫자 오류(FALSE) · 표시 오류 · 설명 부족 · 독립 검증
    if kinds.count("표시 오류") or kinds.count("설명 부족"):
        line += f" · 표시 오류 {kinds.count('표시 오류')} · 설명 부족 {kinds.count('설명 부족')}"
    judged = [c for c in live if c.ok is False and not c.minor and not dsd_links.no_review(c)]      # 늘 나는 차이 · 근거 확인 숫자 오류는 독립 검증 대상이 아니다(2026-10-22)
    if any(c.verified for c in judged):
        line += f" · 독립 검증 {sum(1 for c in judged if c.verified)}/{len(judged)}(바꿈 {sum(1 for c in judged if c.verified == '바꿈')})"
    n_sampled = sum(1 for c in live if dsd_links.sampled(c))
    if n_sampled:
        line += f" · 늘 나는 차이 {n_sampled}(독립 검증 대신 회계사 표본)"
    n_engine = sum(1 for c in live if dsd_links.engine_checked(c))
    if n_engine:
        line += f" · 엔진이 근거를 확인한 숫자 오류 {n_engine}(독립 검증 안 함)"
    print(f"{line} → {r['book']}")
    for p in r.get("review_problems") or []:
        print(f"  {p}")
    if r.get("wtb") is not None:
        print("  " + dsd_wtb.describe(r["wtb"]))
    for c in bad[:40]:
        t = doc.table(c.table)
        print(f"  FALSE [{c.kind}] {doc.part_of(c.table).key} {dsd_links._labels(t)[c.r]} · {t.header[c.c]}: {c.left:,} ↔ {c.right:,} ({c.label})")
        for h in c.hints[:2]:
            print(f"    후보 [{h['kind']}] {h['text']}")
    for c in ask[:40]:
        t = doc.table(c.table)
        print(f"  확인 [{c.kind}] {doc.part_of(c.table).key} {dsd_links._labels(t)[c.r]} · {t.header[c.c]}: {c.left:,} ↔ {c.right:,} (차이 {c.left - c.right:,}. 조건: {c.when})")
    for u in unresolved[:40]:
        print(f"  풀지 못함 {u['table']}: {u['why']}")
    for u in lost[:10]:
        print(f"  전기 대사 {u['table']}: {u['why']}")
    for u in nowtb[:40]:
        print(f"  조서 대사 {u['table']}: {u['why']}")
    for x in r.get("consistency") or []:
        print(f"  원문 대조 {x['what']}: {x['why']}")
    from .report import dsd_text

    print("  " + dsd_text.summary(r["text"]))
    if r["changes"]:
        for k, n in r["changes"].items():
            if n:
                print(f"  바뀜 {k}: {n}곳")
        for x in r["match"].gone_parts:
            print(f"  없어진 시트: {x}")
    return 1 if bad or unresolved else 0


def _text(a) -> int:
    import json
    import shutil

    from .report import dsd_text

    out = _out_dir(a)
    if a.apply:
        dst = out / "문장.json"
        if Path(a.apply).resolve() != dst.resolve():
            shutil.copyfile(a.apply, dst)
    case = Path(a.case) if a.case else None
    facts = dsd_text.load_facts(Path(a.facts) if a.facts else out / "기준사실.json", case)
    res = dsd_text.review(Path(a.dsd), facts, Path(a.prior) if a.prior else None, out / "문장.json", case)
    (out / "문장읽기.md").write_text(dsd_text.reading(res), encoding="utf-8")
    (out / "문장검토.json").write_text(json.dumps(dsd_text.to_json(res), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{Path(a.dsd).name}: 글 조각 {len(res['segments'])}개 · {dsd_text.summary(res)} → {out / '문장읽기.md'}")
    for x in res["engine"][:40]:
        print(f"  [{x['kind']} · {x['rule']}] {x['seg']} {x['where']}: {x['quote'][:60]} → {x['fix']}")
    for x in res["invalid"][:20]:
        print(f"  받지 않음 {x.get('seg') or x.get('item')}: {x['why']}")
    return 1 if res["invalid"] else 0


def _proposal_line(props: list[dict]) -> str:
    from collections import Counter

    by = Counter(x["how"] for x in props)
    return f"엔진 연결 후보 {len(props)}건" + (f"({' · '.join(f'{k} {v}' for k, v in by.most_common())})" if by else "") \
        + " → dsd_연결요청.json 의 proposals, 읽기 자료의 표 아래 「후보」 줄"


def _links(a) -> int:
    import json

    from .report import dsd_ai, dsd_grid, dsd_links

    src, out = Path(a.dsd), _out_dir(a)
    defs_path = Path(a.defs) if a.defs else out / "dsd_연결정의.json"
    defs = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.exists() else {}
    doc = dsd_grid.read_grid(src)
    checks, base, _ = dsd_links.build(doc, defs)
    if not a.apply:
        dsd_links.evaluate(doc, checks)
        req = dsd_ai.request(doc, checks, base, with_proposals=True)
        p = out / "dsd_연결요청.json"
        p.write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "dsd_읽기자료.md").write_text(dsd_ai.reading(doc, base, checks, req["proposals"]), encoding="utf-8")
        print(f"{src.name}: {dsd_ai.summary(req)} → {p}")
        print("  " + _proposal_line(req["proposals"]))
        for x in req["unlinked"][:40]:
            print(f"  {x['table']} {x['row']} (가리킨 주석 {', '.join(x['notes'])})")
        return 0
    patch = json.loads(Path(a.apply).read_text(encoding="utf-8"))
    n_prop = {}
    if patch.get("proposals", {}) is not None:        # 후보 판정의 건수(넣은 뒤 화면에 보인다). 판정을 적지 않은 후보는 기본으로 들어간다(2026-10-22)
        got = patch.get("proposals") or {}
        xs = got.get("X") or {}
        n_prop = {"O": sum(len(dsd_ai._ids(x)) for x in got.get("O") or []), "X": sum(len(dsd_ai._ids(x)) for x in (xs if isinstance(xs, dict) else [e.get("id") for e in xs])),
                  "고침": len(got.get("고침") or got.get("edit") or [])}
    if a.carry:                                       # 다른 판에서 적은 연결을 이 판의 표 번호 · 이름으로 옮긴다
        cdoc = dsd_grid.read_grid(Path(a.carry))
        if "proposals" in patch:                      # 후보 번호는 그 판의 것이라 먼저 연결로 풀어 옮긴다
            patch, bad, _ = dsd_ai.expand_proposals(cdoc, patch, strict=False)
            for x in bad:
                print(f"  후보를 풀지 못함 {x}")
        patch, lost = dsd_ai.carry(cdoc, doc, patch)
        moved = out / "연결_옮김.json"
        moved.write_text(json.dumps(patch, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{Path(a.carry).name} 의 연결을 옮겼습니다: 연결 {len(patch['links'])} · 합계 구조 {len(patch['sums'])} · 합계 아님 {len(patch['no_sums'])} · 옮기지 못함 {len(lost)} → {moved}")
        for x in lost:
            print(f"  옮기지 못함 {x}")
    new, problems = dsd_ai.apply(doc, base, patch, add=a.add)
    if problems:
        print(f"연결을 넣지 않았습니다. 고칠 곳 {len(problems)}건")
        for x in problems:
            print(f"  {x}")
        return 1
    defs_path.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    doc = dsd_grid.read_grid(src)                     # 단위를 바로잡은 표가 바뀌었을 수 있어 다시 읽는다
    checks, _, _ = dsd_links.build(doc, new)
    dsd_links.evaluate(doc, checks)
    ai = [c for c in checks if c.source == "AI" and c.group == "레퍼"]
    n = sum(1 for x in new["links"] if x.get("source") == "AI")
    same = f" · 규칙이나 합계 구조와 같아 뺀 것 {n - len(ai)}건" if n > len(ai) else ""
    print(f"{src.name}: AI 연결 {len(ai)}건을 넣었습니다(맞음 {sum(1 for c in ai if c.ok)} · 단수 차이 {sum(1 for c in ai if c.minor)} · "
          f"확인 {sum(1 for c in ai if dsd_links.asks(c))} · 안 맞음 {sum(1 for c in ai if dsd_links.failed(c))}{same}) → {defs_path}")
    sm = [c for c in checks if c.source == "AI" and c.group == "합계"]
    if new.get("units"):
        print("  단위를 바로잡은 표: " + ", ".join(f"{u['table']} → {u['unit']:,}" for u in new["units"]))
    if new.get("sums") or new.get("no_sums"):
        print(f"  AI 가 정한 합계 구조 {len(new.get('sums', []))}개(검증 칸 {len(sm)} · 맞음 {sum(1 for c in sm if c.ok)} · 단수 차이 {sum(1 for c in sm if c.minor)} · "
              f"안 맞음 {sum(1 for c in sm if dsd_links.failed(c))}) · 합계가 아니라고 한 것 {len(new.get('no_sums', []))}개")
    eng = [c for c in checks if c.group == "합계" and c.source != "AI" and dsd_links.failed(c)]
    if eng:                                          # 엔진이 찾은 구조에서 안 맞는 칸. 구조가 틀렸으면 sums 로 다시 적고, 맞으면 보고서의 차이다
        print(f"  엔진 합계 구조에서 안 맞는 칸 {len(eng)}곳")
        for c in eng[:20]:
            t = doc.table(c.table)
            print(f"    {c.kind} {c.table} {dsd_links._labels(t)[c.r]} · {t.header[c.c]}: {c.left:,} ↔ {c.right:,} ({c.label})")
    for x in dsd_ai.sum_review(doc, base, checks):
        why = "걸린 칸이 전부 안 맞습니다. 구조를 잘못 읽었을 수 있으니 표를 다시 읽으십시오" if x["all"] else f"{x['checks']}칸 가운데 {x['false']}칸이 안 맞습니다"
        print(f"  합계 안 맞음 {x['table']} {x['kind']} {x['ai']}: {why}" + (f" (엔진이 찾았던 구조: {x['engine']})" if x["engine"] else ""))
    req = dsd_ai.request(doc, checks, new, with_proposals=True)      # 넣은 뒤의 요청 자료: 아직 이어지지 않은 과목과 금액 대조 참고가 줄어든다
    (out / "dsd_연결요청.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "dsd_읽기자료.md").write_text(dsd_ai.reading(doc, new, checks, req["proposals"]), encoding="utf-8")
    if n_prop:
        vids = {x["id"] for x in new["links"] if x.get("via")}
        via = [c for c in ai if c.id in vids or c.id.rsplit("|", 1)[0] in vids]
        print(f"  엔진 후보 {len(req['proposals'])}건: 판정 없이 넣음 {sum(1 for x in req['proposals'] if x.get('mark') == '기본')} · O {n_prop['O']} · X {n_prop['X']} · 고침 {n_prop['고침']}"
              + (f" (후보로 넣은 연결 가운데 안 맞음 {sum(1 for c in via if dsd_links.failed(c))})" if via else ""))
    else:
        print("  " + _proposal_line(req["proposals"]) + '. 연결.json 의 "proposals": null 이라 후보는 넣지 않았습니다')
    print(f"  {dsd_ai.summary(req)} · 금액이 같은데 아직 연결이 없는 칸 짝 {len(req['amount_evidence'])}건 → dsd_연결요청.json")
    for x in dsd_ai.review(doc, checks):
        print(f"  {'단수 차이' if x['minor'] else ('확인' if x['when'] else '안 맞음')} {x['left']}: {x['left_value']:,} ↔ {x['right']} {x['right_value']:,} (차이 {x['diff']:,})")
        for y in ([] if x["minor"] else x["same_amount_cells"]):
            print(f"    같은 주석에서 그 금액과 같은 칸: {y['table']} {y['row']} · {y['col']}")
    return 0



def _fetch(a) -> int:
    from .report import dart_fetch as F

    src = a.src.strip()
    try:
        if re.fullmatch(r"\d{14}", src):
            rcept, how, base = src, "접수번호", Path(a.out) if a.out else Path.cwd()
        elif src.lower().endswith(".pdf") and Path(src).exists():
            rcept, how = F.from_pdf(Path(src))
            base = Path(a.out) if a.out else Path(src).resolve().parent
        else:
            print(f"받을 것을 알지 못함: {src}. 접수번호(14자리)나 DART 에서 받은 PDF 를 주십시오")
            return 2
        r = F.fetch(rcept, base, with_prior=not a.no_prior)
    except F.FetchError as e:                         # 오류 글에는 인증키가 없다
        print(f"원문을 받지 못함: {e}")
        return 2

    def line(x, what):
        kinds = " · ".join(["본문"] + list(x["split"])) if x["split"] else x["main"].name
        return f"{what} {x['rcept_no']} {x.get('report_nm') or x['name']} ({kinds}) → {x['main'].parent}"

    print(line(r["main"], f"원문 받음({how}):"))
    for x in r["priors"]:
        print("  " + line(x, "작년 비교:"))
    m, ps = r["main"], r["priors"]
    kinds = list(m["split"]) or [""]
    print("foot 명령:")
    for kind in kinds:
        me = m["split"].get(kind, m["main"]) if kind else m["main"]
        prior = [str(p["split"].get(kind, p["main"]) if kind else p["main"]) for p in ps if not kind or kind in p["split"]]
        other = [m["split"][k] for k in m["split"] if k != kind]
        cmd = f'python -m audit dsd foot "{me}"' + ("" if not prior else " --prior " + " ".join(f'"{p}"' for p in prior)) \
              + (f' --pair "{other[0]}"' if other else "") + f' --out "{base / ("푸팅결과_" + kind if kind else "푸팅결과")}"'
        print("  " + cmd)
    return 0
