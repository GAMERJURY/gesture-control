"""
Window Controller
Cross-platform window management: move, resize, snap, multi-monitor fling,
virtual desktop switch, volume, cursor.

Platform detection is automatic.  On unsupported platforms a warning is printed
and calls become no-ops so the rest of the system still runs.
"""

import sys
import platform
import math
import pyautogui
import screeninfo

from state import GestureState

OS = platform.system()   # 'Linux', 'Windows', 'Darwin'

# --- optional platform imports ---
if OS == "Linux":
    try:
        import subprocess
        import re as _re
        _HAS_WMCTRL = True
    except Exception:
        _HAS_WMCTRL = False

elif OS == "Windows":
    try:
        import ctypes
        import ctypes.wintypes as wintypes
        _user32 = ctypes.windll.user32
        _HAS_WIN32 = True
    except Exception:
        _HAS_WIN32 = False
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        import comtypes
        _HAS_PYCAW = True
    except Exception:
        _HAS_PYCAW = False

elif OS == "Darwin":
    try:
        from AppKit import NSWorkspace
        from Quartz import (
            CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID, CGEventCreateMouseEvent, CGEventPost,
            kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGHIDEventTap
        )
        _HAS_QUARTZ = True
    except Exception:
        _HAS_QUARTZ = False


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def _get_monitors():
    try:
        return screeninfo.get_monitors()
    except Exception:
        return []


class WindowController:
    def __init__(self, config: dict, state: GestureState):
        self.config = config
        self.state  = state
        self._monitors = _get_monitors()
        self._volume_interface = None
        self._init_volume()
        self._active_win_id   = None
        self._win_start_x     = 0
        self._win_start_y     = 0

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def _init_volume(self):
        if OS == "Windows" and _HAS_PYCAW:
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._volume_interface = interface.QueryInterface(IAudioEndpointVolume)
            except Exception:
                pass

    def set_volume(self, level: float):
        """level: 0.0 – 1.0"""
        level = max(0.0, min(1.0, level))
        if OS == "Windows" and self._volume_interface:
            try:
                self._volume_interface.SetMasterVolumeLevelScalar(level, None)
            except Exception:
                pass
        elif OS == "Linux":
            pct = int(level * 100)
            try:
                import subprocess
                subprocess.run(
                    ["amixer", "-q", "sset", "Master", f"{pct}%"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        elif OS == "Darwin":
            pct = int(level * 100)
            try:
                import subprocess
                subprocess.run(
                    ["osascript", "-e", f"set volume output volume {pct}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def move_cursor(self, norm_x: float, norm_y: float):
        """Move mouse to normalized screen position."""
        monitors = self._monitors or _get_monitors()
        if not monitors:
            sw, sh = pyautogui.size()
            pyautogui.moveTo(int(norm_x * sw), int(norm_y * sh))
            return
        # Use primary monitor
        m = monitors[0]
        px = m.x + int(norm_x * m.width)
        py = m.y + int(norm_y * m.height)
        pyautogui.moveTo(px, py)

    # ------------------------------------------------------------------
    # Window grab / drag
    # ------------------------------------------------------------------

    def get_active_window_rect(self):
        """Returns (x, y, w, h) of the currently focused window, or None."""
        if OS == "Linux" and _HAS_WMCTRL:
            return self._linux_get_active_rect()
        elif OS == "Windows" and _HAS_WIN32:
            return self._win_get_active_rect()
        elif OS == "Darwin" and _HAS_QUARTZ:
            return self._mac_get_active_rect()
        return None

    def grab_active_window(self):
        """Returns (window_id, rect) of the active window."""
        rect = self.get_active_window_rect()
        win_id = self._get_active_window_id()
        if rect:
            self._win_start_x = rect[0]
            self._win_start_y = rect[1]
        return win_id, rect

    def drag_window(self, win_id, orig_rect, dx: int, dy: int):
        """Move window by (dx, dy) pixels relative to its last position."""
        if orig_rect is None:
            return
        # We accumulate position via the state's grabbed_window_rect
        s = self.state
        if s.grabbed_window_rect:
            x, y, w, h = s.grabbed_window_rect
            nx, ny = x + dx, y + dy
            self._move_window(win_id, nx, ny)
            s.grabbed_window_rect = (nx, ny, w, h)

    def snap_window(self, win_id, zone: str):
        """Snap window to a predefined zone on the primary monitor."""
        monitors = self._monitors or _get_monitors()
        if not monitors:
            return
        m = monitors[0]
        hw = m.width  // 2
        hh = m.height // 2
        zones = {
            "left-half":    (m.x,       m.y,       hw,       m.height),
            "right-half":   (m.x + hw,  m.y,       hw,       m.height),
            "top-half":     (m.x,       m.y,       m.width,  hh),
            "bottom-half":  (m.x,       m.y + hh,  m.width,  hh),
            "top-left":     (m.x,       m.y,       hw,       hh),
            "top-right":    (m.x + hw,  m.y,       hw,       hh),
            "bottom-left":  (m.x,       m.y + hh,  hw,       hh),
            "bottom-right": (m.x + hw,  m.y + hh,  hw,       hh),
            "full":         (m.x,       m.y,       m.width,  m.height),
        }
        if zone not in zones:
            return
        x, y, w, h = zones[zone]
        self._move_window(win_id, x, y)
        self._resize_window_abs(win_id, w, h)

    def fling_to_next_monitor(self, win_id, direction: str):
        """Move window to the adjacent monitor."""
        monitors = self._monitors or _get_monitors()
        if len(monitors) < 2:
            return
        rect = self.state.grabbed_window_rect or self.get_active_window_rect()
        if not rect:
            return
        x, y, w, h = rect
        # Find current monitor
        cur_idx = 0
        for i, m in enumerate(monitors):
            if m.x <= x < m.x + m.width:
                cur_idx = i
                break
        if direction == "right":
            next_m = monitors[(cur_idx + 1) % len(monitors)]
        else:
            next_m = monitors[(cur_idx - 1) % len(monitors)]
        # Place at same relative position
        rel_x = x - monitors[cur_idx].x
        rel_y = y - monitors[cur_idx].y
        nx = next_m.x + rel_x
        ny = next_m.y + rel_y
        self._move_window(win_id, nx, ny)

    def resize_window(self, orig_rect, ratio: float):
        """Resize active window by ratio relative to its grabbed size."""
        if orig_rect is None:
            return
        x, y, ow, oh = orig_rect
        nw = int(ow * ratio)
        nh = int(oh * ratio)
        nw = max(200, min(nw, 3840))
        nh = max(150, min(nh, 2160))
        win_id = self._get_active_window_id()
        self._resize_window_abs(win_id, nw, nh)

    # ------------------------------------------------------------------
    # Virtual desktop switching
    # ------------------------------------------------------------------

    def switch_desktop(self, direction: str):
        """Switch virtual workspace left or right."""
        if OS == "Linux":
            key = "ctrl+alt+Left" if direction == "left" else "ctrl+alt+Right"
            pyautogui.hotkey(*key.split("+"))
        elif OS == "Windows":
            key = "ctrl+win+Left" if direction == "left" else "ctrl+win+Right"
            pyautogui.hotkey(*key.split("+"))
        elif OS == "Darwin":
            # macOS Mission Control left/right
            key = "ctrl+Left" if direction == "left" else "ctrl+Right"
            pyautogui.hotkey(*key.split("+"))

    # ------------------------------------------------------------------
    # Internal platform helpers
    # ------------------------------------------------------------------

    def list_windows(self):
        out = []
        if OS == "Windows" and _HAS_WIN32:
            import ctypes
            def cb(hwnd, _):
                if _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd) > 0:
                    buf = ctypes.create_unicode_buffer(256)
                    _user32.GetWindowTextW(hwnd, buf, 256)
                    title = buf.value.strip()
                    if title and title not in ("", "Program Manager", "Windows Input Experience"):
                        out.append((hwnd, title))
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            _user32.EnumWindows(WNDENUMPROC(cb), 0)
        elif OS == "Linux":
            try:
                import subprocess, re
                raw = subprocess.check_output(["wmctrl", "-l"], text=True)
                for line in raw.strip().splitlines():
                    parts = line.split(None, 3)
                    if len(parts) == 4:
                        wid = int(parts[0], 16)
                        title = parts[3].strip()
                        if title:
                            out.append((wid, title))
            except Exception:
                pass
        return out

    def focus_window(self, win_id):
        if win_id is None:
            return
        if OS == "Windows" and _HAS_WIN32:
            try:
                _user32.ShowWindow(win_id, 9)
                _user32.SetForegroundWindow(win_id)
            except Exception:
                pass
        elif OS == "Linux":
            try:
                import subprocess
                subprocess.run(["wmctrl", "-ia", hex(win_id)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass


    def _get_active_window_id(self):
        if OS == "Linux" and _HAS_WMCTRL:
            try:
                import subprocess
                out = subprocess.check_output(
                    ["xdotool", "getactivewindow"], text=True
                ).strip()
                return int(out)
            except Exception:
                return None
        elif OS == "Windows" and _HAS_WIN32:
            return _user32.GetForegroundWindow()
        return None

    def _move_window(self, win_id, x: int, y: int):
        if win_id is None:
            return
        if OS == "Linux" and _HAS_WMCTRL:
            try:
                import subprocess
                subprocess.run(
                    ["xdotool", "windowmove", str(win_id), str(x), str(y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        elif OS == "Windows" and _HAS_WIN32:
            try:
                rect = wintypes.RECT()
                _user32.GetWindowRect(win_id, ctypes.byref(rect))
                w = rect.right  - rect.left
                h = rect.bottom - rect.top
                _user32.MoveWindow(win_id, x, y, w, h, True)
            except Exception:
                pass
        elif OS == "Darwin":
            # Use AppleScript as fallback
            try:
                import subprocess
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "System Events" to set position of '
                     f'(first window of (first process whose frontmost is true)) to {{{x}, {y}}}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    def _resize_window_abs(self, win_id, w: int, h: int):
        if win_id is None:
            return
        if OS == "Linux" and _HAS_WMCTRL:
            try:
                import subprocess
                subprocess.run(
                    ["xdotool", "windowsize", str(win_id), str(w), str(h)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        elif OS == "Windows" and _HAS_WIN32:
            try:
                rect = wintypes.RECT()
                _user32.GetWindowRect(win_id, ctypes.byref(rect))
                _user32.MoveWindow(win_id, rect.left, rect.top, w, h, True)
            except Exception:
                pass
        elif OS == "Darwin":
            try:
                import subprocess
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "System Events" to set size of '
                     f'(first window of (first process whose frontmost is true)) to {{{w}, {h}}}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

    # --- Linux helpers ---
    def _linux_get_active_rect(self):
        try:
            import subprocess, re
            wid = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
            out = subprocess.check_output(
                ["xdotool", "getwindowgeometry", wid], text=True
            )
            pos = re.search(r"Position: (\d+),(\d+)", out)
            sz  = re.search(r"Geometry: (\d+)x(\d+)", out)
            if pos and sz:
                return (int(pos.group(1)), int(pos.group(2)),
                        int(sz.group(1)),  int(sz.group(2)))
        except Exception:
            pass
        return None

    # --- Windows helpers ---
    def _win_get_active_rect(self):
        try:
            hwnd = _user32.GetForegroundWindow()
            rect = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
            return (rect.left, rect.top,
                    rect.right - rect.left, rect.bottom - rect.top)
        except Exception:
            return None

    # --- macOS helpers ---
    def _mac_get_active_rect(self):
        try:
            import subprocess, re
            out = subprocess.check_output(
                ["osascript", "-e",
                 'tell application "System Events" to get {position, size} of '
                 '(first window of (first process whose frontmost is true))'],
                text=True
            ).strip()
            nums = list(map(int, re.findall(r"-?\d+", out)))
            if len(nums) >= 4:
                return (nums[0], nums[1], nums[2], nums[3])
        except Exception:
            pass
        return None
