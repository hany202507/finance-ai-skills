import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeRunTool, TOOLS } from '../tools.mjs';
import { TARGETS, NAMES } from './targets.mjs';

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

test('effective_date 를 한글 날짜로 줘도 그 날 시행 중인 판을 읽는다', async () => {
  const api = fakeApi((path) => {
    if (path === 'lawSearch.do') {
      return page([
        row('주택법', '300003', '20241001', '20240901', '3'),
        row('주택법', '300002', '20240701', '20240601', '2'),
        row('주택법', '300001', '20240101', '20231201', '1'),
      ]);
    }
    if (path === 'lawService.do') return body('주택법', '20240701', [unit('1', '제1조(목적)')]);
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  await run('get_law_text', { law_name: '주택법', effective_date: '2024년 7월 1일' });
  const svc = api.calls.find((c) => c.path === 'lawService.do');
  assert.deepEqual([svc.MST, svc.efYd], ['300002', '20240701']);
});

test('get_addenda 는 시행일이 아니라 공포일이 가장 늦은 판에서 부칙을 읽는다', async () => {
  const api = fakeApi((path) => {
    if (path === 'lawSearch.do') {
      return page([
        row('주택법', 'OLD_PROM', '20270101', '20251230', '9'),
        row('주택법', 'NEW_PROM', '20260701', '20260301', '5'),
      ]);
    }
    if (path === 'lawService.do') {
      return { 법령: { 기본정보: { 법령명_한글: '주택법' }, 부칙: { 부칙단위: [{ 부칙공포일자: '20260301', 부칙공포번호: '5', 부칙내용: ['제1조(시행일) 이 법은 공포한 날부터 시행한다.'] }] } } };
    }
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_addenda', { law_name: '주택법' });
  const svc = api.calls.find((c) => c.path === 'lawService.do');
  assert.deepEqual([svc.target, svc.MST], ['law', 'NEW_PROM']);
  assert.match(out, /MST NEW_PROM/);
});

/* ---------------------------------------------------- 2026-10-09 최종 검토 수정 */

const fx = (f) => JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'fixtures', f), 'utf8'));
const sameParams = (a, b) => Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => String(b[k]) === String(v));

/** 저장한 실제 응답(test/targets.mjs)을 돌려주는 가짜 callApi. 목록에 없는 호출은 more 가 답한다 */
function fixtureApi(more = () => undefined) {
  return fakeApi((path, p) => {
    const t = TARGETS.find((x) => x.path === path && sameParams(x.params, p));
    return t ? fx(t.file) : more(path, p);
  });
}
/** MST 로 읽는 본문은 고른 판을 확인하는 데만 쓰므로 이름만 맞춘 가짜로 둔다 */
const mstBody = (names) => (path, p) => (path === 'lawService.do' && p.MST ? body(names[p.MST] ?? '이름 모름', p.efYd, [unit('1', '제1조(목적)')]) : undefined);
const header2 = (out) => out.split('\n')[1];

// ---- C1. 옛 이름 ----

test('C1(a) 옛 이름 + 개칭 뒤 날짜면 법령ID 로 현행 이름을 찾아 새 이름 판을 읽는다', async () => {
  const api = fixtureApi(mstBody({ 258035: NAMES.경제새 }));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_law_text', { law_name: NAMES.경제옛, effective_date: '2024-05-01' });
  const svc = api.calls.filter((c) => c.path === 'lawService.do' && c.MST);
  assert.deepEqual(svc.map((c) => [c.MST, c.efYd]), [['258035', '20240109']]);
  assert.match(out, new RegExp(`^법령: ${NAMES.경제새}\n`));
  assert.ok(header2(out).includes(`요청한 이름 "${NAMES.경제옛}" 은 옛 이름이다. 현행 이름: ${NAMES.경제새}`), header2(out));
  assert.ok(api.calls.some((c) => c.ID === '009411'), '법령ID 로 현행 이름을 묻지 않았다');
});

test('C1(b) 옛 이름 + 개칭 전 날짜면 옛 이름 판을 읽는다', async () => {
  const api = fixtureApi(mstBody({ 75650: NAMES.경제옛 }));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_law_text', { law_name: NAMES.경제옛, effective_date: '2008-01-01' });
  const svc = api.calls.filter((c) => c.path === 'lawService.do' && c.MST);
  assert.deepEqual(svc.map((c) => [c.MST, c.efYd]), [['75650', '20070928']]);
  assert.ok(header2(out).includes(`요청한 이름 "${NAMES.경제옛}" 은 옛 이름이다. 현행 이름: ${NAMES.경제새}`), header2(out));
});

test('C1 옛 이름을 날짜 없이 조회하면 연혁까지 찾아 오늘 시행 중인 새 이름 판을 읽는다', async () => {
  const api = fixtureApi(mstBody({ 286513: NAMES.경제새 }));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_law_text', { law_name: NAMES.경제옛 });
  const svc = api.calls.filter((c) => c.path === 'lawService.do' && c.MST);
  assert.deepEqual(svc.map((c) => [c.MST, c.efYd]), [['286513', '20260602']]);
  assert.ok(header2(out).startsWith('시행일: 20260602 (오늘 20261009 기준 시행 중인 판; 요청한 이름'), header2(out));
});

for (const [today, note] of [['20261009', false], ['20261016', true]]) {
  test(`C1(c) 지방자치분권법 옛 이름을 날짜 없이 조회하면 ${today} 에도 새 이름 현행 판(286737@20260910)을 읽는다`, async () => {
    const api = fixtureApi(mstBody({ 286737: NAMES.지방새 }));
    const run = makeRunTool({ callApi: api, today: () => today });
    const out = await run('get_law_text', { law_name: NAMES.지방옛 });
    const svc = api.calls.filter((c) => c.path === 'lawService.do' && c.MST);
    assert.deepEqual(svc.map((c) => [c.MST, c.efYd]), [['286737', '20260910']]);
    assert.ok(header2(out).includes(`현행 이름: ${NAMES.지방새}`), header2(out));
    // 개칭 전에 공포돼 2026-10-15 에 시행된 옛 이름 판은 고르지 않되, 있다는 사실은 알린다
    assert.equal(header2(out).includes('MST 285293(시행 20261015)'), note, header2(out));
  });
}

test('C1(d) 현행 이름 조회는 법령ID 조회나 추가 검색을 하지 않는다', async () => {
  const api = fixtureApi(mstBody({ 286513: NAMES.경제새 }));
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('get_law_text', { law_name: NAMES.경제새 });
  assert.deepEqual(api.calls.map((c) => [c.path, c.query ?? c.MST]), [['lawSearch.do', NAMES.경제새], ['lawService.do', '286513']]);
  assert.doesNotMatch(out, /옛 이름/);
});

test('C1 현행 이름을 얻지 못하고 고른 판이 그 이름의 마지막 판이면 개칭·폐지를 의심해 실패한다', async () => {
  const old = (mst, ef) => ({ ...row('옛이름법', mst, ef, ef, '1', '777777'), 현행연혁코드: '연혁' });
  const api = fakeApi((path, p) => {
    if (path === 'lawSearch.do') return page([old('2', '20050101'), old('1', '20000101')]);
    if (path === 'lawService.do' && p.ID) return { Law: '일치하는 법령이 없습니다.  법령명을 확인하여 주십시오.' };
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '옛이름법' }), /개칭·폐지됐을 수 있다\. 현행 이름으로 조회하거나 법령별칭을 확인하라/);
  assert.equal(api.calls.some((c) => c.MST), false);
  // 그 이름의 마지막 판이 아니면(뒤에 같은 이름 판이 있으면) 그 날짜 판을 읽는다
  const api2 = fakeApi((path, p) => {
    if (path === 'lawSearch.do') return page([old('2', '20050101'), old('1', '20000101')]);
    if (path === 'lawService.do' && p.ID) return { Law: '일치하는 법령이 없습니다.' };
    if (path === 'lawService.do') return body('옛이름법', p.efYd, [unit('1', '제1조')]);
  });
  await makeRunTool({ callApi: api2, today: TODAY })('get_law_text', { law_name: '옛이름법', effective_date: '2001-01-01' });
  assert.deepEqual(api2.calls.filter((c) => c.MST).map((c) => c.MST), ['1']);
});

test('C1 고른 판이 폐지 판이면 읽지 않고 폐지됐다고 실패한다', async () => {
  const r = (mst, ef, kind) => ({ ...row('폐지된법', mst, ef, ef, '1', '012004'), 현행연혁코드: '연혁', 제개정구분명: kind });
  const api = fakeApi((path, p) => {
    if (path === 'lawSearch.do') return page([r('9', '20170120', '타법폐지'), r('8', '20160901', '타법개정')]);
    if (path === 'lawService.do' && p.ID) throw new Error('법제처 API가 JSON이 아닌 응답을 반환했다');
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '폐지된법', effective_date: '2020-01-01' }), /폐지된 법령이다/);
  assert.equal(api.calls.some((c) => c.MST), false);
});

test('C1 amendment_track 도 옛 이름이면 현행 이름의 판까지 보이고 옛 이름 판을 현행으로 적지 않는다', async () => {
  const api = fixtureApi();
  const run = makeRunTool({ callApi: api, today: TODAY });
  const out = await run('amendment_track', { law_name: NAMES.경제옛, display: 200 });
  assert.match(out, new RegExp(`요청한 이름 "${NAMES.경제옛}" 은 옛 이름이다\\. 현행 이름: ${NAMES.경제새}`));
  assert.match(out, /시행 20260602 · 현행 · .*MST 286513/);
  assert.doesNotMatch(out, /시행 20090101 · 현행/);
});

// ---- C1 반례 D: 개칭 공포 뒤·시행 전에 옛 이름으로 공포된 개정 ----
// 개칭 R: 공포 2025-06-01, 시행 2026-01-01(새 이름). 그 사이 옛 이름 개정 Y: 공포 2025-09-01, 시행 2025-10-01.
// 법제처는 판을 시행일에 쓰던 이름으로 싣기 때문에 Y 는 옛 이름이다
function renameApiD() {
  const mk = (name, mst, ef, prom, mark) => ({ ...row(name, mst, ef, prom, '1', 'D00001'), 현행연혁코드: mark });
  const oldRows = [mk('D옛법', 'Y', '20251001', '20250901', '연혁'), mk('D옛법', 'O1', '20200101', '20200101', '연혁')];
  const newRows = [mk('D새법', 'R', '20260101', '20250601', '현행')];
  return fakeApi((path, p) => {
    if (path === 'lawSearch.do' && p.query === 'D옛법') return page(p.nw === '2,3' ? [] : oldRows);
    if (path === 'lawSearch.do' && p.query === 'D새법') return page(newRows);
    if (path === 'lawService.do' && p.ID === 'D00001') return { 법령: { 기본정보: { 법령명_한글: 'D새법' } } };
    if (path === 'lawService.do' && p.MST) return body(p.MST === 'R' ? 'D새법' : 'D옛법', p.efYd, [unit('1', '제1조(목적)')]);
  });
}
const readMst = (api) => api.calls.filter((c) => c.path === 'lawService.do' && c.MST).map((c) => [c.MST, c.efYd]);

for (const [label, args, today, want] of [
  ['날짜 없이(오늘 2026-03-01)', {}, '20260301', ['R', '20260101']],
  ['effective_date 2026-03-01', { effective_date: '2026-03-01' }, '20261009', ['R', '20260101']],
  ['effective_date 2025-11-01', { effective_date: '2025-11-01' }, '20261009', ['Y', '20251001']],
]) {
  test(`C1 반례 D: 옛 이름 ${label} → ${want[0]}`, async () => {
    const api = renameApiD();
    const out = await makeRunTool({ callApi: api, today: () => today })('get_law_text', { law_name: 'D옛법', ...args });
    assert.deepEqual(readMst(api), [want]);
    assert.ok(header2(out).includes('요청한 이름 "D옛법" 은 옛 이름이다. 현행 이름: D새법'), header2(out));
    assert.doesNotMatch(header2(out), /옛 이름으로 공포된 판/);
  });
}

test('C1 반례 D: 현행 이름으로 조회해도 R 을 읽는다', async () => {
  const api = renameApiD();
  await makeRunTool({ callApi: api, today: () => '20260301' })('get_law_text', { law_name: 'D새법' });
  assert.deepEqual(readMst(api), [['R', '20260101']]);
});

test('C1 반례 D: amendment_track 은 오늘 2026-03-01 에 R 을 현행, Y 를 연혁으로 적는다', async () => {
  const out = await makeRunTool({ callApi: renameApiD(), today: () => '20260301' })('amendment_track', { law_name: 'D옛법' });
  assert.match(out, /시행 20260101 · 현행 · .*MST R/);
  assert.match(out, /시행 20251001 · 연혁 · .*MST Y/);
});

// ---- C2. trace_references 가지 조문 ----

function traceApi(articleText, decreeUnits) {
  return fakeApi((path, p) => {
    if (path === 'lawSearch.do') {
      if (p.query === '소득세법') return page([row('소득세법', '280405', '20260701', '20260101', '1', 'A')]);
      if (p.query === '소득세법 시행령') return page([row('소득세법 시행령', '290841', '20261001', '20260101', '1', 'B')]);
      if (p.query === '소득세법 시행규칙') return page([row('소득세법 시행규칙', '290000', '20260301', '20260101', '1', 'C')]);
      if (p.query === '주택법') return page([row('주택법', '289171', '20260908', '20260101', '1', 'D')]);
    }
    if (path === 'lawService.do') {
      if (p.MST === '280405') return body('소득세법', '20260701', [{ 조문번호: '104', 조문가지번호: '3', 조문여부: '조문', 조문제목: '비사업용 토지의 범위', 조문내용: articleText }]);
      if (p.MST === '290841') return body('소득세법 시행령', '20261001', decreeUnits);
      if (p.MST === '290000') return body('소득세법 시행규칙', '20260301', [unit('1', '제1조(목적)')]);
      if (p.MST === '289171') return body('주택법', '20260908', [{ 조문번호: '63', 조문가지번호: '2', 조문여부: '조문', 조문제목: '조정대상지역의 지정 및 해제', 조문내용: '…' }]);
    }
  });
}
const dUnit = (no, br, text) => ({ 조문번호: no, 조문가지번호: br, 조문여부: '조문', 조문제목: `제목${no}`, 조문내용: text });

for (const art of ['104의3', '104-3']) {
  test(`C2 trace_references("${art}") 는 시행령의 「법 제104조의3」 을 찾고 「법 제104조」 는 넣지 않는다`, async () => {
    const decree = [dUnit('168', '6', '법 제104조의3제1항제1호에서 "대통령령으로 정하는 기간"이란'), dUnit('167', '', '법 제104조제1항에 따른 세율'), dUnit('169', '', '법 제104조의30에 따른')];
    const api = traceApi('제104조의2에 따른 토지와 「주택법」 제63조의2에 따른 지역', decree);
    const out = await makeRunTool({ callApi: api, today: TODAY })('trace_references', { law_name: '소득세법', article: art });
    assert.match(out, /^소득세법 제104조의3 — 참조 관계\n {2}https:\/\/www\.law\.go\.kr\/법령\/소득세법\/제104조의3\n/);
    assert.match(out, /■ 시행령에서 이 조문을 되부르는 조문 1건\n {2}제168조의6 /);
    assert.match(out, /「주택법」 제63조의2 조정대상지역의 지정 및 해제\n {6}https:\/\/www\.law\.go\.kr\/법령\/주택법\/제63조의2/);
    assert.match(out, /같은 법 내부 인용 1건: 제104조의2/);
    assert.doesNotMatch(out, /제104의3조|제63의2조/);
  });
}

test('C2 trace_references("60") 는 「법 제60조의2」 를 잡지 않고, 다른 법 이름 끝의 「법 제60조」 도 잡지 않는다', async () => {
  const decree = [dUnit('118', '', '법 제60조의2에 따른 신고'), dUnit('117', '', '법 제60조제1항에 따른'), dUnit('116', '', '농어촌특별세법 제60조에 따른')];
  const api = fakeApi((path, p) => {
    if (path === 'lawSearch.do') {
      if (p.query === '소득세법') return page([row('소득세법', '280405', '20260701', '20260101', '1', 'A')]);
      if (p.query === '소득세법 시행령') return page([row('소득세법 시행령', '290841', '20261001', '20260101', '1', 'B')]);
      if (p.query === '소득세법 시행규칙') return page([]);
    }
    if (path === 'lawService.do' && p.MST === '280405') return body('소득세법', '20260701', [unit('60', '본문')]);
    if (path === 'lawService.do' && p.MST === '290841') return body('소득세법 시행령', '20261001', decree);
  });
  const out = await makeRunTool({ callApi: api, today: TODAY })('trace_references', { law_name: '소득세법', article: '60' });
  assert.match(out, /■ 시행령에서 이 조문을 되부르는 조문 1건\n {2}제117조 /);
});

// ---- I1. 인증 실패·예상과 다른 응답 ----

const AUTH_FAIL = { result: '사용자 정보 검증에 실패하였습니다.', msg: 'OPEN API 호출 시 사용자 검증을 위하여 정확한 서버장비의 IP주소 및 도메인주소를 등록해 주세요.' };

test('I1 인증 실패 응답이면 「이름이 정확히 같은 법령이 없다」 가 아니라 그 문구로 실패한다', async () => {
  const run = makeRunTool({ callApi: fakeApi(() => AUTH_FAIL), today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '주택법' }), /사용자 정보 검증에 실패하였습니다/);
  await assert.rejects(run('search_law', { query: '주택법' }), /사용자 정보 검증에 실패하였습니다/);
});

test('I1 LawSearch 루트가 없으면 응답 키 이름을 담아 실패한다(값은 담지 않는다)', async () => {
  const run = makeRunTool({ callApi: fakeApi(() => ({ error: '비밀값', code: 'x' })), today: TODAY });
  const err = await run('search_law', { query: '주택법' }).then(() => null, (e) => e);
  assert.match(err?.message ?? '', /법제처 응답 형식이 다르다\(인증 실패일 수 있다\): error, code/);
  assert.doesNotMatch(err.message, /비밀값/);
});

test('I1 실패 문구 안의 OC= 값은 가린다', async () => {
  const run = makeRunTool({ callApi: fakeApi(() => ({ result: '검증에 실패 OC=abc123&x', msg: '' })), today: TODAY });
  const err = await run('search_law', { query: '주택법' }).then(() => null, (e) => e);
  assert.match(err?.message ?? '', /OC=\*\*\*/);
  assert.doesNotMatch(err.message, /abc123/);
});

test('I1 search_rulings 도 인증 실패를 「결과 없음」 으로 적지 않는다', async () => {
  const run = makeRunTool({ callApi: fakeApi(() => AUTH_FAIL), today: TODAY });
  const out = await run('search_rulings', { query: '양도소득세', source: 'tribunal' });
  assert.match(out, /검색 실패: .*사용자 정보 검증에 실패하였습니다/);
  assert.doesNotMatch(out, /결과 없음/);
});

// ---- I2. 10쪽(1000행) 한도 ----

test('I2 검색 결과가 1000행을 넘어 다 읽지 못하면 실패한다', async () => {
  const many = Array.from({ length: 100 }, (_, i) => row(`다른법${i}`, String(i), '20260101'));
  const api = fakeApi((path) => (path === 'lawSearch.do' ? page(many, 1500) : undefined));
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '주택법' }), /검색 결과가 1500건이라 다 읽지 못했다\. 이름을 더 정확히 준다/);
  assert.equal(api.calls.length, 10);
});

// ---- Minor ----

test('M2 law_name 과 미래 effective_date 로 읽어도 시행예정이라고 적는다', async () => {
  const api = fakeApi((path) => {
    if (path === 'lawSearch.do') return page([row('주택법', '289171', '20270309', '20260901'), row('주택법', '289171', '20260908', '20260301')]);
    if (path === 'lawService.do') return body('주택법', '20270309', [unit('1', '제1조')]);
  });
  const out = await makeRunTool({ callApi: api, today: TODAY })('get_law_text', { law_name: '주택법', effective_date: '2027-03-09' });
  assert.equal(header2(out), '시행일: 20270309 (2027-03-09 시점 시행 판, 시행예정)');
});

test('M5 없는 조문 번호로 비어 오면 그 판에 조문이 없을 수 있다고 안내한다', async () => {
  const api = fakeApi((path) => {
    if (path === 'lawSearch.do') return page([row('주택법', '289171', '20260908')]);
    if (path === 'lawService.do') return { 법령: { 기본정보: { 법령명_한글: '주택법' } } };
  });
  const run = makeRunTool({ callApi: api, today: TODAY });
  await assert.rejects(run('get_law_text', { law_name: '주택법', article: '999' }), /그 판에 이 조문이 없거나 시행일자가 판과 다르다/);
});

test('M3 도구 설명: search_law 는 기본으로 시행예정 판도 보인다, get_law_outline 의 mst 는 effective_date 가 필요하다', () => {
  const t = (n) => TOOLS.find((x) => x.name === n);
  assert.match(t('search_law').description, /시행예정/);
  assert.match(t('search_law').inputSchema.properties.current.description, /시행예정/);
  assert.match(t('get_law_outline').inputSchema.properties.mst.description, /effective_date/);
});
