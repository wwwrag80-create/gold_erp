# -*- coding: utf-8 -*-
"""فهمُ القيد محاسبياً — ما الذي جرى لحسابٍ في قيدٍ بعينه؟

**السؤال**: قيدٌ يوميٌّ جعل محمداً مديناً بذهب، وجعل جهةً أخرى دائنةً
به. المستند لا يقول «بيع» ولا «مرتجع» — فالنظام كان يرمي الاثنين في
«حركات أخرى»، والمحاسب يرى ما جرى من أول نظرة: محمدٌ أخذ بضاعة
(مبيعاتٌ عنده)، والجهة الأخرى أعادتها (مرتجعٌ منها).

**الجواب من الحساب المقابل لا من اسم المستند**: كل سطرٍ على الحساب
يُقرأ باتجاهه (مدين/دائن) وبالحساب الذي قابله في القيد نفسه:

    الحساب المقابل                 مدين على الجهة     دائن للجهة
    ─────────────────────────────  ─────────────────  ─────────────────
    الأرصدة الافتتاحية (3900)      رصيد سابق           رصيد سابق
    جهة تعامل أخرى (عميل/مورد…)    مبيعات              مرتجع
    الذهب المشغول (بضاعة 1200)      مبيعات              مرتجع
    خزائن الذهب الأخرى (كسر…)       مبيعات              سداد (ذهبٌ سلّمه)
    النقدية (صندوق · بنك)           أخرى (صُرف له)      سداد
    الإيرادات / الضريبة             مبيعات              مرتجع
    المصروفات (خصمٌ مسموح…)         مبيعات (تحميل)      سداد (خصمٌ أطفأ دينه)
    ما سوى ذلك                      أخرى                أخرى

وإن قابل السطرَ أكثرُ من حساب قُسّم بحصصها — فقيدٌ دائنُه نصفه لجهةٍ
ونصفه للمخزون يُقرأ نصفُه مبيعاتٍ من الجهة ونصفه مبيعاتٍ من المخزون،
والمجموع كما هو.

**ما يُقرأ هكذا**: القيد اليومي (يدوي) والإشعار الضريبي. أما الفاتورة
والسند والتسكير فمستنداتٌ تقول نوعها بنفسها، فتبقى على نوعها.

قراءةٌ محضة — لا تكتب شيئاً.
"""
from models import opening as _opening

CATS = ("open", "sales", "returns", "paid", "other")
LABELS = {"open": "رصيد سابق", "sales": "مبيعات", "returns": "مرتجع",
          "paid": "سداد", "other": "أخرى"}
# وصف القيد اليومي في كشف الحساب بتصنيفه — «قيد يومي · مبيعات»
JOURNAL_LABELS = {"open": "افتتاحي", "sales": "مبيعات",
                  "returns": "مرتجع", "paid": "سداد", "other": ""}

# المصادر التي تُفهم من حسابها المقابل (لا نوعَ مستندٍ لها)
READ_SOURCES = (None, "", "manual", "tax_debit_notes")

CASH_GROUP = "1010"          # النقدية: الصندوق والبنك والنثرية
GOLD_GROUP = "1020"          # خزائن الذهب والمخازن
GOODS = "1200"               # الذهب المشغول — بضاعة تامة


def is_read_source(src):
    return (src or "") in ("", "manual", "tax_debit_notes")


class Kinds:
    """ذاكرةٌ مؤقتة لأنواع الحسابات وأسطر القيود — تُبنى مرةً لكل تقرير."""

    def __init__(self, conn):
        self.conn = conn
        from models.accounts import subtree_ids_by_code
        self.opening = set(_opening.opening_account_ids(conn))
        self.cash = set(subtree_ids_by_code(conn, CASH_GROUP) or [])
        self.goods = set(subtree_ids_by_code(conn, GOODS) or [])
        self.gold = set(subtree_ids_by_code(conn, GOLD_GROUP) or [])
        self.party = set()
        for r in conn.execute(
                "SELECT account_id, capital_account_id FROM entities"
                " WHERE is_deleted=0"):
            for k in ("account_id", "capital_account_id"):
                if r[k]:
                    self.party.add(r[k])
        self.types = {r["id"]: r["type"] for r in conn.execute(
            "SELECT id, type FROM accounts")}
        self._lines = {}

    # ── نوع الحساب المقابل ──
    def kind_of(self, account_id):
        if account_id in self.opening:
            return "opening"
        if account_id in self.party:
            return "party"
        if account_id in self.goods:
            return "goods"
        if account_id in self.gold:
            return "gold"
        if account_id in self.cash:
            return "cash"
        t = self.types.get(account_id)
        if t in ("revenue", "liability"):
            return "revenue"
        if t == "expense":
            return "expense"
        return "other"

    @staticmethod
    def cat_for(kind, debit, dim):
        """التصنيف من نوع المقابل واتجاه السطر على الجهة."""
        if kind == "opening":
            return "open"
        if kind in ("party", "goods", "revenue"):
            return "sales" if debit else "returns"
        if kind == "gold":
            return "sales" if debit else "paid"
        if kind == "cash":
            # نقدٌ خرج إليه: صرفٌ لا بيع. وذهبٌ خرج إليه من خزينةٍ
            # نقديةٍ لا يقع (الخزائن النقدية بلا ذهب) — فيُعامل بالمثل.
            return "other" if debit else "paid"
        if kind == "expense":
            return "sales" if debit else "paid"
        return "other"

    def lines(self, entry_id):
        if entry_id not in self._lines:
            self._lines[entry_id] = [dict(r) for r in self.conn.execute(
                "SELECT account_id, gold_debit gd, gold_credit gc,"
                " cash_debit cd, cash_credit cc FROM journal_lines"
                " WHERE entry_id=?", (entry_id,))]
        return self._lines[entry_id]

    def split(self, entry_id, account_ids):
        """أثر القيد على الحساب (أو مجموعة حسابات) مقسوماً بالتصنيف.

        يُرجع {"gold": {cat: صافي مدين−دائن}, "cash": {...}}. المجموع
        في كل بُعد = صافي حركة الحساب في القيد تماماً — فلا يضيع شيء.
        """
        own = set(account_ids if isinstance(account_ids, (set, list, tuple))
                  else [account_ids])
        ls = self.lines(entry_id)
        out = {"gold": {}, "cash": {}}
        for dim, dk, ck in (("gold", "gd", "gc"), ("cash", "cd", "cc")):
            s = sum(float(l[dk] or 0) - float(l[ck] or 0)
                    for l in ls if l["account_id"] in own)
            if abs(s) < 1e-9:
                continue
            debit = s > 0
            # المقابل: ما سار في الاتجاه المعاكس، بحصّته
            cps = []
            for l in ls:
                if l["account_id"] in own:
                    continue
                v = float(l[dk] or 0) - float(l[ck] or 0)
                if (debit and v < 0) or (not debit and v > 0):
                    cps.append((l["account_id"], abs(v)))
            total = sum(w for _, w in cps)
            if total <= 1e-12:
                out[dim]["other"] = out[dim].get("other", 0.0) + s
                continue
            for acc, w in cps:
                cat = self.cat_for(self.kind_of(acc), debit, dim)
                out[dim][cat] = out[dim].get(cat, 0.0) + s * w / total
        return out

    def main_cat(self, entry_id, account_ids):
        """التصنيف الغالب — لوصف السطر في كشف الحساب."""
        sp = self.split(entry_id, account_ids)
        acc = {}
        for dim, scale in (("gold", 1.0), ("cash", 0.001)):
            for c, v in sp[dim].items():
                acc[c] = acc.get(c, 0.0) + abs(v) * scale
        if not acc:
            return "other"
        return max(acc.items(), key=lambda kv: kv[1])[0]


def journal_label(base, cat):
    """«قيد يومي · مبيعات» — وصفٌ يقرؤه المحاسب كما يقرأ القيد."""
    extra = JOURNAL_LABELS.get(cat) or ""
    return f"{base} · {extra}" if extra else base


def opening_part(conn, account_id, date_from=None, date_to=None):
    """الرصيد الافتتاحي **الواقع في الفترة** على حساب — (ذهب، نقد).

    بالقاعدة نفسها التي تقرأ بها لوحة العملاء وتحليل الحركة: قيدٌ
    افتتاحيٌّ بمصدره يُحسب كلّه، والقيد اليومي بحصة ما قابل منه
    «الأرصدة الافتتاحية» وحدها.
    """
    cond, cp = _opening.sql(conn, "e", by_counter=False)
    clause, p = "", []
    if date_from:
        clause += " AND e.entry_date>=?"
        p.append(date_from)
    if date_to:
        clause += " AND e.entry_date<=?"
        p.append(date_to)
    r = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
        " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        f" WHERE e.is_deleted=0 AND l.account_id=? AND {cond}" + clause,
        [account_id] + cp + p).fetchone()
    g, c = float(r["g"] or 0), float(r["c"] or 0)
    kinds = None
    for e in conn.execute(
            "SELECT DISTINCT e.id FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0 AND l.account_id=?"
            " AND COALESCE(e.source_table,'') IN ('','manual','tax_debit_notes')"
            f" AND NOT {cond}" + clause,
            [account_id] + cp + p).fetchall():
        kinds = kinds or Kinds(conn)
        sp = kinds.split(e["id"], [account_id])
        g += sp["gold"].get("open", 0.0)
        c += sp["cash"].get("open", 0.0)
    return round(g, 3), round(c, 2)
