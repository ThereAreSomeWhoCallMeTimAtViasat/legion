#!/usr/bin/env python3
"""tests/test_ui_v10c_features.py

Non-hollow Selenium regression tests for features added in the 2026-03-30 session.

  v10.98  Scan uptime clock — #scan-uptime appears in the process bar once a
          non-interactive process starts Running, ticks every second (the JS
          interval fires independently of the 1.5 s snapshot poll), and is
          displayed with the correct "Xs" / "Xm Ys" format.  Hidden until the
          first scan of the session starts.

  v10.106 Tools tab auto-select — clicking the Tools left tab for the first
          time automatically selects the first tool entry, populates the middle
          pane (#tool-hosts-body) with host rows, and loads output in the right
          pane (#tool-output-text).  Switching away to Hosts and back restores
          the same tool+host selection instead of showing an empty pane.

  v10.110 Match navigation full output — when a process has has_match=True and
          its output length exceeds the previous 50 000-char display limit, the
          fix loads up to 2 MB so the matched keyword is always in the rendered
          text.  The match navigation arrows must show count > 0 (not 0/0).

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_v10c_features.py -v
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
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5079
IP   = '10.79.79.1'
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


def _snapshot(timeout=5):
    return _req.get(f'{BASE}/api/snapshot', timeout=timeout).json()


def _wait_proc_status(proc_id, status, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in _snapshot().get('processes', []):
                if str(p.get('id')) == str(proc_id) and p.get('status') == status:
                    return p
        except Exception:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Process {proc_id} did not reach '{status}' in {timeout}s")


def _wait_proc_done(proc_id, timeout=30):
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
# v10.98 — Scan uptime clock in the process bar
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanUptimeClock:
    """#scan-uptime appears the moment a non-interactive process is Running,
    shows elapsed time in Xs / Xm Ys format, and persists (greyed) after
    the process finishes."""

    _proc_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']
        # Run a short sleep so the process is briefly Running
        r = wc.runCommand(command='sleep 3', name='uptime-test',
                          tabTitle='uptime-test', hostIp=IP)
        type(self)._proc_id = str(r['process_id'])
        # Wait for it to actually start Running before checking the UI
        _wait_proc_status(type(self)._proc_id, 'Running', timeout=10)
        time.sleep(2.5)   # let snapshot poll fire and JS _renderUptime() run
        yield
        # Let the sleep finish before next class
        _wait_proc_done(type(self)._proc_id, timeout=15)

    def _uptime_el(self, drv):
        return drv.find_element(By.ID, 'scan-uptime')

    def _uptime_val(self, drv):
        return js(drv, "var v=document.getElementById('scan-uptime-value'); return v?v.textContent.trim():'';")

    def test_uptime_element_exists_in_dom(self, drv, srv):
        """#scan-uptime must be in the DOM (it's always rendered, just hidden)."""
        el = drv.find_element(By.ID, 'scan-uptime')
        assert el is not None

    def test_uptime_becomes_visible_while_running(self, drv, srv):
        """The uptime clock is visible (display != 'none') while a process is Running."""
        display = js(drv, "return document.getElementById('scan-uptime').style.display")
        assert display != 'none', \
            f"#scan-uptime should be visible while a process is Running, got display='{display}'"

    def test_uptime_value_is_nonzero(self, drv, srv):
        """The uptime counter shows a positive elapsed time (not '0s' frozen)."""
        val = self._uptime_val(drv)
        assert val and val != '', f"#scan-uptime-value is empty"
        # Accept "Xs" or "Xm Ys" format — any non-zero reading
        assert val != '0s', f"Uptime should be > 0, got '{val}'"

    def test_uptime_format_is_correct(self, drv, srv):
        """Value must match the 'Xs', 'Xm Ys', or 'Xh Xm Ys' pattern."""
        import re
        val = self._uptime_val(drv)
        pattern = r'^(\d+h )?\d+m \d+s$|^\d+s$'
        assert re.match(pattern, val), \
            f"Uptime format wrong — expected '3s' or '1m 5s', got '{val}'"

    def test_uptime_is_amber_while_active(self, drv, srv):
        """The uptime span has amber/orange styling when a scan is active."""
        color = js(drv, "return getComputedStyle(document.getElementById('scan-uptime')).color")
        # Amber is typically rgb(232,160,32) or similar warm tone — not the muted grey
        assert color != 'rgb(119, 119, 119)', \
            f"Uptime should be amber/orange while active, not muted grey: {color}"

    def test_uptime_persists_after_process_finishes(self, drv, srv):
        """After the process finishes, the clock stays visible (greyed) with final elapsed."""
        _wait_proc_done(self._proc_id, timeout=10)
        time.sleep(2.5)  # let snapshot + _renderUptime update
        display = js(drv, "return document.getElementById('scan-uptime').style.display")
        assert display != 'none', \
            "Uptime clock should remain visible (greyed) after scan finishes"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.106 — Tools tab auto-selects first tool and remembers last selection
# ═══════════════════════════════════════════════════════════════════════════════

_TOOL_A = 'tools-auto-a'
_TOOL_B = 'tools-auto-b'


class TestToolsTabAutoSelect:
    """First click on the Tools left tab must auto-populate all three panes.
    Returning to the tab after switching away must restore the last selection."""

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']
        # Create processes with two different tool names so both appear in the list
        r_a = wc.runCommand(command='echo tool_a_output', name=_TOOL_A,
                            tabTitle=_TOOL_A, hostIp=IP)
        r_b = wc.runCommand(command='echo tool_b_output', name=_TOOL_B,
                            tabTitle=_TOOL_B, hostIp=IP)
        _wait_proc_done(str(r_a['process_id']), timeout=20)
        _wait_proc_done(str(r_b['process_id']), timeout=20)
        time.sleep(2.0)   # let snapshot rebuild tool list

        # Reset L.selectedTool to simulate a "first visit" by navigating to Hosts tab
        js(drv, "L.selectedTool = null;")
        # Navigate to Hosts tab to clear any existing tools-display state
        js(drv, "document.querySelector('[data-tab=\"hosts-panel\"]').click()")
        time.sleep(0.5)
        yield
        # Return to hosts tab for cleanup
        js(drv, "document.querySelector('[data-tab=\"hosts-panel\"]').click()")

    def _click_tools_tab(self, drv):
        js(drv, "document.querySelector('[data-tab=\"tools-panel-left\"]').click()")
        time.sleep(1.2)   # auto-select setTimeout(0) + updateToolHosts + loadProcessOutput

    def _tools_display_visible(self, drv):
        return js(drv, "return document.getElementById('tools-display').style.display") == 'flex'

    def _selected_tool(self, drv):
        return js(drv, "return L.selectedTool || null")

    def _middle_row_count(self, drv):
        return js(drv, "return document.querySelectorAll('#tool-hosts-body tr[data-process-id]').length")

    def _right_pane_text(self, drv):
        return js(drv, "return (document.getElementById('tool-output-text')||{}).textContent || ''")

    # ── First visit ────────────────────────────────────────────────────────

    def test_tools_display_shown_on_first_click(self, drv, srv):
        """Clicking Tools tab must always show #tools-display (even on first visit)."""
        self._click_tools_tab(drv)
        assert self._tools_display_visible(drv), \
            "#tools-display not shown after clicking Tools tab"

    def test_first_tool_auto_selected(self, drv, srv):
        """A tool must be selected automatically on first visit (L.selectedTool set)."""
        tool = self._selected_tool(drv)
        assert tool is not None and tool != '', \
            f"No tool was auto-selected on first click (L.selectedTool={tool!r})"

    def test_middle_pane_has_rows_after_auto_select(self, drv, srv):
        """#tool-hosts-body must have at least one process row after auto-select."""
        count = self._middle_row_count(drv)
        assert count >= 1, \
            f"Middle pane has {count} rows after auto-select — expected ≥1"

    def test_right_pane_has_output_after_auto_select(self, drv, srv):
        """#tool-output-text must contain output, not the placeholder 'Select a host'."""
        text = self._right_pane_text(drv)
        assert text.strip() and 'Select a host' not in text, \
            f"Right pane still shows placeholder after auto-select: {text[:80]!r}"

    # ── Return visit ───────────────────────────────────────────────────────

    def test_selected_tool_remembered_after_switch(self, drv, srv):
        """Navigating to Hosts and back must restore the previously selected tool."""
        before = self._selected_tool(drv)
        assert before, "Must have a selected tool before switching"

        # Switch away to Hosts
        js(drv, "document.querySelector('[data-tab=\"hosts-panel\"]').click()")
        time.sleep(0.4)

        # Switch back to Tools
        js(drv, "document.querySelector('[data-tab=\"tools-panel-left\"]').click()")
        time.sleep(0.8)

        after = self._selected_tool(drv)
        assert after == before, \
            f"Tool selection not remembered: was {before!r}, now {after!r}"

    def test_tools_display_restored_on_return(self, drv, srv):
        """#tools-display must be flex again when returning to Tools tab."""
        assert self._tools_display_visible(drv), \
            "#tools-display not shown when returning to Tools tab"

    def test_middle_pane_still_has_rows_on_return(self, drv, srv):
        """Middle pane rows are preserved (not cleared) on tab switch-and-return."""
        count = self._middle_row_count(drv)
        assert count >= 1, \
            f"Middle pane lost its rows on return: found {count}"

    def test_right_pane_preserved_on_return(self, drv, srv):
        """Right pane output persists (innerHTML not wiped) when returning to Tools tab."""
        text = self._right_pane_text(drv)
        assert text.strip() and 'Select a host' not in text, \
            f"Right pane output lost on return: {text[:80]!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.110 — Match navigation loads full output to find match beyond 50k chars
# ═══════════════════════════════════════════════════════════════════════════════

# 'proof' is in [MatchSettings] global-positive in legion.conf so it is loaded
# into the JS matchPositive array at page load and highlightMatches() will wrap
# it in .match-positive spans.  Do not use a custom keyword not in the conf.
_MATCH_KW = 'proof'


class TestMatchNavigationFullOutput:
    """When a process has has_match=True and its output exceeds 50 000 chars,
    loadProcessOutput must fetch up to 2 MB so the matched keyword is in the
    rendered text and the navigation arrows show count > 0 (not 0/0)."""

    _proc_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']

        # Build a command that produces >55 000 chars BEFORE the match keyword.
        # 1000 lines × ~57 chars each ≈ 57 000 chars, then a line with 'proof'.
        # The first 50 000 chars (old limit ≈ line 877) would NOT contain 'proof'
        # at line 1001, proving the fix (fetch up to 2 MB) is needed to find it.
        cmd = (
            f"python3 -c \""
            f"[print('L'+str(i).zfill(4)+':'+'X'*50) for i in range(1000)];"
            f"print('Found {_MATCH_KW} of concept here')\""
        )

        r = wc.runCommand(command=cmd, name='match-fullout-test',
                          tabTitle='match-fullout-test', hostIp=IP)
        pid = r['process_id']
        type(self)._proc_id = str(pid)
        _wait_proc_done(str(pid), timeout=30)

        # 'proof' is in global-positive in the conf so detectMatches() picks it up
        # during the readline loop — no manual injection needed.  But we also
        # inject directly as a belt-and-suspenders measure in case the match was
        # already stored and the snapshot key lookup needs it.
        tabTitle = 'match-fullout-test'
        if not wc._matches.get(f"{IP}:{tabTitle}"):
            wc._matches[f"{IP}:{tabTitle}"] = [_MATCH_KW]
        time.sleep(2.5)   # wait ≥1 snapshot cycle so has_match propagates to JS

        # Ensure we are on the Scan tab, Processes panel, click the process row
        js(drv, "document.querySelector('[data-tab=\"scan-tab\"]').click()")
        time.sleep(0.5)
        js(drv, "document.querySelector('[data-tab=\"processes-panel\"]') && "
                "document.querySelector('[data-tab=\"processes-panel\"]').click()")
        time.sleep(0.5)

        # Click the process row to load output
        proc_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))
        js(drv, 'arguments[0].click()', proc_row)
        # Wait for the output to load — large fetch may take a moment
        time.sleep(4.0)

        yield
        wc._matches.pop(f"{IP}:{tabTitle}", None)

    def _banner(self, drv):
        return drv.find_elements(By.CSS_SELECTOR, '#plain-output .match-banner')

    def _match_spans(self, drv):
        return js(drv, "return document.querySelectorAll('#plain-output .match-positive').length")

    def _counter_text(self, drv):
        return js(drv, "var c=document.querySelector('#plain-output .match-nav-counter');"
                       "return c?c.textContent.trim():'';")

    def _output_length(self, drv):
        return js(drv, "return (document.getElementById('plain-output')||{}).textContent.length || 0")

    # ── Verify the keyword is actually in the fetched output ───────────────

    def test_output_contains_keyword_in_displayed_text(self, drv, srv):
        """The match keyword must appear in the rendered plain-output content.
        Without the fix, only the first 50 000 chars are shown and the keyword
        (at ~57 000 chars) would be absent."""
        text = js(drv, "return document.getElementById('plain-output').textContent || ''")
        assert _MATCH_KW in text, \
            (f"Match keyword '{_MATCH_KW}' not found in displayed output "
             f"({len(text)} chars shown). The 50k truncation fix may not be working.")

    def test_output_is_larger_than_50k(self, drv, srv):
        """The displayed output must exceed 50 000 chars — proving the full output
        was fetched (not the old 50 k limit)."""
        length = self._output_length(drv)
        assert length > 50000, \
            f"Displayed output is only {length} chars — expected >50 000 (full fetch)"

    def test_match_banner_is_present(self, drv, srv):
        """A .match-banner element must be rendered when has_match=True."""
        banners = self._banner(drv)
        assert len(banners) >= 1, \
            "No .match-banner found — match banner not rendered for has_match process"

    def test_match_spans_count_greater_than_zero(self, drv, srv):
        """At least one .match-positive span must exist in the rendered output.
        Before the fix: 0 spans (keyword beyond 50k window). After: ≥1."""
        count = self._match_spans(drv)
        assert count >= 1, \
            (f"Found {count} .match-positive spans — expected ≥1. "
             f"The match keyword is in the output but was not highlighted, "
             f"suggesting the full-output fetch is not working.")

    def test_nav_counter_shows_nonzero(self, drv, srv):
        """The match navigation counter must NOT show '0 / 0' — it must reflect
        the actual number of match spans in the rendered output."""
        counter = self._counter_text(drv)
        assert counter, f"Navigation counter is empty"
        assert not counter.startswith('0'), \
            (f"Counter shows '{counter}' — still 0/0 despite keyword being present. "
             f"The navigation was not initialised on the full output.")

    def test_nav_counter_format_is_correct(self, drv, srv):
        """Counter must be in 'N ⁄ M' format with N=M=number of match spans."""
        import re
        counter = self._counter_text(drv)
        # Accept "1 / 1", "1 ⁄ 1" etc.
        assert re.search(r'\d', counter), \
            f"Counter has no digits: '{counter}'"
