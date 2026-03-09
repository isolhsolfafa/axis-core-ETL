#!/usr/bin/env python3
"""
ETL 파이프라인 통합 실행
Teams Excel (실제 데이터) → Staging DB 적재 + doc_id 생성 → QR 이미지 발행

사용법:
  python etl_main.py --date 2026-01-15                         # 기구시작일 기준 특정 날짜
  python etl_main.py --start 2026-01-01 --end 2026-01-31      # 범위
  python etl_main.py --all                                      # 전체 (필터 없이)
  python etl_main.py                                            # 반기 자동 필터 (cron 기본)
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

from dotenv import load_dotenv
load_dotenv()

from step1_extract import extract_from_teams_excel, filter_by_date, filter_by_date_range
from step2_load import load_to_postgres


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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

    # Step 2: Load (Staging DB PostgreSQL — UPSERT)
    print(f"\n[Step 2] Load - Staging DB UPSERT 적재")
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
    inserted = [r for r in load_results if r.get('status') == 'inserted']
    updated = [r for r in load_results if r.get('status') == 'updated']
    unchanged = [r for r in load_results if r.get('status') == 'unchanged']

    print("\n" + "=" * 60)
    print("  ETL 완료")
    print("=" * 60)
    print(f"  전체 추출: {len(all_data)}건")
    print(f"  필터 적용: {len(metadata_list)}건")
    print(f"  신규 적재: {len(inserted)}건")
    print(f"  변경 반영: {len(updated)}건")
    print(f"  동일 스킵: {len(unchanged)}건")

    # 결과 JSON 저장
    result_summary = {
        'timestamp': datetime.now().isoformat(),
        'filter': {'field': date_field, 'date': date, 'start': start, 'end': end},
        'total_extracted': len(all_data),
        'filtered': len(metadata_list),
        'inserted': len(inserted),
        'updated': len(updated),
        'unchanged': len(unchanged),
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
        # --all: 필터 없이 전체
        run_etl()
    elif args.date or (args.start and args.end):
        # 명시적 날짜 지정
        run_etl(date=args.date, start=args.start, end=args.end, date_field=args.field)
    else:
        # 옵션 없음 (cron 기본) → 반기 자동 필터
        half_start, half_end = get_half_year_range()
        print(f"📅 반기 자동 필터: {half_start} ~ {half_end}")
        run_etl(start=half_start, end=half_end, date_field=args.field)
