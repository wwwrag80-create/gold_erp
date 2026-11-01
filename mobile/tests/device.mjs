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
  check("الإصدار المثبّت 1.1.0 (2)", us.version === "1.1.0" && us.code === 2 && !us.unsupported, JSON.stringify(us));
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

  await run(ev, `location.hash = "#/settings"; await t.sleep(300); t.fill("الاسم", "جاديت للذهب"); t.click("حفظ الإعدادات"); await t.sleep(300);`);
  for (const [n, w] of [["محل الأمانة", "20"], ["محل النخبة", ""]]) {
    await run(ev, `location.hash = "#/shop-form"; await t.sleep(300); t.fill("اسم المحل", ${JSON.stringify(n)});
      ${w ? `t.fill("الأجرة المتفق عليها", "${w}");` : ""} t.click("حفظ"); await t.sleep(400);`);
  }
  check("أُضيف محلان", (await ev("App.state.shops.length")) === 2);

  // فاتورة بيع
  await run(ev, `location.hash = "#/invoice/new?kind=sale"; await t.sleep(400); await t.pick("محل الأمانة");
    t.fill("رقم التشغيل", "W100"); t.fill("رقم الموديل", "M1"); t.fill("الذهب", "10"); t.fill("الفصوص", "1"); t.fill("الأحجار", "2");
    await t.sleep(100); t.click("+ إضافة سطر"); await t.sleep(200);
    t.fill("رقم التشغيل", "W200"); t.fill("العيار", "21"); t.fill("الذهب", "18"); t.fill("الأجر/جم", "23");
    t.click("+ إضافة سطر"); await t.sleep(300);`);
  shot("invoice_editor");
  check("الإجماليات 33.00 جم و654.00", await run(ev, `const x = document.querySelector(".totals").innerText; return x.includes("33.00") && x.includes("654.00");`));
  await run(ev, `t.click("ترحيل الفاتورة"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّلت S-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("S-00001"));
  await sleep(1200);
  shot("invoice_doc");

  // مرتجع — يُعبّأ من الفاتورة
  await run(ev, `location.hash = "#/invoice/new?kind=sale_return"; await t.sleep(400); await t.pick("محل الأمانة");
    t.fill("رقم التشغيل", "W100"); await t.sleep(200);`);
  check("المرتجع يُعبّأ من البيع (المقيد 12.00)", (await ev("__t.val('الوزن المقيد')")) === "12.00");
  await run(ev, `t.click("+ إضافة سطر"); await t.sleep(200); t.click("ترحيل الفاتورة"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّل R-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("R-00001"));

  // بيع الرقم المرتجع لمحلٍّ آخر — يُعبّأ من المرتجع
  await run(ev, `location.hash = "#/invoice/new?kind=sale"; await t.sleep(400); await t.pick("محل النخبة");
    t.fill("رقم التشغيل", "W100"); await t.sleep(200);`);
  check("بيع رقمٍ مرتجع يُعبّأ من المرتجع", (await ev("__t.val('الوزن المقيد')")) === "12.00" &&
    (await ev("__t.text().includes('رجع بالمرتجع R-00001')")));
  shot("resale_autofill");
  await run(ev, `t.click("+ إضافة سطر"); await t.sleep(200); t.click("ترحيل الفاتورة"); await t.confirm("ترحيل"); await t.sleep(800);`);

  // سند قبض
  await run(ev, `location.hash = "#/voucher/new?kind=receipt"; await t.sleep(400); await t.pick("محل الأمانة");
    t.fill("الوزن الفعلي", "6"); t.fill("العيار", "21"); t.click("+ نقد"); await t.sleep(200); t.fill("المبلغ", "500");
    await t.sleep(200); t.click("ترحيل السند"); await t.confirm("ترحيل"); await t.sleep(800);`);
  check("رُحّل RV-00001", (await ev("document.querySelector('#bar h1').innerText")).includes("RV-00001"));

  const sid = await ev("App.state.shops.find((s) => s.name === 'محل الأمانة').id");
  await run(ev, `location.hash = "#/statement/${sid}"; await t.sleep(600);`);
  const kp = await ev("document.querySelector('.kpis').innerText");
  check("كشف الحساب: 14.00 جم عليه و86.00 ريال له", kp.includes("14.00 جم عليه") && kp.includes("86.00 ريال له"), kp);
  shot("statement");

  // الحفظ التلقائي في المجلد بعد كل عملية
  await sleep(2500);
  let saved = null;
  try { saved = JSON.parse(adb("shell", "cat", "/sdcard/Documents/jadeite-data.json").toString()); } catch (e) { /* */ }
  check("الحفظ التلقائي: jadeite-data.json في Documents بكل العمليات",
    saved && saved.format === "jadeite-mobile-backup" && saved.invoices.length === 3 && saved.vouchers.length === 1,
    saved ? `${saved.invoices.length}/${saved.vouchers.length}` : "no file");
  const ls = adb("shell", "ls", "/sdcard/Documents").toString();
  check("ونسخة اليوم معه", /jadeite-data-\d{4}-\d{2}-\d{2}\.json/.test(ls), ls);

  await run(ev, `location.hash = "#/dashboard"; await t.sleep(700);`);
  check("لوحة التحكم: ثلاثة رسوم", (await ev("document.querySelectorAll('svg.chart').length")) === 3);
  shot("dashboard");
  await run(ev, `location.hash = "#/customers?view=board"; await t.sleep(600);`);
  shot("customers_board");

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
  check("البيانات باقية بعد إغلاق التطبيق وفتحه", (await ev("App.state.invoices.length")) === 3 &&
    (await ev("App.state.vouchers.length")) === 1);
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
  check("المجلد نفسه يُقرأ: jadeite-data.json", picked2 && rs && rs.ok && rs.file === "jadeite-data.json",
    JSON.stringify(rs && { ok: rs.ok, file: rs.file, error: rs.error }));
  await sleep(800);
  shot("restore_confirm");
  await run(ev, `await t.confirm("استرجاع"); await t.sleep(800);`);
  check("استُرجع كل شيء: 3 فواتير وسند ومحلان", (await ev("App.state.invoices.length")) === 3 &&
    (await ev("App.state.vouchers.length")) === 1 && (await ev("App.state.shops.length")) === 2);
  check("والحفظ التلقائي مستمرٌّ في المجلد نفسه", (await ev("Bridge.backupFolder()")) === "Documents");
  await run(ev, `location.hash = "#/statement/" + App.state.shops.find((s) => s.name === "محل الأمانة").id; await t.sleep(600);`);
  const kp2 = await ev("document.querySelector('.kpis').innerText");
  check("وكشف الحساب كما كان: 14.00 جم عليه و86.00 ريال له", kp2.includes("14.00 جم عليه") && kp2.includes("86.00 ريال له"), kp2);
  shot("restored_statement");
  ws.close();
}

main().catch((e) => { check("تشغيل الاختبار", false, e.stack || e.message); })
  .finally(() => {
    fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ failed, results }, null, 1));
    console.log(failed ? `✘ ${failed} فشل` : `✔ ${results.length} نجح على الجهاز`);
    process.exit(failed ? 1 : 0);
  });
