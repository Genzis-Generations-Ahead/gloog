"""Fake Pi + fake band, so the whole stack can be run and tested without hardware.

Physics (simplified): each subcarrier k is a static path S_k plus a path that
reflects off the chest, D_k * exp(j * 4*pi*d(t)/lambda + j*phi_k). The chest
displacement d(t) = breathing (~5 mm) + heartbeat (~0.2 mm). On top: receiver
noise, random AGC gain steps (like the Broadcom chip), packet-rate jitter.

    python -m gloog_engine.simulator                      # still person, BR 15, HR 72
    python -m gloog_engine.simulator --scenario           # empty -> still -> moving -> still, loops
    python -m gloog_engine.simulator --br 20 --hr 85 --rate 80
Sends CSI to UDP 5501 and band PPG to UDP 5600 on 127.0.0.1 (same as the real Pi/band).
"""
from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass

import numpy as np

from .csi import NULL_20MHZ, encode

LAMBDA = 0.125         # m, 2.4 GHz


@dataclass
class Person:
    mode: str = "still"     # empty | still | moving
    br: float = 15.0        # breaths / min
    hr: float = 72.0        # beats / min
    breath_mm: float = 5.0
    heart_mm: float = 0.25


class CsiSim:
    def __init__(self, seed: int = 1, n: int = 64):
        self.rng = np.random.default_rng(seed)
        self.n = n
        r = self.rng
        self.S = (r.normal(0, 1, n) + 1j * r.normal(0, 1, n)) * 250 + 400      # static paths
        self.D = (r.uniform(0.15, 0.35, n)) * np.abs(self.S)                      # chest reflection strength
        self.phi = r.uniform(0, 2 * np.pi, n)
        self.D[NULL_20MHZ] = 0; self.S[NULL_20MHZ] = 0
        self.gain = 1.0
        self.next_agc = 6.0
        self.walk = 0.0
        self.seq = 0

    def frame(self, t: float, p: Person) -> np.ndarray:
        r = self.rng
        if t >= self.next_agc:                          # AGC re-sets its gain now and then
            self.gain = float(r.uniform(0.7, 1.4))
            self.next_agc = t + r.uniform(4, 12)
        if p.mode == "empty":
            d, refl = 0.0, 0.0
        else:
            d = p.breath_mm / 1000 * np.sin(2 * np.pi * p.br / 60 * t) \
                + p.heart_mm / 1000 * np.sin(2 * np.pi * p.hr / 60 * t)
            refl = 1.0
            if p.mode == "moving":
                self.walk += r.normal(0, 0.004)          # big, random body movement
                d += self.walk
        H = self.S + refl * self.D * np.exp(1j * (4 * np.pi * d / LAMBDA + self.phi))
        H = H * self.gain * (1 + r.normal(0, 0.003))
        H += (r.normal(0, 1.5, self.n) + 1j * r.normal(0, 1.5, self.n))
        H[NULL_20MHZ] = 0
        return H

    def packet(self, t: float, p: Person) -> bytes:
        self.seq += 1
        return encode(self.frame(t, p), rssi=int(-42 + self.rng.normal(0, 1.5)), seq=self.seq)


def ppg(t: float, hr: float, contact: bool = True, rng=np.random.default_rng(2)) -> float:
    """MAX30102-like IR value: big DC + small pulse."""
    if not contact:
        return 2000 + rng.normal(0, 50)
    ph = (hr / 60 * t) % 1
    pulse = np.exp(-((ph - 0.2) / 0.08) ** 2) + 0.35 * np.exp(-((ph - 0.5) / 0.1) ** 2)
    return 120_000 + 900 * pulse + rng.normal(0, 30)


def stream(seconds: float, rate: float, person: Person, seed: int = 1, t0: float = 0.0):
    """Offline generator of (t, payload) at ~rate packets/s with jitter (for tests)."""
    sim = CsiSim(seed)
    rng = np.random.default_rng(seed + 7)
    t = t0
    while t < t0 + seconds:
        yield t, sim.packet(t, person)
        t += max(0.002, rng.normal(1 / rate, 0.15 / rate))


SCENARIO = [("empty", 40), ("still", 70), ("moving", 15), ("still", 70)]


def main() -> None:
    ap = argparse.ArgumentParser(description="Gloog hardware simulator")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--br", type=float, default=15)
    ap.add_argument("--hr", type=float, default=72)
    ap.add_argument("--rate", type=float, default=100)
    ap.add_argument("--mode", default="still", choices=["empty", "still", "moving"])
    ap.add_argument("--scenario", action="store_true", help="cycle empty -> still -> moving -> still")
    ap.add_argument("--no-band", action="store_true")
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sim, person = CsiSim(), Person(a.mode, a.br, a.hr)
    start = time.time()
    next_csi = next_band = next_log = start
    band_seq = 0
    print(f"[sim] CSI -> {a.host}:5501 at {a.rate:.0f}/s, band -> {a.host}:5600 (Ctrl+C to stop)")
    try:
        while True:
            now = time.time()
            t = now - start
            if a.scenario:
                cyc = t % sum(s for _, s in SCENARIO)
                for m, s in SCENARIO:
                    if cyc < s:
                        person.mode = m; break
                    cyc -= s
            if now >= next_csi:
                sock.sendto(sim.packet(t, person), (a.host, 5501))
                next_csi += max(0.002, np.random.normal(1 / a.rate, 0.15 / a.rate))
            if not a.no_band and now >= next_band:
                band_seq += 1
                ir = ppg(t, person.hr, contact=person.mode != "empty")
                sock.sendto(f"{band_seq},{int(t * 1000)},{int(ir)},{int(ir * 0.8)}".encode(), (a.host, 5600))
                next_band += 0.01
            if now >= next_log:
                print(f"[sim] t={t:5.0f}s  mode={person.mode:6s}  BR={person.br:.0f}  HR={person.hr:.0f}", flush=True)
                next_log += 5
            time.sleep(0.001)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
