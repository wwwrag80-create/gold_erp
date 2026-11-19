# -*- coding: utf-8 -*-
"""السنوات المالية (5.9) — زرّ «السنة»: لكل سنةٍ حساباتها، وكل شيءٍ محفوظ.

**المنطق المحاسبي المتعارف عليه** (دفتر أستاذٍ واحدٌ مستمر، كأنظمة ERP):

* **السنة الجديدة تبدأ بالأرصدة نفسها**: ما على العملاء وما للمصانع، والصناديق
  والبنوك والذهب والمخزون — كلها حسابات ميزانية تنتقل كما هي، فتظهر أول السنة
  «رصيداً سابقاً» في كل كشف. لا يُعاد إدخال شيء.
* **والنتيجة تبدأ من صفر**: الإيرادات والمصروفات تُصفَّر بقيد إقفالٍ بتاريخ
  31-12 ويُرحَّل صافي الربح (أو الخسارة) إلى الأرباح المحتجزة (أو جاري الشركاء)
  — `models.closing.run_year_end_closing`.
* **والسنة المُقفلة تُحفظ ولا تُمسّ**: قفل الفترات (`models.fiscal`) يمنع أي قيدٍ
  أو تعديلٍ أو حذفٍ بتاريخها، وتبقى كاملةً للعرض والكشوف والتقارير متى اختيرت
  من زرّ السنة. وتُفتح للتصحيح عند الحاجة (للمدير العام) ثم تُقفل من جديد —
  وإقفالها ثانيةً يُرحّل ما تغيّر فقط.
* **بالترتيب**: لا تُقفل سنةٌ قبل ما قبلها، ولا سنةٌ لم تنتهِ بعد. ونسخةٌ
  احتياطية تُؤخذ قبل كل إقفال.

والسنة التي **يعمل فيها كل مستخدم** (`services.work_year`) تُحفظ له: بها تبدأ
كل شاشةٍ فترتها وتواريخها — فمن اختار 2026 يرى حسابات 2026 وحدها، ومن رجع
إلى 2025 يراها كما أُقفلت.
"""
import datetime as _dt

from models import fiscal
from services.audit import log_action

WORK_KEY = "fiscal_work_year"
# 5.10.2: آخر سنةٍ «بُدئت» قبل أوانها أو دون إقفال ما قبلها — تظهر في القائمة
STARTED_KEY = "fiscal_started_through"


def _today():
    return _dt.date.today()


def closed_through(conn):
    """آخر سنةٍ مُقفلة كاملةً (قفلٌ في 31-12 أو بعده) — أو None."""
    lock = fiscal.lock_date(conn)
    if not lock:
        return None
    try:
        d = _dt.date.fromisoformat(lock[:10])
    except ValueError:
        return None
    return d.year if (d.month, d.day) == (12, 31) else d.year - 1


def is_closed(conn, year):
    last = closed_through(conn)
    return last is not None and int(year) <= last


def first_year(conn):
    r = conn.execute("SELECT MIN(entry_date) d FROM journal_entries"
                     " WHERE is_deleted=0").fetchone()
    d = (r["d"] if r else None) or ""
    try:
        return int(str(d)[:4])
    except ValueError:
        return _today().year


def years(conn):
    """السنوات من أول قيدٍ حتى السنة الجارية (والتي بعد آخر مُقفلة) — لكلٍّ
    حالها: مقفلة؟ وكم قيداً فيها."""
    cur = _today().year
    first = min(first_year(conn), cur)
    last = max(cur, (closed_through(conn) or 0) + 1, started_through(conn) or 0)
    counts = {int(r["y"]): r["n"] for r in conn.execute(
        "SELECT substr(entry_date,1,4) y, COUNT(*) n FROM journal_entries"
        " WHERE is_deleted=0 GROUP BY y") if str(r["y"] or "").isdigit()}
    out = []
    for y in range(first, last + 1):
        out.append({"year": y, "closed": is_closed(conn, y),
                    "entries": counts.get(y, 0), "current": y == cur})
    return out


def started_through(conn):
    try:
        return int(str(fiscal.get_setting(conn, STARTED_KEY, "") or "").strip())
    except ValueError:
        return None


def latest_year(conn):
    return years(conn)[-1]["year"]


def start_next_year(conn, username):
    """يبدأ السنة التالية لآخر سنةٍ في القائمة **دون إقفال ما قبلها** (5.10.2).

    الأرصدة الافتتاحية تنتقل وحدها: الدفتر واحدٌ متصل، فرصيد كل حسابٍ في أول
    السنة الجديدة هو رصيده في آخر التي قبلها («رصيدٌ سابق» في كل كشف). والسنة
    السابقة تبقى مفتوحةً تقبل التصحيح، وتُقفل متى شاء المدير بعد انتهائها —
    فيُرحَّل صافيها حينئذٍ بقيدٍ بتاريخ 31-12 إلى الأرباح المحتجزة."""
    y = latest_year(conn) + 1
    fiscal.set_setting(conn, STARTED_KEY, str(y), username)
    set_work_year(conn, username, y)
    log_action(conn, username, "fiscal_year_start", "settings", None,
               f"بدء سنة {y} (والأرصدة الافتتاحية من {y - 1}) دون إقفال {y - 1}")
    return y


def opening_balances(conn, year):
    """الأرصدة الافتتاحية لسنة `year` = الأرصدة كما هي في 31-12 من السنة قبلها.

    تُجمع حسابات الميزانية (أصول · خصوم · حقوق ملكية) تحت حسابها في
    المستوى الثالث (الصناديق · العملاء · المخزون …) نقداً وذهباً، ومعها صافي
    إيرادات ومصروفات سنواتٍ لم تُقفل بعد (يُرحَّل للأرباح المحتجزة عند إقفالها)."""
    start = f"{int(year)}-01-01"
    acc = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, code, name, type, parent_id, account_level FROM accounts")}

    def head(aid):
        """الحساب في المستوى الثالث من الشجرة (الصناديق · العملاء · المخزون…)."""
        chain, a, seen = [], acc.get(aid), set()
        while a and a["id"] not in seen:
            seen.add(a["id"])
            chain.append(a)
            a = acc.get(a.get("parent_id"))
        return chain[-3] if len(chain) >= 3 else (chain[0] if chain else None)
    rows, pnl_c, pnl_g = {}, 0.0, 0.0
    for r in conn.execute(
            "SELECT l.account_id a, SUM(COALESCE(l.cash_debit,0)-COALESCE(l.cash_credit,0)) c,"
            " SUM(COALESCE(l.gold_debit,0)-COALESCE(l.gold_credit,0)) g"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " AND e.is_deleted=0 WHERE e.entry_date < ? GROUP BY l.account_id",
            (start,)):
        a = acc.get(r["a"])
        if not a:
            continue
        c, g = float(r["c"] or 0), float(r["g"] or 0)
        if a["type"] in ("revenue", "expense"):
            pnl_c += c
            pnl_g += g
            continue
        if a["type"] not in ("asset", "liability", "equity"):
            continue
        h = head(a["id"]) or a
        x = rows.setdefault(h["id"], {"code": h["code"], "name": h["name"],
                                      "type": h["type"], "cash": 0.0, "gold": 0.0})
        x["cash"] += c
        x["gold"] += g
    out = [dict(x, cash=round(x["cash"], 2), gold=round(x["gold"], 3))
           for x in sorted(rows.values(), key=lambda x: x["code"])
           if abs(x["cash"]) > 0.005 or abs(x["gold"]) > 0.0005]
    return {"year": int(year), "as_of": f"{int(year) - 1}-12-31", "rows": out,
            "unclosed_cash": round(-pnl_c, 2), "unclosed_gold": round(-pnl_g, 3),
            "prev_closed": is_closed(conn, int(year) - 1)}


def open_years(conn):
    return [y["year"] for y in years(conn) if not y["closed"]]


def next_to_close(conn):
    """أول سنةٍ مفتوحةٍ انتهت — هي التي تُقفل الآن (أو None)."""
    cur = _today().year
    for y in open_years(conn):
        if y < cur:
            return y
    return None


# ── السنة التي يعمل فيها المستخدم ──
def work_year(conn, username):
    v = fiscal.get_setting(conn, f"{WORK_KEY}:{username or ''}", "")
    try:
        y = int(str(v).strip())
        if 1990 <= y <= 2200:
            return y
    except ValueError:
        pass
    return _today().year


def set_work_year(conn, username, year):
    y = int(year)
    fiscal.set_setting(conn, f"{WORK_KEY}:{username or ''}", str(y), username)
    return y


# ── الإقفال ──
def check_close(conn, year):
    """ما يمنع إقفال السنة الآن (نصّ) — أو "" إن جاز."""
    y = int(year)
    if is_closed(conn, y):
        return f"سنة {y} مُقفلة من قبل."
    if y >= _today().year:
        return (f"سنة {y} لم تنتهِ بعد — تُقفل بعد 31-12-{y} "
                f"(في سنة {y + 1}).")
    earlier = [x for x in open_years(conn) if x < y]
    if earlier:
        return f"أقفل سنة {earlier[0]} أولاً — السنوات تُقفل بالترتيب."
    return ""


def close_year(conn, year, username, to_partners=False, backup=True):
    """يُقفل السنة ويبدأ التي بعدها:

    1. نسخةٌ احتياطية (قبل أي تغيير).
    2. قيد الإقفال بتاريخ 31-12: تصفير الإيرادات والمصروفات وترحيل الصافي
       (إن كان في السنة إيرادٌ أو مصروف).
    3. قفل السنة: لا يُقبل بعدها قيدٌ ولا تعديلٌ ولا حذفٌ بتاريخها.
    """
    from models import closing
    from services import desk_guard
    y = int(year)
    desk_guard.require(conn, f"إقفال سنة {y}")
    why = check_close(conn, y)
    if why:
        raise ValueError(why)
    bk = ""
    if backup:
        try:
            from services import storage
            bk = storage.make_backup(f"before_close_{y}") or ""
        except Exception:
            bk = ""
    prev = closing.year_end_preview(conn, y)
    res = None
    if prev["items"]:
        res = closing.run_year_end_closing(conn, y, username,
                                           to_partners=to_partners)
    fiscal.set_lock(conn, f"{y}-12-31", username)
    log_action(conn, username, "create", "fiscal_year", y,
               f"إقفال السنة المالية {y} وبدء {y + 1}"
               f" (صافي النتيجة: نقد {prev['net_cash']} · ذهب {prev['net_gold']})")
    return {"year": y, "next": y + 1, "backup": bk,
            "close_entry": res["close_entry"] if res else None,
            "net_cash": prev["net_cash"], "net_gold": prev["net_gold"],
            "accounts": len(prev["items"])}


def reopen_year(conn, year, username):
    """يفتح آخر سنةٍ مُقفلة للتصحيح (والتي قبلها تبقى مقفلة). وإقفالها
    ثانيةً يُرحّل ما تغيّر فقط."""
    from services import desk_guard
    y = int(year)
    desk_guard.require(conn, f"إعادة فتح سنة {y}")
    last = closed_through(conn)
    if last is None or y != last:
        raise ValueError("يُعاد فتح آخر سنةٍ مُقفلة وحدها"
                         + (f" (سنة {last})" if last else ""))
    earlier = y - 1
    keep = f"{earlier}-12-31" if earlier >= first_year(conn) else ""
    fiscal.set_lock(conn, keep, username)
    log_action(conn, username, "update", "fiscal_year", y,
               f"إعادة فتح السنة المالية {y} للتصحيح")
    return {"year": y, "lock": keep}
