"""DSD 푸팅 명령줄(2026-10-12). 감사 폴더 없이 dsd 한 파일로 돈다.

  python -m audit dsd read <dsd> [--out 폴더]
      격자로 읽어 dsd_표.json 을 쓴다
  python -m audit dsd foot <dsd> [--links 연결.json [--add]] [--text 문장.json …] [--prev 기존 판] [--prior 작년 보고서] [--wtb 정산표] [--pair 다른 보고서] [--out 폴더] [--defs 파일]
      검증 엑셀을 만든다. 오버뷰에 합계 · 레퍼 · 전기 · 버전 네 가지가 신호등으로 보인다.
      --links 를 주면 먼저 links --apply 와 같이 연결을 넣고(풀리지 않는 칸이 있으면 엑셀을 만들지 않고 1 로 끝난다), --text 에 여럿을 주면
      text --apply 와 같이 합쳐 문장.json 에 쓴 뒤 엑셀까지 한 번에 돈다(2026-10-23 분석 6.7. 모듈 불러오기 약 3초를 한 번만 쓴다).
      --prev 를 주면 기존 판 대비 바뀐 곳을, --prior 를 주면 전기 숫자가 작년 보고서와 같은지를 본다.
      FALSE 나 풀지 못한 연결이 있으면 1 로 끝난다. 바뀐 곳, 확인, 전기 대사에서 못 찾은 줄은 종료 코드에 넣지 않는다.
      --wtb 는 8100B · WTB 양식 · 감사 법인 양식(BS · IS · WBS · WIS · AJE)을 읽는다. 읽지 못하는 양식이면 「이 WTB 양식을 읽지 못함: …」 한 줄로 2 로 끝난다.
  python -m audit dsd links <dsd> [--text [--facts 기준사실.json] [--case 감사 폴더] [--split N]] [--out 폴더] [--defs 파일]
      AI 가 읽을 자료를 낸다: dsd_읽기자료.md(맨 앞에 연결.json 쓰는 법, 재무제표와 주석 전부, 표마다 줄 · 열 번호), 연결_초안.json(빈 연결.json 과 할 일),
      dsd_연결요청.json(아직 주석과 이어지지 않은 과목, 금액 대조가 찾은 참고, 엔진의 연결 후보 proposals). 연결 후보(2026-10-22)는 위치 · 이름 · XBRL 코드로 내고
      금액은 보지 않는다. 읽기 자료의 표 아래 「후보 P0001」 줄로도 보인다. --text 면 문장 검토의 문장읽기.md 도 함께 쓴다(dsd text 와 같다)
  python -m audit dsd links <dsd> --apply <연결.json> [--add] [--out 폴더] [--defs 파일]
      AI 가 적은 연결을 검사해 dsd_연결정의.json 에 넣는다. 이름이 칸으로 풀리지 않는 연결이 하나라도 있으면 아무것도 쓰지 않고 1 로 끝난다.
      연결.json 은 AI 연결의 전체 목록이다. 앞서 넣은 AI 연결은 이 목록으로 바뀐다(--add 면 두고 더한다). 넣은 뒤 dsd_연결요청.json 을 다시 쓴다
      연결.json 에 proposals(후보 번호의 O · X · 고침)가 있으면 후보 전부에 판정이 있어야 넣는다(--add 면 앞서 판정한 후보는 판정한 것으로 본다)

  python -m audit dsd fetch <접수번호 | PDF> [--out 폴더] [--no-prior]
      OpenDART 공시서류원본(xml)을 받는다(2026-10-22). PDF 는 DART 에서 받은 「[회사]보고서(접수일).pdf」 꼴이면 그날 그 회사의 공시를 찾는다.
      사업 · 반기 · 분기보고서면 <접수번호>_연결.xml · _별도.xml 로 나누고, 작년 비교 보고서(직전 사업보고서, 작년 같은 기간 보고서)도 받아 나눈다.
      끝에 foot 명령(--prior · --pair 를 채운 것)을 적어 준다. 인증키는 환경변수 DART_API_KEY 에서만 읽는다. 받지 못하면 한 줄로 2 로 끝난다

  python -m audit dsd text <dsd> [--facts 기준사실.json] [--case 감사 폴더] [--prior 작년 보고서] [--split N] [--apply 문장.json …] [--out 폴더]
      문장 검토(2026-10-17): 표가 아닌 글과 표 안 글자를 읽어 문장읽기.md(AI 가 읽을 글 전부와 엔진이 찾은 것)와 문장검토.json 을 쓴다.
      --split N 이면 문장읽기를 주석 제목에서 끊어 문장읽기_1.md … _N.md 로도 쓴다(2026-10-22, 에이전트 N 명이 동시에 읽는다. 글이 짧으면 덜 나눈다).
      --apply 로 AI 가 적은 문장.json 을 넣으면 발췌가 원문에 있는지 본다. 여럿을 주면(문장_1.json 문장_2.json) 하나로 합쳐 문장.json 에 쓴다.
      foot 은 폴더의 기준사실.json · 문장.json 을 함께 읽어 「문장 검토」 시트를 만든다

  foot 에 --html 을 주면(2026-10-26) 엑셀 옆에 판 비교 · 숫자 검증 HTML(DSD보기_<이름>.html)과 자료 dsd_보기.json 을 쓴다. --prev 와 함께면(2026-11-04)
      판 비교 화면은 dsd diff --html 과 같은 셈(추가 · 삭제 · 변경 색과 거르기, 바뀐 곳 목록)이고 판비교_<옛>_<새>.xlsx · .json 도 쓴다. --mask 치환표.json 이면
      이름을 바꾼 판(_치환.html)도 쓴다(치환 뒤 check 에 걸리는 글이 남으면 2). 결과 폴더의 확인_*.json(HTML 에서 내려받은 O · X)은 엑셀 확인 칸과 함께 읽는다
  python -m audit dsd view <결과 폴더 | dsd_보기.json> [--mask 치환표.json] [--out 폴더]
      dsd_보기.json 으로 HTML 을 다시 만든다(템플릿만 고쳤을 때, 이름 치환판이 필요할 때)
  python -m audit dsd sheet <dsd | xml> [--roll] [--out 폴더]
      DSD → 엑셀(2026-10-26): 원고 엑셀(원고_<이름>.xlsx)을 쓴다. 요소 하나가 원고 줄 하나, 글과 숫자는 원문 그대로, 병합 칸은 회색.
      표 오른쪽 「검증」 열에 표 안 합계 수식. --roll 이면 작년 판으로 당기 초안을 만든다(당기 열 → 전기 열, 기수 · 해 +1. 못 한 표는 원고 안내에)
  python -m audit dsd build <원고.xlsx> [--out 파일]
      엑셀 → DSD: 바탕이 dsd 면 고친 요소의 글자만 바꾸고(고치지 않으면 contents.xml 이 바탕과 바이트까지 같다), 바탕이 공시 xml 이면
      엔진 틀에 넣는다. 원고 검사(엑셀 손상 · 옮기지 못한 것 · 롤포워드에서 남은 곳)를 원고검사.json 과 화면에 낸다
  foot · links · text · diff 에 dsd 대신 원고 엑셀을 주면 먼저 dsd 로 만들어 돈다. foot 은 「원고 검사」 시트를 더하고 --prev 가 없으면 바탕 판과 견준다
  python -m audit dsd diff <옛 판> <새 판> [--html [--mask 치환표.json]] [--out 폴더]
      판 비교(2026-10-26): 두 판의 추가 · 삭제 · 변경 · 옮김 · 나뉨 · 합침을 판비교_<옛>_<새>.xlsx(요약 · 바뀐 곳 · 바뀐 부분 시트)와
      같은 이름의 .json 으로 낸다. 표지 · 감사보고서 · 재무제표 · 주석 · 외부감사 실시내용을 견준다. 푸팅은 돌리지 않는다.
      --html 이면(2026-11-03) 같은 결과를 판비교_<옛>_<새>.html 로도 쓴다. 기존 판 · 새 판을 나란히 두고 추가(연두) · 삭제(분홍) · 변경(하늘색,
      칸에 마우스를 올리면 기존 값 · 차이) · 옮김 · 나뉨 · 합침(주황)을 색과 거르기로 나누고, 바뀐 곳 목록에서 누르면 그 칸으로 간다.
      --mask 면 이름을 바꾼 판(_치환.html)도 쓴다(치환 뒤 check 에 걸리는 글이 남으면 HTML 을 만들지 않고 2).
      바뀐 곳이 있어도 0 으로 끝난다(읽지 못하면 한 줄로 2)

  python -m audit dsd quick <dsd> [--wtb …] [--prior …] [--prev …] [--pair …] [--facts …] [--case …] --out <폴더> [--serve [--port 8791]]
      빠른 검토(2026-11-04): links --text 와 foot --html 을 한 번에 돈다. AI 연결 정의가 아직 없으면 연결_초안.json 을 넣어 엔진 후보를
      판정 없이 건다. AI 없이 첫 HTML 까지 간다(한 회사 vF 14초). --serve 면 끝나고 검토 화면 서버를 띄운다
  python -m audit dsd serve <결과 폴더> [--port 8791] [--no-open]
      검토 화면 서버(2026-11-04): DSD보기 HTML 을 127.0.0.1 에서 열고, 화면의 「수정」 을 받아 원본은 두고 <이름>_수정판.dsd 에 쓴 뒤
      foot 을 다시 돌린다(옵션은 foot --html 이 남긴 dsd_실행.json). 수정 기록은 수정기록.json, 되돌리기는 마지막 묶음을 뺀다
  python -m audit dsd fix <dsd> <수정_이름.json> [--out 파일]
      서버 없이 연 화면에서 내려받은 수정 목록을 dsd 에 쓴다. 숫자 칸은 값 · 줄 이름으로, 문장은 고칠 글로 원문 요소를 찾고,
      쓴 뒤 다시 판독해 다른 숫자 칸이 바뀌었으면 쓰지 않는다. 못 고친 것이 있으면 1

dsd 자리에는 DART 편집기 파일(.dsd)이나 OpenDART 공시서류원본파일(.xml)을 준다.
"""
from __future__ import annotations

import re
from pathlib import Path


def register(sub) -> None:
    p = sub.add_parser("dsd", help="회사 제시 dsd 푸팅: 격자 판독과 수식 검증 엑셀")
    ps = p.add_subparsers(dest="dcmd", required=True)
    r = ps.add_parser("read", help="dsd 를 재무제표와 주석 번호별 격자로 읽는다")
    r.add_argument("dsd")
    r.add_argument("--out", default=None)
    r.set_defaults(func=_read)
    f = ps.add_parser("foot", help="수식 검증 엑셀을 만든다")
    f.add_argument("dsd")
    f.add_argument("--prev", default=None, help="기존 판(dsd · xml). 바뀐 곳을 본다")
    f.add_argument("--prior", default=None, nargs="+",
                   help="작년 보고서(dsd · xml). 전기 숫자가 같은지 본다. 반기 · 분기보고서는 둘을 준다(직전 사업보고서, 작년 같은 기간의 보고서)")
    f.add_argument("--wtb", default=None, help="정산표 엑셀(8100B · WTB 양식 · 감사 법인 양식 BS · IS · WBS · WIS · AJE). 본표 과목을 감사한 금액과 견준다. "
                                                 "엑셀에서 계산된 값이 저장된 파일이어야 한다. 읽지 못하는 양식이면 한 줄 오류로 2 로 끝난다")
    f.add_argument("--pair", default=None, help="함께 낸 다른 보고서(연결이면 별도, 별도면 연결). 자본금처럼 두 보고서에 같은 금액과 「짝:」 으로 적은 연결을 견준다")
    f.add_argument("--out", default=None)
    f.add_argument("--defs", default=None)
    f.add_argument("--amount-links", action="store_true", help="금액이 같은 칸을 엔진이 찾아 함께 건다(기본은 AI 가 정의한 연결만)")
    f.add_argument("--facts", default=None, help="문장 검토의 기준 사실 json(없으면 --out 폴더의 기준사실.json)")
    f.add_argument("--case", default=None, help="감사 폴더. 회사명 · 결산일과 공시 확인 대상(의사록 · 등기부 판독 사실)을 읽는다")
    f.add_argument("--text", default=None, nargs="+", help="AI 가 적은 문장 검토 json(없으면 --out 폴더의 문장.json). 여럿이면(문장_1.json 문장_2.json) 합쳐 문장.json 에 쓴다")
    f.add_argument("--links", default=None, nargs="+", help="AI 가 적은 연결.json. 엑셀을 만들기 전에 links --apply 와 같이 넣는다(2026-10-23). "
                                                             "여럿이면(몫마다 적은 연결_1.json 연결_2.json) 첫 파일 옆 연결.json 으로 합쳐 넣는다(2026-11-09)")
    f.add_argument("--part", type=int, default=0, help="--links 와 함께: 몫 번호. 화면 · 판정자료의 FALSE · 확인을 그 몫 것만 낸다(links --parts 가 쓴 dsd_몫.json)")
    f.add_argument("--add", action="store_true", help="--links 와 함께: 앞서 넣은 AI 연결을 두고 더한다")
    f.add_argument("--html", action="store_true", help="판 비교 · 숫자 검증 HTML 보기(DSD보기_<이름>.html)와 자료 dsd_보기.json 도 쓴다")
    f.add_argument("--stage", choices=("회사제시", "제출"), default=None,
                   help="문장 검토에서 감사인 절(외부감사 실시내용 · 감사보고서) 빈칸을 셀 방법. 회사제시 초안이면 「감사인 작성 전」 으로 따로 묶는다. "
                        "없으면 파일 이름(회사제시) · 받은자료 폴더로 정한다(2026-11-04)")
    f.add_argument("--mask", default=None, help="이름 치환표 json(subs · check). HTML 을 이름 바꾼 판(_치환)으로 쓴다. 저장소에 넣지 않는다")

    vw = ps.add_parser("view", help="dsd_보기.json 으로 HTML 보기를 다시 만든다(템플릿만 고쳤거나 이름 치환판이 필요할 때)")
    vw.add_argument("src", help="결과 폴더 또는 dsd_보기.json")
    vw.add_argument("--mask", default=None, help="이름 치환표 json")
    vw.add_argument("--out", default=None, help="쓸 폴더. 없으면 자료가 있는 폴더")
    vw.set_defaults(func=_view)
    f.set_defaults(func=_foot)
    t = ps.add_parser("text", help="문장 검토: 오타 · 표현 · 사실 불일치(주소 · 대표이사 · 감사기간 · 보고서일) · 공시 누락")
    t.add_argument("dsd")
    t.add_argument("--facts", default=None)
    t.add_argument("--case", default=None)
    t.add_argument("--prior", default=None, help="작년 보고서. 같은 문장에 작년 날짜가 남은 곳을 본다")
    t.add_argument("--apply", default=None, nargs="+", help="AI 가 적은 문장.json. 폴더에 문장.json 으로 옮겨 둔다. 여럿이면 하나로 합친다")
    t.add_argument("--split", type=int, default=0, help="문장읽기를 N 몫으로도 나눠 쓴다(문장읽기_1.md …). 에이전트 N 명이 한 몫씩 읽는다")
    t.add_argument("--stage", choices=("회사제시", "제출"), default=None, help="foot 의 --stage 와 같다")
    t.add_argument("--out", default=None)
    t.set_defaults(func=_text)
    k = ps.add_parser("links", help="AI 가 정할 연결의 요청 자료를 내거나(--apply 없이) AI 가 적은 연결을 넣는다(--apply)")
    k.add_argument("dsd")
    k.add_argument("--apply", default=None, help="AI 가 적은 연결 json. 앞서 넣은 AI 연결은 이 파일의 것으로 바뀐다")
    k.add_argument("--add", action="store_true", help="--apply 와 함께: 앞서 넣은 AI 연결을 두고 더한다")
    k.add_argument("--carry", default=None, help="--apply 와 함께: --apply 의 연결을 적은 판(dsd · xml). 표 번호와 줄 이름을 이 판에 맞게 옮겨서 넣는다")
    k.add_argument("--text", action="store_true", help="--apply 없이: 문장 검토의 문장읽기.md 도 함께 쓴다(dsd text 와 같다)")
    k.add_argument("--facts", default=None, help="--text 와 함께: 기준 사실 json(없으면 --out 폴더의 기준사실.json)")
    k.add_argument("--case", default=None, help="--text 와 함께: 감사 폴더")
    k.add_argument("--prior", default=None, nargs="+", help="--text 와 함께: 작년 보고서(같은 문장에 작년 날짜가 남은 곳을 본다). foot 처럼 둘을 줘도 되고 첫째만 쓴다")
    k.add_argument("--split", type=int, default=0, help="--text 와 함께: 문장읽기를 N 몫으로도 나눠 쓴다")
    k.add_argument("--parts", type=int, default=0, help="숫자 쪽 읽기 자료 · 연결_초안을 주석 범위 N 몫으로도 나눠 쓴다(dsd_읽기자료_1.md · 연결_초안_1.json …, 2026-11-09)")
    # quick 이 --stage 를 links 에 넘긴다. 옵션이 없어 「unrecognized arguments」 로 멈췄다(2026-11-06 실제 회사 시험)
    k.add_argument("--stage", choices=("회사제시", "제출"), default=None, help="--text 와 함께: foot 의 --stage 와 같다")
    k.add_argument("--out", default=None)
    k.add_argument("--defs", default=None)
    k.set_defaults(func=_links)
    sh = ps.add_parser("sheet", help="DSD → 엑셀: dsd · 공시 xml 을 원고 엑셀로 쓴다")
    sh.add_argument("dsd")
    sh.add_argument("--roll", action="store_true", help="작년 판으로 당기 초안: 당기 열을 전기 열로 옮기고 당기 칸을 비운다")
    sh.add_argument("--out", default=None)
    sh.set_defaults(func=_sheet)
    bd = ps.add_parser("build", help="엑셀 → DSD: 원고 엑셀로 dsd 를 만든다")
    bd.add_argument("xlsx")
    bd.add_argument("--out", default=None, help="만들 dsd 경로. 없으면 원고 옆 <이름>_원고판.dsd")
    bd.set_defaults(func=_build)
    v = ps.add_parser("diff", help="판 비교: 두 판(dsd · xml)의 추가 · 삭제 · 변경을 엑셀로 낸다")
    v.add_argument("old", help="옛 판")
    v.add_argument("new", help="새 판")
    v.add_argument("--out", default=None, help="결과 폴더. 없으면 새 판이 있는 폴더")
    v.add_argument("--html", action="store_true", help="판 비교 HTML(판비교_<옛>_<새>.html)도 쓴다. 추가 · 삭제 · 변경을 색으로 나누고 목록에서 그 칸으로 간다")
    v.add_argument("--mask", default=None, help="이름 치환표 json. 이름을 바꾼 HTML(_치환.html)도 쓴다(--html 을 뜻한다)")
    v.set_defaults(func=_diff)
    g = ps.add_parser("fetch", help="OpenDART 원문 xml 을 받아 정기보고서면 연결 · 별도로 나눈다(작년 비교 보고서도)")
    g.add_argument("src", help="접수번호(14자리) 또는 DART 에서 받은 PDF")
    g.add_argument("--out", default=None, help="받을 폴더. 없으면 PDF 가 있는 폴더(접수번호면 지금 폴더). 그 아래 원문_<접수번호>/ 에 둔다")
    g.add_argument("--no-prior", action="store_true", help="작년 비교 보고서를 받지 않는다")
    g.set_defaults(func=_fetch)
    cv = ps.add_parser("convert", help="DART 공시 원문 → 편집기 dsd: 본문은 원문 그대로 두고 편집기 뼈대(삽입 위치 · 목차 · 안내문 · 머리)만 되살린다")
    cv.add_argument("src", help="접수번호(14자리), DART 에서 받은 PDF, 또는 공시 원문 xml(감사보고서 · 연결감사보고서)")
    cv.add_argument("--out", default=None, help="결과 폴더. 없으면 원문 xml 이 있는 폴더(접수번호면 지금 폴더)")
    cv.add_argument("--roll", action="store_true", help="다음 기수 초안도 만든다: 당기 숫자 → 전기 칸, 기수 · 해 +1, 당기 칸 비움(dsd sheet --roll → build)")
    cv.add_argument("--bare", action="store_true", help="뼈대 없이: 머리 감싸개와 meta.xml 만 더한다(편집기 확인용 비교판)")
    cv.add_argument("--view", default=None, help="같은 보고서의 DART 공시 화면 HTML. 없으면 원문 옆 <이름>.view.html 을 쓴다. 원문에서 빠진 줄바꿈을 되살린다")
    cv.set_defaults(func=_convert)
    q = ps.add_parser("quick", help="빠른 검토: links --text 와 foot --html 을 한 번에(엔진 후보는 판정 없이 넣는다). AI 없이 첫 HTML 까지")
    q.add_argument("dsd")
    for name in ("prev", "wtb", "pair", "facts", "case", "mask"):
        q.add_argument(f"--{name}", default=None)
    q.add_argument("--prior", default=None, nargs="+")
    q.add_argument("--stage", choices=("회사제시", "제출"), default=None)
    q.add_argument("--out", default=None)
    q.add_argument("--serve", action="store_true", help="끝나면 검토 화면 서버를 띄운다(dsd serve 와 같다)")
    q.add_argument("--port", type=int, default=8791)
    q.set_defaults(func=_quick)
    fx = ps.add_parser("fix", help="수정 목록(HTML 에서 내려받은 수정_<이름>.json)을 dsd 에 써서 수정판을 만든다. 원본은 두고 <이름>_수정판.dsd 에 쓴다")
    fx.add_argument("dsd")
    fx.add_argument("items", help="수정 목록 json({\"items\": [...]} 또는 목록)")
    fx.add_argument("--out", default=None, help="만들 dsd 경로. 없으면 원본 옆 <이름>_수정판.dsd")
    fx.set_defaults(func=_fix)
    sv = ps.add_parser("serve", help="검토 화면 서버: DSD보기 HTML 을 127.0.0.1 에서 열고 「수정」 을 받아 수정판을 쓰고 다시 검증한다")
    sv.add_argument("folder", help="foot --html 결과 폴더(dsd_실행.json 이 있는 곳)")
    sv.add_argument("--port", type=int, default=8791)
    sv.add_argument("--no-open", action="store_true", help="브라우저를 열지 않는다")
    sv.set_defaults(func=_serve)


def _out_dir(a) -> Path:
    d = Path(a.out) if a.out else Path(a.dsd).resolve().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(a) -> int:
    import json

    from .report import dsd_grid

    doc = dsd_grid.read_grid(Path(a.dsd))
    out = _out_dir(a) / "dsd_표.json"
    out.write_text(json.dumps(dsd_grid.to_json(doc), ensure_ascii=False, indent=1), encoding="utf-8")
    notes = sum(1 for p in doc.parts if p.key.startswith("주석"))
    print(f"{doc.source}: 재무제표 {len(doc.parts) - notes}개 · 주석 {notes}개 · 표 {len(doc.tables())}개 → {out}")
    return 0


def foot(src: Path, out: Path, prev: Path | None = None, prior: Path | None = None, defs_path: Path | None = None, amount_links: bool = False,
         wtb: Path | None = None, pair: Path | None = None, facts: Path | None = None, case: Path | None = None, text: Path | None = None,
         draft: list | None = None, html: bool = False, mask: Path | None = None, stage: str | None = None, only=None) -> dict:
    """검증 엑셀을 만들고 요약을 돌려준다. {book, doc, checks, unresolved, changes, consistency, view}
    html 이면 같은 결과를 dsd_보기.json 과 DSD보기_<이름>.html 로도 쓴다(2026-10-26). mask 는 이름 치환표 json(HTML 만 치환한다)."""
    import json

    from .report import dsd_book, dsd_compare, dsd_grid, dsd_links

    defs_path = defs_path or out / "dsd_연결정의.json"
    book = out / f"DSD푸팅_{src.stem}.xlsx"
    defs = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.exists() else {}
    from .report import dsd_view

    xlsx_marks = [(old, dsd_book.read_marks(old)) for old in sorted(out.glob("DSD푸팅_*.xlsx"), key=lambda p: p.stat().st_mtime)]
    marks, mark_notes = dsd_view.merge_marks(dict(defs.get("marks", {})), out, xlsx_marks)     # HTML 에서 내려받은 확인_*.json 도 읽는다
    defs["marks"] = marks
    cache = dsd_grid.cache_dir()                      # 넣기마다 foot 을 다시 돌려도 같은 파일은 다시 판독하지 않는다(2026-10-22 P5)
    doc = dsd_grid.read_cached(src, cache)
    pdoc = dsd_grid.read_cached(prev, cache) if prev else None
    priors = [prior] if isinstance(prior, (str, Path)) else list(prior or [])
    ydocs = [dsd_grid.read_cached(Path(p), cache) for p in priors]
    odoc = dsd_grid.read_cached(Path(pair), cache) if pair else None
    checks, new_defs, unresolved = dsd_links.build(doc, defs, amount_links=amount_links, other=odoc)
    ydoc = None
    prior_matches: list = []                          # (작년 문서, 앞머리, 짝) 차이 설명 후보의 「작년 이름」 에 쓴다(11단계)
    if ydocs:
        ydoc, groups = dsd_links.join_priors(ydocs)       # 둘째 보고서의 표는 이름 앞에 ② 를 붙여 한 문서로 잇는다
        for y, tag in groups:
            ym = dsd_compare.match(doc, y)
            prior_matches.append((y, tag, ym))
            more, missing = dsd_links.prior_checks(doc, y, ym, tag, defs.get("prior_pairs", []))
            dsd_links.apply_marks(more, marks)
            dsd_links.apply_prior_verdicts(more, defs.get("prior", []))
            notes = dsd_links.by_idk(defs.get("findings", []))       # 전기 대사 차이를 「확인」 으로 판정한 근거도 「볼 것」 시트에 보인다
            for c in more:
                if not c.finding and dsd_links.idk(c.id) in notes:
                    dsd_links.apply_finding(c, notes[dsd_links.idk(c.id)])
            checks, unresolved = checks + more, unresolved + missing
    wdoc = None
    if wtb:                                          # 정산표와 본표 과목의 대사
        from .report import dsd_wtb

        wdoc = dsd_wtb.read_wtb(Path(wtb))             # 읽지 못하면 WtbFormatError(_foot 이 한 줄로 끝낸다)
        more, missing = dsd_wtb.checks(doc, wdoc, {(c.table, c.r) for c in checks if c.kind == "세로합"})
        dsd_links.apply_marks(more, marks)
        notes = dsd_links.by_idk(defs.get("findings", []))
        for c in more:
            if dsd_links.idk(c.id) in notes:
                dsd_links.apply_finding(c, notes[dsd_links.idk(c.id)])
        checks, unresolved = checks + more, unresolved + missing
    dsd_links.evaluate(doc, checks, ydoc, wdoc, odoc)
    from .report import dsd_diff, dsd_verify          # 11단계: 고칠 칸 근거 · 독립 검증 · 차이 설명 후보 · 판정자료

    dsd_verify.apply_fixes(checks, defs.get("findings", []), doc, ydoc, wdoc, odoc)
    review_problems = dsd_verify.apply_review(checks, dsd_verify.load_review(out / dsd_verify.REVIEW), doc, ydoc, wdoc, odoc)
    tabs = dsd_diff.tables(doc, ydoc, wdoc, odoc)
    dsd_diff.explain(doc, checks, tabs, prior_matches)
    mine = [c for c in checks if only(c)] if only else checks      # 몫 하나만 판정할 때(--part) 그 몫의 검증만 판정자료에 싣는다
    (out / dsd_verify.PACK).write_text(dsd_verify.pack(doc, mine, tabs, dsd_book.causes(doc, checks), dsd_book.last_year(doc, tabs, checks), ydoc), encoding="utf-8")
    m = dsd_compare.match(doc, pdoc, fuzzy=True) if pdoc is not None else None
    old_checks = None
    if pdoc is not None:                             # 기존 판에도 같은 연결을 걸어 검증 결과가 달라진 것을 본다(고쳐 달라고 한 곳이 고쳐졌는지)
        old_checks, _, _ = dsd_links.build(pdoc, dict(defs, marks={}), amount_links=amount_links)
        dsd_links.evaluate(pdoc, old_checks)
    from .report import dsd_ai

    gaps = dsd_ai.request(doc, [c for c in checks if c.group != "전기"], new_defs, with_evidence=False)
    same = dsd_ai.consistency(doc)
    if wdoc is not None and (wdoc.stats or {}).get("과목에 잇지 못한 수정 계정"):
        lost_acc = wdoc.stats["과목에 잇지 못한 수정 계정"]
        same.append({"what": "정산표 과목에 잇지 못한 수정 계정", "n": len(lost_acc),
                     "why": f"{', '.join(lost_acc[:8])}. 감사 법인 WTB 의 계정별 시트에서 수정이 있는 계정을 공시 과목에 잇지 못해 그 과목의 회사제시 금액을 구하지 못했다. "
                            "수정 후 금액 대사는 그대로 된다."})
    if wdoc is not None and dsd_wtb.no_adjustments(wdoc):
        same.append({"what": "정산표 수정분개 0건", "n": 0, "why": "정산표의 당기(회사제시)와 당기(최종)이 모든 과목에서 같다. 수정분개를 넣기 전의 정산표라면 "
                     "정산표 대사는 회사 장부와 맞춘 것일 뿐이다. 수정분개를 다 넣은 정산표로 다시 돌린다."})
    for x in mark_notes:
        same.append({"what": "엑셀 확인과 HTML 확인이 다름", "n": 1, "why": x})
    from .report import dsd_text                     # 문장 검토(2026-10-17). 기준사실.json · 문장.json 은 폴더에 있으면 읽는다

    tres = dsd_text.review(src, dsd_text.load_facts(facts or out / "기준사실.json", case), priors[0] if priors else None,
                           text or out / "문장.json", case, stage)
    dsd_text.mark_stale(tres, out / "문장검토.json")    # dsd text 가 AI 에게 준 공시 확인 대상과 지금 대상이 같은지(2026-10-18 B-7)
    vres = None
    if pdoc is not None:                             # 판 비교(dsd diff 와 같은 셈). 새 판에서 띄어쓰기가 빠진 낱말은 문장 검토 오타로 넘긴다(2026-11-04)
        from .report import dsd_versions

        vres = dsd_versions.compare(dsd_versions.read_doc(prev, cache), dsd_versions.read_doc(src, cache))
        dsd_text.version_spacing(tres, vres.changes, Path(prev).name)
    dsd_book.write(book, doc, checks, unresolved, pdoc, ydoc, m,
                   {"unlinked": gaps["unlinked"], "unchecked_totals": gaps["unchecked_totals"], "skipped": new_defs.get("skipped", []),
                    "workpapers": new_defs.get("workpapers", []), "consistency": same, "text": tres, "draft": draft}, wdoc, odoc, old_checks)
    defs_path.write_text(json.dumps(new_defs, ensure_ascii=False, indent=1), encoding="utf-8")
    changed = dsd_compare.changes(doc, pdoc, m) if pdoc is not None else None
    view = None
    versions = None
    if html and pdoc is not None:                    # 판 비교 화면은 dsd diff 와 같은 셈(2026-11-04). 판비교 엑셀 · json 도 같이 쓴다
        from .report import dsd_versions, dsd_versions_book, dsd_versions_view

        vstem = dsd_versions.file_stem(prev, src)
        vbook = dsd_versions_book.write(out / f"{vstem}.xlsx", vres, f"python -m audit dsd foot {src.name} --prev {Path(prev).name} --html")
        dsd_versions.write_json(out / f"{vstem}.json", vres)
        vdata = dsd_versions_view.build(vres)
        versions = {"book": vbook, "line": dsd_versions.line(vres), "data": {k: vdata[k] for k in ("parts", "changes", "summary", "leftovers")}}
    if html:                                         # 판 비교 · 숫자 검증 HTML 보기(2026-10-26). 엑셀이 정본이고 이 화면은 같은 결과를 그린다
        from .report import dsd_links as _dl, dsd_wtb as _dw

        data = dsd_view.build(doc, checks, pdoc, m, old_checks,
                              {"others": {_dl.PRIOR_ID: ydoc, _dw.WTB_ID: wdoc, _dl.PAIR_ID: odoc}, "text": tres,
                               "prior": " · ".join(Path(p).name for p in priors), "wtb": Path(wtb).name if wtb else "",
                               "pair": Path(pair).name if pair else "", "diff": versions["data"] if versions else None,
                               "workpapers": new_defs.get("workpapers", []), "src": src})
        view = dsd_view.write(out, data, src.stem)
        if mask:                                     # 이름 바꾼 판은 따로 쓴다(_치환). 치환 뒤 이름이 남으면 MaskError
            view["masked"] = dsd_view.write(out, data, src.stem, json.loads(Path(mask).read_text(encoding="utf-8")))
    return {"book": book, "doc": doc, "checks": checks, "unresolved": unresolved, "changes": changed, "match": m, "consistency": same, "text": tres,
            "review_problems": review_problems,
            "wtb": wdoc, "view": view, "versions": versions}


SHOW, SHOW_LOST = 40, 10      # foot 화면에 줄마다 적는 수. 넘으면 「외 n건」 과 전체가 있는 엑셀 시트를 적는다(2026-11-04)


def _more(items: list, shown: int, what: str, sheet: str) -> None:
    """화면 목록을 shown 줄에서 끊었으면 남은 수와 전체가 있는 시트를 한 줄로 적는다. 예전에는 알림 없이 끊겨 한 상장사 2026 반기의
    FALSE 56건 가운데 40건만 보이고 나머지가 없는 것처럼 읽혔다."""
    if len(items) > shown:
        print(f"  {what} 외 {len(items) - shown}건(엑셀 「{sheet}」)")


def _foot(a) -> int:
    from .report import dsd_links

    from .report import dsd_view, dsd_wtb

    src = Path(a.dsd)
    out = _out_dir(a)
    src, draft, base = resolve_draft(src, out)          # 원고 엑셀이면 dsd 로 만든다(2026-10-26 DSD 네 기능 C)
    if draft is not None and not a.prev:
        a.prev = str(base)
    part = None
    if a.links:                                       # 연결.json 을 먼저 넣는다(links --apply 와 같다). 풀리지 않는 칸이 있으면 엑셀을 만들지 않는다
        import json

        from .report import dsd_ai

        links = Path(a.links[0])
        if len(a.links) > 1:                          # 몫마다 적은 연결을 하나로(2026-11-09). 후보 번호 장부는 첫 파일 옆 것을 쓴다
            merged = dsd_ai.merge_patches([json.loads(Path(x).read_text(encoding="utf-8")) for x in a.links])
            links = links.with_name("연결.json")
            links.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"연결 {len(a.links)}개를 합침: 연결 {len(merged.get('links', []))} · 표 한 줄 {len(merged.get('tables', []))} · 합계 구조 {len(merged.get('sums', []))} · "
                  f"계산 {len(merged.get('calcs', []))} · 판정 {len(merged.get('findings', []))} · 전기 판정 {len(merged.get('prior', []))} → {links}")
        if a.part:
            pf = next((x for x in (links.with_name(dsd_ai.PARTS_FILE), out / dsd_ai.PARTS_FILE) if x.exists()), None)
            if pf is None:
                print(f"--part {a.part}: {dsd_ai.PARTS_FILE} 이 없습니다. links --parts 로 먼저 나눕니다")
                return 2
            part = (json.loads(pf.read_text(encoding="utf-8")), a.part)
        code = apply_links(src, out, Path(a.defs) if a.defs else out / "dsd_연결정의.json", links, add=a.add, pair=Path(a.pair) if a.pair else None, part=part)
        if code:
            return code
    text = None
    if a.text and len(a.text) > 1:                    # 나눈 몫의 문장.json 을 합친다(text --apply 와 같다)
        import json

        from .report import dsd_text

        text = out / "문장.json"
        merged = dsd_text.merge_ai([json.loads(Path(x).read_text(encoding="utf-8")) for x in a.text])
        text.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"문장.json {len(a.text)}개를 합침: findings {len(merged['findings'])} · disclosures {len(merged['disclosures'])} → {text}")
    elif a.text:
        text = Path(a.text[0])
    try:
        r = foot(src, out, Path(a.prev) if a.prev else None, [Path(p) for p in a.prior] if a.prior else None, Path(a.defs) if a.defs else None, a.amount_links,
                 Path(a.wtb) if a.wtb else None, Path(a.pair) if a.pair else None, Path(a.facts) if a.facts else None,
                 Path(a.case) if a.case else None, text, draft, a.html or bool(a.mask), Path(a.mask) if a.mask else None, a.stage,
                 only=(lambda c: dsd_ai.check_owner(part[0], c) == part[1]) if part else None)
    except dsd_wtb.WtbFormatError as e:               # 정산표 양식을 못 읽으면 역추적 없이 한 줄(2026-10-18 실제 회사 자료 B-1)
        print(f"이 WTB 양식을 읽지 못함: {e}")
        return 2
    except dsd_view.MaskError as e:                   # 치환 뒤에도 실제 이름이 남으면 HTML 을 만들지 않는다(설계 4.3)
        print(f"HTML 을 만들지 않음: {e}")
        return 2
    if r.get("view") and draft is None:              # 검토 화면 서버가 수정판으로 다시 돌릴 때 쓴다(2026-11-04)
        from .report import dsd_serve

        dsd_serve.save_run(out, a, src)
    doc, checks, unresolved = r["doc"], r["checks"], r["unresolved"]
    live = [c for c in checks if not c.excluded and not c.dropped]
    n_drop = sum(1 for c in checks if c.dropped)
    bad = [c for c in live if dsd_links.failed(c)]
    minor = [c for c in live if c.minor]
    ask = [c for c in live if dsd_links.asks(c)]
    if part:                                          # 몫 하나: 그 몫의 FALSE · 확인만 보인다. 다른 몫의 후보는 판정 없이 들어가 FALSE 가 섞인다
        bad = [c for c in bad if dsd_ai.check_owner(part[0], c) == part[1]]
        ask = [c for c in ask if dsd_ai.check_owner(part[0], c) == part[1]]
        print(f"  {part[1]}몫만 보입니다(FALSE · 확인 · 판정자료). 합친 결과는 맡긴 쪽이 foot --links 연결_1.json … 으로 냅니다")
    by = {g: sum(1 for c in live if c.group == g) for g in ("합계", "레퍼", "전기")}
    n_calc = sum(1 for c in live if c.expr)
    lost = [u for u in unresolved if u.get("kind") == "전기"]       # 작년 보고서에서 줄을 찾지 못한 전기 금액. 풀지 못한 연결과 따로 센다
    nowtb = [u for u in unresolved if u.get("kind") == "조서"]      # 정산표에서 과목을 찾지 못한 본표 줄
    unresolved = [u for u in unresolved if u.get("kind") not in ("전기", "조서")]
    line = (f"{src.name}: 검증 {len(live)}(합계 {by['합계']} · 레퍼 {by['레퍼']}" + (f"(계산 {n_calc})" if n_calc else "") + f" · 전기 {by['전기']}) · FALSE {len(bad)} · 확인 {len(ask)} · 단수 차이 {len(minor)} · "
            f"판정으로 뺌 {n_drop} · 제외(X) {len(checks) - len(live) - n_drop} · 풀지 못한 연결 {len(unresolved)}" + (f" · 전기 대사에서 못 찾은 줄 {len(lost)}" if lost else "")
            + (f" · 정산표에서 못 찾은 과목 {len(nowtb)}" if nowtb else ""))
    if r["changes"] is not None:
        line += f" · 바뀐 곳 {sum(r['changes'].values())}"
    kinds = [dsd_links.kind_of(c) for c in live]      # 11단계: 숫자 오류(FALSE) · 표시 오류 · 설명 부족 · 독립 검증
    if kinds.count("표시 오류") or kinds.count("설명 부족"):
        line += f" · 표시 오류 {kinds.count('표시 오류')} · 설명 부족 {kinds.count('설명 부족')}"
    judged = [c for c in checks if not c.excluded and c.ok is False and not c.minor and not dsd_links.no_review(c) and (not c.dropped or c.verified)]
    # 늘 나는 차이 · 근거 확인 숫자 오류는 독립 검증 대상이 아니다(2026-10-22). 검증 뒤 판정으로 뺀 검증도 센다(10-23 한 상장사: 전기 대사 1건이 「걸지 않음」 으로 바뀌어 9/9 로 보였다)
    if any(c.verified for c in judged):
        line += f" · 독립 검증 {sum(1 for c in judged if c.verified)}/{len(judged)}(바꿈 {sum(1 for c in judged if c.verified == '바꿈')})"
    n_sampled = sum(1 for c in live if dsd_links.sampled(c))
    if n_sampled:
        line += f" · 늘 나는 차이 {n_sampled}(독립 검증 대신 회계사 표본)"
    n_engine = sum(1 for c in live if dsd_links.engine_checked(c))
    if n_engine:
        line += f" · 엔진이 근거를 확인한 숫자 오류 {n_engine}(독립 검증 안 함)"
    print(f"{line} → {r['book']}")
    if r.get("view"):
        v = r["view"]
        print(f"  HTML 보기 {v['html'].name}({v['size'] / 1_048_576:.1f}MB) · 자료 {v['json'].name}")
        for w in v["warnings"]:
            print(f"  HTML {w}")
        if v.get("masked"):
            print(f"  이름 치환한 판 {v['masked']['html'].name}")
    if r.get("versions"):
        print(f"  판 비교(HTML 판 비교 화면과 같은 셈) {r['versions']['line']} → {r['versions']['book'].name}")
    if draft is not None:
        print(f"  원고 검사 {len(draft)}건(막음 {sum(1 for x in draft if x['수준'] == '막음')}) · 원고로 만든 dsd {src.name} · 바뀐 곳은 바탕 판과 견줬다")
    for p in r.get("review_problems") or []:
        print(f"  {p}")
    if r.get("wtb") is not None:
        print("  " + dsd_wtb.describe(r["wtb"]))
    for c in bad[:SHOW]:
        t = doc.table(c.table)
        print(f"  FALSE [{c.kind}] {doc.part_of(c.table).key} {dsd_links._labels(t)[c.r]} · {t.header[c.c]}: {c.left:,} ↔ {c.right:,} ({c.label})")
        for h in c.hints[:2]:
            print(f"    후보 [{h['kind']}] {h['text']}")
    _more(bad, SHOW, "FALSE", "볼 것")
    for c in ask[:SHOW]:
        t = doc.table(c.table)
        print(f"  확인 [{c.kind}] {doc.part_of(c.table).key} {dsd_links._labels(t)[c.r]} · {t.header[c.c]}: {c.left:,} ↔ {c.right:,} (차이 {c.left - c.right:,}. 조건: {c.when})")
    _more(ask, SHOW, "확인", "볼 것")
    for u in unresolved[:SHOW]:
        print(f"  풀지 못함 {u['table']}: {u['why']}")
    _more(unresolved, SHOW, "풀지 못함", "풀지 못한 연결")
    for u in lost[:SHOW_LOST]:
        print(f"  전기 대사 {u['table']}: {u['why']}")
    _more(lost, SHOW_LOST, "전기 대사", "풀지 못한 연결")
    for u in nowtb[:SHOW]:
        print(f"  조서 대사 {u['table']}: {u['why']}")
    _more(nowtb, SHOW, "조서 대사", "풀지 못한 연결")
    for x in r.get("consistency") or []:
        print(f"  원문 대조 {x['what']}: {x['why']}")
    from .report import dsd_text

    print("  " + dsd_text.summary(r["text"]))
    for x in (r["text"] or {}).get("invalid", [])[:20]:
        print(f"  문장 받지 않음 {x.get('seg') or x.get('item')}: {x['why']}")
    if r["changes"]:
        for k, n in r["changes"].items():
            if n:
                print(f"  바뀜 {k}: {n}곳")
        for x in r["match"].gone_parts:
            print(f"  없어진 시트: {x}")
    return 1 if bad or unresolved else 0


def _parse(argv: list[str]):
    import argparse

    p = argparse.ArgumentParser(prog="audit")
    register(p.add_subparsers(dest="cmd"))
    return p.parse_args(argv)


def _quick(a) -> int:
    """빠른 검토(2026-11-04): links --text(읽기 자료 · 문장읽기 · 연결_초안) 다음 foot --html. AI 연결 정의가 아직 없으면 연결_초안.json 을
    넣어 엔진 후보를 판정 없이 건다. 이미 있으면(두 번째부터) 그 정의를 그대로 쓴다. 끝에 AI 가 볼 곳(FALSE · 할 일 · 문장)을 한 줄씩 적는다."""
    import json
    import time

    t0 = time.time()
    out = _out_dir(a)
    base = ["dsd", "links", a.dsd, "--text", "--out", str(out)]
    for k in ("facts", "case", "stage"):
        if getattr(a, k):
            base += [f"--{k}", getattr(a, k)]
    if a.prior:
        base += ["--prior", *a.prior]
    code = _links(_parse(base))
    if code not in (0, 1):
        return code
    defs = out / "dsd_연결정의.json"
    has_ai = defs.exists() and bool(json.loads(defs.read_text(encoding="utf-8")).get("links"))
    argv = ["dsd", "foot", a.dsd, "--out", str(out), "--html"] + ([] if has_ai else ["--links", str(out / "연결_초안.json")])
    for k in ("prev", "wtb", "pair", "facts", "case", "stage", "mask"):
        if getattr(a, k):
            argv += [f"--{k}", getattr(a, k)]
    if a.prior:
        argv += ["--prior", *a.prior]
    code = _foot(_parse(argv))
    todo = json.loads((out / "연결_초안.json").read_text(encoding="utf-8")).get("할 일", [])
    print(f"빠른 검토 {time.time() - t0:.0f}초 · AI 연결 정의 {'있음(그대로 씀)' if has_ai else '없음(엔진 후보만)'} · 할 일 {len(todo)}건 · "
          f"다음: AI 는 dsd_판정자료.md 의 FALSE 와 연결_초안.json 할 일만 보고, 문장은 문장읽기.md 를 다른 에이전트가 본다")
    if a.serve:
        from .report import dsd_serve

        dsd_serve.serve(out, a.port)
    return code


def _fix(a) -> int:
    import json

    from .report import dsd_fix

    data = json.loads(Path(a.items).read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else data
    src = Path(a.dsd)
    out = Path(a.out) if a.out else src.with_name(dsd_fix.fixed_name(src))
    r = dsd_fix.apply(src, items, out)
    for x in r["failed"]:
        print(f"  못 고침 {x.get('table') or x.get('seg') or ''} {x.get('old', '')}: {x['why']}")
    for p in r["problems"]:
        print(f"  다시 읽어 보니 {p}")
    if r["path"] is None:
        print(f"{src.name}: 고친 것 없음(못 고침 {len(r['failed'])})")
        return 1 if r["failed"] else 0
    print(f"{src.name}: 고침 {len(r['done'])} · 못 고침 {len(r['failed'])}" + (f" · 서식 잃음 {len(r['lost_format'])}" if r["lost_format"] else "")
          + f" → {r['path']}. 원본은 그대로다. 제출 전에 DART 편집기에서 열어 확인한다")
    return 1 if r["failed"] else 0


def _serve(a) -> int:
    from .report import dsd_serve

    try:
        dsd_serve.serve(Path(a.folder), a.port, not a.no_open)
    except FileNotFoundError as e:
        print(e)
        return 2
    return 0


def _view(a) -> int:
    import json

    from .report import dsd_view

    src = Path(a.src)
    js = src / dsd_view.DATA_FILE if src.is_dir() else src
    if not js.exists():
        print(f"자료가 없습니다: {js} (foot 을 --html 로 먼저 돌린다)")
        return 2
    data = json.loads(js.read_text(encoding="utf-8"))
    out = Path(a.out) if a.out else js.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(data["meta"]["new"]).stem
    try:
        v = dsd_view.write(out, data, stem, json.loads(Path(a.mask).read_text(encoding="utf-8")) if a.mask else None)
    except dsd_view.MaskError as e:
        print(f"HTML 을 만들지 않음: {e}")
        return 2
    print(f"HTML 보기 {v['html']}({v['size'] / 1_048_576:.1f}MB)")
    for w in v["warnings"]:
        print(f"  {w}")
    return 0


def _text(a) -> int:
    out = _out_dir(a)
    src, _, _ = resolve_draft(Path(a.dsd), out)
    return text_run(src, out, Path(a.facts) if a.facts else None, Path(a.case) if a.case else None,
                    Path(a.prior) if a.prior else None, a.apply, a.split, a.stage)


def text_run(src: Path, out: Path, facts: Path | None = None, case: Path | None = None, prior: Path | None = None,
             apply: list | None = None, split: int = 0, stage: str | None = None) -> int:
    """dsd text 의 몸통. links --text 도 이것을 부른다(2026-10-23)."""
    import json
    import shutil

    from .report import dsd_text

    dst = out / "문장.json"
    if apply and len(apply) > 1:                      # 나눈 몫마다 적은 문장.json 을 하나로(2026-10-22)
        merged = dsd_text.merge_ai([json.loads(Path(x).read_text(encoding="utf-8")) for x in apply])
        dst.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"문장.json {len(apply)}개를 합침: findings {len(merged['findings'])} · disclosures {len(merged['disclosures'])} → {dst}")
    elif apply and Path(apply[0]).resolve() != dst.resolve():
        shutil.copyfile(apply[0], dst)
    facts_ = dsd_text.load_facts(facts or out / "기준사실.json", case)
    res = dsd_text.review(src, facts_, prior, dst, case, stage)
    (out / "문장읽기.md").write_text(dsd_text.reading(res), encoding="utf-8")
    for old in out.glob("문장읽기_*.md"):              # 앞서 나눈 몫이 남아 있으면 지운다
        old.unlink()
    parts = dsd_text.reading_parts(res, split) if split > 1 else []
    if len(parts) > 1:
        for i, x in enumerate(parts, 1):
            (out / f"문장읽기_{i}.md").write_text(x, encoding="utf-8")
    (out / "문장검토.json").write_text(json.dumps(dsd_text.to_json(res), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{src.name}: 글 조각 {len(res['segments'])}개 · {dsd_text.summary(res)} → {out / '문장읽기.md'}")
    if len(parts) > 1:
        print(f"  나눈 문장읽기 {len(parts)}개: " + ", ".join(f"문장읽기_{i}.md({x.count(chr(10))}줄)" for i, x in enumerate(parts, 1)))
    elif split > 1:
        print("  글이 짧아 나누지 않음(문장읽기.md 하나)")
    for x in res["engine"][:40]:
        print(f"  [{x['kind']} · {x['rule']}] {x['seg']} {x['where']}: {x['quote'][:60]} → {x['fix']}")
    for x in res["invalid"][:20]:
        print(f"  받지 않음 {x.get('seg') or x.get('item')}: {x['why']}")
    return 1 if res["invalid"] else 0


def _proposal_line(props: list[dict]) -> str:
    from collections import Counter

    by = Counter(x["how"] for x in props)
    return f"엔진 연결 후보 {len(props)}건" + (f"({' · '.join(f'{k} {v}' for k, v in by.most_common())})" if by else "") \
        + " → dsd_연결요청.json 의 proposals, 읽기 자료의 표 아래 「후보」 줄"


def _links(a) -> int:
    import json

    from .report import dsd_ai, dsd_grid, dsd_links

    src, out = Path(a.dsd), _out_dir(a)
    src, _, _ = resolve_draft(src, out)
    defs_path = Path(a.defs) if a.defs else out / "dsd_연결정의.json"
    if a.apply:
        return apply_links(src, out, defs_path, Path(a.apply), add=a.add, carry=Path(a.carry) if a.carry else None)
    defs = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.exists() else {}
    doc = dsd_grid.read_cached(src, dsd_grid.cache_dir())
    checks, base, _ = dsd_links.build(doc, defs)
    dsd_links.evaluate(doc, checks)
    p = out / "dsd_연결요청.json"
    req = dsd_ai.request(doc, checks, base, with_proposals=True, book=dsd_ai.id_book(p))      # 이 폴더에 앞서 낸 후보 번호를 그대로 쓴다
    p.write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "dsd_읽기자료.md").write_text(dsd_ai.reading(doc, base, checks, req["proposals"]), encoding="utf-8")
    d = dsd_ai.draft(doc, req)
    (out / "연결_초안.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{src.name}: {dsd_ai.summary(req)} → {p}")
    if a.parts and a.parts > 1:                      # 숫자 쪽을 주석 범위로 나눈다(2026-11-09). 몫마다 에이전트 하나가 읽고 연결_k.json 을 쓴다
        plan = dsd_ai.plan_parts(doc, a.parts, base, checks, req["proposals"])
        (out / dsd_ai.PARTS_FILE).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        for k in range(1, plan["n"] + 1):
            txt = dsd_ai.part_reading(doc, plan, k, base, checks, req["proposals"])
            (out / f"dsd_읽기자료_{k}.md").write_text(txt, encoding="utf-8")
            pd = dsd_ai.part_draft(plan, k, d)
            (out / f"연결_초안_{k}.json").write_text(json.dumps(pd, ensure_ascii=False, indent=1), encoding="utf-8")
            keys = [x for x, v in plan["notes"].items() if v == k]
            print(f"  몫 {k}: {keys[0] if keys else '-'} ~ {keys[-1] if keys else '-'} · 읽기 자료 {txt.count(chr(10))}줄 · 할 일 {len(pd['할 일'])}건 → dsd_읽기자료_{k}.md · 연결_초안_{k}.json")
    print("  " + _proposal_line(req["proposals"]))
    print(f"  연결_초안.json: 할 일 {len(d['할 일'])}건(후보 없는 표 · 합계 구조 없음 · 잇지 못한 과목) → {out / '연결_초안.json'}")
    for x in req["unlinked"][:40]:
        print(f"  {x['table']} {x['row']} (가리킨 주석 {', '.join(x['notes'])})")
    if a.text:                                       # 문장읽기도 같은 프로세스에서 쓴다(2026-10-23 분석 6.7)
        return text_run(src, out, Path(a.facts) if a.facts else None, Path(a.case) if a.case else None, Path(a.prior[0]) if a.prior else None, None, a.split,
                        getattr(a, "stage", None))
    return 0


def apply_links(src: Path, out: Path, defs_path: Path, patch_path: Path, add: bool = False, carry: Path | None = None, pair: Path | None = None,
                part: tuple | None = None) -> int:
    """links --apply 의 몸통. foot --links 도 이것을 부른다(2026-10-23). 넣지 못하면 1."""
    import json

    from .report import dsd_ai, dsd_grid, dsd_links, dsd_patch

    defs = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.exists() else {}
    cache = dsd_grid.cache_dir()
    doc = dsd_grid.read_cached(src, cache)
    checks, base, _ = dsd_links.build(doc, defs)
    patch = json.loads(Path(patch_path).read_text(encoding="utf-8"))
    # 후보 번호 장부: AI 가 읽은 dsd_연결요청.json 의 번호. 연결.json 옆에 있으면 그것을, 없으면 결과 폴더의 것을 쓴다(2026-11-09)
    book = dsd_ai.id_book(Path(patch_path).with_name("dsd_연결요청.json")) or dsd_ai.id_book(out / "dsd_연결요청.json")
    cdoc = dsd_grid.read_cached(carry, cache) if carry else None
    odoc = dsd_grid.read_cached(pair, cache) if pair else None
    patch, problems, notes = dsd_patch.normalize(cdoc if cdoc is not None else doc, patch, odoc)      # 번호 칸 · 표 한 줄은 그 연결을 적은 판의 번호다
    if problems:
        print(f"연결을 넣지 않았습니다. 고칠 곳 {len(problems)}건")
        for x in problems:
            print(f"  {x}")
        return 1
    for x in notes:
        print(f"  {x}")
    n_prop = {}
    if patch.get("proposals", {}) is not None:        # 후보 판정의 건수(넣은 뒤 화면에 보인다). 판정을 적지 않은 후보는 기본으로 들어간다(2026-10-22)
        got = patch.get("proposals") or {}
        xs = got.get("X") or {}
        n_prop = {"O": sum(len(dsd_ai._ids(x)) for x in got.get("O") or []), "X": sum(len(dsd_ai._ids(x)) for x in (xs if isinstance(xs, dict) else [e.get("id") for e in xs])),
                  "고침": len(got.get("고침") or got.get("edit") or [])}
    if carry:                                         # 다른 판에서 적은 연결을 이 판의 표 번호 · 이름으로 옮긴다
        if "proposals" in patch:                      # 후보 번호는 그 판의 것이라 먼저 연결로 풀어 옮긴다
            patch, bad, _ = dsd_ai.expand_proposals(cdoc, patch, strict=False)
            for x in bad:
                print(f"  후보를 풀지 못함 {x}")
        patch, lost = dsd_ai.carry(cdoc, doc, patch)
        moved = out / "연결_옮김.json"
        moved.write_text(json.dumps(patch, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{Path(carry).name} 의 연결을 옮겼습니다: 연결 {len(patch['links'])} · 합계 구조 {len(patch['sums'])} · 합계 아님 {len(patch['no_sums'])} · 옮기지 못함 {len(lost)} → {moved}")
        for x in lost:
            print(f"  옮기지 못함 {x}")
    new, problems = dsd_ai.apply(doc, base, patch, add=add, book=None if carry else book)
    if problems:
        print(f"연결을 넣지 않았습니다. 고칠 곳 {len(problems)}건")
        for x in problems:
            print(f"  {x}")
        return 1
    defs_path.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    doc = dsd_grid.read_cached(src, cache)            # 단위를 바로잡은 표가 바뀌었을 수 있어 새 사본을 다시 푼다
    checks, _, _ = dsd_links.build(doc, new)
    dsd_links.evaluate(doc, checks)
    ai = [c for c in checks if c.source == "AI" and c.group == "레퍼"]
    n = sum(1 for x in new["links"] if x.get("source") == "AI")
    same = f" · 규칙이나 합계 구조와 같아 뺀 것 {n - len(ai)}건" if n > len(ai) else ""
    print(f"{src.name}: AI 연결 {len(ai)}건을 넣었습니다(맞음 {sum(1 for c in ai if c.ok)} · 단수 차이 {sum(1 for c in ai if c.minor)} · "
          f"확인 {sum(1 for c in ai if dsd_links.asks(c))} · 안 맞음 {sum(1 for c in ai if dsd_links.failed(c))}{same}) → {defs_path}")
    sm = [c for c in checks if c.source == "AI" and c.group == "합계"]
    if new.get("units"):
        print("  단위를 바로잡은 표: " + ", ".join(f"{u['table']} → {u['unit']:,}" for u in new["units"]))
    if new.get("sums") or new.get("no_sums"):
        print(f"  AI 가 정한 합계 구조 {len(new.get('sums', []))}개(검증 칸 {len(sm)} · 맞음 {sum(1 for c in sm if c.ok)} · 단수 차이 {sum(1 for c in sm if c.minor)} · "
              f"안 맞음 {sum(1 for c in sm if dsd_links.failed(c))}) · 합계가 아니라고 한 것 {len(new.get('no_sums', []))}개")
    eng = [c for c in checks if c.group == "합계" and c.source != "AI" and dsd_links.failed(c)]
    if eng:                                          # 엔진이 찾은 구조에서 안 맞는 칸. 구조가 틀렸으면 sums 로 다시 적고, 맞으면 보고서의 차이다
        print(f"  엔진 합계 구조에서 안 맞는 칸 {len(eng)}곳")
        for c in eng[:20]:
            t = doc.table(c.table)
            print(f"    {c.kind} {c.table} {dsd_links._labels(t)[c.r]} · {t.header[c.c]}: {c.left:,} ↔ {c.right:,} ({c.label})")
    for x in dsd_ai.sum_review(doc, base, checks):
        why = "걸린 칸이 전부 안 맞습니다. 구조를 잘못 읽었을 수 있으니 표를 다시 읽으십시오" if x["all"] else f"{x['checks']}칸 가운데 {x['false']}칸이 안 맞습니다"
        print(f"  합계 안 맞음 {x['table']} {x['kind']} {x['ai']}: {why}" + (f" (엔진이 찾았던 구조: {x['engine']})" if x["engine"] else ""))
    req = dsd_ai.request(doc, checks, new, with_proposals=True, book=None if carry else book)      # 넣은 뒤의 요청 자료: 아직 이어지지 않은 과목과 금액 대조 참고가 줄어든다
    if part:                                          # 몫 하나: 잇지 못한 과목 · 합계 구조 없음 · 금액이 같은 칸 짝도 그 몫 것만
        req = dsd_ai.part_request(doc, part[0], part[1], req)
    (out / "dsd_연결요청.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "dsd_읽기자료.md").write_text(dsd_ai.part_reading(doc, part[0], part[1], new, checks, req["proposals"]) if part
                                       else dsd_ai.reading(doc, new, checks, req["proposals"]), encoding="utf-8")
    if n_prop:
        vids = {x["id"] for x in new["links"] if x.get("via")}
        via = [c for c in ai if c.id in vids or c.id.rsplit("|", 1)[0] in vids]
        print(f"  엔진 후보 {len(req['proposals'])}건: 판정 없이 넣음 {sum(1 for x in req['proposals'] if x.get('mark') == '기본')} · O {n_prop['O']} · X {n_prop['X']} · 고침 {n_prop['고침']}"
              + (f" (후보로 넣은 연결 가운데 안 맞음 {sum(1 for c in via if dsd_links.failed(c))})" if via else ""))
    else:
        print("  " + _proposal_line(req["proposals"]) + '. 연결.json 의 "proposals": null 이라 후보는 넣지 않았습니다')
    print(f"  {dsd_ai.summary(req)} · 금액이 같은데 아직 연결이 없는 칸 짝 {len(req['amount_evidence'])}건 → dsd_연결요청.json")
    for x in dsd_ai.review(doc, [c for c in checks if dsd_ai.check_owner(part[0], c) == part[1]] if part else checks):
        print(f"  {'단수 차이' if x['minor'] else ('확인' if x['when'] else '안 맞음')} {x['left']}: {x['left_value']:,} ↔ {x['right']} {x['right_value']:,} (차이 {x['diff']:,})")
        for y in ([] if x["minor"] else x["same_amount_cells"]):
            print(f"    같은 주석에서 그 금액과 같은 칸: {y['table']} {y['row']} · {y['col']}")
    return 0



def is_draft(p: Path) -> bool:
    return Path(p).suffix.lower() in (".xlsx", ".xlsm")


def resolve_draft(src: Path, out: Path) -> tuple[Path, list | None, Path | None]:
    """원고 엑셀이면 dsd 로 만들어 그 경로를 준다. (dsd 경로, 원고 검사 | None, 바탕 판 경로 | None). 원고가 아니면 그대로."""
    import json

    if not is_draft(src):
        return src, None, None
    from .report import dsd_build, dsd_draft_book

    d = out / "_원고판"
    d.mkdir(parents=True, exist_ok=True)
    res = dsd_build.build(src, d / f"{src.stem}.dsd")
    r = dsd_draft_book.read(src)
    if r.base == "dsd":
        base = dsd_build.zip_dsd(d / f"바탕_{src.stem}.dsd", r.contents, r.meta)
    else:
        base = d / f"바탕_{src.stem}.xml"
        base.write_bytes(r.contents)
    (out / "원고검사.json").write_text(json.dumps(res["issues"], ensure_ascii=False, indent=1), encoding="utf-8")
    return Path(res["path"]), res["issues"], base


def _sheet(a) -> int:
    import zipfile
    import xml.etree.ElementTree as ET
    import xml.parsers.expat

    from .report import dsd_draft, dsd_draft_book

    src = Path(a.dsd)
    out = Path(a.out) if a.out else src.resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    try:
        d = dsd_draft.read(src)
    except (zipfile.BadZipFile, ET.ParseError, xml.parsers.expat.ExpatError, ValueError, FileNotFoundError) as e:
        print(f"읽지 못함: {type(e).__name__} {e}")
        return 2
    if a.roll:
        dsd_draft.roll(d)
    cmd = f"python -m audit dsd sheet {src.name}" + (" --roll" if a.roll else "")
    book = dsd_draft_book.write(out / f"원고_{src.stem}.xlsx", d, cmd)
    n_line = sum(len(s.lines) for s in d.sheets)
    n_tab = sum(1 for s in d.sheets for ln in s.lines if ln.kind in ("표", "글 표"))
    rolled = f" · 롤포워드 표 {len(d.info.get('rolled_tables') or [])}" if a.roll else ""
    print(f"{src.name}: 시트 {len(d.sheets)}개 · 줄 {n_line} · 표 {n_tab}{rolled} → {book}")
    for x in d.notes[:30]:
        print(f"  {x}")
    return 0


def _build(a) -> int:
    import json

    from .report import dsd_build

    src = Path(a.xlsx)
    if not src.exists():
        print(f"파일이 없습니다: {src}")
        return 2
    try:
        res = dsd_build.build(src, Path(a.out) if a.out else None)
    except ValueError as e:
        print(f"만들지 못함: {e}")
        return 2
    path = Path(res["path"])
    (path.parent / f"원고검사_{src.stem}.json").write_text(json.dumps(res["issues"], ensure_ascii=False, indent=1), encoding="utf-8")
    block = [x for x in res["issues"] if x["수준"] == "막음"]
    same = " · 바탕과 바이트까지 같음" if res.get("same_bytes") else ""
    print(f"{src.name} → {path.name}({res['mode']}): 고친 요소 {res['changed']} · 더한 것 {res['added']} · 뺀 것 {res['removed']}{same} · "
          f"원고 검사 {len(res['issues'])}(막음 {len(block)})")
    for x in res["issues"][:40]:
        print(f"  [{x['수준']} · {x['분류']}] {x['시트']} {x['칸']} {x['내용']}".rstrip())
    return 1 if block else 0


def _diff(a) -> int:
    import zipfile
    import xml.etree.ElementTree as ET

    from .report import dsd_grid, dsd_versions, dsd_versions_book

    old, new = Path(a.old), Path(a.new)
    for p in (old, new):
        if not p.exists():
            print(f"파일이 없습니다: {p}")
            return 2
    out = Path(a.out) if a.out else new.resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    try:
        old_d, _, _ = resolve_draft(old, out)
        new_d, _, _ = resolve_draft(new, out)
        res = dsd_versions.compare_files(old_d, new_d, dsd_grid.cache_dir())
    except (zipfile.BadZipFile, ET.ParseError, ValueError) as e:
        print(f"판을 읽지 못함: {type(e).__name__} {e}")
        return 2
    stem = dsd_versions.file_stem(old, new)
    cmd = f"python -m audit dsd diff {old.name} {new.name}"
    book = dsd_versions_book.write(out / f"{stem}.xlsx", res, cmd)
    dsd_versions.write_json(out / f"{stem}.json", res)
    print(dsd_versions.line(res))
    print(f"→ {book}")
    if a.html or a.mask:                              # 판 비교 HTML(2026-11-03). 엑셀과 같은 셈을 화면으로 그린다
        import json

        from .report import dsd_versions_view, dsd_view

        data = dsd_versions_view.build(res)
        try:
            views = [dsd_versions_view.write(out, data, stem)]
            if a.mask:
                views.append(dsd_versions_view.write(out, data, stem, json.loads(Path(a.mask).read_text(encoding="utf-8"))))
        except dsd_view.MaskError as e:
            print(f"HTML 을 만들지 않음: {e}")
            return 2
        for v in views:
            print(f"→ {v['html']}({v['size'] / 1_048_576:.1f}MB)")
            for w in v["warnings"]:
                print(f"  HTML {w}")
    return 0


def _convert(a) -> int:
    import json
    from xml.parsers.expat import ExpatError

    from .report import dart_fetch as F, dsd_convert as C

    src = a.src.strip()
    try:
        if re.fullmatch(r"\d{14}", src) or (src.lower().endswith(".pdf") and Path(src).exists()):
            rcept = src if re.fullmatch(r"\d{14}", src) else F.from_pdf(Path(src))[0]
            base = Path(a.out) if a.out else (Path.cwd() if re.fullmatch(r"\d{14}", src) else Path(src).resolve().parent)
            xp = Path(F.fetch_one(rcept, base)["main"])
        elif src.lower().endswith(".xml") and Path(src).exists():
            xp = Path(src)
        else:
            print(f"바꿀 것을 알지 못함: {src}. 접수번호(14자리), DART 에서 받은 PDF, 공시 원문 xml 중 하나를 주십시오")
            return 2
    except F.FetchError as e:                         # 오류 글에는 인증키가 없다
        print(f"원문을 받지 못함: {e}")
        return 2
    out = Path(a.out) if a.out else xp.resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    raw = xp.read_bytes()
    from .report import dsd_breaks

    vp = Path(a.view) if a.view else dsd_breaks.view_for(xp)
    view = vp.read_text(encoding="utf-8", errors="replace") if vp and vp.exists() else None
    try:
        r = C.convert(raw, bare=a.bare, view=view)
    except (ValueError, ExpatError) as e:
        print(f"바꾸지 못함: {e}")
        return 2
    year = r.period_end[:4]
    stem = C.file_stem(r.company, year, C.FORMS[r.form])
    path = C.write(out / f"{stem}_변환{'_뼈대없음' if a.bare else ''}.dsd", r, C.sha(raw))
    same = C.same_body(raw, r.contents)
    print(f"{xp.name} → {path.name}: {C.FORMS[r.form]}({r.form}) · {r.company} · 결산 {r.period_end or '?'} · "
          f"삽입 위치 {r.counts.get('삽입 위치', 0)}(넣은 LIBRARY {r.counts.get('넣은 LIBRARY', 0)}) · ENG 뺌 {r.counts.get('ENG 뺌', 0)} · "
          f"본문 원문과 {'같음' if same else '다름'} · 줄바꿈 "
          + (f"{r.counts.get('줄바꿈 되살림', 0)}곳 · 빈칸 {r.counts.get('빈칸 되살림', 0)}곳 되살림(공시 화면 {vp.name})" if r.breaks == "화면" else "없음(공시 화면 없음)"))
    for x in r.notes:
        print(f"  {x}")
    print("  편집기에서: 재무제표마다 [재무제표 > 재무제표 검사] 를 돌린 뒤 파일형식 검사를 한다(공시 원문에는 그 검사 기록이 없다)")
    code = 0 if same else 1
    if a.roll:
        from .report import dsd_build, dsd_draft, dsd_draft_book

        d = dsd_draft.read(path)
        dsd_draft.roll(d)
        nxt = str(int(year) + 1) if year.isdigit() else "다음"
        book = dsd_draft_book.write(out / f"원고_{C.file_stem(r.company, nxt, C.FORMS[r.form])}_초안.xlsx", d,
                                    f"python -m audit dsd convert {xp.name} --roll")
        res = dsd_build.build(book, out / f"{C.file_stem(r.company, nxt, C.FORMS[r.form])}_초안.dsd")
        (out / f"원고검사_{book.stem}.json").write_text(json.dumps(res["issues"], ensure_ascii=False, indent=1), encoding="utf-8")
        rolled = d.info.get("rolled_tables") or []
        print(f"다음 기수 초안 → {Path(res['path']).name}: 롤포워드 표 {len(rolled)} · 고친 요소 {res['changed']} · 원고 {book.name}")
        issues = [f"[{x['수준']} · {x['분류']}] {x['시트']} {x['칸']} {x['내용']}".rstrip() for x in res["issues"]]
        guide = out / f"초안안내_{book.stem}.txt"          # 화면은 앞 몇 줄만, 전체는 파일로(2026-11-06 다른 회사 시험 E6: 말없이 잘렸다)
        guide.write_text("\n".join(["[롤포워드 안내]", *d.notes, "", "[원고 검사]", *issues]) + "\n", encoding="utf-8")
        for x in d.notes[:30]:
            print(f"  {x}")
        if len(d.notes) > 30:
            print(f"  … 안내 외 {len(d.notes) - 30}건은 {guide.name}")
        for x in issues[:20]:
            print(f"  {x}")
        if len(issues) > 20:
            print(f"  … 원고 검사 외 {len(issues) - 20}건은 {guide.name}")
        print("  그대로 남은 것: 감사인의 감사보고서 · 외부감사 실시내용 · 문단 속 날짜와 금액은 작년 글이다. 원고 엑셀에서 고쳐 dsd build 로 다시 만든다")
    return code


def _fetch(a) -> int:
    from .report import dart_fetch as F

    src = a.src.strip()
    try:
        if re.fullmatch(r"\d{14}", src):
            rcept, how, base = src, "접수번호", Path(a.out) if a.out else Path.cwd()
        elif src.lower().endswith(".pdf") and Path(src).exists():
            rcept, how = F.from_pdf(Path(src))
            base = Path(a.out) if a.out else Path(src).resolve().parent
        else:
            print(f"받을 것을 알지 못함: {src}. 접수번호(14자리)나 DART 에서 받은 PDF 를 주십시오")
            return 2
        r = F.fetch(rcept, base, with_prior=not a.no_prior)
    except F.FetchError as e:                         # 오류 글에는 인증키가 없다
        print(f"원문을 받지 못함: {e}")
        return 2

    def line(x, what):
        kinds = " · ".join(["본문"] + list(x["split"])) if x["split"] else x["main"].name
        return f"{what} {x['rcept_no']} {x.get('report_nm') or x['name']} ({kinds}) → {x['main'].parent}"

    print(line(r["main"], f"원문 받음({how}):"))
    for x in r["priors"]:
        print("  " + line(x, "작년 비교:"))
    m, ps = r["main"], r["priors"]
    kinds = list(m["split"]) or [""]
    print("foot 명령:")
    for kind in kinds:
        me = m["split"].get(kind, m["main"]) if kind else m["main"]
        prior = [str(p["split"].get(kind, p["main"]) if kind else p["main"]) for p in ps if not kind or kind in p["split"]]
        other = [m["split"][k] for k in m["split"] if k != kind]
        cmd = f'python -m audit dsd foot "{me}"' + ("" if not prior else " --prior " + " ".join(f'"{p}"' for p in prior)) \
              + (f' --pair "{other[0]}"' if other else "") + f' --out "{base / ("푸팅결과_" + kind if kind else "푸팅결과")}"'
        print("  " + cmd)
    return 0
