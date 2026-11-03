# ÀUR — النشر في المتاجر والإعلانات (المرجع الكامل)

كل ما يلزم لـ Google Play وApp Store وAdMob: ما جُهّز في المشروع، وإجابات النماذج، وما يحتاج
حساب المالك. الأرقام والمعرّفات أدناه **ليست أسراراً**؛ مفاتيح التوقيع لا تُكتب هنا أبداً.

## 1) هوية التطبيق
| | Android | iPhone |
|---|---|---|
| الاسم | ÀUR | ÀUR |
| المعرّف | `com.jadeite.mobile` | `com.jadeite.mobile` |
| الإصدار | من `mobile/web/version.json` (name · code) | نفسه (MARKETING_VERSION · CURRENT_PROJECT_VERSION) |
| الأيقونة | `android/app/src/main/res/mipmap-*` | `ios/AUR/Assets.xcassets/AppIcon.appiconset` |
| صور المتجر | `store/google-play-icon-512.png` · `store/google-play-feature-1024x500.png` | `store/app-store-icon-1024.png` |

المعرّف `com.jadeite.mobile` ثابتٌ عمداً: النسخ المثبّتة من الرابط تتحدّث فوقه وتبقى بياناتها.

## 2) AdMob — ما يحتاجه حساب المالك
1. admob.google.com ← **Apps ← Add app** مرتين: Android ثم iOS (التطبيق «غير منشورٍ بعد» أول مرة).
2. لكل تطبيق **Ad units ← Banner** (اترك الحجم تكيّفياً).
3. انسخ المعرّفات إلى:
   - Android: `mobile/android/admob.properties` ← `ADMOB_APP_ID` و`ADMOB_BANNER_ID` — **تمّ (1.7.1)**
   - iPhone: `mobile/ios/AUR/Config.xcconfig` ← `ADMOB_APP_ID` و`ADMOB_BANNER_ID` — بانتظار تطبيق iOS في الحساب
   (حتى ذلك: معرّفات Google التجريبية — ونسخ الإصدار لا تعرض بها إعلاناً أبداً.)
   نسخة التطوير والمحاكي تستخدم معرّفات Google التجريبية دائماً — لا يُطلب إعلانٌ حقيقي أثناء التجربة.
   **لا تلمس إعلانات تطبيقك بنفسك** (سياسة AdMob تعدّها نقراتٍ غير صالحة وقد تُوقف الحساب).
4. **Privacy & messaging**: أنشئ رسالة GDPR (أوروبا) — ورسالة IDFA للآيفون إن أردت إعلاناتٍ مخصّصة.
5. بعد النشر في المتجر: **App settings ← Link to store** لكل تطبيق — بدونه تبقى الإعلانات محدودة جداً.
6. **app-ads.txt**: موقعٌ إلكتروني للمطوّر (يُكتب في صفحة المتجر) وعليه الملف الذي يعطيه AdMob.

أنواع الإعلانات: **الشريط وحده مفعّل** (أسفل الشاشة، في شاشات التصفّح وحدها، مطويٌّ حتى يصل إعلان).
الإعلانات بملء الشاشة وبمكافأة والمدمجة (Native) **غير مفعّلة** عمداً — لا تُضاف إلا بقرارٍ منك.

## 3) Google Play Console
- **الحساب**: play.google.com/console (رسمٌ لمرةٍ واحدة 25$). الحسابات الشخصية الجديدة تحتاج
  **اختباراً مغلقاً بـ 12 مختبِراً لمدة 14 يوماً** قبل النشر العام.
- **إنشاء التطبيق**: الاسم ÀUR · تطبيق · مجاني · يحتوي إعلانات: **نعم**.
- **توقيع التطبيق**: يُترك الافتراضي — **Google يدير مفتاح توقيع التطبيق** (Play App Signing)، ومفتاح ÀUR
  الحالي يصير **مفتاح الرفع** (الحزمة موقّعة به). لا خطوات تقنية على المالك، وإن ضاع مفتاح الرفع يعيد Google
  ضبطه. أثره: نسخة المتجر بتوقيع Google، فمن ثبّت ÀUR من الرابط يبقى عليه ويتحدّث منه كما هو؛ ولينتقل إلى
  المتجر: يحذفه، ويثبّته من Play، ثم «استرجاع بياناتي» من ملف «ÀUR».
- **الحزمة**: `ÀUR-<الإصدار>-play.aab` موقّعة بمفتاح الرفع. نسخة «play» **بلا كود التحديث الذاتي أصلاً**:
  `src/play/.../Updater.java` بلا تنزيلٍ ولا تثبيت، و`UpdateJobService` في نسخة الرابط وحدها
  (`src/direct`) — سياسة Play: التحديث من المتجر وحده. `android.yml` يتحقّق من ذلك في كل بناء.
- **الحساب الشخصي الجديد**: اختبارٌ مغلق بـ **12 مختبِراً على الأقل لمدة 14 يوماً متواصلة** ثم «Apply for
  production». النصوص والإجابات ورسائل المختبرين: حزمة Google Play المُسلَّمة للمالك.
- **بعد النشر**: `site/config.json` ← `"play_live": true` (زرّ أندرويد في الموقع يصير رابط المتجر، والملف بديلاً)،
  وربط AdMob بالمتجر.
- **استهداف API 36** (أندرويد 16) — مطلوبٌ للتطبيقات الجديدة وتحديثاتها.
- **سياسة الخصوصية**: https://deluxe-chebakia-749799.netlify.app/privacy.html
- **Data safety** (إجابات جاهزة):
  - يجمع أو يشارك بيانات؟ **نعم** (مكتبة إعلانات Google).
  - مشفّرة أثناء النقل؟ **نعم**. يستطيع المستخدم طلب الحذف؟ لا حساب في التطبيق — بياناته في جهازه.
  - الأنواع (جمعٌ ومشاركة مع Google، للإعلان والتحليلات ومنع الاحتيال، وليست اختيارية للعرض):
    **Device or other IDs** · **Approximate location** (من IP) · **App interactions** ·
    **Diagnostics / Crash logs**.
  - بيانات الحسابات والصور: **لا تُجمع** (تبقى في الجهاز، لا تُنقل إلينا).
- **المعرّف الإعلاني (Advertising ID)** في App content: **نعم، يستخدمه** — للإعلانات (مكتبة Google تضيف
  إذن `AD_ID` وأذونات `ACCESS_ADSERVICES_*` بنفسها). الأذونات الأخرى في الحزمة: الإنترنت وحالة الشبكة
  (للإعلان)، و`WAKE_LOCK`/`FOREGROUND_SERVICE` من مكتبة المهام الخلفية التي تستخدمها Google — بلا كاميرا
  ولا موقع ولا جهات اتصال (صور الأطقم من نافذة النظام نفسها).
- **تصنيف المحتوى**: لا عنف ولا مقامرة… (أداة أعمال) · **الجمهور المستهدف**: 18+.
- **إعلان «يحتوي إعلانات»**: نعم. **وصول التطبيق**: لا تسجيل دخول.
- **صور الشاشة**: هاتف (2–8 صور) — من صور تجربة المحاكي أو جهازك.

## 4) Apple — App Store Connect (بلا جهاز Mac)
- **الحساب**: developer.apple.com (99$ سنوياً) — فرد أو مؤسسة (المؤسسة تحتاج رقم D-U-N-S).
- **البناء بلا Mac**: سير العمل `ios.yml` يبني ويجرّب على جهاز Mac سحابي من GitHub. والرفع إلى
  TestFlight/App Store: `ios-release.yml` بعد إضافة أسرار المستودع:
  `APPLE_TEAM_ID` · `ASC_KEY_ID` · `ASC_ISSUER_ID` · `ASC_KEY_P8` (مفتاح App Store Connect API —
  Users and Access ← Integrations ← App Store Connect API، بصلاحية App Manager).
- **إنشاء التطبيق** في App Store Connect: الاسم ÀUR · Bundle ID `com.jadeite.mobile` · SKU مثلاً `aur-ios`.
- **App Privacy** (إجابات جاهزة، من مكتبة Google): يُجمع ويُستخدم لإعلانات طرفٍ ثالث وتحليلات:
  **Identifiers ← Device ID** · **Location ← Coarse** · **Usage Data ← Product Interaction, Advertising Data** ·
  **Diagnostics ← Crash Data, Performance Data, Other**. «التتبّع» (Tracking): **نعم للمعرّف الإعلاني**
  إن فعّلت رسالة IDFA، وإلا لا. بيانات الحسابات: لا تُجمع.
- **التشفير**: `ITSAppUsesNonExemptEncryption = false` (لا سؤال تصدير).
- **صور الشاشة**: iPhone 6.9″ (أو 6.7″) — من صور تجربة المحاكي.

## 5) ما يحتاج Mac فعلاً
لا شيء إلزامياً: البناء والتجربة والتوقيع والرفع كلها على أجهزة Mac سحابية (GitHub Actions).
Mac/Xcode يلزم فقط لمن أراد فتح المشروع وتعديله بنفسه على شاشة Xcode.

## 6) الآيفون عبر رابط — بلا متجر (نسخة الويب)
- الموقع يُبنى بـ `python3 mobile/tools/build_site.py OUT` وفيه: صفحة التثبيت (`mobile/site`)، والتطبيق نفسه في
  `app/` (يُضاف إلى الشاشة الرئيسية من سفاري، ويعمل بلا إنترنت، والتحديث بنافذة «يوجد تحديث جديد»)، ورابط تطبيق
  أندرويد، وسياسة الخصوصية، و`ads.txt`/`app-ads.txt`.
- مكانه: **Cloudflare Pages** (مجاني، بلا أي شعارٍ في الصفحات، ويسمح بالاستخدام التجاري) برابطٍ محايد
  `<اسم-المشروع>.pages.dev`. الربط مرةً واحدة من حساب المالك: dash.cloudflare.com ← Workers & Pages ← Create ←
  Pages ← Connect to Git ← gold_erp ← الفرع `main` ← Framework: None ← Build command:
  `python3 tools/build_site.py site-dist` ← Build output: `site-dist` ← Root directory: `mobile` ← Save and Deploy.
  يُبنى من جديد مع كل دفعٍ إلى main.
- **Netlify** (المكان الأول، https://deluxe-chebakia-749799.netlify.app): خطته المجانية تضع شعار «Powered by
  Netlify» ولا يُطفأ إلا باشتراك. بعد الانتقال: `site/config.json` ← `"moved_to": "<الرابط الجديد>"`، فيبني Netlify
  تحويلاً فقط (301 لكل رابطٍ قديم إلى مكانه في الجديد — بلا صفحةٍ ولا شعار)، ويُحدَّث `SITE_URL` في
  `mobile/web/js/app.js` ورابط `site-check.yml`. ثم يُحذف مشروع Netlify متى شاء المالك (بعد أن تتحدّث التطبيقات).
- الحفظ: البيانات تُحفظ في الجوال فوراً؛ وبعد كل تغييرٍ بثوانٍ (وعند الفتح) يظهر «احفظ نسخة» — لمسةٌ تحفظ الملف في
  «الملفات»/iCloud (المتصفح لا يكتب خارج نفسه وحده — قاعدة Apple). والاسترجاع من الملف في أول فتح.
- فحص الموقع كما يراه المستخدم: Actions ← «فحص موقع ÀUR» (الصفحات، وبصمة AUR.apk، والتطبيق بلا إنترنت).
- **الإعلانات (AdSense)**: adsense.google.com بحساب Google نفسه ← Sites ← أضف رابط الموقع (التحقّق
  بوسم `google-adsense-account` الموجود في الصفحة، و`ads.txt`). بعد القبول: Ads ← By ad unit ← Display ← أفقي ←
  يُرسَل رقم الوحدة (data-ad-slot) فيوضع في `mobile/web/js/webads.js` (`slot`). أبقِ **Auto ads مطفأة** (الإعلان شريطٌ
  واحد أسفل شاشات التصفّح فقط). وفعّل رسالة الموافقة (Privacy & messaging ← GDPR) لأوروبا.
  ملاحظة صادقة: قبول AdSense لموقعٍ هو «تطبيق» غير مضمون — قد يُطلب محتوى أكثر.
- **شعار «Powered by Netlify»**: يضعه Netlify وحده في كل صفحة (سكربت `/.netlify/scripts/hud`) لمواقع الخطة المجانية
  التي أُنشئت منذ 19 أغسطس 2026، وليس من ملفاتنا. يُطفأ مجاناً بلا إعادة نشر: app.netlify.com ← الموقع ←
  Project configuration ← General ← **Powered by Netlify badge** ← Off. و«فحص موقع ÀUR» يفشل ما دام ظاهراً.

## 7) متجر شاومي (Xiaomi GetApps) — ملف APK
- مجاني للمطوّر، ويقبله AdMob متجراً (ربطه يرفع «الإعلانات المحدودة»). التسجيل: global.developer.mi.com ←
  مطوّر **فرد** (Individual) بتوثيق الهوية — شرطٌ منذ 30 سبتمبر 2026 — والمراجعة يوم إلى يومي عمل؛ ومراجعة التطبيق
  عادةً حتى 3 أيام عمل.
- الملف: نسخة **play** نفسها (بلا تحديثٍ ذاتي ولا إذن تثبيت) بصيغة APK — يبنيها `android.yml`
  (`jadeite-mobile-play-unsigned.apk` في إصدار `mobile-unsigned`) ويجرّبها على أندرويد 15 (`tests/store_smoke.sh`،
  بلا شبكة فلا طلب إعلانٍ حقيقي). التوقيع بمفتاح التطبيق نفسه، v1 وv2:
  `python3 mobile/tools/sign_apk.py --key DIR --v1 jadeite-mobile-play-unsigned.apk com.jadeite.mobile.apk`
  (اسم الملف = رقم الحزمة، فبعض لوحات شاومي ترفض اسماً مختلفاً).
- الصفحة: التصنيف Business · العمر 3+ · يحتوي إعلانات: نعم · سياسة الخصوصية من الموقع · صور 1080×1920 ·
  أيقونة 512 · العربية والإنجليزية.
- بعد النشر: AdMob ← Apps ← ÀUR (Android) ← App settings ← App store details ← Add ← **Xiaomi GetApps** ←
  `com.jadeite.mobile`.
- التحديثات: كل إصدارٍ جديد يُرفع يدوياً من لوحة شاومي (Update). والمفتاح واحد، فنسخة الرابط ونسخة المتجر
  تتحدّث إحداهما فوق الأخرى بلا فقد بيانات.
