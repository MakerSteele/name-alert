package com.makersteele.namealert;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import org.json.JSONException;
import org.vosk.Model;

import java.util.List;

/** Bridge between the web UI and the native listener service. */
@CapacitorPlugin(
        name = "NameAlert",
        permissions = {
                @Permission(strings = {Manifest.permission.RECORD_AUDIO}, alias = "microphone"),
                @Permission(strings = {Manifest.permission.POST_NOTIFICATIONS}, alias = "notifications")
        })
public class NameAlertPlugin extends Plugin {

    private Context ctx() {
        return getContext().getApplicationContext();
    }

    private String[] neededAliases() {
        return Build.VERSION.SDK_INT >= 33
                ? new String[]{"microphone", "notifications"}
                : new String[]{"microphone"};
    }

    // ---------------------------------------------------------------- settings
    @PluginMethod
    public void getSettings(PluginCall call) {
        call.resolve(toJs(AppSettings.load(ctx()).toJson()));
    }

    @PluginMethod
    public void saveSettings(PluginCall call) {
        AppSettings s = AppSettings.load(ctx());
        s.applyFrom(call.getData());
        s.save(ctx());
        if (ListenerService.running) send(ListenerService.ACTION_RELOAD);
        call.resolve(toJs(s.toJson()));
    }

    // ---------------------------------------------------------------- start / stop
    @PluginMethod
    public void start(PluginCall call) {
        if (getPermissionState("microphone") != PermissionState.GRANTED
                || (Build.VERSION.SDK_INT >= 33 && getPermissionState("notifications") != PermissionState.GRANTED)) {
            requestPermissionForAliases(neededAliases(), call, "afterStartPerms");
            return;
        }
        doStart(call);
    }

    @PermissionCallback
    private void afterStartPerms(PluginCall call) {
        if (getPermissionState("microphone") != PermissionState.GRANTED) {
            call.reject("Microphone permission is needed to listen for your name.");
            return;
        }
        doStart(call);   // notifications denied is OK: chime + vibrate still work
    }

    private void doStart(PluginCall call) {
        Intent i = new Intent(ctx(), ListenerService.class).setAction(ListenerService.ACTION_START);
        ContextCompat.startForegroundService(ctx(), i);
        call.resolve();
    }

    @PluginMethod
    public void pause(PluginCall call) {
        if (ListenerService.running) send(ListenerService.ACTION_PAUSE);
        call.resolve();
    }

    @PluginMethod
    public void resume(PluginCall call) {
        start(call);
    }

    @PluginMethod
    public void stop(PluginCall call) {
        if (ListenerService.running) send(ListenerService.ACTION_STOP);
        call.resolve();
    }

    @PluginMethod
    public void testAlert(PluginCall call) {
        Alerts.createChannels(ctx());
        Alerts.fire(ctx(), AppSettings.load(ctx()), "test");
        call.resolve();
    }

    private void send(String action) {
        ctx().startService(new Intent(ctx(), ListenerService.class).setAction(action));
    }

    // ---------------------------------------------------------------- status
    @PluginMethod
    public void getStatus(PluginCall call) {
        JSObject o = new JSObject();
        o.put("running", ListenerService.running);
        o.put("listening", ListenerService.listening);
        o.put("level", (double) ListenerService.level);
        o.put("status", ListenerService.status);
        JSArray log = new JSArray();
        for (String line : ListenerService.logSnapshot()) log.put(line);
        o.put("log", log);
        o.put("micPermission", getPermissionState("microphone") == PermissionState.GRANTED);
        o.put("notifications", NotificationManagerCompat.from(ctx()).areNotificationsEnabled());
        o.put("fullScreen", Alerts.canFullScreen(ctx()));
        o.put("modelLoaded", ModelHolder.isLoaded());
        call.resolve(o);
    }

    // ---------------------------------------------------------------- vocabulary check
    @PluginMethod
    public void checkWords(PluginCall call) {
        final JSArray words = call.getArray("words", new JSArray());
        new Thread(() -> {
            JSObject out = new JSObject();
            JSArray unknown = new JSArray();
            try {
                Model m = ModelHolder.get(ctx());
                boolean available = true;
                List<Object> list = words.toList();
                for (Object w : list) {
                    Boolean ok = ModelHolder.inVocabulary(m, String.valueOf(w).toLowerCase());
                    if (ok == null) {
                        available = false;
                        break;
                    }
                    if (!ok) unknown.put(w);
                }
                out.put("available", available);
                out.put("unknown", unknown);
                call.resolve(out);
            } catch (Exception e) {
                call.reject("Could not load the speech model: " + e.getMessage());
            }
        }, "vocab-check").start();
    }

    // ---------------------------------------------------------------- permissions / settings screens
    @PluginMethod
    public void requestPerms(PluginCall call) {
        requestPermissionForAliases(neededAliases(), call, "afterPerms");
    }

    @PermissionCallback
    private void afterPerms(PluginCall call) {
        getStatus(call);
    }

    @PluginMethod
    public void openFullScreenSettings(PluginCall call) {
        Intent i;
        if (Build.VERSION.SDK_INT >= 34) {
            i = new Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT,
                    Uri.parse("package:" + ctx().getPackageName()));
        } else {
            i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, ctx().getPackageName());
        }
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            ctx().startActivity(i);
        } catch (Exception e) {
            Intent fallback = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + ctx().getPackageName())).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx().startActivity(fallback);
        }
        call.resolve();
    }

    private static JSObject toJs(org.json.JSONObject o) {
        try {
            return JSObject.fromJSONObject(o);
        } catch (JSONException e) {
            return new JSObject();
        }
    }
}
