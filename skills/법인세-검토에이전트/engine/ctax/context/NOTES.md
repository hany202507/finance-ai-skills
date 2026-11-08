# context 메모

- 정본 파일: `<회사>/_회사맥락/맥락.json`(store.py). 신고 건 폴더 밖이다. 확인 기록은 신고 건마다 `_색인/맥락확인.json`(apply.py).
- 조서가 읽는 곳은 하나다: `wp/cli.py build()` → `Books.context` → `Paper.take` 의 `_from_context`. 작년 답은 기본값으로만 쓰고 `overridden`(회계사 값)에 넣지 않는다.
  `_입력` 시트 기본값이 작년 답이 되어 다시 돌려도 회계사 값으로 바뀌지 않는다. 이 성질은 `test_context.py::test_next_year_fills_last_answer_unconfirmed` 가 지킨다.
- 줄 단위 칸(`take_lines`)은 줄 키(일자 · 전표 · 계정 · 금액)가 해마다 달라 맥락을 쓰지 않는다. 기업업무추진비 증빙만 거래처로 묶어 까닭 칸에 적는다(계정별 서식이 조서입력.json 만 읽어 칸을 채우면 23호와 갈라진다).
- 새 칸을 맥락에 넣으려면 `catalog.ENGINE` 에 한 줄. 한 해에만 맞는 금액은 넣지 않는다.
- 결과 문서: `docs/specs/2026-10-29-법인세-회사맥락-클로징-결과.md`.
