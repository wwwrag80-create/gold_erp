package com.jadeite.mobile;

import android.app.Activity;
import android.content.ClipData;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.core.content.FileProvider;
import androidx.webkit.WebViewAssetLoader;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/**
 * جاديت للجوال: الواجهة كلها صفحاتٌ داخل التطبيق (assets/web) تُعرض في
 * WebView بلا إنترنت، وبياناتها في الجوال (IndexedDB). هذا الملف يضيف ما
 * لا تقدر عليه الصفحة وحدها: المشاركة صورةً، والطباعة وحفظ PDF، وحفظ
 * النسخة الاحتياطية واسترجاعها.
 */
public class MainActivity extends Activity {

    static final String HOST = "appassets.androidplatform.net";
    static final String BASE = "https://" + HOST + "/assets/web/";
    static final int REQ_PICK = 11;
    static final int REQ_SAVE = 12;

    WebView web;
    FrameLayout root;
    WebViewAssetLoader loader;
    ValueCallback<Uri[]> pickCallback;
    byte[] pendingSave;
    WebView printView;          // يبقى حيّاً حتى تنتهي الطباعة
    final Handler ui = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle state) {
        // لالتقاط صفحة المستند كاملةً صورةً — قبل إنشاء أي WebView
        WebView.enableSlowWholeDocumentDraw();
        super.onCreate(state);
        // نسخة الاختبار وحدها (debuggable) تُفحص صفحاتها آلياً من الحاسب
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        root = new FrameLayout(this);
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setTextZoom(100);
        web.setWebViewClient(new LocalClient(null));
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pickCallback != null) pickCallback.onReceiveValue(null);
                pickCallback = callback;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                try {
                    startActivityForResult(Intent.createChooser(i, "اختر ملف النسخة الاحتياطية"), REQ_PICK);
                } catch (ActivityNotFoundException e) {
                    pickCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "AndroidBridge");
        if (state != null) web.restoreState(state);
        else web.loadUrl(BASE + "index.html");
    }

    /** يخدم ملفات الواجهة من داخل التطبيق، ويفتح ما سواها (اتصال، واتساب) خارجه. */
    class LocalClient extends WebViewClient {
        final Runnable onLoaded;

        LocalClient(Runnable onLoaded) { this.onLoaded = onLoaded; }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            return loader.shouldInterceptRequest(req.getUrl());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (HOST.equals(u.getHost())) return false;
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (ActivityNotFoundException e) {
                toast("لا يوجد تطبيق يفتح هذا الرابط");
            }
            return true;
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            if (onLoaded != null) onLoaded.run();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_PICK) {
            if (pickCallback != null) {
                Uri[] r = null;
                if (res == RESULT_OK && data != null && data.getData() != null) r = new Uri[]{data.getData()};
                pickCallback.onReceiveValue(r);
                pickCallback = null;
            }
        } else if (req == REQ_SAVE) {
            byte[] bytes = pendingSave;
            pendingSave = null;
            if (res != RESULT_OK || data == null || data.getData() == null || bytes == null) return;
            try (OutputStream os = getContentResolver().openOutputStream(data.getData())) {
                if (os == null) throw new Exception("تعذّر فتح الملف");
                os.write(bytes);
                toast("حُفظت النسخة الاحتياطية");
            } catch (Exception e) {
                toast("تعذّر الحفظ: " + e.getMessage());
            }
        }
    }

    void toast(String msg) {
        ui.post(() -> Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show());
    }

    File shareFile(String name, byte[] bytes) throws Exception {
        File dir = new File(getCacheDir(), "share");
        if (!dir.exists() && !dir.mkdirs()) throw new Exception("تعذّر تجهيز الملف");
        File f = new File(dir, name.replaceAll("[\\\\/:*?\"<>|]", "_"));
        try (FileOutputStream fo = new FileOutputStream(f)) {
            fo.write(bytes);
        }
        return f;
    }

    void sendFile(File f, String mime, String title) {
        Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".files", f);
        Intent i = new Intent(Intent.ACTION_SEND);
        i.setType(mime);
        i.putExtra(Intent.EXTRA_STREAM, uri);
        // ClipData مع الإذن: نافذة المشاركة نفسها تقرأ الملف فتعرض معاينته،
        // والتطبيق المستقبِل (واتساب…) يقرؤه كذلك
        i.setClipData(ClipData.newRawUri(f.getName(), uri));
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        startActivity(Intent.createChooser(i, title));
    }

    /** صفحة المستند في WebView مخفيٍّ خلف الواجهة — للطباعة أو للالتقاط صورةً. */
    WebView hiddenPage(String html, int widthPx, Runnable onLoaded) {
        WebView v = new WebView(this);
        v.getSettings().setJavaScriptEnabled(false);
        v.getSettings().setTextZoom(100);
        v.getSettings().setUseWideViewPort(true);
        v.getSettings().setLoadWithOverviewMode(true);
        v.setBackgroundColor(Color.WHITE);
        v.setWebViewClient(new LocalClient(onLoaded));
        root.addView(v, 0, new FrameLayout.LayoutParams(widthPx, ViewGroup.LayoutParams.WRAP_CONTENT));
        v.loadDataWithBaseURL(BASE, html, "text/html", "utf-8", null);
        return v;
    }

    void capture(String html, String name) {
        final int widthPx = 1080;                       // صورةٌ بعرض 1080 (الصفحة 1000)
        final String page = html.replace("width=device-width,initial-scale=1", "width=1000");
        final WebView[] ref = new WebView[1];
        ref[0] = hiddenPage(page, widthPx, () -> ui.postDelayed(() -> {
            WebView v = ref[0];
            int h = (int) Math.ceil(v.getContentHeight() * widthPx / 1000f);
            if (h <= 0) h = 1400;
            // صورةٌ أطول من هذا تُثقل ذاكرة الجوال — والكشف الطويل له «طباعة / PDF»
            if (h > 9000) {
                h = 9000;
                toast("المستند طويل: الصورة تعرض أوله — استعمل «طباعة / PDF» للكامل");
            }
            v.setLayoutParams(new FrameLayout.LayoutParams(widthPx, h));
            v.measure(View.MeasureSpec.makeMeasureSpec(widthPx, View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(h, View.MeasureSpec.EXACTLY));
            v.layout(0, 0, widthPx, h);
            final int fh = h;
            ui.postDelayed(() -> {
                try {
                    Bitmap bmp = Bitmap.createBitmap(widthPx, fh, Bitmap.Config.ARGB_8888);
                    Canvas c = new Canvas(bmp);
                    c.drawColor(Color.WHITE);
                    v.draw(c);
                    java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                    bmp.compress(Bitmap.CompressFormat.PNG, 100, bo);
                    bmp.recycle();
                    sendFile(shareFile(name + ".png", bo.toByteArray()), "image/png", "مشاركة المستند");
                } catch (Throwable e) {
                    toast("تعذّر تجهيز الصورة: " + e.getMessage());
                } finally {
                    root.removeView(v);
                    v.destroy();
                }
            }, 350);
        }, 450));
    }

    class Bridge {
        @JavascriptInterface
        public String appVersion() {
            return BuildConfig.VERSION_NAME;
        }

        @JavascriptInterface
        public void shareText(String text) {
            ui.post(() -> {
                Intent i = new Intent(Intent.ACTION_SEND);
                i.setType("text/plain");
                i.putExtra(Intent.EXTRA_TEXT, text);
                startActivity(Intent.createChooser(i, "مشاركة"));
            });
        }

        @JavascriptInterface
        public void shareHtmlImage(String html, String name) {
            ui.post(() -> capture(html, name));
        }

        @JavascriptInterface
        public void printHtml(String html, String name) {
            ui.post(() -> {
                final WebView[] ref = new WebView[1];
                ref[0] = hiddenPage(html, ViewGroup.LayoutParams.MATCH_PARENT, () -> {
                    if (ref[0] != printView) return;
                    PrintManager pm = (PrintManager) getSystemService(Context.PRINT_SERVICE);
                    PrintDocumentAdapter ad = ref[0].createPrintDocumentAdapter(name);
                    pm.print(name, ad, new PrintAttributes.Builder()
                            .setMediaSize(PrintAttributes.MediaSize.ISO_A4).build());
                });
                if (printView != null) {
                    root.removeView(printView);
                    printView.destroy();
                }
                printView = ref[0];
            });
        }

        @JavascriptInterface
        public void saveFile(String name, String b64, String mime) {
            ui.post(() -> {
                pendingSave = Base64.decode(b64, Base64.DEFAULT);
                Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType(mime);
                i.putExtra(Intent.EXTRA_TITLE, name);
                try {
                    startActivityForResult(i, REQ_SAVE);
                } catch (ActivityNotFoundException e) {
                    pendingSave = null;
                    shareFile(name, b64, mime);
                }
            });
        }

        @JavascriptInterface
        public void shareFile(String name, String b64, String mime) {
            ui.post(() -> {
                try {
                    sendFile(MainActivity.this.shareFile(name, Base64.decode(b64, Base64.DEFAULT)), mime,
                            "حفظ النسخة الاحتياطية");
                } catch (Exception e) {
                    toast("تعذّر تجهيز الملف: " + e.getMessage());
                }
            });
        }
    }
}
