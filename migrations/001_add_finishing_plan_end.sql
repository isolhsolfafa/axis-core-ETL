-- Migration 001: Sprint 1 — UPSERT 지원 + 마무리계획종료일
-- 대상: AXIS-OPS Railway PostgreSQL
-- 실행: Railway DB 콘솔 또는 psql에서 수동 실행
-- 날짜: 2026-03-09

-- 1) 마무리계획종료일 컬럼 추가 (협력사 평가지수 + 실적관리 기준)
ALTER TABLE plan.product_info
ADD COLUMN IF NOT EXISTS finishing_plan_end DATE;

-- 2) UPSERT 변경 추적용 updated_at
ALTER TABLE plan.product_info
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- 3) serial_number UNIQUE 제약 확인 (ON CONFLICT 필수)
-- 이미 있으면 무시됨
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'product_info_serial_number_key'
        AND conrelid = 'plan.product_info'::regclass
    ) THEN
        ALTER TABLE plan.product_info
        ADD CONSTRAINT product_info_serial_number_key UNIQUE (serial_number);
    END IF;
END $$;

-- 확인
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'plan' AND table_name = 'product_info'
AND column_name IN ('finishing_plan_end', 'updated_at')
ORDER BY column_name;
