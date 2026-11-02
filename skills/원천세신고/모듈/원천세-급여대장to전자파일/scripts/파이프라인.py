"""급여대장 → 원천징수집계(엑셀·JSON) → 홈택스 전자파일(C103900) → 형식검증 한 번에.

사용: python 파이프라인.py --받은자료 <폴더> --출력 <폴더> [--귀속연월 202607 --지급연월 202607 --시트 7월]
종료코드 0 = 파일 생성 + 형식검증 통과. 그 외 = 파일을 넘기면 안 된다.
"""
import argparse, glob, json, os, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_여기 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
SK = _여기 if os.path.isdir(os.path.join(_여기, "원천세전자파일")) else os.path.join(os.path.expanduser("~"), ".claude", "skills")
작성 = os.path.join(SK, "원천징수이행상황신고서", "scripts", "작성.py")
만들기 = os.path.join(SK, "원천세전자파일", "scripts", "make_c103900.py")
검증 = os.path.join(SK, "원천세전자파일", "scripts", "validate_c103900.py")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def 실행(cmd):
    p = subprocess.run([sys.executable] + cmd, capture_output=True, text=True, encoding="utf-8", env=ENV)
    print(p.stdout + p.stderr)
    return p.returncode


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--받은자료", required=True)
    a.add_argument("--출력", required=True)
    a.add_argument("--귀속연월"); a.add_argument("--지급연월"); a.add_argument("--시트")
    a.add_argument("--계산값-생략", action="store_true", help="엑셀 재계산을 건너뛴다")
    a = a.parse_args()
    os.makedirs(a.출력, exist_ok=True)

    # 1) 급여대장 → 집계표·신고값
    cmd = [작성, "--받은자료", a.받은자료, "--출력", a.출력]
    for k in ("귀속연월", "지급연월", "시트"):
        if getattr(a, k): cmd += [f"--{k}", getattr(a, k)]
    if a.계산값_생략: cmd += ["--계산값-생략"]
    if 실행(cmd): sys.exit("1단계(신고서 작성) 실패")
    신고값 = sorted(glob.glob(os.path.join(a.출력, "신고값_*.json")), key=os.path.getmtime)[-1]

    # 2) 회사기초정보 찾기. 소재지 표기만 다르면(띄어쓰기·시도 약칭) 받은자료 원본 표기를 신고값 사본에 쓴다.
    설정 = [f for f in glob.glob(os.path.join(a.받은자료, "**", "회사기초정보*.xlsx"), recursive=True)]
    if not 설정: sys.exit("회사기초정보_<사업자번호>.xlsx 가 없다 — 원천세전자파일 스킬의 make_company_info_xlsx.py 로 빈 틀을 만들어 채운다")
    설정 = 설정[0]
    import openpyxl
    ws = openpyxl.load_workbook(설정, data_only=True).active
    원본주소 = next((r[2] for r in ws.iter_rows(values_only=True) if r[1] == "사업장 소재지"), None)
    j = json.load(open(신고값, encoding="utf-8"))
    압축 = lambda s: "".join(str(s or "").split()).replace("서울특별시", "서울")
    if 원본주소 and j["회사"].get("소재지") != 원본주소 and 압축(원본주소) == 압축(j["회사"].get("소재지")):
        j["회사"]["소재지"] = 원본주소
        신고값 = 신고값.replace(".json", "_전자파일용.json")
        json.dump(j, open(신고값, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"소재지는 받은자료 원본 표기 사용: {원본주소}")

    # 3) 전자파일 생성
    전자 = os.path.join(a.출력, "전자파일")
    if 실행([만들기, "--신고값", 신고값, "--설정", 설정, "--산출", 전자]):
        sys.exit("2단계(전자파일 생성) 실패 — 빠진 것 목록을 사용자에게 보이고 채운다")
    파일 = sorted(glob.glob(os.path.join(전자, "*C103900.0?")), key=os.path.getmtime)[-1]

    # 4) 형식검증
    if 실행([검증, 파일, "--신고값", 신고값]): sys.exit("3단계(형식검증) 실패 — 파일을 넘기지 않는다")
    print("완료:", 파일)


if __name__ == "__main__":
    main()
