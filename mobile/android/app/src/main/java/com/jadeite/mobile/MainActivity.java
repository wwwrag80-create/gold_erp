package com.jadeite.mobile;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.provider.DocumentsContract;
import android.provider.Settings;
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

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * نظام محاسبي للذهب (الجوال): الواجهة كلها صفحاتٌ داخل التطبيق (assets/web) تُعرض في
 * WebView، وبياناتها في الجوال (IndexedDB). هذا الملف يضيف ما لا تقدر عليه
 * الصفحة وحدها: المشاركة صورةً، والطباعة وحفظ PDF، والنسخ الاحتياطي في
 * مجلدٍ خارج التطبيق (يبقى بعد حذفه)، والتحديث من GitHub.
 */
public class MainActivity extends Activity {

    static final String HOST = "appassets.androidplatform.net";
    static final String BASE = "https://" + HOST + "/assets/web/";
    static final String EXTRA_UPDATE = "jadeite.update";
    static final int REQ_PICK = 11;
    static final int REQ_SAVE = 12;
    static final int REQ_TREE = 13;
    static final int REQ_RESTORE = 14;
    static final int REQ_NOTIFY = 15;

    WebView web;
    FrameLayout root;
    WebViewAssetLoader loader;
    ValueCallback<Uri[]> pickCallback;
    byte[] pendingSave;
    WebView printView;              // يبقى حيّاً حتى تنتهي الطباعة
    boolean pageReady;
    boolean openUpdateWhenReady;
    File pendingInstall;            // ينتظر إذن «تثبيت التطبيقات» من الإعدادات
    final Handler ui = new Handler(Looper.getMainLooper());
    final ExecutorService bg = Executors.newSingleThreadExecutor();
    final ExecutorService backupQ = Executors.newSingleThreadExecutor();

    boolean debuggable() {
        return (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
    }

    @Override
    protected void onCreate(Bundle state) {
        // لالتقاط صفحة المستند كاملةً صورةً — قبل إنشاء أي WebView
        WebView.enableSlowWholeDocumentDraw();
        super.onCreate(state);
        // نسخة الاختبار وحدها (debuggable) تُفحص صفحاتها آلياً من الحاسب
        if (debuggable()) WebView.setWebContentsDebuggingEnabled(true);
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
        web.setWebViewClient(new LocalClient(() -> {
            pageReady = true;
            if (openUpdateWhenReady) {
                openUpdateWhenReady = false;
                emit("openUpdate", new JSONObject());
            }
        }));
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

        Updater.ensureChannel(this);
        Updater.schedule(this);
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleIntent(intent);
    }

    void handleIntent(Intent i) {
        if (i == null || !i.getBooleanExtra(EXTRA_UPDATE, false)) return;
        i.removeExtra(EXTRA_UPDATE);
        if (pageReady) emit("openUpdate", new JSONObject());
        else openUpdateWhenReady = true;
    }

    @Override
    protected void onResume() {
        super.onResume();
        // رجع من إعداد «السماح بالتثبيت» — يُكمل التثبيت إن أُذن له
        if (pendingInstall != null && canInstall()) {
            File f = pendingInstall;
            pendingInstall = null;
            launchInstall(f);
        }
    }

    /** حدثٌ من الأصل إلى الصفحة: window.__native(اسم، بيانات). */
    void emit(String event, JSONObject data) {
        ui.post(() -> web.evaluateJavascript("window.__native&&window.__native("
                + JSONObject.quote(event) + "," + data.toString() + ")", null));
    }

    static JSONObject obj(Object... kv) {
        JSONObject o = new JSONObject();
        try {
            for (int i = 0; i + 1 < kv.length; i += 2) o.put(String.valueOf(kv[i]), kv[i + 1]);
        } catch (Exception ignored) { }
        return o;
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
        Uri uri = data == null ? null : data.getData();
        if (req == REQ_PICK) {
            if (pickCallback != null) {
                pickCallback.onReceiveValue(res == RESULT_OK && uri != null ? new Uri[]{uri} : null);
                pickCallback = null;
            }
        } else if (req == REQ_SAVE) {
            byte[] bytes = pendingSave;
            pendingSave = null;
            if (res != RESULT_OK || uri == null || bytes == null) return;
            try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                if (os == null) throw new Exception("تعذّر فتح الملف");
                os.write(bytes);
                toast("حُفظت النسخة الاحتياطية");
            } catch (Exception e) {
                toast("تعذّر الحفظ: " + e.getMessage());
            }
        } else if (req == REQ_TREE) {
            if (res != RESULT_OK || uri == null) {
                emit("backupFolder", obj("ok", false));
                return;
            }
            try {
                BackupFolder.set(this, uri);
                emit("backupFolder", obj("ok", true, "name", BackupFolder.name(this)));
            } catch (Exception e) {
                emit("backupFolder", obj("ok", false, "error", String.valueOf(e.getMessage())));
            }
        } else if (req == REQ_RESTORE) {
            if (res != RESULT_OK || uri == null) {
                emit("restore", obj("ok", false));
                return;
            }
            bg.execute(() -> {
                try {
                    BackupFolder.set(this, uri);
                    String[] r = BackupFolder.readLatest(this, uri);
                    if (r == null) {
                        emit("restore", obj("ok", false, "error",
                                "لا توجد نسخةٌ من بيانات التطبيق في هذا المجلد", "name", BackupFolder.name(this)));
                    } else {
                        emit("restore", obj("ok", true, "file", r[0], "text", r[1], "name", BackupFolder.name(this)));
                    }
                } catch (Exception e) {
                    emit("restore", obj("ok", false, "error", String.valueOf(e.getMessage())));
                }
            });
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

    /** نافذة اختيار مجلد — تفتح على «Documents» في ذاكرة الجوال (مكانٌ يبقى بعد حذف التطبيق). */
    void openTree(int req, String event) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        if (Build.VERSION.SDK_INT >= 26) {
            i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri(
                    "com.android.externalstorage.documents", "primary:Documents"));
        }
        try {
            startActivityForResult(i, req);
        } catch (ActivityNotFoundException e) {
            emit(event, obj("ok", false, "error", "لا يدعم الجهاز اختيار مجلد"));
        }
    }

    // ══ التحديث ══
    boolean canInstall() {
        return Build.VERSION.SDK_INT < 26 || getPackageManager().canRequestPackageInstalls();
    }

    void launchInstall(File f) {
        try {
            startActivity(Updater.installIntent(this, f));
        } catch (Exception e) {
            emit("update", obj("error", "تعذّر فتح نافذة التثبيت: " + e.getMessage()));
        }
    }

    void installFile(File f) {
        ui.post(() -> {
            if (!canInstall()) {
                pendingInstall = f;
                toast("اسمح للتطبيق بتثبيت التحديثات، ثم ارجع");
                try {
                    startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:" + getPackageName())));
                } catch (Exception e) {
                    launchInstall(f);
                }
                return;
            }
            launchInstall(f);
        });
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

        // ── مجلد الحفظ التلقائي ──
        @JavascriptInterface
        public String backupFolder() {
            return BackupFolder.name(MainActivity.this);
        }

        @JavascriptInterface
        public void pickBackupFolder() {
            ui.post(() -> openTree(REQ_TREE, "backupFolder"));
        }

        @JavascriptInterface
        public void restoreFromFolder() {
            ui.post(() -> openTree(REQ_RESTORE, "restore"));
        }

        @JavascriptInterface
        public void autoBackup(String json) {
            backupQ.execute(() -> {
                try {
                    long at = BackupFolder.write(MainActivity.this, json);
                    emit("backupDone", obj("ok", true, "at", at));
                } catch (Exception e) {
                    emit("backupDone", obj("ok", false, "error", String.valueOf(e.getMessage())));
                }
            });
        }

        // ── التحديث ──
        @JavascriptInterface
        public String updateState() {
            return Updater.state(MainActivity.this).toString();
        }

        @JavascriptInterface
        public void checkUpdate() {
            bg.execute(() -> {
                try {
                    Updater.fetchPointer(MainActivity.this);
                    emit("update", Updater.state(MainActivity.this));
                } catch (Exception e) {
                    Updater.prefs(MainActivity.this).edit()
                            .putString("lastError", String.valueOf(e.getMessage())).apply();
                    JSONObject s = Updater.state(MainActivity.this);
                    try {
                        s.put("error", "تعذّر الاتصال بقناة التحديث — تحقّق من الإنترنت");
                    } catch (Exception ignored) { }
                    emit("update", s);
                }
            });
        }

        @JavascriptInterface
        public void installUpdate() {
            bg.execute(() -> {
                try {
                    JSONObject p = Updater.cachedPointer(MainActivity.this);
                    if (p == null || !Updater.newer(MainActivity.this, p)) p = Updater.fetchPointer(MainActivity.this);
                    if (!Updater.newer(MainActivity.this, p)) {
                        emit("update", Updater.state(MainActivity.this));
                        return;
                    }
                    File f = Updater.download(MainActivity.this, p,
                            pct -> emit("updateProgress", obj("pct", pct)));
                    emit("update", Updater.state(MainActivity.this));
                    installFile(f);
                } catch (Exception e) {
                    emit("update", obj("error", String.valueOf(e.getMessage())));
                }
            });
        }

        @JavascriptInterface
        public void requestNotifications() {
            if (Build.VERSION.SDK_INT >= 33 && !Updater.canNotify(MainActivity.this)) {
                ui.post(() -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIFY));
            }
        }

        // ── الناشر ──
        @JavascriptInterface
        public boolean setPublisherToken(String token) {
            Updater.setToken(MainActivity.this, token);
            return Updater.hasToken(MainActivity.this);
        }

        @JavascriptInterface
        public void publishUpdate(String notes) {
            bg.execute(() -> {
                try {
                    String v = Updater.publish(MainActivity.this, notes);
                    emit("publish", obj("ok", true, "version", v));
                } catch (Exception e) {
                    String msg = String.valueOf(e.getMessage());
                    if (e instanceof Updater.HttpError && (((Updater.HttpError) e).code == 401
                            || ((Updater.HttpError) e).code == 403 || ((Updater.HttpError) e).code == 404)) {
                        msg = "مفتاح النشر غير صالح أو بلا صلاحية «Issues: Read and write» على المستودع";
                    }
                    emit("publish", obj("ok", false, "error", msg));
                }
            });
        }

        // ── لنسخة الاختبار وحدها (debuggable): تجربة سلسلة التحديث آلياً ──
        @JavascriptInterface
        public void _testInstall(String url, String sha, String version) {
            if (!debuggable()) return;
            bg.execute(() -> {
                try {
                    File f = Updater.apkFile(MainActivity.this, 999999);
                    File dir = f.getParentFile();
                    if (dir != null && !dir.exists()) dir.mkdirs();
                    Updater.fetchTo(url, f, pct -> emit("updateProgress", obj("pct", pct)));
                    String got = Updater.sha256(f);
                    if (!got.equalsIgnoreCase(sha)) throw new Exception("sha mismatch " + got);
                    Updater.notifyReady(MainActivity.this, obj("version", version));
                    emit("testInstall", obj("ok", true, "sha", got));
                    installFile(f);
                } catch (Exception e) {
                    emit("testInstall", obj("ok", false, "error", String.valueOf(e.getMessage())));
                }
            });
        }

        @JavascriptInterface
        public void _testPatch() {
            if (!debuggable()) return;
            bg.execute(() -> {
                int code = 0;
                String err = "";
                try {
                    Updater.http(Updater.API_ISSUE, "PATCH", null, "{}", 15000);
                    code = 200;
                } catch (Updater.HttpError e) {
                    code = e.code;
                } catch (Exception e) {
                    err = String.valueOf(e);
                }
                emit("testPatch", obj("code", code, "error", err));
            });
        }
    }
}
