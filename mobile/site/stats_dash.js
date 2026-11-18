/* لوحة إحصاءات ÀUR في المتصفح — بلا مكتباتٍ ولا ملفاتٍ خارجية: أرقام، ورسوم SVG بمؤشرٍ يُظهر القيمة.
 * يضعها build_site.py نصّاً داخل _worker.js (فتُرسل داخل صفحة اللوحة نفسها بسياسة أمانٍ صارمة). */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const fmt = (n) => Number(n || 0).toLocaleString("en-US");
  const MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
  const PLAT = { android: "أندرويد (ملف التثبيت)", play: "أندرويد (Google Play)", ios: "آيفون", web: "المتصفح", trial: "نسخة تجريبية" };
  const DAY = 86400000;
  const addDays = (d, n) => new Date(Date.parse(d + "T00:00:00Z") + n * DAY).toISOString().slice(0, 10);
  const weekKey = (d) => { const t = Date.parse(d + "T00:00:00Z"); return new Date(t - new Date(t).getUTCDay() * DAY).toISOString().slice(0, 10); };
  const dmy = (d) => d.slice(8, 10) + "/" + d.slice(5, 7) + "/" + d.slice(0, 4);
  const dm = (d) => d.slice(8, 10) + "/" + d.slice(5, 7);
  const mname = (m) => MONTHS[+m.slice(5, 7) - 1] + " " + m.slice(0, 4);
  const mshort = (m) => MONTHS[+m.slice(5, 7) - 1];
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const NS = "http://www.w3.org/2000/svg";
  let D = null;
  const charts = [];

  // أعلى المحور: أربع خطوطٍ بأعدادٍ صحيحة (0 · 60 · 120 · 180 · 240)
  function niceMax(v) {
    const raw = Math.max(1, v / 4), p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10]) {
      const step = m * p;
      if (step >= raw && Number.isInteger(step)) return step * 4;
    }
    return 40 * p;
  }
  const tick = (v) => (v >= 10000 ? (v / 1000).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "K" : fmt(v));

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  // أعمدة: pts = [{k: نص المحور، t: نص التلميح، v}] — kind "bar" أو "line" (نموّ تراكمي)
  function plot(box, pts, kind, unit) {
    box.innerHTML = "";
    if (!pts.length || pts.every((p) => !p.v)) {
      box.innerHTML = '<div class="empty">لا بيانات بعد</div>';
      return;
    }
    const W = Math.max(260, box.clientWidth || 300), H = 210;
    const ml = 40, mr = 14, mt = 14, mb = 26;
    const iw = W - ml - mr, ih = H - mt - mb;
    const max = niceMax(Math.max(...pts.map((p) => p.v)));
    const y = (v) => mt + ih - (v / max) * ih;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", direction: "ltr" }, box);
    for (let i = 0; i <= 4; i++) {
      const v = (max / 4) * i, yy = Math.round(y(v)) + 0.5;
      el("line", { x1: ml, x2: W - mr, y1: yy, y2: yy, stroke: "var(--grid)", "stroke-width": 1 }, svg);
      const t = el("text", { x: ml - 6, y: yy + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, svg);
      t.textContent = tick(v);
    }
    const n = pts.length, band = iw / n;
    const xc = (i) => ml + band * i + band / 2;
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 64))));
    for (let i = 0; i < n; i++) {
      if ((n - 1 - i) % every) continue;
      const t = el("text", { x: xc(i), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" }, svg);
      t.textContent = pts[i].k;
    }
    let marks = [];
    if (kind === "line") {
      const path = pts.map((p, i) => (i ? "L" : "M") + xc(i).toFixed(1) + "," + y(p.v).toFixed(1)).join("");
      el("path", { d: path + `L${xc(n - 1).toFixed(1)},${y(0)}L${xc(0).toFixed(1)},${y(0)}Z`, fill: "var(--accent-wash)" }, svg);
      el("path", { d: path, fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      el("circle", { cx: xc(n - 1), cy: y(pts[n - 1].v), r: 4, fill: "var(--accent)", stroke: "var(--surface)", "stroke-width": 2 }, svg);
      const lab = el("text", { x: xc(n - 1) - 8, y: y(pts[n - 1].v) - 9, "text-anchor": "end", "font-size": 12, "font-weight": 600, fill: "var(--text)" }, svg);
      lab.textContent = fmt(pts[n - 1].v);
    } else {
      const bw = Math.max(1, Math.min(24, band - 2));
      marks = pts.map((p, i) => {
        const h = Math.max(0, y(0) - y(p.v)), x = xc(i) - bw / 2, top = y(0) - h;
        const r = Math.min(bw >= 8 ? 4 : 0, h);
        const d = h <= 0 ? "" : `M${x},${y(0)}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${y(0)}Z`;
        return el("path", { d, fill: "var(--accent)" }, svg);
      });
    }
    el("line", { x1: ml, x2: W - mr, y1: y(0) + 0.5, y2: y(0) + 0.5, stroke: "var(--line)", "stroke-width": 1 }, svg);
    // التلميح
    const tip = document.createElement("div");
    tip.className = "tip";
    box.appendChild(tip);
    const cross = el("line", { y1: mt, y2: y(0), stroke: "var(--muted)", "stroke-width": 1, opacity: 0 }, svg);
    const dot = kind === "line" ? el("circle", { r: 5, fill: "var(--accent)", stroke: "var(--surface)", "stroke-width": 2, opacity: 0 }, svg) : null;
    const hit = el("rect", { x: ml, y: mt, width: iw, height: ih, fill: "transparent" }, svg);
    const show = (ev) => {
      const r = svg.getBoundingClientRect();
      const sx = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(n - 1, Math.floor((sx - ml) / band)));
      const p = pts[i];
      marks.forEach((m, j) => m.setAttribute("opacity", j === i ? 1 : 0.45));
      cross.setAttribute("x1", xc(i)); cross.setAttribute("x2", xc(i)); cross.setAttribute("opacity", kind === "line" ? 0.6 : 0);
      if (dot) { dot.setAttribute("cx", xc(i)); dot.setAttribute("cy", y(p.v)); dot.setAttribute("opacity", 1); }
      tip.innerHTML = `${esc(p.t)}<br><b>${fmt(p.v)}</b> ${esc(unit || "")}`;
      tip.style.display = "block";
      const px = (xc(i) / W) * r.width, tw = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(r.width - tw, px - tw / 2)) + "px";
      tip.style.top = Math.max(0, (y(p.v) / H) * r.height - tip.offsetHeight - 10) + "px";
    };
    const hide = () => {
      tip.style.display = "none"; cross.setAttribute("opacity", 0);
      if (dot) dot.setAttribute("opacity", 0);
      marks.forEach((m) => m.setAttribute("opacity", 1));
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", hide);
  }

  function table(head, rows) {
    return `<details class="tbl"><summary>عرض كجدول</summary><div class="tblwrap"><table><tr>${head.map((h, i) => `<th${i ? ' class="num"' : ""}>${esc(h)}</th>`).join("")}</tr>` +
      rows.map((r) => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ""}>${esc(i ? fmt(c) : c)}</td>`).join("")}</tr>`).join("") + "</table></div></details>";
  }

  // سلاسل زمنية من الجدول اليومي: يومي (90 يوماً) · أسبوعي (26 أسبوعاً) · شهري (12 شهراً)
  function series(field, per) {
    const t = D.today, by = {};
    for (const r of D.daily) by[r.day] = r[field] || 0;
    if (per === "d") {
      const out = [];
      for (let i = 89; i >= 0; i--) { const d = addDays(t, -i); out.push({ k: dm(d), t: dmy(d), v: by[d] || 0 }); }
      return out;
    }
    if (per === "w") {
      const w0 = weekKey(t), sums = {};
      for (const d in by) sums[weekKey(d)] = (sums[weekKey(d)] || 0) + by[d];
      const out = [];
      for (let i = 25; i >= 0; i--) { const w = addDays(w0, -7 * i); out.push({ k: dm(w), t: "أسبوع " + dmy(w), v: sums[w] || 0 }); }
      return out;
    }
    const sums = {};
    for (const d in by) sums[d.slice(0, 7)] = (sums[d.slice(0, 7)] || 0) + by[d];
    return months().map((m) => ({ k: mshort(m), t: mname(m), v: sums[m] || 0 }));
  }
  function months() {
    const out = [];
    let y = +D.today.slice(0, 4), m = +D.today.slice(5, 7);
    for (let i = 0; i < 12; i++) {
      out.unshift(y + "-" + String(m).padStart(2, "0"));
      if (--m === 0) { m = 12; y--; }
    }
    return out;
  }
  function activeSeries(per) {
    if (per === "d") return series("active", "d");
    if (per === "w") {
      const by = {};
      for (const r of D.weeks) by[r.k] = r.n;
      const w0 = weekKey(D.today), out = [];
      for (let i = 25; i >= 0; i--) { const w = addDays(w0, -7 * i); out.push({ k: dm(w), t: "أسبوع " + dmy(w), v: by[w] || 0 }); }
      return out;
    }
    const by = {};
    for (const r of D.months) by[r.k] = r.n;
    return months().map((m) => ({ k: mshort(m), t: mname(m), v: by[m] || 0 }));
  }
  function growth() {
    const g = D.growth;
    if (!g.length) return [];
    const by = {};
    for (const r of g) by[r.d] = r.n;
    let d = g[0].d, total = 0;
    const out = [];
    while (d <= D.today) {
      total += by[d] || 0;
      out.push({ k: dm(d), t: dmy(d), v: total });
      d = addDays(d, 1);
    }
    if (out.length === 1) out.unshift({ k: "", t: "قبل البدء", v: 0 });
    return out;
  }

  function card(id, title, note, toggles) {
    const seg = toggles ? `<div class="seg" role="group">${[["d", "يومي"], ["w", "أسبوعي"], ["m", "شهري"]].map(([k, l]) =>
      `<button type="button" data-per="${k}" aria-pressed="${k === "d"}">${l}</button>`).join("")}</div>` : "";
    return `<section class="card" id="${id}"><div class="hd"><h3>${title}</h3>${seg}</div>${note ? `<p class="note">${note}</p>` : ""}<div class="chart"></div><div class="tv"></div></section>`;
  }

  function mount(id, build, unit, kind) {
    const sec = document.getElementById(id);
    const box = sec.querySelector(".chart"), tv = sec.querySelector(".tv");
    let per = "d";
    const draw = () => {
      const pts = build(per);
      plot(box, pts, kind || "bar", unit);
      tv.innerHTML = pts.length ? table(["الفترة", unit || "العدد"], pts.slice().reverse().map((p) => [p.t, p.v])) : "";
    };
    sec.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
      per = b.dataset.per;
      sec.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw();
    }));
    charts.push(draw);
    draw();
  }

  function hbars(rows) {
    if (!rows.length) return '<div class="empty muted" style="padding:16px 0">لا بيانات بعد</div>';
    const max = Math.max(...rows.map((r) => r[1])) || 1;
    return `<div class="hb">` + rows.map(([k, v, h]) =>
      `<div class="k" title="${esc(k)}">${esc(k)}</div><div class="tr" title="${esc(h || "")}"><div class="bar" style="width:${(v / max) * 100}%"></div></div><div class="n">${fmt(v)}</div>`).join("") + "</div>";
  }

  function render() {
    const P = D.plats, sum = (f, rows) => (rows || P).reduce((a, r) => a + (r[f] || 0), 0);
    const daysum = (f, from) => D.daily.filter((r) => r.day >= from).reduce((a, r) => a + (r[f] || 0), 0);
    const t = D.today, c7 = addDays(t, -6), c30 = addDays(t, -29);
    const total = sum("n"), fresh = sum("fresh");
    const behind = Object.values(D.behind).reduce((a, b) => a + b, 0);
    const tile = (l, v, h, tag) => `<div class="tile"><div class="l">${l}${tag ? `<span class="tag">${tag}</span>` : ""}</div><div class="v">${fmt(v)}</div>${h ? `<div class="h">${h}</div>` : ""}</div>`;
    $("#asof").textContent = "حتى " + dmy(t) + " · " + new Date(D.at).toLocaleTimeString("ar-SA-u-nu-latn", { hour: "2-digit", minute: "2-digit" });
    $("#app").innerHTML =
      `<h2>المستخدمون</h2><div class="tiles">` +
      tile("إجمالي الأجهزة", total, "ثبّتت التطبيق وفتحته") +
      tile("نشطون اليوم", sum("a1")) + tile("نشطون (7 أيام)", sum("a7")) + tile("نشطون (30 يوماً)", sum("a30")) +
      `</div><h2>المنضمّون الجدد</h2><div class="tiles">` +
      tile("جدد اليوم", sum("n1")) + tile("جدد (7 أيام)", sum("n7")) + tile("جدد (30 يوماً)", sum("n30")) +
      tile("جدد منذ بدء الإحصاء", fresh) + tile("مستخدمون سابقون", total - fresh, "كانوا يستخدمونه قبل بدء الإحصاء") +
      `</div><h2>الاستخدام</h2><div class="tiles">` +
      tile("مرات الفتح اليوم", daysum("opens", t)) + tile("مرات الفتح (7 أيام)", daysum("opens", c7)) +
      tile("مرات الفتح (30 يوماً)", daysum("opens", c30)) + tile("مرات الفتح (الكل)", sum("opens")) +
      `</div><h2>التحديثات</h2><div class="tiles">` +
      tile("تحديثات مثبّتة (30 يوماً)", daysum("upd", c30)) + tile("تحديثات مثبّتة (الكل)", sum("upd")) +
      tile("وصلهم التحديث ولم يثبّتوه", sum("waiting"), "نُزّل في الجهاز وينتظر التثبيت") +
      tile("على إصدارٍ أقدم", behind, "نشطون لم يصلوا إلى أحدث إصدار") +
      `</div><h2>التوقف والحذف</h2><div class="tiles">` +
      tile("توقفوا مؤقتاً", sum("paused"), "لم يفتحوه منذ 7 إلى 30 يوماً", "تقديري") +
      tile("غادروا", sum("gone"), "لم يفتحوه منذ أكثر من 30 يوماً: حذفوه أو تركوه", "تقديري") +
      `</div><h2>الرسوم</h2><div class="grid">` +
      card("c-growth", "نموّ عدد المستخدمين", "إجمالي الأجهزة بمرور الوقت") +
      card("c-active", "المستخدمون النشطون", "أجهزةٌ فتحت التطبيق في الفترة", true) +
      card("c-new", "المستخدمون الجدد", "تثبيتٌ جديد فُتح أول مرة", true) +
      card("c-opens", "مرات فتح التطبيق", "", true) +
      card("c-upd", "التحديثات المثبّتة", "انتقال جهازٍ إلى إصدارٍ أحدث", true) +
      card("c-left", "المغادرون حسب آخر استخدام", "أجهزةٌ لم تفتحه منذ أكثر من 30 يوماً، حسب شهر آخر فتح") +
      `<section class="card"><div class="hd"><h3>الإصدارات لدى الأجهزة النشطة</h3></div><p class="note">آخر 30 يوماً</p>` +
      hbars(D.versions.slice().sort((a, b) => b.n - a.n).map((v) => [`${PLAT[v.plat] || v.plat} · ${v.ver}`, v.n, v.ver === D.latest[v.plat] ? "أحدث إصدار" : "إصدارٌ أقدم"])) +
      table(["المنصة · الإصدار", "أجهزة"], D.versions.slice().sort((a, b) => b.n - a.n).map((v) => [`${PLAT[v.plat] || v.plat} · ${v.ver}`, v.n])) +
      `</section><section class="card"><div class="hd"><h3>المنصات</h3></div><p class="note">كل الأجهزة (والنشطة في 30 يوماً بالجدول)</p>` +
      hbars(P.slice().sort((a, b) => b.n - a.n).map((r) => [PLAT[r.plat] || r.plat, r.n, "نشطة: " + fmt(r.a30)])) +
      table(["المنصة", "كل الأجهزة", "نشطة (30 يوماً)", "جدد (30 يوماً)"], P.map((r) => [PLAT[r.plat] || r.plat, r.n, r.a30 || 0, r.n30 || 0])) +
      `</section><section class="card"><div class="hd"><h3>التحديثات المثبّتة لكل إصدار</h3></div>` +
      hbars(D.updVers.map((u) => ["إلى " + u.v, u.n])) + `</section></div>`;
    charts.length = 0;
    mount("c-growth", () => growth(), "جهاز", "line");
    mount("c-active", (p) => activeSeries(p), "جهاز");
    mount("c-new", (p) => series("new", p), "جهاز");
    mount("c-opens", (p) => series("opens", p), "مرة");
    mount("c-upd", (p) => series("upd", p), "تحديث");
    mount("c-left", () => {
      const by = {};
      for (const r of D.left) by[r.m] = r.n;
      return months().map((m) => ({ k: mshort(m), t: mname(m), v: by[m] || 0 }));
    }, "جهاز");
  }

  async function load() {
    $("#asof").textContent = "جارٍ التحميل…";
    try {
      const r = await fetch("/stats/data", { cache: "no-store", credentials: "same-origin" });
      if (r.status === 401) { location.reload(); return; }
      D = await r.json();
      render();
    } catch (e) {
      $("#asof").textContent = "تعذّر التحميل — تحقّق من الاتصال ثم «تحديث»";
    }
  }
  $("#reload").addEventListener("click", load);
  let rt = 0;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => charts.forEach((f) => f()), 150); });

  const dlg = $("#pwdlg"), msg = $("#pwmsg");
  $("#pwbtn").addEventListener("click", () => { msg.textContent = ""; $("#pwform").reset(); dlg.showModal(); });
  $("#pwcancel").addEventListener("click", () => dlg.close());
  $("#pwform").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    msg.className = ""; msg.textContent = "…";
    try {
      const r = await fetch("/stats/pass", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cur: f.get("cur"), pw: f.get("pw"), pw2: f.get("pw2") }),
      });
      const j = await r.json();
      msg.className = j.ok ? "okm" : "err";
      msg.textContent = j.ok ? "تم الحفظ. الأجهزة الأخرى خرجت من اللوحة." : (j.error || "تعذّر الحفظ");
    } catch (e) { msg.className = "err"; msg.textContent = "تعذّر الاتصال"; }
  });
  load();
})();
