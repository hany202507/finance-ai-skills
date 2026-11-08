"""스캔 PDF 를 AI 가 읽을 쪽 이미지로 만든다(300dpi, 쪽마다 위·아래 반씩 잘라 글자를 키운다).

python pdf_pages.py <PDF> <출력 폴더> [--dpi 300] [--split 2]
그 다음 AI 가 이미지를 차례로 읽어 templates/표준거래표_양식.csv 꼴로 옮겨 적고 run.py --standard 로 돌린다.
옮겨 적을 때 증권사 잔액 칸(현금잔액·외화예수금·잔고수량)을 반드시 함께 적는다. 엔진이 줄마다 잔액을
다시 계산해 대조하므로 숫자를 잘못 읽은 행이 [대사] 로 드러난다.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--split", type=int, default=2)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("pdftoppm")
    if not exe:
        raise SystemExit("pdftoppm(poppler)이 없다")
    subprocess.run([exe, "-r", str(a.dpi), "-png", a.pdf, str(out / "p")], check=True)
    from PIL import Image
    n = 0
    for p in sorted(out.glob("p-*.png")):
        im = Image.open(p)
        w, h = im.size
        # 흰 여백을 잘라 낸다
        bbox = im.convert("L").point(lambda v: 255 if v < 240 else 0).getbbox()
        if bbox:
            im = im.crop(bbox)
            w, h = im.size
        step = h // a.split
        for k in range(a.split):
            top = max(0, k * step - 40)
            im.crop((0, top, w, min(h, (k + 1) * step + 40))).save(out / f"{p.stem}_{k+1}.png")
            n += 1
    print(f"{n}장 → {out}")


if __name__ == "__main__":
    main()
