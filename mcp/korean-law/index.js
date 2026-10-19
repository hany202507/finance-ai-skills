#!/usr/bin/env node
/**
 * korean-law — 법제처 국가법령정보 OPEN API 직결 MCP 서버 (stdio)
 *
 * 왜 있는가: 원격 법령 MCP 가 불안정해(2026-08-03 측정, 8회 중 1회 응답) 중간 호스트를
 * 걷어내고 법제처 OPEN API 를 직접 부른다. 받는 사람이 자기 OC 키 하나로 돌릴 수 있다.
 *
 * 인증: 법제처 OC 키. 환경변수 LAW_OC 로 주입한다. **기본값을 두지 않는다.**
 *   기본값이 있으면 OC 를 발급받지 않은 사람이 남의 키로 조회하면서 "설치가 됐다"고
 *   착각한다. 수용 테스트가 전부 통과해 버려 구멍을 드러내는 게 아니라 덮는다.
 *   그래서 없으면 뜨는 순간 죽는다.
 * 문서: https://open.law.go.kr/LSO/openApi/guideList.do
 */

import { readFileSync } from 'node:fs';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { maskSecrets, todaySeoul } from './lib.mjs';
import { TOOLS, makeRunTool } from './tools.mjs';

const OC = process.env.LAW_OC;
if (!OC) {
  process.stderr.write(
    'LAW_OC 가 설정되지 않았다. 법제처 OPEN API 는 OC(가입 이메일의 아이디 부분) 없이는 호출할 수 없다.\n' +
    'MCP 등록 시 환경변수로 준다:\n' +
    '  claude mcp add -s user korean-law -e LAW_OC=<본인OC> -- node "<설치경로>/korean-law/index.js"\n' +
    'OC 발급: https://open.law.go.kr 회원가입 → OPEN API 활용신청 (승인 1~2일)\n',
  );
  process.exit(1);
}
const BASE = 'https://www.law.go.kr/DRF';
// 조세특례제한법 전문이 1MB라 30초로는 부하가 겹칠 때 끊긴다(selftest 에서 실측).
const TIMEOUT_MS = Number(process.env.LAW_TIMEOUT_MS || 45000);

/* ---------------------------------------------------------------- fetch */

/**
 * 법제처는 응답 인코딩이 일정하지 않다(UTF-8 / EUC-KR 혼재).
 * UTF-8로 먼저 풀고, JSON 파싱이 깨지면 EUC-KR로 다시 푼다.
 */
async function callApi(path, params) {
  const url = new URL(`${BASE}/${path}`);
  url.searchParams.set('OC', OC);
  url.searchParams.set('type', 'JSON');
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  }

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), TIMEOUT_MS);
  let buf;
  try {
    const res = await fetch(url, { signal: ac.signal });
    if (!res.ok) throw new Error(`법제처 API HTTP ${res.status} — ${url.pathname}${url.search.replace(OC, '***')}`);
    buf = Buffer.from(await res.arrayBuffer());
  } finally {
    clearTimeout(timer);
  }

  for (const enc of ['utf-8', 'euc-kr']) {
    try {
      return JSON.parse(new TextDecoder(enc).decode(buf));
    } catch { /* 다음 인코딩으로 */ }
  }
  // JSON이 아니면 법제처가 HTML 오류 페이지를 준 것이다 — 지원하지 않는 target 조합일 때 그렇다.
  const head = new TextDecoder('utf-8').decode(buf).slice(0, 200).replace(/\s+/g, ' ');
  throw new Error(`법제처 API가 JSON이 아닌 응답을 반환했다(지원하지 않는 조회 조합일 수 있음). 앞부분: ${head}`);
}

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
const runTool = makeRunTool({ callApi, today: () => todaySeoul() });

const server = new Server(
  { name: pkg.name, version: pkg.version },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  try {
    const text = await runTool(req.params.name, req.params.arguments ?? {});
    return { content: [{ type: 'text', text: maskSecrets(text, OC) }] };
  } catch (err) {
    // 실패를 조용히 삼키면 회신에 "확인 불가"가 아니라 빈칸이 들어간다. 그래서 그대로 올린다.
    return { content: [{ type: 'text', text: maskSecrets(`조회 실패: ${err.message}`, OC) }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
