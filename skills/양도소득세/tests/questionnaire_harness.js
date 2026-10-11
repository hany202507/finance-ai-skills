// 질문지 핵심 논리(core.js)를 node 로 돌리는 시험 도구. 입력은 표준입력의 JSON 한 개, 출력은 표준출력의 JSON 한 개.
//   {"mode": "cond", "defs": ..., "conds": ..., "cases": [{"qid": "A09", "values": {"A13": true}}]}
//     -> {"states": ["E", ...]}   조건 하나를 값 표(질문 id -> 답)로 판정한 상태(T, F, U, E)
//   {"mode": "facts", "defs": ..., "conds": ..., "stores": [...]}
//     -> {"results": [{"facts": ..., "errors": [...], "states": {...}}]}   화면 저장소에서 만든 사실관계
const fs = require('fs');
const path = require('path');

const core = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'questionnaire_template', 'core.js'), 'utf8');
const makeCore = new Function(core + '\n;return makeCore;')();
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const c = makeCore(input.defs, input.conds);

if (input.mode === 'cond') {
  const out = input.cases.map(function (cs) {
    const ctx = { get: function (id) { return Object.prototype.hasOwnProperty.call(cs.values, id) ? cs.values[id] : undefined; } };
    return c.condState(input.conds[cs.qid], ctx, cs.qid);
  });
  process.stdout.write(JSON.stringify({ states: out }));
} else if (input.mode === 'facts') {
  const out = input.stores.map(function (store) {
    const comp = c.compute(store);
    const b = c.buildFacts(store, comp);
    return { facts: b.facts, errors: b.errors, states: comp.st };
  });
  process.stdout.write(JSON.stringify({ results: out }));
} else {
  throw new Error('mode 를 모른다: ' + input.mode);
}
