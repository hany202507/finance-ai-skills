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

## 조회 규칙 (2026-10-09)

- 법령명은 띄어쓰기·가운뎃점 차이만 무시하고 **이름이 정확히 같은 법령만** 쓴다. 없으면 비슷한 이름을 보여 주고 실패한다. 예전에는 「주택법」을 조회하면 민간임대주택법이 나왔다
- 날짜를 주지 않으면 **오늘 시행 중인 판**을 읽는다. 시행 전 개정이 섞인 공포본으로 대신 읽지 않는다. 시행예정 판은 `effective_date` 에 그 시행일을 주거나 `amendment_track` 의 MST·시행일로 읽는다
- `mst` 로 조회할 때는 `effective_date` 에 그 판의 시행일자를 함께 준다
- `get_addenda` 만 가장 늦게 공포된 판에서 부칙을 읽는다. 시행예정 부칙의 적용례까지 보기 위해서다
- 표 안의 목·세목까지 모두 출력한다
- 모든 출력에서 OC 값을 가린다

## 단위 시험

`npm test` 는 네트워크 없이 돈다. `test/fixtures` 의 법제처 응답은 `LAW_OC=<본인OC> node test/capture.mjs` 로 다시 받는다.

## 시험

```bash
npm install
LAW_OC=<본인OC> node selftest.mjs
```

실제 법제처 API 를 불러 응답에 기대한 문구가 들어 있는지 33개 항목으로 확인합니다.
