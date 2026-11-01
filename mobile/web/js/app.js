/* جاديت للجوال — الشاشات والتنقّل.
 * المنطق كلّه في domain.js والمعادلات في gold.js؛ هنا الواجهة وحدها.
 */
(function (root) {
  "use strict";
  const { h, toast, err, sheet, confirmSheet, pickSheet, numInput, field, enterChain } = root.UI;
  const { f2 } = root.Num;
  const G = root.Gold, D = root.Domain, P = root.PrintDoc, B = root.Bridge, S = root.Store;

  const App = { state: null };
  root.App = App;

  // ══ أدوات عامة ══
  const st = () => App.state;
  const vk = () => parseInt(st().settings.viewKarat || 18, 10);
  const gw = (w18, k) => f2(G.g(w18, k || vk()));
  const dmy = P.dmy;
  const view = () => document.getElementById("view");

  function balSpan(v, unit) {
    if (Math.abs(v) < 0.005) return h("span", { class: "muted" }, "0.00");
    return h("span", { class: v > 0 ? "bal-on" : "bal-for" },
      `${f2(Math.abs(v))} ${unit} ${v > 0 ? "عليه" : "له"}`);
  }
  function goldBal(w18) { return balSpan(G.g(w18, vk()), "جم"); }
  function cashBal(c) { return balSpan(c, "ريال"); }

  function go(path) { location.hash = "#/" + path; }
  function replace(path) { location.replace("#/" + path); }

  async function persist(ops) {
    try { await S.write(ops); return true; }
    catch (e) { err(new Error("تعذّر الحفظ في الجوال: " + ((e && e.message) || e))); return false; }
  }

  function setBar(title, sub, opts) {
    const o = opts || {};
    const bar = document.getElementById("bar");
    bar.innerHTML = "";
    if (o.back !== false) {
      bar.appendChild(h("button", { class: "icon-btn", "aria-label": "رجوع",
        onclick: () => (history.length > 1 ? history.back() : go("home")) }, "→"));
    }
    bar.appendChild(h("h1", null, title, sub ? h("span", { class: "sub", text: sub }) : null));
    for (const a of o.actions || []) bar.appendChild(a);
    document.body.classList.toggle("no-tabs", !!o.noTabs);
    document.title = title;
  }

  function setTab(name) {
    for (const b of document.querySelectorAll("#tabs button")) {
      b.classList.toggle("on", b.dataset.tab === name);
    }
  }

  function shopTitle(id) {
    const s = D.shopById(st(), id);
    return s ? s.name : "—";
  }

  function kindBadge(kind) {
    const ret = kind === "sale_return" || kind === "payment";
    return h("span", { class: "badge" + (ret ? " ret" : ""), text: D.KIND_LABEL[kind] });
  }

  function docSummary(d) {
    if (d.kind === "sale" || d.kind === "sale_return") {
      return `${gw(d.totalW18)} جم · أجور ${f2(d.grand)}`;
    }
    const parts = [];
    if (d.gold18) parts.push(`${gw(d.gold18)} جم`);
    if (d.cash) parts.push(`${f2(d.cash)} ريال`);
    return parts.join(" · ") || "—";
  }

  function docItem(d) {
    const type = d.kind === "sale" || d.kind === "sale_return" ? "inv" : "vo";
    return h("div", { class: "list-item", onclick: () => go(`doc/${type}/${d.id}`) },
      h("div", { class: "grow" },
        h("div", { class: "spread" }, h("span", { class: "t", text: shopTitle(d.shopId) }), kindBadge(d.kind)),
        h("div", { class: "spread muted small" },
          h("span", null, h("span", { dir: "ltr", text: d.no }), " · ", h("span", { dir: "ltr", text: dmy(d.date) })),
          h("span", { class: "num", text: docSummary(d) }))));
  }

  // ══ الرئيسية ══
  function home() {
    const s = st();
    setBar(s.settings.name || "جاديت", "حساباتي مع المحلات", { back: false });
    setTab("home");
    const v = view();
    const bals = D.allBalances(s);
    let gOn = 0, gFor = 0, cOn = 0, cFor = 0;
    for (const b of Object.values(bals)) {
      if (b.gold18 > 0) gOn += b.gold18; else gFor -= b.gold18;
      if (b.cash > 0) cOn += b.cash; else cFor -= b.cash;
    }
    const t = D.today();
    const todays = s.invoices.filter((d) => d.date === t);
    let tw = 0, tg = 0;
    for (const d of todays) {
      const sgn = d.kind === "sale" ? 1 : -1;
      tw += sgn * d.totalW18; tg += sgn * d.grand;
    }
    v.append(
      h("div", { class: "kpis" },
        h("div", { class: "kpi" }, h("b", null, "ذهب على المحلات"), h("span", { class: "v num" }, gw(gOn)), h("span", { class: "u" }, ` جم عيار ${vk()}`)),
        h("div", { class: "kpi" }, h("b", null, "ذهب للمحلات"), h("span", { class: "v num" }, gw(gFor)), h("span", { class: "u" }, ` جم عيار ${vk()}`)),
        h("div", { class: "kpi" }, h("b", null, "أجور ونقد على المحلات"), h("span", { class: "v num" }, f2(cOn)), h("span", { class: "u" }, " ريال")),
        h("div", { class: "kpi" }, h("b", null, "نقد للمحلات"), h("span", { class: "v num" }, f2(cFor)), h("span", { class: "u" }, " ريال"))),
      h("div", { class: "quick" },
        quickBtn("🧾", "فاتورة بيع", () => go("invoice/new?kind=sale")),
        quickBtn("↩️", "مرتجع بيع", () => go("invoice/new?kind=sale_return")),
        quickBtn("📥", "سند قبض", () => go("voucher/new?kind=receipt")),
        quickBtn("📤", "سند صرف", () => go("voucher/new?kind=payment")),
        quickBtn("📒", "كشف حساب", pickShopThen((id) => go(`statement/${id}`))),
        quickBtn("🔎", "حركة الطقم", () => go("wo"))),
    );
    v.append(h("div", { class: "card" }, h("h2", null, "اليوم ", h("span", { class: "muted small", dir: "ltr", text: dmy(t) })),
      h("div", { class: "grid3 small" },
        h("div", null, h("div", { class: "muted" }, "فواتير"), h("b", { class: "num" }, String(todays.length))),
        h("div", null, h("div", { class: "muted" }, `الوزن (عيار ${vk()})`), h("b", { class: "num" }, gw(tw))),
        h("div", null, h("div", { class: "muted" }, "الأجور"), h("b", { class: "num" }, f2(tg))))));
    const hasData = s.invoices.length + s.vouchers.length > 0;
    const last = s.settings.lastBackup;
    if (hasData && (!last || D.daysBetween(last.slice(0, 10), t) >= 7)) {
      v.append(h("div", { class: "note-bar warn", style: { marginBottom: "12px" }, onclick: () => go("settings") },
        last ? `آخر نسخة احتياطية قبل ${D.daysBetween(last.slice(0, 10), t)} يوماً — احفظ نسخةً جديدة (البيانات في هذا الجوال وحده).`
          : "لم تُحفظ نسخة احتياطية بعد — البيانات في هذا الجوال وحده. اضغط هنا لحفظ نسخة."));
    }
    const recent = [...s.invoices, ...s.vouchers]
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0)).slice(0, 8);
    v.append(h("div", { class: "sec-title" }, "آخر العمليات"));
    if (!recent.length) {
      v.append(h("div", { class: "empty" }, "لا عمليات بعد — أضف محلاً ثم أصدر أول فاتورة."));
    } else recent.forEach((d) => v.append(docItem(d)));
  }

  function quickBtn(icon, label, fn) {
    return h("button", { onclick: fn }, h("span", { class: "i" }, icon), label);
  }

  function shopItems() {
    const s = st();
    const bals = D.allBalances(s);
    return s.shops.slice().sort((a, b) => a.name.localeCompare(b.name, "ar")).map((x) => ({
      id: x.id, title: x.name,
      sub: `ذهب ${P.balTxt(G.g(bals[x.id].gold18, vk()), "جم")} · نقد ${P.balTxt(bals[x.id].cash, "ريال")}`,
    }));
  }

  function pickShopThen(fn) {
    return async () => {
      const it = await pickSheet("اختر المحل", shopItems(), { addLabel: "+ محل جديد", empty: "لا محلات بعد" });
      if (!it) return;
      if (it.add) { go("shop-form"); return; }
      fn(it.id);
    };
  }

  // ══ المحلات ══
  function shops() {
    setBar("المحلات", `${st().shops.length} محل`, { back: false,
      actions: [h("button", { class: "icon-btn", onclick: () => go("shop-form") }, "+ محل")] });
    setTab("shops");
    const v = view();
    const q = h("input", { class: "in", type: "search", placeholder: "ابحث باسم المحل أو الجوال…" });
    const sortSeg = h("div", { class: "chips", style: { margin: "8px 0" } });
    let sort = "name";
    const list = h("div");
    const render = () => {
      const s = st();
      const bals = D.allBalances(s);
      const t = q.value.trim();
      let arr = s.shops.filter((x) => !t || x.name.includes(t) || (x.phone || "").includes(t));
      if (sort === "name") arr.sort((a, b) => a.name.localeCompare(b.name, "ar"));
      if (sort === "gold") arr.sort((a, b) => bals[b.id].gold18 - bals[a.id].gold18);
      if (sort === "cash") arr.sort((a, b) => bals[b.id].cash - bals[a.id].cash);
      list.innerHTML = "";
      if (!arr.length) {
        list.append(h("div", { class: "empty" }, s.shops.length ? "لا نتائج" : "لا محلات بعد — اضغط «+ محل» لإضافة أول محل."));
      }
      for (const x of arr) {
        list.append(h("div", { class: "list-item", onclick: () => go(`shop/${x.id}`) },
          h("div", { class: "grow" }, h("div", { class: "t", text: x.name }),
            x.phone ? h("div", { class: "muted small", dir: "ltr", style: { textAlign: "right" }, text: x.phone }) : null),
          h("div", { style: { textAlign: "left" }, class: "small num" },
            h("div", null, goldBal(bals[x.id].gold18)), h("div", null, cashBal(bals[x.id].cash)))));
      }
    };
    const chips = [["name", "بالاسم"], ["gold", "الأكثر ذهباً عليه"], ["cash", "الأكثر نقداً عليه"]];
    for (const [k, label] of chips) {
      sortSeg.append(h("button", { class: "chip" + (k === sort ? " on" : ""), onclick: (e) => {
        sort = k;
        for (const c of sortSeg.children) c.classList.remove("on");
        e.target.classList.add("on");
        render();
      } }, label));
    }
    q.addEventListener("input", render);
    v.append(q, sortSeg, list);
    render();
  }

  function shopPage(id) {
    const s = st();
    const shop = D.shopById(s, id);
    if (!shop) { replace("shops"); return; }
    setBar(shop.name, shop.phone || "", {
      actions: [h("button", { class: "icon-btn", onclick: () => go(`shop-form/${id}`) }, "✎")] });
    setTab("shops");
    const b = D.balance(s, id);
    const v = view();
    v.append(h("div", { class: "kpis" },
      h("div", { class: "kpi" }, h("b", null, `رصيد الذهب (عيار ${vk()})`), h("div", { class: "v num" }, goldBal(b.gold18))),
      h("div", { class: "kpi" }, h("b", null, "رصيد الأجور والنقد"), h("div", { class: "v num" }, cashBal(b.cash)))));
    if (shop.agreedWage18) {
      v.append(h("div", { class: "note-bar info", style: { marginBottom: "12px" } },
        `💠 الأجرة المتفق عليها: ${f2(G.rate(shop.agreedWage18, vk()))} ريال لكل جرام عيار ${vk()}`));
    }
    v.append(h("div", { class: "quick" },
      quickBtn("🧾", "فاتورة بيع", () => go(`invoice/new?kind=sale&shop=${id}`)),
      quickBtn("↩️", "مرتجع بيع", () => go(`invoice/new?kind=sale_return&shop=${id}`)),
      quickBtn("📒", "كشف الحساب", () => go(`statement/${id}`)),
      quickBtn("📥", "سند قبض", () => go(`voucher/new?kind=receipt&shop=${id}`)),
      quickBtn("📤", "سند صرف", () => go(`voucher/new?kind=payment&shop=${id}`)),
      shop.phone ? quickBtn("📞", "اتصال", () => B.dial(shop.phone)) : quickBtn("✎", "تعديل المحل", () => go(`shop-form/${id}`))));
    if (shop.notes) v.append(h("div", { class: "card small" }, shop.notes));
    const docs = D.docsOf(s, id).reverse();
    v.append(h("div", { class: "sec-title" }, `العمليات (${docs.length})`));
    if (!docs.length) v.append(h("div", { class: "empty" }, "لا عمليات لهذا المحل بعد"));
    docs.slice(0, 60).forEach((d) => v.append(docItem(d)));
  }

  function shopForm(id) {
    const s = st();
    const shop = id ? D.shopById(s, id) : null;
    setBar(shop ? "تعديل المحل" : "محل جديد", "", { noTabs: true });
    const k = vk();
    const name = h("input", { class: "in", value: shop ? shop.name : "", placeholder: "اسم المحل", enterkeyhint: "next" });
    const phone = h("input", { class: "in", value: shop ? shop.phone : "", inputmode: "tel", dir: "ltr", placeholder: "05xxxxxxxx" });
    const notes = h("textarea", { class: "in", rows: 2, placeholder: "ملاحظات (اختياري)" });
    notes.value = shop ? shop.notes : "";
    const wage = numInput({ value: shop && shop.agreedWage18 ? G.rate(shop.agreedWage18, k) : 0 });
    const og = shop ? shop.openGold18 : 0, oc = shop ? shop.openCash : 0;
    const goldIn = numInput({ value: Math.abs(G.g(og, k)) });
    const cashIn = numInput({ value: Math.abs(oc) });
    const segOf = (neg) => {
      let on = neg ? "for" : "on";
      const seg = h("div", { class: "seg" });
      const mk = (key, label) => h("button", { type: "button", class: key === on ? "on" : "", onclick: (e) => {
        on = key;
        for (const c of seg.children) c.classList.remove("on");
        e.target.classList.add("on");
      } }, label);
      seg.append(mk("on", "عليه"), mk("for", "له"));
      seg.get = () => on;
      return seg;
    };
    const gSeg = segOf(og < 0), cSeg = segOf(oc < 0);
    const date = h("input", { class: "in", type: "date", value: shop ? shop.openDate : D.today() });
    const v = view();
    v.append(
      h("div", { class: "card" }, h("h2", null, "بيانات المحل"),
        field("اسم المحل", name), h("div", { style: { height: "8px" } }),
        field("الجوال", phone), h("div", { style: { height: "8px" } }),
        field(`الأجرة المتفق عليها (ريال لكل جرام عيار ${k}) — تُملأ تلقائياً في الفواتير`, wage),
        h("div", { style: { height: "8px" } }), field("ملاحظات", notes)),
      h("div", { class: "card" }, h("h2", null, "رصيد افتتاحي (اختياري)"),
        h("div", { class: "muted small", style: { marginBottom: "8px" } },
          "ما كان بينك وبين المحل قبل أول فاتورة في التطبيق."),
        h("div", { class: "grid2" }, field(`ذهب (جم عيار ${k})`, goldIn), field("الاتجاه", gSeg),
          field("نقد (ريال)", cashIn), field("الاتجاه", cSeg), field("بتاريخ", date, "span2"))));
    const save = async () => {
      try {
        const gv = goldIn.getVal(), cv = cashIn.getVal(), wv = wage.getVal();
        if ([gv, cv, wv].some((x) => !isFinite(x))) throw new Error("رقمٌ غير صحيح في أحد الحقول");
        const rec = D.saveShop(s, {
          id: shop ? shop.id : null, createdAt: shop ? shop.createdAt : null,
          name: name.value, phone: phone.value, notes: notes.value,
          agreedWage18: wv ? G.rateStore(wv, k) : 0,
          openGold18: (gSeg.get() === "for" ? -1 : 1) * G.store(gv, k),
          openCash: (cSeg.get() === "for" ? -1 : 1) * cv, openDate: date.value || D.today(),
        });
        if (await persist([["shops", "put", rec]])) {
          toast("حُفظ المحل");
          if (shop) history.back(); else replace(`shop/${rec.id}`);
        }
      } catch (e) { err(e); }
    };
    const del = async () => {
      try {
        if (!(await confirmSheet(`حذف المحل «${shop.name}»؟`, "حذف", true))) return;
        D.deleteShop(s, shop.id);
        if (await persist([["shops", "del", shop.id]])) { toast("حُذف المحل"); replace("shops"); }
      } catch (e) { err(e); }
    };
    v.append(h("div", { class: "footer-bar" },
      h("button", { class: "btn", onclick: save }, "حفظ"),
      shop ? h("button", { class: "btn ghost", onclick: del }, "حذف") : null));
  }

  // ══ الفاتورة (بيع · مرتجع) ══
  function invoiceEditor(q, mode, docId) {
    const s = st();
    let inv;
    const draftKey = (k) => "draft_inv_" + k;
    if (mode === "edit") {
      const d = s.invoices.find((x) => x.id === docId);
      if (!d) { replace("log"); return; }
      inv = JSON.parse(JSON.stringify(d));
    } else if (mode === "held") {
      const hd = s.held.find((x) => x.id === docId);
      if (!hd) { replace("held"); return; }
      inv = JSON.parse(JSON.stringify(hd));
      inv.heldId = hd.id; inv.id = null;
    } else {
      inv = { id: null, kind: q.kind === "sale_return" ? "sale_return" : "sale", shopId: q.shop || "",
        date: D.today(), vat: false, desc: "", lines: [] };
      try {
        const dr = JSON.parse(localStorage.getItem(draftKey(inv.kind)) || "null");
        if (dr && dr.lines && dr.lines.length && (!q.shop || dr.shopId === q.shop)) {
          Object.assign(inv, dr, { id: null });
          setTimeout(() => toast("استُعيدت فاتورةٌ لم تُرحَّل — أكملها أو احذف أسطرها"), 300);
        }
      } catch (e) { /* لا مسودة */ }
    }
    const editing = mode === "edit";
    const k0 = vk();
    const ent = { karat: k0, stoneRate: s.settings.stoneRate, regManual: false, wageManual: false,
      fromCard: false, shadow: null, wage18: 0, editIdx: null, lastWo: "" };

    const title = () => (inv.kind === "sale" ? "فاتورة بيع" : "مرتجع بيع") + (editing ? ` — تعديل ${inv.no}` : "");
    setBar(title(), editing ? "" : "تُرحَّل على حساب المحل", { noTabs: true });
    const v = view();

    // ── ① العملية والطرف ──
    const kindSeg = h("div", { class: "seg" });
    const setKind = (kind) => {
      inv.kind = kind;
      for (const b of kindSeg.children) b.classList.toggle("on", b.dataset.k === kind);
      setBar(title(), "", { noTabs: true });
      ent.lastWo = "";
      woIn.dispatchEvent(new Event("change"));
      refresh();
    };
    for (const [kk, label] of [["sale", "فاتورة بيع"], ["sale_return", "مرتجع بيع"]]) {
      kindSeg.append(h("button", { type: "button", "data-k": kk, class: kk === inv.kind ? "on" : "",
        disabled: editing, onclick: () => setKind(kk) }, label));
    }
    const shopBtn = h("button", { type: "button", class: "pick" });
    const shopNote = h("div");
    const renderShop = () => {
      shopBtn.innerHTML = "";
      const sh = D.shopById(s, inv.shopId);
      shopBtn.append(sh ? h("span", { class: "t" }, sh.name) : h("span", { class: "ph" }, "اختر المحل…"), h("span", null, "▾"));
      shopNote.innerHTML = "";
      if (sh && sh.agreedWage18) {
        shopNote.append(h("div", { class: "note-bar info" },
          `💠 الأجرة المتفق عليها: ${f2(G.rate(sh.agreedWage18, ent.karat))} ريال/جم عيار ${ent.karat}`));
      }
    };
    shopBtn.addEventListener("click", async () => {
      const it = await pickSheet("اختر المحل", shopItems(), { addLabel: "+ محل جديد", empty: "لا محلات بعد" });
      if (!it) return;
      if (it.add) { saveDraft(); go("shop-form"); return; }
      inv.shopId = it.id;
      renderShop();
      ent.lastWo = "";
      woIn.dispatchEvent(new Event("change"));
      refresh();
    });
    const dateIn = h("input", { class: "in", type: "date", value: inv.date,
      onchange: (e) => { inv.date = e.target.value || D.today(); refresh(); } });
    const vatIn = h("input", { type: "checkbox", checked: inv.vat, onchange: (e) => { inv.vat = e.target.checked; refresh(); } });
    const descIn = h("input", { class: "in", value: inv.desc, placeholder: "البيان (اختياري) — يظهر في كشف الحساب",
      oninput: (e) => { inv.desc = e.target.value; saveDraft(); } });

    // ── ② إدخال الطقم ──
    const woIn = h("input", { class: "in n hl", placeholder: "رقم التشغيل", autocomplete: "off",
      enterkeyhint: "next", inputmode: "text" });
    const modelIn = h("input", { class: "in", placeholder: "رقم الموديل", enterkeyhint: "next" });
    const gold = numInput(), small = numInput(), big = numInput(), after = numInput();
    const dia = numInput(), reg = numInput({ hl: true }), stand = numInput();
    const wage = numInput({ enter: "done" });
    const karatSel = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: `عيار ${x}` })));
    karatSel.value = String(ent.karat);
    const wagesOut = h("div", { class: "num", style: { fontWeight: "700" } }, "0.00");
    const notice = h("div");
    const addBtn = h("button", { type: "button", class: "btn grow" }, "+ إضافة سطر");
    const cancelEdit = h("button", { type: "button", class: "btn ghost", style: { display: "none" } }, "إلغاء التعديل");

    const W = { gold, small, big, after, standing: stand, reg };
    const snap = () => {
      ent.shadow = {};
      for (const [key, el] of Object.entries(W)) ent.shadow[key] = G.store(el.getVal() || 0, ent.karat);
    };
    const showWages = () => {
      const r = reg.getVal() || 0, w = wage.getVal() || 0;
      wagesOut.textContent = f2(G.totalWages(w, r));
    };
    const derive = () => {
      const gv = gold.getVal() || 0, sv = small.getVal() || 0, bv = big.getVal() || 0;
      const d = G.entryDerive(gv, sv, bv, ent.stoneRate, ent.regManual, reg.getVal() || 0);
      after.setVal(d.after); stand.setVal(d.standing);
      if (!ent.regManual) reg.setVal(d.reg);
      showWages(); snap();
    };
    for (const el of [gold, small, big]) el.addEventListener("input", derive);
    after.addEventListener("input", () => {
      ent.stoneRate = G.rateFromAfter(big.getVal() || 0, after.getVal() || 0, ent.stoneRate);
      if (!ent.regManual) {
        reg.setVal(Num_round3((gold.getVal() || 0) + (small.getVal() || 0) + (after.getVal() || 0)));
      }
      showWages(); snap();
    });
    reg.addEventListener("input", () => { ent.regManual = true; showWages(); snap(); });
    stand.addEventListener("input", snap);
    wage.addEventListener("input", () => {
      ent.wageManual = true;
      ent.wage18 = G.rateStore(wage.getVal() || 0, ent.karat);
      ent.wageExact18 = null;
      showWages();
    });
    karatSel.addEventListener("change", () => {
      const nk = parseInt(karatSel.value, 10);
      if (ent.fromCard && ent.shadow) {
        for (const [key, el] of Object.entries(W)) el.setVal(G.g(ent.shadow[key], nk));
        if (ent.wage18) wage.setVal(G.rate(ent.wage18, nk));
        ent.karat = nk;
      } else {
        ent.karat = nk;
        snap();
        ent.wage18 = G.rateStore(wage.getVal() || 0, nk);
      }
      showWages();
      renderShop();
    });

    function setNotice(kind, text) {
      notice.innerHTML = "";
      if (text) notice.append(h("div", { class: "note-bar " + kind }, text));
    }

    function fillFrom(li) {
      const e = D.lineToEntry(li, ent.karat);
      gold.setVal(e.gold); small.setVal(e.small); big.setVal(e.big); after.setVal(e.after);
      stand.setVal(e.standing); reg.setVal(e.reg); dia.setVal(e.diamond);
      if (e.model && !modelIn.value.trim()) modelIn.value = e.model;
      ent.stoneRate = e.stoneRate === undefined ? s.settings.stoneRate : e.stoneRate;
      ent.regManual = false; ent.fromCard = true; ent.exact18 = e.exact18;
      snap();
    }

    // رقم التشغيل: آخر حركةٍ له تقول من أين تُعبَّأ أوزانه
    woIn.addEventListener("change", () => {
      const no = woIn.value.trim();
      if (!no) { setNotice(); ent.lastWo = ""; return; }
      if (no === ent.lastWo) return;
      ent.lastWo = no;
      const last = D.woLast(s, no, inv.id);
      const sh = D.shopById(s, inv.shopId);
      if (!last) {
        setNotice("info", inv.kind === "sale"
          ? `رقم ${no} جديد — اكتب أوزانه.`
          : `رقم ${no} غير مسجّل في التطبيق — اكتب أوزانه كما رجعت.`);
        ent.fromCard = false;
        return;
      }
      fillFrom(last.line);
      if (!ent.wageManual) {
        const r18 = last.line.rate18;
        ent.wage18 = r18;
        ent.wageExact18 = r18;
        // الصفر المسجّل صفرٌ مكتوب (4.95) — لا فراغٌ يُستبدل بالمتفق عليه
        wage.value = f2(G.wageView(r18, ent.karat), { sep: false });
      }
      const who = last.shop ? last.shop.name : "—";
      const at = `بتاريخ ${dmy(last.date)}`;
      if (inv.kind === "sale") {
        if (last.kind === "sale_return") {
          setNotice("info", `↩ الطقم ${no} رجع بالمرتجع ${last.inv.no} من «${who}» ${at} — عُبّئت أوزانه من المرتجع.`);
        } else {
          setNotice("warn", `⚠ الطقم ${no} مباعٌ بالفاتورة ${last.inv.no} لـ«${who}» ${at} ولم يُرتجع بعد.`);
        }
      } else {
        if (last.kind === "sale") {
          const days = D.daysBetween(last.date, inv.date || D.today());
          let txt = `الطقم ${no}: بِيع بالفاتورة ${last.inv.no} لـ«${who}» ${at}` +
            (days > 0 ? ` — عنده منذ ${days} يوماً.` : ".") + " عُبّئت أوزانه من الفاتورة.";
          const other = sh && last.shop && last.shop.id !== sh.id;
          if (other) txt += `\n⚠ بِيع لـ«${who}» لا للمحل المختار.`;
          setNotice(other ? "warn" : "info", txt);
        } else {
          setNotice("warn", `⚠ الطقم ${no} مرتجعٌ مسبقاً بالمرتجع ${last.inv.no} من «${who}» ${at}.`);
        }
      }
    });

    function clearEntry() {
      woIn.value = ""; modelIn.value = "";
      for (const el of [gold, small, big, after, dia, reg, stand, wage]) el.setVal(0);
      ent.regManual = false; ent.wageManual = false; ent.fromCard = false; ent.shadow = null;
      ent.wage18 = 0; ent.stoneRate = s.settings.stoneRate; ent.editIdx = null; ent.lastWo = "";
      ent.exact18 = null; ent.wageExact18 = null;
      addBtn.textContent = "+ إضافة سطر"; cancelEdit.style.display = "none";
      setNotice(); showWages();
    }

    async function addLine() {
      try {
        const no = woIn.value.trim();
        const vals = { gold: gold.getVal(), small: small.getVal(), big: big.getVal(), after: after.getVal(),
          diamond: dia.getVal(), reg: reg.getVal(), standing: stand.getVal(), wage: wage.getVal() };
        for (const [key, x] of Object.entries(vals)) {
          if (!isFinite(x)) throw new Error("رقمٌ غير صحيح في خانة " + ({ gold: "الذهب", small: "الفصوص", big: "الأحجار",
            after: "بعد الخصم", diamond: "الماس", reg: "الوزن المقيد", standing: "الوزن القائم", wage: "الأجر" })[key]);
        }
        if (!no) {
          if (vals.wage > 0) { pushLine(D.buildLine({ wageOnly: true, amount: vals.wage })); clearEntry(); return; }
          woIn.focus();
          throw new Error("اكتب رقم التشغيل");
        }
        const dupAt = inv.lines.findIndex((l, i) => !l.wageOnly && l.wo.trim() === no && i !== ent.editIdx);
        if (dupAt >= 0) throw new Error(`الطقم ${no} مضافٌ مسبقاً في هذه الفاتورة`);
        let w = vals.wage, r18x = null;
        if (wage.isBlank()) {
          const sh = D.shopById(s, inv.shopId);
          w = sh && sh.agreedWage18 ? G.rate(sh.agreedWage18, ent.karat) : 0;
          if (sh && sh.agreedWage18) r18x = sh.agreedWage18;
        } else if (ent.wageExact18 !== null && ent.wageExact18 !== undefined &&
          Math.abs(w - G.wageView(ent.wageExact18, ent.karat)) <= 0.005) {
          r18x = ent.wageExact18;
        }
        const regV = vals.reg > 0 ? vals.reg : 0;
        if (!(regV > 0)) throw new Error(`أدخل وزن الطقم ${no} — الذهب أو الوزن المقيد`);
        const last = D.woLast(s, no, inv.id);
        if (ent.editIdx === null && last) {
          if (inv.kind === "sale" && last.kind === "sale") {
            const ok = await confirmSheet(`الطقم ${no} مباعٌ بالفاتورة ${last.inv.no} لـ«${last.shop ? last.shop.name : "—"}»` +
              ` بتاريخ ${dmy(last.date)} ولم يُرتجع.\n\nبيعه مرةً أخرى؟`, "نعم، أضفه");
            if (!ok) return;
          }
          if (inv.kind === "sale_return" && last.kind === "sale_return") {
            const ok = await confirmSheet(`الطقم ${no} مرتجعٌ مسبقاً بالمرتجع ${last.inv.no}.\n\nإرجاعه مرةً أخرى؟`, "نعم، أضفه");
            if (!ok) return;
          }
        }
        const li = D.buildLine({ wo: no, model: modelIn.value, karat: ent.karat,
          gold: vals.gold, small: vals.small, big: vals.big, after: vals.after,
          standing: vals.standing || regV, reg: regV, diamond: vals.diamond,
          stoneRate: ent.stoneRate, wage: w, rate18: r18x, exact18: ent.fromCard ? ent.exact18 : null });
        pushLine(li);
        clearEntry();
        woIn.focus();
      } catch (e) { err(e); }
    }
    function pushLine(li) {
      if (ent.editIdx !== null) inv.lines[ent.editIdx] = li; else inv.lines.push(li);
      refresh();
    }
    addBtn.addEventListener("click", addLine);
    cancelEdit.addEventListener("click", clearEntry);
    enterChain([woIn, modelIn, gold, small, big, after, dia, reg, stand, wage], addLine);

    async function wageOnly() {
      const amt = numInput();
      const note = h("input", { class: "in", placeholder: "مثلاً: تلميع · تعديل مقاس · أجرة سابقة" });
      const r = await sheet((box, close) => {
        box.append(h("h3", null, "سطر أجر فقط"),
          h("div", { class: "muted small", style: { marginBottom: "8px" } },
            "يُضاف إلى أجور المحل وحدها — بلا ذهب. وفي المرتجع يُردّ من أجوره."),
          field("المبلغ (ريال)", amt), h("div", { style: { height: "8px" } }), field("البيان", note),
          h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => close(true) }, "إضافة"),
            h("button", { class: "btn ghost", onclick: () => close(false) }, "إلغاء")));
      });
      if (!r) return;
      try { pushLine(D.buildLine({ wageOnly: true, amount: amt.getVal(), note: note.value })); }
      catch (e) { err(e); }
    }

    function editLine(i) {
      const li = inv.lines[i];
      if (li.wageOnly) {
        inv.lines.splice(i, 1);
        refresh();
        wage.setVal(li.amount);
        woIn.value = "";
        toast("عدّل المبلغ ثم «+ إضافة سطر» (رقم التشغيل فارغ = أجر فقط)");
        return;
      }
      clearEntry();
      ent.editIdx = i;
      ent.karat = li.karat || ent.karat;
      karatSel.value = String(ent.karat);
      woIn.value = li.wo; ent.lastWo = li.wo;
      modelIn.value = li.model || "";
      fillFrom(li);
      ent.wageManual = true; ent.wage18 = li.rate18; ent.wageExact18 = li.rate18;
      wage.setVal(f2(G.wageView(li.rate18, ent.karat), { sep: false }), true);
      if (Math.abs(G.g(li.reg18, ent.karat) - G.registered(G.g(li.gold18, ent.karat), G.g(li.small18, ent.karat),
        G.g(li.big18, ent.karat), ent.stoneRate)) > 0.0051) ent.regManual = true;
      showWages();
      addBtn.textContent = "✔ حفظ تعديل السطر";
      cancelEdit.style.display = "";
      setNotice("info", `تعديل السطر ${i + 1} — الطقم ${li.wo}`);
      entryCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── ③ البنود والإجماليات ──
    const linesBox = h("div");
    const totalsBox = h("div", { class: "totals" });
    function refresh() {
      linesBox.innerHTML = "";
      if (!inv.lines.length) {
        linesBox.append(h("div", { class: "empty" }, "لا بنود بعد — أدخل الطقم ثم «+ إضافة سطر»"));
      }
      inv.lines.forEach((li, i) => {
        const lk = li.karat || 18;
        linesBox.append(h("div", { class: "line" + (ent.editIdx === i ? " editing" : "") },
          h("div", { class: "top" },
            h("div", null, li.wageOnly ? h("b", null, "أجر فقط") : h("span", { class: "wo", text: li.wo }),
              li.model ? h("span", { class: "muted small" }, "  · موديل " + li.model) : null,
              li.wageOnly && li.note ? h("span", { class: "muted small" }, "  · " + li.note) : null,
              li.wageOnly ? null : h("span", { class: "badge", style: { marginInlineStart: "6px" } }, `عيار ${lk}`)),
            h("div", { class: "act" },
              h("button", { onclick: () => editLine(i), "aria-label": "تعديل" }, "✎"),
              h("button", { class: "del", "aria-label": "حذف", onclick: async () => {
                if (await confirmSheet(`حذف السطر ${li.wageOnly ? "(أجر فقط)" : li.wo}؟`, "حذف", true)) {
                  inv.lines.splice(i, 1);
                  if (ent.editIdx === i) clearEntry();
                  refresh();
                }
              } }, "✕"))),
          li.wageOnly ? h("div", { class: "vals" }, h("div", null, "الأجرة", h("b", { class: "num" }, f2(li.amount))))
            : h("div", { class: "vals" },
              h("div", { class: "muted" }, "المقيد", h("b", { class: "num" }, gw(li.reg18, lk))),
              h("div", { class: "muted" }, "الأجر/جم", h("b", { class: "num" }, f2(G.wageView(li.rate18, lk)))),
              h("div", { class: "muted" }, "الأجرة", h("b", { class: "num" }, f2(li.wages))))));
      });
      const t = D.totals(inv.lines, inv.vat);
      const sets = inv.lines.filter((l) => !l.wageOnly).length;
      const k = vk();
      totalsBox.innerHTML = "";
      const row = (a, b, cls) => h("div", { class: "spread" + (cls ? " " + cls : "") }, h("span", null, a), h("span", { class: "num" }, b));
      totalsBox.append(row(`عدد الأطقم`, String(sets)),
        row(`إجمالي الوزن المقيد (عيار ${k})`, gw(t.totalW18)),
        row("إجمالي الأجور", f2(t.wages)));
      if (inv.vat) totalsBox.append(row("ضريبة 15% على الأجور", f2(t.vatAmt)));
      totalsBox.append(row("الإجمالي", f2(t.grand) + " ريال", "grand"));
      if (inv.shopId) {
        const before = D.balance(s, inv.shopId, inv.id);
        const sg = inv.kind === "sale" ? 1 : -1;
        const g18 = Num_round3(before.gold18 + sg * t.totalW18);
        const c = Num_round2(before.cash + sg * t.grand);
        totalsBox.append(h("hr", { class: "sep" }),
          h("div", { class: "spread small" }, h("span", null, "رصيد الذهب بعد الفاتورة"), goldBal(g18)),
          h("div", { class: "spread small" }, h("span", null, "رصيد الأجور بعد الفاتورة"), cashBal(c)));
      }
      saveDraft();
    }

    function saveDraft() {
      if (editing || mode === "held") return;
      try {
        if (inv.lines.length) {
          localStorage.setItem(draftKey(inv.kind), JSON.stringify({ kind: inv.kind, shopId: inv.shopId,
            date: inv.date, vat: inv.vat, desc: inv.desc, lines: inv.lines }));
        } else localStorage.removeItem(draftKey(inv.kind));
      } catch (e) { /* لا مساحة */ }
    }
    function clearDraft() { try { localStorage.removeItem(draftKey(inv.kind)); } catch (e) { /* */ } }

    async function save() {
      try {
        if (ent.editIdx !== null) throw new Error("أكمل تعديل السطر أو ألغه أولاً");
        if (woIn.value.trim() && !(await confirmSheet(`في سطر الإدخال الطقم ${woIn.value.trim()} ولم يُضَف.\n\nالترحيل بدونه؟`, "ترحيل بدونه"))) return;
        if (!inv.shopId) throw new Error("اختر المحل");
        D.checkLines(inv.lines);
        const t = D.totals(inv.lines, inv.vat);
        const label = inv.kind === "sale" ? "فاتورة بيع" : "مرتجع بيع";
        const msg = `${editing ? "حفظ تعديل" : "ترحيل"} ${label} على «${shopTitle(inv.shopId)}»\n` +
          `${inv.lines.filter((l) => !l.wageOnly).length} طقم · ${gw(t.totalW18)} جم عيار ${vk()}\n` +
          `الأجور ${f2(t.wages)}${inv.vat ? ` + ضريبة ${f2(t.vatAmt)}` : ""} = ${f2(t.grand)} ريال`;
        if (!(await confirmSheet(msg, editing ? "حفظ التعديل" : "ترحيل"))) return;
        const rec = D.saveInvoice(s, { ...inv, heldId: inv.heldId });
        const ops = [["invoices", "put", rec], ...S.meta(s)];
        if (inv.heldId) ops.push(["held", "del", inv.heldId]);
        if (await persist(ops)) {
          clearDraft();
          toast(`${editing ? "حُفظ تعديل" : "رُحّلت"} ${rec.no}`);
          replace(`doc/inv/${rec.id}`);
        }
      } catch (e) { err(e); }
    }

    async function hold() {
      try {
        if (!inv.lines.length) throw new Error("لا بنود لتعليقها");
        const rec = { id: inv.heldId || D.uid("hd_"), kind: inv.kind, shopId: inv.shopId, date: inv.date,
          vat: inv.vat, desc: inv.desc, lines: inv.lines, savedAt: new Date().toISOString() };
        const i = s.held.findIndex((x) => x.id === rec.id);
        if (i >= 0) s.held[i] = rec; else s.held.push(rec);
        if (await persist([["held", "put", rec]])) {
          clearDraft();
          toast("عُلّقت الفاتورة — تجدها في «المعلّقات»");
          replace("held");
        }
      } catch (e) { err(e); }
    }

    const entryCard = h("div", { class: "card" }, h("h2", null, "② إدخال الطقم"),
      h("div", { class: "grid2" },
        field("رقم التشغيل", woIn), field("رقم الموديل", modelIn),
        field("الذهب", gold), field("الفصوص", small),
        field("الأحجار", big), field("الأحجار بعد الخصم", after),
        field("💎 الماس (للعرض)", dia), field("العيار", karatSel),
        field("الوزن المقيد", reg), field("الوزن القائم", stand),
        field("الأجر/جم", wage), h("label", { class: "f" }, h("span", null, "الأجرة (ريال)"),
          h("div", { class: "in", style: { display: "flex", alignItems: "center", justifyContent: "center" } }, wagesOut))),
      // الأزرار قبل الإشعار: الإشعار يظهر عند مغادرة خانة رقم التشغيل —
      // ولو كان فوقها لانزاح الزرّ تحت الإصبع فتقع اللمسة على غيره
      h("div", { class: "row", style: { marginTop: "10px" } }, addBtn,
        h("button", { type: "button", class: "btn ghost", onclick: wageOnly }, "+ أجر فقط"), cancelEdit),
      notice);

    v.append(
      h("div", { class: "card" }, h("h2", null, "① العملية والمحل"), kindSeg, h("div", { style: { height: "8px" } }),
        shopBtn, shopNote, h("div", { class: "grid2", style: { marginTop: "8px" } },
          field("التاريخ", dateIn), h("label", { class: "switch" }, vatIn, "ضريبة 15% على الأجور"),
          h("div", { class: "span2" }, descIn))),
      entryCard,
      h("div", { class: "card" }, h("h2", null, "③ بنود الفاتورة"), linesBox, totalsBox),
      h("div", { class: "footer-bar" },
        h("button", { class: "btn", onclick: save }, editing ? "حفظ التعديل" : "ترحيل الفاتورة"),
        editing ? null : h("button", { class: "btn ghost", onclick: hold }, "⏸ تعليق")));
    renderShop();
    refresh();
    showWages();
    if (!inv.shopId) setTimeout(() => shopBtn.click(), 150); else setTimeout(() => woIn.focus(), 150);
  }

  const Num_round3 = (x) => root.Num.pyRound(x, 3);
  const Num_round2 = (x) => root.Num.pyRound(x, 2);

  // ══ السند (قبض · صرف) ══
  function voucherEditor(q, mode, docId) {
    const s = st();
    let vo;
    if (mode === "edit") {
      const d = s.vouchers.find((x) => x.id === docId);
      if (!d) { replace("log"); return; }
      vo = JSON.parse(JSON.stringify(d));
    } else {
      vo = { id: null, kind: q.kind === "payment" ? "payment" : "receipt", shopId: q.shop || "", date: D.today(),
        notes: "", rows: [{ kind: "gold", weight: 0, karat: vk(), notes: "" }], discCash: 0, discGold18: 0, netDiff: 0 };
    }
    const editing = mode === "edit";
    const k = vk();
    const title = () => (vo.kind === "receipt" ? "سند قبض" : "سند صرف") + (editing ? ` — تعديل ${vo.no}` : "");
    setBar(title(), vo.kind === "receipt" ? "استلام ذهب أو نقد من المحل" : "تسليم ذهب أو نقد للمحل", { noTabs: true });
    const v = view();
    const kindSeg = h("div", { class: "seg" });
    for (const [kk, label] of [["receipt", "سند قبض"], ["payment", "سند صرف"]]) {
      kindSeg.append(h("button", { type: "button", "data-k": kk, class: kk === vo.kind ? "on" : "", disabled: editing,
        onclick: () => {
          vo.kind = kk;
          for (const b of kindSeg.children) b.classList.toggle("on", b.dataset.k === kk);
          setBar(title(), "", { noTabs: true });
          extras.style.display = kk === "receipt" ? "" : "none";
          refresh();
        } }, label));
    }
    const shopBtn = h("button", { type: "button", class: "pick" });
    const renderShop = () => {
      shopBtn.innerHTML = "";
      const sh = D.shopById(s, vo.shopId);
      shopBtn.append(sh ? h("span", { class: "t" }, sh.name) : h("span", { class: "ph" }, "اختر المحل…"), h("span", null, "▾"));
    };
    shopBtn.addEventListener("click", async () => {
      const it = await pickSheet("اختر المحل", shopItems(), { addLabel: "+ محل جديد", empty: "لا محلات بعد" });
      if (!it) return;
      if (it.add) { go("shop-form"); return; }
      vo.shopId = it.id; renderShop(); refresh();
    });
    const dateIn = h("input", { class: "in", type: "date", value: vo.date, onchange: (e) => { vo.date = e.target.value || D.today(); } });
    const notesIn = h("input", { class: "in", value: vo.notes, placeholder: "البيان (اختياري)", oninput: (e) => { vo.notes = e.target.value; } });

    const rowsBox = h("div");
    const inputs = [];
    function renderRows() {
      rowsBox.innerHTML = "";
      inputs.length = 0;
      vo.rows.forEach((r, i) => {
        const card = h("div", { class: "line" });
        const top = h("div", { class: "top" },
          h("b", null, r.kind === "gold" ? "ذهب" : "نقد"),
          h("div", { class: "act" }, h("button", { class: "del", onclick: () => { vo.rows.splice(i, 1); renderRows(); refresh(); } }, "✕")));
        card.append(top);
        if (r.kind === "gold") {
          const w = numInput({ value: r.weight });
          const ks = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: `عيار ${x}` })));
          ks.value = String(r.karat || k);
          const eq = h("div", { class: "muted small num" });
          const upd = () => {
            r.weight = w.getVal() || 0; r.karat = parseInt(ks.value, 10);
            const vg = G.voucherGold(r.weight, r.karat);
            eq.textContent = `= ${f2(vg.equiv)} جم عيار 18` + (k !== 18 ? ` · ${gw(vg.equiv)} جم عيار ${k}` : "");
            refresh();
          };
          w.addEventListener("input", upd); ks.addEventListener("change", upd);
          card.append(h("div", { class: "grid2", style: { marginTop: "6px" } }, field("الوزن الفعلي (جم)", w), field("العيار", ks)), eq);
          inputs.push(w);
          upd();
        } else {
          const a = numInput({ value: r.amount });
          a.addEventListener("input", () => { r.amount = a.getVal() || 0; refresh(); });
          card.append(h("div", { style: { marginTop: "6px" } }, field("المبلغ (ريال)", a)));
          inputs.push(a);
        }
        const n = h("input", { class: "in", value: r.notes || "", placeholder: "بيان السطر (اختياري)",
          oninput: (e) => { r.notes = e.target.value; } });
        card.append(h("div", { style: { marginTop: "6px" } }, n));
        rowsBox.append(card);
      });
      if (!vo.rows.length) rowsBox.append(h("div", { class: "empty" }, "أضف سطر ذهب أو نقد"));
    }
    const dGold = numInput({ value: G.g(vo.discGold18, k) });
    const dCash = numInput({ value: vo.discCash });
    const nDiff = numInput({ value: vo.netDiff });
    for (const el of [dGold, dCash, nDiff]) el.addEventListener("input", refresh);
    const extras = h("details", { class: "card", style: { display: vo.kind === "receipt" ? "" : "none" } },
      h("summary", { class: "sec-title", style: { margin: "0" } }, "خصومات وفرق صافي (اختياري)"),
      h("div", { class: "grid2", style: { marginTop: "10px" } },
        field(`خصم مسموح وزناً (جم عيار ${k})`, dGold), field("خصم مسموح نقداً (ريال)", dCash),
        field("فرق الصافي (ريال، + زيادة · − تخفيض)", nDiff, "span2")));
    if (vo.discCash || vo.discGold18 || vo.netDiff) extras.open = true;

    const totalsBox = h("div", { class: "totals" });
    function draft() {
      return { ...vo, discGold18: G.store(dGold.getVal() || 0, k), discCash: dCash.getVal() || 0, netDiff: nDiff.getVal() || 0 };
    }
    function refresh() {
      totalsBox.innerHTML = "";
      let rows;
      try { rows = D.voucherRows(vo.rows); } catch (e) { rows = []; }
      let eq = 0, cash = 0;
      for (const r of rows) { eq += r.equiv; cash += r.amount; }
      const row = (a, b) => h("div", { class: "spread" }, h("span", null, a), h("span", { class: "num" }, b));
      totalsBox.append(row("الذهب (مكافئ عيار 18)", f2(Num_round3(eq))),
        k !== 18 ? row(`الذهب (عيار ${k})`, gw(Num_round3(eq))) : null, row("النقد", f2(Num_round2(cash)) + " ريال"));
      if (vo.shopId) {
        const dv = draft();
        const before = D.balance(s, vo.shopId, vo.id);
        let e;
        try {
          e = D.effects({ kind: vo.kind, rows, discCash: Num_round2(dv.discCash), discGold18: Num_round3(dv.discGold18),
            netDiff: Num_round2(dv.netDiff) });
        } catch (x) { e = { gd: 0, gc: 0, cd: 0, cc: 0 }; }
        totalsBox.append(h("hr", { class: "sep" }),
          h("div", { class: "spread small" }, h("span", null, "رصيد الذهب قبل"), goldBal(before.gold18)),
          h("div", { class: "spread small" }, h("span", null, "رصيد الذهب بعد"), goldBal(Num_round3(before.gold18 + e.gd - e.gc))),
          h("div", { class: "spread small" }, h("span", null, "رصيد النقد قبل"), cashBal(before.cash)),
          h("div", { class: "spread small" }, h("span", null, "رصيد النقد بعد"), cashBal(Num_round2(before.cash + e.cd - e.cc))));
      }
    }
    async function save() {
      try {
        if (!vo.shopId) throw new Error("اختر المحل");
        const dv = draft();
        if ([dGold.getVal(), dCash.getVal(), nDiff.getVal()].some((x) => !isFinite(x))) throw new Error("رقمٌ غير صحيح");
        const rows = D.voucherRows(vo.rows);
        const label = vo.kind === "receipt" ? "سند قبض" : "سند صرف";
        let eq = 0, cash = 0;
        for (const r of rows) { eq += r.equiv; cash += r.amount; }
        const msg = `${editing ? "حفظ تعديل" : "ترحيل"} ${label} — «${shopTitle(vo.shopId)}»\n` +
          `ذهب ${f2(Num_round3(eq))} جم عيار 18 · نقد ${f2(Num_round2(cash))} ريال`;
        if (!(await confirmSheet(msg, editing ? "حفظ التعديل" : "ترحيل"))) return;
        const rec = D.saveVoucher(s, dv);
        if (await persist([["vouchers", "put", rec], ...S.meta(s)])) {
          toast(`${editing ? "حُفظ تعديل" : "رُحّل"} ${rec.no}`);
          replace(`doc/vo/${rec.id}`);
        }
      } catch (e) { err(e); }
    }
    v.append(
      h("div", { class: "card" }, kindSeg, h("div", { style: { height: "8px" } }), shopBtn,
        h("div", { class: "grid2", style: { marginTop: "8px" } }, field("التاريخ", dateIn), field("البيان", notesIn))),
      h("div", { class: "card" }, h("h2", null, "الأسطر"), rowsBox,
        h("div", { class: "row" },
          h("button", { class: "btn ghost grow", onclick: () => { vo.rows.push({ kind: "gold", weight: 0, karat: k, notes: "" }); renderRows(); } }, "+ ذهب"),
          h("button", { class: "btn ghost grow", onclick: () => { vo.rows.push({ kind: "cash", amount: 0, notes: "" }); renderRows(); } }, "+ نقد"))),
      extras,
      h("div", { class: "card" }, totalsBox),
      h("div", { class: "footer-bar" }, h("button", { class: "btn", onclick: save }, editing ? "حفظ التعديل" : "ترحيل السند")));
    renderShop(); renderRows(); refresh();
    if (!vo.shopId) setTimeout(() => shopBtn.click(), 150);
  }

  // ══ عرض المستند: مشاركة · طباعة · تعديل · حذف ══
  function docView(type, id) {
    const s = st();
    const isInv = type === "inv";
    const d = (isInv ? s.invoices : s.vouchers).find((x) => x.id === id);
    if (!d) { replace("log"); return; }
    setBar(`${D.KIND_LABEL[d.kind]} ${d.no}`, `${shopTitle(d.shopId)} · ${dmy(d.date)}`);
    setTab("log");
    const html = isInv ? P.invoiceHtml(s, d) : P.voucherHtml(s, d);
    const v = view();
    const name = `${d.no}`;
    v.append(h("div", { class: "quick" },
      quickBtn("📷", "مشاركة صورة", () => B.shareHtmlImage(html, name)),
      quickBtn("🖨", "طباعة / PDF", () => B.printHtml(html, name)),
      isInv ? quickBtn("💬", "نص واتساب", () => B.shareText(P.invoiceText(s, d))) : quickBtn("📒", "كشف الحساب", () => go(`statement/${d.shopId}`)),
      quickBtn("✎", "تعديل", () => go(`${isInv ? "invoice" : "voucher"}/edit/${d.id}`)),
      quickBtn("🗑", "حذف", async () => {
        if (!(await confirmSheet(`حذف ${D.KIND_LABEL[d.kind]} ${d.no}؟\n\nيُلغى أثره من رصيد «${shopTitle(d.shopId)}».`, "حذف", true))) return;
        if (isInv) D.deleteInvoice(s, d.id); else D.deleteVoucher(s, d.id);
        if (await persist([[isInv ? "invoices" : "vouchers", "del", d.id]])) { toast(`حُذف ${d.no}`); replace(`shop/${d.shopId}`); }
      }),
      isInv ? quickBtn("📒", "كشف الحساب", () => go(`statement/${d.shopId}`)) : quickBtn("🏪", "المحل", () => go(`shop/${d.shopId}`))));
    v.append(previewFrame(html));
  }

  function previewFrame(html) {
    const box = h("div", { class: "preview" });
    const fr = h("iframe", { title: "معاينة" });
    fr.srcdoc = html;
    box.append(fr);
    const fit = () => {
      const w = box.clientWidth || 360;
      const sc = w / 1000;
      fr.style.width = "1000px";
      fr.style.transform = `scale(${sc})`;
      try {
        const ht = fr.contentDocument.documentElement.scrollHeight;
        fr.style.height = ht + "px";
        box.style.height = Math.ceil(ht * sc) + "px";
      } catch (e) { /* */ }
    };
    fr.addEventListener("load", () => { fit(); setTimeout(fit, 300); });
    window.addEventListener("resize", fit, { once: true });
    return box;
  }

  // ══ كشف الحساب ══
  function statementScreen(id, q) {
    const s = st();
    const shop = D.shopById(s, id);
    if (!shop) { replace("shops"); return; }
    setBar("كشف حساب", shop.name);
    setTab("shops");
    const v = view();
    const from = h("input", { class: "in", type: "date", value: q.from || "" });
    const to = h("input", { class: "in", type: "date", value: q.to || "" });
    const chips = h("div", { class: "chips", style: { margin: "8px 0" } });
    const t = D.today();
    const ym = t.slice(0, 7);
    const prev = (() => { const d = new Date(+t.slice(0, 4), +t.slice(5, 7) - 2, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; })();
    const last = (ymS) => { const d = new Date(+ymS.slice(0, 4), +ymS.slice(5, 7), 0); return `${ymS}-${String(d.getDate()).padStart(2, "0")}`; };
    const presets = [["الكل", "", ""], ["هذا الشهر", ym + "-01", ""], ["الشهر الماضي", prev + "-01", last(prev)], ["هذه السنة", t.slice(0, 4) + "-01-01", ""]];
    for (const [label, a, b] of presets) {
      chips.append(h("button", { class: "chip" + ((q.from || "") === a && (q.to || "") === b ? " on" : ""),
        onclick: () => replace(`statement/${id}?from=${a}&to=${b}`) }, label));
    }
    const apply = () => replace(`statement/${id}?from=${from.value}&to=${to.value}`);
    from.addEventListener("change", apply); to.addEventListener("change", apply);
    const res = D.statement(s, id, q.from || null, q.to || null);
    const html = () => P.statementHtml(s, id, q.from || null, q.to || null);
    v.append(h("div", { class: "card" }, h("div", { class: "grid2" }, field("من", from), field("إلى", to)), chips),
      h("div", { class: "kpis" },
        h("div", { class: "kpi" }, h("b", null, `رصيد الذهب (عيار ${vk()})`), h("div", { class: "v num" }, goldBal(res.gold18))),
        h("div", { class: "kpi" }, h("b", null, "رصيد النقد"), h("div", { class: "v num" }, cashBal(res.cash)))),
      h("div", { class: "row", style: { marginBottom: "12px" } },
        h("button", { class: "btn ghost grow", onclick: () => B.shareHtmlImage(html(), `كشف ${shop.name}`) }, "📷 مشاركة صورة"),
        h("button", { class: "btn ghost grow", onclick: () => B.printHtml(html(), `كشف ${shop.name}`) }, "🖨 طباعة / PDF")));
    const card = h("div", { class: "card" });
    if (!res.rows.length) card.append(h("div", { class: "empty" }, "لا حركة في الفترة"));
    const k = vk();
    const z = (x) => (x ? f2(x) : "—");
    for (const r of res.rows.slice().reverse()) {
      const type = r.doc ? (r.doc.kind === "sale" || r.doc.kind === "sale_return" ? "inv" : "vo") : null;
      card.append(h("div", { class: "st-row", onclick: () => type && go(`doc/${type}/${r.doc.id}`) },
        h("div", { class: "spread" }, h("span", null, h("b", null, r.label), " ", h("span", { class: "muted small", dir: "ltr", text: r.no })),
          h("span", { class: "muted small", dir: "ltr", text: dmy(r.date) })),
        r.desc ? h("div", { class: "muted small", text: r.desc }) : null,
        h("div", { class: "cols" },
          h("div", null, h("span", { class: "muted" }, "ذهب: "), h("span", { class: "num" }, r.gd ? "+" + z(G.g(r.gd, k)) : r.gc ? "−" + z(G.g(r.gc, k)) : "—"),
            h("div", null, h("span", { class: "muted" }, "الرصيد "), h("b", { class: "num" }, f2(G.g(r.gbal, k))))),
          h("div", null, h("span", { class: "muted" }, "نقد: "), h("span", { class: "num" }, r.cd ? "+" + z(r.cd) : r.cc ? "−" + z(r.cc) : "—"),
            h("div", null, h("span", { class: "muted" }, "الرصيد "), h("b", { class: "num" }, f2(r.cbal)))))));
    }
    v.append(card);
  }

  // ══ سجل العمليات ══
  function logScreen(q) {
    const s = st();
    setBar("سجل العمليات", "الفواتير والسندات", { back: false });
    setTab("log");
    const v = view();
    let kind = q.kind || "";
    const search = h("input", { class: "in", type: "search", placeholder: "ابحث برقم المستند أو المحل أو رقم التشغيل…", value: q.q || "" });
    const chips = h("div", { class: "chips", style: { margin: "8px 0" } });
    const list = h("div");
    const render = () => {
      const t = search.value.trim();
      let docs = [...s.invoices, ...s.vouchers];
      if (kind) docs = docs.filter((d) => d.kind === kind);
      if (t) {
        docs = docs.filter((d) => d.no.includes(t) || shopTitle(d.shopId).includes(t) ||
          (d.lines && d.lines.some((l) => (l.wo || "").includes(t) || (l.model || "").includes(t))) ||
          (d.desc || d.notes || "").includes(t));
      }
      docs.sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : (a.createdAt < b.createdAt ? 1 : -1)));
      list.innerHTML = "";
      if (!docs.length) list.append(h("div", { class: "empty" }, "لا عمليات"));
      docs.slice(0, 300).forEach((d) => list.append(docItem(d)));
    };
    for (const [kk, label] of [["", "الكل"], ["sale", "بيع"], ["sale_return", "مرتجع"], ["receipt", "قبض"], ["payment", "صرف"]]) {
      chips.append(h("button", { class: "chip" + (kk === kind ? " on" : ""), onclick: (e) => {
        kind = kk;
        for (const c of chips.children) c.classList.remove("on");
        e.target.classList.add("on");
        render();
      } }, label));
    }
    search.addEventListener("input", render);
    v.append(search, chips, list);
    render();
  }

  // ══ حركة رقم التشغيل ══
  function woScreen(q) {
    const s = st();
    setBar("حركة الطقم", "كل ما جرى على رقم التشغيل");
    setTab("more");
    const v = view();
    const inp = h("input", { class: "in n hl", placeholder: "رقم التشغيل", value: q.no || "", enterkeyhint: "search" });
    const out = h("div");
    const render = () => {
      const no = inp.value.trim();
      out.innerHTML = "";
      if (!no) return;
      const hist = D.woHistory(s, no);
      if (!hist.length) { out.append(h("div", { class: "empty" }, `لا حركة للرقم ${no}`)); return; }
      const last = hist[hist.length - 1];
      out.append(h("div", { class: "note-bar " + (last.kind === "sale" ? "warn" : "info"), style: { marginBottom: "10px" } },
        last.kind === "sale" ? `الآن: عند «${last.shop ? last.shop.name : "—"}» — مباعٌ بالفاتورة ${last.inv.no}`
          : `الآن: عندك — رجع بالمرتجع ${last.inv.no} من «${last.shop ? last.shop.name : "—"}»`));
      for (const m of hist.slice().reverse()) {
        const lk = m.line.karat || 18;
        out.append(h("div", { class: "list-item", onclick: () => go(`doc/inv/${m.inv.id}`) },
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t" }, m.shop ? m.shop.name : "—"), kindBadge(m.kind)),
            h("div", { class: "spread muted small" },
              h("span", null, h("span", { dir: "ltr", text: m.inv.no }), " · ", h("span", { dir: "ltr", text: dmy(m.date) })),
              h("span", { class: "num" }, `${gw(m.line.reg18, lk)} جم ${lk} · أجر ${f2(G.wageView(m.line.rate18, lk))}`)))));
      }
    };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); render(); } });
    inp.addEventListener("change", render);
    v.append(h("div", { class: "card" }, field("رقم التشغيل", inp)), out);
    render();
    if (!q.no) setTimeout(() => inp.focus(), 100);
  }

  // ══ المعلّقات ══
  function heldScreen() {
    const s = st();
    setBar("المعلّقات", "فواتير لم تُرحَّل بعد");
    setTab("more");
    const v = view();
    if (!s.held.length) { v.append(h("div", { class: "empty" }, "لا فواتير معلّقة")); return; }
    for (const hd of s.held.slice().sort((a, b) => (a.savedAt < b.savedAt ? 1 : -1))) {
      const t = D.totals(hd.lines, hd.vat);
      v.append(h("div", { class: "list-item" },
        h("div", { class: "grow", onclick: () => go(`invoice/held/${hd.id}`) },
          h("div", { class: "spread" }, h("span", { class: "t" }, shopTitle(hd.shopId)), kindBadge(hd.kind)),
          h("div", { class: "muted small" }, `${hd.lines.length} سطر · ${gw(t.totalW18)} جم · ${f2(t.grand)} ريال · ${dmy((hd.savedAt || "").slice(0, 10))}`)),
        h("div", { class: "act" }, h("button", { class: "del", onclick: async () => {
          if (!(await confirmSheet("حذف الفاتورة المعلّقة؟", "حذف", true))) return;
          s.held = s.held.filter((x) => x.id !== hd.id);
          if (await persist([["held", "del", hd.id]])) render();
        } }, "✕"))));
    }
    function render() { view().innerHTML = ""; heldScreen(); }
  }

  // ══ المزيد ══
  function moreScreen() {
    setBar("المزيد", "", { back: false });
    setTab("more");
    const v = view();
    const item = (icon, t, sub, fn) => h("div", { class: "list-item", onclick: fn },
      h("span", { style: { fontSize: "22px" } }, icon), h("div", { class: "grow" }, h("div", { class: "t" }, t),
        sub ? h("div", { class: "muted small" }, sub) : null), h("span", { class: "muted" }, "‹"));
    v.append(
      item("🔎", "حركة الطقم", "كل ما جرى على رقم تشغيل: بيع ومرتجع", () => go("wo")),
      item("⏸", "المعلّقات", `${st().held.length} فاتورة لم تُرحَّل`, () => go("held")),
      item("📒", "كشف حساب محل", "", pickShopThen((id) => go(`statement/${id}`))),
      item("⚙️", "الإعدادات والنسخ الاحتياطي", "اسم النشاط · العيار · المظهر · حفظ واسترجاع البيانات", () => go("settings")));
  }

  // ══ الإعدادات والنسخ الاحتياطي ══
  function settingsScreen() {
    const s = st();
    setBar("الإعدادات", "", {});
    setTab("more");
    const v = view();
    const S0 = s.settings;
    const name = h("input", { class: "in", value: S0.name, placeholder: "يظهر أعلى الفواتير" });
    const phone = h("input", { class: "in", value: S0.phone, inputmode: "tel", dir: "ltr" });
    const address = h("input", { class: "in", value: S0.address });
    const vatNo = h("input", { class: "in", value: S0.vatNo, inputmode: "numeric", dir: "ltr", placeholder: "للفواتير الضريبية (رمز QR)" });
    const karat = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: `عيار ${x}` })));
    karat.value = String(S0.viewKarat || 18);
    const rate = numInput({ value: Num_round2((S0.stoneRate ?? 0.5) * 100), raw: true });
    const showBal = h("input", { type: "checkbox", checked: S0.showBalanceOnInvoice });
    const theme = h("select", { class: "in" }, h("option", { value: "auto", text: "تلقائي (حسب الجوال)" }),
      h("option", { value: "light", text: "☀ فاتح" }), h("option", { value: "dark", text: "🌙 ليلي" }));
    theme.value = S0.theme || "auto";
    const save = async () => {
      try {
        const r = rate.getVal();
        if (!isFinite(r) || r < 0 || r > 100) throw new Error("نسبة خصم الأحجار بين 0 و100");
        Object.assign(S0, { name: name.value.trim(), phone: phone.value.trim(), address: address.value.trim(),
          vatNo: vatNo.value.trim(), viewKarat: parseInt(karat.value, 10), stoneRate: r / 100,
          showBalanceOnInvoice: showBal.checked, theme: theme.value });
        applyTheme();
        if (await persist(S.meta(s))) toast("حُفظت الإعدادات");
      } catch (e) { err(e); }
    };
    const backupName = () => `jadeite-backup-${D.today()}.json`;
    const doBackup = async (share) => {
      const text = JSON.stringify(D.toBackup(s));
      if (share) B.shareFile(backupName(), text); else B.saveFile(backupName(), text);
      s.settings.lastBackup = new Date().toISOString();
      await persist(S.meta(s));
      toast(share ? "اختر أين تحفظ النسخة (واتساب · درايف · …)" : "حُفظت النسخة في «التنزيلات»");
    };
    const fileIn = h("input", { type: "file", accept: ".json,application/json", style: { display: "none" } });
    fileIn.addEventListener("change", async () => {
      const f = fileIn.files && fileIn.files[0];
      fileIn.value = "";
      if (!f) return;
      try {
        const obj = JSON.parse(await f.text());
        const ns = D.fromBackup(obj);
        const msg = `استرجاع النسخة المحفوظة ${(obj.savedAt || "").slice(0, 10)}:\n` +
          `${ns.shops.length} محل · ${ns.invoices.length} فاتورة · ${ns.vouchers.length} سند\n\n` +
          "تُستبدل بها كل البيانات الحالية في هذا الجوال.";
        if (!(await confirmSheet(msg, "استرجاع", true))) return;
        await S.replaceAll(ns);
        App.state = ns;
        applyTheme();
        toast("استُرجعت البيانات");
        replace("home");
      } catch (e) { err(e.name === "SyntaxError" ? new Error("الملف تالف أو ليس نسخةً احتياطية") : e); }
    });
    v.append(
      h("div", { class: "card" }, h("h2", null, "بيانات النشاط (تظهر في الفواتير)"),
        field("الاسم", name), h("div", { style: { height: "8px" } }),
        h("div", { class: "grid2" }, field("الجوال", phone), field("الرقم الضريبي", vatNo)),
        h("div", { style: { height: "8px" } }), field("العنوان", address)),
      h("div", { class: "card" }, h("h2", null, "الحساب والعرض"),
        h("div", { class: "grid2" }, field("عيار العرض", karat), field("نسبة خصم الأحجار %", rate),
          field("المظهر", theme, "span2")),
        h("label", { class: "switch" }, showBal, "إظهار رصيد المحل في الفاتورة"),
        h("div", { class: "muted small" }, "الأوزان تُحفظ دائماً بمكافئ عيار 18 كما في البرنامج — العيار هنا وحدة عرضٍ فقط.")),
      h("button", { class: "btn block", onclick: save, style: { marginBottom: "12px" } }, "حفظ الإعدادات"),
      h("div", { class: "card" }, h("h2", null, "النسخ الاحتياطي"),
        h("div", { class: "muted small", style: { marginBottom: "10px" } },
          "البيانات في هذا الجوال وحده. احفظ نسخةً بانتظام (واحفظها خارج الجوال: واتساب أو درايف) — " +
          "حذفُ التطبيق يحذف بياناته." + (S0.lastBackup ? `\nآخر نسخة: ${dmy(S0.lastBackup.slice(0, 10))}` : "\nلم تُحفظ نسخة بعد.")),
        h("div", { class: "grid2" },
          h("button", { class: "btn", onclick: () => doBackup(false) }, "💾 حفظ في التنزيلات"),
          h("button", { class: "btn ghost", onclick: () => doBackup(true) }, "📤 مشاركة النسخة")),
        h("button", { class: "btn ghost block", style: { marginTop: "8px" }, onclick: () => fileIn.click() }, "♻ استرجاع من نسخة"),
        fileIn),
      h("div", { class: "muted small", style: { textAlign: "center", margin: "16px 0" } },
        `جاديت للجوال · الإصدار ${B.appVersion()} · ${s.shops.length} محل · ${s.invoices.length} فاتورة · ${s.vouchers.length} سند`));
  }

  // ══ «+ جديد» ══
  async function newSheet() {
    const r = await sheet((box, close) => {
      box.append(h("h3", null, "عملية جديدة"),
        h("div", { class: "quick" },
          quickBtn("🧾", "فاتورة بيع", () => close("invoice/new?kind=sale")),
          quickBtn("↩️", "مرتجع بيع", () => close("invoice/new?kind=sale_return")),
          quickBtn("🏪", "محل جديد", () => close("shop-form")),
          quickBtn("📥", "سند قبض", () => close("voucher/new?kind=receipt")),
          quickBtn("📤", "سند صرف", () => close("voucher/new?kind=payment")),
          quickBtn("🔎", "حركة الطقم", () => close("wo"))));
    });
    if (r) setTimeout(() => go(r), 30);
  }

  // ══ التنقّل ══
  function parse() {
    const raw = (location.hash || "").replace(/^#\/?/, "");
    const [path, qs] = raw.split("?");
    const q = {};
    for (const part of (qs || "").split("&")) {
      if (!part) continue;
      const [a, b] = part.split("=");
      q[decodeURIComponent(a)] = decodeURIComponent(b || "");
    }
    return { parts: (path || "home").split("/"), q };
  }

  function route() {
    const { parts, q } = parse();
    const v = view();
    v.innerHTML = "";
    window.scrollTo(0, 0);
    try {
      switch (parts[0]) {
        case "home": return home();
        case "shops": return shops();
        case "shop": return shopPage(parts[1]);
        case "shop-form": return shopForm(parts[1]);
        case "invoice": return invoiceEditor(q, parts[1], parts[2]);
        case "voucher": return voucherEditor(q, parts[1], parts[2]);
        case "doc": return docView(parts[1], parts[2]);
        case "statement": return statementScreen(parts[1], q);
        case "log": return logScreen(q);
        case "wo": return woScreen(q);
        case "held": return heldScreen();
        case "more": return moreScreen();
        case "settings": return settingsScreen();
        default: return home();
      }
    } catch (e) {
      err(e);
      console.error(e);
    }
  }

  function applyTheme() {
    const t = st().settings.theme || "auto";
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  }

  async function start() {
    App.state = await S.load();
    applyTheme();
    for (const b of document.querySelectorAll("#tabs button")) {
      b.addEventListener("click", () => {
        const t = b.dataset.tab;
        if (t === "plus") newSheet(); else go(t);
      });
    }
    window.addEventListener("hashchange", route);
    if (!location.hash) location.replace("#/home");
    route();
  }

  App.start = start;
  App.go = go;
  document.addEventListener("DOMContentLoaded", start);
})(window);
