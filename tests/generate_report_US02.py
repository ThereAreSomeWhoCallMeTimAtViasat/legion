#!/usr/bin/env python3
"""
US-02 Test Report — Semicolons Create Parallel Scan Processes
=============================================================
Usage:
    sudo python3 tests/generate_report_US02.py [--port 5085]
"""
import argparse
import os
import sys
import time
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

import tests.generate_report as R

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5085)
args = parser.parse_args()
R.configure(args.port)
BASE = R.base_url()

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
    </ports>
  </host>
</nmaprun>"""


def seed_server():
    snap = requests.get(f'{BASE}/api/snapshot').json()
    if any(h['ip'] == '10.10.10.1' for h in snap.get('hosts', [])):
        return
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML); path = f.name
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
# Scenario 1 — semicolon creates two processes, one per host
# ---------------------------------------------------------------------------
def run_semicolon_parallel(driver):
    name   = 'Test 1 — Semicolons create two independent parallel scan processes'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)
    R.record(driver, name, 1,
             f'Navigate to Legion at {BASE}. Hosts table and processes table visible.',
             True, '#hosts-table, #hosts-body')

    snap_before  = api('get', '/api/snapshot').json()
    procs_before = {p['id'] for p in snap_before.get('processes', [])}
    R.record(driver, name, 2,
             f'Baseline: {len(procs_before)} existing process(es). IDs recorded so '
             f'we can identify ONLY the new ones after submission.',
             True, '#processes-table, #processes-body')

    open_modal(driver)
    time.sleep(0.3)
    R.record(driver, name, 3,
             'Add Hosts modal opened.',
             True, '#add-hosts-modal')

    ta = driver.find_element(By.ID, 'add-hosts-targets')
    ta.clear()
    ta.send_keys('127.0.0.1; 127.0.0.2')
    time.sleep(0.2)
    R.record(driver, name, 4,
             'Typed "127.0.0.1; 127.0.0.2" — semicolon separates two hosts. '
             'routes.py splits on [\\n;]+ so each token becomes an independent '
             'call to wc.addHosts() → runStagedNmap().',
             True, '#add-hosts-targets')

    driver.find_element(By.ID, 'add-hosts-start').click()
    R.record(driver, name, 5,
             'Clicked Start — two staged nmap scans launch in parallel.',
             True, '#add-hosts-start')

    time.sleep(5.0)
    snap_after = api('get', '/api/snapshot').json()
    new_procs  = [p for p in snap_after.get('processes', [])
                  if p['id'] not in procs_before]
    host_ips   = {p.get('hostIp', '') for p in new_procs}

    ok_count = len(new_procs) >= 2
    ok_101   = '127.0.0.1' in host_ips
    ok_102   = '127.0.0.2' in host_ips
    ok_all   = ok_count and ok_101 and ok_102
    passed   = ok_all

    R.record(driver, name, 6,
             f'After 5 s: {len(new_procs)} new process(es) found. '
             f'Host IPs: {sorted(host_ips)}. '
             f'Need ≥2 processes with both 127.0.0.1 and 127.0.0.2. '
             f'count≥2={ok_count} | .1 present={ok_101} | .2 present={ok_102}.',
             ok_all, '#processes-table, #processes-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 2 — server accepts semicolon targets (not 400)
# ---------------------------------------------------------------------------
def run_server_accepts(driver):
    name   = 'Test 2 — Server returns HTTP 200 for semicolon-separated targets'
    passed = True
    print(f'\n  {name}')

    R.record(driver, name, 1,
             'Calling POST /api/nmap/scan directly with targets="127.0.0.1; 127.0.0.2". '
             'Confirms the server-side split is on [\\n;]+ and both tokens pass '
             'validateNmapInput([a-zA-Z0-9:./-\\s,]).',
             True)

    resp = api('post', '/api/nmap/scan', json={
        'targets': '127.0.0.1; 127.0.0.2',
        'scan_mode': 'Easy',
        'discovery': True,
        'staged': True,
        'timing': '4',
        'nmap_options': ['-n'],
        'enable_ipv6': False,
    })
    data     = resp.json()
    ok_http  = resp.status_code == 200
    ok_noerr = data.get('status') != 'error'
    passed   = ok_http and ok_noerr

    time.sleep(2)
    R.record(driver, name, 2,
             f'API response: HTTP {resp.status_code}, status={data.get("status")!r}. '
             f'Must be 200 and status != "error". '
             f'http200={ok_http} | no_error={ok_noerr}.',
             passed, '#processes-table, #processes-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 3 — newline works the same way as semicolon
# ---------------------------------------------------------------------------
def run_newline_parallel(driver):
    name   = 'Test 3 — Newline separator also creates two processes (equivalent to semicolon)'
    passed = True
    print(f'\n  {name}')

    snap_before  = api('get', '/api/snapshot').json()
    procs_before = {p['id'] for p in snap_before.get('processes', [])}
    R.record(driver, name, 1,
             f'Baseline: {len(procs_before)} existing process(es). '
             f'Will submit two hosts separated by a newline character.',
             True, '#processes-table, #processes-body')

    open_modal(driver)
    ta = driver.find_element(By.ID, 'add-hosts-targets')
    ta.clear()
    # Newline key press inserts literal newline in the textarea
    from selenium.webdriver.common.keys import Keys
    ta.send_keys('127.0.0.5')
    ta.send_keys(Keys.RETURN)
    ta.send_keys('127.0.0.6')
    time.sleep(0.2)
    R.record(driver, name, 2,
             'Typed "127.0.0.5\\n127.0.0.6" (Enter key between hosts). '
             'The split regex [\\n;]+ treats newlines identically to semicolons.',
             True, '#add-hosts-targets')

    driver.find_element(By.ID, 'add-hosts-start').click()
    R.record(driver, name, 3,
             'Clicked Start — two scans should launch, one for each line.',
             True)

    time.sleep(5.0)
    snap_after = api('get', '/api/snapshot').json()
    new_procs  = [p for p in snap_after.get('processes', [])
                  if p['id'] not in procs_before]
    host_ips   = {p.get('hostIp', '') for p in new_procs}

    ok_count = len(new_procs) >= 2
    ok_105   = '127.0.0.5' in host_ips
    ok_106   = '127.0.0.6' in host_ips
    ok_all   = ok_count and ok_105 and ok_106
    passed   = ok_all

    R.record(driver, name, 4,
             f'{len(new_procs)} new process(es). Host IPs: {sorted(host_ips)}. '
             f'Need ≥2 with both .5 and .6. '
             f'count≥2={ok_count} | .5={ok_105} | .6={ok_106}.',
             ok_all, '#processes-table, #processes-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-02 Report Generator')
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
    all_passed  = run_semicolon_parallel(driver) and all_passed
    all_passed  = run_server_accepts(driver)     and all_passed
    all_passed  = run_newline_parallel(driver)   and all_passed
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Semicolons Create Parallel Scan Processes',
    us_id='US-02',
    description=(
        'Semicolons (and newlines) separate multiple hosts in the Add Hosts dialog. '
        'Each token becomes an independent parallel nmap scan process. '
        'The split uses [\\n;]+ in routes.py; each part is validated by '
        'validateNmapInput separately before any scan is launched.'
    ),
)
sys.exit(0 if all_passed else 1)
