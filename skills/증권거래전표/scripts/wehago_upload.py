"""위하고(더존 Smart A 10 · WEHAGO T) 일반전표 엑셀 업로드 파일 쓰기와 올리기 전 검사.

근거(2026-11-08 정리):
- 더존 「일반전표입력 엑셀업로드방법_SmartA 10」(2024-12-06), 「SmartA 10 회계관리매뉴얼」(2023-02-22)
- 결산자동화 스킬 `references/더존업로드양식.md` 와 결산 · 급여 전표를 실제로 올려 본 기록

| 항목 | 규칙 | 근거 |
|---|---|---|
| 필수 열 | 월 · 일 · 구분 · 계정과목코드 · 계정과목명 | 업로드 방법 PDF p.1~2(노란색 5개) |
| 구분 | 3 차변 · 4 대변 | 같은 PDF. 1 · 2(출금 · 입금)는 쓰지 않는다 |
| 숫자 열 | 월 · 일 · 구분 · 계정과목코드 · 차변 · 대변은 숫자형. 텍스트면 반려 | 결산 스킬 실측 |
| 거래처코드 | 앞자리 0 을 지키려고 텍스트. 3~10자리(회사 환경설정) | 같은 자료조사 |
| 적요 | 71자 이상은 업로드 거부(실측). 41~70자는 확인. 기본 40자로 자른다 | 결산 · 급여 스킬 실측 |
| 적요 글자 | CP949 로 못 쓰는 글자(이모지, 일부 외국 문자)와 줄바꿈 · 탭은 깨진다 | 급여 스킬 검사 |
| 전표 | 한 전표의 줄은 붙어 있고 차변 합 = 대변 합 | 더존 양식 문서 |
| 연도 | 파일에 연도 열이 없어 회계연도 하나에 한 파일. 기간이 두 해에 걸치면 나눈다 | 양식에 연도 열 없음 |
| 외화 | 일반전표 업로드에 외화 열이 없다. 원화만 올리고 외화는 워크북 거래원장이 보조원장이다 | 같은 자료조사 |
| 재업로드 | 위하고 「자동분개 일괄검색 및 삭제 > 전표엑셀업로드」로 먼저 지운다. 변환옵션은 기본값(계정코드 · 거래처 기준) | 업로드 방법 PDF |
| 글자 저장 꼴 | 글자 칸은 sharedStrings · UTF-8 글자 그대로. openpyxl 기본(inlineStr, 한글을 &#50900; 문자참조)은 위하고에서 한글이 깨진다 | 2026-11-08 커널스페이스 실제 업로드 |
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

HEADER = ["월", "일", "구분", "계정과목코드", "계정과목명", "거래처코드", "거래처명", "적요", "차변", "대변"]
MEMO_WARN, MEMO_FAIL = 41, 71


def clean_memo(s: str, limit: int = 40) -> str:
    """줄바꿈 · 탭을 띄어쓰기로, CP949 로 못 쓰는 글자를 ? 로 바꾸고 limit 자 안으로 자른다(끝의 #번호는 지킨다)."""
    s = " ".join(str(s or "").split())
    s = "".join(ch if _cp949(ch) else "?" for ch in s)
    if len(s) > limit:
        m = re.search(r" #\d+$", s)
        tag = m.group(0) if m else ""
        s = s[: limit - len(tag)].rstrip() + tag
    return s


def to_shared_strings(path: Path):
    """openpyxl 이 쓴 글자 칸(inlineStr, 한글은 &#50900; 같은 숫자 문자참조)을 엑셀이 저장하는 꼴(sharedStrings,
    UTF-8 글자 그대로)로 바꾼다. 위하고 일반전표 엑셀올리기는 숫자 문자참조를 풀지 못해 계정과목명 · 거래처 · 적요의
    한글이 깨졌다(2026-11-08 커널스페이스 시험 업로드, 엑셀로 다시 저장한 파일은 정상)."""
    import html
    import re as _re
    import zipfile
    from xml.sax.saxutils import escape
    src = zipfile.ZipFile(path)
    files = {n: src.read(n) for n in src.namelist()}
    src.close()
    sst, index = [], {}

    def repl(m):
        attrs, text = m.group(1), html.unescape(m.group(2))
        if text not in index:
            index[text] = len(sst)
            sst.append(text)
        return f'<c{attrs} t="s"><v>{index[text]}</v></c>'

    cell = _re.compile(r'<c([^>]*?) t="inlineStr"><is><t[^>]*>(.*?)</t></is></c>', _re.S)
    sheets = [n for n in files if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
    empty = _re.compile(r'<c([^>]*?) t="inlineStr">(?:<is>(?:<t[^>]*/>|<t[^>]*></t>)?</is>)?</c>')
    for n in sheets:
        x = empty.sub(lambda m: f"<c{m.group(1)}/>", files[n].decode("utf-8"))     # 빈 글자 칸은 빈 칸으로
        files[n] = cell.sub(repl, x).encode("utf-8")
    if not sst:
        return
    body = "".join(f'<si><t xml:space="preserve">{escape(t)}</t></si>' for t in sst)
    files["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(sst)}" '
        f'uniqueCount="{len(sst)}">{body}</sst>').encode("utf-8")
    ct = files["[Content_Types].xml"].decode("utf-8")
    if "sharedStrings" not in ct:
        ct = ct.replace("</Types>", '<Override PartName="/xl/sharedStrings.xml" ContentType="application/'
                        'vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        files["[Content_Types].xml"] = ct.encode("utf-8")
    rels = files["xl/_rels/workbook.xml.rels"].decode("utf-8")
    if "sharedStrings" not in rels:
        rels = rels.replace("</Relationships>", '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/'
                            '2006/relationships/sharedStrings" Target="sharedStrings.xml" Id="rIdSst"/></Relationships>')
        files["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)


def _cp949(ch: str) -> bool:
    try:
        ch.encode("cp949")
        return True
    except UnicodeEncodeError:
        return False


def fiscal_year(d: dt.date, start_month: int) -> int:
    """회계연도 이름(시작 연도). 1월 시작이면 그해."""
    return d.year if d.month >= start_month else d.year - 1


def write(lines, out_dir: Path, company: str, cfg) -> list:
    """lines(재계산 값) → 회계연도마다 위하고_일반전표_<회사>[_<연도>].xlsx. [(경로, 줄 수, 검사 결과)]"""
    import openpyxl
    from read_source import parse_date
    codes = {k: str(v) for k, v in (cfg.get("거래처코드") or {}).items()}
    limit = int(cfg.get("적요길이", 40))
    start_m = int(cfg.get("회계연도시작월", 1))
    rows_by_year = {}
    for ln in lines:
        dr, cr = ln["dr"] or 0, ln["cr"] or 0
        if not dr and not cr:
            continue
        d = ln["date"]
        if isinstance(d, dt.datetime):
            d = d.date()
        if not isinstance(d, dt.date):
            d = parse_date(d)
        if d is None:
            continue
        party = ln["party"] or ""
        code = str(ln["code"]).strip()
        row = [d.month, d.day, int(ln["gubun"]), int(code) if code.isdigit() else code, ln["name"],
               codes.get(party, ""), party, clean_memo(ln["memo"], limit), int(round(dr)), int(round(cr))]
        rows_by_year.setdefault(fiscal_year(d, start_m), []).append((d, ln.get("voucher"), row))
    out = []
    multi = len(rows_by_year) > 1
    for fy, rows in sorted(rows_by_year.items()):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "일반전표"
        ws.append(HEADER)
        for _, _, row in rows:
            ws.append(row)
        for r in range(2, ws.max_row + 1):
            ws.cell(r, 6).number_format = "@"          # 거래처코드 앞자리 0
        p = out_dir / (f"위하고_일반전표_{company}_{fy}.xlsx" if multi else f"위하고_일반전표_{company}.xlsx")
        wb.save(p)
        to_shared_strings(p)       # 위하고가 읽는 글자 저장 꼴로(2026-11-08 실제 업로드에서 한글이 깨졌다)
        out.append((p, len(rows), verify(rows, cfg)))
    return out


def verify(rows, cfg) -> list:
    """올리기 전 검사. [(항목, 값, 판정, 예시)] 판정은 OK · 확인 · 반려."""
    res = []
    body = [r for _, _, r in rows]

    def chk(name, bad, level="반려"):
        res.append((name, len(bad), "OK" if not bad else level, "; ".join(map(str, bad[:3]))))

    chk("필수 열(월 · 일 · 구분 · 계정코드 · 계정명) 빈칸", [i for i, r in enumerate(body, 2) if any(r[k] in (None, "") for k in range(5))])
    chk("구분이 3 · 4 가 아닌 줄", [i for i, r in enumerate(body, 2) if r[2] not in (3, 4)])
    chk("숫자형이 아닌 계정코드", [f"{i}행 {r[3]}" for i, r in enumerate(body, 2) if not isinstance(r[3], int)])
    chk("구분과 금액 열이 어긋난 줄(차변 줄에 대변 금액 등)",
        [i for i, r in enumerate(body, 2) if (r[2] == 3 and (r[9] or r[8] <= 0)) or (r[2] == 4 and (r[8] or r[9] <= 0))])
    chk("음수 금액", [i for i, r in enumerate(body, 2) if r[8] < 0 or r[9] < 0])
    chk(f"적요 {MEMO_FAIL}자 이상(업로드 거부)", [f"{i}행 {len(r[7])}자" for i, r in enumerate(body, 2) if len(r[7]) >= MEMO_FAIL])
    chk(f"적요 {MEMO_WARN}~{MEMO_FAIL - 1}자", [f"{i}행 {len(r[7])}자" for i, r in enumerate(body, 2) if MEMO_WARN <= len(r[7]) < MEMO_FAIL], "확인")
    chk("적요에 CP949 로 못 쓰는 글자 · 줄바꿈", [i for i, r in enumerate(body, 2) if "?" in r[7] or "\n" in r[7]], "확인")
    bad_codes = [f"{k}={v}" for k, v in (cfg.get("거래처코드") or {}).items() if not re.fullmatch(r"\d{3,10}", str(v))]
    chk("거래처코드가 숫자 3~10자리가 아님", bad_codes)
    # 전표 경계: 같은 날 줄을 위에서부터 더해 차대가 0 이 되는 곳에서 끊긴다. 날짜가 바뀌기 전에 0 이 돼야 한다
    unbal, run, cur = [], 0, None
    for i, (d, _, r) in enumerate(rows, 2):
        if d != cur:
            if run:
                unbal.append(f"{cur} 차대 {run:+,}")
            run, cur = 0, d
        run += r[8] - r[9]
    if run:
        unbal.append(f"{cur} 차대 {run:+,}")
    chk("날짜 안에서 차대가 맞지 않는 전표", unbal)
    no_party = [f"{i}행 {r[4]}" for i, r in enumerate(body, 2) if r[6] and not r[5]]
    chk("거래처명은 있는데 거래처코드가 빈 줄(거래처명만 반영된다)", no_party, "확인")
    # 계정코드 · 이름을 위하고 기본 계정과목과 맞춘다. 회사가 이름을 바꿔 쓰면 회사 화면을 따르니 확인으로만 둔다
    std = _standard_accounts()
    used = sorted({(r[3], r[4]) for r in body}, key=lambda x: str(x[0]))
    chk("위하고 기본 계정표에 없는 코드(회사 [계정과목및적요등록] 화면 확인)",
        [f"{c} {n}" for c, n in used if str(c) not in std], "확인")
    chk("위하고 기본 이름과 다른 계정명(코드 기준으로 올라가니 회사 이름이면 그대로)",
        [f"{c} {n}(기본 {std[str(c)]})" for c, n in used if str(c) in std and std[str(c)] != n], "확인")
    return res


def _standard_accounts() -> dict:
    import csv
    p = Path(__file__).resolve().parent.parent / "references" / "위하고_계정과목.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8-sig") as f:
        return {r[0].strip(): r[1].strip() for r in list(csv.reader(f))[1:] if r}
