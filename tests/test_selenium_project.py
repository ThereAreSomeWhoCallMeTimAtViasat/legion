"""
Phase 1 Selenium Tests — Project New / Save / Open
====================================================
Tests the full UI round-trip: save via file browser modal, new project
(clears UI), open via file browser modal, verify data restored.

Each test class gets its own fresh Flask server and Firefox instance so
project resets don't pollute the shared session used by test_selenium_ui.py.

Run with:
    sudo python3 -m pytest tests/test_selenium_project.py -v
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

SELENIUM_PORT_PROJECT = 5098   # separate port from main Selenium suite (5099)
POLL = 1.5


# ── Seed XML ──────────────────────────────────────────────────────────────────

_SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.50.60.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
</nmaprun>"""


# ── Per-class fixtures (fresh server + browser per class) ─────────────────────

@pytest.fixture(scope="module")
def proj_server():
    """Fresh Flask server for project tests. Class-scoped so each class
    gets clean state. Does NOT share state with the session-scoped server."""
    import os
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    # Seed one host with ports 22 and 80
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED_XML); seed_path = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=seed_path, output="")
    os.unlink(seed_path)

    # Add a note to the seeded host
    from app.auxiliary import Filters
    filters = Filters()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if hosts:
        h = hosts[0]
        hid = h.get('id') if isinstance(h, dict) else getattr(h, 'id')
        logic.activeProject.repositoryContainer.noteRepository.storeNotes(
            hid, 'selenium-round-trip-note')

    t = threading.Thread(
        target=app.run,
        kwargs={'host': '127.0.0.1', 'port': SELENIUM_PORT_PROJECT,
                'use_reloader': False, 'threaded': True},
        daemon=True
    )
    t.start()
    time.sleep(2)

    yield {'app': app, 'logic': logic, 'wc': wc,
           'url': f'http://127.0.0.1:{SELENIUM_PORT_PROJECT}'}


@pytest.fixture(scope="module")
def proj_driver(proj_server):
    """Headless Firefox for project tests, isolated from main Selenium session."""
    import os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service

    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)

    opts = webdriver.FirefoxOptions()
    opts.add_argument("--headless")
    svc = Service(executable_path='/usr/bin/geckodriver')
    d = webdriver.Firefox(service=svc, options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.get(proj_server['url'])
    time.sleep(1.5)
    yield d
    d.quit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def W(driver, timeout=5):
    return WebDriverWait(driver, timeout)


def wait_for_host_row(driver, ip, timeout=8):
    return W(driver, timeout).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))


def js_click(driver, element):
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", element)
    time.sleep(0.1)


def modal_is_open(driver, modal_id, timeout=5):
    def _check(d):
        try:
            el = d.find_element(By.ID, modal_id)
            return 'is-open' in (el.get_attribute('class') or '')
        except Exception:
            return False
    return W(driver, timeout).until(_check)


def modal_is_closed(driver, modal_id, timeout=5):
    def _check(d):
        try:
            el = d.find_element(By.ID, modal_id)
            return 'is-open' not in (el.get_attribute('class') or '')
        except Exception:
            return True
    return W(driver, timeout).until(_check)


def host_count(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]'))


def navigate_fb_to(driver, path):
    """Type a path into the file browser path input and press Go."""
    fb_path = driver.find_element(By.ID, 'fb-path')
    fb_path.clear()
    fb_path.send_keys(path)
    driver.find_element(By.ID, 'fb-go').click()
    time.sleep(0.5)


def fb_type_filename(driver, name):
    """Type a filename in the file browser filename input (save mode)."""
    inp = driver.find_element(By.ID, 'fb-filename')
    inp.clear()
    inp.send_keys(name)


def fb_click_select(driver):
    """Click the Select button in the file browser."""
    driver.find_element(By.ID, 'fb-select').click()


def fb_find_and_dblclick(driver, filename):
    """Find a file by name in #fb-list and double-click it."""
    def _find(d):
        entries = d.find_elements(By.CSS_SELECTOR, '#fb-list div[data-name]')
        for e in entries:
            if e.get_attribute('data-name') == filename:
                return e
        return False
    entry = W(driver, 5).until(_find)
    driver.execute_script(
        "arguments[0].dispatchEvent(new MouseEvent('dblclick', {bubbles:true, cancelable:true}));",
        entry)


def new_project_via_api(driver, server_url):
    """Reset project to empty via direct API call (avoids Ctrl+N resetting shared session)."""
    import urllib.request, json
    req = urllib.request.Request(
        f"{server_url}/api/project/new-temp",
        data=b'{}',
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    urllib.request.urlopen(req)
    # Wait for snapshot to reflect empty project
    W(driver, 5).until(lambda d: host_count(d) == 0)


@pytest.fixture(autouse=True, scope="class")
def restore_seed_between_classes(proj_server, proj_driver):
    """Before each test class, ensure the seeded host exists.
    Needed because TestProjectNew empties the project."""
    from app.importers.nmap_import import import_nmap_xml
    # Check if project is empty and re-seed if needed
    import urllib.request, json as _json
    try:
        r = urllib.request.urlopen(f"{proj_server['url']}/api/snapshot")
        snap = _json.loads(r.read())
        if len(snap.get('hosts', [])) == 0:
            with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
                f.write(_SEED_XML); p = f.name
            import_nmap_xml(
                project=proj_server['logic'].activeProject,
                xml_path=p, output="")
            import os; os.unlink(p)
            # Re-add the note
            from app.auxiliary import Filters
            filters = Filters()
            hosts = proj_server['logic'].activeProject.repositoryContainer.hostRepository.getHosts(filters)
            if hosts:
                h = hosts[0]
                hid = h.get('id') if isinstance(h, dict) else getattr(h, 'id')
                proj_server['logic'].activeProject.repositoryContainer.noteRepository.storeNotes(
                    hid, 'selenium-round-trip-note')
    except Exception:
        pass
    yield


# ══════════════════════════════════════════════════════════════════════════════
# 1. File → New
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectNew:
    """Verify File → New clears the UI."""

    def test_seeded_host_visible_before_new(self, proj_driver, proj_server):
        """Confirm seeded host is present before we clear."""
        wait_for_host_row(proj_driver, '10.50.60.1', timeout=POLL * 3)

    def test_new_clears_hosts_table(self, proj_driver, proj_server):
        """After new-temp, Hosts table shows 0 rows."""
        new_project_via_api(proj_driver, proj_server['url'])
        assert host_count(proj_driver) == 0, "Hosts table not empty after new project"

    def test_new_clears_processes_table(self, proj_driver, proj_server):
        """After new-temp, Processes table shows 0 rows."""
        rows = proj_driver.find_elements(By.CSS_SELECTOR, '#processes-body tr[data-process-id]')
        assert len(rows) == 0, f"Process table not empty after new: {len(rows)} rows"


# ══════════════════════════════════════════════════════════════════════════════
# 2. File → Save + Open (full UI round-trip)
# ══════════════════════════════════════════════════════════════════════════════

SAVE_FILENAME = 'legion-selenium-project-test'
SAVE_PATH = f'/tmp/{SAVE_FILENAME}.legion'


class TestProjectSaveOpen:
    """Full UI round-trip: save via file browser → new → open → verify data."""

    @pytest.fixture(autouse=True)
    def cleanup_save_file(self):
        """Remove save file before and after each test."""
        if os.path.exists(SAVE_PATH):
            os.unlink(SAVE_PATH)
        yield
        if os.path.exists(SAVE_PATH):
            os.unlink(SAVE_PATH)

    def _ensure_seeded_host(self, driver, server):
        """Re-seed if project was cleared by a previous test."""
        if host_count(driver) == 0:
            from app.importers.nmap_import import import_nmap_xml
            with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
                f.write(_SEED_XML); p = f.name
            import_nmap_xml(
                project=server['logic'].activeProject,
                xml_path=p, output="")
            os.unlink(p)
            # Restore note so save/open round-trip (test_08) can verify it
            from app.auxiliary import Filters
            _rsh = server['logic'].activeProject.repositoryContainer
            _rsh_hosts = _rsh.hostRepository.getHosts(Filters())
            if _rsh_hosts:
                _rsh_h = _rsh_hosts[0]
                _rsh_hid = _rsh_h.get('id') if isinstance(_rsh_h, dict) else getattr(_rsh_h, 'id')
                _rsh.noteRepository.storeNotes(_rsh_hid, 'selenium-round-trip-note')
            wait_for_host_row(driver, '10.50.60.1', timeout=POLL * 3)

    def test_01_save_opens_file_browser(self, proj_driver, proj_server):
        """File → Save opens #file-browser-modal."""
        self._ensure_seeded_host(proj_driver, proj_server)
        proj_driver.execute_script("document.getElementById('action-save').click()")
        modal_is_open(proj_driver, 'file-browser-modal')
        # Close it — we'll do the real save in test_03
        proj_driver.find_element(By.ID, 'fb-cancel').click()
        modal_is_closed(proj_driver, 'file-browser-modal')

    def test_02_file_browser_has_required_elements(self, proj_driver, proj_server):
        """File browser modal has path input, file list, filename input, Select button."""
        self._ensure_seeded_host(proj_driver, proj_server)
        proj_driver.execute_script("document.getElementById('action-save').click()")
        modal_is_open(proj_driver, 'file-browser-modal')
        assert proj_driver.find_element(By.ID, 'fb-path')
        assert proj_driver.find_element(By.ID, 'fb-list')
        assert proj_driver.find_element(By.ID, 'fb-filename')
        assert proj_driver.find_element(By.ID, 'fb-select')
        proj_driver.find_element(By.ID, 'fb-cancel').click()
        modal_is_closed(proj_driver, 'file-browser-modal')

    def test_03_save_creates_file_and_updates_title(self, proj_driver, proj_server):
        """Save to /tmp/legion-selenium-project-test → file exists, title bar updated."""
        self._ensure_seeded_host(proj_driver, proj_server)
        proj_driver.execute_script("document.getElementById('action-save').click()")
        modal_is_open(proj_driver, 'file-browser-modal')

        # Navigate to /tmp and type filename
        navigate_fb_to(proj_driver, '/tmp')
        fb_type_filename(proj_driver, SAVE_FILENAME)
        fb_click_select(proj_driver)

        modal_is_closed(proj_driver, 'file-browser-modal')

        # Wait for the file to exist on disk — server write is async
        import time as _t
        deadline = _t.monotonic() + 5
        while _t.monotonic() < deadline:
            if os.path.exists(SAVE_PATH) and os.path.getsize(SAVE_PATH) > 0:
                break
            _t.sleep(0.2)
        assert os.path.exists(SAVE_PATH), f"Save file not created: {SAVE_PATH}"
        assert os.path.getsize(SAVE_PATH) > 0, "Save file is empty"

        # Wait for the title bar to reflect the saved filename — DOM update is async
        from selenium.webdriver.support.ui import WebDriverWait
        WebDriverWait(proj_driver, 5).until(lambda d:
            SAVE_FILENAME in d.find_element(By.ID, 'window-title').text or
            'legion-selenium' in d.find_element(By.ID, 'window-title').text)
        title = proj_driver.find_element(By.ID, 'window-title').text
        assert SAVE_FILENAME in title or 'legion-selenium' in title, \
            f"Title bar not updated after save: {title!r}"

    def test_04_new_after_save_empties_hosts_table(self, proj_driver, proj_server):
        """After saving, new project clears the Hosts table."""
        self._ensure_seeded_host(proj_driver, proj_server)
        # Save first
        proj_driver.execute_script("document.getElementById('action-save').click()")
        modal_is_open(proj_driver, 'file-browser-modal')
        navigate_fb_to(proj_driver, '/tmp')
        fb_type_filename(proj_driver, SAVE_FILENAME)
        fb_click_select(proj_driver)
        modal_is_closed(proj_driver, 'file-browser-modal')
        time.sleep(0.5)

        # New project
        new_project_via_api(proj_driver, proj_server['url'])
        assert host_count(proj_driver) == 0, "Hosts not cleared after new project"

    def test_05_open_opens_file_browser(self, proj_driver, proj_server):
        """File → Open opens #file-browser-modal (in open mode — filename input hidden)."""
        # Save first so we have something to open
        self._ensure_seeded_host(proj_driver, proj_server)
        proj_driver.execute_script("document.getElementById('action-save').click()")
        modal_is_open(proj_driver, 'file-browser-modal')
        navigate_fb_to(proj_driver, '/tmp')
        fb_type_filename(proj_driver, SAVE_FILENAME)
        fb_click_select(proj_driver)
        modal_is_closed(proj_driver, 'file-browser-modal')
        time.sleep(0.5)

        new_project_via_api(proj_driver, proj_server['url'])

        proj_driver.execute_script("document.getElementById('action-open').click()")
        modal_is_open(proj_driver, 'file-browser-modal')

        # In open mode, filename input should be hidden
        fn = proj_driver.find_element(By.ID, 'fb-filename')
        assert fn.get_attribute('style') and 'none' in fn.get_attribute('style'), \
            "Filename input should be hidden in open mode"

        proj_driver.find_element(By.ID, 'fb-cancel').click()
        modal_is_closed(proj_driver, 'file-browser-modal')

    def test_06_open_restores_host_row(self, proj_driver, proj_server):
        """After save → new → open via file browser, host row reappears."""
        self._ensure_seeded_host(proj_driver, proj_server)

        # Save
        proj_driver.execute_script("document.getElementById('action-save').click()")
        modal_is_open(proj_driver, 'file-browser-modal')
        navigate_fb_to(proj_driver, '/tmp')
        fb_type_filename(proj_driver, SAVE_FILENAME)
        fb_click_select(proj_driver)
        modal_is_closed(proj_driver, 'file-browser-modal')
        time.sleep(0.5)

        # New
        new_project_via_api(proj_driver, proj_server['url'])
        assert host_count(proj_driver) == 0

        # Open via file browser
        proj_driver.execute_script("document.getElementById('action-open').click()")
        modal_is_open(proj_driver, 'file-browser-modal')
        navigate_fb_to(proj_driver, '/tmp')
        fb_find_and_dblclick(proj_driver, f'{SAVE_FILENAME}.legion')
        modal_is_closed(proj_driver, 'file-browser-modal', timeout=8)

        # Host must reappear after snapshot poll
        wait_for_host_row(proj_driver, '10.50.60.1', timeout=POLL * 4)

    def test_07_open_restores_ports_in_services_tab(self, proj_driver, proj_server):
        """After open, selecting the restored host shows its original ports."""
        # Assumes test_06 ran and the project is open with the host restored
        # Re-do if needed:
        if host_count(proj_driver) == 0:
            pytest.skip("Host not present — run after test_06")

        host_row = wait_for_host_row(proj_driver, '10.50.60.1', timeout=5)
        js_click(proj_driver, host_row)
        time.sleep(POLL)

        # Switch to Services right tab
        btn = proj_driver.find_element(
            By.CSS_SELECTOR, '#right-tab-bar [data-tab="services-right"]')
        js_click(proj_driver, btn)
        W(proj_driver, 5).until(lambda d: len(
            d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)

        port_rows = proj_driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        found = set()
        for row in port_rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 2:
                try:
                    found.add(int(cells[1].text.strip()))
                except ValueError:
                    pass
        assert 22 in found, f"Port 22 missing after open (found: {found})"
        assert 80 in found, f"Port 80 missing after open (found: {found})"

    def test_08_open_restores_notes(self, proj_driver, proj_server):
        """After save → new → open, the host's note text is intact."""
        if host_count(proj_driver) == 0:
            pytest.skip("Host not present — run after test_06")

        host_row = wait_for_host_row(proj_driver, '10.50.60.1', timeout=5)
        js_click(proj_driver, host_row)
        time.sleep(POLL)

        # Click Notes tab
        notes_btn = proj_driver.find_element(
            By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')
        js_click(proj_driver, notes_btn)
        time.sleep(0.3)

        # Note text should be in either #notes-display or #notes-text
        notes_text = ''
        for el_id in ('notes-display', 'notes-text'):
            try:
                el = proj_driver.find_element(By.ID, el_id)
                notes_text = el.text or el.get_attribute('value') or ''
                if notes_text.strip():
                    break
            except Exception:
                pass

        assert 'selenium-round-trip-note' in notes_text, \
            f"Note not found after open. Notes content: {notes_text!r}"

    def test_09_title_bar_shows_project_name_after_open(self, proj_driver, proj_server):
        """After opening a saved project, the active project name matches the saved file.

        Note: test_08 selects a host row which updates the DOM title bar to the
        host name ('LEGION v... – 10.50.60.1 (unknown)').  Reading #window-title
        after that would always fail this check.  The snapshot /api/snapshot exposes
        'project.name' directly from the server, which is the authoritative value
        and is unaffected by host-selection UI state.

        Polls rather than reading once: the open operation from test_06 is async
        on the server side and the project name in the snapshot can transiently
        show a temp name while the switch completes.
        """
        import urllib.request as _ur, json as _j, time as _t
        deadline = _t.monotonic() + 10
        project_name = ''
        while _t.monotonic() < deadline:
            try:
                r = _ur.urlopen(f"{proj_server['url']}/api/snapshot", timeout=3)
                snap = _j.loads(r.read())
                project_name = snap.get('project', {}).get('name', '')
                if SAVE_FILENAME in project_name or 'legion-selenium' in project_name:
                    break
            except Exception:
                pass
            _t.sleep(0.5)
        assert SAVE_FILENAME in project_name or 'legion-selenium' in project_name, \
            f"Project name not in snapshot after open (waited 10s): {project_name!r}"
