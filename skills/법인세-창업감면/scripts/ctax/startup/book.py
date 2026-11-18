"""창업감면 검증 워크북. 입력은 노란 칸, 판정 · 감면율 · 감면세액은 모두 엑셀 수식이다. 엔진 값은 「4엔진대조」 에만 숫자로 들어간다.

시트: 목록 · 0입력 · 0기준 · 1연도별 · 2계산 · 3신청서 · 4엔진대조
"""
from __future__ import annotations

from datetime import date
from fractions import Fraction

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from .. import xlsx as X
from .model import COMPANY_ROWS, REGIONS, Inputs, picks

S_LIST, S_IN, S_BASE, S_YEARS, S_CALC, S_FORM, S_CHECK = "목록", "0입력", "0기준", "1연도별", "2계산", "3신청서", "4엔진대조"
DATE_FMT = "yyyy-mm-dd"
RATE_FMT = "0.00%"
HEADS = ("청년", "일반", "청년상실", "소규모")


def _q(sheet: str) -> str:
    return f"'{sheet}'!"


class Book:
    def __init__(self, inp: Inputs, r: dict, rules: dict, notes: list[str]):
        self.inp, self.r, self.rules, self.notes = inp, r, rules, notes
        self.wb = Workbook()
        self.addr: dict[str, str] = {}      # 이름 → 시트 포함 절대 주소
        self.engine: list[tuple] = []       # (항목, 엔진 값, 이름, 꼴)

    def a(self, name: str) -> str:
        return self.addr[name]

    # ------------------------------------------------------------ 0입력
    def sheet_input(self):
        ws = self.wb.active
        ws.title = S_IN
        row = X.title(ws, "0 입력", "노란 칸만 고친다. 입력 파일(창업감면_입력.xlsx 회사 시트)과 같은 값이다. 고쳤으면 입력 파일도 고친다")
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
            if kind.startswith("pick:") and kind != "pick:industry":     # 업종 목록은 255자를 넘어 목록 검사를 걸지 않는다(엑셀이 파일을 못 연다)
                items = [o for o in opts[kind[5:]] if o]
                dv = DataValidation(type="list", formula1='"' + ",".join(items) + '"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(c)
            X.cell(ws, row, 3, desc, wrap=True)
            self.addr["in:" + key] = f"{_q(S_IN)}$B${row}"
        X.widths(ws, [40, 26, 90])

    # ------------------------------------------------------------ 0기준
    def sheet_base(self):
        ws = self.wb.create_sheet(S_BASE)
        R = self.rules
        row = X.title(ws, "0 기준", "법령 값. 근거 조문 · 등급은 C 열(rules.yaml 과 같다)")
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

        def g(*path):
            v = R
            for p in path:
                v = v[p]
            return v

        put("deadline", "창업 기한", date.fromisoformat(g("period", "deadline", "value")), g("period", "deadline", "basis"), DATE_FMT)
        put("boundary", "감면율 시기 구분(이 날 이전 창업)", date.fromisoformat(g("rates", "boundary", "value")), g("rates", "boundary", "basis"), DATE_FMT)
        put("asset_max", "인수 자산 비율 한도", g("founding", "asset_ratio_max", "value"), g("founding", "asset_ratio_max", "basis"), RATE_FMT)
        put("age_from", "청년 나이 하한", g("youth", "age_from", "value"), g("youth", "age_from", "basis"))
        put("age_to", "청년 나이 상한", g("youth", "age_to", "value"), g("youth", "age_to", "basis"))
        put("mil_cap", "병역 개월 한도", g("youth", "military_cap_months", "value"), g("youth", "military_cap_months", "basis"))
        put("t2025", "소규모 수입금액 한도(2025 이전 개시 과세연도)", g("small", "threshold_2025", "value"), g("small", "threshold_2025", "basis"))
        put("t2026", "소규모 수입금액 한도(2026 이후 개시 과세연도)", g("small", "threshold_2026", "value"), g("small", "threshold_2026", "basis"))
        put("small_from", "소규모 새 한도 적용 개시일", date.fromisoformat(g("small", "from", "value")), g("small", "from", "basis"), DATE_FMT)
        put("ng_until", "신성장 서비스업(제5항) 창업 기한", date.fromisoformat(g("new_growth", "until")), g("new_growth", "basis"), DATE_FMT)
        put("emp_from", "제7항 · 제13항 개정규정 적용 창업일", date.fromisoformat(g("employment", "new_from", "value")),
            g("employment", "new_from", "basis"), DATE_FMT)
        put("staff_big", "업종별최소고용인원(광업 · 제조업 · 건설업 · 물류산업)", 10, g("industry", "min_staff", "basis"))
        put("staff_other", "업종별최소고용인원(그 밖)", 5, g("industry", "min_staff", "basis"))
        put("cap", "감면 한도(2025 이후 창업)", g("amount", "cap", "value"), g("amount", "cap", "basis"))
        row += 2
        X.cell(ws, row, 1, "감면율 표(창업 시기|지역)").font = Font(name=X.FONT, bold=True)
        row += 1
        X.header(ws, row, ["구분"] + list(HEADS))
        top = row + 1
        for key, rates in g("rates", "value").items():
            row += 1
            X.cell(ws, row, 1, key)
            for j, h in enumerate(HEADS):
                X.cell(ws, row, 2 + j, rates[h]).number_format = RATE_FMT
        X.cell(ws, row + 1, 1, g("rates", "basis"), wrap=True)
        self.addr["b:keys"] = f"{_q(S_BASE)}$A${top}:$A${row}"
        self.addr["b:table"] = f"{_q(S_BASE)}$B${top}:$E${row}"
        self.addr["b:heads"] = f"{_q(S_BASE)}$B${top - 1}:$E${top - 1}"
        X.widths(ws, [44, 16, 16, 16, 16])
        ws.column_dimensions["C"].width = 90

    # ------------------------------------------------------------ 1연도별
    def sheet_years(self):
        ws = self.wb.create_sheet(S_YEARS)
        row = X.title(ws, "1 연도별", "창업 뒤 과세연도마다 감면사업 소득금액 · 수입금액 · 상시근로자 수. 최초 소득 과세연도와 직전 인원을 여기서 찾는다")
        X.header(ws, row, ["과세연도 시작일", "과세연도 종료일", "감면사업 소득금액", "수입금액", "상시근로자 수"])
        top = row + 1
        for y in self.r["years"]:
            row += 1
            X.cell(ws, row, 1, y.start, kind="input").number_format = DATE_FMT
            X.cell(ws, row, 2, y.end, kind="input").number_format = DATE_FMT
            X.cell(ws, row, 3, y.income, kind="input", money=True)
            X.cell(ws, row, 4, y.revenue, kind="input", money=True)
            X.cell(ws, row, 5, y.staff, kind="input")
        end = max(row, top) + 10           # 줄을 더해도 수식이 잡도록 여유
        q = _q(S_YEARS)
        self.addr.update({"y:end": f"{q}$B${top}:$B${end}", "y:inc": f"{q}$C${top}:$C${end}", "y:staff": f"{q}$E${top}:$E${end}"})
        X.widths(ws, [18, 18, 20, 20, 16])

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
            if fmt == "date":
                c.number_format = DATE_FMT
            elif fmt == "rate":
                c.number_format = RATE_FMT
            elif fmt == "ratio":
                c.number_format = "0.0000"
            X.cell(ws, self._row, 3, basis, wrap=True)
            self.addr[name] = f"{_q(S_CALC)}$B${self._row}"
            if engine is not None or name in r:
                self.engine.append((label, r.get(name) if engine is None else engine, name, kind))

        def section(text):
            self._row += 2
            X.cell(ws, self._row, 1, text).font = Font(name=X.FONT, bold=True)

        fs, fe, found = I("과세연도 시작일"), I("과세연도 종료일"), I("창업일")
        section("1. 창업 해당(제6조 제1항 · 제3항 · 제10항 · 제11항)")
        put("c_deadline", "창업일이 기한 안", f"{found}<={B('deadline')}", "제6조 제1항", kind="bool")
        put("c_sme", "중소기업", f'AND({I("중소기업")}="Y",OR({I("중소기업 아니게 된 날")}="",{I("중소기업 아니게 된 날")}>{fe}))',
            "제6조 제1항 · 제11항", kind="bool")
        put("c_industry", "감면 업종", f'AND({I("업종")}<>"그 밖의 업종",{I("업종 단서 제외 업종")}="N")', "제6조 제3항", kind="bool")
        succ, asset = I("합병 · 분할 · 현물출자 · 사업양수로 종전 사업 승계"), I("종전 사업 자산 인수 · 매입")
        put("no1", "사업 승계 · 자산 인수로 창업 아님", f'AND(OR({succ}="Y",{asset}="Y"),NOT(OR(AND({asset}="Y",{succ}="N",'
            f'{I("인수 자산 비율")}<={B("asset_max")}),{I("사업 분리 임직원 창업")}="Y")))', "제6조 제10항 제1호, 시행령 제5조 제19항 ~ 제21항",
            kind="bool")
        put("c_founding", "창업에 해당", f'NOT(OR({N("no1")},{I("법인전환")}="Y",{I("폐업 후 같은 종류 사업 재개")}="Y",'
            f'{I("사업 확장 · 업종 추가")}="Y"))', "제6조 제10항", kind="bool")
        put("c_started", "창업일이 과세연도 종료일 이전", f"{found}<={fe}", kind="bool")

        section("2. 감면기간(최초 소득 과세연도부터 5개 과세연도)")
        ye, yi = self.a("y:end"), self.a("y:inc")
        put("start", "사업 개시일(비우면 창업일)", f'IF({I("사업 개시일")}<>"",{I("사업 개시일")},{found})', "제6조 제1항 괄호", "date",
            kind="date")
        put("day5", "사업 개시일부터 5년이 되는 날", f'EDATE({N("start")},60)-1', "개시일을 첫날로 센다", "date", kind="date")
        d5 = N("day5")
        put("inc_end", "소득이 처음 생긴 과세연도 종료일",
            f'IF(COUNTIFS({ye},">="&{found},{yi},">0")>0,_xlfn.AGGREGATE(15,6,{ye}/(({ye}>={found})*({yi}>0)),1),"")',
            "1연도별 감면사업 소득금액이 0 보다 큰 첫 과세연도", "date", kind="date")
        put("y5_end", "5년이 되는 날이 속하는 과세연도 종료일", f'IF(COUNTIFS({ye},">="&{d5})>0,_xlfn.AGGREGATE(15,6,{ye}/({ye}>={d5}),1),"")',
            "", "date", kind="date")
        inc, y5, given = N("inc_end"), N("y5_end"), I("최초 소득 발생 과세연도 종료일")
        put("first_end", "최초 소득 과세연도 종료일", f'IF({given}<>"",{given},IF({inc}="",{y5},IF({y5}="",{inc},MIN({inc},{y5}))))',
            "제6조 제1항: 소득이 처음 생긴 과세연도와 5년이 되는 날이 속하는 과세연도 중 이른 쪽", "date", kind="date")
        fi = N("first_end")
        put("term_end", "감면 끝 날", f'IF({fi}="","",EDATE({fi}+1,48)-1)', "그 다음 과세연도 개시일부터 4년 이내에 끝나는 과세연도까지", "date",
            kind="date")
        put("nth", "감면 차수", f'IF({fi}="",0,IF({fi}>{fe},0,ROUND(DATEDIF({fi},{fe},"m")/12,0)+1))')
        put("c_term", "감면기간 안", f'IF({fi}="",FALSE,AND({fi}<={fe},{fe}<={N("term_end")}))', kind="bool")
        put("eligible", "감면 대상", f'AND({N("c_deadline")},{N("c_sme")},{N("c_industry")},{N("c_founding")},{N("c_started")},{N("c_term")})',
            kind="bool")

        section("3. 청년창업중소기업(시행령 제5조 제1항 · 제2항)")
        birth = I("대표자 생년월일")
        put("birth_adj", "병역 기간을 늦춘 생년월일", f'IF({birth}="","",EDATE({birth},MIN({I("대표자 병역 개월 수")},{B("mil_cap")})))', "", "date",
            engine=self.r["birth_adj"] or "", kind="date")
        put("age", "창업 당시 만 나이", f'IF({birth}="","",DATEDIF({N("birth_adj")},{found},"y"))', engine=self.r["age"] if self.r["age"] is not None else "")
        put("youth", "청년창업", f'IF({birth}="",FALSE,AND({N("age")}>={B("age_from")},{N("age")}<={B("age_to")},{I("대표자 최대주주")}="Y"))',
            kind="bool")
        lost = I("청년 요건 상실일")
        put("youth_lost", "청년 요건 상실", f'AND({N("youth")},{lost}<>"",{lost}<={fe})', kind="bool")
        put("type", "구분", f'IF({N("youth_lost")},"청년상실",IF({N("youth")},"청년","일반"))', kind="text")

        section("4. 창업 시기 · 지역(제6조 제1항 제1호 가목 · 나목, 시행령 제5조 제25항)")
        put("era", "창업 시기", f'IF({found}<={B("boundary")},"2025이전","2026이후")', kind="text")
        mr, md, reg = I("이전 · 지점 지역"), I("이전 · 지점 설치일"), I("창업 지역")
        era = N("era")
        rank = lambda x: f'IF({x}="{REGIONS[0]}",0,IF({era}="2025이전",1,IF({x}="{REGIONS[1]}",1,2)))'  # noqa: E731
        put("moved_set", "이전 · 지점을 이 과세연도까지 둠", f'AND({mr}<>"",{md}<>"",{md}<={fe})', kind="bool")
        put("moved", "이전 · 지점 지역 적용(감면율이 더 낮을 때만)", f'AND({N("moved_set")},{rank(mr)}<{rank(reg)})',
            "시행령 제5조 제25항. 감면율 순서: 과밀억제권역 < 수도권(2026 이후 창업) < 수도권 밖 · 수도권 인구감소지역", kind="bool")
        put("region", "감면율을 정하는 지역", f'IF({N("moved")},{mr},{reg})', kind="text")
        put("key", "감면율 표 구분", f'{N("era")}&"|"&IF({N("region")}="{REGIONS[0]}","과밀",IF({N("era")}="2025이전","과밀외",'
            f'IF({N("region")}="{REGIONS[1]}","수도권","지방")))', kind="text")

        section("5. 소규모(제6항) · 신성장 서비스업(제5항)")
        put("fy_months", "과세연도 개월 수", f'MAX(1,DATEDIF({fs},{fe}+1,"m"))', "1개월 미만 끝수는 버림, 최소 1")
        put("revenue_year", "수입금액(1년 환산)", f'IF({N("fy_months")}<12,{I("수입금액")}*12/{N("fy_months")},{I("수입금액")})', "제6조 제6항 괄호",
            "won", engine=float(self.r["revenue_year"]))
        put("threshold", "소규모 수입금액 한도", f'IF({fs}>={B("small_from")},{B("t2026")},{B("t2025")})', "제6조 제6항, 부칙 <제21223호> 제2조", "won")
        put("small", "소규모 감면(제6항)", f'AND({N("type")}="일반",{N("revenue_year")}<={N("threshold")})', kind="bool")
        put("new_growth", "신성장 서비스업 감면(제5항)", f'AND({N("type")}="일반",NOT({N("small")}),{found}<={B("ng_until")},'
            f'{N("key")}="2025이전|과밀외",{I("신성장 서비스업")}="Y")', kind="bool")

        section("6. 감면율")
        tb, ks, hs = B("table"), B("keys"), B("heads")
        look = lambda h: f'INDEX({tb},MATCH({N("key")},{ks},0),MATCH({h},{hs},0))'  # noqa: E731
        put("rate_table", "표에서 고른 감면율", f'IF(OR({N("type")}="청년",{N("type")}="청년상실"),{look(N("type"))},IF({N("small")},'
            f'{look(chr(34) + "소규모" + chr(34))},IF({N("new_growth")},IF({N("nth")}<=3,0.75,0.5),{look(chr(34) + "일반" + chr(34))})))',
            "0기준 감면율 표", "rate", engine=float(self.r["rate_table"]))
        put("rate", "감면율(감면 대상일 때)", f'IF({N("eligible")},{N("rate_table")},0)', "", "rate", engine=float(self.r["rate"]))

        section("7. 고용증가 추가감면(제7항)")
        ind = I("업종")
        put("emp_new", "개정규정(2025 이후 창업)", f'{found}>={B("emp_from")}', "부칙 <제20617호> 제2조", kind="bool")
        put("min_staff", "업종별최소고용인원", f'IF(OR({ind}="광업",{ind}="제조업",{ind}="건설업",{ind}="물류산업"),{B("staff_big")},{B("staff_other")})',
            "시행령 제5조 제14항")
        ys = self.a("y:staff")
        idx = lambda d: f'INDEX({ys},MATCH({d},{ye},0))'                        # noqa: E731
        put("staff_cur", "상시근로자 수(해당)", f'IF({I("상시근로자 수(해당)")}<>"",{I("상시근로자 수(해당)")},'
            f'IFERROR(IF({idx(fe)}="","",{idx(fe)}),""))', engine=self.r["staff_cur"] if self.r["staff_cur"] is not None else "")
        zero = f'IF(AND({fs}<={found},{found}<={fe}),0,"")'                     # 창업한 과세연도면 0
        put("staff_prev", "상시근로자 수(직전)", f'IF({I("상시근로자 수(직전)")}<>"",{I("상시근로자 수(직전)")},'
            f'IFERROR(IF({idx(fs + "-1")}="",{zero},{idx(fs + "-1")}),{zero}))',
            "비우면 연도별 시트 직전 줄, 창업한 과세연도면 0(시행령 제5조 제17항 → 제23조 제13항 제1호)",
            engine=self.r["staff_prev"] if self.r["staff_prev"] is not None else "")
        put("emp_target", "추가감면 대상", f'IF({N("emp_new")},AND({N("rate")}>0,{N("rate")}<1),AND({N("type")}="일반",'
            f'RIGHT({N("key")},3)="과밀외",{N("rate")}>0,{N("rate")}<1))', "개정 제7항 / 종전 제7항(과밀억제권역 밖 일반 창업만)", kind="bool")
        put("staff_base", "기준 인원 max(직전, 업종별최소고용인원)", f'IF({N("staff_prev")}="","",MAX({N("staff_prev")},{N("min_staff")}))',
            engine=float(self.r["staff_base"]) if self.r.get("staff_base") is not None else "")
        sc, sb = N("staff_cur"), N("staff_base")
        put("add_rate", "추가감면율", f'IF(AND({N("emp_target")},{sc}<>"",{N("staff_prev")}<>""),IF(AND({sc}>={N("min_staff")},{sc}>{sb}),'
            f'ROUNDDOWN(ROUND(MIN(({sc}-{sb})/{sb}*IF({N("emp_new")},1,0.5),IF({N("rate")}=0.75,0.25,0.5)),9),2),0),0)',
            "한도 50%(75% 감면 연도 25%), 1% 미만 버림", "rate", engine=float(self.r["add_rate"]))

        section("8. 감면세액(법인세법 제59조 제2항)")
        put("inc_ratio", "감면소득 ÷ 과세표준(100% 한도)", f'IF(AND({I("과세표준")}>0,{I("감면소득")}>0),MIN(1,{I("감면소득")}/{I("과세표준")}),0)',
            "법인세법 제59조 제2항, 시행령 제96조", "ratio", engine=float(self.r["inc_ratio"]))
        put("tax_on_income", "감면소득에 대한 세액", f'{I("산출세액")}*{N("inc_ratio")}', "", "won", engine=float(self.r["tax_on_income"]))
        put("base_amt", "기본 감면세액", f'ROUNDDOWN(ROUND({N("tax_on_income")}*{N("rate")},4),0)', "원 미만 버림", "won")
        put("add_amt", "고용증가 추가감면세액", f'ROUNDDOWN(ROUND({N("tax_on_income")}*{N("add_rate")},4),0)', "", "won")
        put("o_7", "11O 대상세액(최저한세 적용제외)", f'IF({N("rate")}=1,{N("base_amt")},0)+{N("add_amt")}', "제132조 제1항 제4호 가목 · 나목", "won")
        put("t_7", "111 대상세액(최저한세 적용대상)", f'IF({N("rate")}=1,0,{N("base_amt")})', "", "won")

        section("9. 최저한세 · 5억원 한도 · 중복 배제")
        put("mt_base", "최저한세 과세표준", f'IF({I("최저한세 과세표준")}<>"",{I("최저한세 과세표준")},{I("과세표준")})', "", "won")
        put("min_tax", "최저한세액", f'ROUNDDOWN(ROUND({N("mt_base")}*{I("최저한세율")},4),0)', "제132조 제1항", "won")
        put("mt_room", "111 줄이 받을 수 있는 여지", f'MAX(0,{I("산출세액")}-{N("min_tax")}-{I("먼저 적용할 다른 최저한세 대상 감면 · 공제")})',
            "다른 대상 공제를 먼저 뺀다고 봄", "won")
        put("t_8", "111 감면세액(최저한세 반영)", f'MIN({N("t_7")},{N("mt_room")})', "", "won")
        put("o_8", "11O 감면세액", f'{N("o_7")}', "", "won")
        put("mt_cut", "최저한세로 감면하지 않은 금액", f'{N("t_7")}-{N("t_8")}', "", "won")
        put("cap_cut", "5억원 넘어 감면하지 않은 금액", f'IF({N("emp_new")},MAX(0,{N("o_8")}+{N("t_8")}-{B("cap")}),0)', "제6조 제13항", "won")
        put("t_9", "111 한도충족 감면세액", f'{N("t_8")}-MIN({N("t_8")},{N("cap_cut")})', "", "won")
        put("o_9", "11O 한도충족 감면세액", f'{N("o_8")}-({N("cap_cut")}-MIN({N("t_8")},{N("cap_cut")}))', "", "won")
        put("conflict_employ", "통합고용 · 고용증대와 함께 못 받음", f'AND({N("emp_new")},{I("통합고용 · 고용증대 세액공제")}>0)', "제127조 제4항 단서",
            kind="bool")
        put("other_sum", "함께 받지 못하는 공제감면 합계", f'IF({N("conflict_employ")},{I("통합고용 · 고용증대 세액공제")},0)+{I("제127조 제4항 세액공제")}'
            f'+{I("중소기업특별세액감면")}', "제127조 제4항 · 제5항", "won")
        put("chosen", "창업감면을 고름", f'{I("적용 선택")}="창업감면"', kind="bool")
        put("o_final", "신청 11O", f'IF({N("chosen")},{N("o_9")},0)', "", "won")
        put("t_final", "신청 111", f'IF({N("chosen")},{N("t_9")},0)', "", "won")
        put("total", "창업중소기업 세액감면 합계", f'{N("o_final")}+{N("t_final")}', "", "won")
        X.widths(ws, [40, 22, 70])

    # ------------------------------------------------------------ 3신청서
    def sheet_form(self):
        ws = self.wb.create_sheet(S_FORM)
        row = X.title(ws, "3 세액감면(면제)신청서", "조세특례제한법 시행규칙 별지 제2호서식(2026. 5. 22. 개정) ❸ 신청 내용 중 창업중소기업 줄과 합계")
        X.header(ws, row, ["구분", "근거법령", "코드", "⑥ 감면율", "⑦ 대상세액", "⑧ 감면세액", "⑨ 한도충족 감면세액"])
        N = self.a
        rows = [("창업중소기업에 대한 감면(최저한세 적용제외)", "11O", "o"), ("창업중소기업에 대한 감면(최저한세 적용대상)", "111", "t")]
        first = row + 1
        for label, code, p in rows:
            row += 1
            X.cell(ws, row, 1, label)
            X.cell(ws, row, 2, "영 제5조제26항")
            X.cell(ws, row, 3, code)
            rate = (f'=IF({N("o_7")}=0,"",IF({N("rate")}=1,{N("rate")}+{N("add_rate")},{N("add_rate")}))' if p == "o"
                    else f'=IF({N("t_7")}=0,"",{N("rate")})')
            X.cell(ws, row, 4, rate).number_format = RATE_FMT
            X.cell(ws, row, 5, f'=IF({N("chosen")},{N(p + "_7")},0)', money=True)
            X.cell(ws, row, 6, f'=IF({N("chosen")},{N(p + "_8")},0)', money=True)
            X.cell(ws, row, 7, f'={N(p + "_final")}', money=True)
        row += 1
        X.cell(ws, row, 1, "세액감면 합계", kind="total")
        X.cell(ws, row, 3, "1A4", kind="total")
        for col in (5, 6, 7):
            L = "EFG"[col - 5]
            X.cell(ws, row, col, f"=SUM({L}{first}:{L}{row - 1})", money=True, kind="total")
        self.addr["f:total"] = f"{_q(S_FORM)}$G${row}"
        self.addr["f:o7"], self.addr["f:o8"], self.addr["f:o9"] = (f"{_q(S_FORM)}${c}${first}" for c in "EFG")
        self.addr["f:t7"], self.addr["f:t8"], self.addr["f:t9"] = (f"{_q(S_FORM)}${c}${first + 1}" for c in "EFG")
        row += 2
        for text in ("작성방법 3: ⑦ 대상세액은 최저한세 적용 전 감면세액, 4: ⑧ 은 ⑦ 에서 최저한세 배제세액을 뺀 금액, "
                     "5: ⑨ 는 ⑧ 과 감면한도 중 적은 금액(창업감면은 제6조 제13항 5억원)",
                     "11O 감면율란: 100% 감면 연도는 기본 감면율 + 추가감면율, 그 밖에는 추가감면율. 추가감면분을 11O 에 적는 것은 엔진 규칙(제132조 제1항 제4호 나목)",
                     "상호 · 사업자등록번호 · 대표자 · 주소 · 날짜 · 서명은 사람이 적는다"):
            X.cell(ws, row, 1, text).font = X.NOTE_FONT
            row += 1
        X.widths(ws, [44, 16, 8, 12, 18, 18, 20])

    # ------------------------------------------------------------ 4엔진대조
    def sheet_check(self):
        ws = self.wb.create_sheet(S_CHECK)
        row = X.title(ws, "4 엔진 대조", "엔진(ctax startup)이 따로 계산한 값과 수식 값. 「불일치」 가 있으면 입력 칸이나 수식을 바꾼 것이다")
        X.header(ws, row, ["항목", "엔진 값", "수식 값", "결과"])
        top = row + 1
        for label, val, name, kind in self.engine:
            row += 1
            X.cell(ws, row, 1, label)
            if isinstance(val, Fraction):
                val = float(val)
            c = X.cell(ws, row, 2, val)
            c2 = X.cell(ws, row, 3, f"={self.a(name)}")
            if kind == "date":
                c.number_format = c2.number_format = DATE_FMT
            X.cell(ws, row, 4, f'=IF(AND(ISNUMBER(B{row}),ISNUMBER(C{row})),IF(ABS(C{row}-B{row})<0.005,"일치","불일치"),'
                               f'IF(C{row}&""=B{row}&"","일치","불일치"))')
        self.addr["k:res"] = f"{_q(S_CHECK)}$D${top}:$D${row}"
        X.widths(ws, [40, 18, 18, 10])

    # ------------------------------------------------------------ 목록
    def sheet_list(self):
        ws = self.wb.create_sheet(S_LIST, 0)
        N, I = self.a, lambda k: self.a("in:" + k)
        row = X.title(ws, "창업중소기업 세액감면 검증", f"{self.inp.values['과세연도 시작일']} ~ {self.inp.values['과세연도 종료일']} · "
                      "조세특례제한법 제6조 · ctax startup")
        X.header(ws, row, ["결과", "값", "", ""])
        for label, f, fmt in (("창업중소기업 세액감면(신청 합계)", N("total"), "won"), ("11O 최저한세 적용제외", N("o_final"), "won"),
                              ("111 최저한세 적용대상", N("t_final"), "won"), ("감면 대상", N("eligible"), None), ("구분", N("type"), None),
                              ("감면율 표 구분", N("key"), None), ("감면율", N("rate"), "rate"), ("추가감면율", N("add_rate"), "rate"),
                              ("감면 차수", N("nth"), None)):
            row += 1
            X.cell(ws, row, 1, label)
            c = X.cell(ws, row, 2, f"={f}", money=fmt == "won")
            if fmt == "rate":
                c.number_format = RATE_FMT
        row += 2
        X.header(ws, row, ["검산", "결과", "왼쪽", "오른쪽"])
        checks = [
            ("신청서 1A4 ⑨ = 2계산 합계", N("f:total"), N("total"), "="),
            ("11O ⑨ ≤ ⑧ ≤ ⑦", f"AND({N('f:o9')}<={N('f:o8')},{N('f:o8')}<={N('f:o7')})", "TRUE", "bool"),
            ("111 ⑨ ≤ ⑧ ≤ ⑦", f"AND({N('f:t9')}<={N('f:t8')},{N('f:t8')}<={N('f:t7')})", "TRUE", "bool"),
            ("감면세액 합계 ≤ 감면소득에 대한 세액", N("total"), N("tax_on_income"), "<="),
            ("감면율 + 추가감면율 ≤ 100%", f"{N('rate')}+{N('add_rate')}", "1", "<="),
            ("감면 후 111 이 최저한세를 지킴", f"{I('산출세액')}-{N('t_8')}", N("min_tax"), ">=t"),
            ("5억원 한도(2025 이후 창업)", N("total"), f"IF({N('emp_new')},{self.a('b:cap')},{N('total')})", "<="),
            ("엔진 대조 불일치 0건", f'COUNTIF({N("k:res")},"불일치")', "0", "="),
        ]
        for label, left, right, op in checks:
            row += 1
            X.cell(ws, row, 1, label)
            if op == "bool":
                ok = f"={left}"
            elif op == "=":
                ok = f"=ABS(({left})-({right}))<0.005"
            elif op == ">=t":                  # 111 이 없거나 이미 산출세액이 최저한세보다 작으면 깎을 것이 없다
                ok = f"=OR({N('t_8')}=0,({left})>=({right}))"
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
        self.sheet_years()
        self.sheet_calc()
        self.sheet_form()
        self.sheet_check()
        self.sheet_list()
        return self.wb


def build(inp: Inputs, r: dict, rules: dict, notes: list[str]) -> tuple[Workbook, list]:
    b = Book(inp, r, rules, notes)
    wb = b.build()
    return wb, b.engine
