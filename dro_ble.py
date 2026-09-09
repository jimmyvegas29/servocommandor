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

from applog import log

try:
    from bleak import BleakClient, BleakScanner
except ImportError:          # desktop without bleak
    BleakClient = BleakScanner = None

SERVICE_UUID = '5e7a0001-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
DATA_UUID = '5e7a0002-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
PING_UUID = '5e7a0003-8d2c-4b1e-9c3a-2f6d0a1b3c4d'
STALE_S = 0.5


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
    """bytes -> {'s','x','z','t'} or None."""
    if len(data) != 16:
        return None
    s, x, z, t = struct.unpack('<IiiI', data)
    return {'s': s, 'x': x, 'z': z, 't': t}


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
