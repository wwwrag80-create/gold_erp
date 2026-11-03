package com.jadeite.mobile;

import android.app.job.JobParameters;
import android.app.job.JobService;

/** الفحص الدوري عن تحديث (كل بضع ساعات، والجهاز متصل) — حتى والتطبيق مغلق. */
public class UpdateJobService extends JobService {
    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            try {
                Updater.backgroundCheck(getApplicationContext());
            } catch (Exception e) {
                Updater.prefs(getApplicationContext()).edit()
                        .putString("lastError", String.valueOf(e.getMessage())).apply();
            }
            jobFinished(params, false);
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
