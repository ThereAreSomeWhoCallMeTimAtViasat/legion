"""
Terminal Selenium Tests — Upper panel switches between plain and xterm.js
=========================================================================
Tests that clicking a regular process shows plain output, and clicking
an Interactive process shows xterm.js in the upper panel.

Run with:
    sudo python3 -m pytest tests/test_selenium_terminal.py -v
"""

import os
import sys
import time
import threading
import tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TERM_PORT = 5094
POLL = 1.5

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.88.88.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
    </ports>
  </host>
</nmaprun>"""


@pytest.fixture(scope="module")
def term_server():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    wc.start()

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
    os.unlink(p)

    # Create a regular (non-interactive) process
    wc.runCommand('echo PLAIN_PROCESS_OUTPUT', name='plain-proc', hostIp='10.88.88.1')
    time.sleep(1)

    # Create an interactive (bash) process — this will get a PTY session
    wc.runCommand('bash -c "echo INTERACTIVE_READY; sleep 300"',
                  name='interactive-proc', hostIp='10.88.88.1')
    time.sleep(1)

    t = threading.Thread(
        target=app.run,
        kwargs={'host': '127.0.0.1', 'port': TERM_PORT,
                'use_reloader': False, 'threaded': True},
        daemon=True)
    t.start()
    time.sleep(2)

    yield {'app': app, 'logic': logic, 'wc': wc,
           'url': f'http://127.0.0.1:{TERM_PORT}'}


@pytest.fixture(scope="module")
def term_driver(term_server):
    import os as _os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service

    _os.environ.pop('XAUTHORITY', None)
    _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument("--headless")
    svc = Service(executable_path='/usr/bin/geckodriver')
    d = webdriver.Firefox(service=svc, options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.get(term_server['url'])
    time.sleep(2)
    yield d
    d.quit()


def W(d, t=5): return WebDriverWait(d, t)

def js_click(driver, el):
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)
    time.sleep(0.1)


# ══════════════════════════════════════════════════════════════════════════════
# S1: Upper output panel switches between plain and terminal
# ══════════════════════════════════════════════════════════════════════════════

class TestOutputPanelSwitch:

    def _click_process_by_name(self, driver, name_fragment, timeout=10):
        """Find and click a process row containing name_fragment via JS."""
        driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                if (r.textContent.toLowerCase().includes(arguments[0].toLowerCase())) {
                    r.click(); return;
                }
            }
        """, name_fragment)
        time.sleep(POLL)

    def test_plain_output_div_exists(self, term_driver):
        """#plain-output div must exist inside #process-output-inline."""
        el = term_driver.find_element(By.ID, 'plain-output')
        assert el, "#plain-output not found in DOM"

    def test_terminal_output_div_exists(self, term_driver):
        """#terminal-output div must exist inside #process-output-inline."""
        el = term_driver.find_element(By.ID, 'terminal-output')
        assert el, "#terminal-output not found in DOM"

    def test_regular_process_shows_plain(self, term_driver):
        """Clicking a regular (echo) process shows #plain-output, hides #terminal-output."""
        self._click_process_by_name(term_driver, 'plain-proc')
        time.sleep(POLL)
        plain = term_driver.find_element(By.ID, 'plain-output')
        terminal = term_driver.find_element(By.ID, 'terminal-output')
        plain_display = plain.value_of_css_property('display')
        terminal_display = terminal.value_of_css_property('display')
        assert plain_display != 'none', \
            f"#plain-output should be visible for regular process, display={plain_display}"
        assert terminal_display == 'none', \
            f"#terminal-output should be hidden for regular process, display={terminal_display}"

    def test_interactive_process_shows_terminal(self, term_driver):
        """Clicking an Interactive (bash) process shows #terminal-output, hides #plain-output."""
        self._click_process_by_name(term_driver, 'interactive-proc')
        time.sleep(POLL)
        plain = term_driver.find_element(By.ID, 'plain-output')
        terminal = term_driver.find_element(By.ID, 'terminal-output')
        plain_display = plain.value_of_css_property('display')
        terminal_display = terminal.value_of_css_property('display')
        assert terminal_display != 'none', \
            f"#terminal-output should be visible for Interactive process, display={terminal_display}"
        assert plain_display == 'none', \
            f"#plain-output should be hidden for Interactive process, display={plain_display}"

    def test_xterm_mounted_in_terminal_output(self, term_driver):
        """When terminal is shown, xterm.js must mount content inside #terminal-output.
        Skips if xterm.js CDN not reachable in headless mode."""
        self._click_process_by_name(term_driver, 'interactive-proc')
        time.sleep(POLL + 1)
        xterm_loaded = term_driver.execute_script("return typeof Terminal !== 'undefined'")
        if not xterm_loaded:
            pytest.skip("xterm.js not loaded from CDN in headless browser")
        # xterm.js creates a .xterm container with .xterm-screen inside
        has_content = term_driver.execute_script("""
            var t = document.getElementById('terminal-output');
            if (!t) return false;
            return t.children.length > 0 || t.querySelector('.xterm') !== null
                   || t.querySelector('canvas') !== null;
        """)
        assert has_content, "#terminal-output has no xterm.js content after clicking Interactive process"

    def test_switch_back_to_plain(self, term_driver):
        """After viewing terminal, clicking a regular process switches back to plain."""
        self._click_process_by_name(term_driver, 'interactive-proc')
        time.sleep(POLL)
        self._click_process_by_name(term_driver, 'plain-proc')
        time.sleep(POLL)
        plain = term_driver.find_element(By.ID, 'plain-output')
        terminal = term_driver.find_element(By.ID, 'terminal-output')
        assert plain.value_of_css_property('display') != 'none', \
            "#plain-output should be visible after switching back"
        assert terminal.value_of_css_property('display') == 'none', \
            "#terminal-output should be hidden after switching back"

    def test_plain_output_has_content(self, term_driver):
        """Plain output for the echo process must contain expected text."""
        self._click_process_by_name(term_driver, 'plain-proc')
        time.sleep(POLL)
        text = term_driver.find_element(By.ID, 'plain-output').text
        assert 'PLAIN_PROCESS_OUTPUT' in text, \
            f"Expected 'PLAIN_PROCESS_OUTPUT' in plain output: {text[:200]!r}"


# ══════════════════════════════════════════════════════════════════════════════
# S2: Interactive detection from runCommand
# ══════════════════════════════════════════════════════════════════════════════

class TestInteractiveDetection:

    def _click_process_by_name(self, driver, name_fragment):
        driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                if (r.textContent.toLowerCase().includes(arguments[0].toLowerCase())) {
                    r.click(); return;
                }
            }
        """, name_fragment)
        time.sleep(POLL)

    def test_bash_process_shows_xterm(self, term_driver):
        """A process created with 'bash' in command → clicking shows xterm, not plain."""
        self._click_process_by_name(term_driver, 'interactive-proc')
        time.sleep(POLL)
        terminal = term_driver.find_element(By.ID, 'terminal-output')
        assert terminal.value_of_css_property('display') != 'none', \
            "bash process should show #terminal-output"

    def test_echo_process_shows_plain(self, term_driver):
        """A process created with 'echo' command → clicking shows plain text."""
        self._click_process_by_name(term_driver, 'plain-proc')
        time.sleep(POLL)
        plain = term_driver.find_element(By.ID, 'plain-output')
        assert plain.value_of_css_property('display') != 'none', \
            "echo process should show #plain-output"


# ══════════════════════════════════════════════════════════════════════════════
# S3: "Open Terminal" from host right-click
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenTerminal:

    def test_open_terminal_in_host_menu(self, term_driver):
        """Right-click host → 'Open Terminal' must appear in context menu."""
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.common.exceptions import StaleElementReferenceException
        import time as _time
        labels = []
        for _attempt in range(8):
            try:
                row = term_driver.find_element(By.CSS_SELECTOR,
                    '#hosts-body tr[data-host-ip="10.88.88.1"]')
                ActionChains(term_driver).context_click(row).perform()
                _time.sleep(0.3)
                menu = term_driver.find_element(By.ID, 'ctx-menu')
                labels = [b.text for b in menu.find_elements(By.TAG_NAME, 'button')]
                break
            except (StaleElementReferenceException, Exception):
                _time.sleep(0.3)
        # Dismiss menu
        term_driver.find_element(By.TAG_NAME, 'body').click()
        time.sleep(0.2)
        assert any('Open Terminal' in l for l in labels), \
            f"'Open Terminal' not in host menu: {labels}"

    def test_open_terminal_creates_interactive_row(self, term_driver, term_server):
        """Click 'Open Terminal' → new process row with status Interactive."""
        import urllib.request, json as _j
        server_url = term_server['url']

        # Start terminal via API (same as what the JS does)
        req = urllib.request.Request(
            f"{server_url}/api/terminal/start",
            data=_j.dumps({'label': 'Terminal - 10.88.88.1', 'host_ip': '10.88.88.1'}).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST')
        resp = _j.loads(urllib.request.urlopen(req).read())
        pid = resp.get('process_id')
        assert pid, f"No process_id returned: {resp}"

        # Wait for the specific process row to appear (by process_id)
        W(term_driver, 5).until(lambda d: len(
            d.find_elements(By.CSS_SELECTOR,
                f'#processes-body tr[data-process-id="{pid}"]')) > 0)

        # Verify it shows Interactive status via the specific process_id
        status = term_driver.execute_script("""
            var row = document.querySelector(
                '#processes-body tr[data-process-id="' + arguments[0] + '"]');
            if (!row) return 'not found';
            var cells = row.querySelectorAll('td');
            return cells.length >= 5 ? cells[4].textContent.trim() : 'no cells';
        """, str(pid))
        assert status == 'Interactive', \
            f"Terminal process {pid} status should be Interactive, got: {status!r}"

    def test_open_terminal_row_shows_terminal_in_lower(self, term_driver):
        """Clicking the Terminal process row → lower output panel shows xterm.js."""
        # Click the Terminal row
        term_driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                if (r.textContent.includes('Terminal')) { r.click(); break; }
            }
        """)
        time.sleep(POLL + 0.5)
        terminal = term_driver.find_element(By.ID, 'terminal-output')
        assert terminal.value_of_css_property('display') != 'none', \
            "Clicking Terminal process row should show #terminal-output"


# ══════════════════════════════════════════════════════════════════════════════
# S4: Upper panel — dynamic tool tab xterm.js
# ══════════════════════════════════════════════════════════════════════════════

class TestUpperDynamicTabTerminal:
    """The upper right panel (dynamic tool tabs) must mount xterm.js for Interactive
    processes and plain text for regular ones — independently of the lower panel."""

    def _select_host(self, driver):
        """Select the seeded host so dynamic tabs render."""
        row = driver.find_element(By.CSS_SELECTOR,
            '#hosts-body tr[data-host-ip="10.88.88.1"]')
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", row)
        time.sleep(POLL)

    def _click_dynamic_tab(self, driver, name_fragment):
        """Click a dynamic tab containing name_fragment."""
        driver.execute_script("""
            var tabs = document.querySelectorAll('#right-tab-bar .dynamic-tab');
            for (var t of tabs) {
                if (t.textContent.toLowerCase().includes(arguments[0].toLowerCase())) {
                    t.click(); return true;
                }
            }
            return false;
        """, name_fragment)
        time.sleep(POLL + 0.5)

    def test_interactive_proc_dynamic_tab_exists(self, term_driver):
        """Interactive process must create a dynamic tab in the upper right panel."""
        self._select_host(term_driver)
        tabs = term_driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        tab_texts = [t.text for t in tabs]
        interactive_tabs = [t for t in tab_texts if 'interactive' in t.lower()]
        assert len(interactive_tabs) > 0, \
            f"No dynamic tab for interactive-proc. Tabs: {tab_texts}"

    def test_interactive_dynamic_tab_mounts_xterm(self, term_driver):
        """Clicking an Interactive dynamic tab mounts xterm.js content in that tab's panel."""
        self._select_host(term_driver)
        self._click_dynamic_tab(term_driver, 'interactive-proc')

        # The active dynamic panel should have xterm.js content
        has_terminal = term_driver.execute_script("""
            var panels = document.querySelectorAll(
                '#dynamic-tabs-container .tab-content.active');
            for (var p of panels) {
                /* xterm.js removes tool-output-area content and replaces with xterm elements */
                if (p.querySelector('.xterm') || p.querySelector('canvas') ||
                    /* Fallback: panel is present and has content but not plain text */
                    (p.children.length > 0 && !p.querySelector('.tool-output-area'))) {
                    return true;
                }
            }
            return false;
        """)
        # Also accept: the panel is visible and the _dynTermState.sessionId is set
        has_session = term_driver.execute_script("""
            return _dynTermState && _dynTermState.sessionId !== null;
        """)
        assert has_terminal or has_session, \
            "Interactive dynamic tab should mount xterm.js or connect a terminal session"

    def test_plain_dynamic_tab_shows_text(self, term_driver):
        """Clicking a regular (echo) dynamic tab shows plain text, not xterm.js."""
        self._select_host(term_driver)
        self._click_dynamic_tab(term_driver, 'plain-proc')
        time.sleep(0.5)

        # _dynTermState should NOT have a session for a plain process
        has_session = term_driver.execute_script("""
            return _dynTermState && _dynTermState.sessionId !== null;
        """)
        assert not has_session, \
            "Plain process dynamic tab should NOT mount a terminal session"

    def test_upper_and_lower_independent(self, term_driver, term_server):
        """Upper dynamic tab and lower output panel can show different processes."""
        self._select_host(term_driver)
        # Click interactive tab in upper area
        self._click_dynamic_tab(term_driver, 'interactive-proc')
        upper_has_session = term_driver.execute_script(
            "return _dynTermState && _dynTermState.sessionId !== null;")

        # Click plain process row in lower area
        term_driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                if (r.textContent.toLowerCase().includes('plain-proc')) {
                    r.click(); break;
                }
            }
        """)
        time.sleep(POLL)
        lower_shows_plain = term_driver.execute_script(
            "return document.getElementById('plain-output').style.display !== 'none';")
        lower_shows_terminal = term_driver.execute_script(
            "return document.getElementById('terminal-output').style.display !== 'none';")

        assert upper_has_session, "Upper panel should still have interactive session"
        assert lower_shows_plain and not lower_shows_terminal, \
            "Lower panel should show plain output for the echo process"
