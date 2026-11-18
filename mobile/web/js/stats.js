/* إحصاءات الاستخدام — في الخلفية بلا أي شاشةٍ أو زرّ أو إشعار.
 * رسالةٌ صغيرة (أقل من 200 بايت) إلى خادم الموقع (Cloudflare، لا سحابة Supabase):
 *   i  رقمٌ عشوائي يصنعه التطبيق عند أول فتح (لا يدلّ على صاحبه، ولا يدخل النسخة الاحتياطية)
 *   v  الإصدار · p المنصة · o مرات الفتح منذ آخر رسالة · n تثبيتٌ جديد؟ · r تحديثٌ نُزّل وينتظر التثبيت؟
 * لا أسماء ولا أرقام ولا فواتير ولا موقع. تُرسَل عند الفتح، ومرةً كل 30 دقيقة على الأكثر
 * (والفتحات بينها تُجمع)، وبلا إنترنت تنتظر الاتصال. وأي خطأٍ هنا لا يمسّ التطبيق.
 */
(function (root) {
  "use strict";
  const KEY = "aur.u";
  const SITE = "https://gold-erp.pages.dev";
  // النسخة التجريبية تُرسل إلى موقع التجربة فلا تختلط بأرقام العملاء
  const TRIAL = "https://claude-gold-accounting-syste.gold-erp.pages.dev";
  const GAP = 30 * 60 * 1000;          // أقلّ مدةٍ بين رسالتين
  const REOPEN = 30 * 60 * 1000;       // العودة بعد غيابٍ أطول من هذا = فتحٌ جديد
  const MIN_OPEN = 5 * 60 * 1000;      // إعادة تحميل الصفحة سريعاً لا تُعدّ فتحاً

  const B = () => root.Bridge || null;
  const today = () => new Date(Date.now() + 3 * 3600 * 1000).toISOString().slice(0, 10);

  function rawVersion() {
    const b = B();
    return b && b.native ? String(b.appVersion() || "") : "";
  }
  function platform() {
    const b = B();
    if (b && b.native) {
      if (/-trial$/.test(rawVersion())) return "trial";
      try { if ((b.updateState() || {}).store === "play") return "play"; } catch (e) { /* */ }
      return "android";
    }
    const n = root.navigator || {};
    const ios = /iPad|iPhone|iPod/.test(n.userAgent || "") || (n.platform === "MacIntel" && n.maxTouchPoints > 1);
    let standalone = n.standalone === true;
    try { standalone = standalone || root.matchMedia("(display-mode: standalone)").matches; } catch (e) { /* */ }
    return ios && standalone ? "ios" : "web";
  }
  function endpoint(plat) {
    if (root.__aurStatsEndpoint !== undefined) return root.__aurStatsEndpoint;   // للاختبار فقط
    const h = root.location.hostname;
    if (h === "appassets.androidplatform.net") return (plat === "trial" ? TRIAL : SITE) + "/api/p";
    if (h === "gold-erp.pages.dev" || /\.gold-erp\.pages\.dev$/.test(h)) return root.location.origin + "/api/p";
    return "";                          // نسخةٌ محلية أو اختبار: لا يُرسل شيء
  }

  function load() {
    try { return JSON.parse(root.localStorage.getItem(KEY) || "null"); } catch (e) { return null; }
  }
  function save(st) {
    try { root.localStorage.setItem(KEY, JSON.stringify(st)); return true; } catch (e) { return false; }
  }
  function newId() {
    const c = root.crypto;
    if (c && c.randomUUID) return c.randomUUID();
    const a = new Uint8Array(16);
    c.getRandomValues(a);
    return Array.from(a, (x) => x.toString(16).padStart(2, "0")).join("");
  }
  function state() {
    let st = load();
    if (!st || typeof st.i !== "string") {
      let welcomed = false;
      try { welcomed = !!root.localStorage.getItem("welcomed"); } catch (e) { /* */ }
      // من كان يستخدم التطبيق قبل هذا الإصدار ليس «جديداً»
      st = { i: newId(), o: 0, a: 0, t: 0, d: "", v: "", n: welcomed ? 0 : 1 };
      if (!save(st)) return null;       // لا تخزين = لا رقم ثابت، فلا نرسل (كي لا يُعدّ مرتين)
    }
    return st;
  }

  let webVer = "";
  async function version() {
    const raw = rawVersion();
    if (raw) return raw.replace(/-.*$/, "");
    if (webVer) return webVer;
    try {
      const r = await fetch("version.json", { cache: "no-store" });
      webVer = String((await r.json()).name || "");
    } catch (e) { /* */ }
    return webVer;
  }
  async function waiting() {
    const b = B();
    if (b && b.native) {
      try { return b.updateState().ready ? 1 : 0; } catch (e) { return 0; }
    }
    try {
      const sw = root.navigator.serviceWorker;
      const reg = sw && (await sw.getRegistration());
      return reg && reg.waiting ? 1 : 0;
    } catch (e) { return 0; }
  }

  let busy = false;
  async function flush(force) {
    if (busy) return;
    const plat = platform(), url = endpoint(plat);
    if (!url) return;
    const st = state();
    if (!st) return;
    if (root.navigator && root.navigator.onLine === false) return;
    busy = true;
    try {
      const v = await version();
      if (!/^[0-9]+(\.[0-9]+){0,3}$/.test(v)) return;
      const now = Date.now(), d = today();
      if (!force && st.t && now - st.t < GAP && st.d === d && st.v === v) return;
      const sent = Math.min(200, st.o || 0);
      const body = JSON.stringify({ i: st.i, v, p: plat, o: sent, n: st.n ? 1 : 0, r: await waiting() });
      const ctl = root.AbortController ? new AbortController() : null;
      const to = ctl ? setTimeout(() => ctl.abort(), 15000) : 0;
      const r = await fetch(url, {
        method: "POST", body, keepalive: true, credentials: "omit", cache: "no-store",
        headers: { "Content-Type": "text/plain" }, signal: ctl ? ctl.signal : undefined,
      });
      if (to) clearTimeout(to);
      if (!r.ok) return;
      const cur = load() || st;
      cur.o = Math.max(0, (cur.o || 0) - sent);
      cur.t = now; cur.d = d; cur.v = v; cur.n = 0;
      save(cur);
    } catch (e) {
      /* بلا إنترنت أو خطأ: الفتحات محفوظة وتُرسل في المرة القادمة */
    } finally {
      busy = false;
    }
  }

  function opened() {
    const plat = platform();
    if (!endpoint(plat)) return false;
    const st = state();
    if (!st) return false;
    const now = Date.now();
    if (now - (st.a || 0) < MIN_OPEN) return false;
    st.o = (st.o || 0) + 1;
    st.a = now;
    save(st);
    return true;
  }

  let hiddenAt = 0;
  function start() {
    try {
      if (!endpoint(platform())) return;
      const first = !(load() || {}).t;
      opened();
      setTimeout(() => flush(first), 3000);    // بعد اكتمال الفتح، لا يزاحمه
      root.document.addEventListener("visibilitychange", () => {
        if (root.document.visibilityState === "hidden") { hiddenAt = Date.now(); return; }
        if (hiddenAt && Date.now() - hiddenAt >= REOPEN && opened()) flush(false);
        else if (today() !== ((load() || {}).d || "")) flush(false);
      });
      root.addEventListener("online", () => flush(false));
    } catch (e) { /* لا يمسّ التطبيق */ }
  }

  root.AurStats = { flush, start, _state: load };
  if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", start);
  else start();
})(window);
