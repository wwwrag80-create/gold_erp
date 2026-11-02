/* ÀUR على الويب (الآيفون عبر الرابط): يعمل بلا إنترنت. لكل إصدارٍ نسخةٌ من ملفات التطبيق؛
 * والإصدار الجديد يُنزَّل في الخلفية وينتظر «حدّث الآن» (نافذة «يوجد تحديث جديد»).
 * VERSION وFILES يكتبهما build_site.py عند بناء الموقع — وهنا (للتطوير) بلا ذاكرة. */
const VERSION = "dev";
const FILES = [];
const CACHE = "aur-" + VERSION;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("aur-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// «حدّث الآن» من الصفحة
self.addEventListener("message", (e) => { if (e.data === "skipWaiting") self.skipWaiting(); });

self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;   // الإعلانات والشبكة كما هي
  // رقم الإصدار وقناة الرعاة: من الشبكة أولاً
  if (u.pathname.endsWith("/version.json")) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request, { ignoreSearch: true })));
    return;
  }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then((r) => r || fetch(e.request)));
});
