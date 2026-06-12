# ETL 운영 기록 — 6/11 취소 사건 + Node 24 전환 대응 (2026-06-11)

> 작성: Claude (Fable 5) / 검토 근거: `etl-metadata-sync.yml` 직접 확인 + GitHub 공식 공지(2025-09-19, 2026-05-19 갱신) 직접 열람
> 성격: 사건 기록 + 조치 계획. 완료 시 체크박스 갱신 후 BACKLOG/handoff에 1줄 반영 권장
> **갱신 (2026-06-12)**:
> - GitHub Actions 실제 런타임 경고 확인 → ① 30분 timeout 확정 (가설→사실), ② `upload-artifact@v5`는 **Node 20 기반** (메이저 버전 = Node 버전 매핑 추정이 빗나간 사례). CORE-ETL도 6/16 영향 대상.
> - `upload-artifact` 최신 릴리스 v7.0.1 = Node 24 확인 → **`@v5` → `@v7` 핀 업** 으로 해결.
> - 알림 채널: Teams 미사용 결정 → **SMTP 메일 (`dkkim1@gst-in.com`)** 으로 확정.

---

## 1. 사건 ① — 정기 동기화 run 취소 (2026-06-11)

### 증상 (실제 Actions 로그)

```
Run if [ "schedule" = "schedule" ]; then
⏰ 정기 자동 동기화 (반기 자동 필터)
/opt/hostedtoolcache/Python/3.10.20/x64/lib/python3.10/site-packages/openpyxl/worksheet/_reader.py:329:
UserWarning: Data Validation extension is not supported and will be removed  ← 무해한 잡음
Error: The operation was canceled.
```

**Annotations (확정 단서)**:
- `The job has exceeded the maximum execution time of 30m0s` → **timeout 30분 초과 = 취소 원인 확정**
- `Node.js 20 actions are deprecated. ... actions/upload-artifact@v5` → 별개의 deprecation 경고 (이 사건의 원인은 아님)

### 분석

- **취소 원인 = `timeout-minutes: 30` 초과로 확정** (Annotation에 "exceeded the maximum execution time of 30m0s" 명시)
- openpyxl 경고가 떴다는 것 = Excel **다운로드까지 성공**, 파싱/적재 단계에서 멈춤
- **30분 hang을 일으킨 underlying 원인 후보 (사후 확정 어려움 — step별 로그 부족)**:
  - ① **DB 락 충돌** — 동시간대 수동 SQL 클라이언트가 idle in transaction 상태면 ETL UPSERT가 락 대기 → lock_timeout 미설정으로 "실패" 대신 **무한 대기** → 30분 채움
  - ② **schedule run 겹침** — schedule이 하루 4회(07/10/13/16 KST). 직전 run이 hang 상태로 30분 가까이 걸렸다면 다음 cron과 겹치며 한쪽이 취소될 수 있음 (`concurrency` 미설정 상태)
  - ③ **외부 호출 hang** — Graph API 또는 DB 호출 도중 무응답. 현재 step별 timestamped 로그가 없어 어느 구간에서 멈췄는지 사후 추적 불가
- ⚠️ 이 사건은 리스크 검토(6-10) P0 ②번 "ETL 실패가 침묵한다"의 실물 사례 — 알림이 없어 수동 확인으로만 발견됨

### 복구 절차 (재발 시 동일)

```sql
-- ① 락 잡은 세션 확인
SELECT pid, state, query_start, left(query,60)
FROM pg_stat_activity
WHERE state = 'idle in transaction';
-- ② 해당 세션 커밋/롤백 또는 클라이언트 종료
--    (필요 시: SELECT pg_terminate_backend(<pid>); — 본인 세션 확인 후)
```

→ ③ Actions에서 **Run workflow (mode=auto)** 수동 재실행. ETL은 UPSERT + ON CONFLICT (idempotent)라 재실행 안전.

### 확인 필요 (가설 확정용)

- [x] 취소된 run의 실제 소요시간이 30:00 근처인지 Actions 화면에서 확인 → **확정 (Annotation에 30m0s 명시)**
- [ ] 같은 시각에 열려 있던 수동 DB 세션이 있었는지 기억 대조 (후보 ① 확정용)

---

## 2. 사건 ② — Node 20 deprecation 경고 (시한: 6/16)

### 내용 (GitHub 공식 공지 확인)

- **2026-06-16부터** 러너가 Node 24를 기본 강제 — Node 20 기반 액션은 "may not work as expected"
- **2026 가을(~9/16)** Node 20 완전 제거, 임시 우회(`ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION`)도 종료
- 사전 테스트: `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` env로 지금 Node 24 강제 가능

### 영향 범위 (GitHub Actions 런타임 경고 기준 — 2026-06-12 재확정)

> 메이저 버전 = Node 버전 매핑이 액션마다 다름. **GitHub 실측 경고가 ground truth.**

| 파일 | 액션 | Node 기반 (실측) | 6/16 영향 |
|---|---|---|---|
| `CORE-ETL/.github/workflows/etl-metadata-sync.yml:55` | `actions/checkout@v5` | Node 24 (경고 미발생) | ✅ 안전 |
| `CORE-ETL/.github/workflows/etl-metadata-sync.yml:58` | `actions/setup-python@v6` | Node 24 (경고 미발생) | ✅ 안전 |
| `CORE-ETL/.github/workflows/etl-metadata-sync.yml:93` | `actions/upload-artifact@v5` | **Node 20** (GitHub 경고 명시) | ⚠️ 영향 |
| `AXIS-OPS/.github/workflows/pytest.yml:29` | `actions/checkout@v4` | **Node 20** (추정) | ⚠️ 영향 |
| `AXIS-OPS/.github/workflows/pytest.yml:32` | `actions/setup-python@v5` | **Node 20** (추정) | ⚠️ 영향 |
| `AXIS-OPS/.github/workflows/pytest.yml:55` | `actions/upload-artifact@v4` | **Node 20** (추정) | ⚠️ 영향 |

→ **CORE-ETL도 6/16 영향 대상** — `upload-artifact@v5`가 Node 20. 즉시 조치 필요.
→ **AXIS-OPS도 영향 대상** — 3개 액션 모두 Node 20 가능성 높음. CI 1회 돌려서 경고 출력으로 확정 권장.

### `actions/upload-artifact` 릴리스 조사 결과 (2026-06-12)

| 버전 | Node 기반 | 릴리스 |
|---|---|---|
| **v7.0.1** | Node 24 | 4/10 (최신, 권장) |
| v7.0.0 | Node 24 | 2/26 |
| v6.0.0 | Node 24 | 12/12 |
| v5.0.0 | Node 24 (릴리스 노트) — but GitHub 런타임은 `@v5`를 Node 20으로 경고 ⚠️ | 10/24 |
| v4.6.2 | Node 20 | 3/19 |

→ **해결책: `@v5` → `@v7` 핀 업** — 가장 최근 + Node 24 명시 (modulo 릴리스 노트/런타임 불일치 회피). env 우회(`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`) 불필요.

### 리스크 시나리오

6/16 이후 artifact 업로드 step이 깨져도 **ETL 적재는 이전 step에서 완료**되므로 데이터는 무사. 단 run이 매일 4회 빨간 실패로 표시 → 알림 부재 상태에선 침묵하거나, 반대로 **가짜 실패 노이즈가 진짜 장애를 가림**.

---

## 3. 조치 계획 — workflow 정비 5종 (목표: 6/16 전)

> 사건 ①·② + P0 ②를 한 번의 workflow 수정으로 해소

- [ ] **(a) Node 24 호환화 — 양 레포 모두 대상** (`upload-artifact`는 `@v7` 핀 권장):
  - **(a-1) CORE-ETL etl-metadata-sync.yml L93**:
    - `actions/upload-artifact@v5` → **`@v7`** (Node 24 명시)
  - **(a-2) AXIS-OPS pytest.yml** — 액션 3종 모두 메이저 버전 업:
    - `actions/checkout@v4` → `@v5` (Node 24)
    - `actions/setup-python@v5` → `@v6` (Node 24)
    - `actions/upload-artifact@v4` → **`@v7`** (Node 24)
  - **검증**: CI 1회 돌려 deprecation 경고 사라지는지 확인. 잔존 시 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` env로 fallback
- [ ] **(b) 실패/취소 SMTP 알림 → `dkkim1@gst-in.com`** — 침묵 실패 차단 (P0 ②). Teams 미사용 결정에 따라 메일 채널로 확정:
  ```yaml
  - name: ETL 실패/취소 메일 알림
    if: failure() || cancelled()
    uses: dawidd6/action-send-mail@v4
    with:
      server_address: ${{ secrets.SMTP_HOST }}      # 예: smtp.office365.com
      server_port: ${{ secrets.SMTP_PORT }}         # 예: 587 (STARTTLS)
      secure: false                                  # 587/STARTTLS면 false, 465/SSL이면 true
      username: ${{ secrets.SMTP_USERNAME }}
      password: ${{ secrets.SMTP_PASSWORD }}
      from: "AXIS ETL Bot <${{ secrets.SMTP_USERNAME }}>"
      to: dkkim1@gst-in.com
      subject: "🔴 ETL Sync 실패/취소 — run ${{ github.run_id }}"
      body: |
        ETL 동기화 ${{ job.status }} 발생
        - Repo:  ${{ github.repository }}
        - Event: ${{ github.event_name }}
        - Run:   ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        - Time:  ${{ github.event.repository.updated_at }}
  ```

  **GitHub Secrets 등록 필요 항목**:
  | Secret | 값 (M365 가정) | 비고 |
  |---|---|---|
  | `SMTP_HOST` | `smtp.office365.com` | GST 메일 인프라 확인 후 결정 |
  | `SMTP_PORT` | `587` | STARTTLS |
  | `SMTP_USERNAME` | 발신용 메일 계정 | ex: `axis-bot@gst-in.com` 신규 발급 or 기존 서비스 계정 재사용 |
  | `SMTP_PASSWORD` | 위 계정 비밀번호 (또는 앱 비밀번호) | M365 + MFA 환경이면 **앱 비밀번호** 필수 |

  ⚠️ **선결 작업**:
  1. GST 메일 서버 (Office 365 / 자체 서버) 확인
  2. ETL 봇 전용 발신 계정 마련 — 기존 사용자 계정 자격증명을 secret에 넣지 말 것 (퇴사/MFA 변경 시 알림 끊김)
  3. M365라면 SMTP AUTH 허용 정책 확인 (테넌트 차원에서 막혀 있으면 IT 협조 필요)
- [ ] **(c) concurrency 가드** — 겹침 실행 방지 (사건 ① 후보 ②번 차단):
  ```yaml
  concurrency:
    group: etl-sync
    cancel-in-progress: false   # 겹치면 취소 대신 대기
  ```
- [ ] **(d) DB 타임아웃** — hang 대신 빠른 실패 (사건 ① 후보 ①번 차단):
  ```python
  conn = psycopg2.connect(DATABASE_URL,
      options="-c lock_timeout=60s -c statement_timeout=300s")
  ```
  → 락이면 60초 만에 명확한 에러 + (b) 알림 발송. 30분 침묵 대기 구조 제거.
  ⚠️ **검증 필요**: `statement_timeout=300s`는 세션 단일 쿼리당 5분 — UPSERT 한 건당으로는 충분하나, ETL 트랜잭션 구조가 단일 트랜잭션 전체 적재면 5분 초과 시 실패. 반기 자동 필터 1회분 소요 측정 후 값 조정 (여유분 2배 권장)
- [ ] **(e) step별 timestamped 로그** — 다음 hang 시 어느 단계에서 멈췄는지 즉시 식별 (사건 ① 후보 ③번 추적):
  ```python
  import time
  def _ts(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
  _ts("step2 시작 — DB 연결")
  _ts("step2 — prefetch 시작")
  _ts("step2 — UPSERT 루프 시작")
  ```
  `flush=True` 필수 — Actions 로그 버퍼링으로 진행 상황이 가려지면 hang 진단 불가

### 진행 순서 (2026-06-12 → 6/16)

| 순서 | 작업 | 대상 항목 | 소요 |
|---|---|---|---|
| 1️⃣ | GST SMTP 서버/포트 확인 + ETL 봇용 발신 계정 확보 + GitHub Secrets 4종 등록 (`SMTP_HOST/PORT/USERNAME/PASSWORD`) | (b) 선결 | 30분~1시간 (IT 협조) |
| 2️⃣ | `upload-artifact@v5→@v7` 핀 업 (CORE-ETL) + AXIS-OPS pytest.yml 액션 3종 메이저 업 | (a-1)(a-2) | 20분 + CI 1회 |
| 3️⃣ | CORE-ETL workflow에 concurrency 가드 + SMTP 알림 step 추가 | (b)(c) | 30분 |
| 4️⃣ | step2_load.py lock_timeout + timestamped 로그 | (d)(e) | 1시간 |
| 5️⃣ | 통합 검증 (CORE-ETL 1회 + AXIS-OPS pytest 1회 + 의도적 실패 1회로 메일 수신 테스트) | 완료 기준 | 15분 |

### 완료 기준

- **CORE-ETL** 수동 실행 1회: ✅ 미적재분 복구 + ✅ timestamped 로그 출력 + ✅ Node 20 deprecation 경고 사라짐
- **CORE-ETL** 의도적 실패 1회 (예: invalid SOURCE_DOC_ID로 dry-run): ✅ `dkkim1@gst-in.com` 메일 수신 확인
- **AXIS-OPS** pytest 실행 1회: ✅ 액션 v5/v6/v7 정상 동작 + Node 20 경고 사라짐

---

## 4. 참고

- 리스크 검토 보고서(Notion 🛡️ §8) P0 ② — 본 건으로 우선순위 재확인됨
- GitHub 공지: github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners
- openpyxl "Data Validation extension" 경고는 **무해** — 원인 분석 시 무시할 것
