# -*- coding: utf-8 -*-
"""
المعادلات الذهبية الأساسية من وثيقة المتطلبات — منطق خالص قابل للاختبار.
(جاهزة ومكتملة، لأنها رياضيات صرفة لا تعتمد على قاعدة البيانات.)
"""
from config import (BASE_KARAT, CASH_DECIMALS, MELTING_LOSS_LIMIT,
                    STONE_DISCOUNT_RATE, VAT_RATE, WEIGHT_DECIMALS)


def to_base_karat(weight: float, karat: int) -> float:
    """تحويل أي وزن إلى مكافئه بعيار 18:  الوزن × العيار ÷ 18."""
    return round(weight * karat / BASE_KARAT, WEIGHT_DECIMALS)


# العيارات المتداولة في السوق — تُعرض للاختيار في الكشوف والتقارير
KARATS = (18, 21, 22, 24)


def from_base_karat(weight18: float, karat: int) -> float:
    """عكس `to_base_karat`: يعرض وزناً مقيداً بعيار 18 بعيار آخر.

    القيد في النظام كله بمكافئ عيار 18 — وهذا هو الصحيح محاسبياً لأن
    الميزان لا يتزن إلا بوحدة واحدة. لكن السوق يتعامل بـ21 و22 و24،
    فيُراد **عرض** الرقم نفسه بالعيار المتداول:  الوزن18 × 18 ÷ العيار.

    التحويل عرضٌ محض لا يمسّ القيد: `to_base_karat(from_base_karat(w, k), k)`
    تُعيد `w` نفسه.
    """
    try:
        k = int(karat or BASE_KARAT)
    except (TypeError, ValueError):
        k = BASE_KARAT
    w = float(weight18 or 0)
    if k <= 0 or k == BASE_KARAT:
        return round(w, WEIGHT_DECIMALS)
    return round(w * BASE_KARAT / k, WEIGHT_DECIMALS)


def stones_after_discount(big_stones: float,
                          discount_rate: float = STONE_DISCOUNT_RATE) -> float:
    """الأحجار بعد الخصم التجاري = وزن الأحجار × (1 − نسبة الخصم)."""
    return round(big_stones * (1.0 - discount_rate), WEIGHT_DECIMALS)


def registered_weight(gold_weight: float, small_stones: float = 0.0,
                      big_stones: float = 0.0,
                      discount_rate: float = STONE_DISCOUNT_RATE) -> float:
    """الوزن المقيد (صاحب الأثر المالي والمخزني) =
    الذهب + الفصوص + الأحجار بعد الخصم."""
    return round(gold_weight + small_stones
                 + stones_after_discount(big_stones, discount_rate),
                 WEIGHT_DECIMALS)


def standing_gold(gold_weight: float, small_stones: float = 0.0,
                  big_stones: float = 0.0) -> float:
    """الذهب القائم = الذهب + الفصوص + الأحجار (قبل الخصم) — للمعرفة
    والإحصاء فقط، بلا أي أثر محاسبي أو مخزني."""
    return round(gold_weight + small_stones + big_stones, WEIGHT_DECIMALS)


def total_wages(rate_per_gram: float, reg_weight: float) -> float:
    """إجمالي الأجور = الأجر للجرام × الوزن المقيد."""
    return round(rate_per_gram * reg_weight, CASH_DECIMALS)


def wages_vat(wages: float) -> float:
    """ضريبة القيمة المضافة (15%) — على الأجور فقط."""
    return round(wages * VAT_RATE, CASH_DECIMALS)


def expected_pure_24k(weight: float, karat: int) -> float:
    """المتوقع صافياً عيار 24 من كسرٍ ما:  الوزن × العيار ÷ 24."""
    return round(weight * karat / 24, WEIGHT_DECIMALS)


def melting_shrinkage(expected_24k: float, actual_24k: float
                      ) -> tuple[float, float, bool]:
    """
    فاقد الصهر: يعيد (الفاقد بالجرام 24، نسبته، هل تجاوز الحد 1.5%).
    الفاقد يُقيَّد كمصروف وزني بمكافئ عيار 18 (× 24 ÷ 18).
    """
    loss = round(expected_24k - actual_24k, WEIGHT_DECIMALS)
    ratio = (loss / expected_24k) if expected_24k else 0.0
    return loss, round(ratio, 4), ratio > MELTING_LOSS_LIMIT
