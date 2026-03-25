#!/usr/bin/env python3
"""
US-44/45/46 Test Report — Keyword Matching: Case, Word-Boundary, Negative
==========================================================================
Usage:
    sudo python3 tests/generate_report_US44_45_46.py [--port 5095]

Root cause of isolation requirement:
    wc._matches is keyed by "hostIp:tabTitle" where tabTitle = "custom (PORT/tcp)".
    All processes on the same port share the same match-key — matches accumulate.
    Each test uses a UNIQUE fake port (2201-2206) so each has its own key.

Three user stories, six scenarios:
  US-44a — "SUCCEED" (in global-positive, uppercase) → has_match=True
  US-44b — "succeed" (lowercase) → has_match=False  (case-sensitive)
  US-45a — "HTTP PUT is allowed" → has_match=True    (word-boundary match)
  US-45b — "PUTTY OUTPUT" → has_match=False          (PUT embedded, boundary fails)
  US-46a — "system is vulnerable" → has_match=True   (positive only)
  US-46b — "system is NOT vulnerable" → has_match=False (negative fires first)
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

import tests.generate_report as R

# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5095)
args  = parser.parse_args()
R.configure(args.port)
BASE  = R.base_url()

HOST_IP  = '10.10.10.1'
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
    """POST /api/processes/custom on a unique port → unique match key."""
    r = requests.post(f'{BASE}/api/processes/custom', json={
        'command':  cmd,
        'host_ip':  HOST_IP,
        'port':     str(port),
        'protocol': 'tcp',
    })
    d = r.json()
    assert d.get('status') == 'ok', f'/api/processes/custom failed: {d}'
    return d['process_id']


def wait_finished(pid, timeout=15):
    """Poll snapshot until pid is Finished/Crashed. Returns (has_match, status)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        procs = requests.get(f'{BASE}/api/snapshot').json().get('processes', [])
        for p in procs:
            if str(p.get('id')) == str(pid):
                if p.get('status') in ('Finished', 'Crashed'):
                    return p.get('has_match', False), p.get('status'), p.get('match_text', '')
        time.sleep(0.5)
    return False, 'Timeout', ''


def wait_dom_finished(driver, pid, timeout=12):
    """Wait for the process row to show Finished in the DOM."""
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


def select_host(driver):
    driver.execute_script(f"""
        var row = document.querySelector(
            '#hosts-body tr[data-host-ip="{HOST_IP}"]');
        if (row) row.click();
    """)
    time.sleep(1.0)


def proc_has_match_class(driver, pid):
    return driver.execute_script(f"""
        var row = document.querySelector(
            '#processes-body tr[data-process-id="{pid}"]');
        if (!row) return null;
        return row.classList.contains('proc-match');
    """)


# ---------------------------------------------------------------------------
# Generic runner — avoids repeating identical structure 6 times
# ---------------------------------------------------------------------------
def run_scenario(driver, name, cmd, port, expect_match, explanation):
    print(f'\n  {name}')
    select_host(driver)

    R.record(driver, name, 1,
             f'Host {HOST_IP} selected. Port {port} used for isolation '
             f'(each port = unique match key "10.10.10.1:custom ({port}/tcp)"). '
             f'Command: {cmd!r}. {explanation}',
             True, '#hosts-body')

    pid = run_custom(cmd, port)

    dom_status = wait_dom_finished(driver, pid)
    has_match, snap_status, match_text = wait_finished(pid)

    time.sleep(1.5)   # one full snapshot cycle for proc-match class to render
    row_has_match = proc_has_match_class(driver, pid)

    ok_api = (has_match is True) == expect_match
    ok_dom = (row_has_match is True) == expect_match

    verdict = 'MATCH' if expect_match else 'NO MATCH'
    R.record(driver, name, 2,
             f'Process {pid}: status={snap_status}, has_match={has_match} '
             f'(match_text={match_text!r}). '
             f'Expected: {verdict}. API correct: {ok_api}. '
             f'proc-match class in DOM: {row_has_match} (correct: {ok_dom}).',
             ok_api and ok_dom,
             f'#processes-body tr[data-process-id="{pid}"]')

    passed = ok_api and ok_dom
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-44/45/46 Report Generator')
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
    results = []

    results.append(run_scenario(
        driver,
        name='US-44a — Case-sensitive MATCH: "SUCCEED" (uppercase)',
        cmd='printf "SUCCEED test"',
        port=2201,
        expect_match=True,
        explanation='"SUCCEED" is in global-positive. _pattern_matches uses '
                    'case-sensitive `in` — "SUCCEED" in "SUCCEED test" → True.',
    ))

    results.append(run_scenario(
        driver,
        name='US-44b — Case-sensitive NO MATCH: "succeed" (lowercase)',
        cmd='printf "succeed test"',
        port=2202,
        expect_match=False,
        explanation='"succeed" is NOT in global-positive (only "SUCCEED" uppercase is). '
                    'Case-sensitive check: "SUCCEED" in "succeed test" → False.',
    ))

    results.append(run_scenario(
        driver,
        name='US-45a — Word-boundary MATCH: "HTTP PUT is allowed"',
        cmd='printf "HTTP PUT is allowed"',
        port=2203,
        expect_match=True,
        explanation='Keyword " PUT " has leading+trailing spaces → regex (?<!\\w)PUT(?!\\w). '
                    'In "HTTP PUT is allowed", PUT preceded by space (not \\w) and '
                    'followed by space (not \\w) → match.',
    ))

    results.append(run_scenario(
        driver,
        name='US-45b — Word-boundary NO MATCH: "PUTTY OUTPUT" (PUT embedded)',
        cmd='printf "PUTTY OUTPUT"',
        port=2204,
        expect_match=False,
        explanation='(?<!\\w)PUT(?!\\w): in "PUTTY", PUT followed by T (\\w) → '
                    'suffix fails. In "OUTPUT", PUT preceded by T (\\w) → prefix fails. '
                    'Neither satisfies the word-boundary regex.',
    ))

    results.append(run_scenario(
        driver,
        name='US-46a — Positive fires when no negative: "system is vulnerable"',
        cmd='printf "system is vulnerable"',
        port=2205,
        expect_match=True,
        explanation='"vulnerable" in global-positive. _getMatches checks negatives '
                    'first — "NOT vulnerable", "Not vulnerable" etc. not in this line '
                    '→ negative check passes → positive "vulnerable" fires → match.',
    ))

    results.append(run_scenario(
        driver,
        name='US-46b — Negative suppresses positive: "system is NOT vulnerable"',
        cmd='printf "system is NOT vulnerable to this"',
        port=2206,
        expect_match=False,
        explanation='"NOT vulnerable" is in global-negative. _getMatches checks '
                    'negatives FIRST: "NOT vulnerable" IS in this line → returns '
                    'empty immediately. "vulnerable" positive never checked.',
    ))

    all_passed = all(results)
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Keyword Matching: Case-Sensitive, Word-Boundary, Negative Suppression',
    us_id='US-44-45-46',
    description=(
        'US-44: Global-positive keywords are case-sensitive — "SUCCEED" matches '
        '"SUCCEED" but not "succeed". '
        'US-45: Keywords stored with spaces use word-boundary regex '
        r'(?&lt;!\w)PUT(?!\w) — matches "HTTP PUT is allowed" but not "PUTTY OUTPUT". '
        'US-46: Negative patterns are checked FIRST — "NOT vulnerable" suppresses '
        '"vulnerable" on the same line. '
        'Isolation: each test uses a unique port so wc._matches keys do not overlap.'
    ),
)
sys.exit(0 if all_passed else 1)
