"""Bluetooth vs USB bench for the DRO tap board (firmware v2 streams both).

Run on the Pi with the app stopped:

    kivy_venv/bin/python tests/ble_bench.py [seconds] [--usb /dev/ttyACM0]

Reports, for BLE: connect time, round-trip ping stats, notification
inter-arrival histogram, dropped frames, and (if --usb) the lag of each
BLE frame behind the same sequence number seen on USB.
"""
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dro_ble import DroBle                     # noqa: E402
from dro_serial import DroSerial               # noqa: E402

seconds = 60
usb_port = None
args = sys.argv[1:]
if args and args[0].isdigit():
    seconds = int(args[0])
if '--usb' in args:
    usb_port = args[args.index('--usb') + 1]


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(len(vals) * p))]


ble = DroBle()
ble.start()
t0 = time.monotonic()
while not ble.connected and time.monotonic() - t0 < 30:
    time.sleep(0.1)
if not ble.connected:
    print('BLE: no connection within 30 s (found: %s)' % ble.found)
    sys.exit(1)
print('BLE connected in %.1f s to %s (%s dBm)' % (time.monotonic() - t0, ble.device_name, ble.rssi))
time.sleep(1.0)

usb = None
usb_seen = {}
if usb_port:
    usb = DroSerial(usb_port)
    usb.start()

# ---- round trip ----
rtts = ble.ping(30, gap=0.1)
good = [r * 1000 for r in rtts if r is not None]
print('PING: %d/%d answered, min %.1f  median %.1f  p90 %.1f  max %.1f ms' % (
    len(good), len(rtts), min(good), statistics.median(good), pct(good, 0.9), max(good))
      if good else 'PING: no replies')

# ---- stream ----
ble.intervals.clear()
ble.dropped = 0
lags = []
f0 = ble.frames
last_ble_seq = None
deadline = time.monotonic() + seconds
print('streaming %d s ...' % seconds)
while time.monotonic() < deadline:
    if usb is not None:
        s = usb.latest()
        if s is not None:
            usb_seen.setdefault(s['s'], time.monotonic())
    b = ble.latest()
    if b is not None and b['s'] != last_ble_seq:
        last_ble_seq = b['s']
        t_usb = usb_seen.get(b['s'])
        if t_usb is not None:
            lags.append((time.monotonic() - t_usb) * 1000)
    time.sleep(0.005)

iv = [v * 1000 for v in ble.intervals]
frames = ble.frames - f0
print('BLE frames: %d in %d s (%.1f Hz), dropped %d, connected=%s' % (
    frames, seconds, frames / float(seconds), ble.dropped, ble.connected))
if iv:
    print('inter-arrival ms: min %.1f  median %.1f  p90 %.1f  p99 %.1f  max %.1f' % (
        min(iv), statistics.median(iv), pct(iv, 0.9), pct(iv, 0.99), max(iv)))
    buckets = [(0, 40), (40, 60), (60, 100), (100, 200), (200, 1e9)]
    for lo, hi in buckets:
        n = sum(1 for v in iv if lo <= v < hi)
        print('  %4d-%-4s ms: %5d  %s' % (lo, ('%d' % hi) if hi < 1e9 else '', n, '#' * (60 * n // max(1, len(iv)))))
if lags:
    print('BLE behind USB (same frame): median %.1f  p90 %.1f  max %.1f ms  (n=%d)' % (
        statistics.median(lags), pct(lags, 0.9), max(lags), len(lags)))
ble.stop()
if usb is not None:
    usb.stop()
