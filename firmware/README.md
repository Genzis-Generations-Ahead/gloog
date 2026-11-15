# Firmware

| Folder | Runs on | What |
|---|---|---|
| `pi/` | Raspberry Pi 3B+ (Nexmon CSI, kernel 5.10.92) | `start_csi.sh` configures CSI capture, `forward_csi.py` sends CSI to the laptop over Ethernet (UDP 5501) |
| `band/` | Seeed XIAO ESP32-C3 + MAX30102 | Reference PPG band, streams IR/RED at 100 Hz over UDP 5600 |
| `phantom/` | Arduino Uno/Nano + servo | Breathing phantom, serial-controlled bpm |
| `tests/` | XIAO ESP32-C3 | `wifi_test`, `i2c_scanner`, `traffic_gen` |

## Pi setup (once)
1. Flash `2022-01-28-raspios-bullseye-armhf-lite` (kernel 5.10.92). Never run `apt upgrade`.
2. `curl -fsSL https://raw.githubusercontent.com/nexmonster/nexmon_csi_bin/main/install.sh | sudo bash` then reboot.

## Run the Pi (after every boot)
```
cd ~/gloog/firmware/pi
sudo ./start_csi.sh
```
Settings come from `gloog.conf` (channel, router BSSID, target). Default target is `broadcast`, so whichever laptop is on the Ethernet cable gets the CSI, with no IP to set.
Different router? Edit `gloog.conf`, or pass args: `sudo ./start_csi.sh 6/20 <bssid>`.

Router: Tenda N301, SSID `gloog`, channel 6, 20 MHz fixed. Carry it; it needs power only, no internet.

## Band Wi-Fi setup (phone, no code changes)
1. Power the band. With no saved Wi-Fi it opens hotspot `Gloog-Band-Setup`.
2. Join it on your phone; the setup page pops up (or open http://192.168.4.1).
3. Pick the network (2.4 GHz only), enter the password, Save. It remembers it.
4. Run `receiver.py` on the laptop: the band finds the laptop by itself (UDP 5601 beacon).
5. To change network: hold the **B** button 3 s while running.
