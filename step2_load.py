#!/usr/bin/env python3
"""
Step 2: Load - Staging DB (PostgreSQL) 적재 + qr_doc_id 생성

DB 스키마:
  plan.product_info  — 생산 메타데이터 (S/N, model, 일정, 협력사...)
  public.qr_registry — QR ↔ 제품 매핑 (qr_doc_id, serial_number, status)
  etl.change_log     — 핵심 5개 필드 변경 이력 (Sprint 2)

환경변수:
  DATABASE_URL — PostgreSQL 접속 URL

일정 컬럼 매핑 (ETL 필드 → DB 컬럼):
  mech_start       → mech_start, prod_date (MM)
  mech_end         → mech_end (MM)
  elec_start       → elec_start (EE)
  elec_end         → elec_end (EE)
  semi_product_start → module_start (TM)
  pressure_test    → pi_start (PI 가압검사)
  process_inspect  → qi_start (QI 공정검사)
  finishing_start  → si_start (SI 마무리검사)
  planned_finish   → ship_plan_date (출하계획일)
  finishing_plan_end → finishing_plan_end (마무리계획종료일)
  actual_ship_date → actual_ship_date (출고일자 실적)
"""

import os
from datetime import date, timedelta

import psycopg2


# ── 변경 추적 대상 (5개 필드) ──────────────────────────────────
# ETL 필드명 → DB 컬럼명
TRACKED_FIELDS = {
    'order_no':       'sales_order',
    'planned_finish': 'ship_plan_date',
    'mech_start':     'mech_start',
    'mech_partner':   'mech_partner',
    'elec_partner':   'elec_partner',
}


def get_db_url():
    """환경변수에서 DB URL 가져오기"""
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise ValueError("DATABASE_URL 환경변수가 설정되지 않았습니다.")
    return url


def generate_qr_doc_id(serial_number):
    """
    qr_doc_id 생성 (S/N 기반)
    형식: DOC_{serial_number}
    예: DOC_GBWS-6408
    """
    return f"DOC_{serial_number}"


def _normalize_value(val):
    """비교용 값 정규화: None/빈문자열 → None, 나머지 → str"""
    if val is None or val == '':
        return None
    return str(val)


def _prefetch_tracked_values(cursor, serial_numbers):
    """
    변경 추적 대상 5개 필드의 기존 값을 일괄 조회 → dict 반환
    레코드당 SELECT 제거 → 1회 쿼리로 전체 캐시
    Returns: {serial_number: {db_col: value, ...}, ...}
    """
    if not serial_numbers:
        return {}

    # IN 절로 일괄 조회
    placeholders = ','.join(['%s'] * len(serial_numbers))
    cursor.execute(f"""
        SELECT serial_number, sales_order, ship_plan_date, mech_start, mech_partner, elec_partner
        FROM plan.product_info
        WHERE serial_number IN ({placeholders})
    """, serial_numbers)

    cache = {}
    for row in cursor.fetchall():
        cache[row[0]] = {
            'sales_order':    row[1],
            'ship_plan_date': str(row[2]) if row[2] else None,
            'mech_start':     str(row[3]) if row[3] else None,
            'mech_partner':   row[4],
            'elec_partner':   row[5],
        }
    return cache


def _record_changes(cursor, sn, item, existing_cache):
    """
    캐시된 기존 값과 5개 추적 필드 비교 → change_log INSERT
    신규 레코드(캐시에 없음)는 변경 기록 없이 스킵.
    Returns: 기록된 변경 건수
    """
    old_values = existing_cache.get(sn)
    if not old_values:
        return 0  # 신규 레코드 — 변경 이력 없음

    change_count = 0
    for etl_key, db_col in TRACKED_FIELDS.items():
        old_val = _normalize_value(old_values.get(db_col))
        new_val = _normalize_value(item.get(etl_key))

        if old_val != new_val:
            cursor.execute("""
                INSERT INTO etl.change_log (serial_number, field_name, old_value, new_value)
                VALUES (%s, %s, %s, %s)
            """, (sn, db_col, old_val, new_val))
            change_count += 1

    return change_count


BATCH_SIZE = 500  # 배치 단위 커밋 (대량 데이터 안정성)


def _process_single_record(cursor, item, existing_cache):
    """
    단일 레코드 UPSERT 처리
    Returns: (result_dict, change_count) or raises Exception
    """
    sn = item['serial_number']
    mech_start = item.get('mech_start') or None

    # 0) 변경 이력 기록 (캐시 기반, UPSERT 직전)
    change_count = _record_changes(cursor, sn, item, existing_cache)

    # 1) plan.product_info UPSERT
    params = (
        sn, item['model_name'],
        item.get('title_number', ''),
        item.get('product_code', ''),
        item.get('order_no', ''),
        item.get('customer', ''),
        item.get('line', ''),
        item.get('quantity', '1'),
        item.get('mech_partner', ''),
        item.get('elec_partner', ''),
        item.get('module_outsourcing', ''),
        mech_start,
        mech_start,
        item.get('mech_end') or None,
        item.get('elec_start') or None,
        item.get('elec_end') or None,
        item.get('semi_product_start') or None,
        item.get('pressure_test') or None,
        item.get('process_inspect') or None,
        item.get('finishing_start') or None,
        item.get('planned_finish') or None,
        item.get('finishing_plan_end') or None,
        item.get('actual_ship_date') or None,
    )
    cursor.execute('''
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
            finishing_plan_end,
            actual_ship_date
        ) VALUES (
            %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s,
            %s, %s,
            %s, %s,
            %s,
            %s, %s, %s,
            %s,
            %s,
            %s
        )
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
            actual_ship_date = EXCLUDED.actual_ship_date,
            prod_date = EXCLUDED.prod_date,
            updated_at = NOW()
        WHERE
            plan.product_info.model IS DISTINCT FROM EXCLUDED.model
            OR plan.product_info.sales_order IS DISTINCT FROM EXCLUDED.sales_order
            OR plan.product_info.customer IS DISTINCT FROM EXCLUDED.customer
            OR plan.product_info.mech_partner IS DISTINCT FROM EXCLUDED.mech_partner
            OR plan.product_info.elec_partner IS DISTINCT FROM EXCLUDED.elec_partner
            OR plan.product_info.module_outsourcing IS DISTINCT FROM EXCLUDED.module_outsourcing
            OR plan.product_info.mech_start IS DISTINCT FROM EXCLUDED.mech_start
            OR plan.product_info.mech_end IS DISTINCT FROM EXCLUDED.mech_end
            OR plan.product_info.elec_start IS DISTINCT FROM EXCLUDED.elec_start
            OR plan.product_info.elec_end IS DISTINCT FROM EXCLUDED.elec_end
            OR plan.product_info.module_start IS DISTINCT FROM EXCLUDED.module_start
            OR plan.product_info.pi_start IS DISTINCT FROM EXCLUDED.pi_start
            OR plan.product_info.qi_start IS DISTINCT FROM EXCLUDED.qi_start
            OR plan.product_info.si_start IS DISTINCT FROM EXCLUDED.si_start
            OR plan.product_info.ship_plan_date IS DISTINCT FROM EXCLUDED.ship_plan_date
            OR plan.product_info.finishing_plan_end IS DISTINCT FROM EXCLUDED.finishing_plan_end
            OR plan.product_info.actual_ship_date IS DISTINCT FROM EXCLUDED.actual_ship_date
            OR plan.product_info.prod_date IS DISTINCT FROM EXCLUDED.prod_date
        RETURNING id, (xmax = 0) AS is_insert
    ''', params)
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "SELECT id FROM plan.product_info WHERE serial_number = %s", (sn,)
        )
        product_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT qr_doc_id FROM public.qr_registry WHERE serial_number = %s", (sn,)
        )
        qr_row = cursor.fetchone()
        qr_doc_id = qr_row[0] if qr_row else generate_qr_doc_id(sn)
        status = 'unchanged'
    elif row[1]:
        product_id = row[0]
        qr_doc_id = generate_qr_doc_id(sn)
        cursor.execute('''
            INSERT INTO public.qr_registry (qr_doc_id, serial_number, status)
            VALUES (%s, %s, 'active')
            RETURNING id
        ''', (qr_doc_id, sn))
        cursor.fetchone()
        status = 'inserted'
    else:
        product_id = row[0]
        cursor.execute(
            "SELECT qr_doc_id FROM public.qr_registry WHERE serial_number = %s", (sn,)
        )
        qr_row = cursor.fetchone()
        qr_doc_id = qr_row[0] if qr_row else generate_qr_doc_id(sn)
        status = 'updated'

    # shipped 상태 처리
    actual_ship = item.get('actual_ship_date') or None
    if actual_ship:
        ship_date = date.fromisoformat(actual_ship)
        if ship_date <= date.today() - timedelta(days=1):
            cursor.execute("""
                UPDATE public.qr_registry
                SET status = 'shipped'
                WHERE serial_number = %s AND status = 'active'
            """, (sn,))
            if cursor.rowcount > 0:
                print(f"  [📦 출고] {sn} → shipped (출고일: {actual_ship})")

    return {
        'id': product_id,
        'serial_number': sn,
        'qr_doc_id': qr_doc_id,
        'model_name': item['model_name'],
        'product_code': item.get('product_code', ''),
        'status': status,
    }, change_count


def load_to_postgres(metadata_list, db_url=None):
    """
    Staging DB (PostgreSQL)에 UPSERT 적재 (배치 단위 커밋)
    - BATCH_SIZE(500건)마다 commit → 대량 데이터 안정성 확보
    - 레코드 단위 SAVEPOINT로 개별 에러 격리

    Args:
        metadata_list: step1에서 추출한 metadata 리스트
        db_url: DB 접속 URL (None이면 환경변수 사용)
    Returns:
        list[dict]: 적재 결과 (serial_number, qr_doc_id, model_name 등)
    """
    if db_url is None:
        db_url = get_db_url()

    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    cursor.execute("SET timezone = 'Asia/Seoul'")

    total = len(metadata_list)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"[Load] 전체 {total}건 → {total_batches}개 배치 ({BATCH_SIZE}건 단위)")

    # 변경 추적용 기존 값 일괄 조회 (1회 쿼리)
    all_sns = [item['serial_number'] for item in metadata_list]
    existing_cache = _prefetch_tracked_values(cursor, all_sns)
    print(f"[Load] 변경 추적 대상: 기존 {len(existing_cache)}건 / 전체 {len(all_sns)}건")

    results = []
    error_count = 0
    total_changes = 0

    for batch_idx in range(total_batches):
        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch = metadata_list[batch_start:batch_end]

        for item in batch:
            sn = item['serial_number']
            try:
                cursor.execute("SAVEPOINT sp_record")
                result, change_count = _process_single_record(cursor, item, existing_cache)
                total_changes += change_count
                cursor.execute("RELEASE SAVEPOINT sp_record")
                results.append(result)

                # 상태별 로그 (배치 모드에서는 신규/변경만 출력)
                if result['status'] == 'inserted':
                    print(f"  [✅ 신규] {sn} → {result['qr_doc_id']}")
                elif result['status'] == 'updated':
                    log_suffix = f" (이력 {change_count}건)" if change_count > 0 else ""
                    print(f"  [🔄 변경] {sn}{log_suffix}")

            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT sp_record")
                error_count += 1
                print(f"  [❌ Error] {sn}: {e}")

        # 배치 단위 커밋
        conn.commit()
        print(f"  [📦 배치 {batch_idx + 1}/{total_batches}] {len(batch)}건 커밋 완료 ({batch_end}/{total})")

    conn.close()

    # 결과 요약 출력
    inserted = sum(1 for r in results if r['status'] == 'inserted')
    updated = sum(1 for r in results if r['status'] == 'updated')
    unchanged = sum(1 for r in results if r['status'] == 'unchanged')
    print(f"[Load] PostgreSQL 적재 완료: 신규 {inserted}건, 변경 {updated}건, 동일 {unchanged}건")
    if total_changes > 0:
        print(f"[Load] 📋 변경 이력 {total_changes}건 기록 (etl.change_log)")
    if error_count > 0:
        print(f"[Load] ⚠️ 에러 {error_count}건 (해당 레코드 스킵, 나머지 정상 커밋)")
    return results


if __name__ == '__main__':
    from step1_extract import extract_from_teams_excel
    data = extract_from_teams_excel()
    results = load_to_postgres(data)
    print(f"\n적재 결과:")
    for r in results:
        print(f"  {r['serial_number']} → {r['qr_doc_id']} ({r['model_name']}) [{r['status']}]")
