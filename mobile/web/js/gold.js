/* معادلات الذهب — منقولةٌ سطراً بسطر من `services/gold_math.py`
 * و`services/karat_view.py` في البرنامج، بترتيب العمليات نفسه (فالفاصلة
 * العائمة تعطي الناتج نفسه بالضبط) وبتقريب بايثون نفسه (`Num.pyRound`).
 * وفحص `mobile/tests/parity` يقارن كل دالةٍ هنا بنظيرتها هناك.
 *
 * القاعدة كما في البرنامج: كل وزنٍ يُخزَّن بمكافئ عيار 18، والعيار في
 * الشاشة وحدةُ قراءةٍ وكتابة فقط.
 */
(function (root) {
  "use strict";
  const N = root.Num || (typeof require !== "undefined" ? require("./num.js") : null);
  const R = N.pyRound;

  const BASE = 18;
  const KARATS = [18, 21, 22, 24];
  const WEIGHT_DECIMALS = 3, CASH_DECIMALS = 2;
  const VAT_RATE = 0.15, STONE_DISCOUNT_RATE = 0.5;

  // ── gold_math ──
  function toBase(weight, karat) {                  // to_base_karat
    return R(weight * karat / BASE, WEIGHT_DECIMALS);
  }
  function fromBase(weight18, karat) {              // from_base_karat
    let k = parseInt(karat || BASE, 10);
    if (!isFinite(k)) k = BASE;
    const w = Number(weight18 || 0);
    if (k <= 0 || k === BASE) return R(w, WEIGHT_DECIMALS);
    return R(w * BASE / k, WEIGHT_DECIMALS);
  }
  function stonesAfter(big, rate) {                 // stones_after_discount
    if (rate === undefined) rate = STONE_DISCOUNT_RATE;
    return R(big * (1.0 - rate), WEIGHT_DECIMALS);
  }
  function registered(gold, small, big, rate) {     // registered_weight
    return R(gold + (small || 0) + stonesAfter(big || 0, rate), WEIGHT_DECIMALS);
  }
  function standing(gold, small, big) {             // standing_gold
    return R(gold + (small || 0) + (big || 0), WEIGHT_DECIMALS);
  }
  function totalWages(ratePerGram, regWeight) {     // total_wages
    return R(ratePerGram * regWeight, CASH_DECIMALS);
  }
  function wagesVat(wages) {                        // wages_vat
    return R(wages * VAT_RATE, CASH_DECIMALS);
  }

  // ── karat_view (العيار وحدة عرض) ──
  function g(weight18, karat) { return fromBase(weight18, karat); }
  function store(view, karat) {
    const k = parseInt(karat, 10);
    if (k === BASE) return R(Number(view || 0), WEIGHT_DECIMALS);
    return toBase(Number(view || 0), k);
  }
  function rate(rate18, karat) {                    // أجر الجرام: 18 ← العرض
    const k = parseInt(karat, 10);
    if (k === BASE) return R(Number(rate18 || 0), 2);
    return R(Number(rate18 || 0) * k / BASE, 2);
  }
  function rateStore(view, karat) {                 // العرض ← 18
    const k = parseInt(karat, 10);
    if (k === BASE) return R(Number(view || 0), 2);
    return R(Number(view || 0) * BASE / k, 6);
  }
  // `_wage_store` في شاشة المبيعات: ستّ منازل في كل عيار (الأجرة
  // المقطوعة تُقسَم على الوزن فلا تُقرَّب إلى منزلتين)
  function wageStore(view, karat) {
    const k = parseInt(karat, 10) || BASE;
    return R(Number(view || 0) * BASE / k, 6);
  }
  function wageView(rate18, karat) {                // `_wage_view`: بلا تقريب
    const k = parseInt(karat, 10) || BASE;
    return Number(rate18 || 0) * k / BASE;
  }

  // ── سطر الإدخال كما في شاشة المبيعات (`_parts_changed`) ──
  // الأرقام بعيار السطر: الأحجار بعد الخصم، والقائم، والمقيد (ما لم
  // يُكتب بيد)
  function entryDerive(gold, small, big, rate, regManual, regTyped) {
    const after = stonesAfter(big, rate);
    const stand = standing(gold, small, big);
    const reg = regManual ? regTyped : R(gold + small + after, 3);
    return { after, standing: stand, reg };
  }
  // كتابة «بعد الخصم» يدوياً تعيد اشتقاق النسبة (`_after_changed`)
  function rateFromAfter(big, after, current) {
    if (big > 0) return Math.max(0.0, Math.min(1.0, 1.0 - after / big));
    return current;
  }

  // ── السند: سطر ذهب بعياره ← مكافئ 18 (`create_voucher`) ──
  function voucherGold(weight, karat) {
    const wt = R(Number(weight || 0), 2);
    const kt = parseInt(karat || 18, 10);
    return { weight: wt, karat: kt, equiv: toBase(wt, kt) };
  }

  const api = {
    BASE, KARATS, VAT_RATE, STONE_DISCOUNT_RATE,
    toBase, fromBase, stonesAfter, registered, standing, totalWages, wagesVat,
    g, store, rate, rateStore, wageStore, wageView, entryDerive, rateFromAfter,
    voucherGold,
  };
  root.Gold = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
