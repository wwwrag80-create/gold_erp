// تجربة التطبيق كاملاً في متصفحٍ بمقاس جوال — كما يستعمله صاحبه.
//   node mobile/tests/e2e.js [مجلد_الصور]
// يحتاج playwright (مثبّت في بيئة التطوير وفي GitHub Actions).
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const WEB = path.join(__dirname, "../web");
const SHOTS = process.argv[2] || "";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css", ".ttf": "font/ttf", ".json": "application/json", ".png": "image/png" };

function serve() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/") p = "/index.html";
      const f = path.join(WEB, p);
      if (!f.startsWith(WEB) || !fs.existsSync(f)) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(f)] || "application/octet-stream" });
      fs.createReadStream(f).pipe(res);
    });
    srv.listen(0, "127.0.0.1", () => resolve(srv));
  });
}

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log("  ✔", name); }
  else { fail++; console.log("  ✘", name, detail === undefined ? "" : "— " + detail); }
}

(async () => {
  const srv = await serve();
  const url = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 393, height: 851 }, deviceScaleFactor: 2,
    hasTouch: true, isMobile: true, locale: "ar", acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  let n = 0;
  const shot = async (name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${String(++n).padStart(2, "0")}_${name}.png`), fullPage: true }); };
  const tap = (sel) => page.locator(sel).first().click();
  const fill = async (label, value) => {
    const f = page.locator("label.f", { hasText: label }).first().locator("input,select").first();
    await f.fill(String(value));
    await f.dispatchEvent("input");
  };
  const confirm = async (text) => { await page.locator(".sheet .btn", { hasText: text }).first().click(); };
  const text = async (sel) => (await page.locator(sel).first().innerText()).trim();

  await page.goto(url);
  await page.waitForSelector("#tabs");
  check("الرئيسية تفتح فارغة", (await page.content()).includes("لا عمليات بعد"));
  check("خمسة أزرار سفلية بأيقونات", (await page.locator("#tabs button .i svg").count()) === 5);
  check("زر التحديث مخفيٌّ في المتصفح (يعمل في أندرويد)", !(await page.locator("#upd-btn").isVisible()));
  check("لا شاشة ترحيب خارج أندرويد", !page.url().includes("welcome"));
  await shot("home_empty");

  // الإعدادات
  await page.goto(url + "#/settings");
  await fill("الاسم", "جاديت للذهب");
  await tap("button:has-text('حفظ الإعدادات')");
  await page.waitForTimeout(200);

  // محلان
  for (const [name, wage] of [["محل الأمانة", "20"], ["محل النخبة", ""]]) {
    await page.goto(url + "#/shop-form");
    await fill("اسم المحل", name);
    if (wage) await fill("الأجرة المتفق عليها", wage);
    await tap(".footer-bar .btn:has-text('حفظ')");
    await page.waitForTimeout(250);
  }
  check("أُضيف المحلان", (await page.evaluate(() => App.state.shops.length)) === 2);
  await shot("shop_page");

  // فاتورة بيع: W100 بأحجار، وW200 بعيار 21
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await fill("رقم التشغيل", "W100");
  await page.locator("label.f", { hasText: "رقم التشغيل" }).locator("input").press("Enter");
  check("رقمٌ جديد يُقال إنه جديد", (await page.content()).includes("جديد — اكتب أوزانه"));
  await fill("رقم الموديل", "M1");
  await fill("الذهب", "10");
  await fill("الفصوص", "1");
  await fill("الأحجار", "2");
  check("الأحجار بعد الخصم تُحسب (2 × 50% = 1)",
    (await page.locator("label.f", { hasText: "بعد الخصم" }).locator("input").inputValue()) === "1.00");
  check("والمقيد = 12", (await page.locator("label.f", { hasText: "الوزن المقيد" }).locator("input").inputValue()) === "12.00");
  await tap("button:has-text('+ إضافة سطر')");
  await page.waitForTimeout(150);
  check("السطر الأول أُضيف بأجر المحل المتفق عليه (240)",
    (await page.locator(".line").first().innerText()).includes("240.00"));
  await fill("رقم التشغيل", "W200");
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await fill("الذهب", "18");
  await fill("الأجر/جم", "23");
  await tap("button:has-text('+ إضافة سطر')");
  await page.waitForTimeout(150);
  await fill("رقم التشغيل", "W100");
  await tap("button:has-text('+ إضافة سطر')");
  await page.waitForTimeout(100);
  check("الطقم المكرّر في الفاتورة يُرفض", (await text("#toast")).includes("مضافٌ مسبقاً"), await text("#toast"));
  await fill("رقم التشغيل", "");
  for (const el of ["الذهب", "الوزن المقيد"]) await fill(el, "");
  const totals = await text(".totals");
  check("الإجماليات: 33.00 جم و654.00 ريال", totals.includes("33.00") && totals.includes("654.00"), totals);
  await shot("invoice_editor");
  await tap(".footer-bar .btn:has-text('ترحيل الفاتورة')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("رُحّلت الفاتورة S-00001", (await text("#bar h1")).includes("S-00001"));
  await page.waitForTimeout(500);
  await shot("invoice_doc");

  // مرتجع W100: يُعبّأ من الفاتورة
  await page.goto(url + "#/invoice/new?kind=sale_return");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await fill("رقم التشغيل", "W100");
  await page.locator("label.f", { hasText: "رقم التشغيل" }).locator("input").press("Enter");
  await page.waitForTimeout(150);
  check("المرتجع يقول أين بِيع", (await page.content()).includes("بِيع بالفاتورة S-00001"));
  check("ويعبّئ الذهب 10 والمقيد 12",
    (await page.locator("label.f", { hasText: "الذهب" }).first().locator("input").inputValue()) === "10.00" &&
    (await page.locator("label.f", { hasText: "الوزن المقيد" }).locator("input").inputValue()) === "12.00");
  check("وأجر البيع 20", (await page.locator("label.f", { hasText: "الأجر/جم" }).locator("input").inputValue()) === "20.00");
  await tap("button:has-text('+ إضافة سطر')");
  await tap(".footer-bar .btn:has-text('ترحيل الفاتورة')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("رُحّل المرتجع R-00001", (await text("#bar h1")).includes("R-00001"));

  // بيع W100 من جديد لمحلٍّ آخر: الأوزان من المرتجع
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل النخبة" }).click();
  await fill("رقم التشغيل", "W100");
  await page.locator("label.f", { hasText: "رقم التشغيل" }).locator("input").press("Enter");
  await page.waitForTimeout(150);
  check("بيع رقمٍ مرتجع: يقول إنه رجع بالمرتجع R-00001", (await page.content()).includes("رجع بالمرتجع R-00001"));
  check("ويعبّئ وزنه من المرتجع تلقائياً (12)",
    (await page.locator("label.f", { hasText: "الوزن المقيد" }).locator("input").inputValue()) === "12.00");
  await shot("resale_autofill");
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  check("وتبديل العيار يحوّل الأوزان (12 جم 18 = 10.29 جم 21)",
    (await page.locator("label.f", { hasText: "الوزن المقيد" }).locator("input").inputValue()) === "10.29");
  await tap("button:has-text('+ إضافة سطر')");
  await tap(".footer-bar .btn:has-text('ترحيل الفاتورة')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  const resold = await page.evaluate(() => App.state.invoices.find((d) => d.no === "S-00002"));
  check("ويُرحَّل بوزنه الدقيق 12 مكافئ 18 (لا 12.001)", resold && resold.totalW18 === 12, resold && resold.totalW18);
  check("وبأجره الدقيق: 12 جم × 20 = 240.00 (لا 239.97 من 23.33 المعروضة)", resold && resold.wages === 240, resold && resold.wages);

  // سند قبض: 6 جم عيار 21 + 500 نقداً
  await page.goto(url + "#/voucher/new?kind=receipt");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await fill("الوزن الفعلي", "6");
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await tap("button:has-text('+ نقد')");
  await fill("المبلغ", "500");
  check("مكافئ 6 جم عيار 21 = 7.00 جم عيار 18", (await page.content()).includes("= 7.00 جم عيار 18"));
  await shot("voucher");
  await tap(".footer-bar .btn:has-text('ترحيل السند')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/vo\//);
  check("رُحّل السند RV-00001", (await text("#bar h1")).includes("RV-00001"));

  // كشف الحساب
  const shopId = await page.evaluate(() => App.state.shops.find((s) => s.name === "محل الأمانة").id);
  await page.goto(url + `#/statement/${shopId}`);
  await page.waitForTimeout(200);
  const kp = await text(".kpis");
  // بيع 654 − مرتجع 240 − قبض 500 = 86 للمحل؛ وذهب 33 − 12 − 7 = 14 عليه
  check("كشف الحساب: 14.00 جم عليه و86.00 ريال له", kp.includes("14.00 جم عليه") && kp.includes("86.00 ريال له"), kp);
  await shot("statement");

  // حركة الطقم
  await page.goto(url + "#/wo?no=W100");
  await page.waitForTimeout(200);
  check("حركة W100: ثلاث حركات، والآن عند محل النخبة",
    (await page.locator(".list-item").count()) === 3 && (await page.content()).includes("الآن: عند «محل النخبة»"));
  await shot("wo_history");

  // العملاء: الأرصدة ثم «المبيعات والسداد»
  await tap("#tabs button[data-tab=customers]");
  await page.waitForURL(/#\/customers/);
  await page.waitForTimeout(200);
  check("شاشة العملاء: محلان بصورة رمزية", (await page.locator(".list-item .avatar").count()) === 2);
  await shot("customers");
  await tap(".seg button:has-text('المبيعات والسداد')");
  await page.waitForURL(/view=board/);
  await page.waitForTimeout(200);
  check("المبيعات والسداد: خمس بلاطات", (await page.locator(".stat").count()) === 5);
  const amana = page.locator(".list-item.col", { hasText: "محل الأمانة" });
  const at = (await amana.innerText()).replace(/\s+/g, " ");
  // ذهب: صافي 33 − 12 = 21، سداد 7، باقي 14 → 33.3% «سيء»
  check("الأمانة: صافي 21.00 وسداد 7.00 وباقي 14.00 — «سيء»",
    at.includes("21.00") && at.includes("7.00") && at.includes("14.00") && at.includes("سيء"), at);
  await shot("customers_board");
  await tap(".seg.sm button:has-text('النقد')");
  await page.waitForURL(/side=cash/);
  await page.waitForTimeout(200);
  const ct = (await page.locator(".list-item.col", { hasText: "محل الأمانة" }).innerText()).replace(/\s+/g, " ");
  // نقد: صافي 654 − 240 = 414، سداد 500 → مسدَّد
  check("والنقد: صافي 414.00 وسداد 500.00 — «مسدَّد»", ct.includes("414.00") && ct.includes("500.00") && ct.includes("مسدَّد"), ct);
  await tap(".chip:has-text('هذا الشهر')");
  await page.waitForTimeout(150);
  check("فلتر الفترة يعمل", page.url().includes("from="));

  // لوحة التحكم
  await tap("#tabs button[data-tab=dashboard]");
  await page.waitForURL(/#\/dashboard/);
  await page.waitForTimeout(200);
  check("لوحة التحكم: ثلاثة رسوم شهرية", (await page.locator("svg.chart").count()) === 3);
  const dk = (await text(".kpis")).replace(/\s+/g, " ");
  // ذهب: الأمانة 14 + النخبة 12 = 26 عليهم؛ نقد: النخبة 240 عليه والأمانة 86 له
  check("لوحة التحكم: 26.00 جم و240.00 ريال على العملاء و86.00 لهم",
    dk.includes("26.00") && dk.includes("240.00") && dk.includes("86.00"), dk);
  await shot("dashboard");
  await page.locator("svg.chart").first().locator(".hit").last().tap();
  check("لمس العمود يُظهر قيمته", await page.locator(".chart-tip").first().isVisible());
  await page.locator(".card button.link", { hasText: "جدول" }).first().click();
  check("والرسم يتحوّل جدولاً بستة أشهر", (await page.locator(".mini-table").first().locator("tbody tr").count()) === 6);

  // المزيد
  await tap("#tabs button[data-tab=more]");
  await page.waitForURL(/#\/more/);
  await page.waitForTimeout(200);
  check("المزيد: السجل والمعلّقات والإعدادات", (await page.content()).includes("سجل العمليات") &&
    (await page.content()).includes("المعلّقات") && (await page.content()).includes("الإعدادات والحفظ"));

  // النسخة الاحتياطية
  await page.goto(url + "#/settings");
  const [dl] = await Promise.all([page.waitForEvent("download"), tap("button:has-text('حفظ ملف')")]);
  const bk = JSON.parse(fs.readFileSync(await dl.path(), "utf8"));
  check("النسخة الاحتياطية فيها كل شيء", bk.format === "jadeite-mobile-backup" && bk.invoices.length === 3 && bk.vouchers.length === 1);

  // البيانات تبقى بعد إغلاق التطبيق
  await page.reload();
  await page.goto(url + "#/home");
  await page.waitForTimeout(300);
  check("البيانات باقية بعد إعادة الفتح", (await page.evaluate(() => App.state.invoices.length)) === 3);
  await shot("home_after");

  // الوضع الليلي
  await page.evaluate(() => { App.state.settings.theme = "dark"; document.documentElement.setAttribute("data-theme", "dark"); });
  await page.goto(url + "#/customers");
  await page.waitForTimeout(200);
  await shot("customers_dark");
  await page.goto(url + "#/dashboard");
  await page.waitForTimeout(300);
  await shot("dashboard_dark");

  check("بلا أي خطأ في الصفحة", !errors.length, errors.slice(0, 3).join(" | "));
  await browser.close();
  srv.close();
  console.log(`\n${fail ? "✘" : "✔"} ${pass} نجح · ${fail} فشل`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
