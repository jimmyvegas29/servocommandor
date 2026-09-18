"""Servocom machine node launcher (main.py on the Pico).  Never updated over
the air.  The real firmware is node.py; an over-the-air update arrives as
node_new.py and is swapped in here with a rollback if it never confirms.

  node_new.py present  -> node.py becomes node_prev.py, node_new.py becomes
                          node.py, trial.flag is set
  trial.flag present   -> the previous boot was a trial that never confirmed
                          (crash, watchdog, power cut): put node_prev.py back
  node.py raises       -> print it and reset (with trial.flag set this rolls
                          back on the way round)
"""
import os
import sys
import time
import machine


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


if exists('node_new.py'):
    if exists('node_prev.py'):
        os.remove('node_prev.py')
    if exists('node.py'):
        os.rename('node.py', 'node_prev.py')
    os.rename('node_new.py', 'node.py')
    with open('trial.flag', 'w') as fh:
        fh.write('1')
    print('LAUNCHER installed new node.py (trial)')
elif exists('trial.flag'):
    # a trial image is running and has not confirmed yet.  Roll back if it
    # died (watchdog reset, or the crash flag written below) or if this is
    # already its third boot without confirming (a hang that never reached
    # the watchdog, cleared by a power cycle).
    try:
        boots = int(open('trial.flag').read().strip() or '1')
    except (OSError, ValueError):
        boots = 1
    crashed = machine.reset_cause() == machine.WDT_RESET or exists('crash.flag') or boots >= 3
    if exists('crash.flag'):
        os.remove('crash.flag')
    if not crashed:
        with open('trial.flag', 'w') as fh:
            fh.write(str(boots + 1))
    if crashed and exists('node_prev.py'):
        os.remove('trial.flag')
        if exists('node.py'):
            if exists('node_bad.py'):
                os.remove('node_bad.py')
            os.rename('node.py', 'node_bad.py')
        os.rename('node_prev.py', 'node.py')
        print('LAUNCHER trial image died: rolled back to previous node.py')
    else:
        print('LAUNCHER trial image gets another boot to confirm')

try:
    import node  # noqa: F401  (runs forever)
except Exception as exc:
    sys.print_exception(exc)
    with open('crash.flag', 'w') as fh:
        fh.write('1')
    print('LAUNCHER node.py crashed, resetting in 3 s')
    time.sleep(3)
    machine.reset()
