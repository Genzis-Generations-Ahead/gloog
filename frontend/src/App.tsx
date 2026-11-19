import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, AlertTriangle, Radar, BedDouble, Check, CheckCircle2, Clock, HeartPulse, Radio, RotateCcw, Settings2, Wifi, WifiOff, Wind, X } from 'lucide-react';
import { api, onCsi, useLive, type Point, type Settings, type Status, type Vitals } from './api';

const fmtAgo = (t: number) => {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? 'just now' : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
};

const STATE: Record<Vitals['presence'], { title: string; sub: string; bg: string; Icon: typeof BedDouble }> = {
  still: { title: 'Resting', sub: 'Person in bed, lying still', bg: 'var(--lime)', Icon: BedDouble },
  moving: { title: 'Moving', sub: 'Vitals pause while the person moves', bg: 'var(--sun)', Icon: Activity },
  empty: { title: 'Bed empty', sub: 'No one detected', bg: 'var(--lilac)', Icon: BedDouble },
  warming_up: { title: 'Warming up', sub: 'Collecting the first seconds of signal', bg: 'var(--sky)', Icon: Radio },
  no_signal: { title: 'No signal', sub: 'Check the Pi, LAN cable and router', bg: 'var(--red)', Icon: WifiOff },
};

export default function App() {
  const { status, connected, history } = useLive();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const v = status?.vitals;

  return (
    <div className="wrap">
      <header className="top">
        <div className="word">gloog<i>live</i></div>
        <span className="bed">{status?.bed ?? '—'}</span>
        <div className="spacer" />
        <span className="conn" role="status"><span className={`dot ${connected && v?.presence !== 'no_signal' ? 'live' : ''}`} />{connected ? 'Connected' : 'Reconnecting…'}</span>
        <button className="btn" onClick={() => setSettingsOpen(true)}><Settings2 size={18} />Settings</button>
      </header>

      {!status || !v ? <div className="card"><div className="label">Waiting for the Gloog backend…</div></div> : (
        <main className="bento">
          <Hero s={status} v={v} />
          <Breathing v={v} />
          <WifiVision v={v} />
          <Heart v={v} />
          <Stillness s={status} v={v} />
          <Alerts s={status} />
          <Trend points={history} s={status} />
          <Signal s={status} v={v} />
        </main>
      )}
      <div className="foot">Gloog by Genzis · research prototype, not a medical device</div>
      {settingsOpen && status && <SettingsDrawer s={status.settings} onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

function Hero({ s, v }: { s: Status; v: Vitals }) {
  const st = STATE[v.presence];
  return (
    <section className="card c-hero" aria-label="Patient state">
      <div className="label"><BedDouble size={16} />Patient</div>
      <div className="state">
        <span className="ic" style={{ background: st.bg }}><st.Icon size={32} /></span>
        <div><h2>{st.title}</h2><div className="sub">{st.sub}</div></div>
      </div>
      <ul className="checks">
        <li><CheckCircle2 size={18} />No camera, nothing worn: Wi-Fi only</li>
        <li><CheckCircle2 size={18} />{v.calibrated ? 'Room calibrated' : 'Using default room settings'}{s.calibrating ? ' · calibrating now, keep the bed empty' : ''}</li>
        <li><CheckCircle2 size={18} />Movement level {v.motion.toFixed(1)}× room noise</li>
      </ul>
    </section>
  );
}

function wavePath(w: number[], W = 600, H = 120) {
  if (w.length < 2) return { line: '', area: '' };
  const pts = w.map((y, i) => [(i / (w.length - 1)) * W, H / 2 - y * (H / 2 - 8)]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  return { line, area: `${line} L${W},${H} L0,${H} Z` };
}

function Breathing({ v }: { v: Vitals }) {
  const { line, area } = useMemo(() => wavePath(v.wave), [v.wave]);
  const show = v.presence === 'still' && v.br != null;
  return (
    <section className="card c-br" aria-label="Breathing">
      <div className="head">
        <div className="label"><Wind size={16} />Breathing</div>
        {show && <span className={`chip ${v.br_conf >= 0.6 ? 'lime' : 'sun'}`}>{Math.round(v.br_conf * 100)}% sure</span>}
      </div>
      <div className={`big ${show ? '' : 'dim'}`}>{show ? v.br!.toFixed(0) : '––'}<small>breaths/min</small></div>
      <svg className="wave" viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="Breathing trace, last 30 seconds">
        {show && <><path className="area" d={area} /><path d={line} /></>}
        {!show && <line x1="0" y1="60" x2="600" y2="60" stroke="#b3afa6" strokeWidth="3" strokeDasharray="10 8" />}
      </svg>
      <div className="sub">Chest movement read from Wi-Fi, last 30 s</div>
    </section>
  );
}

function Heart({ v }: { v: Vitals }) {
  return (
    <section className="card c-hr" aria-label="Heart rate">
      <div className="head"><div className="label"><HeartPulse size={16} />Heart rate</div><span className="chip pink">Wi-Fi · experimental</span></div>
      <div className={`big ${v.hr ? '' : 'dim'}`}>{v.hr ?? '––'}<small>bpm</small></div>
      <div className="sub">{v.hr ? `${Math.round(v.hr_conf * 100)}% sure` : v.presence === 'still' ? 'Not sure enough to show' : 'Needs a still person'}</div>
      <div className="kv">
        <span>Reference band</span>
        <b>{v.band_status === 'ok' ? `${v.band_hr} bpm` : v.band_status === 'no_contact' ? 'no skin contact' : 'not connected'}</b>
        {v.hr && v.band_hr && <><span>Difference</span><b>{Math.abs(v.hr - v.band_hr)} bpm</b></>}
      </div>
    </section>
  );
}

function Stillness({ s, v }: { s: Status; v: Vitals }) {
  const limit = s.settings.no_move_minutes;
  const m = v.presence === 'still' || v.presence === 'moving' ? s.minutes_still ?? 0 : null;
  const pct = m == null ? 0 : Math.min(100, (m / limit) * 100);
  return (
    <section className="card c-still" aria-label="Time since last movement">
      <div className="label"><Clock size={16} />Since last movement</div>
      <div className={`big ${m == null ? 'dim' : ''}`}>{m == null ? '––' : m < 1 ? '<1' : Math.floor(m)}<small>min</small></div>
      <div className={`meter ${pct >= 100 ? 'over' : ''}`} role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${pct}%` }} /></div>
      <div className="sub">Turning reminder at {limit} min</div>
    </section>
  );
}

function Alerts({ s }: { s: Status }) {
  const [busy, setBusy] = useState<number | null>(null);
  const list = [...s.alerts].reverse();
  return (
    <section className="card c-alerts" aria-label="Alerts">
      <div className="head"><div className="label"><AlertTriangle size={16} />Alerts</div>{list.length > 0 && <span className="chip red">{list.filter((a) => !a.cleared).length} open</span>}</div>
      {list.length === 0 ? <div className="empty-ok"><CheckCircle2 size={22} />All clear</div> : (
        <div className="alerts">
          {list.map((a) => (
            <div key={a.id} className={`alert ${a.level} ${a.cleared ? 'cleared' : ''}`}>
              <div className="msg">{a.message}<time>{fmtAgo(a.opened)}{a.cleared ? ' · resolved' : ''}</time></div>
              {!a.acked && <button className="btn sm" disabled={busy === a.id} aria-label="Acknowledge" onClick={() => { setBusy(a.id); api.ack(a.id).finally(() => setBusy(null)); }}><Check size={16} /></button>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Trend({ points, s }: { points: Point[]; s: Status }) {
  const W = 800, H = 200, now = Date.now() / 1000;
  // zoom to the data until there are 30 minutes of it (min 3 minutes)
  const first = points.length ? points[0].t : now;
  const span = Math.min(30 * 60, Math.max(3 * 60, now - first + 10));
  const x = (t: number) => ((t - (now - span)) / span) * W;
  const path = (key: 'br' | 'hr' | 'band_hr', lo: number, hi: number) => {
    let d = '', pen = false;
    for (const p of points) {
      const val = p[key];
      if (val == null) { pen = false; continue; }
      const y = H - 10 - ((Math.min(hi, Math.max(lo, val)) - lo) / (hi - lo)) * (H - 20);
      d += `${pen ? 'L' : 'M'}${x(p.t).toFixed(1)},${y.toFixed(1)} `;
      pen = true;
    }
    return d;
  };
  const moves = points.filter((p) => p.presence === 'moving');
  const empties = points.filter((p) => p.presence === 'empty');
  return (
    <section className="card c-trend" aria-label="Last 30 minutes">
      <div className="head"><div className="label"><Activity size={16} />Last {span >= 30 * 60 ? 30 : Math.ceil(span / 60)} minutes</div>
        <div className="legend"><span className="chip"><i className="sw" style={{ background: 'var(--sky)' }} />Breathing</span><span className="chip"><i className="sw" style={{ background: 'var(--pink)' }} />Heart (Wi-Fi)</span><span className="chip"><i className="sw" style={{ background: 'var(--sun)' }} />Moving</span></div>
      </div>
      <svg className="trend" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Breathing and heart-rate trend">
        {empties.map((p) => <rect key={`e${p.t}`} x={x(p.t)} y="0" width="3" height={H} fill="var(--lilac-soft)" />)}
        {moves.map((p) => <rect key={`m${p.t}`} x={x(p.t)} y="0" width="3" height={H} fill="var(--sun)" opacity=".7" />)}
        {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} stroke="#11111118" strokeWidth="1" />)}
        <path d={path('br', 0, 40)} fill="none" stroke="var(--ink)" strokeWidth="5" strokeLinejoin="round" />
        <path d={path('br', 0, 40)} fill="none" stroke="var(--sky)" strokeWidth="3" strokeLinejoin="round" />
        <path d={path('hr', 40, 140)} fill="none" stroke="var(--ink)" strokeWidth="5" strokeLinejoin="round" />
        <path d={path('hr', 40, 140)} fill="none" stroke="var(--pink)" strokeWidth="3" strokeLinejoin="round" />
      </svg>
      <div className="sub">{s.settings.bed_name} · breathing scale 0–40/min, heart 40–140 bpm</div>
    </section>
  );
}

function Signal({ s, v }: { s: Status; v: Vitals }) {
  const [cal, setCal] = useState(false);
  return (
    <section className="card c-signal" aria-label="Signal">
      <div className="head"><div className="label"><Wifi size={16} />Signal</div><span className={`chip ${v.pkt_rate >= 50 ? 'lime' : 'sun'}`}>{Math.round(v.pkt_rate)} pkt/s</span></div>
      <div className="kv">
        <span>Wi-Fi strength</span><b>{v.rssi != null ? `${Math.round(v.rssi)} dBm` : '—'}</b>
        <span>Gain jumps fixed</span><b>{v.agc_steps}</b>
        <span>CSI packets</span><b>{(s.packets.csi ?? 0).toLocaleString()}</b>
        <span>Band samples</span><b>{(s.packets.band ?? 0).toLocaleString()}</b>
        <span>Running</span><b>{Math.floor(s.uptime_s / 60)} min</b>
      </div>
      {v.notes.map((n) => <div key={n} className="note">{n}</div>)}
      <button className="btn lime" style={{ marginTop: 14, width: '100%', justifyContent: 'center' }} disabled={s.calibrating || cal}
        onClick={() => { setCal(true); api.calibrate(30).finally(() => setTimeout(() => setCal(false), 2000)); }}>
        <RotateCcw size={18} />{s.calibrating ? 'Calibrating… keep bed empty' : 'Calibrate empty room (30 s)'}
      </button>
    </section>
  );
}

function SettingsDrawer({ s, onClose }: { s: Settings; onClose: () => void }) {
  const [f, setF] = useState<Settings>(s);
  const [saving, setSaving] = useState(false);
  const num = (k: keyof Settings) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value === '' ? '' : Number(e.target.value) });
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Settings">
        <div className="head"><h3>Settings</h3><button className="btn sm" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        <label className="field">Bed name<input value={f.bed_name} onChange={(e) => setF({ ...f, bed_name: e.target.value })} /></label>
        <label className="field">Turning reminder after (min)<input type="number" min={5} value={f.no_move_minutes} onChange={num('no_move_minutes')} /></label>
        <label className="field">Bed-empty alert after (min)<input type="number" min={1} value={f.empty_minutes} onChange={num('empty_minutes')} /></label>
        <label className="field">Breathing low below (/min)<input type="number" min={2} value={f.br_low} onChange={num('br_low')} /></label>
        <label className="field">Breathing high above (/min)<input type="number" max={60} value={f.br_high} onChange={num('br_high')} /></label>
        <button className="btn lime" style={{ justifyContent: 'center' }} disabled={saving}
          onClick={() => { setSaving(true); api.saveSettings(f).then(onClose).finally(() => setSaving(false)); }}><Check size={18} />Save</button>
      </aside>
    </>
  );
}

// diverging map: below its own average = violet, average = paper, above = pink
const STOPS = [[107, 78, 255], [185, 166, 255], [244, 241, 234], [255, 155, 219], [255, 63, 164]];
function cmap(x: number): string {
  const p = Math.max(0, Math.min(0.9999, x)) * (STOPS.length - 1), i = Math.floor(p), f = p - i;
  const a = STOPS[i], b = STOPS[i + 1];
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}
const COLS = 150;                                   // 30 s at 5 columns/s

function WifiVision({ v }: { v: Vitals }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    const c = ref.current!;
    const ctx = c.getContext('2d')!;
    const fit = () => { const w = Math.round(c.getBoundingClientRect().width); if (w && c.width !== w) { c.width = w; ctx.fillStyle = cmap(0.5); ctx.fillRect(0, 0, c.width, c.height); } };
    fit();
    window.addEventListener('resize', fit);
    let count = 0;
    const off = onCsi((vals) => {
      const W = c.width, H = c.height, cw = Math.max(1, Math.ceil(W / COLS)), rh = H / vals.length;
      ctx.drawImage(c, cw, 0, W - cw, H, 0, 0, W - cw, H);          // scroll left
      vals.forEach((x, k) => { ctx.fillStyle = cmap(x); ctx.fillRect(W - cw, H - (k + 1) * rh, cw, Math.ceil(rh)); });
      if (++count % 5 === 0) setN(vals.length);
    });
    return () => { off(); window.removeEventListener('resize', fit); };
  }, []);
  const hint = v.presence === 'moving' ? 'Movement: streaks across every subcarrier'
    : v.presence === 'still' ? 'Breathing: slow ripples every few seconds'
    : v.presence === 'empty' ? 'Empty: flat, calm bands' : 'Waiting for packets';
  return (
    <section className="card c-vision" aria-label="Wi-Fi vision">
      <div className="head">
        <div className="label"><Radar size={16} />Wi-Fi vision · raw signal</div>
        <div className="legend"><span className="chip lilac">below average</span><span className="chip pink">above average</span><span className="chip">{n || '–'} subcarriers</span></div>
      </div>
      <div className="vision">
        <div className="vaxis" aria-hidden="true"><span>high</span><span>freq</span><span>low</span></div>
        <canvas ref={ref} height={200} role="img" aria-label="Scrolling heatmap of every Wi-Fi subcarrier over the last 30 seconds" />
      </div>
      <div className="between-row"><span>30 s ago</span><span>{hint}</span><span>now</span></div>
    </section>
  );
}
