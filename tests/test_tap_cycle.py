"""Off-Pico test of the node's tap cycle (firmware/main_node.py TapCycle)
against a simulated XP200.  Run from the repo root:

    python tests/test_tap_cycle.py

The class is lifted out of the firmware source with ast, so this tests the
exact code that runs on the node."""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'firmware', 'main_node.py'), encoding='utf-8').read()
node = next(n for n in ast.parse(SRC).body if isinstance(n, ast.ClassDef) and n.name == 'TapCycle')
ns = {}
exec(compile(ast.Module(body=[node], type_ignores=[]), 'main_node.py', 'exec'), ns)
TapCycle = ns['TapCycle']

fails = []


def check(label, got, want):
    ok = got == want
    print('%-52s got %-22r want %-22r %s' % (label, got, want, 'OK' if ok else 'FAIL'))
    if not ok:
        fails.append(label)


class SimDrive:
    """Motor position in encoder counts, a torque cap and a hole bottom.
    counts_dir: which way the counts run for a positive (in) speed.
    swap: position low word in register 6 instead of 5."""
    CPR = 10000

    def __init__(self, bottom=None, counts_dir=1, swap=False, start=123456789,
                 jam_out=False, fail_reads=0, alarm_at=None):
        self.pos = start                 # absolute motor counts
        self.origin = start
        self.speed = 0                   # commanded motor rpm (signed, + = in)
        self.enabled = False
        self.regs = {65: 300, 66: -300}
        self.writes = []
        self.bottom = bottom             # counts in from the origin where the tap bottoms
        self.counts_dir = counts_dir
        self.swap = swap
        self.jam_out = jam_out
        self.fail_reads = fail_reads
        self.alarm_at = alarm_at
        self.t = 0
        self.torque = 0
        self.log_lines = []
        self.restored = 0

    # ---- io for TapCycle
    def read_block(self):
        self.t += 20                     # one bus transaction
        self._move(20)
        if self.fail_reads:
            self.fail_reads -= 1
            return None
        v = self.pos & 0xFFFFFFFF
        lo, hi = v & 0xFFFF, v >> 16
        w5, w6 = (hi, lo) if self.swap else (lo, hi)
        return (w5, w6, self.torque & 0xFFFF)

    def read_alarm(self):
        if self.alarm_at is not None and self.t >= self.alarm_at:
            return 29
        return 0

    def read_limits(self):
        return (self.regs[65], self.regs[66])

    def write(self, addr, value):
        self.regs[addr] = value
        self.writes.append((addr, value))
        return True

    def set_speed(self, speed):
        self.speed = speed
        return True

    def set_enabled(self, on):
        self.enabled = on
        return True

    def restore_speed(self):
        self.restored += 1

    def now_ms(self):
        return self.t

    def log(self, *a):
        self.log_lines.append(' '.join(str(x) for x in a))

    # ---- physics
    def depth(self):
        return (self.pos - self.origin) * self.counts_dir

    def _move(self, ms):
        if not self.enabled or self.speed == 0:
            self.torque = 0
            return
        step = round(self.speed * self.CPR / 60000.0 * ms)       # counts this slice
        new_depth = self.depth() + step
        cap = self.regs[65]
        if self.speed > 0 and self.bottom is not None and new_depth >= self.bottom:
            new_depth = self.bottom                               # bottomed: stall at the cap
            self.torque = cap
        elif self.speed < 0 and self.jam_out:
            new_depth = self.depth()
            self.torque = -cap
        else:
            self.torque = 20 if self.speed > 0 else -10
        self.pos = self.origin + new_depth * self.counts_dir


def run(cyc, sim, limit_ms=60000):
    while cyc.active and sim.t < limit_ms:
        cyc.step()
    return cyc


CPR = SimDrive.CPR
ratio = 1.65
turn = int(CPR * ratio)                  # motor counts per spindle turn

# 1. to depth: 10 turns in, back out 2 turns past the origin, limits restored
for swap in (False, True):
    for cdir in (1, -1):
        sim = SimDrive(counts_dir=cdir, swap=swap)
        cyc = TapCycle(sim)
        ok = cyc.start(165, 30, 10 * turn, 2 * turn, 150, False)
        run(cyc, sim)
        tag = 'swap=%s dir=%+d' % (swap, cdir)
        check('depth %s: started, done' % tag, (ok, cyc.state), (True, TapCycle.DONE))
        check('depth %s: reason depth, peak ~10 turns' % tag,
              (cyc.reason, round(cyc.peak / turn, 1)), (TapCycle.R_DEPTH, 10.0))
        check('depth %s: ended 2 turns out, drive off' % tag,
              (round(sim.depth() / turn), sim.enabled), (-2, False))
        check('depth %s: torque cap set then restored' % tag,
              (sim.writes[:2], (sim.regs[65], sim.regs[66])), ([(65, 30), (66, -30)], (300, -300)))
        check('depth %s: panel speed restored' % tag, sim.restored, 1)

# 2. to bottom: stall at 6.3 turns, reverse out
sim = SimDrive(bottom=int(6.3 * turn))
cyc = TapCycle(sim)
cyc.start(165, 30, 20 * turn, 2 * turn, 150, False)
run(cyc, sim)
check('bottom: reason stall, done', (cyc.state, cyc.reason), (TapCycle.DONE, TapCycle.R_STALL))
check('bottom: peak at the bottom', round(cyc.peak / turn, 2), 6.3)
check('bottom: backed out 2 turns', round(sim.depth() / turn), -2)

# 3. second pass keeps the origin: same bottom -> same peak
cyc.start(165, 30, 20 * turn, 2 * turn, 150, True)
run(cyc, sim)
check('re-enter keeps origin: same peak', round(cyc.peak / turn, 2), 6.3)

# 4. a fresh start resets the origin
cyc.start(165, 30, 3 * turn, 2 * turn, 150, False)
run(cyc, sim)
check('new origin: 3 turns from where it started', (cyc.reason, round(cyc.peak / turn)), (TapCycle.R_DEPTH, 3))

# 5. no stall during spin-up even if it has not moved yet
sim = SimDrive(bottom=0)                     # tap already hard against the bottom
cyc = TapCycle(sim)
cyc.start(165, 30, 20 * turn, 2 * turn, 150, False)
t_stall = None
while cyc.state == TapCycle.IN and sim.t < 5000:
    cyc.step()
t_stall = sim.t
check('stall not before spin-up (400 ms)', t_stall >= 400, True)
run(cyc, sim)
check('stall at the start still backs out', (cyc.state, cyc.reason), (TapCycle.DONE, TapCycle.R_STALL))

# 6. jammed on the way out: halt with the drive off and limits back
sim = SimDrive(bottom=int(4 * turn), jam_out=True)
cyc = TapCycle(sim)
cyc.start(165, 30, 20 * turn, 2 * turn, 150, False)
run(cyc, sim)
check('jam: halted, reason jam', (cyc.state, cyc.reason), (TapCycle.HALTED, TapCycle.R_JAM))
check('jam: drive off, limits back', (sim.enabled, sim.regs[65], sim.regs[66]), (False, 300, -300))

# 7. panel stop mid-hole, then reverse out
sim = SimDrive()
cyc = TapCycle(sim)
cyc.start(165, 30, 20 * turn, 2 * turn, 150, False)
while cyc.counts < 5 * turn:
    cyc.step()
cyc.abort(TapCycle.R_PANEL)
check('stop: halted with drive off, limits back', (cyc.state, cyc.reason, sim.enabled, sim.regs[65]),
      (TapCycle.HALTED, TapCycle.R_PANEL, False, 300))
check('reverse out accepted', cyc.reverse_out(), True)
check('reverse out: cap set again', sim.regs[65], 30)
run(cyc, sim)
check('reverse out: done, 2 turns out, limits back', (cyc.state, round(sim.depth() / turn), sim.regs[65]),
      (TapCycle.DONE, -2, 300))
check('reverse out: reason says so', cyc.reason, TapCycle.R_OUT)

# 8. link lost going in: backs out by itself
sim = SimDrive()
cyc = TapCycle(sim)
cyc.start(165, 30, 20 * turn, 2 * turn, 150, False)
while cyc.counts < 4 * turn:
    cyc.step()
cyc.link_lost()
run(cyc, sim)
check('link lost: backed out and stopped', (cyc.state, cyc.reason, round(sim.depth() / turn), sim.enabled),
      (TapCycle.DONE, TapCycle.R_LINK, -2, False))

# 9. bus failures: halt after FAIL_MAX in a row, a single glitch is fine
sim = SimDrive(fail_reads=1)
cyc = TapCycle(sim)
check('position unreadable at start: refused, drive untouched',
      (cyc.start(165, 30, 5 * turn, 2 * turn, 150, False), sim.enabled, sim.regs[65]), (False, False, 300))
sim = SimDrive()
cyc = TapCycle(sim)
cyc.start(165, 30, 5 * turn, 2 * turn, 150, False)
for _ in range(5):
    cyc.step()
sim.fail_reads = 1
run(cyc, sim)
check('one failed read mid-pass: pass completes', (cyc.state, round(cyc.peak / turn)), (TapCycle.DONE, 5))
sim = SimDrive()
cyc = TapCycle(sim)
cyc.start(165, 30, 20 * turn, 2 * turn, 150, False)
for _ in range(10):
    cyc.step()
sim.fail_reads = 10
run(cyc, sim)
check('bus lost: halted, drive off', (cyc.state, cyc.reason, sim.enabled), (TapCycle.HALTED, TapCycle.R_COMM, False))

# 10. drive alarm mid-pass
sim = SimDrive(alarm_at=1500)
cyc = TapCycle(sim)
cyc.start(165, 30, 50 * turn, 2 * turn, 150, False)
run(cyc, sim)
check('drive alarm: halted', (cyc.state, cyc.reason, sim.enabled), (TapCycle.HALTED, TapCycle.R_DRIVE, False))

# 11. left-hand tap: negative speed in, still counts "in" as positive
sim = SimDrive(counts_dir=-1)
cyc = TapCycle(sim)
cyc.start(-165, 30, 4 * turn, 2 * turn, 150, False)
run(cyc, sim)
check('LH tap: to depth and out', (cyc.state, cyc.reason, round(cyc.peak / turn)), (TapCycle.DONE, TapCycle.R_DEPTH, 4))

# 12. unreadable torque limits: refuse without touching the drive
sim = SimDrive()
sim.read_limits = lambda: None
cyc = TapCycle(sim)
check('limits unreadable: refused, nothing enabled', (cyc.start(165, 30, 4 * turn, 0, 150, False), sim.enabled,
                                                     sim.writes), (False, False, []))

print('RESULT:', 'ALL PASS' if not fails else fails)
