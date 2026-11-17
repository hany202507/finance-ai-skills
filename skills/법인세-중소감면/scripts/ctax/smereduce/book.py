"""중소기업특별세액감면 검증 워크북. 입력은 노란 칸, 판정 · 감면율 · 감면세액은 모두 엑셀 수식이다. 엔진 값은 「4엔진대조」 에만 숫자로 들어간다.

시트: 목록 · 0입력 · 0기준 · 2계산 · 3신청서 · 4엔진대조
"""
from __future__ import annotations

from datetime import date
from fractions import Fraction

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from .. import xlsx as X
from .model import COMPANY_ROWS, NOT_LISTED, Inputs, picks

S_LIST, S_IN, S_BASE, S_CALC, S_FORM, S_CHECK = "목록", "0입력", "0기준", "2계산", "3신청서", "4엔진대조"
DATE_FMT = "yyyy-mm-dd"
RATE_FMT = "0.00%"


def _q(sheet: str) -> str:
    return f"'{sheet}'!"


def _s(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


class Book:
    def __init__(self, inp: Inputs, r: dict, rules: dict, notes: list[str]):
        self.inp, self.r, self.rules, self.notes = inp, r, rules, notes
        self.wb = Workbook()
        self.addr: dict[str, str] = {}
        self.engine: list[tuple] = []       # (항목, 엔진 값, 이름, 꼴)

    def a(self, name: str) -> str:
        return self.addr[name]

    # ------------------------------------------------------------ 0입력
    def sheet_input(self):
        ws = self.wb.active
        ws.title = S_IN
        row = X.title(ws, "0 입력", "노란 칸만 고친다. 입력 파일(중소감면_입력.xlsx 회사 시트)과 같은 값이다. 고쳤으면 입력 파일도 고친다")
        X.header(ws, row, ["항목", "값", "설명"])
        opts = picks(self.rules)
        for key, kind, _d, desc in COMPANY_ROWS:
            row += 1
            v = self.inp.values[key]
            X.cell(ws, row, 1, key)
            c = X.cell(ws, row, 2, v, kind="input", money=kind == "won")
            if kind == "date":
                c.number_format = DATE_FMT
            elif kind == "rate":
                c.number_format = RATE_FMT
            if kind.startswith("pick:") and kind != "pick:industry":   # 업종 목록은 255자를 넘어 목록 검사를 걸지 않는다
                dv = DataValidation(type="list", formula1='"' + ",".join(opts[kind[5:]]) + '"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(c)
            if kind == "yn":
                dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(c)
            X.cell(ws, row, 3, desc, wrap=True)
            self.addr["in:" + key] = f"{_q(S_IN)}$B${row}"
        X.widths(ws, [40, 26, 90])

    # ------------------------------------------------------------ 0기준
    def sheet_base(self):
        ws = self.wb.create_sheet(S_BASE)
        R = self.rules
        row = X.title(ws, "0 기준", "법령 값. 근거 조문 · 등급은 rules.yaml 과 같다")
        X.header(ws, row, ["항목", "값", "근거"])

        def put(name, label, value, basis, fmt=None):
            nonlocal row
            row += 1
            X.cell(ws, row, 1, label)
            c = X.cell(ws, row, 2, value, money=isinstance(value, int) and value > 1000)
            if fmt:
                c.number_format = fmt
            X.cell(ws, row, 3, basis, wrap=True)
            self.addr["b:" + name] = f"{_q(S_BASE)}$B${row}"

        ind = R["industry"]
        put("deadline", "일몰(이 날 이전에 끝나는 과세연도까지)", date.fromisoformat(R["period"]["deadline"]["value"]),
            R["period"]["deadline"]["basis"], DATE_FMT)
        put("publish_from", "일반 서적 출판업(마목) 적용 개시일", date.fromisoformat(ind["publish"]["from"]), ind["publish"]["basis"], DATE_FMT)
        put("small_since", "별표 3 새 표 적용(과세연도 종료일이 이 날 이후, 엔진 규칙)", date.fromisoformat(R["small"]["since"]["value"]),
            R["small"]["since"]["basis"], DATE_FMT)
        put("hydro_from", "수소발전사업 적용 개시일(엔진 규칙)", date.fromisoformat(ind["hydrogen"]["from"]), ind["hydrogen"]["basis"], DATE_FMT)
        put("limit", "감면한도", R["limit"]["base"]["value"], R["limit"]["base"]["basis"])
        put("per_worker", "감소 상시근로자 1명당 한도 차감", R["limit"]["per_worker"]["value"], R["limit"]["per_worker"]["basis"])
        row += 2
        X.cell(ws, row, 1, "감면 비율(기업 규모|지역|업종 구분)").font = Font(name=X.FONT, bold=True)
        row += 1
        X.header(ws, row, ["구분", "감면율"])
        top = row + 1
        for key, rate in R["rates"]["value"].items():
            row += 1
            X.cell(ws, row, 1, key)
            X.cell(ws, row, 2, rate).number_format = RATE_FMT
        X.cell(ws, row + 1, 1, R["rates"]["basis"], wrap=True)
        self.addr["b:rate_keys"] = f"{_q(S_BASE)}$A${top}:$A${row}"
        self.addr["b:rate_vals"] = f"{_q(S_BASE)}$B${top}:$B${row}"
        row += 3
        X.cell(ws, row, 1, "소기업 규모 기준(중소기업기본법 시행령 별표 3)").font = Font(name=X.FONT, bold=True)
        row += 1
        X.header(ws, row, ["호 · 주된 업종", "규모 기준(2025-09-01 개정 표)", "분류기호", "옛 규모 기준(2025-08-31 까지)"])
        top = row + 1
        for no, name, code, amt, old in R["small"]["table"]["value"]:
            row += 1
            X.cell(ws, row, 1, f"{no}. {name}")
            X.cell(ws, row, 2, amt, money=True)
            X.cell(ws, row, 3, code)
            X.cell(ws, row, 4, old, money=True)
        self.addr["b:small"] = f"{_q(S_BASE)}$B${top}:$B${row}"
        self.addr["b:small_old"] = f"{_q(S_BASE)}$D${top}:$D${row}"
        self.addr["b:small_names"] = f"{_q(S_BASE)}$A${top}:$A${row}"
        X.cell(ws, row + 1, 1, R["small"]["table"]["basis"], wrap=True)
        row += 3
        X.cell(ws, row, 1, "도매업등(가목 · 라목)").font = Font(name=X.FONT, bold=True)
        top = row + 1
        for name in ind["wholesale"]["value"]:
            row += 1
            X.cell(ws, row, 1, name)
        self.addr["b:wholesale"] = f"{_q(S_BASE)}$A${top}:$A${row}"
        put("half", "감면 비율 절반 업종(제2호 단서)", ind["half"]["value"], ind["half"]["basis"])
        put("hydro", "수소발전사업", ind["hydrogen"]["value"], ind["hydrogen"]["basis"])
        X.widths(ws, [52, 20, 90, 20])

    # ------------------------------------------------------------ 2계산
    def sheet_calc(self):
        ws = self.wb.create_sheet(S_CALC)
        row = X.title(ws, "2 계산", "판정과 감면세액. 모두 수식이다. C 열은 근거")
        X.header(ws, row, ["항목", "값", "근거"])
        self._row = row
        I = lambda k: self.a("in:" + k)        # noqa: E731
        B = lambda k: self.a("b:" + k)         # noqa: E731
        N = self.a
        r = self.r

        def put(name, label, formula, basis="", fmt=None, engine=None, kind="num"):
            self._row += 1
            X.cell(ws, self._row, 1, label)
            c = X.cell(ws, self._row, 2, "=" + formula, money=fmt == "won")
            if fmt == "rate":
                c.number_format = RATE_FMT
            elif fmt == "ratio":
                c.number_format = "0.000000"
            X.cell(ws, self._row, 3, basis, wrap=True)
            self.addr[name] = f"{_q(S_CALC)}$B${self._row}"
            if engine is not None or name in r:
                val = r.get(name) if engine is None else engine
                self.engine.append((label, val, name, kind))

        def section(text):
            self._row += 2
            X.cell(ws, self._row, 1, text).font = Font(name=X.FONT, bold=True)

        fs, fe, ind = I("과세연도 시작일"), I("과세연도 종료일"), I("업종")
        section("1. 감면 대상(제7조 제1항)")
        put("c_deadline", "일몰 안", f"{fe}<={B('deadline')}", "제7조 제1항", kind="bool")
        put("c_sme", "중소기업", f'{I("중소기업")}="Y"', "제7조 제1항", kind="bool")
        put("c_industry", "감면 업종", f'AND({ind}<>{_s(NOT_LISTED)},{I("업종 괄호 제외 업종")}="N",'
            f'NOT(AND({ind}={B("hydro")},{fs}<{B("hydro_from")})))', "제7조 제1항 제1호", kind="bool")
        put("eligible", "감면 대상", f'AND({N("c_deadline")},{N("c_sme")},{N("c_industry")})', kind="bool")

        section("2. 소기업 · 수도권 · 업종 구분")
        put("threshold", "소기업 규모 기준", f'IF({I("소기업 규모 기준 직접 입력")}<>"",{I("소기업 규모 기준 직접 입력")},'
            f'IF({fe}>={B("small_since")},INDEX({B("small")},{I("별표 3 업종 호")}),INDEX({B("small_old")},{I("별표 3 업종 호")})))',
            "시행령 제6조 제4항, 중소기업기본법 시행령 별표 3(과세연도 종료일 현재 시행 표)", "won")
        put("small", "소기업", f'{I("매출액")}<={N("threshold")}', "매출액 ≤ 규모 기준", kind="bool")
        put("size", "기업 규모", f'IF({N("small")},"소기업","중기업")', kind="text")
        put("capital", "수도권", f'OR({I("본점 수도권")}="Y",{I("감면 사업장 수도권")}="Y")', "제7조 제1항 단서(본점이 수도권이면 모든 사업장 수도권)",
            kind="bool")
        put("region", "지역 구분", f'IF({N("capital")},"수도권","수도권 외")', kind="text")
        put("group", "업종 구분", f'IF(COUNTIF({B("wholesale")},{ind})>0,"도매업등",IF(AND({ind}="출판업",{I("일반 서적 출판업")}="Y",'
            f'{N("size")}="중기업",{N("capital")},{fs}>={B("publish_from")}),"일반 서적 출판업","그 밖"))',
            "가목 도매업등 · 마목 일반 서적 출판업(2025 이후 개시)", kind="text")
        put("key", "감면 비율 구분", f'{N("size")}&"|"&{N("region")}&"|"&{N("group")}', kind="text")

        section("3. 감면율(제7조 제1항 제2호)")
        put("half", "절반 업종(통관 대리)", f'AND({ind}={B("half")},{N("group")}="그 밖")', "제2호 단서", kind="bool")
        put("rate_table", "표에서 고른 감면율", f'INDEX({B("rate_vals")},MATCH({N("key")},{B("rate_keys")},0))*IF({N("half")},0.5,1)',
            "0기준 감면 비율 표", "rate", engine=float(r["rate_table"]))
        put("rate", "감면율(감면 대상일 때)", f'IF({N("eligible")},{N("rate_table")},0)', "", "rate", engine=float(r["rate"]))

        section("4. 감면한도(제7조 제1항 제3호)")
        sc, sp = I("상시근로자 수(해당)"), I("상시근로자 수(직전)")
        put("staff_dec", "감소한 상시근로자 수", f'IF(OR({sc}="",{sp}=""),0,MAX(0,ROUND({sp}-{sc},4)))', "시행령 제6조 제7항(제23조 제10항 ~ 제13항 준용)",
            engine=float(r["staff_dec"]))
        put("limit_cut", "한도 차감액", f'ROUNDDOWN(ROUND({N("staff_dec")}*{B("per_worker")},4),0)', "가목: 1명당 5백만원", "won")
        put("limit", "감면한도", f'MAX(0,{B("limit")}-{N("limit_cut")})', "가목 · 나목", "won")

        section("5. 감면소득(법인세법 시행령 제96조)")
        inc, ded, src = I("각 사업연도 소득금액"), I("이월결손금 · 비과세 · 소득공제"), I("공제액등이 생긴 사업")
        put("biz_income", "감면사업 소득", f'MAX(0,{inc}-{I("감면 제외 소득")})', "해당 사업장 · 감면 업종 소득", "won")
        put("ded_share", "공제액등 중 감면사업 몫", f'IF({src}="감면사업",{ded},IF(OR({src}="그 밖의 사업",{inc}<=0),0,'
            f'ROUNDDOWN(ROUND({ded}*{N("biz_income")}/{inc},4),0)))', "제1호 전액 · 제2호 소득금액 비례 안분", "won")
        put("reduced_income", "감면소득", f'MAX(0,{N("biz_income")}-{N("ded_share")})', "", "won")

        section("6. 감면세액(법인세법 제59조 제2항)")
        tax, base = I("산출세액"), I("과세표준")
        put("inc_ratio", "감면소득 ÷ 과세표준(100% 한도)", f'IF(AND({base}>0,{N("reduced_income")}>0),MIN(1,{N("reduced_income")}/{base}),0)',
            "법인세법 제59조 제2항", "ratio", engine=float(r["inc_ratio"]))
        put("tax_on_income", "감면소득에 대한 세액", f'{tax}*{N("inc_ratio")}', "", "won", engine=float(r["tax_on_income"]))
        put("a7", "⑦ 대상세액(최저한세 전)", f'ROUNDDOWN(ROUND({N("tax_on_income")}*{N("rate")},4),0)', "원 미만 버림", "won")
        mb = I("최저한세 과세표준")
        put("mt_base", "최저한세 과세표준", f'IF({mb}<>"",{mb},{base})', "", "won")
        put("min_tax", "최저한세액", f'ROUNDDOWN(ROUND({N("mt_base")}*{I("최저한세율")},4),0)', "제132조 제1항", "won")
        put("mt_room", "감면이 받을 수 있는 최저한세 여지", f'MAX(0,{tax}-{N("min_tax")}-{I("먼저 적용할 다른 최저한세 대상 감면 · 공제")})',
            "제132조 제1항 제4호(제7조는 적용대상)", "won")
        put("a8", "⑧ 감면세액(최저한세 반영)", f'MIN({N("a7")},{N("mt_room")})', "", "won")
        put("mt_cut", "최저한세로 감면하지 않은 금액", f'{N("a7")}-{N("a8")}', "", "won")
        put("a9", "⑨ 한도충족 감면세액", f'MIN({N("a8")},{N("limit")})', "서식 작성방법: ⑧ 과 감면한도 중 적은 금액", "won")
        put("limit_over", "한도를 넘어 감면하지 않은 금액", f'{N("a8")}-{N("a9")}', "", "won")

        section("7. 중복 배제(제127조 제4항 · 제5항)와 통합고용세액공제")
        put("other_sum", "함께 받지 못하는 공제감면 합계", f'{I("제127조 제4항 세액공제")}+{I("같은 사업장 다른 감면")}', "제127조 제4항 본문 · 제5항", "won")
        put("chosen", "중소기업특별세액감면을 고름", f'{I("적용 선택")}="중소기업특별세액감면"', kind="bool")
        put("total", "중소기업특별세액감면(신청)", f'IF({N("chosen")},{N("a9")},0)', "", "won")
        emp = I("통합고용 세액공제")
        put("emp_room", "감면(또는 고른 다른 공제감면) 뒤 남은 최저한세 여지",
            f'MAX(0,{N("mt_room")}-IF({N("chosen")},{N("total")},{N("other_sum")}))', "고른 쪽이 여지를 먼저 쓴다고 봄(순서는 납세자가 고름)", "won")
        put("emp_now", "통합고용 세액공제(당기 공제)", f'MIN({emp},{N("emp_room")})', "제127조 제4항이 막지 않음, 제132조", "won")
        put("emp_carry", "통합고용 세액공제(이월)", f'{emp}-{N("emp_now")}', "제144조", "won")
        X.widths(ws, [40, 22, 70])

    # ------------------------------------------------------------ 3신청서
    def sheet_form(self):
        ws = self.wb.create_sheet(S_FORM)
        row = X.title(ws, "3 세액감면(면제)신청서", "조세특례제한법 시행규칙 별지 제2호서식(2026. 5. 22. 개정) ❸ 신청 내용 중 112 줄과 합계")
        X.header(ws, row, ["구분", "근거법령", "코드", "⑥ 감면율", "⑦ 대상세액", "⑧ 감면세액", "⑨ 한도충족 감면세액"])
        N = self.a
        row += 1
        first = row
        X.cell(ws, row, 1, "중소기업에 대한 특별세액감면")
        X.cell(ws, row, 2, "영 제6조제8항")
        X.cell(ws, row, 3, "112")
        X.cell(ws, row, 4, f'=IF({N("a7")}=0,"",{N("rate")})').number_format = RATE_FMT
        X.cell(ws, row, 5, f'=IF({N("chosen")},{N("a7")},0)', money=True)
        X.cell(ws, row, 6, f'=IF({N("chosen")},{N("a8")},0)', money=True)
        X.cell(ws, row, 7, f'={N("total")}', money=True)
        row += 1
        X.cell(ws, row, 1, "세액감면 합계", kind="total")
        X.cell(ws, row, 3, "1A4", kind="total")
        for col in (5, 6, 7):
            L = "EFG"[col - 5]
            X.cell(ws, row, col, f"=SUM({L}{first}:{L}{row - 1})", money=True, kind="total")
        q = _q(S_FORM)
        self.addr.update({"f:total": f"{q}$G${row}", "f:a7": f"{q}$E${first}", "f:a8": f"{q}$F${first}", "f:a9": f"{q}$G${first}"})
        row += 2
        for text in ("작성방법: ⑦ 대상세액은 최저한세 적용 전 감면세액, ⑧ 은 ⑦ 에서 최저한세 배제세액을 뺀 금액, ⑨ 는 ⑧ 과 감면한도 중 적은 금액",
                     "다른 감면 줄(창업감면 11O · 111 등)은 이 시트에 없다. 같은 사업장이면 제127조 제5항으로 하나만 적는다",
                     "상호 · 사업자등록번호 · 대표자 · 주소 · 날짜 · 서명은 사람이 적는다"):
            X.cell(ws, row, 1, text).font = X.NOTE_FONT
            row += 1
        X.widths(ws, [36, 16, 8, 12, 18, 18, 20])

    # ------------------------------------------------------------ 4엔진대조
    def sheet_check(self):
        ws = self.wb.create_sheet(S_CHECK)
        row = X.title(ws, "4 엔진 대조", "엔진(ctax smereduce)이 따로 계산한 값과 수식 값. 「불일치」 가 있으면 입력 칸이나 수식을 바꾼 것이다")
        X.header(ws, row, ["항목", "엔진 값", "수식 값", "결과"])
        top = row + 1
        for label, val, name, kind in self.engine:
            row += 1
            X.cell(ws, row, 1, label)
            if isinstance(val, Fraction):
                val = float(val)
            X.cell(ws, row, 2, val)
            X.cell(ws, row, 3, f"={self.a(name)}")
            X.cell(ws, row, 4, f'=IF(AND(ISNUMBER(B{row}),ISNUMBER(C{row})),IF(ABS(C{row}-B{row})<0.005,"일치","불일치"),'
                               f'IF(C{row}&""=B{row}&"","일치","불일치"))')
        self.addr["k:res"] = f"{_q(S_CHECK)}$D${top}:$D${row}"
        X.widths(ws, [40, 18, 18, 10])

    # ------------------------------------------------------------ 목록
    def sheet_list(self):
        ws = self.wb.create_sheet(S_LIST, 0)
        N, I = self.a, lambda k: self.a("in:" + k)
        v = self.inp.values
        row = X.title(ws, "중소기업특별세액감면 검증", f"{v['과세연도 시작일']} ~ {v['과세연도 종료일']} · 조세특례제한법 제7조 · ctax smereduce")
        X.header(ws, row, ["결과", "값", "", ""])
        for label, f, fmt in (("중소기업특별세액감면(신청, 112)", N("total"), "won"), ("감면 대상", N("eligible"), None),
                              ("감면 비율 구분", N("key"), None), ("감면율", N("rate"), "rate"), ("감면한도", N("limit"), "won"),
                              ("⑦ 대상세액", N("a7"), "won"), ("최저한세로 감면하지 않은 금액", N("mt_cut"), "won"),
                              ("통합고용 세액공제 당기 · 이월", f'TEXT({N("emp_now")},"#,##0")&" · "&TEXT({N("emp_carry")},"#,##0")', None)):
            row += 1
            X.cell(ws, row, 1, label)
            c = X.cell(ws, row, 2, f"={f}", money=fmt == "won")
            if fmt == "rate":
                c.number_format = RATE_FMT
        row += 2
        X.header(ws, row, ["검산", "결과", "왼쪽", "오른쪽"])
        checks = [
            ("신청서 1A4 ⑨ = 2계산 신청 금액", N("f:total"), N("total"), "="),
            ("112 ⑨ ≤ ⑧ ≤ ⑦", f"AND({N('f:a9')}<={N('f:a8')},{N('f:a8')}<={N('f:a7')})", "TRUE", "bool"),
            ("⑨ ≤ 감면한도", N("a9"), N("limit"), "<="),
            ("감면세액 ≤ 감면소득에 대한 세액", N("total"), N("tax_on_income"), "<="),
            ("감면소득 ≤ 과세표준(넘으면 100% 로 자름)", N("inc_ratio"), "1", "<="),
            ("감면 뒤 세액이 최저한세를 지킴", f"{I('산출세액')}-{N('a8')}", N("min_tax"), ">=t"),
            ("엔진 대조 불일치 0건", f'COUNTIF({N("k:res")},"불일치")', "0", "="),
        ]
        for label, left, right, op in checks:
            row += 1
            X.cell(ws, row, 1, label)
            if op == "bool":
                ok = f"={left}"
            elif op == "=":
                ok = f"=ABS(({left})-({right}))<0.005"
            elif op == ">=t":                  # 감면이 없거나 처음부터 산출세액이 최저한세보다 작으면 깎을 것이 없다
                ok = f"=OR({N('a8')}=0,({left})>=({right}))"
            else:
                ok = f"=({left})<=({right})+0.005"
            X.cell(ws, row, 2, f'=IF({ok[1:]},"통과","확인")')
            X.cell(ws, row, 3, f"={left}")
            X.cell(ws, row, 4, f"={right}")
        row += 2
        X.cell(ws, row, 1, "확인할 것").font = Font(name=X.FONT, bold=True)
        for text in self.notes:
            row += 1
            X.cell(ws, row, 1, text, wrap=True)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
            ws.row_dimensions[row].height = 30
        X.widths(ws, [46, 22, 20, 20])

    def build(self) -> Workbook:
        self.sheet_input()
        self.sheet_base()
        self.sheet_calc()
        self.sheet_form()
        self.sheet_check()
        self.sheet_list()
        return self.wb


def build(inp: Inputs, r: dict, rules: dict, notes: list[str]) -> tuple[Workbook, list]:
    b = Book(inp, r, rules, notes)
    wb = b.build()
    return wb, b.engine
