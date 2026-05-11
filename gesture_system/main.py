"""
Gesture Control System — Iron Man style
Run: python main.py
Stop: Ctrl+C or close tray icon
"""

import threading
import signal
import sys
import time
import json
import os

from gesture_engine import GestureEngine
from window_control import WindowController
from hud_overlay import HUDOverlay
from state import GestureState

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def main():
    print("=" * 50)
    print("  Gesture Control System  ")
    print("  Press Ctrl+C to quit    ")
    print("=" * 50)

    config = load_config()
    state = GestureState()

    window_ctrl = WindowController(config, state)
    hud = HUDOverlay(config, state)
    engine = GestureEngine(config, state, window_ctrl, hud)

    # Graceful shutdown
    def shutdown(sig=None, frame=None):
        print("\nShutting down...")
        state.running = False
        hud.stop()
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # HUD runs on main thread (Tkinter requirement)
    hud_thread = threading.Thread(target=hud.run, daemon=True)
    hud_thread.start()

    # Gesture engine runs on its own thread
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    print("Gesture engine running. Show your hand to the camera.")
    print("Gestures:")
    print("  PINCH (index+thumb)  — grab focused window")
    print("  DRAG while pinching  — move window")
    print("  RELEASE              — drop / snap to zone")
    print("  TWO-HAND SPREAD      — resize window")
    print("  OPEN PALM SWIPE      — switch virtual desktop")
    print("  FIST                 — toggle pause mode")
    print("  POINT (index up)     — move mouse cursor")
    print("  LEFT PINCH DISTANCE  — system volume")
    print()

    try:
        while state.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
