"""시연 회사(academy-product ctax demo --with-errors)처럼 전기 PDF 없이 합성 전기.json(`synthetic: true`)만 있으면 engine 명령이
전기 읽기 단계를 건너뛴다(2026-10-25). 전기.json 이 없거나 합성 표시가 없으면 전처럼 PDF 를 읽으러 간다."""
import json

from bestar import pipeline


def test_synthetic_prior_flag(tmp_path):
    case = tmp_path / "회사" / "2025 법인세"
    (case / "_색인").mkdir(parents=True)
    assert pipeline._synthetic_prior(str(case)) is False
    (case / "_색인" / "전기.json").write_text(json.dumps({"synthetic": True, "cells": {}}), encoding="utf-8")
    assert pipeline._synthetic_prior(str(case)) is True
    (case / "_색인" / "전기.json").write_text(json.dumps({"pdf": "x.pdf", "cells": {}}), encoding="utf-8")
    assert pipeline._synthetic_prior(str(case)) is False
