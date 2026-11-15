#!/bin/bash
# Gloog - start Nexmon CSI capture on the Pi 3B+ and forward it to the laptop.
# Run after EVERY boot:
#   sudo ./start_csi.sh                                   (uses gloog.conf)
#   sudo ./start_csi.sh <channel/bw> <router_bssid> [laptop_ip|broadcast]
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

CHBW=""; ROUTER_MAC=""; LAPTOP_IP="broadcast"
if [ -f "$DIR/gloog.conf" ]; then
  # shellcheck disable=SC1091
  source "$DIR/gloog.conf"
fi
[ $# -ge 1 ] && CHBW="$1"
[ $# -ge 2 ] && ROUTER_MAC="$2"
[ $# -ge 3 ] && LAPTOP_IP="$3"

if [ -z "$CHBW" ] || [ -z "$ROUTER_MAC" ]; then
  echo "usage: sudo ./start_csi.sh <channel/bw> <router_bssid> [laptop_ip|broadcast]"
  echo "   or: set CHBW and ROUTER_MAC in gloog.conf and run: sudo ./start_csi.sh"
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo"; exit 1
fi

PARAMS=$(mcp -C 1 -N 1 -c "$CHBW" -m "$ROUTER_MAC")
echo "[gloog] channel=$CHBW router=$ROUTER_MAC target=$LAPTOP_IP"
echo "[gloog] csi params: $PARAMS"

ip link set wlan0 up
nexutil -Iwlan0 -s500 -b -l34 -v"$PARAMS"
iw dev wlan0 interface add mon0 type monitor 2>/dev/null || true
ip link set mon0 up

echo "[gloog] capturing on wlan0 -> forwarding to $LAPTOP_IP:5501 (Ctrl+C to stop)"
exec python3 "$DIR/forward_csi.py" "$LAPTOP_IP" 5501
