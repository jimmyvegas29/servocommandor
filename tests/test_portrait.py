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
DATUMS = os.path.join(ROOT, 'tests', 'datums_test.json')
os.environ['SERVOCOM_SETTINGS'] = SETTINGS
os.environ['SERVOCOM_DATUMS'] = DATUMS
for _p in (SETTINGS, DATUMS):
    if os.path.exists(_p):
        os.remove(_p)

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
    check('preset 8 is SFM', ids.sp_btn8.text, 'SFM')
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

    # load goes red 20 points under the drive's overload alarm level (Pr070)
    check('red threshold from mock Pr070=140', app.red_at(), 120)
    app._show_load(119, False)
    check('119 not red', app.load_color, [1, 1, 1, 1])
    app._show_load(120, False)
    check('120 red', app.load_color, [0.95, 0.25, 0.2, 1])
    app.servo.params[70] = 250
    check('threshold follows Pr070=250', (app.red_at(), app.settings['overload_level']), (230, 250))
    app._show_load(229, False)
    check('229 not red at 250', app.load_color, [1, 1, 1, 1])
    app.servo.params[70] = 140
    app.red_at()
    app._on_graph_cursor(app.graph, -1)          # back to the live reading

    # load graph scrolled back: readout shows the sample at the right edge
    g = app.graph
    saved_hist = list(g.hist)
    g.hist = [10 + i for i in range(300)]        # 300 samples, newest = 309
    live_str = app.load_str
    g.view_offset = 40
    g.redraw()
    check('scrolled readout = right-edge sample', app.load_str, str(g.hist[-41]))
    g.add_sample(500)                             # history moves, view keeps its place
    check('scrolled readout tracks while data arrives', app.load_str, str(g.hist[-42]))
    g.go_live()
    check('live readout restored', (g.cursor_value, app.load_str), (-1, live_str))
    g.hist = saved_hist
    g.redraw()

    # offline overlay: dismissable, speed section locked, DRO usable
    servo.offline = True
    app._poll_ui(0)
    app._poll_ui(0)
    check('one or two misses: no popup yet', app._offline, None)
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
    check('menu has pages', sorted(ov._buttons), ['connection', 'display', 'drive', 'dro', 'sfm', 'speedpad', 'system'])
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
    check('presets re-applied', app.control_ids().sp_btn6.text, '800')
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
    check('cards presets', app.control_ids().sp_btn6.text, '800')
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
          ('Speed mode', 'Orientation', 'Build')), True)
    check('drive rows moved off system', any(l in labels for l in ('Ratio', 'Drive')), False)
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
    check('cal closed, drive page reopened',
          (app._ratio_cal, app._settings_overlay.page), (None, 'drive'))
    ini_after = open(ini_path, encoding='utf-8').read()
    check('ini ratio line rewritten', 'ratio=%s\n' % app.fmt_ratio(want) in ini_after.replace('\r\n', '\n'), True)
    check('ini comments intact', ini_after.count('#'), ini_before.count('#'))
    # restore the original ratio in the file and the app
    app.apply_ratio(old_ratio)
    check('ratio restored', open(ini_path, encoding='utf-8').read() == ini_before, True)
    app.toggle_enable()
    app.close_settings()

    # drive page: parameters read from the (mock) drive, edited, saved
    app.open_settings('drive')
    page = app._settings_overlay.ids.content.children[0]
    page.refresh()
    rows = dict((r.key, r) for r in page.ids.params.children)
    check('drive page rows', sorted(rows), sorted(d['key'] for d in m.DRIVE_PARAMS))
    check('torque limit read', rows['torque_limit'].value, '300 %')
    check('overload level read', rows['overload_level'].value, '140 %')
    check('drive info rows', [r.label for r in page.ids.info.children][::-1][:3],
          ['Average load', 'Drive', 'Ratio'])
    app._poll_ui(0)
    page.refresh()
    check('average load row live', page._avg_row.value.endswith(' %'), True)
    check('edit allowed while disabled', (app.drive_edit_ok, page.status), (True, ''))
    app.open_param_edit('overload_level')
    ed = app._param_edit
    check('editor shows current', (ed.title, ed.current), ('Overload level', '140 %'))
    for ch in '350':
        ed.add_digit(ch)
    check('editor flags out of range', ed.over, True)
    ed.accept()
    check('out of range not written', app.servo.params[70], 140)
    ed.clear()
    for ch in '200':
        ed.add_digit(ch)
    ed.accept()
    check('overload level written both signs', (app.servo.params[70], app.servo.params[71]), (200, -200))
    check('editor closed, value kept by panel', (app._param_edit, app.settings['drive_params']),
          (None, {'70': 200, '71': -200}))
    page.refresh()
    check('row shows new value', rows['overload_level'].value, '200 %')
    app.open_drive_info()
    check('drive info popup lists the change', 'Overload level' in app._info.body, True)
    app.close_info()
    check('info closed', app._info, None)
    app.toggle_enable()
    page.refresh()
    check('no edit while enabled', (app.drive_edit_ok, page.status), (False, 'Disable the servo to change parameters'))
    check('write refused while enabled', app.apply_drive_param('overload_level', 150), False)
    app.toggle_enable()
    page.refresh()
    # the drive "forgets" at power-off: on the next link the panel writes it back
    app.servo.params[70], app.servo.params[71] = 140, -140
    app._params_requested = False
    app._poll_ui(0)                                  # first poll: read requested
    app._poll_ui(0)                                  # second poll: re-apply
    check('kept values re-applied', (app.servo.params[70], app.servo.params[71]), (200, -200))
    app.apply_drive_param('overload_level', 140)
    app.settings['drive_params'] = {}
    app._save_settings()
    app.close_settings()

    # overlays swallow touches: tapping where the gear sits while SET is
    # open must not open settings (it did, through the axis label)
    from kivy.base import EventLoop
    from kivy.core.window import Window
    from kivy.input.motionevent import MotionEvent

    class UnitTestTouch(MotionEvent):
        """Synthetic touch in window pixels (kivy.tests needs pytest)."""
        def __init__(self, x, y):
            super().__init__('unittest', 99, {'x': x / Window.width, 'y': y / Window.height},
                             is_touch=True, type_id='touch')

        def depack(self, args):
            self.sx, self.sy = args['x'], args['y']
            self.profile = ['pos']
            super().depack(args)

        def touch_down(self):
            EventLoop._dispatch_input('begin', self)
            EventLoop.dispatch_input()          # process the queued event now

        def touch_up(self):
            EventLoop._dispatch_input('end', self)
            EventLoop.dispatch_input()

    app.open_set('X')
    gear = app.root_layout.children[-1].children[0]     # TitleBar's IconButton
    gx, gy = gear.center
    app.stage.do_layout()        # size the overlay now (normally next frame)
    t = UnitTestTouch(gx, gy)
    t.touch_down()
    t.touch_up()
    check('gear blocked behind SET overlay', app._settings_overlay, None)
    check('SET overlay still open', app._set_overlay is not None, True)
    app.close_set()
    t = UnitTestTouch(gx, gy)
    t.touch_down()
    t.touch_up()
    check('gear works with no overlay', app._settings_overlay is not None, True)
    app.close_settings()

    # flip display: rotation applies only on the panel, but the setting
    # persists and the stage rebuilds
    app.set_flip(True)
    check('flip on', app.flip, True)
    with open(SETTINGS, encoding='utf-8') as fh:
        check('flip saved', json.load(fh)['flip'], True)
    app.set_flip(False)
    check('flip off', app.flip, False)

    # scale feed: raw counts -> ABS through the datum offset
    from dro_serial import parse_line, DroSerial
    check('parse good line', parse_line('DRO X:12345 Z:-6789 S:3 T:100'),
          {'x': 12345, 'z': -6789, 's': 3, 't': 100})
    check('parse banner ignored', parse_line('DRO tap firmware v1'), None)
    check('parse junk ignored', parse_line('X:1 Z:2'), None)
    app.select_mode(0)
    app.apply_set('X', 0.0)
    app.apply_set('Z', 0.0)
    app.dro = DroSerial('/nonexistent')          # never opens a port
    app.dro.feed('DRO X:12345 Z:-6789 S:1 T:1')
    app._poll_dro(0)
    # x_invert / z_invert are true in servo.ini, so signs flip
    check('X from counts', app.x_val, '-12.345')
    check('Z from counts', app.z_val, '+6.789')
    check('feed live', app.dro_stale, False)
    app.zero_axis('X')
    check('ABS zero with live raw', app.x_val, '+0.000')
    app.dro.feed('DRO X:13345 Z:-6789 S:2 T:2')
    app._poll_dro(0)
    check('moves 1mm after zero', app.x_val, '-1.000')
    app.select_mode(1)                            # INC
    app.zero_axis('X')
    app.dro.feed('DRO X:13845 Z:-6789 S:3 T:3')
    app._poll_dro(0)
    check('INC tracks raw', app.x_val, '-0.500')
    app.select_mode(0)
    check('ABS still tracks raw', app.x_val, '-1.500')
    app.zero_axis('X')
    app.zero_axis('X')
    check('un-zero with live raw', app.x_val, '-1.500')
    app.apply_set('X', 0.0)
    app.dro.feed('DRO X:0 Z:0 S:4 T:4')
    app._poll_dro(0)
    app.apply_set('X', 0.0)
    app.apply_set('Z', 0.0)
    app.dro = None
    app.dro_stale = False

    Clock.schedule_once(after_layout, 0.3)     # let the rebuilt root lay out


def after_layout(dt):
    from dro_serial import DroSerial
    # tabular digits: the decimal point and every digit slot stay put no
    # matter which digits are showing
    card = app.root_layout.ids.dro.children[-1]          # X AxisCard
    fd = [w for w in card.children if type(w).__name__ == 'FixedDigits'][0]
    app.dro = DroSerial('/nonexistent')
    app.dro.feed('DRO X:-111111 Z:0 S:1 T:1')       # x_invert -> +111.111
    app._poll_dro(0)
    cells_1 = fd.cells()
    app.dro.feed('DRO X:-888888 Z:0 S:2 T:2')
    app._poll_dro(0)
    cells_8 = fd.cells()
    check('digit strings differ', (fd.text, [c[0] for c in cells_1] != [c[0] for c in cells_8]),
          ('+888.888', True))
    check('slot positions identical', [(x, w) for _c, x, w in cells_1],
          [(x, w) for _c, x, w in cells_8])
    dot_1 = [x for c, x, _w in cells_1 if c == '.'][0]
    dot_8 = [x for c, x, _w in cells_8 if c == '.'][0]
    check('decimal point does not move', dot_1, dot_8)
    check('font size fixed', fd.font_px > 40, True)
    app.dro.feed('DRO X:0 Z:0 S:3 T:3')
    app._poll_dro(0)

    # DRO settings: direction and resolution per axis
    app.dro.feed('DRO X:2000 Z:2000 S:4 T:4')
    app._poll_dro(0)
    app.apply_set('X', 0.0)
    app.apply_set('Z', 0.0)
    app.set_dro_invert('X', False)
    check('X invert off flips reading', app.x_val, '+4.000')      # -2 -> +2 around datum -2
    app.set_dro_um('Z', 5)
    check('Z at 5um per count', app.z_val, '-8.000')              # -10 - (-2)
    with open(SETTINGS, encoding='utf-8') as fh:
        s = json.load(fh)
    check('dro settings saved', (s['dro_x_invert'], s['dro_z_um']), (False, 5))
    app.set_dro_invert('X', True)
    app.set_dro_um('Z', 1)
    app.apply_set('X', 0.0)
    app.apply_set('Z', 0.0)

    # datums persist: save, then simulate a power cycle
    app.apply_set('X', 25.0)                      # ABS reads 25 at raw -2
    app.select_mode(3)                            # SDM 2
    app.apply_set('X', 3.0)
    app.select_mode(0)
    app._save_datums()
    with open(DATUMS, encoding='utf-8') as fh:
        d = json.load(fh)
    check('datums file written', (round(d['raw']['X'], 3), d['mode_index']), (-2.0, 0))
    # "power cycle": fresh in-memory state, board restarts counting at 0
    saved_abs = app.x_val
    app.abs_off = {'X': 0.0, 'Z': 0.0}
    app.offs = {ax: {'INC': 0.0, 'SDM': [0.0] * app.SDM_COUNT} for ax in ('X', 'Z')}
    app._load_datums()
    check('datums reloaded (SDM 2 kept)', app.offs['X']['SDM'][1] != 0.0, True)
    app.dro.feed('DRO X:0 Z:0 S:1 T:1')           # board rebooted: counts from 0
    app._poll_dro(0)
    check('reading restored after power cycle', app.x_val, saved_abs)
    app.select_mode(3)
    check('SDM 2 restored', app.x_val, '+3.000')
    app.select_mode(0)
    app.dro.feed('DRO X:-1000 Z:0 S:2 T:2')       # move 1mm (inverted axis)
    app._poll_dro(0)
    check('still tracks after resync', app.x_val, '+26.000')
    # app-only restart with the board still counting: no false shift
    app._save_datums()
    app._load_datums()
    app.dro.feed('DRO X:-1000 Z:0 S:3 T:3')
    app._poll_dro(0)
    check('app restart, board kept counting', app.x_val, '+26.000')
    app.apply_set('X', 0.0)
    app.dro.feed('DRO X:0 Z:0 S:4 T:4')
    app._poll_dro(0)
    app.apply_set('X', 0.0)
    app.dro = None
    app.dro_stale = False

    # 1/2 centerline function
    app.select_mode(0)
    app.apply_set('X', 25.0)
    app.apply_set('Z', -8.0)
    app.axis_tap('X')
    check('letter inert when not armed', app.x_val, '+25.000')
    app.arm_half()
    check('armed', app.half_armed, True)
    app.axis_tap('X')
    check('X halved', app.x_val, '+12.500')
    check('disarmed after use', app.half_armed, False)
    check('Z untouched', app.z_val, '-8.000')
    app.arm_half()
    app.arm_half()
    check('arm toggles off', app.half_armed, False)
    app.select_mode(1)                            # INC: halve the INC reading
    app.zero_axis('Z')
    app.apply_set('Z', 5.0)
    app.arm_half()
    app.axis_tap('Z')
    check('halve in INC', app.z_val, '+2.500')
    app.select_mode(0)
    check('ABS Z unaffected by INC halve', app.z_val, '-8.000')
    app.arm_half()
    app._disarm_half()
    app.apply_set('X', 0.0)
    app.apply_set('Z', 0.0)

    # copy a reading into several datums (double-tap picker)
    app.select_mode(0)
    app.apply_set('X', 40.0)
    app.select_mode(2)                            # SDM 1 reads 40 too (offset 0)
    app.zero_axis('X')                            # SDM 1 -> 0
    app.open_copy('X')
    ov = app._copy_overlay
    check('copy picker title value', (ov.axis, ov.value_text), ('X', '+0.000'))
    check('current datum greyed', ov._buttons['SDM 1'].disabled, True)
    ov.toggle('SDM 3')
    ov.toggle('SDM 7')
    ov.toggle('INC')
    ov.toggle('SDM 7')                            # untoggle
    check('selection', ov.selected(), ['INC', 'SDM 3'])
    ov.apply()
    check('picker closed', app._copy_overlay, None)
    app.select_mode(4)                            # SDM 3
    check('SDM 3 now reads 0', app.x_val, '+0.000')
    app.select_mode(1)                            # INC
    check('INC now reads 0', app.x_val, '+0.000')
    app.select_mode(8)                            # SDM 7 untouched
    check('SDM 7 untouched', app.x_val, '+40.000')
    app.select_mode(0)
    check('ABS untouched', app.x_val, '+40.000')
    app.open_copy('X')
    ov = app._copy_overlay
    ov.select_all(True)
    check('ALL selects 21', ov.selected_count, 21)
    ov.select_all(False)
    check('NONE clears', ov.selected_count, 0)
    app.close_copy()
    app.apply_set('X', 0.0)
    for ax in ('X', 'Z'):
        app.offs[ax]['INC'] = 0.0
        app.offs[ax]['SDM'] = [0.0] * app.SDM_COUNT

    # DRO link switch: USB <-> Bluetooth keeps the readout continuous
    import struct
    from dro_ble import DroBle, parse_packet
    check('ble packet parse', parse_packet(struct.pack('<IiiI', 7, 1234, -50, 999)),
          {'s': 7, 'x': 1234, 'z': -50, 't': 999})
    check('ble bad packet', parse_packet(b'short'), None)
    app.select_mode(0)
    app.dro = DroSerial('/nonexistent')
    app.dro.feed('DRO X:-5000 Z:0 S:1 T:1')        # raw X = +5.000 (inverted)
    app._poll_dro(0)
    app.apply_set('X', 10.0)                        # ABS reads 10 at raw 5
    check('usb reading', app.x_val, '+10.000')
    app.set_dro_link('ble')
    check('link is ble', (app.dro_link, type(app.dro).__name__), ('ble', 'DroBle'))
    with open(SETTINGS, encoding='utf-8') as fh:
        check('link saved', json.load(fh)['dro_link'], 'ble')
    # the BLE board's counter happens to be at a different raw value
    app.dro.feed(struct.pack('<IiiI', 1, -8000, 0, 1))      # raw X = +8.000
    app._poll_dro(0)
    check('reading continuous across link switch', app.x_val, '+10.000')
    app.dro.feed(struct.pack('<IiiI', 2, -9000, 0, 2))      # +1 mm
    app._poll_dro(0)
    check('tracks on ble', app.x_val, '+11.000')
    check('status mentions BT', app.dro_status.startswith('BT'), True)
    picker = m.BlePickerOverlay()
    app._show('_ble_picker', picker)
    picker.populate([('AA:BB:CC:DD:EE:01', 'SERVOCOM-DRO-0001', -50),
                     ('AA:BB:CC:DD:EE:02', 'SERVOCOM-DRO-0002', -70)], '')
    check('picker lists boards', len(picker.ids.grid.children), 2)
    app.select_ble_board('AA:BB:CC:DD:EE:02', 'SERVOCOM-DRO-0002')
    check('board chosen', (app.ble_address, app.ble_name, app._ble_picker),
          ('AA:BB:CC:DD:EE:02', 'SERVOCOM-DRO-0002', None))
    check('reader targets the board', app.dro.address, 'AA:BB:CC:DD:EE:02')
    app.set_dro_link('usb')
    check('back to usb', type(app.dro).__name__, 'DroSerial')
    app.dro.stop()
    app.dro = DroSerial('/nonexistent')
    app.dro.feed('DRO X:0 Z:0 S:1 T:1')
    app._poll_dro(0)
    app.apply_set('X', 0.0)
    app.ble_address = ''
    app.ble_name = ''
    app._save_settings()
    app.dro = None
    app.dro_stale = False

    # speed pad: presets 1-6 editable, 7-9 are the tools menu / SFM / JOG
    import speedpad
    ids = app.control_ids()
    check('buttons 7-9 relabelled', (ids['sp_btn7'].text, ids['sp_btn8'].text, ids['sp_btn9'].text),
          ('[font=' + app.fa + ']\uf0c9[/font]', 'SFM', 'JOG'))
    check('preset 1 default from ini', app.preset_value(1), 50)
    app._set_preset(1, 75)
    check('preset 1 override applied', (ids['sp_btn1'].text, app.preset_value(1),
                                         app.settings['speed_pad']['rpm']['1']), ('75', 75, 75))
    app.preset_press(ids['sp_btn1'])
    check('override preset sets speed', app.command_speed, round(75 * app.ratio))
    app.open_settings('speedpad')
    page = app._settings_overlay.ids.content.children[0]
    labels = [r.label for r in page.ids.rows.children][::-1]
    check('speed pad rows', (labels[0], labels[1], labels[6], labels[7], len(labels)),
          ('Step buttons', 'Button 1', 'Button 6', 'Jog speed', 8))
    app._settings_overlay.select('sfm')
    sfm_page = app._settings_overlay.ids.content.children[0]
    sfm_labels = [r.label for r in sfm_page.ids.rows.children][::-1]
    check('sfm page rows', (sfm_labels[0], sfm_labels[2], sfm_labels[8], len(sfm_labels)),
          ('Mild steel', 'High carbon', 'Mild steel', 16))
    app._settings_overlay.select('speedpad')
    page = app._settings_overlay.ids.content.children[0]
    check('step default from ini', (app.step_value(), ids['inc_btnp'].text, ids['inc_btnn'].text), (50, '+50', '-50'))
    app.open_pad_edit('step')
    for ch in '10':
        app._param_edit.add_digit(ch)
    app._param_edit.accept()
    check('step changed', (app.step_value(), ids['inc_btnp'].text, ids['inc_btnn'].text), (10, '+10', '-10'))
    app.set_speed(600)
    app.adjust_speed(int(ids['inc_btnp'].text))
    check('step button adds 10', app.command_speed, round(610 * app.ratio))
    app.open_pad_edit('preset:1')
    ed = app._param_edit
    check('pad editor generic', (ed.title, ed.accept_text, ed.current), ('Button 1', 'SAVE', '75 rpm'))
    for ch in '50':
        ed.add_digit(ch)
    ed.accept()
    check('pad editor saved and closed', (app.preset_value(1), app._param_edit), (50, None))
    app.open_pad_edit('jog')
    for ch in '12':
        app._param_edit.add_digit(ch)
    app._param_edit.accept()
    check('jog rpm saved', app.jog_rpm(), 12)
    app.close_settings()

    # button 7 is the tools menu; Drill opens the drill popup and closes the menu
    app.open_tools()
    check('tools menu open', app._tools is not None, True)
    app.tools_pick('tap')
    check('tap not built: menu stays', (app._tools is not None, app._drill), (True, None))
    app.tools_pick('drill')
    check('drill from the menu', (app._tools, app._drill is not None), (None, True))
    app.close_drill()

    # drill: 1/4 in mild steel at 90 SFM -> 1375 rpm
    check('rpm_for', round(speedpad.rpm_for(90, 0.25)), 1375)
    app.open_drill()
    d = app._drill
    d.set_tool('hss')
    d.set_material('Mild steel')
    d.choose('1/4', 0.25)
    check('drill rpm', (d.rpm, d.capped), (1375, False))
    d.set_tool('cbd')
    check('drill carbide capped', (d.rpm, d.capped), (6112, True))
    d.set_tool('hss')
    d.choose('1/8', 0.125)
    check('drill capped at spindle max', (d.rpm, d.rpm_set, d.capped), (2750, app.max_spindle_rpm(), True))
    d.set_unit('mm')
    check('mm presets 6..20', [b.text for b in d.ids.sizes.children][::-1][:3] + [d.ids.sizes.children[0].text],
          ['6', '7', '8', '20'])
    for ch in '6.5':
        d.add_dot() if ch == '.' else d.add_digit(ch)
    check('drill typed mm', (d.entry, d.size_text, d.rpm), ('6.5', '6.5 mm', round(speedpad.rpm_for(90, 6.5 / 25.4))))
    d.backspace()
    d.backspace()
    check('drill backspace', (d.entry, d.size_text), ('6', '6 mm'))
    d.choose('8', 8 / 25.4)
    check('picking a preset clears the entry', (d.entry, d.size_text), ('', '8 mm'))
    for ch in '6.5':
        d.add_dot() if ch == '.' else d.add_digit(ch)
    d.accept()
    check('drill set speed and closed', (app.command_speed, app._drill),
          (round(round(speedpad.rpm_for(90, 6.5 / 25.4)) * app.ratio), None))
    d_unit = app.settings['speed_pad']['drill_unit']
    check('drill unit remembered', d_unit, 'mm')

    # sfm calculator: 2.125 in at 445 SFM -> 800 rpm, feed line
    app.open_sfm()
    o = app._sfm
    o.set_unit('inch')
    o.set_diameter(2.125)
    o.set_tool('cbd')
    o.set_material('Mild steel')
    check('sfm material button', (o.sfm, o.rpm), (400, 719))
    o.set_tool('hss')
    check('sfm tool switch reloads', (o.sfm, o.rpm), (90, 162))
    o.set_tool('cbd')
    o.set_sfm(445)
    check('sfm rpm', (o.rpm, o.material), (800, ''))
    o.accept()
    check('sfm set speed and closed', (app.command_speed, app._sfm), (round(800 * app.ratio), None))

    # constant SFM: learn the way to centre (needed before ACTIVATE),
    # ACTIVATE swaps in the CSS panel, START anchors the pass where X is,
    # IN: past centre + run-over the pass is DONE; OUT: past the OD +
    # run-over.  STOP = drive off + old speed.  The DRO display is never
    # touched.
    app.dro = DroSerial('/nonexistent')
    seq = [0]
    x0 = 40000                                    # counts; on this lathe 'in' = counts going down

    def feed_x(counts):
        seq[0] += 1
        app.dro.feed('DRO X:%d Z:0 S:%d T:%d' % (counts, seq[0], seq[0]))
        app._poll_dro(0)

    def at_radius(r_mm):
        # counts that put the tool r_mm from centre, for a pass started at x0 on a 2 in part
        feed_x(round(x0 - (25.4 - r_mm) * 1000.0 / app.dro_x_um))

    def rpm_m(rpm):
        return round(rpm * app.ratio)

    feed_x(x0)
    app.set_speed(400)
    base = app.command_speed
    app.save_speed_pad(css_sfm=400, css_top=1500, css_material='', css_tool='cbd', css_over_mm=0.5,
                       css_start_dia_mm=0, css_in_sign=0, css_dir='in')
    x_shown = app.x_val
    app.open_tools()
    app.tools_pick('css')
    o = app._css
    check('css popup from the menu', (app._tools, o is not None), (None, True))
    check('css not learned yet', (o.learn_btn, o.learned), ('LEARN', False))
    o.primary()
    check('ACTIVATE refused until the direction is learned', (app.css_mode, app._css is o), (False, True))
    app.open_pad_edit('css_learn')
    check('learn waits for movement', (app.css_learning, app._param_edit), (True, None))
    feed_x(x0 - 20)                               # 0.02 mm: not enough yet
    app._css_learn_tick(0)
    check('learn ignores a small wiggle', app.css_learning, True)
    feed_x(x0 - 80)
    app._css_learn_tick(0)
    o.refresh()
    check('learned: counts going down = toward centre',
          (app.css_learning, app.css_config()['in_sign'], o.learn_btn, o.learned), (False, -1, 'RELEARN', True))
    o.set_start_dia(2.0 if app.units == 'in' else 50.8)
    check('css live line', o.live_text, '400 SFM at OD %s  ->  764 rpm at START' % o.start_dia)
    o.primary()
    check('css ACTIVATE: panel in, popup closed, speed untouched',
          (app.css_mode, app.css_state, app._css, app.command_speed), (True, 'ready', None, base))
    check('css ready card', (app.css_badge, app.css_left_text, app.css_right_text, app.css_frac, app.css_can_start),
          ('READY', '764 rpm', '1500 rpm', 0.0, True))
    kinds = sorted(k for _f, k in app.css_marks)
    check('bar marks: 9 minor and the center', (kinds.count('minor'), kinds.count('major'), len(kinds)), (9, 1, 10))
    app.set_speed(600)
    app.adjust_speed(50)
    check('pad speed changes ignored while CSS is up', app.command_speed, base)
    feed_x(x0)                                    # user brings X back to the start point
    check('css START', app.css_start(), True)
    check('css running at the start diameter', (app.css_state, app.css_badge, app.command_speed),
          ('running', 'RUNNING', rpm_m(764)))
    app.css_exit()
    check('EXIT does nothing while running', (app.css_mode, app.css_state), (True, 'running'))
    at_radius(13.03)                              # 1490 rpm: just under the top
    app._css_tick(0)
    check('near the top', app.command_speed, rpm_m(round(speedpad.rpm_for(400, 2 * 13.03 / 25.4))))
    at_radius(12.9)                               # 1504 wanted: capped, a step under 1 %
    app._css_tick(0)
    check('small last step still reaches the top limit', app.command_speed, rpm_m(1500))
    check('bar fills with the travel', round(app.css_frac, 3), round((25.4 - 12.9) / 25.9, 3))
    at_radius(12.7)                               # half the radius: 1528 rpm wanted
    app._css_tick(0)
    check('toward centre stops at the top limit', app.command_speed, rpm_m(1500))
    at_radius(50.8)                               # out to a 4 in diameter
    app._css_tick(0)
    check('bigger diameter slows down', app.command_speed, rpm_m(382))
    sends = app.servo.rpm
    at_radius(50.9)                               # 381 rpm: inside the 1 % deadband
    app._css_tick(0)
    check('deadband: no resend for 1 rpm', (app.command_speed, app.servo.rpm), (rpm_m(382), sends))
    at_radius(-0.3)                               # past centre, inside the run-over
    app._css_tick(0)
    check('past centre: top speed, still running', (app.css_state, app.command_speed), ('running', rpm_m(1500)))
    at_radius(-0.6)                               # past the 0.5 mm run-over
    app._css_tick(0)
    check('run-over reached: pass DONE, speed held', (app.css_state, app.css_badge, app.command_speed),
          ('done', 'DONE', rpm_m(1500)))
    check('bar full when done', app.css_frac, 1.0)
    at_radius(-5.0)
    app._css_tick(0)
    check('DONE holds, no slowing back down', app.command_speed, rpm_m(1500))
    app.toggle_enable()
    check('drive enabled for the STOP check', app.servo_state, 'enabled')
    app.css_stop()
    check('STOP: drive off, speed back to before CSS', (app.css_state, app.servo_state, app.command_speed),
          ('ready', 'disabled', base))
    at_radius(25.4)
    check('second pass starts', app.css_start(), True)
    app.dro_stale = True
    app._css_tick(0)
    check('DRO lost mid-pass: hold', (app.css_badge, app.command_speed), ('HOLD', rpm_m(764)))
    app.dro_stale = False
    at_radius(10.0)
    app._css_tick(0)
    check('DRO back: stays on hold until restarted', (app.css_badge, app.command_speed), ('HOLD', rpm_m(764)))
    app.css_stop()

    # OUT: start at centre, top speed there, slows as the tool moves out,
    # DONE past the OD plus the run-over
    app.save_speed_pad(css_dir='out')
    app._css_tick(0)
    check('OUT ready card', (app.css_badge, app.css_left_text, app.css_right_text, app.css_dia_text),
          ('READY', '1500 rpm', '764 rpm', 'from center'))
    feed_x(x0)                                    # tool at centre
    check('OUT start', app.css_start(), True)
    check('OUT starts at the top speed', app.command_speed, rpm_m(1500))

    def out_at(r_mm):                             # outward = counts going up here
        feed_x(round(x0 + r_mm * 1000.0 / app.dro_x_um))

    out_at(19.05)                                 # 1.5 in diameter
    app._css_tick(0)
    check('OUT slows as the diameter grows', app.command_speed, rpm_m(1019))
    out_at(25.7)                                  # past the 1 in radius, inside the run-over
    app._css_tick(0)
    check('OUT past the OD, inside the run-over', app.css_state, 'running')
    out_at(26.0)
    app._css_tick(0)
    check('OUT run-over reached: DONE', (app.css_state, app.css_badge, app.css_fill), ('done', 'DONE', [0.4, 0.85, 0.5, 1]))
    app.css_stop()
    app.save_speed_pad(css_dir='in')
    app.css_exit()
    check('EXIT: pad back, speed as before', (app.css_mode, app.css_state, app.command_speed), (False, '', base))
    feed_x(x0)
    check('DRO display never touched by CSS', app.x_val, x_shown)
    app.set_speed(600)
    check('pad works again after EXIT', app.command_speed, rpm_m(600))
    app.dro = None
    app.dro_stale = False

    # jog: hold sends keep-alives at the jog speed, release stops and restores
    app.set_speed(600)
    app.servo.hw_direction = None            # lever OFF (an earlier check left it in FWD)
    app._poll_ui(0)
    check('jog allowed while disabled', app.jog_ok, True)
    before = app.servo.jog_calls if hasattr(app.servo, 'jog_calls') else 0
    check('jog press', app.jog_press(), True)
    check('jog running', (app.jogging, app.servo.servostate, app.servo.rpm), (True, 'enabled', round(12 * app.ratio)))
    check('jog readout shows jog rpm lit', (app.rpm_str, app.rpm_colors[3]), ('0012', m.WHITE))
    app._jog_tick(0)
    check('jog keep-alives', app.servo.jog_calls - before, 2)
    app.jog_release()
    check('jog stopped', (app.jogging, app.servo.servostate, app.servo_state), (False, 'disabled', 'disabled'))
    check('readout back to the setpoint, dim', (app.rpm_str, app.rpm_colors[3]), ('0600', m.DIM))
    app.toggle_enable()
    app._poll_ui(0)
    check('no jog while enabled', (app.jog_ok, app.jog_press()), (False, False))
    app.toggle_enable()
    app.settings['speed_pad'] = {}
    app._save_settings()
    app._apply_presets(app.root_layout)


    # machine node: drive data and commands through the Bluetooth packet
    from dro_ble import parse_packet as _pp, F_ONLINE, F_FWD, F_ENABLED, F_CONTROL, F_CMD_OK
    pkt = struct.pack('<IiiIhhHB', 9, 100, 200, 5, -6600, 42, 0, F_ONLINE | F_FWD | F_CMD_OK)
    nd = _pp(pkt)
    check('node packet parsed', (nd['rpm'], nd['torque'], nd['online'], nd['switch'], nd['control']),
          (-6600, 42, True, 'fwd', False))
    app.set_dro_link('ble')
    app.set_drive_link('node')
    check('drive link is node', (app.drive_link, type(app.servo).__name__), ('node', 'NodeServo'))
    app.dro.feed(pkt)
    app._poll_dro(0)
    app._poll_ui(0)
    check('node rpm decoded (-6600 x0.1 -> 660 motor rpm)', app.current_speed, 660)
    check('node torque decoded', app.current_torque, 42)
    check('node direction synced from switch', app.direction, 'fwd')
    check('node read-only flagged', app.node_control, False)
    check('offline overlay not shown when node online', app._offline, None)
    sent_before = app.dro.cmds_sent
    app.set_speed(600)                      # goes out as a command, node will refuse
    check('command attempted over BLE (no link => 0 sent)', app.dro.cmds_sent, sent_before)
    pkt2 = struct.pack('<IiiIhhHB', 10, 100, 200, 6, 0, 0, 0, F_CMD_OK)   # node says drive offline
    app.dro.feed(pkt2)
    app._poll_dro(0)
    for _ in range(3):                      # popup only after three missed polls
        app._poll_ui(0)
    check('node reports drive offline -> popup', app._offline is not None, True)
    # DRO capture: ring holds raw + UI lines, save writes a file, old ones pruned
    check('capture ring has raw and UI lines',
          (any(' UI ' in l for l in app.dro.ring), any(' raw=' in l for l in app.dro.ring)), (True, True))
    cap_path = app.save_dro_capture()
    check('capture saved', cap_path is not None and os.path.exists(cap_path), True)
    check('capture status', app.capture_status.startswith('Saved'), True)
    if cap_path:
        os.remove(cap_path)
    # SEND LOG: bundle built, uploaded through a fake transport, folder cleared
    import diag_upload
    uploaded = []

    def fake_put(token, repo_path, data, message):
        uploaded.append((repo_path, len(data)))
    app.uploader = diag_upload.Uploader(transport=fake_put)
    app.settings['panel_name'] = 'Test Panel #1'
    manifest = app._diag_manifest()
    check('manifest has build and settings', ('build' in manifest, 'settings' in manifest, manifest['panel']),
          (True, True, 'Test-Panel-1'))
    cap_path = app.save_dro_capture()
    bundle = diag_upload.build_bundle(app._panel_name(), cap_path, manifest, None)
    check('bundle pending', len(diag_upload.pending_bundles()), 1)
    app.uploader.send_now()
    app.uploader._thread.join(10)
    check('bundle uploaded and cleared',
          (sorted(p.split('/')[0] for p, n in uploaded), len(uploaded), diag_upload.pending_bundles()),
          (['Test-Panel-1', 'Test-Panel-1'], 2, []))
    check('upload status', app.uploader.status()[0], 'sent')
    app.settings['panel_name'] = ''
    if cap_path and os.path.exists(cap_path):
        os.remove(cap_path)
    app.dismiss_offline()
    app.set_drive_link('hat')
    check('back to hat', type(app.servo).__name__, 'ServoCommunicator')
    app.set_dro_link('usb')
    app.dro.stop()
    app.dro = DroSerial('/nonexistent')
    app.dro.feed('DRO X:0 Z:0 S:1 T:1')
    app._poll_dro(0)
    app.apply_set('X', 0.0)
    app.apply_set('Z', 0.0)
    app.dro = None
    app.dro_stale = False
    app.servo.offline = False
    app._poll_ui(0)

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
