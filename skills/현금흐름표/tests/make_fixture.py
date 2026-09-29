# -*- coding: utf-8 -*-
"""test_engine 의 합성 분개장을 엑셀로 떨어뜨린다. 워크북 수식이 재분류를 제대로 따라가는지 볼 때 쓴다."""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from test_engine import 분개, 전기, 마스터

def 저장(폴더):
    os.makedirs(폴더, exist_ok=True)
    j = pd.DataFrame(분개()).rename(columns={"번호": "전표번호", "코드": "계정코드", "계정": "계정과목"})
    j.to_excel(os.path.join(폴더, "합성_분개장.xlsx"), index=False)
    b = pd.DataFrame(전기).rename(columns={"코드": "계정코드", "계정": "계정과목"})
    b.insert(0, "기준일", "2026-05-31")
    b.to_excel(os.path.join(폴더, "합성_재무상태표.xlsx"), index=False)
    pd.DataFrame([{"계정코드": k, "계정과목": v[0], "구분": v[1]} for k, v in 마스터.items()]).to_excel(
        os.path.join(폴더, "합성_계정.xlsx"), index=False)

if __name__ == "__main__":
    저장(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "fixtures"))
