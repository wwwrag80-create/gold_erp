// التطبيق بالإنجليزية — English mode end to end, in a phone-sized browser.
//   node mobile/tests/e2e_en.js [SHOTS_DIR]
// Builds a little data through the English screens, then opens every screen and fails on any
// Arabic text left over (names here are English, so any Arabic is a missing translation), on a
// page wider than the phone, and on layout not flipped to left-to-right. Then switches back to
// Arabic from Settings.
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const WEB = path.join(__dirname, "../web");
const SHOTS = process.argv[2] || "";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css", ".ttf": "font/ttf", ".json": "application/json", ".png": "image/png" };
function serve() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/") p = "/index.html";
      const f = path.join(WEB, p);
      if (!f.startsWith(WEB) || !fs.existsSync(f)) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(f)] || "application/octet-stream" });
      fs.createReadStream(f).pipe(res);
    });
    srv.listen(0, "127.0.0.1", () => resolve(srv));
  });
}
let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log("  ✔", name); }
  else { fail++; console.log("  ✘", name, detail === undefined ? "" : "— " + detail); }
}

(async () => {
  const srv = await serve();
  const url = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 393, height: 851 }, deviceScaleFactor: 2,
    hasTouch: true, isMobile: true, locale: "en" });
  await ctx.addInitScript(() => { try { if (!localStorage.getItem("aur.lang")) localStorage.setItem("aur.lang", "en"); } catch (e) { /* */ } });
  await ctx.route("https://raw.githubusercontent.com/**", (r) => r.fulfill({ status: 404, body: "" }));
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let n = 0;
  const shot = async (name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${String(++n).padStart(2, "0")}_${name}.png`), fullPage: true }); };
  const tap = (sel) => page.locator(sel).first().click();
  const fill = async (label, value) => {
    const f = page.locator("label.f", { hasText: label }).first().locator("input,select").first();
    await f.fill(String(value));
    await f.dispatchEvent("input");
  };
  const confirm = async (t) => { await page.locator(".sheet .btn", { hasText: t }).first().click(); };
  // Arabic left on screen: text, placeholders, labels — and translations the page asked for and missed
  const arabic = () => page.evaluate(() => {
    const AR = /[؀-ۿ]/;
    const out = new Set();
    const roots = [document.getElementById("bar"), document.getElementById("view"), document.getElementById("sheet-root"), document.getElementById("tabs")];
    for (const r of roots) {
      if (!r) continue;
      const w = document.createTreeWalker(r, NodeFilter.SHOW_TEXT);
      // «العربية» اسم اللغة في زرّ التبديل نفسه — مقصود
      while (w.nextNode()) { const t = w.currentNode.nodeValue.trim(); if (t && AR.test(t) && t !== "العربية") out.add(t); }
      r.querySelectorAll("[placeholder],[aria-label],[title],[alt]").forEach((el) => {
        for (const a of ["placeholder", "aria-label", "title", "alt"]) { const v = el.getAttribute(a); if (v && AR.test(v)) out.add(a + ": " + v); }
      });
      r.querySelectorAll("iframe").forEach((f) => { const d = f.srcdoc || ""; const m = d.replace(/<style[\s\S]*?<\/style>/g, "").replace(/<[^>]+>/g, " ").match(/[^\s<>]*[؀-ۿ][^<>]{0,30}/g); if (m) m.forEach((x) => out.add("print: " + x.trim())); });
    }
    return [...out];
  });
  const missing = () => page.evaluate(() => [...I18N.missing]);
  const wide = () => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  const screen = async (name, hash, after) => {
    if (hash !== null) { await page.goto(url + "#/" + hash); }
    await page.waitForTimeout(450);
    if (after) await after();
    const ar = await arabic();
    check(`${name}: no Arabic left`, !ar.length, ar.slice(0, 6).join(" | "));
    const w = await wide();
    check(`${name}: fits the phone width`, w <= 1, `${w}px wider`);
    await shot(name);
  };

  await page.goto(url);
  await page.waitForSelector("#tabs");
  check("English: <html lang=en dir=ltr>", await page.evaluate(() => document.documentElement.lang === "en" && document.documentElement.dir === "ltr"));
  check("Tabs in English", (await page.locator("#tabs").innerText()).includes("Holdings") && (await page.locator("#tabs").innerText()).includes("Accounts"));
  check("Home tiles in English", (await page.locator(".op-tile .op-t").allInnerTexts()).join(",") ===
    "Sale to customer,Customer return,Goods from factory,Return to factory,Collect from customer,Pay factory");
  const chev = await page.evaluate(() => { const s = document.querySelector(".ic-chevron svg"); return s ? getComputedStyle(s).transform : ""; });
  check("Chevrons point right (flipped)", /matrix\(-1/.test(chev), chev);
  await screen("home", null);

  // a customer (21K), a factory, a sale, a collection, opening holdings
  await page.goto(url + "#/shop-form");
  await page.waitForTimeout(250);
  await fill("Customer name", "Golden Gate Jewels");
  await page.locator("label.f", { hasText: "Account karat" }).locator("select").selectOption("21");
  await fill("Agreed charge", "20");
  await fill("Gold (g, 21K)", "6");
  await screen("customer_form", null);
  await tap(".footer-bar .btn:has-text('Save')");
  await page.waitForURL(/#\/shop\//);
  await page.waitForTimeout(250);
  check("Customer saved in 21K: 6.00 g owes you", (await page.locator(".kpis").innerText()).includes("6.00") &&
    (await page.locator(".kpis").innerText()).includes("21K"), await page.locator(".kpis").innerText());
  await screen("customer_page", null);
  await page.goto(url + "#/shop-form?type=factory");
  await page.waitForTimeout(250);
  await fill("Factory name", "Atlas Gold Factory");
  await fill("Agreed factory charge", "8");
  await tap(".footer-bar .btn:has-text('Save')");
  await page.waitForURL(/#\/shop\//);

  await page.goto(url + "#/invoice/new?kind=purchase");
  await page.waitForSelector(".sheet");
  await screen("pick_factory", null);
  await page.locator(".sheet .list-item", { hasText: "Atlas" }).click();
  await page.waitForTimeout(200);
  await fill("Set (optional)", "R-7");
  await fill("Weight (g)", "12");
  await fill("Charges (SAR)", "96");
  await screen("purchase_editor", null);
  await tap(".footer-bar .btn:has-text('Save invoice')");
  await page.waitForSelector(".sheet .btn");
  await screen("purchase_confirm", null);
  await confirm("Save invoice");
  await page.waitForURL(/#\/doc\/inv\//);
  await page.waitForTimeout(600);
  await screen("purchase_doc", null);

  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "Golden Gate" }).click();
  await page.waitForTimeout(200);
  check("Sale line starts in the customer's karat (21)", (await page.locator("label.f", { hasText: "Karat" }).locator("select").inputValue()) === "21");
  await tap("button:has-text('Choose from the sets I have')");
  await page.waitForSelector(".sheet .list-item");
  await screen("set_picker", null);
  await page.locator(".sheet .list-item", { hasText: "R-7" }).locator(".grow").click();
  await page.waitForTimeout(250);
  await screen("sale_editor", null);
  await tap(".footer-bar .btn:has-text('Save invoice')");
  await confirm("Save invoice");
  await page.waitForURL(/#\/doc\/inv\//);
  await page.waitForTimeout(600);
  await screen("sale_doc", null);

  await page.goto(url + "#/voucher/new?kind=receipt");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "Golden Gate" }).click();
  await page.waitForTimeout(200);
  await fill("Weight (g)", "3");
  await tap("button:has-text('+ Cash')");
  await fill("Amount (SAR)", "150");
  await screen("collect_editor", null);
  await tap(".footer-bar .btn:has-text('Save voucher')");
  await confirm("Save voucher");
  await page.waitForURL(/#\/doc\/vo\//);
  await page.waitForTimeout(500);
  await screen("collect_doc", null);

  await page.goto(url + "#/opening");
  await page.waitForTimeout(300);
  await fill("21K (g)", "10");
  await fill("Amount (SAR)", "500");
  await screen("opening", null);
  await tap(".footer-bar .btn:has-text('Save')");
  await page.waitForURL(/#\/holdings/);
  await page.waitForTimeout(300);
  check("Holdings: what I have now, no net position card", (await page.locator(".net-card").count()) === 0 &&
    (await page.locator(".boxes").innerText()).includes("Gold 21K"));
  await screen("holdings", null);
  await screen("holdings_boxsheet", null, async () => { await page.locator(".box-tile").first().click(); await page.waitForSelector(".sheet"); });
  await page.goBack();
  await screen("holdings_customers", null, async () => { await page.locator(".wide-tile.cus").click(); await page.waitForSelector(".sheet"); });
  await page.goBack();

  const sid = await page.evaluate(() => App.state.shops.find((x) => x.name.startsWith("Golden")).id);
  await screen("statement", "statement/" + sid);
  await screen("statement_diamond", "statement/" + sid + "?view=diamond");
  await screen("customers", "customers");
  await screen("factories", "customers?view=factories");
  await screen("board", "customers?view=board");
  await screen("log", "log");
  await screen("search", "wo", async () => { await page.locator("#view input.sr-in").pressSequentially("R"); await page.waitForTimeout(300); });
  await screen("search_detail", null, async () => { await page.locator(".sr-item").first().click(); await page.waitForTimeout(300); });
  await screen("today", "today");
  await screen("held", "held");
  await screen("more", "more");
  await screen("settings", "settings");
  await screen("new_sheet", "home", async () => { await tap("#tabs button[data-tab=plus]"); await page.waitForSelector(".sheet"); });
  await page.goBack();
  await screen("delete_confirm", "shop-form/" + sid, async () => { await tap(".footer-bar .btn:has-text('Delete')"); await page.waitForSelector(".sheet"); });
  await page.goBack();

  // an error message from the shared logic, in English
  await page.goto(url + "#/invoice/new?kind=sale");
  await page.waitForSelector(".sheet");
  await page.locator(".sheet .list-item", { hasText: "Golden Gate" }).click();
  await page.waitForTimeout(200);
  await tap("button:has-text('+ Add')");
  await page.waitForTimeout(150);
  check("Error toast in English", /Enter the weight, the charges or the diamond/.test(await page.locator("#toast").innerText()), await page.locator("#toast").innerText());

  const miss = await missing();
  check("No missing translations were asked for", !miss.length, miss.slice(0, 8).join(" | "));

  // back to Arabic from Settings
  await page.goto(url + "#/settings");
  await page.waitForTimeout(300);
  await Promise.all([page.waitForEvent("load"), page.locator("#lang-sel").selectOption("ar")]);
  await page.waitForSelector("#tabs");
  await page.waitForTimeout(400);
  check("Switched back: Arabic, right-to-left", await page.evaluate(() => document.documentElement.dir === "rtl" && I18N.lang === "ar") &&
    (await page.locator("#tabs").innerText()).includes("الممتلكات"));
  check("Data kept after switching", await page.evaluate(() => App.state.shops.length === 2 && App.state.invoices.length === 2));
  check("No page errors", !errors.length, errors.slice(0, 3).join(" | "));

  await browser.close();
  srv.close();
  console.log(`\n${fail ? "✘" : "✔"} ${pass} passed · ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
