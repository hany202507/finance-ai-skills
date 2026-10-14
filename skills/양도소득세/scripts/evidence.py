# -*- coding: utf-8 -*-
"""증빙 자료(매매계약서, 영수증, 세금계산서)를 목록으로 만들고, Claude 가 읽어 낸 값을 검증해 사실관계에 넣는다.

  python scripts/evidence.py inventory <증빙 폴더> --출력 <폴더>
      폴더의 파일마다 문서 id(D01...)를 붙이고 글자층 여부를 적은 증빙_목록.json 을 쓴다.
  python scripts/evidence.py apply --사실관계 facts.json --추출 증빙추출.json --목록 증빙_목록.json --출력 <폴더>
      추출 값을 원문과 대조해 통과한 것만 사실관계 파일에 넣고, 증빙_확인표.md 와 증빙_결과.json 을 쓴다.
      사실관계 파일이 없으면 자산 A 하나로 시작한다.

종료코드: 0 완료(확인필요·충돌·거절이 있어도 0, 확인표에 나온다), 2 입력 파일 오류
"""
import argparse
import json
import os
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL not in sys.path:
    sys.path.insert(0, SKILL)

from yangdo import evidence as E  # noqa: E402
from yangdo import facts as F  # noqa: E402

INVENTORY = "증빙_목록.json"
TABLE = "증빙_확인표.md"
RESULT = "증빙_결과.json"


def _write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _read(path, what):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise E.EvidenceError("%s 를 읽지 못했다: %s (%s)" % (what, path, type(e).__name__)) from e


def run_inventory(folder, out_dir):
    inv = E.inventory(folder)
    _write(os.path.join(out_dir, INVENTORY), json.dumps(inv, ensure_ascii=False, indent=1))
    return inv


def run_apply(facts_path, extractions, inv, out_dir):
    facts = _read(facts_path, "사실관계") if os.path.exists(facts_path) else {"자산": [{"id": "A"}]}
    F.check_personal(facts)
    new, rep = E.apply(facts, extractions, inv)
    F.check_personal(new)
    _write(facts_path, json.dumps(new, ensure_ascii=False, indent=1))
    _write(os.path.join(out_dir, RESULT), json.dumps(rep, ensure_ascii=False, indent=1))
    _write(os.path.join(out_dir, TABLE), E.confirm_markdown(rep, inv))
    return new, rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("inventory")
    a.add_argument("폴더")
    a.add_argument("--출력", required=True)
    b = sub.add_parser("apply")
    b.add_argument("--사실관계", required=True)
    b.add_argument("--추출", required=True)
    b.add_argument("--목록", required=True)
    b.add_argument("--출력", required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "inventory":
            inv = run_inventory(args.폴더, args.출력)
            for d in inv["문서"]:
                print("%s %s %s%s" % (d["id"], d["파일"], "글자층 있음" if d["글자층"] else "글자층 없음",
                                      "  " + d["안내"] if d["안내"] else ""))
            print("목록: %s" % os.path.join(args.출력, INVENTORY))
        else:
            inv = _read(args.목록, "증빙 목록")
            items = _read(args.추출, "증빙추출")
            _, rep = run_apply(args.사실관계, items, inv, args.출력)
            print("반영 %d, 일치 %d, 충돌 %d, 확인필요 %d, 거절 %d, 남은 문항 %d" % (
                len(rep["반영"]), len(rep["일치"]), len(rep["충돌"]), len(rep["확인필요"]), len(rep["거절"]),
                len(rep["남은문항"])))
            print("확인표: %s" % os.path.join(args.출력, TABLE))
    except (E.EvidenceError, F.FactsError) as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
