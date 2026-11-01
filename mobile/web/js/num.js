/* الأرقام: تقريبٌ مطابقٌ لبايثون حرفياً، وعرضٌ بمنزلتين نصفياً للأعلى.
 *
 * الجوال يعيد حساب ما يحسبه البرنامج على الكمبيوتر بالمعادلات نفسها، فلا
 * بدّ أن يقرّب كما يقرّب: `round(x, n)` في بايثون يقرّب القيمة الثنائية
 * **الحقيقية** للرقم، وعند التعادل التامّ إلى الزوجي — فـ2.675 تصير 2.67
 * (لأنها مخزّنة 2.67499…) و0.0625 تصير 0.062. و`toFixed` في جافاسكربت
 * يقرّب التعادل للأعلى، فيختلف الرقمان في المنزلة الأخيرة أحياناً.
 * هنا تُقرأ القيمة الحقيقية بثلاثين منزلةً زائدة ثم يُطبَّق حكم بايثون.
 *
 * والعرض (`f2`) كـ`services/numfmt.py`: يُزال غبار الفاصلة العائمة
 * بتقريبٍ إلى تسع منازل، ثم منزلتان نصفياً للأعلى، بلا «‎-0.00».
 */
(function (root) {
  "use strict";

  function incDigits(s) {            // "0999" → "1000"
    const a = s.split("");
    let i = a.length - 1;
    while (i >= 0) {
      if (a[i] === "9") { a[i] = "0"; i--; continue; }
      a[i] = String.fromCharCode(a[i].charCodeAt(0) + 1);
      return a.join("");
    }
    return "1" + a.join("");
  }

  function pyRound(x, n) {
    x = Number(x);
    if (!isFinite(x) || x === 0) return x;
    n = n | 0;
    const neg = x < 0, ax = Math.abs(x);
    if (ax >= 1e21) return x;
    const s = ax.toFixed(Math.min(100, n + 30));
    const dot = s.indexOf(".");
    const ip = dot < 0 ? s : s.slice(0, dot);
    const fp = dot < 0 ? "" : s.slice(dot + 1);
    const keep = fp.slice(0, n), rest = fp.slice(n);
    let up = false;
    if (rest.length) {
      const r0 = rest[0];
      if (r0 > "5") up = true;
      else if (r0 === "5") {
        if (/[1-9]/.test(rest.slice(1))) up = true;
        else {                         // تعادلٌ تامّ: إلى الزوجي
          const last = n > 0 ? keep[n - 1] : ip[ip.length - 1];
          up = (last.charCodeAt(0) - 48) % 2 === 1;
        }
      }
    }
    let digits = ip + keep;
    if (up) digits = incDigits(digits);
    const intPart = n > 0 ? digits.slice(0, digits.length - n) || "0" : digits;
    const frac = n > 0 ? digits.slice(digits.length - n) : "";
    const v = Number(intPart + (frac ? "." + frac : ""));
    return neg ? -v : v;
  }

  // الرقم بصورته العشرية العادية (بلا أُسّ) — كـDecimal(repr(x))
  function plain(x) {
    let s = String(x);
    if (!/e/i.test(s)) return s;
    const m = /^(-?)(\d+)(?:\.(\d+))?e([+-]\d+)$/i.exec(s);
    if (!m) return s;
    const sign = m[1], int = m[2], fr = m[3] || "", e = parseInt(m[4], 10);
    let digits = int + fr, point = int.length + e;
    if (point <= 0) return sign + "0." + "0".repeat(-point) + digits;
    if (point >= digits.length) return sign + digits + "0".repeat(point - digits.length);
    return sign + digits.slice(0, point) + "." + digits.slice(point);
  }

  // نصٌّ عشري ← منزلتان نصفياً للأعلى (ROUND_HALF_UP)
  function halfUp(str, n) {
    let neg = str[0] === "-";
    if (neg) str = str.slice(1);
    let [ip, fp = ""] = str.split(".");
    fp = fp.padEnd(n + 1, "0");
    let digits = ip + fp.slice(0, n);
    if (fp[n] >= "5") digits = incDigits(digits);
    let i = digits.slice(0, digits.length - n) || "0";
    i = i.replace(/^0+(?=\d)/, "");
    const f = digits.slice(digits.length - n);
    if (/^0*$/.test(i + f)) neg = false;     // لا «‎-0.00»
    return (neg ? "-" : "") + i + (n ? "." + f : "");
  }

  function q2str(v) {
    if (v === null || v === undefined || v === "") return null;
    const f = Number(v);
    if (!isFinite(f)) return null;
    return halfUp(plain(pyRound(f, 9)), 2);
  }

  function r2(v) {
    const s = q2str(v);
    return s === null ? 0 : Number(s);
  }

  function groupThousands(s) {
    const neg = s[0] === "-";
    if (neg) s = s.slice(1);
    const [i, f] = s.split(".");
    const g = i.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return (neg ? "-" : "") + g + (f !== undefined ? "." + f : "");
  }

  function f2(v, opts) {
    const o = opts || {};
    const s = q2str(v);
    if (s === null) return v === null || v === undefined ? "" : String(v);
    let out = o.sep === false ? s : groupThousands(s);
    if (o.sign && !out.startsWith("-") && Number(s) !== 0) out = "+" + out;
    return out;
  }

  // ══ قراءة ما يكتبه المستخدم ══
  // أرقامٌ عربية أو هندية، وفاصلةٌ عشرية «٫» أو «,»، وجمعٌ وطرحٌ بسيط
  // كما تقبل خانات البرنامج («12+3» ← 15).
  const AR = "٠١٢٣٤٥٦٧٨٩", FA = "۰۱۲۳۴۵۶۷۸۹";
  function normalizeDigits(s) {
    return String(s == null ? "" : s)
      .replace(/[٠-٩]/g, (c) => String(AR.indexOf(c)))
      .replace(/[۰-۹]/g, (c) => String(FA.indexOf(c)))
      .replace(/[٫,،]/g, ".")
      .replace(/[\s‎‏]/g, "");
  }

  function parseNum(s) {
    const t = normalizeDigits(s);
    if (!t) return 0;
    if (!/^[-+]?\d*\.?\d+([-+]\d*\.?\d+)*$/.test(t)) {
      const n = Number(t);
      return isFinite(n) ? n : NaN;
    }
    let total = 0;
    const re = /([-+]?)(\d*\.?\d+)/g;
    let m;
    while ((m = re.exec(t))) total += (m[1] === "-" ? -1 : 1) * Number(m[2]);
    return total;
  }

  const api = { pyRound, f2, r2, q2str, parseNum, normalizeDigits, plain, halfUp };
  root.Num = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
