"""Tap sizes and tapping torque for the Tap tool.

Torque rows (inch-pounds, at the tap) are Tapmatic's published "Torque
Setting Data For HSS Straight Flute Plug Taps": minimum and maximum tapping
torque, breaking torque of a low- and a high-strength tap, and the clutch
setting Tapmatic recommends for its torque-limiting heads (the "normal"
column).  The panel uses that clutch setting as the torque cap.
https://www.tapmatic.com/tapping_questions_torque_setting_data_for_hss.ydev

Sizes under 1/4 in are left out (not tapped on a lathe); M6 stays as the
metric 1/4-20.  Tapmatic lists inch sizes only.  Metric sizes use the row of the next
SMALLER inch size, so their cap errs low (they are marked derived).

The torque a thread needs in a given material is estimated with the
cutting-tap formula from tap makers' technical data (ECL):
    Md [Nm] = 0.2 * P^2 * Ks * D / 1000
P pitch mm, D major diameter mm, Ks specific cutting force N/mm2.
https://precisiontoolstooling.au/pages/ecl-taps-technical-information-trouble-shooting
Only materials with a published Ks get an estimate.
"""

IN_LB_PER_NM = 8.8507

# specific cutting force, N/mm2 (middle of the published range), by the
# material names the SFM tables use; None = no published value
KS = {
    'Mild steel': 2300,            # low carbon steel 2200-2400
    'Medium carbon': 3000,         # not listed: uses the alloy steel value (errs high)
    'High carbon': 3000,           # 4130 / 4140: alloy steel 2800-3200
    'Stainless': 3650,             # austenitic stainless (304 / 316) 3500-3800
    'Cast iron': None,
    'Aluminum': 800,               # aluminium alloy 700-900
    'Brass': None,
    'Plastic': None,
}
KS_NOTE = {'Medium carbon': 'alloy steel value', 'Stainless': '304/316 value'}

# major diameter, mm, of the numbered and fractional sizes
_DIA = {'#0': 1.524, '#1': 1.854, '#2': 2.184, '#3': 2.515, '#4': 2.845, '#5': 3.175, '#6': 3.505,
        '#8': 4.166, '#10': 4.826, '#12': 5.486, '1/4': 6.35, '5/16': 7.9375, '3/8': 9.525,
        '7/16': 11.1125, '1/2': 12.7, '9/16': 14.2875, '5/8': 15.875, '3/4': 19.05}

# row: (min tapping, max tapping, break low, break high, clutch setting), in-lb
_ROWS = {
    '0-2': (10, 18, 25, 50, 20),
    '3-4': (10, 20, 30, 50, 20),
    '5-6': (10, 20, 30, 50, 20),
    '8': (20, 30, 40, 60, 25),
    '10-32': (20, 30, 40, 60, 25),
    '10-24': (25, 50, 40, 60, 30),
    '12': (25, 50, 40, 70, 30),
    '1/4-28': (30, 60, 50, 100, 40),
    '1/4-20': (40, 80, 50, 100, 50),
    '5/16-24': (40, 80, 75, 150, 60),
    '5/16-18': (60, 120, 75, 150, 90),
    '3/8-24': (60, 120, 180, 260, 90),
    '3/8-16': (100, 200, 180, 260, 130),
    '7/16-20': (80, 160, 180, 300, 130),
    '7/16-14': (100, 200, 180, 300, 200),
    '1/2-20': (100, 250, 300, 600, 300),
    '1/2-13': (150, 300, 300, 600, 300),
    '9/16-18': (150, 350, 500, 800, 350),
    '9/16-12': (200, 500, 500, 800, 350),
    '5/8-18': (200, 600, 800, 1200, 450),
    '5/8-11': (300, 800, 800, 1200, 450),
    '3/4-16': (300, 800, 1000, 1500, 650),
    '3/4-10': (500, 1000, 1000, 1500, 650),
}

# (key, label, family, pitch value, pitch unit, table row, derived-from label or '')
_SIZES = [
    # UNC
    ('1/4-20', '1/4-20', 'UNC', 20, 'tpi', '1/4-20', ''),
    ('5/16-18', '5/16-18', 'UNC', 18, 'tpi', '5/16-18', ''),
    ('3/8-16', '3/8-16', 'UNC', 16, 'tpi', '3/8-16', ''),
    ('7/16-14', '7/16-14', 'UNC', 14, 'tpi', '7/16-14', ''),
    ('1/2-13', '1/2-13', 'UNC', 13, 'tpi', '1/2-13', ''),
    ('9/16-12', '9/16-12', 'UNC', 12, 'tpi', '9/16-12', ''),
    ('5/8-11', '5/8-11', 'UNC', 11, 'tpi', '5/8-11', ''),
    ('3/4-10', '3/4-10', 'UNC', 10, 'tpi', '3/4-10', ''),
    # UNF
    ('1/4-28', '1/4-28', 'UNF', 28, 'tpi', '1/4-28', ''),
    ('5/16-24', '5/16-24', 'UNF', 24, 'tpi', '5/16-24', ''),
    ('3/8-24', '3/8-24', 'UNF', 24, 'tpi', '3/8-24', ''),
    ('7/16-20', '7/16-20', 'UNF', 20, 'tpi', '7/16-20', ''),
    ('1/2-20', '1/2-20', 'UNF', 20, 'tpi', '1/2-20', ''),
    ('9/16-18', '9/16-18', 'UNF', 18, 'tpi', '9/16-18', ''),
    ('5/8-18', '5/8-18', 'UNF', 18, 'tpi', '5/8-18', ''),
    ('3/4-16', '3/4-16', 'UNF', 16, 'tpi', '3/4-16', ''),
    # metric coarse (row of the next smaller inch size)
    ('M6x1', 'M6', 'M', 1.0, 'mm', '12', '#12'),
    ('M8x1.25', 'M8', 'M', 1.25, 'mm', '5/16-18', '5/16'),
    ('M10x1.5', 'M10', 'M', 1.5, 'mm', '3/8-16', '3/8'),
    ('M12x1.75', 'M12', 'M', 1.75, 'mm', '7/16-14', '7/16'),
    ('M14x2', 'M14', 'M', 2.0, 'mm', '1/2-13', '1/2'),
    ('M16x2', 'M16', 'M', 2.0, 'mm', '5/8-11', '5/8'),
    # metric fine
    ('M8x1', 'M8x1', 'MF', 1.0, 'mm', '5/16-24', '5/16'),
    ('M10x1', 'M10x1', 'MF', 1.0, 'mm', '3/8-24', '3/8'),
    ('M10x1.25', 'M10x1.25', 'MF', 1.25, 'mm', '3/8-24', '3/8'),
    ('M12x1.25', 'M12x1.25', 'MF', 1.25, 'mm', '7/16-20', '7/16'),
    ('M12x1.5', 'M12x1.5', 'MF', 1.5, 'mm', '7/16-20', '7/16'),
    ('M14x1.5', 'M14x1.5', 'MF', 1.5, 'mm', '1/2-20', '1/2'),
    ('M16x1.5', 'M16x1.5', 'MF', 1.5, 'mm', '5/8-18', '5/8'),
]

FAMILIES = [('UNC', 'UNC'), ('UNF', 'UNF'), ('M', 'Metric'), ('MF', 'M fine')]


def _entry(t):
    key, label, fam, pitch, unit, row, derived = t
    mn, mx, blo, bhi, clutch = _ROWS[row]
    if unit == 'tpi':
        dia = _DIA[label.split('-')[0]]
    else:
        dia = float(key[1:].split('x')[0])
    return {'key': key, 'label': label, 'family': fam, 'pitch': pitch, 'unit': unit, 'dia_mm': dia,
            'pitch_mm': 25.4 / pitch if unit == 'tpi' else float(pitch),
            'min': mn, 'max': mx, 'break_lo': blo, 'break_hi': bhi, 'clutch': clutch,
            'derived': derived}


THREADS = [_entry(t) for t in _SIZES]
BY_KEY = dict((t['key'], t) for t in THREADS)


def family(fam):
    return [t for t in THREADS if t['family'] == fam]


def full_name(t):
    if t['unit'] == 'tpi':
        return '%s %s' % (t['label'], t['family'])
    return t['key'].replace('x', ' x ')


def pct_of_spindle(in_lb, motor_rated_nm, ratio):
    """Torque at the tap (in-lb) as a percent of the motor's rated torque,
    through the belt ratio."""
    spindle_in_lb = motor_rated_nm * ratio * IN_LB_PER_NM
    return 100.0 * in_lb / spindle_in_lb if spindle_in_lb > 0 else 0.0


def cutting_torque_in_lb(pitch_mm, dia_mm, material):
    """Estimated torque to cut the thread, in-lb, or None when the material
    has no published specific cutting force."""
    ks = KS.get(material)
    if ks is None or pitch_mm <= 0 or dia_mm <= 0:
        return None
    return 0.2 * pitch_mm ** 2 * ks * dia_mm / 1000.0 * IN_LB_PER_NM
