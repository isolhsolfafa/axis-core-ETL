#!/usr/bin/env python3
"""
Step 2: Load - Staging DB (PostgreSQL) 적재 + qr_doc_id 생성

DB 스키마:
  plan.product_info  — 생산 메타데이터 (S/N, model, 일정, 협력사...)
  public.qr_registry — QR ↔ 제품 매핑 (qr_doc_id, serial_number, status)

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
"""

import os
import psycopg2


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


def load_to_postgres(metadata_list, db_url=None):
    """
    Staging DB (PostgreSQL)에 적재
    1) plan.product_info INSERT
    2) public.qr_registry INSERT

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

    results = []
    for item in metadata_list:
        sn = item['serial_number']

        # 중복 체크 (qr_registry 기준)
        cursor.execute("SELECT id, qr_doc_id FROM public.qr_registry WHERE serial_number = %s", (sn,))
        existing = cursor.fetchone()
        if existing and existing[1]:
            print(f"  [Skip] {sn} → 이미 존재 (qr_doc_id: {existing[1]})")
            results.append({
                'id': existing[0],
                'serial_number': sn,
                'qr_doc_id': existing[1],
                'model_name': item['model_name'],
                'product_code': item.get('product_code', ''),
                'status': 'skipped',
            })
            continue

        try:
            qr_doc_id = generate_qr_doc_id(sn)
            mech_start = item.get('mech_start') or None

            # 1) plan.product_info INSERT
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
                    ship_plan_date
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
                    %s
                )
                RETURNING id
            ''', (
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
            ))
            product_id = cursor.fetchone()[0]

            # 2) public.qr_registry INSERT (QR 매핑)
            cursor.execute('''
                INSERT INTO public.qr_registry (qr_doc_id, serial_number, status)
                VALUES (%s, %s, 'active')
                RETURNING id
            ''', (qr_doc_id, sn))
            qr_id = cursor.fetchone()[0]

            results.append({
                'id': product_id,
                'qr_id': qr_id,
                'serial_number': sn,
                'qr_doc_id': qr_doc_id,
                'model_name': item['model_name'],
                'product_code': item.get('product_code', ''),
                'status': 'inserted',
            })
            print(f"  [Load] {sn} → {qr_doc_id} (plan.product_info:{product_id}, qr_registry:{qr_id})")

        except Exception as e:
            conn.rollback()
            print(f"  [Error] {sn}: {e}")
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor()
            cursor.execute("SET timezone = 'Asia/Seoul'")

    conn.commit()
    conn.close()
    print(f"[Load] PostgreSQL 적재 완료: {len(results)}건")
    return results


if __name__ == '__main__':
    from step1_extract import extract_from_teams_excel
    data = extract_from_teams_excel()
    results = load_to_postgres(data)
    print(f"\n적재 결과:")
    for r in results:
        print(f"  {r['serial_number']} → {r['qr_doc_id']} ({r['model_name']}) [{r['status']}]")
