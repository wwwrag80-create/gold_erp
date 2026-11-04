// أندرويد 15 (API 35) والتطبيق بـ targetSdk 36: الصفحة تُزاح عن شريطي النظام وعن
// لوحة المفاتيح. يقيس حدود WebView من شجرة الواجهة (uiautomator) ويصوّر الشاشة.
//   node mobile/tests/edge.mjs OUT_DIR      (بعد adb forward tcp:9223 → devtools)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "device-out/edge";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const adb = (...a) => execFileSync("adb", a, { maxBuffer: 64 << 20 });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail: String(detail) }); console.log(ok ? "  ✔" : "  ✘", name, detail); };
const shot = (n) => fs.writeFileSync(path.join(OUT, `${n}.png`), adb("exec-out", "screencap", "-p"));

// صفحة التطبيق نفسها (appassets) — لا WebView الإعلان الذي يظهر في القائمة أيضاً
async function connect() {
  let t;
  for (let i = 0; i < 40 && !t; i++) {
    try {
      const list = await (await fetch("http://127.0.0.1:9223/json")).json();
      t = list.find((x) => (x.url || "").includes("appassets"));
    } catch (e) { /* */ }
    if (!t) await sleep(500);
  }
  if (!t) throw new Error("app page not found in devtools list");
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const wait = new Map();
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (wait.has(d.id)) { wait.get(d.id)(d); wait.delete(d.id); } });
  return async (expr) => {
    const n = ++id;
    ws.send(JSON.stringify({ id: n, method: "Runtime.evaluate", params: { expression: expr, awaitPromise: true, returnByValue: true } }));
    const d = await new Promise((r) => wait.set(n, r));
    return d.result && d.result.result ? d.result.result.value : undefined;
  };
}

// حدود WebView التطبيق على الشاشة (بكسل) من شجرة الواجهة — الأطول بينها (الإعلان WebView صغيرٌ أيضاً)
// المحاكي قد يقتل أداة uiautomator (137) وقد كتبت الملف أو لم تكتبه: تُعاد حتى ثلاث
// مرات، ويُقرأ الملف إن وُجد — وتفشل التجربة إن لم تُقرأ الشجرة أبداً
function dumpUi() {
  let last;
  for (let i = 0; i < 3; i++) {
    try { adb("shell", "rm", "-f", "/sdcard/ui.xml"); } catch (e) { /* */ }
    try { adb("shell", "uiautomator", "dump", "/sdcard/ui.xml"); } catch (e) { last = e; }
    try {
      const xml = adb("shell", "cat", "/sdcard/ui.xml").toString();
      if (xml.includes("</hierarchy>")) return xml;
    } catch (e) { last = e; }
    execFileSync("sleep", ["2"]);
  }
  throw last || new Error("uiautomator dump: no hierarchy");
}
function webBounds() {
  const xml = dumpUi();
  const all = [...xml.matchAll(/class="android\.webkit\.WebView"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/g)]
    .map((m) => ({ l: +m[1], t: +m[2], r: +m[3], b: +m[4] }));
  return all.sort((a, b) => (b.b - b.t) - (a.b - a.t))[0] || null;
}

(async () => {
  const size = adb("shell", "wm", "size").toString().match(/(\d+)x(\d+)/);
  const H = +size[2];
  // شريط الحالة 24dp: بالبكسل حسب كثافة الشاشة (160 = 1×)
  const dpi = +((adb("shell", "wm", "density").toString().match(/(\d+)\s*$/m) || [0, 160])[1]);
  const bar = Math.round(24 * dpi / 160);
  const ev = await connect();
  for (let i = 0; i < 40 && !(await ev("!!(window.App && App.state)")); i++) await sleep(250);
  await ev(`try { localStorage.setItem("welcomed", "1"); } catch (e) {} App.go("home"); 1`);
  for (let i = 0; i < 20 && !(await ev(`!!document.querySelector("#view .op-tile")`)); i++) await sleep(250);
  await sleep(600);
  shot("02_home");
  const w = webBounds();
  check("أندرويد 15: الصفحة تبدأ تحت شريط الحالة لا خلفه", w && w.t >= bar, `${JSON.stringify(w)} · شريط الحالة ${bar}px`);
  check("وتنتهي فوق شريط التنقّل", w && w.b <= H - 20, `${JSON.stringify(w)} / ${H}`);
  // لوحة المفاتيح: خانةٌ في الإعدادات تُلمس فتظهر — والصفحة تقصر بقدرها
  await ev(`location.hash = "#/settings"; 1`);
  await sleep(900);
  const r = await ev(`(() => { const i = document.querySelector("#view input.in"); if (!i) return null; const b = i.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2, dpr: devicePixelRatio }; })()`);
  check("شاشة الإعدادات فيها خانة كتابة", r && w, await ev("location.hash"));
  if (r && w) adb("shell", "input", "tap", String(Math.round(w.l + r.x * r.dpr)), String(Math.round(w.t + r.y * r.dpr)));
  await sleep(1800);
  shot("03_keyboard");
  const k = webBounds();
  // بقدر لوحة المفاتيح: خُمس الشاشة على الأقل — لا عددٌ ثابت من البكسل، فلوحة
  // محاكي 320×640 بلا شريط اقتراحات ارتفاعها 185px وحده
  check("ولوحة المفاتيح لا تغطّي الصفحة: تقصر بقدرها", k && w && k.b < w.b - Math.round(H * 0.2) && k.b > w.t + 100,
    `${JSON.stringify(k)} vs ${JSON.stringify(w)} · H ${H}`);
  adb("shell", "input", "keyevent", "KEYCODE_BACK");
  await sleep(600);
  // الرجوع بالإيماءة الجديدة: من الإعدادات إلى الرئيسية
  adb("shell", "input", "keyevent", "KEYCODE_BACK");
  await sleep(900);
  check("زرّ الرجوع يعود صفحةً داخل التطبيق", (await ev("location.hash")) === "#/home", await ev("location.hash"));
  shot("04_back_home");
  const failed = results.filter((x) => !x.ok).length;
  fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ failed, results }, null, 1));
  console.log(failed ? `✘ ${failed} فشل` : "✔ الحواف سليمة");
  process.exit(failed ? 1 : 0);
})().catch((e) => {
  console.error(e);
  fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ failed: 1, error: String(e && e.stack || e), results }, null, 1));
  process.exit(1);
});
