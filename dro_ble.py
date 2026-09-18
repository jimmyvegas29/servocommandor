"""Bluetooth LE reader for the DRO tap board (Pico 2 W running firmware v2).

The board is a BLE peripheral advertising SERVICE_UUID; this module is the
central.  A background thread runs an asyncio loop that scans (or connects
straight to a remembered address), subscribes to the DATA characteristic
and keeps the latest sample.  Same interface as dro_serial.DroSerial so the
app can use either:  start() / stop() / latest() / stale / connected /
frames / dropped.  ping() measures round-trip time through the PING echo.
"""
import asyncio
import struct
import threading
import time
import os

from applog import log

try:
    from bleak import BleakClient, BleakScanner
except ImportError:          # desktop without bleak
    BleakClient = BleakScanner = None

SERVICE_UUID = '5e7a0001-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
DATA_UUID = '5e7a0002-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
PING_UUID = '5e7a0003-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
CMD_UUID = '5e7a0004-8d2c-4b1e-9c3a-2f6d0a1b3c4d'      # machine node only
STALE_S = 0.5

# node packet (firmware v3): seq, x, z, t_ms, rpm_0p1, torque, alarm, flags
NODE_FMT = '<IiiIhhHB'
NODE_LEN = struct.calcsize(NODE_FMT)      # 23 bytes (node <= 3.4)
NODE_FMT2 = '<IiiIhhHBH'                  # + average load ratio % (node 3.5)
NODE_LEN2 = struct.calcsize(NODE_FMT2)    # 25 bytes
F_ONLINE, F_FWD, F_REV, F_ENABLED, F_CONTROL, F_CMD_OK = 1, 2, 4, 8, 16, 32


def scan_boards(timeout=4.0):
    """Blocking scan (own event loop): [(address, name, rssi)] strongest first."""
    if BleakScanner is None:
        return []

    async def _scan():
        found = []
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for dev, adv in devices.values():
            name = adv.local_name or dev.name or ''
            if SERVICE_UUID in (adv.service_uuids or []) or name.startswith('SERVOCOM-DRO'):
                found.append((dev.address, name, adv.rssi))
        found.sort(key=lambda f: -(f[2] if f[2] is not None else -999))
        return found

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_scan())
    finally:
        loop.close()


def parse_packet(data):
    """bytes -> {'s','x','z','t'} (+ drive fields from a machine node) or None.

    16 bytes: DRO tap (firmware v2).  23 bytes: machine node (v3) adds
    rpm (0.1 rpm, signed), torque %, alarm code and a flags byte."""
    if len(data) == 16:
        s, x, z, t = struct.unpack('<IiiI', data)
        return {'s': s, 'x': x, 'z': z, 't': t}
    if len(data) in (NODE_LEN, NODE_LEN2):
        if len(data) == NODE_LEN2:
            s, x, z, t, rpm, torque, alarm, flags, avg_load = struct.unpack(NODE_FMT2, data)
        else:
            s, x, z, t, rpm, torque, alarm, flags = struct.unpack(NODE_FMT, data)
            avg_load = None
        return {'s': s, 'x': x, 'z': z, 't': t, 'rpm': rpm, 'torque': torque,
                'alarm': alarm, 'flags': flags, 'avg_load': avg_load,
                'online': bool(flags & F_ONLINE),
                'switch': 'fwd' if flags & F_FWD else ('rev' if flags & F_REV else 'neutral'),
                'enabled': bool(flags & F_ENABLED),
                'control': bool(flags & F_CONTROL),
                'cmd_ok': bool(flags & F_CMD_OK)}
    return None


class DroBle:
    def __init__(self, address=None, name_prefix='SERVOCOM-DRO'):
        self.address = address          # remembered board, or None to scan
        self.name_prefix = name_prefix
        self._lock = threading.Lock()
        self._latest = None
        self._last_rx = 0.0
        self.connected = False
        self.device_name = ''
        self.rssi = None
        self.frames = 0
        self.dropped = 0
        self.intervals = []             # last arrival gaps (s), for the bench
        self._stop = threading.Event()
        self._thread = None
        self._loop = None
        self._client = None
        self._ping_event = None
        self._ping_echo = None
        self.found = []                 # (address, name, rssi) from the last scan
        self.is_node = False            # True once a CMD characteristic is found
        self.params = {}                # drive parameter number -> signed value (from 'R'/'W' acks)
        self.params_ts = 0.0
        self.last_write = None          # (addr, value, ok, time)
        self.last_save = None           # (ok, time)
        self.node_version = ''          # from the 'I' ack
        self.ota_state = 'idle'         # idle / sending / verifying / done / failed
        self.ota_progress = 0.0
        self.ota_error = ''
        self._ota_ack = None            # (ok, got) from the last 'G' ack
        self.last_raw = None            # (ok, response pdu, time) from the last 'X' ack
        self.last_raw_ms = None         # drive response time of the last raw command, ms
        self._mon = None                # raw sample log file while /tmp/dromon exists
        self._raw_event = threading.Event()
        self._ota_event = None
        self.last_ack = None
        self.acks = 0
        self.cmds_sent = 0

    # ---- lifecycle ------------------------------------------------------
    def start(self):
        if BleakClient is None:
            log.warning('DRO BLE: bleak not available, reader disabled')
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='dro-ble', daemon=True)
            self._thread.start()
            log.info('DRO BLE reader started (address=%s)', self.address or 'scan')

    def stop(self):
        self._stop.set()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()

    # ---- central loop ---------------------------------------------------
    async def _find(self):
        devices = await BleakScanner.discover(timeout=4.0, return_adv=True,
                                              service_uuids=[SERVICE_UUID])
        found = []
        for dev, adv in devices.values():
            name = adv.local_name or dev.name or ''
            if SERVICE_UUID in (adv.service_uuids or []) or name.startswith(self.name_prefix):
                found.append((dev.address, name, adv.rssi))
        found.sort(key=lambda f: -(f[2] or -999))
        self.found = found
        return found

    async def _main(self):
        last_seq = None
        while not self._stop.is_set():
            target = self.address
            if target is None:
                found = await self._find()
                if not found:
                    await asyncio.sleep(1.0)
                    continue
                target = found[0][0]
                self.device_name = found[0][1]
                self.rssi = found[0][2]
                log.info('DRO BLE: found %s (%s, %s dBm)', target, self.device_name, self.rssi)
            try:
                async with BleakClient(target, timeout=8.0) as client:
                    self._client = client
                    self.connected = True
                    log.info('DRO BLE: connected to %s', target)
                    self._ping_event = asyncio.Event()

                    def on_data(_h, data):
                        sample = parse_packet(bytes(data))
                        if sample is None:
                            return
                        now = time.monotonic()
                        nonlocal last_seq
                        if last_seq is not None and sample['s'] > last_seq + 1:
                            self.dropped += sample['s'] - last_seq - 1
                        last_seq = sample['s']
                        self._monitor(sample, bytes(data))
                        with self._lock:
                            if self._last_rx:
                                self.intervals.append(now - self._last_rx)
                                if len(self.intervals) > 2000:
                                    del self.intervals[:1000]
                            self._latest = sample
                            self._last_rx = now
                            self.frames += 1

                    def on_ping(_h, data):
                        self._ping_echo = bytes(data)
                        self._ping_event.set()

                    await client.start_notify(DATA_UUID, on_data)
                    await client.start_notify(PING_UUID, on_ping)
                    self.is_node = False
                    try:
                        def on_ack(_h, data):
                            self.last_ack = bytes(data)
                            self.acks += 1
                            self._parse_ack(self.last_ack)
                        await client.start_notify(CMD_UUID, on_ack)
                        self.is_node = True
                        log.info('DRO BLE: machine node (command characteristic present)')
                        try:
                            await client.write_gatt_char(CMD_UUID, b'I', response=False)
                        except Exception:
                            pass
                    except Exception:
                        pass          # plain DRO tap: no CMD characteristic
                    await self._tune_interval(target)
                    while not self._stop.is_set() and client.is_connected:
                        await asyncio.sleep(0.2)
                    try:
                        await client.stop_notify(DATA_UUID)
                    except Exception:
                        pass
            except Exception as exc:
                log.warning('DRO BLE: %s (%s)', exc, target)
            finally:
                if self.connected:
                    log.info('DRO BLE: disconnected from %s', target)
                self.connected = False
                self._client = None
            await asyncio.sleep(1.0)

    # ---- connection interval -------------------------------------------
    # BlueZ creates the link at its 30-50 ms defaults whatever main.conf
    # says, so after connecting we ask the controller for a faster interval
    # with hcitool lecup (units of 1.25 ms).  Env DRO_BLE_INTERVAL="6,12"
    # overrides; empty disables.
    async def _tune_interval(self, address):
        import os
        import subprocess
        spec = os.environ.get('DRO_BLE_INTERVAL', '6,12')
        if not spec:
            return
        try:
            lo, hi = [int(v) for v in spec.split(',')]
            out = subprocess.run(['sudo', '-n', 'hcitool', 'con'], capture_output=True,
                                 text=True, timeout=3).stdout
            handle = None
            for line in out.splitlines():
                if address.upper() in line.upper() and 'handle' in line:
                    handle = int(line.split('handle')[1].split()[0])
            if handle is None:
                log.warning('DRO BLE: no handle for %s, interval left at default', address)
                return
            r = subprocess.run(['sudo', '-n', 'hcitool', 'lecup', '--handle', str(handle),
                                '--min', str(lo), '--max', str(hi), '--latency', '0',
                                '--timeout', '100'], capture_output=True, text=True, timeout=3)
            log.info('DRO BLE: connection update requested %d-%d x1.25ms (handle %d) rc=%s %s',
                     lo, hi, handle, r.returncode, (r.stdout + r.stderr).strip())
        except Exception as exc:
            log.warning('DRO BLE: interval tune failed: %s', exc)

    # ---- raw sample monitor (touch /tmp/dromon to start, remove to stop) -----
    MON_FLAG = '/tmp/dromon'
    MON_LOG = '/tmp/dromon.log'

    def _monitor(self, sample, raw):
        n = self.frames
        if n % 40 == 0 or self._mon is None:          # check the flag twice a second
            want = os.path.exists(self.MON_FLAG)
            if want and self._mon is None:
                try:
                    self._mon = open(self.MON_LOG, 'a')
                    self._mon.write('# %s start' % time.strftime('%H:%M:%S') + chr(10))
                except OSError:
                    self._mon = False
            elif not want and self._mon:
                self._mon.close()
                self._mon = None
        if not self._mon:
            return
        try:
            self._mon.write('%s %d x=%d z=%d rpm=%d tq=%d al=%d f=%02x d=%d raw=%s' % (
                time.strftime('%H:%M:%S'), sample['s'], sample['x'], sample['z'],
                sample.get('rpm', 0), sample.get('torque', 0), sample.get('alarm', 0),
                sample.get('flags', 0), self.dropped, raw.hex()) + chr(10))
            if n % 20 == 0:
                self._mon.flush()
        except OSError:
            pass

    # ---- reads ---------------------------------------------------------
    def latest(self):
        with self._lock:
            return self._latest

    @property
    def stale(self):
        with self._lock:
            return (time.monotonic() - self._last_rx) > STALE_S

    def feed(self, data):
        """Test hook: inject a packet as if it arrived over the air."""
        sample = parse_packet(data)
        if sample is not None:
            with self._lock:
                self._latest = sample
                self._last_rx = time.monotonic()
                self.frames += 1
        return sample

    # ---- machine-node commands ------------------------------------------
    def _parse_ack(self, data):
        """Ack layout: ok byte, command byte, payload (see firmware docstring)."""
        if len(data) < 2:
            return
        ok, cmd = data[0] == 1, data[1:2]
        try:
            if cmd == b'R' and len(data) >= 5:
                addr, count = struct.unpack('<HB', data[2:5])
                if ok and len(data) >= 5 + 2 * count:
                    vals = struct.unpack('<%dh' % count, data[5:5 + 2 * count])
                    for i, v in enumerate(vals):
                        self.params[addr + i] = v
                    self.params_ts = time.time()
            elif cmd == b'W' and len(data) >= 6:
                addr, value = struct.unpack('<Hh', data[2:6])
                self.last_write = (addr, value, ok, time.time())
                if ok:
                    self.params[addr] = value
                log.info('node param write Pr%03d = %d -> %s', addr, value, 'ok' if ok else 'REFUSED')
            elif cmd == b'V':
                self.last_save = (ok, time.time())
                log.info('node save to EEPROM -> %s', 'ok' if ok else 'REFUSED')
            elif cmd == b'I' and ok:
                self.node_version = data[2:].decode('utf-8', 'replace')
                log.info('node firmware: %s', self.node_version)
            elif cmd in (b'X', b'L', b'K'):
                self.last_raw = (ok, data[2:], time.time())
                if self._raw_event is not None:
                    self._raw_event.set()
            elif cmd in (b'F', b'G'):
                got = struct.unpack('<I', data[2:6])[0] if len(data) >= 6 else 0
                self._ota_ack = (ok, cmd, got)
                if self._ota_event is not None:
                    self._ota_event.set()
        except struct.error:
            pass

    # ---- diagnostics: raw Modbus PDU through the node ------------------------
    def raw_modbus(self, pdu, timeout=3.0):
        """Send function byte + data to the drive via the node; returns the
        response PDU bytes, or None.  Blocks the calling (non-BLE) thread."""
        self._raw_event.clear()
        self.last_raw = None
        if not self.send_cmd(b'X' + bytes(pdu)):
            return None
        if not self._raw_event.wait(timeout):
            return None
        ok, resp, _t = self.last_raw
        if len(resp) >= 2:                      # node 3.10+: response time first
            self.last_raw_ms = struct.unpack('<H', resp[:2])[0] / 10.0
            resp = resp[2:]
        return resp if ok else None

    def _ask(self, data, timeout=3.0):
        self._raw_event.clear()
        self.last_raw = None
        if not self.send_cmd(data) or not self._raw_event.wait(timeout):
            return None
        return self.last_raw

    def read_crash_log(self):
        """Fetch the node's crash.txt (written when its firmware died), or ''."""
        out = b''
        for off in range(40):
            res = self._ask(b'L' + bytes([off]))
            if res is None or not res[0] or not res[1]:
                break
            out += res[1]
            if len(res[1]) < 18:
                break
        return out.decode('utf-8', 'replace')

    def clear_crash_log(self):
        return bool(self._ask(b'K'))

    # ---- over-the-air firmware update -------------------------------------
    def ota_send(self, path):
        """Push a new node.py to the node (runs on the BLE loop).  Progress
        in ota_state / ota_progress; the node verifies the crc and resets."""
        if self._client is None or not self.connected or self._loop is None:
            return False
        if self.ota_state == 'sending':
            return False
        self.ota_state = 'sending'
        self.ota_progress = 0.0
        self.ota_error = ''
        asyncio.run_coroutine_threadsafe(self._ota(path), self._loop)
        return True

    async def _wait_ota_ack(self, want, timeout):
        try:
            await asyncio.wait_for(self._ota_event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        self._ota_event.clear()
        ack = self._ota_ack
        return ack if ack and ack[1] == want else None

    async def _ota(self, path):
        import zlib
        try:
            with open(path, 'rb') as fh:
                blob = fh.read()
            crc = zlib.crc32(blob) & 0xFFFFFFFF
            self._ota_event = asyncio.Event()
            client = self._client
            try:
                await client._acquire_mtu()          # BlueZ: ask for the real MTU
            except Exception:
                pass
            mtu = getattr(client, 'mtu_size', 23) or 23
            chunk = max(16, min(mtu - 4, 200))
            log.info('node OTA: %s, %d bytes, crc %08x, chunk %d', path, len(blob), crc, chunk)
            self._ota_event.clear()
            await client.write_gatt_char(CMD_UUID, b'F' + struct.pack('<II', len(blob), crc), response=True)
            ack = await self._wait_ota_ack(b'F', 3.0)
            if not ack or not ack[0]:
                raise RuntimeError('node refused the update start')
            sent = 0
            while sent < len(blob):
                piece = blob[sent:sent + chunk]
                await client.write_gatt_char(CMD_UUID, b'f' + piece, response=True)
                sent += len(piece)
                self.ota_progress = sent / float(len(blob))
            self.ota_state = 'verifying'
            self._ota_event.clear()
            await client.write_gatt_char(CMD_UUID, b'G', response=True)
            ack = await self._wait_ota_ack(b'G', 8.0)
            if not ack or not ack[0]:
                raise RuntimeError('node rejected the image (size/crc mismatch or drive enabled)')
            self.ota_state = 'done'
            log.info('node OTA: image accepted, node is resetting')
        except Exception as exc:
            self.ota_state = 'failed'
            self.ota_error = str(exc)
            log.error('node OTA failed: %s', exc)

    def send_cmd(self, data):
        """Fire-and-forget command to the node (b'E', b'D', b'C', b'S'+int16).
        Returns False if there is no connected node."""
        if self._client is None or not self.connected or self._loop is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(
                self._client.write_gatt_char(CMD_UUID, bytes(data), response=False), self._loop)
            self.cmds_sent += 1
            return True
        except Exception as exc:
            log.warning('DRO BLE: command failed: %s', exc)
            return False

    # ---- round-trip timing ------------------------------------------------
    async def _ping_once(self, token, timeout=1.0):
        self._ping_event.clear()
        self._ping_echo = None
        t0 = time.perf_counter()
        await self._client.write_gatt_char(PING_UUID, token, response=False)
        try:
            await asyncio.wait_for(self._ping_event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        if self._ping_echo != token:
            return None
        return time.perf_counter() - t0

    def ping(self, count=20, gap=0.1):
        """Blocking from another thread: list of RTTs in seconds (None = lost)."""
        results = []
        for i in range(count):
            if self._client is None or not self.connected:
                results.append(None)
                time.sleep(gap)
                continue
            token = struct.pack('<I', i + 1)
            fut = asyncio.run_coroutine_threadsafe(self._ping_once(token), self._loop)
            try:
                results.append(fut.result(timeout=2.0))
            except Exception:
                results.append(None)
            time.sleep(gap)
        return results
