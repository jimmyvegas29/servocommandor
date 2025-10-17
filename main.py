from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.properties import NumericProperty, StringProperty, BooleanProperty, partial
from kivy.uix.modalview import ModalView
from kivy.clock import Clock
from servo_communication import ServoCommunicator
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import ObjectProperty
from kivy_garden.graph import MeshLinePlot, LinePlot, SmoothLinePlot
from time import sleep
import subprocess
import operator
import os
import re


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

    def full_shutdown(self):
        shutdown_path = os.path.expanduser("~/servocommandor/shutdown_root.sh")
        subprocess.call(["sudo", shutdown_path, "poweroff"])
    def sys_restart(self):
        shutdown_path = os.path.expanduser("~/servocommandor/shutdown_root.sh")
        subprocess.call(["sudo", shutdown_path, "reboot"])
    def app_close(self):
        App.get_running_app().stop()

class AlarmPopup(ModalView):
    alarm_codes = {1: {'clearable': True, 'name': 'Overspeed', 'content': 'Motor speed exceeds max value'},
                   2: {'clearable': False, 'name': 'Power main overvoltage', 'content': 'Main voltage exceeds specified value, check break resistor'},
                   3: {'clearable': False, 'name': 'Power main undervoltage', 'content': 'Main voltage is lower than specified value'},
                   4: {'clearable': True, 'name': 'Position overshoot', 'content': 'Position tracking deviation exceeds set value'},
                   5: {'clearable': True, 'name': 'Position command overclocked', 'content': 'The position instruction frequency exceeds the max frequency allowed'},
                   6: {'clearable': True, 'name': 'Motor stalling', 'content': 'Motor power line connection error, pole number P-201 error'},
                   7: {'clearable': True, 'name': 'Drive inhibit exception', 'content': 'The CCWL and CWL drive travel limit switch is abnormal'},
                   9: {'clearable': True, 'name': 'Incremental encoder ABZ signal is faulty', 'content': 'Encoder ABZ signal is interfered or disconnected'},
                   10: {'clearable': True, 'name': 'Incremental encoder UVW signal is faulty', 'content': 'Encoder UVW signal is interfered or disconnected'},
                   11: {'clearable': False, 'name': 'IPM Module is faulty', 'content': 'Main power loop IPM inverter module is faulty'},
                   12: {'clearable': True, 'name': 'Overcurrent', 'content': 'Instantaneous current of the servo drive is to large'},
                   13: {'clearable': True, 'name': 'Excess Load', 'content': 'Average load motor current is to large'},
                   14: {'clearable': True, 'name': 'Break peak power overload', 'content': 'Short break time load is too large, check value or check brake resistor'},
                   20: {'clearable': False, 'name': 'EEPROM error', 'content': 'EEPROM read/write error occured'},
                   21: {'clearable': False, 'name': 'Logic circuit error', 'content': 'Peripheral logic circuit of the processor is faulty'},
                   23: {'clearable': False, 'name': 'AD reference voltage conversion incorrect', 'content': 'AD sampling circuit voltage non-standard value'},
                   24: {'clearable': False, 'name': 'AD conversion asymmtetrical or zero-drift large', 'content': 'AD sampling amplifier conditioning circuit is abnormal'},
                   29: {'clearable': True, 'name': 'Torque overload', 'content': 'Motor load exceeds max value, check max value and duration value'},
                   30: {'clearable': False, 'name': 'Encoder Z signal is lost', 'content': 'Encoder Z signal does not appear'},
                   31: {'clearable': False, 'name': 'Encoder Z signal abnormal', 'content': 'Interference or instability in encoder Z signal'},
                   32: {'clearable': False, 'name': 'Encoder UVW signal is illegally encoded', 'content': 'Encoder UVW signal disconnected'},
                   33: {'clearable': False, 'name': 'Dart encoder signal error', 'content': 'No high resistance state in the power-on sequence'},
                   }
    def __init__(self, **kwargs):
        super(AlarmPopup, self).__init__(**kwargs)

    def set_alarm_code(self, code: int):
        alarm_code = operator.getitem(self.alarm_codes, code)
        self.ids.alarm_main_text.text = f"Error.{code}"
        self.ids.alarm_sub_text.text = f"{alarm_code['name']}\n{alarm_code['content']}"
        if not alarm_code['clearable']:
            label = Label(text='Alarm not clearable\npower cycle drive to clear alarm',color=(1, 0, 0, 1), font_size='20sp', font_name='assets/Orbitron-Medium.ttf', halign='center', valign=
                'top')
            alarm_btn = self.ids.alarm_clear_btn
            alarm_btn.parent.remove_widget(alarm_btn)
            self.ids.alarm_box_lower.add_widget(label)

    def alarm_clear(self):
        app = App.get_running_app()
        app.servo.disable_servo()
        app.servo.clear_alarm()
        sleep(2)
        if app.servo.get_alarm() == 0:
            self.dismiss()

class LongPressButton(Button):
    long_press_time = NumericProperty(1.0)
    _long_press_triggered = BooleanProperty(False)
    _touch_id = None 

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._scheduled_event = None

    def on_press(self):
        pass

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self._touch_id is not None:
                return True
                
            self._long_press_triggered = False
            self._touch_id = touch.uid
            self.state = 'down' 
            self._scheduled_event = Clock.schedule_once(self._long_press_callback, self.long_press_time)
            return True 
        
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.uid == self._touch_id:
            # 1. Cancel timer and reset ID
            if self._scheduled_event:
                self._scheduled_event.cancel()
                self._scheduled_event = None
            self._touch_id = None 
            self.state = 'normal' 
            suppress_on_release = (self._long_press_triggered and self.text == "DISABLED")
            if not suppress_on_release:
                self.dispatch('on_release') 
            return True
        
        return super().on_touch_up(touch)

    def _long_press_callback(self, dt):
        self._long_press_triggered = True
        App.get_running_app().root.set_speed(0)



class ServoControl(BoxLayout):
    servo_state = StringProperty('disabled')
    direction = StringProperty('fwd')
    current_torque = NumericProperty(0)
    current_speed = NumericProperty(0)
    command_speed = NumericProperty(0)
    torque_plot = ObjectProperty(LinePlot(color=[0, 0.5, 1, 1], line_width=1.5))
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        unit_conversion = {'inch': 12, 'metric': 1000}
        self.cfg = dict(App.get_running_app().config.items('Settings'))
        self.mode = self.cfg['mode']
        self.max_rpm = int(self.cfg['servo_max_rpm'])
        self.unit = self.cfg['unit']
        self.ratio = float(self.cfg['ratio'])
        self.diameter = float(self.cfg['diameter'])
        self.unit_div = unit_conversion[self.unit]
        self.data_time = 0.0
        self.data_list = []

    def text_integer(self, text):
        return text.isdigit()

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
            App.get_running_app().servo.set_speed(0)
            self.command_speed = 0 #When switching directions it will bring the bring the servo speed down to 0

        self.direction = direction

        if self.direction == 'fwd':
            self.ids.fwd_button.text = 'FORWARD'
        elif self.direction == 'rev':
            self.ids.fwd_button.text = 'REVERSE'
        print(f"Toggle direction to: {self.direction}")

    def toggle_enable(self, servo_state):
        self.servo_state = servo_state

        if self.servo_state == 'enabled':
            #self.ids.servo_button.state = 'normal'
            self.ids.servo_button.text = 'ENABLED'
            App.get_running_app().servo.enable_servo()
        elif self.servo_state == 'disabled':
            #self.ids.servo_button.state = 'down'
            self.ids.servo_button.text = 'DISABLED'
            App.get_running_app().servo.disable_servo()
        print(f"Servo State Changed To: {self.servo_state}")

    def update_rpm_display(self):
        if self.servo_state == 'disabled':
            speed = self.command_speed
        elif self.servo_state == 'enabled':
            speed = self.current_speed
        if self.mode == 'rpm':
            self.display_speed = round(speed/self.ratio)
        elif self.mode == 'surface_speed':
            self.display_speed = round(self.ss_convert(speed))
        rpm_str = str(int(self.display_speed)).zfill(4)
        self.ids.rpm_digit_1.text = rpm_str[0]
        self.ids.rpm_digit_2.text = rpm_str[1]
        self.ids.rpm_digit_3.text = rpm_str[2]
        self.ids.rpm_digit_4.text = rpm_str[3]

        if self.display_speed < 1000:
            self.ids.rpm_digit_1.color = (0.13, 0.13, 0.13, 1)
        else:
            if self.servo_state == 'enabled':
                self.ids.rpm_digit_1.color = (1, 1, 1, 1)
            elif self.servo_state == 'disabled':
                self.ids.rpm_digit_1.color = (0.313, 0.313, 0.313, 1)
        if self.display_speed < 100:
            self.ids.rpm_digit_2.color = (0.13, 0.13, 0.13, 1)
        else:
            if self.servo_state == 'enabled':
                self.ids.rpm_digit_2.color = (1, 1, 1, 1)
            elif self.servo_state == 'disabled':
                self.ids.rpm_digit_2.color = (0.313, 0.313, 0.313, 1)
        if self.display_speed < 10:
            self.ids.rpm_digit_3.color = (0.13, 0.13, 0.13, 1)
        else:
            if self.servo_state == 'enabled':
                self.ids.rpm_digit_3.color = (1, 1, 1, 1)
            elif self.servo_state == 'disabled':
                self.ids.rpm_digit_3.color = (0.313, 0.313, 0.313, 1)
        if self.servo_state == 'enabled':
            self.ids.rpm_digit_4.color = (1, 1, 1, 1)
        elif self.servo_state == 'disabled':
            self.ids.rpm_digit_4.color = (0.313, 0.313, 0.313, 1)

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
        self.torque_plot.points = self.data_list
        self.ids.torque_graph.add_plot(self.torque_plot)
        self.ids.torque_graph.xmin = self.data_list[0][0]
        self.ids.torque_graph.xmax = self.data_list[-1][0] + 1
        self.data_time += 0.3

class ServoApp(App):
    offline_flag = False
    alarm_flag = False
    def get_application_config(self):
        return super(ServoApp, self).get_application_config('~/servocommandor/%(appname)s.ini')

    def build_config(self, config):
        # This function is necessary to load custom ini file. but it does do anything
        config.setdefaults('settings', {'general': True})

    def get_file_path(self, filename):
        app_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(app_dir, filename)

    def build(self):
        Builder.load_file(f"{self.config.get('GUI', 'kvfile')}.kv")
        self.servo = ServoCommunicator()
        self.offline = OfflinePopup()
        self.alarm = AlarmPopup()
        root = ServoControl()
        Clock.schedule_interval(lambda dt: self.update_rpm(root, dt), 0.3)
        Clock.schedule_interval(lambda dt: self.update_torque(root, dt), 0.4)
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
            spd_btn = getattr(ids_dict, k)
            match_custom = re.compile(r"\((\w+)\s*,\s*(\d{1,4})\)")
            match_num = re.compile(r"\b[+-]?\d{4}\b")
            if match_custom.findall(v) and k.startswith('sp_btn'):
                clean_str = v[1:-1]
                custom_list = [s.strip() for s in clean_str.split(',', 1)]
                custom_str = custom_list[0]
                custom_int = int(custom_list[1])
                if len(custom_str) > 5:
                    x_factor = 1 - ((len(custom_str)-5)*0.15)
                    if x_factor < 0.5:
                        x_factor = 0.5
                    cur_fnt_size = spd_btn.font_size
                    spd_btn.font_size = cur_fnt_size * x_factor
                    print(x_factor)
                if len(custom_str) > 10:
                    custom_str = custom_str[:10]
                spd_btn.text = custom_str.upper()
                spd_btn.bind(on_press=lambda instance, s=custom_int: root.set_speed(s))
            elif match_num.findall(v):
                spd_btn.text = v
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
        alarm_status = rpm[0]
        rpm = rpm[1]
        if isinstance(rpm, int):
            if self.offline_flag:
                self.offline.dismiss()
                self.offline_flag = False
            if alarm_status == 0:
                if self.alarm_flag:
                    self.alarm_flag = False
                if rpm > 35000:
                    rpm = 65536 - rpm
                if rpm is not None:
                    rpm = round(rpm/10)
                    root.current_speed = abs(rpm)
                    root.update_rpm_display()
            else:
                if not self.alarm_flag:
                    self.alarm.set_alarm_code(alarm_status)
                    self.alarm.open()
                    self.alarm_flag = True
                    print("Servo Drive Alarm")
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
                    if root.direction == 'fwd':
                        torque = torque - 65536
                    if root.direction == 'rev':
                        torque = 65536 - torque
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
