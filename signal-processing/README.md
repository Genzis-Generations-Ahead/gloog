# Signal processing

`gloog_engine/` is the core, shared by the console receiver and the backend:

| File | What it does |
|---|---|
| `csi.py` | Decode/encode Nexmon CSI packets (Pi 3B+, 20 MHz, 64 subcarriers) |
| `vitals.py` | Presence, movement, breathing rate, heart rate (Wi-Fi) and band heart rate |
| `runtime.py` | UDP receive (CSI 5501, band 5600), band discovery beacon (5601), CSV logs |
| `simulator.py` | Fake Pi + band with known breathing/heart rates, for testing without hardware |

How vitals are computed (every 2 s, on the last 30 s):
1. Drop guard/DC subcarriers.
2. **Gain-jump fix**: divide every packet by its own mean amplitude (the Broadcom chip changes its gain on its own; without this it looks like movement).
3. Remove spikes, resample to 50 Hz.
4. **Movement** = broadband energy vs. the empty-room baseline (calibrate once per room).
5. **Breathing**: pick the most *periodic* subcarriers in 0.1-0.7 Hz, combine (PCA), spectral peak.
6. **Heart rate**: subtract breathing and all its harmonics, look in 0.8-2.5 Hz, and show it only if the peak is strong (SNR > 40), clearly above the runner-up, and the same in both halves of the window. Otherwise `None`: never a confident wrong number.
7. **Band**: heart rate by autocorrelation (peak-picking double-counted the dicrotic notch at slow rates).

```bash
pip install -r requirements.txt
python receiver.py --calibrate          # console, logs to ./logs/
python -m gloog_engine.simulator --scenario   # no hardware
python -m pytest -q                     # 25 tests
```
Simulator benchmark (168 combinations of BR 10-24 and HR 55-110): breathing 168/168 within 1/min; Wi-Fi heart rate 125 correct, 43 withheld, 0 wrong.
