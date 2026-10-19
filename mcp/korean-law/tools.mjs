/**
 * korean-law 도구 정의와 실행부. 법제처 호출(callApi)과 오늘 날짜(today)를 주입받아
 * 네트워크 없이 시험할 수 있다. index.js 는 진입점(OC 확인·실제 callApi·서버 연결)만 갖는다.
 */
import {
  strip, asArray, joCode, flattenArticle, lawUrl, articleRef, articleParts, articleLabel,
  normName, pickExact, pickInForce, pickInForceRenamed, ymd, maskSecrets,
} from './lib.mjs';

/* ------------------------------------------------------------------ 도구 */

export const TOOLS = [
  {
    name: 'search_law',
    description:
      '법령을 이름으로 검색해 법령일련번호(MST)·시행일자·공포번호를 돌려준다. get_law_text 로 조문을 뽑기 전 단계. 기본(current=true)은 법령마다 오늘 시행 중인 판(현행)과 시행예정 판을 보이고, current=false 면 지난 판(연혁)까지 보인다.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '법령명 (예: 부가가치세법, 소득세법 시행령)' },
        current: { type: 'boolean', description: '기본 true: 현행 판과 시행예정 판. false 면 지난 판(연혁)까지 시행일별 전체', default: true },
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
        law_name: { type: 'string', description: '법령명 (예: 부가가치세법). 띄어쓰기·가운뎃점 차이는 무시하고 이름이 정확히 같은 법령만 쓴다' },
        mst: { type: 'string', description: '법령일련번호. 주면 effective_date 에 그 판의 시행일자를 함께 준다(search_law·amendment_track 결과의 "시행 YYYYMMDD")' },
        article: { type: 'string', description: '조문번호. "12", "45의3", "45-3" 형식. 생략하면 전체' },
        effective_date: { type: 'string', description: '이 날짜에 시행 중이던 판을 읽는다(YYYY-MM-DD). 없으면 오늘 시행 중인 판' },
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
        mst: { type: 'string', description: '법령일련번호. law_name 대신 쓸 수 있고, 주면 effective_date 에 그 판의 시행일자를 함께 준다' },
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

/* --------------------------------------------------------------- 실행부 */

export function makeRunTool({ callApi: rawCallApi, today }) {
  /**
   * 법제처는 인증 실패도 HTTP 200 에 { result: '…실패…', msg } 로 준다. 그대로 두면 루트를 못 찾아
   * 「이름이 같은 법령이 없다」·「결과 없음」으로 보고된다. 모든 호출에서 실패로 올린다.
   */
  async function callApi(path, params) {
    const d = await rawCallApi(path, params);
    if (d && typeof d === 'object' && !Array.isArray(d) && String(d.result ?? '').includes('실패')) {
      throw new Error(maskSecrets(`법제처 응답: ${strip(d.result)} ${strip(d.msg ?? '')}`.trim()));
    }
    return d;
  }

  /** eflaw 검색 결과를 끝까지(최대 10쪽) 모은다. nw: '2,3' 현행·시행예정, '1,2,3' 연혁 포함 */
  async function searchVersions(query, nw) {
    const rows = [];
    let total = 0;
    for (let page = 1; page <= 10; page++) {
      const d = await callApi('lawSearch.do', { target: 'eflaw', query, nw, display: 100, page });
      const root = d && typeof d === 'object' ? d.LawSearch : null;
      if (!root || typeof root !== 'object') {
        const keys = d && typeof d === 'object' ? Object.keys(d).join(', ') : typeof d;
        throw new Error(`법제처 응답 형식이 다르다(인증 실패일 수 있다): ${keys || '(빈 응답)'}`);
      }
      const got = asArray(root.law).filter((r) => r && typeof r === 'object');
      rows.push(...got);
      total = Number(root.totalCnt ?? rows.length);
      if (!got.length || rows.length >= total) break;
    }
    // 1000행에서 끊긴 결과로 「이름이 같은 법령이 없다」·「그날 판이 없다」를 말하면 틀린다
    if (rows.length < total) throw new Error(`검색 결과가 ${total}건이라 다 읽지 못했다. 이름을 더 정확히 준다.`);
    return rows;
  }

  function noExact(lawName, rows) {
    const names = [...new Set(rows.map((r) => strip(r['법령명한글'])))].slice(0, 8);
    return new Error(`이름이 정확히 같은 법령이 없다: "${lawName}". 비슷한 이름: ${names.join(', ') || '(없음)'}. 옛 이름이면 현행 이름으로 다시 조회하라.`);
  }

  const markOf = (r) => strip(r?.['현행연혁코드']);
  const isAbolished = (r) => /^(타법)?폐지$/.test(strip(r?.['제개정구분명']));

  /**
   * 이름이 정확히 같은 판을 모은다. 이 이름에 법제처가 「현행」으로 표시한 판이 없으면 옛 이름일 수 있으므로
   * 법령ID 로 현행 이름을 물어, 이름이 다르면 현행 이름의 판(같은 법령ID)까지 합친다.
   * 현행 이름으로 조회하면 추가 호출이 없다.
   * 돌려주는 것: rows(합친 판), current(현행 이름, 모르면 ''), notes(머리줄에 붙일 설명), unknown(현행 이름을 못 얻음)
   */
  async function versionsOf(lawName, nw) {
    const rows = await searchVersions(lawName, nw);
    let exact = pickExact(rows, lawName);
    // 현행·시행예정에 이 이름이 없으면 연혁까지 본다. 개칭·폐지된 이름은 연혁에만 있다
    if (!exact.length && nw !== '1,2,3') exact = pickExact(await searchVersions(lawName, '1,2,3'), lawName);
    if (!exact.length) throw noExact(lawName, rows);
    if (exact.some((r) => markOf(r) === '현행')) return { rows: exact, current: strip(exact[0]['법령명한글']), notes: [], unknown: false };

    const ids = [...new Set(exact.map((r) => strip(r['법령ID'])).filter(Boolean))];
    let current = '';
    if (ids.length === 1) {
      try {
        const d = await callApi('lawService.do', { target: 'eflaw', ID: ids[0], JO: '000100' });
        current = strip(d?.법령?.기본정보?.['법령명_한글']);
      } catch { current = ''; }
    }
    if (!current) return { rows: exact, current: '', notes: [], unknown: true };
    if (normName(current) === normName(lawName)) return { rows: exact, current, notes: [], unknown: false };
    const more = pickExact(await searchVersions(current, nw), current).filter((r) => strip(r['법령ID']) === ids[0]);
    return { rows: [...exact, ...more], current, notes: [`요청한 이름 "${lawName}" 은 옛 이름이다. 현행 이름: ${current}`], unknown: false };
  }

  /** 이름이 정확히 같은 법령의, date8(없으면 오늘)에 시행 중이던 판. 옛 이름이면 현행 이름의 판까지 보고 고른다 */
  async function resolveLaw(lawName, effectiveDate) {
    const date8 = effectiveDate ? ymd(effectiveDate) : today();
    const v = await versionsOf(lawName, effectiveDate ? '1,2,3' : '2,3');
    const hit = pickInForceRenamed(v.rows, lawName, v.current, date8);
    if (!hit) throw new Error(`${date8} 에 시행 중이던 "${lawName}" 판이 없다. amendment_track 으로 시행일 목록을 확인하라.`);
    if (isAbolished(hit)) {
      throw new Error(`"${lawName}" 은 ${date8} 에는 폐지된 법령이다(${strip(hit['제개정구분명'])}, 시행 ${hit['시행일자']}). 대신한 법령은 법령별칭을 확인하라.`);
    }
    const last = pickInForce(v.rows, '99999999');
    if (v.unknown && !v.rows.some((r) => ['현행', '시행예정'].includes(markOf(r))) && last === hit) {
      throw new Error(`"${lawName}" 은 개칭·폐지됐을 수 있다. 현행 이름으로 조회하거나 법령별칭을 확인하라(이 이름에 현행·시행예정 판이 없고, 고른 판 MST ${hit['법령일련번호']}(시행 ${hit['시행일자']})이 이 이름의 마지막 판이다).`);
    }
    const notes = [...v.notes];
    // 현행 이름 판을 골랐을 때, 그보다 늦게 시행된 옛 이름(요청한 이름) 판은 고르지 않지만 숨기지도 않는다
    // (개칭 전에 공포돼 개칭 뒤에 시행된 판, 지방자치분권법 MST 285293). 설명은 그 판이 실제로 옛 이름일 때만 붙인다
    const old = normName(lawName);
    const pickedOld = normName(hit['법령명한글']) === old;
    for (const r of v.rows) {
      if (!pickedOld && normName(r['법령명한글']) === old && String(r['시행일자']) > String(hit['시행일자']) && String(r['시행일자']) <= date8) {
        notes.push(`옛 이름으로 공포된 판 MST ${r['법령일련번호']}(시행 ${r['시행일자']})이 이 판보다 늦게 시행됐다. 그 개정분은 mst 로 따로 읽어 대조하라`);
      }
    }
    return { ...hit, _notes: notes };
  }

  /** 부칙용: 이름이 같은 판 중 가장 늦게 공포된 것(시행예정 부칙까지 보려고). 시행일이 아니라 공포일 순이다 */
  async function resolveLatestPromulgated(lawName) {
    const v = await versionsOf(lawName, '2,3');
    const hit = [...v.rows].sort((a, b) =>
      String(b['공포일자'] ?? '').localeCompare(String(a['공포일자'] ?? '')) ||
      Number(b['공포번호'] ?? 0) - Number(a['공포번호'] ?? 0) ||
      String(b['시행일자'] ?? '').localeCompare(String(a['시행일자'] ?? '')))[0];
    const notes = [...v.notes];
    if (v.unknown) notes.push('이 이름에 현행 판이 없다. 개칭·폐지됐을 수 있다');
    return { ...hit, _notes: notes };
  }

  /** 그 판을 eflaw 로 읽는다. 비어 오면 실패한다(공포본으로 대신 읽지 않는다) */
  async function readVersion(meta, article) {
    const params = { target: 'eflaw', MST: String(meta['법령일련번호']), efYd: String(meta['시행일자']) };
    if (article) params.JO = joCode(article);
    const d = await callApi('lawService.do', params);
    const units = asArray(d?.법령?.조문?.조문단위);
    if (!units.length) {
      const what = article
        ? `${articleLabel(article)} 본문이 비어 있다. 그 판에 이 조문이 없거나 시행일자가 판과 다르다(amendment_track·get_law_outline 으로 확인하라).`
        : '조문이 비어 있다. 시행일자가 그 판의 실제 시행일과 같은지 확인하라.';
      throw new Error(`법제처가 준 ${strip(meta['법령명한글'])} (MST ${params.MST}, 시행 ${params.efYd}) ${what} 공포본(target=law)으로 대신 읽지 않는다.`);
    }
    return { d, units };
  }

  function statusOf(ef, t) {
    return ef > t ? '시행예정' : null;
  }

  const withNotes = (s, meta) => (meta?._notes?.length ? `${s}; ${meta._notes.join('; ')}` : s);

  return async function runTool(name, args = {}) {
    const t = today();
    switch (name) {
      case 'search_law': {
        const current = args.current !== false;
        const rows = await searchVersions(args.query, current ? '2,3' : '1,2,3');
        if (!rows.length) return `"${args.query}" 에 해당하는 법령이 없다.`;
        // 법령ID 마다 오늘 시행 중인 판(현행)과 그 뒤 판(시행예정)을 고른다. 법제처의 현행·연혁 표시는 낡을 때가 있다
        const groups = new Map();
        for (const r of rows) {
          const k = r['법령ID'] ?? normName(r['법령명한글']);
          if (!groups.has(k)) groups.set(k, []);
          groups.get(k).push(r);
        }
        const list = [];
        for (const g of groups.values()) {
          const cur = pickInForce(g, t);
          if (current) {
            if (cur) list.push({ r: cur, s: '현행' });
            for (const u of g.filter((x) => String(x['시행일자']) > t)) list.push({ r: u, s: '시행예정' });
          } else {
            for (const u of g) list.push({ r: u, s: String(u['시행일자']) > t ? '시행예정' : u === cur ? '현행' : '연혁' });
          }
        }
        const want = normName(args.query);
        list.sort((a, b) => (normName(b.r['법령명한글']) === want) - (normName(a.r['법령명한글']) === want));
        return list.slice(0, args.display ?? 10).map(({ r, s }) => [
          `${normName(r['법령명한글']) === want ? '★ 이름 일치 · ' : ''}${strip(r['법령명한글'])} (${strip(r['법령구분명'])})`,
          `  MST ${r['법령일련번호']} · 시행 ${r['시행일자']} · ${s} · 공포 ${r['공포번호']}호(${r['공포일자'] ?? '-'}) · ${strip(r['제개정구분명'])}`,
          `  소관 ${strip(r['소관부처명'])}`,
          `  출처: ${lawUrl(strip(r['법령명한글']))}`,
        ].join('\n')).join('\n\n');
      }

      case 'get_law_text': {
        let meta;
        if (args.mst) {
          if (!args.effective_date) throw new Error('mst 로 조회할 때는 effective_date 에 그 판의 시행일자를 함께 준다(search_law·amendment_track 결과의 "시행 YYYYMMDD").');
          meta = { 법령일련번호: String(args.mst), 시행일자: ymd(args.effective_date), 법령명한글: args.law_name ?? '' };
        } else {
          if (!args.law_name) throw new Error('law_name 또는 mst 중 하나는 있어야 한다.');
          meta = await resolveLaw(args.law_name, args.effective_date);
        }
        const { d, units } = await readVersion(meta, args.article);
        const info = d?.법령?.기본정보 ?? {};
        const wanted = args.article ? String(args.article).match(/^(\d+)/)[1] : null;
        const picked = wanted ? units.filter((u) => String(u?.조문번호) === wanted) : units;
        const bodyText = flattenArticle(picked.length ? picked : units).join('\n');
        const ef = strip(info['시행일자'] ?? meta['시행일자']);
        const st = statusOf(ef, t) ? `, ${statusOf(ef, t)}` : '';
        const why = withNotes(args.mst
          ? `지정한 판${st}`
          : args.effective_date ? `${args.effective_date} 시점 시행 판${st}` : `오늘 ${t} 기준 시행 중인 판`, meta);
        const lawNameOut = strip(info['법령명_한글'] ?? meta['법령명한글'] ?? '');
        const header = [
          `법령: ${lawNameOut}`,
          `시행일: ${ef} (${why})`,
          `공포: ${strip(info['공포번호'] ?? meta['공포번호'] ?? '')}호 (${strip(info['공포일자'] ?? meta['공포일자'] ?? '')}) ${strip(info['제개정구분'] ?? '')}`,
          `MST: ${meta['법령일련번호']}`,
          '─'.repeat(50),
        ].join('\n');
        const cite = `\n출처: ${lawUrl(lawNameOut, args.article)}`;
        if (!bodyText) return `${header}\n(해당 조문의 본문을 받지 못했다. article 번호를 확인하라.)${cite}`;
        return `${header}\n${bodyText}${cite}`;
      }

      case 'trace_references': {
        const meta = await resolveLaw(args.law_name, args.effective_date);
        const lawName = strip(meta['법령명한글']);
        const { units } = await readVersion(meta, args.article);
        const parts = articleParts(args.article); // readVersion 의 joCode 가 형식을 이미 검사했다
        const self = `${parts.main}${parts.branch ? '의' + parts.branch : ''}`;
        const picked = units.filter((u) => String(u?.조문번호) === parts.main);
        const text = flattenArticle(picked.length ? picked : units).join('\n');
        if (!text) throw new Error(`${lawName} ${articleLabel(self)} 본문을 받지 못했다.`);
        const cross = new Map();
        for (const m of text.matchAll(/「([^」]+)」\s*제(\d+)조(?:의(\d+))?/g)) {
          const ref = `${m[2]}${m[3] ? '의' + m[3] : ''}`;
          cross.set(`${m[1]}|${ref}`, { law: m[1], art: ref });
        }
        const inner = new Set();
        for (const m of text.matchAll(/(?<!」\s*)제(\d+)조(?:의(\d+))?/g)) {
          const ref = `${m[1]}${m[2] ? '의' + m[2] : ''}`;
          if (ref !== self) inner.add(ref);
        }
        const vague = (text.match(/같은 (조|항|호|법|목)|준용|전단|후단|각 목|대통령령으로 정하는|기획재정부령으로 정하는/g) ?? []).length;
        const lines = [`${lawName} ${articleLabel(self)} — 참조 관계`, `  ${lawUrl(lawName, self)}`];
        if (meta._notes?.length) lines.push(`  (${meta._notes.join('; ')})`);
        lines.push('─'.repeat(50));
        lines.push(`■ 이 조문이 부르는 타법 조문 ${cross.size}건`);
        for (const { law, art } of cross.values()) {
          let title = '';
          try {
            const m2 = await resolveLaw(law, args.effective_date);
            const { units: u2s } = await readVersion(m2, art);
            const u2 = u2s.find((u) => (u?.['조문여부'] ?? '조문') === '조문');
            title = strip(u2?.['조문제목'] ?? '');
          } catch (e) { title = `(조회 실패: ${e.message.slice(0, 60)})`; }
          lines.push(`  「${law}」 ${articleLabel(art)} ${title}\n      ${lawUrl(law, art)}`);
        }
        if (!cross.size) lines.push('  (없음)');
        lines.push(`■ 같은 법 내부 인용 ${inner.size}건: ${inner.size ? [...inner].map(articleLabel).join(', ') : '(없음)'}`);
        if (args.reverse !== false) {
          // 시행령은 모법을 「법 제104조의3제1항」처럼 부른다. 가지 번호는 「조」 뒤에 오고,
          // 제104조의3 이 제104조의30 을, 제60조가 제60조의2 를 잡지 않게 뒤를 막는다. 「농어촌특별세법 제60조」 같은 다른 법 이름도 빼려고 앞을 막는다
          const pat = new RegExp(`(?<![가-힣])법 제${parts.main}조${parts.branch ? '의' + parts.branch : ''}(?!\\d|의\\d)`);
          for (const suffix of ['시행령', '시행규칙']) {
            const sub = `${lawName} ${suffix}`;
            try {
              const m3 = await resolveLaw(sub, args.effective_date);
              const { units: all } = await readVersion(m3);
              const arts = all.filter((u) => (u?.['조문여부'] ?? '조문') === '조문');
              const hit = arts.filter((u) => pat.test(flattenArticle(u).join(' ')));
              lines.push(`■ ${suffix}에서 이 조문을 되부르는 조문 ${hit.length}건`);
              for (const u of hit) lines.push(`  ${articleLabel(articleRef(u))} ${strip(u['조문제목']) || ''}\n      ${lawUrl(sub, articleRef(u))}`);
              if (!hit.length) lines.push('  (없음)');
            } catch {
              lines.push(`■ ${suffix} — 조회 실패. **확인되지 않았다**(없다는 뜻이 아니다).`);
            }
          }
        }
        lines.push('─'.repeat(50), `⚠ 풀지 못한 모호참조 ${vague}건 — "같은 조/항/호", "준용", "전단·후단", "대통령령으로 정하는" 등.`, '  이 도구는 명시 인용만 잇는다. 위 숫자만큼은 사람이 본문을 읽어야 한다.');
        return lines.join('\n');
      }

      case 'get_addenda': {
        let mst = args.mst, metaName = args.law_name ?? '', notes = [];
        if (!mst) {
          if (!args.law_name) throw new Error('law_name 또는 mst 중 하나는 있어야 한다.');
          const meta = await resolveLatestPromulgated(args.law_name);
          mst = meta['법령일련번호'];
          metaName = strip(meta['법령명한글']);
          notes = meta._notes ?? [];
        }
        // 부칙은 가장 늦게 공포된 판에서 읽는다. 시행예정 부칙(적용례)까지 보려고 target=law 를 쓰는 유일한 곳이다
        const d = await callApi('lawService.do', { target: 'law', MST: mst });
        const nameOut = strip(d?.법령?.기본정보?.['법령명_한글'] ?? metaName);
        let rows = asArray(d?.법령?.부칙?.부칙단위).filter((r) => r && typeof r === 'object');
        if (!rows.length) return `${nameOut}: 부칙을 받지 못했다. 「부칙 없음」이 아니다. 원문을 직접 확인하라.`;
        rows.sort((a, b) => String(b['부칙공포일자']).localeCompare(String(a['부칙공포일자'])));
        const since8 = args.since ? ymd(args.since) : null;
        const keys = asArray(args.keywords).map((s) => String(s).trim()).filter(Boolean);
        const out = [];
        let skipped = 0;
        for (const r of rows) {
          const date = String(r['부칙공포일자'] ?? '');
          if (since8 && date < since8) { skipped++; continue; }
          const lines = [].concat(r['부칙내용']).flat(Infinity).map(strip).filter(Boolean);
          const b = keys.length ? lines.filter((x) => keys.some((k) => x.includes(k))) : lines;
          if (!b.length) { skipped++; continue; }
          out.push(`■ 부칙 <제${r['부칙공포번호']}호, ${date}>\n` + b.map((x) => `  ${x}`).join('\n'));
        }
        if (!out.length) return `${nameOut}: 조건에 맞는 부칙이 없다(전체 ${rows.length}건 중 ${skipped}건 제외).\n출처: ${lawUrl(nameOut)}`;
        const head = [`${nameOut} — 부칙 ${rows.length}건 중 ${out.length}건 (MST ${mst}, 가장 늦게 공포된 판 기준)`, notes.length ? `(${notes.join('; ')})` : null, keys.length ? `키워드: ${keys.join(' / ')}` : null, since8 ? `${args.since} 이후 공포분` : null, '─'.repeat(50)].filter(Boolean).join('\n');
        const tail = [];
        if (args.include_reason !== false) {
          const reason = [].concat(d?.법령?.제개정이유?.['제개정이유내용']).flat(Infinity).map(strip).filter(Boolean).join(' ');
          if (reason) tail.push('─'.repeat(50), '■ 제개정이유(최근 개정)', reason.slice(0, 1500) + (reason.length > 1500 ? '…' : ''));
        }
        return [head, out.join('\n\n'), ...tail, `출처: ${lawUrl(nameOut)}`].join('\n');
      }

      case 'get_law_outline': {
        let meta;
        if (args.mst) {
          if (!args.effective_date) throw new Error('mst 로 조회할 때는 effective_date 에 그 판의 시행일자를 함께 준다.');
          meta = { 법령일련번호: String(args.mst), 시행일자: ymd(args.effective_date), 법령명한글: args.law_name ?? '' };
        } else {
          if (!args.law_name) throw new Error('law_name 또는 mst 중 하나는 있어야 한다.');
          meta = await resolveLaw(args.law_name, args.effective_date);
        }
        const { d, units } = await readVersion(meta);
        const info = d?.법령?.기본정보 ?? {};
        const nm = strip(info['법령명_한글'] ?? meta['법령명한글'] ?? '');
        const lines = [];
        let arts = 0;
        for (const u of units) {
          if ((u?.['조문여부'] ?? '조문') !== '조문') {
            const x = strip([].concat(u['조문내용']).flat(Infinity).join(' '));
            if (x) lines.push(`\n[${x}]`);
          } else { arts++; lines.push(`  제${articleRef(u)}조 ${strip(u['조문제목']) || '(제목 없음)'}`); }
        }
        return [`${nm} — 조문 ${arts}개 (${withNotes(`시행 ${strip(info['시행일자'] ?? meta['시행일자'])}`, meta)})`, '─'.repeat(50), lines.join('\n').trim(), `\n출처: ${lawUrl(nm)}`].join('\n');
      }

      case 'scan_articles': {
        const laws = asArray(args.law_names).map((s) => String(s).trim()).filter(Boolean);
        const keys = asArray(args.keywords).map((s) => String(s).trim()).filter(Boolean);
        if (!laws.length || !keys.length) throw new Error('law_names 와 keywords 는 각각 하나 이상이어야 한다.');
        const maxSnip = args.max_snippets ?? 2;
        const blocks = [];
        for (const lawName of laws) {
          try {
            const meta = await resolveLaw(lawName, args.effective_date);
            const { units } = await readVersion(meta);
            const real = units.filter((u) => (u?.['조문여부'] ?? '조문') === '조문');
            const hits = [];
            for (const u of real) {
              const ls = [strip(u['조문제목']), ...flattenArticle(u)].filter(Boolean);
              const matched = ls.filter((x) => keys.some((k) => x.includes(k)));
              if (matched.length) hits.push({ u, matched });
            }
            const head = `■ ${strip(meta['법령명한글'])} (${withNotes(`시행 ${meta['시행일자']}`, meta)}) — 조문 ${real.length}개 중 ${hits.length}개 매칭\n  ${lawUrl(strip(meta['법령명한글']))}`;
            if (!hits.length) { blocks.push(`${head}\n  (매칭 없음)`); continue; }
            const b = hits.map(({ u, matched }) => {
              const line = `  제${articleRef(u)}조 ${strip(u['조문제목']) || '(제목 없음)'}   → get_law_text(article="${articleRef(u)}")`;
              if (args.titles_only) return line;
              const snips = matched.slice(0, maxSnip).map((x) => `      · ${x.length > 220 ? x.slice(0, 220) + '…' : x}`);
              const more = matched.length > maxSnip ? `      · (매칭 문장 ${matched.length - maxSnip}개 더 있음 — 전문은 get_law_text)` : null;
              return [line, ...snips, more].filter(Boolean).join('\n');
            }).join('\n');
            blocks.push(`${head}\n${b}`);
          } catch (err) {
            blocks.push(`■ ${lawName} — 훑기 실패: ${err.message}\n  ※ 이 법령은 검토되지 않았다. "확인 불가"로 남겨라.`);
          }
        }
        return [`키워드: ${keys.join(' / ')}`, `대상 법령 ${laws.length}건`, '─'.repeat(50), ...blocks].join('\n');
      }

      case 'amendment_track': {
        const v = await versionsOf(args.law_name, '1,2,3');
        const exact = [...v.rows];
        const cur = pickInForceRenamed(exact, args.law_name, v.current, t);
        exact.sort((a, b) => String(b['시행일자']).localeCompare(String(a['시행일자'])) || String(b['공포일자'] ?? '').localeCompare(String(a['공포일자'] ?? '')));
        const named = v.notes.length > 0; // 이름이 둘 이상이면 줄마다 이름을 붙인다
        return [
          `${strip((cur ?? exact[0])['법령명한글'])} — 시행일별 개정 이력 ${exact.length}건 (상태는 오늘 ${t} 기준으로 계산)`,
          ...v.notes.map((n) => `(${n})`),
          '─'.repeat(50),
          ...exact.slice(0, args.display ?? 30).map((r) => {
            const s = String(r['시행일자']) > t ? '시행예정' : r === cur ? '현행' : '연혁';
            return `시행 ${r['시행일자']} · ${s} · ${strip(r['제개정구분명'])} · 공포 ${r['공포번호']}호(${r['공포일자'] ?? '-'}) · MST ${r['법령일련번호']}${named ? ` · ${strip(r['법령명한글'])}` : ''}`;
          }),
        ].join('\n');
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
  };
}
