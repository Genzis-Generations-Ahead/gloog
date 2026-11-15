#!/usr/bin/env python3
"""Gloog - sniff Nexmon CSI UDP frames (dst port 5500) on wlan0 and forward
the raw CSI payload to the laptop over Ethernet. Stdlib only.

Usage: sudo python3 forward_csi.py <laptop_ip|broadcast> [port]
  broadcast -> sends to 255.255.255.255 out of eth0, so whatever laptop is on
               the cable receives it (no IP needed).
"""
import socket, struct, sys, time

TARGET = sys.argv[1] if len(sys.argv) > 1 else "broadcast"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5501
ETH_P_ALL = 0x0003
SO_BINDTODEVICE = 25

rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(ETH_P_ALL))
rx.bind(("wlan0", 0))

tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
if TARGET == "broadcast":
    tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    tx.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, b"eth0\0")
    dest = ("255.255.255.255", PORT)
else:
    dest = (TARGET, PORT)

n, errs, t0 = 0, 0, time.time()
print(f"[gloog] waiting for CSI... (router must be sending data)", flush=True)
while True:
    frame = rx.recv(4096)
    if len(frame) < 42 or frame[12:14] != b"\x08\x00":      # IPv4 only
        continue
    if frame[23] != 17:                                      # UDP only
        continue
    ihl = (frame[14] & 0x0F) * 4
    udp = 14 + ihl
    dport = struct.unpack("!H", frame[udp + 2:udp + 4])[0]
    if dport != 5500:
        continue
    payload = frame[udp + 8:]
    if payload[:2] != b"\x11\x11":                           # nexmon CSI magic
        continue
    try:
        tx.sendto(payload, dest)
        n += 1
    except OSError:
        errs += 1                                            # cable unplugged etc.
    if time.time() - t0 >= 5:
        dt = time.time() - t0
        extra = f"  ({errs} send errors - is the Ethernet cable in?)" if errs else ""
        print(f"[gloog] {n / dt:.0f} CSI pkt/s{extra}", flush=True)
        n, errs, t0 = 0, 0, time.time()
