package com.jadeite.mobile;

import android.content.Context;

/**
 * لغة الواجهة كما اختارها صاحب التطبيق في الصفحة (العربية أو English) — تحفظها الصفحة هنا
 * (`AndroidBridge.setLang`) فتظهر بها نوافذ الجهاز ورسائله وإشعار التحديث.
 * The UI language the user picked in the app; native toasts, choosers and notifications follow it.
 */
final class Lang {
    private static final String PREFS = "aur_lang";

    private Lang() {}

    // commit (لا apply): يُكتب في الحال، فلا يضيع الاختيار ولو أُغلق التطبيق بعده بلحظة
    static void set(Context c, String lang) {
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("lang", "en".equals(lang) ? "en" : "ar").commit();
    }

    /** المحفوظ («ar» أو «en»)، أو "" إن لم يُختر بعد. */
    static String get(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("lang", "");
    }

    static boolean en(Context c) {
        return "en".equals(c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("lang", "ar"));
    }

    static String t(Context c, String ar, String en) {
        return en(c) ? en : ar;
    }
}
