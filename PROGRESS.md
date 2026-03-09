# CORE-ETL 프로젝트 진행 상황

## 개요
GST 제조 현장 생산 메타데이터 ETL 파이프라인 — Teams Excel(SCR 생산현황) → PostgreSQL 자동 적재.
AXIS-OPS DB에 직접 적재하며, GitHub Actions cron으로 주기적 자동 실행.

> **현재 버전**: v0.1.0 (Sprint 1, 2026-03-09)
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
