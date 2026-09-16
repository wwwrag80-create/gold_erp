# -*- coding: utf-8 -*-
"""نموذج لوحات لوحة التحكم.

**الفكرة**: بدل بطاقات ثابتة يحددها المبرمج، يبني المستخدم لوحاته
بنفسه — كل لوحة عنوان وتحته مجموعة حسابات من الدليل. النقر على اللوحة
يفتح جدولها كاملاً: كل حساب بمدينه ودائنه ورصيده، وصف إجمالي أسفله.

**الأساس المحاسبي**: اللوحة تجميع **عرضي** لا محاسبي — لا تُنشئ حساباً
ولا قيداً، بل تعرض أرصدة حسابات قائمة. فتغييرها لا يمسّ أي ميزان.
"""
import json
from pathlib import Path

# اللوحات الافتراضية عند أول تشغيل
DEFAULTS = [
    {"key": "boxes", "title": "الصناديق",
     "accounts": ["1400", "1500", "1100"], "unit": "cash"},
    {"key": "loss", "title": "الذهب الفاقد",
     "accounts": ["5110"]},
    {"key": "sales", "title": "المبيعات",
     "accounts": ["4110", "4120", "1600"], "unit": "gold"},
    {"key": "scrap", "title": "صندوق الكسر",
     "accounts": ["1310"], "kind": "scrap"},
]


def _cfg_path():
    import config
    d = Path(str(config.DB_PATH)).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "dashboard_panels.json"


def load_panels():
    """لوحات المستخدم — أو الافتراضية عند أول تشغيل."""
    try:
        p = _cfg_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                out = []
                for d in data:
                    if not isinstance(d, dict) or not d.get("title"):
                        continue
                    out.append({
                        "key": d.get("key") or d["title"],
                        "title": d["title"],
                        "accounts": [str(x) for x in
                                     (d.get("accounts") or [])],
                        "kind": d.get("kind") or "accounts",
                        # أشرطة النسب: كل شريط اسم وحسابان
                        "ratios": list(d.get("ratios") or []),
                        # نطاق التاريخ المحفوظ لهذه اللوحة
                        "date_from": d.get("date_from") or "",
                        "date_to": d.get("date_to") or "",
                        # وحدة الرقم المعروض على واجهة اللوحة
                        "unit": d.get("unit") or "gold",
                    })
                if out:
                    return out
    except Exception:
        pass
    return [dict(x) for x in DEFAULTS]


def save_panels(panels):
    try:
        _cfg_path().write_text(
            json.dumps(panels, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return True
    except Exception:
        return False


def _subtree_ids(conn, code):
    """الحساب وكل فروعه — استعلام واحد (انظر models/accounts.py)."""
    from models.accounts import subtree_ids_by_code
    return subtree_ids_by_code(conn, code)


def account_rows(conn, codes, date_from=None, date_to=None):
    """صفوف الجدول: كل حساب بمدينه ودائنه ورصيده (ذهباً ونقداً).

    المدين والدائن **مجموع الحركة** لا الرصيد — فيرى المستخدم حجم
    النشاط على الحساب لا محصّلته وحدها.
    """
    out = []
    for code in codes:
        ids = _subtree_ids(conn, code)
        if not ids:
            continue
        acc = conn.execute("SELECT code, name FROM accounts WHERE code=?",
                           (code,)).fetchone()
        qs = ",".join("?" * len(ids))
        p = list(ids)
        clause = ""
        if date_from:
            clause += " AND e.entry_date>=?"
            p.append(date_from)
        if date_to:
            clause += " AND e.entry_date<=?"
            p.append(date_to)
        r = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit),0) gd,"
            " COALESCE(SUM(l.gold_credit),0) gc,"
            " COALESCE(SUM(l.cash_debit),0) cd,"
            " COALESCE(SUM(l.cash_credit),0) cc"
            " FROM journal_lines l JOIN journal_entries e"
            "  ON e.id=l.entry_id"
            f" WHERE e.is_deleted=0 AND l.account_id IN ({qs})" + clause,
            p).fetchone()
        gd, gc = round(r["gd"] or 0, 3), round(r["gc"] or 0, 3)
        cd, cc = round(r["cd"] or 0, 2), round(r["cc"] or 0, 2)
        out.append({
            "code": acc["code"], "name": acc["name"],
            "gold_debit": gd, "gold_credit": gc,
            "gold_balance": round(gd - gc, 3),
            "cash_debit": cd, "cash_credit": cc,
            "cash_balance": round(cd - cc, 2),
        })
    return out


def ratio_bars(rows, ratios):
    """يحسب أشرطة النسب أسفل الجدول.

    **المعنى المحاسبي**: النسبة = رصيد الحساب الثاني ÷ رصيد الأول.
    تُعرض أسفل الجدول لا فيه، لأنها **مؤشر** لا رصيد — إدراجها بين
    الصفوف يُفسد الإجمالي.
    """
    by_code = {r["code"]: r for r in rows}
    out = []
    for spec in (ratios or []):
        a = str(spec.get("first") or "")
        b = str(spec.get("second") or "")
        ra, rb = by_code.get(a), by_code.get(b)
        # البعد يُختار تلقائياً: الذهب إن كان للمقام رصيد ذهبي،
        # وإلا النقد — فلا تظهر النسبة فارغة لحسابات نقدية بحتة.
        ga = float(ra["gold_balance"]) if ra else 0.0
        gb = float(rb["gold_balance"]) if rb else 0.0
        ca = float(ra["cash_balance"]) if ra else 0.0
        cb = float(rb["cash_balance"]) if rb else 0.0
        forced = str(spec.get("dim") or "").lower()
        if forced == "cash" or (forced != "gold" and abs(ga) < 1e-9
                                and abs(ca) > 1e-9):
            va, vb, unit = ca, cb, "ريال"
        else:
            va, vb, unit = ga, gb, "جم"
        # نمط النسبة:
        #   مباشرة (direct): الثاني ÷ الأول    → 8÷10 = 80%
        #   عكسية  (inverse): الفرق ÷ الأول    → (10-8)÷10 = 20%
        mode = str(spec.get("mode") or "direct").lower()
        # ══ النسبة تُحسب بالقيم المطلقة ══
        # إشارة الرصيد تدلّ على طبيعة الحساب (مدين أو دائن) لا على
        # مقداره. حساب العملاء دائن بطبعه والمخزون مدين، فقسمة أحدهما
        # على الآخر بإشارتهما تُنتج نسبة سالبة لا معنى لها. المقصود
        # نسبة **الحجم** لا اتجاه الرصيد.
        aa, ab = abs(va), abs(vb)
        if aa > 1e-9:
            pct = ((ab / aa * 100) if mode != "inverse"
                   else (abs(aa - ab) / aa * 100))
        else:
            pct = None
        out.append({
            "title": spec.get("title") or f"{b} ÷ {a}",
            "first": a, "second": b, "unit": unit,
            "first_name": ra["name"] if ra else a,
            "second_name": rb["name"] if rb else b,
            "first_value": round(va, 3), "second_value": round(vb, 3),
            "mode": mode,
            "pct": (round(pct, 2) if pct is not None else None),
        })
    return out


def totals(rows):
    return {
        "gold_debit": round(sum(r["gold_debit"] for r in rows), 3),
        "gold_credit": round(sum(r["gold_credit"] for r in rows), 3),
        "gold_balance": round(sum(r["gold_balance"] for r in rows), 3),
        "cash_debit": round(sum(r["cash_debit"] for r in rows), 2),
        "cash_credit": round(sum(r["cash_credit"] for r in rows), 2),
        "cash_balance": round(sum(r["cash_balance"] for r in rows), 2),
    }


def scrap_rows(conn):
    """صفوف صندوق الكسر: كل عيار بوزنه الفعلي ومكافئه بعيار 18.

    الصندوق حساب واحد (1310) يضمّ الأعيرة الأربعة. الرصيد المحاسبي
    بمكافئ 18 دائماً، والوزن الفعلي لكل عيار يُقرأ من سجل الحركات
    الوزنية — فيُعرف كم في الصندوق فعلياً من كل عيار.
    """
    import config
    from models.inventory import scrap_actuals
    actual = scrap_actuals(conn)
    from services.gold_math import to_base_karat
    out = []
    for k in config.KARATS:
        w = round(float(actual.get(k, 0) or 0), 3)
        out.append({"karat": k, "actual": w,
                    "eq18": round(to_base_karat(w, k), 3)})
    return out


# ══════════════════════════════════════════════════════════════════
#  مقارنة فترتين
# ------------------------------------------------------------------
#  رقم الفترة وحده لا يقول إن كان النشاط يصعد أو يهبط. المقارنة
#  بالفترة السابقة **المساوية لها طولاً** هي ما يحوّل الرقم إلى خبر.
# ══════════════════════════════════════════════════════════════════

def previous_period(date_from, date_to):
    """الفترة السابقة المساوية في الطول، المنتهية قبل بداية الحالية.

    فترة 1–31 يناير تُقارَن بـ1–31 ديسمبر لا بشهر تقويمي ناقص: طول
    الفترتين يجب أن يتساوى وإلا كانت المقارنة كذباً مهذّباً.
    """
    import datetime as _dt
    try:
        d1 = _dt.date.fromisoformat(str(date_from)[:10])
        d2 = _dt.date.fromisoformat(str(date_to)[:10])
    except Exception:
        return None, None
    if d2 < d1:
        d1, d2 = d2, d1
    span = (d2 - d1).days
    p2 = d1 - _dt.timedelta(days=1)
    p1 = p2 - _dt.timedelta(days=span)
    return p1.isoformat(), p2.isoformat()


def _pct(cur, prev):
    """نسبة التغيّر. `None` حين لا معنى لها (القسمة على صفر)."""
    if abs(prev) < 1e-9:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 1)


def compare_rows(conn, codes, date_from, date_to):
    """صفوف اللوحة مع نظيرتها من الفترة السابقة والفرق والنسبة.

    المقارنة على **حجم الحركة** (المدين والدائن) لا على الرصيد
    التراكمي: الرصيد يحمل تاريخ ما قبل الفترة كله، فمقارنته بفترة
    أخرى تقارن أعماراً لا نشاطاً.
    """
    p1, p2 = previous_period(date_from, date_to)
    cur = {r["code"]: r for r in account_rows(conn, codes, date_from,
                                              date_to)}
    prev = ({r["code"]: r for r in account_rows(conn, codes, p1, p2)}
            if p1 else {})
    out = []
    for code in codes:
        c = cur.get(code)
        if not c:
            continue
        p = prev.get(code) or {"gold_debit": 0.0, "gold_credit": 0.0,
                               "cash_debit": 0.0, "cash_credit": 0.0,
                               "gold_balance": 0.0, "cash_balance": 0.0}
        cur_g = round(c["gold_debit"] + c["gold_credit"], 3)
        prev_g = round(p["gold_debit"] + p["gold_credit"], 3)
        cur_c = round(c["cash_debit"] + c["cash_credit"], 2)
        prev_c = round(p["cash_debit"] + p["cash_credit"], 2)
        out.append({
            "code": code, "name": c["name"],
            "gold": cur_g, "gold_prev": prev_g,
            "gold_diff": round(cur_g - prev_g, 3),
            "gold_pct": _pct(cur_g, prev_g),
            "cash": cur_c, "cash_prev": prev_c,
            "cash_diff": round(cur_c - prev_c, 2),
            "cash_pct": _pct(cur_c, prev_c),
        })
    return {"rows": out, "from": p1, "to": p2}


def compare_totals(rows):
    """إجمالي المقارنة — صف الإجمالي أسفل الجدول."""
    cg = round(sum(r["gold"] for r in rows), 3)
    pg = round(sum(r["gold_prev"] for r in rows), 3)
    cc = round(sum(r["cash"] for r in rows), 2)
    pc = round(sum(r["cash_prev"] for r in rows), 2)
    return {"gold": cg, "gold_prev": pg, "gold_diff": round(cg - pg, 3),
            "gold_pct": _pct(cg, pg),
            "cash": cc, "cash_prev": pc, "cash_diff": round(cc - pc, 2),
            "cash_pct": _pct(cc, pc)}
