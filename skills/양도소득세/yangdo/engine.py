# -*- coding: utf-8 -*-
"""사실관계 JSON 하나로 판정·계산·검산까지. run.py 와 mcp_server.py 가 이 함수를 부른다."""
import datetime as dt

from yangdo import calc, codes, judge, regions, ruleset, verify, workbook
from yangdo import facts as F

STALE_DAYS = 7


def today_seoul():
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).date().isoformat()


def _dedupe(xs):
    out = []
    for x in xs:
        if x not in out:
            out.append(x)
    return out


def _load_rules(rules_dir):
    """기준정보가 깨졌으면 무엇이 원인이든 RuleError 로 돌려준다(실행 스크립트가 종료코드 3 으로 구분한다)."""
    try:
        return ruleset.load(rules_dir), regions.load(rules_dir), codes.load(rules_dir)
    except ruleset.RuleError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ruleset.RuleError("기준정보를 읽지 못했다: %s" % e) from e


def _malformed(e):
    return F.FactsError("사실관계의 값을 처리하지 못했다(%s: %s). 날짜는 YYYY-MM-DD, 금액은 원 단위 정수, 목록 모양은 질문지 문항.json 의 facts키 대로인지 확인하라"
                        % (type(e).__name__, e))


def calculate(f, rules_dir=None, today=None, workbook_path=None):
    """판정·계산·검산. 인적사항이 있거나 값의 형식이 틀리면 facts.FactsError, 기준정보가 깨졌으면 ruleset.RuleError."""
    rs, reg, cd = _load_rules(rules_dir)
    today = today or today_seoul()
    stale = (dt.date.fromisoformat(today) - dt.date.fromisoformat(rs.확인일)).days > STALE_DAYS
    out = {"상태": "질문", "기준정보": {"판": rs.판id, "확인일": rs.확인일, "오늘": today, "낡음": stale},
           "질문": [], "다루지않음": [], "확인사항": [], "경고": [], "계산": None, "검산": []}
    if stale:
        out["경고"].append("기준정보 확인일 %s 이 오늘(%s)보다 7일 넘게 지났다. 기준정보를 갱신한 뒤 다시 계산하라" % (rs.확인일, today))
    F.check_personal(f)
    if not f.get("자산"):
        out["질문"].append(F.Missing("P02", None, "양도한 자산이 하나도 없습니다. 판 부동산의 종류와 소재지부터 알려 주세요").to_dict())
        return out
    try:
        prep = F.prepare(f)
        out["질문"] += prep["질문"]
        out["다루지않음"] += prep["다루지않음"]
        out["확인사항"] += prep["확인사항"]
        if out["질문"] or out["다루지않음"]:
            return out
        j = judge.judge(f, prep, rs, reg)
        out["질문"] += j["질문"]
        out["다루지않음"] += j["다루지않음"]
        if out["질문"] or out["다루지않음"]:
            return out
        try:
            res = calc.annual(f, j["자산"], rs, cd)
        except F.Missing as m:
            out["질문"].append(m.to_dict())
            return out
        except calc.Unsupported as u:
            out["다루지않음"].append({"자산": None, "내용": str(u), "계획": u.계획})
            return out
    except (ValueError, TypeError, KeyError) as e:  # 날짜 형식이나 자료형이 틀린 값. 기준정보 오류와 구분한다
        raise _malformed(e) from e
    fails = verify.check(res, f, rs)
    if workbook_path:
        workbook.write(res, workbook_path)
        fails += verify.check_workbook(workbook_path, res)
    for v in j["자산"]:
        out["확인사항"] += ["%s: %s" % (v["id"], m) for m in v["확인사항"]]
        out["경고"] += ["%s: %s" % (v["id"], w) for w in v["경고"]]
    out["확인사항"] = _dedupe(out["확인사항"] + res["확인사항"])
    out["경고"] = _dedupe(out["경고"])
    out.update(상태="완료" if not fails else "검산실패", 계산=res, 검산=fails)
    return out
