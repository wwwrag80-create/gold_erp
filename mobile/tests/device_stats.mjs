// يتصل بصفحة النسخة التجريبية على المحاكي (منفذ 9223) ويفحص الإرسال الصامت فعلاً:
// حالة الإحصاء في الجهاز، وطلبٌ مباشر إلى موقع التجربة، والرجوع من الخلفية (visibilitychange).
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const OUT = process.argv[2] || "device-out";
const PKG = process.env.PKG || "com.jadeite.mobile.trial";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const adb = (...a) => { try { return execFileSync("adb", a, { encoding: "utf8" }); } catch (e) { return String(e); } };

async function connect() {
  for (let i = 0; i < 30; i++) {
    try {
      const list = await (await fetch("http://127.0.0.1:9223/json")).json();
      const t = list.find((x) => (x.url || "").includes("appassets"));
      if (t) {
        const ws = new WebSocket(t.webSocketDebuggerUrl);
        await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
        let id = 0;
        const pending = new Map();
        ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
        const ev = (expr) => new Promise((res) => {
          const n = ++id;
          pending.set(n, (d) => res(d.result && d.result.result ? d.result.result.value : d));
          ws.send(JSON.stringify({ id: n, method: "Runtime.evaluate", params: { expression: expr, awaitPromise: true, returnByValue: true } }));
        });
        return { ws, ev };
      }
    } catch (e) { /* */ }
    await sleep(1000);
  }
  throw new Error("no webview page");
}

const res = {};
try {
  const { ws, ev } = await connect();
  res.first = await ev(`(async () => {
    for (let i = 0; i < 40 && !(window.AurStats); i++) await new Promise((r) => setTimeout(r, 250));
    await new Promise((r) => setTimeout(r, 4000));
    window.__vis = [];
    document.addEventListener("visibilitychange", () => window.__vis.push(document.visibilityState));
    return { href: location.href, online: navigator.onLine, hasStats: !!window.AurStats,
      native: !!(window.Bridge && Bridge.native), ver: window.Bridge && Bridge.appVersion(),
      state: JSON.parse(localStorage.getItem("aur.u") || "null"), vis: document.visibilityState };
  })()`);
  res.direct = await ev(`(async () => {
    const T = "https://claude-gold-accounting-syste.gold-erp.pages.dev/api/p", r = {};
    for (const ka of [false, true]) {
      const body = JSON.stringify({ i: "test-emu-" + Date.now().toString(36) + (ka ? "-ka" : "-no") + "-abcdef", v: "1.15.0", p: "trial", o: 1 });
      try { const x = await fetch(T, { method: "POST", body, keepalive: ka, credentials: "omit", cache: "no-store", headers: { "Content-Type": "text/plain" } }); r["keepalive_" + ka] = x.status + " " + (await x.text()); }
      catch (e) { r["keepalive_" + ka] = "ERR " + e.name + ": " + e.message; }
    }
    return r;
  })()`);
  // إلى الخلفية ثم العودة
  adb("shell", "input", "keyevent", "KEYCODE_HOME");
  await sleep(4000);
  res.background = await ev(`document.visibilityState`);
  adb("shell", "am", "start", "-n", `${PKG}/com.jadeite.mobile.MainActivity`);
  await sleep(5000);
  res.back = await ev(`({ vis: document.visibilityState, events: window.__vis, state: JSON.parse(localStorage.getItem("aur.u") || "null") })`);
  ws.close();
} catch (e) {
  res.error = String(e && e.stack || e);
}
const txt = JSON.stringify(res, null, 1);
console.log("=== STATS DEVICE ===\n" + txt);
fs.writeFileSync(path.join(OUT, "stats.json"), txt);
