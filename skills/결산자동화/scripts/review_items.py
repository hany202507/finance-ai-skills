# -*- coding: utf-8 -*-
"""확인 항목을 데이터에서 뽑고, AI 1차 의견을 붙인다.

엔진이 사람에게 넘기는 것(미분류 거래 · 잠정 처리 · 해외카드 · 거래처 미해소 · 검증 확인/FAIL)을
항목 하나씩 JSON 으로 낸다. AI 는 그 JSON 을 읽고 AI의견_{기간}.json 에 의견 · 근거 · 확신도를 적는다.
build_docx 가 둘을 id 로 합쳐 확인사항 문서에 싣는다.

AI 의견은 숫자를 바꾸지 않는다. 회계사가 받아들인 것만 프로파일 규칙이 되고, 엔진을 다시 돌려야
숫자가 바뀐다. 확신도가 높아도 확인 대상에서 빠지지 않는다.

사용:
  python review_items.py <raw_dir> <out_dir> <기간라벨> [profile_module]   # 항목 내보내기
  python review_items.py --check <out_dir> <기간라벨>                       # AI 의견 형식 점검
"""
import sys, os, io, json, hashlib, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

확신도_값 = ("높음", "중간", "낮음")


def _hid(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def _검증(out_dir, period):
    got = []
    for 이름, 파일 in (("업로드 사전검증", f"_검증_업로드_{period}.json"),
                     ("워크북 검산", f"_검증_워크북_{period}.json")):
        fp = os.path.join(out_dir, 파일)
        if os.path.exists(fp):
            got.append((이름, json.load(io.open(fp, encoding="utf-8"))))
    return got


def collect(eng, out_dir, period):
    """엔진 결과와 검증 JSON 에서 사람이 확인할 항목을 뽑는다. id 는 다시 돌려도 같다."""
    from close_engine import to_int
    P = eng.P
    items = []

    def add(id_, 구분, 내용, 엔진처리, 질문):
        items.append({"id": id_, "구분": 구분, "내용": 내용, "엔진처리": 엔진처리, "질문": 질문})

    # 1) 미분류 거래. 규칙에 안 걸려 가계정에 둔 통장 거래
    seen = {}
    for r in getattr(eng, "unclassified_rows", []):
        date, _acct, side, amt, 적요 = r[0], r[1], r[2], r[3], r[4]
        base = f"미분류-{date}-{side}-{amt}"
        seen[base] = seen.get(base, 0) + 1
        id_ = base if seen[base] == 1 else f"{base}-{seen[base]}"
        code, name = P.미분류_계정[side]
        add(id_, "미분류 거래", f"{date} {side} {amt:,}원 · 적요 「{적요}」",
            f"{name}({code}) 가계정에 대체", "어느 계정으로 분류하나")

    # 2) 기말재고 잠정. 실사표 없이 잠정 금액으로 원가를 대체했다
    기말 = eng._by_period(getattr(P, "상품_기말재고_잠정", 0)) or 0
    기초 = eng._by_period(getattr(P, "상품_기초재고", 0)) or 0
    if 기말 or 기초:
        add("잠정-기말재고", "잠정 처리", f"기초 {기초:,}원 · 기말 잠정 {기말:,}원(실사표 없음)",
            "잠정 기말재고로 매출원가 대체", "기말재고를 확정할 근거가 있나")

    # 3) 해외카드. 대리납부(부가세법 §52) 해당 여부는 거래 성격을 봐야 한다
    해외 = {}
    for r in eng.card:
        shop = r[3]
        spec = P.카드가맹점_계정.get(shop)
        if spec is None:
            continue
        if eng._by_period(spec)[2] == "해외":
            해외[shop] = 해외.get(shop, 0) + (to_int(r[6]) - to_int(r[7]))
    for shop, amt in sorted(해외.items()):
        add(f"해외카드-{shop}", "해외카드", f"{shop} 해외결제 {amt:,}원",
            "일반전표 전액비용(매입세액 없음)", "대리납부 대상 용역인가")

    # 4) 거래처 미해소. 거래처마스터에서 못 찾은 라벨
    for lab, accts in sorted(getattr(eng, "party_miss", {}).items()):
        add(f"거래처-{lab}", "거래처 미해소", f"라벨 「{lab}」(계정 {sorted(accts)})",
            "거래처코드 빈칸", "마스터 등록 · 별칭 · 집합거래처 중 무엇인가")

    # 5) 검증이 남긴 확인 · FAIL
    for 이름, d in _검증(out_dir, period):
        for 종류, msgs in (("FAIL", d.get("fail", [])), ("확인", d.get("확인", []))):
            for m in msgs:
                add(f"검증-{_hid(이름 + m)}", f"{이름} {종류}", m, "검증 스크립트 결과",
                    "이대로 두어도 되나")
    return items


def 참고자료(P):
    return {"전기_확정판단": list(getattr(P, "전기_확정판단", [])),
            "처리기준": "references/처리기준.md",
            "계정과목": "references/위하고_계정과목.csv"}


def load_opinions(out_dir, period):
    fp = os.path.join(out_dir, f"AI의견_{period}.json")
    if not os.path.exists(fp):
        return None
    return json.load(io.open(fp, encoding="utf-8")).get("의견", {})


def check_opinions(items, opinions):
    """AI 의견의 형식을 본다. 문제 목록을 돌려준다(빈 목록 = 통과)."""
    errs = []
    ids = {it["id"] for it in items}
    for it in items:
        o = opinions.get(it["id"])
        if o is None:
            errs.append(f"{it['id']}: 의견이 없다")
            continue
        if o.get("판단보류"):
            continue
        if not str(o.get("의견", "")).strip():
            errs.append(f"{it['id']}: 의견이 비었다(판단을 못 하면 판단보류 true)")
        if not o.get("근거"):
            errs.append(f"{it['id']}: 근거가 없다(근거가 없으면 판단보류 true)")
        if o.get("확신도") not in 확신도_값:
            errs.append(f"{it['id']}: 확신도 {o.get('확신도')!r} 는 높음·중간·낮음 중 하나여야 한다")
    for k in opinions:
        if k not in ids:
            errs.append(f"{k}: 항목 목록에 없는 id 다(엔진을 다시 돌렸으면 항목을 다시 내보낸다)")
    return errs


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if sys.argv[1] == "--check":
        out, period = sys.argv[2], sys.argv[3]
        d = json.load(io.open(os.path.join(out, f"_확인항목_{period}.json"), encoding="utf-8"))
        ops = load_opinions(out, period)
        if ops is None:
            print(f"AI의견_{period}.json 이 없다")
            sys.exit(1)
        errs = check_opinions(d["항목"], ops)
        보류 = sum(1 for o in ops.values() if o.get("판단보류"))
        for e in errs:
            print(f"  [형식] {e}")
        print(f"AI 의견 {len(ops)}/{len(d['항목'])}건 · 판단보류 {보류}건 · 형식 오류 {len(errs)}건")
        sys.exit(1 if errs else 0)

    from close_engine import Engine
    raw, out, period = sys.argv[1], sys.argv[2], sys.argv[3]
    P = importlib.import_module(sys.argv[4] if len(sys.argv) > 4 else "profile_sample")
    eng = Engine(raw, period, P).run()
    items = collect(eng, out, period)
    fp = os.path.join(out, f"_확인항목_{period}.json")
    json.dump({"회사": P.회사명, "기간": period, "참고": 참고자료(P), "항목": items},
              io.open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"확인 항목 {len(items)}건: {fp}")
    print(f"다음: AI 가 AI의견_{period}.json 에 의견을 채운 뒤 review_items.py --check 로 형식을 본다")


if __name__ == "__main__":
    main()
