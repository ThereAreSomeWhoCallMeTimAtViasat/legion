#!/usr/bin/env python3
"""
US-32 Test Report — CVEs Tab Lists Vulnerabilities Sorted by CVSS Score
========================================================================
Usage:
    sudo python3 tests/generate_report_US32.py [--port 5095]

Verifies US-32: the CVEs tab for a host lists CVE entries with their CVSS
scores sorted highest-to-lowest.

Implementation:
  /api/workspace/hosts/{id}/cves-list → cves array →
  renderCves(cves) in legion.js →
  sorted = cves.slice().sort() with _cvesSort = {col:'severity', dir:-1} →
  highest severity rendered first.

Test strategy:
  Inject 5 CVEs with known CVSS scores (out of insertion order) via the
  POST /api/workspace/hosts/{id}/cves API. Then load the CVEs tab in Selenium
  and verify the displayed rows are in descending CVSS order.

  This tests the REAL sorting mechanism without requiring a 5-minute vulners
  NSE scan. The CVE injection endpoint is the same one used by the vulners
  importer — it is the real production code path.

Three scenarios:
  1. Inject 5 CVEs in shuffled order; verify all 5 appear in the CVEs tab.
  2. Verify CVSS scores are displayed in descending order.
  3. Click a different host; click back — verify CVEs still sorted (persistence).
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
from selenium.webdriver.support import expected_conditions as EC

import tests.generate_report as R

# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5095)
args  = parser.parse_args()
R.configure(args.port)
BASE  = R.base_url()

HOST_IP  = '10.10.10.1'
HOST2_IP = '10.10.10.2'   # second host for the navigation test

SEED_XML = """\
<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="80">
      <state state="open"/><service name="http"/></port></ports>
  </host>
  <host><status state="up"/>
    <address addr="10.10.10.2" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22">
      <state state="open"/><service name="ssh"/></port></ports>
  </host>
</nmaprun>"""

# CVEs injected in shuffled order — not sorted by severity
CVES_TO_INJECT = [
    {'name': 'CVE-2017-0144', 'severity': '9.3', 'product': 'Windows SMB'},
    {'name': 'CVE-2014-0160', 'severity': '5.0', 'product': 'OpenSSL'},
    {'name': 'CVE-2021-3156',  'severity': '7.8', 'product': 'sudo'},
    {'name': 'CVE-2022-0001',  'severity': '9.8', 'product': 'kernel'},
    {'name': 'CVE-2019-0708',  'severity': '9.8', 'product': 'RDP BlueKeep'},
]
EXPECTED_ORDER = sorted(
    [float(c['severity']) for c in CVES_TO_INJECT],
    reverse=True)   # [9.8, 9.8, 9.3, 7.8, 5.0]


def seed_hosts():
    snap = requests.get(f'{BASE}/api/snapshot').json()
    existing = {h['ip'] for h in snap.get('hosts', [])}
    if HOST_IP in existing and HOST2_IP in existing:
        return
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML); path = f.name
    requests.post(f'{BASE}/api/nmap/import-xml', json={'path': path})
    time.sleep(1.5)
    os.unlink(path)


def get_host_id(ip):
    snap = requests.get(f'{BASE}/api/snapshot').json()
    for h in snap.get('hosts', []):
        if h['ip'] == ip:
            return h['id']
    return None


def inject_cves(host_id):
    """POST each CVE to /api/workspace/hosts/{id}/cves."""
    for cve in CVES_TO_INJECT:
        requests.post(f'{BASE}/api/workspace/hosts/{host_id}/cves',
                      json={'name': cve['name'],
                            'severity': cve['severity'],
                            'product': cve['product'],
                            'url': ''})
    time.sleep(0.5)


def select_host(driver, ip):
    driver.execute_script(f"""
        var row = document.querySelector('#hosts-body tr[data-host-ip="{ip}"]');
        if (row) row.click();
    """)
    time.sleep(1.0)


def open_cves_tab(driver):
    driver.execute_script("""
        var btn = document.querySelector('#right-tab-bar [data-tab="cves-right"]');
        if (btn) btn.click();
    """)
    time.sleep(0.8)


def get_cves_from_dom(driver):
    """Return list of CVE severities as floats from the DOM table."""
    return driver.execute_script("""
        var rows = document.querySelectorAll('#host-detail-cves tr');
        var severities = [];
        for (var i = 0; i < rows.length; i++) {
            var cells = rows[i].querySelectorAll('td');
            if (cells.length >= 2) {
                var sev = cells[1].textContent.trim();  /* severity is 2nd column */
                if (sev) severities.push(parseFloat(sev) || 0);
            }
        }
        return severities;
    """) or []


# ---------------------------------------------------------------------------
# Scenario 1 — Inject CVEs and verify all appear in the CVEs tab
# ---------------------------------------------------------------------------
def run_cves_appear(driver):
    name = 'Test 1 — 5 injected CVEs appear in the CVEs tab'
    print(f'\n  {name}')

    seed_hosts()
    host_id = get_host_id(HOST_IP)
    assert host_id, f'Host {HOST_IP} not in snapshot'

    # Clear any existing CVEs for this host by checking the API
    inject_cves(host_id)

    R.record(driver, name, 1,
             f'Injected {len(CVES_TO_INJECT)} CVEs for host {HOST_IP} '
             f'via POST /api/workspace/hosts/{host_id}/cves. '
             f'Severities (shuffled): '
             f'{[c["severity"] for c in CVES_TO_INJECT]}. '
             f'The same endpoint is used by the vulners NSE importer.',
             True, '#hosts-body')

    select_host(driver, HOST_IP)
    open_cves_tab(driver)

    # Wait for CVE rows to appear
    deadline = time.time() + 10
    cve_count = 0
    while time.time() < deadline:
        cve_count = driver.execute_script(
            "return document.querySelectorAll('#host-detail-cves tr').length")
        if cve_count >= len(CVES_TO_INJECT):
            break
        time.sleep(0.5)

    ok = cve_count >= len(CVES_TO_INJECT)
    R.record(driver, name, 2,
             f'CVEs tab row count: {cve_count} (need ≥{len(CVES_TO_INJECT)}). '
             f'renderCves() called by loadHostDetail → fetches /api/workspace/hosts/{host_id}/cves-list.',
             ok,
             '#host-detail-cves')

    R.finish_test(name, ok)
    return ok


# ---------------------------------------------------------------------------
# Scenario 2 — CVEs are sorted by CVSS score descending
# ---------------------------------------------------------------------------
def run_cves_sorted(driver):
    name = 'Test 2 — CVEs displayed in descending CVSS score order'
    print(f'\n  {name}')

    severities = get_cves_from_dom(driver)

    # The DB may have accumulated CVEs from prior runs (inject_cves is additive).
    # We verify sort ORDER rather than exact list to be robust to duplicates.
    # A sorted list equals its own sorted-descending version — O(n log n) check.
    is_sorted_desc = severities == sorted(severities, reverse=True)
    has_our_cves   = len(severities) >= len(EXPECTED_ORDER)  # at least what we injected

    ok = is_sorted_desc and has_our_cves
    R.record(driver, name, 1,
             f'CVE severity values from DOM: {severities}. '
             f'Expected ≥{len(EXPECTED_ORDER)} rows in descending order. '
             f'is_sorted_desc={is_sorted_desc}, has_our_cves={has_our_cves}. '
             f'JS: _cvesSort = {{col:"severity", dir:-1}}. '
             f'Note: accumulated CVEs from prior runs are OK — only order matters.',
             ok,
             '#host-detail-cves')

    R.finish_test(name, ok)
    return ok


# ---------------------------------------------------------------------------
# Scenario 3 — Navigate away and back; CVEs still sorted
# ---------------------------------------------------------------------------
def run_cves_persist_after_navigation(driver):
    name = 'Test 3 — Navigate to host 2 and back; CVEs for host 1 still sorted'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'About to click host {HOST2_IP} (different host, no CVEs). '
             f'Then click back to {HOST_IP}. '
             f'loadHostDetail re-fetches CVEs from server each time — '
             f'sorted by renderCves() on each load.',
             True, '#hosts-body')

    # Click the second host
    select_host(driver, HOST2_IP)
    time.sleep(0.5)

    # Click back to the first host
    select_host(driver, HOST_IP)
    open_cves_tab(driver)

    deadline = time.time() + 8
    cve_count = 0
    while time.time() < deadline:
        cve_count = driver.execute_script(
            "return document.querySelectorAll('#host-detail-cves tr').length")
        if cve_count >= len(CVES_TO_INJECT):
            break
        time.sleep(0.5)

    severities = get_cves_from_dom(driver)
    is_sorted_desc = severities == sorted(severities, reverse=True)
    has_our_cves   = len(severities) >= len(EXPECTED_ORDER)
    ok = is_sorted_desc and has_our_cves

    R.record(driver, name, 2,
             f'After navigation: {cve_count} CVE rows, '
             f'severities={severities}. '
             f'is_sorted_desc={is_sorted_desc}, has_our_cves={has_our_cves}. '
             f'Sort survives host navigation round-trip.',
             ok,
             '#host-detail-cves')

    R.finish_test(name, ok)
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-32 Report Generator')
print(f'Server : {BASE}')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable: {e}'); sys.exit(1)

driver = R.make_driver()
driver.get(BASE)
time.sleep(2)

try:
    ok1 = run_cves_appear(driver)
    ok2 = run_cves_sorted(driver)          if ok1 else False
    ok3 = run_cves_persist_after_navigation(driver) if ok1 else False
    all_passed = ok1 and ok2 and ok3
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='CVEs Tab — Sorted by CVSS Score Descending',
    us_id='US-32',
    description=(
        '5 CVEs injected in shuffled severity order via POST /api/workspace/hosts/{id}/cves '
        '(same endpoint used by vulners NSE importer). '
        'renderCves() in legion.js sorts with _cvesSort={col:"severity",dir:-1} '
        'so highest CVSS score appears first. '
        'Verified: (1) all CVEs appear, (2) sorted descending, '
        '(3) sort survives host navigation round-trip.'
    ),
)
sys.exit(0 if all_passed else 1)
