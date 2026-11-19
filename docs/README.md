# Gloog bring-up guide

From blank hardware to live CSI on a laptop. This is the exact setup we run.

**You need:** Raspberry Pi 3B+, 5V 2.5A micro-USB adapter, microSD card or USB pen drive (8 GB+), Tenda N301 router, LAN cable, laptop with an Ethernet port, Seeed XIAO ESP32-C3 + its antenna, MAX30102 sensor.

```
 Tenda router ))) Wi-Fi )))  Pi 3B+ ──LAN cable──  Laptop (receiver.py)
      ▲                                             ▲
      └──── Wi-Fi ──── Reference band (XIAO) ───────┘
```

---

## A. Router (once)

1. Power the Tenda, join its Wi-Fi from your phone, open **http://192.168.0.1**.
2. Quick setup: connection type **Dynamic IP**, Wi-Fi name **`gloog`**, set a password.
3. Wireless settings: **Channel 6**, **Channel width 20 MHz**. Not "auto". Save, then check it shows *Current Channel: 6*.
4. Get the router's MAC (BSSID). On a Windows laptop joined to `gloog`:
   ```
   netsh wlan show interfaces
   ```
   Copy the **AP BSSID** line. Ours is `e8:65:d4:f6:0f:28`.

The router needs power only. It does not need internet. Carry it with you.

## B. Raspberry Pi (once)

### B1. Flash
- Image (must be this one, kernel 5.10.92):
  `https://downloads.raspberrypi.org/raspios_lite_armhf/images/raspios_lite_armhf-2022-01-28/2022-01-28-raspios-bullseye-armhf-lite.zip`
- Raspberry Pi Imager → Device **Raspberry Pi 3** → OS **Use custom** (the .zip) → your SD card or pen drive.
- Edit settings: username **`pi`**, a password, **Wi-Fi unchecked**, Services → **enable SSH**.
- A USB pen drive works instead of an SD card: plug it into any Pi USB port.

> [!WARNING]
> **Never run `apt upgrade`** on this Pi. A new kernel breaks Nexmon. `apt install <package>` is fine.

### B2. Give the Pi internet (only for the install)
Easiest: share the laptop's Wi-Fi over the LAN cable.
1. Laptop on home Wi-Fi. LAN cable Pi ↔ laptop.
2. `Win+R` → `ncpa.cpl` → right-click **Wi-Fi** → Properties → **Sharing** → tick *Allow other network users…* → choose **Ethernet** → OK.
3. Power the Pi, wait ~2 min (first boot is slow), then:
   ```
   ssh pi@raspberrypi.local
   ```
   Not found? Run `arp -a` and use the `192.168.137.x` address.

(Alternative: plug the Pi straight into a router that has internet.)

### B3. Install Nexmon CSI (prebuilt, ~3 min)
On the Pi:
```bash
uname -r          # must print 5.10.92-v7+
ping -c 3 google.com
curl -fsSL https://raw.githubusercontent.com/nexmonster/nexmon_csi_bin/main/install.sh | sudo bash
sudo reboot
```
After this the Pi's Wi-Fi is capture-only. You always reach it over the LAN cable.

### B4. Quick check
Reconnect with `ssh pi@raspberrypi.local`, then:
```bash
P=$(mcp -C 1 -N 1 -c 6/20 -m e8:65:d4:f6:0f:28)
sudo ip link set wlan0 up
sudo nexutil -Iwlan0 -s500 -b -l34 -v$P
sudo iw dev wlan0 interface add mon0 type monitor
sudo ip link set mon0 up
sudo tcpdump -i wlan0 dst port 5500 -c 20
```
Make the router send data (a phone on `gloog` refreshing 192.168.0.1). You want lines like `10.10.10.10.5500 > 255.255.255.255.5500: UDP, length 274`. That is CSI.

### B5. Get the code
```bash
sudo apt install -y git
git clone https://github.com/Genzis-Generations-Ahead/gloog ~/gloog
```
Update later with `cd ~/gloog && git pull`.

## C. Run it (every session)

**Pi** (settings live in `firmware/pi/gloog.conf`):
```bash
cd ~/gloog/firmware/pi && sudo ./start_csi.sh
```
It prints `[gloog] NN CSI pkt/s` once the router is sending data. CSI is broadcast down the LAN cable, so any laptop on the cable receives it.

**Laptop, option 1 (dashboard, recommended):**
```bash
cd frontend && npm install && npm run build      # once, builds the dashboard
cd ../backend && pip install -r requirements.txt
python -m gloog_api                               # open http://localhost:8000
```
**Laptop, option 2 (console only):**
```bash
cd signal-processing
pip install -r requirements.txt
python receiver.py --calibrate                    # keep the bed EMPTY for the first 30 s
```
Run one or the other, not both (they share the UDP ports).
Allow Python through Windows Firewall, **Private and Public**. Put the laptop's Wi-Fi on **`gloog`** so the band can reach it.

**Traffic:** CSI only comes from frames the router sends, so it must be busy at a steady rate. Flash `firmware/tests/traffic_gen` onto a spare XIAO (set your Wi-Fi password in it first): it gives a steady 100 packets/s. Heart rate needs 50+/s.

Console lines look like:
```
CSI 100pkt/s STILL motion=1.6x BR=15.0/min HR=72bpm agc_fixed=2 | BAND HR=72bpm
```
`motion` is relative to the empty room (calibrate once per room: dashboard button or `--calibrate`). `HR=–` means the Wi-Fi heart rate wasn't sure enough to show; that's by design.
Logs land in `signal-processing/logs/` as CSV.

## D. Reference band

**Wiring** (hold the XIAO with USB-C pointing up, component side facing you):
```
          [USB-C]
   D0  ●           ● 5V
   D1  ●           ● GND   ← MAX30102 GND
   D2  ●           ● 3V3   ← MAX30102 VIN
   D3  ●           ● D10
   D4  ●  ← SDA    ● D9
   D5  ●  ← SCL    ● D8
   D6  ●           ● D7
```
- **Click the antenna onto the XIAO.** Without it RSSI sits around -90 dBm; with it, around -20 to -50.

**Arduino IDE:**
- Boards Manager URL: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json` → install **esp32**.
- Library: **SparkFun MAX3010x**.
- Board **XIAO_ESP32C3**, Tools → **USB CDC On Boot: Enabled**.
- Upload won't start? Hold **B**, tap **R**, release **B**, upload again.

**Test in order:**
1. `firmware/tests/wifi_test`: connects to `gloog`, prints RSSI.
2. `firmware/tests/i2c_scanner`: must print `Found 0x57`.
3. `firmware/band`: the real thing.

**Band Wi-Fi setup (no code edits):**
1. First power-on opens hotspot **`Gloog-Band-Setup`**. Join it on your phone; the setup page pops up (or open http://192.168.4.1).
2. Pick `gloog` (2.4 GHz only), enter the password, Save. It remembers it.
3. With `receiver.py` running, the band finds the laptop on its own and starts streaming.
4. Change network: hold **B** for 3 s while it's running.

Serial Monitor (115200) shows `wifi=ok laptop=192.168.0.x sensor=ok sent=…`.

## E. Troubleshooting

| Symptom | Fix |
|---|---|
| SSH keeps dropping / Pi restarts | Weak power. Run `vcgencmd get_throttled`; anything but `0x0` means use a proper 5V 2.5A adapter |
| `Could not resolve raspberrypi.local` | Pi still booting, wait 2 min. Or `arp -a` → `ssh pi@192.168.137.x` |
| Host key warning | `ssh-keygen -R raspberrypi.local` |
| Pi shows no `CSI pkt/s` | Router idle: run traffic. Check channel and BSSID in `gloog.conf` |
| Dashboard says *No signal* / receiver says `CSI: no data` | Pi script not running, or firewall blocked Python (allow Private + Public) |
| `BAND: no data` | Laptop Wi-Fi not on `gloog`, or band not set up yet |
| XIAO RSSI around -90 | Antenna not clicked on |
| No COM port for the XIAO | Charge-only USB cable, or use the B + R boot trick |
| `scp` prints a usage message | Missing the source folder: `scp -r pi pi@raspberrypi.local:~/gloog` |
| Commands error in PowerShell | You're on Windows, not the Pi. The Pi prompt is green `pi@raspberrypi` |

| Presence wrong (says Resting in an empty bed) | Calibrate the empty room (dashboard → Signal → Calibrate) |
| Heart rate always `–` | Packet rate under 50/s (run traffic_gen), or the person is moving |

## No hardware? Use the simulator

```bash
cd signal-processing
python -m gloog_engine.simulator --scenario    # fake Pi + band: empty -> still -> moving, loops
```
Then run the backend (or `receiver.py`) as usual. Tests: `python -m pytest -q` in `signal-processing/` and `backend/`.

## Checklist

- [x] Router on fixed channel 6 / 20 MHz, BSSID noted
- [x] Pi flashed (2022-01-28 bullseye lite, kernel 5.10.92), SSH working
- [x] Nexmon CSI installed, tcpdump shows UDP 5500 packets
- [ ] `start_csi.sh` → `receiver.py` shows live `CSI NNpkt/s`
- [ ] XIAO soldered, I2C scanner finds `0x57`
- [ ] Band set up from phone, `BAND HR` shows in receiver
- [ ] Empty room / walking / lying still captures recorded
- [ ] Breathing phantom runs at set bpm, receiver BR matches
- [ ] Dashboard shows live vitals on http://localhost:8000
- [ ] Phantom test: 12 / 18 / 24 bpm on 2 routers, logs saved for the paper
