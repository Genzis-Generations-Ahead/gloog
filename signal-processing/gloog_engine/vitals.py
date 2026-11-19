"""Gloog vitals engine: Wi-Fi CSI amplitude -> presence, movement, breathing, heart rate.

Pipeline (every update, on the last WIN_S seconds):
  1. drop guard/DC subcarriers
  2. AGC fix: divide every packet by its own mean amplitude. The Broadcom chip
     re-sets its gain on its own; without this, gain steps look like movement.
  3. Hampel filter (spikes) + uniform resampling to FS Hz
  4. movement score = broadband (0.7-5 Hz) energy vs. the empty-room baseline
  5. breathing: pick the subcarriers whose 0.1-0.7 Hz band is most *periodic*
     (not just most variable), combine them with PCA, take the spectral peak
  6. heart rate: same in 0.8-2.5 Hz, after notching out breathing harmonics
     (2x..6x BR), which otherwise dominate this band. Reported only when the
     peak clearly stands out (confidence), else None.

Single-antenna Pi 3B+ CSI gives amplitude only (no usable phase difference),
so heart rate from CSI is experimental: compare it with the reference band.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

from .csi import usable_subcarriers

WIN_S = 30.0         # analysis window
FS = 50.0            # internal sample rate after resampling
BR_BAND = (0.1, 0.7)      # 6-42 breaths/min
HR_BAND = (0.8, 2.5)      # 48-150 bpm
MOVE_BAND = (0.7, 5.0)    # body movement is broadband


def _bp(x: np.ndarray, lo: float, hi: float, fs: float = FS, order: int = 3) -> np.ndarray:
    sos = butter(order, [lo / (fs / 2), min(hi / (fs / 2), 0.99)], btype="band", output="sos")
    return sosfiltfilt(sos, x, axis=0)


def _spectrum(x: np.ndarray, fs: float = FS) -> tuple[np.ndarray, np.ndarray]:
    x = x - x.mean(0)
    n = 1 << int(np.ceil(np.log2(len(x) * 4)))       # zero-pad for finer bins
    w = np.hanning(len(x))
    if x.ndim == 2:
        w = w[:, None]
    return np.fft.rfftfreq(n, 1 / fs), np.abs(np.fft.rfft(x * w, n, axis=0)) ** 2


def _hampel(a: np.ndarray, k: int = 7, t: float = 3.0) -> np.ndarray:
    """Replace spikes (per column) with the rolling median."""
    from scipy.ndimage import median_filter
    med = median_filter(a, size=(k, 1), mode="nearest")
    mad = median_filter(np.abs(a - med), size=(k, 1), mode="nearest") * 1.4826 + 1e-9
    out = a.copy()
    bad = np.abs(a - med) > t * mad
    out[bad] = med[bad]
    return out


def _periodicity(x: np.ndarray, band: tuple[float, float]) -> np.ndarray:
    """Per column: share of in-band power that sits in the strongest peak (+-1 bin)."""
    f, P = _spectrum(x)
    m = (f >= band[0]) & (f <= band[1])
    Pb = P[m]
    i = Pb.argmax(0)
    peak = np.array([Pb[max(0, j - 2):j + 3, c].sum() for c, j in enumerate(i)])
    return peak / (Pb.sum(0) + 1e-12)


def _pca1(x: np.ndarray) -> np.ndarray:
    x = x - x.mean(0)
    u, s, _ = np.linalg.svd(x, full_matrices=False)
    return u[:, 0] * s[0]


def _peak_rate(sig: np.ndarray, band: tuple[float, float], notch: list[float] | None = None) -> tuple[float, float, float]:
    """Dominant frequency in band (per minute, sub-bin accurate), a 0..1 confidence and the peak SNR.

    Confidence = how far the top peak stands above the best *other* peak
    (>0.15 Hz away): 1.0 when it is 3x stronger, 0 when they are equal.
    """
    f, P = _spectrum(sig)
    m = (f >= band[0]) & (f <= band[1])
    if notch:
        for fn in notch:
            m &= np.abs(f - fn) > 0.04
    if not m.any():
        return float("nan"), 0.0, 0.0
    Pm = np.where(m, P, 0.0)
    j = int(Pm.argmax())
    # parabolic interpolation on the log spectrum for sub-bin accuracy
    if 0 < j < len(P) - 1 and Pm[j - 1] > 0 and Pm[j + 1] > 0:
        a, b, c = np.log(Pm[j - 1]), np.log(Pm[j]), np.log(Pm[j + 1])
        off = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    else:
        off = 0.0
    fpk = f[j] + off * (f[1] - f[0])
    away = m & (np.abs(f - f[j]) > 0.15)
    p2 = Pm[away].max() if away.any() else 0.0
    conf = float(np.clip((Pm[j] / (p2 + 1e-12) - 1) / 2, 0, 1))
    snr = float(Pm[j] / (np.median(P[m]) + 1e-12))
    return float(fpk * 60), conf, snr


def _remove_harmonics(x: np.ndarray, f0: float, kmax: int | None = None) -> np.ndarray:
    """Least-squares fit and subtract sin/cos at k*f0 (k = 1..kmax) from each column.
    Breathing is ~20x stronger than the heartbeat and its 2nd-6th harmonics land
    right in the heart-rate band; notching alone leaks, subtracting works."""
    t = np.arange(len(x)) / FS
    if kmax is None:                               # every harmonic up to the top of the HR band
        kmax = int((HR_BAND[1] + 0.1) / f0)
    cols = []
    for k in range(1, kmax + 1):
        if k * f0 >= FS / 2:
            break
        for df in (-0.004, 0.0, 0.004):            # tolerate slight BR drift in the window
            w = 2 * np.pi * (k * f0 + df) * t
            cols += [np.sin(w), np.cos(w)]
    if not cols:
        return x
    B = np.stack(cols, 1)
    coef, *_ = np.linalg.lstsq(B, x, rcond=None)
    return x - B @ coef


@dataclass
class Vitals:
    t: float
    pkt_rate: float = 0.0
    rssi: float | None = None
    presence: str = "no_signal"         # no_signal | warming_up | empty | still | moving
    motion: float = 0.0                 # movement score; ~1 = empty-room noise level
    br: float | None = None             # breaths / min
    br_conf: float = 0.0
    hr: float | None = None             # beats / min (CSI, experimental)
    hr_conf: float = 0.0
    band_hr: float | None = None        # reference band
    band_status: str = "no_data"        # no_data | no_contact | ok
    agc_steps: int = 0                  # gain jumps fixed in this window
    calibrated: bool = False
    wave: list[float] = field(default_factory=list)   # breathing trace, last WIN_S s at 5 Hz, -1..1
    notes: list[str] = field(default_factory=list)


class VitalsEngine:
    """Feed packets with push_csi()/push_band(); call compute() every ~2 s."""

    def __init__(self, win_s: float = WIN_S):
        self.win = win_s
        self.csi_t: deque[float] = deque()
        self.csi_a: deque[np.ndarray] = deque()
        self.rssi: deque[int] = deque()
        self.band_t: deque[float] = deque()
        self.band_ir: deque[float] = deque()
        self.baseline_motion: float | None = None      # set by calibrate()
        self.baseline_br_power: float | None = None
        self._cal_until: float | None = None
        self._cal_samples: list[tuple[float, float]] = []

    # ── input ──────────────────────────────────────────────
    def push_csi(self, t: float, amp: np.ndarray, rssi: int | None = None) -> None:
        if self.csi_a and len(amp) != len(self.csi_a[-1]):     # bandwidth changed: start over
            self.csi_t.clear(); self.csi_a.clear(); self.rssi.clear()
        self.csi_t.append(t); self.csi_a.append(np.asarray(amp, dtype=np.float32))
        if rssi is not None:
            self.rssi.append(rssi)
        self._trim(t)

    def push_band(self, t: float, ir: float) -> None:
        self.band_t.append(t); self.band_ir.append(float(ir))
        self._trim(t)

    def _trim(self, now: float) -> None:
        while self.csi_t and now - self.csi_t[0] > self.win:
            self.csi_t.popleft(); self.csi_a.popleft()
            if self.rssi:
                self.rssi.popleft()
        while self.band_t and now - self.band_t[0] > self.win:
            self.band_t.popleft(); self.band_ir.popleft()

    # ── empty-room calibration ─────────────────────────────
    def calibrate(self, now: float, seconds: float = 30.0) -> None:
        """Start an empty-room calibration: nobody in the bed for `seconds`."""
        self._cal_until = now + seconds
        self._cal_samples = []

    @property
    def calibrating(self) -> bool:
        return self._cal_until is not None

    # ── processing ─────────────────────────────────────────
    def _matrix(self) -> tuple[np.ndarray, np.ndarray, int] | None:
        """AGC-normalised, despiked, uniformly resampled amplitude matrix [time, subcarrier]."""
        ts = np.fromiter(self.csi_t, float)
        A = np.stack(self.csi_a)
        A = A[:, usable_subcarriers(A.shape[1])]
        A = A[:, A.mean(0) > 1e-3 * A.mean()]
        g = A.mean(1, keepdims=True)
        # count AGC steps: >8 % jump in mean gain between consecutive packets
        steps = int((np.abs(np.diff(np.log(g[:, 0] + 1e-9))) > 0.08).sum())
        A = A / (g + 1e-9)
        A = _hampel(A)
        tu = np.arange(ts[0], ts[-1], 1 / FS)
        if len(tu) < 4:
            return None
        R = np.stack([np.interp(tu, ts, A[:, k]) for k in range(A.shape[1])], axis=1)
        return tu, R, steps

    def compute(self, now: float) -> Vitals:
        v = Vitals(t=now)
        self._trim(now)
        n = len(self.csi_t)
        if n >= 2:
            span = self.csi_t[-1] - self.csi_t[0]
            v.pkt_rate = (n - 1) / span if span > 0 else 0.0
            if self.rssi:
                v.rssi = float(np.median(self.rssi))
        if n < 20 or now - self.csi_t[-1] > 3:
            v.presence = "no_signal"
            v.notes.append("No CSI: is the Pi forwarding and the router sending data?")
            self._band(v)
            return v

        span = self.csi_t[-1] - self.csi_t[0]
        if span < 12:
            v.presence = "warming_up"
            self._band(v)
            return v
        if v.pkt_rate < 20:
            v.notes.append(f"Low packet rate ({v.pkt_rate:.0f}/s): run traffic_gen; heart rate needs 50+/s")

        mat = self._matrix()
        if mat is None:
            v.presence = "warming_up"; self._band(v); return v
        _, R, v.agc_steps = mat
        R = R - R.mean(0)

        # movement: broadband energy over the last 4 s
        mv = _bp(R, *MOVE_BAND)[-int(4 * FS):]
        motion_raw = float(np.median(mv.std(0)))
        br_sig = _bp(R, *BR_BAND)
        br_power = float(np.median(br_sig.std(0)))

        if self._cal_until is not None:
            self._cal_samples.append((motion_raw, br_power))
            if now >= self._cal_until and len(self._cal_samples) >= 3:
                arr = np.array(self._cal_samples)
                self.baseline_motion = float(np.median(arr[:, 0])) + 1e-9
                self.baseline_br_power = float(np.median(arr[:, 1])) + 1e-9
                self._cal_until = None
            v.notes.append("Calibrating: keep the bed empty")

        base_m = self.baseline_motion or 2e-3       # sensible defaults before calibration
        base_b = self.baseline_br_power or 2e-3
        v.calibrated = self.baseline_motion is not None
        v.motion = motion_raw / base_m

        # breathing
        per = _periodicity(br_sig, BR_BAND)
        top = np.argsort(per)[-max(4, R.shape[1] // 6):]
        comp = _pca1(br_sig[:, top])
        br, br_conf, _ = _peak_rate(comp, BR_BAND)
        w = comp[:: int(FS / 5)]
        v.wave = np.round(w / (np.abs(w).max() + 1e-12), 3).tolist()
        breathing_strength = br_power / base_b

        # presence decision
        if v.motion > 6:
            v.presence = "moving"
        elif breathing_strength > 2.5 and br_conf > 0.25:
            v.presence = "still"
        elif v.motion < 2 and breathing_strength < 1.8:
            v.presence = "empty"
        else:
            v.presence = "still" if br_conf > 0.4 else "empty"

        if v.presence == "still" and br_conf > 0.25:
            v.br, v.br_conf = round(br, 1), round(br_conf, 2)
            # heart rate: subtract breathing + its harmonics, then look in 0.8-2.5 Hz
            f_br = br / 60
            clean = _remove_harmonics(R, f_br)
            hr_sig = _bp(clean, *HR_BAND)
            per_h = _periodicity(hr_sig, HR_BAND)
            top_h = np.argsort(per_h)[-max(4, R.shape[1] // 6):]
            comp_h = _pca1(hr_sig[:, top_h])
            notch = [k * f_br for k in range(2, int((HR_BAND[1] + 0.1) / f_br) + 1)]
            hr, hr_conf, snr = _peak_rate(comp_h, HR_BAND, notch=notch)
            # consistency: the first and last 2/3 of the window must agree,
            # otherwise the "peak" is noise (e.g. HR sits on a breathing harmonic)
            n2 = int(len(comp_h) * 2 / 3)
            hr_a, _, _ = _peak_rate(comp_h[:n2], HR_BAND, notch=notch)
            hr_b, _, _ = _peak_rate(comp_h[-n2:], HR_BAND, notch=notch)
            consistent = abs(hr_a - hr) <= 6 and abs(hr_b - hr) <= 6
            # a real heartbeat stands far above the noise floor (SNR > 40 in tests);
            # leftovers after breathing removal sit below ~20
            if not consistent or snr < 40:
                hr_conf = min(hr_conf, 0.2)
            v.hr_conf = round(hr_conf, 2)
            if hr_conf >= 0.3 and v.pkt_rate >= 30:
                v.hr = round(hr)
        elif v.presence == "moving":
            v.notes.append("Movement: vitals paused until the person is still")

        self._band(v)
        return v

    def _band(self, v: Vitals) -> None:
        if len(self.band_t) < 300:
            v.band_status = "no_data"
            return
        ts = np.fromiter(self.band_t, float)
        ir = np.fromiter(self.band_ir, float)
        if ir.mean() < 50_000:
            v.band_status = "no_contact"
            return
        fs = 100.0
        tu = np.arange(ts[0], ts[-1], 1 / fs)
        x = np.interp(tu, ts, ir)
        f = _bp(x, 0.7, 3.5, fs)
        # autocorrelation finds the full beat period; peak-picking double-counts the
        # dicrotic notch (the second small bump in each pulse) at slow heart rates
        f = f - f.mean()
        ac = np.correlate(f, f, "full")[len(f) - 1:]
        ac /= ac[0] + 1e-12
        lo, hi = int(fs * 60 / 180), int(fs * 60 / 40)        # 40-180 bpm
        seg = ac[lo:hi]
        pk, props = find_peaks(seg, height=0.3)
        if len(pk):
            lag = lo + pk[int(np.argmax(props["peak_heights"]))]
            # prefer the shortest lag that is nearly as strong (avoid 2x period)
            for p_ in pk:
                if ac[lo + p_] >= 0.9 * ac[lag]:
                    lag = lo + p_
                    break
            v.band_hr = round(60 * fs / lag)
            v.band_status = "ok"
        else:
            v.band_status = "no_contact"
