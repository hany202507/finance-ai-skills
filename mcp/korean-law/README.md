# korean-law MCP

법제처 국가법령정보 OPEN API 를 직접 부르는 로컬 stdio MCP 서버입니다. `세법자문-회신` 스킬이 이 서버의 도구 이름을 전제로 쓰여 있습니다.

## 준비

1. [open.law.go.kr](https://open.law.go.kr) 회원가입 후 OPEN API 활용신청을 합니다. 승인까지 1~2일 걸립니다. OC 는 가입한 이메일의 아이디 부분입니다.
2. Node.js 18 이상.

## 설치

저장소 루트의 `install.ps1`·`install.sh` 가 `~/.claude/mcp/korean-law` 에 넣고 패키지까지 설치합니다. 등록은 한 번만 합니다.

```bash
claude mcp add -s user korean-law -e LAW_OC=<본인OC> -- node "<홈>/.claude/mcp/korean-law/index.js"
```

OC 기본값은 두지 않았습니다. `LAW_OC` 가 없으면 서버가 뜨자마자 종료합니다. 남의 키로 조회되면서 설치가 끝난 것처럼 보이는 일을 막기 위해서입니다.

## 도구

| 도구 | 하는 일 |
|---|---|
| `search_law` | 법령명으로 MST·시행일 찾기. 법령명 전용이라 내용 키워드는 0건 |
| `get_law_outline` | 편·장·절과 조문 목차 |
| `scan_articles` | 여러 법령의 조문 본문을 키워드로 훑기 |
| `get_law_text` | 조문 원문. `effective_date` 로 과거 시행 버전 |
| `get_addenda` | 부칙의 적용례·경과조치 |
| `amendment_track` | 개정 이력 |
| `trace_references` | 법-령-칙·타법 인용 연결 |
| `search_decisions` · `get_decision` | 판례·법령해석례·헌재결정례 |
| `search_rulings` · `get_ruling` | 국세청 예규 목록, 조세심판원 결정 본문 |
| `search_forms` | 별표·서식 목록과 링크 |

모든 조회 결과 끝에 law.go.kr 출처 URL 이 붙습니다. 국세청 예규는 법제처가 본문 API 를 제공하지 않아 목록과 링크까지만 나옵니다.

## 시험

```bash
npm install
LAW_OC=<본인OC> node selftest.mjs
```

실제 법제처 API 를 불러 응답에 기대한 문구가 들어 있는지 25개 항목으로 확인합니다.
