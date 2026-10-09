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

/**
 * 인용용 법제처 원문 링크.
 * 도구가 링크를 주지 않으면 모델이 링크를 지어낸다. 그래서 모든 조회 응답 끝에 붙인다.
 * 한글 경로는 그대로 두고 공백만 인코딩한다("상속세 및 증여세법" 은 raw 로는 400).
 * 퍼센트 인코딩된 URL 은 사람이 못 읽어서 회신에 붙었을 때 검증이 안 된다.
 */
export function lawUrl(lawName, article) {
  const base = `https://www.law.go.kr/법령/${String(lawName ?? '').trim().replace(/ /g, '%20')}`;
  return article ? `${base}/제${String(article).replace(/-/g, '의')}조` : base;
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

/** Asia/Seoul 기준 오늘 YYYYMMDD */
export function todaySeoul(now = new Date()) {
  const k = new Date(now.getTime() + 9 * 3600 * 1000);
  return k.toISOString().slice(0, 10).replace(/-/g, '');
}

export const ymd = (s) => String(s ?? '').replace(/\D/g, '').slice(0, 8);

/** 법제처 응답 링크에 OC 가 평문으로 섞여 온다. 내보내기 전에 가린다 */
export function maskSecrets(text, oc) {
  let t = String(text ?? '');
  if (oc) t = t.split(oc).join('***');
  return t.replace(/OC=(?!\*\*\*)[^&"'\s]*/g, 'OC=***');
}
