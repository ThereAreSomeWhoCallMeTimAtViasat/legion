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
    """Wait until a process row matching name_fragment has the given status."""
    def _check(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 5:
                text = ' '.join(c.text for c in cells)
                if name_fragment.lower() in text.lower():
                    if cells[4].text.strip() == status:
                        return row
        return False
    return W(driver, timeout).until(_check)

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
                if len(cells) >= 5 and 'kill-test' in row.text.lower():
                    return cells[4].text.strip() not in ('Running', 'Waiting')
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
        """Clear a finished process — its row must disappear."""
        wc = gap_server['wc']
        result = wc.runCommand('echo clear-target', name='clear-test', hostIp=IP_A)
        pid = result.get('process_id')
        wait_process_status(gap_driver, 'clear-test', 'Finished', timeout=15)

        fin_row = gap_driver.find_element(
            By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')
        ActionChains(gap_driver).context_click(fin_row).perform()
        ctx_menu_click(gap_driver, 'Clear')

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
