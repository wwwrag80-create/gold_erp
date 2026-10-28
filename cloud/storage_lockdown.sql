-- ═══════════════════════════════════════════════════════════════
-- قفل حاوية التحديثات (5.0) — لا يكتب فيها إلا مفتاح الخدمة
-- ───────────────────────────────────────────────────────────────
-- البرنامج يُنزّل تحديثاته من الحاوية `app-updates`. والمفتاح العام
-- (anon) موجودٌ في كل نسخة من البرنامج — فلو سمحت أي سياسةٍ على
-- `storage.objects` بالكتابة له في هذه الحاوية لاستطاع أي حاملٍ
-- للبرنامج أن يضع «تحديثاً» تُنزّله كل المصانع وتشغّله.
--
-- السياسات هنا **مقيِّدة** (RESTRICTIVE): تُضاف إلى أي سياسةٍ قائمة
-- فلا تفتح شيئاً، وتمنع المفتاح العام والمستخدمين من الكتابة والتعديل
-- والحذف في `app-updates` مهما سمحت سياساتٌ أخرى. ونشر التحديث من
-- `tools/publish_update.py` بمفتاح الخدمة لا يتأثر (يتجاوز RLS).
--
-- شغّله مرة واحدة في: Supabase → SQL Editor → New query → RUN
-- ═══════════════════════════════════════════════════════════════

DROP POLICY IF EXISTS updates_no_public_insert ON storage.objects;
CREATE POLICY updates_no_public_insert ON storage.objects
  AS RESTRICTIVE FOR INSERT TO anon, authenticated
  WITH CHECK (bucket_id <> 'app-updates');

DROP POLICY IF EXISTS updates_no_public_update ON storage.objects;
CREATE POLICY updates_no_public_update ON storage.objects
  AS RESTRICTIVE FOR UPDATE TO anon, authenticated
  USING (bucket_id <> 'app-updates')
  WITH CHECK (bucket_id <> 'app-updates');

DROP POLICY IF EXISTS updates_no_public_delete ON storage.objects;
CREATE POLICY updates_no_public_delete ON storage.objects
  AS RESTRICTIVE FOR DELETE TO anon, authenticated
  USING (bucket_id <> 'app-updates');

-- للمراجعة: كل السياسات القائمة على ملفات التخزين
SELECT policyname, permissive, cmd, roles, qual, with_check
  FROM pg_policies
 WHERE schemaname = 'storage' AND tablename = 'objects'
 ORDER BY policyname;
