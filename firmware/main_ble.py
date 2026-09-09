"""Servocom lathe DRO tap firmware v2 - Pico 2 W, USB serial + Bluetooth LE.

Counts both Sino glass scales with the PIO X4 decoder and publishes the raw
counts 20 times a second on BOTH links at once, so the two can be compared
on identical data:

  USB serial:  DRO X:<counts> Z:<counts> S:<seq> T:<ms>
  BLE notify:  struct '<IiiI'  seq, x, z, t_ms   on the DATA characteristic

A PING characteristic echoes whatever is written to it, for round-trip
timing from the Pi.

Pins (same as v1):  X A/B = GP6/GP7,  Z A/B = GP2/GP3,  scale 5V from VBUS.
"""
import struct
import time
import asyncio
import bluetooth
import aioble
from machine import Pin, unique_id
from encoder_rp2 import Encoder

X_BASE = 6
Z_BASE = 2
PERIOD_MS = 50           # 20 Hz
ADV_INTERVAL_US = 100_000

SERVICE_UUID = bluetooth.UUID('5e7a0001-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
DATA_UUID = bluetooth.UUID('5e7a0002-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
PING_UUID = bluetooth.UUID('5e7a0003-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
NAME = 'SERVOCOM-DRO-' + ''.join('%02X' % b for b in unique_id()[-2:])

for gp in (X_BASE, X_BASE + 1, Z_BASE, Z_BASE + 1):
    Pin(gp, Pin.IN, Pin.PULL_UP)
enc_x = Encoder(0, Pin(X_BASE))
enc_z = Encoder(1, Pin(Z_BASE))

aioble.config(gap_name=NAME)
svc = aioble.Service(SERVICE_UUID)
data_char = aioble.Characteristic(svc, DATA_UUID, read=True, notify=True)
ping_char = aioble.Characteristic(svc, PING_UUID, write=True, write_no_response=True,
                                  notify=True, capture=True)
aioble.register_services(svc)

seq = 0
led = Pin('LED', Pin.OUT)


def sample():
    global seq
    seq += 1
    return seq, enc_x.value(), enc_z.value(), time.ticks_ms()


async def sampler():
    """Print on USB and notify over BLE at a fixed 20 Hz cadence."""
    next_t = time.ticks_ms()
    while True:
        s, x, z, t = sample()
        print('DRO X:%d Z:%d S:%d T:%d' % (x, z, s, t))
        try:
            data_char.write(struct.pack('<IiiI', s, x, z, t), send_update=True)
        except Exception:
            pass
        next_t = time.ticks_add(next_t, PERIOD_MS)
        delay = time.ticks_diff(next_t, time.ticks_ms())
        await asyncio.sleep_ms(delay if delay > 0 else 0)
        if delay <= 0:
            next_t = time.ticks_ms()


async def peripheral():
    """Advertise whenever not connected; the Pi (central) does the connecting."""
    while True:
        led.off()
        async with await aioble.advertise(ADV_INTERVAL_US, name=NAME,
                                          services=[SERVICE_UUID]) as conn:
            print('BLE connected', conn.device)
            led.on()
            await conn.disconnected(timeout_ms=None)
            print('BLE disconnected')


async def pinger():
    """Echo every write to PING back as a notification (round-trip timing)."""
    while True:
        conn, data = await ping_char.written()
        try:
            ping_char.write(data, send_update=True)
        except Exception:
            pass


async def main():
    print('DRO tap firmware v2 (USB + BLE) as', NAME)
    await asyncio.gather(sampler(), peripheral(), pinger())


asyncio.run(main())
