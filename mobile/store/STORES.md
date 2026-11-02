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
   - Android: `mobile/android/admob.properties` ← `ADMOB_APP_ID` و`ADMOB_BANNER_ID`
   - iPhone: `mobile/ios/AUR/Config.xcconfig` ← `ADMOB_APP_ID` و`ADMOB_BANNER_ID`
   (حتى ذلك: معرّفات Google التجريبية — ونسخ الإصدار لا تعرض بها إعلاناً أبداً.)
4. **Privacy & messaging**: أنشئ رسالة GDPR (أوروبا) — ورسالة IDFA للآيفون إن أردت إعلاناتٍ مخصّصة.
5. بعد النشر في المتجر: **App settings ← Link to store** لكل تطبيق — بدونه تبقى الإعلانات محدودة جداً.
6. **app-ads.txt**: موقعٌ إلكتروني للمطوّر (يُكتب في صفحة المتجر) وعليه الملف الذي يعطيه AdMob.

أنواع الإعلانات: **الشريط وحده مفعّل** (أسفل الشاشة، في شاشات التصفّح وحدها، مطويٌّ حتى يصل إعلان).
الإعلانات بملء الشاشة وبمكافأة والمدمجة (Native) **غير مفعّلة** عمداً — لا تُضاف إلا بقرارٍ منك.

## 3) Google Play Console
- **الحساب**: play.google.com/console (رسمٌ لمرةٍ واحدة 25$). الحسابات الشخصية الجديدة تحتاج
  **اختباراً مغلقاً بـ 12 مختبِراً لمدة 14 يوماً** قبل النشر العام.
- **إنشاء التطبيق**: الاسم ÀUR · تطبيق · مجاني · يحتوي إعلانات: **نعم**.
- **توقيع التطبيق (مهم)**: اختر **«Use existing app signing key»** وارفع مفتاح التطبيق الحالي (أداة PEPK من
  Play Console) — فيتحدّث من Play حتى من ثبّته من الرابط، بلا حذفٍ ولا فقد بيانات.
  المفتاح نفسه (الملف الذي سُلّم سابقاً) هو مفتاح الرفع أيضاً.
- **الحزمة**: `ÀUR-<الإصدار>-play.aab` موقّعة بمفتاح التطبيق نفسه (نسخة «play»: بلا تحديثٍ ذاتي ولا إذن
  تثبيت — سياسة Play). تُبنى تلقائياً في GitHub (`android.yml`) غير موقّعة، ثم تُوقَّع خارج المستودع.
  **مهم**: الحزمة المبنية بمعرّفات AdMob التجريبية لا تعرض إعلاناً — للنشر بإعلانات: ضع معرّفاتك في
  `admob.properties` أولاً ثم تُبنى وتُوقَّع من جديد.
- **استهداف API 36** (أندرويد 16) — مطلوبٌ للتطبيقات الجديدة وتحديثاتها.
- **سياسة الخصوصية**: رابط `store/privacy-policy.md` (أو صفحتك بعد تعبئة الاسم والبريد).
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
