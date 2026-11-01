/* منطق الحسابات مع المحلات — بلا واجهة، فيُختبر وحده (`mobile/tests`).
 *
 * الأثر على حساب المحل كما يرحّله البرنامج على الكمبيوتر
 * (`models/invoices.py` و`models/vouchers.py`)، والموجب «عليه»:
 *   فاتورة بيع   : ذهب + الوزن المقيد (مكافئ 18) · نقد + (الأجور + الضريبة)
 *   مرتجع بيع    : ذهب − الوزن المقيد            · نقد − (الأجور + الضريبة)
 *   سند قبض      : ذهب − مكافئ كل سطر ذهب − الخصم الوزني
 *                  نقد − النقد − الخصم النقدي، وفرق الصافي بإشارته
 *   سند صرف      : ذهب + مكافئ كل سطر ذهب      · نقد + النقد
 * والرصيد الجاري يُقرَّب كما يقرّبه كشف الحساب هناك: الذهب ثلاث منازل
 * والنقد منزلتان عند كل حركة.
 *
 * **الفرق المقصود عن البرنامج**: لا مخزون ولا «وارد من التصنيع». رقم
 * التشغيل يُكتب بأوزانه في الفاتورة ولو لم يُسجَّل قبلها، وإن كان قد
 * رجع بمرتجعٍ سابق تُعبَّأ أوزانه من ذلك المرتجع (`woLast`).
 */
(function (root) {
  "use strict";
  const Num = root.Num || require("./num.js");
  const Gold = root.Gold || require("./gold.js");
  const R = Num.pyRound;

  const KIND_LABEL = {
    sale: "فاتورة بيع", sale_return: "مرتجع بيع",
    receipt: "سند قبض", payment: "سند صرف", opening: "رصيد افتتاحي",
  };
  const PREFIX = { sale: "S", sale_return: "R", receipt: "RV", payment: "PV" };

  function newState() {
    return {
      settings: {
        name: "", vatNo: "", phone: "", address: "",
        viewKarat: 18, stoneRate: Gold.STONE_DISCOUNT_RATE,
        showBalanceOnInvoice: true, theme: "auto", lastBackup: "",
      },
      seq: { S: 0, R: 0, RV: 0, PV: 0 },
      shops: [], invoices: [], vouchers: [], held: [],
    };
  }

  let _uid = 0;
  function uid(p) {
    _uid = (_uid + 1) % 1e6;
    return p + Date.now().toString(36) + _uid.toString(36) +
      Math.floor(Math.random() * 1e6).toString(36);
  }
  function today() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  function nowStamp() { return new Date().toISOString(); }

  function nextNo(st, kind) {
    const p = PREFIX[kind];
    st.seq[p] = (st.seq[p] || 0) + 1;
    return `${p}-${String(st.seq[p]).padStart(5, "0")}`;
  }

  // ══ المحلات ══
  function shopById(st, id) { return st.shops.find((s) => s.id === id) || null; }
  function saveShop(st, data) {
    const name = String(data.name || "").trim();
    if (!name) throw new Error("اكتب اسم المحل");
    const dup = st.shops.find((s) => s.name.trim() === name && s.id !== data.id);
    if (dup) throw new Error(`يوجد محلٌّ بالاسم نفسه: ${name}`);
    const rec = {
      id: data.id || uid("sh_"),
      name, phone: String(data.phone || "").trim(),
      notes: String(data.notes || "").trim(),
      agreedWage18: Number(data.agreedWage18 || 0),
      openGold18: R(Number(data.openGold18 || 0), 3),
      openCash: R(Number(data.openCash || 0), 2),
      openDate: data.openDate || today(),
      createdAt: data.createdAt || nowStamp(),
    };
    const i = st.shops.findIndex((s) => s.id === rec.id);
    if (i >= 0) st.shops[i] = rec; else st.shops.push(rec);
    return rec;
  }
  function deleteShop(st, id) {
    const used = st.invoices.some((d) => d.shopId === id) ||
      st.vouchers.some((d) => d.shopId === id);
    if (used) throw new Error("للمحل فواتير أو سندات — احذفها أولاً أو أبقِ المحل");
    st.shops = st.shops.filter((s) => s.id !== id);
  }

  // ══ سطر الفاتورة ══
  // `e`: ما في سطر الإدخال بعيار السطر (كما يُكتب في الشاشة)
  function buildLine(e) {
    const k = parseInt(e.karat || 18, 10);
    if (e.wageOnly) {
      const amount = R(Number(e.amount || 0), 2);
      if (amount <= 0) throw new Error("أدخل مبلغ الأجر لسطر «أجر فقط»");
      return { wageOnly: true, amount, wages: amount, note: String(e.note || "").trim(),
        wo: "", model: "", karat: 0, reg18: 0, gold18: 0, small18: 0, big18: 0,
        after18: 0, standing18: 0, diamond: 0, rate18: 0 };
    }
    const wo = String(e.wo || "").trim();
    if (!wo) throw new Error("اكتب رقم التشغيل");
    const reg = Number(e.reg || 0);
    if (!(reg > 0)) throw new Error(`أدخل وزن الطقم ${wo} — الوزن المقيد صفر`);
    // الوزن المقترح (من مرتجعٍ أو بيعٍ سابق) يُعتمد بدقّته المخزَّنة ما دام
    // لم يُغيَّر — كـ`_reg_exact` في البرنامج: الخانة تعرض منزلتين، وعيار
    // 21 ذهاباً وإياباً كان يترك 0.001 جم من لا شيء
    const ex = e.exact18 || {};
    const st18 = (key, view) => {
      const x = ex[key];
      if (x !== undefined && Math.abs(Number(view || 0) - Gold.g(x, k)) <= 0.0051) return x;
      return Gold.store(Number(view || 0), k);
    };
    const reg18 = R(st18("reg18", reg), 3);
    // الأجر المقترح (المتفق عليه أو أجر حركةٍ سابقة) بدقّته إن مُرِّر —
    // الخانة تعرضه بمنزلتين، فقراءته منها تُنقص الأجرة هللات بعيار 21
    const rate18 = e.rate18 !== undefined && e.rate18 !== null ? Number(e.rate18)
      : Gold.wageStore(Number(e.wage || 0), k);
    return {
      wageOnly: false, wo, model: String(e.model || "").trim(), karat: k,
      gold18: st18("gold18", e.gold), small18: st18("small18", e.small),
      big18: st18("big18", e.big), after18: st18("after18", e.after),
      standing18: st18("standing18", e.standing),
      reg18, diamond: R(Math.max(0, Number(e.diamond || 0)), 3),
      stoneRate: e.stoneRate === undefined ? Gold.STONE_DISCOUNT_RATE : Number(e.stoneRate),
      rate18, wages: Gold.totalWages(rate18, reg18),
      note: String(e.note || "").trim(),
    };
  }

  // السطر المحفوظ ← سطر الإدخال بعيار k (للتعديل والتعبئة التلقائية)
  function lineToEntry(li, k) {
    k = parseInt(k || li.karat || 18, 10);
    if (li.wageOnly) return { wageOnly: true, amount: li.amount, note: li.note };
    return {
      wo: li.wo, model: li.model, karat: k,
      gold: Gold.g(li.gold18, k), small: Gold.g(li.small18, k),
      big: Gold.g(li.big18, k), after: Gold.g(li.after18, k),
      standing: Gold.g(li.standing18, k), reg: Gold.g(li.reg18, k),
      diamond: li.diamond, stoneRate: li.stoneRate,
      wage: Gold.wageView(li.rate18, k), note: li.note,
      exact18: { gold18: li.gold18, small18: li.small18, big18: li.big18,
        after18: li.after18, standing18: li.standing18, reg18: li.reg18 },
    };
  }

  // الإجماليات كما في `_save`: الوزن يُجمع بتقريبٍ عند كل سطر
  function totals(lines, applyVat) {
    let w = 0;
    for (const li of lines) if (!li.wageOnly) w = R(w + Number(li.reg18 || 0), 3);
    const totalW18 = R(w, 3);
    let s = 0;
    for (const li of lines) s += li.wageOnly ? R(Number(li.amount), 2) : li.wages;
    const wages = R(s, 2);
    const vatAmt = applyVat ? Gold.wagesVat(wages) : 0;
    const grand = R(wages + vatAmt, 2);
    return { totalW18, wages, vatAmt, grand };
  }

  function checkLines(lines) {
    if (!lines.length) throw new Error("أضف طقماً واحداً على الأقل");
    const seen = new Set();
    for (const li of lines) {
      if (li.wageOnly) continue;
      const key = li.wo.trim();
      if (seen.has(key)) {
        throw new Error(`الطقم ${key} مكرّر في الفاتورة — القطعة الواحدة لا تُباع ` +
          "مرتين في مستندٍ واحد. احذف السطر المكرّر.");
      }
      seen.add(key);
    }
  }

  function saveInvoice(st, draft) {
    if (!shopById(st, draft.shopId)) throw new Error("اختر المحل");
    if (!["sale", "sale_return"].includes(draft.kind)) throw new Error("نوع الفاتورة غير صحيح");
    const lines = draft.lines || [];
    checkLines(lines);
    const t = totals(lines, !!draft.vat);
    const old = draft.id ? st.invoices.find((d) => d.id === draft.id) : null;
    if (old && old.kind !== draft.kind) {
      throw new Error("لا يتغيّر نوع الفاتورة بعد ترحيلها — احذفها وأصدر الصحيح");
    }
    const rec = {
      id: old ? old.id : uid("in_"),
      no: old ? old.no : nextNo(st, draft.kind),
      kind: draft.kind, shopId: draft.shopId,
      date: draft.date || today(), vat: !!draft.vat,
      desc: String(draft.desc || "").trim(),
      lines: lines.map((x) => Object.assign({}, x)),
      ...t,
      createdAt: old ? old.createdAt : nowStamp(),
      updatedAt: old ? nowStamp() : "",
    };
    if (old) st.invoices[st.invoices.indexOf(old)] = rec; else st.invoices.push(rec);
    if (draft.heldId) st.held = st.held.filter((h) => h.id !== draft.heldId);
    return rec;
  }
  function deleteInvoice(st, id) { st.invoices = st.invoices.filter((d) => d.id !== id); }

  // ══ السندات ══
  function voucherRows(rows) {
    const out = [];
    for (const r of rows || []) {
      if ((r.kind || "gold") === "gold") {
        const v = Gold.voucherGold(r.weight, r.karat);
        if (v.weight <= 0) continue;
        if (!Gold.KARATS.includes(v.karat)) throw new Error(`عيار غير مدعوم: ${v.karat}`);
        out.push({ kind: "gold", weight: v.weight, karat: v.karat, equiv: v.equiv,
          amount: 0, notes: String(r.notes || "").trim() });
      } else {
        const amt = R(Number(r.amount || 0), 2);
        if (amt <= 0) continue;
        out.push({ kind: "cash", weight: 0, karat: 0, equiv: 0, amount: amt,
          notes: String(r.notes || "").trim() });
      }
    }
    return out;
  }

  function saveVoucher(st, draft) {
    if (!shopById(st, draft.shopId)) throw new Error("اختر المحل");
    if (!["receipt", "payment"].includes(draft.kind)) throw new Error("نوع سند غير صحيح");
    const rows = voucherRows(draft.rows);
    const discCash = R(Number(draft.discCash || 0), 2);
    const discGold18 = R(Number(draft.discGold18 || 0), 3);
    const netDiff = R(Number(draft.netDiff || 0), 2);
    for (const v of [discCash, discGold18]) if (v < 0) throw new Error("الخصومات لا تقبل السالب");
    if (draft.kind === "payment" && (discCash || discGold18)) {
      throw new Error("الخصومات المسموحة تخص سندات القبض فقط");
    }
    if (!rows.length && !discCash && !discGold18 && !netDiff) {
      throw new Error("أضف سطراً واحداً على الأقل في السند");
    }
    const old = draft.id ? st.vouchers.find((d) => d.id === draft.id) : null;
    if (old && old.kind !== draft.kind) {
      throw new Error("لا يتغيّر نوع السند بعد ترحيله — احذفه وأصدر الصحيح");
    }
    let eq = 0, cash = 0;
    for (const r of rows) { eq += r.equiv; cash += r.amount; }
    const rec = {
      id: old ? old.id : uid("vo_"),
      no: old ? old.no : nextNo(st, draft.kind),
      kind: draft.kind, shopId: draft.shopId, date: draft.date || today(),
      notes: String(draft.notes || "").trim(), rows,
      gold18: R(eq, 3), cash: R(cash, 2), discCash, discGold18, netDiff,
      createdAt: old ? old.createdAt : nowStamp(),
      updatedAt: old ? nowStamp() : "",
    };
    if (old) st.vouchers[st.vouchers.indexOf(old)] = rec; else st.vouchers.push(rec);
    return rec;
  }
  function deleteVoucher(st, id) { st.vouchers = st.vouchers.filter((d) => d.id !== id); }

  // ══ الأثر والأرصدة ══
  // gd/gc ذهب مدين/دائن (مكافئ 18)، cd/cc نقد — والموجب «عليه»
  function effects(doc) {
    if (doc.kind === "sale") return { gd: doc.totalW18, gc: 0, cd: doc.grand, cc: 0 };
    if (doc.kind === "sale_return") return { gd: 0, gc: doc.totalW18, cd: 0, cc: doc.grand };
    if (doc.kind === "receipt") {
      let gc = 0, cc = 0;
      for (const r of doc.rows) { gc += r.equiv; cc += r.amount; }
      gc = R(R(gc, 3) + doc.discGold18, 3);
      cc = R(R(cc, 2) + doc.discCash + (doc.netDiff < 0 ? -doc.netDiff : 0), 2);
      return { gd: 0, gc, cd: doc.netDiff > 0 ? doc.netDiff : 0, cc };
    }
    if (doc.kind === "payment") {
      let gd = 0, cd = 0;
      for (const r of doc.rows) { gd += r.equiv; cd += r.amount; }
      return { gd: R(gd, 3), gc: 0, cd: R(cd + (doc.netDiff > 0 ? doc.netDiff : 0), 2),
        cc: doc.netDiff < 0 ? -doc.netDiff : 0 };
    }
    return { gd: 0, gc: 0, cd: 0, cc: 0 };
  }

  function docsOf(st, shopId) {
    const out = [];
    for (const d of st.invoices) if (!shopId || d.shopId === shopId) out.push(d);
    for (const d of st.vouchers) if (!shopId || d.shopId === shopId) out.push(d);
    out.sort(docOrder);
    return out;
  }
  function docOrder(a, b) {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    return (a.createdAt || "") < (b.createdAt || "") ? -1 :
      (a.createdAt || "") > (b.createdAt || "") ? 1 : 0;
  }

  function openingRow(shop) {
    if (!shop || (!shop.openGold18 && !shop.openCash)) return null;
    return {
      kind: "opening", date: shop.openDate, no: "", createdAt: "",
      gd: shop.openGold18 > 0 ? shop.openGold18 : 0,
      gc: shop.openGold18 < 0 ? -shop.openGold18 : 0,
      cd: shop.openCash > 0 ? shop.openCash : 0,
      cc: shop.openCash < 0 ? -shop.openCash : 0,
    };
  }

  // كشف الحساب: رصيدٌ سابق (إن حُدّدت بداية) ثم كل مستندٍ بسطرٍ واحد
  function statement(st, shopId, from, to, exclude) {
    const shop = shopById(st, shopId);
    const items = [];
    const op = openingRow(shop);
    if (op) items.push({ doc: null, e: op, date: op.date, kind: "opening", order: "" });
    for (const d of docsOf(st, shopId)) {
      if (exclude && d.id === exclude) continue;
      items.push({ doc: d, e: effects(d), date: d.date, kind: d.kind, order: d.createdAt });
    }
    items.sort((a, b) => a.date !== b.date ? (a.date < b.date ? -1 : 1)
      : a.kind === "opening" ? -1 : b.kind === "opening" ? 1
        : a.order < b.order ? -1 : a.order > b.order ? 1 : 0);
    let gb = 0, cb = 0;
    const rows = [];
    let prevG = 0, prevC = 0, hasPrev = false;
    for (const it of items) {
      if (from && it.date < from) {
        prevG += it.e.gd - it.e.gc; prevC += it.e.cd - it.e.cc; hasPrev = true;
        continue;
      }
      if (!rows.length && from) {
        gb = R(prevG, 3); cb = R(prevC, 2);
        rows.push({ kind: "prev", label: "رصيد سابق", date: from, no: "", desc: "",
          gd: 0, gc: 0, cd: 0, cc: 0, gbal: gb, cbal: cb, doc: null });
      }
      if (to && it.date > to) continue;
      gb = R(gb + it.e.gd - it.e.gc, 3);
      cb = R(cb + it.e.cd - it.e.cc, 2);
      rows.push({
        kind: it.kind, label: KIND_LABEL[it.kind], date: it.date,
        no: it.doc ? it.doc.no : "", desc: it.doc ? (it.doc.desc || it.doc.notes || "") : "",
        ...it.e, gbal: gb, cbal: cb, doc: it.doc,
      });
    }
    if (!rows.length && from && hasPrev) {
      gb = R(prevG, 3); cb = R(prevC, 2);
      rows.push({ kind: "prev", label: "رصيد سابق", date: from, no: "", desc: "",
        gd: 0, gc: 0, cd: 0, cc: 0, gbal: gb, cbal: cb, doc: null });
    }
    return { rows, gold18: gb, cash: cb };
  }

  function balance(st, shopId, exclude) {
    const s = statement(st, shopId, null, null, exclude);
    return { gold18: s.gold18, cash: s.cash };
  }
  // الرصيد قبل المستند وبعده **في موضعه من الكشف** — لا الرصيد اليوم:
  // فاتورةٌ قديمة تُطبع برصيدها يومها، لا بما جاء بعدها من سندات
  function balanceAround(st, doc) {
    const rows = statement(st, doc.shopId).rows;
    const i = rows.findIndex((r) => r.doc && r.doc.id === doc.id);
    if (i < 0) {
      const before = balance(st, doc.shopId, doc.id);
      const e = effects(doc);
      return { before, after: { gold18: R(before.gold18 + e.gd - e.gc, 3), cash: R(before.cash + e.cd - e.cc, 2) } };
    }
    const prev = i > 0 ? rows[i - 1] : null;
    return {
      before: { gold18: prev ? prev.gbal : 0, cash: prev ? prev.cbal : 0 },
      after: { gold18: rows[i].gbal, cash: rows[i].cbal },
    };
  }

  function allBalances(st) {
    const out = {};
    for (const s of st.shops) out[s.id] = balance(st, s.id);
    return out;
  }

  // ══ حركة رقم التشغيل ══
  function woHistory(st, woNo) {
    const key = String(woNo || "").trim();
    const out = [];
    if (!key) return out;
    for (const d of st.invoices) {
      d.lines.forEach((li, idx) => {
        if (!li.wageOnly && li.wo.trim() === key) {
          out.push({ inv: d, line: li, idx, kind: d.kind, date: d.date,
            createdAt: d.createdAt, shop: shopById(st, d.shopId) });
        }
      });
    }
    out.sort((a, b) => docOrder(a.inv, b.inv));
    return out;
  }
  // آخر حركةٍ للرقم — يُستبعد منها مستندٌ يُعدَّل الآن
  function woLast(st, woNo, excludeInvoiceId) {
    const h = woHistory(st, woNo).filter((m) => m.inv.id !== excludeInvoiceId);
    return h.length ? h[h.length - 1] : null;
  }
  function daysBetween(a, b) {
    const t = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
    return Math.round((t(b) - t(a)) / 86400000);
  }

  // ══ نسخة احتياطية ══
  const BACKUP_FORMAT = "jadeite-mobile-backup";
  function toBackup(st) {
    return { format: BACKUP_FORMAT, version: 1, savedAt: nowStamp(),
      settings: st.settings, seq: st.seq, shops: st.shops,
      invoices: st.invoices, vouchers: st.vouchers, held: st.held };
  }
  function fromBackup(obj) {
    if (!obj || obj.format !== BACKUP_FORMAT) {
      throw new Error("الملف ليس نسخةً احتياطية من هذا التطبيق");
    }
    const st = newState();
    Object.assign(st.settings, obj.settings || {});
    Object.assign(st.seq, obj.seq || {});
    for (const k of ["shops", "invoices", "vouchers", "held"]) {
      st[k] = Array.isArray(obj[k]) ? obj[k] : [];
    }
    return st;
  }

  const api = {
    KIND_LABEL, newState, uid, today, nextNo,
    shopById, saveShop, deleteShop,
    buildLine, lineToEntry, totals, checkLines, saveInvoice, deleteInvoice,
    voucherRows, saveVoucher, deleteVoucher,
    effects, docsOf, statement, balance, balanceAround, allBalances,
    woHistory, woLast, daysBetween, toBackup, fromBackup, BACKUP_FORMAT,
  };
  root.Domain = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
