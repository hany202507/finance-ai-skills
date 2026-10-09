import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  flattenArticle, joCode, normName, pickExact, pickInForce, todaySeoul, ymd, maskSecrets,
  lawUrl, articleLabel, pickInForceRenamed,
} from '../lib.mjs';

const fx = (f) => JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'fixtures', f), 'utf8'));

// 독립 판정기: 내용 키 아래 문자열을 구현과 다른 방법으로 전부 모은다
const KEYS = new Set(['조문내용', '항내용', '호내용', '목내용']);
function oracle(node, inside = false, out = []) {
  if (typeof node === 'string') { if (inside) { const t = node.replace(/<[^>]+>/g, '').replace(/\r/g, '').trim(); if (t) out.push(t); } return out; }
  if (Array.isArray(node)) { node.forEach((n) => oracle(n, inside, out)); return out; }
  if (node && typeof node === 'object') for (const [k, v] of Object.entries(node)) oracle(v, inside || KEYS.has(k), out);
  return out;
}

// 목내용이 배열로 온 곳의 수. fixture 가 이 경우를 실제로 담고 있어야 아래 시험이 뜻이 있다
function arrayMok(node, n = { c: 0 }) {
  if (Array.isArray(node)) { node.forEach((x) => arrayMok(x, n)); return n.c; }
  if (node && typeof node === 'object') for (const [k, v] of Object.entries(node)) { if (k === '목내용' && Array.isArray(v)) n.c++; arrayMok(v, n); }
  return n.c;
}

for (const f of ['소득세법_104.json', '소득세법시행령_167의3.json']) {
  test(`flattenArticle 이 ${f} 의 항·호·목 문장을 하나도 빠뜨리지 않는다`, () => {
    const units = fx(f).법령.조문.조문단위;
    assert.ok(oracle(units).length > 0, 'fixture 에 문장이 없다');
    assert.ok(arrayMok(units) >= 1, 'fixture 에 배열 목내용이 없다');
    const got = new Set(flattenArticle(units));
    const missing = oracle(units).filter((t) => !got.has(t));
    assert.deepEqual(missing.slice(0, 5), [], `빠진 문장 ${missing.length}개`);
  });
}

test('lawUrl 은 가지 조문을 law.go.kr 한글주소 형식(제104조의3)으로 만든다', () => {
  assert.equal(lawUrl('소득세법', '104의3'), 'https://www.law.go.kr/법령/소득세법/제104조의3');
  assert.equal(lawUrl('소득세법', '104-3'), 'https://www.law.go.kr/법령/소득세법/제104조의3');
  assert.equal(lawUrl('국세기본법', '45-3'), lawUrl('국세기본법', '45의3'));
  assert.equal(lawUrl('소득세법', '104'), 'https://www.law.go.kr/법령/소득세법/제104조');
  assert.equal(lawUrl('상속세 및 증여세법'), 'https://www.law.go.kr/법령/상속세%20및%20증여세법');
});

test('articleLabel 은 조문 번호를 법령 표기로 쓴다', () => {
  assert.equal(articleLabel('104의3'), '제104조의3');
  assert.equal(articleLabel('104-3'), '제104조의3');
  assert.equal(articleLabel(' 60 '), '제60조');
});

const rr = (name, ef, prom, mst) => ({ 법령명한글: name, 시행일자: ef, 공포일자: prom, 공포번호: '1', 법령일련번호: mst });

test('pickInForceRenamed 는 현행 이름 판이 시행 중이면 그 이름에서, 아니면 요청한 이름에서 고른다', () => {
  const rows = [
    rr('옛법', '20080101', '20071201', 'O1'),
    rr('새법', '20090731', '20090130', 'N1'), // 개칭(공포 2009-01-30, 시행 2009-07-31)
    rr('새법', '20240109', '20240109', 'N2'),
  ];
  assert.equal(pickInForceRenamed(rows, '옛법', '새법', '20090301').법령일련번호, 'O1');
  assert.equal(pickInForceRenamed(rows, '옛법', '새법', '20240501').법령일련번호, 'N2');
  assert.equal(pickInForceRenamed(rows, '옛법', '새법', '20000101'), null);
});

test('pickInForceRenamed 는 개칭 전에 공포돼 개칭 뒤 시행된 옛 이름 판(285293)을 고르지 않는다', () => {
  const rows = [
    rr('지역균형발전법', '20261015', '20260414', '285293'),
    rr('균형성장법', '20260910', '20260609', '286737'),
    rr('균형성장법', '20260602', '20260602', '286503'),
  ];
  assert.equal(pickInForceRenamed(rows, '지역균형발전법', '균형성장법', '20261016').법령일련번호, '286737');
  assert.equal(pickInForceRenamed(rows, '지역균형발전법', '균형성장법', '20261009').법령일련번호, '286737');
});

test('pickInForceRenamed 반례 D: 개칭 공포 뒤·시행 전에 옛 이름으로 공포된 개정 Y 는 개칭 시행 뒤에 고르지 않는다', () => {
  // 개칭 R: 공포 2025-06-01, 시행 2026-01-01(새 이름). 그 사이 옛 이름 개정 Y: 공포 2025-09-01, 시행 2025-10-01
  const rows = [
    rr('옛법', '20200101', '20200101', 'O1'),
    rr('옛법', '20251001', '20250901', 'Y'),
    rr('새법', '20260101', '20250601', 'R'),
  ];
  assert.equal(pickInForceRenamed(rows, '옛법', '새법', '20260301').법령일련번호, 'R');
  assert.equal(pickInForceRenamed(rows, '옛법', '새법', '20251101').법령일련번호, 'Y');
});

test('pickInForceRenamed 는 이름이 하나이거나 현행 이름을 모르면 pickInForce 와 같다', () => {
  const one = [rr('한이름', '20260910', '20260609', 'A'), rr('한이름', '20261015', '20260414', 'B')];
  assert.equal(pickInForceRenamed(one, '한이름', '한이름', '20261016').법령일련번호, pickInForce(one, '20261016').법령일련번호);
  assert.equal(pickInForceRenamed(one, '한이름', '', '20261016').법령일련번호, pickInForce(one, '20261016').법령일련번호);
});

test('flattenArticle 은 목내용이 배열이어도 문장을 모은다', () => {
  const node = { 호: [{ 호내용: '1. 가', 목: [{ 목내용: ['가. 첫째', ['  1) 세목']] }] }] };
  assert.deepEqual(flattenArticle(node), ['1. 가', '가. 첫째', '1) 세목']);
});

test('joCode', () => {
  assert.equal(joCode('12'), '001200');
  assert.equal(joCode('45의3'), '004503');
  assert.equal(joCode('63-2'), '006302');
});

test('normName 은 공백과 가운뎃점 차이를 지운다', () => {
  assert.equal(normName('댐건설·관리 및  주변지역지원'), normName('댐건설ㆍ관리 및 주변지역지원'));
});

const row = (name, ef, prom = '20260101', no = '1') => ({ 법령명한글: name, 시행일자: ef, 공포일자: prom, 공포번호: no });

test('pickExact 는 이름이 정확히 같은 행만 고른다', () => {
  const rows = [row('민간임대주택에 관한 특별법', '20260101'), row('주택법', '20260908')];
  assert.deepEqual(pickExact(rows, '주택법').map((r) => r.법령명한글), ['주택법']);
  assert.deepEqual(pickExact(rows, '상법'), []);
});

test('pickInForce 는 기준일까지 시행된 판 중 가장 늦은 것, 같은 날이면 늦게 공포된 것', () => {
  const rows = [row('주택법', '20260908', '20260301'), row('주택법', '20270309', '20260901'), row('주택법', '20260908', '20260501', '2')];
  assert.equal(pickInForce(rows, '20261009').공포일자, '20260501');
  assert.equal(pickInForce(rows, '20270310').시행일자, '20270309');
  assert.equal(pickInForce(rows, '20200101'), null);
});

test('todaySeoul 은 UTC 15시 이후를 다음 날로 본다', () => {
  assert.equal(todaySeoul(new Date('2026-10-08T15:30:00Z')), '20261009');
  assert.equal(todaySeoul(new Date('2026-10-08T14:59:00Z')), '20261008');
});

test('ymd 는 여러 날짜 표기를 8자리로 맞춘다', () => {
  assert.equal(ymd('2026-10-09'), '20261009');
  assert.equal(ymd('20240701'), '20240701');
  assert.equal(ymd('2024.7.1'), '20240701');
  assert.equal(ymd('2024년 7월 1일'), '20240701');
});

test('ymd 는 날짜가 아니면 조용히 넘기지 않고 실패한다', () => {
  assert.throws(() => ymd('abc'), /날짜 형식이 아니다: "abc"\. YYYY-MM-DD 로 준다\./);
  assert.throws(() => ymd('2024-13-01'), /날짜 형식이 아니다/);
  assert.throws(() => ymd('2024-07-32'), /날짜 형식이 아니다/);
  assert.throws(() => ymd(''), /날짜 형식이 아니다/);
});

test('maskSecrets 는 OC 값과 OC= 파라미터를 가린다', () => {
  assert.equal(maskSecrets('a OC=abc&x abc', 'abc'), 'a OC=***&x ***');
});
