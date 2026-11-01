package com.jadeite.mobile;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.net.Uri;

import androidx.documentfile.provider.DocumentFile;

import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.Locale;

/**
 * الحفظ التلقائي في مجلدٍ يختاره صاحب الجهاز (خارج التطبيق) — فالبيانات تبقى
 * ولو حُذف التطبيق. بعد كل تغيير يُكتب `gold-data.json` (الأحدث) ونسخةُ
 * اليوم `gold-data-YYYY-MM-DD.json` (تبقى آخر 14). وعند تثبيت التطبيق من
 * جديد يُختار المجلد نفسه فيُسترجع منه كل شيء.
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
        if (d == null) return "";
        String n = d.getName();
        return n == null ? "المجلد المختار" : n;
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
        DocumentFile d = dir(c);
        if (d == null) throw new Exception("لم يُختر مجلد الحفظ التلقائي، أو سُحب إذنه");
        byte[] data = json.getBytes(StandardCharsets.UTF_8);
        writeFile(c, d, LATEST, data);
        String day = new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
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
        DocumentFile p = photosDir(c, false);
        if (p == null) return out;
        for (DocumentFile f : p.listFiles()) {
            String n = f.getName();
            if (n != null && n.endsWith(".jpg") && validId(n.substring(0, n.length() - 4))) out.add(n.substring(0, n.length() - 4));
        }
        return out;
    }

    static byte[] readPhoto(Context c, String id) throws Exception {
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
        DocumentFile best = d.findFile(LATEST);
        if (best == null) best = d.findFile(OLD_LATEST);
        if (best == null) {
            for (DocumentFile f : d.listFiles()) {
                String n = f.getName();
                if (n == null || !n.endsWith(".json")) continue;
                if (!(n.startsWith("gold-data") || n.startsWith("gold-backup")
                        || n.startsWith("jadeite-data") || n.startsWith("jadeite-backup"))) continue;
                if (best == null || f.lastModified() > best.lastModified()) best = f;
            }
        }
        if (best == null) return null;
        try (InputStream is = c.getContentResolver().openInputStream(best.getUri())) {
            if (is == null) return null;
            return new String[]{best.getName(), Updater.readAll(is)};
        }
    }
}
