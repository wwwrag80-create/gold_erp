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
  // الفصل: عنوانه ووصفه، وما يقوله الصوت عند بطاقته (مشكولاً)
  const chap = (title, desc, say) => {
    chapter = shots.filter((s) => s.type === "chapter").length + 1;
    shots.push({ type: "chapter", n: chapter, title, desc, say });
  };
  // لقطة الشاشة كما هي مع ما يُشرح فيها: `target` يُبرَز (خانةٌ أو زرّ)، ثم يُلمس
  // إن كان زرّاً (`press`). `say` نصّ الصوت مشكولاً، ويُكتب تحته بلا تشكيل.
  async function snap(id, title, say, target, opts) {
    const o = opts || {};
    await page.evaluate(() => { const t = document.getElementById("toast"); if (t) t.style.display = "none"; });
    if (o.blur !== false) await page.evaluate(() => document.activeElement && document.activeElement.blur && document.activeElement.blur());
    let box = null;
    if (target) {
      await target.scrollIntoViewIfNeeded();
      await wait(250);
      box = await target.boundingBox();
    }
    await wait(o.settle || 350);
    const file = `${String(shots.length + 1).padStart(2, "0")}_${id}.png`;
    await page.screenshot({ path: path.join(OUT, file) });
    // تقريب الكاميرا: إلى ما يُشرح تلقائياً، أو إلى `focus` (بنقاط الشاشة)، أو لا تقريب
    shots.push({ type: "shot", id, file, title, say, tap: box, press: !!(target && o.press), chapter,
      focus: o.zoom === false ? null : o.focus || (box ? { x: box.x + box.width / 2, y: box.y + box.height / 2, s: o.s || 1.4 } : null) });
    if (target && o.press) { await target.click(); await wait(o.after || 500); }
    console.log("  ✔", file);
  }
  const press = { press: true };
  const field = (label) => page.locator("label.f", { hasText: label }).first().locator("input,select").first();
  const sheetItem = (t) => page.locator(".sheet .list-item", { hasText: t }).first();
  const footerBtn = (t) => page.locator(".footer-bar .btn", { hasText: t }).first();
  const sheetBtn = (t) => page.locator(".sheet .btn", { hasText: t }).first();
  const tile = (t) => page.locator(".op-tile", { hasText: t }).first();
  const tab = (t) => page.locator(`#tabs button[data-tab=${t}]`);
  const btn = (t) => page.locator("button", { hasText: t }).first();
  const homeNow = async () => { await page.goto(url + "#/home"); await wait(500); };
  const setPhotos = async (list, n) => {
    await page.locator('input[type=file][accept="image/*"]').setInputFiles(list.map((k) => ({ name: k + ".png", mimeType: "image/png", buffer: photos[k] })));
    await page.waitForFunction((m) => [...document.querySelectorAll(".photo-pick img.thumb")].filter((x) => (x.src || "").startsWith("data:")).length === m, n);
  };

  await page.goto(url);
  await page.waitForSelector("#tabs");
  const meta = {
    intro: "أَهْلًا بِكَ فِي نِظَامٍ مُحَاسَبِيٍّ لِلذَّهَبِ. فِي هَذَا الْفِيدْيُو نَشْرَحُ لَكَ خُطْوَةً بِخُطْوَةٍ: كَيْفَ تَبْدَأُ، وَكَيْفَ تُسَجِّلُ الْبِضَاعَةَ، وَتَبِيعُ لِعُمَلَائِكَ، وَتُحَصِّلُ مِنْهُمْ، وَتُسَدِّدُ لِلْمَصْنَعِ.",
    outro: "أَنْتَ الْآنَ جَاهِزٌ. أَضِفِ الْمَصْنَعَ وَعُمَلَاءَكَ، وَسَجِّلِ الْبِضَاعَةَ، وَبِعْ بِثِقَةٍ. بِالتَّوْفِيقِ.",
  };

  // ══ 1. البداية ══
  chap("البداية", "أول تشغيلٍ وإعدادٌ بسيط", "الدَّرْسُ الْأَوَّلُ: الْبِدَايَةُ.");
  await page.goto(url + "#/welcome");
  await wait(500);
  await snap("welcome", "اضغط «ابدأ» واختر مجلداً",
    "عِنْدَ فَتْحِ التَّطْبِيقِ أَوَّلَ مَرَّةٍ، انْقُرْ عَلَى زِرِّ «اِبْدَأْ»، ثُمَّ اخْتَرْ مُجَلَّدًا فِي جَوَّالِكَ، مِثْلَ مُجَلَّدِ الْمُسْتَنَدَاتِ، ثُمَّ انْقُرْ عَلَى «اِسْتِخْدَامِ هَذَا الْمُجَلَّدِ». بَعْدَهَا يُحْفَظُ كُلُّ شَيْءٍ تِلْقَائِيًّا.",
    btn("ابدأ — اختر مجلد الحفظ التلقائي"));
  await snap("welcome_restore", "حذفت التطبيق؟ استرجع بياناتك",
    "وَإِذَا حَذَفْتَ التَّطْبِيقَ ثُمَّ ثَبَّتَّهُ مِنْ جَدِيدٍ، انْقُرْ عَلَى «عِنْدِي بَيَانَاتٌ سَابِقَةٌ»، وَاخْتَرِ الْمُجَلَّدَ نَفْسَهُ، فَيَعُودُ كُلُّ شَيْءٍ كَمَا كَانَ.",
    btn("عندي بيانات سابقة"));
  await homeNow();
  await snap("home", "الشاشة الرئيسية: ست لوحات",
    "هَذِهِ هِيَ الشَّاشَةُ الرَّئِيسِيَّةُ. فِيهَا سِتُّ لَوْحَاتٍ: بَيْعٌ لِلْعَمِيلِ، وَمُرْتَجَعٌ لِلْعَمِيلِ، وَبِضَاعَةٌ مِنْ مَصْنَعٍ، وَإِرْجَاعٌ لِلْمَصْنَعِ، وَتَحْصِيلٌ مِنَ الْعَمِيلِ، وَسَدَادٌ لِلْمَصْنَعِ.",
    page.locator(".op-grid"), { s: 1.15 });
  await snap("home_more", "اضغط «المزيد»",
    "أَوَّلًا، اُكْتُبِ اسْمَكَ أَوِ اسْمَ مُؤَسَّسَتِكَ. لِذَلِكَ انْقُرْ عَلَى «الْمَزِيدِ» فِي أَسْفَلِ الشَّاشَةِ.", tab("more"), press);
  await snap("more_settings", "ثم «الإعدادات والحفظ»", "ثُمَّ انْقُرْ عَلَى «الْإِعْدَادَاتِ وَالْحِفْظِ»، فِي آخِرِ الْقَائِمَةِ.",
    page.locator(".list-item", { hasText: "الإعدادات والحفظ" }), press);
  await fill("الاسم", "مؤسسة الذهب");
  await fill("الجوال", "0551234567");
  await snap("settings_name", "اكتب اسمك وجوالك",
    "اُكْتُبِ اسْمَكَ أَوِ اسْمَ مُؤَسَّسَتِكَ فِي خَانَةِ «الِاسْمِ»، وَرَقْمَ جَوَّالِكَ فِي خَانَةِ «الْجَوَّالِ». تَظْهَرُ هَذِهِ الْبَيَانَاتُ فِي رَأْسِ كُلِّ فَاتُورَةٍ.",
    field("الاسم"));
  await snap("settings_save", "اضغط «حفظ الإعدادات»", "ثُمَّ انْقُرْ عَلَى زِرِّ «حِفْظِ الْإِعْدَادَاتِ».", btn("حفظ الإعدادات"), press);

  // ══ 2. العملاء والمصانع ══
  chap("العملاء والمصانع", "أضفهم مرةً واحدة", "الدَّرْسُ الثَّانِي: الْعُمَلَاءُ وَالْمَصَانِعُ.");
  await homeNow();
  await snap("tab_accounts", "اضغط «الحسابات»", "لِإِضَافَةِ عَمِيلٍ جَدِيدٍ، انْقُرْ عَلَى «الْحِسَابَاتِ» فِي أَسْفَلِ الشَّاشَةِ.", tab("customers"), press);
  await snap("add_shop", "اضغط «+ محل»", "ثُمَّ انْقُرْ عَلَى زِرِّ «زَائِدْ مَحَلّ» فِي الْأَعْلَى.",
    page.locator("#bar .icon-btn[aria-label='محل جديد']"), press);
  await fill("اسم المحل", "محل الأمانة للمجوهرات");
  await fill("الجوال", "0501112233");
  await snap("shop_name", "اسم المحل وجواله",
    "اُكْتُبِ اسْمَ الْمَحَلِّ فِي خَانَةِ «اسْمِ الْمَحَلِّ»، وَرَقْمَ جَوَّالِهِ فِي خَانَةِ «الْجَوَّالِ».", field("اسم المحل"));
  await fill("الأجرة المتفق عليها", "25");
  await snap("shop_wage", "الأجرة المتفق عليها",
    "وَإِذَا كَانَ بَيْنَكَ وَبَيْنَهُ أُجْرَةٌ مُتَّفَقٌ عَلَيْهَا لِكُلِّ جِرَامٍ، اُكْتُبْهَا هُنَا. عِنْدَهَا يَحْسُبُ التَّطْبِيقُ الْأُجُورَ تِلْقَائِيًّا عِنْدَ الْبَيْعِ لَهُ.",
    field("الأجرة المتفق عليها"));
  await snap("shop_opening", "رصيدٌ سابق؟ (اختياري)",
    "وَإِذَا كَانَ عَلَيْهِ ذَهَبٌ أَوْ نَقْدٌ مِنْ قَبْلُ، اُكْتُبْهُ فِي «الرَّصِيدِ الِافْتِتَاحِيِّ». وَهَذَا اخْتِيَارِيٌّ.",
    page.locator(".card", { hasText: "رصيد افتتاحي" }).first(), { s: 1.25 });
  await snap("shop_save", "اضغط «حفظ»", "ثُمَّ انْقُرْ عَلَى زِرِّ «حِفْظ» فِي أَسْفَلِ الشَّاشَةِ.", footerBtn("حفظ"), { press: true, after: 700 });
  await page.goto(url + "#/shop-form");
  await wait(400);
  await fill("اسم المحل", "مجوهرات النخبة");
  await footerBtn("حفظ").click();
  await wait(500);
  await page.goto(url + "#/customers");
  await wait(500);
  await snap("seg_factories", "ثم «المصانع» ← «+ مصنع»",
    "وَبِالطَّرِيقَةِ نَفْسِهَا أَضِفِ الْمَصْنَعَ الَّذِي تَأْخُذُ مِنْهُ الْبِضَاعَةَ؛ انْقُرْ عَلَى «الْمَصَانِعِ»، ثُمَّ عَلَى «زَائِدْ مَصْنَع».",
    page.locator(".seg button", { hasText: "المصانع" }), press);
  await page.locator("#bar .icon-btn[aria-label='مصنع جديد']").click();
  await wait(500);
  await fill("اسم المصنع", "مصنع الريان للذهب");
  await fill("الجوال", "0509998877");
  await fill("أجرة المصنع", "20");
  await snap("factory_wage", "اسم المصنع وأجرته",
    "اُكْتُبِ اسْمَ الْمَصْنَعِ وَجَوَّالَهُ، وَأُجْرَةَ الْمَصْنَعِ الْمُتَّفَقَ عَلَيْهَا لِكُلِّ جِرَامٍ. وَإِنْ كَانَ عَلَيْكَ لَهُ دَيْنٌ سَابِقٌ، اُكْتُبْهُ فِي «الدَّيْنِ السَّابِقِ».",
    field("أجرة المصنع"));
  await snap("factory_save", "اضغط «حفظ»", "ثُمَّ انْقُرْ عَلَى زِرِّ «حِفْظ» فِي أَسْفَلِ الشَّاشَةِ.", footerBtn("حفظ"), { press: true, after: 700 });

  // ══ 3. بضاعة من المصنع ══
  chap("بضاعة من المصنع", "سجّل ما استلمته", "الدَّرْسُ الثَّالِثُ: الْبِضَاعَةُ مِنَ الْمَصْنَعِ.");
  await homeNow();
  await snap("home_purchase", "اضغط «بضاعة من مصنع»",
    "عِنْدَمَا تَسْتَلِمُ بِضَاعَةً مِنَ الْمَصْنَعِ، انْقُرْ عَلَى «بِضَاعَةٌ مِنْ مَصْنَعٍ» فِي الشَّاشَةِ الرَّئِيسِيَّةِ.", tile("بضاعة من مصنع"), { press: true, after: 700 });
  await page.waitForSelector(".sheet");
  await snap("pick_factory", "اختر المصنع",
    "اِخْتَرِ الْمَصْنَعَ مِنَ الْقَائِمَةِ. يَظْهَرُ اسْمُهُ وَتَارِيخُ الْيَوْمِ فِي أَعْلَى الْفَاتُورَةِ، وَتَسْتَطِيعُ تَغْيِيرَهُمَا بِلَمْسَةٍ.",
    sheetItem("مصنع الريان"), press);
  await fill("الطقم", "ط-101");
  await field("الطقم").press("Enter");
  await snap("p_set", "خانة «الطقم»",
    "فِي خَانَةِ «الطَّقْمِ» اُكْتُبِ اسْمَ الطَّقْمِ أَوْ رَقْمَهُ. وَهَذِهِ الْخَانَةُ اخْتِيَارِيَّةٌ.", field("الطقم"));
  await snap("p_karat", "خانة «العيار»",
    "وَمِنْ خَانَةِ «الْعِيَارِ» اِخْتَرْ عِيَارَ الطَّقْمِ، مِثْلَ ثَمَانِيَةَ عَشَرَ، أَوْ وَاحِدٍ وَعِشْرِينَ.", field("العيار"));
  await fill("الوزن (جم)", "24.5");
  await snap("p_weight", "خانة «الوزن»", "وَفِي خَانَةِ «الْوَزْنِ» اُكْتُبْ وَزْنَ الطَّقْمِ بِالْجِرَامِ.", field("الوزن (جم)"));
  await fill("الأجور", "490");
  await snap("p_wages", "خانة «الأجور»",
    "وَفِي خَانَةِ «الْأُجُورِ» اُكْتُبْ أُجُورَ الطَّقْمِ بِالرِّيَالِ. وَإِذَا كَانَتْ لِلْمَصْنَعِ أُجْرَةٌ مُتَّفَقٌ عَلَيْهَا، تَظْهَرُ الْأُجُورُ تِلْقَائِيًّا.",
    field("الأجور"));
  await snap("p_diamond", "خانة «الماس» (اختيارية)",
    "وَإِذَا كَانَ فِي الطَّقْمِ أَلْمَاسٌ، اُكْتُبْ وَزْنَهُ فِي خَانَةِ «الْأَلْمَاسِ». وَإِلَّا فَاتْرُكْهَا فَارِغَةً.", field("الماس"));
  await snap("p_photo_btn", "صور الطقم",
    "وَلِإِضَافَةِ صُورَةِ الطَّقْمِ، انْقُرْ عَلَى «صُورَة»، وَاخْتَرْ مِنَ الْكَامِيرَا أَوْ مِنْ مَعْرِضِ الصُّوَرِ. وَتَسْتَطِيعُ إِضَافَةَ أَكْثَرَ مِنْ صُورَةٍ.",
    page.locator(".photo-add button"));
  await setPhotos(["necklace", "earrings"], 2);
  await snap("p_photos", "الصور في الخانة نفسها",
    "تَظْهَرُ الصُّوَرُ هُنَا. وَلِحَذْفِ صُورَةٍ، انْقُرْ عَلَى عَلَامَةِ الْإِغْلَاقِ فَوْقَهَا.", page.locator(".photo-pick"), { s: 1.5 });
  await snap("p_add", "طقمٌ آخر؟ اضغط «+ إضافة»",
    "إِذَا كَانَ مَعَكَ طَقْمٌ آخَرُ فِي الْفَاتُورَةِ نَفْسِهَا، انْقُرْ عَلَى «زَائِدْ إِضَافَة»، ثُمَّ اُكْتُبِ الطَّقْمَ التَّالِيَ بِالطَّرِيقَةِ نَفْسِهَا.",
    btn("+ إضافة"), press);
  await fill("الطقم", "ط-102");
  await field("الطقم").press("Enter");
  await fill("الوزن (جم)", "18.75");
  await fill("الأجور", "375");
  await setPhotos(["ring"], 1);
  await snap("p_lines", "الطقم الأول في «البنود»",
    "يَظْهَرُ الطَّقْمُ الْأَوَّلُ فِي «الْبُنُودِ» أَسْفَلَ الشَّاشَةِ، وَتَحْتَهُ الْإِجْمَالِيُّ.", page.locator(".line").first());
  await snap("p_save", "آخر طقم؟ «حفظ الفاتورة» مباشرة",
    "وَبَعْدَ آخِرِ طَقْمٍ، انْقُرْ عَلَى «حِفْظِ الْفَاتُورَةِ» مُبَاشَرَةً، وَلَا تَحْتَاجُ إِلَى «زَائِدْ إِضَافَة».",
    footerBtn("حفظ الفاتورة"), { press: true, after: 700 });
  await page.waitForSelector(".sheet .btn");
  await snap("p_confirm", "راجع ثم احفظ",
    "تَظْهَرُ لَكَ مُرَاجَعَةٌ: عَدَدُ الْأَطْقُمِ، وَالْوَزْنُ، وَالْأُجُورُ. ثُمَّ انْقُرْ عَلَى «حِفْظِ الْفَاتُورَةِ» لِلتَّأْكِيدِ.",
    sheetBtn("حفظ الفاتورة"), { press: true, after: 800 });
  await page.waitForURL(/#\/doc\/inv\//);
  await page.waitForFunction(() => (document.querySelector(".preview iframe") || {}).srcdoc && document.querySelector(".preview iframe").srcdoc.includes("data:image"));
  await wait(700);
  await snap("p_doc", "حُفظت الفاتورة",
    "تَمَّ حِفْظُ الْفَاتُورَةِ. وَمِنْ هُنَا تَسْتَطِيعُ مُشَارَكَتَهَا صُورَةً، أَوْ طِبَاعَتَهَا، أَوْ تَعْدِيلَهَا.", page.locator(".quick").first(), { s: 1.25 });

  // ══ 4. الأطقم التي معي ══
  chap("الأطقم التي معي", "كل طقمٍ ووزنه وصوره", "الدَّرْسُ الرَّابِعُ: الْأَطْقُمُ الَّتِي مَعَكَ.");
  await snap("tab_holdings", "اضغط «الممتلكات»",
    "لِتَرَى الْأَطْقُمَ الَّتِي مَعَكَ، انْقُرْ عَلَى «الْمُمْتَلَكَاتِ» فِي أَسْفَلِ الشَّاشَةِ.", tab("holdings"), { press: true, after: 700 });
  await snap("sets_tile", "«الأطقم التي معي»",
    "فِي لَوْحَةِ «الْأَطْقُمِ الَّتِي مَعِي» تَرَى عَدَدَ الْأَطْقُمِ، وَوَزْنَهَا الْإِجْمَالِيَّ، ثُمَّ انْقُرْ عَلَيْهَا.", page.locator(".wide-tile.sets"), { press: true, after: 700 });
  await page.waitForSelector(".sheet .pc-row");
  await snap("pieces", "«معاينة» لصور الطقم",
    "تَظْهَرُ كُلُّ الْأَطْقُمِ: اسْمُ الطَّقْمِ، وَوَزْنُهُ، وَمِنْ أَيْنَ جَاءَ. وَلِرُؤْيَةِ صُوَرِهِ، انْقُرْ عَلَى زِرِّ «مُعَايَنَهْ».",
    page.locator(".sheet .pc-row", { hasText: "ط-101" }).locator(".prev-btn"), { press: true, after: 800 });
  await page.waitForFunction(() => [...document.querySelectorAll(".sheet .photo-fig img")].filter((x) => (x.src || "").startsWith("data:")).length >= 2);
  await snap("set_photos", "كل صورةٍ وحدها كاملة",
    "تَظْهَرُ كُلُّ صُورَةٍ وَحْدَهَا كَامِلَةً. وَلِتَكْبِيرِ الصُّورَةِ، انْقُرْ عَلَيْهَا.", null, { settle: 600 });
  await page.goBack(); await wait(300); await page.goBack(); await wait(400);

  // ══ 5. البيع للعميل ══
  chap("البيع للعميل", "من الأطقم التي معك، أو بالوزن مباشرة", "الدَّرْسُ الْخَامِسُ: الْبَيْعُ لِلْعَمِيلِ.");
  await homeNow();
  await snap("home_sale", "اضغط «بيع للعميل»",
    "لِلْبَيْعِ لِعَمِيلٍ، انْقُرْ عَلَى «بَيْعٌ لِلْعَمِيلِ» فِي الشَّاشَةِ الرَّئِيسِيَّةِ.", tile("بيع للعميل"), { press: true, after: 700 });
  await page.waitForSelector(".sheet");
  await snap("pick_shop", "اختر العميل",
    "اِخْتَرِ الْعَمِيلَ مِنَ الْقَائِمَةِ. وَإِذَا كَانَ عَمِيلًا جَدِيدًا، انْقُرْ عَلَى «زَائِدْ عَمِيلٌ جَدِيدٌ».", sheetItem("محل الأمانة"), press);
  await snap("sale_header", "فاتورة البيع: طريقتان",
    "هَذِهِ فَاتُورَةُ الْبَيْعِ. فِي الْأَعْلَى اسْمُ الْعَمِيلِ وَالتَّارِيخُ. وَلِلْبَيْعِ طَرِيقَتَانِ.", page.locator("#bar .bar-chips"), { s: 1.3 });
  await snap("sale_pick_btn", "١) من الأطقم التي معك",
    "الطَّرِيقَةُ الْأُولَى: إِذَا كُنْتَ تَبِيعُ طَقْمًا مِنَ الْأَطْقُمِ الَّتِي مَعَكَ، انْقُرْ عَلَى «اِخْتَرْ مِنَ الْأَطْقُمِ الَّتِي مَعِي».",
    btn("اختر من الطقوم التي معي"), press);
  await page.waitForSelector(".sheet .list-item");
  await snap("picker_preview", "«معاينة» قبل الاختيار",
    "تَظْهَرُ الْأَطْقُمُ الَّتِي مَعَكَ بِأَوْزَانِهَا. وَلِرُؤْيَةِ صُوَرِ الطَّقْمِ قَبْلَ اخْتِيَارِهِ، انْقُرْ عَلَى زِرِّ «مُعَايَنَهْ».",
    sheetItem("ط-101").locator(".prev-btn"));
  await snap("picker_pick", "اضغط الطقم لاختياره", "ثُمَّ انْقُرْ عَلَى الطَّقْمِ نَفْسِهِ لِاخْتِيَارِهِ.",
    sheetItem("ط-101").locator(".grow"), { press: true, after: 700 });
  await snap("sale_filled", "يُعبّأ الطقم ووزنه وصوره",
    "يُعَبِّئُ التَّطْبِيقُ اسْمَ الطَّقْمِ، وَوَزْنَهُ، وَعِيَارَهُ، وَصُوَرَهُ تِلْقَائِيًّا.", field("الوزن (جم)"));
  await snap("sale_wages_auto", "الأجور المتفق عليها تلقائياً",
    "وَفِي خَانَةِ «الْأُجُورِ» تَظْهَرُ أُجْرَةُ الْعَمِيلِ الْمُتَّفَقُ عَلَيْهَا تِلْقَائِيًّا. اُتْرُكْهَا كَمَا هِيَ، أَوِ اكْتُبْ مَبْلَغًا آخَرَ.",
    field("الأجور"));
  await snap("sale_add", "سطرٌ آخر؟ «+ إضافة»",
    "وَلِإِضَافَةِ سَطْرٍ آخَرَ فِي الْفَاتُورَةِ نَفْسِهَا، انْقُرْ عَلَى «زَائِدْ إِضَافَة».", btn("+ إضافة"), press);
  await snap("direct_set", "٢) بالوزن مباشرة: «الطقم» فارغ",
    "الطَّرِيقَةُ الثَّانِيَةُ: الْبَيْعُ بِالْوَزْنِ مُبَاشَرَةً. اُتْرُكْ خَانَةَ «الطَّقْمِ» فَارِغَةً.", field("الطقم"));
  await fill("الوزن (جم)", "10");
  await snap("direct_weight", "اكتب الوزن", "وَاكْتُبِ الْوَزْنَ بِالْجِرَامِ فِي خَانَةِ «الْوَزْنِ».", field("الوزن (جم)"));
  await fill("الأجور", "250");
  await snap("direct_wages", "واكتب الأجور", "وَاكْتُبِ الْأُجُورَ بِالرِّيَالِ فِي خَانَةِ «الْأُجُورِ».", field("الأجور"));
  await snap("sale_save", "اضغط «حفظ الفاتورة»",
    "ثُمَّ انْقُرْ عَلَى «حِفْظِ الْفَاتُورَةِ». يُحْفَظُ السَّطْرُ الْأَخِيرُ مَعَهَا تِلْقَائِيًّا.", footerBtn("حفظ الفاتورة"), { press: true, after: 700 });
  await page.waitForSelector(".sheet .btn");
  await snap("sale_confirm", "راجع ثم احفظ", "رَاجِعِ الْإِجْمَالِيَّ، ثُمَّ انْقُرْ عَلَى «حِفْظِ الْفَاتُورَةِ» لِلتَّأْكِيدِ.",
    sheetBtn("حفظ الفاتورة"), { press: true, after: 800 });
  await page.waitForURL(/#\/doc\/inv\//);
  await wait(900);
  await snap("sale_share", "أرسل الفاتورة للعميل",
    "فَاتُورَةُ الْبَيْعِ جَاهِزَةٌ. وَلِإِرْسَالِهَا لِلْعَمِيلِ، انْقُرْ عَلَى «مُشَارَكَةِ صُورَةٍ»، وَاخْتَرْ وَاتْسَابْ.",
    page.locator(".quick button", { hasText: "مشاركة صورة" }));

  // ══ 6. المرتجع ══
  chap("المرتجع من العميل", "باسم الطقم، أو بالوزن", "الدَّرْسُ السَّادِسُ: الْمُرْتَجَعُ مِنَ الْعَمِيلِ.");
  await homeNow();
  await snap("home_return", "اضغط «مرتجع للعميل»",
    "إِذَا أَرْجَعَ الْعَمِيلُ بِضَاعَةً، انْقُرْ عَلَى «مُرْتَجَعٌ لِلْعَمِيلِ»، ثُمَّ اخْتَرِ الْعَمِيلَ.", tile("مرتجع للعميل"), { press: true, after: 700 });
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await wait(500);
  await fill("الطقم", "ط-101");
  await field("الطقم").press("Enter");
  await wait(300);
  await snap("ret_named", "١) باسم الطقم",
    "إِذَا أَرْجَعَ طَقْمًا بِعَيْنِهِ، اُكْتُبِ اسْمَهُ فِي خَانَةِ «الطَّقْمِ»، فَيُعَبِّئُ التَّطْبِيقُ وَزْنَهُ وَأُجُورَهُ مِنْ فَاتُورَةِ الْبَيْعِ.",
    field("الطقم"), { s: 1.3 });
  // المرتجع بالوزن: فاتورةٌ جديدة (المسودة السابقة لا تُحفظ)
  await page.evaluate(() => { try { localStorage.removeItem("draft_inv_sale_return"); } catch (e) { /* */ } });
  await homeNow();
  await page.goto(url + "#/invoice/new?kind=sale_return");
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await wait(500);
  await fill("الوزن (جم)", "5");
  await snap("ret_weight", "٢) بالوزن مباشرة",
    "وَإِذَا كَانَ الْمُرْتَجَعُ بِالْوَزْنِ فَقَطْ، اُتْرُكْ خَانَةَ «الطَّقْمِ» فَارِغَةً، وَاكْتُبِ الْوَزْنَ فِي خَانَةِ «الْوَزْنِ».", field("الوزن (جم)"));
  await fill("الأجور", "125");
  await snap("ret_wages", "واكتب الأجور", "وَاكْتُبْ أُجُورَهُ فِي خَانَةِ «الْأُجُورِ».", field("الأجور"));
  await snap("ret_save", "اضغط «حفظ الفاتورة»",
    "ثُمَّ انْقُرْ عَلَى «حِفْظِ الْفَاتُورَةِ»، وَأَكِّدِ الْحِفْظَ. يَنْقُصُ الْمُرْتَجَعُ مِنْ رَصِيدِ الْعَمِيلِ.", footerBtn("حفظ الفاتورة"), { press: true, after: 700 });
  await page.waitForSelector(".sheet .btn");
  await sheetBtn("حفظ الفاتورة").click();
  await page.waitForURL(/#\/doc\/inv\//);
  await wait(500);

  // ══ 7. التحصيل من العميل ══
  chap("التحصيل من العميل", "ذهبٌ بعياره، أو نقد", "الدَّرْسُ السَّابِعُ: التَّحْصِيلُ مِنَ الْعَمِيلِ.");
  await homeNow();
  await snap("home_receipt", "اضغط «تحصيل من العميل»",
    "عِنْدَمَا تَسْتَلِمُ مِنْ عَمِيلٍ ذَهَبًا أَوْ نَقْدًا، انْقُرْ عَلَى «تَحْصِيلٌ مِنَ الْعَمِيلِ»، ثُمَّ اخْتَرِ الْعَمِيلَ.",
    tile("تحصيل من العميل"), { press: true, after: 700 });
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await wait(500);
  await fill("الوزن (جم)", "10");
  await snap("rv_weight", "الذهب: اكتب وزنه",
    "إِذَا اسْتَلَمْتَ ذَهَبًا، اُكْتُبْ وَزْنَهُ بِالْجِرَامِ فِي خَانَةِ «الْوَزْنِ».", field("الوزن (جم)"));
  await field("العيار").selectOption("21");
  await wait(250);
  await snap("rv_karat", "واختر عياره",
    "وَاخْتَرْ عِيَارَهُ مِنْ خَانَةِ «الْعِيَارِ». يَحْسُبُ التَّطْبِيقُ مَا يُعَادِلُهُ بِعِيَارِ ثَمَانِيَةَ عَشَرَ.", field("العيار"));
  await snap("rv_cash_btn", "النقد: اضغط «+ نقد»", "وَإِذَا اسْتَلَمْتَ نَقْدًا، انْقُرْ عَلَى «زَائِدْ نَقْد».", btn("+ نقد"), press);
  await fill("المبلغ", "500");
  await snap("rv_amount", "اكتب المبلغ", "وَاكْتُبِ الْمَبْلَغَ بِالرِّيَالِ فِي خَانَةِ «الْمَبْلَغِ».", field("المبلغ"));
  await snap("rv_totals", "الرصيد قبل وبعد",
    "وَفِي الْأَسْفَلِ تَرَى رَصِيدَ الْعَمِيلِ قَبْلَ التَّحْصِيلِ وَبَعْدَهُ.", page.locator(".totals").first(), { s: 1.3 });
  await snap("rv_save", "اضغط «حفظ السند»",
    "ثُمَّ انْقُرْ عَلَى «حِفْظِ السَّنَدِ»، وَأَكِّدِ الْحِفْظَ. يَدْخُلُ الذَّهَبُ وَالنَّقْدُ إِلَى صَنَادِيقِكَ.", footerBtn("حفظ السند"), { press: true, after: 700 });
  await page.waitForSelector(".sheet .btn");
  await sheetBtn("حفظ السند").click();
  await page.waitForURL(/#\/doc\/vo\//);
  await wait(500);

  // ══ 8. السداد للمصنع ══
  chap("السداد للمصنع", "من صناديقك", "الدَّرْسُ الثَّامِنُ: السَّدَادُ لِلْمَصْنَعِ.");
  await homeNow();
  await snap("home_payment", "اضغط «سداد للمصنع»",
    "وَعِنْدَمَا تُسَدِّدُ لِلْمَصْنَعِ، انْقُرْ عَلَى «سَدَادٌ لِلْمَصْنَعِ»، ثُمَّ اخْتَرِ الْمَصْنَعَ.", tile("سداد للمصنع"), { press: true, after: 700 });
  await page.waitForSelector(".sheet");
  await sheetItem("مصنع الريان").click();
  await wait(500);
  await field("العيار").selectOption("21");
  await fill("الوزن (جم)", "8");
  await wait(300);
  await snap("pv_box", "كم معك في الصندوق",
    "اِخْتَرِ الْعِيَارَ وَاكْتُبِ الْوَزْنَ. يُخْبِرُكَ التَّطْبِيقُ كَمْ مَعَكَ فِي صُنْدُوقِ هَذَا الْعِيَارِ.",
    page.locator(".small", { hasText: "معك في صندوق" }).first(), { s: 1.5 });
  await btn("+ نقد").click();
  await fill("المبلغ", "300");
  await snap("pv_cash", "والنقد: «+ نقد» ثم المبلغ", "وَلِلنَّقْدِ انْقُرْ عَلَى «زَائِدْ نَقْد»، ثُمَّ اكْتُبِ الْمَبْلَغَ.", field("المبلغ"));
  await snap("pv_save", "اضغط «حفظ السند»",
    "ثُمَّ انْقُرْ عَلَى «حِفْظِ السَّنَدِ». يُخْصَمُ مَا سَدَّدْتَهُ مِنْ صَنَادِيقِكَ، وَيَنْقُصُ مِنْ دَيْنِ الْمَصْنَعِ.", footerBtn("حفظ السند"), { press: true, after: 700 });
  await page.waitForSelector(".sheet .btn");
  await sheetBtn("حفظ السند").click();
  await page.waitForURL(/#\/doc\/vo\//);
  await wait(500);

  // ══ 9. كشف الحساب ══
  chap("كشف الحساب", "بسيطٌ وواضح", "الدَّرْسُ التَّاسِعُ: كَشْفُ الْحِسَابِ.");
  await homeNow();
  await snap("home_statement", "اضغط «كشف حساب»",
    "لِكَشْفِ حِسَابِ عَمِيلٍ أَوْ مَصْنَعٍ، انْقُرْ عَلَى «كَشْفِ حِسَابٍ» فِي الشَّاشَةِ الرَّئِيسِيَّةِ، ثُمَّ اخْتَرِ الْحِسَابَ.",
    page.locator(".wide-tile", { hasText: "كشف حساب" }), { press: true, after: 600 });
  await page.waitForSelector(".sheet");
  await sheetItem("محل الأمانة").click();
  await page.waitForURL(/#\/statement\//);
  await wait(600);
  await snap("st_bal", "الرصيد: «عليه» و«له»",
    "فِي الْأَعْلَى الرَّصِيدُ. «عَلَيْهِ» يَعْنِي مَا عَلَى الْعَمِيلِ لَكَ، وَ«لَهُ» يَعْنِي مَا لَهُ عِنْدَكَ.", page.locator(".st-bal"), { s: 1.5 });
  await snap("st_table", "كل عمليةٍ ورصيدها بعدها",
    "وَفِي الْجَدْوَلِ كُلُّ عَمَلِيَّةٍ بِتَارِيخِهَا، وَالرَّصِيدُ بَعْدَهَا بِالذَّهَبِ وَالنَّقْدِ.", page.locator(".st-table"), { s: 1.45 });
  await snap("st_tap", "اضغط أي عملية لمعاينتها", "فِي الْجَدْوَلِ، انْقُرْ عَلَى أَيِّ عَمَلِيَّةٍ لِمُعَايَنَتِهَا.",
    page.locator(".st-table tr.tap", { hasText: "S-00001" }), { press: true, after: 900 });
  await page.waitForSelector(".sheet .preview iframe");
  await wait(700);
  await snap("st_doc", "المعاينة… ومنها «تعديل»",
    "تَظْهَرُ الْفَاتُورَةُ وَصُوَرُ أَطْقُمِهَا. وَإِذَا أَرَدْتَ تَصْحِيحَ شَيْءٍ، انْقُرْ عَلَى «تَعْدِيل».",
    page.locator(".sheet .doc-acts .btn", { hasText: "تعديل" }), { s: 1.3 });
  await page.goBack();
  await wait(500);
  await snap("st_period", "اختر الفترة",
    "وَلِاخْتِيَارِ فَتْرَةٍ مُعَيَّنَةٍ، مِثْلَ هَذَا الشَّهْرِ، انْقُرْ عَلَى زِرِّ الْفَتْرَةِ.", page.locator(".st-period"));
  await snap("st_share", "أرسل الكشف صورةً",
    "وَلِإِرْسَالِ الْكَشْفِ لِلْعَمِيلِ صُورَةً، انْقُرْ عَلَى زِرِّ الْمُشَارَكَةِ فِي الْأَعْلَى، وَاخْتَرْ وَاتْسَابْ.",
    page.locator("#bar .icon-btn[aria-label='مشاركة صورة']"));

  // ══ 10. ممتلكاتك ══
  chap("ممتلكاتك", "كل ما معك في شاشة", "الدَّرْسُ الْعَاشِرُ: مُمْتَلَكَاتُكَ.");
  await tab("holdings").click();
  await wait(700);
  await snap("h_boxes", "صناديق الذهب والنقد",
    "فِي «الْمُمْتَلَكَاتِ» تَرَى صَنَادِيقَ الذَّهَبِ بِعِيَارِهَا، وَالنَّقْدَ الَّذِي مَعَكَ.", page.locator(".boxes"), { s: 1.3 });
  await snap("h_fac", "«ذهب المصانع عندي»",
    "وَلَوْحَةُ «ذَهَبُ الْمَصَانِعِ عِنْدِي» تُبَيِّنُ كَمْ عَلَيْكَ لِلْمَصَانِعِ، وَإِذَا نَقَرْتَ عَلَيْهَا تَرَى كُلَّ مَصْنَعٍ.",
    page.locator(".wide-tile.fac"), { press: true, after: 700 });
  await page.waitForSelector(".sheet");
  await snap("h_factories", "لكل مصنع: أخذتُ · سدّدتُ · عليّ",
    "لِكُلِّ مَصْنَعٍ: كَمْ أَخَذْتَ مِنْهُ، وَكَمْ سَدَّدْتَ، وَكَمْ عَلَيْكَ لَهُ الْآنَ.", null, { focus: { x: 196, y: 690, s: 1.4 } });
  await page.goBack();
  await wait(500);
  await snap("h_cus", "«ذهبي عند العملاء»",
    "وَلَوْحَةُ «ذَهَبِي عِنْدَ الْعُمَلَاءِ» تُبَيِّنُ كَمْ لَكَ عِنْدَ عُمَلَائِكَ، وَلَمْسُهَا يَعْرِضُ كُلَّ عَمِيلٍ.", page.locator(".wide-tile.cus"));

  // ══ 11. اطمئن ══
  chap("اطمئن", "حفظٌ وتحديثٌ تلقائي", "الدَّرْسُ الْحَادِي عَشَرَ: اِطْمَئِنَّ.");
  await tab("more").click();
  await wait(600);
  await snap("more", "حفظٌ وتحديثٌ تلقائي",
    "نُسْخَتُكَ الِاحْتِيَاطِيَّةُ تُحْفَظُ تِلْقَائِيًّا فِي الْمُجَلَّدِ الَّذِي اخْتَرْتَهُ. وَالتَّحْدِيثَاتُ تَصِلُكَ بِإِشْعَارٍ، فَانْقُرْ عَلَى «تَثْبِيت» فَقَطْ، وَتَبْقَى بَيَانَاتُكَ كَمَا هِيَ.",
    null, { zoom: false });

  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify({ viewport: { w: 393, h: 851, dpr: 2 }, meta, shots }, null, 1));
  console.log(`✔ ${shots.filter((s) => s.type === "shot").length} لقطة في ${OUT}`);
  await browser.close();
  srv.close();
})().catch((e) => { console.error(e); process.exit(1); });
