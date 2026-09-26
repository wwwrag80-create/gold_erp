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
    تسكير              → السداد بذهبه، وقيمته النقدية مبيعاتٌ بالنقد
    رصيد افتتاحي       → رصيدٌ سابق (بطاقة الجهة، أرصدة أول المدة…)
    قيد يومي           → **يُقرأ بحسابه المقابل** (models.entry_kind):
                          مدينٌ مقابل جهةٍ أو بضاعة = مبيعات، دائنٌ
                          مقابلها = مرتجع، دائنٌ مقابل صندوقٍ أو خزينة
                          أو خصم = سداد، مقابل «الأرصدة الافتتاحية» =
                          رصيدٌ سابق — والمقسوم يُقسم بحصصه
    كل ما عدا ذلك      → حركات أخرى (سند صرف، تسوية…) — مسمّاةً
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
from models import entry_kind as _ek
from models import opening as _opening

EXTRA_KEY = "customer_board.accounts"

# مصادر الرصيد الافتتاحي وحسابه المقابل — القاعدة في `models.opening`
OPENING_SOURCES = _opening.OPENING_SOURCES

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
    # نسبة المرتجع من **كل ما خرج إليه**: رصيدٌ سابق + مبيعات. فالرصيد
    # السابق بضاعةٌ عنده كالمبيعات، ويُرجَع منها كما يُرجَع من المبيعات
    x["ret_pct"] = _pct(x["returns"], x["open"] + x["sales"])
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


GRADES = ("مسدَّد", "ممتاز", "جيد", "سيء")


def grade(paid_pct, remaining, has_sales, paid=0.0):
    """تقديرٌ بكلمةٍ واحدة من أربع لا غير: مسدَّد · ممتاز · جيد · سيء.

    مسدَّد: لا شيء عليه. ممتاز: سدّد ٩٠٪ فأكثر من صافي مبيعاته. جيد:
    ٧٠٪ فأكثر. وما دون ذلك — أو عليه رصيدٌ ولم يسدّد منه شيئاً — سيء.
    ومن لا حركة له ولا رصيد لا يُقدَّر («—»).
    """
    if remaining <= 0.005:
        return "مسدَّد" if has_sales or paid > 0.005 else "—"
    if paid_pct is not None and paid_pct >= 90:
        return "ممتاز"
    if paid_pct is not None and paid_pct >= 70:
        return "جيد"
    return "سيء"


def _other_label(sub):
    """اسم ما وقع في «حركات أخرى» — ليُفصَّل ولا يبقى مجهولاً."""
    src, _, kind = (sub or ":").partition(":")
    if src == "vouchers":
        return "صرف" if kind == "payment" else "سند"
    if src in ("", "manual"):
        return "قيد يومي"
    from models.journal import OP_LABELS
    return OP_LABELS.get(src, src)


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

    # **القيد الافتتاحي** بمصدره (بطاقة الجهة، أرصدة أول المدة، فتح
    # السنة…). والقيد اليومي لا يُحكم عليه جملةً: يُقرأ بحساباته
    # المقابلة (`models.entry_kind`) — فما قابل «الأرصدة الافتتاحية»
    # رصيدٌ سابق، وما قابل جهةً أخرى مبيعاتٌ أو مرتجع، وما قابل
    # الصندوق سداد.
    open_cond, open_params = _opening.sql(conn, "e", by_counter=False)
    read_src = ",".join("?" * 2)
    # تجميعٌ واحد: الحساب × الفئة × (قبل الفترة؟) × المصدر. والقيد
    # المقروء بحساباته يبقى قيداً قيداً (`reid`) ليُقسَّم بحصصه.
    q = f"""
        SELECT aid, cat, before, sub,
               CASE WHEN cat='read' AND before=0 THEN eid ELSE 0 END reid,
               SUM(g) g, SUM(c) c, COUNT(DISTINCT eid) n, MAX(d) d
        FROM (
          SELECT l.account_id aid, e.id eid, e.entry_date d,
                 CASE
                   WHEN {open_cond} THEN 'open'
                   WHEN e.source_table='invoices' AND i.kind='sale'
                        THEN 'sales'
                   WHEN e.source_table='invoices' AND i.kind='sale_return'
                        THEN 'returns'
                   WHEN e.source_table='vouchers' AND v.kind='receipt'
                        THEN 'paid'
                   WHEN e.source_table='fixing_ops' THEN 'fixing'
                   WHEN COALESCE(e.source_table,'') IN ('', {read_src})
                        THEN 'read'
                   ELSE 'other'
                 END cat,
                 COALESCE(e.source_table,'') || ':' || COALESCE(v.kind,'')
                   sub,
                 CASE WHEN e.entry_date < ? THEN 1 ELSE 0 END before,
                 l.gold_debit - l.gold_credit g,
                 l.cash_debit - l.cash_credit c
          FROM journal_lines l
          JOIN journal_entries e ON e.id = l.entry_id
          LEFT JOIN invoices i ON e.source_table='invoices'
                              AND i.id=e.source_id
          LEFT JOIN vouchers v ON e.source_table='vouchers'
                              AND v.id=e.source_id
          WHERE e.is_deleted=0 AND l.account_id IN ({marks})
            AND e.entry_date <= ?)
        GROUP BY aid, cat, before, sub, reid"""
    agg = {aid: {"gold": {}, "cash": {}, "n_sales": 0, "fix_cash": 0.0,
                 "other_parts": {"gold": {}, "cash": {}},
                 "ls": "", "lp": ""} for aid in ids}
    kinds = _ek.Kinds(conn)

    def _add(a, cat, g, c, sub=""):
        # المبيعات والرصيد مدينان بطبعهما، والمرتجع والسداد دائنان:
        # يُقلب الإشارة للدائنَين فيُعرض كلُّ رقمٍ موجباً كما يُقرأ.
        sign = -1.0 if cat in ("returns", "paid") else 1.0
        for side, v in (("gold", g), ("cash", c)):
            if not v:
                continue
            a[side][cat] = a[side].get(cat, 0.0) + sign * v
            if cat == "other":
                lbl = _other_label(sub)
                parts = a["other_parts"][side]
                parts[lbl] = parts.get(lbl, 0.0) + v

    for r in conn.execute(q, (*open_params, *_ek.READ_SOURCES[2:],
                              date_from, *ids, date_to)).fetchall():
        a = agg[r["aid"]]
        g, c = float(r["g"] or 0), float(r["c"] or 0)
        if r["before"]:
            _add(a, "open", g, c)
            continue
        cat = r["cat"]
        if cat == "read":
            # القيد يُقسَّم بحساباته المقابلة — والمجموع كما هو
            sp = kinds.split(r["reid"], [r["aid"]])
            cats = set(sp["gold"]) | set(sp["cash"])
            for k in cats:
                _add(a, k, sp["gold"].get(k, 0.0), sp["cash"].get(k, 0.0),
                     "manual:")
            if "sales" in cats:
                a["n_sales"] += 1
                a["ls"] = max(a["ls"], r["d"] or "")
            if "paid" in cats:
                a["lp"] = max(a["lp"], r["d"] or "")
            continue
        if cat == "fixing":
            # **التسكير سداد**: ذهبُ العميل سُوّي بسعره فانطفأ دينُه
            # الذهبي — فشقُّه الذهبي في «السداد». وشقُّه النقدي قيمةُ
            # ذلك الذهب صارت عليه نقداً: مبيعاتٌ بالنقد، فيُقاس عليها
            # سدادُه النقدي حين يدفعها (ولولا ذلك لظهرت نسبة سداد
            # النقد فوق المئة لمن دفع قيمة تسكيره).
            _add(a, "paid", g, 0.0)
            _add(a, "sales", 0.0, c)
            a["fix_cash"] += c
            a["lp"] = max(a["lp"], r["d"] or "")
            continue
        _add(a, cat, g, c, r["sub"] or "")
        if cat == "sales":
            a["n_sales"] += int(r["n"] or 0)
            a["ls"] = max(a["ls"], r["d"] or "")
        elif cat == "paid":
            a["lp"] = max(a["lp"], r["d"] or "")

    # آخر بيعٍ وآخر سدادٍ حتى نهاية الفترة — من أي تاريخ (وما قبل
    # الفترة يُحمل رصيداً، فتاريخه يُقرأ هنا من المستندات)
    for r in conn.execute(
            f"""SELECT l.account_id aid,
                   MAX(CASE WHEN e.source_table='invoices' AND i.kind='sale'
                            THEN e.entry_date END) ls,
                   MAX(CASE WHEN (e.source_table='vouchers'
                                  AND v.kind='receipt')
                              OR e.source_table='fixing_ops'
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
        a = agg[r["aid"]]
        a["ls"] = max(a["ls"], r["ls"] or "")
        a["lp"] = max(a["lp"], r["lp"] or "")
    last = {aid: (a["ls"], a["lp"]) for aid, a in agg.items()}

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
        for side, x in (("gold", gold), ("cash", cash)):
            x["other_parts"] = {
                k: round(v, 3 if side == "gold" else 2)
                for k, v in a["other_parts"][side].items()
                if abs(v) > 0.0005}
        rows.append(dict(m, gold=gold, cash=cash, n_sales=a["n_sales"],
                         last_sale=ls, last_paid=lp, days_since_paid=days,
                         active=active,
                         avg_sale_gold=(round(gold["sales"] / a["n_sales"], 3)
                                        if a["n_sales"] else 0.0),
                         # متوسط الفاتورة من الفواتير: قيمة التسكير
                         # ليست فاتورة فلا تُضخّم متوسطها
                         avg_sale_cash=(round((cash["sales"] - a["fix_cash"])
                                              / a["n_sales"], 2)
                                        if a["n_sales"] else 0.0)))
    return {"rows": by_paid(rows, "gold"),
            "totals": {"gold": _side(tot["gold"], "gold"),
                       "cash": _side(tot["cash"], "cash")},
            "date_from": date_from, "date_to": date_to}


# ══════════════════════════════════════════════════════════════════
#  تفصيل الحركة — لماذا وقع كل قيدٍ في عموده؟
# ══════════════════════════════════════════════════════════════════

def detail(conn, account_id, date_from=None, date_to=None):
    """حركة الحساب قيداً قيداً، ومع كل قيدٍ العمودُ الذي حُسب فيه.

    **لماذا**: اللوحة أرقامٌ مجمّعة، ومن رأى «مرتجع ٥ جم» لعميلٍ لم
    يُرجع فاتورةً يحتاج أن يرى القيد الذي صُنّف كذلك — وبأي حسابٍ قابله.
    فتُعرض كل حركة بعمودها، والقيد اليومي المقسوم بين عمودين سطرين،
    والمجاميع تساوي أرقام اللوحة بالضبط (مفحوصٌ في smoke_flow).

    يُرجع {"rows": [...], "totals": {cat: {"gold", "cash"}}}.
    """
    from models import journal
    date_to = date_to or date.today().isoformat()
    rows = journal.statement(conn, [int(account_id)], date_from or None,
                             date_to)
    kinds = _ek.Kinds(conn)
    open_ids = _opening.entry_ids(conn, [r["eid"] for r in rows
                                         if r["op"] != "رصيد سابق"],
                                  by_counter=False)
    out = []
    totals = {k: {"gold": 0.0, "cash": 0.0} for k in KINDS}

    def _put(r, cat, g, c, why):
        if abs(g) < 0.0005 and abs(c) < 0.005:
            return
        totals[cat]["gold"] += g
        totals[cat]["cash"] += c
        out.append({"date": str(r["date"])[:10], "op": r["op"],
                    "doc_no": r.get("doc_no") or "",
                    "name": r.get("name") or "—",
                    "desc": r.get("desc") or "", "eid": r["eid"],
                    "cat": cat, "cat_label": _ek.LABELS[cat],
                    "gold": round(g, 3), "cash": round(c, 2), "why": why})

    for r in rows:
        g = float(r["gd"] or 0) - float(r["gc"] or 0)
        c = float(r["cd"] or 0) - float(r["cc"] or 0)
        if r["op"] == "رصيد سابق":
            _put(r, "open", float(r["gbal"] or 0), float(r["cbal"] or 0),
                 "رصيد الحساب قبل بداية الفترة")
            continue
        src = r.get("src") or ""
        if r["eid"] in open_ids:
            _put(r, "open", g, c, "قيدٌ افتتاحي بمصدره")
            continue
        if _ek.is_read_source(src):
            sp = kinds.split(r["eid"], [int(account_id)])
            for cat in KINDS:
                pg = pc = 0.0
                for dim, v in (("gold", g), ("cash", c)):
                    tot = sum(sp[dim].values())
                    if abs(tot) > 1e-12 and v:
                        amt = sp[dim].get(cat, 0.0) * v / tot
                        if dim == "gold":
                            pg = amt
                        else:
                            pc = amt
                _put(r, cat, pg, pc, _why(cat, pg or pc))
            continue
        if src == "invoices":
            cat = "returns" if "مرتجع" in (r["op"] or "") else "sales"
            why = "فاتورة " + ("مرتجع" if cat == "returns" else "بيع")
        elif src == "vouchers" and r["op"] == "قبض":
            cat, why = "paid", "سند قبض"
        elif src == "fixing_ops":
            _put(r, "paid", g, 0.0, "تسكير: ذهبٌ سُوّي بسعره — سداد")
            _put(r, "sales", 0.0, c, "تسكير: قيمة الذهب المسكَّر نقداً")
            continue
        else:
            cat = "other"
            why = r["op"] or "حركة"
        _put(r, cat, g, c, why)

    # المرتجع والسداد يُعرضان موجبَين في اللوحة — وكذا مجموعهما هنا
    for k in ("returns", "paid"):
        totals[k] = {d: -v for d, v in totals[k].items()}
    for k in totals:
        totals[k] = {"gold": round(totals[k]["gold"], 3),
                     "cash": round(totals[k]["cash"], 2)}
    return {"rows": out, "totals": totals}


def _why(cat, v):
    """سبب تصنيف القيد اليومي — بلغة المحاسب."""
    debit = v > 0
    return {
        "open": "قيدٌ يومي مقابل «الأرصدة الافتتاحية»",
        "sales": "قيدٌ يومي: صار مديناً مقابل جهةٍ أو بضاعةٍ أو إيراد",
        "returns": "قيدٌ يومي: صار دائناً مقابل جهةٍ أو بضاعةٍ",
        "paid": "قيدٌ يومي: صار دائناً مقابل صندوقٍ أو خزينةٍ أو خصم",
        "other": ("قيدٌ يومي: صُرف له من الصندوق" if debit
                  else "قيدٌ يومي مقابل حسابٍ لا يُصنَّف"),
    }.get(cat, "")
