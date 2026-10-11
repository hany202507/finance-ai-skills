# -*- coding: utf-8 -*-
"""고객용 HTML 질문지를 만든다.

  python scripts/make_questionnaire_html.py [--출력 질문지/양도소득세_질문지.html]

질문지 정의는 질문지/문항.json 하나다. 회계사는 대화(yangdo/questions.py)로, 고객은 이 HTML 로 같은 사실관계 JSON 을 만든다.
서버 없이 브라우저에서 여는 파일 한 개이고 외부 CSS·스크립트·전송이 없다. 근거 링크만 law.go.kr 로 열린다.

HTML 은 엔진을 돌릴 수 없다. 그래서 조건 문법(문항.json 머리의 조건표기, questions.py 의 _item·_visible)대로
앞 답으로 정해지는 조건만 판정하고, 엔진 중간값(엔진.이름, 주택.이름)이 있어야 정해지는 문항은 「회계사가 확인합니다」로 둔다.
기본 화면은 그런 문항도 「회계사가 확인합니다」 표시를 붙여 보여 주어 알고 있는 만큼 미리 적을 수 있고, 화면 위의
「회계사가 확인하는 항목 숨기기」를 켜면 감춘다(app.js 의 hidePending, 처음 값은 꺼짐).

범위가 서식단계인 문항(인적사항, 양수인, 환급계좌)은 넣지 않는다. 이 파일에는 문항.json 전체의 해시나 판 정보를 넣지 않는다.
서식단계 문항이 바뀌어도 생성물이 달라지지 않아야 하기 때문이다.

화면 논리는 scripts/questionnaire_template/ 의 core.js(DOM 없음, node 시험이 파이썬 판정과 견준다), app.js, style.css, page.html 이다.
page.html 의 CSP meta 가 이 파일 안의 스크립트·스타일만 허용하고 나머지 요청을 모두 막는다(default-src 'none'). 템플릿에 외부 자원,
그림, 글꼴, 양식 전송, 문자열 실행(eval)을 더하면 브라우저가 막으니 정책과 시험(tests/test_questionnaire_html.py)을 함께 고친다.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from urllib.parse import quote

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import QUESTIONS_PATH  # noqa: E402
from yangdo import questions as Questions  # noqa: E402
from yangdo.regions import KNOWN_SIDO, SIDO_SHORT  # noqa: E402

TEMPLATE_DIR = os.path.join(SKILL, "scripts", "questionnaire_template")
DEFAULT_OUT = os.path.join(SKILL, "질문지", "양도소득세_질문지.html")

ASSET_KIND = {"q": "P02", "house": "주택"}   # 판 집(주택)마다 집 목록에 한 줄이 있어야 한다
HOUSE_QUESTION = "H04"
ALONE = ("해당없음", "없음")                    # 복수선택에서 다른 선택과 함께 둘 수 없는 코드


# ---- spec 도우미 ------------------------------------------------------------
def fld(n, label, s, **kw):
    d = {"n": n, "label": label, "s": s}
    d.update(kw)
    return d


DATE = {"t": "date"}
INT = {"t": "int"}
NUM = {"t": "num"}
TEXT = {"t": "text"}
BOOL = {"t": "bool"}


def choice(opts):
    return {"t": "choice", "opts": [[c, l] for c, l in opts]}


def obj(fields, req=None, **kw):
    d = {"t": "obj", "fields": fields}
    if req:
        d["req"] = req
    d.update(kw)
    return d


def rows(noun, row, add, none=None, as_="rows"):
    d = {"t": "list", "as": as_, "noun": noun, "row": row, "add": add}
    if none:
        d["none"] = none
    return d


# 영수증 종류. 코드는 calc.OK_EVIDENCE 와 같은 글자여야 경비로 들어간다(tests/test_questionnaire_html.py 가 대조한다)
EVIDENCE = [("세금계산서", "세금계산서"), ("계산서", "계산서(면세 거래)"), ("카드영수증", "카드영수증"), ("현금영수증", "현금영수증"),
            ("계좌이체", "계좌이체 내역"), ("간이영수증", "간이영수증"), ("없음", "없음")]

KEY_LABELS = {"계약일": "매매계약을 맺은 날", "계약금지급일": "계약금을 낸 날", "잔금일": "잔금을 낸 날",
              "등기접수일": "본인 이름으로 등기가 접수된 날", "사용승인일": "사용승인일(사용검사일)",
              "사실상사용일": "실제로 쓰기 시작한 날(입주일, 임시사용승인일)"}

SHARE_OPTS = [["단독", "혼자 소유"], ["공동", "공동 소유(지분 입력)"]]


# 사업자등록번호 칸. 하이픈은 빼 주고 숫자 10자리가 아니면 알려 준다(검증번호는 서식 단계 질문 F07 이 본다)
BIZ_NO = dict(TEXT, digits=10, hint="숫자 10자리, 모르면 비워 두세요")


def expense_row(content):
    """필요경비 지출 한 줄. 사업자번호는 전자신고 07 레코드의 필수 구분코드 지출에 쓰이는 선택 칸이다(yangdo.return_values)."""
    return obj([fld("내용", "내용", content), fld("지급일", "낸 날", DATE), fld("금액", "금액", INT),
                fld("증빙종류", "받은 영수증 종류", choice(EVIDENCE)), fld("상대방", "대금을 지급한 상대(업체·사람)", TEXT),
                fld("사업자번호", "그 업체의 사업자등록번호", BIZ_NO)],
               req=["내용", "금액", "증빙종류"])


def build_specs(doc_q):
    """복합 답(묶음, 목록)을 가진 문항의 입력 방식. 나머지는 답형식으로 만든다."""
    def opts_of(qid):
        return [[o["코드"], o["표시"]] for o in doc_q[qid]["선택지"]]

    def tx(content_suggest):
        return dict(TEXT, suggest=content_suggest)

    return {
        "P04": {"t": "share", "opts": SHARE_OPTS},
        "P06": rows("예정신고 건", obj([fld("양도소득금액", "신고서의 양도소득금액", INT), fld("결정세액", "신고서의 결정세액", INT)],
                                        req=["양도소득금액", "결정세액"]), "예정신고 건 추가", "해당 없음"),
        "A14": dict(INT, hint="없으면 0"),
        "A20": obj([fld("토지", "토지 전체 면적", dict(NUM, unit="㎡")), fld("건물", "건물 전체 면적", dict(NUM, unit="㎡"))]),
        "A22": obj([fld("토지", "토지 가격", INT), fld("건물", "건물 가격", INT)], req=["토지", "건물"]),
        "H03": rows("세대원", obj([fld("관계", "관계", choice([(x, x) for x in ("배우자", "자녀", "부모", "형제자매", "다른 가족")])),
                                  fld("같은주민등록", "주민등록상 같은 세대인가요", BOOL),
                                  fld("주택보유", "집을 갖고 있나요", BOOL),
                                  fld("입주권분양권보유", "입주권이나 분양권을 갖고 있나요", BOOL)],
                                 req=["관계"]), "세대원 추가", "해당 없음(다른 세대원이 없습니다)"),
        HOUSE_QUESTION: {"t": "houses"},
        "H06": rows("입주권·분양권", obj([fld("종류", "종류", choice([("조합원입주권", "재개발·재건축 조합원입주권"), ("분양권", "아파트 분양권")])),
                                        fld("취득일", "취득한 날", DATE)], req=["종류"]), "입주권·분양권 추가", "해당 없음"),
        "H07": rows("거주 기간", obj([fld("a", "전입일", DATE), fld("b", "전출일", DATE)]), "거주 기간 추가",
                    "이 집에 주민등록을 두고 산 적이 없습니다", as_="pairs"),
        "L01": obj([fld("대지면적", "땅 전체 면적", dict(NUM, unit="㎡", positive=True)),
                    fld("정착면적", "건축면적(건물이 땅을 덮고 있는 면적)", dict(NUM, unit="㎡", positive=True)),
                    fld("용도지역", "용도지역", choice(ZONES))], req=["대지면적", "정착면적", "용도지역"]),
        "M08": rows("지출", expense_row(tx(["중개수수료", "법무사비용"])), "지출 추가", "해당 없음"),
        "M09": rows("공사", expense_row(choice(opts_of("M09"))), "공사 추가", "해당 없음"),
        "M10": rows("지출", expense_row(tx(["개발부담금", "재건축부담금", "소송비용", "도로 개설 비용"])), "지출 추가", "해당 없음"),
        "M11": rows("지출", expense_row(tx(["중개수수료", "계약서·신고서 작성비", "공증비", "인지대", "국민주택채권 매각 손실"])),
                    "지출 추가", "해당 없음"),
        "M21": obj([fld("매매사례가액", "매매사례가액(같은 단지·조건의 다른 거래 금액)", INT),
                    fld("감정가액", "감정평가 금액(여러 건이면 추가)", rows("감정가액", INT, "감정가액 추가", as_="scalars"))]),
        "M22": obj([fld("취득", "산 날 기준", obj([fld("토지", "토지", INT), fld("건물", "건물", INT), fld("주택", "주택", INT)])),
                    fld("양도", "판 날 기준", obj([fld("토지", "토지", INT), fld("건물", "건물", INT), fld("주택", "주택", INT)]))]),
        "M23": obj([fld("사용승인일", "사용승인일(증축일)", DATE), fld("증축면적", "늘린 면적", dict(NUM, unit="㎡"))]),
        "M24": obj([fld("개별공시지가", "1990-01-01 기준 개별공시지가", INT), fld("토지등급", "그 당시의 토지등급(1990-01-01 기준)", INT)]),
        "X06": obj([fld("신청일", "허가를 신청한 날", DATE), fld("허가일", "허가를 받은 날", DATE)]),
    }


ZONES = [(z, z) for z in (
    "제1종전용주거지역", "제2종전용주거지역", "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역", "준주거지역",
    "중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역", "전용공업지역", "일반공업지역", "준공업지역",
    "보전녹지지역", "생산녹지지역", "자연녹지지역", "보전관리지역", "생산관리지역", "계획관리지역", "농림지역", "자연환경보전지역")]


def spec_for(q, specs):
    """문항 하나의 입력 방식. 복합 답은 specs 표에서, 나머지는 답형식에서 만든다."""
    if q["id"] in specs:
        return specs[q["id"]]
    kind, keys = q["답형식"], q["키"]
    codes = [o["코드"] for o in q.get("선택지") or []]
    opts = [[o["코드"], o["표시"]] for o in q.get("선택지") or []]
    if kind == "예아니오":
        return BOOL
    if kind == "선택":
        return {"t": "choice", "opts": opts}
    if kind == "복수선택":
        return {"t": "multi", "opts": opts, "alone": [c for c in codes if c in ALONE]}
    if kind == "주소":
        return {"t": "addr"}
    base = {"날짜": DATE, "금액": INT, "숫자": NUM}.get(kind)
    if base is None:
        raise SystemExit("%s: 답형식 %s 의 입력 방식을 모릅니다. build_specs 에 적어 주세요" % (q["id"], kind))
    if len(keys) == 1:
        return base
    return obj([fld(k.rsplit(".", 1)[-1], KEY_LABELS.get(k.rsplit(".", 1)[-1], k.rsplit(".", 1)[-1]), base) for k in keys])


# ---- 근거 링크 --------------------------------------------------------------
LAW_NAMES = {"소득세법": "소득세법", "소득세법 시행령": "소득세법시행령", "소득세법 시행규칙": "소득세법시행규칙",
             "부동산등기법": "부동산등기법", "부동산 거래신고 등에 관한 법률": "부동산거래신고등에관한법률"}
ARTICLE = re.compile(r"제(\d+)조(?:의(\d+))?")


def law_link(g):
    """근거조문 한 건의 {t: 글자, h: law.go.kr 주소 또는 None}. 법령이 아닌 근거(작성요령, 점검표)는 글자만 둔다."""
    law, jo = g["법령"], g["조항"]
    text = "%s %s" % (law, jo)
    name = LAW_NAMES.get(law)
    base = law.split(" <")[0].replace(" 부칙", "")   # 소득세법 시행령 부칙 <제36737호, 2026.9.30> 는 법령 본문으로 잇는다
    name = name or LAW_NAMES.get(base)
    if not name:
        return {"t": text, "h": None}
    path = "법령/" + name
    m = ARTICLE.match(jo) if "부칙" not in law else None
    if m:
        path += "/제%s조%s" % (m.group(1), "의" + m.group(2) if m.group(2) else "")
    return {"t": text, "h": "https://www.law.go.kr/" + quote(path)}


# ---- 정의 만들기 ------------------------------------------------------------
def sido_list():
    seen = []
    for v in SIDO_SHORT.values():
        if v not in seen:
            seen.append(v)
    return seen + sorted(KNOWN_SIDO - set(seen))


def check_conditions(qs):
    """조건이 가리키는 문항은 이 화면에 있는 문항이어야 하고, 서로를 가리키며 돌면 안 된다.

    조건은 정의 순서와 상관없이 뒤에 있는 문항(A09 가 A13 을 보는 경우)도 가리킨다. 화면이 필요한 문항 상태를 그때그때 구한다.
    """
    ids = {q["id"] for q in qs}
    refs = {}

    def walk(cond, qid, out):
        if cond == "항상":
            return
        (group, items), = cond.items()
        for it in items:
            if isinstance(it, dict):
                walk(it, qid, out)
            elif not it[0].startswith(("엔진.", "주택.")):
                if it[0] not in ids:
                    raise SystemExit("%s 의 보이는조건이 이 화면에 없는 문항 %s 를 가리킵니다" % (qid, it[0]))
                out.add(it[0])

    for q in qs:
        refs[q["id"]] = set()
        walk(q["보이는조건"], q["id"], refs[q["id"]])
    state = {}

    def visit(n, path):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise SystemExit("보이는조건이 서로를 가리키며 돕니다: %s" % " > ".join(path + [n]))
        state[n] = 1
        for m in sorted(refs[n]):
            visit(m, path + [n])
        state[n] = 2

    for n in refs:
        visit(n, [])


def build(doc):
    qs = [q for q in doc["문항"] if q["범위"] != "서식단계"]
    by_all = {q["id"]: q for q in doc["문항"]}
    check_conditions(qs)
    specs = build_specs(by_all)
    sec_name = {s["id"]: s["이름"] for s in doc["섹션"]}
    out_q, houseqs = [], []
    for q in qs:
        unit = Questions.unit_kind(q)
        if unit in ("주택", "신규"):
            zone = "row"
        elif unit == "자산":
            zone = "asset"
        else:
            zone = "top" if q["섹션"] == "S0" else "house"
        sp = spec_for(q, specs)
        out_q.append({
            "id": q["id"], "sec": q["섹션"], "text": q["질문"], "help": q.get("도움말") or "", "form": q["답형식"],
            "unit": unit, "zone": zone, "keys": q["키"], "spec": sp,
            "moreum": "모름" in [o["코드"] for o in q.get("선택지") or []],
            "why": {"used": q.get("쓰이는판정") or [], "law": [law_link(g) for g in q.get("근거조문") or []],
                    "docs": q.get("증빙서류") or [], "where": q.get("모를때확인처") or []},
        })
        if zone == "row":
            houseqs.append(q)
    used_sec = {q["sec"] for q in out_q}
    defs = {
        "questions": out_q,
        "sections": {k: v for k, v in sec_name.items() if k in used_sec},
        "sido": sido_list(),
        "assetKind": ASSET_KIND,
        "houseQuestion": HOUSE_QUESTION,
        "houseRow": house_row(by_all, houseqs),
    }
    conds = {q["id"]: q["보이는조건"] for q in qs}
    # 이 화면이 보이는 문항과 조건의 지문. 브라우저에 임시로 남은 답이 옛 양식의 것이면 버리는 데 쓴다.
    # 서식단계 문항은 defs 에 없으므로 그 문항이 바뀌어도 지문은 같다.
    defs["sig"] = hashlib.sha256((js_json(defs) + js_json(conds)).encode("utf-8")).hexdigest()[:16]
    return defs, conds


def house_row(by_all, houseqs):
    """집 목록의 한 줄. 판 집으로 이어진 줄은 주소·형태·산 날·원인·지분을 자산 답에서 가져온다(sold=false 인 항목)."""
    def opts_of(qid):
        return [[o["코드"], o["표시"]] for o in by_all[qid]["선택지"]]

    main = [
        fld("소유자", "누구 명의인가요", choice([("본인", "본인"), ("배우자", "배우자"), ("세대원", "다른 세대원")])),
        fld("소재지", "주소(시·도, 시·군·구, 읍·면·동)", {"t": "addr"}, sold=False),
        fld("유형", "주택 형태", choice(opts_of("A04")), sold=False),
        fld("취득일", "산 날(잔금일)", DATE, sold=False),
        fld("취득원인", "어떻게 갖게 됐나요", choice(opts_of("A15")), sold=False),
        fld("지분", "지분", {"t": "share", "opts": SHARE_OPTS}, sold=False),
        fld("등록임대", "임대사업자로 등록한 집인가요", BOOL),
    ]
    extra = []
    labels = {"양도당시기준시가": "판 날 기준 공시가격", "제12호해당": "2024-01-10 이후 산 집이라면 해당하는 유형",
              "계약일": "새 집 매매계약일", "계약금지급일": "새 집 계약금을 낸 날"}
    names = {m["n"] for m in main}
    for q in houseqs:
        first = True
        for k in q["키"]:
            n = k.rsplit(".", 1)[-1]
            if n in names:        # T02 취득원인은 위 「어떻게 갖게 됐나요」가 같은 키다
                continue
            names.add(n)
            kind = q["답형식"]
            s = {"날짜": DATE, "금액": INT}.get(kind) or choice([(o["코드"], o["표시"]) for o in q.get("선택지") or []])
            d = fld(n, labels.get(n, n), s, q=q["id"], qtext=q["질문"] if first else "")
            first = False
            extra.append(d)
    return {"main": main, "extra": extra}


# ---- 조립 -------------------------------------------------------------------
def read(name):
    with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def js_json(o):
    """script 안에 넣는 JSON. 닫는 태그나 주석 시작으로 읽히지 않게 막는다."""
    s = json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/").replace("<!--", "<\\!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render(path=QUESTIONS_PATH):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    defs, conds = build(doc)
    parts = {"STYLE": read("style.css").rstrip("\n"), "CORE": read("core.js").rstrip("\n"), "APP": read("app.js").rstrip("\n"),
             "DEFS": js_json(defs), "CONDITIONS": js_json(conds)}
    page = read("page.html")
    html = re.sub(r"@@([A-Z]+)@@", lambda m: parts[m.group(1)], page)
    return html


def main(argv=None):
    ap = argparse.ArgumentParser(description="고객용 HTML 질문지를 만든다")
    ap.add_argument("--출력", dest="out", default=DEFAULT_OUT)
    ap.add_argument("--문항", dest="path", default=QUESTIONS_PATH)
    a = ap.parse_args(argv)
    html = render(a.path)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "wb") as f:   # 줄끝을 LF 로 고정한다(기계마다 같은 바이트가 나와야 최신 여부를 견줄 수 있다)
        f.write(html.encode("utf-8"))
    print("질문지 HTML 을 썼습니다: %s (%d 바이트)" % (a.out, len(html.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
