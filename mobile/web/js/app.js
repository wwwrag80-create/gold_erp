/* ÀUR — تطبيق حسابات الذهب للمندوب (الجوال): الشاشات والتنقّل.
 * المنطق كلّه في domain.js والمعادلات في gold.js؛ هنا الواجهة وحدها.
 */
(function (root) {
  "use strict";
  const { h, toast, err, sheet, confirmSheet, pickSheet, numInput, field, enterChain } = root.UI;
  const T = root.I18N.T;
  // العربية ⇄ English: يُحفظ الاختيار ثم يُعاد فتح التطبيق بلغته واتجاهه (بياناتك كما هي)
  const OTHER_LANG = () => (root.I18N.lang === "ar" ? "en" : "ar");
  const LANG_NAME = { ar: "العربية", en: "English" };
  function switchLang(l) {
    if (l === root.I18N.lang) return;
    root.I18N.setLang(l);
    location.reload();
  }
  const langChip = () => h("button", { type: "button", class: "chip lang-chip", onclick: () => switchLang(OTHER_LANG()) },
    ico("languages", 16), " ", LANG_NAME[OTHER_LANG()]);
  const { f2 } = root.Num;
  const G = root.Gold, D = root.Domain, P = root.PrintDoc, B = root.Bridge, S = root.Store;

  const App = { state: null };
  root.App = App;

  // ══ أدوات عامة ══
  const st = () => App.state;
  // عيار المجاميع (الإعدادات): حين تُجمع حساباتٌ بأعيرةٍ مختلفة. ولكل حسابٍ عياره (`pk`)
  const vk = () => parseInt(st().settings.viewKarat || 18, 10);
  // 1.13: عيارٌ واحد للعرض والمكافئ يُختار أعلى الرئيسية — كل الأوزان والأرصدة
  // والمكافئات تُعرض به (والتخزين بمكافئ 18 كما هو). وعيار الحساب (العميل/المصنع)
  // صار عيارَ الإدخال: به يبدأ سطر الذهب في فواتيره وسنداته
  const pk = () => vk();
  const ek = (party) => D.partyKarat(party, vk());
  const gw = (w18, k) => f2(G.g(w18, k || vk()));
  const dmy = P.dmy;
  const view = () => document.getElementById("view");

  // الرصيد بكلمته: العميل «عليه» (لي عنده) أو «له»، والمصنع «عليّ» (له عندي) أو «لي»
  function balWord(v, fac) {
    if (fac) return v < 0 ? T("عليّ") : T("لي");
    return v > 0 ? T("عليه") : T("له");
  }
  function balSpan(v, unit, fac) {
    if (Math.abs(v) < 0.005) return h("span", { class: "muted" }, "0.00");
    const owing = fac ? v < 0 : v > 0;   // أحمر: ما على العميل لي، أو ما عليّ للمصنع
    return h("span", { class: owing ? "bal-on" : "bal-for" }, `${f2(Math.abs(v))} ${unit} ${balWord(v, fac)}`);
  }
  function balText(v, unit, fac) {
    if (Math.abs(v) < 0.005) return "0.00";
    return `${f2(Math.abs(v))} ${unit} ${balWord(v, fac)}`;
  }
  // رصيد الذهب بعيار الحساب (أو المعطى) — والعيار مكتوبٌ معه حين يخالف عيار المجاميع
  function goldBal(w18, fac, k) {
    k = k || vk();
    return balSpan(G.g(w18, k), k === vk() ? T("جم") : T("جم ع{0}", k), fac);
  }
  function cashBal(c, fac) { return balSpan(c, T("ريال"), fac); }
  // 1.12: سبيكة ذهب بجانب أوزان الذهب، وورقة نقد بجانب النقد والأجور
  const icoGold = () => h("span", { class: "u", html: P.ICO_GOLD });
  const icoCash = () => h("span", { class: "u", html: P.ICO_CASH });
  const APP_NAME = "ÀUR";
  // رابط ÀUR للجميع: الآيفون (يُضاف إلى الشاشة الرئيسية) وتحميل أندرويد — Cloudflare Pages
  const SITE_URL = "https://gold-erp.pages.dev";

  // الانتقال بعد أن يكتمل رجوع السجل الذي يتبع إغلاق نافذةٍ سفلية — وإلا ألغاه
  function go(path) { root.UI.idle().then(() => { location.hash = "#/" + path; }); }
  function replace(path) { root.UI.idle().then(() => location.replace("#/" + path)); }

  async function persist(ops) {
    try { await S.write(ops); scheduleAutoBackup(); markWebChange(); return true; }
    catch (e) { err(new Error(T("تعذّر الحفظ في الجوال: ") + ((e && e.message) || e))); return false; }
  }

  // نسخةٌ في مجلد الحفظ التلقائي (خارج التطبيق) بعد كل تغيير — بتأنٍّ يسير
  // فتُجمع التغييرات المتتابعة في كتابةٍ واحدة
  let backupTimer = null;
  // ══ نسخة الويب (الآيفون عبر الرابط) ══
  // بياناتك تُحفظ في الجوال فوراً بعد كل عملية. أما نسخةٌ خارج التطبيق (الملفات · iCloud) فلا
  // يكتبها المتصفح وحده (قاعدة Apple)؛ فبعد كل تغييرٍ بثوانٍ — وعند الفتح — يظهر «احفظ نسخة»:
  // لمسةٌ تحفظ الملف جاهزاً. وبه تُسترجع البيانات إن حُذفت الأيقونة أو تغيّر الجوال.
  const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* */ } return null; };
  const isWeb = () => !B.native;
  const webDirty = () => +(ls("webChangedAt") || 0) > Math.max(+(ls("webBackupAt") || 0), +(ls("webBarHidden") || 0));
  let bkTimer = null, bkBar = null, bkFile = null;
  function markWebChange() {
    if (!isWeb()) return;
    ls("webChangedAt", String(Date.now()));
    clearTimeout(bkTimer);
    bkTimer = setTimeout(showBackupBar, 2500);
  }
  function hideBackupBar() { if (bkBar) { bkBar.remove(); bkBar = null; } }
  async function showBackupBar() {
    if (!isWeb() || !webDirty() || !AD_SCREENS.has(parse().parts[0] || "home")) return;
    const s = st();
    if (s.shops.length + s.invoices.length + s.vouchers.length === 0) return;
    // الملف جاهزٌ قبل اللمس: المشاركة في الآيفون تُطلب في اللمسة نفسها
    const text = JSON.stringify(D.toBackup(s, await S.allPhotos()));
    const name = `AUR-${D.today()}.json`;
    bkFile = { name, text, file: typeof File === "function" ? new File([text], name, { type: "application/json" }) : null };
    if (bkBar) return;
    bkBar = h("div", { class: "note-bar info web-bk" },
      ico("cloud", 20),
      h("span", { class: "grow small" }, T("احفظ نسخةً من بياناتك في «الملفات» (iCloud) — لمسةٌ واحدة")),
      h("button", { class: "btn sm", onclick: () => webBackupNow() }, ico("save", 16), T("حفظ")),
      h("button", { class: "x", "aria-label": T("لاحقاً"), onclick: () => { ls("webBarHidden", String(Date.now())); hideBackupBar(); } }, ico("x", 16)));
    document.body.append(bkBar);
  }
  function webBackupNow() {
    const f = bkFile;
    if (!f) return;
    const done = () => { ls("webBackupAt", String(Date.now())); hideBackupBar(); toast(T("حُفظت النسخة")); };
    try {
      if (f.file && navigator.canShare && navigator.canShare({ files: [f.file] })) {
        navigator.share({ files: [f.file], title: T("ÀUR — نسخة احتياطية") }).then(done).catch((e) => {
          if (!e || e.name !== "AbortError") { B.saveFile(f.name, f.text); done(); }
        });
        return;
      }
    } catch (e) { /* التنزيل بدلاً منها */ }
    B.saveFile(f.name, f.text);
    done();
  }
  // استرجاعٌ من ملف (أول فتحٍ على جوالٍ جديد، أو بعد حذف الأيقونة)
  function pickRestoreFile() {
    const inp = h("input", { type: "file", accept: ".json,application/json", style: { display: "none" } });
    inp.addEventListener("change", async () => {
      const f = inp.files && inp.files[0];
      inp.remove();
      if (!f) return;
      try { if (await restoreText(await f.text(), f.name)) { ls("webBackupAt", String(Date.now())); route(); } } catch (e) { err(e); }
    });
    document.body.append(inp);
    inp.click();
  }
  const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = () => navigator.standalone === true || (window.matchMedia && matchMedia("(display-mode: standalone)").matches);
  // يعمل بلا إنترنت، وتحديثٌ جديد ينتظر «حدّث الآن»
  function webSetup() {
    if (!isWeb()) return;
    if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
    if (!("serviceWorker" in navigator) || !(location.protocol === "https:" || location.hostname === "localhost")) return;
    const hadController = !!navigator.serviceWorker.controller;
    let reloading = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController && !reloading) { reloading = true; location.reload(); }
    });
    // يُراقَب التسجيل ولو فُتح التطبيق بلا إنترنت (يفشل التسجيل حينها فيُؤخذ القائم)
    const watch = (reg) => {
      if (!reg || reg.__aur) return;
      reg.__aur = true;
      const waiting = () => { if (reg.waiting && navigator.serviceWorker.controller) { webWaiting = reg.waiting; maybeUpdatePop(); } };
      waiting();
      reg.addEventListener("updatefound", () => {
        const w = reg.installing;
        if (w) w.addEventListener("statechange", () => { if (w.state === "installed") waiting(); });
      });
    };
    const attach = () => navigator.serviceWorker.register("sw.js").then(watch)
      .catch(() => navigator.serviceWorker.getRegistration().then(watch).catch(() => {}));
    attach();
    window.addEventListener("online", attach);
    // عند العودة إلى التطبيق: هل نُشر إصدارٌ جديد؟
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      navigator.serviceWorker.getRegistration().then((r) => { watch(r); if (r) r.update().catch(() => {}); }).catch(() => {});
    });
  }
  let webWaiting = null;

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
      bar.appendChild(h("button", { class: "icon-btn", "aria-label": T("رجوع"),
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
    return h("span", { class: "badge" + (isRetKind(kind) ? " ret" : ""), text: T(D.KIND_LABEL[kind]) });
  }

  // وزن المستند بعيار حسابه (العميل/المصنع) — والوحدة تذكر العيار إن خالف عيار المجاميع
  const unitK = (k) => (k === vk() ? T("جم") : T("جم ع{0}", k));
  function docSummary(d) {
    const k = pk(D.shopById(st(), d.shopId));
    if (isInvKind(d.kind)) return T("{0} {1} · أجور {2}", gw(d.totalW18, k), unitK(k), f2(d.grand));
    const parts = [];
    if (d.gold18) parts.push(`${gw(d.gold18, k)} ${unitK(k)}`);
    if (d.cash) parts.push(T("{0} ريال", f2(d.cash)));
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
  function photoThumb(id, cls, onTap) {
    if (!id) return null;
    const img = h("img", { class: "thumb" + (cls ? " " + cls : ""), alt: T("صورة الطقم") });
    photoData(id).then((d) => { if (d) img.src = d; else img.remove(); });
    img.addEventListener("click", (e) => { e.stopPropagation(); if (onTap) onTap(); else showPhoto(id); });
    return img;
  }
  async function showPhoto(id) {
    const d = await photoData(id);
    if (d) await sheet((box) => box.append(h("img", { src: d, class: "photo-full", alt: T("صورة الطقم") })));
  }
  // صور الطقم أو الفاتورة: كل صورةٍ وحدها كاملةً، بعضها تحت بعض — واللمس يكبّرها
  // `items`: [{id, cap}]
  function photosSheet(items, title) {
    if (!items.length) return Promise.resolve();
    return sheet((box) => {
      box.append(h("h3", null, ico("image", 20), " ", title || T("الصور")));
      items.forEach((p, i) => box.append(photoFig(p.id, p.cap, i, items.length)));
    });
  }
  function photoFig(id, cap, i, n) {
    const img = h("img", { class: "photo-full", alt: cap || T("صورة الطقم") });
    const fig = h("figure", { class: "photo-fig", onclick: () => showPhoto(id) }, img,
      h("figcaption", { class: "muted small" }, (cap ? cap + " · " : "") + (n > 1 ? T("صورة {0} من {1}", i + 1, n) : T("صورة الطقم"))));
    photoData(id).then((d) => { if (d) img.src = d; else fig.remove(); });
    return fig;
  }
  // أول صور السطر مصغّرةً، وعليها عدد الباقي — واللمس يعرضها كلها
  function lineThumb(li, cls) {
    const ids = D.linePhotos(li);
    if (!ids.length) return null;
    const all = () => photosSheet(ids.map((id) => ({ id, cap: li.wo || "" })), li.wo ? T("صور الطقم {0}", li.wo) : T("صور الطقم"));
    return h("span", { class: "thumb-wrap", onclick: (e) => { e.stopPropagation(); all(); } },
      photoThumb(ids[0], cls, all), ids.length > 1 ? h("span", { class: "thumb-n" }, `+${ids.length - 1}`) : null);
  }
  // من أين جاء الطقم الذي معي، ومتى — نصّاً، أو عناصرَ لا ينكسر فيها التاريخ
  const pieceOrigin = (p) => (p.fromKind === "opening" ? T("من الرصيد الافتتاحي")
    : T("{0} «{1}»", p.fromKind === "purchase" ? T("من مصنع") : T("مرتجع من"), p.party ? p.party.name : "—"));
  function pieceFrom(p) {
    return `${pieceOrigin(p)}${p.date ? " · " + dmy(p.date) : ""}`;
  }
  function pieceFromEl(p, pre) {
    return [`${pre || ""}${pieceOrigin(p)}${p.date ? " · " : ""}`,
      p.date ? h("span", { class: "nowrap", dir: "ltr" }, dmy(p.date)) : null];
  }
  function piecePhotos(p) {
    const ids = D.linePhotos(p.line);
    return photosSheet(ids.map((id) => ({ id, cap: p.name || "" })), p.name ? T("صور الطقم {0}", p.name) : T("صور الطقم"));
  }
  // زرّ «معاينة» صور الطقم (ومصغّرته) — لا يختار الطقم، يعرض صوره فقط
  function piecePreview(p) {
    const ids = D.linePhotos(p.line);
    if (!ids.length) return h("span", { class: "muted small no-ph" }, T("بلا صورة"));
    return h("span", { class: "pc-prev" }, lineThumb(p.line, "sm"),
      h("button", { type: "button", class: "btn sm prev-btn", onclick: (e) => { e.stopPropagation(); piecePhotos(p); } },
        ico("image", 16), T("معاينة")));
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
        img.onerror = () => reject(new Error(T("تعذّر فتح الصورة")));
        img.src = fr.result;
      };
      fr.onerror = () => reject(new Error(T("تعذّر قراءة الصورة")));
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
  // بعد الاسترجاع المباشر من ملف «ÀUR» (بلا نافذة مجلد): أندرويد قد يُبقي ملف البيانات مقروءاً للتطبيق
  // ويُخفي صور التثبيت السابق — فإن بقيت صورٌ تذكرها البيانات ولم تُسترجع، يُطلب إذن المجلد مرّةً
  // لقراءتها منه (والبيانات نفسها لا تُستورد ثانيةً)
  async function missingPhotos() {
    const refs = new Set((JSON.stringify(st()).match(/"ph_[\w-]{1,60}"/g) || []).map((s) => s.slice(1, -1)));
    const have = new Set(await S.photoIds());
    return [...refs].filter((id) => !have.has(id));
  }
  function restorePhotosChecked() {
    const off = B.on("photosDone", () => {
      off();
      setTimeout(async () => {
        const miss = await missingPhotos();
        if (!miss.length || B.backupInfo().mode !== "auto") return;
        const ok = await confirmSheet(T("استُرجعت بياناتك ✔\n\nوبقيت {0} صورة للأطقم في ملف «{1}».", miss.length, APP_NAME) +
          T("\nاضغط «استرجاع الصور»، ثم «استخدام هذا المجلد» و«سماح»."), T("استرجاع الصور"));
        if (!ok) return;
        const offR = B.on("restore", (r) => {
          offR();
          if (r.ok) B.restorePhotos(); else if (r.error) err(new Error(r.error));
        });
        B.restoreFromFolder();
      }, 1500);
    });
    B.restorePhotos();
  }
  async function importPhotos(map) {
    let n = 0;
    for (const [id, data] of Object.entries(map || {})) { await S.putPhoto(id, data); n++; }
    return n;
  }

  // ══ الرئيسية: ستّ لوحاتٍ للعمليات، ثم كشف الحساب، ثم عمليات اليوم ══
  function home() {
    const s = st();
    setBar(s.settings.name || APP_NAME, T("حساباتي مع العملاء والمصانع"), { back: false,
      actions: [karatButton(), updateButton()], logo: true });
    setTab("home");
    const v = view();
    const t = D.today();
    const us = B.updateState();
    if (us.available) {
      v.append(h("div", { class: "note-bar info tap", style: { marginBottom: "12px" }, onclick: updateSheet },
        ico("sparkles", 18), T(" تحديث {0} متاح — اضغط للتثبيت (بياناتك تبقى كما هي)", us.published ? us.published.version : "")));
    }
    const hasData = s.invoices.length + s.vouchers.length > 0;
    const last = s.settings.lastBackup;
    if (B.native) {
      if (!B.backupFolder()) {
        v.append(h("div", { class: "note-bar warn tap", style: { marginBottom: "12px" }, onclick: () => go("settings") },
          ico("folder", 18), T(" فعّل الحفظ التلقائي في مجلدٍ على الجوال — فتبقى بياناتك ولو حُذف التطبيق.")));
      }
    } else {
      // نسخة الويب: تثبيتها على الشاشة الرئيسية، والاسترجاع من ملفٍ في أول فتح
      if (!standalone()) {
        v.append(h("div", { class: "note-bar info install-card", style: { marginBottom: "12px" } },
          h("b", null, ico("sparkles", 18), T(" ثبّت {0} على جوالك كتطبيق", APP_NAME)),
          isIOS()
            ? h("ol", { class: "small" },
                h("li", null, T("اضغط زرّ المشاركة "), ico("upload", 15), T(" أسفل سفاري")),
                h("li", null, T("اختر «إضافة إلى الشاشة الرئيسية» ثم «إضافة»")),
                h("li", null, T("افتح {0} من أيقونته — يعمل بلا إنترنت", APP_NAME)))
            : h("div", { class: "small", style: { marginTop: "4px" } }, T("من قائمة المتصفح ⋮ اختر «إضافة إلى الشاشة الرئيسية» أو «تثبيت التطبيق»."))));
      }
      if (!hasData && s.shops.length === 0) {
        v.append(h("div", { class: "note-bar info tap", style: { marginBottom: "12px" }, onclick: pickRestoreFile },
          ico("history", 18), T(" عندك نسخة سابقة من بياناتك؟ اضغط هنا لاسترجاعها من ملف")));
      }
    }
    // اللوحات: العميل يميناً والمصنع يساراً، صفّاً صفّاً
    const tile = (icon, label, hint, to, fac) => h("button", { class: "op-tile" + (fac ? " fac" : ""), onclick: () => go(to) },
      h("span", { class: "op-ic" }, ico(icon, 26)), h("span", { class: "op-t" }, label), h("span", { class: "op-h" }, hint));
    v.append(h("div", { class: "op-grid" },
      tile("receipt", T("بيع للعميل"), T("ذهب · أجور · ماس"), "invoice/new?kind=sale"),
      tile("return", T("مرتجع للعميل"), T("يرجع إلى يدك"), "invoice/new?kind=sale_return"),
      tile("package", T("بضاعة من مصنع"), T("تدخل يدك"), "invoice/new?kind=purchase", true),
      tile("return", T("إرجاع للمصنع"), T("يخرج من يدك"), "invoice/new?kind=purchase_return", true),
      tile("in", T("تحصيل من العميل"), T("ذهب ونقد"), "voucher/new?kind=receipt"),
      tile("out", T("سداد للمصنع"), T("من صناديقك"), "voucher/new?kind=payment", true)));
    // كشف حساب
    v.append(h("button", { class: "wide-tile", onclick: pickPartyThen(null, (id) => go(`statement/${id}`)) },
      h("span", { class: "op-ic" }, ico("book", 24)),
      h("span", { class: "grow" }, h("span", { class: "op-t" }, T("كشف حساب")), h("span", { class: "op-h" }, T("عميل أو مصنع — بالذهب أو بالألماس، ويُرسَل صورة"))),
      ico("chevron", 20, "muted")));
    // بحث عن طقم: باسمه أو وزنه — ومع من هو الآن
    v.append(h("button", { class: "wide-tile search", onclick: () => go("wo") },
      h("span", { class: "op-ic" }, ico("search", 24)),
      h("span", { class: "grow" }, h("span", { class: "op-t" }, T("بحث عن طقم")), h("span", { class: "op-h" }, T("باسمه أو وزنه — ومع من هو الآن"))),
      ico("chevron", 20, "muted")));
    // الأطقم التي معي (1.11): المسمّاة وحدها — عددها ووزنها، ولمسها يعرض كل طقمٍ وصوره
    const hd = D.holdings(s), sk = vk();
    v.append(h("button", { class: "wide-tile sets", onclick: () => piecesSheet(D.holdings(st())) },
      h("span", { class: "op-ic" }, ico("gem", 24)),
      h("span", { class: "grow" }, h("span", { class: "op-t" }, T("الأطقم التي معي ({0})", hd.pieces.length)),
        h("span", { class: "op-h" }, hd.pieces.length ? T("{0} جم عيار {1} — اضغط لترى كل طقم وصوره", gw(hd.setsW18, sk), sk)
          : T("لا أطقم معك الآن — الطقم هو ما سجّلت له اسماً في خانة «الطقم»"))),
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
      h("span", { class: "grow" }, h("span", { class: "op-t" }, T("عمليات اليوم ({0})", todays.length)),
        h("span", { class: "op-h" }, todays.length ? T("مبيعات {0} جم · أجور {1} — اضغط لعرضها ومعاينتها", gw(tw), f2(tg))
          : T("لا عمليات اليوم بعد — اضغط لعرض آخر العمليات"))),
      ico("chevron", 20, "muted")));
    const sp = root.Promo && root.Promo.pick();
    if (sp) v.append(sponsorCard(sp));
  }

  // بطاقة الراعي: مصنعٌ أو مورّدٌ يصل إلى المستخدمين — وتُغلق أسبوعاً بلمسة
  function sponsorCard(p) {
    const open = (url) => B.openUrl(url);
    return h("div", { class: "sponsor" },
      h("div", { class: "spread" }, h("span", { class: "sp-tag" }, T("راعٍ")),
        h("button", { class: "sp-x", "aria-label": T("إخفاء"), onclick: () => { root.Promo.hide(p.id); route(); } }, ico("x", 16))),
      h("div", { class: "sp-t" }, p.title),
      p.text ? h("div", { class: "sp-d" }, p.text) : null,
      h("div", { class: "sp-acts" },
        p.whatsapp ? h("button", { class: "btn sm", onclick: () => open(`https://wa.me/${p.whatsapp}`) }, ico("chat", 16), T("واتساب")) : null,
        p.phone ? h("button", { class: "btn sm ghost", onclick: () => open(`tel:${p.phone}`) }, ico("phone", 16), T("اتصال")) : null,
        p.link ? h("button", { class: "btn sm ghost", onclick: () => open(p.link) }, ico("info", 16), T("التفاصيل")) : null));
  }
  // «أعلن في التطبيق»: تواصلٌ مع صاحب التطبيق
  function advertiseSheet() {
    const c = root.Promo && root.Promo.contact();
    if (!c) return;
    return sheet((box) => {
      box.append(h("h3", null, ico("megaphone", 20), T(" أعلن في التطبيق")),
        h("div", { style: { lineHeight: "1.8", marginBottom: "10px" } }, c.text ||
          T("اعرض مصنعك أو نشاطك لكل مناديب الذهب الذين يستعملون التطبيق: بطاقةٌ في الشاشة الرئيسية باسمك ورقمك.")),
        h("div", { class: "actions" },
          c.whatsapp ? h("button", { class: "btn", onclick: () => B.openUrl(`https://wa.me/${c.whatsapp}`) }, ico("chat", 18), T("واتساب")) : null,
          c.phone ? h("button", { class: "btn ghost", onclick: () => B.openUrl(`tel:${c.phone}`) }, ico("phone", 18), T("اتصال")) : null));
    });
  }

  // ══ عمليات اليوم: كلّ عمليةٍ بزرّ «معاينة» يُظهر مستندها ══
  function todayScreen() {
    const s = st(), t = D.today();
    setBar(T("عمليات اليوم"), dmy(t));
    setTab("home");
    const v = view();
    const all = [...s.invoices, ...s.vouchers]
      .sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : (a.createdAt < b.createdAt ? 1 : -1)));
    const todays = all.filter((d) => d.date === t);
    const item = (d) => {
      const el = docItem(d);
      el.classList.add("op-row");
      el.append(h("button", { class: "btn sm prev-btn", onclick: (e) => { e.stopPropagation(); previewSheet(d); } },
        ico("file", 16), T("معاينة")));
      return el;
    };
    if (todays.length) todays.forEach((d) => v.append(item(d)));
    else v.append(h("div", { class: "empty" }, T("لا عمليات اليوم بعد")));
    const older = all.filter((d) => d.date !== t).slice(0, 20);
    if (older.length) {
      v.append(h("div", { class: "sec-title spread", style: { marginTop: "14px" } }, h("span", null, T("آخر العمليات")),
        h("button", { class: "link", onclick: () => go("log") }, T("السجل كاملاً"))));
      older.forEach((d) => v.append(item(d)));
    }
  }

  // معاينة المستند في نافذةٍ سفلية: الفاتورة كما تُرسَل، ثم صور أطقمها كلُّ
  // صورةٍ وحدها كاملة — وتعديلها · مشاركتها صورةً · طباعتها
  async function previewSheet(d) {
    const s = st();
    const isInv = isInvKind(d.kind);
    let html = isInv ? P.invoiceHtml(s, d, {}) : P.voucherHtml(s, d);
    const frame = previewFrame(html);
    const phs = isInv ? D.docPhotos(d) : [];
    if (phs.length) {
      S.getPhotos(phs.map((p) => p.id)).then((ph) => {
        if (Object.keys(ph).length) { html = P.invoiceHtml(s, d, ph); frame.setHtml(html); }
      });
    }
    const r = await sheet((box, close) => {
      box.append(h("h3", null, `${T(D.KIND_LABEL[d.kind])} ${d.no} — ${shopTitle(d.shopId)}`),
        h("div", { class: "actions doc-acts" },
          h("button", { class: "btn", onclick: () => close("edit") }, ico("edit", 18), T("تعديل")),
          h("button", { class: "btn ghost", onclick: () => B.shareHtmlImage(html, d.no) }, ico("share", 18), T("مشاركة")),
          h("button", { class: "btn ghost", onclick: () => B.printHtml(html, d.no) }, ico("printer", 18), T("طباعة"))),
        frame);
      if (phs.length) {
        box.append(h("div", { class: "sec-title", style: { marginTop: "12px" } }, ico("image", 18), T("صور الأطقم ({0})", phs.length)));
        phs.forEach((p, i) => box.append(photoFig(p.id, p.wo || T("طقم {0}", p.n), i, phs.length)));
      }
    });
    if (r === "edit") go(`${isInv ? "invoice" : "voucher"}/edit/${d.id}`);
  }

  // أيقونة خطّية من مجموعة التطبيق (icons.js) — أو النصّ كما هو
  function ico(name, size, cls) {
    return root.ICON_NAMES && root.ICON_NAMES.includes(name) ? root.Icon(name, size, cls)
      : h("span", { class: "ic" }, name);
  }
  function quickBtn(icon, label, fn) {
    return h("button", { onclick: fn }, h("span", { class: "i" }, ico(icon, 24)), h("span", null, label));
  }

  // ══ الحسابات: العملاء والمصانع ══
  // `type`: «shop» أو «factory» — أو null لكل الحسابات
  function partyItems(type) {
    const s = st();
    const bals = D.allBalances(s);
    return s.shops.filter((x) => !type || (type === "factory") === D.isFactory(x))
      .sort((a, b) => (D.isFactory(a) - D.isFactory(b)) || a.name.localeCompare(b.name, "ar"))
      .map((x) => {
        const fac = D.isFactory(x), k = pk(x);
        return { id: x.id, title: x.name,
          sub: (type ? "" : fac ? T("مصنع · ") : T("عميل · ")) +
            T("ذهب {0} · نقد {1}", balText(G.g(bals[x.id].gold18, k), T("جم عيار {0}", k), fac), balText(bals[x.id].cash, T("ريال"), fac)) };
      });
  }
  function pickPartyThen(type, fn) {
    return async () => {
      const fac = type === "factory";
      const it = await pickSheet(type ? T("اختر {0}", fac ? T("المصنع") : T("العميل")) : T("اختر الحساب"), partyItems(type),
        { addLabel: type ? (fac ? T("+ مصنع جديد") : T("+ عميل جديد")) : null, empty: T("لا حسابات بعد") });
      if (!it) return;
      if (it.add) { go(fac ? "shop-form?type=factory" : "shop-form"); return; }
      fn(it.id);
    };
  }

  function customers(q) {
    const s = st();
    const mode = q.view === "board" ? "board" : q.view === "factories" ? "factories" : "shops";
    const fac = mode === "factories";
    setBar(T("الحسابات"), T("{0} عميل · {1} مصنع", D.shopsOnly(s).length, D.factoriesOnly(s).length), { back: false,
      actions: mode === "board" ? [] : [h("button", { class: "icon-btn", "aria-label": fac ? T("مصنع جديد") : T("عميل جديد"),
        onclick: () => go(fac ? "shop-form?type=factory" : "shop-form") }, ico("plus", 20), h("span", null, fac ? T("مصنع") : T("عميل")))] });
    setTab("customers");
    const v = view();
    v.append(h("div", { class: "seg", style: { marginBottom: "10px" } },
      h("button", { class: mode === "shops" ? "on" : "", onclick: () => replace("customers") }, T("العملاء")),
      h("button", { class: fac ? "on" : "", onclick: () => replace("customers?view=factories") }, T("المصانع")),
      h("button", { class: mode === "board" ? "on" : "", onclick: () => replace("customers?view=board") }, T("المبيعات والتحصيل"))));
    if (mode === "board") return boardView(v, q);
    partyList(v, fac);
  }

  function partyList(v, fac) {
    const q = h("input", { class: "in", type: "search", placeholder: fac ? T("ابحث باسم المصنع أو الجوال…") : T("ابحث باسم العميل أو الجوال…") });
    const sortSeg = h("div", { class: "chips", style: { margin: "8px 0" } });
    let sort = "name";
    const list = h("div");
    const render = () => {
      const s = st();
      const bals = D.allBalances(s);
      const t = q.value.trim();
      const all = fac ? D.factoriesOnly(s) : D.shopsOnly(s);
      const arr = all.filter((x) => !t || x.name.includes(t) || (x.phone || "").includes(t));
      // «الأكثر»: للعميل أكبر ما عليه، وللمصنع أكبر ما عليّ له (السالب) — بمكافئ 18 فالأعيرة تُقارن
      const sg = fac ? -1 : 1;
      if (sort === "name") arr.sort((a, b) => a.name.localeCompare(b.name, "ar"));
      if (sort === "gold") arr.sort((a, b) => sg * (bals[b.id].gold18 - bals[a.id].gold18));
      if (sort === "cash") arr.sort((a, b) => sg * (bals[b.id].cash - bals[a.id].cash));
      list.innerHTML = "";
      if (!arr.length) {
        list.append(h("div", { class: "empty" }, all.length ? T("لا نتائج") : fac
          ? T("لا مصانع بعد — اضغط «+ مصنع» لإضافة المصنع الذي تأخذ منه البضاعة وتدفع له.")
          : T("لا عملاء بعد — اضغط «+ عميل» لإضافة أول عميل.")));
      }
      for (const x of arr) {
        list.append(h("div", { class: "list-item", onclick: () => go(`shop/${x.id}`) },
          h("span", { class: "avatar" + (fac ? " fac" : "") }, fac ? ico("package", 20) : (x.name.trim()[0] || T("؟"))),
          h("div", { class: "grow" }, h("div", { class: "t", text: x.name }),
            x.phone ? h("div", { class: "muted small", dir: "ltr", style: { textAlign: root.I18N.start }, text: x.phone }) : null),
          h("div", { style: { textAlign: root.I18N.end }, class: "small num" },
            h("div", null, goldBal(bals[x.id].gold18, fac, pk(x))), h("div", null, cashBal(bals[x.id].cash, fac)))));
      }
    };
    const chips = fac ? [["name", T("بالاسم")], ["gold", T("الأكثر ذهباً عليّ")], ["cash", T("الأكثر نقداً عليّ")]]
      : [["name", T("بالاسم")], ["gold", T("الأكثر ذهباً عليه")], ["cash", T("الأكثر نقداً عليه")]];
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
    const k = pk(shop);
    setBar(shop.name, (fac ? T("مصنع") : T("عميل")) + T(" · عيار {0}", k) + (shop.phone ? " · " + shop.phone : ""), {
      actions: [h("button", { class: "icon-btn", "aria-label": T("تعديل"), onclick: () => go(`shop-form/${id}`) }, ico("edit", 20))] });
    setTab("customers");
    const b = D.balance(s, id);
    const v = view();
    v.append(h("div", { class: "kpis" },
      h("div", { class: "kpi" }, h("b", null, T("رصيد الذهب (عيار {0})", k)), h("div", { class: "v num" }, goldBal(b.gold18, fac, k))),
      h("div", { class: "kpi" }, h("b", null, fac ? T("رصيد النقد والأجور") : T("رصيد الأجور والنقد")), h("div", { class: "v num" }, cashBal(b.cash, fac)))));
    if (shop.agreedWage18) {
      v.append(h("div", { class: "note-bar info", style: { marginBottom: "12px" } },
        T("{0}: {1} ريال لكل جرام عيار {2}", fac ? T("أجرة المصنع المتفق عليها") : T("الأجرة المتفق عليها"), f2(G.rate(shop.agreedWage18, k)), k)));
    }
    const contact = shop.phone ? quickBtn("phone", T("اتصال"), () => B.dial(shop.phone))
      : quickBtn("edit", fac ? T("تعديل المصنع") : T("تعديل العميل"), () => go(`shop-form/${id}`));
    v.append(h("div", { class: "quick" }, ...(fac ? [
      quickBtn("out", T("سداد للمصنع"), () => go(`voucher/new?kind=payment&shop=${id}`)),
      quickBtn("package", T("بضاعة من المصنع"), () => go(`invoice/new?kind=purchase&shop=${id}`)),
      quickBtn("return", T("إرجاع للمصنع"), () => go(`invoice/new?kind=purchase_return&shop=${id}`)),
      quickBtn("book", T("كشف الحساب"), () => go(`statement/${id}`)), contact,
    ] : [
      quickBtn("receipt", T("فاتورة بيع"), () => go(`invoice/new?kind=sale&shop=${id}`)),
      quickBtn("return", T("مرتجع"), () => go(`invoice/new?kind=sale_return&shop=${id}`)),
      quickBtn("in", T("تحصيل"), () => go(`voucher/new?kind=receipt&shop=${id}`)),
      quickBtn("book", T("كشف الحساب"), () => go(`statement/${id}`)), contact,
    ])));
    if (shop.notes) v.append(h("div", { class: "card small" }, shop.notes));
    const docs = D.docsOf(s, id).reverse();
    v.append(h("div", { class: "sec-title" }, T("العمليات ({0})", docs.length)));
    if (!docs.length) v.append(h("div", { class: "empty" }, fac ? T("لا عمليات مع هذا المصنع بعد") : T("لا عمليات لهذا العميل بعد")));
    docs.slice(0, 60).forEach((d) => v.append(docItem(d)));
  }

  function shopForm(id, q) {
    const s = st();
    const shop = id ? D.shopById(s, id) : null;
    const fac = shop ? D.isFactory(shop) : (q && q.type === "factory");
    const word = fac ? T("المصنع") : T("العميل");
    setBar(shop ? T("تعديل {0}", word) : fac ? T("مصنع جديد") : T("عميل جديد"), "", { noTabs: true });
    // عيار الحساب: لكل عميلٍ ومصنعٍ عياره — به يُعرض رصيده وكشفه، ويبدأ به كل سطرٍ في فواتيره
    let k = shop ? ek(shop) : vk();
    const karatSel = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: T("عيار {0}", x) })));
    karatSel.value = String(k);
    const name = h("input", { class: "in", value: shop ? shop.name : "", placeholder: T("اسم {0}", word), enterkeyhint: "next" });
    const phone = h("input", { class: "in", value: shop ? shop.phone : "", inputmode: "tel", dir: "ltr", placeholder: "05xxxxxxxx" });
    const notes = h("textarea", { class: "in", rows: 2, placeholder: T("ملاحظات (اختياري)") });
    notes.value = shop ? shop.notes : "";
    const wage = numInput({ value: shop && shop.agreedWage18 ? G.rate(shop.agreedWage18, k) : 0 });
    const og = shop ? shop.openGold18 : 0, oc = shop ? shop.openCash : 0;
    const goldIn = numInput({ value: Math.abs(G.g(og, k)) });
    const cashIn = numInput({ value: Math.abs(oc) });
    const wageF = field("", wage), goldF = field("", goldIn);
    const labels = () => {
      wageF.firstChild.textContent = fac ? T("أجرة المصنع المتفق عليها (ريال لكل جرام عيار {0}) — تُملأ تلقائياً في البضاعة", k)
        : T("الأجرة المتفق عليها (ريال لكل جرام عيار {0}) — تُملأ تلقائياً في الفواتير", k);
      goldF.firstChild.textContent = T("ذهب (جم عيار {0})", k);
    };
    labels();
    // القيمة المحفوظة بمكافئ 18 ما دام الرقم المعروض لم يُمسّ — فتبديل العيار ذهاباً وإياباً لا يُقرّب شيئاً
    const exact = (el, v18, toView, toStore) => {
      let seen = el.value;
      return {
        v18: () => (el.value === seen ? v18 : toStore(el.getVal(), k)),
        to: (nk) => { const x = (el.value === seen ? v18 : toStore(el.getVal(), k)); v18 = x; el.setVal(toView(x, nk)); seen = el.value; },
      };
    };
    const goldX = exact(goldIn, Math.abs(og), G.g, G.store);
    const wageX = exact(wage, shop ? shop.agreedWage18 || 0 : 0, G.rate, G.rateStore);
    // تغيير العيار لا يغيّر ما بينكما: الوزن والأجرة المكتوبان يتحوّلان إلى العيار الجديد
    karatSel.addEventListener("change", () => {
      const nk = parseInt(karatSel.value, 10);
      if ([goldIn.getVal(), wage.getVal()].some((x) => !isFinite(x))) { karatSel.value = String(k); err(new Error(T("صحّح الرقم أولاً"))); return; }
      goldX.to(nk); wageX.to(nk);
      k = nk;
      labels();
    });
    // الاتجاه: للعميل «عليه» موجب و«له» سالب — وللمصنع «عليّ» سالب و«لي» موجب
    const segOf = (val) => {
      let on = fac ? (val > 0 ? "for" : "on") : (val < 0 ? "for" : "on");
      const seg = h("div", { class: "seg" });
      const mk = (key, label) => h("button", { type: "button", class: key === on ? "on" : "", onclick: (e) => {
        on = key;
        for (const c of seg.children) c.classList.remove("on");
        e.target.classList.add("on");
      } }, label);
      seg.append(mk("on", fac ? T("عليّ له") : T("عليه")), mk("for", fac ? T("لي عنده") : T("له")));
      seg.sign = () => (fac ? (on === "on" ? -1 : 1) : (on === "on" ? 1 : -1));
      return seg;
    };
    const gSeg = segOf(og), cSeg = segOf(oc);
    const date = h("input", { class: "in", type: "date", value: shop ? shop.openDate : D.today() });
    const v = view();
    v.append(
      h("div", { class: "card" }, h("h2", null, fac ? T("بيانات المصنع") : T("بيانات العميل")),
        field(T("اسم {0}", word), name), h("div", { style: { height: "8px" } }),
        field(T("الجوال"), phone), h("div", { style: { height: "8px" } }),
        field(T("عيار الحساب"), karatSel),
        h("div", { class: "muted small", style: { margin: "4px 0 8px" } },
          fac ? T("به يبدأ كل سطرٍ في بضاعته وسداده — والعرض كله بالعيار المختار أعلى الرئيسية.") : T("به يبدأ كل سطرٍ في فواتيره وتحصيله — والعرض كله بالعيار المختار أعلى الرئيسية.")),
        wageF,
        h("div", { style: { height: "8px" } }), field(T("ملاحظات"), notes)),
      h("div", { class: "card" }, h("h2", null, fac ? T("دَينٌ سابق (اختياري)") : T("رصيد افتتاحي (اختياري)")),
        h("div", { class: "muted small", style: { marginBottom: "8px" } },
          fac ? T("ما كان بينك وبين المصنع قبل أول عملية في التطبيق.") : T("ما كان بينك وبين العميل قبل أول فاتورة في التطبيق.")),
        h("div", { class: "grid2" }, goldF, field(T("الاتجاه"), gSeg),
          field(T("نقد (ريال)"), cashIn), field(T("الاتجاه"), cSeg), field(T("بتاريخ"), date, "span2"))));
    const save = async () => {
      try {
        const gv = goldIn.getVal(), cv = cashIn.getVal(), wv = wage.getVal();
        if ([gv, cv, wv].some((x) => !isFinite(x))) throw new Error(T("رقمٌ غير صحيح في أحد الحقول"));
        const rec = D.saveShop(s, {
          id: shop ? shop.id : null, createdAt: shop ? shop.createdAt : null, type: fac ? "factory" : "shop",
          name: name.value, phone: phone.value, notes: notes.value,
          agreedWage18: wv ? wageX.v18() : 0,
          openGold18: gv ? gSeg.sign() * goldX.v18() : 0,
          openCash: cSeg.sign() * cv, openDate: date.value || D.today(), karat: k,
        });
        if (await persist([["shops", "put", rec]])) {
          toast(fac ? T("حُفظ المصنع") : T("حُفظ العميل"));
          if (shop) history.back(); else replace(`shop/${rec.id}`);
        }
      } catch (e) { err(e); }
    };
    const del = async () => {
      try {
        if (!(await confirmSheet(T("حذف {0} «{1}»؟", word, shop.name), T("حذف"), true))) return;
        D.deleteShop(s, shop.id);
        if (await persist([["shops", "del", shop.id]])) { toast(T("حُذف {0}", word)); replace(fac ? "customers?view=factories" : "customers"); }
      } catch (e) { err(e); }
    };
    v.append(h("div", { class: "footer-bar" },
      h("button", { class: "btn", onclick: save }, T("حفظ")),
      shop ? h("button", { class: "btn ghost", onclick: del }, T("حذف")) : null));
  }

  // ══ الفاتورة: بيع · مرتجع (العميل) — بضاعة من مصنع · إرجاع للمصنع ══
  const INV_TITLE = { sale: T("فاتورة بيع"), sale_return: T("مرتجع"), purchase: T("بضاعة من مصنع"), purchase_return: T("إرجاع للمصنع") };

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
          setTimeout(() => toast(T("استُعيدت فاتورةٌ لم تُحفظ — أكملها أو احذف أسطرها")), 300);
        }
      } catch (e) { /* لا مسودة */ }
    }
    const editing = mode === "edit";
    const forFactory = () => D.FACTORY_KINDS.includes(inv.kind);
    const isOut = () => D.OUT_KINDS.includes(inv.kind);
    const partyWord = () => (forFactory() ? T("المصنع") : T("العميل"));
    const party = () => D.shopById(s, inv.shopId);
    // عيار الحساب: إجماليات الفاتورة والرصيد بعدها بعيار العميل/المصنع، ومنه يبدأ كل سطر
    const partyK = () => ek(party());
    const ent = { karat: partyK(), stoneRate: s.settings.stoneRate, regManual: false, fromCard: false, shadow: null,
      editIdx: null, lastWo: "", src: "", lid: null, smallV: 0, afterV: 0, exact18: null, photos: [] };

    // ── الرأس: النوع · الحساب · التاريخ ──
    const header = () => {
      const sh = party();
      docHeader(INV_TITLE[inv.kind] + (editing ? ` ${inv.no}` : ""), sh ? sh.name : "", T("اختر {0}", partyWord()),
        inv.date, pickParty, (d) => { inv.date = d; header(); refresh(); });
    };
    async function pickParty() {
      const fac = forFactory();
      const it = await pickSheet(T("اختر {0}", partyWord()), partyItems(fac ? "factory" : "shop"),
        { addLabel: fac ? T("+ مصنع جديد") : T("+ عميل جديد"), empty: fac ? T("لا مصانع بعد") : T("لا عملاء بعد") });
      if (!it) return;
      if (it.add) { saveDraft(); go(fac ? "shop-form?type=factory" : "shop-form"); return; }
      inv.shopId = it.id;
      header();
      // خانات الطقم فارغة؟ فعيارها عيار الحساب المختار
      if (!pendingEntry() && !(gold.getVal() > 0)) { ent.karat = partyK(); karatSel.value = String(ent.karat); }
      ent.lastWo = "";
      woIn.dispatchEvent(new Event("change"));
      refresh();
      setTimeout(() => woIn.focus(), 60);
    }
    const v = view();

    // ── الطقم: الاسم اختياري؛ ويُحفظ ذهبٌ أو ماسٌ أو أجورٌ وحدها ──
    const woIn = h("input", { class: "in", placeholder: T("اختياري"), autocomplete: "off", dir: "auto",
      enterkeyhint: "next", inputmode: "text" });
    const gold = numInput(), big = numInput(), dia = numInput(), stand = numInput();
    const reg = numInput({ hl: true });
    const wagesIn = numInput({ enter: "done" });
    const karatSel = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: T("عيار {0}", x) })));
    karatSel.value = String(ent.karat);
    const notice = h("div");
    const addBtn = h("button", { type: "button", class: "btn grow" }, T("+ إضافة"));
    const cancelEdit = h("button", { type: "button", class: "btn ghost", style: { display: "none" } }, T("إلغاء التعديل"));
    const pickBtn = h("button", { type: "button", class: "btn ghost block sm", style: { marginBottom: "10px" } });
    // صور الطقم: من الكاميرا أو المعرض، واحدةً أو أكثر في الخانة نفسها —
    // تُحفظ وحدها ويُربط بها السطر. الزرّ في خانته، والصور تحت الخانات
    const photoBox = h("div", { class: "photo-add" });
    const photoStrip = h("div", { class: "photo-pick" });
    const photoIn = h("input", { type: "file", accept: "image/*", style: { display: "none" } });
    photoIn.multiple = true;
    function renderPhoto() {
      photoBox.innerHTML = "";
      photoStrip.innerHTML = "";
      const n = ent.photos.length;
      if (n < D.MAX_PHOTOS) {
        photoBox.append(h("button", { type: "button", class: "btn ghost block photo-btn", onclick: () => photoIn.click() },
          ico("image", 20), n ? T("+ صورة ({0})", n) : T("صورة")));
      } else photoBox.append(h("div", { class: "muted small" }, T("{0} صور", n)));
      photoStrip.style.display = n ? "" : "none";
      ent.photos.forEach((id, i) => {
        photoStrip.append(h("span", { class: "ph-item" },
          photoThumb(id, "lg", () => photosSheet(ent.photos.map((x) => ({ id: x, cap: woIn.value.trim() })), T("صور الطقم"))),
          h("button", { type: "button", class: "ph-x", "aria-label": T("إزالة الصورة {0}", i + 1),
            onclick: () => { ent.photos = ent.photos.filter((x) => x !== id); renderPhoto(); } }, ico("x", 14))));
      });
    }
    photoIn.addEventListener("change", async () => {
      const files = [...(photoIn.files || [])];
      photoIn.value = "";
      for (const f of files) {
        if (ent.photos.length >= D.MAX_PHOTOS) { toast(T("حتى {0} صور للطقم", D.MAX_PHOTOS)); break; }
        try { ent.photos.push(await savePhotoData(await shrinkImage(f))); } catch (e) { err(e); }
      }
      renderPhoto();
    });
    // للتجربة الآلية على الجهاز: صورةٌ جاهزة تُربط بالسطر كما لو اختيرت
    App.attachPhotoData = async (dataUrl) => {
      const id = await savePhotoData(dataUrl);
      ent.photos.push(id); renderPhoto(); return id;
    };

    // الأجور المتفق عليها (بالجرام) تُقترح مبلغاً للوزن المكتوب — والمكتوب يُعتمد
    const agreedWages = () => {
      const sh = party(), r = reg.getVal() || 0;
      return sh && sh.agreedWage18 && r > 0 ? G.totalWages(sh.agreedWage18, G.store(r, ent.karat)) : null;
    };
    const hintWages = () => {
      const a = agreedWages();
      wagesIn.placeholder = a === null ? "" : T("تلقائي {0}", f2(a));
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
      field(T("الذهب"), gold), field(T("أحجار/فصوص"), big), field(T("الوزن القائم"), stand, "span2"));
    const detailsBtn = h("button", { type: "button", class: "link" });
    const renderDetails = () => {
      detailsBox.style.display = details ? "" : "none";
      detailsBtn.textContent = details ? T("إخفاء تفصيل الوزن") : T("تفصيل الوزن (ذهب · أحجار/فصوص) — اختياري");
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
      ent.photos = (e.photos || []).slice();
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
      // عند تعديل فاتورةٍ محفوظة: ما خرج بها يعود متاحاً (فيُحذف سطره ويُضاف من جديد)
      const base = editing && inv.id ? Object.assign({}, s, { invoices: s.invoices.filter((x) => x.id !== inv.id) }) : s;
      return D.holdings(base).pieces.filter((p) => !used.has(p.id) && !(p.name && names.has(p.name)) &&
        (inv.kind === "sale" || (p.fromKind === "purchase" && (!inv.shopId || p.party && p.party.id === inv.shopId))));
    }
    function renderPickBtn() {
      const n = ent.editIdx === null ? availablePieces().length : 0;
      pickBtn.style.display = n ? "" : "none";
      pickBtn.innerHTML = "";
      pickBtn.append(ico("package", 18), T("اختر من الطقوم التي معي ({0})", n));
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
      setNotice("info", T("{0} — {1} جم عيار {2} · {3}", p.name ? T("الطقم ") + p.name : T("طقمٌ بلا اسم"), gw(p.w18, p.karat), p.karat, pieceFrom(p)));
      setTimeout(() => (wagesIn.isBlank() ? wagesIn : reg).focus(), 50);
    }
    pickBtn.addEventListener("click", async () => {
      const pcs = availablePieces();
      // لكل طقمٍ زرّ «معاينة» يعرض صوره دون أن يختاره — واللمس على الطقم يختاره
      const it = await pickSheet(T("الطقوم التي معي"), pcs.map((p) => ({ id: p.id,
        title: T("{0} · {1} جم عيار {2}", p.name || T("طقمٌ بلا اسم"), gw(p.w18, p.karat), p.karat), sub: pieceFrom(p), subNode: pieceFromEl(p),
        badge: piecePreview(p) })),
        { empty: T("لا طقم معك") });
      if (it) usePiece(pcs.find((p) => p.id === it.id));
    });

    // اسم الطقم: آخر حركةٍ له تقول أين هو، ومنها يُعبّأ وزنه
    woIn.addEventListener("change", () => {
      const no = woIn.value.trim();
      if (!no) { if (!ent.src) setNotice(); ent.lastWo = ""; return; }
      if (no === ent.lastWo) return;
      ent.lastWo = no; ent.src = "";
      const last = D.woLast(s, no, inv.id);
      // طقمٌ من الرصيد الافتتاحي (لا حركة له بعد): يُعبّأ منه كما لو اختير من «الطقوم التي معي»
      const op = !last && isOut() && ent.editIdx === null ? availablePieces().find((p) => p.fromKind === "opening" && p.name === no) : null;
      if (op) { usePiece(op); return; }
      if (!last) {
        setNotice("info", T("طقمٌ جديد باسم {0}.", no));
        ent.fromCard = false;
        return;
      }
      fillFrom(last.line);
      if (D.FACTORY_KINDS.includes(last.kind) === forFactory()) offerWages(last.line);
      const lastIn = D.IN_KINDS.includes(last.kind);
      const who = last.shop ? last.shop.name : "—";
      const what = `${T(D.KIND_LABEL[last.kind])} ${last.inv.no}`;
      const at = T("بتاريخ {0}", dmy(last.date));
      if (isOut()) {
        if (lastIn) setNotice("info", T("الطقم {0} معك — {1} من «{2}» {3}. عُبّئ وزنه.", no, what, who, at));
        else setNotice("warn", T("⚠ الطقم {0} خرج من يدك: {1} لـ«{2}» {3}.", no, what, who, at));
      } else if (!lastIn) {
        const days = D.daysBetween(last.date, inv.date || D.today());
        let txt = T("الطقم {0}: {1} لـ«{2}» {3}", no, what, who, at) + (days > 0 ? T(" — منذ {0} يوماً.", days) : ".") + T(" عُبّئ وزنه.");
        const other = inv.kind === "sale_return" && inv.shopId && last.shop && last.shop.id !== inv.shopId;
        if (other) txt += T("\n⚠ بِيع لـ«{0}» لا للعميل المختار.", who);
        setNotice(other ? "warn" : "info", txt);
      } else {
        setNotice("warn", T("⚠ الطقم {0} معك أصلاً — {1} من «{2}» {3}.", no, what, who, at));
      }
    });

    function clearEntry() {
      woIn.value = "";
      for (const el of [gold, big, dia, reg, stand, wagesIn]) el.setVal(0);
      ent.regManual = false; ent.fromCard = false; ent.shadow = null;
      ent.stoneRate = s.settings.stoneRate; ent.editIdx = null; ent.lastWo = "";
      ent.exact18 = null; ent.src = ""; ent.lid = null; ent.smallV = 0; ent.afterV = 0;
      ent.photos = []; renderPhoto();
      addBtn.textContent = T("+ إضافة"); cancelEdit.style.display = "none";
      setNotice(); hintWages(); renderPickBtn();
    }

    // يُضاف الطقم المكتوب (أو يُحفظ تعديل السطر) — ويُرجع هل أُضيف.
    // `quiet`: من «حفظ الفاتورة» — فلا تُفتح لوحة المفاتيح بعده
    async function addLine(opt) {
      const quiet = !!(opt && opt.quiet);
      try {
        const no = woIn.value.trim();
        const vals = { gold: gold.getVal(), big: big.getVal(), diamond: dia.getVal(), reg: reg.getVal(),
          standing: stand.getVal(), wages: wagesIn.getVal() };
        for (const [key, x] of Object.entries(vals)) {
          if (!isFinite(x)) throw new Error(T("رقمٌ غير صحيح في خانة ") + ({ gold: T("الذهب"), big: T("أحجار/فصوص"),
            diamond: T("الماس"), reg: T("الوزن"), standing: T("الوزن القائم"), wages: T("الأجور") })[key]);
        }
        const regV = vals.reg > 0 ? vals.reg : 0, diaV = vals.diamond > 0 ? vals.diamond : 0;
        let wagesV = wagesIn.isBlank() ? agreedWages() : Math.max(0, vals.wages);
        if (wagesV === null) wagesV = 0;
        if (!(regV > 0) && !(diaV > 0) && !(wagesV > 0)) {
          reg.focus();
          throw new Error(T("اكتب الوزن، أو الأجور، أو الماس — ويكفي واحدٌ منها"));
        }
        if (no && (regV > 0 || diaV > 0)) {
          const dupAt = inv.lines.findIndex((l, i) => !l.wageOnly && (l.wo || "").trim() === no && i !== ent.editIdx);
          if (dupAt >= 0) throw new Error(T("الطقم {0} مضافٌ مسبقاً في هذه الفاتورة", no));
        }
        const last = no && !ent.src && (regV > 0 || diaV > 0) ? D.woLast(s, no, inv.id) : null;
        if (ent.editIdx === null && last) {
          const lastIn = D.IN_KINDS.includes(last.kind);
          if (isOut() && !lastIn) {
            const ok = await confirmSheet(T("الطقم {0} خرج من يدك: {1} {2} لـ«{3}»", no, T(D.KIND_LABEL[last.kind]), last.inv.no, last.shop ? last.shop.name : "—") +
              T(" بتاريخ {0}.\n\nإضافته مرةً أخرى؟", dmy(last.date)), T("نعم، أضفه"));
            if (!ok) return false;
          }
          if (!isOut() && lastIn) {
            const ok = await confirmSheet(T("الطقم {0} معك أصلاً ({1} {2}).\n\nإضافته مرةً أخرى؟", no, T(D.KIND_LABEL[last.kind]), last.inv.no), T("نعم، أضفه"));
            if (!ok) return false;
          }
        }
        const li = D.buildLine({ wo: no, karat: ent.karat,
          gold: vals.gold, small: ent.smallV, big: vals.big, after: ent.afterV,
          standing: vals.standing || regV, reg: regV, diamond: diaV,
          stoneRate: ent.stoneRate, wages: wagesV, exact18: ent.fromCard ? ent.exact18 : null,
          src: ent.src, lid: ent.lid, photos: ent.photos });
        pushLine(li);
        clearEntry();
        if (!quiet) (no ? woIn : reg).focus();
        return true;
      } catch (e) { err(e); return false; }
    }
    // في خانات الطقم ما لم يُضَف بعد (أو سطرٌ قيد التعديل)
    const pendingEntry = () => ent.editIdx !== null || !!woIn.value.trim() || (reg.getVal() || 0) > 0 ||
      (dia.getVal() || 0) > 0 || !wagesIn.isBlank() || ent.photos.length > 0;
    function pushLine(li) {
      if (ent.editIdx !== null) inv.lines[ent.editIdx] = li; else inv.lines.push(li);
      refresh();
    }
    addBtn.addEventListener("click", () => addLine());
    cancelEdit.addEventListener("click", clearEntry);
    enterChain([woIn, gold, big, stand, reg, wagesIn], () => addLine());
    enterChain([dia], () => addLine());

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
      addBtn.textContent = T("✔ حفظ تعديل السطر");
      cancelEdit.style.display = "";
      renderPickBtn();
      setNotice("info", T("تعديل السطر {0}{1}", i + 1, li.wo ? T(" — الطقم ") + li.wo : ""));
      entryCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // ── البنود والإجماليات ──
    const linesBox = h("div");
    const totalsBox = h("div", { class: "totals" });
    function lineTitle(li, i) {
      if (li.wageOnly) return [h("b", null, T("أجور فقط")), li.note ? h("span", { class: "muted small" }, "  · " + li.note) : null];
      return [li.wo ? h("span", { class: "wo", dir: "auto", text: li.wo }) : h("b", null, T("طقم {0}", i + 1)),
        li.reg18 > 0 ? h("span", { class: "badge", style: { marginInlineStart: "6px" } }, T("عيار {0}", li.karat || 18))
          : h("span", { class: "badge", style: { marginInlineStart: "6px" } }, T("ماس فقط")),
        li.src ? h("span", { class: "muted small" }, T("  · من الطقوم التي معي")) : null];
    }
    function refresh() {
      linesBox.innerHTML = "";
      if (!inv.lines.length) {
        linesBox.append(h("div", { class: "empty" }, T("اكتب بيانات الطقم ثم «حفظ الفاتورة» — أو «+ إضافة» لطقمٍ آخر")));
      }
      inv.lines.forEach((li, i) => {
        const lk = li.karat || 18;
        const cell = (label, val, ic) => h("div", { class: "muted" }, label, h("b", { class: "num" }, ic && val !== "—" ? ic() : null, val));
        linesBox.append(h("div", { class: "line" + (ent.editIdx === i ? " editing" : "") },
          h("div", { class: "top" },
            lineThumb(li, "sm"),
            h("div", { class: "grow" }, ...lineTitle(li, i)),
            h("div", { class: "act" },
              h("button", { onclick: () => editLine(i), "aria-label": T("تعديل") }, ico("edit", 17)),
              h("button", { class: "del", "aria-label": T("حذف"), onclick: async () => {
                if (await confirmSheet(T("حذف {0}؟", li.wageOnly ? T("سطر الأجور") : li.wo ? T("الطقم ") + li.wo : T("السطر ") + (i + 1)), T("حذف"), true)) {
                  inv.lines.splice(i, 1);
                  if (ent.editIdx === i) clearEntry();
                  refresh();
                }
              } }, ico("x", 17)))),
          li.wageOnly ? h("div", { class: "vals" }, cell(T("الأجور"), f2(li.amount), icoCash))
            : h("div", { class: "vals" },
              cell(T("الوزن"), li.reg18 > 0 ? gw(li.reg18, lk) : "—", icoGold),
              cell(T("💎 الماس"), li.diamond > 0 ? f2(li.diamond) : "—"),
              cell(T("الأجور"), f2(li.wages), icoCash))));
      });
      const t = D.totals(inv.lines, inv.vat);
      const sets = inv.lines.filter((l) => !l.wageOnly).length;
      const dia0 = D.diamondOf(inv);
      const k = vk();
      totalsBox.innerHTML = "";
      const row = (a, b, cls, ic) => h("div", { class: "spread" + (cls ? " " + cls : "") }, h("span", null, a), h("span", { class: "num" }, ic ? ic() : null, b));
      totalsBox.append(row(T("عدد الأطقم"), String(sets)),
        row(T("إجمالي الوزن (عيار {0})", k), gw(t.totalW18, k), "", icoGold),
        dia0 > 0 ? row(T("💎 إجمالي الماس (جم)"), f2(dia0)) : null,
        row(T("إجمالي الأجور"), f2(t.wages), "", icoCash));
      if (inv.vat) totalsBox.append(row(T("ضريبة 15% على الأجور"), f2(t.vatAmt), "", icoCash));
      totalsBox.append(row(T("الإجمالي"), f2(t.grand) + T(" ريال"), "grand", icoCash));
      if (inv.shopId) {
        const fac = forFactory();
        const before = D.balance(s, inv.shopId, inv.id);
        const e = D.effects({ kind: inv.kind, totalW18: t.totalW18, grand: t.grand });
        const g18 = Num_round3(before.gold18 + e.gd - e.gc);
        const c = Num_round2(before.cash + e.cd - e.cc);
        totalsBox.append(h("hr", { class: "sep" }),
          h("div", { class: "spread small" }, h("span", null, T("رصيد الذهب بعدها")), h("span", null, icoGold(), goldBal(g18, fac, k))),
          h("div", { class: "spread small" }, h("span", null, T("رصيد الأجور بعدها")), h("span", null, icoCash(), cashBal(c, fac))));
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
        // ما كُتب في خانات الطقم يُضاف تلقائياً — لا حاجة لـ«+ إضافة» قبل الحفظ
        if (pendingEntry() && !(await addLine({ quiet: true }))) return;
        if (!inv.shopId) { pickParty(); throw new Error(T("اختر {0}", partyWord())); }
        D.checkLines(inv.lines);
        const t = D.totals(inv.lines, inv.vat);
        const dia0 = D.diamondOf(inv);
        const msg = T("{0} {1} — «{2}»\n", editing ? T("حفظ تعديل") : T("حفظ"), INV_TITLE[inv.kind], shopTitle(inv.shopId)) +
          T("{0} طقم · {1} جم عيار {2}", inv.lines.filter((l) => !l.wageOnly).length, gw(t.totalW18, vk()), vk()) +
          (dia0 > 0 ? T(" · 💎 {0} جم", f2(dia0)) : "") + "\n" +
          T("الأجور {0}{1} = {2} ريال", f2(t.wages), inv.vat ? T(" + ضريبة {0}", f2(t.vatAmt)) : "", f2(t.grand));
        if (!(await confirmSheet(msg, editing ? T("حفظ التعديل") : T("حفظ الفاتورة")))) return;
        const rec = D.saveInvoice(s, { ...inv, heldId: inv.heldId });
        const ops = [["invoices", "put", rec], ...S.meta(s)];
        if (inv.heldId) ops.push(["held", "del", inv.heldId]);
        if (await persist(ops)) {
          clearDraft();
          toast(`${editing ? T("حُفظ تعديل") : T("حُفظت الفاتورة")} ${rec.no}`);
          replace(`doc/inv/${rec.id}`);
        }
      } catch (e) { err(e); }
    }

    async function hold() {
      try {
        if (!inv.lines.length) throw new Error(T("لا بنود لتعليقها"));
        const rec = { id: inv.heldId || D.uid("hd_"), kind: inv.kind, shopId: inv.shopId, date: inv.date,
          vat: inv.vat, desc: inv.desc, lines: inv.lines, savedAt: new Date().toISOString() };
        const i = s.held.findIndex((x) => x.id === rec.id);
        if (i >= 0) s.held[i] = rec; else s.held.push(rec);
        if (await persist([["held", "put", rec]])) {
          clearDraft();
          toast(T("عُلّقت — تجدها في «المعلّقات»"));
          replace("held");
        }
      } catch (e) { err(e); }
    }

    // الضريبة والبيان: نادراً ما يُحتاجان — مطويّان تحت الإجماليات
    const vatIn = h("input", { type: "checkbox", checked: inv.vat, onchange: (e) => { inv.vat = e.target.checked; refresh(); } });
    const descIn = h("input", { class: "in", value: inv.desc, placeholder: T("البيان — يظهر في كشف الحساب"),
      oninput: (e) => { inv.desc = e.target.value; saveDraft(); } });
    const opts = h("details", { class: "opts" }, h("summary", null, T("ضريبة · بيان (اختياري)")),
      h("label", { class: "switch" }, vatIn, T("ضريبة 15% على الأجور")), descIn);
    if (inv.vat || inv.desc) opts.open = true;

    const entryCard = h("div", { class: "card" }, h("h2", null, ico("gem", 18), T("الطقم")),
      pickBtn,
      h("div", { class: "grid2" }, field(T("الطقم (اختياري)"), woIn), field(T("العيار"), karatSel)),
      h("div", { style: { marginTop: "2px" } }, detailsBtn), detailsBox,
      h("div", { class: "grid2", style: { marginTop: "8px" } }, field(T("الوزن (جم)"), reg), field(T("الأجور (ريال)"), wagesIn)),
      h("div", { class: "grid2", style: { marginTop: "8px" } }, field(T("💎 الماس (جم)"), dia),
        h("div", { class: "fld" }, h("span", null, T("صور الطقم")), photoBox, photoIn)),
      photoStrip,
      // الأزرار قبل الإشعار: الإشعار يظهر عند مغادرة خانة الطقم —
      // ولو كان فوقها لانزاح الزرّ تحت الإصبع فتقع اللمسة على غيره
      h("div", { class: "row", style: { marginTop: "10px" } }, addBtn, cancelEdit),
      notice);

    v.append(entryCard,
      h("div", { class: "card" }, h("h2", null, ico("list", 18), T("البنود")), linesBox, totalsBox, opts),
      h("div", { class: "footer-bar" },
        h("button", { class: "btn", onclick: save }, editing ? T("حفظ التعديل") : T("حفظ الفاتورة")),
        editing ? null : h("button", { class: "btn ghost", onclick: hold }, T("⏸ تعليق"))));
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

  // ══ التحصيل من عميل · الدفع لمصنع ══
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
    const isPay = vo.kind === "payment";
    const p0 = D.shopById(s, vo.shopId);
    // عيار الحساب يبدأ به سطر الذهب؛ والمكافئ والخصم وزناً والرصيد قبل وبعد بعيار العرض
    let k = ek(p0);
    const K = vk();
    if (!editing) vo.rows.forEach((r) => { if (r.kind === "gold") r.karat = k; });
    // دفعٌ قديم لعميل (من الإصدارات الأولى) يبقى قابلاً للتعديل كما هو
    const legacy = isPay && p0 && !D.isFactory(p0);
    const forFactory = isPay && !legacy;
    const word = forFactory ? T("المصنع") : T("العميل");
    const label = isPay ? (legacy ? T("صرف لعميل") : T("سداد للمصنع")) : T("تحصيل من العميل");
    const header = () => {
      const sh = D.shopById(s, vo.shopId);
      docHeader(label + (editing ? ` ${vo.no}` : ""), sh ? sh.name : "", T("اختر {0}", word), vo.date, pickParty,
        (d) => { vo.date = d; header(); });
    };
    const v = view();
    // ما في صناديقي (دون هذا السند إن كان يُعدَّل)
    const hd = D.holdings({ ...s, vouchers: s.vouchers.filter((x) => x.id !== vo.id) });
    const boxOf = (karat) => (hd.boxes.find((b) => b.karat === karat) || { weight: 0 }).weight;

    async function pickParty() {
      const it = await pickSheet(T("اختر {0}", word), partyItems(forFactory ? "factory" : "shop"),
        { addLabel: forFactory ? T("+ مصنع جديد") : T("+ عميل جديد"), empty: forFactory ? T("لا مصانع بعد") : T("لا عملاء بعد") });
      if (!it) return;
      if (it.add) { go(forFactory ? "shop-form?type=factory" : "shop-form"); return; }
      vo.shopId = it.id; header();
      const nk = ek(D.shopById(s, it.id));
      if (nk !== k) {
        k = nk;
        vo.rows.forEach((r) => { if (r.kind === "gold" && !(r.weight > 0)) r.karat = k; });
        renderRows();
      }
      refresh();
    }
    const notesIn = h("input", { class: "in", value: vo.notes, placeholder: T("البيان — يظهر في كشف الحساب"), oninput: (e) => { vo.notes = e.target.value; } });

    const rowsBox = h("div");
    function renderRows() {
      rowsBox.innerHTML = "";
      vo.rows.forEach((r, i) => {
        const card = h("div", { class: "line" });
        card.append(h("div", { class: "top" },
          h("b", null, r.kind === "gold" ? T("ذهب") : T("نقد")),
          h("div", { class: "act" }, h("button", { class: "del", "aria-label": T("حذف"), onclick: () => { vo.rows.splice(i, 1); renderRows(); refresh(); } }, ico("x", 17)))));
        if (r.kind === "gold") {
          const w = numInput({ value: r.weight });
          const ks = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: T("عيار {0}", x) })));
          ks.value = String(r.karat || k);
          const eq = h("div", { class: "muted small num" });
          const avail = h("div", { class: "small" });
          const upd = () => {
            r.weight = w.getVal() || 0; r.karat = parseInt(ks.value, 10);
            const vg = G.voucherGold(r.weight, r.karat);
            eq.textContent = r.karat === K ? "" : T("= {0} جم مكافئ عيار {1}", gw(vg.equiv, K), K);
            if (isPay) {
              const have = boxOf(r.karat);
              avail.className = "small " + (r.weight > have + 0.0005 ? "bal-on" : "muted");
              avail.textContent = T("معك في صندوق عيار {0}: {1} جم", r.karat, f2(have)) + (r.weight > have + 0.0005 ? T(" — أقلّ مما تدفع") : "");
            }
            refresh();
          };
          w.addEventListener("input", upd); ks.addEventListener("change", upd);
          card.append(h("div", { class: "grid2", style: { marginTop: "6px" } }, field(T("الوزن (جم)"), w), field(T("العيار"), ks)), eq, isPay ? avail : null);
          upd();
        } else {
          const a = numInput({ value: r.amount });
          const avail = h("div", { class: "small muted" });
          const upd = () => {
            r.amount = a.getVal() || 0;
            if (isPay) {
              const have = hd.cash.amount;
              avail.className = "small " + (r.amount > have + 0.005 ? "bal-on" : "muted");
              avail.textContent = T("معك نقداً: {0} ريال", f2(have)) + (r.amount > have + 0.005 ? T(" — أقلّ مما تدفع") : "");
            }
            refresh();
          };
          a.addEventListener("input", upd);
          card.append(h("div", { style: { marginTop: "6px" } }, field(T("المبلغ (ريال)"), a)), isPay ? avail : null);
          upd();
        }
        const n = h("input", { class: "in", value: r.notes || "", placeholder: T("بيان السطر (اختياري)"),
          oninput: (e) => { r.notes = e.target.value; } });
        card.append(h("div", { style: { marginTop: "6px" } }, n));
        rowsBox.append(card);
      });
      if (!vo.rows.length) rowsBox.append(h("div", { class: "empty" }, T("أضف سطر ذهب أو نقد")));
    }
    const dGold = numInput({ value: G.g(vo.discGold18, K) });
    const dCash = numInput({ value: vo.discCash });
    const nDiff = numInput({ value: vo.netDiff });
    for (const el of [dGold, dCash, nDiff]) el.addEventListener("input", refresh);
    const dGoldF = field("", dGold);
    const dGoldLbl = () => { dGoldF.firstChild.textContent = T("خصم مسموح وزناً (جم عيار {0})", K); };
    dGoldLbl();
    // البيان (والخصومات في التحصيل) مطويّةٌ — نادراً ما تُحتاج
    const extras = h("details", { class: "opts" },
      h("summary", null, isPay ? T("بيان (اختياري)") : T("بيان · خصومات (اختياري)")), notesIn,
      isPay ? null : h("div", { class: "grid2", style: { marginTop: "10px" } },
        dGoldF, field(T("خصم مسموح نقداً (ريال)"), dCash),
        field(T("فرق الصافي (ريال، + زيادة · − تخفيض)"), nDiff, "span2")));
    if (vo.notes || vo.discCash || vo.discGold18 || vo.netDiff) extras.open = true;

    const totalsBox = h("div", { class: "totals" });
    function draft() {
      return { ...vo, discGold18: G.store(dGold.getVal() || 0, K), discCash: dCash.getVal() || 0, netDiff: nDiff.getVal() || 0 };
    }
    function refresh() {
      totalsBox.innerHTML = "";
      let rows;
      try { rows = D.voucherRows(vo.rows); } catch (e) { rows = []; }
      let eq = 0, cash = 0;
      for (const r of rows) { eq += r.equiv; cash += r.amount; }
      const row = (a, b, ic) => h("div", { class: "spread" }, h("span", null, a), h("span", { class: "num" }, ic ? ic() : null, b));
      totalsBox.append(row(T("الذهب (مكافئ عيار {0})", K), gw(Num_round3(eq), K), icoGold),
        row(T("النقد"), f2(Num_round2(cash)) + T(" ريال"), icoCash));
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
          h("div", { class: "spread small" }, h("span", null, T("رصيد الذهب قبل")), h("span", null, icoGold(), goldBal(before.gold18, fac, K))),
          h("div", { class: "spread small" }, h("span", null, T("رصيد الذهب بعد")), h("span", null, icoGold(), goldBal(Num_round3(before.gold18 + e.gd - e.gc), fac, K))),
          h("div", { class: "spread small" }, h("span", null, T("رصيد النقد قبل")), h("span", null, icoCash(), cashBal(before.cash, fac))),
          h("div", { class: "spread small" }, h("span", null, T("رصيد النقد بعد")), h("span", null, icoCash(), cashBal(Num_round2(before.cash + e.cd - e.cc), fac))));
      }
    }
    async function save() {
      try {
        if (!vo.shopId) { pickParty(); throw new Error(T("اختر {0}", word)); }
        const dv = draft();
        if ([dGold.getVal(), dCash.getVal(), nDiff.getVal()].some((x) => !isFinite(x))) throw new Error(T("رقمٌ غير صحيح"));
        const rows = D.voucherRows(vo.rows);
        let eq = 0, cash = 0;
        for (const r of rows) { eq += r.equiv; cash += r.amount; }
        const golds = rows.filter((r) => r.kind === "gold").map((r) => T("{0} جم عيار {1}", f2(r.weight), r.karat)).join(" + ");
        const msg = T("{0} {1} — «{2}»\n", editing ? T("حفظ تعديل") : T("حفظ"), label, shopTitle(vo.shopId)) +
          T("{0}نقد {1} ريال", golds ? T("ذهب ") + golds + "\n" : "", f2(Num_round2(cash)));
        if (!(await confirmSheet(msg, editing ? T("حفظ التعديل") : T("حفظ السند")))) return;
        const rec = D.saveVoucher(s, dv);
        if (await persist([["vouchers", "put", rec], ...S.meta(s)])) {
          toast(`${editing ? T("حُفظ تعديل") : T("حُفظ السند")} ${rec.no}`);
          replace(`doc/vo/${rec.id}`);
        }
      } catch (e) { err(e); }
    }
    v.append(
      h("div", { class: "card" }, h("h2", null, ico(isPay ? "out" : "in", 18), isPay ? T("ما سدّدته") : T("ما حصّلته")), rowsBox,
        h("div", { class: "row" },
          h("button", { class: "btn ghost grow", onclick: () => { vo.rows.push({ kind: "gold", weight: 0, karat: k, notes: "" }); renderRows(); } }, T("+ ذهب")),
          h("button", { class: "btn ghost grow", onclick: () => { vo.rows.push({ kind: "cash", amount: 0, notes: "" }); renderRows(); } }, T("+ نقد")))),
      h("div", { class: "card" }, totalsBox, extras),
      h("div", { class: "footer-bar" }, h("button", { class: "btn", onclick: save }, editing ? T("حفظ التعديل") : T("حفظ السند"))));
    header(); renderRows(); refresh();
    if (!vo.shopId) setTimeout(pickParty, 150);
  }

  // ══ عرض المستند: مشاركة · طباعة · تعديل · حذف ══
  function docView(type, id) {
    const s = st();
    const isInv = type === "inv";
    const d = (isInv ? s.invoices : s.vouchers).find((x) => x.id === id);
    if (!d) { replace("log"); return; }
    setBar(`${T(D.KIND_LABEL[d.kind])} ${d.no}`, `${shopTitle(d.shopId)} · ${dmy(d.date)}`);
    setTab("more");
    let html = isInv ? P.invoiceHtml(s, d, {}) : P.voucherHtml(s, d);
    const v = view();
    const name = `${d.no}`;
    v.append(h("div", { class: "quick" },
      quickBtn("share", T("مشاركة صورة"), () => B.shareHtmlImage(html, name)),
      quickBtn("printer", T("طباعة / PDF"), () => B.printHtml(html, name)),
      isInv ? quickBtn("chat", T("نص واتساب"), () => B.shareText(P.invoiceText(s, d))) : quickBtn("book", T("كشف الحساب"), () => go(`statement/${d.shopId}`)),
      quickBtn("edit", T("تعديل"), () => go(`${isInv ? "invoice" : "voucher"}/edit/${d.id}`)),
      quickBtn("trash", T("حذف"), async () => {
        if (!(await confirmSheet(T("حذف {0} {1}؟\n\nيُلغى أثره من رصيد «{2}».", T(D.KIND_LABEL[d.kind]), d.no, shopTitle(d.shopId)), T("حذف"), true))) return;
        if (isInv) D.deleteInvoice(s, d.id); else D.deleteVoucher(s, d.id);
        if (await persist([[isInv ? "invoices" : "vouchers", "del", d.id]])) { toast(T("حُذف {0}", d.no)); replace(`shop/${d.shopId}`); }
      }),
      isInv ? quickBtn("book", T("كشف الحساب"), () => go(`statement/${d.shopId}`)) : quickBtn("store", T("الحساب"), () => go(`shop/${d.shopId}`))));
    const frame = previewFrame(html);
    v.append(frame);
    // صور الأطقم تُحمَّل ثم تُعاد المعاينة بها (والمشاركة والطباعة كذلك)،
    // وتحتها كل صورةٍ وحدها كاملة
    const phs = isInv ? D.docPhotos(d) : [];
    if (phs.length) {
      S.getPhotos(phs.map((p) => p.id)).then((ph) => {
        if (!Object.keys(ph).length) return;
        html = P.invoiceHtml(s, d, ph);
        frame.setHtml(html);
      });
      v.append(h("div", { class: "sec-title", style: { marginTop: "12px" } }, ico("image", 18), T("صور الأطقم ({0})", phs.length)));
      phs.forEach((p, i) => v.append(photoFig(p.id, p.wo || T("طقم {0}", p.n), i, phs.length)));
    }
  }

  // المعاينة: صفحةٌ بعرض 1000 تُصغَّر — أو «مرنة» تأخذ عرض الشاشة كما هي
  function previewFrame(html, opts) {
    const fluid = !!(opts && opts.fluid);
    const box = h("div", { class: "preview" + (fluid ? " fluid" : "") });
    const fr = h("iframe", { title: T("معاينة") });
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

  // ══ كشف الحساب: جدولٌ واحدٌ بسيط — ولمس العملية يعاينها بصورها، ومنها تعديلها ══
  function statementScreen(id, q) {
    const s = st();
    const shop = D.shopById(s, id);
    if (!shop) { replace("customers"); return; }
    const fac = D.isFactory(shop);
    const mode = q.view === "diamond" ? "diamond" : "gold";
    const from = q.from || "", to = q.to || "";
    // الفرز (1.11): الكل · المبيعات · المرتجعات · التحصيل (وللمصنع: البضاعة · الإرجاع · السداد)
    const filter = mode === "gold" && D.ST_FILTERS.includes(q.f) ? q.f : "";
    const k = pk(shop);
    const url = (o) => {
      const x = Object.assign({ id, from, to, view: mode === "diamond" ? "diamond" : "", f: filter }, o);
      if (x.view === "diamond") x.f = "";
      const qs = ["from", "to", "view", "f"].filter((key) => x[key]).map((key) => `${key}=${encodeURIComponent(x[key])}`).join("&");
      return `statement/${x.id}` + (qs ? "?" + qs : "");
    };
    const html = P.statementHtml(s, id, from || null, to || null, mode, filter);
    const fl = filter ? P.filterLabel(fac, filter) : "";
    const name = T("كشف {0}{1}", shop.name, mode === "diamond" ? T(" — الماس") : fl ? " — " + fl : "");
    // الشريط: الحساب يُبدَّل بلمسة، والمشاركة صورةً والطباعة أيقونتان
    setBar(T("كشف حساب"), h("span", { class: "sub bar-chips" },
      h("button", { type: "button", class: "chip-btn party", onclick: pickPartyThen(null, (nid) => replace(url({ id: nid }))) },
        h("span", { class: "t" }, (fac ? T("مصنع · ") : "") + shop.name), h("span", { class: "car" }, "▾"))), {
      actions: [
        h("button", { class: "icon-btn", "aria-label": T("مشاركة صورة"), onclick: () => B.shareHtmlImage(html, name) }, ico("share", 21)),
        h("button", { class: "icon-btn", "aria-label": T("طباعة"), onclick: () => B.printHtml(html, name) }, ico("printer", 21))],
    });
    setTab("customers");
    const v = view();

    // الفترة (زرٌّ واحد) · ذهب أو ماس
    const presets = periodPresets();
    const cur = presets.find(([, a, b]) => a === from && b === to);
    const periodLabel = cur ? cur[0] : `${from ? dmy(from) : T("البداية")} ← ${to ? dmy(to) : T("اليوم")}`;
    async function periodSheet() {
      const r = await sheet((box, close) => {
        const fIn = h("input", { class: "in", type: "date", value: from });
        const tIn = h("input", { class: "in", type: "date", value: to });
        fIn.dataset.autofocus = "no";
        const list = h("div", { class: "chips wrap" });
        for (const [label, a, b] of presets) {
          list.append(h("button", { class: "chip" + (from === a && to === b ? " on" : ""), onclick: () => close({ from: a, to: b }) }, label));
        }
        box.append(h("h3", null, ico("calendar", 20), T(" الفترة")), list,
          h("div", { class: "grid2", style: { marginTop: "12px" } }, field(T("من"), fIn), field(T("إلى"), tIn)),
          h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => close({ from: fIn.value, to: tIn.value }) }, T("عرض"))));
      });
      if (r) replace(url({ from: r.from || "", to: r.to || "" }));
    }
    v.append(h("div", { class: "st-filters" },
      h("button", { type: "button", class: "chip on st-period", onclick: periodSheet }, ico("calendar", 15), h("span", null, periodLabel), " ▾"),
      h("div", { class: "seg sm" },
        h("button", { class: mode === "gold" ? "on" : "", onclick: () => replace(url({ view: "" })) }, T("ذهب")),
        h("button", { class: mode === "diamond" ? "on" : "", onclick: () => replace(url({ view: "diamond" })) }, T("💎 ماس")))));
    if (mode === "gold") {
      v.append(h("div", { class: "chips st-kinds" }, ["", ...D.ST_FILTERS].map((key) =>
        h("button", { class: "chip" + (key === filter ? " on" : ""), onclick: () => replace(url({ f: key })) }, P.filterLabel(fac, key)))));
    }

    // خانات الجدول: التاريخ يوماً وشهراً والسنة تحته؛ والحركة فوق رصيدها
    const sgn = (x) => (x > 0 ? "+" : "−") + f2(Math.abs(x));
    const dt = (iso) => h("td", { class: "d" }, iso ? h("span", { dir: "ltr" }, iso.slice(8, 10) + "-" + iso.slice(5, 7)) : null,
      iso ? h("small", null, iso.slice(0, 4)) : null);
    const mcell = (mv, bal, word) => h("td", { class: "m" },
      mv ? h("span", { class: "mv num", dir: "ltr" }, mv) : null,
      h("b", { class: "num" }, bal), word ? [" ", h("span", { class: "w" }, word)] : null);
    const opCell = (r, extra) => h("td", { class: "op" }, h("b", null, T(r.label)),
      r.no ? h("small", { class: "no" }, h("span", { dir: "ltr" }, r.no)) : null, extra || null);
    const tbody = h("tbody");
    const row = (r, cells) => {
      const tr = h("tr", r.doc ? { class: "tap", onclick: () => previewSheet(r.doc) } : null, ...cells);
      tbody.append(tr);
    };
    let head, bal, n = 0;
    if (mode === "diamond") {
      const res = D.diamondStatement(s, id, from || null, to || null);
      const f = fac ? -1 : 1;     // للمصنع: البضاعة «+» والإرجاع «−» من جهته
      for (const r of res.rows) {
        const sets = (r.sets || []).map((x) => `${x.name || T("طقم")} (${f2(x.diamond)})`).join(T("، "));
        row(r, [dt(r.date), opCell(r, sets ? h("small", null, sets) : null),
          mcell(r.kind === "prev" ? "" : sgn(f * (r.dd - r.dc)), f2(f * r.bal), "")]);
        if (r.doc) n++;
      }
      head = [T("التاريخ"), T("العملية"), T("💎 الماس (جم)")];
      bal = h("div", { class: "st-bal" }, h("span", { class: "muted" }, T("صافي الماس")),
        h("b", { class: "num" }, T("{0} جم", f2(f * res.diamond))));
    } else {
      // «عليه · له · الرصيد» (1.11): في كل خانةٍ الذهب فوق والنقد تحته — ثم صفّ
      // الإجمالي: كم عليه، وكم له، وكم الباقي (عليه − له). وبالفرز: النوع وحده ومجموعه
      const res = D.statementView(s, id, from || null, to || null, filter);
      const cum = !!res.filter;
      const amt = (g18, c) => {
        const gv = G.g(g18, k);
        const hg = Math.abs(gv) >= 0.005, hc = Math.abs(c) >= 0.005;
        if (!hg && !hc) return h("td", { class: "m z" }, "—");
        return h("td", { class: "m" }, h("span", { class: "gl" }, hg ? icoGold() : null, h("span", { class: "num", dir: "ltr" }, hg ? f2(gv) : "—")),
          h("span", { class: "cl" }, hc ? icoCash() : null, h("span", { class: "num", dir: "ltr" }, hc ? f2(c) : "—")));
      };
      const balc = (g18, c) => {
        const gv = G.g(g18, k);
        const w = (x) => (cum || Math.abs(x) < 0.005 ? null : [" ", h("span", { class: "w" }, balWord(x, fac))]);
        return h("td", { class: "m b" }, h("span", { class: "gl" }, icoGold(), h("b", { class: "num" }, f2(Math.abs(gv))), w(gv)),
          h("span", { class: "cl" }, icoCash(), h("span", { class: "num" }, f2(Math.abs(c))), w(c)));
      };
      for (const r of res.rows) {
        row(r, [dt(r.date), opCell(r), amt(r.gd, r.cd), amt(r.gc, r.cc), balc(r.gbal, r.cbal)]);
        if (r.doc) n++;
      }
      if (res.rows.length) {
        const t = res.totals;
        tbody.append(h("tr", { class: "tot" },
          h("td", { class: "op", colspan: "2" }, h("b", null, cum ? T("إجمالي {0}", fl) : T("الإجمالي")),
            h("small", null, cum ? T("{0} عملية", res.rows.length) : T("عليه − له = الباقي"))),
          amt(t.gd, t.cd), amt(t.gc, t.cc), balc(t.gbal, t.cbal)));
      }
      head = [T("التاريخ"), T("العملية"), T("عليه"), T("له"), cum ? T("المجموع") : T("الرصيد")];
      bal = cum
        ? h("div", { class: "st-bal" }, h("span", { class: "muted" }, T("إجمالي {0}", fl)),
          h("b", { class: "num" }, icoGold(), T("{0} جم", gw(Math.abs(res.totals.gbal), k))), h("span", { class: "muted" }, "·"),
          h("b", { class: "num" }, icoCash(), T("{0} ريال", f2(Math.abs(res.totals.cbal)))),
          h("span", { class: "muted small st-all" }, T("رصيد الحساب كله: "), icoGold(), goldBal(res.gold18, fac, k), " · ", icoCash(), cashBal(res.cash, fac)))
        : h("div", { class: "st-bal" }, h("span", { class: "muted" }, T("الرصيد")),
          h("span", null, icoGold(), goldBal(res.gold18, fac, k)), h("span", { class: "muted" }, "·"), h("span", null, icoCash(), cashBal(res.cash, fac)));
    }
    v.append(bal);
    if (!tbody.children.length) {
      v.append(h("div", { class: "empty" }, mode === "diamond" ? T("لا ماس في الفترة")
        : filter ? T("لا شيء من «{0}» في الفترة", fl) : T("لا حركة في الفترة")));
      return;
    }
    if (mode === "gold") v.append(h("div", { class: "muted small st-legend", html: T("في كل خانة: {0} الذهب (جم عيار {1}) فوق، و{2} النقد والأجور (ريال) تحته.", P.ICO_GOLD, k, P.ICO_CASH) }));
    v.append(h("table", { class: "st-table" + (mode === "diamond" ? " dia" : " gold") },
      h("thead", null, h("tr", null, ...head.map((x) => h("th", null, x)))), tbody));
    if (n) v.append(h("div", { class: "muted small st-hint" }, T("اضغط على أي عملية لمعاينتها وصورها، ومنها تعديلها")));
  }

  // ══ سجل العمليات ══
  function logScreen(q) {
    const s = st();
    setBar(T("سجل العمليات"), T("الفواتير والسندات"), { back: false });
    setTab("more");
    const v = view();
    let kind = q.kind || "";
    const search = h("input", { class: "in", type: "search", placeholder: T("ابحث برقم المستند أو الاسم أو الطقم…"), value: q.q || "" });
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
      if (!docs.length) list.append(h("div", { class: "empty" }, T("لا عمليات")));
      docs.slice(0, 300).forEach((d) => list.append(docItem(d)));
    };
    for (const [kk, label] of [["", T("الكل")], ["sale", T("بيع")], ["sale_return", T("مرتجع")], ["receipt", T("تحصيل")],
      ["payment", T("سداد")], ["purchase", T("بضاعة")], ["purchase_return", T("إرجاع للمصنع")]]) {
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
  // ══ البحث عن طقم: باسمه أو وزنه — ومع من هو الآن (1.6) ══
  // الاقتراحات تظهر من أول حرف (أو أول رقمٍ للوزن)، ولمس الطقم يعرض مكانه
  // الآن وكل حركاته؛ والطقم بلا اسم يُتتبَّع بسطر دخوله وما اختير منه بعده
  function setWhere(t) {
    const who = t.party ? t.party.name : "—";
    if (t.where === "in") return { short: T("معك"), cls: "badge grade good",
      long: t.last.kind === "opening" ? T("معك — من الرصيد الافتتاحي") : T("معك — {0} «{1}»", t.last.kind === "purchase" ? T("من مصنع") : T("مرتجعٌ من"), who) };
    if (t.where === "customer") return { short: T("عند «{0}»", who), cls: "badge",
      long: T("عند «{0}» — مباعٌ بالفاتورة {1}", who, t.last.inv.no) };
    return { short: T("رجع إلى «{0}»", who), cls: "badge ret", long: T("رجع إلى المصنع «{0}» — {1} {2}", who, T(D.KIND_LABEL[t.last.kind]), t.last.inv.no) };
  }
  function woScreen(q) {
    const s = st();
    setBar(T("بحث عن طقم"), T("باسمه أو وزنه — ومع من هو الآن"));
    setTab("home");
    const v = view();
    // (نصٌّ لا `type=search`: زرّ المسح فيه بلونٍ من خارج لوحة التطبيق)
    const inp = h("input", { class: "in hl sr-in", type: "text", inputmode: "search", placeholder: T("اسم الطقم أو وزنه"), value: q.no || "",
      enterkeyhint: "search", dir: "auto", autocomplete: "off", "aria-label": T("اسم الطقم أو وزنه") });
    const out = h("div", { class: "sr-out" });
    const title = (t) => t.name || T("طقمٌ بلا اسم");
    const meta = (t) => T("{0} جم عيار {1}", f2(t.weight), t.karat);
    const thumbOf = (t) => lineThumb({ photos: t.photos, wo: t.name }, "md");
    // الاقتراحات: الاسم ووزنه وعياره ومكانه الآن
    const suggest = () => {
      out.innerHTML = "";
      const text = inp.value.trim();
      if (!text) { out.append(h("div", { class: "empty" }, T("اكتب أول حرفٍ من اسم الطقم، أو وزنه — فتظهر الأطقم المطابقة"))); return; }
      const res = D.searchSets(s, text);
      if (!res.length) { out.append(h("div", { class: "empty" }, T("لا طقم باسمٍ أو وزنٍ يطابق «{0}»", text))); return; }
      for (const t of res) {
        const w = setWhere(t);
        out.append(h("div", { class: "list-item sr-item", onclick: () => detail(t) },
          thumbOf(t),
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t", dir: "auto", text: title(t) }), h("span", { class: w.cls, text: w.short })),
            h("div", { class: "muted small num" }, meta(t))),
          ico("chevron", 18, "muted")));
      }
    };
    // الطقم: أين هو الآن، ثم حركاته من الأحدث
    const detail = (t) => {
      out.innerHTML = "";
      const w = setWhere(t);
      out.append(h("div", { class: "list-item", style: { cursor: "default" } }, thumbOf(t),
        h("div", { class: "grow" }, h("div", { class: "t", dir: "auto", text: title(t) }), h("div", { class: "muted small num" }, meta(t)))));
      out.append(h("div", { class: "note-bar info", style: { marginBottom: "10px" } }, T("الآن: {0}", w.long)));
      for (const m of t.moves.slice().reverse()) {
        const lk = m.line.karat || 18;
        const op = m.kind === "opening";
        out.append(h("div", { class: "list-item", onclick: () => go(op ? "opening" : `doc/inv/${m.inv.id}`) },
          lineThumb(m.line, "md"),
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t" }, op ? T("ما كان معي") : m.shop ? m.shop.name : "—"), kindBadge(m.kind)),
            h("div", { class: "spread muted small" },
              h("span", null, h("span", { dir: "ltr", text: m.inv.no }), " · ", h("span", { dir: "ltr", text: dmy(m.date) })),
              h("span", { class: "num" }, T("{0} جم {1} · أجر {2}", gw(m.line.reg18, lk), lk, f2(G.wageView(m.line.rate18, lk))))))));
      }
      out.append(h("button", { class: "btn ghost", style: { width: "100%" }, onclick: () => { suggest(); inp.focus(); } }, T("نتائج البحث")));
    };
    inp.addEventListener("input", suggest);
    inp.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const res = D.searchSets(s, inp.value);
      if (res.length === 1) detail(res[0]);
    });
    v.append(h("div", { class: "card" }, field(T("الطقم"), inp)), out);
    // من رابطٍ باسم طقمٍ بعينه: يُفتح مباشرةً إن طابقه طقمٌ واحد باسمه
    const exact = q.no ? D.searchSets(s, q.no).filter((t) => D.searchKey(t.name) === D.searchKey(q.no)) : [];
    if (exact.length === 1) detail(exact[0]);
    else suggest();
    if (!q.no) setTimeout(() => inp.focus(), 100);
  }

  // ══ المعلّقات ══
  function heldScreen() {
    const s = st();
    setBar(T("المعلّقات"), T("فواتير لم تُحفظ بعد"));
    setTab("more");
    const v = view();
    if (!s.held.length) { v.append(h("div", { class: "empty" }, T("لا فواتير معلّقة"))); return; }
    for (const hd of s.held.slice().sort((a, b) => (a.savedAt < b.savedAt ? 1 : -1))) {
      const t = D.totals(hd.lines, hd.vat);
      v.append(h("div", { class: "list-item" },
        h("div", { class: "grow", onclick: () => go(`invoice/held/${hd.id}`) },
          h("div", { class: "spread" }, h("span", { class: "t" }, shopTitle(hd.shopId)), kindBadge(hd.kind)),
          h("div", { class: "muted small" }, T("{0} سطر · {1} {2} · {3} ريال · {4}", hd.lines.length, gw(t.totalW18, pk(D.shopById(s, hd.shopId))), unitK(pk(D.shopById(s, hd.shopId))), f2(t.grand), dmy((hd.savedAt || "").slice(0, 10))))),
        h("div", { class: "act" }, h("button", { class: "del", onclick: async () => {
          if (!(await confirmSheet(T("حذف الفاتورة المعلّقة؟"), T("حذف"), true))) return;
          s.held = s.held.filter((x) => x.id !== hd.id);
          if (await persist([["held", "del", hd.id]])) render();
        } }, ico("x", 17)))));
    }
    function render() { view().innerHTML = ""; heldScreen(); }
  }

  // ══ المزيد ══
  function moreScreen() {
    setBar(T("المزيد"), "", { back: false });
    setTab("more");
    const v = view();
    const item = (icon, t, sub, fn) => h("div", { class: "list-item", onclick: fn },
      h("span", { class: "avatar" }, ico(icon, 20)), h("div", { class: "grow" }, h("div", { class: "t" }, t),
        sub ? h("div", { class: "muted small" }, sub) : null), ico("chevron", 18, "muted"));
    const us = B.updateState();
    v.append(
      item("languages", T("اللغة: العربية"), LANG_NAME[OTHER_LANG()], () => switchLang(OTHER_LANG())),
      item("list", T("سجل العمليات"), T("كل الفواتير والسندات — بحثٌ ونوع"), () => go("log")),
      item("search", T("بحث عن طقم"), T("باسمه أو وزنه — ومع من هو الآن"), () => go("wo")),
      item("pause", T("المعلّقات"), T("{0} فاتورة لم تُحفظ", st().held.length), () => go("held")),
      item("book", T("كشف حساب"), T("عميل أو مصنع"), pickPartyThen(null, (id) => go(`statement/${id}`))),
      item("coins", T("الرصيد الافتتاحي للممتلكات"), T("ما كان معك قبل التطبيق: ذهب · نقد · أطقم"), () => go("opening")),
      us.unsupported ? null : item("update", T("التحديثات"), us.available ? T("يوجد إصدارٌ جديد") : T("الإصدار {0}", us.version), updateSheet),
      item("settings", T("الإعدادات والحفظ"), T("اسم النشاط · عيار المجاميع · المظهر · الحفظ التلقائي"), () => go("settings")),
      item("share", T("شارك {0} مع غيرك", APP_NAME), T("رابطٌ واحد للآيفون وأندرويد — مجاني"),
        () => B.shareText(T("{0} — حسابات الذهب للمندوب، مجاني لأندرويد والآيفون:\n{1}", APP_NAME, SITE_URL))),
      // حيث يلزم القانون (أوروبا وبريطانيا) وحده: تغيير موافقة الإعلانات
      B.adsState().privacy === true ? item("shield", T("خيارات الخصوصية للإعلانات"), T("موافقتك على الإعلانات — غيّرها متى شئت"), () => B.adsPrivacy()) : null,
      root.Promo && root.Promo.contact() ? item("megaphone", T("أعلن في التطبيق"), T("اعرض نشاطك لكل المستخدمين"), advertiseSheet) : null);
  }

  // ══ الإعدادات والنسخ الاحتياطي ══
  function settingsScreen() {
    const s = st();
    setBar(T("الإعدادات"), "", {});
    setTab("more");
    const v = view();
    const S0 = s.settings;
    const name = h("input", { class: "in", value: S0.name, placeholder: T("يظهر أعلى الفواتير") });
    const phone = h("input", { class: "in", value: S0.phone, inputmode: "tel", dir: "ltr" });
    const address = h("input", { class: "in", value: S0.address });
    const vatNo = h("input", { class: "in", value: S0.vatNo, inputmode: "numeric", dir: "ltr", placeholder: T("للفواتير الضريبية (رمز QR)") });
    const karat = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: T("عيار {0}", x) })));
    karat.value = String(S0.viewKarat || 18);
    const rate = numInput({ value: Num_round2((S0.stoneRate ?? 0.5) * 100), raw: true });
    const showBal = h("input", { type: "checkbox", checked: S0.showBalanceOnInvoice });
    const langSel = h("select", { class: "in", id: "lang-sel", onchange: (e) => switchLang(e.target.value) },
      h("option", { value: "ar", text: "العربية" }), h("option", { value: "en", text: "English" }));
    langSel.value = root.I18N.lang;
    const theme = h("select", { class: "in" }, h("option", { value: "auto", text: T("تلقائي (حسب الجوال)") }),
      h("option", { value: "light", text: T("☀ فاتح") }), h("option", { value: "dark", text: T("🌙 ليلي") }));
    theme.value = S0.theme || "auto";
    const save = async () => {
      try {
        const r = rate.getVal();
        if (!isFinite(r) || r < 0 || r > 100) throw new Error(T("نسبة خصم الأحجار بين 0 و100"));
        Object.assign(S0, { name: name.value.trim(), phone: phone.value.trim(), address: address.value.trim(),
          vatNo: vatNo.value.trim(), viewKarat: parseInt(karat.value, 10), stoneRate: r / 100,
          showBalanceOnInvoice: showBal.checked, theme: theme.value });
        applyTheme();
        if (await persist(S.meta(s))) toast(T("حُفظت الإعدادات"));
      } catch (e) { err(e); }
    };
    const backupName = () => `gold-backup-${D.today()}.json`;
    const doBackup = async (share) => {
      const text = JSON.stringify(D.toBackup(s, await S.allPhotos()));
      if (share) B.shareFile(backupName(), text); else B.saveFile(backupName(), text);
      s.settings.lastBackup = new Date().toISOString();
      await persist(S.meta(s));
      ls("webBackupAt", String(Date.now()));
      hideBackupBar();
      toast(share ? T("اختر أين تحفظ النسخة (واتساب · درايف · …)") : T("حُفظت النسخة في «التنزيلات»"));
    };
    const fileIn = h("input", { type: "file", accept: ".json,application/json", style: { display: "none" } });
    fileIn.addEventListener("change", async () => {
      const f = fileIn.files && fileIn.files[0];
      fileIn.value = "";
      if (!f) return;
      try {
        const obj = JSON.parse(await f.text());
        const ns = D.fromBackup(obj);
        const msg = T("استرجاع النسخة المحفوظة {0}:\n", (obj.savedAt || "").slice(0, 10)) +
          T("{0} عميل ومصنع · {1} فاتورة · {2} سند\n\n", ns.shops.length, ns.invoices.length, ns.vouchers.length) +
          T("تُستبدل بها كل البيانات الحالية في هذا الجوال.");
        if (!(await confirmSheet(msg, T("استرجاع"), true))) return;
        await S.replaceAll(ns);
        await importPhotos(D.backupPhotos(obj));
        App.state = ns;
        applyTheme();
        toast(T("استُرجعت البيانات"));
        scheduleAutoBackup();
        syncAllPhotos();
        replace("home");
      } catch (e) { err(e.name === "SyntaxError" ? new Error(T("الملف تالف أو ليس نسخةً احتياطية")) : e); }
    });
    // الحفظ التلقائي في مجلد
    const folder = B.backupFolder();
    const binfo = B.native ? B.backupInfo() : { mode: "none" };
    const autoMode = binfo.mode === "auto";
    const lastTxt = lastAutoBackup() ? T("\nآخر حفظ: {0}", new Date(+lastAutoBackup()).toLocaleString(root.I18N.lang)) : "";
    const autoCard = !B.native ? null : h("div", { class: "card" }, h("h2", null, ico("folder", 18), T("الحفظ التلقائي")),
      h("div", { class: "small", style: { marginBottom: "8px", whiteSpace: "pre-line" } }, autoMode
        ? T("مفعّل — بعد كل عمليةٍ تُحفظ نسخةٌ في ملف «{0}» داخل «المستندات» بجوالك", binfo.autoName || folder) + lastTxt
        : folder
          ? T("مفعّل — بعد كل عمليةٍ تُحفظ نسخةٌ في المجلد «{0}»", folder) + lastTxt
          : T("غير مفعّل. اختر مجلداً على الجوال (مثل Documents) يُحفظ فيه كل شيء تلقائياً — فتبقى بياناتك ولو حُذف التطبيق.")),
      h("div", { class: "muted small", style: { marginBottom: "10px" } }, autoMode
        ? T("بعد إعادة تثبيت التطبيق يظهر لك «استرجاع بياناتي» من هذا الملف مباشرة — فيعود كل شيء كما كان.")
        : T("بعد إعادة تثبيت التطبيق: «استرجاع من المجلد» ثم اختر المجلد نفسه — فيعود كل شيء كما كان.")),
      h("div", { class: "grid2" },
        h("button", { class: "btn" + (folder ? " ghost" : ""), onclick: () => B.pickBackupFolder() }, ico("folder", 18),
          autoMode ? T("اختيار مجلدٍ آخر") : folder ? T("تغيير المجلد") : T("اختيار المجلد")),
        h("button", { class: "btn ghost", onclick: () => B.restoreFromFolder() }, ico("history", 18), T("استرجاع من المجلد"))));
    const offF = onRoute("backupFolder", (r) => {
      if (r.ok) { toast(T("الحفظ التلقائي في «{0}»", r.name)); scheduleAutoBackup(); syncAllPhotos(); offF(); offR(); replace("settings"); }
      else if (r.error) err(new Error(r.error));
    });
    const offR = onRoute("restore", async (r) => {
      if (!r.ok) { if (r.error) err(new Error(r.error)); return; }
      try { if (await restoreText(r.text, r.file)) { B.restorePhotos(); offF(); offR(); replace("home"); } } catch (e) { err(e); }
    });
    v.append(
      h("div", { class: "card" }, h("h2", null, T("بيانات النشاط (تظهر في الفواتير)")),
        field(T("الاسم"), name), h("div", { style: { height: "8px" } }),
        h("div", { class: "grid2" }, field(T("الجوال"), phone), field(T("الرقم الضريبي"), vatNo)),
        h("div", { style: { height: "8px" } }), field(T("العنوان"), address)),
      h("div", { class: "card" }, h("h2", null, T("الحساب والعرض")),
        h("div", { class: "grid2" }, field(T("عيار العرض والمكافئ"), karat), field(T("نسبة خصم الأحجار %"), rate),
          field(T("المظهر"), theme), field(T("اللغة"), langSel)),
        h("label", { class: "switch" }, showBal, T("إظهار رصيد العميل في الفاتورة"))),
      h("button", { class: "btn block", onclick: save, style: { marginBottom: "12px" } }, T("حفظ الإعدادات")),
      autoCard,
      h("div", { class: "card" }, h("h2", null, ico("save", 18), T("نسخةٌ في ملف")),
        h("div", { class: "muted small", style: { marginBottom: "10px" } },
          T("نسخةٌ تحفظها أو ترسلها لنفسك (واتساب · درايف) — تنفع لنقل بياناتك إلى جوالٍ آخر.") +
          (S0.lastBackup ? T("\nآخر نسخة: {0}", dmy(S0.lastBackup.slice(0, 10))) : "")),
        h("div", { class: "grid2" },
          h("button", { class: "btn ghost", onclick: () => doBackup(false) }, ico("save", 18), T("حفظ ملف")),
          h("button", { class: "btn ghost", onclick: () => doBackup(true) }, ico("share", 18), T("مشاركة"))),
        h("button", { class: "btn ghost block", style: { marginTop: "8px" }, onclick: () => fileIn.click() }, ico("upload", 18), T("استرجاع من ملف")),
        fileIn),
      B.native ? h("button", { class: "btn ghost block", style: { marginBottom: "12px" }, onclick: updateSheet }, ico("update", 18), T("التحديثات")) : null,
      h("div", { class: "muted small", style: { textAlign: "center", margin: "16px 0" } },
        T("{0} · الإصدار {1} · {2} عميل · {3} مصنع · {4} فاتورة · {5} سند", APP_NAME, B.appVersion(), D.shopsOnly(s).length, D.factoriesOnly(s).length, s.invoices.length, s.vouchers.length)));
  }

  // ══ العملاء — المبيعات والتحصيل (كشاشة العملاء في البرنامج) ══
  function periodPresets() {
    const t = D.today(), ym = t.slice(0, 7);
    const d = new Date(+t.slice(0, 4), +t.slice(5, 7) - 2, 1);
    const prev = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const lastDay = (x) => `${x}-${String(new Date(+x.slice(0, 4), +x.slice(5, 7), 0).getDate()).padStart(2, "0")}`;
    return [[T("منذ البداية"), "", ""], [T("هذا الشهر"), ym + "-01", ""], [T("الشهر الماضي"), prev + "-01", lastDay(prev)],
      [T("هذه السنة"), t.slice(0, 4) + "-01-01", ""]];
  }
  function gradeBadge(g) {
    // ألوان التقدير كما في شاشة العملاء في البرنامج
    const cls = { "مسدَّد": "good", "ممتاز": "good", "جيد": "mid", "مقبول": "fair", "سيء": "bad" }[g];
    return h("span", { class: "badge grade " + (cls === undefined ? "none" : cls) }, T(g));
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
      h("button", { class: side === "gold" ? "on" : "", onclick: () => replace(url({ side: "gold" })) }, T("الذهب")),
      h("button", { class: side === "cash" ? "on" : "", onclick: () => replace(url({ side: "cash" })) }, T("النقد (ريال)")));
    const idle = h("input", { type: "checkbox", checked: hideIdle, onchange: (e) => replace(url({ all: e.target.checked ? "" : "1" })) });
    v.append(h("div", { class: "card" }, chips, h("div", { class: "grid2", style: { marginTop: "8px" } }, field(T("من"), fIn), field(T("إلى"), tIn)),
      h("div", { style: { marginTop: "10px" } }, sideSeg), h("label", { class: "switch" }, idle, T("إخفاء من لا حركة له"))));
    const b = D.board(s, from || null, to || null);
    const fmt = (x) => (side === "gold" ? gw(x) : f2(x));
    const unit = side === "gold" ? T("جم عيار {0}", k) : T("ريال");
    const TS = b[side];
    const rows = hideIdle ? b.rows.filter(D.hasMovement) : b.rows;
    const tile = (label, val, sub) => h("div", { class: "stat" }, h("span", { class: "l" }, label),
      h("span", { class: "v num" }, val), sub ? h("span", { class: "u" }, sub) : null);
    v.append(h("div", { class: "stats" },
      tile(T("العملاء"), String(rows.length)), tile(T("المبيعات"), fmt(TS.sales), unit), tile(T("المرتجع"), fmt(TS.returns),
        TS.retPct === null ? unit : `${f2(TS.retPct)}% · ${unit}`),
      tile(T("التحصيل"), fmt(TS.paid), TS.paidPct === null ? unit : `${f2(TS.paidPct)}% · ${unit}`), tile(T("الباقي"), fmt(TS.remaining), unit)));
    if (!rows.length) { v.append(h("div", { class: "empty" }, T("لا حركة في الفترة"))); return; }
    for (const r of rows) {
      const x = r[side];
      // كل عميلٍ بعيار حسابه — والمجاميع أعلاه بعيار المجاميع
      const rk = pk(D.shopById(s, r.id));
      const fr = (val) => (side === "gold" ? gw(val, rk) : f2(val));
      v.append(h("div", { class: "list-item col", onclick: () => go(`shop/${r.id}`) },
        h("div", { class: "spread" }, h("span", { class: "t" }, r.name), gradeBadge(x.grade)),
        h("div", { class: "grid3 small" },
          h("div", null, h("span", { class: "muted" }, T("الصافي")), h("b", { class: "num" }, fr(x.net))),
          h("div", null, h("span", { class: "muted" }, T("التحصيل")), h("b", { class: "num" }, fr(x.paid))),
          h("div", null, h("span", { class: "muted" }, T("الباقي")), h("b", { class: "num" }, fr(x.remaining)))),
        h("div", { class: "row small", style: { marginTop: "6px" } }, meter(x.paidPct),
          h("span", { class: "muted num", style: { minWidth: "48px", textAlign: root.I18N.end } }, x.paidPct === null ? "—" : `${f2(x.paidPct)}%`)),
        h("div", { class: "muted small" },
          r.lastPay ? [T("آخر تحصيل "), h("span", { dir: "ltr", text: dmy(r.lastPay) })] : T("لا تحصيل في الفترة"),
          r.lastSale ? [T(" · آخر بيع "), h("span", { dir: "ltr", text: dmy(r.lastSale) })] : null,
          x.open ? [T(" · رصيد سابق "), h("span", { class: "num", text: fr(x.open) })] : null)));
    }
  }

  // ══ الممتلكات: ما معي الآن (صندوقٌ لكل عيار · النقد · الأطقم)، ثم حساباتي ══
  function holdingsScreen() {
    const s = st(), k = vk();
    setBar(T("الممتلكات"), T("ما معي الآن"), { back: false, actions: [karatButton(), updateButton()] });
    setTab("holdings");
    const v = view();
    const hd = D.holdings(s);
    const oh = hd.open;
    const hasOpen = Object.keys(oh.gold).length || oh.cash || oh.sets.length;
    if (!hasOpen) {
      v.append(h("button", { class: "note-bar info open-cta", onclick: () => go("opening") },
        ico("coins", 18), h("span", { class: "grow" }, h("b", null, T("سجّل ما معك الآن")),
          h("span", { class: "muted small" }, T(" — ذهبٌ بعياره، ونقد، وأطقم في يدك قبل أول عملية (رصيد افتتاحي)"))),
        ico("chevron", 18, "muted")));
    }

    // ── لوحة «المديونية والذهب الذي معي» (1.11): لكل عيارٍ ما معي (الكسر)، وما لي
    // عند العملاء، وما عليّ للمصانع — ثم النقد، ثم المجموع بعيار المجاميع ──
    const ex = D.exposure(s);
    v.append(debtCard(s, hd, ex, k));

    // ── معي الآن: صندوقٌ لكل عيار بوزنه في عياره، والنقد ──
    const tile = (icon, title, val, unit, sub, onclick, neg, cls) => h("button", { class: "box-tile" + (cls ? " " + cls : ""), onclick },
      h("div", { class: "spread" }, h("span", { class: "box-ic" }, ico(icon, 20)), ico("chevron", 18, "muted")),
      h("div", { class: "box-t" }, title),
      h("div", { class: "box-v" + (neg ? " bal-on" : "") }, h("span", { class: "num" }, val), h("span", { class: "u" }, " " + unit)),
      sub ? h("div", { class: "muted small" }, sub) : null);
    const grid = h("div", { class: "boxes" });
    for (const b of hd.boxes) {
      grid.append(tile("coins", T("ذهب عيار {0}", b.karat), f2(b.weight), T("جم"),
        (b.open ? T("افتتاحي {0} · ", f2(b.open)) : "") + T("حصّلت {0} · دفعت {1}", f2(b.inSum), f2(b.outSum)), () => boxSheet(b), b.weight < -0.0005));
    }
    if (hd.cash.moves.length) {
      grid.append(tile("receipt", T("النقد والأجور"), f2(hd.cash.amount), T("ريال"),
        (hd.cash.open ? T("افتتاحي {0} · ", f2(hd.cash.open)) : "") + T("حصّلت {0} · دفعت {1}", f2(hd.cash.inSum), f2(hd.cash.outSum)),
        () => cashSheet(hd.cash), hd.cash.amount < -0.005));
    }
    v.append(h("div", { class: "sec-title" }, T("معي الآن")));
    if (grid.children.length) v.append(grid);
    else {
      v.append(h("div", { class: "note-bar info", style: { margin: "0 0 12px" } },
        T("ما تحصّله من العملاء يظهر هنا في صندوق عياره، والنقد في صندوقه. وما تسدّده للمصانع يُخصم منها.")));
    }
    // (الأطقم التي معي انتقلت إلى لوحات الرئيسية — 1.11)
    const big = (cls, icon, title, val, unit, sub, onclick) => h("button", { class: "wide-tile big " + cls, onclick },
      h("span", { class: "op-ic" }, ico(icon, 24)),
      h("span", { class: "grow" }, h("span", { class: "op-t" }, title),
        h("span", { class: "big-v" }, h("span", { class: "num" }, val), h("span", { class: "u" }, unit)),
        h("span", { class: "op-h" }, sub)),
      ico("chevron", 20, "muted"));

    // ── حساباتي: لي عند العملاء، وعليّ للمصانع — كلٌّ بعياره داخل القائمة ──
    const facN = ex.factories.filter((x) => x.owe18 > 0.0005 || x.oweCash > 0.005).length;
    const cusN = ex.customers.filter((x) => x.gold18 > 0.0005 || x.cash > 0.005).length;
    v.append(h("div", { class: "sec-title" }, T("حساباتي")),
      big("cus", "users", T("لي عند العملاء"), gw(ex.cusGold18, k), T(" جم عيار {0}", k),
        T("وأجور {0} ريال · {1} عميل — اضغط لترى كل عميل بعياره", f2(ex.cusCash), cusN), () => customersSheet(ex)),
      big("fac", "package", T("عليّ للمصانع"), gw(ex.facGold18, k), T(" جم عيار {0}", k),
        T("ونقد {0} ريال · {1} مصنع — اضغط لترى كل مصنع بعياره", f2(ex.facCash), facN), () => factoriesSheet(ex)));
    v.append(h("div", { class: "quick" },
      quickBtn("in", T("تحصيل من العميل"), () => go("voucher/new?kind=receipt")),
      quickBtn("out", T("سداد للمصنع"), () => go("voucher/new?kind=payment")),
      quickBtn("coins", T("الرصيد الافتتاحي"), () => go("opening"))));
  }

  // لوحة المديونية: جدولٌ صغير — العيار · معي (كسر) · لي عند العملاء · عليّ للمصانع.
  // ولمس الخانة يفتح تفصيلها: صندوق العيار، أو العملاء، أو المصانع
  function debtCard(s, hd, ex, k) {
    const ds = D.debtSummary(s, k, true);
    const cell = (val, dec, onclick) => {
      const z = Math.abs(val) < (dec === 2 ? 0.005 : 0.0005);
      return h("td", { class: (z ? "z" : val < 0 ? "neg" : "") + (onclick && !z ? " tap" : ""), onclick: z ? null : onclick },
        z ? "—" : h("span", { class: "num", dir: "ltr" }, (val < 0 ? "−" : "") + f2(Math.abs(val))));
    };
    const tbody = h("tbody");
    for (const r of ds.rows) {
      const box = hd.boxes.find((b) => b.karat === r.karat);
      tbody.append(h("tr", null, h("td", { class: "k" }, T("عيار {0}", r.karat), h("small", null, T("جم"))),
        cell(r.inHand, 3, box ? () => boxSheet(box) : null),
        cell(r.cust, 3, () => customersSheet(ex)), cell(r.fac, 3, () => factoriesSheet(ex))));
    }
    const c = ds.cash;
    if (Math.abs(c.inHand) > 0.005 || c.cust > 0.005 || c.fac > 0.005) {
      tbody.append(h("tr", { class: "cash" }, h("td", { class: "k" }, T("النقد"), h("small", null, T("ريال"))),
        cell(c.inHand, 2, hd.cash.moves.length ? () => cashSheet(hd.cash) : null),
        cell(c.cust, 2, () => customersSheet(ex)), cell(c.fac, 2, () => factoriesSheet(ex))));
    }
    // المجموع بعيار المجاميع حين تتعدّد العيارات (لا يُطرح منه شيء: كلٌّ في خانته)
    if (ds.rows.length > 1) {
      const t = ds.total18, g = (x) => G.g(x, k);
      tbody.append(h("tr", { class: "tot" }, h("td", { class: "k" }, T("المجموع"), h("small", null, T("جم عيار {0}", k))),
        cell(g(t.inHand), 3), cell(g(t.cust), 3), cell(g(t.fac), 3)));
    }
    const card = h("div", { class: "card debt-card" }, h("h2", null, ico("scale", 18), T("المديونية والذهب الذي معي")));
    if (!tbody.children.length) {
      card.append(h("div", { class: "muted small" }, T("لا ذهب معك ولا ديون بعد — يظهر هنا كل عيارٍ وحده: ما معك، وما لك عند العملاء، وما عليك للمصانع.")));
      return card;
    }
    card.append(h("table", { class: "debt-tbl" },
      h("thead", null, h("tr", null, h("th", null, T("العيار")), h("th", null, T("معي (كسر)")),
        h("th", null, T("لي عند العملاء")), h("th", null, T("عليّ للمصانع")))), tbody),
      h("div", { class: "muted small debt-hint" }, T("ما معي: كل عيارٍ بوزنه في صندوقه — وما عند العملاء وما عليّ للمصانع بعيار العرض ({0}). اضغط على أي رقمٍ لتفصيله.", vk())));
    return card;
  }

  // ══ الرصيد الافتتاحي للممتلكات: ما كان معي قبل أول عملية في التطبيق ══
  function openingScreen() {
    const s = st();
    setBar(T("الرصيد الافتتاحي"), T("ما كان معك قبل التطبيق"), { noTabs: true });
    const v = view();
    const oh = D.openHold(s);
    const date = h("input", { class: "in", type: "date", value: oh.date || D.today() });
    const goldIns = {};
    for (const x of G.KARATS) goldIns[x] = numInput({ value: oh.gold[x] || 0 });
    const cashIn = numInput({ value: oh.cash });
    // الأطقم: اسمٌ (الطقم هو المسمّى — 1.11)، وعيار، ووزن (بعياره) — وما خرج منها بفاتورةٍ لا يُحذف
    const used = new Set();
    for (const d of s.invoices) for (const l of d.lines) if (l.src && l.src.startsWith("op:")) used.add(l.src.slice(3));
    const rows = oh.sets.map((x) => ({ id: x.id, name: x.name, karat: x.karat, weight: G.g(x.w18, x.karat), photos: x.photos }));
    const setsBox = h("div");
    const renderSets = () => {
      setsBox.innerHTML = "";
      if (!rows.length) setsBox.append(h("div", { class: "muted small", style: { margin: "4px 0 8px" } }, T("لا أطقم — اضغط «+ طقم» لكل طقمٍ في يدك.")));
      rows.forEach((r, i) => {
        const nm = h("input", { class: "in", value: r.name || "", placeholder: T("اسم الطقم"), dir: "auto",
          oninput: (e) => { r.name = e.target.value; } });
        const ks = h("select", { class: "in" }, G.KARATS.map((x) => h("option", { value: x, text: T("عيار {0}", x) })));
        ks.value = String(r.karat);
        ks.addEventListener("change", () => { r.karat = parseInt(ks.value, 10); });
        const w = numInput({ value: r.weight });
        w.addEventListener("input", () => { r.weight = w.getVal(); });
        const sold = r.id && used.has(r.id);
        setsBox.append(h("div", { class: "line" },
          h("div", { class: "top" }, h("b", { class: "grow" }, T("طقم {0}", i + 1)),
            sold ? h("span", { class: "badge" }, T("خرج بفاتورة"))
              : h("div", { class: "act" }, h("button", { class: "del", "aria-label": T("حذف الطقم {0}", i + 1),
                onclick: () => { rows.splice(i, 1); renderSets(); } }, ico("x", 17)))),
          h("div", { style: { marginTop: "6px" } }, nm),
          h("div", { class: "grid2", style: { marginTop: "6px" } }, field(T("الوزن (جم)"), w), field(T("العيار"), ks))));
      });
    };
    renderSets();
    v.append(
      h("div", { class: "note-bar info", style: { marginBottom: "12px" } },
        T("اكتب ما كان معك قبل أول عمليةٍ تسجّلها في التطبيق — فيبدأ منه «معي الآن». ") +
        T("أمّا ما لك عند كل عميل وما عليك لكل مصنع فيُكتب في «رصيد افتتاحي» داخل حسابه.")),
      h("div", { class: "card" }, h("h2", null, ico("coins", 18), T("ذهبٌ في يدي (كل عيارٍ بوزنه)")),
        h("div", { class: "grid2" }, ...G.KARATS.map((x) => field(T("عيار {0} (جم)", x), goldIns[x])))),
      h("div", { class: "card" }, h("h2", null, ico("receipt", 18), T("نقدٌ في يدي")), field(T("المبلغ (ريال)"), cashIn)),
      h("div", { class: "card" }, h("h2", null, ico("gem", 18), T("أطقمٌ في يدي")),
        h("div", { class: "muted small", style: { marginBottom: "6px" } }, T("الطقم يُعرف باسمه — وما معك وزناً بلا اسمٍ اكتبه في «ذهبٌ في يدي» بعياره.")), setsBox,
        h("button", { class: "btn ghost block", onclick: () => { rows.push({ name: "", karat: vk(), weight: 0 }); renderSets(); } }, T("+ طقم"))),
      h("div", { class: "card" }, field(T("بتاريخ"), date),
        h("div", { class: "row", style: { marginTop: "10px", flexWrap: "wrap" } },
          h("button", { class: "btn ghost sm", onclick: () => go("customers") }, ico("users", 16), T("أرصدة العملاء")),
          h("button", { class: "btn ghost sm", onclick: () => go("customers?view=factories") }, ico("package", 16), T("أرصدة المصانع")))));
    const save = async () => {
      try {
        const gold = {};
        for (const x of G.KARATS) {
          const g = goldIns[x].getVal();
          if (!isFinite(g) || g < 0) throw new Error(T("وزنٌ غير صحيح لعيار {0}", x));
          gold[x] = g;
        }
        const cash = cashIn.getVal();
        if (!isFinite(cash) || cash < 0) throw new Error(T("مبلغ النقد غير صحيح"));
        if (rows.some((r) => !isFinite(r.weight))) throw new Error(T("رقمٌ غير صحيح في وزن أحد الأطقم"));
        const prev = JSON.stringify(s.settings.openHold || null);
        D.saveOpenHold(s, { date: date.value || D.today(), gold, cash, sets: rows });
        if (await persist(S.meta(s))) { toast(T("حُفظ الرصيد الافتتاحي")); replace("holdings"); }
        else s.settings.openHold = JSON.parse(prev);
      } catch (e) { err(e); }
    };
    v.append(h("div", { class: "footer-bar" }, h("button", { class: "btn", onclick: save }, T("حفظ"))));
  }

  // كل طقمٍ معي: اسمه ووزنه ومن أين جاء — و«معاينة» تفتح صوره كلٌّ وحدها
  function piecesSheet(hd) {
    const k = vk();
    return sheet((box) => {
      box.append(h("h3", null, ico("gem", 20), T(" الأطقم التي معي")),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          sumRow(T("عددها"), T("{0} طقم", hd.pieces.length)),
          sumRow(T("وزنها"), T("{0} جم عيار {1}", gw(hd.setsW18), k), "grand")));
      if (!hd.pieces.length) box.append(h("div", { class: "empty" }, T("لا أطقم معك الآن")));
      for (const p of hd.pieces) {
        const has = D.linePhotos(p.line).length > 0;
        box.append(h("div", { class: "list-item pc-row", onclick: () => { if (has) piecePhotos(p); } },
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t", dir: "auto" }, p.name || T("طقمٌ بلا اسم")),
              h("b", { class: "num" }, T("{0} جم", f2(G.g(p.w18, p.karat))))),
            h("div", { class: "muted small" }, pieceFromEl(p, T("عيار {0} · ", p.karat)))),
          piecePreview(p)));
      }
    });
  }

  // كل مصنع: كم أخذتُ منه، وكم أرجعتُ وسدّدتُ، وكم عليّ له الآن
  async function factoriesSheet(ex) {
    const k = vk();
    const id = await sheet((box, close) => {
      box.append(h("h3", null, ico("package", 20), T(" عليّ للمصانع")),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          sumRow(T("عليّ للمصانع ذهباً"), T("{0} جم عيار {1}", gw(ex.facGold18), k), "grand"),
          sumRow(T("وعليّ نقداً"), T("{0} ريال", f2(ex.facCash)))));
      if (!ex.factories.length) box.append(h("div", { class: "empty" }, T("لا مصانع بعد")));
      for (const x of ex.factories) {
        const pk1 = pk(x.party);
        box.append(h("div", { class: "list-item", onclick: () => close(x.party.id) },
          h("span", { class: "avatar fac" }, ico("package", 18)),
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t" }, x.party.name), goldBal(-x.owe18, true, pk1)),
            h("div", { class: "muted small" }, T("أخذتُ {0} · أرجعتُ {1} · سدّدتُ {2} جم عيار {3}", gw(x.took18, pk1), gw(x.back18, pk1), gw(x.paid18, pk1), pk1)),
            Math.abs(x.oweCash) > 0.005 ? h("div", { class: "small" }, T("نقد: "), cashBal(-x.oweCash, true)) : null)));
      }
    });
    if (id) setTimeout(() => go(`statement/${id}`), 30);
  }
  // كل عميل: كم عنده من ذهبي، وكم عليه نقداً
  async function customersSheet(ex) {
    const k = vk();
    const id = await sheet((box, close) => {
      box.append(h("h3", null, ico("users", 20), T(" لي عند العملاء")),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          sumRow(T("عند العملاء ذهباً"), T("{0} جم عيار {1}", gw(ex.cusGold18), k), "grand"),
          sumRow(T("وعليهم أجور ونقد"), T("{0} ريال", f2(ex.cusCash)))));
      if (!ex.customers.length) box.append(h("div", { class: "empty" }, T("لا عملاء بعد")));
      for (const x of ex.customers) {
        box.append(h("div", { class: "list-item", onclick: () => close(x.party.id) },
          h("span", { class: "avatar" }, x.party.name.trim()[0] || T("؟")),
          h("div", { class: "grow" },
            h("div", { class: "spread" }, h("span", { class: "t" }, x.party.name), goldBal(x.gold18, false, pk(x.party))),
            h("div", { class: "small" }, T("أجور ونقد: "), cashBal(x.cash)))));
      }
    });
    if (id) setTimeout(() => go(`statement/${id}`), 30);
  }

  // حركة صندوق: من أين دخل، وإلى من خرج، وكم، ومتى
  function movesList(moves, fmt, close) {
    const list = h("div");
    if (!moves.length) list.append(h("div", { class: "empty" }, T("لا حركة")));
    for (const m of moves) {
      const to = m.opening ? "opening" : `doc/vo/${m.doc.id}`;
      list.append(h("div", { class: "list-item", onclick: () => { close(); setTimeout(() => go(to), 30); } },
        h("span", { class: "avatar" + (m.sign < 0 ? " ret" : "") }, ico(m.opening ? "coins" : m.sign > 0 ? "in" : "out", 18)),
        h("div", { class: "grow" },
          h("div", { class: "spread" }, h("span", { class: "t" }, m.opening ? T("رصيد افتتاحي") : m.party ? m.party.name : "—"),
            h("b", { class: "num " + (m.sign > 0 ? "bal-for" : "bal-on") }, (m.sign > 0 ? "+" : "−") + fmt(m))),
          h("div", { class: "spread muted small" },
            m.opening ? h("span", null, T("ما كان معي قبل التطبيق"))
              : h("span", null, (m.sign > 0 ? T("تحصيل") : T("دفع")) + " · ", h("span", { dir: "ltr", text: m.doc.no })),
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
      box.append(h("h3", null, ico("coins", 20), T(" صندوق ذهب عيار {0}", b.karat)),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          b.open ? sumRow(T("رصيد افتتاحي"), T("{0} جم", f2(b.open))) : null,
          sumRow(T("حصّلته من العملاء"), T("{0} جم", f2(b.inSum))), sumRow(T("دفعته للمصانع"), T("{0} جم", f2(b.outSum))),
          sumRow(T("معي الآن"), T("{0} جم", f2(b.weight)), "grand"),
          b.karat !== vk() ? h("div", { class: "muted small" }, T("= {0} جم مكافئ عيار {1}", gw(G.store(b.weight, b.karat)), vk())) : null),
        movesList(b.moves, (m) => T("{0} جم", f2(m.weight)), close));
    });
  }
  function cashSheet(c) {
    return sheet((box, close) => {
      box.append(h("h3", null, ico("receipt", 20), T(" صندوق النقد والأجور")),
        h("div", { class: "totals", style: { marginBottom: "10px" } },
          c.open ? sumRow(T("رصيد افتتاحي"), T("{0} ريال", f2(c.open))) : null,
          sumRow(T("حصّلته من العملاء"), T("{0} ريال", f2(c.inSum))), sumRow(T("دفعته للمصانع"), T("{0} ريال", f2(c.outSum))),
          sumRow(T("معي الآن"), T("{0} ريال", f2(c.amount)), "grand")),
        movesList(c.moves, (m) => T("{0} ريال", f2(m.amount)), close));
    });
  }
  // ══ التحديثات ══
  // 1.13: زرّ العيار أعلى الشاشة — عيار العرض والمكافئ للتطبيق كله
  function karatButton() {
    return h("button", { class: "k-chip", "aria-label": T("عيار العرض"), onclick: karatSheet },
      ico("coins", 16), h("span", null, T("عيار {0}", vk())), " ▾");
  }
  async function karatSheet() {
    const s = st(), cur = vk();
    const k = await sheet((box, close) => {
      box.append(h("h3", null, ico("coins", 20), T(" عيار العرض والمكافئ")),
        h("div", { class: "muted small", style: { marginBottom: "10px" } },
          T("به تظهر كل الأوزان والأرصدة والمكافئات: الكشوف والفواتير والتحصيل والسداد والممتلكات.")),
        h("div", { class: "k-grid" }, G.KARATS.map((x) => h("button", { class: "chip" + (x === cur ? " on" : ""),
          onclick: () => close(x) }, T("عيار {0}", x)))));
    });
    if (!k || k === cur) return;
    s.settings.viewKarat = k;
    if (await persist(S.meta(s))) { toast(T("العرض الآن بعيار {0}", k)); route(); }
  }
  function updateButton() {
    const us = B.updateState();
    const btn = h("button", { class: "icon-btn upd" + (us.available ? " dot" : ""), id: "upd-btn",
      "aria-label": T("التحديثات"), onclick: updateSheet }, ico("update", 20));
    if (us.unsupported) btn.style.display = "none";
    return btn;
  }
  function refreshUpdateDot(us) {
    const b = document.getElementById("upd-btn");
    if (b) b.classList.toggle("dot", !!(us && us.available));
  }
  // ══ «يوجد تحديث جديد» في وسط الشاشة — حين يُنشر إصدار: شعارٌ وزرٌّ كبير «حدّث الآن» يُنزّل
  //    ويثبّت مباشرة. مرةً في كل فتحٍ للتطبيق، وفي شاشات التصفّح وحدها (لا يقطع فاتورةً تُكتب) ══
  let popShown = "";
  function maybeUpdatePop(us) {
    if (!B.native) {
      if (webWaiting && popShown !== "web" && AD_SCREENS.has(parse().parts[0] || "home")) {
        popShown = "web";
        const w = webWaiting;
        fetch("version.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({}))
          .then((vj) => updatePop({ published: { version: vj.name || "" } }, () => w.postMessage("skipWaiting")));
      }
      return;
    }
    us = us || B.updateState();
    if (!us || us.unsupported || !us.available || !us.published || !us.published.version || updateOpen) return;
    if (popShown === us.published.version || !AD_SCREENS.has(parse().parts[0] || "home")) return;
    popShown = us.published.version;
    updatePop(us);
  }
  function updatePop(us, webGo) {
    const pub = us.published;
    const offs = [];
    sheet((box, close) => {
      box.classList.add("pop");
      if (box.parentNode) box.parentNode.classList.add("center");
      const prog = h("div", { class: "progress", style: { display: "none" } }, h("span"));
      const note = h("div", { class: "muted small pop-note" });
      const go = h("button", { class: "btn block big", onclick: () => {
        go.disabled = true;
        if (webGo) { note.textContent = T("جارٍ التحديث…"); webGo(); return; }
        note.textContent = T("جارٍ التنزيل…");
        prog.style.display = "";
        B.installUpdate();
      } }, ico("update", 20), T("حدّث الآن"));
      box.append(
        h("img", { src: "img/icon.png", alt: "", class: "pop-logo" }),
        h("h3", null, T("يوجد تحديث جديد")),
        pub.version ? h("div", { class: "muted" }, T("الإصدار {0}", pub.version)) : null,
        pub.notes ? h("div", { class: "small pop-notes" }, pub.notes) : null,
        go, prog, note,
        h("button", { class: "btn ghost block sm", onclick: () => close() }, T("لاحقاً")));
      offs.push(B.on("updateProgress", (p) => {
        prog.style.display = "";
        prog.firstChild.style.width = (p.pct || 0) + "%";
        note.textContent = T("جارٍ التنزيل… {0}%", p.pct || 0);
      }));
      offs.push(B.on("update", (u) => {
        if (u.error) { note.textContent = root.I18N.TX(u.error); go.disabled = false; prog.style.display = "none"; }
        else if (u.ready) { note.textContent = T("اضغط «تثبيت» في نافذة أندرويد — بياناتك تبقى كما هي."); go.disabled = false; }
      }));
    }).then(() => offs.forEach((f) => f()));
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
      box.append(h("h3", null, ico("update", 20), T(" التحديثات")), body, prog, note);
      const render = (us) => {
        body.innerHTML = "";
        if (us.unsupported) {
          body.append(h("div", { class: "muted" }, T("التحديث التلقائي يعمل في تطبيق أندرويد.")));
          return;
        }
        const pub = us.published && us.published.code ? us.published : null;
        body.append(h("div", { class: "spread" }, h("span", null, T("الإصدار المثبّت")), h("b", { class: "num" }, us.version)));
        if (us.available && pub) {
          body.append(h("div", { class: "update-card" },
            h("div", { class: "spread" }, h("b", null, T("إصدارٌ جديد {0}", pub.version)), ico("sparkles", 20)),
            pub.notes ? h("div", { class: "small", style: { whiteSpace: "pre-line", marginTop: "6px" } }, pub.notes) : null,
            h("button", { class: "btn block", style: { marginTop: "10px" }, onclick: () => {
              note.textContent = T("جارٍ التنزيل…");
              prog.style.display = "";
              B.installUpdate();
            } }, ico("update", 18), us.ready ? T("تثبيت التحديث الآن") : T("تنزيل التحديث وتثبيته")),
            h("div", { class: "muted small", style: { marginTop: "6px" } },
              T("يُنزَّل من GitHub ويُتحقَّق من بصمته، ثم يطلب أندرويد تأكيد التثبيت بلمسة. بياناتك تبقى كما هي."))));
        } else {
          body.append(h("div", { class: "ok-line" }, ico("check", 18), T(" أنت على آخر إصدارٍ منشور")));
        }
        if (us.lastCheck) body.append(h("div", { class: "muted small" }, T("آخر فحص: ") + new Date(us.lastCheck).toLocaleString(root.I18N.lang)));
        if (us.error) body.append(h("div", { class: "note-bar warn" }, root.I18N.TX(us.error)));
        body.append(h("button", { class: "btn ghost block sm", style: { marginTop: "8px" }, onclick: () => {
          note.textContent = T("جارٍ الفحص…");
          B.checkUpdate();
        } }, ico("refresh", 18), T("تحقّق الآن")));
        if (!us.canNotify) {
          body.append(h("button", { class: "btn ghost block sm", style: { marginTop: "8px" }, onclick: () => B.requestNotifications() },
            ico("bell", 18), T("تفعيل إشعار التحديث")));
        }
      };
      offs.push(B.on("update", (us) => {
        note.textContent = us.error && !us.version ? root.I18N.TX(us.error) : "";
        prog.style.display = "none";
        if (us.version) render(us);
        refreshUpdateDot(us);
      }));
      offs.push(B.on("updateProgress", (p) => {
        prog.style.display = "";
        prog.firstChild.style.width = (p.pct || 0) + "%";
        note.textContent = T("جارٍ التنزيل… {0}%", p.pct || 0);
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
    try { obj = JSON.parse(text); } catch (e) { throw new Error(T("الملف تالف أو ليس نسخةً احتياطية")); }
    const ns = D.fromBackup(obj);
    const msg = T("استرجاع {0} ({1}):\n", label || T("النسخة"), (obj.savedAt || "").slice(0, 10)) +
      T("{0} عميل · {1} فاتورة · {2} سند\n\n", ns.shops.length, ns.invoices.length, ns.vouchers.length) +
      T("تُستبدل بها البيانات الحالية في هذا الجوال.");
    if (!(await confirmSheet(msg, T("استرجاع"), true))) return false;
    await S.replaceAll(ns);
    await importPhotos(D.backupPhotos(obj));
    App.state = ns;
    applyTheme();
    toast(T("استُرجعت البيانات"));
    return true;
  }

  // ══ الترحيب (أول تشغيل) ══
  // أندرويد 10+: ملف «ÀUR» في «المستندات» يُنشأ وحده من أول تشغيل ويُحفظ فيه كل شيء — وبعد
  // إعادة التثبيت يُعرض الاسترجاع منه مباشرة. والأقدم: اختيار مجلدٍ كما كان.
  function welcome() {
    setBar(T("أهلاً بك"), "", { back: false, noTabs: true });
    const v = view();
    const info = B.backupInfo();
    const AUR = info.autoName || APP_NAME;
    const done = () => { try { localStorage.setItem("welcomed", "1"); } catch (e) { /* */ } B.requestNotifications(); replace("home"); };
    const waitFolder = onRoute("backupFolder", (r) => { if (r.ok) { toast(T("الحفظ التلقائي في «{0}»", r.name)); syncAllPhotos(); waitFolder(); waitRestore(); done(); } });
    const waitRestore = onRoute("restore", async (r) => {
      if (!r.ok) { if (r.error) err(new Error(r.error)); return; }
      try {
        if (await restoreText(r.text, r.file)) {
          B.startAuto();          // الحفظ مستمرٌّ في ملف «ÀUR» نفسه (أو المجلد المختار)
          restorePhotosChecked(); waitFolder(); waitRestore(); done();
        }
      } catch (e) { err(e); }
    });
    // «ابدأ»: الحفظ التلقائي في ملف «ÀUR» — ويُنشأ الملف الآن. وفوق ملفٍ سابق («ابدأ من جديد»)
    // تبقى نسخته الأخيرة باسمٍ آخر، فلا يُكتب فوق بيانات أحدٍ أبداً
    const start = (fresh) => {
      if (fresh) B.startFresh(); else B.startAuto();
      B.autoBackup(JSON.stringify(D.toBackup(st())));
      waitFolder(); waitRestore(); done();
    };
    const head = [
      h("div", { class: "lang-top" }, langChip()),
      h("img", { src: "img/icon.png", alt: "", class: "welcome-logo" }),
      h("h2", null, APP_NAME),
      h("div", { class: "muted" }, T("حساباتك مع العملاء والمصانع"))];
    let body;
    if (info.mode === "found") {
      body = [
        h("p", null, T("وجدنا ملف «{0}» من استخدامك السابق في «المستندات» بجوالك — فيه بياناتك كلها.", AUR)),
        h("button", { class: "btn block", onclick: () => (info.readable ? B.restoreAuto() : B.restoreFromFolder()) },
          ico("history", 20), T("استرجاع بياناتي")),
        info.readable ? null
          : h("div", { class: "muted small" }, T("تُفتح نافذة المجلد على «{0}» مباشرة: اضغط «استخدام هذا المجلد» ثم «سماح».", AUR)),
        h("button", { class: "link", style: { marginTop: "12px" }, onclick: () => start(true) }, T("ابدأ من جديد بلا بيانات"))];
    } else if (info.mode === "auto") {
      body = [
        h("p", { class: "muted" }, T("بياناتك في جوالك وحده، وتُحفظ تلقائياً بعد كل عملية في ملفٍ باسم «{0}» داخل «المستندات» — ", AUR) +
          T("فإن حذفت التطبيق ثم ثبّته من جديد، تعود منه بياناتك كلها.")),
        h("button", { class: "btn block", onclick: () => start(false) }, ico("check", 20), T("ابدأ")),
        h("button", { class: "btn ghost block", onclick: () => B.restoreFromFolder() }, ico("history", 20), T("عندي بيانات سابقة — استرجاعها"))];
    } else {
      body = [
        h("p", { class: "muted" }, T("بياناتك في جوالك وحده. اختر مجلداً يُحفظ فيه كل شيءٍ تلقائياً بعد كل عملية — ") +
          T("فإن حذفت التطبيق ثم ثبّته من جديد، اختر المجلد نفسه فيعود كل شيء كما كان.")),
        h("button", { class: "btn block", onclick: () => B.pickBackupFolder() }, ico("folder", 20), T("ابدأ — اختر مجلد الحفظ التلقائي")),
        h("button", { class: "btn ghost block", onclick: () => B.restoreFromFolder() }, ico("history", 20), T("عندي بيانات سابقة — استرجاعها")),
        h("button", { class: "link", style: { marginTop: "12px" }, onclick: () => { waitFolder(); waitRestore(); done(); } }, T("تخطَّ الآن"))];
    }
    v.append(h("div", { class: "welcome" }, ...head, ...body));
  }

  // ══ «+ جديد» ══
  async function newSheet() {
    const r = await sheet((box, close) => {
      box.append(h("h3", null, T("عملية جديدة")),
        h("div", { class: "sec-title" }, T("مع العملاء")),
        h("div", { class: "quick" },
          quickBtn("receipt", T("فاتورة بيع"), () => close("invoice/new?kind=sale")),
          quickBtn("return", T("مرتجع"), () => close("invoice/new?kind=sale_return")),
          quickBtn("in", T("تحصيل"), () => close("voucher/new?kind=receipt"))),
        h("div", { class: "sec-title" }, T("مع المصانع")),
        h("div", { class: "quick" },
          quickBtn("out", T("سداد للمصنع"), () => close("voucher/new?kind=payment")),
          quickBtn("package", T("بضاعة من مصنع"), () => close("invoice/new?kind=purchase")),
          quickBtn("return", T("إرجاع للمصنع"), () => close("invoice/new?kind=purchase_return"))),
        h("div", { class: "sec-title" }, T("حساب جديد")),
        h("div", { class: "quick" },
          quickBtn("store", T("عميل جديد"), () => close("shop-form")),
          quickBtn("package", T("مصنع جديد"), () => close("shop-form?type=factory")),
          quickBtn("search", T("بحث عن طقم"), () => close("wo"))));
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

  const AD_SCREENS = new Set(["home", "shops", "customers", "holdings", "today", "dashboard", "shop",
    "doc", "statement", "log", "more"]);
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
    // الإعلان (شريطٌ صغير أسفل الشاشة) في شاشات التصفّح وحدها — لا في الإدخال
    // ولا البحث ولا الترحيب، فلا يُلمس خطأً ولا يزاحم لوحة المفاتيح
    B.setAds(AD_SCREENS.has(parts[0] || "home"));
    setTimeout(() => maybeUpdatePop(), 700);
    if (isWeb()) { if (AD_SCREENS.has(parts[0] || "home")) setTimeout(showBackupBar, 900); else hideBackupBar(); }
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
        case "opening": return openingScreen();
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

  // فحص التحديث عند كل فتحٍ للتطبيق وعودته من الخلفية — بحدّ دقيقتين بين فحصين، فإصدارٌ نُشر
  // للتوّ تظهر نافذته في أول فتحٍ بعده (لا بعد نصف ساعة)
  function maybeCheckUpdate() {
    const us = B.updateState();
    if (us.unsupported) return;
    if (Date.now() - (us.lastCheck || 0) > 2 * 60 * 1000) B.checkUpdate();
  }

  function firstRun() {
    const s = st();
    if (!B.native || B.backupInfo().mode === "tree") return false;
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
    B.on("update", (us) => { refreshUpdateDot(us); maybeUpdatePop(us); });
    let lastBackupErr = 0;
    B.on("backupDone", (r) => {
      if (r.ok) {
        try { localStorage.setItem("lastAutoBackup", String(r.at)); } catch (e) { /* */ }
      } else if (Date.now() - lastBackupErr > 60000) {   // تنبيهٌ واحد في الدقيقة لا مع كل حفظ
        lastBackupErr = Date.now();
        toast(T("تعذّر الحفظ التلقائي في المجلد: ") + (r.error || "") + T("\nاختر المجلد من جديد في الإعدادات."), "err");
      }
    });
    // صور المجلد: ما نقص منه يُكتب، وما يُسترجع منه يُحفظ
    B.on("photosMissing", async (r) => {
      for (const id of r.ids || []) { const d = await S.getPhoto(id); if (d) B.savePhoto(id, d.split(",")[1] || ""); }
    });
    B.on("photo", (r) => { if (r.id && r.b64) S.putPhoto(r.id, "data:image/jpeg;base64," + r.b64); });
    B.on("photosDone", (r) => { if (r.n) toast(T("استُرجعت {0} صورة", r.n)); });
    setTimeout(syncAllPhotos, 4000);
    // الرعاة: يُقرأ ملفهم كل 6 ساعات، وتُعاد الرئيسية إن تغيّر
    const promo = () => root.Promo && root.Promo.refresh().then((changed) => {
      if (changed && ["home", "more"].includes(parse().parts[0])) route();
    });
    setTimeout(promo, 1500);
    // العودة إلى التطبيق بعد غيابٍ (10 دقائق فأكثر) فتحٌ جديد: نافذة «يوجد تحديث» تظهر من جديد إن
    // لم يُثبَّت بعد — لا مرةً واحدة طوال بقاء التطبيق في ذاكرة الجوال
    let hiddenAt = 0;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      if (hiddenAt && Date.now() - hiddenAt >= 10 * 60 * 1000) { popShown = ""; setTimeout(() => maybeUpdatePop(), 700); }
      maybeCheckUpdate(); promo();
    });
    window.addEventListener("hashchange", route);
    webSetup();
    // مجلد «ÀUR» من تثبيتٍ سابق، والتطبيق ليس في أول تشغيله (فيه بيانات): الحفظ فيه من الآن
    if (B.native && !firstRun() && B.backupInfo().mode === "found") B.startAuto();
    if (firstRun()) location.replace("#/welcome");
    else if (!location.hash) location.replace("#/home");
    route();
    maybeCheckUpdate();
  }

  App.start = start;
  App.go = go;
  document.addEventListener("DOMContentLoaded", start);
})(window);
