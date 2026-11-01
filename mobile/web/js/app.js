/* نظام محاسبي للذهب (الجوال) — الشاشات والتنقّل.
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

  // الرصيد بكلمته: المحل «عليه» (لي عنده) أو «له»، والمصنع «عليّ» (له عندي) أو «لي»
  function balWord(v, fac) {
    if (fac) return v < 0 ? "عليّ" : "لي";
    return v > 0 ? "عليه" : "له";
  }
  function balSpan(v, unit, fac) {
    if (Math.abs(v) < 0.005) return h("span", { class: "muted" }, "0.00");
    const owing = fac ? v < 0 : v > 0;   // أحمر: ما على المحل لي، أو ما عليّ للمصنع
    return h("span", { class: owing ? "bal-on" : "bal-for" }, `${f2(Math.abs(v))} ${unit} ${balWord(v, fac)}`);
  }
  function balText(v, unit, fac) {
    if (Math.abs(v) < 0.005) return "0.00";
    return `${f2(Math.abs(v))} ${unit} ${balWord(v, fac)}`;
  }
  function goldBal(w18, fac) { return balSpan(G.g(w18, vk()), "جم", fac); }
  function cashBal(c, fac) { return balSpan(c, "ريال", fac); }
  const APP_NAME = "نظام محاسبي للذهب";

  // الانتقال بعد أن يكتمل رجوع السجل الذي يتبع إغلاق نافذةٍ سفلية — وإلا ألغاه
  function go(path) { root.UI.idle().then(() => { location.hash = "#/" + path; }); }
  function replace(path) { root.UI.idle().then(() => location.replace("#/" + path)); }

  async function persist(ops) {
    try { await S.write(ops); scheduleAutoBackup(); return true; }
    catch (e) { err(new Error("تعذّر الحفظ في الجوال: " + ((e && e.message) || e))); return false; }
  }

  // نسخةٌ في مجلد الحفظ التلقائي (خارج التطبيق) بعد كل تغيير — بتأنٍّ يسير
  // فتُجمع التغييرات المتتابعة في كتابةٍ واحدة
  let backupTimer = null;
  function scheduleAutoBackup() {
    if (!B.native || !B.backupFolder()) return;
    clearTimeout(backupTimer);
    backupTimer = setTimeout(() => B.autoBackup(JSON.stringify(D.toBackup(st()))), 1200);
  }
  function lastAutoBackup() {
    try { return localStorage.getItem("lastAutoBackup") || ""; } catch (e) { return ""; }
  }

  function setBar(title, sub, opts) {
    const o = opts || {};
    const bar = document.getElementById("bar");
    bar.innerHTML = "";
    if (o.back !== false) {
      bar.appendChild(h("button", { class: "icon-btn", "aria-label": "رجوع",
        onclick: () => (history.length > 1 ? history.back() : go("home")) }, ico("back", 22)));
    }
    if (o.logo) bar.appendChild(h("img", { class: "bar-logo", src: "img/icon.png", alt: "" }));
    bar.appendChild(h("h1", null, title,
      sub ? (sub instanceof Node ? sub : h("span", { class: "sub", text: sub })) : null));
    for (const a of o.actions || []) bar.appendChild(a);
    document.body.classList.toggle("no-tabs", !!o.noTabs);
    document.title = title;
  }

  // مستمعٌ لأحداث الأصل يخصّ الشاشة الحالية — يُزال تلقائياً عند الانتقال منها
  let routeOffs = [];
  function onRoute(ev, fn) {
    const off = B.on(ev, fn);
    routeOffs.push(off);
    return off;
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

  const isInvKind = (k) => D.SHOP_KINDS.includes(k) || D.FACTORY_KINDS.includes(k);
  const isRetKind = (k) => ["sale_return", "purchase_return", "payment"].includes(k);
  const KIND_ICON = { sale: "receipt", sale_return: "return", purchase: "package", purchase_return: "return",
    receipt: "in", payment: "out" };
  function kindBadge(kind) {
    return h("span", { class: "badge" + (isRetKind(kind) ? " ret" : ""), text: D.KIND_LABEL[kind] });
  }

  function docSummary(d) {
    if (isInvKind(d.kind)) return `${gw(d.totalW18)} جم · أجور ${f2(d.grand)}`;
    const parts = [];
    if (d.gold18) parts.push(`${gw(d.gold18)} جم`);
    if (d.cash) parts.push(`${f2(d.cash)} ريال`);
    return parts.join(" · ") || "—";
  }

  function docItem(d) {
    const type = isInvKind(d.kind) ? "inv" : "vo";
    return h("div", { class: "list-item", onclick: () => go(`doc/${type}/${d.id}`) },
      h("span", { class: "avatar" + (isRetKind(d.kind) ? " ret" : "") }, ico(KIND_ICON[d.kind] || "file", 20)),
      h("div", { class: "grow" },
        h("div", { class: "spread" }, h("span", { class: "t", text: shopTitle(d.shopId) }), kindBadge(d.kind)),
        h("div", { class: "spread muted small" },
          h("span", null, h("span", { dir: "ltr", text: d.no }), " · ", h("span", { dir: "ltr", text: dmy(d.date) })),
          h("span", { class: "num", text: docSummary(d) }))));
  }

  // ══ صور الأطقم: مخزنٌ وحده، ومصغّرةٌ تُحمَّل عند الحاجة ══
  const photoCache = new Map();
  async function photoData(id) {
    if (!id) return null;
    if (photoCache.has(id)) return photoCache.get(id);
    const d = await S.getPhoto(id);
    if (d) {
      photoCache.set(id, d);
      if (photoCache.size > 60) photoCache.delete(photoCache.keys().next().value);
    }
    return d;
  }
  function photoThumb(id, cls) {
    if (!id) return null;
    const img = h("img", { class: "thumb" + (cls ? " " + cls : ""), alt: "صورة الطقم" });
    photoData(id).then((d) => { if (d) img.src = d; else img.remove(); });
    img.addEventListener("click", (e) => { e.stopPropagation(); showPhoto(id); });
    return img;
  }
  async function showPhoto(id) {
    const d = await photoData(id);
    if (d) await sheet((box) => box.append(h("img", { src: d, class: "photo-full", alt: "صورة الطقم" })));
  }
  // من الكاميرا أو المعرض ← صورةٌ مصغّرة (أطول ضلعٍ 640) بصيغة JPEG
  function shrinkImage(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const img = new Image();
        img.onload = () => {
          const sc = Math.min(1, 640 / Math.max(img.width, img.height));
          const c = document.createElement("canvas");
          c.width = Math.max(1, Math.round(img.width * sc));
          c.height = Math.max(1, Math.round(img.height * sc));
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          resolve(c.toDataURL("image/jpeg", 0.78));
        };
        img.onerror = () => reject(new Error("تعذّر فتح الصورة"));
        img.src = fr.result;
      };
      fr.onerror = () => reject(new Error("تعذّر قراءة الصورة"));
      fr.readAsDataURL(file);
    });
  }
  async function savePhotoData(dataUrl) {
    const id = D.uid("ph_");
    await S.putPhoto(id, dataUrl);
    photoCache.set(id, dataUrl);
    if (B.native && B.backupFolder()) B.savePhoto(id, dataUrl.split(",")[1] || "");
    return id;
  }
  // مزامنة صور المجلد: ما ليس فيه يُكتب (بعد اختيار المجلد أو الاسترجاع)
  async function syncAllPhotos() {
    if (!B.native || !B.backupFolder()) return;
    B.syncPhotos(JSON.stringify(await S.photoIds()));
  }
  async function importPhotos(map) {
    let n = 0;
    for (const [id, data] of Object.entries(map || {})) { await S.putPhoto(id, data); n++; }
    return n;
  }

  // ══ الرئيسية: ستّ لوحاتٍ للعمليات، ثم كشف الحساب، ثم عمليات اليوم ══
  function home() {
    const s = st();
    setBar(s.settings.name || APP_NAME, "حساباتي مع العملاء والمصانع", { back: false,
      actions: [updateButton()], logo: true });
    setTab("home");
    const v = view();
    const t = D.today();
    const us = B.updateState();
    if (us.available) {
      v.append(h("div", { class: "note-bar info tap", style: { marginBottom: "12px" }, onclick: updateSheet },
        ico("sparkles", 18), ` تحديث ${us.published ? us.published.version : ""} متاح — اضغط للتثبيت (بياناتك تبقى كما هي)`));
    }
    const hasData = s.invoices.length + s.vouchers.length > 0;
    const last = s.settings.lastBackup;
    if (B.native) {
      if (!B.backupFolder()) {
        v.append(h("div", { class: "note-bar warn tap", style: { marginBottom: "12px" }, onclick: () => go("settings") },
          ico("folder", 18), " فعّل الحفظ التلقائي في مجلدٍ على الجوال — فتبقى بياناتك ولو حُذف التطبيق."));
      }
    } else if (hasData && (!last || D.daysBetween(last.slice(0, 10), t) >= 7)) {
      v.append(h("div", { class: "note-bar warn tap", style: { marginBottom: "12px" }, onclick: () => go("settings") },
        last ? `آخر نسخة احتياطية قبل ${D.daysBetween(last.slice(0, 10), t)} يوماً — احفظ نسخةً جديدة.`
          : "لم تُحفظ نسخة احتياطية بعد — اضغط هنا لحفظ نسخة."));
    }
    // اللوحات: العميل يميناً والمصنع يساراً، صفّاً صفّاً
    const tile = (icon, label, hint, to, fac) => h("button", { class: "op-tile" + (fac ? " fac" : ""), onclick: () => go(to) },
      h("span", { class: "op-ic" }, ico(icon, 26)), h("span", { class: "op-t" }, label), h("span", { class: "op-h" }, hint));
    v.append(h("div", { class: "op-grid" },
      tile("receipt", "بيع للعميل", "ذهب · أجور · ماس", "invoice/new?kind=sale"),
      tile("return", "مرتجع للعميل", "يرجع إلى يدك", "invoice/new?kind=sale_return"),
      tile("package", "بضاعة من مصنع", "تدخل يدك", "invoice/new?kind=purchase", true),
      tile("return", "إرجاع للمصنع", "يخرج من يدك", "invoice/new?kind=purchase_return", true),
      tile("in", "تحصيل من العميل", "ذهب ونقد", "voucher/new?kind=receipt"),
      tile("out", "سداد للمصنع", "من صناديقك", "voucher/new?kind=payment", true)));
    // كشف حساب
    v.append(h("button", { class: "wide-tile", onclick: pickPartyThen(null, (id) => go(`statement/${id}`)) },
      h("span", { class: "op-ic" }, ico("book", 24)),
      h("span", { class: "grow" }, h("span", { class: "op-t" }, "كشف حساب"), h("span", { class: "op-h" }, "عميل أو مصنع — بالذهب أو بالألماس، ويُرسَل صورة")),
      ico("chevron", 20, "muted")));
    // عمليات اليوم
    const todays = [...s.invoices, ...s.vouchers].filter((d) => d.date === t);
    let tw = 0, tg = 0;
    for (const d of todays) {
      if (d.kind === "sale" || d.kind === "sale_return") {
        const sg = d.kind === "sale" ? 1 : -1;
        tw += sg * d.totalW18; tg += sg * d.grand;
      }
    }
    v.append(h("button", { class: "wide-tile today", onclick: () => go("today") },
      h("span", { class: "op-ic" }, ico("clock", 24)),
      h("span", { class: "grow" }, h("span", { class: "op-t" }, `عمليات اليوم (${todays.length})`),
        h("span", { class: "op-h" }, todays.length ? `مبيعات ${gw(tw)} جم · أجور ${f2(tg)} — اضغط لعرضها ومعاينتها`
          : "لا عمليات اليوم بعد — اضغط لعرض آخر العمليات")),
      ico("chevron", 20, "muted")));
  }

  // ══ عمليات اليوم: كلّ عمليةٍ بزرّ «معاينة» يُظهر مستندها ══
  function todayScreen() {
    const s = st(), t = D.today();
    setBar("عمليات اليوم", dmy(t));
    setTab("home");
    const v = view();
    const all = [...s.invoices, ...s.vouchers]
      .sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : (a.createdAt < b.createdAt ? 1 : -1)));
    const todays = all.filter((d) => d.date === t);
    const item = (d) => {
      const el = docItem(d);
      el.classList.add("op-row");
      el.append(h("button", { class: "btn sm prev-btn", onclick: (e) => { e.stopPropagation(); previewSheet(d); } },
        ico("file", 16), "معاينة"));
      return el;
    };
    if (todays.length) todays.forEach((d) => v.append(item(d)));
    else v.append(h("div", { class: "empty" }, "لا عمليات اليوم بعد"));
    const older = all.filter((d) => d.date !== t).slice(0, 20);
    if (older.length) {
      v.append(h("div", { class: "sec-title spread", style: { marginTop: "14px" } }, h("span", null, "آخر العمليات"),
        h("button", { class: "link", onclick: () => go("log") }, "السجل كاملاً")));
      older.forEach((d) => v.append(item(d)));
    }
  }

  // معاينة المستند في نافذةٍ سفلية: مشاركة صورة · طباعة · فتحه
  async function previewSheet(d) {
    const s = st();
    const isInv = isInvKind(d.kind);
    let html = isInv ? P.invoiceHtml(s, d, {}) : P.voucherHtml(s, d);
    const frame = previewFrame(html);
    const ids = isInv ? d.lines.map((l) => l.photo).filter(Boolean) : [];
    if (ids.length) S.getPhotos(ids).then((ph) => { if (Object.keys(ph).length) { html = P.invoiceHtml(s, d, ph); frame.setHtml(html); } });
    const r = await sheet((box, close) => {
      box.append(h("h3", null, `${D.KIND_LABEL[d.kind]} ${d.no} — ${shopTitle(d.shopId)}`), frame,
        h("div", { class: "actions" },
          h("button", { class: "btn", onclick: () => B.shareHtmlImage(html, d.no) }, ico("share", 18), "مشاركة صورة"),
          h("button", { class: "btn ghost", onclick: () => B.printHtml(html, d.no) }, ico("printer", 18), "طباعة"),
          h("button", { class: "btn ghost", onclick: () => close("open") }, "فتح")));
    });
    if (r === "open") go(`doc/${isInv ? "inv" : "vo"}/${d.id}`);
  }

  // أيقونة خطّية من مجموعة التطبيق (icons.js) — أو النصّ كما هو
  function ico(name, size, cls) {
    return root.ICON_NAMES && root.ICON_NAMES.includes(name) ? root.Icon(name, size, cls)
      : h("span", { class: "ic" }, name);
  }
  function quickBtn(icon, label, fn) {
    return h("button", { onclick: fn }, h("span", { class: "i" }, ico(icon, 24)), h("span", null, label));
  }

  // ══ الحسابات: المحلات والمصانع ══
  // `type`: «shop» أو «factory» — أو null لكل الحسابات
  function partyItems(type) {
    const s = st();
    const bals = D.allBalances(s);
    return s.shops.filter((x) => !type || (type === "factory") === D.isFactory(x))
      .sort((a, b) => (D.isFactory(a) - D.isFactory(b)) || a.name.localeCompare(b.name, "ar"))
      .map((x) => {
        const fac = D.isFactory(x);
        return { id: x.id, title: x.name,
          sub: (type ? "" : fac ? "مصنع · " : "محل · ") +
            `ذهب ${balText(G.g(bals[x.id].gold18, vk()), "جم", fac)} · نقد ${balText(bals[x.id].cash, "ريال", fac)}` };
      });
  }
  function pickPartyThen(type, fn) {
    return async () => {
      const fac = type === "factory";
      const it = await pickSheet(type ? `اختر ${fac ? "المصنع" : "المحل"}` : "اختر الحساب", partyItems(type),
        { addLabel: type ? (fac ? "+ مصنع جديد" : "+ محل جديد") : null, empty: "لا حسابات بعد" });
      if (!it) return;
      if (it.add) { go(fac ? "shop-form?type=factory" : "shop-form"); return; }
      fn(it.id);
    };
  }

  function customers(q) {
    const s = st();
    const mode = q.view === "board" ? "board" : q.view === "factories" ? "factories" : "shops";
    const fac = mode === "factories";
    setBar("الحسابات", `${D.shopsOnly(s).length} محل · ${D.factoriesOnly(s).length} مصنع`, { back: false,
      actions: mode === "board" ? [] : [h("button", { class: "icon-btn", "aria-label": fac ? "مصنع جديد" : "محل جديد",
        onclick: () => go(fac ? "shop-form?type=factory" : "shop-form") }, ico("plus", 20), h("span", null, fac ? "مصنع" : "محل"))] });
    setTab("customers");
    const v = view();
    v.append(h("div", { class: "seg", style: { marginBottom: "10px" } },
      h("button", { class: mode === "shops" ? "on" : "", onclick: () => replace("customers") }, "المحلات"),
      h("button", { class: fac ? "on" : "", onclick: () => replace("customers?view=factories") }, "المصانع"),
      h("button", { class: mode === "board" ? "on" : "", onclick: () => replace("customers?view=board") }, "المبيعات والتحصيل")));
    if (mode === "board") return boardView(v, q);
    partyList(v, fac);
  }

  function partyList(v, fac) {
    const q = h("input", { class: "in", type: "search", placeholder: fac ? "ابحث باسم المصنع أو الجوال…" : "ابحث باسم المحل أو الجوال…" });
    const sortSeg = h("div", { class: "chips", style: { margin: "8px 0" } });
    let sort = "name";
    const list = h("div");
    const render = () => {
      const s = st();
      const bals = D.allBalances(s);
      const t = q.value.trim();
      const all = fac ? D.factoriesOnly(s) : D.shopsOnly(s);
      const arr = all.filter((x) => !t || x.name.includes(t) || (x.phone || "").includes(t));
      // «الأكثر»: للمحل أكبر ما عليه، وللمصنع أكبر ما عليّ له (السالب)
      const sg = fac ? -1 : 1;
      if (sort === "name") arr.sort((a, b) => a.name.localeCompare(b.name, "ar"));
      if (sort === "gold") arr.sort((a, b) => sg * (bals[b.id].gold18 - bals[a.id].gold18));
      if (sort === "cash") arr.sort((a, b) => sg * (bals[b.id].cash - bals[a.id].cash));
      list.innerHTML = "";
      if (!arr.length) {
        list.append(h("div", { class: "empty" }, all.length ? "لا نتائج" : fac
          ? "لا مصانع بعد — اضغط «+ مصنع» لإضافة المصنع الذي تأخذ منه البضاعة وتدفع له."
          : "لا محلات بعد — اضغط «+ محل» لإضافة أول محل."));
      }
      for (const x of arr) {
        list.append(h("div", { class: "list-item", onclick: () => go(`shop/${x.id}`) },
          h("span", { class: "avatar" + (fac ? " fac" : "") }, fac ? ico("package", 20) : (x.name.trim()[0] || "؟")),
          h("div", { class: "grow" }, h("div", { class: "t", text: x.name }),
            x.phone ? h("div", { class: "muted small", dir: "ltr", style: { textAlign: "right" }, text: x.phone }) : null),
          h("div", { style: { textAlign: "left" }, class: "small num" },
            h("div", null, goldBal(bals[x.id].gold18, fac)), h("div", null, cashBal(bals[x.id].cash, fac)))));
      }
    };
    const chips = fac ? [["name", "بالاسم"], ["gold", "الأكثر ذهباً عليّ"], ["cash", "الأكثر نقداً عليّ"]]
      : [["name", "بالاسم"], ["gold", "الأكثر ذهباً عليه"], ["cash", "الأكثر نقداً عليه"]];
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
    if (!shop) { replace("customers"); return; }
    const fac = D.isFactory(shop);
    setBar(shop.name, (fac ? "مصنع" : "محل") + (shop.phone ? " · " + shop.phone : ""), {
      actions: [h("button", { class: "icon-btn", "aria-label": "تعديل", onclick: () => go(`shop-form/${id}`) }, ico("edit", 20))] });
    setTab("customers");
    const b = D.balance(s, id);
    const v = view();
    v.append(h("div", { class: "kpis" },
      h("div", { class: "kpi" }, h("b", null, `رصيد الذهب (عيار ${vk()})`), h("div", { class: "v num" }, goldBal(b.gold18, fac))),
      h("div", { class: "kpi" }, h("b", null, fac ? "رصيد النقد والأجور" : "رصيد الأجور والنقد"), h("div", { class: "v num" }, cashBal(b.cash, fac)))));
    if (shop.agreedWage18) {
      v.append(h("div", { class: "note-bar info", style: { marginBottom: "12px" } },
        `${fac ? "أجرة المصنع المتفق عليها" : "الأجرة المتفق عليها"}: ${f2(G.rate(shop.agreedWage18, vk()))} ريال لكل جرام عيار ${vk()}`));
    }
    const contact = shop.phone ? quickBtn("phone", "اتصال", () => B.dial(shop.phone))
      : quickBtn("edit", fac ? "تعديل المصنع" : "تعديل المحل", () => go(`shop-form/${id}`));
    v.append(h("div", { class: "quick" }, ...(fac ? [
      quickBtn("out", "سداد للمصنع", () => go(`voucher/new?kind=payment&shop=${id}`)),
      quickBtn("package", "بضاعة من المصنع", () => go(`invoice/new?kind=purchase&shop=${id}`)),
      quickBtn("return", "إرجاع للمصنع", () => go(`invoice/new?kind=purchase_return&shop=${id}`)),
      quickBtn("book", "كشف الحساب", () => go(`statement/${id}`)), contact,
    ] : [
      quickBtn("receipt", "فاتورة بيع", () => go(`invoice/new?kind=sale&shop=${id}`)),
      quickBtn("return", "مرتجع", () => go(`invoice/new?kind=sale_return&shop=${id}`)),
      quickBtn("in", "تحصيل", () => go(`voucher/new?kind=receipt&shop=${id}`)),
      quickBtn("book", "كشف الحساب", () => go(`statement/${id}`)), contact,
    ])));
    if (shop.notes) v.append(h("div", { class: "card small" }, shop.notes));
    const docs = D.docsOf(s, id).reverse();
    v.append(h("div", { class: "sec-title" }, `العمليات (${docs.length})`));
    if (!docs.length) v.append(h("div", { class: "empty" }, fac ? "لا عمليات مع هذا المصنع بعد" : "لا عمليات لهذا المحل بعد"));
    docs.slice(0, 60).forEach((d) => v.append(docItem(d)));
  }

  function shopForm(id, q) {
    const s = st();
    const shop = id ? D.shopById(s, id) : null;
    const fac = shop ? D.isFactory(shop) : (q && q.type === "factory");
    const word = fac ? "المصنع" : "المحل";
    setBar(shop ? `تعديل ${word}` : fac ? "مصنع جديد" : "محل جديد", "", { noTabs: true });
    const k = vk();
    const name = h("input", { class: "in", value: shop ? shop.name : "", placeholder: `اسم ${word}`, enterkeyhint: "next" });
    const phone = h("input", { class: "in", value: shop ? shop.phone : "", inputmode: "tel", dir: "ltr", placeholder: "05xxxxxxxx" });
    const notes = h("textarea", { class: "in", rows: 2, placeholder: "ملاحظات (اختياري)" });
    notes.value = shop ? shop.notes : "";
    const wage = numInput({ value: shop && shop.agreedWage18 ? G.rate(shop.agreedWage18, k) : 0 });
    const og = shop ? shop.openGold18 : 0, oc = shop ? shop.openCash : 0;
    const goldIn = numInput({ value: Math.abs(G.g(og, k)) });
    const cashIn = numInput({ value: Math.abs(oc) });
    // الاتجاه: للمحل «عليه» موجب و«له» سالب — وللمصنع «عليّ» سالب و«لي» موجب
    const segOf = (val) => {
      let on = fac ? (val > 0 ? "for" : "on") : (val < 0 ? "for" : "on");
      const seg = h("div", { class: "seg" });
      const mk = (key, label) => h("button", { type: "button", class: key === on ? "on" : "", onclick: (e) => {
        on = key;
        for (const c of seg.children) c.classList.remove("on");
        e.target.classList.add("on");
      } }, label);
      seg.append(mk("on", fac ? "عليّ له" : "عليه"), mk("for", fac ? "لي عنده" : "له"));
      seg.sign = () => (fac ? (on === "on" ? -1 : 1) : (on === "on" ? 1 : -1));
      return seg;
    };
    const gSeg = segOf(og), cSeg = segOf(oc);
    const date = h("input", { class: "in", type: "date", value: shop ? shop.openDate : D.today() });
    const v = view();
    v.append(
      h("div", { class: "card" }, h("h2", null, fac ? "بيانات المصنع" : "بيانات المحل"),
        field(`اسم ${word}`, name), h("div", { style: { height: "8px" } }),
        field("الجوال", phone), h("div", { style: { height: "8px" } }),
        field(fac ? `أجرة المصنع المتفق عليها (ريال لكل جرام عيار ${k}) — تُملأ تلقائياً في البضاعة`
          : `الأجرة المتفق عليها (ريال لكل جرام عيار ${k}) — تُملأ تلقائياً في الفواتير`, wage),
        h("div", { style: { height: "8px" } }), field("ملاحظات", notes)),
      h("div", { class: "card" }, h("h2", null, fac ? "دَينٌ سابق (اختياري)" : "رصيد افتتاحي (اختياري)"),
        h("div", { class: "muted small", style: { marginBottom: "8px" } },
          fac ? "ما كان عليك للمصنع قبل أول عملية في التطبيق." : "ما كان بينك وبين المحل قبل أول فاتورة في التطبيق."),
        h("div", { class: "grid2" }, field(`ذهب (جم عيار ${k})`, goldIn), field("الاتجاه", gSeg),
          field("نقد (ريال)", cashIn), field("الاتجاه", cSeg), field("بتاريخ", date, "span2"))));
    const save = async () => {
      try {
        const gv = goldIn.getVal(), cv = cashIn.getVal(), wv = wage.getVal();
        if ([gv, cv, wv].some((x) => !isFinite(x))) throw new Error("رقمٌ غير صحيح في أحد الحقول");
        const rec = D.saveShop(s, {
          id: shop ? shop.id : null, createdAt: shop ? shop.createdAt : null, type: fac ? "factory" : "shop",
          name: name.value, phone: phone.value, notes: notes.value,
          agreedWage18: wv ? G.rateStore(wv, k) : 0,
          openGold18: gSeg.sign() * G.store(gv, k),
          openCash: cSeg.sign() * cv, openDate: date.value || D.today(),
        });
        if (await persist([["shops", "put", rec]])) {
          toast(fac ? "حُفظ المصنع" : "حُفظ المحل");
          if (shop) history.back(); else replace(`shop/${rec.id}`);
        }
      } catch (e) { err(e); }
    };
    const del = async () => {
      try {
        if (!(await confirmSheet(`حذف ${word} «${shop.name}»؟`, "حذف", true))) return;
        D.deleteShop(s, shop.id);
        if (await persist([["shops", "del", shop.id]])) { toast(`حُذف ${word}`); replace(fac ? "customers?view=factories" : "customers"); }
      } catch (e) { err(e); }
    };
    v.append(h("div", { class: "footer-bar" },
      h("button", { class: "btn", onclick: save }, "حفظ"),
      shop ? h("button", { class: "btn ghost", onclick: del }, "حذف") : null));
  }

  // ══ الفاتورة: بيع · مرتجع (العميل) — بضاعة من مصنع · إرجاع للمصنع ══
  const INV_TITLE = { sale: "فاتورة بيع", sale_return: "مرتجع", purchase: "بضاعة من مصنع", purchase_return: "إرجاع للمصنع" };

  // رأس المستند: نوعه، والحساب (يُبدَّل بلمسة)، والتاريخ — مكان خاناتٍ في الصفحة
  function docHeader(title, partyName, partyPh, date, onParty, onDate) {
    const dIn = h("input", { type: "date", class: "date-hidden", value: date, tabindex: "-1",
      onchange: (e) => onDate(e.target.value || D.today()) });
    const openDate = () => {
      try { if (dIn.showPicker) { dIn.showPicker(); return; } } catch (e) { /* */ }
      dIn.focus(); dIn.click();
    };
    const sub = h("span", { class: "sub bar-chips" },
      h("button", { type: "button", class: "chip-btn party" + (partyName ? "" : " empty"), onclick: onParty },
        h("span", { class: "t" }, partyName || partyPh), h("span", { class: "car" }, "▾")),
      h("button", { type: "button", class: "chip-btn date", onclick: openDate },
        ico("calendar", 14), h("span", { dir: "ltr", text: dmy(date) })), dIn);
    setBar(title, sub, { noTabs: true });
  }

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
      const kind = INV_TITLE[q.kind] ? q.kind : "sale";
      inv = { id: null, kind, shopId: q.shop || "", date: D.today(), vat: false, desc: "", lines: [] };
      try {
        const dr = JSON.parse(localStorage.getItem(draftKey(inv.kind)) || "null");
        if (dr && dr.lines && dr.lines.length && (!q.shop || dr.shopId === q.shop) && !q.piece) {
          Object.assign(inv, dr, { id: null });
          setTimeout(() => toast("استُعيدت فاتورةٌ لم تُرحَّل — أكملها أو احذف أسطرها"), 300);
        }
      } catch (e) { /* لا مسودة */ }
    }
    const editing = mode === "edit";
    const forFactory = () => D.FACTORY_KINDS.includes(inv.kind);
    const isOut = () => D.OUT_KINDS.includes(inv.kind);
    const partyWord = () => (forFactory() ? "المصنع" : "العميل");
    const party = () => D.shopById(s, inv.shopId);
    const ent = { karat: vk(), stoneRate: s.settings.stoneRate, regManual: false, fromCard: false, shadow: null,
      editIdx: null, lastWo: "", src: "", lid: null, smallV: 0, afterV: 0, exact18: null, photo: "" };

    // ── الرأس: النوع · الحساب · التاريخ ──
    const header = () => {
      const sh = party();
      docHeader(INV_TITLE[inv.kind] + (editing ? ` ${inv.no}` : ""), sh ? sh.name : "", `اختر ${partyWord()}`,
        inv.date, pickParty, (d) => { inv.date = d; header(); refresh(); });
    };
    async function pickParty() {
      const fac = forFactory();
      const it = await pickSheet(`اختر ${partyWord()}`, partyItems(fac ? "factory" : "shop"),
        { addLabel: fac ? "+ مصنع جديد" : "+ عميل جديد", empty: fac ? "لا مصانع بعد" : "لا عملاء بعد" });
      if (!it) return;
      if (it.add) { saveDraft(); go(fac ? "shop-form?type=factory" : "shop-form"); return; }
      inv.shopId = it.id;
      header();
      ent.lastWo = "";
      woIn.dispatchEvent(new Event("change"));
      refresh();
      setTimeout(() => woIn.focus(), 60);
    }
    const v = view();

    // ── الطقم: الاسم اختياري؛ ويُرحَّل ذهبٌ أو ماسٌ أو أجورٌ وحدها ──
    const woIn = h("input", { class: "in", placeholder: "اختياري", autocomplete: "off", dir: "auto",
      enterkeyhint: "next", inputmode: "text" });
    const gold = numInput(), big = numInput(), dia = numInput(), stand = numInput();
    const reg = numInput({ hl: true });
    const wagesIn = numInput({ enter: "done" });
    const karatSel = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: `عيار ${x}` })));
    karatSel.value = String(ent.karat);
    const notice = h("div");
    const addBtn = h("button", { type: "button", class: "btn grow" }, "+ إضافة");
    const cancelEdit = h("button", { type: "button", class: "btn ghost", style: { display: "none" } }, "إلغاء التعديل");
    const pickBtn = h("button", { type: "button", class: "btn ghost block sm", style: { marginBottom: "10px" } });
    // صورة الطقم: من الكاميرا أو المعرض — تُحفظ وحدها ويُربط بها السطر
    const photoBox = h("div", { class: "photo-pick" });
    const photoIn = h("input", { type: "file", accept: "image/*", style: { display: "none" } });
    function renderPhoto() {
      photoBox.innerHTML = "";
      if (ent.photo) {
        photoBox.append(photoThumb(ent.photo, "lg"),
          h("div", { class: "photo-acts" },
            h("button", { type: "button", class: "link", onclick: () => photoIn.click() }, "تغيير"),
            h("button", { type: "button", class: "link", onclick: () => { ent.photo = ""; renderPhoto(); } }, "إزالة")));
      } else {
        photoBox.append(h("button", { type: "button", class: "btn ghost block photo-btn", onclick: () => photoIn.click() },
          ico("image", 20), "صورة"));
      }
    }
    photoIn.addEventListener("change", async () => {
      const f = photoIn.files && photoIn.files[0];
      photoIn.value = "";
      if (!f) return;
      try { ent.photo = await savePhotoData(await shrinkImage(f)); renderPhoto(); } catch (e) { err(e); }
    });
    // للتجربة الآلية على الجهاز: صورةٌ جاهزة تُربط بالسطر كما لو اختيرت
    App.attachPhotoData = async (dataUrl) => { ent.photo = await savePhotoData(dataUrl); renderPhoto(); return ent.photo; };

    // الأجور المتفق عليها (بالجرام) تُقترح مبلغاً للوزن المكتوب — والمكتوب يُعتمد
    const agreedWages = () => {
      const sh = party(), r = reg.getVal() || 0;
      return sh && sh.agreedWage18 && r > 0 ? G.totalWages(sh.agreedWage18, G.store(r, ent.karat)) : null;
    };
    const hintWages = () => {
      const a = agreedWages();
      wagesIn.placeholder = a === null ? "" : `تلقائي ${f2(a)}`;
    };
    const W = { gold, big, standing: stand, reg };
    const snap = () => {
      ent.shadow = { small: G.store(ent.smallV || 0, ent.karat), after: G.store(ent.afterV || 0, ent.karat) };
      for (const [key, el] of Object.entries(W)) ent.shadow[key] = G.store(el.getVal() || 0, ent.karat);
    };
    const derive = () => {
      const gv = gold.getVal() || 0, bv = big.getVal() || 0;
      const d = G.entryDerive(gv, ent.smallV || 0, bv, ent.stoneRate, ent.regManual, reg.getVal() || 0);
      ent.afterV = d.after; stand.setVal(d.standing);
      if (!ent.regManual) reg.setVal(d.reg);
      hintWages(); snap();
    };
    for (const el of [gold, big]) el.addEventListener("input", derive);
    reg.addEventListener("input", () => { ent.regManual = true; hintWages(); snap(); });
    stand.addEventListener("input", snap);
    karatSel.addEventListener("change", () => {
      const nk = parseInt(karatSel.value, 10);
      if (ent.fromCard && ent.shadow) {
        for (const [key, el] of Object.entries(W)) el.setVal(G.g(ent.shadow[key], nk));
        ent.smallV = G.g(ent.shadow.small, nk); ent.afterV = G.g(ent.shadow.after, nk);
      } else snap();
      ent.karat = nk;
      hintWages();
    });

    // تفصيل الوزن (الذهب · أحجار/فصوص · القائم) — مطويٌّ ما لم يُفتح
    let details = false;
    try { details = localStorage.getItem("lineDetails") === "1"; } catch (e) { /* */ }
    const detailsBox = h("div", { class: "grid2", style: { marginTop: "8px" } },
      field("الذهب", gold), field("أحجار/فصوص", big), field("الوزن القائم", stand, "span2"));
    const detailsBtn = h("button", { type: "button", class: "link" });
    const renderDetails = () => {
      detailsBox.style.display = details ? "" : "none";
      detailsBtn.textContent = details ? "إخفاء تفصيل الوزن" : "تفصيل الوزن (ذهب · أحجار/فصوص) — اختياري";
    };
    detailsBtn.addEventListener("click", () => {
      details = !details;
      try { localStorage.setItem("lineDetails", details ? "1" : "0"); } catch (e) { /* */ }
      renderDetails();
    });

    function setNotice(kind, text) {
      notice.innerHTML = "";
      if (text) notice.append(h("div", { class: "note-bar " + kind }, text));
    }

    function fillFrom(li) {
      const e = D.lineToEntry(li, ent.karat);
      gold.setVal(e.gold); big.setVal(e.big); stand.setVal(e.standing); reg.setVal(e.reg); dia.setVal(e.diamond);
      ent.smallV = e.small || 0; ent.afterV = e.after || 0;
      ent.stoneRate = e.stoneRate === undefined ? s.settings.stoneRate : e.stoneRate;
      ent.regManual = false; ent.fromCard = true; ent.exact18 = e.exact18;
      ent.photo = e.photo || "";
      renderPhoto();
      snap();
      hintWages();
    }
    // أجور حركةٍ سابقة (من الجهة نفسها) تُقترح كما هي
    const offerWages = (li) => { if (wagesIn.isBlank() && li && li.wages > 0) wagesIn.setVal(li.wages); };

    // الطقوم التي في يدي — للبيع، وما جاء من مصنعٍ للإرجاع إليه
    function availablePieces() {
      if (!isOut()) return [];
      const used = new Set(inv.lines.map((l) => l.src).filter(Boolean));
      const names = new Set(inv.lines.map((l) => (l.wo || "").trim()).filter(Boolean));
      return D.holdings(s).pieces.filter((p) => !used.has(p.id) && !(p.name && names.has(p.name)) &&
        (inv.kind === "sale" || (p.fromKind === "purchase" && (!inv.shopId || p.party && p.party.id === inv.shopId))));
    }
    function renderPickBtn() {
      const n = ent.editIdx === null ? availablePieces().length : 0;
      pickBtn.style.display = n ? "" : "none";
      pickBtn.innerHTML = "";
      pickBtn.append(ico("package", 18), `اختر من الطقوم التي معي (${n})`);
    }
    function pieceLabel(p) {
      return `${p.fromKind === "purchase" ? "من مصنع" : "مرتجع من"} «${p.party ? p.party.name : "—"}» · ${dmy(p.date)}`;
    }
    function usePiece(p) {
      if (!p) return;
      clearEntry();
      ent.karat = p.karat;
      karatSel.value = String(p.karat);
      woIn.value = p.name; ent.lastWo = p.name;
      fillFrom(p.line);
      ent.src = p.id;
      // الأجور من الجهة نفسها: بيع مرتجعٍ بأجور بيعه، وإرجاعٌ للمصنع بأجور المصنع
      if ((inv.kind === "sale" && p.fromKind === "sale_return") || (inv.kind === "purchase_return" && p.fromKind === "purchase")) {
        offerWages(p.line);
      }
      if (inv.kind === "purchase_return" && !inv.shopId && p.party) { inv.shopId = p.party.id; header(); refresh(); }
      setNotice("info", `${p.name ? "الطقم " + p.name : "طقمٌ بلا اسم"} — ${gw(p.w18, p.karat)} جم عيار ${p.karat} · ${pieceLabel(p)}`);
      setTimeout(() => (wagesIn.isBlank() ? wagesIn : reg).focus(), 50);
    }
    pickBtn.addEventListener("click", async () => {
      const pcs = availablePieces();
      const it = await pickSheet("الطقوم التي معي", pcs.map((p) => ({ id: p.id,
        title: `${p.name || "طقمٌ بلا اسم"} · ${gw(p.w18, p.karat)} جم عيار ${p.karat}`, sub: pieceLabel(p),
        badge: photoThumb(p.line.photo, "sm") })),
        { empty: "لا طقم معك" });
      if (it) usePiece(pcs.find((p) => p.id === it.id));
    });

    // اسم الطقم: آخر حركةٍ له تقول أين هو، ومنها يُعبّأ وزنه
    woIn.addEventListener("change", () => {
      const no = woIn.value.trim();
      if (!no) { if (!ent.src) setNotice(); ent.lastWo = ""; return; }
      if (no === ent.lastWo) return;
      ent.lastWo = no; ent.src = "";
      const last = D.woLast(s, no, inv.id);
      if (!last) {
        setNotice("info", `طقمٌ جديد باسم ${no}.`);
        ent.fromCard = false;
        return;
      }
      fillFrom(last.line);
      if (D.FACTORY_KINDS.includes(last.kind) === forFactory()) offerWages(last.line);
      const lastIn = D.IN_KINDS.includes(last.kind);
      const who = last.shop ? last.shop.name : "—";
      const what = `${D.KIND_LABEL[last.kind]} ${last.inv.no}`;
      const at = `بتاريخ ${dmy(last.date)}`;
      if (isOut()) {
        if (lastIn) setNotice("info", `الطقم ${no} معك — ${what} من «${who}» ${at}. عُبّئ وزنه.`);
        else setNotice("warn", `⚠ الطقم ${no} خرج من يدك: ${what} لـ«${who}» ${at}.`);
      } else if (!lastIn) {
        const days = D.daysBetween(last.date, inv.date || D.today());
        let txt = `الطقم ${no}: ${what} لـ«${who}» ${at}` + (days > 0 ? ` — منذ ${days} يوماً.` : ".") + " عُبّئ وزنه.";
        const other = inv.kind === "sale_return" && inv.shopId && last.shop && last.shop.id !== inv.shopId;
        if (other) txt += `\n⚠ بِيع لـ«${who}» لا للعميل المختار.`;
        setNotice(other ? "warn" : "info", txt);
      } else {
        setNotice("warn", `⚠ الطقم ${no} معك أصلاً — ${what} من «${who}» ${at}.`);
      }
    });

    function clearEntry() {
      woIn.value = "";
      for (const el of [gold, big, dia, reg, stand, wagesIn]) el.setVal(0);
      ent.regManual = false; ent.fromCard = false; ent.shadow = null;
      ent.stoneRate = s.settings.stoneRate; ent.editIdx = null; ent.lastWo = "";
      ent.exact18 = null; ent.src = ""; ent.lid = null; ent.smallV = 0; ent.afterV = 0;
      ent.photo = ""; renderPhoto();
      addBtn.textContent = "+ إضافة"; cancelEdit.style.display = "none";
      setNotice(); hintWages(); renderPickBtn();
    }

    async function addLine() {
      try {
        const no = woIn.value.trim();
        const vals = { gold: gold.getVal(), big: big.getVal(), diamond: dia.getVal(), reg: reg.getVal(),
          standing: stand.getVal(), wages: wagesIn.getVal() };
        for (const [key, x] of Object.entries(vals)) {
          if (!isFinite(x)) throw new Error("رقمٌ غير صحيح في خانة " + ({ gold: "الذهب", big: "أحجار/فصوص",
            diamond: "الماس", reg: "الوزن", standing: "الوزن القائم", wages: "الأجور" })[key]);
        }
        const regV = vals.reg > 0 ? vals.reg : 0, diaV = vals.diamond > 0 ? vals.diamond : 0;
        let wagesV = wagesIn.isBlank() ? agreedWages() : Math.max(0, vals.wages);
        if (wagesV === null) wagesV = 0;
        if (!(regV > 0) && !(diaV > 0) && !(wagesV > 0)) {
          reg.focus();
          throw new Error("اكتب الوزن، أو الأجور، أو الماس — ويكفي واحدٌ منها");
        }
        if (no && (regV > 0 || diaV > 0)) {
          const dupAt = inv.lines.findIndex((l, i) => !l.wageOnly && (l.wo || "").trim() === no && i !== ent.editIdx);
          if (dupAt >= 0) throw new Error(`الطقم ${no} مضافٌ مسبقاً في هذه الفاتورة`);
        }
        const last = no && !ent.src && (regV > 0 || diaV > 0) ? D.woLast(s, no, inv.id) : null;
        if (ent.editIdx === null && last) {
          const lastIn = D.IN_KINDS.includes(last.kind);
          if (isOut() && !lastIn) {
            const ok = await confirmSheet(`الطقم ${no} خرج من يدك: ${D.KIND_LABEL[last.kind]} ${last.inv.no} لـ«${last.shop ? last.shop.name : "—"}»` +
              ` بتاريخ ${dmy(last.date)}.\n\nإضافته مرةً أخرى؟`, "نعم، أضفه");
            if (!ok) return;
          }
          if (!isOut() && lastIn) {
            const ok = await confirmSheet(`الطقم ${no} معك أصلاً (${D.KIND_LABEL[last.kind]} ${last.inv.no}).\n\nإضافته مرةً أخرى؟`, "نعم، أضفه");
            if (!ok) return;
          }
        }
        const li = D.buildLine({ wo: no, karat: ent.karat,
          gold: vals.gold, small: ent.smallV, big: vals.big, after: ent.afterV,
          standing: vals.standing || regV, reg: regV, diamond: diaV,
          stoneRate: ent.stoneRate, wages: wagesV, exact18: ent.fromCard ? ent.exact18 : null,
          src: ent.src, lid: ent.lid, photo: ent.photo });
        pushLine(li);
        clearEntry();
        (no ? woIn : reg).focus();
      } catch (e) { err(e); }
    }
    function pushLine(li) {
      if (ent.editIdx !== null) inv.lines[ent.editIdx] = li; else inv.lines.push(li);
      refresh();
    }
    addBtn.addEventListener("click", addLine);
    cancelEdit.addEventListener("click", clearEntry);
    enterChain([woIn, gold, big, stand, reg, wagesIn], addLine);
    enterChain([dia], addLine);

    function editLine(i) {
      const li = inv.lines[i];
      clearEntry();
      ent.editIdx = i;
      ent.lid = li.lid || null;
      if (li.wageOnly) {
        woIn.value = li.note || ""; ent.lastWo = woIn.value;
        wagesIn.setVal(li.amount);
      } else {
        ent.src = li.src || "";
        ent.karat = li.karat || ent.karat;
        karatSel.value = String(ent.karat);
        woIn.value = li.wo || ""; ent.lastWo = li.wo || "";
        fillFrom(li);
        wagesIn.setVal(li.wages);
        if (Math.abs(G.g(li.reg18, ent.karat) - G.registered(G.g(li.gold18, ent.karat), G.g(li.small18, ent.karat),
          G.g(li.big18, ent.karat), ent.stoneRate)) > 0.0051) ent.regManual = true;
      }
      addBtn.textContent = "✔ حفظ تعديل السطر";
      cancelEdit.style.display = "";
      renderPickBtn();
      setNotice("info", `تعديل السطر ${i + 1}${li.wo ? " — الطقم " + li.wo : ""}`);
      entryCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── البنود والإجماليات ──
    const linesBox = h("div");
    const totalsBox = h("div", { class: "totals" });
    function lineTitle(li, i) {
      if (li.wageOnly) return [h("b", null, "أجور فقط"), li.note ? h("span", { class: "muted small" }, "  · " + li.note) : null];
      return [li.wo ? h("span", { class: "wo", dir: "auto", text: li.wo }) : h("b", null, `طقم ${i + 1}`),
        li.reg18 > 0 ? h("span", { class: "badge", style: { marginRight: "6px" } }, `عيار ${li.karat || 18}`)
          : h("span", { class: "badge", style: { marginRight: "6px" } }, "ماس فقط"),
        li.src ? h("span", { class: "muted small" }, "  · من الطقوم التي معي") : null];
    }
    function refresh() {
      linesBox.innerHTML = "";
      if (!inv.lines.length) {
        linesBox.append(h("div", { class: "empty" }, "لا بنود بعد — اكتب الوزن أو الأجور أو الماس ثم «+ إضافة»"));
      }
      inv.lines.forEach((li, i) => {
        const lk = li.karat || 18;
        const cell = (label, val) => h("div", { class: "muted" }, label, h("b", { class: "num" }, val));
        linesBox.append(h("div", { class: "line" + (ent.editIdx === i ? " editing" : "") },
          h("div", { class: "top" },
            li.photo ? photoThumb(li.photo, "sm") : null,
            h("div", { class: "grow" }, ...lineTitle(li, i)),
            h("div", { class: "act" },
              h("button", { onclick: () => editLine(i), "aria-label": "تعديل" }, ico("edit", 17)),
              h("button", { class: "del", "aria-label": "حذف", onclick: async () => {
                if (await confirmSheet(`حذف ${li.wageOnly ? "سطر الأجور" : li.wo ? "الطقم " + li.wo : "السطر " + (i + 1)}؟`, "حذف", true)) {
                  inv.lines.splice(i, 1);
                  if (ent.editIdx === i) clearEntry();
                  refresh();
                }
              } }, ico("x", 17)))),
          li.wageOnly ? h("div", { class: "vals" }, cell("الأجور", f2(li.amount)))
            : h("div", { class: "vals" },
              cell("الوزن", li.reg18 > 0 ? gw(li.reg18, lk) : "—"),
              cell("💎 الماس", li.diamond > 0 ? f2(li.diamond) : "—"),
              cell("الأجور", f2(li.wages)))));
      });
      const t = D.totals(inv.lines, inv.vat);
      const sets = inv.lines.filter((l) => !l.wageOnly).length;
      const dia0 = D.diamondOf(inv);
      const k = vk();
      totalsBox.innerHTML = "";
      const row = (a, b, cls) => h("div", { class: "spread" + (cls ? " " + cls : "") }, h("span", null, a), h("span", { class: "num" }, b));
      totalsBox.append(row("عدد الأطقم", String(sets)),
        row(`إجمالي الوزن (عيار ${k})`, gw(t.totalW18)),
        dia0 > 0 ? row("💎 إجمالي الماس (جم)", f2(dia0)) : null,
        row("إجمالي الأجور", f2(t.wages)));
      if (inv.vat) totalsBox.append(row("ضريبة 15% على الأجور", f2(t.vatAmt)));
      totalsBox.append(row("الإجمالي", f2(t.grand) + " ريال", "grand"));
      if (inv.shopId) {
        const fac = forFactory();
        const before = D.balance(s, inv.shopId, inv.id);
        const e = D.effects({ kind: inv.kind, totalW18: t.totalW18, grand: t.grand });
        const g18 = Num_round3(before.gold18 + e.gd - e.gc);
        const c = Num_round2(before.cash + e.cd - e.cc);
        totalsBox.append(h("hr", { class: "sep" }),
          h("div", { class: "spread small" }, h("span", null, "رصيد الذهب بعدها"), goldBal(g18, fac)),
          h("div", { class: "spread small" }, h("span", null, "رصيد الأجور بعدها"), cashBal(c, fac)));
      }
      renderPickBtn();
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
        const pending = woIn.value.trim() || (reg.getVal() || 0) > 0 || (dia.getVal() || 0) > 0 || !wagesIn.isBlank();
        if (pending && !(await confirmSheet("في خانات الطقم ما لم يُضَف (لم تضغط «+ إضافة»).\n\nالترحيل بدونه؟", "ترحيل بدونه"))) return;
        if (!inv.shopId) { pickParty(); throw new Error(`اختر ${partyWord()}`); }
        D.checkLines(inv.lines);
        const t = D.totals(inv.lines, inv.vat);
        const dia0 = D.diamondOf(inv);
        const msg = `${editing ? "حفظ تعديل" : "ترحيل"} ${INV_TITLE[inv.kind]} — «${shopTitle(inv.shopId)}»\n` +
          `${inv.lines.filter((l) => !l.wageOnly).length} طقم · ${gw(t.totalW18)} جم عيار ${vk()}` +
          (dia0 > 0 ? ` · 💎 ${f2(dia0)} جم` : "") + "\n" +
          `الأجور ${f2(t.wages)}${inv.vat ? ` + ضريبة ${f2(t.vatAmt)}` : ""} = ${f2(t.grand)} ريال`;
        if (!(await confirmSheet(msg, editing ? "حفظ التعديل" : "ترحيل"))) return;
        const rec = D.saveInvoice(s, { ...inv, heldId: inv.heldId });
        const ops = [["invoices", "put", rec], ...S.meta(s)];
        if (inv.heldId) ops.push(["held", "del", inv.heldId]);
        if (await persist(ops)) {
          clearDraft();
          toast(`${editing ? "حُفظ تعديل" : "رُحّل"} ${rec.no}`);
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
          toast("عُلّقت — تجدها في «المعلّقات»");
          replace("held");
        }
      } catch (e) { err(e); }
    }

    // الضريبة والبيان: نادراً ما يُحتاجان — مطويّان تحت الإجماليات
    const vatIn = h("input", { type: "checkbox", checked: inv.vat, onchange: (e) => { inv.vat = e.target.checked; refresh(); } });
    const descIn = h("input", { class: "in", value: inv.desc, placeholder: "البيان — يظهر في كشف الحساب",
      oninput: (e) => { inv.desc = e.target.value; saveDraft(); } });
    const opts = h("details", { class: "opts" }, h("summary", null, "ضريبة · بيان (اختياري)"),
      h("label", { class: "switch" }, vatIn, "ضريبة 15% على الأجور"), descIn);
    if (inv.vat || inv.desc) opts.open = true;

    const entryCard = h("div", { class: "card" }, h("h2", null, ico("gem", 18), "الطقم"),
      pickBtn,
      h("div", { class: "grid2" }, field("الطقم (اختياري)", woIn), field("العيار", karatSel)),
      h("div", { style: { marginTop: "2px" } }, detailsBtn), detailsBox,
      h("div", { class: "grid2", style: { marginTop: "8px" } }, field("الوزن (جم)", reg), field("الأجور (ريال)", wagesIn)),
      h("div", { class: "grid2", style: { marginTop: "8px" } }, field("💎 الماس (جم)", dia),
        h("div", { class: "fld" }, h("span", null, "صورة الطقم"), photoBox, photoIn)),
      // الأزرار قبل الإشعار: الإشعار يظهر عند مغادرة خانة الطقم —
      // ولو كان فوقها لانزاح الزرّ تحت الإصبع فتقع اللمسة على غيره
      h("div", { class: "row", style: { marginTop: "10px" } }, addBtn, cancelEdit),
      notice);

    v.append(entryCard,
      h("div", { class: "card" }, h("h2", null, ico("list", 18), "البنود"), linesBox, totalsBox, opts),
      h("div", { class: "footer-bar" },
        h("button", { class: "btn", onclick: save }, editing ? "حفظ التعديل" : "ترحيل"),
        editing ? null : h("button", { class: "btn ghost", onclick: hold }, "⏸ تعليق")));
    header();
    renderDetails();
    renderPhoto();
    refresh();
    hintWages();
    if (q.piece && !editing) usePiece(D.pieceById(s, q.piece));
    if (!inv.shopId) setTimeout(pickParty, 150);
    else if (!q.piece) setTimeout(() => woIn.focus(), 150);
  }

  const Num_round3 = (x) => root.Num.pyRound(x, 3);
  const Num_round2 = (x) => root.Num.pyRound(x, 2);

  // ══ التحصيل من محل · الدفع لمصنع ══
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
    const isPay = vo.kind === "payment";
    const p0 = D.shopById(s, vo.shopId);
    // دفعٌ قديم لمحل (من الإصدارات الأولى) يبقى قابلاً للتعديل كما هو
    const legacy = isPay && p0 && !D.isFactory(p0);
    const forFactory = isPay && !legacy;
    const word = forFactory ? "المصنع" : "العميل";
    const label = isPay ? (legacy ? "صرف لمحل" : "سداد للمصنع") : "تحصيل من العميل";
    const header = () => {
      const sh = D.shopById(s, vo.shopId);
      docHeader(label + (editing ? ` ${vo.no}` : ""), sh ? sh.name : "", `اختر ${word}`, vo.date, pickParty,
        (d) => { vo.date = d; header(); });
    };
    const v = view();
    // ما في صناديقي (دون هذا السند إن كان يُعدَّل)
    const hd = D.holdings({ ...s, vouchers: s.vouchers.filter((x) => x.id !== vo.id) });
    const boxOf = (karat) => (hd.boxes.find((b) => b.karat === karat) || { weight: 0 }).weight;

    async function pickParty() {
      const it = await pickSheet(`اختر ${word}`, partyItems(forFactory ? "factory" : "shop"),
        { addLabel: forFactory ? "+ مصنع جديد" : "+ عميل جديد", empty: forFactory ? "لا مصانع بعد" : "لا عملاء بعد" });
      if (!it) return;
      if (it.add) { go(forFactory ? "shop-form?type=factory" : "shop-form"); return; }
      vo.shopId = it.id; header(); refresh();
    }
    const notesIn = h("input", { class: "in", value: vo.notes, placeholder: "البيان — يظهر في كشف الحساب", oninput: (e) => { vo.notes = e.target.value; } });

    const rowsBox = h("div");
    function renderRows() {
      rowsBox.innerHTML = "";
      vo.rows.forEach((r, i) => {
        const card = h("div", { class: "line" });
        card.append(h("div", { class: "top" },
          h("b", null, r.kind === "gold" ? "ذهب" : "نقد"),
          h("div", { class: "act" }, h("button", { class: "del", "aria-label": "حذف", onclick: () => { vo.rows.splice(i, 1); renderRows(); refresh(); } }, ico("x", 17)))));
        if (r.kind === "gold") {
          const w = numInput({ value: r.weight });
          const ks = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: `عيار ${x}` })));
          ks.value = String(r.karat || k);
          const eq = h("div", { class: "muted small num" });
          const avail = h("div", { class: "small" });
          const upd = () => {
            r.weight = w.getVal() || 0; r.karat = parseInt(ks.value, 10);
            const vg = G.voucherGold(r.weight, r.karat);
            eq.textContent = `= ${f2(vg.equiv)} جم عيار 18` + (k !== 18 ? ` · ${gw(vg.equiv)} جم عيار ${k}` : "");
            if (isPay) {
              const have = boxOf(r.karat);
              avail.className = "small " + (r.weight > have + 0.0005 ? "bal-on" : "muted");
              avail.textContent = `معك في صندوق عيار ${r.karat}: ${f2(have)} جم` + (r.weight > have + 0.0005 ? " — أقلّ مما تدفع" : "");
            }
            refresh();
          };
          w.addEventListener("input", upd); ks.addEventListener("change", upd);
          card.append(h("div", { class: "grid2", style: { marginTop: "6px" } }, field("الوزن (جم)", w), field("العيار", ks)), eq, isPay ? avail : null);
          upd();
        } else {
          const a = numInput({ value: r.amount });
          const avail = h("div", { class: "small muted" });
          const upd = () => {
            r.amount = a.getVal() || 0;
            if (isPay) {
              const have = hd.cash.amount;
              avail.className = "small " + (r.amount > have + 0.005 ? "bal-on" : "muted");
              avail.textContent = `معك نقداً: ${f2(have)} ريال` + (r.amount > have + 0.005 ? " — أقلّ مما تدفع" : "");
            }
            refresh();
          };
          a.addEventListener("input", upd);
          card.append(h("div", { style: { marginTop: "6px" } }, field("المبلغ (ريال)", a)), isPay ? avail : null);
          upd();
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
    // البيان (والخصومات في التحصيل) مطويّةٌ — نادراً ما تُحتاج
    const extras = h("details", { class: "opts" },
      h("summary", null, isPay ? "بيان (اختياري)" : "بيان · خصومات (اختياري)"), notesIn,
      isPay ? null : h("div", { class: "grid2", style: { marginTop: "10px" } },
        field(`خصم مسموح وزناً (جم عيار ${k})`, dGold), field("خصم مسموح نقداً (ريال)", dCash),
        field("فرق الصافي (ريال، + زيادة · − تخفيض)", nDiff, "span2")));
    if (vo.notes || vo.discCash || vo.discGold18 || vo.netDiff) extras.open = true;

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
        const fac = D.isFactory(D.shopById(s, vo.shopId));
        const dv = draft();
        const before = D.balance(s, vo.shopId, vo.id);
        let e;
        try {
          e = D.effects({ kind: vo.kind, rows, discCash: Num_round2(dv.discCash), discGold18: Num_round3(dv.discGold18),
            netDiff: Num_round2(dv.netDiff) });
        } catch (x) { e = { gd: 0, gc: 0, cd: 0, cc: 0 }; }
        totalsBox.append(h("hr", { class: "sep" }),
          h("div", { class: "spread small" }, h("span", null, "رصيد الذهب قبل"), goldBal(before.gold18, fac)),
          h("div", { class: "spread small" }, h("span", null, "رصيد الذهب بعد"), goldBal(Num_round3(before.gold18 + e.gd - e.gc), fac)),
          h("div", { class: "spread small" }, h("span", null, "رصيد النقد قبل"), cashBal(before.cash, fac)),
          h("div", { class: "spread small" }, h("span", null, "رصيد النقد بعد"), cashBal(Num_round2(before.cash + e.cd - e.cc), fac)));
      }
    }
    async function save() {
      try {
        if (!vo.shopId) { pickParty(); throw new Error(`اختر ${word}`); }
        const dv = draft();
        if ([dGold.getVal(), dCash.getVal(), nDiff.getVal()].some((x) => !isFinite(x))) throw new Error("رقمٌ غير صحيح");
        const rows = D.voucherRows(vo.rows);
        let eq = 0, cash = 0;
        for (const r of rows) { eq += r.equiv; cash += r.amount; }
        const golds = rows.filter((r) => r.kind === "gold").map((r) => `${f2(r.weight)} جم عيار ${r.karat}`).join(" + ");
        const msg = `${editing ? "حفظ تعديل" : "ترحيل"} ${label} — «${shopTitle(vo.shopId)}»\n` +
          `${golds ? "ذهب " + golds + "\n" : ""}نقد ${f2(Num_round2(cash))} ريال`;
        if (!(await confirmSheet(msg, editing ? "حفظ التعديل" : "ترحيل"))) return;
        const rec = D.saveVoucher(s, dv);
        if (await persist([["vouchers", "put", rec], ...S.meta(s)])) {
          toast(`${editing ? "حُفظ تعديل" : "رُحّل"} ${rec.no}`);
          replace(`doc/vo/${rec.id}`);
        }
      } catch (e) { err(e); }
    }
    v.append(
      h("div", { class: "card" }, h("h2", null, ico(isPay ? "out" : "in", 18), isPay ? "ما سدّدته" : "ما حصّلته"), rowsBox,
        h("div", { class: "row" },
          h("button", { class: "btn ghost grow", onclick: () => { vo.rows.push({ kind: "gold", weight: 0, karat: k, notes: "" }); renderRows(); } }, "+ ذهب"),
          h("button", { class: "btn ghost grow", onclick: () => { vo.rows.push({ kind: "cash", amount: 0, notes: "" }); renderRows(); } }, "+ نقد"))),
      h("div", { class: "card" }, totalsBox, extras),
      h("div", { class: "footer-bar" }, h("button", { class: "btn", onclick: save }, editing ? "حفظ التعديل" : "ترحيل")));
    header(); renderRows(); refresh();
    if (!vo.shopId) setTimeout(pickParty, 150);
  }

  // ══ عرض المستند: مشاركة · طباعة · تعديل · حذف ══
  function docView(type, id) {
    const s = st();
    const isInv = type === "inv";
    const d = (isInv ? s.invoices : s.vouchers).find((x) => x.id === id);
    if (!d) { replace("log"); return; }
    setBar(`${D.KIND_LABEL[d.kind]} ${d.no}`, `${shopTitle(d.shopId)} · ${dmy(d.date)}`);
    setTab("more");
    let html = isInv ? P.invoiceHtml(s, d, {}) : P.voucherHtml(s, d);
    const v = view();
    const name = `${d.no}`;
    v.append(h("div", { class: "quick" },
      quickBtn("share", "مشاركة صورة", () => B.shareHtmlImage(html, name)),
      quickBtn("printer", "طباعة / PDF", () => B.printHtml(html, name)),
      isInv ? quickBtn("chat", "نص واتساب", () => B.shareText(P.invoiceText(s, d))) : quickBtn("book", "كشف الحساب", () => go(`statement/${d.shopId}`)),
      quickBtn("edit", "تعديل", () => go(`${isInv ? "invoice" : "voucher"}/edit/${d.id}`)),
      quickBtn("trash", "حذف", async () => {
        if (!(await confirmSheet(`حذف ${D.KIND_LABEL[d.kind]} ${d.no}؟\n\nيُلغى أثره من رصيد «${shopTitle(d.shopId)}».`, "حذف", true))) return;
        if (isInv) D.deleteInvoice(s, d.id); else D.deleteVoucher(s, d.id);
        if (await persist([[isInv ? "invoices" : "vouchers", "del", d.id]])) { toast(`حُذف ${d.no}`); replace(`shop/${d.shopId}`); }
      }),
      isInv ? quickBtn("book", "كشف الحساب", () => go(`statement/${d.shopId}`)) : quickBtn("store", "الحساب", () => go(`shop/${d.shopId}`))));
    const frame = previewFrame(html);
    v.append(frame);
    // صور الأطقم تُحمَّل ثم تُعاد المعاينة بها (والمشاركة والطباعة كذلك)
    const ids = isInv ? d.lines.map((l) => l.photo).filter(Boolean) : [];
    if (ids.length) {
      S.getPhotos(ids).then((ph) => {
        if (!Object.keys(ph).length) return;
        html = P.invoiceHtml(s, d, ph);
        frame.setHtml(html);
      });
    }
  }

  // المعاينة: صفحةٌ بعرض 1000 تُصغَّر — أو «مرنة» تأخذ عرض الشاشة كما هي
  function previewFrame(html, opts) {
    const fluid = !!(opts && opts.fluid);
    const box = h("div", { class: "preview" + (fluid ? " fluid" : "") });
    const fr = h("iframe", { title: "معاينة" });
    box.append(fr);
    const fit = () => {
      try {
        if (fluid) {
          fr.style.width = "100%";
          const ht = fr.contentDocument.documentElement.scrollHeight;
          fr.style.height = ht + "px";
          box.style.height = ht + "px";
          return;
        }
        const w = box.clientWidth || 360;
        const sc = w / 1000;
        fr.style.width = "1000px";
        fr.style.transform = `scale(${sc})`;
        const ht = fr.contentDocument.documentElement.scrollHeight;
        fr.style.height = ht + "px";
        box.style.height = Math.ceil(ht * sc) + "px";
      } catch (e) { /* */ }
    };
    fr.addEventListener("load", () => { fit(); setTimeout(fit, 300); });
    window.addEventListener("resize", fit, { once: true });
    box.setHtml = (x) => { fr.srcdoc = x; };
    box.setHtml(html);
    return box;
  }

  // ══ كشف الحساب ══
  function statementScreen(id, q) {
    const s = st();
    const shop = D.shopById(s, id);
    if (!shop) { replace("customers"); return; }
    const fac = D.isFactory(shop);
    const mode = q.view === "diamond" ? "diamond" : "gold";
    const from = q.from || "", to = q.to || "";
    setBar("كشف حساب", (fac ? "مصنع " : "") + shop.name);
    setTab("customers");
    const v = view();
    const url = (o) => {
      const x = Object.assign({ id, from, to, view: mode === "diamond" ? "diamond" : "" }, o);
      const qs = ["from", "to", "view"].filter((k) => x[k]).map((k) => `${k}=${encodeURIComponent(x[k])}`).join("&");
      return `statement/${x.id}` + (qs ? "?" + qs : "");
    };
    // الحساب يُبدَّل من هنا مباشرة
    const partyBtn = h("button", { type: "button", class: "pick", onclick: pickPartyThen(null, (nid) => replace(url({ id: nid }))) },
      h("span", null, h("span", { class: "muted small" }, fac ? "مصنع · " : "محل · "), h("span", { class: "t" }, shop.name)), h("span", null, "▾"));
    const viewSeg = h("div", { class: "seg", style: { marginTop: "8px" } },
      h("button", { class: mode === "gold" ? "on" : "", onclick: () => replace(url({ view: "" })) }, "كشف بالذهب"),
      h("button", { class: mode === "diamond" ? "on" : "", onclick: () => replace(url({ view: "diamond" })) }, "💎 كشف بالألماس"));
    const fIn = h("input", { class: "in", type: "date", value: from, onchange: (e) => replace(url({ from: e.target.value })) });
    const tIn = h("input", { class: "in", type: "date", value: to, onchange: (e) => replace(url({ to: e.target.value })) });
    const chips = h("div", { class: "chips", style: { marginTop: "8px" } });
    for (const [label, a, b] of periodPresets()) {
      chips.append(h("button", { class: "chip" + (from === a && to === b ? " on" : ""), onclick: () => replace(url({ from: a, to: b })) }, label));
    }
    v.append(h("div", { class: "card" }, partyBtn, viewSeg, chips,
      h("div", { class: "grid2", style: { marginTop: "8px" } }, field("من", fIn), field("إلى", tIn))));
    let kpis;
    if (mode === "diamond") {
      const dres = D.diamondStatement(s, id, from || null, to || null);
      const net = fac ? -dres.diamond : dres.diamond;
      kpis = h("div", { class: "kpis" },
        h("div", { class: "kpi" }, h("b", null, fac ? "صافي الماس (البضاعة − الإرجاع)" : "صافي الماس (المبيعات − المرتجع)"),
          h("span", { class: "v num" }, f2(net)), h("span", { class: "u" }, " جم")),
        h("div", { class: "kpi" }, h("b", null, fac ? "بضاعة · إرجاع" : "مبيعات · مرتجع"),
          h("span", { class: "v num small-v" }, fac ? `${f2(dres.minus)} · ${f2(dres.plus)}` : `${f2(dres.plus)} · ${f2(dres.minus)}`), h("span", { class: "u" }, " جم")));
    } else {
      const res = D.statement(s, id, from || null, to || null);
      kpis = h("div", { class: "kpis" },
        h("div", { class: "kpi" }, h("b", null, `رصيد الذهب (عيار ${vk()})`), h("div", { class: "v num" }, goldBal(res.gold18, fac))),
        h("div", { class: "kpi" }, h("b", null, "رصيد النقد"), h("div", { class: "v num" }, cashBal(res.cash, fac))));
    }
    const html = P.statementHtml(s, id, from || null, to || null, mode);
    const name = `كشف ${shop.name}${mode === "diamond" ? " — الماس" : ""}`;
    v.append(kpis,
      h("div", { class: "row", style: { marginBottom: "12px" } },
        h("button", { class: "btn grow", onclick: () => B.shareHtmlImage(html, name) }, ico("share", 18), "مشاركة صورة"),
        h("button", { class: "btn ghost grow", onclick: () => B.printHtml(html, name) }, ico("printer", 18), "طباعة / PDF")),
      h("div", { class: "sec-title" }, ico("image", 18), "معاينة الكشف كما يُرسَل صورةً"),
      previewFrame(html, { fluid: true }));
  }

  // ══ سجل العمليات ══
  function logScreen(q) {
    const s = st();
    setBar("سجل العمليات", "الفواتير والسندات", { back: false });
    setTab("more");
    const v = view();
    let kind = q.kind || "";
    const search = h("input", { class: "in", type: "search", placeholder: "ابحث برقم المستند أو الاسم أو الطقم…", value: q.q || "" });
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
    for (const [kk, label] of [["", "الكل"], ["sale", "بيع"], ["sale_return", "مرتجع"], ["receipt", "تحصيل"],
      ["payment", "سداد"], ["purchase", "بضاعة"], ["purchase_return", "إرجاع للمصنع"]]) {
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

  // ══ حركة الطقم (باسمه) ══
  function woScreen(q) {
    const s = st();
    setBar("حركة الطقم", "كل ما جرى على طقمٍ باسمه");
    setTab("more");
    const v = view();
    const inp = h("input", { class: "in hl", placeholder: "اسم الطقم أو رقمه", value: q.no || "", enterkeyhint: "search", dir: "auto" });
    const out = h("div");
    const render = () => {
      const no = inp.value.trim();
      out.innerHTML = "";
      if (!no) return;
      const hist = D.woHistory(s, no);
      if (!hist.length) { out.append(h("div", { class: "empty" }, `لا حركة للطقم ${no}`)); return; }
      const last = hist[hist.length - 1];
      const who = last.shop ? last.shop.name : "—";
      const what = `${D.KIND_LABEL[last.kind]} ${last.inv.no}`;
      const msg = D.IN_KINDS.includes(last.kind) ? `الآن: معك — ${what} من «${who}»`
        : last.kind === "sale" ? `الآن: عند «${who}» — مباعٌ بالفاتورة ${last.inv.no}`
          : `الآن: رجع إلى المصنع «${who}» — ${what}`;
      out.append(h("div", { class: "note-bar " + (D.IN_KINDS.includes(last.kind) ? "info" : "warn"), style: { marginBottom: "10px" } }, msg));
      for (const m of hist.slice().reverse()) {
        const lk = m.line.karat || 18;
        out.append(h("div", { class: "list-item", onclick: () => go(`doc/inv/${m.inv.id}`) },
          m.line.photo ? photoThumb(m.line.photo, "md") : null,
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t" }, m.shop ? m.shop.name : "—"), kindBadge(m.kind)),
            h("div", { class: "spread muted small" },
              h("span", null, h("span", { dir: "ltr", text: m.inv.no }), " · ", h("span", { dir: "ltr", text: dmy(m.date) })),
              h("span", { class: "num" }, `${gw(m.line.reg18, lk)} جم ${lk} · أجر ${f2(G.wageView(m.line.rate18, lk))}`)))));
      }
    };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); render(); } });
    inp.addEventListener("change", render);
    v.append(h("div", { class: "card" }, field("الطقم", inp)), out);
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
        } }, ico("x", 17)))));
    }
    function render() { view().innerHTML = ""; heldScreen(); }
  }

  // ══ المزيد ══
  function moreScreen() {
    setBar("المزيد", "", { back: false });
    setTab("more");
    const v = view();
    const item = (icon, t, sub, fn) => h("div", { class: "list-item", onclick: fn },
      h("span", { class: "avatar" }, ico(icon, 20)), h("div", { class: "grow" }, h("div", { class: "t" }, t),
        sub ? h("div", { class: "muted small" }, sub) : null), ico("chevron", 18, "muted"));
    const us = B.updateState();
    v.append(
      item("list", "سجل العمليات", "كل الفواتير والسندات — بحثٌ ونوع", () => go("log")),
      item("search", "حركة الطقم", "كل ما جرى على طقمٍ باسمه", () => go("wo")),
      item("pause", "المعلّقات", `${st().held.length} فاتورة لم تُرحَّل`, () => go("held")),
      item("book", "كشف حساب", "محل أو مصنع", pickPartyThen(null, (id) => go(`statement/${id}`))),
      us.unsupported ? null : item("update", "التحديثات", us.available ? "يوجد إصدارٌ جديد" : `الإصدار ${us.version}`, updateSheet),
      item("settings", "الإعدادات والحفظ", "اسم النشاط · العيار · المظهر · الحفظ التلقائي · النشر", () => go("settings")));
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
    const backupName = () => `gold-backup-${D.today()}.json`;
    const doBackup = async (share) => {
      const text = JSON.stringify(D.toBackup(s, await S.allPhotos()));
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
        await importPhotos(D.backupPhotos(obj));
        App.state = ns;
        applyTheme();
        toast("استُرجعت البيانات");
        scheduleAutoBackup();
        syncAllPhotos();
        replace("home");
      } catch (e) { err(e.name === "SyntaxError" ? new Error("الملف تالف أو ليس نسخةً احتياطية") : e); }
    });
    // الحفظ التلقائي في مجلد
    const folder = B.backupFolder();
    const autoCard = !B.native ? null : h("div", { class: "card" }, h("h2", null, ico("folder", 18), "الحفظ التلقائي"),
      h("div", { class: "small", style: { marginBottom: "8px" } }, folder
        ? `مفعّل — بعد كل عمليةٍ تُحفظ نسخةٌ في المجلد «${folder}»` + (lastAutoBackup() ? `\nآخر حفظ: ${new Date(+lastAutoBackup()).toLocaleString("ar")}` : "")
        : "غير مفعّل. اختر مجلداً على الجوال (مثل Documents) يُحفظ فيه كل شيء تلقائياً — فتبقى بياناتك ولو حُذف التطبيق."),
      h("div", { class: "muted small", style: { marginBottom: "10px" } },
        "بعد إعادة تثبيت التطبيق: «استرجاع من المجلد» ثم اختر المجلد نفسه — فيعود كل شيء كما كان."),
      h("div", { class: "grid2" },
        h("button", { class: "btn" + (folder ? " ghost" : ""), onclick: () => B.pickBackupFolder() }, ico("folder", 18), folder ? "تغيير المجلد" : "اختيار المجلد"),
        h("button", { class: "btn ghost", onclick: () => B.restoreFromFolder() }, ico("history", 18), "استرجاع من المجلد")));
    const offF = onRoute("backupFolder", (r) => {
      if (r.ok) { toast(`الحفظ التلقائي في «${r.name}»`); scheduleAutoBackup(); syncAllPhotos(); offF(); offR(); replace("settings"); }
      else if (r.error) err(new Error(r.error));
    });
    const offR = onRoute("restore", async (r) => {
      if (!r.ok) { if (r.error) err(new Error(r.error)); return; }
      try { if (await restoreText(r.text, r.file)) { B.restorePhotos(); offF(); offR(); replace("home"); } } catch (e) { err(e); }
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
      autoCard,
      h("div", { class: "card" }, h("h2", null, ico("save", 18), "نسخةٌ في ملف"),
        h("div", { class: "muted small", style: { marginBottom: "10px" } },
          "نسخةٌ تحفظها أو ترسلها لنفسك (واتساب · درايف) — تنفع لنقل بياناتك إلى جوالٍ آخر." +
          (S0.lastBackup ? `\nآخر نسخة: ${dmy(S0.lastBackup.slice(0, 10))}` : "")),
        h("div", { class: "grid2" },
          h("button", { class: "btn ghost", onclick: () => doBackup(false) }, ico("save", 18), "حفظ ملف"),
          h("button", { class: "btn ghost", onclick: () => doBackup(true) }, ico("share", 18), "مشاركة")),
        h("button", { class: "btn ghost block", style: { marginTop: "8px" }, onclick: () => fileIn.click() }, ico("upload", 18), "استرجاع من ملف"),
        fileIn),
      B.native ? h("button", { class: "btn ghost block", style: { marginBottom: "12px" }, onclick: updateSheet }, ico("update", 18), "التحديثات") : null,
      h("div", { class: "muted small", style: { textAlign: "center", margin: "16px 0" } },
        `${APP_NAME} · الإصدار ${B.appVersion()} · ${D.shopsOnly(s).length} محل · ${D.factoriesOnly(s).length} مصنع · ${s.invoices.length} فاتورة · ${s.vouchers.length} سند`));
  }

  // ══ المحلات — المبيعات والتحصيل (كشاشة العملاء في البرنامج) ══
  function periodPresets() {
    const t = D.today(), ym = t.slice(0, 7);
    const d = new Date(+t.slice(0, 4), +t.slice(5, 7) - 2, 1);
    const prev = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const lastDay = (x) => `${x}-${String(new Date(+x.slice(0, 4), +x.slice(5, 7), 0).getDate()).padStart(2, "0")}`;
    return [["منذ البداية", "", ""], ["هذا الشهر", ym + "-01", ""], ["الشهر الماضي", prev + "-01", lastDay(prev)],
      ["هذه السنة", t.slice(0, 4) + "-01-01", ""]];
  }
  function gradeBadge(g) {
    // ألوان التقدير كما في شاشة العملاء في البرنامج
    const cls = { "مسدَّد": "good", "ممتاز": "good", "جيد": "mid", "مقبول": "fair", "سيء": "bad" }[g];
    return h("span", { class: "badge grade " + (cls === undefined ? "none" : cls) }, g);
  }
  function meter(pctVal) {
    const p = Math.max(0, Math.min(100, pctVal || 0));
    return h("div", { class: "meter", role: "meter", "aria-valuenow": String(p), "aria-valuemin": "0", "aria-valuemax": "100" },
      h("span", { style: { width: p + "%" } }));
  }
  function boardView(v, q) {
    const s = st(), k = vk();
    const side = q.side === "cash" ? "cash" : "gold";
    const from = q.from || "", to = q.to || "";
    const hideIdle = q.all !== "1";
    const url = (o) => {
      const x = Object.assign({ view: "board", side, from, to, all: hideIdle ? "" : "1" }, o);
      return "customers?" + Object.entries(x).filter(([, val]) => val !== "").map(([a, b]) => `${a}=${encodeURIComponent(b)}`).join("&");
    };
    const chips = h("div", { class: "chips" });
    for (const [label, a, b] of periodPresets()) {
      chips.append(h("button", { class: "chip" + (from === a && to === b ? " on" : ""), onclick: () => replace(url({ from: a, to: b })) }, label));
    }
    const fIn = h("input", { class: "in", type: "date", value: from, onchange: (e) => replace(url({ from: e.target.value })) });
    const tIn = h("input", { class: "in", type: "date", value: to, onchange: (e) => replace(url({ to: e.target.value })) });
    const sideSeg = h("div", { class: "seg sm" },
      h("button", { class: side === "gold" ? "on" : "", onclick: () => replace(url({ side: "gold" })) }, `الذهب (عيار ${k})`),
      h("button", { class: side === "cash" ? "on" : "", onclick: () => replace(url({ side: "cash" })) }, "النقد (ريال)"));
    const idle = h("input", { type: "checkbox", checked: hideIdle, onchange: (e) => replace(url({ all: e.target.checked ? "" : "1" })) });
    v.append(h("div", { class: "card" }, chips, h("div", { class: "grid2", style: { marginTop: "8px" } }, field("من", fIn), field("إلى", tIn)),
      h("div", { style: { marginTop: "10px" } }, sideSeg), h("label", { class: "switch" }, idle, "إخفاء من لا حركة له")));
    const b = D.board(s, from || null, to || null);
    const fmt = (x) => (side === "gold" ? gw(x) : f2(x));
    const unit = side === "gold" ? `جم ${k}` : "ريال";
    const T = b[side];
    const rows = hideIdle ? b.rows.filter(D.hasMovement) : b.rows;
    const tile = (label, val, sub) => h("div", { class: "stat" }, h("span", { class: "l" }, label),
      h("span", { class: "v num" }, val), sub ? h("span", { class: "u" }, sub) : null);
    v.append(h("div", { class: "stats" },
      tile("العملاء", String(rows.length)), tile("المبيعات", fmt(T.sales), unit), tile("المرتجع", fmt(T.returns),
        T.retPct === null ? unit : `${f2(T.retPct)}% · ${unit}`),
      tile("التحصيل", fmt(T.paid), T.paidPct === null ? unit : `${f2(T.paidPct)}% · ${unit}`), tile("الباقي", fmt(T.remaining), unit)));
    if (!rows.length) { v.append(h("div", { class: "empty" }, "لا حركة في الفترة")); return; }
    for (const r of rows) {
      const x = r[side];
      v.append(h("div", { class: "list-item col", onclick: () => go(`shop/${r.id}`) },
        h("div", { class: "spread" }, h("span", { class: "t" }, r.name), gradeBadge(x.grade)),
        h("div", { class: "grid3 small" },
          h("div", null, h("span", { class: "muted" }, "الصافي"), h("b", { class: "num" }, fmt(x.net))),
          h("div", null, h("span", { class: "muted" }, "التحصيل"), h("b", { class: "num" }, fmt(x.paid))),
          h("div", null, h("span", { class: "muted" }, "الباقي"), h("b", { class: "num" }, fmt(x.remaining)))),
        h("div", { class: "row small", style: { marginTop: "6px" } }, meter(x.paidPct),
          h("span", { class: "muted num", style: { minWidth: "48px", textAlign: "left" } }, x.paidPct === null ? "—" : `${f2(x.paidPct)}%`)),
        h("div", { class: "muted small" },
          r.lastPay ? ["آخر تحصيل ", h("span", { dir: "ltr", text: dmy(r.lastPay) })] : "لا تحصيل في الفترة",
          r.lastSale ? [" · آخر بيع ", h("span", { dir: "ltr", text: dmy(r.lastSale) })] : null,
          x.open ? [" · رصيد سابق ", h("span", { class: "num", text: fmt(x.open) })] : null)));
    }
  }

  // ══ الممتلكات: صندوقٌ لكل عيار، والنقد، والأطقم التي معي ══
  function holdingsScreen() {
    const s = st(), k = vk();
    setBar("الممتلكات", "ما معي الآن", { back: false, actions: [updateButton()] });
    setTab("holdings");
    const v = view();
    const hd = D.holdings(s);
    const empty = !hd.boxes.length && !hd.cash.moves.length && !hd.pieces.length;
    v.append(h("div", { class: "kpis" },
      h("div", { class: "kpi" }, h("b", null, "ذهب معي"), h("span", { class: "v num" }, gw(hd.gold18)), h("span", { class: "u" }, ` جم عيار ${k}`)),
      h("div", { class: "kpi" }, h("b", null, "نقد معي"), h("span", { class: "v num" }, f2(hd.cash.amount)), h("span", { class: "u" }, " ريال"))));
    const tile = (icon, title, val, unit, sub, onclick, neg) => h("button", { class: "box-tile", onclick },
      h("div", { class: "spread" }, h("span", { class: "box-ic" }, ico(icon, 20)), ico("chevron", 18, "muted")),
      h("div", { class: "box-t" }, title),
      h("div", { class: "box-v" + (neg ? " bal-on" : "") }, h("span", { class: "num" }, val), h("span", { class: "u" }, " " + unit)),
      sub ? h("div", { class: "muted small" }, sub) : null);
    const grid = h("div", { class: "boxes" });
    for (const b of hd.boxes) {
      grid.append(tile("coins", `ذهب عيار ${b.karat}`, f2(b.weight), "جم",
        `حصّلت ${f2(b.inSum)} · دفعت ${f2(b.outSum)}`, () => boxSheet(b), b.weight < -0.0005));
    }
    if (hd.cash.moves.length) {
      grid.append(tile("receipt", "الأجور والنقد", f2(hd.cash.amount), "ريال",
        `حصّلت ${f2(hd.cash.inSum)} · دفعت ${f2(hd.cash.outSum)}`, () => cashSheet(hd.cash), hd.cash.amount < -0.005));
    }
    grid.append(tile("package", "الطقوم", String(hd.pieces.length), "طقم",
      hd.pieces.length ? `${gw(hd.setsW18)} جم عيار ${k}` : "لا طقم معك", () => piecesSheet(hd.pieces)));
    v.append(grid);
    if (empty) {
      v.append(h("div", { class: "note-bar info", style: { margin: "4px 0 12px" } },
        "ما تحصّله من المحلات يظهر هنا في صندوق عياره، والنقد في صندوقه. وما تدفعه للمصانع يُخصم منها. " +
        "والأطقم: ما أخذته من مصنعٍ أو رجع إليك من محلٍّ ولم تبعه."));
    }
    v.append(h("div", { class: "quick" },
      quickBtn("in", "تحصيل من العميل", () => go("voucher/new?kind=receipt")),
      quickBtn("out", "سداد للمصنع", () => go("voucher/new?kind=payment")),
      quickBtn("package", "بضاعة من مصنع", () => go("invoice/new?kind=purchase"))));
  }

  // حركة صندوق: من أين دخل، وإلى من خرج، وكم، ومتى
  function movesList(moves, fmt, close) {
    const list = h("div");
    if (!moves.length) list.append(h("div", { class: "empty" }, "لا حركة"));
    for (const m of moves) {
      list.append(h("div", { class: "list-item", onclick: () => { close(); setTimeout(() => go(`doc/vo/${m.doc.id}`), 30); } },
        h("span", { class: "avatar" + (m.sign < 0 ? " ret" : "") }, ico(m.sign > 0 ? "in" : "out", 18)),
        h("div", { class: "grow" },
          h("div", { class: "spread" }, h("span", { class: "t" }, m.party ? m.party.name : "—"),
            h("b", { class: "num " + (m.sign > 0 ? "bal-for" : "bal-on") }, (m.sign > 0 ? "+" : "−") + fmt(m))),
          h("div", { class: "spread muted small" },
            h("span", null, (m.sign > 0 ? "تحصيل" : "دفع") + " · ", h("span", { dir: "ltr", text: m.doc.no })),
            h("span", { dir: "ltr", text: dmy(m.date) })),
          m.notes ? h("div", { class: "muted small" }, m.notes) : null)));
    }
    return list;
  }
  function sumRow(a, b, cls) {
    return h("div", { class: "spread" + (cls ? " " + cls : "") }, h("span", null, a), h("span", { class: "num" }, b));
  }
  function boxSheet(b) {
    return sheet((box, close) => {
      box.append(h("h3", null, ico("coins", 20), ` صندوق ذهب عيار ${b.karat}`),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          sumRow("حصّلته من المحلات", `${f2(b.inSum)} جم`), sumRow("دفعته للمصانع", `${f2(b.outSum)} جم`),
          sumRow("معي الآن", `${f2(b.weight)} جم`, "grand"),
          b.karat !== 18 ? h("div", { class: "muted small" }, `= ${f2(G.store(b.weight, b.karat))} جم مكافئ عيار 18`) : null),
        movesList(b.moves, (m) => `${f2(m.weight)} جم`, close));
    });
  }
  function cashSheet(c) {
    return sheet((box, close) => {
      box.append(h("h3", null, ico("receipt", 20), " صندوق الأجور والنقد"),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          sumRow("حصّلته من المحلات", `${f2(c.inSum)} ريال`), sumRow("دفعته للمصانع", `${f2(c.outSum)} ريال`),
          sumRow("معي الآن", `${f2(c.amount)} ريال`, "grand")),
        movesList(c.moves, (m) => `${f2(m.amount)} ريال`, close));
    });
  }
  async function piecesSheet(pieces) {
    const p = await sheet((box, close) => {
      box.append(h("h3", null, ico("package", 20), ` الطقوم التي معي (${pieces.length})`));
      if (!pieces.length) {
        box.append(h("div", { class: "empty" }, "لا طقم معك الآن — ما تأخذه من مصنعٍ أو يرجع إليك من محلٍّ يظهر هنا."));
        return;
      }
      for (const x of pieces) {
        box.append(h("div", { class: "list-item", onclick: () => close(x) },
          x.line.photo ? photoThumb(x.line.photo, "md")
            : h("span", { class: "avatar" + (x.fromKind === "sale_return" ? " ret" : "") }, ico(x.fromKind === "purchase" ? "package" : "return", 18)),
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t", dir: "auto" }, x.name || "طقمٌ بلا اسم"),
              h("b", { class: "num" }, `${gw(x.w18, x.karat)} جم`)),
            h("div", { class: "spread muted small" },
              h("span", null, `${x.fromKind === "purchase" ? "من مصنع" : "مرتجع من"} «${x.party ? x.party.name : "—"}»`),
              h("span", null, `عيار ${x.karat} · `, h("span", { dir: "ltr", text: dmy(x.date) }))))));
      }
    });
    if (!p) return;
    const act = await sheet((box, close) => {
      box.append(h("h3", null, p.name ? `الطقم ${p.name}` : "طقمٌ بلا اسم"),
        h("div", { class: "muted", style: { marginBottom: "10px" } },
          `${gw(p.w18, p.karat)} جم عيار ${p.karat} · ${p.fromKind === "purchase" ? "من مصنع" : "مرتجع من"} «${p.party ? p.party.name : "—"}» · ${dmy(p.date)}`),
        h("button", { class: "btn block", style: { marginBottom: "8px" }, onclick: () => close("sale") }, ico("receipt", 18), "بيعه لمحل"),
        p.fromKind === "purchase" ? h("button", { class: "btn ghost block", style: { marginBottom: "8px" }, onclick: () => close("back") }, ico("return", 18), "إرجاعه للمصنع") : null,
        h("button", { class: "btn ghost block", onclick: () => close("doc") }, ico("file", 18), `عرض ${D.KIND_LABEL[p.fromKind]} ${p.doc.no}`));
    });
    if (act === "sale") setTimeout(() => go(`invoice/new?kind=sale&piece=${encodeURIComponent(p.id)}`), 30);
    if (act === "back") setTimeout(() => go(`invoice/new?kind=purchase_return&shop=${p.party.id}&piece=${encodeURIComponent(p.id)}`), 30);
    if (act === "doc") setTimeout(() => go(`doc/inv/${p.doc.id}`), 30);
  }

  // ══ التحديثات ══
  function updateButton() {
    const us = B.updateState();
    const btn = h("button", { class: "icon-btn upd" + (us.available ? " dot" : ""), id: "upd-btn",
      "aria-label": "التحديثات", onclick: updateSheet }, ico("update", 20));
    if (us.unsupported) btn.style.display = "none";
    return btn;
  }
  function refreshUpdateDot(us) {
    const b = document.getElementById("upd-btn");
    if (b) b.classList.toggle("dot", !!(us && us.available));
  }
  let updateOpen = false;
  async function updateSheet() {
    if (updateOpen) return;
    updateOpen = true;
    const offs = [];
    await sheet((box) => {
      const body = h("div");
      const prog = h("div", { class: "progress", style: { display: "none" } }, h("span"));
      const note = h("div", { class: "muted small", style: { marginTop: "8px", whiteSpace: "pre-line" } });
      box.append(h("h3", null, ico("update", 20), " التحديثات"), body, prog, note);
      const render = (us) => {
        body.innerHTML = "";
        if (us.unsupported) {
          body.append(h("div", { class: "muted" }, "التحديث التلقائي يعمل في تطبيق أندرويد."));
          return;
        }
        const pub = us.published && us.published.code ? us.published : null;
        body.append(h("div", { class: "spread" }, h("span", null, "الإصدار المثبّت"), h("b", { class: "num" }, us.version)));
        if (us.available && pub) {
          body.append(h("div", { class: "update-card" },
            h("div", { class: "spread" }, h("b", null, `إصدارٌ جديد ${pub.version}`), ico("sparkles", 20)),
            pub.notes ? h("div", { class: "small", style: { whiteSpace: "pre-line", marginTop: "6px" } }, pub.notes) : null,
            h("button", { class: "btn block", style: { marginTop: "10px" }, onclick: () => {
              note.textContent = "جارٍ التنزيل…";
              prog.style.display = "";
              B.installUpdate();
            } }, ico("update", 18), us.ready ? "تثبيت التحديث الآن" : "تنزيل التحديث وتثبيته"),
            h("div", { class: "muted small", style: { marginTop: "6px" } },
              "يُنزَّل من GitHub ويُتحقَّق من بصمته، ثم يطلب أندرويد تأكيد التثبيت بلمسة. بياناتك تبقى كما هي.")));
        } else {
          body.append(h("div", { class: "ok-line" }, ico("check", 18), " أنت على آخر إصدارٍ منشور"));
        }
        if (us.lastCheck) body.append(h("div", { class: "muted small" }, "آخر فحص: " + new Date(us.lastCheck).toLocaleString("ar")));
        if (us.error) body.append(h("div", { class: "note-bar warn" }, us.error));
        body.append(h("button", { class: "btn ghost block sm", style: { marginTop: "8px" }, onclick: () => {
          note.textContent = "جارٍ الفحص…";
          B.checkUpdate();
        } }, ico("refresh", 18), "تحقّق الآن"));
        if (!us.canNotify) {
          body.append(h("button", { class: "btn ghost block sm", style: { marginTop: "8px" }, onclick: () => B.requestNotifications() },
            ico("bell", 18), "تفعيل إشعار التحديث"));
        }
      };
      offs.push(B.on("update", (us) => {
        note.textContent = us.error && !us.version ? us.error : "";
        prog.style.display = "none";
        if (us.version) render(us);
        refreshUpdateDot(us);
      }));
      offs.push(B.on("updateProgress", (p) => {
        prog.style.display = "";
        prog.firstChild.style.width = (p.pct || 0) + "%";
        note.textContent = `جارٍ التنزيل… ${p.pct || 0}%`;
      }));
      render(B.updateState());
      if (!B.updateState().unsupported) B.checkUpdate();
    });
    offs.forEach((f) => f());
    updateOpen = false;
  }

  // ══ الاسترجاع (من مجلد الحفظ التلقائي أو من ملف) ══
  async function restoreText(text, label) {
    let obj;
    try { obj = JSON.parse(text); } catch (e) { throw new Error("الملف تالف أو ليس نسخةً احتياطية"); }
    const ns = D.fromBackup(obj);
    const msg = `استرجاع ${label || "النسخة"} (${(obj.savedAt || "").slice(0, 10)}):\n` +
      `${ns.shops.length} عميل · ${ns.invoices.length} فاتورة · ${ns.vouchers.length} سند\n\n` +
      "تُستبدل بها البيانات الحالية في هذا الجوال.";
    if (!(await confirmSheet(msg, "استرجاع", true))) return false;
    await S.replaceAll(ns);
    await importPhotos(D.backupPhotos(obj));
    App.state = ns;
    applyTheme();
    toast("استُرجعت البيانات");
    return true;
  }

  // ══ الترحيب (أول تشغيل): مجلد الحفظ التلقائي أو استرجاع ما سبق ══
  function welcome() {
    setBar("أهلاً بك", "", { back: false, noTabs: true });
    const v = view();
    const done = () => { try { localStorage.setItem("welcomed", "1"); } catch (e) { /* */ } B.requestNotifications(); replace("home"); };
    const waitFolder = onRoute("backupFolder", (r) => { if (r.ok) { toast(`الحفظ التلقائي في «${r.name}»`); syncAllPhotos(); waitFolder(); waitRestore(); done(); } });
    const waitRestore = onRoute("restore", async (r) => {
      if (!r.ok) { if (r.error) err(new Error(r.error)); return; }
      try { if (await restoreText(r.text, r.file)) { B.restorePhotos(); waitFolder(); waitRestore(); done(); } } catch (e) { err(e); }
    });
    v.append(h("div", { class: "welcome" },
      h("img", { src: "img/icon.png", alt: "", class: "welcome-logo" }),
      h("h2", null, APP_NAME),
      h("div", { class: "muted" }, "حساباتك مع المحلات والمصانع"),
      h("p", { class: "muted" }, "بياناتك في جوالك وحده. اختر مجلداً يُحفظ فيه كل شيءٍ تلقائياً بعد كل عملية — " +
        "فإن حذفت التطبيق ثم ثبّته من جديد، اختر المجلد نفسه فيعود كل شيء كما كان."),
      h("button", { class: "btn block", onclick: () => B.pickBackupFolder() }, ico("folder", 20), "ابدأ — اختر مجلد الحفظ التلقائي"),
      h("button", { class: "btn ghost block", onclick: () => B.restoreFromFolder() }, ico("history", 20), "عندي بيانات سابقة — استرجاعها"),
      h("button", { class: "link", style: { marginTop: "12px" }, onclick: () => { waitFolder(); waitRestore(); done(); } }, "تخطَّ الآن")));
  }

  // ══ «+ جديد» ══
  async function newSheet() {
    const r = await sheet((box, close) => {
      box.append(h("h3", null, "عملية جديدة"),
        h("div", { class: "sec-title" }, "مع المحلات"),
        h("div", { class: "quick" },
          quickBtn("receipt", "فاتورة بيع", () => close("invoice/new?kind=sale")),
          quickBtn("return", "مرتجع", () => close("invoice/new?kind=sale_return")),
          quickBtn("in", "تحصيل", () => close("voucher/new?kind=receipt"))),
        h("div", { class: "sec-title" }, "مع المصانع"),
        h("div", { class: "quick" },
          quickBtn("out", "سداد للمصنع", () => close("voucher/new?kind=payment")),
          quickBtn("package", "بضاعة من مصنع", () => close("invoice/new?kind=purchase")),
          quickBtn("return", "إرجاع للمصنع", () => close("invoice/new?kind=purchase_return"))),
        h("div", { class: "sec-title" }, "حساب جديد"),
        h("div", { class: "quick" },
          quickBtn("store", "محل جديد", () => close("shop-form")),
          quickBtn("package", "مصنع جديد", () => close("shop-form?type=factory")),
          quickBtn("search", "حركة الطقم", () => close("wo"))));
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
    routeOffs.forEach((f) => f());
    routeOffs = [];
    v.innerHTML = "";
    window.scrollTo(0, 0);
    v.classList.remove("enter");
    void v.offsetWidth;                       // يعيد حركة الدخول لكل شاشة
    v.classList.add("enter");
    try {
      switch (parts[0]) {
        case "home": return home();
        case "shops": return customers(q);
        case "customers": return customers(q);
        case "holdings": return holdingsScreen();
        case "today": return todayScreen();
        case "dashboard": return holdingsScreen();
        case "welcome": return welcome();
        case "shop": return shopPage(parts[1]);
        case "shop-form": return shopForm(parts[1], q);
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

  // فحص التحديث عند الفتح والعودة إلى التطبيق — مرةً كل 3 ساعات على الأكثر
  function maybeCheckUpdate() {
    const us = B.updateState();
    if (us.unsupported) return;
    if (Date.now() - (us.lastCheck || 0) > 3 * 3600 * 1000) B.checkUpdate();
  }

  function firstRun() {
    const s = st();
    if (!B.native || B.backupFolder()) return false;
    if (s.shops.length + s.invoices.length + s.vouchers.length > 0) return false;
    try { return !localStorage.getItem("welcomed"); } catch (e) { return false; }
  }

  async function start() {
    App.state = await S.load();
    applyTheme();
    for (const b of document.querySelectorAll("#tabs button")) {
      b.querySelector(".i").append(ico(b.dataset.ic, b.dataset.tab === "plus" ? 26 : 22));
      b.addEventListener("click", () => {
        const t = b.dataset.tab;
        if (t === "plus") newSheet(); else go(t);
      });
    }
    // أحداث الأصل العامة: إشعار التحديث، ونتيجة الحفظ التلقائي
    B.on("openUpdate", () => updateSheet());
    B.on("update", (us) => refreshUpdateDot(us));
    let lastBackupErr = 0;
    B.on("backupDone", (r) => {
      if (r.ok) {
        try { localStorage.setItem("lastAutoBackup", String(r.at)); } catch (e) { /* */ }
      } else if (Date.now() - lastBackupErr > 60000) {   // تنبيهٌ واحد في الدقيقة لا مع كل حفظ
        lastBackupErr = Date.now();
        toast("تعذّر الحفظ التلقائي في المجلد: " + (r.error || "") + "\nاختر المجلد من جديد في الإعدادات.", "err");
      }
    });
    // صور المجلد: ما نقص منه يُكتب، وما يُسترجع منه يُحفظ
    B.on("photosMissing", async (r) => {
      for (const id of r.ids || []) { const d = await S.getPhoto(id); if (d) B.savePhoto(id, d.split(",")[1] || ""); }
    });
    B.on("photo", (r) => { if (r.id && r.b64) S.putPhoto(r.id, "data:image/jpeg;base64," + r.b64); });
    B.on("photosDone", (r) => { if (r.n) toast(`استُرجعت ${r.n} صورة`); });
    setTimeout(syncAllPhotos, 4000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) maybeCheckUpdate(); });
    window.addEventListener("hashchange", route);
    if (firstRun()) location.replace("#/welcome");
    else if (!location.hash) location.replace("#/home");
    route();
    maybeCheckUpdate();
  }

  App.start = start;
  App.go = go;
  document.addEventListener("DOMContentLoaded", start);
})(window);
