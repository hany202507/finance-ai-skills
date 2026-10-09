import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeRunTool } from '../tools.mjs';

function fakeApi(handler) {
  const calls = [];
  const api = async (path, params) => {
    calls.push({ path, ...params });
    const r = handler(path, params);
    if (r === undefined) throw new Error('예상하지 못한 호출 ' + JSON.stringify({ path, params }));
    return r;
  };
  api.calls = calls;
  return api;
}
const row = (name, mst, ef, prom = '20260101', no = '1', id = '000001') => ({
  법령명한글: name, 법령일련번호: mst, 시행일자: ef, 공포일자: prom, 공포번호: no, 법령ID: id,
  법령구분명: '법률', 현행연혁코드: '현행', 제개정구분명: '일부개정', 소관부처명: '국토교통부',
});
const page = (rows, total = rows.length) => ({ LawSearch: { totalCnt: String(total), law: rows } });
const body = (name, ef, units) => ({ 법령: { 기본정보: { 법령명_한글: name, 시행일자: ef, 공포번호: '1', 공포일자: '20260101', 제개정구분: '일부개정' }, 조문: { 조문단위: units } } });
const unit = (no, text) => ({ 조문번호: no, 조문여부: '조문', 조문제목: '제목', 조문내용: text });
const TODAY = () => '20261009';

test('검색 첫 쪽에 없어도 다음 쪽에서 이름이 정확히 같은 법령을 찾는다', async () => {
  const api = fakeApi((path, p) => {
    if (path === 'lawSearch.do' && p.page === 1) return page([row('민간임대주택에 관한 특별법', '1', '20260101')], 2);
    if (path === 'lawSearch.do' && p.page === 2) return page([row('주택법', '289171', '20260908')], 2);
    if (path === 'lawService.do') return body('주택법', '20260908', [unit('63', '제63조의2(조정대상지역의 지정 및 해제)')]);
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_law_text', { law_name: '주택법', article: '63의2' });
  assert.match(out, /^법령: 주택법\n시행일: 20260908 /);
  const svc = api.calls.find((c) => c.path === 'lawService.do');
  assert.deepEqual([svc.target, svc.MST, svc.efYd, svc.JO], ['eflaw', '289171', '20260908', '006302']);
});

test('이름이 정확히 같은 법령이 없으면 다른 법을 쓰지 않고 실패한다', async () => {
  const api = fakeApi((path) => (path === 'lawSearch.do' ? page([row('공영주택법', '9', '19630101')]) : undefined));
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '주택법' }), /이름이 정확히 같은 법령이 없다/);
  assert.equal(api.calls.filter((c) => c.path === 'lawService.do').length, 0);
});

test('날짜가 없으면 오늘 시행 중인 판을 읽는다(시행예정 판을 읽지 않는다)', async () => {
  const api = fakeApi((path) => {
    if (path === 'lawSearch.do') return page([row('주택법', '289171', '20270309', '20260901'), row('주택법', '289171', '20260908', '20260301')]);
    if (path === 'lawService.do') return body('주택법', '20260908', [unit('1', '제1조(목적)')]);
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  await run('get_law_text', { law_name: '주택법' });
  const s = api.calls.find((c) => c.path === 'lawService.do');
  assert.equal(s.efYd, '20260908');
  const q = api.calls.find((c) => c.path === 'lawSearch.do');
  assert.equal(q.target, 'eflaw');
});

test('eflaw 가 비어 오면 공포본(target=law)으로 대신 읽지 않고 실패한다', async () => {
  const api = fakeApi((path) => {
    if (path === 'lawSearch.do') return page([row('주택법', '289171', '20260908')]);
    if (path === 'lawService.do') return body('주택법', '20260908', []);
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '주택법', article: '1' }), /공포본\(target=law\)으로 대신 읽지 않는다/);
  assert.equal(api.calls.some((c) => c.target === 'law'), false);
});

test('mst 만 주고 effective_date 가 없으면 실패한다', async () => {
  const run = makeRunTool({ callApi: fakeApi(() => undefined), today: TODAY });
  await assert.rejects(run('get_law_text', { mst: '289171' }), /effective_date/);
});

test('mst 와 effective_date 를 주면 검색 없이 그 판을 읽는다', async () => {
  const api = fakeApi((path) => (path === 'lawService.do' ? body('주택법', '20270309', [unit('1', '제1조')]) : undefined));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_law_text', { mst: '289171', effective_date: '2027-03-09' });
  assert.match(out, /시행일: 20270309 \(.*시행예정/);
});

test('amendment_track 은 이름이 같은 법령만 보이고 상태를 날짜로 정한다', async () => {
  const api = fakeApi((path) => (path === 'lawSearch.do'
    ? page([row('공영주택법', '9', '19630101'), row('주택법', '289171', '20270309'), row('주택법', '289171', '20260908'), row('주택법', '280000', '20250101')])
    : undefined));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('amendment_track', { law_name: '주택법' });
  assert.match(out, /^주택법 — 시행일별 개정 이력 3건/);
  assert.match(out, /시행 20270309 · 시행예정/);
  assert.match(out, /시행 20260908 · 현행/);
  assert.match(out, /시행 20250101 · 연혁/);
  assert.doesNotMatch(out, /공영주택법/);
});

test('amendment_track 은 이름이 같은 법령이 없으면 그렇게 말한다', async () => {
  const api = fakeApi((path) => (path === 'lawSearch.do' ? page([row('공영주택법', '9', '19630101')]) : undefined));
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('amendment_track', { law_name: '주택법' }), /이름이 정확히 같은 법령이 없다/);
});

test('search_law 는 이름이 같은 법령을 맨 앞에, 표시를 붙여 보인다', async () => {
  const api = fakeApi((path) => (path === 'lawSearch.do'
    ? page([row('민간임대주택에 관한 특별법', '1', '20260101', '20260101', '1', 'A'), row('주택법', '289171', '20260908', '20260101', '1', 'B')])
    : undefined));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('search_law', { query: '주택법' });
  assert.match(out, /^★ 이름 일치 · 주택법/);
});
