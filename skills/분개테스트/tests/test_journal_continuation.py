"""분개장이 첫 시트에서 행 한도로 끊기고 머리줄 없는 다음 시트로 이어지는 꼴(2026-11-23, 합성 자료).

더존 분개장 xls 는 첫 시트 65,492행에서 끊고 Sheet2 로 이어 쓴다. 엔진이 둘째 시트를 읽지 않고 파일을 「잘림」 으로 알리던 것을 고쳤다.
시험에서는 한 시트 한도를 20행으로 낮춰 xlsx 로 같은 꼴을 만든다(판독 규칙은 xls 와 같다).
"""
import sys
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))

from audit import reader  # noqa: E402
from audit.workpapers import common  # noqa: E402

LIMIT = 20
HEAD = [(None, None, None, None, "분   개   장", None, None, None),
        ("회사명 : 가상상사", None, None, None, None, None, "2026/01/01 ~ 2026/01/31", None),
        ("날짜", "번호", "차변금액", "계정과목", "계정과목", "대변금액", "작성일", "작성번호")]


def _voucher(day: int, no: int, amt: int, month: int = 1) -> list[tuple]:
    """영세율 수출 매출 전표 하나. 부가세예수금 줄은 금액 칸이 비어 있다."""
    d = f"2026/{month:02d}/{day:02d}"
    return [(d, no, amt, "[1080000] 외상매출금", None, None, d, no),
            (d, no, None, None, "[2550000] 부가세예수금", None, d, no),
            (d, no, None, None, "[4040002] 해외매출", amt, d, no)]


def _body(n: int) -> list[tuple]:
    out = []
    for k in range(n):
        out += _voucher(1 + (1 + k) % 28, 1 + k, 1000 * (1 + k))
    return out


def _xlsx(path: Path, sheets: dict) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(list(r))
    wb.save(path)
    return path


@pytest.fixture
def small_limit(monkeypatch):
    monkeypatch.setitem(reader.SHEET_ROW_LIMIT, ".xlsx", LIMIT)
    reader._JCACHE.clear()
    yield
    reader._JCACHE.clear()


def test_continuation_sheet_is_read_and_not_flagged(tmp_path, small_limit):
    body = _body(12)
    cut = LIMIT - len(HEAD)          # 6번 전표의 차변 · 부가세 줄까지 첫 시트, 매출 대변 줄부터 둘째 시트
    p = _xlsx(tmp_path / "2026-01 분개장.xlsx", {"Sheet1": HEAD + body[:cut], "Sheet2": body[cut:]})
    assert [t["sheet"] for t in reader.journal_tables(p)] == ["Sheet1", "Sheet2"]
    lines = reader.journal_rows(p)
    assert sum(x["dr"] for x in lines) == sum(x["cr"] for x in lines) == sum(r[2] or 0 for r in body)
    split = [x for x in lines if x["voucher"] == "6"]
    assert {x["sheet"] for x in split} == {"Sheet1", "Sheet2"}
    assert reader.row_limit_hit(p, reader.journal_sheet_rows(p)) is None
    stat = common.journal_file_stat(p, p.name, common.read_journal(p, p.name))
    checks = common.journal_file_checks([stat], date(2026, 1, 1), date(2026, 1, 31))
    assert not any("한도" in c or "차변 − 대변" in c for c in checks), checks


def test_full_last_sheet_is_still_flagged(tmp_path, small_limit):
    body = _body(12)
    p = _xlsx(tmp_path / "2026-01 분개장.xlsx", {"Sheet1": HEAD + body[:LIMIT - len(HEAD)]})
    assert reader.row_limit_hit(p, reader.journal_sheet_rows(p)) == LIMIT
    stat = common.journal_file_stat(p, p.name, common.read_journal(p, p.name))
    assert any("한도" in c for c in common.journal_file_checks([stat], date(2026, 1, 1), date(2026, 1, 31)))


def test_other_sheets_are_not_read_as_continuation(tmp_path, small_limit):
    body = _body(12)
    short = _xlsx(tmp_path / "a.xlsx", {"Sheet1": HEAD + body[:9], "Sheet2": body[9:]})
    assert [t["sheet"] for t in reader.journal_tables(short)] == ["Sheet1"]
    memo = _xlsx(tmp_path / "b.xlsx", {"Sheet1": HEAD + body[:LIMIT - len(HEAD)],
                                       "메모": [("출력 조건", "전체"), ("출력자", "관리자")]})
    assert [t["sheet"] for t in reader.journal_tables(memo)] == ["Sheet1"]
    assert reader.row_limit_hit(memo, reader.journal_sheet_rows(memo)) == LIMIT


# 2026-11-23 밤 리뷰에서 찾은 꼴
TOTAL = ("합 계", None, 0, None, None, 0, None, None)
FIRST = LIMIT - len(HEAD)


def _balanced(p: Path, body: list[tuple]) -> bool:
    lines = reader.journal_rows(p)
    return sum(x["dr"] for x in lines) == sum(x["cr"] for x in lines) == sum(r[2] or 0 for r in body)


def test_xlsx_converted_from_xls_reads_second_sheet(tmp_path, monkeypatch):
    """xls 를 xlsx 로 바꾼 파일은 첫 시트가 옛 엑셀 한도 바로 아래에서 끝난다. 둘째 시트를 이어 읽는다."""
    monkeypatch.setitem(reader.SHEET_ROW_LIMIT, ".xls", LIMIT)
    reader._JCACHE.clear()
    body = _body(12)
    p = _xlsx(tmp_path / "2026-01 분개장.xlsx", {"Sheet1": HEAD + body[:FIRST], "Sheet2": body[FIRST:] + [TOTAL]})
    assert [t["sheet"] for t in reader.journal_tables(p)] == ["Sheet1", "Sheet2"]
    assert _balanced(p, body)
    reader._JCACHE.clear()


def test_repeated_header_and_total_only_sheets(tmp_path, small_limit):
    """다음 시트가 머리줄을 되풀이하거나, 합계 줄만 넘어와도 이어 읽고 잘림으로 보지 않는다."""
    body = _body(10)
    p = _xlsx(tmp_path / "a.xlsx", {"Sheet1": HEAD + body[:FIRST], "Sheet2": HEAD + body[FIRST:]})
    assert reader.journal_tables(p)[0].get("continued") and _balanced(p, body)
    assert reader.row_limit_hit(p, reader.journal_sheet_rows(p)) is None
    six = _body(6)
    q = _xlsx(tmp_path / "b.xlsx", {"Sheet1": [HEAD[0], HEAD[2]] + six, "Sheet2": [TOTAL]})
    assert [t["sheet"] for t in reader.journal_tables(q)] == ["Sheet1", "Sheet2"] and _balanced(q, six)
    assert reader.row_limit_hit(q, reader.journal_sheet_rows(q)) is None


def test_short_title_daily_and_blank_sheet_continuations(tmp_path, small_limit):
    """짧은 이어짐 + 합계 줄, 맨 앞 제목 줄, 일계 줄, 사이에 낀 빈 시트."""
    body = _body(10)
    rest = body[FIRST:]
    daily = []
    for i, r in enumerate(rest):
        daily.append(r)
        if i % 3 == 2:
            daily.append(("[ 일 계 ]", None, 1, None, None, 1, None, None))
    cases = {"short": ({"Sheet1": HEAD + body[:FIRST], "Sheet2": rest[:1] + [TOTAL]}, body[:FIRST + 1]),
             "title": ({"Sheet1": HEAD + body[:FIRST], "Sheet2": [("분개장(계속)",)] + rest + [TOTAL]}, body),
             "daily": ({"Sheet1": HEAD + body[:FIRST], "Sheet2": daily + [TOTAL]}, body),
             "blank": ({"Sheet1": HEAD + body[:FIRST], "Sheet2": [], "Sheet3": rest + [TOTAL]}, body)}
    for name, (sheets, want) in cases.items():
        p = _xlsx(tmp_path / f"{name}.xlsx", sheets)
        assert reader.journal_tables(p)[-1].get("cont_of") == "Sheet1", name
        assert _balanced(p, want), name
        assert reader.row_limit_hit(p, reader.journal_sheet_rows(p)) is None, name


def test_other_tables_after_full_sheet_are_not_read(tmp_path, small_limit):
    """앞 시트 마지막 일자보다 이른 날부터 시작하는 일별 집계, 한 달 넘게 떨어진 같은 머리줄 시트는 잇지 않는다."""
    body = _body(12)
    summary = [(f"2026/01/{d:02d}", None, 1000 * d, None, None, 1000 * d, None, None) for d in range(1, 21)]
    p = _xlsx(tmp_path / "a.xlsx", {"Sheet1": HEAD + body[:FIRST], "일별": summary})
    assert [t["sheet"] for t in reader.journal_tables(p)] == ["Sheet1"]
    later = [x for k in range(3) for x in _voucher(10 + k, 100 + k, 500, month=4)]
    q = _xlsx(tmp_path / "b.xlsx", {"Sheet1": HEAD + body[:FIRST], "4월": HEAD + later})
    assert not reader.journal_tables(q)[0].get("continued")
    assert reader.row_limit_hit(q, reader.journal_sheet_rows(q)) == LIMIT


def test_index_rereads_journal_only_when_rules_change(tmp_path):
    """판독 규칙 판이 다른 분개장은 파일이 그대로여도 index read 가 다시 읽는다. 판이 같으면 다시 읽지 않는다."""
    import json

    from audit import folder, index

    now = "2026-11-23 23:00"
    d = folder.scaffold(tmp_path / "합성상사(가상)" / "2026 중간감사", "합성상사(가상)", "2026-12-31", now=now)
    p = d / "00 받은자료" / "분개장" / "086_2026-01 분개장.xlsx"
    p.parent.mkdir(parents=True, exist_ok=True)
    _xlsx(p, {"Sheet1": HEAD + _body(3)})
    index.read_all(d, now=now)
    docs_p = d / "_색인" / "문서목록.json"

    def entry(docs):
        return next(f for f in docs["files"] if f["path"].endswith("086_2026-01 분개장.xlsx"))

    docs = json.loads(docs_p.read_text(encoding="utf-8"))
    assert entry(docs).get("journal_rules") == reader.JOURNAL_RULES
    entry(docs).pop("journal_rules")
    docs_p.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    calls = []
    real = reader.read
    try:
        reader.read = lambda *a, **k: calls.append(a[0]) or real(*a, **k)
        index.read_all(d, now=now)
        assert len(calls) == 1
        folder.scan(d, now=now)
        index.read_all(d, now=now)
        assert len(calls) == 1
    finally:
        reader.read = real
    assert entry(json.loads(docs_p.read_text(encoding="utf-8"))).get("journal_rules") == reader.JOURNAL_RULES
