package com.makersteele.namealert;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** User settings, stored in SharedPreferences so the background service can read them. */
public final class AppSettings {
    private static final String PREFS = "namealert";
    public static final String DEFAULT_DECOYS =
            "seven, seventeen, even, evening, eleven, evan, eve, steep, stephanie, "
            + "heaven, sleeve, believe, leave, receive, these";

    public String wakeWords = "";
    public String decoyWords = DEFAULT_DECOYS;
    public double minConf = 0.72;
    public double cooldownSec = 5.0;
    public double gain = 1.0;
    public boolean chime = true;
    public boolean vibrate = true;
    public boolean flash = true;
    public double flashSeconds = 3.0;

    public static AppSettings load(Context c) {
        SharedPreferences p = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        AppSettings s = new AppSettings();
        s.wakeWords = p.getString("wakeWords", s.wakeWords);
        s.decoyWords = p.getString("decoyWords", s.decoyWords);
        s.minConf = p.getFloat("minConf", (float) s.minConf);
        s.cooldownSec = p.getFloat("cooldownSec", (float) s.cooldownSec);
        s.gain = p.getFloat("gain", (float) s.gain);
        s.chime = p.getBoolean("chime", s.chime);
        s.vibrate = p.getBoolean("vibrate", s.vibrate);
        s.flash = p.getBoolean("flash", s.flash);
        s.flashSeconds = p.getFloat("flashSeconds", (float) s.flashSeconds);
        return s;
    }

    public void save(Context c) {
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("wakeWords", wakeWords)
                .putString("decoyWords", decoyWords)
                .putFloat("minConf", (float) minConf)
                .putFloat("cooldownSec", (float) cooldownSec)
                .putFloat("gain", (float) gain)
                .putBoolean("chime", chime)
                .putBoolean("vibrate", vibrate)
                .putBoolean("flash", flash)
                .putFloat("flashSeconds", (float) flashSeconds)
                .apply();
    }

    /** Copy any fields present in a JSON object (from the web UI). */
    public void applyFrom(JSONObject o) {
        wakeWords = o.optString("wakeWords", wakeWords);
        decoyWords = o.optString("decoyWords", decoyWords);
        minConf = clamp(o.optDouble("minConf", minConf), 0.3, 0.99);
        cooldownSec = clamp(o.optDouble("cooldownSec", cooldownSec), 0, 120);
        gain = clamp(o.optDouble("gain", gain), 1, 4);
        chime = o.optBoolean("chime", chime);
        vibrate = o.optBoolean("vibrate", vibrate);
        flash = o.optBoolean("flash", flash);
        flashSeconds = clamp(o.optDouble("flashSeconds", flashSeconds), 1, 30);
    }

    public JSONObject toJson() {
        JSONObject o = new JSONObject();
        try {
            o.put("wakeWords", wakeWords);
            o.put("decoyWords", decoyWords);
            o.put("minConf", minConf);
            o.put("cooldownSec", cooldownSec);
            o.put("gain", gain);
            o.put("chime", chime);
            o.put("vibrate", vibrate);
            o.put("flash", flash);
            o.put("flashSeconds", flashSeconds);
        } catch (JSONException ignored) {
        }
        return o;
    }

    /** "Steven, Steve\nstevie" -> [steven, steve, stevie]; single words only. */
    public static List<String> parseWords(String text) {
        List<String> out = new ArrayList<>();
        if (text == null) return out;
        for (String w : text.toLowerCase(Locale.US).split("[,\\s]+")) {
            if (w.matches("[a-z']+") && !out.contains(w)) out.add(w);
        }
        return out;
    }

    private static double clamp(double v, double lo, double hi) {
        return Math.max(lo, Math.min(hi, v));
    }
}
