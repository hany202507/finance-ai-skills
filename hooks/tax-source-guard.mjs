#!/usr/bin/env node
/**
 * tax-source-guard — UserPromptSubmit 훅 (크로스플랫폼 / Node)
 *
 * 세법자문-회신 스킬과 같이 쓴다. korean-law 서버 때문에 Node 는 어차피 필요하므로 의존성이 늘지 않는다.
 *
 * 왜 있는가: 세법 쟁점인데 근거 출처(TaxDoctor · korean-law)를 안 쓰고 웹·기억으로 답하는 일이 있었다.
 * 스킬 문구는 모델이 읽고 넘길 수 있지만, 훅은 모델의 판단과 무관하게 매번 주입된다.
 * 그래서 "세법 냄새가 나는 프롬프트"에만 한 줄을 끼워 넣는다.
 *
 * 노이즈를 줄이려고 키워드를 좁게 잡았다. 넓히면 결산·발행 같은 다른 작업에서도 떠서
 * 훅 자체가 무시당한다 — 그게 이 장치가 죽는 방식이다.
 */

// 세법 '해석' 쟁점 신호. 단순 기장·발행 작업어(전표·발행·마감)는 일부러 뺐다.
const PATTERN = new RegExp(
  '가산세|부가가치세|부가세|법인세|소득세|원천세|원천징수|조세특례|조특법|국세기본법|' +
  '세법|세무 ?(검토|자문|질의|회신)|예규|심판례|경정청구|제척기간|매입세액|영세율|' +
  '과세표준|비과세|면세사업|세액감면|신고불성실|납부지연'
);

const MSG = `[세법 근거 규약 — 자동 주입]
세법 쟁점으로 보인다. 해석·검토가 필요하면 \`세법자문-회신\` 스킬을 쓰고, 아래를 지켜라.

1. 근거로 적는 출처는 TaxDoctor 와 \`korean-law\` 두 곳이다. 웹·기억만으로 조문번호를 단정하지 마라.
   - 세법 조문·예규·판례 조사: TaxDoctor (\`search_tax\`, \`get_article\`)
   - 세법이 아닌 법령, 부칙의 적용 시점(\`get_addenda\`), 지난 과세기간 조문, 내용으로 조문 찾기(\`scan_articles\`): \`korean-law\`
2. 근거마다 등급을 붙인다. ★★★ 원문 확인(세법 조문은 두 곳에서 같은 판, TaxDoctor 에 없는 법령과 부칙은 korean-law 원문과 링크) / ★★☆ 한 곳에서만 읽었거나 요지만 / ☆ 두 곳에서 다 못 엶.
   결론에 쓴 조문이 ★★★ 이 아니면 그 사실을 결론 옆에 적는다.
3. 답변에는 결론에 쓴 조문만 적는다. 확정하지 못한 것은 결론이나 금액을 바꾸는 것만 적는다.
4. 한 곳이 응답하지 않으면 남은 곳으로 쓰고 조문 등급은 ★★☆ 까지다. 둘 다 응답하지 않으면 웹으로 잠정 검토하되, 답변 첫 줄에 "법령 원문 미검증"을 적는다.
5. 링크는 도구가 준 것만 옮긴다. 조립하지 마라.

단순 질문이면 이 규약을 무시해도 된다. 다만 조문번호·세율·가산세율을 말하는 순간 1번은 필수다.
사용자가 TaxDoctor 만 쓰라고 했으면 그 지시를 따르고 조문 등급은 ★★☆ 로 적는다.`;

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  // BOM 이 붙어 오면 JSON.parse 가 죽는다(PowerShell 의 Out-File -Encoding utf8 등).
  return Buffer.concat(chunks).toString('utf8').replace(/^﻿/, '');
}

/**
 * `--selftest` — 훅이 살아 있는지 확인하는 통로.
 *
 * 왜 필요한가: 검증을 `echo '{"prompt":"가산세"}' | node hook.mjs` 로 하면
 * Windows PowerShell 5.1 이 파이프의 한글을 ANSI 로 뭉개서 키워드가 안 걸린다.
 * 훅은 멀쩡한데 "출력이 없다 → 죽었다"는 **거짓 음성**이 나온다.
 * 그래서 명령줄을 순수 ASCII 로 두고, 한글은 이 파일 안에서 만든다.
 */
if (process.argv.includes('--selftest')) {
  const hit = PATTERN.test('가산세 붙나요');
  const miss = !PATTERN.test('README 고쳐줘');
  const ok = hit && miss;
  process.stdout.write(
    ok
      ? 'PASS — 훅이 정상이다. 세법 프롬프트에 규약이 주입되고, 그 외에는 조용히 빠진다.\n'
      : `FAIL — 패턴 매칭이 깨졌다 (세법어=${hit}, 비세법어제외=${miss}).\n`,
  );
  process.exit(ok ? 0 : 1);
}

try {
  const raw = await readStdin();
  if (!raw.trim()) process.exit(0);

  const prompt = JSON.parse(raw)?.prompt;
  if (!prompt || !PATTERN.test(prompt)) process.exit(0);

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext: MSG,
    },
  }));
} catch {
  // 훅이 깨져도 대화를 막지 않는다. 조용히 빠진다.
}
process.exit(0);
