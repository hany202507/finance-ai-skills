# -*- coding: utf-8 -*-
"""현금흐름표 엔진. 전기 재무상태표 + 당기 분개장 → 직접법·간접법·비교·최종.

현금 전표를 먼저 현금분과 비현금분으로 나눈다
  비품 1,000 을 현금 300 과 미지급금 700 으로 산 전표에서 현금이 실제로 나간 것은 300 이다.
  현금과 반대편(현금이 나가면 차변) 줄들에 현금액 300 을 금액 비율로 나눠 붙이고(현금분),
  나머지(비품 700 과 미지급금 700)는 현금이 없는 전표처럼 다룬다(비현금분). 비현금분의 미지급금 700 은
  나중에 결제될 때 비품으로 추적되는 원천이 되고, 기말까지 안 갚으면 비현금 투자 거래로 공시 대상이 된다.
  급여 100 에서 예수금 10 을 떼고 90 을 준 전표는 급여 줄에 90 이 붙고 예수금 10 은 비현금분이 된다.

순서
  1. 직접법   현금분 줄마다 활동·항목을 정한다. 추적 계정(미지급금 등)이면 비현금분에서 원천을 찾는다.
  2. 보정     원천으로 안 정해진 행을 반환 상계 → 상세 발라내기 → 적요 → 거래처 이력 순으로 판정한다.
              계정으로 정해진 행은 적요가 다른 활동을 가리키는지만 점검한다(적합성).
  3. 간접법   계정별 잔액 증감으로 따로 만든다. 활동이 섞인 비현금분에서는 투자·재무 줄과 같은 금액의
              영업 줄을 뺀다.
  4. 비교     활동별 차이가 전부 직접법의 재분류로 설명되는지 본다(구조상 항등식).
  5. 최종     직접법은 그대로, 간접법은 영업활동에 재분류 조정을 넣고 투자·재무·환율은 직접법 항목을 쓴다.

금액은 원 단위 정수, 나눌 때는 최대잉여법. 현금영향 부호: 유입 +, 유출 -. 한 줄의 현금영향 = 대변 - 차변.
"""
import datetime
from bisect import bisect_left
from collections import defaultdict, Counter
import 계정규칙 as R
import 적요 as J

영업, 투자, 재무, 환율 = R.영업, R.투자, R.재무, R.환율
활동순서 = [영업, 투자, 재무, 환율]
최대깊이 = 3
약한방법 = {"원천 없음", "기초잔액", "추적 깊이 초과", "계정 순차"}
근거방법 = {"상대계정", "부속(주 계정 따름)", "건별 일치", "거래처 순차", "환율", "기초잔액(명세서)", "기초잔액(명세서 원천)", "현금 반환 상계", "역분개 상계",
           "상대계정+적요"}
뭉칫돈계정 = ("가수금", "가지급금", "가계정", "미결산", "미분류", "현금과부족")
# 성격이 정해지지 않은 손익계정. 강한 적요가 다른 활동을 가리키면 적요를 따른다(비품 중고판매 대금을 잡이익으로 받은 경우)
잡계정 = ("잡이익", "잡손실", "잡수익", "기타수익", "기타비용", "기타의수익", "기타의비용")


def 정수배분(총액, 가중치):
    """총액을 가중치(0 이상) 비율로 나눈 정수 목록. 합계는 총액과 같다."""
    w = [max(0, x) for x in 가중치]
    s = sum(w)
    if s == 0:
        w = [1] * len(가중치); s = len(w)
    부호 = -1 if 총액 < 0 else 1
    a = abs(총액)
    몫 = [a * x // s for x in w]
    나머지 = sorted(range(len(w)), key=lambda i: -((a * w[i]) % s))
    for i in 나머지[: a - sum(몫)]:
        몫[i] += 1
    return [부호 * x for x in 몫]


def 효과(x):
    return x["대변"] - x["차변"]


def 가상(x, e):
    """줄 x 의 현금영향 e 만큼을 가진 사본. 원래 줄은 원id 로 찾는다."""
    return dict(x, 차변=-e if e < 0 else 0, 대변=e if e > 0 else 0, 원id=x.get("원id", id(x)),
                역=x.get("역", x["차변"] < 0 or x["대변"] < 0))


class 결과:
    pass


def 실행(분개, 전기BS, 계정마스터=None, 정책=None, 기말BS=None, 기준="일반기업", 상세=None, 명세서=None, 손익NI=None,
         현금추가=None, 투자지정=None, 잔액열어둠=False, 판정=None):
    """분개: [{번호,일자,코드,계정,차변,대변,거래처,적요,구분}], 전기BS: [{코드,계정,구분,잔액,분류}].
    상세: [{일자,금액(입금+ 출금-),적요,거래처}]  가계정 뭉칫돈을 발라낼 은행거래·미분류목록.
    명세서: [{코드,거래처,잔액,적요,활동,항목,원천}]  전기말 추적 계정의 거래처별 잔액.
    판정: [{코드,거래처,활동,항목,근거,판정자,판정일}]  회계사가 전에 내린 판정. 약한 판정 행을 덮는다."""
    r = 결과()
    r.확인 = []
    r.제외전표 = []
    r.기준 = "일반기업" if 기준 in ("일반기업", "중소기업", None) else 기준
    r.정책 = dict(R.정책_기본, **(R.정책_1118 if r.기준 == "K-IFRS1118" else {}))
    for k, v in (정책 or {}).items():
        if k in R.정책_고정.get(r.기준, set()) and v != r.정책[k]:
            근 = "제2장 문단 2.61·2.62·2.71" if r.기준 == "일반기업" else "K-IFRS 1118 이 고친 제1007호"
            r.확인.append(("정책", f"{k}={v} 요청은 {'일반기업회계기준' if r.기준 == '일반기업' else r.기준}에서 쓸 수 없어 {r.정책[k]}로 두었다({근})", None))
            continue
        r.정책[k] = v
    r.전기BS = 전기BS
    r.상세 = [dict(d, 사용=False) for d in (상세 or [])]
    r.명세서 = 명세서 or []
    r.판정 = []
    for p in 판정 or []:
        if p["활동"] not in (영업, 투자, 재무) or not p["항목"]:
            r.확인.append(("판정", f"판정 파일 {p['코드']} {p['거래처']}: 활동은 영업·투자·재무, 항목은 비울 수 없다. 쓰지 않았다", None))
            continue
        if not (p.get("근거") and p.get("판정자") and p.get("판정일")):
            r.확인.append(("판정", f"판정 파일 {p['코드']} {p['거래처']}: 근거·판정자·판정일 중 빈 칸이 있다", None))
        r.판정.append(dict(p, 쓰임=0))
    r.손익NI = 손익NI
    r.잔액열어둠 = 잔액열어둠

    # ── 계정표. 이름은 분개장 > 재무상태표 > 마스터, 구분은 재무상태표 > 마스터 > 코드대역
    계정 = {}
    def 등록(코드, 이름, 구분, 분류=None):
        c = 계정.setdefault(코드, {"코드": 코드, "계정": 이름, "구분": None, "분류": None})
        if 구분 and not c["구분"]:
            c["구분"] = 구분
        if 분류 and not c["분류"]:
            c["분류"] = 분류
        if 이름 and not c["계정"]:
            c["계정"] = 이름
    for l in 분개:
        등록(l["코드"], l["계정"], None)
    for b in 전기BS + (기말BS or []):
        등록(b["코드"], b["계정"], b.get("구분"), b.get("분류"))
    for 코드, (이름, 구분) in (계정마스터 or {}).items():
        if 코드 in 계정 and 계정[코드]["계정"] != 이름:
            r.확인.append(("계정", f"코드 {코드}: 분개장은 '{계정[코드]['계정']}', 계정 마스터는 '{이름}'. 분개장 이름으로 판정", None))
        등록(코드, 이름, 구분)
    추정 = []
    for c in 계정.values():
        if not c["구분"]:
            c["구분"] = R.구분_코드추정(c["코드"], c["계정"])
            추정.append(c)
        c.update(R.판정(c["계정"], c["구분"], r.정책, c.get("분류")))
        if 현금추가 and (c["코드"] in 현금추가 or c["계정"] in 현금추가):
            c.update(성격="현금", 활동=None, 근거="현금계정 지정(--현금계정)", 기본값=False)
        if 투자지정 and (c["코드"] in 투자지정 or c["계정"] in 투자지정):
            c.update(성격="명확", 활동=투자, 유입="금융상품의 처분", 유출="금융상품의 취득", 근거="투자계정 지정(--투자계정)", 기본값=False)
    if 추정:
        r.확인.append(("계정", f"구분(자산·부채·자본·수익·비용)을 코드대역으로 추정한 계정 {len(추정)}개. 계정규칙 시트에서 확인"
                      + ("" if all(c["구분"] for c in 추정) else f". 추정 못 한 것: {', '.join(c['계정'] for c in 추정 if not c['구분'])}"), None))
    r.계정 = 계정

    # ── 전표 묶기, 대차 확인
    전표 = defaultdict(list)
    for l in 분개:
        전표[l["번호"]].append(l)
    불일치 = [(k, sum(x["차변"] - x["대변"] for x in v)) for k, v in 전표.items()
              if sum(x["차변"] - x["대변"] for x in v) != 0]
    if 불일치:
        raise ValueError(f"대차가 안 맞는 전표 {len(불일치)}건: {불일치[:10]}")
    성 = lambda x: 계정[x["코드"]]["성격"]

    # 마감분개(손익 → 이익잉여금 대체)는 현금흐름과 무관하고 당기순이익을 0 으로 만든다. 뺀다
    for k, v in list(전표.items()):
        if any(성(x) == "현금" for x in v):
            continue
        손익 = [x for x in v if 계정[x["코드"]]["구분"] in ("수익", "비용")]
        잉여 = [x for x in v if 성(x) == "잉여금"]
        if any(성(x) == "마감" for x in v) or (손익 and 잉여 and len(손익) + len(잉여) == len(v)):
            r.제외전표.append((k, "마감분개(손익 대체)"))
            del 전표[k]
    if r.제외전표:
        r.확인.append(("분개장", f"마감분개 {len(r.제외전표)}건을 뺐다(손익 → 이익잉여금 대체는 현금흐름이 아니다)", None))
    r.전표 = 전표

    # ── 현금분·비현금분
    r.현금부, r.비현금부, r.현금줄, r.이체 = {}, {}, {}, []
    for k, v in 전표.items():
        cash = [x for x in v if 성(x) == "현금"]
        non = [x for x in v if 성(x) != "현금"]
        if not cash:
            r.비현금부[k] = v
            continue
        r.현금줄[k] = cash
        C = sum(효과(x) for x in non)
        if not non or C == 0:
            r.이체.append((k, cash[0]["일자"], sum(x["차변"] - x["대변"] for x in cash), len(cash)))
            if non:
                r.비현금부[f"{k}*"] = non
            continue
        반대편 = [x for x in non if 효과(x) * C > 0]
        몫 = 정수배분(C, [abs(효과(x)) for x in 반대편])
        r.현금부[k] = [가상(x, s) for x, s in zip(반대편, 몫) if s]
        나머지 = [가상(x, 효과(x) - s) for x, s in zip(반대편, 몫) if 효과(x) - s]
        나머지 += [가상(x, 효과(x)) for x in non if 효과(x) * C <= 0 and 효과(x)]
        if 나머지:
            r.비현금부[f"{k}*"] = 나머지

    # ── 잔액
    기초 = defaultdict(int)
    for b in 전기BS:
        기초[b["코드"]] += b["잔액"]
    차 = defaultdict(int); 대 = defaultdict(int)
    for v in 전표.values():
        for x in v:
            차[x["코드"]] += x["차변"]; 대[x["코드"]] += x["대변"]
    def 기말(c):
        g = 계정[c]["구분"]
        if g in ("수익", "비용"):
            return 0
        return 기초[c] + (차[c] - 대[c] if g == "자산" else 대[c] - 차[c])
    r.기초, r.차, r.대, r.기말 = 기초, 차, 대, {c: 기말(c) for c in 계정}
    현금계정 = [c for c in 계정 if 계정[c]["성격"] == "현금"]
    r.현금계정 = 현금계정
    for c in 현금계정:
        n = 계정[c]["계정"].replace(" ", "").replace(".", "")
        if any(k in n for k in ("정기예금", "정기적금", "예적금")) and (계정[c]["근거"] or "").startswith("키워드"):
            r.확인.insert(0, ("정책·질문", f"{계정[c]['계정']}({c})을 현금성자산으로 봤다(잔액 {r.기말.get(c, 0) if not 잔액열어둠 else '열어둠'}). "
                                      f"취득일부터 만기 3개월 이내가 아니면 투자활동(단기금융상품)이다. 사용자에게 묻고, 아니라면 "
                                      f"--투자계정 {c} 로 다시 돌린다", None))
    r.기초현금 = sum(기초[c] for c in 현금계정)
    r.기말현금 = sum(r.기말[c] for c in 현금계정)
    r.현금증감 = r.기말현금 - r.기초현금

    _직접법(r)
    _반환상계(r)
    _적요보정(r)
    _적합성(r)
    _마무리(r)
    _간접법(r)
    _비교와최종(r)
    _정산표(r)
    _독립검산(r)
    _확인사항(r, 기말BS)
    _검증(r, 기말BS)
    return r


# ════════════════════════════════════════════ 추적 원천 풀
class _풀:
    """한 계정·한 방향의 원천(비현금분 줄). 날짜순 목록과 거래처별 목록, 금액 색인."""
    def __init__(self, units):
        self.전체 = sorted(units, key=lambda u: (u["일자"], str(u["전표"])))
        self.날짜 = [u["일자"] for u in self.전체]
        self.거래처 = defaultdict(list)
        self.금액 = defaultdict(list)
        for u in self.전체:
            self.거래처[u["거래처"]].append(u)
            self.금액[(u["거래처"], u["용량"])].append(u)
        self.거래처날짜 = {p: [u["일자"] for u in us] for p, us in self.거래처.items()}
        self.시작 = defaultdict(int)

    def 순서(self, 목록, 날짜들, 키, 일자, 앞선):
        """앞선=True: 일자 이하를 오래된 순. False: 일자 이상을 오래된 순. 다 쓴 것은 건너뛴다."""
        if 앞선:
            i = self.시작[키]
            while i < len(목록) and 목록[i]["남은"] == 0:
                i += 1
            self.시작[키] = i
            while i < len(목록) and 목록[i]["일자"] <= 일자:
                if 목록[i]["남은"] > 0:
                    yield 목록[i]
                i += 1
        else:
            for u in 목록[bisect_left(날짜들, 일자):]:
                if u["남은"] > 0:
                    yield u


원천최대 = 5


def _원천합(a, b):
    """원천 전표 목록을 합친다. 앞 다섯 개만 이름으로 두고 나머지는 건수로 센다(메모리 폭증 방지)."""
    이름 = list(dict.fromkeys(a[0] + b[0]))
    return (이름[:원천최대], a[1] + b[1] + max(0, len(이름) - 원천최대))


def _합치기(rows):
    """같은 (활동, 항목, 방법, 경로, 확인) 행을 합친다. 추적 한 단계마다 불러 행 수를 묶어 둔다."""
    g = {}
    for t in rows:
        k = (t["활동"], t["항목"], t["방법"], t["경로"], t["확인"])
        if k in g:
            g[k]["금액"] += t["금액"]
            g[k]["_원천"] = _원천합(g[k]["_원천"], t["_원천"])
        else:
            g[k] = dict(t)
    return [t for t in g.values() if t["금액"]]


def _묶기(rows, 기반):
    out = []
    for t in _합치기(rows):
        이름, 외 = t.pop("_원천")
        t["원천"] = ", ".join(이름) + (f" 외 {외}건" if 외 else "")
        out.append(t)
    return out


# ════════════════════════════════════════════ 직접법
def _직접법(r):
    계정 = r.계정
    행 = []

    def 항목(c, 금액):
        a = 계정[c]
        return a["활동"], (a["유입"] if 금액 > 0 else a["유출"])

    def 주계정(lines):
        후보 = [x for x in lines if 계정[x["코드"]]["성격"] in ("명확", "잉여금")]
        return max(후보, key=lambda x: abs(효과(x)), default=None)

    # ── 원천 풀: 비현금분의 추적 계정 줄. 역분개(부호만 반대인 같은 금액)는 먼저 서로 지운다
    원천 = defaultdict(list)
    for k, v in r.비현금부.items():
        for i, x in enumerate(v):
            if 계정[x["코드"]]["성격"] != "추적":
                continue
            d = x["차변"] - x["대변"]
            if d == 0:
                continue
            구성 = [y for j, y in enumerate(v) if j != i and (y["차변"] - y["대변"]) * d < 0]
            if not 구성:
                continue
            원천[(x["코드"], 1 if d > 0 else -1)].append(
                {"전표": str(k).rstrip("*"), "일자": x["일자"], "거래처": x["거래처"], "방향": 1 if d > 0 else -1,
                 "용량": abs(d), "남은": abs(d), "구성": 구성, "역": x["차변"] < 0 or x["대변"] < 0})
    역상계 = 0
    for (c, 방향), us in 원천.items():
        반대 = 원천.get((c, -방향), [])
        색 = defaultdict(list)
        for u in 반대:
            if not u["역"]:
                색[(u["거래처"], u["용량"])].append(u)
        for u in us:
            if u["역"] and u["남은"]:
                for w in 색.get((u["거래처"], u["용량"]), []):
                    if w["남은"] == w["용량"]:
                        w["남은"] = 0; u["남은"] = 0; 역상계 += 1
                        break
    if 역상계:
        r.확인.append(("추적", f"비현금 발생분과 그 역분개 {역상계}쌍을 서로 지웠다", None))
    풀 = {k: _풀(v) for k, v in 원천.items()}

    # ── 기초잔액 풀: 계정의 정상 방향 잔액만. 명세서가 있으면 거래처별
    기초풀 = defaultdict(list)
    명세합 = defaultdict(int)
    for m in r.명세서:
        c = m["코드"]
        if c not in 계정 or 계정[c]["성격"] != "추적" or not m["잔액"]:
            continue
        if m["잔액"] < 0:
            r.확인.append(("명세서", f"{계정[c]['계정']} {m['거래처']} 명세서 잔액이 음수({m['잔액']:,}). 기초잔액 풀에서 뺐다", m["잔액"]))
            continue
        기초풀[c].append({"거래처": m.get("거래처", ""), "남은": m["잔액"], "적요": m.get("적요", ""),
                        "활동": m.get("활동"), "항목": m.get("항목"), "원천": m.get("원천"), "명세서": True})
        명세합[c] += m["잔액"]
    for c in 계정:
        if 계정[c]["성격"] != "추적" or not r.기초[c]:
            continue
        if r.기초[c] < 0:
            r.확인.append(("잔액", f"{계정[c]['계정']} 전기말 잔액이 반대 방향({r.기초[c]:,}). 기초잔액 풀로 쓰지 않았다", r.기초[c]))
            continue
        남 = r.기초[c] - 명세합[c]
        if 남 < 0:
            r.확인.append(("명세서", f"{계정[c]['계정']} 계정명세서 합계 {명세합[c]:,}가 전기말 잔액 {r.기초[c]:,}보다 크다", 남))
        elif 남 > 0:
            기초풀[c].append({"거래처": "", "남은": 남, "적요": "", "활동": None, "항목": None, "명세서": False})

    def 감소형(c, d):
        """이 줄이 계정 잔액을 줄이는가. 줄이면 원천은 앞선 발생분(과 기초잔액)이다."""
        return (d < 0) if 계정[c]["구분"] == "자산" else (d > 0)

    def 소비(u, 금액):
        u["남은"] -= abs(금액)
        return list(zip(u["구성"], 정수배분(금액, [abs(y["차변"] - y["대변"]) for y in u["구성"]])))

    def 분류_원천(줄들, 경로, 원천id, 방법, 깊이, 기반):
        out = []
        주 = 주계정([y for y, _ in 줄들])
        for y, 금액 in 줄들:
            if 금액 == 0:
                continue
            a = 계정[y["코드"]]
            p = 경로 + [a["계정"]]
            if a["성격"] == "추적":
                if 깊이 < 최대깊이:
                    out += _추적1(y["코드"], 금액, y["차변"] - y["대변"], y["일자"], y["거래처"], p, 원천id, 깊이 + 1,
                                 dict(기반, 적요=y["적요"] or 기반["적요"]))
                else:
                    활, 항 = 항목(y["코드"], 금액)
                    out.append(dict(기반, 금액=금액, 활동=활, 항목=항, 경로=" → ".join(p), _원천=(원천id, 0),
                                    방법="추적 깊이 초과", 확인="추적이 세 번을 넘어 기본값을 썼다"))
                continue
            if a["성격"] in ("부속", "환율") and 주 is not None:
                활, 항 = 항목(주["코드"], 금액)
                p = p[:-1] + [f"{a['계정']}(→{계정[주['코드']]['계정']})"]
            elif a["성격"] == "환율":
                활, 항 = 영업, "기타 영업활동"
            else:
                활, 항 = 항목(y["코드"], 금액)
            out.append(dict(기반, 금액=금액, 활동=활, 항목=항, 경로=" → ".join(p), _원천=(원천id, 0), 방법=방법, 확인=""))
        return _합치기(out)

    def 원천판정(원, x):
        """명세서의 원천 계정(그 잔액이 생긴 계정)으로 활동·항목. 원천이 또 추적 계정이거나 규칙이 없으면 None."""
        if not 원:
            return None
        oc, on = 원
        a = 계정.get(oc) if oc is not None else None
        if a is None:
            if oc is None and on:
                a = next((v for v in 계정.values() if v["계정"].replace(" ", "") == on.replace(" ", "")), None)
            if a is None:
                a = R.판정(on or "", R.구분_코드추정(oc, on) if oc is not None else R.구분_이름추정(on), r.정책)
                a = dict(a, 계정=on or str(oc))
        if a["성격"] not in ("명확",) or a.get("기본값"):
            return None
        return a["활동"], a["유입" if x > 0 else "유출"], a["계정"]

    def _기초(c, 남, 거래처, 경로, 원천id, 기반, 같은것만):
        """기초잔액 풀. 같은것만=True 면 같은 거래처와 거래처 모름, False 면 다른 거래처."""
        out = []
        us = [u for u in 기초풀[c] if u["남은"] > 0]
        if 같은것만:
            같음 = [u for u in us if 거래처 and u["거래처"] == 거래처]
            같음.sort(key=lambda u: u["남은"] != abs(남))
            순서 = 같음 + [u for u in us if not u["거래처"]]
        else:
            순서 = [u for u in us if u["거래처"] and u["거래처"] != 거래처]
        for u in 순서:
            if not 남:
                break
            x = min(abs(남), u["남은"]) * (1 if 남 > 0 else -1)
            u["남은"] -= abs(x)
            p = " → ".join(경로 + [f"기초잔액({u['거래처']})" if u["거래처"] else "기초잔액"])
            원 = 원천판정(u.get("원천"), x)
            if u["활동"] and u["항목"]:
                out.append(dict(기반, 금액=x, 활동=u["활동"], 항목=u["항목"], 경로=p, _원천=(원천id, 0),
                                방법="기초잔액(명세서)", 확인="" if 같은것만 else "다른 거래처의 전기말 잔액을 썼다. 확인 필요"))
            elif 원:
                out.append(dict(기반, 금액=x, 활동=원[0], 항목=원[1], 경로=p + f"(원천 {원[2]})", _원천=(원천id, 0),
                                방법="기초잔액(명세서 원천)", 확인="" if 같은것만 else "다른 거래처의 전기말 잔액을 썼다. 확인 필요"))
            else:
                j = J.판정(u["적요"], x, r.정책, u["거래처"]) if u["명세서"] else None
                if j:
                    out.append(dict(기반, 금액=x, 활동=j["활동"], 항목=j["항목"], 경로=p, _원천=(원천id, 0),
                                    방법="기초잔액(명세서 적요)", 확인=f"명세서 적요 '{j['키워드']}'로 판정"))
                else:
                    활, 항 = 항목(c, x)
                    out.append(dict(기반, 금액=x, 활동=활, 항목=항, 경로=p, _원천=(원천id, 0), 방법="기초잔액",
                                    확인="전기 발생분이라 분개장에 원천이 없다"))
            남 -= x
        return out, 남

    def _추적1(c, 금액, d, 일자, 거래처, 경로, 원천id, 깊이, 기반, 단계=("건별", "기초", "거래처", "기초타", "계정")):
        out = []
        남 = 금액
        dec = 감소형(c, d)
        P = 풀.get((c, -1 if d > 0 else 1))
        if P and "건별" in 단계 and 거래처:
            same = [u for u in P.금액.get((거래처, abs(남)), [])
                    if u["남은"] == u["용량"] and ((u["일자"] <= 일자) if dec else (u["일자"] >= 일자))]
            if len(same) == 1:
                u = same[0]
                out += 분류_원천(소비(u, 남), 경로, (원천id + [u["전표"]])[-원천최대:], "건별 일치", 깊이, 기반)
                남 = 0
        if 남 and "기초" in 단계 and dec:
            o, 남 = _기초(c, 남, 거래처, 경로, 원천id, 기반, True); out += o
        if 남 and P and "거래처" in 단계 and 거래처 in P.거래처:
            for u in P.순서(P.거래처[거래처], P.거래처날짜[거래처], ("p", 거래처), 일자, dec):
                if not 남:
                    break
                x = min(abs(남), u["남은"]) * (1 if 남 > 0 else -1)
                out += 분류_원천(소비(u, x), 경로, (원천id + [u["전표"]])[-원천최대:], "거래처 순차", 깊이, 기반)
                남 -= x
        if 남 and "기초타" in 단계 and dec:
            o, 남 = _기초(c, 남, 거래처, 경로, 원천id, 기반, False); out += o
        if 남 and P and "계정" in 단계:
            for u in P.순서(P.전체, P.날짜, "all", 일자, dec):
                if not 남:
                    break
                x = min(abs(남), u["남은"]) * (1 if 남 > 0 else -1)
                out += [dict(o, 방법="계정 순차", 확인=o["확인"] or "거래처로 못 찾아 같은 계정의 오래된 발생분부터 썼다")
                        for o in 분류_원천(소비(u, x), 경로, (원천id + [u["전표"]])[-원천최대:], "계정 순차", 깊이, 기반)]
                남 -= x
        if 남 and 단계[-1] == "계정":
            활, 항 = 항목(c, 남)
            why = ("기초잔액을 넘는 결제인데 앞선 발생분이 없다" if dec
                   else "기말까지 정산되지 않아 원천이 없다(기말잔액으로 남음)")
            out.append(dict(기반, 금액=남, 활동=활, 항목=항, 경로=" → ".join(경로 + ["원천 없음"]), _원천=(원천id, 0),
                            방법="원천 없음", 확인=why))
        return _합치기(out)

    # ── 현금분을 돈다
    대기 = []
    for k, v in r.현금부.items():
        cj = r.현금줄[k][0]
        주 = 주계정(v)
        # 현금과 외화 손익(환산·차손익)만 있는 전표가 환율변동효과다. 외화예금을 매월 환산하고 다음 달 외환차손익으로
        # 되돌리는 회사가 있어서 환산만 세면 크게 부푼다. 둘을 함께 세야 순액이 맞다
        오직환율 = all(계정[x["코드"]]["성격"] == "환율" or "외환차" in 계정[x["코드"]]["계정"] for x in v)
        for x in v:
            e = 효과(x)
            a = 계정[x["코드"]]
            기반 = {"전표": k, "일자": x["일자"], "거래처": x["거래처"] or cj["거래처"], "적요": x["적요"] or cj["적요"],
                   "상대코드": x["코드"], "상대계정": a["계정"], "기본활동": a["활동"], "원id": x["원id"]}
            if a["성격"] == "추적":
                대기.append((x, e, 기반))
                continue
            if a["성격"] in ("환율", "부속") and 오직환율:
                행.append(dict(기반, 금액=e, 활동=환율, 항목=R.환율항목, 경로=a["계정"], _원천=([], 0), 방법="환율", 확인=""))
                continue
            if a["성격"] in ("부속", "환율"):
                if 주 is not None:
                    활, 항 = 항목(주["코드"], e)
                    행.append(dict(기반, 금액=e, 활동=활, 항목=항, 경로=f"{a['계정']}(→{계정[주['코드']]['계정']})",
                                  _원천=([], 0), 방법="부속(주 계정 따름)", 확인=""))
                else:
                    활, 항 = (영업, "기타 영업활동") if a["성격"] == "환율" else 항목(x["코드"], e)
                    행.append(dict(기반, 금액=e, 활동=활, 항목=항, 경로=a["계정"], _원천=([], 0), 방법="상대계정", 확인=""))
                continue
            if a["구분"] in ("수익", "비용") and any(k in a["계정"].replace(" ", "") for k in 잡계정):
                j = J.판정(기반["적요"], e, r.정책, "")
                if j and j["강도"] == "강" and j["활동"] != a["활동"]:
                    행.append(dict(기반, 금액=e, 활동=j["활동"], 항목=j["항목"], 경로=a["계정"], _원천=([], 0), 방법="상대계정+적요",
                                  확인=f"잡계정이라 적요 '{j['키워드']}'로 판정"))
                    continue
            활, 항 = 항목(x["코드"], e)
            행.append(dict(기반, 금액=e, 활동=활, 항목=항, 경로=a["계정"], _원천=([], 0), 방법="상대계정",
                          확인="규칙 없음. 기본값 적용" if a.get("기본값") else ""))

    # 역분개(음수 금액) 결제는 원래 결제와 부호만 반대로 같은 활동·항목에 둔다. 먼저 떼어 두고 끝에 붙인다
    역대기 = [t for t in 대기 if t[0].get("역")]
    대기 = [t for t in 대기 if not t[0].get("역")]
    대기.sort(key=lambda t: (t[0]["일자"], str(t[2]["전표"])))
    남은 = []
    for x, e, 기반 in 대기:     # 1단계: 건별 일치만 전 기간에 먼저
        o = _추적1(x["코드"], e, x["차변"] - x["대변"], x["일자"], x["거래처"], [계정[x["코드"]]["계정"]], [], 1, 기반,
                  단계=("건별",))
        행 += _묶기(o, 기반)
        rest = e - sum(t["금액"] for t in o)
        if rest:
            남은.append((x, rest, 기반))
    for x, e, 기반 in 남은:     # 2단계: 기초잔액 → 거래처 순차 → 다른 거래처 기초잔액 → 계정 순차 → 원천 없음
        행 += _묶기(_추적1(x["코드"], e, x["차변"] - x["대변"], x["일자"], x["거래처"], [계정[x["코드"]]["계정"]], [], 1,
                          기반, 단계=("기초", "거래처", "기초타", "계정")), 기반)
    for x, e, 기반 in 역대기:
        짝 = [t for t in 행 if t["상대코드"] == x["코드"] and t["거래처"] == 기반["거래처"] and t["금액"] * e < 0
              and not t.get("_역짝") and t["일자"] <= x["일자"]]
        남 = e
        for t in sorted(짝, key=lambda t: t["일자"], reverse=True):
            if not 남:
                break
            y = min(abs(남), abs(t["금액"])) * (1 if 남 > 0 else -1)
            t["_역짝"] = True
            if t["방법"] not in 근거방법 and y == -t["금액"]:
                # 원거래도 원천을 못 찾은 것이었다면 역분개로 지워진 것으로 표시한다
                t["방법"], t["확인"] = "역분개 상계", f"역분개(전표 {기반['전표']})로 취소됨"
            행.append(dict(기반, 금액=y, 활동=t["활동"], 항목=t["항목"], 경로=t["경로"], _원천=([str(t["전표"])], 0),
                          방법="역분개 상계", 확인=f"전표 {t['전표']}의 역분개. 같은 활동·항목으로 상계"))
            남 -= y
        if 남:
            행 += _묶기(_추적1(x["코드"], 남, x["차변"] - x["대변"], x["일자"], x["거래처"], [계정[x["코드"]]["계정"]], [], 1,
                              기반), 기반)
    for t in 행:
        t.pop("_역짝", None)
        if "_원천" in t:
            이름, 외 = t.pop("_원천")
            t["원천"] = ", ".join(이름) + (f" 외 {외}건" if 외 else "")
        t.setdefault("적요판정", "")
    r.직접행 = 행


def _쪼개기(t, x):
    a = dict(t, 금액=x)
    rest = t["금액"] - x
    return a, (dict(t, 금액=rest) if rest else None)


# ════════════════════════════════════════════ 보정
def _반환상계(r):
    """같은 추적 계정·같은 거래처(거래처가 있는 것만)에서 현금으로 나간 것과 돌아온 것을 짝지어 같은 항목에 둔다."""
    행 = r.직접행
    묶음 = defaultdict(list)
    for i, t in enumerate(행):
        if t["방법"] == "원천 없음" and t["거래처"]:
            묶음[(t["상대코드"], t["거래처"])].append(i)
    새 = {}
    for (코드, 거래처), idx in 묶음.items():
        나감 = sorted([행[i] for i in idx if 행[i]["금액"] < 0], key=lambda t: t["일자"])
        들어옴 = sorted([행[i] for i in idx if 행[i]["금액"] > 0], key=lambda t: t["일자"])
        if not 나감 or not 들어옴:
            continue
        결과 = []
        a = b = 0
        while a < len(나감) and b < len(들어옴):
            o, n = 나감[a], 들어옴[b]
            x = min(-o["금액"], n["금액"])
            j = (J.판정(o["적요"], o["금액"], r.정책, "") or J.판정(n["적요"], -n["금액"], r.정책, ""))
            활, 항 = (j["활동"], j["항목"]) if j else (o["활동"], o["항목"])
            po, ro = _쪼개기(o, -x); pn, rn = _쪼개기(n, x)
            for p, 상대 in ((po, pn), (pn, po)):
                결과.append(dict(p, 활동=활, 항목=항, 방법="현금 반환 상계",
                                확인=f"전표 {상대['전표']}와 상계(같은 거래처의 지급과 반환)"))
            if ro: 나감[a] = ro
            else: a += 1
            if rn: 들어옴[b] = rn
            else: b += 1
        결과 += 나감[a:] + 들어옴[b:]
        for i in idx:
            새[i] = None
        새[idx[0]] = 결과
    if 새:
        out = []
        for i, t in enumerate(행):
            if i in 새:
                out += 새[i] or []
            else:
                out.append(t)
        r.직접행 = out


def _발라내기(r, t, 색인):
    """뭉칫돈 가계정 행을 상세 내역으로 나눈다. 못 맞추면 None."""
    부호 = 1 if t["금액"] > 0 else -1
    전체 = [d for d in 색인[부호] if not d["사용"]]
    if not 전체:
        return None
    한건 = [d for d in 전체 if d["금액"] == t["금액"]]
    if 한건:
        import datetime as _dt
        def 거리(d):
            try:
                return abs((_dt.date.fromisoformat(d["일자"]) - _dt.date.fromisoformat(t["일자"])).days)
            except ValueError:
                return 0
        고른 = [min(한건, key=거리)]
    else:
        고른 = None
        for 묶음 in ([d for d in 전체 if d["일자"][:7] == t["일자"][:7]],
                   [d for d in 전체 if d["일자"] <= t["일자"]], 전체):
            if 묶음 and sum(d["금액"] for d in 묶음) == t["금액"]:
                고른 = 묶음
                break
        if 고른 is None:
            return None
    out = []
    for d in 고른:
        d["사용"] = True
        out.append(dict(t, 금액=d["금액"], 적요=d["적요"] or t["적요"], 거래처=d.get("거래처") or t["거래처"],
                        일자=d["일자"], 경로=t["경로"].replace("원천 없음", "상세") if "원천 없음" in t["경로"] else t["경로"] + " → 상세",
                        방법="상세", 확인=""))
    return out


def _거래처이력(r):
    """근거 있는 행에서 거래처별로 가장 많이 나온 (활동, 항목). 한 방향 80% 이상일 때만."""
    c = defaultdict(Counter)
    for t in r.직접행:
        if t["방법"] in 근거방법 and t["거래처"]:
            c[(t["거래처"], t["금액"] > 0)][(t["활동"], t["항목"])] += abs(t["금액"])
    out = {}
    for k, cnt in c.items():
        (활항, v), tot = cnt.most_common(1)[0], sum(cnt.values())
        if v >= 0.8 * tot:
            out[k] = 활항
    return out


def _적요보정(r):
    """원천으로 안 정해진 행을 상세 → 적요 → 거래처 이력 순으로 판정한다."""
    계정 = r.계정
    색인 = {1: [d for d in r.상세 if d["금액"] > 0], -1: [d for d in r.상세 if d["금액"] < 0]}
    약 = [i for i, t in enumerate(r.직접행) if t["방법"] in 약한방법]
    조각 = {}
    if r.상세:
        # 뭉칫돈 계정(가수금·가지급금 …)을 먼저, 금액이 큰 것부터 발라낸다
        대상 = [i for i in 약 if r.직접행[i]["방법"] == "원천 없음"]
        대상.sort(key=lambda i: (not any(k in r.직접행[i]["상대계정"] for k in 뭉칫돈계정), -abs(r.직접행[i]["금액"])))
        for i in 대상:
            o = _발라내기(r, r.직접행[i], 색인)
            if o:
                조각[i] = o
    out = []
    for i, t in enumerate(r.직접행):
        out += 조각.get(i, [t])
    이력 = None
    판정표 = defaultdict(list)
    for p in r.판정:
        판정표[(p["코드"], p["거래처"])].append(p)
    for t in out:
        if t["방법"] not in 약한방법 | {"상세"}:
            continue
        원방법 = t["방법"]
        ps = 판정표.get((t["상대코드"], t["거래처"])) or 판정표.get((t["상대코드"], ""))
        if ps:
            p = ps[0]
            p["쓰임"] += t["금액"]
            t.update(활동=p["활동"], 항목=p["항목"], 방법=f"{원방법}+회계사 판정",
                     확인=f"판정 파일: {p['근거'] or '근거 없음'} ({p['판정자'] or '?'} {p['판정일'] or '?'})")
            continue
        j = J.판정(t["적요"], t["금액"], r.정책, t["거래처"])
        if j:
            t.update(활동=j["활동"], 항목=j["항목"], 방법=f"{원방법}+적요",
                     확인=f"적요 '{j['키워드']}'로 판정({j['강도']})" + ("" if j["강도"] == "강" else ". 확인 필요"))
            continue
        if 이력 is None:
            이력 = _거래처이력(r)
        h = 이력.get((t["거래처"], t["금액"] > 0))
        if h:
            t.update(활동=h[0], 항목=h[1], 방법=f"{원방법}+거래처 이력",
                     확인=f"적요로 모름. 거래처 '{t['거래처']}'의 다른 거래로 판정. 확인 필요")
            continue
        if 원방법 == "상세":
            활, 항 = 계정[t["상대코드"]]["활동"], 계정[t["상대코드"]]["유입" if t["금액"] > 0 else "유출"]
            t.update(활동=활, 항목=항, 방법="상세(적요로 모름)", 확인="상세 내역 적요로도 성격을 모른다")
        elif not t["확인"]:
            t["확인"] = "적요로도 성격을 모른다"
    r.직접행 = out


def _적합성(r):
    """계정으로 정해진 행에 적요가 다른 활동을 강하게 가리키면 표시만 한다(바꾸지 않는다)."""
    r.부적합 = []
    for t in r.직접행:
        j = J.판정(t["적요"], t["금액"], r.정책, "")
        if not j:
            continue
        t["적요판정"] = f"{j['활동']}/{j['항목']} ('{j['키워드']}')"
        if t["방법"] in 근거방법 and j["강도"] == "강" and j["활동"] != t["활동"] and t["활동"] != 환율:
            t["확인"] = (t["확인"] + ". " if t["확인"] else "") + \
                f"적요 '{j['키워드']}'는 {j['활동']}활동({j['항목']})인데 계정 판정은 {t['활동']}"
            r.부적합.append(t)


def _마무리(r):
    for i, t in enumerate(r.직접행, 1):
        t["번호"] = i
    r.직접 = defaultdict(int)
    for t in r.직접행:
        r.직접[(t["활동"], t["항목"])] += t["금액"]


# ════════════════════════════════════════════ 간접법
def _간접법(r):
    계정 = r.계정
    m = defaultdict(int)
    m교차 = defaultdict(int)
    r.비현금 = []
    r.줄제외 = defaultdict(int)          # 원래 줄 id → 뺀 금액
    for v in r.전표.values():
        for x in v:
            m[x["코드"]] += 효과(x)
    for k, v in r.비현금부.items():
        활동들 = {계정[x["코드"]]["활동"] for x in v}
        if len(활동들) <= 1:
            continue
        비영업 = [x for x in v if 계정[x["코드"]]["활동"] != 영업]
        영업줄 = [x for x in v if 계정[x["코드"]]["활동"] == 영업]
        제외 = {id(x): 효과(x) for x in 비영업}
        필요 = sum(효과(x) for x in 영업줄)
        if 필요:
            부호 = 1 if 필요 > 0 else -1
            for 층 in (("자산", "부채", "자본"), ("수익", "비용")):
                if not 필요:
                    break
                후보 = [x for x in 영업줄 if 계정[x["코드"]]["구분"] in 층 and 효과(x) * 부호 > 0]
                용량 = sum(abs(효과(x)) for x in 후보)
                if not 용량:
                    continue
                뺄 = min(abs(필요), 용량) * 부호
                for x, y in zip(후보, 정수배분(뺄, [abs(효과(x)) for x in 후보])):
                    제외[id(x)] = 제외.get(id(x), 0) + y
                필요 -= 뺄
        손익 = any(계정[x["코드"]]["구분"] in ("수익", "비용") and 제외.get(id(x)) for x in v)
        for x in v:
            if 제외.get(id(x)):
                m교차[x["코드"]] += 제외[id(x)]
                r.줄제외[x.get("원id", id(x))] += 제외[id(x)]
        r.비현금.append({"전표": k, "일자": v[0]["일자"], "종류": "비현금 손익" if 손익 else "비현금 투자·재무 거래",
                        "줄": v, "적요": v[0]["적요"], "제외": {id(x): 제외.get(id(x)) for x in v}})
    r.m, r.m교차 = m, m교차

    PL = [c for c in 계정 if 계정[c]["구분"] in ("수익", "비용")]
    BS = [c for c in 계정 if 계정[c]["구분"] in ("자산", "부채", "자본") and 계정[c]["성격"] != "현금"]
    r.당기순이익 = sum(m[c] for c in PL)
    영 = [("당기순이익", r.당기순이익, "순이익", None)]
    for c in sorted(PL, key=str):
        a = 계정[c]
        if a["활동"] != 영업 and m[c]:
            영.append((f"{a['계정']} ({a['활동']}활동으로)", -m[c], "활동 이동 손익", c))
    for c in sorted(PL, key=str):
        a = 계정[c]
        if a["활동"] == 영업 and m교차[c]:
            영.append((a["계정"], -m교차[c], "현금 유출입 없는 손익", c))
    for c in sorted(BS, key=str):
        a = 계정[c]
        v = m[c] - m교차[c]
        if a["활동"] == 영업 and v:
            영.append((f"{a['계정']}의 {'감소' if v * (1 if a['구분'] == '자산' else -1) > 0 else '증가'}",
                      v, "영업 자산·부채 변동", c))
    r.간접초안 = {영업: 영, 투자: [], 재무: [], 환율: []}
    for 활 in (투자, 재무):
        for c in sorted(PL + BS, key=str):
            a = 계정[c]
            if a["활동"] == 활 and m[c] - m교차[c]:
                r.간접초안[활].append((f"{a['계정']} 순증감", m[c] - m교차[c], "계정 순증감", c))
    r.간접초안합 = {활: sum(x[1] for x in r.간접초안[활]) for 활 in 활동순서}


# ════════════════════════════════════════════ 비교·최종
def _비교와최종(r):
    r.직접합 = {활: sum(t["금액"] for t in r.직접행 if t["활동"] == 활) for 활 in 활동순서}
    재분류 = defaultdict(int)
    for t in r.직접행:
        if t["활동"] != t["기본활동"]:
            재분류[(t["상대코드"], t["상대계정"], t["기본활동"], t["활동"], t["항목"])] += t["금액"]
    r.재분류 = dict(재분류)
    r.비교 = []
    for 활 in 활동순서:
        들어옴 = sum(v for k, v in 재분류.items() if k[3] == 활)
        나감 = sum(v for k, v in 재분류.items() if k[2] == 활)
        차이 = r.직접합[활] - r.간접초안합[활]
        r.비교.append({"활동": 활, "직접법": r.직접합[활], "간접법": r.간접초안합[활], "차이": 차이,
                       "재분류": 들어옴 - 나감, "미설명": 차이 - (들어옴 - 나감)})
    조정 = []
    for (코드, 계정, 기본, 활, 항), v in sorted(r.재분류.items(), key=lambda kv: str(kv[0])):
        if 기본 == 영업:
            조정.append((재분류라벨(계정, 기본, 활, 항), -v, "추적 재분류", 코드))
        elif 활 == 영업:
            조정.append((재분류라벨(계정, 기본, 활, 항), v, "추적 재분류", 코드))
    r.간접최종영업 = r.간접초안[영업] + 조정
    r.간접최종영업합 = sum(x[1] for x in r.간접최종영업)


# ════════════════════════════════════════════ 정산표 (감사인 현금흐름 정산표 방식)
# 재무상태표 계정 한 행의 증감을 칸으로 모두 설명한다.
#   I 비용가산 · K 수익차감 · M 영업자산부채 증감 · O/Q 투자 유입/유출 · S/U 재무 유입/유출 · W/Y 비현금 차변/대변 · AA 환율
# 현금영향(대변-차변) m = I - K + M + O - Q + S - U - W + Y + AA 가 모든 행에서 성립한다.
# O·Q·S·U·AA·M(비영업 계정)은 워크북에서 분개장 분류를 SUMIFS 로 가져온다. 여기서는 비현금분을 I·K·W·Y 로 나눈다.
_비현금손익 = ("감가상각", "상각비", "대손상각", "충당금환입", "충당금전입", "충당부채전입", "퇴직급여", "평가손", "평가이익",
             "외화환산", "외환차", "손상", "처분손", "처분이익", "폐기", "감모", "주식보상", "지분법")
# 외화 손익은 한 라벨로 묶어 행마다 순액으로 둔다. 매월 환산하고 다음 달 외환차손익으로 되돌리는 회사에서
# 환산만 따로 세면 손익계산서보다 크게 부푼다
_외화라벨 = "외화환산손익"
_장기성 = ("충당", "퇴직", "누계", "보조금")


def _보일것(계정, 상대):
    """비현금분에서 이 짝을 정산표 칸(I·K·W·Y)에 드러낼지. 아니면 영업자산부채 증감(M)에 남는다."""
    a, c = 계정, 상대
    if a["활동"] != 영업:
        return True
    if any(k in a["계정"] for k in _장기성):
        return True
    if c["구분"] in ("수익", "비용"):
        return any(k in c["계정"] for k in _비현금손익)
    return c["활동"] != a["활동"]


def _정산표(r):
    계정 = r.계정
    칸 = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))    # 코드 → 칸 → 라벨 → 금액(양수)
    라벨코드 = {}
    줄정산 = defaultdict(lambda: defaultdict(int))   # 원 분개 줄 id → (칸, 라벨) → 현금영향 부호 금액. 분개장 정산 열
    라벨활동 = {}
    for v in r.비현금부.values():
        양 = [[x, 효과(x)] for x in v if 효과(x) > 0]
        음 = [[x, -효과(x)] for x in v if 효과(x) < 0]
        i = j = 0
        while i < len(양) and j < len(음):
            a = min(양[i][1], 음[j][1])
            p, n = 양[i][0], 음[j][0]
            pa, na = 계정[p["코드"]], 계정[n["코드"]]
            양BS = pa["구분"] in ("자산", "부채", "자본") and na["구분"] in ("자산", "부채", "자본")
            # 재무상태표 두 계정 사이의 짝은 양쪽 행에 똑같이 적어야 비현금 차변 = 대변이 된다. 한쪽이라도 드러낼 대상이면 둘 다
            짝보임 = 양BS and (_보일것(pa, na) or _보일것(na, pa))
            for x, cp, amt in ((p, n, a), (n, p, -a)):
                xa, ca = 계정[x["코드"]], 계정[cp["코드"]]
                oid = x.get("원id", id(x))
                if xa["구분"] in ("수익", "비용"):
                    줄정산[oid][("순이익", "")] += amt
                    continue
                if xa["구분"] not in ("자산", "부채", "자본") or xa["성격"] == "현금":
                    continue
                if not (짝보임 if 양BS else _보일것(xa, ca)):
                    줄정산[oid][("영업잔차", "")] += amt
                    continue
                if ca["구분"] in ("수익", "비용"):
                    k = "I" if amt > 0 else "K"
                    if "외화환산" in ca["계정"] or "외환차" in ca["계정"]:
                        칸[x["코드"]][k][_외화라벨] += abs(amt)
                        줄정산[oid][("손익", _외화라벨)] += amt
                        continue
                    라벨코드[ca["계정"]] = cp["코드"]
                else:
                    k = "Y" if amt > 0 else "W"
                칸[x["코드"]][k][ca["계정"]] += abs(amt)
                if ca["구분"] in ("수익", "비용"):
                    줄정산[oid][("손익", ca["계정"])] += amt
                else:
                    줄정산[oid][("비현금", ca["계정"])] += amt
                    라벨활동[ca["계정"]] = ca["활동"]
            양[i][1] -= a; 음[j][1] -= a
            if not 양[i][1]: i += 1
            if not 음[j][1]: j += 1
    # 한 행에서 같은 라벨이 양쪽(비용가산·수익차감, 비현금 차변·대변)에 있으면 역분개·대체라 순액만 남긴다
    for c, d in 칸.items():
        for 가, 나 in (("I", "K"), ("Y", "W")):
            for lab in set(d.get(가, {})) & set(d.get(나, {})):
                x = d[가][lab] - d[나][lab]
                d[가][lab], d[나][lab] = max(x, 0), max(-x, 0)
            for k in (가, 나):
                for lab in [l for l, v in d.get(k, {}).items() if not v]:
                    del d[k][lab]
    r.정산칸 = 칸
    r.정산라벨코드 = 라벨코드
    r.줄정산 = 줄정산
    r.정산라벨활동 = 라벨활동
    합 = lambda k: sum(v for c in 칸 for v in 칸[c].get(k, {}).values())
    if 합("W") != 합("Y"):
        r.확인.append(("정산표", f"비현금 차변 {합('W'):,} / 대변 {합('Y'):,} 이 다르다(엔진 오류)", 합("W") - 합("Y")))
    # 손익계정 중 현금분이 영업 외 활동으로 간 것(이자 지급을 재무로, 처분이익 현금분 등)
    r.정산손익 = sorted({t["상대코드"] for t in r.직접행
                       if 계정[t["상대코드"]]["구분"] in ("수익", "비용") and t["활동"] != 영업}, key=str)


# ════════════════════════════════════════════ 독립 검산
# 직접법과 정산표의 일치는 같은 분개장 분류를 공유해서 구조상 늘 맞는다. 분류가 맞는지는 알려주지 않는다.
# 아래 셋은 분류와 무관한 사실(손익계정의 성격, 잔액, 비현금 대체액, 손익계산서)로 분류 결과를 확인한다.
def 비현금성손익(이름):
    n = 이름.replace(" ", "")
    return any(k in n for k in _비현금손익) and "외화환산" not in n and "외환차" not in n


def _독립검산(r):
    계정 = r.계정
    현금분 = defaultdict(int)
    for t in r.직접행:
        현금분[t["상대코드"]] += t["금액"]
    쓰인 = {x["코드"] for v in r.전표.values() for x in v}
    # A. 비현금 성격 손익(감가상각비·상각비·대손상각비·평가·손상·처분손익)은 현금이 오가면 안 된다
    A = []
    for c in sorted(쓰인, key=str):
        a = 계정[c]
        if a["구분"] in ("수익", "비용") and 비현금성손익(a["계정"]):
            A.append({"코드": c, "계정": a["계정"], "현금분": 현금분.get(c, 0), "통과": 현금분.get(c, 0) == 0})
    # B. 추적 계정에서 투자·재무로 간 현금은 그 계정의 비현금 대체액과 잔액이 허락하는 범위 안이어야 한다
    대체 = defaultdict(int)       # (계정, 활동, 방향) → 금액
    원줄 = {}
    for v in r.전표.values():
        for x in v:
            원줄[id(x)] = x
    for oid, d in r.줄정산.items():
        x = 원줄.get(oid)
        if x is None or 계정[x["코드"]]["성격"] != "추적":
            continue
        for (k, lab), amt in d.items():
            활 = r.정산라벨활동.get(lab)
            if k == "비현금" and 활 in (투자, 재무) and amt:
                대체[(x["코드"], 활, "유출" if amt > 0 else "유입")] += abs(amt)
    # 상한용: 추적 계정 줄이 든 비현금분에 투자·재무 계정(또는 다른 추적 계정)이 함께 있으면 그 줄 금액 전부.
    # 비품과 함께 외상으로 산 부가세, 미지급금 → 가지급금 → 비품 같은 두 단계를 하한용 짝 금액은 못 잡는다
    상한 = defaultdict(int)
    경유 = defaultdict(int)
    경유대상 = defaultdict(set)
    r.상한대체 = {}
    for v in r.비현금부.values():
        활들 = {계정[y["코드"]]["활동"] for y in v}
        추적들 = {y["코드"] for y in v if 계정[y["코드"]]["성격"] == "추적"}
        for x in v:
            c = x["코드"]
            if 계정[c]["성격"] != "추적" or not 효과(x):
                continue
            꼬리 = 투자 if 투자 in 활들 else 재무 if 재무 in 활들 else ("추적경유" if 추적들 - {c} else None)
            if not 꼬리:
                continue
            r.상한대체[x.get("원id", id(x))] = (꼬리, r.상한대체.get(x.get("원id", id(x)), (None, 0))[1] + 효과(x))
            방 = "유출" if 효과(x) > 0 else "유입"
            if 꼬리 == "추적경유":
                # 다른 추적 계정을 거쳐 투자·재무로 갈 수 있는 몫. 그 계정들의 실제 투자·재무 대체액을 넘을 수 없다
                for 활 in (투자, 재무):
                    경유[(c, 활, 방)] += abs(효과(x))
                    경유대상[(c, 활, 방)] |= 추적들 - {c}
            else:
                상한[(c, 꼬리, 방)] += abs(효과(x))
    대체총 = defaultdict(int)
    for (u, 활, _), v in 대체.items():
        대체총[(u, 활)] += v
    r.경유대상 = 경유대상
    for key, v in 경유.items():
        상한[key] += min(v, sum(대체총[(u, key[1])] for u in 경유대상[key]))
    결제 = defaultdict(int)
    for t in r.직접행:
        if 계정[t["상대코드"]]["성격"] == "추적" and t["활동"] in (투자, 재무):
            결제[(t["상대코드"], t["활동"], "유출" if t["금액"] < 0 else "유입")] += abs(t["금액"])
    B = []
    for key in sorted(set(대체) | set(결제), key=str):
        c, 활, 방향 = key
        자산 = 계정[c]["구분"] == "자산"
        기초, 기말 = max(r.기초.get(c, 0), 0), max(r.기말.get(c, 0), 0)
        발생먼저 = (방향 == "유출") != 자산       # 미지급금 결제·미수금 회수: 발생이 먼저
        a, amax, pay = 대체.get(key, 0), 상한.get(key, 0), 결제.get(key, 0)
        # 하한 완화: 그 계정이 현금 없이 반대쪽으로 움직인 금액(유출이면 비현금 차변, 유입이면 비현금 대변).
        # 가지급금이 미지급금으로 생겨 비품으로 대체되면 현금 없이도 대체가 채워진다
        현금쪽 = sum(-t["금액"] for t in r.직접행 if t["상대코드"] == c and t["금액"] < 0) if 방향 == "유출" \
            else sum(t["금액"] for t in r.직접행 if t["상대코드"] == c and t["금액"] > 0)
        비현금반대 = max(0, (r.차.get(c, 0) if 방향 == "유출" else r.대.get(c, 0)) - 현금쪽)
        하한 = max(0, a - (기말 if 발생먼저 else 기초) - 비현금반대)
        상한값 = max(a, amax) + (기초 if 발생먼저 else 기말)
        # 분류가 맞다면 기말에 이 계정에 남아 있어야 할 투자·재무 관련 잔액. 기말 계정명세서와 대조하면 강한 검산이 된다
        if 발생먼저:
            남하, 남상 = max(0, a - pay), max(0, max(a, amax) + 기초 - pay)
        else:
            남하, 남상 = max(0, pay - max(a, amax)), max(0, 기초 + pay - a)
        B_남 = (min(남하, 기말), min(남상, 기말))
        B.append({"코드": c, "계정": 계정[c]["계정"], "활동": 활, "방향": 방향, "비현금대체": a, "상한용대체": max(a, amax),
                  "기말관련잔액_추정": B_남, "잔액열어둠": r.잔액열어둠,
                  "비현금반대": 비현금반대,
                  "분류된현금": pay, "기초": 기초, "기말": 기말, "하한": 하한, "상한": 상한값, "발생먼저": 발생먼저,
                  "통과": 하한 <= pay <= 상한값})
    # C. 비현금 성격 손익은 손익계산서 금액 = 정산표 가감 + 현금분(부호 맞춰)
    순 = defaultdict(int)
    for c, d in r.정산칸.items():
        for lab, v in d.get("I", {}).items():
            순[lab] += v
        for lab, v in d.get("K", {}).items():
            순[lab] -= v
    C = []
    for x in A:
        c = x["코드"]; a = 계정[c]
        비용 = a["구분"] == "비용"
        손익 = -r.m.get(c, 0) if 비용 else r.m.get(c, 0)
        가감 = 순.get(a["계정"], 0) if 비용 else -순.get(a["계정"], 0)
        차이 = 손익 - 가감 + (x["현금분"] if 비용 else -x["현금분"])
        C.append({"코드": c, "계정": a["계정"], "손익계산서": 손익, "정산표가감": 가감, "현금분": x["현금분"], "차이": 차이,
                  "통과": 차이 == 0})
    if r.잔액열어둠:
        for x in B:
            x["통과"] = None          # 기초·기말을 모르면 범위를 못 정한다
    r.독립 = {"A": A, "B": B, "C": C}
    r.독립통과 = all(x["통과"] is not False for k in "ABC" for x in r.독립[k])
    for x in A:
        if not x["통과"]:
            r.확인.append(("독립검산", f"{x['계정']}은 비현금 성격인데 현금분 {x['현금분']:,}가 있다. 분개 확인", x["현금분"]))
    for x in B:
        if x["통과"] is False:
            r.확인.append(("독립검산", f"{x['계정']}에서 {x['활동']} {x['방향']}으로 분류한 현금 {x['분류된현금']:,}가 "
                                      f"잔액·비현금 대체로 가능한 범위({x['하한']:,} ~ {x['상한']:,}) 밖이다. 추적 판정 확인", x["분류된현금"]))
    for x in C:
        if not x["통과"]:
            r.확인.append(("독립검산", f"{x['계정']} 손익계산서 {x['손익계산서']:,} ≠ 정산표 가감 {x['정산표가감']:,} + 현금분. "
                                      f"차이 {x['차이']:,}(비현금분이 영업자산부채 증감에 남았을 수 있다)", x["차이"]))


def 재분류라벨(계정, 기본, 활, 항):
    if 활 == 환율:
        return f"{계정} 중 {R.환율항목}"
    if 기본 == 영업:
        return f"{계정} 중 {활}활동({항})"
    return f"{계정} 중 영업활동({항})"


# ════════════════════════════════════════════ 확인사항·검증
def _확인사항(r, 기말BS):
    계정 = r.계정
    쓰인 = {x["코드"] for v in r.전표.values() for x in v} | {c for c, v in r.기초.items() if v}
    for c in sorted(쓰인, key=str):
        a = 계정[c]
        if a.get("기본값"):
            r.확인.append(("계정", f"{a['계정']}({c}) 규칙 없음. 추적·적요로 판정하고 남은 것은 {a['활동']}활동 기본값", abs(r.m.get(c, 0))))
        if r.잔액열어둠:
            pass
        elif a["구분"] == "자산" and r.기말[c] < 0 and not any(k in a["계정"] for k in ("누계액", "충당금", "보조금")):
            r.확인.append(("잔액", f"{a['계정']} 기말잔액이 음수({r.기말[c]:,})", r.기말[c]))
        if a["구분"] in ("부채", "자본") and r.기말[c] < 0 and a["성격"] != "잉여금" and not r.잔액열어둠:
            r.확인.append(("잔액", f"{a['계정']} 기말잔액이 음수({r.기말[c]:,})", r.기말[c]))
        if a["활동"] == 투자 and any(k in a["계정"] for k in ("정기예금", "정기적금", "단기금융상품", "양도성예금", "금융상품")):
            r.확인.append(("정책", f"{a['계정']}: 취득일부터 만기 3개월 이내면 현금성자산이다. 만기 확인", None))
        if "단기매매" in a["계정"] or "공정가치" in a["계정"]:
            r.확인.append(("정책", f"{a['계정']}: 단기매매 목적이면 영업활동(K-IFRS 1007 문단 15), 아니면 투자활동. 현재 {a['활동']}", None))
    for (활, 항), v in sorted(r.직접.items()):
        if 항 in ("이자의 수취", "이자의 지급", "배당금의 수취", "배당금의 지급") and v and r.기준 == "K-IFRS1118":
            r.확인.append(("정책", f"{항} {v:,}원을 {활}활동으로 분류했다(K-IFRS 1118 이 고친 제1007호). 주된 사업활동이 "
                                  "금융·투자인 회사(금융회사·지주회사 등)는 분류가 다르니 확인", v))
        if 항 in ("이자의 수취", "이자의 지급", "배당금의 수취", "배당금의 지급") and v and r.기준 == "K-IFRS":
            r.확인.append(("정책", f"{항} {v:,}원을 {활}활동으로 분류했다(K-IFRS 1007 문단 31~34, 회사 정책으로 매기 일관 적용)", v))
    # 회계사 판정 파일
    for p in r.판정:
        if not p["쓰임"]:
            r.확인.append(("판정", f"판정 파일 {p['코드']} {p['거래처'] or '(거래처 전체)'} → {p['활동']}/{p['항목']}: 이번 기간에 맞는 행이 없다", None))
    # 유형·무형자산 대금을 부채로 두었다가 나중에 낸 것. 투자(취득 직후 지급)냐 재무(자산 취득에 따른 부채의 지급)냐
    늦은, 건 = 0, 0
    for t in r.직접행:
        if t["활동"] != 투자 or t["항목"] not in ("유형자산의 취득", "무형자산의 취득") or "→" not in t["경로"]:
            continue
        if "기초잔액" in t["경로"]:
            늦은 += t["금액"]; 건 += 1
            continue
        첫 = (t.get("원천") or "").split(",")[0].split(" 외")[0].strip()
        원일 = r.전표[첫][0]["일자"] if 첫 in r.전표 else None
        if 원일 and (datetime.date.fromisoformat(t["일자"][:10]) - datetime.date.fromisoformat(원일[:10])).days > 90:
            늦은 += t["금액"]; 건 += 1
    if 건:
        r.확인.append(("정책", f"유형·무형자산 대금을 미지급금 등으로 두었다가 전기에 또는 취득 90일 뒤에 지급한 {늦은:,}원({건}행)을 "
                              "투자활동으로 분류했다. 일반기업회계기준은 취득 직전 또는 직후의 지급액은 투자(2.68), 자산의 취득에 따른 "
                              "부채의 지급은 재무(2.71)로 적는다. 「직후」의 기간 기준은 기준서에 없고 90일은 이 스킬이 정한 참고값이다", 늦은))
    방법별 = defaultdict(int)
    for t in r.직접행:
        if t["방법"] not in 근거방법:
            방법별[(t["상대계정"], t["방법"], t["활동"], t["항목"])] += t["금액"]
    for (계, 방, 활, 항), v in sorted(방법별.items(), key=lambda kv: -abs(kv[1])):
        if 방.endswith("+회계사 판정"):
            continue
        r.확인.append(("판정", f"{계} {방} → {활}/{항} {v:,}원", v))
    if r.부적합:
        합 = sum(t["금액"] for t in r.부적합)
        묶 = Counter((t["상대계정"], t["확인"].split("적요 '")[-1].split("'")[0], t["활동"]) for t in r.부적합)
        상위 = ", ".join(f"{a}·'{b}' {n}건" for (a, b, _), n in 묶.most_common(5))
        r.확인.append(("적합성", f"적요와 계정 판정이 다른 행 {len(r.부적합)}건({합:,}원). 많은 순: {상위}", 합))
    if r.상세:
        쓴 = sum(1 for d in r.상세 if d["사용"])
        r.확인.append(("상세", f"상세 내역 {len(r.상세)}건 중 {쓴}건을 가계정 발라내기에 썼다", None))
    복합 = defaultdict(set)
    for t in r.직접행:
        복합[t["전표"]].add(t["활동"])
    n = [k for k, s in 복합.items() if len(s) > 1]
    if n:
        r.확인.append(("전표", f"현금 전표 {len(n)}건이 두 활동 이상에 걸친다(직접법_추적에서 전표번호로 확인)", None))
    투재 = [x for x in r.비현금 if x["종류"] == "비현금 투자·재무 거래"]
    if 투재:
        합 = sum(-(v or 0) for x in 투재 for y in x["줄"] for k, v in [(id(y), x["제외"].get(id(y)))]
                if 계정[y["코드"]]["활동"] == 투자)
        r.확인.append(("비현금거래", f"현금이 오가지 않은 투자·재무 거래 {len(투재)}건(투자 쪽 {합:,}원). 비현금거래 시트, 주석 공시 대상(K-IFRS 1007 문단 43)", None))
    if r.이체:
        r.확인.append(("현금", f"현금 계정끼리 옮기거나 현금 순액이 0 인 전표 {len(r.이체)}건은 현금흐름에서 뺐다", sum(x[2] for x in r.이체)))
    r.기말대조 = []
    if 기말BS:
        주어진 = defaultdict(int)
        for b in 기말BS:
            주어진[b["코드"]] += b["잔액"]
        잉여 = {c for c in 계정 if 계정[c]["성격"] == "잉여금"}
        for c in sorted(set(주어진) | {c for c in r.기말 if 계정[c]["구분"] in ("자산", "부채", "자본")}, key=str):
            if c in 잉여:
                continue
            v = r.기말.get(c, 0)
            if v != 주어진.get(c, 0):
                r.기말대조.append((c, 계정.get(c, {}).get("계정", str(c)), v, 주어진.get(c, 0)))
        if 잉여:
            v = sum(r.기말.get(c, 0) for c in 잉여) + r.당기순이익
            g = sum(주어진.get(c, 0) for c in 잉여)
            if v != g:
                r.기말대조.append(("잉여금", "이익잉여금 합계(분개장 + 당기순이익)", v, g))
        for c, n_, v, g in r.기말대조:
            r.확인.append(("기말대조", f"{n_}: 분개장 기말 {v:,} / 주어진 기말 {g:,} (차이 {v - g:,})", v - g))


def _검증(r, 기말BS):
    직합 = sum(r.직접합.values())
    간합 = sum(r.간접초안합.values())
    현금대조 = None
    if 기말BS:
        주어진 = sum(b["잔액"] for b in 기말BS if b["코드"] in r.현금계정)
        현금대조 = r.기말현금 - 주어진
    if r.손익NI is not None and r.손익NI != r.당기순이익:
        r.확인.append(("손익대조", f"분개장 당기순이익 {r.당기순이익:,} / 손익계산서 {r.손익NI:,} (차이 {r.당기순이익 - r.손익NI:,})",
                      r.당기순이익 - r.손익NI))
    미분류 = sum(1 for t in r.직접행 if t["활동"] not in 활동순서)
    r.검증 = [
        ("직접법 합계 = 기말현금 - 기초현금", 직합 - r.현금증감),
        ("간접법 합계 = 기말현금 - 기초현금", 간합 - r.현금증감),
        ("직접법 미분류 현금 줄 0", 미분류),
        ("활동별 차이가 재분류로 전부 설명됨", sum(abs(x["미설명"]) for x in r.비교)),
        ("최종 간접법 영업활동 = 직접법 영업활동", r.간접최종영업합 - r.직접합[영업]),
        ("현금 계정 간 이체 순액 0", sum(x[2] for x in r.이체)),
        ("분개장 기말현금 = 주어진 기말 재무상태표 현금", 현금대조),
        ("분개장 당기순이익 = 손익계산서 당기순이익", None if r.손익NI is None else r.당기순이익 - r.손익NI),
    ]
    r.통과 = all(v in (0, None) for _, v in r.검증)
