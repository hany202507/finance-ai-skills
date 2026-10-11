# -*- coding: utf-8 -*-
"""서식 검산. 신고값(C8)의 서식 값이 서로 맞는지, 엔진 결과(C4)와 맞는지를 따로 다시 검사한다.

신고값 생성기(return_values), 서식 렌더러(forms, forms_pdf)를 부르지 않는다. 신고값이 틀린 채로 서식 PDF와 전자신고 파일이
만들어지는 것을 막으려는 검사라서, 생성기와 같은 코드를 쓰면 같이 틀린다. 읽는 표는 셋이다.
  efile/codes_c116300.json 의 필요경비구분: 부표3 행의 전자코드가 취득가액·차감·기타필요경비 중 어느 묶음인지(코드 앞자리로 가르지 않는다)
  forms/서식판.json 의 부표1_장특공코드: 판정의 장특공(없음·표1·표2)에 맞는 부표1 ⑯ 코드
  rules/ruleset.json: 분납 기준금액·상한, 전자신고세액공제 금액(엔진과 같이 규칙세트에서만 읽는다)

    forms_check.check(rv, result) -> [실패 문장]      빈 목록이면 통과

검사하는 것:
  인적사항 필수 칸    신고인 성명·주민등록번호·주소, 양수인(성명·번호·지분 합 1), 부표1 소재지·양도일·취득일
  부표3               행의 전자코드·구분코드, 취득가액 묶음 합 = ⑤ 계, 기타필요경비 묶음 합 = ⑬ 계
  부표3 → 부표1       ⑤ 계 = ⑫ 취득가액, ⑬ 계 = ⑭ 기타 필요경비, 실지거래가액 자산에는 부표3이 있어야 한다
  부표1 행 산식       양도차익 = ⑪-⑫-⑬-⑭, ⑮ = 양도차익-비과세양도차익, ⑱ = ⑮-⑯, 합계 행 = 자산 행 합, ⑦ 양도면적 = ⑥ 총면적 × 지분
  부표1 → 본지        부표1 ⑱ 합 = 본지 ④(합계, 세율구분 열별, 국내소계)
  본지 산식           ⑧ = ④+⑤-⑥-⑦, ⑯ 계, ⑱ = ⑩-⑪-⑫-⑬-⑭-⑮+⑯-⑰, ⑳ = ⑱-⑲, ⑲ 분납 한도, ⑮ 전자신고세액공제(합계 열은 기대값과 같아야 하고 다른 열은 한도 이하)
                      합계 열의 ⑰~⑳(지방은 납부할 총세액·신고기한내 납부)은 비어 있으면 실패
  세율구분 열 합      합계 열·국내소계 = 세율구분 열의 합. 합산 비교세액이 이기면 합계 열의 ⑩·⑮·⑱~⑳ 은 열 합과 다르다(빼고 본다)
  본지 → 지방         지방 과세표준 = 본지 ⑧(열마다), 지방 납부할 세액 산식, 지방 열 합
  엔진 대조           자산별 양도일·취득일·양도가액·양도차익·비과세양도차익·과세양도차익·장특공·양도소득금액, 취득가액+필요경비,
                      지분으로 나눈 양도가액, 서식에 옮겨 적은 자산종류·장특공 코드·취득가액종류,
                      합계 과세표준·산출세액·지방소득세, 세율구분 열별 과세표준·산출세액·양도소득금액·기본공제

검산하지 않는 것: ⑨ 세율 표기, ⑨⑩ 보유·거주기간 글자, 부표3 상호·사업자번호·지급일·증빙코드, 양도·취득 원인, 신고 절의 코드와 날짜.
세율과 기간 글자는 생성기의 표기 규칙을 되풀이해야 해서 뺐고(세액은 엔진과 대조한다), 나머지는 전자신고 파일 검증기(efile_check)가 본다.
감면율은 감면이 이번 신고 범위가 아니라 항상 0 이다.

열의 칸이 None 이면 서식에서 비워 두는 칸이다. 합하지 않고 산식에도 넣지 않는다(세율구분 열이 여럿이면 열의 ⑰~⑳ 이 비어 있다).
합산 비교세액이 이기는지는 신고값이 아니라 엔진 결과로 정한다.

문장은 「부표1 ⑱ 합계 155,893,335 ≠ 본지 ④ 155,893,334」 꼴이다. 성명, 주민등록번호, 양수인 번호, 소재지, 상호 같은
인적사항 값은 문장에 넣지 않는다. 칸 이름과 금액, 코드, 자산 id 만 쓴다.
"""
import json
import os
from decimal import ROUND_DOWN, Decimal
from fractions import Fraction

from yangdo import SKILL_DIR, ruleset

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
FORMS_DIR = os.path.join(SKILL_DIR, "forms")
CODES_FILE = "codes_c116300.json"
# 부표1 취득가액 종류 칸에 적는 말. 엔진 취득가액방법 → 서식 표기(전액비과세 자산은 취득가액을 정하지 않아 빈 글자)
ACQ_LABEL = {"실지거래가액": "실지거래가액", "매매사례가액": "매매사례가액", "감정가액": "감정가액", "환산가액": "환산취득가액"}

# 본지(별지 84) 금액 칸. (신고값 키, 서식 번호, 이름)
NAT = (("양도소득금액", "④", "양도소득금액"), ("기신고양도소득금액", "⑤", "기신고 양도소득금액"),
       ("감면소득금액", "⑥", "감면소득금액"), ("기본공제", "⑦", "기본공제"), ("과세표준", "⑧", "과세표준"),
       ("산출세액", "⑩", "산출세액"), ("감면세액", "⑪", "감면세액"), ("외국납부", "⑫", "외국납부세액공제"),
       ("원천징수", "⑬", "원천징수세액공제"), ("연금계좌", "⑭", "연금계좌세액공제"), ("전자신고공제", "⑮", "전자신고세액공제"),
       ("가산세", "⑯", "가산세 계"), ("기신고세액", "⑰", "기신고세액"), ("납부할세액", "⑱", "납부할 세액"),
       ("분납", "⑲", "분납할 세액"), ("신고기한내납부", "⑳", "납부세액"))
# 지방소득세(별지 40의11) 금액 칸
LOCAL = (("과세표준", "⑤", "과세표준"), ("산출세액", "⑦", "산출세액"), ("감면세액", "⑧", "감면세액"),
         ("외국납부", "⑨", "외국납부세액공제"), ("원천징수", "⑩", "특별징수세액공제"), ("연금계좌", "⑪", "연금계좌세액공제"),
         ("전자신고공제", "⑫", "전자신고세액공제"), ("가산세", "⑬", "가산세 합계"), ("기신고세액", "⑭", "기신고세액"),
         ("납부할세액", "⑮", "납부할 총세액"), ("신고기한내납부", "", "신고기한내 납부"))
# 합계 열은 납부 칸이 반드시 숫자여야 한다. 세율구분 열·소계의 납부 칸은 비워 두는 것이 정상이다(서식 열 납부 행 계약)
NAT_TOTAL_REQUIRED = ("기신고세액", "납부할세액", "분납", "신고기한내납부")
LOCAL_TOTAL_REQUIRED = ("납부할세액", "신고기한내납부")
# 합산 비교세액이 이기면 합계 열이 세율구분 열의 합과 달라지는 칸(산출세액과 그에 딸린 칸)
NAT_WIN = ("산출세액", "전자신고공제", "납부할세액", "분납", "신고기한내납부")
LOCAL_WIN = ("산출세액", "전자신고공제", "납부할세액", "신고기한내납부")
NAT_PENALTY = ("가산세_신고", "가산세_납부", "가산세_기장")
LOCAL_PENALTY = ("가산세_신고", "가산세_납부", "가산세_기타")

# 부표1 행 금액 칸. (신고값 키, 서식 번호, 이름)
SHEET1_MONEY = (("양도가액", "⑪", "양도가액"), ("취득가액", "⑫", "취득가액"), ("토초세", "⑬", "기납부 토지초과이득세"),
                ("기타필요경비", "⑭", "기타 필요경비"), ("양도차익", "", "양도차익"), ("비과세양도차익", "", "비과세양도차익"),
                ("과세양도차익", "⑮", "과세대상양도차익"), ("장특공", "⑯", "장기보유특별공제"),
                ("양도소득금액", "⑱", "양도소득금액"), ("감면소득금액", "⑳", "감면소득금액"))


# ---------------------------------------------------------------- 낱개 도우미

def _i(x):
    """칸 값 → 정수. 빈 칸(None)은 0."""
    return 0 if x is None else int(x)


def _w(x):
    """문장에 쓰는 값. 정수는 천 단위 쉼표, 빈 칸은 「빈칸」."""
    if x is None or x == "":
        return "빈칸"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return format(x, ",")
    return str(x)


def _blank(x):
    return x is None or (isinstance(x, str) and not x.strip())


def _iso(s):
    """YYYYMMDD → YYYY-MM-DD. 이미 그 꼴이면 그대로."""
    s = str(s)
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]) if len(s) == 8 and s.isdigit() else s


def _col(name):
    return name if name in ("합계", "국내소계", "국외소계") else name + " 열"


def _group(entry):
    """필요경비구분 한 항목 → 취득 | 차감 | 기타 | None. 코드표의 묶음 이름으로 가른다."""
    g = entry.get("묶음") or ""
    if g.startswith("취득가액"):
        return "차감" if "차감항목" in g else "취득"
    if g.startswith("기타필요경비"):
        return "기타"
    return None


def _expense_table(efile_dir):
    with open(os.path.join(efile_dir, CODES_FILE), encoding="utf-8") as f:
        table = json.load(f)["필요경비구분"]
    return {v["전자코드"]: v for v in table.values()}


class _Check:
    def __init__(self, rv, result, rules_dir, efile_dir, forms_dir):
        self.rv, self.result = rv, result
        self.rules_dir = rules_dir
        self.efile_dir = efile_dir or EFILE_DIR
        self.forms_dir = forms_dir or FORMS_DIR
        self.out = []
        self._rs = None
        self._rs_failed = False
        self.calc = (result or {}).get("계산") or {}
        self.eng = {r["id"]: r for r in self.calc.get("자산") or []}
        total = self.calc.get("합계") or {}
        # 합산 비교세액이 이기는지는 엔진 결과로 정한다
        self.nat_win = total.get("합산비교세액", 0) > total.get("호별합산세액", 0)
        self.local_win = total.get("지방_합산비교", 0) > total.get("지방_호별합산", 0)

    # ------------------------------------------------------------ 공통

    def fail(self, text):
        if text not in self.out:
            self.out.append(text)

    def same(self, a, b, left, right):
        if _i(a) != _i(b):
            self.fail("%s %s ≠ %s %s" % (left, _w(a), right, _w(b)))

    def rules(self):
        """규칙세트. 못 읽으면 한 번만 알리고 None."""
        if self._rs is None and not self._rs_failed:
            try:
                self._rs = ruleset.load(self.rules_dir)
            except ruleset.RuleError:
                self._rs_failed = True
                self.fail("규칙세트를 읽지 못해 분납 한도와 전자신고세액공제 한도를 검사하지 못했다")
        return self._rs

    def rule(self, key, on):
        rs = self.rules()
        if rs is None:
            return None
        try:
            return rs.value(key, on)
        except ruleset.RuleError:
            self.fail("규칙세트에 %s 의 %s 값이 없어 한도를 검사하지 못했다" % (key, on))
            return None

    def asset_ids(self):
        return [x["자산"] for x in self.rv["부표1"]]

    def is_exempt(self, aid):
        e = self.eng.get(aid)
        return bool(e and e["판정"].get("전액비과세"))

    def column(self, form, cols, name):
        c = cols.get(name)
        if c is None:
            self.fail("%s 열 목록에 %s 열이 없다" % (form, name))
        return c

    def run(self):
        if not self.result or self.result.get("상태") != "완료" or not self.calc:
            return ["엔진 결과가 완료 상태가 아니라 서식 값을 엔진과 대조하지 못했다"]
        steps = (("신고인·양수인", self.required), ("부표3", self.schedule3), ("부표1", self.schedule1),
                 ("본지", self.main), ("지방", self.local), ("엔진 대조(부표1)", self.engine_assets),
                 ("엔진 대조(본지)", self.engine_main), ("엔진 대조(지방)", self.engine_local))
        for name, step in steps:
            try:
                step()
            except (KeyError, TypeError, AttributeError, ValueError, IndexError, OSError) as e:
                what = type(e).__name__ + (" " + str(e.args[0]) if isinstance(e, KeyError) and e.args else "")
                self.fail("%s 검사를 하지 못했다. 신고값에 필요한 칸이 없거나 모양이 다르다(%s)" % (name, what))
        return self.out

    # ------------------------------------------------------------ 필수 칸

    def required(self):
        rv = self.rv
        p = rv.get("신고인") or {}
        if _blank(p.get("성명")):
            self.fail("본지 ① 신고인 성명이 비어 있다")
        if _blank(p.get("주민등록번호")):
            self.fail("본지 ① 신고인 주민등록번호가 비어 있다")
        addr = p.get("주소") or {}
        if not any(not _blank(addr.get(k)) for k in ("시도", "시군구", "읍면동")):
            self.fail("본지 ① 신고인 주소가 비어 있다")
        ids = self.asset_ids()
        buyers = rv.get("양수인") or []
        for b in buyers:
            if b.get("자산") not in ids:
                self.fail("본지 ② 양수인의 자산 %s 가 부표1 에 없다" % _w(b.get("자산")))
        for aid in ids:
            mine = [b for b in buyers if b.get("자산") == aid]
            if not mine:
                self.fail("본지 ② 양수인이 없다(자산 %s)" % aid)
                continue
            share = Fraction(0)
            for b in mine:
                if _blank(b.get("성명")):
                    self.fail("본지 ② 양수인 성명이 비어 있다(자산 %s)" % aid)
                if _blank(b.get("번호")):
                    self.fail("본지 ② 양수인 번호가 비어 있다(자산 %s)" % aid)
                if not b.get("지분분모") or b.get("지분분자") is None:
                    self.fail("본지 ② 양수인 지분이 비어 있다(자산 %s)" % aid)
                else:
                    share += Fraction(int(b["지분분자"]), int(b["지분분모"]))
            if share != 1:
                self.fail("본지 ② 양수인 지분 합 %s ≠ 1 (자산 %s)" % (share, aid))
        for row in rv["부표1"]:
            aid = row["자산"]
            for key, no, name in (("소재지", "②", "소재지"), ("양도일", "④", "양도일"), ("취득일", "⑤", "취득일")):
                if _blank(row.get(key)):
                    self.fail("부표1 %s %s %s가 비어 있다" % (aid, no, name))

    # ------------------------------------------------------------ 부표3

    def schedule3(self):
        table = _expense_table(self.efile_dir)
        rows1 = {x["자산"]: x for x in self.rv["부표1"]}
        seen = set()
        for s in self.rv["부표3"]:
            aid = s["자산"]
            if aid in seen:
                self.fail("부표3 이 자산 %s 에 둘 이상 있다" % aid)
            seen.add(aid)
            row1 = rows1.get(aid)
            if row1 is None:
                self.fail("부표3 의 자산 %s 가 부표1 에 없다" % aid)
            acq = other = 0
            for x in s["행"]:
                e = table.get(x["전자코드"])
                if e is None:
                    self.fail("부표3 %s 구분 전자코드 %s 가 코드표에 없다" % (aid, _w(x["전자코드"])))
                    continue
                if x["구분코드"] != e["코드"]:
                    self.fail("부표3 %s 구분코드 %s 가 전자코드 %s 의 코드 %s 와 다르다"
                              % (aid, _w(x["구분코드"]), x["전자코드"], e["코드"]))
                if x.get("구분") != e["이름"]:
                    self.fail("부표3 %s 전자코드 %s 의 구분 이름이 코드표와 다르다" % (aid, x["전자코드"]))
                g = _group(e)
                if g == "취득":
                    acq += _i(x["금액"])
                elif g == "차감":
                    acq -= _i(x["금액"])
                elif g == "기타":
                    other += _i(x["금액"])
                else:
                    self.fail("부표3 %s 전자코드 %s 의 묶음을 알 수 없다" % (aid, x["전자코드"]))
            self.same(s["취득가액계"], acq, "부표3 %s ⑤ 계" % aid, "행 합")
            self.same(s["기타필요경비계"], other, "부표3 %s ⑬ 기타 필요경비 계" % aid, "행 합")
            if row1 is not None:
                self.same(s["취득가액계"], row1["취득가액"], "부표3 %s ⑤ 계" % aid, "부표1 %s ⑫ 취득가액" % aid)
                self.same(s["기타필요경비계"], row1["기타필요경비"], "부표3 %s ⑬ 기타 필요경비 계" % aid,
                          "부표1 %s ⑭ 기타 필요경비" % aid)
        for aid, e in self.eng.items():
            if e["계산"].get("취득가액방법") == "실지거래가액" and aid not in seen and aid in rows1:
                self.fail("부표1 %s ⑫ 취득가액이 실지거래가액인데 부표3 이 없다" % aid)

    # ------------------------------------------------------------ 부표1

    def schedule1(self):
        rows = self.rv["부표1"]
        for r in rows:
            aid = r["자산"]
            if self.is_exempt(aid):
                if _i(r.get("과세양도차익")) or _i(r.get("장특공")) or _i(r.get("양도소득금액")):
                    self.fail("부표1 %s 전액비과세 자산인데 ⑮ 과세대상양도차익 %s, ⑯ 장기보유특별공제 %s, ⑱ 양도소득금액 %s 이 0 이 아니다"
                              % (aid, _w(r.get("과세양도차익")), _w(r.get("장특공")), _w(r.get("양도소득금액"))))
                continue
            gain = _i(r.get("양도가액")) - _i(r.get("취득가액")) - _i(r.get("토초세")) - _i(r.get("기타필요경비"))
            self.same(r.get("양도차익"), gain, "부표1 %s 양도차익" % aid, "⑪-⑫-⑬-⑭")
            taxable = _i(r.get("양도차익")) - _i(r.get("비과세양도차익"))
            self.same(r.get("과세양도차익"), taxable, "부표1 %s ⑮ 과세대상양도차익" % aid, "양도차익-비과세양도차익")
            income = _i(r.get("과세양도차익")) - _i(r.get("장특공"))
            self.same(r.get("양도소득금액"), income, "부표1 %s ⑱ 양도소득금액" % aid, "⑮-⑯")

        for r in rows:
            self.area_share(r)

        # 합계 행 = 자산 행 합
        total = self.rv["부표1합계"]
        for key, no, name in SHEET1_MONEY:
            self.same(total.get(key), sum(_i(r.get(key)) for r in rows), "부표1 합계 행 %s%s" % (no + " " if no else "", name),
                      "자산 행 합")
        for k, v in (total.get("기준시가") or {}).items():
            self.same(v, sum(_i((r.get("기준시가") or {}).get(k)) for r in rows), "부표1 합계 행 기준시가 %s" % k, "자산 행 합")

        # 부표1 ⑱ → 본지 ④
        main = self.rv["본지"]["열"]
        labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        income_sum = sum(_i(r.get("양도소득금액")) for r in rows)
        if "합계" in main:
            self.same(income_sum, main["합계"].get("양도소득금액"), "부표1 ⑱ 합계", "본지 ④")
        taxed = [r for r in rows if not self.is_exempt(r["자산"])]
        for r in taxed:
            if r.get("세율구분표기") not in labels:
                self.fail("부표1 %s ① 세율구분 %s 에 해당하는 본지 열이 없다" % (r["자산"], _w(r.get("세율구분표기"))))
        for label in labels:
            if label in main:
                self.same(sum(_i(r.get("양도소득금액")) for r in taxed if r.get("세율구분표기") == label),
                          main[label].get("양도소득금액"), "부표1 ⑱ %s 열 합" % label, "본지 %s 열 ④" % label)
        if "국내소계" in main:
            self.same(sum(_i(r.get("양도소득금액")) for r in taxed if str(r.get("세율구분표기")).startswith("1-")),
                      main["국내소계"].get("양도소득금액"), "부표1 ⑱ 국내분 합", "본지 국내소계 ④")

    def area_share(self, r):
        """⑦ 양도면적 = ⑥ 총면적 × 양도 지분. 면적은 소수 셋째 자리까지 쓰므로 0.001 미만 차이는 같게 본다."""
        if r.get("지분분자") is None or not r.get("지분분모"):
            self.fail("부표1 %s 양도 지분이 비어 있다" % r["자산"])
            return
        share = Fraction(int(r["지분분자"]), int(r["지분분모"]))
        for kind in ("토지", "건물"):
            total, sold = Fraction(str(r.get("총면적_" + kind) or 0)), Fraction(str(r.get("양도면적_" + kind) or 0))
            if abs(total * share - sold) >= Fraction(1, 1000):
                self.fail("부표1 %s ⑦ 양도면적 %s %s ≠ ⑥ 총면적 %s × 지분 %s" % (r["자산"], kind, float(sold), float(total), share))

    def check_labels(self, form, labels):
        for x in labels:
            if x["표기"] != "%s-%s" % (x["국내외분"], x["세율구분"]):
                self.fail("%s 세율구분 표기 %s ≠ 국내외분 %s, 세율구분 %s" % (form, x["표기"], x["국내외분"], x["세율구분"]))

    # ------------------------------------------------------------ 본지

    def main(self):
        form = self.rv["본지"]
        cols = form["열"]
        self.check_labels("본지", form["세율구분"])
        labels = [x["표기"] for x in form["세율구분"]]
        names = ["합계", "국내소계"] + labels + ["국외소계"]
        for n in names:
            c = self.column("본지", cols, n)
            if c is not None:
                self.main_column(n, c)
        self.sums("본지", cols, labels, NAT, NAT_WIN, self.nat_win)
        self.payment_limits(cols, [n for n in names if n in cols])

    def total_payment_filled(self, form, c, keys, table):
        """합계 열의 납부 칸이 비어 있으면 알린다. 비어 있으면 산식 검사를 건너뛰어 틀린 값을 놓치기 때문이다."""
        names = {key: (no, name) for key, no, name in table}
        for key in keys:
            if c.get(key) is None:
                no, name = names[key]
                self.fail("%s 합계 %s%s 칸이 비어 있다(합계 열의 납부 칸은 숫자여야 한다)" % (form, no + " " if no else "", name))

    def main_column(self, n, c):
        cn = "본지 " + _col(n)
        if n == "합계":
            self.total_payment_filled("본지", c, NAT_TOTAL_REQUIRED, NAT)
        base = _i(c.get("양도소득금액")) + _i(c.get("기신고양도소득금액")) - _i(c.get("감면소득금액")) - _i(c.get("기본공제"))
        self.same(c.get("과세표준"), base, cn + " ⑧ 과세표준", "④+⑤-⑥-⑦")
        self.same(c.get("가산세"), sum(_i(c.get(k)) for k in NAT_PENALTY), cn + " ⑯ 가산세 계", "세 칸 합")
        if c.get("납부할세액") is not None:
            due = (_i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                   - _i(c.get("연금계좌")) - _i(c.get("전자신고공제")) + _i(c.get("가산세")) - _i(c.get("기신고세액")))
            self.same(c.get("납부할세액"), due, cn + " ⑱ 납부할 세액", "⑩-⑪-⑫-⑬-⑭-⑮+⑯-⑰")
            if c.get("분납") is not None and c.get("신고기한내납부") is not None:
                self.same(c.get("신고기한내납부"), _i(c.get("납부할세액")) - _i(c.get("분납")), cn + " ⑳ 납부세액", "⑱-⑲")

    def sums(self, form, cols, labels, keys, win_keys, win):
        """소계와 합계 열이 세율구분 열의 합과 같은가. 열의 칸이 None 이면 그 칸은 합하지 않는다."""
        groups = (("국내소계", [x for x in labels if x.startswith("1")]), ("국외소계", [x for x in labels if not x.startswith("1")]),
                  ("합계", labels))
        for sub, members in groups:
            if sub not in cols:
                continue
            for key, no, name in keys:
                vals = [cols[x].get(key) for x in members if x in cols]
                if any(v is None for v in vals) or cols[sub].get(key) is None:
                    continue
                if sub == "합계" and win and key in win_keys:
                    continue
                self.same(cols[sub].get(key), sum(_i(v) for v in vals), "%s %s %s%s" % (form, sub, no + " " if no else "", name),
                          "세율구분 열 합")

    def filing_credit(self, cols, names, kind, sin):
        """⑮ 전자신고세액공제. 합계 열은 기대값과 같아야 하고(빠뜨려도 잡는다), 다른 열은 기대값 이하이면 된다.
        기대값은 예정신고 min(규칙세트 금액, ⑩-⑪-⑫-⑬-⑭) (음수면 0), 확정신고 0. 확정신고에서는 규칙 키를 부르지 않는다."""
        if kind == "예정":
            cap, why = self.rule("전자신고세액공제.예정", _iso(sin["작성일"])), "예정신고 한도"
        else:
            cap, why = 0, "확정신고에는 전자신고세액공제가 없다"
        for n in names:
            c = cols[n]
            got = _i(c.get("전자신고공제"))
            if n != "합계" and got == 0:
                continue
            room = max(0, _i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                       - _i(c.get("연금계좌")))
            if got < 0:
                self.fail("본지 %s ⑮ 전자신고세액공제 %s 가 음수다" % (_col(n), _w(c.get("전자신고공제"))))
            elif cap is None:
                continue
            elif n == "합계" and got != min(int(cap), room):
                self.fail("본지 합계 ⑮ 전자신고세액공제 %s ≠ %s (%s %s, 산출세액에서 ⑪~⑭ 를 뺀 %s)"
                          % (_w(c.get("전자신고공제")), _w(min(int(cap), room)), why, _w(int(cap)), _w(room)))
            elif n != "합계" and got > min(int(cap), room):
                self.fail("본지 %s ⑮ 전자신고세액공제 %s 이 한도 %s 를 넘는다(%s, 산출세액에서 ⑪~⑭ 를 뺀 %s)"
                          % (_col(n), _w(c.get("전자신고공제")), _w(min(int(cap), room)), why, _w(room)))

    def payment_limits(self, cols, names):
        """⑮ 전자신고세액공제와 ⑲ 분납 한도. 한도는 규칙세트 값이다. 확정신고의 ⑮ 는 규칙을 부르지 않고 0 으로 본다.
        분납 규칙은 ⑲ 에 값이 있는 칸이 있을 때만 읽는다."""
        sin = self.rv["신고"]
        kind = sin["구분"]
        if kind not in ("예정", "확정"):
            self.fail("신고 구분 %s 이 예정이나 확정이 아니다" % _w(kind))
        if kind in ("예정", "확정"):
            self.filing_credit(cols, names, kind, sin)
        installments = [n for n in names if _i(cols[n].get("분납")) != 0]
        if not installments:
            return
        on = _iso(sin["양도일자"])
        base, top, rate = (self.rule("분납.기준금액", on), self.rule("분납.상한기준", on), self.rule("분납.상한율", on))
        for n in installments:
            c = cols[n]
            inst, due = _i(c.get("분납")), _i(c.get("납부할세액"))
            if inst < 0:
                self.fail("본지 %s ⑲ 분납할 세액 %s 가 음수다" % (_col(n), _w(inst)))
                continue
            if "분납신청" in sin and not sin["분납신청"]:
                self.fail("본지 %s ⑲ 분납할 세액 %s 인데 신고에서 분납을 신청하지 않았다" % (_col(n), _w(inst)))
            if base is None or top is None or rate is None:
                continue
            if due <= int(base):
                limit = 0
            elif due <= int(top):
                limit = due - int(base)
            else:
                limit = int((Decimal(due) * Decimal(str(rate))).to_integral_value(rounding=ROUND_DOWN))
            if inst > limit:
                self.fail("본지 %s ⑲ 분납할 세액 %s 이 한도 %s 를 넘는다(⑱ 납부할 세액 %s)" % (_col(n), _w(inst), _w(limit), _w(due)))

    # ------------------------------------------------------------ 지방

    def local(self):
        form = self.rv["지방"]
        cols = form["열"]
        main = self.rv["본지"]["열"]
        self.check_labels("지방", form["세율구분"])
        labels = [x["표기"] for x in form["세율구분"]]
        main_labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        if labels != main_labels:
            self.fail("지방 세율구분 열 %s 이 본지 %s 와 다르다" % (", ".join(labels) or "없음", ", ".join(main_labels) or "없음"))
        names = ["합계", "국내소계"] + labels + ["국외소계"]
        for n in names:
            c = self.column("지방", cols, n)
            if c is None:
                continue
            cn = "지방 " + _col(n)
            if n == "합계":
                self.total_payment_filled("지방", c, LOCAL_TOTAL_REQUIRED, LOCAL)
            m = main.get(n)
            if m is not None:
                self.same(c.get("과세표준"), m.get("과세표준"), cn + " ⑤ 과세표준", "본지 %s ⑧" % _col(n))
            self.same(c.get("가산세"), sum(_i(c.get(k)) for k in LOCAL_PENALTY), cn + " ⑬ 가산세 합계", "세 칸 합")
            if c.get("납부할세액") is not None:
                due = (_i(c.get("산출세액")) - _i(c.get("감면세액")) - _i(c.get("외국납부")) - _i(c.get("원천징수"))
                       - _i(c.get("연금계좌")) - _i(c.get("전자신고공제")) + _i(c.get("가산세")) - _i(c.get("기신고세액")))
                self.same(c.get("납부할세액"), due, cn + " ⑮ 납부할 총세액", "⑦-⑧-⑨-⑩-⑪-⑫+⑬-⑭")
                if c.get("신고기한내납부") is not None:
                    self.same(c.get("신고기한내납부"), c.get("납부할세액"), cn + " 신고기한내 납부", "⑮ 납부할 총세액")
        self.sums("지방", cols, labels, LOCAL, LOCAL_WIN, self.local_win)

    # ------------------------------------------------------------ 엔진 대조

    def engine_assets(self):
        rows = self.rv["부표1"]
        ids = [r["자산"] for r in rows]
        eng_ids = [r["id"] for r in self.calc["자산"]]
        if ids != eng_ids:
            self.fail("부표1 자산 [%s] ≠ 엔진 자산 [%s]" % (", ".join(ids), ", ".join(eng_ids)))
        for r in rows:
            e = self.eng.get(r["자산"])
            if e is None:
                continue
            aid, v, c = r["자산"], e["판정"], e["계산"]
            for key, label, no in (("양도일", "양도일", "④"), ("취득일", "취득일", "⑤")):
                if r.get(key) != v.get(key):
                    self.fail("부표1 %s %s %s %s ≠ 엔진 %s" % (aid, no, label, _w(r.get(key)), _w(v.get(key))))
            for key, no, name in (("양도가액", "⑪", "양도가액"), ("양도차익", "", "양도차익"), ("비과세양도차익", "", "비과세양도차익"),
                                  ("과세양도차익", "⑮", "과세양도차익"), ("장특공", "⑯", "장기보유특별공제"),
                                  ("양도소득금액", "⑱", "양도소득금액")):
                if c.get(key) is not None:                      # 전액비과세 자산은 양도차익·비과세양도차익이 비어 있다
                    self.same(r.get(key), c[key], "부표1 %s %s%s" % (aid, no + " " if no else "", name), "엔진")
            if c.get("취득가액") is not None:
                self.same(_i(r.get("취득가액")) + _i(r.get("기타필요경비")), _i(c["취득가액"]) + _i(c.get("필요경비")),
                          "부표1 %s ⑫ 취득가액 + ⑭ 기타필요경비" % aid, "엔진 취득가액 + 필요경비")
            self.engine_codes(r, v, c)
            if r.get("지분분모") and r.get("지분분자") is not None and c.get("전체양도가액") is not None:
                mine = Fraction(int(r["지분분자"]), int(r["지분분모"])) * Fraction(int(c["전체양도가액"]))
                self.same(mine.numerator // mine.denominator, c["양도가액"],
                          "부표1 %s 지분 %s/%s 로 나눈 전체양도가액" % (aid, r["지분분자"], r["지분분모"]), "엔진 양도가액")

    def engine_codes(self, r, v, c):
        """서식에 코드나 말로 옮겨 적은 칸이 엔진 판정과 맞는가. 값을 서식 표기로 바꾸는 표는 forms/서식판.json 과 이 파일 위쪽의 표다."""
        aid = r["자산"]
        try:
            kind = str(int(c["코드"]["자산종류"]))
        except (KeyError, ValueError):
            kind = None
        if kind is not None and r.get("자산종류") != kind:
            self.fail("부표1 %s ③ 자산종류 %s ≠ 엔진 자산종류 코드 %s 의 서식 표기 %s" % (aid, _w(r.get("자산종류")), c["코드"]["자산종류"], kind))
        label = ACQ_LABEL.get(c.get("취득가액방법"), "")
        if (r.get("취득가액종류") or "") != label:
            self.fail("부표1 %s 취득가액종류 %s ≠ 엔진 취득가액방법 %s 의 서식 표기 %s" % (aid, _w(r.get("취득가액종류")), _w(c.get("취득가액방법")), _w(label)))
        codes = self.ltd_codes()
        if codes is not None and v.get("장특공") in codes and r.get("장특공코드") != codes[v["장특공"]]:
            self.fail("부표1 %s ⑯ 장기보유특별공제 코드 %s ≠ 엔진 판정 %s 의 서식 코드 %s"
                      % (aid, _w(r.get("장특공코드")), v["장특공"], codes[v["장특공"]]))

    def ltd_codes(self):
        """판정의 장특공 값(없음, 표1, 표2) → 부표1 ⑯ 코드."""
        if not hasattr(self, "_ltd"):
            with open(os.path.join(self.forms_dir, "서식판.json"), encoding="utf-8") as f:
                self._ltd = json.load(f)["부표1_장특공코드"]["코드"]
        return self._ltd

    def engine_columns(self):
        """엔진 결과를 세율구분 표기별로 모은다. 전액비과세 자산은 열이 없다."""
        out = {}
        for r in self.calc["자산"]:
            if r["판정"].get("전액비과세"):
                continue
            k = "%s-%s" % (r["계산"]["코드"]["국내외분"], r["계산"]["코드"]["세율구분"])
            x = out.setdefault(k, {"양도소득금액": 0, "기본공제": 0})
            x["양도소득금액"] += _i(r["계산"]["양도소득금액"])
            x["기본공제"] += _i(r["계산"]["기본공제"])
        return out

    def engine_main(self):
        cols = self.rv["본지"]["열"]
        labels = [x["표기"] for x in self.rv["본지"]["세율구분"]]
        eng_rates = {"%s-%s" % (x["국내외분"], x["세율구분"]): x for x in self.calc["세율별"]}
        if labels != list(eng_rates):
            self.fail("본지 세율구분 열 [%s] ≠ 엔진 세율별 [%s]" % (", ".join(labels), ", ".join(eng_rates)))
        eng_cols = self.engine_columns()
        for label in labels:
            c, e, g = cols.get(label), eng_rates.get(label), eng_cols.get(label)
            if c is None or e is None:
                continue
            self.same(c.get("과세표준"), e["과세표준"], "본지 %s 열 ⑧ 과세표준" % label, "엔진 세율별")
            self.same(c.get("산출세액"), e["산출세액"], "본지 %s 열 ⑩ 산출세액" % label, "엔진 세율별")
            if g is not None:
                self.same(c.get("양도소득금액"), g["양도소득금액"], "본지 %s 열 ④ 양도소득금액" % label, "엔진")
                self.same(c.get("기본공제"), g["기본공제"], "본지 %s ⑦ 기본공제" % label, "엔진")
        t = self.calc["합계"]
        total = cols.get("합계")
        if total is not None:
            self.same(total.get("과세표준"), t["과세표준"], "본지 합계 ⑧ 과세표준", "엔진")
            self.same(total.get("산출세액"), t["산출세액"], "본지 합계 ⑩ 산출세액", "엔진")
            self.same(total.get("양도소득금액"), sum(g["양도소득금액"] for g in eng_cols.values()), "본지 합계 ④ 양도소득금액", "엔진")
            self.same(total.get("기본공제"), sum(g["기본공제"] for g in eng_cols.values()), "본지 합계 ⑦ 기본공제", "엔진")
        sub = cols.get("국내소계")
        if sub is not None:
            self.same(sub.get("산출세액"), sum(e["산출세액"] for k, e in eng_rates.items() if k.startswith("1-")),
                      "본지 국내소계 ⑩ 산출세액", "엔진 세율별 합")

    def engine_local(self):
        cols = self.rv["지방"]["열"]
        t = self.calc["합계"]
        total = cols.get("합계")
        if total is not None:
            self.same(total.get("과세표준"), t["과세표준"], "지방 합계 ⑤ 과세표준", "엔진")
            self.same(total.get("산출세액"), t["지방소득세"], "지방 합계 ⑦ 산출세액", "엔진 지방소득세")
        labels = [x["표기"] for x in self.rv["지방"]["세율구분"]]
        if all(x in cols for x in labels):
            self.same(sum(_i(cols[x].get("산출세액")) for x in labels), t["지방_호별합산"], "지방 세율구분 열 ⑦ 합",
                      "엔진 호별합산")


def check(rv, result, rules_dir=None, efile_dir=None, forms_dir=None):
    """신고값 rv(C8)와 엔진 결과 result(C4)로 서식 값을 검산한다. 실패 문장 목록을 돌려주고, 비면 통과."""
    return _Check(rv, result, rules_dir, efile_dir, forms_dir).run()
