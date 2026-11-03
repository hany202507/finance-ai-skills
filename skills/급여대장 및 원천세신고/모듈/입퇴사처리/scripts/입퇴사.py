# -*- coding: utf-8 -*-
"""입사 · 퇴사 · 기타소득이 생겼을 때 할 일과 금액을 낸다.

계산은 원천세 엔진을 그대로 부른다. 여기서는 사건 하나를 엔진 넷에 나눠 태우고,
결과를 신고서 스킬이 읽는 추가행 파일로 남긴다.

    입사  근로계약서 → 빠진 것 · 위법 조항 · 신고 기한
    퇴사  급여대장 1월(그해 입사자는 입사월)~퇴사월 → 퇴직금 · 퇴직소득세 · 중도퇴사 정산 · 신고 기한 → A02 · A22 행
    기타  지급 목록 → 기타소득세 → A42 · A59 행
"""
import argparse
import calendar
import json
import math
import os
import sys
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path


def _엔진경로():
    """요율 엔진. 같은 스킬 폴더의 원천세를 먼저 보고, 설치 경로를 다음에 본다."""
    후보 = [Path(__file__).resolve().parents[2] / "원천세" / "scripts",
            Path(os.path.expanduser("~/.claude/skills/원천세/scripts"))]
    for c in 후보:
        if (c / "retirement_tax.py").exists():
            return c
    raise RuntimeError("원천세 스킬을 못 찾았습니다. 찾아본 곳: " + " · ".join(map(str, 후보)))


sys.path.insert(0, str(_엔진경로()))
import contract_review as 계약     # noqa: E402
import db                          # noqa: E402
import event_obligations as 의무표  # noqa: E402
import retirement_tax as 퇴직세     # noqa: E402
import withholding_engine as 원천   # noqa: E402
import yearend_engine as 연말       # noqa: E402
from yearend_param import seed_2025  # noqa: E402
import yearend_rollover as 이월     # noqa: E402

월소정근로시간 = 209      # 주 40시간 사업장의 통상 산정 시간. 다르면 월통상임금을 맞춰 넣는다
일소정근로시간 = 8
퇴직금_제외기본 = ("CAR",)  # 자가운전보조금은 실비로 보고 임금 총액에서 뺀다. 되물을 것에 적는다
인적용역 = ("강연료", "인적용역", "자문료")   # 소득세법 §21①19호. 신고 코드 A59(규격서 2024-01-16 신설)


class 확인필요(Exception):
    """사실 하나가 없어서 결정할 수 없을 때. 기본값으로 밀어 넣지 않는다."""


def _날(s):
    return date.fromisoformat(str(s)[:10])


def _끝수(금액):
    """국고금 관리법 §47①. 납부액의 10원 미만은 계산하지 않는다."""
    return 금액 // 10 * 10


def _앞달(y, m, n):
    k = y * 12 + (m - 1) - n
    return k // 12, k % 12 + 1


def _기한비고(기한):
    """민법 §161. 표에는 법이 정한 날을 그대로 두고, 밀리는 것만 적는다. 공휴일 표는 없다."""
    요일 = {5: "토요일", 6: "일요일"}.get(_날(기한).weekday())
    return f"{요일}이라 다음 근무일까지 밀린다(민법 §161). 이어지는 공휴일은 달력으로 확인" if 요일 else ""


def _의무(입사일=None, 퇴사일=None):
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO payee(id,name,resident_type,payee_type,join_date,leave_date) "
                 "VALUES(1,'대상','거주자','근로자',?,?)", (입사일, 퇴사일))
    기준 = 퇴사일 or 입사일
    return [{"의무": o.의무, "기한": o.기한, "근거": o.근거, "비고": "" if "교부" in o.의무 else _기한비고(o.기한)}
            for o in 의무표.scan_events(conn, 기준, 창=0) if o.이벤트 == ("퇴사" if 퇴사일 else "입사")]


# ── 입사 ──
def 계약서글(경로):
    """docx 를 글로 푼다. 표는 「라벨 | 값」 줄이 되어 빈칸이 보인다."""
    import docx
    d = docx.Document(str(경로))
    줄 = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            줄.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(줄)


def 입사처리(계약서, 입사일):
    글 = 계약서글(계약서)
    이슈 = [{"항목": i.항목, "유형": i.유형, "근거": i.근거, "현재문구": i.현재문구, "대안문구": i.대안문구}
            for i in 계약.검토(글, 입사일)]
    return {"입사일": 입사일, "이슈": 이슈, "의무": _의무(입사일=입사일), "계약서글": 글}


# ── 퇴직금 ──
def _1년채움(입사, 퇴사):
    """계속근로 1년을 날짜로 센다. 일수로 세면 윤년이 낀 해에 하루가 어긋난다."""
    try:
        돌 = date(입사.year + 1, 입사.month, 입사.day)
    except ValueError:                       # 2월 29일 입사
        돌 = date(입사.year + 1, 3, 1)
    return 퇴사 >= 돌 - timedelta(days=1)


def _산정시작(b):
    """평균임금 산정 기간의 첫날. 퇴사일 다음 날에서 석 달 앞(근기법 §2①6 「사유 발생일 이전 3개월」)."""
    c = b + timedelta(days=1)
    y, m = _앞달(c.year, c.month, 3)
    말 = calendar.monthrange(y, m)[1]
    return date(y, m, min(c.day, 말))


def _말일(b):
    return b.day == calendar.monthrange(b.year, b.month)[1]


def 퇴직금(입사일, 퇴사일, 임금3개월, 월통상임금):
    """근기법 §2①6 · ② 평균임금, 근퇴법 §8① 1년에 30일분. 법이 「이상」이라 원 미만은 올린다."""
    a, b = _날(입사일), _날(퇴사일)
    재직 = (b - a).days + 1
    산정 = (b - _산정시작(b)).days + 1
    if not _1년채움(a, b):
        return {"재직일수": 재직, "산정일수": 산정, "퇴직금": 0, "적용": "",
                "사유": "계속근로 1년 미만이라 퇴직금 대상이 아니다(근퇴법 §4① 단서)"}
    평균 = Fraction(임금3개월, 산정)
    통상 = Fraction(월통상임금, 월소정근로시간) * 일소정근로시간
    적용 = "통상임금" if 통상 > 평균 else "평균임금"     # 근기법 §2②
    일급 = max(평균, 통상)
    금액 = math.ceil(일급 * 30 * Fraction(재직, 365))
    return {"재직일수": 재직, "산정일수": 산정, "임금3개월": 임금3개월, "평균임금": float(평균),
            "통상일급": float(통상), "적용": 적용, "퇴직금": 금액,
            "평균임금기준": math.ceil(평균 * 30 * Fraction(재직, 365)),
            "통상임금기준": math.ceil(통상 * 30 * Fraction(재직, 365)),
            "식": f"{float(일급):,.2f}원 × 30일 × {재직}일 ÷ 365일", "사유": ""}


# ── 중도정산 ──
def _세법(연도):
    conn = db.connect(":memory:")
    seed_2025(conn)
    if 연도 != 2025:
        이월.prepare_year(conn, 연도)     # §47 · §55 · §59 표는 2026-07-01 판 원문과 같음을 확인했다(2026-11-02)
    return conn


def 중도정산(월행들, 연도, 소득공제신고=None):
    """소득세법 §137. 신고가 없으면 §137③ 대로 본인 기본공제와 표준세액공제만 적용한다."""
    conn = _세법(연도)
    conn.execute("INSERT INTO payee(id,name,resident_type,payee_type) VALUES(1,'대상','거주자','근로자')")
    for r in 월행들:
        conn.execute("INSERT INTO payment(payee_id,income_type,accrual_ym,gross,nontax) VALUES(1,'근로',?,?,?)",
                     (r["연월"], r["총지급액"], r["비과세"]["소득세"]))
        conn.execute("INSERT INTO withholding_result(payment_id,income_tax,local_tax) "
                     "VALUES((SELECT max(id) FROM payment),?,?)", (r["소득세"], r["지방소득세"]))
    자료 = {"부양가족": [{"관계": "본인"}]}
    자료.update(소득공제신고 or {})
    for k, v in 자료.items():
        값 = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else None
        conn.execute("INSERT INTO yearend_deduction(payee_id,귀속연도,항목,금액,부속) VALUES(1,?,?,?,?)",
                     (연도, k, 0 if 값 else v, 값))
    conn.commit()
    s = 연말.settle(conn, 연도, 1)
    if isinstance(s, 연말.NeedsInfo):
        raise 확인필요("중도정산에 사실이 더 필요합니다: " + "; ".join(str(q) for q in s.requests))
    기납지방 = sum(r["지방소득세"] for r in 월행들)
    결정지방 = s.결정세액 // 10 // 10 * 10
    return {"총급여": s.총급여, "근로소득금액": s.근로소득금액, "과세표준": s.과세표준, "산출세액": s.산출세액,
            "세액공제": s.세액공제 if hasattr(s, "세액공제") else s.명세["세액공제계"], "결정세액": s.결정세액,
            "기납부": s.기납부세액 if hasattr(s, "기납부세액") else sum(r["소득세"] for r in 월행들),
            "정산세액": s.결정세액 - sum(r["소득세"] for r in 월행들), "지방정산": 결정지방 - 기납지방,
            "약식": 소득공제신고 is None}


# ── 퇴사 ──
def _대장읽기(폴더, 사번, 연월):
    p = Path(폴더) / f"급여대장_{연월}.json"
    if not p.exists():
        raise 확인필요(f"{연월} 급여대장이 없습니다({p.name}). 1월부터 퇴사월까지 있어야 정산합니다")
    for r in json.loads(p.read_text(encoding="utf-8")):
        if r["사번"] == 사번:
            return dict(r, 연월=연월)
    raise 확인필요(f"{연월} 급여대장에 {사번} 이 없습니다")


def 퇴사처리(폴더, 사번, 입사일, 퇴사일, 생년월일, 월통상임금, 소득공제신고=None, 제외항목=퇴직금_제외기본,
           임금3개월=None, IRP이전=None):
    a, b = _날(입사일), _날(퇴사일)
    첫달 = a.month if a.year == b.year else 1           # 그해 입사자는 입사한 달부터 대장이 있다
    월행들 = [_대장읽기(폴더, 사번, f"{b.year}-{m:02d}") for m in range(첫달, b.month + 1)]
    성명 = 월행들[0]["성명"]

    임금3 = 0
    if _1년채움(a, b) and 임금3개월 is not None:         # 사람이 정한 석 달 임금(월 중 퇴사 등)
        임금3 = int(임금3개월)
    elif _1년채움(a, b) and not _말일(b):
        시작 = _산정시작(b)
        raise 확인필요(f"월 중 퇴사라 평균임금 산정 기간({시작} ~ {b})의 임금을 대장 달 단위로 나눌 수 없습니다. "
                      "그 기간에 지급된 임금 총액을 일할로 정해 임금3개월 로 주세요(근기법 §2①6)")
    elif _1년채움(a, b):                                 # 1년 미만은 퇴직금이 없어 석 달 임금을 읽지 않는다
        for k in range(3):
            y, m = _앞달(b.year, b.month, k)
            r = _대장읽기(폴더, 사번, f"{y}-{m:02d}")
            임금3 += r["총지급액"] - sum(r["지급"].get(c, 0) for c in 제외항목)
    금 = 퇴직금(입사일, 퇴사일, 임금3, 월통상임금)

    나이 = b.year - _날(생년월일).year - ((b.month, b.day) < (_날(생년월일).month, _날(생년월일).day))
    # 근퇴법 §9② · 시행령 §3의2: 55세 미만은 IRP 이전이 원칙이고 예외(고시 금액 이하 등)가 있다. 사실을 받으면 그것을 쓴다
    이전 = (나이 < 55) if IRP이전 is None else bool(IRP이전)
    세 = None
    if 금["퇴직금"]:
        세 = 퇴직세.settle(_세법(b.year), 금["퇴직금"], 입사일, 퇴사일, 사실={"연금계좌이체": 이전}, 귀속연도=b.year)
        if isinstance(세, 원천.InfoRequest):
            raise 확인필요(f"퇴직소득세에 사실이 더 필요합니다: {세}")
    정산 = 중도정산(월행들, b.year, 소득공제신고)

    면제 = sum(min(r["지급"].get("CAR", 0), 200_000) for r in 월행들)   # 령 §12 3호 월 20만원 이내만 지급명세서 면제
    총 = sum(r["총지급액"] for r in 월행들)
    행들 = [{"성명": 성명, "소득코드": "A02", "대장총지급액": 총, "면제비과세": 면제, "총지급액": 총 - 면제,
             "소득세": 정산["정산세액"], "농특세": 0, "지방소득세": 정산["지방정산"], "출처": "입퇴사처리",
             "비고": f"{첫달}~{b.month}월 중도퇴사 정산" + (" · 소득공제 신고 없음(§137③)" if 정산["약식"] else "")}]
    if 금["퇴직금"]:
        # 신고서 작성방법: 연금계좌(A21)란은 연금계좌취급자가 적는다. 회사가 준 퇴직금은 IRP 로 보내도 그 외(A22)
        행들.append({"성명": 성명, "소득코드": "A22", "대장총지급액": 금["퇴직금"], "면제비과세": 0,
                     "총지급액": 금["퇴직금"], "소득세": _끝수(세.산출세액), "농특세": 0, "지방소득세": _끝수(세.지방소득세),
                     "출처": "입퇴사처리",
                     "비고": "IRP 이전 · 과세이연(원천징수 안 함, 소득세법 §146②)" if 이전 else f"퇴직 시 만 {나이}세 · 현금 수령"})

    되물을것 = ["연차 잔여일수. 미사용 연차수당은 잔여일수를 받아야 계산한다",
              "소득공제 신고서를 냈는지. 내지 않았으면 본인 기본공제와 표준세액공제만 적용한다(소득세법 §137③). 내면 다시 돌린다"]
    if 금["퇴직금"]:                                  # 퇴직금이 없으면 퇴직금에 딸린 것은 묻지 않는다
        되물을것 = (["통상임금에 넣은 수당이 맞는지. 고정 수당이 들어가면 평균임금보다 커져 퇴직금이 늘어난다(근기법 §2②)"]
                  + 되물을것[:1]
                  + (["자가운전보조금이 실비인지. 실비가 아니면 임금 총액에 넣어 퇴직금을 다시 계산한다"] if 면제 else [])
                  + 되물을것[1:]
                  + ["퇴직연금 가입 여부. 이 계산은 퇴직금제도 기준이다",
                     "퇴직금 지급일. 퇴사한 달에 주지 않으면 퇴직소득세 신고 달이 달라진다(소득세법 §128①)"])
        if 나이 < 55 and IRP이전 is None:
            되물을것.insert(0, "IRP 계좌. 55세 미만은 IRP 로 이전하는 것이 원칙이다(근퇴법 §9②). 퇴직금이 고용노동부 고시 금액 이하인 경우 등 "
                                "예외(시행령 §3의2①)로 현금으로 줬으면 IRP이전 N 으로 다시 돌린다. 그때는 퇴직소득세를 뗀다")
    return {"성명": 성명, "퇴사일": 퇴사일, "나이": 나이, "퇴직금": 금,
            "퇴직소득세": ({"근속연수": 세.근속연수, "과세표준": 세.과세표준, "산출세액": 세.산출세액,
                       "징수세액": _끝수(세.산출세액), "지방소득세": _끝수(세.지방소득세)} if 세 else None),
            "중도정산": 정산, "추가행": 행들, "의무": _의무(입사일=입사일, 퇴사일=퇴사일), "되물을것": 되물을것}


# ── 기타소득 ──
def 기타소득처리(목록):
    행들 = []
    for x in 목록:
        if str(x.get("계속반복", "")).upper() in ("Y", "TRUE", "1"):
            raise 확인필요(f"{x['성명']} 의 {x['종류']} 는 계속 · 반복이면 기타소득이 아니라 사업소득입니다. 3.3% 로 다시 정해 주세요")
        if not x.get("지급일"):
            raise 확인필요(f"{x['성명']} 의 지급일이 없습니다. 지급일에 따라 신고 달과 세율 판이 정해집니다")
        금액 = int(x["지급액"])
        지급일 = str(x["지급일"])[:10]
        r = 원천.judge(원천.PaymentInput(원천.소득유형.기타, 금액, 지급일[:7],
                                       {"성명": x["성명"]}, 기타소득종류=x["종류"]), on_date=지급일)
        if isinstance(r, 원천.InfoRequest):
            raise 확인필요(f"{x['성명']} 기타소득 판정: {r}")
        행들.append({"성명": x["성명"], "소득코드": "A59" if x["종류"] in 인적용역 else "A42", "대장총지급액": 금액,
                     "면제비과세": 0, "총지급액": 금액, "소득세": r.소득세, "농특세": 0, "지방소득세": r.지방소득세,
                     "출처": "입퇴사처리", "비고": f"{x['종류']} · 필요경비 {float(원천.기타경비율[x['종류']]) * 100:.0f}% · {r.근거}"})
    return 행들


def 추가행저장(폴더, 연월, 행들):
    경로 = Path(폴더) / f"추가행_{연월}.json"
    경로.parent.mkdir(parents=True, exist_ok=True)
    경로.write_text(json.dumps(행들, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(경로)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="입사 · 퇴사 · 기타소득 처리")
    sub = ap.add_subparsers(dest="일", required=True)
    a = sub.add_parser("입사"); a.add_argument("--계약서", required=True); a.add_argument("--입사일", required=True)
    b = sub.add_parser("퇴사"); b.add_argument("--대장폴더", required=True); b.add_argument("--사번", required=True)
    b.add_argument("--입사일", required=True); b.add_argument("--퇴사일", required=True)
    b.add_argument("--생년월일", required=True); b.add_argument("--월통상임금", type=int, required=True)
    b.add_argument("--소득공제신고", help="근로소득자 소득공제 신고 내용 JSON 파일. 연말정산 엔진의 항목 이름을 쓴다")
    b.add_argument("--제외항목", default=",".join(퇴직금_제외기본), help="임금 총액에서 뺄 항목코드, 쉼표로. 빈 값이면 다 넣는다")
    b.add_argument("--임금3개월", type=int, help="평균임금 산정 기간 임금 총액. 월 중 퇴사면 사람이 일할로 정해 준다")
    b.add_argument("--IRP이전", choices=("Y", "N"), help="퇴직금을 IRP 로 보냈는가. 주지 않으면 55세 미만은 Y 로 본다")
    c = sub.add_parser("기타"); c.add_argument("--목록", required=True)
    for s in (b, c):
        s.add_argument("--받은자료", help="주면 추가행 파일에 이어 적는다"); s.add_argument("--연월")
    x = ap.parse_args()
    try:
        if x.일 == "입사":
            r = 입사처리(x.계약서, x.입사일); r.pop("계약서글")
        elif x.일 == "퇴사":
            신고 = json.loads(Path(x.소득공제신고).read_text(encoding="utf-8")) if x.소득공제신고 else None
            r = 퇴사처리(x.대장폴더, x.사번, x.입사일, x.퇴사일, x.생년월일, x.월통상임금, 소득공제신고=신고,
                     제외항목=tuple(k for k in x.제외항목.split(",") if k), 임금3개월=x.임금3개월,
                     IRP이전=None if x.IRP이전 is None else x.IRP이전 == "Y")
        else:
            import csv
            r = {"추가행": 기타소득처리(list(csv.DictReader(open(x.목록, encoding="utf-8-sig"))))}
    except 확인필요 as e:
        print(f"멈췄습니다: {e}", file=sys.stderr)
        return 2
    if x.일 != "입사" and x.받은자료:
        p = Path(x.받은자료) / f"추가행_{x.연월}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        기존 = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        기존 = [q for q in 기존 if not any(q["성명"] == n["성명"] and q["소득코드"] == n["소득코드"] for n in r["추가행"])]
        추가행저장(x.받은자료, x.연월, 기존 + r["추가행"])
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
