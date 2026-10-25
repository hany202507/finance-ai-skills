# 조서 하나 더하기

조서 하나는 이 폴더의 파일 하나(`<id>.py`)와 등록부(`__init__.py` 의 `ORDER`) 한 줄이다. 다른 조서 파일은 건드리지 않는다.

## 1. 파일 `papers/<id>.py`

```python
NAME = "미수이자"            # 시트 이름은 「<번호> <NAME>」
FORMS = ["10갑"]             # 이어지는 서식 code(계약 6절)
LEDGER_CHECK = True          # p.accounts 의 재무제표 금액 = 원장 줄 합계 검사를 할지

def compute(p, b):           # p: model.Paper (id · 번호는 등록부가 채움), b: books.Books
    ...                      # p.accounts · p.lines · p.values · p.adjustments · p.notes · p.confirm 를 채우고 p.settle(...)

def write(bk, p):            # sheet.py 도우미로 시트 한 장
    ...
```

고를 수 있는 것: `basis(rates)` (기준 시트 줄 `(이름, 값, 근거, 등급, 꼴)`), `basis_table(bk, s, r)` (기준 시트에 표),
`finish(p, b, flow)` (15호 합계 뒤에 계산할 것, 기부금 한도처럼), `write_after(bk, p)` (3호 · 결손금 시트를 부르는 수식).

## 2. 지킬 것

- 숫자는 `compute` 에서만 만든다. 엑셀에는 같은 계산을 수식으로 건다. 수식 결과 = values 값이어야 한다(`calc_row` · `Rows` 가 key → 칸 주소를 `bk.cells` 에 올리고 시험이 비교한다).
- 회계사가 고칠 값은 노란 칸이다. 계산에서는 `p.take(b, key, 기본값, 종류)` 로 읽고, 시트에서는 `Sheet.inp` · `calc_row(kind="input")` · `ledger(pick=...)` 로 쓴다. key 는 이름으로 짓는다(예 `부인 여부/<일자|전표|계정|금액>`, `내용연수/<묶음>`). 원장 검토 줄의 노란 칸은 `p.take_lines(b, "부인 여부")`.
- 조정 줄은 `model.Adj`. `kind` 는 조서 안에서 겹치지 않게, `key` 는 금액이 든 values 키. 유보면 `reserve_subject` · `reserve_col`(증가 · 감소) · `reserve_sign`.
- 세율 · 한도는 `rates_2025.yaml` 에 자기 조서 이름의 묶음을 하나 더해 넣는다(값 · 근거 · 등급). korean-law MCP 원문으로 확인한다.
- 조정.json 은 키를 더하는 것만 된다. 더한 키는 CONTRACT.md 13절에 한 줄.
- 문구: 줄표 금지, 물음표로 끝내지 않음, 서식의 칸은 「란」.

## 3. 등록부와 시험

`__init__.py` 의 `ORDER` 에 `("<id>", "<번호>")` 를 번호 순서 자리에 넣는다. 시험은 `ctax/tests/test_wp_<id>.py` 에 합성 장부로(`test_wp.make_case`), 적어도 계산 값 하나와 「수식 결과 = JSON」 하나. `test_wp.py::test_contract_shape` 의 id 목록도 고친다.
