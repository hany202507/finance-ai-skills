# -*- coding: utf-8 -*-
"""scripts 디렉토리를 sys.path에 추가 — 테스트가 모듈을 bare import."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "모듈", "원천세", "scripts"))
