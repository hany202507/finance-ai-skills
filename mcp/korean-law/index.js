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

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

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

const strip = (s) => String(s ?? '').replace(/<[^>]+>/g, '').replace(/\r/g, '').trim();

/**
 * 법제처는 "일치하는 판례가 없습니다" 같은 안내를 **객체가 아니라 맨 문자열**로 돌려줄 때가 있다.
 * 그걸 그대로 Object.entries() 에 넣으면 문자열이 글자 단위로 쪼개져
 * `■ 0 / 일`, `■ 1 / 치` … 처럼 **가짜 본문 30개**가 만들어진다.
 * "없다"가 "내용이 있다"로 둔갑하는 것이라, 이 설계가 막으려는 실패 그 자체다.
 * 맨 문자열이면 안내문으로 보고 그대로 돌려준다.
 */
function bareMessage(root) {
  if (typeof root === 'string') return strip(root) || '빈 응답';
  return null;
}
const asArray = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

/** 조문번호 "12" → "001200", "45-3"·"45의3" → "004503" */
function joCode(article) {
  const m = String(article).trim().match(/^(\d+)\s*(?:[-의]\s*(\d+))?$/);
  if (!m) throw new Error(`조문번호 형식이 아니다: "${article}" (예: "12", "45의3", "45-3")`);
  return m[1].padStart(4, '0') + (m[2] ? m[2].padStart(2, '0') : '00');
}

/** 응답 트리에서 조문/항/호/목 텍스트만 순서대로 긁는다 */
function flattenArticle(node, out = []) {
  if (Array.isArray(node)) { for (const n of node) flattenArticle(n, out); return out; }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      if (typeof v === 'string' && ['조문내용', '항내용', '호내용', '목내용'].includes(k)) {
        const t = strip(v);
        if (t) out.push(t);
      } else flattenArticle(v, out);
    }
  }
  return out;
}

/**
 * 인용용 법제처 원문 링크.
 * 도구가 링크를 주지 않으면 모델이 링크를 지어낸다. 그래서 모든 조회 응답 끝에 붙인다.
 */
function lawUrl(lawName, article) {
  // 한글 경로는 그대로 두고 공백만 인코딩한다("상속세 및 증여세법" 은 raw 로는 400).
  // 퍼센트 인코딩된 URL 은 사람이 못 읽어서 회신에 붙었을 때 검증이 안 된다.
  const base = `https://www.law.go.kr/법령/${String(lawName ?? '').trim().replace(/ /g, '%20')}`;
  return article ? `${base}/제${String(article).replace(/-/g, '의')}조` : base;
}

/** 조문단위 → get_law_text 의 article 에 그대로 넣을 수 있는 표기 ("60", "75의8") */
function articleRef(u) {
  const branch = Number(u?.['조문가지번호'] ?? 0);
  return `${u?.['조문번호']}${branch ? `의${branch}` : ''}`;
}

/* ------------------------------------------------------------- 법령 조회 */

async function resolveLaw(lawName, effectiveDate) {
  const target = effectiveDate ? 'eflaw' : 'law';
  const d = await callApi('lawSearch.do', { target, query: lawName, display: 20 });
  let rows = asArray(d?.LawSearch?.law).filter((r) => r && typeof r === 'object');
  if (!rows.length) throw new Error(`법령을 찾지 못했다: "${lawName}"`);

  // 법령명 완전일치를 우선한다 ("소득세법" 검색에 "소득세법 시행령"이 먼저 오는 것을 막는다)
  const exact = rows.filter((r) => strip(r['법령명한글']) === lawName.trim());
  if (exact.length) rows = exact;

  if (effectiveDate) {
    const target8 = effectiveDate.replace(/\D/g, '');
    // 기준일 이전에 시행된 것 중 가장 늦은 것 = 그날 시행 중이던 버전
    const inForce = rows
      .filter((r) => String(r['시행일자']) <= target8)
      .sort((a, b) => String(b['시행일자']).localeCompare(String(a['시행일자'])));
    if (!inForce.length) {
      throw new Error(`${effectiveDate} 시점에 시행 중이던 "${lawName}" 버전을 찾지 못했다. amendment_track 으로 시행일 목록을 먼저 확인하라.`);
    }
    return inForce[0];
  }
  return rows[0];
}

/* ------------------------------------------------------------------ 도구 */

const TOOLS = [
  {
    name: 'search_law',
    description:
      '법령을 이름으로 검색해 법령일련번호(MST)·시행일자·공포번호를 돌려준다. get_law_text 로 조문을 뽑기 전 단계. current=false 로 두면 과거·시행예정 버전까지 나온다.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '법령명 (예: 부가가치세법, 소득세법 시행령)' },
        current: { type: 'boolean', description: '현행만 조회(기본 true). false 면 시행일별 전체 버전', default: true },
        display: { type: 'number', description: '최대 건수 (기본 10)', default: 10 },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_law_text',
    description:
      '법령 조문 원문을 가져온다. law_name 만 주면 현행, effective_date 를 주면 그 날짜에 시행 중이던 버전을 가져온다(이전 과세기간 검토에 필수). article 을 주면 그 조문만, 없으면 법령 전체.',
    inputSchema: {
      type: 'object',
      properties: {
        law_name: { type: 'string', description: '법령명 (예: 부가가치세법). mst 를 주면 생략 가능' },
        mst: { type: 'string', description: '법령일련번호. search_law 결과의 MST' },
        article: { type: 'string', description: '조문번호. "12", "45의3", "45-3" 형식. 생략하면 전체' },
        effective_date: { type: 'string', description: '이 날짜에 시행 중이던 버전을 조회 (YYYY-MM-DD 또는 YYYYMMDD)' },
      },
    },
  },
  {
    name: 'search_rulings',
    description:
      '국세청 법령해석(예규)과 조세심판원 결정례를 검색한다. **`search_decisions`(판례·법제처해석례) 로는 이 둘이 나오지 않는다** — 세무 쟁점의 실무 적용례는 대부분 여기 있다. 조세심판원은 본문(재결요지·이유·주문·관련법령)까지 `get_ruling` 으로 읽힌다.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '검색어 (예: "세금계산서합계표 가산세")' },
        source: { type: 'string', enum: ['nts', 'tribunal', 'both'], description: 'nts=국세청 예규, tribunal=조세심판원. 기본 both', default: 'both' },
        display: { type: 'number', description: '각 통로별 최대 건수 (기본 8)', default: 8 },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_ruling',
    description:
      'search_rulings 로 찾은 예규·결정례의 본문을 가져온다. 조세심판원(source:"tribunal")은 재결요지·이유·주문·관련법령까지 전문이 온다. 국세청 예규는 본문 API 가 존재하지 않아 원문 링크만 돌려준다 — 신청으로 풀리는 문제가 아니다(법제처가 국세청 법령해석 본문을 제공하지 않는다, 2026-08-05 확인). 링크를 직접 열어 확인하고, 못 열었으면 안건명·번호·일자까지만 쓰고 본문을 추측하지 마라.',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'search_rulings 결과의 일련번호' },
        source: { type: 'string', enum: ['nts', 'tribunal'], description: '어느 통로에서 찾았는지' },
      },
      required: ['id', 'source'],
    },
  },
  {
    name: 'search_forms',
    description:
      '법령의 별표·서식 목록을 찾는다(세율표·과태료 부과기준·신고서 서식 등). **"서식 미작성·미제출" 쟁점에서 그 서식이 실제로 무엇인지** 확인할 때 쓴다. 본문은 PDF·HWP 파일이라 텍스트로 오지 않으므로 **이름과 링크만 돌려준다 — 내용을 추측하지 마라.**',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '법령명 또는 별표·서식명 (예: "소득세법", "세금계산서")' },
        display: { type: 'number', description: '최대 건수 (기본 10)', default: 10 },
      },
      required: ['query'],
    },
  },
  {
    name: 'trace_references',
    description:
      '한 조문이 **부르는 다른 조문**(같은 법 내부·타법 인용)과, 그 조문을 **되부르는 시행령·시행규칙 조문**을 함께 찾아 준다. 법-령-칙 연계와 타법 인용을 사람이 눈으로 쫓지 않게 한다(예: 부가법 §60⑩ → 법인세법 §75의6·소득세법 §81의9). 해석이 필요한 모호참조("같은 조"·"준용"·"전단")는 **풀지 못하며, 몇 건을 못 풀었는지 반드시 보고한다.**',
    inputSchema: {
      type: 'object',
      properties: {
        law_name: { type: 'string', description: '법령명 (예: 부가가치세법)' },
        article: { type: 'string', description: '조문번호 ("60", "75의8")' },
        effective_date: { type: 'string', description: '이 날짜 시행 버전 (YYYY-MM-DD)' },
        reverse: { type: 'boolean', description: '시행령·시행규칙의 역참조도 찾는다 (기본 true)', default: true },
      },
      required: ['law_name', 'article'],
    },
  },
  {
    name: 'get_addenda',
    description:
      '부칙(附則)과 제개정이유를 가져온다. **세법에서 "언제부터 적용되는가"의 근거는 조문이 아니라 부칙에 있다** — 시행일·적용례("이 법 시행 후 신고하는 분부터 적용한다")·경과조치가 전부 여기 있다. 조문만 읽고 과세기간을 판단하면 틀린다. 개정 쟁점·소급 여부·경과규정을 볼 때 반드시 부른다.',
    inputSchema: {
      type: 'object',
      properties: {
        law_name: { type: 'string', description: '법령명 (예: 부가가치세법)' },
        mst: { type: 'string', description: '법령일련번호. law_name 대신 사용 가능' },
        keywords: {
          type: 'array',
          items: { type: 'string' },
          description: '이 말이 든 부칙만 (예: ["적용례","경과조치"]). 생략하면 전부',
        },
        since: { type: 'string', description: '이 날짜 이후 공포된 부칙만 (YYYY-MM-DD)' },
        include_reason: { type: 'boolean', description: '제개정이유도 함께 (기본 true)', default: true },
      },
    },
  },
  {
    name: 'get_law_outline',
    description:
      '법령의 조문 목차(편·장·절 + 조문번호·제목)를 돌려준다. 전문을 읽지 않고 구조를 파악할 때 쓴다(조세특례제한법 전문은 1MB라 통째로 읽을 수 없다). 어느 장에 무엇이 있는지 본 뒤 scan_articles 로 좁히고 get_law_text 로 편다.',
    inputSchema: {
      type: 'object',
      properties: {
        law_name: { type: 'string', description: '법령명' },
        mst: { type: 'string', description: '법령일련번호. law_name 대신 사용 가능' },
        effective_date: { type: 'string', description: '이 날짜에 시행 중이던 버전 (YYYY-MM-DD)' },
      },
    },
  },
  {
    name: 'scan_articles',
    description:
      '여러 법령의 전문을 훑어 키워드가 들어간 조문만 골라낸다. search_law 는 법령명만 찾고 조문 본문은 검색하지 못하므로, "가산세"·"명세서"·"제출"처럼 내용으로 조문을 찾을 때는 반드시 이 도구를 쓴다. 조문제목이 아니라 항·호 본문까지 훑기 때문에 제목에 키워드가 없는 조문도 잡힌다(예: 조세특례제한법에서 "가산세"를 언급하는 조문 28개 중 제목에 있는 것은 2개뿐). 돌려주는 조문번호는 get_law_text 의 article 에 그대로 넣을 수 있다.',
    inputSchema: {
      type: 'object',
      properties: {
        law_names: {
          type: 'array',
          items: { type: 'string' },
          description: '훑을 법령명 목록 (예: ["부가가치세법", "국세기본법", "조세특례제한법"])',
        },
        keywords: {
          type: 'array',
          items: { type: 'string' },
          description: '이 중 하나라도 포함한 조문을 고른다(OR 매칭)',
        },
        effective_date: { type: 'string', description: '이 날짜에 시행 중이던 버전을 훑는다 (YYYY-MM-DD)' },
        max_snippets: { type: 'number', description: '조문당 인용할 매칭 문장 수 (기본 2)', default: 2 },
        titles_only: { type: 'boolean', description: 'true 면 조문번호·제목만 (기본 false)', default: false },
      },
      required: ['law_names', 'keywords'],
    },
  },
  {
    name: 'amendment_track',
    description:
      '한 법령의 시행일별 개정 이력을 돌려준다(시행예정 포함). 이전 기간에 어느 버전을 적용해야 하는지, 앞으로 무엇이 바뀌는지 확인할 때 쓴다.',
    inputSchema: {
      type: 'object',
      properties: {
        law_name: { type: 'string', description: '법령명' },
        display: { type: 'number', description: '최대 건수 (기본 30)', default: 30 },
      },
      required: ['law_name'],
    },
  },
  {
    name: 'search_decisions',
    description:
      '판례·법령해석례·헌재결정례를 검색한다. domain: prec(대법원 등 판례) | expc(법제처 법령해석례) | detc(헌재결정례). **국세청 예규와 조세심판원 결정은 여기서 나오지 않는다 — `search_rulings` 를 써라**(target 이 다를 뿐 법제처 API 안에 있다).',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '검색어' },
        domain: { type: 'string', enum: ['prec', 'expc', 'detc'], description: '기본 prec', default: 'prec' },
        display: { type: 'number', description: '최대 건수 (기본 10)', default: 10 },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_decision',
    description: 'search_decisions 로 찾은 판례·해석례·결정례의 본문을 가져온다.',
    inputSchema: {
      type: 'object',
      properties: {
        id: { type: 'string', description: 'search_decisions 결과의 일련번호(ID)' },
        domain: { type: 'string', enum: ['prec', 'expc', 'detc'], description: '기본 prec', default: 'prec' },
      },
      required: ['id'],
    },
  },
];

/* --------------------------------------------------------------- 실행부 */

async function runTool(name, args = {}) {
  switch (name) {
    case 'search_law': {
      const target = args.current === false ? 'eflaw' : 'law';
      const d = await callApi('lawSearch.do', { target, query: args.query, display: args.display ?? 10 });
      const rows = asArray(d?.LawSearch?.law).filter((r) => r && typeof r === 'object');
      if (!rows.length) return `"${args.query}" 에 해당하는 법령이 없다.`;
      return rows
        .map((r) =>
          [
            `${strip(r['법령명한글'])} (${strip(r['법령구분명'])})`,
            `  MST ${r['법령일련번호']} · 시행 ${r['시행일자']} · 공포 ${r['공포번호']}호(${r['공포일자'] ?? '-'}) · ${strip(r['현행연혁코드'])} ${strip(r['제개정구분명'])}`,
            `  소관 ${strip(r['소관부처명'])}`,
            // 출처 URL 은 근거등급 ★★★ 의 유일한 증거다. 한 도구라도 빠지면
            // "링크가 없네"가 아니라 모델이 링크를 지어내는 쪽으로 간다.
            `  출처: ${lawUrl(strip(r['법령명한글']))}`,
          ].join('\n'),
        )
        .join('\n\n');
    }

    case 'get_law_text': {
      let mst = args.mst;
      let meta = null;
      if (!mst) {
        if (!args.law_name) throw new Error('law_name 또는 mst 중 하나는 있어야 한다.');
        meta = await resolveLaw(args.law_name, args.effective_date);
        mst = meta['법령일련번호'];
      }
      // eflaw 는 efYd 가 "그 버전의 실제 시행일자"와 정확히 같아야 조문을 돌려준다.
      // 사용자가 준 기준일(예: 2020-07-01)을 그대로 넘기면 조문이 빈 채로 온다.
      const efYd = meta?.['시행일자'] ?? args.effective_date?.replace(/\D/g, '');
      const params = { target: args.effective_date ? 'eflaw' : 'law', MST: mst };
      if (args.article) params.JO = joCode(args.article);
      if (args.effective_date && efYd) params.efYd = efYd;

      let d = await callApi('lawService.do', params);
      let units = asArray(d?.법령?.조문?.조문단위);
      // eflaw 가 비어 오면 같은 MST 를 law 로 다시 친다(구버전도 MST 로 조회된다).
      if (!units.length && params.target === 'eflaw') {
        d = await callApi('lawService.do', { target: 'law', MST: mst, ...(params.JO ? { JO: params.JO } : {}) });
        units = asArray(d?.법령?.조문?.조문단위);
      }
      const info = d?.법령?.기본정보 ?? {};

      const wanted = args.article ? String(args.article).match(/^(\d+)/)[1] : null;
      const picked = wanted ? units.filter((u) => String(u?.조문번호) === wanted) : units;
      const body = flattenArticle(picked.length ? picked : units).join('\n');

      const header = [
        `법령: ${strip(info['법령명_한글'] ?? meta?.['법령명한글'] ?? args.law_name ?? '')}`,
        `시행일: ${strip(info['시행일자'] ?? meta?.['시행일자'] ?? '')}`,
        `공포: ${strip(info['공포번호'] ?? meta?.['공포번호'] ?? '')}호 (${strip(info['공포일자'] ?? meta?.['공포일자'] ?? '')}) ${strip(info['제개정구분'] ?? '')}`,
        `MST: ${mst}`,
        args.effective_date ? `※ ${args.effective_date} 시점 시행 버전으로 조회함` : null,
        '─'.repeat(50),
      ].filter(Boolean).join('\n');

      const lawNameOut = strip(info['법령명_한글'] ?? meta?.['법령명한글'] ?? args.law_name ?? '');
      const cite = `\n출처: ${lawUrl(lawNameOut, args.article)}`;
      if (!body) return `${header}\n(해당 조문의 본문을 받지 못했다. article 번호를 확인하라.)${cite}`;
      return `${header}\n${body}${cite}`;
    }

    case 'search_rulings': {
      // 국세청 예규·조세심판원 결정은 판례(prec)·법제처해석례(expc) 와 target 이 다르다.
      // 오래 "법제처 API 범위 밖" 이라고 적어 두었으나 사실이 아니었다(2026-08-05 확인).
      const SRC = {
        nts: { target: 'ntsCgmExpc', row: 'cgmExpc', label: '국세청 법령해석(예규)' },
        tribunal: { target: 'ttSpecialDecc', row: 'decc', label: '조세심판원 결정례' },
      };
      const want = args.source === 'nts' ? ['nts'] : args.source === 'tribunal' ? ['tribunal'] : ['nts', 'tribunal'];
      const out = [];
      for (const key of want) {
        const s = SRC[key];
        try {
          const d = await callApi('lawSearch.do', { target: s.target, query: args.query, display: args.display ?? 8 });
          const root = Object.values(d ?? {})[0] ?? {};
          const rows = asArray(root[s.row]).filter((r) => r && typeof r === 'object');
          const total = root.totalCnt ?? '?';
          if (!rows.length) { out.push(`■ ${s.label} — 결과 없음 (총 ${total})`); continue; }
          const body = rows.map((r) => {
            const id = r['법령해석일련번호'] ?? r['특별행정심판재결례일련번호'] ?? '';
            const title = strip(r['안건명'] ?? r['사건명'] ?? '');
            const no = strip(r['안건번호'] ?? r['청구번호'] ?? '');
            const date = strip(r['해석일자'] ?? r['의결일자'] ?? '');
            const link = strip(r['법령해석상세링크'] ?? '');
            return [
              `  [${key}:${id}] ${title}`,
              `      ${no} · ${date}${r['재결구분명'] ? ' · ' + strip(r['재결구분명']) : ''}`,
              link.startsWith('http') ? `      ${link}` : null,
            ].filter(Boolean).join('\n');
          }).join('\n');
          out.push(`■ ${s.label} — ${rows.length}건 (총 ${total})\n${body}`);
        } catch (err) {
          out.push(`■ ${s.label} — 검색 실패: ${err.message}\n  ※ 이 통로는 확인되지 않았다. "확인 불가"로 남겨라.`);
        }
      }
      return [
        `"${args.query}" 예규·결정례`,
        '─'.repeat(50),
        ...out,
        '',
        '※ 예규·결정례는 법원(法源)이 아니라 과세관청·심판기관의 판단이다. 조문을 먼저 대라.',
        '  본문은 get_ruling(id, source) 로.',
      ].join('\n');
    }

    case 'get_ruling': {
      const target = args.source === 'nts' ? 'ntsCgmExpc' : 'ttSpecialDecc';
      let d;
      try {
        d = await callApi('lawService.do', { target, ID: args.id });
      } catch (err) {
        // 국세청 예규는 본문 API 가 없다(아래 안내문). 조세심판원도 실패할 수 있다.
        // 못 받았으면 링크만 안내한다. 본문을 지어내는 것이 최악이다.
        return [
          `본문을 받지 못했다 (${args.source} / ID ${args.id}).`,
          `사유: ${err.message}`,
          args.source === 'nts'
            ? [
                '국세청 법령해석은 **목록만 제공된다. 본문 API 자체가 없다**(2026-08-05 확인).',
                '법제처 신청 화면에 국세청만 본문 체크박스가 없고, 국세청 OpenAPI 는 사업자등록 확인용뿐이다.',
                '신청으로 풀리는 문제가 아니다.',
                '→ 목록이 주는 taxlaw.nts.go.kr 링크를 **브라우저로 열면** 요지·회신·상세내용이 다 보인다.',
                '   읽었으면 그 내용을 인용하고, 안 읽었으면 근거등급 ★★☆ 로 남겨라.',
                '**본문을 추측해 쓰지 마라.**',
              ].join('\n')
            : '원문: https://www.law.go.kr/ 에서 청구번호로 확인하라. **본문을 추측해 쓰지 마라.**',
        ].join('\n');
      }
      const root = Object.values(d ?? {})[0] ?? {};
      const bare = bareMessage(root);
      if (bare) return `${args.id} — 법제처 응답: ${bare}\n**본문을 추측해 쓰지 마라.**`;
      const parts = [];
      for (const [k, v] of Object.entries(root)) {
        if (typeof v === 'string' && strip(v)) parts.push(`■ ${k}\n${strip(v)}`);
      }
      if (!parts.length) return `ID ${args.id} (${args.source}) 본문이 비어 있다. 원문 링크로 확인하라. 본문 추측 금지.`;
      return parts.join('\n\n') + '\n\n※ 예규·결정례는 법원(法源)이 아니다. 조문 근거를 함께 대라.';
    }

    case 'search_forms': {
      const d = await callApi('lawSearch.do', { target: 'licbyl', query: args.query, display: args.display ?? 10 });
      const root = Object.values(d ?? {})[0] ?? {};
      const rows = asArray(root.licbyl).filter((r) => r && typeof r === 'object');
      if (!rows.length) return `"${args.query}" 별표·서식 검색 결과가 없다 (총 ${root.totalCnt ?? 0}).`;
      const body = rows.map((r) => {
        const kind = strip(r['별표종류']);
        const link = strip(r['별표서식PDF파일링크'] ?? r['별표서식파일링크'] ?? r['별표법령상세링크'] ?? '');
        return [
          `  [${kind || '별표'}] ${strip(r['별표명'])}`,
          `      ${strip(r['관련법령명'])}${r['별표번호'] ? ` 별표 ${strip(r['별표번호'])}` : ''}`,
          link ? `      ${link.startsWith('http') ? link : 'https://www.law.go.kr' + link}` : null,
        ].filter(Boolean).join('\n');
      }).join('\n');
      return [
        `"${args.query}" 별표·서식 ${rows.length}건 (총 ${root.totalCnt ?? '?'})`,
        '─'.repeat(50),
        body,
        '',
        '※ 본문은 PDF·HWP 파일이라 텍스트로 오지 않는다. 링크로 확인하고 **내용을 추측하지 마라.**',
      ].join('\n');
    }

    case 'trace_references': {
      const meta = await resolveLaw(args.law_name, args.effective_date);
      const mst = meta['법령일련번호'];
      const lawName = strip(meta['법령명한글']);
      const params = { target: args.effective_date ? 'eflaw' : 'law', MST: mst, JO: joCode(args.article) };
      if (args.effective_date) params.efYd = meta['시행일자'];
      let d = await callApi('lawService.do', params);
      let units = asArray(d?.법령?.조문?.조문단위);
      if (!units.length) {
        d = await callApi('lawService.do', { target: 'law', MST: mst, JO: params.JO });
        units = asArray(d?.법령?.조문?.조문단위);
      }
      const wanted = String(args.article).match(/^(\d+)/)[1];
      const picked = units.filter((u) => String(u?.조문번호) === wanted);
      const text = flattenArticle(picked.length ? picked : units).join('\n');
      if (!text) throw new Error(`${lawName} 제${args.article}조 본문을 받지 못했다.`);

      // 1) 타법 인용: 「법인세법」 제75조의6  2) 내부 인용: 제39조제1항
      const cross = new Map();
      for (const m of text.matchAll(/「([^」]+)」\s*제(\d+)조(?:의(\d+))?/g)) {
        const ref = `${m[2]}${m[3] ? '의' + m[3] : ''}`;
        cross.set(`${m[1]}|${ref}`, { law: m[1], art: ref });
      }
      const inner = new Set();
      for (const m of text.matchAll(/(?<!」\s*)제(\d+)조(?:의(\d+))?/g)) {
        const ref = `${m[1]}${m[2] ? '의' + m[2] : ''}`;
        if (ref !== String(args.article).replace(/-/g, '의')) inner.add(ref);
      }
      // 3) 풀지 못하는 참조 — 숫자를 반드시 보고한다. 조용히 빠지면 "연결이 없다"로 읽힌다.
      const vague = (text.match(/같은 (조|항|호|법|목)|준용|전단|후단|각 목|대통령령으로 정하는|기획재정부령으로 정하는/g) ?? []).length;

      const lines = [`${lawName} 제${args.article}조 — 참조 관계`, `  ${lawUrl(lawName, args.article)}`, '─'.repeat(50)];

      lines.push(`■ 이 조문이 부르는 타법 조문 ${cross.size}건`);
      for (const { law, art } of cross.values()) {
        let title = '';
        try {
          const m2 = await resolveLaw(law, args.effective_date);
          const d2 = await callApi('lawService.do', { target: 'law', MST: m2['법령일련번호'], JO: joCode(art) });
          const u2 = asArray(d2?.법령?.조문?.조문단위).find((u) => (u?.['조문여부'] ?? '조문') === '조문');
          title = strip(u2?.['조문제목'] ?? '');
        } catch { title = '(조회 실패)'; }
        lines.push(`  「${law}」 제${art}조 ${title}\n      ${lawUrl(law, art)}`);
      }
      if (!cross.size) lines.push('  (없음)');

      lines.push(`■ 같은 법 내부 인용 ${inner.size}건: ${inner.size ? [...inner].map((a) => `제${a}조`).join(', ') : '(없음)'}`);

      if (args.reverse !== false) {
        for (const suffix of ['시행령', '시행규칙']) {
          const sub = `${lawName} ${suffix}`;
          try {
            const m3 = await resolveLaw(sub, args.effective_date);
            const d3 = await callApi('lawService.do', { target: 'law', MST: m3['법령일련번호'] });
            const arts = asArray(d3?.법령?.조문?.조문단위).filter((u) => (u?.['조문여부'] ?? '조문') === '조문');
            const pat = new RegExp(`법 제${String(args.article).replace(/의/, '조의').replace(/^(\\d+)$/, '$1')}조`);
            const hit = arts.filter((u) => pat.test(flattenArticle(u).join(' ')));
            lines.push(`■ ${suffix}에서 이 조문을 되부르는 조문 ${hit.length}건`);
            for (const u of hit) lines.push(`  제${articleRef(u)}조 ${strip(u['조문제목']) || ''}\n      ${lawUrl(sub, articleRef(u))}`);
            if (!hit.length) lines.push('  (없음)');
          } catch {
            lines.push(`■ ${suffix} — 조회 실패. **확인되지 않았다**(없다는 뜻이 아니다).`);
          }
        }
      }

      lines.push(
        '─'.repeat(50),
        `⚠ 풀지 못한 모호참조 ${vague}건 — "같은 조/항/호", "준용", "전단·후단", "대통령령으로 정하는" 등.`,
        '  이 도구는 명시 인용만 잇는다. 위 숫자만큼은 사람이 본문을 읽어야 한다.',
      );
      return lines.join('\n');
    }

    case 'get_addenda': {
      let mst = args.mst, meta = null;
      if (!mst) {
        if (!args.law_name) throw new Error('law_name 또는 mst 중 하나는 있어야 한다.');
        meta = await resolveLaw(args.law_name);
        mst = meta['법령일련번호'];
      }
      const d = await callApi('lawService.do', { target: 'law', MST: mst });
      const name = strip(d?.법령?.기본정보?.['법령명_한글'] ?? meta?.['법령명한글'] ?? args.law_name ?? '');
      let rows = asArray(d?.법령?.부칙?.부칙단위).filter((r) => r && typeof r === 'object');
      if (!rows.length) return `${name}: 부칙을 받지 못했다.`;

      rows.sort((a, b) => String(b['부칙공포일자']).localeCompare(String(a['부칙공포일자'])));
      const since8 = args.since ? String(args.since).replace(/\D/g, '') : null;
      const keys = asArray(args.keywords).map((s) => String(s).trim()).filter(Boolean);

      const out = [];
      let skipped = 0;
      for (const r of rows) {
        const date = String(r['부칙공포일자'] ?? '');
        if (since8 && date < since8) { skipped++; continue; }
        const lines = [].concat(r['부칙내용']).flat().map(strip).filter(Boolean);
        const body = keys.length ? lines.filter((t) => keys.some((k) => t.includes(k))) : lines;
        if (!body.length) { skipped++; continue; }
        out.push(`■ 부칙 <제${r['부칙공포번호']}호, ${date}>\n` + body.map((t) => `  ${t}`).join('\n'));
      }
      if (!out.length) return `${name}: 조건에 맞는 부칙이 없다(전체 ${rows.length}건 중 ${skipped}건 제외).\n출처: ${lawUrl(name)}`;

      const head = [
        `${name} — 부칙 ${rows.length}건 중 ${out.length}건`,
        keys.length ? `키워드: ${keys.join(' / ')}` : null,
        since8 ? `${args.since} 이후 공포분` : null,
        '─'.repeat(50),
      ].filter(Boolean).join('\n');

      const tail = [];
      if (args.include_reason !== false) {
        const reason = [].concat(d?.법령?.제개정이유?.['제개정이유내용']).flat().map(strip).filter(Boolean).join(' ');
        if (reason) tail.push('─'.repeat(50), '■ 제개정이유(최근 개정)', reason.slice(0, 1500) + (reason.length > 1500 ? '…' : ''));
      }
      return [head, out.join('\n\n'), ...tail, `출처: ${lawUrl(name)}`].join('\n');
    }

    case 'get_law_outline': {
      let mst = args.mst, meta = null;
      if (!mst) {
        if (!args.law_name) throw new Error('law_name 또는 mst 중 하나는 있어야 한다.');
        meta = await resolveLaw(args.law_name, args.effective_date);
        mst = meta['법령일련번호'];
      }
      const params = { target: args.effective_date ? 'eflaw' : 'law', MST: mst };
      if (args.effective_date && meta) params.efYd = meta['시행일자'];
      let d = await callApi('lawService.do', params);
      let units = asArray(d?.법령?.조문?.조문단위);
      if (!units.length && params.target === 'eflaw') {
        d = await callApi('lawService.do', { target: 'law', MST: mst });
        units = asArray(d?.법령?.조문?.조문단위);
      }
      const info = d?.법령?.기본정보 ?? {};
      const name = strip(info['법령명_한글'] ?? meta?.['법령명한글'] ?? args.law_name ?? '');

      const lines = [];
      let arts = 0;
      for (const u of units) {
        if ((u?.['조문여부'] ?? '조문') !== '조문') {
          // 편·장·절 제목 줄. 구조를 보여주는 게 목차의 목적이니 여기서는 버리지 않는다.
          const t = strip([].concat(u['조문내용']).flat().join(' '));
          if (t) lines.push(`\n[${t}]`);
        } else {
          arts++;
          lines.push(`  제${articleRef(u)}조 ${strip(u['조문제목']) || '(제목 없음)'}`);
        }
      }
      return [
        `${name} — 조문 ${arts}개 (시행 ${strip(info['시행일자'] ?? meta?.['시행일자'] ?? '')})`,
        '─'.repeat(50),
        lines.join('\n').trim(),
        `\n출처: ${lawUrl(name)}`,
      ].join('\n');
    }

    case 'scan_articles': {
      const laws = asArray(args.law_names).map((s) => String(s).trim()).filter(Boolean);
      const keys = asArray(args.keywords).map((s) => String(s).trim()).filter(Boolean);
      if (!laws.length || !keys.length) throw new Error('law_names 와 keywords 는 각각 하나 이상이어야 한다.');
      const maxSnip = args.max_snippets ?? 2;

      const blocks = [];
      for (const lawName of laws) {
        // 한 법이 실패해도 나머지 스윕은 계속한다. 조용히 빠지면 "안 훑은 것"이 "없는 것"으로 둔갑한다.
        try {
          const meta = await resolveLaw(lawName, args.effective_date);
          const mst = meta['법령일련번호'];
          const params = { target: args.effective_date ? 'eflaw' : 'law', MST: mst };
          if (args.effective_date) params.efYd = meta['시행일자'];
          let d = await callApi('lawService.do', params);
          let units = asArray(d?.법령?.조문?.조문단위);
          if (!units.length && params.target === 'eflaw') {
            d = await callApi('lawService.do', { target: 'law', MST: mst });
            units = asArray(d?.법령?.조문?.조문단위);
          }
          // 조문여부 는 '조문' | '전문' 이다. '전문' 은 편·장·절 제목 줄("제2절 가산세")이라
          // 같은 조문번호로 한 번 더 잡혀 목록을 오염시킨다. 조문만 남긴다.
          const real = units.filter((u) => (u?.['조문여부'] ?? '조문') === '조문');

          const hits = [];
          for (const u of real) {
            const lines = [strip(u['조문제목']), ...flattenArticle(u)].filter(Boolean);
            const matched = lines.filter((t) => keys.some((k) => t.includes(k)));
            if (matched.length) hits.push({ u, matched });
          }

          const head = `■ ${strip(meta['법령명한글'])} (시행 ${meta['시행일자']}) — 조문 ${real.length}개 중 ${hits.length}개 매칭\n  ${lawUrl(strip(meta['법령명한글']))}`;
          if (!hits.length) { blocks.push(`${head}\n  (매칭 없음)`); continue; }
          const body = hits.map(({ u, matched }) => {
            const line = `  제${articleRef(u)}조 ${strip(u['조문제목']) || '(제목 없음)'}   → get_law_text(article="${articleRef(u)}")`;
            if (args.titles_only) return line;
            const snips = matched.slice(0, maxSnip).map((t) => `      · ${t.length > 220 ? t.slice(0, 220) + '…' : t}`);
            const more = matched.length > maxSnip ? `      · (매칭 문장 ${matched.length - maxSnip}개 더 있음 — 전문은 get_law_text)` : null;
            return [line, ...snips, more].filter(Boolean).join('\n');
          }).join('\n');
          blocks.push(`${head}\n${body}`);
        } catch (err) {
          blocks.push(`■ ${lawName} — 훑기 실패: ${err.message}\n  ※ 이 법령은 검토되지 않았다. "확인 불가"로 남겨라.`);
        }
      }
      return [`키워드: ${keys.join(' / ')}`, `대상 법령 ${laws.length}건`, '─'.repeat(50), ...blocks].join('\n');
    }

    case 'amendment_track': {
      const d = await callApi('lawSearch.do', { target: 'eflaw', query: args.law_name, display: args.display ?? 30 });
      let rows = asArray(d?.LawSearch?.law).filter((r) => r && typeof r === 'object');
      const exact = rows.filter((r) => strip(r['법령명한글']) === String(args.law_name).trim());
      if (exact.length) rows = exact;
      if (!rows.length) return `"${args.law_name}" 의 개정 이력을 찾지 못했다.`;
      rows.sort((a, b) => String(b['시행일자']).localeCompare(String(a['시행일자'])));
      return [
        `${strip(rows[0]['법령명한글'])} — 시행일별 개정 이력 ${rows.length}건`,
        '─'.repeat(50),
        ...rows.map(
          (r) => `시행 ${r['시행일자']} · ${strip(r['현행연혁코드'])} · ${strip(r['제개정구분명'])} · 공포 ${r['공포번호']}호(${r['공포일자'] ?? '-'}) · MST ${r['법령일련번호']}`,
        ),
      ].join('\n');
    }

    case 'search_decisions': {
      const domain = args.domain || 'prec';
      const d = await callApi('lawSearch.do', { target: domain, query: args.query, display: args.display ?? 10 });
      const root = d?.PrecSearch ?? d?.Expc ?? d?.DetcSearch ?? Object.values(d ?? {})[0];
      const rows = asArray(root?.prec ?? root?.expc ?? root?.detc).filter((r) => r && typeof r === 'object');
      if (!rows.length) return `"${args.query}" (${domain}) 검색 결과가 없다.`;
      return rows
        .map((r) => {
          const id = r['판례일련번호'] ?? r['법령해석례일련번호'] ?? r['헌재결정례일련번호'] ?? r['id'];
          const title = strip(r['사건명'] ?? r['안건명'] ?? r['사건번호'] ?? '');
          const no = strip(r['사건번호'] ?? r['안건번호'] ?? '');
          const date = strip(r['선고일자'] ?? r['회신일자'] ?? r['종국일자'] ?? '');
          const org = strip(r['법원명'] ?? r['질의기관명'] ?? r['회신기관명'] ?? '');
          return `[ID ${id}] ${title}\n  ${no} · ${date} · ${org}`;
        })
        .join('\n\n');
    }

    case 'get_decision': {
      const domain = args.domain || 'prec';
      const d = await callApi('lawService.do', { target: domain, ID: args.id });
      const root = d?.PrecService ?? d?.Expc ?? d?.DetcService ?? Object.values(d ?? {})[0] ?? {};
      const bare = bareMessage(root);
      if (bare) return `ID ${args.id} (${domain}) — 법제처 응답: ${bare}`;
      const parts = [];
      for (const [k, v] of Object.entries(root)) {
        if (typeof v === 'string' && strip(v)) parts.push(`■ ${k}\n${strip(v)}`);
      }
      return parts.length ? parts.join('\n\n') : `ID ${args.id} (${domain}) 본문을 받지 못했다.`;
    }

    default:
      throw new Error(`알 수 없는 도구: ${name}`);
  }
}

const server = new Server(
  { name: 'korean-law', version: '1.0.0' },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  try {
    const text = await runTool(req.params.name, req.params.arguments ?? {});
    return { content: [{ type: 'text', text }] };
  } catch (err) {
    // 실패를 조용히 삼키면 회신에 "확인 불가"가 아니라 빈칸이 들어간다. 그래서 그대로 올린다.
    return { content: [{ type: 'text', text: `조회 실패: ${err.message}` }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
