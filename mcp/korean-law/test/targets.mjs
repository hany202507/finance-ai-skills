/**
 * 단위 시험이 쓰는 법제처 응답 목록. capture.mjs 가 이 목록대로 다시 받고, 시험의 가짜 callApi 가 이 목록으로 응답을 찾는다.
 * 데이터만 둔다. node --test 가 test/ 아래 파일을 모두 실행하므로 여기에 부작용이 있으면 안 된다.
 */
const 경제옛 = '경제자유구역의 지정 및 운영에 관한 법률';
const 경제새 = '경제자유구역의 지정 및 운영에 관한 특별법';
const 지방옛 = '지방자치분권 및 지역균형발전에 관한 특별법';
const 지방새 = '지방자치분권 및 균형성장에 관한 특별법';
const search = (query, nw, page = 1) => ({ target: 'eflaw', query, nw, display: 100, page });

export const TARGETS = [
  // 조문 본문(목내용 배열). 받은 판(MST@시행일)은 2026-10-09 현행이다
  { file: '소득세법_104.json', path: 'lawService.do', params: { target: 'eflaw', MST: '280405', efYd: '20260701', JO: '010400' } },
  { file: '소득세법시행령_167의3.json', path: 'lawService.do', params: { target: 'eflaw', MST: '290841', efYd: '20261001', JO: '016703' } },
  // 옛 이름 조회(2026-10-09 받음). 경제자유구역법은 2009-07-31 개칭, 지방자치분권법은 2026-06-02 개칭
  { file: '검색_경제옛_123_1.json', path: 'lawSearch.do', params: search(경제옛, '1,2,3') },
  { file: '검색_경제옛_23_1.json', path: 'lawSearch.do', params: search(경제옛, '2,3') },
  { file: '검색_경제새_123_1.json', path: 'lawSearch.do', params: search(경제새, '1,2,3', 1) },
  { file: '검색_경제새_123_2.json', path: 'lawSearch.do', params: search(경제새, '1,2,3', 2) },
  { file: '검색_경제새_23_1.json', path: 'lawSearch.do', params: search(경제새, '2,3') },
  { file: '검색_지방옛_23_1.json', path: 'lawSearch.do', params: search(지방옛, '2,3') },
  { file: '검색_지방새_23_1.json', path: 'lawSearch.do', params: search(지방새, '2,3') },
  // 법령ID 로 현행 이름 얻기(제1조만 받아 응답을 줄인다)
  { file: '법령ID_009411.json', path: 'lawService.do', params: { target: 'eflaw', ID: '009411', JO: '000100' } },
  { file: '법령ID_014455.json', path: 'lawService.do', params: { target: 'eflaw', ID: '014455', JO: '000100' } },
];

export const NAMES = { 경제옛, 경제새, 지방옛, 지방새 };
