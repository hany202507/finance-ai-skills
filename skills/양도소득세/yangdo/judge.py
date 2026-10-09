# -*- coding: utf-8 -*-
"""판정. 사실관계·기준정보만 보고 정한다. 외부를 조회하지 않는다.

순서: 미등기 → 비과세(일시적 2주택 포함) → 고가주택 → 중과 → 단기 → 장특공.
소득세법 제95조②가 제104조⑦ 중과 대상과 미등기양도자산을 장특공에서 빼므로 중과가 장특공보다 먼저다.
"""
from datetime import date

from yangdo import dates
from yangdo import facts as F
from yangdo.dates import to_date
from yangdo.regions import NeedAnswer

CONTROL = "조정대상지역"
소형신축_시작 = date(2024, 1, 10)  # 시행령 제167조의3①12호 가목. 문항 X03 을 보일지 정하는 데만 쓴다
EXEMPT_REASONS = {"공공임대5년", "수용", "해외이주", "해외취학근무", "부득이1년"}
# 시행령 제154조①2호 나목(해외이주)·다목(1년 이상 해외 취학·근무). 두 목 모두 단서가 「출국일 현재 1주택을 보유하고 있는 경우로서
# 출국일부터 2년 이내에 양도하는 경우에 한한다」 이므로 출국일(문항 H11, 키 보유거주예외일자)을 받아 두 요건을 본다
DEPARTURE_REASONS = {"해외이주": "나목", "해외취학근무": "다목"}
# 시행령 제155조⑱ 각 호. 현금청산소송 코드는 4호(현금청산금 소송)와 5호(수용재결·매도청구소송)를 함께 맡는다(문항 T03 선택지 표시)
EXTEND_ITEMS = {"자산관리공사": "1호", "경매신청": "2호", "공매": "3호", "현금청산소송": "4호 또는 5호"}
EXTEND_REASONS = set(EXTEND_ITEMS)
# ⑱ 본문은 290841@2026-10-01 판에서도 「다른 주택을 취득한 날부터 3년이 되는 날 현재」 다. 처분기한이 2년으로 줄어든 사례(2026-10-01 이후 조정대상지역 간 이동)에
# 이 연장을 적용한 것은 문언만으로 확인되지 않은 해석이라 연장을 적용할 때 확인사항으로 남긴다
EXTEND_2YEAR_NOTE = ("시행령 제155조⑱ 본문은 사유가 다른 주택을 취득한 날부터 3년이 되는 날 현재 있어야 한다고 적는다. "
                     "처분기한이 2년인 경우에 이 연장을 적용하는지는 확인되지 않았다. 세무 전문가 확인이 필요하다")
# 시행령 제154조①1호(공공임대 5년 거주), 2호 가목(수용), 3호(부득이한 사유 1년 거주). 2호 나목·다목(해외 출국)은 빠진다.
# 이 셋은 제155조① 후단이 「종전 주택 취득 1년 뒤 신규 주택 취득」 요건을 적용하지 않는다고 정한다
GAP_EXEMPT_REASONS = {"공공임대5년", "수용", "부득이1년"}
# 중과로 계산한 집에 붙이는 확인사항. 엔진은 판 집의 중과배제 사유(X04)만 묻고 다른 집의 사유는 묻지 않는다.
# 다른 집이 배제 주택이라 일반주택 한 채만 남으면 같은 항 10호가 그 집을 중과에서 뺀다(시행령 제167조의10①10호, 제167조의3①10호)
HEAVY_ITEM_10 = {
    "중과2": "1세대 2주택 중과로 계산했다. 다른 주택이 모두 중과배제 주택(시행령 제167조의10①1호부터 7호까지, 2호는 제167조의3①2호부터 8호까지 "
             "및 8호의2 주택)이면 같은 항 10호(제167조의10①10호)로 이 주택은 중과하지 않는다. 다른 주택의 배제 사유를 확인하라",
    "중과3": "1세대 3주택 이상 중과로 계산했다. 다른 주택 가운데 중과배제 주택(시행령 제167조의3①1호부터 8호까지 및 8호의2)을 빼고 "
             "이 주택 한 채만 남으면 일반주택이라 같은 항 10호(제167조의3①10호)로 중과하지 않는다. 다른 주택의 배제 사유를 확인하라",
}
EV_KEYS = ["지구확인필요", "행정구역대응없음", "조정_취득일", "계약일_공고일이전", "세대주택수", "세대주택수_중과",
           "보유년", "거주년", "보유거주미충족", "비과세후보", "일시적2주택후보", "처분기한초과",
           "종전수도권_신규수도권밖", "과세", "중과후보", "지방소재주택있음", "양도주택기준시가_1억이하",
           "2024-01-10이후취득주택있음", "양도일", "취득일", "감정가액사용", "토지건물안분필요", "신규주택id",
           "소재지확인필요", "소재지안내", "취득당시소재지확인필요", "취득당시소재지안내", "주택별"]
# 집마다의 엔진값 이름. engine_values 의 「주택별」 은 {주택 id: {이 이름: 값}} 이고 문항의 보이는조건은 「주택.<이름>」 으로 읽는다
HOUSE_EV_KEYS = ["지방소재", "2024-01-10이후취득"]


def _status(reg, addr, on, 지구, aid):
    try:
        return reg.status(CONTROL, addr, on, 지구)
    except NeedAnswer as e:
        extra = " (후보: %s)" % ", ".join(e.후보) if e.후보 else ""
        raise F.Missing(e.문항, aid, e.내용 + extra)


def _status_asset(reg, a, on):
    try:
        return reg.status(CONTROL, a["소재지"], on, a.get("지구해당"))
    except NeedAnswer as e:
        if e.문항 == "A03" and a.get("취득당시소재지"):
            return _status(reg, a["취득당시소재지"], on, a.get("지구해당"), a["id"])
        raise F.Missing(e.문항, a["id"], e.내용)


def _opt(f, a, path, 문항):
    """값이 없으면 질문. 「모름」으로 답했으면 None."""
    v = F.get(a, path)
    if v is None and "%s:%s" % (문항, a["id"]) in (f.get("모름") or []):
        return None
    if v is None:
        raise F.Missing(문항, a["id"], "%s 가 필요합니다" % path)
    return v


def _blank(a, t):
    return {"id": a["id"], "종류": a["종류"], "취득일": t["취득일"], "양도일": t["양도일"],
            "보유년": 0, "거주년": 0, "거주근사": False, "주택수": None, "주택수_중과": None,
            "일세대": None, "일세대일주택": False, "일시적2주택": False, "처분기한": None,
            "비과세": False, "고가주택": False, "전액비과세": False, "미등기": False, "중과": None,
            "단기": None, "장특공": "없음", "조정_양도일": None, "조정_취득일": None, "공고전계약_취득": False,
            "근거": [], "확인사항": [], "경고": []}


def one_household(f):
    if F.need(f, "세대.배우자", "H01", None):
        return True
    요건 = F.need(f, "세대.1세대요건", "H02", None)   # 복수선택이라 목록이다. 목록이 아니면 prepare 가 H02 를 되묻는다
    return any(c != "해당없음" for c in 요건)


def self_house(f, a, houses):
    for h in houses or []:
        if h.get("자산id") == a["id"]:
            return h
    raise F.Missing("H04", a["id"], "판 집을 세대 주택 목록에 넣고 자산id 로 이어 주세요")


def holding_start(a, 취득):
    """비과세 보유기간을 세는 시작일. 주택이 아닌 건물을 주거용으로 바꿔 쓰면 주거 사용을 시작한 날부터 센다(시행령 제154조⑤ 단서)."""
    return max(취득, to_date(a.get("주거사용개시일")) or 취득)


def house_acq(h, prep):
    """주택 목록 항목의 취득일. 판 자산과 이어진 집(자산id)은 prepare 가 정한 취득 시기를 쓴다(houses_at 과 같은 규칙)."""
    aid = h.get("자산id")
    t = (prep.get("시기") or {}).get(aid) if aid else None
    return to_date(t["취득일"]) if t else to_date(h.get("취득일"))


def _with_acq(h, prep):
    """취득일을 house_acq 로 바꾼 사본. 신규 주택의 취득일이 houses_at 과 어긋나지 않게 한다."""
    d = house_acq(h, prep)
    return dict(h, 취득일=d.isoformat() if d else None)


def _sale_base_price(a, h):
    vals = [int(x) for x in ((a.get("기준시가") or {}).get("양도") or {}).values() if x]
    if vals:
        return sum(vals)
    return (h or {}).get("양도당시기준시가")


def disposal_years(f, a, other, 양도, rs, reg):
    """일시적 2주택 처분기한(년), 근거, 확인사항. 시행령 제155조①과 부칙 제36737호 제2조."""
    base = rs.value("일시적2주택.처분기한.일반", 양도)
    cites = rs.cite("일시적2주택.처분기한.일반", 양도)
    if F.get(f, "세대.기관이전종사자"):
        return (rs.value("일시적2주택.처분기한.기관이전", 양도), rs.cite("일시적2주택.처분기한.기관이전", 양도),
                ["공공기관·법인 지방 이전 종사자 특례(시행령 제155조⑯)를 입력대로 적용했다. 이전 지역 요건을 확인하라"])
    신규 = to_date(other["취득일"])
    if 양도 < to_date(rs.value("일시적2주택.조정기한.양도시작", 양도)):
        return base, cites, []
    if 신규 < to_date(rs.value("일시적2주택.조정기한.신규취득시작", 양도)):
        return base, cites + rs.cite("일시적2주택.조정기한.신규취득시작", 양도), []
    기준 = to_date(rs.value("일시적2주택.조정기한.계약기준", 양도))
    계약, 계약금 = to_date(other.get("계약일")), to_date(other.get("계약금지급일"))
    if 계약 and 계약금 and 계약 <= 기준 and 계약금 <= 기준:
        return (base, cites + rs.cite("일시적2주택.조정기한.계약기준", 양도),
                ["신규 주택 매매계약과 계약금 지급이 %s 이전이라 종전 규정(3년)을 적용했다(부칙 제36737호 제2조②2호). 증명서류를 확인하라" % 기준])
    종전 = _status_asset(reg, a, 신규)
    새집 = _status(reg, other["소재지"], 신규, other.get("지구해당"), a["id"])
    if not (종전["지정"] and 새집["지정"]):
        return base, cites, []
    공고일 = to_date(새집["공고일"])
    if 공고일 and (신규 <= 공고일 or (계약 and 계약금 and 계약 <= 공고일 and 계약금 <= 공고일)):
        return base, cites, ["신규 주택 취득·계약이 조정대상지역 공고일(%s) 이전이라 2년 기한을 적용하지 않았다(시행령 제155조①1호 괄호)" % 공고일]
    return (rs.value("일시적2주택.처분기한.조정", 양도),
            rs.cite("일시적2주택.처분기한.조정", 양도) + rs.cite("일시적2주택.조정기한.신규취득시작", 양도), [])


def count_for_heavy(f, a, houses, me, on, rs, reg):
    limit = rs.value("중과.지방저가.기준시가", on)
    m, notes = 0, []
    for h in houses:
        if h.get("제12호해당") not in (None, "해당없음"):
            notes.append("%s: 시행령 제167조의3①12호 주택(%s)으로 입력돼 주택 수에서 뺐다. 요건을 확인하라" % (h["id"], h["제12호해당"]))
            continue
        metro = reg.metro(h["소재지"], on)
        if metro is False:
            p = _sale_base_price(a, h) if h is me else h.get("양도당시기준시가")
            if p is None:
                notes.append("%s: 지방 주택의 양도 당시 기준시가를 몰라 주택 수에 넣었다" % h["id"])
                m += 1
                continue
            if p <= limit:
                continue
        elif metro is None:
            notes.append("%s: 광역시 해당 여부를 정하지 못해 주택 수에 넣었다" % h["id"])
        m += 1
    return m, notes


def _excluded_self(a, me, on, rs, reg):
    if me.get("제12호해당") not in (None, "해당없음"):
        return True
    if reg.metro(me["소재지"], on) is False:
        p = _sale_base_price(a, me)
        return p is not None and p <= rs.value("중과.지방저가.기준시가", on)
    return False


def _new_house_cause(aid, other):
    """신규 주택의 취득 원인(T02). 재개발·재건축 조합원으로 받은 집은 입주권 특례(시행령 제156조의2·제156조의3)가 걸려
    일시적 2주택 처분기한과 주택 수를 이 엔진이 정하지 못하므로 계산하지 않는다. 글자가 아닌 값은 T02 를 되묻는다."""
    cause = other.get("취득원인")
    if cause is None:
        return
    if not isinstance(cause, str):
        q = next(x for x in F.load_questions()["문항"] if x["id"] == "T02")
        raise F.Missing("T02", aid, F.FORM_MSG % ("세대.주택목록[신규].취득원인", F.form_problem(q, cause)))
    if cause == "조합원":
        raise F.OutOfScope(aid, "신규 주택을 재개발·재건축 조합원으로 받았다(시행령 제156조의2·제156조의3, 입주권 특례가 걸려 계산하지 않았다)", "5")


def _acq_contract_exception(f, a, st):
    공고일 = to_date(st.get("공고일"))
    if not 공고일:
        return False
    계약 = to_date(_opt(f, a, "취득.계약일", "A16"))
    계약금 = to_date(_opt(f, a, "취득.계약금지급일", "A16"))
    if 계약 and 계약금 and 계약 <= 공고일 and 계약금 <= 공고일:
        return bool(_opt(f, a, "취득.계약금지급일_무주택", "H09"))
    return False


def _temporary(f, a, other, 취득, 양도, rs, reg, v):
    신규 = to_date(other["취득일"])
    기관 = bool(F.get(f, "세대.기관이전종사자"))
    채움 = 기관 or dates.full_years(취득, 신규) >= rs.value("일시적2주택.취득간격", 양도)
    사유 = F.get(a, "보유거주예외")  # 여기서는 묻지 않는다. 문항 H10 은 보유·거주 미달일 때만 나온다
    면제 = 사유 in GAP_EXEMPT_REASONS
    간격 = 채움 or 면제
    years, cites, notes = disposal_years(f, a, other, 양도, rs, reg)
    기한일 = dates.add_years(신규, years)
    v["처분기한"] = 기한일.isoformat()
    v["근거"] += rs.cite("판정.일시적2주택", 양도) + rs.cite("일시적2주택.취득간격", 양도) + cites
    v["확인사항"] += notes
    기한내 = 양도 <= 기한일
    if not 기한내:
        연장 = _opt(f, a, "처분기한연장사유", "T03")
        if 연장 in EXTEND_REASONS:
            기한내 = True
            v["근거"] += rs.cite("판정.처분기한연장", 양도)
            v["확인사항"].append("처분기한(%s)이 지났지만 %s 사유로 기한 안 양도로 보았다(시행령 제155조⑱%s). 증빙을 확인하라"
                              % (v["처분기한"], 연장, EXTEND_ITEMS[연장]))
            if years < rs.value("일시적2주택.처분기한.일반", 양도):
                v["확인사항"].append(EXTEND_2YEAR_NOTE)
    if 면제 and not 채움:
        v["확인사항"].append("종전 주택 양도가 시행령 제154조① 예외 사유(%s)에 해당해 종전 주택 취득 1년 뒤 신규 주택을 취득해야 한다는 요건을 "
                          "적용하지 않았다(시행령 제155조① 후단). 증빙을 확인하라" % 사유)
    if not 간격:
        v["확인사항"].append("신규 주택을 종전 주택 취득 1년 안에 취득해 일시적 2주택 특례를 적용하지 않았다")
    return 간격 and 기한내


def _departure_exemption(f, a, 예외, 취득, 양도, v):
    """해외 출국 예외(시행령 제154조①2호 나목·다목 단서)를 적용할 수 있는지. 사유를 못 채우면 확인사항에 이유를 적고 False.

    요건 둘: 출국일 현재 이 주택을 보유했고(취득일 <= 출국일), 출국일부터 2년 이내에 양도했다(양도일 <= 출국일 + 2년).
    출국일 현재 세대가 가진 주택이 한 채뿐인지는 주택 목록으로 알 수 없어 확인사항으로 남긴다.
    """
    aid = a["id"]
    조문 = "시행령 제154조①2호 %s 단서" % DEPARTURE_REASONS[예외]
    try:
        출국 = to_date(F.get(a, "보유거주예외일자"))
    except ValueError:
        raise F.Missing("H11", aid, "출국한 날은 YYYY-MM-DD 로 적어야 합니다")
    if 출국 is None:
        if "H11:%s" % aid not in (f.get("모름") or []):
            raise F.Missing("H11", aid, "%s 예외를 보려면 출국한 날(보유거주예외일자)이 필요합니다" % 예외)
        v["확인사항"].append("출국일을 알 수 없어 %s 예외를 적용하지 않았다(%s는 출국일 현재 보유와 출국일부터 2년 안 양도를 요건으로 한다). "
                          "출국일을 확인한 뒤 다시 계산하라" % (예외, 조문))
        return False
    if 취득 > 출국:
        v["확인사항"].append("출국일(%s) 현재 이 주택을 보유하지 않았다(취득일 %s). %s 에 따라 %s 예외를 적용하지 않았다"
                          % (출국, 취득, 조문, 예외))
        return False
    기한 = dates.add_years(출국, 2)
    if 양도 > 기한:
        v["확인사항"].append("출국일(%s)부터 2년 안에 양도하지 않았다(2년째 날 %s, 양도일 %s). %s 에 따라 %s 예외를 적용하지 않았다"
                          % (출국, 기한, 양도, 조문, 예외))
        return False
    v["확인사항"].append("%s 예외(%s)를 적용했다. 출국일(%s) 현재 이 주택을 보유했고 출국일부터 2년 안에 양도했다. "
                      "출국일 현재 세대의 주택이 이 한 채뿐이었는지와 출국 증빙을 확인하라" % (예외, 조문, 출국))
    return True


def _exemption(f, a, rs, v, 취득, 양도):
    보유시작 = holding_start(a, 취득)
    if 보유시작 != 취득:
        v["근거"] += rs.cite("판정.주거용전환", 양도)
    보유 = dates.full_years(보유시작, 양도)
    요건거주 = rs.value("비과세.조정취득거주", 양도)
    거주필요 = bool(v["조정_취득일"]["지정"])
    if 거주필요 and a.get("거주_일부미거주") is True:   # 모를때처리(H08): 사실 판단이라 확인사항으로 낸다. 거주기간은 입력한 구간 그대로 센다
        v["확인사항"].append(F.NOT_REFLECTED % (
            "거주 기간 중 세대원 일부가 학교·직장·질병 치료로 따로 산 적이 있다고 답했다. 거주기간(H07)은 입력한 구간 그대로 셌다. "
            "따로 산 기간을 거주기간으로 볼 수 있는지는 사실을 확인하라(소득세법 시행규칙 제71조③, 시행령 제154조①1호 괄호)"))
    if 거주필요 and v["거주년"] < 요건거주 and _acq_contract_exception(f, a, v["조정_취득일"]):
        거주필요 = False
        v["공고전계약_취득"] = True
        v["근거"] += rs.cite("판정.거주요건공고전계약", 양도)
        v["확인사항"].append("조정대상지역 공고일(%s) 이전 계약·계약금 지급이고 그날 무주택이라 거주요건을 적용하지 않았다(시행령 제154조①5호). 증빙을 확인하라"
                          % v["조정_취득일"]["공고일"])
    ok = 보유 >= rs.value("비과세.보유", 양도) and (not 거주필요 or v["거주년"] >= 요건거주)
    if not ok:
        예외 = _opt(f, a, "보유거주예외", "H10")
        if 예외 in DEPARTURE_REASONS:
            ok = _departure_exemption(f, a, 예외, 취득, 양도, v)
            if ok:
                v["근거"] += rs.cite("판정.보유거주예외", 양도)
        elif 예외 in EXEMPT_REASONS:
            ok = True
            v["근거"] += rs.cite("판정.보유거주예외", 양도)
            v["확인사항"].append("보유·거주 요건 예외(%s, 시행령 제154조① 단서)를 입력대로 적용했다. 증빙을 확인하라" % 예외)
    v["비과세"] = ok
    if ok:
        v["근거"] += rs.cite("비과세.보유", 양도)
        if 거주필요:
            v["근거"] += rs.cite("비과세.조정취득거주", 양도)


def _heavy(f, a, houses, me, rs, reg, v, 양도):
    st = v["조정_양도일"]
    if not st["지정"] or len(houses) < 2:
        return
    m, notes = count_for_heavy(f, a, houses, me, 양도, rs, reg)
    v["주택수_중과"] = m
    v["확인사항"] += notes
    if _excluded_self(a, me, 양도, rs, reg):
        v["확인사항"].append("판 집이 지방 저가주택이거나 시행령 제167조의3①12호 주택이라 중과하지 않았다")
        return
    if m < 2:
        return
    kind = "중과3" if m >= 3 else "중과2"
    key = "중과.3주택" if kind == "중과3" else "중과.2주택"
    공고일 = to_date(st.get("공고일"))
    계약 = to_date(_opt(f, a, "양도.계약일", "A09"))
    계약금 = to_date(_opt(f, a, "양도.계약금수령일", "A10"))
    if 공고일 and 계약 and 계약금 and 계약 <= 공고일 and 계약금 <= 공고일:
        v["근거"] += rs.cite("판정.중과배제.공고전계약", 양도)
        v["확인사항"].append("조정대상지역 공고일(%s) 이전에 양도 매매계약·계약금 수령을 해 중과하지 않았다. 증빙을 확인하라" % 공고일)
        return
    기한 = to_date(rs.value("중과.한시배제.가목.양도기한", 양도))
    if v["보유년"] >= rs.value("중과.한시배제.보유", 양도) and 양도 <= 기한:
        v["근거"] += rs.cite("중과.한시배제.가목.양도기한", 양도) + rs.cite("중과.한시배제.보유", 양도)
        v["확인사항"].append("보유 2년 이상 주택을 %s 까지 양도해 다주택 중과를 배제했다(한시배제 가목)" % 기한)
        return
    if kind == "중과2":
        p = _sale_base_price(a, me)
        if p is None:
            raise F.Missing("M22", a["id"], "양도 당시 기준시가가 필요합니다")
        if p <= rs.value("중과.소형.기준시가", 양도):
            정비 = _opt(f, a, "정비구역", "X02")
            if 정비 == "아니오":
                v["근거"] += rs.cite("중과.소형.기준시가", 양도)
                v["확인사항"].append("양도 당시 기준시가 1억원 이하이고 정비구역이 아니라 중과하지 않았다(시행령 제167조의10①9호)")
                return
            v["확인사항"].append("양도 당시 기준시가 1억원 이하지만 정비구역 여부가 정해지지 않아 중과로 계산했다")
    사유 = [c for c in F.need(a, "중과배제_사유", "X04", a["id"]) if c != "해당없음"]
    if "장기임대등록" in 사유:
        v["확인사항"].append("등록임대주택 중과배제(시행령 제167조의3①2호)는 판정하지 않았다. 요건을 갖추면 중과가 빠진다. "
                          "아파트 장기임대주택은 2027-12-31 까지 양도해야 한다(시행령 제167조의3⑪)")
        사유 = [c for c in 사유 if c != "장기임대등록"]
    if 사유:
        v["근거"] += rs.cite("판정.중과배제.사유", 양도)
        v["확인사항"].append("중과배제 사유 %s 를 입력대로 인정했다. 해당 호의 요건과 증빙을 확인하라" % ", ".join(사유))
        return
    if a.get("토지거래허가대상") == "예":
        v["확인사항"].append("한시배제 나목(토지거래허가 대상 주택)은 계획 5 에서 판정한다. 해당하면 중과가 빠진다")
    elif 계약 and 계약 <= 기한:
        v["확인사항"].append("양도 매매계약이 %s 이전이라 한시배제 다목에 해당할 수 있다. 다목 판정은 계획 5 다" % 기한)
    v["중과"] = kind
    v["확인사항"].append(HEAVY_ITEM_10[kind])
    v["근거"] += rs.cite(key, 양도) + rs.cite("판정.비교과세", 양도)
    v["경고"] += rs.notes(key, 양도)


def _house(f, a, prep, rs, reg, v, 취득, 양도):
    aid = a["id"]
    houses = F.houses_at(f, 양도, prep)
    me = self_house(f, a, houses)
    n = len(houses)
    v["주택수"] = n
    일세대 = one_household(f)
    v["일세대"] = 일세대
    v["조정_양도일"] = _status(reg, a["소재지"], 양도, a.get("지구해당"), aid)
    v["조정_취득일"] = _status(reg, a.get("취득당시소재지") or a["소재지"], 취득, a.get("지구해당"), aid)
    for st in (v["조정_양도일"], v["조정_취득일"]):
        v["확인사항"] += st["주석"]
    cand = False
    if 일세대 and n == 1:
        cand = True
    elif 일세대 and n == 2:
        other = _with_acq([h for h in houses if h is not me][0], prep)
        if not other.get("취득일"):
            raise F.Missing("H04", aid, "주택 목록 %s 의 취득일이 필요합니다" % other.get("id"))
        if 취득 < to_date(other["취득일"]):
            _new_house_cause(aid, other)
            v["일시적2주택"] = True
            cand = _temporary(f, a, other, 취득, 양도, rs, reg, v)
    if not 일세대:
        v["확인사항"].append("1세대 요건(소득세법 제88조6호)을 갖추지 못해 1세대1주택 비과세를 적용하지 않았다")
    v["일세대일주택"] = cand
    if cand:
        v["근거"] += rs.cite("판정.1세대1주택", 양도)
        v["거주년"], v["거주근사"] = dates.residence_years(F.need(a, "거주기간", "H07", aid), 취득, 양도)
        if v["거주근사"]:
            v["확인사항"].append("거주기간이 여러 구간이라 일수 합을 365 로 나눠 햇수를 셌다. 경계에 걸리면 직접 확인하라")
        _exemption(f, a, rs, v, 취득, 양도)
        if v["비과세"]:
            if F.need(a, "전체양도가액", "M01", aid) > rs.value("고가주택기준", 양도):
                v["고가주택"] = True
                v["근거"] += rs.cite("고가주택기준", 양도) + rs.cite("판정.고가안분", 양도)
            else:
                v["전액비과세"] = True
            return
    _heavy(f, a, houses, me, rs, reg, v, 양도)


def judge_asset(f, a, prep, rs, reg):
    aid = a["id"]
    t = (prep.get("시기") or {}).get(aid)
    if t is None:
        raise F.Missing("A11", aid, "양도·취득 시기를 먼저 정해야 합니다")
    취득, 양도 = to_date(t["취득일"]), to_date(t["양도일"])
    v = _blank(a, t)
    v["근거"] += rs.cite("판정.취득양도시기", 양도)
    v["보유년"] = dates.full_years(취득, 양도)
    if not F.need(a, "등기", "A07", aid):
        사유 = F.need(a, "미등기사유", "A08", aid)
        if 사유 == "미이행":
            v["미등기"] = True
            v["근거"] += rs.cite("미등기", 양도)
        else:
            v["확인사항"].append("등기하지 않은 사유(%s)가 시행령 제168조① 제외 사유라 미등기양도자산으로 보지 않았다. 증빙을 확인하라" % 사유)
            v["근거"] += rs.cite("판정.미등기제외", 양도)
    if a["종류"] == "주택" and not v["미등기"]:
        try:
            _house(f, a, prep, rs, reg, v, 취득, 양도)
        except F.Missing as m:
            # 판정이 지구 답(A02)을 요구하는데 모른다고 답했으면 다시 묻지 않고 다루지않음으로 돌린다. 질문지는 이미 답한 문항을 내지 않아
            # 되물으면 대화가 끝나지 않는다. 지구 답이 필요 없는 주소(엔진값 지구확인필요 거짓)와 미등기 미이행 주택은 이 길을 지나지 않는다
            if m.문항 == "A02" and F.district_unknown(f, a):
                raise F.OutOfScope(aid, F.DISTRICT_UNKNOWN, "없음") from None
            raise
        if v["전액비과세"]:
            return v
    grp = "주택" if a["종류"] == "주택" else "일반"
    if v["보유년"] < 2 and not v["미등기"]:
        v["단기"] = "1년미만" if v["보유년"] < 1 else "2년미만"
        v["근거"] += rs.cite("단기.%s.%s" % (grp, v["단기"]), 양도)
    if v["미등기"] or v["중과"] or v["보유년"] < rs.value("장특공.최소보유", 양도):
        v["장특공"] = "없음"
        if v["미등기"] or v["중과"]:
            v["근거"] += rs.cite("판정.장특공제외", 양도)
    elif v["일세대일주택"] and v["거주년"] >= rs.value("장특공.표2.거주요건", 양도):
        if holding_start(a, 취득) != 취득:
            # 소득세법 제95조⑤: 건물로 보유한 기간은 표1, 주택으로 보유한 기간은 표2 로 나눠 합산하고 거주 공제율은 주택 기간 중 거주만 본다.
            # 엔진은 취득일부터 표2 를 주므로 이 경우는 계산하지 않는다
            raise F.OutOfScope(aid, "주택으로 용도를 바꾼 건물의 장기보유특별공제(소득세법 제95조⑤)", "5")
        v["장특공"] = "표2"
        for k in ("장특공.표2.보유", "장특공.표2.거주", "장특공.표2.거주요건"):
            v["근거"] += rs.cite(k, 양도)
    else:
        v["장특공"] = "표1"
        v["근거"] += rs.cite("장특공.표1", 양도)
    return v


def judge(f, prep, rs, reg):
    out = {"질문": [], "다루지않음": [], "자산": [], "확인사항": [], "경고": []}
    돌려보냄 = {x.get("자산") for x in (prep.get("질문") or []) + (prep.get("다루지않음") or [])}
    for a in f.get("자산") or []:
        aid = a.get("id")
        # 시기를 못 정했거나, 정했어도 prepare 가 질문이나 다루지않음으로 돌려보낸 자산은 판정하지 않는다.
        # prepare 는 시기를 먼저 적은 뒤 소재지 질문(A01)과 다루지않음 검사를 하므로 시기만 보면 놓친다
        if aid not in (prep.get("시기") or {}) or aid in 돌려보냄:
            continue
        try:
            out["자산"].append(judge_asset(f, a, prep, rs, reg))
        except F.Missing as m:
            out["질문"].append(m.to_dict())
        except F.OutOfScope as o:
            out["다루지않음"].append(o.to_dict())
    # 자산별 확인사항·경고를 자산 id 를 붙여 모은다. 엔진이 이 목록을 그대로 결과에 싣는다
    for key in ("확인사항", "경고"):
        for v in out["자산"]:
            for m in v[key]:
                line = "%s: %s" % (v["id"], m)
                if line not in out[key]:
                    out[key].append(line)
    return out


_SOFT = (F.Missing, F.OutOfScope, NeedAnswer, KeyError, TypeError, ValueError, IndexError, AttributeError)


def _try(fn):
    try:
        return fn()
    except _SOFT:
        return None


def _lt(x, y):
    """x < y. 둘 중 하나라도 모르면 None."""
    return None if x is None or y is None else x < y


def house_values(h, 양도, prep, reg):
    """주택 목록 한 채의 엔진값(HOUSE_EV_KEYS). 모르면 None.

    지방소재: 수도권도 아니고 광역시(군 제외)·세종(읍면 제외)의 동 지역도 아니면 참. 중과 주택 수의 지방 저가 제외(count_for_heavy)가
    쓰는 reg.metro 와 같은 규칙이다. 소재지를 모르거나 지역을 정하지 못하면 None.
    2024-01-10이후취득: 시행령 제167조의3①12호 가목의 시작일(소형신축_시작) 이후에 취득했으면 참. 취득일은 house_acq 와 같은 규칙이다.
    """
    metro = _try(lambda: reg.metro(h["소재지"], 양도))
    acq = _try(lambda: house_acq(h, prep))
    return {"지방소재": None if metro is None else not metro,
            "2024-01-10이후취득": None if acq is None else acq >= 소형신축_시작}


def engine_values(f, a, prep, rs, reg):
    """질문지 보이는조건의 엔진값. 모르는 값은 None 이고 예외를 던지지 않는다.

    사실관계가 반쯤 채워져 있어도(주택 목록의 소재지 없음, 거주 구간의 끝 날짜 없음 등) 읽는 곳마다 _try 로 감싸
    그 값만 None 으로 둔다.

    소재지확인필요, 취득당시소재지확인필요: 적어 둔 주소가 고시 이력으로 지역을 정하기에 모자라면(구 이름이 빠진 시군구, 모르는 시도 등,
    NeedAnswer A01) 참이고, 되물을 안내 문장이 소재지안내, 취득당시소재지안내에 들어간다. 문항이 아니라 되묻기에 쓴다.
    주택별: {주택 id: house_values}. 양도일에 세대가 가진 주택(houses_at)만 들어간다. 주택 목록을 정하지 못하면 빈 dict.
    """
    ev = dict.fromkeys(EV_KEYS)
    ev["지구확인필요"] = ev["행정구역대응없음"] = ev["소재지확인필요"] = ev["취득당시소재지확인필요"] = False
    ev["주택별"] = {}
    aid = a.get("id")
    t = (prep.get("시기") or {}).get(aid)
    if not t:
        return ev
    날짜 = _try(lambda: (to_date(t["취득일"]), to_date(t["양도일"])))
    if not 날짜 or None in 날짜:
        return ev
    취득, 양도 = 날짜
    ev.update(양도일=t["양도일"], 취득일=t["취득일"], 보유년=_try(lambda: dates.full_years(취득, 양도)))
    if a.get("소재지"):
        # 취득일의 주소는 취득당시소재지를 따로 적었으면 그 주소(A03), 아니면 소재지(A01)다
        for name, addr, on in (("소재지", a["소재지"], 양도),
                               ("취득당시소재지" if a.get("취득당시소재지") else "소재지",
                                a.get("취득당시소재지") or a["소재지"], 취득)):
            try:
                reg.status(CONTROL, addr, on, a.get("지구해당"))
            except NeedAnswer as e:
                ev["지구확인필요"] = ev["지구확인필요"] or e.문항 == "A02"
                ev["행정구역대응없음"] = ev["행정구역대응없음"] or e.문항 == "A03"
                if e.문항 == "A01" and not ev[name + "확인필요"]:
                    ev[name + "확인필요"], ev[name + "안내"] = True, e.내용
            except _SOFT:
                pass
    st_acq = _try(lambda: reg.status(CONTROL, a.get("취득당시소재지") or a["소재지"], 취득, a.get("지구해당")))
    st_sale = _try(lambda: reg.status(CONTROL, a["소재지"], 양도, a.get("지구해당")))
    ev["조정_취득일"] = st_acq["지정"] if st_acq else None
    if st_acq and st_acq["지정"] and st_acq["공고일"]:
        def 계약이_공고일_이전():
            계약, 계약금 = to_date(F.get(a, "취득.계약일")), to_date(F.get(a, "취득.계약금지급일"))
            if 계약 and 계약금:
                return 계약 <= to_date(st_acq["공고일"]) and 계약금 <= to_date(st_acq["공고일"])
            return None
        ev["계약일_공고일이전"] = _try(계약이_공고일_이전)
    elif st_acq:
        ev["계약일_공고일이전"] = False
    p = _try(lambda: _sale_base_price(a, None))
    ev["양도주택기준시가_1억이하"] = None if p is None else _try(lambda: p <= rs.value("중과.소형.기준시가", 양도))
    ev["감정가액사용"] = a.get("취득가액_확인") == "모름" and not a.get("매매사례가액") and bool(a.get("감정가액"))
    ev["토지건물안분필요"] = a.get("종류") == "건물" and not a.get("토지건물구분")
    if a.get("거주기간") is not None:
        ev["거주년"] = _try(lambda: dates.residence_years(a["거주기간"], 취득, 양도)[0])
    if a.get("종류") in ("토지", "건물"):
        ev.update(과세=True, 중과후보=False, 비과세후보=False)
        return ev
    houses = _try(lambda: F.houses_at(f, 양도, prep)) if F.get(f, "세대.주택목록") is not None else None
    if houses is not None:
        ev["주택별"] = {h["id"]: house_values(h, 양도, prep, reg) for h in houses if h.get("id")}
    me = _try(lambda: self_house(f, a, houses)) if houses is not None else None
    if me is None:
        return ev
    n = len(houses)
    others = [h for h in houses if h is not me]
    신규 = _try(lambda: _with_acq(others[0], prep)) if n == 2 else None
    ev["세대주택수"] = n
    ev["지방소재주택있음"] = any(_try(lambda h=h: reg.metro(h["소재지"], 양도)) is not True for h in houses)

    def 신축_이후(h):
        d = _try(lambda: house_acq(h, prep))
        return d is not None and d >= 소형신축_시작
    ev["2024-01-10이후취득주택있음"] = any(신축_이후(h) for h in houses)
    ev["세대주택수_중과"] = _try(lambda: count_for_heavy(f, a, houses, me, 양도, rs, reg)[0])
    temp = bool(신규 is not None and _try(lambda: 취득 < to_date(신규["취득일"])))
    ev["일시적2주택후보"] = temp
    if temp:
        ev["신규주택id"] = 신규.get("id")
        r = _try(lambda: disposal_years(f, a, 신규, 양도, rs, reg))
        if r:
            ev["처분기한초과"] = _try(lambda: 양도 > dates.add_years(to_date(신규["취득일"]), r[0]))
        ev["종전수도권_신규수도권밖"] = _try(lambda: reg.capital(a["소재지"]) and not reg.capital(신규["소재지"]))
    일세대 = _try(lambda: one_household(f))
    ev["비과세후보"] = None if 일세대 is None else bool(일세대 and (n == 1 or temp))
    if ev["비과세후보"] is False:
        ev["보유거주미충족"] = False
    elif ev["비과세후보"]:
        # 보유 햇수는 judge_asset 의 _exemption 과 같은 시작일로 센다. ev["보유년"] 은 취득일 기준 그대로다
        보유 = _try(lambda: dates.full_years(holding_start(a, 취득), 양도))
        보유미달 = _lt(보유, _try(lambda: rs.value("비과세.보유", 양도)))
        if ev["조정_취득일"] is False:
            거주미달 = False
        elif ev["조정_취득일"] is None or ev["거주년"] is None:
            거주미달 = None
        else:
            거주미달 = _lt(ev["거주년"], _try(lambda: rs.value("비과세.조정취득거주", 양도)))
        if 보유미달 or 거주미달:
            ev["보유거주미충족"] = True
        else:
            ev["보유거주미충족"] = None if (보유미달 is None or 거주미달 is None) else False
    full = _try(lambda: judge_asset(f, a, prep, rs, reg))
    if full:
        ev["과세"] = not full["전액비과세"]
        ev["중과후보"] = bool(full["중과"]) or bool(st_sale and st_sale["지정"] and n >= 2 and not full["비과세"])
    else:
        if ev["비과세후보"] is False:
            ev["과세"] = True
        if st_sale is not None:
            ev["중과후보"] = bool(st_sale["지정"] and n >= 2 and not (temp and ev["처분기한초과"] is False))
    return ev
