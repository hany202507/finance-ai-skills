# -*- coding: utf-8 -*-
"""합성 사례의 사실관계 파일과 신고인 파일을 폴더에 쓴다. SKILL.md 「시험해 보기」의 두 줄을 한 번에 하는 스크립트다.

  python tests/sample_inputs.py A sample          sample/a.json, sample/a_신고인.json 을 쓴다
  python scripts/make_return.py --사실관계 sample/a.json --신고인 sample/a_신고인.json --출력 out --오늘 2026-12-20

사실관계는 tests/cases.py, 신고인 정보는 tests/filers.py 의 합성값이다. 실제 사람이나 주소와 관계없다.
CI 가 이 스크립트로 입력을 만들어 make_return.py 를 끝까지 돌린다(.github/workflows/test.yml).
쓴 파일 경로와, 그 사례의 작성일(--오늘 로 줄 날짜)을 한 줄씩 낸다.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import filers  # noqa: E402
from cases import CASES  # noqa: E402


def write(name, folder):
    """사례 name 의 입력 두 파일을 folder 에 쓴다. (사실관계 경로, 신고인 경로, 작성일)."""
    if name not in filers.FILERS or name not in CASES:
        raise SystemExit("합성 신고인이 있는 사례가 아니다: %s (있는 사례: %s)" % (name, ", ".join(sorted(filers.FILERS))))
    os.makedirs(folder, exist_ok=True)
    filer = filers.get(name)
    paths = (os.path.join(folder, "%s.json" % name.lower()), os.path.join(folder, "%s_신고인.json" % name.lower()))
    for path, data in zip(paths, (CASES[name], filer)):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    return paths[0], paths[1], filer["신고"]["작성일"]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("쓰는 법: python tests/sample_inputs.py <사례 이름> <폴더>", file=sys.stderr)
        return 2
    facts, filer, made = write(args[0], args[1])
    print(facts)
    print(filer)
    print(made)
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(main())
