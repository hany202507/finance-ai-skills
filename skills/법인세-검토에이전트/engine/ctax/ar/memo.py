"""AR 메모 검사 · 넣기와 회계사 결론 이어받기(CONTRACT.md 14.1).

AI(법인세-AR 스킬)가 쓴 메모 JSON

    {"items": [{"issue": 3, "judgment": "조정 필요", "why": "...",
                "law": [{"ref": "법인세법 제25조 제4항", "grade": "★★★", "url": "https://www.law.go.kr/..."}],
                "questions": ["...주십시오"]}]}

검사(하나라도 어기면 아무것도 넣지 않는다)
  1. items 의 issue 가 AR.json 이슈 번호 전부와 같다(빠짐 · 없는 번호 · 겹침 금지)
  2. judgment 는 조정 필요 · 조정 없음 · 판단 필요, why 는 비지 않는다
  3. 글 속 금액(쉼표 있는 숫자, 쉼표 없이 다섯 자리 이상인 숫자)은 AR.json(조정.json 이 있으면 그것도)에 있는 값이다(△ · 음수는 절대값으로 본다).
     법정 금액은 조문 글 꼴(3만원, 1천200만원)로 쓰면 검사하지 않는다. 법령 공포번호(법률 제20613호) · MST · 여덟 자리
     날짜(20241231)는 금액이 아니다
  4. law 는 한 줄 이상, 줄마다 ref 와 grade(★★★ · ★★☆ · ★☆☆ · ☆). ★★★ 는 url 이 있어야 하고 url 은 law.go.kr 주소다
  5. 줄표(—) · 물음표 금지, 질문은 「…주십시오」 로 끝난다

넣을 때 엔진이 by「AI」 · confirmed false · at 을 붙인다. 회계사 결론은 AR_이슈.xlsx 노란 칸을 다음 실행이 읽는다.
"""
from __future__ import annotations

import re
from datetime import datetime

JUDGMENTS = ("조정 필요", "조정 없음", "판단 필요")
GRADES = ("★★★", "★★☆", "★☆☆", "☆")
URL_RE = re.compile(r"^https?://(www\.)?law\.go\.kr/")
COMMA_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d,])")
PLAIN_RE = re.compile(r"(?<![\d.,])\d{5,}(?![\d,])")
# 금액이 아닌 번호. 법령 공포번호(법률 제20613호 · 대통령령 제35347호, 부칙 <제20613호, 20241231>), 법령일련번호(MST 279739),
# 부칙 머리의 공포일(20241231 꼴 여덟 자리 날짜). 이 자리는 지우고 금액을 찾는다.
NOT_AMOUNT_RE = re.compile(r"제\s?\d{1,6}\s?호|(?:MST|법령일련번호)\s?:?\s?\d+"
                           r"|(?<![\d.,])(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?![\d,])")
SKIP_KEYS = ("memo", "conclusion")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def tokens(text: str) -> list[tuple[str, int]]:
    """검사할 금액 토큰 (원문, 절대값). 법령 번호 · 날짜는 금액으로 보지 않는다(NOT_AMOUNT_RE)."""
    text = NOT_AMOUNT_RE.sub(" ", text)
    out = [(m.group(0), int(m.group(0).replace(",", ""))) for m in COMMA_RE.finditer(text)]
    out += [(m.group(0), int(m.group(0))) for m in PLAIN_RE.finditer(text)]
    return out


def numbers_of(obj, out: set | None = None) -> set:
    """AR.json 안의 숫자(절대값). 숫자 값과 글 속 금액을 모두 모은다. 메모 · 결론은 뺀다."""
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(abs(int(round(obj))))
    elif isinstance(obj, str):
        out.update(v for _raw, v in tokens(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k not in SKIP_KEYS:
                numbers_of(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            numbers_of(v, out)
    return out


def _texts(item: dict) -> list[tuple[str, str]]:
    """(어디, 글) 목록. why · questions · law ref."""
    out = [("why", str(item.get("why") or ""))]
    out += [(f"질문 {j}", str(q)) for j, q in enumerate(item.get("questions") or [], 1)]
    out += [(f"근거 {j}", str(x.get("ref") or "")) for j, x in enumerate(item.get("law") or [], 1) if isinstance(x, dict)]
    return out


def check_item(item: dict, nums: set) -> list[str]:
    """메모 한 건의 문제 목록(이슈 번호 대조는 validate 가 한다)."""
    w = f"이슈 {item.get('issue')}"
    probs = []
    if item.get("judgment") not in JUDGMENTS:
        probs.append(f"{w}: judgment 는 {' · '.join(JUDGMENTS)} 가운데서 고릅니다: {item.get('judgment')}")
    if not str(item.get("why") or "").strip():
        probs.append(f"{w}: why(까닭)가 비었습니다")
    qs = item.get("questions") or []
    if not isinstance(qs, list):
        probs.append(f"{w}: questions 는 목록이어야 합니다")
        qs = []
    law = item.get("law")
    if not isinstance(law, list) or not law:
        probs.append(f"{w}: law(근거 조문)가 한 줄 이상 있어야 합니다. 조문을 찾지 못했으면 grade ☆ 로 그 사실을 적습니다")
        law = []
    for j, x in enumerate(law, 1):
        if not isinstance(x, dict) or not str(x.get("ref") or "").strip():
            probs.append(f"{w} 근거 {j}: ref 가 비었습니다")
            continue
        if x.get("grade") not in GRADES:
            probs.append(f"{w} 근거 {j}: grade 는 {' · '.join(GRADES)} 가운데 하나여야 합니다: {x.get('grade')}")
        url = str(x.get("url") or "")
        if x.get("grade") == "★★★" and not url:
            probs.append(f"{w} 근거 {j}: ★★★ 는 원문을 확인한 도구의 url 이 있어야 합니다")
        if url and not URL_RE.match(url):
            probs.append(f"{w} 근거 {j}: url 은 korean-law 도구가 준 law.go.kr 주소 그대로 씁니다: {url}")
    for where, text in _texts({**item, "questions": qs, "law": law}):
        if "—" in text:
            probs.append(f"{w} {where}: 줄표(—)를 쓰지 않습니다")
        if "?" in text or "？" in text:
            probs.append(f"{w} {where}: 물음표를 쓰지 않습니다")
        for raw, v in tokens(text):
            if v not in nums:
                probs.append(f"{w} {where}: AR.json 에 없는 금액 {raw}")
    for j, q in enumerate(qs, 1):
        if not str(q).rstrip(" .").endswith("주십시오"):
            probs.append(f"{w} 질문 {j}: 「…주십시오」 로 끝냅니다")
    return probs


def validate(memo: dict, ar: dict, allowed: set | None = None) -> list[str]:
    """allowed: AR.json 밖에서 글에 써도 되는 금액(조서 계산 조정.json 의 숫자)."""
    if not isinstance(memo, dict) or not isinstance(memo.get("items"), list):
        return ['메모는 {"items": [{"issue", "judgment", "why", "law", "questions"}]} 꼴이어야 합니다']
    probs = []
    have = [i["no"] for i in ar.get("issues", [])]
    got = [it.get("issue") if isinstance(it, dict) else None for it in memo["items"]]
    dup = sorted({n for n in got if got.count(n) > 1 and n is not None})
    miss = sorted(set(have) - set(got))
    extra = [n for n in got if n not in have]
    if miss or extra or dup:
        probs.append(f"items 는 AR.json 이슈 전부여야 합니다. 빠진 이슈 {miss}, AR.json 에 없는 이슈 {extra}, 겹친 이슈 {dup}")
    nums = numbers_of(ar) | (allowed or set())
    for it in memo["items"]:
        if not isinstance(it, dict):
            probs.append("items 의 줄은 사전이어야 합니다")
            continue
        probs += check_item(it, nums)
    return probs


def stored(item: dict, at: str | None = None) -> dict:
    """AR.json issues[].memo 꼴."""
    return {"judgment": item["judgment"], "why": str(item["why"]).strip(),
            "law": [{k: x[k] for k in ("ref", "grade", "url") if x.get(k)} for x in item.get("law") or []],
            "questions": [str(q).strip() for q in item.get("questions") or []],
            "by": "AI", "confirmed": False, "at": at or now()}


def apply(memo: dict, ar: dict, at: str | None = None) -> int:
    """검사를 통과한 메모를 넣는다. 넣은 건수."""
    by_no = {i["no"]: i for i in ar.get("issues", [])}
    at = at or now()
    for it in memo["items"]:
        by_no[it["issue"]]["memo"] = stored(it, at)
    return len(memo["items"])


# ---------------------------------------------------------------- 이어받기


def match(issues: list[dict], *, key=None, rule=None, kind=None, title=None) -> dict | None:
    """같은 이슈 찾기. key 와 rule 이 같은 이슈 → rule · 종류가 같은 이슈 하나 → key 가 같은 이슈 하나 → 종류 · 제목이 같은 이슈 하나."""
    def one(c):
        return c[0] if len(c) == 1 else None
    if key and rule:
        hit = one([i for i in issues if i.get("key") == key and i.get("rule") == rule])
        if hit:
            return hit
    if rule and kind:
        hit = one([i for i in issues if i.get("rule") == rule and i.get("kind") == kind])
        if hit:
            return hit
    if key:
        hit = one([i for i in issues if i.get("key") == key])
        if hit:
            return hit
    if kind and title:
        return one([i for i in issues if i.get("kind") == kind and i.get("title") == title])
    return None


# 금액이 바뀐 메모를 뺄 때 알리는 글. 이 엔진을 감싸는 스킬(법인세-AR)에서도 맞는 말로 둔다(10-20)
MEMO_DROPPED = "이슈 {no} AI 메모는 금액이 바뀌어 뺐습니다. 메모를 다시 써서 메모 명령으로 넣으십시오"


def carry(ar: dict, old: dict | None, rows: list[dict] | None, at: str | None = None,
          allowed: set | None = None) -> list[str]:
    """앞 실행의 회계사 결론과 AI 메모를 새 AR 에 잇는다. 알릴 글 목록.

    rows: AR_이슈.xlsx 「이슈 목록」 에서 읽은 줄 [{key, rule, kind, title, text}](text 가 빈 줄 포함).
    rows 가 None 이면(엑셀이 없음) 앞 AR.json 의 결론을 그대로 잇는다. 엑셀이 있으면 엑셀이 정본이다.
    AI 메모는 앞 AR.json 에서 잇되, 메모 속 금액이 새 AR.json 에 없으면 버리고 알린다.
    allowed: AR.json 밖에서 메모 글에 써도 되는 금액(조서 계산 조정.json 의 숫자). `--memo` 검사(validate)와 같은 허용 숫자 집합을
    써야 넣을 때 통과한 메모가 다음 실행에서 버려지지 않는다(10-20).
    """
    at = at or now()
    notes = []
    issues = ar.get("issues", [])
    old_issues = (old or {}).get("issues", [])

    def old_of(new: dict) -> dict | None:
        return match(old_issues, key=new.get("key"), rule=new.get("rule"), kind=new.get("kind"), title=new.get("title"))

    got = 0
    if rows is not None:
        lost = 0
        for r in rows:
            text = str(r.get("text") or "").strip()
            if not text:
                continue
            new = match(issues, key=r.get("key"), rule=r.get("rule"), kind=r.get("kind"), title=r.get("title"))
            if new is None:
                lost += 1
                notes.append(f"회계사 결론을 이을 이슈가 없습니다: {r.get('title') or r.get('key')} 「{text[:40]}」")
                continue
            prev = (old_of(new) or {}).get("conclusion") or {}
            new["conclusion"] = {"text": text, "by": "회계사",
                                 "at": prev.get("at") if prev.get("text") == text and prev.get("at") else at}
            got += 1
    else:
        for new in issues:
            prev = (old_of(new) or {}).get("conclusion")
            if prev:
                new["conclusion"] = prev
                got += 1
    if got:
        notes.insert(0, f"회계사 결론 {got}건을 이어받았습니다")

    nums = numbers_of(ar) | (allowed or set())
    kept = dropped = 0
    for new in issues:
        o = old_of(new)
        m = (o or {}).get("memo")
        if not m:
            continue
        probs = [p for p in check_item({"issue": new["no"], **m}, nums) if "AR.json 에 없는 금액" in p]
        if probs:
            dropped += 1
            notes.append(MEMO_DROPPED.format(no=new["no"]))
            continue
        new["memo"] = m
        kept += 1
    if kept:
        notes.append(f"AI 메모 {kept}건을 이어받았습니다")
    return notes
