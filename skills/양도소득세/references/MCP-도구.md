# 양도소득세 · MCP 도구 표

> 양도소득세 스킬의 딸린 자료다. yangdo 도구를 부르다 오류가 나거나 인자와 출력 파일 이름을 확인할 때 읽는다. 본문의 「3절」 은 SKILL.md 의 절이다.
> 2026-11-15 SKILL.md 에서 글자 그대로 옮겼다.

| 도구 | 하는 일 |
|---|---|
| `yangdo_next_questions` | 사실관계에 비어 있는 것 중 다음에 물을 문항을 돌려준다. 문항마다 `섹션`, `섹션이름`, 흔한 값의 `가정` 이 붙는다. `생략` 에는 묻지 않는 선택 문항과 그 안내가 온다. 인자는 `facts_path`(파일 경로)나 `facts`(JSON 객체) 중 하나, `limit`(한 번에 받을 문항 수, 기본 1. 묶어 물을 때는 10 안팎). `forms`(서식 단계 문항도 낸다)는 계산용 문항을 모을 때는 쓰지 않는다 |
| `yangdo_answer` | 문항 답을 사실관계에 넣는다. 인자는 `facts_path` 나 `facts`, `question`(문항 id), `value`(답), 자산이나 주택마다 묻는 문항이면 `asset`(자산 id), `house`(주택 id). `value` 에 문자열 「모름」을 주면 모름으로 기록한다. `facts_path` 를 주면 그 파일을 고쳐 쓰고, `facts` 를 주면 고친 사실관계를 `사실관계` 로 돌려준다 |
| `yangdo_calculate` | 판정, 세액, 근거, 파일설명서 코드를 응답으로 낸다. 인자는 `facts_path` 나 `facts`, `today`(YYYY-MM-DD, 비우면 한국 시간 오늘), `out_dir`. `out_dir` 를 주면 그 폴더에 이 스킬이 쓰는 이름의 이전 파일을 지우고 `양도소득세_계산근거.xlsx` 만 쓴다 |
| `yangdo_forms` | 계산에 이어 신고인 정보 검사, 신고값, 서식 검산, 신고서 PDF 두 벌까지 한다. 출력 폴더에는 신고서 PDF 두 벌과 계산근거 엑셀만 남는다. 인자는 `facts_path` 나 `facts`, `filer_path`(신고인 JSON 파일 경로, 필수), `out_dir`(필수), `today` |
| `regulated_area` | 기준일에 조정대상지역·투기과열지구·투기지역인지 공고 이력으로 판정한다. 필수 인자 `sido`(시도), `sigungu`(시군구), `as_of`(기준일), 선택 인자 `eupmyeondong`(읍면동), `in_district`(지구해당) |
| `ruleset_info` | 기준정보 판 id, 확인일, 시행예정 개정, 계류 개정 |
