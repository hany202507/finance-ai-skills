# -*- coding: utf-8 -*-
"""리스회계 xlsx의 수식을 독립 평가(formulas)해 엔진값과 삼중 일치 확인.

사용법: python verify_lease.py <리스회계.xlsx>
- formulas 라이브러리로 워크북 전체를 재계산.
- 엔진 산출(_result.json) vs 수식 재계산값 비교(차이 1원 미만이면 일치).
- 검증 항목 PASS/FAIL 출력. 모두 PASS면 종료코드 0.
"""
import sys, os, re, json, warnings
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import formulas


def main():
    path = sys.argv[1]
    base = os.path.basename(path).upper()
    xl = formulas.ExcelModel().loads(path).finish()
    sol = xl.calculate()

    def cell(sheet, addr):
        key = "'[%s]%s'!%s" % (base, sheet, addr)
        for k, v in sol.items():
            if k.upper() == key:
                try:
                    return v.value[0, 0]
                except Exception:
                    return v.value
        return None

    def num(x):
        try:
            return float(x)
        except Exception:
            return None

    rj = path.rsplit(".", 1)[0] + "_result.json"
    eng = json.load(open(rj, encoding="utf-8")) if os.path.exists(rj) else {}

    pv = num(cell("입력가정", "B22"))
    rou = num(cell("입력가정", "B23"))
    tint = num(cell("입력가정", "B25"))
    liab_end = num(cell("입력가정", "B28"))
    dep_end = num(cell("입력가정", "B29"))
    dc_diff = num(cell("입력가정", "B31"))
    chk = {
        "리스부채잔액0": cell("입력가정", "C28"),
        "사용권자산잔액0": cell("입력가정", "C29"),
        "총이자식": cell("입력가정", "C30"),
        "차대일치": cell("입력가정", "C31"),
    }

    print("=== 수식 재계산 vs 엔진(삼중 일치) ===")
    rows = [
        ("리스부채(PV)", pv, eng.get("리스부채_PV")),
        ("사용권자산(ROU)", rou, eng.get("사용권자산_ROU")),
        ("총이자", tint, eng.get("총이자")),
    ]
    allmatch = True
    for name, f, e in rows:
        ok = (f is not None and e is not None and abs(f - e) < 1.0)
        allmatch = allmatch and ok
        print("  %-16s 수식=%15s 엔진=%15s  %s" %
              (name, "%.2f" % f if f is not None else "None",
               "%.2f" % e if e is not None else "None",
               "일치" if ok else "불일치"))

    print("--- 잔액/차대 검증(수식 평가) ---")
    print("  리스부채 기말잔액 :", round(liab_end, 4) if liab_end is not None else None)
    print("  사용권자산 기말장부:", round(dep_end, 4) if dep_end is not None else None)
    print("  전표 차대 차이    :", round(dc_diff, 4) if dc_diff is not None else None)
    allpass = allmatch
    for k, v in chk.items():
        s = str(v)
        p = "PASS" in s
        allpass = allpass and p
        print("  %-12s -> %s" % (k, s))

    print("ALL_PASS:", allpass)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
