# -*- coding: utf-8 -*-
"""수정분개를 장부에 반영해 수정 후 장부를 만든다.

  python apply_fix.py <장부폴더> [산출폴더]

<장부폴더>/검토산출 의 수정분개를 읽어 장부에 붙이고 <산출폴더> 에 수정 후 장부를 낸다.
기본 산출폴더는 <장부폴더>/수정후 다.

**원본 장부를 고치지 않는다.** 새 폴더에 낸다. 회계사가 둘을 나란히 놓고 본다.

붙이는 방식은 더존과 같다. 원건을 지우지 않고 음수 행과 양수 행을 덧붙인다.
그래야 무엇을 왜 고쳤는지 장부에 남는다.
"""
import os
import sys
import glob
import shutil

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from review import (_rows_from_xlsx, write_xlsx, MM_COLS, GJ_COLS,  # noqa: E402
                    MM_W, GJ_W, n, s)


def find(folder, prefix):
    for p in sorted(glob.glob(os.path.join(folder, "*.xlsx"))):
        if os.path.basename(p).startswith(prefix):
            return p
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = os.path.abspath(sys.argv[1])
    fixes = os.path.join(src, "검토산출")
    out = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 \
        else os.path.join(src, "수정후")
    os.makedirs(out, exist_ok=True)

    led_p = find(src, "매입매출장") or find(src, "매입매출전표")
    gj_p = find(src, "일반전표")
    fix_mm_p = find(fixes, "수정_매입매출전표")
    fix_gj_p = find(fixes, "수정_일반전표")
    if not (led_p and fix_mm_p):
        print("장부나 수정분개를 못 찾았습니다. review.py 를 먼저 돌립니다.")
        sys.exit(1)

    led = _rows_from_xlsx(led_p)
    gjs = _rows_from_xlsx(gj_p) if gj_p else []
    allfix = _rows_from_xlsx(fix_mm_p)
    fgj = _rows_from_xlsx(fix_gj_p) if fix_gj_p else []

    # 금액이 없는 보정행은 덧붙이지 않는다. 원건의 그 칸을 고친다
    patched, unresolved = 0, 0
    for f in allfix:
        if n(f["공급가액"]) or n(f["부가세"]) or "[E3]" not in s(f["품명"]):
            continue
        want = s(f["사업자(주민)등록번호"])
        if want.startswith("<"):
            unresolved += 1
            continue
        for r in led:
            if (n(r["년도"]), n(r["월"]), n(r["일"])) == (n(f["년도"]), n(f["월"]), n(f["일"])) \
                    and s(r["거래처명"]) == s(f["거래처명"]) \
                    and not s(r["사업자(주민)등록번호"]):
                r["사업자(주민)등록번호"] = want
                patched += 1
                break
    fmm = [r for r in allfix if n(r["공급가액"]) or n(r["부가세"])]

    merged_mm = led + fmm
    merged_gj = gjs + fgj
    merged_mm.sort(key=lambda r: (n(r["년도"]), n(r["월"]), n(r["일"]),
                                  n(r["매입매출구분(1-매출/2-매입)"])))
    merged_gj.sort(key=lambda r: (n(r["월"]), n(r["일"])))

    base = os.path.basename(led_p)
    write_xlsx(os.path.join(out, base),
               [("매출자료 & 매입자료", MM_COLS, merged_mm, MM_W)])
    if gj_p:
        write_xlsx(os.path.join(out, os.path.basename(gj_p)),
                   [("일반전표", GJ_COLS, merged_gj, GJ_W)])

    # 원천과 마스터를 같이 옮긴다. 다시 검토하려면 옆에 있어야 한다
    copied = 0
    for pat in ("*.xlsx", "*.pdf", "*.csv"):
        for p in sorted(glob.glob(os.path.join(src, pat))):
            b = os.path.basename(p)
            # 장부만 새로 쓴다. 원천·마스터·직원 신고서 PDF 는 그대로 옮긴다.
            # 신고서를 안 옮기면 다음 단계인 부가세신고서검토가 대조할 것이 없다
            if b.startswith(("매입매출장", "매입매출전표", "일반전표")) or b.startswith("~$"):
                continue
            shutil.copy2(p, os.path.join(out, b))
            copied += 1
    for p in sorted(glob.glob(os.path.join(src, "*.py"))):
        shutil.copy2(p, os.path.join(out, os.path.basename(p)))

    print("=" * 66)
    print("수정분개 반영")
    print("=" * 66)
    print(f"  매입매출장 {len(led):,}행 + 수정 {len(fmm)}줄 -> {len(merged_mm):,}행")
    print(f"  일반전표   {len(gjs):,}행 + 수정 {len(fgj)}줄 -> {len(merged_gj):,}행")
    if patched:
        print(f"  사업자번호 {patched}건은 원건의 그 칸을 채웠습니다")
    if unresolved:
        print(f"  사업자번호 {unresolved}건은 원천에도 없어 그대로 뒀습니다. "
              f"거래처에 확인해야 합니다")
    print(f"  원천·마스터 {copied}개를 같이 옮겼습니다")
    print(f"\n산출 -> {out}")
    print("\n이 폴더에 review.py 를 다시 돌립니다. 정지가 0건이면 닫힌 것입니다.")


if __name__ == "__main__":
    main()
