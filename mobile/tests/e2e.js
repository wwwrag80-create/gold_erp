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
  check("الاسم: نظام محاسبي للذهب، والشعار في الشريط", (await text("#bar h1")).includes("نظام محاسبي للذهب") &&
    (await page.locator("#bar img.bar-logo").count()) === 1);
  check("خمسة أزرار سفلية بأيقونات: الحسابات والممتلكات", (await page.locator("#tabs button .i svg").count()) === 5 &&
    (await text("#tabs")).includes("الحسابات") && (await text("#tabs")).includes("الممتلكات") && !(await text("#tabs")).includes("لوحة التحكم"));
  check("زر التحديث مخفيٌّ في المتصفح (يعمل في أندرويد)", !(await page.locator("#upd-btn").isVisible()));
  check("لا شاشة ترحيب خارج أندرويد", !page.url().includes("welcome"));
  await shot("home_empty");

  // الإعدادات
  await page.goto(url + "#/settings");
  await fill("الاسم", "مؤسسة الذهب");
  await tap("button:has-text('حفظ الإعدادات')");
  await page.waitForTimeout(200);

  // محلان ومصنع
  for (const [name, wage] of [["محل الأمانة", "20"], ["محل النخبة", ""]]) {
    await page.goto(url + "#/shop-form");
    await fill("اسم المحل", name);
    if (wage) await fill("الأجرة المتفق عليها", wage);
    await tap(".footer-bar .btn:has-text('حفظ')");
    await page.waitForTimeout(250);
  }
  await page.goto(url + "#/shop-form?type=factory");
  await page.waitForTimeout(150);
  check("نموذج المصنع: «دَينٌ سابق» و«عليّ له»", (await page.content()).includes("دَينٌ سابق") && (await page.content()).includes("عليّ له"));
  await fill("اسم المصنع", "مصنع الريان");
  await fill("أجرة المصنع", "8");
  await fill("ذهب (جم عيار 18)", "50");
  await tap(".footer-bar .btn:has-text('حفظ')");
  await page.waitForURL(/#\/shop\//);
  await page.waitForTimeout(200);
  check("المصنع: عليّ له 50.00 جم", (await text(".kpis")).includes("50.00 جم عليّ"), await text(".kpis"));
  check("أُضيف محلان ومصنع", (await page.evaluate(() => [App.state.shops.length, App.state.shops.filter((x) => x.type === "factory").length].join())) === "3,1");
  await shot("factory_page");

  // بضاعة من المصنع: طقمٌ باسمه وآخر بلا اسم
  await page.goto(url + "#/invoice/new?kind=purchase");
  await page.waitForSelector(".sheet");
  check("اختيار المصنع يعرض المصانع وحدها", (await page.locator(".sheet .list-item").count()) === 1);
  await page.locator(".sheet .list-item", { hasText: "مصنع الريان" }).click();
  await page.waitForTimeout(150);
  const html0 = await page.content();
  check("لا خانة موديل ولا فصوص ولا «الأحجار بعد الخصم»", !html0.includes("رقم الموديل") && !html0.includes("الفصوص") && !html0.includes("بعد الخصم"));
  check("وخانة «الطقم (اختياري)»", html0.includes("الطقم (اختياري)") && !html0.includes("رقم التشغيل"));
  await fill("الطقم", "T1");
  await page.locator("label.f", { hasText: "الطقم" }).locator("input").press("Enter");
  await fill("الوزن (جم)", "12");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  check("أجر المصنع المتفق عليه: 12 × 8 = 96", (await page.locator(".line").first().innerText()).includes("96.00"));
  await fill("الوزن (جم)", "20");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  check("وسطرٌ بلا اسم طقم يُضاف بوزنه", (await page.locator(".line").count()) === 2 && (await page.locator(".line").nth(1).innerText()).includes("طقم 2"));
  await shot("purchase_editor");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("رُحّلت البضاعة P-00001", (await text("#bar h1")).includes("P-00001"));
  await page.waitForTimeout(500);
  await shot("purchase_doc");

  // الممتلكات: الطقمان في يدي
  await tap("#tabs button[data-tab=holdings]");
  await page.waitForURL(/#\/holdings/);
  await page.waitForTimeout(200);
  check("الممتلكات: صندوق الطقوم فيه 2", (await page.locator(".box-tile", { hasText: "الطقوم" }).innerText()).includes("2"));
  await page.locator(".box-tile", { hasText: "الطقوم" }).click();
  await page.waitForSelector(".sheet");
  const ps = await text(".sheet");
  check("وتفصيلها: T1 وطقمٌ بلا اسم، من «مصنع الريان»", ps.includes("T1") && ps.includes("طقمٌ بلا اسم") && ps.includes("مصنع الريان"), ps);
  await page.keyboard.press("Escape");
  await page.goBack();
  await page.waitForTimeout(200);

  // بيعٌ لمحل: الطقم بلا اسم من الممتلكات، وسطرٌ بوزنٍ فقط
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  check("اختيار المحل يعرض المحلات وحدها", (await page.locator(".sheet .list-item").count()) === 2);
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await page.waitForTimeout(150);
  await tap("button:has-text('اختر من الطقوم التي معي (2)')");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "طقمٌ بلا اسم" }).click();
  await page.waitForTimeout(200);
  check("اختياره يعبّئ وزنه 20 ولا يأخذ أجر المصنع",
    (await page.locator("label.f", { hasText: "الوزن (جم)" }).locator("input").inputValue()) === "20.00" &&
    (await page.locator("label.f", { hasText: "الأجر لكل جرام" }).locator("input").inputValue()) === "");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  check("بأجر المحل المتفق عليه: 20 × 20 = 400", (await page.locator(".line").first().innerText()).includes("400.00"));
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(100);
  check("الوزن لازم", (await text("#toast")).includes("أدخل الوزن"), await text("#toast"));
  await fill("الوزن (جم)", "5");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  const totals = await text(".totals");
  check("الإجماليات: 25.00 جم و500.00 ريال", totals.includes("25.00") && totals.includes("500.00"), totals);
  await shot("sale_editor");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("رُحّلت الفاتورة S-00001", (await text("#bar h1")).includes("S-00001"));
  await page.waitForTimeout(500);
  await shot("sale_doc");

  // مرتجع من المحل بوزنه فقط
  await page.goto(url + "#/invoice/new?kind=sale_return");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await page.waitForTimeout(100);
  await fill("الوزن (جم)", "5");
  await fill("الأجر لكل جرام", "20");
  await tap("button:has-text('+ إضافة')");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("رُحّل المرتجع R-00001", (await text("#bar h1")).includes("R-00001"));

  // تحصيل من المحل: 6 جم عيار 21 + 300 نقداً
  await page.goto(url + "#/voucher/new?kind=receipt");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await page.waitForTimeout(100);
  check("شاشة التحصيل بلا «قبض» ولا «صرف»", (await text("#bar h1")).includes("تحصيل من محل") &&
    !(await page.content()).includes("سند قبض") && !(await page.content()).includes("سند صرف"));
  await fill("الوزن (جم)", "6");
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await tap("button:has-text('+ نقد')");
  await fill("المبلغ", "300");
  check("مكافئ 6 جم عيار 21 = 7.00 جم عيار 18", (await page.content()).includes("= 7.00 جم عيار 18"));
  await shot("collect");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/vo\//);
  check("رُحّل التحصيل RV-00001", (await text("#bar h1")).includes("RV-00001"));

  // دفعٌ للمصنع من الصناديق: 4 جم عيار 21 + 200 نقداً
  await page.goto(url + "#/voucher/new?kind=payment");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "مصنع الريان" }).click();
  await page.waitForTimeout(100);
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await fill("الوزن (جم)", "4");
  check("يذكر ما في صندوق عيار 21: 6.00 جم", (await page.content()).includes("معك في صندوق عيار 21: 6.00 جم"));
  await tap("button:has-text('+ نقد')");
  await fill("المبلغ", "200");
  check("ويذكر النقد الذي معي: 300.00", (await page.content()).includes("معك نقداً: 300.00 ريال"));
  await shot("pay_factory");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/vo\//);
  check("رُحّل الدفع PV-00001", (await text("#bar h1")).includes("PV-00001"));

  // الممتلكات بعدها
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(250);
  const b21 = await page.locator(".box-tile", { hasText: "عيار 21" }).innerText();
  check("صندوق عيار 21: 2.00 جم (حصّلت 6 · دفعت 4)", b21.includes("2.00") && b21.includes("حصّلت 6.00") && b21.includes("دفعت 4.00"), b21);
  check("صندوق النقد: 100.00", (await page.locator(".box-tile", { hasText: "الأجور والنقد" }).innerText()).includes("100.00"));
  check("والطقوم 2: T1 والمرتجع", (await page.locator(".box-tile", { hasText: "الطقوم" }).innerText()).includes("2"));
  await shot("holdings");
  await page.locator(".box-tile", { hasText: "عيار 21" }).click();
  await page.waitForSelector(".sheet");
  const bs = await text(".sheet");
  check("تفصيل الصندوق: من «محل الأمانة» +6.00 وإلى «مصنع الريان» −4.00 بتاريخه",
    bs.includes("محل الأمانة") && bs.includes("+6.00") && bs.includes("مصنع الريان") && bs.includes("−4.00") && bs.includes("RV-00001"), bs);
  await shot("box_detail");
  await page.goBack();
  await page.waitForTimeout(150);

  // بيع T1 من الممتلكات مباشرة
  await page.locator(".box-tile", { hasText: "الطقوم" }).click();
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "T1" }).click();
  await page.waitForTimeout(150);
  await tap(".sheet button:has-text('بيعه لمحل')");
  await page.waitForURL(/kind=sale&piece=/);
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل النخبة" }).click();
  await page.waitForTimeout(150);
  check("بيعه من الممتلكات يعبّئ اسمه ووزنه",
    (await page.locator("label.f", { hasText: "الطقم" }).locator("input").inputValue()) === "T1" &&
    (await page.locator("label.f", { hasText: "الوزن (جم)" }).locator("input").inputValue()) === "12.00");
  await fill("الأجر لكل جرام", "15");
  await tap("button:has-text('+ إضافة')");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("رُحّلت S-00002، وبقي معي طقمٌ واحد (المرتجع)", (await text("#bar h1")).includes("S-00002") &&
    (await page.evaluate(() => Domain.holdings(App.state).pieces.length)) === 1);

  // كشف حساب المصنع
  const facId = await page.evaluate(() => App.state.shops.find((s) => s.type === "factory").id);
  await page.goto(url + `#/statement/${facId}`);
  await page.waitForTimeout(200);
  const fk = await text(".kpis");
  // 50 + 32 − (4 جم عيار 21 = 4.667) = 77.33 عليّ · أجور 256 − 200 = 56 عليّ
  check("كشف المصنع: 77.33 جم و56.00 ريال عليّ", fk.includes("77.33 جم عليّ") && fk.includes("56.00 ريال عليّ"), fk);
  await shot("factory_statement");

  // كشف حساب المحل
  const shopId = await page.evaluate(() => App.state.shops.find((s) => s.name === "محل الأمانة").id);
  await page.goto(url + `#/statement/${shopId}`);
  await page.waitForTimeout(200);
  const kp = await text(".kpis");
  // ذهب 25 − 5 − 7 = 13 عليه · أجور 500 − 100 − 300 = 100 عليه
  check("كشف المحل: 13.00 جم و100.00 ريال عليه", kp.includes("13.00 جم عليه") && kp.includes("100.00 ريال عليه"), kp);

  // الحسابات
  await tap("#tabs button[data-tab=customers]");
  await page.waitForURL(/#\/customers/);
  await page.waitForTimeout(200);
  check("الحسابات ← المحلات: محلان", (await page.locator(".list-item .avatar").count()) === 2);
  await tap(".seg button:has-text('المصانع')");
  await page.waitForURL(/view=factories/);
  await page.waitForTimeout(200);
  check("الحسابات ← المصانع: مصنعٌ واحد عليّ له", (await page.locator(".list-item .avatar.fac").count()) === 1 &&
    (await text(".list-item")).includes("عليّ"));
  await shot("factories");
  await tap(".seg button:has-text('المبيعات والتحصيل')");
  await page.waitForURL(/view=board/);
  await page.waitForTimeout(200);
  const at = (await page.locator(".list-item.col", { hasText: "محل الأمانة" }).innerText()).replace(/\s+/g, " ");
  check("المبيعات والتحصيل: الأمانة صافي 20.00 وتحصيل 7.00 وباقي 13.00",
    at.includes("20.00") && at.includes("7.00") && at.includes("13.00") && at.includes("التحصيل"), at);
  check("وفيها المحلات وحدها", (await page.locator(".list-item.col").count()) <= 2 &&
    !(await page.content()).includes("مصنع الريان"));
  await shot("board");

  // الرئيسية
  await tap("#tabs button[data-tab=home]");
  await page.waitForTimeout(250);
  const hk = (await text(".kpis")).replace(/\s+/g, " ");
  check("الرئيسية: ذهب على المحلات 25.00 وعليّ للمصانع 77.33", hk.includes("ذهب على المحلات 25.00") && hk.includes("عليّ للمصانع 77.33"), hk);
  check("وبطاقة «معي الآن»", (await page.content()).includes("معي الآن"));
  await shot("home");

  // «+ جديد»
  await tap("#tabs button[data-tab=plus]");
  await page.waitForSelector(".sheet");
  const ns = await text(".sheet");
  check("«+» بلا قبض ولا صرف: مع المحلات · مع المصانع", ns.includes("مع المحلات") && ns.includes("مع المصانع") &&
    ns.includes("تحصيل") && ns.includes("دفع لمصنع") && !ns.includes("سند قبض") && !ns.includes("سند صرف"));
  await page.goBack();

  // السجل
  await page.goto(url + "#/log");
  await page.waitForTimeout(150);
  await tap(".chip:has-text('تحصيل')");
  await page.waitForTimeout(100);
  check("السجل ← تحصيل: سندٌ واحد", (await page.locator(".list-item").count()) === 1);

  // النسخة الاحتياطية
  await page.goto(url + "#/settings");
  const [dl] = await Promise.all([page.waitForEvent("download"), tap("button:has-text('حفظ ملف')")]);
  const bk = JSON.parse(fs.readFileSync(await dl.path(), "utf8"));
  check("النسخة الاحتياطية فيها كل شيء", bk.format === "jadeite-mobile-backup" && bk.invoices.length === 4 && bk.vouchers.length === 2 &&
    bk.shops.some((x) => x.type === "factory") && dl.suggestedFilename().startsWith("gold-backup-"), dl.suggestedFilename());

  // البيانات تبقى بعد إغلاق التطبيق
  await page.reload();
  await page.goto(url + "#/home");
  await page.waitForTimeout(300);
  check("البيانات باقية بعد إعادة الفتح", (await page.evaluate(() => App.state.invoices.length)) === 4);

  // الوضع الليلي
  await page.evaluate(() => { App.state.settings.theme = "dark"; document.documentElement.setAttribute("data-theme", "dark"); });
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(300);
  await shot("holdings_dark");
  await page.goto(url + "#/customers?view=factories");
  await page.waitForTimeout(200);
  await shot("factories_dark");

  check("بلا أي خطأ في الصفحة", !errors.length, errors.slice(0, 3).join(" | "));
  await browser.close();
  srv.close();
  console.log(`\n${fail ? "✘" : "✔"} ${pass} نجح · ${fail} فشل`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
