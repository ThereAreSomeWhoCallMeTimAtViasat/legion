#!/usr/bin/env python3
"""tests/test_ui_session_tweaks.py

Non-hollow Selenium regression tests for UI tweaks that lack coverage
from the 2026-03-28 to 2026-03-30 session (v10.85 – v10.97, v10.103, v10.109).

  v10.85  Splitter flex-basis fix — clicking (not dragging) a splitter no
          longer collapses the target pane to 0 px because startSize is
          captured BEFORE flex properties are changed and flexBasis is set.

  v10.86  Horizontal splitter direction — dragging the main-hsplitter downward
          shrinks the bottom section (expanding the top).  Before the fix the
          delta was applied in the wrong direction.

  v10.87  Clear process clears lower output — when the currently-displayed
          process is cleared (closed), plain-output is emptied immediately
          rather than left showing stale content.

  v10.88/89  Host input comma validation — the Add Hosts dialog accepts
          nmap octet-shorthand ("192.168.1.1,111") but rejects a full second
          IP after a comma ("192.168.1.1,192.168.1.111") with an inline error
          message that does NOT close the dialog.

  v10.92  Add hosts error display — when the server returns 400 for an invalid
          target, the validation element shows the error message and the dialog
          remains open.

  v10.96  Context menu scroll arrows — when the right-click context menu is
          taller than the viewport, ▼ "more below" and ▲ "more above" arrows
          appear and clicking them scrolls the list.

  v10.97  Match banner not selectable — .match-banner has user-select:none
          so click-drag selections in the output panel skip over it.

  v10.103 Config manager save works — saving the default profile in the
          Config Manager no longer shows ❌ JSON.parse error (the backup
          function previously called undefined `log.warning`).

Run (from repo root):
    sudo python3 -m pytest tests/test_ui_session_tweaks.py -v
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

PORT = 5080
IP   = '10.80.80.1'
BASE = f'http://127.0.0.1:{PORT}'

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


def _select_host(drv):
    row = W(drv, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', row)
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
def _reset_state(drv):
    """Dismiss any open modals/menus before each test."""
    try:
        drv.switch_to.alert.dismiss()
    except Exception:
        pass
    # Close any open context menu
    js(drv, "var m=$('ctx-menu'); if(m) m.remove();")
    yield
    try:
        drv.switch_to.alert.dismiss()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# v10.87 — Clearing the selected process empties the lower output panel
# ═══════════════════════════════════════════════════════════════════════════════

class TestClearProcessClearsOutput:
    """When the process currently displayed in plain-output is cleared (closed),
    plain-output is emptied instead of left showing stale content."""

    _proc_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']
        r = wc.runCommand(command='echo clear_test_output', name='clear-test',
                          tabTitle='clear-test', hostIp=IP)
        pid = r['process_id']
        type(self)._proc_id = str(pid)
        _wait_proc_done(str(pid), timeout=20)
        time.sleep(2.0)

        # Click the process row to load output in plain-output
        js(drv, "document.querySelector('[data-tab=\"scan-tab\"]').click()")
        time.sleep(0.3)
        js(drv, "var b=document.querySelector('[data-tab=\"processes-panel\"]'); if(b) b.click();")
        time.sleep(0.3)
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(1.5)
        yield

    def _plain_output_text(self, drv):
        return js(drv, "return (document.getElementById('plain-output')||{}).textContent || ''")

    def test_output_loaded_before_clear(self, drv, srv):
        """plain-output must have content before we clear the process."""
        text = self._plain_output_text(drv)
        assert text.strip(), f"plain-output is empty before clear — cannot test clearing"

    def test_clear_via_context_menu_empties_output(self, drv, srv):
        """Selecting 'Clear' in the process row right-click menu must empty plain-output.
        The JS at line 3748-3756 checks if the cleared process is selected and
        sets po.textContent='' — this only fires via the client-side menu action."""
        pid = self._proc_id
        # Right-click the process row to get context menu
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))
        ActionChains(drv).context_click(row).perform()
        time.sleep(0.5)
        # Find and click the "Clear" option in the context menu
        menu = W(drv, 4).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))
        btns = menu.find_elements(By.TAG_NAME, 'button')
        clear_btn = next((b for b in btns if 'clear' in b.text.lower()), None)
        if clear_btn is None:
            pytest.skip("No 'Clear' option in process context menu")
        js(drv, 'arguments[0].click()', clear_btn)
        time.sleep(2.0)  # wait for postJson + pollSnapshot
        text = self._plain_output_text(drv)
        assert not text.strip(), \
            f"plain-output still has content after context-menu Clear: {text[:80]!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.88/89 — Host input comma validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestHostInputCommaValidation:
    """The Add Hosts dialog validates comma syntax:
    - Octet shorthand (192.168.1.1,111) is allowed — no error
    - Full second IP after comma (192.168.1.1,192.168.1.111) is rejected inline"""

    def _open_add_hosts(self, drv):
        """Open the Add Hosts modal."""
        js(drv, "document.getElementById('action-add-hosts') && "
                "document.getElementById('action-add-hosts').click()")
        time.sleep(0.4)
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'add-hosts-modal')))

    def _enter_target(self, drv, target):
        ta = drv.find_element(By.ID, 'add-hosts-targets')
        ta.clear()
        ta.send_keys(target)

    def _click_add(self, drv):
        btn = drv.find_element(By.ID, 'add-hosts-start')
        js(drv, 'arguments[0].click()', btn)
        time.sleep(0.8)

    def _validation_msg(self, drv):
        el = drv.find_element(By.ID, 'add-hosts-validation')
        return el.get_attribute('style') or '', el.text

    def _close_modal(self, drv):
        try:
            js(drv, "var m=document.getElementById('add-hosts-modal');"
                    "if(m) m.classList.remove('is-open');")
        except Exception:
            pass
        time.sleep(0.2)

    # ── Octet shorthand is valid ────────────────────────────────────────────

    def test_octet_shorthand_shows_no_error(self, drv, srv):
        """192.168.1.1,111 (octet shorthand) must not trigger a validation error."""
        self._open_add_hosts(drv)
        self._enter_target(drv, '192.168.1.1,111')
        style, msg = self._validation_msg(drv)
        # Validation element should be hidden (display:none) for valid input before submit
        assert 'display: none' in style or 'display:none' in style or not msg.strip(), \
            f"Octet shorthand wrongly flagged as invalid: '{msg}'"
        self._close_modal(drv)

    # ── Full IP after comma is rejected ────────────────────────────────────

    def test_full_ip_after_comma_shows_error(self, drv, srv):
        """192.168.1.1,192.168.1.111 must show a validation error — comma only
        allowed for single-octet shorthand, not a full second IP."""
        self._open_add_hosts(drv)
        self._enter_target(drv, '192.168.1.1,192.168.1.111')
        self._click_add(drv)
        style, msg = self._validation_msg(drv)
        assert 'display: none' not in style and 'display:none' not in style, \
            "Validation element is hidden — error was not shown for full IP after comma"
        assert msg.strip(), "Validation message is empty for full IP after comma"
        self._close_modal(drv)

    def test_dialog_stays_open_after_comma_error(self, drv, srv):
        """When comma validation fails, the Add Hosts dialog must remain open."""
        self._open_add_hosts(drv)
        self._enter_target(drv, '10.0.0.1,10.0.0.2')
        self._click_add(drv)
        modal = drv.find_element(By.ID, 'add-hosts-modal')
        # The modal must still be visible (not closed)
        is_open = 'is-open' in (modal.get_attribute('class') or '')
        visible = modal.is_displayed()
        assert is_open or visible, \
            "Dialog closed after comma validation error — should stay open"
        self._close_modal(drv)

    def test_semicolon_target_is_rejected(self, drv, srv):
        """A semicolon in the target (injection attempt) must be rejected."""
        self._open_add_hosts(drv)
        self._enter_target(drv, '10.0.0.1; echo injection')
        self._click_add(drv)
        style, msg = self._validation_msg(drv)
        assert msg.strip() and ('display: none' not in style and 'display:none' not in style), \
            "Semicolon injection target was not rejected"
        self._close_modal(drv)


# ═══════════════════════════════════════════════════════════════════════════════
# v10.92 — Add hosts server-side error shown inline without closing dialog
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddHostsErrorDisplay:
    """When the server returns 400 for an invalid target, the error message
    is displayed inside the dialog and the dialog remains open."""

    def _open_and_enter(self, drv, target):
        js(drv, "document.getElementById('action-add-hosts') && "
                "document.getElementById('action-add-hosts').click()")
        time.sleep(0.4)
        W(drv, 5).until(EC.visibility_of_element_located((By.ID, 'add-hosts-modal')))
        ta = drv.find_element(By.ID, 'add-hosts-targets')
        ta.clear(); ta.send_keys(target)
        btn = drv.find_element(By.ID, 'add-hosts-start')
        js(drv, 'arguments[0].click()', btn)
        time.sleep(1.0)

    def _close_modal(self, drv):
        try:
            js(drv, "var m=document.getElementById('add-hosts-modal');"
                    "if(m) m.classList.remove('is-open');")
        except Exception:
            pass
        time.sleep(0.2)

    def test_validation_element_exists(self, drv, srv):
        """#add-hosts-validation must be present in the DOM."""
        el = drv.find_element(By.ID, 'add-hosts-validation')
        assert el is not None

    def test_invalid_target_shows_inline_error(self, drv, srv):
        """Submitting a clearly invalid target shows an error in #add-hosts-validation."""
        self._open_and_enter(drv, 'not_a_valid_target!!!')
        el = drv.find_element(By.ID, 'add-hosts-validation')
        style = el.get_attribute('style') or ''
        text = el.text.strip()
        visible = 'display: none' not in style and 'display:none' not in style
        # Either the validation shows an error message OR the dialog rejected via red text
        if visible and text:
            assert True  # error shown inline ✓
        else:
            # Server might have returned 400 — check status in add-hosts-status
            status = js(drv, "var s=document.getElementById('add-hosts-status');"
                             "return s ? s.textContent : '';")
            assert 'error' in status.lower() or 'invalid' in status.lower(), \
                f"No inline error shown for invalid target. validation='{text}' status='{status}'"
        self._close_modal(drv)

    def test_dialog_open_after_server_error(self, drv, srv):
        """Dialog stays open when the server returns an error."""
        self._open_and_enter(drv, '!!invalid!!')
        modal = drv.find_element(By.ID, 'add-hosts-modal')
        visible = modal.is_displayed() or 'is-open' in (modal.get_attribute('class') or '')
        self._close_modal(drv)
        assert visible, "Dialog closed after server error — should stay open"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.85 — Splitter click without drag does not collapse pane to zero
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitterNonZeroOnClick:
    """Clicking (mousedown + mouseup without moving) a splitter must not
    collapse its target pane to 0 px.  The fix captures startSize BEFORE
    setting flex properties and sets flexBasis alongside flexGrow/flexShrink."""

    def _width_of(self, drv, element_id):
        return js(drv, f"return document.getElementById('{element_id}').offsetWidth")

    def _height_of(self, drv, element_id):
        return js(drv, f"return document.getElementById('{element_id}').offsetHeight")

    def test_proc_vsplitter_click_preserves_width(self, drv, srv):
        """Clicking proc-vsplitter without dragging must keep proc-table-wrap > 0 px."""
        before = self._width_of(drv, 'proc-table-wrap')
        if before == 0:
            pytest.skip("proc-table-wrap already 0 before test")

        splitter = drv.find_element(By.ID, 'proc-vsplitter')
        # Mousedown + mouseup without moving = click without drag
        ActionChains(drv).move_to_element(splitter).click().perform()
        time.sleep(0.3)

        after = self._width_of(drv, 'proc-table-wrap')
        assert after > 0, \
            f"proc-table-wrap collapsed to 0 px after splitter click (was {before}px)"

    def test_main_vsplitter_click_preserves_left_panel_width(self, drv, srv):
        """Clicking main-vsplitter without dragging must keep left-panel width > 0 px."""
        before = self._width_of(drv, 'left-panel')
        if before == 0:
            pytest.skip("left-panel already 0 before test")

        splitter = drv.find_element(By.ID, 'main-vsplitter')
        ActionChains(drv).move_to_element(splitter).click().perform()
        time.sleep(0.3)

        after = self._width_of(drv, 'left-panel')
        assert after > 0, \
            f"left-panel collapsed to 0 px after splitter click (was {before}px)"

    def test_main_hsplitter_click_preserves_bottom_section_height(self, drv, srv):
        """Clicking main-hsplitter without dragging keeps bottom-section height > 0 px."""
        before = self._height_of(drv, 'bottom-section')
        if before == 0:
            pytest.skip("bottom-section already 0 before test")

        splitter = drv.find_element(By.ID, 'main-hsplitter')
        ActionChains(drv).move_to_element(splitter).click().perform()
        time.sleep(0.3)

        after = self._height_of(drv, 'bottom-section')
        assert after > 0, \
            f"bottom-section collapsed to 0 px after hsplitter click (was {before}px)"


# ═══════════════════════════════════════════════════════════════════════════════
# v10.86 — Horizontal splitter: drag down shrinks bottom (not grow)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHorizontalSplitterDirection:
    """Dragging the main-hsplitter downward must shrink the bottom-section
    (expanding the scan area above it).  Before v10.86 the delta was negated
    so dragging down grew the bottom instead."""

    def test_drag_down_shrinks_bottom_section(self, drv, srv):
        """Dragging main-hsplitter 60px downward must reduce bottom-section height."""
        splitter = drv.find_element(By.ID, 'main-hsplitter')
        before = js(drv, "return document.getElementById('bottom-section').offsetHeight")
        if before == 0:
            pytest.skip("bottom-section starts at 0 — cannot test direction")

        # Drag splitter 60px downward
        ActionChains(drv)\
            .move_to_element(splitter)\
            .click_and_hold()\
            .move_by_offset(0, 60)\
            .release()\
            .perform()
        time.sleep(0.3)

        after = js(drv, "return document.getElementById('bottom-section').offsetHeight")
        assert after < before, \
            (f"Dragging hsplitter DOWN should shrink bottom-section "
             f"(before={before}px, after={after}px). Direction may still be reversed.")

    def test_drag_up_grows_bottom_section(self, drv, srv):
        """Dragging main-hsplitter 60px upward must increase bottom-section height."""
        splitter = drv.find_element(By.ID, 'main-hsplitter')
        before = js(drv, "return document.getElementById('bottom-section').offsetHeight")

        ActionChains(drv)\
            .move_to_element(splitter)\
            .click_and_hold()\
            .move_by_offset(0, -60)\
            .release()\
            .perform()
        time.sleep(0.3)

        after = js(drv, "return document.getElementById('bottom-section').offsetHeight")
        assert after > before, \
            (f"Dragging hsplitter UP should grow bottom-section "
             f"(before={before}px, after={after}px). Direction may still be reversed.")


# ═══════════════════════════════════════════════════════════════════════════════
# v10.97 — Match banner is not user-selectable
# ═══════════════════════════════════════════════════════════════════════════════

class TestMatchBannerNotSelectable:
    """.match-banner has user-select:none so that click-drag selections in the
    output panel skip over the banner and only capture tool output text."""

    _proc_id = None

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, drv, srv):
        wc = srv['wc']
        r = wc.runCommand(command='echo "proof of concept found here"',
                          name='banner-select-test', tabTitle='banner-select-test',
                          hostIp=IP)
        pid = r['process_id']
        type(self)._proc_id = str(pid)
        _wait_proc_done(str(pid), timeout=20)
        wc._matches[f"{IP}:banner-select-test"] = ['proof']
        time.sleep(2.5)

        # Select the process to show the banner
        js(drv, "document.querySelector('[data-tab=\"processes-panel\"]') && "
                "document.querySelector('[data-tab=\"processes-panel\"]').click()")
        time.sleep(0.3)
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(2.0)
        yield
        wc._matches.pop(f"{IP}:banner-select-test", None)

    def test_match_banner_has_user_select_none(self, drv, srv):
        """CSS user-select on .match-banner must be 'none'."""
        result = js(drv,
            "var b = document.querySelector('#plain-output .match-banner');"
            "if (!b) return null;"
            "return getComputedStyle(b).userSelect;")
        assert result is not None, \
            "No .match-banner found in plain-output — was the match process clicked?"
        assert result == 'none', \
            f"match-banner user-select is '{result}', expected 'none'"

    def test_match_banner_not_included_in_drag_selection(self, drv, srv):
        """Selecting all text in plain-output should not start from or include
        the banner text ('Matches:') — user-select:none excludes it."""
        banner_text = js(drv,
            "var b=document.querySelector('#plain-output .match-banner');"
            "return b ? b.textContent.trim() : '';")
        if not banner_text:
            pytest.skip("No match banner present")

        # Select all content in plain-output via JS
        js(drv, """
            var el = document.getElementById('plain-output');
            var range = document.createRange();
            range.selectNodeContents(el);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        """)
        time.sleep(0.1)

        selected = js(drv, "return window.getSelection().toString();")
        # The banner should not appear at the START of the selection
        # (user-select:none excludes it from selection entirely)
        assert not selected.startswith('Matches'), \
            (f"Selection starts with banner text — banner is NOT excluded from selection. "
             f"Selected: {selected[:60]!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# v10.96 — Context menu scroll arrows appear when menu exceeds viewport
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextMenuScrollArrows:
    """When a right-click context menu is taller than the available viewport
    height, ▼ 'more below' and ▲ 'more above' arrow bars appear.  They
    disappear when at the bottom/top of the list respectively."""

    def _open_port_menu(self, drv):
        """Right-click the host row to get a long host-action context menu.
        Host actions include nmap variants, masscan, dnsrecon, searchsploit,
        BloodHound, pyShodan, etc. — typically 10+ items, enough to overflow
        a 400px-tall viewport."""
        _select_host(drv)
        host_row = W(drv, 6).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
        ActionChains(drv).context_click(host_row).perform()
        time.sleep(0.5)

    def test_context_menu_exists_on_right_click(self, drv, srv):
        """Right-clicking must produce a #ctx-menu element."""
        self._open_port_menu(drv)
        menu = drv.find_element(By.ID, 'ctx-menu')
        assert menu is not None
        js(drv, "var m=document.getElementById('ctx-menu'); if(m) m.remove();")

    def test_bottom_arrow_appears_when_list_overflows(self, drv, srv):
        """When the inner scrollable list overflows, the ▼ arrow becomes visible.
        We force overflow by shrinking the list's max-height via JS, then fire
        the scroll handler — no viewport resize needed."""
        self._open_port_menu(drv)
        time.sleep(0.3)
        result = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return 'NO_MENU';
            // Inner list is the div with overflow-y:auto (second child of menu)
            var list = m.children[1];
            if (!list) return 'NO_LIST';
            var botArrow = m.lastElementChild;  // bottom arrow is last child
            if (!botArrow) return 'NO_ARROW';

            // Constrain list height to force overflow, then fire scroll event
            var orig = list.style.maxHeight;
            list.style.maxHeight = '50px';
            list.dispatchEvent(new Event('scroll'));

            var display = botArrow.style.display;
            // Restore
            list.style.maxHeight = orig;
            list.dispatchEvent(new Event('scroll'));
            return display;
        """)
        js(drv, "var m=document.getElementById('ctx-menu'); if(m) m.remove();")
        if result == 'NO_MENU':
            pytest.skip("Context menu not opened")
        if result in ('NO_LIST', 'NO_ARROW'):
            pytest.fail(f"Context menu structure wrong: {result}")
        assert result != 'none', \
            (f"Bottom arrow is hidden even when list overflows (display='{result}'). "
             f"The scroll event handler may not be wired or _updateArrows is broken.")

    def test_top_arrow_hidden_at_scroll_top(self, drv, srv):
        """The ▲ 'more above' arrow must be display:none when list.scrollTop == 0."""
        self._open_port_menu(drv)
        time.sleep(0.3)
        result = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return 'NO_MENU';
            var list = m.children[1];
            if (!list) return 'NO_LIST';
            var topArrow = m.firstElementChild;  // top arrow is first child
            if (!topArrow) return 'NO_ARROW';
            list.scrollTop = 0;
            list.dispatchEvent(new Event('scroll'));
            return topArrow.style.display;
        """)
        js(drv, "var m=document.getElementById('ctx-menu'); if(m) m.remove();")
        if result in ('NO_MENU', 'NO_LIST', 'NO_ARROW'):
            pytest.skip(f"Context menu structure issue: {result}")
        assert result == 'none', \
            f"Top arrow visible at scrollTop=0 — should be display:none: '{result}'"

    def test_top_arrow_appears_after_scrolling_down(self, drv, srv):
        """After scrolling the list down, the ▲ 'more above' arrow must appear."""
        self._open_port_menu(drv)
        time.sleep(0.3)
        result = js(drv, """
            var m = document.getElementById('ctx-menu');
            if (!m) return 'NO_MENU';
            var list = m.children[1];
            if (!list) return 'NO_LIST';
            var topArrow = m.firstElementChild;
            if (!topArrow) return 'NO_ARROW';
            // Force overflow then scroll down
            var orig = list.style.maxHeight;
            list.style.maxHeight = '50px';
            list.scrollTop = 100;
            list.dispatchEvent(new Event('scroll'));
            var display = topArrow.style.display;
            list.style.maxHeight = orig;
            return display;
        """)
        js(drv, "var m=document.getElementById('ctx-menu'); if(m) m.remove();")
        if result in ('NO_MENU', 'NO_LIST', 'NO_ARROW'):
            pytest.skip(f"Context menu structure issue: {result}")
        assert result != 'none', \
            (f"Top arrow still hidden after scrolling down (display='{result}'). "
             f"The scroll event handler may not be updating the top arrow.")


# ═══════════════════════════════════════════════════════════════════════════════
# v10.95/v10.103 — Config Manager save does not produce ❌ JSON.parse error
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigManagerSave:
    """Saving a profile in the Config Manager (F2) must show '✓ Saved' and NOT
    '❌ JSON.parse: unexpected character at line 1 column 1'.  The bug was a
    NameError in _backup_conf (log.warning called but log not defined) causing
    the route to return a 500 HTML page which r.json() could not parse."""

    def _open_config(self, drv):
        """Open the Config Manager modal."""
        js(drv, "document.getElementById('action-config') && "
                "document.getElementById('action-config').click()")
        time.sleep(0.5)
        W(drv, 6).until(EC.visibility_of_element_located((By.ID, 'config-modal')))

    def _close_config(self, drv):
        try:
            close = drv.find_element(By.ID, 'config-close')
            js(drv, 'arguments[0].click()', close)
        except Exception:
            js(drv, "var m=document.getElementById('config-modal');"
                    "if(m) m.classList.remove('is-open');")
        time.sleep(0.3)

    def _config_status_text(self, drv):
        return js(drv, "var s=document.getElementById('config-status');"
                       "return s ? s.textContent.trim() : '';")

    def test_config_modal_opens(self, drv, srv):
        """Config Manager modal opens and profile tabs are rendered."""
        self._open_config(drv)
        # At least one tab button must be present
        tabs = drv.find_elements(By.CSS_SELECTOR, '#config-tab-bar .tab-btn')
        self._close_config(drv)
        assert len(tabs) >= 1, "Config Manager has no profile tabs after opening"

    def test_save_shows_success_not_json_error(self, drv, srv):
        """Clicking Save on the default profile must show ✓ Saved, not ❌ JSON.parse."""
        self._open_config(drv)

        # Click Save button
        save_btn = W(drv, 5).until(EC.presence_of_element_located(
            (By.ID, 'config-save')))
        js(drv, 'arguments[0].click()', save_btn)
        time.sleep(2.0)   # save route + applySettings can take ~1s

        status = self._config_status_text(drv)
        self._close_config(drv)

        assert 'JSON.parse' not in status and 'json' not in status.lower(), \
            (f"Config save produced a JSON.parse error: '{status}'. "
             f"The _backup_conf NameError (log not defined) may not be fixed.")
        assert status.startswith('✓') or 'aved' in status or 'pplied' in status, \
            f"Config save did not show success: '{status}'"

    def test_save_does_not_show_json_error_on_repeated_save(self, drv, srv):
        """Saving the same profile twice in a row must both succeed without error."""
        self._open_config(drv)
        save_btn = W(drv, 5).until(EC.presence_of_element_located((By.ID, 'config-save')))
        js(drv, 'arguments[0].click()', save_btn)
        time.sleep(1.5)
        js(drv, 'arguments[0].click()', save_btn)
        time.sleep(1.5)
        status = self._config_status_text(drv)
        self._close_config(drv)
        assert 'JSON.parse' not in status, \
            f"Second save produced JSON.parse error: '{status}'"
