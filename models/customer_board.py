# -*- coding: utf-8 -*-
"""لوحة العملاء — كم باع لكل عميل، وكم رجع، وكم سدّد، وكم بقي.

**السؤال**: كشف الحساب يجيب عن عميلٍ واحد، وأرصدة الجهات تعطي الباقي
وحده. والإدارة تسأل سؤالاً ثالثاً: **من يسدّد ومن يتأخّر؟** والجواب
يحتاج أربعة أرقامٍ متجاورة لكل عميل — المبيعات والمرتجع والسداد
والباقي — ونسبتين تقرأهما العين دون حساب.

**الذهب والنقد منفصلان**: ذهب العميل وزنٌ وأجوره ريال، ولا يُجمع
أحدهما إلى الآخر. فكل رقمٍ هنا زوجان.

**التصنيف من مصدر القيد لا من وصفه**:
    فاتورة بيع         → المبيعات
    فاتورة مرتجع       → المرتجع
    سند قبض            → السداد (صافي ما قيّده السند على الحساب،
                          ومعه ما منحه من خصم — فكلاهما يُطفئ الدين)
    رصيد افتتاحي       → رصيدٌ سابق
    كل ما عدا ذلك      → حركات أخرى (تثبيت، سند صرف، تسوية…)
فالمعادلة تُغلق دائماً:
    سابق + مبيعات − مرتجع − سداد + أخرى = الباقي
والباقي هو رصيد الحساب في دفتر الأستاذ بعينه — لا رقمٌ موازٍ له.

**أي حسابٍ من الشجرة**: العملاء المسجّلون يظهرون وحدهم، ويُضاف إليهم
ما يختاره المستخدم من دليل الحسابات (عميلٌ قديمٌ بلا بطاقة، أو حساب
وسيط…). والقائمة محفوظةٌ في القاعدة فتبقى بين الجلسات والأجهزة.

قراءةٌ محضة: لا تكتب قيداً ولا تغيّر رصيداً.
"""
import json
from datetime import date

from models import fiscal

EXTRA_KEY = "customer_board.accounts"

# مصادر الرصيد الافتتاحي — قيدٌ ينشأ مع الجهة أو مع فتح السنة
OPENING_SOURCES = ("entities", "opening", "opening_entry", "year_open")

KINDS = ("open", "sales", "returns", "paid", "other")


# ══════════════════════════════════════════════════════════════════
#  الحسابات المضافة من الشجرة
# ══════════════════════════════════════════════════════════════════

def extra_accounts(conn):
    """معرّفات الحسابات التي أضافها المستخدم — مرتّبةً كما أُضيفت."""
    try:
        raw = json.loads(fiscal.get_setting(conn, EXTRA_KEY, "[]") or "[]")
    except Exception:
        return []
    out = []
    for x in raw if isinstance(raw, list) else []:
        try:
            x = int(x)
        except Exception:
            continue
        if x not in out:
            out.append(x)
    return out


def _save_extra(conn, ids, username):
    fiscal.set_setting(conn, EXTRA_KEY, json.dumps(ids), username)


def add_account(conn, account_id, username=None):
    """يضيف حساباً من الشجرة إلى اللوحة. يُرجع اسمه."""
    a = conn.execute(
        "SELECT id, code, name, is_postable FROM accounts WHERE id=?",
        (account_id,)).fetchone()
    if not a:
        raise ValueError("الحساب غير موجود في الدليل")
    if not a["is_postable"]:
        raise ValueError(
            f"«{a['name']}» حسابٌ تجميعي لا تُقيَّد عليه حركة —\n"
            "اختر أحد الحسابات الفرعية تحته.")
    if account_id in _customer_accounts(conn):
        raise ValueError(f"«{a['name']}» عميلٌ مسجّل — ظاهرٌ في اللوحة أصلاً")
    ids = extra_accounts(conn)
    if account_id in ids:
        raise ValueError(f"«{a['name']}» مضافٌ مسبقاً")
    ids.append(int(account_id))
    _save_extra(conn, ids, username)
    return display_name(a["name"])


def remove_account(conn, account_id, username=None):
    """يُخرج حساباً مضافاً من اللوحة — لا يمسّ الحساب نفسه."""
    ids = [x for x in extra_accounts(conn) if x != int(account_id)]
    _save_extra(conn, ids, username)


PREFIXES = ("عميل:", "مورد:", "موظف:", "عامل:", "أخرى:", "شريك:")


def display_name(name):
    """اسم الحساب بلا بادئته الوصفية («أخرى: »، «مورد: »…) كما في الكشوف."""
    n = (name or "").strip()
    for p in PREFIXES:
        if n.startswith(p):
            return n[len(p):].strip() or n
    return n


def _customer_accounts(conn):
    return {r["account_id"] for r in conn.execute(
        "SELECT account_id FROM entities WHERE entity_type='customer'"
        " AND is_deleted=0 AND COALESCE(is_internal,0)=0").fetchall()}


# ══════════════════════════════════════════════════════════════════
#  اللوحة
# ══════════════════════════════════════════════════════════════════

def _members(conn):
    """العملاء المسجّلون ثم الحسابات المضافة — بلا تكرار."""
    out, seen = [], set()
    for r in conn.execute(
            "SELECT e.id eid, e.name, e.phone, e.account_id,"
            " COALESCE(e.credit_limit,0) lim_c,"
            " COALESCE(e.credit_limit_gold,0) lim_g, a.code"
            " FROM entities e JOIN accounts a ON a.id=e.account_id"
            " WHERE e.entity_type='customer' AND e.is_deleted=0"
            " AND COALESCE(e.is_internal,0)=0"
            " ORDER BY e.name").fetchall():
        if r["account_id"] in seen:
            continue
        seen.add(r["account_id"])
        out.append({"account_id": r["account_id"], "code": r["code"],
                    "name": r["name"], "phone": r["phone"] or "",
                    "entity_id": r["eid"], "added": False,
                    "limit_cash": float(r["lim_c"] or 0),
                    "limit_gold": float(r["lim_g"] or 0)})
    for aid in extra_accounts(conn):
        if aid in seen:
            continue
        a = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                         (aid,)).fetchone()
        if not a:
            continue
        seen.add(aid)
        out.append({"account_id": aid, "code": a["code"],
                    "name": display_name(a["name"]),
                    "phone": "", "entity_id": None, "added": True,
                    "limit_cash": 0.0, "limit_gold": 0.0})
    return out


def _pct(part, whole):
    return round(part / whole * 100.0, 1) if whole > 1e-9 else None


def _side(d, kind):
    """أرقام جانبٍ واحد (ذهب أو نقد) ونسبتاه."""
    x = {k: round(d.get(k, 0.0), 3 if kind == "gold" else 2) for k in KINDS}
    # **صافي المبيعات = رصيدٌ سابق + المبيعات − المرتجع**: الرصيد
    # السابق مبيعاتٌ عند العميل لم تُسدَّد بعد، فهو مما يُطالَب به
    # ويُقاس عليه سداده. ولو أُسقط لظهر من سدّد رصيده القديم كاملاً
    # بنسبةٍ فوق المئة، ومن لم يسدّد منه شيئاً بنسبةٍ لا تُنذر.
    x["net"] = round(x["open"] + x["sales"] - x["returns"], 3)
    x["remaining"] = round(x["net"] - x["paid"] + x["other"], 3)
    x["ret_pct"] = _pct(x["returns"], x["sales"])
    # والسداد من هذا الصافي: عميلٌ باع مئةً ورجع أربعين وسدّد ستين
    # قد سدّد كل ما عليه — ونسبته من الإجمالي (٦٠٪) تظلمه.
    x["paid_pct"] = _pct(x["paid"], x["net"])
    return x


def by_paid(rows, side="gold"):
    """الأعلى سداداً أولاً — بمبلغ السداد نفسه لا بنسبته.

    النسبة تُنصف الصغير: عميلٌ سدّد عشرة جرامات من عشرة نسبته ١٠٠٪،
    ومن سدّد خمسمئةٍ من ستمئة نسبته ٨٣٪ — والإدارة تريد الثاني أولاً،
    فهو من يُدخل الذهب والمال. والتعادل يُحسم بالجانب الآخر ثم بالاسم.
    """
    other = "cash" if side == "gold" else "gold"
    return sorted(rows, key=lambda r: (-r[side]["paid"], -r[other]["paid"],
                                       r["name"]))


def grade(paid_pct, remaining, has_sales, paid=0.0):
    """تقديرٌ هادئ بكلمةٍ واحدة — للإدارة لا للمحاسب."""
    if remaining <= 0.005:
        return "مسدَّد" if has_sales else "—"
    if paid_pct is None:
        # بلا مبيعاتٍ في الفترة لا نسبة: من سدّد شيئاً لا يُقال عنه
        # «لم يسدّد»، ودينُه من رصيدٍ سابق لا من بيعٍ يُقاس عليه
        return "لم يسدّد" if paid <= 0.005 else "—"
    if paid_pct >= 90:
        return "ممتاز"
    if paid_pct >= 70:
        return "جيد"
    if paid_pct >= 40:
        return "متابعة"
    return "متأخر"


def board(conn, date_from=None, date_to=None):
    """لوحة العملاء خلال الفترة. `date_from` فارغاً = منذ البداية.

    يُرجع {"rows": [...], "totals": {"gold": …, "cash": …},
    "date_from", "date_to"}. كل صف فيه جانبا "gold" و"cash" بالأرقام
    الخمسة والباقي والنسبتين، ومعها آخر بيعٍ وآخر سدادٍ وعدد الفواتير.
    """
    date_to = date_to or date.today().isoformat()
    date_from = date_from or ""
    members = _members(conn)
    if not members:
        return {"rows": [], "totals": {"gold": _side({}, "gold"),
                                       "cash": _side({}, "cash")},
                "date_from": date_from, "date_to": date_to}
    ids = [m["account_id"] for m in members]
    marks = ",".join("?" * len(ids))

    # تجميعٌ واحد: الحساب × الفئة × (قبل الفترة؟). والفئة من مصدر
    # القيد: الفاتورة بنوعها، والسند بنوعه، والافتتاحي، وما سواها.
    q = f"""
        SELECT l.account_id aid,
               CASE
                 WHEN e.source_table IN ({",".join("?" * len(OPENING_SOURCES))})
                      THEN 'open'
                 WHEN e.source_table='invoices' AND i.kind='sale'
                      THEN 'sales'
                 WHEN e.source_table='invoices' AND i.kind='sale_return'
                      THEN 'returns'
                 WHEN e.source_table='vouchers' AND v.kind='receipt'
                      THEN 'paid'
                 ELSE 'other'
               END cat,
               CASE WHEN e.entry_date < ? THEN 1 ELSE 0 END before,
               SUM(l.gold_debit - l.gold_credit) g,
               SUM(l.cash_debit - l.cash_credit) c,
               COUNT(DISTINCT e.id) n
        FROM journal_lines l
        JOIN journal_entries e ON e.id = l.entry_id
        LEFT JOIN invoices i ON e.source_table='invoices' AND i.id=e.source_id
        LEFT JOIN vouchers v ON e.source_table='vouchers' AND v.id=e.source_id
        WHERE e.is_deleted=0 AND l.account_id IN ({marks})
          AND e.entry_date <= ?
        GROUP BY aid, cat, before"""
    agg = {aid: {"gold": {}, "cash": {}, "n_sales": 0} for aid in ids}
    for r in conn.execute(q, (*OPENING_SOURCES, date_from, *ids,
                              date_to)).fetchall():
        a = agg[r["aid"]]
        g, c = float(r["g"] or 0), float(r["c"] or 0)
        cat = "open" if r["before"] else r["cat"]
        # المبيعات والرصيد مدينان بطبعهما، والمرتجع والسداد دائنان:
        # يُقلب الإشارة للدائنَين فيُعرض كلُّ رقمٍ موجباً كما يُقرأ.
        sign = -1.0 if cat in ("returns", "paid") else 1.0
        for side, v in (("gold", g), ("cash", c)):
            a[side][cat] = a[side].get(cat, 0.0) + sign * v
        if cat == "sales":
            a["n_sales"] += int(r["n"] or 0)

    # آخر بيعٍ وآخر سدادٍ حتى نهاية الفترة — من أي تاريخ
    last = {}
    for r in conn.execute(
            f"""SELECT l.account_id aid,
                   MAX(CASE WHEN e.source_table='invoices' AND i.kind='sale'
                            THEN e.entry_date END) ls,
                   MAX(CASE WHEN e.source_table='vouchers' AND v.kind='receipt'
                            THEN e.entry_date END) lp
            FROM journal_lines l
            JOIN journal_entries e ON e.id = l.entry_id
            LEFT JOIN invoices i ON e.source_table='invoices'
                                AND i.id=e.source_id
            LEFT JOIN vouchers v ON e.source_table='vouchers'
                                AND v.id=e.source_id
            WHERE e.is_deleted=0 AND l.account_id IN ({marks})
              AND e.entry_date <= ?
            GROUP BY aid""", (*ids, date_to)).fetchall():
        last[r["aid"]] = (r["ls"] or "", r["lp"] or "")

    try:
        end = date.fromisoformat(date_to)
    except Exception:
        end = date.today()

    rows = []
    tot = {"gold": {k: 0.0 for k in KINDS}, "cash": {k: 0.0 for k in KINDS}}
    for m in members:
        a = agg[m["account_id"]]
        gold, cash = _side(a["gold"], "gold"), _side(a["cash"], "cash")
        ls, lp = last.get(m["account_id"], ("", ""))
        try:
            days = (end - date.fromisoformat(lp)).days if lp else None
        except Exception:
            days = None
        for side, x in (("gold", gold), ("cash", cash)):
            x["grade"] = grade(x["paid_pct"], x["remaining"],
                               x["net"] > 0.005, x["paid"])
            for k in KINDS:
                tot[side][k] += x[k]
        active = any(abs(x[k]) > 0.0005 for x in (gold, cash) for k in KINDS)
        rows.append(dict(m, gold=gold, cash=cash, n_sales=a["n_sales"],
                         last_sale=ls, last_paid=lp, days_since_paid=days,
                         active=active,
                         avg_sale_gold=(round(gold["sales"] / a["n_sales"], 3)
                                        if a["n_sales"] else 0.0),
                         avg_sale_cash=(round(cash["sales"] / a["n_sales"], 2)
                                        if a["n_sales"] else 0.0)))
    return {"rows": by_paid(rows, "gold"),
            "totals": {"gold": _side(tot["gold"], "gold"),
                       "cash": _side(tot["cash"], "cash")},
            "date_from": date_from, "date_to": date_to}
