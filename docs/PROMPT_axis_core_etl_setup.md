# axis-core-etl Repo 생성 + ETL 분리 프롬프트

## 목표
AXIS-OPS repo 내 `etl/` 폴더를 별도 repo `axis-core-etl`로 분리하고,
AXIS-OPS에서 ETL 관련 파일을 제거한다.

---

## 1. 로컬 폴더 구조

```
/Users/kdkyu311/Desktop/GST/
├── AXIS-OPS/          (기존 — etl/ 제거 예정)
├── AXIS-VIEW/         (기존 — 변경 없음)
└── AXIS-CORE/
    └── CORE-ETL/      (신규 repo)
```

---

## 2. 실행 순서

### Step 1: 폴더 생성 + Git 초기화

```bash
cd /Users/kdkyu311/Desktop/GST
mkdir -p AXIS-CORE/CORE-ETL
cd AXIS-CORE/CORE-ETL
git init
```

### Step 2: AXIS-OPS에서 ETL 파일 복사

```bash
# ETL 소스 파일
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/etl/etl_main.py .
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/etl/step1_extract.py .
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/etl/step2_load.py .
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/etl/requirements.txt .
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/etl/PROMPT_step1_graph_api.md .

# .gitignore
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/etl/.gitignore .

# GitHub Actions workflow
mkdir -p .github/workflows
cp /Users/kdkyu311/Desktop/GST/AXIS-OPS/.github/workflows/etl-metadata-sync.yml .github/workflows/
```

### Step 3: CORE-ETL 최종 구조 확인

```
AXIS-CORE/CORE-ETL/
├── etl_main.py                  # 오케스트레이터
├── step1_extract.py             # Excel 추출 (Graph API 통합 예정)
├── step2_load.py                # PostgreSQL 적재
├── requirements.txt             # 의존성
├── PROMPT_step1_graph_api.md    # Graph API 통합 프롬프트
├── .gitignore                   # output/, .env 등
└── .github/
    └── workflows/
        └── etl-metadata-sync.yml  # GitHub Actions cron
```

### Step 4: GitHub에 repo 생성 + push

```bash
cd /Users/kdkyu311/Desktop/GST/AXIS-CORE/CORE-ETL

# GitHub에 repo 생성 (gh CLI 사용)
gh repo create isolhsolfafa/axis-core-etl --private --source=. --remote=origin

# 또는 수동으로 GitHub에서 repo 생성 후:
# git remote add origin https://github.com/isolhsolfafa/axis-core-etl.git

git add -A
git commit -m "Initial commit: ETL pipeline (AXIS-OPS에서 분리)

- etl_main.py: 오케스트레이터 (CLI: --date, --all, --field)
- step1_extract.py: SCR Excel 추출 (로컬 SCR-Schedule 의존 → Graph API 전환 예정)
- step2_load.py: PostgreSQL 적재 (plan.product_info + public.qr_registry)
- GitHub Actions: workflow_dispatch + 매주 월 09:00 KST cron
- Graph API 통합 프롬프트 포함 (PROMPT_step1_graph_api.md)"

git branch -M main
git push -u origin main
```

### Step 5: AXIS-OPS에서 ETL 파일 제거

```bash
cd /Users/kdkyu311/Desktop/GST/AXIS-OPS

# etl 폴더 제거
rm -rf etl/

# GitHub Actions workflow 제거
rm .github/workflows/etl-metadata-sync.yml

# 커밋
git add -A
git commit -m "Remove etl/ — axis-core-etl repo로 분리"
```

---

## 3. 분리 후 다음 작업

axis-core-etl repo에서 PROMPT_step1_graph_api.md를 프롬프트로 사용하여:

1. `step1_extract.py` Graph API 통합 (MSAL + OneDrive 다운로드 + fallback)
2. `etl/.env` 생성 (Autolink `.env_teams`에서 복사 + DATABASE_URL)
3. `pip install msal requests psycopg2-binary openpyxl pandas`
4. `python etl_main.py --all` 로컬 테스트
5. 정상이면 push
6. GitHub Secrets 등록 (axis-core-etl repo):
   - `DATABASE_URL`
   - `TEAMS_TENANT_ID`
   - `TEAMS_CLIENT_ID`
   - `TEAMS_CLIENT_SECRET`
   - `SOURCE_DOC_ID`
   - `SOURCE_USER_EMAIL`
   - `FALLBACK_BASE_PATH`

---

## 4. 참고: Repo 관계

```
axis-ops (Railway 배포)
  ├── Flask API + 모바일 앱
  └── DB 스키마 (plan.product_info, public.qr_registry)

axis-view (Netlify 배포)
  └── React 관리자 대시보드 → axis-ops API 호출

axis-core-etl (GitHub Actions cron)
  └── ETL 파이프라인 → axis-ops DB 직접 적재
      (axis-ops API 거치지 않음, DATABASE_URL로 직접 연결)
```
