# Sprint {N} 완료 보고서

> 완료일: YYYY-MM-DD
> Sprint: docs/SPRINT_{N}.md

---

## 테스트 결과

### 로컬 테스트
```
실행 명령어: python etl_main.py --start YYYY-MM-DD --end YYYY-MM-DD

Excel 다운로드: ✅/❌ (방법 A/B)
파싱 행 수: {N}건
S/N 누락 제외: {N}건
```

### DB 적재 결과
```
전체 추출: {N}건
필터 적용: {N}건
신규 적재: {N}건
변경 업데이트: {N}건
동일 (변경 없음): {N}건
S/N 누락 skip: {N}건
에러: {N}건
```

### 재실행 테스트 (UPSERT 검증)
```
동일 데이터 재실행 → 신규: 0, 변경: 0, 동일: {N}
```

### GitHub Actions 테스트
- [ ] workflow_dispatch 수동 실행: ✅/❌
- [ ] 실행 시간: {N}초
- [ ] 아티팩트 업로드: ✅/❌

---

## 완료 항목

| Task | 상태 | 비고 |
|------|------|------|
| Task 1: ... | ✅/❌ | |
| Task 2: ... | ✅/❌ | |
| Task 3: ... | ✅/❌ | |

---

## 수정된 파일

```
파일명                    # 신규/수정/삭제
```

---

## DB 마이그레이션 (실행 여부)

```sql
-- 실행한 SQL (있으면 기록)
```

---

## 발견된 이슈 / 다음 Sprint 전달 사항

- 없음 / 이슈 내용

---

## MD 파일 업데이트 체크리스트

- [ ] PROGRESS.md — Sprint {N} 섹션 추가
- [ ] BACKLOG.md — Sprint 이력 테이블 상태 변경
- [ ] CLAUDE.md — 구조/환경변수 변경 시 반영
- [ ] push 완료
