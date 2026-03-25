#!/usr/bin/env python3
"""
US-39 Test Report — Screenshot Tab Shows Eyewitness Capture for HTTP Services
==============================================================================
Usage:
    sudo python3 tests/generate_report_US39.py [--port 5095] [--target 192.168.85.11]

Requires: eyewitness at /usr/bin/eyewitness; xvfb-run; live target with HTTP.

Verifies US-39: after the screenshooter runs against an HTTP service, clicking
the screenshooter process row in the Processes table shows the captured PNG
image in the lower output panel.

Implementation:
  1. _run_screenshot() calls wc.runCommand(name='screenshooter', ...)
     with command: xvfb-run -a eyewitness --single http://IP:PORT --no-prompt
                   --web --delay 15 -d {outputfile}-dir
  2. /api/processes/{id}/output: if name=='screenshooter' and PNG exists in
     outputfile-dir → returns 'screenshot:/path/to/file.png'
  3. loadProcessOutput() in legion.js: if text.startsWith('screenshot:')
     → renders <img src="/api/screenshots?path=...">
  4. /api/screenshots?path= serves the PNG file

Trigger path:
  Import nmap XML with HTTP port → POST /api/scheduler/run → scheduler
  finds HTTP service for host → calls _run_screenshot(ip, port) →
  creates process with name='screenshooter'.

Three scenarios:
  1. Import host + HTTP port; trigger scheduler; screenshooter process appears.
  2. Wait for screenshooter to Finish (eyewitness captures the page).
  3. Click the screenshooter row → lower panel shows <img> tag pointing to
     /api/screenshots (the captured PNG is served and rendered).
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
parser.add_argument('--port',   type=int, default=5095)
parser.add_argument('--target', default='192.168.85.11')
args  = parser.parse_args()
R.configure(args.port)
BASE   = R.base_url()
TARGET = args.target

SEED_XML = f"""\
<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{TARGET}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


def get_host_id():
    for h in requests.get(f'{BASE}/api/snapshot').json().get('hosts', []):
        if h['ip'] == TARGET:
            return h['id']
    return None


def select_host(driver):
    driver.execute_script(f"""
        var row = document.querySelector('#hosts-body tr[data-host-ip="{TARGET}"]');
        if (row) row.click();
    """)
    time.sleep(1.0)


def find_screenshooter_pid():
    """Return (process_id, status) for the first screenshooter process, or (None, None)."""
    for p in requests.get(f'{BASE}/api/snapshot').json().get('processes', []):
        if p.get('name') == 'screenshooter':
            return p['id'], p.get('status')
    return None, None


# ---------------------------------------------------------------------------
# Scenario 1 — Import host with HTTP; trigger scheduler; screenshooter starts
# ---------------------------------------------------------------------------
def run_screenshooter_starts(driver):
    name = f'Test 1 — Import {TARGET}:80/http; scheduler triggers screenshooter process'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Importing nmap XML showing {TARGET} port 80/http open. '
             f'Then POST /api/scheduler/run to invoke scheduler(). '
             f'Scheduler finds http service → calls _run_screenshot(ip, 80) → '
             f'runCommand(name="screenshooter", cmd="xvfb-run eyewitness ..."). '
             f'screenshooter-timeout=15000ms in config (15s eyewitness delay).',
             True, '#processes-body')

    # Import XML
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML); path = f.name
    requests.post(f'{BASE}/api/nmap/import-xml', json={'path': path})
    time.sleep(1.0)
    os.unlink(path)

    select_host(driver, )

    # Trigger scheduler
    requests.post(f'{BASE}/api/scheduler/run', json={})
    time.sleep(2.0)   # scheduler queues the screenshooter

    # Wait for screenshooter process to appear in snapshot
    deadline = time.time() + 15
    pid = None
    while time.time() < deadline:
        pid, _ = find_screenshooter_pid()
        if pid:
            break
        time.sleep(1)

    ok = pid is not None

    # Also wait for it to appear in the DOM
    if ok:
        time.sleep(1.5)  # one snapshot poll

    R.record(driver, name, 2,
             f'screenshooter process ID: {pid}. '
             f'Process visible in Processes table.',
             ok,
             '#processes-body')

    R.finish_test(name, ok)
    return ok, pid


# ---------------------------------------------------------------------------
# Scenario 2 — Wait for screenshooter to finish
# ---------------------------------------------------------------------------
def run_screenshooter_finishes(driver, pid):
    name = 'Test 2 — Screenshooter output shows screenshot: path (PNG captured)'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Polling /api/processes/{pid}/output every 2s for up to 90s. '
             f'Server: if name=="screenshooter" and PNG exists in outputfile-dir/ '
             f'→ returns "screenshot:/path". '
             f'eyewitness --delay 15 takes ~20-30s to capture. '
             f'Process may still be Running when PNG is ready (eyewitness '
             f'writes the PNG before its process fully exits).',
             True,
             f'#processes-body')

    timeout  = 90
    deadline = time.time() + timeout
    found_screenshot = False
    screenshot_path  = None
    while time.time() < deadline:
        resp = requests.get(f'{BASE}/api/processes/{pid}/output').json()
        out  = resp.get('output_chunk', '') or resp.get('output', '') or ''
        if out.startswith('screenshot:'):
            found_screenshot = True
            screenshot_path  = out.strip()
            break
        _, status = find_screenshooter_pid()
        if status in ('Finished', 'Crashed'):
            # Re-check output after status change
            out2 = requests.get(f'{BASE}/api/processes/{pid}/output').json().get('output_chunk','')
            if out2.startswith('screenshot:'):
                found_screenshot = True
                screenshot_path  = out2.strip()
            break
        time.sleep(2)

    ok = found_screenshot
    R.record(driver, name, 2,
             f'Process {pid} output starts with "screenshot:": {found_screenshot}. '
             f'Path: {screenshot_path!r}. '
             f'{"PNG captured by eyewitness and found by the server." if ok else "No screenshot: prefix — PNG not found in outputfile-dir."}',
             ok,
             f'#processes-body')

    R.finish_test(name, ok)
    return ok


# ---------------------------------------------------------------------------
# Scenario 3 — Click screenshooter row → <img> appears in lower panel
# ---------------------------------------------------------------------------
def run_screenshot_renders(driver, pid):
    name = 'Test 3 — Clicking screenshooter row renders <img> in lower panel'
    print(f'\n  {name}')

    select_host(driver)
    time.sleep(1.0)

    R.record(driver, name, 1,
             f'Clicking process row data-process-id="{pid}" (screenshooter). '
             f'loadProcessOutput() fetches /api/processes/{pid}/output. '
             f'Server: if name=="screenshooter" and PNG in outputfile-dir/ → '
             f'returns "screenshot:/path/to/file.png". '
             f'JS: if text.startsWith("screenshot:") → innerHTML = <img src="/api/screenshots?path=...">.',
             True,
             f'#processes-body tr[data-process-id="{pid}"]')

    # Click the screenshooter row
    driver.execute_script(f"""
        var row = document.querySelector('#processes-body tr[data-process-id="{pid}"]');
        if (row) row.click();
    """)
    time.sleep(2.5)   # loadProcessOutput + render time

    # Check if <img> with /api/screenshots in src appears in plain-output
    img_info = driver.execute_script("""
        var po = document.getElementById('plain-output');
        if (!po) return {found: false};
        var img = po.querySelector('img');
        if (!img) return {found: false, innerText: po.innerText.substring(0, 100)};
        return {
            found: true,
            src:   img.getAttribute('src') || '',
            hasScreenshots: (img.getAttribute('src') || '').indexOf('/api/screenshots') >= 0
        };
    """)

    ok = img_info.get('hasScreenshots') is True

    R.record(driver, name, 2,
             f'#plain-output img found: {img_info.get("found")}. '
             f'img src: {img_info.get("src","")!r}. '
             f'Contains /api/screenshots: {img_info.get("hasScreenshots")}. '
             f'Must be True — eyewitness PNG served via /api/screenshots?path=...',
             ok,
             '#plain-output')

    R.finish_test(name, ok)
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-39 Report Generator')
print(f'Server : {BASE}')
print(f'Target : {TARGET}')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable: {e}'); sys.exit(1)

import subprocess as _sp
if _sp.run(['ping', '-c', '1', '-W', '2', TARGET], capture_output=True).returncode != 0:
    print(f'✗ Target {TARGET} not reachable'); sys.exit(1)
print(f'✓ Target {TARGET} reachable')

if not os.path.isfile('/usr/bin/eyewitness'):
    print('✗ eyewitness not found at /usr/bin/eyewitness'); sys.exit(1)
print('✓ eyewitness available')

driver = R.make_driver()
driver.get(BASE)
time.sleep(2)

try:
    ok1, pid  = run_screenshooter_starts(driver)
    ok2       = run_screenshooter_finishes(driver, pid) if ok1 else False
    ok3       = run_screenshot_renders(driver, pid)     if ok2 else False
    all_passed = ok1 and ok2 and ok3
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Screenshot Tab — Eyewitness PNG Rendered After HTTP Screenshooter',
    us_id='US-39',
    description=(
        f'Import {TARGET}:80 as HTTP host → POST /api/scheduler/run → '
        f'scheduler triggers _run_screenshot() → wc.runCommand(name="screenshooter") → '
        f'xvfb-run eyewitness captures PNG to outputfile-dir/. '
        f'Clicking screenshooter row → /api/processes/{{id}}/output returns '
        f'"screenshot:/path" → JS renders <img src="/api/screenshots?path=...">.'
    ),
)
sys.exit(0 if all_passed else 1)
