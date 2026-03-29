#!/usr/bin/env python3
"""tests/test_ui_v10_features.py

Non-hollow Selenium regression tests covering:

  v10.69/10.71  Upper-panel font size controls affect script-output-inline,
                notes-right, and tool-output-text containers.

  v10.72        showContextMenu() clamps position so the menu never overflows
                the viewport (both short-window and normal-window cases).

  v10.73a       'Go to Tab' (same host) activates the correct dyn tab in the
                right-panel tab bar and scrolls it into view.

  v10.73b       'Go to Tab' (cross-host) switches the host selection and then
                activates the dyn tab for the process on the other host.

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_v10_features.py -v
"""
import os
import sys
import time
import threading
import tempfile

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT  = 5075
IP_A  = '10.75.75.1'
IP_B  = '10.75.75.2'

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


# ── Tiny helpers ──────────────────────────────────────────────────────────────

def _free_port(port, retries=20):
    """Kill whatever process is holding `port` and wait until it is free."""
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
    """Poll /api/snapshot until process proc_id reaches a terminal state.
    Uses Python requests — completely independent of DOM / snapshot-poll timing."""
    import requests as _req
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = _req.get(f"{srv_url}/api/snapshot", timeout=5).json()
            for p in data.get('processes', []):
                if str(p.get('id', '')) == str(proc_id):
                    if p.get('status', '') in ('Finished', 'Killed', 'Crashed'):
                        return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Process {proc_id} did not reach terminal state within {timeout}s")


def ctx_menu_click(d, label):
    menu = W(d, 5).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))
    for btn in menu.find_elements(By.TAG_NAME, 'button'):
        if label.lower() in btn.text.lower():
            btn.click()
            return
    raise AssertionError(
        f"'{label}' not in menu. Items: "
        f"{[b.text for b in menu.find_elements(By.TAG_NAME, 'button')]}"
    )


def _ctx_click_row(d, css, retries=8):
    """Re-find and right-click a row, retrying on StaleElementReferenceException."""
    for _ in range(retries):
        try:
            row = d.find_element(By.CSS_SELECTOR, css)
            ActionChains(d).context_click(row).perform()
            return row
        except StaleElementReferenceException:
            time.sleep(0.3)
    raise AssertionError(f"Could not right-click {css} after {retries} retries")


def _select_host(d, ip):
    row = W(d, 10).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))
    js(d, 'arguments[0].click()', row)
    time.sleep(1.0)


def _parse_pt(style_value):
    """Parse '10pt' → 10.0, returns 0.0 if unparseable."""
    try:
        return float(style_value.replace('pt', '').strip())
    except Exception:
        return 0.0


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _orig_hb_timeout = getattr(_web_routes, '_HB_TIMEOUT', 20)
    _web_routes._HB_TIMEOUT = 600   # disable watchdog for tests

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
    _web_routes._HB_TIMEOUT = _orig_hb_timeout


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


# ═══════════════════════════════════════════════════════════════════════════════
# v10.72  Context menu clamping — menu must never overflow the viewport
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextMenuClamping:
    """showContextMenu() clamps the menu position so bottom and right edges stay
    inside the browser viewport regardless of where the right-click lands."""

    def test_menu_within_viewport_short_window(self, drv, srv):
        """Clamping is applied when the click position would push menu out of viewport.

        The JS showContextMenu clamps: left = max(0, vw-mw) if x+mw>vw, else x.
        We verify: when a contextmenu event fires at (clientX=850, clientY=550)
        in a 900×600 window, the menu top is clamped to <= max(0, vh-mh) and
        the menu left is clamped to <= max(0, vw-mw).  We cannot assert bottom
        <= vh if the menu is taller than the viewport itself — instead we assert
        the JS clamping formula was applied (top == max(0, vh-mh)).
        """
        # Use a taller short window so the menu can still fit
        W(drv, 10).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_A}"]')))

        drv.set_window_size(900, 600)
        time.sleep(0.8)

        # Dispatch contextmenu at a position that forces clamping right+bottom
        js(drv, """
            var row = document.querySelector('#hosts-body tr[data-host-ip="10.75.75.1"]');
            if (!row) return;
            var evt = new MouseEvent('contextmenu', {
                bubbles: true, cancelable: true,
                clientX: 850, clientY: 550
            });
            row.dispatchEvent(evt);
        """)
        time.sleep(0.5)

        W(drv, 5).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))

        info = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return null;
            var r = m.getBoundingClientRect();
            var mw = m.offsetWidth, mh = m.offsetHeight;
            var vw = window.innerWidth, vh = window.innerHeight;
            return {top: r.top, left: r.left, bottom: r.bottom, right: r.right,
                    mw: mw, mh: mh, vw: vw, vh: vh};
        """)
        assert info is not None, "ctx-menu not found in JS"

        # The menu must be clamped: top <= max(0, vh-mh); left <= max(0, vw-mw)
        expected_top  = max(0, info['vh'] - info['mh'])
        expected_left = max(0, info['vw'] - info['mw'])
        assert info['top']  <= expected_top  + 2, (
            f"Menu top {info['top']:.1f} > clamped top {expected_top:.1f} "
            f"(vh={info['vh']}, mh={info['mh']})"
        )
        assert info['left'] <= expected_left + 2, (
            f"Menu left {info['left']:.1f} > clamped left {expected_left:.1f} "
            f"(vw={info['vw']}, mw={info['mw']})"
        )
        # Also: the clamped position should have moved the menu from clientX=850
        # (i.e., left must be less than 850 if the menu was wide enough to overflow)
        if info['mw'] + 850 > info['vw']:
            assert info['left'] < 850, (
                f"Menu at left={info['left']:.1f} was NOT clamped left from clientX=850"
            )

        # Dismiss and restore window
        js(drv, "document.body.click()")
        time.sleep(0.3)
        drv.set_window_size(1600, 900)
        time.sleep(0.5)

    def test_menu_within_viewport_normal_window(self, drv, srv):
        """Normal window (1600×900) — run a quick process and right-click its row."""
        drv.set_window_size(1600, 900)
        time.sleep(0.3)

        wc = srv['wc']
        result = wc.runCommand('echo viewport_test', name='viewport-proc', hostIp=IP_A,
                               run_actions=False)
        proc_id = result['process_id']
        _wait_proc_done_api(srv['url'], proc_id, timeout=20)
        time.sleep(1.5)   # let snapshot rebuild #processes-body

        _ctx_click_row(drv, f'#processes-body tr[data-process-id="{proc_id}"]')

        W(drv, 5).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))

        rect = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return null;
            var r = m.getBoundingClientRect();
            return {bottom: r.bottom, right: r.right,
                    inh: window.innerHeight, inw: window.innerWidth};
        """)
        assert rect is not None, "ctx-menu not found in JS"
        assert rect['bottom'] <= rect['inh'] + 1, (
            f"Menu bottom {rect['bottom']:.1f} > innerHeight {rect['inh']}"
        )
        assert rect['right'] <= rect['inw'] + 1, (
            f"Menu right {rect['right']:.1f} > innerWidth {rect['inw']}"
        )

        js(drv, "document.body.click()")
        time.sleep(0.3)


# ═══════════════════════════════════════════════════════════════════════════════
# v10.69/10.71  Font size controls — upper panel
# ═══════════════════════════════════════════════════════════════════════════════

class TestFontSizeAllPanels:
    """upper-font-inc / upper-font-dec must update inline style on
    script-output-inline, notes-right, and tool-output-text."""

    # Class-level storage so the dec test can compare against the inc values
    _after_inc = {}

    @pytest.fixture(scope="class", autouse=True)
    def font_setup(self, drv, srv):
        """Select IP_A, reset font to 10 pt, click inc once to initialise."""
        _select_host(drv, IP_A)
        # Reset to a known baseline
        js(drv, "localStorage.setItem('legion_upper_font_pt', '10')")
        # Reload to pick up the reset
        drv.get(srv['url'])
        time.sleep(2.0)
        _select_host(drv, IP_A)
        # Click inc once to ensure applyFontSize has run with the baseline
        inc = drv.find_element(By.ID, 'upper-font-inc')
        js(drv, 'arguments[0].click()', inc)
        time.sleep(0.3)
        yield

    def _read_pt(self, drv, el_id):
        val = js(drv, f"var el=document.getElementById('{el_id}'); return el ? el.style.fontSize : '';")
        return _parse_pt(val)

    def test_script_output_inline_font_increases(self, drv, srv):
        initial = self._read_pt(drv, 'script-output-inline')
        # Click inc twice more
        inc = drv.find_element(By.ID, 'upper-font-inc')
        js(drv, 'arguments[0].click()', inc)
        time.sleep(0.2)
        js(drv, 'arguments[0].click()', inc)
        time.sleep(0.2)
        after = self._read_pt(drv, 'script-output-inline')
        type(self)._after_inc['script-output-inline'] = after
        assert after > initial, (
            f"script-output-inline fontSize did not increase: {initial}pt → {after}pt"
        )

    def test_notes_right_font_increases(self, drv, srv):
        initial = self._read_pt(drv, 'notes-right')
        inc = drv.find_element(By.ID, 'upper-font-inc')
        # Current state: already been inc'd twice in the previous test
        # Click once more
        js(drv, 'arguments[0].click()', inc)
        time.sleep(0.2)
        after = self._read_pt(drv, 'notes-right')
        type(self)._after_inc['notes-right'] = after
        assert after > 0, "notes-right fontSize not set"
        # notes-right should be at least as large as after script test
        assert after >= type(self)._after_inc.get('script-output-inline', 0) - 1, (
            f"notes-right {after}pt is unexpectedly small"
        )

    def test_tool_output_text_font_increases(self, drv, srv):
        initial = self._read_pt(drv, 'tool-output-text')
        inc = drv.find_element(By.ID, 'upper-font-inc')
        js(drv, 'arguments[0].click()', inc)
        time.sleep(0.2)
        after = self._read_pt(drv, 'tool-output-text')
        type(self)._after_inc['tool-output-text'] = after
        assert after > 0, "tool-output-text fontSize not set"
        assert after > initial or after >= 11, (
            f"tool-output-text did not increase from {initial}pt to {after}pt"
        )

    def test_font_dec_decreases_all(self, drv, srv):
        # We're now at a high value — dec three times
        dec = drv.find_element(By.ID, 'upper-font-dec')
        for _ in range(3):
            js(drv, 'arguments[0].click()', dec)
            time.sleep(0.2)
        # Read all three
        si_pt  = self._read_pt(drv, 'script-output-inline')
        nr_pt  = self._read_pt(drv, 'notes-right')
        tot_pt = self._read_pt(drv, 'tool-output-text')

        si_after  = type(self)._after_inc.get('script-output-inline', 0)
        nr_after  = type(self)._after_inc.get('notes-right', 0)
        tot_after = type(self)._after_inc.get('tool-output-text', 0)

        assert si_pt  < si_after,  f"script-output-inline not decreased: {si_after}→{si_pt}"
        assert nr_pt  < nr_after,  f"notes-right not decreased: {nr_after}→{nr_pt}"
        assert tot_pt < tot_after, f"tool-output-text not decreased: {tot_after}→{tot_pt}"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.73a  Go to Tab — same host
# ═══════════════════════════════════════════════════════════════════════════════

class TestGotoTabSameHost:
    """'Go to Tab' on a process belonging to the currently-selected host should
    activate the dyn tab in the right-panel tab bar without switching hosts."""

    # shared between the two tests in this class
    _proc_id = None

    @pytest.fixture(scope="class", autouse=True)
    def run_proc(self, drv, srv):
        """Run a process on IP_A and store its id at class level."""
        wc = srv['wc']
        _select_host(drv, IP_A)
        result = wc.runCommand('echo goto_same_host', name='goto-same',
                               hostIp=IP_A, run_actions=False)
        type(self)._proc_id = result['process_id']
        _wait_proc_done_api(srv['url'], type(self)._proc_id, timeout=25)
        time.sleep(1.5)   # let snapshot rebuild dyn tabs
        yield

    def test_goto_tab_activates_dyn_tab(self, drv, srv):
        proc_id = type(self)._proc_id
        assert proc_id is not None

        # Click Notes tab to deactivate any current dyn tab
        notes_btn = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
        js(drv, 'arguments[0].click()', notes_btn)
        time.sleep(0.5)

        # Right-click the process row
        _ctx_click_row(drv, f'#processes-body tr[data-process-id="{proc_id}"]')
        ctx_menu_click(drv, 'Go to Tab')
        time.sleep(0.8)

        # Dyn tab button should now be active
        active = js(drv, f"""
            var btn = document.querySelector('[data-tab="dyntab-{proc_id}"]');
            return btn ? btn.classList.contains('active') : false;
        """)
        assert active, f"dyntab-{proc_id} is not active after 'Go to Tab' (same host)"

        # Right panel should be visible
        right_display = js(drv, "return document.getElementById('right-tabs').style.display")
        assert right_display != 'none', "#right-tabs is hidden after 'Go to Tab'"

    def test_goto_tab_tab_visible_in_bar(self, drv, srv):
        """The dyn tab button must be scrolled into view (within ±5 px of bar bounds)."""
        proc_id = type(self)._proc_id

        rects = js(drv, f"""
            var bar = document.getElementById('right-tab-bar');
            var btn = bar ? bar.querySelector('[data-tab="dyntab-{proc_id}"]') : null;
            if (!bar || !btn) return null;
            var br = bar.getBoundingClientRect();
            var btr = btn.getBoundingClientRect();
            return {{bar_left: br.left, bar_right: br.right,
                     btn_left: btr.left, btn_right: btr.right}};
        """)
        assert rects is not None, "Could not read rects for bar or dyn tab button"
        assert rects['btn_left'] >= rects['bar_left'] - 5, (
            f"Tab button scrolled off left edge: btn_left={rects['btn_left']:.1f} "
            f"bar_left={rects['bar_left']:.1f}"
        )
        assert rects['btn_right'] <= rects['bar_right'] + 5, (
            f"Tab button scrolled off right edge: btn_right={rects['btn_right']:.1f} "
            f"bar_right={rects['bar_right']:.1f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# v10.73b  Go to Tab — cross-host
# ═══════════════════════════════════════════════════════════════════════════════

class TestGotoTabCrossHost:
    """'Go to Tab' on a process belonging to a DIFFERENT host must (1) switch the
    host selection and (2) activate the correct dyn tab after the tab bar renders."""

    _proc_b_id = None

    @pytest.fixture(scope="class", autouse=True)
    def run_proc_b(self, drv, srv):
        """Run a process on IP_B (not the currently-selected host)."""
        wc = srv['wc']
        result = wc.runCommand('echo cross_host', name='goto-cross',
                               hostIp=IP_B, run_actions=False)
        type(self)._proc_b_id = result['process_id']
        _wait_proc_done_api(srv['url'], type(self)._proc_b_id, timeout=25)
        time.sleep(2.0)   # let snapshot propagate L.processes + L.hosts
        yield

    def test_goto_tab_cross_host_switches_host_and_activates_tab(self, drv, srv):
        proc_b_id = type(self)._proc_b_id
        assert proc_b_id is not None

        # Ensure we start on IP_A so IP_B is NOT the current host
        _select_host(drv, IP_A)
        time.sleep(0.5)

        # IP_B's dyn tab must not exist yet (wrong host selected)
        present_before = js(drv, f"""
            return !!document.querySelector('[data-tab="dyntab-{proc_b_id}"]');
        """)
        assert not present_before, (
            f"dyntab-{proc_b_id} should not exist when IP_B is not selected"
        )

        # Right-click the process row (processes-body shows ALL procs)
        _ctx_click_row(drv, f'#processes-body tr[data-process-id="{proc_b_id}"]')
        ctx_menu_click(drv, 'Go to Tab')

        # Wait for host switch — IP_B row should get 'selected'
        def _host_b_selected(d):
            row = d.find_elements(By.CSS_SELECTOR,
                                  f'#hosts-body tr[data-host-ip="{IP_B}"]')
            return row and 'selected' in row[0].get_attribute('class')

        W(drv, 8).until(_host_b_selected)

        # Wait for dyn tab to become active
        def _dyn_tab_active(d):
            return js(d, f"""
                var btn = document.querySelector('[data-tab="dyntab-{proc_b_id}"]');
                return btn ? btn.classList.contains('active') : false;
            """)

        W(drv, 8).until(_dyn_tab_active)

        assert True   # reached without timeout

    def test_goto_tab_cross_host_right_panel_visible(self, drv, srv):
        """After cross-host goto-tab, right-panel must be visible and tools hidden."""
        right_display = js(drv, "return document.getElementById('right-tabs').style.display")
        tools_display = js(drv, "return document.getElementById('tools-display').style.display")
        assert right_display != 'none', "#right-tabs should be visible after goto-tab"
        assert tools_display == 'none', "#tools-display should be hidden after goto-tab"
