# -*- coding: utf-8 -*-
"""검토 결과를 PDF 로 낸다.

엑셀은 작업용이다. 열어서 고칠 수 있으니 확정본으로 남기기에 안 맞는다.
**회계사가 서명 전에 보고 조서에 철하고 고객에게 보내는 것은 PDF 다.**

실제 신고는 PDF 로 하지 않는다. 홈택스 전자신고나 더존 전송이다.
여기서 만드는 PDF 는 제출용이 아니라 **검토본과 보관본**이다.

HTML 로 그린 뒤 브라우저로 인쇄한다. Edge 나 Chrome 이면 된다.
둘 다 없으면 HTML 만 남기고 알린다. 그 HTML 을 열어 Ctrl+P 로 뽑으면 같다.
"""
import os
import pathlib
import re
import sys
import glob
import time
import shutil
import subprocess
import tempfile

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser():
    if os.environ.get("VAT_NO_BROWSER"):    # 테스트·CI 에서 인쇄를 건너뛴다. HTML 만 남는다
        return None
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome", "chromium", "google-chrome", "google-chrome-stable",
                 "chromium-browser", "microsoft-edge", "microsoft-edge-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None


def html_to_pdf(html_path, pdf_path):
    """브라우저로 인쇄한다. 못 하면 False 를 돌려주고 HTML 은 남는다.

    까다로운 곳이 셋이라 그대로 두면 조용히 틀린 PDF 가 나온다.

    ① 한글이 든 경로를 URL 에 그대로 넣으면 Edge 가 ERR_FILE_NOT_FOUND 를 인쇄한다
    ② 인쇄 실행기가 먼저 빠져나가는 일이 있다. 그때 원본이나 임시본을 지우면
       뒤늦게 로드하는 쪽이 파일을 못 찾는다
    ③ 그러면 PDF 는 멀쩡히 생긴다. 크기만 보면 통과하고 내용은 오류 화면이다

    그래서 따로 복사해 인쇄하고, **PDF 가 다 써질 때까지 기다린 뒤** 치우고,
    마지막에 오류 화면인지 본다."""
    exe = find_browser()
    if not exe:
        return False
    out = os.path.abspath(pdf_path)
    if os.path.exists(out):
        os.remove(out)
    prof = tempfile.mkdtemp(prefix="pdfprof-")
    # 프로필 폴더 안에 두지 않는다. Edge 가 자기 프로필을 정리하면서 같이 지운다
    stage = tempfile.mkdtemp(prefix="pdfpage-")
    try:
        page = os.path.join(stage, "page.html")
        shutil.copyfile(html_path, page)
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
               f"--user-data-dir={prof}", "--no-pdf-header-footer",
               "--virtual-time-budget=8000",
               f"--print-to-pdf={out}", pathlib.Path(page).as_uri()]
        subprocess.run(cmd, capture_output=True, timeout=180)
        if not _settled(out):
            return False
    except Exception:
        return False
    finally:
        shutil.rmtree(prof, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)
    return not _is_browser_error(out)


def _settled(path, wait=30.0):
    """파일이 생기고 크기가 더 안 늘 때까지 기다린다. 실행기가 먼저 빠져나간다."""
    size, still = -1, 0
    for _ in range(int(wait / 0.4)):
        now = os.path.getsize(path) if os.path.exists(path) else -1
        if now > 1000 and now == size:
            still += 1
            if still >= 2:
                return True
        else:
            still = 0
        size = now
        time.sleep(0.4)
    return os.path.exists(path) and os.path.getsize(path) > 1000


ERRS = ("ERR_FILE_NOT_FOUND", "ERR_ACCESS_DENIED", "파일을 찾을 수 없음")


def _is_browser_error(pdf_path):
    """브라우저가 오류 화면을 인쇄한 것을 성공으로 보지 않는다.

    PyMuPDF 가 없으면 확인하지 않는다. 그 경우 크기만 보고 통과시킨다."""
    try:
        import fitz
    except ImportError:
        return False
    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count != 1:
                return False
            head = doc[0].get_text()[:400]
    except Exception:
        return False
    return any(e in head for e in ERRS)
def won(v):
    if v in ("", None):
        return ""
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def page(title, body):
    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")


def sign_block(role="검토·서명"):
    return f"""<div class="sign"><table><tr>
 <td style="width:22mm">작성</td><td><div class="line"></div></td>
 <td style="width:22mm">{esc(role)}</td><td><div class="line"></div></td>
 <td style="width:22mm">일자</td><td><div class="line"></div></td>
</tr></table></div>"""


def foot(tool):
    return (f'<div class="foot">{esc(tool)} 가 만들었습니다. '
            f'제출용이 아니라 검토·보관용입니다. 실제 신고는 홈택스 전자신고나 더존 전송으로 합니다.'
            f'<br>본지 란 구조와 계산식은 부가가치세법 시행규칙 별지 제21호서식(2026. 3. 20. 개정)을 따릅니다.</div>')


# ── 본지 ─────────────────────────────────
def build_return_html(company, period, mine, staff, findings, filed_label):
    """검토본. 1쪽은 별지 제21호서식 그대로 내가 만든 본지, 뒤에 대조와 검토 결과.

    회계사가 조서에 철하는 것이라 1쪽이 서식 모양이어야 한다.
    직원 것과 나란히 놓은 표와 검출 목록은 그 뒤에 붙인다."""
    import form21
    d_m = {r[0]: r for r in mine}
    rev = ['<div class="rev"><h2>직원 작성본과 대조</h2>',
           f'<div class="meta"><b>{form21.esc(company)}</b> · {form21.esc(period)}</div>']

    if staff:
        tr = []
        for no, nm, sup, tax in mine:
            s_ = staff.get(no)
            if not s_:
                continue
            gap = (s_[3] or 0) - (tax or 0)
            if not gap and (sup or 0) == (s_[2] or 0):
                continue
            tr.append(
                f"<tr><td class='c'>{form21.esc(no)}</td><td class='l'>{form21.esc(nm)}</td>"
                f"<td class='n'>{form21.won(sup)}</td><td class='n'>{form21.won(tax)}</td>"
                f"<td class='n'>{form21.won(s_[2])}</td><td class='n'>{form21.won(s_[3])}</td>"
                f"<td class='n neg'>{format(gap, '+,') if gap else '0'}</td></tr>")
        rev.append(
            "<table><tr><th style='width:7%'>란</th><th style='width:27%'>명칭</th>"
            "<th>내 본지 금액</th><th>내 본지 세액</th>"
            "<th>직원 금액</th><th>직원 세액</th><th style='width:12%'>세액 차이</th></tr>"
            + "".join(tr) + "</table>")
        sp = staff.get("(30)", ("", "", 0, 0))[3] or 0
        mp = d_m["(30)"][3] or 0
        rev.append(f'<div class="note">차감·가감하여 납부할 세액이 '
                   f'<b>{form21.won(sp)}원</b> 대 <b>{form21.won(mp)}원</b>, '
                   f'차이 <b class="stop">{format(sp - mp, "+,")}원</b> 입니다.</div>')

    stop = [f for f in findings if f["등급"] == "정지"]
    ask = [f for f in findings if f["등급"] == "확인"]
    rev.append("<h2>검토 결과</h2>")
    if not findings:
        rev.append('<div class="note">검사가 전부 맞습니다.</div>')
    else:
        rev.append(f'<div class="note">정지 <b class="stop">{len(stop)}</b>건 · '
                   f'확인 <b>{len(ask)}</b>건. '
                   f'<b class="stop">정지가 남아 있으면 신고하지 않습니다.</b></div>')
        rows = []
        for f in findings:
            g = (f'<span class="stop">{form21.esc(f["등급"])}</span>'
                 if f["등급"] == "정지" else form21.esc(f["등급"]))
            rows.append(f"<tr><td class='c'>{form21.esc(f['검사'])}</td>"
                        f"<td class='c'>{g}</td><td class='l'>{form21.esc(f['무엇'])}</td>"
                        f"<td class='l'>{form21.esc(f['대상'])}</td>"
                        f"<td class='l'>{form21.esc(f['근거'])}</td></tr>")
        rev.append("<table><tr><th style='width:7%'>검사</th><th style='width:7%'>등급</th>"
                   "<th style='width:24%'>무엇이 걸렸나</th><th>대상</th>"
                   "<th style='width:26%'>근거</th></tr>" + "".join(rows) + "</table>")

    rev.append('<div class="sign"><table><tr>'
               '<td style="width:22mm">작성</td><td><div class="line"></div></td>'
               '<td style="width:22mm">검토·서명</td><td><div class="line"></div></td>'
               '<td style="width:22mm">일자</td><td><div class="line"></div></td>'
               '</tr></table></div>')
    rev.append('<div class="foot">부가세신고서검토 스킬이 만들었습니다. '
               '제출용이 아니라 검토·보관용입니다. '
               '실제 신고는 홈택스 전자신고나 더존 전송으로 합니다.</div></div>')

    return form21.build(company, period, mine, extra="".join(rev))


# ── 부속명세 ─────────────────────────
def build_attach_html(company, period, att, ver, ctx):
    """부속명세 8종. 공식 서식 칸 구성을 그대로 옮긴 것은 attach_forms.py 다."""
    import attach_forms
    return attach_forms.build(company, period, att, ver, ctx)


# ── 직원 작성본 신고서 (검토 대상) ────────────────────
def build_staff_return_html(company, period, rows):
    """직원이 더존에서 뽑아 넘긴 신고서. 별지 제21호서식 그대로 그린다."""
    import form21
    return form21.build(company, period, rows)


# ── 신고서 PDF 읽기 ──────────────────────────
RAN = re.compile(r"^\(\d{1,2}(?:-1)?\)$|^[ㅩ-㉿㋐-㋾㈀-㈞]$")
# 2023. 3. 20. 개정 서식(더존 출력물)은 (10-1)·(20-1) 이 있고 그 뒤 번호가 하나씩 밀린다.
# 2026. 3. 20. 개정 서식 번호로 옮긴다. 1쪽 신고내용 표에만 적용한다
OLD2NEW = {"(10-1)": "(11)", "(11)": "(12)", "(12)": "(13)", "(13)": "(14)", "(14)": "(15)",
           "(15)": "(16)", "(16)": "(17)", "(17)": "(18)", "(18)": "(19)", "(19)": "(20)",
           "(20)": "(21)", "(20-1)": "(22)", "(21)": "(23)", "(22)": "(24)", "(23)": "(25)",
           "(24)": "(26)", "(25)": "(27)", "(26)": "(29)", "(27)": "(30)"}


def _joined(txt):
    """더존 출력물은 「구 분 금 액」처럼 낱글자로 쪼개진다. 붙여서 찾는다."""
    return "".join(txt)


def _lines(words):
    """낱말을 줄로 묶는다. y 를 반올림해 묶으면 같은 줄의 낱말이 경계에서 갈라져
    란 번호와 금액이 다른 줄로 떨어진다. 낱말 높이의 절반 안이면 같은 줄로 본다."""
    out = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        h = max(w[3] - w[1], 1.0)
        if out and abs(w[1] - out[-1][0]) <= h * 0.5:
            out[-1][1].append(w)
        else:
            out.append([w[1], [w]])
    return [ws for _, ws in out]


def _mid_of(txt, mid, target):
    """target 문자열이 걸친 낱말들의 가로 가운데. 낱글자로 쪼개진 머리글에서 열 위치를 잡는다."""
    joined, spans = "", []
    for t, m in zip(txt, mid):
        spans.append((len(joined), len(joined) + len(t), m))
        joined += t
    i = joined.find(target)
    if i < 0:
        return None
    ms = [m for a, b, m in spans if a < i + len(target) and b > i]
    return sum(ms) / len(ms) if ms else None
NUM = re.compile(r"^-?[\d,]+$")


def read_return_pdf(path):
    """신고서 PDF 에서 란별 금액과 세액을 읽는다.

    글자 좌표로 읽는다. 줄 안의 숫자를 순서대로 집으면 금액이 빈 란에서 어긋난다.
    ① 신고내용 표의 머리글 「금액」과 「세액」의 가로 가운데를 잡고,
    숫자가 어느 쪽에 가까운지로 열을 정한다. 더존 출력물은 머리글이 「금 액」처럼
    낱글자로 쪼개져 있어 붙여서 찾는다.

    서식이 2023. 3. 20. 개정판이면 란 번호를 2026 서식으로 옮긴다(OLD2NEW).
    신고내용 표는 1쪽에만 있어 란은 1쪽에서만 읽는다. 「과세표준명세」 아래는
    업종코드·수입금액이라 란으로 읽지 않는다. 면세수입금액 줄은 어느 쪽이든 읽는다.

    못 읽은 란은 0 으로 채우지 않고 빼고 돌려준다. 회계사가 읽은 값을 확인해야 한다."""
    try:
        import fitz
    except ImportError:
        return None, "PyMuPDF 가 없습니다. pip install pymupdf"

    out, cx, old_form = {}, None, False
    with fitz.open(path) as doc:
        for pno, pg in enumerate(doc):
            if pno == 0:
                m = re.search(r"개정\s*(\d{4})", pg.get_text())
                old_form = bool(m) and int(m.group(1)) < 2026
            stop = False
            for ws in _lines(pg.get_text("words")):
                ws.sort(key=lambda w: w[0])
                txt = [w[4] for w in ws]
                mid = [(w[0] + w[2]) / 2 for w in ws]
                joined = _joined(txt)
                # ① 신고내용 표의 머리글. 구분·금액·세율·세액이 한 줄에 있다
                if cx is None and all(k in joined for k in ("구분", "금액", "세율", "세액")):
                    gm, sm = _mid_of(txt, mid, "금액"), _mid_of(txt, mid, "세액")
                    if gm is not None and sm is not None:
                        cx = (gm, sm)
                    continue
                if cx is None:
                    continue
                if "면세사업" in joined and "수입금액" in joined:
                    nums = [int(x.replace(",", "")) for x in txt if NUM.match(x)]
                    if nums:
                        out["면세"] = ("면세", "면세수입금액", nums[-1], 0)
                    continue
                # 신고내용 표는 1쪽에만 있다. 2쪽의 (41)·(42) 같은 명세 번호를 란으로 읽지 않는다
                if pno > 0:
                    continue
                if "과세표준명세" in joined:
                    stop = True
                if stop:
                    continue
                ran = next((x for x in txt if RAN.match(x)), None)
                if not ran:
                    continue
                if old_form and pno == 0:
                    ran = OLD2NEW.get(ran, ran)
                sup = tax = None
                for w, m, x in zip(ws, mid, txt):
                    if not NUM.match(x) or x == ran:
                        continue
                    v = int(x.replace(",", ""))
                    if abs(m - cx[1]) < abs(m - cx[0]):
                        tax = v
                    else:
                        sup = v
                if sup is None and tax is None:
                    continue
                name = " ".join(x for x in txt if not NUM.match(x) and x != ran)
                out.setdefault(ran, (ran, name, sup, tax))
    if not out:
        return None, "란을 하나도 못 읽었습니다. 서식이 다른 PDF 일 수 있습니다"
    return out, None


def write(html, out_html, out_pdf):
    """HTML 로 남기고 브라우저로 인쇄한다. 인쇄가 안 되면 HTML 은 남는다."""
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    return html_to_pdf(out_html, out_pdf)
