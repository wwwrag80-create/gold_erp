// إحصاءات الاستخدام: منطق الخادم عبر أيامٍ وأسابيع وشهور (قاعدةٌ مؤقتة في الذاكرة بدل D1، والوقت مُتحكَّمٌ به).
//   node --no-warnings mobile/tests/stats.test.mjs            ← الأرقام
//   SHOTS=dir node --no-warnings mobile/tests/stats.test.mjs   ← ومعها اللوحة في متصفحٍ حقيقي (هاتف وحاسوب · فاتح وداكن)
import { DatabaseSync } from "node:sqlite";
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pbkdf2Sync, randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "site", "_worker.js");

// ── D1 من SQLite ──
class FakeD1 {
  constructor() { this.db = new DatabaseSync(":memory:"); this.writes = 0; }
  prepare(sql) {
    const db = this.db, self = this;
    const mk = (args) => ({
      _sql: sql, _args: args,
      bind: (...a) => mk(a),
      first: async () => db.prepare(sql).get(...args) ?? null,
      all: async () => ({ results: db.prepare(sql).all(...args) }),
      run: async () => { self.writes++; db.prepare(sql).run(...args); return { success: true }; },
    });
    return mk([]);
  }
  async batch(stmts) {
    this.db.exec("BEGIN");
    try {
      const out = stmts.map((s) => {
        if (!/^\s*SELECT/i.test(s._sql)) this.writes++;
        return { results: this.db.prepare(s._sql).all(...s._args), success: true };
      });
      this.db.exec("COMMIT");
      return out;
    } catch (e) { this.db.exec("ROLLBACK"); throw e; }
  }
}

// الوقت: كل «يوم» ظهراً بتوقيت الرياض
let NOW = Date.parse("2026-09-01T09:00:00Z");
const realNow = Date.now;
Date.now = () => NOW;
const setDay = (d, h = 9) => { NOW = Date.parse(d + "T" + String(h).padStart(2, "0") + ":00:00Z"); };

// كلمة مرورٍ للاختبار مكان كلمة المالك
const PW = "test-pass-1234";
const salt = randomBytes(16);
const TEST_HASH = `p2$10000$${salt.toString("base64")}$${pbkdf2Sync(PW, salt, 10000, 32, "sha256").toString("base64")}`;
const src = readFileSync(SRC, "utf8")
  .replace(/const INITIAL_PASS = "[^"]+";/, `const INITIAL_PASS = ${JSON.stringify(TEST_HASH)};`)
  .replace('"/*DASH_JS*/"', () => JSON.stringify(readFileSync(path.join(HERE, "..", "site", "stats_dash.js"), "utf8")));
const W = (await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"))).default;
const DB = new FakeD1();
const env = { STATS: DB, ASSETS: { fetch: async () => new Response("static", { status: 200 }) } };

let ok = 0, bad = 0;
const check = (name, cond, info) => {
  if (cond) { ok++; console.log("  ✔ " + name); } else { bad++; console.log("  ✘ " + name + (info !== undefined ? "  [" + JSON.stringify(info) + "]" : "")); }
};
const ping = async (i, v, p, o = 1, extra = {}) => {
  const r = await W.fetch(new Request("https://gold-erp.pages.dev/api/p", { method: "POST", body: JSON.stringify({ i, v, p, o, ...extra }) }), env);
  return r.status;
};
const ID = (n) => "dev-" + String(n).padStart(4, "0") + "-aaaaaaaaaaaa";

async function login(pw = PW) {
  const r = await W.fetch(new Request("https://gold-erp.pages.dev/stats/login", {
    method: "POST", body: new URLSearchParams({ pw }), headers: { Origin: "https://gold-erp.pages.dev" }, redirect: "manual",
  }), env);
  return (r.headers.get("set-cookie") || "").match(/aur_s=([0-9a-f]{64})/)[1];
}
async function data(tok) {
  const r = await W.fetch(new Request("https://gold-erp.pages.dev/stats/data", { headers: { Cookie: "aur_s=" + tok } }), env);
  return r.json();
}
const plat = (D, p) => (D.plats.find((x) => x.plat === p) || {});
const tot = (D, f) => D.plats.reduce((a, r) => a + (r[f] || 0), 0);

console.log("── اليوم الأول (1 سبتمبر): بدء الإحصاء");
setDay("2026-09-01");
for (let n = 1; n <= 5; n++) await ping(ID(n), "1.14.0", "android", 3, { n: 0 });     // كانوا يستخدمونه قبلُ
for (let n = 6; n <= 7; n++) await ping(ID(n), "1.15.0", "android", 1, { n: 1 });     // تثبيتٌ جديد
await ping(ID(8), "1.15.0", "ios", 1, { n: 1 });
await ping(ID(9), "1.15.0", "web", 1, { n: 1 });
await ping(ID(1), "1.14.0", "android", 2, { n: 0 });                                   // مرةٌ ثانية في اليوم نفسه
let D = await data(await login());
check("9 أجهزة", tot(D, "n") === 9, tot(D, "n"));
check("4 جدد و5 سابقون", tot(D, "fresh") === 4, tot(D, "fresh"));
check("نشطون اليوم 9 (الجهاز المكرر مرةٌ واحدة)", tot(D, "a1") === 9 && D.daily[0].active === 9, D.daily);
check("مرات الفتح 21", D.daily[0].opens === 5 * 3 + 2 + 2 + 1 + 1, D.daily[0].opens);
check("الجدد اليوم 4 فقط (السابقون لا يُعدّون جدداً)", tot(D, "n1") === 4 && D.daily[0].new === 4);

console.log("── تحديثٌ يصل (3 سبتمبر)");
setDay("2026-09-03");
await ping(ID(1), "1.15.0", "android", 1);
await ping(ID(2), "1.15.0", "android", 1);
await ping(ID(3), "1.14.0", "android", 1, { r: 1 });                                  // نُزّل التحديث وينتظر
await ping(ID(3), "1.14.0", "android", 1, { r: 1 });
await ping(ID(6), "1.15.0", "android", 2);
D = await data(await login());
const d3 = D.daily.find((x) => x.day === "2026-09-03");
check("تحديثان مثبّتان (1.14 ← 1.15)", tot(D, "upd") === 2 && d3.upd === 2, d3);
check("ونشطو اليوم 4", d3.active === 4, d3);
check("التحديثات لكل إصدار: إلى 1.15.0 ×2", D.updVers.length === 1 && D.updVers[0].v === "1.15.0" && D.updVers[0].n === 2);
check("وصله التحديث ولم يثبّته: 1", tot(D, "waiting") === 1);

console.log("── بعد 40 يوماً (11 أكتوبر)");
setDay("2026-09-20"); await ping(ID(4), "1.14.0", "android", 1);
setDay("2026-10-05"); await ping(ID(6), "1.15.0", "android", 1);
setDay("2026-10-08"); await ping(ID(10), "1.15.0", "android", 1, { n: 1 });
setDay("2026-10-11"); await ping(ID(1), "1.16.0", "android", 1);
await ping(ID(8), "1.16.0", "ios", 4);
await ping(ID(9), "1.15.0", "web", 1);
await ping(ID(9), "1.14.0", "web", 1);                                                  // نزولٌ لإصدارٍ أقدم ليس «تحديثاً»
D = await data(await login());
check("اليوم 11 أكتوبر", D.today === "2026-10-11");
check("نشطون اليوم 3 (1 · 8 · 9)", tot(D, "a1") === 3, tot(D, "a1"));
check("نشطون 7 أيام 5 (… و6 و10)", tot(D, "a7") === 5, tot(D, "a7"));
check("نشطون 30 يوماً 6 (… و4)", tot(D, "a30") === 6, tot(D, "a30"));
check("جدد 7 أيام 1 · 30 يوماً 1", tot(D, "n7") === 1 && tot(D, "n30") === 1);
check("توقفوا مؤقتاً (7–30 يوماً): 1 (الجهاز 4)", tot(D, "paused") === 1, tot(D, "paused"));
check("غادروا (أكثر من 30 يوماً): 4 (2 · 3 · 5 · 7)", tot(D, "gone") === 4, tot(D, "gone"));
check("التحديثات: 4 (اثنان إلى 1.15 · اثنان إلى 1.16) والنزول لا يُعدّ", tot(D, "upd") === 4
  && D.updVers.map((u) => u.v + ":" + u.n).join() === "1.16.0:2,1.15.0:2", D.updVers);
check("أحدث إصدار لكل منصة", D.latest.android === "1.16.0" && D.latest.ios === "1.16.0" && D.latest.web === "1.14.0", D.latest);
check("على إصدارٍ أقدم: 3 من أندرويد (4 · 6 · 10)", D.behind.android === 3 && !D.behind.ios, D.behind);
check("الإصدارات لدى النشطين", D.versions.some((v) => v.plat === "android" && v.ver === "1.15.0" && v.n === 2)
  && D.versions.some((v) => v.plat === "android" && v.ver === "1.14.0" && v.n === 1));
check("النمو: 9 في 1 سبتمبر ثم 1 في 8 أكتوبر", D.growth.map((g) => g.d + ":" + g.n).join() === "2026-09-01:9,2026-10-08:1", D.growth);
check("المغادرون حسب شهر آخر فتح: سبتمبر 4", D.left.length === 1 && D.left[0].m === "2026-09" && D.left[0].n === 4, D.left);
const wk = Object.fromEntries(D.weeks.map((w) => [w.k, w.n]));
check("النشطون أسبوعياً (الأسبوع يبدأ الأحد)", wk["2026-08-30"] === 9 && wk["2026-10-11"] === 3 && wk["2026-10-04"] === 2, wk);
const mo = Object.fromEntries(D.months.map((m) => [m.k, m.n]));
check("النشطون شهرياً: سبتمبر 9 · أكتوبر 5", mo["2026-09"] === 9 && mo["2026-10"] === 5, mo);
check("مرات الفتح لكل جهاز تتراكم", D.plats.find((p) => p.plat === "ios").opens === 5);

console.log("── الحماية وكلمة المرور");
const tok = await login();
let r = await W.fetch(new Request("https://gold-erp.pages.dev/stats/pass", {
  method: "POST", headers: { Cookie: "aur_s=" + tok, Origin: "https://gold-erp.pages.dev", "Content-Type": "application/json" },
  body: JSON.stringify({ cur: "nope", pw: "new-pass-5678", pw2: "new-pass-5678" }),
}), env);
check("تغييرها بكلمةٍ حالية خاطئة مرفوض", (await r.json()).ok === false);
const other = await login();
r = await W.fetch(new Request("https://gold-erp.pages.dev/stats/pass", {
  method: "POST", headers: { Cookie: "aur_s=" + tok, Origin: "https://gold-erp.pages.dev", "Content-Type": "application/json" },
  body: JSON.stringify({ cur: PW, pw: "new-pass-5678", pw2: "new-pass-5678" }),
}), env);
check("وبالصحيحة تتغيّر", (await r.json()).ok === true);
r = await W.fetch(new Request("https://gold-erp.pages.dev/stats/data", { headers: { Cookie: "aur_s=" + other } }), env);
check("والأجهزة الأخرى تخرج من اللوحة", r.status === 401, r.status);
r = await W.fetch(new Request("https://gold-erp.pages.dev/stats/data", { headers: { Cookie: "aur_s=" + tok } }), env);
check("والجهاز الذي غيّرها يبقى داخلاً", r.status === 200);
const loginWith = async (pw, ip = "1.2.3.4") => (await W.fetch(new Request("https://gold-erp.pages.dev/stats/login", {
  method: "POST", body: new URLSearchParams({ pw }), redirect: "manual",
  headers: { Origin: "https://gold-erp.pages.dev", "CF-Connecting-IP": ip },
}), env)).status;
check("الكلمة القديمة لم تعد تعمل", (await loginWith(PW)) === 401);
check("والجديدة تعمل", (await loginWith("new-pass-5678")) === 303);
for (let k = 0; k < 10; k++) await loginWith("guess-" + k, "9.9.9.9");
check("بعد 10 محاولاتٍ خاطئة من عنوانٍ واحد: يُوقف اليوم", (await loginWith("new-pass-5678", "9.9.9.9")) === 429);
check("وعنوانٌ آخر غير متأثر", (await loginWith("new-pass-5678", "5.5.5.5")) === 303);
const ipRow = DB.db.prepare("SELECT k FROM fails").all().map((x) => x.k).join();
check("ولا يُحفظ عنوان IP نفسه", !ipRow.includes("9.9.9.9"));
const cols = DB.db.prepare("PRAGMA table_info(devices)").all().map((c) => c.name).join();
check("ولا يُحفظ عن الجهاز غير المعرّف العشوائي والإصدار والمنصة والأيام والعدد", cols === "id,plat,fresh,first_day,last_day,first_ver,ver,opens,updates,waiting,last_ts", cols);
check("بلا قاعدة مربوطة: الاستقبال 503 والموقع يعمل", (await W.fetch(new Request("https://x/api/p", { method: "POST", body: "{}" }), { ASSETS: env.ASSETS })).status === 503
  && (await (await W.fetch(new Request("https://x/"), { ASSETS: env.ASSETS })).text()) === "static");

console.log("── الكلفة: كتابات القاعدة لكل رسالة");
const before = DB.writes;
setDay("2026-10-12");
for (let n = 1; n <= 10; n++) await ping(ID(n), "1.16.0", "android", 1);
const per = (DB.writes - before) / 10;
check(`نحو ${per.toFixed(1)} كتابة لكل رسالة (حدّ الخطة المجانية 100,000 صفّ يومياً)`, per <= 5, per);

// ── اللوحة في متصفحٍ حقيقي ──
if (process.env.SHOTS) {
  console.log("── اللوحة في المتصفح");
  // بياناتٌ أغنى للصورة: 120 يوماً من النمو
  setDay("2026-07-20");
  let next = 100;
  const live = [];
  for (let k = 0; k < 120; k++) {
    const d = new Date(Date.parse("2026-07-20T09:00:00Z") + k * 86400000).toISOString().slice(0, 10);
    setDay(d);
    const add = 1 + ((k * 7) % 5) + Math.floor(k / 20);
    for (let j = 0; j < add; j++) live.push(ID(next++));
    for (const [j, id] of live.entries()) {
      if ((j + k) % 3 === 0 || j > live.length - add - 2) await ping(id, k > 80 && j % 2 ? "1.16.0" : "1.15.0", j % 9 === 0 ? "ios" : "android", 1 + (j % 3), { n: 1 });
    }
  }
  const tk = await login("new-pass-5678");
  const server = createServer(async (req, res) => {
    const body = await new Promise((ok) => { const c = []; req.on("data", (x) => c.push(x)); req.on("end", () => ok(Buffer.concat(c))); });
    const rq = new Request("http://127.0.0.1:" + server.address().port + req.url, {
      method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body,
    });
    const rs = await W.fetch(rq, env);
    res.writeHead(rs.status, Object.fromEntries(rs.headers));
    res.end(Buffer.from(await rs.arrayBuffer()));
  }).listen(0, "127.0.0.1");
  await new Promise((ok) => server.on("listening", ok));
  const base = "http://127.0.0.1:" + server.address().port;
  const { chromium } = createRequire(import.meta.url)("playwright");
  const browser = await chromium.launch();
  for (const [name, vp, scheme] of [["phone", { width: 390, height: 844 }, "light"], ["desktop", { width: 1280, height: 900 }, "light"], ["phone-dark", { width: 390, height: 844 }, "dark"]]) {
    const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme, locale: "ar-SA" });
    await ctx.addCookies([{ name: "aur_s", value: tk, url: base + "/stats" }]);
    const pg = await ctx.newPage();
    const errs = [];
    pg.on("pageerror", (e) => errs.push(String(e)));
    pg.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
    await pg.goto(base + "/stats");
    await pg.waitForSelector("#c-growth svg");
    check(`${name}: بلا أخطاء`, errs.length === 0, errs);
    const wide = await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    check(`${name}: بلا تمريرٍ أفقي`, wide);
    await pg.hover("#c-active svg rect[fill=transparent]", { position: { x: 200, y: 80 } });
    check(`${name}: التلميح يظهر عند المرور`, await pg.isVisible("#c-active .tip"));
    await pg.screenshot({ path: path.join(process.env.SHOTS, `stats-${name}.png`), fullPage: true });
    if (name === "phone") {
      await pg.click("#c-new .seg button[data-per=m]");
      check("التبديل إلى شهري", (await pg.getAttribute("#c-new .seg button[data-per=m]", "aria-pressed")) === "true");
      const txt = await pg.textContent("#app");
      check("الأرقام في الصفحة", txt.includes("إجمالي الأجهزة") && txt.includes("غادروا") && txt.includes("أندرويد"));
    }
    await ctx.close();
  }
  const ctx = await browser.newContext();
  const pg = await ctx.newPage();
  await pg.goto(base + "/stats");
  check("بلا جلسة: كلمة المرور فقط", (await pg.isVisible("input[name=pw]")) && !(await pg.isVisible("#app")));
  await pg.fill("input[name=pw]", "new-pass-5678");
  await pg.click("button[type=submit]");
  await pg.waitForSelector("#c-growth svg");
  check("الدخول من المتصفح يفتح اللوحة", true);
  await pg.click("button:has-text('خروج')");
  await pg.waitForSelector("input[name=pw]");
  check("والخروج يعيد صفحة كلمة المرور", true);
  await browser.close();
  server.close();
}

Date.now = realNow;
console.log(`\n${ok} ✔ · ${bad} ✘`);
process.exit(bad ? 1 : 0);
