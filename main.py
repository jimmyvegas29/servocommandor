from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.modalview import ModalView
from kivy.clock import Clock
from mock_servo_communication import ServoCommunicator
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import ObjectProperty
from kivy_garden.graph import MeshLinePlot, LinePlot, SmoothLinePlot
import subprocess
import os


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
            if str(value)[0:3] == '999' and len(str(value)) == 6:
                self.the_backdoor(value)
            if int(self.ids.numpad_display.text) > 3000:
                self.ids.numpad_display.color = (1,0,0,1)
            else:
                App.get_running_app().root.set_speed(value)
                self.dismiss()
        except ValueError:
            self.ids.numpad_display.text = 'Invalid Input'

    def the_backdoor(self, value):
        app = App.get_running_app()
        if int(value) == 999999: #disabled the servo and shuts down just the application
            if hasattr(app, 'servo') and app.servo:
                app.servo.disable_servo()
            app.stop()
        if int(value) == 999123: #disables the servo and shuts down the application as well as the rpi
            if hasattr(app, 'servo') and app.servo:
                app.servo.disable_servo()
            shutdown_path = os.path.expanduser("~/servocommandor/shutdown_root.sh")
            subprocess.call(["sudo", shutdown_path, "poweroff"])
        if int(value) == 999124: #disables the servo and restarts the rpi
            if hasattr(app, 'servo') and app.servo:
                app.servo.disable_servo()
            shutdown_path = os.path.expanduser("~/servocommandor/shutdown_root.sh")
            subprocess.call(["sudo", shutdown_path, "reboot"])


class OfflinePopup(ModalView):
    def __init__(self, **kwargs):
        super(OfflinePopup, self).__init__(**kwargs)

class ServoControl(BoxLayout):
    current_torque = NumericProperty(0)
    current_speed = NumericProperty(0)
    command_speed = NumericProperty(0)
    temp_plot = ObjectProperty(LinePlot(color=[0, 0.5, 1, 1], line_width=1.5))
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        unit_conversion = {'inch': 12, 'metric': 1000}
        self.direction = StringProperty('fwd')
        self.servo_state = StringProperty('disabled')
        self.cfg = dict(App.get_running_app().config.items('Settings'))
        self.mode = self.cfg['mode']
        self.max_rpm = int(self.cfg['servo_max_rpm'])
        self.unit = self.cfg['unit']
        self.ratio = float(self.cfg['ratio'])
        self.diameter = float(self.cfg['diameter'])
        self.unit_div = unit_conversion[self.unit]
        self.data_time = 0.0
        self.data_list = []

    def rpm_convert(self, surface_speed):
        rpm = (surface_speed * self.unit_div)/(3.14159 * self.diameter)
        servo_rpm = rpm * self.ratio
        return servo_rpm

    def ss_convert(self, servo_rpm):
        output_rpm = servo_rpm/self.ratio
        ss = (3.14159 * output_rpm * self.diameter)/self.unit_div
        return ss

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
            self.display_speed = round(self.ss_convert(self.current_speed))
        rpm_str = str(int(self.display_speed)).zfill(4)
        self.ids.rpm_digit_1.text = rpm_str[0]
        self.ids.rpm_digit_2.text = rpm_str[1]
        self.ids.rpm_digit_3.text = rpm_str[2]
        self.ids.rpm_digit_4.text = rpm_str[3]

        if self.display_speed < 1000:
            self.ids.rpm_digit_1.color = (0.13, 0.13, 0.13, 1)
        else:
            print(self.current_speed)
            self.ids.rpm_digit_1.color = (1, 1, 1, 1)
        if self.display_speed < 100:
            self.ids.rpm_digit_2.color = (0.13, 0.13, 0.13, 1)
        else:
            self.ids.rpm_digit_2.color = (1, 1, 1, 1)
        if self.display_speed < 10:
            self.ids.rpm_digit_3.color = (0.13, 0.13, 0.13, 1)
        else:
            self.ids.rpm_digit_3.color = (1, 1, 1, 1)

    def update_torque_display(self):
        #import random
        #new_temp = random.uniform(5, 90)
        self.display_torque = self.current_torque
        torque_str = str(int(abs(self.display_torque))).zfill(3)
        self.ids.torque_digit_1.text = torque_str[0]
        self.ids.torque_digit_2.text = torque_str[1]
        self.ids.torque_digit_3.text = torque_str[2]
        if self.display_torque < 100:
            self.ids.torque_digit_1.color = (0.13, 0.13, 0.13, 1)
        elif self.display_torque < 0:
            self.ids.torque_digit_1.color = (1, 0, 0, 1)
        else:
            self.ids.torque_digit_1.color = (1, 1, 1, 1)
        if self.display_torque < 10:
            self.ids.torque_digit_2.color = (0.13, 0.13, 0.13, 1)
        elif self.display_torque < 0:
            self.ids.torque_digit_2.color = (1, 0, 0, 1)
        else:
            self.ids.torque_digit_2.color = (1, 1, 1, 1)
        if self.display_torque < 0:
            self.ids.torque_digit_3.color = (1, 0, 0, 1)
        else:
            self.ids.torque_digit_3.color = (1, 1, 1, 1)
        
        #Update the data list
        self.data_list.append((self.data_time, self.display_torque))
        #Maintain a scrolling window of data (e.g., last 40 points)
        if len(self.data_list) > 40:
            self.data_list = self.data_list[-40:]
        #Update the Plot and Axes
        self.temp_plot.points = self.data_list
        self.ids.torque_graph.add_plot(self.temp_plot)
        self.ids.torque_graph.xmin = self.data_list[0][0]
        self.ids.torque_graph.xmax = self.data_list[-1][0] + 1
        self.data_time += 0.3

class ServoApp(App):
    offline_flag = False
    def get_application_config(self):
        return super(ServoApp, self).get_application_config('~/servocommandor/%(appname)s.ini')

    def build_config(self, config):
        # This function is necessary to load custom ini file. but it does do anything
        config.setdefaults('settings', {'general': True})

    def build(self):
        Builder.load_file(f"{self.config.get('GUI', 'kvfile')}.kv")
        self.servo = ServoCommunicator()
        self.offline = OfflinePopup()
        root = ServoControl()
        Clock.schedule_interval(lambda dt: self.update_rpm(root, dt), 0.3)
        Clock.schedule_interval(lambda dt: self.update_torque(root, dt), 0.3)
        Clock.schedule_once(lambda dt: self.set_config(root, dt))
        return root

    def set_config(self, root, dt):
        Window.borderless = self.config.getboolean('GUI', 'borderless')
        Window.fullscreen = self.config.getboolean('GUI', 'fullscreen')
        Window.show_cursor = self.config.getboolean('GUI', 'cursor')
        Window.size = (800, 480)
        Window.bind(on_key_down=self.on_keyboard_down)
        reverse = self.config.getboolean('GUI', 'no_reverse')
        kv_file = self.config.get('GUI', 'kvfile')
        settings = dict(self.config.items('Settings'))
        sp_btn = dict(self.config.items(settings['mode']))
        ids_dict = self.root.ids
        for k, v in sp_btn.items():
            getattr(ids_dict, k).text = v
        if settings['mode'] == 'surface_speed':
            if settings['unit'] == 'inch':
                self.root.ids.servo_mode.text = 'S.F.M.'
            elif settings['unit'] == 'metric':
                self.root.ids.servo_mode.text = 'S.M.M.'
        if reverse == True:
            self.root.ids.lb_layout.cols = 1
            btn_font_size = self.root.ids.servo_button.font_size
            self.root.ids.servo_button.font_size = btn_font_size * 2
            fwd_btn = self.root.ids.fwd_button
            fwd_btn.parent.remove_widget(fwd_btn)
        if 'reterm' in kv_file:
            Window.size = (1280, 720)

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

    def update_torque(self, root, dt):
        if self.config.get('GUI', 'kvfile').startswith('Servo_tq'):
            torque = self.servo.get_torque()
            if isinstance(torque, int):
                if torque > 3000:
                    torque = torque - 65536
                    print(torque)
                root.current_torque = torque
                root.update_torque_display()

    def on_keyboard_down(self, window, keycode, scancode, text, modifiers):
        key_name = text

        if key_name == 'a':
            self.root.toggle_enable('enabled')
            return True

        if key_name == 's':
            self.root.toggle_enable('disabled')
            return True

        if self.config.getboolean('GUI', 'no_reverse') == False:
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
