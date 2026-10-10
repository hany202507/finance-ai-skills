# -*- coding: utf-8 -*-
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "scripts"), os.path.join(ROOT, "scripts", "refresh"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
