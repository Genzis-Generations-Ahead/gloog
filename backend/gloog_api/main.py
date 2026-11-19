"""Gloog backend: live vitals API + WebSocket + alerts, and it serves the dashboard.

    cd backend
    pip install -r requirements.txt
    python -m gloog_api                 # http://localhost:8000   (dashboard + API)

It listens for the Pi (UDP 5501) and the band (UDP 5600) itself: run it INSTEAD of
signal-processing/receiver.py, not next to it (they would fight over the ports).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "signal-processing"))

from gloog_engine.runtime import Receiver  # noqa: E402
from gloog_engine.vitals import Vitals, VitalsEngine  # noqa: E402

from .alerts import AlertEngine, Settings  # noqa: E402

SETTINGS_FILE = Path(os.environ.get("GLOOG_SETTINGS", Path(__file__).resolve().parents[1] / "settings.json"))
LOG_DIR = os.environ.get("GLOOG_LOG_DIR", str(Path(__file__).resolve().parents[1] / "logs"))
HISTORY_POINTS = 24 * 3600 // 2          # 24 h at one point per 2 s
DIST = ROOT / "frontend" / "dist"


class Hub:
    """Glue between the receiver thread and async clients."""

    def __init__(self) -> None:
        settings = Settings()
        if SETTINGS_FILE.exists():
            try:
                settings.update(**json.loads(SETTINGS_FILE.read_text()))
            except Exception:
                pass
        self.alerts = AlertEngine(settings)
        self.history: deque[dict] = deque(maxlen=HISTORY_POINTS)
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.rx: Receiver | None = None
        self.latest: Vitals | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        log = None if os.environ.get("GLOOG_NO_LOG") else LOG_DIR
        self.rx = Receiver(VitalsEngine(), log_dir=log, on_vitals=self.on_vitals).start()

    # runs on the receiver thread
    def on_vitals(self, v: Vitals) -> None:
        self.latest = v
        self.alerts.update(v)
        self.history.append({"t": round(v.t, 1), "presence": v.presence, "motion": round(v.motion, 2),
                             "br": v.br, "hr": v.hr, "band_hr": v.band_hr, "pkt_rate": round(v.pkt_rate)})
        if self.loop and self.clients:
            payload = json.dumps(self.snapshot())
            asyncio.run_coroutine_threadsafe(self.broadcast(payload), self.loop)

    async def broadcast(self, payload: str) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def snapshot(self) -> dict:
        v = self.latest or Vitals(t=time.time())
        now = time.time()
        return {
            "type": "status",
            "bed": self.alerts.settings.bed_name,
            "vitals": asdict(v),
            "minutes_still": self.alerts.minutes_still(now),
            "calibrating": bool(self.rx and self.rx.engine.calibrating),
            "alerts": [a.to_dict() for a in self.alerts.active()],
            "packets": dict(self.rx.counts) if self.rx else {},
            "uptime_s": round(now - self.rx.started) if self.rx else 0,
            "settings": asdict(self.alerts.settings),
        }


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.start(asyncio.get_running_loop())
    yield
    if hub.rx:
        hub.rx.stop()


app = FastAPI(title="Gloog API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SettingsIn(BaseModel):
    bed_name: str | None = None
    no_move_minutes: float | None = None
    empty_minutes: float | None = None
    br_low: float | None = None
    br_high: float | None = None


class CalibrateIn(BaseModel):
    seconds: float = 30


@app.get("/api/health")
def health():
    return {"ok": True, "receiving": bool(hub.latest and hub.latest.presence != "no_signal")}


@app.get("/api/status")
def status():
    return hub.snapshot()


@app.get("/api/history")
def history(minutes: float = 30):
    cutoff = time.time() - minutes * 60
    pts = [p for p in hub.history if p["t"] >= cutoff]
    step = max(1, len(pts) // 600)                 # at most ~600 points to the browser
    return {"points": pts[::step]}


@app.get("/api/alerts")
def alerts(all: bool = False):
    items = hub.alerts.alerts if all else hub.alerts.active()
    return {"alerts": [a.to_dict() for a in items]}


@app.post("/api/alerts/{alert_id}/ack")
def ack(alert_id: int):
    if not hub.alerts.ack(alert_id):
        raise HTTPException(404, "no such alert")
    return {"ok": True}


@app.post("/api/calibrate")
def calibrate(body: CalibrateIn):
    if not hub.rx:
        raise HTTPException(503, "receiver not running")
    hub.rx.calibrate(max(10.0, min(body.seconds, 120.0)))
    return {"ok": True, "seconds": body.seconds}


@app.get("/api/settings")
def get_settings():
    return asdict(hub.alerts.settings)


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    s = hub.alerts.settings.update(**body.model_dump())
    try:
        SETTINGS_FILE.write_text(json.dumps(asdict(s), indent=2))
    except OSError:
        pass
    return asdict(s)


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        await websocket.send_text(json.dumps(hub.snapshot()))
        while True:
            await websocket.receive_text()             # keep-alive; client may send pings
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(websocket)


# dashboard (after `npm run build` in frontend/)
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if path and f.is_file() else DIST / "index.html")
