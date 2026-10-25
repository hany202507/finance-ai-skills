"""시험 공용. 엔진(engine/ctax)과 스킬(bestar)을 불러올 수 있게 한다. 고객 자료는 쓰지 않는다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "engine", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
