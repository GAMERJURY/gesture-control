"""
Shared mutable state passed between gesture engine, window controller, and HUD.
All fields are read/written from multiple threads — use simple types only.
"""

import threading
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class GestureState:
    running: bool = True
    paused: bool = False           # fist gesture pauses all input

    # Right hand — window control
    r_pinching: bool = False
    r_pinch_pos: Optional[Tuple[float, float]] = None   # normalized 0-1
    r_drag_delta: Optional[Tuple[int, int]] = None       # pixels

    # Left hand — aux control (volume etc.)
    l_pinching: bool = False
    l_pinch_dist: float = 0.0     # normalized pinch distance 0-1

    # Two-hand resize
    both_pinching: bool = False
    spread_dist: float = 0.0      # normalized distance between both pinch points

    # Point gesture — cursor control
    pointing: bool = False
    point_pos: Optional[Tuple[float, float]] = None

    # Swipe
    swipe_direction: Optional[str] = None   # 'left' | 'right' | None

    # Current grabbed window info
    grabbed_window_id: Optional[int] = None
    grabbed_window_rect: Optional[Tuple[int, int, int, int]] = None  # x,y,w,h

    # HUD display info
    hud_message: str = ""
    hud_snap_zone: Optional[str] = None   # 'left-half' | 'right-half' | 'full' | etc.

    # Volume (0.0 - 1.0)
    volume_level: float = 0.5

    # Lock for complex multi-field updates
    lock: threading.Lock = field(default_factory=threading.Lock)
