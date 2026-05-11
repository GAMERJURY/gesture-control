# Gesture Control System
### Iron Man–style hand gesture window manager — fully local, no cloud

---

## What it does

| Gesture | Action |
|---|---|
| Pinch (right hand, hold 150ms) | Grab the active window |
| Drag while pinching | Move window anywhere |
| Release at screen edge | Fling window to next monitor |
| Release near edge zone | Snap to left-half / right-half / top / bottom |
| Both hands pinch + spread | Resize window live |
| Open palm swipe | Switch virtual desktop |
| Fist | Toggle pause mode |
| Index finger point | Drive mouse cursor |
| Left hand pinch + open/close | Control system volume |

---

## Setup

### 1. Python
Requires Python 3.9+.  Create a virtual environment first.

```bash
python3 -m venv gesture-env
source gesture-env/bin/activate        # macOS / Linux
gesture-env\Scripts\activate.bat       # Windows
```

### 2. Install Python packages

```bash
pip install -r requirements.txt
```

### 3. Platform extras

#### Linux
```bash
sudo apt update
sudo apt install wmctrl xdotool python3-tk
```

#### Windows
Uncomment `pycaw` and `comtypes` lines in `requirements.txt`, then re-run pip.
```
pip install pycaw comtypes
```
Also ensure your user has permission to move other windows (usually fine on Windows 10/11).

#### macOS
No extra installs needed.  AppleScript is used for window control.
You **must** grant Accessibility permission:
- System Settings → Privacy & Security → Accessibility → add Terminal (or your IDE)
- System Settings → Privacy & Security → Screen Recording → add Terminal

---

## Run

```bash
python main.py
```

A small semi-transparent HUD appears in the top-left corner.
An OpenCV debug window shows the camera feed with skeleton overlay.

**Hide the debug window:** press `Q` in the OpenCV window, or set
`"show_debug_window": false` in `config.json`.

---

## Tuning

Edit `config.json` — no code changes needed.

| Key | Default | What it does |
|---|---|---|
| `pinch_threshold` | 0.32 | Tighter pinch required if lower. Try 0.25–0.40. |
| `pinch_hold_ms` | 150 | Hold duration before grab fires. Increase to reduce misfires. |
| `swipe_velocity` | 0.04 | Speed needed to trigger desktop switch. |
| `drag_scale_x/y` | 2.5 | How much hand movement maps to pixel movement. |
| `show_debug_window` | true | Show/hide the OpenCV preview. |

---

## Run at login (optional)

### Linux (systemd user service)

Create `~/.config/systemd/user/gesture.service`:
```ini
[Unit]
Description=Gesture Control System
After=graphical-session.target

[Service]
ExecStart=/path/to/gesture-env/bin/python /path/to/gesture_system/main.py
Restart=on-failure
Environment=DISPLAY=:0

[Install]
WantedBy=default.target
```
```bash
systemctl --user enable gesture.service
systemctl --user start gesture.service
```

### Windows (Task Scheduler)

1. Open Task Scheduler → Create Basic Task
2. Trigger: At log on
3. Action: Start a program
   - Program: `C:\path\to\gesture-env\Scripts\python.exe`
   - Arguments: `C:\path\to\gesture_system\main.py`
4. Tick "Run only when user is logged on"

### macOS (launchd)

Create `~/Library/LaunchAgents/com.gesture.system.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.gesture.system</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/gesture-env/bin/python</string>
    <string>/path/to/gesture_system/main.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.gesture.system.plist
```

---

## Project structure

```
gesture_system/
├── main.py            ← entry point, thread orchestration
├── state.py           ← shared GestureState dataclass
├── gesture_engine.py  ← camera loop, MediaPipe, gesture classification
├── window_control.py  ← cross-platform window move/resize/snap/volume
├── hud_overlay.py     ← transparent Tkinter HUD
├── config.json        ← all tunable parameters
└── requirements.txt
```

---

## Troubleshooting

**Camera not found** — change `"index": 0` to `1` or `2` in config.json.

**Gestures too sensitive / misfiring** — increase `pinch_hold_ms` to 250–400.

**Window not moving (Linux)** — ensure `xdotool` is installed: `which xdotool`.

**Volume not working (Linux)** — ensure `amixer` is available: `sudo apt install alsa-utils`.

**macOS: "not trusted to use accessibility"** — see macOS setup section above.

**HUD flickers or doesn't appear** — Tkinter threading issue. Try running with:
```bash
PYTHONPATH=. python main.py
```
