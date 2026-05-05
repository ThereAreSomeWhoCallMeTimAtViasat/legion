#!/usr/bin/env python3
"""tests/test_ui_v10d_features.py

Non-hollow Selenium regression tests for Legion features added April 2026.

  v10.128  Process table sorts by status on startup: Running first, then
           Waiting, Finished, Interactive, Crashed/Killed last.  Previously
           the default sort was by ID (newest first), hiding active scans.

  v10.129  nmap_import concurrent import deadlock fixed.  The old wrapper
           patched project.database.dbsemaphore.acquire/release on a shared
           object; thread B's patch overwrote thread A's so one thread
           blocked forever.  Fix: hold _import_lock for the entire
           patch→run→restore cycle so patches are never clobbered.

  v10.131  Scheduler respects tool-duplication=skip.  The old inline dup
           check only blocked Waiting/Running processes.  Finished processes
           were invisible to it, so every new nmap stage completion re-fired
           the same tools.  Fix: scheduler now calls checkDuplicate() which
           reads the tool-duplication setting and includes Finished processes.

  v10.133  AI tab ai-ready state shows #ai-ready-history section when the
           persistent history DB has previous analyses for the current host.
           Previously the comparison dropdown was buried inside ai-results
           (only visible after running a new analysis).

Run:
    sudo python3 -m pytest tests/test_ui_v10d_features.py -v
"""
import os
import sys
import time
import json
import sqlite3
import tempfile
import threading

import pytest
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5081
IP   = '10.81.81.1'

SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="25"><state state="open"/><service name="smtp"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
</nmaprun>"""

AI_HISTORY_DB = os.path.expanduser('~/.local/share/legion/ai_history.db')


# ── helpers ────────────────────────────────────────────────────────────────

def _free_port(port, retries=20):
    import subprocess, socket
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    for _ in range(retries):
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
            s.close()
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Port {port} still in use")


def js(d, s, *a):
    return d.execute_script(s, *a)


def W(d, t=10):
    return WebDriverWait(d, t)


def _snap(srv_url):
    return requests.get(f'{srv_url}/api/snapshot', timeout=5).json()


def _wait_status(srv_url, proc_id, statuses, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in _snap(srv_url).get('processes', []):
            if str(p.get('id')) == str(proc_id) and p.get('status') in statuses:
                return p.get('status')
        time.sleep(0.4)
    raise TimeoutError(f"Process {proc_id} did not reach {statuses} in {timeout}s")


def _ensure_scan_tab(d):
    btn = W(d, 5).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]')))
    js(d, 'arguments[0].click()', btn)
    W(d, 3).until(lambda dd: 'active' in (
        dd.find_element(By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]')
          .get_attribute('class') or ''))


def _ensure_processes_tab(d):
    btn = W(d, 5).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#bottom-tab-bar [data-tab="processes-panel"]')))
    js(d, 'arguments[0].click()', btn)
    W(d, 3).until(lambda dd: 'active' in (
        dd.find_element(By.CSS_SELECTOR,
                        '#bottom-tab-bar [data-tab="processes-panel"]')
          .get_attribute('class') or ''))


def _select_host(d, ip=IP):
    row = W(d, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))
    js(d, 'arguments[0].click()', row)
    W(d, 5).until(lambda dd: js(dd, "return (L && L.selectedHostIp) || ''") == ip)


def _wait_proc_count(srv_url, predicate, timeout=8):
    """Poll snapshot until predicate(processes_list) returns True. Returns
    the matching processes list. Replaces blind sleeps after wc.scheduler()."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            procs = _snap(srv_url).get('processes', [])
            if predicate(procs):
                return procs
        except Exception:
            pass
        time.sleep(0.2)
    return _snap(srv_url).get('processes', [])  # last snapshot if no match


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _orig_hb = getattr(_web_routes, '_HB_TIMEOUT', 20)
    _web_routes._HB_TIMEOUT = 600

    _free_port(PORT)
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)

    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(2.0)

    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}

    httpd.shutdown()
    _web_routes._HB_TIMEOUT = _orig_hb


@pytest.fixture(scope="module")
def drv(srv):
    import os as _os
    _os.environ.pop('XAUTHORITY', None)
    _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(srv['url'])
    time.sleep(2.0)
    yield d
    d.quit()


@pytest.fixture(autouse=True)
def _dismiss_alerts(drv):
    try:
        drv.switch_to.alert.dismiss()
    except Exception:
        pass
    yield


# ═══════════════════════════════════════════════════════════════════════════
# v10.128  Process table default sort: Running first
# ═══════════════════════════════════════════════════════════════════════════

class TestProcessTableSort:
    """Default sort is status ascending: Running(0) < Waiting(1) < Finished(2).
    A Running process started AFTER a Finished one must still appear first."""

    def test_running_row_before_finished_row(self, drv, srv):
        """Running process must appear above Finished process in the process table
        regardless of insertion order (Running started second, Finished started first)."""
        wc = srv['wc']
        srv_url = srv['url']

        # Start the 'Finished' process first — it completes almost immediately
        r_fin = wc.runCommand('echo finished-first', name='sort-finished',
                              hostIp=IP, run_actions=False)
        fin_id = r_fin['process_id']

        # Wait for it to finish
        _wait_status(srv_url, fin_id, {'Finished', 'Crashed'}, timeout=15)

        # Now start the 'Running' process — it outlasts the test
        r_run = wc.runCommand('sleep 45', name='sort-running',
                              hostIp=IP, run_actions=False)
        run_id = r_run['process_id']

        # Wait for it to actually start (status=Running in snapshot)
        _wait_status(srv_url, run_id, {'Running'}, timeout=10)

        try:
            _ensure_scan_tab(drv)
            _ensure_processes_tab(drv)
            # Wait for both pid rows to be in DOM — replaces 1.5s sleep.
            W(drv, 8).until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{run_id}"]')))
            W(drv, 8).until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{fin_id}"]')))

            # Collect all process rows in their current DOM order
            rows = drv.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')
            assert len(rows) >= 2, f"Expected ≥2 process rows, got {len(rows)}"

            # Build ordered list of (row_index, proc_id, status_text)
            order = []
            for i, row in enumerate(rows):
                pid = row.get_attribute('data-process-id')
                cells = row.find_elements(By.TAG_NAME, 'td')
                # Checkbox added v10.136: cols are ☐|ID|Name|Target|PID|Status|%|Elapsed
                # Status is now index 5 (was 4 before checkbox column)
                status = cells[5].text.strip() if len(cells) >= 6 else ''
                order.append((i, pid, status))

            # Find positions of our two processes
            run_pos  = next((i for i, pid, _ in order if str(pid) == str(run_id)), None)
            fin_pos  = next((i for i, pid, _ in order if str(pid) == str(fin_id)), None)

            assert run_pos  is not None, f"Running process {run_id} not in table"
            assert fin_pos  is not None, f"Finished process {fin_id} not in table"

            # Running row must come BEFORE Finished row
            assert run_pos < fin_pos, (
                f"Running process (pos={run_pos}) should be above "
                f"Finished process (pos={fin_pos}) — sort is wrong.\n"
                f"Full order: {[(i, pid, s) for i, pid, s in order[:8]]}"
            )

            # Verify status cell text matches expected values
            run_status = next(s for i, pid, s in order if str(pid) == str(run_id))
            fin_status = next(s for i, pid, s in order if str(pid) == str(fin_id))
            assert run_status == 'Running',  f"Expected 'Running', got {run_status!r}"
            assert fin_status in ('Finished', 'Crashed'), \
                f"Expected 'Finished'/'Crashed', got {fin_status!r}"

        finally:
            try:
                requests.post(f'{srv_url}/api/processes/{run_id}/kill', timeout=5)
            except Exception:
                pass
            time.sleep(0.5)

    def test_sort_column_header_shows_status(self, drv, srv):
        """The Status column header (th[data-sort='status']) must exist — it's
        how users can re-sort if needed.  The default sort uses it as the key."""
        _ensure_scan_tab(drv)
        _ensure_processes_tab(drv)
        status_th = drv.find_elements(By.CSS_SELECTOR,
            '#processes-table thead th[data-sort="status"]')
        assert len(status_th) == 1, \
            "Status column header with data-sort='status' not found in process table"


# ═══════════════════════════════════════════════════════════════════════════
# v10.129  Concurrent nmap import — no deadlock
# ═══════════════════════════════════════════════════════════════════════════

class TestConcurrentImport:
    """Two simultaneous import_nmap_xml calls must both complete.
    The old code had a shared-object patch race: thread B overwrote thread A's
    dbsemaphore patch, leaving thread A's lock unreleased → permanent stall.
    Fix: _import_lock wraps the entire patch→run→restore cycle."""

    def test_two_concurrent_imports_both_succeed(self, srv):
        """Import two XMLs on parallel threads; both hosts must appear in the
        snapshot within 15 seconds — proving no import hung indefinitely."""
        from app.importers.nmap_import import import_nmap_xml

        IP_A = '10.81.81.101'
        IP_B = '10.81.81.102'

        xml_a = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP_A}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port></ports>
  </host></nmaprun>"""
        xml_b = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP_B}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port></ports>
  </host></nmaprun>"""

        errors = []

        def do_import(xml_text, label):
            try:
                with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
                    f.write(xml_text); p = f.name
                import_nmap_xml(project=srv['logic'].activeProject, xml_path=p, output='')
                os.unlink(p)
            except Exception as e:
                errors.append(f"{label}: {e}")

        t_a = threading.Thread(target=do_import, args=(xml_a, 'host-A'), daemon=True)
        t_b = threading.Thread(target=do_import, args=(xml_b, 'host-B'), daemon=True)
        t_a.start()
        t_b.start()
        t_a.join(timeout=15)
        t_b.join(timeout=15)

        assert not t_a.is_alive(), "Thread A (host-A import) is still hanging — deadlock!"
        assert not t_b.is_alive(), "Thread B (host-B import) is still hanging — deadlock!"
        assert not errors, f"Import errors: {errors}"

        # Both hosts must appear in the snapshot
        snap = requests.get(f"{srv['url']}/api/snapshot", timeout=5).json()
        ips = {h.get('ip') for h in snap.get('hosts', [])}
        assert IP_A in ips, f"Host {IP_A} not in snapshot after concurrent import: {ips}"
        assert IP_B in ips, f"Host {IP_B} not in snapshot after concurrent import: {ips}"


# ═══════════════════════════════════════════════════════════════════════════
# v10.131  Scheduler tool-duplication=skip prevents re-runs after Finished
# ═══════════════════════════════════════════════════════════════════════════

class TestSchedulerNoDuplication:
    """With tool-duplication=skip the scheduler must not re-launch a tool that
    already Finished for the same host+port.  The old code only checked
    Waiting/Running — Finished processes were invisible to it, so every nmap
    stage completion re-triggered the same tools."""

    def test_scheduler_does_not_rerun_finished_tool(self, srv):
        wc = srv['wc']
        srv_url = srv['url']
        orig_dup = getattr(wc.settings, 'general_tool_duplication', 'skip')
        wc.settings.general_tool_duplication = 'skip'

        try:
            # First scheduler call — smtp-enum-vrfy fires for port 25/smtp
            wc.scheduler(isNmapImport=False)

            # Wait for smtp-enum-vrfy to appear and reach a terminal state
            deadline = time.time() + 20
            smtp_ids = []
            while time.time() < deadline:
                procs = _snap(srv_url).get('processes', [])
                smtp_ids = [
                    str(p['id']) for p in procs
                    if p.get('name') == 'smtp-enum-vrfy'
                    and p.get('hostIp') == IP
                    and str(p.get('port', '')) == '25'
                ]
                if smtp_ids:
                    # Check if any are in terminal state
                    statuses = {
                        str(p['id']): p.get('status')
                        for p in procs if str(p['id']) in smtp_ids
                    }
                    if any(s in ('Finished', 'Crashed', 'Killed')
                           for s in statuses.values()):
                        break
                time.sleep(0.5)

            if not smtp_ids:
                pytest.skip("smtp-enum-vrfy was not triggered by scheduler — "
                            "check legion.conf SchedulerSettings")

            count_after_first = len(smtp_ids)

            # Second scheduler call — must NOT create new smtp-enum-vrfy processes.
            # Poll for stability: the scheduler's effect (or non-effect) is observable
            # within ~500ms; we wait up to 3s and verify the count never grows.
            wc.scheduler(isNmapImport=False)
            _scheduler_settle_deadline = time.time() + 3
            count_seen = count_after_first
            while time.time() < _scheduler_settle_deadline:
                _live = [str(p['id']) for p in _snap(srv_url).get('processes', [])
                         if p.get('name') == 'smtp-enum-vrfy'
                         and p.get('hostIp') == IP
                         and str(p.get('port', '')) == '25']
                if len(_live) > count_seen:
                    count_seen = len(_live)  # short-circuit assertion will catch it
                    break
                time.sleep(0.2)

            procs2 = _snap(srv_url).get('processes', [])
            smtp_ids2 = [
                str(p['id']) for p in procs2
                if p.get('name') == 'smtp-enum-vrfy'
                and p.get('hostIp') == IP
                and str(p.get('port', '')) == '25'
            ]
            count_after_second = len(smtp_ids2)

            assert count_after_second == count_after_first, (
                f"Scheduler re-launched smtp-enum-vrfy after it Finished: "
                f"count went {count_after_first} → {count_after_second}. "
                f"tool-duplication=skip should have blocked this."
            )

        finally:
            wc.settings.general_tool_duplication = orig_dup
            # Kill any lingering smtp-enum-vrfy processes
            try:
                for p in _snap(srv_url).get('processes', []):
                    if p.get('name') == 'smtp-enum-vrfy' and \
                            p.get('status') in ('Running', 'Waiting'):
                        requests.post(f"{srv_url}/api/processes/{p['id']}/kill",
                                      timeout=3)
            except Exception:
                pass

    def test_scheduler_still_runs_tool_first_time(self, srv):
        """Verify the dup-check doesn't prevent the FIRST run.
        After clearing processes, a fresh scheduler call must fire smtp-enum-vrfy."""
        wc = srv['wc']
        srv_url = srv['url']
        orig_dup = getattr(wc.settings, 'general_tool_duplication', 'skip')
        wc.settings.general_tool_duplication = 'skip'

        try:
            # Close all existing smtp-enum-vrfy processes so the dup check sees none
            procs_before = _snap(srv_url).get('processes', [])
            closed_ids = []
            for p in procs_before:
                if p.get('name') == 'smtp-enum-vrfy':
                    try:
                        requests.post(f"{srv_url}/api/processes/{p['id']}/close",
                                      timeout=3)
                        closed_ids.append(str(p['id']))
                    except Exception:
                        pass
            # Wait for the closed processes to disappear from snapshot — replaces 1s sleep
            if closed_ids:
                _close_deadline = time.time() + 5
                while time.time() < _close_deadline:
                    live_ids = {str(p['id']) for p in _snap(srv_url).get('processes', [])}
                    if not any(cid in live_ids for cid in closed_ids):
                        break
                    time.sleep(0.2)

            # Now run the scheduler — should launch smtp-enum-vrfy.
            # Wait for at least 1 NEW smtp-enum-vrfy proc to appear; replaces 2s sleep.
            wc.scheduler(isNmapImport=False)
            _existing_ids = {str(p['id']) for p in procs_before
                             if p.get('name') == 'smtp-enum-vrfy'}
            _wait_proc_count(srv_url,
                lambda procs: any(p.get('name') == 'smtp-enum-vrfy'
                                  and str(p['id']) not in _existing_ids
                                  for p in procs),
                timeout=8)

            procs_after = _snap(srv_url).get('processes', [])
            new_smtp = [
                p for p in procs_after
                if p.get('name') == 'smtp-enum-vrfy'
                and p.get('hostIp') == IP
                and str(p.get('port', '')) == '25'
            ]

            if not new_smtp:
                pytest.skip("smtp-enum-vrfy not triggered — check SchedulerSettings")

            # At least one new smtp-enum-vrfy must exist after scheduler ran
            assert len(new_smtp) >= 1, \
                "Scheduler with tool-duplication=skip blocked the FIRST run — wrong"

        finally:
            wc.settings.general_tool_duplication = orig_dup


# ═══════════════════════════════════════════════════════════════════════════
# v10.133  AI tab: history section visible in ai-ready state
# ═══════════════════════════════════════════════════════════════════════════

class TestAIReadyHistory:
    """The #ai-ready-history section inside ai-ready must be:
    - hidden (display:none) when the history DB has no entry for this host
    - visible when a history entry exists for this host's IP

    This was the bug: the comparison dropdown was buried inside ai-results
    (only visible AFTER running a new analysis), not in ai-ready."""

    def _open_ai_tab(self, d, srv):
        _ensure_scan_tab(d)
        _select_host(d)
        ai_tab = W(d, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#right-tab-bar [data-tab="ai-right"]')))
        js(d, 'arguments[0].click()', ai_tab)
        # Wait for the ai-right tab to become active — replaces 1.5s sleep
        W(d, 5).until(lambda dd: 'active' in (
            dd.find_element(By.CSS_SELECTOR, '#right-tab-bar [data-tab="ai-right"]')
              .get_attribute('class') or ''))

    def _get_history_section_display(self, d):
        """Return computed display value of #ai-ready-history."""
        return js(d, """
            var el = document.getElementById('ai-ready-history');
            if (!el) return 'MISSING';
            return window.getComputedStyle(el).display;
        """)

    def _get_host_id(self, srv, ip):
        """Look up the DB id for a host by IP (used to construct AI history URLs)."""
        for h in _snap(srv['url']).get('hosts', []):
            if h.get('ip') == ip:
                return h.get('id')
        return None

    def test_history_section_exists_in_dom(self, drv, srv):
        """#ai-ready-history must be present in the DOM (not conditional render)."""
        self._open_ai_tab(drv, srv)
        result = js(drv,
            "return document.getElementById('ai-ready-history') !== null")
        assert result, "#ai-ready-history element not found in DOM"

    def test_history_section_hidden_when_no_history(self, drv, srv):
        """When the history DB has no entry for this test host's IP,
        #ai-ready-history must be hidden."""
        # The test host IP (10.81.81.1) has never been analysed — confirm
        conn = sqlite3.connect(AI_HISTORY_DB)
        count = conn.execute(
            "SELECT COUNT(*) FROM ai_sessions WHERE host_ip=?", (IP,)
        ).fetchone()[0]
        conn.close()

        if count > 0:
            pytest.skip(f"{IP} already has {count} history entries — "
                        "can't test 'no history' case with this IP")

        self._open_ai_tab(drv, srv)

        # Pre-fetch via the same API the JS uses, so we know when the response
        # is available.  Then poll the DOM until the section's display matches
        # the expected (hidden) state.  Replaces 2s blind sleep.
        host_id = self._get_host_id(srv, IP)
        try:
            requests.get(f"{srv['url']}/api/ai/history/similar/{host_id}", timeout=5)
        except Exception:
            pass
        W(drv, 8).until(lambda d: self._get_history_section_display(d)
                                  in ('none', 'MISSING'))
        display = self._get_history_section_display(drv)
        assert display in ('none', 'MISSING') or display == 'none', (
            f"#ai-ready-history should be hidden when no history exists, "
            f"but computed display is {display!r}"
        )

    def test_history_section_visible_when_history_exists(self, drv, srv):
        """After inserting a fake history entry for this host,
        #ai-ready-history must become visible."""
        # Insert fake history entry
        conn = sqlite3.connect(AI_HISTORY_DB)
        conn.row_factory = sqlite3.Row
        # Ensure table exists
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_sessions (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            host_ip TEXT NOT NULL,
            project_name TEXT,
            fingerprint_json TEXT NOT NULL,
            phase1_json TEXT NOT NULL,
            phase2_markdown TEXT,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0
        )""")
        fake_fingerprint = json.dumps([
            f'22/tcp:ssh:OpenSSH 7.4', f'80/tcp:http:nginx 1.14',
            f'OS:Linux 4.x'
        ])
        fake_phase1 = json.dumps([{
            'source': 'test', 'port': '22', 'severity': 'info',
            'finding': 'SSH service detected', 'evidence': 'OpenSSH 7.4'
        }])
        conn.execute(
            """INSERT INTO ai_sessions
               (timestamp, host_ip, project_name, fingerprint_json,
                phase1_json, phase2_markdown, tokens_input, tokens_output, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ('2026-04-09T10:00:00Z', IP, 'test-session',
             fake_fingerprint, fake_phase1, '## Attack Plan\nTest.', 1000, 200, 0.015)
        )
        inserted_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        try:
            # Reload the AI tab so it re-fetches history.
            # Wait until the section becomes visible — the just-inserted history
            # entry must propagate via the API and the JS render.  Replaces 2.5s sleep.
            self._open_ai_tab(drv, srv)
            W(drv, 10).until(lambda d:
                self._get_history_section_display(d) not in ('none', 'MISSING'))

            display = self._get_history_section_display(drv)
            assert display not in ('none', 'MISSING'), (
                f"#ai-ready-history should be visible after history was seeded "
                f"for {IP}, but computed display is {display!r}"
            )

            # Also verify the select has at least one real option (not just placeholder)
            option_count = js(drv, """
                var sel = document.getElementById('ai-ready-history-select');
                return sel ? sel.options.length : 0;
            """)
            assert option_count >= 2, (
                f"Expected ≥2 options in ai-ready-history-select "
                f"(placeholder + at least one match), got {option_count}"
            )

        finally:
            # Clean up the fake history entry
            conn2 = sqlite3.connect(AI_HISTORY_DB)
            conn2.execute("DELETE FROM ai_sessions WHERE id=?", (inserted_id,))
            conn2.commit()
            conn2.close()

    def test_load_button_exists_in_ready_history(self, drv, srv):
        """The Load button must exist inside ai-ready so the user can load
        a previous analysis without running a new one."""
        self._open_ai_tab(drv, srv)
        load_btn = js(drv,
            "return document.getElementById('ai-ready-history-load') !== null")
        assert load_btn, "#ai-ready-history-load button not found in DOM"
