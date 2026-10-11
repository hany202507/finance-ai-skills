# -*- coding: utf-8 -*-
import json
import os
import shutil
from decimal import Decimal

import pytest

from yangdo import SKILL_DIR, keys
from yangdo import ruleset as R

RS = R.load()


def test_every_key_present_from_start():
    for k in keys.VALUE_KEYS + keys.CITE_KEYS:
        start = keys.LATE_KEYS.get(k, "2025-01-01")
        for on in (start, "2026-10-09", "2027-12-31"):
            RS.entry(k, on)
            assert RS.cite(k, on), k


def test_spot_values():
    assert RS.value("기본공제", "2026-10-09") == 2500000
    assert RS.value("고가주택기준", "2025-01-01") == 1200000000
    assert RS.value("기본세율", "2026-10-09")[-1] == [1000000000, 384060000, Decimal("0.45")]
    assert RS.value("지방.기본세율", "2026-10-09")[-1] == [1000000000, 38406000, Decimal("0.045")]
    assert RS.value("장특공.표2.거주", "2026-10-09")[0] == [2, Decimal("0.08")]
    assert RS.value("단기.주택.2년미만", "2026-10-09") == Decimal("0.60")


def test_history_values():
    assert RS.value("중과.한시배제.가목.양도기한", "2025-01-15") == "2025-05-09"
    assert RS.value("중과.한시배제.가목.양도기한", "2026-01-01") == "2026-05-09"
    assert RS.value("일시적2주택.처분기한.일반", "2026-09-30") == 3
    assert RS.value("일시적2주택.처분기한.일반", "2026-11-01") == 3
    assert RS.value("일시적2주택.처분기한.조정", "2026-11-01") == 2
    assert RS.value("일시적2주택.조정기한.신규취득시작", "2025-06-01") == "2026-08-04"


def test_disposal_extension_cites_every_item_of_paragraph_18():
    """확인사항이 시행령 제155조⑱ 의 1호부터 5호까지(현금청산소송은 4호 또는 5호)를 부르므로 근거 발췌에 다섯 호의 문구가 다 있어야 한다."""
    for on in ("2025-01-01", "2026-10-09"):
        cites = RS.cite("판정.처분기한연장", on)
        assert [c["조항"] for c in cites] == ["제155조⑱"]
        excerpts = cites[0]["발췌"]
        for want in ("한국자산관리공사에 매각을 의뢰한 경우",
                     "법원에 경매를 신청한 경우",
                     "「국세징수법」에 따른 공매가 진행 중인 경우",
                     "현금청산금 지급을 구하는 소송절차가 진행 중인 경우 또는 소송절차는 종료되었으나 해당 청산금을 지급받지 못한 경우",
                     "수용재결 또는 매도청구소송 절차가 진행 중인 경우 또는 재결이나 소송절차는 종료되었으나 토지등소유자가 해당 매도대금 등을 지급받지 못한 경우"):
            assert want in excerpts, want


def test_pending_amendment_note():
    assert any(n.startswith("계류") for n in RS.notes("중과.2주택", "2026-06-01"))
    assert not any(n.startswith("계류") for n in RS.notes("중과.2주택", "2026-05-09"))


def test_cites_have_urls_and_versions():
    for k in keys.VALUE_KEYS + keys.CITE_KEYS:
        on = keys.LATE_KEYS.get(k, "2026-10-09")
        for c in RS.cite(k, on):
            assert c["URL"].startswith("https://www.law.go.kr/법령/") and c["시행일"], k


# ---- 기준정보 판이 서식 매핑과 필드목록까지 덮는다(계획 2b G7) ----

FORM_TABLES = ("매핑", "필드목록")


def _form_table_keys():
    return ["../forms/%s/%s" % (sub, name) for sub in FORM_TABLES
            for name in sorted(os.listdir(os.path.join(SKILL_DIR, "forms", sub))) if name.endswith(".json")]


def test_edition_covers_form_mapping_and_field_lists():
    """신고값을 서식 칸에 잇는 매핑과 칸 좌표 목록이 바뀌면 신고서가 달라진다. 폴더의 모든 JSON 이 판 묶음과 판 파일에 있어야 한다."""
    keys_ = _form_table_keys()
    assert len(keys_) == 9
    with open(os.path.join(R.RULES_DIR, "기준정보판.json"), encoding="utf-8") as f:
        files = json.load(f)["파일"]
    for k in keys_:
        assert k in R.EDITION_EXTRA, k
        assert files.get(k) == R.canonical_hash(os.path.join(R.RULES_DIR, k)), k


def test_changed_mapping_file_is_caught_when_rules_load(tmp_path):
    """매핑 파일을 고치고 판을 다시 만들지 않으면 규칙세트를 읽을 때 멈춘다."""
    rules, forms = tmp_path / "rules", tmp_path / "forms"
    shutil.copytree(R.RULES_DIR, str(rules), ignore=shutil.ignore_patterns("조문"))
    for sub in FORM_TABLES:
        shutil.copytree(os.path.join(SKILL_DIR, "forms", sub), str(forms / sub))
    R.load(str(rules))                                      # 서식판·전자신고 묶음이 없는 사본은 그 파일을 대조하지 않는다
    target = forms / "매핑" / "본지.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data["_시험"] = "바꿈"
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(R.RuleError, match="본지.json"):
        R.load(str(rules))
    R.write_edition(str(rules), "2026-10-11")               # 판을 다시 만들면 읽힌다
    R.load(str(rules))
