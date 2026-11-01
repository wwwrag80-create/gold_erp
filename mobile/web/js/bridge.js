/* الجسر إلى أندرويد: مشاركة صورة/نص، طباعة وحفظ PDF، حفظ ملف، الحفظ
 * التلقائي في مجلدٍ خارج التطبيق، والتحديث من GitHub.
 * داخل التطبيق يوجد الكائن `AndroidBridge` (من MainActivity)، وفي متصفحٍ
 * عادي (للتجربة) بدائلُ من المتصفح نفسه. والأصل يرسل أحداثه إلى
 * `window.__native(اسم، بيانات)`.
 */
(function (root) {
  "use strict";
  const A = root.AndroidBridge || null;
  const listeners = {};
  root.__native = (ev, data) => {
    for (const fn of (listeners[ev] || []).slice()) {
      try { fn(data || {}); } catch (e) { console.error(e); }
    }
  };

  function b64(str) {
    const bytes = new TextEncoder().encode(str);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  }

  function browserDownload(name, text, mime) {
    const blob = new Blob([text], { type: mime || "application/octet-stream" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  const Bridge = {
    native: !!A,
    on(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); return () => Bridge.off(ev, fn); },
    off(ev, fn) { listeners[ev] = (listeners[ev] || []).filter((x) => x !== fn); },
    once(ev) { return new Promise((res) => { const off = Bridge.on(ev, (d) => { off(); res(d); }); }); },

    // صفحة المستند صورةً (PNG) تُشارك في واتساب وغيره
    shareHtmlImage(html, name) {
      if (A) { A.shareHtmlImage(html, name); return true; }
      const w = window.open("", "_blank");
      if (w) { w.document.write(html); w.document.close(); }
      return false;
    },
    // طباعة — ومنها «حفظ PDF» في نافذة الطباعة
    printHtml(html, name) {
      if (A) { A.printHtml(html, name); return; }
      const f = document.createElement("iframe");
      f.style.cssText = "position:fixed;width:0;height:0;border:0";
      document.body.appendChild(f);
      f.contentDocument.write(html);
      f.contentDocument.close();
      setTimeout(() => { f.contentWindow.print(); setTimeout(() => f.remove(), 2000); }, 300);
    },
    shareText(text) {
      if (A) { A.shareText(text); return; }
      if (navigator.share) { navigator.share({ text }).catch(() => {}); return; }
      window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank");
    },
    // ملف (النسخة الاحتياطية): يُحفظ حيث يختار صاحب الجهاز أو يُشارك
    saveFile(name, text, mime) {
      if (A) { A.saveFile(name, b64(text), mime || "application/json"); return; }
      browserDownload(name, text, mime);
    },
    shareFile(name, text, mime) {
      if (A) { A.shareFile(name, b64(text), mime || "application/json"); return; }
      browserDownload(name, text, mime);
    },
    dial(phone) { location.href = "tel:" + phone; },
    appVersion() { return A && A.appVersion ? A.appVersion() : "web"; },

    // ── الحفظ التلقائي في مجلدٍ خارج التطبيق (يبقى بعد حذفه) ──
    backupFolder() { return A && A.backupFolder ? A.backupFolder() : ""; },
    pickBackupFolder() { if (A) A.pickBackupFolder(); },
    restoreFromFolder() { if (A) A.restoreFromFolder(); },
    autoBackup(json) { if (A && A.autoBackup) A.autoBackup(json); },
    // صور الأطقم في مجلدٍ فرعي (gold-photos) داخل مجلد الحفظ
    savePhoto(id, b64) { if (A && A.savePhoto) A.savePhoto(id, b64); },
    syncPhotos(idsJson) { if (A && A.syncPhotos) A.syncPhotos(idsJson); },
    restorePhotos() { if (A && A.restorePhotos) A.restorePhotos(); },

    // ── التحديث ──
    updateState() {
      if (!A || !A.updateState) return { unsupported: true, version: "web" };
      try { return JSON.parse(A.updateState()); } catch (e) { return { unsupported: true }; }
    },
    checkUpdate() { if (A) A.checkUpdate(); },
    installUpdate() { if (A) A.installUpdate(); },
    requestNotifications() { if (A && A.requestNotifications) A.requestNotifications(); },

  };
  root.Bridge = Bridge;
})(window);
