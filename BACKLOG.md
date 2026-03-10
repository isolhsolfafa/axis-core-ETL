# CORE-ETL 백로그

> 마지막 업데이트: 2026-03-10

---

## Sprint 이력

| Sprint | 내용 | 상태 |
|--------|------|------|
| 0 | 초기 구성 — OPS에서 분리, Graph API 통합, GitHub Actions | ✅ 완료 |
| 1 | UPSERT 전환 + 컬럼 매핑 교정 + 데이터 누락 해결 (39→158건) | ✅ 완료 |
| 2 | 변경 이력 추적 + actual_ship_date + VIEW 연동 | 🔄 진행 중 |

---

## 백로그 (우선순위 순)

### 1. 변경 이력 추적 + VIEW 대시보드 — Sprint 2 진행 중
- **ETL 코드 구현 완료** (Task 1~3): change_log 기록 + actual_ship_date + shipped 처리
- **남은 작업**: Task 4 (OPS BE 엔드포인트) → Task 5 (VIEW API 연동)
- **상세**: `docs/SPRINT_2.md` 참고
- **시기**: Sprint 2 (2026-03-10~)

### 2. 복수 연도 지원
- **내용**: 2026년 + 2027년 동시 처리 (FALLBACK_BASE_PATH 리스트화)
- **목적**: 연말~연초 데이터 교차 시점 대응
- **시기**: 2026년 하반기

### 3. ETL 실행 이력 테이블
- **내용**: DB에 `etl.run_history` 테이블 생성 → 실행 시간, 건수, 에러 기록
- **목적**: 운영 이력 추적 + 장애 진단
- **시기**: 미정

### 4. 협력사 평가지수 연동
- **내용**: finishing_plan_end(마무리계획종료일) 기반 납기 준수율 KPI 산출
- **목적**: 협력사 평가 + 실적관리 대시보드 (AXIS-VIEW 연동)
- **시기**: Sprint 1 완료 후

### 5. S/N 미등록 건수 추적 + VIEW 연동
- **내용**: ETL step1에서 S/N 누락으로 skip된 건수를 DB에 기록, VIEW QR 관리 페이지에서 "미등록" KPI로 표시
- **배경**: `qr_registry.status`의 `revoked`는 실제 업무에서 사용 안 됨 (라벨기에서 doc_id+S/N 문자열만 추출하여 출력, 이력 추적 불가). S/N 미등록 건수가 실무적으로 더 유용
- **VIEW 변경**: KPI 카드 — Active/Revoked → **전체 등록 / S/N 미등록** 으로 교체
- **ETL 변경**: step1에서 S/N 누락 건수 카운트 → `etl.run_history`에 `skipped_no_sn` 저장
- **의존성**: 3번(ETL 실행 이력 테이블) 완료 후 진행
- **시기**: Sprint 1 이후

### 6. GBWS-6834 module_start "5083 모듈" 데이터 확인
- **증상**: step2 적재 시 `invalid input syntax for type date: "5083 모듈"` 에러
- **위치**: GBWS-6834의 `semi_product_start` → DB `module_start` (DATE 타입)
- **원인 추정**: Excel 해당 셀에 날짜가 아닌 텍스트("5083 모듈") 입력 — 현장 확인 필요
- **확인 사항**: Excel 원본에서 해당 셀 값이 오입력인지, 의도된 메모인지 확인
- **대응**: 오입력이면 Excel 수정 / 의도된 값이면 ETL에서 날짜 파싱 실패 시 NULL 처리 방어 로직 추가
- **시기**: 현장 확인 후

### 7. ERP 데이터 연동 (장기)
- **내용**: ERP 시스템에서 추가 데이터 소스 ETL
- **시기**: 미정

---

## GitHub Secrets (axis-core-etl repo)

| Secret Name | 용도 | 등록 |
|---|---|---|
| `DATABASE_URL` | Railway PostgreSQL | ✅ |
| `TEAMS_TENANT_ID` | MSAL 인증 | ✅ |
| `TEAMS_CLIENT_ID` | MSAL 인증 | ✅ |
| `TEAMS_CLIENT_SECRET` | MSAL 인증 | ✅ |
| `SOURCE_DOC_ID` | Primary Excel 파일 ID | ✅ |
| `SOURCE_USER_EMAIL` | OneDrive 소유자 | ✅ |
| `FALLBACK_BASE_PATH` | Fallback 폴더 경로 | ✅ |
