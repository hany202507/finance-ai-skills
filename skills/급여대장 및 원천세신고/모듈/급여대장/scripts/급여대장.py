# -*- coding: utf-8 -*-
"""인사카드 + 급여계약 + 급여항목규칙 → 급여대장.

핵심은 하나다. **과세표준을 제도마다 따로 만든다.**
소득세 비과세와 4대보험 산입 여부가 같지 않다. 국외근로수당이 그 자리다.
소득세는 안 떼고 건강보험은 뗀다. 한 벌로 계산하면 둘 중 하나가 틀린다.

    인사카드 hr_card.csv        누가 어떤 조건인가
    급여계약 pay_contract.csv   사번 x 항목코드 x 금액 (효력일자)
    항목규칙 pay_item_rule.csv  항목 x 제도 x 산입여부·한도·근거

계산은 원천세 스킬의 검증된 엔진을 그대로 쓴다. 요율·간이세액표를 두 벌 두지 않는다.
"""
import csv
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

def _엔진경로():
    """요율·간이세액표 엔진을 어디서 찾을지.

    설치된 원천세 스킬을 먼저 본다. 없으면 배포 패키지에 같이 넣은 사본을 쓴다.
    두 벌을 두지 않으려는 것이고, 배포본만 받은 사람도 돌아가게 하려는 것이다.
    """
    후보 = [Path(__file__).resolve().parents[2] / "원천세" / "scripts",
            Path(os.path.expanduser(r"~/.claude/skills/원천세/scripts")),
            Path(__file__).parent.parent.parent / "_공용엔진",
            Path(__file__).parent / "_공용엔진"]
    for c in 후보:
        if (c / "simple_tax_table.py").exists():
            return c
    raise RuntimeError(
        "요율 엔진을 못 찾았습니다. 원천세 스킬을 설치하거나 "
        "_공용엔진 폴더를 스킬 옆에 두세요. 찾아본 곳: "
        + " · ".join(str(c) for c in 후보))


원천세 = _엔진경로()
sys.path.insert(0, str(원천세))

import insurance_engine as I          # noqa: E402
import simple_tax_table as T          # noqa: E402
import withholding_engine as W        # noqa: E402
import db                             # noqa: E402

제도들 = ("소득세", "국민연금", "건강보험", "고용보험")
소득코드 = {"상용": "A01", "일용": "A03", "사업": "A25"}
산입으로본다 = ("과세", "산입")


class 확인필요(Exception):
    """사실 하나가 없어서 결정할 수 없을 때. 기본값으로 밀어 넣지 않는다."""


# ── 읽기 ────────────────────────────────────────────────
def _rows(경로):
    with open(경로, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_rules(경로):
    """(항목코드, 제도) → 규칙."""
    표 = {}
    for r in _rows(경로):
        표[(r["항목코드"], r["제도"])] = {
            "구분": r["구분"],
            "한도금액": int(r["한도금액"]) if r["한도금액"] else None,
            "한도단위": r["한도단위"] or None,
            "근거": r["근거"], "등급": r["등급"],
        }
    return 표


def load_cards(경로):
    표 = {}
    for r in _rows(경로):
        for k in ("부양가족수", "6세이하자녀수", "8_20세자녀수"):
            r[k] = int(r[k] or 0)
        for k in ("국민연금가입", "건강보험가입", "고용보험가입"):
            r[k] = (r[k] or "N").upper() == "Y"
        표[r["사번"]] = r
    return 표


def load_contracts(경로, 기준일):
    """효력일자가 기준일 이하인 것 중 가장 늦은 것을 쓴다."""
    최신 = {}
    for r in _rows(경로):
        if r["적용시작일"] > 기준일:
            continue
        키 = (r["사번"], r["항목코드"])
        if 키 not in 최신 or r["적용시작일"] > 최신[키]["적용시작일"]:
            최신[키] = r
    묶음 = {}
    for (사번, 코드), r in 최신.items():
        묶음.setdefault(사번, {})[코드] = int(r["금액"])
    return 묶음


# ── 제도별 과세표준 ──────────────────────────────────────
@dataclass
class 표준:
    값: dict = field(default_factory=dict)       # 제도 → 금액
    비과세: dict = field(default_factory=dict)   # 제도 → 뺀 금액
    근거: list = field(default_factory=list)


def 과세표준(지급항목, 카드, 규칙):
    """항목 하나하나를 제도 넷에 각각 태운다.

    지급항목: {항목코드: 금액}
    """
    out = 표준({p: 0 for p in 제도들}, {p: 0 for p in 제도들}, [])
    for 코드, 금액 in 지급항목.items():
        if not 금액:
            continue
        for 제도 in 제도들:
            규 = 규칙.get((코드, 제도))
            if 규 is None:
                raise 확인필요(f"{코드} 의 {제도} 규칙이 마스터에 없습니다. "
                              f"pay_item_rule.csv 에 행을 넣어 주세요")
            구분 = 규["구분"]
            if 구분 in 산입으로본다:
                out.값[제도] += 금액
                continue
            if 구분 == "전액비과세":
                out.비과세[제도] += 금액
                continue
            # 한도부비과세 · 제외 · 제외(확인필요)
            한도 = _한도(코드, 규, 카드, out)
            뺀값 = min(금액, 한도)
            out.비과세[제도] += 뺀값
            out.값[제도] += 금액 - 뺀값
            if 금액 > 한도 and 제도 == "소득세":
                out.근거.append(f"{코드} 초과분 {금액 - 한도:,} 은 과세 "
                                f"(한도 {한도:,} · {규['근거']})")
            if 규["등급"] == "☆" and 제도 not in [g.split()[0] for g in out.근거]:
                out.근거.append(f"확인필요: {코드} 의 {제도} 처리는 근거 미확인입니다 "
                                f"({규['근거']})")
    return out


def _한도(코드, 규, 카드, out):
    한도 = 규["한도금액"]
    단위 = 규["한도단위"] or ""
    if 한도 is None:
        return 10 ** 12                       # 사실상 전액
    if "자녀1명당" in 단위:
        자녀 = 카드.get("6세이하자녀수")
        if 자녀 in (None, ""):
            raise 확인필요(f"{카드.get('성명')} 의 6세 이하 자녀 수가 없습니다. "
                          f"{코드} 한도를 정할 수 없습니다")
        if 자녀 == 0:
            out.근거.append(f"{코드}: 6세 이하 자녀가 없어 전액 과세입니다")
        return 한도 * int(자녀)
    if 단위 == "연":
        raise 확인필요(f"{코드} 는 연 한도({한도:,})라 그 해 이미 받은 금액이 있어야 "
                      f"계산됩니다. 누적액을 주세요")
    return 한도                                # 월


# ── 한 사람 한 달 ────────────────────────────────────────
@dataclass
class 급여행:
    사번: str = ""
    성명: str = ""
    소득구분: str = ""
    소득코드: str = ""
    지급: dict = field(default_factory=dict)
    총지급액: int = 0
    표준: dict = field(default_factory=dict)
    비과세: dict = field(default_factory=dict)
    국민연금: int = 0
    건강보험: int = 0
    장기요양보험: int = 0
    고용보험: int = 0
    소득세: int = 0
    지방소득세: int = 0
    공제합계: int = 0
    실지급액: int = 0
    근거: list = field(default_factory=list)


def 계산_상용(conn, 카드, 지급항목, 규칙, 기준일):
    s = 과세표준(지급항목, 카드, 규칙)
    총 = sum(지급항목.values())

    연금 = I.compute(s.값["국민연금"], on_date=기준일,
                     국민연금가입=카드["국민연금가입"]).국민연금
    건보 = I.compute(s.값["건강보험"], on_date=기준일,
                     건강가입=카드["건강보험가입"])
    고용 = I.compute(s.값["고용보험"], on_date=기준일,
                     고용가입=카드["고용보험가입"]).고용보험

    세 = T.lookup(conn, s.값["소득세"], 카드["부양가족수"], on_date=기준일,
                  자녀8_20세수=카드["8_20세자녀수"])
    지방 = 세 // 10 // 10 * 10          # 사람마다 절사한다

    r = 급여행(사번=카드["사번"], 성명=카드["성명"], 소득구분=카드["소득구분"],
              소득코드=소득코드.get(카드["소득구분"], "A01"),
              지급=dict(지급항목), 총지급액=총, 표준=dict(s.값), 비과세=dict(s.비과세),
              국민연금=연금, 건강보험=건보.건강보험, 장기요양보험=건보.장기요양,
              고용보험=고용, 소득세=세, 지방소득세=지방, 근거=list(s.근거))
    r.공제합계 = r.국민연금 + r.건강보험 + r.장기요양보험 + r.고용보험 + r.소득세 + r.지방소득세
    r.실지급액 = r.총지급액 - r.공제합계
    if 지급항목.get("OVERSEA"):
        r.근거.append("확인필요: 국외에서 업무에 종사하는 달이면 건강보험료율이 절반입니다(국민건강보험법 §73②). 여기서는 전액으로 계산했습니다")
    if s.값["소득세"] != s.값["국민연금"]:
        r.근거.append(f"과세표준이 제도마다 다릅니다. 소득세 {s.값['소득세']:,} · "
                      f"국민연금 {s.값['국민연금']:,} · 건강보험 {s.값['건강보험']:,} · "
                      f"고용보험 {s.값['고용보험']:,}")
    return r


def 계산_일용(카드, 일급들, 기준일):
    """일용은 날마다 계산한다. 소액부징수도 날마다 본다."""
    세 = 0
    for 일급 in 일급들:
        p = W.PaymentInput(W.소득유형.일용, int(일급), 기준일[:7], {"성명": 카드["성명"]})
        res = W.judge(p, on_date=기준일)
        if isinstance(res, W.InfoRequest):
            raise 확인필요(f"{카드['성명']} 일용 판정: {res}")
        세 += res.소득세
    총 = int(sum(일급들))
    고용 = I.compute(총, on_date=기준일, 국민연금가입=False, 건강가입=False,
                     고용가입=카드["고용보험가입"]).고용보험
    지방 = 세 // 10 // 10 * 10
    r = 급여행(사번=카드["사번"], 성명=카드["성명"], 소득구분="일용", 소득코드="A03",
              지급={"HOURLY": 총}, 총지급액=총,
              표준={p: 총 for p in 제도들}, 비과세={p: 0 for p in 제도들},
              고용보험=고용, 소득세=세, 지방소득세=지방,
              근거=[f"{len(일급들)}일치. 일별로 (일급−15만)x6%x(1−55%), "
                    f"일 1,000원 미만은 안 뗍니다"])
    r.공제합계 = r.고용보험 + r.소득세 + r.지방소득세
    r.실지급액 = r.총지급액 - r.공제합계
    return r


def 계산_사업(카드, 지급액, 기준일):
    p = W.PaymentInput(W.소득유형.사업, int(지급액), 기준일[:7], {"성명": 카드["성명"]})
    res = W.judge(p, on_date=기준일)
    if isinstance(res, W.InfoRequest):
        raise 확인필요(f"{카드['성명']} 사업소득 판정: {res}")
    r = 급여행(사번=카드["사번"], 성명=카드["성명"], 소득구분="사업", 소득코드="A25",
              지급={"SERVICE": int(지급액)}, 총지급액=int(지급액),
              표준={p: int(지급액) for p in 제도들}, 비과세={p: 0 for p in 제도들},
              소득세=res.소득세, 지방소득세=res.지방소득세, 근거=[res.근거])
    r.공제합계 = r.소득세 + r.지방소득세
    r.실지급액 = r.총지급액 - r.공제합계
    return r
