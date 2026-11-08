/* صفحات المستندات للطباعة والمشاركة صورةً: الفاتورة والسند وكشف الحساب.
 * ألوان لوحة النظام الفاتحة نفسها (الورق أبيض)، وخط IBM Plex Sans Arabic.
 */
(function (root) {
  "use strict";
  const { f2 } = root.Num;
  const T = root.I18N.T;
  const G = root.Gold, D = root.Domain;

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dmy = (iso) => iso ? `${iso.slice(8, 10)}-${iso.slice(5, 7)}-${iso.slice(0, 4)}` : "";
  const ltr = (s) => `<span dir="ltr">${esc(s)}</span>`;
  // 1.12: رمزان بجانب الأرقام — سبيكة ذهب بجانب أوزان الذهب، وورقة نقد بجانب النقد والأجور
  const ICO_GOLD = '<svg class="ug" viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">' +
    '<path d="M6.5 8h11l4 9.5h-19z" fill="#E2B93B" stroke="#8A6A12" stroke-width="1.5" stroke-linejoin="round"/>' +
    '<path d="M8.8 10.7h6.4" stroke="#FFF1B8" stroke-width="1.4" stroke-linecap="round"/></svg>';
  const ICO_CASH = '<svg class="uc" viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">' +
    '<rect x="2" y="6.5" width="20" height="11" rx="2" fill="#2F9E5B" stroke="#1C6B3C" stroke-width="1.3"/>' +
    '<circle cx="12" cy="12" r="2.8" fill="none" stroke="#E6F7EC" stroke-width="1.5"/></svg>';
  const gI = (v) => ICO_GOLD + v, cI = (v) => ICO_CASH + v;
  // 1.13: عيار العرض والمكافئ الواحد (يُختار أعلى الرئيسية) — للمستندات كلها
  const vK = (st) => parseInt(st.settings.viewKarat || 18, 10);

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
  svg.ug,svg.uc{vertical-align:-2px;margin-inline-end:3px}
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
  td.m .gl,td.m .cl{display:block;white-space:nowrap}
  td.m .cl{font-size:12px;color:#4A443A;margin-top:2px}
  tr.tot td.m .cl,tr.tot td.m .w,tr.tot td small{color:#E9E2D2}
  td.z{color:#9A9384;text-align:center}
  .legend{font-size:12px;color:#4A443A;margin:-4px 0 8px}
  .sum{grid-template-columns:repeat(2,1fr);gap:8px}
  .box span{font-size:16px}
  `;

  // سطر التعريف بالتطبيق أسفل المستند (يضبطه صاحب التطبيق من GitHub)
  function brand() {
    const t = root.Promo ? root.Promo.footer() : "";
    return t ? `<div class="brand">${esc(t)}</div>` : "";
  }

  function page(title, body, narrow) {
    // بلغة الواجهة واتجاهها — والأنماط مكتوبةٌ للعربية فتُقلب جهاتها للإنجليزية
    const rtl = root.I18N.rtl;
    const css = rtl ? CSS : CSS.replace(/\b(left|right)\b/g, (m) => (m === "left" ? "right" : "left"));
    return `<!doctype html><html lang="${root.I18N.lang}" dir="${rtl ? "rtl" : "ltr"}"><head><meta charset="utf-8">${narrow ? `<!--page-width:${NARROW}-->` : ""}
<base href="${esc(base())}"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title><style>${css}${narrow ? CSS_NARROW : ""}</style></head><body><div class="page">${body}${brand()}</div></body></html>`;
  }

  function header(st, title, no, date) {
    const s = st.settings;
    return `<div class="head"><div><div class="biz">${esc(s.name || APP)}</div>
      ${s.phone ? T("<div class=\"muted\">هاتف: {0}</div>", ltr(s.phone)) : ""}
      ${s.address ? `<div class="muted">${esc(s.address)}</div>` : ""}</div>
      <div><div class="title">${esc(title)}</div>
      ${no ? `<div class="no">${ltr(no)}</div>` : ""}
      <div class="muted" style="text-align:${root.I18N.end}">${ltr(dmy(date))}</div></div></div>`;
  }

  const APP = "ÀUR";
  const INV_TITLE = { sale: T("فاتورة بيع"), sale_return: T("مرتجع"), purchase: T("بضاعة من مصنع"), purchase_return: T("إرجاع للمصنع") };
  const PARTY_WORD = { sale: T("العميل"), sale_return: T("من"), purchase: T("المصنع"), purchase_return: T("إلى") };

  function balTxt(v, unit) {
    if (Math.abs(v) < 0.005) return "0.00";
    return `${f2(Math.abs(v))} ${unit} ${v > 0 ? T("عليه") : T("له")}`;
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
    const shop = D.shopById(st, inv.shopId) || { name: "—" };
    // عيار حساب العميل/المصنع
    const k = vK(st);
    const title = (INV_TITLE[inv.kind] || T("فاتورة")) + (inv.vat ? T(" ضريبية") : "");
    const anyDia = inv.lines.some((l) => l.diamond > 0);
    let rows = "", n = 0;
    for (const li of inv.lines) {
      n++;
      if (li.wageOnly) {
        rows += T("<tr><td>{0}</td><td class=\"t\" colspan=\"{1}\">أجور فقط{2}</td>\n          <td>{3}</td></tr>", n, (anyDia ? 5 : 4) + (anyPh ? 1 : 0), li.note ? " — " + esc(li.note) : "", cI(f2(li.amount)));
        continue;
      }
      const lk = li.karat || 18;
      rows += `<tr><td>${n}</td>${anyPh ? phCell(li) : ""}<td>${li.wo ? `<span dir="auto">${esc(li.wo)}</span>` : "—"}</td>
        <td>${li.reg18 > 0 ? lk : "—"}</td><td>${li.reg18 > 0 ? f2(G.g(li.standing18, lk)) : "—"}</td><td><b>${li.reg18 > 0 ? gI(f2(G.g(li.reg18, lk))) : "—"}</b></td>
        ${anyDia ? `<td>${li.diamond ? f2(li.diamond) : "—"}</td>` : ""}
        <td>${cI(f2(li.wages))}</td></tr>`;
    }
    const sets = inv.lines.filter((l) => !l.wageOnly).length;
    rows += T("<tr class=\"tot\"><td colspan=\"{0}\">الإجمالي — {1} طقم · عيار {2}</td>\n      <td>{3}</td>{4}<td>{5}</td></tr>", anyPh ? 5 : 4, sets, k, gI(f2(G.g(inv.totalW18, k))), anyDia ? `<td>${f2(D.diamondOf(inv))}</td>` : "", cI(f2(inv.wages)));

    let qr = "";
    if (inv.vat && st.settings.vatNo) {
      const ts = `${inv.date}T${(inv.createdAt || "").slice(11, 19) || "00:00:00"}`;
      qr = `<div class="qr">${qrImg(zatcaB64(st.settings.name || "", st.settings.vatNo, ts, inv.grand, inv.vatAmt))}</div>`;
    }
    let bal = "";
    if (st.settings.showBalanceOnInvoice) {
      const { before, after } = D.balanceAround(st, inv);
      bal = T("<div class=\"sum\">\n        <div class=\"box\"><b>رصيد الذهب قبل الفاتورة (عيار {0})</b><span>{1}</span></div>\n        <div class=\"box\"><b>رصيد الذهب بعد الفاتورة (عيار {2})</b><span>{3}</span></div>\n        <div class=\"box\"><b>رصيد الأجور قبل الفاتورة</b><span>{4}</span></div>\n        <div class=\"box\"><b>رصيد الأجور بعد الفاتورة</b><span>{5}</span></div></div>", k, gI(balTxt(G.g(before.gold18, k), T("جم"))), k, gI(balTxt(G.g(after.gold18, k), T("جم"))), cI(balTxt(before.cash, T("ريال"))), cI(balTxt(after.cash, T("ريال"))));
    }
    const body = header(st, title, inv.no, inv.date) +
      T("<div class=\"party\"><div><b>{0}:</b> {1}</div>\n       {2}\n       {3}</div>\n      <table><thead><tr><th>#</th>{4}<th>الطقم</th><th>العيار</th>\n      <th>الوزن القائم</th><th>الوزن</th>{5}<th>الأجور (ريال)</th></tr></thead>\n      <tbody>{6}</tbody></table>\n      {7}<div class=\"sum\">\n        <div class=\"box\"><b>إجمالي الوزن</b><span>{8} جم {9}</span></div>\n        <div class=\"box\"><b>إجمالي الأجور</b><span>{10} ريال</span></div>\n        {11}\n      </div>{12}\n      {13}\n      <div class=\"foot\">{14} · {15}</div>", PARTY_WORD[inv.kind] || T("الحساب"), esc(shop.name), shop.phone ? `<div>${ltr(shop.phone)}</div>` : "", inv.vat && st.settings.vatNo ? T("<div class=\"muted\">الرقم الضريبي: {0}</div>", ltr(st.settings.vatNo)) : "", anyPh ? T("<th>الصورة</th>") : "", anyDia ? T("<th>💎 الماس (جم)</th>") : "", rows, qr, gI(f2(G.g(inv.totalW18, k))), k, cI(f2(inv.wages)), inv.vat ? T("<div class=\"box\"><b>ضريبة القيمة المضافة 15%</b><span>{0} ريال</span></div>\n        <div class=\"box\"><b>الإجمالي شامل الضريبة</b><span>{1} ريال</span></div>", cI(f2(inv.vatAmt)), cI(f2(inv.grand))) : "", bal, inv.desc ? T("<div class=\"note\">البيان: {0}</div>", esc(inv.desc)) : "", esc(st.settings.name || APP), ltr(inv.no));
    return page(`${title} ${inv.no}`, body);
  }

  function voucherHtml(st, v) {
    const shop = D.shopById(st, v.shopId) || { name: "—" };
    // عيار حساب العميل/المصنع
    const k = vK(st);
    const title = v.kind === "receipt" ? T("سند تحصيل") : D.isFactory(shop) ? T("سند سداد للمصنع") : T("سند صرف");
    let rows = "", n = 0;
    for (const r of v.rows) {
      n++;
      rows += r.kind === "gold"
        ? T("<tr><td>{0}</td><td>ذهب</td><td>{1} جم عيار {2}</td>\n           <td>{3} جم عيار {5}</td><td>—</td><td class=\"t\">{4}</td></tr>", n, gI(f2(r.weight)), r.karat, f2(G.g(r.equiv, k)), esc(r.notes), k)
        : T("<tr><td>{0}</td><td>نقد</td><td>—</td><td>—</td><td>{1}</td><td class=\"t\">{2}</td></tr>", n, cI(f2(r.amount)), esc(r.notes));
    }
    if (v.discGold18) rows += T("<tr><td>—</td><td>خصم مسموح وزناً</td><td>—</td><td>{0} جم عيار {1}</td><td>—</td><td></td></tr>", f2(G.g(v.discGold18, k)), k);
    if (v.discCash) rows += T("<tr><td>—</td><td>خصم مسموح نقداً</td><td>—</td><td>—</td><td>{0}</td><td></td></tr>", f2(v.discCash));
    if (v.netDiff) rows += T("<tr><td>—</td><td>فرق الصافي</td><td>—</td><td>—</td><td>{0}</td><td></td></tr>", f2(v.netDiff, { sign: true }));
    rows += T("<tr class=\"tot\"><td colspan=\"3\">الإجمالي</td><td>{0} جم عيار {2}</td><td>{1}</td><td></td></tr>", gI(f2(G.g(v.gold18, k))), cI(f2(v.cash)), k);
    const { after } = D.balanceAround(st, v);
    const body = header(st, title, v.no, v.date) +
      T("<div class=\"party\"><div><b>{0}:</b> {1}</div>\n       {2}</div>\n      <table><thead><tr><th>#</th><th>النوع</th><th>الوزن الفعلي</th><th>المكافئ</th><th>النقد (ريال)</th><th>البيان</th></tr></thead>\n      <tbody>{3}</tbody></table>\n      <div class=\"sum\"><div class=\"box\"><b>رصيد الذهب بعد السند (عيار {4})</b><span>{5}</span></div>\n      <div class=\"box\"><b>رصيد النقد بعد السند</b><span>{6}</span></div></div>\n      {7}\n      <div class=\"foot\">{8} · {9}</div>", v.kind === "receipt" ? T("من") : T("إلى"), esc(shop.name), shop.phone ? `<div>${ltr(shop.phone)}</div>` : "", rows, k, gI(balTxt(G.g(after.gold18, k), T("جم"))), cI(balTxt(after.cash, T("ريال"))), v.notes ? T("<div class=\"note\">البيان: {0}</div>", esc(v.notes)) : "", esc(st.settings.name || APP), ltr(v.no));
    return page(`${title} ${v.no}`, body);
  }

  // كشف الحساب بعرض الجوال: «gold» الذهب والنقد، أو «diamond» الماس
  function statementHtml(st, shopId, from, to, mode, filter) {
    const shop = D.shopById(st, shopId) || { name: "—" };
    // عيار حساب العميل/المصنع
    const k = vK(st);
    const fac = D.isFactory(shop);
    const period = from || to ? T("من {0} إلى {1}", from ? dmy(from) : T("البداية"), to ? dmy(to) : T("اليوم")) : T("كل الفترات");
    const sgn = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + f2(Math.abs(v));
    const op = (r) => `${esc(T(r.label))}${r.no ? `<small>${ltr(r.no)}</small>` : ""}${r.desc ? `<small>${esc(r.desc)}</small>` : ""}`;
    // التاريخ يوماً وشهراً، والسنة تحته — فيتّسع الجدول لعرض الجوال
    const dt = (iso) => iso ? `${ltr(iso.slice(8, 10) + "-" + iso.slice(5, 7))}<small>${iso.slice(0, 4)}</small>` : "";
    // الحركة فوق، والرصيد بعدها في الخانة نفسها
    const cell = (mv, bal, word) => `<td class="m">${mv ? `<span class="mv" dir="ltr">${mv}</span>` : ""}<b>${bal}</b>${word ? `<span class="w">${word}</span>` : ""}</td>`;
    const partyRow = `<div class="party"><div><b>${fac ? T("المصنع") : T("العميل")}:</b> ${esc(shop.name)}</div>
      <div class="muted">${period}${mode === "diamond" ? T(" · الماس بالجرام") : T(" · الذهب بعيار {0}", k)}</div></div>`;
    let body;
    if (mode === "diamond") {
      const s = D.diamondStatement(st, shopId, from, to);
      // للمصنع: البضاعة «+» والإرجاع «−» — من جهته
      const f = fac ? -1 : 1;
      let rows = "";
      for (const r of s.rows) {
        const v = f * (r.dd - r.dc);
        const sets = r.sets.map((x) => `${x.name ? esc(x.name) : T("طقم")} (${f2(x.diamond)})`).join(T("، "));
        rows += `<tr><td class="d">${dt(r.date)}</td><td class="t">${op(r)}</td><td class="t">${sets || "—"}</td>
          ${cell(r.kind === "prev" ? "" : sgn(v), f2(f * r.bal), "")}</tr>`;
      }
      body = header(st, T("كشف حساب الماس"), "", to || D.today()) + partyRow +
        T("<table><thead><tr><th>التاريخ</th><th>العملية</th><th>الأطقم (الماس)</th><th>الماس (جم)<small>الحركة · الصافي</small></th></tr></thead>\n        <tbody>{0}</tbody></table>\n        <div class=\"sum\">\n          <div class=\"box\"><b>{1}</b><span>{2} جم</span></div>\n          <div class=\"box\"><b>{3}</b><span>{4} جم</span></div>\n          <div class=\"box\" style=\"grid-column:span 2\"><b>صافي الماس</b><span>{5} جم</span></div></div>\n        <div class=\"note\">الماس للعرض والمعرفة: لا يدخل الوزن ولا رصيد الذهب.</div>", rows || T("<tr><td colspan=\"4\">لا ماس في الفترة</td></tr>"), fac ? T("البضاعة") : T("المبيعات"), f2(fac ? s.minus : s.plus), fac ? T("الإرجاع") : T("المرتجع"), f2(fac ? s.plus : s.minus), f2(f * s.diamond));
    } else {
      // «عليه · له · الرصيد» (1.11): الذهب فوق والنقد تحته في كل خانة، ثم صفّ
      // الإجمالي: مجموع ما عليه، ومجموع ما له، والباقي — والفرز نوعٌ واحدٌ ومجموعه
      const s = D.statementView(st, shopId, from, to, filter);
      const fl = s.filter ? filterLabel(fac, s.filter) : "";
      const word = (v, eps) => (Math.abs(v) < eps ? "" : v > 0 ? T("عليه") : T("له"));
      const amt = (g18, c) => {
        const gv = G.g(g18, k);
        if (Math.abs(gv) < 0.005 && Math.abs(c) < 0.005) return `<td class="z">—</td>`;
        return `<td class="m"><span class="gl"><b>${Math.abs(gv) < 0.005 ? "—" : gI(f2(gv))}</b></span><span class="cl">${Math.abs(c) < 0.005 ? "—" : cI(f2(c))}</span></td>`;
      };
      const balc = (g18, c, cum) => {
        const gv = G.g(g18, k);
        const wg = cum ? "" : word(gv, 0.005), wc = cum ? "" : word(c, 0.005);
        return `<td class="m"><span class="gl"><b>${gI(f2(Math.abs(gv)))}</b>${wg ? `<span class="w">${wg}</span>` : ""}</span>` +
          `<span class="cl">${cI(f2(Math.abs(c)))}${wc ? `<span class="w">${wc}</span>` : ""}</span></td>`;
      };
      let rows = "";
      for (const r of s.rows) {
        rows += `<tr><td class="d">${dt(r.date)}</td><td class="t">${op(r)}</td>${amt(r.gd, r.cd)}${amt(r.gc, r.cc)}${balc(r.gbal, r.cbal, !!s.filter)}</tr>`;
      }
      const t = s.totals;
      if (s.rows.length) {
        rows += `<tr class="tot"><td colspan="2">${s.filter ? T("إجمالي {0}", fl) : T("الإجمالي")}<small>${s.filter ? T("{0} عملية", s.rows.length) : T("عليه − له = الباقي")}</small></td>` +
          `${amt(t.gd, t.cd)}${amt(t.gc, t.cc)}${balc(t.gbal, t.cbal, !!s.filter)}</tr>`;
      }
      const sums = s.filter
        ? T("<div class=\"sum\"><div class=\"box\"><b>إجمالي {0} ذهباً (عيار {1})</b><span>{2} جم</span></div>\n        <div class=\"box\"><b>إجمالي {3} نقداً</b><span>{4} ريال</span></div></div>", fl, k, gI(f2(Math.abs(G.g(t.gbal, k)))), fl, cI(f2(Math.abs(t.cbal))))
        : T("<div class=\"sum\"><div class=\"box\"><b>رصيد الذهب (عيار {0})</b><span>{1}</span></div>\n        <div class=\"box\"><b>رصيد النقد</b><span>{2}</span></div></div>", k, gI(balTxt(G.g(s.gold18, k), T("جم"))), cI(balTxt(s.cash, T("ريال"))));
      body = header(st, s.filter ? T("كشف حساب — {0}", fl) : T("كشف حساب"), "", to || D.today()) + partyRow +
        `<div class="legend">${T("في كل خانة: {0} الذهب (جم عيار {1}) فوق، و{2} النقد والأجور (ريال) تحته.", ICO_GOLD, k, ICO_CASH)}</div>` +
        T("<table><thead><tr><th>التاريخ</th><th>العملية</th><th>عليه</th><th>له</th><th>{0}</th></tr></thead>\n        <tbody>{1}</tbody></table>", s.filter ? T("المجموع") : T("الرصيد"), rows || T("<tr><td colspan=\"5\">لا حركة في الفترة</td></tr>")) + sums;
    }
    body += T("<div class=\"foot\">{0} · كشف حساب {1}</div>", esc(st.settings.name || APP), esc(shop.name));
    return page(T("كشف حساب {0}", shop.name), body, true);
  }

  // اسم الفرز: للعميل المبيعات · المرتجعات · التحصيل، وللمصنع البضاعة · الإرجاع · السداد
  function filterLabel(fac, f) {
    const m = fac ? { sales: T("البضاعة"), returns: T("الإرجاع"), collect: T("السداد") }
      : { sales: T("المبيعات"), returns: T("المرتجعات"), collect: T("التحصيل") };
    return m[f] || T("الكل");
  }

  // نصٌّ قصير للمشاركة في واتساب
  function invoiceText(st, inv) {
    const shop = D.shopById(st, inv.shopId) || { name: "" };
    // عيار حساب العميل/المصنع
    const k = vK(st);
    const { after } = D.balanceAround(st, inv);
    return [`${INV_TITLE[inv.kind] || T("فاتورة")} ${inv.no} — ${dmy(inv.date)}`,
      `${shop.name}`,
      T("الوزن: {0} جم عيار {1}", f2(G.g(inv.totalW18, k)), k),
      T("الأجور: {0} ريال", f2(inv.wages)) + (inv.vat ? T(" + ضريبة {0} = {1}", f2(inv.vatAmt), f2(inv.grand)) : ""),
      T("الرصيد بعدها: ذهب {0} · أجور {1}", balTxt(G.g(after.gold18, k), T("جم")), balTxt(after.cash, T("ريال"))),
    ].join("\n");
  }

  root.PrintDoc = { invoiceHtml, voucherHtml, statementHtml, filterLabel, invoiceText, zatcaB64, balTxt, dmy, ICO_GOLD, ICO_CASH };
})(window);
