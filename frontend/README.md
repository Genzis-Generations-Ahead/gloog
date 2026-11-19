# Dashboard

React + Vite, Gloog style (neo-brutal bento, pastel + neon, Lucide icons). Live over WebSocket.

```bash
npm install
npm run build      # the backend serves dist/ at http://localhost:8000
npm run dev        # development with hot reload (proxies /api and /ws to :8000)
```
Cards: patient state, breathing rate + live chest trace, Wi-Fi vision (raw subcarrier waterfall, 5 columns/s), heart rate (Wi-Fi vs band), time since last movement, alerts (acknowledge), trend, signal health + empty-room calibration, settings.
