#!/usr/bin/env python3
"""tests/test_ui_v10f_features.py

Non-hollow Selenium tests for v10.211–v10.213 changes:

  v10.211   Config Manager — single Save button with dirty-state pulse.
            "Apply to Config" button removed. Save button pulses when
            changes are detected. Status text clears on modal reopen.

  v10.212   Negative match un-highlighting. "not vulnerable" no longer
            has "vulnerable" highlighted in yellow. Negative patterns
            strip positive highlight spans.

  v10.213   Cross-host service view survives snapshot poll. Clicking a
            service in the left panel shows all hosts with that service
            on the right — this view persists across 1.5s polls.

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_v10f_features.py -v

Port: 5074
"""
import os
import sys
import time
import threading
import tempfile

import pytest
import requests as req
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5074
IP_A = '10.74.74.1'
IP_B = '10.74.74.2'

SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP_A}" addrtype="ipv4"/>
    <hostnames><hostname name="host1.local" type="PTR"/></hostnames>
    <ports>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http" product="Apache"/></port>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="{IP_B}" addrtype="ipv4"/>
    <hostnames><hostname name="host2.local" type="PTR"/></hostnames>
    <ports>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http" product="nginx"/></port>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https" product="nginx"/></port>
    </ports>
  </host>
</nmaprun>"""


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _wait_proc_done_api(srv_url, proc_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in req.get(f"{srv_url}/api/snapshot", timeout=5).json().get('processes', []):
                if str(p.get('id')) == str(proc_id) and p.get('status') in ('Finished', 'Killed', 'Crashed'):
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Process {proc_id} did not finish within {timeout}s")


def _select_host(d, ip):
    row = W(d, 10).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))
    js(d, 'arguments[0].click()', row)
    time.sleep(1.0)


# ── Fixtures ─────────────────────────────────────────────────────────────────

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
        f.write(SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)
    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(2.0)  # DETERMINISM-EXEMPT: socket listen handshake
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}
    httpd.shutdown()
    _web_routes._HB_TIMEOUT = 20


@pytest.fixture(scope="module")
def drv(srv):
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(srv['url'])
    time.sleep(2.0)  # DETERMINISM-EXEMPT: initial page load + first snapshot poll
    yield d
    d.quit()


# ═══════════════════════════════════════════════════════════════════════════════
# v10.211 — Config Manager: single Save button + status cleanup
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigManagerSaveButton:
    """Verify: Apply to Config button removed, Save button pulses on changes,
    status text clears on modal reopen."""

    def test_apply_button_absent(self, drv, srv):
        """The 'Apply to Config' button should no longer exist in the DOM."""
        js(drv, "document.getElementById('action-config').click()")
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'config-modal')))
        time.sleep(0.5)
        btns = drv.find_elements(By.ID, 'easy-apply-btn')
        assert len(btns) == 0 or not btns[0].is_displayed(), \
            "'Apply to Config' button should be removed"
        js(drv, "document.getElementById('config-close').click()")
        time.sleep(0.3)

    def test_status_clears_on_reopen(self, drv, srv):
        """Opening the config modal should clear any stale status text."""
        # Open modal and force a status message
        js(drv, "document.getElementById('action-config').click()")
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'config-modal')))
        js(drv, "document.getElementById('config-status').textContent = 'STALE MESSAGE'")
        status_before = js(drv, "return document.getElementById('config-status').textContent")
        assert status_before == 'STALE MESSAGE', "Pre-condition: stale message set"
        # Close and reopen
        js(drv, "document.getElementById('config-close').click()")
        time.sleep(0.5)
        js(drv, "document.getElementById('action-config').click()")
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'config-modal')))
        time.sleep(0.3)
        status_after = js(drv, "return document.getElementById('config-status').textContent")
        assert status_after == '', \
            f"Status should be empty on reopen, got: '{status_after}'"
        js(drv, "document.getElementById('config-close').click()")
        time.sleep(0.3)

    def test_save_button_pulses_on_textarea_edit(self, drv, srv):
        """Editing the raw textarea in Advanced mode should add the dirty class to Save."""
        js(drv, "document.getElementById('action-config').click()")
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'config-modal')))
        time.sleep(0.5)
        # Pre-condition: Save button should NOT have dirty class
        has_dirty_before = js(drv, """
            var btn = document.getElementById('config-save');
            return btn ? btn.classList.contains('config-save-dirty') : false;
        """)
        assert not has_dirty_before, "Save button should not be dirty initially"
        # Type into the active textarea
        js(drv, """
            var ta = document.querySelector('#config-editors textarea');
            if (ta) {
                ta.value += '\\n# test change';
                ta.dispatchEvent(new Event('input', {bubbles: true}));
            }
        """)
        time.sleep(0.3)
        has_dirty_after = js(drv, """
            return document.getElementById('config-save').classList.contains('config-save-dirty');
        """)
        assert has_dirty_after, "Save button should pulse after textarea edit"
        js(drv, "document.getElementById('config-close').click()")
        time.sleep(0.3)

    def test_save_clears_pulse_and_shows_status(self, drv, srv):
        """Clicking Save should remove the dirty class and show success status."""
        js(drv, "document.getElementById('action-config').click()")
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'config-modal')))
        time.sleep(0.5)
        # Make a change to trigger dirty
        js(drv, """
            var ta = document.querySelector('#config-editors textarea');
            if (ta) {
                ta.value += '\\n# save test';
                ta.dispatchEvent(new Event('input', {bubbles: true}));
            }
        """)
        time.sleep(0.3)
        # Click Save
        js(drv, "document.getElementById('config-save').click()")
        # Wait for status to update (API call is async)
        deadline = time.time() + 5
        status = ''
        while time.time() < deadline:
            status = js(drv, "return document.getElementById('config-status').textContent")
            if 'Saved' in status:
                break
            time.sleep(0.3)
        assert 'Saved' in status, f"Expected 'Saved' in status, got: '{status}'"
        # Dirty class should be removed after save
        still_dirty = js(drv, """
            return document.getElementById('config-save').classList.contains('config-save-dirty');
        """)
        assert not still_dirty, "Save button should not be dirty after successful save"
        js(drv, "document.getElementById('config-close').click()")
        time.sleep(0.3)


# ═══════════════════════════════════════════════════════════════════════════════
# v10.212 — Negative match un-highlighting
# ═══════════════════════════════════════════════════════════════════════════════

class TestNegativeMatchUnhighlight:
    """Verify: words matching a positive pattern are NOT highlighted when they
    appear within a negative pattern context."""

    @pytest.fixture(scope="class")
    def match_setup(self, drv, srv):
        """Inject match patterns, create a process with test output, select it."""
        drv.get(srv['url'])
        time.sleep(2.0)  # DETERMINISM-EXEMPT: full page reload
        # Inject match patterns
        js(drv, """
            matchPositive.length = 0;
            matchNegative.length = 0;
            matchPositive.push('vulnerable');
            matchNegative.push('not vulnerable');
            matchNegative.push('Not vulnerable');
        """)
        # Create a process with output containing both positive and negative contexts
        wc = srv['wc']
        _select_host(drv, IP_A)
        result = wc.runCommand(
            command='echo "This server IS vulnerable to CVE-2021-1234"; '
                    'echo "This server is not vulnerable to CVE-2022-9999"; '
                    'echo "Not vulnerable to anything else"',
            name='match-neg-test',
            hostIp=IP_A, port='80', protocol='tcp')
        proc_id = result['process_id']
        _wait_proc_done_api(srv['url'], proc_id)
        time.sleep(2.0)  # DETERMINISM-EXEMPT: wait for snapshot to pick up the process
        yield proc_id

    def test_positive_match_highlighted(self, drv, srv, match_setup):
        """'vulnerable' in a positive-only context should be highlighted."""
        proc_id = match_setup
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(2.0)  # DETERMINISM-EXEMPT: output loads async
        html = js(drv, "return document.getElementById('plain-output').innerHTML")
        assert html, "Output panel should have content"
        import re as _re
        # match-positive span may also have match-current class from match-nav
        pos_spans = _re.findall(r'<span class="match-positive[^"]*">vulnerable</span>', html)
        assert len(pos_spans) >= 1, \
            "Standalone 'vulnerable' should be highlighted with match-positive class"

    def test_negative_match_not_highlighted(self, drv, srv, match_setup):
        """'vulnerable' within 'not vulnerable' should NOT be highlighted."""
        proc_id = match_setup
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(2.0)  # DETERMINISM-EXEMPT: output loads async
        html = js(drv, "return document.getElementById('plain-output').innerHTML")
        import re as _re
        # Count match-positive spans — should be exactly 1 (the standalone "IS vulnerable")
        # The "not vulnerable" and "Not vulnerable" lines should have plain text, no span
        pos_spans = _re.findall(r'<span class="match-positive[^"]*">vulnerable</span>', html)
        assert len(pos_spans) == 1, (
            f"Expected exactly 1 highlighted 'vulnerable' (standalone only), "
            f"found {len(pos_spans)}. 'not vulnerable' should be un-highlighted.\n"
            f"HTML:\n{html[:500]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# v10.213 — Cross-host service view survives snapshot poll
# ═══════════════════════════════════════════════════════════════════════════════

class TestServiceViewPersistence:
    """Verify: clicking a service in the left panel shows all hosts with that
    service on the right, and this view survives multiple snapshot polls."""

    def test_service_click_shows_cross_host_results(self, drv, srv):
        """Clicking 'http' in the left Services tab should show both hosts on the right."""
        drv.get(srv['url'])
        time.sleep(2.5)  # DETERMINISM-EXEMPT: full page reload + snapshot
        # Click the Services tab on the left (data-tab="services-left-panel")
        svc_tab = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#left-tab-bar [data-tab="services-left-panel"]')))
        js(drv, 'arguments[0].click()', svc_tab)
        time.sleep(1.0)
        # Find and click the 'http' row in the services table
        http_row = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#services-body tr[data-service="http"]')))
        js(drv, 'arguments[0].click()', http_row)
        time.sleep(2.0)  # DETERMINISM-EXEMPT: updatePortsByService fetches per-host data async
        # Right panel cross-host results go into #host-detail-ports
        right_html = js(drv, "return document.getElementById('host-detail-ports').innerHTML")
        assert IP_A in right_html, f"Right panel should contain {IP_A}"
        assert IP_B in right_html, f"Right panel should contain {IP_B}"

    def test_service_view_survives_polls(self, drv, srv):
        """After clicking a service, the cross-host view should persist across polls."""
        drv.get(srv['url'])
        time.sleep(2.5)  # DETERMINISM-EXEMPT: full page reload + snapshot
        svc_tab = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#left-tab-bar [data-tab="services-left-panel"]')))
        js(drv, 'arguments[0].click()', svc_tab)
        time.sleep(1.0)
        http_row = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#services-body tr[data-service="http"]')))
        js(drv, 'arguments[0].click()', http_row)
        time.sleep(2.0)  # DETERMINISM-EXEMPT: updatePortsByService fetches per-host data async
        # Verify initial state — both hosts visible
        right_initial = js(drv, "return document.getElementById('host-detail-ports').innerHTML")
        assert IP_A in right_initial and IP_B in right_initial, \
            "Pre-condition: both hosts visible in cross-host view"
        # Wait for 3+ snapshot polls (each is 1.5s)
        time.sleep(5.0)  # DETERMINISM-EXEMPT: must survive multiple snapshot poll cycles
        right_after = js(drv, "return document.getElementById('host-detail-ports').innerHTML")
        assert IP_A in right_after, \
            f"After 5s of polls, {IP_A} should still be in the cross-host service view"
        assert IP_B in right_after, \
            f"After 5s of polls, {IP_B} should still be in the cross-host service view"

    def test_host_click_clears_service_view(self, drv, srv):
        """Clicking a host row should exit the cross-host service view."""
        drv.get(srv['url'])
        time.sleep(2.5)  # DETERMINISM-EXEMPT: full page reload + snapshot
        svc_tab = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#left-tab-bar [data-tab="services-left-panel"]')))
        js(drv, 'arguments[0].click()', svc_tab)
        time.sleep(1.0)
        http_row = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#services-body tr[data-service="http"]')))
        js(drv, 'arguments[0].click()', http_row)
        time.sleep(1.5)
        flag = js(drv, "return L._serviceViewActive")
        assert flag is True, "_serviceViewActive should be true after service click"
        # Switch to Hosts tab and click a host
        hosts_tab = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#left-tab-bar [data-tab="hosts-panel"]')))
        js(drv, 'arguments[0].click()', hosts_tab)
        time.sleep(0.5)
        _select_host(drv, IP_A)
        time.sleep(1.5)
        flag_after = js(drv, "return L._serviceViewActive")
        assert flag_after is False, \
            "_serviceViewActive should be false after host click"
