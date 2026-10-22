"""DSD 푸팅: AI 가 정하는 연결의 읽기 자료 · 요청 · 반영(2026-10-12).

재무제표와 주석 사이, 주석과 주석 사이 연결은 AI 가 주석의 제목 · 문장 · 표를 읽고 뜻으로 정한다. AI 는 숫자를 만들지 않고
「이 칸은 저 칸과 같아야 한다」 만 근거와 함께 적는다. 계산과 비교는 엑셀 수식과 엔진이 한다. 금액이 같은 칸을 엔진이 찾는 것
(dsd_refs)은 연결을 걸지 않고 AI 의 참고와 채점에만 쓴다.

  reading   AI 가 읽을 자료: 재무제표 넷과 주석 전부를 원문 순서대로.
  request   연결을 넣은 뒤 놓친 것을 볼 자료: 주석을 가리키는데 아직 이어지지 않은 과목(unlinked), 합계 줄 · 열이 있는데 검증이
            걸리지 않은 곳(unchecked_totals), 금액이 같은데 연결이 없는 칸 짝(amount_evidence).
  apply     AI 가 적은 연결을 검사해 연결 정의에 넣는다. 표 · 행 · 열 이름이 실제 칸으로 풀리지 않는 연결이 하나라도 있으면
            아무것도 쓰지 않는다. 넣은 연결은 source 「AI」, confirmed false 다. 확인은 회계사가 엑셀의 확인 칸에서 한다.
            앞서 넣은 AI 연결은 새 목록으로 바뀐다. 한 칸에 연결을 여럿 걸 수 있다.
  review    금액이 안 맞는 AI 연결마다 같은 주석 안에서 그 금액과 같은 다른 칸을 찾아 준다(총액과 순액을 바꿔 건 경우를 다시 보게).
  proposals 엔진이 금액을 보지 않고 위치 · 이름 · XBRL 코드로 낸 연결 후보(dsd_propose, 2026-10-22). AI 는 연결.json 의 proposals 에
            후보 번호로 O · X · 고침을 적고, 후보에 없는 연결만 links 에 적는다. O · 고침은 AI 연결과 같이 confirmed false 로 들어간다.
"""
from __future__ import annotations

import json
import re

from .base import norm
from .dsd_grid import Doc, Table
from .dsd_links import (PAIR_ID, Check, _isnum, _labels, _ref, _resolve, col_prefix, cut_prefix, failed, find_col, find_row, is_rate, overlay, period_col,
                        struct_text, total_kind)

STATEMENTS = ("재무상태표", "손익계산서", "현금흐름표")
PRIOR_VERDICTS = ("불일치", "작년 불일치", "설명됨", "걸지 않음")
VERDICTS = ("숫자 오류", "표시 오류", "설명 부족", "보고서 불일치", "작년 보고서 불일치", "식 고침", "확인", "걸지 않음", "엔진 판독")
# 11단계: 보고서 불일치를 숫자 오류(금액이 틀림) · 표시 오류(금액은 맞고 이름 · 기간 · 분류 표시가 틀림) · 설명 부족(금액은 맞고 문장이 모자람)으로 나눴다.
# 옛 이름 「보고서 불일치」 는 숫자 오류로 읽는다(dsd_links.OLD_VERDICT)
CMPS = ("le", "ge")
GRADES = ("항등식", "조건부", "약함")
_EXPR_OK = re.compile(r"^[\sA-Za-z_가-힣0-9.+\-*/()]+$")


def _dec(x: float) -> str:
    """식에 넣는 배수(지수 꼴 없이, 엑셀 수식에도 그대로 들어간다)."""
    return str(int(x)) if float(x).is_integer() else f"{x:.12f}".rstrip("0").rstrip(".")


def _calc_expr(expr: str, names: list[str]) -> tuple[str | None, str]:
    """계산 검증의 식(「a / b * 100」)을 항 자리 식(「{0} / {1} * 100」)으로 바꾼다. (식, 문제). 숫자 · 사칙 · 괄호 · 항 이름만 받는다."""
    import ast

    if not _EXPR_OK.match(expr or ""):
        return None, "식에는 항 이름, 숫자, + - * /, 괄호만 적습니다"
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None, f"식 「{expr}」 을 읽지 못했습니다"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in names:
                return None, f"식의 「{node.id}」 가 vars 에 없습니다"
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Load)):
            return None, "식에는 더하기 · 빼기 · 곱하기 · 나누기와 괄호만 씁니다"
    out = re.sub(r"[A-Za-z_가-힣][A-Za-z_가-힣0-9]*", lambda m: "{" + str(names.index(m.group(0))) + "}" if m.group(0) in names else m.group(0), expr)
    return out, ""


def _table_json(t: Table) -> dict:
    return {"id": t.id, "caption": t.caption, "unit": t.unit, "header": t.header,
            "rows": [[r[0]] + [t.nums[i][j] if t.nums[i][j] is not None else r[j] for j in range(1, len(t.header))] for i, r in enumerate(t.rows)]}


def _label_cols(t: Table) -> int:
    """줄 이름으로 이은 글자 열의 수."""
    numeric = lambda j: any(_isnum(r[j]) and r[j] != 0 and not t.rate(i, j) for i, r in enumerate(t.nums))      # noqa: E731
    return min(next((j for j in range(1, len(t.header)) if numeric(j)), len(t.header)), 3)


def _no_money(t: Table) -> bool:
    """맞춰 볼 금액이 없는 표. 숫자 칸이 하나도 없거나(글만 있는 표) 비율 칸(%, 이름에 「율」)뿐인 표(종속기업 목록의 지분율)다.
    주식수 · 연도처럼 비율이 아닌 숫자가 하나라도 있으면 아니다. 문장 금액 표는 늘 금액이 있다."""
    if t.kind:
        return False
    return not any(_isnum(t.nums[i][j]) and not t.rate(i, j) and not is_rate(t.header[j]) for i in range(len(t.rows)) for j in range(1, len(t.header)))


def reading(doc: Doc, defs: dict | None = None, checks: list[Check] | None = None, proposals: list[dict] | None = None) -> str:
    """AI 가 읽을 자료: 재무제표 넷과 주석 전부를 원문 순서대로. 표는 이름을 글자 그대로 적는다(연결을 적을 때 이 이름을 쓴다).
    defs 와 checks 를 주면 표마다 엔진이 금액 근거로 찾은 합계 구조와, 합계 줄 · 열인데 구조를 찾지 못한 곳을 적는다."""
    out = [f"# {doc.source} 읽기 자료", "",
           "표 번호는 [대괄호], 표의 첫 열이 행 이름, 첫 줄이 열 이름이다. 재무제표 표의 마지막 열 「주석」 은 그 과목이 가리키는 주석 번호다.",
           "표 번호 옆에 「줄 이름: 앞의 N칸」 이라고 적힌 표는 앞의 N칸을 띄어 이은 것이 행 이름이다(「기초 | 취득원가」 줄은 「기초 취득원가」). 빈 칸은 건너뛴다.",
           "표 아래 「엔진 합계」 는 엔진이 금액이 맞는 것을 근거로 찾은 합계 구조다. 틀렸거나 빠진 것은 sums · no_sums 로 적는다.",
           "맞춰 볼 금액이 없는 표(지분율 목록, 글만 있는 표)는 한 줄로 줄였다. 칸이 필요하면 python -m audit dsd read 의 dsd_표.json 을 본다."]
    if proposals:
        out.append("표 아래 「후보 P0001」 줄은 엔진이 위치 · 이름 · XBRL 코드로 낸 연결 후보다(금액은 보지 않았다). 판정을 적지 않은 후보는 그대로 연결로 들어간다. "
                   "틀린 후보만 연결.json 의 proposals 에 번호로 X(이유) · 고침을 적는다.")
    found = {s["table"]: s for s in (defs or {}).get("structures", [])}
    by_table: dict[str, list] = {}
    for x in proposals or []:
        by_table.setdefault(x["left"]["table"], []).append(x)
    lost: dict[str, list] = {}
    for x in (unchecked_totals(doc, checks, defs) if checks is not None else []):
        lost.setdefault(x["table"], []).append(f"「{x.get('row', x.get('col'))}」 {'줄' if x['what'] == '합계 줄' else '열'}({', '.join(x.get('cells', []))})")
    for p in doc.parts:
        out.append(f"\n## {p.key} {p.title}")
        for x in p.items:
            if x[0] == "p":
                if p.key.startswith("주석"):
                    out.append(x[1])
                continue
            t = x[1]
            if _no_money(t):                          # 지분율 목록 · 글만 있는 표는 한 줄로 줄인다(2026-10-22 실행 시간 P6)
                labels = _labels(t)
                what = "지분율 · 비율만 있는 표" if any(_isnum(v) for r in t.nums for v in r[1:]) else "글만 있는 표"
                out.append(f"\n[{t.id}] {what}. 줄 {len(t.rows)}개 · 열 {' · '.join(h for h in t.header if h.strip())}"
                           + (f" · 첫 줄 「{labels[0]}」 · 끝 줄 「{labels[-1]}」" if labels else "") + ". 맞춰 볼 금액이 없어 칸을 적지 않았다")
                if t.id in lost:
                    out.append("합계 구조를 찾지 못한 곳: " + ", ".join(lost[t.id]))
                continue
            pre = col_prefix(t.header)
            out.append(f"\n[{t.id}] 단위 {t.unit}" + (f" · 줄 이름: 앞의 {_label_cols(t)}칸" if t.labels else "")
                       + (" · 주석 문단의 금액을 모은 표(원문에 없는 표). 줄 이름은 금액 앞의 글, 금액은 문장에 적힌 단위" if t.kind else "")
                       + (" · 칸에 단위가 붙은 칸은 숫자 뒤에 그 단위를 적었다" if t.cell_units else "")
                       + (f" · 열 이름 공통 앞부분 「{pre}」 은 떼고 적었다(연결에 뗀 이름을 그대로 써도 된다)" if pre else ""))
            out.append("| " + " | ".join(cut_prefix(h, pre) if j else h for j, h in enumerate(t.header)) + (" | 주석" if t.refs else "") + " |")
            words = {1: "원", 1000: "천원", 10000: "만원", 1000000: "백만원", 100000000: "억원", 10 ** 12: "조원", 0.01: "%"}
            for i, r in enumerate(t.rows):
                cells = [r[0]] + [(f"{t.nums[i][j]:,}" + (words.get(t.cell_units[(i, j)], "") if t.cell_units and (i, j) in t.cell_units else ""))
                                  if _isnum(t.nums[i][j]) else (r[j] or "") for j in range(1, len(t.header))]
                if t.refs:
                    cells.append(",".join(map(str, t.refs[i])))
                out.append("| " + " | ".join(cells) + " |")
            s = overlay(t, found.get(t.id), [x for x in (defs or {}).get("sums", []) + [dict(n, off=True) for n in (defs or {}).get("no_sums", [])] if x["table"] == t.id])
            for key, name in (("vsum", "세로"), ("hsum", "가로")):
                if s[key]:
                    out.append(f"엔진 합계({name}): " + "; ".join(struct_text(t, x, key) + (" (AI)" if x.get("source") == "AI" else "") for x in s[key]))
            if t.id in lost:
                out.append("합계 구조를 찾지 못한 곳: " + ", ".join(lost[t.id]))
            for x in by_table.get(t.id, []):
                out.append(f"후보 {x['id']}{(' (' + x['mark'] + ')') if x.get('mark') else ''}: {proposal_text(x)}")
    return "\n".join(out) + "\n"


def _cell_text(d: dict) -> str:
    return f"{d['table']} 「{d['row']}」{'#' + str(d['row_nth']) if d.get('row_nth', 1) != 1 else ''} · 「{d['col']}」{'#' + str(d['col_nth']) if d.get('col_nth', 1) != 1 else ''}"


def proposal_text(x: dict) -> str:
    """후보 한 줄: 「왼쪽 칸 = 오른쪽 칸 [근거 · 등급]」. 여러 칸을 더하는 후보(회사별 표)는 칸을 다 적지 않고 표 · 줄 · 열 이름 앞부분 · 칸 수로 적는다."""
    r, g = x["right"][0], x.get("sum_of")
    if g:
        right = f"{g['table']} 「{g['row']}」 줄에서 열 이름이 「{g['head']}」 로 시작하는 {g['n']}칸의 합"
    else:
        right = " + ".join(f"{'-' if y.get('sign', 1) < 0 else ''}{_cell_text(y)}" for y in x["right"]) if len(x["right"]) > 1 \
            else f"{'-' if r.get('sign', 1) < 0 else ''}{_cell_text(r)}"
    return (f"{_cell_text(x['left'])} = {right} [{x['how']}"
            + (f" · {x['grade']}" if x.get("grade") != "항등식" else "") + (f" · 조건: {x['when']}" if x.get("when") else "") + "]")


def _psig(doc: Doc, x: dict) -> str:
    return _sig(_ref_of(doc, x["left"])) + "=" + "+".join(_sig(_ref_of(doc, r)) for r in x["right"])


def _ids(spec) -> list[str]:
    """「P0003」 · 「P0001-P0012」 → 후보 번호 목록."""
    m = re.fullmatch(r"\s*P(\d+)\s*[-~]\s*P?(\d+)\s*", str(spec))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return [f"P{k:04d}" for k in range(a, b + 1)] if a <= b else []
    return [str(spec).strip()]


def expand_proposals(doc: Doc, patch: dict, defs: dict | None = None, strict: bool = True) -> tuple[dict, list[str], dict]:
    """연결.json 의 proposals(엔진 후보의 O · X · 고침)를 links · skipped 로 풀어 patch 에 더한다. (새 patch, 문제, {후보 서명: 판정}).

    proposals = {"O": ["P0001-P0012", "P0015"], "X": {"P0013": "이유"}, "고침": [{"id": "P0020", "right": [...], ...}]}
    O 는 후보 그대로 연결이 되고, 고침은 후보에 적은 키(left · right · grade · when · cmp · basis …)만 바꿔 연결이 된다.
    X 는 걸지 않은 연결로 「검증 범위」 시트에 이유와 함께 남는다. 판정을 적지 않은 후보는 「기본」 으로 그대로 연결이 된다(2026-10-22 결정:
    엔진 후보는 기본으로 넣고 AI 는 X · 고침만 적는다. 틀린 후보는 금액이 어긋나 FALSE 로 올라온다). --add 로 더할 때는 앞서 판정한 후보를
    판정한 것으로 보고 새로 생긴 후보만 기본으로 넣는다. strict 는 옛 호출을 위해 남긴 인자이고 쓰지 않는다."""
    from . import dsd_propose

    got = patch.get("proposals") or {}
    if not isinstance(got, dict):
        return patch, ["proposals 는 {\"O\": [...], \"X\": {...}, \"고침\": [...]} 꼴로 적어 주십시오"], {}
    props = {x["id"]: x for x in dsd_propose.proposals(doc)}
    problems, marks, links, skipped = [], {}, [], []

    def take(pid, verdict):
        if pid not in props:
            problems.append(f"proposals {verdict}: 후보 「{pid}」 가 없습니다(dsd_연결요청.json 의 proposals 를 다시 보십시오)")
        elif pid in marks:
            problems.append(f"proposals: 후보 「{pid}」 를 두 번 적었습니다({marks[pid]} · {verdict})")
        else:
            marks[pid] = verdict
            return props[pid]
        return None

    for spec in got.get("O") or []:
        for pid in _ids(spec):
            x = take(pid, "O")
            if x is not None:
                links.append({k: x[k] for k in ("left", "right", "grade", "when") if k in x} | {"basis": x["basis"] + " (엔진 후보)", "via": pid})
    xs = got.get("X") or {}
    xs = xs if isinstance(xs, dict) else {str(e.get("id")): e.get("why", "") for e in xs if isinstance(e, dict)}
    for spec, why in xs.items():
        for pid in _ids(spec):
            x = take(pid, "X")
            if x is None:
                continue
            if not str(why or "").strip():
                problems.append(f"proposals X: 후보 「{pid}」 를 걸지 않는 이유를 한 줄 적어 주십시오")
            skipped.append({"what": f"엔진 후보 {pid}: {proposal_text(x)}", "why": str(why or "").strip()})
    for e in got.get("고침") or got.get("edit") or []:
        x = take(str((e or {}).get("id", "")), "고침") if isinstance(e, dict) else None
        if x is None:
            continue
        y = {k: x[k] for k in ("left", "right", "grade", "when") if k in x}
        y.update({k: v for k, v in e.items() if k != "id"})
        if "grade" in e and "when" not in e and e["grade"] != "조건부":
            y.pop("when", None)
        y["basis"] = str(e.get("basis") or x["basis"] + " (엔진 후보를 고침)")
        y["via"] = x["id"]
        links.append(y)
    before = (defs or {}).get("proposal_marks", {})
    for pid, x in props.items():                    # 판정을 적지 않은 후보는 기본으로 넣는다. 앞서(--add 전) 판정한 후보는 그 판정을 따른다
        if pid in marks:
            continue
        old = before.get(_psig(doc, x))
        if old and old != "기본":
            continue
        marks[pid] = "기본"
        links.append({k: x[k] for k in ("left", "right", "grade", "when") if k in x} | {"basis": x["basis"] + " (엔진 후보, 판정 없이 넣음)", "via": pid})
    out = {k: v for k, v in patch.items() if k != "proposals"}
    out["links"] = list(patch.get("links", [])) + links
    out["skipped"] = list(patch.get("skipped", [])) + skipped
    return out, problems, {_psig(doc, props[pid]): v for pid, v in marks.items()}


def evidence(doc: Doc, checks: list[Check]) -> list[dict]:
    """금액 대조가 찾은 칸 짝 가운데 아직 연결이 없는 것. AI 가 놓친 연결이 있는지 볼 참고다. 금액이 같다는 것만으로 걸지 않는다."""
    from . import dsd_refs

    linked = {(c.table, c.r, c.c) for c in checks if c.group == "레퍼"} | {(t[0], t[1], t[2]) for c in checks if c.group == "레퍼" for t in c.terms}
    out = []
    for x in dsd_refs.detect(doc, set()):
        got = [_resolve(doc, x["left"], None)] + [_resolve(doc, r, None) for r in x["right"]]
        if any(g is None for g in got) or all((g[0].id, g[1], g[2]) in linked for g in got):
            continue
        out.append({"left": {k: x["left"][k] for k in ("table", "row", "row_nth", "col")},
                    "right": [{k: r[k] for k in ("table", "row", "row_nth", "col")} for r in x["right"]], "why": x["basis"]})
    return out


FS_TOTALS = {      # 재무제표 본표에서 이름이 합계 꼴은 아니지만 다른 줄의 합인 줄. 과목 단계가 없는 K-IFRS 본표에서 구조가 없으면 알린다
    "재무상태표": ("유동자산", "비유동자산", "유동부채", "비유동부채"),
    "손익계산서": ("매출총이익", "매출총손실", "매출총손익", "영업이익", "영업손실", "영업손익", "법인세비용차감전", "당기순이익", "당기순손실", "당기순손익", "총포괄"),
    "현금흐름표": ("영업활동", "투자활동", "재무활동", "현금의증가", "현금및현금성자산의순증가", "현금및현금성자산의증가", "기말의현금", "기말현금"),
}


def _fs_total(t: Table, i: int, labels: list[str]) -> bool:
    """재무제표 본표의 중간 합계로 보이는 줄. 과목 단계를 알면 하위 과목이 있는 줄, 모르면 이름으로 본다."""
    if not t.refs and not t.levels:              # 재무제표 본표가 아니다
        return False
    if t.levels and t.levels[i] is not None and not t.id.startswith("자본변동표"):      # 자본변동표는 줄이 기간이라 단계가 합계 관계를 뜻하지 않는다
        nxt = next((x for x in t.levels[i + 1:] if x is not None), None)
        if nxt is not None and nxt > t.levels[i]:
            return True
    name = "".join(labels[i].split())
    keys = next((v for k, v in FS_TOTALS.items() if t.id.startswith(k)), ())
    if t.id.startswith("현금흐름표"):
        return any(name.startswith(k) for k in keys) and ("현금흐름" in name or "현금" in name[:6] or name.startswith("기말"))
    return any(name.startswith(k) for k in keys)


_CLOSING = re.compile(r"^(기말|당기말|전기말)(잔액|금액|장부금액|장부가액|순장부금액)?(\(.*\))?$")      # 「기말상품재고액」 「기말 이연법인세자산」 은 변동표의 기말이 아니다


def _closing(names: list[str], i: int) -> bool:
    """변동표의 기말: 이름이 「기말」 로 시작하고 앞에 「기초」 가 있다. 합계 이름은 아니지만 기초와 변동의 합이다."""
    low = ["".join(str(x).split()) for x in names]
    return bool(_CLOSING.match(low[i])) and any(x.startswith("기초") for x in low[:i])


def unchecked_totals(doc: Doc, checks: list[Check], defs: dict | None = None) -> list[dict]:
    """합계 · 소계 줄이나 열에서 합계 검증이 걸리지 않은 칸이 있는 곳. 줄(열)의 칸 가운데 하나라도 빠졌으면 알린다.
    예전에는 그 줄의 칸이 하나라도 검증되면 넘어가서, 「0곳」 이라고 적힌 보고서에 합계 줄의 회색 칸이 남았다(9단계 재평가).
    빠진 칸은 그 열(줄)에 숫자가 셋 이상 있어 합이 있을 만한 곳만 센다. % 칸과 비율 이름의 열(줄)은 뺀다.
    no_sums 에 only 로 적은 열(줄)은 합계가 아니라고 본 칸이라 다시 묻지 않는다."""
    same = {(c.table, c.r, c.c) for c in checks if c.group != "합계" and c.table in {x[0] for x in c.terms}}      # 같은 표 안 연결로 메운 칸
    done_v = {(c.table, c.r, c.c) for c in checks if c.kind == "세로합"} | same
    done_h = {(c.table, c.r, c.c) for c in checks if c.kind == "가로합"} | same
    off: dict = {}                                       # AI 가 합계가 아니라고 한 줄 · 열(only 가 있으면 그 칸만)
    for x in (defs or {}).get("no_sums", []):
        off.setdefault((x["table"], x["axis"]), []).append(x)
    out = []
    for t in doc.tables():
        if t.kind:
            continue
        labels = _labels(t)

        def skipped(axis, i, j):
            for x in off.get((t.id, axis), []):
                if (find_row if axis == "v" else find_col)(t, *x["total"]) != (i if axis == "v" else j):
                    continue
                only = x.get("only")
                if not only:
                    return True
                other = t.header[j] if axis == "v" else labels[i]
                names = {"".join(str(o).split()) for o in only}
                if "".join(other.split()) in names or (axis == "v" and "".join(cut_prefix(other, col_prefix(t.header)).split()) in names):
                    return True
            return False

        dense_c = {j: sum(1 for i in range(len(t.rows)) if _isnum(t.nums[i][j]) and t.nums[i][j]) for j in range(1, len(t.header))}
        dense_r = {i: sum(1 for j in range(1, len(t.header)) if _isnum(t.nums[i][j]) and t.nums[i][j]) for i in range(len(t.rows))}
        for i, lab in enumerate(labels):
            if is_rate(lab) or not (total_kind(lab) or (_closing(labels, i) and not t.refs) or _fs_total(t, i, labels)):
                continue
            miss = [j for j in range(1, len(t.header)) if _isnum(t.nums[i][j]) and t.nums[i][j] and not t.rate(i, j) and not is_rate(t.header[j])
                    and dense_c[j] >= 3 and (t.id, i, j) not in done_v and not skipped("v", i, j)]
            if miss:
                name, nth = _ref(labels, i)
                out.append({"table": t.id, "what": "합계 줄", "row": name, "row_nth": nth, "cells": [t.header[j] for j in miss]})
        for j in range(1, len(t.header)):
            if is_rate(t.header[j]) or not (total_kind(t.header[j]) or _closing(t.header, j)):
                continue
            miss = [i for i in range(len(t.rows)) if _isnum(t.nums[i][j]) and t.nums[i][j] and not t.rate(i, j) and not is_rate(labels[i])
                    and dense_r[i] >= 3 and (t.id, i, j) not in done_h and not skipped("h", i, j)]
            if miss:
                out.append({"table": t.id, "what": "합계 열", "col": t.header[j], "col_nth": t.header[:j + 1].count(t.header[j]), "cells": [labels[i] for i in miss]})
    return out


def request(doc: Doc, checks: list[Check], defs: dict | None = None, with_evidence: bool = True, with_proposals: bool = False) -> dict:
    """엔진이 잇지 못한 과목과 그 과목이 가리키는 주석의 표. with_proposals 면 엔진의 연결 후보(proposals)와 앞서 적은 판정(mark)도 싣는다."""
    tied = set()
    for c in checks:
        if c.kind != "주석-재무제표":
            continue
        for tid, r, *_ in [(c.table, c.r)] + [(x[0], x[1]) for x in c.terms]:
            tied.add((tid, r))
    lines, notes = [], {}
    for name in STATEMENTS:
        t = doc.table(name)
        if t is None or not t.refs:
            continue
        a, b = period_col(t, "당기"), period_col(t, "전기")
        for r in range(len(t.rows)):
            cur, pri = (t.nums[r][a] if a else None), (t.nums[r][b] if b else None)
            if not t.refs[r] or (t.id, r) in tied or not ((_isnum(cur) and cur) or (_isnum(pri) and pri)):
                continue
            lab = _ref(_labels(t), r)
            near = []
            for no in t.refs[r]:
                p = next((p for p in doc.parts if p.key == f"주석{no}"), None)
                if p is None:
                    continue
                notes.setdefault(p.key, {"title": p.title, "paragraphs": [x[1][:300] for x in p.items if x[0] == "p"][:12],
                                         "tables": [_table_json(x[1]) for x in p.items if x[0] == "t"]})
                for q in (x[1] for x in p.items if x[0] == "t"):
                    for i in range(len(q.rows)):
                        for j in range(1, len(q.header)):
                            w = q.nums[i][j]
                            for period, v in (("당기", cur), ("전기", pri)):
                                if _isnum(w) and _isnum(v) and v and w and abs(abs(w) * q.unit - abs(v) * t.unit) <= 0.01 * abs(v) * t.unit:
                                    near.append({"table": q.id, "row": q.rows[i][0], "col": q.header[j], "value": w, "period": period,
                                                 "same": abs(abs(w) * q.unit - abs(v) * t.unit) < max(q.unit, t.unit)})
            lines.append({"table": t.id, "row": lab[0], "row_nth": lab[1], "당기": cur, "전기": pri, "unit": t.unit,
                          "notes": [f"주석{n}" for n in t.refs[r]], "near": near})
    return {"source": doc.source, "unlinked": lines, "unchecked_totals": unchecked_totals(doc, checks, defs),
            "amount_evidence": evidence(doc, checks) if with_evidence else [], "notes": notes,
            **({"proposals": proposal_list(doc, defs)} if with_proposals else {}),
            "how": "left 는 주석 칸, right 는 재무제표 과목(여러 칸이면 더한다). 표 · 행 · 열 이름은 이 파일에 적힌 글자 그대로. "
                   "회계상 같아야 하는 칸만 적는다. 일부만 담은 표(특수관계자 잔액, 외화 금액)는 과목 전체와 같지 않으므로 걸지 않는다."}


def proposal_list(doc: Doc, defs: dict | None = None) -> list[dict]:
    """엔진 후보와, 앞서 넣은 연결.json 에서 적은 판정(mark: O · X · 고침)."""
    from . import dsd_propose

    marks = (defs or {}).get("proposal_marks", {})
    out = []
    for x in dsd_propose.proposals(doc):
        m = marks.get(_psig(doc, x))
        out.append(dict(x, **({"mark": m} if m else {})))
    return out


def _ref_of(doc: Doc, d: dict) -> dict:
    tid = str(d.get("table", ""))
    base = tid[len(PAIR_ID):] if tid.startswith(PAIR_ID) else tid      # 다른 보고서의 표(「짝:재무상태표」)도 본표면 「당기」 「전기」 로 적는다
    out = {"table": d.get("table"), "row": d.get("row"), "row_nth": d.get("row_nth", 1), "col": d.get("col"), "col_nth": d.get("col_nth", 1)}
    t, col = doc.table(base) if tid == base else None, d.get("col")
    pre = col_prefix(t.header) if t is not None and isinstance(col, str) else ""
    if pre and not any(norm(h) == norm(col) for h in t.header):      # 읽기 자료에서 공통 앞부분을 뗀 열 이름으로 적은 칸은 원래 열 이름으로 바꿔 둔다(2026-10-22 P6)
        out["col"] = next((h for h in t.header if norm(cut_prefix(h, pre)) == norm(col)), col)
    if d.get("sign", 1) != 1:
        out["sign"] = d["sign"]
    fs = (doc.table(base) is not None or tid != base) and not base.startswith("주석") and not base.startswith("자본변동표")
    if not (fs and d.get("col") in ("당기", "전기")):
        out["exact"] = True                       # 재무제표의 「당기」 「전기」 말고는 열 이름을 글자 그대로 찾는다. 자본변동표는 열이 자본 항목이라 글자 그대로다
    return out


def _sig(ref: dict) -> str:
    return f"{'-' if ref.get('sign', 1) < 0 else ''}{ref['table']}|{ref['row']}#{ref['row_nth']}|{ref['col']}#{ref['col_nth']}"


def apply(doc: Doc, defs: dict, patch: dict, add: bool = False) -> tuple[dict, list[str]]:
    """AI 가 적은 연결을 검사해 defs 의 links 에 넣는다. (새 defs, 문제 목록). 문제가 있으면 defs 는 그대로다.

    patch 는 AI 연결의 전체 목록이다. 앞서 넣은 AI 연결은 지우고 이 목록으로 바꾼다(고치거나 뺀 연결이 남지 않게).
    add 면 앞서 넣은 것을 두고 더한다(다음 판에서 새로 생긴 표만 볼 때). 한 칸에 연결을 여럿 걸 수 있다(기초 = 전기 변동표의 기말, 기초 = 재무상태표 전기)."""
    pmarks = {}
    if patch.get("proposals", {}) is not None:      # 엔진 후보의 O · X · 고침을 links · skipped 로 풀고, 판정이 없는 후보는 기본으로 넣는다(2026-10-22).
        patch, problems, pmarks = expand_proposals(doc, patch, defs, strict=not add)      # "proposals": null 이면 후보를 쓰지 않는다
        if problems:
            return defs, problems
    problems, new, seen = [], [], set()
    for n, x in enumerate(patch.get("links", []), 1):
        if not x.get("left") or not x.get("right"):
            problems.append(f"{n}번째 연결: left 와 right 가 있어야 합니다")
            continue
        left, rights = _ref_of(doc, x["left"]), [_ref_of(doc, r) for r in x["right"]]
        for side, ref in [("left", left)] + [("right", r) for r in rights]:
            if str(ref["table"]).startswith(PAIR_ID):      # 다른 보고서의 칸은 foot --pair 때 푼다
                continue
            got = _resolve(doc, ref, None)
            if got is None:
                problems.append(f"{n}번째 연결 {side}: 「{ref['table']}」 표의 「{ref['row']}」 줄 · 「{ref['col']}」 열을 찾지 못했습니다")
            elif not _isnum(got[0].nums[got[1]][got[2]]):
                problems.append(f"{n}번째 연결 {side}: 「{ref['table']}」 「{ref['row']}」 · 「{ref['col']}」 칸에 숫자가 없습니다")
        if not str(x.get("basis", "")).strip():
            problems.append(f"{n}번째 연결: 근거(basis)를 한 줄 적어 주십시오")
        grade = str(x.get("grade") or "").strip()
        if grade and grade not in GRADES:
            problems.append(f"{n}번째 연결: grade 는 {' · '.join(GRADES)} 가운데 하나로 적어 주십시오")
        if grade == "조건부" and not str(x.get("when") or "").strip():
            problems.append(f"{n}번째 연결: 조건부 연결은 조건(when)을 한 줄 적어 주십시오")
        cmp = str(x.get("cmp") or "").strip()
        if cmp and cmp not in CMPS:
            problems.append(f"{n}번째 연결: cmp 는 le(왼쪽 ≤ 오른쪽) · ge(왼쪽 ≥ 오른쪽) 가운데 하나로 적어 주십시오")
        lid = "AI|" + _sig(left) + ("<=" if cmp == "le" else ">=" if cmp == "ge" else "=") + "+".join(_sig(r) for r in rights)
        if lid in seen:                             # 같은 연결을 두 번 적은 것은 한 번만 넣는다
            continue
        seen.add(lid)
        new.append({"id": lid, "left": left, "right": rights, "source": "AI", "basis": str(x.get("basis", "")).strip(), "confirmed": False,
                    **({"when": str(x["when"]).strip()} if str(x.get("when") or "").strip() else {}),
                    **({"usual": str(x["usual"]).strip()} if str(x.get("usual") or "").strip() else {}),
                    **({"grade": grade} if grade else {}),
                    **({"cmp": cmp} if cmp in CMPS else {}),
                    **({"via": str(x["via"])} if x.get("via") else {}),
                    **({"tol": float(x["tol"])} if x.get("tol") is not None else {})})
    for n, x in enumerate(patch.get("calcs", []), 1):      # 계산 검증: {left, expr: "a / b", vars: {a: 칸, b: 칸}, basis, tol?}
        vars_ = x.get("vars") or {}
        if not x.get("left") or not vars_ or not isinstance(vars_, dict):
            problems.append(f"calcs {n}번째: left 와 vars 가 있어야 합니다")
            continue
        names = list(vars_)
        units = [v.get("unit") for v in vars_.values() if isinstance(v, dict)] + ([x["left"].get("unit")] if isinstance(x["left"], dict) else [])
        if any(u is not None and u not in (1, 1000, 1000000, 0.01) for u in units):
            problems.append(f"calcs {n}번째: unit 은 1 · 1000 · 1000000 · 0.01 가운데 하나로 적어 주십시오")
            continue
        expr, why = _calc_expr(str(x.get("expr", "")), names)
        if expr is None:
            problems.append(f"calcs {n}번째: {why}")
            continue
        left, rights = _ref_of(doc, x["left"]), [_ref_of(doc, vars_[k]) for k in names]
        for side, ref in [("left", left)] + [(f"vars {k}", r) for k, r in zip(names, rights)]:
            if str(ref["table"]).startswith(PAIR_ID):
                continue
            got = _resolve(doc, ref, None)
            if got is None:
                problems.append(f"calcs {n}번째 {side}: 「{ref['table']}」 표의 「{ref['row']}」 줄 · 「{ref['col']}」 열을 찾지 못했습니다")
            elif not _isnum(got[0].nums[got[1]][got[2]]):
                problems.append(f"calcs {n}번째 {side}: 「{ref['table']}」 「{ref['row']}」 · 「{ref['col']}」 칸에 숫자가 없습니다")
        if not str(x.get("basis", "")).strip():
            problems.append(f"calcs {n}번째: 근거(basis)를 한 줄 적어 주십시오")
        for i, (k, ref) in enumerate(zip(names, rights)):      # 칸의 단위를 적었으면(표 단위와 다른 주식수 · 주당 금액) 그 배수를 식에 넣는다
            u = (vars_[k] or {}).get("unit") if isinstance(vars_[k], dict) else None
            got = _resolve(doc, ref, None) if u else None
            if got is not None and u != got[0].unit_at(got[1], got[2]):
                expr = expr.replace("{" + str(i) + "}", "({" + str(i) + "}*" + _dec(u / got[0].unit_at(got[1], got[2])) + ")")
        lu = x["left"].get("unit") if isinstance(x["left"], dict) else None
        got = _resolve(doc, left, None) if lu else None
        if got is not None and lu != got[0].unit_at(got[1], got[2]):
            expr = "(" + expr + ")*" + _dec(got[0].unit_at(got[1], got[2]) / lu)
        lid = "AI계산|" + _sig(left) + "=" + expr.format(*[_sig(r) for r in rights])
        if lid in seen:
            continue
        seen.add(lid)
        new.append({"id": lid, "left": left, "right": rights, "expr": expr, "source": "AI", "basis": str(x.get("basis", "")).strip(), "confirmed": False,
                    **({"tol": float(x["tol"])} if x.get("tol") is not None else {}),
                    **({"grade": str(x["grade"]).strip()} if str(x.get("grade") or "").strip() in GRADES else {}),
                    **({"when": str(x["when"]).strip()} if str(x.get("when") or "").strip() else {})})
    if problems:
        return defs, problems
    sums, offs = _sums_of(doc, patch, problems)
    units = []
    for n, x in enumerate(patch.get("units", []), 1):      # 단위를 바로잡을 표: {table, unit: 1 | 1000 | 1000000, why}
        if doc.table(x.get("table", "")) is None:
            problems.append(f"units {n}번째: 「{x.get('table')}」 표가 없습니다")
        elif x.get("unit") not in (1, 1000, 1000000):
            problems.append(f"units {n}번째: unit 은 1(원) · 1000(천원) · 1000000(백만원) 가운데 하나로 적어 주십시오")
        elif not str(x.get("why", "")).strip():
            problems.append(f"units {n}번째: 이유(why)를 한 줄 적어 주십시오")
        else:
            units.append({"table": x["table"], "unit": x["unit"], "why": str(x["why"]).strip()})
    if problems:
        return defs, problems
    out = dict(defs)
    keep = [x for x in defs.get("links", []) if x.get("source") != "AI" or (add and x["id"] not in seen)]
    out["links"] = keep + new
    key = lambda x: (x["table"], x["axis"], tuple(x["total"]))      # noqa: E731
    for name, got in (("sums", sums), ("no_sums", offs)):
        have = {key(x) for x in got}
        out[name] = ([x for x in defs.get(name, []) if key(x) not in have] if add else []) + got
    out["units"] = ([x for x in defs.get("units", []) if x["table"] not in {u["table"] for u in units}] if add else []) + units
    prior = []
    for n, x in enumerate(patch.get("prior", []), 1):       # 전기 대사 차이의 판정: {id, verdict: 불일치 | 설명됨 | 걸지 않음, why}
        if not str(x.get("id", "")).startswith("전기|") or x.get("verdict") not in PRIOR_VERDICTS or not str(x.get("why", "")).strip():
            problems.append(f"prior {n}번째: id(전기|…), verdict({' · '.join(PRIOR_VERDICTS)}), why 를 적어 주십시오")
        else:
            prior.append({"id": x["id"], "verdict": x["verdict"], "why": str(x["why"]).strip()})
    if problems:
        return defs, problems
    out["prior"] = ([x for x in defs.get("prior", []) if x["id"] not in {p["id"] for p in prior}] if add else []) + prior
    found = []
    for n, x in enumerate(patch.get("findings", []), 1):       # 차이의 판정: {id(검증 id), verdict, why}. 엑셀 「볼 것」 시트의 판정 열에 나온다
        if not str(x.get("id", "")).strip() or x.get("verdict") not in VERDICTS or not str(x.get("why", "")).strip():
            problems.append(f"findings {n}번째: id(검증 id), verdict({' · '.join(VERDICTS)}), why 를 적어 주십시오")
            continue
        rec = {"id": str(x["id"]), "verdict": x["verdict"], "why": str(x["why"]).strip(), **({"cause": str(x["cause"]).strip()} if str(x.get("cause") or "").strip() else {})}
        if "usual" in x:                              # 늘 나는 차이 유형. 빈 값이면 연결에 붙은 유형을 뗀다(독립 검증 대상으로 돌린다, 2026-10-22)
            rec["usual"] = str(x["usual"] or "").strip()
        if x.get("fix") is not None:                  # 고칠 칸 · 맞는 숫자 · 근거 칸(11단계). 근거 값은 foot 이 작년 보고서 · 정산표를 읽은 뒤 계산한다
            fx = x["fix"]
            if not isinstance(fx, dict) or str(fx.get("table", "")).startswith((PAIR_ID, "작년:", "조서:")) or _resolve(doc, _ref_of(doc, fx), None) is None:
                problems.append(f"findings {n}번째: fix 는 이 보고서의 칸 하나(table · row · col)로 적어 주십시오")
                continue
            if not isinstance(x.get("correct"), (int, float)) or isinstance(x.get("correct"), bool):
                problems.append(f"findings {n}번째: fix 를 적으면 맞는 숫자(correct)를 그 칸의 표시 단위로 적어 주십시오")
                continue
            ev = x.get("evidence") or []
            if not isinstance(ev, list) or any(not isinstance(e, dict) or not e.get("table") or e.get("row") is None for e in ev):
                problems.append(f"findings {n}번째: evidence 는 칸(table · row · col)의 목록으로 적어 주십시오")
                continue
            rec.update({"fix": fx, "correct": x["correct"], "evidence": ev})
        found.append(rec)
    if problems:
        return defs, problems
    out["findings"] = ([x for x in defs.get("findings", []) if x["id"] not in {f["id"] for f in found}] if add else []) + found
    skipped = [{"what": str(x["what"]).strip(), "why": str(x.get("why", "")).strip()} for x in patch.get("skipped", []) if isinstance(x, dict) and str(x.get("what", "")).strip()]
    have = {x["what"] for x in skipped}       # 걸지 않은 연결과 이유: 엑셀 「검증 범위」 시트에 그대로 나온다
    out["skipped"] = ([x for x in defs.get("skipped", []) if x["what"] not in have] if add else []) + skipped
    wps = []
    for n, x in enumerate(patch.get("workpapers", []), 1):      # 조서와 맞출 숫자: {table, rows?: [줄 이름], what, wp, why}
        t = doc.table(str(x.get("table", "")))
        if t is None:
            problems.append(f"workpapers {n}번째: 「{x.get('table')}」 표가 없습니다")
            continue
        rows = [r if isinstance(r, dict) else str(r) for r in (x.get("rows") or [])]      # 줄 이름, 또는 같은 이름이 여럿이면 {"row": 이름, "row_nth": 순번}
        lost = [str(r) for r in rows if (find_row(t, r["row"], int(r.get("row_nth", 1))) if isinstance(r, dict) else find_row(t, r)) is None]
        if lost:
            problems.append(f"workpapers {n}번째: 「{t.id}」 에서 줄 {', '.join('「' + r + '」' for r in lost)} 을 찾지 못했습니다")
            continue
        if not str(x.get("what", "")).strip() or not str(x.get("why", "")).strip():
            problems.append(f"workpapers {n}번째: what(무엇과 맞추는지)과 why(보고서 안에서 맞춰 볼 곳이 없는 까닭)를 적어 주십시오")
            continue
        wps.append({"table": t.id, **({"rows": rows} if rows else {}), "what": str(x["what"]).strip(), "wp": str(x.get("wp", "")).strip(), "why": str(x["why"]).strip()})
    pairs = []
    for n, x in enumerate(patch.get("prior_pairs", []), 1):      # 전기 대사에서 이름이 바뀐 줄의 짝: {table, row, prior_row, why}. 작년 줄은 foot --prior 때 푼다
        t = doc.table(str(x.get("table", "")))
        if t is None or find_row(t, str(x.get("row", "")), int(x.get("row_nth", 1))) is None:
            problems.append(f"prior_pairs {n}번째: 「{x.get('table')}」 표에서 줄 「{x.get('row')}」 을 찾지 못했습니다")
        elif not str(x.get("prior_row", "")).strip() or not str(x.get("why", "")).strip():
            problems.append(f"prior_pairs {n}번째: prior_row(작년 보고서의 줄 이름)와 why 를 적어 주십시오")
        else:
            pairs.append({k: x[k] for k in ("table", "row", "row_nth", "prior_row", "prior_row_nth", "why") if k in x})
    if problems:
        return defs, problems
    out["prior_pairs"] = ([x for x in defs.get("prior_pairs", []) if (x["table"], x["row"]) not in {(p["table"], p["row"]) for p in pairs}] if add else []) + pairs
    rkey = lambda x: (x["table"], tuple(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in x.get("rows", [])))      # noqa: E731
    have = {rkey(x) for x in wps}
    out["workpapers"] = ([x for x in defs.get("workpapers", []) if rkey(x) not in have] if add else []) + wps
    out["proposal_marks"] = ({**defs.get("proposal_marks", {})} if add else {}) | pmarks
    return out, []


def carry(src: Doc, dst: Doc, patch: dict) -> tuple[dict, list[str]]:
    """src 판에서 적은 AI 연결(patch)을 dst 판의 이름으로 옮긴다. (옮긴 patch, 옮기지 못한 것 목록).

    회사가 수정본을 보내면 주석이 끼어들어 번호가 밀리고(주석5 → 주석6) 줄 이름이 바뀐다. 두 판의 표 · 줄 · 열을 짝지어
    (dsd_compare.match) 연결이 가리키는 칸을 dst 의 표 번호와 이름으로 다시 적는다. 짝이 없는 칸을 가리키는 연결은 빼고 알린다."""
    from . import dsd_compare

    m = dsd_compare.match(dst, src, fuzzy=True)
    back = {old: (new, {j: i for i, j in rows.items()}, {j: i for i, j in cols.items()}) for new, (old, rows, cols) in m.tables.items()}
    named = {old: v[0] for old, v in back.items()}   # 이름으로 짝지은 표(숫자 짝으로 바뀌지 않은 것)
    for tid, (nid, rows, cols) in list(back.items()):  # 기수 · 연도가 적힌 열은 같은 이름이 아니라 같은 자리(당기는 당기)로 짝짓는다
        back[tid] = (nid, rows, _period_cols(src.table(tid), dst.table(nid), cols))
    num: dict = {}                                  # 옛 표 → [(새 표, 옛 줄 → 새 줄, 옛 열 → 새 열)]. 옛 표 하나가 새 표 여럿(당기 표 · 전기 표)으로 나뉠 수 있다
    sure = {}
    for new_id, (old_id, rows, cols, score) in dsd_compare.match_numbers(dst, src).items():
        num.setdefault(old_id, []).append((new_id, {j: i for i, j in rows.items()}, {j: i for i, j in cols.items()}))
        sure[(old_id, new_id)] = score
    def term(doc: Doc):
        from .dsd_links import term_of
        for name in ("재무상태표", "손익계산서"):
            t = doc.table(name)
            j = period_col(t, "당기") if t is not None else None
            if j is not None and term_of(t.header[j]) is not None:
                return term_of(t.header[j])
        return None

    # 같은 기간을 다른 꼴로 낸 판(감사보고서 원문 ↔ 사업보고서 본문)은 숫자가 같다. 재무제표의 당기 기수가 같으면 같은 기간이다.
    # 기수를 못 읽으면 새 판 표의 절반 넘게가 숫자 9할 이상 같을 때 같은 기간으로 본다. 해를 건너 옮길 때(올해 반기 → 작년 반기)는
    # 올해의 전기 표와 작년의 당기 표가 숫자가 같아 숫자로는 가를 수 없다
    big = [t for t in dst.tables() if sum(1 for r in t.nums for v in r[1:] if _isnum(v) and v) >= 5]
    ta, tb = term(src), term(dst)
    same_period = (ta == tb) if ta is not None and tb is not None else bool(big) and sum(1 for (o, n), sc in sure.items() if sc >= 0.9) >= 0.5 * len(big)
    taken = {}
    for tid, cands in num.items():                  # 같은 표면 이름 짝에 없는 줄 · 열을 숫자 짝으로 채운다
        for nid, rows, cols in cands:
            if tid in back and back[tid][0] == nid:
                back[tid] = (nid, {**rows, **back[tid][1]}, {**cols, **back[tid][2]})
            elif tid not in back or (same_period and sure[(tid, nid)] >= 0.9 and tid not in taken):
                back[tid] = (nid, rows, cols)       # 숫자가 9할 넘게 같으면 이름 짝보다 앞선다(이름 짝이 표 하나씩 밀린 판, 한 상장사 사업보고서 주석 4)
                taken[tid] = nid
                named.pop(tid, None)
    lost: list[str] = []

    index: dict = {}                                # 같은 기간 판에서 칸 하나씩 찾을 때 쓰는 「절댓값 → 새 판의 칸들」
    for q in dst.tables():
        for i, row in enumerate(q.nums):
            for j, w in enumerate(row):
                if j and _isnum(w) and w and not q.rate(i, j):
                    index.setdefault(abs(w), []).append((q.id, i, j))

    def by_cell(tid: str, r: int, c: int):
        """칸 하나 찾기: 새 판에서 숫자가 같은 칸 가운데 줄 이름과 주석 제목이 가장 비슷한 칸. 비슷한 정도가 같은 칸이 둘이면 고르지 않는다.
        사업보고서는 감사보고서의 표를 다르게 나누고 합쳐 표 단위 짝이 안 되는 칸이 많다(한 상장사 2025 연결 주석 27 조정 항목)."""
        t = src.table(tid)
        v = t.nums[r][c]
        if not _isnum(v) or not v:
            return None
        from difflib import SequenceMatcher

        from .dsd_compare import _name
        lab, title = _name(_labels(t)[r]), _name(src.part_of(tid).title)
        sc = []
        for nid, i, j in index.get(abs(v), []):
            q = dst.table(nid)
            nl = _name(_labels(q)[i])
            row = max(SequenceMatcher(None, lab, nl).ratio(), SequenceMatcher(None, lab, nl[-len(lab):] if lab else nl).ratio())
            sc.append((0.6 * row + 0.4 * SequenceMatcher(None, title, _name(dst.part_of(nid).title)).ratio(), row, nid, i, j))
        sc.sort(reverse=True)
        if not sc or sc[0][1] < 0.5 or (len(sc) > 1 and sc[1][0] >= sc[0][0] - 0.01):
            return None
        return sc[0][2:]

    def where(tid: str, r: int, c: int):
        """옛 칸 (표, 줄, 열) 의 새 칸. 이름 짝을 먼저 쓰고, 안 되면 숫자 짝(감사보고서 원문 ↔ 사업보고서 본문처럼 이름이 다른 판)을 쓴다.
        숫자로 짝지은 칸은 옛 칸과 새 칸의 숫자가 같을 때만 쓴다(줄과 열을 따로 짝지어 엇갈린 칸을 가리키지 않게). 같은 기간 판이면 칸 하나씩 찾기까지 한다."""
        v = src.table(tid).nums[r][c]
        for k, (nid, rows, cols) in enumerate(([back[tid]] if tid in back else []) + num.get(tid, [])):
            if r in rows and c in cols:
                w = dst.table(nid).nums[rows[r]][cols[c]]
                by_name = k == 0 and tid in named and named[tid] == nid
                if by_name or (_isnum(v) and _isnum(w) and abs(v) == abs(w)):
                    return nid, rows[r], cols[c]
        return by_cell(tid, r, c) if same_period else None

    def cell(d: dict) -> dict | None:
        got = _resolve(src, _ref_of(src, d), None)
        if got is None:
            return None
        t, r, c = got
        hit = where(t.id, r, c)
        if hit is None:
            return None
        nid, nr, nc = hit
        rows, cols = {r: nr}, {c: nc}
        q = dst.table(nid)
        out = dict(d, table=nid)
        out["row"], out["row_nth"] = _ref(_labels(q), rows[r])
        fs = not nid.startswith("주석") and not nid.startswith("자본변동표")      # 「당기」 「전기」 는 재무제표 본표에서만 기간 열이다(_ref_of 와 같다)
        if fs and d.get("col") in ("당기", "전기") and period_col(q, d["col"]) is not None:
            pass                                    # 본표의 「당기」 「전기」 는 자리로 적은 것이라 그대로 둔다(해를 건너도 당기는 당기)
        elif not fs or d.get("col") not in ("당기", "전기") or period_col(q, d["col"]) != cols[c]:
            out["col"], out["col_nth"] = _ref(q.header, cols[c])
        return out

    out = {k: v for k, v in patch.items() if k not in ("links", "sums", "no_sums", "units", "calcs", "workpapers")}
    def gap(doc: Doc, x: dict):
        got = [_resolve(doc, _ref_of(doc, d), None) for d in [x["left"]] + list(x["right"])]
        if any(g is None for g in got) or not all(_isnum(g[0].nums[g[1]][g[2]]) for g in got):
            return None
        val = [g[0].nums[g[1]][g[2]] * g[0].unit_at(g[1], g[2]) for g in got]
        unit = max(g[0].unit_at(g[1], g[2]) for g in got)
        return (val[0] - sum(d.get("sign", 1) * v for d, v in zip(x["right"], val[1:]))) / unit

    out["links"] = []
    for x in patch.get("links", []):
        left, rights = cell(x["left"]), [cell(r) for r in x["right"]]
        if left is None or any(r is None for r in rights):
            lost.append(f"연결: {x['left'].get('table')} {x['left'].get('row')} · {x['left'].get('col')} ({x.get('basis', '')[:40]})")
            continue
        y = dict(x, left=left, right=rights)
        dead = next((d for d in [left] + rights if not str(d.get("table", "")).startswith(PAIR_ID)
                     and ((g := _resolve(dst, _ref_of(dst, d), None)) is None or not _isnum(g[0].nums[g[1]][g[2]]))), None)
        if dead is not None:                          # 새 판에서 그 칸이 비었다(작년에 없던 사채 종류 같은 것)
            lost.append(f"연결(새 판 칸에 숫자가 없음): {dead.get('table')} {dead.get('row')} · {dead.get('col')} ({x.get('basis', '')[:40]})")
            continue
        if same_period and not x.get("expr"):
            a, b = gap(src, x), gap(dst, y)
            if a is not None and b is not None and abs(a) <= 3 and abs(b) > 3:
                lost.append(f"연결(옮긴 칸의 금액이 달라 뺌): {x['left'].get('table')} {x['left'].get('row')} · {x['left'].get('col')} ({x.get('basis', '')[:40]})")
                continue
        out["links"].append(y)
    out["calcs"] = []
    for x in patch.get("calcs", []):
        left, vars_ = cell(x["left"]), {k: cell(v) for k, v in (x.get("vars") or {}).items()}
        if left is None or any(v is None for v in vars_.values()):
            lost.append(f"계산: {x['left'].get('table')} {x['left'].get('row')} · {x['left'].get('col')} ({x.get('basis', '')[:40]})")
            continue
        out["calcs"].append(dict(x, left=left, vars=vars_))
    out["workpapers"] = []
    for x in patch.get("workpapers", []):
        t = src.table(str(x.get("table", "")))
        if t is None or t.id not in back:
            lost.append(f"조서 대사: {x.get('table')} {x.get('what', '')[:30]}")
            continue
        nid, rows, _ = back[t.id]
        q = dst.table(nid)
        names = []
        for r in x.get("rows") or []:
            i = find_row(t, r)
            names.append(_ref(_labels(q), rows[i])[0] if i is not None and i in rows else None)
        if any(n is None for n in names):
            lost.append(f"조서 대사: {x.get('table')} {x.get('what', '')[:30]}")
            continue
        out["workpapers"].append(dict(x, table=nid, **({"rows": names} if names else {})))
    def holds(doc: Doc, x: dict):
        """합계 구조 하나가 그 판에서 맞는가. 구조를 풀지 못하거나 걸린 칸이 없으면 None."""
        from .dsd_links import _checks_from_structure, evaluate

        got, _ = _sums_of(doc, {"sums": [x]}, [])
        if not got:
            return None
        g = got[0]
        checks = _checks_from_structure(doc.table(g["table"]), {"vsum" if g["axis"] == "v" else "hsum": [g]}, [])
        if not checks:
            return None
        evaluate(doc, checks)
        return all(c.ok or c.minor for c in checks)

    for kind in ("sums", "no_sums"):
        out[kind] = []
        for x in patch.get(kind, []):
            t = src.table(x.get("table", ""))
            tk = "total_col" if "total_col" in x else "total"
            cands = ([back[t.id]] if t is not None and t.id in back else []) + [c for c in (num.get(t.id, []) if t is not None else []) if t.id not in back or c[0] != back[t.id][0]]
            made = []
            for nid, rows, cols in cands:             # 사업보고서가 표를 당기 · 전기로 나눴으면 나뉜 표마다 구조를 옮긴다
                q = dst.table(nid)
                axis = "h" if "total_col" in x else "v"
                find, mp, names = (find_col, cols, q.header) if axis == "h" else (find_row, rows, _labels(q))
                other_find, other_mp, other_names = (find_row, rows, _labels(q)) if axis == "h" else (find_col, cols, q.header)

                def name(n, nth, find=find, mp=mp, names=names, t=t):
                    if n in ("당기", "전기") and find is find_col:
                        return [n, nth]
                    i = find(t, n, nth)
                    return _ref(names, mp[i]) if i is not None and i in mp else None

                y = dict(x, table=nid)
                total = name(str(x.get(tk, "")), int(x.get("total_nth", 1)))
                ok = total is not None
                if ok:
                    y[tk], y["total_nth"] = total
                ik, key = ("cols", "col") if axis == "h" else ("rows", "row")
                if ok and ik in x:
                    items = []
                    for it in x[ik]:
                        n, nth, sign = _item(it, axis)
                        got = name(n, nth)
                        if got is None:
                            ok = False
                            break
                        items.append({key: got[0], "nth": got[1], **({"sign": -1} if sign < 0 else {})})
                    y[ik] = items
                for k in ("from", "to"):
                    if ok and k in x:
                        n, nth, _ = _item(x[k], axis)
                        got = name(n, nth)
                        ok = got is not None
                        if ok:
                            y[k] = {key: got[0], "nth": got[1]}
                for k in ("skip", "only"):                # 새 판에 없는 열(줄) 이름은 뺀다. only 가 다 빠지면 이 표에는 걸 칸이 없다
                    if ok and x.get(k):
                        y[k] = [g[0] for g in (name(str(n), 1, other_find, other_mp, other_names) for n in x[k]) if g is not None]
                        if k == "only" and not y[k]:
                            ok = False
                if ok and kind == "sums" and same_period and holds(src, x) and holds(dst, y) is False:
                    lost.append(f"{kind}(옮긴 칸의 금액이 안 맞아 뺌): {x.get('table')} {x.get(tk)} → {nid}")
                    continue
                if ok:
                    made.append(y)
            if made:
                out[kind] += made
            else:
                lost.append(f"{kind}: {x.get('table')} {x.get(tk)}")
    out["units"] = [dict(x, table=back[x["table"]][0]) for x in patch.get("units", []) if x.get("table") in back]
    return out, lost


_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def _col_period(h: str) -> int | None:
    """열 머리줄의 기수(「제 57 기 반기」 → 57)나 연도(「2025.06.30」 → 2025). 없으면 None."""
    from .dsd_links import term_of

    n = term_of(h)
    if n is not None:
        return n
    m = _YEAR.search(str(h))
    return int(m.group(0)) if m else None


def _period_cols(t: Table, q: Table, cols: dict) -> dict:
    """옛 열 → 새 열 짝을 기수 · 연도로 고친다. 해를 건너 옮기면(올해 반기에서 작년 반기로) 올해의 전기 열 「제 56 기 반기」 와
    작년의 당기 열 「제 56 기 반기」 가 글자가 같아 이름 짝이 당기 · 전기를 바꿔 잇는다. 두 표 모두 열마다 기수 · 연도가 있으면
    가장 큰 값끼리의 차이만큼 옮겨 짝짓는다(같은 판끼리면 차이가 0 이라 그대로다)."""
    a = {j: _col_period(h) for j, h in enumerate(t.header) if j}
    b = {j: _col_period(h) for j, h in enumerate(q.header) if j}
    if not a or not b or None in a.values() or None in b.values():
        return cols
    delta = max(b.values()) - max(a.values())
    if delta == 0:
        return cols
    out = dict(cols)
    for j, n in a.items():
        same = [k for k, m in b.items() if m == n + delta and (_name_tail(t.header[j]) == _name_tail(q.header[k]))]
        if len(same) == 1:
            out[j] = same[0]
    return out


def _name_tail(h: str) -> str:
    """기수 · 연도를 뗀 열 이름(「제 57 기 반기 3개월」 → 「반기3개월」)."""
    return re.sub(r"\s+", "", re.sub(r"제\s*\d+\s*\(?\s*[당전]?\s*\)?\s*기|(19|20)\d{2}[.년]?\s*\d{0,2}[.월]?\s*\d{0,2}일?", "", str(h)))


def _item(x, axis: str) -> tuple[str, int, int]:
    if isinstance(x, dict):
        nth = x.get("nth", x.get("row_nth" if axis == "v" else "col_nth", 1))      # links 와 같은 이름(row_nth · col_nth)으로 적어도 된다
        return str(x.get("row" if axis == "v" else "col", x.get("name", ""))), int(nth), (-1 if x.get("sign", 1) < 0 else 1)
    return str(x), 1, 1


def _sums_of(doc: Doc, patch: dict, problems: list[str]) -> tuple[list[dict], list[dict]]:
    """AI 가 적은 합계 구조(sums)와 합계가 아닌 줄 · 열(no_sums)을 검사해 연결 정의의 꼴로 바꾼다.

    세로: {table, total, rows:[이름 | {row, nth, sign}], basis}  또는 {table, total, from, to, basis}
    가로: {table, total_col, cols:[이름 | {col, nth, sign}], basis}  또는 {table, total_col, from, to, basis}
    범위(from · to)에 "sign": -1 을 적으면 범위 전부를 뺀다.
    total_nth 로 같은 이름의 몇 번째인지, skip 으로 이 구조를 걸지 않을 열(세로) · 줄(가로) 이름을 적는다.
    keep 을 적으면 엔진이 찾은 구조를 두고 이 식을 하나 더 건다(한 합계 칸을 두 식으로 검증).
    only 를 적으면 거기 적힌 열(줄)에만 건다. 이름에 % 나 「율」 이 있어 엔진이 비율로 보고 빼는 금액 열을 걸 때도 only 로 적는다."""
    sums, offs = [], []
    for kind, src in (("sums", patch.get("sums", [])), ("no_sums", patch.get("no_sums", []))):
        for n, x in enumerate(src, 1):
            who = f"{kind} {n}번째"
            t = doc.table(x.get("table", ""))
            if t is None:
                problems.append(f"{who}: 「{x.get('table')}」 표가 없습니다")
                continue
            axis = "h" if "total_col" in x else "v"
            find, what = (find_col, "열") if axis == "h" else (find_row, "줄")
            total = [str(x.get("total_col" if axis == "h" else "total", "")), int(x.get("total_nth", 1))]
            ti = find(t, *total)
            if ti is None:
                problems.append(f"{who}: 「{t.id}」 표에서 합계 {what} 「{total[0]}」 을 찾지 못했습니다")
                continue
            note = str(x.get("basis" if kind == "sums" else "why", "")).strip()
            if not note:
                problems.append(f"{who}: {'근거(basis)' if kind == 'sums' else '이유(why)'}를 한 줄 적어 주십시오")
            if kind == "no_sums":
                offs.append({"table": t.id, "axis": axis, "total": total, "why": note, **({"only": [str(n) for n in x["only"]]} if x.get("only") else {})})
                continue
            d = {"table": t.id, "axis": axis, "total": total, "source": "AI", "basis": note}
            if x.get("keep"):
                d["keep"] = True
            for k in ("skip", "only"):
                if x.get(k):
                    names = t.header if axis == "v" else _labels(t)
                    if axis == "v":                           # 열 이름의 공통 앞부분을 떼고 적은 것도 받는다(읽기 자료의 꼴)
                        names = list(names) + [cut_prefix(h, col_prefix(t.header)) for h in t.header]
                    lost = [str(n) for n in x[k] if "".join(str(n).split()) not in {"".join(str(h).split()) for h in names}
                            and not (axis == "v" and n in ("당기", "전기") and period_col(t, n) is not None)]
                    if lost:
                        problems.append(f"{who}: 「{t.id}」 의 {k} 에 적은 {'열' if axis == 'v' else '줄'} {', '.join('「' + n + '」' for n in lost)} 이 표에 없습니다")
                    d[k] = [str(n) for n in x[k]]
            if "from" in x or "to" in x:
                a, b = _item(x.get("from", ""), axis), _item(x.get("to", ""), axis)
                ia, ib = find(t, a[0], a[1]), find(t, b[0], b[1])
                if ia is None or ib is None or ia > ib or ia <= ti <= ib:
                    problems.append(f"{who}: 「{t.id}」 「{total[0]}」 의 범위 「{a[0]}」~「{b[0]}」 을 찾지 못했거나 합계 {what}이 그 안에 있습니다")
                    continue
                d.update({"mode": "range", "from": [a[0], a[1]], "to": [b[0], b[1]]})
                if x.get("sign", 1) < 0:
                    d["sign"] = -1
            else:
                items = [_item(i, axis) for i in x.get("cols" if axis == "h" else "rows", [])]
                bad = [i[0] for i in items if find(t, i[0], i[1]) is None or find(t, i[0], i[1]) == ti]
                if not items or bad:
                    problems.append(f"{who}: 「{t.id}」 「{total[0]}」 의 항 {what} {', '.join('「' + b + '」' for b in bad) or '(없음)'} 을 찾지 못했습니다")
                    continue
                d.update({"mode": "rows", "rows": [[i[0], i[1]] for i in items], "signs": [i[2] for i in items]})
            sums.append(d)
    return sums, offs


def sum_review(doc: Doc, before: dict, checks: list[Check]) -> list[dict]:
    """AI 가 정한 합계 구조 가운데 안 맞는 것. 걸린 칸이 둘 이상인데 전부 안 맞으면 구조를 잘못 읽었을 가능성이 높다.
    엔진이 금액 근거로 찾았던 구조가 있으면 함께 보여 준다(표를 다시 읽을 참고다)."""
    found = {s["table"]: s for s in before.get("structures", [])}
    groups: dict[tuple, list] = {}
    for c in checks:
        if c.group == "합계" and c.source == "AI":
            t = doc.table(c.table)
            name = _labels(t)[c.r] if c.kind == "세로합" else t.header[c.c]
            groups.setdefault((c.table, c.kind, name, c.r if c.kind == "세로합" else c.c), []).append(c)
    out = []
    for (tid, kind, name, i), cs in groups.items():
        bad = [c for c in cs if failed(c)]
        if not bad:
            continue
        t = doc.table(tid)
        key, find = ("vsum", find_row) if kind == "세로합" else ("hsum", find_col)
        eng = next((struct_text(t, y, key) for y in (found.get(tid) or {}).get(key, []) if find(t, *y["total"]) == i), None)
        out.append({"table": tid, "kind": kind, "total": name, "checks": len(cs), "false": len(bad), "all": len(cs) >= 2 and len(bad) == len(cs),
                    "ai": cs[0].label, "engine": eng})
    return out


def review(doc: Doc, checks: list[Check]) -> list[dict]:
    """금액이 안 맞는 AI 연결과, 같은 표 묶음(그 주석) 안에서 맞는 금액을 가진 다른 칸들."""
    out = []
    for c in checks:
        if c.source != "AI" or c.group != "레퍼" or c.ok is not False:
            continue
        t = doc.table(c.table)
        part = doc.part_of(c.table)
        want = c.right
        same = []
        for q in (x[1] for x in part.items if x[0] == "t"):
            for i in range(len(q.rows)):
                for j in range(1, len(q.header)):
                    w = q.nums[i][j]
                    if _isnum(w) and (q.id, i, j) != (c.table, c.r, c.c) and abs(abs(w) - abs(want)) < 1e-6:
                        same.append({"table": q.id, "row": q.rows[i][0], "col": q.header[j]})
        out.append({"id": c.id, "minor": c.minor, "when": c.when, "left": f"{t.id} {_labels(t)[c.r]} · {t.header[c.c] or f'{c.c + 1}번째 열'}", "left_value": c.left, "right": c.label, "right_value": c.right,
                    "diff": c.left - c.right, "same_amount_cells": same[:8]})
    return out


def summary(req: dict) -> str:
    n = len(req["unlinked"])
    with_near = sum(1 for x in req["unlinked"] if x["near"])
    more = f" · 검증이 걸리지 않은 합계 줄 · 열 {len(req['unchecked_totals'])}곳" if req.get("unchecked_totals") else ""
    return f"엔진이 주석과 잇지 못한 과목 {n}개(그중 가리킨 주석에 1% 안쪽으로 가까운 금액이 있는 과목 {with_near}개){more}"



_NOTE_REF = re.compile(r"주\s*석\s*(\d{1,2})(?![\d.])")


_ITEM_MARK = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|\d+\.|\(\d+\)|[가-하]\.|[①-⑳])\s*")


def _plain_name(s: str) -> str:
    return re.sub(r"[\s,·ㆍ\-()「」\[\]:]", "", re.sub(r"\([^)]*\)|\[[^\]]*\]|\*\d*", "", str(s or "")))


def _name_variants(label: str) -> list[str]:
    """재무제표 과목 이름의 견주기용 변형. 번호 · 괄호 · 각주를 떼고, 유동 · 비유동을 뺀 이름과 「및」 으로 나눈 이름을 더한다."""
    core = _plain_name(_ITEM_MARK.sub("", str(label or "")))
    out = [core]
    out.append(re.sub(r"비?유동", "", core))
    out.append(re.sub(r"^(단기|장기)", "", core))     # 「단기차입금」 → 「차입금」(담보 제공 자산 주석은 「차입금」 으로만 적는다)
    out += [x for x in core.split("및") if len(x) >= 2]
    if core.startswith("기타") and len(core) > 4:
        out.append(core[2:])
    return [x for x in dict.fromkeys(out) if len(x) >= 2]


GENERIC_NOTES = ("범주", "공정가치", "위험", "외화", "특수관계", "현금흐름", "부가가치", "담보", "우발", "약정", "금융상품", "부문", "성격",
                 "회계정책", "추정", "보고기간후", "보고기간종료일후", "후속", "일반사항", "개요", "비용", "수익", "자본관리")


def _title_tokens(title: str) -> list[str]:
    t = _ITEM_MARK.sub("", re.sub(r"^\s*\d+\.\s*", "", str(title or "")))
    return [x for x in (_plain_name(w) for w in re.split(r"\s+|및|,|ㆍ|·", t)) if len(x) >= 2]


def misdirected_refs(doc: Doc) -> list[str]:
    """재무제표 과목이 가리킨 주석에 그 과목 이름이 한 번도 없는 곳(11단계). 주석 번호를 잘못 적은 꼴이다
    (한 상장사 2026 반기: 재무상태표 「전환사채(유동)」 이 사용권자산 주석 14 를 가리킴. 실제 회사 자료 최종판에서 「주석 11 참조」 를 12 로 고침).
    틀린 지적을 줄이려고 다섯 가지가 다 맞을 때만 알린다. 가리킨 주석의 제목 · 문단 · 줄 · 열 이름에 과목 이름(변형 포함)이 없다.
    그 주석의 제목과 과목 이름이 낱말 하나도 겹치지 않는다. 다른 주석의 제목에 과목 이름이 있다.
    가리킨 주석이 여러 과목을 함께 다루는 주석(범주별 금융상품, 공정가치, 위험관리, 외화, 특수관계자 …)이 아니다.
    가리킨 주석 제목의 낱말이 모두 재무상태표 과목이고 그 과목이 모두 반대쪽(자산 ↔ 부채)이다(국보디자인 2025 「유형자산 → 사용권자산과 리스부채」 는 사용권자산이 유형자산에 든 회사였다).
    자본 과목과 자본 주석, 담보를 적은 주석, 자산이 가리킨 차입금 · 사채 주석은 보지 않는다. 공개 원문 307건에서 기타포괄손익누계액이
    매도가능금융자산 · 지분법 주석을, 자산이 담보를 적은 차입금 주석을 가리킨 곳이 틀린 알림이었다(한 상장사 2025 주석5 는 「담보」 없이 「채권 최고액 … 설정」 으로 적었다).
    처음 꼴(이름이 없으면 알림)은 스터디 보고서에서 범주별 금융상품 · 외화 주석을 가리킨 과목을 잘못 짚었다."""
    notes = {}
    for p in doc.parts:
        if p.key.startswith("주석") and p.key[2:].isdigit():
            bits = [p.title]
            for x in p.items:
                if x[0] == "p":
                    bits.append(x[1])
                else:
                    t = x[1]
                    bits += [t.caption or ""] + [str(h) for h in t.header] + [str(r[0]) for r in t.rows] + list(_labels(t))
            notes[int(p.key[2:])] = (p.title, _plain_name(" ".join(bits)))
    out = []
    t = doc.table("재무상태표")
    if t is None or not t.refs:
        return out
    labels = _labels(t)
    side, sides = "자산", []
    for lab in labels:                                   # 자산총계 앞은 자산, 부채총계 앞은 부채, 그 뒤는 자본
        sides.append(side)
        p = _plain_name(lab)
        if "자산총계" in p:
            side = "부채"
        elif "부채총계" in p:
            side = "자본"
    line_side = {}
    for i, lab in enumerate(labels):
        for v in _name_variants(lab):
            line_side.setdefault(v, sides[i])
    for i, refs in enumerate(t.refs):
        vs = _name_variants(labels[i])
        if not vs:
            continue
        for n in refs:
            if n not in notes or any(v in notes[n][1] for v in vs):
                continue
            title = notes[n][0]
            if any(g in _plain_name(title) for g in GENERIC_NOTES) or sides[i] == "자본" or "담보" in notes[n][1]                     or (sides[i] == "자산" and re.search(r"차입|사채", _plain_name(title))):
                continue                                 # 자본 과목(기타포괄손익누계액 → 매도가능금융자산 · 지분법 주석), 담보를 적은 주석, 자산 → 차입금 · 사채 주석(담보 제공)은 둔다
            words = [re.sub(r"[\d.]+$", "", tk) for tk in _title_tokens(title)]      # 「기타비유동자산6-1.」 처럼 제목 뒤에 붙은 번호를 뗀다
            words = [tk[:-1] if tk[-1:] in ("과", "와") and tk[:-1] in line_side else tk for tk in words if tk]
            toks = [tk for tk in words if tk in line_side]
            other = [tk for tk in toks if line_side[tk] != sides[i]]
            titled = [str(k) for k, (tt, _) in notes.items() if k != n and any(v in _plain_name(tt) for v in vs)]
            if not other or not titled or any(line_side[tk] == sides[i] for tk in toks) or len(toks) < len(words) or any(line_side[tk] == "자본" for tk in other):
                continue                                 # 같은 쪽 과목이 든 주석, 재무상태표에 없는 이름이 든 주석(「사용권자산과 리스부채」, 사용권자산이 유형자산에 든 회사)은 둔다
            out.append(f"{t.id} 「{labels[i]}」({sides[i]}) → 주석 {n}({title[:20]}, {line_side[other[0]]} 과목 「{other[0]}」 주석)에 「{vs[0]}」 이 없다. "
                       f"제목에 있는 주석: {', '.join(titled[:3])}")
    return out


def consistency(doc: Doc) -> list[dict]:
    """원문 대조: 주석 번호 참조와 재무제표 머리줄이 맞는지. [{what, n, why}].

    - 재무제표 과목이 가리키는 주석 번호(주석 열, 「(주석 5)」)와 주석 문단의 「주석 N 참조」 가 보고서에 있는 주석인지.
    - 읽은 주석 번호에 빠진 번호가 있는지(제목을 못 읽어 앞 주석에 붙었을 수 있다).
    - 재무제표 넷의 당기 · 전기 기수가 같은지(「제 10(당) 기」 와 「제 9(전) 기」).
    9단계 재평가에서 「표를 통째로 못 읽으면 지금은 알 수 없다」 로 남은 항목이다."""
    from .dsd_links import term_of

    have = sorted(int(p.key[2:]) for p in doc.parts if p.key.startswith("주석") and p.key[2:].isdigit())
    out = []
    unread = [n for n in ("재무상태표", "손익계산서", "자본변동표", "현금흐름표") if doc.table(n) is None]
    if unread:                                            # 2026-10-20: 시나리오 B 의 현금흐름표 없음, 공개 원문 044 의 빈 재무상태표 삽입 자리를 알리지 않았다
        whole = len(unread) == 4
        out.append({"what": "읽지 못한 재무제표", "n": len(unread),
                    "why": " · ".join(unread) + ". 원문에 없거나 엔진이 표로 읽지 못했다. 원문과 견주고, 원문에 없으면 공시 누락이다"
                           + (". 사업 · 반기 · 분기보고서 본문이면 tools/dart_periodic_split.py 로 연결과 별도를 먼저 나눈다(접수번호나 DART PDF 만 있으면 python -m audit dsd fetch 가 받으며 나눈다)" if whole else "")})
    if have:
        gap = [n for n in range(have[0], have[-1] + 1) if n not in have]
        if gap:
            out.append({"what": "읽은 주석 번호에 빠진 번호", "n": len(gap), "why": ", ".join(map(str, gap)) + ". 제목을 못 읽어 앞 주석에 붙었을 수 있으니 원문과 견준다"})
    bad = []
    for name in STATEMENTS + ("자본변동표",):
        t = doc.table(name)
        if t is None or not t.refs:
            continue
        labels = _labels(t)
        for i, refs in enumerate(t.refs):
            for n in refs:
                if have and n not in have:
                    bad.append(f"{t.id} 「{labels[i]}」 → 주석 {n}")
    if bad:
        out.append({"what": "보고서에 없는 주석을 가리킨 과목", "n": len(bad), "why": "; ".join(bad[:20])})
    off = misdirected_refs(doc)
    if off:
        out.append({"what": "가리킨 주석에 과목 이름이 없음", "n": len(off), "why": "; ".join(off[:20])})
    words = []
    for p in doc.parts:
        for x in p.items:
            if x[0] != "p":
                continue
            for m in _NOTE_REF.finditer(x[1]):
                n = int(m.group(1))
                if have and n not in have and f"{p.key} → 주석 {n}" not in words:
                    words.append(f"{p.key} → 주석 {n}")
    if words:
        out.append({"what": "문단이 가리킨 주석이 보고서에 없음", "n": len(words), "why": "; ".join(words[:20])})
    terms, marks = {}, []
    for name in ("재무상태표", "손익계산서", "자본변동표", "현금흐름표"):
        t = doc.table(name)
        if t is None:
            continue
        a, b = period_col(t, "당기"), period_col(t, "전기")
        ta = term_of(t.header[a]) if a is not None else None
        tb = term_of(t.header[b]) if b is not None and b != a else None
        if ta is not None:
            terms[name] = (ta, tb)
        if a is not None and re.search(r"\(\s*전\s*\)", t.header[a]):          # 기수가 큰 당기 열에 「(전)」(DART 00242509 2025 손익계산서 「제43(전)기」)
            marks.append(f"{name} 당기 열 「{t.header[a]}」")
        if b is not None and b != a and re.search(r"\(\s*당\s*\)", t.header[b]):
            marks.append(f"{name} 전기 열 「{t.header[b]}」")
    if marks:
        out.append({"what": "재무제표 머리줄의 당 · 전 표시가 기수와 다름", "n": len(marks), "why": "; ".join(marks)})
    ends: dict = {}                                       # 기수마다 재무제표 머리 문단에 적힌 끝 날짜(「제 10 기 2025년 1월 1일부터 2025년 12월 31일까지」)
    for p in doc.parts:
        if p.key.startswith("주석"):
            continue
        for x in p.items:
            if x[0] != "p":
                continue
            for m in re.finditer(r"제\s*(\d+)\s*\(?\s*[당전]?\s*\)?\s*기[^제]*?((?:\d{4}\s*[년.]\s*\d{1,2}\s*[월.]\s*\d{1,2}\s*일?[^제\d]*)+)", x[1]):
                dates = re.findall(r"(\d{4})\s*[년.]\s*(\d{1,2})\s*[월.]\s*(\d{1,2})", m.group(2))
                if dates:                                 # 반기 · 분기 손익의 기간(제 57 기 반기 6.30)과 재무상태표의 기말(제 57 기말 12.31)은 따로 본다
                    span = "반기" if "반기" in m.group(0) else ("분기" if "분기" in m.group(0) else "")
                    ends.setdefault((int(m.group(1)), span), {}).setdefault(tuple(int(v) for v in dates[-1]), []).append(p.key)
    for (n, span), got in sorted(ends.items()):
        if len(got) > 1:
            out.append({"what": "같은 기수의 끝 날짜가 재무제표마다 다름", "n": len(got),
                        "why": f"제 {n} 기{(' ' + span) if span else ''}: " + "; ".join(f"{y}.{mo}.{d} ({', '.join(dict.fromkeys(ks))})" for (y, mo, d), ks in got.items())})
    cur = {v[0] for v in terms.values()}
    if len(cur) > 1:
        out.append({"what": "재무제표마다 당기 기수가 다름", "n": len(cur), "why": "; ".join(f"{k} 제 {v[0]} 기" for k, v in terms.items())})
    odd = [f"{k} 당기 제 {v[0]} 기 · 전기 제 {v[1]} 기" for k, v in terms.items() if v[1] is not None and v[1] != v[0] - 1]
    if odd:
        out.append({"what": "전기 기수가 당기보다 하나 작지 않음", "n": len(odd), "why": "; ".join(odd)})
    from . import dsd_kicpa                               # 감리지적 유형에서 공시가 빠졌을 수 있는 곳(12단계)

    return out + dsd_kicpa.alerts(doc)
