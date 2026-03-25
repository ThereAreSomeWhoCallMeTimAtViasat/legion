#!/usr/bin/env python3
"""US-40 Report — Log tab is non-empty.
Usage: sudo python3 tests/generate_report_US40.py [--port 5085]
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


def api(path):
    return requests.get(BASE + path).json()


def open_log_tab(driver):
    btn = driver.find_element(By.CSS_SELECTOR, '#bottom-tab-bar [data-tab="log-panel"]')
    driver.execute_script('arguments[0].click()', btn)
    WebDriverWait(driver, 8).until(
        lambda d: bool(d.find_element(By.ID, 'log-output')
                        .get_attribute('innerHTML').strip()))


# ---------------------------------------------------------------------------
def run_output_nonempty(driver):
    name = 'Test 1 — #log-output is non-empty after clicking Log tab'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)
    R.record(driver, name, 1,
             f'Navigate to Legion at {BASE}. Processes table visible.',
             True, '#processes-table, #processes-body')

    btn = driver.find_element(By.CSS_SELECTOR,
                              '#bottom-tab-bar [data-tab="log-panel"]')
    driver.execute_script('arguments[0].click()', btn)
    R.record(driver, name, 2,
             'Clicked the Log tab button in #bottom-tab-bar. '
             'Click triggers loadLog() → fetchJson("/api/logs?level=INFO") → '
             'sets #log-output.innerHTML via ansiToHtml().',
             True, '#bottom-tab-bar [data-tab="log-panel"]')

    WebDriverWait(driver, 8).until(
        lambda d: bool(d.find_element(By.ID, 'log-output')
                        .get_attribute('innerHTML').strip()))
    time.sleep(0.5)

    html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
    ok = bool(html.strip())
    passed = ok
    R.record(driver, name, 4,
             f'#log-output.innerHTML length={len(html)} chars. '
             f'Must be non-empty — the _InMemoryLogHandler buffer has '
             f'been capturing server log output since startup.',
             ok, '#log-output')

    R.finish_test(name, passed)
    return passed


def run_line_count(driver):
    name = 'Test 2 — #log-line-count shows N lines where N > 0'
    passed = True
    print(f'\n  {name}')

    open_log_tab(driver)
    time.sleep(0.5)

    text = driver.find_element(By.ID, 'log-line-count').text.strip()
    ok_has_lines = 'lines' in text
    count = int(text.split()[0]) if text.split() and text.split()[0].isdigit() else 0
    ok_positive = count > 0
    ok = ok_has_lines and ok_positive
    passed = ok

    R.record(driver, name, 1,
             f'#log-line-count text: {text!r}. '
             f'Must contain "lines" and show a count > 0. '
             f'loadLog() sets this via: setText("log-line-count", lines.length + " lines"). '
             f'has_lines={ok_has_lines} | count={count} | positive={ok_positive}.',
             ok, '#log-line-count')

    R.finish_test(name, passed)
    return passed


def run_api_nonempty(driver):
    name = 'Test 3 — /api/logs returns at least one log line'
    passed = True
    print(f'\n  {name}')

    d = api('/api/logs?level=INFO')
    total    = d.get('total', 0)
    n_lines  = len(d.get('lines', []))
    ok       = total > 0 and n_lines > 0
    passed   = ok

    R.record(driver, name, 1,
             f'/api/logs?level=INFO → total={total}, displayed={n_lines}. '
             f'total is the un-truncated buffer count; displayed is capped at 500. '
             f'_InMemoryLogHandler (maxlen=10000) captures without stdout redirect.',
             ok, '#log-output')

    R.finish_test(name, passed)
    return passed


print(f'\nLegion US-40 Report Generator | Server: {BASE}')
try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ {e}'); sys.exit(1)

driver = R.make_driver()
try:
    all_ok = run_output_nonempty(driver)
    all_ok = run_line_count(driver)  and all_ok
    all_ok = run_api_nonempty(driver) and all_ok
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} passed')
R.render_and_save(
    title='Log Tab Is Non-Empty',
    us_id='US-40',
    description=(
        'The Log tab must show server application log output captured by the '
        '_InMemoryLogHandler buffer — no stdout redirection required. '
        'Clicking the tab fires loadLog() which fetches /api/logs?level=INFO '
        'and renders lines into #log-output via ansiToHtml().'
    ),
)
sys.exit(0 if all_ok else 1)
