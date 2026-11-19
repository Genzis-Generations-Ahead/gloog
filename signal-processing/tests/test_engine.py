"""Gloog signal engine tests. Run from signal-processing/:  python -m pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gloog_engine import VitalsEngine, decode, encode  # noqa: E402
from gloog_engine.simulator import CsiSim, Person, ppg, stream  # noqa: E402


def run(person, secs=32, rate=100, seed=1, t0=0.0, engine=None):
    e = engine or VitalsEngine()
    t = t0
    for t, p in stream(secs, rate, person, seed=seed, t0=t0):
        pk = decode(p)
        e.push_csi(t, pk.amp, pk.rssi)
    return e, e.compute(t)


# ── packet format ─────────────────────────────────────────
def test_encode_decode_roundtrip():
    csi = (np.arange(64) * 3 + 1j * np.arange(64)[::-1]).astype(np.complex64)
    pk = decode(encode(csi, rssi=-37, seq=513))
    assert pk.rssi == -37 and pk.seq == 513 and pk.mac == "e8:65:d4:f6:0f:28"
    np.testing.assert_allclose(pk.csi, csi, atol=1)
    assert len(encode(csi)) == 18 + 64 * 4 == 274          # matches real Nexmon length


def test_decode_rejects_garbage():
    assert decode(b"hello") is None
    assert decode(b"\x11\x11" + b"\x00" * 17) is None


# ── breathing ─────────────────────────────────────────────
@pytest.mark.parametrize("br", [8, 12, 16, 22, 30])
def test_breathing_rate_within_1_per_min(br):
    _, v = run(Person("still", br, 75))
    assert v.presence == "still"
    assert v.br is not None and abs(v.br - br) <= 1


def test_agc_gain_steps_do_not_break_breathing():
    _, v = run(Person("still", 14, 70), secs=40)
    assert v.agc_steps >= 2                    # the simulator really did jump the gain
    assert abs(v.br - 14) <= 1


# ── heart rate: correct or withheld, never confidently wrong ─────
@pytest.mark.parametrize("br,hr", [(15, 72), (14, 66), (16, 80), (20, 85), (12, 90), (24, 110)])
def test_heart_rate_correct_or_withheld(br, hr):
    _, v = run(Person("still", br, hr))
    assert v.hr is None or abs(v.hr - hr) <= 5


def test_heart_rate_found_in_easy_case():
    _, v = run(Person("still", 15, 72))
    assert v.hr is not None and abs(v.hr - 72) <= 3


def test_heart_rate_on_exact_breathing_harmonic_is_withheld():
    _, v = run(Person("still", 12, 60))         # 60 = 5 x 12: physically ambiguous
    assert v.hr is None


def test_low_packet_rate_withholds_hr_and_warns():
    _, v = run(Person("still", 15, 72), rate=20)
    assert v.hr is None
    assert any("packet rate" in n for n in v.notes)


# ── presence ──────────────────────────────────────────────
def test_empty_room():
    _, v = run(Person("empty"))
    assert v.presence == "empty" and v.br is None


def test_moving_person():
    _, v = run(Person("moving", 15, 72))
    assert v.presence == "moving"


def test_calibration_sets_baseline():
    e = VitalsEngine()
    e.calibrate(0.0, seconds=20)
    t = 0.0
    for t, p in stream(24, 100, Person("empty"), seed=3):
        pk = decode(p); e.push_csi(t, pk.amp)
        if int(t * 100) % 200 == 0:
            e.compute(t)
    e.compute(t)
    assert not e.calibrating and e.baseline_motion is not None
    e, v = run(Person("still", 15, 72), seed=3, t0=t + 1, engine=e)
    assert v.calibrated and v.presence == "still"


def test_no_signal_and_warming_up():
    e = VitalsEngine()
    assert e.compute(0).presence == "no_signal"
    sim = CsiSim()
    for i in range(500):                          # 5 s of data
        e.push_csi(i / 100, np.abs(sim.frame(i / 100, Person())))
    assert e.compute(5).presence == "warming_up"


# ── reference band ────────────────────────────────────────
@pytest.mark.parametrize("hr", [58, 72, 96])
def test_band_heart_rate(hr):
    e = VitalsEngine()
    for i in range(2500):
        e.push_band(i / 100, ppg(i / 100, hr))
    v = e.compute(25)
    assert v.band_status == "ok" and abs(v.band_hr - hr) <= 3


def test_band_without_skin_contact():
    e = VitalsEngine()
    for i in range(1000):
        e.push_band(i / 100, ppg(i / 100, 70, contact=False))
    assert e.compute(10).band_status == "no_contact"
