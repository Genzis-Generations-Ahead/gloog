import { useEffect, useRef, useState } from 'react';

export type Presence = 'no_signal' | 'warming_up' | 'empty' | 'still' | 'moving';

export interface Vitals {
  t: number; pkt_rate: number; rssi: number | null; presence: Presence; motion: number;
  br: number | null; br_conf: number; hr: number | null; hr_conf: number;
  band_hr: number | null; band_status: 'no_data' | 'no_contact' | 'ok';
  agc_steps: number; calibrated: boolean; wave: number[]; notes: string[];
}
export interface Alert { id: number; kind: string; level: 'info' | 'warn' | 'urgent'; message: string; opened: number; cleared: number | null; acked: boolean }
export interface Settings { bed_name: string; no_move_minutes: number; empty_minutes: number; br_low: number; br_high: number }
export interface Status {
  bed: string; vitals: Vitals; minutes_still: number | null; calibrating: boolean;
  alerts: Alert[]; packets: Record<string, number>; uptime_s: number; settings: Settings;
}
export interface Point { t: number; presence: Presence; motion: number; br: number | null; hr: number | null; band_hr: number | null; pkt_rate: number }

const j = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...init });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
};
export const api = {
  history: (minutes = 30) => j<{ points: Point[] }>(`/api/history?minutes=${minutes}`),
  ack: (id: number) => j(`/api/alerts/${id}/ack`, { method: 'POST' }),
  calibrate: (seconds = 30) => j('/api/calibrate', { method: 'POST', body: JSON.stringify({ seconds }) }),
  saveSettings: (s: Partial<Settings>) => j<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(s) }),
};

/** Wi-Fi vision columns arrive 5x/s: delivered outside React state so they don't re-render the page. */
type CsiFn = (v: number[], t: number) => void;
const csiSubs = new Set<CsiFn>();
export const onCsi = (fn: CsiFn) => { csiSubs.add(fn); return () => { csiSubs.delete(fn); }; };

/** Live status over WebSocket, with auto-reconnect. */
export function useLive() {
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState(false);
  const [history, setHistory] = useState<Point[]>([]);
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null, closed = false, timer = 0;
    const open = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => { setConnected(true); retry.current = 0; api.history(30).then((h) => setHistory(h.points)).catch(() => {}); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'csi') { csiSubs.forEach((fn) => fn(msg.v, msg.t)); return; }
        const s: Status = msg;
        setStatus(s);
        const v = s.vitals;
        setHistory((h) => {
          if (h.length && h[h.length - 1].t >= v.t) return h;
          const p: Point = { t: v.t, presence: v.presence, motion: v.motion, br: v.br, hr: v.hr, band_hr: v.band_hr, pkt_rate: v.pkt_rate };
          return [...h.filter((x) => x.t > v.t - 30 * 60), p];
        });
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(open, Math.min(8000, 500 * 2 ** retry.current++));
      };
    };
    open();
    const ping = window.setInterval(() => ws?.readyState === 1 && ws.send('ping'), 20000);
    return () => { closed = true; clearTimeout(timer); clearInterval(ping); ws?.close(); };
  }, []);

  return { status, connected, history };
}
