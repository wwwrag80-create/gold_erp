// فيديو تعليمي — الخطوة 1: لقطات التطبيق الحقيقي بمقاس الجوال.
//   node mobile/tools/video/capture.js OUT_DIR
// يشغّل التطبيق في متصفحٍ بمقاس جوال (393×851، دقّة ×2)، ويمرّ بخطوات المندوب
// كما في الفيديو، ويحفظ لقطةً لكل خطوة ومكان اللمسة التالية في manifest.json.
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const WEB = path.join(__dirname, "../../web");
const OUT = path.resolve(process.argv[2] || "video-shots");
fs.mkdirSync(OUT, { recursive: true });
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

// صور أطقمٍ للعرض (رسمٌ بألوان الذهب) — قلادة · خاتم · حَلَق
const GOLD = `<radialGradient id="g" cx="35%" cy="30%" r="75%"><stop offset="0" stop-color="#FFF4C8"/>
  <stop offset=".35" stop-color="#E4C665"/><stop offset=".75" stop-color="#B08E2A"/><stop offset="1" stop-color="#5E4A0C"/></radialGradient>
  <radialGradient id="bg" cx="50%" cy="40%" r="80%"><stop offset="0" stop-color="#3A3120"/><stop offset="1" stop-color="#0B0907"/></radialGradient>
  <linearGradient id="gem" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFFFFF"/><stop offset=".5" stop-color="#E9F1F7"/><stop offset="1" stop-color="#9FB7C9"/></linearGradient>`;
function necklace() {
  let beads = "";
  for (let i = 0; i <= 26; i++) {
    const a = Math.PI * (0.12 + 0.76 * i / 26);
    const x = 450 - 330 * Math.cos(a), y = 120 + 300 * Math.sin(a);
    beads += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(12 + 5 * Math.sin(a)).toFixed(1)}" fill="url(#g)"/>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="700"><defs>${GOLD}</defs>
    <rect width="900" height="700" fill="url(#bg)"/>${beads}
    <path d="M450 430 C 400 470 395 540 450 600 C 505 540 500 470 450 430 Z" fill="url(#g)"/>
    <polygon points="450,470 478,510 450,565 422,510" fill="url(#gem)" stroke="#E4C665" stroke-width="3"/></svg>`;
}
function ring() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="700"><defs>${GOLD}</defs>
    <rect width="900" height="700" fill="url(#bg)"/>
    <ellipse cx="450" cy="420" rx="190" ry="150" fill="none" stroke="url(#g)" stroke-width="46"/>
    <polygon points="450,170 520,235 480,300 420,300 380,235" fill="url(#gem)" stroke="#E4C665" stroke-width="6"/>
    <polyline points="380,235 520,235" stroke="#FFFFFF" stroke-opacity=".7" stroke-width="3" fill="none"/>
    <circle cx="300" cy="300" r="10" fill="url(#gem)"/><circle cx="600" cy="300" r="10" fill="url(#gem)"/></svg>`;
}
function earrings() {
  const one = (x) => `<circle cx="${x}" cy="170" r="22" fill="url(#g)"/><path d="M${x} 190 L${x} 260" stroke="url(#g)" stroke-width="8"/>
    <path d="M${x} 260 C ${x - 70} 330 ${x - 60} 470 ${x} 520 C ${x + 60} 470 ${x + 70} 330 ${x} 260 Z" fill="url(#g)"/>
    <ellipse cx="${x}" cy="420" rx="26" ry="40" fill="url(#gem)" stroke="#E4C665" stroke-width="4"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="700"><defs>${GOLD}</defs>
    <rect width="900" height="700" fill="url(#bg)"/>${one(300)}${one(600)}</svg>`;
}

(async () => {
  const srv = await serve();
  const url = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch();

  // الصور أولاً
  const pg0 = await browser.newPage({ viewport: { width: 900, height: 700 } });
  const photos = {};
  for (const [k, fn] of Object.entries({ necklace, ring, earrings })) {
    await pg0.setContent(`<body style="margin:0">${fn()}</body>`);
    photos[k] = await pg0.screenshot({ type: "png" });
    fs.writeFileSync(path.join(OUT, `photo_${k}.png`), photos[k]);
  }
  await pg0.close();

  const ctx = await browser.newContext({ viewport: { width: 393, height: 851 }, deviceScaleFactor: 2,
    hasTouch: true, isMobile: true, locale: "ar" });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("pageerror:", e.message));
  // لا بطاقة راعٍ في الفيديو
  await page.route("https://raw.githubusercontent.com/**/promo.json*", (r) => r.fulfill({ status: 404, body: "" }));

  const wait = (ms) => page.waitForTimeout(ms);
  const fill = async (label, value) => {
    const f = page.locator("label.f", { hasText: label }).first().locator("input,select").first();
    await f.fill(String(value));
    await f.dispatchEvent("input");
    await f.dispatchEvent("change");
  };
  const shots = [];
  let chapter = null;
  const chap = (title, desc) => { chapter = shots.filter((s) => s.type === "chapter").length + 1; shots.push({ type: "chapter", n: chapter, title, desc }); };
  // لقطة الشاشة كما هي، ومكان اللمسة التالية (إن وُجدت) — ثم اللمسة نفسها
  async function snap(id, title, sub, tap, opts) {
    const o = opts || {};
    await page.evaluate(() => { const t = document.getElementById("toast"); if (t) t.style.display = "none"; });
    let box = null;
    if (tap) {
      await tap.scrollIntoViewIfNeeded();
      await wait(250);
      box = await tap.boundingBox();
    }
    await wait(o.settle || 350);
    const file = `${String(shots.length + 1).padStart(2, "0")}_${id}.png`;
    await page.screenshot({ path: path.join(OUT, file) });
    // تقريب الكاميرا: إلى اللمسة تلقائياً، أو إلى `focus` (بنقاط الشاشة)، أو لا تقريب
    shots.push({ type: "shot", id, file, title, sub: sub || "", tap: box, chapter,
      focus: o.zoom === false ? null : o.focus || (box ? { x: box.x + box.width / 2, y: box.y + box.height / 2, s: 1.4 } : null) });
    if (tap && !o.noClick) { await tap.click(); await wait(o.after || 450); }
    console.log("  ✔", file);
  }
  const sheetItem = (t) => page.locator(".sheet .list-item", { hasText: t }).first();
  const footerBtn = (t) => page.locator(".footer-bar .btn", { hasText: t }).first();
  const sheetBtn = (t) => page.locator(".sheet .btn", { hasText: t }).first();
  const tile = (t) => page.locator(".op-tile", { hasText: t }).first();

  await page.goto(url);
  await page.waitForSelector("#tabs");

  // ══ 1. البداية ══
  chap("البداية", "أول تشغيلٍ في دقيقة");
  await page.goto(url + "#/welcome");
  await wait(500);
  await snap("welcome", "اضغط «ابدأ» واختر مجلد الحفظ", "يُحفظ فيه كل شيء تلقائياً — ولو حذفت التطبيق وثبّته من جديد يعود كما كان",
    page.locator("button", { hasText: "ابدأ — اختر مجلد الحفظ التلقائي" }), { noClick: true });
  await page.goto(url + "#/home");
  await wait(500);
  await snap("home", "هذه الرئيسية", "ست لوحات لكل عملياتك: بيع · مرتجع · بضاعة · إرجاع · تحصيل · سداد",
    page.locator("#tabs button[data-tab=more]"), { zoom: false });
  await page.locator(".list-item", { hasText: "الإعدادات والحفظ" }).click();
  await wait(400);
  await fill("الاسم", "مؤسسة الذهب");
  await fill("الجوال", "0551234567");
  await snap("settings", "اكتب اسمك أو اسم مؤسستك", "من «المزيد» ← «الإعدادات» — ويظهر في رأس كل فاتورة",
    page.locator("button", { hasText: "حفظ الإعدادات" }));

  // ══ 2. العملاء والمصانع ══
  chap("العملاء والمصانع", "أضفهم مرةً واحدة");
  await page.goto(url + "#/shop-form");
  await wait(400);
  await fill("اسم المحل", "محل الأمانة للمجوهرات");
  await fill("الجوال", "0501112233");
  await fill("الأجرة المتفق عليها", "25");
  await snap("shop_form", "أضف العميل (المحل)", "الاسم والجوال — والأجرة المتفق عليها إن وُجدت", footerBtn("حفظ"), { after: 600 });
  await page.goto(url + "#/shop-form");
  await wait(400);
  await fill("اسم المحل", "مجوهرات النخبة");
  await footerBtn("حفظ").click();
  await wait(500);
  await page.goto(url + "#/shop-form?type=factory");
  await wait(400);
  await fill("اسم المصنع", "مصنع الريان للذهب");
  await fill("الجوال", "0509998877");
  await fill("أجرة المصنع", "20");
  await snap("factory_form", "وأضف المصنع الذي تأخذ منه", "ويُكتب ما عليك له من قبل — إن وُجد", footerBtn("حفظ"), { after: 600 });
  await page.goto(url + "#/customers");
  await wait(500);
  await snap("accounts", "كل حساباتك في «الحسابات»", "المحلات والمصانع — اضغط أي اسمٍ لترى رصيده وكشفه",
    page.locator(".seg button", { hasText: "المصانع" }), { after: 500 });

  // ══ 3. بضاعة من المصنع ══
  chap("بضاعة من المصنع", "سجّل ما استلمته");
  await page.goto(url + "#/home");
  await wait(500);
  await snap("home_purchase", "من الرئيسية: «بضاعة من مصنع»", "", tile("بضاعة من مصنع"), { after: 600 });
  await page.waitForSelector(".sheet");
  await snap("pick_factory", "اختر المصنع", "يظهر اسمه وتاريخ اليوم في أعلى الفاتورة", sheetItem("مصنع الريان"), { after: 500 });
  await fill("الطقم", "ط-101");
  await page.locator("label.f", { hasText: "الطقم" }).first().locator("input").press("Enter");
  await fill("الوزن (جم)", "24.5");
  await fill("الأجور", "490");
  await page.locator('input[type=file][accept="image/*"]').setInputFiles([
    { name: "necklace.png", mimeType: "image/png", buffer: photos.necklace },
    { name: "earrings.png", mimeType: "image/png", buffer: photos.earrings }]);
  await page.waitForFunction(() => [...document.querySelectorAll(".photo-pick img.thumb")].filter((x) => (x.src || "").startsWith("data:")).length === 2);
  await snap("set1", "اكتب الطقم: اسمه ووزنه وأجوره", "وأضف صورةً أو أكثر من الكاميرا أو المعرض", page.locator("button", { hasText: "+ إضافة" }), { after: 500 });
  await fill("الطقم", "ط-102");
  await page.locator("label.f", { hasText: "الطقم" }).first().locator("input").press("Enter");
  await fill("الوزن (جم)", "18.75");
  await fill("الأجور", "375");
  await page.locator('input[type=file][accept="image/*"]').setInputFiles([{ name: "ring.png", mimeType: "image/png", buffer: photos.ring }]);
  await page.waitForFunction(() => [...document.querySelectorAll(".photo-pick img.thumb")].filter((x) => (x.src || "").startsWith("data:")).length === 1);
  await snap("set2", "آخر طقم؟ اضغط «حفظ الفاتورة» مباشرة", "يُحفظ معها دون «+ إضافة»", footerBtn("حفظ الفاتورة"), { after: 600 });
  await page.waitForSelector(".sheet .btn");
  await snap("confirm_purchase", "راجع الإجمالي ثم احفظ", "طقمان · 43.25 جم · أجور 865 ريال", sheetBtn("حفظ الفاتورة"), { after: 700 });
  await page.waitForURL(/#\/doc\/inv\//);
  await page.waitForFunction(() => (document.querySelector(".preview iframe") || {}).srcdoc && document.querySelector(".preview iframe").srcdoc.includes("data:image"));
  await wait(700);
  await snap("purchase_doc", "فاتورتك جاهزة", "شاركها صورةً، أو اطبعها PDF، أو عدّلها — وتحتها صور الأطقم", null,
    { focus: { x: 196, y: 330, s: 1.3 } });

  // ══ 4. الأطقم التي معي ══
  chap("الأطقم التي معي", "كل طقمٍ ووزنه وصوره");
  await page.locator("#tabs button[data-tab=holdings]").click();
  await wait(600);
  await snap("holdings_sets", "في «الممتلكات»: الأطقم التي معي", "عددها ووزنها الإجمالي — اضغط لترى كل طقم", page.locator(".wide-tile.sets"), { after: 600 });
  await page.waitForSelector(".sheet .pc-row");
  await snap("pieces", "كل طقم: وزنه ومن أين جاء", "و«معاينة» تفتح صوره",
    page.locator(".sheet .pc-row", { hasText: "ط-101" }).locator(".prev-btn"), { after: 700 });
  await page.waitForFunction(() => [...document.querySelectorAll(".sheet .photo-fig img")].filter((x) => (x.src || "").startsWith("data:")).length >= 2);
  await snap("set_photos", "كل صورةٍ وحدها كاملة", "اضغط الصورة لتكبيرها", null, { settle: 600 });
  await page.goBack(); await wait(300); await page.goBack(); await wait(400);

  // ══ 5. البيع للعميل ══
  chap("البيع للعميل", "من الطقوم التي معك");
  await page.goto(url + "#/home");
  await wait(400);
  await tile("بيع للعميل").click();
  await page.waitForSelector(".sheet");
  await wait(300);
  await snap("pick_shop", "«بيع للعميل» ثم اختر العميل", "", sheetItem("محل الأمانة"), { after: 500 });
  await snap("sale_editor", "اختر من الطقوم التي معك", "فيُعبّأ وزنه وصوره تلقائياً",
    page.locator("button", { hasText: "اختر من الطقوم التي معي" }), { after: 500 });
  await page.waitForSelector(".sheet .list-item");
  await snap("picker", "اضغط الطقم لاختياره", "أو «معاينة» لترى صوره أولاً", sheetItem("ط-101").locator(".grow"), { after: 600 });
  await snap("sale_filled", "الأجور المتفق عليها تظهر تلقائياً", "اكتب غيرها إن أردت — ثم «حفظ الفاتورة»", footerBtn("حفظ الفاتورة"), { after: 600 });
  await page.waitForSelector(".sheet .btn");
  await sheetBtn("حفظ الفاتورة").click();
  await page.waitForURL(/#\/doc\/inv\//);
  await wait(600);
  // المرتجع: اسم الطقم يكفي (لقطةٌ للتعريف فقط — لا يُحفظ)
  await page.goto(url + "#/invoice/new?kind=sale_return");
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await wait(400);
  await fill("الطقم", "ط-101");
  await page.locator("label.f", { hasText: "الطقم" }).first().locator("input").press("Enter");
  await page.locator("label.f", { hasText: "الطقم" }).first().locator("input").blur();
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await wait(500);
  await snap("return", "والمرتجع: اكتب اسم الطقم فقط", "يُعبّأ وزنه وأجوره من فاتورة البيع", null,
    { focus: { x: 196, y: 330, s: 1.35 } });
  await page.evaluate(() => { try { localStorage.removeItem("draft_inv_sale_return"); } catch (e) { /* */ } });

  // ══ 6. التحصيل والسداد ══
  chap("التحصيل والسداد", "ذهبٌ بعياره، أو نقد");
  await page.goto(url + "#/voucher/new?kind=receipt");
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await wait(400);
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await fill("الوزن (جم)", "10");
  await page.locator("button", { hasText: "+ نقد" }).click();
  await fill("المبلغ", "500");
  await wait(300);
  await snap("receipt", "«تحصيل من العميل»", "ذهبٌ بعياره (يُحسب مكافئه بعيار 18) أو نقد — ويدخل صندوقك", footerBtn("حفظ السند"), { after: 600 });
  await sheetBtn("حفظ السند").click();
  await page.waitForURL(/#\/doc\/vo\//);
  await wait(400);
  await page.goto(url + "#/voucher/new?kind=payment");
  await page.waitForSelector(".sheet");
  await sheetItem("مصنع الريان").click();
  await wait(400);
  await page.locator("label.f", { hasText: "العيار" }).locator("select").selectOption("21");
  await fill("الوزن (جم)", "8");
  await page.locator("button", { hasText: "+ نقد" }).click();
  await fill("المبلغ", "300");
  await wait(300);
  await snap("payment", "«سداد للمصنع» من صناديقك", "ويخبرك كم معك في كل صندوق", footerBtn("حفظ السند"), { after: 600 });
  await sheetBtn("حفظ السند").click();
  await page.waitForURL(/#\/doc\/vo\//);
  await wait(400);

  // ══ 7. كشف الحساب ══
  chap("كشف الحساب", "بسيطٌ وواضح");
  await page.goto(url + "#/home");
  await wait(500);
  await snap("home_statement", "«كشف حساب» من الرئيسية", "ثم اختر العميل أو المصنع", page.locator(".wide-tile", { hasText: "كشف حساب" }), { after: 500 });
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await page.waitForURL(/#\/statement\//);
  await wait(600);
  await snap("statement", "جدولٌ واحد: كل عمليةٍ ورصيدها", "«عليه» ما على العميل لك — و«له» ما لَه عندك", null,
    { focus: { x: 196, y: 250, s: 1.5 } });
  await snap("statement_tap", "اضغط أي عمليةٍ لمعاينتها", "", page.locator(".st-table tr.tap", { hasText: "S-00001" }), { after: 900 });
  await page.waitForSelector(".sheet .preview iframe");
  await wait(700);
  await snap("doc_sheet", "الفاتورة كما تُرسَل — ومنها «تعديل»", "ومشاركتها صورةً أو طباعتها", null);
  await page.goBack();
  await wait(500);
  await snap("statement_share", "أرسل الكشف صورةً للعميل", "بلمسةٍ واحدة — في واتساب أو غيره", page.locator("#bar .icon-btn[aria-label='مشاركة صورة']"), { noClick: true });

  // ══ 8. ممتلكاتك ══
  chap("ممتلكاتك", "كل ما معك في شاشة");
  await page.locator("#tabs button[data-tab=holdings]").click();
  await wait(600);
  await snap("holdings", "صناديق الذهب بعيارها، والنقد", "وذهب المصانع عندك، وذهبك عند العملاء، والأطقم التي معك", page.locator(".wide-tile.fac"), { after: 600 });
  await page.waitForSelector(".sheet");
  await snap("factories", "كل مصنع: كم أخذت، وكم سدّدت", "وكم عليك له الآن — واللمس يفتح كشفه", null,
    { focus: { x: 196, y: 690, s: 1.4 } });
  await page.goBack();
  await wait(400);

  // ══ 9. اطمئن ══
  chap("اطمئن", "حفظٌ وتحديثٌ تلقائي");
  await page.locator("#tabs button[data-tab=more]").click();
  await wait(500);
  await snap("more", "نسختك محفوظةٌ تلقائياً في مجلدك", "والتحديثات تصلك بإشعار — اضغط «تثبيت» فقط", null);

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify({ viewport: { w: 393, h: 851, dpr: 2 }, shots }, null, 1));
  console.log(`✔ ${shots.filter((s) => s.type === "shot").length} لقطة في ${OUT}`);
  await browser.close();
  srv.close();
})().catch((e) => { console.error(e); process.exit(1); });
