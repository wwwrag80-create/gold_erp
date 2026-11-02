package com.jadeite.mobile;

import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import androidx.documentfile.provider.DocumentFile;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.Locale;

/**
 * الحفظ التلقائي خارج التطبيق — فالبيانات تبقى ولو حُذف التطبيق. بعد كل تغيير
 * يُكتب `gold-data.json` (الأحدث) ونسخةُ اليوم `gold-data-YYYY-MM-DD.json` (تبقى
 * آخر 14)، وصور الأطقم في `gold-photos`. مكانه أحد اثنين:
 * <ul>
 *   <li><b>تلقائي</b> (أندرويد 10+، الافتراضي): مجلد «ÀUR» في «المستندات» يُنشأ وحده
 *       من أول تشغيل — بلا اختيارٍ ولا إذن (ملفات التطبيق نفسه عبر MediaStore). وبعد
 *       إعادة التثبيت يُرى المجلد فيُعرض الاسترجاع منه، ونافذة المجلد تُفتح عليه مباشرة
 *       (موافقةٌ واحدة يشترطها أندرويد لقراءة ما كتبه التثبيت السابق).</li>
 *   <li><b>مجلدٌ مختار</b> (SAF): ما اختاره صاحب الجهاز، أو مجلد «ÀUR» بعد الاسترجاع منه.</li>
 * </ul>
 */
final class BackupFolder {
    static final String PREFS = "backup";
    static final String LATEST = "gold-data.json";
    static final String DAILY = "gold-data-";
    // أسماء الإصدارات الأولى — يُسترجع منها أيضاً
    static final String OLD_LATEST = "jadeite-data.json";
    static final int KEEP_DAYS = 14;

    private BackupFolder() { }

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static Uri tree(Context c) {
        String s = prefs(c).getString("tree", null);
        return s == null ? null : Uri.parse(s);
    }

    static boolean granted(Context c, Uri t) {
        for (UriPermission p : c.getContentResolver().getPersistedUriPermissions()) {
            if (p.getUri().equals(t) && p.isWritePermission()) return true;
        }
        return false;
    }

    static DocumentFile dir(Context c) {
        Uri t = tree(c);
        if (t == null || !granted(c, t)) return null;
        DocumentFile d = DocumentFile.fromTreeUri(c, t);
        return d != null && d.canWrite() ? d : null;
    }

    static String name(Context c) {
        DocumentFile d = dir(c);
        if (d == null) return "auto".equals(mode(c)) ? AUTO_NAME : "";
        String n = d.getName();
        return n == null ? "المجلد المختار" : n;
    }

    // ══ المجلد التلقائي «ÀUR» في «المستندات» (أندرويد 10+) ══
    static final String AUTO_NAME = "ÀUR";
    static final String AUTO_REL = Environment.DIRECTORY_DOCUMENTS + "/" + AUTO_NAME + "/";

    @androidx.annotation.ChecksSdkIntAtLeast(api = 29)
    static boolean autoSupported() {
        return Build.VERSION.SDK_INT >= 29;
    }

    static File autoDirFile() {
        return new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS), AUTO_NAME);
    }

    /**
     * مكان الحفظ الآن: tree (مجلدٌ مختار) · auto (المجلد التلقائي) · found (مجلد «ÀUR» من
     * تثبيتٍ سابق ينتظر الاسترجاع منه أو «ابدأ من جديد» — لا يُكتب فيه قبل ذلك) · none.
     */
    static String mode(Context c) {
        if (dir(c) != null) return "tree";
        if (!autoSupported()) return "none";
        if (prefs(c).getBoolean("auto", false)) return "auto";
        // تثبيتٌ جديد ومجلد «ÀUR» موجود (من تثبيتٍ سابق): لا يُكتب فيه قبل الاسترجاع أو «ابدأ من جديد»
        try {
            if (autoSupported() && (autoFind(c, null, LATEST) != null || autoDirFile().isDirectory())) return "found";
        } catch (Exception ignored) { }
        return "auto";
    }

    /** نسخة التثبيت السابق ما زالت لنا (يقرؤها التطبيق مباشرة، بلا نافذة مجلد)؟ */
    static boolean autoReadable(Context c) {
        try {
            return autoSupported() && autoFind(c, null, LATEST) != null;
        } catch (Exception e) {
            return false;
        }
    }

    static void startAuto(Context c) {
        prefs(c).edit().putBoolean("auto", true).apply();
    }

    /** «ابدأ من جديد» فوق مجلد «ÀUR» سابق: نسخته الأخيرة تبقى باسمٍ آخر — لا يُكتب فوقها أبداً. */
    static void startFresh(Context c) {
        if (autoSupported()) {
            try {
                Uri u = autoFind(c, null, LATEST);
                if (u != null) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.MediaColumns.DISPLAY_NAME, DAILY + "old-"
                            + new SimpleDateFormat("yyyy-MM-dd-HHmmss", Locale.US).format(new Date()) + ".json");
                    c.getContentResolver().update(u, v, null, null);
                }
            } catch (Exception ignored) { }
        }
        startAuto(c);
    }

    /** نسخة «ÀUR» الأخيرة (ملف التطبيق نفسه): {اسم الملف، نصّه} — أو null */
    static String[] autoReadLatest(Context c) throws Exception {
        if (autoSupported()) {
            Uri u = autoFind(c, null, LATEST);
            byte[] b = u == null ? null : readUri(c, u);
            if (b != null) return new String[]{LATEST, new String(b, StandardCharsets.UTF_8)};
        }
        return null;
    }

    static boolean active(Context c) {
        String m = mode(c);
        return "tree".equals(m) || "auto".equals(m);
    }

    @androidx.annotation.RequiresApi(29)
    static Uri autoCol() {
        return MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);
    }

    static String autoRel(String sub) {
        return sub == null ? AUTO_REL : AUTO_REL + sub + "/";
    }

    /** ملفّنا في المجلد التلقائي (أو مجلده الفرعي) — أو null */
    @androidx.annotation.RequiresApi(29)
    static Uri autoFind(Context c, String sub, String fileName) {
        try (Cursor cur = c.getContentResolver().query(autoCol(), new String[]{MediaStore.MediaColumns._ID},
                MediaStore.MediaColumns.RELATIVE_PATH + "=? AND " + MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                new String[]{autoRel(sub), fileName}, null)) {
            if (cur != null && cur.moveToFirst()) return ContentUris.withAppendedId(autoCol(), cur.getLong(0));
        }
        return null;
    }

    /** ملفاتنا في المجلد التلقائي (أو مجلده الفرعي): الاسم ← المعرّف */
    @androidx.annotation.RequiresApi(29)
    static Map<String, Long> autoList(Context c, String sub) {
        Map<String, Long> out = new HashMap<>();
        try (Cursor cur = c.getContentResolver().query(autoCol(),
                new String[]{MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME},
                MediaStore.MediaColumns.RELATIVE_PATH + "=?", new String[]{autoRel(sub)}, null)) {
            while (cur != null && cur.moveToNext()) {
                if (cur.getString(1) != null) out.put(cur.getString(1), cur.getLong(0));
            }
        }
        return out;
    }

    @androidx.annotation.RequiresApi(29)
    static void autoWrite(Context c, String sub, String fileName, String mime, byte[] data, boolean replace) throws Exception {
        Uri u = autoFind(c, sub, fileName);
        if (u != null && !replace) return;
        if (u == null) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName);
            v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
            v.put(MediaStore.MediaColumns.RELATIVE_PATH, autoRel(sub));
            u = c.getContentResolver().insert(autoCol(), v);
        }
        if (u == null) throw new Exception("تعذّر إنشاء ملف «" + AUTO_NAME + "» في المستندات");
        try (OutputStream os = c.getContentResolver().openOutputStream(u, "wt")) {
            if (os == null) throw new Exception("تعذّر الكتابة في ملف «" + AUTO_NAME + "»");
            os.write(data);
        }
    }

    static byte[] readUri(Context c, Uri u) throws Exception {
        try (InputStream is = c.getContentResolver().openInputStream(u)) {
            if (is == null) return null;
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            while ((n = is.read(buf)) > 0) bo.write(buf, 0, n);
            return bo.toByteArray();
        }
    }

    static void set(Context c, Uri t) {
        c.getContentResolver().takePersistableUriPermission(t,
                Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        prefs(c).edit().putString("tree", t.toString()).apply();
    }

    static void writeFile(Context c, DocumentFile d, String fileName, byte[] data) throws Exception {
        DocumentFile f = d.findFile(fileName);
        if (f == null) f = d.createFile("application/json", fileName);
        if (f == null) throw new Exception("تعذّر إنشاء ملفٍ في المجلد");
        OutputStream os;
        try {
            os = c.getContentResolver().openOutputStream(f.getUri(), "wt");
        } catch (Exception e) {
            os = c.getContentResolver().openOutputStream(f.getUri(), "w");
        }
        if (os == null) throw new Exception("تعذّر الكتابة في المجلد");
        try {
            os.write(data);
        } finally {
            os.close();
        }
    }

    /** يكتب النسخة ويعيد وقتها — أو يرمي سبب التعذّر. */
    static synchronized long write(Context c, String json) throws Exception {
        byte[] data = json.getBytes(StandardCharsets.UTF_8);
        String day = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
        String m = mode(c);
        if (autoSupported() && "auto".equals(m)) {
            autoWrite(c, null, LATEST, "application/json", data, true);
            autoWrite(c, null, DAILY + day + ".json", "application/json", data, true);
            Map<String, Long> all = autoList(c, null);
            List<String> daily = new ArrayList<>();
            for (String n : all.keySet()) {
                if (n.startsWith(DAILY) && n.endsWith(".json") && !n.startsWith(DAILY + "old-")) daily.add(n);
            }
            Collections.sort(daily, Collections.reverseOrder());
            for (int i = KEEP_DAYS; i < daily.size(); i++) {
                try { c.getContentResolver().delete(ContentUris.withAppendedId(autoCol(), all.get(daily.get(i))), null, null); }
                catch (Exception ignored) { }
            }
            startAuto(c);
            long now = System.currentTimeMillis();
            prefs(c).edit().putLong("lastWrite", now).apply();
            return now;
        }
        DocumentFile d = dir(c);
        if (d == null) throw new Exception("found".equals(m) ? "بانتظار استرجاع بياناتك من ملف «" + AUTO_NAME + "»"
                : "لم يُختر مجلد الحفظ التلقائي، أو سُحب إذنه");
        writeFile(c, d, LATEST, data);
        writeFile(c, d, DAILY + day + ".json", data);
        List<DocumentFile> daily = new ArrayList<>();
        for (DocumentFile f : d.listFiles()) {
            String n = f.getName();
            if (n != null && n.startsWith(DAILY) && n.endsWith(".json")) daily.add(f);
        }
        Collections.sort(daily, (a, b) -> String.valueOf(b.getName()).compareTo(String.valueOf(a.getName())));
        for (int i = KEEP_DAYS; i < daily.size(); i++) daily.get(i).delete();
        long now = System.currentTimeMillis();
        prefs(c).edit().putLong("lastWrite", now).apply();
        return now;
    }

    // ══ صور الأطقم: ملفٌ لكل صورة في مجلدٍ فرعي، يُكتب مرةً ولا يُعاد ══
    static final String PHOTOS = "gold-photos";

    static boolean validId(String id) {
        return id != null && id.matches("[A-Za-z0-9_-]{1,64}");
    }

    static DocumentFile photosDir(Context c, boolean create) {
        DocumentFile d = dir(c);
        if (d == null) return null;
        DocumentFile p = d.findFile(PHOTOS);
        if (p == null && create) p = d.createDirectory(PHOTOS);
        return p != null && p.isDirectory() ? p : null;
    }

    static synchronized void savePhoto(Context c, String id, byte[] jpeg) throws Exception {
        if (autoSupported() && "auto".equals(mode(c))) {
            autoWrite(c, PHOTOS, id + ".jpg", "image/jpeg", jpeg, false);
            return;
        }
        DocumentFile p = photosDir(c, true);
        if (p == null) throw new Exception("لم يُختر مجلد الحفظ التلقائي، أو سُحب إذنه");
        if (p.findFile(id + ".jpg") != null) return;
        DocumentFile f = p.createFile("image/jpeg", id + ".jpg");
        if (f == null) throw new Exception("تعذّر حفظ صورة الطقم في المجلد");
        try (OutputStream os = c.getContentResolver().openOutputStream(f.getUri(), "w")) {
            if (os == null) throw new Exception("تعذّر حفظ صورة الطقم في المجلد");
            os.write(jpeg);
        }
    }

    static Set<String> photoIds(Context c) {
        Set<String> out = new HashSet<>();
        if (autoSupported() && "auto".equals(mode(c))) {
            for (String n : autoList(c, PHOTOS).keySet()) {
                if (n.endsWith(".jpg") && validId(n.substring(0, n.length() - 4))) out.add(n.substring(0, n.length() - 4));
            }
            return out;
        }
        DocumentFile p = photosDir(c, false);
        if (p == null) return out;
        for (DocumentFile f : p.listFiles()) {
            String n = f.getName();
            if (n != null && n.endsWith(".jpg") && validId(n.substring(0, n.length() - 4))) out.add(n.substring(0, n.length() - 4));
        }
        return out;
    }

    static byte[] readPhoto(Context c, String id) throws Exception {
        if (autoSupported() && "auto".equals(mode(c))) {
            Uri u = autoFind(c, PHOTOS, id + ".jpg");
            return u == null ? null : readUri(c, u);
        }
        DocumentFile p = photosDir(c, false);
        DocumentFile f = p == null ? null : p.findFile(id + ".jpg");
        if (f == null) return null;
        try (InputStream is = c.getContentResolver().openInputStream(f.getUri())) {
            if (is == null) return null;
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            while ((n = is.read(buf)) > 0) bo.write(buf, 0, n);
            return bo.toByteArray();
        }
    }

    /** أحدث نسخةٍ في المجلد: {اسم الملف، نصّه} — أو null إن خلا منها. */
    static String[] readLatest(Context c, Uri t) throws Exception {
        DocumentFile d = DocumentFile.fromTreeUri(c, t);
        if (d == null) return null;
        // الأحدث كتابةً بين نسخ التطبيق (ومنها «gold-data (1).json» إن كتب تثبيتٌ لاحق بجانب
        // ملفٍ قديم)؛ و`gold-data.json` إن كان معاصراً له (نسخة اليوم تُكتب بعده بلحظة)
        DocumentFile latest = d.findFile(LATEST), best = null;
        for (DocumentFile f : d.listFiles()) {
            String n = f.getName();
            if (n == null || !n.endsWith(".json")) continue;
            if (!(n.startsWith("gold-data") || n.startsWith("gold-backup")
                    || n.startsWith("jadeite-data") || n.startsWith("jadeite-backup"))) continue;
            if (best == null || f.lastModified() > best.lastModified()) best = f;
        }
        if (latest != null && (best == null || best.lastModified() - latest.lastModified() < 120_000)) best = latest;
        if (best == null) best = d.findFile(OLD_LATEST);
        if (best == null) return null;
        try (InputStream is = c.getContentResolver().openInputStream(best.getUri())) {
            if (is == null) return null;
            return new String[]{best.getName(), Updater.readAll(is)};
        }
    }
}
