"""
Phase 2 Selenium Tests — Multi-Host Data Isolation
====================================================
Proves that the UI shows the correct data for each host with no bleeding.
Each group verifies one isolation property: ports, notes, dynamic tabs,
tab indicators, and the OS tab.

Run with:
    sudo python3 -m pytest tests/test_selenium_multihost.py -v
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

MULTIHOST_PORT = 5097
POLL = 1.5

IP_A = '10.20.30.1'
IP_B = '10.20.30.2'
NOTE_A = 'host-a-note'
NOTE_B = 'host-b-note'

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.20.30.1" addrtype="ipv4"/>
    <os><osmatch name="Linux 4.x" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="10.20.30.2" addrtype="ipv4"/>
    <os><osmatch name="Windows 10" accuracy="90"/></os>
    <ports>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
      <port protocol="tcp" portid="3389"><state state="open"/><service name="ms-wbt-server"/></port>
    </ports>
  </host>
</nmaprun>"""


# ── Module-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mh_server():
    """Fresh server seeded with two distinct hosts."""
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from app.auxiliary import Filters

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
    os.unlink(p)

    # Notes
    filters = Filters()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    for h in hosts:
        ip = h.get('ip') if isinstance(h, dict) else getattr(h, 'ipv4', '') or getattr(h, 'ip', '')
        hid = h.get('id') if isinstance(h, dict) else getattr(h, 'id')
        if ip == IP_A:
            logic.activeProject.repositoryContainer.noteRepository.storeNotes(hid, NOTE_A)
        elif ip == IP_B:
            logic.activeProject.repositoryContainer.noteRepository.storeNotes(hid, NOTE_B)

    # Processes — one per host with distinct output
    wc.start()
    wc.runCommand('echo host-a-output', name='host-a-proc', hostIp=IP_A)
    wc.runCommand('echo host-b-output', name='host-b-proc', hostIp=IP_B)
    time.sleep(1)   # let processes finish before server starts

    t = threading.Thread(
        target=app.run,
        kwargs={'host': '127.0.0.1', 'port': MULTIHOST_PORT,
                'use_reloader': False, 'threaded': True},
        daemon=True)
    t.start()
    time.sleep(2)

    yield {'app': app, 'logic': logic, 'wc': wc,
           'url': f'http://127.0.0.1:{MULTIHOST_PORT}'}


@pytest.fixture(scope="module")
def mh_driver(mh_server):
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
    d.get(mh_server['url'])
    time.sleep(1.5)
    yield d
    d.quit()


@pytest.fixture(autouse=True, scope="class")
def reset_to_hosts_tab(mh_driver):
    """Before each class: return to Hosts left tab, Scan main tab."""
    try:
        mh_driver.find_element(By.TAG_NAME, 'body').click()
        try:
            mh_driver.switch_to.alert.dismiss()
        except Exception:
            pass
        for mid in ['add-hosts-modal', 'import-nmap-modal', 'config-modal',
                    'help-modal', 'filters-modal']:
            try:
                el = mh_driver.find_element(By.ID, mid)
                if 'is-open' in (el.get_attribute('class') or ''):
                    mh_driver.find_element(
                        By.CSS_SELECTOR, f'#{mid} .modal-close-btn').click()
                    time.sleep(0.1)
            except Exception:
                pass
        for tab_css in ['#main-tab-bar [data-tab="scan-tab"]',
                        '#left-tab-bar [data-tab="hosts-panel"]']:
            try:
                btn = mh_driver.find_element(By.CSS_SELECTOR, tab_css)
                if 'active' not in (btn.get_attribute('class') or ''):
                    btn.click()
            except Exception:
                pass
        mh_driver.execute_script("window.scrollTo(0,0)")
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

def click_right_tab(driver, tab_id):
    btn = driver.find_element(By.CSS_SELECTOR, f'#right-tab-bar [data-tab="{tab_id}"]')
    js_click(driver, btn)
    W(driver, 3).until(lambda d: 'active' in
                       d.find_element(By.ID, tab_id).get_attribute('class'))

def select_host(driver, ip):
    row = wait_row(driver, ip)
    js_click(driver, row)
    time.sleep(POLL)
    return row

def get_port_numbers(driver):
    """Return set of integer port numbers from the Services right tab."""
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

def get_notes_text(driver):
    """Return the current notes display text for the selected host."""
    for el_id in ('notes-display', 'notes-text'):
        try:
            el = driver.find_element(By.ID, el_id)
            txt = el.text or el.get_attribute('value') or ''
            if txt.strip():
                return txt
        except Exception:
            pass
    return ''

def get_dyn_tab_labels(driver):
    """Return list of visible dynamic tab button labels."""
    tabs = driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
    labels = []
    for t in tabs:
        txt = t.text.replace('×', '').strip()
        if txt:
            labels.append(txt)
    return labels


# ══════════════════════════════════════════════════════════════════════════════
# 1. Both hosts visible
# ══════════════════════════════════════════════════════════════════════════════

class TestBothHostsVisible:

    def test_host_a_row_appears(self, mh_driver):
        wait_row(mh_driver, IP_A, timeout=POLL * 3)

    def test_host_b_row_appears(self, mh_driver):
        wait_row(mh_driver, IP_B, timeout=POLL * 3)

    def test_exactly_two_hosts(self, mh_driver):
        rows = mh_driver.find_elements(By.CSS_SELECTOR, '#hosts-body tr[data-host-id]')
        assert len(rows) == 2, f"Expected 2 host rows, got {len(rows)}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Port isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestPortIsolation:

    def _load_ports(self, driver, ip):
        select_host(driver, ip)
        click_right_tab(driver, 'services-right')
        # Wait for the port table to refresh with THIS host's data.
        # Waiting for len(rows) > 0 is not enough — the previous host's rows
        # satisfy that condition immediately and cause the wrong host's ports
        # to be read.  Instead, wait until the host IP column contains our IP.
        W(driver, POLL * 3).until(
            lambda d: any(
                ip in (td.text or '')
                for row in d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
                for td in row.find_elements(By.TAG_NAME, 'td')
            )
        )
        return get_port_numbers(driver)

    def test_host_a_shows_only_a_ports(self, mh_driver):
        """Select host A → Services tab shows 22 and 80 only."""
        ports = self._load_ports(mh_driver, IP_A)
        assert 22 in ports, f"Port 22 missing from host A (found: {ports})"
        assert 80 in ports, f"Port 80 missing from host A (found: {ports})"
        assert 443 not in ports, f"Host B's port 443 bled into host A (ports: {ports})"
        assert 3389 not in ports, f"Host B's port 3389 bled into host A (ports: {ports})"

    def test_host_b_shows_only_b_ports(self, mh_driver):
        """Select host B → Services tab shows 443 and 3389 only."""
        ports = self._load_ports(mh_driver, IP_B)
        assert 443 in ports, f"Port 443 missing from host B (found: {ports})"
        assert 3389 in ports, f"Port 3389 missing from host B (found: {ports})"
        assert 22 not in ports, f"Host A's port 22 bled into host B (ports: {ports})"
        assert 80 not in ports, f"Host A's port 80 bled into host B (ports: {ports})"

    def test_switch_a_to_b_ports_update(self, mh_driver):
        """Select A, then switch to B — ports update to B's."""
        self._load_ports(mh_driver, IP_A)
        ports_b = self._load_ports(mh_driver, IP_B)
        assert 443 in ports_b and 22 not in ports_b, \
            f"After switching A→B, ports didn't update correctly: {ports_b}"

    def test_switch_b_to_a_ports_update(self, mh_driver):
        """Select B, then switch to A — ports revert to A's."""
        self._load_ports(mh_driver, IP_B)
        ports_a = self._load_ports(mh_driver, IP_A)
        assert 22 in ports_a and 443 not in ports_a, \
            f"After switching B→A, ports didn't revert correctly: {ports_a}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Information tab isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestInformationIsolation:

    def _load_info(self, driver, ip):
        select_host(driver, ip)
        click_right_tab(driver, 'info-right')
        # Wait until the Information tab content actually shows THIS host's IP.
        # Reading immediately after click_right_tab can return stale content
        # from the previously-selected host.
        W(driver, POLL * 3).until(
            lambda d: ip in d.find_element(By.ID, 'info-right').text)
        return driver.find_element(By.ID, 'info-right').text

    def test_host_a_info_shows_a_ip(self, mh_driver):
        info = self._load_info(mh_driver, IP_A)
        assert IP_A in info, f"{IP_A} not in Information tab for host A: {info[:200]}"
        assert IP_B not in info, f"Host B's IP leaked into host A's Information tab"

    def test_host_b_info_shows_b_ip(self, mh_driver):
        info = self._load_info(mh_driver, IP_B)
        assert IP_B in info, f"{IP_B} not in Information tab for host B: {info[:200]}"
        assert IP_A not in info, f"Host A's IP leaked into host B's Information tab"

    def test_host_a_info_shows_linux(self, mh_driver):
        info = self._load_info(mh_driver, IP_A)
        assert 'Linux' in info or '4.x' in info, \
            f"Host A OS not showing Linux in info tab: {info[:200]}"
        assert 'Windows' not in info, \
            f"Host B's Windows OS leaked into host A's info tab: {info[:200]}"

    def test_host_b_info_shows_windows(self, mh_driver):
        info = self._load_info(mh_driver, IP_B)
        assert 'Windows' in info or '10' in info, \
            f"Host B OS not showing Windows in info tab: {info[:200]}"
        assert 'Linux' not in info, \
            f"Host A's Linux OS leaked into host B's info tab: {info[:200]}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Notes isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestNotesIsolation:

    def _load_notes(self, driver, ip):
        select_host(driver, ip)
        click_right_tab(driver, 'notes-right')
        time.sleep(0.3)
        return get_notes_text(driver)

    def test_host_a_notes_visible(self, mh_driver):
        notes = self._load_notes(mh_driver, IP_A)
        assert NOTE_A in notes, f"Host A note '{NOTE_A}' not in Notes tab: {notes!r}"

    def test_host_b_notes_visible(self, mh_driver):
        notes = self._load_notes(mh_driver, IP_B)
        assert NOTE_B in notes, f"Host B note '{NOTE_B}' not in Notes tab: {notes!r}"

    def test_host_a_note_absent_from_b(self, mh_driver):
        notes = self._load_notes(mh_driver, IP_B)
        assert NOTE_A not in notes, \
            f"Host A's note '{NOTE_A}' leaked into host B's Notes tab: {notes!r}"

    def test_host_b_note_absent_from_a(self, mh_driver):
        notes = self._load_notes(mh_driver, IP_A)
        assert NOTE_B not in notes, \
            f"Host B's note '{NOTE_B}' leaked into host A's Notes tab: {notes!r}"

    def test_write_note_on_a_doesnt_change_b(self, mh_driver):
        """Type a note on host A then click host B — B's Notes tab must not show A's text.

        This tests the _noteHostId fix: the blur handler now snapshots the host ID
        when editing starts, so clicking a different host row cannot redirect the save.
        """
        select_host(mh_driver, IP_A)
        click_right_tab(mh_driver, 'notes-right')
        time.sleep(0.3)

        # Enter edit mode (click display div → _showNotesEdit captures _noteHostId = A)
        mh_driver.execute_script(
            "var d=document.getElementById('notes-display');"
            "if(d) d.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true}));")
        time.sleep(0.2)

        # Set text in textarea
        mh_driver.execute_script("""
            var ta=document.getElementById('notes-text');
            if(ta){ ta.value='ui-blur-test-A'; ta.dispatchEvent(new Event('input')); }
        """)

        # Click host B row — L.selectedHostId changes to B, but blur saves to _noteHostId (A)
        select_host(mh_driver, IP_B)
        time.sleep(0.5)

        click_right_tab(mh_driver, 'notes-right')
        time.sleep(0.3)
        notes_b = get_notes_text(mh_driver)
        assert 'ui-blur-test-A' not in notes_b, \
            f"Note from host A bled into host B after blur fix: {notes_b!r}"

    def test_switch_back_a_note_persists(self, mh_driver):
        """Note typed on host A must persist after switching to B and back."""
        select_host(mh_driver, IP_A)
        click_right_tab(mh_driver, 'notes-right')
        time.sleep(0.3)

        mh_driver.execute_script(
            "var d=document.getElementById('notes-display');"
            "if(d) d.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true}));")
        time.sleep(0.2)
        mh_driver.execute_script("""
            var ta=document.getElementById('notes-text');
            if(ta){ ta.value='ui-persist-test-A'; ta.dispatchEvent(new Event('input')); }
        """)

        # Click host B to trigger blur (saves to A via _noteHostId)
        select_host(mh_driver, IP_B)
        time.sleep(0.5)

        # Return to A — note must still be there
        select_host(mh_driver, IP_A)
        click_right_tab(mh_driver, 'notes-right')
        time.sleep(0.3)
        notes_a = get_notes_text(mh_driver)
        assert 'ui-persist-test-A' in notes_a, \
            f"Host A's note missing after switching away and back: {notes_a!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Dynamic tab isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestDynamicTabIsolation:

    def test_host_a_tabs_show_only_a_process(self, mh_driver):
        """Select A — only host-a-proc tab visible, not host-b-proc."""
        select_host(mh_driver, IP_A)
        time.sleep(POLL)   # let snapshot render tabs
        labels = get_dyn_tab_labels(mh_driver)
        a_present = any('host-a' in l.lower() for l in labels)
        b_present = any('host-b' in l.lower() for l in labels)
        assert a_present, f"Host A's process tab missing when A selected (tabs: {labels})"
        assert not b_present, f"Host B's process tab visible when A selected (tabs: {labels})"

    def test_host_b_tabs_show_only_b_process(self, mh_driver):
        """Select B — only host-b-proc tab visible, not host-a-proc."""
        select_host(mh_driver, IP_B)
        time.sleep(POLL)
        labels = get_dyn_tab_labels(mh_driver)
        b_present = any('host-b' in l.lower() for l in labels)
        a_present = any('host-a' in l.lower() for l in labels)
        assert b_present, f"Host B's process tab missing when B selected (tabs: {labels})"
        assert not a_present, f"Host A's process tab visible when B selected (tabs: {labels})"

    def test_tabs_change_on_host_switch(self, mh_driver):
        """A→B→A: tabs change each time."""
        select_host(mh_driver, IP_A)
        time.sleep(POLL)
        labels_a1 = get_dyn_tab_labels(mh_driver)

        select_host(mh_driver, IP_B)
        time.sleep(POLL)
        labels_b = get_dyn_tab_labels(mh_driver)

        select_host(mh_driver, IP_A)
        time.sleep(POLL)
        labels_a2 = get_dyn_tab_labels(mh_driver)

        # A tabs should not contain B's process name
        assert not any('host-b' in l.lower() for l in labels_a1), \
            f"B process in A tabs on first select: {labels_a1}"
        assert not any('host-a' in l.lower() for l in labels_b), \
            f"A process in B tabs: {labels_b}"
        assert not any('host-b' in l.lower() for l in labels_a2), \
            f"B process in A tabs after returning to A: {labels_a2}"

    def test_process_output_correct_for_host(self, mh_driver):
        """Click host A's process tab → output has 'host-a-output', not 'host-b-output'."""
        select_host(mh_driver, IP_A)
        time.sleep(POLL)

        dyn_tabs = mh_driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        a_tab = next(
            (t for t in dyn_tabs if 'host-a' in t.text.lower()), None)
        if not a_tab:
            pytest.skip("host-a-proc tab not visible")

        js_click(mh_driver, a_tab)
        time.sleep(POLL)

        # Find the active dynamic panel
        panels = mh_driver.find_elements(
            By.CSS_SELECTOR, '#dynamic-tabs-container .tab-content.active')
        output = ''
        if panels:
            output = panels[0].text

        assert 'host-a-output' in output, \
            f"host-a-output not in output (got: {output!r})"
        assert 'host-b-output' not in output, \
            f"host-b-output leaked into host A's process output (got: {output!r})"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Tab indicator isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestTabIndicatorIsolation:

    def _tab_is_orange(self, driver, tab_id):
        """Return True if the tab button has tab-unread class."""
        try:
            btn = driver.find_element(
                By.CSS_SELECTOR, f'#right-tab-bar [data-tab="{tab_id}"]')
            return 'tab-unread' in (btn.get_attribute('class') or '')
        except Exception:
            return False

    def test_clicking_tab_removes_orange_for_a(self, mh_driver):
        """Select A, force-mark a tab orange, click it — orange is gone."""
        select_host(mh_driver, IP_A)
        # Force-mark the info tab as unread
        mh_driver.execute_script(
            "var b=document.querySelector('#right-tab-bar [data-tab=\"info-right\"]'); if(b) b.classList.add('tab-unread');")
        assert self._tab_is_orange(mh_driver, 'info-right'), "Could not set orange"
        click_right_tab(mh_driver, 'info-right')
        time.sleep(0.3)
        assert not self._tab_is_orange(mh_driver, 'info-right'), \
            "Orange not cleared after clicking the tab"

    def test_orange_on_a_not_present_when_b_selected(self, mh_driver):
        """Force-mark host A's tab orange, switch to B — the tab is not still orange."""
        select_host(mh_driver, IP_A)
        mh_driver.execute_script(
            "var b=document.querySelector('#right-tab-bar [data-tab=\"cves-right\"]'); if(b) b.classList.add('tab-unread');")
        assert self._tab_is_orange(mh_driver, 'cves-right')

        # Switch to B — clearAllTabHighlights should fire
        select_host(mh_driver, IP_B)
        time.sleep(0.3)
        assert not self._tab_is_orange(mh_driver, 'cves-right'), \
            "Tab-unread not cleared when switching from host A to host B"


# ══════════════════════════════════════════════════════════════════════════════
# 7. OS tab isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestOSTabIsolation:

    def _open_os_tab(self, driver):
        btn = driver.find_element(By.CSS_SELECTOR, '#left-tab-bar [data-tab="os-panel"]')
        js_click(driver, btn)
        W(driver, 3).until(lambda d: 'active' in
                           d.find_element(By.ID, 'os-panel').get_attribute('class'))
        W(driver, POLL * 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#os-list-body tr')) > 0)

    def _os_list_text(self, driver):
        rows = driver.find_elements(By.CSS_SELECTOR, '#os-list-body tr')
        return ' '.join(r.text for r in rows)

    def _click_os_row(self, driver, text_fragment):
        rows = driver.find_elements(By.CSS_SELECTOR, '#os-list-body tr')
        for r in rows:
            if text_fragment.lower() in r.text.lower():
                js_click(driver, r)
                time.sleep(0.3)
                return True
        return False

    def _os_hosts_ips(self, driver):
        rows = driver.find_elements(By.CSS_SELECTOR, '#os-hosts-body tr')
        ips = set()
        for r in rows:
            cells = r.find_elements(By.TAG_NAME, 'td')
            if cells:
                # IP is typically in the first or second column
                for c in cells:
                    txt = c.text.strip()
                    if txt.count('.') == 3:
                        ips.add(txt)
        return ips

    def test_os_tab_shows_both_os(self, mh_driver):
        """OS tab must list both Linux and Windows entries."""
        self._open_os_tab(mh_driver)
        text = self._os_list_text(mh_driver)
        assert 'Linux' in text or '4.x' in text, \
            f"Linux not in OS list: {text!r}"
        assert 'Windows' in text or '10' in text, \
            f"Windows not in OS list: {text!r}"

    def test_os_linux_click_shows_host_a_only(self, mh_driver):
        """Click Linux row → only 10.20.30.1 in OS hosts list."""
        self._open_os_tab(mh_driver)
        clicked = self._click_os_row(mh_driver, 'Linux')
        if not clicked:
            self._click_os_row(mh_driver, '4.x')
        time.sleep(0.3)
        ips = self._os_hosts_ips(mh_driver)
        assert IP_A in ips, f"{IP_A} not in Linux host list: {ips}"
        assert IP_B not in ips, \
            f"{IP_B} (Windows) in Linux host list — OS filter bleeding: {ips}"

    def test_os_windows_click_shows_host_b_only(self, mh_driver):
        """Click Windows row → only 10.20.30.2 in OS hosts list."""
        self._open_os_tab(mh_driver)
        clicked = self._click_os_row(mh_driver, 'Windows')
        if not clicked:
            self._click_os_row(mh_driver, '10')
        time.sleep(0.3)
        ips = self._os_hosts_ips(mh_driver)
        assert IP_B in ips, f"{IP_B} not in Windows host list: {ips}"
        assert IP_A not in ips, \
            f"{IP_A} (Linux) in Windows host list — OS filter bleeding: {ips}"
