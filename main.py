"""Servo Commander - portrait build.

7" 800x480 panel driven in portrait (480x800) by rotating the whole UI on a
Scatter, so the touchscreen and the compositor stay in their native
orientation.  Controls one AC servo through an XP200 drive over Modbus
RS-485 and shows a two-axis DRO (X/Z) with ABS / INC / SDM datums.

Environment hooks (all optional):
  SERVOCOM_MOCK=1        use mock_servo_communication (desk testing)
  SERVOCOM_ROTATE=0      override [GUI] rotate (0 = windowed 480x800)
  SERVOCOM_SHOT=<png>    render one frame to a file and exit
"""
import os
import re
import subprocess

os.environ['KIVY_METRICS_DENSITY'] = '1'

from kivy.config import Config
Config.set('input', 'mouse', 'mouse,disable_multitouch')

from applog import log
from kivy.app import App
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.properties import (NumericProperty, StringProperty, ListProperty,
                             BooleanProperty)

from portrait_ui import (LoadGraph, FitLabel, SetOverlay, ModeOverlay,   # noqa: F401
                         CalcOverlay, HistRow, CalcHistory, FONT, FA, DT)

HERE = os.path.dirname(os.path.abspath(__file__))
USE_MOCK = bool(os.environ.get('SERVOCOM_MOCK'))
if USE_MOCK:
    from mock_servo_communication import ServoCommunicator
else:
    from servo_communication import ServoCommunicator

WHITE = [1, 1, 1, 1]
DIM = [0.313, 0.313, 0.313, 1]
GHOST = [0.13, 0.13, 0.13, 1]

ALARM_CODES = {
    1: {'clearable': True, 'name': 'Overspeed', 'content': 'Motor speed exceeds max value'},
    2: {'clearable': False, 'name': 'Power main overvoltage', 'content': 'Main voltage exceeds specified value, check brake resistor'},
    3: {'clearable': False, 'name': 'Power main undervoltage', 'content': 'Main voltage is lower than specified value'},
    4: {'clearable': True, 'name': 'Position overshoot', 'content': 'Position tracking deviation exceeds set value'},
    5: {'clearable': True, 'name': 'Position command overclocked', 'content': 'The position instruction frequency exceeds the max frequency allowed'},
    6: {'clearable': True, 'name': 'Motor stalling', 'content': 'Motor power line connection error, pole number P-201 error'},
    7: {'clearable': True, 'name': 'Drive inhibit exception', 'content': 'The CCWL and CWL drive travel limit switch is abnormal'},
    9: {'clearable': True, 'name': 'Incremental encoder ABZ signal is faulty', 'content': 'Encoder ABZ signal is interfered or disconnected'},
    10: {'clearable': True, 'name': 'Incremental encoder UVW signal is faulty', 'content': 'Encoder UVW signal is interfered or disconnected'},
    11: {'clearable': False, 'name': 'IPM Module is faulty', 'content': 'Main power loop IPM inverter module is faulty'},
    12: {'clearable': True, 'name': 'Overcurrent', 'content': 'Instantaneous current of the servo drive is too large'},
    13: {'clearable': True, 'name': 'Excess Load', 'content': 'Average load motor current is too large'},
    14: {'clearable': True, 'name': 'Brake peak power overload', 'content': 'Short brake time load is too large, check value or check brake resistor'},
    20: {'clearable': False, 'name': 'EEPROM error', 'content': 'EEPROM read/write error occurred'},
    21: {'clearable': False, 'name': 'Logic circuit error', 'content': 'Peripheral logic circuit of the processor is faulty'},
    23: {'clearable': False, 'name': 'AD reference voltage conversion incorrect', 'content': 'AD sampling circuit voltage non-standard value'},
    24: {'clearable': False, 'name': 'AD conversion asymmetrical or zero-drift large', 'content': 'AD sampling amplifier conditioning circuit is abnormal'},
    29: {'clearable': True, 'name': 'Torque overload', 'content': 'Motor load exceeds max value, check max value and duration value'},
    30: {'clearable': False, 'name': 'Encoder Z signal is lost', 'content': 'Encoder Z signal does not appear'},
    31: {'clearable': False, 'name': 'Encoder Z signal abnormal', 'content': 'Interference or instability in encoder Z signal'},
    32: {'clearable': False, 'name': 'Encoder UVW signal is illegally encoded', 'content': 'Encoder UVW signal disconnected'},
    33: {'clearable': False, 'name': 'Dart encoder signal error', 'content': 'No high resistance state in the power-on sequence'},
}


class Root(BoxLayout):
    pass


class EnableButton(Button):
    """Tap toggles enable/disable; holding for 1s commands speed 0 (the
    same behaviour as the landscape build's DISABLED long-press)."""
    long_press_time = NumericProperty(1.0)

    def __init__(self, **kw):
        super().__init__(**kw)
        self._evt = None
        self._long = False
        self._touch_id = None

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self._touch_id is not None:
                return True
            self._long = False
            self._touch_id = touch.uid
            self.state = 'down'
            self._evt = Clock.schedule_once(self._fire_long, self.long_press_time)
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.uid == self._touch_id:
            if self._evt:
                self._evt.cancel()
                self._evt = None
            self._touch_id = None
            self.state = 'normal'
            if not self._long:
                App.get_running_app().toggle_enable()
            return True
        return super().on_touch_up(touch)

    def _fire_long(self, dt):
        self._long = True
        App.get_running_app().set_speed(0)


class NumpadOverlay(FloatLayout):
    entry = StringProperty('')
    over = BooleanProperty(False)

    def _limit(self):
        return App.get_running_app().display_max()

    def add_digit(self, d):
        if len(self.entry) >= 6:
            return
        if self.entry == '0':
            self.entry = d
        else:
            self.entry += d
        self.over = int(self.entry) > self._limit() and not self.entry.startswith('999')

    def backspace(self):
        self.entry = self.entry[:-1]
        self.over = bool(self.entry) and int(self.entry) > self._limit()

    def clear(self):
        self.entry = ''
        self.over = False

    def submit(self):
        app = App.get_running_app()
        if not self.entry:
            return
        value = int(self.entry)
        if len(self.entry) == 6 and self.entry.startswith('999'):
            app.backdoor(value)
            return
        if value > self._limit():
            self.over = True
            return
        app.set_speed(value)
        app.close_numpad()


class OfflineOverlay(FloatLayout):
    pass


class AlarmOverlay(FloatLayout):
    code_text = StringProperty('')
    name_text = StringProperty('')
    body_text = StringProperty('')
    clearable = BooleanProperty(False)

    def set_code(self, code):
        # codes outside the XP200 table (it skips 8, 15-19, 22, 25-28) still
        # get a popup instead of a crash
        if code not in ALARM_CODES:
            log.error('Alarm code %s is not in the XP200 alarm table', code)
        info = ALARM_CODES.get(code, {
            'clearable': False,
            'name': 'Unknown alarm (code %s)' % code,
            'content': 'Not in the XP200 alarm table - consult the drive manual'})
        self.code_text = 'Error.%s' % code
        self.name_text = info['name']
        self.body_text = info['content']
        self.clearable = info['clearable']


class SystemOverlay(FloatLayout):
    info_text = StringProperty('')


class ServoCommanderApp(App):
    font = FONT
    fa = FA

    # ---- DRO (X/Z) -------------------------------------------------------
    # x_mm / z_mm are the ABS coordinates.  INC and each SDM are offsets from
    # ABS; the readout in any mode is ABS - offset.  With no scales wired in
    # yet the ABS values only move through ZERO / SET.
    x_val = StringProperty('+0.000')
    z_val = StringProperty('+0.000')
    units = StringProperty('mm')
    x_mm = NumericProperty(0.0)
    z_mm = NumericProperty(0.0)
    SDM_COUNT = 20
    MODES = ['ABS', 'INC'] + ['SDM %d' % i for i in range(1, 21)]
    mode_index = NumericProperty(0)
    mode_text = StringProperty('ABS')
    calc_history = []

    # ---- load ------------------------------------------------------------
    load_str = StringProperty('0')
    load_color = ListProperty([1, 1, 1, 1])
    load_color_dim = ListProperty([0.7, 0.7, 0.7, 1])

    # ---- servo -----------------------------------------------------------
    rpm_str = StringProperty('0000')
    rpm_colors = ListProperty([GHOST, GHOST, GHOST, DIM])
    speed_mode_text = StringProperty('R.P.M.')
    speed_unit_short = StringProperty('rpm')
    servo_state = StringProperty('disabled')
    direction = StringProperty('fwd')
    dir_text = StringProperty('FWD')

    def __init__(self, **kw):
        super().__init__(**kw)
        self.offs = {ax: {'INC': 0.0, 'SDM': [0.0] * self.SDM_COUNT}
                     for ax in ('X', 'Z')}
        self._unzero = {}
        self.command_speed = 0      # motor rpm currently commanded
        self.current_speed = 0      # motor rpm reported by the drive
        self.current_torque = 0
        self.offline_flag = False
        self.alarm_flag = False
        self._set_overlay = None
        self._mode_overlay = None
        self._calc_overlay = None
        self._numpad = None
        self._offline = None
        self._alarm = None
        self._system = None

    # ---- config ----------------------------------------------------------
    def get_application_config(self):
        return os.path.join(HERE, 'servo.ini')

    def build_config(self, config):
        config.setdefaults('GUI', {'fullscreen': True, 'cursor': False,
                                   'rotate': 90, 'no_reverse': False})
        config.setdefaults('Hardware', {'invert_direction': False})
        config.setdefaults('Settings', {'mode': 'rpm', 'servo_max_rpm': 3000,
                                        'ratio': 1.0, 'diameter': 100,
                                        'unit': 'metric'})

    # ---- build -----------------------------------------------------------
    def build(self):
        cfg = self.config
        self.mode = cfg.get('Settings', 'mode')
        self.max_rpm = cfg.getint('Settings', 'servo_max_rpm')
        self.ratio = cfg.getfloat('Settings', 'ratio')
        self.diameter = cfg.getfloat('Settings', 'diameter')
        self.unit = cfg.get('Settings', 'unit')
        self.unit_div = {'inch': 12, 'metric': 1000}[self.unit]
        invert = cfg.getboolean('Hardware', 'invert_direction')
        rot_env = os.environ.get('SERVOCOM_ROTATE')
        self.rotate = int(rot_env) if rot_env not in (None, '') else cfg.getint('GUI', 'rotate')
        if self.mode == 'surface_speed':
            self.speed_mode_text = 'S.F.M.' if self.unit == 'inch' else 'S.M.M.'
            self.speed_unit_short = 'sfm' if self.unit == 'inch' else 'smm'
        log.info('App build (portrait): mode=%s ratio=%s max_rpm=%s invert=%s rotate=%s mock=%s',
                 self.mode, self.ratio, self.max_rpm, invert, self.rotate, USE_MOCK)

        Builder.load_file(os.path.join(HERE, 'portrait.kv'))
        self.servo = ServoCommunicator(invert_direction=invert)
        self.servo.start_polling()

        root = Root()
        self.root_layout = root
        self.graph = root.ids.graph
        self.stage = FloatLayout()
        self.stage.add_widget(root)
        self._apply_presets(root)
        self.refresh_axes()
        self.update_rpm_display()

        if self.rotate:
            from kivy.uix.scatter import Scatter
            self.stage.size_hint = (None, None)
            self.stage.size = (480, 800)
            scat = Scatter(size_hint=(None, None), size=(480, 800),
                           do_rotation=False, do_scale=False,
                           do_translation=False, rotation=self.rotate)
            scat.add_widget(self.stage)
            base = FloatLayout()
            base.add_widget(scat)
            self._scatter = scat

            def center(*a):
                scat.center = (Window.width / 2.0, Window.height / 2.0)
            Window.bind(on_resize=center)
            Clock.schedule_once(center, 0)
            display_root = base
        else:
            display_root = self.stage

        Clock.schedule_once(self._set_window, 0)
        Clock.schedule_interval(self._poll_ui, DT)
        Clock.schedule_interval(self._shot_hook, 0.5)

        shot = os.environ.get('SERVOCOM_SHOT')
        if shot:
            Clock.schedule_once(lambda dt: self._cap(shot), 1.0)
        return display_root

    def _set_window(self, dt):
        cfg = self.config
        fullscreen = cfg.getboolean('GUI', 'fullscreen')
        if os.environ.get('SERVOCOM_ROTATE') == '0':
            fullscreen = False       # desk testing: plain 480x800 window
        Window.show_cursor = cfg.getboolean('GUI', 'cursor')
        if fullscreen:
            Window.borderless = True
            Window.fullscreen = 'auto'
        else:
            Window.fullscreen = False
            Window.size = (800, 480) if self.rotate else (480, 800)
        Window.bind(on_key_down=self.on_keyboard_down)

    def _apply_presets(self, root):
        # [rpm] / [surface_speed] sections: sp_btn1..9 and inc_btnp/inc_btnn.
        # A preset can be a plain number or (Name, value) for a labelled speed.
        sp_btn = dict(self.config.items(self.mode))
        match_custom = re.compile(r"\((\w+)\s*,\s*(\d{1,4})\)")
        for key, val in sp_btn.items():
            btn = root.ids.get(key)
            if btn is None:
                continue
            m = match_custom.match(val.strip())
            if m and key.startswith('sp_btn'):
                name, speed = m.group(1)[:10].upper(), int(m.group(2))
                btn.text = name
                btn.custom_speed = speed
                if len(name) > 5:
                    btn.font_size = btn.font_size * max(0.5, 1 - (len(name) - 5) * 0.15)
            else:
                btn.text = val.strip()
                btn.custom_speed = None

    # ---- DRO model -------------------------------------------------------
    def fmt_axis(self, mm_value):
        if self.units == 'mm':
            return '%+.3f' % mm_value
        return '%+.4f' % (mm_value / 25.4)

    def _abs_mm(self, axis):
        return self.x_mm if axis == 'X' else self.z_mm

    def _offset(self, axis):
        m = self.mode_text
        if m == 'ABS':
            return 0.0
        if m == 'INC':
            return self.offs[axis]['INC']
        return self.offs[axis]['SDM'][int(m.split()[1]) - 1]

    def disp_mm(self, axis):
        return self._abs_mm(axis) - self._offset(axis)

    def _apply_mm(self, axis, mm_value):
        m = self.mode_text
        if m == 'ABS':
            if axis == 'X':
                self.x_mm = mm_value
            else:
                self.z_mm = mm_value
        elif m == 'INC':
            self.offs[axis]['INC'] = self._abs_mm(axis) - mm_value
        else:
            self.offs[axis]['SDM'][int(m.split()[1]) - 1] = self._abs_mm(axis) - mm_value
        self.refresh_axes()

    def refresh_axes(self):
        self.x_val = self.fmt_axis(self.disp_mm('X'))
        self.z_val = self.fmt_axis(self.disp_mm('Z'))

    def toggle_units(self):
        self.units = 'in' if self.units == 'mm' else 'mm'
        self.refresh_axes()

    def on_mode_index(self, *args):
        self.mode_text = self.MODES[int(self.mode_index)]
        self.refresh_axes()

    def mode_step(self, delta):
        self.mode_index = (int(self.mode_index) + delta) % len(self.MODES)

    def apply_set(self, axis, value):
        mm_value = value if self.units == 'mm' else value * 25.4
        self._apply_mm(axis, mm_value)

    def zero_axis(self, axis):
        key = (axis, self.mode_text)
        cur_mm = self.disp_mm(axis)
        if abs(cur_mm) < 0.0005:
            prev = self._unzero.pop(key, None)
            if prev is None:
                return
            self._apply_mm(axis, prev)
        else:
            self._unzero[key] = cur_mm
            self._apply_mm(axis, 0.0)

    # ---- overlays --------------------------------------------------------
    def _show(self, attr, widget):
        self._hide(attr)
        setattr(self, attr, widget)
        self.stage.add_widget(widget)
        return widget

    def _hide(self, attr):
        w = getattr(self, attr, None)
        if w is not None:
            self.stage.remove_widget(w)
            setattr(self, attr, None)

    def open_set(self, axis):
        self._show('_set_overlay', SetOverlay(axis=axis))

    def close_set(self):
        self._hide('_set_overlay')

    def open_mode_list(self):
        ov = self._show('_mode_overlay', ModeOverlay())
        ov.populate(self.MODES, int(self.mode_index))

    def close_mode_list(self):
        self._hide('_mode_overlay')

    def select_mode(self, idx):
        self.mode_index = idx
        self.close_mode_list()

    def open_calc(self):
        self._show('_calc_overlay', CalcOverlay())

    def close_calc(self):
        self._hide('_calc_overlay')

    def open_numpad(self):
        self._show('_numpad', NumpadOverlay())

    def close_numpad(self):
        self._hide('_numpad')

    def open_system(self):
        ov = self._show('_system', SystemOverlay())
        ov.info_text = ('mode %s   ratio %s   max %d rpm\n%s' % (
            self.mode, self.ratio, self.max_rpm,
            'MOCK DRIVE' if USE_MOCK else 'XP200 via RS-485'))

    def close_system(self):
        self._hide('_system')

    # ---- speed / direction / enable -------------------------------------
    def display_max(self):
        """Largest value the numpad accepts, in display units."""
        if self.mode == 'rpm':
            return int(self.max_rpm / self.ratio)
        return int(self.ss_convert(self.max_rpm))

    def rpm_convert(self, surface_speed):
        rpm = (surface_speed * self.unit_div) / (3.14159 * self.diameter)
        return rpm * self.ratio

    def ss_convert(self, servo_rpm):
        output_rpm = servo_rpm / self.ratio
        return (3.14159 * output_rpm * self.diameter) / self.unit_div

    def _to_motor(self, value):
        if self.mode == 'rpm':
            return round(value * self.ratio)
        return round(self.rpm_convert(value))

    def _send_speed(self):
        signed = -self.command_speed if self.direction == 'rev' else self.command_speed
        self.servo.set_speed(signed)
        self.update_rpm_display()

    def set_speed(self, speed):
        self.command_speed = self._to_motor(speed)
        if self.command_speed > self.max_rpm:
            log.warning('set_speed clamped: %s -> %s (servo_max_rpm)',
                        self.command_speed, self.max_rpm)
            self.command_speed = self.max_rpm
        if self.command_speed < 0:
            self.command_speed = 0
        self._send_speed()
        log.info('GUI set_speed: %s (direction=%s)', self.command_speed, self.direction)

    def adjust_speed(self, amount):
        self.command_speed += self._to_motor(amount)
        self.command_speed = max(0, min(self.max_rpm, self.command_speed))
        self._send_speed()
        log.info('GUI adjust_speed: %+d -> %s (direction=%s)',
                 amount, self.command_speed, self.direction)

    def preset_press(self, btn):
        speed = getattr(btn, 'custom_speed', None)
        if speed is None:
            if not btn.text.strip().isdigit():
                return
            speed = int(btn.text)
        self.set_speed(speed)

    def _set_direction(self, direction):
        self.direction = direction
        self.dir_text = 'FWD' if direction == 'fwd' else 'REV'

    def toggle_direction(self):
        if self.config.getboolean('GUI', 'no_reverse'):
            return
        new = 'rev' if self.direction == 'fwd' else 'fwd'
        # switching direction brings the speed to 0 first
        self.command_speed = 0
        self.servo.set_speed(0)
        self._set_direction(new)
        self.update_rpm_display()
        log.info('GUI toggle_direction: %s (speed zeroed)', new)

    def sync_direction(self, direction):
        # from the physical FWD/OFF/REV switch: follow it without zeroing
        # (the switch handler already re-applied the speed with the right sign)
        self._set_direction(direction)
        log.info('GUI direction synced from switch: %s', direction)

    def toggle_enable(self):
        self.set_enabled(self.servo_state != 'enabled', source='GUI')

    def set_enabled(self, enabled, source='GUI'):
        if enabled:
            if source == 'GUI':
                self.servo.enable_servo()
            self.servo_state = 'enabled'
        else:
            if source == 'GUI':
                self.servo.disable_servo()
            self.servo_state = 'disabled'
        self.update_rpm_display()
        log.info('Servo state: %s (%s)', self.servo_state, source)

    def update_rpm_display(self):
        speed = self.current_speed if self.servo_state == 'enabled' else self.command_speed
        if self.mode == 'rpm':
            shown = round(speed / self.ratio)
        else:
            shown = round(self.ss_convert(speed))
        shown = max(0, min(9999, int(shown)))
        s = str(shown).zfill(4)
        lit = WHITE if self.servo_state == 'enabled' else DIM
        cols = []
        for i, thresh in enumerate((1000, 100, 10, 1)):
            cols.append(GHOST if (shown < thresh and i < 3) else lit)
        self.rpm_str = s
        self.rpm_colors = cols

    # ---- drive polling (UI thread, reads the poller's cache) -------------
    def _poll_ui(self, dt):
        hw_state = self.servo.get_servo_state()
        if hw_state != self.servo_state:
            self.set_enabled(hw_state == 'enabled', source='switch')
        hw_dir = self.servo.get_hw_direction()
        if hw_dir is not None and hw_dir != self.direction:
            self.sync_direction(hw_dir)

        result = self.servo.get_rpm()
        if result is None:
            if not self.offline_flag:
                self._show('_offline', OfflineOverlay())
                self.offline_flag = True
                log.warning('Offline overlay shown')
            return
        if self.offline_flag:
            self._hide('_offline')
            self.offline_flag = False
        alarm_status, rpm = result
        if alarm_status == 0:
            self.alarm_flag = False
            if self._alarm is not None:
                self._hide('_alarm')
            if rpm > 35000:
                rpm = 65536 - rpm
            self.current_speed = abs(round(rpm / 10))
            self.update_rpm_display()
        elif not self.alarm_flag:
            ov = self._show('_alarm', AlarmOverlay())
            ov.set_code(alarm_status)
            self.alarm_flag = True
            log.error('Drive ALARM raised: code %s', alarm_status)

        torque = self.servo.get_torque()
        if isinstance(torque, int):
            if torque > 3000:
                torque = torque - 65536
            self.current_torque = torque
            load = abs(torque)
            self.load_str = str(load)
            over = load > 100
            self.load_color = [0.95, 0.25, 0.2, 1] if over else [1, 1, 1, 1]
            self.load_color_dim = [0.95, 0.35, 0.3, 0.8] if over else [0.7, 0.7, 0.7, 1]
            # the graph only records while the servo is enabled
            if self.servo_state == 'enabled':
                self.graph.add_sample(load)

    def alarm_clear(self):
        self.servo.disable_servo()
        self.servo_state = 'disabled'
        self.servo.clear_alarm()
        log.info('Alarm clear requested')

        def check(dt):
            if self.servo.get_alarm() == 0:
                self._hide('_alarm')
                self.alarm_flag = False
        Clock.schedule_once(check, 2.0)

    # ---- system ----------------------------------------------------------
    def backdoor(self, value):
        log.info('Backdoor code entered: %s', value)
        if value == 999999:
            self.stop()
        elif value == 999123:
            self.sys_poweroff()
        elif value == 999124:
            self.sys_reboot()

    def _sys(self, action):
        if hasattr(self, 'servo'):
            self.servo.disable_servo()
        log.info('System %s requested', action)
        if os.name == 'nt':
            return
        subprocess.call(['sudo', os.path.join(HERE, 'shutdown_root.sh'), action])

    def sys_poweroff(self):
        self._sys('poweroff')

    def sys_reboot(self):
        self._sys('reboot')

    def on_stop(self):
        # never leave the drive enabled when the GUI goes away
        try:
            self.servo.disable_servo()
            self.servo.disconnect()
        except Exception as exc:
            log.error('on_stop: %s', exc)
        log.info('App stopped')

    def on_keyboard_down(self, window, keycode, scancode, text, modifiers):
        if text == 'a':
            self.set_enabled(True)
            return True
        if text == 's':
            self.set_enabled(False)
            return True
        if text in ('d', 'f') and not self.config.getboolean('GUI', 'no_reverse'):
            want = 'fwd' if text == 'd' else 'rev'
            if self.direction != want:
                self.toggle_direction()
            return True
        return False

    # ---- debug hooks -----------------------------------------------------
    def _shot_hook(self, dt):
        # remote screenshot: touch /tmp/mockshot -> /tmp/mockshot.png
        trigger = '/tmp/mockshot'
        if os.name != 'nt' and os.path.exists(trigger):
            try:
                os.remove(trigger)
                self.stage.export_to_png('/tmp/mockshot.png')
            except Exception:
                pass

    def _cap(self, path):
        self.stage.export_to_png(path)
        print('saved', path)
        self.stop()


if __name__ == '__main__':
    ServoCommanderApp().run()
