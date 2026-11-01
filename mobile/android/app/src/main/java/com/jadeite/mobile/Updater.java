package com.jadeite.mobile;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;

import androidx.core.content.FileProvider;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.ProtocolException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * تحديث التطبيق من GitHub — بلا سحابة المالك ولا مساحتها.
 *
 * القناة: صفحةٌ (issue) في المستودع يكتب فيها زرُّ الناشر رقم آخر إصدارٍ
 * منشور وبصمته، والملف نفسه في المستودع (mobile/dist) على خوادم GitHub.
 * كل جهازٍ يقرأ القناة دورياً، فإن وجد إصداراً أحدث نزّله، وتحقّق من
 * بصمته، ونبّه صاحبه بإشعار — والتثبيت بلمسته (أندرويد لا يثبّت وحده).
 * والبيانات تبقى: التحديث بالمفتاح نفسه يُثبَّت فوق القديم.
 */
final class Updater {
    static final String OWNER = "wwwrag80-create";
    static final String REPO = "gold_erp";
    static final int ISSUE = 23;
    static final String API_ISSUE = "https://api.github.com/repos/" + OWNER + "/" + REPO + "/issues/" + ISSUE;
    static final String RAW = "https://raw.githubusercontent.com/" + OWNER + "/" + REPO + "/";
    static final String VERSIONS = RAW + "main/mobile/dist/versions.json";
    static final String MARK = "<!-- jadeite-mobile-channel -->";
    static final String PREFS = "updates";
    static final String PUB_PREFS = "publisher";
    static final String CHANNEL_ID = "updates";
    static final int NOTIFY_ID = 7001;
    static final int JOB_ID = 7002;

    interface Progress {
        void on(int pct);
    }

    private Updater() { }

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static long ownCode(Context c) {
        try {
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
        } catch (Exception e) {
            return BuildConfig.VERSION_CODE;
        }
    }

    // ══ HTTP ══
    static String http(String url, String method, String token, String body, int timeoutMs) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setConnectTimeout(timeoutMs);
        con.setReadTimeout(timeoutMs);
        con.setInstanceFollowRedirects(true);
        try {
            con.setRequestMethod(method);
        } catch (ProtocolException e) {          // PATCH في تطبيقٍ قديمٍ لـHttpURLConnection
            con.setRequestMethod("POST");
            con.setRequestProperty("X-HTTP-Method-Override", method);
        }
        con.setRequestProperty("Accept", "application/vnd.github+json");
        con.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        con.setRequestProperty("User-Agent", "JadeiteMobile/" + BuildConfig.VERSION_NAME);
        if (token != null) con.setRequestProperty("Authorization", "Bearer " + token.trim());
        if (body != null) {
            byte[] b = body.getBytes(StandardCharsets.UTF_8);
            con.setDoOutput(true);
            con.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream os = con.getOutputStream()) {
                os.write(b);
            }
        }
        int code = con.getResponseCode();
        InputStream is = code >= 400 ? con.getErrorStream() : con.getInputStream();
        String text = is == null ? "" : readAll(is);
        con.disconnect();
        if (code >= 400) {
            String msg = text;
            try {
                msg = new JSONObject(text).optString("message", text);
            } catch (Exception ignored) { }
            throw new HttpError(code, msg.length() > 200 ? msg.substring(0, 200) : msg);
        }
        return text;
    }

    static final class HttpError extends IOException {
        final int code;

        HttpError(int code, String msg) {
            super("HTTP " + code + ": " + msg);
            this.code = code;
        }
    }

    static String readAll(InputStream is) throws IOException {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = is.read(buf)) > 0) bo.write(buf, 0, n);
        is.close();
        return new String(bo.toByteArray(), StandardCharsets.UTF_8);
    }

    // ══ القناة ══
    static JSONObject parseChannel(String body) throws Exception {
        int i = body.indexOf(MARK);
        if (i < 0) throw new Exception("صفحة التحديثات بلا بيانات قناة");
        int a = body.indexOf("```json", i);
        int b = a < 0 ? -1 : body.indexOf("```", a + 7);
        if (a < 0 || b < 0) throw new Exception("بيانات القناة ناقصة");
        JSONObject p = new JSONObject(body.substring(a + 7, b).trim());
        if (!"jadeite-mobile".equals(p.optString("channel"))) throw new Exception("قناةٌ غير معروفة");
        if (p.optLong("code") > 0) {
            String url = p.optString("url");
            // الملف من مستودع التطبيق وحده — لا من أي رابطٍ آخر
            if (!url.startsWith(RAW)) throw new Exception("رابط التحديث من خارج المستودع");
            if (p.optString("sha256").length() != 64) throw new Exception("بصمة التحديث ناقصة");
        }
        return p;
    }

    static JSONObject fetchPointer(Context c) throws Exception {
        JSONObject issue = new JSONObject(http(API_ISSUE, "GET", null, null, 15000));
        JSONObject p = parseChannel(issue.optString("body", ""));
        prefs(c).edit().putString("pointer", p.toString())
                .putLong("lastCheck", System.currentTimeMillis()).remove("lastError").apply();
        return p;
    }

    static JSONObject cachedPointer(Context c) {
        try {
            String s = prefs(c).getString("pointer", null);
            return s == null ? null : new JSONObject(s);
        } catch (Exception e) {
            return null;
        }
    }

    static boolean newer(Context c, JSONObject p) {
        return p != null && p.optLong("code") > ownCode(c);
    }

    static File apkFile(Context c, long code) {
        return new File(new File(c.getFilesDir(), "updates"), "jadeite-" + code + ".apk");
    }

    static boolean ready(Context c, JSONObject p) {
        if (!newer(c, p)) return false;
        File f = apkFile(c, p.optLong("code"));
        return f.exists() && f.length() > 0
                && p.optString("sha256").equalsIgnoreCase(prefs(c).getString("readySha", ""));
    }

    static String sha256(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (InputStream is = new FileInputStream(f)) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = is.read(buf)) > 0) md.update(buf, 0, n);
        }
        StringBuilder sb = new StringBuilder();
        for (byte x : md.digest()) sb.append(String.format(Locale.US, "%02x", x));
        return sb.toString();
    }

    static File fetchTo(String url, File out, Progress cb) throws Exception {
        File part = new File(out.getPath() + ".part");
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setConnectTimeout(20000);
        con.setReadTimeout(30000);
        con.setRequestProperty("User-Agent", "JadeiteMobile/" + BuildConfig.VERSION_NAME);
        int code = con.getResponseCode();
        if (code >= 400) throw new HttpError(code, "تعذّر تنزيل الملف");
        long total = con.getContentLength();
        long got = 0;
        int last = -1;
        try (InputStream is = con.getInputStream(); OutputStream os = new FileOutputStream(part)) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = is.read(buf)) > 0) {
                os.write(buf, 0, n);
                got += n;
                if (cb != null && total > 0) {
                    int pct = (int) (got * 100 / total);
                    if (pct != last) {
                        last = pct;
                        cb.on(pct);
                    }
                }
            }
        } finally {
            con.disconnect();
        }
        if (out.exists() && !out.delete()) throw new IOException("تعذّر استبدال الملف");
        if (!part.renameTo(out)) throw new IOException("تعذّر حفظ الملف");
        return out;
    }

    static File download(Context c, JSONObject p, Progress cb) throws Exception {
        long code = p.getLong("code");
        String want = p.getString("sha256");
        File f = apkFile(c, code);
        if (f.exists() && want.equalsIgnoreCase(sha256(f))) {
            prefs(c).edit().putString("readySha", want).apply();
            return f;
        }
        File dir = f.getParentFile();
        if (dir != null) {
            if (!dir.exists() && !dir.mkdirs()) throw new IOException("تعذّر تجهيز مجلد التحديث");
            File[] old = dir.listFiles();
            if (old != null) for (File x : old) x.delete();
        }
        fetchTo(p.getString("url"), f, cb);
        String got = sha256(f);
        if (!want.equalsIgnoreCase(got)) {
            f.delete();
            throw new Exception("الملف المنزَّل لا يطابق بصمته — أُلغي (لم يُثبَّت شيء)");
        }
        prefs(c).edit().putString("readySha", want).apply();
        return f;
    }

    // ══ الإشعار ══
    static void ensureChannel(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "تحديثات التطبيق",
                NotificationManager.IMPORTANCE_DEFAULT);
        ch.setDescription("إشعارٌ حين يجهز إصدارٌ جديد من التطبيق للتثبيت");
        nm.createNotificationChannel(ch);
    }

    static boolean canNotify(Context c) {
        return Build.VERSION.SDK_INT < 33
                || c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    static void notifyReady(Context c, JSONObject p) {
        if (!canNotify(c)) return;
        ensureChannel(c);
        Intent i = new Intent(c, MainActivity.class)
                .putExtra(MainActivity.EXTRA_UPDATE, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, 1, i,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(c, CHANNEL_ID) : new Notification.Builder(c);
        b.setSmallIcon(R.drawable.ic_stat_update)
                .setContentTitle("تحديث نظام الذهب " + p.optString("version") + " جاهز")
                .setContentText("اضغط للتثبيت — بياناتك تبقى كما هي")
                .setAutoCancel(true)
                .setContentIntent(pi);
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        nm.notify(NOTIFY_ID, b.build());
    }

    /** الفحص في الخلفية (JobScheduler): يقرأ القناة، ينزّل الأحدث، ينبّه مرةً لكل إصدار. */
    static void backgroundCheck(Context c) throws Exception {
        JSONObject p = fetchPointer(c);
        if (!newer(c, p)) return;
        download(c, p, null);
        SharedPreferences sp = prefs(c);
        if (sp.getLong("notifiedCode", 0) != p.optLong("code")) {
            notifyReady(c, p);
            sp.edit().putLong("notifiedCode", p.optLong("code")).apply();
        }
    }

    static void schedule(Context c) {
        try {
            JobScheduler js = (JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
            for (JobInfo j : js.getAllPendingJobs()) if (j.getId() == JOB_ID) return;
            js.schedule(new JobInfo.Builder(JOB_ID, new ComponentName(c, UpdateJobService.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPeriodic(6L * 3600L * 1000L)
                    .setPersisted(true)
                    .build());
        } catch (Exception ignored) { }
    }

    static Intent installIntent(Context c, File f) {
        Uri u = FileProvider.getUriForFile(c, c.getPackageName() + ".files", f);
        return new Intent(Intent.ACTION_VIEW)
                .setDataAndType(u, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    static JSONObject state(Context c) {
        JSONObject s = new JSONObject();
        try {
            SharedPreferences sp = prefs(c);
            JSONObject p = cachedPointer(c);
            s.put("version", BuildConfig.VERSION_NAME);
            s.put("code", ownCode(c));
            s.put("lastCheck", sp.getLong("lastCheck", 0));
            s.put("lastError", sp.getString("lastError", ""));
            s.put("publisher", hasToken(c));
            s.put("published", p == null ? JSONObject.NULL : p);
            s.put("available", newer(c, p));
            s.put("ready", ready(c, p));
            s.put("canNotify", canNotify(c));
        } catch (Exception ignored) { }
        return s;
    }

    // ══ الناشر ══
    static boolean hasToken(Context c) {
        return c.getSharedPreferences(PUB_PREFS, Context.MODE_PRIVATE).getString("token", "").length() > 10;
    }

    static void setToken(Context c, String t) {
        c.getSharedPreferences(PUB_PREFS, Context.MODE_PRIVATE).edit()
                .putString("token", t == null ? "" : t.trim()).apply();
    }

    static byte[] signer(PackageInfo pi) {
        if (pi == null) return null;
        if (Build.VERSION.SDK_INT >= 28 && pi.signingInfo != null) {
            Signature[] s = pi.signingInfo.getApkContentsSigners();
            return s != null && s.length > 0 ? s[0].toByteArray() : null;
        }
        //noinspection deprecation
        return pi.signatures != null && pi.signatures.length > 0 ? pi.signatures[0].toByteArray() : null;
    }

    @SuppressWarnings("deprecation")
    static int sigFlag() {
        return Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
    }

    /**
     * «إرسال التحديث للجميع»: يعلن في القناة الإصدارَ المثبّت عند الناشر نفسه —
     * بعد التحقّق أن ملفّه في المستودع هو هو: الرقم نفسه والمفتاح نفسه والبصمة.
     */
    static String publish(Context c, String notes) throws Exception {
        String token = c.getSharedPreferences(PUB_PREFS, Context.MODE_PRIVATE).getString("token", "");
        if (token.length() < 10) throw new Exception("أدخل مفتاح النشر أولاً (الإعدادات ← النشر)");
        long code = ownCode(c);
        JSONArray vs = new JSONArray(http(VERSIONS + "?t=" + System.currentTimeMillis(), "GET", null, null, 20000));
        JSONObject e = null;
        for (int i = 0; i < vs.length(); i++) {
            if (vs.getJSONObject(i).optLong("code") == code) e = vs.getJSONObject(i);
        }
        if (e == null) {
            throw new Exception("الإصدار المثبّت عندك (" + BuildConfig.VERSION_NAME
                    + ") ليس في ملفات التوزيع على GitHub بعد");
        }
        String url = RAW + "main/mobile/dist/" + e.getString("file");
        File tmp = new File(c.getCacheDir(), "publish-check.apk");
        fetchTo(url, tmp, null);
        try {
            String sha = sha256(tmp);
            if (!sha.equalsIgnoreCase(e.getString("sha256"))) {
                throw new Exception("ملف الإصدار على GitHub لا يطابق بصمته — لم يُنشر شيء");
            }
            PackageManager pm = c.getPackageManager();
            PackageInfo arch = pm.getPackageArchiveInfo(tmp.getPath(), sigFlag());
            PackageInfo own = pm.getPackageInfo(c.getPackageName(), sigFlag());
            long archCode = arch == null ? -1 : (Build.VERSION.SDK_INT >= 28 ? arch.getLongVersionCode() : arch.versionCode);
            if (archCode != code) throw new Exception("ملف GitHub برقم إصدارٍ غير المثبّت عندك");
            byte[] a = signer(arch), b = signer(own);
            if (a == null || !Arrays.equals(a, b)) throw new Exception("ملف GitHub موقّعٌ بمفتاحٍ غير مفتاح تطبيقك");
            SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
            iso.setTimeZone(TimeZone.getTimeZone("UTC"));
            JSONObject p = new JSONObject();
            p.put("channel", "jadeite-mobile");
            p.put("version", BuildConfig.VERSION_NAME);
            p.put("code", code);
            p.put("sha256", sha.toLowerCase(Locale.US));
            p.put("url", url);
            p.put("notes", notes != null && notes.trim().length() > 0 ? notes.trim() : e.optString("notes", ""));
            p.put("published", iso.format(new Date()));
            String body = "قناة تحديثات تطبيق «نظام محاسبي للذهب» للجوال: يقرأ التطبيق هذا النص ليعرف آخر إصدارٍ منشور، "
                    + "فيُنزّله من ملفات المستودع (`mobile/dist`) ويعرض على صاحبه تثبيته.\n\n"
                    + "يكتب هذا النصَّ زرُّ «إرسال التحديث للجميع» في تطبيق الناشر — فلا تعدّله يدوياً ولا تُغلق هذه الصفحة.\n\n"
                    + MARK + "\n```json\n" + p.toString() + "\n```\n";
            http(API_ISSUE, "PATCH", token, new JSONObject().put("body", body).toString(), 20000);
            prefs(c).edit().putString("pointer", p.toString()).putLong("lastCheck", System.currentTimeMillis()).apply();
            return BuildConfig.VERSION_NAME;
        } finally {
            tmp.delete();
        }
    }
}
