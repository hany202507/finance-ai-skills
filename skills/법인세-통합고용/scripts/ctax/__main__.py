"""스킬 꾸러미용 진입점: `python -m ctax employ <신고 건 폴더> [옵션]`."""
import sys

from ctax.employ.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv[:1] == ["employ"]:
        argv = argv[1:]
    sys.exit(main(argv))
