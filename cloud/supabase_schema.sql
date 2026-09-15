-- ═══════════════════════════════════════════════════════════════
-- مخطط السحابة المركزية (Supabase / PostgreSQL)
-- نظام جاديت متعدد المصانع — عزل تام بين المصانع عبر tenant_id
-- ═══════════════════════════════════════════════════════════════

-- سجل المصانع المشتركة
CREATE TABLE IF NOT EXISTS factories (
  tenant_id     TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  license_key   TEXT,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- سجل الحزم الواردة (idempotent: op_uuid يمنع التكرار عند إعادة الرفع)
CREATE TABLE IF NOT EXISTS sync_bundles (
  id          BIGSERIAL PRIMARY KEY,
  tenant_id   TEXT NOT NULL REFERENCES factories(tenant_id),
  op_uuid     UUID NOT NULL UNIQUE,
  entity      TEXT NOT NULL,
  payload     JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_bundles_tenant ON sync_bundles(tenant_id, id);

-- الجداول المرآة: كلها تحمل tenant_id إجبارياً
CREATE TABLE IF NOT EXISTS journal_entries (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL,
  entry_date DATE, description TEXT, user_note TEXT,
  source_table TEXT, source_id BIGINT,
  is_deleted INT DEFAULT 0, created_by TEXT, created_at TIMESTAMPTZ,
  PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS journal_lines (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL, entry_id BIGINT,
  account_id BIGINT, gold_debit NUMERIC, gold_credit NUMERIC,
  cash_debit NUMERIC, cash_credit NUMERIC, line_desc TEXT,
  PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS invoices (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL,
  invoice_no TEXT, kind TEXT, customer_id BIGINT, invoice_date DATE,
  total_wages NUMERIC, total_weight NUMERIC, vat_applied INT,
  vat_amount NUMERIC, grand_total NUMERIC, description TEXT,
  entry_id BIGINT, is_deleted INT DEFAULT 0,
  created_by TEXT, created_at TIMESTAMPTZ,
  PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS invoice_items (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL, invoice_id BIGINT,
  work_order_id BIGINT, registered_weight NUMERIC,
  wage_per_gram NUMERIC, wages NUMERIC,
  PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS vouchers (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL,
  voucher_no TEXT, kind TEXT, customer_id BIGINT, voucher_date DATE,
  gold_weight NUMERIC, gold_karat INT, gold_equiv18 NUMERIC,
  cash_amount NUMERIC, net_diff NUMERIC, disc_cash NUMERIC,
  disc_gold NUMERIC, notes TEXT, entry_id BIGINT,
  is_deleted INT DEFAULT 0, created_by TEXT, created_at TIMESTAMPTZ,
  PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS voucher_lines (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL, voucher_id BIGINT,
  line_kind TEXT, gold_weight NUMERIC, gold_karat INT,
  gold_equiv18 NUMERIC, cash_amount NUMERIC, line_notes TEXT,
  PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS work_orders (
  tenant_id TEXT NOT NULL, id BIGINT NOT NULL,
  work_order_no TEXT, status TEXT, registered_weight NUMERIC,
  item_type TEXT, PRIMARY KEY (tenant_id, id)
);

-- ═══════════════════════════════════════════════════════════════
-- استيعاب الحزم: كل حزمة داخل معاملة واحدة على الخادم
-- فإما تُكتب الفاتورة وقيدها وحركة أطقمها معاً أو لا شيء
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION ingest_bundle(batch JSONB)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE it JSONB; n INT := 0; p JSONB; t TEXT; rec JSONB;
BEGIN
  FOR it IN SELECT * FROM jsonb_array_elements(batch) LOOP
    t := it->>'p_tenant_id';
    p := it->'p_payload';

    -- idempotent: تجاهل الحزمة المرفوعة سابقاً
    BEGIN
      INSERT INTO sync_bundles(tenant_id, op_uuid, entity, payload)
      VALUES (t, (it->>'p_op_uuid')::uuid, it->>'p_entity', p);
    EXCEPTION WHEN unique_violation THEN
      CONTINUE;
    END;

    IF p ? 'entry' AND p->'entry' <> 'null'::jsonb THEN
      rec := p->'entry';
      INSERT INTO journal_entries(tenant_id,id,entry_date,description,
        user_note,source_table,source_id,is_deleted,created_by)
      VALUES (t,(rec->>'id')::bigint,(rec->>'entry_date')::date,
              rec->>'description', rec->>'user_note',
              rec->>'source_table', (rec->>'source_id')::bigint,
              COALESCE((rec->>'is_deleted')::int,0), rec->>'created_by')
      ON CONFLICT (tenant_id,id) DO NOTHING;
    END IF;

    n := n + 1;
  END LOOP;
  RETURN n;
END $$;

-- ═══════════════════════════════════════════════════════════════
-- أمن الصفوف (Row Level Security) — ضروري جداً
-- ───────────────────────────────────────────────────────────────
-- المفتاح العام (publishable) يُوزَّع مع نسخ المصانع، فيصل للعملاء.
-- بدون RLS يستطيع أي حامل للمفتاح قراءة بيانات كل المصانع أو
-- تعديلها. السياسات أدناه تمنع ذلك: كل مصنع يرى صفوفه فقط.
-- ═══════════════════════════════════════════════════════════════

ALTER TABLE factories       ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_bundles    ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_lines   ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices        ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_items   ENABLE ROW LEVEL SECURITY;
ALTER TABLE vouchers        ENABLE ROW LEVEL SECURITY;
ALTER TABLE voucher_lines   ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_orders     ENABLE ROW LEVEL SECURITY;

-- هوية المصنع تصل مع كل طلب في ترويسة مخصّصة
CREATE OR REPLACE FUNCTION current_tenant() RETURNS TEXT
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    current_setting('request.headers', true)::json->>'x-tenant-id', '');
$$;

-- سياسة موحّدة: كل مصنع يرى ويكتب صفوفه فقط
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['sync_bundles','journal_entries','journal_lines',
                           'invoices','invoice_items','vouchers',
                           'voucher_lines','work_orders'] LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS tenant_isolation ON %I; '
      'CREATE POLICY tenant_isolation ON %I FOR ALL '
      'USING (tenant_id = current_tenant()) '
      'WITH CHECK (tenant_id = current_tenant());', t, t);
  END LOOP;
END $$;

-- جدول المصانع: المصنع يقرأ سجله فقط
DROP POLICY IF EXISTS factory_self ON factories;
CREATE POLICY factory_self ON factories FOR SELECT
  USING (tenant_id = current_tenant());

-- ملاحظة: مفتاح الخدمة (service_role) يتجاوز RLS تلقائياً، وهو ما
-- تستخدمه نسخة المدير الأعلى وحدها لإدارة المصانع وانتحال الشخصية.
-- لا يُوزَّع هذا المفتاح مع نسخ المصانع إطلاقاً.

-- ═══════════════════════════════════════════════════════════════
-- حسابات أصحاب المصانع (يُنشئها المدير الأعلى)
-- كلمات المرور تُخزَّن مُجزّأة (hash) ولا تُحفظ نصاً صريحاً أبداً
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS factory_users (
  id            BIGSERIAL PRIMARY KEY,
  tenant_id     TEXT NOT NULL REFERENCES factories(tenant_id),
  username      TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  full_name     TEXT,
  role          TEXT NOT NULL DEFAULT 'owner',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, username)
);
ALTER TABLE factory_users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_self ON factory_users;
CREATE POLICY users_self ON factory_users FOR SELECT
  USING (tenant_id = current_tenant());

-- ═══════════════════════════════════════════════════════════════
-- إصدارات التطبيق — للتحديث التلقائي
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS app_versions (
  id           BIGSERIAL PRIMARY KEY,
  version      TEXT NOT NULL,
  notes        TEXT,
  download_url TEXT,
  is_mandatory BOOLEAN NOT NULL DEFAULT FALSE,
  released_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE app_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS versions_readable ON app_versions;
CREATE POLICY versions_readable ON app_versions FOR SELECT USING (TRUE);

-- سبب الإيقاف يُعرض للمصنع عند منع الدخول
ALTER TABLE factories
  ADD COLUMN IF NOT EXISTS suspend_reason TEXT DEFAULT '';

-- المصنع يقرأ حالته (لازم للتحقق من الإيقاف عن بُعد)
DROP POLICY IF EXISTS factory_self ON factories;
CREATE POLICY factory_self ON factories FOR SELECT
  USING (tenant_id = current_tenant());

-- ═══════════════════════════════════════════════════════════════
-- تحديث جدول المستخدمين: اسم مستخدم فريد عالمياً + صلاحية
-- (النظام يعتمد الدخول المركزي، فاسم المستخدم يجب أن يكون فريداً)
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE factory_users
  ADD COLUMN IF NOT EXISTS full_name TEXT DEFAULT '';

DO $$
BEGIN
  -- إزالة القيد المركّب القديم إن وُجد، وفرض تفرّد اسم المستخدم
  IF EXISTS (SELECT 1 FROM pg_constraint
             WHERE conname = 'factory_users_tenant_id_username_key') THEN
    ALTER TABLE factory_users
      DROP CONSTRAINT factory_users_tenant_id_username_key;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'factory_users_username_key') THEN
    ALTER TABLE factory_users
      ADD CONSTRAINT factory_users_username_key UNIQUE (username);
  END IF;
END $$;

-- التحقق من الهوية يتم بمفتاح service_role من التطبيق، فتُمنع القراءة
-- العامة لجدول المستخدمين حمايةً لبصمات كلمات المرور.
DROP POLICY IF EXISTS users_self ON factory_users;

-- ═══════════════════════════════════════════════════════════════
-- تخزين النسخ الاحتياطية للمصانع
-- كل مصنع يرفع ويقرأ نسخه وحده (المسار يبدأ بهويته)
-- ═══════════════════════════════════════════════════════════════
INSERT INTO storage.buckets (id, name, public)
VALUES ('factory-backups', 'factory-backups', FALSE)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS backups_own_read ON storage.objects;
CREATE POLICY backups_own_read ON storage.objects FOR SELECT
  USING (bucket_id = 'factory-backups'
         AND (storage.foldername(name))[1] = current_tenant());

DROP POLICY IF EXISTS backups_own_write ON storage.objects;
CREATE POLICY backups_own_write ON storage.objects FOR INSERT
  WITH CHECK (bucket_id = 'factory-backups'
              AND (storage.foldername(name))[1] = current_tenant());

DROP POLICY IF EXISTS backups_own_update ON storage.objects;
CREATE POLICY backups_own_update ON storage.objects FOR UPDATE
  USING (bucket_id = 'factory-backups'
         AND (storage.foldername(name))[1] = current_tenant());
