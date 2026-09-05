"""Central logging for Servo Commandor.

Writes to logs/servocom.log next to the app (rotating, 5 x 1MB) and also
echoes to the console when run from a terminal. Auto-configures on import,
and hooks uncaught exceptions from the main thread and all background
threads so crashes are recorded with full tracebacks.

Review after an issue:  tail -100 ~/servocommandor/logs/servocom.log
"""
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')

log = logging.getLogger('servocom')


def _excepthook(exc_type, exc, tb):
    log.critical('UNCAUGHT EXCEPTION - app is going down',
                 exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def _thread_excepthook(args):
    name = args.thread.name if args.thread else 'unknown-thread'
    log.critical('UNCAUGHT EXCEPTION in thread %s', name,
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _setup():
    if log.handlers:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        '%(asctime)s.%(msecs)03d %(levelname)-8s [%(threadName)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'servocom.log'),
        maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log.addHandler(console)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    log.info('==================== Servo Commandor starting ====================')


_setup()
