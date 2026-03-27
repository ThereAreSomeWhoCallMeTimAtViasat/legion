#!/usr/bin/env python3
"""US-55 Report — Two instances on different ports are independent.
Usage: sudo python3 tests/generate_report_US55.py [--port-a 5085] [--port-b 5086]

Requires BOTH servers already running:
    sudo python3 legion.py --web --port 5085 &
    sudo python3 legion.py --web --port 5086 &
"""
import argparse, os, sys, time, tempfile
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
import requests
from selenium.webdriver.common.by import By
import tests.generate_report as R

parser = argparse.ArgumentParser()
parser.add_argument('--port-a', type=int, default=5085)
parser.add_argument('--port-b', type=int, default=5086)
args = parser.parse_args()

PORT_A = args.port_a
PORT_B = args.port_b
URL_A  = f'http://127.0.0.1:{PORT_A}'
URL_B  = f'http://127.0.0.1:{PORT_B}'

# Configure generate_report module with port A (primary)
R.configure(PORT_A)

# Unique IPs for this test
IP_A = '10.55.85.1'
IP_B = '10.55.86.1'

XML_A = f"""<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{IP_A}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="80">
      <state state="open"/><service name="http"/>
    </port></ports>
  </host>
</nmaprun>"""

XML_B = f"""<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{IP_B}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="443">
      <state state="open"/><service name="https"/>
    </port></ports>
  </host>
</nmaprun>"""


def import_xml(port, xml):
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); path = f.name
    try:
        return requests.post(f'http://127.0.0.1:{port}/api/nmap/import-xml',
                             json={'path': path}, timeout=60).json()
    finally:
        os.unlink(path)


def hosts_at(port):
    return [h['ip'] for h in requests.get(
        f'http://127.0.0.1:{port}/api/snapshot', timeout=5).json().get('hosts', [])]


def ui_host_ips(driver, url):
    driver.get(url)
    time.sleep(2.5)
    return driver.execute_script("""
        return Array.from(
            document.querySelectorAll('#hosts-body tr[data-host-ip]')
        ).map(r => r.dataset.hostIp);
    """)


def drain_server(port):
    """Kill all running processes and wait until the queue is truly empty.

    killRunningProcesses() takes 10-15 s with many processes (0.3 s × N for
    SIGTERM → SIGKILL). After it returns, killed-process threads still write
    final state to DB for several more seconds.  Sleeping a fixed time is
    unreliable; instead we poll the snapshot until no Running/Waiting procs
    remain, then add a short DB-settle pause.
    """
    try:
        requests.post(f'http://127.0.0.1:{port}/api/processes/drain',
                      json={}, timeout=60)   # drain itself may take 15 s
    except Exception:
        pass
    # Poll until queue is empty (Running/Waiting → Killed/Finished)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            snap = requests.get(f'http://127.0.0.1:{port}/api/snapshot',
                                timeout=5).json()
            active = [p for p in snap.get('processes', [])
                      if p.get('status') in ('Running', 'Waiting')]
            if not active:
                break
        except Exception:
            pass
        time.sleep(1)
    time.sleep(3)   # let killed-process Python threads finish their DB writes


def ensure_seed():
    # Drain both servers so their DB is idle before we write to it.
    # Background nmap/auto-tool processes from earlier reports hold DB write
    # locks; the import will ReadTimeout if those locks aren't released first.
    drain_server(PORT_A)
    drain_server(PORT_B)
    if IP_A not in hosts_at(PORT_A):
        import_xml(PORT_A, XML_A); time.sleep(1)
    if IP_B not in hosts_at(PORT_B):
        import_xml(PORT_B, XML_B); time.sleep(1)


# ---------------------------------------------------------------------------
def run_api_isolation(driver):
    name   = 'Test 1 — API: each instance\'s snapshot contains only its own host'
    passed = True
    print(f'\n  {name}')

    driver.get(URL_A); time.sleep(1.5)
    hosts_a = hosts_at(PORT_A)
    hosts_b = hosts_at(PORT_B)

    ok_a_has  = IP_A in hosts_a
    ok_a_excl = IP_A not in hosts_b
    ok_b_has  = IP_B in hosts_b
    ok_b_excl = IP_B not in hosts_a
    ok        = ok_a_has and ok_a_excl and ok_b_has and ok_b_excl
    passed    = ok

    R.record(driver, name, 1,
             f'Server A ({URL_A}) snapshot hosts: {hosts_a}. '
             f'Server B ({URL_B}) snapshot hosts: {hosts_b}. '
             f'{IP_A} in A={ok_a_has} | {IP_A} absent from B={ok_a_excl} | '
             f'{IP_B} in B={ok_b_has} | {IP_B} absent from A={ok_b_excl}. '
             f'Each Legion instance uses an isolated SQLite DB in /tmp — '
             f'created by NamedTemporaryFile at startup (v10.26).',
             ok)

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
def run_ui_a_shows_ip_a(driver):
    name   = f'Test 2 — Selenium: navigating to :{PORT_A} shows {IP_A}, not {IP_B}'
    passed = True
    print(f'\n  {name}')

    ips = ui_host_ips(driver, URL_A)
    ok_has  = IP_A in ips
    ok_excl = IP_B not in ips
    ok      = ok_has and ok_excl
    passed  = ok

    R.record(driver, name, 1,
             f'Browser at {URL_A} — #hosts-body data-host-ip values: {ips}. '
             f'{IP_A} present={ok_has} (should be True). '
             f'{IP_B} absent={ok_excl} (should be True — only belongs to :{PORT_B}).',
             ok, '#hosts-table, #hosts-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
def run_ui_b_shows_ip_b(driver):
    name   = f'Test 3 — Selenium: navigating to :{PORT_B} shows {IP_B}, not {IP_A}'
    passed = True
    print(f'\n  {name}')

    ips = ui_host_ips(driver, URL_B)
    ok_has  = IP_B in ips
    ok_excl = IP_A not in ips
    ok      = ok_has and ok_excl
    passed  = ok

    R.record(driver, name, 1,
             f'Browser at {URL_B} — #hosts-body data-host-ip values: {ips}. '
             f'{IP_B} present={ok_has} (should be True). '
             f'{IP_A} absent={ok_excl} (should be True — only belongs to :{PORT_A}).',
             ok, '#hosts-table, #hosts-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
def run_ui_side_by_side(driver):
    name   = 'Test 4 — Selenium: one driver navigates A then B, confirms different host sets'
    passed = True
    print(f'\n  {name}')

    ips_a = ui_host_ips(driver, URL_A)
    R.record(driver, name, 1,
             f'Step 1 of 2: Browser at {URL_A}. '
             f'Hosts in DOM: {ips_a}. '
             f'{IP_A} present: {IP_A in ips_a}.',
             IP_A in ips_a, '#hosts-body')

    ips_b = ui_host_ips(driver, URL_B)
    R.record(driver, name, 2,
             f'Step 2 of 2: Same browser driver navigated to {URL_B}. '
             f'Hosts in DOM: {ips_b}. '
             f'Completely different host set — {IP_B} present: {IP_B in ips_b}. '
             f'{IP_A} absent: {IP_A not in ips_b}. '
             f'Both servers use --no-remote Firefox profiles per port (v10.29) '
             f'and separate SQLite DBs (v10.26).',
             IP_B in ips_b and IP_A not in ips_b, '#hosts-body')

    ok = IP_A in ips_a and IP_B in ips_b and IP_A not in ips_b and IP_B not in ips_a
    passed = ok
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
def run_process_isolation(driver):
    name   = f'Test 5 — Process scan on :{PORT_A} does not appear in :{PORT_B}'
    passed = True
    print(f'\n  {name}')

    procs_b_before = len(requests.get(f'{URL_B}/api/snapshot').json().get('processes', []))
    driver.get(URL_B); time.sleep(1.5)
    R.record(driver, name, 1,
             f'Baseline: server B ({URL_B}) has {procs_b_before} processes. '
             f'About to submit a scan to server A only.',
             True, '#processes-table, #processes-body')

    resp = requests.post(f'{URL_A}/api/nmap/scan', json={
        'targets': '127.0.0.1',
        'scan_mode': 'Easy', 'discovery': False, 'staged': False,
        'timing': '4', 'nmap_options': ['-n'], 'enable_ipv6': False,
    }, timeout=10)
    R.record(driver, name, 2,
             f'POST /api/nmap/scan to {URL_A}: HTTP {resp.status_code} '
             f'status={resp.json().get("status")}. '
             f'Waiting 2.5 s for snapshot poll...',
             resp.status_code == 200)

    time.sleep(2.5)
    procs_b_after = len(requests.get(f'{URL_B}/api/snapshot').json().get('processes', []))
    ok = procs_b_after == procs_b_before
    passed = ok

    # Navigate driver to B to show its unchanged process table
    ips_b = ui_host_ips(driver, URL_B)
    R.record(driver, name, 3,
             f'Server B process count: before={procs_b_before} after={procs_b_after}. '
             f'Must be unchanged — WebController instances are per-process; '
             f'each server\'s wc.runCommand() only modifies its own DB and queue. '
             f'unchanged={ok}.',
             ok, '#processes-table, #processes-body')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
print(f'\nLegion US-55 Report Generator')
print(f'Server A: {URL_A}')
print(f'Server B: {URL_B}')

for url, label in [(URL_A, 'A'), (URL_B, 'B')]:
    try:
        requests.get(f'{url}/api/snapshot', timeout=5).raise_for_status()
        print(f'✓ Server {label} ({url}) reachable')
    except Exception as e:
        print(f'✗ Server {label} ({url}) not reachable: {e}')
        sys.exit(1)

ensure_seed()
print(f'✓ Seeds: {IP_A} in :{PORT_A}, {IP_B} in :{PORT_B}')

driver = R.make_driver()
try:
    all_ok  = run_api_isolation(driver)
    all_ok  = run_ui_a_shows_ip_a(driver)  and all_ok
    all_ok  = run_ui_b_shows_ip_b(driver)  and all_ok
    all_ok  = run_ui_side_by_side(driver)   and all_ok
    all_ok  = run_process_isolation(driver) and all_ok
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} passed')
R.render_and_save(
    title='Two Instances on Different Ports Are Independent',
    us_id='US-55',
    description=(
        f'Legion :{PORT_A} and :{PORT_B} are completely isolated: '
        f'separate SQLite DBs (NamedTemporaryFile per instance, v10.26), '
        f'separate WebController instances, separate process queues. '
        f'Data imported into one instance never appears in the other at the '
        f'API (/api/snapshot) or UI (#hosts-body) level.'
    ),
)
sys.exit(0 if all_ok else 1)
