#!/usr/bin/env python3
"""tests/test_multiinstance_detection.py

Non-hollow tests for v10.64 multi-instance detection.

What is tested:
  1. Server A starts cleanly with no other servers present — the detection
     message must NOT appear in its stdout.
  2. Server B starts AFTER server A (--no-prompt) — the detection table
     showing server A's PID and port MUST appear in stdout.
  3. The "--no-prompt Continuing alongside" confirmation message must appear
     in server B's stdout.
  4. Both servers become HTTP-reachable after the detection phase.
  5. Data isolation: a host seeded into server A via the API must NOT
     appear in server B's /api/snapshot or browser host table.

Architecture:
  Both servers are real `legion.py --web` subprocesses started with:
    --no-prompt   skip the K/C/A interactive prompt (auto-continue)
    --no-browser  suppress Firefox auto-open
  Stdout of each subprocess is captured in a background reader thread.
  We wait for each server to become HTTP-reachable (/health endpoint)
  before asserting, so all detection output has already been written.

Run:
    sudo python3 -m pytest tests/test_multiinstance_detection.py -v
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT_A = 5073   # first instance — no other servers when it starts
PORT_B = 5074   # second instance — must detect server A

IP_SEED = '10.73.73.1'   # seeded ONLY in server A; must NOT appear in server B

_SEED_XML = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP_SEED}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22">
      <state state="open"/><service name="ssh"/></port></ports>
  </host>
</nmaprun>"""

SERVER_STARTUP_TIMEOUT = 120   # seconds — real legion.py --web takes ~15-30 s


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _http_get(port, path, timeout=5):
    """GET http://127.0.0.1:port/path → parsed JSON or None."""
    try:
        resp = urllib.request.urlopen(
            f'http://127.0.0.1:{port}{path}', timeout=timeout)
        return json.loads(resp.read())
    except Exception:
        return None


def _http_post(port, path, payload=None, timeout=15):
    """POST JSON to http://127.0.0.1:port/path → parsed JSON or None."""
    try:
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}{path}',
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST')
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}


def _port_bound(port):
    """True if something is listening on 127.0.0.1:port."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def _wait_ready(port, timeout=SERVER_STARTUP_TIMEOUT, poll=1.5):
    """Block until /health responds (server is up) or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                f'http://127.0.0.1:{port}/health', timeout=2)
            return True
        except Exception:
            time.sleep(poll)
    return False


def _start_server(port):
    """Start `legion.py --web --no-prompt --no-browser --port PORT`.

    Returns (proc, stdout_lines, lock) where stdout_lines is populated
    by a background thread and lock guards access to it.
    """
    stdout_lines = []
    lock = threading.Lock()

    proc = subprocess.Popen(
        [sys.executable, 'legion.py', '--web',
         '--no-prompt', '--no-browser', '--port', str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=PROJECT_ROOT,
    )

    def _collect_stdout(pipe, dest, lk):
        for raw in iter(pipe.readline, b''):
            with lk:
                dest.append(raw.decode(errors='replace').rstrip())

    def _collect_stderr(pipe):
        # Drain stderr to prevent the subprocess blocking on a full pipe;
        # we don't assert on stderr but keep it readable for debugging.
        for _ in iter(pipe.readline, b''):
            pass

    threading.Thread(
        target=_collect_stdout, args=(proc.stdout, stdout_lines, lock),
        daemon=True).start()
    threading.Thread(
        target=_collect_stderr, args=(proc.stderr,),
        daemon=True).start()

    return proc, stdout_lines, lock


def _stdout_snapshot(lines, lock):
    """Return a single string of everything captured so far."""
    with lock:
        return '\n'.join(lines)


# ── Module-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def server_a():
    """Start server A (no other instances); yield info dict; kill on teardown."""
    proc, lines, lock = _start_server(PORT_A)
    ready = _wait_ready(PORT_A)
    if not ready:
        proc.kill()
        proc.wait()
        out = _stdout_snapshot(lines, lock)
        pytest.fail(
            f"Server A (port {PORT_A}) did not become ready within "
            f"{SERVER_STARTUP_TIMEOUT}s.\n"
            f"--- captured stdout ---\n{out[:2000]}")
    # Extra moment so all startup prints have flushed
    time.sleep(0.5)
    yield {'proc': proc, 'port': PORT_A, 'lines': lines, 'lock': lock}
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@pytest.fixture(scope='module')
def server_b(server_a):
    """Start server B after server A is ready; it should detect server A."""
    proc, lines, lock = _start_server(PORT_B)
    ready = _wait_ready(PORT_B)
    if not ready:
        proc.kill()
        proc.wait()
        out = _stdout_snapshot(lines, lock)
        pytest.fail(
            f"Server B (port {PORT_B}) did not become ready within "
            f"{SERVER_STARTUP_TIMEOUT}s.\n"
            f"--- captured stdout ---\n{out[:2000]}")
    # Wait for all detection output to flush (detection happens before
    # app.run() so it's definitely done by now; the 0.5 s is a safety margin)
    time.sleep(0.5)
    yield {'proc': proc, 'port': PORT_B, 'lines': lines, 'lock': lock}
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@pytest.fixture(scope='module')
def drv(server_b):
    """Headless Firefox pointed at server B for browser-based isolation check."""
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(
        service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(f'http://127.0.0.1:{PORT_B}')
    time.sleep(2.0)
    yield d
    d.quit()


# ── Detection output tests ────────────────────────────────────────────────────

class TestDetectionOutput:
    """Verify what each server prints to stdout during startup."""

    def test_server_a_has_no_detection_message(self, server_a):
        """Server A starts with no other instances → detection table must NOT appear."""
        out = _stdout_snapshot(server_a['lines'], server_a['lock'])
        assert 'Other Legion web server' not in out, (
            f"Server A should not have detected any other instance.\n"
            f"--- server A stdout ---\n{out[:1200]}")

    def test_server_b_shows_detection_header(self, server_b):
        """Server B must print the detection table header."""
        out = _stdout_snapshot(server_b['lines'], server_b['lock'])
        assert 'Other Legion web server' in out, (
            f"Server B should detect server A and print the detection table.\n"
            f"Expected 'Other Legion web server' in stdout.\n"
            f"--- server B stdout ---\n{out[:1200]}")

    def test_server_b_shows_server_a_port(self, server_b):
        """Detection table row must contain server A's port number."""
        out = _stdout_snapshot(server_b['lines'], server_b['lock'])
        assert str(PORT_A) in out, (
            f"Server B's detection table should mention port {PORT_A}.\n"
            f"--- server B stdout ---\n{out[:1200]}")

    def test_server_b_shows_server_a_pid(self, server_a, server_b):
        """Detection table row must contain server A's actual OS PID."""
        pid_a = str(server_a['proc'].pid)
        out = _stdout_snapshot(server_b['lines'], server_b['lock'])
        assert pid_a in out, (
            f"Server B's detection table should show server A's PID ({pid_a}).\n"
            f"--- server B stdout ---\n{out[:1200]}")

    def test_server_b_confirms_no_prompt_continuation(self, server_b):
        """--no-prompt must trigger the 'Continuing alongside' confirmation."""
        out = _stdout_snapshot(server_b['lines'], server_b['lock'])
        # Either the --no-prompt banner or the C-choice banner
        assert ('Continuing alongside' in out or '[--no-prompt]' in out), (
            f"Server B should confirm that it is continuing alongside server A.\n"
            f"Expected 'Continuing alongside' or '[--no-prompt]' in stdout.\n"
            f"--- server B stdout ---\n{out[:1200]}")


# ── Operational tests ─────────────────────────────────────────────────────────

class TestBothServersOperational:
    """Verify both servers continue to serve HTTP after the detection phase."""

    def test_server_a_responds_to_health(self, server_a):
        """Server A /health must return HTTP 200."""
        result = _http_get(PORT_A, '/health')
        assert result is not None, (
            f"Server A on port {PORT_A} did not respond to /health after detection.")

    def test_server_b_responds_to_health(self, server_b):
        """Server B /health must return HTTP 200."""
        result = _http_get(PORT_B, '/health')
        assert result is not None, (
            f"Server B on port {PORT_B} did not respond to /health after detection.")

    def test_server_a_snapshot_returns_valid_json(self, server_a):
        """Server A /api/snapshot must return a valid snapshot dict."""
        snap = _http_get(PORT_A, '/api/snapshot')
        assert snap is not None and 'hosts' in snap, (
            f"Server A /api/snapshot did not return expected JSON.\n"
            f"Got: {snap!r}")

    def test_server_b_snapshot_returns_valid_json(self, server_b):
        """Server B /api/snapshot must return a valid snapshot dict."""
        snap = _http_get(PORT_B, '/api/snapshot')
        assert snap is not None and 'hosts' in snap, (
            f"Server B /api/snapshot did not return expected JSON.\n"
            f"Got: {snap!r}")


# ── Data isolation tests ──────────────────────────────────────────────────────

class TestDataIsolation:
    """Verify the two instances share no data — separate databases."""

    @pytest.fixture(scope='class', autouse=True)
    def seed_host_in_a(self, server_a):
        """Seed IP_SEED into server A's database exactly once per class."""
        with tempfile.NamedTemporaryFile(
                suffix='.xml', mode='w', delete=False) as f:
            f.write(_SEED_XML)
            path = f.name
        try:
            result = _http_post(PORT_A, '/api/nmap/import-xml', {'path': path})
        finally:
            os.unlink(path)
        # Allow the server to import and the snapshot poll to reflect it
        time.sleep(3.0)

        # Verify the seed landed in server A before testing isolation
        snap_a = _http_get(PORT_A, '/api/snapshot')
        hosts_a = [h.get('ip', '') for h in (snap_a or {}).get('hosts', [])]
        if IP_SEED not in hosts_a:
            pytest.fail(
                f"Seed failed: {IP_SEED} not in server A after import.\n"
                f"import result: {result}\n"
                f"hosts in A: {hosts_a}")

    def test_seeded_host_visible_in_server_a(self, server_a):
        """Confirm the seeded host is in server A's snapshot."""
        snap = _http_get(PORT_A, '/api/snapshot')
        hosts = [h.get('ip', '') for h in (snap or {}).get('hosts', [])]
        assert IP_SEED in hosts, (
            f"Seeded host {IP_SEED} not visible in server A.\n"
            f"Hosts in A: {hosts}")

    def test_seeded_host_not_in_server_b_api(self, server_b):
        """Server B's /api/snapshot must NOT contain the host seeded in A.

        Each server has its own temp SQLite DB created by
        createNewTemporaryProject().  No data can cross between them.
        """
        snap = _http_get(PORT_B, '/api/snapshot')
        hosts = [h.get('ip', '') for h in (snap or {}).get('hosts', [])]
        assert IP_SEED not in hosts, (
            f"ISOLATION FAILURE: {IP_SEED} (seeded only in server A) "
            f"appeared in server B's /api/snapshot.\n"
            f"Hosts in B: {hosts}\n"
            f"Each instance must use a separate database.")

    def test_seeded_host_not_visible_in_server_b_browser(self, server_b, drv):
        """Browser on server B must show an empty hosts table.

        This is the Selenium verification that the isolation holds end-to-end:
        the UI served by server B reflects only server B's own (empty) database,
        not server A's data.
        """
        # Navigate to server B and wait for the snapshot to render
        drv.get(f'http://127.0.0.1:{PORT_B}')
        time.sleep(2.0)

        # Wait up to 8 s for the hosts table to be present (even if empty)
        WebDriverWait(drv, 8).until(
            EC.presence_of_element_located((By.ID, 'hosts-body')))

        # Collect all host IPs shown in the #hosts-body table
        rows = drv.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-ip]')
        visible_ips = [r.get_attribute('data-host-ip') for r in rows]

        assert IP_SEED not in visible_ips, (
            f"ISOLATION FAILURE (browser): {IP_SEED} (seeded only in server A) "
            f"appeared in server B's host table in the browser.\n"
            f"Visible IPs in B: {visible_ips}")

        # Also assert server B's UI is completely empty (no hosts at all)
        assert len(visible_ips) == 0, (
            f"Server B's host table should be empty — it was never seeded.\n"
            f"Visible IPs: {visible_ips}")
