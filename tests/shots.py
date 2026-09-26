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


def s_scrolled():
    import math
    g = app.graph
    # a few minutes of made-up history so there is something to scroll into
    g.hist = [int(40 + 30 * math.sin(i / 9.0) + (60 if 180 < i < 200 else 0)) for i in range(600)] + g.hist
    g.view_offset = 130
    g.redraw()


def s_scroll_live():
    app.graph.go_live()


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


def s_drive_info():
    app.open_drive_info()


def s_drive_info_close():
    app.close_info()


def s_settings_speedpad():
    app._settings_overlay.select('speedpad')


def s_tools():
    app.close_settings()
    app.open_tools()


def s_css():
    app.close_tools()
    app.close_css()
    app.save_speed_pad(css_sfm=400, css_top=1500, css_material='Mild steel', css_tool='cbd',
                       css_start_dia_mm=38.1, css_in_sign=-1)
    app.open_css()


def s_css_unlearned():
    app.close_tools()
    app.save_speed_pad(css_in_sign=0)
    app.open_css()


def s_css_ready():
    app.css_activate()


def s_css_running():
    evt = getattr(app, '_css_evt', None)       # picture only: freeze a running pass
    if evt is not None:
        evt.cancel()
    app.css_state = 'running'
    app.css_badge, app.css_badge_color = 'RUNNING', [1, 1, 1, 1]
    app.css_rem_label, app.css_dia_text = 'Cut remaining', '0.456 in'
    app.css_frac, app.css_fill = 0.42, [0, 0.5, 1, 1]


def s_css_off():
    app.css_state = 'ready'
    app.css_exit()


def s_tap():
    app.close_tools()
    app.close_css()
    app._tap_node_ok = lambda: True          # picture only: pretend a 3.15 node
    app.save_speed_pad(tap_thread='1/4-20', tap_mode='bottom', tap_depth_mm=12.7, tap_confirm=2,
                       tap_rpm=100, tap_tlim_manual=0, tap_margin=2.0, tap_hand='rh', tap_drag={'100': 8})
    app.open_tap()


def s_threads():
    app.open_threads()


def s_threads_custom():
    app._threads.set_family('custom')


def s_threads_close():
    app.close_threads()


def s_tap_ready():
    app.close_tap()
    app.tap_activate()


def s_tap_running():
    evt = getattr(app, '_tap_evt', None)       # picture only: freeze a pass
    if evt is not None:
        evt.cancel()
    app.tap_state = 'in'
    app._tap_passes = 2
    app.tap_badge, app.tap_badge_color = 'TAPPING', [1, 1, 1, 1]
    app.tap_big_label, app.tap_big_text = 'Depth  pass 2', app.css_len_text(7.4)
    app.tap_frac, app.tap_fill = 7.4 / 12.7, [0, 0.5, 1, 1]
    app.tap_marks = [(i / 10.0, 'minor') for i in range(1, 10)] + [(8.0 / 12.7, 'major')]
    app.tap_btn_text = 'STOP'


def s_tap_done():
    app.tap_state = 'done'
    app.tap_badge, app.tap_badge_color = 'DONE', [0.4, 0.85, 0.5, 1]
    app.tap_big_label, app.tap_big_text = 'Bottom', app.css_len_text(8.0)
    app.tap_frac, app.tap_fill = 8.0 / 12.7, [0.4, 0.85, 0.5, 1]
    app.tap_btn_text = 'START'


def s_tap_off():
    app.tap_state = 'ready'
    app.tap_exit()


def s_drill():
    app.close_tools()
    app.open_drill()
    app._drill.set_material('Mild steel')
    app._drill.choose('1/4', 0.25)


def s_sfm():
    app.close_drill()
    app.open_sfm()
    app._sfm.set_unit('inch')
    app._sfm.set_diameter(2.125)
    app._sfm.set_material('Mild steel')


def s_sfm_done():
    app.close_sfm()


def s_settings_drive():
    app.set_enabled(False)
    app._settings_overlay.select('drive')
    app._settings_overlay.ids.content.children[0].refresh()


def s_param_edit():
    app.open_param_edit('overload_level')
    for ch in '200':
        app._param_edit.add_digit(ch)


def s_param_dirty():
    app._param_edit.accept()
    app._settings_overlay.ids.content.children[0].refresh()


def s_ratio_prep():
    app.close_settings()
    app.set_speed(1000)
    app.set_enabled(True)


def s_ratio_cal():
    print('RATIO_CAL state:', app.servo_state, app.current_speed, app.command_speed, app.offline_flag)
    app.open_settings('drive')
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
    (4.0, s_scrolled), (0.4, lambda: cap('graph_scrolled')), (0.2, s_scroll_live),
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
    (0.2, s_drive_info), (0.5, lambda: cap('drive_info')), (0.2, s_drive_info_close),
    (0.2, s_settings_speedpad), (0.4, lambda: cap('settings_speedpad')),
    (0.2, s_tools), (0.6, lambda: cap('tools')),
    (0.2, s_css_unlearned), (0.6, lambda: cap('css_unlearned')),
    (0.2, s_css), (0.6, lambda: cap('css')),
    (0.2, s_tap), (0.6, lambda: cap('tap')),
    (0.2, s_threads), (0.6, lambda: cap('tap_threads')),
    (0.2, s_threads_custom), (0.6, lambda: cap('tap_threads_custom')), (0.2, s_threads_close),
    (0.2, s_tap_ready), (0.6, lambda: cap('tap_ready')),
    (0.2, s_tap_running), (0.6, lambda: cap('tap_running')),
    (0.2, s_tap_done), (0.6, lambda: cap('tap_done')), (0.2, s_tap_off),
    (0.2, s_css_ready), (0.6, lambda: cap('css_ready')),
    (0.2, s_css_running), (0.6, lambda: cap('css_running')), (0.2, s_css_off),
    (0.2, s_drill), (0.6, lambda: cap('drill')),
    (0.2, s_sfm), (0.6, lambda: cap('sfm')), (0.2, s_sfm_done),
    (0.2, lambda: app.open_settings()),
    (0.2, s_settings_drive), (0.6, lambda: cap('settings_drive')),
    (0.2, s_param_edit), (0.4, lambda: cap('param_edit')),
    (0.2, s_param_dirty), (0.6, lambda: cap('settings_drive_dirty')),
    (0.2, s_ratio_prep), (1.6, s_ratio_cal), (1.2, lambda: cap('ratio_cal')),
    (0.2, s_nodro), (0.6, lambda: cap('portrait_nodro')),
    (0.2, s_landscape), (1.0, lambda: cap('landscape')),
    (0.2, s_tap_ready), (0.6, lambda: cap('landscape_tap_ready')),
    (0.2, s_tap_running), (0.6, lambda: cap('landscape_tap_running')), (0.2, s_tap_off),
    (0.2, s_css_ready), (0.6, lambda: cap('landscape_css_ready')),
    (0.2, lambda: app.open_css()), (0.6, lambda: cap('landscape_css_setup')), (0.2, lambda: app.close_css()),
    (0.2, s_css_running), (0.6, lambda: cap('landscape_css_running')), (0.2, s_css_off),
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
