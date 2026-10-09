/**
 * 단위 시험용 법제처 응답을 다시 받는다. LAW_OC 가 필요하다.
 *   LAW_OC=<본인OC> node test/capture.mjs
 * 받을 목록은 test/targets.mjs 에 있다. 저장 전에 OC 를 가린다.
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TARGETS } from './targets.mjs';

// node --test 는 test/ 아래 파일을 전부 시험으로 실행한다. 시험은 네트워크 없이 돌아야 하고
// fixture 를 덮어쓰면 안 되므로, 시험 러너가 띄운 자식 프로세스에서는 아무것도 하지 않는다.
if (process.env.NODE_TEST_CONTEXT) process.exit(0);

const OC = process.env.LAW_OC;
if (!OC) { console.error('LAW_OC 가 없다'); process.exit(1); }
const here = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');
mkdirSync(here, { recursive: true });

for (const t of TARGETS) {
  const url = new URL(`https://www.law.go.kr/DRF/${t.path}`);
  for (const [k, v] of Object.entries({ OC, type: 'JSON', ...t.params })) url.searchParams.set(k, String(v));
  const text = await (await fetch(url)).text();
  const masked = text.replaceAll(OC, '***').replace(/OC=[^&"'\s]*/g, 'OC=***');
  JSON.parse(masked);
  writeFileSync(join(here, t.file), masked, 'utf8');
  console.log('saved', t.file, masked.length);
}
