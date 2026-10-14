"""Phone remote: a Bluetooth LE service on the panel for the Servo Remote
phone app.

The panel stays the one brain: the phone only says which button was
pressed, and the app runs it through the same code as its own buttons.
The Pi's Bluetooth is the machine node's central at the same time; this is
the peripheral side (BlueZ GATT server + advertisement over D-Bus, with the
dbus_fast that bleak already brings).

Service 5e7a1001-...:
  CMD    write      b'H' + 8-byte phone id + name (up to 11 bytes): hello.
                    Must come first on every connection; a phone the panel
                    has not paired is refused unless PAIR is open on the
                    panel, in which case it is paired and remembered.
                    After an accepted hello:
                    b'D' + b'F' / b'R'   direction
                    b'E' + 1 / 0         enable / disable
                    b'J'                 jog: held (repeat every 150 ms)
                    b'j'                 jog released
  STATE  read/notify  flags byte, uint16 LE commanded spindle rpm, version
                    flags: b0 a paired phone is connected, b1 enabled,
                    b2 direction REV, b3 jogging, b4 drive online,
                    b5 jog allowed, b6 lever not OFF, b7 last hello refused
                    (not paired).  Sent on every change and once a second.
"""
import asyncio
import struct
import threading
import time

from applog import log

SERVICE_UUID = '5e7a1001-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
CMD_UUID = '5e7a1002-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
STATE_UUID = '5e7a1003-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
LOCAL_NAME = 'SC Panel'            # 8 characters: fits beside the 128-bit UUID
APP_PATH = '/com/servocom/remote'
ADV_PATH = '/com/servocom/remote/adv0'
ADAPTER = '/org/bluez/hci0'
PROTOCOL = 1

F_PAIRED, F_ENABLED, F_REV, F_JOG, F_ONLINE, F_JOG_OK, F_LEVER, F_REFUSED = (1 << i for i in range(8))

try:
    from dbus_fast import BusType, Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import ServiceInterface, dbus_property, method, PropertyAccess
except Exception:                       # not on the Pi (tests, Windows)
    ServiceInterface = None


def pack_state(flags, rpm):
    return struct.pack('<BHB', flags & 0xFF, max(0, min(65535, int(rpm))), PROTOCOL)


if ServiceInterface is not None:

    class _Service(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.GattService1')

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> 's':
            return SERVICE_UUID

        @dbus_property(access=PropertyAccess.READ)
        def Primary(self) -> 'b':
            return True

    class _Characteristic(ServiceInterface):
        def __init__(self, uuid, service_path, flags, on_write=None):
            super().__init__('org.bluez.GattCharacteristic1')
            self._uuid = uuid
            self._service = service_path
            self._flags = flags
            self._value = b''
            self._on_write = on_write
            self.notifying = False

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> 's':
            return self._uuid

        @dbus_property(access=PropertyAccess.READ)
        def Service(self) -> 'o':
            return self._service

        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> 'as':
            return self._flags

        @dbus_property(access=PropertyAccess.READ)
        def Value(self) -> 'ay':
            return self._value

        @method()
        def ReadValue(self, options: 'a{sv}') -> 'ay':
            return self._value

        @method()
        def WriteValue(self, value: 'ay', options: 'a{sv}'):
            dev = options.get('device')
            if self._on_write is not None:
                self._on_write(bytes(value), dev.value if dev is not None else '')

        @method()
        def StartNotify(self):
            self.notifying = True

        @method()
        def StopNotify(self):
            self.notifying = False

        def set_value(self, value):
            value = bytes(value)
            if value == self._value:
                return
            self._value = value
            if self.notifying:
                self.emit_properties_changed({'Value': value})

    class _Advertisement(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.LEAdvertisement1')

        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> 's':
            return 'peripheral'

        @dbus_property(access=PropertyAccess.READ)
        def ServiceUUIDs(self) -> 'as':
            return [SERVICE_UUID]

        @dbus_property(access=PropertyAccess.READ)
        def LocalName(self) -> 's':
            return LOCAL_NAME

        @method()
        def Release(self):
            log.info('phone remote: advertisement released by BlueZ')


class PhoneRemote:
    """Runs the service in its own asyncio thread.

    on_command(cmd, arg) is called (from that thread) for every command of
    an accepted phone; the app hands it to its UI thread.  is_paired(id) and
    on_pair(id, name) keep the list of paired phones in the app's settings.
    """

    def __init__(self, on_command, is_paired, on_pair):
        self.on_command = on_command
        self.is_paired = is_paired
        self.on_pair = on_pair
        self.pairing_until = 0.0         # monotonic deadline of an open PAIR window
        self.status = 'off'
        self.phone_name = ''
        self._accepted = {}              # device path -> phone name
        self._refused = False
        self._flags = 0
        self._rpm = 0
        self._loop = None
        self._thread = None
        self._stop = None
        self._state_chr = None

    # ---- lifecycle (any thread) --------------------------------------
    def start(self):
        if ServiceInterface is None:
            self.status = 'not available on this computer'
            return False
        if self._thread is not None:
            return True
        self.status = 'starting'
        self._thread = threading.Thread(target=self._run, name='phone-remote', daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self.status = 'off'
        self._accepted.clear()

    def open_pairing(self, seconds=60):
        self.pairing_until = time.monotonic() + seconds

    @property
    def pairing(self):
        return time.monotonic() < self.pairing_until

    @property
    def connected(self):
        return bool(self._accepted)

    def set_state(self, flags, rpm):
        """The app's current state (UI thread); sent if it changed."""
        self._flags, self._rpm = flags, rpm
        if self._loop is not None and self._state_chr is not None:
            self._loop.call_soon_threadsafe(self._push_state)

    # ---- the asyncio side ----------------------------------------------
    def _state_value(self):
        f = self._flags & ~(F_PAIRED | F_REFUSED)
        if self._accepted:
            f |= F_PAIRED
        if self._refused:
            f |= F_REFUSED
        return pack_state(f, self._rpm)

    def _push_state(self):
        if self._state_chr is not None:
            self._state_chr.set_value(self._state_value())

    def _on_write(self, data, device):
        if not data:
            return
        cmd = data[:1]
        if cmd == b'H':
            self._hello(data[1:], device)
            return
        if device not in self._accepted:
            return                                   # no accepted hello on this link
        if cmd == b'D' and len(data) >= 2 and data[1:2] in (b'F', b'R'):
            self.on_command('dir', 'fwd' if data[1:2] == b'F' else 'rev')
        elif cmd == b'E' and len(data) >= 2:
            self.on_command('enable', bool(data[1]))
        elif cmd == b'J':
            self.on_command('jog', True)
        elif cmd == b'j':
            self.on_command('jog', False)

    def _hello(self, payload, device):
        if len(payload) < 8:
            return
        phone_id = payload[:8].hex()
        name = payload[8:20].decode('utf-8', 'replace').strip() or 'phone'
        if self.is_paired(phone_id):
            ok = True
        elif self.pairing:
            self.on_pair(phone_id, name)
            self.pairing_until = 0.0
            log.info('phone remote: paired %s (%s)', name, phone_id)
            ok = True
        else:
            ok = False
        if ok:
            self._accepted = {device: name}         # one phone at a time: the latest hello wins
            self._refused = False
            self.phone_name = name
            self.status = 'connected: %s' % name
            log.info('phone remote: %s connected', name)
        else:
            self._refused = True
            log.info('phone remote: refused %s (%s): not paired', name, phone_id)
        self._push_state()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:
            log.warning('phone remote stopped: %s', exc)
            self.status = 'error: %s' % exc
        finally:
            self._state_chr = None
            self._loop.close()
            self._loop = None

    async def _main(self):
        self._stop = asyncio.Event()
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        svc_path = APP_PATH + '/service0'
        service = _Service()
        cmd = _Characteristic(CMD_UUID, svc_path, ['write', 'write-without-response'], self._on_write)
        state = _Characteristic(STATE_UUID, svc_path, ['read', 'notify'])
        state.set_value(self._state_value())
        adv = _Advertisement()
        bus.export(svc_path, service)
        bus.export(svc_path + '/char0', cmd)
        bus.export(svc_path + '/char1', state)
        bus.export(ADV_PATH, adv)
        intro = await bus.introspect('org.bluez', ADAPTER)
        adapter = bus.get_proxy_object('org.bluez', ADAPTER, intro)
        gatt = adapter.get_interface('org.bluez.GattManager1')
        advm = adapter.get_interface('org.bluez.LEAdvertisingManager1')
        await gatt.call_register_application(APP_PATH, {})
        await advm.call_register_advertisement(ADV_PATH, {})
        self._state_chr = state
        self.status = 'waiting for the phone'
        log.info('phone remote: advertising as %s', LOCAL_NAME)
        bus.add_message_handler(self._bus_message)
        # Device1 property changes (the phone disconnecting) only arrive with a match rule
        from dbus_fast import Message
        await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                               interface='org.freedesktop.DBus', member='AddMatch', signature='s',
                               body=["type='signal',sender='org.bluez',"
                                     "interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'"]))
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), 1.0)
                except asyncio.TimeoutError:
                    pass
                self._push_state()                       # once a second: the phone sees we are alive
                if not self._accepted and not self.status.startswith('error'):
                    self.status = 'pairing: open the app on the phone' if self.pairing else 'waiting for the phone'
        finally:
            self._state_chr = None
            for call in (lambda: advm.call_unregister_advertisement(ADV_PATH),
                         lambda: gatt.call_unregister_application(APP_PATH)):
                try:
                    await call()
                except Exception:
                    pass
            bus.disconnect()
            log.info('phone remote: stopped')

    def _bus_message(self, msg):
        """A paired phone that disconnects is forgotten until its next hello."""
        try:
            if (msg.member == 'PropertiesChanged' and msg.path in self._accepted
                    and msg.body and msg.body[0] == 'org.bluez.Device1'):
                changed = msg.body[1]
                if 'Connected' in changed and not changed['Connected'].value:
                    name = self._accepted.pop(msg.path, '')
                    self.status = 'waiting for the phone'
                    log.info('phone remote: %s disconnected', name)
                    self.on_command('gone', None)
        except Exception:
            pass
        return None
