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
  return true;
})()`;

const run = async (ev, body) => ev(`(async () => { const t = window.__t; ${body} })()`);

async function main() {
  let { ws, ev } = await connect();
  for (let i = 0; i < 40; i++) { if (await ev("!!(window.App && App.state)")) break; await sleep(250); }
  check("التطبيق يفتح وتُحمَّل بياناته", await ev("!!(window.App && App.state)"));
  check("الخط العربي محمَّل", await ev("document.fonts.check('16px Plex')"));
  await ev(HARNESS);
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

  // البيانات تبقى بعد إغلاق التطبيق
  ws.close();
  adb("shell", "am", "force-stop", "com.jadeite.mobile");
  await sleep(1500);
  adb("shell", "am", "start", "-W", "-n", "com.jadeite.mobile/.MainActivity");
  await sleep(5000);
  const pid = adb("shell", "pidof", "com.jadeite.mobile").toString().trim();
  adb("forward", "--remove-all");
  adb("forward", "tcp:9222", `localabstract:webview_devtools_remote_${pid}`);
  ({ ws, ev } = await connect());
  for (let i = 0; i < 40; i++) { if (await ev("!!(window.App && App.state)")) break; await sleep(250); }
  check("البيانات باقية بعد إغلاق التطبيق وفتحه", (await ev("App.state.invoices.length")) === 3 &&
    (await ev("App.state.vouchers.length")) === 1);
  await ev(`location.hash = "#/home"`);
  await sleep(800);
  shot("home_after");
  ws.close();
}

main().catch((e) => { check("تشغيل الاختبار", false, e.stack || e.message); })
  .finally(() => {
    fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ failed, results }, null, 1));
    console.log(failed ? `✘ ${failed} فشل` : `✔ ${results.length} نجح على الجهاز`);
    process.exit(failed ? 1 : 0);
  });
