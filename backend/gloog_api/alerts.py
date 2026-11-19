"""Bed-monitoring alert rules. Pure logic (no I/O) so it is unit-tested.

Rules (all thresholds in Settings, editable from the dashboard):
  no_movement     patient present but hasn't moved for `no_move_minutes`
                  (pressure-sore turning reminder; default 120 min)
  bed_empty       bed empty for `empty_minutes` after someone was in it
  breathing_low   BR below `br_low` for 60 s (confident readings only)
  breathing_high  BR above `br_high` for 60 s
  signal_lost     no CSI for 15 s
An alert opens once, stays until its condition clears AND it's acknowledged,
and never re-fires while open.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import asdict, dataclass, field

from gloog_engine.vitals import Vitals


@dataclass
class Settings:
    bed_name: str = "Bed 1"
    no_move_minutes: float = 120.0
    empty_minutes: float = 10.0
    br_low: float = 8.0
    br_high: float = 30.0

    def update(self, **kw) -> "Settings":
        for k, v in kw.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, type(getattr(self, k))(v))
        return self


@dataclass
class Alert:
    id: int
    kind: str
    level: str                 # info | warn | urgent
    message: str
    opened: float
    cleared: float | None = None
    acked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AlertEngine:
    settings: Settings = field(default_factory=Settings)
    alerts: list[Alert] = field(default_factory=list)
    last_moved: float | None = None
    last_present: float | None = None
    ever_present: bool = False
    last_signal: float | None = None
    first_update: float | None = None
    br_out_since: dict = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def _open(self, kind: str) -> Alert | None:
        return next((a for a in self.alerts if a.kind == kind and a.cleared is None), None)

    def _raise(self, kind: str, level: str, msg: str, now: float) -> None:
        if not self._open(kind):
            self.alerts.append(Alert(next(self._ids), kind, level, msg, now))

    def _clear(self, kind: str, now: float) -> None:
        a = self._open(kind)
        if a:
            a.cleared = now

    def ack(self, alert_id: int) -> bool:
        for a in self.alerts:
            if a.id == alert_id:
                a.acked = True
                return True
        return False

    def active(self) -> list[Alert]:
        """Shown on the dashboard: still happening, or not yet acknowledged."""
        return [a for a in self.alerts if a.cleared is None or not a.acked][-50:]

    def minutes_still(self, now: float) -> float | None:
        return None if self.last_moved is None else (now - self.last_moved) / 60

    def update(self, v: Vitals, now: float | None = None) -> None:
        now = v.t if now is None else now
        s = self.settings
        present = v.presence in ("still", "moving")

        # signal
        if self.first_update is None:
            self.first_update = now
        if v.presence == "no_signal":
            if now - (self.last_signal or self.first_update) >= 15:
                self._raise("signal_lost", "warn", "No Wi-Fi signal data for 15 s. Check the Pi, the LAN cable and the router.", now)
            return
        self.last_signal = now
        self._clear("signal_lost", now)
        if v.presence == "warming_up":
            return

        # movement / turning
        if v.presence == "moving" or self.last_moved is None and present:
            self.last_moved = now
        if v.presence == "moving":
            self._clear("no_movement", now)
        if present and self.last_moved is not None and now - self.last_moved >= s.no_move_minutes * 60:
            self._raise("no_movement", "warn",
                        f"{s.bed_name}: no movement for {int((now - self.last_moved) // 60)} min. Time to turn the patient.", now)

        # bed occupancy
        if present:
            self.last_present = now
            self.ever_present = True
            self._clear("bed_empty", now)
        elif v.presence == "empty" and self.ever_present and self.last_present is not None \
                and now - self.last_present >= s.empty_minutes * 60:
            self._raise("bed_empty", "urgent", f"{s.bed_name} has been empty for {int((now - self.last_present) // 60)} min.", now)

        # breathing
        for kind, bad, level, msg in (
            ("breathing_low", v.br is not None and v.br < s.br_low, "urgent", f"Breathing is low ({v.br}/min)."),
            ("breathing_high", v.br is not None and v.br > s.br_high, "urgent", f"Breathing is fast ({v.br}/min)."),
        ):
            if bad and v.br_conf >= 0.5:
                self.br_out_since.setdefault(kind, now)
                if now - self.br_out_since[kind] >= 60:
                    self._raise(kind, level, f"{s.bed_name}: {msg}", now)
            else:
                self.br_out_since.pop(kind, None)
                if v.br is not None:
                    self._clear(kind, now)


def now() -> float:
    return time.time()
