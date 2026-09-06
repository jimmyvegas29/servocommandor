"""Closed-loop logic test for the portrait build, driven through the mock
drive.  Run from the repo root:

    python tests/test_portrait.py

Exercises presets from servo.ini, speed/direction/enable, the four-digit
rpm readout, the custom numpad, offline and alarm overlays, the DRO datum
model and the calculator hand-off.  Exports tests/portrait_main.png.
"""
import json
import os
import sys

os.environ['SERVOCOM_MOCK'] = '1'
os.environ['SERVOCOM_ROTATE'] = '0'
os.environ['SERVOCOM_SHOT'] = ''

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
SETTINGS = os.path.join(ROOT, 'tests', 'settings_test.json')
os.environ['SERVOCOM_SETTINGS'] = SETTINGS
if os.path.exists(SETTINGS):
    os.remove(SETTINGS)

import main as m                      # noqa: E402
from kivy.clock import Clock          # noqa: E402

app = m.ServoCommanderApp()
fails = []


def check(label, got, want):
    ok = got == want
    print('%-40s got %-18r want %-18r %s' % (label, got, want, 'OK' if ok else 'FAIL'))
    if not ok:
        fails.append(label)


def run(dt):
    ids = app.root_layout.ids.controls.ids
    servo = app.servo
    # presets come from [rpm] in servo.ini
    check('preset 8 from ini', ids.sp_btn8.text, '1250')
    check('inc buttons from ini', (ids.inc_btnp.text, ids.inc_btnn.text), ('+50', '-50'))
    check('start disabled', app.servo_state, 'disabled')
    check('start rpm readout', app.rpm_str, '0000')
    check('leading digits ghosted', app.rpm_colors[:3], [m.GHOST] * 3)

    # speed: preset -> motor rpm = display * ratio
    app.preset_press(ids.sp_btn5)               # 600
    check('command_speed = 600*ratio', app.command_speed, round(600 * app.ratio))
    check('mock got signed speed', servo.rpm, round(600 * app.ratio))
    check('readout while disabled = command', app.rpm_str, '0600')
    check('disabled digits dim', app.rpm_colors[3], m.DIM)
    app.adjust_speed(50)
    check('adjust +50', app.rpm_str, '0650')
    app.adjust_speed(-50)
    check('adjust -50', app.rpm_str, '0600')
    app.set_speed(99999)
    check('clamped to max', app.command_speed, app.max_rpm)
    app.set_speed(600)

    # direction: toggling zeroes speed; readout follows
    app.toggle_direction()
    check('direction rev', (app.direction, app.dir_text), ('rev', 'REV'))
    check('speed zeroed on direction change', (app.command_speed, servo.rpm), (0, 0))
    app.set_speed(400)
    check('rev speed negative on wire', servo.rpm, -round(400 * app.ratio))
    app.toggle_direction()
    app.set_speed(600)

    # enable: mock ramps toward command; readout shows actual when enabled
    app.toggle_enable()
    check('enabled', (app.servo_state, servo.servostate), ('enabled', 'enabled'))
    Clock.schedule_once(after_enable, 1.5)


def after_enable(dt):
    servo = app.servo
    check('rpm readout tracks drive', app.rpm_str, '0600')
    check('enabled digits white', app.rpm_colors[3], m.WHITE)
    check('load shown while enabled', app.load_str != '0', True)
    check('graph sampling while enabled', len(app.graph.hist) > 2, True)
    n = len(app.graph.hist)
    app.toggle_enable()
    check('disabled again', app.servo_state, 'disabled')
    Clock.schedule_once(lambda dt: after_disable(n), 0.8)


def after_disable(n):
    servo = app.servo
    check('graph frozen while disabled', len(app.graph.hist), n)
    check('readout back to command when disabled', app.rpm_str, '0600')

    # long-press on EN commands speed 0
    ids = app.root_layout.ids.controls.ids
    ids.servo_button._fire_long(0)
    check('long press -> speed 0', (app.command_speed, app.rpm_str), (0, '0000'))

    # custom numpad
    app.open_numpad()
    np_ = app._numpad
    for ch in '1250':
        np_.add_digit(ch)
    np_.submit()
    check('numpad set 1250', app.command_speed, round(1250 * app.ratio))
    check('numpad closed', app._numpad, None)
    app.open_numpad()
    np_ = app._numpad
    for ch in '5000':
        np_.add_digit(ch)
    check('numpad over limit flagged', np_.over, True)
    np_.submit()
    check('over limit not applied', app.command_speed, round(1250 * app.ratio))
    app.close_numpad()

    # switch sync: the poller's state/direction flow into the GUI
    servo.servostate = 'enabled'
    servo.hw_direction = 'rev'
    app._poll_ui(0)
    check('switch enable synced', app.servo_state, 'enabled')
    check('switch direction synced', (app.direction, app.dir_text), ('rev', 'REV'))
    servo.servostate = 'disabled'
    servo.hw_direction = 'fwd'
    app._poll_ui(0)
    check('switch neutral synced', (app.servo_state, app.direction), ('disabled', 'fwd'))

    # offline overlay: dismissable, speed section locked, DRO usable
    servo.offline = True
    app._poll_ui(0)
    check('offline overlay shown', app._offline is not None, True)
    app.dismiss_offline()
    check('offline dismissed', (app._offline, app.offline_dismissed), (None, True))
    app._poll_ui(0)
    check('stays dismissed while offline', app._offline, None)
    before = (app.command_speed, servo.rpm, app.direction, app.servo_state)
    app.set_speed(1500)
    check('set_speed offline re-shows popup', app._offline is not None, True)
    app.dismiss_offline()
    app.adjust_speed(50)
    check('adjust offline re-shows popup', app._offline is not None, True)
    app.dismiss_offline()
    app.toggle_direction()
    app.dismiss_offline()
    app.toggle_enable()
    check('enable offline re-shows popup', app._offline is not None, True)
    app.dismiss_offline()
    app.open_numpad()
    check('numpad offline blocked', (app._numpad, app._offline is not None), (None, True))
    check('nothing commanded while offline',
          (app.command_speed, servo.rpm, app.direction, app.servo_state), before)
    app.dismiss_offline()
    app.apply_set('X', 3.0)
    app.zero_axis('X')
    check('DRO works while offline', app.x_val, '+0.000')
    app.zero_axis('X')
    check('DRO un-zero while offline', app.x_val, '+3.000')
    app.apply_set('X', 0.0)
    servo.offline = False
    app._poll_ui(0)
    check('offline overlay cleared', (app._offline, app.offline_dismissed), (None, False))
    app.set_speed(600)
    check('speed works again online', app.rpm_str, '0600')

    # alarm overlay
    servo.alarmcode = 13
    app._poll_ui(0)
    check('alarm overlay shown', app._alarm is not None, True)
    check('alarm text', (app._alarm.code_text, app._alarm.clearable), ('Error.13', True))
    servo.alarmcode = 77
    app._alarm.set_code(77)
    check('unknown alarm handled', app._alarm.clearable, False)
    servo.alarmcode = 13
    app.alarm_clear()
    check('alarm clear disables', servo.servostate, 'disabled')
    Clock.schedule_once(after_alarm, 2.3)


def after_alarm(dt):
    app._poll_ui(0)
    check('alarm overlay cleared', app._alarm, None)

    # DRO datums start at zero with no scales wired
    check('axes at zero', (app.x_val, app.z_val), ('+0.000', '+0.000'))
    app.apply_set('X', 12.5)
    app.select_mode(1)                    # INC
    app.zero_axis('X')
    app.select_mode(0)
    check('INC zero leaves ABS', app.x_val, '+12.500')
    app.select_mode(1)
    check('INC kept', app.x_val, '+0.000')
    app.select_mode(0)
    app.toggle_units()
    check('inch readout', app.x_val, '+0.4921')
    app.toggle_units()

    # calculator hand-off
    app.open_calc()
    ov = app._calc_overlay
    for ch in '25.4':
        ov.add_dot() if ch == '.' else ov.add_digit(ch)
    ov.add_op('×')
    ov.add_digit('2')
    ov.send_to('Z')
    check('calc SET Z', app.z_val, '+50.800')
    check('calc closed', app._calc_overlay, None)

    # settings: menu / pages
    app.open_settings()
    ov = app._settings_overlay
    check('settings opens on display page', ov.page, 'display')
    check('menu has pages', sorted(ov._buttons), ['display', 'system'])
    ov.select('system')
    check('system page selected', (ov.page, ov._buttons['system'].active), ('system', True))
    check('display button inactive', ov._buttons['display'].active, False)
    app.close_settings()
    check('settings closed', app._settings_overlay, None)

    # show DRO off: block collapses, load/rpm cards grow
    ids = app.root_layout.ids
    check('dro block visible', ids.dro.height, 240)
    app.set_show_dro(False)
    check('dro hidden', (ids.dro.height, ids.dro.opacity, ids.dro.disabled), (0, 0, True))
    check('load card grows', ids.load_card.height, 290)
    check('rpm card grows', (ids.rpm_card.height, ids.rpm_card.digit_font), (170, 120))
    with open(SETTINGS, encoding='utf-8') as fh:
        saved = json.load(fh)
    check('settings saved', saved['show_dro'], False)
    app.set_show_dro(True)
    check('dro back', ids.dro.height, 240)

    # orientation: landscape rebuilds the stage, keeps state
    hist_len = len(app.graph.hist)
    app.set_speed(800)
    app.open_settings()
    app.set_orientation('landscape')
    check('landscape root', type(app.root_layout).__name__, 'RootLandscape')
    check('stage 800x480', tuple(app.stage.size), (800, 480))
    check('history carried over', len(app.graph.hist), hist_len)
    check('presets re-applied', app.control_ids().sp_btn8.text, '1250')
    check('rpm readout kept', app.rpm_str, '0800')
    check('settings reopened after rebuild', app._settings_overlay is not None, True)
    check('landscape has no dro id', 'dro' in app.root_layout.ids, False)
    check('landscape direction label', app.control_ids().fwd_button.text, 'FORWARD')
    check('landscape enable label', app.control_ids().servo_button.text, 'DISABLED')
    check('landscape torque digits', (app.load_digits, len(app.load_colors)), ('000', 3))
    # parked card-style landscape still builds
    app.settings['landscape_style'] = 'cards'
    app._build_stage()
    check('cards landscape root', type(app.root_layout).__name__, 'RootLandscapeCards')
    check('cards presets', app.control_ids().sp_btn8.text, '1250')
    app.settings['landscape_style'] = 'classic'
    app._build_stage()
    check('classic landscape again', type(app.root_layout).__name__, 'RootLandscape')
    app.open_settings()
    with open(SETTINGS, encoding='utf-8') as fh:
        saved = json.load(fh)
    check('orientation saved', saved['orientation'], 'landscape')
    app.stage.export_to_png(os.path.join(ROOT, 'tests', 'landscape_settings.png'))
    app.close_settings()
    app.stage.export_to_png(os.path.join(ROOT, 'tests', 'landscape_main.png'))
    app.set_orientation('portrait')
    check('back to portrait', (type(app.root_layout).__name__, tuple(app.stage.size)),
          ('Root', (480, 800)))
    check('same orientation is a no-op', app.set_orientation('portrait'), None)

    # system page rows + ratio calibration (servo.ini edited in place)
    app.open_settings('system')
    page = app._settings_overlay.ids.content.children[0]
    labels = [r.label for r in page.ids.rows.children]
    check('system rows present', all(l in labels for l in
          ('Speed mode', 'Ratio', 'Max motor rpm', 'Build')), True)
    ini_path = os.path.join(ROOT, 'servo.ini')
    ini_before = open(ini_path, encoding='utf-8').read()
    old_ratio = app.ratio
    app.open_ratio_cal()
    cal = app._ratio_cal
    check('cal needs running spindle', (cal.motor_rpm, cal.new_ratio), (0, 0.0))
    app.set_speed(600)
    app.toggle_enable()
    Clock.schedule_once(lambda dt: after_ratio(ini_path, ini_before, old_ratio), 1.5)


def after_ratio(ini_path, ini_before, old_ratio):
    cal = app._ratio_cal
    cal.refresh()
    motor = round(600 * old_ratio)
    check('cal reads motor rpm', cal.motor_rpm, motor)
    check('cal shows spindle rpm', cal.shown_rpm, 600)
    for ch in '580':                      # tach says 580 instead of 600
        cal.add_digit(ch)
    want = round(motor / 580.0, 3)
    check('new ratio computed', cal.new_ratio, want)
    cal.accept()
    check('ratio applied', app.ratio, want)
    check('readout uses new ratio', app.rpm_str, str(round(app.current_speed / want)).zfill(4))
    check('cal closed, system page reopened',
          (app._ratio_cal, app._settings_overlay.page), (None, 'system'))
    ini_after = open(ini_path, encoding='utf-8').read()
    check('ini ratio line rewritten', 'ratio=%s\n' % app.fmt_ratio(want) in ini_after.replace('\r\n', '\n'), True)
    check('ini comments intact', ini_after.count('#'), ini_before.count('#'))
    # restore the original ratio in the file and the app
    app.apply_ratio(old_ratio)
    check('ratio restored', open(ini_path, encoding='utf-8').read() == ini_before, True)
    app.toggle_enable()
    app.close_settings()

    # units persist
    app.toggle_units()
    with open(SETTINGS, encoding='utf-8') as fh:
        saved = json.load(fh)
    check('units saved', saved['units'], 'in')
    app.toggle_units()

    app.stage.export_to_png(os.path.join(ROOT, 'tests', 'portrait_main.png'))
    print('RESULT:', 'ALL PASS' if not fails else fails)
    app.stop()


Clock.schedule_once(run, 1.0)
app.run()
