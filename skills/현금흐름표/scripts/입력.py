# -*- coding: utf-8 -*-
"""분개장·재무상태표·손익계산서·계정 마스터·상세·명세서를 읽어 엔진 형식으로 맞춘다.

ERP 마다 모양이 달라서 아래를 모두 받는다.

분개장
  (가) 한 줄 한 계정: 전표번호 · 일자 · 계정코드 · 계정과목 · 차변 · 대변 (더존·위하고)
  (나) 차변·대변 계정이 다른 열: 승인번호 · 승인일 · 차변금액 · 차변계정과목 · 대변계정과목 · 대변금액
  계정과목이 「[2530003]미지급금 법인카드」처럼 코드를 품고 있으면 떼어 낸다.
  제목 줄이 위에 몇 줄 있어도 머리글 줄을 찾는다. 날짜가 아닌 줄(합계 등)은 뺀다.
  여러 파일(분기별)을 받으면 이어 붙인다.
  7자리 세부계정(2530003)은 상위계정(2530000)으로 합친다. 재무상태표가 상위계정으로만 나오고,
  세부계정 이름(자사몰정산)에는 성격이 안 드러나서다. 원래 계정은 「세부」에 남긴다.

재무상태표
  (가) 표: 계정코드 · 계정과목 · 구분 · 잔액 (기준일 열이 있으면 날짜별)
  (나) 공시 양식: 과목 · 당기(금액 두 칸) · 전기(금액 두 칸). 코드가 없고 소계·총계가 섞이며,
       감가상각누계액·대손충당금이 자산 바로 밑에 반복된다. 대·소분류(유형자산 …)를 같이 읽는다.
손익계산서(공시 양식): 당기순이익 대조용
"""
import re
from pathlib import Path
import pandas as pd
import 계정규칙 as R

별칭 = {
    "번호": ["전표번호", "전표No", "전표 No", "전표NO", "승인번호", "전표", "번호", "voucher"],
    "일자": ["일자", "전표일자", "승인일", "거래일자", "회계일자", "년/월/일", "날짜", "date"],
    "코드": ["계정코드", "코드", "account_code"],
    "계정": ["계정과목", "계정", "계정명", "과목"],
    "차변": ["차변", "차변금액", "debit"],
    "대변": ["대변", "대변금액", "credit"],
    "차변계정": ["차변계정과목", "차변계정", "차변과목"],
    "대변계정": ["대변계정과목", "대변계정", "대변과목"],
    "거래처": ["거래처명", "거래처"],
    "적요": ["적요", "내용", "memo"],
    "구분": ["구분", "전표구분"],
    "잔액": ["잔액", "기초잔액", "기말잔액", "금액", "전기말", "balance"],
    "기준일": ["기준일", "일자", "date"],
    "BS구분": ["구분", "분류", "type"],
}
_날짜 = re.compile(r"^\d{4}-\d{2}-\d{2}")
_코드이름 = re.compile(r"^\s*\[(\d+)\]\s*(.+)$")


def _열(df, 키, 필수=True):
    for a in 별칭[키]:
        if a in df.columns:
            return a
    for a in 별칭[키]:            # 두 줄 머리글을 합친 이름(구분[기표]년/월/일)은 포함으로 찾는다. 앞 열이 이긴다
        for c in df.columns:
            if len(a) >= 2 and a in str(c):
                return c
    if 필수:
        raise KeyError(f"'{키}' 열을 찾지 못했다. 있는 열: {list(df.columns)}")
    return None


_빈스타일 = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<fonts count="1"><font/></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            b'<borders count="1"><border/></borders>'
            b'<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf/></cellXfs></styleSheet>')


def 스타일제거(경로):
    """ERP 가 내보낸 xlsx 중 표준에 없는 스타일 속성 때문에 openpyxl 이 못 여는 파일이 있다
    (CellStyle count 오류). 값은 그대로 두고 styles.xml 만 최소본으로 바꾼 사본(BytesIO)을 준다."""
    import io, zipfile
    src = zipfile.ZipFile(경로)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for i in src.infolist():
            dst.writestr(i, _빈스타일 if i.filename == "xl/styles.xml" else src.read(i.filename))
    buf.seek(0)
    return buf


def _원본(경로, 시트=None, header=0):
    p = Path(경로)
    if p.suffix.lower() in (".csv", ".txt"):
        # 엑셀이 한글을 제대로 여는 BOM 붙은 UTF-8, BOM 없는 UTF-8, 한글 엑셀이 저장한 CP949 를 모두 받는다
        for enc in ("utf-8-sig", "cp949"):
            try:
                return pd.read_csv(p, header=header, encoding=enc)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(p, header=header, encoding="utf-8", encoding_errors="replace")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return pd.read_excel(p, sheet_name=시트 if 시트 is not None else 0, header=header)
        except (TypeError, ValueError, KeyError) as e:
            if "sheet" in str(e).lower() and "not found" in str(e).lower():
                raise
            return pd.read_excel(스타일제거(p), sheet_name=시트 if 시트 is not None else 0, header=header)


def _읽기(경로, 시트=None, 찾을=("차변", "계정", "잔액", "금액", "과목", "입금", "적요")):
    """머리글 줄을 찾아 읽는다. 첫 줄이 제목이어도 된다."""
    df = _원본(경로, 시트, header=None)
    for i in range(min(15, len(df))):
        값 = [_이름(v) for v in df.iloc[i].tolist() if pd.notna(v)]
        if sum(any(k in v for k in 찾을) for v in 값) >= 2:
            if i + 1 < len(df):
                이 = [_이름(v) for v in df.iloc[i].tolist()]
                다음 = [_이름(v) for v in df.iloc[i + 1].tolist() if pd.notna(v)]
                if len(set(x for x in 이 if x)) < len([x for x in 이 if x]) and \
                        sum(any(k in v for k in 찾을 + ("번호", "년/월/일", "일자")) for v in 다음) >= 2:
                    i += 1      # 윗줄은 묶음 제목(차변·대변)이고 실제 머리글은 다음 줄이다
            out = df.iloc[i + 1:].reset_index(drop=True)
            이름 = [_이름(v) if pd.notna(v) else f"열{j}" for j, v in enumerate(df.iloc[i].tolist())]
            if len(set(이름)) < len(이름) and i > 0:
                # 두 줄 머리글: 윗줄(차변·대변, 병합 셀은 앞으로 채움)을 앞에 붙인다
                위 = df.iloc[i - 1].tolist()
                채움, 앞 = [], ""
                for v in 위:
                    앞 = _이름(v) if pd.notna(v) and _이름(v) else 앞
                    채움.append(앞)
                이름 = [n if (not w or n.startswith(w)) else w + n for w, n in zip(채움, 이름)]
            out.columns = 이름
            return out
    out = df.iloc[1:].reset_index(drop=True)
    out.columns = [str(v).strip() for v in df.iloc[0].tolist()]
    return out


def _원(v):
    """금액. (1,000) 과 1,000- 는 음수로 읽는다. 숫자가 아니면 오류를 낸다(0 으로 삼키면 대차 오류의 원인이 가려진다)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0
    s = str(v).strip().replace(",", "").replace("₩", "").replace("원", "")
    if s in ("", "-"):
        return 0
    음 = False
    if s.startswith("(") and s.endswith(")"):
        s, 음 = s[1:-1], True
    elif s.endswith("-"):
        s, 음 = s[:-1], True
    try:
        x = int(round(float(s)))
    except ValueError:
        raise ValueError(f"금액으로 읽을 수 없는 값: {v!r}")
    return -x if 음 else x


def _코드(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return str(v).strip()


def _번호(v):
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(v)
    except (TypeError, ValueError):
        return str(v).strip()


def _글(x):
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip()


def _일자(v):
    s = str(v).strip()[:10].replace("/", "-").replace(".", "-")
    return s if _날짜.match(s) else None


def _계정분리(코드, 이름):
    """「[2530003]미지급금 법인카드」 → (2530003, '미지급금 법인카드')."""
    m = _코드이름.match(_글(이름))
    if m:
        return int(m.group(1)), m.group(2).strip()
    return (_코드(코드) if _글(코드) else _글(이름)), _글(이름)


def 분개장(경로, 시트=None):
    경로들 = 경로 if isinstance(경로, (list, tuple)) else [경로]
    줄 = []
    for p in 경로들:
        df = _읽기(p, 시트)
        번, 일 = _열(df, "번호"), _열(df, "일자")
        거, 적, 구 = _열(df, "거래처", False), _열(df, "적요", False), _열(df, "구분", False)
        차계, 대계 = _열(df, "차변계정", False), _열(df, "대변계정", False)
        차, 대 = _열(df, "차변"), _열(df, "대변")
        코, 계 = _열(df, "코드", False), _열(df, "계정", False)
        for x in df.itertuples(index=False):
            x = dict(zip(df.columns, x))
            d = _일자(x[일])
            if not d:
                continue
            공통 = {"번호": _번호(x[번]), "일자": d, "거래처": _글(x.get(거)) if 거 else "",
                   "적요": _글(x.get(적)) if 적 else "", "구분": _글(x.get(구)) if 구 else "", "파일": Path(p).name}
            if 차계 and 대계:
                for 계정열, 금액열, 차변 in ((차계, 차, True), (대계, 대, False)):
                    if not _글(x[계정열]):
                        continue
                    c, n = _계정분리(None, x[계정열])
                    a = _원(x[금액열])
                    줄.append(dict(공통, 코드=c, 계정=n, 차변=a if 차변 else 0, 대변=0 if 차변 else a))
            else:
                if not (계 or 코) or not _글(x.get(계 or 코)):
                    continue
                c, n = _계정분리(x.get(코) if 코 else None, x.get(계) if 계 else x.get(코))
                줄.append(dict(공통, 코드=c, 계정=n, 차변=_원(x[차]), 대변=_원(x[대])))
    # 같은 번호가 다른 날짜(또는 다른 파일)에 또 나오면 번호가 일자별로 다시 매겨진 분개장이다
    날짜들 = {}
    for l in 줄:
        날짜들.setdefault(l["번호"], set()).add((l["일자"], l["파일"]))
    if any(len(s) > 1 for s in 날짜들.values()):
        for l in 줄:
            l["번호"] = f"{l['일자']}-{l['번호']}"
    return 줄


def 세부계정_통합(줄):
    """7자리 이상 세부계정을 상위계정(끝 네 자리 0000)으로 합친다. 반환: (줄, {세부: 상위})."""
    코드들 = {l["코드"] for l in 줄 if isinstance(l["코드"], int)}
    if not 코드들 or min(코드들) < 1_000_000:
        return 줄, {}
    이름 = {}
    for l in 줄:
        이름.setdefault(l["코드"], l["계정"])
    바꿈 = {}
    for c in 코드들:
        p = c // 10000 * 10000
        if p != c:
            바꿈[c] = p
    상위이름 = {}
    for c, p in 바꿈.items():
        if p in 이름:
            상위이름[p] = 이름[p]
        else:   # 상위계정 줄이 없으면 세부 이름에서 공통 앞부분, 없으면 첫 세부 이름
            형제 = sorted(이름[s] for s, q in 바꿈.items() if q == p)
            앞 = 형제[0]
            for s in 형제[1:]:
                while 앞 and not s.startswith(앞):
                    앞 = 앞[:-1]
            상위이름[p] = 앞.strip(" _-") if len(앞.strip(" _-")) >= 2 else 형제[0]
    for l in 줄:
        if l["코드"] in 바꿈:
            l["세부"] = f"[{l['코드']}]{l['계정']}"
            l["코드"] = 바꿈[l["코드"]]
            l["계정"] = 상위이름[l["코드"]]
        elif l["코드"] in 상위이름:
            l["계정"] = 상위이름[l["코드"]]
    return 줄, 바꿈


def 전기이월_분리(줄):
    """분개장에서 전기이월 줄을 떼어 (당기 줄, 이월로 만든 기초잔액) 을 돌려준다."""
    # 전기이월 표시가 있어도 그 줄을 빼면 전표 대차가 깨지면 이월이 아니다
    # (「전기이월이익잉여금 대체」 같은 마감분개 줄). 전표 단위로 본다
    from collections import defaultdict
    후보 = defaultdict(list)
    for l in 줄:
        if l["구분"] == "전기이월" or l["적요"].startswith("전기이월"):
            후보[l["번호"]].append(l)
    전표합 = defaultdict(int)
    for l in 줄:
        if l["번호"] in 후보:
            전표합[l["번호"]] += l["차변"] - l["대변"]
    이월 = []
    for k, ls in 후보.items():
        if 전표합[k] - sum(l["차변"] - l["대변"] for l in ls) == 0:
            이월 += ls
    ids = {id(l) for l in 이월}
    당기 = [l for l in 줄 if id(l) not in ids] if 이월 else 줄
    기초 = {}
    for l in 이월:
        b = 기초.setdefault(l["코드"], {"코드": l["코드"], "계정": l["계정"], "차대": 0})
        b["차대"] += l["차변"] - l["대변"]
    return 당기, list(기초.values())


# ════════════════ 공시 양식 재무제표
_머리 = re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|\(\d+\)|\d+\.|(I|II|III|IV|V|VI|VII|VIII|IX|X)\.)")
_반대 = ("누계액", "충당금", "정부보조금", "국고보조금", "현재가치할인차금", "사채할인발행차금")


def _이름(v):
    return re.sub(r"\((주석|주)[^)]*\)", "", re.sub(r"[\s\u3000\xa0]+", "", _글(v)))


def _이름열(df):
    for i in range(min(6, len(df))):
        for j, v in enumerate(df.iloc[i].tolist()):
            if _이름(v) in ("과목", "과목명"):
                return j
    return None


def _양식여부(df):
    return _이름열(df) is not None or any("(당)기" in _이름(v) for v in df.iloc[0].tolist())


def _양식_열(df, nc=0):
    """(당기 열 두 칸, 전기 열 두 칸) 위치. 머리글 줄에서 (당)·(전)을 찾는다."""
    당 = 전 = None
    for i in range(min(3, len(df))):
        for j, v in enumerate(df.iloc[i].tolist()):
            if j <= nc:
                continue
            s = _이름(v)
            if 당 is None and ("(당)" in s or "당기" in s):
                당 = j
            elif 전 is None and ("(전)" in s or "전기" in s):
                전 = j
    당 = 당 or nc + 1
    전 = 전 or 당 + 2
    return (당, 당 + 1), (전, 전 + 1)


def 재무상태표_양식(경로, 시트=None):
    """공시 양식 재무상태표 → {'당기': 행들, '전기': 행들}. 행: 계정·구분·분류·잔액·모계정."""
    df = _원본(경로, 시트, header=None)
    nc = _이름열(df) or 0
    당, 전 = _양식_열(df, nc)
    out = {"당기": [], "전기": []}
    대 = 소 = None
    모 = None
    for i in range(len(df)):
        n = _이름(df.iat[i, nc])
        if not n or n in ("과목", "과목명"):
            continue
        if n in ("자산", "부채", "자본"):
            대 = n; continue
        if "총계" in n or n.startswith("(당기") or n.startswith("당기:") or n.startswith("전기:") or ":" in n:
            continue
        if _머리.match(n):
            소 = _머리.sub("", n).lstrip(".")
            continue
        반대 = 대 == "자산" and any(k in n for k in _반대)
        for 기, (a, b) in (("당기", 당), ("전기", 전)):
            if b >= df.shape[1]:
                continue
            세, 합 = df.iat[i, a], df.iat[i, b]
            # 반대계정 행의 합계 칸은 순액(자산 - 반대계정)이다. 반대계정 금액은 세부 칸에만 있다
            v = 세 if (pd.notna(세) and str(세).strip() != "") or 반대 else 합
            if pd.isna(v) or str(v).strip() == "":
                continue
            금액 = _원(v)
            out[기].append({"코드": None, "계정": n, "구분": 대, "분류": 소,
                           "잔액": -abs(금액) if 반대 else 금액, "모계정": 모 if 반대 else None})
        if not 반대:
            모 = n
    return out


def 손익계산서_양식(경로, 시트=None):
    """공시 양식 손익계산서 → {'당기': 당기순이익, '전기': …}. 순손실이면 음수."""
    df = _원본(경로, 시트, header=None)
    nc = _이름열(df) or 0
    당, 전 = _양식_열(df, nc)
    out = {}
    for i in range(len(df)):
        n = _이름(df.iat[i, nc])
        if "당기순" in n and ("이익" in n or "손실" in n) and "차감전" not in n:
            for 기, (a, b) in (("당기", 당), ("전기", 전)):
                if b < df.shape[1]:
                    v = next((df.iat[i, c] for c in (b, a) if pd.notna(df.iat[i, c])), None)
                    if v is not None:
                        x = _원(v)
                        out[기] = -abs(x) if "손실" in n and x > 0 else x
    return out


def 시산표(경로, 시트=None):
    """기말 합계잔액시산표 → [{코드, 계정, 구분, 분류, 잔액}]. 잔액은 자산·비용 차변 +, 부채·자본·수익 대변 +.
    구분은 <<자산>>·<<부채>>·<<자본>>·<<손익>> 과 <매출액>·<판매관리비> 같은 소제목에서 읽는다."""
    df = _원본(경로, 시트, header=None)
    머 = None
    for i in range(min(8, len(df))):
        v = [_이름(x) for x in df.iloc[i].tolist()]
        if any("계정과목" in x for x in v) and any("잔액" in x for x in v):
            머 = i
    if 머 is None:
        raise ValueError("시산표 머리글(계정과목·잔액)을 찾지 못했다")
    이름행 = [_이름(x) for x in df.iloc[머].tolist()]
    nc = next(j for j, x in enumerate(이름행) if "계정과목" in x)
    잔 = [j for j, x in enumerate(이름행) if "잔액" in x]
    차잔 = next((j for j in 잔 if j < nc), None)
    대잔 = next((j for j in 잔 if j > nc), None)
    out = []
    대 = 소 = None
    for i in range(머 + 1, len(df)):
        n = _이름(df.iat[i, nc])
        if not n:
            continue
        m = re.match(r"^<<(.+)>>$", n)
        if m:
            대 = m.group(1); 소 = None; continue
        m = re.match(r"^[<\[](.+)[>\]]$", n)
        if m:
            소 = m.group(1); continue
        c, nm = _계정분리(None, n)
        if not isinstance(c, int):
            continue
        d = _원(df.iat[i, 차잔]) if 차잔 is not None else 0
        cr = _원(df.iat[i, 대잔]) if 대잔 is not None else 0
        if 대 == "손익":
            구분 = "수익" if 소 and ("매출액" in 소 or "수익" in 소) else "비용"
        else:
            구분 = 대
        잔액 = d - cr if 구분 in ("자산", "비용") else cr - d
        out.append({"코드": c, "계정": nm, "구분": 구분, "분류": 소, "잔액": 잔액})
    return out


def 재무상태표(경로, 기준일=None, 시트=None):
    """계정코드·계정과목·구분·잔액. 기준일 열이 있으면 기준일별로 나눈 dict 를 돌려준다.
    공시 양식이면 {'당기': …, '전기': …}."""
    raw = _원본(경로, 시트, header=None)
    if _양식여부(raw):
        return 재무상태표_양식(경로, 시트)
    df = _읽기(경로, 시트, 찾을=("계정", "잔액", "금액", "구분", "코드", "과목"))
    if "차변잔액" in df.columns and "대변잔액" in df.columns and "잔액" not in df.columns:
        return {"-": _차대잔액(df)}
    kc, nc = _열(df, "코드", False), _열(df, "계정")
    gc, bc = _열(df, "BS구분", False), _열(df, "잔액")
    dc = _열(df, "기준일", False)
    df = df[df[bc].notna()]
    out = {}
    for _, x in df.iterrows():
        d = str(x[dc])[:10] if dc else "-"
        c, n = _계정분리(x[kc] if kc else None, x[nc])
        out.setdefault(d, []).append({"코드": c if kc else n, "계정": n,
                                      "구분": _글(x[gc]) or None if gc else None, "분류": None, "잔액": _원(x[bc])})
    return out


def 상세(경로, 필터=None):
    """가계정을 발라낼 상세 내역(은행거래내역·미분류목록). 입금 +, 출금 - 로 맞춘다.
    필터를 주면 어느 글자 열이든 그 값과 같은 행만 쓴다(은행거래내역의 계정 라벨이 '미분류'인 행 등)."""
    df = _읽기(경로, 찾을=("일자", "금액", "입금", "출금", "적요", "거래"))
    if 필터:
        글자열 = [c for c in df.columns if df[c].dtype == object]
        df = df[df[글자열].apply(lambda r: any(str(v).strip() == 필터 for v in r), axis=1)]
    dc = next(c for c in ["일자", "거래일자", "거래일시", "승인일", "날짜", "date"] if c in df.columns)
    tc = next((c for c in ["적요", "내용", "거래내용", "memo"] if c in df.columns), None)
    pc = next((c for c in ["거래처", "거래처명", "거래처 라벨", "상대방"] if c in df.columns), None)
    out = []
    for _, x in df.iterrows():
        if "입금" in df.columns and "출금" in df.columns:
            금액 = _원(x["입금"]) - _원(x["출금"])
        else:
            ac = next(c for c in ["금액", "거래금액", "amount"] if c in df.columns)
            금액 = _원(x[ac])
            io = next((c for c in ["입출금", "구분", "거래구분"] if c in df.columns), None)
            if io and "출" in str(x[io]):
                금액 = -abs(금액)
        d = _일자(x[dc])
        if not 금액 or not d:
            continue
        out.append({"일자": d, "금액": 금액, "적요": _글(x[tc]) if tc else "", "거래처": _글(x[pc]) if pc else ""})
    return out


def _차대잔액(df):
    """차변잔액·대변잔액 두 열인 잔액표 → 계정별 한 줄. 거래처별로 나뉜 줄은 합친다. 구분이 없으면 이름으로 정한다."""
    kc, nc = _열(df, "코드", False), _열(df, "계정")
    gc = _열(df, "BS구분", False)
    합, 이름, 구분 = {}, {}, {}
    for _, x in df.iterrows():
        c, n = _계정분리(x[kc] if kc else None, x[nc])
        if c is None or (isinstance(c, str) and not c.strip()):
            continue
        차, 대 = (_원(x["차변잔액"]) if pd.notna(x["차변잔액"]) else 0), (_원(x["대변잔액"]) if pd.notna(x["대변잔액"]) else 0)
        합[c] = 합.get(c, 0) + 차 - 대
        이름.setdefault(c, n)
        if gc and _글(x[gc]):
            구분[c] = _글(x[gc])
    out = []
    for c, v in 합.items():
        g = 구분.get(c) or R.구분_코드추정(c, 이름[c])
        out.append({"코드": c, "계정": 이름[c], "구분": g, "분류": None, "잔액": v if g == "자산" else -v})
    return out


def 계정명세서(경로):
    """전기말 추적 계정(미지급금·가지급금 …)의 거래처별 잔액. 활동·항목 열이 있으면 그대로 쓴다.
    차변잔액·대변잔액 두 열인 기초잔액 파일이면 거래처가 적힌 줄만 명세로 쓴다."""
    df = _읽기(경로, 찾을=("계정", "잔액", "거래처", "금액"))
    if "차변잔액" in df.columns and "대변잔액" in df.columns and "잔액" not in df.columns:
        pc = next((c for c in ["거래처", "거래처명"] if c in df.columns), None)
        if not pc:
            return []
        df = df[df[pc].map(lambda v: bool(_글(v)))].copy()
        df["잔액"] = [abs((_원(a) if pd.notna(a) else 0) - (_원(b) if pd.notna(b) else 0))
                     for a, b in zip(df["차변잔액"], df["대변잔액"])]
    kc, nc = _열(df, "코드", False), _열(df, "계정", False)
    bc = _열(df, "잔액")
    pc = next((c for c in ["거래처", "거래처명"] if c in df.columns), None)
    tc = next((c for c in ["적요", "내용", "비고", "성격"] if c in df.columns), None)
    oc = next((c for c in ["원천계정", "원천 계정", "원천", "원천코드", "발생계정"] if c in df.columns), None)
    out = []
    for _, x in df.iterrows():
        if pd.isna(x[bc]):
            continue
        c, n = _계정분리(x[kc] if kc else None, x[nc] if nc else "")
        out.append({"코드": c, "계정": n, "잔액": _원(x[bc]), "원천": _원천계정(x[oc]) if oc else None,
                    "거래처": _글(x[pc]) if pc else "", "적요": _글(x[tc]) if tc else "",
                    "활동": _글(x["활동"]) or None if "활동" in df.columns else None,
                    "항목": _글(x["항목"]) or None if "항목" in df.columns else None})
    return out


def _원천계정(v):
    """「833 광고선전비」·「[833]광고선전비」·「833」·「광고선전비」 → (코드 또는 None, 이름)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    t = str(v).strip()
    if not t:
        return None
    m = re.match(r"^\[?(\d+)\]?\s*(.*)$", t)
    if m:
        return (_코드(m.group(1)), m.group(2).strip())
    return (None, t)


def 판정파일(경로):
    """회계사 판정: 계정코드·거래처·활동·항목(직접법항목)·근거·판정자·판정일. 활동이 빈 줄은 건너뛴다.
    판정후보_<기간>.csv 를 채운 것도 그대로 받는다."""
    df = _읽기(경로, 찾을=("계정", "활동", "거래처"))
    kc = _열(df, "코드", False) or _열(df, "계정")
    hc = next((c for c in ["항목", "직접법항목", "직접법 항목", "표시항목"] if c in df.columns), None)
    out = []
    for _, x in df.iterrows():
        활 = _글(x["활동"]) if "활동" in df.columns else ""
        if not 활:
            continue
        c, _n = _계정분리(x[kc], "")
        out.append({"코드": c, "거래처": _글(x["거래처"]) if "거래처" in df.columns else "",
                    "활동": 활, "항목": _글(x[hc]) if hc else "",
                    "근거": _글(x["근거"]) if "근거" in df.columns else "",
                    "판정자": _글(x["판정자"]) if "판정자" in df.columns else "",
                    "판정일": _글(x["판정일"])[:10] if "판정일" in df.columns else ""})
    return out


def 계정마스터(경로):
    df = _읽기(경로, 찾을=("계정", "코드", "구분", "과목"))
    kc, nc, gc = _열(df, "코드"), _열(df, "계정"), _열(df, "BS구분")
    return {_코드(x[kc]): (_글(x[nc]), _글(x[gc])) for _, x in df.iterrows() if pd.notna(x[kc])}


def _코드찾기(행들, 줄, 마스터, 메모, 이름):
    """코드가 없는 재무상태표 행에 분개장 코드를 붙인다. 반대계정은 바로 위 자산의 코드 다음 번호."""
    이름표 = {}
    for l in 줄:
        이름표.setdefault(_이름(l["계정"]), l["코드"])
    for k, v in 마스터.items():
        이름표.setdefault(_이름(v[0]), k)
    코드이름 = {v: k for k, v in 이름표.items()}
    못찾음 = []
    for b in 행들:
        if not isinstance(b["코드"], (str, type(None))):
            continue
        n = _이름(b["계정"])
        if b.get("모계정"):
            continue
        if n in 이름표:
            b["코드"] = 이름표[n]
            continue
        후보 = [c for k, c in 이름표.items() if k and (k in n or n in k) and not any(r in k for r in _반대)]
        if len(set(후보)) == 1:
            b["코드"] = 후보[0]
        else:
            b["코드"] = b["계정"]
            못찾음.append(b["계정"])
    # 반대계정(누계액·충당금): 모계정 코드 + 1 단위(3자리 1, 7자리 10000). 없으면 남은 같은 이름 코드를 순서대로
    # 같은 이름(감가상각누계액)이 여러 코드에 있으므로 코드 → 이름으로 본다
    전코드 = {}
    for l in 줄:
        전코드.setdefault(l["코드"], _이름(l["계정"]))
    for k, v in 마스터.items():
        전코드.setdefault(k, _이름(v[0]))
    남은 = defaultdict_list()
    for c, nm in sorted(전코드.items(), key=lambda kv: str(kv[0])):
        종 = next((r for r in _반대 if r in nm), None)
        if 종 and isinstance(c, int):
            남은[종].append(c)
    모코드 = {_이름(b["계정"]): b["코드"] for b in 행들 if not b.get("모계정")}
    반대행 = [b for b in 행들 if b.get("모계정")]
    쓴 = set()
    for b in 반대행:   # 1차: 모계정 코드 + 1 단위
        종류 = next((r for r in _반대 if r in _이름(b["계정"])), None)
        p = 모코드.get(_이름(b["모계정"]))
        if isinstance(p, int):
            단위 = 10000 if p >= 1_000_000 else 1
            if (p + 단위) in 남은.get(종류, []):
                b["코드"] = p + 단위; 쓴.add(p + 단위)
    for b in 반대행:   # 2차: 남은 같은 종류 코드를 순서대로
        if isinstance(b["코드"], int):
            continue
        종류 = next((r for r in _반대 if r in _이름(b["계정"])), None)
        c = next((x for x in 남은.get(종류, []) if x not in 쓴), None)
        if c is not None:
            b["코드"] = c; 쓴.add(c)
            메모.append(f"{이름}: {b['모계정']}의 {b['계정']}을 코드 {c}로 짝지었다(번호 순서로 추정)")
        else:
            b["코드"] = f"{b['모계정']} {b['계정']}"
            못찾음.append(b["코드"])
    if 못찾음:
        메모.append(f"{이름} 계정 중 분개장 코드와 못 맞춘 것 {len(못찾음)}개: {', '.join(map(str, 못찾음[:8]))}")
    # 같은 코드로 모인 행은 합친다
    합 = {}
    for b in 행들:
        k = b["코드"]
        if k in 합:
            합[k]["잔액"] += b["잔액"]
        else:
            합[k] = dict(b)
    return list(합.values())


def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)


def 준비(분개장경로, 재무상태표경로=None, 계정마스터경로=None, 분개장시트=None, 세부통합=True, 손익계산서경로=None,
         시산표경로=None, 재무상태표시트=None, 손익계산서시트=None):
    """엔진 입력 한 벌: (분개, 전기BS, 기말BS 또는 None, 마스터, 메모 목록, 기간, 부가정보)."""
    메모 = []
    부가 = {}
    import 원장복원
    경로들 = 분개장경로 if isinstance(분개장경로, (list, tuple)) else [분개장경로]
    if all(원장복원.원장여부(p) for p in 경로들):
        원 = []
        for p in 경로들:
            ls, 원기간, 원이월, 월계 = 원장복원.읽기(p)
            복, 통 = 원장복원.복원(ls)
            원 += 복
            부가.setdefault("원장이월", {}).update(원이월)
            메모.append(f"원장 월계 대조: {월계['월계계정']}개 계정 중 읽은 줄 합계와 다른 계정 {len(월계['어긋남'])}개"
                      + (f" {list(월계['어긋남'])[:5]}" if 월계["어긋남"] else ""))
            부가["원장월계어긋남"] = len(월계["어긋남"])
            메모.append(f"계정별원장 {Path(p).name}: 전표번호가 없어 {len(ls):,}줄을 다시 묶었다 "
                      + ", ".join(f"{k} {v['줄']:,}줄·{v['전표']:,}전표" for k, v in 통.items()))
        부가["원장복원"] = True
    else:
        원 = 분개장(분개장경로, 분개장시트)
    if not 원:
        raise ValueError("분개장에서 날짜가 있는 줄을 하나도 못 읽었다")
    if 세부통합:
        원, 바꿈 = 세부계정_통합(원)
        if 바꿈:
            메모.append(f"세부계정 {len(바꿈)}개를 상위계정으로 합쳤다(원래 계정은 분개장 시트 '세부' 열)")
    줄, 이월 = 전기이월_분리(원)
    이월일 = max((l["일자"] for l in 원 if l["구분"] == "전기이월" or l["적요"].startswith("전기이월")), default=None)
    마스터 = 계정마스터(계정마스터경로) if 계정마스터경로 else {}
    for c, (nm, _) in 부가.get("원장이월", {}).items():
        마스터.setdefault(c, (nm, R.구분_코드추정(c, nm)))
    if 부가.get("원장복원") and not (재무상태표경로 or 시산표경로 or 계정마스터경로):
        메모.append("원장에는 계정 구분(자산·부채 …)이 없어 계정 이름으로, 이름으로 모르면 더존 코드대역으로 정했다. 계정규칙 시트에서 확인")
    시작, 끝 = min(l["일자"] for l in 줄), max(l["일자"] for l in 줄)
    첫거래 = 시작
    전기, 기말 = [], None
    if 시산표경로:
        # 기말 시산표 - 당기 분개장 증감 = 기초. 계정 단위로 정확한 기초가 나온다
        tb = 시산표(시산표경로)
        합 = {}
        for l in 줄:
            합[l["코드"]] = 합.get(l["코드"], 0) + l["차변"] - l["대변"]
        기말, 전기, 어긋 = [], [], []
        for b in tb:
            dr = 합.get(b["코드"], 0)
            증감 = dr if b["구분"] in ("자산", "비용") else -dr
            if b["구분"] in ("수익", "비용"):
                if b["잔액"] != 증감:
                    어긋.append(f"{b['계정']}({b['코드']}) 시산표 {b['잔액']:,} / 분개장 {증감:,}")
                continue
            기말.append(dict(b))
            전기.append(dict(b, 잔액=b["잔액"] - 증감))
        tb코드 = {b["코드"] for b in tb}
        빠짐 = sorted({l["코드"] for l in 줄} - tb코드, key=str)
        for b in tb:
            마스터[b["코드"]] = (b["계정"], b["구분"])
        메모.append(f"기말 시산표 {len(tb)}계정에서 분개장 증감을 빼 기초를 만들었다"
                  + (f". 손익계정 중 시산표와 분개장이 다른 것 {len(어긋)}개: {'; '.join(어긋[:5])}" if 어긋
                     else ". 손익계정은 시산표와 분개장이 전부 같다")
                  + (f". 시산표에 없는 분개장 계정 {len(빠짐)}개: {빠짐[:8]}" if 빠짐 else ""))
        if 재무상태표경로:
            부가["전기재무상태표_대조용"] = 재무상태표(재무상태표경로, 시트=재무상태표시트)
    elif 재무상태표경로:
        표 = 재무상태표(재무상태표경로, 시트=재무상태표시트)
        if set(표) == {"당기", "전기"}:
            전기, 기말 = 표["전기"], 표["당기"] or None
            메모.append("공시 양식 재무상태표: 전기 열을 기초로, 당기 열을 기말 대조로 썼다")
            y = int(시작[:4])
            if 시작[5:] <= "01-31":
                시작 = f"{y}-01-01"
        else:
            날짜 = sorted(표)
            앞 = [d for d in 날짜 if d == "-" or d < 시작]
            if not 앞:
                raise ValueError(f"분개장 시작일 {시작} 이전 기준일의 재무상태표가 없다. 있는 기준일: {날짜}")
            전기 = 표[앞[-1]]
            메모.append(f"전기 재무상태표 기준일 {앞[-1]}")
            if 앞[-1] != "-":
                시작 = _다음날(앞[-1])
            elif 시작[8:] != "01":
                시작 = 시작[:8] + "01"
                메모.append(f"재무상태표에 기준일이 없어 기간을 분개장 첫 달 1일({시작})부터로 봤다")
            if 끝 in 표:
                기말 = 표[끝]
                메모.append(f"같은 파일의 {끝} 재무상태표로 기말 대조")
    elif 이월:
        메모.append(f"전기 재무상태표 없이 분개장의 전기이월 {len(이월)}줄로 기초잔액을 만들었다")
        if 이월일:
            시작 = _다음날(이월일)
    else:
        # 기초를 줄 자료가 없으면 잔액을 열어 두고 당기 변동만으로 만든다(대표 지시 2026-09-28)
        부가["잔액열어둠"] = True
        메모.append("기초 잔액 자료가 없어 잔액을 열어 두었다. 현금흐름은 당기 변동만이고, 기초·기말 현금과 잔액이 필요한 검산(독립 B)은 판정하지 않는다")
    if 이월 and (재무상태표경로 or 시산표경로):
        메모.append(f"분개장의 전기이월 {len(이월)}줄은 뺐다(전기 재무상태표를 쓴다)")
    if not 전기:
        전기 = []
        for b in 이월:
            구분 = 마스터.get(b["코드"], (None, None))[1] or R.구분_코드추정(b["코드"], b["계정"])
            잔액 = b["차대"] if 구분 == "자산" else -b["차대"]
            전기.append({"코드": b["코드"], "계정": b["계정"], "구분": 구분, "잔액": 잔액})
    전기 = _코드찾기(전기, 줄, 마스터, 메모, "전기 재무상태표")
    if 기말:
        기말 = _코드찾기(기말, 줄, 마스터, 메모, "기말 재무상태표")
    if 손익계산서경로:
        부가["손익계산서"] = 손익계산서_양식(손익계산서경로, 손익계산서시트)
    if 시작 != 첫거래:
        메모.append(f"기간 시작일은 기초 기준일 다음 날({시작}), 첫 거래일은 {첫거래}")
    return 줄, 전기, 기말, 마스터, 메모, (시작, 끝), 부가


def _다음날(d):
    import datetime as dt
    try:
        return (dt.date.fromisoformat(d[:10]) + dt.timedelta(days=1)).isoformat()
    except ValueError:
        return d
