#!/usr/bin/env python3
"""tests/test_ui_new_features2.py

Non-hollow Selenium regression tests for UI/backend features added 2026-03-28 (session 2).

  v10.76  Tool-hosts middle-pane host column truncates to 18 characters when
          the hostIp is longer, appending '…'.  The full value is available via
          the <td title="..."> attribute.  Short IPs (≤18 chars) are unchanged
          with no title attribute.

  v10.78  AI comparison dropdown context-sensitive placeholder:
          - No similar hosts in history → "— No similar hosts in history —"
          - Similar host found (Jaccard ≥ 0.95) → "— Select a host to compare —"
            followed by the match entries (user can skip comparison by leaving
            the prompt selected).

  v10.80  Ctrl+B from the lower output panel (plain-output) saves the note to
          the process's own host, not necessarily the currently selected host.
          Previously always used L.selectedHostId regardless of which process
          was displayed in the lower panel.

  v10.82  Killing a running process immediately triggers checkProcessQueue() so
          the next waiting process starts within seconds.  Previously the queue
          only advanced after _capture_output's readline() loop unblocked, which
          required the orphaned grandchild tool (nmap, sleep, etc.) to finish on
          its own — a delay of minutes.

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_new_features2.py -v
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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT   = 5077
IP_A   = '10.77.77.1'   # primary host (selected in UI for Ctrl+B test)
IP_B   = '10.77.77.2'   # secondary host (process belongs here for Ctrl+B test)
IP_LONG  = '10.200.200.200.local'   # 20 chars — will be truncated (not in SEED)
IP_SHORT = IP_A                      # 10 chars — will NOT be truncated

# Seed: two real hosts so both show up in the host list
SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP_A}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="{IP_B}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
    </ports>
  </host>
</nmaprun>"""

BASE = f'http://127.0.0.1:{PORT}'


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
    raise RuntimeError(f"Port {port} still in use after {retries} attempts")


def js(d, s, *a):
    return d.execute_script(s, *a)


def W(d, t=12):
    return WebDriverWait(d, t)


def _snapshot(timeout=5):
    return _req.get(f'{BASE}/api/snapshot', timeout=timeout).json()


def _wait_proc_done_api(proc_id, timeout=30):
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
    raise TimeoutError(f"Process {proc_id} did not finish within {timeout}s")


def _wait_proc_status(proc_id, status, timeout=20):
    """Poll snapshot until proc_id reaches the given status string."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in _snapshot().get('processes', []):
                if str(p.get('id')) == str(proc_id):
                    if p.get('status') == status:
                        return p
        except Exception:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Process {proc_id} did not reach status '{status}' within {timeout}s")


def _get_host_id(ip):
    for h in _snapshot().get('hosts', []):
        if h.get('ip') == ip:
            return h['id']
    return None


def _get_host_note(host_id):
    r = _req.get(f'{BASE}/api/workspace/hosts/{host_id}', timeout=5)
    return r.json().get('note', '') if r.ok else ''


def _switch_left_tab(drv, tab_id):
    js(drv, f"document.querySelector('[data-tab=\"{tab_id}\"]').click()")
    time.sleep(0.8)


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
# v10.76 — Tool-hosts host column truncation (18 chars + '…', hover title)
# ═══════════════════════════════════════════════════════════════════════════════

_TRUNC_TOOL = 'trunc-test-tool'


class TestToolHostTruncation:
    """The Host cell in #tool-hosts-body truncates hostIp to 18 chars + '…'
    when the value is longer than 18 characters.  Short values are unchanged.
    The full value is always readable via the title= attribute (hover tooltip)."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']

        # Long IP: 20 chars — triggers truncation
        r_long = wc.runCommand(command='echo trunc_long',
                               name=_TRUNC_TOOL, tabTitle=_TRUNC_TOOL,
                               hostIp=IP_LONG)
        pid_long = r_long['process_id']

        # Short IP: 10 chars — no truncation
        r_short = wc.runCommand(command='echo trunc_short',
                                name=_TRUNC_TOOL, tabTitle=_TRUNC_TOOL,
                                hostIp=IP_SHORT)
        pid_short = r_short['process_id']

        _wait_proc_done_api(pid_long, timeout=20)
        _wait_proc_done_api(pid_short, timeout=20)
        time.sleep(2.0)

        # Navigate to Tools tab and click the trunc-test-tool entry
        _switch_left_tab(drv, 'tools-panel-left')
        tool_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#tools-body tr[data-tool-id="{_TRUNC_TOOL}"]')))
        js(drv, 'arguments[0].click()', tool_row)
        time.sleep(1.5)

        type(self)._pid_long  = str(pid_long)
        type(self)._pid_short = str(pid_short)

        yield

        _switch_left_tab(drv, 'hosts-panel')

    def _get_host_td(self, drv, proc_id):
        row = W(drv, 5).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#tool-hosts-body tr[data-process-id="{proc_id}"]')))
        return row.find_elements(By.TAG_NAME, 'td')[0]

    # ── Long IP ────────────────────────────────────────────────────────────

    def test_long_ip_display_is_truncated(self, drv, srv):
        """A 20-char hostIp is shown as at most 19 chars (18 + '…')."""
        td = self._get_host_td(drv, self._pid_long)
        # strip the ★ prefix if present
        text = td.text.replace('★ ', '').strip()
        assert len(text) <= 19, \
            f"Expected ≤19 chars for long IP, got {len(text)}: '{text}'"

    def test_long_ip_ends_with_ellipsis(self, drv, srv):
        """Truncated cell text ends with the ellipsis character '…'."""
        td = self._get_host_td(drv, self._pid_long)
        text = td.text.replace('★ ', '').strip()
        assert text.endswith('…'), \
            f"Expected text to end with '…', got '{text}'"

    def test_long_ip_first_18_chars_correct(self, drv, srv):
        """The first 18 chars of the truncated display match the hostIp."""
        td = self._get_host_td(drv, self._pid_long)
        text = td.text.replace('★ ', '').strip().rstrip('…')
        expected = IP_LONG[:18]
        assert text == expected, \
            f"Expected truncated prefix '{expected}', got '{text}'"

    def test_long_ip_title_attr_has_full_value(self, drv, srv):
        """The <td> title attribute contains the complete untruncated hostIp."""
        td = self._get_host_td(drv, self._pid_long)
        title = td.get_attribute('title') or ''
        assert title == IP_LONG, \
            f"Expected title='{IP_LONG}', got '{title}'"

    # ── Short IP ───────────────────────────────────────────────────────────

    def test_short_ip_not_truncated(self, drv, srv):
        """A 10-char hostIp is displayed in full with no truncation."""
        td = self._get_host_td(drv, self._pid_short)
        text = td.text.replace('★ ', '').strip()
        assert IP_SHORT in text, \
            f"Expected full IP '{IP_SHORT}' in cell text, got '{text}'"
        assert '…' not in text, \
            f"Short IP should NOT be truncated, got '{text}'"

    def test_short_ip_no_title_attr(self, drv, srv):
        """Short IPs do not get a title attribute (tooltip would be redundant)."""
        td = self._get_host_td(drv, self._pid_short)
        title = td.get_attribute('title') or ''
        assert title == '', \
            f"Short IP should have empty title, got '{title}'"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.78 — AI compare dropdown placeholder logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestAICompareDropdown:
    """AI comparison dropdown shows a context-sensitive first option:
    - No history matches → '— No similar hosts in history —' (greyed, non-selectable)
    - History match ≥ 95% Jaccard → '— Select a host to compare —' (neutral prompt)
      followed by the match entries so the user can opt out of comparing."""

    _history_session_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        # Select IP_A (has ports 22+80 which we'll use for fingerprint matching)
        host_a_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_A}"]')))
        js(drv, 'arguments[0].click()', host_a_row)
        time.sleep(1.0)
        type(self)._host_a_id = _get_host_id(IP_A)
        yield
        # Cleanup: remove any injected history record
        if type(self)._history_session_id is not None:
            try:
                import sqlite3, os as _os
                db_path = _os.path.expanduser('~/.local/share/legion/ai_history.db')
                if _os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    conn.execute('DELETE FROM ai_sessions WHERE id=?',
                                 (type(self)._history_session_id,))
                    conn.commit(); conn.close()
            except Exception:
                pass

    def _open_ai_tab(self, drv):
        """Click the AI tab and wait for the dropdown to populate.
        Clicks Notes first so the AI tab is never already-active (avoids any
        initTabBar guards that could suppress same-tab re-clicks)."""
        js(drv, "var b=document.querySelector('[data-tab=\"notes-right\"]'); if(b) b.click();")
        time.sleep(0.2)
        ai_btn = W(drv, 5).until(EC.presence_of_element_located((By.ID, 'ai-tab-btn')))
        js(drv, 'arguments[0].click()', ai_btn)
        time.sleep(2.5)  # async fetch + render

    def _first_option_text(self, drv):
        # #ai-compare-select lives inside #ai-results (display:none until analysis runs).
        # Selenium returns '' for elements inside hidden containers — read via JS instead.
        result = js(drv, "var s=document.getElementById('ai-compare-select');"
                         "return s&&s.options.length?s.options[0].text:null;")
        return result if result is not None else ''

    def _first_option_value(self, drv):
        # Must NOT use Python `or` fallback — an empty string value '' is valid and falsy.
        result = js(drv, "var s=document.getElementById('ai-compare-select');"
                         "return s&&s.options.length?s.options[0].value:null;")
        return result if result is not None else '__MISSING__'

    def _option_count(self, drv):
        return js(drv, "var s=document.getElementById('ai-compare-select');"
                       "return s?s.options.length:0;") or 0

    # ── No history ─────────────────────────────────────────────────────────

    def test_no_history_first_option_says_no_similar(self, drv, srv):
        """Without AI history the first option is 'No similar hosts in history'."""
        self._open_ai_tab(drv)
        text = self._first_option_text(drv)
        assert 'No similar hosts' in text, \
            f"Expected 'No similar hosts' without history, got: '{text}'"

    def test_no_history_first_option_has_empty_value(self, drv, srv):
        """The no-similar-hosts option has value='' (cannot trigger a compare)."""
        val = self._first_option_value(drv)
        assert val == '', f"Expected value='' for no-history option, got '{val}'"

    def test_no_history_only_one_option(self, drv, srv):
        """Without history there is exactly one option in the dropdown."""
        count = self._option_count(drv)
        assert count == 1, \
            f"Expected exactly 1 option with no history, found {count}"

    # ── With history (inject matching fingerprint) ─────────────────────────

    def test_with_history_first_option_is_select_prompt(self, drv, srv):
        """With a ≥95%-similar history record the first option is the neutral
        'Select a host to compare' prompt — not the match itself."""
        from app.ai import history_db
        # Build a fingerprint matching the seeded host (ports 22/tcp:ssh, 80/tcp:http)
        # Fingerprint must match the live host's exactly for Jaccard ≥ 0.95.
        # The test host shows os='unknown' so _assemble_host_data includes
        # 'OS:unknown' in the fingerprint — must match that token exactly.
        fp = history_db.build_fingerprint([
            {'portId': '22', 'protocol': 'tcp', 'name': 'ssh',  'version': ''},
            {'portId': '80', 'protocol': 'tcp', 'name': 'http', 'version': ''},
        ], os_family='unknown')
        sid = history_db.save_session(
            host_ip=IP_A, project_name='selenium-test',
            fingerprint=fp,
            phase1_json='[]', phase2_markdown='# Test Match',
            tokens_input=10, tokens_output=5, cost_usd=0.001)
        type(self)._history_session_id = sid

        # Re-open the AI tab to reload the dropdown
        self._open_ai_tab(drv)
        text = self._first_option_text(drv)
        assert 'Select' in text and 'compare' in text.lower(), \
            f"Expected 'Select a host to compare' prompt, got: '{text}'"

    def test_with_history_first_option_empty_value(self, drv, srv):
        """The select-prompt first option has value='' so deselection hides compare."""
        val = self._first_option_value(drv)
        assert val == '', \
            f"Expected value='' for the neutral prompt, got '{val}'"

    def test_with_history_second_option_is_match(self, drv, srv):
        """After the neutral prompt the match entry appears as the second option."""
        count = self._option_count(drv)
        assert count >= 2, \
            f"Expected at least 2 options with a history match, found {count}"
        match_text = js(drv, "var s=document.getElementById('ai-compare-select');"
                             "return s&&s.options.length>1?s.options[1].text:'';") or ''
        assert 'match' in match_text.lower() or IP_A in match_text, \
            f"Second option should be the match entry, got: '{match_text}'"

    def test_with_history_match_option_has_nonzero_value(self, drv, srv):
        """The match option has a non-empty value (the session id)."""
        count = self._option_count(drv)
        if count < 2:
            pytest.skip("Match option not present")
        val = js(drv, "var s=document.getElementById('ai-compare-select');"
                      "return s&&s.options.length>1?s.options[1].value:null;")
        assert val not in ('', None), \
            f"Match option should have a session id as value, got '{val}'"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.80 — Ctrl+B from lower panel saves to process's host, not selected host
# ═══════════════════════════════════════════════════════════════════════════════

_CTRLB_MARKER = 'CTRLB_SELENIUM_MARKER_77'


class TestCtrlBProperHost:
    """When Ctrl+B is triggered from the lower output panel (plain-output) while
    a process from host B is displayed but host A is selected in the host list,
    the note is appended to host B's notes — not host A's."""

    _proc_b_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']
        # Clear any prior notes on both hosts
        host_a_id = _get_host_id(IP_A)
        host_b_id = _get_host_id(IP_B)
        if host_a_id:
            _req.post(f'{BASE}/api/workspace/hosts/{host_a_id}/note',
                      json={'note': ''}, timeout=5)
        if host_b_id:
            _req.post(f'{BASE}/api/workspace/hosts/{host_b_id}/note',
                      json={'note': ''}, timeout=5)
        time.sleep(0.3)

        # Run a process for IP_B with distinctive output
        r = wc.runCommand(command=f'echo {_CTRLB_MARKER}',
                          name='ctrlb-host-test', tabTitle='ctrlb-host-test',
                          hostIp=IP_B)
        pid = r['process_id']
        type(self)._proc_b_id = str(pid)
        _wait_proc_done_api(pid, timeout=20)
        time.sleep(2.0)

        # Select IP_A in the host list so L.selectedHostId = host_a_id
        host_a_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_A}"]')))
        js(drv, 'arguments[0].click()', host_a_row)
        time.sleep(1.0)

        # Click the IP_B process row in the processes table
        # This loads its output in #plain-output but leaves L.selectedHostId = IP_A
        proc_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))
        js(drv, 'arguments[0].click()', proc_row)
        time.sleep(1.5)  # wait for loadProcessOutput() to fill plain-output

        # Verify output is loaded in plain-output
        po = drv.find_element(By.ID, 'plain-output')
        W(drv, 5).until(lambda d: _CTRLB_MARKER in d.find_element(By.ID, 'plain-output').text)

        # Simulate mousedown on plain-output → sets _lastNonXtermSelSource='plain-output'
        js(drv,
           "document.getElementById('plain-output')"
           ".dispatchEvent(new MouseEvent('mousedown', {bubbles:true,cancelable:true}))")
        time.sleep(0.1)

        # Create a text selection covering the full plain-output content
        js(drv, """
            var el = document.getElementById('plain-output');
            var rng = document.createRange();
            rng.selectNodeContents(el);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(rng);
        """)
        time.sleep(0.1)

        # Trigger Ctrl+B via bubble-phase keyboard event on document body
        ActionChains(drv).key_down(Keys.CONTROL).send_keys('b').key_up(Keys.CONTROL).perform()
        time.sleep(2.5)  # async: fetchJson + postJson for different-host case

        type(self)._host_a_id = host_a_id
        type(self)._host_b_id = host_b_id
        yield

    def test_note_saved_to_process_host_b(self, drv, srv):
        """The selection is appended to host B's notes (the process's host)."""
        note = _get_host_note(self._host_b_id)
        assert _CTRLB_MARKER in note, \
            f"Expected marker '{_CTRLB_MARKER}' in host B's notes, got: '{note[:200]}'"

    def test_note_not_saved_to_selected_host_a(self, drv, srv):
        """The selection is NOT appended to host A's notes (the selected host)."""
        note = _get_host_note(self._host_a_id)
        assert _CTRLB_MARKER not in note, \
            f"Marker should NOT be in host A's notes, got: '{note[:200]}'"

    def test_note_contains_selection_header(self, drv, srv):
        """The note on host B includes the '=== Selection from ...' header."""
        note = _get_host_note(self._host_b_id)
        assert '=== Selection from' in note, \
            f"Expected selection header in host B's note, got: '{note[:200]}'"

    def test_host_b_note_unread_indicator_set(self, drv, srv):
        """After Ctrl+B to a different host, that host's Notes tab is marked unread
        in _hostUnreadTabs so the orange indicator appears when navigating to it."""
        target_id = self._host_b_id
        # The JS state: L._hostUnreadTabs[host_b_id]['notes-right'] should be truthy
        result = js(drv,
            f"var t=L._hostUnreadTabs[{target_id}]; "
            f"return t && t['notes-right'] ? true : false;")
        assert result is True, \
            f"Expected host B ({target_id}) notes-right to be marked unread in _hostUnreadTabs"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.82 — Process queue advances immediately after kill
# ═══════════════════════════════════════════════════════════════════════════════

class TestProcessQueueAfterKill:
    """Killing a running process must trigger checkProcessQueue() immediately so
    the next waiting process starts within seconds — not after the orphaned
    grandchild tool eventually exits on its own (which could take minutes)."""

    _pid1 = None   # long-running process (will be killed)
    _pid2 = None   # queued process (must start quickly after kill)
    _kill_time = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']
        # Force concurrency limit to 1 so the second process is queued
        orig_max = getattr(wc.settings, 'general_max_fast_processes', 5)
        wc.settings.general_max_fast_processes = 1

        # Process 1: long-running — occupies the single slot
        r1 = wc.runCommand(command='sleep 120',
                           name='queue-kill-proc1', tabTitle='queue-kill-proc1',
                           hostIp=IP_A)
        pid1 = r1['process_id']

        # Wait for it to actually start (Running), not just Queued
        _wait_proc_status(pid1, 'Running', timeout=15)

        # Process 2: quick echo — must queue behind process 1
        r2 = wc.runCommand(command='echo queue_started',
                           name='queue-kill-proc2', tabTitle='queue-kill-proc2',
                           hostIp=IP_A)
        pid2 = r2['process_id']
        time.sleep(1.0)  # let queue logic settle

        type(self)._pid1 = str(pid1)
        type(self)._pid2 = str(pid2)

        yield

        # Restore max processes
        wc.settings.general_max_fast_processes = orig_max
        # Kill any remaining processes
        try: _req.post(f'{BASE}/api/processes/{pid1}/kill', timeout=5)
        except Exception: pass
        try: _req.post(f'{BASE}/api/processes/{pid2}/kill', timeout=5)
        except Exception: pass

    def test_proc1_is_running_before_kill(self, drv, srv):
        """Process 1 (sleep 120) is Running before the kill."""
        for p in _snapshot().get('processes', []):
            if str(p.get('id')) == self._pid1:
                assert p.get('status') == 'Running', \
                    f"Expected proc1 status=Running, got {p.get('status')}"
                return
        pytest.fail(f"Process {self._pid1} not found in snapshot")

    def test_proc2_is_waiting_before_kill(self, drv, srv):
        """Process 2 (echo) is Waiting (queued) because slot is occupied."""
        for p in _snapshot().get('processes', []):
            if str(p.get('id')) == self._pid2:
                status = p.get('status')
                assert status == 'Waiting', \
                    f"Expected proc2 status=Waiting before kill, got '{status}'"
                return
        pytest.fail(f"Process {self._pid2} not found in snapshot")

    def test_kill_proc1_via_api(self, drv, srv):
        """Killing process 1 via the API returns status=ok."""
        r = _req.post(f'{BASE}/api/processes/{self._pid1}/kill', timeout=5)
        assert r.ok, f"Kill API returned {r.status_code}"
        type(self)._kill_time = time.time()

    def test_proc2_starts_within_10_seconds_of_kill(self, drv, srv):
        """Process 2 transitions from Waiting to Running within 10 seconds of the kill.
        Without the fix this would take until sleep 120 finished (~2 minutes).
        With checkProcessQueue() called directly from killProcess() it is near-instant."""
        if self._kill_time is None:
            pytest.skip("Kill API test did not run")
        deadline = self._kill_time + 10
        while time.time() < deadline:
            for p in _snapshot().get('processes', []):
                if str(p.get('id')) == self._pid2:
                    if p.get('status') in ('Running', 'Finished'):
                        elapsed = time.time() - self._kill_time
                        assert elapsed < 10, \
                            f"Process 2 started after {elapsed:.1f}s (expected <10s)"
                        return
            time.sleep(0.5)
        pytest.fail(
            f"Process {self._pid2} did not start within 10s of killing process 1. "
            f"This indicates checkProcessQueue() was not called immediately after kill.")

    def test_proc1_is_killed_not_running(self, drv, srv):
        """After the kill, process 1 is no longer Running (status=Killed or Crashed)."""
        for p in _snapshot().get('processes', []):
            if str(p.get('id')) == self._pid1:
                status = p.get('status')
                assert status in ('Killed', 'Crashed', 'Finished'), \
                    f"Expected proc1 to be Killed after kill API, got '{status}'"
                return
        # Process might have been removed from snapshot (closed); that's also fine
