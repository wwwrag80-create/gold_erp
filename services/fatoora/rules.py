# -*- coding: utf-8 -*-
"""التحقق المحلي من قواعد الهيئة (BR-KSA / BR-CO) قبل الإرسال.

الهيئة ترفض المستند المخالف وتعيده برسالة خطأ؛ والأفضل أن يُكشف الخطأ
هنا قبل أن يُصدَر مستندٌ يدخل السلسلة ثم يُرفض. القواعد هنا هي التي
تنطبق على مستندات هذا النظام (فواتير البيع ومرتجعاتها بضريبة 15%)،
بأرقامها في دليل الهيئة ليُعرف مصدر كل رسالة.
"""
import re
from decimal import Decimal

from services.fatoora import profile as pf
from services.fatoora import ubl


def check_document(doc):
    """يعيد (أخطاء, تنبيهات) — كلٌّ قائمة نصوص عربية مع رقم القاعدة."""
    errors, warns = [], []
    s, b = doc.get("seller") or {}, doc.get("buyer") or {}
    std = doc.get("subtype") == "standard"

    # ── البائع ──
    if not pf.valid_vat(s.get("vat")):
        errors.append("BR-KSA-39/40: الرقم الضريبي للبائع 15 رقماً يبدأ "
                      "وينتهي بـ3")
    if not pf.valid_crn(s.get("crn"), s.get("crn_scheme") or "CRN"):
        errors.append("BR-KSA-08: معرّف البائع (السجل التجاري) غير صالح")
    if not str(s.get("name", "")).strip():
        errors.append("BR-06: اسم البائع القانوني مطلوب")
    for f, lbl in (("street", "الشارع"), ("district", "الحي"),
                   ("city", "المدينة")):
        if not str(s.get(f, "")).strip():
            errors.append(f"BR-KSA-09: {lbl} في عنوان البائع مطلوب")
    if not pf.valid_building(s.get("building")):
        errors.append("BR-KSA-37: رقم مبنى البائع 4 أرقام")
    if not pf.valid_postal(s.get("postal")):
        errors.append("BR-KSA-66: الرمز البريدي للبائع 5 أرقام")

    # ── المشتري ──
    if std:
        if not (pf.valid_vat(b.get("vat")) or str(b.get("crn", "")).strip()):
            errors.append("BR-KSA-81: الفاتورة الضريبية تتطلّب رقم المشتري "
                          "الضريبي أو معرّفاً آخر")
        if not str(b.get("name", "")).strip():
            errors.append("BR-KSA-42: اسم المشتري مطلوب في الفاتورة الضريبية")
        for p in pf.buyer_problems(b):
            errors.append(f"BR-KSA-63/67: عنوان المشتري ناقص — {p}")
    elif b.get("vat") and not pf.valid_vat(b.get("vat")):
        warns.append("BR-KSA-44: الرقم الضريبي للمشتري بصيغة غير صحيحة")

    # ── المستند ──
    if doc.get("kind") not in ubl.TYPE_CODES:
        errors.append("BR-KSA-05: نوع المستند غير معروف")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(doc.get("issue_date", ""))):
        errors.append("BR-KSA-04: تاريخ الإصدار بصيغة YYYY-MM-DD")
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", str(doc.get("issue_time", ""))):
        errors.append("BR-KSA-70: وقت الإصدار بصيغة HH:MM:SS")
    try:
        if int(doc.get("icv", 0)) < 1:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("BR-KSA-33: عدّاد الفواتير (ICV) رقمٌ موجب")
    if not doc.get("pih"):
        errors.append("BR-KSA-26: بصمة المستند السابق (PIH) مطلوبة")
    if doc.get("kind") in ("credit", "debit"):
        if not doc.get("billing_refs"):
            errors.append("BR-KSA-56: الإشعار يجب أن يشير لرقم الفاتورة "
                          "الأصلية")
        if not str(doc.get("reason", "")).strip():
            errors.append("BR-KSA-17: سبب إصدار الإشعار مطلوب")
    if std and not doc.get("supply_date", doc.get("issue_date")):
        errors.append("BR-KSA-15: تاريخ التوريد مطلوب في الفاتورة الضريبية")

    # ── الأسطر والإجماليات ──
    lines = doc.get("lines") or []
    if not lines:
        errors.append("BR-16: المستند بلا أسطر")
    for i, li in enumerate(lines, 1):
        if not str(li.get("name", "")).strip():
            errors.append(f"BR-25: اسم الصنف في السطر {i} مطلوب")
        if ubl.money(li.get("amount")) < 0:
            errors.append(f"BR-27: مبلغ السطر {i} سالب")
    if lines:
        t = ubl.totals(lines, float(doc.get("rate", 15.0)))
        if t["gross"] != t["net"] + t["vat"]:
            errors.append("BR-CO-15: الإجمالي شامل الضريبة لا يساوي "
                          "الصافي + الضريبة")
        expect = doc.get("expect_gross")
        if expect is not None and abs(t["gross"] - ubl.money(expect)) > \
                Decimal("0.01"):
            warns.append(f"الإجمالي المحسوب {t['gross']} يخالف إجمالي "
                         f"الفاتورة المسجّل {ubl.money(expect)}")
    try:
        ubl.tlv(1, s.get("name", ""))
    except ValueError:
        errors.append("BR-KSA-27: اسم البائع أطول مما يسعه رمز QR")
    return errors, warns
