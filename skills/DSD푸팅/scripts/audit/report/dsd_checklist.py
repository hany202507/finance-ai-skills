"""연결 유형 점검표(2026-11-08, DSD 시험 3단계 D9 · D10).

같은 보고서를 세 번 처음부터 돌렸더니 실행마다 거는 연결이 6.6 ~ 11.4% 달랐고, 실제 불일치를 실행마다 다르게 놓쳤다.
AI 는 references/연결-유형.md 에서 주석 제목의 절만 골라 읽는다. 그래서 잘 걸지 않는 유형을 엔진이 보고서에서 찾아 연결_초안.json
「할 일」 에 「점검:」 줄로 낸다. AI 는 점검 줄마다 links · tables · calcs · sums 로 걸거나 skipped 에 까닭을 적는다.
점검 줄의 유형은 정답과 견준 시험에서 놓친 불일치와, 늘 나는 차이를
FALSE 로 매긴 꼴에서 왔다. 연결 방법(등급 · 조건)도 함께 적어 실행마다 같은 등급이 나오게 한다.

    items(doc) -> [str]
"""
from __future__ import annotations

import re

from .base import norm
from .dsd_grid import Doc, Table
from .dsd_links import _isnum, _labels


def _title(doc: Doc, t: Table) -> str:
    try:
        return doc.part_of(t.id).title or ""
    except Exception:
        return ""


def _has(t: Table, pat: str, where: str = "rows") -> bool:
    rx = re.compile(pat)
    if where in ("rows", "both") and any(rx.search(norm(x)) for x in _labels(t)):
        return True
    if where in ("head", "both") and any(rx.search(norm(h)) for h in t.header):
        return True
    return False


def _money(t: Table) -> bool:
    return any(_isnum(v) for r in t.nums for v in r[1:])


def items(doc: Doc) -> list[str]:
    out: list[str] = []
    tabs = [t for t in doc.tables() if not t.kind and t.id.startswith("주석") and _money(t)]
    by_title = {t.id: norm(_title(doc, t)) for t in tabs}

    def note(rx: str) -> list[Table]:
        r = re.compile(rx)
        return [t for t in tabs if r.search(by_title[t.id]) or r.search(norm(t.caption or ""))]

    def ids(ts) -> str:
        return ", ".join(t.id for t in ts[:8]) + (" 등" if len(ts) > 8 else "")

    # 1. 주식기준보상: 변동표 기초 · 기말 수량 = 회차별 표 잔여수량 합(한 상장사 주석21-12 ↔ 21-1 30주를 11-08 재시험이 놓쳤다)
    sb = note(r"주식기준보상|주식선택권|주식매수선택권|양도제한조건부|성과조건부|RSU|PSU")
    moves = [t for t in sb if _has(t, r"^기초|기초잔여|^기말|기말잔여")]
    grants = [t for t in sb if _has(t, r"\d+차|\d+회|회차|부여일", "both") and t not in moves]
    if moves and grants:
        out.append(f"점검: 주식기준보상 변동표({ids(moves)})의 기초 · 기말 수량 = 회차별 표({ids(grants)})의 같은 주식 잔여수량 합. "
                   "회사 · 주식 종류마다 links 로 칸 합을 적는다(항등식)")
    # 2. 비현금거래 ↔ 변동표 증가(사용권자산 · 리스부채, 유무형 취득)
    nc = [t for t in tabs if _has(t, r"사용권자산.*인식|리스부채.*인식|사용권자산의증가|리스부채의증가|미지급.*취득|비현금")]
    if nc:
        out.append(f"점검: 비현금거래 표({ids(nc)})의 사용권자산 · 리스부채 인식 = 리스 주석 사용권자산 증가(취득) · 리스부채 증가, "
                   "미지급 취득 = 유형 · 무형 변동표 취득 - 현금흐름표 취득. 조건부(when: 리스 변경 · 해지 · 사업결합을 따로 적었다)로 건다")
    # 3. 현금흐름표 조정의 퇴직급여 줄 ↔ 퇴직급여 주석(재측정요소는 현금이 아니다)
    cfp = [t for t in tabs if _has(t, r"퇴직연금운용자산|사외적립자산") and _has(t, r"퇴직금의지급|퇴직금지급|확정급여채무|퇴직급여채무")
           and re.search(r"현금흐름", by_title[t.id] + norm(t.caption or ""))]
    if cfp:
        out.append(f"점검: 현금흐름 조정 표({ids(cfp)})의 퇴직연금운용자산 · 확정급여채무 줄 = 퇴직급여 주석의 지급 · 불입(재측정요소 · 이자는 빼고). "
                   "재측정요소가 섞였으면 보고서 불일치다")
    # 4. 법인세: 세율 조정표 합계, 자본에 직접 가감된 법인세 ↔ OCI 세효과, 일시적차이 표 ↔ 재무상태표
    tax = note(r"법인세")
    adj = [t for t in tax if _has(t, r"적용세율|세율에따른|법인세비용차감전")]
    if adj:
        out.append(f"점검: 법인세 세율 조정표({ids(adj)})는 적용세율 세부담액 + 조정 줄 = 법인세비용(sums, 항등식). 안 맞으면 구조를 바꾸지 말고 판정한다")
    oci = [t for t in tax if _has(t, r"자본에직접|기타포괄|직접가감")]
    if oci:
        out.append(f"점검: 법인세 주석의 자본에 직접 가감된 법인세({ids(oci)}) = 기타포괄손익 항목별 법인세효과 합. 부호를 두 해 다 견준다")
    temp = [t for t in tax if _has(t, r"기초|기말", "head") and _has(t, r"충당|미지급|감가상각|퇴직급여")]
    if temp:
        out.append(f"점검: 이연법인세 일시적차이 표({ids(temp)})의 기말 = 재무상태표 같은 과목 잔액(조건부: 세무상 금액이 장부와 같다). "
                   "차이가 잔액 × 세율과 같으면 일시적차이 열에 법인세효과를 적은 표시 오류다")
    # 4-2. 인식하지 않은 세무상결손금 · 이월세액공제 ↔ 일시적차이 표의 이월결손금 · 이월세액공제(한 상장사 주석26-7 ↔ 26-3:
    # 「이월결손금과 이월세액공제에 대해서는 이연법인세자산을 인식하지 않았습니다」 인데 금액이 달랐다. 세 실행 가운데 하나만 냈다)
    unrec = [t for t in tax if re.search(r"인식(?:하지않|되지아니|하지아니)", norm(t.caption or "")) and _has(t, r"결손금|세액공제", "both")]
    carry = [t for t in tax if t not in unrec and _has(t, r"이월결손금|세무상결손금") and _has(t, r"기말", "head")]
    if unrec and carry:
        out.append(f"점검: 이연법인세를 인식하지 않은 세무상결손금 · 이월세액공제 표({ids(unrec)}) ↔ 일시적차이 표({ids(carry)})의 이월결손금 · 이월세액공제 기말. "
                   "주석 문장이 「이월결손금(이월세액공제)에 대해 이연법인세자산을 인식하지 않았다」 고 적었으면 항등식, 일부만 인식했으면 조건부(when). "
                   "소멸시기 표의 합계도 같은 금액이다")
    # 4-3. 범주별 손익의 리스 범주 ↔ 리스 주석 이자(한 상장사 별도 11-09: 같은 보고서 두 번 실행에서 한 번은 항등식으로 걸어 51,043천원 차이를
    # 숫자 오류로 냈고, 한 번은 「리스 이자 ≤ 기타금융자산 이자」 로 걸어 놓쳤다. 연결 보고서도 세 실행 가운데 하나가 놓쳤다)
    lease_int = [t for t in tabs if _has(t, r"리스채권.*이자|리스부채.*이자")]
    cat = [t for t in tabs if t not in lease_int and _has(t, r"^기타금융자산|^기타금융부채", "both")
           and (_has(t, r"이자|손익", "both") or re.search(r"범주|순손익", norm(t.caption or "")))]
    if lease_int and cat:
        out.append(f"점검: 범주별 손익 표({ids(cat)})의 기타금융자산 · 기타금융부채 이자 ↔ 리스 주석({ids(lease_int)})의 리스채권 이자수익 · 리스부채 이자비용. "
                   "범주별 장부금액 표에서 그 범주에 든 과목이 리스채권 · 리스부채뿐인지 보고, 그러면 항등식으로 건다(cmp: le 를 쓰지 않는다). "
                   "다른 과목도 들어 있으면 조건부")
    # 5. 만기분석이 여러 주석에 있으면 서로 잇는다(공개 연결 보고서: 리스부채 1년 이내가 주석19 와 주석31 에서 506 다름)
    mat = [t for t in tabs if _has(t, r"이내|미만|초과", "head") and _has(t, r"리스부채|차입금|사채")]
    if len({t.id.split("-")[0] for t in mat}) >= 2:
        out.append(f"점검: 만기분석 표가 여러 주석에 있다({ids(mat)}). 같은 과목 · 같은 구간 칸을 links 로 잇는다(항등식)")
    # 6. 요약재무정보: 자본 = 자산 - 부채(회사마다)
    def _ae(t: Table) -> bool:
        return _has(t, r"^자산|자산계|자산총계|^유동자산|^비유동자산", "both") and _has(t, r"^부채|부채계|부채총계|^유동부채|^비유동부채", "both")
    summ = [t for t in tabs if _ae(t)]
    eq = [t for t in summ if _has(t, r"^자본|자본계|자본총계|순자산", "both")]
    if eq:
        out.append(f"점검: 요약재무정보 표({ids(eq)})는 회사마다 자본(순자산) = 자산 - 부채(sums · calcs, 항등식)")
    # 6-2. 같은 주석의 장부금액 조정표: 요약재무정보 순자산 = 조정표 순자산(한 상장사 주석12-5 19,950,000 을 실행 셋 가운데 하나만 걸었다)
    notes = {t.id.split("-")[0] for t in summ}
    rec = [t for t in tabs if t.id.split("-")[0] in notes and t not in summ
           and _has(t, r"지분율|지분해당|지분상당|귀속순자산|순자산", "both")
           and (_has(t, r"장부금액|장부가액", "both") or re.search(r"장부금액|장부가액", norm(t.caption or "")))]
    rn = {t.id.split("-")[0] for t in rec}
    sr = [t for t in summ if t.id.split("-")[0] in rn]
    if sr and rec:
        out.append(f"점검: 요약재무정보 표({ids(sr)})의 순자산(자산 - 부채) = 장부금액 조정표({ids(rec)})의 순자산 · 보통주 귀속 순자산"
                   "(회사 · 기간마다 links, 항등식). 연결재무제표를 내는 관계기업(비지배지분) · 금융업 관계기업 · 「지배주주지분만」 각주가 붙은 회사는 "
                   "조건부(when: 요약재무정보가 관계기업의 연결 금액이거나 금융업이라 순자산이 자본과 다를 수 있다)나 only. 이 회사들의 차이는 확인이다. "
                   "순자산 × 지분율은 걸지 않는다(연결-유형.md 관계기업 절). 한 기간만 다르면 판정에서 그 기간 칸을 본다")
        # 조정표 줄마다 순자산 지분 + 조정 열 = 장부금액(가로 합). 한 상장사 주석12-6 한 관계기업 줄이 62,660 안 맞는 것을 실행 셋이 모두 놓쳤다
        out.append(f"점검: 장부금액 조정표({ids(rec)})는 회사마다 순자산 지분 금액 + 조정 열(투자차액 · 내부거래 · 손상 · 기타) = 장부금액(가로 sums, 항등식). "
                   "지분법 적용을 중지한 회사(장부금액 0, 미반영 손실)는 조정 열에 그 금액이 있어야 맞는다")
    # 7. 현금흐름표 조정의 외화환산손익 ↔ 손익계산서(늘 나는 차이를 FALSE 로 매겼다. 공개 별도 보고서)
    fx = [t for t in doc.tables() if t.id.startswith("현금흐름표") and _has(t, r"외화환산")] + [t for t in tabs if _has(t, r"외화환산") and re.search(r"현금흐름", by_title[t.id])]
    if fx:
        out.append(f"점검: 현금흐름 조정의 외화환산이익 · 손실({ids(fx)}) ↔ 손익계산서 · 주석의 외화환산이익 · 손실은 조건부(when: 외화 현금성자산 환산분도 조정에 넣었다). "
                   "다르면 판정에 usual 「외화환산과 현금흐름표」 를 적는다")
    # 8. 변동표의 대체 ↔ 각주 · 상대 과목(늘 나는 차이를 FALSE 로 매겼다. 한 상장사 785)
    tr = [t for t in tabs if _has(t, r"^대체|대체\(|본계정대체|타계정대체") and _has(t, r"^기초|^기말")]
    if tr:
        out.append(f"점검: 변동표의 대체 줄({ids(tr)}) ↔ 각주 대체 금액 · 상대 과목 대체는 조건부(when: 각주에 적지 않은 대체가 없다)")
    # 9. 연결 주당이익 분자 = 지배기업 귀속 당기순이익(공개 연결 보고서: 연결 당기순이익 전체를 분자로 적었다)
    # 제목은 보지 않는다. 캡션의 「상장주식의 주당 가격」(민감도 표)이 걸렸다(11-08 한 상장사 주석4-4)
    eps = [t for t in note(r"주당") if _has(t, r"가중평균|주당이익|주당순이익|주당손익|보통주.*순이익|귀속.*순이익")]
    if eps and any("지배" in norm(x) for t in doc.tables() if t.id.startswith("손익계산서") for x in _labels(t)):
        out.append(f"점검: 주당이익 표({ids(eps)})의 당기순이익 = 손익계산서 지배기업 귀속 당기순이익(연결은 비지배지분을 빼야 한다, 기업회계기준서 제1033호 문단 10)")
    # 11. 주요경영진 보상 ≤ 같은 비용 전체(공개 연결 보고서 11-09: 주요경영진 퇴직급여 724,190 이 연결 퇴직급여 비용 495,052 보다 컸는데
    # 세 실행이 모두 걸지 않았다). 주요경영진 보상은 전체 비용의 일부다
    km = [t for t in tabs if (re.search(r"주요경영진|경영진보상|임원보상", by_title[t.id] + norm(t.caption or "")) or _has(t, r"주요경영진|^단기종업원급여|^단기급여", "both"))
          and _has(t, r"퇴직급여|퇴직후급여|단기종업원급여|^급여|주식보상|주식기준보상", "both")]
    if km:
        out.append(f"점검: 주요경영진 보상 표({ids(km)})의 급여 · 퇴직급여 · 주식보상 ≤ 보고서의 같은 비용 전체(성격별 비용 · 판매비와관리비 명세 · "
                   "퇴직급여 주석의 당기손익 인식 금액 · 주식보상비용). cmp: le 로 건다. 전체가 판관비 한 줄뿐이면 조건부(when: 제조원가 · 개발비에 든 금액이 있다)")
    # 12. 현금흐름 조정의 평가 · 처분손익 줄 ↔ 금융 · 기타 손익 주석의 같은 이름 줄(공개 연결 보고서 11-09: 조정 「이자율스왑평가손실」 이
    # 금융수익의 평가이익 금액이었다. 세 실행 가운데 둘이 걸지 않았다)
    cfa = [t for t in doc.tables() if t.id.startswith("현금흐름표")] + [t for t in tabs if re.search(r"현금흐름", by_title[t.id] + norm(t.caption or ""))]
    cfa = [t for t in cfa if _has(t, r"평가(이익|손실|손익)|처분(이익|손실|손익)")]
    pl = [t for t in tabs if t not in cfa and re.search(r"금융수익|금융비용|금융손익|기타수익|기타비용|영업외", by_title[t.id] + norm(t.caption or ""))
          and _has(t, r"평가(이익|손실)|처분(이익|손실)")]
    if cfa and pl:
        out.append(f"점검: 현금흐름 조정의 평가 · 처분손익 줄({ids(cfa)}) ↔ 금융 · 기타 손익 주석({ids(pl)})의 같은 이름 줄. 손실 줄은 손실 칸, 이익 줄은 이익 칸에 "
                   "항등식으로 건다. 조정 줄 하나가 이익과 손실을 함께 적은 순액이면 두 칸의 차로 건다. 이름은 손실인데 이익 칸의 금액이면 표시 오류다")
    # 13. 퇴직급여 변동표의 당기근무원가 · 이자 줄 ↔ 당기손익 인식 금액 표(공개 연결 보고서 11-09: 변동표 당기근무원가 줄의 사외적립자산 열에
    # 기대수익이 들어갔다. 세 실행 가운데 둘이 놓쳤다)
    db = note(r"퇴직급여|확정급여|종업원급여")
    move = [t for t in db if _has(t, r"당기근무원가|근무원가") and _has(t, r"기초|기말|당기초|전기초")]
    rec_pl = [t for t in db if t not in move and _has(t, r"당기근무원가|근무원가")]
    if move and rec_pl:
        out.append(f"점검: 퇴직급여 변동표({ids(move)})의 당기근무원가 · 이자원가 · 이자수익(기대수익) 줄 = 당기손익 인식 금액 표({ids(rec_pl)})의 같은 줄"
                   "(확정급여채무 열과 사외적립자산 열을 따로, 항등식). 변동표에서 당기근무원가가 사외적립자산 열에도 있으면 그 칸부터 본다")
    both = [t for t in move if _has(t, r"사외적립자산|플랜자산", "head") and _has(t, r"확정급여채무|확정급여부채", "head")]
    if both:
        out.append(f"점검: 확정급여채무와 사외적립자산을 한 표에 담은 변동표({ids(both)})는 당기근무원가 · 이자비용이 확정급여채무 열에만, 기대수익(이자수익)이 "
                   "사외적립자산 열에만 있다. 사외적립자산 열의 기대수익 칸 = 기초 사외적립자산 × 할인율(calcs, 조건부 when: 기중 불입 · 지급을 반영했다)로 건다. "
                   "당기근무원가 줄 사외적립자산 칸에 금액이 있고 기대수익 줄이 비었으면 줄이 바뀐 표시 오류다")
    # 10. 성격별 비용의 재고자산 변동 ↔ 재무상태표 재고자산 증감(공개 연결 보고서: 부호가 두 해 모두 반대)
    inv = [t for t in tabs if _has(t, r"재고자산의변동|제품.*변동|재공품.*변동|재고자산의증감")]
    if inv:
        out.append(f"점검: 성격별 비용 표({ids(inv)})의 재고자산 변동 = 재무상태표 재고자산 전기말 - 당기말(감소가 +, 조건부: 평가손실 · 타계정 대체를 따로 적었다). "
                   "크기가 같고 부호만 반대면 표시 오류다")
    return out
