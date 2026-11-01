/* صفحات المستندات للطباعة والمشاركة صورةً: الفاتورة والسند وكشف الحساب.
 * ألوان لوحة النظام الفاتحة نفسها (الورق أبيض)، وخط IBM Plex Sans Arabic.
 */
(function (root) {
  "use strict";
  const { f2 } = root.Num;
  const G = root.Gold, D = root.Domain;

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dmy = (iso) => iso ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : "";
  const ltr = (s) => `<span dir="ltr">${esc(s)}</span>`;

  function base() {
    try { return location.href.replace(/[^/]*([?#].*)?$/, ""); } catch (e) { return ""; }
  }

  const CSS = `
  @font-face{font-family:Plex;src:url(fonts/IBMPlexSansArabic-Regular.ttf)}
  @font-face{font-family:Plex;font-weight:600;src:url(fonts/IBMPlexSansArabic-SemiBold.ttf)}
  @font-face{font-family:Plex;font-weight:700;src:url(fonts/IBMPlexSansArabic-Bold.ttf)}
  *{box-sizing:border-box}
  body{margin:0;background:#FFFFFF;color:#0B0907;font-family:Plex,sans-serif;font-size:15px}
  .page{width:100%;max-width:1000px;margin:0 auto;padding:28px 30px}
  .head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
    border-bottom:3px solid #9A7B22;padding-bottom:12px;margin-bottom:14px}
  .biz{font-size:22px;font-weight:700;color:#5E4A0C}
  .muted{color:#4A443A;font-size:13px}
  .title{font-size:20px;font-weight:700;text-align:left}
  .no{font-size:15px;font-weight:600;text-align:left}
  .party{background:#FAF8F3;border:1px solid #E3DDD0;border-radius:10px;padding:10px 14px;
    display:flex;justify-content:space-between;margin-bottom:14px;gap:10px}
  table{width:100%;border-collapse:collapse;margin-bottom:14px}
  th{background:#F1ECE0;color:#1E1A14;font-weight:600;font-size:13px;padding:7px 5px;
    border:1px solid #D8CDB4}
  td{padding:6px 5px;border:1px solid #E3DDD0;text-align:center;font-size:14px}
  td.t{text-align:right}
  tr.tot td{background:#1C1A17;color:#FFFFFF;font-weight:700}
  thead{display:table-header-group} tr{break-inside:avoid}
  .sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:14px}
  .box{border:1px solid #E6C68A;background:#FDF3E2;border-radius:10px;padding:9px 12px}
  .box b{display:block;font-size:13px;color:#5A3806}
  .box span{font-size:19px;font-weight:700}
  .note{border-top:1px dashed #D6CFC0;padding-top:8px;color:#4A443A;font-size:13px}
  .qr{float:left;margin-right:12px}
  .foot{margin-top:18px;color:#4A443A;font-size:12px;text-align:center}
  td.ph{padding:3px;width:66px}
  td.ph img{width:60px;height:60px;object-fit:cover;border-radius:6px;display:block;margin:0 auto}
  td.ph .phs{display:grid;grid-template-columns:repeat(2,30px);gap:3px;justify-content:center}
  td.ph .phs img{width:30px;height:30px;border-radius:4px}
  .brand{margin-top:10px;text-align:center;color:#7C7566;font-size:11px}
  @page{size:A4;margin:10mm}
  `;
  // صفحةٌ بعرض الجوال (كشف الحساب): تُقرأ في المعاينة كما هي، وتُلتقط صورةً
  // بعرضها (`page-width` يقرؤه التطبيق عند التقاط الصورة)
  const NARROW = 720;
  const CSS_NARROW = `
  .page{max-width:${NARROW}px;padding:16px 14px}
  .head{gap:10px;padding-bottom:10px;margin-bottom:10px}
  .biz{font-size:18px} .title{font-size:17px}
  .party{padding:8px 10px;margin-bottom:10px;flex-wrap:wrap}
  th{font-size:12px;padding:6px 3px} th small{display:block;font-weight:400;font-size:10.5px;color:#4A443A}
  td{font-size:13px;padding:6px 3px}
  td small{display:block;color:#4A443A;font-size:11px;font-weight:400}
  td.d{white-space:nowrap;font-size:12px}
  td.m{white-space:nowrap}
  td.m .mv{display:block;font-size:12px;color:#4A443A}
  td.m b{display:inline-block;font-size:14px}
  td.m .w{font-size:11px;color:#4A443A;margin-inline-start:3px}
  .sum{grid-template-columns:repeat(2,1fr);gap:8px}
  .box span{font-size:16px}
  `;

  // سطر التعريف بالتطبيق أسفل المستند (يضبطه صاحب التطبيق من GitHub)
  function brand() {
    const t = root.Promo ? root.Promo.footer() : "";
    return t ? `<div class="brand">${esc(t)}</div>` : "";
  }

  function page(title, body, narrow) {
    return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">${narrow ? `<!--page-width:${NARROW}-->` : ""}
<base href="${esc(base())}"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><style>${CSS}${narrow ? CSS_NARROW : ""}</style></head><body><div class="page">${body}${brand()}</div></body></html>`;
  }

  function header(st, title, no, date) {
    const s = st.settings;
    return `<div class="head"><div><div class="biz">${esc(s.name || APP)}</div>
      ${s.phone ? `<div class="muted">هاتف: ${ltr(s.phone)}</div>` : ""}
      ${s.address ? `<div class="muted">${esc(s.address)}</div>` : ""}</div>
      <div><div class="title">${esc(title)}</div>
      ${no ? `<div class="no">${ltr(no)}</div>` : ""}
      <div class="muted" style="text-align:left">${ltr(dmy(date))}</div></div></div>`;
  }

  const APP = "نظام محاسبي للذهب";
  const INV_TITLE = { sale: "فاتورة بيع", sale_return: "مرتجع", purchase: "بضاعة من مصنع", purchase_return: "إرجاع للمصنع" };
  const PARTY_WORD = { sale: "العميل", sale_return: "من", purchase: "المصنع", purchase_return: "إلى" };

  function balTxt(v, unit) {
    if (Math.abs(v) < 0.005) return "0.00";
    return `${f2(Math.abs(v))} ${unit} ${v > 0 ? "عليه" : "له"}`;
  }

  // ══ رمز QR الضريبي (المرحلة الأولى) — كـ`services/zatca.py` ══
  function tlv(tag, value) {
    const b = new TextEncoder().encode(String(value));
    return [tag, b.length, ...b];
  }
  function zatcaB64(name, vatNo, ts, total, vat) {
    const bytes = [...tlv(1, name), ...tlv(2, vatNo), ...tlv(3, ts),
      ...tlv(4, Number(total).toFixed(2)), ...tlv(5, Number(vat).toFixed(2))];
    let bin = "";
    for (const x of bytes) bin += String.fromCharCode(x);
    return btoa(bin);
  }
  function qrImg(text) {
    if (!root.qrcode) return "";
    const q = root.qrcode(0, "M");
    q.addData(text);
    q.make();
    return q.createImgTag(3, 8);
  }

  function invoiceHtml(st, inv, photos) {
    const ph = photos || {};
    // صور السطر (واحدةٌ أو أكثر) — ما وُجد منها
    const linePh = (l) => D.linePhotos(l).filter((id) => ph[id]);
    const anyPh = inv.lines.some((l) => linePh(l).length);
    const phCell = (l) => {
      const ids = linePh(l);
      if (!ids.length) return `<td class="ph"></td>`;
      if (ids.length === 1) return `<td class="ph"><img src="${ph[ids[0]]}" alt=""></td>`;
      return `<td class="ph"><div class="phs">${ids.slice(0, 4).map((id) => `<img src="${ph[id]}" alt="">`).join("")}</div>${ids.length > 4 ? `<small>+${ids.length - 4}</small>` : ""}</td>`;
    };
    const k = st.settings.viewKarat || 18;
    const shop = D.shopById(st, inv.shopId) || { name: "—" };
    const title = (INV_TITLE[inv.kind] || "فاتورة") + (inv.vat ? " ضريبية" : "");
    const anyDia = inv.lines.some((l) => l.diamond > 0);
    let rows = "", n = 0;
    for (const li of inv.lines) {
      n++;
      if (li.wageOnly) {
        rows += `<tr><td>${n}</td><td class="t" colspan="${(anyDia ? 5 : 4) + (anyPh ? 1 : 0)}">أجور فقط${li.note ? " — " + esc(li.note) : ""}</td>
          <td>${f2(li.amount)}</td></tr>`;
        continue;
      }
      const lk = li.karat || 18;
      rows += `<tr><td>${n}</td>${anyPh ? phCell(li) : ""}<td>${li.wo ? `<span dir="auto">${esc(li.wo)}</span>` : "—"}</td>
        <td>${li.reg18 > 0 ? lk : "—"}</td><td>${li.reg18 > 0 ? f2(G.g(li.standing18, lk)) : "—"}</td><td><b>${li.reg18 > 0 ? f2(G.g(li.reg18, lk)) : "—"}</b></td>
        ${anyDia ? `<td>${li.diamond ? f2(li.diamond) : "—"}</td>` : ""}
        <td>${f2(li.wages)}</td></tr>`;
    }
    const sets = inv.lines.filter((l) => !l.wageOnly).length;
    rows += `<tr class="tot"><td colspan="${anyPh ? 5 : 4}">الإجمالي — ${sets} طقم · عيار ${k}</td>
      <td>${f2(G.g(inv.totalW18, k))}</td>${anyDia ? `<td>${f2(D.diamondOf(inv))}</td>` : ""}<td>${f2(inv.wages)}</td></tr>`;

    let qr = "";
    if (inv.vat && st.settings.vatNo) {
      const ts = `${inv.date}T${(inv.createdAt || "").slice(11, 19) || "00:00:00"}`;
      qr = `<div class="qr">${qrImg(zatcaB64(st.settings.name || "", st.settings.vatNo, ts, inv.grand, inv.vatAmt))}</div>`;
    }
    let bal = "";
    if (st.settings.showBalanceOnInvoice) {
      const { before, after } = D.balanceAround(st, inv);
      bal = `<div class="sum">
        <div class="box"><b>رصيد الذهب قبل الفاتورة (عيار ${k})</b><span>${balTxt(G.g(before.gold18, k), "جم")}</span></div>
        <div class="box"><b>رصيد الذهب بعد الفاتورة (عيار ${k})</b><span>${balTxt(G.g(after.gold18, k), "جم")}</span></div>
        <div class="box"><b>رصيد الأجور قبل الفاتورة</b><span>${balTxt(before.cash, "ريال")}</span></div>
        <div class="box"><b>رصيد الأجور بعد الفاتورة</b><span>${balTxt(after.cash, "ريال")}</span></div></div>`;
    }
    const body = header(st, title, inv.no, inv.date) +
      `<div class="party"><div><b>${PARTY_WORD[inv.kind] || "الحساب"}:</b> ${esc(shop.name)}</div>
       ${shop.phone ? `<div>${ltr(shop.phone)}</div>` : ""}
       ${inv.vat && st.settings.vatNo ? `<div class="muted">الرقم الضريبي: ${ltr(st.settings.vatNo)}</div>` : ""}</div>
      <table><thead><tr><th>#</th>${anyPh ? "<th>الصورة</th>" : ""}<th>الطقم</th><th>العيار</th>
      <th>الوزن القائم</th><th>الوزن</th>${anyDia ? "<th>💎 الماس (جم)</th>" : ""}<th>الأجور (ريال)</th></tr></thead>
      <tbody>${rows}</tbody></table>
      ${qr}<div class="sum">
        <div class="box"><b>إجمالي الوزن</b><span>${f2(G.g(inv.totalW18, k))} جم ${k}</span></div>
        <div class="box"><b>إجمالي الأجور</b><span>${f2(inv.wages)} ريال</span></div>
        ${inv.vat ? `<div class="box"><b>ضريبة القيمة المضافة 15%</b><span>${f2(inv.vatAmt)} ريال</span></div>
        <div class="box"><b>الإجمالي شامل الضريبة</b><span>${f2(inv.grand)} ريال</span></div>` : ""}
      </div>${bal}
      ${inv.desc ? `<div class="note">البيان: ${esc(inv.desc)}</div>` : ""}
      <div class="foot">${esc(st.settings.name || APP)} · ${ltr(inv.no)}</div>`;
    return page(`${title} ${inv.no}`, body);
  }

  function voucherHtml(st, v) {
    const k = st.settings.viewKarat || 18;
    const shop = D.shopById(st, v.shopId) || { name: "—" };
    const title = v.kind === "receipt" ? "سند تحصيل" : D.isFactory(shop) ? "سند سداد للمصنع" : "سند صرف";
    let rows = "", n = 0;
    for (const r of v.rows) {
      n++;
      rows += r.kind === "gold"
        ? `<tr><td>${n}</td><td>ذهب</td><td>${f2(r.weight)} جم عيار ${r.karat}</td>
           <td>${f2(r.equiv)} جم عيار 18</td><td>—</td><td class="t">${esc(r.notes)}</td></tr>`
        : `<tr><td>${n}</td><td>نقد</td><td>—</td><td>—</td><td>${f2(r.amount)}</td><td class="t">${esc(r.notes)}</td></tr>`;
    }
    if (v.discGold18) rows += `<tr><td>—</td><td>خصم مسموح وزناً</td><td>—</td><td>${f2(v.discGold18)} جم عيار 18</td><td>—</td><td></td></tr>`;
    if (v.discCash) rows += `<tr><td>—</td><td>خصم مسموح نقداً</td><td>—</td><td>—</td><td>${f2(v.discCash)}</td><td></td></tr>`;
    if (v.netDiff) rows += `<tr><td>—</td><td>فرق الصافي</td><td>—</td><td>—</td><td>${f2(v.netDiff, { sign: true })}</td><td></td></tr>`;
    rows += `<tr class="tot"><td colspan="3">الإجمالي</td><td>${f2(v.gold18)} جم عيار 18</td><td>${f2(v.cash)}</td><td></td></tr>`;
    const { after } = D.balanceAround(st, v);
    const body = header(st, title, v.no, v.date) +
      `<div class="party"><div><b>${v.kind === "receipt" ? "من" : "إلى"}:</b> ${esc(shop.name)}</div>
       ${shop.phone ? `<div>${ltr(shop.phone)}</div>` : ""}</div>
      <table><thead><tr><th>#</th><th>النوع</th><th>الوزن الفعلي</th><th>المكافئ</th><th>النقد (ريال)</th><th>البيان</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="sum"><div class="box"><b>رصيد الذهب بعد السند (عيار ${k})</b><span>${balTxt(G.g(after.gold18, k), "جم")}</span></div>
      <div class="box"><b>رصيد النقد بعد السند</b><span>${balTxt(after.cash, "ريال")}</span></div></div>
      ${v.notes ? `<div class="note">البيان: ${esc(v.notes)}</div>` : ""}
      <div class="foot">${esc(st.settings.name || APP)} · ${ltr(v.no)}</div>`;
    return page(`${title} ${v.no}`, body);
  }

  // كشف الحساب بعرض الجوال: «gold» الذهب والنقد، أو «diamond» الماس
  function statementHtml(st, shopId, from, to, mode) {
    const k = st.settings.viewKarat || 18;
    const shop = D.shopById(st, shopId) || { name: "—" };
    const fac = D.isFactory(shop);
    const period = from || to ? `من ${from ? dmy(from) : "البداية"} إلى ${to ? dmy(to) : "اليوم"}` : "كل الفترات";
    const sgn = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + f2(Math.abs(v));
    const op = (r) => `${esc(r.label)}${r.no ? `<small>${ltr(r.no)}</small>` : ""}${r.desc ? `<small>${esc(r.desc)}</small>` : ""}`;
    // التاريخ يوماً وشهراً، والسنة تحته — فيتّسع الجدول لعرض الجوال
    const dt = (iso) => iso ? `${ltr(iso.slice(8, 10) + "-" + iso.slice(5, 7))}<small>${iso.slice(0, 4)}</small>` : "";
    // الحركة فوق، والرصيد بعدها في الخانة نفسها
    const cell = (mv, bal, word) => `<td class="m">${mv ? `<span class="mv" dir="ltr">${mv}</span>` : ""}<b>${bal}</b>${word ? `<span class="w">${word}</span>` : ""}</td>`;
    const partyRow = `<div class="party"><div><b>${fac ? "المصنع" : "المحل"}:</b> ${esc(shop.name)}</div>
      <div class="muted">${period}${mode === "diamond" ? " · الماس بالجرام" : ` · الذهب بعيار ${k}`}</div></div>`;
    let body;
    if (mode === "diamond") {
      const s = D.diamondStatement(st, shopId, from, to);
      // للمصنع: البضاعة «+» والإرجاع «−» — من جهته
      const f = fac ? -1 : 1;
      let rows = "";
      for (const r of s.rows) {
        const v = f * (r.dd - r.dc);
        const sets = r.sets.map((x) => `${x.name ? esc(x.name) : "طقم"} (${f2(x.diamond)})`).join("، ");
        rows += `<tr><td class="d">${dt(r.date)}</td><td class="t">${op(r)}</td><td class="t">${sets || "—"}</td>
          ${cell(r.kind === "prev" ? "" : sgn(v), f2(f * r.bal), "")}</tr>`;
      }
      body = header(st, "كشف حساب الماس", "", to || D.today()) + partyRow +
        `<table><thead><tr><th>التاريخ</th><th>العملية</th><th>الأطقم (الماس)</th><th>الماس (جم)<small>الحركة · الصافي</small></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="4">لا ماس في الفترة</td></tr>`}</tbody></table>
        <div class="sum">
          <div class="box"><b>${fac ? "البضاعة" : "المبيعات"}</b><span>${f2(fac ? s.minus : s.plus)} جم</span></div>
          <div class="box"><b>${fac ? "الإرجاع" : "المرتجع"}</b><span>${f2(fac ? s.plus : s.minus)} جم</span></div>
          <div class="box" style="grid-column:span 2"><b>صافي الماس</b><span>${f2(f * s.diamond)} جم</span></div></div>
        <div class="note">الماس للعرض والمعرفة: لا يدخل الوزن ولا رصيد الذهب.</div>`;
    } else {
      const s = D.statement(st, shopId, from, to);
      let rows = "";
      for (const r of s.rows) {
        const gv = G.g(r.gd - r.gc, k), cv = r.cd - r.cc;
        rows += `<tr><td class="d">${dt(r.date)}</td><td class="t">${op(r)}</td>
          ${cell(r.kind === "prev" || !gv ? "" : sgn(gv), f2(Math.abs(G.g(r.gbal, k))), Math.abs(r.gbal) < 0.0005 ? "" : r.gbal > 0 ? "عليه" : "له")}
          ${cell(r.kind === "prev" || !cv ? "" : sgn(cv), f2(Math.abs(r.cbal)), Math.abs(r.cbal) < 0.005 ? "" : r.cbal > 0 ? "عليه" : "له")}</tr>`;
      }
      body = header(st, "كشف حساب", "", to || D.today()) + partyRow +
        `<table><thead><tr><th>التاريخ</th><th>العملية</th><th>الذهب (جم ${k})<small>الحركة · الرصيد</small></th><th>النقد (ريال)<small>الحركة · الرصيد</small></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="4">لا حركة في الفترة</td></tr>`}</tbody></table>
        <div class="sum"><div class="box"><b>رصيد الذهب (عيار ${k})</b><span>${balTxt(G.g(s.gold18, k), "جم")}</span></div>
        <div class="box"><b>رصيد النقد</b><span>${balTxt(s.cash, "ريال")}</span></div></div>`;
    }
    body += `<div class="foot">${esc(st.settings.name || APP)} · كشف حساب ${esc(shop.name)}</div>`;
    return page(`كشف حساب ${shop.name}`, body, true);
  }

  // نصٌّ قصير للمشاركة في واتساب
  function invoiceText(st, inv) {
    const k = st.settings.viewKarat || 18;
    const shop = D.shopById(st, inv.shopId) || { name: "" };
    const { after } = D.balanceAround(st, inv);
    return [`${INV_TITLE[inv.kind] || "فاتورة"} ${inv.no} — ${dmy(inv.date)}`,
      `${shop.name}`,
      `الوزن: ${f2(G.g(inv.totalW18, k))} جم عيار ${k}`,
      `الأجور: ${f2(inv.wages)} ريال` + (inv.vat ? ` + ضريبة ${f2(inv.vatAmt)} = ${f2(inv.grand)}` : ""),
      `الرصيد بعدها: ذهب ${balTxt(G.g(after.gold18, k), "جم")} · أجور ${balTxt(after.cash, "ريال")}`,
    ].join("\n");
  }

  root.PrintDoc = { invoiceHtml, voucherHtml, statementHtml, invoiceText, zatcaB64, balTxt, dmy };
})(window);
