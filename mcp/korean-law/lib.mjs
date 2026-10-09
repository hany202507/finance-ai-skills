/**
 * korean-law 순수 함수. 네트워크를 쓰지 않아 단위 시험이 오프라인으로 돈다.
 */
export const strip = (s) => String(s ?? '').replace(/<[^>]+>/g, '').replace(/\r/g, '').trim();
export const asArray = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

/** 조문번호 "12" → "001200", "45-3"·"45의3" → "004503" */
export function joCode(article) {
  const m = String(article).trim().match(/^(\d+)\s*(?:[-의]\s*(\d+))?$/);
  if (!m) throw new Error(`조문번호 형식이 아니다: "${article}" (예: "12", "45의3", "45-3")`);
  return m[1].padStart(4, '0') + (m[2] ? m[2].padStart(2, '0') : '00');
}

const CONTENT_KEYS = new Set(['조문내용', '항내용', '호내용', '목내용']);

function pushText(v, out) {
  if (typeof v === 'string') { const t = strip(v); if (t) out.push(t); return; }
  if (Array.isArray(v)) { for (const x of v) pushText(x, out); return; }
  if (v && typeof v === 'object') flattenArticle(v, out);
}

/**
 * 조문·항·호·목 문장을 순서대로 모은다.
 * 법제처는 목내용을 문자열이 아니라 배열(표 줄마다 한 칸)로 줄 때가 있다.
 * 예전 구현은 문자열만 모아서 소득세법 제104조①11·12호 같은 목을 통째로 빠뜨렸다(2026-10-09).
 */
export function flattenArticle(node, out = []) {
  if (Array.isArray(node)) { for (const n of node) flattenArticle(n, out); return out; }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      if (CONTENT_KEYS.has(k)) pushText(v, out);
      else flattenArticle(v, out);
    }
  }
  return out;
}

/** 조문번호 "104의3"·"104-3" → { main: "104", branch: "3" }. 형식이 아니면 null */
export function articleParts(article) {
  const m = String(article ?? '').trim().match(/^(\d+)\s*(?:[-의]\s*(\d+))?$/);
  return m ? { main: String(Number(m[1])), branch: m[2] ? String(Number(m[2])) : '' } : null;
}

/** 법령 표기: "104의3"·"104-3" → "제104조의3", "60" → "제60조". 가지 번호는 「조」 뒤에 붙는다 */
export function articleLabel(article) {
  const p = articleParts(article);
  if (!p) return `제${String(article ?? '').trim()}조`;
  return `제${p.main}조${p.branch ? `의${p.branch}` : ''}`;
}

/**
 * 인용용 법제처 원문 링크.
 * 도구가 링크를 주지 않으면 모델이 링크를 지어낸다. 그래서 모든 조회 응답 끝에 붙인다.
 * 한글 경로는 그대로 두고 공백만 인코딩한다("상속세 및 증여세법" 은 raw 로는 400).
 * 퍼센트 인코딩된 URL 은 사람이 못 읽어서 회신에 붙었을 때 검증이 안 된다.
 * 가지 조문은 law.go.kr 한글주소 형식대로 "제104조의3" 이다("제104의3조" 는 오류 페이지, 2026-10-09 확인).
 */
export function lawUrl(lawName, article) {
  const base = `https://www.law.go.kr/법령/${String(lawName ?? '').trim().replace(/ /g, '%20')}`;
  return article ? `${base}/${articleLabel(article)}` : base;
}

/** 조문단위 → get_law_text 의 article 에 그대로 넣을 수 있는 표기 ("60", "75의8") */
export function articleRef(u) {
  const branch = Number(u?.['조문가지번호'] ?? 0);
  return `${u?.['조문번호']}${branch ? `의${branch}` : ''}`;
}

/** 법령명 비교용: 공백을 지우고 가운뎃점을 하나로 맞춘다 */
export const normName = (s) => strip(s).replace(/\s+/g, '').replace(/[·・]/g, 'ㆍ');

/** 이름이 정확히 같은 행만. 없으면 빈 배열(첫 행으로 대신하지 않는다) */
export function pickExact(rows, lawName) {
  const want = normName(lawName);
  return asArray(rows).filter((r) => normName(r?.['법령명한글']) === want);
}

/** date8 까지 시행된 판 중 가장 늦은 것. 같은 시행일이면 늦게 공포된 것 */
export function pickInForce(rows, date8) {
  const ok = asArray(rows).filter((r) => String(r?.['시행일자'] ?? '') <= date8);
  ok.sort((a, b) =>
    String(b['시행일자']).localeCompare(String(a['시행일자'])) ||
    String(b['공포일자'] ?? '').localeCompare(String(a['공포일자'] ?? '')) ||
    Number(b['공포번호'] ?? 0) - Number(a['공포번호'] ?? 0));
  return ok[0] ?? null;
}

/**
 * 이름이 바뀐 법령(같은 법령ID)의 여러 이름 행에서 date8 에 시행 중이던 판.
 * date8 까지 시행된 판 중 가장 늦게 공포된 판의 이름을 그날의 이름으로 보고, 그 이름의 판 중에서 pickInForce 로 고른다.
 * 시행일만 보면 개칭 전에 공포돼 개칭 뒤에 시행된 옛 이름 판(지방자치분권법 MST 285293, 공포 2026-04-14, 시행 2026-10-15)이
 * 개칭 뒤 판보다 늦게 시행됐다는 이유로 현행으로 뽑힌다. 이름이 하나뿐이면 pickInForce 와 같다.
 */
export function pickInForceAcrossNames(rows, date8) {
  const ok = asArray(rows).filter((r) => String(r?.['시행일자'] ?? '') <= date8);
  if (!ok.length) return null;
  const latest = [...ok].sort((a, b) =>
    String(b['공포일자'] ?? '').localeCompare(String(a['공포일자'] ?? '')) ||
    String(b['시행일자']).localeCompare(String(a['시행일자'])) ||
    Number(b['공포번호'] ?? 0) - Number(a['공포번호'] ?? 0))[0];
  const name = normName(latest['법령명한글']);
  return pickInForce(ok.filter((r) => normName(r['법령명한글']) === name), date8);
}

/** Asia/Seoul 기준 오늘 YYYYMMDD */
export function todaySeoul(now = new Date()) {
  const k = new Date(now.getTime() + 9 * 3600 * 1000);
  return k.toISOString().slice(0, 10).replace(/-/g, '');
}

/**
 * 날짜를 YYYYMMDD 로 맞춘다. "20240701", "2024-07-01", "2024.7.1", "2024년 7월 1일" 을 받는다.
 * 숫자만 남기면 "2024.7.1" 이 "202471" 이 되어 문자열 비교가 엉뚱한 판을 고른다. 날짜가 아니면 실패한다.
 */
export function ymd(s) {
  const raw = String(s ?? '').trim();
  const m = raw.match(/^(\d{4})(\d{2})(\d{2})$/) || raw.match(/^\D*(\d{4})\D+(\d{1,2})\D+(\d{1,2})\D*$/);
  const mo = m ? Number(m[2]) : 0;
  const d = m ? Number(m[3]) : 0;
  if (!m || mo < 1 || mo > 12 || d < 1 || d > 31) {
    throw new Error(`날짜 형식이 아니다: "${raw}". YYYY-MM-DD 로 준다.`);
  }
  return `${m[1]}${String(mo).padStart(2, '0')}${String(d).padStart(2, '0')}`;
}

/** 법제처 응답 링크에 OC 가 평문으로 섞여 온다. 내보내기 전에 가린다 */
export function maskSecrets(text, oc) {
  let t = String(text ?? '');
  if (oc) t = t.split(oc).join('***');
  return t.replace(/OC=(?!\*\*\*)[^&"'\s]*/g, 'OC=***');
}
