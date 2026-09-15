-- الهجرة الأساسية: تسجيل نقطة البداية.
-- الجداول الأصلية تُنشأ من database/database.py (SCHEMA + migrate_schema)،
-- وهذا الملف يوثّق خط الأساس ليبدأ الترقيم منه.
CREATE TABLE IF NOT EXISTS schema_baseline(
  marker TEXT PRIMARY KEY,
  noted_at TEXT DEFAULT (datetime('now','localtime'))
);
INSERT OR IGNORE INTO schema_baseline(marker) VALUES ('v1.0.0');
