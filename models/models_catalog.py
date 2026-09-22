# -*- coding: utf-8 -*-
"""دليل الموديلات — تصنيف الأطقم بتصميمها.

**الفكرة المحاسبية**: رقم الموديل تصنيف **وصفي** لا مالي — يجمع أرقام
التشغيل التي تشترك في التصميم نفسه. فلا يُنشأ له حساب في الدليل ولا
يدخل في أي قيد، لكنه يجيب سؤالاً إدارياً مهماً:

    «موديل الخاتم رقم 55: كم قطعة منه بيعت وأين، وكم بقي بالخزنة؟»

البنية شجرية كدليل الحسابات:

    ◄ الموديل 55                    (الإجمالي)
        ├─ المبيعات                 (خرجت وعند العملاء)
        │    └─ رقم التشغيل + العميل
        └─ الموجود                  (متاح للبيع في الذهب المشغول)
             └─ رقم التشغيل + الوزن
"""


# تاريخ الورود: تاريخُ **قيد** الدفعة لا لحظةُ كتابة السجل. القيد
# يُؤرَّخ بيوم التوريد كما أدخله المستخدم في «الوارد من التصنيع»،
# أما `created_at` فلحظةُ الكتابة — وقد تتأخّر يوماً أو شهراً عن
# التوريد نفسه. والسؤال «ماذا ورد يوم كذا» يريد الأول لا الثاني.
IN_DATE = ("COALESCE((SELECT e.entry_date FROM journal_entries e"
           " WHERE e.id=w.entry_id AND e.is_deleted=0),"
           " substr(w.created_at,1,10))")

# مكانُ القطعة اليوم: الخزنة أو جهة. لا ثالث لهما — حالة الطقم
# `in_stock` أو `sold`، والمرتجع يعيدها `in_stock` فتعود للخزنة.
SAFE = "الخزنة"


def list_models(conn, date_from=None, date_to=None):
    """كل الموديلات المسجّلة مع إجمالياتها."""
    p = []
    clause = ""
    if date_from:
        clause += f" AND {IN_DATE} >= ?"
        p.append(date_from)
    if date_to:
        clause += f" AND {IN_DATE} <= ?"
        p.append(date_to)
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(TRIM(w.model_no),''),'— بلا موديل —') mno,"
        " COUNT(*) n,"
        " SUM(CASE WHEN w.status='in_stock' THEN 1 ELSE 0 END) in_n,"
        " SUM(CASE WHEN w.status='sold' THEN 1 ELSE 0 END) out_n,"
        " ROUND(SUM(CASE WHEN w.status='in_stock'"
        "   THEN w.registered_weight ELSE 0 END),2) in_w,"
        " ROUND(SUM(CASE WHEN w.status='sold'"
        "   THEN w.registered_weight ELSE 0 END),2) out_w"
        " FROM work_orders w WHERE w.is_deleted=0" + clause +
        " GROUP BY mno ORDER BY mno", p).fetchall()
    return [{"model": r["mno"], "count": r["n"],
             "in_count": r["in_n"] or 0, "out_count": r["out_n"] or 0,
             "in_weight": r["in_w"] or 0.0,
             "out_weight": r["out_w"] or 0.0} for r in rows]


def model_items(conn, model_no, branch):
    """أطقم الموديل في فرع محدد.

    `branch='sold'`     → الخارجة المباعة، مع اسم آخر من أخذها
    `branch='in_stock'` → المتاحة في الذهب المشغول
    """
    bare = model_no in ("— بلا موديل —", "", None)
    where = ("(w.model_no IS NULL OR TRIM(w.model_no)='')" if bare
             else "TRIM(w.model_no)=?")
    p = [] if bare else [str(model_no).strip()]
    status = "sold" if branch == "sold" else "in_stock"
    rows = conn.execute(
        "SELECT w.id, w.work_order_no wo, w.registered_weight reg,"
        " w.standing_gold standing, w.gold_weight gold,"
        " substr(w.created_at,1,10) created,"
        " (SELECT en.name FROM invoice_items it"
        "   JOIN invoices i ON i.id=it.invoice_id"
        "   JOIN entities en ON en.id=i.customer_id"
        "  WHERE it.work_order_id=w.id AND i.is_deleted=0"
        "    AND i.kind='sale'"
        "  ORDER BY i.invoice_date DESC, i.id DESC LIMIT 1) holder,"
        " (SELECT i.invoice_date FROM invoice_items it"
        "   JOIN invoices i ON i.id=it.invoice_id"
        "  WHERE it.work_order_id=w.id AND i.is_deleted=0"
        "    AND i.kind='sale'"
        "  ORDER BY i.invoice_date DESC, i.id DESC LIMIT 1) sold_date"
        f" FROM work_orders w WHERE w.is_deleted=0 AND {where}"
        f" AND w.status=? ORDER BY w.work_order_no", p + [status]).fetchall()
    return [{"id": r["id"], "wo": r["wo"],
             "reg": round(r["reg"] or 0, 2),
             "standing": round(r["standing"] or 0, 2),
             "gold": round(r["gold"] or 0, 2),
             "holder": r["holder"] or "—",
             "date": r["sold_date"] or r["created"] or ""}
            for r in rows]


# ══════════════════════════════════════════════════════════════════
# الوارد من التصنيع بتاريخ — ماذا دخل ذلك اليوم، وأين هو الآن
# ══════════════════════════════════════════════════════════════════
#
# **لماذا لا يُقرأ الوارد من بطاقة الطقم**: الرقم التجميعي 0001 سجلٌّ
# **تراكمي** واحد يزيد رصيده مع كل دفعة، وبطاقتُه تحمل تاريخ آخر
# دفعة ورصيدَها الكلي. فمن سأل «ماذا ورد يوم الأحد» وقرأ البطاقات
# رأى رصيد الشهر كلِّه منسوباً ليوم واحد. لذلك يُقرأ الوارد من
# `wo_batch_lines` — وهو سجلُّ حصة كل طقم في دفعته كما أُدخلت.
#
# والدفعات القديمة (قبل وجود ذلك الجدول) لا سطور لها، فتُقرأ من
# بطاقاتها مباشرةً — وإلا اختفى وارد سنةٍ كاملة من التقرير.

_RECV_SQL = f"""
SELECT e.entry_date d, w.id wid, w.work_order_no wo,
       COALESCE(NULLIF(TRIM(l.model_no),''),
                NULLIF(TRIM(w.model_no),'')) mno,
       l.registered_weight reg, l.wage_per_gram wage,
       w.status st, w.is_bulk bulk
  FROM wo_batch_lines l
  JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0
  JOIN work_orders w ON w.id=l.work_order_id AND w.is_deleted=0
 WHERE e.entry_date BETWEEN ? AND ?
UNION ALL
SELECT {IN_DATE} d, w.id wid, w.work_order_no wo,
       NULLIF(TRIM(w.model_no),'') mno,
       w.registered_weight reg, w.wage_per_gram wage,
       w.status st, w.is_bulk bulk
  FROM work_orders w
 WHERE w.is_deleted=0
   AND NOT EXISTS (SELECT 1 FROM wo_batch_lines l2
                    WHERE l2.work_order_id=w.id)
   AND {IN_DATE} BETWEEN ? AND ?
"""


def _holders(conn, ids):
    """اسم آخر جهةٍ أخذت كل طقم — للمباع وحده."""
    out = {}
    ids = [int(i) for i in (ids or [])]
    for i in range(0, len(ids), 400):        # دفعات: لا استعلام بألف مُعامل
        chunk = ids[i:i + 400]
        ph = ",".join("?" * len(chunk))
        for r in conn.execute(
                "SELECT it.work_order_id wid, en.name nm"
                " FROM invoice_items it"
                " JOIN invoices i ON i.id=it.invoice_id"
                " JOIN entities en ON en.id=i.customer_id"
                f" WHERE it.work_order_id IN ({ph}) AND i.is_deleted=0"
                " AND i.kind='sale'"
                " ORDER BY i.invoice_date, i.id", chunk):
            out[r["wid"]] = r["nm"]          # الأحدث يغلب — الترتيب تصاعدي
    return out


def received(conn, date_from, date_to, models=None):
    """الوارد من التصنيع في فترة — موديلاً موديلاً، ومع من كل قطعة.

    `models`: قائمة أرقام موديلات للقصر عليها (أو لا شيء = الكل).

    كل قطعة تحمل مكانها **اليوم** لا يوم ورودها: «الخزنة» إن كانت
    متاحةً للبيع، واسمُ الجهة إن خرجت إليها. فالسؤال الذي يُسأل بعد
    شهرٍ من التوريد ليس «أين وضعتُها» بل «أين هي الآن».
    """
    d1 = str(date_from or "")
    d2 = str(date_to or d1)
    if d2 < d1:
        d1, d2 = d2, d1
    rows = conn.execute(_RECV_SQL, (d1, d2, d1, d2)).fetchall()
    want = {str(m).strip() for m in (models or []) if str(m).strip()}

    groups, wids = {}, set()
    for r in rows:
        mno = (r["mno"] or "").strip() or "— بلا موديل —"
        if want and mno not in want:
            continue
        if r["st"] == "sold":
            wids.add(r["wid"])
        groups.setdefault(mno, []).append(r)
    names = _holders(conn, wids)

    out, t_n, t_w, in_n, in_w = [], 0, 0.0, 0, 0.0
    for mno in sorted(groups):
        items, g_n, g_w, g_in, g_inw = [], 0, 0.0, 0, 0.0
        for r in sorted(groups[mno], key=lambda x: (x["d"] or "",
                                                    str(x["wo"]))):
            reg = round(float(r["reg"] or 0), 2)
            safe = r["st"] != "sold"
            items.append({
                "id": r["wid"], "wo": r["wo"], "reg": reg,
                "wage": round(float(r["wage"] or 0), 2),
                "date": r["d"] or "", "bulk": bool(r["bulk"]),
                "safe": safe,
                "holder": SAFE if safe else (names.get(r["wid"]) or "جهة"),
            })
            g_n += 1
            g_w = round(g_w + reg, 2)
            if safe:
                g_in += 1
                g_inw = round(g_inw + reg, 2)
        out.append({"model": mno, "count": g_n, "weight": g_w,
                    "in_count": g_in, "in_weight": g_inw,
                    "out_count": g_n - g_in,
                    "out_weight": round(g_w - g_inw, 2),
                    "items": items})
        t_n += g_n
        t_w = round(t_w + g_w, 2)
        in_n += g_in
        in_w = round(in_w + g_inw, 2)

    holders = sorted({i["holder"] for m in out for i in m["items"]
                      if not i["safe"]})
    return {"date_from": d1, "date_to": d2, "models": out,
            "count": t_n, "weight": t_w,
            "in_count": in_n, "in_weight": in_w,
            "out_count": t_n - in_n, "out_weight": round(t_w - in_w, 2),
            "model_count": len(out), "holders": holders,
            "days": sorted({i["date"] for m in out for i in m["items"]
                            if i["date"]})}


def received_days(conn, limit=400):
    """أيامُ التوريد الفعلية — ليختار المستخدم يوماً موجوداً.

    قائمةُ أيامٍ فيها وارد أنفعُ من تقويمٍ يفتح على يومٍ فارغ: فمن
    أراد «ماذا ورد آخر مرة» وجده في أول السطر.
    """
    rows = conn.execute(f"""
        SELECT d, COUNT(*) n, ROUND(SUM(reg),2) w,
               COUNT(DISTINCT COALESCE(mno,'')) k FROM (
          SELECT e.entry_date d, l.registered_weight reg,
                 COALESCE(NULLIF(TRIM(l.model_no),''),
                          NULLIF(TRIM(w.model_no),'')) mno
            FROM wo_batch_lines l
            JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0
            JOIN work_orders w ON w.id=l.work_order_id AND w.is_deleted=0
          UNION ALL
          SELECT {IN_DATE} d, w.registered_weight reg,
                 NULLIF(TRIM(w.model_no),'') mno
            FROM work_orders w
           WHERE w.is_deleted=0
             AND NOT EXISTS (SELECT 1 FROM wo_batch_lines l2
                              WHERE l2.work_order_id=w.id))
         WHERE d IS NOT NULL AND d<>''
         GROUP BY d ORDER BY d DESC LIMIT ?""", (int(limit),)).fetchall()
    return [{"date": r["d"], "count": r["n"], "weight": r["w"] or 0.0,
             "models": r["k"]} for r in rows]


def model_names(conn):
    """أرقام الموديلات المسجّلة — للاقتراح في شاشة التوريد."""
    return [r["m"] for r in conn.execute(
        "SELECT DISTINCT TRIM(model_no) m FROM work_orders"
        " WHERE is_deleted=0 AND model_no IS NOT NULL"
        " AND TRIM(model_no)<>'' ORDER BY m")]


def rename_model(conn, old_no, new_no, username):
    """يعيد تسمية موديل — تصنيف وصفي، بلا أي أثر مالي."""
    from services.audit import log_action
    new_no = str(new_no or "").strip()
    if not new_no:
        raise ValueError("أدخل رقم الموديل الجديد")
    cur = conn.execute(
        "UPDATE work_orders SET model_no=? WHERE TRIM(model_no)=?"
        " AND is_deleted=0", (new_no, str(old_no).strip()))
    n = cur.rowcount or 0
    log_action(conn, username, "rename", "work_orders", None,
               f"موديل: {old_no} ← {new_no} ({n} طقم)")
    return {"old": old_no, "new": new_no, "count": n}


def assign_model(conn, wo_id, model_no, username):
    """يربط طقماً برقم موديل (أو يفكّه بتركه فارغاً)."""
    from services.audit import log_action
    m = str(model_no or "").strip() or None
    wo = conn.execute(
        "SELECT work_order_no FROM work_orders WHERE id=? AND is_deleted=0",
        (wo_id,)).fetchone()
    if not wo:
        raise ValueError("الطقم غير موجود")
    conn.execute("UPDATE work_orders SET model_no=? WHERE id=?", (m, wo_id))
    log_action(conn, username, "update", "work_orders", wo_id,
               f"ربط الطقم {wo['work_order_no']} بالموديل {m or '—'}")
    return {"wo": wo["work_order_no"], "model": m}


# ══════════════════════════════════════════════════════════════════
# صور الموديلات
# ══════════════════════════════════════════════════════════════════

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def images_dir():
    """مجلد صور الموديلات — داخل مساحة المصنع فلا تختلط بين المصانع."""
    from pathlib import Path

    import config
    d = Path(str(config.DB_PATH)).parent / "model_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(model_no):
    keep = "-_"
    return "".join(c for c in str(model_no)
                   if c.isalnum() or c in keep or "\u0600" <= c <= "\u06FF")[:80]


def image_path(model_no):
    """مسار صورة الموديل إن وُجدت."""
    base = images_dir() / _safe_name(model_no)
    for ext in IMAGE_EXTS:
        p = base.with_suffix(ext)
        if p.exists():
            return p
    return None


def set_image(model_no, src_path, username="admin"):
    """ينسخ صورة من جهاز المستخدم ويربطها بالموديل.

    الصورة **وصفية بحتة** — لا أثر محاسبي لها إطلاقاً. تُنسخ داخل
    مساحة المصنع فتبقى مع النسخ الاحتياطي ولا تنكسر إن نُقل الملف
    الأصلي أو حُذف.
    """
    import shutil
    from pathlib import Path
    src = Path(str(src_path))
    if not src.exists():
        raise ValueError("الملف غير موجود")
    ext = src.suffix.lower()
    if ext not in IMAGE_EXTS:
        raise ValueError(
            "صيغة غير مدعومة — المسموح: " + " · ".join(IMAGE_EXTS))
    if src.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("حجم الصورة يتجاوز 8 ميجابايت")
    remove_image(model_no)
    dst = images_dir() / (_safe_name(model_no) + ext)
    shutil.copy2(src, dst)
    return str(dst)


def remove_image(model_no):
    """يحذف صورة الموديل إن وُجدت."""
    p = image_path(model_no)
    if p is None:
        return False
    try:
        p.unlink()
        return True
    except Exception:
        return False


def models_with_images(conn=None):
    """أرقام الموديلات التي لها صور."""
    out = set()
    try:
        for f in images_dir().iterdir():
            if f.suffix.lower() in IMAGE_EXTS:
                out.add(f.stem)
    except Exception:
        pass
    return out


def delete_model(conn, model_no, username, reason=""):
    """يحذف موديلاً بكامله — يفكّ ارتباط كل أطقمه به.

    **بلا أي أثر محاسبي**: الموديل تصنيف وصفي لا حساب له ولا يدخل في
    أي قيد. حذفه يفكّ الرابط فقط — الأطقم تبقى بأوزانها وحالاتها
    وفواتيرها كما هي تماماً، وتنتقل لمجموعة «بلا موديل».
    """
    from services.audit import log_action
    name = str(model_no or "").strip()
    if not name:
        raise ValueError("حدّد الموديل المراد حذفه")
    n = conn.execute(
        "SELECT COUNT(*) c FROM work_orders"
        " WHERE is_deleted=0 AND TRIM(COALESCE(model_no,''))=?",
        (name,)).fetchone()["c"]
    conn.execute(
        "UPDATE work_orders SET model_no=NULL"
        " WHERE TRIM(COALESCE(model_no,''))=?", (name,))
    conn.execute(
        "UPDATE wo_batch_lines SET model_no=NULL"
        " WHERE TRIM(COALESCE(model_no,''))=?", (name,))
    removed_img = remove_image(name)
    log_action(conn, username, "delete", "work_orders", None,
               f"حذف الموديل «{name}»: فُكّ عن {n} طقم"
               + (" · حُذفت صورته" if removed_img else "")
               + (f" | {reason}" if reason else ""))
    return {"model": name, "count": n, "image": removed_img}
