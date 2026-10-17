"""Tap sizes and tapping torque for the Tap tool.

Torque rows (inch-pounds, at the tap) are from Tapmatic's published "Torque
Setting Data For HSS Straight Flute Plug Taps": the tapping torque (least
and most it takes to cut the thread) and the breaking torque of an HSS tap.
The auto torque cap is BREAK_SHARE of the breaking torque (plus spindle
drag): always above the most it takes to cut, never at the break.
https://www.tapmatic.com/tapping_questions_torque_setting_data_for_hss.ydev

The small sizes (#8 and #10, M3, M4, M5) are there to find how small a
tap the lathe can drive without breaking it.  Tapmatic lists inch sizes
only.  Metric sizes use the row of the next SMALLER inch size, so their cap
errs low (they are marked derived).
"""

IN_LB_PER_NM = 8.8507

# Jimmy, 2026-10-16: every size gets 90 % of its breaking torque (the
# old clutch-setting caps sat below what a 1/4-20 needs to cut).
BREAK_SHARE = 0.90

# major diameter, mm, of the numbered and fractional sizes
_DIA = {'#0': 1.524, '#1': 1.854, '#2': 2.184, '#3': 2.515, '#4': 2.845, '#5': 3.175, '#6': 3.505,
        '#8': 4.166, '#10': 4.826, '#12': 5.486, '1/4': 6.35, '5/16': 7.9375, '3/8': 9.525,
        '7/16': 11.1125, '1/2': 12.7, '9/16': 14.2875, '5/8': 15.875, '3/4': 19.05}

# row: (min tapping, max tapping, breaking), in-lb
_ROWS = {
    '0-2': (10, 18, 50),
    '3-4': (10, 20, 50),
    '5-6': (10, 20, 50),
    '8': (20, 30, 60),
    '10-32': (20, 30, 60),
    '10-24': (25, 50, 60),
    '12': (25, 50, 70),
    '1/4-28': (30, 60, 100),
    '1/4-20': (40, 80, 100),
    '5/16-24': (40, 80, 150),
    '5/16-18': (60, 120, 150),
    '3/8-24': (60, 120, 260),
    '3/8-16': (100, 200, 260),
    '7/16-20': (80, 160, 300),
    '7/16-14': (100, 200, 300),
    '1/2-20': (100, 250, 600),
    '1/2-13': (150, 300, 600),
    '9/16-18': (150, 350, 800),
    '9/16-12': (200, 500, 800),
    '5/8-18': (200, 600, 1200),
    '5/8-11': (300, 800, 1200),
    '3/4-16': (300, 800, 1500),
    '3/4-10': (500, 1000, 1500),
}

# (key, label, family, pitch value, pitch unit, table row, derived-from label or '')
_SIZES = [
    # UNC
    ('#8-32', '#8-32', 'UNC', 32, 'tpi', '8', ''),
    ('#10-24', '#10-24', 'UNC', 24, 'tpi', '10-24', ''),
    ('1/4-20', '1/4-20', 'UNC', 20, 'tpi', '1/4-20', ''),
    ('5/16-18', '5/16-18', 'UNC', 18, 'tpi', '5/16-18', ''),
    ('3/8-16', '3/8-16', 'UNC', 16, 'tpi', '3/8-16', ''),
    ('7/16-14', '7/16-14', 'UNC', 14, 'tpi', '7/16-14', ''),
    ('1/2-13', '1/2-13', 'UNC', 13, 'tpi', '1/2-13', ''),
    ('9/16-12', '9/16-12', 'UNC', 12, 'tpi', '9/16-12', ''),
    ('5/8-11', '5/8-11', 'UNC', 11, 'tpi', '5/8-11', ''),
    ('3/4-10', '3/4-10', 'UNC', 10, 'tpi', '3/4-10', ''),
    # UNF
    ('#8-36', '#8-36', 'UNF', 36, 'tpi', '8', ''),
    ('#10-32', '#10-32', 'UNF', 32, 'tpi', '10-32', ''),
    ('1/4-28', '1/4-28', 'UNF', 28, 'tpi', '1/4-28', ''),
    ('5/16-24', '5/16-24', 'UNF', 24, 'tpi', '5/16-24', ''),
    ('3/8-24', '3/8-24', 'UNF', 24, 'tpi', '3/8-24', ''),
    ('7/16-20', '7/16-20', 'UNF', 20, 'tpi', '7/16-20', ''),
    ('1/2-20', '1/2-20', 'UNF', 20, 'tpi', '1/2-20', ''),
    ('9/16-18', '9/16-18', 'UNF', 18, 'tpi', '9/16-18', ''),
    ('5/8-18', '5/8-18', 'UNF', 18, 'tpi', '5/8-18', ''),
    ('3/4-16', '3/4-16', 'UNF', 16, 'tpi', '3/4-16', ''),
    # metric coarse (row of the next smaller inch size)
    ('M3x0.5', 'M3', 'M', 0.5, 'mm', '3-4', '#4'),
    ('M4x0.7', 'M4', 'M', 0.7, 'mm', '5-6', '#6'),
    ('M5x0.8', 'M5', 'M', 0.8, 'mm', '10-24', '#10'),
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
    mn, mx, brk = _ROWS[row]
    if unit == 'tpi':
        dia = _DIA[label.split('-')[0]]
    else:
        dia = float(key[1:].split('x')[0])
    return {'key': key, 'label': label, 'family': fam, 'pitch': pitch, 'unit': unit, 'dia_mm': dia,
            'pitch_mm': 25.4 / pitch if unit == 'tpi' else float(pitch),
            'min': mn, 'max': mx, 'break': brk, 'cap_in_lb': BREAK_SHARE * brk,
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
