# -*- coding: utf-8 -*-
"""질문지. 정의는 질문지/문항.json 하나다.

대화 화면은 next_questions 로 다음 문항을 받고 answer 로 사실관계에 답을 넣는다. 보이는조건의 엔진값은
judge.engine_values 로 계산한다. 아직 모르는 답이나 엔진값에 걸린 문항은 묻지 않고 기다린다.

단위는 문항의 키로 정한다. 자산[] 은 자산마다, 세대.주택목록[] 은 주택마다, 세대.주택목록[신규] 는 일시적 2주택
후보 자산의 신규 주택, 나머지는 한 번이다. 세대와 주택 단위 문항은 자산이 여럿이면 자산 하나라도 보이는조건이
참일 때 묻는다(토지를 먼저 적어도 세대 문항이 나온다).
"""
import copy
import json
import os
import re
from datetime import date

from yangdo import QUESTIONS_PATH, RULES_DIR, judge, regions, ruleset
from yangdo import facts as F

MOREUM = "모름"
_DEF, _RULES = {}, {}
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, "in": lambda a, b: a in b,
       "not_in": lambda a, b: a not in b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
       "<": lambda a, b: a < b, ">": lambda a, b: a > b}


def load(path=None):
    path = path or QUESTIONS_PATH
    if path not in _DEF:
        with open(path, encoding="utf-8") as f:
            _DEF[path] = json.load(f)
    return _DEF[path]


def _rules(rules_dir):
    """규칙세트와 지역. 기준정보 판 파일이 바뀌면 다시 읽는다(오래 떠 있는 서버가 옛 판을 쓰지 않도록)."""
    d = rules_dir or RULES_DIR
    try:
        stamp = os.stat(os.path.join(d, "기준정보판.json")).st_mtime_ns
    except OSError:
        stamp = None
    key = (d, stamp)
    if stamp is None or key not in _RULES:
        loaded = (ruleset.load(rules_dir), regions.load(rules_dir))
        for old in [k for k in _RULES if k[0] == d]:
            del _RULES[old]
        _RULES[key] = loaded
    return _RULES[key]


def unit_kind(q):
    ks = q["키"]
    if any("주택목록[]." in k for k in ks):
        return "주택"
    if any("주택목록[신규]." in k for k in ks):
        return "신규"
    if any(k.startswith("자산[].") for k in ks):
        return "자산"
    return "전역"


def _split(key):
    parts = key.split(".")
    if parts[0] == "자산[]":
        return "자산", parts[1:]
    if parts[0] == "세대" and len(parts) > 1 and parts[1] in ("주택목록[]", "주택목록[신규]"):
        return "주택", parts[2:]
    return "전역", parts


def read(f, key, asset=None, house=None):
    where, parts = _split(key)
    node = {"자산": asset, "주택": house, "전역": f}[where]
    for p in parts:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
        if node is None:
            return None
    return node


def write(f, key, value, asset=None, house=None):
    where, parts = _split(key)
    node = {"자산": asset, "주택": house, "전역": f}[where]
    if node is None:
        raise ValueError("%s 를 쓸 자산이나 주택이 없다" % key)
    for p in parts[:-1]:
        if node.get(p) is None:
            node[p] = {}
        elif not isinstance(node[p], dict):
            raise ValueError("%s 의 %s 가 이미 다른 형식의 값이다" % (key, p))
        node = node[p]
    node[parts[-1]] = value


def _marker(qid, unit):
    return "%s:%s" % (qid, unit or "")


def _answered(f, q, unit, asset, house):
    if _marker(q["id"], unit) in (f.get("모름") or []):
        return True
    return any(read(f, k, asset, house) is not None for k in q["키"])


def _item(it, f, ev, asset, house, qmap):
    if isinstance(it, dict):
        return _visible(it, f, ev, asset, house, qmap)
    left, op, right = it
    if left.startswith("엔진."):
        val = ev.get(left[3:])
    else:
        q2 = qmap.get(left)
        if q2 is None or not q2["키"]:
            return None
        val = read(f, q2["키"][0], asset, house)
    if val is None:
        return None
    try:
        return bool(OPS[op](val, right))
    except TypeError:
        return None


def _visible(cond, f, ev, asset, house, qmap):
    """참, 거짓, 또는 아직 모르면 None."""
    if cond == "항상":
        return True
    if "모두" in cond:
        rs = [_item(it, f, ev, asset, house, qmap) for it in cond["모두"]]
        return False if False in rs else (None if None in rs else True)
    rs = [_item(it, f, ev, asset, house, qmap) for it in cond.get("하나라도", [])]
    return True if True in rs else (None if None in rs else False)


def context(f, rules_dir=None):
    """자산마다 보이는조건에 쓰는 엔진값."""
    rs, reg = _rules(rules_dir)
    prep = F.prepare(f)
    return {a["id"]: judge.engine_values(f, a, prep, rs, reg) for a in f.get("자산") or [] if a.get("id")}


def _units(q, f, ev):
    """(단위 id, 답을 읽고 쓸 자산, 주택, 보이는조건을 따질 [(자산, 엔진값)])."""
    kind = unit_kind(q)
    assets = [a for a in f.get("자산") or [] if a.get("id")]
    houses = F.get(f, "세대.주택목록") or []
    if kind == "자산":
        return [(a["id"], a, None, [(a, ev.get(a["id"], {}))]) for a in assets]
    if kind == "신규":
        out = []
        for a in assets:
            hid = ev.get(a["id"], {}).get("신규주택id")
            h = next((x for x in houses if x.get("id") == hid), None)
            if h is not None:
                out.append((hid, a, h, [(a, ev.get(a["id"], {}))]))
        return out
    ctx = [(a, ev.get(a["id"], {})) for a in assets] or [(None, {})]
    if kind == "주택":
        return [(h.get("id"), None, h, ctx) for h in houses]
    return [(None, None, None, ctx)]


def _describe(q, asset, house, 안내=None):
    kind = unit_kind(q)
    return {"id": q["id"], "질문": q["질문"], "도움말": q.get("도움말"), "답형식": q["답형식"],
            "선택지": copy.deepcopy(q.get("선택지")), "키": list(q["키"]),
            "자산": asset["id"] if asset is not None and kind in ("자산", "신규") else None,
            "주택": house.get("id") if house is not None and kind in ("주택", "신규") else None,
            "근거조문": copy.deepcopy(q.get("근거조문")), "증빙서류": copy.deepcopy(q.get("증빙서류")),
            "모를때확인처": copy.deepcopy(q.get("모를때확인처")), "안내": 안내}


def _address_note(q, f, asset, e, reg):
    """주소 문항에 적은 답을 고시 이력이 정하지 못하면 그 안내 문장(구 이름이 빠졌거나 모르는 시도 등).

    engine_values 는 이 경우를 삼키므로 문항 쪽에서 되묻는다. 날짜를 아직 모르거나 정할 수 있으면 None.
    """
    if q["답형식"] != "주소" or asset is None:
        return None
    addr = read(f, q["키"][0], asset)
    if not isinstance(addr, dict):
        return None
    if q["키"][0].endswith(".취득당시소재지"):
        days = [e.get("취득일")]
    else:
        days = [e.get("양도일")] + ([] if asset.get("취득당시소재지") else [e.get("취득일")])
    for on in days:
        if not on:
            continue
        try:
            reg.status(judge.CONTROL, addr, on, asset.get("지구해당"))
        except regions.NeedAnswer as ex:
            if ex.문항 == "A01":
                return ex.내용
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    return None


def next_questions(f, rules_dir=None, 서식=False, limit=1):
    """정의 순서로 아직 안 물은 보이는 문항. limit=None 이면 전부.

    이미 답한 주소를 고시 이력이 정하지 못하면 그 문항을 안내 문장과 함께 다시 낸다.
    """
    qs = load()["문항"]
    qmap = {q["id"]: q for q in qs}
    ev = context(f, rules_dir)
    reg = _rules(rules_dir)[1]
    pending = []
    for q in qs:
        if not q["키"] or (q["범위"] == "서식단계" and not 서식):
            continue
        for unit, asset, house, ctxs in _units(q, f, ev):
            note = None
            if _answered(f, q, unit, asset, house):
                if _marker(q["id"], unit) in (f.get("모름") or []):
                    continue
                note = _address_note(q, f, asset, ev.get(asset["id"], {}) if asset else {}, reg)
                if note is None:
                    continue
            if any(_visible(q["보이는조건"], f, e, a, house, qmap) is True for a, e in ctxs):
                pending.append(_describe(q, asset, house, note))
    return {"다음": pending[:limit], "남은": len(pending), "엔진값": ev}


def _is_iso(v):
    if not isinstance(v, str) or not _ISO.fullmatch(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _check_houses(qid, value, f):
    """H04. 집마다 id 가 있어야 주택 단위 문항을 답할 수 있고, 취득일은 판 집이 아니면 필요하다."""
    if not isinstance(value, list) or not all(isinstance(h, dict) for h in value):
        raise ValueError("%s 는 집마다 dict 인 목록으로 답한다" % qid)
    ids = [h.get("id") for h in value]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("%s 는 집마다 겹치지 않는 id 가 있어야 한다" % qid)
    for h in value:
        d = h.get("취득일")
        if d is None and not h.get("자산id"):
            raise ValueError("%s 의 집 %s 는 취득일이 필요하다(판 집이면 자산id 로 잇는다)" % (qid, h["id"]))
        if d is not None and not _is_iso(d):
            raise ValueError("%s 의 집 %s 취득일은 YYYY-MM-DD 로 적는다" % (qid, h["id"]))
    linked = {h.get("자산id") for h in value}
    for a in f.get("자산") or []:
        if a.get("종류") == "주택" and a.get("id") not in linked:
            raise ValueError("%s 에 판 집(자산 %s)이 없다. 자산id 로 이어 넣는다" % (qid, a.get("id")))


def _check_periods(qid, value):
    ok = isinstance(value, list) and all(
        isinstance(p, (list, tuple)) and len(p) == 2 and _is_iso(p[0]) and _is_iso(p[1]) and p[0] <= p[1]
        for p in value)
    if not ok:
        raise ValueError("%s 는 [전입일, 전출일] 구간의 목록으로 답한다. 날짜는 YYYY-MM-DD" % qid)


def _validate(q, value, f):
    qid, kind, keys = q["id"], q["답형식"], q["키"]
    codes = [o["코드"] for o in q.get("선택지") or []]
    if kind == "예아니오" and not isinstance(value, bool):
        raise ValueError("%s 는 true 또는 false 로 답한다" % qid)
    if kind == "선택" and codes:
        v = value.get("구분") if isinstance(value, dict) else value
        if v not in codes:
            raise ValueError("%s 의 답은 %s 중 하나다" % (qid, codes))
    if kind == "복수선택" and codes:
        if not isinstance(value, list) or any(v not in codes for v in value):
            raise ValueError("%s 의 답은 %s 중 고른 목록이다" % (qid, codes))
    if kind == "주소" and not (isinstance(value, dict) and all(
            isinstance(value.get(k), str) and value[k] for k in ("시도", "시군구"))):
        raise ValueError("%s 는 시도·시군구·읍면동으로 나눈 dict 로 답한다. 주소 문자열은 받지 않는다" % qid)
    if kind == "목록" and not isinstance(value, list):
        raise ValueError("%s 는 목록으로 답한다" % qid)
    if kind == "날짜":
        vals = list(value.values()) if len(keys) > 1 and isinstance(value, dict) else [value]
        if any(v is not None and not _is_iso(v) for v in vals):
            raise ValueError("%s 의 날짜는 YYYY-MM-DD 로 답한다" % qid)
    if keys[-1].endswith(".지분"):
        try:
            F.share({"지분": value})
        except F.FactsError as e:
            raise ValueError("%s: %s" % (qid, e))
    if keys == ["세대.주택목록"]:
        _check_houses(qid, value, f)
    if keys[-1].endswith(".거주기간"):
        _check_periods(qid, value)


def answer(f, qid, value, 자산=None, 주택=None):
    """답을 넣은 새 사실관계를 돌려준다. 원본은 바꾸지 않는다.

    형식이 틀린 답은 ValueError. 인적사항이나 주민등록번호 형태가 들어가면 facts.FactsError.
    """
    q = {x["id"]: x for x in load()["문항"]}.get(qid)
    if q is None:
        raise ValueError("%s 라는 문항이 없다" % qid)
    if value is None:
        raise ValueError("%s 의 답이 비었다. 모르면 MOREUM 으로 답한다" % qid)
    f2 = copy.deepcopy(f)
    kind = unit_kind(q)
    asset = next((a for a in f2.get("자산") or [] if a.get("id") == 자산), None) if 자산 else None
    if kind in ("자산", "신규") and asset is None:
        raise ValueError("%s 는 자산마다 묻는 문항이라 자산 id 가 필요하다" % qid)
    house = None
    if kind in ("주택", "신규"):
        house = next((h for h in F.get(f2, "세대.주택목록") or [] if h.get("id") == 주택), None)
        if house is None:
            raise ValueError("%s 는 주택마다 묻는 문항이라 주택 id 가 필요하다" % qid)
    unit = {"자산": 자산, "신규": 주택, "주택": 주택, "전역": None}[kind]
    marker = _marker(qid, unit)
    moreum = list(f2.get("모름") or [])
    if value == MOREUM and MOREUM not in [o["코드"] for o in q.get("선택지") or []]:
        if marker not in moreum:
            moreum.append(marker)
        f2["모름"] = moreum
        return f2
    _validate(q, value, f2)
    if len(q["키"]) == 1:
        write(f2, q["키"][0], value, asset, house)
    else:
        names = [k.rsplit(".", 1)[-1] for k in q["키"]]
        if not isinstance(value, dict):
            raise ValueError("%s 는 %s 를 이름으로 한 dict 로 답한다" % (qid, names))
        if set(value) - set(names) or all(value.get(n) is None for n in names):
            raise ValueError("%s 는 %s 중 값이 있는 것만 dict 로 답한다" % (qid, names))
        for k, last in zip(q["키"], names):
            if last in value:
                write(f2, k, value[last], asset, house)
    if marker in moreum:  # 나중에 값을 알게 되면 모름 표시를 지운다
        moreum.remove(marker)
        f2["모름"] = moreum
    F.check_personal(f2)
    return f2
