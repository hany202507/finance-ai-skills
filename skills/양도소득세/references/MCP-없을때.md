# 양도소득세 · MCP 가 없을 때 문항 받기와 답 넣기

> 양도소득세 스킬의 딸린 자료다. yangdo MCP 가 등록돼 있지 않아 스크립트로 문항을 받고 답을 넣어야 할 때 읽는다. 본문의 「위와 같이」 는 SKILL.md 의 새 사건 줄을 가리킨다.
> 2026-11-15 SKILL.md 에서 글자 그대로 옮겼다.

MCP 가 없으면 같은 일을 스크립트로 합니다. `{skill}` 은 스킬 폴더 경로로 바꿔 읽습니다. 새 사건은 위와 같이 `{"자산": [{"id": "A"}]}` 를 담은 파일을 먼저 만듭니다.

```bash
# 다음 문항
python -c "import sys,json; sys.path.insert(0, r'{skill}'); from yangdo import questions as Q; r=Q.next_questions(json.load(open(r'<facts.json>', encoding='utf-8')), limit=10); print(json.dumps({k: r[k] for k in ('다음', '남은', '생략')}, ensure_ascii=False, indent=1))"

# 답 넣기(자산이나 주택마다 묻는 문항은 자산=, 주택= 를 함께 준다)
python -c "import sys,json; sys.path.insert(0, r'{skill}'); from yangdo import questions as Q; p=r'<facts.json>'; f=Q.answer(json.load(open(p, encoding='utf-8')), '<문항id>', <값>, 자산='<자산id>'); json.dump(f, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)"
```
