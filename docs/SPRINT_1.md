# Sprint 1: UPSERT 전환 + 연도 필터링 + 마무리계획종료일

> 시작: 2026-03-09
> 상태: 🔧 진행 중

---

## 목표
1. step2_load.py의 INSERT → UPSERT 전환 (일정 변경 자동 반영)
2. Extract 시 연도 필터링 (26년 데이터만 적재)
3. 마무리계획종료일(finishing_plan_end) DB 적재 추가

---

## Task 1: step2_load.py — INSERT → UPSERT 전환

### 배경
현재 중복 S/N은 skip하는데, 이러면 일정 변경(기구시작일, 마무리계획종료일 등)이 DB에 반영 안 됨.

### 변경 내용

**plan.product_info** — `ON CONFLICT (serial_number) DO UPDATE`:

```sql
INSERT INTO plan.product_info (
    serial_number, model,
    title_number, product_code, sales_order,
    customer, line, quantity,
    mech_partner, elec_partner, module_outsourcing,
    prod_date,
    mech_start, mech_end,
    elec_start, elec_end,
    module_start,
    pi_start, qi_start, si_start,
    ship_plan_date,
    finishing_plan_end
) VALUES (...)
ON CONFLICT (serial_number)
DO UPDATE SET
    model = EXCLUDED.model,
    sales_order = EXCLUDED.sales_order,
    customer = EXCLUDED.customer,
    mech_partner = EXCLUDED.mech_partner,
    elec_partner = EXCLUDED.elec_partner,
    module_outsourcing = EXCLUDED.module_outsourcing,
    mech_start = EXCLUDED.mech_start,
    mech_end = EXCLUDED.mech_end,
    elec_start = EXCLUDED.elec_start,
    elec_end = EXCLUDED.elec_end,
    module_start = EXCLUDED.module_start,
    pi_start = EXCLUDED.pi_start,
    qi_start = EXCLUDED.qi_start,
    si_start = EXCLUDED.si_start,
    ship_plan_date = EXCLUDED.ship_plan_date,
    finishing_plan_end = EXCLUDED.finishing_plan_end,
    prod_date = EXCLUDED.prod_date,
    updated_at = NOW()
RETURNING id, (xmax = 0) AS is_insert;
```

> `(xmax = 0) AS is_insert`: PostgreSQL 트릭 — `true`면 INSERT, `false`면 UPDATE

**public.qr_registry** — UPSERT 불필요 (S/N 기준 이미 존재하면 QR 변경 없음)

### 결과 로그 변경

```
기존: 신규 3건, 중복 스킵 117건
변경: 신규 3건, 변경 5건, 동일 112건
```

---

## Task 2: 반기 기준 자동 필터링

### 배경
매번 Excel 전체를 파싱하지만, 전체 적재는 불필요. 반기(6개월) 단위로 필터링하여 UPSERT 범위를 제한.

### 전략: 고정 반기 구간

| 현재 월 | 시작 (고정) | 끝 (롤링) | 설명 |
|---------|-----------|----------|------|
| 3월 | 전년 11월 1일 | 4월 말 | 과거 2개월 버퍼 + 다음달 계획 |
| 6월 | 전년 11월 1일 | 7월 말 | 상반기 마지막 + 다음달 |
| 7월 | 5월 1일 | 8월 말 | 하반기 시작 + 다음달 |
| 12월 | 5월 1일 | 다음해 1월 말 | 하반기 마지막 + 다음달 |

> **시작**: 반기 기준 - 2개월 버퍼 (고정) → 변경분 누락 방지
> **끝**: 현재월 + 1개월 (롤링) → 가까운 미래 계획만 적재, 불필요한 원거리 데이터 제외
> batch UPSERT라 겹치는 데이터는 "동일 N건"으로 처리 — 시스템 부하 없음.

### 변경 내용

`etl_main.py`에 반기 자동 계산 + 기본 필터 적용:

```python
from datetime import datetime

def get_half_year_range():
    """현재 반기 (과거 2개월 버퍼 + 현재월 +1개월) 자동 계산"""
    from calendar import monthrange
    today = datetime.now()

    # 시작: 반기 시작 - 2개월 (고정)
    if today.month <= 6:
        date_from = f"{today.year - 1}-11-01"
    else:
        date_from = f"{today.year}-05-01"

    # 끝: 현재월 + 1개월 말일 (롤링)
    next_month = today.month + 1
    next_year = today.year
    if next_month > 12:
        next_month = 1
        next_year += 1
    last_day = monthrange(next_year, next_month)[1]
    date_to = f"{next_year}-{next_month:02d}-{last_day:02d}"

    return date_from, date_to
```

CLI 옵션이 없을 때(cron 실행) 기본 동작:

```python
# --all 이 아니고 --date/--start/--end도 없으면 → 반기 자동
if not args.all and not args.date and not args.start:
    start, end = get_half_year_range()
    run_etl(start=start, end=end, date_field=args.field)
```

### 연초/연말 운영
- **1월**: 전년도 하반기 일정 변경이 있을 수 있음 → `--all`로 1회 전체 실행
- **27년 연장 시**: `FALLBACK_BASE_PATH`에 2027년 경로 추가, 필터 범위는 자동 계산되므로 코드 변경 불필요

---

## Task 3: 마무리계획종료일 DB 적재

### 배경
BU열 "마무리계획종료일" — 협력사 평가지수 + 실적관리 기준일.
step1에서 이미 `finishing_plan_end`로 추출 중 (find_extra_column fallback 적용 완료).

### 변경 내용

**1) DB 스키마 — plan.product_info에 컬럼 추가:**

```sql
ALTER TABLE plan.product_info
ADD COLUMN IF NOT EXISTS finishing_plan_end DATE;
```

> 이 마이그레이션은 AXIS-OPS Railway DB에서 실행해야 함

**2) step2_load.py — INSERT/UPSERT에 finishing_plan_end 추가:**

Task 1의 UPSERT SQL에 이미 포함되어 있음. `item.get('finishing_plan_end') or None`으로 값 전달.

---

## 수정 파일 목록

| 파일 | 수정 내용 |
|------|----------|
| `step2_load.py` | INSERT → UPSERT (ON CONFLICT DO UPDATE) + finishing_plan_end |
| `etl_main.py` | 연도 필터 적용 (filter_by_year) + ETL_YEAR_FROM 환경변수 |
| `step1_extract.py` | (수정 불필요 — finishing_plan_end 이미 추출 중) |

---

## DB 마이그레이션 (AXIS-OPS Railway)

```sql
-- Railway DB에서 실행
ALTER TABLE plan.product_info
ADD COLUMN IF NOT EXISTS finishing_plan_end DATE;

-- updated_at 컬럼이 없으면 추가 (UPSERT 변경 추적용)
ALTER TABLE plan.product_info
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
```

---

## 테스트

```bash
cd /Users/kdkyu311/Desktop/GST/AXIS-CORE/CORE-ETL

# 1) 소량 테스트 (26년 1월 1~10일)
python etl_main.py --start 2026-01-01 --end 2026-01-10

# 2) 동일 데이터 재실행 → UPSERT 확인 (변경 0건, 동일 N건)
python etl_main.py --start 2026-01-01 --end 2026-01-10

# 3) 전체 26년 데이터
python etl_main.py --all
```

---

## 완료 조건
- [ ] step2_load.py UPSERT 전환 완료
- [ ] 연도 필터링 동작 확인 (25년 데이터 제외)
- [ ] finishing_plan_end DB 적재 확인
- [ ] 로컬 테스트 통과 (소량 → 재실행 → 전체)
- [ ] push + GitHub Actions workflow_dispatch 수동 실행 확인
