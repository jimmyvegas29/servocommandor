"""Tap sizes and tapping torque for the Tap tool.

Torque rows (inch-pounds, at the tap) are Tapmatic's published "Torque
Setting Data For HSS Straight Flute Plug Taps": minimum and maximum tapping
torque, breaking torque of a low- and a high-strength tap, and the clutch
setting Tapmatic recommends for its torque-limiting heads (the "normal"
column).  The panel uses that clutch setting as the torque cap.
https://www.tapmatic.com/tapping_questions_torque_setting_data_for_hss.ydev

Tapmatic lists inch sizes only.  Metric sizes use the row of the next
SMALLER inch size, so their cap errs low (they are marked derived).
"""

IN_LB_PER_NM = 8.8507

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
    ('#1-64', '#1-64', 'UNC', 64, 'tpi', '0-2', ''),
    ('#2-56', '#2-56', 'UNC', 56, 'tpi', '0-2', ''),
    ('#3-48', '#3-48', 'UNC', 48, 'tpi', '3-4', ''),
    ('#4-40', '#4-40', 'UNC', 40, 'tpi', '3-4', ''),
    ('#5-40', '#5-40', 'UNC', 40, 'tpi', '5-6', ''),
    ('#6-32', '#6-32', 'UNC', 32, 'tpi', '5-6', ''),
    ('#8-32', '#8-32', 'UNC', 32, 'tpi', '8', ''),
    ('#10-24', '#10-24', 'UNC', 24, 'tpi', '10-24', ''),
    ('#12-24', '#12-24', 'UNC', 24, 'tpi', '12', ''),
    ('1/4-20', '1/4-20', 'UNC', 20, 'tpi', '1/4-20', ''),
    ('5/16-18', '5/16-18', 'UNC', 18, 'tpi', '5/16-18', ''),
    ('3/8-16', '3/8-16', 'UNC', 16, 'tpi', '3/8-16', ''),
    ('7/16-14', '7/16-14', 'UNC', 14, 'tpi', '7/16-14', ''),
    ('1/2-13', '1/2-13', 'UNC', 13, 'tpi', '1/2-13', ''),
    ('9/16-12', '9/16-12', 'UNC', 12, 'tpi', '9/16-12', ''),
    ('5/8-11', '5/8-11', 'UNC', 11, 'tpi', '5/8-11', ''),
    ('3/4-10', '3/4-10', 'UNC', 10, 'tpi', '3/4-10', ''),
    # UNF
    ('#0-80', '#0-80', 'UNF', 80, 'tpi', '0-2', ''),
    ('#1-72', '#1-72', 'UNF', 72, 'tpi', '0-2', ''),
    ('#2-64', '#2-64', 'UNF', 64, 'tpi', '0-2', ''),
    ('#3-56', '#3-56', 'UNF', 56, 'tpi', '3-4', ''),
    ('#4-48', '#4-48', 'UNF', 48, 'tpi', '3-4', ''),
    ('#5-44', '#5-44', 'UNF', 44, 'tpi', '5-6', ''),
    ('#6-40', '#6-40', 'UNF', 40, 'tpi', '5-6', ''),
    ('#8-36', '#8-36', 'UNF', 36, 'tpi', '8', ''),
    ('#10-32', '#10-32', 'UNF', 32, 'tpi', '10-32', ''),
    ('#12-28', '#12-28', 'UNF', 28, 'tpi', '12', ''),
    ('1/4-28', '1/4-28', 'UNF', 28, 'tpi', '1/4-28', ''),
    ('5/16-24', '5/16-24', 'UNF', 24, 'tpi', '5/16-24', ''),
    ('3/8-24', '3/8-24', 'UNF', 24, 'tpi', '3/8-24', ''),
    ('7/16-20', '7/16-20', 'UNF', 20, 'tpi', '7/16-20', ''),
    ('1/2-20', '1/2-20', 'UNF', 20, 'tpi', '1/2-20', ''),
    ('9/16-18', '9/16-18', 'UNF', 18, 'tpi', '9/16-18', ''),
    ('5/8-18', '5/8-18', 'UNF', 18, 'tpi', '5/8-18', ''),
    ('3/4-16', '3/4-16', 'UNF', 16, 'tpi', '3/4-16', ''),
    # metric coarse (row of the next smaller inch size)
    ('M2x0.4', 'M2', 'M', 0.4, 'mm', '0-2', '#0-#2'),
    ('M2.5x0.45', 'M2.5', 'M', 0.45, 'mm', '0-2', '#2'),
    ('M3x0.5', 'M3', 'M', 0.5, 'mm', '3-4', '#4'),
    ('M3.5x0.6', 'M3.5', 'M', 0.6, 'mm', '5-6', '#5'),
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
    mn, mx, blo, bhi, clutch = _ROWS[row]
    return {'key': key, 'label': label, 'family': fam, 'pitch': pitch, 'unit': unit,
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
