package com.makersteele.namealert;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

import org.json.JSONArray;
import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;

import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * Foreground service (type "microphone") that listens for the user's name with Vosk.
 * While paused it stays in the foreground (so Resume works from the notification)
 * but the microphone is fully released.
 */
public class ListenerService extends Service {
    public static final String ACTION_START = "com.makersteele.namealert.START";
    public static final String ACTION_PAUSE = "com.makersteele.namealert.PAUSE";
    public static final String ACTION_RESUME = "com.makersteele.namealert.RESUME";
    public static final String ACTION_STOP = "com.makersteele.namealert.STOP";
    public static final String ACTION_RELOAD = "com.makersteele.namealert.RELOAD";
    public static final String ACTION_TEST = "com.makersteele.namealert.TEST";

    private static final int NOTIF_ID = 1;
    private static final int SAMPLE_RATE = 16000;
    private static final int BLOCK = 2000;   // 0.125 s

    // ---- state read by the UI (via the plugin)
    public static volatile boolean running = false;     // service alive
    public static volatile boolean listening = false;   // mic open
    public static volatile float level = 0f;            // 0..100
    public static volatile String status = "Stopped";
    private static final ArrayDeque<String> LOG = new ArrayDeque<>();

    private final Handler main = new Handler(Looper.getMainLooper());
    private Thread worker;
    private volatile boolean workerStop = false;
    private long lastAlert = 0;

    public static synchronized void log(String msg) {
        String line = new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date()) + "  " + msg;
        LOG.addLast(line);
        while (LOG.size() > 120) LOG.removeFirst();
    }

    public static synchronized List<String> logSnapshot() {
        return new ArrayList<>(LOG);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        Alerts.createChannels(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null && intent.getAction() != null ? intent.getAction() : ACTION_START;
        switch (action) {
            case ACTION_STOP:
                stopWorker();
                running = false;
                listening = false;
                status = "Stopped";
                log("Stopped");
                ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE);
                stopSelf();
                return START_NOT_STICKY;
            case ACTION_PAUSE:
                stopWorker();
                status = "Paused";
                updateNotification();
                return START_NOT_STICKY;
            case ACTION_TEST:
                Alerts.fire(this, AppSettings.load(this), "test");
                if (!running) stopSelf();
                return START_NOT_STICKY;
            case ACTION_RELOAD:
                if (listening) {
                    stopWorker();
                    startWorker();
                }
                return START_NOT_STICKY;
            case ACTION_START:
            case ACTION_RESUME:
            default:
                goForeground();
                running = true;
                if (!listening) startWorker();
                updateNotification();
                return START_NOT_STICKY;
        }
    }

    private void goForeground() {
        int type = Build.VERSION.SDK_INT >= 30 ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE : 0;
        ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(), type);
    }

    private Notification buildNotification() {
        boolean on = listening || (worker != null && worker.isAlive());
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent openPi = PendingIntent.getActivity(this, 10, open, PendingIntent.FLAG_IMMUTABLE);
        PendingIntent togglePi = PendingIntent.getService(this, 11,
                new Intent(this, ListenerService.class).setAction(on ? ACTION_PAUSE : ACTION_RESUME),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent stopPi = PendingIntent.getService(this, 12,
                new Intent(this, ListenerService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        List<String> names = AppSettings.parseWords(AppSettings.load(this).wakeWords);
        return new NotificationCompat.Builder(this, Alerts.CH_SERVICE)
                .setSmallIcon(on ? android.R.drawable.ic_btn_speak_now : android.R.drawable.ic_media_pause)
                .setContentTitle(on ? "Listening for your name" : "Name Alert paused")
                .setContentText(names.isEmpty() ? "No names set - open the app" : android.text.TextUtils.join(", ", names))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(openPi)
                .addAction(0, on ? "Pause" : "Resume", togglePi)
                .addAction(0, "Stop", stopPi)
                .build();
    }

    private void updateNotification() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        try {
            nm.notify(NOTIF_ID, buildNotification());
        } catch (SecurityException ignored) {
        }
    }

    // ---------------------------------------------------------------- worker
    private void startWorker() {
        workerStop = false;
        listening = true;
        status = "Starting...";
        worker = new Thread(this::listenLoop, "name-alert-listener");
        worker.start();
    }

    private void stopWorker() {
        workerStop = true;
        Thread w = worker;
        if (w != null) {
            try {
                w.join(2000);
            } catch (InterruptedException ignored) {
            }
        }
        worker = null;
        listening = false;
        level = 0f;
    }

    @SuppressLint("MissingPermission")   // checked by the plugin before starting
    private void listenLoop() {
        AudioRecord rec = null;
        Recognizer recognizer = null;
        try {
            status = "Loading speech model...";
            Model model = ModelHolder.get(this);
            AppSettings s = AppSettings.load(this);
            List<String> wake = AppSettings.parseWords(s.wakeWords);
            List<String> decoys = AppSettings.parseWords(s.decoyWords);
            decoys.removeAll(wake);
            if (wake.isEmpty()) {
                status = "No names set";
                log("No names set - add yours in the app");
                while (!workerStop) SystemClock.sleep(300);
                return;
            }
            JSONArray grammar = new JSONArray();
            for (String w : wake) grammar.put(w);
            for (String w : decoys) grammar.put(w);
            grammar.put("[unk]");
            recognizer = new Recognizer(model, SAMPLE_RATE, grammar.toString());
            recognizer.setWords(true);

            int minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(minBuf, BLOCK * 4));
            if (rec.getState() != AudioRecord.STATE_INITIALIZED) {
                throw new IllegalStateException("Microphone could not be opened");
            }
            rec.startRecording();
            status = "Listening";
            log("Mic ON  names=" + wake + "  min conf=" + String.format(Locale.US, "%.2f", s.minConf));
            main.post(this::updateNotification);

            short[] buf = new short[BLOCK];
            while (!workerStop) {
                int n = rec.read(buf, 0, buf.length);
                if (n <= 0) continue;
                double sum = 0;
                for (int i = 0; i < n; i++) {
                    int v = (int) (buf[i] * s.gain);
                    if (v > 32767) v = 32767;
                    if (v < -32768) v = -32768;
                    buf[i] = (short) v;
                    sum += (double) v * v;
                }
                double rms = Math.sqrt(sum / n) / 32768.0;
                double db = 20 * Math.log10(rms + 1e-9);
                level = (float) Math.max(0, Math.min(100, (db + 60) / 60 * 100));
                if (recognizer.acceptWaveForm(buf, n)) {
                    handleResult(recognizer.getResult(), s, wake, decoys);
                }
            }
        } catch (Throwable t) {
            status = "Error: " + t.getMessage();
            log("ERROR " + t);
        } finally {
            if (rec != null) {
                try {
                    rec.stop();
                } catch (Exception ignored) {
                }
                rec.release();
            }
            if (recognizer != null) recognizer.close();
            level = 0f;
            listening = false;
            if (!status.startsWith("Error")) status = running ? "Paused" : "Stopped";
            log("Mic OFF");
            main.post(this::updateNotification);
        }
    }

    private void handleResult(String json, AppSettings s, List<String> wake, List<String> decoys) {
        try {
            JSONArray words = new JSONObject(json).optJSONArray("result");
            if (words == null) return;
            boolean fired = false;
            for (int i = 0; i < words.length(); i++) {
                JSONObject w = words.getJSONObject(i);
                String word = w.optString("word");
                double conf = w.optDouble("conf", 0);
                String c = String.format(Locale.US, "%.2f", conf);
                if (wake.contains(word)) {
                    boolean hit = conf >= s.minConf && !fired;
                    log("NAME   '" + word + "'  conf=" + c + (hit ? "  -> ALERT" : "  (below threshold)"));
                    if (hit) {
                        fired = true;
                        long now = SystemClock.elapsedRealtime();
                        if (now - lastAlert >= s.cooldownSec * 1000) {
                            lastAlert = now;
                            final String fw = word;
                            main.post(() -> Alerts.fire(this, s, fw));
                        }
                    }
                } else if (decoys.contains(word)) {
                    log("decoy  '" + word + "'  conf=" + c);
                }
            }
        } catch (Exception e) {
            log("bad result: " + e.getMessage());
        }
    }

    @Override
    public void onDestroy() {
        stopWorker();
        running = false;
        listening = false;
        status = "Stopped";
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
