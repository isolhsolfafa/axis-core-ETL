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
- [x] step2_load.py UPSERT 전환 완료
- [x] 연도 필터링 동작 확인 (25년 데이터 제외)
- [x] finishing_plan_end DB 적재 확인
- [x] 로컬 테스트 통과 (소량 → 재실행 → 전체)
- [ ] push + GitHub Actions workflow_dispatch 수동 실행 확인

---

## Sprint 1-Debugging: Bug Fix — 컬럼 매핑 및 값 변환 오류

> 날짜: 2026-03-09
> 원인: ETL 실행 후 DB 적재 데이터 검증 시 발견

### 증상
- **모델명(model)**: Excel F열 "Model" 약자 저장 확인 (예: Dragon LE → DRG S). 코드 버그 아닌 Excel 데이터 자체가 약자
- **elec_start, elec_end**: 값 누락 — Excel 헤더 줄바꿈 매칭 실패
- **qi_start**: 값 누락 — Excel 헤더 "TEST계획시작일" ↔ COLUMN_MAPPING "공정시작" 불일치
- **전체**: 텍스트 필드에 날짜 포맷 함수 적용 → float 소수점 등 변환 오류

### 원인 분석

**1) `_format_date_value()` 일괄 적용 문제**
- 모든 필드(텍스트 포함)에 날짜 포맷 함수가 적용됨
- model_name, customer, line 등 텍스트 필드가 날짜 변환 로직을 거침
- Excel에서 숫자로 저장된 값이 float 변환 시 소수점 발생 (2100 → 2100.0)

**2) `_find_column()` 공백/줄바꿈 미처리**
- Excel 헤더에 셀 내 줄바꿈 포함 시 (예: "전장\n시작") 매칭 실패
- "전장시작"으로 검색해도 "전장\n시작" 컬럼을 찾지 못함
- 매칭 실패 → col_map에 미등록 → 해당 필드 데이터 누락

**3) COLUMN_MAPPING ↔ 실제 Excel 헤더 불일치**
- COLUMN_MAPPING이 대시보드 표시명 사용, 실제 Excel 헤더명과 다름
- "공정시작" → 실제 "TEST계획시작일" (BN열), "모델" → 실제 "Model" (F열)
- SCR-Schedule config.py에서 실제 헤더명 확인 후 COLUMN_ALIASES 추가로 해결

### 수정 내용

**1) `_find_column()` 정규화 매칭 (step1_extract.py)**
```python
def _find_column(df, candidates):
    """DataFrame에서 후보 컬럼명 중 존재하는 것 반환 (공백/줄바꿈 무시)"""
    for col in df.columns:
        col_normalized = re.sub(r"\s+", "", str(col))
        for c in candidates:
            c_normalized = re.sub(r"\s+", "", c)
            if c_normalized in col_normalized:
                return col
    return None
```

**2) 날짜/텍스트 필드 분리 처리**
```python
DATE_FIELDS = {
    "mech_start", "mech_end", "elec_start", "elec_end",
    "pressure_test", "self_inspect", "process_inspect",
    "finishing_start", "planned_finish",
}

def _format_text_value(val):
    """텍스트 값 변환 (모델명, 업체명 등 비날짜 필드)"""
    if pd.isna(val):
        return ''
    if isinstance(val, float) and val == int(val):
        return str(int(val))  # 2100.0 → "2100"
    return str(val).strip()
```

**3) 추출 루프 분기 적용**
```python
for eng_key, df_col in col_map.items():
    val = row[df_col]
    if eng_key in DATE_FIELDS:
        base_item[eng_key] = _format_date_value(val)
    else:
        base_item[eng_key] = _format_text_value(val)
```

**4) `_format_date_value()` 강화**
- 문자열 날짜 "2026-03-15 00:00:00" → "2026-03-15" 잘라내기 추가

**5) EXTRA_COLUMNS 추출 분기 누락 수정**
- `module_outsourcing`(모듈외주)은 업체명 텍스트인데 `_format_date_value()` 적용되고 있었음
- `EXTRA_DATE_FIELDS = {"semi_product_start", "finishing_plan_end"}` 분기 추가
- 날짜 필드만 date 포맷, 나머지는 `_format_text_value()` 적용

**6) COLUMN_ALIASES 추가 — 실제 Excel 헤더명 대체 검색**
```python
COLUMN_ALIASES = {
    "모델":     ["Model", "모델명"],
    "오더번호":  ["판매오더"],
    "기구업체":  ["기구외주"],
    "전장업체":  ["전장외주"],
    "기구시작":  ["기구계획시작일"],
    "기구종료":  ["기구계획종료일"],
    "전장시작":  ["전장계획시작일"],
    "전장종료":  ["전장계획종료일"],
    "가압시작":  ["가압계획시작일"],
    "자주검사":  ["가동검사계획시작일"],
    "공정시작":  ["TEST계획시작일", "TEST계획"],   # BN열
    "마무리시작": ["마무리계획시작일"],
    "출하":     ["출고계획일"],                    # U열
}
```
- SCR-Schedule config.py 기준 실제 헤더명 확인 후 적용
- 검색: `candidates = [kor_key] + COLUMN_ALIASES.get(kor_key, [])` 로 매칭 범위 확장
- 매칭 실패 시 Warning 로그 출력

### 수정 파일

| 파일 | 수정 내용 |
|------|----------|
| `step1_extract.py` | `_find_column()` 정규화, `DATE_FIELDS` 분리, `_format_text_value()` 추가, `COLUMN_ALIASES` 추가, EXTRA_COLUMNS 분기 |

### 확인된 컬럼 위치 (2026-03-09)

| ETL 필드 | Excel 열 | Excel 헤더 | 상태 |
|----------|---------|-----------|------|
| model_name | F열 | Model | ✅ 약자 저장 확인 (풀네임 필요 시 매핑 테이블 별도 추가) |
| process_inspect → qi_start | BN열 | TEST계획시작일 | ✅ COLUMN_ALIASES로 매칭 |
| planned_finish → ship_plan_date | U열 | 출고계획일 | ✅ 확인 완료 |

### 검증
- [ ] 모델명: Excel F열 약자 그대로 DB 적재 확인
- [ ] elec_start, elec_end 날짜 정상 적재 확인
- [ ] qi_start (TEST계획시작일 BN열) 날짜 정상 적재 확인
- [ ] ship_plan_date (출고계획일 U열) 날짜 정상 적재 확인
- [ ] 기존 정상 필드 (mech_start, S/N 등) 영향 없음 확인

### 미해결 (Backlog)
- **모델명 풀네임**: Excel F열에 약자 저장 (DRG S 등). 풀네임 필요 시 약자↔풀네임 매핑 테이블 또는 별도 컬럼 추가 필요

---

## Sprint 1-Investigation: ETL 데이터 누락 분석 (158건 → 39건)

> 날짜: 2026-03-09
> 증상: 3월 Excel 데이터 158건, POC 대시보드(SCR-Schedule) 100건+, ETL DB 39건
> 동일 data source (SCR 생산현황 Excel) 사용

### SCR-Schedule vs AXIS-CORE ETL 비교 분석

같은 Excel 파일을 읽는데 결과가 다른 원인을 코드 레벨에서 비교.

| 항목 | SCR-Schedule (POC) | AXIS-CORE ETL | 차이 영향 |
|------|-------------------|---------------|----------|
| **컬럼 접근** | 인덱스 기반 `row.iloc[col_idx - 1]` | 컬럼명 매칭 `_find_column()` | **ETL 매칭 실패 시 필드 누락** |
| **S/N 인덱스** | `("S/N", 31)` — AF열 고정 | `_find_column(df, ["S/N", "SN", "시리얼"])` | 매칭 성공하면 동일 |
| **기구시작 인덱스** | `("기구계획시작일", 46)` — AT열 고정 | COLUMN_ALIASES `["기구계획시작일"]` 매칭 | 매칭 성공하면 동일 |
| **데이터 로딩** | Graph API `usedRange` JSON (값 직접 수신) | 파일 다운로드 + `pd.read_excel()` | **Excel 수식/형식 차이 가능** |
| **날짜 필터 (3월)** | `filter_month_range=2` → {1,2,3,4,5월} | 반기 `2025-11-01 ~ 2026-04-30` | **범위는 ETL이 더 넓음 — 필터 문제 아님** |
| **빈 기구시작** | `else: continue` (스킵) | `item.get('mech_start', '') → falsy → 스킵` | 동일 동작 |
| **에러 핸들링** | 개별 필드 실패 → 빈 문자열, 행은 유지 | step2 KeyError → SAVEPOINT 롤백 → **행 전체 스킵** | **ETL이 더 많이 탈락** |

### 핵심 원인 (반기 필터 아님)

반기 필터 범위(~2026-04-30)는 3월 데이터를 포함하므로 필터 문제가 아님.
**ETL Extract → Load 과정에서 대량 탈락** 발생.

**원인 1: 컬럼명 매칭 방식 — 가장 유력**
- SCR-Schedule은 인덱스로 직접 접근하므로 항상 성공
- ETL은 `_find_column()`으로 컬럼명 매칭 → Excel 헤더 변경/병합 시 실패
- 매칭 실패한 필드는 `col_map`에 미등록 → `base_item`에 해당 키 없음
- step2에서 `item['model_name']` 접근 시 KeyError → SAVEPOINT 롤백 → 행 스킵

**원인 2: pd.read_excel() vs Graph API JSON 차이**
- Graph API는 Excel 수식 결과값을 직접 반환 (= 화면에 보이는 값)
- `pd.read_excel()`은 openpyxl로 파싱 — 셀 형식/병합/수식 처리가 다를 수 있음
- 특히 병합 셀 영역에서 NaN이 대량 발생 가능 → S/N 빈 행 제거 시 대량 탈락

**원인 3: step2 에러 누적**
- DB 제약 조건 위반 (날짜 형식, NOT NULL 등) → SAVEPOINT 롤백
- 현재 에러 로그가 단순해서 정확한 실패 건수/원인 파악 어려움

### 전체 누락 원인 분류 (수정)

| # | 단계 | 원인 | 심각도 | 영향 |
|---|------|------|--------|------|
| 1 | **Extract** | 컬럼명 매칭 실패 → 필드 누락 → step2 KeyError | 🔴 높음 | 대량 행 스킵 |
| 2 | **Extract** | pd.read_excel 병합 셀 NaN → S/N 빈 행 제거 대량 발생 | 🔴 높음 | Excel 구조 의존 |
| 3 | **Load** | DB 제약 위반 → SAVEPOINT 롤백 → 레코드 스킵 | 🟡 중간 | 날짜/형식 오류 |
| 4 | Extract | `parse_sn()` 비표준 형식 → 빈 리스트 → 행 스킵 | 🟡 중간 | 소수 |
| 5 | Filter | 기구시작일 비어있으면 범위 필터에서 탈락 | 🟡 중간 | 일부 |

### 개선 방안

**방안 1: SCR-Schedule처럼 인덱스 기반 fallback 추가 (권장)**
- COLUMN_MAPPING에 SCR-Schedule config.py의 인덱스를 fallback으로 추가
- `_find_column()` 실패 시 인덱스로 직접 접근
```python
# SCR-Schedule config.py 기준 인덱스 (1-based)
COLUMN_INDEX_FALLBACK = {
    "serial_number": 31,   # S/N — AF열
    "model_name": 6,       # Model — F열
    "order_no": 2,         # 판매오더 — B열
    "customer": 4,         # 고객사 — D열
    "product_code": 7,     # 제품번호 — G열
    "line": 5,             # 라인 — E열
    "mech_partner": 39,    # 기구외주
    "elec_partner": 40,    # 전장외주
    "mech_start": 46,      # 기구계획시작일 — AT열
    "mech_end": 48,        # 기구계획종료일
    "elec_start": 51,      # 전장계획시작일
    "elec_end": 52,        # 전장계획종료일
    "pressure_test": 58,   # 가압계획시작일
    "self_inspect": 62,    # 가동검사계획시작일
    "process_inspect": 66, # TEST계획시작일
    "finishing_start": 72, # 마무리계획시작일
    "planned_finish": 21,  # 출고계획일 — U열
}
```

**방안 2: 디버그 로그 강화 — 즉시 적용**
- step1: Extract 후 총 행수, S/N 빈 행 제거 수, parse_sn 실패 수 출력
- step2: 에러 유형별 카운트 + 샘플 SN 출력
```python
# step2 에러 상세 추적
error_details = {}
except Exception as e:
    err_type = type(e).__name__
    error_details.setdefault(err_type, []).append(sn)
# 요약 출력
for err_type, sns in error_details.items():
    print(f"  [{err_type}] {len(sns)}건 — 샘플: {sns[:3]}")
```

**방안 3: cron 기본 동작을 `--all`로 변경**
- UPSERT이므로 전체 적재해도 부하 없음
- 반기 필터 제거하면 기구시작일 비어있는 건도 포함

### parse_sn() 처리 한계 (참고)

현재 지원하는 형식:
- 단일: `GBWS-6408` → `["GBWS-6408"]`
- 쉼표: `GBWS-6408, GBWS-6409` → `["GBWS-6408", "GBWS-6409"]`
- 쉼표(접두사 보완): `DBW-3715,3716` → `["DBW-3715", "DBW-3716"]`
- 범위: `GBWS-6408~6410` → `["GBWS-6408", "GBWS-6409", "GBWS-6410"]`

미지원 형식 (파싱 실패 시 원본 그대로 반환):
- 접두사 없는 숫자 범위: `6408~6410`
- 혼합: `GBWS-6408~6410, 6412`

### 검증 방법

```bash
# 1) 26년 3월 기준 실행하여 Extract 건수 확인
python etl_main.py --start 2026-03-01 --end 2026-03-31

# 2) 로그에서 확인할 것:
#    - [Extract] Teams Excel 데이터 N건 추출 완료
#    - [⚠️ Warning] 컬럼 매칭 실패 목록
#    - [❌ Error] 에러 건수 및 원인
#    - [Load] 신규 N건, 변경 N건, 동일 N건

# 3) POC 대시보드 건수와 비교
#    - SCR-Schedule 실행 후 출력되는 "대시보드 데이터 추출: N건"과 대조
```

---

## 추가 조사 항목 (Sprint 2 범위)

> 2026-03-09 정리

### 1. 출고 완료 시 상태 변경
- **Source**: R열 "출고" 컬럼
- **동작**: 출고 값 존재 시 `qr_registry.status`를 `'shipped'`(또는 `'completed'`)로 변경
- **구현 위치**: step2_load.py UPSERT 로직 내 조건 분기 추가

### 2. 신규여부 컬럼 추가
- **Source**: N열 "신규여부"
- **값**: 양산(기본), 신규, 계약변경
- **DB**: `plan.product_info`에 `contract_type VARCHAR` 컬럼 추가 필요
- **ETL**: step1 EXTRA_COLUMNS + step2 매핑 추가
- **계약변경 시**: 해당 행에 Excel 메모(comment) 존재 여부 확인 필요 → openpyxl `cell.comment` 접근

### 3. Excel 메모/노트(comment) 추출
- **배경**: 계약변경 발생 시 Excel 셀에 메모 형태로 변경 사유 기록
- **확인 필요**: openpyxl로 `ws.cell(row, col).comment.text` 접근 가능한지
- **주의**: pandas `read_excel()`은 comment를 읽지 못함 → openpyxl 직접 접근 필요
- **구현 방향**: step1에서 openpyxl로 별도 comment 추출 후 metadata에 추가

### 4. 특이사항(영업) CJ열
- **Source**: CJ열(index 87) "특이사항(영업)"
- **현재**: step1 `EXTRA_COLUMNS`에 `sales_note` 추가 완료
- **남은 작업**:
  - DB 마이그레이션: `ALTER TABLE plan.product_info ADD COLUMN IF NOT EXISTS sales_note TEXT;`
  - step2_load.py: INSERT/UPSERT 쿼리에 `sales_note` 매핑 추가
  - VIEW: 화면 표시 (필요 시)

### 5. VIEW 날짜 필터 버그 — 수정 완료 ✅
- **증상**: "전체보기" 클릭 후 날짜 설정 시 필터 결과 나오지 않음
- **원인**: `showAll=true` 상태가 날짜 input 변경 시에도 유지
- **수정**: `dateField`, `dateFrom`, `dateTo` onChange에 `setShowAll(false)` 추가
- **파일**: `AXIS-VIEW/app/src/pages/qr/QrManagementPage.tsx`
