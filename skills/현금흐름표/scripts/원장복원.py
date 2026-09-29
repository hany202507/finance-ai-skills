# -*- coding: utf-8 -*-
"""계정별원장 → 분개장. 원장에는 전표번호도 상대계정도 없어서 전표를 다시 묶는다.

더존 계정별원장은 계정마다 「계정과목 : [103] 보통예금」 머리 아래 날짜·적요·거래처코드·거래처·차변·대변·잔액이 이어지고,
「전월이월」·「월계」·「누계」 줄이 끼어 있다. 같은 전표의 줄들은 날짜와 적요가 같다(더존은 전표 적요를 줄마다 복사한다).

묶는 순서(앞에서 묶인 줄은 뒤로 넘기지 않는다)
  1. 적요 묶음    같은 날짜·같은 적요의 줄. 합이 대차 일치면 한 전표. 그 안에서 거래처코드별로도 대차가 맞으면 거래처별로 나눈다
  2. 금액 짝      대차가 안 맞는 적요 묶음끼리, 같은 날짜에 남은 금액이 서로 반대인 것을 합친다
  3. 일자 잔여    그래도 남은 줄은 날짜별로 한 전표로 묶는다(하루치 전표가 모두 대차 일치라 날짜 잔여도 맞는다).
                 이 전표의 현금은 그날 남은 상대 줄에 금액 비율로 나뉘므로 신뢰도가 낮다
구분 열에 「원장 복원(적요)」·「원장 복원(금액 짝)」·「원장 복원(일자 잔여)」를 적는다.
"""
import re
from collections import defaultdict
from pathlib import Path
import pandas as pd

_계정머리 = re.compile(r"계정과목\s*:\s*\[(\d+)\]\s*(.+?)\s*$")
_기간 = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})\s*~\s*(\d{4})[.\-/](\d{2})[.\-/](\d{2})")


def 원장여부(경로):
    import 입력
    try:
        df = 입력._원본(경로, 0, header=None)
    except Exception:
        return False
    머 = " ".join(str(v) for v in df.iloc[:8].values.ravel() if pd.notna(v))
    return "계정별원장" in 머.replace(" ", "") or bool(_계정머리.search(머))


def 읽기(경로):
    """계정별원장 → [{코드, 계정, 일자, 적요, 거래처코드, 거래처, 차변, 대변}], 기간, 전월이월 잔액."""
    import 입력, warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            시트들 = pd.read_excel(경로, sheet_name=None, header=None)      # 원장은 여러 시트에 나뉘어 있을 수 있다
        except (TypeError, ValueError, KeyError):
            시트들 = pd.read_excel(입력.스타일제거(경로), sheet_name=None, header=None)
    줄, 이월, 기간 = [], {}, None
    월계 = {}
    for df in 시트들.values():
        계 = None
        열 = None
        for row in df.itertuples(index=False):
            row = list(row)
            글 = " ".join(str(v) for v in row if pd.notna(v))
            if 기간 is None:
                m = _기간.search(글)
                if m:
                    기간 = (f"{m.group(1)}-{m.group(2)}-{m.group(3)}", f"{m.group(4)}-{m.group(5)}-{m.group(6)}")
            m = _계정머리.search(글)
            if m:
                계 = (int(m.group(1)), re.sub(r"\s+", "", m.group(2)))
                continue
            이름 = [입력._이름(v) for v in row]
            if "날짜" in 이름 and "차변" in 이름:
                열 = {k: 이름.index(k) for k in ("날짜", "적요란", "코드", "거래처", "차변", "대변", "잔액") if k in 이름}
                열.setdefault("적요란", next((i for i, v in enumerate(이름) if "적요" in v), 1))
                continue
            if 계 is None or 열 is None:
                continue
            날 = row[열["날짜"]]
            적 = 입력._글(row[열["적요란"]])
            if 적.replace(" ", "") == "전월이월":
                잔 = row[열["잔액"]] if "잔액" in 열 else None
                이월[계[0]] = (계[1], 입력._원(잔) if pd.notna(잔) else 0)
                continue
            if 적.replace(" ", "").replace("[", "").replace("]", "") == "월계":
                w = 월계.setdefault(계[0], [0, 0])
                w[0] += 입력._원(row[열["차변"]]); w[1] += 입력._원(row[열["대변"]])
                continue
            if not (isinstance(날, str) and re.match(r"^\d{2}-\d{2}$", 날.strip())):
                continue
            연 = (기간 or ("2000-01-01",))[0][:4]
            줄.append({"코드": 계[0], "계정": 계[1], "일자": f"{연}-{날.strip()}", "적요": 적,
                      "거래처코드": 입력._글(row[열["코드"]]) if "코드" in 열 else "",
                      "거래처": 입력._글(row[열["거래처"]]) if "거래처" in 열 else "",
                      "차변": 입력._원(row[열["차변"]]), "대변": 입력._원(row[열["대변"]])})
    # 원장 자체의 월계와 읽은 줄 합계를 맞춘다(한 줄이라도 빠지면 여기서 걸린다)
    합 = defaultdict(lambda: [0, 0])
    for l in 줄:
        합[l["코드"]][0] += l["차변"]; 합[l["코드"]][1] += l["대변"]
    어긋 = {c: (합[c], w) for c, w in 월계.items() if tuple(합[c]) != tuple(w)}
    return 줄, 기간, 이월, {"월계계정": len(월계), "어긋남": 어긋}


def 복원(줄):
    """줄에 번호·구분을 붙여 분개장 형식으로 돌려준다. 반환: (분개 줄, 통계)."""
    차대 = lambda ls: sum(l["차변"] - l["대변"] for l in ls)
    묶 = defaultdict(list)
    for l in 줄:
        묶[(l["일자"], l["적요"])].append(l)
    전표 = []          # (구분, 줄들)
    남은 = defaultdict(list)    # 일자 → [(잔차, 줄들)]
    for (일, 적), ls in 묶.items():
        if 차대(ls) == 0:
            처별 = defaultdict(list)
            for l in ls:
                처별[l["거래처코드"] or l["거래처"]].append(l)
            if len(처별) > 1 and all(차대(v) == 0 for v in 처별.values()):
                전표 += [("원장 복원(적요)", v) for v in 처별.values()]
            else:
                전표.append(("원장 복원(적요)", ls))
        else:
            남은[일].append([차대(ls), ls])
    짝수 = 0
    for 일, 목록 in 남은.items():
        색 = defaultdict(list)
        for i, (r, ls) in enumerate(목록):
            색[r].append(i)
        쓴 = set()
        for i, (r, ls) in enumerate(목록):
            if i in 쓴:
                continue
            j = next((j for j in 색.get(-r, []) if j not in 쓴 and j != i), None)
            if j is not None:
                쓴 |= {i, j}
                전표.append(("원장 복원(금액 짝)", ls + 목록[j][1]))
                짝수 += 1
        잔여 = [l for i, (r, ls) in enumerate(목록) if i not in 쓴 for l in ls]
        if 잔여:
            if 차대(잔여) != 0:
                raise ValueError(f"{일} 원장 줄의 차대가 맞지 않는다({차대(잔여):,}). 원장이 일부만 들어온 것 같다")
            전표.append(("원장 복원(일자 잔여)", 잔여))
    out = []
    통계 = defaultdict(lambda: [0, 0])
    for n, (구분, ls) in enumerate(sorted(전표, key=lambda t: (t[1][0]["일자"], t[1][0]["적요"])), 1):
        for l in ls:
            out.append({"번호": f"R{n}", "일자": l["일자"], "코드": l["코드"], "계정": l["계정"], "차변": l["차변"],
                        "대변": l["대변"], "거래처": l["거래처"] or l["거래처코드"], "적요": l["적요"], "구분": 구분, "파일": "원장"})
            통계[구분][0] += 1
        통계[구분][1] += 1
    return out, {k: {"줄": v[0], "전표": v[1]} for k, v in 통계.items()}
