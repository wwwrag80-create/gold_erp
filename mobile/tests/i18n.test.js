// كل نصٍّ ملفوفٍ بـ T("…") في الواجهة له ترجمةٌ إنجليزية، بنفس الخانات {0}… ونفس وسوم HTML
// Every T("…") key in the UI has an English entry with the same {n} slots and HTML tags.
//   node mobile/tests/i18n.test.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const W = path.join(__dirname, "../web/js");
let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log("  ✔", name); }
  else { fail++; console.log("  ✘", name, detail === undefined ? "" : "— " + detail); }
}

const sandbox = { window: {}, globalThis: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(W, "i18n-en.js"), "utf8"), sandbox);
const EN = sandbox.window.I18N_EN;
check("القاموس يُحمَّل", EN && Object.keys(EN).length > 500, EN && Object.keys(EN).length);

const keys = new Map();
const re = /\bT\(\s*("(?:[^"\\]|\\.)*")/g;
for (const f of ["app.js", "ui.js", "printdoc.js", "domain.js", "store.js", "promo.js"]) {
  const src = fs.readFileSync(path.join(W, f), "utf8");
  let m;
  while ((m = re.exec(src))) {
    const k = JSON.parse(m[1]);
    if (!keys.has(k)) keys.set(k, `${f}:${src.slice(0, m.index).split("\n").length}`);
  }
}
const slots = (s) => (s.match(/\{\d+\}/g) || []).sort().join();
const tags = (s) => (s.match(/<[^>]+>/g) || []).join();
const missing = [], badSlots = [], badTags = [];
for (const [k, where] of keys) {
  if (!/[؀-ۿ]/.test(k)) continue;
  const v = EN[k] !== undefined ? EN[k] : EN[k.trim()];
  if (v === undefined) { missing.push(`${where} ${JSON.stringify(k)}`); continue; }
  if (slots(k) !== slots(v)) badSlots.push(`${where} ${JSON.stringify(k)}`);
  if (tags(k) !== tags(v)) badTags.push(`${where} ${JSON.stringify(k)}`);
}
check(`كل النصوص (${keys.size}) مترجمة`, !missing.length, "\n      " + missing.slice(0, 15).join("\n      "));
check("الخانات {0}… نفسها في الترجمة", !badSlots.length, badSlots.slice(0, 10).join(" | "));
check("وسوم HTML نفسها في الترجمة (الطباعة)", !badTags.length, badTags.slice(0, 10).join(" | "));
check("لا عربية في الترجمات (إلا اسم اللغة)", Object.entries(EN).every(([k, v]) => !/[؀-ۿ]/.test(v) || k === "العربية"),
  Object.entries(EN).filter(([k, v]) => /[؀-ۿ]/.test(v) && k !== "العربية").map(([k]) => k).slice(0, 5).join(" | "));

// T: العربية كما هي، والإنجليزية من القاموس، والقيم المعروفة داخل القالب تُترجم
function load(lang) {
  const store = { "aur.lang": lang };
  const win = { I18N_EN: EN, localStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } } };
  const ctx = { window: win };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(W, "i18n.js"), "utf8"), ctx);
  return win.I18N;
}
const ar = load("ar"), en = load("en");
check("العربية: النص كما هو والقالب يُملأ", ar.T("اختر {0}", "العميل") === "اختر العميل" && ar.T("حفظ") === "حفظ" && ar.rtl);
check("English: “اختر {0}” + «العميل» → “Choose customer”", en.T("اختر {0}", "العميل") === "Choose customer" && !en.rtl, en.T("اختر {0}", "العميل"));
check("English: مسافة في أول النص تبقى", en.T(" الأطقم التي معي") === " Sets I have");
check("English: رسالة الجهاز «بداية: تفصيل»", en.TX("تعذّر فتح نافذة التثبيت: timeout") === "Couldn't open the install window: timeout", en.TX("تعذّر فتح نافذة التثبيت: timeout"));
check("English: ما لم يُترجم يبقى ويُسجَّل", en.T("نص تجريبي غير موجود") === "نص تجريبي غير موجود" && en.missing.has("نص تجريبي غير موجود"));

console.log(`\n${fail ? "✘" : "✔"} ${pass} نجح · ${fail} فشل`);
process.exit(fail ? 1 : 0);
