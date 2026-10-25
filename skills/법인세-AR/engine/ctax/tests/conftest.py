"""ctax 시험 공용. 고객 자료 없이 합성 신고 건 폴더를 만든다."""
import pytest


@pytest.fixture
def case_dir(tmp_path):
    """빈 신고 건 폴더 `<tmp>/가상회사/2025 법인세/` 와 받은자료 폴더."""
    root = tmp_path / "가상회사" / "2025 법인세"
    (root / "00 받은자료" / "전기").mkdir(parents=True)
    return root
