/* ÀUR — إحصاءات الاستخدام: خادمٌ صغير يعمل مع الموقع نفسه على Cloudflare، وقاعدةٌ مستقلة
 * (D1 باسم الربط STATS) — لا علاقة له بسحابة Supabase ولا يستهلك شيئاً من مساحتها.
 *
 *   POST /api/p        ← التطبيق يرسل في الخلفية رسالةً صغيرة: معرّفٌ عشوائي للتثبيت (لا يدلّ على
 *                        صاحبه)، الإصدار، المنصة، عدد مرات الفتح منذ آخر رسالة، وهل ينتظره تحديث.
 *                        لا أسماء ولا أرقام ولا فواتير ولا موقع، ولا يُحفظ عنوان IP.
 *   GET  /stats        ← لوحة المالك (كلمة مرور) · /stats/data أرقامها · /stats/login · /stats/logout ·
 *                        /stats/pass (تغيير كلمة المرور).
 * وكل مسارٍ غير هذين لا يصل إلى هنا أصلاً (_routes.json) فيبقى الموقع ملفاتٍ ثابتة كما كان.
 * الأيام بتوقيت الرياض.
 */

const TZ_MS = 3 * 3600 * 1000;                  // الرياض UTC+3 (بلا توقيت صيفي)
const DAY_MS = 86400000;
const PLATS = ["android", "play", "ios", "web", "trial"];
const PING_MAX = 600;
const COOKIE = "aur_s";
const SESSION_DAYS = 30;
const MAX_FAILS = 10;                           // محاولات دخولٍ خاطئة لكل عنوانٍ في اليوم
const ITER = 10000;
// كلمة المرور الأولى أُعطيت للمالك وحده؛ هنا بصمتها فقط. وتغييرها من اللوحة يحفظ بصمةً جديدة في القاعدة.
const INITIAL_PASS = "p2$10000$0PFcXXwpmlXWSbGzBrY7Xg==$4E9FUn40wh2o2QhvbCSFv/2K+LwV83dJq5L22zKC1XM=";

// نصّ اللوحة في المتصفح (mobile/site/stats_dash.js) — يضعه build_site.py هنا عند بناء الموقع
const DASH_JS = "/*DASH_JS*/";

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, plat TEXT, fresh INTEGER, first_day TEXT,
     last_day TEXT, first_ver TEXT, ver TEXT, opens INTEGER DEFAULT 0, updates INTEGER DEFAULT 0,
     waiting INTEGER DEFAULT 0, last_ts INTEGER)`,
  `CREATE TABLE IF NOT EXISTS daily(day TEXT PRIMARY KEY, active INTEGER DEFAULT 0, opens INTEGER DEFAULT 0,
     new INTEGER DEFAULT 0, upd INTEGER DEFAULT 0)`,
  `CREATE TABLE IF NOT EXISTS act(p TEXT, id TEXT, PRIMARY KEY(p, id)) WITHOUT ROWID`,
  `CREATE TABLE IF NOT EXISTS updates(id TEXT, day TEXT, from_ver TEXT, to_ver TEXT)`,
  `CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)`,
  `CREATE TABLE IF NOT EXISTS sess(h TEXT PRIMARY KEY, exp INTEGER)`,
  `CREATE TABLE IF NOT EXISTS fails(k TEXT PRIMARY KEY, n INTEGER, exp INTEGER)`,
];

// ── أيام وأسابيع (الأسبوع يبدأ الأحد) وإصدارات ──
const dayOf = (ms) => new Date(ms + TZ_MS).toISOString().slice(0, 10);
const addDays = (d, n) => new Date(Date.parse(d + "T00:00:00Z") + n * DAY_MS).toISOString().slice(0, 10);
function weekKey(d) {
  const t = Date.parse(d + "T00:00:00Z");
  return new Date(t - new Date(t).getUTCDay() * DAY_MS).toISOString().slice(0, 10);
}
function verCmp(a, b) {
  const x = String(a || "").split(".").map((n) => parseInt(n, 10) || 0);
  const y = String(b || "").split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d) return d > 0 ? 1 : -1;
  }
  return 0;
}

async function withSchema(db, fn) {
  try {
    return await fn();
  } catch (e) {
    if (!/no such table/i.test(String(e && e.message))) throw e;
    await db.batch(SCHEMA.map((s) => db.prepare(s)));
    return await fn();
  }
}

// ── الاستقبال من التطبيق ──
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

async function ping(request, env) {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (request.method !== "POST") return new Response("", { status: 405, headers: CORS });
  const db = env.STATS;
  if (!db) return new Response("", { status: 503, headers: CORS });
  const raw = await request.text();
  if (raw.length > PING_MAX) return new Response("", { status: 413, headers: CORS });
  let b;
  try { b = JSON.parse(raw) || {}; } catch (e) { return new Response("", { status: 400, headers: CORS }); }
  const id = String(b.i || ""), ver = String(b.v || ""), plat = String(b.p || "");
  if (!/^[a-z0-9-]{16,40}$/i.test(id) || !/^[0-9]{1,4}(\.[0-9]{1,5}){0,3}$/.test(ver) || !PLATS.includes(plat)) {
    return new Response("", { status: 400, headers: CORS });
  }
  const opens = Math.max(0, Math.min(200, parseInt(b.o, 10) || 0));
  const fresh = b.n ? 1 : 0, wait = b.r ? 1 : 0;
  const now = Date.now(), d = dayOf(now), w = "W" + weekKey(d), m = "M" + d.slice(0, 7);
  await withSchema(db, async () => {
    const row = await db.prepare("SELECT ver, last_day FROM devices WHERE id=?").bind(id).first();
    const daily = (active, nw, upd) => db.prepare(
      "INSERT INTO daily(day,active,opens,new,upd) VALUES(?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET " +
      "active=active+excluded.active, opens=opens+excluded.opens, new=new+excluded.new, upd=upd+excluded.upd",
    ).bind(d, active, opens, nw, upd);
    const act = (p) => db.prepare("INSERT OR IGNORE INTO act(p,id) VALUES(?,?)").bind(p, id);
    const st = [];
    if (!row) {
      st.push(db.prepare(
        "INSERT INTO devices(id,plat,fresh,first_day,last_day,first_ver,ver,opens,updates,waiting,last_ts) " +
        "VALUES(?,?,?,?,?,?,?,?,0,?,?) ON CONFLICT(id) DO NOTHING",
      ).bind(id, plat, fresh, d, d, ver, ver, opens, wait, now));
      st.push(daily(1, fresh, 0), act(w), act(m));
    } else {
      const last = String(row.last_day || "");
      const upd = verCmp(ver, row.ver) > 0 ? 1 : 0;
      if (upd) {
        st.push(db.prepare("INSERT INTO updates(id,day,from_ver,to_ver) VALUES(?,?,?,?)").bind(id, d, row.ver, ver));
      }
      st.push(db.prepare(
        "UPDATE devices SET plat=?, last_day=?, ver=?, opens=opens+?, updates=updates+?, waiting=?, last_ts=? WHERE id=?",
      ).bind(plat, d, ver, opens, upd, wait, now, id));
      st.push(daily(last === d ? 0 : 1, 0, upd));
      if (!last || "W" + weekKey(last) !== w) st.push(act(w));
      if (last.slice(0, 7) !== d.slice(0, 7)) st.push(act(m));
    }
    await db.batch(st);
  });
  return new Response('{"ok":1}', {
    status: 200, headers: { ...CORS, "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

// ── كلمة المرور والجلسة ──
const enc = new TextEncoder();
const b64 = (u8) => btoa(String.fromCharCode(...u8));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const hex = (u8) => [...u8].map((x) => x.toString(16).padStart(2, "0")).join("");
const randHex = (n) => hex(crypto.getRandomValues(new Uint8Array(n)));
async function sha256hex(s) { return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(s)))); }
async function pbkdf2(pw, salt, iter) {
  const k = await crypto.subtle.importKey("raw", enc.encode(pw), "PBKDF2", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: iter }, k, 256));
}
function same(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a[i] ^ b[i];
  return r === 0;
}
async function checkPass(pw, stored) {
  const [tag, it, s, h] = String(stored || "").split("$");
  if (tag !== "p2" || !(+it > 0)) return false;
  try { return same(await pbkdf2(pw, unb64(s), +it), unb64(h)); } catch (e) { return false; }
}
async function makePass(pw) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  return `p2$${ITER}$${b64(salt)}$${b64(await pbkdf2(pw, salt, ITER))}`;
}
async function storedPass(db) {
  const r = await db.prepare("SELECT v FROM meta WHERE k='pw'").first();
  return (r && r.v) || INITIAL_PASS;
}
function cookieOf(request, name) {
  for (const p of (request.headers.get("Cookie") || "").split(/;\s*/)) {
    const i = p.indexOf("=");
    if (i > 0 && p.slice(0, i) === name) return p.slice(i + 1);
  }
  return "";
}
async function session(request, db) {
  const t = cookieOf(request, COOKIE);
  if (!/^[0-9a-f]{64}$/.test(t)) return null;
  const h = await sha256hex(t);
  const r = await db.prepare("SELECT exp FROM sess WHERE h=?").bind(h).first();
  return r && r.exp > Date.now() ? h : null;
}
function sameOrigin(request, url) {
  const o = request.headers.get("Origin"), site = request.headers.get("Sec-Fetch-Site");
  if (site && site !== "same-origin" && site !== "none") return false;
  // «null»: متصفحٌ يُخفي الأصل — يُقبل فقط إن شهد المتصفح نفسه أن الطلب من الصفحة ذاتها
  if (o === "null") return site === "same-origin";
  return !o || o === url.origin;
}

// ── الصفحات ──
const NOCACHE = { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" };
function page(html, status, nonce, extra) {
  return new Response(html, {
    status: status || 200,
    headers: {
      "Content-Type": "text/html; charset=utf-8", ...NOCACHE,
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; " +
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'" + (nonce ? `; script-src 'nonce-${nonce}'` : ""),
      "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
      ...(extra || {}),
    },
  });
}
function json(obj, status, extra) {
  return new Response(JSON.stringify(obj), {
    status: status || 200, headers: { "Content-Type": "application/json; charset=utf-8", ...NOCACHE, ...(extra || {}) },
  });
}
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CSS = `
:root{color-scheme:light;--bg:#f4f3ef;--surface:#fcfcfb;--line:#e4e3de;--grid:#ebeae6;--text:#0b0b0b;--text2:#52514e;
--muted:#77766f;--accent:#2a78d6;--accent-wash:rgba(42,120,214,.10);--danger:#d03b3b;--ok:#0a7d0a;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--line:#2e2e2b;--grid:#272725;--text:#f0efec;--text2:#c3c2b7;--muted:#9b9a92;--accent:#3987e5;
--accent-wash:rgba(57,135,229,.14);--danger:#e66767;--ok:#3ec43e;--chip:#262624}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--line:#2e2e2b;--grid:#272725;--text:#f0efec;
--text2:#c3c2b7;--muted:#9b9a92;--accent:#3987e5;--accent-wash:rgba(57,135,229,.14);--danger:#e66767;--ok:#3ec43e;--chip:#262624}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif}
button,input{font:inherit;color:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
.top{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:14px}
.top h1{font-size:20px;margin:0}.sub{margin:2px 0 0;color:var(--muted);font-size:13px}
.acts{display:flex;gap:8px;flex-wrap:wrap}.acts form{margin:0}
.btn{border:1px solid var(--line);background:var(--surface);border-radius:10px;padding:7px 12px;cursor:pointer}
.btn:hover{border-color:var(--muted)}.btn.pri{background:var(--accent);border-color:var(--accent);color:#fff}
h2{font-size:15px;margin:22px 0 10px;color:var(--text2);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 14px;min-width:0}
.tile .l{color:var(--text2);font-size:13px}.tile .v{font-size:26px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.tile .h{color:var(--muted);font-size:12px;margin-top:2px}
.tag{display:inline-block;font-size:11px;color:var(--text2);background:var(--chip);border-radius:6px;padding:0 6px;margin-inline-start:6px;vertical-align:1px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,520px),1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;min-width:0}
.card .hd{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.card h3{font-size:15px;margin:0}.card .note{color:var(--muted);font-size:12px;margin:0 0 6px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.seg button{border:0;background:transparent;padding:4px 10px;cursor:pointer;color:var(--text2);font-size:13px}
.seg button[aria-pressed="true"]{background:var(--chip);color:var(--text);font-weight:600}
.chart{position:relative;min-height:60px}.chart svg{display:block;width:100%;overflow:visible}
.chart .empty{color:var(--muted);font-size:13px;padding:28px 0;text-align:center}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:9px;
padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);white-space:nowrap;z-index:2;display:none}
.tip b{font-size:14px}
.hb{display:grid;grid-template-columns:minmax(90px,auto) 1fr auto;gap:6px 10px;align-items:center;font-size:13px}
.hb .k{color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hb .tr{height:16px;position:relative}.hb .bar{position:absolute;inset-block:0;inset-inline-start:0;background:var(--accent);
border-start-end-radius:4px;border-end-end-radius:4px;min-width:2px}
.hb .n{font-variant-numeric:tabular-nums;color:var(--text)}
details.tbl{margin-top:8px}details.tbl summary{cursor:pointer;color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
td,th{border-bottom:1px solid var(--grid);padding:4px 6px;text-align:start}th{color:var(--text2);font-weight:600}
td.num,th.num{text-align:end;font-variant-numeric:tabular-nums}
.tblwrap{max-height:260px;overflow:auto}
.muted{color:var(--muted)}.err{color:var(--danger)}.okm{color:var(--ok)}
.login{max-width:360px;margin:12vh auto;background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:22px}
.login h1{font-size:19px;margin:0 0 4px}.login p{margin:0 0 14px;color:var(--muted);font-size:13px}
.fld{display:block;margin-bottom:10px}.fld span{display:block;font-size:13px;color:var(--text2);margin-bottom:4px}
.fld input{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:10px;background:var(--bg)}
dialog{border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--text);padding:18px;width:min(92vw,380px)}
dialog::backdrop{background:rgba(0,0,0,.35)}
.foot{color:var(--muted);font-size:12px;margin:22px 0 8px;line-height:1.7}
`;

function shell(title, body, nonce, script) {
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">` +
    `<meta name="color-scheme" content="light dark"><title>${esc(title)}</title><style>${CSS}</style></head>` +
    `<body>${body}${script ? `<script nonce="${nonce}">${script}</script>` : ""}</body></html>`;
}

function loginPage(msg, status) {
  const body = `<form class="login" method="post" action="/stats/login" autocomplete="on">
<h1>لوحة إحصاءات ÀUR</h1><p>للمالك فقط.</p>
<label class="fld"><span>كلمة المرور</span><input type="password" name="pw" autocomplete="current-password" required autofocus></label>
${msg ? `<p class="err" role="alert">${esc(msg)}</p>` : ""}
<button class="btn pri" type="submit" style="width:100%">دخول</button></form>`;
  return page(shell("إحصاءات ÀUR", body), status || 200);
}

function dashPage() {
  const nonce = randHex(16);
  const body = `<div class="wrap">
<header class="top"><div><h1>إحصاءات ÀUR</h1><p class="sub" id="asof">جارٍ التحميل…</p></div>
<div class="acts"><button class="btn" id="reload" type="button">تحديث</button>
<button class="btn" id="pwbtn" type="button">كلمة المرور</button>
<form method="post" action="/stats/logout"><button class="btn" type="submit">خروج</button></form></div></header>
<main id="app"></main>
<p class="foot">كل جهازٍ يُعرَف برقمٍ عشوائي يصنعه التطبيق عند أول فتح، بلا اسمٍ ولا رقم هاتف ولا بيانات عملاء.
الأيام بتوقيت الرياض. «غادروا» و«توقفوا» تقديرٌ من آخر استخدام: لا يُبلَّغ أي تطبيقٍ عند حذفه.</p>
</div>
<dialog id="pwdlg"><form id="pwform" method="dialog">
<h3 style="margin:0 0 12px">تغيير كلمة المرور</h3>
<label class="fld"><span>الحالية</span><input type="password" name="cur" autocomplete="current-password" required></label>
<label class="fld"><span>الجديدة (8 أحرف على الأقل)</span><input type="password" name="pw" autocomplete="new-password" minlength="8" required></label>
<label class="fld"><span>تأكيد الجديدة</span><input type="password" name="pw2" autocomplete="new-password" minlength="8" required></label>
<p id="pwmsg" role="status" style="min-height:1.5em;margin:0 0 8px"></p>
<div style="display:flex;gap:8px"><button class="btn pri" type="submit">حفظ</button>
<button class="btn" type="button" id="pwcancel">إغلاق</button></div></form></dialog>`;
  return page(shell("إحصاءات ÀUR", body, nonce, DASH_JS), 200, nonce);
}

// ── أرقام اللوحة ──
async function data(db) {
  const d = dayOf(Date.now());
  const c7 = addDays(d, -6), c30 = addDays(d, -29);
  const q = (sql, ...p) => db.prepare(sql).bind(...p);
  const r = await db.batch([
    q(`SELECT plat, COUNT(*) n, SUM(fresh) fresh, SUM(last_day=?) a1, SUM(last_day>=?) a7, SUM(last_day>=?) a30,
        SUM(fresh=1 AND first_day=?) n1, SUM(fresh=1 AND first_day>=?) n7, SUM(fresh=1 AND first_day>=?) n30,
        SUM(last_day<? AND last_day>=?) paused, SUM(last_day<?) gone, SUM(opens) opens, SUM(updates) upd,
        SUM(waiting=1 AND last_day>=?) waiting FROM devices GROUP BY plat`,
      d, c7, c30, d, c7, c30, c7, c30, c30, c30),
    q("SELECT day, active, opens, new, upd FROM daily WHERE day>=? ORDER BY day", addDays(d, -400)),
    q("SELECT first_day d, COUNT(*) n, SUM(fresh) f FROM devices GROUP BY first_day ORDER BY first_day"),
    q("SELECT substr(p,2) k, COUNT(*) n FROM act WHERE p>=? AND p<'X' GROUP BY p ORDER BY p", "W" + addDays(d, -26 * 7)),
    q("SELECT substr(p,2) k, COUNT(*) n FROM act WHERE p>=? AND p<'N' GROUP BY p ORDER BY p", "M" + addDays(d, -370).slice(0, 7)),
    q("SELECT plat, ver, COUNT(*) n FROM devices WHERE last_day>=? GROUP BY plat, ver", c30),
    q("SELECT substr(last_day,1,7) m, COUNT(*) n FROM devices WHERE last_day<? GROUP BY m ORDER BY m", c30),
    q("SELECT to_ver v, COUNT(*) n FROM updates GROUP BY to_ver"),
  ]);
  const rows = (i) => (r[i] && r[i].results) || [];
  const vers = rows(5);
  const latest = {};
  for (const v of vers) if (!latest[v.plat] || verCmp(v.ver, latest[v.plat]) > 0) latest[v.plat] = v.ver;
  const behind = {};
  for (const v of vers) if (verCmp(v.ver, latest[v.plat]) < 0) behind[v.plat] = (behind[v.plat] || 0) + v.n;
  return {
    today: d, at: Date.now(),
    plats: rows(0), daily: rows(1), growth: rows(2), weeks: rows(3), months: rows(4),
    versions: vers, latest, behind, left: rows(6), updVers: rows(7).sort((a, b) => verCmp(b.v, a.v)),
  };
}

async function stats(request, env, url) {
  const db = env.STATS;
  const p = url.pathname.replace(/\/+$/, "") || "/stats";
  if (!db) {
    return p === "/stats/data" ? json({ error: "not_configured" }, 503)
      : page(shell("إحصاءات ÀUR", `<div class="login"><h1>لوحة إحصاءات ÀUR</h1><p>قاعدة الإحصاء لم تُربط بعد.</p></div>`), 503);
  }
  return withSchema(db, async () => {
    if (p === "/stats/login") {
      if (request.method !== "POST") return Response.redirect(url.origin + "/stats", 303);
      if (!sameOrigin(request, url)) return loginPage("طلبٌ غير مسموح", 403);
      const ip = request.headers.get("CF-Connecting-IP") || "-";
      const now = Date.now();
      // عدّاد المحاولات الخاطئة لكل عنوانٍ في اليوم — ببصمةٍ مملّحة بسرٍّ عشوائي، لا العنوان نفسه
      let salt = await db.prepare("SELECT v FROM meta WHERE k='salt'").first();
      if (!salt) {
        await db.prepare("INSERT OR IGNORE INTO meta(k,v) VALUES('salt',?)").bind(randHex(16)).run();
        salt = await db.prepare("SELECT v FROM meta WHERE k='salt'").first();
      }
      const fk = await sha256hex(salt.v + "|" + ip + "|" + dayOf(now));
      const f = await db.prepare("SELECT n FROM fails WHERE k=?").bind(fk).first();
      if (f && f.n >= MAX_FAILS) return loginPage("محاولاتٌ خاطئة كثيرة — جرّب غداً", 429);
      let pw = "";
      try { pw = String((await request.formData()).get("pw") || "").slice(0, 200); } catch (e) { /* */ }
      if (!pw || !(await checkPass(pw, await storedPass(db)))) {
        await db.prepare("INSERT INTO fails(k,n,exp) VALUES(?,1,?) ON CONFLICT(k) DO UPDATE SET n=n+1")
          .bind(fk, now + 2 * DAY_MS).run();
        return loginPage("كلمة المرور غير صحيحة", 401);
      }
      const tok = randHex(32);
      await db.batch([
        db.prepare("INSERT INTO sess(h,exp) VALUES(?,?)").bind(await sha256hex(tok), now + SESSION_DAYS * DAY_MS),
        db.prepare("DELETE FROM sess WHERE exp<?").bind(now),
        db.prepare("DELETE FROM fails WHERE k=? OR exp<?").bind(fk, now),
      ]);
      return new Response(null, {
        status: 303,
        headers: {
          Location: "/stats", ...NOCACHE,
          "Set-Cookie": `${COOKIE}=${tok}; Path=/stats; Max-Age=${SESSION_DAYS * 86400}; HttpOnly; Secure; SameSite=Strict`,
        },
      });
    }
    const sh = await session(request, db);
    if (p === "/stats/logout") {
      if (request.method === "POST" && sameOrigin(request, url) && sh) {
        await db.prepare("DELETE FROM sess WHERE h=?").bind(sh).run();
      }
      return new Response(null, {
        status: 303,
        headers: { Location: "/stats", ...NOCACHE, "Set-Cookie": `${COOKIE}=; Path=/stats; Max-Age=0; HttpOnly; Secure; SameSite=Strict` },
      });
    }
    if (!sh) return p === "/stats/data" || p === "/stats/pass" ? json({ error: "login" }, 401) : loginPage("");
    if (p === "/stats/data") return json(await data(db));
    if (p === "/stats/pass") {
      if (request.method !== "POST" || !sameOrigin(request, url)) return json({ ok: false, error: "طلبٌ غير مسموح" }, 403);
      let b = {};
      try { b = await request.json(); } catch (e) { /* */ }
      const cur = String(b.cur || ""), pw = String(b.pw || ""), pw2 = String(b.pw2 || "");
      if (!(await checkPass(cur, await storedPass(db)))) return json({ ok: false, error: "كلمة المرور الحالية غير صحيحة" });
      if (pw.length < 8 || pw.length > 200) return json({ ok: false, error: "الجديدة 8 أحرف على الأقل" });
      if (pw !== pw2) return json({ ok: false, error: "الجديدة وتأكيدها غير متطابقتين" });
      await db.batch([
        db.prepare("INSERT INTO meta(k,v) VALUES('pw',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v").bind(await makePass(pw)),
        db.prepare("DELETE FROM sess WHERE h<>?").bind(sh),
      ]);
      return json({ ok: true });
    }
    if (p === "/stats") return dashPage();
    return new Response("Not found", { status: 404, headers: NOCACHE });
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    try {
      if (p === "/api/p") return await ping(request, env);
      if (p === "/stats" || p.startsWith("/stats/")) return await stats(request, env, url);
    } catch (e) {
      return new Response("", { status: 500, headers: { ...CORS, ...NOCACHE } });
    }
    return env.ASSETS.fetch(request);
  },
};
