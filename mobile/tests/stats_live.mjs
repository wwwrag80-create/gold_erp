// فحص خادم الإحصاءات على عنوانٍ حيّ (محلي من «wrangler pages dev» أو موقع التجربة أو الموقع نفسه):
//   node mobile/tests/stats_live.mjs http://127.0.0.1:8788            ← الاستقبال والحماية
//   STATS_PASS=… node mobile/tests/stats_live.mjs URL                  ← ومعه الدخول وأرقام اللوحة
// الرسائل التجريبية بمعرّفٍ يبدأ بـ «test-» فتُعرف وتُحذف لاحقاً.
const BASE = (process.argv[2] || "http://127.0.0.1:8788").replace(/\/+$/, "");
const PASS = process.env.STATS_PASS || "";
let ok = 0, bad = 0;
const check = (name, cond, info) => {
  if (cond) { ok++; console.log("  ✔ " + name); } else { bad++; console.log("  ✘ " + name + (info !== undefined ? "  [" + info + "]" : "")); }
};
const ping = (body, origin) => fetch(BASE + "/api/p", {
  method: "POST", body: typeof body === "string" ? body : JSON.stringify(body),
  headers: { "Content-Type": "text/plain", Origin: origin || "https://appassets.androidplatform.net" },
});
const id = "test-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);

console.log("── الموقع كما هو");
let r = await fetch(BASE + "/");
check("الصفحة الرئيسية تُفتح", r.status === 200 && (await r.text()).includes("ÀUR"));
r = await fetch(BASE + "/app/version.json");
check("ملفات التطبيق تُفتح", r.status === 200 && !!(await r.json()).name);
r = await fetch(BASE + "/_worker.js");
check("ملف الخادم نفسه لا يُعرض", r.status !== 200 || !(await r.text()).includes("INITIAL_PASS"));

console.log("── الاستقبال من التطبيق");
r = await fetch(BASE + "/api/p", { method: "OPTIONS", headers: { Origin: "https://appassets.androidplatform.net", "Access-Control-Request-Method": "POST" } });
check("سماح المتصفح (CORS)", r.status === 204 && r.headers.get("access-control-allow-origin") === "*");
r = await ping("{bad");
check("رسالةٌ تالفة تُرفض", r.status === 400, r.status);
r = await ping({ i: "x", v: "1.15.0", p: "android", o: 1 });
check("معرّفٌ غير صالح يُرفض", r.status === 400, r.status);
r = await ping({ i: id, v: "1.15.0", p: "mars", o: 1 });
check("منصةٌ غير معروفة تُرفض", r.status === 400, r.status);
r = await ping("x".repeat(2000));
check("رسالةٌ كبيرة تُرفض", r.status === 413, r.status);
r = await ping({ i: id, v: "1.14.0", p: "trial", o: 2, n: 1 });
check("رسالةٌ صحيحة تُحفظ", r.status === 200 && (await r.json()).ok === 1, r.status);
r = await ping({ i: id, v: "1.15.0", p: "trial", o: 1, r: 0 });
check("ورسالةٌ ثانية بإصدارٍ أحدث (تحديث)", r.status === 200, r.status);
r = await fetch(BASE + "/api/p");
check("GET على الاستقبال مرفوض", r.status === 405, r.status);

console.log("── اللوحة محمية");
r = await fetch(BASE + "/stats", { redirect: "manual" });
let h = await r.text();
check("بلا دخول: صفحة كلمة المرور فقط", r.status === 200 && h.includes('name="pw"') && !h.includes("dashMain"));
check("ولا تُخزَّن ولا تُفهرس", (r.headers.get("cache-control") || "").includes("no-store")
  && (r.headers.get("x-robots-tag") || "").includes("noindex"));
r = await fetch(BASE + "/stats/data");
check("وأرقامها مرفوضة بلا دخول", r.status === 401, r.status);
r = await fetch(BASE + "/stats/data", { headers: { Cookie: "aur_s=" + "0".repeat(64) } });
check("وبجلسةٍ مزيّفة مرفوضة", r.status === 401, r.status);
r = await fetch(BASE + "/stats/login", {
  method: "POST", redirect: "manual", body: new URLSearchParams({ pw: "wrong-password" }),
  headers: { Origin: BASE },
});
check("كلمة مرورٍ خاطئة تُرفض", r.status === 401 && !(r.headers.get("set-cookie") || "").includes("aur_s=") , r.status);
r = await fetch(BASE + "/stats/login", {
  method: "POST", redirect: "manual", body: new URLSearchParams({ pw: PASS || "x" }),
  headers: { Origin: "https://evil.example" },
});
check("والدخول من موقعٍ آخر مرفوض", r.status === 403, r.status);

if (PASS) {
  console.log("── الدخول والأرقام");
  r = await fetch(BASE + "/stats/login", {
    method: "POST", redirect: "manual", body: new URLSearchParams({ pw: PASS }), headers: { Origin: BASE },
  });
  const sc = r.headers.get("set-cookie") || "";
  const tok = (sc.match(/aur_s=([0-9a-f]{64})/) || [])[1];
  check("كلمة المرور الصحيحة تفتح اللوحة", r.status === 303 && !!tok, r.status);
  check("والجلسة آمنة (HttpOnly · Secure · SameSite)", /HttpOnly/i.test(sc) && /Secure/i.test(sc) && /SameSite=Strict/i.test(sc));
  const C = { Cookie: "aur_s=" + tok };
  r = await fetch(BASE + "/stats", { headers: C });
  h = await r.text();
  check("صفحة اللوحة", r.status === 200 && h.includes("إحصاءات ÀUR") && h.includes("<script nonce=") && h.includes('id="app"'));
  check("وسياسة أمانٍ تمنع أي سكربتٍ غريب", /script-src 'nonce-/.test(r.headers.get("content-security-policy") || ""));
  r = await fetch(BASE + "/stats/data", { headers: C });
  const D = await r.json();
  const trial = (D.plats || []).find((p) => p.plat === "trial") || {};
  check("الأرقام تصل: الجهاز التجريبي محسوب", r.status === 200 && trial.n >= 1, JSON.stringify(trial));
  check("ونشطٌ اليوم وجديد", trial.a1 >= 1 && trial.n1 >= 1);
  check("وتحديثه إلى 1.15.0 محسوب", (D.updVers || []).some((u) => u.v === "1.15.0" && u.n >= 1));
  check("ومرات الفتح اليوم", (D.daily || []).some((d) => d.day === D.today && d.opens >= 3));
  check("وإصداره في توزيع الإصدارات", (D.versions || []).some((v) => v.plat === "trial" && v.ver === "1.15.0"));
}
console.log(`\n${ok} ✔ · ${bad} ✘`);
process.exit(bad ? 1 : 0);
