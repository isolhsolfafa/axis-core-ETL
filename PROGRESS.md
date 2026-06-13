# CORE-ETL 프로젝트 진행 상황

## 개요
GST 제조 현장 생산 메타데이터 ETL 파이프라인 — Teams Excel(SCR 생산현황) → PostgreSQL 자동 적재.
AXIS-OPS DB에 직접 적재하며, GitHub Actions cron으로 주기적 자동 실행.

> **현재 버전**: v0.4.2 (운영 사건 ① 대응 — 6/11 timeout + Node 24 + SMTP, 2026-06-13)
> **저장소**: axis-core-etl (AXIS-OPS에서 분리)
> **DB 대상**: AXIS-OPS Railway PostgreSQL (plan.product_info, public.qr_registry)

---

## Repo 관계

```
axis-ops (Railway 배포)
  ├── Flask API + Flutter 모바일 앱
  └── DB 스키마 (plan.product_info, public.qr_registry)

axis-view (Netlify 배포)
  └── React 관리자 대시보드 → axis-ops API 호출

axis-core-etl (GitHub Actions cron)  ← 현재 repo
  └── ETL 파이프라인 → axis-ops DB 직접 적재 (DATABASE_URL)
```

---

## Sprint 0: 초기 구성 (2026-03-09) ✅

### 목표
AXIS-OPS에서 ETL 코드 분리 + Graph API 통합으로 GitHub Actions 자동화 기반 마련.

### 완료 내역
- **`etl_main.py`** — ETL 오케스트레이터
  - CLI: `--date`, `--start/--end`, `--all`, `--field`
  - dotenv 환경변수 로드
- **`step1_extract.py`** — Graph API 기반 Excel 추출
  - MSAL Client Credentials Flow 인증
  - 방법 A: OneDrive 파일 ID 직접 접근 (Primary)
  - 방법 B: OneDrive 폴더 탐색 fallback (404 시 자동 전환)
  - 폴더 패턴: `생산관리팀/1.정기업무/1.일정관리/2026년/W{NN}/SCR 일정관리_W{NN}.xlsx`
  - pandas 파싱 + COLUMN_MAPPING (17개) + EXTRA_COLUMNS (3개)
  - 마무리계획종료일 컬럼명 기반 fallback 탐색 (`find_extra_column`)
  - S/N split 로직 (sn_parser 대체)
- **`step2_load.py`** — PostgreSQL 적재
  - plan.product_info INSERT + public.qr_registry INSERT
  - 중복 체크 (serial_number 기준 skip)
  - DATABASE_URL 환경변수 기반
- **`.github/workflows/etl-metadata-sync.yml`** — GitHub Actions
  - workflow_dispatch (수동) + schedule (매주 월 09:00 KST)
  - Secrets: DATABASE_URL + Graph API 키 7개
- **`.env`** — 로컬 개발용 환경변수 (Graph API + DB)
- **`requirements.txt`** — msal, requests, psycopg2-binary, openpyxl, pandas, python-dotenv

### 생성 파일
```
etl_main.py                                     # 오케스트레이터
step1_extract.py                                # Graph API + Excel 파싱
step2_load.py                                   # PostgreSQL 적재
requirements.txt                                # 의존성
.gitignore                                      # output/, .env 등
.env                                            # 로컬 환경변수 (git 제외)
.github/workflows/etl-metadata-sync.yml         # GitHub Actions cron
```

---

## Sprint 1: UPSERT + 컬럼 매핑 교정 + 데이터 누락 해결 (2026-03-09) ✅

### 목표
INSERT → UPSERT 전환, finishing_plan_end 적재, 컬럼 매핑 버그 수정으로 SCR-Schedule과 동일한 적재 결과 달성.

### 완료 내역

**UPSERT 전환 + 에러 격리**
- step2_load.py: INSERT → `ON CONFLICT DO UPDATE` UPSERT
- `WHERE IS DISTINCT FROM` 조건으로 실제 변경된 경우만 UPDATE
- SAVEPOINT 패턴으로 레코드 단위 롤백 (에러 시 다른 레코드에 영향 없음)

**컬럼 매핑 버그 수정 (핵심)**
- `_find_column()` 정규화 매칭: 공백/줄바꿈 무시 + 정확매칭 우선
- COLUMN_ALIASES 추가: Excel 실제 헤더명 대체 검색어 (SCR-Schedule config.py 기준)
- 날짜/텍스트 필드 분리: `DATE_FIELDS` + `_format_text_value()` (float 소수점 제거)

**COLUMN_MAPPING SCR-Schedule 기준 교정 (39건 → 158건)**
- **원인**: "기구시작"(실적일, col 49) 매칭 → "기구계획시작일"(계획일, col 46)이 정확
- COLUMN_MAPPING 17개 전체를 SCR-Schedule config.py 기준 컬럼명으로 교체
- COLUMN_ALIASES는 기존 약자를 fallback으로 유지
- `semi_product_start` 컬럼명: "반제품시작" → "모듈계획시작일" 수정
- 결과: 3월 기준 ETL 40건 → **158건** (SCR-Schedule과 일치)

**추가 컬럼**
- `finishing_plan_end` (마무리계획종료일): 컬럼명 탐색 + index 72 fallback
- `sales_note` (특이사항영업): EXTRA_COLUMNS에 CJ열(index 87) 추가

**데이터 누락 분석**
- ETL vs SCR-Schedule 비교 진단 스크립트 (`compare_etl_vs_scr.py`)
- 원인 분류: 컬럼명 매칭 방식 차이 > pd.read_excel vs Graph API JSON > step2 에러 누적

### 미해결
- GBWS-6834: `module_start`에 "5083 모듈" 텍스트 → DATE 타입 에러 (현장 확인 필요, BACKLOG #6)
- 모델명 풀네임: Excel F열에 약자 저장 (풀네임 필요 시 매핑 테이블 별도 추가)

---

## Sprint 2: 변경 이력 추적 + VIEW 연동 (2026-03-10~11) ✅ 완료

### 목표
UPSERT 시 핵심 5개 필드 변경 이력을 DB에 기록 + actual_ship_date 적재 + shipped 상태 처리 + OPS BE 엔드포인트 + VIEW API 연동.

### 완료 내역

**Task 1: DB 스키마 ✅**
- `etl` 스키마 생성 + `etl.change_log` 테이블 + 인덱스 3개
- `plan.product_info.actual_ship_date` DATE 컬럼 추가

**Task 2: 변경 이력 기록 로직 ✅**
- `TRACKED_FIELDS`: 5개 필드 (sales_order, ship_plan_date, mech_start, mech_partner, elec_partner)
- `_record_changes()`: UPSERT 직전 SELECT → 비교 → etl.change_log INSERT
- `_normalize_value()`: NULL/빈문자열 정규화
- SAVEPOINT 범위 내 실행 → 에러 시 같이 롤백

**Task 3: actual_ship_date + shipped 처리 ✅**
- step1: EXTRA_COLUMNS에 `actual_ship_date` 추가 (R열, "출고")
- step2: UPSERT에 actual_ship_date 추가 (INSERT/UPDATE/WHERE — 18개 필드)
- shipped: `actual_ship_date <= today - 1일` → `qr_registry.status = 'shipped'`

**Task 4: OPS BE 엔드포인트 ✅** (2026-03-11)
- `GET /api/admin/etl/changes` — `@manager_or_admin_required`
- 파라미터: days, field, serial_number, limit
- 응답: changes[] + summary (total_changes, by_field)
- `etl.change_log` JOIN `plan.product_info` (model 포함)

**Task 5: VIEW API 연동 ✅** (2026-03-11)
- `api/etl.ts` — `getEtlChanges()` API 함수
- `hooks/useEtlChanges.ts` — TanStack Query 훅 (staleTime: 60초)
- `EtlChangeLogPage.tsx` — Mock 제거 → API 연동
- 기간 필터 (7/14/30일) + 필드/S/N 필터 + 로딩/에러 상태

**Task 6: Sidebar 서브메뉴 ✅** (Sprint 2 이전 완료)

---

## Sprint 2-A: pi_start 변경이력 추적 추가 (2026-03-14) ✅ 완료

### 목표
ETL 변경 추적 대상에 pi_start(가압시작) 필드 추가. VIEW 변경이력 페이지에서 가압시작 일정 변경도 확인 가능하게.

### 변경 내역

**step2_load.py**
- `TRACKED_FIELDS`: `'pressure_test': 'pi_start'` 추가 (5→6개)
- `_prefetch_tracked_values()`: SELECT에 `pi_start` 추가, 캐시 dict에 매핑
- `_record_changes()` 주석: 5개 → 6개 필드

**AXIS-OPS BE** (admin.py)
- `_FIELD_LABELS`에 `'pi_start': '가압시작'` 추가

**AXIS-VIEW FE** (별도 진행)
- `FIELD_CONFIG`, `DATE_FIELDS`, KPI 그리드 6열, kpiCards, 주간 차트 — DESIGN_FIX_SPRINT.md 참고

---

## Sprint 31A 연동: DUAL 모델 Tank QR 자동 생성 (2026-03-18) ✅ 완료

### 목표
AXIS-OPS Sprint 31A 다모델 지원에 따른 ETL step2_load.py 수정. DUAL 모델 제품 신규 등록 시 L/R Tank QR 자동 생성.

### 변경 내역

**step2_load.py**
- 신규 제품 INSERT 시 `qr_type='PRODUCT'` 명시
- DUAL 모델 판단: model_name에 'DUAL' 포함 OR `model_config.always_dual=True` (iVAS)
- DUAL + `tank_in_mech=False` → L/R Tank QR 2건 생성 (`qr_type='TANK'`, `parent_qr_doc_id` 설정)
- DRAGON(`tank_in_mech=True`) → Tank QR 미생성 (MECH에서 일괄 처리)
- `ON CONFLICT (qr_doc_id) DO NOTHING` — 멱등성 보장

---

## Sprint 3: module_end 추가 + VIEW 실적뷰 기준 변경 (2026-03-23) ✅ 완료

### 목표
생산실적 VIEW 페이지의 표시 기준을 `mech_start`(착수일) → 공정 종료일(`mech_end`/`elec_end`/`module_end`) 기준으로 변경. W12에 시작한 O/N이 W13에 끝나면 W13에 표시되어야 실적확인 시점과 일치.

### 배경
- 기존: `mech_start` 기준 → W12에 착수한 O/N을 W12에 표시 (실적확인 시점과 불일치)
- MECH/ELEC end는 보통 비슷하지만 module_end는 7~10일 차이 발생
- PI/QI/SI는 하루 공정으로 end date 불필요 (start ≈ end, 실제 완료는 `app_task_details.completed_at`로 판단)

### DB 변경 (수동 실행 필요)
```sql
ALTER TABLE plan.product_info ADD COLUMN IF NOT EXISTS module_end DATE;
CREATE INDEX IF NOT EXISTS idx_plan_pi_module_end ON plan.product_info(module_end);
CREATE INDEX IF NOT EXISTS idx_plan_pi_mech_end ON plan.product_info(mech_end);
CREATE INDEX IF NOT EXISTS idx_plan_pi_elec_end ON plan.product_info(elec_end);
```

### ETL 변경
**step1_extract.py**
- `EXTRA_COLUMNS`에 `semi_product_end` 추가 (Excel AQ열 "모듈계획종료일", fallback index 42)
- `EXTRA_DATE_FIELDS`에 `semi_product_end` 추가 (날짜 포맷 적용)

**step2_load.py**
- 매핑 추가: `semi_product_end → module_end`
- INSERT 컬럼 리스트에 `module_end` 추가
- UPSERT `DO UPDATE SET`에 `module_end = EXCLUDED.module_end` 추가
- UPSERT `WHERE` 변경 감지 조건에 `module_end IS DISTINCT FROM` 추가

### AXIS-OPS BE 변경
**production.py** `get_performance()` 쿼리:
- 변경 전: `WHERE p.mech_start >= %s AND p.mech_start < %s`
- 변경 후: `WHERE (mech_end 범위) OR (elec_end 범위) OR (COALESCE(module_end, module_start) 범위)`
- `module_end` NULL 과도기 대응: `COALESCE(module_end, module_start)` fallback

---

## Sprint 3-A: finishing_plan_end 변경이력 추적 추가 (2026-03-24) ✅ 완료

### 목표
ETL 변경 추적 대상에 finishing_plan_end(마무리계획종료일) 필드 추가. VIEW 변경이력 페이지에서 마무리계획종료일 변경도 확인 가능하게.

### 변경 내역

**step2_load.py**
- `TRACKED_FIELDS`: `'finishing_plan_end': 'finishing_plan_end'` 추가 (6→7개)
- `_prefetch_tracked_values()`: SELECT에 `finishing_plan_end` 추가, 캐시 dict에 매핑

---

## 운영 사건 ①: 6/11 cron 취소 + Node 24 + SMTP 알림 대응 (2026-06-11 ~ 2026-06-13) ✅ 완료

### 배경
- 2026-06-11 schedule run 1건이 `The operation was canceled` 으로 종료
- 동시에 GitHub Actions 런타임이 `actions/upload-artifact@v5` Node 20 deprecation 경고 표시 (2026-06-16부터 강제 Node 24)
- ETL 실패가 "침묵"되는 구조 (알림 부재) — 수동 확인으로만 발견

### 진단 (트래킹 로그로 확정 — 6/12)
- 30분 timeout 초과로 cancel 확정 (Annotation: `exceeded the maximum execution time of 30m0s`)
- 6/12 16:00 KST 재실패 run #27411398223 로그 분석:
  ```
  10:57:55  배치 1/4 시작
  11:09:07  배치 1/4 commit (11분 12초 소요)
  11:09:07  배치 2/4 시작
  11:20:00  배치 2/4 commit (10분 53초 소요)
  11:20:00  배치 3/4 시작 → 30분 초과로 cancel
  ```
- **결론**: hang/락 충돌 아님. 배치당 약 11분 × 4배치 = 약 44분 필요한데 timeout 30분이라 잘림
- **원인**: Railway DB 네트워크 왕복 지연 + 레코드당 SAVEPOINT/UPSERT/SELECT 5회 round-trip × 1542건 ≈ 7700 round-trip
- 6/11 사건도 동일 원인 추정 (락 가설 기각)

### 변경 내역

**step2_load.py** (`2be5b81`)
- `_ts()` 헬퍼 추가 (timestamped 로그, `flush=True`로 Actions 버퍼링 회피)
- `load_to_postgres` 진입/연결/prefetch/배치별 진행에 `_ts()` 호출 6개
- `psycopg2.connect()`에 `options="-c lock_timeout=60s -c statement_timeout=300s"` 추가
  → 락 대기 60초 / 단일 쿼리 5분 초과 시 즉시 실패

**step1_extract.py** (`2be5b81`)
- `_ts()` 헬퍼 + `HTTP_TIMEOUT = (30, 60)` 상수 추가
- `get_graph_token()`, `_download_by_doc_id()`, `_download_by_folder_search()`, `extract_from_teams_excel()` 진입/종료에 `_ts()` 호출
- 모든 `requests.get()` 호출에 `timeout=HTTP_TIMEOUT` 명시 (이전엔 무한 대기)

**.github/workflows/etl-metadata-sync.yml** (`2be5b81`, `db9839e`, `7eba85a`, `e188cbf`, `495172f`)
- `concurrency: { group: etl-sync, cancel-in-progress: false }` 추가 → schedule run 겹침 방지
- `actions/upload-artifact@v5` → **`@v7`** (Node 24 호환)
- `dawidd6/action-send-mail@v4` → **`@v17`** (Node 24 호환)
- `timeout-minutes: 30 → 60` (배치 적재 시간 확보)
- SMTP 메일 알림 step 추가 (`dkkim1@gst-in.com`, port 465 SSL, `secure: true`)
  - 트리거: `if: failure() || cancelled()` (실패/취소 시만 발송, 성공은 대시보드 확인)
  - 본문: `output/etl_result.json` 부분 적재 통계 + Run URL + hang 위치 가이드

### 검증 결과
- ✅ 6/13 SMTP 검증 메일 정상 수신 (`dkkim1@gst-in.com`)
- ✅ Node 20 deprecation 경고 사라짐 확인 (`@v7`, `@v17` 적용 후)
- ✅ timestamped 로그로 hang 위치 즉시 식별 가능 (배치 처리 시점)
- ⏳ 다음 schedule run (2026-06-13 토 07:00 KST 이후) 정상 완료 — timeout 60분으로 처리 가능

### GitHub Secrets 추가 등록 (5종)
| Secret | 값 | 출처 |
|---|---|---|
| `SMTP_HOST` | (Railway 동일값) | Railway variables |
| `SMTP_PORT` | `465` (SSL) | Railway variables |
| `SMTP_USER` | (Railway 동일값) | Railway variables |
| `SMTP_PASSWORD` | (Railway 동일값) | Railway variables |
| `SMTP_FROM_NAME` | `G-AXIS` | Railway variables |

### CLAUDE.md 동기화
- 모델 설정 섹션 신규 추가 (Opus 4.8 기본 / Fable 5 한시 승격) — AXIS-OPS와 동기화 (`dcb196e`)

### 후속 BACKLOG
- 🟠 AXIS-OPS pytest.yml Node 24 호환화 (시한 2026-06-16) — 별도 sprint
- 🟡 ETL 배치 적재 속도 최적화 — `_prefetch_tracked_values` 확장 + `psycopg2.extras.execute_batch` 도입
- 🟡 serial_number 변경 추적 — 보조 식별자(O/N) 기반 매칭 로직 (이전 대화 기록)

### 문서
- `ETL_INCIDENT_20260611_AND_NODE24_PLAN.md` — 사건 기록 + 조치 + 완료 보고 (전 과정 trail)
- `BACKLOG.md` — 후속 항목 등록
- `CLAUDE.md` — 모델 설정 섹션 추가
