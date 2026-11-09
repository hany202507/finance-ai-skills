"""명령줄: 단독 표본 조서(2026-11-09). __main__.py 가 dsd 처럼 따로 더한다.

  python -m audit sample scan <데이터 파일> [--tm <허용왜곡표시>] [--sheet <시트>] [--amount <열>] … [--json]
      뽑기 전에 파일을 읽는다(조서는 만들지 않음). 읽은 열 · 다른 숫자 열 · 금액 0 이하 행 · 일자 범위 · 결산일 어림 ·
      계층 후보 · 거래처 수 · 금액 상위 비중, --tm 을 주면 위험 수준별 표본 간격 · 점 수. AI 가 감사인에게 물을 것을 정할 때 쓴다
  python -m audit sample make <데이터 파일> --tm <허용왜곡표시> [--method mus|random|systematic|specific]
        [--risk 높음|보통|낮음|기본] [--factor <신뢰계수>] [--expected <예상 왜곡표시>] [--key <고액 기준>] [--size <표본 수>]
        [--top <상위 n>] [--window <결산일 전후 일수>] [--strata <계층 열>] [--group <묶을 열>] [--tail-months <n>] [--fy-end YYYY-MM-DD]
        [--control <시산표 금액>] [--seed <시드>] [--sheet <시트>] [--amount <열>] [--date <열>] [--party <열>] [--desc <열>] [--ref <열>]
        [--company <회사>] [--assertion <경영진 주장>] [--out <조서.xlsx>] [--full] [--force] [--json]
      데이터 파일 하나로 표본 조서(설계 · 표본 · 평가)를 만든다. 기본 저장 위치는 데이터 파일 옆 「표본_<파일 이름>.xlsx」.
      같은 조서가 있으면 감사인이 적은 값을 옮기고, 옮길 칸이 없는 값이 있으면 멈춘다(--force 로 덮어씀)
  python -m audit sample eval <조서.xlsx> [--json]
      감사인이 적은 검사 결과 · 왜곡표시 금액으로 엔진이 평가한다(엑셀 「허용왜곡표시와 견줌」 과 같은 판정)

끝난 값: 0(씀 · 평가함), 1(입력 오류 · 덮어쓰기 멈춤).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def register(sub) -> None:
    from .sample_wp import METHODS

    p = sub.add_parser("sample", help="단독 표본 조서: 데이터 파일 하나로 표본 설계 · 추출 · 평가")
    ss = p.add_subparsers(dest="scmd", required=True)
    sc = ss.add_parser("scan", help="뽑기 전에 데이터 파일을 읽어 열 · 기간 · 계층 후보 · 위험 수준별 표본 수를 보인다")
    sc.add_argument("data")
    sc.add_argument("--tm", type=float, default=None, help="주면 위험 수준별 표본 간격 · 점 수를 함께 낸다")
    sc.add_argument("--sheet", default=None)
    for role, h in (("amount", "금액"), ("date", "일자"), ("party", "거래처"), ("desc", "적요"), ("ref", "전표번호")):
        sc.add_argument(f"--{role}", default=None, help=f"{h} 열 이름")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_scan)
    m = ss.add_parser("make", help="데이터 파일로 표본 조서를 만든다")
    m.add_argument("data", help="매출 원장 · 세금계산서 목록 · 채권 명세 같은 표(xlsx · xls · csv)")
    m.add_argument("--tm", type=float, required=True, help="허용왜곡표시(보통 수행중요성)")
    m.add_argument("--method", choices=METHODS, default="mus",
                   help="mus 금액 단위 표본(통계) · random 무작위 · systematic 체계적(비통계) · specific 특정 항목 선정(표본감사 아님)")
    m.add_argument("--risk", default=None, help="위험 수준(sampling.yaml risk_levels). 조서 기입란보다 앞선다")
    m.add_argument("--factor", type=float, default=None, help="신뢰계수 직접 입력(위험 수준보다 앞선다)")
    m.add_argument("--expected", type=float, default=None, help="예상 왜곡표시. 비우면 조서 기입란, 그것도 없으면 0")
    m.add_argument("--key", type=float, default=None, help="고액 기준(전수 검사). 표본 간격보다 크게는 못 잡는다. specific 에서는 금액 기준")
    m.add_argument("--size", type=int, default=None, help="random · systematic 표본 수(비우면 표본 대상 금액 ÷ 표본 간격)")
    m.add_argument("--top", type=int, default=None, help="specific: 금액 상위 n 건")
    m.add_argument("--window", type=int, default=None, help="specific: 결산일 전후 n 일(--fy-end 필요)")
    m.add_argument("--strata", default=None, help="계층으로 나눌 열 이름(제품 · 상품 · 수출 같은 구분)")
    m.add_argument("--group", default=None, help="이 열 값이 같은 행을 더해 표본 단위 하나로 본다(거래처별 묶기)")
    m.add_argument("--tail-months", type=int, default=None, help="결산일 앞 n 개월을 따로 계층으로 둔다(--fy-end 필요)")
    m.add_argument("--fy-end", default=None, help="결산일 YYYY-MM-DD. 사업연도에 들지 않는 일자를 모집단에서 뺀다")
    m.add_argument("--control", type=float, default=None, help="시산표 · 원장 금액(모집단 대사)")
    m.add_argument("--seed", type=int, default=None, help="시드(비우면 sampling.yaml seed)")
    m.add_argument("--sheet", default=None, help="읽을 시트(비우면 금액 열이 있는 표를 찾는다)")
    for role, h in (("amount", "금액"), ("date", "일자"), ("party", "거래처"), ("desc", "적요"), ("ref", "전표번호")):
        m.add_argument(f"--{role}", default=None, help=f"{h} 열 이름(비우면 머리줄 이름으로 찾는다)")
    m.add_argument("--company", default=None, help="조서 머리의 회사명")
    m.add_argument("--assertion", default=None, help="테스트 목적 · 경영진 주장(발생사실 · 실재성 · 정확성 · 기간귀속 · 완전성 …)")
    m.add_argument("--title", default=None, help="조서 제목(비우면 「표본 조서」)")
    m.add_argument("--out", default=None, help="조서 파일(비우면 데이터 파일 옆 표본_<파일 이름>.xlsx)")
    m.add_argument("--full", action="store_true", help="모집단 전 항목 시트를 함께 넣는다")
    m.add_argument("--force", action="store_true", help="옮길 칸이 없는 앞 판 기입값을 버리고 덮어쓴다")
    m.add_argument("--json", action="store_true")
    m.set_defaults(func=_make)
    e = ss.add_parser("eval", help="감사인이 적은 왜곡표시로 엔진이 평가한다")
    e.add_argument("path")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=_eval)


def _out():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _scan(a) -> int:
    from . import dataset, sample_wp

    _out()
    opt = {k: getattr(a, k) for k in ("sheet", "amount", "date", "party", "desc", "ref")}
    try:
        r = sample_wp.scan(Path(a.data), a.tm, **opt)
    except sample_wp.SampleError as ex:
        print(f"데이터 파일을 읽지 못했습니다: {ex}")
        return 1
    if a.json:
        print(json.dumps(r, ensure_ascii=False, default=str, indent=1))
        return 0
    sk, po, ne, dt = r["skipped"], r["positive"], r["nonpositive"], r["dates"]
    print(f"데이터: {r['file']} 「{r['sheet']}」 머리줄 {r['header_row']}행 · 읽은 행 {r['rows']:,} "
          f"(합계 행 {sk['합계 행']:,} · 금액 없음 {sk['금액 없음']:,} 뺌)")
    print("  열: " + " · ".join(f"{dataset.ROLE_NAMES.get(k, k)}={v}" for k, v in r["cols"].items()))
    if r["other_numeric"]:
        print(f"  다른 숫자 열: {' · '.join(r['other_numeric'])} (금액 열을 바꾸려면 --amount)")
    print(f"  금액 0 보다 큼 {po['count']:,}건 {po['total']:,.0f}원 · 0 이하 {ne['count']:,}건 {ne['total']:,.0f}원(모집단에서 뺌)")
    if dt["min"]:
        print(f"  일자 {dt['min']} ~ {dt['max']}" + (f" · 일자 없음 {dt['missing']:,}행" if dt["missing"] else "")
              + f" · 결산일 어림 {r['fy_end_guess']}(이 사업연도에 들지 않는 행 {r['outside_guess']:,})")
    print(f"  사업연도 순합계 {r['net_fy_guess']:,.0f}원(반품 포함, 결산일 뒤 제외). 이 금액을 그 계정 시산표 · 원장 금액과 맞춘다")
    if r["party"]:
        print(f"  거래처 {r['party']['distinct']:,}곳(두 번 이상 나온 곳 {r['party']['repeat']:,})")
    for c in r["strata_candidates"]:
        print(f"  계층 후보 「{c['col']}」: " + " · ".join(f"{v['value']} {v['count']:,}건 {v['total']:,.0f}원" for v in c["values"]))
    print(f"  금액 상위 10건이 0 보다 큰 금액의 {r['top10_share']:.1%}")
    for z in r["sizes"]:
        print(f"  위험 {z['risk']}: 신뢰계수 {z['factor']:.2f} · 간격 {z['interval']:,.0f}원 · 점 {z['points']:,} · 간격 이상 {z['key_items']:,}건"
              " (결산일 · 계층 · 묶기 전 어림)")
    return 0


def _make(a) -> int:
    from . import dataset, sample_wp
    from .workpapers.common import Kept

    _out()
    opt = {k: getattr(a, k) for k in ("method", "risk", "factor", "expected", "key", "size", "top", "window", "strata", "group",
                                      "tail_months", "fy_end", "control", "seed", "sheet", "amount", "date", "party", "desc", "ref",
                                      "company", "assertion", "title", "full", "force")}
    try:
        r = sample_wp.make(Path(a.data), a.tm, Path(a.out) if a.out else None, **opt)
    except sample_wp.SampleError as ex:
        print(f"표본 조서를 만들지 못했습니다: {ex}")
        return 1
    except Kept as ex:
        print(str(ex))
        return 1
    if a.json:
        print(json.dumps(r, ensure_ascii=False, default=str, indent=1))
        return 0
    sk = r["skipped"]
    print(f"표본 조서: {r['path']}")
    print(f"  데이터: {r['file']} 「{r['sheet']}」 · 읽은 행 {r['rows']:,} (합계 행 {sk['합계 행']:,} · 금액 없음 {sk['금액 없음']:,} 뺌)")
    print("  열: " + " · ".join(f"{dataset.ROLE_NAMES.get(k, k)}={v}" for k, v in r["cols"].items()))
    print(f"  모집단: {r['pop_count']:,}건 {r['pop_total']:,.0f}원"
          + (" · 모집단에서 뺀 항목 " + " · ".join(f"{w} {v['count']:,}건 {v['total']:,.0f}원" for w, v in r["excluded_by"].items())
             if r["excluded_by"] else ""))
    if r["control"] is not None:
        print(f"  모집단 대사: 사업연도 순합계 {r['net_fy']:,.0f}원 − 시산표 · 원장 {r['control']:,.0f}원 = 차이 {r['control_diff']:,.0f}원"
              + (" (일치)" if abs(r["control_diff"]) < 0.5 else " (차이 설명은 「설계」 시트에 감사인이 적는다)"))
    else:
        print(f"  모집단 대사: 시산표 · 원장 금액을 받지 않음(사업연도 순합계 {r['net_fy']:,.0f}원). 「설계」 시트에 적거나 --control 로 다시 돌린다")
    print(f"  위험 {r['risk']} ({r['risk_source']}) · 신뢰수준 {r['confidence']:.1%} · 신뢰계수 {r['factor']:.2f}"
          + (f" · 예상 왜곡표시 {r['expected']:,.0f} × 확장계수 {r['ef']:.2f}" if r["expected"] else ""))
    print(f"  표본 간격 {r['interval']:,.0f}원 · 시드 {r['seed']}")
    if r["method"] == "specific":
        print(f"  특정 항목 선정 {r['selected']:,}건(표본감사 아님, 투영하지 않음)")
    else:
        kt, rest = r["key_threshold"], r["selected"] - r["key_items"]
        how = {"mus": "간격 선정", "random": "무작위", "systematic": "체계적"}[r["method"]]
        tail = (f"계층마다 올림한 계획 점 {r['planned']:,} · 실제 찍힌 점 {r['points']:,}" if r["method"] == "mus"
                else f"계획 {r['planned']:,}")
        print(f"  고른 항목 {r['selected']:,}건 = 고액 기준 {kt:,.0f}원 이상 전수 {r['key_items']:,}건 + {how} {rest:,}건 ({tail})")
    if len(r["strata"]) > 1:
        for s in r["strata"]:
            print(f"    계층 {s['label']}: {s['count']:,}건 {s['total']:,.0f}원 · 고액 {s['key_count']:,} · 고른 항목 {s['picked']:,}")
    if r["risk_source"].startswith("초기값"):
        print("  주의: 위험 수준을 초기값으로 뽑았습니다. 감사인이 「설계」 시트의 위험 수준을 확인해 주십시오")
    if r["moved"] or r["lost"]:
        print(f"  앞 판 기입값 {r['moved']}개 옮김" + (f" · 버림 {len(r['lost'])}개(--force)" if r["lost"] else ""))
    return 0


def _eval(a) -> int:
    from . import sample_wp

    _out()
    try:
        r = sample_wp.evaluate(Path(a.path))
    except (sample_wp.SampleError, FileNotFoundError) as ex:
        print(f"평가하지 못했습니다: {ex}")
        return 1
    if a.json:
        print(json.dumps(r, ensure_ascii=False, default=str, indent=1))
        return 0
    print(f"평가: {Path(a.path).name} ({r['method']}) · 항목 {r['items']:,} · 검사 결과 빈 항목 {r['pending']:,} · 왜곡 있는 항목 {r['with_error']:,}")
    if r["method"] == "mus":
        print(f"  기본 정밀도 {r['basic']:,.0f}")
        for side, name in (("over", "과대계상"), ("under", "과소계상")):
            print(f"  {name}: 투영 {r[f'projected_{side}']:,.0f} · 증분 허용 {r[f'increment_{side}']:,.0f} · 상한 {r[f'upper_{side}']:,.0f}")
        print(f"  모집단 왜곡표시 추정치 {r['estimate']:,.0f}")
    elif r["method"] in ("random", "systematic"):
        print(f"  투영 과대 {r['projected_over']:,.0f} · 과소 {r['projected_under']:,.0f} · 추정치 {r['estimate']:,.0f}")
    else:
        print(f"  찾은 왜곡 과대 {r['found_over']:,.0f} · 과소 {r['found_under']:,.0f} · 선정하지 않은 나머지 {r['rest']:,.0f}")
    print(f"  허용왜곡표시 {r['tolerable']:,.0f} → {r['verdict']}")
    return 0
