#!/usr/bin/env python3
"""
ETL vs SCR-Schedule 결과 비교 진단 스크립트

같은 Excel 파일을 두 가지 방식으로 추출하여 건수 차이 원인 분석:
1) AXIS-CORE ETL 방식: 컬럼명 매칭 (_find_column)
2) SCR-Schedule 방식: 인덱스 기반 (row.iloc[col_idx - 1])

사용법:
  python compare_etl_vs_scr.py
"""

import os
import io
import re
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
load_dotenv()

from step1_extract import (
    _download_scr_excel, _find_column, _format_date_value, _format_text_value,
    parse_sn, COLUMN_MAPPING, COLUMN_ALIASES, EXTRA_COLUMNS, DATE_FIELDS,
    HEADER_ROW
)


# ── SCR-Schedule config.py 기준 인덱스 (1-based → 0-based로 사용) ──
SCR_INDEX_MAP = {
    "serial_number":    31,   # S/N — AF열
    "model_name":       6,    # Model — F열
    "order_no":         2,    # 판매오더 — B열
    "customer":         4,    # 고객사 — D열
    "product_code":     7,    # 제품번호 — G열
    "line":             5,    # 라인 — E열
    "mech_partner":     39,   # 기구외주
    "elec_partner":     40,   # 전장외주
    "mech_start":       46,   # 기구계획시작일 — AT열
    "mech_end":         48,   # 기구계획종료일
    "elec_start":       51,   # 전장계획시작일
    "elec_end":         52,   # 전장계획종료일
    "pressure_test":    58,   # 가압계획시작일
    "self_inspect":     62,   # 가동검사계획시작일
    "process_inspect":  66,   # TEST계획시작일
    "finishing_start":  72,   # 마무리계획시작일
    "planned_finish":   21,   # 출고계획일 — U열
}


def extract_etl_style(df, sn_col):
    """AXIS-CORE ETL 방식: 컬럼명 매칭"""
    # 컬럼 매핑
    col_map = {}
    col_map_failures = []
    for kor_key, eng_key in COLUMN_MAPPING.items():
        candidates = [kor_key] + COLUMN_ALIASES.get(kor_key, [])
        matched = _find_column(df, candidates)
        if matched:
            col_map[eng_key] = matched
        else:
            col_map_failures.append((kor_key, eng_key, candidates))

    # 추출
    converted = []
    skip_reasons = {"empty_sn": 0, "parse_sn_fail": 0, "key_error": 0}

    for idx, row in df.iterrows():
        raw_sn = str(row[sn_col]).strip()
        if not raw_sn:
            skip_reasons["empty_sn"] += 1
            continue

        split_sns = parse_sn(raw_sn)
        if not split_sns:
            skip_reasons["parse_sn_fail"] += 1
            continue

        base_item = {}
        has_error = False
        for eng_key, df_col in col_map.items():
            if eng_key == "serial_number":
                continue
            val = row[df_col]
            if eng_key in DATE_FIELDS:
                base_item[eng_key] = _format_date_value(val)
            else:
                base_item[eng_key] = _format_text_value(val)

        # model_name 누락 체크 (step2에서 KeyError 발생하는 케이스)
        if "model_name" not in base_item:
            skip_reasons["key_error"] += 1
            continue

        for sn in split_sns:
            item = dict(base_item)
            item["serial_number"] = sn
            converted.append(item)

    return converted, col_map, col_map_failures, skip_reasons


def extract_scr_style(df):
    """SCR-Schedule 방식: 인덱스 기반"""
    converted = []
    skip_reasons = {"empty_sn": 0, "parse_sn_fail": 0, "index_error": 0}

    sn_idx = SCR_INDEX_MAP["serial_number"] - 1  # 0-based

    for idx, row in df.iterrows():
        # S/N 추출 (인덱스)
        try:
            raw_sn_val = row.iloc[sn_idx] if sn_idx < len(row) else ""
        except (IndexError, KeyError):
            skip_reasons["index_error"] += 1
            continue

        if pd.isna(raw_sn_val) or str(raw_sn_val).strip() == "":
            skip_reasons["empty_sn"] += 1
            continue

        raw_sn = str(raw_sn_val).strip()
        split_sns = parse_sn(raw_sn)
        if not split_sns:
            skip_reasons["parse_sn_fail"] += 1
            continue

        # 나머지 필드 (인덱스)
        base_item = {}
        for eng_key, col_idx_1based in SCR_INDEX_MAP.items():
            if eng_key == "serial_number":
                continue
            idx_0 = col_idx_1based - 1
            try:
                val = row.iloc[idx_0] if idx_0 < len(row) else ""
            except (IndexError, KeyError):
                val = ""

            if pd.isna(val):
                val = ""

            if eng_key in DATE_FIELDS:
                base_item[eng_key] = _format_date_value(val) if val != "" else ""
            else:
                base_item[eng_key] = _format_text_value(val) if val != "" else ""

        for sn in split_sns:
            item = dict(base_item)
            item["serial_number"] = sn
            converted.append(item)

    return converted, skip_reasons


def apply_half_year_filter(data, date_field="mech_start"):
    """반기 필터 적용 (ETL cron 기본 동작)"""
    today = datetime.now()
    if today.month <= 6:
        start = f"{today.year - 1}-11-01"
    else:
        start = f"{today.year}-05-01"

    from calendar import monthrange
    next_month = today.month + 1
    next_year = today.year
    if next_month > 12:
        next_month = 1
        next_year += 1
    last_day = monthrange(next_year, next_month)[1]
    end = f"{next_year}-{next_month:02d}-{last_day:02d}"

    filtered = [
        item for item in data
        if item.get(date_field, '') and start <= item[date_field][:10] <= end
    ]
    skipped_empty = sum(1 for item in data if not item.get(date_field, ''))
    skipped_range = len(data) - len(filtered) - skipped_empty

    return filtered, start, end, skipped_empty, skipped_range


def apply_scr_month_filter(data, range_months=2):
    """SCR-Schedule 월 기반 필터"""
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)

    allowed = set()
    for delta in range(-range_months, range_months + 1):
        m = now.month + delta
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        allowed.add((y, m))

    filtered = []
    skipped_empty = 0
    skipped_range = 0

    for item in data:
        mech = item.get("mech_start", "")
        if not mech or "-" not in mech:
            skipped_empty += 1
            continue
        try:
            parts = mech.split("-")
            year, month = int(parts[0]), int(parts[1])
            if (year, month) in allowed:
                filtered.append(item)
            else:
                skipped_range += 1
        except (ValueError, IndexError):
            skipped_empty += 1

    return filtered, allowed, skipped_empty, skipped_range


def main():
    print("=" * 70)
    print("  ETL vs SCR-Schedule 비교 진단")
    print(f"  실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1) Excel 다운로드
    print("\n[1] Excel 다운로드")
    print("-" * 50)
    file_bytes = _download_scr_excel()

    sheet_name = os.environ.get("SOURCE_SHEET_NAME", "SCR 생산현황")
    df = pd.read_excel(file_bytes, sheet_name=sheet_name, header=HEADER_ROW, engine="openpyxl")
    total_rows = len(df)
    total_cols = len(df.columns)
    print(f"  DataFrame: {total_rows}행 x {total_cols}열")

    # S/N 컬럼 찾기 (ETL 방식)
    sn_col = _find_column(df, ["S/N", "SN", "시리얼"])
    print(f"  S/N 컬럼 (ETL _find_column): '{sn_col}'")

    # S/N 인덱스 확인 (SCR 방식)
    sn_idx = SCR_INDEX_MAP["serial_number"] - 1
    sn_col_by_idx = df.columns[sn_idx] if sn_idx < total_cols else "⚠️ 범위 초과"
    print(f"  S/N 컬럼 (SCR index {SCR_INDEX_MAP['serial_number']}): '{sn_col_by_idx}'")

    # 빈 S/N 제거 전/후
    df_filtered = df[df[sn_col].notna() & (df[sn_col].astype(str).str.strip() != "")]
    print(f"  S/N 있는 행: {len(df_filtered)}행 (제거: {total_rows - len(df_filtered)}행)")

    # 2) ETL 방식 추출
    print(f"\n[2] ETL 방식 추출 (컬럼명 매칭)")
    print("-" * 50)
    etl_data, col_map, col_failures, etl_skip = extract_etl_style(df_filtered, sn_col)
    print(f"  컬럼 매핑 성공: {len(col_map)}개")
    if col_failures:
        for kor, eng, cands in col_failures:
            print(f"  ⚠️ 매핑 실패: {kor} ({eng}) — 후보: {cands}")
    print(f"  추출 결과: {len(etl_data)}건")
    print(f"  스킵: S/N빈행={etl_skip['empty_sn']}, parse실패={etl_skip['parse_sn_fail']}, KeyError={etl_skip['key_error']}")

    # 3) SCR 방식 추출 (빈 S/N 제거 전 원본 df 사용 — SCR은 자체 S/N 체크)
    print(f"\n[3] SCR-Schedule 방식 추출 (인덱스 기반)")
    print("-" * 50)
    scr_data, scr_skip = extract_scr_style(df)
    print(f"  추출 결과: {len(scr_data)}건")
    print(f"  스킵: S/N빈행={scr_skip['empty_sn']}, parse실패={scr_skip['parse_sn_fail']}, index에러={scr_skip['index_error']}")

    # 4) 필터 적용 비교
    print(f"\n[4] 필터 적용 비교")
    print("-" * 50)

    # ETL 반기 필터
    etl_filtered, h_start, h_end, h_empty, h_range = apply_half_year_filter(etl_data)
    print(f"  ETL 반기필터 ({h_start} ~ {h_end}):")
    print(f"    통과: {len(etl_filtered)}건, 탈락: mech_start빈값={h_empty}, 범위밖={h_range}")

    # SCR 월 필터
    scr_filtered, allowed, s_empty, s_range = apply_scr_month_filter(scr_data)
    months_str = ", ".join(f"{y}-{m:02d}" for y, m in sorted(allowed))
    print(f"  SCR 월필터 ({months_str}):")
    print(f"    통과: {len(scr_filtered)}건, 탈락: mech_start빈값={s_empty}, 범위밖={s_range}")

    # 5) S/N 비교
    print(f"\n[5] S/N 비교 (필터 적용 후)")
    print("-" * 50)
    etl_sns = set(item["serial_number"] for item in etl_filtered)
    scr_sns = set(item["serial_number"] for item in scr_filtered)

    common = etl_sns & scr_sns
    only_etl = etl_sns - scr_sns
    only_scr = scr_sns - etl_sns

    print(f"  공통: {len(common)}건")
    print(f"  ETL에만 있음: {len(only_etl)}건")
    print(f"  SCR에만 있음: {len(only_scr)}건")

    if only_scr:
        print(f"\n  [SCR에만 있는 S/N — ETL 누락 후보] (최대 20건)")
        for sn in sorted(only_scr)[:20]:
            scr_item = next(i for i in scr_filtered if i["serial_number"] == sn)
            mech = scr_item.get("mech_start", "")
            model = scr_item.get("model_name", "")
            print(f"    {sn:15s} | model={model:12s} | mech_start={mech}")

    # 6) 전체 요약
    print(f"\n{'=' * 70}")
    print(f"  요약")
    print(f"{'=' * 70}")
    print(f"  Excel 원본 행:          {total_rows}")
    print(f"  S/N 있는 행:            {len(df_filtered)}")
    print(f"  ─────────────────────────────────────")
    print(f"  ETL 추출 (컬럼명):      {len(etl_data)}")
    print(f"  SCR 추출 (인덱스):      {len(scr_data)}")
    print(f"  차이:                   {len(scr_data) - len(etl_data)}건 (SCR이 더 많음)")
    print(f"  ─────────────────────────────────────")
    print(f"  ETL 반기필터 후:        {len(etl_filtered)}")
    print(f"  SCR 월필터 후:          {len(scr_filtered)}")
    print(f"  차이:                   {len(scr_filtered) - len(etl_filtered)}건")
    print(f"  ─────────────────────────────────────")
    print(f"  DB 현재:                39건 (수동 확인)")

    # 7) ETL 필터 없이 (--all) 추출
    print(f"\n[참고] ETL --all (필터 없이): {len(etl_data)}건")
    print(f"[참고] SCR 필터 없이:         {len(scr_data)}건")

    if len(scr_data) > len(etl_data):
        diff = len(scr_data) - len(etl_data)
        print(f"\n⚠️  필터 이전 단계에서 이미 {diff}건 차이 발생 — 컬럼 매칭/파싱 차이 확인 필요")


if __name__ == "__main__":
    main()
