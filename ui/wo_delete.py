# -*- coding: utf-8 -*-
"""حذف رقم تشغيل — من دليل الموديلات ومن لوحة التحكم بالسؤال نفسه.

الحذف حذفٌ لتوريد الطقم كأنه لم يدخل (`inventory.delete_work_order`):
يُخصم وزنه من حساب الوجهة ويعود لخزينة التصنيع في قيد دفعته نفسه
بتاريخها، فيختفي من الدليل ومن لوحة التحكم ولا يبقى له أثرٌ في الأرصدة.
وما لا يُحذف (له فاتورة بيعٍ أو مرتجع، أو رقمٌ تجميعي) يُقال سببه.
"""
from database.database import db
from models import inventory
from services import karat_view as kv
from services import numfmt as _nf
from ui.widgets.common import ask, err, info, warn


def delete_wo(parent, wo_id, user):
    """يسأل ثم يحذف — يعيد True إن حُذف."""
    try:
        with db(readonly=True) as conn:
            d = inventory.work_order_delete_info(conn, wo_id)
        if d["blocked"]:
            warn(parent, d["blocked"], "لا يُحذف هذا الطقم")
            return False
        w = f"{_nf.f2(kv.g(d['weight']))} {kv.unit()}"
        lines = [f"حذف رقم التشغيل {d['wo_no']} نهائياً؟", ""]
        lines.append(f"• الموديل: {d['model'] or '— بلا موديل —'}"
                     + ("  (آخر طقمٍ فيه، فيختفي الموديل من الدليل)"
                        if d["model"] and not d["model_left"] else ""))
        lines.append(f"• وزنه المقيد: {w}")
        if d["date"]:
            if d["others"]:
                lines.append(f"• يُخرج من دفعة توريده بتاريخ {d['date']}:"
                             f" يُخصم وزنه من {d['dest'] or 'الذهب المشغول'}"
                             " ويعود لخزينة التصنيع — وبقية أطقم الدفعة"
                             " كما هي.")
            else:
                lines.append(f"• هو وحده في دفعة توريده بتاريخ {d['date']}:"
                             " يُحذف قيدها كله، فيُخصم وزنه من "
                             f"{d['dest'] or 'الذهب المشغول'} ويعود لخزينة"
                             " التصنيع.")
        lines.append("• يختفي من دليل الموديلات ومن لوحة التحكم.")
        lines += ["", "لا رجوع عن الحذف إلا بإدخاله من جديد في «الوارد من"
                  " التصنيع»."]
        if not ask(parent, "\n".join(lines), "حذف رقم تشغيل"):
            return False
        with db() as conn:
            r = inventory.delete_work_order(conn, wo_id, user["username"])
        info(parent, f"حُذف رقم التشغيل {r['wo_no']}"
                     f" ({_nf.f2(kv.g(r['weight']))} {kv.unit()}).\n"
                     "خرج من دليل الموديلات ولوحة التحكم، وعُدّل قيد توريده"
                     " بتاريخه.")
        return True
    except Exception as e:
        err(parent, e)
        return False
