"""Alert rule tests. Run from backend/:  python -m pytest -q"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "signal-processing"))
sys.path.insert(0, str(ROOT / "backend"))

from gloog_api.alerts import AlertEngine, Settings  # noqa: E402
from gloog_engine.vitals import Vitals  # noqa: E402


def v(t, presence="still", br=15.0, conf=0.9, rate=100.0):
    return Vitals(t=t, presence=presence, br=br if presence == "still" else None, br_conf=conf, pkt_rate=rate)


def kinds(e):
    return {a.kind for a in e.active()}


def test_no_movement_after_threshold_then_clears_on_move():
    e = AlertEngine(Settings(no_move_minutes=10))
    e.update(v(0, "moving"))
    for t in range(2, 10 * 60, 2):
        e.update(v(t))
    assert "no_movement" not in kinds(e)
    e.update(v(10 * 60 + 2))
    assert "no_movement" in kinds(e)
    e.update(v(10 * 60 + 4, "moving"))
    a = [x for x in e.alerts if x.kind == "no_movement"][0]
    assert a.cleared is not None
    assert e.ack(a.id) and "no_movement" not in kinds(e)


def test_alert_fires_once():
    e = AlertEngine(Settings(no_move_minutes=1))
    e.update(v(0, "moving"))
    for t in range(2, 600, 2):
        e.update(v(t))
    assert sum(a.kind == "no_movement" for a in e.alerts) == 1


def test_bed_empty_only_after_someone_was_there():
    e = AlertEngine(Settings(empty_minutes=1))
    for t in range(0, 300, 2):
        e.update(v(t, "empty"))
    assert "bed_empty" not in kinds(e)
    e.update(v(300, "still"))
    for t in range(302, 400, 2):
        e.update(v(t, "empty"))
    assert "bed_empty" in kinds(e)


def test_breathing_low_needs_60s_and_confidence():
    e = AlertEngine()
    for t in range(0, 50, 2):
        e.update(v(t, br=6))
    assert "breathing_low" not in kinds(e)
    for t in range(50, 70, 2):
        e.update(v(t, br=6))
    assert "breathing_low" in kinds(e)
    e2 = AlertEngine()
    for t in range(0, 200, 2):
        e2.update(v(t, br=6, conf=0.2))                   # low-confidence readings never alarm
    assert "breathing_low" not in kinds(e2)


def test_signal_lost_after_15s():
    e = AlertEngine()
    e.update(v(0))
    for t in range(2, 14, 2):
        e.update(v(t, "no_signal", rate=0))
    assert "signal_lost" not in kinds(e)
    e.update(v(16, "no_signal", rate=0))
    assert "signal_lost" in kinds(e)
    e.update(v(18))
    assert [a for a in e.alerts if a.kind == "signal_lost"][0].cleared == 18


def test_settings_update_types():
    s = Settings().update(no_move_minutes="30", bed_name="Ward 3 · Bed 4", unknown=1)
    assert s.no_move_minutes == 30.0 and s.bed_name == "Ward 3 · Bed 4"
