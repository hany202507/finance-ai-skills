# -*- coding: utf-8 -*-
"""받은 자료가 어디에 무엇으로 있는지 찾는다. 계산은 하지 않는다.

입력은 셋 가운데 하나다.
  로컬 폴더       그 폴더와 한두 단계 아래 폴더(받은자료 · 이번달사건 등)를 본다
  로컬 파일       급여대장 엑셀 하나. 그 파일이 든 폴더를 본다
  Google Drive 링크  여기서는 내려받지 않는다. 링크에서 폴더 · 파일 id 를 뽑아 돌려주고,
                  Claude 가 세션의 Drive 커넥터로 내려받은 뒤 그 폴더로 다시 부른다
"""
import base64
import json
import re
from pathlib import Path

키트이름 = {"hr_card.csv": ("hr_card.csv", "인사카드.csv"),
            "pay_contract.csv": ("pay_contract.csv", "급여계약.csv"),
            "pay_item_rule.csv": ("pay_item_rule.csv", "항목규칙.csv", "급여항목규칙.csv")}
_달 = re.compile(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])")
_드라이브 = re.compile(r"^https?://(drive|docs)\.google\.com/", re.I)


class 확인필요(Exception):
    """사실 하나가 없어서 멈출 때. 문장을 그대로 사용자에게 묻는다."""


def 달(이름):
    """파일 이름에서 YYYY-MM. 없으면 None."""
    m = _달.search(이름)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def 드라이브링크(s):
    """Drive · Docs 링크면 {"종류", "id"}, 아니면 None. 종류를 링크로 못 가르면 「모름」."""
    s = str(s).strip()
    if not _드라이브.match(s):
        return None
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", s)
    if m:
        return {"종류": "폴더", "id": m.group(1)}
    m = re.search(r"/(?:file|document|spreadsheets|presentation)/d/([A-Za-z0-9_-]{10,})", s)
    if m:
        return {"종류": "파일", "id": m.group(1)}
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", s)
    if m:
        return {"종류": "모름", "id": m.group(1)}
    raise 확인필요(f"Drive 링크에서 폴더나 파일 id 를 못 찾았습니다: {s}")


def 풀기(base64글, 저장경로):
    """Drive 커넥터의 download_file_content 가 준 base64 글을 파일로 쓴다. 앞뒤 공백 · 줄바꿈은 무시한다."""
    글 = re.sub(r"\s+", "", str(base64글))
    if 글.startswith("{"):                       # 도구 응답 JSON 을 통째로 붙였을 때
        d = json.loads(글)
        글 = d.get("content") or d.get("base64Content") or d.get("data") or ""
    바이트 = base64.b64decode(글)
    p = Path(저장경로)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(바이트)
    if p.suffix.lower() in (".xlsx", ".xlsm", ".docx") and not 바이트.startswith(b"PK"):
        raise 확인필요(f"{p.name} 이 엑셀 · 워드 파일이 아닙니다. 구글 시트면 xlsx 로 내보내 받아 주세요")
    return p


def _파일들(뿌리, 깊이=2):
    뿌리 = Path(뿌리)
    out = []
    for p in sorted(뿌리.rglob("*")):
        rel = p.relative_to(뿌리)
        if len(rel.parts) > 깊이 + 1 or not p.is_file():
            continue
        if p.name.startswith(("~$", ".")) or any(x.startswith("신고_") or x in ("결과", "__pycache__") for x in rel.parts[:-1]):
            continue
        out.append(p)
    return out


def 찾기(입력):
    """입력 폴더(또는 파일)에서 쓸 자료를 찾는다. 고르지 못하는 것은 후보 목록으로 남긴다."""
    p = Path(입력)
    if not p.exists():
        raise 확인필요(f"{입력} 이 없습니다. 폴더 경로나 Google Drive 링크를 주세요")
    지정대장 = p if p.is_file() else None
    폴더 = p.parent if p.is_file() else p
    파일 = _파일들(폴더)

    대장 = {}
    for f in 파일:
        if f.suffix.lower() in (".xlsx", ".xlsm", ".xls") and ("급여대장" in f.name or "payroll" in f.name.lower()):
            대장.setdefault(달(f.name), []).append(f)
    if 지정대장:
        대장 = {달(지정대장.name): [지정대장]}

    키트 = {}
    for 표준, 이름들 in 키트이름.items():
        후보 = [f for f in 파일 if f.name.lower() in 이름들]
        if 후보:
            키트[표준] = 후보[0]

    기초 = [f for f in 파일 if f.suffix.lower() == ".xlsx" and any(m in f.name for m in ("회사기초정보", "기초정보", "회사정보"))]
    추가행 = {}
    for f in 파일:
        if f.name.startswith("추가행_") and f.suffix == ".json":
            추가행.setdefault(달(f.name), []).append(f)
    return {
        "폴더": 폴더,
        "급여대장": 대장,                     # {"YYYY-MM": [경로]}
        "급여대장json": {달(f.name): f for f in 파일 if f.name.startswith("급여대장_") and f.suffix == ".json"},
        "키트": 키트 if len(키트) == 3 else {},
        "키트일부": sorted(키트) if 0 < len(키트) < 3 else [],
        "근태": {달(f.name): f for f in 파일 if "근태" in f.name and f.suffix.lower() == ".xlsx"},
        "회사기초정보": 기초,
        "추가행": 추가행,
        "기타소득목록": [f for f in 파일 if f.suffix.lower() == ".csv" and "기타소득" in f.name],
        "근로계약서": [f for f in 파일 if f.suffix.lower() == ".docx" and "근로계약" in f.name],
        "글": [f for f in 파일 if f.suffix.lower() in (".txt", ".md") and "README" not in f.name],
    }


def 요약(찾음):
    """사용자에게 보일 한 덩어리 글."""
    폴더 = 찾음["폴더"]
    r = lambda f: f.relative_to(폴더).as_posix()
    줄 = [f"폴더: {폴더}"]
    줄.append("급여대장: " + (", ".join(f"{k or '달 모름'} {r(v[0])}" + (f" 외 {len(v) - 1}개" if len(v) > 1 else "")
                                     for k, v in sorted(찾음["급여대장"].items(), key=lambda x: x[0] or "")) or "없음"))
    줄.append("인사카드 · 급여계약 · 항목규칙: " + ("있음 " + r(찾음["키트"]["hr_card.csv"].parent) if 찾음["키트"]
                                       else ("일부만 있음(" + ", ".join(찾음["키트일부"]) + ")" if 찾음["키트일부"] else "없음")))
    줄.append("회사기초정보: " + (", ".join(r(f) for f in 찾음["회사기초정보"]) or "없음"))
    줄.append("받은 자료의 추가행: " + (", ".join(r(f) for v in 찾음["추가행"].values() for f in v) or "없음"))
    if 찾음["기타소득목록"]:
        줄.append("기타소득 목록: " + ", ".join(r(f) for f in 찾음["기타소득목록"]))
    if 찾음["근로계약서"]:
        줄.append("근로계약서: " + ", ".join(r(f) for f in 찾음["근로계약서"]))
    if 찾음["글"]:
        줄.append("읽어 볼 글: " + ", ".join(r(f) for f in 찾음["글"]))
    return "\n".join(줄)
