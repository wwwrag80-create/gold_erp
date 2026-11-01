/* منطق حسابات المندوب — بلا واجهة، فيُختبر وحده (`mobile/tests`).
 *
 * المندوب يأخذ البضاعة من **المصانع** ويبيعها **للمحلات**، يحصّل من المحلات
 * ذهباً ونقداً، ثم يدفع للمصانع ما عليه. الطرفان في قائمةٍ واحدة (`shops`)
 * ويميّزهما `type`: «shop» (الافتراضي) أو «factory».
 *
 * الأثر على حساب الطرف، والموجب «عليه» (للمحل: عليه لي · للمصنع: الموجب له
 * عندي نادر، والسالب ما عليّ له):
 *   فاتورة بيع (محل)        : ذهب + الوزن المقيد (مكافئ 18) · نقد + (الأجور + الضريبة)
 *   مرتجع (محل)             : ذهب − الوزن · نقد − الأجور
 *   تحصيل (سند قبض، محل)    : ذهب − مكافئ كل سطر − الخصم الوزني · نقد − النقد − الخصم
 *   بضاعة من مصنع           : ذهب − الوزن · نقد − الأجور   (صار عليّ للمصنع)
 *   إرجاع لمصنع             : ذهب + الوزن · نقد + الأجور
 *   دفع (سند صرف، لمصنع)    : ذهب + مكافئ كل سطر · نقد + النقد   (نقص ما عليّ)
 * والفاتورة والسند كما يرحّلهما البرنامج على الكمبيوتر
 * (`models/invoices.py` و`models/vouchers.py`)، والرصيد يُقرَّب عند كل حركة:
 * الذهب ثلاث منازل والنقد منزلتان.
 *
 * **الممتلكات** (`holdings`): ما مع المندوب الآن — صندوقٌ لكل عيار من ذهب
 * التحصيل ناقصاً ما دُفع للمصانع، وصندوق النقد، والأطقم التي في يده (من مصنعٍ
 * أو مرتجعةً من محل) ما لم تُبَع أو تُرجَع.
 *
 * اسم الطقم اختياري: يُكتب الوزن ويُرحَّل. وإن كُتب اسمٌ سبق له حركة
 * عُبّئت أوزانه منها (`woLast`).
 */
(function (root) {
  "use strict";
  const Num = root.Num || require("./num.js");
  const Gold = root.Gold || require("./gold.js");
  const R = Num.pyRound;

  const KIND_LABEL = {
    sale: "فاتورة بيع", sale_return: "مرتجع",
    purchase: "بضاعة من مصنع", purchase_return: "إرجاع للمصنع",
    receipt: "تحصيل", payment: "سداد", opening: "رصيد افتتاحي",
  };
  const PREFIX = { sale: "S", sale_return: "R", purchase: "P", purchase_return: "PR", receipt: "RV", payment: "PV" };
  // ما يدخل يد المندوب من أطقم وما يخرج منها
  const IN_KINDS = ["sale_return", "purchase"];
  const OUT_KINDS = ["sale", "purchase_return"];
  const SHOP_KINDS = ["sale", "sale_return"];
  const FACTORY_KINDS = ["purchase", "purchase_return"];

  function newState() {
    return {
      settings: {
        name: "", vatNo: "", phone: "", address: "",
        viewKarat: 18, stoneRate: Gold.STONE_DISCOUNT_RATE,
        showBalanceOnInvoice: true, theme: "auto", lastBackup: "",
      },
      seq: { S: 0, R: 0, P: 0, PR: 0, RV: 0, PV: 0 },
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

  // ══ الأطراف: المحلات والمصانع ══
  function shopById(st, id) { return st.shops.find((s) => s.id === id) || null; }
  function isFactory(p) { return !!p && p.type === "factory"; }
  function shopsOnly(st) { return st.shops.filter((p) => !isFactory(p)); }
  function factoriesOnly(st) { return st.shops.filter(isFactory); }
  function saveShop(st, data) {
    const type = data.type === "factory" ? "factory" : "shop";
    const word = type === "factory" ? "المصنع" : "المحل";
    const name = String(data.name || "").trim();
    if (!name) throw new Error(`اكتب اسم ${word}`);
    const dup = st.shops.find((s) => s.name.trim() === name && s.id !== data.id);
    if (dup) throw new Error(`يوجد ${isFactory(dup) ? "مصنعٌ" : "محلٌّ"} بالاسم نفسه: ${name}`);
    const old = data.id ? shopById(st, data.id) : null;
    if (old && (old.type || "shop") !== type) throw new Error("لا يتحوّل المحل مصنعاً ولا العكس");
    const rec = {
      id: data.id || uid(type === "factory" ? "fa_" : "sh_"), type,
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
    if (used) throw new Error("للحساب فواتير أو سندات — احذفها أولاً أو أبقِ الحساب");
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
        after18: 0, standing18: 0, diamond: 0, rate18: 0, lid: e.lid || uid("l"), src: "" };
    }
    // اسم الطقم اختياري. والسطر: ذهبٌ (وزن)، أو ماسٌ وحده، أو أجورٌ وحدها —
    // والأجور مبلغٌ مباشر (`wages`) أو بالجرام (`wage`/`rate18`) من حركةٍ قديمة
    const wo = String(e.wo || "").trim();
    const reg = Number(e.reg || 0);
    const dia0 = Math.max(0, Number(e.diamond || 0));
    const direct = e.wages !== undefined && e.wages !== null && e.wages !== "";
    const wagesAmt = direct ? R(Math.max(0, Number(e.wages)), 2) : null;
    if (!(reg > 0) && !(dia0 > 0)) {
      if (wagesAmt > 0) {
        return { wageOnly: true, amount: wagesAmt, wages: wagesAmt, note: String(e.note || wo).trim(),
          wo: "", model: "", karat: 0, reg18: 0, gold18: 0, small18: 0, big18: 0,
          after18: 0, standing18: 0, diamond: 0, rate18: 0, lid: e.lid || uid("l"), src: "" };
      }
      throw new Error(wo ? `أدخل وزن الطقم ${wo} أو أجوره أو ماسه` : "أدخل الوزن أو الأجور أو الماس");
    }
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
    let rate18 = e.rate18 !== undefined && e.rate18 !== null ? Number(e.rate18)
      : Gold.wageStore(Number(e.wage || 0), k);
    let wages = Gold.totalWages(rate18, reg18);
    if (direct) {
      wages = wagesAmt;
      rate18 = reg18 > 0 ? R(wagesAmt / reg18, 6) : 0;     // للعلم فقط — الأجور هي المكتوبة
    }
    return {
      wageOnly: false, wo, model: String(e.model || "").trim(), karat: k,
      gold18: st18("gold18", e.gold), small18: st18("small18", e.small),
      big18: st18("big18", e.big), after18: st18("after18", e.after),
      standing18: st18("standing18", e.standing),
      reg18, diamond: R(Math.max(0, Number(e.diamond || 0)), 3),
      stoneRate: e.stoneRate === undefined ? Gold.STONE_DISCOUNT_RATE : Number(e.stoneRate),
      rate18, wages,
      note: String(e.note || "").trim(),
      // رقم السطر الثابت، ومن أي طقمٍ في اليد جاء (للممتلكات)، وصورته
      lid: e.lid || uid("l"), src: String(e.src || ""), photo: String(e.photo || ""),
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
      wage: Gold.wageView(li.rate18, k), note: li.note, photo: li.photo || "",
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
    const srcs = new Set();
    for (const li of lines) {
      if (li.wageOnly) continue;
      if (li.src) {
        if (srcs.has(li.src)) throw new Error("الطقم نفسه مضافٌ مرتين في الفاتورة — احذف السطر المكرّر.");
        srcs.add(li.src);
      }
      const key = (li.wo || "").trim();
      if (!key) continue;
      if (seen.has(key)) {
        throw new Error(`الطقم ${key} مكرّر في الفاتورة — القطعة الواحدة لا تُباع ` +
          "مرتين في مستندٍ واحد. احذف السطر المكرّر.");
      }
      seen.add(key);
    }
  }

  function saveInvoice(st, draft) {
    const party = shopById(st, draft.shopId);
    const forFactory = FACTORY_KINDS.includes(draft.kind);
    if (!SHOP_KINDS.includes(draft.kind) && !forFactory) throw new Error("نوع الفاتورة غير صحيح");
    if (!party || isFactory(party) !== forFactory) throw new Error(forFactory ? "اختر المصنع" : "اختر المحل");
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
    const party = shopById(st, draft.shopId);
    if (!["receipt", "payment"].includes(draft.kind)) throw new Error("نوع سند غير صحيح");
    // التحصيل من المحلات، والدفع للمصانع (ودفعٌ قديم لمحلٍّ يبقى كما رُحّل)
    if (draft.kind === "receipt" && (!party || isFactory(party))) throw new Error("اختر المحل");
    if (draft.kind === "payment" && !party) throw new Error("اختر المصنع");
    const rows = voucherRows(draft.rows);
    const discCash = R(Number(draft.discCash || 0), 2);
    const discGold18 = R(Number(draft.discGold18 || 0), 3);
    const netDiff = R(Number(draft.netDiff || 0), 2);
    for (const v of [discCash, discGold18]) if (v < 0) throw new Error("الخصومات لا تقبل السالب");
    if (draft.kind === "payment" && (discCash || discGold18)) {
      throw new Error("الخصومات المسموحة تخص التحصيل فقط");
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
    if (doc.kind === "purchase") return { gd: 0, gc: doc.totalW18, cd: 0, cc: doc.grand };
    if (doc.kind === "purchase_return") return { gd: doc.totalW18, gc: 0, cd: doc.grand, cc: 0 };
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
        if (!li.wageOnly && (li.wo || "").trim() === key) {
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

  // ══ العملاء — المبيعات والسداد (كـmodels/customer_board.py) ══
  // لكل عميلٍ وجهين (ذهب · نقد): رصيدٌ سابق، مبيعات (ومعها سندات الصرف:
  // ما صُرف له فصار عليه)، مرتجع، صافي = سابق + مبيعات − مرتجع، سداد،
  // باقي = صافي − سداد، ونسبتا المرتجع والسداد، وتقديرٌ بكلمة.
  const GRADES = ["مسدَّد", "ممتاز", "جيد", "مقبول", "سيء"];
  function pct(part, whole) { return whole > 1e-9 ? R(part / whole * 100, 1) : null; }
  function grade(paidPct, remaining, hasSales, paid) {
    if (remaining <= 0.005) return hasSales || paid > 0.005 ? "مسدَّد" : "—";
    const p = paidPct === null || paidPct === undefined ? 0 : paidPct;
    if (p >= 80) return "ممتاز";
    if (p >= 60) return "جيد";
    if (p >= 40) return "مقبول";
    return "سيء";
  }
  function boardSide(d, dec) {
    const x = {};
    for (const k of ["open", "sales", "returns", "paid", "other"]) x[k] = R(d[k] || 0, dec);
    x.net = R(x.open + x.sales - x.returns, 3);
    x.remaining = R(x.net - x.paid + x.other, 3);
    x.retPct = pct(x.returns, x.open + x.sales);
    x.paidPct = pct(x.paid, x.net);
    x.grade = grade(x.paidPct, x.remaining, x.sales > 0.0005 || x.open > 0.0005, x.paid);
    return x;
  }
  function board(st, from, to) {
    const rows = [];
    for (const shop of shopsOnly(st)) {
      const g = { open: 0, sales: 0, returns: 0, paid: 0, other: 0 };
      const c = { open: 0, sales: 0, returns: 0, paid: 0, other: 0 };
      let nInv = 0, lastSale = "", lastPay = "";
      const op = openingRow(shop);
      if (op && (!to || op.date <= to)) { g.open += op.gd - op.gc; c.open += op.cd - op.cc; }
      for (const d of docsOf(st, shop.id)) {
        if (to && d.date > to) continue;
        const e = effects(d);
        if (from && d.date < from) { g.open += e.gd - e.gc; c.open += e.cd - e.cc; continue; }
        if (d.kind === "sale") { g.sales += e.gd; c.sales += e.cd; nInv++; if (d.date > lastSale) lastSale = d.date; }
        else if (d.kind === "sale_return") { g.returns += e.gc; c.returns += e.cc; }
        else if (d.kind === "receipt") {
          g.paid += e.gc - e.gd; c.paid += e.cc - e.cd;
          if (d.date > lastPay) lastPay = d.date;
        } else if (d.kind === "payment") { g.sales += e.gd - e.gc; c.sales += e.cd - e.cc; }
      }
      rows.push({ shop, id: shop.id, name: shop.name, gold: boardSide(g, 3), cash: boardSide(c, 2),
        nInv, lastSale, lastPay });
    }
    // الأعلى سداداً أولاً — بالمبلغ لا بالنسبة (`by_paid`)
    rows.sort((a, b) => (b.gold.paid - a.gold.paid) || (b.cash.paid - a.cash.paid) ||
      a.name.localeCompare(b.name, "ar"));
    const tot = (side) => {
      const t = { open: 0, sales: 0, returns: 0, paid: 0, other: 0 };
      for (const r of rows) for (const k of Object.keys(t)) t[k] += r[side][k];
      return boardSide(t, side === "gold" ? 3 : 2);
    };
    return { rows, gold: tot("gold"), cash: tot("cash") };
  }
  function hasMovement(r) {
    return [r.gold, r.cash].some((x) => Math.abs(x.open) > 0.0005 || x.sales > 0.0005 ||
      x.returns > 0.0005 || x.paid > 0.0005);
  }

  // ══ الممتلكات: ما مع المندوب الآن ══
  function lineId(doc, li, idx) { return li.lid || `${doc.id}#${idx}`; }
  function holdings(st) {
    // صناديق الذهب بعيارها، وصندوق النقد — من التحصيل ناقصاً الدفع
    const boxes = {};
    const cash = { amount: 0, inSum: 0, outSum: 0, moves: [] };
    for (const v of st.vouchers.slice().sort(docOrder)) {
      const sg = v.kind === "receipt" ? 1 : v.kind === "payment" ? -1 : 0;
      if (!sg) continue;
      const party = shopById(st, v.shopId);
      for (const r of v.rows) {
        if (r.kind === "gold") {
          const b = boxes[r.karat] = boxes[r.karat] || { karat: r.karat, weight: 0, inSum: 0, outSum: 0, moves: [] };
          b.weight = R(b.weight + sg * r.weight, 3);
          if (sg > 0) b.inSum = R(b.inSum + r.weight, 3); else b.outSum = R(b.outSum + r.weight, 3);
          b.moves.push({ sign: sg, weight: r.weight, date: v.date, party, doc: v, notes: r.notes || "" });
        } else {
          cash.amount = R(cash.amount + sg * r.amount, 2);
          if (sg > 0) cash.inSum = R(cash.inSum + r.amount, 2); else cash.outSum = R(cash.outSum + r.amount, 2);
          cash.moves.push({ sign: sg, amount: r.amount, date: v.date, party, doc: v, notes: r.notes || "" });
        }
      }
    }
    // الأطقم في اليد: ما دخل (مرتجعٌ من محل · بضاعةٌ من مصنع) ولم يخرج
    // (بيعٌ لمحل · إرجاعٌ لمصنع). الخارج يُطابق بطقمه المختار (`src`) أو باسمه
    const pieces = new Map();
    const byName = new Map();
    for (const d of st.invoices.slice().sort(docOrder)) {
      const isIn = IN_KINDS.includes(d.kind), isOut = OUT_KINDS.includes(d.kind);
      d.lines.forEach((li, idx) => {
        if (li.wageOnly) return;
        const name = (li.wo || "").trim();
        if (isIn) {
          const id = lineId(d, li, idx);
          if (name && byName.has(name)) pieces.delete(byName.get(name));
          pieces.set(id, { id, name, karat: li.karat || 18, w18: li.reg18, rate18: li.rate18,
            date: d.date, doc: d, line: li, party: shopById(st, d.shopId), fromKind: d.kind });
          if (name) byName.set(name, id);
        } else if (isOut) {
          let id = li.src && pieces.has(li.src) ? li.src : null;
          if (!id && name && byName.has(name)) id = byName.get(name);
          if (id) {
            const p = pieces.get(id);
            pieces.delete(id);
            if (p && p.name) byName.delete(p.name);
          }
        }
      });
    }
    const list = [...pieces.values()].sort((x, y) => docOrder(y.doc, x.doc));
    let setsW18 = 0;
    for (const p of list) setsW18 = R(setsW18 + p.w18, 3);
    const boxList = Object.values(boxes).filter((b) => b.moves.length)
      .sort((x, y) => y.karat - x.karat);
    for (const b of boxList) b.moves.reverse();
    cash.moves.reverse();
    let gold18 = 0;
    for (const b of boxList) gold18 = R(gold18 + Gold.store(b.weight, b.karat), 3);
    return { boxes: boxList, cash, pieces: list, setsW18, gold18 };
  }
  function pieceById(st, id) {
    return holdings(st).pieces.find((p) => p.id === id) || null;
  }

  // ══ كشف الماس ══
  // مجموع ماس كل فاتورة — للعرض والمعرفة كما في البرنامج: لا يدخل الوزن ولا
  // رصيد الذهب. البيع والإرجاع للمصنع «+» والمرتجع والبضاعة «−» كالذهب
  function diamondOf(doc) {
    let s = 0;
    for (const li of doc.lines || []) if (!li.wageOnly) s += Number(li.diamond || 0);
    return R(s, 3);
  }
  function diamondStatement(st, partyId, from, to) {
    const docs = st.invoices.filter((d) => d.shopId === partyId).sort(docOrder);
    const rows = [];
    let bal = 0, prev = 0, hasPrev = false, plusSum = 0, minusSum = 0;
    const prevRow = () => ({ kind: "prev", label: "رصيد سابق", date: from, no: "", dd: 0, dc: 0, bal: prev, doc: null, sets: [] });
    for (const d of docs) {
      const dia = diamondOf(d);
      if (!(dia > 0)) continue;
      const plus = d.kind === "sale" || d.kind === "purchase_return";
      if (from && d.date < from) { prev = R(prev + (plus ? dia : -dia), 3); hasPrev = true; continue; }
      if (to && d.date > to) continue;
      if (!rows.length && hasPrev) { bal = prev; rows.push(prevRow()); }
      bal = R(bal + (plus ? dia : -dia), 3);
      if (plus) plusSum = R(plusSum + dia, 3); else minusSum = R(minusSum + dia, 3);
      rows.push({ kind: d.kind, label: KIND_LABEL[d.kind], date: d.date, no: d.no, doc: d,
        dd: plus ? dia : 0, dc: plus ? 0 : dia, bal,
        sets: d.lines.filter((l) => !l.wageOnly && Number(l.diamond || 0) > 0)
          .map((l) => ({ name: (l.wo || "").trim(), diamond: l.diamond })) });
    }
    if (!rows.length && hasPrev) rows.push(prevRow());
    return { rows, diamond: rows.length ? rows[rows.length - 1].bal : 0, plus: plusSum, minus: minusSum };
  }

  // ══ نسخة احتياطية ══
  // الصور خارج الحالة (مخزنٌ وحده) — وتدخل ملفَّ النسخة إن مُرِّرت
  const BACKUP_FORMAT = "jadeite-mobile-backup";
  function toBackup(st, photos) {
    const out = { format: BACKUP_FORMAT, version: 1, savedAt: nowStamp(),
      settings: st.settings, seq: st.seq, shops: st.shops,
      invoices: st.invoices, vouchers: st.vouchers, held: st.held };
    if (photos) out.photos = photos;
    return out;
  }
  function backupPhotos(obj) {
    const p = obj && obj.photos;
    if (!p || typeof p !== "object") return {};
    const out = {};
    for (const [id, data] of Object.entries(p)) {
      if (/^[\w-]{1,64}$/.test(id) && typeof data === "string" && data.startsWith("data:image/")) out[id] = data;
    }
    return out;
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
    KIND_LABEL, IN_KINDS, OUT_KINDS, SHOP_KINDS, FACTORY_KINDS, newState, uid, today, nextNo,
    shopById, isFactory, shopsOnly, factoriesOnly, saveShop, deleteShop,
    buildLine, lineToEntry, totals, checkLines, saveInvoice, deleteInvoice,
    voucherRows, saveVoucher, deleteVoucher,
    effects, docsOf, statement, balance, balanceAround, allBalances,
    woHistory, woLast, daysBetween, toBackup, fromBackup, BACKUP_FORMAT,
    GRADES, grade, boardSide, board, hasMovement, holdings, pieceById, docOrder,
    diamondOf, diamondStatement, backupPhotos,
  };
  root.Domain = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
