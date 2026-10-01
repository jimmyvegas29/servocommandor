"""Keeps Kivy's own log folder (~/.kivy/logs) bounded and durable.

That log records every raw Bluetooth packet from the machine node (bleak's
D-Bus debug output), which makes it the panel's black box: it is what showed,
frame by frame, the drive dropping off the RS-485 line on 2026-09-30.  Left
alone it grows about 23 MB per hour of running and Kivy only limits the
number of files, not their size.

  * the folder is held to CAP_BYTES: the oldest files go first, the file
    being written is never touched
  * a session's file is closed and a new one started every FILE_BYTES, so a
    long session can be trimmed too
  * the file being written is pushed through to the card every SYNC_S, so
    cutting the power loses a couple of seconds, not half a minute
"""
import logging
import os
import threading
import time

from applog import log

CAP_BYTES = 250 * 1024 * 1024        # about 11 hours of running
FILE_BYTES = 50 * 1024 * 1024        # about 2 hours per file
SYNC_S = 2.0
CHECK_S = 600.0

_thread = None


def _handler():
    """Kivy's file log handler (it sits on the root logger), or None."""
    try:
        from kivy.logger import FileHandler
    except Exception:
        return None
    for h in logging.getLogger().handlers:
        if isinstance(h, FileHandler):
            return h
    return None


def prune(log_dir, cap=CAP_BYTES, keep=None):
    """Delete the oldest files in log_dir until it holds cap bytes or less.
    keep (the file being written) is never deleted.  Returns (files
    removed, bytes left)."""
    files = []
    for name in os.listdir(log_dir):
        path = os.path.join(log_dir, name)
        try:
            if os.path.isfile(path):
                st = os.stat(path)
                files.append((st.st_mtime, st.st_size, path))
        except OSError:
            pass
    files.sort()
    total = sum(f[1] for f in files)
    removed = 0
    keep = os.path.abspath(keep) if keep else None
    for _mtime, size, path in files:
        if total <= cap:
            break
        if keep and os.path.abspath(path) == keep:
            continue
        try:
            os.remove(path)
            total -= size
            removed += 1
        except OSError:
            pass
    return removed, total


def roll(handler, limit=FILE_BYTES):
    """Start a new log file once the current one passes limit bytes."""
    cls = type(handler)
    fd, name = getattr(cls, 'fd', None), getattr(cls, 'filename', '')
    if fd in (None, False) or not name:
        return False
    try:
        if os.path.getsize(name) < limit:
            return False
    except OSError:
        return False
    handler.acquire()                    # no record is written while the file is swapped
    try:
        handler._configure()             # picks the next free name and re-opens
    finally:
        handler.release()
    return True


def sync(handler):
    fd = getattr(type(handler), 'fd', None)
    if fd in (None, False):
        return
    try:
        os.fsync(fd.fileno())
    except (OSError, ValueError):
        pass


def check(handler, cap=CAP_BYTES, limit=FILE_BYTES):
    """One housekeeping pass; returns (rolled, files removed, bytes left)."""
    rolled = roll(handler, limit)
    removed, total = prune(handler.log_dir, cap, keep=type(handler).filename)
    if rolled or removed:
        log.info('Kivy log housekeeping: %s%d old file(s) removed, %.0f MB kept',
                 'new file started, ' if rolled else '', removed, total / 1048576.0)
    return rolled, removed, total


def _run(handler):
    next_check = 0.0
    while True:
        now = time.monotonic()
        if now >= next_check:
            next_check = now + CHECK_S
            try:
                check(handler)
            except Exception as exc:                       # never take the app down
                log.warning('Kivy log housekeeping failed: %s', exc)
        sync(handler)
        time.sleep(SYNC_S)


def start():
    """Begin the housekeeping thread (once).  Returns True if it is running."""
    global _thread
    if _thread is not None:
        return True
    handler = _handler()
    if handler is None or not getattr(handler, 'log_dir', ''):
        return False
    _thread = threading.Thread(target=_run, args=(handler,), name='logcap', daemon=True)
    _thread.start()
    return True
