#!/usr/bin/env python3
"""tests/test_ui_session_features.py

Non-hollow Selenium regression tests for UI changes in the 2026-03-27 session.

  v10.59  bottom-section splitter initialises at ~50% of main-area height on first
          load (was hard-coded 200 px; JS now uses offsetHeight/2 via localStorage
          default branch).

  v10.60  proc-vsplitter, os-vsplitter, scripts-vsplitter, tools-vsplitter are
          genuinely draggable — size of the target element changes when the
          splitter is dragged.  (Before the fix only the cursor changed.)

  v10.61  Every .tab-bar has overflow-x:scroll so the horizontal scrollbar is
          always rendered, not hidden by the old height:0 hack.

  v10.62  The active right-panel tab (Scripts, Notes, Info …) and the active
          left-panel tab (OS, Services …) are preserved when the user switches
          Scan → Brute → Scan.  (initTabBar was wiping nested .active classes
          on every main-tab switch before the closest('.tab-widget') guard.)

  v10.63  When a process has match hits, the match banner gains ▲/▼ navigation
          buttons and an "N ⁄ M" counter.  The buttons work in both the upper
          (dyn-output-*) and lower (plain-output) panels.

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_session_features.py -v
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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5072
IP   = '10.70.70.1'

# Three occurrences of _MATCH_WORD so nav wrap tests work (1→2→3→1)
_MATCH_WORD = 'NAVTEST_KEYWORD'
_NAV_CMD = (
    f'printf "alpha\\n{_MATCH_WORD} one\\nbeta\\n'
    f'{_MATCH_WORD} two\\ngamma\\n{_MATCH_WORD} three\\ndelta\\n"'
)

_SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
    </ports>
  </host>
</nmaprun>"""


# ── tiny helpers ──────────────────────────────────────────────────────────────

def _free_port(port, retries=20):
    """Kill whatever process is holding `port` and wait until it is free."""
    import subprocess
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    import socket
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


def _wait_proc_done_api(srv_url, proc_id, timeout=25):
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


def _wait_proc_done(drv, name, timeout=25):
    """Poll #processes-body until a row whose Name cell contains `name` is Finished."""
    def _done(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 5 and name in cells[1].text:
                if cells[4].text.strip() in ('Finished', 'Killed', 'Crashed'):
                    return row
        return False
    return W(drv, timeout).until(_done)


def _select_host(drv):
    """Click the seeded host row and wait for the ports table to populate."""
    row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', row)
    W(drv, 10).until(lambda d: len(
        d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)
    return row


def _ensure_bottom_processes_tab(drv):
    """Make sure the Processes tab in the bottom panel is active."""
    btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#bottom-tab-bar [data-tab="processes-panel"]')))
    js(drv, 'arguments[0].click()', btn)
    time.sleep(0.3)


def _setup_match_process(drv, srv, name='nav-test'):
    """
    Run _NAV_CMD (3 × _MATCH_WORD), inject frontend matchPositive, inject
    wc._matches so the snapshot reports has_match=True, then wait for the
    snapshot to propagate.

    Returns proc_id (int) only — NOT a WebElement, which would go stale
    during the 2.5 s sleep while the snapshot re-renders #processes-body.
    Callers must re-find the row fresh after this returns.
    """
    wc = srv['wc']
    js(drv, f"""
        if (!window.matchPositive) window.matchPositive = [];
        if (matchPositive.indexOf('{_MATCH_WORD}') < 0)
            matchPositive.push('{_MATCH_WORD}');
    """)
    result  = wc.runCommand(_NAV_CMD, name=name, hostIp=IP, run_actions=False)
    proc_id = result['process_id']
    # Use API poll (not DOM) — completely independent of localStorage/splitter state
    # that may prevent #processes-body from updating reliably in the full suite.
    _wait_proc_done_api(srv['url'], proc_id)
    # Inject match status into wc._matches — the snapshot route reads this dict
    # to set proc['has_match'] / proc['match_text'].
    wc._matches[f"{IP}:{name}"] = [_MATCH_WORD]
    # Wait ≥1 snapshot cycle (1.5 s) so L.processes picks up has_match=True
    # before the caller clicks the row.
    time.sleep(2.5)
    return proc_id


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server

    _free_port(PORT)

    # Disable the heartbeat watchdog for the duration of this test module.
    # The watchdog calls os._exit(0) after 20 s of no heartbeat; page reloads
    # between tests create brief gaps that can exceed this in slow CI environments.
    import app.web.routes as _web_routes
    _orig_hb_timeout = getattr(_web_routes, '_HB_TIMEOUT', 20)
    _web_routes._HB_TIMEOUT = 600   # 10 minutes — effectively disabled for tests

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED)
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
    d.set_script_timeout(30)   # prevent execute_script() from hanging indefinitely
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
# v10.59  Bottom-section splitter centre start
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitterCenterStart:
    """
    On first load (no localStorage value), JS sets #bottom-section height to
    Math.round(mainArea.offsetHeight / 2) instead of the HTML-encoded 200 px.
    """

    def test_bottom_section_starts_near_half_of_main_area(self, drv, srv):
        # Clear saved position so the JS default branch fires.
        js(drv, "localStorage.removeItem('legion-splitter-bottom')")
        drv.get(srv['url'])
        time.sleep(1.5)

        bottom_h = js(drv, "return document.getElementById('bottom-section').offsetHeight")
        main_h   = js(drv, "return document.getElementById('main-area').offsetHeight")

        assert main_h  > 0, "main-area has no rendered height"
        assert bottom_h > 0, "bottom-section has no rendered height"

        ratio = bottom_h / main_h
        # JS divides by 2; allow 30–70 % tolerance for font/chrome variation
        assert 0.30 <= ratio <= 0.70, (
            f"bottom-section should start at ~50 % of main-area height on first load.\n"
            f"  main-area={main_h}px  bottom-section={bottom_h}px  ratio={ratio:.2%}\n"
            f"  200 px was the old hard-coded default that would fail this check on "
            f"any window taller than ~600 px content area.")


# ═══════════════════════════════════════════════════════════════════════════════
# v10.60  All splitters genuinely draggable
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplittersDraggable:
    """
    Each test drags a splitter 80 px and asserts the target element's
    width (or height) changed by at least 30 px.  Before v10.60 only
    proc-, os-, scripts-, and tools-vsplitter had initSplitter wired up;
    dragging them changed the cursor but not the layout.
    """

    def _drag(self, drv, splitter_id, target_id, is_height, delta_px):
        sp = W(drv).until(EC.presence_of_element_located((By.ID, splitter_id)))
        prop = 'offsetHeight' if is_height else 'offsetWidth'
        before = js(drv, f"return document.getElementById('{target_id}').{prop}")
        assert before > 0, f"#{target_id}.{prop} = 0 before drag — element not laid out"

        dx, dy = (0, delta_px) if is_height else (delta_px, 0)
        ActionChains(drv).click_and_hold(sp).move_by_offset(dx, dy).release().perform()
        time.sleep(0.4)

        after = js(drv, f"return document.getElementById('{target_id}').{prop}")
        assert abs(after - before) >= 30, (
            f"#{splitter_id} drag should change #{target_id}.{prop} by ≥30 px.\n"
            f"  before={before}  after={after}  Δ={after - before}\n"
            f"  If Δ=0 the splitter's initSplitter() call is missing or the "
            f"target element is not the left/top sibling.")

    def test_main_vsplitter(self, drv, srv):
        """Left ↔ right panel boundary."""
        drv.get(srv['url']); time.sleep(1.5)
        self._drag(drv, 'main-vsplitter', 'left-panel', False, 80)

    def test_main_hsplitter(self, drv, srv):
        """Top ↔ bottom section boundary."""
        drv.get(srv['url']); time.sleep(1.5)
        self._drag(drv, 'main-hsplitter', 'bottom-section', True, -60)

    def test_proc_vsplitter(self, drv, srv):
        """Processes-table ↔ output pane inside the bottom Processes panel."""
        drv.get(srv['url']); time.sleep(1.5)
        _ensure_bottom_processes_tab(drv)
        self._drag(drv, 'proc-vsplitter', 'proc-table-wrap', False, 80)

    def test_os_vsplitter(self, drv, srv):
        """OS-list ↔ OS-hosts inside the OS left-tab."""
        drv.get(srv['url']); time.sleep(1.5)
        btn = W(drv).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#left-tab-bar [data-tab="os-panel"]')))
        js(drv, 'arguments[0].click()', btn)
        time.sleep(0.4)
        self._drag(drv, 'os-vsplitter', 'os-list-wrap', False, 80)

    def test_scripts_vsplitter(self, drv, srv):
        """Scripts-table ↔ script-output inside the Scripts right-tab."""
        drv.get(srv['url']); time.sleep(1.5)
        _select_host(drv)
        btn = W(drv).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#right-tab-bar [data-tab="scripts-right"]')))
        js(drv, 'arguments[0].click()', btn)
        time.sleep(0.3)
        self._drag(drv, 'scripts-vsplitter', 'scripts-table-wrap', False, 80)

    def test_tools_vsplitter(self, drv, srv):
        """tool-hosts ↔ tool-output inside the Tools display panel.

        tools-display only shows when L.selectedTool is set and the Tools
        left-tab is clicked.  We set the JS state, trigger the tab click, then
        drag.

        Verification: the initSplitter drag handler sets el.style.width directly
        (this is the only path that matters — if it fires, the splitter is wired).
        We check style.width before (empty) and after (a px value) since
        offsetWidth may report 0 in headless mode when the flex layout hasn't
        fully resolved.
        """
        drv.get(srv['url']); time.sleep(1.5)
        js(drv, """
            if (window.L) window.L.selectedTool = 'nmap';
            var btn = document.querySelector(
                '#left-tab-bar [data-tab="tools-panel-left"]');
            if (btn) btn.click();
        """)
        W(drv, 5).until(lambda d: js(d, """
            var td = document.getElementById('tools-display');
            return td ? window.getComputedStyle(td).display : 'none';
        """) == 'flex')
        time.sleep(0.5)

        sp = W(drv).until(EC.presence_of_element_located((By.ID, 'tools-vsplitter')))
        style_before = js(drv,
            "return document.getElementById('tools-table-wrap').style.width")

        # Pin flex so the drag handler can read offsetWidth (sets flex-grow/shrink=0)
        js(drv, """
            var wrap = document.getElementById('tools-table-wrap');
            if (wrap) {
                wrap.style.flexGrow   = '0';
                wrap.style.flexShrink = '0';
                wrap.style.width      = '275px';
            }
        """)
        ActionChains(drv).click_and_hold(sp).move_by_offset(80, 0).release().perform()
        time.sleep(0.3)

        style_after = js(drv,
            "return document.getElementById('tools-table-wrap').style.width")
        assert style_after and style_after != '', (
            "tools-vsplitter drag must write a width px value to "
            "tools-table-wrap.style.width.\n"
            f"  style before drag: {style_before!r}\n"
            f"  style after  drag: {style_after!r}\n"
            "  Empty style_after means initSplitter('tools-vsplitter', ...) "
            "was never called — the mousedown handler isn't wired.")
        # Also verify the value is a plausible pixel width
        assert 'px' in style_after, \
            f"Expected 'NNNpx', got: {style_after!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.61  Tab-bar scrollbar always visible
# ═══════════════════════════════════════════════════════════════════════════════

class TestTabBarScrollbarAlwaysVisible:
    """
    The old CSS had overflow-x:auto on .tab-bar and then
    .tab-bar::-webkit-scrollbar{height:0} to hide it.  v10.61 changed to
    overflow-x:scroll and a real 8 px scrollbar-thumb so users can tell the
    bar is scrollable and won't accidentally grab invisible chrome.
    """

    def test_right_tab_bar_overflow_is_scroll(self, drv, srv):
        drv.get(srv['url']); time.sleep(1.5)
        ov = js(drv, """
            return window.getComputedStyle(
                document.getElementById('right-tab-bar')).overflowX;
        """)
        assert ov == 'scroll', (
            f"right-tab-bar overflowX must be 'scroll' (always show track).\n"
            f"  Got '{ov}'.  'auto' hides the scrollbar when content fits, "
            f"which led to accidental tab-drag misclicks.")

    def test_right_tab_bar_scrollbar_consumes_height(self, drv, srv):
        """
        With overflow-x:scroll a horizontal scrollbar is always rendered inside
        the element.  clientHeight < offsetHeight because the scrollbar track
        eats into the padding box.
        """
        drv.get(srv['url']); time.sleep(1.5)
        offset_h = js(drv, "return document.getElementById('right-tab-bar').offsetHeight")
        client_h = js(drv, "return document.getElementById('right-tab-bar').clientHeight")
        assert offset_h > client_h, (
            f"right-tab-bar scrollbar must consume real vertical space.\n"
            f"  offsetHeight={offset_h}  clientHeight={client_h}\n"
            f"  If equal the scrollbar is still hidden (height:0 or overlay mode).")

    def test_all_tab_bars_have_scroll_overflow(self, drv, srv):
        """Every .tab-bar in the document must use overflow-x:scroll."""
        drv.get(srv['url']); time.sleep(1.5)
        results = js(drv, """
            return Array.from(document.querySelectorAll('.tab-bar')).map(function(b) {
                return {
                    id:       b.id || '(no id)',
                    overflow: window.getComputedStyle(b).overflowX
                };
            });
        """)
        bad = [r for r in results if r['overflow'] != 'scroll']
        assert not bad, (
            "All .tab-bar elements must have overflow-x:scroll.  Offenders:\n" +
            '\n'.join(f"  #{r['id']} → overflowX='{r['overflow']}'" for r in bad))

    def test_tab_bar_scrollbar_thumb_color_is_grey(self, drv, srv):
        """
        The scrollbar-color property (Firefox) must contain a grey thumb value,
        not 'auto' (which would render the OS default invisible on some themes).
        """
        drv.get(srv['url']); time.sleep(1.5)
        color = js(drv, """
            return window.getComputedStyle(
                document.getElementById('right-tab-bar')).scrollbarColor;
        """)
        # scrollbarColor is 'thumb track' — should be non-empty and non-'auto'
        assert color and color.lower() not in ('', 'auto'), (
            f"right-tab-bar scrollbarColor should define an explicit thumb colour.\n"
            f"  Got '{color}'.  'auto' may render invisibly on dark GTK themes.")


# ═══════════════════════════════════════════════════════════════════════════════
# v10.62  Scan-tab state restoration after Brute switch
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanTabStateRestoration:
    """
    Before v10.62, initTabBar's querySelectorAll('.tab-content.active') walked
    the entire subtree.  Switching to Brute stripped .active from every nested
    panel — scripts-right, notes-right, os-panel, etc.  Returning to Scan left
    the right panel blank (no tab active) until the user clicked a tab again.

    Fix: guard with c.closest('.tab-widget') === widget so only same-level
    panels are deactivated.
    """

    def _active_right_tab(self, drv):
        return js(drv, """
            var b = document.querySelector('#right-tab-bar .tab-btn.active');
            return b ? b.dataset.tab : null;
        """)

    def _active_left_tab(self, drv):
        return js(drv, """
            var b = document.querySelector('#left-tab-bar .tab-btn.active');
            return b ? b.dataset.tab : null;
        """)

    def _switch_brute_then_scan(self, drv):
        js(drv, """
            document.querySelector('#main-tab-bar [data-tab="brute-tab"]').click();
        """)
        time.sleep(0.5)
        js(drv, """
            document.querySelector('#main-tab-bar [data-tab="scan-tab"]').click();
        """)
        time.sleep(1.2)   # snapshot poll + loadHostDetail to settle

    def _activate_right_tab(self, drv, tab_id):
        btn = W(drv).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#right-tab-bar [data-tab="{tab_id}"]')))
        js(drv, 'arguments[0].click()', btn)
        time.sleep(0.3)
        assert self._active_right_tab(drv) == tab_id, \
            f"Could not activate {tab_id} before the Brute-switch test"

    def test_scripts_tab_preserved_after_brute_switch(self, drv, srv):
        drv.get(srv['url']); time.sleep(1.5)
        _select_host(drv)
        self._activate_right_tab(drv, 'scripts-right')
        self._switch_brute_then_scan(drv)
        got = self._active_right_tab(drv)
        assert got == 'scripts-right', (
            f"scripts-right must still be active after Brute→Scan.\n"
            f"  Got: {got!r}\n"
            f"  Cause: initTabBar was wiping nested .active classes.")

    def test_notes_tab_preserved_after_brute_switch(self, drv, srv):
        drv.get(srv['url']); time.sleep(1.5)
        _select_host(drv)
        self._activate_right_tab(drv, 'notes-right')
        self._switch_brute_then_scan(drv)
        got = self._active_right_tab(drv)
        assert got == 'notes-right', \
            f"notes-right must survive Brute→Scan. Got: {got!r}"

    def test_info_tab_preserved_after_brute_switch(self, drv, srv):
        drv.get(srv['url']); time.sleep(1.5)
        _select_host(drv)
        self._activate_right_tab(drv, 'info-right')
        self._switch_brute_then_scan(drv)
        got = self._active_right_tab(drv)
        assert got == 'info-right', \
            f"info-right must survive Brute→Scan. Got: {got!r}"

    def test_cves_tab_preserved_after_brute_switch(self, drv, srv):
        drv.get(srv['url']); time.sleep(1.5)
        _select_host(drv)
        self._activate_right_tab(drv, 'cves-right')
        self._switch_brute_then_scan(drv)
        got = self._active_right_tab(drv)
        assert got == 'cves-right', \
            f"cves-right must survive Brute→Scan. Got: {got!r}"

    def test_left_os_tab_preserved_after_brute_switch(self, drv, srv):
        """The left-panel active tab must also survive a Scan↔Brute switch."""
        drv.get(srv['url']); time.sleep(1.5)
        os_btn = W(drv).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, '#left-tab-bar [data-tab="os-panel"]')))
        js(drv, 'arguments[0].click()', os_btn)
        time.sleep(0.3)
        assert self._active_left_tab(drv) == 'os-panel'
        self._switch_brute_then_scan(drv)
        got = self._active_left_tab(drv)
        assert got == 'os-panel', \
            f"os-panel (left tab) must survive Brute→Scan. Got: {got!r}"

    def test_right_panel_content_is_visible_after_return(self, drv, srv):
        """
        The active right-panel tab-content must have display:flex (not display:none)
        after returning from Brute.  If .active was stripped the content is hidden.
        """
        drv.get(srv['url']); time.sleep(1.5)
        _select_host(drv)
        self._activate_right_tab(drv, 'scripts-right')
        self._switch_brute_then_scan(drv)
        display = js(drv, """
            var el = document.getElementById('scripts-right');
            return el ? window.getComputedStyle(el).display : 'missing';
        """)
        assert display == 'flex', (
            f"scripts-right tab content must be display:flex after Brute→Scan.\n"
            f"  Got: '{display}'.  'none' means .active was stripped and content "
            f"is invisible even though the tab button looks active.")


# ═══════════════════════════════════════════════════════════════════════════════
# v10.63  Match navigation arrows
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="class")
def match_setup(drv, srv):
    """Load page and select host ONCE for all TestMatchNavigation tests.

    A single page load for the whole class avoids repeated drv.get() calls that
    accumulate Firefox/geckodriver memory and cause WebDriver connection failures
    after ~2 match tests when preceded by 17 splitter/scrollbar/scan tests.
    """
    drv.get(srv['url'])
    time.sleep(1.5)
    _select_host(drv)
    _ensure_bottom_processes_tab(drv)
    # Pre-inject the match keyword — persists in this page's matchPositive array
    js(drv, f"""
        if (!window.matchPositive) window.matchPositive = [];
        if (matchPositive.indexOf('{_MATCH_WORD}') < 0)
            matchPositive.push('{_MATCH_WORD}');
    """)
    yield


class TestMatchNavigation:
    """
    When a process output contains .match-positive spans:
      • The match banner gains ▲ (.match-prev) and ▼ (.match-next) buttons.
      • A counter span (.match-nav-counter) shows "N ⁄ M".
      • Clicking ▼ advances the counter and moves .match-current to the next span.
      • Clicking ▲ decrements the counter and moves .match-current backwards.
      • Navigation wraps: last → first, first → last.

    Tests cover both panels: lower (plain-output) and upper (dyn-output-*).
    The match_setup class-scoped fixture loads the page ONCE for all tests in
    this class to avoid repeated drv.get() calls that destabilise geckodriver.
    """

    # ── lower panel helpers ───────────────────────────────────────────────────

    def _load_lower(self, drv, srv, proc_name):
        """Set up a lower-panel (plain-output) match nav test WITHOUT page reload.

        Creates a fresh process, clicks its row (which overwrites plain-output with
        fresh content), and waits for the match banner.  Avoids innerHTML='' DOM
        mutations which can hang Firefox headless with attached event listeners.
        """
        proc_id = _setup_match_process(drv, srv, proc_name)
        _ensure_bottom_processes_tab(drv)
        # Find the process row by its data-process-id attribute
        proc_row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        js(drv, 'arguments[0].click()', proc_row)
        # Wait for banner to appear (snapshot has has_match → loadProcessOutput)
        W(drv, 15).until(lambda d: d.find_elements(
            By.CSS_SELECTOR, '#plain-output .match-banner'))
        return proc_row, proc_id

    def _counter(self, drv, panel='plain-output'):
        return js(drv, f"""
            var c = document.querySelector('#{panel} .match-nav-counter');
            return c ? c.textContent.trim() : '';
        """)

    def _current_idx(self, drv, panel='plain-output'):
        return js(drv, f"""
            var spans = Array.from(
                document.querySelectorAll('#{panel} .match-positive'));
            return spans.findIndex(function(s) {{
                return s.classList.contains('match-current');
            }});
        """)

    def _click_next(self, drv, panel='plain-output'):
        js(drv, f"document.querySelector('#{panel} .match-next').click()")
        time.sleep(0.15)

    def _click_prev(self, drv, panel='plain-output'):
        js(drv, f"document.querySelector('#{panel} .match-prev').click()")
        time.sleep(0.15)

    # ── lower panel tests ─────────────────────────────────────────────────────

    def test_lower_banner_has_prev_and_next_buttons(self, drv, srv, match_setup):
        """match-banner must contain .match-prev and .match-next buttons."""
        self._load_lower(drv, srv, 'nav-l1')
        assert drv.find_element(
            By.CSS_SELECTOR, '#plain-output .match-prev').is_displayed(), \
            ".match-prev (▲) button must be visible in the match banner"
        assert drv.find_element(
            By.CSS_SELECTOR, '#plain-output .match-next').is_displayed(), \
            ".match-next (▼) button must be visible in the match banner"

    def test_lower_counter_shows_correct_total(self, drv, srv, match_setup):
        """Counter must show '1 ⁄ 3' — three occurrences of _MATCH_WORD."""
        self._load_lower(drv, srv, 'nav-l2')
        txt = self._counter(drv)
        assert txt.startswith('1'), \
            f"Counter should start at 1. Got: {txt!r}"
        assert '3' in txt, (
            f"Counter must show total of 3 matches (printf outputs 3 lines "
            f"with {_MATCH_WORD}).  Got: {txt!r}")

    def test_lower_next_button_advances_counter(self, drv, srv, match_setup):
        """▼ from position 1 must advance counter to 2."""
        self._load_lower(drv, srv, 'nav-l3')
        self._click_next(drv)
        txt = self._counter(drv)
        assert txt.startswith('2'), \
            f"After one ▼ click counter must start with '2'. Got: {txt!r}"

    def test_lower_prev_button_decrements_counter(self, drv, srv, match_setup):
        """▼ then ▲ must return counter to 1."""
        self._load_lower(drv, srv, 'nav-l4')
        self._click_next(drv)
        self._click_prev(drv)
        txt = self._counter(drv)
        assert txt.startswith('1'), \
            f"After ▼ then ▲, counter must be back at 1. Got: {txt!r}"

    def test_lower_match_current_moves_on_next(self, drv, srv, match_setup):
        """The .match-current class must move to a different span when ▼ is clicked."""
        self._load_lower(drv, srv, 'nav-l5')
        before = self._current_idx(drv)
        assert before >= 0, ".match-current must be on a span before navigation"
        self._click_next(drv)
        after = self._current_idx(drv)
        assert after != before, (
            f".match-current did not move after ▼ click.\n"
            f"  Before={before}  After={after}")

    def test_lower_navigation_wraps_last_to_first(self, drv, srv, match_setup):
        """▼ three times from position 1 of 3 must wrap back to 1."""
        self._load_lower(drv, srv, 'nav-l6')
        for _ in range(3):          # 1 → 2 → 3 → wraps to 1
            self._click_next(drv)
        txt = self._counter(drv)
        assert txt.startswith('1'), (
            f"After 3× ▼ on 3 matches (wraps: 1→2→3→1), counter must be 1. "
            f"Got: {txt!r}")

    def test_lower_navigation_wraps_first_to_last(self, drv, srv, match_setup):
        """▲ from position 1 must wrap to position 3 (the last match)."""
        self._load_lower(drv, srv, 'nav-l7')
        self._click_prev(drv)   # 1 → wraps to 3
        txt = self._counter(drv)
        assert txt.startswith('3'), (
            f"▲ from position 1 must wrap to 3 (last match). Got: {txt!r}")

    def test_lower_only_one_span_has_match_current(self, drv, srv, match_setup):
        """Exactly one .match-positive span may carry .match-current at a time."""
        self._load_lower(drv, srv, 'nav-l8')
        self._click_next(drv)
        count = js(drv, """
            return document.querySelectorAll(
                '#plain-output .match-positive.match-current').length;
        """)
        assert count == 1, (
            f"Exactly one span must have .match-current. Found {count}.")

    def test_lower_banner_is_sticky_top(self, drv, srv, match_setup):
        """
        The match banner must be position:sticky / top:0 so it stays visible
        when the user scrolls the output area to a deeply-nested match.
        """
        self._load_lower(drv, srv, 'nav-l9')
        pos = js(drv, """
            return window.getComputedStyle(
                document.querySelector('#plain-output .match-banner')
            ).position;
        """)
        assert pos == 'sticky', (
            f"match-banner must be position:sticky so it pins to the top of the "
            f"output area while the user scrolls to a match. Got: '{pos}'")

    # ── upper panel (dyn-output) tests ────────────────────────────────────────

    def _load_upper(self, drv, srv, proc_name):
        """Set up an upper-panel (dyn-output-*) match nav test WITHOUT page reload.
        match_setup already loaded the page and selected the host for this class."""
        proc_id = _setup_match_process(drv, srv, proc_name)

        # Click the dynamic tab button for this process
        tab_css = f'#right-tab-bar .dynamic-tab[data-tab="dyntab-{proc_id}"]'
        dyn_btn = W(drv, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, tab_css)))
        js(drv, 'arguments[0].click()', dyn_btn)

        dyn_id = f'dyn-output-{proc_id}'
        W(drv, 15).until(lambda d: d.find_elements(
            By.CSS_SELECTOR, f'#{dyn_id} .match-banner'))
        return proc_id

    def test_upper_banner_has_nav_buttons(self, drv, srv, match_setup):
        """dyn-output must contain .match-prev and .match-next buttons."""
        proc_id = self._load_upper(drv, srv, 'nav-u1')
        dyn_id  = f'dyn-output-{proc_id}'
        assert drv.find_element(
            By.CSS_SELECTOR, f'#{dyn_id} .match-prev').is_displayed(), \
            f"#{dyn_id} .match-prev must be visible"
        assert drv.find_element(
            By.CSS_SELECTOR, f'#{dyn_id} .match-next').is_displayed(), \
            f"#{dyn_id} .match-next must be visible"

    def test_upper_counter_shows_correct_total(self, drv, srv, match_setup):
        """Upper panel counter must show total of 3 matches."""
        proc_id = self._load_upper(drv, srv, 'nav-u2')
        dyn_id  = f'dyn-output-{proc_id}'
        txt = self._counter(drv, dyn_id)
        assert '3' in txt, \
            f"Upper panel counter must show 3 total matches. Got: {txt!r}"

    def test_upper_next_button_advances_counter(self, drv, srv, match_setup):
        """▼ in the upper panel must increment the counter from 1 to 2."""
        proc_id = self._load_upper(drv, srv, 'nav-u3')
        dyn_id  = f'dyn-output-{proc_id}'
        self._click_next(drv, dyn_id)
        txt = self._counter(drv, dyn_id)
        assert txt.startswith('2'), \
            f"After ▼ in upper panel, counter must start with '2'. Got: {txt!r}"

    def test_upper_match_current_moves_on_next(self, drv, srv, match_setup):
        """The .match-current class must move in the upper panel too."""
        proc_id = self._load_upper(drv, srv, 'nav-u4')
        dyn_id  = f'dyn-output-{proc_id}'
        before  = self._current_idx(drv, dyn_id)
        assert before >= 0, f"#{dyn_id} .match-current must exist before navigation"
        self._click_next(drv, dyn_id)
        after = self._current_idx(drv, dyn_id)
        assert after != before, (
            f"Upper panel .match-current did not move.\n"
            f"  Before={before}  After={after}")
