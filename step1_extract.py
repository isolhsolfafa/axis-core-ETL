#!/usr/bin/env python3
"""
Step 1: Extract - Teams Excel (SCR 생산현황)에서 metadata 추출
Microsoft Graph API로 OneDrive에서 Excel 다운로드 + pandas 파싱

의존성:
  - msal (MSAL Client Credentials Flow)
  - requests (Graph API HTTP 호출)
  - pandas + openpyxl (Excel 파싱)

환경변수:
  TEAMS_TENANT_ID      — Azure AD Tenant ID
  TEAMS_CLIENT_ID      — Azure AD App Client ID
  TEAMS_CLIENT_SECRET  — Azure AD App Client Secret
  SOURCE_USER_EMAIL    — OneDrive 파일 소유자 이메일
  SOURCE_DOC_ID        — OneDrive 파일 ID (Primary)
  SOURCE_SHEET_NAME    — Excel 시트명 (default: "SCR 생산현황")
  FALLBACK_BASE_PATH   — OneDrive 폴더 탐색 경로 (Fallback)
"""

import os
import io
import re
import urllib.parse

import msal
import requests
import pandas as pd


# ── Graph API 설정 ──────────────────────────────────────────

DEFAULT_USER_EMAIL = "smlee@gst365.onmicrosoft.com"
DEFAULT_SHEET_NAME = "SCR 생산현황"
DEFAULT_FALLBACK_PATH = "생산관리팀/1.정기업무/1.일정관리/2026년"
HEADER_ROW = 2  # 0-indexed (Excel 3번째 행이 헤더)


# ── 컬럼 매핑 ───────────────────────────────────────────────

# SCR Excel 한글 컬럼 → ETL 영문 필드
COLUMN_MAPPING = {
    "S/N": "serial_number",
    "모델": "model_name",
    "오더번호": "order_no",
    "고객사": "customer",
    "제품번호": "product_code",
    "라인": "line",
    "기구업체": "mech_partner",
    "전장업체": "elec_partner",
    "기구시작": "mech_start",
    "기구종료": "mech_end",
    "전장시작": "elec_start",
    "전장종료": "elec_end",
    "가압시작": "pressure_test",
    "자주검사": "self_inspect",
    "공정시작": "process_inspect",
    "마무리시작": "finishing_start",
    "출하": "planned_finish",
}

# 추가 컬럼: 이름 기반 탐색 + 고정 인덱스 fallback
EXTRA_COLUMNS = {
    "module_outsourcing": {"name": "모듈외주",       "index": 40},
    "semi_product_start": {"name": "반제품시작",     "index": 41},
    "finishing_plan_end": {"name": "마무리계획종료일", "index": 72},
}


# ── Graph API 인증 ──────────────────────────────────────────

def get_graph_token():
    """MSAL Client Credentials Flow로 access_token 획득"""
    tenant_id = os.environ["TEAMS_TENANT_ID"]
    client_id = os.environ["TEAMS_CLIENT_ID"]
    client_secret = os.environ["TEAMS_CLIENT_SECRET"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise Exception(f"Token 획득 실패: {result.get('error_description')}")
    return result["access_token"]


def _get_graph_headers():
    token = get_graph_token()
    return {"Authorization": f"Bearer {token}"}


# ── Excel 다운로드 (A: 파일 ID / B: 폴더 탐색) ─────────────

def _download_by_doc_id():
    """방법 A: OneDrive 파일 ID 직접 접근 (Primary)"""
    source_doc_id = os.environ.get("SOURCE_DOC_ID")
    if not source_doc_id:
        return None

    user_email = os.environ.get("SOURCE_USER_EMAIL", DEFAULT_USER_EMAIL)
    headers = _get_graph_headers()

    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{source_doc_id}"
    resp = requests.get(url, headers=headers)

    if resp.status_code == 404:
        print(f"  [Warning] SOURCE_DOC_ID ({source_doc_id}) 파일 없음 — fallback 전환")
        return None
    resp.raise_for_status()

    download_url = resp.json()["@microsoft.graph.downloadUrl"]
    file_resp = requests.get(download_url)
    file_resp.raise_for_status()
    return io.BytesIO(file_resp.content)


def _download_by_folder_search():
    """방법 B: OneDrive 개인 드라이브 폴더 탐색 (Fallback)"""
    user_email = os.environ.get("SOURCE_USER_EMAIL", DEFAULT_USER_EMAIL)
    base_path = os.environ.get("FALLBACK_BASE_PATH", DEFAULT_FALLBACK_PATH)
    headers = _get_graph_headers()

    # 폴더 목록 조회
    encoded_path = urllib.parse.quote(base_path)
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{encoded_path}:/children"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"폴더 조회 실패: {resp.status_code} - {resp.text}")

    items = resp.json().get("value", [])

    # W{NN} 폴더 중 최신 주차 찾기
    week_folders = []
    for item in items:
        if item.get("folder"):
            m = re.match(r"W(\d+)", item["name"])
            if m:
                week_folders.append((int(m.group(1)), item))

    if not week_folders:
        raise Exception(f"주차 폴더를 찾을 수 없습니다: {base_path}")

    latest = sorted(week_folders, key=lambda x: x[0], reverse=True)[0][1]
    print(f"  [Fallback] 최신 주차 폴더: {latest['name']}")

    # 폴더 안에서 SCR 파일 찾기
    folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{latest['id']}/children"
    folder_resp = requests.get(folder_url, headers=headers)
    files = folder_resp.json().get("value", [])

    scr_file = None
    for f in files:
        if "SCR" in f["name"] and f["name"].endswith(".xlsx"):
            scr_file = f
            break

    if not scr_file:
        raise Exception(f"SCR 파일 없음: {latest['name']}")

    download_url = scr_file["@microsoft.graph.downloadUrl"]
    file_resp = requests.get(download_url)
    file_resp.raise_for_status()
    print(f"  [Fallback] 파일: {scr_file['name']}")
    return io.BytesIO(file_resp.content)


def _download_scr_excel():
    """SCR Excel 다운로드 (A → B fallback)"""
    print("  [Download] 방법 A: OneDrive 파일 ID로 접근...")
    result = _download_by_doc_id()
    if result is not None:
        print("  [Download] 방법 A 성공")
        return result

    print("  [Download] 방법 B: OneDrive 폴더 탐색 fallback...")
    result = _download_by_folder_search()
    print("  [Download] 방법 B 성공")
    return result


# ── S/N 파싱 (SCR-Schedule sn_parser 대체) ──────────────────

def parse_sn(raw_sn: str) -> list:
    """
    S/N 문자열을 개별 S/N 리스트로 분리
    예:
      "GBWS-6408"              → ["GBWS-6408"]
      "GBWS-6408~6410"         → ["GBWS-6408", "GBWS-6409", "GBWS-6410"]
      "GBWS-6408, GBWS-6409"   → ["GBWS-6408", "GBWS-6409"]
      "DBW-3715,3716"          → ["DBW-3715", "DBW-3716"]  (접두사 자동 보완)
      "GPWS-0340~0342"         → ["GPWS-0340", "GPWS-0341", "GPWS-0342"]  (선행 0 보존)
    """
    raw_sn = str(raw_sn).strip()
    if not raw_sn:
        return []

    # 쉼표 분리 (접두사 없는 항목에 첫 번째 항목의 접두사 적용)
    if "," in raw_sn:
        items = [s.strip() for s in raw_sn.split(",") if s.strip()]
        if not items:
            return []

        # 첫 번째 항목에서 접두사 추출
        first_match = re.match(r"([A-Za-z]+-)", items[0])
        prefix = first_match.group(1) if first_match else ""

        # 숫자 자릿수 (선행 0 보존)
        num_match = re.search(r"(\d+)$", items[0])
        num_width = len(num_match.group(1)) if num_match else 0

        result = [items[0]]
        for item in items[1:]:
            if re.match(r"[A-Za-z]", item):
                # 이미 접두사가 있는 경우 그대로
                result.append(item)
            elif prefix and item.isdigit():
                # 숫자만 있으면 접두사 + 자릿수 맞춤
                result.append(f"{prefix}{item.zfill(num_width)}")
            else:
                result.append(item)
        return result

    # ~ 범위 분리 (예: GBWS-6408~6410, GPWS-0340~0342)
    if "~" in raw_sn:
        parts = raw_sn.split("~")
        if len(parts) == 2:
            prefix_match = re.match(r"([A-Za-z]+-?)(\d+)", parts[0].strip())
            if prefix_match:
                prefix = prefix_match.group(1)
                num_str = prefix_match.group(2)
                num_width = len(num_str)  # 선행 0 보존용 자릿수
                start_num = int(num_str)
                end_match = re.search(r"(\d+)", parts[1].strip())
                if end_match:
                    end_num = int(end_match.group(1))
                    return [f"{prefix}{str(n).zfill(num_width)}" for n in range(start_num, end_num + 1)]

    return [raw_sn]


# ── Excel 파싱 ──────────────────────────────────────────────

def _find_column(df, candidates):
    """DataFrame에서 후보 컬럼명 중 존재하는 것 반환 (공백/줄바꿈 무시)"""
    for col in df.columns:
        col_normalized = re.sub(r"\s+", "", str(col))
        for c in candidates:
            c_normalized = re.sub(r"\s+", "", c)
            if c_normalized in col_normalized:
                return col
    return None


def _find_extra_column(df, col_name: str, fallback_index: int):
    """
    컬럼명으로 먼저 탐색, 없으면 고정 인덱스 fallback

    Args:
        df: DataFrame (header=2 기준)
        col_name: 찾을 한글 컬럼명
        fallback_index: 매칭 실패 시 0-indexed 열 번호
    Returns:
        pd.Series or None
    """
    # 정확한 컬럼명 매칭
    for col in df.columns:
        if col_name in str(col).replace(" ", ""):
            return df[col]

    # 부분 매칭 (공백/줄바꿈 제거)
    normalized_target = re.sub(r"\s+", "", col_name)
    for col in df.columns:
        normalized_col = re.sub(r"\s+", "", str(col))
        if normalized_target in normalized_col:
            return df[col]

    # fallback: 고정 인덱스
    if fallback_index < len(df.columns):
        print(f"  [Warning] '{col_name}' 컬럼명 없음 — fallback index {fallback_index} 사용")
        return df.iloc[:, fallback_index]

    return None


# 날짜 필드 목록 (이 필드만 date 포맷 적용)
DATE_FIELDS = {
    "mech_start", "mech_end", "elec_start", "elec_end",
    "pressure_test", "self_inspect", "process_inspect",
    "finishing_start", "planned_finish",
}


def _format_date_value(val):
    """날짜 값을 YYYY-MM-DD 문자열로 변환"""
    if pd.isna(val):
        return ''
    if hasattr(val, 'strftime'):
        return val.strftime('%Y-%m-%d')
    # 문자열 날짜도 처리 (예: "2026-03-15 00:00:00")
    s = str(val).strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    return s


def _format_text_value(val):
    """텍스트 값 변환 (모델명, 업체명 등 비날짜 필드)"""
    if pd.isna(val):
        return ''
    # Excel에서 숫자로 저장된 경우 소수점 제거 (2100.0 → "2100")
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val).strip()


def _parse_excel(file_bytes: io.BytesIO):
    """SCR 생산현황 Excel 파싱 → DataFrame"""
    sheet_name = os.environ.get("SOURCE_SHEET_NAME", DEFAULT_SHEET_NAME)

    df = pd.read_excel(
        file_bytes,
        sheet_name=sheet_name,
        header=HEADER_ROW,
        engine="openpyxl",
    )

    # S/N 컬럼 찾기
    sn_col = _find_column(df, ["S/N", "SN", "시리얼"])
    if sn_col is None:
        raise Exception("S/N 컬럼을 찾을 수 없습니다")

    # 빈 S/N 행 제거
    df = df[df[sn_col].notna() & (df[sn_col].astype(str).str.strip() != "")]

    return df, sn_col


# ── 메인 추출 함수 ──────────────────────────────────────────

def extract_from_teams_excel():
    """
    Graph API로 Teams Excel (SCR 생산현황) 다운로드 + 파싱 → metadata list 반환
    SCR-Schedule 의존성 없이 독립 실행 가능
    """
    # Excel 다운로드
    file_bytes = _download_scr_excel()

    # Excel 파싱
    df, sn_col = _parse_excel(file_bytes)

    # 추가 컬럼 Series 준비
    extra_series = {}
    for field_key, config in EXTRA_COLUMNS.items():
        series = _find_extra_column(df, config["name"], config["index"])
        extra_series[field_key] = series

    # 컬럼명 → DataFrame 컬럼 매핑 (한글 → 영문)
    col_map = {}
    for kor_key, eng_key in COLUMN_MAPPING.items():
        matched_col = _find_column(df, [kor_key])
        if matched_col is not None:
            col_map[eng_key] = matched_col

    # 행별 변환 + S/N split
    converted = []
    for idx, row in df.iterrows():
        # 원본 S/N (split 전)
        raw_sn = str(row[sn_col]).strip()
        if not raw_sn:
            continue

        # S/N split
        split_sns = parse_sn(raw_sn)
        if not split_sns:
            continue

        # 기본 필드 추출 (S/N 제외)
        base_item = {}
        for eng_key, df_col in col_map.items():
            if eng_key == "serial_number":
                continue
            val = row[df_col]
            if eng_key in DATE_FIELDS:
                base_item[eng_key] = _format_date_value(val)
            else:
                base_item[eng_key] = _format_text_value(val)

        # 추가 컬럼 추출 (날짜/텍스트 분기)
        EXTRA_DATE_FIELDS = {"semi_product_start", "finishing_plan_end"}
        for field_key, series in extra_series.items():
            if series is not None:
                val = series.iloc[df.index.get_loc(idx)]
                if field_key in EXTRA_DATE_FIELDS:
                    base_item[field_key] = _format_date_value(val)
                else:
                    base_item[field_key] = _format_text_value(val)
            else:
                base_item[field_key] = ''

        # split된 각 S/N에 대해 개별 item 생성
        for sn in split_sns:
            item = dict(base_item)
            item['serial_number'] = sn
            item['quantity'] = '1'
            item['title_number'] = _generate_title_number(
                item.get('mech_start', ''),
                item.get('order_no', ''),
                sn
            )
            converted.append(item)

    print(f"[Extract] Teams Excel 데이터 {len(converted)}건 추출 완료 (Graph API)")
    return converted


# ── 유틸 함수 ───────────────────────────────────────────────

def _generate_title_number(mech_start, order_no, serial_number):
    """
    title_number 생성: YYMMDD/판매오더/SN번호
    예: 251201/6119/6408  (GBWS-6408 → 6408)
    """
    date_part = ''
    if mech_start and len(mech_start) >= 10:
        date_part = mech_start[2:4] + mech_start[5:7] + mech_start[8:10]

    sn_number = serial_number.split('-')[-1] if serial_number and '-' in serial_number else serial_number

    parts = [p for p in [date_part, order_no, sn_number] if p]
    return '/'.join(parts) if parts else ''


def filter_by_date(metadata_list, date_field, target_date):
    """날짜 기준 필터링 (단일 날짜)"""
    filtered = [
        item for item in metadata_list
        if item.get(date_field, '').startswith(target_date)
    ]
    print(f"[Filter] {date_field} = {target_date}: {len(filtered)}건")
    return filtered


def filter_by_date_range(metadata_list, date_field, start_date, end_date):
    """날짜 범위 필터링"""
    filtered = [
        item for item in metadata_list
        if item.get(date_field, '') and start_date <= item[date_field][:10] <= end_date
    ]
    print(f"[Filter] {date_field} {start_date}~{end_date}: {len(filtered)}건")
    return filtered


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()

    data = extract_from_teams_excel()
    print(f"\n전체: {len(data)}건")

    # 샘플 출력
    for item in data[:5]:
        print(f"  {item['serial_number']:15s} | {item.get('model_name',''):12s} | "
              f"{item.get('product_code',''):10s} | {item.get('line',''):5s} | "
              f"{item.get('module_outsourcing',''):5s} | {item.get('title_number','')}")
