package com.jadeite.mobile;

import android.app.job.JobScheduler;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.File;

/**
 * نسخة المتاجر (Google Play): التحديث من المتجر وحده — فلا قناة تحديث، ولا تنزيل ملفات تثبيت، ولا
 * نافذة تثبيت في هذه النسخة أصلاً (سياسة Play: لا يحدّث التطبيق نفسه من خارج المتجر).
 * الأسماء نفسها التي تستدعيها MainActivity (وكلها خلف BuildConfig.SELF_UPDATE = false) بلا عمل.
 * التحديث الذاتي الحقيقي في src/direct (نسخة الرابط).
 */
final class Updater {
    static final int JOB_ID = 7002;
    static final String UNSUPPORTED = "التحديث من المتجر";

    interface Progress {
        void on(int pct);
    }

    private Updater() { }

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("updates", Context.MODE_PRIVATE);
    }

    static void ensureChannel(Context c) { }

    static void schedule(Context c) { }

    /** فحصٌ دوري بقي من نسخة رابطٍ سابقة على الجهاز: يُلغى. */
    static void cancel(Context c) {
        try {
            ((JobScheduler) c.getSystemService(Context.JOB_SCHEDULER_SERVICE)).cancel(JOB_ID);
        } catch (Exception ignored) { }
    }

    static boolean canNotify(Context c) {
        return false;
    }

    static JSONObject state(Context c) {
        JSONObject s = new JSONObject();
        try {
            s.put("unsupported", true).put("store", "play").put("version", BuildConfig.VERSION_NAME);
        } catch (Exception ignored) { }
        return s;
    }

    static JSONObject cachedPointer(Context c) {
        return null;
    }

    static boolean newer(Context c, JSONObject p) {
        return false;
    }

    static JSONObject fetchPointer(Context c) throws Exception {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    static File apkFile(Context c, long code) {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    static File download(Context c, JSONObject p, Progress cb) throws Exception {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    static File fetchTo(String url, File out, Progress cb) throws Exception {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    static String sha256(File f) throws Exception {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }

    static void notifyReady(Context c, JSONObject p) { }

    static Intent installIntent(Context c, File f) {
        throw new UnsupportedOperationException(UNSUPPORTED);
    }
}
