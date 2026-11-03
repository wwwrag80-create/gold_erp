/* اللغة: العربية (الأصل) أو الإنجليزية — Arabic (default) or English.
 *
 * كل نصٍّ في الواجهة مكتوبٌ بالعربية كما هو، ملفوفاً بـ T("…") — والقوالب `…${x}…` صارت
 * T("…{0}…", x). وفي الإنجليزية يُبحث عن النص في I18N_EN (i18n-en.js)؛ وما لم يُترجَم بعد
 * يبقى عربياً (ويُجمع في I18N.missing للفحص). وما يُمرَّر للقالب من نصٍّ معروف يُترجَم أيضاً
 * (مثل «العميل» في «اختر {0}»).
 *
 * الاختيار يُحفظ في الجهاز (localStorage «aur.lang») ويُبلَّغ للتطبيق الأصلي (إشعارات أندرويد
 * ونوافذه)؛ وتبديل اللغة يعيد تحميل الصفحة، فكل شيء يُبنى من جديد باللغة المختارة واتجاهها.
 */
(function (root) {
  "use strict";
  const KEY = "aur.lang";
  let lang = "ar";
  try {
    const v = root.localStorage && root.localStorage.getItem(KEY);
    if (v === "en" || v === "ar") lang = v;
  } catch (e) { /* لا تخزين: العربية */ }
  // في أندرويد يحفظها الجهاز أيضاً (في الحال) — وهو المرجع إن وُجد
  try {
    const n = root.AndroidBridge && root.AndroidBridge.getLang && root.AndroidBridge.getLang();
    if (n === "en" || n === "ar") lang = n;
  } catch (e) { /* */ }

  const missing = new Set();
  const has = (d, k) => Object.prototype.hasOwnProperty.call(d, k);
  function look(s) {
    const d = root.I18N_EN || {};
    if (has(d, s)) return d[s];
    // مسافةٌ في أول النص أو آخره (" تحديث {0} متاح") تبقى كما هي حول الترجمة
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s);
    if (m && (m[1] || m[3]) && has(d, m[2])) return m[1] + d[m[2]] + m[3];
    return undefined;
  }
  function T(s, ...a) {
    let out = s;
    if (lang === "en" && typeof s === "string") {
      const e = look(s);
      if (e !== undefined) out = e;
      else if (/[؀-ۿ]/.test(s)) missing.add(s);
    }
    if (a.length && typeof out === "string") {
      out = out.replace(/\{(\d+)\}/g, (m, i) => {
        let v = a[+i];
        if (lang === "en" && typeof v === "string") { const e = look(v); if (e !== undefined) v = e; }
        return String(v);
      });
    }
    return out;
  }
  // رسالةٌ من الجهاز «بداية: تفصيل» — تُترجم بدايتها إن عُرفت
  function TX(s) {
    if (lang !== "en" || typeof s !== "string") return s;
    const e = look(s);
    if (e !== undefined) return e;
    const m = /^([^:]+?)(\s*:\s*)([\s\S]*)$/.exec(s);
    if (m) { const p = look(m[1]); if (p !== undefined) return p + ": " + m[3]; }
    return s;
  }
  function setLang(l) {
    lang = l === "en" ? "en" : "ar";
    try { root.localStorage.setItem(KEY, lang); } catch (e) { /* */ }
    try { if (root.AndroidBridge && root.AndroidBridge.setLang) root.AndroidBridge.setLang(lang); } catch (e) { /* */ }
  }
  function apply() {
    const d = root.document;
    if (!d) return;
    d.documentElement.lang = lang;
    d.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    // الشريط السفلي مكتوبٌ في index.html نفسه
    d.querySelectorAll("#tabs .l").forEach((el) => { el.textContent = T(el.textContent); });
    d.querySelectorAll("#tabs [aria-label]").forEach((el) => el.setAttribute("aria-label", T(el.getAttribute("aria-label"))));
  }

  root.I18N = {
    T, TX, setLang, apply, missing,
    get lang() { return lang; },
    get rtl() { return lang === "ar"; },
    // الجهة الفعلية لبداية السطر ونهايته (للأنماط المكتوبة في الكود)
    get start() { return lang === "ar" ? "right" : "left"; },
    get end() { return lang === "ar" ? "left" : "right"; },
  };
  apply();
  // الجهاز الأصلي يعرف اللغة من أول فتح (إشعاراته ونوافذه بها)
  try { if (root.AndroidBridge && root.AndroidBridge.setLang) root.AndroidBridge.setLang(lang); } catch (e) { /* */ }
})(typeof window !== "undefined" ? window : globalThis);
