#!/usr/bin/env python3
"""US-18 Report — Auto-scroll stays at bottom when user is at bottom.
Usage: sudo python3 tests/generate_report_US18.py [--port 5085]
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


def select_host_and_process(driver, process_id, wait=12):
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


def scroll_info(driver):
    return driver.execute_script("""
        var el = document.getElementById('plain-output');
        return {
            scrollTop:    el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            gap:          el.scrollHeight - el.scrollTop - el.clientHeight,
            scrollable:   el.scrollHeight > el.clientHeight
        };
    """)


# ---------------------------------------------------------------------------
def run_autoscroll_at_bottom(driver):
    name   = 'Test 1 — Panel stays at bottom across polls when user is at bottom'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE); time.sleep(2)
    pid = start_slow_process()
    R.record(driver, name, 1,
             f'Started slow process pid={pid} (40 lines × 0.35 s = 14 s). '
             f'Waiting 10 s for ~28 lines to accumulate before clicking '
             f'(need scrollHeight > clientHeight for a meaningful scroll test).',
             True, '#processes-body')

    time.sleep(10.0)
    select_host_and_process(driver, pid)

    si0 = scroll_info(driver)
    R.record(driver, name, 2,
             f'Clicked process row. #plain-output state after first load: '
             f'scrollHeight={si0["scrollHeight"]} clientHeight={si0["clientHeight"]} '
             f'scrollTop={si0["scrollTop"]} gap={si0["gap"]:.0f}px '
             f'scrollable={si0["scrollable"]}. '
             f'First load defaults atBottom=True so loadProcessOutput '
             f'sets scrollTop=scrollHeight.',
             si0['scrollable'], '#plain-output')

    # Explicitly scroll to bottom
    driver.execute_script(
        "var el=document.getElementById('plain-output'); el.scrollTop=el.scrollHeight;")
    time.sleep(0.1)
    si1 = scroll_info(driver)
    R.record(driver, name, 3,
             f'Scrolled to exact bottom (scrollTop=scrollHeight). '
             f'gap={si1["gap"]:.0f} px (must be <40). '
             f'This simulates the user being at the bottom watching live output.',
             si1['gap'] < 40, '#plain-output')

    time.sleep(3.5)   # 2+ polls
    si2 = scroll_info(driver)
    ok = si2['gap'] < 40
    passed = ok
    R.record(driver, name, 4,
             f'After 3.5 s (≥2 polls): gap={si2["gap"]:.0f} px '
             f'scrollHeight={si2["scrollHeight"]} scrollTop={si2["scrollTop"]}. '
             f'loadProcessOutput read atBottom=True before each fetch and '
             f'fired scrollTop=scrollHeight after the innerHTML update. '
             f'gap<40px: {ok}.',
             ok, '#plain-output')

    R.finish_test(name, passed)
    return passed


def run_scroll_up_preserved(driver):
    name   = 'Test 2 — Scroll-up position is preserved across polls (not hijacked)'
    passed = True
    print(f'\n  {name}')

    pid = start_slow_process()
    time.sleep(10.0)

    select_host_and_process(driver, pid)
    time.sleep(1.5)

    si_pre = scroll_info(driver)
    if not si_pre['scrollable']:
        time.sleep(3.0)
        si_pre = scroll_info(driver)

    # Scroll to TOP
    driver.execute_script(
        "document.getElementById('plain-output').scrollTop = 0;")
    time.sleep(0.1)
    top_before = driver.execute_script(
        "return document.getElementById('plain-output').scrollTop")

    R.record(driver, name, 1,
             f'Scrolled #plain-output to TOP (scrollTop=0). '
             f'scrollHeight={si_pre["scrollHeight"]} clientHeight={si_pre["clientHeight"]}. '
             f'loadProcessOutput records atBottom=False because '
             f'scrollHeight-scrollTop-clientHeight > 40.',
             True, '#plain-output')

    time.sleep(3.5)   # 2+ polls

    top_after = driver.execute_script(
        "return document.getElementById('plain-output').scrollTop")
    si_post  = scroll_info(driver)
    drift    = abs(top_after - top_before)
    ok       = drift < 20
    passed   = ok

    R.record(driver, name, 2,
             f'After 3.5 s: scrollTop before={top_before}px after={top_after}px '
             f'drift={drift}px (must be <20). '
             f'loadProcessOutput only auto-scrolls when atBottom was True. '
             f'Since user scrolled up, atBottom=False → position preserved. '
             f'v10.30: _procScrollPos map stores the position before each poll.',
             ok, '#plain-output')

    R.finish_test(name, passed)
    return passed


print(f'\nLegion US-18 Report Generator | Server: {BASE}')
try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ {e}'); sys.exit(1)

driver = R.make_driver()
try:
    all_ok  = run_autoscroll_at_bottom(driver)
    all_ok  = run_scroll_up_preserved(driver) and all_ok
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} passed')
R.render_and_save(
    title='Auto-Scroll Stays at Bottom — Scroll Position Preserved When Up',
    us_id='US-18',
    description=(
        'loadProcessOutput() reads atBottom = (scrollHeight-scrollTop-clientHeight < 40) '
        'BEFORE each fetch. If at bottom: after innerHTML update, scrollTop is '
        'set to scrollHeight (follow). If scrolled up: _procScrollPos restores '
        'the exact pixel offset (v10.30).'
    ),
)
sys.exit(0 if all_ok else 1)
