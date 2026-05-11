"""
HUD Overlay
A transparent, always-on-top Tkinter window that renders:
- Current gesture status
- Snap zone highlight
- Volume bar
- Hand position reticle
Inspired by Iron Man's JARVIS interface.
"""

import tkinter as tk
import threading
import time
import math
from state import GestureState


# Colour palette — JARVIS cyan on near-black
HUD_BG        = "#0a0f14"
HUD_ALPHA     = 0.75          # window transparency
CYAN          = "#00e5ff"
CYAN_DIM      = "#005f6b"
AMBER         = "#ffb300"
GREEN         = "#00e676"
RED_DIM       = "#b71c1c"
FONT_MAIN     = ("Courier New", 13, "bold")
FONT_SMALL    = ("Courier New", 10)
HUD_W         = 320
HUD_H         = 190
SNAP_FLASH_MS = 500


class HUDOverlay:
    def __init__(self, config: dict, state: GestureState):
        self.config = config
        self.state  = state
        self._root  = None
        self._canvas = None
        self._stop  = False
        self._snap_flash_until = 0

    def stop(self):
        self._stop = True
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass

    def run(self):
        self._root = tk.Tk()
        root = self._root

        # --- window style ---
        root.title("Gesture HUD")
        root.geometry(f"{HUD_W}x{HUD_H}+20+20")
        root.configure(bg=HUD_BG)
        root.attributes("-topmost", True)
        root.attributes("-alpha", HUD_ALPHA)
        root.overrideredirect(True)      # no title bar

        # Transparent click-through on Windows
        try:
            root.attributes("-transparentcolor", HUD_BG)
        except Exception:
            pass

        self._canvas = tk.Canvas(
            root, width=HUD_W, height=HUD_H,
            bg=HUD_BG, highlightthickness=0
        )
        self._canvas.pack()

        # Allow dragging the HUD itself
        self._canvas.bind("<ButtonPress-1>",   self._start_drag)
        self._canvas.bind("<B1-Motion>",       self._do_drag)

        self._update_hud()
        root.mainloop()

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        x  = self._root.winfo_x() + dx
        y  = self._root.winfo_y() + dy
        self._root.geometry(f"+{x}+{y}")

    def _update_hud(self):
        if self._stop or not self._root:
            return
        self._draw()
        self._root.after(33, self._update_hud)   # ~30 fps

    def _draw(self):
        c = self._canvas
        s = self.state
        c.delete("all")

        W, H = HUD_W, HUD_H

        # Border
        border_col = RED_DIM if s.paused else CYAN_DIM
        c.create_rectangle(1, 1, W-1, H-1, outline=border_col, width=1)

        # Corner accents
        L = 12
        for x0, y0, x1, y1 in [
            (1,1,L,1), (1,1,1,L),
            (W-L,1,W-1,1), (W-1,1,W-1,L),
            (1,H-L,1,H-1), (1,H-1,L,H-1),
            (W-1,H-L,W-1,H-1), (W-L,H-1,W-1,H-1),
        ]:
            c.create_line(x0, y0, x1, y1, fill=CYAN, width=2)

        # Header
        label = "GESTURE SYSTEM" if not s.paused else "— PAUSED —"
        col   = CYAN if not s.paused else AMBER
        c.create_text(W//2, 18, text=label, fill=col, font=FONT_MAIN, anchor="center")

        # Divider
        c.create_line(10, 30, W-10, 30, fill=CYAN_DIM, width=1)

        # Status message
        msg = s.hud_message[:38]
        c.create_text(14, 46, text=msg, fill=CYAN, font=FONT_SMALL, anchor="w")

        # Gesture indicators row
        indicators = [
            ("GRAB",   s.r_pinching),
            ("RESIZE", s.both_pinching),
            ("POINT",  s.pointing),
            ("L-VOL",  s.l_pinching),
        ]
        ix = 14
        for label, active in indicators:
            col = GREEN if active else CYAN_DIM
            c.create_text(ix, 66, text=label, fill=col, font=FONT_SMALL, anchor="w")
            ix += 70

        # Volume bar
        vol = s.volume_level
        bar_x, bar_y, bar_w, bar_h = 14, 82, W-28, 8
        c.create_rectangle(bar_x, bar_y, bar_x+bar_w, bar_y+bar_h,
                            outline=CYAN_DIM, fill="", width=1)
        fill_w = int(bar_w * vol)
        if fill_w > 0:
            col = AMBER if vol > 0.85 else CYAN
            c.create_rectangle(bar_x, bar_y, bar_x+fill_w, bar_y+bar_h,
                                fill=col, outline="")
        c.create_text(bar_x+bar_w+6, bar_y+4, text=f"VOL",
                      fill=CYAN_DIM, font=FONT_SMALL, anchor="w")

        # Snap zone visualizer (mini monitor grid)
        self._draw_snap_preview(c, 14, 100, W-28, 72, s.hud_snap_zone)

    def _draw_snap_preview(self, c, x, y, w, h, active_zone):
        """Draw a mini monitor outline with snap zone highlighted."""
        c.create_rectangle(x, y, x+w, y+h, outline=CYAN_DIM, width=1)

        zones = {
            "left-half":   (x,       y,       x+w//2,  y+h),
            "right-half":  (x+w//2,  y,       x+w,     y+h),
            "top-half":    (x,       y,       x+w,     y+h//2),
            "bottom-half": (x,       y+h//2,  x+w,     y+h),
            "full":        (x,       y,       x+w,     y+h),
        }

        # Faint grid lines
        c.create_line(x+w//2, y, x+w//2, y+h, fill=CYAN_DIM, width=1, dash=(2,4))
        c.create_line(x, y+h//2, x+w, y+h//2, fill=CYAN_DIM, width=1, dash=(2,4))

        # Highlight active zone
        now = time.time() * 1000
        if active_zone and active_zone in zones:
            flash = now < self._snap_flash_until
            zx0, zy0, zx1, zy1 = zones[active_zone]
            c.create_rectangle(zx0+1, zy0+1, zx1-1, zy1-1,
                                fill=CYAN, outline="", stipple="gray50")
            c.create_text((zx0+zx1)//2, (zy0+zy1)//2,
                          text=active_zone.upper().replace("-"," "),
                          fill=HUD_BG, font=FONT_SMALL, anchor="center")
            self._snap_flash_until = now + SNAP_FLASH_MS
        else:
            # Label
            c.create_text(x+w//2, y+h//2, text="SNAP ZONES",
                          fill=CYAN_DIM, font=FONT_SMALL, anchor="center")
