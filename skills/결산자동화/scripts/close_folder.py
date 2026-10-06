# -*- coding: utf-8 -*-
"""엑셀이나 CSV 폴더 하나로 결산 4종을 낸다. 한 명령으로 끝난다.

  python close_folder.py <자료폴더> [기간] [회사프로파일] [산출폴더]
예:
  python close_folder.py ./모의데이터
  python close_folder.py ./모의데이터 2026-06
  python close_folder.py ./내회사자료 2026-06 profile_glowbeam ./결산결과

**기간을 안 주면 통장에 있는 달 중 마지막 달로 잡고 화면에 찍는다.**
산출폴더를 안 주면 **CSV폴더 안에 `결산_<기간>` 을 만든다.**
원본 파일은 건드리지 않는다. 읽기만 한다.

폴더에 있어야 하는 표 열 개 (.xlsx 나 .csv):
  bank_transactions · card_approvals · tax_invoices · payroll · partners
  accounts · opening_balance · journal_prior · platform_settlements · export_invoices
"""
import sys, io, os, re, subprocess, importlib.util

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

기간꼴 = re.compile(r"\d{4}(-\d{2}|Q[1-4]|H[12])$")

# (import 이름, pip 이름). 엑셀 읽기·쓰기, 확인사항 docx, 검산 재계산에 쓴다.
필요한것 = [("openpyxl", "openpyxl"), ("docx", "python-docx"), ("formulas", "formulas")]


def 준비():
    """없는 것만 처음 한 번 깐다. 수강생이 사전과제로 설치할 것을 없애기 위한 것이다."""
    빠진것 = [pip for mod, pip in 필요한것 if importlib.util.find_spec(mod) is None]
    if not 빠진것:
        return
    print("   처음 한 번만 설치합니다: " + " · ".join(빠진것))
    if subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + 빠진것).returncode != 0:
        raise SystemExit("설치가 안 됐습니다. 직접 깔아 주십시오: pip install " + " ".join(빠진것))
    print("   설치 끝")

필요한표 = ["bank_transactions", "card_approvals", "tax_invoices", "payroll", "partners",
            "accounts", "opening_balance", "platform_settlements", "export_invoices"]


def 표경로(kit, stem):
    x = os.path.join(kit, stem + ".xlsx")
    return x if os.path.exists(x) else os.path.join(kit, stem + ".csv")


def 기간찾기(kit):
    """통장 거래일자에 있는 달 중 마지막 달을 고른다. 무엇을 골랐는지 화면에 찍는다."""
    from glowbeam_raw import _read_table
    rows = _read_table(표경로(kit, "bank_transactions"))
    if not rows:
        raise SystemExit("통장이 비어 있어 기간을 정하지 못했습니다. 기간을 직접 주십시오.")
    키 = next((k for k in rows[0] if "일자" in k or "날짜" in k), None)
    if 키 is None:
        raise SystemExit("통장에 거래일자 열이 없습니다. 기간을 직접 주십시오.")
    달 = sorted({str(r.get(키, ""))[:7] for r in rows
                if re.fullmatch(r"\d{4}-\d{2}", str(r.get(키, ""))[:7])})
    if not 달:
        raise SystemExit(f"거래일자를 읽지 못했습니다({키}). 기간을 직접 주십시오.")
    고른달 = 달[-1]
    print(f"   기간  {고른달}  (통장에 있는 달 {' · '.join(달)} 중 마지막)")
    return 고른달


def step(title, argv, 계속=False):
    """계속=True 면 실패해도 멈추지 않고 False 를 돌려준다.

    검증이 실패해도 확인사항 문서는 만들어야 무엇이 틀렸는지 볼 수 있다.
    """
    print(f"\n── {title}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable] + argv, cwd=HERE, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "").rstrip()
    if out:
        print("\n".join("   " + l for l in out.splitlines()))
    if r.returncode != 0:
        print((r.stderr or "").rstrip()[-1500:])
        if 계속:
            return False
        raise SystemExit(f"[{title}] 에서 멈췄습니다.")
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    kit = os.path.abspath(sys.argv[1])
    뒤 = list(sys.argv[2:])
    period = 뒤.pop(0) if 뒤 and 기간꼴.fullmatch(뒤[0]) else None
    prof = 뒤.pop(0) if 뒤 else "profile_glowbeam"
    out인자 = 뒤.pop(0) if 뒤 else None

    if not os.path.isdir(kit):
        raise SystemExit(f"폴더가 없습니다: {kit}")
    없는것 = [t for t in 필요한표
             if not (os.path.exists(os.path.join(kit, t + ".xlsx"))
                     or os.path.exists(os.path.join(kit, t + ".csv")))]
    if 없는것:
        raise SystemExit("표가 없습니다: " + " · ".join(없는것))

    print(f"=== 결산 · {prof}")
    print(f"   자료  {kit}")
    준비()
    if period is None:
        period = 기간찾기(kit)
    else:
        print(f"   기간  {period}")
    out = os.path.abspath(out인자) if out인자 else os.path.join(kit, f"결산_{period}")
    print(f"   산출  {out}")

    raw = os.path.join(out, "raw")
    os.makedirs(raw, exist_ok=True)

    step("1/5 표 읽어 원천 정리", [os.path.join(HERE, "glowbeam_raw.py"), kit, raw, period])
    step("2/5 분개·시산표·재무제표·더존 업로드", [os.path.join(HERE, "run_close.py"), raw, out, period, prof])
    # 검증을 문서보다 먼저 돌린다. 그래야 문서가 실제 결과를 받아쓴다.
    # FAIL 이어도 문서는 만들고(무엇이 틀렸는지 봐야 한다) 종료코드로 실패를 남긴다
    나쁨 = []
    if not step("3/5 더존 업로드 사전검증",
                [os.path.join(HERE, "verify_upload.py"), out, period, prof], 계속=True):
        나쁨.append("업로드 사전검증")
    v = step("4/5 검산", [os.path.join(HERE, "verify_close.py"),
                          os.path.join(out, f"결산확정_{period}.xlsx")], 계속=True)
    if v is False:
        나쁨.append("검산")
        v = ""
    step("5/5 확인사항(검증 결과 반영)",
         [os.path.join(HERE, "build_docx.py"), raw, out, period, prof])

    print(f"\n=== 나온 것 · {out}")
    for n in sorted(os.listdir(out)):
        p = os.path.join(out, n)
        if os.path.isfile(p):
            print(f"   {n:<44} {os.path.getsize(p)/1024:>7.0f} KB")
    if 나쁨:
        print("\n검증 실패: " + " · ".join(나쁨) + " — 확인사항 문서에 FAIL 로 적혀 있습니다.")
        raise SystemExit(1)
    print("\n" + ("검산 통과. 전문가가 보고 확정합니다."
                  if "ALL PASS" in v else "검산에서 어긋난 것이 있습니다. 확인사항을 먼저 보십시오."))


if __name__ == "__main__":
    main()
