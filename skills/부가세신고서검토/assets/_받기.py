# -*- coding: utf-8 -*-
"""부가가치세 신고 서식 원본을 국가법령정보센터(law.go.kr)에서 다시 받는다.

  python assets/_받기.py          별지 제21호서식만 받아 이 폴더의 PDF 를 바꾼다
  python assets/_받기.py --all    부속 서식 15종도 assets/서식/ 에 받는다(참고용)

이 폴더의 `별지21호_일반과세자_부가가치세신고서.pdf` 는 부가가치세법 시행규칙
별지 제21호서식 <개정 2026. 3. 20.> 원본에서 문서 속성(작성자 등)만 지운 것이다.
`scripts/form21_pdf.py` 가 이 PDF 를 깔고 값만 써 넣는다.

서식이 개정되면 이 스크립트로 새 판을 받는다. 다만 칸 위치가 바뀌었을 수 있으니
`python -m pytest tests` 와 make_return.py 결과 PDF 를 눈으로 한 번 확인한다.

링크는 법제처 서식 목록이 주는 다운로드 주소(flSeq)를 그대로 쓴다. 주소를 조립하지 않는다.
개정으로 flSeq 가 바뀌면 국가법령정보센터에서 「부가가치세법 시행규칙」 별표·서식을
열어 새 번호로 고친다.
"""
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))

MAIN = ("21", "일반과세자_부가가치세신고서", 162619805)

OTHERS = [
    ("38", "매출처별_세금계산서합계표", 162619955),
    ("39", "매입처별_세금계산서합계표", 162619965),
    ("16", "신용카드매출전표등_수령명세서", 162619767),
    ("23", "신용카드매출전표등_발행금액집계표", 162619829),
    ("22", "공제받지못할_매입세액명세서", 162619821),
    ("27", "건물등_감가상각자산_취득명세서", 162619855),
    ("15", "의제매입세액_공제신고서", 162619759),
    ("19", "대손세액_공제변제신고서", 162619789),
    ("40", "수출실적명세서", 162619975),
    ("41", "내국신용장_구매확인서_전자발급명세서", 162619983),
    ("29", "영세율_매출명세서", 162619873),
    ("14의4", "매입자발행세금계산서합계표", 162619745),
    ("24", "전자화폐결제명세서", 162619835),
    ("25", "부동산임대공급가액명세서", 162619841),
    ("소득29", "매출처별_매입처별_계산서합계표", 164444021),
]


def sniff(b):
    if b[:4] == b"%PDF":
        return "pdf"
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "hwp"
    if b[:2] == b"PK":
        return "hwpx"
    return "bin"


def fetch(seq):
    url = f"https://www.law.go.kr/LSW/flDownload.do?flSeq={seq}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def strip_meta(path):
    """문서 속성(작성자·작성 프로그램)을 지운다. 서식 본문은 그대로다."""
    try:
        import fitz
    except ImportError:
        return
    tmp = path + ".tmp"
    with fitz.open(path) as d:
        d.del_xml_metadata()
        d.set_metadata({})
        d.save(tmp, garbage=4, deflate=True)
    os.replace(tmp, path)


def save(folder, no, name, seq):
    data = fetch(seq)
    if len(data) < 2000:
        raise ValueError(f"너무 작음 {len(data)}B")
    ext = sniff(data)
    fn = os.path.join(folder, f"별지{no}호_{name}.{ext}")
    with open(fn, "wb") as f:
        f.write(data)
    if ext == "pdf":
        strip_meta(fn)
    return fn, len(data)


def main(argv):
    ok, bad = [], []
    jobs = [(HERE, *MAIN)]
    if "--all" in argv:
        sub = os.path.join(HERE, "서식")
        os.makedirs(sub, exist_ok=True)
        jobs += [(sub, *f) for f in OTHERS]
    for folder, no, name, seq in jobs:
        try:
            ok.append(save(folder, no, name, seq))
        except Exception as e:  # noqa: BLE001
            bad.append((name, str(e)[:80]))
    print(f"받음 {len(ok)}건 / 실패 {len(bad)}건")
    for fn, n in ok:
        print(f"  {os.path.basename(fn):<52} {n:>9,}B")
    for n, e in bad:
        print(f"  실패 {n}: {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
