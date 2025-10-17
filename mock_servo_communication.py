###### UNCOMMENT IF YOU WANT TO TEST PHYSICAL BUTTONS ######
from gpiozero import Button
############################################################

class ServoCommunicator:
    def __init__(self, port='COM3', baudrate=9600, slave_id=1):
        self.rpm = 0
        self.alarmcode = 0
        self.servostate = 'disabled'
        ###### UNCOMMENT IF YOU WANT TO TEST PHYSICAL BUTTONS ######
        # self.enablebutton = Button(21, bounce_time=.1)
        # self.enablebutton.when_pressed = self.enable_servo
        # self.disablebutton = Button(13, bounce_time=.1)
        # self.disablebutton.when_pressed = self.disable_servo
        ############################################################

    def get_servo_state(self):
        return self.servostate

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
        return [self.alarmcode, self.rpm]

    def get_torque(self):
        return 0

    def get_alarm(self):
        return self.alarmcode

    def clear_alarm(self):
        self.alarmcode = 0
