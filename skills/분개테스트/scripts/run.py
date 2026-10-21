# -*- coding: utf-8 -*-
"""분개테스트 실행기. 분개장 엑셀로 분개 테스트(3600-JET) 조서를 만든다.

    python run.py <분개장.xlsx> [<분개장2.xlsx> ...] --fy-end 2025-12-31 [--fy-start 2025-01-01]
                  [--after <결산일 후 분개장.xlsx>] [--tb <회사제시 시산표 · 재무제표.xlsx>] [--pm 수행중요성] [--company 회사]
                  --out <결과 폴더>

결과 폴더에 「3600-JET_분개테스트.xlsx」 와 작업용 감사 폴더(_감사폴더)가 남는다. 엔진이 분개장을 읽고 시험 스무 가지와 분포 분석을 낸다.
걸린 전표가 정상 거래인지는 회계사가 결과 목록의 검토 결과 칸에 적는다. 엔진은 부정 여부를 정하지 않는다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("AUDIT_OCR", "off")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _force(func, path, exc):
    """rmtree 가 지우지 못한 파일 · 폴더 하나의 읽기 전용 속성을 풀고 잠깐씩 기다리며 다시 지운다. OneDrive 동기화 폴더는 하위 폴더마다
    읽기 전용 속성이 붙어 os.rmdir 이 WinError 5 로 멈춘다(2026-10-21 부트캠프). 끝내 안 되면 마지막 오류를 그대로 올린다."""
    err = exc[1] if isinstance(exc, tuple) else exc
    if func not in (os.rmdir, os.unlink, os.remove) or not isinstance(err, PermissionError):
        raise err
    for wait in (0, 0.2, 0.5, 1.0):
        time.sleep(wait)
        try:
            os.chmod(path, stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IWRITE)
            func(path)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            err = e
    raise err


def _work_dir(out: Path) -> Path:
    """작업용 감사 폴더. 지난 실행이 남긴 _감사폴더는 지우고 새로 만든다. 그래도 못 지우면 _감사폴더_<시각> 에 만들고 출력에 한 줄 알린다."""
    d = out / "_감사폴더"
    if not d.exists():
        return d
    try:
        shutil.rmtree(d, **{"onexc" if sys.version_info >= (3, 12) else "onerror": _force})
        return d
    except OSError as e:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        alt, n = out / f"_감사폴더_{stamp}", 2
        while alt.exists():
            alt, n = out / f"_감사폴더_{stamp}_{n}", n + 1
        print(f"알림: 지난 실행의 _감사폴더를 지우지 못해({type(e).__name__}: {e}) 이번 작업 폴더는 {alt.name} 입니다. 옛 _감사폴더는 탐색기에서 지워도 됩니다.")
        return alt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="분개테스트")
    ap.add_argument("journals", nargs="+", help="당기 분개장 엑셀(여러 개면 모두)")
    ap.add_argument("--fy-end", required=True)
    ap.add_argument("--fy-start", default=None)
    ap.add_argument("--after", nargs="*", default=[], help="결산일 후 분개장(기말 후 취소 · 역분개 시험)")
    ap.add_argument("--tb", default=None, help="회사제시 시산표 또는 재무제표 엑셀(손익계정 완전성 대사)")
    ap.add_argument("--pm", type=float, default=None, help="수행중요성(결산일 근처 큰 금액 시험의 기준). 비우면 그 시험은 기준 칸을 비워 둔다")
    ap.add_argument("--company", default="회사")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    from audit import folder, index
    from audit.workpapers import jet

    out = Path(a.out).resolve()
    d = _work_dir(out)
    folder.scaffold(d, a.company, a.fy_end, fiscal_year_start=a.fy_start)
    rec = d / "00 받은자료"
    for p in list(a.journals) + list(a.after):
        shutil.copy2(p, rec / "분개장" / Path(p).name)
    if a.tb:
        shutil.copy2(a.tb, rec / "회사제시" / Path(a.tb).name)
    index.read_all(d, use_ocr=False)
    # 수행중요성은 늘 명령에서 받는다. 비우면 그 값을 쓰는 시험은 「수행중요성이 없어」 메모를 남긴다(2026-10-21: 예전에는 감사 엔진의 중요성 계산으로
    # 넘어가 이 스킬에 없는 모듈을 찾다가 멈췄다)
    ctx = {"mat": {"performance": a.pm, "trivial": None, "basis": "명령 --pm" if a.pm else "수행중요성 없음", "candidate": False, "candidates": []}}
    try:
        r = jet.make(d, ctx, force=True)
    except Exception as e:  # noqa: BLE001
        print(f"멈춤: {type(e).__name__}: {e}")
        return 1
    src = Path(r["path"])
    if not src.is_absolute():
        src = (Path.cwd() / src) if (Path.cwd() / src).exists() else d / src
    dst = out / "3600-JET_분개테스트.xlsx"
    shutil.copy2(src, dst)
    run = r["run"]
    print(f"분개장 {run['lines']:,}행 · 차변 {run['dr']:,.0f} · 대변 {run['cr']:,.0f}")
    for t in run["tests"]:
        print(f"  {t['id']} {t['title']}: {len(t['hits'])}건" + (f" ({t['note']})" if t.get("note") else ""))
    an = run["analyses"]
    bf, mo = an["benford"], an["monthly"]
    print(f"  분석 첫 자리 분포: 줄 {bf['n']:,}개 · MAD " + ("-" if bf["mad"] is None else f"{bf['mad']:.4f}") + f" · {bf['verdict']}")
    print("  분석 월별 매출: 결산월 = " + ("-" if mo["ye_ratio"] is None else f"월평균의 {mo['ye_ratio']:.2f}배") + (" (표시)" if mo["flag"] else ""))
    multi = jet.multi_hits(run)
    print(f"  여러 시험에 걸린 전표: {len(multi)}건" + "".join(f" · {e['voucher'].no}({len(e['titles'])}개)" for e in multi[:5]))
    print(f"조서: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
