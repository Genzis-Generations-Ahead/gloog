#!/usr/bin/env python3
"""Gloog laptop receiver — fuses Pi CSI (UDP 5501) + reference band PPG (UDP 5600).
- Logs everything to CSV with laptop-side timestamps (one clock = easy sync)
- Every 2 s prints: presence/motion, CSI breathing rate, CSI heart rate, band HR

pip install numpy scipy
python receiver.py            # Ctrl+C to stop; logs land in ./logs/
"""
import csv, os, socket, select, struct, threading, time
from collections import deque
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

CSI_PORT, BAND_PORT, DISC_PORT = 5501, 5600, 5601
WIN_S = 30                      # analysis window (seconds)
os.makedirs("logs", exist_ok=True)
stamp = time.strftime("%Y%m%d_%H%M%S")

def sock(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port)); s.setblocking(False); return s

def decode_csi(p):
    """Nexmon 5.10.92 format, BCM43455c0: 18-byte header + int16 I/Q pairs."""
    rssi = struct.unpack("b", p[2:3])[0]
    seq = struct.unpack("<H", p[10:12])[0]
    iq = np.frombuffer(p[18:], dtype="<i2").astype(np.float32)
    csi = iq[0::2] + 1j * iq[1::2]
    csi = np.fft.fftshift(csi)
    return rssi, seq, csi

def bandpass(x, fs, lo, hi, order=3):
    b, a = butter(order, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, x)

def dominant_bpm(x, fs, lo, hi):
    x = x - x.mean()
    n = 1 << int(np.ceil(np.log2(len(x) * 4)))          # zero-pad for resolution
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), n))
    f = np.fft.rfftfreq(n, 1 / fs)
    m = (f >= lo) & (f <= hi)
    return float(f[m][np.argmax(spec[m])] * 60) if m.any() else float("nan")

def resample(ts, x, fs):
    ts = np.asarray(ts); t = np.arange(ts[0], ts[-1], 1 / fs)
    return t, np.interp(t, ts, x)

def local_ipv4s():
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        ips = []
    try:                                   # fallback: IP of the default route
        t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t.connect(("192.0.2.1", 9)); ips.append(t.getsockname()[0]); t.close()
    except OSError:
        pass
    return sorted(ip for ip in set(ips) if not ip.startswith("127."))

def discovery_beacon():
    """Broadcast 'GLOOG_RX' on every network adapter every 2 s so the band
    can find this laptop's IP by itself."""
    while True:
        for ip in local_ipv4s() + [""]:   # "" = OS default interface
            try:
                b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                b.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                b.bind((ip, 0))
                b.sendto(b"GLOOG_RX", ("255.255.255.255", DISC_PORT))
                b.close()
            except OSError:
                pass
        time.sleep(2)

threading.Thread(target=discovery_beacon, daemon=True).start()
csi_s, band_s = sock(CSI_PORT), sock(BAND_PORT)
csi_ts, csi_amp = deque(), deque()
band_ts, band_ir = deque(), deque()
csi_f = open(f"logs/csi_{stamp}.csv", "w", newline="")
band_f = open(f"logs/band_{stamp}.csv", "w", newline="")
csi_w, band_w = csv.writer(csi_f), csv.writer(band_f)
band_w.writerow(["t_laptop", "seq", "ms_band", "ir", "red"])
last_print, header_done = time.time(), False
print(f"[gloog] listening CSI:{CSI_PORT} BAND:{BAND_PORT}  "
      f"(announcing on {', '.join(local_ipv4s()) or 'no network'})")

try:
    while True:
        r, _, _ = select.select([csi_s, band_s], [], [], 0.5)
        now = time.time()
        for s in r:
            data = s.recv(4096)
            if s is csi_s and data[:2] == b"\x11\x11":
                rssi, seq, csi = decode_csi(data)
                amp = np.abs(csi)
                if not header_done:
                    csi_w.writerow(["t_laptop", "seq", "rssi"] + [f"a{i}" for i in range(len(amp))])
                    header_done = True
                csi_w.writerow([f"{now:.4f}", seq, rssi] + np.round(amp, 1).tolist())
                csi_ts.append(now); csi_amp.append(amp)
            elif s is band_s:
                try:
                    seqb, ms, ir, red = data.decode().split(",")
                except ValueError:
                    continue
                band_w.writerow([f"{now:.4f}", seqb, ms, ir, red])
                band_ts.append(now); band_ir.append(float(ir))

        for ts, dq in ((csi_ts, csi_amp), (band_ts, band_ir)):
            while ts and now - ts[0] > WIN_S:
                ts.popleft(); dq.popleft()

        if now - last_print < 2:
            continue
        last_print = now
        out = []

        if len(csi_ts) > 200:
            rate = len(csi_ts) / (csi_ts[-1] - csi_ts[0])
            A = np.array(csi_amp)                                  # [time, subcarrier]
            A = A[:, A.mean(0) > 1]                                # drop null/guard subcarriers
            var = A.var(0)
            top = np.argsort(var)[-10:]                            # most motion-sensitive subcarriers
            motion = float(np.median(var[top] / (A.mean(0)[top] ** 2 + 1e-9)))
            presence = "MOVING" if motion > 0.01 else ("STILL" if motion > 1e-4 else "EMPTY?")
            fs = 50.0
            t, sig = resample(list(csi_ts), A[:, top].mean(1), fs)
            if len(sig) > fs * 15:
                br = dominant_bpm(bandpass(sig, fs, 0.1, 0.6), fs, 0.1, 0.6)
                hr = dominant_bpm(bandpass(sig, fs, 0.8, 2.2), fs, 0.8, 2.2)
                out.append(f"CSI {rate:.0f}pkt/s {presence} motion={motion:.4f} BR={br:.1f}/min HR={hr:.0f}bpm")
            else:
                out.append(f"CSI {rate:.0f}pkt/s warming up")
        else:
            out.append("CSI: no data (Pi forwarding? router traffic?)")

        if len(band_ts) > 300:
            fs = 100.0
            t, ir = resample(list(band_ts), np.array(band_ir), fs)
            if np.mean(ir) < 50000:
                out.append("BAND: no finger/skin contact")
            else:
                f = bandpass(ir, fs, 0.7, 3.5)
                pk, _ = find_peaks(f, distance=fs * 0.33, prominence=np.std(f) * 0.5)
                hr_b = 60 / np.median(np.diff(pk) / fs) if len(pk) > 3 else float("nan")
                out.append(f"BAND HR={hr_b:.0f}bpm")
        else:
            out.append("BAND: no data")

        print(" | ".join(out), flush=True)
        csi_f.flush(); band_f.flush()
except KeyboardInterrupt:
    pass
finally:
    csi_f.close(); band_f.close()
    print(f"\n[gloog] saved logs/csi_{stamp}.csv and logs/band_{stamp}.csv")
