"""조서가 읽는 입력(장부.json · 전표.csv · 전기.json · AR.json)과 세율표를 한데 묶는다."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from pathlib import Path

import yaml

from ..case import MissingInput

RATES_FILE = Path(__file__).with_name("rates_2025.yaml")


RATES_DIR = Path(__file__).with_name("rates_2025")   # 3회차: 조서마다 `rates_2025/<id>.yaml` 한 파일(CONTRACT.md 15절)

# 사업연도별 세율 표(11-03). rates_2025.yaml(+ rates_2025/)이 첫 표이고 2025 앞 사업연도도 이 표를 쓴다(이전과 같음).
# 2026 부터는 rates_<연도>.yaml 이 앞 해 표 위에 바뀐 항목만 얹는다. 그 해 판으로 확인하지 못한 항목은 앞 해 값을 쓰되
# 등급을 ☆ 로 낮추고 근거 앞에 「<연도> 판 미확인」 을 붙인다. 표가 없는 해는 NoRates 로 멈춘다.
FIRST_YEAR = 2025
META = ("fy", "since", "base", "checked", "source")


class NoRates(MissingInput):
    """그 사업연도에 쓸 세율 표(rates_<연도>.yaml)가 없다. 조서를 만들지 않는다."""


def rates_year(fy_start: str | None) -> int:
    """사업연도 개시일(YYYY-MM-DD)이 속한 해. 비었거나 2025 앞이면 2025."""
    head = str(fy_start or "")[:4]
    return max(int(head), FIRST_YEAR) if head.isdigit() else FIRST_YEAR


def prior_start(fy_start: str | None) -> str:
    """직전 사업연도 개시일(1년 앞). 결손금 소급공제가 직전 사업연도 세율을 쓴다(법인세법 제72조 제1항 제2호)."""
    s = str(fy_start or "")
    return f"{int(s[:4]) - 1}{s[4:]}" if s[:4].isdigit() else ""


def load_rates(path: Path = RATES_FILE, *, fy_start: str | None = None) -> dict:
    """세율 · 한도 표. fy_start(사업연도 개시일)가 2026 이후면 그 해 표(rates_<연도>.yaml)를 앞 해 표 위에 얹는다."""
    year = rates_year(fy_start)
    if path != RATES_FILE or year == FIRST_YEAR:
        return _load_first(path)
    over_path = path.with_name(f"rates_{year}.yaml")
    if not over_path.exists():
        raise NoRates(f"{year} 사업연도 세율 표가 없습니다(사업연도 개시일 {fy_start}). 법인세율 · 한도가 {year} 판에서 바뀌었을 수 "
                      f"있어 ctax/wp/rates_{year}.yaml 을 법령 원문으로 확인해 만들기 전에는 조서를 만들지 않습니다")
    over = yaml.safe_load(over_path.read_text(encoding="utf-8")) or {}
    base_year = int(over.get("base") or year - 1)
    return _overlay(load_rates(path, fy_start=f"{base_year}-01-01"), over, year, base_year)


def _load_first(path: Path) -> dict:
    rates = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if path == RATES_FILE and RATES_DIR.is_dir():
        for f in sorted(RATES_DIR.glob("*.yaml")):
            for group, body in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).items():
                if group in rates:
                    raise ValueError(f"세율 묶음 {group} 이 rates_2025.yaml 과 {f.name} 에 함께 있습니다")
                rates[group] = body
    return rates


def _overlay(base: dict, over: dict, year: int, base_year: int) -> dict:
    """앞 해 표 + 그 해 표. 그 해 표에 있는 항목은 그것으로 바꾸고(value 가 없으면 앞 해 값, 근거 · 등급만 바꿈), 없는 항목은
    앞 해 값에 등급 ☆ 와 「<연도> 판 미확인」 을 붙인다."""
    out = {k: v for k, v in over.items() if k in META}
    for group, items in base.items():
        if isinstance(items, dict):
            out[group] = {key: {**item, "grade": "☆",
                                "basis": f"{year} 판 미확인({base_year} 사업연도 값). {item.get('basis', '')}".rstrip()}
                          for key, item in items.items()}
    for group, items in over.items():
        if group in META or not isinstance(items, dict):
            continue
        for key, item in items.items():
            prev = (base.get(group) or {}).get(key) or {}
            if "value" not in item and "value" not in prev:
                raise ValueError(f"rates_{year}.yaml {group}.{key} 에 value 가 없고 {base_year} 표에도 없습니다")
            out.setdefault(group, {})[key] = {**({"value": prev["value"]} if "value" in prev else {}), **item}
    return out


def rate(rates: dict, group: str, key: str):
    return rates[group][key]["value"]


def frac(x) -> Fraction:
    """세율을 분수로. 0.7 같은 값을 이진 소수 오차 없이 곱하려고 쓴다."""
    return Fraction(str(x))


def rd(x) -> int:
    """엑셀 ROUNDDOWN(x, 0) 과 같다(0 쪽으로 자름)."""
    return _trunc(x) if isinstance(x, Fraction) else int(x)


def _trunc(x: Fraction) -> int:
    q = abs(x.numerator) // x.denominator
    return q if x >= 0 else -q


@dataclass
class Line:
    date: str
    no: str
    kind: str
    account: str
    account_name: str
    debit: int
    credit: int
    partner_code: str
    partner: str
    memo: str

    @property
    def amount(self) -> int:
        """비용 · 자산 쪽 금액(차변 - 대변)."""
        return self.debit - self.credit

    @property
    def text(self) -> str:
        return f"{self.partner} {self.memo}".strip()


def read_journal(path: Path) -> list[Line]:
    """전표.csv(계약 5절)에서 손익대체(closing=1) 줄을 뺀 줄."""
    out = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("closing", "0")).strip() in ("1", "True", "true"):
                continue
            out.append(Line(date=r["date"], no=r["no"], kind=r.get("kind", ""), account=str(r["account"]),
                            account_name=r.get("account_name", ""), debit=_int(r.get("debit")),
                            credit=_int(r.get("credit")), partner_code=r.get("partner_code") or "",
                            partner=(r.get("partner") or "").strip(), memo=(r.get("memo") or "").strip()))
    return out


def _int(v) -> int:
    if v in (None, ""):
        return 0
    return int(round(float(str(v).replace(",", ""))))


@dataclass
class Books:
    """한 신고 건의 입력 묶음."""
    ledger: dict
    lines: list[Line]
    prior: dict
    ar: dict | None
    info: dict
    rates: dict
    overrides: dict = field(default_factory=dict)   # (조서 id, key) → 회계사 값(조서입력.json)
    prior_rates: dict = field(default_factory=dict)  # 직전 사업연도 세율 표(결손금 소급공제). 비면 rates 를 쓴다
    by_code: dict = field(init=False)

    def __post_init__(self):
        self.by_code = {a["code"]: a for a in self.ledger.get("accounts", [])}
        # 원가 계정(5xx~7xx)의 「원가로 대체」 결대 줄은 장부.json 에서 debit · credit 이 아니라 transfer 로 따로 둔다.
        # 조서 원장 검토에서도 빼야 계정 금액(amount, 대체 전)과 줄 합계가 맞는다.
        transfer_codes = {a["code"] for a in self.ledger.get("accounts", []) if a.get("transfer")}
        self._lines_by_code: dict[str, list[Line]] = {}
        self.transfer_lines: list[Line] = []
        for ln in self.lines:
            if ln.account in transfer_codes and ln.kind == "결대" and ln.credit > 0:
                self.transfer_lines.append(ln)
                continue
            self._lines_by_code.setdefault(ln.account, []).append(ln)

    # 회사 · 기간
    @property
    def company(self) -> str:
        return self.info.get("company", "")

    @property
    def fy(self) -> str:
        return self.info.get("fy", "")

    @property
    def rates_fy(self) -> str:
        """세율 표의 해(「기준 2026」 시트 이름)."""
        return str(self.rates.get("fy") or FIRST_YEAR)

    @property
    def months(self) -> int:
        try:
            s = date.fromisoformat(self.info["fy_start"])
            e = date.fromisoformat(self.info["fy_end"])
        except (KeyError, ValueError):
            return 12
        m = (e.year - s.year) * 12 + e.month - s.month + (1 if e.day >= s.day - 1 else 0)
        return max(1, min(12, m))

    @property
    def sme(self) -> bool:
        got = self.overrides.get(("tax_3", "중소기업 여부"))
        if got in ("여", "부"):
            return got == "여"
        return self.sme_default

    @property
    def sme_default(self) -> bool:
        c = (self.prior or {}).get("company") or {}
        return bool(c.get("sme", True))

    def override(self, paper: str, key: str):
        """회계사 값. 없으면 model.MISSING."""
        from .model import MISSING
        return self.overrides.get((paper, key), MISSING)

    @property
    def sme_known(self) -> bool:
        c = (self.prior or {}).get("company") or {}
        return "sme" in c

    @property
    def totals(self) -> dict:
        return self.ledger.get("totals", {})

    # 계정 찾기
    def accounts(self, *, cls: str | tuple[str, ...] | None = None, any_of=(), none_of=()) -> list[dict]:
        if isinstance(cls, str):
            cls = (cls,)
        out = []
        for a in self.ledger.get("accounts", []):
            name = a.get("name", "")
            if cls and a.get("class") not in cls:
                continue
            if any_of and not any(k in name for k in any_of):
                continue
            if any(k in name for k in none_of):
                continue
            out.append(a)
        return out

    def lines_of(self, accounts: list[dict]) -> list[Line]:
        out = []
        for a in accounts:
            out.extend(self._lines_by_code.get(a["code"], []))
        return sorted(out, key=lambda x: (x.date, x.no, x.account))

    def all_lines(self) -> list[Line]:
        return self.lines

    def issues_for(self, paper_id: str) -> list[int]:
        if not self.ar:
            return []
        return [i["no"] for i in self.ar.get("issues", []) if paper_id in (i.get("papers") or [])]

    def prior_cell(self, form: str, code: str, default=None):
        return ((self.prior or {}).get("cells") or {}).get(form, {}).get(code, default)


# 적요 · 거래처 분류에 쓰는 말
PENALTY = re.compile(r"과태료|가산세|가산금|벌금|벌과금|범칙금|과료|체납|연체료|위반|통행료|강제징수|교통법규")
AUTHORITY = re.compile(r"세무서|국세|부가세|부가가치세|지방세|원천세|경찰|구청|시청|군청|도청|^[가-힣]{1,4}[시군구]$")
GIFT = re.compile(r"경조|축의|조의|부의|화환|조화")
EVIDENCE = re.compile(r"카드|세금계산서|계산서|현금영수증")
PLATE = re.compile(r"(\d{2,3})\s?([가-힣])\s?(\d{4})")
CAR_PATTERN = re.compile(r"\[(?P<code>[^\]]+)\]\s*(?P<plate>\d{2,3}\s?[가-힣]\s?\d{4})\s*(?P<model>.*?)\s*\((?P<type>[^)]*)\)\s*$")
RENT = re.compile(r"리스|렌트|렌터카|렌탈|대여료")
NOT_CAR = re.compile(r"9인승|승합|화물|트럭|경차|11인승|12인승|15인승")
DONATION_SPECIAL = re.compile(r"국가|지방자치|[시군구]청|국방|위문|이재민|재해|수재|구호|사회복지공동모금|공동모금회|대학교|국립대|대한적십자")
DONATION_NONDESIG = re.compile(r"동창회|향우회|종친회|라이온스|로타리|친목|정당|후원회|새마을")
