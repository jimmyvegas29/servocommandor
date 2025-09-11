from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.modalview import ModalView
from kivy.clock import Clock
from mock_servo_communication import ServoCommunicator


class NumberPadPopup(ModalView):
    def __init__(self, **kwargs):
        super(NumberPadPopup, self).__init__(**kwargs)

    def add_digit(self, digit):
        self.ids.numpad_display.text += digit

    def clear_display(self):
        self.ids.numpad_display.text = ''

    def delete_digit(self):
        self.ids.numpad_display.text = self.ids.numpad_display.text[:-1]

    def submit_value(self):
        try:
            value = int(self.ids.numpad_display.text)
            App.get_running_app().root.set_speed(value)
            self.dismiss()
        except ValueError:
            self.ids.numpad_display.text = 'Invalid Input'


class ServoControl(BoxLayout):
    current_speed = NumericProperty(50)
    direction = StringProperty('fwd')

    def set_speed(self, speed):
        self.current_speed = speed
        if self.direction == 'rev':
            App.get_running_app().servo.set_speed(-self.current_speed)
        else:
            App.get_running_app().servo.set_speed(self.current_speed)
        print(f"Set speed to: {self.current_speed}")

    def adjust_speed(self, amount):
        self.current_speed += amount
        if self.current_speed > 3000:
            self.current_speed = 3000
        if self.current_speed < 0:
            self.current_speed = 0
        if self.direction == 'rev':
            App.get_running_app().servo.set_speed(-self.current_speed)
        else:
            App.get_running_app().servo.set_speed(self.current_speed)
        print(f"Adjust speed by: {amount}")

    def show_custom_numpad(self):
        popup = NumberPadPopup()
        popup.open()

    def toggle_direction(self, direction):
        self.direction = direction
        if self.direction == 'fwd':
            self.ids.fwd_button.background_color = (0, 0.5, 1, 1)
            self.ids.rev_button.background_color = (0.3, 0.3, 0.3, 1)
        else:
            self.ids.fwd_button.background_color = (0.3, 0.3, 0.3, 1)
            self.ids.rev_button.background_color = (0, 0.5, 1, 1)
        print(f"Toggle direction to: {self.direction}")

    def update_rpm_display(self):
        rpm_str = str(int(self.current_speed)).zfill(4)
        print(self.ids)
        self.ids.rpm_digit_1.text = rpm_str[0]
        self.ids.rpm_digit_2.text = rpm_str[1]
        self.ids.rpm_digit_3.text = rpm_str[2]
        self.ids.rpm_digit_4.text = rpm_str[3]

        if self.current_speed < 1000:
            self.ids.rpm_digit_1.color = (0.5, 0.5, 0.5, 1)
        else:
            self.ids.rpm_digit_1.color = (1, 1, 1, 1)
        if self.current_speed < 100:
            self.ids.rpm_digit_2.color = (0.5, 0.5, 0.5, 1)
        else:
            self.ids.rpm_digit_2.color = (1, 1, 1, 1)
        if self.current_speed < 10:
            self.ids.rpm_digit_3.color = (0.5, 0.5, 0.5, 1)
        else:
            self.ids.rpm_digit_3.color = (1, 1, 1, 1)


class ServoApp(App):
    def build(self):
        self.servo = ServoCommunicator()
        self.servo.connect()
        root = ServoControl()
        Clock.schedule_interval(lambda dt: self.update_rpm(root, dt), 0.1)
        return root

    def on_stop(self):
        self.servo.disconnect()

    def update_rpm(self, root, dt):
        rpm = self.servo.get_rpm()
        if rpm is not None:
            root.current_speed = rpm
            root.update_rpm_display()


if __name__ == '__main__':
    ServoApp().run()