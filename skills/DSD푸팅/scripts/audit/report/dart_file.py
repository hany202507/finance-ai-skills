"""DART 제출 파일 초안과 DART 검토 (R4 report, 2026-10-05).

DART 감사보고서 본문 순서(감사보고서 → (첨부) 재무제표 → 주석 → 외부감사 실시내용)를 따른 HTML 을 만들고, 같은 내용으로
DART 편집기 dsd 도 만든다(dsd.py, 규격은 dsd 샘플 1건 기준: docs/specs/2026-10-06-감사-DART-dsd-규격.md). 본문은 지금 있는 8820 · 8810 · 8400 워드를 그대로 이어 붙인다.
회계사가 워드를 고쳤으면 고친 내용이 들어간다. 외부감사 실시내용 표는 DART 검토 조서의 기입란 값으로 채운다.

DART 검토는 HTML(또는 dsd)을 다시 읽어 본문 숫자 ↔ 8810 날인재무제표 ↔ 8400 주석 엑셀 ↔ 수정 후 시산표를 맞추고, 본문 문장 ↔ 8820 을 맞춘다.
회사나 다른 사람이 만든 DART 파일도 같은 이름(DART_제출파일_v<판>.html 또는 .dsd)으로 두면 같은 표로 검토한다. 회계사가 고쳤거나
회사가 만든 dsd 가 있으면 dsd 를 먼저 읽는다(report._dart_source).

주석 거르기(2026-10-06): 8400 공시 점검이 「해당 없음」인 주석은 DART 에서 빼고 번호를 1 부터 다시 매긴다. 문단 속 「주석 N」 과
표 캡션 「표 N-k」 도 같은 대응표로 바꾸고, 대응표는 HTML meta(audit-note-map)에 남겨 DART ↔ 8400 엑셀 대사가 표 번호를 맞춘다.
검토 전 초안 상자: 의견 미선택 · 의견 기입 문제 · 검토 전 주석 · 남은 기입 칸이 있으면 본문 맨 위(첫 h1 앞)에 상자를 단다.
대사는 첫 h1 앞을 읽지 않으므로 상자는 대사에서 빠진다. 상자 문장에는 기입 표시 글자를 쓰지 않는다(기입 칸 수에 섞이지 않게).
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .. import wp
from .base import RBook, blocks_hash, count_marks, doc_tables, fmt, norm, prev_inputs, read_html
from .footing import compare_tables, foot_fs, fs_doc_values, item, tie_fs

PARTS = ("감사보고서", "(첨부) 재무제표", "주석", "외부감사 실시내용")
PEOPLE = ["품질관리검토자(심리실 등)", "담당 회계사 · 담당이사(업무수행이사)", "담당 회계사 · 등록 공인회계사",
          "담당 회계사 · 수습 공인회계사", "전산감사 · 세무 · 가치평가 등 전문가"]
PCOLS = ["당기 인원", "당기 시간", "전기 인원", "전기 시간"]
WORKS = ["전반감사계획(감사착수단계)", "현장감사 주요내용", "재고자산실사(입회)", "금융자산실사(입회)", "외부조회",
         "지배기구와의 커뮤니케이션", "외부전문가 활용"]
WCOLS = ["수행 시기", "주요 내용"]
REVIEW_SHEET = "외부감사 실시내용"
WARN_TITLE = "검토 전 초안"
WARN_ID = "audit-draft-warning"
WARN_TEXT = "아래가 끝나지 않아 제출용이 아닙니다. 끝나면 python -m audit report dart 로 다시 만들어 주십시오."
_REF = re.compile(r"주석\s*(\d+)")
_CAP = re.compile(r"^표\s*(\d+)-(\d+)")


def paths(d: Path) -> tuple[Path, Path]:
    h = wp.path_for(d, "DART", ".html")
    return h, h.with_name(h.name.replace("제출파일", "검토").replace(".html", ".xlsx"))


def audit_info_blocks(inputs: dict) -> list:
    def v(sheet_label):
        x = inputs.get((REVIEW_SHEET, sheet_label))
        return "【기입】" if x is None or (isinstance(x, str) and not x.strip()) else (fmt(x) if isinstance(x, (int, float)) else str(x))

    rows = [["감사참여자 구분"] + PCOLS]
    for p in PEOPLE:
        rows.append([p] + [v(f"{p} {c}") for c in PCOLS])
    works = [["구분"] + WCOLS] + [[w] + [v(f"{w} {c}") for c in WCOLS] for w in WORKS]
    return [("h", 2, "감사참여자 구분별 인원수 및 감사시간"), ("table", rows), ("h", 2, "주요 감사실시내용"), ("table", works)]


def _html(blocks_by_part: list[tuple[str, list]], title: str) -> str:
    body = []
    for part, bl in blocks_by_part:
        body.append(f"<h1>{html.escape(part)}</h1>")
        for b in bl:
            if b[0] == "h":
                lv = min(b[1] + 1, 4)
                body.append(f"<h{lv}>{html.escape(b[2])}</h{lv}>")
            elif b[0] == "p":
                body.append(f"<p>{html.escape(b[1])}</p>")
            elif b[0] == "cap":
                body.append(f'<p class="cap">{html.escape(b[1])}</p>')
            elif b[0] == "table":
                rows = []
                for i, r in enumerate(b[1]):
                    tag = "th" if i == 0 else "td"
                    cells = "".join(f'<{tag}{" class=n" if i and j else ""}>{html.escape(str(c))}</{tag}>' for j, c in enumerate(r))
                    rows.append(f"<tr>{cells}</tr>")
                body.append("<table>" + "".join(rows) + "</table>")
    return "\n".join(body)


STYLE = """body{font-family:'맑은 고딕','Malgun Gothic',sans-serif;font-size:10pt;max-width:820px;margin:24px auto;padding:0 16px;color:#1a1c19;background:#fff}
h1{font-size:15pt;border-bottom:2px solid #1B2A4A;padding-bottom:4px;margin-top:36px}h2{font-size:12pt;margin-top:22px}h3{font-size:11pt}
table{border-collapse:collapse;width:100%;margin:8px 0 14px}th,td{border:1px solid #c9cfc5;padding:3px 6px}th{background:#eef1ec}
td.n{text-align:right;white-space:nowrap}.cap{font-weight:bold;font-size:9pt;margin-bottom:2px}"""


WARN_STYLE = "#audit-draft-warning{border:2px solid #B3261E;background:#FBEAE8;padding:8px 14px;margin:12px 0}"


def _plain(t: str) -> str:
    """상자 문장에서 기입 표시 괄호를 뺀다(count_marks 가 상자를 세지 않게)."""
    return str(t).replace("【", "「").replace("】", "」")


def write_html(path: Path, parts: list[tuple[str, list]], title: str, warning: list[str] | None = None,
               note_map: dict | None = None) -> Path:
    body = _html(parts, title)
    if warning:
        items = "".join(f"<p>· {html.escape(_plain(w))}</p>" for w in warning)
        body = (f'<section id="{WARN_ID}"><h2>{WARN_TITLE}</h2>'
                f"<p>{html.escape(WARN_TEXT)}</p>"
                f"{items}</section>\n" + body)
    meta = (f'<meta name="audit-note-map" content="{html.escape(json.dumps({str(k): v for k, v in note_map.items()}))}">'
            if note_map else "")
    tmp = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">{meta}<title>{html.escape(title)}</title>'
           f"<style>{STYLE}{WARN_STYLE}</style></head><body>\n{body}\n</body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tmp, encoding="utf-8")
    h = blocks_hash(read_html(path))
    path.write_text(tmp.replace("<meta charset=\"utf-8\">", f"<meta charset=\"utf-8\"><meta name=\"audit-engine\" content=\"{h}\">", 1),
                    encoding="utf-8")
    return path


def filter_notes(blocks: list, exclude: list[int]) -> tuple[list, dict[int, int]]:
    """뺀 주석(공시 점검 '해당 없음')을 지우고 번호를 1 부터 다시 매긴다. 문단의 '주석 N' 과 캡션 '표 N-k' 도 바꾼다.
    뺀 주석을 가리키는 참조는 '주석 (뺀 주석)' 으로 남겨 회계사가 보게 한다. (블록, {옛 번호: 새 번호})."""
    from .notes import split_notes

    head, parts = split_notes(blocks)
    ex = {int(x) for x in exclude}
    keep = [p for p in parts if p[0] not in ex]
    m = {old: new for new, (old, _, _) in enumerate(keep, 1)}
    if not ex:
        return list(blocks), m

    def ref(t: str) -> str:
        return _REF.sub(lambda x: f"주석 {m[int(x.group(1))]}" if int(x.group(1)) in m else "주석 (뺀 주석)", t)

    out = list(head)
    for old, title, bl in keep:
        out.append(("h", 2, f"{m[old]}. {title}"))
        for b in bl:
            if b[0] == "cap":
                c = _CAP.match(b[1])
                t = f"표 {m.get(int(c.group(1)), c.group(1))}-{c.group(2)}{b[1][c.end():]}" if c else b[1]
                out.append(("cap", t))
            elif b[0] == "p":
                out.append(("p", ref(b[1])))
            else:
                out.append(b)
    return out, m


def warning_lines(op: dict, state: dict, marks: int) -> list[str]:
    """검토 전 초안 상자 줄. 빈 목록이면 상자를 달지 않는다."""
    out = [f"8600 감사의견: {p}" for p in (op.get("problems") or [])]
    if state.get("open"):
        out.append("8400 공시 점검이 끝나지 않은 주석: " + ", ".join(f"주석 {n}" for n in state["open"]))
    if marks:
        out.append(f"남은 기입 칸 {marks}개(감사보고서 · 재무제표 · 주석 · 외부감사 실시내용)")
    return out


def has_warning(blocks: list) -> bool:
    for b in blocks:
        if b[0] == "h" and b[1] == 1:
            return False
        if b[0] == "h" and norm(b[2]) == norm(WARN_TITLE):
            return True
    return False


def read_note_map(path: Path) -> dict[int, int] | None:
    p = Path(path)
    if not p.exists():
        return None
    m = re.search(r'<meta name="audit-note-map" content="([^"]*)">', p.read_text(encoding="utf-8"))
    return {int(k): int(v) for k, v in json.loads(html.unescape(m.group(1))).items()} if m else None


def split_parts(blocks: list) -> dict:
    out, cur = {}, None
    for b in blocks:
        if b[0] == "h" and b[1] == 1 and norm(b[2]) in {norm(p) for p in PARTS}:
            cur = next(p for p in PARTS if norm(p) == norm(b[2]))
            out[cur] = []
            continue
        if cur:
            out[cur].append(b)
    return out


def review(dart_blocks: list, fs: dict, fs_doc_blocks: list | None, note_tables_xlsx: dict, report_blocks: list | None,
           note_map: dict | None = None) -> list[dict]:
    """DART HTML 을 8810 · 8400 · 8820 · 엔진 값과 맞춘다. note_map({8400 번호: DART 번호})이 있으면 8400 엑셀 표 번호를
    DART 번호로 바꿔 맞추고, 대응표에 없는(뺀) 주석의 표는 대사하지 않는다."""
    if note_map:
        def renum(k: str):
            n, _, rest = k.partition("-")
            return f"{note_map[int(n)]}-{rest}" if n.isdigit() and int(n) in note_map else None

        note_tables_xlsx = {renum(k): v for k, v in note_tables_xlsx.items() if renum(k)}
    parts = split_parts(dart_blocks)
    out = []
    for p in PARTS:
        if p not in parts:
            out.append(item("제출 구성", "DART 파일", f"'{p}' 부분이 없음", None, 0, "불일치"))
    fsb = parts.get("(첨부) 재무제표", [])
    dv = fs_doc_values(fsb)
    out += foot_fs(fs, dv, "DART")
    out += tie_fs(fs, dv, "DART")
    if fs_doc_blocks is not None:
        sv = fs_doc_values(fs_doc_blocks)
        for key, title in (("bs", "재무상태표"), ("is", "손익계산서")):
            for lab, vals in dv[key].items():
                other = sv[key].get(lab)
                for j, cn in enumerate(("당기", "전기")):
                    a = vals[j] if j < len(vals) else None
                    b = other[j] if other and j < len(other) else None
                    if a is None and b is None:
                        continue
                    out.append(item("DART ↔ 8810", f"DART {title}", f"{lab} {cn}", a, b))
    nb = doc_tables(parts.get("주석", []))
    out += compare_tables(note_tables_xlsx, nb, "DART ↔ 8400", "8400 주석 엑셀", "DART 주석")
    if report_blocks is not None:
        a = [norm(b[-1]) for b in parts.get("감사보고서", []) if b[0] != "table"]
        r = [norm(b[-1]) for b in report_blocks if b[0] != "table"]
        if a == r:
            out.append(item("DART ↔ 8820", "DART 감사보고서", f"문단 {len(a)}개가 8820 과 같음", 0, 0, "일치"))
        else:
            sa, sr = set(a), set(r)
            for t in [x for x in r if x not in sa]:
                out.append(item("DART ↔ 8820", "DART 감사보고서", f"8820 에만 있는 문단: {t[:60]}", None, None, "불일치"))
            for t in [x for x in a if x not in sr]:
                out.append(item("DART ↔ 8820", "DART 감사보고서", f"DART 에만 있는 문단: {t[:60]}", None, None, "불일치"))
            if sa == sr:
                out.append(item("DART ↔ 8820", "DART 감사보고서", "문단 순서가 다름", None, None, "불일치"))
    n = count_marks(dart_blocks)
    out.append(item("기입", "DART 파일", f"남은 【기입】 칸 {n}개", n, 0, "확인" if n else "일치"))
    return out


def write_review(d: Path, path: Path, items: list[dict], keep: dict, dart_path: Path, sources: list[tuple[str, str, str]]) -> Path:
    from .footing import counts

    b = RBook(d, "DART", title="DART 검토", standard="DART 제출 파일 초안 대사 · HTML 과 dsd(dsd 샘플 1건 기준, 편집기로 열어 확인 전)", keep=keep)
    ws, row = b.sheet("제출 구성", [6, 30, 44, 24])
    row = b.head(ws, row, ["순서", "문서", "원천 파일", "상태"])
    for i, (doc, src, st) in enumerate(sources, 1):
        b.put(ws, row, 1, i)
        b.put(ws, row, 2, doc, bold=True)
        b.put(ws, row, 3, src, wrap=True)
        b.put(ws, row, 4, st, flag=any(w in st for w in ("없음", "기입", "검토 전", "고르지 않음")), wrap=True)
        row += 1
    ws.cell(row + 1, 1, f"대사한 DART 파일: {dart_path.name}. 엔진은 HTML 과 dsd(dsd 샘플 1건 기준 규격)를 함께 만들고, "
                        "회계사가 고쳤거나 회사가 만든 dsd 가 있으면 그 dsd 를 대사한다").font = wp.font(size=9, color=wp.MUTED)

    ws2, r = b.sheet("값 대사", [16, 30, 46, 18, 18, 16, 10, 24])
    c = counts(items)
    b.put(ws2, r, 1, f"불일치 {c['불일치']}건 · 일치 {c['일치']}건 · 확인 {c['확인']}건", bold=True, color="B3261E" if c["불일치"] else None)
    r += 2
    r = b.head(ws2, r, ["구분", "위치", "검사", "DART 금액", "대사 금액", "차이", "결과", "비고"])
    for x in sorted(items, key=lambda x: {"불일치": 0, "확인": 1, "일치": 2}[x["result"]]):
        for j, v in enumerate((x["area"], x["where"], x["item"]), 1):
            b.put(ws2, r, j, v, wrap=True)
        b.put(ws2, r, 4, x["doc"], fmt=wp.WON)
        b.put(ws2, r, 5, x["ref"], fmt=wp.WON)
        b.put(ws2, r, 6, x["diff"], fmt=wp.WON)
        b.put(ws2, r, 7, x["result"], flag=x["result"] == "불일치", bold=x["result"] != "일치")
        b.put(ws2, r, 8, x["note"], wrap=True)
        r += 1
    b.conclusion(ws2, r, 8, "검토 결론(제출해도 되는지)")

    ws3, r = b.sheet(REVIEW_SHEET, [40, 16, 16, 16, 16])
    r = b.section(ws3, r, "감사참여자 구분별 인원수 및 감사시간 (감사인 기입, 8700A 감사시간과 맞춘다)")
    r = b.head(ws3, r, ["감사참여자 구분"] + PCOLS)
    for p in PEOPLE:
        b.put(ws3, r, 1, p)
        for j, cn in enumerate(PCOLS, 2):
            b.ask(ws3, r, j, f"{p} {cn}", rule="number", fmt=wp.WON)
        r += 1
    r += 1
    r = b.section(ws3, r, "주요 감사실시내용 (감사인 기입)")
    r = b.head(ws3, r, ["구분"] + WCOLS)
    for w in WORKS:
        b.put(ws3, r, 1, w)
        for j, cn in enumerate(WCOLS, 2):
            b.ask(ws3, r, j, f"{w} {cn}", rule="required")
        r += 1
    return b.save(path)


def keep_inputs(path: Path) -> dict:
    return prev_inputs(path)
