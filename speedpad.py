"""Speed pad: adjustable presets 1-6, DRILL / SFM calculators, hold-to-JOG.

Positions on the 3x3 speed grid run left to right, top to bottom:
1-6 are user presets (spindle rpm, or surface speed in that mode), 7 is
DRILL, 8 is SFM and 9 is JOG.  The values live in settings.json under
'speed_pad'; servo.ini keeps the factory defaults.
"""
import math

from kivy.app import App
from kivy.properties import (StringProperty, NumericProperty, BooleanProperty,
                             ListProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.clock import Clock

from portrait_ui import ModalTouch

# Surface speeds (ft/min) per material, one table per tool: HSS and coated
# carbide (CBD).  Both popups use them; the user can change every value on
# the Speed Pad page.  High carbon = 4130 / 4140 alloy steels.
MATERIALS = ['Mild steel', 'Medium carbon', 'High carbon', 'Stainless', 'Cast iron',
             'Aluminum', 'Brass', 'Plastic']
DEFAULT_SFM = {
    'hss': {'Mild steel': 90, 'Medium carbon': 70, 'High carbon': 60, 'Stainless': 50,
            'Cast iron': 70, 'Aluminum': 250, 'Brass': 200, 'Plastic': 150},
    'cbd': {'Mild steel': 400, 'Medium carbon': 350, 'High carbon': 300, 'Stainless': 250,
            'Cast iron': 300, 'Aluminum': 800, 'Brass': 500, 'Plastic': 600},
}
TOOL_NAMES = {'hss': 'HSS', 'cbd': 'carbide'}

# drill size lists: 15 each - inch 1/8 .. 1 in 1/16 steps, metric 6 .. 20 mm
INCH_SIZES = [(n, 16) for n in range(2, 17)]
MM_SIZES = list(range(6, 21))
JOG_RPM_DEFAULT = 5
JOG_RPM_MAX = 60


def frac_label(n, d):
    while n % 2 == 0 and d % 2 == 0:
        n //= 2
        d //= 2
    return '%d' % n if d == 1 else '%d/%d' % (n, d)


def rpm_for(sfm, dia_in):
    """Spindle rpm for a surface speed (ft/min) and a diameter (inches)."""
    if dia_in <= 0:
        return 0
    return sfm * 12.0 / (math.pi * dia_in)


def fmt_num(v, places=3):
    s = ('%.*f' % (places, v)).rstrip('0').rstrip('.')
    return s if s else '0'


class DrillOverlay(ModalTouch, FloatLayout):
    """Pick a drill size and material -> recommended spindle rpm -> SET."""
    unit = StringProperty('inch')            # 'inch' | 'mm'
    tool = StringProperty('hss')             # 'hss' | 'cbd'
    material = StringProperty('Mild steel')
    size_text = StringProperty('')           # label of the chosen size
    dia_in = NumericProperty(0.0)            # chosen diameter in inches
    sfm = NumericProperty(0)
    rpm = NumericProperty(0)                 # recommended, uncapped
    rpm_set = NumericProperty(0)             # what SET will command (capped)
    capped = BooleanProperty(False)
    result_text = StringProperty('Pick a size')
    entry = StringProperty('')               # keypad: a custom size being typed

    def populate(self):
        app = App.get_running_app()
        sp = app.settings.get('speed_pad', {})
        self.material = sp.get('drill_material', self.material)
        self.unit = sp.get('drill_unit', self.unit)
        self.tool = sp.get('drill_tool', 'hss')
        self._fill_sizes()
        self._compute()

    def set_tool(self, tool):
        self.tool = tool
        self._compute()
        App.get_running_app().save_speed_pad(drill_tool=tool)

    def _fill_sizes(self):
        grid = self.ids.sizes
        grid.clear_widgets()
        app = App.get_running_app()
        if self.unit == 'inch':
            items = [(frac_label(n, d), n / float(d)) for n, d in INCH_SIZES]
        else:
            items = [('%d' % mm, mm / 25.4) for mm in MM_SIZES]
        for label, dia in items:
            b = Button(text=label, font_name=app.font, font_size='18sp',
                       background_color=(0, 0, 0, 0), background_normal='',
                       size_hint_y=None, height=48)
            b.dia_in = dia
            b.bind(on_press=lambda btn: self.choose(btn.text, btn.dia_in))
            grid.add_widget(b)
        self._restyle()

    def _restyle(self):
        for b in self.ids.sizes.children:
            b.selected = (b.text == self.size_text)
            b.canvas.before.clear()
            from kivy.graphics import Color, RoundedRectangle
            with b.canvas.before:
                Color(0, 0.5, 1, 1) if b.selected else Color(0.16, 0.16, 0.16, 1)
                b._rr = RoundedRectangle(pos=b.pos, size=b.size, radius=[(6, 6)] * 4)
            b.bind(pos=self._sync_rr, size=self._sync_rr)

    @staticmethod
    def _sync_rr(btn, *a):
        rr = getattr(btn, '_rr', None)
        if rr is not None:
            rr.pos, rr.size = btn.pos, btn.size

    def set_unit(self, unit):
        if unit != self.unit:
            self.unit = unit
            self.entry = ''
            self.size_text = ''
            self.dia_in = 0.0
            self._fill_sizes()
            self._compute()
            App.get_running_app().save_speed_pad(drill_unit=unit)

    def set_material(self, name):
        self.material = name
        self._compute()
        App.get_running_app().save_speed_pad(drill_material=name)

    def choose(self, label, dia_in):
        self.entry = ''
        self.size_text = label + (' in' if self.unit == 'inch' else ' mm')
        self.dia_in = dia_in
        self._restyle()
        self._compute()

    def custom_size(self, value):
        """A typed size: inches or mm depending on the unit toggle."""
        if value <= 0:
            return
        self.size_text = fmt_num(value) + (' in' if self.unit == 'inch' else ' mm')
        self.dia_in = value if self.unit == 'inch' else value / 25.4
        self._restyle()
        self._compute()

    # keypad under the size grid: typing a size overrides the picked one
    def _apply_entry(self):
        try:
            v = float(self.entry)
        except ValueError:
            v = 0.0
        if v > 0:
            self.custom_size(v)
        elif not self.entry:
            self.size_text = ''
            self.dia_in = 0.0
            self._restyle()
            self._compute()

    def add_digit(self, d):
        if len(self.entry) >= 6:
            return
        self.entry = d if self.entry == '0' else self.entry + d
        self._apply_entry()

    def add_dot(self):
        if '.' not in self.entry:
            self.entry = (self.entry or '0') + '.'

    def backspace(self):
        self.entry = self.entry[:-1]
        self._apply_entry()

    def _compute(self):
        app = App.get_running_app()
        self.sfm = int(app.sfm_for(self.tool, self.material))
        if self.dia_in <= 0:
            self.rpm = 0
            self.rpm_set = 0
            self.capped = False
            self.result_text = 'Pick a size'
            return
        self.rpm = int(round(rpm_for(self.sfm, self.dia_in)))
        top = app.max_spindle_rpm()
        self.capped = self.rpm > top
        self.rpm_set = min(self.rpm, top)
        note = '  (capped at %d, spindle max)' % top if self.capped else ''
        self.result_text = '%s, %s drill, %s at %d SFM  ->  %d rpm%s' % (
            self.size_text, TOOL_NAMES[self.tool], self.material.lower(), self.sfm, self.rpm, note)

    def accept(self):
        if self.rpm_set > 0:
            App.get_running_app().set_spindle_rpm(self.rpm_set, 'drill %s' % self.size_text)
            App.get_running_app().close_drill()


class SfmOverlay(ModalTouch, FloatLayout):
    """Diameter + surface speed -> spindle rpm."""
    unit = StringProperty('inch')            # diameter unit
    diameter = NumericProperty(0.0)          # in the chosen unit
    sfm = NumericProperty(100)
    tool = StringProperty('cbd')             # 'hss' | 'cbd'
    material = StringProperty('')            # last material button pressed, '' = custom SFM
    rpm = NumericProperty(0)
    rpm_set = NumericProperty(0)
    capped = BooleanProperty(False)
    result_text = StringProperty('')
    dia_label = StringProperty('-')

    def populate(self):
        app = App.get_running_app()
        sp = app.settings.get('speed_pad', {})
        self.unit = sp.get('sfm_unit', 'inch')
        self.diameter = float(sp.get('sfm_diameter', 0.0))
        self.sfm = int(sp.get('sfm_sfm', 100))
        self.material = sp.get('sfm_material', '')
        self.tool = sp.get('sfm_tool', 'cbd')
        self._compute()

    def set_material(self, name):
        """Material hot button: load that material's surface speed for the tool."""
        app = App.get_running_app()
        self.material = name
        self.sfm = int(app.sfm_for(self.tool, name))
        app.save_speed_pad(sfm_material=name, sfm_sfm=self.sfm)
        self._compute()

    def set_tool(self, tool):
        self.tool = tool
        App.get_running_app().save_speed_pad(sfm_tool=tool)
        if self.material:
            self.set_material(self.material)     # reload the SFM for the new tool
        else:
            self._compute()

    def set_unit(self, unit):
        if unit != self.unit:
            # convert the entered diameter so the number keeps its meaning
            self.diameter = self.diameter * 25.4 if unit == 'mm' else self.diameter / 25.4
            self.unit = unit
            self._compute()
            App.get_running_app().save_speed_pad(sfm_unit=unit, sfm_diameter=self.diameter)

    def set_diameter(self, v):
        self.diameter = float(v)
        App.get_running_app().save_speed_pad(sfm_diameter=self.diameter)
        self._compute()

    def set_sfm(self, v):
        self.sfm = int(v)
        self.material = ''                   # typed by hand: no material lit
        App.get_running_app().save_speed_pad(sfm_sfm=self.sfm, sfm_material='')
        self._compute()

    def dia_text(self):
        return (fmt_num(self.diameter) + (' in' if self.unit == 'inch' else ' mm')) if self.diameter > 0 else '-'

    def _compute(self):
        app = App.get_running_app()
        self.dia_label = self.dia_text()
        dia_in = self.diameter if self.unit == 'inch' else self.diameter / 25.4
        if dia_in <= 0 or self.sfm <= 0:
            self.rpm = self.rpm_set = 0
            self.capped = False
            self.result_text = 'Enter a diameter and a surface speed'
            return
        self.rpm = int(round(rpm_for(self.sfm, dia_in)))
        top = app.max_spindle_rpm()
        self.capped = self.rpm > top
        self.rpm_set = min(self.rpm, top)
        note = '  (capped at %d, spindle max)' % top if self.capped else ''
        self.result_text = '%d SFM on %s  ->  %d rpm%s' % (self.sfm, self.dia_text(), self.rpm, note)

    def accept(self):
        if self.rpm_set > 0:
            App.get_running_app().set_spindle_rpm(self.rpm_set, 'sfm calc')
            App.get_running_app().close_sfm()


class JogButton(Button):
    """Hold to jog: the app sends a jog command every 200 ms while the
    finger is down and a stop the moment it lifts (the node also stops on
    its own if the stream stops)."""
    active = BooleanProperty(False)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not self.disabled:
            touch.grab(self)
            self.state = 'down'
            self.active = App.get_running_app().jog_press()
            return True
        return super(JogButton, self).on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self.state = 'normal'
            if self.active:
                App.get_running_app().jog_release()
            self.active = False
            return True
        return super(JogButton, self).on_touch_up(touch)


class SpeedPadPage(BoxLayout):
    """Settings > Speed Pad: presets 1-6, jog speed, drill surface speeds."""

    def __init__(self, **kw):
        super(SpeedPadPage, self).__init__(**kw)
        self.refresh()

    def refresh(self):
        from kivy.factory import Factory
        app = App.get_running_app()
        rows = self.ids.rows
        rows.clear_widgets()
        unit = 'rpm' if app.mode == 'rpm' else ('sfm' if app.unit == 'inch' else 'm/min')
        r = Factory.PadRow()
        r.key = 'step'
        r.label = 'Step buttons'
        r.hint = '+/- speed'
        r.value = '%d %s' % (app.step_value(), unit)
        rows.add_widget(r)
        for pos in range(1, 7):
            r = Factory.PadRow()
            r.key = 'preset:%d' % pos
            r.label = 'Button %d' % pos
            r.hint = 'speed preset, %s' % unit
            r.value = '%s %s' % (app.preset_value(pos), unit)
            rows.add_widget(r)
        r = Factory.PadRow()
        r.key = 'jog'
        r.label = 'Jog speed'
        r.hint = 'hold to enable'
        r.value = '%d rpm' % app.jog_rpm()
        rows.add_widget(r)


class SfmPage(BoxLayout):
    """Settings > SFM: the surface-speed tables, HSS then carbide."""

    def __init__(self, **kw):
        super(SfmPage, self).__init__(**kw)
        self.refresh()

    def refresh(self):
        from kivy.factory import Factory
        app = App.get_running_app()
        rows = self.ids.rows
        rows.clear_widgets()
        for tool in ('hss', 'cbd'):
            for name in MATERIALS:
                r = Factory.PadRow()
                r.key = 'sfm:%s:%s' % (tool, name)
                r.label = name
                r.hint = '%s surface speed' % TOOL_NAMES[tool]
                r.value = '%d SFM' % app.sfm_for(tool, name)
                rows.add_widget(r)
