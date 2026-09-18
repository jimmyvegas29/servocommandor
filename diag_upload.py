"""Diagnostic bundle upload: SEND LOG on the System page.

Builds a bundle from the latest DRO capture (or a fresh one), the panel's
settings, servo.ini, build ids and a screenshot, then uploads it into the
private servocom-logs GitHub repo through the contents API, one HTTPS PUT
per file, into a folder named after the panel:

    <panel>/<YYYY-MM-DD_HHMM>_<build>.log.gz
    <panel>/<YYYY-MM-DD_HHMM>_<build>.json
    <panel>/<YYYY-MM-DD_HHMM>_<build>.png

The token lives in ~/.servocom/upload_token, outside the code tree, and is
never logged.  Bundles that could not be sent wait in logs/pending/ and are
retried every few minutes while the app runs.
"""
import base64
import gzip
import json
import os
import platform
import re
import shutil
import threading
import time
import urllib.error
import urllib.request

from applog import log, LOG_DIR

REPO = 'jimmyvegas29/servocom-logs'
TOKEN_PATH = os.path.expanduser('~/.servocom/upload_token')
PENDING_DIR = os.path.join(LOG_DIR, 'pending')
RETRY_S = 300
API = 'https://api.github.com'


def pi_serial():
    """The Pi's CPU serial, the panel's default identity."""
    for path in ('/sys/firmware/devicetree/base/serial-number', '/proc/cpuinfo'):
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            continue
        if 'cpuinfo' in path:
            for line in text.splitlines():
                if line.startswith('Serial'):
                    return line.split(':', 1)[1].strip().lstrip('0') or 'pi'
        else:
            return text.strip('\x00\n ').lstrip('0') or 'pi'
    return platform.node() or 'panel'


def safe_name(name):
    keep = ''.join(c if (c.isalnum() or c in '-_') else '-' for c in name.strip())
    keep = re.sub(r'-{2,}', '-', keep)
    return keep.strip('-') or 'panel'


def read_token():
    try:
        with open(TOKEN_PATH, encoding='ascii', errors='ignore') as fh:
            tok = fh.read().strip()
    except OSError:
        return None
    if not tok.startswith('github_pat_') or not all(c.isalnum() or c == '_' for c in tok):
        return None
    return tok


def has_token():
    return read_token() is not None


# ---------------------------------------------------------------- bundle
def build_bundle(panel, capture_path, manifest, screenshot_path=None):
    """Write the bundle files into logs/pending/<stamp>/ and return that dir."""
    stamp = time.strftime('%Y-%m-%d_%H%M')
    build = safe_name(manifest.get('build', 'build'))
    base = '%s_%s' % (stamp, build)
    out = os.path.join(PENDING_DIR, base)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'panel'), 'w', encoding='utf-8') as fh:
        fh.write(safe_name(panel))
    if capture_path and os.path.exists(capture_path):
        with open(capture_path, 'rb') as src, gzip.open(os.path.join(out, base + '.log.gz'), 'wb') as dst:
            shutil.copyfileobj(src, dst)
    with open(os.path.join(out, base + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    if screenshot_path and os.path.exists(screenshot_path):
        shutil.copyfile(screenshot_path, os.path.join(out, base + '.png'))
    return out


def pending_bundles():
    try:
        return sorted(os.path.join(PENDING_DIR, d) for d in os.listdir(PENDING_DIR)
                      if os.path.isdir(os.path.join(PENDING_DIR, d)))
    except OSError:
        return []


# ---------------------------------------------------------------- upload
class UploadError(Exception):
    pass


def _put_file(token, repo_path, data, message):
    body = json.dumps({'message': message,
                       'content': base64.b64encode(data).decode('ascii')}).encode('utf-8')
    req = urllib.request.Request('%s/repos/%s/contents/%s' % (API, REPO, repo_path), data=body,
                                 method='PUT',
                                 headers={'Authorization': 'Bearer ' + token,
                                          'Accept': 'application/vnd.github+json',
                                          'Content-Type': 'application/json',
                                          'User-Agent': 'servocom-panel'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        # never let the response echo anything back into the log
        raise UploadError('GitHub answered HTTP %d for %s' % (exc.code, os.path.basename(repo_path)))
    except (urllib.error.URLError, OSError) as exc:
        raise UploadError('no connection (%s)' % type(exc).__name__)


def send_bundle(bundle_dir, transport=None):
    """Upload every file in the bundle dir; remove the dir when all are up.
    transport(token, repo_path, data, message) can be swapped in by tests."""
    put = transport or _put_file
    token = read_token() if transport is None else 'test'
    if token is None:
        raise UploadError('no upload token on this panel')
    with open(os.path.join(bundle_dir, 'panel'), encoding='utf-8') as fh:
        panel = fh.read().strip()
    files = sorted(f for f in os.listdir(bundle_dir) if f != 'panel' and not f.endswith('.sent'))
    for name in files:
        path = os.path.join(bundle_dir, name)
        if os.path.exists(path + '.sent'):
            continue
        with open(path, 'rb') as fh:
            data = fh.read()
        put(token, '%s/%s' % (panel, name), data, 'panel %s: %s' % (panel, name))
        open(path + '.sent', 'w').close()
    shutil.rmtree(bundle_dir, ignore_errors=True)
    return '%s/%s' % (panel, os.path.basename(bundle_dir))


class Uploader:
    """Background sender with retry.  status() is safe to poll from the UI."""

    def __init__(self, transport=None):
        self.transport = transport
        self._lock = threading.Lock()
        self._state = 'idle'          # idle / sending / sent / failed / pending
        self._detail = ''
        self._last_try = 0.0
        self._thread = None

    def status(self):
        with self._lock:
            return self._state, self._detail

    def _set(self, state, detail=''):
        with self._lock:
            self._state, self._detail = state, detail

    def send_now(self):
        if self._thread is not None and self._thread.is_alive():
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def tick(self):
        """Call periodically from the UI clock: retries pending bundles."""
        if pending_bundles() and time.monotonic() - self._last_try > RETRY_S:
            self.send_now()

    def _run(self):
        self._last_try = time.monotonic()
        bundles = pending_bundles()
        if not bundles:
            self._set('idle')
            return
        self._set('sending', '%d bundle%s' % (len(bundles), '' if len(bundles) == 1 else 's'))
        sent = []
        for b in bundles:
            try:
                sent.append(send_bundle(b, self.transport))
            except UploadError as exc:
                left = len(pending_bundles())
                self._set('failed', '%s; %d waiting, retry in %d min' % (exc, left, RETRY_S // 60))
                log.warning('Diagnostic upload failed: %s (%d pending)', exc, left)
                return
            except Exception as exc:
                self._set('failed', '%s; will retry' % type(exc).__name__)
                log.error('Diagnostic upload error: %s', type(exc).__name__)
                return
        self._set('sent', sent[-1])
        log.info('Diagnostic upload sent: %s', ', '.join(sent))
