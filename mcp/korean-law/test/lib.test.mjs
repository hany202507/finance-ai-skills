import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  flattenArticle, joCode, normName, pickExact, pickInForce, todaySeoul, ymd, maskSecrets,
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

for (const f of ['소득세법_104.json', '소득세법시행령_167의3.json']) {
  test(`flattenArticle 이 ${f} 의 항·호·목 문장을 하나도 빠뜨리지 않는다`, () => {
    const units = fx(f).법령.조문.조문단위;
    const got = new Set(flattenArticle(units));
    const missing = oracle(units).filter((t) => !got.has(t));
    assert.deepEqual(missing.slice(0, 5), [], `빠진 문장 ${missing.length}개`);
  });
}

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

test('ymd', () => assert.equal(ymd('2026-10-09'), '20261009'));

test('maskSecrets 는 OC 값과 OC= 파라미터를 가린다', () => {
  assert.equal(maskSecrets('a OC=abc&x abc', 'abc'), 'a OC=***&x ***');
});
