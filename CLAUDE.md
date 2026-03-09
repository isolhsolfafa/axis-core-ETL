# CORE-ETL 프로젝트 컨텍스트

## 프로젝트 개요
GST 제조 현장 생산 메타데이터 ETL 파이프라인.
Teams Excel(SCR 생산현황) → PostgreSQL 자동 적재.
GitHub Actions cron으로 매주 월요일 자동 실행.

## 기술 스택
- Python 3.10+
- Microsoft Graph API (MSAL Client Credentials Flow)
- pandas + openpyxl (Excel 파싱)
- psycopg2 (PostgreSQL)
- GitHub Actions (cron + workflow_dispatch)

## 파일 구조
```
CORE-ETL/
├── etl_main.py              # 오케스트레이터 (CLI: --date, --start/--end, --all)
├── step1_extract.py         # Graph API Excel 다운로드 + 파싱
├── step2_load.py            # PostgreSQL 적재 (plan.product_info + public.qr_registry)
├── requirements.txt         # 의존성
├── .env                     # 로컬 환경변수 (git 제외)
├── .gitignore
├── CLAUDE.md                # 이 파일
├── PROGRESS.md              # 스프린트 이력
├── BACKLOG.md               # 백로그 + GitHub Secrets 목록
├── docs/
│   ├── SPRINT_1.md          # 현재 스프린트
│   └── SPRINT_COMPLETION_TEMPLATE.md
└── .github/workflows/
    └── etl-metadata-sync.yml  # GitHub Actions
```

## DB 대상 (AXIS-OPS Railway PostgreSQL)
```
plan.product_info
  - serial_number (PK), model, sales_order, customer
  - mech_partner, elec_partner, module_outsourcing
  - mech_start, mech_end, elec_start, elec_end
  - module_start, pi_start, qi_start, si_start
  - ship_plan_date, prod_date
  - finishing_plan_end (마무리계획종료일 — 협력사 평가 + 실적관리 기준)
  - updated_at (UPSERT 변경 추적)

public.qr_registry
  - qr_doc_id (DOC_{serial_number}), serial_number, status ('active')
```

## 환경변수 (필수)
```
DATABASE_URL          — Railway PostgreSQL URL
TEAMS_TENANT_ID       — Azure AD Tenant ID
TEAMS_CLIENT_ID       — Azure AD App Client ID
TEAMS_CLIENT_SECRET   — Azure AD App Client Secret
SOURCE_DOC_ID         — OneDrive Excel 파일 ID (Primary)
SOURCE_USER_EMAIL     — OneDrive 파일 소유자 (smlee@gst365.onmicrosoft.com)
FALLBACK_BASE_PATH    — OneDrive 폴더 경로 (생산관리팀/1.정기업무/1.일정관리/2026년)
```

## Excel 다운로드 전략
1. **Primary (방법 A)**: SOURCE_DOC_ID로 OneDrive 직접 접근
2. **Fallback (방법 B)**: 404 시 FALLBACK_BASE_PATH에서 W{NN} 폴더 탐색 → 최신 SCR 파일

## 컬럼 매핑
- COLUMN_MAPPING: 17개 (한글 → 영문)
- EXTRA_COLUMNS: 3개 (module_outsourcing, semi_product_start, finishing_plan_end)
- finishing_plan_end: 컬럼명 "마무리계획종료일"로 먼저 탐색, 실패 시 BU열(index 72) fallback

## ETL 실행 방법
```bash
# 소량 테스트
python etl_main.py --start 2026-01-01 --end 2026-01-10

# 전체
python etl_main.py --all

# cron (옵션 없이) → 반기 자동 필터 (2개월 버퍼)
python etl_main.py
```

## 반기 자동 필터 전략
- 1~6월 실행: 전년 11월 1일 ~ 현재
- 7~12월 실행: 5월 1일 ~ 현재
- UPSERT라 겹치는 데이터는 "동일"로 처리, 부하 없음

## 관련 Repo
- **axis-ops**: Flask API + 모바일 앱 + DB 스키마 (이 ETL이 적재하는 대상)
- **axis-view**: React 관리자 대시보드 (QR 관리 페이지에서 적재된 데이터 조회)
- **Autolink**: Graph API 인증 패턴 참고 (autolink/auth/teams_auth.py)

## 코딩 규칙
- 한글 주석 사용
- print 로그에 이모지 사용 (✅ ⚠️ ❌ 📥 📂)
- 환경변수는 하드코딩 금지 — os.environ 또는 .env에서 로드
- Sprint 완료 시 PROGRESS.md 업데이트 + SPRINT_COMPLETION_TEMPLATE.md에 맞춰 기록
