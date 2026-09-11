"""Render the portrait build's states/overlays to tests/shots/*.png using the
mock drive (run from the repo root: python tests/shots.py)."""
import os
import sys

os.environ['SERVOCOM_MOCK'] = '1'
os.environ['SERVOCOM_ROTATE'] = '0'
os.environ['SERVOCOM_SHOT'] = ''

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
SETTINGS = os.path.join(ROOT, 'tests', 'settings_shots.json')
os.environ['SERVOCOM_SETTINGS'] = SETTINGS
if os.path.exists(SETTINGS):
    os.remove(SETTINGS)
OUT = os.path.join(ROOT, 'tests', 'shots')
os.makedirs(OUT, exist_ok=True)

import main as m                      # noqa: E402
from kivy.clock import Clock          # noqa: E402

app = m.ServoCommanderApp()
steps = []


def cap(name):
    app.stage.export_to_png(os.path.join(OUT, name + '.png'))


def later(delay, fn):
    steps.append((delay, fn))


def s_running():
    ids = app.root_layout.ids.controls.ids
    app.preset_press(ids.sp_btn7)          # 1000
    app.toggle_enable()


def s_half():
    app.arm_half()


def s_half_off():
    app._disarm_half()


def s_copy():
    app.open_copy('X')
    for n in ('SDM 2', 'SDM 3', 'SDM 4', 'INC'):
        app._copy_overlay.toggle(n)


def s_copy_off():
    app.close_copy()


def s_numpad():
    app.open_numpad()
    for ch in '1250':
        app._numpad.add_digit(ch)


def s_numpad_over():
    app._numpad.clear()
    for ch in '5000':
        app._numpad.add_digit(ch)


def s_alarm():
    app.close_numpad()
    app.servo.alarmcode = 13
    app._poll_ui(0)


def s_alarm_nc():
    app.servo.alarmcode = 11
    app._alarm.set_code(11)


def s_offline():
    app.servo.alarmcode = 0
    app._poll_ui(0)
    app.servo.offline = True
    app._poll_ui(0)


def s_settings():
    app.servo.offline = False
    app._poll_ui(0)
    app.open_settings()


def s_settings_system():
    app._settings_overlay.select('system')


def s_settings_dro():
    app._settings_overlay.select('dro')


def s_settings_conn():
    app._settings_overlay.select('connection')


def s_ratio_prep():
    app.close_settings()
    app.set_speed(1000)
    app.set_enabled(True)


def s_ratio_cal():
    print('RATIO_CAL state:', app.servo_state, app.current_speed, app.command_speed, app.offline_flag)
    app.open_settings('system')
    app.open_ratio_cal()
    for ch in '965':
        app._ratio_cal.add_digit(ch)


def s_nodro():
    app.close_ratio_cal()
    app.set_enabled(False)
    app.close_settings()
    app.set_show_dro(False)


def s_landscape():
    app.set_show_dro(True)
    app.set_orientation('landscape')


def s_landscape_settings():
    app.open_settings()


def s_landscape_running():
    app.close_settings()
    app.set_speed(1000)
    app.set_enabled(True)


def s_landscape_cards():
    app.settings['landscape_style'] = 'cards'
    app._build_stage()


def s_done():
    app.settings['landscape_style'] = 'classic'
    app.set_enabled(False)
    app.set_orientation('portrait')
    app.stop()


plan = [
    (1.0, s_running), (3.0, lambda: cap('running')),
    (0.2, s_half), (0.4, lambda: cap('half_armed')), (0.2, s_half_off),
    (0.2, s_copy), (0.5, lambda: cap('copy_picker')), (0.2, s_copy_off),
    (0.2, s_numpad), (0.4, lambda: cap('numpad')),
    (0.2, s_numpad_over), (0.4, lambda: cap('numpad_over')),
    (0.2, s_alarm), (0.4, lambda: cap('alarm')),
    (0.2, s_alarm_nc), (0.4, lambda: cap('alarm_nc')),
    (0.2, s_offline), (0.4, lambda: cap('offline')),
    (0.2, s_settings), (0.4, lambda: cap('settings_display')),
    (0.2, s_settings_system), (0.4, lambda: cap('settings_system')),
    (0.2, s_settings_dro), (0.4, lambda: cap('settings_dro')),
    (0.2, s_settings_conn), (0.4, lambda: cap('settings_connection')),
    (0.2, s_ratio_prep), (1.6, s_ratio_cal), (1.2, lambda: cap('ratio_cal')),
    (0.2, s_nodro), (0.6, lambda: cap('portrait_nodro')),
    (0.2, s_landscape), (1.0, lambda: cap('landscape')),
    (0.2, s_landscape_settings), (0.6, lambda: cap('landscape_settings')),
    (0.2, s_landscape_running), (2.5, lambda: cap('landscape_running')),
    (0.2, s_landscape_cards), (1.0, lambda: cap('landscape_cards')),
    (0.2, s_done),
]
t = 0.0
for delay, fn in plan:
    t += delay
    Clock.schedule_once(lambda dt, f=fn: f(), t)
app.run()
print('done')
