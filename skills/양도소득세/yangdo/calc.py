# -*- coding: utf-8 -*-
"""계산. 사실관계·판정·기준정보만 받는 순수 함수다. 원 미만은 단계마다 버린다."""
from collections import Counter
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction

from yangdo import dates
from yangdo import facts as F
from yangdo.dates import to_date

OK_EVIDENCE = {"세금계산서", "계산서", "카드영수증", "현금영수증", "계좌이체"}
GROUPS = ("취득부대", "자본적지출", "기타", "양도비")


class Unsupported(Exception):
    pass


def floor(x):
    if isinstance(x, Fraction):
        return x.numerator // x.denominator
    return int(Decimal(x).to_integral_value(rounding=ROUND_FLOOR))


def progressive(base, table):
    """원문 방식: 기준액 + (과표 - 하한) × 세율. table 은 [[하한, 기준액, 세율], ...] 오름차순."""
    row = table[0]
    for r in table:
        if base > r[0]:
            row = r
    return Decimal(row[1]) + (Decimal(base) - row[0]) * row[2]


def _lookup(table, years):
    rate = Decimal(0)
    for y, r in table:
        if years >= y:
            rate = r
    return rate


def ltd_rate(v, rs, on):
    if v["장특공"] == "표1":
        return _lookup(rs.value("장특공.표1", on), v["보유년"])
    if v["장특공"] == "표2":
        return _lookup(rs.value("장특공.표2.보유", on), v["보유년"]) + _lookup(rs.value("장특공.표2.거주", on), v["거주년"])
    return Decimal(0)


def expenses(a):
    ex = a.get("필요경비") or {}
    sums = {"취득세": int(ex.get("취득세") or 0)}
    sums.update({g: 0 for g in GROUPS})
    dropped = []
    for g in GROUPS:
        for it in ex.get(g) or []:
            amt = int(it.get("금액") or 0)
            if g == "자본적지출" and it.get("내용") == "일반수선":
                dropped.append("%s %s원: 일반 수선은 필요경비가 아니다" % (it.get("내용"), amt))
                continue
            if it.get("증빙종류") not in OK_EVIDENCE:
                dropped.append("%s %s원: 증빙(%s)이 세금계산서·계산서·카드영수증·현금영수증·계좌이체가 아니라 넣지 않았다(시행령 제163조③·⑤)"
                               % (it.get("내용"), amt, it.get("증빙종류")))
                continue
            sums[g] += amt
    sums["합계"] = sums["취득세"] + sum(sums[g] for g in GROUPS)
    return sums, dropped


def gain(a, v, rs):
    on, aid, r = to_date(v["양도일"]), a["id"], F.share(a)
    전체 = int(F.need(a, "전체양도가액", "M01", aid))
    out = {"양도가액": floor(Fraction(전체) * r), "전체양도가액": 전체, "취득가액": None, "취득가액방법": None,
           "필요경비": None, "필요경비_제외": [], "양도차익": None, "근거": [], "확인사항": []}
    if v["전액비과세"]:
        return out
    sums, dropped = expenses(a)
    out["필요경비_제외"] = dropped
    if dropped:
        out["근거"] += rs.cite("판정.필요경비증빙", on)
    방법 = F.need(a, "취득가액_확인", "M05", aid)
    if 방법 in ("계약서", "기타자료"):
        취득 = floor(Fraction(int(F.need(a, "전체취득가액", "M06", aid))) * r) - int(a.get("감가상각비") or 0)
        경비, kind = sums["합계"], "실지거래가액"
        if 방법 == "기타자료":
            out["확인사항"].append("%s: 계약서 없이 다른 자료로 취득가액을 확인했다. 실지거래가액으로 인정되는지 확인하라" % aid)
    else:
        bs = F.need(a, "기준시가", "M22", aid)
        취득합 = sum(int(x) for x in (bs.get("취득") or {}).values() if x)
        양도합 = sum(int(x) for x in (bs.get("양도") or {}).values() if x)
        if not 취득합 or not 양도합:
            raise F.Missing("M22", aid, "취득가액을 추계하려면 취득·양도 당시 기준시가가 모두 필요합니다")
        율키 = "개산공제율.미등기" if v["미등기"] else "개산공제율"
        개산 = floor(Decimal(floor(Fraction(취득합) * r)) * rs.value(율키, on))
        out["근거"] += rs.cite("판정.추계순서", on) + rs.cite(율키, on)
        if a.get("매매사례가액"):
            취득, 경비, kind = floor(Fraction(int(a["매매사례가액"])) * r), 개산, "매매사례가액"
        elif a.get("감정가액"):
            ap = [int(x) for x in a["감정가액"]]
            취득, 경비, kind = floor(Fraction(sum(ap), len(ap)) * r), 개산, "감정가액"
        else:
            kind = "환산가액"
            환산 = floor(Fraction(out["양도가액"]) * 취득합 / 양도합)
            out["근거"] += rs.cite("판정.환산", on)
            실제 = sums["자본적지출"] + sums["양도비"]
            if 환산 + 개산 < 실제:
                취득, 경비 = 0, 실제
                out["근거"] += rs.cite("판정.개산공제비교", on)
                out["확인사항"].append("%s: 환산취득가액과 개산공제 합(%s원)보다 자본적지출·양도비(%s원)가 커서 그것을 필요경비로 했다(소득세법 제97조②2호 단서)"
                                    % (aid, 환산 + 개산, 실제))
            else:
                취득, 경비 = 환산, 개산
        out["확인사항"].append("%s: 취득가액을 %s 으로 계산했다. 매매사례가액·감정가액·환산취득가액 순서를 확인하라" % (aid, kind))
        built = to_date((a.get("신축증축") or {}).get("사용승인일"))
        if kind in ("환산가액", "감정가액") and built and dates.within_years(built, on, 5):
            out["확인사항"].append("%s: 신축·증축 후 5년 안 양도라 환산·감정가액의 5%% 가산세(소득세법 제114조의2) 대상일 수 있다. 가산세는 계산하지 않았다" % aid)
    out.update(취득가액=취득, 취득가액방법=kind, 필요경비=경비, 양도차익=out["양도가액"] - 취득 - 경비)
    return out


def taxable(g, v, rs):
    on = to_date(v["양도일"])
    기준 = rs.value("고가주택기준", on)
    if v["전액비과세"]:
        return {"비과세양도차익": None, "과세양도차익": 0, "장특공률": "0", "장특공": 0, "양도소득금액": 0, "고가주택기준": 기준}
    if g["양도차익"] < 0:
        raise Unsupported("%s: 양도차손 %s원. 양도차손 통산은 계획 5 범위라 계산하지 않았다" % (v["id"], g["양도차익"]))
    if v["고가주택"]:
        전체 = g["전체양도가액"]
        과세 = floor(Fraction(g["양도차익"]) * (전체 - 기준) / 전체)
    else:
        과세 = g["양도차익"]
    율 = ltd_rate(v, rs, on)
    장특공 = floor(Decimal(과세) * 율)
    return {"비과세양도차익": g["양도차익"] - 과세, "과세양도차익": 과세, "장특공률": str(율), "장특공": 장특공,
            "양도소득금액": 과세 - 장특공, "고가주택기준": 기준}


def rates(v, rs, on, local=False):
    p = "지방." if local else ""
    if v["미등기"]:
        return {"단일": rs.value(p + "미등기", on), "가산": None}
    grp = "주택" if v["종류"] == "주택" else "일반"
    short = rs.value("%s단기.%s.%s" % (p, grp, v["단기"]), on) if v["단기"] else None
    가산 = rs.value(p + ("중과.3주택" if v["중과"] == "중과3" else "중과.2주택"), on) if v["중과"] else Decimal(0)
    return {"단일": short, "가산": 가산}


def rate_tax(v, base, rs, on, local=False):
    """(세액, 이긴 쪽 '단일'|'누진'). 같으면 단일세율 쪽."""
    r = rates(v, rs, on, local)
    if r["가산"] is None:
        return floor(Decimal(base) * r["단일"]), "단일"
    누진 = progressive(base, rs.value(("지방." if local else "") + "기본세율", on)) + Decimal(base) * r["가산"]
    if r["단일"] is not None:
        단일 = Decimal(base) * r["단일"]
        if 단일 >= 누진:
            return floor(단일), "단일"
    return floor(누진), "누진"


def rate_group(v, winner):
    if v["미등기"]:
        return "미등기", None
    g = v["중과"] or ("주택" if v["종류"] == "주택" else "일반")
    return g, (v["단기"] if winner == "단일" else "기본")


def _s(x):
    return None if x is None else str(x)


def _table(t):
    return [[int(a), int(b), str(c)] for a, b, c in t]


def annual(f, verdicts, rs, cd):
    assets = {a["id"]: a for a in f["자산"]}
    if len({v["양도일"][:4] for v in verdicts}) > 1:
        raise Unsupported("과세연도가 다른 양도는 연도마다 따로 계산한다")
    on0 = min(to_date(v["양도일"]) for v in verdicts)
    rows, 확인, 근거 = [], [], []
    for v in verdicts:
        g = gain(assets[v["id"]], v, rs)
        확인 += g.pop("확인사항")
        근거 += g.pop("근거")
        c = dict(g)
        c.update(taxable(g, v, rs))
        rows.append({"id": v["id"], "판정": v, "계산": c})
    남은 = rs.value("기본공제", on0)
    for i in sorted(range(len(rows)), key=lambda i: (rows[i]["판정"]["양도일"], i)):
        c, v = rows[i]["계산"], rows[i]["판정"]
        if v["미등기"] or v["전액비과세"] or c["양도소득금액"] <= 0:
            c["기본공제"] = 0
        else:
            c["기본공제"] = min(남은, c["양도소득금액"])
            남은 -= c["기본공제"]
    if any(r["계산"]["기본공제"] for r in rows):
        근거 += rs.cite("기본공제", on0)
    for row in rows:
        c, v = row["계산"], row["판정"]
        on = to_date(v["양도일"])
        c["과세표준"] = c["양도소득금액"] - c["기본공제"]
        if v["전액비과세"]:
            c["산출세액"], c["지방소득세"], winner = 0, 0, "누진"
        else:
            c["산출세액"], winner = rate_tax(v, c["과세표준"], rs, on)
            c["지방소득세"] = rate_tax(v, c["과세표준"], rs, on, local=True)[0]
        nat, loc = rates(v, rs, on), rates(v, rs, on, True)
        c["적용세율"] = {"단일": _s(nat["단일"]), "가산": _s(nat["가산"]), "지방단일": _s(loc["단일"]), "지방가산": _s(loc["가산"])}
        grp, kind = rate_group(v, winner)
        c["세율그룹"], c["세율종류"] = grp, kind
        c["코드"] = {"과세구분": cd.tax_class(v["전액비과세"]), "국내외분": cd.data["국내외분"]["국내"],
                     "세율구분": cd.rate_code(grp, kind), "자산종류": cd.asset_code(v["종류"], v["고가주택"]),
                     "취득가액종류": cd.acq_code(c["취득가액방법"]), "감면종류": cd.data["감면없음"],
                     "장특공적용구분": cd.data["장기보유특별공제적용구분코드"]["기본"],
                     "보유기간": cd.holding_code(v), "거주기간": cd.residence_code(v)}
    taxed = [r for r in rows if not r["판정"]["전액비과세"]]
    자산별 = sum(r["계산"]["산출세액"] for r in rows)
    지방자산별 = sum(r["계산"]["지방소득세"] for r in rows)
    합산 = 지방합산 = 0
    if len(taxed) >= 2:
        s = sum(r["계산"]["과세표준"] for r in taxed)
        합산 = floor(progressive(s, rs.value("기본세율", on0)))
        지방합산 = floor(progressive(s, rs.value("지방.기본세율", on0)))
        근거 += rs.cite("판정.합산비교", on0)
        same = Counter((r["판정"]["중과"], r["판정"]["단기"]) for r in taxed if r["판정"]["중과"] or r["판정"]["단기"])
        if any(n >= 2 for n in same.values()):
            확인.append("같은 호의 세율이 둘 이상 자산에 걸려 소득세법 제104조⑤2호 단서(같은 호 자산 과표 합산 비교)를 확인해야 한다. 이 계산은 단서를 적용하지 않았다")
    합계 = {"과세표준": sum(r["계산"]["과세표준"] for r in rows), "자산별세액": 자산별, "합산비교세액": 합산,
            "산출세액": max(자산별, 합산), "지방_자산별": 지방자산별, "지방_합산비교": 지방합산,
            "지방소득세": max(지방자산별, 지방합산)}
    세율별 = {}
    for r in taxed:
        k = (r["계산"]["코드"]["국내외분"], r["계산"]["코드"]["세율구분"])
        x = 세율별.setdefault(k, {"국내외분": k[0], "세율구분": k[1], "과세표준": 0, "산출세액": 0})
        x["과세표준"] += r["계산"]["과세표준"]
        x["산출세액"] += r["계산"]["산출세액"]
    return {"자산": rows, "합계": 합계, "세율별": list(세율별.values()),
            "세율표": {"국세": _table(rs.value("기본세율", on0)), "지방": _table(rs.value("지방.기본세율", on0))},
            "근거": 근거, "확인사항": 확인}
