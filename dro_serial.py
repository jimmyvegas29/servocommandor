"""Reader for the lathe DRO tap board (RP2350 on USB serial).

The board streams raw scale counts 20 times a second:

    DRO X:<counts> Z:<counts> S:<seq> T:<ms>

A background thread keeps the latest sample; the GUI polls `latest()` and
never blocks on the port.  The port is reopened on its own if the board is
unplugged or re-enumerates, and `stale` goes True when nothing has arrived
for STALE_S so the screen can show the reading is not live.
"""
import glob
import os
import threading
import time

from applog import log

try:
    import serial
except ImportError:          # desktop without pyserial: reader stays idle
    serial = None

STALE_S = 0.5


def parse_line(line):
    """'DRO X:123 Z:-45 S:7 T:99' -> {'x': 123, 'z': -45, 's': 7, 't': 99}
    or None for anything else (boot banner, garbage)."""
    if not line.startswith('DRO '):
        return None
    out = {}
    try:
        for tok in line.split()[1:]:
            key, val = tok.split(':', 1)
            out[key.lower()] = int(val)
        if 'x' in out and 'z' in out:
            return out
    except ValueError:
        pass
    return None


class DroSerial:
    def __init__(self, port='/dev/ttyACM0', baud=115200):
        self.port_pattern = port
        self.baud = baud
        self._lock = threading.Lock()
        self._latest = None          # last parsed sample
        self._last_rx = 0.0
        self.connected = False
        self.frames = 0
        self.dropped = 0
        self._stop = threading.Event()
        self._thread = None

    # ---- lifecycle ------------------------------------------------------
    def start(self):
        if serial is None:
            log.warning('DRO serial: pyserial not available, reader disabled')
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name='dro-serial', daemon=True)
            self._thread.start()
            log.info('DRO serial reader started (port=%s)', self.port_pattern)

    def stop(self):
        self._stop.set()

    def _find_port(self):
        if os.path.exists(self.port_pattern):
            return self.port_pattern
        hits = sorted(glob.glob(self.port_pattern)) if any(c in self.port_pattern for c in '*?') else []
        return hits[0] if hits else None

    def _loop(self):
        last_seq = None
        while not self._stop.is_set():
            port = self._find_port()
            if port is None:
                self.connected = False
                self._stop.wait(1.0)
                continue
            try:
                with serial.Serial(port, self.baud, timeout=1) as ser:
                    log.info('DRO serial: connected on %s', port)
                    self.connected = True
                    while not self._stop.is_set():
                        raw = ser.readline()
                        if not raw:
                            continue
                        sample = parse_line(raw.decode('ascii', 'replace').strip())
                        if sample is None:
                            continue
                        if last_seq is not None and sample.get('s', 0) > last_seq + 1:
                            self.dropped += sample['s'] - last_seq - 1
                        last_seq = sample.get('s')
                        with self._lock:
                            self._latest = sample
                            self._last_rx = time.monotonic()
                            self.frames += 1
            except Exception as exc:
                if self.connected:
                    log.warning('DRO serial: lost %s (%s)', port, exc)
                self.connected = False
                self._stop.wait(1.0)

    # ---- reads ---------------------------------------------------------
    def latest(self):
        with self._lock:
            return self._latest

    @property
    def stale(self):
        with self._lock:
            return (time.monotonic() - self._last_rx) > STALE_S

    def feed(self, line):
        """Test hook: push a line as if it came from the board."""
        sample = parse_line(line)
        if sample is not None:
            with self._lock:
                self._latest = sample
                self._last_rx = time.monotonic()
                self.frames += 1
        return sample
