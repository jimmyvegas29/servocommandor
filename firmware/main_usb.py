"""Servocom lathe DRO tap firmware (RP2350-Plus, no display).

Counts both Sino glass scales with the PIO X4 decoder and streams the raw
counts over USB serial 20 times a second:

    DRO X:<counts> Z:<counts> S:<seq> T:<ms>

1 count = 1 um (validated against the Sino console).  Zeroing, datums and
units all live in the app; this board only ever reports raw counts, so a
lost line never loses position.

Pins as built 2026-09-08:
    X scale  A = GP6, B = GP7, 0V on header pin 8
    Z scale  A = GP2, B = GP3, 0V on header pin 3
    scale +5V from VBUS (header 40)
"""
import time
from machine import Pin
from encoder_rp2 import Encoder

X_BASE = 6      # GP6 = A, GP7 = B
Z_BASE = 2      # GP2 = A, GP3 = B
PERIOD_MS = 50  # 20 Hz

for gp in (X_BASE, X_BASE + 1, Z_BASE, Z_BASE + 1):
    Pin(gp, Pin.IN, Pin.PULL_UP)

enc_x = Encoder(0, Pin(X_BASE))
enc_z = Encoder(1, Pin(Z_BASE))

seq = 0
print('DRO tap firmware v1 (X=GP6/7, Z=GP2/3)')
next_t = time.ticks_ms()
while True:
    seq += 1
    now = time.ticks_ms()
    print('DRO X:%d Z:%d S:%d T:%d' % (enc_x.value(), enc_z.value(), seq, now))
    next_t = time.ticks_add(next_t, PERIOD_MS)
    delay = time.ticks_diff(next_t, time.ticks_ms())
    if delay > 0:
        time.sleep_ms(delay)
    else:
        next_t = time.ticks_ms()
