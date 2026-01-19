# main.py — Robust per-eye blink + head gestures (voice modules improved only)
import cv2
import mediapipe as mp
import pyautogui
pyautogui.FAILSAFE = False
import time
import os
from voice_listener import start_listening, voice_queue
import subprocess
import shlex
from fuzzywuzzy import fuzz, process
import ctypes
SendInput = ctypes.windll.user32.SendInput
from calibration import Calibration
from gaze_tracker import combined_iris_norm, draw_iris_points, iris_pixels
from blink_detection import BlinkDetector
from smoothing import SmoothFilter
from gaze_lock import GazeLockManager
from clickable_finder import collect_clickable_targets
from utils import clamp_step
import threading
import json
import os
_ui_settings_path = "ui_settings.json"
FRAME_CALLBACK = None

# ---------------------------------------------------------------------------
# GLOBAL PROJECT CONFIG
# ---------------------------------------------------------------------------
DEBUG = True
TARGET_SCAN_INTERVAL = 1.4

# screen
screen_w, screen_h = pyautogui.size()

# camera config
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 30)

# Mediapipe FaceMesh
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    refine_landmarks=True,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

# Nose landmark index for head movement (vertical scroll)
NOSE_LANDMARK_INDEX = 1
HEAD_BASE_SMOOTH_ALPHA = 0.92
HEAD_MOVE_THRESHOLD = 0.012
SCROLL_COOLDOWN = 0.10
SCROLL_ACTIVATION = 0.23

DOUBLE_CLICK_WINDOW = 0.55
MAX_DRAG_DURATION = 2.5

def read_ui_settings_once():
    """
    Non-blocking read of UI settings file (if present).
    Returns dict or None. Do not raise.
    """
    try:
        if os.path.exists(_ui_settings_path):
            with open(_ui_settings_path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None

def write_default_ui_settings():
    # call once at startup to provide defaults (optional)
    default = {
        "enable_actions": False,
        "smoothing_window": 6,
        "smoothing_alpha": 0.93,
        "eye_close_thr": 0.018,
        "min_closed_ms": 220,
        "snap_radius": 115,
        "dwell_time": 0.06
    }
    try:
        with open(_ui_settings_path, "w") as f:
            json.dump(default, f)
    except:
        pass

# Optionally call this at startup (safe)
write_default_ui_settings()
# ---------------------------------------------------------------------------
# HELPER FUNCTION
# ---------------------------------------------------------------------------
def get_norm_from_frame():
    ret, frame = cap.read()
    if not ret:
        return None
    frame = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if results.multi_face_landmarks:
        lm = results.multi_face_landmarks[0]
        return combined_iris_norm(lm)
    return None

# ---------------------------------------------------------------------------
# CALIBRATION
# ---------------------------------------------------------------------------
calib = Calibration()

if os.path.exists("calibration_data.json"):
    print("Loading saved calibration...")
    calib.load()
else:
    print("No calibration found. Starting calibration...")
    calib.record_all(get_norm_from_frame, cap)

# ---------------------------------------------------------------------------
# BLINK DETECTOR
# ---------------------------------------------------------------------------
blink = BlinkDetector(
    eye_close_thr=0.018,
    min_closed_ms=220
)

# ---------------------------------------------------------------------------
# SMOOTHER
# ---------------------------------------------------------------------------
smoother = SmoothFilter(ma_window=6, exp_alpha=0.93)

# ---------------------------------------------------------------------------
# GAZE LOCK MANAGER
# ---------------------------------------------------------------------------
lockmgr = GazeLockManager(
    snap_radius_px=115,
    unlock_distance_px=240,
    dwell_time=0.06,
    velocity_threshold=190,
    vel_window=6,
    dead_zone_px=18,
    sustained_away_time=0.25
)

# ---------------------------------------------------------------------------
# TARGET SCANNING
# ---------------------------------------------------------------------------
last_scan = 0
targets_cache = []

def scan_targets(force=False):
    global last_scan, targets_cache
    now = time.time()
    if force or (now - last_scan > TARGET_SCAN_INTERVAL):
        try:
            targets_cache = collect_clickable_targets()
            lockmgr.update_targets(targets_cache)
        except Exception:
            targets_cache = []
        last_scan = now

# ---------------------------------------------------------------------------
# STATE FOR DRAG + SCROLL + CLICKS
# ---------------------------------------------------------------------------
curr_cursor = (screen_w // 2, screen_h // 2)
pyautogui.moveTo(*curr_cursor)

drag_active = False
drag_start_time = 0.0

scroll_mode = False
both_closed_start = None

head_base_y = None
last_scroll_time = 0.0
last_left_click_time = 0.0

# ---------------------------------------------------------------------------
# VOICE: improved safe launcher + fuzzy command handler
# ---------------------------------------------------------------------------

# Use the exact chrome path you provided:
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# App definitions (executable lists)
APP_COMMANDS = {
    "chrome": [CHROME_EXE],
    "google chrome": [CHROME_EXE],
    "browser": [CHROME_EXE],
    "youtube": [CHROME_EXE, "https://www.youtube.com"],
    "yt": [CHROME_EXE, "https://www.youtube.com"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["taskmgr.exe"]
}

APP_KEYS = list(APP_COMMANDS.keys())

# fuzzy matching helpers
def _fuzzy_best(query, choices, score_cutoff=65):
    """Return best key and score or (None,0)."""
    if not query:
        return None, 0
    best = process.extractOne(query, choices, scorer=fuzz.token_set_ratio)
    if not best:
        return None, 0
    name, score = best[0], best[1] if isinstance(best[1], int) else best[1]
    if isinstance(best, tuple) and len(best) >= 2:
        name, score = best[0], best[1]
    if score >= score_cutoff:
        return name, score
    return None, 0

def open_application(name):
    """
    Safe launcher: fuzzy-match app name, launch by exe path (shell=False).
    """
    if not name:
        return
    name = name.lower().strip()

    # direct fuzzy match to known apps
    best, score = _fuzzy_best(name, APP_KEYS, score_cutoff=60)
    if best:
        cmd = APP_COMMANDS[best]
        try:
            subprocess.Popen(cmd, shell=False)
            print(f"[VOICE] Opening app: {best}")
        except Exception as e:
            print("[VOICE] Launch error:", e)
        return

    # if looks like URL/domain
    if name.startswith("http") or "." in name:
        try:
            subprocess.Popen([CHROME_EXE, name], shell=False)
        except Exception as e:
            print("[VOICE] Launch URL error:", e)
        return

    print("[VOICE] Unknown app requested:", name)

# command phrases for matching
CMD_PHRASES = {
    "click": ["click", "left click", "single click", "please click"],
    "double": ["double click", "double-click", "double"],
    "right": ["right click", "right-click", "right"],
    "start_drag": ["start drag", "begin drag", "hold", "grab"],
    "stop_drag": ["stop drag", "end drag", "release drag", "drop", "stop holding"],
    "scroll_up": ["scroll up", "go up", "move up", "up", "scroll higher"],
    "scroll_down": ["scroll down", "go down", "move down", "down", "scroll lower"],
    "lock": ["lock", "lock target", "focus target", "select target"],
    "unlock": ["unlock", "release", "unlock target"],
    "screenshot": ["screenshot", "take screenshot", "capture screen"],
    "center": ["center", "center cursor", "reset cursor"],
    #"close": ["close", "close window", "close this", "close that"],
    "next_window": ["next window", "switch window", "next"],
    "prev_window": ["previous window", "previous", "prev window", "previous window"],
    "mute": ["mute", "unmute"],
    "volume_up": ["volume up", "increase volume", "raise volume"],
    "volume_down": ["volume down", "decrease volume", "lower volume"],
    "close": ["close", "close window", "exit window", "exit"],
    "minimize": ["minimize", "minimise", "minimize window", "minimise window"],
    "maximize": ["maximize", "maximise", "maximize window", "maximise window"],
    "play_pause": ["pause", "play", "play pause", "resume"],
    "refresh": ["refresh", "reload", "reload page"],
    "new_tab": ["new tab", "open new tab"],
    "close_tab": ["close tab", "close this tab"],
    "next_tab": ["next tab", "switch tab"],
    "prev_tab": ["previous tab", "prev tab"],
    "zoom_in": ["zoom in", "increase zoom"],
    "zoom_out": ["zoom out", "decrease zoom"],
    "copy": ["copy"],
    "paste": ["paste"],
    "cut": ["cut"],
    "select_all": ["select all"],
    "next_desktop": ["next desktop", "switch desktop right"],
    "prev_desktop": ["previous desktop", "prev desktop", "switch desktop left"],
}

# tiny state & dedupe
_last_voice_cmd = None
_last_voice_ts = 0.0
DEDUPE_SECONDS = 0.35

def _is_duplicate_and_debounce(cmd):
    global _last_voice_cmd, _last_voice_ts
    now = time.time()
    if cmd == _last_voice_cmd and (now - _last_voice_ts) < DEDUPE_SECONDS:
        return True
    _last_voice_cmd = cmd
    _last_voice_ts = now
    return False
    

def _match_any(cmd, phrases, threshold=68):
    best, score = _fuzzy_best(cmd, phrases, score_cutoff=threshold)
    return best is not None

def _press_media_key(key):
    try:
        pyautogui.press(key)
        return
    except Exception:
        try:
            subprocess.Popen(f"nircmd.exe {key}", shell=True)
        except Exception:
            pass

def _do_alt_f4():
    try:
        pyautogui.hotkey('alt', 'f4')
    except Exception:
        pass

def _do_alt_tab():
    """
    Performs real Alt+Tab using Windows INPUT API.
    """
    # INPUT structure constants
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort),
                    ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", PUL)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong),
                    ("ki", KEYBDINPUT)]

    def press_key(vk):
        ki = KEYBDINPUT(vk, 0, 0, 0, None)
        inp = INPUT(1, ki)
        SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def release_key(vk):
        ki = KEYBDINPUT(vk, 0, 2, 0, None)
        inp = INPUT(1, ki)
        SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    # Real ALT+TAB
    press_key(0x12)   # ALT
    press_key(0x09)   # TAB
    release_key(0x09) # Release TAB
    release_key(0x12) # Release ALT


def _do_shift_alt_tab():
    """
    Performs real Shift+Alt+Tab (go to previous window)
    """
    def press(vk):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)

    def release(vk):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

    press(0x12)   # ALT
    press(0x10)   # SHIFT
    press(0x09)   # TAB
    release(0x09) # TAB
    release(0x10) # SHIFT
    release(0x12) # ALT

def _minimize_window():
    pyautogui.hotkey("winleft", "down")

def _maximize_window():
    pyautogui.hotkey("winleft", "up")

def _play_pause_media():
    pyautogui.press("playpause")

def _refresh_page():
    pyautogui.press("f5")

def _new_tab():
    pyautogui.hotkey("ctrl", "t")

def _close_tab():
    pyautogui.hotkey("ctrl", "w")

def _next_tab():
    pyautogui.hotkey("ctrl", "tab")

def _prev_tab():
    pyautogui.hotkey("ctrl", "shift", "tab")

def _zoom_in():
    pyautogui.hotkey("ctrl", "+") 

def _zoom_out():
    pyautogui.hotkey("ctrl", "-") 

def _copy():
    pyautogui.hotkey("ctrl", "c")

def _paste():
    pyautogui.hotkey("ctrl", "v")

def _cut():
    pyautogui.hotkey("ctrl", "x")

def _select_all():
    pyautogui.hotkey("ctrl", "a")

def _next_desktop():
    pyautogui.hotkey("winleft", "ctrl", "right")

def _prev_desktop():
    pyautogui.hotkey("winleft", "ctrl", "left")


def handle_voice_command(raw_text):
    global drag_active, drag_start_time, scroll_mode, last_scroll_time, head_base_y

    text = (raw_text or "").lower().strip()
    if not text:
        return

    # remove polite prefixes
    for p in ["please ", "could you ", "please", "hey ", "assistant ", "hey assistant "]:
        if text.startswith(p):
            text = text[len(p):].strip()

    print("[VOICE RAW]:", text)

    if _is_duplicate_and_debounce(text):
        return
    # -----------------------------------------------
# STRICT WINDOW MANAGEMENT (NO FUZZY MATCHING)
# -----------------------------------------------

# CLOSE WINDOW (never fuzzy, avoids accidental VS Code closing)
    if text in ["close window", "close this window"]:
        _do_alt_f4()
        return

    # MINIMIZE (using Windows API)
    if text in ["minimize window", "minimize"]:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE = 6
        return

    # MAXIMIZE (using Windows API)
    if text in ["maximize window", "maximize", "restore window"]:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE = 3
        return

    # NEXT WINDOW (strict only)
    if text in ["next window", "switch window", "go next window"]:
        _do_alt_tab()
        return

    # PREVIOUS WINDOW (strict only)
    if text in ["previous window", "go back window", "back window"]:
        _do_shift_alt_tab()
        return

    # direct matches
    if _match_any(text, CMD_PHRASES["click"]):
        pyautogui.click(); return
    if _match_any(text, CMD_PHRASES["double"]):
        pyautogui.doubleClick(); return
    if _match_any(text, CMD_PHRASES["right"]):
        pyautogui.click(button="right"); return

    if _match_any(text, CMD_PHRASES["start_drag"]):
        if not drag_active:
            pyautogui.mouseDown(button="left")
            drag_active = True
            drag_start_time = time.time()
        return
    if _match_any(text, CMD_PHRASES["stop_drag"]):
        if drag_active:
            pyautogui.mouseUp(button="left"); drag_active = False
        return

    if _match_any(text, CMD_PHRASES["scroll_up"]):
        pyautogui.scroll(300); return
    if _match_any(text, CMD_PHRASES["scroll_down"]):
        pyautogui.scroll(-300); return
    if text.strip() == "scroll":
        pyautogui.scroll(-200); return
        # CLOSE WINDOW (Alt+F4 real close)
    if _match_any(text, CMD_PHRASES["close"]):
        _do_alt_f4()
        return

    # MINIMIZE WINDOW
    if _match_any(text, CMD_PHRASES["minimize"]):
        _minimize_window()
        return

    # MAXIMIZE WINDOW
    if _match_any(text, CMD_PHRASES["maximize"]):
        _maximize_window()
        return

    # PLAY / PAUSE MEDIA
    if _match_any(text, CMD_PHRASES["play_pause"]):
        _play_pause_media()
        return

    # REFRESH PAGE
    if _match_any(text, CMD_PHRASES["refresh"]):
        _refresh_page()
        return

    # NEW TAB
    if _match_any(text, CMD_PHRASES["new_tab"]):
        _new_tab()
        return

    # CLOSE TAB
    if _match_any(text, CMD_PHRASES["close_tab"]):
        _close_tab()
        return

    # NEXT TAB
    if _match_any(text, CMD_PHRASES["next_tab"]):
        _next_tab()
        return

    # PREVIOUS TAB
    if _match_any(text, CMD_PHRASES["prev_tab"]):
        _prev_tab()
        return

    # ZOOM IN / OUT
    if _match_any(text, CMD_PHRASES["zoom_in"]):
        _zoom_in()
        return
    if _match_any(text, CMD_PHRASES["zoom_out"]):
        _zoom_out()
        return

    # COPY / PASTE / CUT / SELECT ALL
    if _match_any(text, CMD_PHRASES["copy"]):
        _copy(); return
    if _match_any(text, CMD_PHRASES["paste"]):
        _paste(); return
    if _match_any(text, CMD_PHRASES["cut"]):
        _cut(); return
    if _match_any(text, CMD_PHRASES["select_all"]):
        _select_all(); return

    # SWITCH DESKTOPS
    if _match_any(text, CMD_PHRASES["next_desktop"]):
        _next_desktop(); return

    if _match_any(text, CMD_PHRASES["prev_desktop"]):
        _prev_desktop(); return

    if _match_any(text, CMD_PHRASES["lock"]):
        if targets_cache:
            lockmgr.locked_target = targets_cache[0]; return
    if _match_any(text, CMD_PHRASES["unlock"]):
        lockmgr.locked_target = None; return

    if _match_any(text, CMD_PHRASES["screenshot"]):
        pyautogui.hotkey('winleft', 'shift', 's'); return

    if _match_any(text, CMD_PHRASES["center"]):
        pyautogui.moveTo(screen_w//2, screen_h//2); return

    if _match_any(text, CMD_PHRASES["mute"]):
        _press_media_key('volumemute'); return
    if _match_any(text, CMD_PHRASES["volume_up"]):
        _press_media_key('volumeup'); return
    if _match_any(text, CMD_PHRASES["volume_down"]):
        _press_media_key('volumedown'); return

    if _match_any(text, CMD_PHRASES["next_window"]):
        _do_alt_tab(); return
    if _match_any(text, CMD_PHRASES["prev_window"]):
        _do_shift_alt_tab(); return
    if _match_any(text, CMD_PHRASES["close"]):
        _do_alt_f4(); return

    # open <app>
    if text.startswith("open"):
        app = text.replace("open", "", 1).strip()
        open_application(app)
        return

    # search <query>
    if text.startswith("search"):
        q = text.replace("search", "", 1).strip()
        if q:
            subprocess.Popen([CHROME_EXE, f"https://www.google.com/search?q={q}"], shell=False)
        return

    # type <...>
    if text.startswith("type"):
        to_type = text.replace("type", "", 1).strip()
        if to_type:
            pyautogui.typewrite(to_type, interval=0.01)
        return

    # fallback: try fuzzy match entire text -> app
    best_app, score = _fuzzy_best(text, APP_KEYS, score_cutoff=55)
    if best_app:
        open_application(best_app)
        return

    print("[VOICE] Unrecognized command →", text)

# ---------------------------------------------------------------------------
# START VOICE LISTENER
# ---------------------------------------------------------------------------
try:
    start_listening()
    print("Voice assistant: listening (offline).")
except Exception as e:
    print("Voice assistant failed to start:", e)

# ---------------------------------------------------------------------------
# (the remainder of your original main loop follows unchanged)
# ---------------------------------------------------------------------------

print("Eye Cursor Ready.")
print("Gestures (USER perspective):")
print("  - BOTH EYES INTENTIONAL BLINK: Left click (double = double-click)")
print("  - RIGHT EYE WINK: Right click")
print("  - LEFT EYE HELD CLOSED (right open): Hold & drag (left mouse button)")
print("  - BOTH EYES HELD CLOSED + HEAD UP: Scroll DOWN")
print("  - BOTH EYES HELD CLOSED + HEAD DOWN: Scroll UP")
print("Keys: [D] Debug  [R] Recalibrate  [Q] Quit")


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# MAIN LOOP (wrapped)
# ---------------------------------------------------------------------------
def main():
    global head_base_y, drag_active, drag_start_time
    global scroll_mode, both_closed_start
    global last_scroll_time, last_left_click_time
    global curr_cursor, targets_cache, last_scan
    global DEBUG
    global smoother, blink, calib, lockmgr
    global FRAME_CALLBACK
    # Your runtime loop starts here (exact same code) — indent the following block by 4 spaces.
    while True:

        scan_targets()

        ret, frame = cap.read()
        if not ret:
            continue
        frame = cv2.flip(frame, 1)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = face_mesh.process(rgb)

        if res.multi_face_landmarks:

            lm = res.multi_face_landmarks[0]

            # -------------------------------
            # HEAD BASELINE (for scroll)
            # -------------------------------
            nose_y = lm.landmark[NOSE_LANDMARK_INDEX].y
            if head_base_y is None:
                head_base_y = nose_y
            else:
                # Only update baseline when NOT in active scroll mode
                if not scroll_mode:
                    head_base_y = (
                        HEAD_BASE_SMOOTH_ALPHA * head_base_y
                        + (1.0 - HEAD_BASE_SMOOTH_ALPHA) * nose_y
                    )

            # -------------------------------
            # BLINK / EYE STATES
            # -------------------------------
            bstate = blink.update(lm, frame.shape)

            left_closed = bstate["left_closed"]    # USER LEFT eye
            right_closed = bstate["right_closed"]  # USER RIGHT eye
            both_closed = bstate["both_closed"]

            left_blink = bstate["left_blink"]      # left wink event
            right_blink = bstate["right_blink"]    # right wink event
            both_blink = bstate["both_blink"]      # both-eyes blink event

            now = time.time()

            # ---------------------------------
            # MODE MANAGEMENT: SCROLL MODE
            # ---------------------------------
            if both_closed:
                if both_closed_start is None:
                    both_closed_start = now
                # Enter scroll mode ONLY after holding both eyes closed long enough
                if (not scroll_mode) and (now - both_closed_start >= SCROLL_ACTIVATION) and (not drag_active):
                    scroll_mode = True
            else:
                both_closed_start = None
                scroll_mode = False
            # Non-invasive UI settings reload (only once every ~0.2s)
            _last_ui_settings_time = getattr(globals(), "_last_ui_settings_time", 0.0)
            now = time.time()
            if now - _last_ui_settings_time > 0.22:
                _last_ui_settings_time = now
                ui_s = read_ui_settings_once()
                if ui_s:
                    # Apply any keys that exist in ui_s to your running objects
                    # For example:
                    try:
                        if "enable_actions" in ui_s:
                            enable_actions = ui_s["enable_actions"]   # make sure this var is used in your code
                        if "smoothing_window" in ui_s and hasattr(smoother, "__init__"):
                            # re-create smoother (safe)
                            smoother = SmoothFilter(ma_window=int(ui_s.get("smoothing_window", 6)),
                                                    exp_alpha=float(ui_s.get("smoothing_alpha", 0.93)))
                        if "eye_close_thr" in ui_s:
                            blink.eye_close_thr = float(ui_s["eye_close_thr"]) if hasattr(blink, "eye_close_thr") else None
                        # add any additional mappings you need
                    except Exception:
                        pass

            # ---------------------------------
            # CLICK ACTIONS (only when NOT scrolling)
            # ---------------------------------
            if not scroll_mode:
                # If we are dragging and do a deliberate both-eyes blink,
                # force-release the drag BEFORE generating the click.
                if both_blink and drag_active:
                    pyautogui.mouseUp(button="left")
                    drag_active = False

                # BOTH EYES BLINK -> LEFT CLICK / DOUBLE-CLICK
                if both_blink:
                    dt = now - last_left_click_time
                    if dt <= DOUBLE_CLICK_WINDOW:
                        pyautogui.doubleClick(button="left")
                        last_left_click_time = 0.0
                    else:
                        pyautogui.click(button="left")
                        last_left_click_time = now

                # RIGHT EYE WINK -> RIGHT CLICK
                if right_blink:
                    pyautogui.click(button="right")

            # ---------------------------------
            # DRAG: LEFT EYE CLOSED & RIGHT OPEN
            # (acts as holding left mouse button)
            # ---------------------------------
            if (left_closed and not right_closed and not both_closed and not scroll_mode):
                if not drag_active:
                    pyautogui.mouseDown(button="left")
                    drag_active = True
                    drag_start_time = now
                else:
                    # Safety: if something goes wrong and LEFT eye is
                    # detected as "closed" for too long, auto-release.
                    if now - drag_start_time > MAX_DRAG_DURATION:
                        pyautogui.mouseUp(button="left")
                        drag_active = False
            else:
                if drag_active:
                    pyautogui.mouseUp(button="left")
                    drag_active = False

            # ---------------------------------
            # SCROLL: BOTH EYES CLOSED + HEAD UP/DOWN (in scroll_mode only)
            # ---------------------------------
            if scroll_mode and both_closed and not drag_active:
                dy = nose_y - head_base_y
                if now - last_scroll_time > SCROLL_COOLDOWN:
                    # Head UP (nose_y smaller) -> SCROLL DOWN page
                    if dy < -HEAD_MOVE_THRESHOLD:
                        pyautogui.scroll(-140)   # faster scroll down
                        last_scroll_time = now
                    # Head DOWN (nose_y larger) -> SCROLL UP page
                    elif dy > HEAD_MOVE_THRESHOLD:
                        pyautogui.scroll(140)    # faster scroll up
                        last_scroll_time = now

            # ---------------------------------
            # GAZE NORMALIZED COORDINATES
            # ---------------------------------
            nx, ny = combined_iris_norm(lm)

            # ---------------------------------
            # MAP TO SCREEN (via calibration)
            # ---------------------------------
            sx, sy = calib.map_norm_to_screen(nx, ny, screen_w, screen_h)

            # ---------------------------------
            # SMOOTH GAZE
            # ---------------------------------
            sx_s, sy_s = smoother.update(sx, sy)

            prev = curr_cursor

            # ---------------------------------
            # LOCK MANAGER
            # ---------------------------------
            state = lockmgr.push_gaze((sx_s, sy_s))

            if state["state"] == "locked":
                dest = state["cursor_pos"]
                next_pos = (
                    int(prev[0] * 0.82 + dest[0] * 0.18),
                    int(prev[1] * 0.82 + dest[1] * 0.18)
                )
                curr_cursor = clamp_step(prev[0], prev[1], next_pos[0], next_pos[1], 50)
                pyautogui.moveTo(*curr_cursor)

            elif state["state"] == "candidate":
                dest = state["cursor_pos"]
                next_pos = (
                    int(prev[0] * 0.75 + dest[0] * 0.25),
                    int(prev[1] * 0.75 + dest[1] * 0.25)
                )
                curr_cursor = clamp_step(prev[0], prev[1], next_pos[0], next_pos[1], 70)
                pyautogui.moveTo(*curr_cursor)

            else:
                # soft unlock: follow gaze
                dest = (sx_s, sy_s)
                next_pos = (
                    int(prev[0] * 0.70 + dest[0] * 0.30),
                    int(prev[1] * 0.70 + dest[1] * 0.30)
                )
                curr_cursor = clamp_step(prev[0], prev[1], next_pos[0], next_pos[1], 55)
                pyautogui.moveTo(*curr_cursor)

            # ---------------------------------
            # DEBUG OVERLAY
            # ---------------------------------
            if DEBUG:
                draw_iris_points(frame, lm)
                lp, rp = iris_pixels(lm, frame)
                cv2.circle(frame, lp, 3, (0, 255, 0), -1)
                cv2.circle(frame, rp, 3, (0, 255, 0), -1)

            cv2.putText(frame, f"STATE: {state['state']}", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            info1 = f"Lc={int(left_closed)} Rc={int(right_closed)} Bc={int(both_closed)}"
            info2 = f"Lb={int(left_blink)} Rb={int(right_blink)} Bb={int(both_blink)}"
            info3 = f"drag={int(drag_active)} scroll={int(scroll_mode)}"

            cv2.putText(frame, info1, (20, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)
            cv2.putText(frame, info2, (20, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)
            cv2.putText(frame, info3, (20, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)

            for t in targets_cache[:6]:
                cx, cy = t["center"]
                cv2.circle(frame, (int(cx), int(cy)), 4, (255, 150, 0), -1)

        # -------------------------------
        # KEY INPUTS
        # -------------------------------
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break

        if key == ord('d'):
            DEBUG = not DEBUG
            print("Debug:", DEBUG)

        if key == ord('r'):
            print("Recalibration requested...")
            calib.record_all(get_norm_from_frame, cap)

        # -------------------------------
        # VOICE COMMANDS (NON-BLOCKING)
        # -------------------------------
        try:
            if not voice_queue.empty():
                cmd = voice_queue.get_nowait()
                handle_voice_command(cmd)
        except:
            pass

        # Send live frame to UI (if UI is running)
        try:
            if FRAME_CALLBACK is not None:
                FRAME_CALLBACK(frame)
        except:
            pass


        #cv2.imshow("Eye Cursor", frame)

    # cleanup at end of main
    try:
        cap.release()
    except:
        pass
    cv2.destroyAllWindows()


# wrapper for UI thread
def run_engine():
    main()

# keep single-file behaviour
if __name__ == "__main__":
    main()

