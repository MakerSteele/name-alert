package com.makersteele.namealert;

import android.app.Activity;
import android.app.NotificationManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

/** Full-screen red flash. Wakes the screen and shows over the lock screen. Tap to dismiss. */
public class AlertActivity extends Activity {
    public static final String EXTRA_SECONDS = "seconds";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private int toggles;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                    | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        root = new FrameLayout(this);
        TextView tv = new TextView(this);
        tv.setText("SOMEONE SAID\nYOUR NAME");
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(40);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setGravity(Gravity.CENTER);
        root.addView(tv, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        root.setOnClickListener(v -> finish());
        setContentView(root);

        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        nm.cancel(Alerts.ALERT_NOTIF_ID);

        double seconds = getIntent().getDoubleExtra(EXTRA_SECONDS, 3.0);
        toggles = Math.max(2, (int) (seconds * 1000 / 250));
        tick();
    }

    private void tick() {
        if (isFinishing()) return;
        if (toggles-- <= 0) {
            finish();
            return;
        }
        root.setBackgroundColor(toggles % 2 == 0 ? Color.rgb(255, 42, 42) : Color.BLACK);
        handler.postDelayed(this::tick, 250);
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
