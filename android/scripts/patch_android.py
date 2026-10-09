"""
Runs in CI after `npx cap add android`. Merges Name Alert's native code into the
freshly generated Capacitor Android project:
  - copies native/*.java into the app package
  - adds permissions, the microphone foreground service and the alert activity to the manifest
  - adds Vosk + JNA dependencies, a fixed debug signing key and the version to app/build.gradle
Every edit asserts its anchor exists, so a Capacitor template change fails loudly.
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # android/
APP = os.path.join(ROOT, "android", "app")
PKG_DIR = os.path.join(APP, "src", "main", "java", "com", "makersteele", "namealert")
VERSION = os.environ.get("APP_VERSION", "1.0.0").lstrip("v")
BUILD_NO = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))


def edit(path, anchor, new, count=1):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text.count(anchor) != count:
        sys.exit(f"patch_android: anchor not found {count}x in {path}: {anchor!r}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(anchor, new))


# 1) Java sources
os.makedirs(PKG_DIR, exist_ok=True)
for name in os.listdir(os.path.join(ROOT, "native")):
    if name.endswith(".java"):
        shutil.copy(os.path.join(ROOT, "native", name), os.path.join(PKG_DIR, name))
        print("copied", name)

# 2) Manifest
manifest = os.path.join(APP, "src", "main", "AndroidManifest.xml")
edit(manifest, '<uses-permission android:name="android.permission.INTERNET" />',
     '<uses-permission android:name="android.permission.INTERNET" />\n'
     '    <uses-permission android:name="android.permission.RECORD_AUDIO" />\n'
     '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />\n'
     '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />\n'
     '    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n'
     '    <uses-permission android:name="android.permission.USE_FULL_SCREEN_INTENT" />\n'
     '    <uses-permission android:name="android.permission.VIBRATE" />\n'
     '    <uses-permission android:name="android.permission.WAKE_LOCK" />')
edit(manifest, "    </application>",
     '        <service\n'
     '            android:name=".ListenerService"\n'
     '            android:exported="false"\n'
     '            android:foregroundServiceType="microphone" />\n\n'
     '        <activity\n'
     '            android:name=".AlertActivity"\n'
     '            android:exported="false"\n'
     '            android:excludeFromRecents="true"\n'
     '            android:launchMode="singleInstance"\n'
     '            android:showWhenLocked="true"\n'
     '            android:turnScreenOn="true"\n'
     '            android:theme="@android:style/Theme.Black.NoTitleBar.Fullscreen" />\n'
     "    </application>")

# 3) app/build.gradle
gradle = os.path.join(APP, "build.gradle")
edit(gradle, "versionCode 1", f"versionCode {BUILD_NO}")
edit(gradle, 'versionName "1.0"', f'versionName "{VERSION}"')
edit(gradle, "    buildTypes {",
     "    signingConfigs {\n"
     "        debug {\n"
     "            // Fixed key so new builds install over old ones (settings are kept)\n"
     "            storeFile file('../../debug.keystore')\n"
     "            storePassword 'android'\n"
     "            keyAlias 'androiddebugkey'\n"
     "            keyPassword 'android'\n"
     "        }\n"
     "    }\n"
     "    buildTypes {")
edit(gradle, "    implementation project(':capacitor-android')",
     "    implementation project(':capacitor-android')\n"
     "    implementation 'com.alphacephei:vosk-android:0.3.47@aar'\n"
     "    implementation 'net.java.dev.jna:jna:5.13.0@aar'")

# 4) Model must be in assets/model
model_dir = os.path.join(APP, "src", "main", "assets", "model")
if not os.path.isdir(os.path.join(model_dir, "am")):
    sys.exit("patch_android: speech model missing at " + model_dir)

print(f"patch_android: OK (version {VERSION}, build {BUILD_NO})")
