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
  * safeguards: drive is disabled when it first appears, when the BLE link
    drops, and whenever the switch goes to OFF; the switch cannot start the
    spindle until it has been seen in OFF once (boot / after a link loss)

BLE service 5e7a0001-... :
  DATA  notify  '<IiiIhhHBH' seq, x, z, t_ms, rpm_0p1, torque, alarm, flags,
                avg_load (0x0018 average load ratio %, the drive's motor
                heating model)
                flags: b0 drive online, b1 switch FWD, b2 switch REV,
                       b3 enabled (as this node last commanded),
                       b4 control allowed, b5 last command ok
  CMD   write   b'E' enable, b'D' disable, b'C' clear alarm,
                b'S' + int16 LE signed speed (drive units, +/-3000)
                b'R' + uint16 LE addr + uint8 count: read drive parameters
                      (03H), answered on the CMD notify as
                      ok, b'R', addr, count, count x uint16 LE
                b'W' + uint16 LE addr + int16 LE value: write one parameter
                      (06H); only the PARAM_WRITABLE set, only while disabled
                b'V' save parameters to EEPROM (41H); the drive poll pauses
                      for 5 s afterwards while the drive is busy
                b'I' info: ack payload is the firmware VERSION string
                b'F' + uint32 LE size + uint32 LE crc32: begin a firmware
                      update (the new node.py), b'f' + bytes: append a chunk,
                      b'G' finish: verify, stage as node_new.py and reset;
                      main.py (the launcher, never updated over the air)
                      swaps it in and rolls back if it does not confirm
        every command is acknowledged on the CMD notify: ok byte, cmd byte,
        then any payload

First-connect lock: the first panel that connects is remembered in
panel.lock and any other central is dropped at once.  To forget the panel,
power the node on with the lever in REV.
  PING  write/notify echo, for round-trip timing

Pins: X A/B = GP6/GP7, Z A/B = GP2/GP3, MAX485 DI = GP0, RO = GP1,
DE+RE = GP4, switch COM = GND (pin 13), lever FWD on GP10 (pin 14), REV on GP11 (pin 15).
"""
import os
import struct
import time
import binascii
import asyncio
import bluetooth
import aioble
from machine import Pin, UART, WDT, unique_id, reset
from encoder_rp2 import Encoder

# ---------------------------------------------------------------- config
VERSION = 'node 3.9'         # shown on the panel; bump on every change
CONTROL_ALLOWED = True       # control path signed off with Jimmy at the lathe 2026-09-11
LOCK_FILE = 'panel.lock'
TRIAL_FLAG = 'trial.flag'    # set by the launcher on the first boot of a new image
OTA_TMP = 'node_new.tmp'
OTA_NEW = 'node_new.py'
INVERT_DIRECTION = True      # same as servo.ini [Hardware] invert_direction
SLAVE_ID = 1
BAUD = 9600
POLL_MS = 100                # drive poll
PERIOD_MS = 50               # BLE / USB packet cadence (20 Hz)
ADV_INTERVAL_US = 100_000

X_BASE, Z_BASE = 6, 2
PIN_TX, PIN_RX, PIN_DE = 0, 1, 4
PIN_FWD, PIN_REV = 10, 11     # switch wired so lever FWD grounds GP10 (rewired by Jimmy 2026-09-11)

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


def file_exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def read_lock():
    try:
        with open(LOCK_FILE) as fh:
            return fh.read().strip()
    except OSError:
        return None


# lever held in REV at power-on: forget the locked panel
if not pin_rev.value() and pin_fwd.value() and file_exists(LOCK_FILE):
    os.remove(LOCK_FILE)
    print('LOCK cleared (lever in REV at boot)')


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
    if len(buf) < 4 or buf[0] != SLAVE_ID:      # 41H / 43H answer with 4 bytes
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


# drive parameters the panel may change (Pr number == Modbus address)
PARAM_WRITABLE = (60, 61, 63, 65, 66, 67, 68, 69, 70, 71, 72, 75)
SAVE_BUSY_MS = 5000          # manual: wait 5 s after 41H


def read_holding_regs(addr, count):
    pdu = struct.pack('>BHH', 0x03, addr, count)
    resp = modbus_txn(pdu, 5 + 2 * count)
    if resp is None or resp[0] != 0x03 or resp[1] != 2 * count:
        return None
    return struct.unpack('>%dH' % count, resp[2:2 + 2 * count])


def save_params():
    """41H: write the parameter table to EEPROM."""
    if not CONTROL_ALLOWED:
        return False
    resp = modbus_txn(bytes([0x41]), 4, timeout_ms=400)
    return resp is not None


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
state = {'online': False, 'rpm': 0, 'torque': 0, 'alarm': 0, 'avg_load': 0,
         'switch': 'neutral', 'enabled': False, 'cmd_ok': True, 'last_speed': 0,
         'armed': False,          # switch interlock: must pass through neutral first
         'save_until': None,      # ticks_ms until which the drive is busy saving
         'linked': False,         # a panel is connected over BLE
         'boot_disable': False,   # drive was told 'disable' once after coming online
         'poll_errors': 0}        # failed drive polls since boot (RS-485 noise indicator)


def safe_disable(why, zero_speed=False):
    """Best effort disable, used by every safeguard.  zero_speed also clears
    the drive's speed setpoint (0x0089) so a stale value left in the drive
    can never make the next enable spin the spindle."""
    ok = write_reg(0x0062, 0)
    if ok:
        state['enabled'] = False
    if zero_speed:
        state['last_speed'] = 0
        ok = write_reg(0x0089, 0) and ok
    print('SAFE disable (%s)%s:' % (why, ' + speed 0' if zero_speed else ''), 'ok' if ok else 'FAILED')
    return ok


def apply_speed(speed):
    """Commanded speed (signed, drive units) -> register 0x0089."""
    state['last_speed'] = speed
    wire = -speed if INVERT_DIRECTION else speed
    return write_reg(0x0089, wire)


ota = {'fh': None, 'size': 0, 'crc': 0, 'got': 0, 'reset_at': None}


def ota_abort():
    if ota['fh'] is not None:
        try:
            ota['fh'].close()
        except Exception:
            pass
        ota['fh'] = None
    if file_exists(OTA_TMP):
        os.remove(OTA_TMP)


def handle_cmd(data):
    """Execute one panel command; returns the ack payload."""
    ok = False
    payload = b''
    if data[:1] == b'I':
        ok = True
        payload = VERSION.encode()
    elif data[:1] == b'L':
        # crash log: b'L' + offset byte -> up to 18 bytes of crash.txt
        off = data[1] if len(data) > 1 else 0
        try:
            with open('crash.txt') as fh:
                fh.seek(off * 18)
                payload = fh.read(18).encode()
            ok = True
        except OSError:
            payload = b''
            ok = False
    elif data[:1] == b'K':
        try:
            os.remove('crash.txt')
        except OSError:
            pass
        ok = True
    elif data[:1] == b'F' and len(data) >= 9:
        ota_abort()
        ota['size'], ota['crc'] = struct.unpack('<II', data[1:9])
        ota['got'] = 0
        try:
            ota['fh'] = open(OTA_TMP, 'wb')
            ok = True
        except OSError as exc:
            print('OTA open failed', exc)
        print('OTA begin', ota['size'], 'bytes')
    elif data[:1] == b'f':
        if ota['fh'] is not None:
            ota['fh'].write(data[1:])
            ota['got'] += len(data) - 1
            ok = True
        payload = struct.pack('<I', ota['got'])
    elif data[:1] == b'G':
        if ota['fh'] is not None:
            ota['fh'].close()
            ota['fh'] = None
            crc = 0
            with open(OTA_TMP, 'rb') as fh:
                while True:
                    chunk = fh.read(512)
                    if not chunk:
                        break
                    crc = binascii.crc32(chunk, crc)
            ok = ota['got'] == ota['size'] and (crc & 0xFFFFFFFF) == ota['crc']
            if ok and not state['enabled']:
                os.rename(OTA_TMP, OTA_NEW)
                ota['reset_at'] = time.ticks_add(time.ticks_ms(), 1500)
                print('OTA verified, resetting to install')
            else:
                print('OTA rejected: got %d/%d crc %08x/%08x enabled=%s' % (
                    ota['got'], ota['size'], crc & 0xFFFFFFFF, ota['crc'], state['enabled']))
                ok = False
                ota_abort()
        payload = struct.pack('<I', ota['got'])
    elif data[:1] == b'X' and len(data) >= 2:
        # diagnostics: raw Modbus PDU passthrough (function byte + data), only
        # while the drive is disabled and never for the enable / speed
        # registers.  Ack payload = the raw response PDU (or empty).
        pdu = data[1:]
        fn = pdu[0]
        target = struct.unpack('>H', pdu[1:3])[0] if len(pdu) >= 3 else None
        if state['enabled']:
            print('CMD X refused: drive enabled')
        elif fn in (0x06, 0x10) and target in (0x0062, 0x0089):
            print('CMD X refused: enable/speed register')
        else:
            resp = modbus_txn(pdu, 4, timeout_ms=600)
            ok = resp is not None
            payload = bytes(resp) if ok else b''
            print('CMD X', pdu, '->', resp)
    elif data[:1] == b'R' and len(data) >= 4:
        addr, count = struct.unpack('<HB', data[1:4])
        count = max(1, min(8, count))
        vals = read_holding_regs(addr, count) if addr + count <= 250 else None
        ok = vals is not None
        payload = struct.pack('<HB', addr, count)
        if ok:
            payload += struct.pack('<%dH' % count, *vals)
    elif data[:1] == b'W' and len(data) >= 5:
        addr, value = struct.unpack('<Hh', data[1:5])
        payload = struct.pack('<Hh', addr, value)
        if addr not in PARAM_WRITABLE:
            print('CMD W refused: Pr%03d not writable from the panel' % addr)
        elif state['enabled']:
            print('CMD W refused: drive enabled')
        else:
            ok = write_reg(addr, value)
    elif data[:1] == b'V':
        if state['enabled']:
            print('CMD V refused: drive enabled')
        else:
            ok = save_params()
            if ok:
                state['save_until'] = time.ticks_add(time.ticks_ms(), SAVE_BUSY_MS)
    elif data[:1] == b'E':
        # the setpoint is re-written first so the drive can only ever enable
        # at the speed the panel last asked for
        ok = apply_speed(state['last_speed']) and write_reg(0x0062, 1)
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
    print('CMD', data[:1], 'ok' if ok else 'refused/failed')
    return payload


OFFLINE_AFTER = 5            # consecutive failed polls (x POLL_MS) before 'offline'
REAPPEAR_MS = 2000           # offline at least this long => treat as a drive power cycle


async def drive_poller():
    last_online = None
    fails = 0
    offline_since = None
    while True:
        if state['save_until'] is not None:
            if time.ticks_diff(state['save_until'], time.ticks_ms()) > 0:
                await asyncio.sleep_ms(POLL_MS)      # drive busy writing EEPROM
                continue
            state['save_until'] = None
        regs = read_input_regs(0x0009, 19)
        if regs is None:
            regs = read_input_regs(0x0009, 19)     # one immediate retry (noise)
        if regs is None:
            fails += 1
            state['poll_errors'] += 1
            if fails == OFFLINE_AFTER and state['online']:
                state['online'] = False
                offline_since = time.ticks_ms()
        else:
            fails = 0
            if not state['online']:
                state['online'] = True
                gone_ms = time.ticks_diff(time.ticks_ms(), offline_since) if offline_since else 0
                if not state['boot_disable'] or gone_ms >= REAPPEAR_MS:
                    # first sight at boot, or the drive was really away (power
                    # cycle): make sure it starts disabled with setpoint 0.
                    # A short RS-485 dropout must NOT stop a cut.
                    state['boot_disable'] = safe_disable('drive online', zero_speed=True)
            state['torque'] = regs[0] - 65536 if regs[0] > 32767 else regs[0]
            state['avg_load'] = regs[15]          # 0x0018 average load ratio %
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
                    safe_disable('switch neutral')
                    if not state['armed']:
                        state['armed'] = True
                        print('SWITCH interlock armed')
                elif not state['armed']:
                    print('SWITCH ignored, interlock not armed (go through OFF first)')
                else:
                    mag = abs(state['last_speed'])
                    apply_speed(-mag if cur == 'rev' else mag)
                    if write_reg(0x0062, 1):
                        state['enabled'] = True
        elif cur == last and cur == 'neutral' and not state['armed']:
            state['armed'] = True
            print('SWITCH interlock armed')
        last = cur
        await asyncio.sleep_ms(50)


# ---------------------------------------------------------------- BLE
aioble.config(gap_name=NAME)
try:
    bluetooth.BLE().config(mtu=250)      # let the panel use ~240-byte writes for updates
except Exception as exc:
    print('MTU config not accepted:', exc)
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
            print('NODE rpm:%d tq:%d al:%d sw:%s on:%d en:%d pe:%d pins fwd=%d rev=%d' % (
                state['rpm'], state['torque'], state['alarm'], state['switch'],
                state['online'], state['enabled'], state['poll_errors'],
                pin_fwd.value(), pin_rev.value()))
        try:
            data_char.write(struct.pack('<IiiIhhHBH', seq, x, z, t, state['rpm'],
                                        state['torque'], state['alarm'], flags(),
                                        state['avg_load'] & 0xFFFF),
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
            addr = ':'.join('%02X' % b for b in conn.device.addr)
            lock = read_lock()
            if lock is None:
                with open(LOCK_FILE, 'w') as fh:
                    fh.write(addr)
                print('LOCK set to first panel', addr)
            elif lock != addr:
                print('LOCK refused', addr, '(panel is', lock + ')')
                await conn.disconnect()
                continue
            print('BLE connected', conn.device)
            led.on()
            state['linked'] = True
            await conn.disconnected(timeout_ms=None)
            print('BLE disconnected')
            state['linked'] = False
            # panel gone: stop the spindle and make the switch pass through
            # OFF before it can start anything again
            safe_disable('link lost', zero_speed=True)
            state['armed'] = False


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
        payload = handle_cmd(bytes(data))
        try:
            cmd_char.write(bytes([1 if state['cmd_ok'] else 0]) + bytes(data[:1]) + payload,
                           send_update=True)
        except Exception:
            pass


async def watchdog():
    wdt = WDT(timeout=8000)
    while True:
        wdt.feed()
        if ota['reset_at'] is not None and time.ticks_diff(ota['reset_at'], time.ticks_ms()) <= 0:
            print('OTA reset')
            time.sleep_ms(100)
            reset()
        await asyncio.sleep_ms(1000)


async def trial_confirm():
    """First boot of a freshly installed image: once it has run 30 s and
    has the drive polled and a panel linked, tell the launcher it is good.
    Keeps checking, so a panel that links later still confirms it."""
    if not file_exists(TRIAL_FLAG):
        return
    await asyncio.sleep_ms(30000)
    while not (state['online'] and state['linked']):
        await asyncio.sleep_ms(2000)
    os.remove(TRIAL_FLAG)
    print('TRIAL confirmed', VERSION)


async def main():
    print('machine node firmware', VERSION, 'as', NAME, '| control',
          'ALLOWED' if CONTROL_ALLOWED else 'READ-ONLY', '| panel lock', read_lock() or 'open')
    await asyncio.gather(sampler(), peripheral(), pinger(), commander(),
                         drive_poller(), switch_task(), watchdog(), trial_confirm())


try:
    asyncio.run(main())
except Exception as exc:
    # leave a note the panel can fetch with the L command, then let the
    # launcher reset us
    try:
        import sys
        with open('crash.txt', 'w') as fh:
            fh.write(VERSION + ' ' + str(time.ticks_ms()) + chr(10))
            sys.print_exception(exc, fh)
    except Exception:
        pass
    raise
