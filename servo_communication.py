from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException
from time import sleep

###### COMMENT THIS OUT IF NOT USING PHYSICAL BUTTONS #####
from gpiozero import Button
###########################################################


class ServoCommunicator:
    def __init__(self, port='/dev/ttyS0', baudrate=9600, slave_id=1):
        self.client = ModbusSerialClient(
            port=port,
            baudrate=baudrate,
            parity='N',
            stopbits=1,
            timeout=1,
            retries=0
        )
        self.slave_id = slave_id
        self.servostate = 'disabled'

        ###### COMMENT OUT THIS SECTION IF NOT USING PHYSICAL BUTTONS #####
        self.enablebutton = Button(21, bounce_time=.1)
        self.enablebutton.when_pressed = self.enable_servo
        self.disablebutton = Button(13, bounce_time=.1)
        self.disablebutton.when_pressed = self.disable_servo
        ###################################################################

    def neg_speed(self, negativespeed):
        # Necessary to conver negative speed numbers
        payload = self.client.convert_to_registers(value=negativespeed, data_type=self.client.DATATYPE.INT16, word_order='big')
        return payload[0]

    def connect(self):
        return self.client.connect()

    def disconnect(self):
        self.client.close()

    def get_servo_state(self):
        return self.servostate

    def enable_servo(self):
        # 0x0062, value for enabled = 1
        self.client.write_register(0x0062, 1, device_id=self.slave_id)
        self.servostate = 'enabled'

    def disable_servo(self):
        # 0x0089, set speed to 0
        self.client.write_register(0x0089, 0, device_id=self.slave_id)
        # 0x0062, value for disable = 0
        self.client.write_register(0x0062, 0, device_id=self.slave_id)
        self.servostate = 'disabled'

    def set_speed(self, speed):
        # 0x0089 and accepts -3000 to +3000 for a value
        if speed < 0:
            speed = self.neg_speed(speed)
        self.client.write_register(0x0089, speed, device_id=self.slave_id)

    def get_rpm(self):
        # To read the current rpm of the servo motor from the drive the hex is 0x0000(when requested via 04H) and 0x1000(when requested via 03H)
        # Using 04H
        # To use 03H use self.client.read_holding_registers
        try:
            response = self.client.read_input_registers(0x0000, count=1, device_id=self.slave_id)
        except ModbusException as exc:
            print(exc)
            return(exec)
        if not response.isError():
            return response.registers[0]
        return None

