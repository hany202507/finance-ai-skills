-- 원천세 엔진 DB 스파인 (SQLite)
-- 원칙: 효력일자(eff_from~eff_to, NULL=무기한) 이력화, 결과 재계산 가능, filing 스냅샷만 불변.

-- 회사
CREATE TABLE IF NOT EXISTS company (
    id          INTEGER PRIMARY KEY,
    biz_no      TEXT,                 -- 사업자등록번호
    name        TEXT NOT NULL,
    wh_office   TEXT,                 -- 원천징수 관할 세무서
    semiannual  INTEGER DEFAULT 0,    -- 반기납부 특례 여부(0/1)
    local_tax_code TEXT               -- 지방소득세 특별징수 지자체
);

-- 지급대상(인사마스터). 근로자·사업자·기타·비거주자 통합.
-- company_id: 멀티테넌트— 회사별 분리. NULL 허용(단일사 운영 호환).
CREATE TABLE IF NOT EXISTS payee (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER REFERENCES company(id),
    name          TEXT NOT NULL,
    rrn_masked    TEXT,               -- 주민등록번호(마스킹 저장)
    resident_type TEXT NOT NULL,      -- '거주자' | '비거주자'
    country_code  TEXT,               -- 비거주자 거주지국(ISO)
    payee_type    TEXT NOT NULL,      -- '근로자' | '사업자' | '기타' | '비거주자'
    join_date     TEXT,               -- 입사일
    leave_date    TEXT                -- 퇴사일
);

-- 급여계약(효력일자) — 급여인상 이력화
CREATE TABLE IF NOT EXISTS payee_contract (
    id                INTEGER PRIMARY KEY,
    payee_id          INTEGER NOT NULL REFERENCES payee(id),
    monthly_pay       INTEGER,        -- 월정액(과세+비과세 총)
    pay_composition   TEXT,           -- 급여구성 JSON(항목→금액/비과세)
    production_worker INTEGER DEFAULT 0,  -- 생산직 비과세 대상
    overseas_relief   INTEGER DEFAULT 0,  -- 국외근로 비과세
    eff_from          TEXT NOT NULL,
    eff_to            TEXT
);

-- 부양가족(효력일자)
CREATE TABLE IF NOT EXISTS dependent (
    id             INTEGER PRIMARY KEY,
    payee_id       INTEGER NOT NULL REFERENCES payee(id),
    relation       TEXT,              -- 관계(배우자/직계존속/직계비속…)
    birth          TEXT,              -- 생년월일
    disabled       INTEGER DEFAULT 0,
    senior         INTEGER DEFAULT 0, -- 경로(70세↑)
    woman          INTEGER DEFAULT 0, -- 부녀자
    single_parent  INTEGER DEFAULT 0, -- 한부모
    basic_deduction INTEGER DEFAULT 1,-- 기본공제 대상 여부
    eff_from       TEXT NOT NULL,
    eff_to         TEXT
);

-- 4대보험 자격(효력일자)
CREATE TABLE IF NOT EXISTS insurance_enrollment (
    id          INTEGER PRIMARY KEY,
    payee_id    INTEGER NOT NULL REFERENCES payee(id),
    ins_type    TEXT NOT NULL,        -- '국민연금'|'건강보험'|'고용보험'
    acquire_date TEXT,
    loss_date   TEXT,
    base_wage   INTEGER,              -- 기준소득월액/보수월액
    relief      REAL DEFAULT 0,       -- 감면율
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- 지급건(트랜잭션)
CREATE TABLE IF NOT EXISTS payment (
    id          INTEGER PRIMARY KEY,
    payee_id    INTEGER NOT NULL REFERENCES payee(id),
    company_id  INTEGER REFERENCES company(id),
    income_type TEXT NOT NULL,        -- 소득유형 코드(ref_income_type)
    accrual_ym  TEXT NOT NULL,        -- 귀속연월 YYYY-MM
    pay_date    TEXT,                 -- 지급일
    gross       INTEGER NOT NULL,     -- 지급총액
    nontax      INTEGER DEFAULT 0,    -- 비과세액
    expense     INTEGER DEFAULT 0,    -- 필요경비
    tax_base    INTEGER               -- 과세표준(파생)
);

-- 급여 항목별 라인(급여대장 원천)
CREATE TABLE IF NOT EXISTS payment_line (
    id          INTEGER PRIMARY KEY,
    payment_id  INTEGER NOT NULL REFERENCES payment(id),
    item        TEXT NOT NULL,        -- 기본급/직책수당/식대…
    amount      INTEGER NOT NULL,
    nontax      INTEGER DEFAULT 0     -- 비과세 여부/금액
);

-- 원천징수 결과(재계산 가능, 불변 아님)
CREATE TABLE IF NOT EXISTS withholding_result (
    id          INTEGER PRIMARY KEY,
    payment_id  INTEGER NOT NULL REFERENCES payment(id),
    income_tax  INTEGER DEFAULT 0,    -- 소득세
    local_tax   INTEGER DEFAULT 0,    -- 지방소득세
    nps         INTEGER DEFAULT 0,    -- 국민연금
    health      INTEGER DEFAULT 0,    -- 건강보험
    ltc         INTEGER DEFAULT 0,    -- 장기요양
    ei          INTEGER DEFAULT 0,    -- 고용보험
    applied_rule TEXT,                -- 적용룰 ID
    basis       TEXT,                 -- 근거 조문
    confirmed   INTEGER DEFAULT 0
);

-- 신고이력(스냅샷 불변)
CREATE TABLE IF NOT EXISTS filing (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER REFERENCES company(id),
    accrual_ym  TEXT NOT NULL,
    filing_type TEXT DEFAULT '정기',  -- '정기'|'반기'
    snapshot    TEXT,                 -- 이행상황신고서 집계 JSON
    filed_date  TEXT
);

-- ===== 참조 데이터(효력일자) =====

-- 소득유형 마스터
CREATE TABLE IF NOT EXISTS ref_income_type (
    code        TEXT NOT NULL,        -- '근로'|'일용'|'사업'|'기타'|'사용료'|'상여'
    name        TEXT,
    return_line TEXT,                 -- 이행상황신고서 귀속칸
    base_rate   REAL,                 -- 기본세율
    expense_rate REAL,                -- 필요경비율(기타)
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- 4대보험 요율·상하한
CREATE TABLE IF NOT EXISTS ref_insurance_rate (
    ins_type    TEXT NOT NULL,        -- '국민연금'|'건강보험'|'장기요양'|'고용보험'
    rate        REAL NOT NULL,        -- 근로자 부담 요율
    base_min    INTEGER,              -- 기준소득월액 하한
    base_max    INTEGER,              -- 기준소득월액 상한
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- 조세조약 제한세율
CREATE TABLE IF NOT EXISTS ref_treaty_rate (
    country     TEXT NOT NULL,        -- 거주지국(ISO)
    income_type TEXT NOT NULL,        -- '사용료'|'이자'|'배당'|'기타'
    rate        REAL NOT NULL,        -- 제한세율
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- ===== 노무·부담 레이어 =====

-- 일별 사용 근로자 수·가동일 — 상시근로자수 정밀 산정(근기법 시행령 §7의2)
CREATE TABLE IF NOT EXISTS workday_headcount (
    company_id  INTEGER NOT NULL,
    date        TEXT NOT NULL,        -- YYYY-MM-DD
    headcount   INTEGER NOT NULL,     -- 그 날 사용한 근로자 수
    is_workday  INTEGER DEFAULT 1     -- 가동일 여부
);

-- 인원 임계점 → 켜지는 의무(효력일자)
CREATE TABLE IF NOT EXISTS ref_labor_threshold (
    threshold   INTEGER NOT NULL,     -- 상시근로자수 임계
    name        TEXT NOT NULL,        -- 의무 명칭
    basis       TEXT,                 -- 근거 조문
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- 부담금 요율·기초액(효력일자)
CREATE TABLE IF NOT EXISTS ref_burden_rate (
    kind          TEXT NOT NULL,      -- '장애인고용부담금' 등
    rate          REAL,               -- 의무고용률
    unit_amount   INTEGER,            -- 부담기초액(월/인)
    min_headcount INTEGER,            -- 부과 최소 인원
    eff_from      TEXT NOT NULL,
    eff_to        TEXT
);

-- 근로소득 간이세액표 (소득령 별표2) — 원문 적재형, 효력일자
-- ※ 표 세액은 2024.3.1판과 2026.3.1판이 동일. 개정된 건 자녀공제(ref_child_credit).
CREATE TABLE IF NOT EXISTS ref_simple_tax_table (
    pay_min     INTEGER NOT NULL,     -- 월급여 구간 하한(이상, 원)
    pay_max     INTEGER NOT NULL,     -- 월급여 구간 상한(미만, 원)
    dependents  INTEGER NOT NULL,     -- 공제대상가족수(본인·배우자 각 1명 포함)
    tax         INTEGER NOT NULL,     -- 월 소득세(100% 기준)
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- 별표2 §3 자녀세액공제(8세 이상 20세 이하) — 개정으로 갈리는 값
CREATE TABLE IF NOT EXISTS ref_child_credit (
    one         INTEGER NOT NULL,     -- 1명
    two         INTEGER NOT NULL,     -- 2명
    extra       INTEGER NOT NULL,     -- 2명 초과 1명당
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- 별표2 §6 고액 산식 기준: 월급여 10,000천원인 경우의 해당 세액(가족수별)
CREATE TABLE IF NOT EXISTS ref_gani_base10000 (
    dependents  INTEGER NOT NULL,
    tax         INTEGER NOT NULL,
    eff_from    TEXT NOT NULL,
    eff_to      TEXT
);

-- ===== 연말정산 (C) =====

-- 근로자별 공제자료(귀속연도) — 홈택스 간소화·수기 취합분
CREATE TABLE IF NOT EXISTS yearend_deduction (
    id          INTEGER PRIMARY KEY,
    payee_id    INTEGER NOT NULL REFERENCES payee(id),
    귀속연도    INTEGER NOT NULL,
    항목        TEXT NOT NULL,        -- '부양가족'|'신용카드'|'의료비'|'교육비'|'기부금'|'연금계좌'…
    금액        INTEGER DEFAULT 0,
    부속        TEXT                  -- 항목별 JSON(부양가족 리스트·결제수단별 금액 등)
);

-- 연말정산 파라미터(귀속연도별 공제율·한도·문턱)
CREATE TABLE IF NOT EXISTS ref_yearend_param (
    귀속연도    INTEGER NOT NULL,
    key         TEXT NOT NULL,        -- 'basic_deduction'|'card_threshold_rate'|'std_credit'…
    value       INTEGER NOT NULL,
    근거        TEXT,
    eff_from    TEXT,
    eff_to      TEXT
);

-- 종합소득 기본세율표(귀속연도별) — 소득세법 §55
CREATE TABLE IF NOT EXISTS ref_tax_bracket (
    귀속연도    INTEGER NOT NULL,
    하한        INTEGER NOT NULL,     -- 과세표준 하한(이상)
    세율        REAL NOT NULL,        -- 한계세율
    누진공제    INTEGER NOT NULL
);

-- 매년 개정 확인할 원문 출처 레지스트리 (연말정산 롤오버 + 원천세 전체 규정워치)
CREATE TABLE IF NOT EXISTS ref_amendment_source (
    source      TEXT NOT NULL,        -- '기재부 세법개정안' 등
    시점        TEXT NOT NULL,        -- 확인 타이밍(사람용, 예: '매년 7~8월')
    months      TEXT,                 -- 기계 매칭용 확인월 (예: '7,8') — monthly_checkup 규정워치
    url         TEXT,
    용도        TEXT
);

-- ===== SaaS 운영 레이어 (외주 다사 운영) =====

-- 신고 사이클 상태머신: 자료수집→계산→검토→신고→납부→완료
CREATE TABLE IF NOT EXISTS filing_status (
    company_id  INTEGER,
    귀속연월    TEXT NOT NULL,
    단계        TEXT NOT NULL,
    updated_at  TEXT,
    memo        TEXT
);

-- InfoRequest 미결 추적 — 질문을 보냈는지·답을 받았는지
CREATE TABLE IF NOT EXISTS info_request_log (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER,
    귀속연월    TEXT,
    payment_id  INTEGER,
    질문        TEXT NOT NULL,
    사유        TEXT,
    상태        TEXT DEFAULT 'open',  -- 'open' | 'answered'
    답변        TEXT,
    created_at  TEXT,
    answered_at TEXT
);

-- 참조데이터 출처·대사 이력 — 신고 전 리뷰의 근거.
-- 원칙: 모든 세율·금액 데이터는 '누가·언제·무엇으로' 대사했는지 기록한다.
--       verify_status='원문대사'가 아니면 신고 전 에이전트가 법령 원문으로 확인해야 한다.
CREATE TABLE IF NOT EXISTS ref_provenance (
    id            INTEGER PRIMARY KEY,
    dataset       TEXT NOT NULL,      -- '국민연금요율'|'간이세액표'|'장애인부담기초액'|'조세조약_US' …
    basis         TEXT NOT NULL,      -- 근거: 법령명·조문·고시번호 (부칙 포함 명시)
    verify_status TEXT NOT NULL,      -- '원문대사' | '2차출처' | '추정' | '미적재'
    verified_on   TEXT,               -- 대사일 YYYY-MM-DD
    verify_method TEXT,               -- 'korean-law:get_law_text' 등 재현 경로
    eff_from      TEXT NOT NULL,      -- 이 데이터가 적용되는 기간
    eff_to        TEXT,
    note          TEXT,               -- 함정·주의(예: 본문 아닌 부칙 경과조치 적용)
    cross_check   TEXT                -- 웹 리서치·최신 개정 교차확인(연말정산 등 매년 개정 항목 필수)
);
