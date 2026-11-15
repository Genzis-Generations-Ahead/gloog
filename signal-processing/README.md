# Signal processing

`receiver.py` runs on the laptop. It listens for Pi CSI (UDP 5501) and band PPG (UDP 5600), logs both to `logs/` as CSV, and prints presence, breathing rate, CSI heart rate and band heart rate every 2 s.

```
pip install numpy scipy
python receiver.py
```
Allow Python through Windows Firewall (Private + Public).

It also broadcasts `GLOOG_RX` on UDP 5601 every 2 s so the band finds the laptop automatically.
