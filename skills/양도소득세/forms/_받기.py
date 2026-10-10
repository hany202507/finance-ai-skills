# -*- coding: utf-8 -*-
"""서식 원본 PDF 를 국가법령정보센터(law.go.kr)에서 다시 받아 `서식판.json` 의 sha256 과 대조한다.

  python forms/_받기.py            대조만 한다. 다르면 새 판이라고 알리고 파일은 그대로 둔다
  python forms/_받기.py --교체     다르면 `forms/원본/` 의 파일을 새 판으로 바꾼다

주소는 `서식판.json` 의 flSeq 로 만든다(`https://www.law.go.kr/LSW/flDownload.do?flSeq=<n>`).
받은 파일은 손대지 않고 그대로 대조한다(문서 속성도 지우지 않는다. sha256 이 받은 파일 그대로의 값이다).

새 판으로 바꾼 뒤에는 사람이 할 일이 있다. `서식판.json` 의 sha256·개정일을 고치고,
`python scripts/refresh/build_fields.py` 로 필드목록을 다시 만든 다음 시험과 렌더 결과를 눈으로 본다.
그 전까지 `tests/test_p2_skeleton.py` 의 원본 대조 시험이 실패해 바뀐 것을 알린다.

종료코드: 0 모두 같음(또는 --교체 로 바꿈), 1 새 판이 있는데 바꾸지 않음, 2 받기 실패.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://www.law.go.kr/LSW/flDownload.do?flSeq={}"


def fetch(flseq, timeout=60):
    req = urllib.request.Request(URL.format(flseq), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _replace(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def run(forms_dir=HERE, 교체=False, fetch=fetch, out=print):
    with open(os.path.join(forms_dir, "서식판.json"), encoding="utf-8") as f:
        reg = json.load(f)["서식"]
    code = 0
    for name, v in reg.items():
        try:
            data = fetch(v["flSeq"])
        except Exception as e:  # noqa: BLE001  받기 실패는 서식마다 알리고 계속한다
            out("%s: 받기 실패 (flSeq %s) %s" % (name, v["flSeq"], str(e)[:80]))
            code = 2
            continue
        if not data.startswith(b"%PDF") or len(data) < 2000:
            out("%s: PDF 가 아니다 (flSeq %s, %d 바이트)" % (name, v["flSeq"], len(data)))
            code = 2
            continue
        got = hashlib.sha256(data).hexdigest()
        if got == v["sha256"]:
            out("%s: 같음 (%s)" % (name, got[:16]))
            continue
        path = os.path.join(forms_dir, v["파일"])
        if 교체:
            _replace(path, data)
            out("%s: 새 판으로 바꿨다 %s → %s. 서식판.json 을 고치고 build_fields.py 를 다시 돌린다"
                % (name, v["sha256"][:16], got[:16]))
        else:
            out("%s: 새 판이 있다 %s → %s. 파일은 그대로 두었다(--교체 로 바꾼다)"
                % (name, v["sha256"][:16], got[:16]))
            code = max(code, 1)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description="서식 원본을 다시 받아 sha256 을 대조한다")
    ap.add_argument("--교체", action="store_true", help="다르면 원본 파일을 바꾼다")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    return run(교체=a.교체)


if __name__ == "__main__":
    sys.exit(main())
