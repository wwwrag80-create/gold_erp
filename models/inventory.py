# -*- coding: utf-8 -*-
"""المخازن: خزينة التصنيع، الذهب المشغول (الأطقم)، صناديق الكسر."""
import config
from models.accounts import acc_id
from services import gold_math
from services.accounting_engine import account_balance, post_entry
from services.audit import log_action
from services.barcode_service import generate_work_order_barcode

# ══ صناديق الكسر ══
# الأعيرة 18/21/22 تُرحَّل كلها إلى **حساب واحد** (1310 صندوق الكسر)
# بمكافئ 18 — فكشف حساب واحد يعرض كل العمليات. وعيار 24 (الصافي)
# يبقى منفصلاً لأنه ذهب خام مختلف الطبيعة والتسعير.
SCRAP_ACCOUNT = "1310"           # صندوق الكسر الموحّد (18·21·22·24)
# الصافي 24 دُمج في صندوق الكسر: كلاهما ذهب خام يُوزن ويُصفّى، وفصلهما
# كان يفرض متابعة رصيدين لبضاعة واحدة. الحساب واحد الآن، والتفصيل
# بالعيار يبقى كاملاً في `scrap_moves` — فلا تُفقد أي معلومة.
PURE_ACCOUNT = SCRAP_ACCOUNT

BOX_CODE = {18: SCRAP_ACCOUNT, 21: SCRAP_ACCOUNT, 22: SCRAP_ACCOUNT,
            24: SCRAP_ACCOUNT}
BULK_WO_NO = "0001"   # رقم تشغيل محجوز: رصيد تجميعي بالوزن، بلا قطع فردية


def classify_item(wo_no, gold, small_stones, big_stones):
    """التصنيف الآلي لنوع الطقم بحسب مكوّناته:

    * رقم التشغيل 0001            → إيطالي (مباشرة).
    * يحتوي على أحجار (كبيرة)     → أحجار.
    * ذهب وفصوص (صغيرة) فقط       → زركون.
    * ذهب فقط                     → ألماس.
    """
    if str(wo_no).strip() == BULK_WO_NO:
        return "إيطالي"
    if (big_stones or 0) > 0:
        return "أحجار"
    if (small_stones or 0) > 0:
        return "زركون"
    return "ألماس"


def get_or_create_bulk_wo(conn, username):
    """يضمن وجود رقم التشغيل التجميعي 0001 كسجل واحد ثابت — لا يُنشأ من
    جديد أبداً، بل يزيد وينقص رصيده الوزني عبر التوريد/البيع/المرتجع."""
    wo = get_wo_by_no(conn, BULK_WO_NO)
    if wo:
        return wo
    conn.execute(
        "INSERT INTO work_orders(work_order_no,gross_weight,stones_weight,"
        "gold_weight,small_stones,big_stones,stones_after_discount,"
        "standing_gold,discount_rate,registered_weight,wage_per_gram,is_bulk,"
        "notes,created_by) VALUES(?,0,0,0,0,0,0,0,0,0,?,1,?,?)",
        (BULK_WO_NO, config.DEFAULT_WAGE_PER_GRAM,
         "رصيد تجميعي بالوزن — لا يمثل قطعة مفردة", username))
    return get_wo_by_no(conn, BULK_WO_NO)


def adjust_bulk_wo(conn, delta_weight, username):
    """يزيد/ينقص رصيد الرقم التجميعي 0001 (موجب = توريد أو مرتجع، سالب
    = بيع) — يبقى الرقم «بالمخزون» دوماً بغض النظر عن رصيده."""
    wo = get_or_create_bulk_wo(conn, username)
    # الرصيد السالب مسموح: الرقم التجميعي **رصيد وزني** لا قطعة
    # مفردة، وخروج بضاعة قبل تسجيل توريدها حالة واقعية. الرصيد
    # السالب يظهر في الكشف فيُصحَّح لاحقاً، والقيد المزدوج يبقى
    # متوازناً على أي حال — فالمنع كان يدفع لتسجيل وهمي أسوأ.
    new_reg = round(wo["registered_weight"] + delta_weight, 3)
    conn.execute(
        "UPDATE work_orders SET registered_weight=?, gold_weight=?,"
        " standing_gold=?, status='in_stock' WHERE id=?",
        (new_reg, new_reg, new_reg, wo["id"]))
    return get_wo_by_no(conn, BULK_WO_NO)


def next_wo_no(conn) -> str:
    row = conn.execute("SELECT COALESCE(MAX(id),0) m FROM work_orders").fetchone()
    return str(1000 + row["m"] + 1)


def get_wo_by_no(conn, no: str):
    return conn.execute(
        "SELECT * FROM work_orders WHERE work_order_no=? AND is_deleted=0",
        (no.strip(),)).fetchone()


def create_work_order(conn, wo_no, gold, small_stones, big_stones,
                      discount_rate, notes, username, entry_date):
    """توريد طقم: من حـ/الذهب المشغول إلى حـ/خزينة التصنيع بالوزن المقيد.
    الوزن المقيد = الذهب + الفصوص + الأحجار بعد الخصم (هو وحده صاحب
    الأثر المالي والمخزني). الذهب القائم للإحصاء فقط."""
    res = create_work_orders_batch(
        conn, [{"wo_no": wo_no, "gold": gold, "small_stones": small_stones,
                "big_stones": big_stones, "discount_rate": discount_rate,
                "notes": notes}], entry_date, username)
    item = res["items"][0]
    item["entry_id"] = res["entry_id"]
    return item


def create_work_orders_batch(conn, rows, entry_date, username):
    """توريد دفعة أطقم (إدخال مجمّع من الشاشة Master-Detail) بقيد محاسبي
    مجمّع واحد: سطر مدين 1200 واحد بإجمالي الوزن المقيد للدفعة كلها /
    سطر دائن 1100 واحد بنفس الإجمالي — ليظهر الأثر في كشف كل حساب
    كرقم إجمالي واحد للعملية بدل سطر منفصل لكل طقم.
    الرقم التجميعي 0001 حالة خاصة: لا يُنشأ من جديد، بل يزيد رصيده
    الوزني القائم فقط (رصيد تراكمي وليس قطعة مفردة).
    rows: [{"wo_no","gold","small_stones","big_stones","discount_rate",
            "wage_per_gram","notes"}, ...]
    """
    if not rows:
        raise ValueError("أضف طقماً واحداً على الأقل قبل الترحيل")
    prepared = []
    for r in rows:
        wo_no = (r.get("wo_no") or "").strip()
        gold = float(r.get("gold", 0) or 0)
        small = float(r.get("small_stones", 0) or 0)
        big = float(r.get("big_stones", 0) or 0)
        rate = r.get("discount_rate", config.STONE_DISCOUNT_RATE)
        # ملاحظة: الأجر صفر قيمة **صحيحة** (تشغيل بلا أجر). استخدام `or`
        # يعامله كغياب فيستبدله بالافتراضي — لذلك نفحص None صراحةً.
        _wg = r.get("wage_per_gram")
        wage = float(config.DEFAULT_WAGE_PER_GRAM if _wg is None or _wg == ""
                     else _wg)
        model_no = str(r.get("model_no") or "").strip() or None
        if not wo_no:
            raise ValueError("رقم تشغيل فارغ في أحد أسطر الدفعة")
        if gold < 0 or small < 0 or big < 0:
            raise ValueError(f"الأوزان لا تقبل السالب للطقم {wo_no}")
        if gold + small + big <= 0:
            raise ValueError(f"أدخل وزناً صحيحاً للطقم {wo_no}")
        if not 0 <= rate <= 1:
            raise ValueError(f"نسبة الخصم غير منطقية للطقم {wo_no}")
        # الأجر صفر مقبول محاسبياً (تشغيل بلا أجر أو أجر يُحدَّد لاحقاً)،
        # لكن السالب خطأ إدخال.
        if wage < 0:
            raise ValueError(f"أجر الجرام لا يكون سالباً — الطقم {wo_no}")
        is_bulk = wo_no == BULK_WO_NO
        if any(p["wo_no"] == wo_no for p in prepared):
            # الرقم التجميعي 0001 يقبل التكرار: رصيد وزني مجمّع لا
            # قطعة مفردة، فتعدد سطوره في الدفعة الواحدة طبيعي.
            if wo_no != BULK_WO_NO:
                raise ValueError(
                    f"رقم التشغيل {wo_no} مكرر داخل نفس الدفعة")
        if not is_bulk and conn.execute(
                "SELECT 1 FROM work_orders WHERE work_order_no=?"
                " AND is_deleted=0",
                (wo_no,)).fetchone():
            raise ValueError(f"رقم التشغيل {wo_no} مستخدم مسبقاً")
        after = gold_math.stones_after_discount(big, rate)
        reg = gold_math.registered_weight(gold, small, big, rate)
        standing = gold_math.standing_gold(gold, small, big)
        item_type = (r.get("item_type") or "").strip() or classify_item(
            wo_no, gold, small, big)
        prepared.append({"model_no": model_no,
                         "wo_no": wo_no, "gold": gold, "small": small,
                         "big": big, "after": after, "reg": reg,
                         "standing": standing, "rate": rate, "wage": wage,
                         "is_bulk": is_bulk, "item_type": item_type,
                         "notes": r.get("notes", "")})

    total_reg = round(sum(p["reg"] for p in prepared), 3)
    n = len(prepared)
    lines = [
        {"account_id": acc_id(conn, "1200"), "gold_debit": total_reg,
         "line_desc": f"توريد دفعة ({n} طقم) — إجمالي الوزن المقيد"},
        {"account_id": acc_id(conn, "1100"), "gold_credit": total_reg,
         "line_desc": f"صرف لدفعة إنتاج ({n} طقم)"},
    ]
    entry_id = post_entry(
        conn, entry_date, f"توريد دفعة أطقم مجمّعة ({n} طقم)", lines,
        source_table="work_orders", username=username)

    created = []
    for p in prepared:
        if p["is_bulk"]:
            wo = adjust_bulk_wo(conn, p["reg"], username)
            conn.execute("UPDATE work_orders SET wage_per_gram=?,"
                         " entry_id=? WHERE id=?",
                         (p["wage"], entry_id, wo["id"]))
            log_action(conn, username, "update", "work_orders", wo["id"],
                      f"bulk +{p['reg']}")
            created.append({"id": wo["id"], "work_order_no": BULK_WO_NO,
                            "registered_weight": p["reg"],
                            "standing_gold": p["reg"],
                            "barcode_path": None, "is_bulk": True})
            continue
        barcode_path = generate_work_order_barcode(p["wo_no"])
        cur = conn.execute(
            "INSERT INTO work_orders(model_no,work_order_no,gross_weight,"
            "stones_weight,"
            "gold_weight,small_stones,big_stones,item_type,"
            "stones_after_discount,"
            "standing_gold,discount_rate,registered_weight,wage_per_gram,"
            "barcode_path,notes,entry_id,created_by)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p.get("model_no"),
             p["wo_no"], p["standing"], round(p["small"] + p["big"], 3),
             p["gold"], p["small"], p["big"], p["item_type"], p["after"],
             p["standing"], p["rate"], p["reg"], p["wage"], barcode_path,
             p["notes"], entry_id, username))
        wo_id = cur.lastrowid
        log_action(conn, username, "create", "work_orders", wo_id,
                   f"reg={p['reg']}")
        created.append({"id": wo_id, "work_order_no": p["wo_no"],
                        "registered_weight": p["reg"],
                        "standing_gold": p["standing"],
                        "barcode_path": barcode_path, "is_bulk": False})
    # ربط القيد بأول طقم في الدفعة: بدونه يبقى `source_id` فارغاً
    # فلا يعرف كشف الحساب أي مستند يفتح عند التعديل أو المعاينة.
    if created:
        conn.execute(
            "UPDATE journal_entries SET source_id=? WHERE id=?",
            (created[0]["id"], entry_id))

    # حفظ حصة كل سطر كما أُدخلت — تُقرأ عند التعديل بدل رصيد
    # الطقم التراكمي (يهمّ خصوصاً الرقم التجميعي 0001).
    for i, (p_, c_) in enumerate(zip(prepared, created)):
        conn.execute(
            "INSERT INTO wo_batch_lines(entry_id,work_order_id,model_no,"
            "wo_no,gold,small_stones,big_stones,discount_rate,"
            "registered_weight,wage_per_gram,notes,seq)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry_id, c_["id"], p_.get("model_no"), p_["wo_no"],
             p_["gold"], p_["small"], p_["big"], p_["rate"],
             p_["reg"], p_.get("wage", 0), p_.get("notes", ""), i))

    return {"entry_id": entry_id, "total_registered": total_reg,
            "items": created}


def list_in_stock(conn):
    return conn.execute(
        "SELECT * FROM work_orders WHERE is_deleted=0 AND status='in_stock'"
        " ORDER BY id DESC").fetchall()


def search_work_orders(conn, q="", date_from=None, date_to=None, limit=200):
    sql = "SELECT * FROM work_orders WHERE is_deleted=0"
    params = []
    if q:
        sql += " AND work_order_no LIKE ?"; params.append(f"%{q}%")
    if date_from:
        sql += " AND date(created_at)>=?"; params.append(date_from)
    if date_to:
        sql += " AND date(created_at)<=?"; params.append(date_to)
    sql += " ORDER BY id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


def add_scrap_move(conn, karat, actual_delta, ref_table, ref_id):
    conn.execute(
        "INSERT INTO scrap_moves(karat,actual_delta,ref_table,ref_id) VALUES(?,?,?,?)",
        (karat, actual_delta, ref_table, ref_id))


def scrap_actuals(conn):
    """الأوزان الفعلية الحالية بكل عيار في صناديق الكسر.

    المصدر الأساسي جدول `scrap_moves` (يغذّيه السندات والصب والجرد).
    لكن **القيود اليدوية** تُحرّك حساب الصندوق مباشرةً بلا مرور به،
    فيظهر المكافئ 18 في لوحة التحكم بلا وزن فعلي بعياره — وهو نقص في
    العرض لا في المحاسبة.

    لذلك نكمل النقص من الحساب نفسه: الفرق بين رصيد الحساب (مكافئ 18)
    وما يفسّره `scrap_moves` يُحوَّل لعياره الأصلي ويُضاف. فيظهر
    للمستخدم الوزن بعياره والمكافئ معاً كما يتوقّع.
    """
    out = {k: 0.0 for k in config.KARATS}
    for r in conn.execute(
            "SELECT karat, COALESCE(SUM(actual_delta),0) w FROM scrap_moves"
            " WHERE is_deleted=0 GROUP BY karat"):
        if r["karat"] in out:
            out[r["karat"]] = round(r["w"], config.WEIGHT_DECIMALS)

    # إكمال ما لم يُسجَّل في scrap_moves (القيود اليدوية).
    # الحسابات موحّدة (18/21/22 في حساب واحد)، فنقارن رصيد **الحساب**
    # بمجموع ما تفسّره حركات أعيرته مجتمعةً — لا كل عيار على حدة،
    # وإلا نُسب الرصيد الكامل لكل عيار فتضاعف الجرد.
    by_account = {}
    for k in config.KARATS:
        code = BOX_CODE.get(k)
        if code:
            by_account.setdefault(code, []).append(k)
    for code, karats in by_account.items():
        try:
            ledger18, _ = account_balance(conn, acc_id(conn, code))
        except Exception:
            continue
        explained18 = round(sum(gold_math.to_base_karat(out[k], k)
                                for k in karats if out[k]), 3)
        gap18 = round(ledger18 - explained18, 3)
        # الفجوة = حركة لم تمرّ بجدول الكسر (قيد يدوي). تُنسب لعيار
        # الأساس 18 لأن عيارها الأصلي غير معروف.
        if abs(gap18) > 0.01:
            base = (config.BASE_KARAT if config.BASE_KARAT in karats
                    else karats[0])
            out[base] = round(out[base] + gap18 * config.BASE_KARAT / base,
                              config.WEIGHT_DECIMALS)
    return out


def stock_snapshot(conn):
    """الجرد اللحظي لكل المخازن (دفتري + فعلي)."""
    actual = scrap_actuals(conn)
    # رصيد الحساب يُقرأ **مرة واحدة لكل حساب** لا لكل عيار، وإلا
    # ظهر الرصيد الموحّد مكرراً أمام كل عيار فبدا الجرد مضاعفاً.
    acc_bal = {}
    for code in set(BOX_CODE.values()):
        try:
            acc_bal[code], _ = account_balance(conn, acc_id(conn, code))
        except Exception:
            acc_bal[code] = 0.0
    boxes = []
    for k in config.KARATS:
        # المكافئ 18 لهذا العيار من وزنه الفعلي (لا رصيد الحساب كله)
        boxes.append((k, actual[k], gold_math.to_base_karat(actual[k], k)))
    scrap_total = round(acc_bal.get(SCRAP_ACCOUNT, 0.0), 3)
    pure_total = round(acc_bal.get(PURE_ACCOUNT, 0.0), 3)
    wo = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(registered_weight),0) w FROM work_orders"
        " WHERE is_deleted=0 AND status='in_stock'").fetchone()
    return {
        "scrap_total18": scrap_total,      # صندوق الكسر الموحّد
        "pure_total18": pure_total,        # صندوق الصافي 24
        "tazeena_gold": account_balance(conn, acc_id(conn, "1100"))[0],
        "mashghool_gold": account_balance(conn, acc_id(conn, "1200"))[0],
        "wo_count": wo["c"], "wo_weight": round(wo["w"], 3),
        "boxes": boxes,
        "cash_box": account_balance(conn, acc_id(conn, "1400"))[1],
        "bank": account_balance(conn, acc_id(conn, "1500"))[1],
    }


def opening_stock_batch(conn, rows, entry_date, username):
    """رصيد افتتاحي مخزني: يُدخل أرقام تشغيل قديمة مباشرة إلى الذهب
    المشغول (متاحة للبيع فوراً) دون المرور بدورة تصنيع كاملة — القيد:
    مدين الذهب المشغول (1200) / دائن الأرصدة الافتتاحية للتسوية (3900)
    بإجمالي الوزن المقيد، بقيد واحد مجمّع مطابقاً لنفس منطق دفعة الإنتاج."""
    if not rows:
        raise ValueError("أضف رقم تشغيل واحداً على الأقل")
    prepared = []
    for r in rows:
        wo_no = (r.get("wo_no") or "").strip()
        gold = float(r.get("gold", 0) or 0)
        small = float(r.get("small_stones", 0) or 0)
        big = float(r.get("big_stones", 0) or 0)
        rate = r.get("discount_rate", config.STONE_DISCOUNT_RATE)
        # ملاحظة: الأجر صفر قيمة **صحيحة** (تشغيل بلا أجر). استخدام `or`
        # يعامله كغياب فيستبدله بالافتراضي — لذلك نفحص None صراحةً.
        _wg = r.get("wage_per_gram")
        wage = float(config.DEFAULT_WAGE_PER_GRAM if _wg is None or _wg == ""
                     else _wg)
        model_no = str(r.get("model_no") or "").strip() or None
        if not wo_no:
            raise ValueError("رقم تشغيل فارغ في أحد الأسطر")
        # الرقم التجميعي 0001 يقبل رصيداً افتتاحياً كغيره: فالمصنع قد
        # يبدأ برصيد وزني مجمّع بلا قطع مفردة. يُعالَج بزيادة رصيده
        # بدل إنشاء سجل جديد (لأنه سجل واحد ثابت).
        if gold + small + big <= 0:
            raise ValueError(f"أدخل وزناً صحيحاً للطقم {wo_no}")
        if any(p["wo_no"] == wo_no for p in prepared):
            # الرقم التجميعي 0001 يقبل التكرار: رصيد وزني مجمّع لا
            # قطعة مفردة، فتعدد سطوره في الدفعة الواحدة طبيعي.
            if wo_no != BULK_WO_NO:
                raise ValueError(
                    f"رقم التشغيل {wo_no} مكرر داخل نفس الدفعة")
        if wo_no != BULK_WO_NO and conn.execute(
                "SELECT 1 FROM work_orders WHERE work_order_no=?"
                " AND is_deleted=0", (wo_no,)).fetchone():
            raise ValueError(f"رقم التشغيل {wo_no} مستخدم مسبقاً")
        after = gold_math.stones_after_discount(big, rate)
        reg = gold_math.registered_weight(gold, small, big, rate)
        standing = gold_math.standing_gold(gold, small, big)
        prepared.append({"model_no": model_no,
                         "wo_no": wo_no, "gold": gold, "small": small,
                         "big": big, "after": after, "reg": reg,
                         "standing": standing, "rate": rate, "wage": wage,
                         "item_type": (r.get("item_type") or "").strip()
                         or classify_item(wo_no, gold, small, big),
                         "notes": r.get("notes", "رصيد افتتاحي مخزني")})

    total_reg = round(sum(p["reg"] for p in prepared), 3)
    n = len(prepared)
    lines = [
        {"account_id": acc_id(conn, "1200"), "gold_debit": total_reg,
         "line_desc": f"رصيد افتتاحي مخزني ({n} رقم تشغيل)"},
        {"account_id": acc_id(conn, "3900"), "gold_credit": total_reg,
         "line_desc": "مقابل أرصدة مخزنية سابقة على تشغيل النظام"},
    ]
    entry_id = post_entry(
        conn, entry_date, f"رصيد افتتاحي مخزني ({n} رقم تشغيل)", lines,
        source_table="work_orders", username=username)

    created = []
    for p in prepared:
        # الرقم التجميعي سجل واحد ثابت: يُزاد رصيده بدل إنشاء سجل جديد
        if p["wo_no"] == BULK_WO_NO:
            bulk = get_or_create_bulk_wo(conn, username)
            conn.execute(
                "UPDATE work_orders SET registered_weight=registered_weight+?,"
                " standing_gold=standing_gold+?, gold_weight=gold_weight+?"
                " WHERE id=?",
                (p["reg"], p["standing"], p["gold"], bulk["id"]))
            log_action(conn, username, "update", "work_orders", bulk["id"],
                       f"رصيد افتتاحي تجميعي +{p['reg']:.2f}")
            created.append({"id": bulk["id"], "work_order_no": BULK_WO_NO,
                            "registered_weight": p["reg"]})
            continue
        barcode_path = generate_work_order_barcode(p["wo_no"])
        cur = conn.execute(
            "INSERT INTO work_orders(model_no,work_order_no,gross_weight,"
            "stones_weight,"
            "gold_weight,small_stones,big_stones,item_type,"
            "stones_after_discount,"
            "standing_gold,discount_rate,registered_weight,wage_per_gram,"
            "barcode_path,notes,entry_id,created_by)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p.get("model_no"),
             p["wo_no"], p["standing"], round(p["small"] + p["big"], 3),
             p["gold"], p["small"], p["big"], p["item_type"], p["after"],
             p["standing"], p["rate"], p["reg"], p["wage"], barcode_path,
             p["notes"], entry_id, username))
        wo_id = cur.lastrowid
        log_action(conn, username, "create", "work_orders", wo_id,
                   f"opening reg={p['reg']}")
        created.append({"id": wo_id, "work_order_no": p["wo_no"],
                        "registered_weight": p["reg"]})
    # ربط القيد بأول طقم في الدفعة: بدونه يبقى `source_id` فارغاً
    # فلا يعرف كشف الحساب أي مستند يفتح عند التعديل أو المعاينة.
    if created:
        conn.execute(
            "UPDATE journal_entries SET source_id=? WHERE id=?",
            (created[0]["id"], entry_id))

    # حفظ حصة كل سطر كما أُدخلت — تُقرأ عند التعديل بدل رصيد
    # الطقم التراكمي (يهمّ خصوصاً الرقم التجميعي 0001).
    for i, (p_, c_) in enumerate(zip(prepared, created)):
        conn.execute(
            "INSERT INTO wo_batch_lines(entry_id,work_order_id,model_no,"
            "wo_no,gold,small_stones,big_stones,discount_rate,"
            "registered_weight,wage_per_gram,notes,seq)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (entry_id, c_["id"], p_.get("model_no"), p_["wo_no"],
             p_["gold"], p_["small"], p_["big"], p_["rate"],
             p_["reg"], p_.get("wage", 0), p_.get("notes", ""), i))

    return {"entry_id": entry_id, "total_registered": total_reg,
            "items": created}


# الطرف الدائن الآلي لأي زيادة في أوزان الطقوم — لا يختاره المستخدم.
# الذهب لا يُخلق من العدم: الزيادة تحويل مخزني بين الأصول (Asset→Asset)
# لا إيراد، فلا تتضخم الإيرادات وهمياً ويبقى ميزان الذهب سليماً.
WO_INCREASE_ACCOUNT = "1250"     # مخزون تسويات أوزان الطقوم (أصل)

# الحسابات المقابلة المتاحة عند **النقص** فقط (وجهة النقص يحددها المستخدم).
ADJUST_CONTRA_ACCOUNTS = [
    ("1100", "خزينة التصنيع (ذهب خام تحت التشغيل)"),
    ("1310", "صندوق كسر عيار 18"),
    ("1320", "صندوق كسر عيار 21"),

    ("1350", "الصهر والتصفية"),
    ("1150", "مخزون الفصوص والأحجار"),
    ("1250", "مخزون تسويات أوزان الطقوم"),
    ("5110", "فاقد تشغيلي — قسم التصنيع (خياس)"),
    ("5120", "الفاقد الفني للصب"),
    ("5130", "خسائر فروقات الجرد — الذهب المشغول"),
    ("4300", "أرباح فروقات الجرد والتسويات"),
]


def adjust_wo_weight(conn, wo_id, new_gold, new_small, new_big, username,
                     notes="", contra_code=None):
    """تسوية أوزان طقم بقيد **مزدوج وزني** كامل.

    فرق الوزن المقيد يُرحَّل بطرفين متوازنين: الذهب المشغول (1200) في
    طرف، والحساب المقابل الذي **يحدّده المستخدم** في الطرف الآخر —
    فلا يختلّ ميزان الذهب أبداً:

        زيادة (الجديد > القديم):
            من حـ/ الذهب المشغول (1200)        مدين بالفارق
                إلى حـ/ الحساب المقابل           دائن بالفارق
            (مثال: الزيادة مصدرها مخزون الخامات أو الكسر)

        نقص (الجديد < القديم):
            من حـ/ الحساب المقابل               مدين بالفارق
                إلى حـ/ الذهب المشغول (1200)     دائن بالفارق
            (مثال: النقص وجهته الفاقد أو عاد للخامات)

    **الزيادة**: الطرف الدائن آلي وإجباري إلى حساب «تسوية الزيادة في
    الطقوم» (4310) ولا يختاره المستخدم.
    **النقص**: `contra_code` إلزامي ويحدد وجهة النقص (فاقد/خامات/كسر)
    من `ADJUST_CONTRA_ACCOUNTS`.

    البيان: «زيادة/نقص في رقم التشغيل X»، وتظهر العملية في كشف الذهب
    المشغول كعملية «تسوية».
    """
    wo = conn.execute("SELECT * FROM work_orders WHERE id=? AND is_deleted=0",
                      (wo_id,)).fetchone()
    if not wo:
        raise ValueError("الطقم غير موجود")
    if wo["work_order_no"] == BULK_WO_NO:
        raise ValueError("الرقم التجميعي 0001 يُعدَّل بالتوريد لا بالتسوية")
    new_gold = round(float(new_gold or 0), 3)
    new_small = round(float(new_small or 0), 3)
    new_big = round(float(new_big or 0), 3)
    if new_gold < 0 or new_small < 0 or new_big < 0:
        raise ValueError("الأوزان لا تقبل السالب")
    if new_gold + new_small + new_big <= 0:
        raise ValueError("لا يمكن تصفير الطقم بالكامل")
    rate = wo["discount_rate"]
    new_after = gold_math.stones_after_discount(new_big, rate)
    new_reg = gold_math.registered_weight(new_gold, new_small, new_big, rate)
    new_standing = gold_math.standing_gold(new_gold, new_small, new_big)
    diff = round(new_reg - wo["registered_weight"], 3)
    entry_id = None
    if abs(diff) >= 0.001:
        worked = acc_id(conn, "1200")
        no = wo["work_order_no"]
        if diff > 0:
            # الزيادة: الطرف الدائن آلي وإجباري — «مخزون تسويات أوزان
            # الطقوم» (تحويل مخزني بين الأصول)
            adj = acc_id(conn, WO_INCREASE_ACCOUNT)
        else:
            # النقص: وجهة النقص يحددها المستخدم صراحةً
            if not contra_code:
                raise ValueError(
                    "حدّد الحساب المقابل للنقص — القيد الوزني يجب أن يكون "
                    "مزدوجاً (وجهة النقص: فاقد أو خامات أو كسر)")
            adj = acc_id(conn, str(contra_code).strip())
            if adj == worked:
                raise ValueError(
                    "الحساب المقابل لا يصح أن يكون الذهب المشغول نفسه")
        if diff > 0:
            lines = [
                {"account_id": worked, "gold_debit": diff,
                 "line_desc": f"تسوية: زيادة في رقم التشغيل {no}"},
                {"account_id": adj, "gold_credit": diff,
                 "line_desc": f"تسوية وزن رقم التشغيل {no}"},
            ]
            label = f"زيادة في رقم التشغيل {no}"
        else:
            lines = [
                {"account_id": adj, "gold_debit": -diff,
                 "line_desc": f"تسوية وزن رقم التشغيل {no}"},
                {"account_id": worked, "gold_credit": -diff,
                 "line_desc": f"تسوية: نقص في رقم التشغيل {no}"},
            ]
            label = f"نقص في رقم التشغيل {no}"
        entry_id = post_entry(
            conn, __import__("datetime").date.today().isoformat(),
            f"تسوية وزن — {label}", lines,
            source_table="wo_adjust", source_id=wo_id,
            username=username, note=(notes or label))
    item_type = classify_item(wo["work_order_no"], new_gold, new_small, new_big)
    conn.execute(
        "UPDATE work_orders SET gold_weight=?, small_stones=?, big_stones=?,"
        " stones_after_discount=?, standing_gold=?, registered_weight=?,"
        " gross_weight=?, stones_weight=?, item_type=? WHERE id=?",
        (new_gold, new_small, new_big, new_after, new_standing, new_reg,
         new_standing, round(new_small + new_big, 3), item_type, wo_id))
    log_action(conn, username, "update", "work_orders", wo_id,
               f"weight adj diff={diff}")
    return {"id": wo_id, "diff": diff, "new_reg": new_reg,
            "entry_id": entry_id, "item_type": item_type,
            "contra_code": (WO_INCREASE_ACCOUNT if diff > 0 else contra_code)}


def item_history(conn, wo_no):
    """حركة الطقم (Item History): جدول زمني لكل حركات رقم تشغيل معيّن —
    توريد، مبيعات، مرتجع، تسوية — مع الجهة المقابلة والأوزان ونوعه.

    تُعاد الصفوف مرتبة زمنياً تصاعدياً.
    """
    wo = get_wo_by_no(conn, wo_no)
    if not wo:
        raise ValueError(f"لا يوجد طقم برقم التشغيل {wo_no}")
    rows = []
    # التوريد (إنشاء الطقم)
    src_entry = conn.execute(
        "SELECT entry_date FROM journal_entries WHERE id=?",
        (wo["entry_id"],)).fetchone() if wo["entry_id"] else None
    rows.append({
        "kind": "توريد", "date": (src_entry["entry_date"] if src_entry
                                  else (wo["created_at"] or "")[:10]),
        "party": "المصنع (خزينة التصنيع)",
        "gold": wo["gold_weight"], "small": wo["small_stones"],
        "big": wo["big_stones"], "reg": wo["registered_weight"],
        "type": wo["item_type"] or "—"})
    # المبيعات والمرتجعات من بنود الفواتير
    for it in conn.execute(
            "SELECT i.kind, i.invoice_no, i.invoice_date, it.registered_weight rw,"
            " e.name party FROM invoice_items it"
            " JOIN invoices i ON i.id=it.invoice_id"
            " LEFT JOIN entities e ON e.id=i.customer_id"
            " WHERE it.work_order_id=? AND i.is_deleted=0"
            " ORDER BY i.invoice_date, i.id", (wo["id"],)).fetchall():
        rows.append({
            "kind": "مبيعات" if it["kind"] == "sale" else "مرتجع",
            "date": it["invoice_date"], "party": it["party"] or "—",
            "gold": "", "small": "", "big": "", "reg": it["rw"],
            "type": wo["item_type"] or "—"})
    # تسويات الوزن على هذا الطقم
    for a in conn.execute(
            "SELECT e.entry_date d, e.user_note note FROM journal_entries e"
            " WHERE e.source_table='wo_adjust' AND e.source_id=?"
            " AND e.is_deleted=0 ORDER BY e.entry_date, e.id",
            (wo["id"],)).fetchall():
        rows.append({
            "kind": "تسوية", "date": a["d"], "party": a["note"] or "—",
            "gold": "", "small": "", "big": "", "reg": "",
            "type": wo["item_type"] or "—"})
    rows.sort(key=lambda r: (r["date"] or "", 0 if r["kind"] == "توريد" else 1))
    return wo, rows


# ══════════════════════════════════════════════════════════════════
# تحليلات دوران المخزون — تتبّع فردي على مستوى رقم التشغيل
# ══════════════════════════════════════════════════════════════════

TURNOVER_PANELS = [
    ("first_sale", "مبيعات من أول مرة",
     "مخزون ممتاز سريع الحركة — خرج مرة واحدة ولم يُرتجع"),
    ("resold_few", "أطقم خارجة أقل من 5 مرات",
     "خرجت 2 إلى 5 مرات — حركة طبيعية"),
    ("resold_many", "مبيعات خارجة أكثر من 5 مرات",
     "خرجت 6 مرات فأكثر — تكرار عالٍ يستدعي المراجعة"),
    ("returned_once", "أطقم مرتجعة لأول مرة",
     "مخزون مسترد ينتظر إعادة البيع"),
    ("returned_few", "أطقم مرتجعة أقل من 5 مرات",
     "أُرجعت 2 إلى 5 مرات — تحتاج مراجعة تسعير أو تصميم"),
    ("returned_many", "أطقم مرتجعة أكثر من 5 مرات",
     "أُرجعت 6 مرات فأكثر — مخزون حرج مرشّح للتكسير"),
]

# التتبّع على مستوى **رقم التشغيل الفردي** لا رقم الفاتورة: تُحسب
# حركات الخروج (بيع) والدخول (مرتجع) لكل طقم على حدة، فإرجاع بعض
# أطقم فاتورة لا يؤثر على بقيتها إطلاقاً.
# الحركات مُرشَّحة **بتاريخ الفاتورة** لا بتاريخ إنشاء الطقم.
# الترشيح بتاريخ الإنشاء كان يُظهر أطقماً تحرّكت في فترات سابقة
# داخل أي فترة يختارها المستخدم — فتفقد التحليلات معناها.
_MOVES_CTE = """
    WITH moves AS (
        SELECT it.work_order_id AS wid,
               SUM(CASE WHEN i.kind='sale'        THEN 1 ELSE 0 END) AS out_n,
               SUM(CASE WHEN i.kind='sale_return' THEN 1 ELSE 0 END) AS in_n,
               MAX(CASE WHEN i.kind='sale' THEN i.invoice_date END) AS last_out
        FROM invoice_items it
        JOIN invoices i ON i.id = it.invoice_id AND i.is_deleted = 0
        WHERE 1=1 {PERIOD}
        GROUP BY it.work_order_id
    )
"""

_PANEL_WHERE = {
    # خرج مرة واحدة · بلا مرتجع · وحالته مباع
    "first_sale":     "m.out_n = 1 AND m.in_n = 0 AND w.status = 'sold'",
    # خرج 2 إلى 5 مرات (حركة متكررة طبيعية)
    "resold_few":     "m.out_n BETWEEN 2 AND 5 AND w.status = 'sold'",
    # خرج 6 مرات فأكثر (تكرار عالٍ)
    "resold_many":    "m.out_n >= 6 AND w.status = 'sold'",
    # أُرجع مرة واحدة · وحالته بالمخزن
    "returned_once":  "m.in_n = 1 AND w.status = 'in_stock'",
    # أُرجع 2 إلى 5 مرات
    "returned_few":   "m.in_n BETWEEN 2 AND 5 AND w.status = 'in_stock'",
    # أُرجع 6 مرات فأكثر — مخزون حرج
    "returned_many":  "m.in_n >= 6 AND w.status = 'in_stock'",
}


def turnover_panel(conn, panel, date_from=None, date_to=None):
    """أطقم لوحة معيّنة: رقم التشغيل · الوزن المقيد · الوزن القائم."""
    where = _PANEL_WHERE.get(panel)
    if not where:
        raise ValueError(f"لوحة غير معروفة: {panel}")
    params = []
    period = ""
    if date_from:
        period += " AND i.invoice_date >= ?"
        params.append(date_from)
    if date_to:
        period += " AND i.invoice_date <= ?"
        params.append(date_to)
    cte = _MOVES_CTE.replace("{PERIOD}", period)
    rows = conn.execute(
        cte +
        " SELECT w.work_order_no AS wo, w.registered_weight AS reg,"
        " w.standing_gold AS standing, m.out_n, m.in_n,"
        # البائع = آخر عميل أخذ الطقم · المُرجِع = آخر من أرجعه.
        # كلاهما يُجلب، والواجهة تعرض المناسب لطبيعة اللوحة.
        " (SELECT en.name FROM invoice_items it2"
        "   JOIN invoices i2 ON i2.id = it2.invoice_id"
        "   JOIN entities en ON en.id = i2.customer_id"
        "  WHERE it2.work_order_id = w.id AND i2.is_deleted = 0"
        "    AND i2.kind = 'sale'"
        "  ORDER BY i2.invoice_date DESC, i2.id DESC LIMIT 1) AS buyer,"
        " (SELECT en.name FROM invoice_items it3"
        "   JOIN invoices i3 ON i3.id = it3.invoice_id"
        "   JOIN entities en ON en.id = i3.customer_id"
        "  WHERE it3.work_order_id = w.id AND i3.is_deleted = 0"
        "    AND i3.kind = 'sale_return'"
        "  ORDER BY i3.invoice_date DESC, i3.id DESC LIMIT 1) AS returner,"
        " w.is_bulk AS is_bulk"
        " FROM work_orders w"
        " JOIN moves m ON m.wid = w.id"
        f" WHERE w.is_deleted = 0 AND ({where})"
        " ORDER BY w.work_order_no", params).fetchall()
    return [{"wo": r["wo"], "reg": round(r["reg"] or 0, 2),
             "standing": round(r["standing"] or 0, 2),
             "out_n": r["out_n"], "in_n": r["in_n"],
             # الرقم التجميعي 0001 رصيد مجمّع لا قطعة، فلا يُنسب لشخص
             "buyer": ("—" if r["is_bulk"] else (r["buyer"] or "—")),
             "returner": ("—" if r["is_bulk"]
                          else (r["returner"] or "—"))} for r in rows]


def turnover_all(conn, date_from=None, date_to=None):
    """اللوحات الأربع مع بنودها وإجمالياتها."""
    out = {}
    for key, title, hint in TURNOVER_PANELS:
        items = turnover_panel(conn, key, date_from, date_to)
        out[key] = {
            "title": title, "hint": hint, "items": items,
            "count": len(items),
            "total_reg": round(sum(i["reg"] for i in items), 2),
            "total_standing": round(sum(i["standing"] for i in items), 2),
        }
    return out


def create_return_stub(conn, wo_no, gold, small_stones, big_stones,
                       discount_rate, wage_per_gram, username):
    """ينشئ طقماً غير مسجّل عائداً بمرتجع، بحالة «مباع».

    **المنطق المحاسبي**: البضاعة العائدة كانت خارج المصنع أصلاً، فلا
    يجوز إثباتها في المخزون مرتين. لذلك يُنشأ السجل بحالة `sold` بلا
    أي قيد مالي — ثم يتولّى قيدُ المرتجع نفسه إدخالها للذهب المشغول
    مقابل ذمة العميل. فيبقى القيد المزدوج سليماً بلا ازدواج.
    """
    wo_no = str(wo_no).strip()
    if not wo_no:
        raise ValueError("أدخل رقم التشغيل")
    if get_wo_by_no(conn, wo_no):
        raise ValueError(f"رقم التشغيل {wo_no} مسجَّل مسبقاً")
    gold = float(gold or 0)
    small = float(small_stones or 0)
    big = float(big_stones or 0)
    if gold <= 0:
        raise ValueError("أدخل وزن الذهب")
    rate = float(discount_rate if discount_rate is not None
                 else config.STONE_DISCOUNT_RATE)
    after = gold_math.stones_after_discount(big, rate)
    reg = gold_math.registered_weight(gold, small, big, rate)
    standing = gold_math.standing_gold(gold, small, big)
    conn.execute(
        "INSERT INTO work_orders(work_order_no,gold_weight,small_stones,"
        "big_stones,stones_after_discount,discount_rate,registered_weight,"
        "standing_gold,gross_weight,stones_weight,"
        "wage_per_gram,item_type,status,notes,created_by)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'sold',?,?)",
        (wo_no, gold, small, big, after, rate, reg, standing,
         standing, round(small + big, 3),
         float(config.DEFAULT_WAGE_PER_GRAM
               if wage_per_gram is None or wage_per_gram == ''
               else wage_per_gram),
         classify_item(wo_no, gold, small, big),
         "طقم غير مسجّل أُدخل عبر مرتجع", username))
    log_action(conn, username, "create", "work_orders", None,
               f"طقم مرتجع غير مسجّل: {wo_no} بوزن مقيد {reg:.2f}")
    return get_wo_by_no(conn, wo_no)


# ══════════════════════════════════════════════════════════════════
# تسويات أوزان الأطقم (حذف · زيادة · نقص)
# ══════════════════════════════════════════════════════════════════

ADJUST_ACCOUNT = "1250"          # مخزون تسويات أوزان الطقوم


def adjust_or_delete_wo(conn, wo_id, username, new_gold=None,
                        new_small=None, new_big=None, delete=False,
                        adjust_date=None, notes=""):
    """يحذف طقماً أو يعدّل وزنه مقابل **حساب التسويات** (1250).

    **المنطق المحاسبي**:

    * **حذف الطقم** → خرج من المخزون:
          دائن حـ/ الذهب المشغول (1200)   بالوزن المقيد
          مدين حـ/ تسويات (1250)
          البيان: «حذف رقم التشغيل ####»

    * **نقص الوزن** → نفس الاتجاه بفرق الوزن:
          البيان: «تعديل وزن رقم التشغيل ####»

    * **زيادة الوزن** → دخل للمخزون:
          مدين حـ/ الذهب المشغول (1200)   بفرق الوزن
          دائن حـ/ تسويات (1250)
          البيان: «زيادة في رقم التشغيل ####»

    فيبقى ميزان الذهب متوازناً دائماً، ويظهر أثر كل تسوية في كشف
    حساب التسويات باسم رقم التشغيل صراحةً.
    """
    import datetime as _dt

    wo = conn.execute("SELECT * FROM work_orders WHERE id=? AND is_deleted=0",
                      (wo_id,)).fetchone()
    if not wo:
        raise ValueError("الطقم غير موجود أو محذوف مسبقاً")
    # الطقم المباع يقبل التسوية أيضاً: تصحيح وزن مُدخل خطأً واجب
    # سواء بقي بالمخزن أو خرج. الفرق أن أثر التسوية يقع على حساب
    # العميل الذي أخذه لا على الذهب المشغول — وهو ما يفعله القيد
    # أصلاً (دائن 1200 / مدين 1250) فيبقى الميزان سليماً.
    if wo["is_bulk"]:
        raise ValueError("الرقم التجميعي 0001 يُعدَّل بالتوريد لا بالتسوية")

    date = adjust_date or _dt.date.today().isoformat()
    old_reg = round(wo["registered_weight"] or 0, 3)
    wo_no = wo["work_order_no"]

    if delete:
        diff = -old_reg
        label = f"حذف رقم التشغيل {wo_no}"
    else:
        g = float(new_gold if new_gold is not None else wo["gold_weight"])
        sm = float(new_small if new_small is not None else wo["small_stones"])
        bg = float(new_big if new_big is not None else wo["big_stones"])
        if g <= 0:
            raise ValueError("وزن الذهب يجب أن يكون أكبر من صفر")
        rate = wo["discount_rate"]
        new_reg = round(gold_math.registered_weight(g, sm, bg, rate), 3)
        diff = round(new_reg - old_reg, 3)
        if abs(diff) < 0.001:
            raise ValueError("لا تغيير في الوزن المقيد")
        label = (f"زيادة في رقم التشغيل {wo_no}" if diff > 0
                 else f"تعديل وزن رقم التشغيل {wo_no}")

    amount = abs(diff)
    mash = acc_id(conn, "1200")
    adj = acc_id(conn, ADJUST_ACCOUNT)
    if diff < 0:
        # خروج من المخزون: دائن الذهب المشغول / مدين التسويات
        lines = [{"account_id": adj, "gold_debit": amount,
                  "line_desc": label},
                 {"account_id": mash, "gold_credit": amount,
                  "line_desc": label}]
    else:
        # دخول للمخزون: مدين الذهب المشغول / دائن التسويات
        lines = [{"account_id": mash, "gold_debit": amount,
                  "line_desc": label},
                 {"account_id": adj, "gold_credit": amount,
                  "line_desc": label}]

    entry_id = post_entry(conn, date, label, lines,
                          source_table="work_orders", source_id=wo_id,
                          username=username, note=notes or label)

    if delete:
        conn.execute("UPDATE work_orders SET is_deleted=1 WHERE id=?",
                     (wo_id,))
    else:
        after = gold_math.stones_after_discount(bg, rate)
        standing = gold_math.standing_gold(g, sm, bg)
        conn.execute(
            "UPDATE work_orders SET gold_weight=?, small_stones=?,"
            " big_stones=?, stones_after_discount=?, standing_gold=?,"
            " gross_weight=?, stones_weight=?, registered_weight=?,"
            " item_type=? WHERE id=?",
            (g, sm, bg, after, standing, standing, round(sm + bg, 3),
             new_reg, classify_item(wo_no, g, sm, bg), wo_id))

    log_action(conn, username, "adjust", "work_orders", wo_id,
               f"{label} | فرق {diff:+.3f} جم")
    return {"wo_no": wo_no, "old_reg": old_reg,
            "new_reg": 0.0 if delete else new_reg,
            "diff": diff, "entry_id": entry_id, "label": label}


def rename_work_order(conn, wo_id, new_no, username, reason=""):
    """يصحّح رقم التشغيل لطقم أُدخل خطأً.

    **المنطق المحاسبي**: رقم التشغيل معرّف وصفي لا يحمل قيمة مالية،
    فتغييره **لا يمسّ أي رصيد ولا قيد**. لكنه يظهر في بيانات القيود
    والفواتير، فتُحدَّث تلك البيانات معه ليبقى الأثر متسقاً ويُتتبَّع
    الطقم برقمه الجديد في كل الكشوف.
    """
    new_no = str(new_no or "").strip()
    if not new_no:
        raise ValueError("أدخل رقم التشغيل الجديد")
    wo = conn.execute("SELECT * FROM work_orders WHERE id=? AND is_deleted=0",
                      (wo_id,)).fetchone()
    if not wo:
        raise ValueError("الطقم غير موجود")
    old_no = wo["work_order_no"]
    if new_no == old_no:
        return {"old": old_no, "new": new_no, "changed": 0}
    if new_no == BULK_WO_NO:
        raise ValueError("الرقم 0001 محجوز للرصيد التجميعي")
    if conn.execute("SELECT 1 FROM work_orders WHERE work_order_no=?"
                    " AND is_deleted=0 AND id<>?",
                    (new_no, wo_id)).fetchone():
        raise ValueError(f"رقم التشغيل {new_no} مستخدم لطقم آخر")

    conn.execute("UPDATE work_orders SET work_order_no=?,"
                 " item_type=? WHERE id=?",
                 (new_no,
                  classify_item(new_no, wo["gold_weight"],
                                wo["small_stones"], wo["big_stones"]),
                  wo_id))

    # سطور الدفعة تحمل الرقم نصاً، والباركود مرسومٌ بالرقم القديم.
    # تركُهما يجعل ورقة الدفعة وملصق الطقم يقولان رقماً والبطاقةُ
    # رقماً آخر — وهو أسوأ من عدم التصحيح.
    try:
        conn.execute("UPDATE wo_batch_lines SET wo_no=?"
                     " WHERE work_order_id=?", (new_no, wo_id))
    except Exception:
        pass
    try:
        path = generate_work_order_barcode(new_no)
        if path:
            conn.execute("UPDATE work_orders SET barcode_path=?"
                         " WHERE id=?", (path, wo_id))
    except Exception:
        pass

    # تحديث البيانات النصية التي تذكر الرقم القديم
    changed = 0
    for tbl, col in (("journal_entries", "description"),
                     ("journal_entries", "user_note"),
                     ("journal_lines", "line_desc")):
        try:
            cur = conn.execute(
                f"UPDATE {tbl} SET {col}=REPLACE({col}, ?, ?)"
                f" WHERE {col} LIKE ?",
                (old_no, new_no, f"%{old_no}%"))
            changed += cur.rowcount or 0
        except Exception:
            pass

    log_action(conn, username, "rename", "work_orders", wo_id,
               f"تصحيح رقم التشغيل: {old_no} ← {new_no}"
               + (f" | {reason}" if reason else ""))
    return {"old": old_no, "new": new_no, "changed": changed}


def update_supply_batch(conn, entry_id, rows, entry_date, username):
    """يحدّث دفعة توريد مُرحَّلة — **تفاضلياً** لا بإعادة إنشائها.

    **لماذا التفاضلي**: إعادة الإنشاء تتطلّب حذف الأطقم القديمة، وهذا
    مستحيل لما بيع منها — فتفشل العملية كلها لأن طقماً واحداً خرج.

    المنطق الصحيح محاسبياً:

      • طقم **مباع**: يبقى كما هو، ولا يُمسّ وزنه (فاتورته قائمة عليه)
      • طقم **بالمخزن تغيّر وزنه**: يُعدَّل وزنه، والفرق يُرحَّل على
        الذهب المشغول
      • طقم **جديد**: يُنشأ ويُضاف كاملاً للذهب المشغول
      • طقم **حُذف من الدفعة** وما زال بالمخزن: يُحذف ويُخصم

    والقيد يُعدَّل بالفرق الصافي فقط — فلا يتضخّم دفتر الأستاذ بقيود
    عكسية لعملية لم تتغيّر إلا جزئياً.
    """
    entry = conn.execute(
        "SELECT * FROM journal_entries WHERE id=? AND is_deleted=0",
        (entry_id,)).fetchone()
    if not entry:
        raise ValueError("القيد غير موجود أو محذوف")
    # قيمة الدفعة **قبل** أن يُعدَّل قيدها
    from models import doc_edits as _de
    _before = _de.totals(conn, entry_id)

    # ══ الحالة الحالية: أطقم الدفعة كما هي الآن ══
    # الدفعات المُنشأة قبل وجود جدول السطور لا سطور لها؛ ولو اعتمدنا
    # عليه وحده لبدت كل أطقمها «جديدة» فيُرفض التعديل بحجّة تكرار
    # أرقام التشغيل. لذلك نبني السطور من الأطقم نفسها عند غيابها —
    # فتُعدَّل الدفعات القديمة كالجديدة تماماً.
    old_lines = conn.execute(
        "SELECT * FROM wo_batch_lines WHERE entry_id=? ORDER BY seq, id",
        (entry_id,)).fetchall()
    if not old_lines:
        legacy = conn.execute(
            "SELECT * FROM work_orders WHERE entry_id=? AND is_deleted=0"
            " ORDER BY id", (entry_id,)).fetchall()
        for i, w in enumerate(legacy):
            conn.execute(
                "INSERT INTO wo_batch_lines(entry_id,work_order_id,"
                "model_no,wo_no,gold,small_stones,big_stones,"
                "discount_rate,registered_weight,wage_per_gram,notes,seq)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry_id, w["id"],
                 (w["model_no"] if "model_no" in w.keys() else None),
                 w["work_order_no"], w["gold_weight"] or 0,
                 w["small_stones"] or 0, w["big_stones"] or 0,
                 w["discount_rate"] or 0, w["registered_weight"] or 0,
                 w["wage_per_gram"] or 0, w["notes"] or "", i))
        old_lines = conn.execute(
            "SELECT * FROM wo_batch_lines WHERE entry_id=?"
            " ORDER BY seq, id", (entry_id,)).fetchall()

    by_no = {}
    for ln in old_lines:
        wo = conn.execute(
            "SELECT * FROM work_orders WHERE id=? AND is_deleted=0",
            (ln["work_order_id"],)).fetchone()
        if wo:
            by_no[wo["work_order_no"]] = {"line": ln, "wo": wo}

    delta = 0.0          # صافي التغيّر في الوزن المقيد
    added, updated, removed, kept_sold = [], [], [], []
    seen = set()

    for i, r in enumerate(rows):
        no = str(r.get("wo_no") or "").strip()
        if not no:
            continue
        seen.add(no)
        gold = float(r.get("gold") or 0)
        small = float(r.get("small_stones") or 0)
        big = float(r.get("big_stones") or 0)
        rate = float(r.get("discount_rate") or 0)
        _wg = r.get("wage_per_gram")
        wage = float(config.DEFAULT_WAGE_PER_GRAM
                     if _wg is None or _wg == "" else _wg)
        reg = gold_math.registered_weight(gold, small, big, rate)
        standing = gold_math.standing_gold(gold, small, big)
        after = gold_math.stones_after_discount(big, rate)
        model_no = str(r.get("model_no") or "").strip() or None

        cur = by_no.get(no)
        if cur is None:
            # ── طقم جديد يُضاف للدفعة ──
            if no == BULK_WO_NO:
                adjust_bulk_wo(conn, reg, username)
                wid = get_or_create_bulk_wo(conn, username)["id"]
            else:
                if conn.execute(
                        "SELECT 1 FROM work_orders WHERE work_order_no=?"
                        " AND is_deleted=0", (no,)).fetchone():
                    raise ValueError(
                        f"رقم التشغيل {no} مستخدم في عملية أخرى")
                cur2 = conn.execute(
                    "INSERT INTO work_orders(model_no,work_order_no,"
                    "gross_weight,stones_weight,gold_weight,small_stones,"
                    "big_stones,item_type,stones_after_discount,"
                    "standing_gold,discount_rate,registered_weight,"
                    "wage_per_gram,notes,entry_id,created_by)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (model_no, no, standing, round(small + big, 3), gold,
                     small, big, classify_item(no, gold, small, big),
                     after, standing, rate, reg, wage,
                     r.get("notes", ""), entry_id, username))
                wid = cur2.lastrowid
            conn.execute(
                "INSERT INTO wo_batch_lines(entry_id,work_order_id,"
                "model_no,wo_no,gold,small_stones,big_stones,"
                "discount_rate,registered_weight,wage_per_gram,notes,seq)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry_id, wid, model_no, no, gold, small, big, rate,
                 reg, wage, r.get("notes", ""), i))
            delta += reg
            added.append(no)
            continue

        wo, ln = cur["wo"], cur["line"]
        old_reg = float(ln["registered_weight"] or 0)
        if abs(reg - old_reg) < 0.001 and (wo["model_no"] or "") == \
                (model_no or ""):
            if wo["status"] == "sold":
                kept_sold.append(no)
            continue

        if wo["status"] == "sold":
            # ── مباع: وزنه مرتبط بفاتورته فلا يُمسّ ──
            # لكن الموديل تصنيف وصفي فيُحدَّث بلا أثر مالي
            if (wo["model_no"] or "") != (model_no or ""):
                conn.execute("UPDATE work_orders SET model_no=?"
                             " WHERE id=?", (model_no, wo["id"]))
            kept_sold.append(no)
            continue

        # ── بالمخزن: يُعدَّل وزنه والفرق يُرحَّل ──
        if no == BULK_WO_NO:
            adjust_bulk_wo(conn, reg - old_reg, username)
        else:
            conn.execute(
                "UPDATE work_orders SET model_no=?, gold_weight=?,"
                " small_stones=?, big_stones=?, stones_after_discount=?,"
                " standing_gold=?, gross_weight=?, stones_weight=?,"
                " discount_rate=?, registered_weight=?, wage_per_gram=?,"
                " item_type=?, notes=? WHERE id=?",
                (model_no, gold, small, big, after, standing, standing,
                 round(small + big, 3), rate, reg, wage,
                 classify_item(no, gold, small, big),
                 r.get("notes", ""), wo["id"]))
        conn.execute(
            "UPDATE wo_batch_lines SET model_no=?, gold=?, small_stones=?,"
            " big_stones=?, discount_rate=?, registered_weight=?,"
            " wage_per_gram=?, notes=?, seq=? WHERE id=?",
            (model_no, gold, small, big, rate, reg, wage,
             r.get("notes", ""), i, ln["id"]))
        delta += (reg - old_reg)
        updated.append(no)

    # ── أطقم حُذفت من الدفعة ──
    for no, cur in by_no.items():
        if no in seen:
            continue
        wo, ln = cur["wo"], cur["line"]
        if wo["status"] == "sold":
            # المباع لا يُحذف: فاتورته قائمة عليه
            kept_sold.append(no)
            continue
        old_reg = float(ln["registered_weight"] or 0)
        if no == BULK_WO_NO:
            adjust_bulk_wo(conn, -old_reg, username)
        else:
            conn.execute("UPDATE work_orders SET is_deleted=1 WHERE id=?",
                         (wo["id"],))
        conn.execute("DELETE FROM wo_batch_lines WHERE id=?", (ln["id"],))
        delta -= old_reg
        removed.append(no)

    # ── تعديل القيد بالفرق الصافي ──
    delta = round(delta, 3)
    if abs(delta) > 0.001:
        gold_line = conn.execute(
            "SELECT l.id, l.gold_debit FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id"
            " WHERE l.entry_id=? AND a.code='1200'", (entry_id,)).fetchone()
        tz_line = conn.execute(
            "SELECT l.id, l.gold_credit FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id"
            " WHERE l.entry_id=? AND a.code='1100'", (entry_id,)).fetchone()
        if gold_line and tz_line:
            conn.execute(
                "UPDATE journal_lines SET gold_debit=? WHERE id=?",
                (round((gold_line["gold_debit"] or 0) + delta, 3),
                 gold_line["id"]))
            conn.execute(
                "UPDATE journal_lines SET gold_credit=? WHERE id=?",
                (round((tz_line["gold_credit"] or 0) + delta, 3),
                 tz_line["id"]))
        else:
            raise ValueError(
                "تعذّر تعديل القيد: أسطره غير متوقّعة — "
                "احذف العملية وأعد إدخالها")

    if entry_date and entry_date != entry["entry_date"]:
        conn.execute("UPDATE journal_entries SET entry_date=? WHERE id=?",
                     (entry_date, entry_id))

    # تعديل دفعة التوريد يغيّر مبالغ القيد وتاريخه في مكانهما —
    # تعديلٌ مشروع من داخل النظام موثَّق في سجل التدقيق أدناه. يُوسَم
    # القيد ليُعاد ختمه في سلسلة البصمات عند إغلاق المعاملة، وإلا
    # ظهر التعديل السليم «عبثاً» في شاشة سلامة السجل.
    try:
        from models import integrity
        integrity.mark(conn, entry_id)
    except Exception:
        pass

    log_action(conn, username, "update", "work_orders", entry_id,
               f"تعديل دفعة توريد: +{len(added)} · ~{len(updated)} · "
               f"-{len(removed)} · مباع محفوظ {len(set(kept_sold))} · "
               f"صافي الوزن {delta:+.3f} جم")
    _de.record(conn, "work_orders", entry_id, username, _before,
               doc_no=entry["doc_no"] or "", entry_id=entry_id,
               kind="inplace",
               note=f"+{len(added)} · ~{len(updated)} · -{len(removed)}")
    # ══ `total_registered` — مفتاحٌ كان ناقصاً ══
    # الشاشة تعرضه في رسالة «تم الترحيل» للمسارين معاً: الإنشاء
    # والتعديل. وكان الإنشاء وحده يعيده، فالتعديل يرفع
    # `KeyError: 'total_registered'` **بعد** إغلاق المعاملة بنجاح —
    # فتُحفظ الدفعة ويرى المستخدم رسالة خطأ إنجليزية لا يفهمها ولا
    # تدلّ على شيء، ويظنّ أن التعديل لم يتمّ فيعيده.
    # ويُقرأ من القاعدة لا يُجمَع من السطور: هو وزن الدفعة كما صارت
    # بعد التعديل — بما فيها الأطقم المباعة التي بقيت كما هي.
    total_reg = conn.execute(
        "SELECT COALESCE(SUM(registered_weight),0) t FROM work_orders"
        " WHERE entry_id=? AND is_deleted=0", (entry_id,)).fetchone()["t"]
    return {"entry_id": entry_id, "added": added, "updated": updated,
            "removed": removed, "kept_sold": sorted(set(kept_sold)),
            "delta": delta,
            "total_registered": round(float(total_reg or 0), 3),
            "items": [{"work_order_no": n,
                       "registered_weight": 0, "standing_gold": 0}
                      for n in (added + updated)]}
