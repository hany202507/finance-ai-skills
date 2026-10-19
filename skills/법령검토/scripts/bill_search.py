"""국회 의안정보시스템에서 결론 조문을 고치는 계류·통과 법안을 찾아 조사 파일로 쓴다.

  python scripts/bill_search.py --대상 "소득세법:제89조" --대상 "상법:제341조,제341조의2" --출력 국회.json
  python scripts/bill_search.py --대상 "소득세법:제89조" --키워드 "1세대 1주택" --출력 국회.json

법령마다 의안명 검색을 한 번 하고(22대 국회), 계류 중이거나 가결됐지만 공포 전인 법안만 남긴 뒤
의안 요약(제안이유·주요내용)에 결론 조문이나 --키워드 가 나오는 것만 항목으로 적는다.
의안 요약은 주된 조문만 「안 제N조 등」으로 적어서 조문 번호만으로는 빠질 수 있다. 결론 조문 제목의 낱말을 --키워드 로 함께 준다. 예정 시행일은 의안 원문 PDF 부칙에만 있어 비워 둔다.
결과 파일은 freshness_check.py --조사 로 넘긴다. 모양은 references/최신화점검.md.

종료코드: 0 완료, 1 조회 실패(파일에 상태 "실패"와 까닭을 쓴다), 2 입력 오류.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html as htmllib
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://likms.assembly.go.kr/bill"
UA = "Mozilla/5.0 (finance-ai-skills bill_search)"


def strip(s):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def jo_pattern(jo):
    """「제89조」는 잡고 「제89조의2」는 잡지 않는다. 「제341조의2」는 그대로 잡는다."""
    m = re.fullmatch(r"제?(\d+)조?(?:의(\d+))?조?", re.sub(r"\s+", "", jo))  # 「제27의2조」 표기도 받는다
    if not m:
        raise ValueError(f"조문 표기를 읽지 못했다: {jo}")
    if m.group(2):
        return re.compile(rf"제\s*{m.group(1)}\s*조\s*의\s*{m.group(2)}(?!\d)")
    return re.compile(rf"제\s*{m.group(1)}\s*조(?!\s*의\s*\d)")


def summary_text(page_html):
    """의안 요약 화면에서 「제안이유 및 주요내용」 본문만 뽑는다.

    본문은 <pre class="print_pre"> 안에 있다. 화면의 <script> 하나가 닫히지 않아 스크립트를 지우는 방식은 쓰지 않는다.
    """
    m = re.search(r'<pre\b[^>]*class="[^"]*print_pre[^"]*"[^>]*>(.*?)</pre>', page_html, re.S)
    if not m:
        return ""
    text = strip(m.group(1))
    return re.sub(r"^제안이유\s*및\s*주요내용\s*", "", text)


def parse_targets(values):
    out = []
    for v in values:
        law, _, jos = v.partition(":")
        law = law.strip()
        if not law or not jos.strip():
            raise ValueError(f"「법령:조문,조문」 꼴이 아니다: {v}")
        out.append((law, [j.strip() for j in jos.split(",") if j.strip()]))
    return out


def parse_rows(page_html):
    """검색 결과 HTML 조각에서 (총건수, 행 목록)을 뽑는다."""
    m = re.search(r'id="pager_count_text"[^>]*value="(\d+)"', page_html)
    total = int(m.group(1)) if m else None
    rows = []
    for tr in re.findall(r"<tr\b.*?</tr>", page_html, re.S):
        no = re.search(r'data-bill_no="(\d+)"', tr)
        if not no:
            continue
        bid = re.search(r'data-bill-id="([A-Z]+_[^"]+)"', tr)
        name = re.search(r"<a\b[^>]*data-bill_no[^>]*>(.*?)</a>", tr, re.S)
        tds = [strip(x) for x in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S)]
        rows.append({
            "의안번호": no.group(1),
            "billId": bid.group(1) if bid else "",
            # 의안명 앞에 붙은 상태 아이콘(<i class="ico_kye">계류의안</i>)은 뺀다
            "의안명": strip(re.sub(r"<i\b.*?</i>", "", name.group(1), flags=re.S)) if name else "",
            "제안자구분": tds[2] if len(tds) > 2 else "",
            "제안일": tds[3] if len(tds) > 3 else "",
            "의결일": tds[4] if len(tds) > 4 else "",
            "의결결과": tds[5] if len(tds) > 5 else "",
            "진행": tds[7] if len(tds) > 7 else "",
            "계류표시": "ico_kye" in tr,
        })
    return total, rows


def stage(row):
    """계류 / 국회통과 / None(공포·폐기·철회 등 개정안이 아닌 것)."""
    if not row["의결일"] or row["계류표시"]:
        return "계류"
    if "가결" in row["의결결과"] and "공포" not in row["진행"]:
        return "국회통과"
    return None


def is_bill_of(row, law):
    return re.match(rf"^{re.escape(law)}\s*(일부|전부)개정법률안", row["의안명"]) is not None


class Site:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("User-Agent", UA)]
        page = self.get(f"{BASE}/bi/bill/sch/detailedSchPage.do?detailedTab=billDtl")
        m = re.search(r'name="_csrf"\s+content="([^"]+)"', page)
        if not m:
            raise RuntimeError("검색 화면에서 _csrf 토큰을 찾지 못했다")
        self.token = m.group(1)

    def get(self, url):
        with self.op.open(url, timeout=60) as r:
            return r.read().decode("utf-8", "replace")

    def search(self, law, age, page, rows=100):
        data = urllib.parse.urlencode({"_csrf": self.token, "reqPageId": "billSrch", "detailedTab": "billDtl",
                                       "billNm": law, "ageFrom": age, "ageTo": age, "rows": rows, "page": page}).encode()
        req = urllib.request.Request(f"{BASE}/bi/bill/sch/findSchPaging.do", data=data, headers={
            "X-CSRF-TOKEN": self.token, "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        with self.op.open(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")

    def summary(self, bill_id):
        return summary_text(self.get(f"{BASE}/bi/popup/billSummary.do?billId={urllib.parse.quote(bill_id)}"))


def pick(text, pats, keywords, need_kw=False):
    """요약에 걸린 조문·키워드를 돌려준다. 고르지 않으면 None.

    need_kw 이면 키워드가 하나라도 나와야 고른다. 정의 조항처럼 넓은 조문에 관계없는 법안이 걸리는 것을 막는다.
    """
    hit = [j for j, p in pats if p.search(text)]
    kw = [k for k in keywords if k in text]
    if need_kw and not kw:
        return None
    if not hit and not kw:
        return None
    return hit, kw


def find(site, law, jos, age, keywords=(), workers=4, need_kw=False):
    rows, page, total = [], 1, None
    while True:
        t, got = parse_rows(site.search(law, age, page))
        total = t if t is not None else total
        rows += got
        if not got or (total is not None and len(rows) >= total) or page >= 10:
            break
        page += 1
    if total is not None and len(rows) < total:
        raise RuntimeError(f"{law} 검색 결과 {total}건 중 {len(rows)}건만 읽었다")
    cands = [r for r in rows if is_bill_of(r, law) and stage(r)]
    pats = [(j, jo_pattern(j)) for j in jos]

    def look(r):
        text = site.summary(r["billId"]) if r["billId"] else ""
        got = pick(text, pats, keywords, need_kw)
        if not got:
            return None
        hit, kw = got
        sent = next((s for s in re.split(r"(?<=[.다])\s", text)
                     if any(p.search(s) for _, p in pats) or any(k in s for k in kw)), "")
        return {"법령": law, "구분": stage(r), "번호": f"의안번호 {r['의안번호']}", "공포일": "", "시행일": "",
                "대상조문": hit, "걸린 말": hit + kw, "요지": sent[:200], "확인": "본문",
                "URL": f"{BASE}/bi/billDetailPage.do?billId={urllib.parse.quote(r['billId'])}",
                "제안일": r["제안일"], "제안자구분": r["제안자구분"]}

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        items = [x for x in ex.map(look, cands) if x]
    return items, {"법령": law, "검색 결과": len(rows), "계류·통과": len(cands), "결론 조문·키워드 언급": len(items)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="국회 계류·통과 법안 중 결론 조문을 고치는 것 찾기")
    ap.add_argument("--대상", required=True, action="append", help="법령:조문,조문 (예: 소득세법:제89조)")
    ap.add_argument("--키워드", action="append", default=[], help="요약에 이 말이 있어도 고른다 (예: 1세대 1주택)")
    ap.add_argument("--키워드필수", action="store_true", help="키워드가 요약에 나온 법안만 남긴다(정의 조항처럼 넓은 조문)")
    ap.add_argument("--대수", default="22")
    ap.add_argument("--오늘", default=None)
    ap.add_argument("--출력", required=True)
    if hasattr(sys.stdout, "reconfigure"):  # --help 한글이 깨지지 않게 parse_args 전에 바꾼다
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    a = ap.parse_args(argv)
    if a.키워드필수 and not a.키워드:
        print("입력 오류: --키워드필수 에는 --키워드 가 하나 이상 있어야 한다", file=sys.stderr)
        return 2
    try:
        targets = parse_targets(a.대상)
        for _, jos in targets:
            for j in jos:
                jo_pattern(j)
    except ValueError as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 2
    today = a.오늘 or (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%d")
    out = {"조사처": "국회", "상태": "완료", "까닭": "",
           "검색": {"출처": f"국회 의안정보시스템({a.대수}대)", "기간": ["", today], "검색어": [t[0] for t in targets]},
           "메모": [], "항목": []}
    code = 0
    try:
        site = Site()
        for law, jos in targets:
            items, memo = find(site, law, jos, a.대수, a.키워드, need_kw=a.키워드필수)
            out["항목"] += items
            out["메모"].append(memo)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 「확인 불가」로 남겨야 한다
        out.update(상태="실패", 까닭=f"의안정보시스템 조회 실패: {type(e).__name__}: {str(e)[:200]}")
        code = 1
    Path(a.출력).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("상태", "까닭", "메모")}, ensure_ascii=False))
    for it in out["항목"]:
        print(f"- {it['법령']} {it['번호']} {it['구분']} {','.join(it['걸린 말'])} ({it['제안자구분']}, {it['제안일']})")
    return code


if __name__ == "__main__":
    sys.exit(main())
