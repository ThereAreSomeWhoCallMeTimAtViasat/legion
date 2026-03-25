#!/usr/bin/env python3
"""
Shutdown safety tests — run the server in a SEPARATE SUBPROCESS.

Why subprocess and not a thread:
  Both shutdown paths (heartbeat watchdog, /api/exit) call os._exit(0).
  If the server runs in a thread inside the pytest process, os._exit(0) kills
  pytest itself.  A subprocess is the only safe way to verify that the process
  actually exits cleanly.

Test A — _kill_all_descendants():
  subprocess.Popen(cmd, shell=True) creates:
    Legion (PID A) → /bin/sh (PID B, tracked as proc._popen.pid)
                   → sleep 30 (PID C, grandchild — NOT tracked)
  The old killRunningProcesses() killed PID B; sleep (PID C) survived as an
  orphan re-parented to PID 1.  _kill_all_descendants() reads /proc to find
  every descendant of Legion and sends SIGKILL to all of them.
  This test verifies PID C is gone after /api/exit.

Test B — heartbeat watchdog:
  legion.js POSTs /api/heartbeat every 5 s.  The server-side watchdog fires
  if no heartbeat arrives for _HB_TIMEOUT seconds.  Closing the browser stops
  the JS, which stops the pings, which eventually fires the watchdog.
  Uses _HB_TIMEOUT=5 (overridden before the server starts) so the test
  completes in ~15 s instead of waiting the 20 s production default.
"""
import json
import os
import select
import socket
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

IP        = '10.99.99.1'
PORT_DESC = 5083   # test A — descendants
PORT_HB   = 5084   # test B — heartbeat

_SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22">
      <state state="open"/><service name="ssh"/></port></ports>
  </host>
</nmaprun>"""

# ── Bootstrap script run inside the child Python process ─────────────────────
# Writes "READY\n" to stdout once the server is accepting connections.
# hb_timeout is injected so test B can use a short value (5 s).
_BOOTSTRAP = r"""
import sys, os, tempfile
sys.path.insert(0, {root!r})
os.chdir({root!r})

import app.web.routes as _rt
_rt._HB_TIMEOUT = {hb_timeout}

from app.web.testhelper import create_test_app
from app.importers.nmap_import import import_nmap_xml
from werkzeug.serving import make_server

app, logic, wc = create_test_app()
app.config['TESTING'] = False

with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
    f.write({seed!r}); p = f.name
import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
os.unlink(p)

httpd = make_server('127.0.0.1', {port}, app, threaded=True)
sys.stdout.write('READY\n')
sys.stdout.flush()
httpd.serve_forever()
"""


def _start_subprocess_server(port, hb_timeout=20, startup_timeout=30):
    """Spawn a Legion Flask server in a child process.
    Blocks until the server writes 'READY' to stdout or *startup_timeout* elapses."""
    script = _BOOTSTRAP.format(
        root=PROJECT_ROOT, port=port,
        hb_timeout=hb_timeout, seed=_SEED)
    proc = subprocess.Popen(
        ['python3', '-c', script],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd=PROJECT_ROOT)
    ready, _, _ = select.select([proc.stdout], [], [], startup_timeout)
    if not ready:
        proc.kill()
        raise RuntimeError(f"Server on port {port} did not start within {startup_timeout}s")
    line = proc.stdout.readline().decode().strip()
    if line != 'READY':
        proc.kill()
        raise RuntimeError(f"Unexpected bootstrap output: {line!r}")
    return proc


def _api(port, path, payload=None):
    """POST to the subprocess server; return parsed JSON response."""
    import urllib.request
    url  = f'http://127.0.0.1:{port}{path}'
    data = json.dumps(payload or {}).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        return json.loads(urllib.request.urlopen(req, timeout=5).read())
    except Exception as e:
        return {'error': str(e)}


def _descendants(pid):
    """Return all descendant PIDs of *pid* by scanning /proc/*/stat."""
    parent_map: dict = {}
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open(f'/proc/{entry}/stat') as f:
                data = f.read()
            # comm field is "(name)" and may contain spaces — find last ')'
            comm_end = data.rfind(')')
            if comm_end < 0:
                continue
            rest  = data[comm_end + 2:].split()
            child = int(entry)
            ppid  = int(rest[1])   # rest[0]=state, rest[1]=ppid
            parent_map.setdefault(ppid, []).append(child)
        except Exception:
            pass

    result, queue, seen = [], [pid], {pid}
    while queue:
        p = queue.pop(0)
        for child in parent_map.get(p, []):
            if child not in seen:
                seen.add(child)
                result.append(child)
                queue.append(child)
    return result


def _pid_alive(pid):
    """True if the process still exists in /proc."""
    return os.path.exists(f'/proc/{pid}')


def _port_open(port):
    """True if something is listening on 127.0.0.1:port."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


# ─── Test A: grandchild processes killed on exit ──────────────────────────────

def test_all_descendants_killed_on_exit():
    """
    Verify _kill_all_descendants() kills grandchild processes.

    subprocess.Popen('sleep 30', shell=True) creates:
      Legion PID → /bin/sh PID (tracked)→ sleep PID (grandchild, NOT tracked)

    The old code: os.kill(shell_pid, SIGKILL) → sleep re-parented to PID 1, survives.
    The new code: _kill_all_descendants() scans /proc, kills every descendant.

    Steps:
      1. Start server subprocess.
      2. POST /api/processes/custom with command='sleep 30' — Legion spawns it
         via Popen(..., shell=True), giving us the shell→sleep chain.
      3. Find the 'sleep' grandchild PID in /proc among the server's descendants.
      4. POST /api/exit — triggers closeProject() → killRunningProcesses()
         → _kill_all_descendants() → SIGKILL on every descendant incl. sleep.
      5. Wait for server subprocess to exit (os._exit(0)).
      6. Assert sleep PID is gone from /proc.
    """
    server = _start_subprocess_server(PORT_DESC)
    try:
        assert _port_open(PORT_DESC), "Server did not bind to port"

        # Launch `sleep 30` through the real Legion HTTP API.
        # shell=True inside Popen means: /bin/sh (tracked) → sleep (grandchild).
        resp = _api(PORT_DESC, '/api/processes/custom', {
            'command': 'sleep 30', 'host_ip': IP, 'port': '22', 'protocol': 'tcp'})
        assert resp.get('status') == 'ok', \
            f"/api/processes/custom failed: {resp}"

        # Wait for Popen() to exec the shell and the shell to exec sleep
        time.sleep(1.5)

        # Scan /proc descendants of the server subprocess for a 'sleep' process
        all_desc = _descendants(server.pid)
        sleep_pids = []
        for pid in all_desc:
            try:
                with open(f'/proc/{pid}/comm') as f:
                    if f.read().strip() == 'sleep':
                        sleep_pids.append(pid)
            except Exception:
                pass

        assert sleep_pids, (
            f"No 'sleep' grandchild found among {len(all_desc)} descendants "
            f"of server PID {server.pid}.\n"
            f"Descendants: {all_desc[:30]}\n"
            f"The command may not have started yet — increase the sleep after runCommand.")

        print(f"\nFound sleep grandchild PID(s): {sleep_pids}")
        print(f"Total server descendants before exit: {len(all_desc)}")

        # Trigger clean exit — runs _kill_all_descendants() before os._exit(0)
        _api(PORT_DESC, '/api/exit', {})

        # Server subprocess should call os._exit(0) within 0.5 s of /api/exit
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
            pytest.fail("Server subprocess did not exit within 8s after /api/exit")

        time.sleep(0.3)  # let the OS reap orphaned children

        for pid in sleep_pids:
            assert not _pid_alive(pid), (
                f"DESCENDANTS KILL FAILED: sleep PID {pid} is still alive in "
                f"/proc after Legion exited.\n"
                f"  _kill_all_descendants() did not reach the grandchild process.\n"
                f"  The old code only killed the shell (proc._popen.pid); sleep "
                f"survived re-parented to PID 1.")

        print(f"PASS: sleep grandchild(s) {sleep_pids} gone after Legion exit ✓")

    finally:
        if server.poll() is None:
            server.kill()


# ─── Test B: heartbeat watchdog shuts server when browser closes ───────────────

def test_heartbeat_watchdog_exits_on_browser_close():
    """
    Verify the heartbeat watchdog shuts the server down when the browser closes.

    legion.js sends POST /api/heartbeat immediately on page load and every 5 s.
    The server-side watchdog fires when no heartbeat arrives for _HB_TIMEOUT s.
    Quitting the browser stops the JS, which stops the pings, which triggers
    the watchdog → killRunningProcesses() → os._exit(0).

    Uses _HB_TIMEOUT=5 (overridden before the server starts) so the test
    finishes in ~15 s instead of the 20 s production default.

    Steps:
      1. Start server subprocess with HB_TIMEOUT=5.
      2. Open headless Firefox — legion.js loads and starts heartbeats.
      3. Wait 2 s: confirm heartbeats are flowing (server is alive).
      4. driver.quit() — closes Firefox, stops heartbeats.
      5. Wait up to 15 s for the watchdog to fire and the subprocess to exit.
      6. Assert the subprocess has exited and the port is no longer bound.
    """
    HB_TIMEOUT = 5   # short for testing; production default is 20 s
    # Maximum time to wait after browser closes for server to exit:
    #   watchdog polls every 5 s + HB_TIMEOUT(5) + 3 s margin = 13 s
    MAX_WAIT = HB_TIMEOUT + 5 + 3

    server = _start_subprocess_server(PORT_HB, hb_timeout=HB_TIMEOUT)
    driver = None
    try:
        assert _port_open(PORT_HB), "Server did not bind to port"

        # Open real Firefox — this loads legion.js and triggers the first heartbeat
        from selenium import webdriver
        from selenium.webdriver.firefox.service import Service
        os.environ.pop('XAUTHORITY', None)
        os.environ.pop('DISPLAY', None)
        opts = webdriver.FirefoxOptions()
        opts.add_argument('--headless')
        driver = webdriver.Firefox(
            service=Service('/usr/bin/geckodriver'), options=opts)
        driver.set_window_size(1600, 900)
        driver.get(f'http://127.0.0.1:{PORT_HB}')
        time.sleep(2)   # let the page load and first heartbeat reach the server

        # Confirm server is still alive — heartbeats are keeping it up
        assert _port_open(PORT_HB), "Server died before browser was closed"
        assert server.poll() is None, "Server subprocess exited prematurely"

        # Confirm the watchdog thread was started by checking it's known to the server
        hb_state = _api(PORT_HB, '/api/heartbeat', {})
        assert hb_state.get('ok'), f"Heartbeat endpoint failed: {hb_state}"
        print(f"\nHeartbeats flowing — server alive on port {PORT_HB} ✓")

        # ── Close the browser — JS heartbeats stop ────────────────────────────
        driver.quit()
        driver = None
        t_close = time.time()

        # ── Wait for watchdog to fire ─────────────────────────────────────────
        # Watchdog sleeps 5 s between checks; first check after browser close
        # may find gap < HB_TIMEOUT; second check (at most HB_TIMEOUT + 5 s
        # after close) will find gap > HB_TIMEOUT and call os._exit(0).
        deadline = t_close + MAX_WAIT
        while time.time() < deadline:
            if server.poll() is not None:
                break
            time.sleep(0.5)

        elapsed = time.time() - t_close

        assert server.poll() is not None, (
            f"HEARTBEAT WATCHDOG FAILED: server subprocess still running "
            f"{elapsed:.1f}s after browser closed "
            f"(HB_TIMEOUT={HB_TIMEOUT}s, MAX_WAIT={MAX_WAIT}s).\n"
            f"  The watchdog did not fire, or os._exit(0) was not called, "
            f"or the heartbeat endpoint is not updating _hb_last.")

        assert not _port_open(PORT_HB), \
            f"Port {PORT_HB} still bound after server subprocess exited"

        print(f"PASS: server exited {elapsed:.1f}s after browser closed ✓")
        print(f"  (HB_TIMEOUT={HB_TIMEOUT}s, max expected={MAX_WAIT}s)")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        if server.poll() is None:
            server.kill()
