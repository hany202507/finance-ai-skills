"""조서가 함께 쓰는 꼴: 조정 줄(`Adj`), 원장 검토 줄(`LineRow`), 조서 한 장(`Paper`).

숫자는 각 조서 파일(`papers/<id>.py`)의 `compute` 에서만 만든다. 노란 칸(회계사 입력)의 값은 `Paper.take` 로 읽는다.
회계사 값이 엔진 기본값과 다르면 `overridden` 에 남아 조정.json papers[].inputs 로 간다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .books import Books, Line

# 15호 소득처분 코드(신고본에 찍힌 꼴): 가산 100 상여 · 200 배당 · 300 기타소득 · 400 유보 · 500 기타사외유출 · 600 기타,
# 차감 100 유보 · 200 기타.
DISPOSITION_CODE = {("가산", "상여"): "100", ("가산", "배당"): "200", ("가산", "기타소득"): "300",
                    ("가산", "유보"): "400", ("가산", "기타사외유출"): "500", ("가산", "기타"): "600",
                    ("차감", "유보"): "100", ("차감", "기타"): "200"}
DISPOSITIONS = {"가산": ["유보", "기타사외유출", "상여", "배당", "기타소득", "기타"], "차감": ["유보", "기타"]}


@dataclass
class Adj:
    side: str            # 가산 · 차감
    subject: str         # 15호 과목(장부 계정 이름)
    amount: int
    disposition: str
    kind: str            # 조정 종류(짧은 이름)
    note: str            # 15호 부표 조정내용
    key: str             # 금액이 든 values 키(엑셀 링크용)
    reserve_subject: str | None = None   # 50호(을) 과목
    reserve_col: str | None = None       # 증가 · 감소
    reserve_sign: int = 1                # 50호(을)에 적는 부호

    @property
    def code(self) -> str:
        return DISPOSITION_CODE.get((self.side, self.disposition), "")

    @property
    def reserve(self) -> bool:
        return self.disposition == "유보"

    def json(self, paper: str | None = None) -> dict:
        d = {"side": self.side, "subject": self.subject, "amount": self.amount, "disposition": self.disposition,
             "code": self.code, "reserve": self.reserve, "kind": self.kind, "note": self.note}
        if paper:
            d = {"paper": paper, **d}
        return d


@dataclass
class LineRow:
    line: Line
    label: str            # 엔진이 본 분류
    pick: str             # 노란 칸 1(부인 여부 · 분류 · 차량)
    pick2: str = ""       # 노란 칸 2(비용 구분)
    why: str = ""
    key: str = ""         # 입력 칸 key 에 쓰는 줄 열쇠(일자 · 전표 · 계정 · 금액)
    default: str = ""     # 엔진이 고른 노란 칸 1 값
    default2: str = ""    # 엔진이 고른 노란 칸 2 값


@dataclass
class Paper:
    id: str
    no: str
    name: str
    status: str = "작성"
    values: dict = field(default_factory=dict)
    adjustments: list[Adj] = field(default_factory=list)
    issues: list[int] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confirm: list[str] = field(default_factory=list)
    lines: list[LineRow] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)       # 노란 칸에 쓸 지금 값(회계사 값이 있으면 그 값)
    defaults: dict = field(default_factory=dict)     # 노란 칸의 엔진 기본값
    overridden: dict = field(default_factory=dict)   # key → {"value", "default"} (회계사 값)
    checks: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def sheet(self) -> str:
        return f"{self.no} {self.name}"

    def live_adjustments(self) -> list[Adj]:
        return [a for a in self.adjustments if a.amount]

    def json(self) -> dict:
        return {"id": self.id, "no": self.no, "name": self.name, "sheet": self.sheet, "status": self.status,
                "values": self.values, "inputs": self.overridden,
                "adjustments": [a.json() for a in self.live_adjustments()],
                "issues": self.issues, "forms": self.forms, "notes": self.notes + self.confirm}

    def settle(self, has_amounts: bool) -> None:
        if not has_amounts:
            self.status = "해당 없음"
        elif self.confirm:
            self.status = "확인 필요"
        else:
            self.status = "작성"

    # 회계사 입력 ------------------------------------------------------------------------------------
    def take(self, b: Books, key: str, default, kind: str = "text"):
        """노란 칸 값. 회계사 값(조서입력.json)이 있으면 그 값, 없으면 엔진 기본값. `inputs` · `defaults` 에 남긴다."""
        default = normalize(default, kind)
        got = b.override(self.id, key)
        value = default if got is MISSING else normalize(got, kind)
        self.defaults[key] = default
        self.inputs[key] = value
        if got is not MISSING and value != default:
            self.overridden[key] = {"value": value, "default": default}
        return value

    def take_lines(self, b: Books, pick: str, pick2: str = "", kind: str = "pick") -> None:
        """원장 검토 줄마다 노란 칸(`pick` · `pick2`) 회계사 값을 반영한다. 줄 열쇠는 `line_keys` 가 붙인다."""
        line_keys(self)
        for r in self.lines:
            r.default, r.default2 = r.pick, r.pick2
            if pick:
                r.pick = self.take(b, f"{pick}/{r.key}", r.pick, kind)
            if pick2:
                r.pick2 = self.take(b, f"{pick2}/{r.key}", r.pick2, "text")
        # 줄 단위 기본값은 inputs 에 두지 않는다(값이 너무 많다). 회계사 값은 overridden 에 남는다.
        for r in self.lines:
            for label in (pick, pick2):
                if label:
                    self.inputs.pop(f"{label}/{r.key}", None)
                    self.defaults.pop(f"{label}/{r.key}", None)


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()


def normalize(v, kind: str):
    """엑셀에서 읽은 값을 칸 종류에 맞춘다. pick 은 O · X 대문자, int 는 정수, ratio 는 소수, year 는 4자리 글."""
    if kind == "int":
        if v in (None, ""):
            return 0
        try:
            return int(round(float(str(v).replace(",", ""))))
        except ValueError:
            return 0
    if kind == "ratio":
        if v in (None, ""):
            return 0.0
        try:
            x = float(str(v).replace(",", "").rstrip("%"))
        except ValueError:
            return 0.0
        return x / 100 if isinstance(v, str) and str(v).strip().endswith("%") else x
    if kind == "year":
        if v in (None, ""):
            return ""
        s = str(v).strip()
        try:
            return str(int(float(s)))
        except ValueError:
            return s
    s = "" if v is None else str(v).strip()
    if kind == "pick":
        s = s.upper()
    return s


def line_keys(p: Paper) -> None:
    """원장 검토 줄 열쇠: 일자|전표|계정|금액, 같은 것이 또 있으면 #2 · #3."""
    seen: dict[str, int] = {}
    for r in p.lines:
        ln = r.line
        base = f"{ln.date}|{ln.no}|{ln.account}|{ln.amount}"
        n = seen.get(base, 0) + 1
        seen[base] = n
        r.key = base if n == 1 else f"{base}#{n}"


def subject_of(accts: list[dict], default: str) -> str:
    return accts[0]["name"] if accts else default


def fs_sum(accts: list[dict]) -> int:
    return sum(int(a.get("amount") or 0) for a in accts)
