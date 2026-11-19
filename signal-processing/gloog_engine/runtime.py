"""Network side of the receiver: UDP in (Pi CSI 5501, band 5600), discovery beacon
(5601) so the band finds this laptop, CSV logging. Shared by receiver.py and the backend."""
from __future__ import annotations

import csv
import os
import select
import socket
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .csi import decode
from .vitals import Vitals, VitalsEngine

CSI_PORT, BAND_PORT, DISC_PORT = 5501, 5600, 5601


def local_ipv4s() -> list[str]:
    ips: list[str] = []
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    try:                                   # fallback: IP of the default route
        t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t.connect(("192.0.2.1", 9)); ips.append(t.getsockname()[0]); t.close()
    except OSError:
        pass
    return sorted(ip for ip in set(ips) if not ip.startswith("127."))


class Receiver:
    """Runs in a background thread. Calls on_vitals(Vitals) every `every` seconds."""

    def __init__(self, engine: VitalsEngine | None = None, log_dir: str | Path | None = "logs",
                 every: float = 2.0, on_vitals: Callable[[Vitals], None] | None = None,
                 csi_port: int = CSI_PORT, band_port: int = BAND_PORT, beacon: bool = True):
        self.engine = engine or VitalsEngine()
        self.every = every
        self.on_vitals = on_vitals
        self.ports = (csi_port, band_port)
        self.beacon = beacon
        self.log_dir = Path(log_dir) if log_dir else None
        self.counts = {"csi": 0, "band": 0, "bad": 0}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.latest: Vitals | None = None
        self.started = time.time()

    # thread-safe access for the API
    def calibrate(self, seconds: float = 30.0) -> None:
        with self._lock:
            self.engine.calibrate(time.time(), seconds)

    def stop(self) -> None:
        self._stop.set()

    def start(self) -> "Receiver":
        threading.Thread(target=self._run, daemon=True, name="gloog-rx").start()
        if self.beacon:
            threading.Thread(target=self._beacon, daemon=True, name="gloog-beacon").start()
        return self

    def _beacon(self) -> None:
        """Broadcast 'GLOOG_RX' on every adapter every 2 s so the band can find us."""
        while not self._stop.is_set():
            for ip in local_ipv4s() + [""]:
                try:
                    b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    b.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    b.bind((ip, 0))
                    b.sendto(b"GLOOG_RX", ("255.255.255.255", DISC_PORT))
                    b.close()
                except OSError:
                    pass
            self._stop.wait(2)

    def _sock(self, port: int) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        s.bind(("0.0.0.0", port)); s.setblocking(False)
        return s

    def _run(self) -> None:
        csi_s, band_s = self._sock(self.ports[0]), self._sock(self.ports[1])
        csi_w = band_w = None
        files = []
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            cf = open(self.log_dir / f"csi_{stamp}.csv", "w", newline="")
            bf = open(self.log_dir / f"band_{stamp}.csv", "w", newline="")
            files = [cf, bf]
            csi_w, band_w = csv.writer(cf), csv.writer(bf)
            band_w.writerow(["t_laptop", "seq", "ms_band", "ir", "red"])
        header_done = False
        next_out = time.time() + self.every
        try:
            while not self._stop.is_set():
                r, _, _ = select.select([csi_s, band_s], [], [], 0.25)
                now = time.time()
                for s in r:
                    for _ in range(256):                      # drain the socket
                        try:
                            data = s.recv(4096)
                        except BlockingIOError:
                            break
                        if s is csi_s:
                            pk = decode(data)
                            if pk is None:
                                self.counts["bad"] += 1; continue
                            amp = pk.amp
                            with self._lock:
                                self.engine.push_csi(now, amp, pk.rssi)
                            self.counts["csi"] += 1
                            if csi_w:
                                if not header_done:
                                    csi_w.writerow(["t_laptop", "seq", "rssi"] + [f"a{i}" for i in range(len(amp))])
                                    header_done = True
                                csi_w.writerow([f"{now:.4f}", pk.seq, pk.rssi] + np.round(amp, 1).tolist())
                        else:
                            try:
                                seqb, ms, ir, red = data.decode().strip().split(",")
                                irv = float(ir)
                            except ValueError:
                                self.counts["bad"] += 1; continue
                            with self._lock:
                                self.engine.push_band(now, irv)
                            self.counts["band"] += 1
                            if band_w:
                                band_w.writerow([f"{now:.4f}", seqb, ms, ir, red])
                if now >= next_out:
                    next_out = now + self.every
                    with self._lock:
                        v = self.engine.compute(now)
                    self.latest = v
                    for f in files:
                        f.flush()
                    if self.on_vitals:
                        try:
                            self.on_vitals(v)
                        except Exception as e:                # never kill the receiver
                            print(f"[gloog] on_vitals error: {e}", flush=True)
        finally:
            for f in files:
                f.close()
            csi_s.close(); band_s.close()


def fmt(v: Vitals) -> str:
    """One console line, like the old receiver.py."""
    parts = []
    if v.presence == "no_signal":
        parts.append("CSI: no data (Pi forwarding? router traffic?)")
    elif v.presence == "warming_up":
        parts.append(f"CSI {v.pkt_rate:.0f}pkt/s warming up")
    else:
        br = f"BR={v.br:.1f}/min" if v.br else "BR=–"
        hr = f"HR={v.hr}bpm" if v.hr else f"HR=– (conf {v.hr_conf:.2f})"
        parts.append(f"CSI {v.pkt_rate:.0f}pkt/s {v.presence.upper()} motion={v.motion:.1f}x {br} {hr}"
                     + (f" agc_fixed={v.agc_steps}" if v.agc_steps else ""))
    parts.append({"ok": f"BAND HR={v.band_hr}bpm", "no_contact": "BAND: no finger/skin contact"}.get(v.band_status, "BAND: no data"))
    line = " | ".join(parts)
    if v.notes:
        line += "   ! " + "; ".join(v.notes)
    return line
