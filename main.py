from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.modalview import ModalView
from kivy.clock import Clock
from mock_servo_communication import ServoCommunicator
from kivy.core.window import Window
from kivy.lang import Builder
from decimal import Decimal

###### UNCOMMENT FOR USE WITH 800x480 SCREENS ######
#Builder.load_file("Servo.kv") #uncomment for use with 800x480 Screens
#Window.size = (800, 480) #uncomment for use with 800x480 Screens
####################################################

###### UNCOMMENT FOR USE WITH 800x480 SCREENS ######
Builder.load_file('Servo_reterm.kv') #uncomment for use with Seedd reTerminal 1280x720
Window.size = (1280, 720) #uncomment for use with Seedd reTerminal 1280x720
####################################################

Window.borderless = True
Window.fullscreen = True
Window.show_cursor = False

class NumberPadPopup(ModalView):
    def __init__(self, **kwargs):
        super(NumberPadPopup, self).__init__(**kwargs)

    def add_digit(self, digit):
        if self.ids.numpad_display.text == 'Invalid Input':
            self.ids.numpad_display.text = ''
        self.ids.numpad_display.text += digit
        if int(self.ids.numpad_display.text) > 3000:
            self.ids.numpad_display.color = (1,0,0,1)

    def clear_display(self):
        self.ids.numpad_display.text = ''
        self.ids.numpad_display.color = (1,1,1,1)

    def delete_digit(self):
        self.ids.numpad_display.text = self.ids.numpad_display.text[:-1]
        if self.ids.numpad_display.text != '' and int(self.ids.numpad_display.text) < 3000:
            self.ids.numpad_display.color = (1,1,1,1)

    def submit_value(self):
        try:
            value = int(self.ids.numpad_display.text)
            if int(self.ids.numpad_display.text) == 999999:
                App.get_running_app().stop()
            if int(self.ids.numpad_display.text) > 3000:
                self.ids.numpad_display.color = (1,0,0,1)
            else:
                App.get_running_app().root.set_speed(value)
                self.dismiss()
        except ValueError:
            self.ids.numpad_display.text = 'Invalid Input'

class OfflinePopup(ModalView):
    def __init__(self, **kwargs):
        super(OfflinePopup, self).__init__(**kwargs)

class ServoControl(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_speed = NumericProperty(50)
        self.command_speed = NumericProperty(0)
        self.direction = StringProperty('fwd')
        self.servo_state = StringProperty('disabled')
        self.cfg = dict(App.get_running_app().config.items('Settings'))
        self.mode = self.cfg['mode']
        self.max_rpm = int(self.cfg['servo_max_rpm'])
        self.unit = self.cfg['unit']
        self.ratio = float(self.cfg['ratio'])
        self.diameter = float(self.cfg['diameter'])
        print(self.max_rpm)


    def rpm_convert(self, surface_speed):
        rpm = (surface_speed * 1000)/(3.14159 * self.diameter)
        servo_rpm = rpm * self.ratio
        return servo_rpm

    def sfm_convert(self, servo_rpm):
        output_rpm = servo_rpm/self.ratio
        sfm = (3.14159 * output_rpm * self.diameter)/1000
        return sfm

    def set_speed(self, speed):
        if self.mode == 'rpm':
            self.command_speed = round(speed*self.ratio)
        elif self.mode == 'surface_speed':
            self.command_speed = round(self.rpm_convert(speed))

        if self.direction == 'rev':
            App.get_running_app().servo.set_speed(-self.command_speed)
        else:
            App.get_running_app().servo.set_speed(self.command_speed)
        print(f"Set speed to: {self.command_speed}")

    def adjust_speed(self, amount):
        if self.mode == 'rpm':
            self.command_speed += round(amount*self.ratio)
        elif self.mode == 'surface_speed':
            self.command_speed += round(self.rpm_convert(amount))
        if self.command_speed > self.max_rpm:
            self.command_speed = self.max_rpm
        if self.command_speed < 0:
            self.command_speed = 0
        if self.direction == 'rev':
            App.get_running_app().servo.set_speed(-self.command_speed)
        else:
            App.get_running_app().servo.set_speed(self.command_speed)
        print(f"Adjust speed by: {amount}") 

    def show_custom_numpad(self):
        popup = NumberPadPopup()
        popup.open()

    def toggle_direction(self, direction):
        if direction != self.direction: 
            App.get_running_app().servo.set_speed(0) #When switching directions it will bring the bring the servo speed down to 0

        self.direction = direction

        if self.direction == 'fwd':
            self.ids.fwd_button.text = 'FORWARD'
        elif self.direction == 'rev':
            self.ids.fwd_button.text = 'REVERSE'
        print(f"Toggle direction to: {self.direction}")

    def toggle_enable(self, servo_state):
        self.servo_state = servo_state

        if self.servo_state == 'enabled':
            self.ids.servo_button.state = 'normal'
            self.ids.servo_button.text = 'ENABLED'
            App.get_running_app().servo.enable_servo()
        elif self.servo_state == 'disabled':
            self.ids.servo_button.state = 'down'
            self.ids.servo_button.text = 'DISABLED'
            App.get_running_app().servo.disable_servo()
        print(f"Servo State Changed To: {self.servo_state}")

    def update_rpm_display(self):
        if self.mode == 'rpm':
            self.display_speed = round(self.current_speed/self.ratio)
        elif self.mode == 'surface_speed':
            self.display_speed = round(self.sfm_convert(self.current_speed))
        rpm_str = str(int(self.display_speed)).zfill(4)
        self.ids.rpm_digit_1.text = rpm_str[0]
        self.ids.rpm_digit_2.text = rpm_str[1]
        self.ids.rpm_digit_3.text = rpm_str[2]
        self.ids.rpm_digit_4.text = rpm_str[3]

        if self.current_speed < 1000:
            self.ids.rpm_digit_1.color = (0.13, 0.13, 0.13, 1)
        else:
            self.ids.rpm_digit_1.color = (1, 1, 1, 1)
        if self.current_speed < 100:
            self.ids.rpm_digit_2.color = (0.13, 0.13, 0.13, 1)
        else:
            self.ids.rpm_digit_2.color = (1, 1, 1, 1)
        if self.current_speed < 10:
            self.ids.rpm_digit_3.color = (0.13, 0.13, 0.13, 1)
        else:
            self.ids.rpm_digit_3.color = (1, 1, 1, 1)


class ServoApp(App):
    offline_flag = False

    def get_application_config(self):
        return super(ServoApp, self).get_application_config('servo.ini')

    def build_config(self, config):
        # This function is necessary to load custom ini file. 
        config.setdefaults('settings', {'general': True})

    def build(self):
        self.servo = ServoCommunicator()
        self.offline = OfflinePopup()
        root = ServoControl()
        Window.bind(on_key_down=self.on_keyboard_down)
        Clock.schedule_interval(lambda dt: self.update_rpm(root, dt), 0.3)
        Clock.schedule_once(lambda dt: self.set_config(root, dt))
        return root

    def set_config(self, root, dt):
        settings = dict(App.get_running_app().config.items('Settings'))
        sp_btn = dict(App.get_running_app().config.items(settings['mode']))
        ids_dict = self.root.ids
        for k, v in sp_btn.items():
            getattr(ids_dict, k).text = v
        if settings['mode'] == 'surface_speed':
            if settings['unit'] == 'inch':
                self.root.ids.servo_mode.text = 'S.F.M.'
            elif settings['unit'] == 'metric':
                self.root.ids.servo_mode.text = 'S.M.M.'

    def update_rpm(self, root, dt):
        get_state = self.servo.get_servo_state()
        if get_state != root.servo_state:
            root.toggle_enable(get_state)
        rpm = self.servo.get_rpm()
        if isinstance(rpm, int):
            if self.offline_flag:
                self.offline.dismiss()
                self.offline_flag = False
            if rpm > 3000:
                rpm = 65536 - rpm
            if rpm is not None:
                root.current_speed = abs(rpm)
                root.update_rpm_display()
        else:
            if not self.offline_flag:
                self.offline.open()
                self.offline_flag = True
                print("Servo Drive Offline")

    def on_keyboard_down(self, window, keycode, scancode, text, modifiers):
        key_name = text

        if key_name == 'a':
            self.root.toggle_enable('enabled')
            return True

        if key_name == 's':
            self.root.toggle_enable('disabled')
            return True

        if key_name == 'd':
            if self.root.ids.fwd_button.text != 'FORWARD':
                self.root.toggle_direction('fwd')
                return True

        if key_name == 'f':
            if self.root.ids.fwd_button.text != 'REVERSE':
                self.root.toggle_direction('rev')
                return True

        return False

if __name__ == '__main__':
    ServoApp().run()
