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
* **تبقى بعد إغلاق النظام**: محفوظة على القرص لا في الذاكرة، فانقطاع
  الكهرباء لا يُضيع ما أُدخل.
* **لا تُستعاد في وضع التعديل**: تعديل مستندٍ مرحَّل حالةٌ قائمة
  بذاتها، وخلطُ مسوّدةٍ بها يُنتج مستنداً لا يقصده أحد.

**ملفٌّ مستقلّ (5.0.5)**: كانت المسوّدات جدولاً في قاعدة المصنع نفسها،
ومنذ 5.0 تُحفظ وهي تُكتب (كل ثانيتين ونصف). فكلُّ حفظٍ كان يطلب قفل
الكتابة على القاعدة — فإن كان خيطٌ خلفي (مزامنة، نسخ احتياطي، رفع)
يكتب في تلك اللحظة انتظرت الواجهة حتى 30 ثانية وهي «لا تستجيب»، ويدُ
المستخدم على لوحة المفاتيح لم ترحّل شيئاً. الآن للمسوّدات ملفٌّ صغير
بجانب القاعدة (`<القاعدة>.drafts`) لا ينافس الفواتير على قفلها، ولا
يغيّر بصمة البيانات فلا تُعاد قراءة الشاشات بسببه. وما بقي في الجدول
القديم يُنقل إليه عند أول قراءة.
"""
import json
import sqlite3
import threading

# كاتبٌ واحد على الملف في كل لحظة (RLock: الحفظ المباشر يُلغي المعلَّق
# ثم يكتب وهو ممسكٌ به، فلا يسبقه كاتبٌ خلفيٌّ بنسخةٍ أقدم)
_LOCK = threading.RLock()
_COND = threading.Condition(threading.Lock())
_PENDING = {}             # (الشاشة، المستخدم) ← (النص، الجيل)
_EPOCH = {}               # جيلُ كل مفتاح — يتقدّم مع كل حفظٍ مباشر أو محو
_FAILED = set()           # مفاتيح فشلت كتابتها الخلفية — تُعاد
_BUSY = [0]
_THREAD = [None]
_MIGRATED = set()         # قواعدُ نُقلت مسوّداتها القديمة


def _key(screen, username):
    return (str(screen), str(username or ""))


def _path():
    import config                     # كما تقرؤه القاعدة (`database`)
    p = config.DB_PATH
    return str(p.with_name(p.name + ".drafts"))


def _connect():
    conn = sqlite3.connect(_path(), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        # ما كُتب ثبت على القرص قبل أن يعود الأمر — المسوّدة لانقطاع
        # الكهرباء أصلاً
        conn.execute("PRAGMA synchronous=FULL")
    except sqlite3.Error:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screen_drafts(
          screen TEXT NOT NULL,
          username TEXT NOT NULL DEFAULT '',
          payload TEXT NOT NULL DEFAULT '',
          updated_at TEXT DEFAULT (datetime('now','localtime')),
          PRIMARY KEY(screen, username)
        )""")
    return conn


def _write(k, payload, keep_newer=False):
    """يكتب نصّ المسوّدة (أو يمحوها إن كان فارغاً)."""
    with _LOCK:
        conn = _connect()
        try:
            if not payload:
                conn.execute(
                    "DELETE FROM screen_drafts WHERE screen=? AND username=?",
                    k)
            else:
                conn.execute(
                    ("INSERT OR IGNORE" if keep_newer else "INSERT OR REPLACE")
                    + " INTO screen_drafts(screen,username,payload,updated_at)"
                    " VALUES(?,?,?,datetime('now','localtime'))",
                    (k[0], k[1], payload))
        finally:
            conn.close()


def _cancel(k):
    """يُسقط ما ينتظر الكتابة الخلفية لهذا المفتاح، ويُبطل ما بيد الكاتب."""
    with _COND:
        _EPOCH[k] = _EPOCH.get(k, 0) + 1
        _PENDING.pop(k, None)
        _FAILED.discard(k)


def save_payload(screen, username, payload):
    """يحفظ نصّاً مُسلسَلاً جاهزاً **الآن** — ويُلغي ما ينتظر الكاتب."""
    k = _key(screen, username)
    try:
        with _LOCK:
            _cancel(k)
            _write(k, payload or "")
        return True
    except Exception:
        return False          # المسوّدة راحةٌ لا تُعطّل عملاً


def save(screen, username, data):
    """يحفظ مسوّدة الشاشة. `data` فارغة أو None تمحو المحفوظ."""
    try:
        payload = json.dumps(data, ensure_ascii=False) if data else ""
    except Exception:
        return False
    return save_payload(screen, username, payload)


# ══ الكتابة في الخلفية (5.0.5) ══
# حارس المسوّدة يقرأ الشاشة في خيط الواجهة (سريع) ويسلّم النصّ هنا،
# فلا تنتظر الواجهةُ القرصَ ولا قفلاً. الأحدث يغلب: نصٌّ جديد لشاشةٍ
# يحلّ محلّ ما لم يُكتب بعد من سابقه.

def save_async(screen, username, payload):
    k = _key(screen, username)
    with _COND:
        _PENDING[k] = (payload or "", _EPOCH.get(k, 0))
        t = _THREAD[0]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_run, name="draft-writer",
                                 daemon=True)
            _THREAD[0] = t
            t.start()
        _COND.notify_all()


def _run():
    while True:
        with _COND:
            while not _PENDING:
                _COND.wait()
            k, (payload, ep) = _PENDING.popitem()
            _BUSY[0] += 1
        try:
            with _LOCK:
                with _COND:
                    stale = _EPOCH.get(k, 0) != ep
                if not stale:
                    _write(k, payload)
                    with _COND:
                        _FAILED.discard(k)
        except Exception:
            with _COND:
                _FAILED.add(k)
        finally:
            with _COND:
                _BUSY[0] -= 1
                _COND.notify_all()


def pending(screen, username):
    """هل لهذه المسوّدة نصٌّ لم يكتبه الكاتب الخلفي بعد؟"""
    with _COND:
        return _key(screen, username) in _PENDING or bool(_BUSY[0])


def failed(screen, username):
    """هل فشلت آخر كتابةٍ خلفية لهذه المسوّدة؟ — فيُعيدها الحارس."""
    with _COND:
        return _key(screen, username) in _FAILED


def flush(timeout=3.0):
    """ينتظر حتى يفرغ الكاتب الخلفي — قبل الإغلاق وفي الفحوص."""
    with _COND:
        return _COND.wait_for(lambda: not _PENDING and not _BUSY[0],
                              timeout)


def _migrate_legacy():
    """ينقل مسوّدات الجدول القديم في قاعدة المصنع إلى ملفها — مرةً.

    النقل والمحو في معاملةٍ واحدة على القاعدة: إن فشلت الكتابة في الملف
    بقي القديم كما هو ليُنقل في التشغيل التالي. وما في الملف أحدثُ من
    القديم دائماً فلا يُستبدل به."""
    key = _path()
    if key in _MIGRATED:
        return
    _MIGRATED.add(key)
    try:
        from database.database import db
        with db(readonly=True) as conn:
            n = conn.execute("SELECT COUNT(*) FROM screen_drafts"
                             " WHERE payload<>''").fetchone()[0]
        if not n:
            return
        with db() as conn:
            for r in conn.execute(
                    "SELECT screen, username, payload FROM screen_drafts"
                    " WHERE payload<>''").fetchall():
                _write(_key(r["screen"], r["username"]), r["payload"],
                       keep_newer=True)
            conn.execute("DELETE FROM screen_drafts")
    except Exception:
        pass                      # لا جدول قديم، أو قاعدةٌ مشغولة: لاحقاً


def load(screen, username):
    """يعيد مسوّدة الشاشة المحفوظة، أو قاموساً فارغاً."""
    _migrate_legacy()
    try:
        with _LOCK:
            conn = _connect()
            try:
                r = conn.execute(
                    "SELECT payload FROM screen_drafts"
                    " WHERE screen=? AND username=?",
                    _key(screen, username)).fetchone()
            finally:
                conn.close()
        if not r or not (r["payload"] or "").strip():
            return {}
        d = json.loads(r["payload"])
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def clear(screen, username):
    """يمحو المسوّدة — يُستدعى فور الترحيل الناجح."""
    return save(screen, username, None)
