class ServoCommunicator:
    def __init__(self, port='COM3', baudrate=9600, slave_id=1):
        self.rpm = 0
        self.enabled = False

    def connect(self):
        print("Mock servo connected")
        return True

    def disconnect(self):
        print("Mock servo disconnected")

    def enable_servo(self):
        self.enabled = True
        print("Mock servo enabled")

    def disable_servo(self):
        self.enabled = False
        print("Mock servo disabled")

    def set_speed(self, speed):
        self.rpm = speed
        print(f"Mock servo speed set to {speed}")

    def get_rpm(self):
        return self.rpm
