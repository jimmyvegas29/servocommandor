"""Phone remote protocol: hello / pairing / commands / state, without D-Bus.

    python tests/test_phone_remote.py
"""
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import phone_remote                                                # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print('%-52s got %-26r want %-26r %s' % (label, got, want, 'OK' if ok else 'FAIL'))


class FakeChr:
    def __init__(self):
        self.value = b''

    def set_value(self, v, force=False):
        self.value = bytes(v)


cmds = []
paired = {}
r = phone_remote.PhoneRemote(lambda c, a: cmds.append((c, a)), lambda pid: pid in paired,
                             lambda pid, name: paired.__setitem__(pid, name))
r._state_chr = FakeChr()
PHONE = '/org/bluez/hci0/dev_7C_D9_5C_B3_ED_33'
OTHER = '/org/bluez/hci0/dev_11_22_33_44_55_66'
pid = bytes(range(1, 9))


def flags():
    return r._state_chr.value[0]


# commands before any hello are ignored
r._on_write(b'EX\x01'[:1] + b'\x01', PHONE)
r._on_write(b'J', PHONE)
check('no hello: commands ignored', cmds, [])

# an unknown phone is refused while PAIR is closed
r._on_write(b'H' + pid + b'Pixel 3 XL', PHONE)
check('unpaired phone refused', (paired, bool(flags() & phone_remote.F_REFUSED), r.connected), ({}, True, False))
r._on_write(b'E\x01', PHONE)
check('refused phone: commands ignored', cmds, [])

# PAIR open: the phone is paired, remembered, accepted
r.open_pairing(60)
r._on_write(b'H' + pid + b'Pixel 3 XL', PHONE)
check('PAIR: phone paired and accepted', (paired, r.connected, r.pairing),
      ({pid.hex(): 'Pixel 3 XL'}, True, False))
check('state says a paired phone is here', (bool(flags() & phone_remote.F_PAIRED), bool(flags() & phone_remote.F_REFUSED)),
      (True, False))

# commands
r._on_write(b'DF', PHONE)
r._on_write(b'DR', PHONE)
r._on_write(b'E\x01', PHONE)
r._on_write(b'E\x00', PHONE)
r._on_write(b'J', PHONE)
r._on_write(b'j', PHONE)
r._on_write(b'+', PHONE)
r._on_write(b'-', PHONE)
r._on_write(b'P\x03', PHONE)
r._on_write(b'P\x07', PHONE)
r._on_write(b'C' + struct.pack('<H', 1234), PHONE)
r._on_write(b'DX', PHONE)
r._on_write(b'?', PHONE)
check('commands passed on', cmds, [('dir', 'fwd'), ('dir', 'rev'), ('enable', True), ('enable', False),
                                   ('jog', True), ('jog', False), ('step', 1), ('step', -1),
                                   ('preset', 3), ('custom', 1234)])

# a second device that did not say hello cannot command
del cmds[:]
r._on_write(b'E\x01', OTHER)
check('another device without hello: ignored', cmds, [])

# the paired phone comes back later (new link, new address): accepted again
r2 = phone_remote.PhoneRemote(lambda c, a: cmds.append((c, a)), lambda p: p in paired, lambda p, n: None)
r2._state_chr = FakeChr()
r2._on_write(b'H' + pid + b'Pixel', OTHER)
r2._on_write(b'E\x01', OTHER)
check('paired phone on a new link: accepted', (r2.connected, cmds[-1]), (True, ('enable', True)))

# state packing: flags, rpm, version
r.set_state(phone_remote.F_ENABLED | phone_remote.F_REV | phone_remote.F_ONLINE, 600, 15,
            [50, 100, 200, 400, 600, 800], 1818)
r._push_state()
v = r._state_chr.value
f, rpm, ver, step = struct.unpack('<BHBH', v[:6])
check('state: flags, rpm, version, step', (f & ~phone_remote.F_PAIRED, rpm, ver, step),
      (phone_remote.F_ENABLED | phone_remote.F_REV | phone_remote.F_ONLINE, 600, phone_remote.PROTOCOL, 15))
check('state: presets and top speed, 20 bytes', (len(v), list(struct.unpack('<6HH', v[6:]))),
      (20, [50, 100, 200, 400, 600, 800, 1818]))

# the heartbeat goes out every second even when nothing changed
class CountingChr(FakeChr):
    sent = 0

    def set_value(self, v, force=False):
        if force or bytes(v) != self.value:
            CountingChr.sent += 1
        FakeChr.set_value(self, v)


r._state_chr = CountingChr()
r._push_state()
n0 = CountingChr.sent
r._push_state()
check('unchanged state: no extra notify on a change push', CountingChr.sent, n0)
r._push_state(force=True)
r._push_state(force=True)
check('heartbeat: notifies every time', CountingChr.sent, n0 + 2)

# the phone disconnecting: forgotten until its next hello, the app is told
class Msg:
    member = 'PropertiesChanged'
    path = PHONE
    body = ['org.bluez.Device1', {'Connected': type('V', (), {'value': False})()}, []]


del cmds[:]
r._bus_message(Msg())
check('disconnect: not connected, app told', (r.connected, cmds), (False, [('gone', None)]))
r._on_write(b'E\x01', PHONE)
check('after disconnect: commands ignored until hello', cmds, [('gone', None)])

print('RESULT:', 'ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
