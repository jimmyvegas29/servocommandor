"""Servocom lathe machine node - firmware v3 (Pico 2 W).

One box at the lathe does the real-time work and talks to the panel over
Bluetooth LE (USB serial mirrors everything for bench work):

  * counts both Sino glass scales (X4 decoder entirely in the PIO)
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
  DATA  notify  '<IiiIhhHBHBBii' seq, x, z, t_ms, rpm_0p1, torque, alarm, flags,
                avg_load (0x0018 average load ratio %, the drive's motor
                heating model), then the tap cycle: state (0 idle, 1 in,
                2 out, 3 done, 4 halted), reason (TapCycle.R_*), counts
                (motor encoder counts in from the origin), peak (deepest
                point of the last in-leg)
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
                b'J' + int16 LE signed motor rpm: jog keep-alive.  Runs the
                      drive at that speed while these keep arriving (the
                      panel sends one every 200 ms); the node stops the
                      drive by itself 600 ms after the last one.  Refused
                      while the lever is not OFF or the drive is enabled
                      for any other reason.  b'j' stops a jog at once.
                b'T' + '<hHIIHB' tap pass: signed motor rpm going in, torque
                      cap %, target counts, back-out margin counts, stall
                      ms, flags (b0 keep the origin of the last pass).
                      Refused unless the lever is OFF, the drive is online
                      and disabled.  b't' stops a pass (drive off, tap left
                      where it is); b'U' backs a stopped tap out.  While a
                      pass runs every other command except D (= stop) is
                      refused, and the normal drive poll pauses: the pass
                      reads position and torque as fast as the bus allows.
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
import rp2

# ---------------------------------------------------------------- config
VERSION = 'node 3.15'         # shown on the panel; bump on every change
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

# the watchdog starts before anything that could block, so a hang anywhere
# (including PIO setup) always ends in a reset and the launcher's rollback
wdt = WDT(timeout=8000)

# ---------------------------------------------------------------- scales
# X4 quadrature decoder that lives entirely in the PIO (port of
# pico-examples quadrature_encoder).  The old encoder_rp2 counted in a
# Python IRQ behind a 4-deep FIFO; anything that held interrupts off (BLE,
# UART) made it miss edges, and a missed quadrature edge decodes as motion
# the wrong way, so the count walked whenever the spindle shook the scale.


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT, out_shiftdir=rp2.PIO.SHIFT_RIGHT)
def _quadrature():
    # 16-entry jump table, index = old_state << 2 | new_state
    jmp("update")        # 00 -> 00
    jmp("decrement")     # 00 -> 01
    jmp("increment")     # 00 -> 10
    jmp("update")        # 00 -> 11 (invalid, both changed)
    jmp("increment")     # 01 -> 00
    jmp("update")        # 01 -> 01
    jmp("update")        # 01 -> 10 (invalid)
    jmp("decrement")     # 01 -> 11
    jmp("decrement")     # 10 -> 00
    jmp("update")        # 10 -> 01 (invalid)
    jmp("update")        # 10 -> 10
    jmp("increment")     # 10 -> 11
    jmp("update")        # 11 -> 00 (invalid)
    jmp("increment")     # 11 -> 01
    jmp("decrement")     # 11 -> 10
    jmp("update")        # 11 -> 11
    label("decrement")
    jmp(y_dec, "update")  # y -= 1 (jmp y-- always falls to update)
    wrap_target()
    label("update")
    mov(isr, y)
    push(noblock)
    out(isr, 2)          # previous 2 pin bits (low bits of OSR) -> ISR
    in_(pins, 2)         # current 2 pin bits appended -> 4-bit table index
    mov(osr, isr)        # remember for next loop
    mov(pc, isr)         # jump into the table
    label("increment")
    mov(y, invert(y))
    jmp(y_dec, "increment_cont")
    label("increment_cont")
    mov(y, invert(y))    # y = ~(~y - 1) = y + 1
    wrap()
    # padding to 32 instructions so the program is loaded at address 0
    nop()
    nop()
    nop()
    nop()
    nop()
    nop()


class Encoder:
    """Drop-in for encoder_rp2.Encoder: Encoder(sm_no, base_pin).value()."""

    def __init__(self, sm_no, base_pin, scale=1):
        self.scale = scale
        self._offset = 0
        self._last = 0
        self.stalled = 0
        self.sm = rp2.StateMachine(sm_no, _quadrature, in_base=base_pin)
        # y = 0, OSR = current pins so the first loop sees "no change"
        self.sm.exec("set(y, 0)")
        self.sm.exec("in_(pins, 2)")
        self.sm.exec("mov(osr, isr)")
        self.sm.exec("mov(isr, null)")
        self.sm.active(1)

    def _raw(self):
        sm = self.sm
        # the state machine refills the 4-deep FIFO every ~100 ns, so the
        # oldest queued value is well under a microsecond old: take it.  Never
        # drain "until empty" (it never empties) and never block (a stalled
        # state machine must not hang the node).
        if not sm.rx_fifo():
            self.stalled += 1
            return self._last
        v = sm.get()
        v = v - 0x100000000 if v & 0x80000000 else v
        self._last = -v
        # the table counts A-leading as negative; the old decoder (and so the
        # panel's saved datums and direction settings) had it positive
        return -v

    def value(self, value=None):
        if value is not None:
            self._offset = value - self._raw()
        return self._raw() + self._offset

    def position(self, value=None):
        if value is not None:
            self.value(round(value / self.scale))
        return self.value() * self.scale


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
         'jogging': False,        # hold-to-jog in progress
         'jog_until': None,       # ticks_ms deadline for the next jog keep-alive
         'linked': False,         # a panel is connected over BLE
         'boot_disable': False,   # drive was told 'disable' once after coming online
         'poll_errors': 0,        # failed drive polls since boot (RS-485 noise indicator)
         'conn': None,            # the panel's connection, for DATA notifies
         'notify_fail': 0}        # DATA notifies the BLE stack refused since boot


def safe_disable(why, zero_speed=False):
    """Best effort disable, used by every safeguard.  zero_speed also clears
    the drive's speed setpoint (0x0089) so a stale value left in the drive
    can never make the next enable spin the spindle."""
    ok = write_reg(0x0062, 0)
    if ok:
        state['enabled'] = False
    state['jogging'] = False
    state['jog_until'] = None
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


# ---------------------------------------------------------------- tapping
TAP_MAX_RPM = 1000           # motor rpm, hard cap for a tap pass
TAP_TLIM_MAX = 150           # %, hard cap for the tap torque limit


class TapCycle:
    """One tapping pass, run on the node so its timing and its safety do not
    depend on the Bluetooth link.

    IN: the drive runs at the tapping speed with its torque capped by
    Pr065/066 (the drive enforces that cap itself, instantly).  The pass
    goes until the target depth (in motor encoder counts from the origin)
    or until the spindle stops advancing for stall_ms (the tap bottomed or
    jammed at the cap).  OUT: it reverses until it is margin counts back
    past the origin, then disables.  A stall on the way out (tap jammed)
    halts with the drive disabled.  Every exit path disables the drive,
    puts the torque limit back to what it was and restores the panel's
    speed setpoint.

    Position: input registers 0x0005/0x0006 hold the 32-bit motor position.
    Only the low word is used, unwrapped from sample to sample (a sample
    never moves anywhere near 32768 counts); which of the two registers is
    the low word is found from the motion itself.  The direction that
    counts as "in" is taken from the first real motion of a pass.

    io must provide: read_block() -> (reg5, reg6, torque) or None,
    read_alarm() -> int or None, read_limits() -> (pr65, pr66) or None,
    write(addr, value) -> bool, set_speed(signed) -> bool,
    set_enabled(bool) -> bool, restore_speed(), now_ms(), log(*args)."""

    IDLE, IN, OUT, DONE, HALTED = 0, 1, 2, 3, 4
    # why a pass ended
    R_NONE, R_DEPTH, R_STALL, R_PANEL, R_LINK, R_LEVER, R_DRIVE, R_COMM, R_JAM, R_OUT = range(10)
    SPINUP_MS = 400          # no stall check while the spindle comes up to speed
    MOVE_COUNTS = 60         # less than this in stall_ms counts as not moving
    SIGN_COUNTS = 100        # motion needed to learn which way is "in"
    FAIL_MAX = 5             # consecutive failed reads before giving up
    ALARM_EVERY_MS = 500

    def __init__(self, io):
        self.io = io
        self.state = self.IDLE
        self.reason = self.R_NONE
        self.counts = 0          # progress in the "in" direction from the origin
        self.peak = 0            # deepest point of the last IN leg
        self.torque = 0
        self.rpm_0p1 = 0
        self._limits = None
        self._raw = [0, 0]       # unwrapped motion of register 5 and register 6
        self._last = None
        self._sign = 0

    @property
    def active(self):
        return self.state in (self.IN, self.OUT)

    def start(self, speed, tlim, target, margin, stall_ms, keep):
        """Begin a pass.  The caller has checked lever / drive / link."""
        limits = self.io.read_limits()
        if limits is None:
            self.io.log('TAP refused: torque limits unreadable')
            return False
        if not (self.io.write(65, tlim) and self.io.write(66, -tlim)):
            self.io.write(65, limits[0])
            self.io.write(66, limits[1])
            self.io.log('TAP refused: torque limit not written')
            return False
        self._limits = limits
        self.tlim = tlim
        if not keep or self._last is None:
            self._raw = [0, 0]
            self._sign = 0
            self._last = None
            self.counts = 0
        # the position baseline is read before the drive is enabled, so no
        # motion goes uncounted
        if not self._read_position():
            self.io.write(65, limits[0])
            self.io.write(66, limits[1])
            self.io.log('TAP refused: position unreadable')
            return False
        self.speed = speed
        self.target = target
        self.margin = margin
        self.stall_ms = stall_ms
        self.peak = 0
        self.reason = self.R_NONE
        self._fails = 0
        self._begin(self.IN, speed)
        if not self.io.set_enabled(True):
            self._stop(self.HALTED, self.R_COMM)
            return False
        self.io.log('TAP in', speed, 'rpm, cap', tlim, '%, target', target, 'margin', margin)
        return True

    def _begin(self, leg, speed):
        self.state = leg
        now = self.io.now_ms()
        self._leg_t0 = now
        self._ref_t = now
        self._ref_c = self.counts
        self._alarm_t = now
        self._rate_t = now
        self._rate_c = self.counts
        self.io.set_speed(speed)

    def reverse_out(self):
        """From HALTED: back the tap out to margin past the origin."""
        if self.state != self.HALTED or self._limits is None:
            return False
        # the halt put the normal limit back: cap it again for the way out
        if not (self.io.write(65, self.tlim) and self.io.write(66, -self.tlim)):
            self.io.write(65, self._limits[0])
            self.io.write(66, self._limits[1])
            return False
        self.reason = self.R_OUT
        self._fails = 0
        self._begin(self.OUT, -self.speed)
        if not self.io.set_enabled(True):
            self._stop(self.HALTED, self.R_COMM)
            return False
        self.io.log('TAP reverse out from', self.counts)
        return True

    def abort(self, reason):
        if self.active:
            self._stop(self.HALTED, reason)

    def link_lost(self):
        # an unwatched pass must not keep going in: back out and stop
        if self.state == self.IN:
            self._to_out(self.R_LINK)

    def _to_out(self, reason):
        self.reason = reason
        self.peak = self.counts
        self._begin(self.OUT, -self.speed)
        self.io.log('TAP out, reason', reason, 'at', self.counts)

    def _stop(self, final, reason):
        self.io.set_enabled(False)
        if self._limits is not None:
            self.io.write(65, self._limits[0])
            self.io.write(66, self._limits[1])
        self.io.restore_speed()
        if reason != self.R_NONE:
            self.reason = reason
        self.state = final
        self.io.log('TAP stop', final, 'reason', self.reason, 'at', self.counts, 'peak', self.peak)

    def _read_position(self):
        blk = self.io.read_block()
        if blk is None:
            return False
        w5, w6, torque = blk
        self.torque = torque - 65536 if torque > 32767 else torque
        if self._last is None:
            self._last = (w5, w6)
            return True
        for i, w in enumerate((w5, w6)):
            d = (w - self._last[i]) & 0xFFFF
            if d > 32767:
                d -= 65536
            self._raw[i] += d
        self._last = (w5, w6)
        # the low word is the one that moves; the high word steps by one
        # every 65536 counts at most
        raw = self._raw[0] if abs(self._raw[0]) >= abs(self._raw[1]) else self._raw[1]
        if self._sign == 0 and abs(raw) >= self.SIGN_COUNTS:
            s = 1 if raw > 0 else -1
            self._sign = s if self.state == self.IN else -s
        if self._sign:
            self.counts = self._sign * raw
        return True

    def step(self):
        """One poll: read the drive, decide.  Call it back to back while
        the pass is active."""
        if not self.active:
            return
        if not self._read_position():
            self._fails += 1
            if self._fails >= self.FAIL_MAX:
                self._stop(self.HALTED, self.R_COMM)
            return
        self._fails = 0
        now = self.io.now_ms()
        dt = now - self._rate_t
        if dt >= 100:
            # motor rpm in 0.1 units (10000 counts per motor rev)
            self.rpm_0p1 = int((self.counts - self._rate_c) * 600000 // (10000 * dt))
            self._rate_t, self._rate_c = now, self.counts
        if now - self._alarm_t >= self.ALARM_EVERY_MS:
            self._alarm_t = now
            alarm = self.io.read_alarm()
            if alarm:
                self._stop(self.HALTED, self.R_DRIVE)
                return
        if abs(self.counts - self._ref_c) >= self.MOVE_COUNTS:
            self._ref_c, self._ref_t = self.counts, now
        stalled = (now - self._ref_t >= self.stall_ms and now - self._leg_t0 >= self.SPINUP_MS)
        if self.state == self.IN:
            if self.counts >= self.target:
                self._to_out(self.R_DEPTH)
            elif stalled:
                self._to_out(self.R_STALL)
        else:
            if self.counts <= -self.margin:
                self._stop(self.DONE, self.R_NONE)
            elif stalled:
                self._stop(self.HALTED, self.R_JAM)


def _s16(v):
    return v - 65536 if v > 32767 else v


class _TapIO:
    """What TapCycle needs from the node (kept apart so the cycle can be
    tested off the Pico)."""

    def __init__(self):
        self._t = 0
        self._last = time.ticks_ms()

    def read_block(self):
        regs = read_input_regs(0x0005, 5)          # position lo/hi .. torque
        return None if regs is None else (regs[0], regs[1], regs[4])

    def read_alarm(self):
        regs = read_input_regs(0x001A, 1)
        return None if regs is None else regs[0]

    def read_limits(self):
        regs = read_holding_regs(65, 2)
        return None if regs is None else (_s16(regs[0]), _s16(regs[1]))

    def write(self, addr, value):
        return write_reg(addr, value)

    def set_speed(self, speed):
        return write_reg(0x0089, -speed if INVERT_DIRECTION else speed)

    def set_enabled(self, on):
        ok = write_reg(0x0062, 1 if on else 0)
        if ok:
            state['enabled'] = on
        return ok

    def restore_speed(self):
        sp = state['last_speed']
        write_reg(0x0089, -sp if INVERT_DIRECTION else sp)

    def now_ms(self):
        now = time.ticks_ms()
        self._t += time.ticks_diff(now, self._last)
        self._last = now
        return self._t

    def log(self, *args):
        print(*args)


tap = TapCycle(_TapIO())


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


JOG_MAX = 300                # motor rpm, hard cap for jog
JOG_TIMEOUT_MS = 600


def jog_end(why):
    if not state['jogging']:
        return
    state['jogging'] = False
    state['jog_until'] = None
    ok = write_reg(0x0062, 0)
    if ok:
        state['enabled'] = False
    apply_speed(state['last_speed'])            # setpoint back to the panel's speed
    print('JOG end (%s):' % why, 'ok' if ok else 'disable FAILED')


def handle_cmd(data):
    """Execute one panel command; returns the ack payload."""
    ok = False
    payload = b''
    if tap.active and data[:1] == b'D':
        tap.abort(TapCycle.R_PANEL)             # disable during a pass = stop it
        state['cmd_ok'] = True
        return payload
    if tap.active and data[:1] not in (b't', b'I', b'L'):
        print('CMD', data[:1], 'refused: tap pass running')
        state['cmd_ok'] = False
        return payload
    if data[:1] == b'T' and len(data) >= 16:
        speed, tlim, target, margin, stall_ms, fl = struct.unpack('<hHIIHB', data[1:16])
        if not CONTROL_ALLOWED:
            print('CMD T refused: read-only build')
        elif state['switch'] != 'neutral':
            print('CMD T refused: lever not OFF')
        elif not state['online']:
            print('CMD T refused: drive offline')
        elif state['enabled'] or state['jogging']:
            print('CMD T refused: drive enabled')
        elif not (0 < abs(speed) <= TAP_MAX_RPM and 5 <= tlim <= TAP_TLIM_MAX and target > 0
                  and 50 <= stall_ms <= 2000):
            print('CMD T refused: parameters', speed, tlim, target, stall_ms)
        else:
            ok = tap.start(speed, tlim, target, margin, stall_ms, bool(fl & 1))
    elif data[:1] == b't':
        tap.abort(TapCycle.R_PANEL)
        ok = True
    elif data[:1] == b'U':
        if state['switch'] != 'neutral' or not state['online']:
            print('CMD U refused: lever not OFF or drive offline')
        else:
            ok = tap.reverse_out()
    elif data[:1] == b'J' and len(data) >= 3:
        speed = struct.unpack('<h', data[1:3])[0]
        speed = max(-JOG_MAX, min(JOG_MAX, speed))
        if state['switch'] != 'neutral':
            print('CMD J refused: lever not OFF')
        elif state['enabled'] and not state['jogging']:
            print('CMD J refused: drive already enabled')
        elif not state['online']:
            print('CMD J refused: drive offline')
        else:
            wire = -speed if INVERT_DIRECTION else speed
            ok = write_reg(0x0089, wire)
            if ok and not state['jogging']:
                ok = write_reg(0x0062, 1)
                if ok:
                    state['enabled'] = True
                    state['jogging'] = True
                    print('JOG start', speed)
            if ok:
                state['jog_until'] = time.ticks_add(time.ticks_ms(), JOG_TIMEOUT_MS)
    elif data[:1] == b'j':
        jog_end('panel')
        ok = True
    elif data[:1] == b'I':
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
            t0 = time.ticks_us()
            resp = modbus_txn(pdu, 4, timeout_ms=600)
            dt_us = time.ticks_diff(time.ticks_us(), t0)
            ok = resp is not None
            # ack payload: uint16 LE response time in 0.1 ms, then the response PDU
            payload = struct.pack('<H', min(65535, dt_us // 100)) + (bytes(resp) if ok else b'')
            if fn == 0x41:
                # give the drive total bus silence after a save request
                state['save_until'] = time.ticks_add(time.ticks_ms(), 10000)
            print('CMD X', pdu, '->', resp, dt_us, 'us')
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
        if tap.active:
            await asyncio.sleep_ms(POLL_MS)          # the tap pass owns the bus
            continue
        if state['save_until'] is not None:
            if time.ticks_diff(state['save_until'], time.ticks_ms()) > 0:
                await asyncio.sleep_ms(POLL_MS)      # drive busy writing EEPROM
                continue
            state['save_until'] = None
        if state['jogging'] and time.ticks_diff(time.ticks_ms(), state['jog_until']) > 0:
            jog_end('keep-alive timeout')
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


async def tap_task():
    while True:
        if tap.active:
            tap.step()
            state['torque'] = tap.torque
            state['rpm'] = tap.rpm_0p1
            await asyncio.sleep_ms(2)
        else:
            await asyncio.sleep_ms(50)


async def switch_task():
    last = read_switch()
    while True:
        cur = read_switch()
        if cur == last and cur != state['switch']:
            state['switch'] = cur
            print('SWITCH', cur)
            if CONTROL_ALLOWED and tap.active:
                # any lever movement stops a tap pass; it must go through OFF
                # before it can start anything
                tap.abort(TapCycle.R_LEVER)
                state['armed'] = False
            elif CONTROL_ALLOWED:
                if state['jogging']:
                    jog_end('lever moved')
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
try:
    # MicroPython's default is 20 bytes, which truncates any longer write;
    # updates arrive as 'f' + up to ~240 bytes once the MTU is raised
    bluetooth.BLE().gatts_set_buffer(cmd_char._value_handle, 256)
except Exception as exc:
    print('CMD buffer not enlarged:', exc)
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
            print('NODE rpm:%d tq:%d al:%d sw:%s on:%d en:%d pe:%d nf:%d pins fwd=%d rev=%d' % (
                state['rpm'], state['torque'], state['alarm'], state['switch'],
                state['online'], state['enabled'], state['poll_errors'], state['notify_fail'],
                pin_fwd.value(), pin_rev.value()))
        data_char.write(struct.pack('<IiiIhhHBHBBii', seq, x, z, t, state['rpm'],
                                    state['torque'], state['alarm'], flags(),
                                    state['avg_load'] & 0xFFFF, tap.state, tap.reason,
                                    tap.counts, tap.peak))
        conn = state['conn']
        if conn is not None:
            try:
                data_char.notify(conn)
            except Exception:
                state['notify_fail'] += 1
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
            state['conn'] = conn
            asyncio.create_task(report_mtu(conn))
            await conn.disconnected(timeout_ms=None)
            print('BLE disconnected')
            state['conn'] = None
            state['linked'] = False
            # panel gone: stop the spindle and make the switch pass through
            # OFF before it can start anything again.  A tap pass going in
            # backs out and stops by itself instead of stopping in the hole.
            if tap.active:
                tap.link_lost()
            else:
                safe_disable('link lost', zero_speed=True)
            state['armed'] = False


async def report_mtu(conn):
    # the panel (BlueZ) runs the MTU exchange just after connecting
    await asyncio.sleep_ms(3000)
    print('BLE mtu', getattr(conn, 'mtu', None))


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
                         drive_poller(), tap_task(), switch_task(), watchdog(), trial_confirm())


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
