/* الرعاة: مصدر دخل التطبيق وهو مجانيٌّ لمستخدميه.
 *
 * - بطاقة راعٍ واحدة في أسفل الرئيسية (مصنعٌ أو مورّدٌ يدفع لصاحب التطبيق
 *   ليصل إلى كل المناديب) — تُغلق بلمسة فتغيب أسبوعاً.
 * - سطرٌ صغير أسفل المستندات المُرسَلة (فاتورة · سند · كشف) يعرّف بالتطبيق.
 * - «أعلن في التطبيق» في «المزيد»: تواصلٌ مع صاحب التطبيق.
 *
 * المحتوى ملف `mobile/promo/promo.json` في المستودع، يكتبه سير العمل
 * «إعلانات التطبيق» بنموذجٍ في GitHub — فلا تحديث للتطبيق مع كل إعلان.
 * يُقرأ كل 6 ساعات ويُحفظ في الجوال. لا تتبّع ولا جمع بياناتٍ من المستخدم.
 */
(function (root) {
  "use strict";
  const URL_ = "https://raw.githubusercontent.com/wwwrag80-create/gold_erp/main/mobile/promo/promo.json";
  const KEY = "promo_cache", HIDE = "promo_hidden";
  const EVERY = 6 * 3600 * 1000;
  const DEFAULT_FOOTER = "أُنشئ بتطبيق «ÀUR»";

  const str = (x, n) => String(x == null ? "" : x).replace(/\s+/g, " ").trim().slice(0, n);
  const digits = (x) => String(x == null ? "" : x).replace(/\D/g, "").slice(0, 15);
  const https = (x) => (/^https:\/\/[^\s"'<>]+$/.test(String(x || "")) ? String(x).slice(0, 300) : "");

  // ما يأتي من الملف يُنقّى: نصوصٌ قصيرة، وأرقامٌ فقط، وروابط https وحدها
  function sanitize(j) {
    const items = (Array.isArray(j.items) ? j.items : []).slice(0, 20).map((it) => ({
      id: str(it.id, 40), title: str(it.title, 60), text: str(it.text, 220),
      phone: digits(it.phone), whatsapp: digits(it.whatsapp), link: https(it.link),
      until: /^\d{4}-\d{2}-\d{2}$/.test(it.until || "") ? it.until : "",
    })).filter((it) => it.id && it.title);
    const c = j.contact && typeof j.contact === "object" ? j.contact : null;
    return {
      items,
      footer: "footer" in j ? str(j.footer, 120) : DEFAULT_FOOTER,
      contact: c && (digits(c.phone) || digits(c.whatsapp))
        ? { name: str(c.name, 40), phone: digits(c.phone), whatsapp: digits(c.whatsapp), text: str(c.text, 220) } : null,
    };
  }

  function read(k, d) { try { return JSON.parse(localStorage.getItem(k) || "null") || d; } catch (e) { return d; } }
  function write(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* */ } }
  let data = read(KEY, {});

  async function refresh(force) {
    if (!force && Date.now() - (data.at || 0) < EVERY) return false;
    try {
      const r = await fetch(URL_ + "?t=" + Math.floor(Date.now() / 600000), { cache: "no-store" });
      if (!r.ok) return false;
      const j = await r.json();
      if (!j || j.channel !== "jadeite-promo") return false;
      const before = JSON.stringify(data.v || null);
      data = { v: sanitize(j), at: Date.now() };
      write(KEY, data);
      return JSON.stringify(data.v) !== before;
    } catch (e) { return false; }
  }

  function today() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function live() {
    const v = data.v;
    if (!v) return [];
    const hidden = read(HIDE, {}), now = Date.now(), t = today();
    return v.items.filter((it) => (!it.until || it.until >= t) && !(hidden[it.id] > now));
  }
  // راعٍ واحد في اليوم — يتناوب الرعاة يوماً بيوم
  function pick() {
    const list = live();
    if (!list.length) return null;
    return list[Math.floor(Date.now() / 86400000) % list.length];
  }
  function hide(id) {
    const hidden = read(HIDE, {}), now = Date.now();
    for (const k of Object.keys(hidden)) if (!(hidden[k] > now)) delete hidden[k];
    hidden[id] = now + 7 * 86400000;
    write(HIDE, hidden);
  }
  function footer() { return data.v ? data.v.footer : DEFAULT_FOOTER; }
  function contact() { return data.v ? data.v.contact : null; }
  // رقمٌ سعودي محلي (05…) ← دولي لواتساب (9665…)
  function wa(n) { const d = digits(n); return d.startsWith("05") ? "966" + d.slice(1) : d; }

  root.Promo = { refresh, pick, hide, footer, contact, wa, url: URL_, sanitize };
})(window);
