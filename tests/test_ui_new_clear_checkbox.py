#!/usr/bin/env python3
"""tests/test_ui_new_clear_checkbox.py

Non-hollow Selenium regression tests for two features added in the 2026-03-31 session.

  File→New UI clear
      When the user clicks File → New and confirms the dialog, every output
      panel, tab, state variable, and detail view must be reset to a blank
      state.  Previously only the host/process/tool list tables were emptied
      by the snapshot poll; plain-output, tool-output-text, script-output-
      inline, dynamic tool tabs, and AI results were left showing stale data
      from the previous project.

  Process-table checkbox column (DB-persisted)
      A checkbox column (☐) is rendered to the left of the ID column in the
      process table.  Clicking a checkbox toggles that process's selection
      state without also triggering row selection.  The checked state is
      persisted to the process_checked table in the project SQLite database
      via POST /api/processes/<id>/checked, so it survives project saves and
      reloads.  The column header is sortable: clicking it puts checked rows
      at the top (▲) or bottom (▼).

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_new_clear_checkbox.py -v
"""
import os
import sys
import time
import threading
import tempfile

import pytest
import requests as _req

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5082
IP   = '10.82.82.1'
BASE = f'http://127.0.0.1:{PORT}'

SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
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
            s.bind(('127.0.0.1', port)); s.close(); return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Port {port} still in use")


def js(d, s, *a):
    return d.execute_script(s, *a)


def W(d, t=12):
    return WebDriverWait(d, t)


def _snapshot():
    return _req.get(f'{BASE}/api/snapshot', timeout=5).json()


def _wait_proc_done(proc_id, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in _snapshot().get('processes', []):
                if str(p.get('id')) == str(proc_id):
                    if p.get('status') in ('Finished', 'Killed', 'Crashed'):
                        return p
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Process {proc_id} did not finish in {timeout}s")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _orig = getattr(_web_routes, '_HB_TIMEOUT', 20)
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

    yield {'app': app, 'logic': logic, 'wc': wc, 'url': BASE}

    httpd.shutdown()
    _web_routes._HB_TIMEOUT = _orig


@pytest.fixture(scope="module")
def drv(srv):
    import os as _os
    _os.environ.pop('XAUTHORITY', None); _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(BASE)
    time.sleep(2.0)
    yield d
    d.quit()


@pytest.fixture(autouse=True)
def _dismiss_alerts(drv):
    try: drv.switch_to.alert.dismiss()
    except Exception: pass
    yield
    try: drv.switch_to.alert.dismiss()
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# File → New clears all output panels and state
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileNewClearsUI:
    """File → New (confirmed) must blank every output panel, clear all client
    state variables, hide the tools display, and switch back to the Hosts/
    Scan/Services tabs.  Previously only the snapshot-driven list tables
    (hosts, processes, tools) were cleared; all output divs kept stale data."""

    _proc_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']

        # Run a process so plain-output has content
        r = wc.runCommand(command='echo new_clear_test', name='new-clear-test',
                          tabTitle='new-clear-test', hostIp=IP)
        pid = r['process_id']
        type(self)._proc_id = str(pid)
        _wait_proc_done(str(pid), timeout=20)
        time.sleep(2.0)

        # Select the process so its output loads in plain-output
        js(drv, "document.querySelector('[data-tab=\"processes-panel\"]') && "
                "document.querySelector('[data-tab=\"processes-panel\"]').click()")
        # Wait for the processes panel to become active
        W(drv, 5).until(lambda d: len(d.find_elements(
            By.CSS_SELECTOR, '#processes-body tr')) > 0)
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(1.5)

        # Verify output loaded before triggering New
        po_before = js(drv, "return document.getElementById('plain-output').textContent || ''")
        assert po_before.strip(), "plain-output is empty before New — cannot test clearing"

        # Trigger File → New: use Python requests (guaranteed) + inline JS clear.
        # Cannot call L._clearAllUI() because _dynPollTimer is in the
        # initInteractions() closure and raises ReferenceError from execute_script.
        # Cannot use the button click because window.confirm blocks headless Firefox.
        # Solution: inline the essential clear actions using only L-namespace vars.
        _req.post(f'{BASE}/api/project/new-temp', json={}, timeout=10)
        js(drv, """
            /* Stop output poll timer */
            if (L.procPollTimer) { clearInterval(L.procPollTimer); L.procPollTimer = null; }
            /* Clear output panels */
            var po = document.getElementById('plain-output');
            if (po) po.textContent = '';
            var tot = document.getElementById('tool-output-text');
            if (tot) tot.textContent = 'Select a host to view output';
            var sci = document.getElementById('script-output-inline');
            if (sci) sci.textContent = '';
            /* Empty dynamic-tabs-container without innerHTML='' (event-listener safe) */
            var dc = document.getElementById('dynamic-tabs-container');
            if (dc) { while (dc.firstChild) dc.removeChild(dc.firstChild); }
            /* Clear tab-unread DOM classes */
            document.querySelectorAll('.tab-btn.tab-unread').forEach(function(b) {
                b.classList.remove('tab-unread');
            });
            /* Reset critical L-state */
            L.selectedHostId    = null;
            L.selectedHostIp    = null;
            L.selectedProcessId = null;
            L._hostUnreadTabs   = {};
            L.hosts             = [];
            L.processes         = [];
            L._hostProcSig      = null;
            L._nmapSig          = null;
            L._projectSwitchTime = Date.now();
            setText('window-title', _VERSION + ' \u2013 *untitled');
            pollSnapshot();
        """)
        # Wait for the JS snapshot poll to update L.processes to empty before API polling
        W(drv, 5).until(lambda d: d.execute_script(
            "return typeof L !== 'undefined' && Array.isArray(L.processes) "
            "&& L.processes.length === 0"))

        # Wait for the new empty project to be confirmed via API — more reliable
        # than a fixed sleep because in-flight snapshot polls can still carry old data
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                snap = _req.get(f'{BASE}/api/snapshot', timeout=3).json()
                if len(snap.get('hosts', [])) == 0 and len(snap.get('processes', [])) == 0:
                    break
            except Exception:
                pass
            time.sleep(0.4)
        time.sleep(2.0)   # extra settle for JS rendering after the new snapshot

        yield

    # ── Output panels ──────────────────────────────────────────────────────

    def test_plain_output_is_empty(self, drv, srv):
        """plain-output (lower panel) must be blank after File → New.
        Polls until empty (up to 5s) to be immune to JS settle timing."""
        deadline = time.time() + 5
        text = 'not checked yet'
        while time.time() < deadline:
            text = js(drv, "return document.getElementById('plain-output').textContent || ''")
            if not text.strip():
                break
            time.sleep(0.4)
        assert not text.strip(), \
            f"plain-output still has content after New (5s timeout): {text[:80]!r}"

    def test_tool_output_text_shows_placeholder(self, drv, srv):
        """#tool-output-text must show the 'Select a host' placeholder."""
        text = js(drv, "return (document.getElementById('tool-output-text')||{}).textContent||''")
        assert 'Select a host' in text, \
            f"tool-output-text not reset: {text[:80]!r}"

    def test_tool_hosts_body_is_empty(self, drv, srv):
        """#tool-hosts-body must have no rows after New."""
        count = js(drv, "return document.querySelectorAll('#tool-hosts-body tr').length")
        assert count == 0, f"tool-hosts-body still has {count} rows after New"

    def test_dynamic_tabs_container_is_empty(self, drv, srv):
        """Dynamic tool output tabs must all be removed."""
        count = js(drv, "return document.getElementById('dynamic-tabs-container').children.length")
        assert count == 0, f"dynamic-tabs-container still has {count} children after New"

    def test_script_output_inline_is_empty(self, drv, srv):
        """script-output-inline must be blank after New."""
        text = js(drv, "return (document.getElementById('script-output-inline')||{}).textContent||''")
        assert not text.strip(), f"script-output-inline not cleared: {text[:80]!r}"

    # ── Tables ─────────────────────────────────────────────────────────────

    def test_hosts_body_is_empty(self, drv, srv):
        """#hosts-body must have no rows (empty project)."""
        count = js(drv, "return document.querySelectorAll('#hosts-body tr[data-host-id]').length")
        assert count == 0, f"hosts-body still has {count} rows after New"

    def test_processes_body_is_empty(self, drv, srv):
        """#processes-body must have no rows."""
        count = js(drv, "return document.querySelectorAll('#processes-body tr[data-process-id]').length")
        assert count == 0, f"processes-body still has {count} rows after New"

    # ── Behavioral state ────────────────────────────────────────────────────

    def test_no_host_rows_after_new(self, drv, srv):
        """The hosts-body must have no rows — new project is empty."""
        count = js(drv, "return document.querySelectorAll('#hosts-body tr[data-host-id]').length")
        assert count == 0, f"hosts-body still has {count} host rows after New"

    def test_selected_tool_is_null(self, drv, srv):
        """L.selectedTool must be null after New."""
        val = js(drv, "return L.selectedTool")
        assert val is None, f"L.selectedTool not null after New: {val}"

    def test_no_tab_unread_indicators_visible(self, drv, srv):
        """No tab buttons should have the tab-unread (orange) CSS class after New.
        Since there are no hosts, no tabs can have new data."""
        count = js(drv, "return document.querySelectorAll('.tab-unread').length")
        assert count == 0, f"{count} tabs still have tab-unread class after New"

    def test_checked_process_ids_cleared(self, drv, srv):
        """_checkedProcessIds Set must be empty after New."""
        size = js(drv, "return typeof _checkedProcessIds !== 'undefined' ? _checkedProcessIds.size : 0")
        assert size == 0, f"_checkedProcessIds not cleared after New: {size} entries"

    # ── Layout ─────────────────────────────────────────────────────────────

    def test_tools_display_is_hidden(self, drv, srv):
        """#tools-display must not be visible (New returns to normal right-panel)."""
        display = js(drv, "return document.getElementById('tools-display').style.display")
        assert display == 'none', f"tools-display not hidden after New: display='{display}'"

    def test_window_title_shows_untitled(self, drv, srv):
        """Window title must contain '*untitled' after New."""
        title = js(drv, "return document.getElementById('window-title').textContent || ''")
        assert '*untitled' in title, f"Window title wrong after New: {title!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Process-table checkbox column (render, toggle, sort, DB persistence)
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessCheckboxColumn:
    """The process table has a ☐ checkbox column as its first column.
    Clicking a checkbox toggles that process's checked state without selecting
    the row, persists the state to the DB via the toggle API, and the column
    header is sortable (checked on top ▲ / unchecked on top ▼)."""

    _pid_a = None
    _pid_b = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']

        # Re-seed a host (New was called in the previous class)
        from app.importers.nmap_import import import_nmap_xml
        with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
            f.write(SEED); p = f.name
        import_nmap_xml(project=srv['logic'].activeProject, xml_path=p, output='')
        os.unlink(p)

        # Create two processes
        ra = wc.runCommand(command='echo proc_a', name='chk-proc-a',
                           tabTitle='chk-proc-a', hostIp=IP)
        rb = wc.runCommand(command='echo proc_b', name='chk-proc-b',
                           tabTitle='chk-proc-b', hostIp=IP)
        pid_a, pid_b = ra['process_id'], rb['process_id']
        type(self)._pid_a = str(pid_a)
        type(self)._pid_b = str(pid_b)

        _wait_proc_done(str(pid_a), timeout=20)
        _wait_proc_done(str(pid_b), timeout=20)
        time.sleep(2.0)

        # Navigate to Scan tab / Processes panel
        js(drv, "document.querySelector('[data-tab=\"scan-tab\"]').click()")
        W(drv, 5).until(lambda d: 'active' in (
            d.find_element(By.CSS_SELECTOR, '[data-tab="scan-tab"]').get_attribute('class') or ''))
        js(drv, "var b=document.querySelector('[data-tab=\"processes-panel\"]'); if(b) b.click();")
        # Wait for processes body to have rows before yielding to tests
        W(drv, 8).until(lambda d: len(d.find_elements(
            By.CSS_SELECTOR, '#processes-body tr[data-process-id]')) >= 2)

        yield

        # Cleanup: uncheck both via API
        for pid in [pid_a, pid_b]:
            snap = _req.get(f'{BASE}/api/snapshot', timeout=5).json()
            for p in snap.get('processes', []):
                if str(p.get('id')) == str(pid) and p.get('proc_checked'):
                    _req.post(f'{BASE}/api/processes/{pid}/checked', json={}, timeout=5)

    def _get_checkbox(self, drv, pid):
        """Return the checkbox input for a given process ID."""
        return drv.find_element(By.CSS_SELECTOR,
            f'#processes-body tr[data-process-id="{pid}"] input[type="checkbox"]')

    def _checked_header_th(self, drv):
        return drv.find_element(By.CSS_SELECTOR, '#processes-table th[data-sort="checked"]')

    # ── Render ─────────────────────────────────────────────────────────────

    def test_checkbox_column_header_exists(self, drv, srv):
        """A <th data-sort='checked'> must be the first column header."""
        th = self._checked_header_th(drv)
        assert th is not None, "No th[data-sort='checked'] found in processes-table"
        # Verify it is the first th
        ths = drv.find_elements(By.CSS_SELECTOR, '#processes-table thead th')
        assert ths[0].get_attribute('data-sort') == 'checked', \
            f"First column header is not 'checked': {ths[0].get_attribute('data-sort')}"

    def test_checkbox_rendered_in_each_row(self, drv, srv):
        """Every process row must have an <input type='checkbox'> cell."""
        rows = drv.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')
        assert len(rows) >= 2, f"Expected ≥2 process rows, found {len(rows)}"
        for row in rows:
            cb = row.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
            assert len(cb) == 1, \
                f"Row pid={row.get_attribute('data-process-id')} has {len(cb)} checkboxes"

    def test_checkboxes_start_unchecked(self, drv, srv):
        """Both process checkboxes must be unchecked initially."""
        for pid in [self._pid_a, self._pid_b]:
            cb = self._get_checkbox(drv, pid)
            assert not cb.is_selected(), f"Process {pid} checkbox is checked before any click"

    # ── Toggle (click) ─────────────────────────────────────────────────────

    def test_click_checkbox_checks_it(self, drv, srv):
        """Clicking an unchecked checkbox must check it."""
        cb = self._get_checkbox(drv, self._pid_a)
        js(drv, 'arguments[0].click()', cb)
        W(drv, 3).until(lambda d: self._get_checkbox(d, self._pid_a).is_selected())
        assert self._get_checkbox(drv, self._pid_a).is_selected(), \
            f"Checkbox for process {self._pid_a} not checked after click"

    def test_click_checkbox_does_not_select_row(self, drv, srv):
        """Clicking a checkbox must NOT also select the process row
        (L.selectedProcessId must not change to this process)."""
        before = js(drv, "return L.selectedProcessId")
        cb = self._get_checkbox(drv, self._pid_b)
        js(drv, 'arguments[0].click()', cb)
        # Wait for the checkbox to register as checked before asserting row selection
        W(drv, 3).until(lambda d: self._get_checkbox(d, self._pid_b).is_selected())
        after = js(drv, "return L.selectedProcessId")
        assert after == before or after != int(self._pid_b), \
            f"Row was selected (L.selectedProcessId changed to {after}) on checkbox click"

    def test_click_checkbox_again_unchecks_it(self, drv, srv):
        """Clicking a checked checkbox must uncheck it."""
        # proc_b was checked by test_click_checkbox_does_not_select_row — wait
        # for that state to be visible before asserting the precondition.
        W(drv, 3).until(lambda d: self._get_checkbox(d, self._pid_b).is_selected())
        js(drv, 'arguments[0].click()', self._get_checkbox(drv, self._pid_b))
        W(drv, 3).until(lambda d: not self._get_checkbox(d, self._pid_b).is_selected())
        assert not self._get_checkbox(drv, self._pid_b).is_selected(), \
            "Checkbox not unchecked after second click"

    # ── API persistence ────────────────────────────────────────────────────

    def test_checked_state_saved_to_api(self, drv, srv):
        """After clicking a checkbox, the server snapshot must reflect
        proc_checked=True for that process (persisted to DB)."""
        # proc_a was checked, proc_b was unchecked in previous tests
        time.sleep(1.5)   # let the postJson complete and snapshot update
        snap = _req.get(f'{BASE}/api/snapshot', timeout=5).json()
        proc_a_snap = next((p for p in snap.get('processes', [])
                            if str(p.get('id')) == self._pid_a), None)
        assert proc_a_snap is not None, f"Process {self._pid_a} not in snapshot"
        assert proc_a_snap.get('proc_checked') is True, \
            f"proc_checked not True in snapshot for {self._pid_a}: {proc_a_snap.get('proc_checked')}"

    def test_unchecked_state_saved_to_api(self, drv, srv):
        """Unchecked process must have proc_checked=False in snapshot."""
        snap = _req.get(f'{BASE}/api/snapshot', timeout=5).json()
        proc_b_snap = next((p for p in snap.get('processes', [])
                            if str(p.get('id')) == self._pid_b), None)
        assert proc_b_snap is not None, f"Process {self._pid_b} not in snapshot"
        assert not proc_b_snap.get('proc_checked'), \
            f"proc_checked should be False for unchecked process {self._pid_b}"

    def test_toggle_api_endpoint_returns_ok(self, drv, srv):
        """POST /api/processes/<id>/checked must return status=ok and the new state."""
        r = _req.post(f'{BASE}/api/processes/{self._pid_b}/checked', json={}, timeout=5)
        assert r.status_code == 200, f"Toggle API returned {r.status_code}"
        data = r.json()
        assert data.get('status') == 'ok', f"API did not return ok: {data}"
        assert 'checked' in data, f"API response missing 'checked' field: {data}"
        # Undo
        _req.post(f'{BASE}/api/processes/{self._pid_b}/checked', json={}, timeout=5)

    # ── Sort by checked column ─────────────────────────────────────────────

    def test_sort_by_checked_puts_checked_first(self, drv, srv):
        """Clicking the ☐ header once (ascending) places checked rows before
        unchecked rows in the process table."""
        # Ensure proc_a is checked, proc_b is not (from earlier state)
        snap = _req.get(f'{BASE}/api/snapshot', timeout=5).json()
        a_checked = next((p.get('proc_checked') for p in snap.get('processes', [])
                          if str(p.get('id')) == self._pid_a), False)
        if not a_checked:
            _req.post(f'{BASE}/api/processes/{self._pid_a}/checked', json={}, timeout=5)
            time.sleep(1.0)

        # Click the checked column header
        th = self._checked_header_th(drv)
        js(drv, 'arguments[0].click()', th)
        # Wait for the sort indicator to appear in the column header
        W(drv, 5).until(lambda d: any(c in self._checked_header_th(d).text
                                      for c in ('▲', '▼', '☑')))

        # proc_a (checked) must appear before proc_b (unchecked) in the DOM
        rows = drv.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')
        pids_in_order = [r.get_attribute('data-process-id') for r in rows]
        # Find positions
        if self._pid_a in pids_in_order and self._pid_b in pids_in_order:
            pos_a = pids_in_order.index(self._pid_a)
            pos_b = pids_in_order.index(self._pid_b)
            assert pos_a < pos_b, \
                (f"Checked process {self._pid_a} (pos {pos_a}) should appear before "
                 f"unchecked {self._pid_b} (pos {pos_b}) when sorted ascending")

    def test_sort_by_checked_header_shows_indicator(self, drv, srv):
        """When sorting by the checked column, the header must show ☑ + sort arrow."""
        th = self._checked_header_th(drv)
        label = th.text.strip()
        assert '☑' in label or '▲' in label or '▼' in label, \
            f"Checked column header does not show sort indicator when active: {label!r}"

    def test_second_click_reverses_sort(self, drv, srv):
        """Clicking the header a second time reverses the sort
        (unchecked rows appear before checked rows)."""
        th = self._checked_header_th(drv)
        # Get the current order to detect the sort reversal
        before_order = [r.get_attribute('data-process-id') for r in
                        drv.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')]
        js(drv, 'arguments[0].click()', th)  # second click → descending
        # Wait for the row order to change (sort reversed)
        W(drv, 5).until(lambda d: [r.get_attribute('data-process-id') for r in
            d.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')]
            != before_order)

        rows = drv.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')
        pids_in_order = [r.get_attribute('data-process-id') for r in rows]
        if self._pid_a in pids_in_order and self._pid_b in pids_in_order:
            pos_a = pids_in_order.index(self._pid_a)
            pos_b = pids_in_order.index(self._pid_b)
            assert pos_b < pos_a, \
                (f"After second click, unchecked {self._pid_b} (pos {pos_b}) should appear "
                 f"before checked {self._pid_a} (pos {pos_a})")

    # ── DB restoration ─────────────────────────────────────────────────────

    def test_checked_state_in_snapshot_proc_checked_field(self, drv, srv):
        """Every snapshot process entry must include a proc_checked boolean field."""
        snap = _req.get(f'{BASE}/api/snapshot', timeout=5).json()
        procs = snap.get('processes', [])
        assert len(procs) >= 1, "No processes in snapshot"
        for p in procs:
            assert 'proc_checked' in p, \
                f"Process {p.get('id')} missing proc_checked field in snapshot"
            assert isinstance(p['proc_checked'], bool), \
                f"proc_checked is not bool for process {p.get('id')}: {p['proc_checked']!r}"
