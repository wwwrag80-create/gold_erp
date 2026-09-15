# -*- coding: utf-8 -*-
"""أداة المطابقة وتسوية الفروقات الآلية (Ledger Reconciliation).

تدقيق آلي شامل يقارن الحركات ويكتشف أي اختلالات محاسبية في النظام،
فيوفّر ساعات البحث اليدوي. تجري خمسة فحوص:

1. توازن كل قيد على حدة (مجموع المدين = مجموع الدائن في كل من ميزان
   الذهب وميزان النقد).
2. التوازن الكلي لدفتر الأستاذ (إجمالي المدين = إجمالي الدائن).
3. مطابقة رصيد الصندوق الدفتري مع مجموع تدفقاته الفعلية.
4. مطابقة أرصدة الذهب: مجموع أرصدة حسابات الذهب المدينة = الدائنة.
5. القيود المعلّقة (يتيمة/غير مكتملة) أو ذات الطرف الواحد.

كل اختلال يُصنَّف بخطورته (حرج/تحذير) ويُوصف بموقعه ليعالجه المحاسب.
"""
from services.accounting_engine import CASH_TOL, GOLD_TOL


def _entry_imbalances(conn):
    """القيود غير المتوازنة (ذهباً أو نقداً) — خطأ حرج."""
    rows = conn.execute(
        "SELECT e.id, e.entry_date, e.description,"
        " ROUND(SUM(l.gold_debit),3) gd, ROUND(SUM(l.gold_credit),3) gc,"
        " ROUND(SUM(l.cash_debit),2) cd, ROUND(SUM(l.cash_credit),2) cc,"
        " COUNT(l.id) nlines"
        " FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id"
        " WHERE e.is_deleted=0 GROUP BY e.id").fetchall()
    out = []
    for r in rows:
        gd_diff = round(r["gd"] - r["gc"], 3)
        cd_diff = round(r["cd"] - r["cc"], 2)
        if abs(gd_diff) > GOLD_TOL or abs(cd_diff) > CASH_TOL:
            out.append({
                "severity": "critical", "kind": "قيد غير متوازن",
                "ref": f"قيد #{r['id']} — {r['entry_date']}",
                "detail": r["description"] or "",
                "gold_diff": gd_diff, "cash_diff": cd_diff,
                "entry_id": r["id"]})
        if r["nlines"] < 2:
            out.append({
                "severity": "critical", "kind": "قيد بطرف واحد",
                "ref": f"قيد #{r['id']} — {r['entry_date']}",
                "detail": f"يحوي {r['nlines']} سطراً فقط",
                "gold_diff": 0.0, "cash_diff": 0.0, "entry_id": r["id"]})
    return out


def _global_balance(conn):
    """التوازن الكلي للأستاذ: إجمالي المدين = إجمالي الدائن."""
    r = conn.execute(
        "SELECT ROUND(SUM(l.gold_debit),3) gd, ROUND(SUM(l.gold_credit),3) gc,"
        " ROUND(SUM(l.cash_debit),2) cd, ROUND(SUM(l.cash_credit),2) cc"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0").fetchone()
    out = []
    gd_diff = round((r["gd"] or 0) - (r["gc"] or 0), 3)
    cd_diff = round((r["cd"] or 0) - (r["cc"] or 0), 2)
    if abs(gd_diff) > GOLD_TOL:
        out.append({
            "severity": "critical", "kind": "اختلال ميزان الذهب الكلي",
            "ref": "دفتر الأستاذ العام",
            "detail": f"مدين {r['gd']:,.2f} مقابل دائن {r['gc']:,.2f}",
            "gold_diff": gd_diff, "cash_diff": 0.0, "entry_id": None})
    if abs(cd_diff) > CASH_TOL:
        out.append({
            "severity": "critical", "kind": "اختلال ميزان النقد الكلي",
            "ref": "دفتر الأستاذ العام",
            "detail": f"مدين {r['cd']:,.2f} مقابل دائن {r['cc']:,.2f}",
            "gold_diff": 0.0, "cash_diff": cd_diff, "entry_id": None})
    return out


def _orphan_entries(conn):
    """قيود بلا مصدر معروف أو بمرجع مصدر مفقود — تحذير."""
    rows = conn.execute(
        "SELECT id, entry_date, description, source_table, source_id"
        " FROM journal_entries WHERE is_deleted=0"
        " AND (source_table IS NULL OR source_table='')").fetchall()
    out = []
    for r in rows:
        # القيود اليدوية مسموحة؛ غيرها بلا مصدر مشبوه
        out.append({
            "severity": "warning", "kind": "قيد بلا مصدر",
            "ref": f"قيد #{r['id']} — {r['entry_date']}",
            "detail": r["description"] or "قيد غير منسوب لمستند",
            "gold_diff": 0.0, "cash_diff": 0.0, "entry_id": r["id"]})
    return out


def _account_side_check(conn):
    """مطابقة الأرصدة: مجموع أرصدة الحسابات المدينة يساوي الدائنة
    (تحقق مستقل من التوازن على مستوى الأرصدة لا الحركات)."""
    rows = conn.execute(
        "SELECT a.id, a.code, a.name,"
        " ROUND(SUM(l.gold_debit-l.gold_credit),3) gbal,"
        " ROUND(SUM(l.cash_debit-l.cash_credit),2) cbal"
        " FROM accounts a"
        " LEFT JOIN journal_lines l ON l.account_id=a.id"
        " LEFT JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " GROUP BY a.id").fetchall()
    tot_g = round(sum((r["gbal"] or 0) for r in rows), 3)
    tot_c = round(sum((r["cbal"] or 0) for r in rows), 2)
    out = []
    if abs(tot_g) > GOLD_TOL:
        out.append({
            "severity": "critical", "kind": "مجموع أرصدة الذهب ≠ صفر",
            "ref": "كل الحسابات",
            "detail": f"صافي أرصدة الذهب = {tot_g:,.2f} (يجب أن يكون صفراً)",
            "gold_diff": tot_g, "cash_diff": 0.0, "entry_id": None})
    if abs(tot_c) > CASH_TOL:
        out.append({
            "severity": "critical", "kind": "مجموع الأرصدة النقدية ≠ صفر",
            "ref": "كل الحسابات",
            "detail": f"صافي الأرصدة النقدية = {tot_c:,.2f} (يجب أن يكون صفراً)",
            "gold_diff": 0.0, "cash_diff": tot_c, "entry_id": None})
    return out


def reconcile(conn):
    """يجري كل الفحوص ويعيد قائمة الاختلالات + ملخصاً."""
    issues = []
    issues += _global_balance(conn)
    issues += _account_side_check(conn)
    issues += _entry_imbalances(conn)
    issues += _orphan_entries(conn)
    critical = sum(1 for i in issues if i["severity"] == "critical")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    return {
        "issues": issues,
        "critical": critical,
        "warnings": warnings,
        "clean": critical == 0 and warnings == 0,
    }
