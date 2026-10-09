"""
Name Alert - flashes your screen when someone says your name.

Built for people who wear earbuds at work. Runs in the system tray, listens
with an offline speech model (Vosk), and flashes a colored border on every
monitor when it hears one of your names. No audio is ever saved or sent
anywhere; the log only records which words matched and how confident the
model was.

Run from source:
    py -m pip install -r requirements.txt
    (download + unzip the model next to this file, see README.md)
    py name_alert.py            console mode (shows log lines)
    pyw name_alert.py           no console
    py name_alert.py --test     flash once and exit
"""

import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import winreg
import winsound
from array import array
from collections import deque
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk

APP_NAME = "Name Alert"
APP_VERSION = "1.0.1"

# ----------------------------------------------------------------- paths
FROZEN = getattr(sys, "frozen", False)  # True when running as the PyInstaller .exe
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
MODEL_NAME = "vosk-model-small-en-us-0.15"
DATA_DIR = Path(os.environ.get("APPDATA", str(APP_DIR))) / "NameAlert"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_FILE = DATA_DIR / "name_alert.log"

SAMPLE_RATE = 16000
BLOCK_SIZE = 2000                  # 0.125 s of audio per chunk
TRANSPARENT_KEY = "#010203"        # color Windows treats as see-through
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

SENS_PRESETS = [("High (catches more)", 0.60),
                ("Medium", 0.72),
                ("Low (fewer false alarms)", 0.85)]

DEFAULTS = {
    "wake_words": [],
    # Sound-alike words give the recognizer somewhere to put "seven", "even"...
    # instead of forcing them into your name. Edit these for your own name.
    "decoy_words": ["seven", "seventeen", "even", "evening", "eleven", "evan",
                    "eve", "steep", "stephanie", "stevens", "stevenson", "heaven",
                    "sleeve", "believe", "leave", "receive", "these"],
    "min_conf": 0.72,
    "mic_name": "",                # "" = Windows default mic
    "mic_gain": 1.0,
    "cooldown_sec": 5.0,
    "start_enabled": True,
    "flash_seconds": 3.0,
    "flash_interval_ms": 250,
    "border_px": 18,
    "border_color": "#FF0000",
    "show_text": True,
    "alert_text": "SOMEONE SAID YOUR NAME",
    "play_sound": True,
}


# ----------------------------------------------------------------- settings / log
def load_settings():
    s = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for k in DEFAULTS:
            if k in saved and type(saved[k]) is type(DEFAULTS[k]):
                s[k] = saved[k]
            elif k in saved and isinstance(DEFAULTS[k], float) and isinstance(saved[k], int):
                s[k] = float(saved[k])
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


HISTORY = deque(maxlen=200)       # recent log lines for the main window
HISTORY_COUNT = [0]               # increments on every log line
_log_lock = threading.Lock()


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line)
    HISTORY.append(line)
    HISTORY_COUNT[0] += 1
    try:
        with _log_lock:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        pass


def trim_log():
    """Keep the log from growing forever (rolls over at 1 MB)."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
            old = LOG_FILE.with_suffix(".old.log")
            if old.exists():
                old.unlink()
            LOG_FILE.rename(old)
    except OSError:
        pass


def parse_words(text):
    """'Steven, Steve\\nstevie' -> ['steven', 'steve', 'stevie'] (single words only)."""
    out = []
    for w in re.split(r"[,\s]+", text.lower()):
        if re.fullmatch(r"[a-z']+", w) and w not in out:
            out.append(w)
    return out


def find_model():
    for base in (BUNDLE_DIR, APP_DIR):
        p = base / MODEL_NAME
        if p.is_dir():
            return p
    return None


# ----------------------------------------------------------------- Windows helpers
user32 = ctypes.windll.user32
user32.GetParent.restype = wt.HWND
user32.GetParent.argtypes = [wt.HWND]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020     # mouse clicks pass through
WS_EX_TOOLWINDOW = 0x00000080      # no taskbar button
WS_EX_NOACTIVATE = 0x08000000      # never steals focus


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def get_monitors():
    monitors = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def _cb(hmon, hdc, lprect, lparam):
        r = lprect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    callback = MonitorEnumProc(_cb)
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return monitors or [(0, 0, 1920, 1080)]


def make_click_through(win):
    hwnd = user32.GetParent(win.winfo_id())
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


_mutex_handle = None


def already_running():
    """Named mutex so only one copy runs (e.g. startup + manual launch)."""
    global _mutex_handle
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wt.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    _mutex_handle = k32.CreateMutexW(None, False, "Local\\NameAlertSingleInstance")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def startup_command():
    if FROZEN:
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else exe}" "{Path(__file__).resolve()}"'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# ----------------------------------------------------------------- audio helpers
def list_input_devices():
    """Mic names from the MME host API (one entry per mic, no duplicates)."""
    try:
        import sounddevice as sd
        mme = [i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "MME"]
        names = []
        for d in sd.query_devices():
            if d["max_input_channels"] > 0 and (not mme or d["hostapi"] in mme):
                if d["name"] not in names and "Sound Mapper" not in d["name"]:
                    names.append(d["name"])
        return names
    except Exception:
        return []


def resolve_device(name):
    """Mic name -> device index (names survive reboots; indexes don't)."""
    if not name:
        return None
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_input_channels"] > 0:
            return i
    log(f"Mic '{name}' not found - using Windows default")
    return None


def process_block(data, gain):
    """Apply gain (if any) and return (bytes, level 0-100)."""
    a = array("h")
    a.frombytes(data)
    if gain != 1.0:
        for i, s in enumerate(a):
            v = int(s * gain)
            a[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
        data = a.tobytes()
    n = len(a) or 1
    rms = math.sqrt(sum(s * s for s in a) / n) / 32768.0
    db = 20.0 * math.log10(rms + 1e-9)          # -inf..0 dBFS
    level = max(0.0, min(100.0, (db + 60.0) / 60.0 * 100.0))
    return data, level


# ----------------------------------------------------------------- overlay
class Overlay:
    """One invisible, click-through, always-on-top window per monitor.
    Flashing only changes opacity, so it never steals focus."""

    def __init__(self, app):
        self.app = app
        self.windows = []
        self.monitors = None
        self.flashing = False
        self.build()

    def build(self):
        for w in self.windows:
            w.destroy()
        self.windows = []
        s = self.app.settings
        self.monitors = get_monitors()
        for (x, y, w, h) in self.monitors:
            win = tk.Toplevel(self.app.root)
            win.overrideredirect(True)
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.configure(bg=TRANSPARENT_KEY)
            win.attributes("-topmost", True)
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
            win.attributes("-alpha", 0.0)
            c = tk.Canvas(win, width=w, height=h, bg=TRANSPARENT_KEY, highlightthickness=0)
            c.pack()
            bp = int(s["border_px"])
            half = bp // 2
            c.create_rectangle(half, half, w - half, h - half,
                               outline=s["border_color"], width=bp)
            if s["show_text"] and s["alert_text"].strip():
                c.create_text(w // 2, bp + 40, text=s["alert_text"],
                              fill=s["border_color"], font=("Segoe UI", 28, "bold"))
            win.update_idletasks()
            make_click_through(win)
            self.windows.append(win)

    def _set_alpha(self, a):
        for win in self.windows:
            win.attributes("-alpha", a)

    def flash(self):
        if self.flashing:
            return
        if get_monitors() != self.monitors:     # docked/undocked since last build
            self.build()
        self.flashing = True
        s = self.app.settings
        interval = int(s["flash_interval_ms"])
        steps = max(2, int(float(s["flash_seconds"]) * 1000 / interval))
        steps += steps % 2  # even -> starts visible, ends hidden
        self._step(steps, interval)

    def _step(self, remaining, interval):
        if remaining <= 0:
            self._set_alpha(0.0)
            self.flashing = False
            return
        self._set_alpha(0.9 if remaining % 2 == 0 else 0.0)
        self.app.root.after(interval, self._step, remaining - 1, interval)


# ----------------------------------------------------------------- listener thread
class Listener(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app

    def run(self):
        app = self.app
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model_dir = find_model()
            if model_dir is None:
                app.ui_q.put(("fatal", f"Speech model folder '{MODEL_NAME}' not found.\n"
                                       f"Looked in:\n{BUNDLE_DIR}\n{APP_DIR}"))
                return
            app.model = Model(str(model_dir))
        except Exception as e:
            app.ui_q.put(("fatal", f"Could not start speech engine:\n{type(e).__name__}: {e}"))
            return

        while not app.stop_evt.is_set():
            app.reload_evt.clear()
            s = dict(app.settings)               # snapshot
            wake = s["wake_words"]
            if not app.enabled.is_set() or not wake:
                app.level = 0.0
                time.sleep(0.2)
                continue

            decoys = [d for d in s["decoy_words"] if d not in wake]
            grammar = json.dumps(wake + decoys + ["[unk]"])
            try:
                rec = KaldiRecognizer(app.model, SAMPLE_RATE, grammar)
                rec.SetWords(True)
                audio_q = queue.Queue()

                def on_audio(indata, frames, time_info, status):
                    audio_q.put(bytes(indata))

                with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                                       device=resolve_device(s["mic_name"]), dtype="int16",
                                       channels=1, callback=on_audio):
                    log(f"Mic ON  names={wake}  min conf={s['min_conf']:.2f}  "
                        f"gain={s['mic_gain']}  mic={s['mic_name'] or 'default'}")
                    unknown = [w for w in wake + decoys
                               if app.model.vosk_model_find_word(w) < 0]
                    if unknown:
                        log(f"Not in vocabulary (ignored): {unknown}")
                    hb_t, hb_sum, hb_n, hb_peak, hb_phr = time.monotonic(), 0.0, 0, 0.0, 0
                    while (app.enabled.is_set() and not app.stop_evt.is_set()
                           and not app.reload_evt.is_set()):
                        if time.monotonic() - hb_t >= 60:   # once a minute: is audio arriving?
                            log(f"audio  avg level {hb_sum / max(hb_n, 1):.0f}%  "
                                f"peak {hb_peak:.0f}%  phrases heard {hb_phr}")
                            if hb_n == 0 or hb_peak < 5:
                                log("WARNING: microphone seems silent - check mic selection, "
                                    "mute, or Windows microphone privacy settings")
                            hb_t, hb_sum, hb_n, hb_peak, hb_phr = time.monotonic(), 0.0, 0, 0.0, 0
                        try:
                            data = audio_q.get(timeout=0.3)
                        except queue.Empty:
                            continue
                        data, app.level = process_block(data, float(s["mic_gain"]))
                        hb_sum += app.level
                        hb_n += 1
                        hb_peak = max(hb_peak, app.level)
                        if rec.AcceptWaveform(data):
                            r = json.loads(rec.Result())
                            if r.get("text"):
                                hb_phr += 1
                            self.check(r, s)
                app.level = 0.0
                log("Mic OFF" if not app.reload_evt.is_set() else "Settings changed - restarting mic")
            except Exception as e:
                app.level = 0.0
                app.enabled.clear()
                app.ui_q.put(("mic_error", f"{type(e).__name__}: {e}"))

    def check(self, result, s):
        fired = False
        for w in result.get("result", []):
            word = w.get("word", "")
            conf = float(w.get("conf", 0.0))
            if word in s["wake_words"]:
                hit = conf >= s["min_conf"] and not fired
                log(f"NAME   '{word}'  conf={conf:.2f}  "
                    f"{'-> ALERT' if hit else '(below threshold)'}  [min {s['min_conf']:.2f}]")
                if hit:
                    self.app.ui_q.put(("alert",))
                    fired = True
            elif word in s["decoy_words"]:
                log(f"decoy  '{word}'  conf={conf:.2f}")


# ----------------------------------------------------------------- main window
class MainWindow:
    def __init__(self, app, tab=0):
        self.app = app
        s = app.settings
        self.win = tk.Toplevel(app.root)
        self.win.title(f"{APP_NAME} {APP_VERSION}")
        self.win.minsize(520, 460)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.shown_count = -1

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        pad = {"padx": 8, "pady": 4}

        # ---- Status tab
        t = ttk.Frame(nb)
        nb.add(t, text="Status")
        self.toggle_btn = tk.Button(t, font=("Segoe UI", 12, "bold"), fg="white",
                                    command=self.toggle, height=2)
        self.toggle_btn.pack(fill="x", **pad)
        lf = ttk.Frame(t)
        lf.pack(fill="x", **pad)
        ttk.Label(lf, text="Mic level:").pack(side="left")
        self.level_bar = ttk.Progressbar(lf, maximum=100)
        self.level_bar.pack(side="left", fill="x", expand=True, padx=6)
        self.status_lbl = ttk.Label(t, foreground="#444")
        self.status_lbl.pack(anchor="w", **pad)
        self.mic_warn = ttk.Label(t, foreground="#d00000", wraplength=480)
        self.mic_warn.pack(anchor="w", padx=8)
        self.quiet_since = None
        ttk.Label(t, text="Recent activity (NAME = your name, decoy = sound-alike):").pack(
            anchor="w", padx=8)
        hf = ttk.Frame(t)
        hf.pack(fill="both", expand=True, **pad)
        self.history = tk.Listbox(hf, font=("Consolas", 9), height=10)
        sb = ttk.Scrollbar(hf, command=self.history.yview)
        self.history.configure(yscrollcommand=sb.set)
        self.history.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        bf = ttk.Frame(t)
        bf.pack(fill="x", **pad)
        ttk.Button(bf, text="Test flash", command=app.test_flash).pack(side="left")
        ttk.Button(bf, text="Open log file", command=app.open_log).pack(side="left", padx=6)

        # ---- Names tab
        t = ttk.Frame(nb)
        nb.add(t, text="Names")
        ttk.Label(t, text="Your name(s) and nicknames - single words, comma or line separated:"
                  ).pack(anchor="w", **pad)
        self.wake_txt = tk.Text(t, height=3, font=("Segoe UI", 10))
        self.wake_txt.insert("1.0", ", ".join(s["wake_words"]))
        self.wake_txt.pack(fill="x", **pad)
        self.wake_vocab_lbl = ttk.Label(t, wraplength=480)
        self.wake_vocab_lbl.pack(anchor="w", padx=8)
        ttk.Label(t, text="Sound-alike decoys (reduce false alarms; words that sound like "
                          "your name):", wraplength=480).pack(anchor="w", **pad)
        self.decoy_txt = tk.Text(t, height=5, font=("Segoe UI", 10))
        self.decoy_txt.insert("1.0", ", ".join(s["decoy_words"]))
        self.decoy_txt.pack(fill="x", **pad)
        self.decoy_vocab_lbl = ttk.Label(t, wraplength=480)
        self.decoy_vocab_lbl.pack(anchor="w", padx=8)
        ttk.Label(t, text="Words in red are not in the speech model's vocabulary and will "
                          "be ignored. Try a different spelling or a nickname.",
                  foreground="#666", wraplength=480).pack(anchor="w", **pad)
        self._vocab_job = None
        for txt in (self.wake_txt, self.decoy_txt):
            txt.tag_configure("bad", foreground="#d00000", underline=True)
            txt.bind("<KeyRelease>", self.schedule_vocab_check)

        # ---- Audio tab
        t = ttk.Frame(nb)
        nb.add(t, text="Audio")
        ttk.Label(t, text="Microphone:").pack(anchor="w", **pad)
        mf = ttk.Frame(t)
        mf.pack(fill="x", **pad)
        self.mic_var = tk.StringVar()
        self.mic_cb = ttk.Combobox(mf, textvariable=self.mic_var, state="readonly")
        self.mic_cb.pack(side="left", fill="x", expand=True)
        ttk.Button(mf, text="Refresh", command=self.refresh_mics).pack(side="left", padx=6)
        self.refresh_mics()
        self.mic_var.set(s["mic_name"] or "(Windows default)")
        ttk.Label(t, text="Sensitivity (minimum confidence) - lower catches more, "
                          "higher gives fewer false alarms:", wraplength=480).pack(anchor="w", **pad)
        self.conf_var = tk.DoubleVar(value=s["min_conf"])
        tk.Scale(t, variable=self.conf_var, from_=0.40, to=0.95, resolution=0.01,
                 orient="horizontal").pack(fill="x", **pad)
        ttk.Label(t, text="Mic gain (software boost - try 2.0 if distant voices are missed):"
                  ).pack(anchor="w", **pad)
        self.gain_var = tk.DoubleVar(value=s["mic_gain"])
        tk.Scale(t, variable=self.gain_var, from_=1.0, to=4.0, resolution=0.1,
                 orient="horizontal").pack(fill="x", **pad)
        cf = ttk.Frame(t)
        cf.pack(fill="x", **pad)
        ttk.Label(cf, text="Cooldown between alerts (s):").pack(side="left")
        self.cool_var = tk.StringVar(value=str(s["cooldown_sec"]))
        ttk.Spinbox(cf, from_=0, to=60, increment=1, width=6,
                    textvariable=self.cool_var).pack(side="left", padx=6)

        # ---- Alert tab
        t = ttk.Frame(nb)
        nb.add(t, text="Alert")
        cf = ttk.Frame(t)
        cf.pack(fill="x", **pad)
        ttk.Label(cf, text="Border color:").pack(side="left")
        self.color = s["border_color"]
        self.swatch = tk.Label(cf, width=4, bg=self.color, relief="solid", bd=1)
        self.swatch.pack(side="left", padx=6)
        ttk.Button(cf, text="Choose...", command=self.pick_color).pack(side="left")
        self.border_var = tk.StringVar(value=str(s["border_px"]))
        self.flash_var = tk.StringVar(value=str(s["flash_seconds"]))
        for label, var, lo, hi, inc in (("Border thickness (px):", self.border_var, 4, 80, 2),
                                        ("Flash length (s):", self.flash_var, 1, 15, 0.5)):
            f = ttk.Frame(t)
            f.pack(fill="x", **pad)
            ttk.Label(f, text=label, width=22).pack(side="left")
            ttk.Spinbox(f, from_=lo, to=hi, increment=inc, width=6,
                        textvariable=var).pack(side="left")
        self.show_text_var = tk.BooleanVar(value=s["show_text"])
        ttk.Checkbutton(t, text="Show text at top of screen",
                        variable=self.show_text_var).pack(anchor="w", **pad)
        self.text_var = tk.StringVar(value=s["alert_text"])
        ttk.Entry(t, textvariable=self.text_var).pack(fill="x", **pad)
        self.sound_var = tk.BooleanVar(value=s["play_sound"])
        ttk.Checkbutton(t, text="Play Windows chime (you hear it in your earbuds)",
                        variable=self.sound_var).pack(anchor="w", **pad)
        ttk.Label(t, text="Tip: click Save & Apply, then Test flash on the Status tab.",
                  foreground="#666").pack(anchor="w", **pad)

        # ---- General tab
        t = ttk.Frame(nb)
        nb.add(t, text="General")
        self.startup_var = tk.BooleanVar(value=startup_enabled())
        ttk.Checkbutton(t, text="Start Name Alert when I sign in to Windows",
                        variable=self.startup_var, command=self.toggle_startup
                        ).pack(anchor="w", **pad)
        self.start_en_var = tk.BooleanVar(value=s["start_enabled"])
        ttk.Checkbutton(t, text="Start listening automatically when the app opens",
                        variable=self.start_en_var).pack(anchor="w", **pad)
        ttk.Button(t, text="Open settings/log folder",
                   command=lambda: self.app.open_path(DATA_DIR)).pack(anchor="w", **pad)
        ttk.Label(t, text=f"{APP_NAME} {APP_VERSION}\nSpeech recognition runs entirely on "
                          f"this PC (Vosk). No audio is saved or sent anywhere.\n"
                          f"Settings: {SETTINGS_FILE}", foreground="#666",
                  wraplength=480, justify="left").pack(anchor="w", **pad)

        # ---- bottom buttons
        bb = ttk.Frame(self.win)
        bb.pack(fill="x", padx=8, pady=8)
        self.save_lbl = ttk.Label(bb, foreground="#080")
        self.save_lbl.pack(side="left")
        ttk.Button(bb, text="Close", command=self.close).pack(side="right")
        ttk.Button(bb, text="Save & Apply", command=self.save).pack(side="right", padx=6)

        nb.select(tab)
        self.refresh_status()
        self.poll()
        self.check_words()
        self.win.lift()
        self.win.focus_force()

    # -- helpers
    def refresh_mics(self):
        self.mic_cb["values"] = ["(Windows default)"] + list_input_devices()

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self.win)[1]
        if c:
            self.color = c
            self.swatch.configure(bg=c)

    def toggle(self):
        self.app.set_enabled(not self.app.enabled.is_set())

    def toggle_startup(self):
        if not set_startup(self.startup_var.get()):
            messagebox.showerror(APP_NAME, "Could not change the Windows startup setting.",
                                 parent=self.win)
            self.startup_var.set(startup_enabled())

    def schedule_vocab_check(self, event=None):
        if self._vocab_job:
            self.win.after_cancel(self._vocab_job)
        self._vocab_job = self.win.after(300, self.check_words)

    def check_words(self):
        """Underline unknown words in red inside both boxes + summary under each."""
        self._vocab_job = None
        if self.win is None:
            return
        model = self.app.model
        for txt, lbl in ((self.wake_txt, self.wake_vocab_lbl),
                         (self.decoy_txt, self.decoy_vocab_lbl)):
            txt.tag_remove("bad", "1.0", "end")
            if model is None:
                lbl.configure(text="Checking vocabulary once the speech model loads...",
                              foreground="#666")
                continue
            content = txt.get("1.0", "end-1c")
            bad, good = [], 0
            for m in re.finditer(r"[A-Za-z']+", content):
                w = m.group(0).lower()
                if model.vosk_model_find_word(w) < 0:
                    txt.tag_add("bad", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
                    if w not in bad:
                        bad.append(w)
                else:
                    good += 1
            if bad:
                lbl.configure(text="\u2717 Not in vocabulary (ignored): " + ", ".join(bad),
                              foreground="#d00000")
            elif good:
                lbl.configure(text=f"\u2713 All {good} words recognized", foreground="#080")
            else:
                lbl.configure(text="")
        if model is None:
            self._vocab_job = self.win.after(1000, self.check_words)

    def refresh_status(self, update_slider=False):
        on = self.app.enabled.is_set()
        names = self.app.settings["wake_words"]
        self.toggle_btn.configure(
            text="LISTENING - click to pause" if on else "PAUSED - click to listen",
            bg="#1a9c1a" if on else "#777", activebackground="#148014" if on else "#666")
        if not names:
            msg = "No names set yet - add yours on the Names tab, then Save & Apply."
        else:
            msg = (f"Listening for: {', '.join(names)}    |    "
                   f"Sensitivity: {self.app.settings['min_conf']:.2f}")
        self.status_lbl.configure(text=msg)
        if update_slider:
            self.conf_var.set(self.app.settings["min_conf"])

    def poll(self):
        if self.win is None:
            return
        self.level_bar["value"] = self.app.level
        # Warn if listening but the mic has been dead silent for 8+ seconds
        if self.app.enabled.is_set() and self.app.settings["wake_words"] and self.app.level < 3:
            self.quiet_since = self.quiet_since or time.monotonic()
            if time.monotonic() - self.quiet_since > 8:
                self.mic_warn.configure(
                    text="No sound from the microphone. Check the mic on the Audio tab, "
                         "your mute switch/key, and Windows Settings > Privacy > Microphone.")
        else:
            self.quiet_since = None
            self.mic_warn.configure(text="")
        if HISTORY_COUNT[0] != self.shown_count:
            self.shown_count = HISTORY_COUNT[0]
            self.history.delete(0, "end")
            for line in list(HISTORY):   # copy: listener thread may append meanwhile
                self.history.insert("end", line)
            self.history.see("end")
        self.win.after(100, self.poll)

    def save(self):
        s = dict(self.app.settings)
        try:
            s["wake_words"] = parse_words(self.wake_txt.get("1.0", "end"))
            s["decoy_words"] = parse_words(self.decoy_txt.get("1.0", "end"))
            mic = self.mic_var.get()
            s["mic_name"] = "" if mic.startswith("(") else mic
            s["min_conf"] = round(float(self.conf_var.get()), 2)
            s["mic_gain"] = round(float(self.gain_var.get()), 1)
            s["cooldown_sec"] = max(0.0, float(self.cool_var.get()))
            s["border_color"] = self.color
            s["border_px"] = max(2, min(200, int(float(self.border_var.get()))))
            s["flash_seconds"] = max(0.5, min(30.0, float(self.flash_var.get())))
            s["show_text"] = bool(self.show_text_var.get())
            s["alert_text"] = self.text_var.get()
            s["play_sound"] = bool(self.sound_var.get())
            s["start_enabled"] = bool(self.start_en_var.get())
        except ValueError:
            messagebox.showerror(APP_NAME, "One of the number fields isn't a valid number.",
                                 parent=self.win)
            return
        self.app.apply_settings(s)
        self.save_lbl.configure(text=f"Saved {time.strftime('%H:%M:%S')}")
        self.refresh_status()
        self.check_words()

    def close(self):
        w, self.win = self.win, None
        w.destroy()
        self.app.main_win = None


# ----------------------------------------------------------------- app
class App:
    def __init__(self):
        trim_log()
        self.first_run = not SETTINGS_FILE.exists()
        self.settings = load_settings()
        self.enabled = threading.Event()
        self.stop_evt = threading.Event()
        self.reload_evt = threading.Event()
        self.ui_q = queue.Queue()
        self.model = None
        self.level = 0.0
        self.last_alert = 0.0
        self.main_win = None
        self.icon = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = Overlay(self)

    # -- actions (main thread)
    def set_enabled(self, on):
        if on:
            self.enabled.set()
        else:
            self.enabled.clear()
        self.refresh_icon()
        if self.main_win:
            self.main_win.refresh_status()

    def apply_settings(self, s):
        self.settings = s
        if not save_settings(s):
            messagebox.showerror(APP_NAME, f"Could not save settings to\n{SETTINGS_FILE}")
        self.overlay.build()
        self.reload_evt.set()
        self.refresh_icon()

    def test_flash(self):
        self.overlay.flash()
        if self.settings["play_sound"]:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)

    def open_path(self, p):
        try:
            Path(p).mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))
        except OSError:
            pass

    def open_log(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if not LOG_FILE.exists():
                LOG_FILE.write_text("", encoding="utf-8")
            os.startfile(str(LOG_FILE))
        except OSError:
            pass

    def show_main(self, tab=0):
        if self.main_win is None:
            self.main_win = MainWindow(self, tab)
        else:
            self.main_win.win.deiconify()
            self.main_win.win.lift()
            self.main_win.win.focus_force()

    def quit(self):
        self.stop_evt.set()
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        self.root.destroy()

    # -- tray (runs in its own thread; only posts messages to the UI queue)
    def refresh_icon(self):
        if not self.icon:
            return
        on = self.enabled.is_set()
        self.icon.icon = self.img_on if on else self.img_off
        names = ", ".join(self.settings["wake_words"]) or "no names set"
        self.icon.title = f"{APP_NAME}: {'LISTENING' if on else 'PAUSED'} ({names})"[:127]

    def start_tray(self):
        import pystray
        from PIL import Image, ImageDraw

        def dot(color):
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse((6, 6, 58, 58), fill=color, outline="white", width=4)
            return img

        self.img_on = dot((0, 200, 0, 255))
        self.img_off = dot((128, 128, 128, 255))
        post = self.ui_q.put

        def sens_item(label, value):
            return pystray.MenuItem(
                label, lambda icon, item: post(("set_sens", value)), radio=True,
                checked=lambda item: abs(self.settings["min_conf"] - value) < 0.005)

        menu = pystray.Menu(
            pystray.MenuItem("Listening", lambda icon, item: post(("toggle",)),
                             checked=lambda item: self.enabled.is_set(), default=True),
            pystray.MenuItem("Sensitivity", pystray.Menu(
                *[sens_item(lbl, v) for lbl, v in SENS_PRESETS])),
            pystray.MenuItem("Test flash", lambda icon, item: post(("test",))),
            pystray.MenuItem(f"Open {APP_NAME}...", lambda icon, item: post(("show",))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: post(("quit",))),
        )
        self.icon = pystray.Icon("name_alert", self.img_off, APP_NAME, menu)
        self.refresh_icon()
        threading.Thread(target=self.icon.run, daemon=True).start()

    # -- UI message pump
    def poll(self):
        try:
            while True:
                msg = self.ui_q.get_nowait()
                kind = msg[0]
                if kind == "alert" and self.enabled.is_set():
                    now = time.monotonic()
                    if now - self.last_alert >= float(self.settings["cooldown_sec"]):
                        self.last_alert = now
                        self.test_flash()
                elif kind == "toggle":
                    self.set_enabled(not self.enabled.is_set())
                elif kind == "set_sens":
                    s = dict(self.settings)
                    s["min_conf"] = msg[1]
                    self.apply_settings(s)
                    log(f"Sensitivity -> {msg[1]:.2f}")
                    if self.main_win:
                        self.main_win.refresh_status(update_slider=True)
                elif kind == "test":
                    self.test_flash()
                elif kind == "show":
                    self.show_main()
                elif kind == "quit":
                    self.quit()
                    return
                elif kind == "mic_error":
                    self.refresh_icon()
                    if self.main_win:
                        self.main_win.refresh_status()
                    messagebox.showerror(APP_NAME, "Microphone problem - listening paused.\n\n"
                                         f"{msg[1]}\n\nPick a different mic in "
                                         f"{APP_NAME} > Audio, then turn listening back on.")
                elif kind == "fatal":
                    messagebox.showerror(APP_NAME, msg[1])
                    self.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def run(self):
        self.start_tray()
        if self.settings["start_enabled"]:
            self.set_enabled(True)
        Listener(self).start()
        self.root.after(50, self.poll)
        if self.first_run or not self.settings["wake_words"]:
            self.root.after(300, lambda: self.show_main(tab=1))   # open on the Names tab
        log(f"{APP_NAME} {APP_VERSION} started")
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.quit()


def main():
    if "--list-mics" in sys.argv:
        for n in list_input_devices():
            print(n)
        return
    set_dpi_aware()
    if "--test" in sys.argv:
        app = App()
        app.root.after(300, app.overlay.flash)
        app.root.after(int(app.settings["flash_seconds"] * 1000) + 800, app.root.destroy)
        app.root.mainloop()
        return
    if already_running():
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(APP_NAME, f"{APP_NAME} is already running - look for the dot "
                                      f"in the system tray (click ^ by the clock).")
        r.destroy()
        return
    App().run()


if __name__ == "__main__":
    main()
