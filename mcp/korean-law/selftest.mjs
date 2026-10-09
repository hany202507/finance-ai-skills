/**
 * selftest — 실제 stdio 로 서버를 띄워 도구를 전부 호출한다.
 * 법제처 API 를 실제로 부르므로 LAW_OC 가 있어야 한다.
 * 실행: node selftest.mjs
 * 통과 기준은 "에러 없음"이 아니라 "기대한 문구가 응답에 실제로 들어 있음"이다.
 */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

if (!process.env.LAW_OC) {
  console.error('LAW_OC 환경변수에 본인 OC 를 넣고 실행한다. 예: LAW_OC=myid node selftest.mjs');
  process.exit(1);
}

const here = dirname(fileURLToPath(import.meta.url));
const proc = spawn(process.execPath, [join(here, 'index.js')], {
  stdio: ['pipe', 'pipe', 'inherit'],
  env: process.env,
});

let buf = '';
const pending = new Map();
proc.stdout.on('data', (c) => {
  buf += c.toString('utf8');
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id != null && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  }
});

let seq = 0;
const rpc = (method, params) =>
  new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, resolve);
    proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(`timeout: ${method}`)); } }, 45000);
  });

const call = async (name, args) => {
  const r = await rpc('tools/call', { name, arguments: args });
  const text = r.result?.content?.[0]?.text ?? JSON.stringify(r.error ?? r);
  return { text, isError: !!r.result?.isError || !!r.error };
};

let pass = 0, fail = 0;
const check = (label, ok, detail) => {
  if (ok) { pass++; console.log(`  PASS  ${label}`); }
  else { fail++; console.log(`  FAIL  ${label}\n        ${String(detail).slice(0, 300)}`); }
};

await rpc('initialize', {
  protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'selftest', version: '1' },
});
proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');

console.log('\n=== korean-law selftest ===\n');

const tools = await rpc('tools/list');
const names = (tools.result?.tools ?? []).map((t) => t.name);
check('tools/list — 12개 도구 노출', names.length === 12, names.join(','));

// 1. search_law
let r = await call('search_law', { query: '부가가치세법' });
check('search_law 부가가치세법 — MST·시행일 반환', !r.isError && /MST \d+/.test(r.text) && /시행 \d{8}/.test(r.text), r.text);

// 2. get_law_text 현행 — 회신에 인용했던 문구가 실제로 나오는지
r = await call('get_law_text', { law_name: '부가가치세법', article: '2' });
check('get_law_text 부가법 §2 — "영리이든 비영리이든" 문구 포함',
  !r.isError && r.text.includes('영리이든 비영리이든'), r.text);

// 3. get_law_text 시행령 + 조의N 형식
r = await call('get_law_text', { law_name: '소득세법 시행령', article: '12' });
check('get_law_text 소득세법 시행령 §12 — 자가운전보조금 월 20만원',
  !r.isError && r.text.includes('월 20만원') && r.text.includes('시내출장'), r.text);

// 4. 조의N 파싱
r = await call('get_law_text', { law_name: '국세기본법', article: '45의3' });
check('get_law_text 국세기본법 §45의3 — 기한 후 신고',
  !r.isError && r.text.includes('기한후과세표준신고서'), r.text);

// 5. 과거 시점 조회 — 이전 과세기간 검토에 필요한 기능
r = await call('get_law_text', { law_name: '부가가치세법', article: '26', effective_date: '2020-07-01' });
check('get_law_text effective_date=2020-07-01 — 그 시점 시행 버전',
  !r.isError && /시행일: 20(1|20)/.test(r.text) && r.text.includes('면세'), r.text);

// 6. amendment_track
r = await call('amendment_track', { law_name: '부가가치세법', display: 10 });
check('amendment_track — 시행일 목록 다건', !r.isError && (r.text.match(/시행 \d{8}/g) ?? []).length >= 3, r.text);

// 7. search_decisions
r = await call('search_decisions', { query: '부가가치세 면세', domain: 'prec', display: 3 });
check('search_decisions prec — ID 반환', !r.isError && /\[ID \d+\]/.test(r.text), r.text);

// 8. 에러 경로 — 없는 법령이면 조용히 빈 값이 아니라 에러여야 한다
r = await call('get_law_text', { law_name: '존재하지않는법령입니다', article: '1' });
check('없는 법령 — 에러로 보고(빈 응답 금지)', r.isError && r.text.includes('조회 실패'), r.text);

// 9. 잘못된 조문번호 형식
r = await call('get_law_text', { law_name: '소득세법', article: '열두조' });
check('잘못된 조문번호 — 형식 에러', r.isError && r.text.includes('조문번호 형식'), r.text);

// 10. scan_articles — 제목이 아니라 본문까지 훑는가
//     부가법 §60⑧(현금매출명세서·부동산임대공급가액명세서 미제출)은 "서식 미작성 가산세"의 대표 조문인데
//     조문제목에는 "가산세"만 있고 "명세서"가 없다. 제목만 보는 검색으로는 못 잡는다.
r = await call('scan_articles', { law_names: ['부가가치세법'], keywords: ['현금매출명세서'] });
check('scan_articles — 본문 매칭으로 부가법 §60 적출',
  !r.isError && /제60조/.test(r.text) && r.text.includes('현금매출명세서'), r.text);

// 11. 여러 법 동시 스윕 — 조특법에 흩어진 부가세 가산세를 잡는가
//     이게 실패하면 "부가세 가산세"를 부가법 안에서만 찾는 옛 실패로 되돌아간다.
r = await call('scan_articles', {
  law_names: ['부가가치세법', '국세기본법', '조세특례제한법'],
  keywords: ['가산세'], titles_only: true,
});
check('scan_articles 3법 스윕 — 부가법 §60 + 국기법 §47의2 + 조특법 §106의9 동시 적출',
  !r.isError && /제60조/.test(r.text) && /제47의2조/.test(r.text) && /제106의9조/.test(r.text), r.text);

// 12. 편·장·절 제목 줄이 조문으로 섞이지 않는가
//     법제처는 "제2절 가산세" 같은 절 제목을 같은 조문번호(60)로 한 번 더 준다(조문여부='전문').
//     걸러내지 않으면 "제60조 (제목 없음)"이 유령 조문으로 목록에 뜬다.
r = await call('scan_articles', { law_names: ['부가가치세법'], keywords: ['가산세'], titles_only: true });
check('scan_articles — 절 제목 줄 제외(유령 조문 없음)',
  !r.isError && !r.text.includes('(제목 없음)') && /제60조 가산세/.test(r.text), r.text);

// 13. 부분 실패가 스윕 전체를 삼키지 않는가 — 안 훑은 법이 "없는 것"으로 둔갑하면 안 된다
r = await call('scan_articles', { law_names: ['존재하지않는법령입니다', '부가가치세법'], keywords: ['가산세'], titles_only: true });
check('scan_articles 부분 실패 — 실패는 실패로 표기하고 나머지는 계속',
  !r.isError && r.text.includes('훑기 실패') && r.text.includes('확인 불가') && /제60조/.test(r.text), r.text);

// 14. get_addenda — "언제부터 적용되나"의 근거는 조문이 아니라 부칙에 있다
r = await call('get_addenda', { law_name: '부가가치세법', keywords: ['적용례', '경과조치'] });
check('get_addenda — 적용례·경과조치 적출',
  !r.isError && /부칙 <제\d+호/.test(r.text) && /적용례|경과조치/.test(r.text), r.text);

// 15. get_law_outline — 1MB 법을 안 읽고 구조를 본다
r = await call('get_law_outline', { law_name: '부가가치세법' });
check('get_law_outline — 편장절 + 조문 목차',
  !r.isError && /\[제\d+장/.test(r.text) && /제60조 가산세/.test(r.text), r.text);

// 16. 출처 URL — 도구가 링크를 안 주면 모델이 지어낸다
r = await call('get_law_text', { law_name: '부가가치세법', article: '60' });
check('get_law_text — 출처 URL 자동 부착(한글 그대로, 조문까지)',
  !r.isError && r.text.includes('출처: https://www.law.go.kr/법령/부가가치세법/제60조'), r.text.slice(-200));

// 17. 띄어쓰기 있는 법령명 — raw 로는 400 이라 공백만 인코딩해야 한다
r = await call('get_law_text', { law_name: '상속세 및 증여세법', article: '78' });
check('출처 URL — 띄어쓰기 법령명은 %20 로',
  !r.isError && r.text.includes('상속세%20및%20증여세법'), r.text.slice(-200));

// 18. 국세청 예규·조세심판원 — 오래 "법제처 API 범위 밖"이라 적어 두었으나 사실이 아니었다
r = await call('search_rulings', { query: '세금계산서합계표 가산세', display: 3 });
check('search_rulings — 국세청 예규 + 조세심판원 동시 검색',
  !r.isError && /국세청 법령해석/.test(r.text) && /조세심판원 결정례/.test(r.text) && /\[nts:\d+\]/.test(r.text), r.text);

// 19. 조세심판원 본문 — 재결요지·주문까지
r = await call('get_ruling', { id: '110296', source: 'tribunal' });
check('get_ruling 조세심판원 — 재결요지·주문 본문',
  !r.isError && r.text.includes('재결요지') && r.text.includes('주문'), r.text.slice(0, 200));

// 20. 법-령-칙 연계 — 부가법 §60⑩ 이 법인세법·소득세법을 끌어오는 것을 자동으로 잇는가
r = await call('trace_references', { law_name: '부가가치세법', article: '60' });
check('trace_references — 타법 인용(법인세법 §75의6·소득세법 §81의9) 적출',
  !r.isError && /법인세법.*제75의6조/s.test(r.text) && /소득세법.*제81의9조/s.test(r.text), r.text.slice(0, 400));

// 21. 시행령 역참조 — 법-령 연결의 실제 표현
check('trace_references — 시행령 역참조(§108 가산세) 적출',
  /시행령에서 이 조문을 되부르는 조문/.test(r.text) && /제108조/.test(r.text), r.text.slice(0, 600));

// 22. 못 푼 것을 숨기지 않는가 — 조용한 0 이 가장 위험하다
check('trace_references — 모호참조 미해결 건수 보고',
  /풀지 못한 모호참조 \d+건/.test(r.text), r.text.slice(-300));

// 23. 별표·서식 — "서식 미작성" 쟁점에서 그 서식이 무엇인지
r = await call('search_forms', { query: '소득세법', display: 5 });
check('search_forms — 별표·서식 목록과 링크',
  !r.isError && /\[(별표|서식)\]/.test(r.text) && /추측하지 마라/.test(r.text), r.text.slice(0, 300));

// 24. 국세청 예규 본문은 막혀 있다 — 막힌 것을 막혔다고 보고하는가(본문 지어내기 금지)
r = await call('get_ruling', { id: '186576', source: 'nts' });
check('get_ruling 국세청 — 차단을 숨기지 않고 원인·링크 안내',
  !r.isError && /본문을 받지 못했다/.test(r.text) && /추측해 쓰지 마라/.test(r.text), r.text.slice(0, 300));

// ---- 2026-10-09 결함 회귀 ----
const today8 = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10).replace(/-/g, '');
const head = (text, key) => (text.match(new RegExp(`^${key}: (.+)$`, 'm')) ?? [])[1] ?? '';

r = await call('get_law_text', { law_name: '주택법', article: '63의2' });
check('주택법을 다른 법으로 찾지 않는다', !r.isError && head(r.text, '법령') === '주택법', r.text);
const dateLine = head(r.text, '시행일').match(/^(\d{8}) \(오늘 (\d{8}) 기준 시행 중인 판\)$/);
check('날짜 없는 조회의 시행일 줄이 「오늘 … 기준 시행 중인 판」 형식이고 오늘이 서울 오늘이다', !!dateLine && dateLine[2] === today8, r.text);

// 오늘 시행 판은 도구 코드를 거치지 않고 법제처 원 응답에서 따로 구한다(공포일이 아니라 시행일 기준, 시행 전 판 제외)
async function rawInForce(lawName, date8) {
  const squash = (x) => String(x ?? '').replace(/\s+/g, '');
  const rows = [];
  for (let page = 1; page <= 10; page++) {
    const u = new URL('https://www.law.go.kr/DRF/lawSearch.do');
    for (const [k, v] of Object.entries({ OC: process.env.LAW_OC, type: 'JSON', target: 'eflaw', query: lawName, nw: '2,3', display: 100, page })) u.searchParams.set(k, String(v));
    const d = await (await fetch(u)).json();
    const got = [d?.LawSearch?.law ?? []].flat().filter((x) => x && typeof x === 'object');
    rows.push(...got);
    if (!got.length || rows.length >= Number(d?.LawSearch?.totalCnt ?? rows.length)) break;
  }
  const inForce = rows
    .filter((x) => squash(x['법령명한글']) === squash(lawName) && String(x['시행일자']) <= date8)
    .sort((a, b) => String(b['시행일자']).localeCompare(String(a['시행일자'])) || String(b['공포일자']).localeCompare(String(a['공포일자'])));
  return inForce.length ? String(inForce[0]['시행일자']) : '';
}
const maskKey = (s) => String(s).split(process.env.LAW_OC).join('***');
let expectedEf = '', rawErr = '';
try { expectedEf = await rawInForce('주택법', today8); } catch (e) { rawErr = maskKey(e.message); }
check('날짜 없는 조회의 시행일이 원 응답에서 따로 구한 오늘 시행 판과 같다',
  !rawErr && expectedEf !== '' && head(r.text, '시행일').slice(0, 8) === expectedEf,
  rawErr ? `원 응답 조회 실패: ${rawErr}` : `기대 ${expectedEf} / 실제 ${head(r.text, '시행일')}`);

r = await call('get_law_text', { law_name: '상법', article: '1' });
check('상법을 다른 법으로 찾지 않는다', !r.isError && head(r.text, '법령') === '상법', r.text);

r = await call('amendment_track', { law_name: '주택법' });
check('amendment_track 주택법', r.text.startsWith('주택법 —'), r.text);

r = await call('get_law_text', { law_name: '없는법령이름시험' });
check('없는 이름은 다른 법을 주지 않고 실패한다', r.isError && r.text.includes('이름이 정확히 같은 법령이 없다'), r.text);

// 목·세목 누락: 법제처 원 응답의 목내용이 출력에 모두 있는지
async function rawUnits(mst, efYd, jo) {
  const u = new URL('https://www.law.go.kr/DRF/lawService.do');
  for (const [k, v] of Object.entries({ OC: process.env.LAW_OC, type: 'JSON', target: 'eflaw', MST: mst, efYd, JO: jo })) u.searchParams.set(k, v);
  return (await (await fetch(u)).json()).법령.조문.조문단위;
}
function mokTexts(node, inside = false, out = []) {
  if (typeof node === 'string') { if (inside) { const x = node.replace(/<[^>]+>/g, '').trim(); if (x) out.push(x); } return out; }
  if (Array.isArray(node)) { node.forEach((n) => mokTexts(n, inside, out)); return out; }
  if (node && typeof node === 'object') for (const [k, v] of Object.entries(node)) mokTexts(v, inside || k === '목내용', out);
  return out;
}
for (const [law, art, jo] of [['소득세법', '104', '010400'], ['소득세법 시행령', '167의3', '016703']]) {
  const t2 = await call('get_law_text', { law_name: law, article: art });
  const mst = head(t2.text, 'MST');
  const ef = head(t2.text, '시행일').slice(0, 8);
  let want;
  try { want = mokTexts(await rawUnits(mst, ef, jo)); } catch (e) {
    check(`${law} 제${art}조 목이 모두 출력에 있다`, false, `원 응답 조회 실패: ${maskKey(e.message)}`);
    continue;
  }
  const missing = want.filter((x) => !t2.text.includes(x));
  check(`${law} 제${art}조 목 ${want.length}개가 모두 출력에 있다`, want.length > 0 && missing.length === 0, missing.slice(0, 3).join(' | '));
}

// OC 노출: 링크가 실제로 나오는 도구로 본다(링크가 없으면 가릴 것이 없어 항상 통과한다). 실패 때 값을 찍지 않도록 detail 은 고정 문구다
const leaksOC = (text) => text.includes(process.env.LAW_OC) || /OC=(?!\*\*\*)/.test(text);
r = await call('search_rulings', { query: '양도소득세', source: 'nts', display: 5 });
check('search_rulings 출력에 링크가 있고 OC 가 섞이지 않는다', !r.isError && /http/.test(r.text) && !leaksOC(r.text), 'OC 노출 또는 링크 없음');
r = await call('search_forms', { query: '양도소득과세표준' });
check('search_forms 출력에 링크가 있고 OC 가 섞이지 않는다', !r.isError && /http/.test(r.text) && !leaksOC(r.text), 'OC 노출 또는 링크 없음');
// 위 두 도구의 링크는 실제로는 OC 가 없는 주소(taxlaw.nts.go.kr, flDownload)만 골라 쓴다. 가림 처리를 빼도 통과하므로
// 입력을 되풀이하는 오류 문구에 OC 를 실어 마스킹 자체가 동작하는지도 본다(가림을 빼면 실패한다)
r = await call('get_law_text', { law_name: `OC=${process.env.LAW_OC}` });
check('입력으로 들어온 OC 가 오류 문구에 되풀이돼도 가려진다', r.isError && r.text.includes('OC=***') && !leaksOC(r.text), 'OC 노출 또는 되풀이 없음');

console.log(`\n결과: ${pass} PASS / ${fail} FAIL\n`);
proc.kill();
process.exit(fail ? 1 : 0);
