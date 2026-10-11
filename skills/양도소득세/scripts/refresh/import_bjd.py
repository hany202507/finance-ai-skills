# -*- coding: utf-8 -*-
"""행정표준코드 법정동코드 전체자료(txt)에서 폐지여부 「존재」 행만 골라 efile/법정동코드.json 으로 쓴다.

  python scripts/refresh/import_bjd.py --입력 <법정동코드 전체자료.txt> --받은날 2026-10-11 \
      [--출력 efile/법정동코드.json] [--인코딩 cp949] [--sha256 <기대 해시>]

원자료: https://www.code.go.kr/stdcode/regCodeL.do 의 「법정동 코드 전체자료」. cp949, 탭 구분 3열
(법정동코드, 법정동명, 폐지여부「존재」/「폐지」), 첫 줄은 머리글이다. 같은 화면에서 폐지구분 「현존」으로 조회한
건수와 존재 행 수가 같아야 한다(2026-10-11 자료는 20,560).
sha256 은 줄끝을 CRLF 로 맞춘 바이트로 센다. git 의 autocrlf 때문에 체크아웃마다 줄끝이 달라도 같은 값이 나온다.
출력은 {"출처": {...}, "코드": {"1111010100": "서울특별시 종로구 청운동", ...}} 이고 코드 순서로 쓴다.
"""
import argparse
import hashlib
import json
import os
import re
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import bjd  # noqa: E402
from yangdo.dates import to_date  # noqa: E402

HEADER = ["법정동코드", "법정동명", "폐지여부"]
STATUS = ("존재", "폐지")
URL = "https://www.code.go.kr/stdcode/regCodeL.do"


class SourceError(Exception):
    pass


def convert(raw, 인코딩="cp949"):
    """원자료 바이트를 {"코드", "sha256", "자료행", "존재행"} 으로. 형식이 다르면 SourceError."""
    canon = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    try:
        text = canon.decode(인코딩)
    except UnicodeDecodeError as e:
        raise SourceError("인코딩 %s 로 읽을 수 없습니다: %s" % (인코딩, e))
    lines = text.split("\r\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0].split("\t") != HEADER:
        raise SourceError("머리글이 %s 이어야 합니다: %r" % ("\t".join(HEADER), lines[0] if lines else ""))
    seen, codes = set(), {}
    for no, line in enumerate(lines[1:], start=2):
        cols = line.split("\t")
        if len(cols) != 3:
            raise SourceError("%d째 줄은 탭으로 나뉜 3열이어야 합니다: %r" % (no, line))
        code, name, status = cols
        if not re.fullmatch(r"[0-9]{10}", code):
            raise SourceError("%d째 줄 법정동코드는 10자리 숫자여야 합니다: %r" % (no, code))
        if status not in STATUS:
            raise SourceError("%d째 줄 폐지여부는 %s 이어야 합니다: %r" % (no, "·".join(STATUS), status))
        if code in seen:
            raise SourceError("%d째 줄 법정동코드 중복: %s" % (no, code))
        seen.add(code)
        if status == "존재":
            codes[code] = name
    if not codes:
        raise SourceError("존재 행이 없습니다")
    try:
        parsed, _ = bjd.parse(codes)
    except bjd.BjdError as e:
        raise SourceError(str(e))
    codes = {c: " ".join(codes[c].split()) for c in sorted(parsed)}
    return {"코드": codes, "sha256": hashlib.sha256(canon).hexdigest(),
            "자료행": len(lines) - 1, "존재행": len(codes)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--입력", required=True)
    ap.add_argument("--출력", default=os.path.join(SKILL, "efile", bjd.TABLE_FILE))
    ap.add_argument("--받은날", required=True, help="자료를 받은 날 YYYY-MM-DD")
    ap.add_argument("--인코딩", default="cp949")
    ap.add_argument("--sha256", default=None, help="기대하는 해시. 다르면 쓰지 않는다")
    ap.add_argument("--출처URL", default=URL)
    a = ap.parse_args(argv)
    try:
        to_date(a.받은날)
        with open(a.입력, "rb") as f:
            raw = f.read()
        out = convert(raw, a.인코딩)
    except (SourceError, ValueError, OSError) as e:
        print("실패: %s" % e, file=sys.stderr)
        return 1
    if a.sha256 and a.sha256.lower() != out["sha256"]:
        print("실패: sha256 이 다릅니다. 기대 %s, 실제 %s" % (a.sha256.lower(), out["sha256"]), file=sys.stderr)
        return 1
    doc = {"출처": {"이름": "행정표준코드 법정동코드 전체자료", "URL": a.출처URL,
                  "파일명": os.path.basename(a.입력), "sha256": out["sha256"], "해시기준": "줄끝을 CRLF 로 맞춘 바이트",
                  "받은날": a.받은날, "인코딩": a.인코딩, "자료행": out["자료행"], "존재행": out["존재행"]},
           "코드": out["코드"]}
    tmp = a.출력 + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(a.출력)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, a.출력)
    except OSError as e:
        print("실패: 출력 파일을 쓰지 못했습니다(%s)" % type(e).__name__, file=sys.stderr)
        return 1
    finally:
        if os.path.exists(tmp):         # 쓰다가 실패하면 임시 파일을 남기지 않는다. 먼저 있던 출력 파일은 그대로다
            os.remove(tmp)
    print("법정동코드 %d행(자료 %d행) → %s" % (out["존재행"], out["자료행"], a.출력))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
