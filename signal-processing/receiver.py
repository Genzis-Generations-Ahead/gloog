#!/usr/bin/env python3
"""Gloog laptop receiver (console). Fuses Pi CSI (UDP 5501) + reference band PPG (UDP 5600).
- Logs everything to CSV with laptop-side timestamps (one clock = easy sync)
- Every 2 s prints: presence/motion, CSI breathing rate, CSI heart rate, band HR

pip install -r requirements.txt
python receiver.py                 # Ctrl+C to stop; logs land in ./logs/
python receiver.py --calibrate     # first 30 s: keep the bed EMPTY (sets the room baseline)

For the live dashboard + alerts, run the backend instead (see ../backend/README.md).
No hardware? In another terminal:  python -m gloog_engine.simulator --scenario
"""
import argparse
import time

from gloog_engine.runtime import Receiver, fmt, local_ipv4s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true", help="empty-room calibration for the first 30 s")
    ap.add_argument("--no-log", action="store_true", help="don't write CSV logs")
    a = ap.parse_args()

    rx = Receiver(log_dir=None if a.no_log else "logs", on_vitals=lambda v: print(fmt(v), flush=True))
    print(f"[gloog] listening CSI:5501 BAND:5600  (announcing on {', '.join(local_ipv4s()) or 'no network'})")
    if a.calibrate:
        rx.calibrate(30)
        print("[gloog] calibrating for 30 s: keep the bed EMPTY")
    rx.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        rx.stop()
        print("\n[gloog] stopped" + ("" if a.no_log else ", logs saved in ./logs/"))


if __name__ == "__main__":
    main()
