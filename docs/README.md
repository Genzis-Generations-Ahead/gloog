# Gloog Bring-up Guide (Pi 3B+ CSI + Reference Band)

Goal for day one: get raw CSI packets flowing from the Pi to a laptop, and a heart-rate stream from the band. Nothing else yet.

> Always follow the official nexmon_csi README (github.com/seemoo-lab/nexmon_csi) for exact kernel versions and build commands. It changes over time. This guide is the order of work, not a replacement for it.

## Part A: Pi 3B+ as CSI collector (owner: Tanush)

### A1. Flash
- Use Raspberry Pi Imager. Pick the Raspberry Pi OS image whose kernel matches the nexmon_csi README table for the 3B+ (bcm43455c0).
- Enable SSH and set Wi-Fi/hostname in Imager's advanced options.
- **Do NOT run `apt full-upgrade` or update the kernel afterwards.** A kernel bump breaks the Nexmon patch.

### A2. Build
- Clone nexmon, then nexmon_csi inside it, as the README says.
- Install the kernel headers and build dependencies listed in the README.
- Build and install the patched firmware. This is the slowest step, so let it run.
- Reboot and confirm wlan0 still comes up.

### A3. Router
- Set the router to **5GHz, channel 36, 80MHz**. (2.4GHz also works, but 5GHz gives wider bandwidth and cleaner spectrum.)
- Note the router's MAC address.

### A4. Configure capture
- Generate parameters with `makecsiparams`. Example: channel 36, 80MHz, core 1, one spatial stream, filtered to your router's MAC:
  `makecsiparams -c 36/80 -C 1 -N 1 -m <ROUTER_MAC>`
- Load the output string into the chip with `nexutil` (exact command is in the README; use the string `makecsiparams` printed).
- Create the monitor interface and bring it up (README has the `iw` / `ip link` commands).

### A5. Capture
- `tcpdump -i wlan0 dst port 5500 -vv -w capture.pcap`
- CSI arrives as UDP on port 5500. If the pcap has packets, the sensing side works.
- The router must be sending frames. If counts are low or bursty, generate steady traffic (ping the router from the Pi, or run a phone/laptop against it).

### A6. Sanity test (do this before any phantom or ML work)
1. Capture 60s in an **empty room**.
2. Capture 60s with a person **walking** around.
3. Capture 60s with a person **lying still, breathing normally**.
4. Parse the pcaps on the laptop (nexmon_csi ships parsing examples) and plot amplitude per subcarrier over time.
- Pass: the walking capture is clearly different from the empty one. Breathing may show as a slow ripple in the still capture.

## Part B: Reference band (owner: pick one teammate)

- XIAO ESP32-C3 + MAX30102 over I2C (VCC, GND, SDA, SCL).
- Firmware: read the PPG sensor and stream heart rate over BLE.
- Test: compare the band's reading against a phone/finger check.
- Log with timestamps. Clock sync between the band log and the CSI capture is what makes the labelled dataset usable later.
- Wrist PPG is noisy. Plan some artifact-rejection filtering on this side too.

## Part C: What is NOT done by flashing the Pi

The Pi only collects raw CSI. Still to build:
- Signal processing: denoising, then movement/presence, breathing rate, heart rate.
- Bed-monitoring logic: "no movement for X minutes" raises an alert.
- Backend and dashboard/app.
- Calibration step per room/router (empty-room baseline).

Expected difficulty: presence/movement first, breathing second, heart rate last.

## Checklist

- [ ] Pi flashed with the pinned image, kernel NOT upgraded
- [ ] Nexmon + nexmon_csi built, wlan0 healthy after reboot
- [ ] Router on 5GHz ch 36/80, MAC noted
- [ ] `makecsiparams` + `nexutil` loaded
- [ ] pcap shows UDP port 5500 packets
- [ ] Empty vs walking vs still captures recorded
- [ ] Band streams HR over BLE
- [ ] Captures and notes pushed to the gloog repo (docs/ and signal-processing/)

