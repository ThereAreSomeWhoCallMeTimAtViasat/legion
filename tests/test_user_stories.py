"""
User Story Tests — Selenium-driven, non-hollow.
================================================
Runs against a REAL legion.py server already running on PORT 5085.

Start before running:
    sudo python3 legion.py --web --port 5085 &

Then seed with a host (done once by the session fixture below).

Run:
    sudo python3 -m pytest tests/test_user_stories.py -v
"""

import os
import sys
import time
import tempfile
import json
import urllib.request

import pytest
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

PORT     = 5085
BASE_URL = f"http://127.0.0.1:{PORT}"

SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <hostnames><hostname name="testhost.local" type="PTR"/></hostnames>
    <os><osmatch name="Linux 4.x" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.4"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4.51"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def W(driver, timeout=8):
    return WebDriverWait(driver, timeout)


def wait_visible(driver, css, timeout=8):
    return W(driver, timeout).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, css)))


def wait_clickable(driver, css, timeout=8):
    return W(driver, timeout).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, css)))


def js(driver, script, *args):
    return driver.execute_script(script, *args)


def open_add_hosts_modal(driver):
    """Open the Add Hosts modal and return the textarea element.

    #action-add-hosts lives inside the collapsed File dropdown so it has
    zero size and fails element_to_be_clickable.  JS click bypasses that,
    exactly as the existing test_selenium_ui.py tests do (line 373).
    """
    driver.execute_script("document.getElementById('action-add-hosts').click()")
    W(driver, 5).until(
        lambda d: 'is-open' in (d.find_element(By.ID, 'add-hosts-modal')
                                  .get_attribute('class') or ''))
    return driver.find_element(By.ID, 'add-hosts-targets')


def close_add_hosts_modal(driver):
    try:
        driver.find_element(By.CSS_SELECTOR, '#add-hosts-modal .modal-close-btn').click()
        time.sleep(0.3)
    except Exception:
        pass


def api(method, path, **kwargs):
    """Thin wrapper for requests against the test server."""
    return getattr(requests, method)(BASE_URL + path, **kwargs)


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ensure_server():
    """Verify the server is reachable. Fail fast with a clear message."""
    try:
        r = requests.get(f"{BASE_URL}/api/snapshot", timeout=5)
        assert r.status_code == 200, f"Snapshot returned {r.status_code}"
    except Exception as e:
        pytest.fail(
            f"Legion server not reachable at {BASE_URL}.\n"
            f"Start it first:  sudo python3 legion.py --web --port {PORT} &\n"
            f"Error: {e}"
        )


@pytest.fixture(scope="session")
def seed_host(ensure_server):
    """Ensure 10.10.10.1 is in the server's DB. Idempotent."""
    snap = requests.get(f"{BASE_URL}/api/snapshot").json()
    if not any(h['ip'] == '10.10.10.1' for h in snap.get('hosts', [])):
        with tempfile.NamedTemporaryFile(suffix='.xml', mode='w',
                                        delete=False) as f:
            f.write(SEED_XML)
            xml_path = f.name
        try:
            requests.post(f"{BASE_URL}/api/nmap/import-xml",
                          json={'path': xml_path}, timeout=10)
            time.sleep(1)
        finally:
            os.unlink(xml_path)
    snap = requests.get(f"{BASE_URL}/api/snapshot").json()
    assert any(h['ip'] == '10.10.10.1' for h in snap.get('hosts', [])), \
        "Seed host 10.10.10.1 not found after import"
    return '10.10.10.1'


@pytest.fixture(scope="session")
def driver(ensure_server):
    """Headless Firefox, session-scoped."""
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)

    opts = webdriver.FirefoxOptions()
    opts.add_argument("--headless")
    svc = Service(executable_path='/usr/bin/geckodriver')
    d = webdriver.Firefox(service=svc, options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.get(BASE_URL)
    time.sleep(2)   # let initial snapshot poll render
    yield d
    d.quit()


@pytest.fixture(autouse=True)
def reset_state(driver):
    """Reset UI to a known baseline before each test."""
    try:
        driver.find_element(By.TAG_NAME, 'body').click()
        time.sleep(0.1)
        # Dismiss any open modal
        for mid in ['add-hosts-modal', 'config-modal', 'help-modal',
                    'filters-modal', 'import-nmap-modal']:
            try:
                el = driver.find_element(By.ID, mid)
                if 'is-open' in (el.get_attribute('class') or ''):
                    driver.find_element(
                        By.CSS_SELECTOR, f'#{mid} .modal-close-btn').click()
                    time.sleep(0.2)
            except Exception:
                pass
        # Dismiss any browser alert
        try:
            driver.switch_to.alert.dismiss()
        except Exception:
            pass
    except Exception:
        pass
    yield


# ===========================================================================
# TEST 1 — US-04: Invalid input shows validation error and starts no scan
# ===========================================================================

class TestUS04_InvalidHostInput:
    """
    US-04: The server rejects targets that contain characters outside the
    allowed set [a-zA-Z0-9:./-\s,].  The observable outcome is that
    NO scan process is created in the DB.

    Note on UI validation: the JS only shows #add-hosts-validation for
    the EMPTY-input case.  For non-empty invalid chars, postJson() does
    not inspect r.ok, so the modal closes regardless — but the server
    has already rejected the request and created no process.  Both
    behaviours are verified here.
    """

    def test_empty_input_shows_js_validation_error(self, driver, seed_host):
        """Submitting empty input triggers the JS-side validation element
        (#add-hosts-validation) to become visible — the modal stays open."""
        textarea = open_add_hosts_modal(driver)
        textarea.clear()

        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(0.4)

        validation = driver.find_element(By.ID, 'add-hosts-validation')
        assert validation.is_displayed(), \
            "#add-hosts-validation must be visible after empty submission"

        modal = driver.find_element(By.ID, 'add-hosts-modal')
        assert 'is-open' in (modal.get_attribute('class') or ''), \
            "Modal must stay open when input is empty"

        close_add_hosts_modal(driver)

    def test_pipe_char_creates_no_process(self, driver, seed_host):
        """'192.168.1.1|ls' — pipe rejected by server; no process created."""
        proc_before = len(api('get', '/api/snapshot').json().get('processes', []))

        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        textarea.send_keys('192.168.1.1|ls')
        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(2.5)   # postJson round-trip + snapshot poll

        proc_after = len(api('get', '/api/snapshot').json().get('processes', []))
        assert proc_after == proc_before, (
            f"A process was created despite invalid input '192.168.1.1|ls': "
            f"before={proc_before} after={proc_after}"
        )

    def test_backtick_char_creates_no_process(self, driver, seed_host):
        """Backtick is not an allowed nmap target character; server rejects it."""
        proc_before = len(api('get', '/api/snapshot').json().get('processes', []))

        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        textarea.send_keys('192.168.1.1;`id`')
        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(2.5)

        proc_after = len(api('get', '/api/snapshot').json().get('processes', []))
        assert proc_after == proc_before, (
            f"A process was created despite backtick in input: "
            f"before={proc_before} after={proc_after}"
        )

    def test_valid_ip_creates_process(self, driver, seed_host):
        """A valid IP is accepted and results in a new scan process."""
        proc_before = len(api('get', '/api/snapshot').json().get('processes', []))

        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        textarea.send_keys('127.0.0.2')
        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(3.5)   # postJson + modal close (1.5 s) + snapshot poll

        proc_after = len(api('get', '/api/snapshot').json().get('processes', []))
        assert proc_after > proc_before, (
            f"No new process after valid IP '127.0.0.2': "
            f"before={proc_before} after={proc_after}"
        )


# ===========================================================================
# TEST — US-03: nmap comma-range syntax is accepted and starts a scan
# ===========================================================================

class TestUS03_CommaRangeSyntax:
    """
    US-03: '192.168.1.1,2' is valid nmap target syntax that expands to
    192.168.1.1 and 192.168.1.2 in a single nmap invocation.
    The Add Hosts dialog must accept it without a validation error and
    the server must create at least one scan process.

    validateNmapInput allows [a-zA-Z0-9:./-\\s,] — comma is in the set.
    The split in routes.py uses [\\n;]+ so the comma stays intact and
    is handed to nmap as-is.
    """

    def test_comma_range_passes_validation(self, driver, seed_host):
        """The JS validation element must NOT appear for '192.168.1.1,2'."""
        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        textarea.send_keys('192.168.1.1,2')
        time.sleep(0.2)

        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(0.5)

        # Validation error must be hidden (JS only shows it for empty input)
        validation = driver.find_element(By.ID, 'add-hosts-validation')
        assert not validation.is_displayed(), (
            "#add-hosts-validation is visible — comma range was incorrectly "
            "treated as invalid input by the JS guard"
        )

    def test_comma_range_creates_scan_process(self, driver, seed_host):
        """Submitting '192.168.1.1,2' must create at least one nmap process."""
        proc_before = len(api('get', '/api/snapshot').json().get('processes', []))

        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        textarea.send_keys('192.168.1.1,2')

        driver.find_element(By.ID, 'add-hosts-start').click()
        # Wait for server round-trip + modal close (1.5 s) + snapshot poll
        time.sleep(4.0)

        proc_after = len(api('get', '/api/snapshot').json().get('processes', []))
        assert proc_after > proc_before, (
            f"No scan process created for '192.168.1.1,2': "
            f"before={proc_before} after={proc_after}"
        )

    def test_comma_range_server_accepts_not_rejects(self, driver, seed_host):
        """Direct API call confirms the server returns 200 not 400 for comma range."""
        resp = api('post', '/api/nmap/scan', json={
            'targets': '192.168.1.1,2',
            'scan_mode': 'Easy',
            'discovery': True,
            'staged': True,
            'timing': '4',
            'nmap_options': ['-n'],
            'enable_ipv6': False,
        })
        data = resp.json()
        assert resp.status_code == 200, (
            f"Server rejected '192.168.1.1,2' with {resp.status_code}: {data}"
        )
        assert data.get('status') != 'error', (
            f"Server returned error for comma-range target: {data}"
        )


# ===========================================================================
# TEST — US-02: Semicolons create two independent parallel scan processes
# ===========================================================================

class TestUS02_SemicolonSeparator:
    """
    US-02: Entering 'host1; host2' in the Add Hosts dialog must create two
    separate nmap processes — one per host — running in parallel.

    routes.py splits on [\\n;]+ so each semicolon-separated token becomes
    an independent call to wc.addHosts() → runStagedNmap().
    """

    def test_two_hosts_create_two_process_groups(self, driver, seed_host):
        """Submitting '127.0.0.1; 127.0.0.2' must produce at least 2 new
        processes, one targeting each host."""
        snap_before  = api('get', '/api/snapshot').json()
        procs_before = {p['id'] for p in snap_before.get('processes', [])}

        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        textarea.send_keys('127.0.0.1; 127.0.0.2')
        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(5.0)   # two staged scans launching + snapshot poll

        snap_after  = api('get', '/api/snapshot').json()
        new_procs   = [p for p in snap_after.get('processes', [])
                       if p['id'] not in procs_before]

        assert len(new_procs) >= 2, (
            f"Expected ≥2 new processes for '127.0.0.1; 127.0.0.2', "
            f"got {len(new_procs)}: {new_procs}"
        )

        host_ips = {p.get('hostIp', '') for p in new_procs}
        assert '127.0.0.1' in host_ips, \
            f"No process for 127.0.0.1 — got host IPs: {host_ips}"
        assert '127.0.0.2' in host_ips, \
            f"No process for 127.0.0.2 — got host IPs: {host_ips}"

    def test_semicolons_not_treated_as_injection(self, driver, seed_host):
        """The semicolon is treated as a separator, not a shell injection char.
        Each resulting token is validated by validateNmapInput individually.
        '127.0.0.1; 127.0.0.2' produces two valid tokens — both accepted."""
        resp = api('post', '/api/nmap/scan', json={
            'targets': '127.0.0.1; 127.0.0.2',
            'scan_mode': 'Easy',
            'discovery': True,
            'staged': True,
            'timing': '4',
            'nmap_options': ['-n'],
            'enable_ipv6': False,
        })
        assert resp.status_code == 200, \
            f"Server rejected valid semicolon-separated targets: {resp.json()}"
        assert resp.json().get('status') != 'error', \
            f"Server returned error for semicolon-separated targets: {resp.json()}"

    def test_newline_separator_also_creates_two_processes(self, driver, seed_host):
        """Newline is an equivalent separator to semicolon — both produce
        independent processes per host."""
        snap_before  = api('get', '/api/snapshot').json()
        procs_before = {p['id'] for p in snap_before.get('processes', [])}

        textarea = open_add_hosts_modal(driver)
        textarea.clear()
        # Send_keys with \n inserts a newline in the textarea
        textarea.send_keys('127.0.0.3\n127.0.0.4')
        driver.find_element(By.ID, 'add-hosts-start').click()
        time.sleep(5.0)

        snap_after = api('get', '/api/snapshot').json()
        new_procs  = [p for p in snap_after.get('processes', [])
                      if p['id'] not in procs_before]

        assert len(new_procs) >= 2, (
            f"Expected ≥2 new processes for newline-separated hosts, "
            f"got {len(new_procs)}"
        )
        host_ips = {p.get('hostIp', '') for p in new_procs}
        assert '127.0.0.3' in host_ips, \
            f"No process for 127.0.0.3 — got: {host_ips}"
        assert '127.0.0.4' in host_ips, \
            f"No process for 127.0.0.4 — got: {host_ips}"


# ===========================================================================
# HELPERS shared by Ctrl+B tests
# ===========================================================================

def _post(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())


def _get_host_id(host_ip):
    """Return the integer hostId for the given IP from /api/snapshot."""
    snap = requests.get(f'{BASE_URL}/api/snapshot').json()
    for h in snap.get('hosts', []):
        if h.get('ip') == host_ip:
            return h.get('id')
    return None


def _clear_notes(host_id):
    """Wipe notes for host_id so Ctrl+B tests start clean."""
    _post(f'{BASE_URL}/api/workspace/hosts/{host_id}/note', {'note': ''})


def _start_terminal(host_ip, label='ctrlb-test'):
    """Start a terminal session and return (process_id, session_id)."""
    resp = _post(f'{BASE_URL}/api/terminal/start',
                 {'label': label, 'host_ip': host_ip, 'command': None})
    return resp['process_id'], resp['session_id']


def _send_input(session_id, text):
    """Send keystrokes to the running terminal session."""
    _post(f'{BASE_URL}/api/terminal/{session_id}/input', {'data': text})


def _click_interactive_row(driver, process_id, timeout=10):
    """Click the process row for process_id so xterm mounts in lower panel.
    We find the element with Selenium (safe CSS) then click via JS to avoid
    scroll-into-view issues — no string interpolation in JS needed."""
    css = f'#processes-body tr[data-process-id="{process_id}"]'
    W(driver, timeout).until(lambda d: d.find_elements(By.CSS_SELECTOR, css))
    row = driver.find_element(By.CSS_SELECTOR, css)
    driver.execute_script('arguments[0].scrollIntoView({block:"center"}); arguments[0].click()', row)
    time.sleep(2.0)  # xterm needs time to mount and render


def _xterm_loaded(driver):
    """True when _termState.xterm is mounted and has content."""
    return driver.execute_script(
        "return typeof _termState !== 'undefined' "
        "    && _termState.xterm !== null "
        "    && _termState.xterm.buffer.active.length > 0")


def _wait_for_marker(driver, marker, timeout=15):
    """Poll xterm buffer until 'marker' text appears. Return True if found."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = driver.execute_script("""
            var marker = arguments[0];
            if (typeof _termState === 'undefined' || !_termState.xterm) return false;
            var buf = _termState.xterm.buffer.active;
            for (var i = 0; i < buf.length; i++) {
                var ln = buf.getLine(i);
                if (ln && ln.translateToString(true).indexOf(marker) >= 0) return true;
            }
            return false;
        """, marker)
        if found:
            return True
        time.sleep(0.5)
    return False


def _select_marker_in_buffer(driver, marker):
    """Find 'marker' in the xterm buffer and select exactly that text.
    Returns the selected text from xterm.getSelection(), or '' if not found."""
    result = driver.execute_script("""
        var marker = arguments[0];
        var buf = _termState.xterm.buffer.active;
        for (var i = 0; i < buf.length; i++) {
            var ln = buf.getLine(i);
            if (!ln) continue;
            var text = ln.translateToString(true);
            var col = text.indexOf(marker);
            if (col >= 0) {
                _termState.xterm.select(col, i, marker.length);
                return _termState.xterm.getSelection();
            }
        }
        return '';
    """, marker)
    return result or ''


def _select_markers_range(driver, start_marker, end_marker):
    """Select from the start of start_marker to the end of end_marker
    across multiple rows.  Returns xterm.getSelection()."""
    result = driver.execute_script("""
        var startM = arguments[0], endM = arguments[1];
        var buf = _termState.xterm.buffer.active;
        var startRow = -1, startCol = -1, endRow = -1, endCol = -1;
        for (var i = 0; i < buf.length; i++) {
            var ln = buf.getLine(i);
            if (!ln) continue;
            var text = ln.translateToString(true);
            if (startRow < 0) {
                var c = text.indexOf(startM);
                if (c >= 0) { startRow = i; startCol = c; }
            }
            var c2 = text.indexOf(endM);
            if (c2 >= 0) { endRow = i; endCol = c2 + endM.length; }
        }
        if (startRow < 0 || endRow < 0) return '';
        /* length = chars from startCol on startRow to endCol on endRow.
           Each row is terminal.cols wide. */
        var cols = _termState.xterm.cols;
        var length = (endRow - startRow) * cols - startCol + endCol;
        _termState.xterm.select(startCol, startRow, length);
        return _termState.xterm.getSelection();
    """, start_marker, end_marker)
    return result or ''


def _ctrlb(driver):
    """Send Ctrl+B via ActionChains — isTrusted=true, goes through xterm capture."""
    textarea = None
    for sel in ['#terminal-output .xterm-helper-textarea',
                '#terminal-output textarea']:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            textarea = els[0]
            break
    assert textarea, 'xterm-helper-textarea not found — terminal not mounted'

    # JS focus preserves the selection; a click would clear it
    driver.execute_script('arguments[0].focus()', textarea)
    time.sleep(0.1)

    # Confirm selection still set after focus
    sel_after_focus = driver.execute_script(
        "return _termState.xterm.getSelection() || ''")
    assert sel_after_focus.strip(), \
        'xterm selection was cleared by .focus() — cannot proceed'

    ActionChains(driver).key_down(Keys.CONTROL).send_keys('b') \
                        .key_up(Keys.CONTROL).perform()
    time.sleep(1.2)  # sendSelectionToNotes posts to DB async


def _parse_notes_body(notes_raw, marker):
    """Extract the text block added by the LAST Ctrl+B call that contains marker.

    Format inserted by sendSelectionToNotes():
        '=== Selection from <title> ===\\n<text>\\n\\n'

    We find the LAST occurrence so each test is isolated even if notes
    accumulates across tests in the same host.
    """
    header_prefix = '=== Selection from '
    # Split on the header prefix and take the last block that contains marker
    blocks = notes_raw.split(header_prefix)
    for block in reversed(blocks):
        if not block.strip():
            continue
        # block starts with title, then '\n', then text, then '\n\n'
        newline = block.find('\n')
        if newline < 0:
            continue
        body = block[newline + 1:].rstrip('\n').rstrip()
        if marker in body:
            return body
    # Fallback: return everything after the last header line
    if header_prefix in notes_raw:
        last = notes_raw.rfind(header_prefix)
        after = notes_raw[last:]
        newline = after.find('\n')
        if newline >= 0:
            return after[newline + 1:].rstrip('\n').rstrip()
    return notes_raw.strip()


# ===========================================================================
# TEST 2 — US-34 Ctrl+B: exact text match — single line and multi-line
# ===========================================================================

class TestUS34_CtrlBExactTextMatch:
    """
    US-34: Text selected in an xterm.js terminal tab and copied to the Notes
    panel via Ctrl+B must be IDENTICAL to what xterm.getSelection() reported
    at the moment Ctrl+B was pressed.

    Two scenarios:
      2a — Single line:  select exactly one output line in the terminal buffer,
                         verify notes body == that line (no more, no less).
      2b — Multi-line:   select output spanning three lines,
                         verify notes body == that three-line selection.

    Skipped if xterm.js CDN cannot be loaded in headless Firefox.
    """

    HOST_IP = '10.10.10.1'

    # ── shared setup ────────────────────────────────────────────────────────

    def _setup(self, driver, seed_host, label, commands):
        """Start terminal, send commands, click the row, wait for xterm.
        Returns (session_id, host_id) or calls pytest.skip if xterm fails."""

        host_id = _get_host_id(self.HOST_IP)
        assert host_id, f'{self.HOST_IP} not in snapshot'
        _clear_notes(host_id)

        # Select the host row so the right panel is active for this host
        driver.execute_script("""
            var row = document.querySelector(
                '#hosts-body tr[data-host-ip="' + arguments[0] + '"]');
            if (row) row.click();
        """, self.HOST_IP)
        time.sleep(1.0)

        proc_id, session_id = _start_terminal(self.HOST_IP, label=label)
        time.sleep(1.5)  # PTY startup

        for cmd in commands:
            _send_input(session_id, cmd)
            time.sleep(0.8)

        _click_interactive_row(driver, proc_id)

        if not W(driver, 10).until(lambda d: _xterm_loaded(d)):
            pytest.skip('xterm.js not loaded (CDN unreachable in headless)')

        return session_id, host_id

    # ── Test 2a: single line ─────────────────────────────────────────────────

    def test_single_line_selection_matches_notes(self, driver, seed_host):
        """
        Single-line Ctrl+B:
          1. Start a terminal and echo a unique marker string.
          2. Locate that exact string in the xterm buffer and select it
             (and only it) using terminal.select(col, row, len).
          3. Record xterm.getSelection() — this is the ground truth.
          4. Press Ctrl+B via ActionChains (isTrusted=true keyboard event).
          5. Read #notes-text and parse out the body after the header line.
          6. Assert body.strip() == selection.strip().
        """
        MARKER = 'CTRLB_SINGLE_LINE_EXACT_9a3f'

        _, host_id = self._setup(
            driver, seed_host, label='ctrlb-single',
            commands=[f'echo {MARKER}\n'])

        # Wait for the marker to appear in the xterm buffer
        assert _wait_for_marker(driver, MARKER), \
            f'Marker {MARKER!r} never appeared in xterm buffer'

        # Select exactly the marker text in the buffer
        selection = _select_marker_in_buffer(driver, MARKER)
        assert selection.strip() == MARKER, (
            f'select() did not return the expected marker.\n'
            f'  Expected: {MARKER!r}\n'
            f'  Got:      {selection!r}')

        _ctrlb(driver)

        notes_raw = driver.execute_script(
            "return document.getElementById('notes-text').value") or ''
        assert notes_raw.strip(), 'Notes textarea is empty after Ctrl+B'

        body = _parse_notes_body(notes_raw, MARKER)

        assert selection.strip() == body.strip(), (
            f'Single-line: notes body does not match xterm selection.\n'
            f'  xterm.getSelection(): {selection!r}\n'
            f'  Notes body:           {body!r}')

    # ── Test 2b: multi-line ──────────────────────────────────────────────────

    def test_multi_line_selection_matches_notes(self, driver, seed_host):
        """
        Multi-line Ctrl+B:
          1. Start a terminal and print three unique marker lines using printf.
          2. Locate the first and last markers in the xterm buffer and select
             the span from start_marker col to end_marker col+len.
          3. Record xterm.getSelection() — ground truth.
          4. Press Ctrl+B.
          5. Parse notes body.
          6. Assert:
               a. Notes body == selection (same text, same order).
               b. All three line markers are present in notes body.
        """
        LINE_A = 'CTRLB_MULTI_LINE_A_7c2e'
        LINE_B = 'CTRLB_MULTI_LINE_B_7c2e'
        LINE_C = 'CTRLB_MULTI_LINE_C_7c2e'

        _, host_id = self._setup(
            driver, seed_host, label='ctrlb-multi',
            commands=[f'printf "{LINE_A}\\n{LINE_B}\\n{LINE_C}\\n"\n'])

        # Wait until all three markers are in the xterm buffer
        for marker in (LINE_A, LINE_B, LINE_C):
            assert _wait_for_marker(driver, marker, timeout=15), \
                f'Marker {marker!r} never appeared in xterm buffer'

        # Select from start of LINE_A to end of LINE_C (spanning all three)
        selection = _select_markers_range(driver, LINE_A, LINE_C)
        assert selection.strip(), 'Multi-line selection returned empty string'

        # All three markers must be inside the selection
        for marker in (LINE_A, LINE_B, LINE_C):
            assert marker in selection, (
                f'{marker!r} not in xterm selection: {selection!r}')

        _ctrlb(driver)

        notes_raw = driver.execute_script(
            "return document.getElementById('notes-text').value") or ''
        assert notes_raw.strip(), 'Notes textarea is empty after Ctrl+B'

        body = _parse_notes_body(notes_raw, LINE_A)

        # Core assertion: notes body == what xterm reported as selected
        assert selection.strip() == body.strip(), (
            f'Multi-line: notes body does not match xterm selection.\n'
            f'  xterm.getSelection() ({len(selection)} chars):\n'
            f'    {selection!r}\n'
            f'  Notes body ({len(body)} chars):\n'
            f'    {body!r}')

        # Belt-and-suspenders: every marker individually present in notes
        for marker in (LINE_A, LINE_B, LINE_C):
            assert marker in body, (
                f'{marker!r} missing from notes body.\n'
                f'  Notes body: {body!r}')
