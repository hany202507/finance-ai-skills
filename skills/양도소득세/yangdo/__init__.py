# -*- coding: utf-8 -*-
"""양도소득세 엔진 패키지. 외부를 조회하지 않고 rules/ 의 기준정보만 읽는다."""
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(SKILL_DIR, "rules")
QUESTIONS_PATH = os.path.join(SKILL_DIR, "질문지", "문항.json")
첫양도일 = "2025-01-01"
