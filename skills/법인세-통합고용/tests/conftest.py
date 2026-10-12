"""시험이 스킬 폴더의 scripts/ 를 import 경로에 올린다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
