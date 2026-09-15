-- ═══════════════════════════════════════════════════════════════
-- إصلاح قيود جدول الحسابات
-- شغّله في: Supabase → SQL Editor → New query → Run
-- ═══════════════════════════════════════════════════════════════

-- 1) إزالة القيود القديمة التي تمنع إنشاء أكثر من حساب
ALTER TABLE factory_users
  DROP CONSTRAINT IF EXISTS factory_users_tenant_id_username_key;
ALTER TABLE factory_users
  DROP CONSTRAINT IF EXISTS factory_users_tenant_id_key;

-- 2) العمود المطلوب للاسم الكامل
ALTER TABLE factory_users
  ADD COLUMN IF NOT EXISTS full_name TEXT DEFAULT '';

-- 3) القيد الصحيح: اسم المستخدم فريد عالمياً
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'factory_users_username_key') THEN
    ALTER TABLE factory_users
      ADD CONSTRAINT factory_users_username_key UNIQUE (username);
  END IF;
END $$;

-- 4) عرض القيود الحالية للتأكد
SELECT conname AS "القيد", pg_get_constraintdef(oid) AS "التعريف"
FROM pg_constraint
WHERE conrelid = 'factory_users'::regclass;

-- ═══════════════════════════════════════════════════════════════
-- دالة إصلاح تُستدعى من داخل النظام مستقبلاً
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION repair_users_schema()
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  ALTER TABLE factory_users
    DROP CONSTRAINT IF EXISTS factory_users_tenant_id_username_key;
  ALTER TABLE factory_users
    DROP CONSTRAINT IF EXISTS factory_users_tenant_id_key;
  ALTER TABLE factory_users
    ADD COLUMN IF NOT EXISTS full_name TEXT DEFAULT '';
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'factory_users_username_key') THEN
    ALTER TABLE factory_users
      ADD CONSTRAINT factory_users_username_key UNIQUE (username);
  END IF;
  RETURN 'ok';
END $$;
