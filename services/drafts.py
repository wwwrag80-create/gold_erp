# -*- coding: utf-8 -*-
"""مسوّدات شاشات الإدخال — ما أدخلته ولم ترحّله يبقى مكانه.

**المشكلة**: النظام يُبقي **شاشة واحدة حيّة** في كل لحظة (يُغلق
السابقة عند الانتقال، وهو ما يمنع تجمّده). فمن أدخل عشرين طقماً في
دفعة توريد ثم خرج ليراجع رقماً في شاشة أخرى، يعود فيجد الدفعة فارغة
— وقد ذهب ربع ساعة من العمل بلا خطأ منه ولا إنذار.

**العلاج**: ما لم يُرحَّل بعد يُحفظ مسوّدةً عند مغادرة الشاشة، ويُستعاد
عند العودة إليها. ويُمحى فور الترحيل — فالمسوّدة بديلٌ عن الذاكرة لا
عن الدفتر.

**ما هي وما ليست**:
* **ليست قيداً**: لا تمسّ حساباً ولا مخزوناً ولا رقماً محاسبياً. هي
  نصٌّ يصف ما كان في الشاشة، لا أثر له حتى يضغط المستخدم «ترحيل».
* **لكل مستخدم على حدة**: مسوّدة المحاسب لا تظهر لغيره.
* **تبقى بعد إغلاق النظام**: محفوظة في قاعدة المصنع لا في الذاكرة،
  فانقطاع الكهرباء لا يُضيع ما أُدخل.
* **لا تُستعاد في وضع التعديل**: تعديل مستندٍ مرحَّل حالةٌ قائمة
  بذاتها، وخلطُ مسوّدةٍ بها يُنتج مستنداً لا يقصده أحد.
"""
import json


def _ensure(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screen_drafts(
          screen TEXT NOT NULL,
          username TEXT NOT NULL DEFAULT '',
          payload TEXT NOT NULL DEFAULT '',
          updated_at TEXT DEFAULT (datetime('now','localtime')),
          PRIMARY KEY(screen, username)
        )""")


def save(screen, username, data):
    """يحفظ مسوّدة الشاشة. `data` فارغة أو None تمحو المحفوظ."""
    try:
        from database.database import db
        with db() as conn:
            _ensure(conn)
            if not data:
                conn.execute(
                    "DELETE FROM screen_drafts WHERE screen=? AND username=?",
                    (str(screen), str(username or "")))
                return True
            conn.execute(
                "INSERT OR REPLACE INTO screen_drafts"
                "(screen,username,payload,updated_at)"
                " VALUES(?,?,?,datetime('now','localtime'))",
                (str(screen), str(username or ""),
                 json.dumps(data, ensure_ascii=False)))
        return True
    except Exception:
        return False          # المسوّدة راحةٌ لا تُعطّل عملاً


def load(screen, username):
    """يعيد مسوّدة الشاشة المحفوظة، أو قاموساً فارغاً."""
    try:
        from database.database import db
        with db(readonly=True) as conn:
            r = conn.execute(
                "SELECT payload FROM screen_drafts"
                " WHERE screen=? AND username=?",
                (str(screen), str(username or ""))).fetchone()
        if not r or not (r["payload"] or "").strip():
            return {}
        d = json.loads(r["payload"])
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def clear(screen, username):
    """يمحو المسوّدة — يُستدعى فور الترحيل الناجح."""
    return save(screen, username, None)
