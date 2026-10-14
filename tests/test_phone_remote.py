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

    def set_value(self, v):
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
r._on_write(b'DX', PHONE)
r._on_write(b'?', PHONE)
check('commands passed on', cmds, [('dir', 'fwd'), ('dir', 'rev'), ('enable', True), ('enable', False),
                                   ('jog', True), ('jog', False)])

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
r.set_state(phone_remote.F_ENABLED | phone_remote.F_REV | phone_remote.F_ONLINE, 600)
r._push_state()
f, rpm, ver = struct.unpack('<BHB', r._state_chr.value)
check('state: flags, rpm, version', (f & ~phone_remote.F_PAIRED, rpm, ver),
      (phone_remote.F_ENABLED | phone_remote.F_REV | phone_remote.F_ONLINE, 600, phone_remote.PROTOCOL))

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
