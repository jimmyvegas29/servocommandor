"""Node event log: the firmware's own history of drive dropouts.

Runs the real functions out of firmware/main_node.py (pulled out by name, the
same way test_tap_cycle.py takes TapCycle) against a simulated RS-485 line.

    python tests/test_node_events.py
"""
import ast
import asyncio as real_asyncio
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, '..', 'firmware', 'main_node.py'), encoding='utf-8').read()

WANT_DEFS = {'_boot_count', 'ev', 'uart_open', '_mb_fail', 'mb_counts', 'mb_since', 'uart_reinit',
             'crc16', 'modbus_txn', 'read_input_regs', 'write_reg', 'safe_disable', 'drive_poller'}
WANT_NAMES = {'EVLOG', 'EVLOG_OLD', 'EVLOG_MAX', 'EVLOG_BURST', 'EVLOG_REFILL_S', 'BOOT_FILE', 'evlog',
              'mb', 'MB_KINDS', 'OFFLINE_AFTER', 'REAPPEAR_MS', 'REINIT_AFTER', 'REINIT_EVERY',
              'SLAVE_ID', 'POLL_MS', 'CONTROL_ALLOWED', 'state'}

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    short = lambda v: repr(v) if len(repr(v)) < 90 else repr(v)[:40] + ' ... ' + repr(v)[-40:]
    print('%-52s got %-26s want %-26s %s' % (label, short(got), short(want), 'OK' if ok else 'FAIL'))


class Clock:
    """The node's time module, with a clock the test drives."""
    def __init__(self):
        self.ms = 1000

    def ticks_ms(self):
        return self.ms

    def ticks_diff(self, a, b):
        return a - b

    def ticks_add(self, a, b):
        return a + b

    def sleep_ms(self, n):
        self.ms += n

    def localtime(self):
        return (2026, 9, 30, 20, 43, 31, 0, 0)


class Line:
    """The RS-485 line and the drive on the far end."""
    def __init__(self):
        self.mode = 'ok'            # ok / none / short / crc
        self.node_stuck = False     # our own port is stuck: only a re-open clears it
        self.opens = 0
        self.writes = []            # (addr, value) the drive accepted


class FakeUart:
    def __init__(self, line, crc16):
        self.line, self.crc16, self.rx = line, crc16, b''

    def any(self):
        return len(self.rx)

    def read(self):
        out, self.rx = self.rx, b''
        return out or None

    def flush(self):
        pass

    def deinit(self):
        pass

    def write(self, frame):
        line = self.line
        if line.node_stuck or line.mode == 'none':
            return
        fn = frame[1]
        if fn == 0x04:
            count = struct.unpack('>H', frame[4:6])[0]
            body = bytes([1, 0x04, 2 * count]) + struct.pack('>%dH' % count, *([0] * count))
        else:                        # 06H echoes the request
            body = bytes(frame[:6])
            line.writes.append(struct.unpack('>HH', frame[2:6]))
        full = body + struct.pack('<H', self.crc16(body))
        if line.mode == 'short':
            full = full[:7]
        elif line.mode == 'crc':
            full = full[:-1] + bytes([full[-1] ^ 0x55])
        self.rx = full


class FakePin:
    OUT = 1

    def __init__(self, *a, **k):
        pass

    def value(self, v=None):
        return 0

    def init(self, *a, **k):
        pass


class Stop(Exception):
    pass


def build(tmp):
    """A fresh copy of the firmware's log / Modbus / poll code in tmp."""
    clock, line = Clock(), Line()
    body = []
    for node in ast.parse(SRC).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in WANT_DEFS:
            body.append(node)
        elif isinstance(node, ast.Assign) and all(
                isinstance(t, ast.Name) and t.id in WANT_NAMES for t in node.targets):
            body.append(node)
        elif isinstance(node, ast.Assign) and all(
                isinstance(t, ast.Tuple) and all(e.id in WANT_NAMES for e in t.elts) for t in node.targets):
            body.append(node)

    class Aio:
        polls = 0
        limit = 0

        @staticmethod
        async def sleep_ms(n):
            clock.ms += n
            Aio.polls += 1
            if Aio.polls >= Aio.limit:
                raise Stop()

    class Tap:
        active = False

    import binascii
    os.chdir(tmp)
    ns = {'os': os, 'time': clock, 'struct': struct, 'binascii': binascii, 'asyncio': Aio,
          'Pin': FakePin, 'UART': None, 'tap': Tap, 'de': FakePin(), 'print': lambda *a, **k: None,
          'INVERT_DIRECTION': True, 'jog_end': lambda why: None}
    exec(compile(ast.Module(body=body, type_ignores=[]), 'main_node.py', 'exec'), ns)
    ns['uart_open'] = lambda: (setattr(line, 'opens', line.opens + 1),
                               setattr(line, 'node_stuck', False),
                               FakeUart(line, ns['crc16']))[2]
    ns['uart'] = FakeUart(line, ns['crc16'])
    ns['evlog']['clock'] = True
    return ns, clock, line, Aio


def log_lines():
    out = []
    for name in ('events.old', 'events.log'):
        if os.path.exists(name):
            out += open(name).read().splitlines()
    return out


def scenario(schedule, total):
    """schedule: {poll number: function(line)} applied as the poll count passes."""
    tmp = tempfile.mkdtemp()
    ns, clock, line, aio = build(tmp)
    orig = aio.sleep_ms

    async def sleep_ms(n):
        clock.ms += n
        aio.polls += 1
        fn = schedule.get(aio.polls)
        if fn:
            fn(line, ns)
        if aio.polls >= total:
            raise Stop()
    aio.sleep_ms = staticmethod(sleep_ms)
    aio.polls = 0
    try:
        real_asyncio.new_event_loop().run_until_complete(ns['drive_poller']())
    except Stop:
        pass
    aio.sleep_ms = orig
    return ns, line, log_lines()


def has(lines, text):
    return sum(1 for l in lines if text in l)


# ---------------------------------------------------------------- the log file
tmp = tempfile.mkdtemp()
ns, clock, line, aio = build(tmp)
ns['evlog']['boot'] = ns['_boot_count']()
check('boot counter starts at 1', ns['evlog']['boot'], 1)
check('boot counter survives a reboot', ns['_boot_count'](), 2)
ns['ev']('BOOT test')
first = log_lines()[0]
check('line has boot, uptime, date, text', first, 'b1 +0s 09-30 20:43:31 BOOT test')
ns['evlog']['tokens'] = 10 ** 6
for i in range(2000):
    ns['ev']('filler line number %d with some length to it' % i)
sizes = [os.path.getsize(n) for n in ('events.log', 'events.old')]
check('both files stay under the cap', all(s <= ns['EVLOG_MAX'] for s in sizes), True)
check('total never passes 12 KB', sum(sizes) <= 12000, True)
check('newest line is kept', log_lines()[-1].endswith('filler line number 1999 with some length to it'), True)
check('oldest lines are gone', has(log_lines(), 'BOOT test'), 0)
# a burst is cut off, and the next line says how many were skipped
ns['evlog']['tokens'] = 2
for i in range(7):
    ns['ev']('burst %d' % i)
ns['evlog']['tokens'] = 1
ns['ev']('after the burst')
check('burst limited, skipped lines counted', log_lines()[-1].split(' ', 4)[-1], '(5 not logged) after the burst')

# ---------------------------------------------------------------- how an exchange failed
tmp = tempfile.mkdtemp()
ns, clock, line, aio = build(tmp)
check('good exchange', ns['read_input_regs'](9, 19) is not None, True)
for mode in ('none', 'short', 'crc'):
    line.mode = mode
    ns['read_input_regs'](9, 19)
    check('silence / cut-off / corrupt told apart: ' + mode, (ns['mb']['last'], ns['mb'][mode]), (mode, 1))
check('since-snapshot summary', ns['mb_since']((0, 0, 0, 0, 0)), 'none=1 short=1 crc=1')

# ---------------------------------------------------------------- one missed reply
ns, line, lines = scenario({20: lambda l, n: setattr(l, 'mode', 'none'),
                            21: lambda l, n: setattr(l, 'mode', 'ok')}, 40)
check('single miss logged once', (has(lines, 'MISS drive reply (none'), has(lines, 'DRIVE OFFLINE')), (1, 0))

# ---------------------------------------------------------------- the drive goes silent and stays silent
def enable(l, n):
    n['state']['enabled'] = True


ns, line, lines = scenario({10: enable, 20: lambda l, n: setattr(l, 'mode', 'none')}, 120)
check('drive first seen', has(lines, 'DRIVE online (first sight since boot)'), 1)
off = [l for l in lines if 'DRIVE OFFLINE' in l]
check('offline logged once, as silence', (len(off), 'none=10' in off[0], 'enabled=1' in off[0]), (1, True, True))
check('port re-opened and logged (3 lines at most)', (line.opens >= 2, has(lines, 'SERIAL PORT re-opened')), (True, 3))
check('no recovery claimed', has(lines, 'DRIVE BACK'), 0)

# the lever goes OFF during the outage: the failed stop is on record
tmp = tempfile.mkdtemp()
ns, clock, line, aio = build(tmp)
ns['state'].update(enabled=True, online=False, boot_disable=True)
line.mode = 'none'
check('stop fails while the drive is silent', ns['safe_disable']('switch neutral'), False)
check('failed stop is logged', has(log_lines(), 'STOP FAILED (switch neutral)'), 1)
line.mode = 'ok'
check('stop works once it answers', (ns['safe_disable']('switch neutral'), ns['state']['enabled']), (True, False))
check('routine lever stops are not logged', len(log_lines()), 1)

# ---------------------------------------------------------------- our own port was stuck
def stick(l, n):
    l.node_stuck = True


ns, line, lines = scenario({10: enable, 20: stick}, 80)
back = [l for l in lines if 'DRIVE BACK' in l]
check('recovery right after the re-open blames the node side',
      (len(back), 'straight after re-opening the serial port' in back[0] if back else None), (1, True))
check('a drive that was away >= 2 s is stopped on return', (has(lines, 'STOP ok (drive online)') >= 1,
                                                         (0x62, 0) in line.writes), (True, True))

# ---------------------------------------------------------------- the drive comes back by itself
ns, line, lines = scenario({10: enable, 20: lambda l, n: setattr(l, 'mode', 'none'),
                            28: lambda l, n: setattr(l, 'mode', 'ok')}, 60)
back = [l for l in lines if 'DRIVE BACK' in l]
check('recovery without a re-open is "by itself"', (len(back), 'by itself' in back[0] if back else None), (1, True))

# ---------------------------------------------------------------- noise instead of silence
ns, line, lines = scenario({10: enable, 20: lambda l, n: setattr(l, 'mode', 'crc')}, 40)
off = [l for l in lines if 'DRIVE OFFLINE' in l]
check('corrupted replies are reported as crc, not silence', ('crc=10' in off[0], 'none=' in off[0]), (True, False))

# ---------------------------------------------------------------- the panel fetches it over Bluetooth
# the firmware's real command handler answers; the panel's real fetch code asks
sys.path.insert(0, os.path.join(HERE, '..'))
import dro_ble                                                      # noqa: E402

tmp = tempfile.mkdtemp()
os.chdir(tmp)
rtc_set = []


class FakeRTC:
    def datetime(self, t):
        rtc_set.append(t)


body = [n for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef) and n.name == 'handle_cmd']
fw = {'os': os, 'struct': struct, 'print': lambda *a, **k: None, 'RTC': FakeRTC, 'VERSION': 'node 3.15',
      'EVLOG': 'events.log', 'EVLOG_OLD': 'events.old', 'evlog': {'clock': False},
      'state': {'cmd_ok': True, 'online': True, 'enabled': False}, 'mb': {'last': ''},
      'tap': type('T', (), {'active': False})(), 'ev': lambda m: None}
exec(compile(ast.Module(body=body, type_ignores=[]), 'main_node.py', 'exec'), fw)


class FakeClient:
    """The Bluetooth link: a write reaches handle_cmd, the ack comes back
    cut to what one notify carries at this MTU."""
    def __init__(self, ble, mtu):
        self.ble, self.mtu_size, self.asked = ble, mtu, 0

    async def write_gatt_char(self, _uuid, data, response=False):
        self.asked += 1
        payload = fw['handle_cmd'](bytes(data))
        ack = bytes([1 if fw['state']['cmd_ok'] else 0]) + bytes(data[:1]) + payload
        real_asyncio.get_event_loop().call_soon(self.ble._parse_ack, ack[:self.mtu_size - 3])


def fetch(ble, client, full):
    real_asyncio.get_event_loop().run_until_complete(ble._fetch_events(client, full))


real_asyncio.set_event_loop(real_asyncio.new_event_loop())
old_text = ''.join('b6 +%ds 09-29 10:00:00 older line %d' % (i, i) + chr(10) for i in range(120))
new_text = ('b7 +0s no-clock BOOT node 3.15, reset cause: power-on' + chr(10)
            + 'b7 +774s 09-30 20:43:31 DRIVE OFFLINE: none=10, last rx= | enabled=1 lever=fwd' + chr(10))
open('events.old', 'wb').write(old_text.encode())
open('events.log', 'wb').write(new_text.encode())
for mtu in (247, 23):
    ble = dro_ble.DroBle(address='AA:BB')
    ble.node_events_path = os.path.join(tmp, 'panel_node_events_%d.log' % mtu)
    ble._ev_seen = set()
    ble.node_version, ble.is_node, ble.connected = 'node 3.15', True, True
    client = FakeClient(ble, mtu)
    ble._client = client
    fetch(ble, client, True)
    check('mtu %d: whole log fetched, oldest first' % mtu, ble.node_events_text(), old_text + new_text)
    check('mtu %d: saved on the panel' % mtu, open(ble.node_events_path, newline='').read().replace(chr(13), ''), old_text + new_text)
check('small MTU just takes more round trips', client.asked > 300, True)
check('node clock set from the panel', (len(rtc_set) >= 1, fw['evlog']['clock'], rtc_set[0][0] >= 2026), (True, True, True))
# big MTU panel again: only what is new is asked for
ble = dro_ble.DroBle(address='AA:BB')
ble.node_events_path = os.path.join(tmp, 'panel_incr.log')
ble._ev_seen = set()
ble.node_version, ble.is_node, ble.connected = 'node 3.15', True, True
client = FakeClient(ble, 247)
ble._client = client
fetch(ble, client, True)
extra = 'b7 +790s 09-30 20:43:47 STOP FAILED (switch neutral): the drive did not take the disable' + chr(10)
open('events.log', 'ab').write(extra.encode())
client.asked = 0
fetch(ble, client, False)
check('later fetch adds only the new line', (ble.node_events_text(), client.asked <= 3),
      (old_text + new_text + extra, True))
# the node's file filled and rotated: the panel notices and starts over
os.remove('events.old')
os.rename('events.log', 'events.old')
open('events.log', 'wb').write(b'b7 +900s 09-30 20:45:37 PANEL linked' + bytes([10]))
fetch(ble, client, False)
check('rotation on the node is followed', ble.node_events_text(),
      new_text + extra + 'b7 +900s 09-30 20:45:37 PANEL linked' + chr(10))
check('older nodes are never asked', (setattr(ble, 'node_version', 'node 3.14'), ble.request_node_events())[1], False)

print('RESULT:', 'ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
