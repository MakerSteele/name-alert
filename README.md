# Name Alert

Wear earbuds at work without people having to throw things at you.

Name Alert runs in the Windows system tray, listens for **your name**, and flashes a
colored border on every monitor (plus an optional chime in your earbuds) when someone
says it.

- **100% offline.** Speech recognition runs on your PC with [Vosk](https://alphacephei.com/vosk/).
  No audio is saved or sent anywhere. The log only records which words matched and
  the model's confidence.
- **Never steals focus.** The flash is a click-through overlay, so it won't interrupt
  whatever you're typing in.
- **Easy on/off.** Green tray dot = listening, gray = paused (mic fully closed).
  Double-click the dot to toggle.

## Install (no Python needed)

1. Download `NameAlert-win64.zip` from the [Releases](../../releases) page.
2. Unzip it anywhere (e.g. `Documents\NameAlert`).
3. Run `NameAlert.exe`.
   - Windows SmartScreen may say "Windows protected your PC" because the app isn't
     code-signed. Click **More info → Run anyway**.
4. The first time, the settings window opens on the **Names** tab. Enter your name and
   any nicknames, click **Check words against speech model**, then **Save & Apply**.

> Using this at work? Check with your IT department first. Some companies don't allow
> always-on microphone software, even when it's fully offline.

## Using it

**Tray menu** (right-click the dot): Listening on/off, Sensitivity (High / Medium / Low),
Test flash, Open Name Alert…, Quit.

**Main window** tabs:

| Tab | What's there |
|---|---|
| Status | Big on/off button, live mic level meter, recent detections |
| Names | Your names/nicknames, sound-alike "decoy" words, vocabulary check |
| Audio | Microphone, sensitivity slider, software gain, cooldown |
| Alert | Border color/thickness, flash length, on-screen text, chime |
| General | Start with Windows, start listening on launch, settings folder |

Settings and the log are stored in `%APPDATA%\NameAlert\`.

## Tuning

Watch the **Status** tab (or the log) for a day:

- **It misses you** → lower the sensitivity, raise mic gain, or check Windows mic input
  volume. Many laptops have "voice focus / personal mode" noise suppression that blocks
  voices that aren't right in front of you. Turn it off or use "conference" mode.
- **False alarms** → raise the sensitivity, and add words that sound like your name to
  **decoys** (for "Steven": seven, even, eleven, heaven...). Decoys give the recognizer
  somewhere else to put those sounds.
- **Name not recognized** → the small English model doesn't know every name. If the
  vocabulary check flags yours, try a nickname or a common spelling.

## Build from source

Requires Windows and Python 3.10+.

```bat
install.bat      :: run from source (creates a desktop shortcut)
build.bat        :: build dist\NameAlert-win64.zip with PyInstaller
```

Pushing a tag like `v1.0.0` runs the GitHub Actions workflow, which builds the zip and
attaches it to a Release automatically.

## Credits & licenses

- Name Alert: MIT (see `LICENSE`)
- [Vosk](https://github.com/alphacep/vosk-api) and the `vosk-model-small-en-us-0.15`
  model: Apache 2.0
- [sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT) / PortAudio
- [pystray](https://github.com/moses-palmer/pystray): LGPL-3.0
- [Pillow](https://github.com/python-pillow/Pillow): MIT-CMU
