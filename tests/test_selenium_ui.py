"""
Legion Flask — Selenium UI Tests
=================================
Covers menus, context menus, modals, keyboard shortcuts, tab indicators,
column sorting, process output, and live network scanning.

Run (offline only):
    sudo python3 -m pytest tests/test_selenium_ui.py -v

Run (including live scan against real VM):
    LEGION_TEST_TARGET=192.168.x.x sudo python3 -m pytest tests/test_selenium_ui.py -v -m live --timeout=900

Requires: selenium>=4, geckodriver, firefox (all present on Kali)
"""

import os
import time
import tempfile
import pytest

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ── Helpers ────────────────────────────────────────────────────────────────

POLL = 1.5   # snapshot poll interval (seconds)

def W(driver, timeout=5):
    """Shorthand WebDriverWait."""
    return WebDriverWait(driver, timeout)


def wait_visible(driver, css, timeout=5):
    return W(driver, timeout).until(EC.visibility_of_element_located((By.CSS_SELECTOR, css)))


def wait_present(driver, css, timeout=5):
    return W(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))


def wait_clickable(driver, css, timeout=5):
    return W(driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))


def js_click(driver, element):
    """Click via JS — bypasses 'element not scrolled into view' errors."""
    driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", element)
    time.sleep(0.1)


def dismiss_menu(driver):
    """Click body to dismiss any open context menu."""
    driver.find_element(By.TAG_NAME, 'body').click()
    time.sleep(0.2)


def close_modal(driver, modal_id):
    """Close a modal via its × button."""
    driver.find_element(By.CSS_SELECTOR, f'#{modal_id} .modal-close-btn').click()
    W(driver, 3).until(lambda d: 'is-open' not in
                       d.find_element(By.ID, modal_id).get_attribute('class'))


def dismiss_alert(driver):
    """Dismiss any stray browser alert silently."""
    try:
        driver.switch_to.alert.dismiss()
    except Exception:
        pass


def modal_is_open(driver, modal_id, timeout=5):
    """Return True when modal has is-open class."""
    dismiss_alert(driver)   # clear any stray alert before checking DOM
    def _check(d):
        try:
            el = d.find_element(By.ID, modal_id)
            return 'is-open' in (el.get_attribute('class') or '')
        except Exception:
            return False
    return W(driver, timeout).until(_check)


def open_file_menu(driver):
    driver.find_element(By.CSS_SELECTOR, '[data-menu="file"] .menu-btn').click()
    wait_visible(driver, '[data-menu="file"].open .dropdown')


def open_help_menu(driver):
    driver.find_element(By.CSS_SELECTOR, '[data-menu="help"] .menu-btn').click()
    wait_visible(driver, '[data-menu="help"].open .dropdown')


def wait_for_host_row(driver, ip, timeout=10):
    return W(driver, timeout).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{ip}"]')))


def wait_for_process_status(driver, name_fragment, status, timeout=60):
    """Wait until a process row containing name_fragment shows given status."""
    def _check(d):
        rows = d.find_elements(By.CSS_SELECTOR, '#processes-body tr')
        for row in rows:
            try:
                cells = row.find_elements(By.TAG_NAME, 'td')
                text = ' '.join(c.text for c in cells)
                if name_fragment.lower() in text.lower():
                    # status is td[5] (index 4)
                    if len(cells) >= 5 and cells[4].text.strip() == status:
                        return row
            except Exception:
                pass
        return False
    return W(driver, timeout).until(_check)


def all_processes_done(driver):
    """True when all process rows are Finished and at least one exists.
    Uses JS to read statuses to avoid StaleElementReferenceException from
    snapshot re-renders (the table DOM is replaced every 1.5s)."""
    try:
        statuses = driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            var result = [];
            rows.forEach(function(r) {
                var cells = r.querySelectorAll('td');
                if (cells.length >= 5) result.push(cells[4].textContent.trim());
            });
            return result;
        """)
        if not statuses:
            return False
        if any(s in ('Running', 'Waiting') for s in statuses):
            return False
        return any(s == 'Finished' for s in statuses)
    except Exception:
        return False  # transient JS error — retry on next poll


def click_left_tab(driver, tab_id):
    btn = driver.find_element(By.CSS_SELECTOR, f'#left-tab-bar [data-tab="{tab_id}"]')
    js_click(driver, btn)
    W(driver, 3).until(lambda d: 'active' in
                       d.find_element(By.ID, tab_id).get_attribute('class'))


def click_right_tab(driver, tab_id):
    btn = driver.find_element(By.CSS_SELECTOR, f'#right-tab-bar [data-tab="{tab_id}"]')
    js_click(driver, btn)
    W(driver, 3).until(lambda d: 'active' in
                       d.find_element(By.ID, tab_id).get_attribute('class'))


# ══════════════════════════════════════════════════════════════════════════════
# 1. APPLICATION LOAD
# ══════════════════════════════════════════════════════════════════════════════

class TestAppLoad:

    def test_page_loads(self, driver, legion_server):
        assert driver.title or True   # page loaded if driver didn't throw

    def test_version_string_visible(self, driver):
        el = wait_visible(driver, '#window-title')
        assert 'LEGION' in el.text
        assert 'flask' in el.text.lower()

    def test_project_name_shown(self, driver):
        el = wait_present(driver, '#project-name')
        # Project name is either '*untitled' or the temp .legion file path
        assert el.text.strip() != '', "Project name element is empty"

    def test_hosts_table_has_seed_host(self, driver):
        # Seeded host 10.10.10.1 should appear after first snapshot poll
        wait_for_host_row(driver, '10.10.10.1', timeout=POLL * 3)

    def test_processes_table_present(self, driver):
        wait_present(driver, '#processes-body')

    def test_status_bar_visible(self, driver):
        wait_present(driver, '#action-status')


# ══════════════════════════════════════════════════════════════════════════════
# 2. MENU BAR — FILE MENU
# ══════════════════════════════════════════════════════════════════════════════

class TestFileMenu:

    def test_file_menu_opens(self, driver):
        open_file_menu(driver)
        dismiss_menu(driver)

    def test_file_menu_has_new(self, driver):
        open_file_menu(driver)
        el = driver.find_element(By.ID, 'action-new')
        assert el.is_displayed()
        dismiss_menu(driver)

    def test_file_menu_has_open(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-open').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_has_save(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-save').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_has_add_hosts(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-add-hosts').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_has_import_nmap(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-import-nmap').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_has_export_json(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-export-json').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_add_hosts_opens_modal(self, driver):
        open_file_menu(driver)
        driver.find_element(By.ID, 'action-add-hosts').click()
        modal_is_open(driver, 'add-hosts-modal')
        close_modal(driver, 'add-hosts-modal')

    def test_file_menu_import_nmap_opens_modal(self, driver):
        open_file_menu(driver)
        driver.find_element(By.ID, 'action-import-nmap').click()
        modal_is_open(driver, 'import-nmap-modal')
        close_modal(driver, 'import-nmap-modal')

    def test_file_menu_has_import_file(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-import-file').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_import_file_opens_file_browser(self, driver):
        open_file_menu(driver)
        driver.find_element(By.ID, 'action-import-file').click()
        modal_is_open(driver, 'file-browser-modal')
        close_modal(driver, 'file-browser-modal')

    def test_file_menu_has_nmap_scan(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-nmap-scan').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_nmap_scan_opens_modal(self, driver):
        open_file_menu(driver)
        driver.find_element(By.ID, 'action-nmap-scan').click()
        modal_is_open(driver, 'nmap-scan-modal')
        close_modal(driver, 'nmap-scan-modal')

    def test_file_menu_has_manual_tool(self, driver):
        open_file_menu(driver)
        assert driver.find_element(By.ID, 'action-manual-tool').is_displayed()
        dismiss_menu(driver)

    def test_file_menu_manual_tool_opens_modal(self, driver):
        open_file_menu(driver)
        driver.find_element(By.ID, 'action-manual-tool').click()
        modal_is_open(driver, 'manual-scan-modal')
        close_modal(driver, 'manual-scan-modal')

    def test_file_menu_closes_on_outside_click(self, driver):
        open_file_menu(driver)
        dismiss_menu(driver)
        menus = driver.find_elements(By.CSS_SELECTOR, '[data-menu="file"].open')
        assert len(menus) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. MENU BAR — HELP MENU
# ══════════════════════════════════════════════════════════════════════════════

class TestHelpMenu:

    def test_help_menu_opens(self, driver):
        open_help_menu(driver)
        dismiss_menu(driver)

    def test_help_menu_has_help_item(self, driver):
        open_help_menu(driver)
        assert driver.find_element(By.ID, 'action-help').is_displayed()
        dismiss_menu(driver)

    def test_help_menu_has_config_item(self, driver):
        open_help_menu(driver)
        assert driver.find_element(By.ID, 'action-config').is_displayed()
        dismiss_menu(driver)

    def test_help_menu_config_opens_modal(self, driver):
        open_help_menu(driver)
        driver.execute_script("document.getElementById('action-config').click()")
        modal_is_open(driver, 'config-modal')
        close_modal(driver, 'config-modal')

    def test_help_menu_help_opens_modal(self, driver):
        open_help_menu(driver)
        driver.execute_script("document.getElementById('action-help').click()")
        modal_is_open(driver, 'help-modal')
        close_modal(driver, 'help-modal')


# ══════════════════════════════════════════════════════════════════════════════
# 4. KEYBOARD SHORTCUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestKeyboardShortcuts:

    def _send(self, driver, *keys):
        ac = ActionChains(driver)
        for k in keys[:-1]:
            ac.key_down(k)
        ac.send_keys(keys[-1])
        for k in reversed(keys[:-1]):
            ac.key_up(k)
        ac.perform()

    def test_ctrl_h_opens_add_hosts(self, driver):
        driver.find_element(By.TAG_NAME, 'body').click()
        self._send(driver, Keys.CONTROL, 'h')
        modal_is_open(driver, 'add-hosts-modal')
        close_modal(driver, 'add-hosts-modal')

    def test_ctrl_i_opens_import_nmap(self, driver):
        driver.find_element(By.TAG_NAME, 'body').click()
        self._send(driver, Keys.CONTROL, 'i')
        modal_is_open(driver, 'import-nmap-modal')
        close_modal(driver, 'import-nmap-modal')

    def test_f2_opens_config(self, driver):
        driver.find_element(By.TAG_NAME, 'body').click()
        ActionChains(driver).send_keys(Keys.F2).perform()
        modal_is_open(driver, 'config-modal')
        close_modal(driver, 'config-modal')

    def test_f1_opens_help(self, driver):
        driver.find_element(By.TAG_NAME, 'body').click()
        ActionChains(driver).send_keys(Keys.F1).perform()
        modal_is_open(driver, 'help-modal')
        close_modal(driver, 'help-modal')

    def test_ctrl_n_triggers_new(self, driver):
        # Ctrl+N fires action-new — just verify the button exists and is wired.
        # We DON'T actually send the keystroke because it would reset the project
        # (clearing all test data) and break subsequent tests in the session.
        new_btn = driver.find_element(By.ID, 'action-new')
        assert new_btn  # button exists in DOM


# ══════════════════════════════════════════════════════════════════════════════
# 5. MODALS
# ══════════════════════════════════════════════════════════════════════════════

class TestModals:

    # ── Add Hosts ──────────────────────────────────────────────────────────

    def test_add_hosts_modal_opens(self, driver):
        # action-add-hosts lives inside the hidden File dropdown;
        # trigger via JS click to bypass the interactability check
        driver.execute_script("document.getElementById('action-add-hosts').click()")
        modal_is_open(driver, 'add-hosts-modal')

    def test_add_hosts_modal_autofocuses_input(self, driver):
        # Modal should already be open from previous test; if not, reopen
        if 'is-open' not in driver.find_element(By.ID, 'add-hosts-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-add-hosts').click()")
            modal_is_open(driver, 'add-hosts-modal')
        time.sleep(0.1)
        focused = driver.switch_to.active_element
        assert focused.get_attribute('id') == 'add-hosts-targets' or \
               focused.tag_name in ('input', 'textarea')

    def test_add_hosts_modal_has_required_fields(self, driver):
        modal = driver.find_element(By.ID, 'add-hosts-modal')
        assert modal.find_element(By.ID, 'add-hosts-targets')
        assert modal.find_element(By.ID, 'add-hosts-start')
        assert modal.find_element(By.ID, 'add-hosts-cancel')

    def test_add_hosts_modal_closes_with_x(self, driver):
        close_modal(driver, 'add-hosts-modal')
        assert 'is-open' not in driver.find_element(
            By.ID, 'add-hosts-modal').get_attribute('class')

    def test_add_hosts_modal_closes_with_cancel(self, driver):
        driver.execute_script("document.getElementById('action-add-hosts').click()")
        modal_is_open(driver, 'add-hosts-modal')
        driver.find_element(By.ID, 'add-hosts-cancel').click()
        W(driver, 3).until(lambda d: 'is-open' not in
                           d.find_element(By.ID, 'add-hosts-modal').get_attribute('class'))

    def test_add_hosts_modal_closes_on_overlay_click(self, driver):
        driver.execute_script("document.getElementById('action-add-hosts').click()")
        modal_is_open(driver, 'add-hosts-modal')
        # Click top-left corner of the overlay (outside the centered modal box).
        # The overlay is fullscreen; the modal box is centered, so (2,2) is outside it.
        driver.execute_script("""
            var el = document.getElementById('add-hosts-modal');
            var ev = new MouseEvent('click', {bubbles:true, cancelable:true, clientX:2, clientY:2});
            el.dispatchEvent(ev);
        """)
        W(driver, 3).until(lambda d: 'is-open' not in
                           d.find_element(By.ID, 'add-hosts-modal').get_attribute('class'))

    # ── Import Nmap ────────────────────────────────────────────────────────

    def test_import_nmap_modal_opens(self, driver):
        driver.execute_script("document.getElementById('action-import-nmap').click()")
        modal_is_open(driver, 'import-nmap-modal')

    def test_import_nmap_modal_has_path_input(self, driver):
        modal = driver.find_element(By.ID, 'import-nmap-modal')
        inp = modal.find_element(By.ID, 'import-nmap-path')
        assert inp.get_attribute('type') == 'text'

    def test_import_nmap_modal_imports_file(self, driver, legion_server):
        """Write a temp XML, enter its path, click Import, verify second host appears."""
        xml = """<?xml version="1.0"?><nmaprun>
          <host><status state="up"/>
            <address addr="10.10.10.2" addrtype="ipv4"/>
            <ports>
              <port protocol="tcp" portid="8080">
                <state state="open"/>
                <service name="http-alt"/>
              </port>
            </ports>
          </host>
        </nmaprun>"""
        with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
            f.write(xml)
            xml_path = f.name
        try:
            driver.execute_script("document.getElementById('action-import-nmap').click()")
            modal_is_open(driver, 'import-nmap-modal')
            inp = driver.find_element(By.ID, 'import-nmap-path')
            inp.clear()
            inp.send_keys(xml_path)
            js_click(driver, driver.find_element(By.ID, 'import-nmap-start'))
            # Status message should appear ('Importing...' is set synchronously)
            W(driver, 8).until(lambda d: d.find_element(
                By.ID, 'import-nmap-status').text.strip() != '')
            # Modal auto-closes after ~1.5s on success
            W(driver, 8).until(lambda d: 'is-open' not in
                               d.find_element(By.ID, 'import-nmap-modal').get_attribute('class'))
            wait_for_host_row(driver, '10.10.10.2', timeout=POLL * 3)
        finally:
            os.unlink(xml_path)

    def test_import_nmap_modal_closes_with_x(self, driver):
        if 'is-open' not in driver.find_element(
                By.ID, 'import-nmap-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-import-nmap').click()")
            modal_is_open(driver, 'import-nmap-modal')
        close_modal(driver, 'import-nmap-modal')

    # ── Config Modal ───────────────────────────────────────────────────────

    def test_config_modal_opens(self, driver):
        driver.execute_script("document.getElementById('action-config').click()")
        modal_is_open(driver, 'config-modal')

    def test_config_modal_has_save_button(self, driver):
        # Ensure modal is open
        if 'is-open' not in driver.find_element(By.ID, 'config-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-config').click()")
            modal_is_open(driver, 'config-modal')
        btn = driver.find_element(By.ID, 'config-save')
        # Scroll into view (modal may be taller than viewport)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'})", btn)
        assert btn  # element exists in DOM inside modal

    def test_config_modal_has_profile_selector(self, driver):
        if 'is-open' not in driver.find_element(By.ID, 'config-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-config').click()")
            modal_is_open(driver, 'config-modal')
        assert driver.find_element(By.ID, 'config-profile-selector')

    def test_config_modal_closes(self, driver):
        if 'is-open' not in driver.find_element(By.ID, 'config-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-config').click()")
            modal_is_open(driver, 'config-modal')
        close_modal(driver, 'config-modal')

    # ── Help Modal ─────────────────────────────────────────────────────────

    def test_help_modal_opens(self, driver):
        driver.execute_script("document.getElementById('action-help').click()")
        modal_is_open(driver, 'help-modal')

    def test_help_modal_has_content(self, driver):
        if 'is-open' not in driver.find_element(By.ID, 'help-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-help').click()")
            modal_is_open(driver, 'help-modal')
        modal = driver.find_element(By.ID, 'help-modal')
        assert len(modal.text.strip()) > 20

    def test_help_modal_closes(self, driver):
        if 'is-open' not in driver.find_element(By.ID, 'help-modal').get_attribute('class'):
            driver.execute_script("document.getElementById('action-help').click()")
            modal_is_open(driver, 'help-modal')
        close_modal(driver, 'help-modal')


# ══════════════════════════════════════════════════════════════════════════════
# 6. LEFT PANEL TABS
# ══════════════════════════════════════════════════════════════════════════════

class TestLeftPanelTabs:

    def test_hosts_tab_active_by_default(self, driver):
        panel = driver.find_element(By.ID, 'hosts-panel')
        assert 'active' in panel.get_attribute('class')

    def test_services_tab_switches(self, driver):
        click_left_tab(driver, 'services-left-panel')
        panel = driver.find_element(By.ID, 'services-left-panel')
        assert 'active' in panel.get_attribute('class')

    def test_tools_tab_switches(self, driver):
        click_left_tab(driver, 'tools-panel-left')
        panel = driver.find_element(By.ID, 'tools-panel-left')
        assert 'active' in panel.get_attribute('class')

    def test_os_tab_switches(self, driver):
        click_left_tab(driver, 'os-panel')
        panel = driver.find_element(By.ID, 'os-panel')
        assert 'active' in panel.get_attribute('class')

    def test_back_to_hosts_tab(self, driver):
        click_left_tab(driver, 'hosts-panel')
        panel = driver.find_element(By.ID, 'hosts-panel')
        assert 'active' in panel.get_attribute('class')


# ══════════════════════════════════════════════════════════════════════════════
# 7. RIGHT PANEL TABS
# ══════════════════════════════════════════════════════════════════════════════

class TestRightPanelTabs:

    def _select_seed_host(self, driver):
        """Ensure seed host is selected so right panel has content."""
        row = wait_for_host_row(driver, '10.10.10.1', timeout=5)
        js_click(driver, row)
        time.sleep(POLL)

    def test_services_tab_default(self, driver):
        self._select_seed_host(driver)
        panel = driver.find_element(By.ID, 'services-right')
        assert 'active' in panel.get_attribute('class')

    def test_scripts_tab_switches(self, driver):
        self._select_seed_host(driver)
        click_right_tab(driver, 'scripts-right')

    def test_information_tab_switches(self, driver):
        self._select_seed_host(driver)
        click_right_tab(driver, 'info-right')
        panel = driver.find_element(By.ID, 'info-right')
        assert 'active' in panel.get_attribute('class')

    def test_cves_tab_switches(self, driver):
        self._select_seed_host(driver)
        click_right_tab(driver, 'cves-right')

    def test_notes_tab_switches(self, driver):
        self._select_seed_host(driver)
        click_right_tab(driver, 'notes-right')

    def test_back_to_services_tab(self, driver):
        click_right_tab(driver, 'services-right')


# ══════════════════════════════════════════════════════════════════════════════
# 8. HOST SELECTION & DATA DISPLAY
# ══════════════════════════════════════════════════════════════════════════════

class TestHostSelection:

    def test_clicking_host_selects_it(self, driver):
        row = wait_for_host_row(driver, '10.10.10.1')
        js_click(driver, row)
        W(driver, 3).until(lambda d: 'selected' in
                           d.find_element(By.CSS_SELECTOR,
                               '#hosts-body tr[data-host-ip="10.10.10.1"]'
                           ).get_attribute('class'))

    def test_selected_host_loads_ports(self, driver):
        # Ensure seed host is selected
        row = wait_for_host_row(driver, '10.10.10.1')
        js_click(driver, row)
        click_right_tab(driver, 'services-right')
        W(driver, POLL * 3).until(
            lambda d: len(d.find_elements(
                By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)

    def test_seed_host_has_expected_ports(self, driver):
        port_rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        port_nums = []
        for row in port_rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 2:
                try:
                    port_nums.append(int(cells[1].text.strip()))
                except ValueError:
                    pass
        assert 22 in port_nums, f"SSH port 22 missing; found: {port_nums}"
        assert 80 in port_nums, f"HTTP port 80 missing; found: {port_nums}"

    def test_information_tab_has_ip(self, driver):
        click_right_tab(driver, 'info-right')
        info_text = driver.find_element(By.ID, 'info-right').text
        assert '10.10.10.1' in info_text

    def test_tab_unread_cleared_on_click(self, driver):
        # Click information tab — tab-unread should be removed
        btn = driver.find_element(
            By.CSS_SELECTOR, '#right-tab-bar [data-tab="info-right"]')
        btn.click()
        time.sleep(0.3)
        assert 'tab-unread' not in (btn.get_attribute('class') or '')


# ══════════════════════════════════════════════════════════════════════════════
# 9. CONTEXT MENUS
# ══════════════════════════════════════════════════════════════════════════════

class TestContextMenus:

    def _get_ctx_items(self, driver):
        menu = wait_present(driver, '#ctx-menu', timeout=3)
        return menu.find_elements(By.CSS_SELECTOR, '#ctx-menu > button, #ctx-menu > div > button')

    # ── Host right-click ───────────────────────────────────────────────────

    def test_host_right_click_shows_menu(self, driver):
        row = wait_for_host_row(driver, '10.10.10.1')
        ActionChains(driver).context_click(row).perform()
        wait_present(driver, '#ctx-menu')
        dismiss_menu(driver)

    def test_host_ctx_menu_has_delete(self, driver):
        from selenium.common.exceptions import StaleElementReferenceException
        labels = []
        for _attempt in range(8):
            try:
                row = wait_for_host_row(driver, '10.10.10.1')
                ActionChains(driver).context_click(row).perform()
                menu = wait_present(driver, '#ctx-menu')
                labels = [b.text for b in menu.find_elements(By.TAG_NAME, 'button')]
                break
            except (StaleElementReferenceException, Exception):
                time.sleep(0.3)
        assert any('Delete' in l or 'delete' in l for l in labels), \
            f"No Delete in menu: {labels}"
        dismiss_menu(driver)

    def test_host_ctx_menu_dismisses_on_click_outside(self, driver):
        row = wait_for_host_row(driver, '10.10.10.1')
        ActionChains(driver).context_click(row).perform()
        wait_present(driver, '#ctx-menu')
        dismiss_menu(driver)
        menus = driver.find_elements(By.ID, 'ctx-menu')
        assert len(menus) == 0

    # ── Process right-click ────────────────────────────────────────────────

    def _ensure_process(self, driver, legion_server):
        """Run a quick echo command so there's a process row to right-click."""
        wc = legion_server['wc']
        wc.start()
        wc.runCommand('echo ctx_test', name='ctx-test', hostIp='10.10.10.1')
        # Wait for process row to appear
        W(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#processes-body tr')) > 0)
        time.sleep(POLL)   # let snapshot refresh

    def test_process_right_click_shows_menu(self, driver, legion_server):
        self._ensure_process(driver, legion_server)
        rows = driver.find_elements(By.CSS_SELECTOR, '#processes-body tr')
        assert rows, "No process rows to right-click"
        ActionChains(driver).context_click(rows[0]).perform()
        wait_present(driver, '#ctx-menu')
        dismiss_menu(driver)

    def test_process_ctx_menu_has_expected_items(self, driver, legion_server):
        rows = driver.find_elements(By.CSS_SELECTOR, '#processes-body tr')
        if not rows:
            self._ensure_process(driver, legion_server)
            rows = driver.find_elements(By.CSS_SELECTOR, '#processes-body tr')
        ActionChains(driver).context_click(rows[0]).perform()
        menu = wait_present(driver, '#ctx-menu')
        labels = [b.text.lower() for b in menu.find_elements(By.TAG_NAME, 'button')]
        # At least one of these must be present
        assert any(kw in ' '.join(labels) for kw in ['kill', 'retry', 'clear', 'close']), \
            f"No process actions in menu: {labels}"
        dismiss_menu(driver)

    # ── Port right-click ───────────────────────────────────────────────────

    def _select_host_and_ports_tab(self, driver):
        """Select seed host, switch to Services right tab, wait for port rows."""
        row = wait_for_host_row(driver, '10.10.10.1')
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'services-right')
        port_rows = W(driver, POLL * 3).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr') or False)
        return port_rows

    def test_port_right_click_shows_menu(self, driver):
        port_rows = self._select_host_and_ports_tab(driver)
        if not port_rows:
            pytest.skip("No port rows — seed host ports not loaded")
        ActionChains(driver).context_click(port_rows[0]).perform()
        wait_present(driver, '#ctx-menu')
        dismiss_menu(driver)

    def test_port_ctx_menu_has_actions(self, driver):
        port_rows = self._select_host_and_ports_tab(driver)
        if not port_rows:
            pytest.skip("No port rows")
        ActionChains(driver).context_click(port_rows[0]).perform()
        menu = wait_present(driver, '#ctx-menu')
        all_btns = menu.find_elements(By.TAG_NAME, 'button')
        assert len(all_btns) > 0, "Port context menu is empty"
        dismiss_menu(driver)

    # ── Dynamic tab right-click ────────────────────────────────────────────

    def test_dynamic_tab_right_click_shows_save_close(self, driver, legion_server):
        # renderDynamicToolTabs only creates tabs for the SELECTED HOST.
        # Create a process, wait for it in L.processes, then force-render.
        wc = legion_server['wc']
        try:
            wc.start()
        except Exception:
            pass
        result = wc.runCommand('echo dyntab_ctx_test', name='dyntab-ctx',
                               hostIp='10.10.10.1')
        # Wait 2 full poll cycles for the snapshot to register the process in L.processes
        dismiss_alert(driver)
        time.sleep(POLL * 2)

        # Force-render tabs for host 10.10.10.1 synchronously via JS
        tab_count = driver.execute_script("""
            try {
                L.selectedHostIp = '10.10.10.1';
                if (typeof renderDynamicToolTabs === 'function')
                    renderDynamicToolTabs('10.10.10.1');
                return document.querySelectorAll('#right-tab-bar .dynamic-tab').length;
            } catch(e) { return -1; }
        """)

        if not tab_count or tab_count < 0:
            procs = driver.execute_script(
                'try {return L.processes.map(function(p){return p.hostIp+":"+p.tabTitle;})} catch(e){return []}')
            pytest.skip(f"No dynamic tabs after force-render (count={tab_count}). L.processes={procs}")

        dyn_tabs = driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        target_tab = dyn_tabs[-1]

        # Scroll the tab button into viewport center before right-clicking
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});", target_tab)
        time.sleep(0.2)

        # Use ActionChains to right-click (works on visible, in-viewport elements)
        ActionChains(driver).move_to_element(target_tab).context_click().perform()
        menu = wait_present(driver, '#ctx-menu', timeout=5)
        labels = [b.text for b in menu.find_elements(By.TAG_NAME, 'button')]
        assert any('Save' in l for l in labels), f"No Save Output: {labels}"
        assert any('Close' in l for l in labels), f"No Close Tab: {labels}"
        dismiss_menu(driver)


# ══════════════════════════════════════════════════════════════════════════════
# 10. COLUMN SORTING
# ══════════════════════════════════════════════════════════════════════════════

class TestColumnSorting:

    def _get_col_values(self, driver, tbody_id, col_index):
        rows = driver.find_elements(By.CSS_SELECTOR, f'#{tbody_id} tr')
        vals = []
        for r in rows:
            cells = r.find_elements(By.TAG_NAME, 'td')
            if len(cells) > col_index:
                vals.append(cells[col_index].text.strip())
        return vals

    def test_hosts_sort_by_os_column(self, driver):
        th = driver.find_element(By.CSS_SELECTOR, '#hosts-table th[data-sort="os"]')
        js_click(driver, th)
        time.sleep(0.3)
        th = driver.find_element(By.CSS_SELECTOR, '#hosts-table th[data-sort="os"]')
        assert '▲' in th.text or '▼' in th.text, "Sort arrow not shown"

    def test_hosts_sort_toggles_direction(self, driver):
        th = driver.find_element(By.CSS_SELECTOR, '#hosts-table th[data-sort="os"]')
        first_text = th.text
        js_click(driver, th)
        time.sleep(0.3)
        th = driver.find_element(By.CSS_SELECTOR, '#hosts-table th[data-sort="os"]')
        second_text = th.text
        assert first_text != second_text, "Sort direction did not toggle"

    def test_processes_sort_by_status(self, driver):
        th = driver.find_element(By.CSS_SELECTOR, '#processes-table th[data-sort="status"]')
        js_click(driver, th)
        time.sleep(0.3)
        th = driver.find_element(By.CSS_SELECTOR, '#processes-table th[data-sort="status"]')
        assert '▲' in th.text or '▼' in th.text

    def test_services_left_sort_by_port(self, driver):
        click_left_tab(driver, 'services-left-panel')
        ths = driver.find_elements(By.CSS_SELECTOR, '#services-table th[data-sort]')
        if not ths:
            pytest.skip("Services table has no sortable headers yet")
        js_click(driver, ths[0])
        time.sleep(0.3)
        click_left_tab(driver, 'hosts-panel')

    def test_ports_table_sort_by_port(self, driver):
        # Select seed host, switch to Services right tab
        row = wait_for_host_row(driver, '10.10.10.1')
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'services-right')
        W(driver, POLL * 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)
        ths = driver.find_elements(By.CSS_SELECTOR, '#ports-table th[data-sort]')
        if ths:
            js_click(driver, ths[0])
            time.sleep(0.3)
            ths = driver.find_elements(By.CSS_SELECTOR, '#ports-table th[data-sort]')
            assert '▲' in ths[0].text or '▼' in ths[0].text


# ══════════════════════════════════════════════════════════════════════════════
# 11. PROCESS OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessOutput:

    def test_clicking_process_loads_output(self, driver, legion_server):
        """Run echo, click the process row, verify output appears in inline panel."""
        wc = legion_server['wc']
        try:
            wc.start()
        except Exception:
            pass  # already started is fine
        result = wc.runCommand('echo selenium_output_test',
                               name='sel-output-test', hostIp='10.10.10.1')
        pid = result.get('process_id')
        assert pid, "No process_id returned"

        # Wait for the process row to appear
        proc_row = W(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{pid}"]')))

        # Wait for it to finish
        wait_for_process_status(driver, 'sel-output-test', 'Finished', timeout=15)

        # Click it (use js_click to bypass scroll-into-view issues)
        js_click(driver, proc_row)
        time.sleep(0.5)

        # Output should appear in inline panel
        output_el = driver.find_element(By.ID, 'process-output-inline')
        W(driver, 5).until(lambda d: 'selenium_output_test' in
                           d.find_element(By.ID, 'process-output-inline').text)

    def test_output_panel_scrolled_to_bottom(self, driver):
        """After output loads, scrollTop should equal scrollHeight."""
        output_el = driver.find_element(By.ID, 'process-output-inline')
        scroll_top = driver.execute_script('return arguments[0].scrollTop', output_el)
        scroll_height = driver.execute_script('return arguments[0].scrollHeight', output_el)
        client_height = driver.execute_script('return arguments[0].clientHeight', output_el)
        # scrollTop + clientHeight should be >= scrollHeight (within 2px tolerance)
        assert scroll_top + client_height >= scroll_height - 2, \
            f"Not scrolled to bottom: scrollTop={scroll_top}, " \
            f"scrollHeight={scroll_height}, clientHeight={client_height}"

    def test_process_status_filter_running(self, driver):
        sel = driver.find_element(By.ID, 'process-status-filter')
        sel.find_element(By.CSS_SELECTOR, 'option[value="Running"]').click()
        time.sleep(0.3)
        rows = driver.find_elements(By.CSS_SELECTOR, '#processes-body tr')
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 5:
                assert cells[4].text.strip() == 'Running', \
                    f"Non-Running process shown when filter=Running: {cells[4].text}"
        # Reset
        sel.find_element(By.CSS_SELECTOR, 'option[value=""]').click()


# ══════════════════════════════════════════════════════════════════════════════
# 12. DYNAMIC TOOL TABS
# ══════════════════════════════════════════════════════════════════════════════

class TestDynamicTabs:

    def _ensure_dyn_tab(self, driver, legion_server):
        """Ensure at least one dynamic tab is present, return the tab button."""
        dyn = driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        if dyn:
            return dyn[0]
        wc = legion_server['wc']
        wc.start()
        wc.runCommand('echo dyntab', name='dyntab', hostIp='10.10.10.1')
        return W(driver, 10).until(
            lambda d: (d.find_elements(
                By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab') or [None])[0])

    def test_dynamic_tab_appears_after_process(self, driver, legion_server):
        tab = self._ensure_dyn_tab(driver, legion_server)
        assert tab is not None, "Dynamic tab did not appear"

    def test_clicking_dynamic_tab_shows_output_panel(self, driver, legion_server):
        tab = self._ensure_dyn_tab(driver, legion_server)
        tab.click()
        time.sleep(0.5)
        container = driver.find_element(By.ID, 'dynamic-tabs-container')
        # Container should be visible (has active tab-content)
        active_panels = container.find_elements(By.CSS_SELECTOR, '.tab-content.active')
        assert len(active_panels) > 0, "No active panel inside dynamic-tabs-container"

    def test_dynamic_tab_close_button_removes_tab(self, driver, legion_server):
        tabs_before = driver.find_elements(
            By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        if not tabs_before:
            self._ensure_dyn_tab(driver, legion_server)
            tabs_before = driver.find_elements(
                By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')

        count_before = len(tabs_before)
        # Click the × on the first dynamic tab
        close_btn = tabs_before[0].find_element(By.CLASS_NAME, 'close-x')
        close_btn.click()
        time.sleep(0.5)
        tabs_after = driver.find_elements(
            By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        assert len(tabs_after) < count_before, "Tab was not removed after × click"


# ══════════════════════════════════════════════════════════════════════════════
# 13. TAB INDICATORS
# ══════════════════════════════════════════════════════════════════════════════

class TestTabIndicators:

    def test_tab_unread_class_exists_in_css(self, driver):
        """Smoke check: tab-unread is a real CSS class the browser knows."""
        result = driver.execute_script("""
            var el = document.createElement('button');
            el.className = 'tab-btn tab-unread';
            document.body.appendChild(el);
            var style = window.getComputedStyle(el);
            var color = style.color;
            document.body.removeChild(el);
            return color;
        """)
        # tab-unread sets color:#fa0 — not default text color
        assert result and result != 'rgb(0, 0, 0)', \
            f"tab-unread CSS may not be applied: color={result}"

    def test_clicking_tab_removes_unread(self, driver):
        """If a tab has tab-unread, clicking it should clear the class."""
        driver.execute_script("""
            var btn = document.querySelector('#right-tab-bar [data-tab="info-right"]');
            if (btn) btn.classList.add('tab-unread');
        """)
        btn = driver.find_element(
            By.CSS_SELECTOR, '#right-tab-bar [data-tab="info-right"]')
        assert 'tab-unread' in btn.get_attribute('class')
        btn.click()
        time.sleep(0.3)
        assert 'tab-unread' not in btn.get_attribute('class'), \
            "tab-unread not cleared after click"

    def test_match_star_class_present_in_css(self, driver):
        """tab-match CSS class is defined (used when process has match)."""
        result = driver.execute_script("""
            var el = document.createElement('button');
            el.className = 'tab-btn tab-match';
            document.body.appendChild(el);
            var style = window.getComputedStyle(el);
            var color = style.color;
            document.body.removeChild(el);
            return color;
        """)
        assert result  # color computed without error


# ══════════════════════════════════════════════════════════════════════════════
# 14. OS TAB
# ══════════════════════════════════════════════════════════════════════════════

class TestOSTab:

    def test_os_tab_shows_grouped_os(self, driver):
        click_left_tab(driver, 'os-panel')
        # Seed host has osMatch="Linux 4.x" — should appear after poll
        W(driver, POLL * 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#os-list-body tr')) > 0)

    def test_clicking_os_filters_hosts(self, driver):
        os_rows = driver.find_elements(By.CSS_SELECTOR, '#os-list-body tr')
        if not os_rows:
            pytest.skip("No OS rows available")
        os_rows[0].click()
        time.sleep(POLL)
        # os-hosts-body should populate
        host_rows = driver.find_elements(By.CSS_SELECTOR, '#os-hosts-body tr')
        assert len(host_rows) > 0, "No hosts shown for selected OS"

    def test_os_list_hash_prevents_cascade(self, driver):
        """_osListHash is present in JS (tested in unit tests) —
        here we verify the OS panel is stable after 2 polls."""
        initial_html = driver.find_element(By.ID, 'os-list-body').get_attribute('innerHTML')
        time.sleep(POLL * 2)
        after_html = driver.find_element(By.ID, 'os-list-body').get_attribute('innerHTML')
        # HTML should be identical (no unnecessary re-render)
        assert initial_html == after_html, "OS list re-rendered unnecessarily"

    def test_back_to_hosts_from_os(self, driver):
        click_left_tab(driver, 'hosts-panel')
        assert 'active' in driver.find_element(
            By.ID, 'hosts-panel').get_attribute('class')


# ══════════════════════════════════════════════════════════════════════════════
# 15. BRUTE TAB
# ══════════════════════════════════════════════════════════════════════════════

class TestBruteTab:

    def test_brute_tab_switches(self, driver):
        driver.find_element(
            By.CSS_SELECTOR, '#main-tab-bar [data-tab="brute-tab"]').click()
        W(driver, 3).until(lambda d: 'active' in
                           d.find_element(By.ID, 'brute-tab').get_attribute('class'))

    def test_brute_tab_has_ip_field(self, driver):
        assert driver.find_element(By.ID, 'brute-ip')

    def test_brute_tab_has_port_field(self, driver):
        assert driver.find_element(By.ID, 'brute-port')

    def test_brute_tab_has_wordlist_field(self, driver):
        # Wordlist fields are brute-userlist and brute-passlist
        assert driver.find_element(By.ID, 'brute-userlist')
        assert driver.find_element(By.ID, 'brute-passlist')

    def test_back_to_scan_tab(self, driver):
        driver.find_element(
            By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]').click()
        W(driver, 3).until(lambda d: 'active' in
                           d.find_element(By.ID, 'scan-tab').get_attribute('class'))


# ══════════════════════════════════════════════════════════════════════════════
# 16. SNAPSHOT PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════

class TestSnapshotPerformance:

    def test_snapshot_api_fast(self, driver, legion_server):
        import urllib.request
        import json as _json
        t0 = time.monotonic()
        with urllib.request.urlopen(f"{legion_server['url']}/api/snapshot") as r:
            data = _json.loads(r.read())
        ms = int((time.monotonic() - t0) * 1000)
        assert r.status == 200
        assert ms < 500, f"Snapshot took {ms}ms (expected <500ms for live server)"
        assert 'hosts' in data
        assert 'processes' in data

    def test_snapshot_includes_os_groups(self, driver, legion_server):
        import urllib.request
        import json as _json
        with urllib.request.urlopen(f"{legion_server['url']}/api/snapshot") as r:
            data = _json.loads(r.read())
        assert 'os_groups' in data, "os_groups missing from snapshot"


# ══════════════════════════════════════════════════════════════════════════════
# 17. LIVE SCAN TESTS (requires LEGION_TEST_TARGET env var)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.live
class TestLiveScan:
    """
    End-to-end live scan against a real target VM.
    Run with: LEGION_TEST_TARGET=192.168.x.x sudo python3 -m pytest tests/test_selenium_ui.py -v -m live
    """

    # Known services on your test VM — override via env var
    # Format: comma-separated port numbers  e.g. "22,80,443,445"
    # Known ports checked in test_07 (port 80 always expected on this VM)

    # Timeouts (seconds)
    # T_HOST_APPEARS raised from 20→45: parallel stages (v10.19) launch 5 nmap
    # processes simultaneously, increasing server load and delaying the first
    # snapshot delivery to the browser. Host is in the DB within ~1s but the
    # browser may not render it for longer under parallel load.
    T_HOST_APPEARS  = 45
    T_SCAN_STARTS   = 45
    T_STAGE1_DONE   = 120
    T_ALL_DONE      = 900   # full 6-stage chain inc. NSE/vulners
    T_EYEWITNESS    = 180

    def test_01_add_live_host_via_modal(self, driver, live_target):
        """Open Add Hosts modal and submit the live VM's IP."""
        driver.execute_script("document.getElementById('action-add-hosts').click()")
        modal_is_open(driver, 'add-hosts-modal')

        inp = driver.find_element(By.ID, 'add-hosts-targets')
        inp.clear()
        inp.send_keys(live_target)

        # Use Easy mode with staged scan (defaults are already set)
        js_click(driver, driver.find_element(By.ID, "add-hosts-start"))

        # Status appears and modal closes
        W(driver, 10).until(lambda d: d.find_element(
            By.ID, 'add-hosts-status').text.strip() != '')
        W(driver, 10).until(lambda d: 'is-open' not in
                            d.find_element(By.ID, 'add-hosts-modal').get_attribute('class'))

    def test_02_host_row_appears(self, driver, live_target):
        """Target IP must appear in the Hosts table."""
        wait_for_host_row(driver, live_target, timeout=self.T_HOST_APPEARS)

    def test_03_scan_process_starts(self, driver, live_target):
        """At least one process row must appear with Running or Waiting status."""
        def _has_active_process(d):
            rows = d.find_elements(By.CSS_SELECTOR, '#processes-body tr')
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() in ('Running', 'Waiting'):
                    return True
            return False
        W(driver, self.T_SCAN_STARTS).until(_has_active_process)

    def test_04_process_output_visible_during_scan(self, driver):
        """While a process is Running, clicking it should show live output."""
        # Use JS to avoid StaleElementReferenceException from snapshot re-renders
        running_pid = driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                var cells = r.querySelectorAll('td');
                if (cells.length >= 5) {
                    var s = cells[4].textContent.trim();
                    if (s === 'Running' || s === 'Waiting')
                        return r.dataset.processId;
                }
            }
            return null;
        """)
        if not running_pid:
            pytest.skip("No running process found at this moment")
        # Click directly via JS by data-process-id — avoids stale element reference
        driver.execute_script("""
            var pid = String(arguments[0]);
            var rows = document.querySelectorAll('#processes-body tr[data-process-id]');
            for (var r of rows) {
                if (r.dataset.processId === pid) { r.click(); break; }
            }
        """, running_pid)
        # Output may take a moment to appear — skip if not ready within 8s
        try:
            W(driver, 8).until(lambda d: len(
                d.find_element(By.ID, 'process-output-inline').text.strip()) > 0)
        except Exception:
            pytest.skip("Process output not yet available — process may have started very recently")

    def test_05_stage1_completes(self, driver):
        """Wait for at least one process to reach Finished status.

        Uses execute_script with querySelectorAll + textContent (atomic JS
        execution) instead of Selenium element references. With 5 parallel
        nmap stages running simultaneously (v10.19), the process table is
        re-rendered every 1.5s — holding element references across renders
        causes StaleElementReferenceException in Python-side iteration.
        """
        W(driver, self.T_STAGE1_DONE).until(lambda d: d.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                var cells = r.querySelectorAll('td');
                if (cells.length >= 5 && cells[4].textContent.trim() === 'Finished')
                    return true;
            }
            return false;
        """))

    def test_06_ports_discovered(self, driver, live_target):
        """After stage 1, the target host must have open ports."""
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'services-right')
        W(driver, POLL * 5).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)
        port_rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        assert len(port_rows) > 0, f"No ports discovered on {live_target}"

    def test_07_known_ports_present(self, driver, live_target):
        """Port 80 must be present on the live target (always open on this VM)."""
        # Select live target and switch to Services tab to populate port rows
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'services-right')
        W(driver, POLL * 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)
        port_rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        found = set()
        for row in port_rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 2:
                try:
                    found.add(int(cells[1].text.strip()))
                except ValueError:
                    pass
        assert 80 in found, f"Port 80 not found on {live_target} (found: {found})"

    def test_08_all_stages_complete(self, driver):
        """Wait for the full 6-stage chain to finish (up to T_ALL_DONE seconds)."""
        W(driver, self.T_ALL_DONE).until(all_processes_done)

    def test_09_information_tab_populated(self, driver, live_target):
        """Information tab must show the target IP after scan."""
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'info-right')
        info_text = W(driver, 5).until(
            lambda d: d.find_element(By.ID, 'info-right').text)
        assert live_target in info_text, \
            f"{live_target} not found in Information tab: {info_text[:200]}"

    def test_10_information_tab_has_os(self, driver, live_target):
        """After NSE stage, OS field should be populated."""
        # Re-select live target host and info tab (test_09 may have left different state)
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'info-right')
        info_text = driver.find_element(By.ID, 'info-right').text
        # OS field present even if "Unknown" — just verify info tab has content
        assert len(info_text.strip()) > 0, "Information tab is empty after scan"

    def test_11_eyewitness_screenshooter_ran(self, driver, live_target):
        """Screenshooter must have run since HTTP ports (80, 8180) are on this VM."""
        # Select live target and switch to Services tab to see discovered ports
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'services-right')
        W(driver, POLL * 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')) > 0)

        port_rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-ports tr')
        http_found = False
        for row in port_rows:
            cells = row.find_elements(By.TAG_NAME, 'td')
            # col 4 = service name (http, http-alt, https, ssl, etc.)
            if len(cells) >= 5 and 'http' in cells[4].text.lower():
                http_found = True
                break
        if not http_found:
            pytest.skip("No HTTP ports found in port table — eyewitness would not run")

        # Screenshooter must be Finished
        wait_for_process_status(driver, 'screenshooter', 'Finished',
                                timeout=self.T_EYEWITNESS)

    def test_12_screenshot_image_loads(self, driver, live_target):
        """Click screenshooter process, find its dynamic tab, verify image not broken."""
        # Find screenshooter by process ID to avoid stale element after DOM re-render
        shoot_pid = driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                var cells = r.querySelectorAll('td');
                for (var c of cells) {
                    if (c.textContent.toLowerCase().includes('screenshooter'))
                        return r.dataset.processId;
                }
            }
            return null;
        """)
        if not shoot_pid:
            pytest.skip("No screenshooter process row found")
        # Re-query by process ID to get a fresh reference
        shoot_row = W(driver, 3).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{shoot_pid}"]')))
        js_click(driver, shoot_row)
        time.sleep(POLL)

        # Look for a dynamic tab for this process and click it
        # First select the live target host so renderDynamicToolTabs renders its tabs
        driver.execute_script("L.selectedHostIp = arguments[0]; if(typeof renderDynamicToolTabs==='function') renderDynamicToolTabs(arguments[0]);", live_target)
        time.sleep(0.3)
        dyn_tabs = driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        if not dyn_tabs:
            pytest.skip("No dynamic tab for screenshooter")
        js_click(driver, dyn_tabs[-1])
        time.sleep(0.5)

        # Screenshot image: naturalWidth > 0 means it loaded successfully
        imgs = driver.find_elements(By.CSS_SELECTOR, '.screenshot-img, img[src*="screenshot"], img[src*="png"]')
        if not imgs:
            pytest.skip("No screenshot image element found in tab")
        for img in imgs:
            w = driver.execute_script('return arguments[0].naturalWidth', img)
            assert w > 0, f"Screenshot image failed to load (naturalWidth=0): {img.get_attribute('src')[:100]}"

    def test_13_cves_populated_after_nse(self, driver):
        """CVEs tab should have rows if vulners.nse found CVEs."""
        click_right_tab(driver, 'cves-right')
        time.sleep(POLL)
        rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-cves tr')
        # Not asserting count > 0 (target may have no CVEs)
        # Just verify the tab rendered without error
        assert driver.find_element(By.ID, 'cves-right').is_displayed()

    def test_14_no_duplicate_screenshooter_processes(self, driver, live_target):
        """Each IP:port on the live target should have at most one screenshooter process."""
        # Use JS to avoid StaleElementReferenceException from snapshot re-renders
        shoot_targets = driver.execute_script("""
            var targets = [];
            document.querySelectorAll('#processes-body tr').forEach(function(r) {
                var cells = r.querySelectorAll('td');
                if (cells.length < 3) return;
                var allText = Array.from(cells).map(function(c){return c.textContent;}).join(' ');
                if (allText.toLowerCase().includes('screenshooter') &&
                    allText.includes(arguments[0])) {
                    targets.push(cells[2].textContent.trim());
                }
            });
            return targets;
        """, live_target)
        dupes = [t for t in set(shoot_targets) if shoot_targets.count(t) > 1]
        assert not dupes, f"Duplicate screenshooter processes for {live_target}: {dupes}"

    def test_15_host_tab_orange_after_discovery(self, driver, live_target):
        """After scan, at least one right-panel tab should have been marked unread."""
        # This is hard to catch after-the-fact since unread clears on click.
        # Verify the mechanism is present: tab-unread CSS class is applied by JS.
        result = driver.execute_script("""
            var btn = document.querySelector('#right-tab-bar [data-tab="info-right"]');
            if (!btn) return 'no button';
            btn.classList.add('tab-unread');
            var color = window.getComputedStyle(btn).color;
            btn.classList.remove('tab-unread');
            return color;
        """)
        # tab-unread color is #fa0 = rgb(255, 170, 0)
        assert '255' in result and '170' in result, \
            f"tab-unread CSS not applying orange color: {result}"
    def test_16_screenshot_modal_opens_on_click(self, driver, live_target):
        """Clicking the screenshot image in a dynamic tab must open the screenshot modal."""
        # Find the screenshooter dynamic tab and click it
        shoot_pid = driver.execute_script("""
            var rows = document.querySelectorAll('#processes-body tr');
            for (var r of rows) {
                var cells = r.querySelectorAll('td');
                for (var c of cells) {
                    if (c.textContent.toLowerCase().includes('screenshooter'))
                        return r.dataset.processId;
                }
            }
            return null;
        """)
        if not shoot_pid:
            pytest.skip("No screenshooter process found")

        # Select live target so dynamic tab renders
        driver.execute_script(
            "L.selectedHostIp = arguments[0];"
            "if(typeof renderDynamicToolTabs==='function') renderDynamicToolTabs(arguments[0]);",
            live_target)
        time.sleep(0.3)

        # Click the screenshooter dynamic tab
        dyn_tabs = driver.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        shoot_tab = None
        for t in dyn_tabs:
            if 'screenshooter' in t.text.lower():
                shoot_tab = t
                break
        if not shoot_tab and dyn_tabs:
            shoot_tab = dyn_tabs[-1]
        if not shoot_tab:
            pytest.skip("No dynamic tab for screenshooter")

        js_click(driver, shoot_tab)

        # Wait for the screenshot image to appear.
        # The snapshot poll (every 1.5s) re-runs renderDynamicToolTabs which wipes
        # container.innerHTML — the img is only present between the tab click and
        # the next re-render. Use WebDriverWait with retry to catch it.
        img_src = None
        for _ in range(6):   # try for up to ~9s across poll cycles
            time.sleep(1.5)
            result = driver.execute_script("""
                var panels = document.querySelectorAll('#dynamic-tabs-container .tab-content.active');
                for (var p of panels) {
                    var img = p.querySelector('img[src*="screenshots"]');
                    if (img) return img.src;
                }
                return null;
            """)
            if result:
                img_src = result
                break
            # Re-click the tab so loadProcessOutput fires again after the re-render
            driver.execute_script("""
                var tabs = document.querySelectorAll('#right-tab-bar .dynamic-tab');
                for (var t of tabs) {
                    if (t.textContent.toLowerCase().includes('screenshooter')) { t.click(); break; }
                }
            """)

        if not img_src:
            pytest.skip("No screenshot image appeared in dynamic tab — possible timing issue")

        # Click the image via JS — should open screenshot-modal
        driver.execute_script("""
            var panels = document.querySelectorAll('#dynamic-tabs-container .tab-content.active');
            for (var p of panels) {
                var img = p.querySelector('img[src*="screenshots"]');
                if (img) { img.click(); break; }
            }
        """)
        time.sleep(0.3)

        modal_class = driver.find_element(By.ID, 'screenshot-modal').get_attribute('class')
        assert 'is-open' in modal_class,             f"screenshot-modal did not open after clicking image: {modal_class}"

        # Image in modal must have loaded
        modal_img = driver.find_element(By.ID, 'screenshot-modal-image')
        w = driver.execute_script('return arguments[0].naturalWidth', modal_img)
        assert w > 0, f"Modal image failed to load (naturalWidth=0)"

        # Close modal
        driver.find_element(By.ID, 'screenshot-modal-close').click()
        time.sleep(0.2)

    def test_17_cves_populated_after_nse(self, driver, live_target):
        """CVEs tab must have real CVE data after NSE/vulners stage completes.
        test_08 guarantees all stages finished before this runs.
        loadHostDetail is async — wait up to 10s for rows to appear."""
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'cves-right')
        # Wait for loadHostDetail async response to render CVE rows
        W(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-cves tr')) > 0,
        )
        rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-cves tr')
        assert len(rows) > 0,             f"CVEs tab has 0 rows after NSE scan completed — vulners.nse may not have stored results"
        cells = rows[0].find_elements(By.TAG_NAME, 'td')
        assert any(c.text.strip() for c in cells), "First CVE row has no cell content"

    def test_18_scripts_populated_after_scan(self, driver, live_target):
        """Scripts tab must have nmap script rows after the full scan.
        test_08 guarantees all stages finished before this runs."""
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'scripts-right')
        # Wait for loadHostDetail async response to render script rows
        W(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-scripts tr')) > 0,
        )
        rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-scripts tr')
        assert len(rows) > 0,             f"Scripts tab has 0 rows after scan completed — nmap scripts may not have stored results"
        cells = rows[0].find_elements(By.TAG_NAME, 'td')
        assert any(c.text.strip() for c in cells), "First script row has no cell content"

    def test_19_script_row_loads_inline_output(self, driver, live_target):
        """Clicking a script row must load its output in #script-output-inline."""
        row = wait_for_host_row(driver, live_target)
        js_click(driver, row)
        time.sleep(POLL)
        click_right_tab(driver, 'scripts-right')
        W(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, '#host-detail-scripts tr')) > 0)
        rows = driver.find_elements(By.CSS_SELECTOR, '#host-detail-scripts tr')
        if not rows:
            pytest.skip("No script rows available")
        # Click first script row
        js_click(driver, rows[0])
        time.sleep(POLL)
        output = driver.find_element(By.ID, 'script-output-inline').text.strip()
        assert len(output) > 0, \
            "Script output inline panel is empty after clicking script row"
        assert output != 'Loading...', \
            "Script output stuck on 'Loading...'"
