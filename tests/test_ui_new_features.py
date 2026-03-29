#!/usr/bin/env python3
"""tests/test_ui_new_features.py

Non-hollow Selenium regression tests for UI features added 2026-03-28.

  v10.67  File-browser fb-select button label is context-sensitive:
          shows "Save" when the browser is opened via Save As, and
          "Open" when opened via Open Project.  Previously always said
          "Select".

  v10.68  "Hide Finished" and "Hide All" process-table buttons now
          toggle: first click hides and renames to "Unhide Finished" /
          "Unhide All"; second click restores and renames back.  Hidden
          processes are absent from #processes-body (snapshot only
          returns closed='False' rows); restored processes reappear.

  v10.70  Tools table (left panel) is sortable by tool name: clicking
          the "Tool ▲" header reverses to Z→A ("Tool ▼"); clicking
          again restores A→Z ("Tool ▲").  The sorted order of actual
          rows matches the direction indicator.

  v10.71  When a process in the tool-hosts middle pane has has_match=True
          (wc._matches contains a hit for that process), the Host and
          Port/Stage cells render in red (#f44) with a ★ prefix.
          A process without a match has no red styling.

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_new_features.py -v
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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5076
IP   = '10.76.76.1'

SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
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
    raise TimeoutError(f"Process {proc_id} did not reach terminal state within {timeout}s")


def _switch_left_tab(drv, tab_id):
    """Click a left-panel tab button by its data-tab value."""
    js(drv, f"document.querySelector('[data-tab=\"{tab_id}\"]').click()")
    time.sleep(0.8)


def _reset_hide_buttons(drv):
    """Force both hide/unhide buttons back to their initial 'Hide' state in JS."""
    js(drv, """
        var b1 = document.getElementById('process-clear-finished-button');
        var b2 = document.getElementById('process-clear-all-button');
        if (b1) { b1.dataset.hidden = '0'; b1.textContent = 'Hide Finished'; }
        if (b2) { b2.dataset.hidden = '0'; b2.textContent = 'Hide All'; }
    """)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _orig = getattr(_web_routes, '_HB_TIMEOUT', 20)
    _web_routes._HB_TIMEOUT = 600          # disable watchdog during tests

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
    _web_routes._HB_TIMEOUT = _orig


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
    try:
        drv.switch_to.alert.dismiss()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# v10.67 — File-browser button label: "Save" vs "Open"
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveOpenDialogLabels:
    """The fb-select button in the file browser shows the label matching
    the operation being performed: "Save" for save-mode, "Open" for open-mode."""

    def _open_fb_via(self, drv, action_id):
        """Trigger the file browser by JS-clicking a File-menu action button.
        Bypasses dropdown visibility so the test doesn't depend on menu hover."""
        js(drv, f"document.getElementById('{action_id}').click()")
        # Wait until the file-browser modal is visible and fb-select is present
        W(drv, 8).until(EC.visibility_of_element_located((By.ID, 'file-browser-modal')))
        time.sleep(0.3)

    def _close_fb(self, drv):
        btn = drv.find_element(By.ID, 'fb-cancel')
        btn.click()
        time.sleep(0.5)

    def test_save_as_dialog_shows_save_label(self, drv, srv):
        """Clicking Save As opens the browser with fb-select labelled 'Save'."""
        self._open_fb_via(drv, 'action-save-as')
        btn = drv.find_element(By.ID, 'fb-select')
        label = btn.text.strip()
        self._close_fb(drv)
        assert label == 'Save', f"Expected 'Save' on fb-select in save mode, got '{label}'"

    def test_open_dialog_shows_open_label(self, drv, srv):
        """Clicking Open opens the browser with fb-select labelled 'Open'."""
        self._open_fb_via(drv, 'action-open')
        btn = drv.find_element(By.ID, 'fb-select')
        label = btn.text.strip()
        self._close_fb(drv)
        assert label == 'Open', f"Expected 'Open' on fb-select in open mode, got '{label}'"

    def test_save_as_then_open_labels_differ(self, drv, srv):
        """Opening Save As then Open gives different labels — proves dynamic switching."""
        self._open_fb_via(drv, 'action-save-as')
        save_label = drv.find_element(By.ID, 'fb-select').text.strip()
        self._close_fb(drv)

        self._open_fb_via(drv, 'action-open')
        open_label = drv.find_element(By.ID, 'fb-select').text.strip()
        self._close_fb(drv)

        assert save_label == 'Save', f"Save mode label wrong: '{save_label}'"
        assert open_label == 'Open', f"Open mode label wrong: '{open_label}'"
        assert save_label != open_label, "Labels must differ between save and open modes"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.68 — Hide Finished / Hide All toggle
# ═══════════════════════════════════════════════════════════════════════════════

class TestHideUnhideProcesses:
    """Hide Finished and Hide All buttons toggle their labels and actually
    remove / restore process rows from #processes-body via closed='True'."""

    _finished_pid = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        # Ensure both buttons start in "hide" state (not toggled)
        _reset_hide_buttons(drv)
        # Restore any previously hidden processes so the table is clean
        _requests.post(f"{srv['url']}/api/processes/restore",
                       json={'reset_all': True}, timeout=5)
        # Ensure the status filter shows all processes
        js(drv, "var f=document.getElementById('process-status-filter'); if(f) f.value='';" )

        # Run a fast process that will finish quickly
        result = srv['wc'].runCommand(
            command="echo hide_test_marker",
            name='hide-test-echo',
            tabTitle='hide-test-echo',
            hostIp=IP,
        )
        pid = result['process_id']
        type(self)._finished_pid = str(pid)
        _wait_proc_done_api(srv['url'], pid, timeout=20)
        time.sleep(2.0)  # let snapshot render the row

        yield

        # Teardown: restore everything and reset button labels
        _requests.post(f"{srv['url']}/api/processes/restore",
                       json={'reset_all': True}, timeout=5)
        _reset_hide_buttons(drv)
        time.sleep(1.5)

    # ── Hide Finished ──────────────────────────────────────────────────────

    def test_hide_finished_initial_label(self, drv, srv):
        """Button initially reads 'Hide Finished' (not toggled)."""
        btn = drv.find_element(By.ID, 'process-clear-finished-button')
        assert btn.text.strip() == 'Hide Finished', \
            f"Expected 'Hide Finished', got '{btn.text.strip()}'"

    def test_finished_process_visible_before_hide(self, drv, srv):
        """The finished process row is present in #processes-body before hiding."""
        rows = drv.find_elements(
            By.CSS_SELECTOR,
            f'#processes-body tr[data-process-id="{self._finished_pid}"]')
        assert len(rows) == 1, \
            f"Process {self._finished_pid} not in table before hide (found {len(rows)} rows)"

    def test_hide_finished_changes_label_to_unhide(self, drv, srv):
        """Clicking 'Hide Finished' changes the label to 'Unhide Finished'."""
        btn = drv.find_element(By.ID, 'process-clear-finished-button')
        btn.click()
        time.sleep(2.5)  # wait for postJson + snapshot re-render
        btn = drv.find_element(By.ID, 'process-clear-finished-button')
        assert btn.text.strip() == 'Unhide Finished', \
            f"Expected 'Unhide Finished' after click, got '{btn.text.strip()}'"

    def test_finished_process_absent_after_hide(self, drv, srv):
        """After hiding, the finished process row is gone from #processes-body."""
        rows = drv.find_elements(
            By.CSS_SELECTOR,
            f'#processes-body tr[data-process-id="{self._finished_pid}"]')
        assert len(rows) == 0, \
            f"Process {self._finished_pid} still visible after Hide Finished"

    def test_unhide_finished_changes_label_back(self, drv, srv):
        """Clicking 'Unhide Finished' restores the label to 'Hide Finished'."""
        btn = drv.find_element(By.ID, 'process-clear-finished-button')
        btn.click()
        time.sleep(2.5)
        btn = drv.find_element(By.ID, 'process-clear-finished-button')
        assert btn.text.strip() == 'Hide Finished', \
            f"Expected 'Hide Finished' after unhide, got '{btn.text.strip()}'"

    def test_finished_process_restored_after_unhide(self, drv, srv):
        """After unhiding, the process row is back in #processes-body."""
        rows = drv.find_elements(
            By.CSS_SELECTOR,
            f'#processes-body tr[data-process-id="{self._finished_pid}"]')
        assert len(rows) == 1, \
            f"Process {self._finished_pid} not restored after Unhide Finished"

    # ── Hide All ───────────────────────────────────────────────────────────

    def test_hide_all_initial_label(self, drv, srv):
        """'Hide All' button reads 'Hide All' before any click."""
        btn = drv.find_element(By.ID, 'process-clear-all-button')
        assert btn.text.strip() == 'Hide All', \
            f"Expected 'Hide All', got '{btn.text.strip()}'"

    def test_hide_all_changes_label_to_unhide_all(self, drv, srv):
        """Clicking 'Hide All' changes the label to 'Unhide All'."""
        btn = drv.find_element(By.ID, 'process-clear-all-button')
        btn.click()
        time.sleep(2.5)
        btn = drv.find_element(By.ID, 'process-clear-all-button')
        assert btn.text.strip() == 'Unhide All', \
            f"Expected 'Unhide All' after click, got '{btn.text.strip()}'"

    def test_hide_all_removes_finished_process(self, drv, srv):
        """After 'Hide All', the finished process is absent from the table."""
        rows = drv.find_elements(
            By.CSS_SELECTOR,
            f'#processes-body tr[data-process-id="{self._finished_pid}"]')
        assert len(rows) == 0, \
            f"Process {self._finished_pid} still visible after Hide All"

    def test_unhide_all_restores_label(self, drv, srv):
        """Clicking 'Unhide All' restores the label to 'Hide All'."""
        btn = drv.find_element(By.ID, 'process-clear-all-button')
        btn.click()
        time.sleep(2.5)
        btn = drv.find_element(By.ID, 'process-clear-all-button')
        assert btn.text.strip() == 'Hide All', \
            f"Expected 'Hide All' after unhide, got '{btn.text.strip()}'"

    def test_unhide_all_restores_process_row(self, drv, srv):
        """After 'Unhide All', the process row is back."""
        rows = drv.find_elements(
            By.CSS_SELECTOR,
            f'#processes-body tr[data-process-id="{self._finished_pid}"]')
        assert len(rows) == 1, \
            f"Process {self._finished_pid} not restored after Unhide All"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.70 — Tools table sort by clicking the "Tool" column header
# ═══════════════════════════════════════════════════════════════════════════════

_SORT_NAMES = ('aaa-sorttest', 'mmm-sorttest', 'zzz-sorttest')


class TestToolsTableSort:
    """Clicking the Tools table header sorts A→Z then Z→A.
    The ▲/▼ arrow in the header text indicates current direction.
    Actual row order in the DOM matches the indicated direction."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        # Run 3 fast processes with deliberately non-sorted names so we can
        # verify the order is controlled by the sort, not insertion order.
        # Submit in reverse order so insertion order is Z→M→A.
        ids = []
        for name in reversed(_SORT_NAMES):   # zzz, mmm, aaa
            result = srv['wc'].runCommand(
                command=f"echo {name}",
                name=name,
                tabTitle=name,
                hostIp=IP,
            )
            ids.append(result['process_id'])
        for pid in ids:
            _wait_proc_done_api(srv['url'], pid, timeout=20)
        time.sleep(2.0)  # let snapshot build the tools list

        # Navigate to the Tools left-panel tab
        _switch_left_tab(drv, 'tools-panel-left')

        yield

        # Return to the Hosts tab so subsequent tests start clean
        _switch_left_tab(drv, 'hosts-panel')

    def _sort_rows(self, drv):
        """Return the data-tool-id values of only the sort-test tools, in DOM order."""
        rows = drv.find_elements(By.CSS_SELECTOR, '#tools-body tr')
        return [
            r.get_attribute('data-tool-id')
            for r in rows
            if (r.get_attribute('data-tool-id') or '').endswith('-sorttest')
        ]

    # ── Initial state (A→Z) ────────────────────────────────────────────────

    def test_tools_header_present_with_sort_attr(self, drv, srv):
        """The tools table has a <th data-sort> header that can be clicked."""
        th = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#tools-table th[data-sort]')))
        assert 'Tool' in th.text, f"Expected 'Tool' in header text, got '{th.text}'"

    def test_initial_header_shows_ascending_arrow(self, drv, srv):
        """Default sort is A→Z so the header shows ▲."""
        th = drv.find_element(By.CSS_SELECTOR, '#tools-table th[data-sort]')
        assert '▲' in th.text, f"Expected ▲ in header initially, got '{th.text}'"

    def test_initial_order_is_ascending(self, drv, srv):
        """All three sort-test tools appear in A→Z order on first load."""
        tools = self._sort_rows(drv)
        assert len(tools) == 3, \
            f"Expected 3 sort-test tools in #tools-body, found {len(tools)}: {tools}"
        assert tools == sorted(tools), \
            f"Expected ascending order, got: {tools}"

    # ── After first click (Z→A) ────────────────────────────────────────────

    def test_click_header_changes_arrow_to_descending(self, drv, srv):
        """Clicking the header once changes ▲ to ▼."""
        th = drv.find_element(By.CSS_SELECTOR, '#tools-table th[data-sort]')
        th.click()
        time.sleep(0.5)
        th = drv.find_element(By.CSS_SELECTOR, '#tools-table th[data-sort]')
        assert '▼' in th.text, \
            f"Expected ▼ after first click, got '{th.text}'"

    def test_order_is_descending_after_first_click(self, drv, srv):
        """Tool rows are in Z→A order after the first header click."""
        tools = self._sort_rows(drv)
        assert len(tools) == 3, \
            f"Expected 3 sort-test tools, found {len(tools)}: {tools}"
        assert tools == sorted(tools, reverse=True), \
            f"Expected descending order, got: {tools}"

    # ── After second click (A→Z restored) ─────────────────────────────────

    def test_second_click_restores_ascending_arrow(self, drv, srv):
        """Clicking the header a second time restores ▲."""
        th = drv.find_element(By.CSS_SELECTOR, '#tools-table th[data-sort]')
        th.click()
        time.sleep(0.5)
        th = drv.find_element(By.CSS_SELECTOR, '#tools-table th[data-sort]')
        assert '▲' in th.text, \
            f"Expected ▲ restored after second click, got '{th.text}'"

    def test_order_is_ascending_after_second_click(self, drv, srv):
        """Tool rows are back to A→Z after the second header click."""
        tools = self._sort_rows(drv)
        assert len(tools) == 3, \
            f"Expected 3 sort-test tools, found {len(tools)}: {tools}"
        assert tools == sorted(tools), \
            f"Expected ascending order restored, got: {tools}"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.71 — Tool-hosts middle pane match highlighting
# ═══════════════════════════════════════════════════════════════════════════════

_MATCH_TOOL = 'match-tool-highlight'
_MATCH_TAB  = 'match-tool-highlight'
_NOMATCH_TAB = 'nomatch-tool-highlight'


class TestToolHostsMatchHighlight:
    """When a process has has_match=True (wc._matches contains its key),
    the Host and Port/Stage cells in #tool-hosts-body render in red (#f44)
    and carry a ★ star.  A process with no match has no such styling."""

    _match_pid   = None
    _nomatch_pid = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']

        # Process 1 — will receive a match injection
        r1 = wc.runCommand(
            command="echo match_target_output",
            name=_MATCH_TOOL,
            tabTitle=_MATCH_TAB,
            hostIp=IP,
        )
        pid1 = r1['process_id']

        # Process 2 — same tool name, different tabTitle → no match injected
        r2 = wc.runCommand(
            command="echo no_match_target_output",
            name=_MATCH_TOOL,
            tabTitle=_NOMATCH_TAB,
            hostIp=IP,
        )
        pid2 = r2['process_id']

        _wait_proc_done_api(srv['url'], pid1, timeout=20)
        _wait_proc_done_api(srv['url'], pid2, timeout=20)

        # Inject match for process 1 — key format is "hostIp:tabTitle"
        wc._matches[f"{IP}:{_MATCH_TAB}"] = ['MATCHKEYWORD']
        time.sleep(2.5)  # wait ≥1 snapshot cycle for has_match to propagate

        type(self)._match_pid   = str(pid1)
        type(self)._nomatch_pid = str(pid2)

        # Navigate to Tools tab and click the tool entry to populate tool-hosts-body
        _switch_left_tab(drv, 'tools-panel-left')
        tool_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#tools-body tr[data-tool-id="{_MATCH_TOOL}"]')))
        js(drv, 'arguments[0].click()', tool_row)
        time.sleep(1.5)  # let updateToolHosts() render both rows

        yield

        # Cleanup
        wc._matches.pop(f"{IP}:{_MATCH_TAB}", None)
        _switch_left_tab(drv, 'hosts-panel')

    def _get_host_cell_style(self, drv, proc_id):
        """Return the style attribute of the first <td> (Host cell) for a process row."""
        row = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#tool-hosts-body tr[data-process-id="{proc_id}"]')))
        tds = row.find_elements(By.TAG_NAME, 'td')
        assert len(tds) >= 2, f"Expected ≥2 cells in row for process {proc_id}"
        return tds[0].get_attribute('style') or '', row.text

    @staticmethod
    def _has_red(style):
        """Firefox normalises #f44 → rgb(255, 68, 68).  Accept either form."""
        return (
            'color:#f44' in style
            or 'color: #f44' in style
            or 'rgb(255, 68, 68)' in style
        )

    # ── Match row ──────────────────────────────────────────────────────────

    def test_match_row_host_cell_is_red(self, drv, srv):
        """The host cell of the match-positive row has the red match color."""
        style, _ = self._get_host_cell_style(drv, self._match_pid)
        assert self._has_red(style), \
            f"Expected red color on match row host cell, got style='{style}'"

    def test_match_row_host_cell_is_bold(self, drv, srv):
        """The host cell of the match row has font-weight:700."""
        style, _ = self._get_host_cell_style(drv, self._match_pid)
        assert 'font-weight:700' in style or 'font-weight: 700' in style, \
            f"Expected bold on match row host cell, got style='{style}'"

    def test_match_row_contains_star(self, drv, srv):
        """The match-positive row text contains the ★ indicator."""
        _, row_text = self._get_host_cell_style(drv, self._match_pid)
        assert '★' in row_text, \
            f"Expected ★ in match row text, got: '{row_text}'"

    def test_match_row_port_cell_is_red(self, drv, srv):
        """The Port/Stage cell (second <td>) of the match row is also red."""
        row = drv.find_element(
            By.CSS_SELECTOR,
            f'#tool-hosts-body tr[data-process-id="{self._match_pid}"]')
        tds = row.find_elements(By.TAG_NAME, 'td')
        style = tds[1].get_attribute('style') or ''
        assert self._has_red(style), \
            f"Expected red on port cell of match row, got style='{style}'"

    # ── No-match row ───────────────────────────────────────────────────────

    def test_nomatch_row_host_cell_has_no_red(self, drv, srv):
        """The host cell of the no-match row does NOT have red styling."""
        style, _ = self._get_host_cell_style(drv, self._nomatch_pid)
        assert not self._has_red(style), \
            f"Expected no red on no-match row host cell, got style='{style}'"

    def test_nomatch_row_has_no_star(self, drv, srv):
        """The no-match row does not contain ★."""
        _, row_text = self._get_host_cell_style(drv, self._nomatch_pid)
        assert '★' not in row_text, \
            f"Expected no ★ in no-match row, got: '{row_text}'"

    # ── Status cell is unaffected by match ─────────────────────────────────

    def test_match_row_status_cell_not_overridden_by_match_style(self, drv, srv):
        """The Status cell (third <td>) is NOT overridden with match-red.
        It should retain its proc-finished / proc-running class coloring."""
        row = drv.find_element(
            By.CSS_SELECTOR,
            f'#tool-hosts-body tr[data-process-id="{self._match_pid}"]')
        tds = row.find_elements(By.TAG_NAME, 'td')
        status_style = tds[2].get_attribute('style') or ''
        # The status cell must not have an inline color override from match styling
        assert not self._has_red(status_style), \
            f"Status cell should not be red-overridden, got style='{status_style}'"
