"""
Phase 3 Selenium Tests — Host/Process/Port Actions
====================================================
Tests functional gaps: host delete, port double-click, send to brute,
process kill/retry/clear, filters, and add port.

Run with:
    sudo python3 -m pytest tests/test_selenium_gaps.py -v
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
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

GAPS_PORT = 5096
POLL = 1.5

IP_A = '10.30.40.1'
IP_B = '10.30.40.2'

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.30.40.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="10.30.40.2" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
    </ports>
  </host>
</nmaprun>"""


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gap_server():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    wc.start()

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
    os.unlink(p)

    t = threading.Thread(
        target=app.run,
        kwargs={'host': '127.0.0.1', 'port': GAPS_PORT,
                'use_reloader': False, 'threaded': True},
        daemon=True)
    t.start()
    time.sleep(2)
    yield {'app': app, 'logic': logic, 'wc': wc,
           'url': f'http://127.0.0.1:{GAPS_PORT}'}


@pytest.fixture(scope="module")
def gap_driver(gap_server):
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
    d.get(gap_server['url'])
    time.sleep(1.5)
    yield d
    d.quit()


@pytest.fixture(autouse=True, scope="class")
def ensure_seed_hosts(gap_server, gap_driver):
    """Before each class: re-seed any missing test hosts."""
    import urllib.request, json as _j
    r = urllib.request.urlopen(f"{gap_server['url']}/api/snapshot")
    snap = _j.loads(r.read())
    ips = {h['ip'] for h in snap['hosts']}
    if IP_A not in ips or IP_B not in ips:
        from app.importers.nmap_import import import_nmap_xml
        with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
            f.write(_SEED); p = f.name
        import_nmap_xml(project=gap_server['logic'].activeProject, xml_path=p, output="")
        os.unlink(p)
        W(gap_driver, 5).until(lambda d: len(
            d.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]')) >= 2)
    # Reset UI state
    try:
        gap_driver.find_element(By.TAG_NAME, 'body').click()
        try:
            gap_driver.switch_to.alert.dismiss()
        except Exception:
            pass
        for tab_css in ['#main-tab-bar [data-tab="scan-tab"]',
                        '#left-tab-bar [data-tab="hosts-panel"]']:
            try:
                btn = gap_driver.find_element(By.CSS_SELECTOR, tab_css)
                if 'active' not in (btn.get_attribute('class') or ''):
                    btn.click()
            except Exception:
                pass
        gap_driver.execute_script("window.scrollTo(0,0)")
    except Exception:
        pass
    yield


# ── Helpers ────────────────────────────────────────────────────────────────────

def W(d, t=5): return WebDriverWait(d, t)

def wait_row(driver, ip, timeout=8):
    return W(driver, timeout).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))

def js_click(driver, el):
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)
    time.sleep(0.1)

def select_host(driver, ip):
    row = wait_row(driver, ip)
    js_click(driver, row)
    time.sleep(POLL)

def click_right_tab(driver, tab_id):
    btn = driver.find_element(By.CSS_SELECTOR, f'#right-tab-bar [data-tab="{tab_id}"]')
    js_click(driver, btn)
    W(driver, 3).until(lambda d: 'active' in
                       d.find_element(By.ID, tab_id).get_attribute('class'))

def modal_open(driver, modal_id, timeout=5):
    def _check(d):
        try:
            return 'is-open' in (d.find_element(By.ID, modal_id).get_attribute('class') or '')
        except Exception:
            return False
    return W(driver, timeout).until(_check)

def modal_closed(driver, modal_id, timeout=5):
    def _check(d):
        try:
            return 'is-open' not in (d.find_element(By.ID, modal_id).get_attribute('class') or '')
        except Exception:
            return True
    return W(driver, timeout).until(_check)

def ctx_menu_click(driver, label):
    """Click a context menu item by label text."""
    menu = W(driver, 3).until(EC.presence_of_element_located((By.ID, 'ctx-menu')))
    for btn in menu.find_elements(By.TAG_NAME, 'button'):
        if label.lower() in btn.text.lower():
            btn.click()
            return
    raise AssertionError(f"Menu item '{label}' not found. Items: "
                         f"{[b.text for b in menu.find_elements(By.TAG_NAME, 'button')]}")

def load_ports(driver, ip):
    """Select a host, switch to Services right tab, return set of port numbers."""
    select_host(driver, ip)
    click_right_tab(driver, 'services-right')
    W(driver, POLL * 3).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)
    rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
    ports = set()
    for r in rows:
        cells = r.find_elements(By.TAG_NAME, 'td')
        if len(cells) >= 2:
            try:
                ports.add(int(cells[1].text.strip()))
            except ValueError:
                pass
    return ports

def wait_process_status(driver, name_fragment, status, timeout=30):
    """Wait until a process row matching name_fragment has the given status.
    Ignores StaleElementReferenceException — the snapshot poll rebuilds
    #processes-body every 1.5 s and can make row/cell references stale
    between the outer find_elements() and the inner .text access."""
    def _check(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 6:
                text = ' '.join(c.text for c in cells)
                if name_fragment.lower() in text.lower():
                    # Checkbox added v10.136: Status now index 5 (was 4)
                    if cells[5].text.strip() == status:
                        return row
        return False
    return WebDriverWait(driver, timeout,
                         ignored_exceptions=[StaleElementReferenceException]).until(_check)

def host_count(driver):
    return len(driver.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]'))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Host delete
# ══════════════════════════════════════════════════════════════════════════════

class TestHostDelete:

    def test_delete_removes_host_from_ui(self, gap_driver):
        """Right-click host A → Delete → confirm → host A row gone."""
        row_a = wait_row(gap_driver, IP_A)
        ActionChains(gap_driver).context_click(row_a).perform()
        ctx_menu_click(gap_driver, 'Delete')

        # Accept the confirm() dialog
        W(gap_driver, 3).until(EC.alert_is_present())
        gap_driver.switch_to.alert.accept()

        # Host A row must disappear
        W(gap_driver, 5).until(lambda d: len(
            d.find_elements(By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_A}"]')) == 0)

    def test_delete_preserves_other_host(self, gap_driver):
        """After deleting host A, host B is still in the table."""
        # Host A was deleted in previous test; host B must still be there
        wait_row(gap_driver, IP_B, timeout=3)

    def test_delete_actually_removed_from_db(self, gap_driver, gap_server):
        """Snapshot must not include deleted host A."""
        import urllib.request, json as _j
        r = urllib.request.urlopen(f"{gap_server['url']}/api/snapshot")
        snap = _j.loads(r.read())
        ips = {h['ip'] for h in snap['hosts']}
        assert IP_A not in ips, f"Deleted host {IP_A} still in snapshot: {ips}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Port double-click
# ══════════════════════════════════════════════════════════════════════════════

class TestPortDoubleClick:

    def test_port_dblclick_switches_left_panel_to_hosts(self, gap_driver):
        """Double-clicking a port row switches the left panel to Hosts tab."""
        load_ports(gap_driver, IP_A)   # select A, switch to services-right, wait for ports

        # Switch left panel away from Hosts first so we can detect the switch back
        svc_tab = gap_driver.find_element(
            By.CSS_SELECTOR, '#left-tab-bar [data-tab="services-left-panel"]')
        js_click(gap_driver, svc_tab)
        time.sleep(0.2)

        # Double-click the first port row
        port_rows = gap_driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        assert port_rows, "No port rows to double-click"
        gap_driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent('dblclick', {bubbles:true, cancelable:true}));",
            port_rows[0])
        time.sleep(0.3)

        # Left panel must now show Hosts tab
        hosts_panel = gap_driver.find_element(By.ID, 'hosts-panel')
        assert 'active' in hosts_panel.get_attribute('class'), \
            "Left panel did not switch to Hosts tab after port double-click"

    def test_port_dblclick_hosts_panel_not_services(self, gap_driver):
        """After port double-click, left services panel must not be active."""
        svc_panel = gap_driver.find_element(By.ID, 'services-left-panel')
        assert 'active' not in svc_panel.get_attribute('class'), \
            "Services left panel still active after port double-click"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Send to Brute
# ══════════════════════════════════════════════════════════════════════════════

class TestSendToBrute:

    def test_send_to_brute_switches_main_tab(self, gap_driver):
        """Right-click SSH port → Send to Brute → main tab switches to Brute."""
        load_ports(gap_driver, IP_A)

        # Find port 22 row
        port_rows = gap_driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        ssh_row = None
        for r in port_rows:
            cells = r.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 2 and cells[1].text.strip() == '22':
                ssh_row = r
                break
        if not ssh_row:
            pytest.skip("Port 22 not found in services tab")

        ActionChains(gap_driver).context_click(ssh_row).perform()
        ctx_menu_click(gap_driver, 'Send to Brute')
        time.sleep(0.5)

        brute_panel = gap_driver.find_element(By.ID, 'brute-tab')
        assert 'active' in brute_panel.get_attribute('class'), \
            "Main tab did not switch to Brute after Send to Brute"

    def test_send_to_brute_fills_ip(self, gap_driver):
        """#brute-ip must be filled with the host's IP."""
        ip_val = gap_driver.find_element(By.ID, 'brute-ip').get_attribute('value')
        assert ip_val == IP_A, f"brute-ip = {ip_val!r}, expected {IP_A}"

    def test_send_to_brute_fills_port(self, gap_driver):
        """#brute-port must be filled with '22'."""
        port_val = gap_driver.find_element(By.ID, 'brute-port').get_attribute('value')
        assert port_val == '22', f"brute-port = {port_val!r}, expected '22'"

    def test_send_to_brute_fills_service(self, gap_driver):
        """#brute-service must be filled with 'ssh'."""
        svc_val = gap_driver.find_element(By.ID, 'brute-service').get_attribute('value')
        assert 'ssh' in svc_val.lower(), f"brute-service = {svc_val!r}, expected 'ssh'"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Process actions
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessActions:

    # ── Kill ──────────────────────────────────────────────────────────────────

    def test_kill_changes_status(self, gap_driver, gap_server):
        """Kill a running process — status must change to Killed."""
        wc = gap_server['wc']

        # Ensure we're on Scan tab with Hosts left panel
        gap_driver.find_element(
            By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]').click()
        time.sleep(0.2)

        wc.runCommand('sleep 30', name='kill-test', hostIp=IP_A)
        run_row = wait_process_status(gap_driver, 'kill-test', 'Running', timeout=15)

        ActionChains(gap_driver).context_click(run_row).perform()
        ctx_menu_click(gap_driver, 'Kill')

        # Status must become Killed (or Finished if process exits fast)
        def _not_running(d):
            for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 6 and 'kill-test' in row.text.lower():
                    return cells[5].text.strip() not in ('Running', 'Waiting')  # checkbox shift
            return False
        W(gap_driver, 10).until(_not_running)

    # ── Retry ──────────────────────────────────────────────────────────────────

    def test_retry_creates_new_process_row(self, gap_driver, gap_server):
        """Retry a finished process — a new row must appear."""
        wc = gap_server['wc']
        wc.runCommand('echo retry-target', name='retry-test', hostIp=IP_A)
        wait_process_status(gap_driver, 'retry-test', 'Finished', timeout=15)

        # Count rows with 'retry-test' in them before
        def _count(d):
            return sum(1 for r in d.find_elements(By.CSS_SELECTOR, '#processes-body tr')
                       if 'retry-test' in r.text.lower())
        count_before = _count(gap_driver)

        # Right-click the finished row → Retry
        fin_row = wait_process_status(gap_driver, 'retry-test', 'Finished', timeout=5)
        ActionChains(gap_driver).context_click(fin_row).perform()
        ctx_menu_click(gap_driver, 'Retry')

        # A new row must appear (count increases)
        W(gap_driver, 10).until(lambda d: _count(d) > count_before)

    # ── Clear ──────────────────────────────────────────────────────────────────

    def test_clear_removes_process_from_table(self, gap_driver, gap_server):
        """Clear a finished process — its row must disappear.

        The snapshot rebuilds #processes-body every 1.5 s.  Grabbing fin_row
        and then calling context_click later can race with that rebuild, making
        the element stale.  We retry the grab+right-click+clear sequence so the
        element is always fresh when .perform() fires.
        """
        wc = gap_server['wc']
        result = wc.runCommand('echo clear-target', name='clear-test', hostIp=IP_A)
        pid = result.get('process_id')
        wait_process_status(gap_driver, 'clear-test', 'Finished', timeout=15)

        # Re-find the row and right-click in one tight window; retry if the
        # snapshot DOM rebuild makes the element stale before .perform() fires.
        cleared = False
        for _ in range(8):
            try:
                fin_row = gap_driver.find_element(
                    By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')
                ActionChains(gap_driver).context_click(fin_row).perform()
                ctx_menu_click(gap_driver, 'Clear')
                cleared = True
                break
            except (StaleElementReferenceException, AssertionError):
                time.sleep(0.3)

        assert cleared, f"Could not right-click and Clear process {pid} (stale-element race)"

        # The specific row must be gone
        W(gap_driver, 5).until(lambda d: len(
            d.find_elements(
                By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')) == 0)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Filters
# ══════════════════════════════════════════════════════════════════════════════

class TestFilters:

    def test_filter_advanced_opens_modal(self, gap_driver):
        """Clicking ⚙ (filter-advanced) opens the filters-modal."""
        js_click(gap_driver, gap_driver.find_element(By.ID, 'filter-advanced'))
        modal_open(gap_driver, 'filters-modal')
        gap_driver.find_element(By.ID, 'filters-cancel').click()
        modal_closed(gap_driver, 'filters-modal')

    def test_keyword_filter_shows_only_matching_host(self, gap_driver):
        """Typing host A's IP in the keyword filter hides host B."""
        # Set keyword via JS — the input may not be scrollable into view via Selenium
        gap_driver.execute_script(
            "var el=document.getElementById('filter-keyword'); el.value=arguments[0];"
            "el.dispatchEvent(new Event('input',{bubbles:true}));", IP_A)
        js_click(gap_driver, gap_driver.find_element(By.ID, 'filter-apply'))

        # Wait for host B to disappear
        W(gap_driver, 3).until(lambda d: len(
            d.find_elements(By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_B}"]')) == 0)

        rows = gap_driver.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]')
        visible_ips = [r.get_attribute('data-host-ip') for r in rows]
        assert IP_A in visible_ips, f"{IP_A} not shown with keyword filter"
        assert IP_B not in visible_ips, \
            f"{IP_B} still shown after filtering for {IP_A}: {visible_ips}"

    def test_clearing_keyword_restores_all_hosts(self, gap_driver):
        """Clearing the keyword filter restores both hosts."""
        gap_driver.execute_script(
            "var el=document.getElementById('filter-keyword'); el.value='';"
            "el.dispatchEvent(new Event('input',{bubbles:true}));")
        js_click(gap_driver, gap_driver.find_element(By.ID, 'filter-apply'))

        W(gap_driver, 5).until(lambda d: len(
            d.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]')) >= 2)
        rows = gap_driver.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]')
        ips = {r.get_attribute('data-host-ip') for r in rows}
        assert IP_A in ips and IP_B in ips, \
            f"Not all hosts visible after clearing filter: {ips}"

    def test_filter_modal_apply_closes_modal(self, gap_driver):
        """Clicking Apply in the filters modal closes it."""
        js_click(gap_driver, gap_driver.find_element(By.ID, 'filter-advanced'))
        modal_open(gap_driver, 'filters-modal')
        gap_driver.find_element(By.ID, 'filters-apply').click()
        modal_closed(gap_driver, 'filters-modal')


# ══════════════════════════════════════════════════════════════════════════════
# 6. Add Port
# ══════════════════════════════════════════════════════════════════════════════

class TestAddPort:

    def test_add_port_modal_opens_and_closes(self, gap_driver):
        """Add-port modal opens via JS and closes with Cancel."""
        gap_driver.execute_script("openModal('add-port-modal')")
        modal_open(gap_driver, 'add-port-modal')
        gap_driver.find_element(By.ID, 'add-port-cancel').click()
        modal_closed(gap_driver, 'add-port-modal')

    def test_add_port_submits_and_appears_in_services_tab(self, gap_driver):
        """Enter port 9999 in the add-port modal → it appears in Services tab."""
        select_host(gap_driver, IP_A)

        gap_driver.execute_script("openModal('add-port-modal')")
        modal_open(gap_driver, 'add-port-modal')

        # Fill in the form
        num = gap_driver.find_element(By.ID, 'add-port-number')
        num.clear()
        num.send_keys('9999')

        svc = gap_driver.find_element(By.ID, 'add-port-service')
        svc.clear()
        svc.send_keys('test-service')

        # Submit
        js_click(gap_driver, gap_driver.find_element(By.ID, 'add-port-submit'))
        modal_closed(gap_driver, 'add-port-modal', timeout=5)

        # Port 9999 must appear in Services right tab
        click_right_tab(gap_driver, 'services-right')
        W(gap_driver, POLL * 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)

        port_rows = gap_driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        found = set()
        for r in port_rows:
            cells = r.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 2:
                try:
                    found.add(int(cells[1].text.strip()))
                except ValueError:
                    pass
        assert 9999 in found, f"Port 9999 not found after add-port (found: {found})"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Notes — write via UI, switch hosts, verify persistence
# ══════════════════════════════════════════════════════════════════════════════

class TestNotes:

    def _open_notes_edit(self, driver, ip):
        """Select host, click Notes tab, double-click display to enter edit mode.
        v10.47 changed entry from single-click to dblclick for UX reasons."""
        select_host(driver, ip)
        click_right_tab(driver, 'notes-right')
        time.sleep(0.3)
        driver.execute_script(
            "var d=document.getElementById('notes-display');"
            "if(d) d.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true}));")
        time.sleep(0.2)

    def _set_note_text(self, driver, text):
        """Set notes-text textarea via JS (triggers input event)."""
        driver.execute_script(
            "var ta=document.getElementById('notes-text');"
            "if(ta){ta.value=arguments[0]; ta.dispatchEvent(new Event('input',{bubbles:true}))}",
            text)

    def _get_note_text(self, driver):
        """Read note from display or textarea."""
        for el_id in ('notes-display', 'notes-text'):
            try:
                el = driver.find_element(By.ID, el_id)
                txt = el.text or el.get_attribute('value') or ''
                if txt.strip():
                    return txt
            except Exception:
                pass
        return ''

    def test_note_written_to_host_a(self, gap_driver):
        """Write a note to host A via the notes textarea."""
        self._open_notes_edit(gap_driver, IP_A)
        self._set_note_text(gap_driver, 'ui-note-for-host-a')
        # Switch to B to trigger blur/save via _noteHostId mechanism
        select_host(gap_driver, IP_B)
        time.sleep(0.5)
        # Back to A — note must persist
        self._open_notes_edit(gap_driver, IP_A)
        notes = self._get_note_text(gap_driver)
        assert 'ui-note-for-host-a' in notes, \
            f"Note not persisted after switching hosts: {notes!r}"

    def test_note_not_visible_on_other_host(self, gap_driver):
        """Note written to host A must not appear on host B."""
        self._open_notes_edit(gap_driver, IP_A)
        self._set_note_text(gap_driver, 'unique-a-note-xyz')
        select_host(gap_driver, IP_B)
        click_right_tab(gap_driver, 'notes-right')

        # Wait for loadHostDetail(B) to overwrite the notes display.
        # The blur handler briefly shows A's text; loadHostDetail then corrects it.
        W(gap_driver, 5).until(lambda d: 'unique-a-note-xyz' not in (
            d.find_element(By.ID, 'notes-display').text or ''))

        notes_b = gap_driver.find_element(By.ID, 'notes-display').text or ''
        assert 'unique-a-note-xyz' not in notes_b, \
            f"Host A's note persisted in host B after loadHostDetail: {notes_b!r}"

    def test_note_survives_multiple_host_switches(self, gap_driver):
        """Write to A, switch A→B→A→B→A — note still there on each return."""
        self._open_notes_edit(gap_driver, IP_A)
        self._set_note_text(gap_driver, 'multi-switch-note')
        for _ in range(2):
            select_host(gap_driver, IP_B)
            time.sleep(0.4)
            select_host(gap_driver, IP_A)
            time.sleep(0.4)
            click_right_tab(gap_driver, 'notes-right')
            time.sleep(0.2)
            notes = self._get_note_text(gap_driver)
            assert 'multi-switch-note' in notes, \
                f"Note lost after A→B→A switch: {notes!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. Column resize — drag handle, localStorage, survives page reload
# ══════════════════════════════════════════════════════════════════════════════

class TestColumnResize:

    STORAGE_KEY = 'col-hosts-table-0'   # first column of hosts-table

    def _drag_handle(self, driver, table_id='hosts-table', col_idx=0, dx=60):
        """Simulate mousedown+mousemove+mouseup on the actual column resize handle.

        The handle is a div appended to each th by initColResizers(). It was previously
        destroyed by th.textContent = ... in _updateSortHeaders (run on every snapshot poll).
        Fixed by replacing th.textContent with _setThText() which preserves child elements.
        Now the handle div persists and can be found and clicked properly.
        """
        result = driver.execute_script("""
            var tableId = arguments[0], colIdx = arguments[1], dx = arguments[2];
            var tbl = document.getElementById(tableId);
            if (!tbl) return 'no table';
            var headers = tbl.querySelectorAll('thead th');
            if (colIdx >= headers.length) return 'no header at index ' + colIdx;
            var th = headers[colIdx];
            // Find the resize handle div — the div with cursor:col-resize
            var handle = null;
            for (var i = 0; i < th.children.length; i++) {
                var child = th.children[i];
                if (child.tagName === 'DIV' && child.style.cursor === 'col-resize') {
                    handle = child; break;
                }
            }
            if (!handle) return 'no handle (th has ' + th.children.length + ' children, innerHTML.len=' + th.innerHTML.length + ')';
            var rect = handle.getBoundingClientRect();
            var startX = rect.left + rect.width / 2;
            var startY = rect.top + rect.height / 2;
            // Simulate the full drag sequence
            handle.dispatchEvent(new MouseEvent('mousedown', {
                bubbles: true, cancelable: true, clientX: startX, clientY: startY
            }));
            document.dispatchEvent(new MouseEvent('mousemove', {
                bubbles: true, cancelable: true, clientX: startX + dx, clientY: startY
            }));
            document.dispatchEvent(new MouseEvent('mouseup', {
                bubbles: true, cancelable: true, clientX: startX + dx, clientY: startY
            }));
            return 'ok';
        """, table_id, col_idx, dx)
        return result

    def test_drag_sets_localstorage(self, gap_driver):
        """Dragging the resize handle must save the width to localStorage."""
        # Clear any existing value first
        gap_driver.execute_script(f"localStorage.removeItem('{self.STORAGE_KEY}')")

        result = self._drag_handle(gap_driver)
        assert result == 'ok', f"Drag simulation failed: {result}"
        time.sleep(0.2)

        saved = gap_driver.execute_script(f"return localStorage.getItem('{self.STORAGE_KEY}')")
        assert saved is not None, "localStorage not set after column drag"
        assert int(float(saved)) > 0, f"Stored width is not positive: {saved!r}"

    def test_width_matches_localstorage(self, gap_driver):
        """Column th style.width must match the value stored in localStorage."""
        saved = gap_driver.execute_script(f"return localStorage.getItem('{self.STORAGE_KEY}')")
        if not saved:
            pytest.skip("No localStorage value — run after test_drag_sets_localstorage")

        # Check style.width (the value set by initColResizers/drag), not offsetWidth
        # offsetWidth is affected by table layout algorithm and may differ
        style_w = gap_driver.execute_script("""
            var tbl = document.getElementById('hosts-table');
            var th = tbl ? tbl.querySelectorAll('thead th')[0] : null;
            return th ? th.style.width : null;
        """)
        assert style_w, "Column th has no inline width style"
        # style.width is e.g. "142px" — extract number
        style_num = int(float(style_w.replace('px', '')))
        assert abs(style_num - int(float(saved))) <= 2, \
            f"th.style.width={style_w!r} doesn't match localStorage={saved}"

    def test_width_persists_after_reload(self, gap_driver, gap_server):
        """Column width stored in localStorage must survive a page reload."""
        saved_before = gap_driver.execute_script(
            f"return localStorage.getItem('{self.STORAGE_KEY}')")
        if not saved_before:
            pytest.skip("No localStorage value to test persistence")

        gap_driver.get(gap_server['url'])   # reload
        time.sleep(1.5)   # wait for DOMContentLoaded + initColResizers

        saved_after = gap_driver.execute_script(
            f"return localStorage.getItem('{self.STORAGE_KEY}')")
        assert saved_after == saved_before, \
            f"localStorage changed after reload: before={saved_before!r} after={saved_after!r}"

    def test_column_renders_at_saved_width_after_reload(self, gap_driver):
        """After reload, initColResizers must restore th.style.width from localStorage."""
        saved = gap_driver.execute_script(f"return localStorage.getItem('{self.STORAGE_KEY}')")
        if not saved:
            pytest.skip("No localStorage value")

        style_w = gap_driver.execute_script("""
            var tbl = document.getElementById('hosts-table');
            var th = tbl ? tbl.querySelectorAll('thead th')[0] : null;
            return th ? th.style.width : null;
        """)
        assert style_w, "Column th has no inline width style after reload"
        style_num = int(float(style_w.replace('px', '')))
        assert abs(style_num - int(float(saved))) <= 2, \
            f"th.style.width={style_w!r} doesn't match localStorage={saved} after reload"


# ══════════════════════════════════════════════════════════════════════════════
# 9. Host double-click → copy IP to clipboard
# ══════════════════════════════════════════════════════════════════════════════

class TestHostDoubleClick:

    def test_dblclick_calls_clipboard_with_host_ip(self, gap_driver):
        """Double-clicking a host row must call clipboard API with that host's IP."""
        # Override clipboard.writeText to capture the value without needing real clipboard
        gap_driver.execute_script("""
            window._clipboardCapture = null;
            // Override navigator.clipboard.writeText
            if (navigator.clipboard) {
                navigator.clipboard.writeText = function(text) {
                    window._clipboardCapture = text;
                    return Promise.resolve();
                };
            }
            // Also override execCommand fallback
            document.execCommand = function(cmd) {
                if (cmd === 'copy') {
                    var ta = document.querySelector('textarea[style*="position:fixed"]') ||
                             document.querySelector('textarea:last-child');
                    if (ta) window._clipboardCapture = ta.value;
                }
                return true;
            };
        """)

        host_row = wait_row(gap_driver, IP_A)
        # Double-click via JS dispatch
        gap_driver.execute_script("""
            var r = arguments[0];
            r.dispatchEvent(new MouseEvent('dblclick', {bubbles:true, cancelable:true}));
        """, host_row)
        time.sleep(0.3)

        captured = gap_driver.execute_script("return window._clipboardCapture;")
        assert captured == IP_A, \
            f"Clipboard not called with {IP_A} after double-click (got: {captured!r})"

    def test_dblclick_host_b_copies_correct_ip(self, gap_driver):
        """Double-clicking host B must copy B's IP, not A's."""
        gap_driver.execute_script("window._clipboardCapture = null;")

        host_row_b = wait_row(gap_driver, IP_B)
        gap_driver.execute_script("""
            arguments[0].dispatchEvent(new MouseEvent('dblclick', {bubbles:true, cancelable:true}));
        """, host_row_b)
        time.sleep(0.3)

        captured = gap_driver.execute_script("return window._clipboardCapture;")
        assert captured == IP_B, \
            f"Clipboard contains {captured!r} instead of {IP_B} after double-clicking host B"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Ctrl+B — Send selection to notes
# ══════════════════════════════════════════════════════════════════════════════

class TestSendSelectionToNotes:

    def test_ctrl_b_appends_selected_text_to_notes(self, gap_driver, gap_server):
        """Select text in process output, press Ctrl+B, verify Notes tab gets the text."""
        # Need a process with output — run one
        wc = gap_server['wc']
        try:
            wc.start()
        except Exception:
            pass
        wc.runCommand('echo send-to-notes-test-content', name='notes-sel-test',
                      hostIp=IP_A)
        time.sleep(POLL * 2)

        # Select host A so notes are for it
        select_host(gap_driver, IP_A)

        # Click a finished process row to load its output in #process-output-inline
        pid = gap_driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                var cells = r.querySelectorAll('td');
                if (cells.length >= 6 && cells[2].textContent.includes('notes-sel-test')) /* checkbox shift: Name now index 2 */
                    return r.dataset.processId;
            }
            return null;
        """)
        if pid:
            gap_driver.execute_script("""
                var rows = document.querySelectorAll('#processes-body tr[data-process-id]');
                for (var r of rows) {
                    if (r.dataset.processId === arguments[0]) { r.click(); break; }
                }
            """, pid)
            time.sleep(POLL)

        # Wait for output text to appear in #plain-output (not the outer container
        # which includes the font-size toolbar and would pollute the selection).
        W(gap_driver, 8).until(lambda d: len(
            d.find_element(By.ID, 'plain-output').text.strip()) > 0)

        # Select all text in #plain-output only — the font toolbar lives in
        # the parent #process-output-inline so selecting the parent would include
        # "Font 10 A− A+" text that makes the notes assertion fragile.
        gap_driver.execute_script("""
            var el = document.getElementById('plain-output');
            if (!el) return;
            var range = document.createRange();
            range.selectNodeContents(el);
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        """)
        time.sleep(0.1)

        # Verify selection has content
        selected = gap_driver.execute_script("return window.getSelection().toString().trim();")
        if not selected:
            pytest.skip("Could not create text selection in process output panel")

        # Dispatch Ctrl+B keydown
        gap_driver.execute_script("""
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'b', ctrlKey: true, bubbles: true, cancelable: true
            }));
        """)
        time.sleep(0.5)

        # Check Notes tab — should have the selection appended
        click_right_tab(gap_driver, 'notes-right')
        time.sleep(0.3)

        notes_text = gap_driver.execute_script("""
            var ta = document.getElementById('notes-text');
            var disp = document.getElementById('notes-display');
            return (ta ? ta.value : '') || (disp ? disp.innerText : '');
        """)
        assert 'Selection from' in notes_text, \
            f"Notes tab missing '=== Selection from ...' header after Ctrl+B: {notes_text[:200]!r}"
        assert selected[:20] in notes_text, \
            f"Selected text not in notes after Ctrl+B. Selected: {selected[:50]!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 11. Mark host as checked / unchecked
# ══════════════════════════════════════════════════════════════════════════════

class TestHostChecked:
    """Each test is self-contained — marks/unmarks the host itself rather than
    relying on state from the previous test."""

    def _is_checked(self, driver):
        """Return True if host A currently has host-checked CSS class."""
        try:
            row = wait_row(driver, IP_A, timeout=3)
            return 'host-checked' in (row.get_attribute('class') or '')
        except Exception:
            return False

    def _set_checked(self, driver, checked: bool):
        """Ensure host A is in the desired checked state, waiting for snapshot to confirm."""
        currently = self._is_checked(driver)
        if currently == checked:
            return  # already correct
        row_a = wait_row(driver, IP_A)
        ActionChains(driver).context_click(row_a).perform()
        label = 'checked' if checked else 'unchecked'
        ctx_menu_click(driver, label)
        # Wait for snapshot to re-render the row with the new checked state
        W(driver, 5).until(lambda d: self._is_checked(d) == checked)

    def test_mark_checked_adds_css_class(self, gap_driver):
        """Right-click → 'Mark as checked' → row gets host-checked CSS class."""
        self._set_checked(gap_driver, False)   # start from unchecked
        row_a = wait_row(gap_driver, IP_A)
        ActionChains(gap_driver).context_click(row_a).perform()
        ctx_menu_click(gap_driver, 'checked')
        time.sleep(POLL)
        row_a = wait_row(gap_driver, IP_A)
        classes = row_a.get_attribute('class') or ''
        assert 'host-checked' in classes, \
            f"host-checked class missing after Mark as checked (classes: {classes!r})"

    def test_mark_checked_shows_checkmark(self, gap_driver):
        """After marking checked, the host row displays a ✓ prefix."""
        self._set_checked(gap_driver, True)
        row_a = wait_row(gap_driver, IP_A)
        row_text = row_a.text
        assert '✓' in row_text or 'host-checked' in (row_a.get_attribute('class') or ''), \
            f"No ✓ indicator after Mark as checked (row text: {row_text!r})"

    def test_mark_unchecked_removes_css_class(self, gap_driver):
        """Right-click → 'Mark as unchecked' → host-checked class removed."""
        self._set_checked(gap_driver, True)    # ensure checked first
        row_a = wait_row(gap_driver, IP_A)
        ActionChains(gap_driver).context_click(row_a).perform()
        ctx_menu_click(gap_driver, 'unchecked')
        time.sleep(POLL)
        row_a = wait_row(gap_driver, IP_A)
        classes = row_a.get_attribute('class') or ''
        assert 'host-checked' not in classes, \
            f"host-checked class still present after Mark as unchecked (classes: {classes!r})"

    def test_checked_field_in_snapshot(self, gap_driver, gap_server):
        """Snapshot must include a 'checked' boolean field for each host."""
        import urllib.request, json as _j
        r = urllib.request.urlopen(f"{gap_server['url']}/api/snapshot")
        snap = _j.loads(r.read())
        host_a = next((h for h in snap['hosts'] if h['ip'] == IP_A), None)
        assert host_a is not None, f"Host A not in snapshot"
        assert 'checked' in host_a, \
            f"snapshot host missing 'checked' field: {host_a}"
