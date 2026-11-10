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
  check("ثم «كشف حساب» ثم «بحث عن طقم» ثم «الأطقم التي معي» ثم «عمليات اليوم» — ولا لوحات أرصدة", (await page.locator(".wide-tile .op-t").allInnerTexts()).join("،") ===
    "كشف حساب،بحث عن طقم،الأطقم التي معي (0)،عمليات اليوم (0)" && (await page.locator(".kpis").count()) === 0);
  check("الاسم: ÀUR، والشعار في الشريط", (await text("#bar h1")).includes("ÀUR") &&
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
    await fill("اسم العميل", name);
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
  check("المصنع: عليّ له 50.00 جم", (await text(".kpis")).includes("50.00 جم عيار 18 عليّ"), await text(".kpis"));
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
  check("خانة «أحجار/فصوص» وخانة الماس وخانة الصورة", html0.includes("أحجار/فصوص") && html0.includes("💎 الماس (جم)") && html0.includes("صور الطقم"));
  check("وبعد خانة الماس مباشرةً «قيمة الماس»", await page.evaluate(() => {
    const ls = [...document.querySelectorAll("label.f")].map((x) => x.textContent.trim());
    const i = ls.findIndex((x) => x.startsWith("💎 الماس (جم)"));
    return i >= 0 && (ls[i + 1] || "").startsWith("💎 قيمة الماس (ريال)"); }));
  await fill("الطقم", "T1");
  await page.locator("label.f", { hasText: "الطقم" }).locator("input").press("Enter");
  await fill("الوزن (جم)", "12");
  await fill("💎 الماس", "0.5");
  await fill("💎 قيمة الماس", "750");
  check("خانة الصور تقبل أكثر من صورة", await page.evaluate(() => document.querySelector('input[type=file][accept="image/*"]').multiple));
  await page.locator('input[type=file][accept="image/*"]').setInputFiles([{ name: "t1.png", mimeType: "image/png", buffer: PHOTO },
    { name: "t1b.png", mimeType: "image/png", buffer: PHOTO }]);
  await page.waitForFunction(() => [...document.querySelectorAll(".photo-pick img.thumb")].filter((x) => (x.src || "").startsWith("data:image/jpeg")).length === 2);
  check("صورتان تُختاران معاً وتظهران في الخانة نفسها", (await page.locator(".photo-pick .ph-item").count()) === 2 &&
    (await text(".photo-add")).includes("+ صورة (2)"));
  await shot("photo_entry");
  await tap("button:has-text('+ إضافة')");
  await page.waitForTimeout(250);
  const l1 = page.locator(".line").first();
  check("أجر المصنع المتفق عليه: 12 × 8 = 96", (await l1.innerText()).includes("96.00"));
  check("والسطر بصورته (وعليها +1) وماسه", (await l1.locator("img.thumb").count()) === 1 && (await l1.locator(".thumb-n").innerText()) === "+1" &&
    (await l1.innerText()).includes("0.50"));
  check("وقيمة ماسه 750.00 — ولا تدخل الأجور (96.00)", (await l1.innerText()).includes("750.00") &&
    (await text(".totals")).includes("750.00") && (await page.locator(".totals .spread", { hasText: "إجمالي الأجور" }).innerText()).includes("96.00"));
  check("وخانة الصورة تفرغ للسطر التالي", (await page.locator(".photo-pick img.thumb").count()) === 0);
  await fill("الوزن (جم)", "20");
  await shot("purchase_editor");
  // بلا «+ إضافة»: الطقم المكتوب يُضاف عند «حفظ الفاتورة»
  check("الزرّ «حفظ الفاتورة» لا «ترحيل»", (await page.locator(".footer-bar .btn", { hasText: "حفظ الفاتورة" }).count()) === 1 &&
    !(await text(".footer-bar")).includes("ترحيل"));
  await tap(".footer-bar .btn:has-text('حفظ الفاتورة')");
  await page.waitForSelector(".sheet");
  check("وتأكيد الحفظ يعدّ الطقم المكتوب: 2 طقم · 32.00 جم", (await text(".sheet")).includes("2 طقم · 32.00 جم"), await text(".sheet"));
  await confirm("حفظ الفاتورة");
  await page.waitForURL(/#\/doc\/inv\//);
  check("حُفظت البضاعة P-00001 بسطرين (الثاني دون «+ إضافة»)", (await text("#bar h1")).includes("P-00001") &&
    (await page.evaluate(() => App.state.invoices.find((d) => d.no === "P-00001").lines.length)) === 2);
  await page.waitForTimeout(500);
  await shot("purchase_doc");

  // الممتلكات (1.11): لوحة «المديونية والذهب الذي معي» أولاً، ولا لوحة أطقمٍ فيها
  await tap("#tabs button[data-tab=holdings]");
  await page.waitForURL(/#\/holdings/);
  await page.waitForTimeout(200);
  check("الأطقم التي معي ليست في الممتلكات", (await page.locator("#view .wide-tile.sets").count()) === 0 &&
    !(await text("#view")).includes("الأطقم التي معي"));
  const dc = (await text(".debt-card")).replace(/\s+/g, " ");
  check("لوحة المديونية أعلى الممتلكات (قبل «معي الآن»): عيار 18 — عليّ للمصانع 82.00",
    (await page.evaluate(() => document.querySelector("#view > .card, #view > .debt-card") === document.querySelector(".debt-card"))) &&
    dc.includes("المديونية والذهب الذي معي") && dc.includes("معي (كسر)") && dc.includes("لي عند العملاء") && dc.includes("عيار 18") && dc.includes("82.00"), dc);
  await shot("holdings_debt");
  // الرئيسية: «الأطقم التي معي» — المسمّى وحده (T1 12.00)، والسطر بلا اسم (20 جم) ليس طقماً
  await tap("#tabs button[data-tab=home]");
  await page.waitForURL(/#\/home/);
  await page.waitForTimeout(200);
  const stt = (await text(".wide-tile.sets")).replace(/\s+/g, " ");
  check("في الرئيسية: الأطقم التي معي (1) ووزنها 12.00 — بلا الوزن غير المسمّى", stt.includes("الأطقم التي معي (1)") && stt.includes("12.00"), stt);
  await page.locator(".wide-tile.sets").click();
  await page.waitForSelector(".sheet .pc-row");
  check("ولمسها يعرض الطقم T1 بـ«معاينة» — ولا «طقمٌ بلا اسم»", (await page.locator(".sheet .pc-row").count()) === 1 &&
    (await page.locator(".sheet .pc-row", { hasText: "T1" }).locator(".prev-btn").count()) === 1 &&
    !(await text(".sheet")).includes("طقمٌ بلا اسم"));
  await page.locator(".sheet .pc-row", { hasText: "T1" }).locator(".prev-btn").click();
  await page.waitForFunction(() => document.querySelectorAll(".sheet").length === 2 &&
    [...document.querySelectorAll(".sheet .photo-fig img")].filter((x) => (x.src || "").startsWith("data:image")).length === 2);
  check("و«معاينة» تعرض صورتيه كلٌّ وحدها كاملة", (await page.locator(".sheet .photo-fig").count()) === 2 &&
    (await text(".sheet:last-child .photo-fig figcaption")).includes("صورة 1 من 2"));
  await page.waitForTimeout(400);
  await shot("set_photos");
  await page.goBack();
  await page.waitForTimeout(250);
  check("والرجوع يغلق الصور وحدها وتبقى قائمة الأطقم", (await page.locator(".sheet").count()) === 1 && (await page.locator(".sheet .pc-row").count()) === 1);
  await page.goBack();
  await page.waitForTimeout(250);
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(250);
  const ft = (await text(".wide-tile.fac")).replace(/\s+/g, " ");
  check("عليّ للمصانع: 82.00 (50 سابق + 32 بضاعة)", ft.includes("عليّ للمصانع") && ft.includes("82.00"), ft);
  await page.locator(".wide-tile.fac").click();
  await page.waitForSelector(".sheet");
  const fs1 = (await text(".sheet")).replace(/\s+/g, " ");
  check("ولكل مصنع: أخذتُ 32.00 · وعليّ 82.00", fs1.includes("مصنع الريان") && fs1.includes("أخذتُ 32.00") && fs1.includes("82.00 جم عيار 18 عليّ"), fs1);
  await page.goBack();
  await page.waitForTimeout(200);

  // بيعٌ لمحل: الوزن غير المسمّى (20 جم) بالوزن مباشرةً — لا يُختار من الأطقم — وسطرٌ بوزنٍ فقط
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  check("اختيار المحل يعرض المحلات وحدها", (await page.locator(".sheet .list-item").count()) === 2);
  await page.locator(".sheet .list-item", { hasText: "محل الأمانة" }).click();
  await page.waitForTimeout(150);
  await tap("button:has-text('اختر من الطقوم التي معي (1)')");
  await page.waitForSelector(".sheet");
  check("الاختيار من الأطقم: T1 وحده — والوزن بلا اسم ليس فيها", (await page.locator(".sheet .list-item").count()) === 1 &&
    (await text(".sheet")).includes("T1") && !(await text(".sheet")).includes("طقمٌ بلا اسم"));
  await page.goBack();
  await page.waitForTimeout(250);
  await fill("الوزن (جم)", "20");
  check("الوزن يُكتب مباشرةً 20 ولا يأخذ أجر المصنع",
    (await page.locator(".sheet").count()) === 0 &&
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
  await tap(".footer-bar .btn:has-text('حفظ الفاتورة')");
  await confirm("حفظ الفاتورة");
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
  await tap(".footer-bar .btn:has-text('حفظ الفاتورة')");
  await confirm("حفظ الفاتورة");
  await page.waitForURL(/#\/doc\/inv\//);
  check("حُفظ المرتجع R-00001", (await text("#bar h1")).includes("R-00001"));

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
  check("مكافئ 6 جم عيار 21 = 7.00 جم بعيار العرض (18)", (await page.content()).includes("= 7.00 جم مكافئ عيار 18") &&
    (await text(".totals")).includes("الذهب (مكافئ عيار 18)"));
  check("ولا كلمة «null» في الشاشة", !(await page.locator("#view").innerText()).includes("null"));
  await shot("collect");
  await tap(".footer-bar .btn:has-text('حفظ السند')");
  await confirm("حفظ السند");
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
  await tap(".footer-bar .btn:has-text('حفظ السند')");
  await confirm("حفظ السند");
  await page.waitForURL(/#\/doc\/vo\//);
  check("رُحّل الدفع PV-00001", (await text("#bar h1")).includes("PV-00001"));

  // الممتلكات بعدها
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(250);
  const b21 = await page.locator(".box-tile", { hasText: "عيار 21" }).innerText();
  check("صندوق عيار 21: 2.00 جم (حصّلت 6 · دفعت 4)", b21.includes("2.00") && b21.includes("حصّلت 6.00") && b21.includes("دفعت 4.00"), b21);
  check("صندوق النقد: 100.00", (await page.locator(".box-tile", { hasText: "النقد والأجور" }).innerText()).includes("100.00"));
  const ct = (await text(".wide-tile.cus")).replace(/\s+/g, " ");
  // الأمانة: 25 − 5 − 7 = 13 ذهباً، و500 − 100 − 300 = 100 أجوراً
  check("لي عند العملاء: 13.00 وأجور 100.00", ct.includes("لي عند العملاء") && ct.includes("13.00") && ct.includes("100.00"), ct);
  check("وعليّ للمصانع بعد السداد: 77.33 ونقد 56.00", (await text(".wide-tile.fac")).includes("77.33") && (await text(".wide-tile.fac")).includes("56.00"));
  await page.locator(".wide-tile.cus").click();
  await page.waitForSelector(".sheet");
  const cs1 = (await text(".sheet")).replace(/\s+/g, " ");
  check("ولكل عميل كم عنده: الأمانة 13.00 جم عليه", cs1.includes("محل الأمانة") && cs1.includes("13.00 جم عيار 18 عليه"), cs1);
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
  check("الطقوم التي معي: T1 بصورته وزرّ «معاينة»", (await page.locator(".sheet .list-item", { hasText: "T1" }).locator("img.thumb").count()) === 1 &&
    (await page.locator(".sheet .list-item", { hasText: "T1" }).locator(".prev-btn").count()) === 1);
  await page.locator(".sheet .list-item", { hasText: "T1" }).locator(".prev-btn").click();
  await page.waitForFunction(() => document.querySelectorAll(".sheet").length === 2);
  check("«معاينة» تعرض صوره دون أن تختاره", (await page.locator(".sheet .photo-fig").count()) === 2 &&
    (await page.locator("label.f", { hasText: "الطقم" }).locator("input").inputValue()) === "");
  await page.waitForTimeout(400);
  await shot("picker_photos");
  await page.goBack();
  await page.waitForTimeout(250);
  await page.locator(".sheet .list-item", { hasText: "T1" }).click();
  await page.waitForTimeout(200);
  check("اختياره يعبّئ اسمه ووزنه",
    (await page.locator("label.f", { hasText: "الطقم" }).locator("input").inputValue()) === "T1" &&
    (await page.locator("label.f", { hasText: "الوزن (جم)" }).locator("input").inputValue()) === "12.00");
  check("ويحمل ماسه 0.50 وصورتيه", (await page.locator("label.f", { hasText: "💎 الماس (جم)" }).locator("input").inputValue()) === "0.50" &&
    (await page.locator(".photo-pick img.thumb").count()) === 2);
  check("وقيمة ماس المصنع لا تُنقل للبيع (كالأجور)", (await page.locator("label.f", { hasText: "💎 قيمة الماس" }).locator("input").inputValue()) === "");
  await fill("الأجور", "180");
  await fill("💎 قيمة الماس", "900");
  await tap("button:has-text('+ إضافة')");
  await tap(".footer-bar .btn:has-text('حفظ الفاتورة')");
  await confirm("حفظ الفاتورة");
  await page.waitForURL(/#\/doc\/inv\//);
  await page.waitForFunction(() => (document.querySelector(".preview iframe") || {}).srcdoc && document.querySelector(".preview iframe").srcdoc.includes("data:image/jpeg"));
  check("الفاتورة المطبوعة فيها صورتا الطقم وعمود الماس", await page.evaluate(() => {
    const x = document.querySelector(".preview iframe").srcdoc; return x.includes("<th>الصورة</th>") && x.includes('class="phs"') && x.includes("💎 الماس (جم)"); }));
  check("وتحتها كل صورةٍ وحدها كاملة", (await page.locator("#view .photo-fig").count()) === 2);
  await shot("sale_doc_photo");
  check("رُحّلت S-00002، ولا طقم معي (المرتجع بالوزن بلا اسمٍ ليس طقماً)", (await text("#bar h1")).includes("S-00002") &&
    (await page.evaluate(() => Domain.holdings(App.state).pieces.length)) === 0);

  // البحث عن طقم من الرئيسية: الاقتراحات من أول حرف، وبالوزن، ومع من هو الآن (1.6)
  await page.goto(url + "#/home");
  await page.waitForTimeout(200);
  await tap(".wide-tile:has-text('بحث عن طقم')");
  await page.waitForURL(/#\/wo/);
  const sIn = page.locator("#view input.sr-in");
  await page.waitForTimeout(200);
  check("بحث عن طقم: الخانة جاهزة للكتابة وتلميحٌ قبلها", (await page.evaluate(() => !!document.activeElement && document.activeElement.classList.contains("sr-in"))) &&
    (await text("#view .empty")).includes("أول حرف"));
  await sIn.pressSequentially("t");
  await page.waitForTimeout(150);
  const sug = await page.locator(".sr-item").allInnerTexts();
  check("من أول حرف «t»: يظهر T1 ومكانه «عند «محل النخبة»»", sug.length === 1 && sug[0].includes("T1") && sug[0].includes("عند «محل النخبة»") &&
    sug[0].includes("12.00 جم عيار 18"), sug.join(" | "));
  check("وبصورته المصغّرة", (await page.locator(".sr-item img.thumb").count()) === 1);
  await sIn.fill("");
  await sIn.pressSequentially("١٢");
  await page.waitForTimeout(150);
  check("وبالوزن بأرقامٍ عربية «١٢» ⇒ T1", (await page.locator(".sr-item", { hasText: "T1" }).count()) === 1);
  await shot("set_search");
  await page.locator(".sr-item", { hasText: "T1" }).click();
  await page.waitForTimeout(150);
  const det = await text("#view");
  check("لمسه: «الآن: عند «محل النخبة» — مباعٌ بالفاتورة S-00002» ثم حركاته", det.includes("الآن: عند «محل النخبة» — مباعٌ بالفاتورة S-00002") &&
    (await page.locator("#view .list-item .badge", { hasText: "بيع" }).count()) >= 1 &&
    (await page.locator("#view .list-item .badge", { hasText: "بضاعة" }).count()) >= 1, det.slice(0, 160));
  await shot("set_search_detail");
  await sIn.fill("س");
  await sIn.dispatchEvent("input");
  await page.waitForTimeout(150);
  check("ونصٌّ لا يطابق: «لا طقم باسمٍ أو وزنٍ يطابق»", (await text("#view .empty")).includes("لا طقم"));

  // الإعلان (1.7): الصفحة تطلبه في شاشات التصفّح وحدها — لا في الإدخال ولا البحث
  const adOn = async (hash) => { await page.goto(url + hash); await page.waitForTimeout(150); return page.evaluate(() => Bridge.adsWanted); };
  check("الإعلان: البحث بلا إعلان، والرئيسية والممتلكات والكشف بإعلان",
    (await page.evaluate(() => Bridge.adsWanted)) === false && (await adOn("#/home")) === true &&
    (await adOn("#/holdings")) === true && (await adOn("#/customers")) === true && (await adOn("#/more")) === true);
  check("ولا إعلان في الفاتورة والسند ونموذج المحل والإعدادات",
    (await adOn("#/invoice/new?kind=sale")) === false && (await adOn("#/voucher/new?kind=receipt")) === false &&
    (await adOn("#/shop-form")) === false && (await adOn("#/settings")) === false);
  check("وفي المتصفح إعلان الويب (AdSense) مطفأٌ بلا رقم وحدة — ولا يُحمَّل شيءٌ من Google",
    await page.evaluate(() => { const a = Bridge.adsState(); return a.web === true && a.enabled === false && a.visible === false &&
      !document.querySelector('script[src*="googlesyndication"]') && !document.getElementById("webad"); }));

  // كشف حساب المصنع
  const facId = await page.evaluate(() => App.state.shops.find((s) => s.type === "factory").id);
  await page.goto(url + `#/statement/${facId}`);
  await page.waitForTimeout(200);
  const fk = await text(".st-bal");
  // 50 + 32 − (4 جم عيار 21 = 4.667) = 77.33 عليّ · أجور 256 − 200 = 56 عليّ
  check("كشف المصنع: 77.33 جم و56.00 ريال عليّ", fk.includes("77.33 جم عيار 18 عليّ") && fk.includes("56.00 ريال عليّ"), fk);
  await shot("factory_statement");

  // كشف حساب المحل
  const shopId = await page.evaluate(() => App.state.shops.find((s) => s.name === "محل الأمانة").id);
  await page.goto(url + `#/statement/${shopId}`);
  await page.waitForTimeout(400);
  check("الكشف بسيط: الحساب في الشريط، وجدولٌ واحد — بلا لوحات ولا قائمة مستندات",
    (await text("#bar .chip-btn.party")).includes("محل الأمانة") && (await page.locator(".st-table").count()) === 1 &&
    (await page.locator(".kpis").count()) === 0 && (await page.locator(".preview").count()) === 0 && (await page.locator(".prev-btn").count()) === 0);
  check("ومشاركة الكشف وطباعته أيقونتان في الشريط", (await page.locator("#bar .icon-btn[aria-label='مشاركة صورة']").count()) === 1 &&
    (await page.locator("#bar .icon-btn[aria-label='طباعة']").count()) === 1);
  await shot("statement_table");
  check("في الجدول عملياته الثلاث (بيع · مرتجع · تحصيل) ورصيد كلٍّ بعدها", (await page.locator(".st-table tr.tap").count()) === 3 &&
    (await page.locator(".st-table tr.tap", { hasText: "R-00001" }).innerText()).replace(/\s+/g, " ").includes("20.00 عليه"));
  const kp = await text(".st-bal");
  // ذهب 25 − 5 − 7 = 13 عليه · أجور 500 − 100 − 300 = 100 عليه
  check("كشف المحل: 13.00 جم و100.00 ريال عليه", kp.includes("13.00 جم عيار 18 عليه") && kp.includes("100.00 ريال عليه"), kp);
  // 1.11: «عليه · له · الرصيد» وصفّ الإجمالي آخر الجدول
  check("الأعمدة: التاريخ · العملية · عليه · له · الرصيد", (await page.locator(".st-table th").allInnerTexts()).join("،") === "التاريخ،العملية،عليه،له،الرصيد",
    (await page.locator(".st-table th").allInnerTexts()).join("،"));
  const rr = (await page.locator(".st-table tr.tap", { hasText: "R-00001" }).locator("td").allInnerTexts()).map((x) => x.replace(/\s+/g, " ").trim());
  check("المرتجع R-00001 في «له»: 5.00 جم و100.00 ريال — و«عليه» فارغ", rr[2] === "—" && rr[3] === "5.00 100.00", rr);
  const tot = (await page.locator(".st-table tr.tot td").allInnerTexts()).map((x) => x.replace(/\s+/g, " ").trim());
  check("صفّ الإجمالي: عليه 25.00 و500.00 · له 12.00 و400.00 · الباقي 13.00 عليه و100.00 عليه",
    tot[0].includes("الإجمالي") && tot[1] === "25.00 500.00" && tot[2] === "12.00 400.00" && tot[3] === "13.00 عليه 100.00 عليه", tot);
  check("الفرز: الكل · المبيعات · المرتجعات · التحصيل", (await page.locator(".st-kinds .chip").allInnerTexts()).join("،") === "الكل،المبيعات،المرتجعات،التحصيل");
  await page.locator(".st-kinds .chip", { hasText: "التحصيل" }).click();
  await page.waitForURL(/f=collect/);
  await page.waitForTimeout(250);
  const cot = (await page.locator(".st-table tr.tot td").allInnerTexts()).map((x) => x.replace(/\s+/g, " ").trim());
  check("فرز التحصيل: سند RV-00001 وحده، وإجماليه في «له» 7.00 و300.00", (await page.locator(".st-table tr.tap").count()) === 1 &&
    (await text(".st-table")).includes("RV-00001") && cot[0].includes("إجمالي التحصيل") && cot[2] === "7.00 300.00" && cot[1] === "—", cot);
  check("وأعلاه إجمالي التحصيل، ورصيد الحساب كله كما هو", (await text(".st-bal")).includes("إجمالي التحصيل") &&
    (await text(".st-bal")).includes("13.00 جم عيار 18 عليه"));
  check("والمشاركة والطباعة تتبعان الفرز", await page.evaluate((id) => {
    const x = PrintDoc.statementHtml(App.state, id, null, null, "gold", "collect");
    return x.includes("كشف حساب — التحصيل") && x.includes("RV-00001") && !x.includes("S-00001") && x.includes("إجمالي التحصيل"); }, shopId));
  await shot("statement_filter");
  await page.locator(".st-kinds .chip", { hasText: "المبيعات" }).click();
  await page.waitForURL(/f=sales/);
  await page.waitForTimeout(250);
  check("فرز المبيعات: S-00001 وحدها — 25.00 جم و500.00 ريال", (await page.locator(".st-table tr.tap").count()) === 1 &&
    (await text(".st-table tr.tot")).replace(/\s+/g, " ").includes("25.00 500.00"));
  await page.locator(".st-kinds .chip", { hasText: "الكل" }).click();
  await page.waitForTimeout(250);
  check("و«الكل» يعيد العمليات الثلاث", (await page.locator(".st-table tr.tap").count()) === 3 && !page.url().includes("f="));
  await page.locator(".st-table tr.tap", { hasText: "R-00001" }).click();
  await page.waitForSelector(".sheet .preview iframe");
  await page.waitForTimeout(300);
  check("لمس المرتجع R-00001 يعاينه، ومنه «تعديل»", await page.evaluate(() => document.querySelector(".sheet .preview iframe").srcdoc.includes("R-00001")) &&
    (await page.locator(".sheet .doc-acts .btn", { hasText: "تعديل" }).count()) === 1);
  await page.locator(".sheet .doc-acts .btn", { hasText: "تعديل" }).click();
  await page.waitForURL(/#\/invoice\/edit\//);
  await page.waitForTimeout(250);
  check("وتعديله يفتح المرتجع بسطره", (await text("#bar h1")).includes("مرتجع R-00001") && (await page.locator(".line").count()) === 1);
  await page.locator("details.opts summary").click();
  await page.locator("details.opts input.in").fill("مرتجعٌ مُعدَّل");
  await page.locator("details.opts input.in").dispatchEvent("input");
  await tap(".footer-bar .btn:has-text('حفظ التعديل')");
  await confirm("حفظ التعديل");
  await page.waitForURL(/#\/doc\/inv\//);
  check("حُفظ التعديل في R-00001 (رقمه كما هو)", (await page.evaluate(() => App.state.invoices.filter((d) => d.no === "R-00001").map((d) => d.desc).join())) === "مرتجعٌ مُعدَّل");
  await page.goto(url + `#/statement/${shopId}`);
  await page.waitForTimeout(300);
  // تبديل الحساب من الشريط ← النخبة، ثم الماس
  await tap("#bar .chip-btn.party");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "محل النخبة" }).click();
  await page.waitForTimeout(400);
  check("تبديل الحساب من الكشف", (await text("#bar .chip-btn.party")).includes("محل النخبة"));
  await tap(".st-filters .seg button:has-text('ماس')");
  await page.waitForURL(/view=diamond/);
  await page.waitForTimeout(400);
  const dk = (await text(".st-bal")).replace(/\s+/g, " ");
  check("كشف الألماس للنخبة: صافي 0.50 جم وقيمته 900.00 ريال، والطقم T1 (0.50 · 900.00) في الجدول",
    dk.includes("0.50") && dk.includes("900.00") && (await text(".st-table")).includes("T1 (0.50 · 900.00)"), dk);
  check("وفي كل خانة: الماس فوق وقيمته تحته", (await page.locator(".st-table.dia tr.tap").first().locator("td.m").count()) === 2 &&
    (await page.locator(".st-table.dia tr.tap").first().locator("td.m.b .gl").innerText()).includes("0.50") &&
    (await page.locator(".st-table.dia tr.tap").first().locator("td.m.b .cl").innerText()).includes("900.00"));
  check("وصورته المُرسَلة: «كشف حساب الماس» بالقيمة تحت الماس", await page.evaluate(() => {
    const id = App.state.shops.find((x) => x.name === "محل النخبة").id;
    const x = PrintDoc.statementHtml(App.state, id, null, null, "diamond");
    return x.includes("كشف حساب الماس") && x.includes("T1 (0.50 · 900.00)") && x.includes("0.50 جم · 900.00 ريال"); }));
  check("والقيمة لا تدخل رصيد النخبة", await page.evaluate(() => {
    const sh = App.state.shops.find((x) => x.name === "محل النخبة");
    const inv = App.state.invoices.find((d) => d.shopId === sh.id && Domain.diamondValueOf(d) === 900);
    return inv && inv.wages === 180 && inv.grand === 180; }));
  await tap(".st-period");
  await page.waitForSelector(".sheet .chip");
  await page.locator(".sheet .chip", { hasText: "هذا الشهر" }).click();
  await page.waitForURL(/from=/);
  await page.waitForTimeout(300);
  check("والفترة من زرٍّ واحد: «هذا الشهر»", (await text(".st-period")).includes("هذا الشهر"));
  await shot("statement_diamond");

  // الحسابات
  await tap("#tabs button[data-tab=customers]");
  await page.waitForURL(/#\/customers/);
  await page.waitForTimeout(200);
  check("الحسابات ← العملاء: عميلان", (await page.locator(".list-item .avatar").count()) === 2);
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
  check("وفيها العملاء وحدهم", (await page.locator(".list-item.col").count()) <= 2 &&
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
  check("«+» بلا قبض ولا صرف: مع العملاء · مع المصانع", ns.includes("مع العملاء") && ns.includes("مع المصانع") &&
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
  check("وفيها صورتا الطقم", Object.keys(bk.photos || {}).length === 2 && Object.values(bk.photos)[0].startsWith("data:image/jpeg"));

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
  await tap(".footer-bar .btn:has-text('حفظ الفاتورة')");
  await confirm("حفظ الفاتورة");
  await page.waitForURL(/#\/doc\/inv\//);
  const s3 = await page.evaluate(() => { const d = App.state.invoices.find((x) => x.no === "S-00003");
    return d && [d.totalW18, d.wages, Domain.diamondOf(d)]; });
  check("حُفظت S-00003: وزن 2 وأجور 50 وماس 0.3", s3 && s3.join() === "2,50,0.3", JSON.stringify(s3));

  // ══ 1.9: الرصيد الافتتاحي · عيار الحساب لكل عميل (و1.10: بلا لوحة «صافي ما لي») ══
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(250);
  check("الممتلكات بلا «صافي ما لي»: تبدأ بالدعوة ثم «معي الآن»", (await page.locator(".net-card").count()) === 0 &&
    !(await text("#view")).includes("صافي ما لي") && (await text("#bar")).includes("ما معي الآن"));
  check("ودعوةٌ لتسجيل الرصيد الافتتاحي", (await page.locator(".open-cta").count()) === 1);
  const hd0 = await page.evaluate(() => { const h = Domain.holdings(App.state); return { g: h.gold18, s: h.setsW18, c: h.cash.amount }; });
  await page.locator(".open-cta").click();
  await page.waitForURL(/#\/opening/);
  await fill("عيار 21 (جم)", "10");
  await fill("المبلغ (ريال)", "500");
  await tap("button:has-text('+ طقم')");
  await page.locator(".line input[placeholder^='اسم الطقم']").fill("OP1");
  await page.locator(".line input[placeholder^='اسم الطقم']").dispatchEvent("input");
  await page.locator(".line label.f", { hasText: "الوزن" }).locator("input").fill("7");
  await page.locator(".line label.f", { hasText: "الوزن" }).locator("input").dispatchEvent("input");
  await page.locator(".line label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await shot("opening");
  await tap(".footer-bar .btn:has-text('حفظ')");
  await page.waitForURL(/#\/holdings/);
  await page.waitForTimeout(250);
  const oh = await page.evaluate(() => Domain.openHold(App.state));
  check("حُفظ الرصيد الافتتاحي: 10 جم ع21 · 500 ريال · OP1 7 جم ع21", oh.gold[21] === 10 && oh.cash === 500 &&
    oh.sets.length === 1 && oh.sets[0].name === "OP1" && oh.sets[0].w18 === 8.167, JSON.stringify(oh));
  const b21o = (await page.locator(".box-tile", { hasText: "عيار 21" }).innerText()).replace(/\s+/g, " ");
  check("صندوق 21: 2 + 10 افتتاحي = 12.00", b21o.includes("12.00") && b21o.includes("افتتاحي 10.00"), b21o);
  check("والأطقم التي معي زادت OP1", await page.evaluate(() =>
    Domain.holdings(App.state).pieces.some((p) => p.name === "OP1" && p.fromKind === "opening")));
  const dc2 = (await text(".debt-card")).replace(/\s+/g, " ");
  check("ولوحة المديونية: عيار 21 معي 12.00 · والنقد بالريال · والمجموع بعيار المجاميع", dc2.includes("عيار 21") && dc2.includes("12.00") &&
    dc2.includes("النقد") && dc2.includes("المجموع"), dc2);
  await page.locator(".debt-tbl tr", { hasText: "عيار 21" }).locator("td.tap").first().click();
  await page.waitForSelector(".sheet");
  check("ولمس «معي» لعيار 21 يفتح صندوقه", (await text(".sheet")).includes("صندوق ذهب عيار 21"));
  await page.goBack();
  await page.waitForTimeout(200);
  const hd1 = await page.evaluate(() => { const h = Domain.holdings(App.state); return { g: h.gold18, s: h.setsW18, c: h.cash.amount }; });
  check("وما معي زاد: 10×21/18 = 11.667 ذهباً · OP1 8.167 · و500 نقداً",
    Math.abs(hd1.g - hd0.g - 11.667) < 0.0015 && Math.abs(hd1.s - hd0.s - 8.167) < 0.0015 && Math.abs(hd1.c - hd0.c - 500) < 0.005, JSON.stringify([hd0, hd1]));
  check("ولا دعوةً بعد التسجيل", (await page.locator(".open-cta").count()) === 0);
  await page.locator(".box-tile", { hasText: "عيار 21" }).click();
  await page.waitForSelector(".sheet");
  check("تفصيل الصندوق يبدأ بالرصيد الافتتاحي", (await text(".sheet")).includes("رصيد افتتاحي") &&
    (await text(".sheet")).includes("ما كان معي قبل التطبيق"));
  await page.goBack();
  await page.waitForTimeout(150);
  await shot("holdings_19");

  // عميلٌ بعيار 21: الرصيد الافتتاحي يُكتب بعياره ويُحفظ بمكافئ 18
  await page.goto(url + "#/shop-form");
  await page.waitForTimeout(150);
  await fill("اسم العميل", "عميل الخليج");
  await page.locator("label.f", { hasText: "عيار الحساب" }).locator("select").selectOption("21");
  await page.waitForTimeout(50);
  check("تبديل العيار يغيّر عنوان خانة الذهب", (await page.content()).includes("ذهب (جم عيار 21)"));
  await fill("ذهب (جم عيار 21)", "6");
  await page.locator("label.f", { hasText: "عيار الحساب" }).locator("select").selectOption("18");
  await page.waitForTimeout(50);
  check("وإلى 18: الوزن نفسه يصير 7.00", (await page.locator("label.f", { hasText: "ذهب (جم عيار 18)" }).locator("input").inputValue()) === "7.00");
  await page.locator("label.f", { hasText: "عيار الحساب" }).locator("select").selectOption("21");
  await page.waitForTimeout(50);
  check("وعودته إلى 21: 6.00 كما كُتب", (await page.locator("label.f", { hasText: "ذهب (جم عيار 21)" }).locator("input").inputValue()) === "6.00");
  await shot("shop_form_karat");
  await tap(".footer-bar .btn:has-text('حفظ')");
  await page.waitForURL(/#\/shop\//);
  await page.waitForTimeout(200);
  const kh = await page.evaluate(() => App.state.shops.find((x) => x.name === "عميل الخليج"));
  check("حُفظ بعيار 21 ورصيدٍ 7 مكافئ 18", kh.karat === 21 && kh.openGold18 === 7, JSON.stringify(kh));
  check("وصفحته بعياره: «عيار 21» و6.00 جم عيار 21 عليه", (await text("#bar")).includes("عيار 21") &&
    (await text(".kpis")).includes("عيار 21") && (await text(".kpis")).includes("6.00"), await text(".kpis"));
  // 1.13.1: لا زرّ عيار في الرئيسية — زرّ عيار العرض أعلى «الممتلكات» وحدها
  await page.goto(url + "#/home");
  await page.waitForTimeout(200);
  check("لا زرّ عيار أعلى الرئيسية", (await page.locator("#bar .k-chip").count()) === 0);
  await page.goto(url + "#/holdings");
  await page.waitForTimeout(250);
  check("زرّ عيار العرض أعلى الممتلكات", (await text("#bar .k-chip")).includes("عيار 18"));
  // كشف الحساب: عيار الحساب أعلى الكشف بجانب الاسم، ويُعرض بعيارٍ آخر للعرض فقط
  await page.goto(url + `#/statement/${kh.id}`);
  await page.waitForTimeout(250);
  check("الكشف بعيار الحساب: زرّ «عيار 21» بجانب الاسم", (await text("#bar .chip-btn.kar")).includes("عيار 21") &&
    (await text(".st-bal")).includes("6.00 جم عيار 21"), await text(".st-bal"));
  await tap("#bar .chip-btn.kar");
  await page.waitForSelector(".sheet .k-grid");
  await page.locator(".sheet .k-grid .chip", { hasText: "عيار 18" }).click();
  await page.waitForTimeout(300);
  check("عرضه بعيار 18 للعرض فقط: 7.00 جم عيار 18 وتنبيهٌ بعيار الحساب", (await text(".st-bal")).includes("7.00 جم عيار 18") &&
    (await text(".st-kview")).includes("عيار الحساب 21") &&
    (await page.evaluate((id) => App.state.shops.find((x) => x.id === id).karat, kh.id)) === 21, await text(".st-bal"));
  await tap(".st-kview");
  await page.waitForTimeout(300);
  check("والرجوع لعيار الحساب بلمسة", (await text("#bar .chip-btn.kar")).includes("عيار 21") && (await page.locator(".st-kview").count()) === 0);
  // فاتورة بيعٍ له: السطر يبدأ بعياره، وOP1 يُعبّأ من الرصيد الافتتاحي باسمه
  await page.goto(url + `#/invoice/new?kind=sale&shop=${kh.id}`);
  await page.waitForTimeout(250);
  check("سطر الفاتورة يبدأ بعيار 21", (await page.locator("label.f", { hasText: "العيار" }).locator("select").inputValue()) === "21");
  await page.locator("label.f", { hasText: "الطقم (اختياري)" }).locator("input").fill("OP1");
  await page.locator("label.f", { hasText: "الطقم (اختياري)" }).locator("input").dispatchEvent("change");
  await page.waitForTimeout(150);
  check("OP1 يُعبّأ من الرصيد الافتتاحي: 7.00 عيار 21", (await page.locator("label.f", { hasText: "الوزن (جم)" }).locator("input").inputValue()) === "7.00" &&
    (await page.content()).includes("من الرصيد الافتتاحي"));
  await fill("الأجور (ريال)", "70");
  check("إجمالي الوزن بعيار العميل", (await text(".totals")).includes("إجمالي الوزن (عيار 21)"));
  await tap(".footer-bar .btn:has-text('حفظ الفاتورة')");
  await confirm("حفظ الفاتورة");
  await page.waitForURL(/#\/doc\/inv\//);
  const pc = await page.evaluate(() => Domain.holdings(App.state).pieces.some((p) => p.name === "OP1"));
  check("بِيع OP1: خرج من يدي", !pc);
  check("وعلى عميل الخليج الآن 6 + 7 = 13.00 جم عيار 21", await page.evaluate((id) =>
    Num.f2(Gold.g(Domain.balance(App.state, id).gold18, 21)) === "13.00", kh.id));
  const cl = await page.evaluate((id) => App.state.invoices.find((d) => d.shopId === id).lines[0], kh.id);
  check("والسطر مربوطٌ بطقم الرصيد الافتتاحي", cl.src && cl.src.startsWith("op:") && cl.karat === 21, JSON.stringify(cl));

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
