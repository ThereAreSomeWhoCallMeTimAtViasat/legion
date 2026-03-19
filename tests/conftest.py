"""
pytest fixtures shared by Selenium UI tests.

Usage:
    sudo python3 -m pytest tests/test_selenium_ui.py -v
    LEGION_TEST_TARGET=192.168.1.100 sudo python3 -m pytest tests/test_selenium_ui.py -v -m live
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

SELENIUM_PORT = 5099   # separate from prod port 5000
BASE_URL = f"http://127.0.0.1:{SELENIUM_PORT}"

# ── Seed XML: one host with HTTP + SSH so offline tests have data ──────────
_SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <hostnames><hostname name="testhost.local" type="PTR"/></hostnames>
    <os><osmatch name="Linux 4.x" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.4"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4.51"/>
      </port>
      <port protocol="tcp" portid="443">
        <state state="open"/>
        <service name="https" product="Apache" version="2.4.51"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


@pytest.fixture(scope="session")
def legion_server():
    """Start Legion Flask on SELENIUM_PORT with seeded test data."""
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from app.auxiliary import Filters

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False   # real WSGI server, not test client

    # Seed one host so the UI has data on first load
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED_XML)
        seed_path = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=seed_path, output="")
    os.unlink(seed_path)

    t = threading.Thread(
        target=app.run,
        kwargs={'host': '127.0.0.1', 'port': SELENIUM_PORT,
                'use_reloader': False, 'threaded': True},
        daemon=True
    )
    t.start()
    time.sleep(2)   # wait for Werkzeug to bind

    yield {'app': app, 'logic': logic, 'wc': wc, 'url': BASE_URL}


@pytest.fixture(scope="session")
def driver(legion_server):
    """Headless Firefox driver, session-scoped so all tests share state."""
    import os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service

    # Firefox refuses to start as root when XAUTHORITY is owned by another user.
    # Headless mode doesn't need a display — unset both vars before starting.
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)

    opts = webdriver.FirefoxOptions()
    opts.add_argument("--headless")

    # Specify geckodriver path directly — Selenium Manager fails on system packages
    svc = Service(executable_path='/usr/bin/geckodriver')
    d = webdriver.Firefox(service=svc, options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)   # use explicit WebDriverWait everywhere
    d.get(legion_server['url'])
    time.sleep(1.5)   # let initial snapshot poll render
    yield d
    d.quit()


@pytest.fixture(scope="session")
def live_target():
    """IP of the live test VM. Skip live tests when not set."""
    target = os.environ.get('LEGION_TEST_TARGET', '').strip()
    if not target:
        pytest.skip("Set LEGION_TEST_TARGET=<ip> to run live scan tests")
    return target


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires LEGION_TEST_TARGET env var")


@pytest.fixture(autouse=True, scope='class')
def reset_ui_state(driver):
    """Restore UI to a known baseline before every test class.

    Prevents state-leak between classes (open modals, wrong tab active,
    context menus left open, scroll position).
    """
    import time as _t
    try:
        from selenium.webdriver.common.by import By as _By

        # Dismiss context menu or stray overlays
        driver.find_element(_By.TAG_NAME, 'body').click()
        _t.sleep(0.1)

        # Close any open modals
        for mid in ['add-hosts-modal', 'import-nmap-modal', 'config-modal',
                    'help-modal', 'filters-modal', 'add-port-modal']:
            try:
                el = driver.find_element(_By.ID, mid)
                if 'is-open' in (el.get_attribute('class') or ''):
                    driver.find_element(
                        _By.CSS_SELECTOR, f'#{mid} .modal-close-btn').click()
                    _t.sleep(0.15)
            except Exception:
                pass

        # Switch to Scan main tab
        try:
            scan_btn = driver.find_element(
                _By.CSS_SELECTOR, '#main-tab-bar [data-tab="scan-tab"]')
            if 'active' not in (scan_btn.get_attribute('class') or ''):
                scan_btn.click()
        except Exception:
            pass

        # Switch to Hosts left panel
        try:
            hosts_btn = driver.find_element(
                _By.CSS_SELECTOR, '#left-tab-bar [data-tab="hosts-panel"]')
            if 'active' not in (hosts_btn.get_attribute('class') or ''):
                hosts_btn.click()
        except Exception:
            pass

        # Dismiss any stray browser alert (config modal can trigger async alerts)
        try:
            driver.switch_to.alert.dismiss()
        except Exception:
            pass

        # Scroll top of page
        driver.execute_script("window.scrollTo(0, 0)")
    except Exception:
        pass   # never block a test due to reset failure

    yield   # run the tests in this class
