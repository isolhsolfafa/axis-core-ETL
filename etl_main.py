#!/usr/bin/env python3
"""
ETL 파이프라인 통합 실행
Teams Excel (실제 데이터) → Staging DB 적재 + doc_id 생성 → QR 이미지 발행

사용법:
  python etl_main.py --date 2025-12-01                         # 기구시작일 기준 특정 날짜
  python etl_main.py --start 2025-12-01 --end 2025-12-31      # 범위
  python etl_main.py --all                                      # 전체 (필터 없이)
환경변수:
  DATABASE_URL       — PostgreSQL 접속 URL (필수)
  TEAMS_TENANT_ID    — Azure AD Tenant ID (step1 Graph API)
  TEAMS_CLIENT_ID    — Azure AD App Client ID
  TEAMS_CLIENT_SECRET — Azure AD App Client Secret
  SOURCE_DOC_ID      — OneDrive 파일 ID (Primary)
  SOURCE_USER_EMAIL  — OneDrive 파일 소유자 이메일
"""

import os
import json
import argparse
from datetime import datetime

from step1_extract import extract_from_teams_excel, filter_by_date, filter_by_date_range
from step2_load import load_to_postgres


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_etl(date=None, start=None, end=None, date_field='mech_start'):
    """
    전체 ETL 파이프라인 실행 (PostgreSQL)
    """
    print("=" * 60)
    print("  GST Factory ETL Pipeline")
    print(f"  실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  필터: {date_field} = {date or f'{start}~{end}' or '전체'}")
    print("=" * 60)

    # Step 1: Extract (실제 Teams Excel)
    print("\n[Step 1] Extract - Teams Excel 실제 데이터 로드")
    print("-" * 40)
    all_data = extract_from_teams_excel()

    # 필터 적용
    if date:
        metadata_list = filter_by_date(all_data, date_field, date)
    elif start and end:
        metadata_list = filter_by_date_range(all_data, date_field, start, end)
    else:
        metadata_list = all_data

    if not metadata_list:
        print("[Warning] 필터 결과 데이터가 없습니다.")
        return None

    # Step 2: Load (Staging DB PostgreSQL)
    print(f"\n[Step 2] Load - Staging DB 적재 + doc_id 생성")
    print("-" * 40)
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("[Error] DATABASE_URL 환경변수가 설정되지 않았습니다.")
        return None
    load_results = load_to_postgres(metadata_list, db_url=db_url)

    if not load_results:
        print("[Error] DB 적재 실패")
        return None

    # 결과 요약
    # (QR 이미지는 현장 라벨기에서 자동 생성 — ETL에서 미생성)
    inserted = [r for r in load_results if r.get('status') == 'inserted']
    skipped = [r for r in load_results if r.get('status') == 'skipped']

    print("\n" + "=" * 60)
    print("  ETL 완료")
    print("=" * 60)
    print(f"  전체 추출: {len(all_data)}건")
    print(f"  필터 적용: {len(metadata_list)}건")
    print(f"  신규 적재: {len(inserted)}건")
    print(f"  중복 스킵: {len(skipped)}건")

    # 결과 JSON 저장
    result_summary = {
        'timestamp': datetime.now().isoformat(),
        'filter': {'field': date_field, 'date': date, 'start': start, 'end': end},
        'total_extracted': len(all_data),
        'filtered': len(metadata_list),
        'inserted': len(inserted),
        'skipped': len(skipped),
        'qr_generated': 0,  # 라벨기 자동 생성 (ETL 미생성)
        'items': load_results,
    }

    summary_path = os.path.join(SCRIPT_DIR, 'output', 'etl_result.json')
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(result_summary, f, ensure_ascii=False, indent=2)

    return result_summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='GST Factory ETL Pipeline')
    parser.add_argument('--date', type=str, help='특정 날짜 (YYYY-MM-DD)')
    parser.add_argument('--start', type=str, help='시작 날짜')
    parser.add_argument('--end', type=str, help='종료 날짜')
    parser.add_argument('--field', type=str, default='mech_start',
                        help='필터 기준 필드 (default: mech_start)')
    parser.add_argument('--all', action='store_true', help='전체 (필터 없이)')

    args = parser.parse_args()

    if args.all:
        run_etl()
    else:
        run_etl(date=args.date, start=args.start, end=args.end, date_field=args.field)
