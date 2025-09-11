from pymodbus.client import ModbusSerialClient

class ServoCommunicator:
    def __init__(self, port='COM3', baudrate=9600, slave_id=1):
        self.client = ModbusSerialClient(
            method='rtu',
            port=port,
            baudrate=baudrate,
            parity='N',
            stopbits=1,
            timeout=1
        )
        self.slave_id = slave_id

    def connect(self):
        return self.client.connect()

    def disconnect(self):
        self.client.close()

    def enable_servo(self):
        # 0x0062, value for enabled = 1
        self.client.write_register(0x0062, 1, unit=self.slave_id)

    def disable_servo(self):
        # 0x0062, value for disable = 0
        self.client.write_register(0x0062, 0, unit=self.slave_id)

    def set_speed(self, speed):
        # 0x0089 and accepts -3000 to +3000 for a value
        self.client.write_register(0x0089, speed, unit=self.slave_id)

    def get_rpm(self):
        # To read the current rpm of the servo motor from the drive the hex is 0x0000(when requested via 04H) and 0x1000(when requested via 03H)
        # Using 03H
        response = self.client.read_holding_registers(0x1000, 1, unit=self.slave_id)
        if not response.isError():
            return response.registers[0]
        return None
