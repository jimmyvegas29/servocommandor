"""Servocom lathe machine node - firmware v3 (Pico 2 W).

One box at the lathe does the real-time work and talks to the panel over
Bluetooth LE (USB serial mirrors everything for bench work):

  * counts both Sino glass scales (PIO X4 decoder, hard IRQ)
  * polls the XP200 drive over RS-485 (MAX485 on UART0, DE/RE on GP4):
    one bulk read of input registers 0x0009..0x001B every 100 ms
    -> torque %, alarm code, speed in 0.1 rpm
  * reads the FWD / OFF / REV switch on GP10 / GP11 (internal pull-ups)
  * executes drive commands from the panel (enable, disable, speed, clear
    alarm) - ONLY when CONTROL_ALLOWED is True; the read-only build never
    writes a single register, so nothing can move

BLE service 5e7a0001-... :
  DATA  notify  '<IiiIhhHB'  seq, x, z, t_ms, rpm_0p1, torque, alarm, flags
                flags: b0 drive online, b1 switch FWD, b2 switch REV,
                       b3 enabled (as this node last commanded),
                       b4 control allowed, b5 last command ok
  CMD   write   b'E' enable, b'D' disable, b'C' clear alarm,
                b'S' + int16 LE signed speed (drive units, +/-3000)
  PING  write/notify echo, for round-trip timing

Pins: X A/B = GP6/GP7, Z A/B = GP2/GP3, MAX485 DI = GP0, RO = GP1,
DE+RE = GP4, switch COM = GND (pin 13), lever FWD contact on GP11 (pin 15), REV on GP10 (pin 14).
"""
import struct
import time
import asyncio
import bluetooth
import aioble
from machine import Pin, UART, WDT, unique_id
from encoder_rp2 import Encoder

# ---------------------------------------------------------------- config
CONTROL_ALLOWED = False      # read-only until the control path is signed off
INVERT_DIRECTION = True      # same as servo.ini [Hardware] invert_direction
SLAVE_ID = 1
BAUD = 9600
POLL_MS = 100                # drive poll
PERIOD_MS = 50               # BLE / USB packet cadence (20 Hz)
ADV_INTERVAL_US = 100_000

X_BASE, Z_BASE = 6, 2
PIN_TX, PIN_RX, PIN_DE = 0, 1, 4
PIN_FWD, PIN_REV = 11, 10     # lever FWD closes the contact on GP11 (verified 2026-09-11)

SERVICE_UUID = bluetooth.UUID('5e7a0001-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
DATA_UUID = bluetooth.UUID('5e7a0002-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
PING_UUID = bluetooth.UUID('5e7a0003-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
CMD_UUID = bluetooth.UUID('5e7a0004-8d2c-4b1e-9c3a-2f6d0a1b3c4d')
NAME = 'SERVOCOM-NODE-' + ''.join('%02X' % b for b in unique_id()[-2:])

# ---------------------------------------------------------------- scales
for gp in (X_BASE, X_BASE + 1, Z_BASE, Z_BASE + 1):
    Pin(gp, Pin.IN, Pin.PULL_UP)
enc_x = Encoder(0, Pin(X_BASE))
enc_z = Encoder(1, Pin(Z_BASE))

# ---------------------------------------------------------------- switch
pin_fwd = Pin(PIN_FWD, Pin.IN, Pin.PULL_UP)
pin_rev = Pin(PIN_REV, Pin.IN, Pin.PULL_UP)


def read_switch():
    fwd = not pin_fwd.value()        # contact to ground = active
    rev = not pin_rev.value()
    if fwd and not rev:
        return 'fwd'
    if rev and not fwd:
        return 'rev'
    return 'neutral'


# ---------------------------------------------------------------- modbus
uart = UART(0, baudrate=BAUD, tx=Pin(PIN_TX), rx=Pin(PIN_RX), bits=8, parity=None, stop=1,
            timeout=0, rxbuf=256)
de = Pin(PIN_DE, Pin.OUT, value=0)


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def modbus_txn(pdu, expect_len, timeout_ms=150):
    """Send slave_id + pdu (+crc), return the response PDU bytes or None."""
    frame = bytes([SLAVE_ID]) + pdu
    frame += struct.pack('<H', crc16(frame))
    while uart.any():
        uart.read()
    de.value(1)
    uart.write(frame)
    uart.flush()
    de.value(0)
    buf = b''
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        chunk = uart.read()
        if chunk:
            buf += chunk
            if len(buf) >= expect_len:
                break
        time.sleep_ms(2)
    if len(buf) < 5 or buf[0] != SLAVE_ID:
        return None
    if struct.unpack('<H', buf[-2:])[0] != crc16(buf[:-2]):
        return None
    if buf[1] & 0x80:                       # exception response
        return None
    return buf[1:-2]


def read_input_regs(addr, count):
    pdu = struct.pack('>BHH', 0x04, addr, count)
    resp = modbus_txn(pdu, 5 + 2 * count)
    if resp is None or resp[0] != 0x04 or resp[1] != 2 * count:
        return None
    return struct.unpack('>%dH' % count, resp[2:2 + 2 * count])


def write_reg(addr, value):
    if not CONTROL_ALLOWED:
        return False
    pdu = struct.pack('>BHH', 0x06, addr, value & 0xFFFF)
    resp = modbus_txn(pdu, 8)
    return resp is not None


def clear_alarm():
    if not CONTROL_ALLOWED:
        return False
    resp = modbus_txn(bytes([0x43]), 4)
    return resp is not None


# ---------------------------------------------------------------- state
state = {'online': False, 'rpm': 0, 'torque': 0, 'alarm': 0,
         'switch': 'neutral', 'enabled': False, 'cmd_ok': True, 'last_speed': 0}


def apply_speed(speed):
    """Commanded speed (signed, drive units) -> register 0x0089."""
    state['last_speed'] = speed
    wire = -speed if INVERT_DIRECTION else speed
    return write_reg(0x0089, wire)


def handle_cmd(data):
    ok = False
    if data[:1] == b'E':
        ok = write_reg(0x0062, 1)
        state['enabled'] = ok or state['enabled']
    elif data[:1] == b'D':
        ok = write_reg(0x0062, 0)
        if ok:
            state['enabled'] = False
    elif data[:1] == b'C':
        ok = clear_alarm()
    elif data[:1] == b'S' and len(data) >= 3:
        speed = struct.unpack('<h', data[1:3])[0]
        speed = max(-3000, min(3000, speed))
        ok = apply_speed(speed)
    state['cmd_ok'] = ok
    print('CMD', data, 'ok' if ok else 'refused/failed')


async def drive_poller():
    last_online = None
    while True:
        regs = read_input_regs(0x0009, 19)
        if regs is None:
            state['online'] = False
        else:
            state['online'] = True
            state['torque'] = regs[0] - 65536 if regs[0] > 32767 else regs[0]
            state['alarm'] = regs[17]
            state['rpm'] = regs[18] - 65536 if regs[18] > 32767 else regs[18]
        if state['online'] != last_online:
            print('DRIVE', 'online' if state['online'] else 'offline')
            last_online = state['online']
        await asyncio.sleep_ms(POLL_MS)


async def switch_task():
    last = read_switch()
    while True:
        cur = read_switch()
        if cur == last and cur != state['switch']:
            state['switch'] = cur
            print('SWITCH', cur)
            if CONTROL_ALLOWED:
                if cur == 'neutral':
                    if write_reg(0x0062, 0):
                        state['enabled'] = False
                else:
                    mag = abs(state['last_speed'])
                    apply_speed(-mag if cur == 'rev' else mag)
                    if write_reg(0x0062, 1):
                        state['enabled'] = True
        last = cur
        await asyncio.sleep_ms(50)


# ---------------------------------------------------------------- BLE
aioble.config(gap_name=NAME)
svc = aioble.Service(SERVICE_UUID)
data_char = aioble.Characteristic(svc, DATA_UUID, read=True, notify=True)
ping_char = aioble.Characteristic(svc, PING_UUID, write=True, write_no_response=True,
                                  notify=True, capture=True)
cmd_char = aioble.Characteristic(svc, CMD_UUID, write=True, write_no_response=True,
                                 notify=True, capture=True)
aioble.register_services(svc)
led = Pin('LED', Pin.OUT)
seq = 0


def flags():
    f = 0
    if state['online']:
        f |= 1
    if state['switch'] == 'fwd':
        f |= 2
    if state['switch'] == 'rev':
        f |= 4
    if state['enabled']:
        f |= 8
    if CONTROL_ALLOWED:
        f |= 16
    if state['cmd_ok']:
        f |= 32
    return f


async def sampler():
    global seq
    next_t = time.ticks_ms()
    while True:
        seq += 1
        x, z, t = enc_x.value(), enc_z.value(), time.ticks_ms()
        print('DRO X:%d Z:%d S:%d T:%d' % (x, z, seq, t))
        if seq % 4 == 0:
            print('NODE rpm:%d tq:%d al:%d sw:%s on:%d en:%d pins fwd=%d rev=%d' % (
                state['rpm'], state['torque'], state['alarm'], state['switch'],
                state['online'], state['enabled'], pin_fwd.value(), pin_rev.value()))
        try:
            data_char.write(struct.pack('<IiiIhhHB', seq, x, z, t, state['rpm'],
                                        state['torque'], state['alarm'], flags()),
                            send_update=True)
        except Exception:
            pass
        next_t = time.ticks_add(next_t, PERIOD_MS)
        delay = time.ticks_diff(next_t, time.ticks_ms())
        await asyncio.sleep_ms(delay if delay > 0 else 0)
        if delay <= 0:
            next_t = time.ticks_ms()


async def peripheral():
    while True:
        led.off()
        async with await aioble.advertise(ADV_INTERVAL_US, name=NAME,
                                          services=[SERVICE_UUID]) as conn:
            print('BLE connected', conn.device)
            led.on()
            await conn.disconnected(timeout_ms=None)
            print('BLE disconnected')


async def pinger():
    while True:
        conn, data = await ping_char.written()
        try:
            ping_char.write(data, send_update=True)
        except Exception:
            pass


async def commander():
    while True:
        conn, data = await cmd_char.written()
        handle_cmd(bytes(data))
        try:
            cmd_char.write(bytes([1 if state['cmd_ok'] else 0]) + bytes(data[:1]), send_update=True)
        except Exception:
            pass


async def watchdog():
    wdt = WDT(timeout=8000)
    while True:
        wdt.feed()
        await asyncio.sleep_ms(1000)


async def main():
    print('machine node firmware v3 as', NAME, '| control', 'ALLOWED' if CONTROL_ALLOWED else 'READ-ONLY')
    await asyncio.gather(sampler(), peripheral(), pinger(), commander(),
                         drive_poller(), switch_task(), watchdog())


asyncio.run(main())
