# Sprint 2: 변경 이력 추적 + VIEW 연동

> 시작일: 2026-03-10
> 상태: ✅ 완료 (Task 1~6 전체 완료)

---

## 목표

ETL UPSERT 시 핵심 5개 필드의 변경 이력을 DB에 기록하고,
AXIS-VIEW에 "ETL 변경 이력" 페이지를 추가하여 일정/협력사 변동을 시각적으로 모니터링.

---

## 변경 추적 대상 (5개 필드)

| 사용자 표현 | ETL 필드 | DB 컬럼 (plan.product_info) | 추적 이유 |
|---|---|---|---|
| 판매오더 | order_no | sales_order | 오더 변경 → 생산 계획 전면 수정 |
| 출하예정 | planned_finish | ship_plan_date | 납기 변동 → 협력사 평가 KPI |
| 기구시작 | mech_start | mech_start | 착수일 변경 → 전체 공정 밀림 |
| 기구외주 | mech_partner | mech_partner | 협력사 교체 |
| 전장외주 | elec_partner | elec_partner | 협력사 교체 |

> UPSERT 비교는 기존 17개 필드 전부 유지. change_log 기록만 5개 필드 한정.

---

## Task 1: DB 스키마 — etl.change_log 테이블 ✅ 완료 (2026-03-10)

```sql
-- 스키마 생성 (최초 1회)
CREATE SCHEMA IF NOT EXISTS etl;

-- 변경 이력 테이블
CREATE TABLE etl.change_log (
    id SERIAL PRIMARY KEY,
    serial_number VARCHAR(50) NOT NULL,
    field_name VARCHAR(50) NOT NULL,       -- 'sales_order' | 'ship_plan_date' | 'mech_start' | 'mech_partner' | 'elec_partner'
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMP DEFAULT NOW()
);

-- 조회 성능 인덱스
CREATE INDEX idx_changelog_sn ON etl.change_log (serial_number);
CREATE INDEX idx_changelog_date ON etl.change_log (changed_at DESC);
CREATE INDEX idx_changelog_field ON etl.change_log (field_name);
```

**실행 완료**: Railway PostgreSQL에서 직접 실행 (2026-03-10)

---

## Task 2: step2_load.py 수정 — change_log 기록 로직 ✅ 완료 (2026-03-10)

### 변경 내용

UPSERT 실행 **직전**에 기존 값을 SELECT하고, 5개 필드를 비교하여 변경분만 `etl.change_log`에 INSERT.

### 구현 사항
- `TRACKED_FIELDS` 상수: ETL 필드명 → DB 컬럼명 매핑 (5개)
- `_normalize_value()`: NULL/빈문자열 정규화 함수
- `_record_changes()`: 기존 값 SELECT → 비교 → change_log INSERT (SAVEPOINT 범위 내)
- 로그 출력: 레코드별 `(이력 N건)`, 요약 `📋 변경 이력 N건 기록`

### 의사 코드

```python
TRACKED_FIELDS = {
    # ETL 필드명: DB 컬럼명
    'order_no':       'sales_order',
    'planned_finish': 'ship_plan_date',
    'mech_start':     'mech_start',
    'mech_partner':   'mech_partner',
    'elec_partner':   'elec_partner',
}

# UPSERT 직전에 기존 값 조회
cursor.execute("""
    SELECT sales_order, ship_plan_date, mech_start, mech_partner, elec_partner
    FROM plan.product_info
    WHERE serial_number = %s
""", (sn,))
existing = cursor.fetchone()

if existing:
    old_values = {
        'sales_order':    existing[0],
        'ship_plan_date': str(existing[1]) if existing[1] else None,
        'mech_start':     str(existing[2]) if existing[2] else None,
        'mech_partner':   existing[3],
        'elec_partner':   existing[4],
    }

    for etl_key, db_col in TRACKED_FIELDS.items():
        new_val = item.get(etl_key) or None
        old_val = old_values.get(db_col)

        # 빈 문자열 → None 정규화
        if new_val == '': new_val = None
        if old_val == '': old_val = None

        if str(new_val) != str(old_val):
            cursor.execute("""
                INSERT INTO etl.change_log (serial_number, field_name, old_value, new_value)
                VALUES (%s, %s, %s, %s)
            """, (sn, db_col, old_val, new_val))
```

### 주의사항
- 날짜 필드는 `str()` 변환 후 비교 (DATE 타입 vs 문자열)
- NULL ↔ 빈 문자열 정규화 필수
- 기존 UPSERT 로직(17개 필드 비교)은 변경 없음
- SAVEPOINT 범위 안에서 실행 → 에러 시 같이 롤백

---

## Task 3: 출고일자(실적) 적재 + shipped 상태 처리 ✅ 완료 (2026-03-10)

> ✅ Excel 컬럼 확인 완료 (2026-03-10)
> - R열 (index 17): `출고` ← 실제 출고일(실적) — **신규 ETL 추가**
> - U열 (index 20): `출고계획일` ← 출하예정 — 기존 COLUMN_MAPPING `planned_finish`로 매핑 완료

### 3-1. step1 변경
```python
# EXTRA_COLUMNS에 추가
"actual_ship_date": {"name": "출고", "index": 17},  # R열 (0-indexed), Excel 원본 오타 그대로

# _find_extra_column()이 이름 기반 탐색 → fallback index 순서로 동작
# "출고"로 정확히 매칭되므로 fallback 불필요하지만 안전장치로 index 17 지정

# DATE_FIELDS에 추가
EXTRA_DATE_FIELDS = {"semi_product_start", "finishing_plan_end", "actual_ship_date"}
```

### 3-2. DB 마이그레이션
```sql
ALTER TABLE plan.product_info
    ADD COLUMN IF NOT EXISTS actual_ship_date DATE;
```

### 3-3. step2 변경 — UPSERT에 actual_ship_date 추가 + shipped 처리
```python
# UPSERT INSERT/UPDATE에 actual_ship_date 컬럼 추가

# UPSERT 후 shipped 처리
actual_ship = item.get('actual_ship_date') or None
if actual_ship:
    from datetime import date, timedelta
    ship_date = date.fromisoformat(actual_ship)
    if ship_date <= date.today() - timedelta(days=1):
        cursor.execute("""
            UPDATE public.qr_registry
            SET status = 'shipped'
            WHERE serial_number = %s AND status = 'active'
        """, (sn,))
```

**shipped 판단 기준**: `actual_ship_date <= today - 1일` (어제까지 출고된 건)

---

## Task 4: OPS BE 엔드포인트 — change_log 조회 API ✅ 완료

> OPS_API_REQUESTS.md에 등록 (VIEW는 BE 코드 수정 금지)

### 엔드포인트

| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| `GET` | `/api/admin/etl/changes` | is_admin, is_manager | 변경 이력 목록 |

### 쿼리 파라미터

| 파라미터 | 타입 | 설명 | 기본값 |
|----------|------|------|--------|
| `days` | int | 최근 N일 | 7 |
| `field` | string | 특정 필드만 필터 | (전체) |
| `serial_number` | string | 특정 S/N만 | (전체) |
| `limit` | int | 최대 건수 | 100 |

### 응답 예시
```json
{
  "changes": [
    {
      "id": 42,
      "serial_number": "GBWS-6408",
      "model": "SCR-1234",
      "field_name": "ship_plan_date",
      "field_label": "출하예정",
      "old_value": "2026-03-15",
      "new_value": "2026-03-22",
      "changed_at": "2026-03-09T09:15:00+09:00"
    }
  ],
  "summary": {
    "total_changes": 15,
    "by_field": {
      "ship_plan_date": 6,
      "mech_start": 4,
      "mech_partner": 3,
      "sales_order": 1,
      "elec_partner": 1
    }
  }
}
```

---

## Task 5: AXIS-VIEW — ETL 변경 이력 페이지 ✅ API 연동 완료 (2026-03-11)

> QR관리 하위 페이지로 구현 완료 (2026-03-09). API 연동 완료 (2026-03-11).

### 실제 구현 파일

```
app/src/
  pages/qr/
    EtlChangeLogPage.tsx          # 단일 파일 구현 (KPI + 필터 + 테이블 + 차트)
  App.tsx                         # /qr/changes 라우트 추가 (ProtectedRoute)
```

> 초기 설계에서 `pages/etl/` + 컴포넌트 분리 구조를 계획했으나,
> G-AXIS 디자인 시스템에 맞춰 단일 파일(`EtlChangeLogPage.tsx`)로 구현.
> API 연동 시 컴포넌트 분리 리팩토링 검토.

### 구현된 UI 구성

| 영역 | 설명 | 상태 |
|------|------|------|
| KPI 카드 (5개) | 전체 변경 + 출하예정 + 기구시작 + 기구외주 + 전장외주. 클릭 시 필터 | ✅ Mock |
| 필터 바 | 필드 드롭다운 + S/N 검색 input | ✅ Mock |
| 변경 이력 테이블 | S/N, 변경항목(컬러 배지), 이전값, 변경값(취소선+차이), 변경일 | ✅ Mock |
| 날짜 차이 표시 | 출하예정/기구시작: +Nd/-Nd 자동 계산, 지연=빨강/앞당김=초록 | ✅ Mock |
| 주간 추이 차트 | 필드별 stacked bar chart (직접 SVG 렌더링) | ✅ Mock |

### API 연동 구현 (2026-03-11)

```
app/src/
  api/etl.ts                          # getEtlChanges() — GET /api/admin/etl/changes
  hooks/useEtlChanges.ts              # TanStack Query 훅 (staleTime: 60초)
  pages/qr/EtlChangeLogPage.tsx       # Mock 제거 → useEtlChanges() 연동
```

- `days` 파라미터로 기간 필터 (7/14/30일)
- `field`, `serial_number` 파라미터로 필드/S/N 필터
- KPI 카드: API summary 응답 활용
- 로딩/에러 상태 UI 추가
- 차트: 데이터 없을 때 빈 상태 표시

---

## Task 6: Sidebar 서브메뉴 ✅ 구현 완료

> QR관리 하위 메뉴로 구현 (별도 메뉴 아님)

### 실제 구현 내용

| 항목 | 초기 설계 | 실제 구현 |
|------|----------|----------|
| 위치 | Dashboard 그룹 별도 메뉴 | QR관리 하위 서브메뉴 |
| 경로 | `/etl-changes` | `/qr/changes` |
| 메뉴 구조 | 단일 NavItem | QR관리 → QR Registry + 변경 이력 (확장/축소) |

### 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `Sidebar.tsx` | SubNavItem 인터페이스 추가, children 지원, ChevronIcon 토글 애니메이션, QR관리 하위 메뉴 |
| `App.tsx` | `/qr/changes` → `EtlChangeLogPage` 라우트 (ProtectedRoute) |

### Sidebar 메뉴 구조

```
📊 협력사 대시보드     /attendance
📋 QR 관리            (확장/축소)
   ├─ QR Registry     /qr
   └─ 변경 이력        /qr/changes
🔒 생산 현황           (비활성)
🔒 KPI 리포트          (비활성)
```

---

## 의존성 관계

```
Task 1 (DB 스키마)              ← ✅ 완료 (2026-03-10)
  ↓
Task 2 (step2 수정)             ← ✅ 완료 (2026-03-10)
  ↓
Task 3 (출고일자 + shipped)     ← ✅ 완료 (2026-03-10)
  ↓
Task 4 (OPS BE 엔드포인트)      ← ✅ 완료
  ↓
Task 5 (VIEW Mock → API 연동)   ← ✅ API 연동 완료 (2026-03-11)
  ↓
Task 6 (Sidebar 메뉴)           ← ✅ 구현 완료
```

- Task 1~3: ✅ ETL 코드 구현 + DB 마이그레이션 완료 (2026-03-10)
- Task 4: ✅ OPS BE 엔드포인트 완료
- Task 5: ✅ API 연동 완료 (2026-03-11)
- Task 6: ✅ 완료

---

## 참고: 기존 UPSERT 동작 (변경 없음)

step2_load.py의 UPSERT는 기존 17개 필드 전부 비교하여 동작:
- `IS DISTINCT FROM` 조건으로 하나라도 다르면 → UPDATE
- 전부 같으면 → 변경 없음 (unchanged)
- 이 로직은 Sprint 2에서 수정하지 않음

Sprint 2에서 추가하는 건 UPSERT **직전** SELECT + 5개 필드 비교 → change_log INSERT 로직만.

UPSERT의 IS DISTINCT FROM 비교는 기존 17개 → **18개**로 확장 (`actual_ship_date` 추가).
