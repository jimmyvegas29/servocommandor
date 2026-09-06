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
    ids = app.root_layout.ids
    app.preset_press(ids.sp_btn7)          # 1000
    app.toggle_enable()


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


def s_system():
    app.servo.offline = False
    app._poll_ui(0)
    app.open_system()


def s_done():
    app.close_system()
    app.stop()


plan = [
    (1.0, s_running), (3.0, lambda: cap('running')),
    (0.2, s_numpad), (0.4, lambda: cap('numpad')),
    (0.2, s_numpad_over), (0.4, lambda: cap('numpad_over')),
    (0.2, s_alarm), (0.4, lambda: cap('alarm')),
    (0.2, s_alarm_nc), (0.4, lambda: cap('alarm_nc')),
    (0.2, s_offline), (0.4, lambda: cap('offline')),
    (0.2, s_system), (0.4, lambda: cap('system')),
    (0.2, s_done),
]
t = 0.0
for delay, fn in plan:
    t += delay
    Clock.schedule_once(lambda dt, f=fn: f(), t)
app.run()
print('done')
