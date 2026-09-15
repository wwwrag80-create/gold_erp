-- ═══════════════════════════════════════════════════════════════
-- إدارة الحسابات بلا شحن مفتاح الخدمة في الملف التنفيذي
-- ───────────────────────────────────────────────────────────────
-- الفكرة: يحصل المدير على رمز إداري (admin_token) عند تسجيل دخوله،
-- ويُرسله مع كل عملية إدارية. الخادم يتحقق منه ثم ينفّذ بصلاحياته.
-- فلا يحمل الـexe أي مفتاح خطير، ولا يستطيع العملاء إنشاء حسابات.
-- شغّل هذا الملف مرة واحدة في: Supabase → SQL Editor
-- ═══════════════════════════════════════════════════════════════

-- 0) حماية على مستوى الجدول: اسم المصنع لا يكون فارغاً أبداً
ALTER TABLE factories ALTER COLUMN name SET DEFAULT 'مصنع';
UPDATE factories SET name = 'مصنع' WHERE name IS NULL OR TRIM(name) = '';

-- 1) إصلاح البنية
ALTER TABLE factory_users
  ADD COLUMN IF NOT EXISTS full_name TEXT DEFAULT '';
ALTER TABLE factory_users
  ADD COLUMN IF NOT EXISTS admin_token TEXT;

ALTER TABLE factory_users
  DROP CONSTRAINT IF EXISTS factory_users_tenant_id_username_key;
ALTER TABLE factory_users
  DROP CONSTRAINT IF EXISTS factory_users_tenant_id_key;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'factory_users_username_key') THEN
    ALTER TABLE factory_users
      ADD CONSTRAINT factory_users_username_key UNIQUE (username);
  END IF;
END $$;

-- 2) تسجيل الدخول: يعيد بيانات المستخدم ورمزه الإداري إن كان مديراً
CREATE OR REPLACE FUNCTION auth_login(p_username TEXT)
RETURNS TABLE (
  username TEXT, password_hash TEXT, tenant_id TEXT,
  role TEXT, is_active BOOLEAN, full_name TEXT, admin_token TEXT
) LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  RETURN QUERY
  SELECT u.username, u.password_hash, u.tenant_id, u.role,
         u.is_active, COALESCE(u.full_name, ''),
         CASE WHEN u.role = 'super_admin' THEN u.admin_token ELSE NULL END
  FROM factory_users u
  WHERE u.username = p_username
  LIMIT 1;
END $$;

-- 3) إنشاء حساب (يتحقق من الرمز الإداري أولاً)
CREATE OR REPLACE FUNCTION admin_create_user(
  p_token TEXT, p_username TEXT, p_hash TEXT, p_role TEXT,
  p_tenant TEXT, p_name TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE ok INT;
BEGIN
  SELECT COUNT(*) INTO ok FROM factory_users fu
   WHERE fu.admin_token = p_token AND fu.role = 'super_admin'
     AND fu.is_active;
  IF ok = 0 THEN
    RAISE EXCEPTION 'رمز إداري غير صالح';
  END IF;

  IF EXISTS (SELECT 1 FROM factory_users fu
              WHERE fu.username = p_username) THEN
    RAISE EXCEPTION 'اسم المستخدم مستخدم مسبقاً';
  END IF;

  -- سجل المصنع أولاً (المفتاح الأجنبي يشترط وجوده)
  INSERT INTO factories(tenant_id, name, is_active)
  VALUES (p_tenant,
          COALESCE(NULLIF(TRIM(p_name), ''),
                   NULLIF(TRIM(p_username), ''), 'مصنع'),
          TRUE)
  ON CONFLICT (tenant_id) DO NOTHING;

  INSERT INTO factory_users(tenant_id, username, password_hash, role,
                            full_name, is_active, admin_token)
  VALUES (p_tenant, p_username, p_hash, p_role,
          COALESCE(NULLIF(TRIM(p_name), ''), p_username), TRUE,
          CASE WHEN p_role = 'super_admin'
               THEN encode(gen_random_bytes(24), 'hex') ELSE NULL END);
  RETURN 'ok';
END $$;

-- 4) قائمة الحسابات
CREATE OR REPLACE FUNCTION admin_list_users(p_token TEXT)
RETURNS TABLE (
  username TEXT, full_name TEXT, tenant_id TEXT,
  role TEXT, is_active BOOLEAN
) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE ok INT;
BEGIN
  SELECT COUNT(*) INTO ok FROM factory_users fu
   WHERE fu.admin_token = p_token AND fu.role = 'super_admin'
     AND fu.is_active;
  IF ok = 0 THEN RAISE EXCEPTION 'رمز إداري غير صالح'; END IF;
  RETURN QUERY
  SELECT u.username, COALESCE(u.full_name, ''), u.tenant_id,
         u.role, u.is_active
  FROM factory_users u ORDER BY u.created_at DESC;
END $$;

-- 5) إيقاف/تفعيل وحذف
CREATE OR REPLACE FUNCTION admin_set_active(
  p_token TEXT, p_username TEXT, p_active BOOLEAN
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE ok INT;
BEGIN
  SELECT COUNT(*) INTO ok FROM factory_users fu
   WHERE fu.admin_token = p_token AND fu.role = 'super_admin'
     AND fu.is_active;
  IF ok = 0 THEN RAISE EXCEPTION 'رمز إداري غير صالح'; END IF;
  UPDATE factory_users fu SET is_active = p_active
   WHERE fu.username = p_username;
  UPDATE factories SET is_active = p_active
   WHERE tenant_id = (SELECT fu2.tenant_id FROM factory_users fu2
                       WHERE fu2.username = p_username);
  RETURN 'ok';
END $$;

CREATE OR REPLACE FUNCTION admin_delete_user(
  p_token TEXT, p_username TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE ok INT;
BEGIN
  SELECT COUNT(*) INTO ok FROM factory_users fu
   WHERE fu.admin_token = p_token AND fu.role = 'super_admin'
     AND fu.is_active;
  IF ok = 0 THEN RAISE EXCEPTION 'رمز إداري غير صالح'; END IF;
  DELETE FROM factory_users fu WHERE fu.username = p_username;
  RETURN 'ok';
END $$;

-- 6) إنشاء أول مدير (يعمل مرة واحدة فقط، ما دام لا يوجد مدير)
CREATE OR REPLACE FUNCTION bootstrap_admin(
  p_username TEXT, p_hash TEXT, p_tenant TEXT
) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE n INT; tok TEXT;
BEGIN
  SELECT COUNT(*) INTO n FROM factory_users fu
   WHERE fu.role = 'super_admin';
  IF n > 0 THEN
    RAISE EXCEPTION 'يوجد مدير مسجّل مسبقاً — سجّل الدخول به';
  END IF;
  tok := encode(gen_random_bytes(24), 'hex');
  -- اسم المصنع إلزامي في الجدول، فنضمن قيمة غير فارغة دائماً
  INSERT INTO factories(tenant_id, name, is_active)
  VALUES (p_tenant,
          COALESCE(NULLIF(TRIM(p_username), ''), 'الإدارة العامة'),
          TRUE)
  ON CONFLICT (tenant_id) DO NOTHING;
  INSERT INTO factory_users(tenant_id, username, password_hash, role,
                            full_name, is_active, admin_token)
  VALUES (p_tenant, p_username, p_hash, 'super_admin',
          'المدير العام', TRUE, tok);
  RETURN tok;
END $$;

-- 6.5) إصدار الدوال — يكشف تشغيل نسخة قديمة على الخادم
CREATE OR REPLACE FUNCTION rpc_version()
RETURNS TEXT LANGUAGE sql SECURITY DEFINER AS $$
  SELECT '2.1.0'::TEXT;
$$;
GRANT EXECUTE ON FUNCTION rpc_version() TO anon, authenticated;

-- 7) صلاحيات التنفيذ للمفتاح العام (الدوال تتحقق بنفسها)
GRANT EXECUTE ON FUNCTION auth_login(TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION admin_create_user(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION admin_list_users(TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION admin_set_active(TEXT,TEXT,BOOLEAN)
  TO anon, authenticated;
GRANT EXECUTE ON FUNCTION admin_delete_user(TEXT,TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION bootstrap_admin(TEXT,TEXT,TEXT) TO anon, authenticated;

-- ═══════════════════════════════════════════════════════════════
-- مسح بيانات مصنع من السحابة (Danger Zone)
-- يتطلب رمزاً إدارياً، ويُبقي سجل المصنع وحساباته
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION admin_wipe_tenant(p_token TEXT, p_tenant TEXT)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE ok INT;
BEGIN
  SELECT COUNT(*) INTO ok FROM factory_users fu
   WHERE fu.admin_token = p_token AND fu.role = 'super_admin'
     AND fu.is_active;
  IF ok = 0 THEN RAISE EXCEPTION 'رمز إداري غير صالح'; END IF;

  DELETE FROM sync_bundles   WHERE tenant_id = p_tenant;
  DELETE FROM journal_lines  WHERE tenant_id = p_tenant;
  DELETE FROM journal_entries WHERE tenant_id = p_tenant;
  DELETE FROM invoice_items  WHERE tenant_id = p_tenant;
  DELETE FROM invoices       WHERE tenant_id = p_tenant;
  DELETE FROM voucher_lines  WHERE tenant_id = p_tenant;
  DELETE FROM vouchers       WHERE tenant_id = p_tenant;
  DELETE FROM work_orders    WHERE tenant_id = p_tenant;
  RETURN 'ok';
END $$;
GRANT EXECUTE ON FUNCTION admin_wipe_tenant(TEXT,TEXT) TO anon, authenticated;
