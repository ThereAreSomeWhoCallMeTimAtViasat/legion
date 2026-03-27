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
from selenium.common.exceptions import StaleElementReferenceException

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
# GROUP 3 — Log Tab (US-40, US-41, US-42)
# ===========================================================================

def _open_log_tab(driver):
    """Click the Log tab button in #bottom-tab-bar and wait for content."""
    btn = driver.find_element(
        By.CSS_SELECTOR, '#bottom-tab-bar [data-tab="log-panel"]')
    driver.execute_script('arguments[0].click()', btn)
    # loadLog() fires a fetchJson and populates #log-output async
    W(driver, 8).until(lambda d: bool(
        d.find_element(By.ID, 'log-output').get_attribute('innerHTML').strip()))


def _log_total(level='INFO'):
    """Return total (untruncated) line count from the API for given level."""
    return api('get', f'/api/logs?level={level}').json().get('total', 0)


def _log_line_count_text(driver):
    """Read the '123 lines' span next to the log level selector."""
    return driver.find_element(By.ID, 'log-line-count').text.strip()


# ---------------------------------------------------------------------------
# US-40: Log tab shows server log output (non-empty)
# ---------------------------------------------------------------------------

class TestUS40_LogTabNonEmpty:
    """
    US-40: The Log tab must display application log lines captured in the
    in-memory buffer — without requiring stdout redirection.

    Verifies:
      - Clicking the Log tab populates #log-output with content.
      - #log-line-count shows 'N lines' where N > 0.
      - The API /api/logs returns lines (not empty).
    """

    def test_log_tab_output_is_non_empty(self, driver, seed_host):
        """After clicking the Log tab, #log-output must have content."""
        _open_log_tab(driver)
        html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
        assert html.strip(), \
            '#log-output is empty after clicking Log tab'

    def test_log_line_count_shows_positive_number(self, driver, seed_host):
        """#log-line-count must display 'N lines' with N > 0."""
        _open_log_tab(driver)
        text = _log_line_count_text(driver)
        assert 'lines' in text, \
            f'#log-line-count does not contain "lines": {text!r}'
        count = int(text.split()[0])
        assert count > 0, \
            f'#log-line-count shows 0 lines: {text!r}'

    def test_api_returns_log_lines(self, driver, seed_host):
        """Direct API call must return at least one log line."""
        total = _log_total('INFO')
        assert total > 0, \
            f'/api/logs?level=INFO returned total={total}'


# ---------------------------------------------------------------------------
# US-41: Log level INFO→DEBUG increases line count
# ---------------------------------------------------------------------------

class TestUS41_LogLevelFilter:
    """
    US-41: Switching the log level selector from INFO to DEBUG (all) must
    show more lines because DEBUG includes snapshot/queue entries that are
    filtered out at INFO.

    The displayed count is capped at 500, so we compare the API 'total'
    field which reflects the un-truncated counts.  The UI content also
    changes (different last-500 set).
    """

    def test_debug_total_greater_than_info_total(self, driver, seed_host):
        """API total at DEBUG must be greater than at INFO."""
        info_total  = _log_total('INFO')
        debug_total = _log_total('DEBUG')
        assert debug_total > info_total, (
            f'DEBUG total ({debug_total}) is not greater than '
            f'INFO total ({info_total}). '
            f'Snapshot/queue DEBUG lines should outnumber INFO-only lines.'
        )

    def test_switching_to_debug_changes_log_output(self, driver, seed_host):
        """Selecting DEBUG in the UI causes #log-output content to change."""
        _open_log_tab(driver)
        time.sleep(1.0)

        # Capture INFO content
        info_html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
        assert info_html.strip(), 'INFO log output is empty before level switch'

        # Switch to DEBUG via the select element
        from selenium.webdriver.support.ui import Select
        Select(driver.find_element(By.ID, 'log-level')).select_by_value('DEBUG')
        time.sleep(2.5)   # fetchJson round-trip + render

        debug_html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
        assert debug_html.strip(), 'DEBUG log output is empty after level switch'

        assert info_html != debug_html, (
            'Log output did not change after switching from INFO to DEBUG. '
            'DEBUG last-500 lines should differ from INFO last-500 lines.'
        )

    def test_log_line_count_text_present_after_switch(self, driver, seed_host):
        """After switching to DEBUG the line count span is still populated."""
        _open_log_tab(driver)
        time.sleep(0.5)
        from selenium.webdriver.support.ui import Select
        Select(driver.find_element(By.ID, 'log-level')).select_by_value('DEBUG')
        time.sleep(2.0)
        text = _log_line_count_text(driver)
        assert 'lines' in text and int(text.split()[0]) > 0, \
            f'#log-line-count empty or zero after DEBUG switch: {text!r}'


# ---------------------------------------------------------------------------
# US-42: Log tab renders ANSI codes as coloured spans, not raw escape codes
# ---------------------------------------------------------------------------

class TestUS42_LogAnsiColor:
    """
    US-42: Log lines from the in-memory handler contain ANSI escape sequences.
    ansiToHtml() must convert them to <span class="ansi-fg-..."> elements.

    Verifies:
      - #log-output innerHTML contains <span elements.
      - #log-output innerHTML does NOT contain raw \\x1b[ sequences.
      - At least one ansi-fg-* or ansi-bold class is present.
    """

    def test_log_output_contains_spans(self, driver, seed_host):
        """#log-output must have <span elements (ANSI converted to HTML)."""
        _open_log_tab(driver)
        html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
        assert '<span' in html, (
            '#log-output has no <span elements — ANSI codes may not have been '
            'converted by ansiToHtml()'
        )

    def test_log_output_has_no_raw_ansi_codes(self, driver, seed_host):
        """#log-output must not contain raw \\x1b[ escape sequences."""
        _open_log_tab(driver)
        # Read via JS to get the exact innerHTML bytes
        html = driver.execute_script(
            "return document.getElementById('log-output').innerHTML")
        assert '\x1b[' not in html, (
            '#log-output contains raw ANSI escape sequences — '
            'ansiToHtml() did not convert them'
        )
        assert 'ESC[' not in html, \
            '#log-output contains literal ESC[ strings'

    def test_log_output_has_ansi_colour_classes(self, driver, seed_host):
        """#log-output must contain CSS classes produced by ansiToHtml():
        ansi-fg-* (foreground colour) and/or ansi-bold."""
        _open_log_tab(driver)
        html = driver.execute_script(
            "return document.getElementById('log-output').innerHTML")

        has_fg    = 'ansi-fg-'  in html
        has_bold  = 'ansi-bold' in html
        assert has_fg or has_bold, (
            f'No ansi-fg-* or ansi-bold classes in log output. '
            f'Log lines have ANSI codes but ansiToHtml() may not be converting them. '
            f'innerHTML snippet: {html[:200]!r}'
        )


# ===========================================================================
# GROUP 7 — Multi-Instance Isolation (US-55)
# ===========================================================================

PORT_A = 5085   # primary test server
PORT_B = 5086   # second instance

# Unique IPs used only by these tests — chosen to not clash with seed data
IP_A = '10.55.85.1'   # imported into instance A only
IP_B = '10.55.86.1'   # imported into instance B only

_SEED_XML_A = f"""<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{IP_A}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="80">
      <state state="open"/><service name="http"/>
    </port></ports>
  </host>
</nmaprun>"""

_SEED_XML_B = f"""<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{IP_B}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="443">
      <state state="open"/><service name="https"/>
    </port></ports>
  </host>
</nmaprun>"""


def _import_xml_to(port, xml):
    """Import XML into the instance at port. Uses /tmp since both servers run as root."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml)
        path = f.name
    try:
        resp = requests.post(f'http://127.0.0.1:{port}/api/nmap/import-xml',
                             json={'path': path}, timeout=20)
        return resp.json()
    finally:
        os.unlink(path)


def _hosts_at(port):
    """Return list of host IPs at the given port instance."""
    snap = requests.get(f'http://127.0.0.1:{port}/api/snapshot', timeout=5).json()
    return [h['ip'] for h in snap.get('hosts', [])]


def _ui_host_ips(driver, url):
    """Navigate to url and return all data-host-ip values from the hosts table."""
    driver.get(url)
    time.sleep(2.5)   # let snapshot poll render
    return driver.execute_script("""
        return Array.from(
            document.querySelectorAll('#hosts-body tr[data-host-ip]')
        ).map(r => r.dataset.hostIp);
    """)


def _ensure_isolated_seed():
    """Import IP_A into A and IP_B into B if not already present."""
    if IP_A not in _hosts_at(PORT_A):
        _import_xml_to(PORT_A, _SEED_XML_A)
        time.sleep(1)
    if IP_B not in _hosts_at(PORT_B):
        _import_xml_to(PORT_B, _SEED_XML_B)
        time.sleep(1)


class TestUS55_TwoInstancesIndependent:
    """
    US-55: Two Legion instances running on different ports (5085, 5086) must
    have completely independent databases, hosts, and processes.

    Data imported into instance A must NOT appear in instance B's snapshot
    or UI, and vice versa.

    Uses one Selenium driver that navigates between the two server URLs —
    the hosts table is read from the DOM (#hosts-body tr[data-host-ip])
    at each URL to verify isolation both at API and UI level.

    Requires BOTH servers to be running:
        sudo python3 legion.py --web --port 5085 &
        sudo python3 legion.py --web --port 5086 &
    """

    @pytest.fixture(autouse=True)
    def _seed(self):
        """Ensure each instance has its unique host before the test runs."""
        _ensure_isolated_seed()

    def test_host_imported_to_a_not_visible_in_b_api(self, driver, seed_host):
        """API: IP_A in 5085 snapshot, NOT in 5086 snapshot."""
        hosts_a = _hosts_at(PORT_A)
        hosts_b = _hosts_at(PORT_B)
        assert IP_A in hosts_a, f'{IP_A} missing from 5085'
        assert IP_A not in hosts_b, (
            f'{IP_A} leaked from 5085 into 5086! hosts_b={hosts_b}')

    def test_host_imported_to_b_not_visible_in_a_api(self, driver, seed_host):
        """API: IP_B in 5086 snapshot, NOT in 5085 snapshot."""
        hosts_a = _hosts_at(PORT_A)
        hosts_b = _hosts_at(PORT_B)
        assert IP_B in hosts_b, f'{IP_B} missing from 5086'
        assert IP_B not in hosts_a, (
            f'{IP_B} leaked from 5086 into 5085! hosts_a={hosts_a}')

    def test_host_a_visible_in_ui_at_port_a(self, driver, seed_host):
        """Selenium: navigating to :5085 shows IP_A in the hosts table."""
        ips = _ui_host_ips(driver, f'http://127.0.0.1:{PORT_A}')
        assert IP_A in ips, (
            f'IP_A ({IP_A}) not in 5085 UI hosts table. Got: {ips}')

    def test_host_a_not_visible_in_ui_at_port_b(self, driver, seed_host):
        """Selenium: navigating to :5086 does NOT show IP_A in the hosts table."""
        ips = _ui_host_ips(driver, f'http://127.0.0.1:{PORT_B}')
        assert IP_A not in ips, (
            f'IP_A ({IP_A}) leaked into 5086 UI hosts table! Got: {ips}')

    def test_host_b_visible_in_ui_at_port_b(self, driver, seed_host):
        """Selenium: navigating to :5086 shows IP_B in the hosts table."""
        ips = _ui_host_ips(driver, f'http://127.0.0.1:{PORT_B}')
        assert IP_B in ips, (
            f'IP_B ({IP_B}) not in 5086 UI hosts table. Got: {ips}')

    def test_host_b_not_visible_in_ui_at_port_a(self, driver, seed_host):
        """Selenium: navigating to :5085 does NOT show IP_B in the hosts table."""
        ips = _ui_host_ips(driver, f'http://127.0.0.1:{PORT_A}')
        assert IP_B not in ips, (
            f'IP_B ({IP_B}) leaked into 5085 UI hosts table! Got: {ips}')

    def test_process_scan_on_a_not_in_b(self, driver, seed_host):
        """Scan submitted to 5085 creates a process in 5085 but not in 5086."""
        procs_b_before = len(
            requests.get(f'http://127.0.0.1:{PORT_B}/api/snapshot').json()
            .get('processes', []))

        # Submit a scan to A only
        resp = requests.post(f'http://127.0.0.1:{PORT_A}/api/nmap/scan', json={
            'targets': '127.0.0.1',
            'scan_mode': 'Easy', 'discovery': False, 'staged': False,
            'timing': '4', 'nmap_options': ['-n'], 'enable_ipv6': False,
        }, timeout=10)
        assert resp.status_code == 200, f'Scan submission to 5085 failed: {resp.json()}'

        time.sleep(2.5)   # snapshot poll

        procs_b_after = len(
            requests.get(f'http://127.0.0.1:{PORT_B}/api/snapshot').json()
            .get('processes', []))
        assert procs_b_after == procs_b_before, (
            f'Process count in 5086 changed after scan submitted to 5085: '
            f'before={procs_b_before} after={procs_b_after}. '
            f'Scan leaked between instances.')


# ===========================================================================
# GROUP 5 — Live Output (US-16, US-18)
# ===========================================================================

# Shared slow-process command:
# - python3, no 'bash'/'msfconsole' → NOT marked Interactive by runCommand
# - single-quoted so no escaping issues in the JSON payload
# - 0.35 s/line → 40 lines takes ~14 s of running time
_SLOW_CMD = (
    "python3 -c "
    "'import time; "
    "[(print(\"LINE_\"+str(i),flush=True),time.sleep(0.35)) for i in range(40)]'"
)
_HOST_IP = '10.10.10.1'


def _start_slow_process():
    """Start _SLOW_CMD via /api/processes/custom. Returns process_id."""
    resp = api('post', '/api/processes/custom', json={
        'command': _SLOW_CMD,
        'host_ip': _HOST_IP,
        'port': '',
        'protocol': 'tcp',
    })
    pid = resp.json().get('process_id')
    assert pid, f'No process_id from /api/processes/custom: {resp.json()}'
    return pid


def _kill_auto_tools():
    """Kill all running processes AND drain the fastProcessQueue entirely.

    Uses POST /api/processes/drain which calls wc.killRunningProcesses().
    This is the only reliable way to clear queue saturation:

      killRunningProcesses() kills active processes AND drains fastProcessQueue.
      Individual per-process kills DON'T drain the queue — each kill triggers
      checkProcessQueue() which immediately starts the next queued auto-tool,
      so the queue self-heals and the slow process never gets a slot.

    By the time US-16/US-18 run, all US-02/03 assertions have passed.
    The ongoing nmap stages and auto-tools are background noise.
    """
    api('post', '/api/processes/drain', json={})
    time.sleep(2)   # let the drain propagate before creating new processes


def _wait_for_running(pid, timeout=30):
    """Poll until process pid is Running. Should return quickly after _kill_auto_tools()."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        procs = api('get', '/api/snapshot').json().get('processes', [])
        for p in procs:
            if str(p.get('id')) == str(pid):
                status = p.get('status', '')
                if status == 'Running':
                    return True
                if status in ('Finished', 'Crashed', 'Killed'):
                    return False
        time.sleep(0.5)
    return False


def _select_host_and_process(driver, process_id, wait_for_rows=8):
    """Select the host row then click the given process row.
    Waits up to wait_for_rows seconds for the process row to appear."""
    # Select host row so the right panel activates
    driver.execute_script("""
        var row = document.querySelector('#hosts-body tr[data-host-ip="' + arguments[0] + '"]');
        if (row) row.click();
    """, _HOST_IP)
    time.sleep(0.8)

    # Wait for the process row to exist in the DOM
    css = f'#processes-body tr[data-process-id="{process_id}"]'
    W(driver, wait_for_rows).until(lambda d: d.find_elements(By.CSS_SELECTOR, css))

    # Click it to load output in #plain-output
    row = driver.find_element(By.CSS_SELECTOR, css)
    driver.execute_script(
        'arguments[0].scrollIntoView({block:"center"}); arguments[0].click()', row)
    time.sleep(1.5)   # one snapshot poll for output to load


def _plain_output_text(driver):
    """Return the current text content of #plain-output."""
    return driver.execute_script(
        "return document.getElementById('plain-output').innerText || ''")


def _plain_output_html_len(driver):
    """Return innerHTML length of #plain-output (includes HTML tags)."""
    return driver.execute_script(
        "return (document.getElementById('plain-output').innerHTML || '').length")


# ---------------------------------------------------------------------------
# US-16: Live output content grows while a process is Running
# ---------------------------------------------------------------------------

class TestUS16_LiveOutputGrows:
    """
    US-16: When a Running process is selected in the Processes tab, the
    output panel (#plain-output) must update with new lines as the tool
    produces them — without any manual refresh.

    The snapshot poll fires every 1.5 s and calls loadProcessOutput() for
    the selected process, which reads the .live_output temp file.
    """

    def test_output_text_grows_over_time(self, driver, seed_host):
        """#plain-output text is longer 3 s after first reading."""
        driver.execute_script("""
            var btn = document.querySelector('#bottom-tab-bar [data-tab="processes-panel"]');
            if (btn) btn.click();
        """)
        time.sleep(0.3)
        _kill_auto_tools()
        pid = _start_slow_process()
        _wait_for_running(pid)
        time.sleep(1.0)   # let a few lines accumulate after start

        _select_host_and_process(driver, pid)

        t0_text = _plain_output_text(driver)
        assert t0_text.strip(), \
            f'#plain-output is empty immediately after clicking process {pid}'

        time.sleep(3.5)   # ~2-3 more polls; ~10 more lines at 0.35 s/line

        t1_text = _plain_output_text(driver)
        assert len(t1_text) > len(t0_text), (
            f'Output did not grow after 3.5 s.\n'
            f'  T=0: {len(t0_text)} chars — {t0_text[:60]!r}\n'
            f'  T=3: {len(t1_text)} chars — {t1_text[:60]!r}'
        )

    def test_output_contains_expected_line_markers(self, driver, seed_host):
        """After 6 s of Running time the output contains multiple LINE_N markers."""
        driver.execute_script("""
            var btn = document.querySelector('#bottom-tab-bar [data-tab="processes-panel"]');
            if (btn) btn.click();
        """)
        time.sleep(0.3)
        _kill_auto_tools()
        pid = _start_slow_process()
        _wait_for_running(pid)
        time.sleep(6.0)   # ~17 lines produced (0.35 s/line × 17 ≈ 6 s)

        _select_host_and_process(driver, pid)
        time.sleep(1.5)

        text = _plain_output_text(driver)
        # Count how many LINE_N markers are present
        count = sum(1 for ln in text.splitlines() if ln.strip().startswith('LINE_'))
        assert count >= 5, (
            f'Expected ≥5 LINE_N markers in output after 6 s, got {count}.\n'
            f'  Output: {text[:200]!r}'
        )

    def test_status_shows_running_while_output_live(self, driver, seed_host):
        """Process row status column must show Running while output is active."""
        driver.execute_script("""
            var btn = document.querySelector('#bottom-tab-bar [data-tab="processes-panel"]');
            if (btn) btn.click();
        """)
        time.sleep(0.3)
        _kill_auto_tools()
        pid = _start_slow_process()
        _wait_for_running(pid)
        time.sleep(0.5)   # brief pause after start

        _select_host_and_process(driver, pid)

        status = driver.execute_script("""
            var row = document.querySelector(
                '#processes-body tr[data-process-id="' + arguments[0] + '"]');
            if (!row) return 'NOT FOUND';
            var cells = row.querySelectorAll('td');
            return cells.length >= 5 ? cells[4].textContent.trim() : 'NO STATUS CELL';
        """, str(pid))
        assert status == 'Running', (
            f'Process {pid} status should be Running while outputting, got: {status!r}'
        )


# ---------------------------------------------------------------------------
# US-18: Auto-scroll stays at bottom when user is at bottom
# ---------------------------------------------------------------------------

class TestUS18_AutoScrollAtBottom:
    """
    US-18: When the user is scrolled to the bottom of a Running process's
    output, new lines arriving via the snapshot poll must keep the view
    at the bottom — the panel auto-scrolls to follow new content.

    loadProcessOutput() reads atBottom = (scrollHeight - scrollTop -
    clientHeight < 40) BEFORE each fetch.  After the innerHTML update it
    sets scrollTop = scrollHeight if atBottom was true.
    """

    def test_panel_stays_at_bottom_across_polls(self, driver, seed_host):
        """After clicking a Running process from the bottom, the panel
        remains at the bottom (gap < 40 px) across two more polls."""
        # Ensure Processes bottom tab is active — Log tab tests leave the
        # bottom section showing the Log panel, making #plain-output zero-height.
        driver.execute_script("""
            var btn = document.querySelector('#bottom-tab-bar [data-tab="processes-panel"]');
            if (btn) btn.click();
        """)
        time.sleep(0.3)

        _kill_auto_tools()
        pid = _start_slow_process()
        _wait_for_running(pid)
        # Wait for enough lines to make the panel scrollable
        time.sleep(10.0)   # ~28 lines × 18 px ≈ 500 px — should overflow panel

        _select_host_and_process(driver, pid)
        time.sleep(1.5)   # let first load settle

        # Confirm the panel is actually scrollable
        scrollable = driver.execute_script("""
            var el = document.getElementById('plain-output');
            return el.scrollHeight > el.clientHeight;
        """)
        if not scrollable:
            # Not enough content yet — wait another cycle
            time.sleep(3.0)
            scrollable = driver.execute_script("""
                var el = document.getElementById('plain-output');
                return el.scrollHeight > el.clientHeight;
            """)

        assert scrollable, (
            '#plain-output is not scrollable — not enough content to test auto-scroll'
        )

        # Explicitly scroll to the bottom (simulates user being at bottom)
        driver.execute_script("""
            var el = document.getElementById('plain-output');
            el.scrollTop = el.scrollHeight;
        """)
        time.sleep(0.1)

        # Record the gap at the bottom (should be ~0)
        gap0 = driver.execute_script("""
            var el = document.getElementById('plain-output');
            return el.scrollHeight - el.scrollTop - el.clientHeight;
        """)
        assert gap0 < 40, f'Scroll not at bottom before poll: gap={gap0}'

        # Wait for 2 more polls (~3 s) — each poll must keep us at bottom
        time.sleep(3.5)

        gap1 = driver.execute_script("""
            var el = document.getElementById('plain-output');
            return el.scrollHeight - el.scrollTop - el.clientHeight;
        """)
        assert gap1 < 40, (
            f'Auto-scroll failed: panel drifted away from bottom after polls.\n'
            f'  Gap before: {gap0} px\n'
            f'  Gap after 3.5 s: {gap1} px  (must be < 40 px)'
        )

    def test_scroll_up_position_is_preserved(self, driver, seed_host):
        """When user scrolls UP, position is preserved across polls
        (panel does NOT auto-jump back to bottom — v10.30 behaviour)."""
        pid = _start_slow_process()
        time.sleep(10.0)

        _select_host_and_process(driver, pid)
        time.sleep(1.5)

        scrollable = driver.execute_script("""
            var el = document.getElementById('plain-output');
            return el.scrollHeight > el.clientHeight;
        """)
        if not scrollable:
            time.sleep(3.0)

        # Scroll to the TOP (user reading from beginning)
        driver.execute_script("""
            var el = document.getElementById('plain-output');
            el.scrollTop = 0;
        """)
        time.sleep(0.1)

        top_before = driver.execute_script(
            "return document.getElementById('plain-output').scrollTop")

        # Wait 3 s (2 polls) — scroll position must be preserved
        time.sleep(3.5)

        top_after = driver.execute_script(
            "return document.getElementById('plain-output').scrollTop")

        # Allow ±5 px drift from sub-pixel rendering
        assert abs(top_after - top_before) < 20, (
            f'Scroll position was NOT preserved: '
            f'before={top_before}px after={top_after}px. '
            f'Panel jumped (auto-scroll should only fire when at the BOTTOM).'
        )


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
    Uses a JS-based lookup inside execute_script to avoid StaleElementReferenceException:
    in the full test suite the snapshot poll rebuilds #processes-body every 1.5 s, making
    any previously-found element reference stale before .click() fires."""
    css = f'#processes-body tr[data-process-id="{process_id}"]'
    # Wait for the row to appear in the DOM (ignore stale refs during table rebuild)
    WebDriverWait(driver, timeout,
                  ignored_exceptions=[StaleElementReferenceException]).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, css))
    # Ensure the Processes bottom tab is visible before clicking.
    # The Log tab tests (US40/41/42) switch the bottom section to the Log tab
    # and never switch back.  If #processes-panel is display:none, the
    # #process-output-inline container has zero width, fitAddon defaults to
    # 10 columns, and long markers wrap across rows and cannot be found.
    driver.execute_script("""
        var btn = document.querySelector('#bottom-tab-bar [data-tab="processes-panel"]');
        if (btn) btn.click();
    """)
    time.sleep(0.3)

    # Re-look up inside JS so the reference is always fresh — immune to staleness
    driver.execute_script(f"""
        var row = document.querySelector('#processes-body tr[data-process-id="{process_id}"]');
        if (row) {{ row.scrollIntoView({{block:'center'}}); row.click(); }}
    """)
    time.sleep(2.0)  # xterm needs time to mount and render

    # Force-fit the terminal after layout settles
    driver.execute_script("""
        if (typeof _termState !== 'undefined' &&
            _termState.fitAddon && _termState.xterm) {
            try { _termState.fitAddon.fit(); } catch(e) {}
        }
    """)
    time.sleep(0.3)


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


# ===========================================================================
# GROUP 8 — Live Scan Tests (US-09, US-32, US-39)
# These require LEGION_TEST_TARGET env var pointing at a reachable host.
# US-32 only requires a running server (CVEs injected via API — no live scan).
# US-09 and US-39 require the live target for nmap and eyewitness.
# ===========================================================================

_LIVE_TARGET = os.environ.get('LEGION_TEST_TARGET', '').strip()
_LIVE_SKIP   = pytest.mark.skipif(
    not _LIVE_TARGET,
    reason='Set LEGION_TEST_TARGET=<ip> to run live tests')


class TestUS32_CvesSortedByScore:
    """
    US-32: The CVEs tab must display vulnerabilities sorted by CVSS score
    descending — highest severity first.

    Uses the real CVE injection endpoint (same one used by vulners NSE) so
    no live nmap scan is required.  Verifies the DOM sort order and that it
    persists after navigating to a different host and back.
    """

    _HOST = '10.10.10.1'
    _CVES = [
        ('CVE-2021-0001', 7.8,  'medium',   'Kernel bug'),
        ('CVE-2021-0002', 9.8,  'critical', 'RCE in SSH'),
        ('CVE-2021-0003', 5.0,  'low',      'Info disclosure'),
        ('CVE-2021-0004', 9.3,  'critical', 'Privilege escalation'),
        ('CVE-2021-0005', 9.8,  'critical', 'Buffer overflow'),
    ]
    _EXPECTED_ORDER = [9.8, 9.8, 9.3, 7.8, 5.0]

    def _get_host_id(self):
        snap = api('get', '/api/snapshot').json()
        for h in snap.get('hosts', []):
            if h.get('ip') == self._HOST:
                return h.get('id')
        return None

    def _inject_cves(self, host_id):
        """POST one CVE per call — endpoint takes a single CVE (name, severity, product)."""
        for cve_id, cvss, _sev, product in self._CVES:
            api('post', f'/api/workspace/hosts/{host_id}/cves',
                json={'name': cve_id, 'severity': str(cvss), 'product': product})
        time.sleep(0.5)

    def _open_cves_tab(self, driver):
        """Select host row then click CVEs tab; wait for loadHostDetail async fetch."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{self._HOST}\"]');"
            "if (r) r.click();")
        time.sleep(1.2)   # loadHostDetail fires CVE fetch async
        driver.execute_script(
            "var btn = document.querySelector('#right-tab-bar [data-tab=\"cves-right\"]');"
            "if (btn) btn.click();")
        time.sleep(1.0)

    def _read_cvss_from_dom(self, driver):
        """Read CVSS values from #host-detail-cves rows — td[1] holds the severity float."""
        return driver.execute_script("""
            var rows = document.querySelectorAll('#host-detail-cves tr');
            var scores = [];
            rows.forEach(function(r) {
                var cells = r.querySelectorAll('td');
                if (cells.length >= 2) {
                    var v = parseFloat(cells[1].textContent.trim());
                    if (!isNaN(v)) scores.push(v);
                }
            });
            return scores;
        """)

    def test_injected_cves_appear_in_tab(self, driver, seed_host):
        """All 5 injected CVEs appear in the CVEs tab."""
        host_id = self._get_host_id()
        assert host_id, f'Host {self._HOST} not found in snapshot'
        self._inject_cves(host_id)
        self._open_cves_tab(driver)

        scores = self._read_cvss_from_dom(driver)
        assert len(scores) >= len(self._CVES), (
            f'Expected ≥{len(self._CVES)} CVE rows, got {len(scores)}')

    def test_cves_sorted_descending_by_cvss(self, driver, seed_host):
        """CVE rows are ordered highest CVSS first."""
        host_id = self._get_host_id()
        assert host_id, f'Host {self._HOST} not found'
        self._inject_cves(host_id)
        self._open_cves_tab(driver)

        scores = self._read_cvss_from_dom(driver)
        assert scores, 'No CVSS scores found in CVEs tab DOM'
        assert scores == sorted(scores, reverse=True), (
            f'CVEs not sorted descending. Got: {scores}. '
            f'Expected: {sorted(scores, reverse=True)}')

    def test_cve_sort_persists_after_host_navigation(self, driver, seed_host):
        """Sort order is preserved after clicking a different host and back."""
        host_id = self._get_host_id()
        assert host_id
        self._inject_cves(host_id)
        self._open_cves_tab(driver)

        # Click any other row (use the hosts list — pick a different ip if available)
        other = driver.execute_script(
            f"var rows = Array.from(document.querySelectorAll('#hosts-body tr[data-host-ip]'));"
            f"var other = rows.filter(r => r.dataset.hostIp !== '{self._HOST}')[0];"
            "if (other) { other.click(); return other.dataset.hostIp; } return null;")
        time.sleep(1.0)

        # Navigate back
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{self._HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)
        driver.execute_script(
            "var btn = document.querySelector('#right-tab-bar [data-tab=\"cves-right\"]');"
            "if (btn) btn.click();")
        time.sleep(1.5)

        scores = self._read_cvss_from_dom(driver)
        assert scores == sorted(scores, reverse=True), (
            f'Sort lost after navigation. Got: {scores}')


@_LIVE_SKIP
class TestUS09_NmapProgressPercent:
    """
    US-09: The % column in the Processes table exists and reflects nmap
    progress when --stats-every 5s emits 'About N% done' lines.

    Structural test: verifies the % column header and the DOM rendering
    pipeline (DB percent field → snapshot → td[5]).  On fast local VMs
    the scan completes before 5s fires so percent may be empty — the
    DOM % cell and snapshot percent field must match either way.

    Set LEGION_TEST_TARGET=192.168.85.11 to run.
    """

    def test_nmap_process_appears_as_running(self, driver, seed_host):
        """Submitting a Hard-mode nmap scan creates a process row."""
        proc_before = len(api('get', '/api/snapshot').json().get('processes', []))
        resp = api('post', '/api/nmap/scan', json={
            'targets': _LIVE_TARGET,
            'scan_mode': 'Hard', 'discovery': True, 'staged': False,
            'timing': '4', 'nmap_options': ['-sV'], 'enable_ipv6': False,
        })
        assert resp.status_code == 200, f'Scan failed: {resp.json()}'
        time.sleep(2.5)

        proc_after = api('get', '/api/snapshot').json().get('processes', [])
        new = [p for p in proc_after if p['id'] > proc_before]
        assert new, 'No new process appeared after submitting nmap scan'

        status = new[0].get('status')
        assert status in ('Running', 'Waiting', 'Finished'), \
            f'Unexpected status: {status}'

    def test_percent_column_header_and_cell_exist(self, driver, seed_host):
        """% column header exists at index 5; process row has ≥6 cells."""
        # Submit a scan to ensure a process row exists
        api('post', '/api/nmap/scan', json={
            'targets': _LIVE_TARGET,
            'scan_mode': 'Hard', 'discovery': True, 'staged': False,
            'timing': '4', 'nmap_options': ['-sV'], 'enable_ipv6': False,
        })
        time.sleep(2.5)

        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_LIVE_TARGET}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        result = driver.execute_script("""
            var headers = document.querySelectorAll('#processes-table thead th');
            var pctIdx = -1;
            for (var i = 0; i < headers.length; i++) {
                if (headers[i].textContent.trim() === '%') { pctIdx = i; break; }
            }
            var row = document.querySelector('#processes-body tr[data-process-id]');
            var cells = row ? row.querySelectorAll('td').length : 0;
            return {headerIndex: pctIdx, rowCells: cells};
        """)
        assert result['headerIndex'] == 5, \
            f'% header not at index 5: {result}'
        assert result['rowCells'] >= 6, \
            f'Process row has <6 cells: {result["rowCells"]}'

    def test_dom_percent_matches_snapshot_percent(self, driver, seed_host):
        """After scan, DOM % cell value == snapshot percent field (same DB source)."""
        resp = api('post', '/api/nmap/scan', json={
            'targets': _LIVE_TARGET,
            'scan_mode': 'Hard', 'discovery': True, 'staged': False,
            'timing': '4', 'nmap_options': ['-sV'], 'enable_ipv6': False,
        })
        pid = resp.json().get('result', {}).get('process_id') or \
              max(p['id'] for p in api('get', '/api/snapshot').json()['processes'])
        time.sleep(1)

        # Wait for finish
        deadline = time.monotonic() + 60
        snap_pct = None
        while time.monotonic() < deadline:
            procs = api('get', '/api/snapshot').json().get('processes', [])
            for p in procs:
                if p['id'] == pid and p['status'] in ('Finished', 'Crashed'):
                    snap_pct = (p.get('percent') or '').strip()
                    break
            if snap_pct is not None:
                break
            time.sleep(1)

        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_LIVE_TARGET}\"]');"
            "if (r) r.click();")
        time.sleep(1.5)

        dom_pct = (driver.execute_script(
            f"var r = document.querySelector('#processes-body tr[data-process-id=\"{pid}\"]');"
            "if (!r) return '';"
            "var c = r.querySelectorAll('td');"
            "return c.length >= 6 ? c[5].textContent.trim() : '';") or '').strip()

        assert snap_pct == dom_pct, (
            f'Snapshot percent {snap_pct!r} != DOM % cell {dom_pct!r}. '
            f'Both must come from the same DB process.percent field.')


@_LIVE_SKIP
class TestUS39_ScreenshotTabShowsImage:
    """
    US-39: After the screenshooter (eyewitness) runs against an HTTP service,
    clicking the screenshooter process row must show an <img> in #plain-output
    pointing to /api/screenshots?path=...

    Set LEGION_TEST_TARGET=192.168.85.11 to run.
    Requires: eyewitness at /usr/bin/eyewitness; xvfb-run.
    """

    def _import_http_host(self):
        xml = f"""<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
  <address addr="{_LIVE_TARGET}" addrtype="ipv4"/>
  <ports><port protocol="tcp" portid="80">
    <state state="open"/><service name="http"/>
  </port></ports>
</host></nmaprun>"""
        with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
            f.write(xml); path = f.name
        api('post', '/api/nmap/import-xml', json={'path': path})
        os.unlink(path)
        time.sleep(1)

    def test_screenshooter_process_appears(self, driver, seed_host):
        """Triggering scheduler on HTTP host creates a screenshooter process."""
        self._import_http_host()
        api('post', '/api/scheduler/run', json={'host_ip': _LIVE_TARGET})
        time.sleep(3)

        procs = api('get', '/api/snapshot').json().get('processes', [])
        shooter = [p for p in procs if 'screenshooter' in (p.get('name') or '').lower()]
        assert shooter, 'No screenshooter process found after scheduler run'

    def test_screenshooter_output_is_screenshot_path(self, driver, seed_host):
        """Process output starts with 'screenshot:' once eyewitness finishes."""
        self._import_http_host()
        resp = api('post', '/api/scheduler/run', json={'host_ip': _LIVE_TARGET})
        time.sleep(2)

        procs = api('get', '/api/snapshot').json().get('processes', [])
        shooter = next((p for p in procs
                        if 'screenshooter' in (p.get('name') or '').lower()), None)
        assert shooter, 'No screenshooter process'

        pid = shooter['id']
        deadline = time.monotonic() + 90
        output = ''
        while time.monotonic() < deadline:
            data = api('get', f'/api/processes/{pid}/output').json()
            output = data.get('output_chunk', '') or data.get('output', '')
            if output.startswith('screenshot:'):
                break
            status = next((p['status'] for p in
                           api('get', '/api/snapshot').json()['processes']
                           if p['id'] == pid), '')
            if status == 'Finished':
                break
            time.sleep(2)

        assert output.startswith('screenshot:'), (
            f'Process {pid} output does not start with "screenshot:": {output[:80]!r}')

    def test_screenshooter_row_renders_img_in_panel(self, driver, seed_host):
        """Clicking screenshooter row renders <img src=/api/screenshots?...>."""
        self._import_http_host()
        api('post', '/api/scheduler/run', json={'host_ip': _LIVE_TARGET})
        time.sleep(3)

        procs = api('get', '/api/snapshot').json().get('processes', [])
        shooter = next((p for p in procs
                        if 'screenshooter' in (p.get('name') or '').lower()), None)
        assert shooter, 'No screenshooter process'
        pid = shooter['id']

        # Wait for finish
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            p = next((x for x in api('get', '/api/snapshot').json()['processes']
                      if x['id'] == pid), {})
            if p.get('status') == 'Finished':
                break
            time.sleep(2)

        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_LIVE_TARGET}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        css = f'#processes-body tr[data-process-id="{pid}"]'
        W(driver, 8).until(lambda d: d.find_elements(By.CSS_SELECTOR, css))
        row = driver.find_element(By.CSS_SELECTOR, css)
        driver.execute_script(
            'arguments[0].scrollIntoView({block:"center"}); arguments[0].click()', row)
        time.sleep(2)

        img = driver.find_elements(By.CSS_SELECTOR, '#plain-output img')
        assert img, '#plain-output contains no <img> after clicking screenshooter row'

        src = img[0].get_attribute('src') or ''
        assert '/api/screenshots' in src, \
            f'<img> src does not point to /api/screenshots: {src!r}'


# ===========================================================================
# GROUP 2 — Font Size Controls (US-25, US-26)
# Pytest classes mirroring the logic in generate_report_US25/26.py.
# The generate_report scripts default to port 5095; these tests use the
# session-scoped driver on port 5085 (same server as all other pytest tests).
# ===========================================================================

def _get_font_px(driver, element_id):
    """Return computed font-size in px for the element (float)."""
    return driver.execute_script(
        f"var el = document.getElementById('{element_id}');"
        "if (!el) return null;"
        "return parseFloat(window.getComputedStyle(el).fontSize);")


class TestUS25_UpperFontSize:
    """
    US-25: Clicking #upper-font-inc increases #dynamic-tabs-container font-size
    without changing #process-output-inline (lower panel is independent).
    """

    def test_upper_font_increases_on_inc_click(self, driver, seed_host):
        """One click of #upper-font-inc increases upper panel computed font-size."""
        before = _get_font_px(driver, 'dynamic-tabs-container')
        assert before is not None and before > 0, \
            '#dynamic-tabs-container has no computed font-size'

        driver.execute_script("document.getElementById('upper-font-inc').click()")
        time.sleep(0.4)

        after = _get_font_px(driver, 'dynamic-tabs-container')
        assert after > before, (
            f'Upper font did not increase after #upper-font-inc click: '
            f'before={before}px after={after}px')

        # Restore
        driver.execute_script("document.getElementById('upper-font-dec').click()")
        time.sleep(0.2)

    def test_upper_font_change_does_not_affect_lower_panel(self, driver, seed_host):
        """Clicking #upper-font-inc leaves #process-output-inline font-size unchanged."""
        lower_before = _get_font_px(driver, 'process-output-inline')
        assert lower_before is not None and lower_before > 0, \
            '#process-output-inline has no computed font-size'

        driver.execute_script("document.getElementById('upper-font-inc').click()")
        time.sleep(0.4)

        lower_after = _get_font_px(driver, 'process-output-inline')
        assert abs(lower_after - lower_before) < 1.0, (
            f'Lower panel font changed after upper A+ click: '
            f'before={lower_before}px after={lower_after}px — panels must be independent')

        driver.execute_script("document.getElementById('upper-font-dec').click()")
        time.sleep(0.2)

    def test_upper_font_dec_decreases_size(self, driver, seed_host):
        """#upper-font-dec shrinks the upper panel font."""
        # First grow so there is room to shrink
        driver.execute_script("document.getElementById('upper-font-inc').click()")
        time.sleep(0.3)
        before = _get_font_px(driver, 'dynamic-tabs-container')

        driver.execute_script("document.getElementById('upper-font-dec').click()")
        time.sleep(0.4)

        after = _get_font_px(driver, 'dynamic-tabs-container')
        assert after < before, (
            f'Upper font did not decrease after #upper-font-dec click: '
            f'before={before}px after={after}px')


class TestUS26_LowerFontSize:
    """
    US-26: Clicking #output-font-inc increases #process-output-inline font-size
    without changing #dynamic-tabs-container (upper panel is independent).
    """

    def test_lower_font_increases_on_inc_click(self, driver, seed_host):
        """One click of #output-font-inc increases lower panel computed font-size."""
        before = _get_font_px(driver, 'process-output-inline')
        assert before is not None and before > 0, \
            '#process-output-inline has no computed font-size'

        driver.execute_script("document.getElementById('output-font-inc').click()")
        time.sleep(0.4)

        after = _get_font_px(driver, 'process-output-inline')
        assert after > before, (
            f'Lower font did not increase after #output-font-inc click: '
            f'before={before}px after={after}px')

        driver.execute_script("document.getElementById('output-font-dec').click()")
        time.sleep(0.2)

    def test_lower_font_change_does_not_affect_upper_panel(self, driver, seed_host):
        """Clicking #output-font-inc leaves #dynamic-tabs-container font-size unchanged."""
        upper_before = _get_font_px(driver, 'dynamic-tabs-container')
        assert upper_before is not None and upper_before > 0

        driver.execute_script("document.getElementById('output-font-inc').click()")
        time.sleep(0.4)

        upper_after = _get_font_px(driver, 'dynamic-tabs-container')
        assert abs(upper_after - upper_before) < 1.0, (
            f'Upper panel font changed after lower A+ click: '
            f'before={upper_before}px after={upper_after}px — panels must be independent')

        driver.execute_script("document.getElementById('output-font-dec').click()")
        time.sleep(0.2)

    def test_lower_font_dec_decreases_size(self, driver, seed_host):
        """#output-font-dec shrinks the lower panel font."""
        driver.execute_script("document.getElementById('output-font-inc').click()")
        time.sleep(0.3)
        before = _get_font_px(driver, 'process-output-inline')

        driver.execute_script("document.getElementById('output-font-dec').click()")
        time.sleep(0.4)

        after = _get_font_px(driver, 'process-output-inline')
        assert after < before, (
            f'Lower font did not decrease after #output-font-dec click: '
            f'before={before}px after={after}px')


# ===========================================================================
# GROUP 4 — Match Logic (US-44/45/46) and Proc-Match CSS (US-31)
# Each test uses a unique fake port (2201-2209) so wc._matches keys
# ("hostIp:custom (PORT/tcp)") do not accumulate between scenarios.
# ===========================================================================

def _run_cmd_and_wait(host_ip, cmd, port, timeout=60):
    """Run cmd via /api/processes/custom and wait for Finished/Crashed.
    Returns (has_match, match_text, status) from snapshot."""
    resp = api('post', '/api/processes/custom', json={
        'command': cmd, 'host_ip': host_ip, 'port': str(port), 'protocol': 'tcp'})
    pid = resp.json().get('process_id')
    assert pid, f'No process_id: {resp.json()}'

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        procs = api('get', '/api/snapshot').json().get('processes', [])
        for p in procs:
            if str(p.get('id')) == str(pid):
                if p.get('status') in ('Finished', 'Crashed'):
                    return pid, p.get('has_match', False), p.get('match_text', ''), p.get('status')
        time.sleep(0.5)
    return pid, False, '', 'Timeout'


def _proc_match_class(driver, pid):
    """True if the process row has CSS class proc-match."""
    return driver.execute_script(
        f"var r = document.querySelector('#processes-body tr[data-process-id=\"{pid}\"]');"
        "return r ? r.classList.contains('proc-match') : null;")


_MATCH_HOST = '10.10.10.1'


class TestUS44US45US46_MatchLogic:
    """
    US-44: Matching is case-sensitive — 'SUCCEED' matches; 'succeed' does not.
    US-45: Space-guarded keywords use word-boundary regex — ' PUT ' matches
           'HTTP PUT is allowed' but NOT 'PUTTY OUTPUT'.
    US-46: Global-negative suppresses global-positive on the same line.

    Each scenario runs a real command via /api/processes/custom, waits for
    it to Finish, then checks has_match in the snapshot AND proc-match CSS
    class in the DOM — two independent layers of verification.
    """

    def test_us44_uppercase_keyword_matches(self, driver, seed_host):
        """'SUCCEED' (uppercase) in output → has_match=True, proc-match CSS set."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, status = _run_cmd_and_wait(_MATCH_HOST, 'printf "SUCCEED test"', 2201)
        time.sleep(1.5)
        row_match = _proc_match_class(driver, pid)

        assert has_match is True, \
            f'"SUCCEED" in output → has_match must be True; got {has_match} (status={status})'
        assert row_match is True, \
            f'proc-match CSS class missing from process row {pid}'

    def test_us44_lowercase_keyword_no_match(self, driver, seed_host):
        """'succeed' (lowercase) → has_match=False — matching is case-sensitive."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, status = _run_cmd_and_wait(_MATCH_HOST, 'printf "succeed test"', 2202)
        time.sleep(1.5)
        row_match = _proc_match_class(driver, pid)

        assert has_match is False, \
            f'"succeed" (lowercase) must NOT match "SUCCEED" keyword; got has_match={has_match}'
        assert row_match is not True, \
            f'proc-match CSS class incorrectly set for lowercase output'

    def test_us45_word_boundary_match(self, driver, seed_host):
        """' PUT ' word-boundary: 'HTTP PUT is allowed' → match."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, _ = _run_cmd_and_wait(_MATCH_HOST, 'printf "HTTP PUT is allowed"', 2203)
        time.sleep(1.5)

        assert has_match is True, \
            '"HTTP PUT is allowed" must match — PUT surrounded by non-word chars'

    def test_us45_word_boundary_no_match_embedded(self, driver, seed_host):
        """' PUT ' word-boundary: 'PUTTY OUTPUT' → no match (PUT embedded in words)."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, _ = _run_cmd_and_wait(_MATCH_HOST, 'printf "PUTTY OUTPUT"', 2204)
        time.sleep(1.5)

        assert has_match is False, \
            '"PUTTY OUTPUT" must NOT match — PUT followed/preceded by word chars'

    def test_us46_positive_fires_without_negative(self, driver, seed_host):
        """'vulnerable' with no negative keyword on same line → match."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, _ = _run_cmd_and_wait(
            _MATCH_HOST, 'printf "system is vulnerable"', 2205)
        time.sleep(1.5)

        assert has_match is True, \
            '"system is vulnerable" must match — "vulnerable" is in global-positive'

    def test_us46_negative_suppresses_positive(self, driver, seed_host):
        """'NOT vulnerable' on same line → negative suppresses 'vulnerable' positive."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, _ = _run_cmd_and_wait(
            _MATCH_HOST, 'printf "system is NOT vulnerable to this"', 2206)
        time.sleep(1.5)

        assert has_match is False, (
            '"NOT vulnerable" is in global-negative — must suppress "vulnerable" positive. '
            '_getMatches checks negatives FIRST and returns empty immediately.')


class TestUS31_ProcMatchCSS:
    """
    US-31 (corrected): When a tool produces output containing a global-positive
    keyword, the process row gets CSS class 'proc-match' and the dynamic tab
    button gets class 'tab-match'.
    """

    def test_matching_output_sets_proc_match_class(self, driver, seed_host):
        """Command outputting 'State: VULNERABLE' → process row gets proc-match."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, status = _run_cmd_and_wait(
            _MATCH_HOST, 'printf "State: VULNERABLE"', 2207)
        time.sleep(1.5)

        row_match = _proc_match_class(driver, pid)
        assert has_match is True, f'has_match must be True; got {has_match}'
        assert row_match is True, (
            f'proc-match CSS class not on process row {pid} after matching output. '
            f'renderProcesses() adds it when p.has_match is truthy (legion.js line 705).')

    def test_non_matching_output_no_proc_match_class(self, driver, seed_host):
        """Command with no keyword match → process row has NO proc-match class."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, _ = _run_cmd_and_wait(
            _MATCH_HOST, 'printf "nothing interesting here xyzzy"', 2208)
        time.sleep(1.5)

        row_match = _proc_match_class(driver, pid)
        assert has_match is False, f'has_match should be False for non-matching output'
        assert row_match is not True, \
            f'proc-match class incorrectly set on process row {pid}'

    def test_matching_output_star_in_name_cell(self, driver, seed_host):
        """Process row Name cell (td:nth-child(2)) gets a ★ prefix on match."""
        driver.execute_script(
            f"var r = document.querySelector('#hosts-body tr[data-host-ip=\"{_MATCH_HOST}\"]');"
            "if (r) r.click();")
        time.sleep(0.8)

        pid, has_match, _, _ = _run_cmd_and_wait(
            _MATCH_HOST, 'printf "State: VULNERABLE"', 2209)
        time.sleep(1.5)

        name_cell = driver.execute_script(
            f"var r = document.querySelector('#processes-body tr[data-process-id=\"{pid}\"]');"
            "if (!r) return null;"
            "var c = r.querySelectorAll('td');"
            "return c.length >= 2 ? c[1].textContent : null;")

        assert name_cell is not None, f'Process row {pid} not found in DOM'
        assert '\u2605' in (name_cell or ''), (
            f'★ (U+2605) not in Name cell after match. Got: {name_cell!r}. '
            f'legion.js line 708: matchIcon = "★" prepended when p.has_match is true.')


# ===========================================================================
# GROUP 6 — Config Manager Ctrl+F (US-54)
# ===========================================================================

def _open_config_manager(driver):
    """Open Config Manager via JS click (same path as F2 keydown handler).
    Waits for textarea content — cfgLoadProfiles() populates it async.

    Navigates to BASE_URL first if needed — US-55 tests leave the browser on
    port 5086 and reset_state does not navigate back."""
    if BASE_URL not in driver.current_url:
        driver.get(BASE_URL)
        time.sleep(1.5)
    driver.execute_script("document.getElementById('action-config').click()")
    W(driver, 5).until(
        lambda d: 'is-open' in (
            d.find_element(By.ID, 'config-modal').get_attribute('class') or ''))
    # Wait for textarea to be populated by cfgLoadProfiles()
    W(driver, 8).until(lambda d: bool(d.execute_script(
        "var ta = document.querySelector('#config-editors textarea');"
        "return ta && ta.value.length > 0;")))


def _close_config_manager(driver):
    try:
        driver.find_element(By.CSS_SELECTOR, '#config-modal .modal-close-btn').click()
        time.sleep(0.3)
    except Exception:
        pass


class TestUS54_ConfigManagerCtrlF:
    """
    US-54: Pressing Ctrl+F while the Config Manager modal is open must show
    the find bar (#cfg-find-bar). Typing a search term must highlight matches
    with <mark> elements. Pressing Escape must hide the bar and clear marks.

    Ctrl+F is sent via ActionChains (isTrusted=true browser keyboard event)
    through the document keydown listener, not dispatchEvent.
    """

    def _get_config_textarea(self, driver):
        """The config textarea is dynamically created inside #config-editors.
        Selector: #config-editors textarea (data-profile attribute varies)."""
        return driver.execute_script(
            "return document.querySelector('#config-editors textarea');")

    def test_ctrlf_opens_find_bar(self, driver, seed_host):
        """Ctrl+F while Config Manager is open makes #cfg-find-bar visible."""
        _open_config_manager(driver)
        time.sleep(0.8)   # JS creates the textarea dynamically

        # Confirm find bar hidden before Ctrl+F
        bar = driver.find_element(By.ID, 'cfg-find-bar')
        assert not bar.is_displayed(), '#cfg-find-bar should be hidden before Ctrl+F'

        # JS-focus the textarea (no ActionChains click — element may be off-screen)
        # then send Ctrl+F with no target element so it goes to the document
        driver.execute_script(
            "var ta = document.querySelector('#config-editors textarea');"
            "if (ta) ta.focus();")
        time.sleep(0.2)
        ActionChains(driver).key_down(Keys.CONTROL).send_keys('f') \
                            .key_up(Keys.CONTROL).perform()
        time.sleep(0.5)

        assert bar.is_displayed(), \
            '#cfg-find-bar not visible after Ctrl+F in Config Manager'

        _close_config_manager(driver)

    def test_search_term_produces_mark_highlights(self, driver, seed_host):
        """Typing 'nmap' in the find bar highlights matches with <mark> elements."""
        _open_config_manager(driver)

        driver.execute_script(
            "var ta = document.querySelector('#config-editors textarea');"
            "if (ta) ta.focus();")
        time.sleep(0.2)
        ActionChains(driver).key_down(Keys.CONTROL).send_keys('f') \
                            .key_up(Keys.CONTROL).perform()
        time.sleep(0.4)

        find_input = driver.find_element(By.ID, 'cfg-find-input')
        find_input.clear()
        find_input.send_keys('nmap')
        time.sleep(0.5)

        mark_count = driver.execute_script(
            "return document.querySelectorAll('.cfg-find-overlay mark').length")
        assert mark_count > 0, (
            f'No <mark> elements after searching "nmap" — '
            f'find bar must highlight matches in the config text overlay')

        _close_config_manager(driver)

    def test_escape_hides_find_bar(self, driver, seed_host):
        """Escape key hides #cfg-find-bar and clears match highlights."""
        _open_config_manager(driver)

        driver.execute_script(
            "var ta = document.querySelector('#config-editors textarea');"
            "if (ta) ta.focus();")
        time.sleep(0.2)
        ActionChains(driver).key_down(Keys.CONTROL).send_keys('f') \
                            .key_up(Keys.CONTROL).perform()
        time.sleep(0.4)

        find_input = driver.find_element(By.ID, 'cfg-find-input')
        find_input.send_keys('nmap')
        time.sleep(0.4)

        find_input.send_keys(Keys.ESCAPE)
        time.sleep(0.4)

        bar = driver.find_element(By.ID, 'cfg-find-bar')
        assert not bar.is_displayed(), \
            '#cfg-find-bar still visible after Escape key'

        mark_count = driver.execute_script(
            "return document.querySelectorAll('.cfg-find-overlay mark').length")
        assert mark_count == 0, \
            f'<mark> elements not cleared after Escape: {mark_count} remain'

        _close_config_manager(driver)
