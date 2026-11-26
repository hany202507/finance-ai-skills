"""표준조서 절차 시트에 엔진 계산을 채운다(2026-11-25). 설계 문서 7절.

결정 D1(11-25): 회계사가 편철 · 서명하는 4000 조서는 표준조서 하나다. 엔진 4000 조서가 받은자료에서 읽어 만들던
거래처별 명세 · 금액 단위 표본 · 조회 연결 · 연령 구간을 표준조서 절차 시트의 표로 옮긴다. 숫자는 엔진 4000 조서와 같은 함수
(audit.workpapers.lead · substantive)가 받은자료에서 읽은 것만 쓴다. AI 는 이 표에 숫자를 넣지 않는다.

  LAYOUT                                     feed 이름 → 표 위 표본 설계 줄 이름 · 표 아래 줄 이름(자리를 미리 잡는다)
  collect(d, code)                           {절차 시트 id: feed}. 정의(std_workpapers.yaml)의 sheets[].feed 를 돌린다
  feed = {"rows": [{열: 값}], "own": [엔진이 채운 열], "key": 줄 키 열, "params": {줄 이름: 값}, "after": {줄 이름: {열: 값}},
          "source": 받은자료, "notes": [글], "groups": {「기타 (n곳)」: [거래처]}} 또는 {"error": 까닭}

감사 폴더가 아니거나(감사건.json 없음) 받은자료가 없으면 error 를 돌려준다. 표준조서는 그 표를 비워 두고 까닭을 한 줄 적는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import stdmode

KEY = "거래처"
PARTY_LEGEND = ("t/m: S = 기말 후 입금이 잔액 이상, C = 3320 회신 일치(엔진이 대사한 것만). "
                "비고의 신규 = 전기 분개장에 없던 거래처, 표본 = .02 채권 조회 표본")
PARTY_LEGEND_PUBLIC = ("t/m: S = 기말 후 입금이 잔액 이상(조회 회신 대사 표시 C 는 감사인이 적습니다). "
                       "비고의 신규 = 전기 분개장에 없던 거래처, 표본 = .02 채권 조회 표본")
RISKS = ("기본", "낮음", "보통", "높음")      # definitions/sampling.yaml risk_levels


def std_inputs(d: Path) -> dict:
    """공개판이 _색인/감사건.json 「std」 칸에 적어 둔 감사인 입력 {performance, risk}. 감사 건에는 이 칸이 없어 빈 dict."""
    p = Path(d) / "_색인" / "감사건.json"
    try:
        v = json.loads(p.read_text(encoding="utf-8")).get("std") if p.is_file() else None
    except (OSError, ValueError):
        v = None
    return v if isinstance(v, dict) else {}

# 표 위 줄(표본 설계)과 표 아래 줄. 받은자료가 없어도 자리를 잡아 두어 다시 씌울 때 칸이 밀리지 않게 한다
LAYOUT = {
    "ar_parties": {"params": [], "after": []},
    "ar_confirm": {"params": ["모집단(거래처별 기말 잔액, 0 이하 뺌)", "거래처 수", "수행중요성(허용왜곡표시)", "예상 왜곡표시",
                              "위험 수준", "신뢰계수", "표본 간격", "표본 점 수"],
                   "after": ["표본에서 찾은 왜곡표시(차이 합계)", "투영한 왜곡표시: 과대계상", "투영한 왜곡표시: 과소계상"]},
    "ar_alt": {"params": [], "after": []},
    "ar_allowance": {"params": [], "after": ["회사 계상 충당금(시산표)", "연령분석표 합계 열", "시산표 채권 잔액(충당금 차감 전)",
                                             "완전성 차이(구간 합 − 시산표 채권 잔액)"]},
}


class _Cache:
    """한 조서를 만드는 동안 엔진 문맥과 매출채권 모집단 · 표본을 한 번만 읽는다."""

    def __init__(self, d: Path):
        self.d = Path(d)
        self._ctx = None
        self._pop = None
        self._sm = False
        self._conf = False

    def ctx(self) -> dict:
        if self._ctx is None:
            from .workpapers import lead

            if not (self.d / "_색인" / "감사건.json").is_file():
                raise LookupError("감사 폴더가 아닙니다(_색인/감사건.json 없음)")
            ctx = lead.context(self.d)
            std = std_inputs(self.d)            # 공개판 --pm · --risk. 2700A 수행중요성 · 명령 --risk 가 있으면 그쪽이 앞선다
            pm = std.get("performance")
            mat = ctx["mat"]
            if not (mat.get("performance") and not mat.get("candidate")):          # 감사인이 2700A 에 적은 값이 없다
                if isinstance(pm, (int, float)) and not isinstance(pm, bool) and pm > 0:
                    ctx["mat"] = {**mat, "performance": pm, "candidate": False, "basis": "감사건.json std.performance(--pm)"}
                elif stdmode.STANDALONE and mat.get("performance"):
                    # 공개판은 엔진 중요성 후보로 표본을 뽑지 않는다. 수행중요성은 감사인이 --pm 으로 준다(표본sampling 과 같은 선)
                    ctx["mat"] = {**mat, "performance": None, "basis": "엔진 후보는 쓰지 않음(--pm 없음)"}
            if not ctx.get("risk") and std.get("risk") in RISKS:
                ctx["risk"] = std["risk"]
            elif not ctx.get("risk") and stdmode.STANDALONE:
                # 공개판에는 2302 영역 위험 · 2700B · 분석 결과가 없다. 감사인 값이 없으면 sampling.yaml 기본값(lead.sample_risk 마지막 단계)
                from .workpapers import sampling

                ctx["risk"] = sampling.settings()["default_risk"]
            self._ctx = ctx
        return self._ctx

    def ar_pop(self) -> dict:
        if self._pop is None:
            from .workpapers import lead

            self._pop = lead.ar_population(self.ctx())
        return self._pop

    def ar_sample(self) -> dict | None:
        if self._sm is False:
            from .workpapers import lead

            self._sm = lead.ar_sample(self.ctx())
        return self._sm

    def confirms(self) -> dict | None:
        """3320 조회 대장의 매출채권 줄. {거래처: 줄}. 3320 을 아직 만들지 않았으면 None."""
        if self._conf is False and stdmode.STANDALONE:
            self._conf = None                  # 공개판에는 조회 대장이 없다. 감사 폴더에 남은 조회.json 도 읽지 않는다
        if self._conf is False:
            from .workpapers import common

            data = common.idx(self.d, "조회.json")
            self._conf = None if data is None else {e["target"]: e for e in data.get("confirmations", []) if e.get("kind") == "매출채권"}
        return self._conf


def _picked(c: _Cache) -> set:
    sm = c.ar_sample()
    return {r["key"] for r in sm["s"]["selected"]} if sm else set()


def ar_parties(c: _Cache) -> dict:
    """4000C .01 거래처별 잔액 명세. 엔진 4000C 「거래처별」 시트와 같은 줄(금액 상위 + 표본 · 신규 · 기말 후 취소, 나머지는 「기타」)."""
    from .workpapers import skeleton

    pop = c.ar_pop()
    if not pop["rows"]:
        return {"error": "연령분석표 · 계정명세서(외상매출금)에서 거래처별 잔액을 찾지 못했습니다. "
                         + (f"자료 폴더에 넣고 `{stdmode.cmd('refresh')}` 를 돌리면 채웁니다" if stdmode.STANDALONE
                            else "받은자료 명세서 폴더에 넣으면 다시 씌울 때 채웁니다")}
    conf = c.confirms() or {}
    picked = _picked(c)
    top = skeleton.top_n(c.ctx()["defs"])
    shown, rest = skeleton.top_rows(pop["rows"], top, lambda r: r["amount"],
                                    keep=lambda r: r["party"] in picked or bool(r["new"]) or bool(r["cancelled"]))
    rows = []
    for r in shown:
        notes = (["신규"] if r["new"] else []) + (["표본"] if r["party"] in picked else []) + \
                (["기말 후 같은 거래처 매출 취소"] if r["cancelled"] else [])
        ticks = (["S"] if r["collected"] and r["collected"] >= r["amount"] else []) + \
                (["C"] if str((conf.get(r["party"]) or {}).get("status") or "") == "회신 일치" else [])
        rows.append({KEY: r["party"], "당기말": r["amount"], "비고": " · ".join(notes) or None, "t/m": " ".join(ticks) or None})
    if rest:
        rows.append({KEY: skeleton.others_label(rest), "당기말": sum(r["amount"] for r in rest), "비고": "금액 상위가 아닌 거래처 합계",
                     "t/m": None})
    for x in pop.get("excluded") or []:
        rows.append({KEY: x["party"], "당기말": x["amount"], "비고": "거래처 아닌 줄(재분류 · 상계 대상인지 확인)", "t/m": None})
    notes = [("신규 판정: 전기 분개장 기준." if pop["new_known"] else "전기 분개장이 없어 신규 거래처를 판정하지 못했습니다.")
             + " 기말 후 입금 · 취소: " + (", ".join(pop["post_files"]) or "기말 후 분개장 없음"),
             PARTY_LEGEND_PUBLIC if stdmode.STANDALONE else PARTY_LEGEND]
    if rest:
        notes.append("거래처 " + skeleton.top_note(len(pop["rows"]), len(shown), len(rest), top, "표본 · 신규 · 기말 후 취소 거래처", pop["source"]))
    groups = {skeleton.others_label(rest): [r["party"] for r in rest]} if rest else {}   # std roll 이 작년 금액을 「기타」 에 더할 때 쓴다
    return {"rows": rows, "own": [KEY, "당기말", "비고", "t/m"], "key": KEY, "params": {}, "after": {}, "groups": groups,
            "source": pop["source"], "notes": notes}


def _status(e: dict | None, conf: dict | None) -> str | None:
    if conf is None:
        return None if stdmode.STANDALONE else "3320 만들기 전"
    if e is None:
        return "3320 대상 아님"
    return f"3320 #{e['no']} {e.get('status') or ''}".strip()


def ar_confirm(c: _Cache) -> dict:
    """4000C .02 채권 조회. 금액 단위 표본(엔진 4000C 「표본」 시트와 같은 시드 · 위험 수준)과 3320 조회 대장의 발송일 · 회신 잔액."""
    sm = c.ar_sample()
    if sm is None:
        why = "거래처별 잔액" if not c.ar_pop()["rows"] else ("수행중요성(--pm)" if stdmode.STANDALONE else "수행중요성(2700B)")
        return {"error": f"{why} 이 없어 금액 단위 표본을 뽑지 못했습니다"}
    s, conf = sm["s"], c.confirms()
    rows = []
    for r in s["selected"]:
        e = (conf or {}).get(r["key"])
        rows.append({KEY: r["key"], "장부 잔액": r["amount"], "발송일": (e or {}).get("sent_at"),
                     "회신 잔액": (e or {}).get("reply_amount"), "비고": _status(e, conf)})
    params = {"모집단(거래처별 기말 잔액, 0 이하 뺌)": s["total"], "거래처 수": s["count"], "수행중요성(허용왜곡표시)": s["tolerable"],
              "예상 왜곡표시": s["expected"], "위험 수준": s["risk"], "신뢰계수": s["factor"], "표본 간격": round(s["interval"]),
              "표본 점 수": s["size"]}
    if stdmode.STANDALONE:
        notes = ["금액 단위 표본입니다. 시드가 고정이라 다시 돌려도 같은 표본이고, 간격 이상인 고액 항목은 반드시 걸립니다. "
                 "발송일 · 회신 잔액은 감사인이 적습니다(공개판에는 조회 대장이 없습니다)",
                 "투영: 간격 이상 항목은 차이 그대로, 미만은 차이 ÷ 장부 잔액 × 표본 간격(감사기준서 530 문단 14). "
                 "증분 허용을 더한 상한 평가는 감사인이 합니다"]
    else:
        notes = ["표본은 엔진 4000C 조서 「표본」 시트와 같은 시드 · 위험 수준으로 뽑았습니다. 간격 이상인 고액 항목은 반드시 걸립니다. "
                 "발송일 · 회신 잔액은 3320 조회 대장(_색인/조회.json)에서 옵니다. 회신을 받으면 3320 을 다시 만든 뒤 std refresh",
                 "투영: 간격 이상 항목은 차이 그대로, 미만은 차이 ÷ 장부 잔액 × 표본 간격(감사기준서 530 문단 14). "
                 "증분 허용을 더한 상한 평가는 엔진 4000C 조서(`wp make 4000C`) 「표본」 시트(계산 근거)에 있습니다"]
    if s["size"] != len(rows):
        notes.append(f"표본 점 {s['size']}개가 거래처 {len(rows)}곳에 걸렸습니다(간격보다 큰 거래처는 점 여러 개)")
    if s.get("excluded"):
        notes.append(f"금액이 0 이하라 모집단에서 뺀 거래처 {len(s['excluded'])}곳")
    return {"rows": rows, "own": [KEY, "장부 잔액", "발송일", "회신 잔액", "비고"], "key": KEY, "params": params, "after": {},
            "source": c.ar_pop()["source"], "notes": notes}


def ar_alt(c: _Cache) -> dict:
    """4000C .03 대체적 절차. 표본 가운데 회신이 없는(회신 일치 · 회신 차이가 아닌) 거래처와 기말 후 입금."""
    sm = c.ar_sample()
    if sm is None:
        return {"error": "금액 단위 표본이 없어 대체적 절차 대상을 정하지 못했습니다"}
    conf = c.confirms()
    coll = {r["party"]: r["collected"] for r in c.ar_pop()["rows"]}
    rows = []
    for r in sm["s"]["selected"]:
        e = (conf or {}).get(r["key"])
        if e and e.get("status") in ("회신 일치", "회신 차이"):
            continue
        rows.append({KEY: r["key"], "장부 잔액": r["amount"], "기말 후 입금": coll.get(r["key"], 0), "비고": _status(e, conf)})
    pop = c.ar_pop()
    who = ("대상: .02 표본 거래처 전부(공개판은 조회 회신을 읽지 않습니다. 회신을 받은 거래처는 해당없음으로 적습니다)."
           if stdmode.STANDALONE else "대상: .02 표본 가운데 3320 회신이 없는 거래처.")
    notes = [who + " 기말 후 입금: " + (", ".join(pop["post_files"]) or "기말 후 분개장 없음")]
    return {"rows": rows, "own": [KEY, "장부 잔액", "기말 후 입금", "비고"], "key": KEY, "params": {}, "after": {},
            "source": pop["source"], "notes": notes}


def ar_allowance(c: _Cache) -> dict:
    """4000C .04 손실충당금. 연령분석표의 연령 구간별 합계(엔진 4000C 「손실충당금 검토」 시트와 같은 함수)."""
    from .workpapers import substantive

    ag = substantive.aging(c.ctx())
    if ag is None:
        return {"error": "연령 구간 열이 있는 연령분석표를 받으면 다시 씌울 때 채웁니다"}
    rows = [{"연령 구간": name, "잔액": amt} for name, amt in ag["buckets"]]
    after = {"회사 계상 충당금(시산표)": {"충당금": ag["allowance"]},
             "연령분석표 합계 열": {"잔액": ag["total"]},
             "시산표 채권 잔액(충당금 차감 전)": {"잔액": ag["receivable"]}}
    notes = ["설정률과 구간별 회사 충당금은 회계사가 적습니다. 엔진은 율을 정하지 않습니다. 회사 계상 충당금은 시산표 "
             + (" · ".join(ag["allowance_names"]) if ag["allowance_names"] else "충당금 계정 없음(0)")]
    return {"rows": rows, "own": ["연령 구간", "잔액"], "key": "연령 구간", "params": {}, "after": after,
            "source": ag["source"], "notes": notes}


FEEDS = {"ar_parties": ar_parties, "ar_confirm": ar_confirm, "ar_alt": ar_alt, "ar_allowance": ar_allowance}


def collect(d: Path | None, code: str, sheets: list[dict]) -> dict:
    """{절차 시트 id: feed}. feed 가 없는 시트는 싣지 않는다. 엔진이 읽다 실패해도 멈추지 않고 그 시트에 까닭을 남긴다."""
    want = {s["id"]: s["feed"] for s in sheets if s.get("feed")}
    if not want:
        return {}
    if d is None:
        return {sid: {"error": "감사 폴더 없이 만든 조서입니다"} for sid in want}
    from . import params
    from .workpapers import common

    c = _Cache(Path(d))
    out = {}
    with params.use(d), common.reading():
        for sid, name in want.items():
            fn = FEEDS.get(name)
            if fn is None:
                out[sid] = {"error": f"정의에 없는 feed 입니다: {name}"}
                continue
            try:
                out[sid] = fn(c)
            except LookupError as e:
                out[sid] = {"error": str(e)}
            except (ValueError, KeyError, OSError) as e:
                out[sid] = {"error": f"엔진이 받은자료를 읽지 못했습니다({type(e).__name__}: {e})"}
    return out
