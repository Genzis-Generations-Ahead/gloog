"""Nexmon CSI packet format (kernel 5.10.92, BCM43455c0 / Pi 3B+).

UDP payload (sent by the Pi on port 5500, forwarded to the laptop on 5501):
    0   2  magic 0x1111
    2   1  RSSI (int8, dBm)
    3   1  frame control
    4   6  source MAC
    10  2  sequence number (LE)
    12  2  core + spatial stream
    14  2  chanspec
    16  2  chip version
    18  .. CSI: int16 I, int16 Q per subcarrier (LE), 64 subcarriers at 20 MHz
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = b"\x11\x11"
HEADER = 18

# 20 MHz, 64-point FFT after fftshift: index 32 is DC. Guard bands (0..3, 61..63)
# and DC carry no signal; pilots (11, 25, 39, 53) are fine for amplitude.
NULL_20MHZ = np.array([0, 1, 2, 3, 32, 61, 62, 63])


@dataclass(frozen=True)
class CsiPacket:
    rssi: int
    seq: int
    mac: str
    csi: np.ndarray          # complex64, fftshifted

    @property
    def amp(self) -> np.ndarray:
        return np.abs(self.csi)


def decode(p: bytes) -> CsiPacket | None:
    """Returns None for anything that isn't a valid Nexmon CSI payload."""
    if len(p) < HEADER + 8 or p[:2] != MAGIC or (len(p) - HEADER) % 4:
        return None
    rssi = struct.unpack("b", p[2:3])[0]
    mac = ":".join(f"{b:02x}" for b in p[4:10])
    seq = struct.unpack("<H", p[10:12])[0]
    iq = np.frombuffer(p[HEADER:], dtype="<i2").astype(np.float32)
    csi = np.fft.fftshift(iq[0::2] + 1j * iq[1::2]).astype(np.complex64)
    return CsiPacket(rssi, seq, mac, csi)


def encode(csi: np.ndarray, rssi: int = -40, seq: int = 0, mac: str = "e8:65:d4:f6:0f:28") -> bytes:
    """Inverse of decode (used by the simulator and tests)."""
    raw = np.fft.ifftshift(np.asarray(csi, dtype=np.complex64))
    iq = np.empty(raw.size * 2, dtype="<i2")
    iq[0::2] = np.clip(np.round(raw.real), -32768, 32767)
    iq[1::2] = np.clip(np.round(raw.imag), -32768, 32767)
    head = MAGIC + struct.pack("b", rssi) + b"\x08" + bytes(int(x, 16) for x in mac.split(":")) \
        + struct.pack("<H", seq & 0xFFFF) + b"\x00\x00" + struct.pack("<H", 0x1006) + struct.pack("<H", 0x4345)
    return head + iq.tobytes()


def usable_subcarriers(n: int) -> np.ndarray:
    """Indices that carry signal for an n-subcarrier capture."""
    keep = np.ones(n, dtype=bool)
    if n == 64:
        keep[NULL_20MHZ] = False
    return np.flatnonzero(keep)
