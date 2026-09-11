from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ModbusPDU
import threading

from applog import log

###### COMMENT THIS OUT IF NOT USING THE PHYSICAL FWD/OFF/REV SWITCH #####
from gpiozero import Button
##########################################################################

# Physical FWD/OFF/REV rotary switch wiring - one 3-pin dupont block on
# consecutive header pins (as actually wired on the lathe):
#   physical pin 14 = GND    -> switch common
#   physical pin 16 = GPIO23 -> REV contact
#   physical pin 18 = GPIO24 -> FWD contact
# The switch is maintained (rotary), not momentary: FWD/REV positions hold
# their contact closed to GND until the switch is moved.
# Note: works together with [Hardware] invert_direction=true in servo.ini -
# the drive's negative speed direction is the lathe's forward.
FWD_GPIO = 24
REV_GPIO = 23


class ClearAlarmRequest(ModbusPDU):
    """ Custom request for Modbus function 0x43 (Clear Alarm). """
    function_code = 0x43

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def encode(self):
        return b''

    def decode(self, data):
        pass


class ServoCommunicator:
    def __init__(self, port='/dev/ttyS0', baudrate=9600, slave_id=1, invert_direction=False):
        self.client = ModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity='N',
            stopbits=1,
            timeout=0.4,
            retries=0,
        )
        self.slave_id = slave_id
        self.servostate = 'disabled'
        self.invert_direction = invert_direction
        self.hw_direction = None    # 'fwd'/'rev' as demanded by the physical switch
        self._last_speed = 0        # last signed speed commanded (before inversion)
        # One RS-485 transaction at a time: the poller thread, the GUI thread
        # and the gpiozero callback threads all share this client.
        self._lock = threading.Lock()
        self._cache = {'ok': False, 'torque': None, 'alarm': None, 'rpm': None}
        self._poll_thread = None
        self._poll_stop = threading.Event()

        ###### COMMENT OUT THIS SECTION IF NOT USING THE PHYSICAL SWITCH #####
        # FWD or REV position -> set direction, apply speed, enable.
        # Neutral (center off) -> disable.
        # The switch is POLLED as a state machine (20Hz, two matching samples
        # before acting) instead of using gpiozero edge callbacks - the
        # lgpio debounce on Bookworm can swallow release edges, which made
        # neutral/direction changes unreliable. Polling reads the live pin
        # level every cycle so no edge can ever be missed.
        # Safety interlock: if the switch is already in FWD/REV at boot it is
        # ignored until it passes through neutral once, so powering the system
        # up with the switch left engaged cannot start the motor.
        self.fwdswitch = Button(FWD_GPIO)
        self.revswitch = Button(REV_GPIO)
        self._switch_armed = self._read_switch() == 'neutral'
        self._switch_state = 'neutral'
        self._switch_thread = threading.Thread(
            target=self._switch_loop, name='switch-poll', daemon=True)
        self._switch_thread.start()
        log.info('Switch init: position=%s armed=%s (FWD=GPIO%d REV=GPIO%d)',
                 self._read_switch(), self._switch_armed, FWD_GPIO, REV_GPIO)
        ######################################################################
        log.info('ServoCommunicator init: port=%s baud=%s slave=%s invert_direction=%s',
                 port, baudrate, slave_id, invert_direction)

    def neg_speed(self, negativespeed):
        # Necessary to conver negative speed numbers
        payload = self.client.convert_to_registers(value=negativespeed, data_type=self.client.DATATYPE.INT16, word_order='big')
        return payload[0]

    def connect(self):
        ok = self.client.connect()
        if ok:
            # the original app did this at startup: never trust a setpoint
            # left in the drive from before the power cycle
            self._write(0x0089, 0)
            self._write(0x0062, 0)
        return ok

    def disconnect(self):
        self._poll_stop.set()
        self.client.close()

    # ---------------- polling (background thread) ----------------

    def start_polling(self, interval=0.25):
        if self._poll_thread is None:
            self._poll_thread = threading.Thread(
                target=self._poll_loop, args=(interval,),
                name='modbus-poll', daemon=True)
            self._poll_thread.start()
            log.info('Modbus poller started (interval=%.2fs)', interval)

    def _poll_loop(self, interval):
        # One bulk read per cycle covers everything the GUI shows:
        # 0x0009 torque %, 0x001A alarm code, 0x001B speed in 0.1 r/min.
        # The GUI reads the cached result and never blocks on the serial line.
        # Online/offline transitions are logged once, not every cycle.
        last_ok = None
        while not self._poll_stop.is_set():
            reason = ''
            try:
                with self._lock:
                    response = self.client.read_input_registers(0x0009, count=19, device_id=self.slave_id)
                if not response.isError():
                    regs = response.registers
                    self._cache = {'ok': True, 'torque': regs[0],
                                   'alarm': regs[17], 'rpm': regs[18]}
                else:
                    reason = str(response)
                    self._cache = {'ok': False, 'torque': None, 'alarm': None, 'rpm': None}
            except Exception as exc:
                reason = str(exc)
                self._cache = {'ok': False, 'torque': None, 'alarm': None, 'rpm': None}
            ok = self._cache['ok']
            if ok != last_ok:
                if ok:
                    log.info('Drive ONLINE (torque=%s alarm=%s rpm=%s)',
                             self._cache['torque'], self._cache['alarm'], self._cache['rpm'])
                else:
                    log.warning('Drive OFFLINE: %s', reason)
                last_ok = ok
            self._poll_stop.wait(interval)

    # ---------------- cached reads (never block the GUI) ----------------

    def get_rpm(self):
        # Same shape as the old blocking read: [alarm_code, speed_0.1rpm],
        # or None when the drive is offline.
        cache = self._cache
        if cache['ok']:
            return [cache['alarm'], cache['rpm']]
        return None

    def get_torque(self):
        cache = self._cache
        return cache['torque'] if cache['ok'] else None

    def get_alarm(self):
        cache = self._cache
        return cache['alarm'] if cache['ok'] else None

    def get_servo_state(self):
        return self.servostate

    def get_hw_direction(self):
        return self.hw_direction

    # ---------------- writes (locked, never crash the caller) ----------------

    def _write(self, address, value):
        try:
            with self._lock:
                self.client.write_register(address, value, device_id=self.slave_id)
            log.debug('Modbus write 0x%04X = %s OK', address, value)
            return True
        except Exception as exc:
            log.error('Modbus write 0x%04X = %s FAILED: %s', address, value, exc)
            return False

    def enable_servo(self):
        # 0x0062, value for enabled = 1
        log.info('enable_servo')
        self._write(0x0062, 1)
        self.servostate = 'enabled'

    def disable_servo(self):
        # 0x0062, value for disable = 0
        log.info('disable_servo')
        self._write(0x0062, 0)
        self.servostate = 'disabled'

    def set_speed(self, speed):
        # 0x0089 and accepts -3000 to +3000 for a value.
        # invert_direction flips the sign at this single choke point, so if
        # the lathe runs backwards vs the FWD/REV labels, fix it in servo.ini
        # ([Hardware] invert_direction) instead of touching drive parameters.
        self._last_speed = speed
        if self.invert_direction:
            speed = -speed
        log.info('set_speed: commanded=%s on-wire=%s (invert=%s)',
                 self._last_speed, speed, self.invert_direction)
        if speed < 0:
            speed = self.neg_speed(speed)
        self._write(0x0089, speed)

    def clear_alarm(self):
        #Sends a custom Modbus command 0x43 to clear alarms on the servo drive.
        log.info('clear_alarm (function 0x43)')
        request = ClearAlarmRequest(dev_id=self.slave_id)
        try:
            with self._lock:
                response = self.client.execute(True, request)
            return True
        except ModbusException as exc:
            log.error('clear_alarm FAILED: %s', exc)
            return False

    # ---------------- physical FWD/OFF/REV switch ----------------

    def _apply_switch_speed(self):
        # Re-issue the last commanded speed with the sign the switch demands,
        # so the drive is already pointing the right way when it enables.
        magnitude = abs(self._last_speed)
        self.set_speed(-magnitude if self.hw_direction == 'rev' else magnitude)

    def _read_switch(self):
        fwd = self.fwdswitch.is_pressed
        rev = self.revswitch.is_pressed
        if fwd and not rev:
            return 'fwd'
        if rev and not fwd:
            return 'rev'
        # neutral (or both contacts closed, which shouldn't happen)
        return 'neutral'

    def _switch_loop(self):
        last_read = self._read_switch()
        while not self._poll_stop.is_set():
            current = self._read_switch()
            # act only on a position that held for two consecutive samples
            if current == last_read:
                if not self._switch_armed:
                    # boot interlock: wait for one pass through neutral
                    if current == 'neutral':
                        self._switch_armed = True
                        self._switch_state = 'neutral'
                        log.info('Switch interlock armed (passed through neutral)')
                elif current != self._switch_state:
                    self._switch_state = current
                    log.info('Switch position: %s (fwd_pin=%s rev_pin=%s)',
                             current, self.fwdswitch.is_pressed, self.revswitch.is_pressed)
                    if current == 'fwd':
                        self.hw_direction = 'fwd'
                        self._apply_switch_speed()
                        self.enable_servo()
                    elif current == 'rev':
                        self.hw_direction = 'rev'
                        self._apply_switch_speed()
                        self.enable_servo()
                    else:
                        self.disable_servo()
            last_read = current
            self._poll_stop.wait(0.05)
