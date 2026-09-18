# -*- coding: utf-8 -*-
"""هجرات قاعدة البيانات المحلية — تُنفَّذ **مرة واحدة** لكل إصدار.

المشكلة: الإصدار الجديد قد يحتاج أعمدة أو جداول جديدة؛ فإن شُغّل على
قاعدة قديمة انهار النظام المحاسبي. الحل: ملفات SQL مرقّمة في مجلد
`migrations/` تُنفَّذ تصاعدياً مرة واحدة فقط، ويُسجَّل ما نُفِّذ في جدول
`schema_migrations` — فلا تتكرر ولا تُفقد.

كل ملف يُنفَّذ داخل **معاملة واحدة**: إن فشل تراجع بالكامل ولم يُسجَّل،
فتبقى القاعدة سليمة ويُعاد المحاولة في التشغيل التالي.
"""
import hashlib
import re
from pathlib import Path

import config

NAME_RE = re.compile(r"^(\d{3,})[_-](.+)\.sql$", re.IGNORECASE)


def _dirs():
    """أماكن ملفات الهجرة — بالترتيب، وأولها الأصحّ.

    **الخلل الذي عولج**: كان المسار `config.BASE_DIR / "migrations"`،
    و`BASE_DIR` هو مجلد **البيانات** لا مجلد البرنامج. وهما مجلدٌ
    واحد في التشغيل من المصدر بلا إعدادات — فمرّ الأمر. أما نسخة
    الـexe فبياناتها في مجلدٍ دائم منفصل، وكذلك أي تشغيل يضبط
    `JADEITE_DATA_DIR`: هناك لا يوجد مجلد `migrations` أصلاً، فكانت
    `discover()` تعيد لا شيء و`run_all` تنجح صامتةً بلا تنفيذ هجرة
    واحدة. والنتيجة عند المستخدم: «لا يوجد جدول كذا» عند أول ميزةٍ
    تعتمد هجرة. لم يظهر قبل الآن لأن الهجرة الوحيدة (001) خطُّ أساسٍ
    لا أثر له.

    وملفات الهجرة تُشحن مع **الكود** لا مع بيانات المستخدم، فمكانها
    جذر المشروع أو جذر الحزمة المفكوكة.
    """
    here = Path(__file__).resolve().parent.parent      # services/ → الجذر
    cands = [here / "migrations",
             Path(getattr(config, "BUNDLE_DIR", here)) / "migrations",
             Path(config.BASE_DIR) / "migrations"]     # وضعٌ قديم
    out, seen = [], set()
    for d in cands:
        try:
            key = str(d.resolve())
        except Exception:
            key = str(d)
        if key in seen:
            continue
        seen.add(key)
        if d.is_dir():
            out.append(d)
    return out


# يبقى الاسم للتوافق: أول مجلدٍ وُجد، أو الجذر إن لم يوجد شيء
MIGRATIONS_DIR = (_dirs() or [Path(__file__).resolve().parent.parent
                              / "migrations"])[0]


def _split(sql):
    """يقسّم ملف SQL إلى عبارات مستقلة مع تجاهل التعليقات."""
    out, buf = [], []
    for raw in sql.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        buf.append(raw)
        if line.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations(
          id         INTEGER PRIMARY KEY,
          name       TEXT NOT NULL,
          checksum   TEXT NOT NULL,
          applied_at TEXT DEFAULT (datetime('now','localtime'))
        )""")


def discover():
    """يعيد الهجرات مرتّبة تصاعدياً: [(رقم, اسم, مسار)].

    يُبحث في كل المجلدات المحتملة، والأسبقية للأول: رقمٌ وُجد مرتين
    يُؤخذ من مجلد الكود لا من نسخةٍ قديمة في مجلد البيانات.
    """
    found = {}
    for d in _dirs():
        for p in d.glob("*.sql"):
            m = NAME_RE.match(p.name)
            if m and int(m.group(1)) not in found:
                found[int(m.group(1))] = (int(m.group(1)), m.group(2), p)
    return [found[k] for k in sorted(found)]


def applied(conn):
    _ensure_table(conn)
    return {r["id"]: r["checksum"]
            for r in conn.execute("SELECT id, checksum FROM schema_migrations")}


def pending(conn):
    done = applied(conn)
    return [(i, n, p) for i, n, p in discover() if i not in done]


def run_all(conn, on_progress=None):
    """ينفّذ كل الهجرات المعلّقة بالترتيب.

    يُستدعى عند كل إقلاع؛ فإن لم يوجد جديد لم يفعل شيئاً (سريع جداً).
    """
    _ensure_table(conn)
    done = applied(conn)
    ran = []
    for num, name, path in discover():
        if num in done:
            continue
        sql = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:32]
        # كل ملف داخل نقطة حفظ: الفشل يتراجع بلا أثر
        # لا نستخدم executescript لأنه يُنهي المعاملة ضمنياً ويُلغي
        # نقطة الحفظ — ننفّذ العبارات فرادى داخلها.
        conn.execute(f"SAVEPOINT mig_{num}")
        try:
            for stmt in _split(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(id,name,checksum)"
                " VALUES(?,?,?)", (num, name, digest))
            conn.execute(f"RELEASE mig_{num}")
        except Exception as e:
            conn.execute(f"ROLLBACK TO mig_{num}")
            conn.execute(f"RELEASE mig_{num}")
            raise RuntimeError(
                f"فشلت الهجرة {num:03d}_{name}: {e}") from e
        ran.append(f"{num:03d}_{name}")
        if on_progress:
            on_progress(num, name)
    return ran


def status(conn):
    done = applied(conn)
    all_m = discover()
    return {"total": len(all_m), "applied": len(done),
            "pending": [f"{i:03d}_{n}" for i, n, _ in all_m if i not in done]}
