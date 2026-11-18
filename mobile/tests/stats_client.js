// إحصاءات الاستخدام في التطبيق نفسه (mobile/web/js/stats.js) — في متصفحٍ بمقاس جوال:
//   node mobile/tests/stats_client.js
// رسالةٌ صغيرة في الخلفية بلا أي أثرٍ في الشاشة، تُجمع الفتحات بلا إنترنت، ولا تُرسل من نسخةٍ محلية.
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const WEB = path.join(__dirname, "../web");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css", ".ttf": "font/ttf", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const VERSION = JSON.parse(fs.readFileSync(path.join(WEB, "version.json"), "utf8")).name;

function listen(handler) {
  return new Promise((resolve) => { const s = http.createServer(handler); s.listen(0, "127.0.0.1", () => resolve(s)); });
}

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log("  ✔", name); } else { fail++; console.log("  ✘", name, detail === undefined ? "" : "— " + JSON.stringify(detail)); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const app = await listen((req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0]);
    if (p === "/") p = "/index.html";
    const f = path.join(WEB, p);
    if (!f.startsWith(WEB) || !fs.existsSync(f)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(f)] || "application/octet-stream" });
    fs.createReadStream(f).pipe(res);
  });
  // خادم الاستقبال (مصدرٌ آخر — كما في التطبيق: appassets ← gold-erp.pages.dev)
  const got = [];
  let down = false, preflight = 0;
  const cap = await listen((req, res) => {
    if (req.method === "OPTIONS") { preflight++; res.writeHead(204, { "Access-Control-Allow-Origin": "*" }); res.end(); return; }
    let b = "";
    req.on("data", (c) => (b += c));
    req.on("end", () => {
      got.push({ body: b, type: req.headers["content-type"], cookie: req.headers.cookie || "" });
      res.writeHead(down ? 503 : 200, { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json" });
      res.end(down ? "" : '{"ok":1}');
    });
  });
  const url = `http://127.0.0.1:${app.address().port}/`;
  const END = `http://127.0.0.1:${cap.address().port}/api/p`;
  const browser = await chromium.launch();

  async function open(opts = {}) {
    const ctx = await browser.newContext({ viewport: { width: 393, height: 851 }, isMobile: true, hasTouch: true, locale: "ar" });
    await ctx.addInitScript(([end, o]) => {
      if (end) window.__aurStatsEndpoint = end;
      if (o.welcomed && !localStorage.getItem("aur.u")) localStorage.setItem("welcomed", "1");
      if (o.bridge) {
        window.AndroidBridge = {
          appVersion: () => o.bridge.version, getLang: () => "ar", setLang: () => {},
          updateState: () => JSON.stringify(o.bridge.update || {}), setAds: () => {}, adsState: () => "{}",
          backupInfo: () => JSON.stringify({ mode: "auto", name: "ÀUR", auto: true }), backupFolder: () => "ÀUR",
          autoBackup: () => {}, requestNotifications: () => {}, goldPrice: () => {}, syncPhotos: () => {},
          startAuto: () => {}, checkUpdate: () => {},
        };
      }
    }, [opts.noEndpoint ? "" : END, opts]);
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    return { ctx, page, errors };
  }
  const st = (page) => page.evaluate(() => JSON.parse(localStorage.getItem("aur.u") || "null"));
  const age = (page, fields) => page.evaluate((f) => {
    const s = JSON.parse(localStorage.getItem("aur.u"));
    for (const k in f) s[k] = typeof f[k] === "number" && f[k] < 0 ? Date.now() + f[k] : f[k];
    localStorage.setItem("aur.u", JSON.stringify(s));
  }, fields);
  const next = async (n, ms = 7000) => { const t = Date.now(); while (got.length < n && Date.now() - t < ms) await wait(100); return got[n - 1]; };

  console.log("── أول فتح على الويب");
  let { ctx, page, errors } = await open();
  await page.goto(url);
  let m = await next(1);
  const b = m && JSON.parse(m.body);
  check("رسالةٌ واحدة بعد الفتح", got.length === 1 && !!b, got.length);
  check("فيها: رقمٌ عشوائي · الإصدار · المنصة · فتحٌ واحد · جديد", b && /^[0-9a-f-]{32,36}$/.test(b.i) && b.v === VERSION
    && b.p === "web" && b.o === 1 && b.n === 1 && b.r === 0, b);
  check("ولا شيء غيرها (لا أسماء ولا بيانات)", b && Object.keys(b).sort().join() === "i,n,o,p,r,v", b && Object.keys(b));
  check("صغيرةٌ جداً (أقل من 200 بايت)", m && m.body.length < 200, m && m.body.length);
  check("نصٌّ عادي بلا كوكيز (ولا طلب سماحٍ مسبق)", m && /^text\/plain/.test(m.type) && !m.cookie && preflight === 0, m && m.type);
  const s1 = await st(page);
  check("محفوظة: أُرسل ولا فتحات معلّقة", s1 && s1.o === 0 && s1.t > 0 && s1.n === 0 && s1.i === b.i, s1);
  const elems = await page.evaluate(() => document.querySelectorAll("*").length);
  const keys = await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("aur")));
  check("مفتاح تخزينٍ واحد فقط (aur.u)", keys.join() === "aur.u", keys);
  check("بلا أخطاء", errors.length === 0, errors);

  console.log("── إعادة الفتح");
  await page.reload();
  await wait(4500);
  check("إعادة تحميلٍ سريعة لا تُعدّ فتحاً ولا تُرسل", got.length === 1 && (await st(page)).o === 0, got.length);
  await age(page, { a: -2 * 3600e3, t: -2 * 3600e3 });
  await page.reload();
  m = await next(2);
  check("بعد ساعتين: فتحٌ جديد يُرسل (ليس جديداً)", m && JSON.parse(m.body).o === 1 && JSON.parse(m.body).n === 0
    && JSON.parse(m.body).i === b.i, m && m.body);
  await age(page, { a: -40 * 60e3, t: -10 * 60e3 });
  await page.reload();
  await wait(4500);
  const s2 = await st(page);
  check("فتحٌ خلال 30 دقيقة من آخر رسالة: يُعدّ ويُجمع بلا إرسال", got.length === 2 && s2.o === 1, { n: got.length, o: s2.o });

  console.log("── بلا إنترنت");
  down = true;
  await age(page, { a: -40 * 60e3, t: -2 * 3600e3 });
  await page.reload();
  await next(3);
  await wait(500);
  check("فشل الإرسال: الفتحات تبقى محفوظة (2)", (await st(page)).o === 2, await st(page));
  down = false;
  await age(page, { a: -40 * 60e3, t: -2 * 3600e3 });
  await page.reload();
  m = await next(4);
  await wait(300);
  check("ثم تُرسل كلها مع الاتصال (3)", m && JSON.parse(m.body).o === 3 && (await st(page)).o === 0, m && m.body);
  await age(page, { a: -10 * 60e3, t: -60e3, v: "1.0.0" });
  await page.reload();
  m = await next(5);
  check("إصدارٌ جديد (تحديث): يُرسل فوراً", m && JSON.parse(m.body).v === VERSION, m && m.body);
  await ctx.close();

  console.log("── انقطاع الإنترنت أثناء الاستخدام");
  const b4 = got.length;
  ({ ctx, page, errors } = await open({ welcomed: true }));
  await page.route(END, (r) => r.abort("internetdisconnected"));       // الخادم غير موجود أصلاً
  await page.goto(url);
  await wait(4500);
  const tabs = ["customers", "holdings", "more", "home"];
  let worked = true;
  for (const t of tabs) {
    await page.locator(`#tabs button[data-tab="${t}"]`).click();
    await wait(300);
    worked = worked && (await page.evaluate(() => document.querySelector("#view").children.length > 0));
  }
  let s3 = await st(page);
  check("بلا شبكة: التطبيق يعمل كاملاً (الحسابات · الممتلكات · المزيد · الرئيسية)", worked && errors.length === 0, errors);
  check("ولا رسالة خرجت، والفتح محفوظ لوقت الاتصال", got.length === b4 && s3.o === 1 && !s3.t, s3);
  await page.unroute(END);
  await ctx.setOffline(true);
  for (const t of tabs) { await page.locator(`#tabs button[data-tab="${t}"]`).click(); await wait(150); }
  check("وضع الطيران: التنقل يعمل بلا أخطاء", errors.length === 0, errors);
  await ctx.setOffline(false);
  m = await next(b4 + 1);
  check("عودة الاتصال: تُرسل الفتحات المحفوظة وحدها", m && JSON.parse(m.body).o === 1 && JSON.parse(m.body).n === 0, m && m.body);
  await ctx.close();

  console.log("── السرعة");
  async function loadTime(withStats) {
    const times = [];
    for (let k = 0; k < 4; k++) {
      const o = await open({ welcomed: true, noEndpoint: !withStats });
      if (!withStats) await o.page.route("**/js/stats.js", (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
      await o.page.goto(url);
      await o.page.waitForFunction(() => document.querySelector("#view") && document.querySelector("#view").children.length > 0);
      times.push(await o.page.evaluate(() => performance.now()));
      await o.ctx.close();
    }
    times.sort((x, y) => x - y);
    return (times[1] + times[2]) / 2;
  }
  const tWith = await loadTime(true), tWithout = await loadTime(false);
  console.log(`    زمن فتح الرئيسية: بالإحصاء ${tWith.toFixed(0)} م.ث · بدونه ${tWithout.toFixed(0)} م.ث`);
  check("لا أثر يُذكر على سرعة الفتح (أقل من 60 م.ث فرقاً)", tWith - tWithout < 60, { tWith, tWithout });

  console.log("── لا أثر في الشاشة");
  ({ ctx, page } = await open());
  await page.route("**/js/stats.js", (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
  await page.goto(url);
  await wait(4000);
  const elemsWithout = await page.evaluate(() => document.querySelectorAll("*").length);
  check("الصفحة نفسها بالإحصاء وبدونه (لا زرّ ولا شاشة ولا إشعار)", elems === elemsWithout, { elems, elemsWithout });
  await ctx.close();

  console.log("── مستخدمٌ سابق · نسخةٌ محلية · أندرويد");
  let before = got.length;
  ({ ctx, page } = await open({ welcomed: true }));
  await page.goto(url);
  m = await next(before + 1);
  check("من كان يستخدمه قبل هذا الإصدار: ليس «جديداً»", m && JSON.parse(m.body).n === 0, m && m.body);
  await ctx.close();
  before = got.length;
  ({ ctx, page } = await open({ noEndpoint: true }));
  await page.goto(url);
  await wait(4500);
  check("نسخةٌ محلية/اختبار: لا يُرسل شيء ولا يُحفظ شيء", got.length === before && !(await st(page)), got.length - before);
  await ctx.close();
  ({ ctx, page, errors } = await open({ bridge: { version: "1.15.0-trial", update: { ready: true } } }));
  await page.goto(url);
  m = await next(before + 1);
  let a = m && JSON.parse(m.body);
  check("النسخة التجريبية: منصة trial والإصدار بلا اللاحقة", a && a.p === "trial" && a.v === "1.15.0", a);
  check("وتحديثٌ نُزّل وينتظر التثبيت: r=1", a && a.r === 1, a);
  check("وبلا أخطاء", errors.length === 0, errors);
  await ctx.close();
  ({ ctx, page } = await open({ bridge: { version: "1.15.0", update: { unsupported: true, store: "play" } } }));
  await page.goto(url);
  m = await next(before + 2);
  a = m && JSON.parse(m.body);
  check("نسخة Google Play: منصة play", a && a.p === "play" && a.r === 0, a);
  await ctx.close();
  ({ ctx, page } = await open({ bridge: { version: "1.15.0", update: { available: false, ready: false } } }));
  await page.goto(url);
  m = await next(before + 3);
  a = m && JSON.parse(m.body);
  check("ملف التثبيت (خارج المتجر): منصة android", a && a.p === "android", a);
  await ctx.close();

  await browser.close();
  app.close(); cap.close();
  console.log(`\n${pass} ✔ · ${fail} ✘`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
