# -*- coding: utf-8 -*-
"""전자신고 규격서(V5.17) 코드. 결과 JSON 이 처음부터 이 코드값을 쓰므로 전자신고 단계에 변환이 없다."""
import json
import os

from yangdo import RULES_DIR


class Codes:
    def __init__(self, data):
        self.data = data

    def rate_code(self, group, kind):
        sel = self.data["세율구분_선택"]
        if group == "미등기":
            return sel["미등기"]
        return sel[group][kind]

    def asset_code(self, 종류, 고가):
        t = self.data["자산종류"]
        if 종류 == "토지":
            return t["토지"]
        if 종류 == "주택":
            return t["고가주택"] if 고가 else t["일반주택"]
        return t["기타건물"]

    def tax_class(self, 전액비과세):
        return self.data["과세구분"]["비과세" if 전액비과세 else "해당없음"]

    def acq_code(self, 방법):
        return self.data["취득가액종류"].get(방법) if 방법 else None

    @staticmethod
    def period_code(years):
        return "%02d" % min(max(int(years), 0), 10)

    def _target(self, v):
        return bool(v.get("일세대일주택") and v.get("비과세"))

    def holding_code(self, v):
        return self.period_code(v["보유년"]) if self._target(v) else "ZZ"

    def residence_code(self, v):
        if not self._target(v):
            return "ZZ"
        if str(v["취득일"]) <= self.data["보유거주기간코드"]["Z1기준"]:
            return "Z1"
        if not (v.get("조정_취득일") or {}).get("지정") or v.get("공고전계약_취득"):
            return "Z2"
        return self.period_code(v["거주년"])


def load(rules_dir=None):
    with open(os.path.join(rules_dir or RULES_DIR, "코드표.json"), encoding="utf-8") as f:
        return Codes(json.load(f))
