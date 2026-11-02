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

async function connect() {
  const list = await (await fetch("http://127.0.0.1:9223/json")).json();
  const ws = new WebSocket(list.find((t) => t.type === "page").webSocketDebuggerUrl);
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

// حدود WebView على الشاشة (بكسل) من شجرة الواجهة
function webBounds() {
  adb("shell", "uiautomator", "dump", "/sdcard/ui.xml");
  const xml = adb("shell", "cat", "/sdcard/ui.xml").toString();
  const m = xml.match(/class="android\.webkit\.WebView"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/);
  return m ? { l: +m[1], t: +m[2], r: +m[3], b: +m[4] } : null;
}

(async () => {
  const size = adb("shell", "wm", "size").toString().match(/(\d+)x(\d+)/);
  const H = +size[2];
  const ev = await connect();
  for (let i = 0; i < 40 && !(await ev("!!(window.App && App.state)")); i++) await sleep(250);
  await ev(`try { localStorage.setItem("welcomed", "1"); } catch (e) {} location.hash = "#/home"; 1`);
  await sleep(1200);
  shot("02_home");
  const w = webBounds();
  check("أندرويد 15: الصفحة تبدأ تحت شريط الحالة لا خلفه", w && w.t >= 40, JSON.stringify(w));
  check("وتنتهي فوق شريط التنقّل", w && w.b <= H - 20, `${JSON.stringify(w)} / ${H}`);
  // لوحة المفاتيح: خانةٌ في الإعدادات تُلمس فتظهر — والصفحة تقصر بقدرها
  await ev(`location.hash = "#/settings"; 1`);
  await sleep(900);
  const r = await ev(`(() => { const i = document.querySelector("#view input"); const b = i.getBoundingClientRect();
    return { x: b.left + b.width / 2, y: b.top + b.height / 2, dpr: devicePixelRatio }; })()`);
  adb("shell", "input", "tap", String(Math.round(w.l + r.x * r.dpr)), String(Math.round(w.t + r.y * r.dpr)));
  await sleep(1800);
  shot("03_keyboard");
  const k = webBounds();
  check("ولوحة المفاتيح لا تغطّي الصفحة: تقصر بقدرها", k && w && k.b < w.b - 200, `${JSON.stringify(k)} vs ${JSON.stringify(w)}`);
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
})().catch((e) => { console.error(e); fs.writeFileSync(path.join(OUT, "result.json"), JSON.stringify({ failed: 1, error: String(e) })); process.exit(1); });
