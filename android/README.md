# Name Alert for Android

The phone version of Name Alert. It listens for your name in the background and alerts you with:

- a **chime in your earbuds** (your music ducks for a moment)
- a **vibration** pattern
- a **full-screen red flash** that wakes the screen, even on the lock screen

Speech recognition runs entirely on the phone (Vosk). No audio is saved or sent anywhere.

## Install

1. On your phone, download `NameAlert-android.apk` from the [Releases](../../releases) page.
2. Open it. Android will ask you to allow installs from your browser or file manager. Allow it, then tap **Install**.
3. Open Name Alert, enter your name(s), tap **Save**, then **Start listening**.
4. Allow **microphone** and **notifications** when asked.
5. On Android 14+, tap **Open setting** in the app and turn on **full-screen notifications** so the flash can wake the screen.

A notification stays up while it's listening, with **Pause** and **Stop** buttons.

## How it's built

- `www/` + `src/app.js`: the settings screen (Capacitor web UI, bundled with esbuild)
- `native/`: the Android code
  - `ListenerService`: microphone foreground service running Vosk with a small grammar (your names + sound-alike decoys)
  - `Alerts` / `AlertActivity`: chime, vibration, full-screen flash
  - `NameAlertPlugin`: the bridge between the UI and the service
- `scripts/patch_android.py`: merges `native/` into the Capacitor project that CI generates
- `debug.keystore`: a public, debug-only signing key, so each new APK installs over the previous one

The APK is built by GitHub Actions (`.github/workflows/android.yml`) on every `v*` tag, or manually from the Actions tab.
