# -*- coding: utf-8 -*-
"""급여대장(또는 인사카드 · 급여계약 · 항목규칙 csv)에서 원천세 신고 파일까지.

    python scripts/실행.py 신고 <폴더|파일|Drive 링크> [--연월 2026-07] [--지급연월 2026-07] [--출력 <폴더>]
    python scripts/실행.py 퇴사 <폴더> --사번 E002 --퇴사일 2026-07-31 --월통상임금 3600000 [--입사일 --생년월일]
    python scripts/실행.py 기타 <폴더> [--목록 기타소득_지급목록.csv]
    python scripts/실행.py 계약서 <근로계약서.docx> --입사일 2026-08-01
    python scripts/실행.py 틀 <폴더>                 회사기초정보 빈 틀
    python scripts/실행.py 링크 <Drive 링크>         폴더 · 파일 id
    python scripts/실행.py 풀기 <base64 글 파일> <저장 경로>
    python scripts/실행.py 샘플 [작업 폴더]          샘플회사(가상) 2026년 7월을 끝까지 돌린다(샘플 자료가 있는 판만)

종료코드  0 끝 · 1 형식검증 실패(파일을 넘기지 않는다) · 2 사실이 모자라 멈춤(표준오류 문장을 그대로 묻는다)
          3 Drive 링크라 내려받아야 함
작업 폴더는 <폴더>/신고_YYYY-MM 이다. 급여대장 · 받은자료 · 결과 · 추가행이 그 안에 생긴다.
"""
import argparse
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
스킬 = 여기.parent
모듈 = 스킬 / "모듈"
sys.path.insert(0, str(여기))
import 입력 as 입  # noqa: E402

확인필요 = 입.확인필요
파이프라인 = 모듈 / "원천세-급여대장to전자파일" / "scripts" / "파이프라인.py"
틀만들기 = 모듈 / "원천세전자파일" / "scripts" / "make_company_info_xlsx.py"
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

기초정보질문 = [
    "1. 홈택스에 로그인하는 ID(세무대리인이 올리면 대리인 ID)",
    "2. 사업자등록번호 · 상호 · 대표자 성명 · 사업장 소재지",
    "3. 신고 종류(정기 · 수정 · 기한후, 보통 정기)와 납부 주기(매월 · 반기)",
    "4. 세무대리인 명의로 신고하는지(예면 대리인 사업자번호 · 성명 · 관리번호 · 전화번호)",
    "5. 세무프로그램 업체코드(없으면 9000)",
    "6. 본점 일괄납부 · 사업자단위과세 · 이번 달 소득처분 신고 가운데 해당하는 것(보통 모두 아니오)",
    "7. 환급받을 은행과 계좌(환급신청할 때만)",
    "8. 사업장 전화번호 · 전자메일(비워도 접수된다)",
]


def _모듈(이름, 하위):
    p = str(모듈 / 하위 / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    return __import__(이름)


def _실행(cmd):
    p = subprocess.run([sys.executable] + [str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV)
    return p.returncode, p.stdout + p.stderr


# ── 회사기초정보 ─────────────────────────────────────────
def 빈틀(폴더):
    경로 = Path(폴더) / "회사기초정보_작성.xlsx"
    if not 경로.exists():
        코드, 글 = _실행([틀만들기, 경로])
        if 코드:
            raise RuntimeError(글)
    return 경로


def _기초정보(찾음):
    기초 = 찾음["회사기초정보"]
    if not 기초:
        틀 = 빈틀(찾음["폴더"])
        raise 확인필요("회사기초정보가 없습니다. 빈 틀을 만들었습니다: " + str(틀) + "\n아래를 한 번에 물어 노란 값 칸에 적고 다시 돌리세요.\n"
                       + "\n".join(기초정보질문))
    if len(기초) > 1:
        raise 확인필요("회사기초정보 후보가 여럿입니다: " + ", ".join(f.name for f in 기초) + ". 하나만 두세요")
    회사정보 = _모듈("회사정보", "원천징수이행상황신고서")
    try:
        회사, *_ = 회사정보.읽기(기초[0])
    except 회사정보.확인필요 as e:
        raise 확인필요(f"{기초[0].name}: {e}\n빈 칸은 아래를 한 번에 물어 채웁니다.\n" + "\n".join(기초정보질문))
    틀읽기 = _모듈("make_company_info_xlsx", "원천세전자파일")
    try:                                     # 전자파일 단계가 같은 파일을 읽을 수 있는지 신고서를 만들기 전에 본다
        틀읽기.read(기초[0])
    except Exception as e:
        틀 = 빈틀(찾음["폴더"])
        raise 확인필요(f"전자파일 단계가 {기초[0].name} 을 읽지 못했습니다({e}). 빈 틀을 만들었습니다: {틀}\n"
                       "값을 틀의 노란 셀에 옮겨 적고 원래 파일을 치운 뒤 다시 돌리세요")
    return 기초[0], 회사


# ── 급여대장 ─────────────────────────────────────────────
def 대장만들기(찾음, 연월, 회사, 출력, 지급연월=None):
    """키트 csv 로 그 달 급여대장 엑셀 · JSON 을 만든다. 지급 달이 귀속 달과 다르면 간이세액표는 지급 달로 고른다."""
    급 = _모듈("run", "급여대장")
    키트 = 찾음["키트"]["hr_card.csv"].parent
    if any(찾음["키트"][k].name != k for k in 찾음["키트"]):      # 한글 이름 csv 는 표준 이름으로 모은다
        모음 = Path(출력) / "_키트"
        모음.mkdir(parents=True, exist_ok=True)
        for 표준, f in 찾음["키트"].items():
            shutil.copyfile(f, 모음 / 표준)
        키트 = 모음
    근태 = 찾음["근태"].get(연월)
    try:
        세액기준일 = f"{지급연월}-01" if 지급연월 and 지급연월 != 연월 else None
        r = 급.run(키트, 연월, Path(출력) / "급여대장", 근태=str(근태) if 근태 else None, 회사=회사["상호"],
                  세액기준일=세액기준일)
    except Exception as e:                               # 급여대장 모듈의 확인필요 · 마스터 빠짐
        raise 확인필요(f"{연월} 급여대장을 만들다 멈췄습니다: {e}")
    return Path(r["엑셀"]), r


def _대장(찾음, 연월, 회사, 출력, 지급연월=None):
    있는 = 찾음["급여대장"].get(연월) or []
    if not 있는 and list(찾음["급여대장"]) == [None]:      # 이름에 달이 없는 대장 하나뿐이면 --연월 의 달로 읽는다
        있는 = 찾음["급여대장"][None]
    if len(있는) > 1:
        raise 확인필요(f"{연월} 급여대장 후보가 여럿입니다: {', '.join(f.name for f in 있는)}. 하나만 두세요")
    if 있는:
        return 있는[0], "받은 급여대장", {"확인": [], "뺀사람": []}
    if 찾음["키트"]:
        경로, r = 대장만들기(찾음, 연월, 회사, 출력, 지급연월)
        확인 = [{"성명": x.성명, "내용": g} for x in r["행들"] for g in x.근거 if g.startswith("확인필요")]
        뺀 = [{"성명": n, "까닭": w} for n, w in r["뺀사람"]]
        return 경로, "인사카드 · 급여계약 · 항목규칙으로 만든 급여대장", {"확인": 확인, "뺀사람": 뺀}
    if 찾음["키트일부"]:
        raise 확인필요("인사카드 · 급여계약 · 항목규칙 csv 가운데 " + ", ".join(찾음["키트일부"]) + " 만 있습니다. 셋이 다 있어야 급여대장을 만듭니다")
    raise 확인필요(f"{연월} 급여대장이 없고 인사카드 · 급여계약 · 항목규칙 csv 도 없습니다. 둘 가운데 하나를 폴더에 넣어 주세요")


def _연월(찾음, 연월):
    if 연월:
        if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", 연월):
            raise 확인필요(f"--연월 은 2026-07 꼴로 적습니다: {연월}")
        return 연월
    달들 = sorted(k for k in 찾음["급여대장"] if k)
    if len(달들) == 1:
        return 달들[0]
    if len(달들) > 1:
        raise 확인필요("급여대장이 여러 달입니다: " + ", ".join(달들) + ". 신고할 귀속 달을 --연월 2026-07 처럼 정해 주세요")
    if None in 찾음["급여대장"]:
        raise 확인필요("급여대장 파일 이름에 달이 없습니다. 신고할 귀속 달을 --연월 2026-07 처럼 정해 주세요")
    raise 확인필요("신고할 귀속 달을 정해 주세요(--연월 2026-07)")


# ── 추가행 ───────────────────────────────────────────────
def _추가행읽기(경로들):
    행들 = []
    for p in 경로들:
        for r in json.loads(Path(p).read_text(encoding="utf-8")):
            행들 = [q for q in 행들 if not (q["성명"] == r["성명"] and q["소득코드"] == r["소득코드"])] + [r]
    return 행들


def 추가행저장(작업, 연월, 새행들):
    p = Path(작업) / f"추가행_{연월}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    행들 = _추가행읽기([p] if p.exists() else [])
    for r in 새행들:
        행들 = [q for q in 행들 if not (q["성명"] == r["성명"] and q["소득코드"] == r["소득코드"])] + [r]
    p.write_text(json.dumps(행들, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


# ── 신고 ─────────────────────────────────────────────────
def 신고(입력, 연월=None, 지급연월=None, 출력=None, 계산값=True):
    링크 = 입.드라이브링크(입력)
    if 링크:
        return {"종료": 3, "링크": 링크}
    찾음 = 입.찾기(입력)
    print(입.요약(찾음), flush=True)
    기초, 회사 = _기초정보(찾음)
    연월 = _연월(찾음, 연월)
    작업 = Path(출력) if 출력 else 찾음["폴더"] / f"신고_{연월}"
    대장, 출처, 대장정보 = _대장(찾음, 연월, 회사, 작업, 지급연월)

    받은 = 작업 / "받은자료"
    if 받은.exists():
        shutil.rmtree(받은)
    받은.mkdir(parents=True)
    shutil.copyfile(대장, 받은 / f"급여대장_{연월}{대장.suffix}")
    shutil.copyfile(기초, 받은 / (기초.name if 기초.name.startswith("회사기초정보") else f"회사기초정보_{회사['사업자번호']}.xlsx"))
    추가 = list(찾음["추가행"].get(연월, [])) + ([작업 / f"추가행_{연월}.json"] if (작업 / f"추가행_{연월}.json").exists() else [])
    추가 = list(dict.fromkeys(Path(p).resolve() for p in 추가))
    추가행 = _추가행읽기(추가)
    신고추가 = [p for p in 추가 if 작업.resolve() in p.parents]
    if 신고추가:
        print("신고 폴더의 추가행(퇴사 · 기타 명령이 쓴 것): " + ", ".join(p.relative_to(작업.resolve()).as_posix() for p in 신고추가)
              + f" · 모두 {len(추가행)}행", flush=True)
    if 추가행:
        (받은 / f"추가행_{연월}.json").write_text(json.dumps(추가행, ensure_ascii=False, indent=1), encoding="utf-8")

    결과 = 작업 / "결과"
    if 결과.exists():
        shutil.rmtree(결과)
    cmd = [파이프라인, "--받은자료", 받은, "--출력", 결과, "--귀속연월", 연월.replace("-", "")]
    if 지급연월:
        cmd += ["--지급연월", 지급연월.replace("-", "")]
    if not 계산값:
        cmd += ["--계산값-생략"]
    코드, 글 = _실행(cmd)
    (작업 / "실행기록.txt").write_text(글, encoding="utf-8")
    요약 = _요약(결과, 연월, 대장, 출처, 추가행, 글, 코드)
    요약["급여대장확인"] = 대장정보["확인"]
    요약["급여대장뺀사람"] = 대장정보["뺀사람"]
    요약["알림"] = []
    if 찾음["기타소득목록"] and not any(str(r["소득코드"]).startswith("A4") or r["소득코드"] == "A59" for r in 추가행):
        요약["알림"].append("기타소득 목록(" + ", ".join(f.name for f in 찾음["기타소득목록"]) + ")이 있는데 「기타」 명령을 돌리지 않아 "
                          "이 신고에 들어가지 않았습니다. 「기타」를 먼저 돌리고 다시 신고하세요")
    환급 = _환급까닭(json.loads(Path(요약["신고값"]).read_text(encoding="utf-8"))) if 요약.get("신고값") else None
    if 요약["종료"] == 1 and 환급:
        요약.setdefault("멈춘까닭", []).insert(0, 환급)
    (결과 / "요약.json").parent.mkdir(parents=True, exist_ok=True)
    (결과 / "요약.json").write_text(json.dumps(요약, ensure_ascii=False, indent=1), encoding="utf-8")
    return 요약


def _환급까닭(값):
    """가감계 소득세가 음수(환급)인 달. 환급세액을 ⑮일반환급 · 조정환급 가운데 어디에 적을지는 사람이 정한다."""
    음수 = [c[0] for c in 값.get("명세", []) if c[0] in ("A10", "A20", "A30", "A40", "A99") and c[3] < 0]
    if not 음수:
        return None
    return (f"{' · '.join(음수)} 소득세가 음수(환급)입니다. 환급 달은 환급세액을 ⑮일반환급 · 조정환급 가운데 어디에 적을지 "
            "사람이 정해야 해서 이 스킬은 전자파일을 넘기지 않습니다. 홈택스에서 직접 작성하세요")


def _요약(결과, 연월, 대장, 출처, 추가행, 글, 코드):
    신고값 = sorted(glob.glob(str(결과 / "신고값_*.json")))
    값 = json.loads(Path([p for p in 신고값 if "_전자파일용" not in p][0]).read_text(encoding="utf-8")) if 신고값 else None
    파일 = sorted(glob.glob(str(결과 / "전자파일" / "*C103900.0?")))
    m = re.search(r"검사 (\d+)개 · 통과 (\d+) · 실패 (\d+)", 글)
    요약 = {"종료": 0 if 코드 == 0 else (1 if m else 2), "귀속연월": 연월, "급여대장": str(대장), "급여대장출처": 출처,
            "추가행": [{"성명": r["성명"], "소득코드": r["소득코드"], "총지급액": r["총지급액"], "소득세": r["소득세"]} for r in 추가행],
            "전자파일": 파일[-1] if 파일 else None,
            "형식검증": {"검사": int(m.group(1)), "통과": int(m.group(2)), "실패": int(m.group(3))} if m else None,
            "실행기록": str(결과.parent / "실행기록.txt")}
    if 값:
        요약["소득코드별"] = [{"코드": c[0], "인원": c[1], "총지급액": c[2], "소득세": c[3], "납부세액": c[7]} for c in 값["명세"]]
        a99 = next((c for c in 값["명세"] if c[0] == "A99"), None)
        요약["납부세액"] = a99[7] if a99 else 0
        요약["위택스_지방소득세"] = 값.get("위택스_지방소득세")
        요약["기한"] = 값["기간"].get("_실제기한")
        요약["기한비고"] = 값["기간"].get("_이월사유")
        요약["확인사항"] = 값.get("확인사항", [])
        요약["집계표"] = next(iter(sorted(glob.glob(str(결과 / "원천징수집계_*.xlsx")))), None)
        요약["신고값"] = [p for p in 신고값 if "_전자파일용" not in p][0]
    if 코드 and not m:
        요약["멈춘까닭"] = [줄 for 줄 in 글.splitlines() if 줄.strip()][-8:]
    return 요약


def 보고(요약):
    if 요약.get("종료") == 3:
        l = 요약["링크"]
        print(f"Drive 링크입니다({l['종류']} id {l['id']}). Drive 커넥터로 파일을 내려받아 한 폴더에 두고 그 폴더로 다시 돌리세요.")
        return
    print()
    if 요약.get("종료") == 1:
        print("형식검증에 실패했습니다. 전자파일을 넘기지 않습니다. 실패 줄은 실행기록에 있습니다.")
    elif 요약.get("종료"):
        print("멈췄습니다. 전자파일을 만들지 못했습니다. 아래 까닭을 사용자에게 보이고 고친 뒤 다시 돌립니다.")
    if 요약.get("소득코드별"):
        if 요약.get("종료"):
            print("(아래 표는 신고서 단계까지 나온 값입니다)")
        print(f"{'코드':<5}{'인원':>5}{'총지급액':>16}{'소득세':>14}{'납부세액':>14}")
        for c in 요약["소득코드별"]:
            print(f"{c['코드']:<5}{c['인원']:>5}{c['총지급액']:>16,}{c['소득세']:>14,}{c['납부세액']:>14,}")
        print(f"납부할 소득세 {요약['납부세액']:,}원 · 위택스 지방소득세 {요약['위택스_지방소득세']:,}원 · 기한 {요약['기한']}"
              + (f" ({요약['기한비고']})" if 요약.get("기한비고") else ""))
    if 요약.get("형식검증"):
        f = 요약["형식검증"]
        print(f"형식검증 {f['검사']}개 · 통과 {f['통과']} · 실패 {f['실패']}  (파일 형식만 본다. 세액과 소득 구분이 맞는지는 보지 않는다)")
    if 요약.get("전자파일"):
        print("전자파일:", 요약["전자파일"])
    빈 = [x["항목"] for x in 요약.get("확인사항", []) if not x.get("정한값")]
    if 요약.get("확인사항"):
        print(f"확인사항 {len(요약['확인사항'])}건" + (" · 아직 안 정한 것: " + ", ".join(빈) if 빈 else ""))
    if 요약.get("급여대장뺀사람"):
        print("급여대장에서 뺀 사람: " + ", ".join(f"{x['성명']}({x['까닭']})" for x in 요약["급여대장뺀사람"]))
    if 요약.get("급여대장확인"):
        print(f"급여대장 확인필요 {len(요약['급여대장확인'])}건")
        for x in 요약["급여대장확인"]:
            print(f"  {x['성명']}: {x['내용']}")
    for 줄 in 요약.get("알림", []):
        print("알림: " + 줄)
    for 줄 in 요약.get("멈춘까닭", []):
        print("  " + 줄)
    print("요약:", Path(요약["실행기록"]).parent / "결과" / "요약.json")


# ── 퇴사 · 기타 · 계약서 ─────────────────────────────────
def _카드(찾음, 사번):
    if not 찾음["키트"]:
        return {}
    with open(찾음["키트"]["hr_card.csv"], encoding="utf-8-sig", newline="") as f:
        return next((r for r in csv.DictReader(f) if r.get("사번") == 사번), {})


def 퇴사(폴더, 사번, 퇴사일, 월통상임금, 입사일=None, 생년월일=None, 지급연월=None, 소득공제신고=None, 제외항목=("CAR",),
         임금3개월=None, IRP이전=None):
    입퇴사 = _모듈("입퇴사", "입퇴사처리")
    찾음 = 입.찾기(폴더)
    카드 = _카드(찾음, 사번)
    입사일 = 입사일 or 카드.get("입사일")
    생년월일 = 생년월일 or 카드.get("생년월일")
    빠진 = [n for n, v in (("입사일", 입사일), ("생년월일", 생년월일)) if not v]
    if 빠진:
        raise 확인필요(f"{사번} 의 {' · '.join(빠진)} 이 인사카드에 없습니다. --{빠진[0]} 처럼 적어 주세요")
    if 월통상임금 is None:
        raise 확인필요("월 통상임금을 알려 주세요(--월통상임금). 기본급으로 대신하지 않습니다. 고정 수당이 들어가면 퇴직금이 달라집니다")
    연, 월 = int(퇴사일[:4]), int(퇴사일[5:7])
    지급연월 = 지급연월 or 퇴사일[:7]
    작업 = 찾음["폴더"] / f"신고_{지급연월}"
    대장폴더 = 작업 / "급여대장"
    첫 = int(입사일[5:7]) if int(입사일[:4]) == 연 else 1      # 그해 입사자는 입사한 달부터 대장이 있다
    필요 = [f"{연}-{m:02d}" for m in range(첫, 월 + 1)]
    없는 = [m for m in 필요 if not (대장폴더 / f"급여대장_{m}.json").exists()]
    if 없는:
        if 찾음["키트"]:
            _, 회사 = _기초정보(찾음) if 찾음["회사기초정보"] else (None, {"상호": "(회사)"})
            for m in 없는:
                대장만들기(찾음, m, 회사, 작업)
        else:
            있는 = 찾음["급여대장json"]
            모자람 = [m for m in 없는 if m not in 있는]
            if 모자람:
                raise 확인필요("퇴사 정산에는 1월(그해 입사자는 입사월)부터 퇴사월까지 이 스킬이 만든 급여대장 JSON 이 있어야 합니다. 없는 달: "
                               + ", ".join(모자람) + ". 인사카드 · 급여계약 · 항목규칙 csv 를 주시면 만듭니다")
            대장폴더.mkdir(parents=True, exist_ok=True)
            for m in 없는:
                shutil.copyfile(있는[m], 대장폴더 / f"급여대장_{m}.json")
    try:
        r = 입퇴사.퇴사처리(대장폴더, 사번, 입사일, 퇴사일, 생년월일, int(월통상임금), 소득공제신고=소득공제신고, 제외항목=tuple(제외항목),
                         임금3개월=임금3개월, IRP이전=IRP이전)
    except 입퇴사.확인필요 as e:
        raise 확인필요(str(e))
    r["추가행파일"] = str(추가행저장(작업, 지급연월, r["추가행"]))
    (작업 / f"퇴사_{사번}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def 기타(폴더, 목록=None):
    입퇴사 = _모듈("입퇴사", "입퇴사처리")
    찾음 = 입.찾기(폴더)
    if not 목록:
        if len(찾음["기타소득목록"]) != 1:
            raise 확인필요("기타소득 지급 목록 csv 를 정해 주세요(--목록). 후보: " + (", ".join(f.name for f in 찾음["기타소득목록"]) or "없음"))
        목록 = 찾음["기타소득목록"][0]
    with open(목록, encoding="utf-8-sig", newline="") as f:
        줄 = list(csv.DictReader(f))
    달들 = sorted({str(x.get("지급일", ""))[:7] for x in 줄})
    if len(달들) != 1 or not re.fullmatch(r"20\d{2}-\d{2}", 달들[0]):
        raise 확인필요("지급일의 달이 하나여야 합니다(신고 달이 지급일로 정해집니다): " + ", ".join(달들))
    try:
        행들 = 입퇴사.기타소득처리(줄)
    except 입퇴사.확인필요 as e:
        raise 확인필요(str(e))
    작업 = 찾음["폴더"] / f"신고_{달들[0]}"
    return {"연월": 달들[0], "추가행": 행들, "추가행파일": str(추가행저장(작업, 달들[0], 행들))}


def 계약서(경로, 입사일):
    입퇴사 = _모듈("입퇴사", "입퇴사처리")
    r = 입퇴사.입사처리(경로, 입사일)
    r.pop("계약서글", None)
    return r


def 샘플(작업=None, 계산값=True):
    """설치 확인. 샘플회사(가상) 폴더를 복사해 퇴사 · 기타소득 · 신고를 차례로 돌린다. 퇴사 값은 퇴사통보.txt 에 적힌 것이다."""
    작업 = Path(작업 or "급여대장_원천세신고_샘플")
    폴더 = 작업 / "샘플회사"
    if 폴더.exists():
        shutil.rmtree(폴더)
    원본 = 스킬 / "examples" / "샘플회사"
    if not 원본.exists():
        raise 확인필요("이 판에는 샘플 자료(examples/샘플회사)가 없습니다. 자기 회사 자료 폴더로 「신고」 를 돌리세요")
    shutil.copytree(원본, 폴더)
    퇴 = 퇴사(폴더, "E002", "2026-07-31", 3_600_000)
    print(f"퇴사 E002: 퇴직금 {퇴['퇴직금']['퇴직금']:,}원({퇴['퇴직금']['적용']} 기준) · 퇴직소득세 {퇴['퇴직소득세']['징수세액']:,}원 · "
          f"중도정산 {퇴['중도정산']['정산세액']:,}원")
    기 = 기타(폴더)
    print("기타소득: " + ", ".join(f"{r['성명']} {r['소득코드']} {r['총지급액']:,}원 · 소득세 {r['소득세']:,}원" for r in 기["추가행"]))
    return 신고(폴더, "2026-07", 계산값=계산값)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="급여대장에서 원천세 신고 파일까지")
    sub = ap.add_subparsers(dest="일", required=True)
    s = sub.add_parser("신고"); s.add_argument("입력"); s.add_argument("--연월"); s.add_argument("--지급연월")
    s.add_argument("--출력"); s.add_argument("--재계산생략", action="store_true", help="엑셀 재계산을 건너뛴다(시험용)")
    t = sub.add_parser("퇴사"); t.add_argument("폴더"); t.add_argument("--사번", required=True)
    t.add_argument("--퇴사일", required=True); t.add_argument("--월통상임금", type=int)
    t.add_argument("--입사일"); t.add_argument("--생년월일"); t.add_argument("--지급연월")
    t.add_argument("--소득공제신고", help="근로소득자 소득공제 신고 내용 JSON 파일")
    t.add_argument("--제외항목", default="CAR", help="퇴직금 임금 총액에서 뺄 항목코드, 쉼표로. 빈 값이면 다 넣는다")
    t.add_argument("--임금3개월", type=int, help="평균임금 산정 기간 임금 총액. 월 중 퇴사면 일할로 정해 준다")
    t.add_argument("--IRP이전", choices=("Y", "N"), help="퇴직금을 IRP 로 보냈는가. 주지 않으면 55세 미만은 Y 로 본다")
    g = sub.add_parser("기타"); g.add_argument("폴더"); g.add_argument("--목록")
    c = sub.add_parser("계약서"); c.add_argument("경로"); c.add_argument("--입사일", required=True)
    b = sub.add_parser("틀"); b.add_argument("폴더")
    l = sub.add_parser("링크"); l.add_argument("링크")
    u = sub.add_parser("풀기"); u.add_argument("글파일"); u.add_argument("저장")
    m = sub.add_parser("샘플"); m.add_argument("작업", nargs="?"); m.add_argument("--재계산생략", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.일 in ("신고", "샘플"):
            r = (신고(a.입력, a.연월, a.지급연월, a.출력, 계산값=not a.재계산생략) if a.일 == "신고"
                 else 샘플(a.작업, 계산값=not a.재계산생략))
            보고(r)
            return r["종료"]
        if a.일 == "퇴사":
            신고서 = json.loads(Path(a.소득공제신고).read_text(encoding="utf-8")) if a.소득공제신고 else None
            r = 퇴사(a.폴더, a.사번, a.퇴사일, a.월통상임금, a.입사일, a.생년월일, a.지급연월, 신고서,
                     tuple(k for k in a.제외항목.split(",") if k), 임금3개월=a.임금3개월,
                     IRP이전=None if a.IRP이전 is None else a.IRP이전 == "Y")
        elif a.일 == "기타":
            r = 기타(a.폴더, a.목록)
        elif a.일 == "계약서":
            r = 계약서(a.경로, a.입사일)
        elif a.일 == "틀":
            r = {"틀": str(빈틀(a.폴더)), "물을것": 기초정보질문}
        elif a.일 == "링크":
            r = 입.드라이브링크(a.링크) or {"종류": "링크 아님"}
        else:
            r = {"저장": str(입.풀기(Path(a.글파일).read_text(encoding="utf-8"), a.저장))}
    except 확인필요 as e:
        print(f"멈췄습니다: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
