/* سعر الذهب في رأس الرئيسية: الأونصة العالمية وجرام عيار 24 و22 و21 و18.
 *
 * كشريط «سعر الذهب العالمي» في البرنامج: المصادر نفسها بالترتيب نفسه
 * (`ui/widgets/gold_price.py`)، والمعادلات نفسها (`Gold.ouncePrices` ←
 * `gold_math.ounce_prices`، ويقارنهما فحص التطابق)، والتحديث كل 5 دقائق.
 *
 * - في تطبيق أندرويد يجلبه التطبيق نفسه (`AndroidBridge.goldPrice`) فلا تمنعه
 *   قيود المتصفح؛ وفي الآيفون ونسخة الويب يُجلب من الصفحة.
 * - آخر سعرٍ معروف يُحفظ في الجوال ويُعرض بلا إنترنت مع وقته.
 * - لا يُرسَل مع الطلب شيءٌ من بيانات المستخدم.
 */
(function (root) {
  "use strict";
  const KEY = "gold_price";
  const EVERY = 5 * 60 * 1000;            // كالبرنامج: كل 5 دقائق
  const TIMEOUT = 6000;
  // مصادر مجانية بلا مفتاح — تُجرَّب بالترتيب حتى ينجح أحدها (كالبرنامج)
  const SOURCES = [
    ["https://api.gold-api.com/price/XAU", ["price"]],
    ["https://api.metalpriceapi.com/v1/latest?base=XAU&currencies=USD", ["rates", "USD"]],
    ["https://data-asg.goldprice.org/dbXRates/USD", ["items", 0, "xauPrice"]],
  ];

  function read() { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } }
  function write(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* */ } }
  let last = read();            // { usd, at }
  if (!(last && last.usd > 0)) last = null;
  let busy = null, failedAt = 0;
  const subs = [];

  function dig(data, path) {
    let cur = data;
    for (const k of path) cur = cur[k];
    const v = Number(cur);
    return isFinite(v) && v > 0 ? Math.round(v * 100) / 100 : 0;
  }

  async function viaFetch() {
    let lastErr = null;
    for (const [url, path] of SOURCES) {
      const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
      const t = ctl ? setTimeout(() => ctl.abort(), TIMEOUT) : null;
      try {
        const r = await fetch(url, { cache: "no-store", signal: ctl ? ctl.signal : undefined });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const v = dig(await r.json(), path);
        if (v > 0) return v;
      } catch (e) { lastErr = e; } finally { if (t) clearTimeout(t); }
    }
    throw lastErr || new Error("no price");
  }

  function viaNative() {
    const A = root.AndroidBridge;
    const B = root.Bridge;
    return new Promise((res, rej) => {
      const off = B.on("gold", (d) => {
        off(); clearTimeout(t);
        if (d && d.usd > 0) res(Math.round(Number(d.usd) * 100) / 100); else rej(new Error((d && d.error) || "no price"));
      });
      const t = setTimeout(() => { off(); rej(new Error("timeout")); }, TIMEOUT * SOURCES.length + 2000);
      try { A.goldPrice(JSON.stringify(SOURCES)); } catch (e) { off(); clearTimeout(t); rej(e); }
    });
  }

  const native = () => !!(root.AndroidBridge && root.AndroidBridge.goldPrice && root.Bridge);

  // يجلب السعر (جلبٌ واحد في كل لحظة). force: ولو لم تمضِ 5 دقائق
  function refresh(force) {
    if (busy) return busy;
    const now = Date.now();
    if (!force && last && now - last.at < EVERY) return Promise.resolve(false);
    if (!force && !last && now - failedAt < 30000) return Promise.resolve(false);
    notify({ loading: true });
    busy = (async () => {
      let ok = false;
      try {
        let usd = 0;
        if (native()) {
          try { usd = await viaNative(); } catch (e) { usd = 0; }
        }
        if (!(usd > 0)) usd = await viaFetch();
        last = { usd, at: Date.now() };
        write(last);
        ok = true;
      } catch (e) {
        failedAt = Date.now();
      }
      busy = null;               // انتهى الجلب قبل الإعلام — فلا يبقى «جارِ التحديث»
      notify(ok ? {} : { failed: true });
      return ok;
    })();
    return busy;
  }

  // الحالة كما تُعرض: السعر وأسعار الأعيرة (بمعادلات البرنامج) ووقته
  function state(extra) {
    const st = Object.assign({ loading: !!busy }, extra || {});
    if (!last) return Object.assign(st, { ok: false });
    const p = root.Gold.ouncePrices(last.usd);
    return Object.assign(st, { ok: true, usd: last.usd, at: last.at, prices: p,
      stale: Date.now() - last.at > 30 * 60 * 1000 });
  }
  function notify(extra) {
    const s = state(extra);
    for (const fn of subs.slice()) { try { fn(s); } catch (e) { console.error(e); } }
  }
  function subscribe(fn) {
    subs.push(fn);
    return () => { const i = subs.indexOf(fn); if (i >= 0) subs.splice(i, 1); };
  }

  // يتجدّد وحده ما دام التطبيق ظاهراً
  setInterval(() => { if (!document.hidden) refresh(false); }, 60 * 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(false); });

  root.GoldPrice = { refresh, state, subscribe, SOURCES };
})(window);
