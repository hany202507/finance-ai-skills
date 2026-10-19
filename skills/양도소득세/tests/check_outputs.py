# -*- coding: utf-8 -*-
"""출력 폴더에 공개본이 남기는 파일만 있는지 본다. 공개본 CI 가 make_return.py 를 돌린 뒤 부른다.

  python tests/check_outputs.py <출력 폴더> 신고서     양도소득세_신고서.pdf, 지방소득세_신고서.pdf, 양도소득세_계산근거.xlsx
  python tests/check_outputs.py <출력 폴더> 계산       양도소득세_계산근거.xlsx

폴더 안의 이름(숨김 파일과 폴더 포함)이 정확히 그 목록이면 종료코드 0, 아니면 1 이다. 이름 목록은 yangdo/edition.py 에 있다.
"""
import os
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import edition  # noqa: E402

KINDS = {"신고서": edition.PUBLIC_RETURN_OUTPUTS, "계산": edition.PUBLIC_CALC_OUTPUTS}


def check(folder, kind):
    """(맞는지, 알릴 문장)."""
    want = set(KINDS[kind])
    try:
        have = set(os.listdir(folder))
    except OSError as e:
        return False, "출력 폴더를 읽지 못했다: %s (%s)" % (folder, e.strerror or e)
    if have == want:
        return True, "출력 폴더에 %s 만 있다" % ", ".join(sorted(want))
    extra, missing = sorted(have - want), sorted(want - have)
    return False, "출력 폴더의 파일이 다르다. 더 있는 것: %s. 없는 것: %s" % (", ".join(extra) or "없음", ", ".join(missing) or "없음")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[1] not in KINDS:
        print("쓰는 법: python tests/check_outputs.py <출력 폴더> 신고서|계산", file=sys.stderr)
        return 2
    ok, msg = check(args[0], args[1])
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
