"""설치 확인: 이 스킬이 쓰는 프로그램과 패키지가 있는지 본다. 거래 자료는 읽지 않는다.

python scripts/check_env.py

| 필요 | 무엇에 | 없으면 |
|---|---|---|
| 파이썬 3.10 이상, openpyxl · xlrd · pdfplumber · pikepdf | 엑셀 · 글자 있는 PDF 읽기, 암호 PDF 풀기, 업로드 · 검증 파일 쓰기 | 실행 안 됨 |
| Node.js(npx) | kordoc 으로 PDF 읽기(첫 후보) | pdfplumber 로만 읽는다 |
| requirements-ocr.txt 패키지 | 스캔 PDF · 화면 캡처 | 스캔본을 못 읽는다 |
| 인터넷(한국은행 ECOS) | 환율표 받기(fetch_rates.py) | 환율표를 직접 만들어 넣는다 |

엑셀이나 LibreOffice 는 필요 없다(2026-11-08 부터 업로드 · 검증 파일을 엔진 값으로 쓴다).
"""
import importlib
import shutil
import sys

# 미래에셋 거래내역증명서 · 키움 PDF 는 암호가 걸려 온다. pikepdf 가 없으면 열지 못한다(2026-11-09)
CORE = ("openpyxl", "xlrd", "pdfplumber", "pikepdf")


def ok(b):
    return "있음" if b else "없음"


def has(mod):
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    py = sys.version_info >= (3, 10)
    core = {m: has(m) for m in CORE}
    ocr = {m: has(m) for m in ("cv2", "numpy", "PIL", "rapidocr", "onnxruntime")}
    npx = bool(shutil.which("npx") or shutil.which("npx.cmd"))
    rows = [
        ("파이썬 3.10 이상", ok(py), "필수"),
        *[(f"패키지 {m}", ok(v), "필수") for m, v in core.items()],
        ("Node.js(npx, kordoc)", ok(npx), "선택: PDF 첫 후보"),
        ("OCR 패키지(requirements-ocr.txt)", ok(all(ocr.values())), "선택: 스캔 PDF · 캡처 이미지"),
    ]
    w = max(len(r[0]) for r in rows)
    for name, v, note in rows:
        print(f"{name.ljust(w)}  {v}  {note}")
    need = py and all(core.values())
    print()
    if not need:
        print("필수 항목이 빠졌다. 스킬 폴더에서 pip install -r requirements.txt 를 실행한다")
        return 1
    print("준비됨. 증권사 거래내역 파일 하나로 시작한다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
