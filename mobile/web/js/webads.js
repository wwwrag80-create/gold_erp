/* إعلان نسخة الويب (الآيفون عبر الرابط) — Google AdSense، كإعلان أندرويد تماماً: شريطٌ واحد
 * صغير أسفل الشاشة، في شاشات التصفّح وحدها (الصفحة تقول ما يناسب كل شاشة)، مطويٌّ حتى يصل
 * إعلانٌ فعلاً. لا يعمل إلا على الموقع نفسه (https) وبعد قبول الموقع في AdSense ووضع رقم
 * الوحدة (slot) هنا — وقبل ذلك لا يُحمَّل شيءٌ من Google أصلاً. التطبيقان (أندرويد/آيفون) لا يستخدمانه. */
(function (root) {
  "use strict";
  const CFG = {
    client: "ca-pub-2600352063526857",   // حساب المالك (رقم الناشر نفسه في AdMob وAdSense)
    slot: "",                            // وحدة «Display» أفقية من AdSense بعد قبول الموقع
  };
  let box = null, ins = null, wanted = false, filled = false;

  function enabled() {
    return !root.AndroidBridge && !!CFG.slot && (location.protocol === "https:" || location.hostname === "localhost");
  }

  function apply() {
    const on = enabled() && wanted && filled;
    document.body.classList.toggle("web-ad", on);
    if (box) document.documentElement.style.setProperty("--webad-h", on ? box.offsetHeight + "px" : "0px");
  }

  function ensure() {
    if (box || !enabled()) return;
    box = document.createElement("div");
    box.id = "webad";
    ins = document.createElement("ins");
    ins.className = "adsbygoogle";
    ins.style.display = "block";
    ins.setAttribute("data-ad-client", CFG.client);
    ins.setAttribute("data-ad-slot", CFG.slot);
    ins.setAttribute("data-ad-format", "horizontal");
    ins.setAttribute("data-full-width-responsive", "true");
    box.appendChild(ins);
    document.body.appendChild(box);
    new MutationObserver(() => { filled = ins.getAttribute("data-ad-status") === "filled"; apply(); })
      .observe(ins, { attributes: true, attributeFilter: ["data-ad-status"] });
    const s = document.createElement("script");
    s.async = true;
    s.crossOrigin = "anonymous";
    s.src = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" + CFG.client;
    document.head.appendChild(s);
    (root.adsbygoogle = root.adsbygoogle || []).push({});
  }

  root.WebAds = {
    set(on) { wanted = !!on; if (on) ensure(); apply(); },
    state() { return { web: true, enabled: enabled(), wanted, loaded: filled, visible: document.body.classList.contains("web-ad") }; },
    config: CFG,
  };
})(window);
