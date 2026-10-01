"""Kivy log housekeeping: size cap, file roll-over, the file in use is kept.

    python tests/test_logcap.py
"""
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import logcap                                                     # noqa: E402

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print('%-52s got %-22r want %-22r %s' % (label, got, want, 'OK' if ok else 'FAIL'))


def make(d, name, size, age):
    path = os.path.join(d, name)
    with open(path, 'wb') as fh:
        fh.write(b'x' * size)
    os.utime(path, (1000000 - age, 1000000 - age))
    return path


# ---- prune: oldest first, down to the cap
d = tempfile.mkdtemp()
for i in range(10):                      # file 0 is the oldest
    make(d, 'kivy_%d.txt' % i, 100, age=100 - i)
removed, total = logcap.prune(d, cap=450)
check('oldest files go until under the cap', (removed, total, sorted(os.listdir(d))),
      (6, 400, ['kivy_6.txt', 'kivy_7.txt', 'kivy_8.txt', 'kivy_9.txt']))
check('already under the cap: nothing touched', logcap.prune(d, cap=450), (0, 400))

# ---- the file being written is never removed, even when it is the oldest or too big
d = tempfile.mkdtemp()
cur = make(d, 'current.txt', 900, age=500)
make(d, 'a.txt', 100, age=50)
make(d, 'b.txt', 100, age=10)
removed, total = logcap.prune(d, cap=300, keep=cur)
check('everything else goes, the open file stays', (removed, total, os.listdir(d)), (2, 900, ['current.txt']))


# ---- roll: a long session moves on to a new file
class Handler:
    """Stands in for kivy.logger.FileHandler: class-level fd / filename."""
    fd = None
    filename = ''

    def __init__(self, d):
        self.log_dir = d
        self.lock = threading.RLock()
        self.n = 0
        self._configure()

    def acquire(self):
        self.lock.acquire()

    def release(self):
        self.lock.release()

    def _configure(self):
        cls = type(self)
        if cls.fd:
            cls.fd.close()
        cls.filename = os.path.join(self.log_dir, 'kivy_%d.txt' % self.n)
        self.n += 1
        cls.fd = open(cls.filename, 'w')


d = tempfile.mkdtemp()
h = Handler(d)
Handler.fd.write('y' * 500)
Handler.fd.flush()
check('small file: no roll', (logcap.roll(h, limit=1000), os.path.basename(Handler.filename)), (False, 'kivy_0.txt'))
Handler.fd.write('y' * 700)
Handler.fd.flush()
check('past the limit: new file started', (logcap.roll(h, limit=1000), os.path.basename(Handler.filename)),
      (True, 'kivy_1.txt'))
logcap.sync(h)                            # must not raise
# a long session: many rolls, the folder still ends up under the cap
for i in range(12):
    Handler.fd.write('z' * 1100)
    Handler.fd.flush()
    rolled, removed, total = logcap.check(h, cap=4000, limit=1000)
check('long session stays under the cap', (total <= 4000, os.path.exists(Handler.filename)), (True, True))
check('newest history kept, oldest gone', ('kivy_0.txt' in os.listdir(d), len(os.listdir(d)) >= 3), (False, True))
Handler.fd.close()

print('RESULT:', 'ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
