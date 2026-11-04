# -*- coding: utf-8 -*-
"""حذف رقم تشغيل — من دليل الموديلات ومن لوحة التحكم بالسؤال نفسه.

الحذف **حذفٌ فقط** (5.1.8): يختفي الطقم أو الرقم التجميعي من الدليل
ولوحة التحكم وقوائم البيع، ولا يتغيّر أي رصيد — خزينة التصنيع والذهب
المشغول وقيد التوريد وفواتير البيع والمرتجع كما هي
(`inventory.delete_work_order`).
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
            warn(parent, d["blocked"], "لا يُحذف هذا الرقم")
            return False
        w = f"{_nf.f2(kv.g(d['weight']))} {kv.unit()}"
        what = "الرقم التجميعي" if d["bulk"] else "رقم التشغيل"
        lines = [f"حذف {what} {d['wo_no']}؟", ""]
        lines.append(f"• الموديل: {d['model'] or '— بلا موديل —'}"
                     + ("  (آخر رقمٍ فيه، فيختفي الموديل من الدليل)"
                        if d["model"] and not d["model_left"] else ""))
        if d["bulk"]:
            lines.append(f"• رصيده الحالي: {w} — والتوريد القادم بهذا الرقم"
                         " يبدأ رصيداً جديداً")
        elif d["sold"]:
            lines.append(f"• مباع ({w})")
        else:
            lines.append(f"• في الخزنة: {w}")
        if d["invoices"]:
            lines.append(f"• فواتيره ({len(d['invoices'])}) تبقى كما هي")
        lines.append("• يختفي من دليل الموديلات ولوحة التحكم وقوائم البيع.")
        lines += ["", "لا يتغيّر أي رصيد: خزينة التصنيع والذهب المشغول وقيد"
                  " التوريد والفواتير كما هي."]
        if not ask(parent, "\n".join(lines), f"حذف {what}"):
            return False
        with db() as conn:
            r = inventory.delete_work_order(conn, wo_id, user["username"])
        info(parent, f"حُذف {what} {r['wo_no']} من القوائم.\n"
                     "ولم يتغيّر أي رصيد.")
        return True
    except Exception as e:
        err(parent, e)
        return False
