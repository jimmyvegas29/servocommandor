"""Portrait UI widgets for Servo Commander (7" screen rotated to 480x800).

LoadGraph   - pannable load history with auto-ranging scale and time ticks
FitLabel    - single-line label that sizes its font to a worst-case template
SetOverlay  - axis preset keypad (mm 3+3 / inch 2+4)
ModeOverlay - ABS / INC / SDM picker
CalcOverlay - four-function calculator with history and SET X / SET Z
"""
import os

from kivy.app import App
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics import Color, Line, Rectangle
from kivy.properties import NumericProperty, StringProperty, ListProperty

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, 'assets', 'Orbitron-Medium.ttf')
FA = os.path.join(HERE, 'assets', 'fa-solid-900.ttf')

DT = 0.25            # seconds per load sample (matches the drive poll rate)
WINDOW_S = 30        # visible window in seconds
WINDOW_N = int(WINDOW_S / DT)
MAX_HISTORY = 2400   # 10 minutes of scroll-back


class LoadGraph(Widget):
    """Pannable load history with right-side auto-ranged scale and
    1s/5s time ticks. Newest data enters at the right edge."""
    view_offset = NumericProperty(0)
    show_times = NumericProperty(0)   # toggled by double-tap: 5s tick labels
    GUT_R = 36       # right gutter for the scale labels
    TICK_H = 13      # bottom zone for time ticks

    def __init__(self, **kwargs):
        super(LoadGraph, self).__init__(**kwargs)
        self.hist = []
        self._drag_acc = 0.0
        self._label_cache = {}
        self.bind(pos=self.redraw, size=self.redraw)

    def _tex(self, text):
        tex = self._label_cache.get(text)
        if tex is None:
            lbl = CoreLabel(text=text, font_size=12, font_name=FONT)
            lbl.refresh()
            tex = lbl.texture
            self._label_cache[text] = tex
        return tex

    def max_offset(self):
        return max(0, len(self.hist) - WINDOW_N)

    def add_sample(self, v):
        self.hist.append(v)
        if len(self.hist) > MAX_HISTORY:
            self.hist.pop(0)
        if self.view_offset > 0:
            self.view_offset = min(self.view_offset + 1, self.max_offset())
        self.redraw()

    def go_live(self):
        self.view_offset = 0
        self.redraw()

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if touch.is_double_tap:
                # hidden trick: double-tap toggles the 5s tick time labels
                self.show_times = 0 if self.show_times else 1
                self.redraw()
                return True
            touch.grab(self)
            self._drag_acc = 0.0
            return True
        return super(LoadGraph, self).on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            step = (self.width - self.GUT_R) / float(WINDOW_N - 1)
            self._drag_acc += touch.dx / step
            n = int(self._drag_acc)
            if n:
                self._drag_acc -= n
                self.view_offset = max(0, min(self.max_offset(),
                                              self.view_offset + n))
                self.redraw()
            return True
        return super(LoadGraph, self).on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super(LoadGraph, self).on_touch_up(touch)

    @staticmethod
    def _nice_step(ymax):
        return 25 if ymax <= 100 else 50

    def redraw(self, *args):
        total = len(self.hist)
        end = total - self.view_offset
        start = max(0, end - WINDOW_N)
        visible = self.hist[start:end]
        vmax = max(visible) if visible else 0
        ymax = 100.0 if vmax <= 100 else ((int(vmax * 1.1) // 10) + 1) * 10.0

        px = self.x
        py = self.y + self.TICK_H
        pw = self.width - self.GUT_R
        ph = self.height - self.TICK_H - 4

        self.canvas.clear()
        with self.canvas:
            # y scale: gridlines + right-side labels
            step_v = self._nice_step(ymax)
            v = 0
            while v <= ymax + 0.01:
                y = py + ph * (v / ymax)
                if v > 0:
                    Color(1, 1, 1, 0.05)
                    Line(points=[px, y, px + pw, y], width=1)
                tex = self._tex(str(int(v)))
                Color(0.55, 0.55, 0.55, 0.9)
                Rectangle(texture=tex, size=tex.size,
                          pos=(self.x + self.width - tex.width - 2,
                               y - tex.height / 2.0))
                v += step_v

            # time ticks: 1s minor / 5s major, anchored to data age
            right_age = self.view_offset * DT
            k = int(right_age) + 1
            while (k - right_age) < WINDOW_S:
                x = px + pw - (k - right_age) * (pw / float(WINDOW_S))
                if x >= px:
                    major = (k % 5 == 0)
                    Color(1, 1, 1, 0.30 if major else 0.14)
                    h = 11 if major else 6
                    Line(points=[x, self.y + 1, x, self.y + 1 + h], width=1)
                    if major and self.show_times and x > px + 14:
                        tex = self._tex(str(k))
                        Color(0.65, 0.65, 0.65, 0.9)
                        Rectangle(texture=tex, size=tex.size,
                                  pos=(x - tex.width / 2.0, self.y + 14))
                k += 1

            # the trace
            if len(visible) >= 2:
                Color(0, 0.5, 1, 1)
                stepx = pw / float(WINDOW_N - 1)
                right = px + pw
                pts = []
                for i, val in enumerate(visible):
                    frac = max(0.0, min(1.0, val / ymax))
                    pts.extend([right - (len(visible) - 1 - i) * stepx,
                                py + frac * ph])
                Line(points=pts, width=1.5)



KV = '''
#:set ACCENT (0, 0.5, 1, 1)
#:set PANEL (0.16, 0.16, 0.16, 1)
#:set PANEL_DK (0.11, 0.11, 0.11, 1)
#:set BTN_GRAY (0.313, 0.313, 0.313, 1)
#:set GHOST (0.13, 0.13, 0.13, 1)

<SLabel@Label>:
    font_name: app.font
    font_size: '20sp'

<SButton@Button>:
    font_name: app.font
    font_size: '26sp'
    background_color: (0, 0, 0, 0)
    background_normal: ''
    canvas.before:
        Color:
            rgba: PANEL if self.state == 'normal' else ACCENT
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(7, 7)] * 4

<SButtonL@SButton>:
    canvas.before:
        Color:
            rgba: PANEL if self.state == 'normal' else ACCENT
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(7, 7), (0, 0), (0, 0), (7, 7)]

<SButtonN@SButton>:
    canvas.before:
        Color:
            rgba: PANEL if self.state == 'normal' else ACCENT
        Rectangle:
            size: self.size
            pos: self.pos

<SButtonR@SButton>:
    canvas.before:
        Color:
            rgba: PANEL if self.state == 'normal' else ACCENT
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(0, 0), (7, 7), (7, 7), (0, 0)]

<AxisCard@BoxLayout>:
    axis: 'X'
    value: '+0.000'
    spacing: 6
    canvas.before:
        Color:
            rgba: PANEL_DK
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(7, 7)] * 4
    SLabel:
        text: root.axis
        font_size: '46sp'
        color: ACCENT
        size_hint_x: None
        width: 52
    FitLabel:
        font_name: app.font
        text: root.value
        max_font: 84
        fit_text: '+888.888' if app.units == 'mm' else '+88.8888'
        text_size: self.size
        halign: 'right'
        valign: 'middle'
    BoxLayout:
        orientation: 'vertical'
        size_hint_x: None
        width: 92
        padding: [0, 6, 6, 6]
        spacing: 5
        SButton:
            text: 'ZERO'
            font_size: '18sp'
            on_press: app.zero_axis(root.axis)
            canvas.before:
                Color:
                    rgba: PANEL if self.state == 'normal' else ACCENT
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(4, 4)] * 4
        SButton:
            text: 'SET'
            font_size: '18sp'
            on_press: app.open_set(root.axis)
            canvas.before:
                Color:
                    rgba: BTN_GRAY if self.state == 'normal' else ACCENT
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(4, 4)] * 4

<HeaderBar@BoxLayout>:
    size_hint_y: None
    height: 30
    ltext: ''
    rtext: ''
    canvas.before:
        Color:
            rgba: PANEL
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(7, 7), (7, 7), (0, 0), (0, 0)]
    SLabel:
        text: root.ltext
        font_size: '17sp'
        text_size: self.size
        halign: 'left'
        valign: 'middle'
        padding: [8, 0]
    SLabel:
        text: root.rtext
        font_size: '17sp'
        text_size: self.size
        halign: 'right'
        valign: 'middle'
        padding: [8, 0]

<GhostDigit@SLabel>:
    text: '0'
    text_size: self.size
    halign: 'center'
    valign: 'middle'
    color: GHOST

<Root>:
    orientation: 'vertical'
    padding: 4
    spacing: 8
    canvas.before:
        Color:
            rgb: 0.01, 0.01, 0.01
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        size_hint_y: None
        height: 38
        canvas.before:
            Color:
                rgba: PANEL
            RoundedRectangle:
                size: self.size
                pos: self.pos
                radius: [(7, 7)] * 4
        SLabel:
            text: 'Servo Commander'
            font_size: '20sp'
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            padding: [10, 0]
        Button:
            text: '\uf013'
            font_name: app.fa
            font_size: '22sp'
            color: (0.65, 0.65, 0.65, 1)
            background_color: (0, 0, 0, 0)
            background_normal: ''
            size_hint_x: None
            width: 46

    AxisCard:
        size_hint_y: None
        height: 96
        axis: 'X'
        value: app.x_val
    AxisCard:
        size_hint_y: None
        height: 96
        axis: 'Z'
        value: app.z_val

    BoxLayout:
        size_hint_y: None
        height: 32
        spacing: 6
        SButton:
            text: 'CALC'
            font_size: '15sp'
            size_hint_x: None
            width: 84
            on_press: app.open_calc()
            canvas.before:
                Color:
                    rgba: PANEL if self.state == 'normal' else ACCENT
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(4, 4)] * 4
        Widget:
        BoxLayout:
            size_hint_x: None
            width: 164
            spacing: 0
            SButton:
                text: '\uf053'
                font_name: app.fa
                font_size: '15sp'
                size_hint_x: None
                width: 40
                on_press: app.mode_step(-1)
                canvas.before:
                    Color:
                        rgba: PANEL if self.state == 'normal' else ACCENT
                    RoundedRectangle:
                        size: self.size
                        pos: self.pos
                        radius: [(4, 4), (0, 0), (0, 0), (4, 4)]
            SButton:
                text: app.mode_text
                font_size: '15sp'
                color: ACCENT
                on_press: app.open_mode_list()
                canvas.before:
                    Color:
                        rgba: PANEL if self.state == 'normal' else ACCENT
                    Rectangle:
                        size: self.size
                        pos: self.pos
            SButton:
                text: '\uf054'
                font_name: app.fa
                font_size: '15sp'
                size_hint_x: None
                width: 40
                on_press: app.mode_step(1)
                canvas.before:
                    Color:
                        rgba: PANEL if self.state == 'normal' else ACCENT
                    RoundedRectangle:
                        size: self.size
                        pos: self.pos
                        radius: [(0, 0), (4, 4), (4, 4), (0, 0)]
        SButton:
            text: 'MM' if app.units == 'mm' else 'INCH'
            font_size: '15sp'
            size_hint_x: None
            width: 84
            on_press: app.toggle_units()
            canvas.before:
                Color:
                    rgba: PANEL if self.state == 'normal' else ACCENT
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(4, 4)] * 4

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: 168
        BoxLayout:
            size_hint_y: None
            height: 30
            canvas.before:
                Color:
                    rgba: PANEL
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(7, 7), (7, 7), (0, 0), (0, 0)]
            SLabel:
                text: 'Load'
                font_size: '17sp'
                text_size: self.size
                halign: 'left'
                valign: 'middle'
                padding: [8, 0]
            Button:
                markup: True
                text: 'LIVE [font=' + app.fa + '][size=13]\uf054[/size][/font]'
                font_name: app.font
                font_size: '15sp'
                color: ACCENT
                background_color: (0, 0, 0, 0)
                background_normal: ''
                size_hint_x: None
                width: 86
                opacity: 1 if graph.view_offset else 0
                disabled: graph.view_offset == 0
                on_press: graph.go_live()
        BoxLayout:
            padding: [8, 6, 8, 6]
            canvas.before:
                Color:
                    rgba: PANEL_DK
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(0, 0), (0, 0), (7, 7), (7, 7)]
            FloatLayout:
                LoadGraph:
                    id: graph
                    size_hint: (1, 1)
                    pos_hint: {'x': 0, 'y': 0}
                SLabel:
                    id: loadnum
                    text: app.load_str
                    font_size: '42sp'
                    color: app.load_color
                    size_hint: (None, None)
                    size: self.texture_size
                    pos_hint: {'x': 0.015, 'top': 1.04}
                SLabel:
                    text: '%'
                    font_size: '17sp'
                    color: app.load_color_dim
                    size_hint: (None, None)
                    size: self.texture_size
                    pos: (loadnum.right + 3, loadnum.top - self.height - 8)

    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: 124
        HeaderBar:
            ltext: 'Servo speed'
            rtext: 'R.P.M.'
        BoxLayout:
            padding: [10, 0, 10, 4]
            canvas.before:
                Color:
                    rgba: PANEL_DK
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(0, 0), (0, 0), (7, 7), (7, 7)]
            GhostDigit:
                font_size: '86sp'
            GhostDigit:
                text: '6'
                font_size: '86sp'
                color: (1, 1, 1, 1)
            GhostDigit:
                text: '0'
                font_size: '86sp'
                color: (1, 1, 1, 1)
            GhostDigit:
                text: '0'
                font_size: '86sp'
                color: (1, 1, 1, 1)

    BoxLayout:
        spacing: 8
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.64
            spacing: 5
            BoxLayout:
                spacing: 5
                SButtonL:
                    text: '50'
                SButtonN:
                    text: '100'
                SButtonR:
                    text: '200'
            BoxLayout:
                spacing: 5
                SButtonL:
                    text: '400'
                SButtonN:
                    text: '600'
                SButtonR:
                    text: '800'
            BoxLayout:
                spacing: 5
                SButtonL:
                    text: '1000'
                SButtonN:
                    text: '1250'
                SButtonR:
                    text: '1500'
        BoxLayout:
            orientation: 'vertical'
            size_hint_x: 0.36
            spacing: 5
            BoxLayout:
                spacing: 5
                SButtonL:
                    text: '+50'
                    font_size: '20sp'
                    canvas.before:
                        Color:
                            rgba: BTN_GRAY if self.state == 'normal' else ACCENT
                        RoundedRectangle:
                            size: self.size
                            pos: self.pos
                            radius: [(7, 7), (0, 0), (0, 0), (7, 7)]
                SButtonR:
                    text: '-50'
                    font_size: '20sp'
                    canvas.before:
                        Color:
                            rgba: BTN_GRAY if self.state == 'normal' else ACCENT
                        RoundedRectangle:
                            size: self.size
                            pos: self.pos
                            radius: [(0, 0), (7, 7), (7, 7), (0, 0)]
            SButton:
                text: 'CUSTOM'
                font_size: '20sp'
            BoxLayout:
                spacing: 5
                SButtonL:
                    text: 'FWD'
                    font_size: '18sp'
                    color: (1, 1, 1, 1)
                    canvas.before:
                        Color:
                            rgba: ACCENT
                        RoundedRectangle:
                            size: self.size
                            pos: self.pos
                            radius: [(7, 7), (0, 0), (0, 0), (7, 7)]
                SButtonR:
                    text: 'EN'
                    font_size: '18sp'
                    color: (0.313, 0.313, 0.313, 1)
                    canvas.before:
                        Color:
                            rgba: (0.105, 0.105, 0.105, 1)
                        RoundedRectangle:
                            size: self.size
                            pos: self.pos
                            radius: [(0, 0), (7, 7), (7, 7), (0, 0)]

<SetKey@Button>:
    font_name: app.font
    font_size: '38sp'
    background_color: (0, 0, 0, 0)
    background_normal: ''
    canvas.before:
        Color:
            rgba: PANEL if self.state == 'normal' else ACCENT
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(7, 7)] * 4

<SetOverlay>:
    canvas.before:
        Color:
            rgba: (0, 0, 0, 0.96)
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        size_hint: (1, 1)
        padding: 10
        spacing: 8
        BoxLayout:
            size_hint_y: None
            height: 44
            canvas.before:
                Color:
                    rgba: PANEL
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(7, 7)] * 4
            SLabel:
                text: 'Set ' + root.axis + ' position'
                font_size: '20sp'
                text_size: self.size
                halign: 'left'
                valign: 'middle'
                padding: [10, 0]
            SLabel:
                text: root.axis
                font_size: '26sp'
                color: ACCENT
                size_hint_x: None
                width: 44
        BoxLayout:
            size_hint_y: None
            height: 76
            padding: [12, 0]
            canvas.before:
                Color:
                    rgba: PANEL_DK
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(7, 7)] * 4
            SLabel:
                text: root.entry if root.entry else '+0.000'
                font_size: root.font_px
                color: (1, 1, 1, 1) if root.entry else (0.35, 0.35, 0.35, 1)
                text_size: self.size
                halign: 'right'
                valign: 'middle'
            SLabel:
                text: app.units
                font_size: '16sp'
                color: (0.55, 0.55, 0.55, 1)
                size_hint_x: None
                width: 36
                text_size: self.size
                halign: 'left'
                valign: 'bottom'
                padding: [4, 0, 0, 13]
        GridLayout:
            cols: 3
            spacing: 6
            SetKey:
                text: '7'
                on_press: root.add_char('7')
            SetKey:
                text: '8'
                on_press: root.add_char('8')
            SetKey:
                text: '9'
                on_press: root.add_char('9')
            SetKey:
                text: '4'
                on_press: root.add_char('4')
            SetKey:
                text: '5'
                on_press: root.add_char('5')
            SetKey:
                text: '6'
                on_press: root.add_char('6')
            SetKey:
                text: '1'
                on_press: root.add_char('1')
            SetKey:
                text: '2'
                on_press: root.add_char('2')
            SetKey:
                text: '3'
                on_press: root.add_char('3')
            SetKey:
                text: '+/-'
                font_size: '30sp'
                on_press: root.toggle_sign()
            SetKey:
                text: '0'
                on_press: root.add_char('0')
            SetKey:
                text: '.'
                on_press: root.add_char('.')
        BoxLayout:
            size_hint_y: None
            height: 64
            spacing: 6
            SetKey:
                text: 'CANCEL'
                font_size: '20sp'
                on_press: app.close_set()
            SetKey:
                markup: True
                text: '[font=' + app.fa + '][size=15]\uf00c[/size][/font]  SET'
                font_size: '20sp'
                color: (0.4, 0.85, 0.5, 1)
                on_press: root.submit()
            SetKey:
                markup: True
                text: '[font=' + app.fa + '][size=15]\uf55a[/size][/font]'
                font_size: '20sp'
                size_hint_x: 0.4
                on_press: root.backspace()

<CalcKey@SetKey>:
    font_size: '34sp'

<CalcOp@SetKey>:
    font_size: '42sp'
    color: ACCENT

<CalcOverlay>:
    canvas.before:
        Color:
            rgba: (0, 0, 0, 1)
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        size_hint: (1, 1)
        padding: 10
        spacing: 8
        BoxLayout:
            size_hint_y: None
            height: 44
            canvas.before:
                Color:
                    rgba: PANEL
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(7, 7)] * 4
            SLabel:
                text: 'Calculator'
                font_size: '20sp'
                text_size: self.size
                halign: 'left'
                valign: 'middle'
                padding: [10, 0]
            Button:
                text: ''
                font_name: app.fa
                font_size: '22sp'
                color: (0.65, 0.65, 0.65, 1)
                background_color: (0, 0, 0, 0)
                background_normal: ''
                size_hint_x: None
                width: 52
                on_press: root.toggle_history()
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: 112
            padding: [12, 6]
            canvas.before:
                Color:
                    rgba: PANEL_DK
                RoundedRectangle:
                    size: self.size
                    pos: self.pos
                    radius: [(7, 7)] * 4
            SLabel:
                text: root.hist
                font_size: '17sp'
                color: (0.55, 0.55, 0.55, 1)
                size_hint_y: None
                height: 24
                text_size: self.size
                halign: 'right'
                valign: 'middle'
            SLabel:
                text: root.entry if root.entry else '0'
                font_size: root.font_px
                color: (1, 1, 1, 1) if root.entry else (0.35, 0.35, 0.35, 1)
                text_size: self.size
                halign: 'right'
                valign: 'middle'
        BoxLayout:
            spacing: 6
            GridLayout:
                cols: 3
                spacing: 6
                CalcKey:
                    text: 'C'
                    on_press: root.clear()
                CalcKey:
                    markup: True
                    text: '[font=' + app.fa + '][size=26][/size][/font]'
                    on_press: root.backspace()
                CalcOp:
                    text: '÷'
                    on_press: root.add_op('÷')
                CalcKey:
                    text: '7'
                    on_press: root.add_digit('7')
                CalcKey:
                    text: '8'
                    on_press: root.add_digit('8')
                CalcKey:
                    text: '9'
                    on_press: root.add_digit('9')
                CalcKey:
                    text: '4'
                    on_press: root.add_digit('4')
                CalcKey:
                    text: '5'
                    on_press: root.add_digit('5')
                CalcKey:
                    text: '6'
                    on_press: root.add_digit('6')
                CalcKey:
                    text: '1'
                    on_press: root.add_digit('1')
                CalcKey:
                    text: '2'
                    on_press: root.add_digit('2')
                CalcKey:
                    text: '3'
                    on_press: root.add_digit('3')
                CalcKey:
                    text: '+/-'
                    font_size: '26sp'
                    on_press: root.toggle_sign()
                CalcKey:
                    text: '0'
                    on_press: root.add_digit('0')
                CalcKey:
                    text: '.'
                    on_press: root.add_dot()
            BoxLayout:
                orientation: 'vertical'
                size_hint_x: None
                width: 108
                spacing: 6
                CalcOp:
                    text: '×'
                    on_press: root.add_op('×')
                CalcOp:
                    text: '−'
                    on_press: root.add_op('−')
                CalcOp:
                    text: '+'
                    on_press: root.add_op('+')
                CalcOp:
                    text: '='
                    size_hint_y: 2
                    color: (0.4, 0.85, 0.5, 1)
                    on_press: root.equals()
        BoxLayout:
            size_hint_y: None
            height: 64
            spacing: 6
            SetKey:
                text: 'CLOSE'
                font_size: '20sp'
                on_press: app.close_calc()
            SetKey:
                markup: True
                text: '[font=' + app.fa + '][size=15][/size][/font]  SET X'
                font_size: '20sp'
                color: (0.4, 0.85, 0.5, 1)
                on_press: root.send_to('X')
            SetKey:
                markup: True
                text: '[font=' + app.fa + '][size=15][/size][/font]  SET Z'
                font_size: '20sp'
                color: (0.4, 0.85, 0.5, 1)
                on_press: root.send_to('Z')

<CalcHistory>:
    orientation: 'vertical'
    size_hint: (None, None)
    padding: 8
    spacing: 8
    canvas.before:
        Color:
            rgba: PANEL_DK
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [(7, 7)] * 4
    SLabel:
        text: 'History'
        font_size: '18sp'
        size_hint_y: None
        height: 30
        text_size: self.size
        halign: 'left'
        valign: 'middle'
        padding: [6, 0]
    ScrollView:
        id: hist_scroll
        bar_width: 0
        do_scroll_x: False
        scroll_type: ['content']
        GridLayout:
            id: hist_grid
            cols: 1
            size_hint_y: None
            height: self.minimum_height
            spacing: 4
    BoxLayout:
        size_hint_y: None
        height: 64
        spacing: 6
        SetKey:
            markup: True
            text: '[font=' + app.fa + '][size=15][/size][/font]  BACK'
            font_size: '20sp'
            on_press: root.close()
        SetKey:
            markup: True
            text: '[font=' + app.fa + '][size=18][/size][/font]'
            font_size: '20sp'
            size_hint_x: 0.4
            color: (0.9, 0.45, 0.45, 1)
            on_press: root.clear_all()

<ModeOverlay>:
    canvas.before:
        Color:
            rgba: (0, 0, 0, 0.9)
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        size_hint: (None, None)
        size: (300, 640)
        pos_hint: {'center_x': 0.5, 'center_y': 0.5}
        padding: 8
        spacing: 8
        canvas.before:
            Color:
                rgba: PANEL_DK
            RoundedRectangle:
                size: self.size
                pos: self.pos
                radius: [(7, 7)] * 4
        SLabel:
            text: 'Select mode'
            font_size: '18sp'
            size_hint_y: None
            height: 34
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            padding: [6, 0]
        ScrollView:
            id: mode_scroll
            bar_width: 0
            do_scroll_x: False
            scroll_type: ['content']
            GridLayout:
                id: mode_grid
                cols: 1
                size_hint_y: None
                height: self.minimum_height
                spacing: 4
        SetKey:
            text: 'CANCEL'
            font_size: '18sp'
            size_hint_y: None
            height: 52
            on_press: app.close_mode_list()
'''


class FitLabel(Label):
    """Single-line label that picks the largest font size whose rendered
    text fits its own width and height (measured, not estimated)."""
    max_font = NumericProperty(90)
    # fit_text: a worst-case template to size against (e.g. '+8888.888') so
    # the font stays one fixed size regardless of the current value
    fit_text = StringProperty('')
    _cache = {}

    def __init__(self, **kwargs):
        super(FitLabel, self).__init__(**kwargs)
        self.bind(text=self._refit, size=self._refit, max_font=self._refit,
                  fit_text=self._refit)

    def _refit(self, *args):
        if self.width <= 0 or self.height <= 0 or not self.text:
            return
        # measure a widest-glyph stand-in (all digits -> 8, sign -> +) so any
        # value of this length fits and the size never twitches as digits change
        source = self.fit_text or self.text
        probe = ''.join('8' if ch.isdigit() else ('+' if ch == '-' else ch)
                        for ch in source)
        key = (probe, int(self.width), int(self.height), int(self.max_font))
        fs = FitLabel._cache.get(key)
        if fs is None:
            avail_w = self.width - 4
            avail_h = self.height
            fs = int(self.max_font)
            while fs > 20:
                lbl = CoreLabel(text=probe, font_size=fs, font_name=self.font_name)
                lbl.refresh()
                if lbl.texture.width <= avail_w and lbl.texture.height <= avail_h:
                    break
                fs -= 2
            FitLabel._cache[key] = fs
        self.font_size = fs


class FixedDigits(Widget):
    """Numeric readout with tabular spacing: every digit gets the same cell
    (the widest digit's width), sign and decimal point get their own fixed
    cells, so a changing value never reflows.  Font size is chosen once
    from fit_text (worst case) so it also never changes."""
    text = StringProperty('')
    fit_text = StringProperty('+888.888')
    max_font = NumericProperty(84)
    color = ListProperty([1, 1, 1, 1])
    font_name = StringProperty(FONT)
    axis = StringProperty('')     # set on the axis cards: double-tap -> copy picker
    _glyph_cache = {}
    _metrics_cache = {}

    def on_touch_down(self, touch):
        if self.axis and touch.is_double_tap and self.collide_point(*touch.pos):
            App.get_running_app().open_copy(self.axis)
            return True
        return super(FixedDigits, self).on_touch_down(touch)

    def __init__(self, **kwargs):
        super(FixedDigits, self).__init__(**kwargs)
        self.font_px = 0
        self.bind(text=self.redraw, size=self._refit, pos=self.redraw,
                  fit_text=self._refit, max_font=self._refit, color=self.redraw)
        Clock.schedule_once(self._refit, 0)

    # -- measuring --------------------------------------------------------
    def _glyph(self, ch, fs):
        key = (self.font_name, fs, ch)
        tex = FixedDigits._glyph_cache.get(key)
        if tex is None:
            lbl = CoreLabel(text=ch, font_size=fs, font_name=self.font_name)
            lbl.refresh()
            tex = lbl.texture
            FixedDigits._glyph_cache[key] = tex
        return tex

    def _metrics(self, fs):
        """cell widths at this size: digit, sign, dot; and glyph height."""
        key = (self.font_name, fs)
        m = FixedDigits._metrics_cache.get(key)
        if m is None:
            digit_w = max(self._glyph(d, fs).width for d in '0123456789')
            sign_w = max(self._glyph(s, fs).width for s in '+-')
            dot_w = self._glyph('.', fs).width
            h = max(self._glyph(d, fs).height for d in '0123456789+')
            m = (digit_w, sign_w, dot_w, h)
            FixedDigits._metrics_cache[key] = m
        return m

    def _cell_w(self, ch, m):
        digit_w, sign_w, dot_w, _h = m
        if ch.isdigit():
            return digit_w
        if ch in '+-':
            return sign_w
        if ch == '.':
            return dot_w + 2
        return digit_w

    def _total_w(self, text, m):
        return sum(self._cell_w(ch, m) for ch in text)

    def _refit(self, *args):
        if self.width <= 0 or self.height <= 0:
            return
        fs = int(self.max_font)
        while fs > 20:
            m = self._metrics(fs)
            if self._total_w(self.fit_text, m) <= self.width - 4 and m[3] <= self.height:
                break
            fs -= 2
        self.font_px = fs
        self.redraw()

    def cells(self):
        """[(char, x, cell_width)] for the current text, right-aligned."""
        if not self.font_px:
            return []
        m = self._metrics(self.font_px)
        x = self.right - 2 - self._total_w(self.text, m)
        out = []
        for ch in self.text:
            w = self._cell_w(ch, m)
            out.append((ch, x, w))
            x += w
        return out

    # -- drawing ----------------------------------------------------------
    def redraw(self, *args):
        self.canvas.clear()
        if not self.font_px or not self.text:
            return
        cy = self.center_y
        with self.canvas:
            Color(*self.color)
            for ch, x, w in self.cells():
                tex = self._glyph(ch, self.font_px)
                Rectangle(texture=tex, size=tex.size,
                          pos=(x + (w - tex.width) / 2.0, cy - tex.height / 2.0))


class ModalTouch:
    """Mixin for full-screen overlays: any touch the overlay's children
    don't handle is swallowed here, so nothing underneath (the gear, the
    axis cards...) can be hit through a popup."""

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        return self.collide_point(*touch.pos)

    def on_touch_move(self, touch):
        if super().on_touch_move(touch):
            return True
        return self.collide_point(*touch.pos)

    def on_touch_up(self, touch):
        if super().on_touch_up(touch):
            return True
        return self.collide_point(*touch.pos)


class ModeOverlay(ModalTouch, FloatLayout):
    def populate(self, modes, current):
        from kivy.uix.button import Button
        grid = self.ids.mode_grid
        grid.clear_widgets()
        app = App.get_running_app()
        for i, name in enumerate(modes):
            btn = Button(text=name, font_name=FONT, font_size=17,
                         size_hint_y=None, height=52,
                         background_color=(0, 0, 0, 0), background_normal='',
                         color=(1, 1, 1, 1) if i == current else (0.75, 0.75, 0.75, 1))
            with btn.canvas.before:
                from kivy.graphics import Color as _C, RoundedRectangle as _R
                col = _C(0, 0.5, 1, 1) if i == current else _C(0.16, 0.16, 0.16, 1)
                rect = _R(size=btn.size, pos=btn.pos, radius=[(5, 5)] * 4)
            btn.bind(pos=lambda b, v, r=rect: setattr(r, 'pos', v),
                     size=lambda b, v, r=rect: setattr(r, 'size', v))
            btn.bind(on_press=lambda b, idx=i: app.select_mode(idx))
            grid.add_widget(btn)

        def scroll_to_current(dt):
            n = len(modes)
            self.ids.mode_scroll.scroll_y = 1.0 - (current / float(max(1, n - 1)))
        Clock.schedule_once(scroll_to_current, 0)


class SetOverlay(ModalTouch, FloatLayout):
    axis = StringProperty('X')
    entry = StringProperty('')
    font_px = NumericProperty(85)

    ENTRY_MAX_W = 386   # label width inside the readout box, minus margin

    @classmethod
    def _fit_font(cls, text):
        fs = 85
        while fs > 30:
            lbl = CoreLabel(text=text, font_size=fs, font_name=FONT)
            lbl.refresh()
            if lbl.texture.width <= cls.ENTRY_MAX_W:
                return fs
            fs -= 2
        return fs

    def on_entry(self, *args):
        self.font_px = self._fit_font(self.entry if self.entry else '+0.000')

    def add_char(self, ch):
        e = self.entry
        if ch == '.':
            if '.' in e:
                return
            if e in ('', '+', '-'):
                e += '0'
        # entry limits follow the unit mode:
        # mm = 3 integer + 3 decimal (1um), inch = 2 integer + 4 decimal
        units = App.get_running_app().units
        int_max, frac_max = (3, 3) if units == 'mm' else (2, 4)
        candidate = (e + ch).lstrip('+-')
        parts = candidate.split('.')
        if len(parts[0]) > int_max:
            return
        if len(parts) > 1 and len(parts[1]) > frac_max:
            return
        self.entry = e + ch

    def toggle_sign(self):
        e = self.entry
        if e.startswith('-'):
            self.entry = '+' + e[1:]
        elif e.startswith('+'):
            self.entry = '-' + e[1:]
        else:
            self.entry = '-' + e

    def backspace(self):
        self.entry = self.entry[:-1]

    def clear(self):
        self.entry = ''

    def submit(self):
        app = App.get_running_app()
        try:
            value = float(self.entry)
        except ValueError:
            self.entry = ''
            return
        app.apply_set(self.axis, value)
        app.close_set()


class CalcOverlay(ModalTouch, FloatLayout):
    """Four-function calculator.  Binary operators are stored as the
    display glyphs (+ − × ÷); a unary minus is a plain '-' glued to
    its number.  The result can be pushed straight into an axis SET."""
    entry = StringProperty('')
    hist = StringProperty('')
    font_px = NumericProperty(64)

    OPS = '+−×÷'
    ENTRY_MAX_W = 432
    MAX_LEN = 40

    def __init__(self, **kw):
        super().__init__(**kw)
        self._result = False   # entry holds the output of '='

    def on_entry(self, *args):
        text = self.entry if self.entry else '0'
        fs = 64
        while fs > 24:
            lbl = CoreLabel(text=text, font_size=fs, font_name=FONT)
            lbl.refresh()
            if lbl.texture.width <= self.ENTRY_MAX_W:
                break
            fs -= 2
        self.font_px = fs

    # -- helpers ------------------------------------------------------
    def _num_start(self):
        """Index where the number currently being typed begins."""
        e = self.entry
        i = len(e)
        while i > 0 and e[i - 1] not in self.OPS:
            i -= 1
        return i

    def _begin_after_result(self):
        if self._result:
            self.entry = ''
            self.hist = ''
            self._result = False

    # -- keys ---------------------------------------------------------
    def add_digit(self, d):
        self._begin_after_result()
        if len(self.entry) >= self.MAX_LEN:
            return
        cur = self.entry[self._num_start():]
        if cur in ('0', '-0'):
            self.entry = self.entry[:-1] + d      # no leading zeros
        else:
            self.entry += d

    def add_dot(self):
        self._begin_after_result()
        cur = self.entry[self._num_start():]
        if '.' in cur:
            return
        if cur in ('', '-'):
            self.entry += '0'
        self.entry += '.'

    def add_op(self, op):
        if self._result:
            self._result = False       # continue from the result
            self.hist = ''
        e = self.entry
        if e == '' or e == '-':
            return
        if e[-1] in self.OPS:
            self.entry = e[:-1] + op   # swap the pending operator
            return
        if e[-1] == '.':
            e = e[:-1]
        self.entry = e + op

    def toggle_sign(self):
        if self._result:
            self.hist = ''
            self._result = False
        s = self._num_start()
        cur = self.entry[s:]
        if cur.startswith('-'):
            self.entry = self.entry[:s] + cur[1:]
        else:
            self.entry = self.entry[:s] + '-' + cur

    def backspace(self):
        if self._result:
            self.clear()
            return
        self.entry = self.entry[:-1]

    def clear(self):
        self.entry = ''
        self.hist = ''
        self._result = False

    # -- evaluation ---------------------------------------------------
    @classmethod
    def _tokens(cls, text):
        toks = []
        num = ''
        for ch in text:
            if ch in cls.OPS:
                if num == '':
                    raise ValueError('operand')
                toks.append(float(num))
                toks.append(ch)
                num = ''
            else:
                num += ch
        if num == '' or num == '-':
            raise ValueError('operand')
        toks.append(float(num))
        return toks

    @classmethod
    def evaluate(cls, text):
        toks = cls._tokens(text)
        # pass 1: × ÷
        out = [toks[0]]
        i = 1
        while i < len(toks):
            op, rhs = toks[i], toks[i + 1]
            if op == '×':
                out[-1] = out[-1] * rhs
            elif op == '÷':
                if rhs == 0:
                    raise ZeroDivisionError
                out[-1] = out[-1] / rhs
            else:
                out.extend([op, rhs])
            i += 2
        # pass 2: + −
        val = out[0]
        i = 1
        while i < len(out):
            op, rhs = out[i], out[i + 1]
            val = val + rhs if op == '+' else val - rhs
            i += 2
        return val

    @staticmethod
    def fmt(value):
        if abs(value) >= 1e9:
            return 'Overflow'
        s = '%.6f' % value
        s = s.rstrip('0').rstrip('.')
        if s in ('', '-0'):
            s = '0'
        return s

    def value(self):
        """Numeric value of the display, or None if it can't be evaluated."""
        if not self.entry:
            return None
        try:
            return self.evaluate(self.entry)
        except (ValueError, ZeroDivisionError, IndexError):
            return None

    def equals(self):
        if not self.entry or self._result:
            return
        try:
            val = self.evaluate(self.entry)
        except ZeroDivisionError:
            self.hist = 'Divide by zero'
            return
        except (ValueError, IndexError):
            self.hist = 'Incomplete'
            return
        self.hist = self.entry + ' ='
        self.entry = self.fmt(val)
        self._result = True
        app = App.get_running_app()
        app.calc_history.insert(0, (self.hist, self.entry))
        del app.calc_history[self.HISTORY_MAX:]

    # -- history panel ------------------------------------------------
    HISTORY_MAX = 50

    def load_result(self, text):
        """Recall a history result into the display."""
        self.entry = text
        self.hist = ''
        self._result = True

    def _place_history(self, *args):
        p = getattr(self, '_hist_panel', None)
        if p is None:
            return
        # covers the keypad + bottom row; display box stays visible
        p.size = (self.width - 20, self.height - 192)
        p.pos = (self.x + 10, self.y + 10)

    def open_history(self):
        if getattr(self, '_hist_panel', None):
            return
        self._hist_panel = CalcHistory(owner=self)
        self._hist_panel.populate(App.get_running_app().calc_history)
        self.add_widget(self._hist_panel)
        self.bind(size=self._place_history, pos=self._place_history)
        self._place_history()

    def close_history(self):
        p = getattr(self, '_hist_panel', None)
        if p is None:
            return
        self.unbind(size=self._place_history, pos=self._place_history)
        self.remove_widget(p)
        self._hist_panel = None

    def toggle_history(self):
        if getattr(self, '_hist_panel', None):
            self.close_history()
        else:
            self.open_history()

    def send_to(self, axis):
        val = self.value()
        if val is None:
            return
        app = App.get_running_app()
        app.apply_set(axis, val)
        app.close_calc()


class HistRow(ButtonBehavior, BoxLayout):
    """Tappable two-line history row (expression over result)."""
    pass


class CalcHistory(BoxLayout):
    """Windows-calculator style history: expression small and grey,
    result large beneath it, newest first; tap a row to recall it."""

    def __init__(self, owner=None, **kw):
        super().__init__(**kw)
        self.owner = owner

    def populate(self, items):
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from kivy.graphics import Color as _C, RoundedRectangle as _R
        grid = self.ids.hist_grid
        grid.clear_widgets()
        if not items:
            grid.add_widget(Label(text="There's no history yet", font_name=FONT,
                                  font_size=17, color=(0.5, 0.5, 0.5, 1),
                                  size_hint_y=None, height=60))
            return
        for expr, result in items:
            row = HistRow(orientation='vertical', size_hint_y=None, height=78,
                          padding=(12, 8, 12, 8))
            top = Label(text=expr, font_name=FONT, font_size=15,
                        color=(0.55, 0.55, 0.55, 1), halign='right', valign='top',
                        size_hint_y=None, height=20)
            bot = Label(text=result, font_name=FONT, font_size=30,
                        color=(1, 1, 1, 1), halign='right', valign='middle')
            for lbl in (top, bot):
                lbl.bind(size=lambda b, v: setattr(b, 'text_size', v))
            row.add_widget(top)
            row.add_widget(bot)
            with row.canvas.before:
                _C(0.16, 0.16, 0.16, 1)
                rect = _R(size=row.size, pos=row.pos, radius=[(5, 5)] * 4)
            row.bind(pos=lambda b, v, r=rect: setattr(r, 'pos', v),
                     size=lambda b, v, r=rect: setattr(r, 'size', v))
            row.bind(on_press=lambda b, res=result: self._recall(res))
            grid.add_widget(row)
        Clock.schedule_once(lambda dt: setattr(self.ids.hist_scroll, 'scroll_y', 1.0), 0)

    def _recall(self, result):
        self.owner.load_result(result)
        self.close()

    def clear_all(self):
        del App.get_running_app().calc_history[:]
        self.populate([])

    def close(self):
        self.owner.close_history()
