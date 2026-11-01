// تجربة التطبيق على جهاز أندرويد (محاكٍ في GitHub Actions) — نسخة الاختبار.
// تتصل بصفحة التطبيق عبر بروتوكول أدوات المطوّر (adb forward 9222)، وتشغّل
// دورة العمل كما يشغّلها صاحبه، وتلتقط صور الشاشة، وتجرّب الجسر الأصلي
// (المشاركة صورةً · الطباعة · حفظ الملف).
//   node mobile/tests/device.mjs OUT_DIR      (Node 22: WebSocket مدمج)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "device-out";
fs.mkdirSync(OUT, { recursive: true });
const results = [];
let failed = 0;
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? "" : String(detail) });
  if (!ok) failed++;
  console.log(ok ? "  ✔" : "  ✘", name, ok ? "" : "— " + detail);
}
const adb = (...a) => execFileSync("adb", a, { maxBuffer: 64 * 1024 * 1024 });
let shotN = 10;
function shot(name) {
  try { fs.writeFileSync(path.join(OUT, `${++shotN}_${name}.png`), adb("exec-out", "screencap", "-p")); }
  catch (e) { console.log("screencap failed", e.message); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PKG = "com.jadeite.mobile";

// نوافذ النظام (اختيار المجلد، الإذن) تُلمس بنصّ أزرارها من شجرة الواجهة
function uiNodes() {
  adb("shell", "uiautomator", "dump", "/sdcard/ui.xml");
  const xml = adb("shell", "cat", "/sdcard/ui.xml").toString();
  const out = [];
  for (const m of xml.matchAll(/<node [^>]*?text="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/g)) {
    out.push({ text: m[1], x: Math.round((+m[2] + +m[4]) / 2), y: Math.round((+m[3] + +m[5]) / 2) });
  }
  return out;
}
async function tapText(re, tries = 12) {
  for (let i = 0; i < tries; i++) {
    try {
      const n = uiNodes().find((x) => re.test(x.text));
      if (n) { adb("shell", "input", "tap", String(n.x), String(n.y)); return true; }
    } catch (e) { /* الشاشة لم تجهز */ }
    await sleep(1000);
  }
  return false;
}
// يختار المجلد المفتوح (Documents) في نافذة النظام ويأذن للتطبيق به
async function chooseFolder(tag) {
  await sleep(2500);
  shot(tag + "_picker");
  const used = await tapText(/^use this folder$/i);
  await sleep(1500);
  const allowed = await tapText(/^allow$/i);
  return used && allowed;
}

async function connect() {
  for (let i = 0; i < 30; i++) {
    try {
      const list = await (await fetch("http://127.0.0.1:9222/json")).json();
      const t = list.find((x) => (x.url || "").includes("appassets"));
      if (t) {
        const ws = new WebSocket(t.webSocketDebuggerUrl);
        await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
        let id = 0;
        const pending = new Map();
        ws.onmessage = (m) => {
          const d = JSON.parse(m.data);
          if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
        };
        const send = (method, params) => new Promise((res) => {
          const n = ++id;
          pending.set(n, res);
          ws.send(JSON.stringify({ id: n, method, params }));
        });
        const ev = async (expr) => {
          const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
          if (r.result && r.result.exceptionDetails) {
            throw new Error((r.result.exceptionDetails.exception || {}).description || r.result.exceptionDetails.text);
          }
          return r.result && r.result.result ? r.result.result.value : undefined;
        };
        return { ws, ev };
      }
    } catch (e) { /* not yet */ }
    await sleep(1000);
  }
  throw new Error("لم يُعثر على صفحة التطبيق في أدوات المطوّر");
}

const HARNESS = `(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const lab = (t) => [...document.querySelectorAll("label.f")].find((l) => l.textContent.includes(t));
  window.__t = {
    sleep,
    fill(t, v) {
      const l = lab(t); if (!l) throw new Error("no field " + t);
      const el = l.querySelector("input,select,textarea");
      el.value = v;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    },
    val(t) { return lab(t).querySelector("input,select").value; },
    click(t) {
      const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes(t) && x.offsetParent !== null);
      if (!b) throw new Error("no button " + t);
      b.click();
    },
    async pick(name) {
      for (let i = 0; i < 20 && !document.querySelector(".sheet"); i++) await sleep(100);
      const it = [...document.querySelectorAll(".sheet .list-item")].find((x) => x.textContent.includes(name));
      if (!it) throw new Error("no shop " + name);
      it.click(); await sleep(250);
    },
    async confirm(t) {
      for (let i = 0; i < 20 && !document.querySelector(".sheet .btn"); i++) await sleep(100);
      [...document.querySelectorAll(".sheet .btn")].find((x) => x.textContent.includes(t)).click();
      await sleep(500);
    },
    text() { return document.body.innerText; },
  };
  // أحداث الأصل تُجمع هنا ليقرأها الاختبار
  window.__ev = {};
  for (const e of ["update", "updateProgress", "backupFolder", "restore", "backupDone", "testInstall", "testPatch", "publish"]) {
    Bridge.on(e, (d) => { (window.__ev[e] = window.__ev[e] || []).push(d); });
  }
  return true;
})()`;

// ينتظر حدثاً جديداً من الأصل (بعد عددٍ سابق) ويعيده
async function waitEv(ev, name, before, ms) {
  for (let i = 0; i < ms / 250; i++) {
    const list = await ev(`(window.__ev[${JSON.stringify(name)}] || [])`);
    if (list.length > before) return list[list.length - 1];
    await sleep(250);
  }
  return null;
}
const evCount = (ev, name) => ev(`(window.__ev[${JSON.stringify(name)}] || []).length`);

async function relaunch() {
  await sleep(500);
  adb("shell", "am", "start", "-W", "-n", `${PKG}/.MainActivity`);
  await sleep(5000);
  const pid = adb("shell", "pidof", PKG).toString().trim();
  adb("forward", "--remove-all");
  adb("forward", "tcp:9222", `localabstract:webview_devtools_remote_${pid}`);
  const c = await connect();
  for (let i = 0; i < 40; i++) { if (await c.ev("!!(window.App && App.state)")) break; await sleep(250); }
  await c.ev(HARNESS);
  return c;
}

const run = async (ev, body) => ev(`(async () => { const t = window.__t; ${body} })()`);

async function main() {
  let { ws, ev } = await connect();
  for (let i = 0; i < 40; i++) { if (await ev("!!(window.App && App.state)")) break; await sleep(250); }
  check("التطبيق يفتح وتُحمَّل بياناته", await ev("!!(window.App && App.state)"));
  check("الخط العربي محمَّل", await ev("document.fonts.check('16px Plex')"));
  await ev(HARNESS);
  await sleep(600);
  check("أول تشغيل: شاشة الترحيب (مجلد الحفظ أو الاسترجاع)", (await ev("location.hash")) === "#/welcome");
  shot("welcome");

  // ══ التحديث: الإصدار، وقراءة القناة من GitHub، وصلاحية PATCH ══
  const us = await ev("Bridge.updateState()");
  check("الإصدار المثبّت 1.2.0 (3)", us.version === "1.2.0" && us.code === 3 && !us.unsupported, JSON.stringify(us));
  check("إذن الإشعارات ممنوح", us.canNotify === true);
  let n0 = await evCount(ev, "update");
  await ev("Bridge.checkUpdate(), 1");
  const u1 = await waitEv(ev, "update", n0, 25000);
  check("قراءة قناة التحديث من GitHub", u1 && !u1.error && u1.lastCheck > 0 && u1.published, JSON.stringify(u1));
  check("ولا تحديث أحدث من المثبّت الآن", u1 && u1.available === false);
  n0 = await evCount(ev, "testPatch");
  await ev("AndroidBridge._testPatch(), 1");
  const tp = await waitEv(ev, "testPatch", n0, 25000);
  check("طلب النشر (PATCH) يصل GitHub — ويُرفض بلا مفتاح", tp && [401, 403, 404].includes(tp.code), JSON.stringify(tp));

  // ══ الترحيب: اختيار مجلد الحفظ التلقائي ══
  n0 = await evCount(ev, "backupFolder");
  await run(ev, `t.click("اختر مجلد الحفظ التلقائي");`);
  const picked = await chooseFolder("folder");
  const bf = await waitEv(ev, "backupFolder", n0, 15000);
  check("اختيار مجلد الحفظ التلقائي (Documents)", picked && bf && bf.ok && bf.name === "Documents", JSON.stringify(bf));
  await sleep(800);
  check("ثم الرئيسية", (await ev("location.hash")) === "#/home");
  shot("home");

  await run(ev, `location.hash = "#/settings"; await t.sleep(300); t.fill("الاسم", "مؤسسة الذهب"); t.click("حفظ الإعدادات"); await t.sleep(300);`);
  for (const [n, w] of [["محل الأمانة", "20"], ["محل النخبة", ""]]) {
    await run(ev, `location.hash = "#/shop-form"; await t.sleep(300); t.fill("اسم المحل", ${JSON.stringify(n)});
      ${w ? `t.fill("الأجرة المتفق عليها", "${w}");` : ""} t.click("حفظ"); await t.sleep(400);`);
  }
  await run(ev, `location.hash = "#/shop-form?type=factory"; await t.sleep(300); t.fill("اسم المصنع", "مصنع الريان");
    t.fill("أجرة المصنع", "8"); t.click("حفظ"); await t.sleep(400);`);
  check("أُضيف محلان ومصنع", (await ev("App.state.shops.length")) === 3 && (await ev("App.state.shops.filter((x) => x.type === 'factory').length")) === 1);

  // بضاعة من المصنع: T1 باسمه، وطقمٌ بوزنه فقط
  await run(ev, `location.hash = "#/invoice/new?kind=purchase"; await t.sleep(400); await t.pick("مصنع الريان");
    t.fill("الطقم", "T1"); await t.sleep(150); t.fill("الوزن (جم)", "12"); t.click("+ إضافة"); await t.sleep(250);
    t.fill("الوزن (جم)", "20"); t.click("+ إضافة"); await t.sleep(250);`);
  check("لا خانة موديل ولا فصوص", await run(ev, `const x = document.body.innerHTML; return !x.includes("رقم الموديل") && !x.includes("الفصوص");`));
  shot("purchase_editor");
  await run(ev, `t.click("ترحيل"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّلت البضاعة P-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("P-00001"));

  // بيعٌ للأمانة: T1 باسمه (يُعبّأ من البضاعة) + 5 جم بلا اسم
  await run(ev, `location.hash = "#/invoice/new?kind=sale"; await t.sleep(400); await t.pick("محل الأمانة");
    t.fill("الطقم", "T1"); await t.sleep(250);`);
  check("الطقم T1 معي ويُعبّأ وزنه 12", (await ev("__t.val('الوزن (جم)')")) === "12.00" && (await ev("__t.text().includes('الطقم T1 معك')")));
  await run(ev, `t.click("+ إضافة"); await t.sleep(250); t.fill("الوزن (جم)", "5"); t.click("+ إضافة"); await t.sleep(300);`);
  shot("invoice_editor");
  check("الإجماليات 17.00 جم و340.00", await run(ev, `const x = document.querySelector(".totals").innerText; return x.includes("17.00") && x.includes("340.00");`));
  await run(ev, `t.click("ترحيل"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّلت S-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("S-00001"));
  await sleep(1200);
  shot("invoice_doc");

  // مرتجع T1 من الأمانة — يُعبّأ من البيع
  await run(ev, `location.hash = "#/invoice/new?kind=sale_return"; await t.pick("محل الأمانة"); await t.sleep(200);
    t.fill("الطقم", "T1"); await t.sleep(250);`);
  check("المرتجع يُعبّأ من البيع (12.00 بأجر 20)", (await ev("__t.val('الوزن (جم)')")) === "12.00" && (await ev("__t.val('الأجر لكل جرام')")) === "20.00");
  await run(ev, `t.click("+ إضافة"); await t.sleep(200); t.click("ترحيل"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّل R-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("R-00001"));

  // بيع T1 للنخبة — من المرتجع
  await run(ev, `location.hash = "#/invoice/new?kind=sale"; await t.sleep(400); await t.pick("محل النخبة");
    t.fill("الطقم", "T1"); await t.sleep(250);`);
  check("بيع المرتجع يُعبّأ منه", (await ev("__t.val('الوزن (جم)')")) === "12.00" && (await ev("__t.text().includes('مرتجع R-00001')")));
  shot("resale_autofill");
  await run(ev, `t.click("+ إضافة"); await t.sleep(200); t.click("ترحيل"); await t.confirm("ترحيل"); await t.sleep(800);`);

  // تحصيل من الأمانة: 3 جم عيار 21 + 50 ريالاً
  await run(ev, `location.hash = "#/voucher/new?kind=receipt"; await t.sleep(400); await t.pick("محل الأمانة");
    t.fill("الوزن (جم)", "3"); t.fill("العيار", "21"); t.click("+ نقد"); await t.sleep(200); t.fill("المبلغ", "50");
    await t.sleep(200); t.click("ترحيل"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّل التحصيل RV-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("RV-00001"));

  // دفعٌ للمصنع من الصناديق: 2 جم عيار 21 + 30 ريالاً
  await run(ev, `location.hash = "#/voucher/new?kind=payment"; await t.sleep(400); await t.pick("مصنع الريان");
    t.fill("العيار", "21"); t.fill("الوزن (جم)", "2"); t.click("+ نقد"); await t.sleep(200); t.fill("المبلغ", "30");
    await t.sleep(200);`);
  check("يذكر ما في صندوق عيار 21 (3.00)", await ev("__t.text().includes('معك في صندوق عيار 21: 3.00 جم')"));
  await run(ev, `t.click("ترحيل"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّل الدفع PV-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("PV-00001"));

  const sid = await ev("App.state.shops.find((s) => s.name === 'محل الأمانة').id");
  await run(ev, `location.hash = "#/statement/${sid}"; await t.sleep(600);`);
  const kp = await ev("document.querySelector('.kpis').innerText");
  // ذهب 17 − 12 − 3.5 = 1.50 عليه · أجور 340 − 240 − 50 = 50.00 عليه
  check("كشف الحساب: 1.50 جم و50.00 ريال عليه", kp.includes("1.50 جم عليه") && kp.includes("50.00 ريال عليه"), kp);
  shot("statement");

  // الحفظ التلقائي في المجلد بعد كل عملية
  await sleep(2500);
  let saved = null;
  try { saved = JSON.parse(adb("shell", "cat", "/sdcard/Documents/gold-data.json").toString()); } catch (e) { /* */ }
  check("الحفظ التلقائي: gold-data.json في Documents بكل العمليات",
    saved && saved.format === "jadeite-mobile-backup" && saved.invoices.length === 4 && saved.vouchers.length === 2,
    saved ? `${saved.invoices.length}/${saved.vouchers.length}` : "no file");
  const ls = adb("shell", "ls", "/sdcard/Documents").toString();
  check("ونسخة اليوم معه", /gold-data-\d{4}-\d{2}-\d{2}\.json/.test(ls), ls);

  await run(ev, `location.hash = "#/holdings"; await t.sleep(700);`);
  const hd = await ev("(() => { const h = Domain.holdings(App.state); return { b21: (h.boxes.find((b) => b.karat === 21) || {}).weight, cash: h.cash.amount, n: h.pieces.length }; })()");
  // الطقم بلا اسم من البضاعة لم يُبع (السطر 5 جم كُتب بوزنه لا باختياره)
  check("الممتلكات: صندوق 21 فيه 1.00 جم، والنقد 20، وطقمٌ واحد معي", hd.b21 === 1 && hd.cash === 20 && hd.n === 1, JSON.stringify(hd));
  check("وصناديقها على الشاشة", (await ev("document.querySelectorAll('.box-tile').length")) === 3);
  shot("holdings");
  await run(ev, `location.hash = "#/customers?view=factories"; await t.sleep(600);`);
  shot("factories");

  // ══ الجسر الأصلي ══
  try { adb("shell", "run-as", "com.jadeite.mobile", "rm", "-rf", "cache/share"); } catch (e) { /* */ }
  await ev(`(() => { const inv = App.state.invoices.find((d) => d.no === "S-00001");
    AndroidBridge.shareHtmlImage(PrintDoc.invoiceHtml(App.state, inv), inv.no); return 1; })()`);
  await sleep(6000);
  shot("share_sheet");
  let png = null;
  try { png = adb("exec-out", "run-as", "com.jadeite.mobile", "cat", "cache/share/S-00001.png"); } catch (e) { /* */ }
  const isPng = png && png.length > 20000 && png.slice(1, 4).toString() === "PNG";
  check("المشاركة صورةً: صورة الفاتورة جاهزة", isPng, png ? png.length + " bytes" : "no file");
  if (isPng) fs.writeFileSync(path.join(OUT, "shared_invoice.png"), png);
  adb("shell", "input", "keyevent", "4");
  await sleep(1500);

  await ev(`(() => { const inv = App.state.invoices.find((d) => d.no === "S-00001");
    AndroidBridge.printHtml(PrintDoc.invoiceHtml(App.state, inv), inv.no); return 1; })()`);
  await sleep(7000);
  shot("print_preview");
  const top = adb("shell", "dumpsys", "activity", "activities").toString();
  check("الطباعة تفتح نافذة الطباعة (حفظ PDF)", /printspooler|PrintActivity/i.test(top));
  adb("shell", "input", "keyevent", "4");
  await sleep(2000);

  await ev(`(() => { AndroidBridge.saveFile("jadeite-backup-test.json", btoa("{}"), "application/json"); return 1; })()`);
  await sleep(4000);
  shot("save_backup");
  const top2 = adb("shell", "dumpsys", "activity", "activities").toString();
  check("حفظ النسخة يفتح نافذة اختيار المكان", /documentsui|DocumentsActivity/i.test(top2));
  adb("shell", "input", "keyevent", "4");
  await sleep(1500);

  // ══ تنزيل تحديث، والتحقّق من بصمته، والإشعار، ونافذة التثبيت ══
  const URL_ = process.env.UNSIGNED_URL, SHA = process.env.UNSIGNED_SHA;
  if (URL_ && SHA) {
    try { adb("shell", "appops", "set", PKG, "REQUEST_INSTALL_PACKAGES", "allow"); } catch (e) { /* */ }
    n0 = await evCount(ev, "testInstall");
    await ev(`AndroidBridge._testInstall(${JSON.stringify(URL_)}, ${JSON.stringify(SHA)}, "9.9.9"), 1`);
    const ti = await waitEv(ev, "testInstall", n0, 120000);
    check("تنزيل ملف التحديث من GitHub ومطابقة بصمته", ti && ti.ok, JSON.stringify(ti));
    await sleep(5000);
    shot("installer");
    const act = adb("shell", "dumpsys", "activity", "activities").toString();
    check("نافذة تثبيت أندرويد تُفتح", /packageinstaller/i.test(act));
    const nt = adb("shell", "dumpsys", "notification", "--noredact").toString();
    check("وإشعار «التحديث جاهز» يظهر", /pkg=com\.jadeite\.mobile[^\n]*id=7001/.test(nt));
    adb("shell", "input", "keyevent", "4");
    await sleep(1500);
    adb("shell", "input", "keyevent", "4");
    await sleep(1000);
  } else {
    check("تجربة التنزيل (يلزمها UNSIGNED_URL و UNSIGNED_SHA)", false, "missing env");
  }

  // البيانات تبقى بعد إغلاق التطبيق
  ws.close();
  adb("shell", "am", "force-stop", PKG);
  ({ ws, ev } = await relaunch());
  check("البيانات باقية بعد إغلاق التطبيق وفتحه", (await ev("App.state.invoices.length")) === 4 &&
    (await ev("App.state.vouchers.length")) === 2);
  await ev(`location.hash = "#/home"`);
  await sleep(800);
  shot("home_after");

  // ══ حذف التطبيق ثم تثبيته من جديد: يعود كل شيء من المجلد ══
  ws.close();
  adb("uninstall", PKG);
  await sleep(1500);
  adb("install", "-r", process.env.APK || "mobile/android/app/build/outputs/apk/debug/app-debug.apk");
  try { adb("shell", "pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS"); } catch (e) { /* */ }
  ({ ws, ev } = await relaunch());
  await sleep(600);
  check("بعد إعادة التثبيت: لا بيانات، وشاشة الترحيب", (await ev("App.state.invoices.length")) === 0 &&
    (await ev("location.hash")) === "#/welcome");
  n0 = await evCount(ev, "restore");
  await run(ev, `t.click("عندي بيانات سابقة");`);
  const picked2 = await chooseFolder("restore");
  const rs = await waitEv(ev, "restore", n0, 15000);
  check("المجلد نفسه يُقرأ: gold-data.json", picked2 && rs && rs.ok && rs.file === "gold-data.json",
    JSON.stringify(rs && { ok: rs.ok, file: rs.file, error: rs.error }));
  await sleep(800);
  shot("restore_confirm");
  await run(ev, `await t.confirm("استرجاع"); await t.sleep(800);`);
  check("استُرجع كل شيء: 4 فواتير وسندان ومحلان ومصنع", (await ev("App.state.invoices.length")) === 4 &&
    (await ev("App.state.vouchers.length")) === 2 && (await ev("App.state.shops.length")) === 3);
  check("والحفظ التلقائي مستمرٌّ في المجلد نفسه", (await ev("Bridge.backupFolder()")) === "Documents");
  await run(ev, `location.hash = "#/statement/" + App.state.shops.find((s) => s.name === "محل الأمانة").id; await t.sleep(600);`);
  const kp2 = await ev("document.querySelector('.kpis').innerText");
  check("وكشف الحساب كما كان: 1.50 جم و50.00 ريال عليه", kp2.includes("1.50 جم عليه") && kp2.includes("50.00 ريال عليه"), kp2);
  shot("restored_statement");
  ws.close();
}

main().catch((e) => { check("تشغيل الاختبار", false, e.stack || e.message); })
  .finally(() => {
    fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ failed, results }, null, 1));
    console.log(failed ? `✘ ${failed} فشل` : `✔ ${results.length} نجح على الجهاز`);
    process.exit(failed ? 1 : 0);
  });
