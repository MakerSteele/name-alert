package com.makersteele.namealert;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Build;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;

import androidx.core.app.NotificationCompat;

/** The three alert types: chime (to earbuds), vibration, full-screen red flash. */
public final class Alerts {
    public static final String CH_ALERT = "name_alert_alerts";
    public static final String CH_SERVICE = "name_alert_service";
    public static final int ALERT_NOTIF_ID = 2;

    private Alerts() {}

    public static void createChannels(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        NotificationChannel svc = new NotificationChannel(CH_SERVICE, "Listening status",
                NotificationManager.IMPORTANCE_LOW);
        svc.setDescription("Shows while Name Alert is listening, with a pause button");
        svc.setShowBadge(false);
        NotificationChannel alert = new NotificationChannel(CH_ALERT, "Name alerts",
                NotificationManager.IMPORTANCE_HIGH);
        alert.setDescription("Fires when someone says your name");
        alert.setSound(null, null);          // we play our own chime
        alert.enableVibration(false);        // and our own vibration pattern
        nm.createNotificationChannel(svc);
        nm.createNotificationChannel(alert);
    }

    public static void fire(Context c, AppSettings s, String word) {
        Context app = c.getApplicationContext();
        if (s.chime) playChime(app);
        if (s.vibrate) vibrate(app);
        if (s.flash) showFlash(app, s, word);
    }

    // ---------------------------------------------------------------- chime
    public static void playChime(Context c) {
        new Thread(() -> {
            final int sr = 44100;
            final double dur = 0.8;
            short[] pcm = new short[(int) (sr * dur)];
            for (int i = 0; i < pcm.length; i++) {
                double t = i / (double) sr;
                double a = Math.sin(2 * Math.PI * 880 * t) * Math.exp(-t * 5);
                double b = t > 0.15 ? Math.sin(2 * Math.PI * 1320 * (t - 0.15)) * Math.exp(-(t - 0.15) * 5) : 0;
                double v = (a + b) * 0.45;
                pcm[i] = (short) (Math.max(-1, Math.min(1, v)) * 32767);
            }
            AudioManager am = (AudioManager) c.getSystemService(Context.AUDIO_SERVICE);
            AudioAttributes attrs = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)          // goes to earbuds when connected
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build();
            AudioFocusRequest focus = null;
            if (Build.VERSION.SDK_INT >= 26) {
                focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                        .setAudioAttributes(attrs).build();
                am.requestAudioFocus(focus);
            }
            AudioTrack track = null;
            try {
                track = new AudioTrack.Builder()
                        .setAudioAttributes(attrs)
                        .setAudioFormat(new AudioFormat.Builder()
                                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                .setSampleRate(sr)
                                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                                .build())
                        .setTransferMode(AudioTrack.MODE_STATIC)
                        .setBufferSizeInBytes(pcm.length * 2)
                        .build();
                track.write(pcm, 0, pcm.length);
                track.play();
                Thread.sleep((long) (dur * 1000) + 150);
            } catch (Exception ignored) {
            } finally {
                if (track != null) track.release();
                if (focus != null && Build.VERSION.SDK_INT >= 26) am.abandonAudioFocusRequest(focus);
            }
        }, "chime").start();
    }

    // ---------------------------------------------------------------- vibration
    public static void vibrate(Context c) {
        long[] pattern = {0, 250, 120, 250, 120, 450};
        Vibrator v;
        if (Build.VERSION.SDK_INT >= 31) {
            VibratorManager vm = (VibratorManager) c.getSystemService(Context.VIBRATOR_MANAGER_SERVICE);
            v = vm.getDefaultVibrator();
        } else {
            v = (Vibrator) c.getSystemService(Context.VIBRATOR_SERVICE);
        }
        if (v == null || !v.hasVibrator()) return;
        if (Build.VERSION.SDK_INT >= 26) {
            v.vibrate(VibrationEffect.createWaveform(pattern, -1));
        } else {
            v.vibrate(pattern, -1);
        }
    }

    // ---------------------------------------------------------------- full-screen flash
    public static void showFlash(Context c, AppSettings s, String word) {
        Intent i = new Intent(c, AlertActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_USER_ACTION)
                .putExtra(AlertActivity.EXTRA_SECONDS, s.flashSeconds);
        PendingIntent pi = PendingIntent.getActivity(c, 1, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification n = new NotificationCompat.Builder(c, CH_ALERT)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle("Someone said your name")
                .setContentText("Heard: \"" + word + "\"")
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setColor(0xFFFF2A2A)
                .setFullScreenIntent(pi, true)
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setTimeoutAfter(15000)
                .build();
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        try {
            nm.notify(ALERT_NOTIF_ID, n);
        } catch (SecurityException ignored) {
            // POST_NOTIFICATIONS not granted - chime/vibrate still work
        }
    }

    /** Android 14+: full-screen alerts need a per-app toggle. */
    public static boolean canFullScreen(Context c) {
        if (Build.VERSION.SDK_INT < 34) return true;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        return nm.canUseFullScreenIntent();
    }
}
