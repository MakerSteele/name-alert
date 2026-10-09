package com.makersteele.namealert;

import android.content.Context;
import android.content.res.AssetManager;
import android.util.Log;

import com.sun.jna.Native;
import com.sun.jna.Pointer;

import org.vosk.LibVosk;
import org.vosk.LogLevel;
import org.vosk.Model;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Loads the Vosk model once (copying it out of the APK assets on first run). */
public final class ModelHolder {
    private static final String TAG = "NameAlert";
    private static final String ASSET_DIR = "model";
    private static final String MODEL_VERSION = "vosk-model-small-en-us-0.15";
    private static Model model;
    private static Boolean findWordOk = null;

    private ModelHolder() {}

    public static synchronized Model get(Context ctx) throws IOException {
        if (model != null) return model;
        Context c = ctx.getApplicationContext();
        File dir = new File(c.getFilesDir(), ASSET_DIR);
        File marker = new File(dir, ".ready-" + MODEL_VERSION);
        if (!marker.exists()) {
            deleteRecursive(dir);
            copyAssetDir(c.getAssets(), ASSET_DIR, dir);
            if (!marker.createNewFile()) Log.w(TAG, "could not create model marker");
        }
        LibVosk.setLogLevel(LogLevel.WARNINGS);
        model = new Model(dir.getAbsolutePath());
        return model;
    }

    public static synchronized boolean isLoaded() {
        return model != null;
    }

    /**
     * Returns true if the word is in the model vocabulary, false if not,
     * or null if the check isn't available on this build.
     */
    public static synchronized Boolean inVocabulary(Model m, String word) {
        try {
            if (findWordOk == null) {
                Native.register(VoskExt.class, "vosk");
                findWordOk = true;
            }
            if (!findWordOk) return null;
            return VoskExt.vosk_model_find_word(m.getPointer(), word) >= 0;
        } catch (Throwable t) {
            Log.w(TAG, "vocabulary check unavailable", t);
            findWordOk = false;
            return null;
        }
    }

    /** Direct JNA mapping for the one C function the Java wrapper doesn't expose. */
    public static final class VoskExt {
        public static native int vosk_model_find_word(Pointer model, String word);
    }

    private static void copyAssetDir(AssetManager am, String assetPath, File dest) throws IOException {
        String[] children = am.list(assetPath);
        if (children == null || children.length == 0) {
            // It's a file
            File parent = dest.getParentFile();
            if (parent != null && !parent.exists() && !parent.mkdirs()) throw new IOException("mkdir " + parent);
            try (InputStream in = am.open(assetPath); OutputStream out = new FileOutputStream(dest)) {
                byte[] buf = new byte[64 * 1024];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
            return;
        }
        if (!dest.exists() && !dest.mkdirs()) throw new IOException("mkdir " + dest);
        for (String child : children) {
            copyAssetDir(am, assetPath + "/" + child, new File(dest, child));
        }
    }

    private static void deleteRecursive(File f) {
        if (!f.exists()) return;
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteRecursive(k);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }
}
