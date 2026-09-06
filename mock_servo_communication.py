"""Stand-in for ServoCommunicator so the GUI runs on a desk without the
drive (SERVOCOM_MOCK=1).  Simulates rpm ramping to the commanded speed and a
plausible load % while enabled, so the readouts and graph can be checked."""
import random
import time

###### UNCOMMENT IF YOU WANT TO TEST PHYSICAL BUTTONS ######
try:
    from gpiozero import Button
except ImportError:      # desktop without gpiozero
    Button = None
############################################################

class ServoCommunicator:
    def __init__(self, port='COM3', baudrate=9600, slave_id=1, invert_direction=False):
        self.rpm = 0
        self.alarmcode = 0
        self.servostate = 'disabled'
        self.invert_direction = invert_direction
        self._actual = 0.0          # simulated motor speed (rpm, signed)
        self._last = time.time()
        self.hw_direction = None
        self.offline = False        # set True to exercise the offline overlay
        ###### UNCOMMENT IF YOU WANT TO TEST PHYSICAL BUTTONS ######
        # self.enablebutton = Button(21, bounce_time=.1)
        # self.enablebutton.when_pressed = self.enable_servo
        # self.disablebutton = Button(13, bounce_time=.1)
        # self.disablebutton.when_pressed = self.disable_servo
        ############################################################

    def get_servo_state(self):
        return self.servostate

    def start_polling(self, interval=0.25):
        print("Mock polling started")

    def get_hw_direction(self):
        return self.hw_direction

    def _step(self):
        # ramp the simulated speed toward the command at ~1500 rpm/s
        now = time.time()
        dt = min(0.5, now - self._last)
        self._last = now
        target = float(self.rpm) if self.servostate == 'enabled' else 0.0
        delta = target - self._actual
        step = 1500.0 * dt
        if abs(delta) <= step:
            self._actual = target
        else:
            self._actual += step if delta > 0 else -step

    def connect(self):
        print("Mock servo connected")
        return True

    def disconnect(self):
        print("Mock servo disconnected")

    def enable_servo(self):
        self.servostate = 'enabled'
        print("Mock servo enabled")

    def disable_servo(self):
        self.servostate = 'disabled'
        print("Mock servo disabled")

    def set_speed(self, speed):
        self.rpm = speed
        print(f"Mock servo speed set to {speed}")

    def get_rpm(self):
        # same shape as the real one: [alarm_code, speed in 0.1 rpm] with the
        # drive's 16-bit two's-complement for negative speeds, or None offline
        if self.offline:
            return None
        self._step()
        tenths = int(round(self._actual * 10))
        if tenths < 0:
            tenths = 65536 + tenths
        return [self.alarmcode, tenths]

    def get_torque(self):
        if self.offline:
            return None
        self._step()
        if self.servostate != 'enabled' or abs(self._actual) < 1:
            return 0
        load = 20 + abs(self._actual) / 100.0 + random.uniform(-3, 3)
        return int(load)

    def get_alarm(self):
        return self.alarmcode

    def clear_alarm(self):
        self.alarmcode = 0
