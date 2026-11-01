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

// صورة طقمٍ صغيرة للتجربة
const PHOTO = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAHgAAABaCAIAAAD8YgW4AAAB3UlEQVR4nO3cQU4CURBFUTSuxK040yW5E/ehM/fm4CcdJ4gIdd9rvHeMdPVJ8YHEcPf2+niw+e7TA/yXhIYSGkpoKKGhhIYSGkpoKKGhhIYSGkpoKKGhhIZ6SA/wq55fnn5+wMf7JzPJn+uFPol77MGd6I3QZxEf+/M27iLoC32PPVuJeMub4XWVmWc+q/xGAxANh0l4o8l1y652Epq/86B1DDp1z6nrZqCzr+LI1QPQDR8D+Blo6AblFTwJCt2jvCLn4aDblFfYVC3fDG8+CLpznVfMbAR0s/IKmNCjA0poqHHo/nNjNT2nGw01C72XdV6NTutGQwkNJTTUIPS+DujV3MxuNJTQUEJDCQ0lNJTQUEJDCQ0lNJTQUIPQJf8BflZzM7vRUEJDCQ01C72vY3p0Wjcaahx6L0s9PacbDSU0FAHdf3oAE0Ib3WzNzObRAcVBdy41NhW60W3W5Dz00dFjDU8SOKMbrPkZMm+GWevI1WOfOlLWqesmP97x9xx8JYU/R5N3nj2v8j/1s+5/9H98G95+W74Zzlk0KB8aNnprE7nKdpf4bhVBb114mLQRrxqhV9+9/G1SqH7Hk7W8Gd58QkMJDSU0lNBQQkMJDSU0lNBQQkMJDSU0lNBQX5byfydN38LHAAAAAElFTkSuQmCC", "base64");

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

  // ملف الرعاة التجريبي (بدل GitHub)
  const PROMO = { channel: "jadeite-promo", footer: "أُنشئ بتطبيق «نظام محاسبي للذهب» — 0559876543",
    contact: { phone: "0559876543", whatsapp: "966559876543", text: "" },
    items: [{ id: "ad-1", title: "مصنع الريان للذهب", text: "أطقم عيار 21 بأسعار المصنع", phone: "0501234567",
      whatsapp: "966501234567", link: "javascript:alert(1)", until: "2099-01-01" },
    { id: "ad-old", title: "إعلانٌ منتهٍ", until: "2000-01-01" }] };
  await page.route("https://raw.githubusercontent.com/**/promo.json*", (r) => r.fulfill({ json: PROMO }));
  await page.goto(url);
  await page.waitForSelector("#tabs");
  const tiles = await page.locator(".op-tile .op-t").allInnerTexts();
  check("الرئيسية: ستّ لوحاتٍ بالترتيب", tiles.join("،") ===
    "بيع للعميل،مرتجع للعميل،بضاعة من مصنع،إرجاع للمصنع،تحصيل من العميل،سداد للمصنع", tiles.join("،"));
  check("ثم «كشف حساب» ثم «عمليات اليوم» — ولا لوحات أرصدة", (await page.locator(".wide-tile .op-t").allInnerTexts()).join("،") ===
    "كشف حساب،عمليات اليوم (0)" && (await page.locator(".kpis").count()) === 0);
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
  check("خانة «أحجار/فصوص» وخانة الماس وخانة الصورة", html0.includes("أحجار/فصوص") && html0.includes("💎 الماس (جم)") && html0.includes("صورة الطقم"));
  await fill("الطقم", "T1");
  await page.locator("label.f", { hasText: "الطقم" }).locator("input").press("Enter");
  await fill("الوزن (جم)", "12");
  await fill("💎 الماس", "0.5");
  await page.locator('input[type=file][accept="image/*"]').setInputFiles({ name: "t1.png", mimeType: "image/png", buffer: PHOTO });
  await page.waitForSelector(".photo-pick img.thumb");
  await page.waitForFunction(() => (document.querySelector(".photo-pick img.thumb") || {}).src && document.querySelector(".photo-pick img.thumb").src.startsWith("data:image/jpeg"));
  check("الصورة تُختار وتظهر مصغّرةً في السطر", true);
  await shot("photo_entry");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(250);
  const l1 = page.locator(".line").first();
  check("أجر المصنع المتفق عليه: 12 × 8 = 96", (await l1.innerText()).includes("96.00"));
  check("والسطر بصورته وماسه", (await l1.locator("img.thumb").count()) === 1 && (await l1.innerText()).includes("0.50"));
  check("وخانة الصورة تفرغ للسطر التالي", (await page.locator(".photo-pick img.thumb").count()) === 0);
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
  check("لا لوحة «الطقوم» في الممتلكات", (await page.locator(".box-tile", { hasText: "الطقوم" }).count()) === 0);
  const ft = (await text(".wide-tile.fac")).replace(/\s+/g, " ");
  check("ذهب المصانع عندي: 82.00 (50 سابق + 32 بضاعة)", ft.includes("ذهب المصانع عندي") && ft.includes("82.00"), ft);
  await page.locator(".wide-tile.fac").click();
  await page.waitForSelector(".sheet");
  const fs1 = (await text(".sheet")).replace(/\s+/g, " ");
  check("ولكل مصنع: أخذتُ 32.00 · وعليّ 82.00", fs1.includes("مصنع الريان") && fs1.includes("أخذتُ 32.00") && fs1.includes("82.00 جم عليّ"), fs1);
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
    (await page.locator("label.f", { hasText: "الأجور" }).locator("input").inputValue()) === "");
  check("والأجور المتفق عليها تُقترح للوزن (20 × 20 = 400)", (await page.locator("label.f", { hasText: "الأجور" }).locator("input").getAttribute("placeholder")) === "تلقائي 400.00");
  check("الرأس: «فاتورة بيع» واسم العميل والتاريخ — بلا خانات", (await text("#bar h1")).includes("فاتورة بيع") &&
    (await text("#bar .chip-btn.party")).includes("محل الأمانة") && (await page.locator("#bar .chip-btn.date").count()) === 1 &&
    !(await page.content()).includes("العملية والحساب") && !(await page.content()).includes("الأجر لكل جرام"));
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  check("بأجر المحل المتفق عليه: 20 × 20 = 400", (await page.locator(".line").first().innerText()).includes("400.00"));
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(100);
  check("سطرٌ فارغ لا يُضاف: الوزن أو الأجور أو الماس", (await text("#toast")).includes("اكتب الوزن، أو الأجور، أو الماس"), await text("#toast"));
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
  await fill("الأجور", "100");
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
  check("شاشة التحصيل بلا «قبض» ولا «صرف»", (await text("#bar h1")).includes("تحصيل من العميل") &&
    !(await page.content()).includes("سند قبض") && !(await page.content()).includes("سند صرف"));
  await fill("الوزن (جم)", "6");
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await tap("button:has-text('+ نقد')");
  await fill("المبلغ", "300");
  check("مكافئ 6 جم عيار 21 = 7.00 جم عيار 18", (await page.content()).includes("= 7.00 جم عيار 18"));
  check("ولا كلمة «null» في الشاشة", !(await page.locator("#view").innerText()).includes("null"));
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
  const ct = (await text(".wide-tile.cus")).replace(/\s+/g, " ");
  // الأمانة: 25 − 5 − 7 = 13 ذهباً، و500 − 100 − 300 = 100 أجوراً
  check("ذهبي عند العملاء: 13.00 وأجور 100.00", ct.includes("ذهبي عند العملاء") && ct.includes("13.00") && ct.includes("100.00"), ct);
  check("وذهب المصانع عندي بعد السداد: 77.33 ونقد 56.00", (await text(".wide-tile.fac")).includes("77.33") && (await text(".wide-tile.fac")).includes("56.00"));
  await page.locator(".wide-tile.cus").click();
  await page.waitForSelector(".sheet");
  const cs1 = (await text(".sheet")).replace(/\s+/g, " ");
  check("ولكل عميل كم عنده: الأمانة 13.00 جم عليه", cs1.includes("محل الأمانة") && cs1.includes("13.00 جم عليه"), cs1);
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await page.waitForURL(/#\/statement\//);
  check("واللمس يفتح كشفه", true);
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(250);
  await shot("holdings");
  await page.locator(".box-tile", { hasText: "عيار 21" }).click();
  await page.waitForSelector(".sheet");
  const bs = await text(".sheet");
  check("تفصيل الصندوق: من «محل الأمانة» +6.00 وإلى «مصنع الريان» −4.00 بتاريخه",
    bs.includes("محل الأمانة") && bs.includes("+6.00") && bs.includes("مصنع الريان") && bs.includes("−4.00") && bs.includes("RV-00001"), bs);
  await shot("box_detail");
  await page.goBack();
  await page.waitForTimeout(150);

  // بيع T1 من «الطقوم التي معي»
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل النخبة" }).click();
  await page.waitForTimeout(200);
  await tap("button:has-text('اختر من الطقوم التي معي')");
  await page.waitForSelector(".sheet");
  check("الطقوم التي معي: T1 بصورته", (await page.locator(".sheet .list-item", { hasText: "T1" }).locator("img.thumb").count()) === 1);
  await page.locator(".sheet .list-item", { hasText: "T1" }).click();
  await page.waitForTimeout(200);
  check("اختياره يعبّئ اسمه ووزنه",
    (await page.locator("label.f", { hasText: "الطقم" }).locator("input").inputValue()) === "T1" &&
    (await page.locator("label.f", { hasText: "الوزن (جم)" }).locator("input").inputValue()) === "12.00");
  check("ويحمل ماسه 0.50 وصورته", (await page.locator("label.f", { hasText: "الماس" }).locator("input").inputValue()) === "0.50" &&
    (await page.locator(".photo-pick img.thumb").count()) === 1);
  await fill("الأجور", "180");
  await tap("button:has-text('+ إضافة')");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  await page.waitForFunction(() => (document.querySelector(".preview iframe") || {}).srcdoc && document.querySelector(".preview iframe").srcdoc.includes("data:image/jpeg"));
  check("الفاتورة المطبوعة فيها صورة الطقم وعمود الماس", await page.evaluate(() => {
    const x = document.querySelector(".preview iframe").srcdoc; return x.includes("<th>الصورة</th>") && x.includes("💎 الماس (جم)"); }));
  await shot("sale_doc_photo");
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
  await page.waitForTimeout(400);
  check("الكشف: الحساب في الأعلى، ومعاينته صورةً بعرض الشاشة", (await text(".card .pick")).includes("محل الأمانة") &&
    (await page.locator(".preview.fluid iframe").count()) === 1 &&
    (await page.evaluate(() => document.querySelector(".preview.fluid iframe").srcdoc.includes("<!--page-width:720-->"))));
  await shot("statement_preview");
  check("مستندات الكشف الثلاثة (بيع · مرتجع · تحصيل)، لكلٍّ «معاينة»", (await page.locator(".op-row .prev-btn").count()) === 3 &&
    (await text(".sec-title:has-text('مستندات الكشف')")).includes("(3)"));
  await page.locator(".op-row", { hasText: "R-00001" }).locator(".prev-btn").click();
  await page.waitForSelector(".sheet .preview iframe");
  await page.waitForTimeout(300);
  check("ومعاينتها تُظهر المرتجع R-00001", await page.evaluate(() => document.querySelector(".sheet .preview iframe").srcdoc.includes("R-00001")));
  await page.goBack();
  await page.waitForTimeout(200);
  const kp = await text(".kpis");
  // ذهب 25 − 5 − 7 = 13 عليه · أجور 500 − 100 − 300 = 100 عليه
  check("كشف المحل: 13.00 جم و100.00 ريال عليه", kp.includes("13.00 جم عليه") && kp.includes("100.00 ريال عليه"), kp);
  // تبديل الحساب من الكشف نفسه ← النخبة، ثم «كشف بالألماس»
  await tap(".card .pick");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل النخبة" }).click();
  await page.waitForTimeout(400);
  check("تبديل الحساب من الكشف", (await text(".card .pick")).includes("محل النخبة"));
  await tap(".seg button:has-text('كشف بالألماس')");
  await page.waitForURL(/view=diamond/);
  await page.waitForTimeout(400);
  const dk = (await text(".kpis")).replace(/\s+/g, " ");
  check("كشف الألماس للنخبة: صافي 0.50 جم", dk.includes("0.50"), dk);
  check("ومعاينته: «كشف حساب الماس» بالطقم T1 (0.50)", await page.evaluate(() => {
    const x = document.querySelector(".preview.fluid iframe").srcdoc; return x.includes("كشف حساب الماس") && x.includes("T1 (0.50)"); }));
  await shot("statement_diamond");

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
  check("عمليات اليوم (6)", (await text(".wide-tile.today")).includes("عمليات اليوم (6)"), await text(".wide-tile.today"));
  await page.waitForSelector(".sponsor");
  const sp = (await text(".sponsor")).replace(/\s+/g, " ");
  check("بطاقة الراعي في أسفل الرئيسية: «مصنع الريان للذهب» بواتساب واتصال", sp.includes("راعٍ") && sp.includes("مصنع الريان للذهب") &&
    sp.includes("واتساب") && sp.includes("اتصال"), sp);
  check("والرابط غير https لا يظهر، والإعلان المنتهي لا يظهر", !sp.includes("التفاصيل") && (await page.locator(".sponsor").count()) === 1);
  check("وهي بعد لوحات العمليات", await page.evaluate(() => {
    const a = document.querySelector(".wide-tile.today"), b = document.querySelector(".sponsor");
    return !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING); }));
  await shot("home");
  await tap(".sponsor .sp-x");
  await page.waitForTimeout(200);
  check("وتُغلق بلمسة", (await page.locator(".sponsor").count()) === 0);
  await page.goto(url + "#/more");
  await page.waitForTimeout(200);
  await tap(".list-item:has-text('أعلن في التطبيق')");
  await page.waitForSelector(".sheet");
  check("«أعلن في التطبيق» بواتساب صاحب التطبيق", (await text(".sheet")).includes("أعلن في التطبيق") && (await text(".sheet")).includes("واتساب"));
  await page.goBack();
  await page.goto(url + "#/home");
  await page.waitForTimeout(250);
  await tap(".wide-tile.today");
  await page.waitForURL(/#\/today/);
  await page.waitForTimeout(250);
  check("عمليات اليوم: ستٌّ، لكلٍّ زرّ «معاينة»", (await page.locator(".op-row").count()) === 6 &&
    (await page.locator(".op-row .prev-btn").count()) === 6);
  await page.locator(".op-row", { hasText: "S-00002" }).locator(".prev-btn").click();
  await page.waitForSelector(".sheet .preview iframe");
  await page.waitForTimeout(400);
  check("والمعاينة تُظهر الفاتورة، وأسفلها سطر التعريف", await page.evaluate(() => {
    const x = document.querySelector(".sheet .preview iframe").srcdoc; return x.includes("S-00002") && x.includes("أُنشئ بتطبيق «نظام محاسبي للذهب» — 0559876543"); }));
  await shot("today_preview");
  await page.goBack();
  await page.waitForTimeout(200);

  // «+ جديد»
  await tap("#tabs button[data-tab=plus]");
  await page.waitForSelector(".sheet");
  const ns = await text(".sheet");
  check("«+» بلا قبض ولا صرف: مع المحلات · مع المصانع", ns.includes("مع المحلات") && ns.includes("مع المصانع") &&
    ns.includes("تحصيل") && ns.includes("سداد للمصنع") && !ns.includes("سند قبض") && !ns.includes("سند صرف"));
  await page.goBack();

  // السجل
  await page.goto(url + "#/log");
  await page.waitForTimeout(150);
  await tap(".chip:has-text('تحصيل')");
  await page.waitForTimeout(100);
  check("السجل ← تحصيل: سندٌ واحد", (await page.locator(".list-item").count()) === 1);

  // النسخة الاحتياطية
  await page.goto(url + "#/settings");
  await page.waitForTimeout(200);
  check("لا «نشر للمستخدمين» في التطبيق", !(await page.content()).includes("النشر للمستخدمين") && !(await page.content()).includes("مفتاح النشر"));
  const [dl] = await Promise.all([page.waitForEvent("download"), tap("button:has-text('حفظ ملف')")]);
  const bk = JSON.parse(fs.readFileSync(await dl.path(), "utf8"));
  check("النسخة الاحتياطية فيها كل شيء", bk.format === "jadeite-mobile-backup" && bk.invoices.length === 4 && bk.vouchers.length === 2 &&
    bk.shops.some((x) => x.type === "factory") && dl.suggestedFilename().startsWith("gold-backup-"), dl.suggestedFilename());
  check("وفيها صورة الطقم", Object.keys(bk.photos || {}).length === 1 && Object.values(bk.photos)[0].startsWith("data:image/jpeg"));

  // البيانات تبقى بعد إغلاق التطبيق
  await page.reload();
  await page.goto(url + "#/home");
  await page.waitForTimeout(300);
  check("البيانات باقية بعد إعادة الفتح", (await page.evaluate(() => App.state.invoices.length)) === 4);

  // سطرٌ بالماس وحده، وآخر بالأجور وحدها، وثالثٌ بالذهب وحده — وتُرحَّل
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل النخبة" }).click();
  await page.waitForTimeout(200);
  await fill("💎 الماس", "0.3");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  await fill("الأجور", "50");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  await fill("الوزن (جم)", "2");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(150);
  const ls = await page.locator(".line").allInnerTexts();
  check("ماسٌ فقط · أجورٌ فقط · ذهبٌ فقط", ls.length === 3 && ls[0].includes("ماس فقط") && ls[1].includes("أجور فقط") &&
    ls[2].includes("2.00"), ls.join(" | "));
  await shot("special_lines");
  await tap(".footer-bar .btn:has-text('ترحيل')");
  await confirm("ترحيل");
  await page.waitForURL(/#\/doc\/inv\//);
  const s3 = await page.evaluate(() => { const d = App.state.invoices.find((x) => x.no === "S-00003");
    return d && [d.totalW18, d.wages, Domain.diamondOf(d)]; });
  check("رُحّلت S-00003: وزن 2 وأجور 50 وماس 0.3", s3 && s3.join() === "2,50,0.3", JSON.stringify(s3));

  // الوضع الليلي
  await page.evaluate(() => { App.state.settings.theme = "dark"; document.documentElement.setAttribute("data-theme", "dark"); });
  await page.goto(url + "#/home");
  await page.waitForTimeout(300);
  await shot("home_dark");
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
