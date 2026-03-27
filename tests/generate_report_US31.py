#!/usr/bin/env python3
"""
US-31 Test Report — Process Row and Dynamic Tab Get Match CSS Classes
=====================================================================
Usage:
    sudo python3 tests/generate_report_US31.py [--port 5095]

Verifies US-31 (corrected): when a process output line matches a global-positive
keyword, the UI reflects this in two ways:
  1. The process row in #processes-body gets CSS class 'proc-match' (yellow star ★
     appears in the Name cell, row styled via .proc-match).
  2. The dynamic tab button for that process in #right-tab-bar gets CSS class
     'tab-match' (tab is rendered with match styling).

Both classes are applied by legion.js when the snapshot returns has_match=true:
  JS line 716: if (p.has_match) tr.classList.add('proc-match');
  JS line 1177: btn.className = 'tab-btn dynamic-tab' + (proc.has_match ? ' tab-match' : '');

Matching command used: printf "SUCCEED" on port 3001 (unique key isolation).
Non-matching command: printf "no keywords here" on port 3002 (control test).

Three scenarios:
  1. Matching process: proc-match class PRESENT on row and tab-match on dyn tab.
  2. Non-matching process: proc-match class ABSENT; dyn tab has no tab-match.
  3. Star icon ★ visible in matching row Name cell (match indicator in DOM).
"""

import argparse
import os
import sys
import time
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import requests

import tests.generate_report as R

# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5095)
args  = parser.parse_args()
R.configure(args.port)
BASE  = R.base_url()

HOST_IP = '10.10.10.1'
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
    if any(h['ip'] == HOST_IP for h in snap.get('hosts', [])):
        return
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML); path = f.name
    requests.post(f'{BASE}/api/nmap/import-xml', json={'path': path})
    time.sleep(1.5)
    os.unlink(path)


def run_custom(cmd, port):
    r = requests.post(f'{BASE}/api/processes/custom', json={
        'command': cmd, 'host_ip': HOST_IP,
        'port': str(port), 'protocol': 'tcp',
    })
    d = r.json()
    assert d.get('status') == 'ok', f'custom command failed: {d}'
    return d['process_id']


def wait_finished(pid, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in requests.get(f'{BASE}/api/snapshot').json().get('processes', []):
            if str(p.get('id')) == str(pid):
                if p.get('status') in ('Finished', 'Crashed'):
                    return p.get('has_match', False), p.get('status')
        time.sleep(0.5)
    return False, 'Timeout'


def select_host(driver):
    driver.execute_script(f"""
        var row = document.querySelector('#hosts-body tr[data-host-ip="{HOST_IP}"]');
        if (row) row.click();
    """)
    time.sleep(1.2)


def wait_dom_finished(driver, pid, timeout=12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = driver.execute_script(f"""
            var row = document.querySelector(
                '#processes-body tr[data-process-id="{pid}"]');
            if (!row) return null;
            var cells = row.querySelectorAll('td');
            return cells.length >= 5 ? cells[4].textContent.trim() : null;
        """)
        if status in ('Finished', 'Crashed'):
            return status
        time.sleep(0.5)
    return None


# ---------------------------------------------------------------------------
# Scenario 1 — Matching process: proc-match + tab-match present
# ---------------------------------------------------------------------------
def run_matching_process(driver):
    name = 'Test 1 — Matching process: proc-match on row AND tab-match on dynamic tab'
    print(f'\n  {name}')

    select_host(driver)

    R.record(driver, name, 1,
             f'Host {HOST_IP} selected. Running printf "SUCCEED" on port 3001. '
             f'"SUCCEED" is in global-positive → has_match will be True. '
             f'Expects: proc-match CSS on the process row AND tab-match CSS on '
             f'the dynamic tab button in #right-tab-bar.',
             True, '#hosts-body')

    pid = run_custom('printf "SUCCEED"', port=3001)

    # Wait for Finished in DOM
    wait_dom_finished(driver, pid)
    has_match, status = wait_finished(pid)
    time.sleep(3.5)   # ensure renderDynamicToolTabs fires with updated has_match

    # Check process row class
    row_has_match = driver.execute_script(f"""
        var row = document.querySelector(
            '#processes-body tr[data-process-id="{pid}"]');
        if (!row) return {{found: false, procMatch: null, starText: null}};
        return {{
            found:     true,
            procMatch: row.classList.contains('proc-match'),
            starText:  row.querySelector('td:first-child') ?
                       row.querySelector('td:first-child').textContent : null
        }};
    """)

    ok_row = row_has_match.get('proc-match') or row_has_match.get('procMatch')

    R.record(driver, name, 2,
             f'Process {pid}: status={status}, has_match={has_match}. '
             f'Row found={row_has_match.get("found")}, '
             f'proc-match class={row_has_match.get("procMatch")}, '
             f'Name cell text={row_has_match.get("starText","")!r}. '
             f'CSS class proc-match must be present.',
             ok_row is True,
             f'#processes-body tr[data-process-id="{pid}"]')

    # Check dynamic tab button class
    tab_has_match = driver.execute_script(f"""
        var btn = document.querySelector(
            '#right-tab-bar [data-tab="dyntab-{pid}"]');
        if (!btn) return {{found: false, tabMatch: null}};
        return {{found: true, tabMatch: btn.classList.contains('tab-match')}};
    """)

    ok_tab = tab_has_match.get('tabMatch') is True

    R.record(driver, name, 3,
             f'Dynamic tab button [data-tab="dyntab-{pid}"]: '
             f'found={tab_has_match.get("found")}, '
             f'tab-match class={tab_has_match.get("tabMatch")}. '
             f'CSS class tab-match must be present when has_match=True.',
             ok_tab,
             f'#right-tab-bar [data-tab="dyntab-{pid}"]')

    passed = (ok_row is True) and ok_tab
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 2 — Non-matching process: neither class present
# ---------------------------------------------------------------------------
def run_non_matching_process(driver):
    name = 'Test 2 — Non-matching process: proc-match ABSENT, tab-match ABSENT'
    print(f'\n  {name}')

    select_host(driver)

    R.record(driver, name, 1,
             f'Running printf "no keywords here" on port 3002. '
             f'Output contains no global-positive keywords → has_match=False. '
             f'Expects: NO proc-match class on row, NO tab-match on dynamic tab.',
             True, '#hosts-body')

    pid = run_custom('printf "no keywords here"', port=3002)

    wait_dom_finished(driver, pid)
    has_match, status = wait_finished(pid)
    time.sleep(2.0)

    row_info = driver.execute_script(f"""
        var row = document.querySelector(
            '#processes-body tr[data-process-id="{pid}"]');
        if (!row) return {{found: false, procMatch: null}};
        return {{found: true, procMatch: row.classList.contains('proc-match')}};
    """)

    tab_info = driver.execute_script(f"""
        var btn = document.querySelector(
            '#right-tab-bar [data-tab="dyntab-{pid}"]');
        if (!btn) return {{found: false, tabMatch: null}};
        return {{found: true, tabMatch: btn.classList.contains('tab-match')}};
    """)

    ok_row_absent = row_info.get('procMatch') is False
    ok_tab_absent = tab_info.get('tabMatch') is False

    R.record(driver, name, 2,
             f'Process {pid}: status={status}, has_match={has_match}. '
             f'proc-match class={row_info.get("procMatch")} (must be False). '
             f'tab-match class={tab_info.get("tabMatch")} (must be False).',
             ok_row_absent and ok_tab_absent,
             f'#processes-body tr[data-process-id="{pid}"]')

    passed = ok_row_absent and ok_tab_absent
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 3 — Star icon ★ visible in matching row Name cell
# ---------------------------------------------------------------------------
def run_star_indicator(driver):
    name = 'Test 3 — Match star ★ visible in Name cell of matching process row'
    print(f'\n  {name}')

    # Reuse the match pid from test 1 (port 3001) — it should still be visible
    # Find the row with proc-match class and verify the ★ star icon
    select_host(driver)
    time.sleep(1.0)

    star_info = driver.execute_script("""
        var rows = document.querySelectorAll('#processes-body tr.proc-match');
        if (!rows.length) return {count: 0, hasstar: false, nameText: null};
        var row = rows[0];
        /* Column order: ID | Name | Target | PID | Status | % | Elapsed
           matchIcon is injected into td:nth-child(2) (the Name column). */
        var nameCell = row.querySelector('td:nth-child(2)');
        var text = nameCell ? nameCell.textContent.trim() : '';
        var innerHTML = nameCell ? nameCell.innerHTML : '';
        return {
            count:    rows.length,
            hasstar:  innerHTML.indexOf('\u2605') >= 0,
            nameText: text.substring(0, 80)
        };
    """)

    ok_star = star_info.get('hasstar') is True

    R.record(driver, name, 1,
             f'Matching rows in #processes-body: {star_info.get("count")}. '
             f'First matching row Name cell text: {star_info.get("nameText")!r}. '
             f'Contains ★ (U+2605): {star_info.get("hasstar")}. '
             f'JS: matchIcon in td:nth-child(2) (Name col). '
             f'innerHTML checked for U+2605 star character.',
             ok_star,
             '#processes-body tr.proc-match')

    R.finish_test(name, ok_star)
    return ok_star


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-31 Report Generator')
print(f'Server : {BASE}')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable: {e}'); sys.exit(1)

seed_server()
print('✓ Seed host present')

driver = R.make_driver()
driver.get(BASE)
time.sleep(2)

try:
    ok1 = run_matching_process(driver)
    ok2 = run_non_matching_process(driver)
    ok3 = run_star_indicator(driver)
    all_passed = ok1 and ok2 and ok3
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Process Row proc-match and Dynamic Tab tab-match CSS Classes',
    us_id='US-31',
    description=(
        'When a process output line matches a global-positive keyword, legion.js '
        'adds CSS class proc-match to the process table row (JS line 716) and '
        'tab-match to the dynamic tab button (JS line 1177). '
        'A non-matching process gets neither class. '
        'The ★ star icon is rendered in the Name cell for matching rows. '
        'Isolation: each test uses a unique port so wc._matches keys do not overlap.'
    ),
)
sys.exit(0 if all_passed else 1)
