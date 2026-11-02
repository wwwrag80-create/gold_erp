package com.jadeite.mobile;

import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.util.DisplayMetrics;
import android.view.View;
import android.widget.FrameLayout;

import com.google.android.gms.ads.AdListener;
import com.google.android.gms.ads.AdRequest;
import com.google.android.gms.ads.AdSize;
import com.google.android.gms.ads.AdView;
import com.google.android.gms.ads.LoadAdError;
import com.google.android.gms.ads.MobileAds;
import com.google.android.ump.ConsentInformation;
import com.google.android.ump.ConsentRequestParameters;
import com.google.android.ump.UserMessagingPlatform;

import org.json.JSONObject;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * إعلان AdMob — شريطٌ واحد صغير أسفل الشاشة، لا غير:
 * <ul>
 *   <li>لا إعلانات بملء الشاشة ولا بمكافأة ولا بصوت — شريطٌ ثابت (anchored adaptive banner).</li>
 *   <li>يظهر في شاشات التصفّح وحدها (الرئيسية، الحسابات، الممتلكات، الكشف…)، ويُخفى
 *       في شاشات الإدخال (الفاتورة، السند، النماذج، البحث) فلا يُلمس خطأً ولا يزاحم
 *       لوحة المفاتيح. الصفحة تخبره بما يناسب كل شاشة (`setWanted`).</li>
 *   <li>لا مساحة فارغة: الشريط مطويّ حتى يصل إعلانٌ فعلاً، وبلا إنترنت يبقى مطويّاً.</li>
 *   <li>الموافقة (UMP) تُطلب أولاً حيث يلزم القانون (أوروبا وبريطانيا).</li>
 * </ul>
 * المعرّفات من mobile/android/admob.properties. ومعرّفات Google التجريبية لا تعرض
 * شيئاً في النسخة المنشورة — في نسخة الاختبار وحدها (للمحاكي) — فلا يصل المستخدمين
 * إعلانٌ تجريبي ولو نُسي استبدالها.
 */
final class Ads {
    final Activity a;
    final FrameLayout bar;
    AdView view;
    boolean wanted;
    boolean loaded;
    String error = "";
    int retries;
    final AtomicBoolean started = new AtomicBoolean(false);

    Ads(Activity a, FrameLayout bar) {
        this.a = a;
        this.bar = bar;
        bar.setVisibility(View.GONE);
    }

    boolean debuggable() {
        return (a.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
    }

    /** تعمل الإعلانات؟ بمعرّفات المالك دائماً، وبالتجريبية في نسخة الاختبار وحدها. */
    boolean enabled() {
        return !BuildConfig.ADMOB_TEST_IDS || debuggable();
    }

    /**
     * الموافقة أولاً (حيث تلزم)، ثم تهيئة المكتبة، ثم أول إعلان — مرّةً واحدة.
     * تنتهي خطوة الموافقة بنجاحٍ أو بخطأ (لا رسالة خصوصيةٍ معدّة في حساب AdMob بعد،
     * أو لا شبكة) — وفي الحالين تبدأ الإعلانات؛ وحيث تلزم الموافقة ولم تُعطَ تحدّ
     * Google الإعلانات بنفسها. ومهلةٌ أخيرة إن لم يُجب أحد.
     */
    void start() {
        if (!enabled()) return;
        bar.postDelayed(this::init, 15_000);
        try {
            ConsentInformation ci = UserMessagingPlatform.getConsentInformation(a);
            ci.requestConsentInfoUpdate(a, new ConsentRequestParameters.Builder().build(),
                    () -> UserMessagingPlatform.loadAndShowConsentFormIfRequired(a, err -> {
                        if (err != null) error = "consent form: " + err.getMessage();
                        init();
                    }),
                    err -> {
                        error = "consent: " + err.getMessage();
                        init();
                    });
            if (ci.canRequestAds()) init();
        } catch (Throwable t) {
            error = "consent: " + t.getMessage();
            init();
        }
    }

    void init() {
        if (!started.compareAndSet(false, true)) return;
        // التهيئة خارج الخيط الرئيسي (توصية Google) ثم التحميل عليه
        new Thread(() -> MobileAds.initialize(a, st -> a.runOnUiThread(this::load))).start();
    }

    void load() {
        if (view == null) {
            view = new AdView(a);
            view.setAdUnitId(BuildConfig.ADMOB_BANNER_ID);
            DisplayMetrics dm = a.getResources().getDisplayMetrics();
            int widthDp = Math.max(320, (int) (dm.widthPixels / dm.density));
            view.setAdSize(AdSize.getCurrentOrientationAnchoredAdaptiveBannerAdSize(a, widthDp));
            view.setAdListener(new AdListener() {
                @Override
                public void onAdLoaded() {
                    loaded = true;
                    apply();
                }

                @Override
                public void onAdFailedToLoad(LoadAdError e) {
                    // لا إعلان (لا إنترنت أو لا مخزون): الشريط مطويّ، ومحاولةٌ لاحقة هادئة
                    loaded = false;
                    error = e.getCode() + " " + e.getMessage();
                    apply();
                    if (retries < 3) {
                        long wait = 60_000L << retries++;
                        bar.postDelayed(Ads.this::reload, wait);
                    }
                }
            });
            bar.addView(view, new FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT));
        }
        reload();
    }

    void reload() {
        if (view != null) view.loadAd(new AdRequest.Builder().build());
    }

    /** الصفحة: هل تناسب الشاشة الحالية إعلاناً؟ */
    void setWanted(boolean w) {
        wanted = w;
        apply();
    }

    void apply() {
        bar.setVisibility(enabled() && wanted && loaded ? View.VISIBLE : View.GONE);
    }

    void pause() { if (view != null) view.pause(); }

    void resume() { if (view != null) view.resume(); }

    void destroy() { if (view != null) view.destroy(); }

    JSONObject state() {
        return MainActivity.obj("enabled", enabled(), "testIds", BuildConfig.ADMOB_TEST_IDS,
                "started", started.get(), "wanted", wanted, "loaded", loaded,
                "visible", bar.getVisibility() == View.VISIBLE, "height", bar.getHeight(), "error", error);
    }
}
