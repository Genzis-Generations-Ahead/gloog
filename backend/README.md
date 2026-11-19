# Backend

FastAPI app that receives the Pi and the band directly (UDP 5501 / 5600), computes vitals with `gloog_engine`, raises alerts and serves the dashboard.

```bash
pip install -r requirements.txt
python -m gloog_api            # http://localhost:8000  (build the frontend first for the dashboard)
python -m pytest -q            # alert rule tests
```

| Endpoint | |
|---|---|
| `GET /api/status` | latest vitals, alerts, packet counts, settings |
| `GET /api/history?minutes=30` | trend points (one per 2 s, kept 24 h in memory) |
| `GET /api/alerts`, `POST /api/alerts/{id}/ack` | alerts |
| `POST /api/calibrate {"seconds":30}` | empty-room calibration |
| `GET/PUT /api/settings` | bed name, turning reminder, empty-bed and breathing limits (saved to settings.json) |
| `WS /ws` | live status every 2 s |

Alerts: **no movement** (turning reminder, default 120 min), **bed empty** (10 min, only after someone was in it), **breathing low/high** (8 / 30 per min for 60 s, confident readings only), **signal lost** (15 s).
Env: `GLOOG_NO_LOG=1` disables CSV logs, `GLOOG_LOG_DIR`, `GLOOG_SETTINGS`.
