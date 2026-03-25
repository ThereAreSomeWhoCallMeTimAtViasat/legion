#!/usr/bin/env python3
"""
US-03 Test Report — Comma Range Syntax
=======================================
Usage:
    sudo python3 tests/generate_report_US03.py [--port 5085]

Runs 3 scenarios for US-03 against the live server, captures a screenshot
at every key step, and writes a dated HTML report to testreport/.
"""
import argparse
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import tests.generate_report as R

# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5085)
args = parser.parse_args()
R.configure(args.port)
BASE = R.base_url()

# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------
SEED_XML = """\
<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.4"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4.51"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


def seed_server():
    import tempfile
    snap = requests.get(f'{BASE}/api/snapshot').json()
    if any(h['ip'] == '10.10.10.1' for h in snap.get('hosts', [])):
        return
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML)
        path = f.name
    requests.post(f'{BASE}/api/nmap/import-xml', json={'path': path})
    time.sleep(1)
    os.unlink(path)


def api(method, path, **kw):
    return getattr(requests, method)(BASE + path, **kw)


def open_modal(driver):
    driver.execute_script("document.getElementById('action-add-hosts').click()")
    WebDriverWait(driver, 5).until(
        lambda d: 'is-open' in (
            d.find_element(By.ID, 'add-hosts-modal').get_attribute('class') or ''))
    return driver.find_element(By.ID, 'add-hosts-targets')


def close_modal(driver):
    try:
        driver.find_element(By.CSS_SELECTOR,
                            '#add-hosts-modal .modal-close-btn').click()
        time.sleep(0.3)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Scenario 1 — validation element stays hidden for comma range
# ---------------------------------------------------------------------------
def run_validation_test(driver):
    name   = 'Test 1 — Comma range passes JS validation (no error shown)'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)
    R.record(driver, name, 1,
             f'Navigate to Legion at {BASE}. Host 10.10.10.1 visible in the hosts table.',
             True, '#hosts-table, #hosts-body, #hosts-panel')

    open_modal(driver)
    time.sleep(0.3)
    R.record(driver, name, 2,
             'Add Hosts modal opened via JS click on hidden #action-add-hosts button.',
             True, '#add-hosts-modal')

    ta = driver.find_element(By.ID, 'add-hosts-targets')
    ta.clear()
    ta.send_keys('192.168.1.1,2')
    time.sleep(0.2)
    R.record(driver, name, 3,
             'Typed "192.168.1.1,2" — valid nmap comma-range syntax expanding to '
             '.1 and .2. validateNmapInput allows [a-zA-Z0-9:./-\\s,] so comma passes.',
             True, '#add-hosts-targets')

    driver.find_element(By.ID, 'add-hosts-start').click()
    time.sleep(0.6)

    val     = driver.find_element(By.ID, 'add-hosts-validation')
    ok_val  = not val.is_displayed()
    passed  = passed and ok_val
    R.record(driver, name, 4,
             '#add-hosts-validation must be hidden (display:none) — the JS guard '
             'only fires for EMPTY input; comma-range is non-empty so it passes JS '
             'validation and is sent to the server.',
             ok_val, '#add-hosts-validation')

    close_modal(driver)
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 2 — process created after submitting comma range
# ---------------------------------------------------------------------------
def run_process_created_test(driver):
    name   = 'Test 2 — Comma range submission creates a scan process'
    passed = True
    print(f'\n  {name}')

    proc_before = len(api('get', '/api/snapshot').json().get('processes', []))
    R.record(driver, name, 1,
             f'Baseline: {proc_before} process(es) in the DB before submitting '
             f'"192.168.1.1,2". Process table visible.',
             True, '#processes-table, #processes-body')

    open_modal(driver)
    ta = driver.find_element(By.ID, 'add-hosts-targets')
    ta.clear()
    ta.send_keys('192.168.1.1,2')
    time.sleep(0.2)
    R.record(driver, name, 2,
             'Typed "192.168.1.1,2" into the targets textarea.',
             True, '#add-hosts-targets')

    driver.find_element(By.ID, 'add-hosts-start').click()
    R.record(driver, name, 3,
             'Clicked Start — postJson fires to /api/nmap/scan with targets="192.168.1.1,2". '
             'Server splits on [\\n;]+ (not comma), so the whole token reaches nmap.',
             True, '#add-hosts-start')

    # Wait for server round-trip + modal auto-close (1.5 s) + snapshot poll
    time.sleep(4.5)
    proc_after = len(api('get', '/api/snapshot').json().get('processes', []))
    ok_proc    = proc_after > proc_before
    passed     = passed and ok_proc
    R.record(driver, name, 4,
             f'Process count after: {proc_after} (was {proc_before}). '
             f'At least one new nmap process must appear — the server accepted '
             f'the comma-range target and launched a scan.',
             ok_proc, '#processes-table, #processes-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 3 — direct API call returns 200 not 400
# ---------------------------------------------------------------------------
def run_api_accept_test(driver):
    name   = 'Test 3 — Direct API call: server returns 200 for comma range'
    passed = True
    print(f'\n  {name}')

    R.record(driver, name, 1,
             'About to call POST /api/nmap/scan with targets="192.168.1.1,2" directly. '
             'This isolates the server validation from the browser UI.',
             True)

    resp = api('post', '/api/nmap/scan', json={
        'targets': '192.168.1.1,2',
        'scan_mode': 'Easy',
        'discovery': True,
        'staged': True,
        'timing': '4',
        'nmap_options': ['-n'],
        'enable_ipv6': False,
    })
    data        = resp.json()
    ok_status   = resp.status_code == 200
    ok_no_error = data.get('status') != 'error'
    ok_both     = ok_status and ok_no_error
    passed      = ok_both

    # Navigate to processes tab to show the result
    time.sleep(2)
    R.record(driver, name, 2,
             f'API response: HTTP {resp.status_code}, status={data.get("status")!r}. '
             f'Must be 200 and not "error". '
             f'validateNmapInput passes comma because it is in [a-zA-Z0-9:./-\\s,].',
             ok_both, '#processes-table, #processes-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-03 Report Generator')
print(f'Server : {BASE}')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable: {e}'); sys.exit(1)

seed_server()
print('✓ Seed host present')

driver = R.make_driver()
try:
    all_passed  = True
    all_passed  = run_validation_test(driver)    and all_passed
    all_passed  = run_process_created_test(driver) and all_passed
    all_passed  = run_api_accept_test(driver)    and all_passed
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Comma Range Syntax Accepted',
    us_id='US-03',
    description=(
        'nmap comma-range syntax (192.168.1.1,2) must pass JS validation, '
        'be accepted by the server (HTTP 200), and result in a scan process. '
        'Comma is in the allowed character set [a-zA-Z0-9:./-\\s,]; '
        'the split uses [\\n;]+ so the comma is not treated as a separator.'
    ),
)
sys.exit(0 if all_passed else 1)
