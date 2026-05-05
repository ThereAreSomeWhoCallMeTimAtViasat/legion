#!/usr/bin/env python3
"""tests/test_ui_v10b_features.py

Non-hollow Selenium regression tests for v10.75–v10.83 features:

  v10.75  Context menu scrollable — showContextMenu() gets max-height + overflow-y:auto
  v10.77  Waiting filter label (not "Queued")
  v10.79  Scan notes written to host — all stages appear for known host
  v10.81  Process timeout watchdog — non-nmap killed after general_process_timeout seconds
  v10.83  Scheduler no impacket credential tools

Run:
    sudo python3 -m pytest tests/test_ui_v10b_features.py -v
"""
import os
import sys
import time
import threading
import tempfile

import pytest
import requests as _requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5078
IP   = '10.77.77.1'

SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
      <port protocol="tcp" portid="445"><state state="open"/><service name="microsoft-ds"/></port>
      <port protocol="tcp" portid="135"><state state="open"/><service name="msrpc"/></port>
    </ports>
  </host>
</nmaprun>"""


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    raise RuntimeError(f"Port {port} still in use after {retries} attempts")


def js(d, s, *a):
    return d.execute_script(s, *a)


def W(d, t=12):
    return WebDriverWait(d, t)


def _wait_proc_done_api(srv_url, proc_id, timeout=30):
    """Poll /api/snapshot until proc_id reaches a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = _requests.get(f"{srv_url}/api/snapshot", timeout=5).json()
            for p in data.get('processes', []):
                if str(p.get('id', '')) == str(proc_id):
                    if p.get('status', '') in ('Finished', 'Killed', 'Crashed'):
                        return
        except Exception:
            pass
        time.sleep(0.5)


def _wait_killed(srv_url, proc_id, timeout=15):
    """Poll /api/snapshot until proc_id reaches Killed status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = _requests.get(f"{srv_url}/api/snapshot", timeout=5).json()
            for p in data.get('processes', []):
                if str(p.get('id', '')) == str(proc_id):
                    if p.get('status', '') == 'Killed':
                        return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def ctx_menu_click(d, label):
    menu = W(d, 3).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))
    for btn in menu.find_elements(By.TAG_NAME, 'button'):
        if label.lower() in btn.text.lower():
            btn.click()
            return
    raise AssertionError(
        f"'{label}' not in menu: {[b.text for b in menu.find_elements(By.TAG_NAME, 'button')]}")


def _select_host(d, ip=IP):
    row = W(d, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))
    js(d, 'arguments[0].click()', row)
    time.sleep(1.0)


def _ensure_scan_processes(d):
    scan_btn = W(d, 5).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]')))
    js(d, 'arguments[0].click()', scan_btn)
    proc_btn = W(d, 5).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#bottom-tab-bar [data-tab="processes-panel"]')))
    js(d, 'arguments[0].click()', proc_btn)
    time.sleep(0.3)


# ── Module fixtures ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _web_routes._HB_TIMEOUT = 600
    _free_port(PORT)
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server
    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED)
        p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)
    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(2.0)
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}
    httpd.shutdown()
    _web_routes._HB_TIMEOUT = 20


@pytest.fixture(scope="module")
def drv(srv):
    _os = __import__('os')
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
    """Dismiss any unexpected JS alerts after each test."""
    yield
    try:
        drv.switch_to.alert.dismiss()
    except Exception:
        pass


# ── Feature 1: TestContextMenuScrollable (v10.75) ────────────────────────────

class TestContextMenuScrollable:
    """Context menu gets max-height + overflow-y:auto so long menus don't clip."""

    def _open_port_ctx_menu(self, d):
        """Select host, go to Scan tab, click Services tab, right-click a port row."""
        _select_host(d)
        scan_btn = W(d, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]')))
        js(d, 'arguments[0].click()', scan_btn)
        time.sleep(0.5)
        # Click Services right-panel tab
        svc_tab = W(d, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '[data-tab="services-right"]')))
        js(d, 'arguments[0].click()', svc_tab)
        time.sleep(0.5)
        # Dismiss any open context menu first
        js(d, 'document.body.click()')
        time.sleep(0.3)
        # Wait for port rows in host-detail-ports tbody
        port_row = W(d, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#host-detail-ports tr')))
        # Scroll into view before right-clicking
        js(d, 'arguments[0].scrollIntoView({block:"center"})', port_row)
        time.sleep(0.3)
        # Right-click to open context menu
        ActionChains(d).context_click(port_row).perform()
        time.sleep(0.5)

    def test_menu_has_max_height_style(self, drv, srv):
        """showContextMenu() sets max-height on outer menu; overflow-y:auto on inner list."""
        self._open_port_ctx_menu(drv)
        W(drv, 5).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))
        styles = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return [null, null, null];
            // Outer menu: max-height capping the whole menu
            // Inner scrollable list: second child (first=topArrow, second=list, third=botArrow)
            var list = m.children[1];
            return [m.style.maxHeight, list ? list.style.overflowY : '', m.style.display];
        """)
        assert styles[0] is not None, "ctx-menu not found"
        assert styles[0] != '', f"max-height not set on ctx-menu; styles={styles}"
        assert ('calc(' in styles[0] or 'vh' in styles[0] or 'px' in styles[0]), \
            f"max-height unexpected value: {styles[0]!r}"
        # overflow-y:auto is on the inner scrollable list div, not the outer wrapper
        assert styles[1] == 'auto', f"overflow-y expected 'auto' on inner list, got: {styles[1]!r}"
        js(drv, 'document.body.click()')
        time.sleep(0.3)

    def test_menu_does_not_overflow_with_many_items(self, drv, srv):
        """Context menu bounding rect bottom <= window.innerHeight."""
        self._open_port_ctx_menu(drv)
        W(drv, 5).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))
        result = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return {bottom: -1, vh: window.innerHeight};
            var r = m.getBoundingClientRect();
            return {bottom: r.bottom, vh: window.innerHeight};
        """)
        assert result['bottom'] != -1, "ctx-menu not found"
        assert result['bottom'] <= result['vh'] + 1, \
            f"Context menu overflows viewport: bottom={result['bottom']} vh={result['vh']}"
        js(drv, 'document.body.click()')
        time.sleep(0.3)


# ── Feature 2: TestWaitingFilterLabel (v10.77) ───────────────────────────────

class TestWaitingFilterLabel:
    """Status filter dropdown shows 'Waiting' not 'Queued'."""

    def test_filter_option_says_waiting_not_queued(self, drv, srv):
        """Option with value='Waiting' has text 'Waiting'; no option says 'Queued'."""
        _ensure_scan_processes(drv)
        sel = W(drv, 8).until(EC.presence_of_element_located(
            (By.ID, 'process-status-filter')))
        options = sel.find_elements(By.TAG_NAME, 'option')
        texts = [o.text.strip() for o in options]
        values = [o.get_attribute('value') for o in options]
        assert 'Queued' not in texts, \
            f"Found 'Queued' option in filter (should be removed): {texts}"
        assert 'Waiting' in texts, \
            f"'Waiting' not found in filter options: {texts}"
        waiting_opt = next((o for o in options if o.get_attribute('value') == 'Waiting'), None)
        assert waiting_opt is not None, \
            f"No option with value='Waiting' found; values: {values}"
        assert waiting_opt.text.strip() == 'Waiting', \
            f"Option value='Waiting' has text {waiting_opt.text.strip()!r}, expected 'Waiting'"

    def test_filter_waiting_filters_correctly(self, drv, srv):
        """Setting filter to Running shows the running sleep; Finished hides it."""
        wc = srv['wc']
        srv_url = srv['url']
        proc_id = None
        try:
            result = wc.runCommand('sleep 30', name='wait-filter-test', hostIp=IP)
            proc_id = result['process_id'] if isinstance(result, dict) else result
            time.sleep(1.5)

            _ensure_scan_processes(drv)
            W(drv, 5).until(EC.presence_of_element_located(
                (By.ID, 'process-status-filter')))

            # Set filter to Running — our process row must be visible
            js(drv, """
                var s = document.getElementById('process-status-filter');
                s.value = 'Running';
                s.dispatchEvent(new Event('change'));
            """)
            time.sleep(1.5)
            # Re-find after snapshot re-render (stale element rule)
            rows = drv.find_elements(By.CSS_SELECTOR,
                f'#processes-body tr[data-process-id="{proc_id}"]')
            assert len(rows) == 1, \
                f"Running filter should show proc {proc_id} but row not found"

            # Set filter to Finished — running sleep must disappear
            js(drv, """
                var s = document.getElementById('process-status-filter');
                s.value = 'Finished';
                s.dispatchEvent(new Event('change'));
            """)
            time.sleep(1.5)
            # Re-find after snapshot re-render (stale element rule)
            rows = drv.find_elements(By.CSS_SELECTOR,
                f'#processes-body tr[data-process-id="{proc_id}"]')
            assert len(rows) == 0, \
                f"Finished filter should hide proc {proc_id} but row still present"
        finally:
            js(drv, """
                var s = document.getElementById('process-status-filter');
                s.value = '';
                s.dispatchEvent(new Event('change'));
            """)
            # Kill just the sleep process via API — avoids calling killRunningProcesses()
            # which calls _kill_all_descendants() and would kill geckodriver too
            if proc_id:
                try:
                    import requests as _r
                    _r.post(f"{srv_url}/api/processes/{proc_id}/kill", timeout=5)
                except Exception:
                    pass
            time.sleep(0.5)


# ── Feature 3: TestNotesAllStages (v10.79) ───────────────────────────────────

class TestNotesAllStages:
    """runStagedNmap() writes all stage commands to host notes for known hosts."""

    _host_id = None

    @pytest.fixture(scope="class", autouse=True)
    def _run_staged_nmap(self, request, srv):
        """Run runStagedNmap once — note write is synchronous; kill launched nmap processes
        immediately afterward so they don't saturate the queue for subsequent test classes."""
        import signal as _signal
        from controller.web_controller import _kill_subtree
        wc = srv['wc']
        repo = wc.logic.activeProject.repositoryContainer
        host_obj = repo.hostRepository.getHostByIP(IP)
        assert host_obj is not None, f"Host {IP} not found in DB after seeding"
        type(self)._host_id = host_obj.id

        # runStagedNmap writes notes synchronously for known hosts BEFORE launching nmap.
        wc.runStagedNmap(IP, discovery=False)
        time.sleep(1.0)   # let _append_to_host_notes commit to DB

        # Kill launched processes: kill grandchildren first (_kill_subtree) so the pipe
        # write end closes and readline() in _capture_output unblocks immediately.
        # Then kill the shell (proc._popen.kill()).  This drains fastProcessesRunning
        # reliably without touching geckodriver (we target specific popen PIDs, not all
        # descendants of the pytest process).
        for _proc in list(wc._active_processes.values()):
            if _proc._popen and _proc._popen.poll() is None:
                try:
                    _kill_subtree(_proc._popen.pid)   # kill grandchildren (nmap binary)
                except Exception:
                    pass
                try:
                    _proc._popen.kill()               # kill shell
                except Exception:
                    pass

        # Wait for _capture_output threads to finish and fastProcessesRunning to reach 0
        deadline = time.time() + 20
        while time.time() < deadline:
            if wc.fastProcessesRunning == 0:
                break
            time.sleep(0.5)
        time.sleep(0.5)
        yield

    def test_notes_contain_all_ports_stages_for_known_host(self, srv):
        """Notes contain scan header + S1/S2 stage lines + NSE template line."""
        host_id = type(self)._host_id
        r = _requests.get(f"{srv['url']}/api/workspace/hosts/{host_id}", timeout=5)
        assert r.status_code == 200, f"Host detail returned {r.status_code}"
        note_text = r.json().get('note', '')
        assert '=== Scan' in note_text, \
            f"Scan header not found in notes. note_text={note_text!r}"
        assert 'S1 (PORTS)' in note_text, \
            f"S1 (PORTS) not found in notes. note_text={note_text!r}"
        assert 'S2 (PORTS)' in note_text, \
            f"S2 (PORTS) not found in notes. note_text={note_text!r}"
        assert 'S6 (NSE template' in note_text, \
            f"S6 (NSE template) not found in notes. note_text={note_text!r}"

    def test_notes_visible_in_ui_notes_tab(self, drv, srv):
        """The Notes tab in the right panel shows the scan commands."""
        # Navigate to Scan tab first to ensure right context
        scan_btn = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]')))
        js(drv, 'arguments[0].click()', scan_btn)
        time.sleep(0.3)
        # Select the host
        _select_host(drv)
        # Click Notes tab in right panel (data-tab="notes-right" per index.html)
        notes_tab = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '[data-tab="notes-right"]')))
        js(drv, 'arguments[0].click()', notes_tab)
        time.sleep(1.0)

        def _notes_non_empty(driver):
            el = driver.find_elements(By.ID, 'notes-display')
            if not el:
                return False
            txt = el[0].get_attribute('innerText') or ''
            return '=== Scan' in txt

        W(drv, 12).until(_notes_non_empty)
        note_text = js(drv, "return document.getElementById('notes-display').innerText || ''")
        assert '=== Scan' in note_text, \
            f"Notes tab does not show scan header. note_text={note_text!r}"


# ── Feature 4: TestProcessTimeout (v10.81) ───────────────────────────────────

def _drain_queue(wc, srv_url, timeout=30):
    """Wait until both fastProcessesRunning is 0 AND the snapshot shows no
    Running processes — ensures all background threads have fully exited and
    the next runCommand can claim a slot immediately."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if wc.fastProcessesRunning == 0:
            try:
                snap = _requests.get(f"{srv_url}/api/snapshot", timeout=5).json()
                running = sum(1 for p in snap.get('processes', [])
                              if p.get('status') == 'Running')
                if running == 0:
                    time.sleep(0.5)  # one extra tick
                    return
            except Exception:
                pass
        time.sleep(0.5)


class TestProcessTimeout:
    """Process timeout watchdog kills non-nmap processes after general_process_timeout secs.

    Class fixture launches one 'sleep 60' with a 5-second timeout, waits for
    the watchdog to kill it, then navigates the browser to the Scan/Processes
    view so all tests can verify both API state and DOM state.
    """

    _proc_id = None   # shared across tests via class attribute

    @pytest.fixture(scope="class", autouse=True)
    def _setup(self, srv, drv):
        """Launch the timeout test process once; navigate browser to see it."""
        wc = srv['wc']
        orig = getattr(wc.settings, 'general_process_timeout', '300')
        _drain_queue(wc, srv['url'])
        wc.settings.general_process_timeout = '5'
        result = wc.runCommand('sleep 60', name='timeout-proc',
                               hostIp=IP, run_actions=False)
        proc_id = result['process_id']
        type(self)._proc_id = proc_id

        # _start_process runs in a background thread — wait for it to populate
        # _active_processes and set _live_output_path before we read it.
        deadline = time.time() + 5
        proc = None
        while time.time() < deadline:
            proc = wc._active_processes.get(proc_id)
            if proc and getattr(proc, '_live_output_path', None):
                break
            time.sleep(0.2)
        type(self)._live_path = getattr(proc, '_live_output_path', None) if proc else None

        # Wait for watchdog to kill it (API, not DOM — immune to splitter state)
        _wait_killed(srv['url'], proc_id, timeout=15)
        # Poll the live file until the timeout message appears (up to 8 s).
        # _capture_output writes it after readline() returns EOF, which happens
        # once _kill_subtree + proc._popen.kill() close all pipe write ends.
        if type(self)._live_path:
            deadline_live = time.time() + 8
            while time.time() < deadline_live:
                try:
                    with open(type(self)._live_path, encoding='ISO-8859-1',
                              errors='replace') as _f:
                        if '[Legion] Process killed' in _f.read():
                            break
                except Exception:
                    pass
                time.sleep(0.3)
        else:
            time.sleep(2.5)

        # Navigate browser so DOM assertions can see the process row
        js(drv, "document.querySelector"
           "('#main-tab-bar [data-tab=\"scan-tab\"]').click()")
        _select_host(drv)
        js(drv, "document.querySelector"
           "('#bottom-tab-bar [data-tab=\"processes-panel\"]').click()")
        time.sleep(1.5)   # wait ≥1 snapshot cycle so row is re-rendered

        yield

        wc.settings.general_process_timeout = orig
        try:
            _requests.post(f"{srv['url']}/api/processes/{type(self)._proc_id}/kill",
                           timeout=5)
        except Exception:
            pass

    def test_killed_status_via_api(self, srv):
        """Snapshot API reports Killed for the timed-out process."""
        proc_id = type(self)._proc_id
        snap = _requests.get(f"{srv['url']}/api/snapshot", timeout=5).json()
        status = next((p['status'] for p in snap.get('processes', [])
                       if str(p.get('id')) == str(proc_id)), None)
        assert status == 'Killed', \
            f"Expected Killed via API, got {status!r} for proc {proc_id}"

    def test_killed_status_in_dom(self, drv):
        """Process row status cell shows 'Killed' text after timeout."""
        # Columns: ☐ | ID | Name | Target | PID | Status | % | Elapsed
        # Checkbox added v10.136 → status is now index 5 (was 4 before checkbox)
        proc_id = type(self)._proc_id
        # Re-find after snapshot re-render (stale element rule)
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        cells = row.find_elements(By.TAG_NAME, 'td')
        assert len(cells) >= 6, f"Process row has only {len(cells)} cells; expected 8"
        status_text = cells[5].text.strip()
        assert status_text == 'Killed', \
            f"Status cell (index 5) shows {status_text!r}, expected 'Killed'"

    def test_killed_in_under_half_runtime(self, srv):
        """The process was killed in under half its 60-second runtime.

        This proves the watchdog fired at ~5s rather than waiting for the process
        to finish naturally.  We verify via the API elapsed time field: a process
        killed by the watchdog has elapsed < 30s (half of 60s), whereas a process
        that ran to completion would have elapsed ≥ 55s.
        """
        proc_id = type(self)._proc_id
        snap = _requests.get(f"{srv['url']}/api/snapshot", timeout=5).json()
        proc_snap = next((p for p in snap.get('processes', [])
                          if str(p.get('id')) == str(proc_id)), None)
        assert proc_snap is not None, f"Process {proc_id} not in snapshot"

        elapsed = float(proc_snap.get('elapsed_secs') or proc_snap.get('elapsed') or 0)
        assert elapsed < 30, \
            f"Process ran for {elapsed:.1f}s — expected <30s (watchdog at 5s, process was 60s)"
        assert elapsed >= 4, \
            f"Process ran for only {elapsed:.1f}s — watchdog should wait 5s"

    def test_output_panel_loads_on_row_click(self, drv, srv):
        """Clicking the killed process row in the browser loads the output panel
        (calls the output API route). Panel element exists and is in the DOM."""
        proc_id = type(self)._proc_id
        # Re-find row after snapshot re-render (stale element rule)
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(1.5)
        # Verify output panel is present and accessible — loadProcessOutput was called
        panel = js(drv, "return document.getElementById('plain-output')")
        assert panel is not None, "plain-output panel not found in DOM after clicking process row"
        # Verify the API output route returns the correct status
        r = _requests.get(f"{srv['url']}/api/processes/{proc_id}/output", timeout=10)
        assert r.status_code == 200, f"Output route returned {r.status_code}"
        data = r.json()
        assert data.get('status') == 'Killed', \
            f"Output route status={data.get('status')!r}, expected 'Killed'"

    def test_nmap_exempt_stays_running(self, srv):
        """A process whose name contains 'nmap' is NOT killed by the watchdog."""
        wc = srv['wc']
        orig = getattr(wc.settings, 'general_process_timeout', '300')
        proc_id = None
        try:
            _drain_queue(wc, srv['url'])
            wc.settings.general_process_timeout = '3'
            result = wc.runCommand('sleep 30', name='nmap-exempt',
                                   hostIp=IP, run_actions=False)
            proc_id = result['process_id']
            time.sleep(6.0)   # DETERMINISM-EXEMPT: testing the 3s process timeout — must wait past it
            snap = _requests.get(f"{srv['url']}/api/snapshot", timeout=5).json()
            status = next((p['status'] for p in snap.get('processes', [])
                           if str(p.get('id')) == str(proc_id)), None)
            assert status == 'Running', \
                f"nmap-named process was killed (status={status!r}) — must be exempt"
        finally:
            wc.settings.general_process_timeout = orig
            if proc_id:
                try:
                    _requests.post(f"{srv['url']}/api/processes/{proc_id}/kill",
                                   timeout=5)
                except Exception:
                    pass
            time.sleep(0.5)


# ── Feature 5: TestSchedulerNoImpacket (v10.83) ──────────────────────────────

class TestSchedulerNoImpacket:
    """Credential-requiring impacket tools are NOT in SchedulerSettings."""

    _BANNED = frozenset([
        'impacket-getnpusers',
        'impacket-getuserspns',
        'impacket-lookupsid',
        'impacket-secretsdump',
    ])

    def _get_scheduler_tool_ids(self, srv):
        """Return set of tool_id strings from automatedAttacks."""
        attacks = srv['wc'].settings.automatedAttacks or []
        # Each entry is a list: [tool_id, svc_scope, protocol]
        return {str(a[0]).strip() for a in attacks}

    def test_credential_impacket_tools_not_in_scheduler(self, srv):
        """None of the credential-requiring impacket tools appear in SchedulerSettings."""
        tool_ids = self._get_scheduler_tool_ids(srv)
        found = self._BANNED & tool_ids
        assert not found, \
            f"Credential-requiring impacket tools found in scheduler: {found}"

    def test_impacket_rpcdump_remains_in_scheduler(self, srv):
        """impacket-rpcdump (no creds needed) is still in SchedulerSettings."""
        tool_ids = self._get_scheduler_tool_ids(srv)
        assert 'impacket-rpcdump' in tool_ids, \
            f"impacket-rpcdump missing from scheduler. All tools: {sorted(tool_ids)}"

    def test_scheduler_does_not_trigger_impacket_on_msrpc_port(self, srv):
        """scheduler() for a host with msrpc+microsoft-ds does not launch banned impacket tools."""
        wc = srv['wc']
        srv_url = srv['url']

        try:
            existing_ids = {
                str(p.get('id', ''))
                for p in _requests.get(f"{srv_url}/api/snapshot", timeout=5).json().get('processes', [])
            }
        except Exception:
            existing_ids = set()

        wc.scheduler(isNmapImport=True)
        time.sleep(2.0)

        try:
            all_procs = _requests.get(f"{srv_url}/api/snapshot", timeout=5).json().get('processes', [])
        except Exception:
            all_procs = []

        new_procs = [p for p in all_procs if str(p.get('id', '')) not in existing_ids]
        new_names = [str(p.get('name', '')).lower() for p in new_procs]

        banned_launched = [n for n in new_names if any(b in n for b in self._BANNED)]
        assert not banned_launched, \
            f"Scheduler launched banned impacket tools: {banned_launched}"

        # Kill new processes via API to avoid _kill_all_descendants() hitting geckodriver
        for p in new_procs:
            if p.get('status', '') in ('Running', 'Waiting'):
                try:
                    _requests.post(f"{srv_url}/api/processes/{p['id']}/kill", timeout=5)
                except Exception:
                    pass
        time.sleep(0.5)
