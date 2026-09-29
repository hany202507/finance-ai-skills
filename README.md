# finance-ai-skills

[![tests](https://github.com/hany202507/finance-ai-skills/actions/workflows/test.yml/badge.svg)](https://github.com/hany202507/finance-ai-skills/actions/workflows/test.yml)

재무·회계·세무 실무에 쓰는 Claude Code 스킬입니다. 하나씩 추가합니다.

실무에서 매달 쓰는 것을 공개합니다. 공통 원칙은 세 가지입니다. 계산은 결정적인 코드가 하고, 판단 근거는 원문으로 남기고, 결과는 AI 와 무관한 방법으로 한 번 더 검산합니다.

| 이름 | 분야 | 하는 일 |
|---|---|---|
| [현금흐름표](skills/현금흐름표/) | 회계 | 전기 재무상태표와 당기 분개장(또는 계정별원장)으로 현금흐름표 직접법·간접법을 만들고 서로 맞춰 본다 |

## 현금흐름표

분개장의 현금 전표를 전부 보고 상대계정으로 영업·투자·재무를 정합니다. 미지급금·가지급금·가수금처럼 상대계정만으로 모르는 것은 원천 전표, 은행 상세 내역, 적요로 따라가 발라냅니다. 그 결과로 직접법을 만들고, 감사인 정산표(WTB) 방식의 간접법과 맞춰 봅니다.

- **계산은 엔진, 워크북은 수식.** 분개장 줄마다 활동·항목이 붙고 직접법·정산표·간접법은 전부 그 열을 SUMIFS 합니다. 분개장 한 줄의 분류를 고치면 현금흐름표가 따라 바뀝니다.
- **직접법과 간접법이 맞는 것은 분류가 맞다는 증거가 아닙니다.** 둘이 같은 분류를 쓰기 때문입니다. 그래서 분류와 무관한 사실로 분류를 확인하는 독립 검산을 따로 둡니다.
- **읽는 입력.** 한 줄 한 계정 분개장, 차변·대변 계정이 다른 열인 분개장, 더존 계정별원장, 합계잔액시산표, 공시 양식 재무상태표·손익계산서, 은행 상세 내역, 계정명세서.
- **기준.** 일반기업회계기준(중소기업 포함)과 K-IFRS.

실제 장부 네 벌로 돌려 내부 대사와 독립 검산을 통과했고, 그중 하나는 감사인 정산표와 대조했습니다. 다만 더존·이카운트류 양식에서만 검증했고, 연결 현금흐름표와 여러 해 비교 표시는 다루지 않습니다.

### 설치

스킬만 설치합니다(플러그인 아님). 한 줄을 붙여 넣으면 스킬 폴더에 들어가고 파이썬 패키지까지 설치합니다.

윈도우 PowerShell

```powershell
irm https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.ps1 | iex
```

맥 · 리눅스 터미널

```bash
curl -fsSL https://raw.githubusercontent.com/hany202507/finance-ai-skills/main/install.sh | sh
```

`~/.claude/skills/현금흐름표` 에 들어갑니다. Claude Code 를 다시 열면 잡힙니다. 파이썬 3.10 이상이 필요합니다. 새 판이 나오면 같은 줄을 다시 실행하면 덮어씁니다.

플러그인으로 설치하려면 `/plugin marketplace add hany202507/finance-ai-skills` 후 `/plugin install finance-ai-skills@finance-ai-skills`.

## 고지

결과는 전문가 검토 전 초안입니다. 회계 처리와 세무 판단의 최종 확정은 사용자에게 있습니다. 예시와 테스트의 회사·금액은 합성하거나 바꾼 값입니다.

## 만든 사람

박상정(Hany). 재무·회계·세무 실무에 AI 에이전트를 붙이는 일을 합니다. 재무 AI 커리큘럼은 [kernelacademy-web](https://github.com/hany202507/kernelacademy-web) 에 공개하고 있습니다.

## 라이선스

MIT
