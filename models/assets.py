# -*- coding: utf-8 -*-
"""الأصول الثابتة والإهلاك — قسطٌ ثابتٌ شهري بقيدٍ آلي.

**الفجوة التي تسدّها**: كانت هذه الوحدة `NotImplementedError`. وفي
شجرة الحسابات مكائن ومعدات وسيارات وأثاث — تُشترى وتُقيَّد ثم **لا
تُهلَك أبداً**. وأثر ذلك يتراكم شهراً بعد شهر:

* **قائمة الدخل تبالغ في الربح**: الإهلاك مصروفٌ حقيقي لا يُدفع
  نقداً، فإغفاله يُظهر ربحاً لم يتحقّق — ويُوزَّع على الشركاء أو
  يُدفع عنه زكاةٌ وضريبة.
* **الميزانية تبالغ في الأصول**: مكينةٌ عمرها خمس سنوات تبقى في
  الدفتر بثمن شرائها إلى الأبد.

**القسط الثابت** — أبسط الطرق وأكثرها قبولاً:

    القسط الشهري = (التكلفة − القيمة التخريدية) ÷ عمرها بالأشهر

والقيد: **من حـ/ مصروف الإهلاك ٥٨٦٠ · إلى حـ/ مجمّع الإهلاك ١٧٩٠**.

**ولماذا مجمّعٌ لا إنقاصٌ من الأصل**: يبقى في الدفتر ما يطلبه أي
مراجع — التكلفة الأصلية، والمُهلَك حتى تاريخه، والصافي الدفتري. ولو
أُنقص الأصل مباشرةً ضاعت التكلفة ولم يُعرف عمر المكينة من دفترها.

**والسجل لا يُقيّد شراءً**: شراء المكينة مُقيَّدٌ أصلاً في المشتريات
أو القيود اليومية على حساب الأصل. فهذا الجدول **يصف** ما في الدفتر
ليُحسب منه الإهلاك — ولو قيَّد الشراء ثانيةً لتضاعفت الأصول. ولذلك
تُقارَن جملةُ السجل برصيد حسابات الأصول (`register_vs_ledger`) فيظهر
أي انحراف بدل أن يمرّ صامتاً.

**والشهر لا يُهلَك مرتين**: `period` مفتاحٌ فريد في
`depreciation_runs`، فإعادة التشغيل على الشهر نفسه تُعيد ما جرى ولا
تُنشئ قيداً ثانياً.
"""
from datetime import date

from models.accounts import acc_id
from services.accounting_engine import post_entry
from services.audit import log_action

ACC_ACCUM = "1790"        # مجمّع إهلاك الأصول الثابتة (مقابل، دائن)
ACC_EXPENSE = "5860"      # مصروف إهلاك الأصول الثابتة

# حسابات الأصول القابلة للإهلاك — فروع «الأصول الثابتة» ١٧٠٠،
# ما عدا المجمّع نفسه (فهو مقابلٌ لها لا أصلٌ يُهلَك).
ASSET_ROOT = "1700"


def depreciable_accounts(conn):
    """حسابات الأصول التي يُسجَّل تحتها أصلٌ قابل للإهلاك."""
    return [dict(r) for r in conn.execute(
        "WITH RECURSIVE tree(id) AS ("
        "   SELECT id FROM accounts WHERE code=?"
        "   UNION ALL"
        "   SELECT a.id FROM accounts a JOIN tree t ON a.parent_id=t.id)"
        " SELECT a.id, a.code, a.name FROM accounts a JOIN tree t ON t.id=a.id"
        " WHERE a.is_active=1 AND a.is_postable=1 AND a.code<>?"
        " ORDER BY a.code", (ASSET_ROOT, ACC_ACCUM))]


# ══════════════════════════════════════════════════════════════════
#  السجل
# ══════════════════════════════════════════════════════════════════

def add_asset(conn, name, account_id, cost, life_months, start_date,
              salvage=0.0, notes="", username="admin"):
    """يسجّل أصلاً في السجل — بلا قيد.

    التحقّقات ليست شكلية: عمرٌ صفرٌ يقسم على صفر، وقيمةٌ تخريدية تفوق
    التكلفة تعطي قسطاً سالباً يُنقص المصروف — وكلاهما يمرّ صامتاً لو
    لم يُمنع هنا.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("اكتب اسم الأصل")
    cost = round(float(cost or 0), 2)
    salvage = round(float(salvage or 0), 2)
    life_months = int(life_months or 0)
    if cost <= 0:
        raise ValueError("تكلفة الأصل يجب أن تكون أكبر من صفر")
    if life_months <= 0:
        raise ValueError("العمر الإنتاجي بالأشهر يجب أن يكون أكبر من صفر")
    if salvage < 0:
        raise ValueError("القيمة التخريدية لا تكون سالبة")
    if salvage >= cost:
        raise ValueError(
            "القيمة التخريدية يجب أن تقلّ عن التكلفة — وإلا فلا شيء "
            "يُهلَك")
    if not conn.execute("SELECT 1 FROM accounts WHERE id=? AND is_postable=1",
                        (account_id,)).fetchone():
        raise ValueError("اختر حساب الأصل من شجرة الأصول الثابتة")
    cur = conn.execute(
        "INSERT INTO fixed_assets(name, account_id, cost, salvage,"
        " life_months, start_date, purchase_date, notes, created_by)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (name, account_id, cost, salvage, life_months, start_date,
         start_date, (notes or "").strip(), username))
    aid = cur.lastrowid
    log_action(conn, username, "create", "fixed_assets", aid,
               f"تسجيل أصل: {name} — تكلفة {cost:,.2f} · "
               f"عمر {life_months} شهراً")
    return aid


def monthly_amount(cost, salvage, life_months):
    """القسط الشهري بالقسط الثابت."""
    life_months = int(life_months or 0)
    if life_months <= 0:
        return 0.0
    return round((float(cost or 0) - float(salvage or 0)) / life_months, 2)


def _period_key(d):
    """'YYYY-MM' من تاريخٍ نصيّ أو كائن تاريخ."""
    s = str(d)
    return s[:7]


def _months_between(start, period):
    """عدد الأشهر من بداية الإهلاك حتى نهاية `period` (شاملاً)."""
    try:
        sy, sm = int(str(start)[:4]), int(str(start)[5:7])
        py, pm = int(period[:4]), int(period[5:7])
    except (ValueError, IndexError):
        return 0
    return (py - sy) * 12 + (pm - sm) + 1


def accumulated(conn, asset_id):
    """ما أُهلك فعلاً من هذا الأصل — من القيود لا من الحساب النظري."""
    r = conn.execute(
        "SELECT COALESCE(SUM(dl.amount),0) t FROM depreciation_lines dl"
        " JOIN depreciation_runs dr ON dr.id=dl.run_id"
        " WHERE dl.asset_id=?", (asset_id,)).fetchone()
    return round(float(r["t"] or 0), 2)


def list_assets(conn, include_disposed=False):
    """السجل مع المُهلَك والصافي الدفتري لكل أصل."""
    sql = ("SELECT f.*, COALESCE(f.start_date, f.purchase_date) begins,"
           "       COALESCE(a.code,'1700') acc_code,"
           "       COALESCE(a.name,'الأصول الثابتة') acc_name"
           "  FROM fixed_assets f"
           "  LEFT JOIN accounts a ON a.id=f.account_id"
           " WHERE f.is_deleted=0")
    if not include_disposed:
        sql += " AND f.is_disposed=0"
    out = []
    for r in conn.execute(sql + " ORDER BY f.start_date, f.id"):
        d = dict(r)
        d["monthly"] = monthly_amount(d["cost"], d["salvage"],
                                      d["life_months"])
        d["accumulated"] = accumulated(conn, d["id"])
        d["net_book"] = round(float(d["cost"]) - d["accumulated"], 2)
        d["depreciable"] = round(float(d["cost"]) - float(d["salvage"]), 2)
        d["remaining"] = round(d["depreciable"] - d["accumulated"], 2)
        d["done"] = d["remaining"] <= 0.005
        out.append(d)
    return out


def due_amount(conn, asset, period):
    """قسط هذا الأصل في هذا الشهر — صفرٌ إن لم يحن أو اكتمل.

    **آخر قسطٍ يأخذ الكسر**: القسمة تترك فلوساً معلّقة، فلو أُخذ القسط
    الثابت في كل شهرٍ لبقي الأصل غير مُهلَكٍ بالكامل أو زاد عن قيمته.
    فيُحدّ القسط بما بقي — فينتهي المجمّع عند القيمة القابلة للإهلاك
    بالضبط.
    """
    # عمرٌ غير محدَّد ⇒ لا يُهلَك: أصلٌ اشتُري من شاشة المشتريات ولم
    # يُكتب عمره بعد. تُبرزه الشاشة ليُستدرك لا ليُهلَك بالتخمين.
    if int(asset.get("life_months") or 0) <= 0:
        return 0.0
    if asset["is_disposed"] or _period_key(asset["begins"]) > period:
        return 0.0
    remaining = round(float(asset["cost"]) - float(asset["salvage"])
                      - accumulated(conn, asset["id"]), 2)
    if remaining <= 0.005:
        return 0.0
    m = monthly_amount(asset["cost"], asset["salvage"], asset["life_months"])
    return round(min(m, remaining), 2)


def preview(conn, period):
    """ما سيُهلَك في هذا الشهر — قبل الترحيل."""
    period = str(period)[:7]
    rows = []
    for a in list_assets(conn):
        amt = due_amount(conn, a, period)
        if amt > 0:
            rows.append({"asset_id": a["id"], "name": a["name"],
                         "acc_code": a["acc_code"], "amount": amt,
                         "cost": a["cost"],
                         "accumulated": a["accumulated"]})
    return rows


def run_for_period(conn, period):
    """تشغيلُ شهرٍ إن كان قد جرى — وإلا None."""
    r = conn.execute("SELECT * FROM depreciation_runs WHERE period=?",
                     (str(period)[:7],)).fetchone()
    return dict(r) if r else None


def run_depreciation(conn, period, username="admin"):
    """يرحّل إهلاك الشهر بقيدٍ واحد مجمّع — ولا يكرّره.

    قيدٌ واحد لكل الأصول لا قيدٌ لكل أصل: الدفتر يُقرأ، ومئةُ قيدٍ
    شهرياً لأجل الإهلاك تُغرق كشف الحساب. والتفصيل محفوظٌ في
    `depreciation_lines` فلا يضيع.
    """
    period = str(period)[:7]
    if len(period) != 7 or period[4] != "-":
        raise ValueError("الشهر يُكتب هكذا: 2026-01")
    done = run_for_period(conn, period)
    if done:
        return {"period": period, "entry_id": done["entry_id"],
                "total": round(float(done["total"] or 0), 2),
                "lines": 0, "already": True}

    rows = preview(conn, period)
    total = round(sum(r["amount"] for r in rows), 2)
    if not rows or total <= 0:
        raise ValueError(
            f"لا يوجد ما يُهلَك في {period} — إما لم يبدأ عمر أي أصل "
            "بعد، أو اكتمل إهلاكها كلها.")

    # آخر يومٍ في الشهر: الإهلاك عن الشهر كاملاً فتاريخه منتهاه
    y, m = int(period[:4]), int(period[5:7])
    last = (date(y + (m == 12), (m % 12) + 1, 1)
            - __import__("datetime").timedelta(days=1)).isoformat()

    entry_id = post_entry(
        conn, last, f"إهلاك شهر {period}",
        [{"account_id": acc_id(conn, ACC_EXPENSE), "cash_debit": total},
         {"account_id": acc_id(conn, ACC_ACCUM), "cash_credit": total}],
        source_table="depreciation", username=username,
        note=f"إهلاك {len(rows)} أصلاً عن شهر {period}")

    cur = conn.execute(
        "INSERT INTO depreciation_runs(period, entry_id, total, created_by)"
        " VALUES(?,?,?,?)", (period, entry_id, total, username))
    run_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO depreciation_lines(run_id, asset_id, amount)"
        " VALUES(?,?,?)",
        [(run_id, r["asset_id"], r["amount"]) for r in rows])
    conn.execute("UPDATE journal_entries SET source_id=? WHERE id=?",
                 (run_id, entry_id))
    try:
        from models import integrity
        integrity.mark(conn, entry_id)
    except Exception:
        pass
    log_action(conn, username, "create", "depreciation", run_id,
               f"إهلاك شهر {period}: {total:,.2f} على {len(rows)} أصلاً")
    return {"period": period, "entry_id": entry_id, "total": total,
            "lines": len(rows), "already": False}


def register_vs_ledger(conn):
    """جملة السجل مقابل رصيد حسابات الأصول — وأي انحراف بينهما.

    السجل يصف ما في الدفتر ولا يكتبه، فقد يفترقان: أصلٌ اشتُري وقُيّد
    ولم يُسجَّل فلا يُهلَك، أو سُجّل ولم يُقيَّد فيُهلَك ما ليس في
    الدفتر. الفرق يُعرض ليُصحَّح لا ليُكتشف بعد سنة.
    """
    reg = conn.execute(
        "SELECT COALESCE(SUM(cost),0) t FROM fixed_assets"
        " WHERE is_deleted=0 AND is_disposed=0").fetchone()["t"]
    led = conn.execute(
        "WITH RECURSIVE tree(id) AS ("
        "   SELECT id FROM accounts WHERE code=?"
        "   UNION ALL"
        "   SELECT a.id FROM accounts a JOIN tree t ON a.parent_id=t.id)"
        " SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) t"
        " FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id"
        " JOIN accounts a ON a.id=l.account_id"
        " WHERE a.id IN (SELECT id FROM tree) AND a.code<>?"
        "   AND e.is_deleted=0", (ASSET_ROOT, ACC_ACCUM)).fetchone()["t"]
    reg = round(float(reg or 0), 2)
    led = round(float(led or 0), 2)
    return {"register": reg, "ledger": led, "difference": round(led - reg, 2)}


def totals(conn):
    """إجماليات السجل: التكلفة والمُهلَك والصافي."""
    rows = list_assets(conn)
    cost = round(sum(float(r["cost"]) for r in rows), 2)
    acc = round(sum(r["accumulated"] for r in rows), 2)
    return {"count": len(rows), "cost": cost, "accumulated": acc,
            "net_book": round(cost - acc, 2),
            "monthly": round(sum(r["monthly"] for r in rows
                                 if not r["done"]), 2),
            # أصولٌ في الدفتر بلا عمرٍ إنتاجي — لا تُهلَك حتى يُكتب
            "unset": sum(1 for r in rows
                         if int(r.get("life_months") or 0) <= 0)}


def dispose_asset(conn, asset_id, on_date, username="admin"):
    """يوقف إهلاك أصلٍ خرج من الخدمة — بلا قيد.

    البيع أو الشطب قيدٌ يكتبه المحاسب بنفسه (فقد يكون بربح أو خسارة،
    وبمقابلٍ نقديٍّ أو بلا مقابل)، وهذا يوقف القسط فحسب فلا يستمرّ
    النظام يُهلك ما لم يعد موجوداً.
    """
    r = conn.execute("SELECT name FROM fixed_assets WHERE id=?",
                     (asset_id,)).fetchone()
    if not r:
        raise ValueError("الأصل غير موجود")
    conn.execute(
        "UPDATE fixed_assets SET is_disposed=1, disposed_on=? WHERE id=?",
        (on_date, asset_id))
    log_action(conn, username, "update", "fixed_assets", asset_id,
               f"إخراج أصل من الخدمة: {r['name']} بتاريخ {on_date}")
    return True


def schedule(conn, asset_id):
    """جدول ما أُهلك من هذا الأصل شهراً بشهر."""
    return [dict(r) for r in conn.execute(
        "SELECT dr.period, dl.amount, dr.entry_id"
        "  FROM depreciation_lines dl"
        "  JOIN depreciation_runs dr ON dr.id=dl.run_id"
        " WHERE dl.asset_id=? ORDER BY dr.period", (asset_id,))]
