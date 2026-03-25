#!/usr/bin/env python3
"""US-16 Report — Live output grows while process is Running.
Usage: sudo python3 tests/generate_report_US16.py [--port 5085]
"""
import argparse, os, sys, time
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

HOST_IP  = '10.10.10.1'
SLOW_CMD = (
    "python3 -c "
    "'import time; "
    "[(print(\"LINE_\"+str(i),flush=True),time.sleep(0.35)) for i in range(40)]'"
)


def api(method, path, **kw):
    return getattr(requests, method)(BASE + path, **kw)


def start_slow_process():
    resp = api('post', '/api/processes/custom', json={
        'command': SLOW_CMD, 'host_ip': HOST_IP, 'port': '', 'protocol': 'tcp'})
    pid = resp.json().get('process_id')
    assert pid, f'No process_id: {resp.json()}'
    return pid


def select_host_and_process(driver, process_id, wait=8):
    driver.execute_script("""
        var row = document.querySelector(
            '#hosts-body tr[data-host-ip="' + arguments[0] + '"]');
        if (row) row.click();
    """, HOST_IP)
    time.sleep(0.8)
    css = f'#processes-body tr[data-process-id="{process_id}"]'
    WebDriverWait(driver, wait).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, css))
    row = driver.find_element(By.CSS_SELECTOR, css)
    driver.execute_script(
        'arguments[0].scrollIntoView({block:"center"}); arguments[0].click()', row)
    time.sleep(1.5)


# ---------------------------------------------------------------------------
def run_output_grows(driver):
    name   = 'Test 1 — #plain-output text grows over 3.5 s while process is Running'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE); time.sleep(2)
    pid = start_slow_process()
    time.sleep(1.0)

    R.record(driver, name, 1,
             f'Started slow process (pid={pid}): '
             f'python3 producing LINE_N every 0.35 s for 40 lines (~14 s total). '
             f'Command does not contain "bash" or "msfconsole" → not marked Interactive.',
             True, '#processes-table, #processes-body')

    select_host_and_process(driver, pid)
    t0_html = driver.execute_script(
        "return document.getElementById('plain-output').innerHTML || ''")
    t0_len  = len(t0_html)
    t0_text = driver.execute_script(
        "return document.getElementById('plain-output').innerText || ''")
    R.record(driver, name, 2,
             f'Clicked process row (data-process-id={pid}). '
             f'#plain-output loaded with current output ({t0_len} HTML chars). '
             f'Snapshot poll fires every 1.5 s and calls '
             f'loadProcessOutput() → reads .live_output temp file.',
             bool(t0_text.strip()), '#plain-output')

    time.sleep(3.5)

    t1_html = driver.execute_script(
        "return document.getElementById('plain-output').innerHTML || ''")
    t1_len  = len(t1_html)
    t1_text = driver.execute_script(
        "return document.getElementById('plain-output').innerText || ''")
    ok      = t1_len > t0_len
    passed  = ok
    R.record(driver, name, 3,
             f'After 3.5 s (≥2 polls): #plain-output is now {t1_len} HTML chars '
             f'(was {t0_len}). Grew by {t1_len - t0_len} chars. '
             f'New lines: {t1_text[:80]!r}... '
             f'grew={ok}.',
             ok, '#plain-output')

    R.finish_test(name, passed)
    return passed


def run_line_markers(driver):
    name   = 'Test 2 — After 6 s output contains ≥5 LINE_N markers'
    passed = True
    print(f'\n  {name}')

    pid = start_slow_process()
    time.sleep(6.0)

    select_host_and_process(driver, pid)
    time.sleep(1.5)

    text  = driver.execute_script(
        "return document.getElementById('plain-output').innerText || ''")
    count = sum(1 for ln in text.splitlines() if ln.strip().startswith('LINE_'))
    ok    = count >= 5
    passed = ok
    R.record(driver, name, 1,
             f'After 6 s: output contains {count} LINE_N marker(s). '
             f'At 0.35 s/line, 6 s → ~17 lines expected. '
             f'Text snippet: {text[:120]!r}. '
             f'count≥5: {ok}.',
             ok, '#plain-output')

    R.finish_test(name, passed)
    return passed


def run_status_running(driver):
    name   = 'Test 3 — Process row shows status "Running" while output is live'
    passed = True
    print(f'\n  {name}')

    pid = start_slow_process()
    time.sleep(1.0)

    select_host_and_process(driver, pid)

    status = driver.execute_script("""
        var row = document.querySelector(
            '#processes-body tr[data-process-id="' + arguments[0] + '"]');
        if (!row) return 'NOT FOUND';
        var cells = row.querySelectorAll('td');
        return cells.length >= 5 ? cells[4].textContent.trim() : 'NO CELL';
    """, str(pid))

    ok = (status == 'Running')
    passed = ok
    R.record(driver, name, 1,
             f'Process row status cell: {status!r}. Must be "Running". '
             f'The process is still producing output at 0.35 s/line.',
             ok,
             f'#processes-body tr[data-process-id="{pid}"]')

    R.finish_test(name, passed)
    return passed


print(f'\nLegion US-16 Report Generator | Server: {BASE}')
try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ {e}'); sys.exit(1)

driver = R.make_driver()
try:
    all_ok  = run_output_grows(driver)
    all_ok  = run_line_markers(driver)   and all_ok
    all_ok  = run_status_running(driver) and all_ok
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} passed')
R.render_and_save(
    title='Live Output Grows While Process is Running',
    us_id='US-16',
    description=(
        'When a Running process is selected, #plain-output must update with new lines '
        'every 1.5 s via the snapshot poll → loadProcessOutput() → '
        '.live_output temp file read. No manual refresh required.'
    ),
)
sys.exit(0 if all_ok else 1)
