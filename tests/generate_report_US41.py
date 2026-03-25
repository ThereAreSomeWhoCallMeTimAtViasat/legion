#!/usr/bin/env python3
"""US-41 Report — Log level INFO→DEBUG increases line count.
Usage: sudo python3 tests/generate_report_US41.py [--port 5085]
"""
import argparse, os, sys, time
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
import tests.generate_report as R

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5085)
args = parser.parse_args()
R.configure(args.port)
BASE = R.base_url()


def api(path):
    return requests.get(BASE + path).json()


def open_log_tab(driver):
    btn = driver.find_element(By.CSS_SELECTOR,
                              '#bottom-tab-bar [data-tab="log-panel"]')
    driver.execute_script('arguments[0].click()', btn)
    WebDriverWait(driver, 8).until(
        lambda d: bool(d.find_element(By.ID, 'log-output')
                        .get_attribute('innerHTML').strip()))


# ---------------------------------------------------------------------------
def run_api_totals(driver):
    name = 'Test 1 — API total: DEBUG greater than INFO (more lines at DEBUG)'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)

    info_d  = api('/api/logs?level=INFO')
    debug_d = api('/api/logs?level=DEBUG')
    info_t  = info_d.get('total', 0)
    debug_t = debug_d.get('total', 0)
    ok      = debug_t > info_t
    passed  = ok

    R.record(driver, name, 1,
             f'API call: /api/logs?level=INFO  → total={info_t} lines. '
             f'INFO level filters to WARNING/ERROR/CRITICAL/INFO only.',
             True)

    R.record(driver, name, 2,
             f'API call: /api/logs?level=DEBUG → total={debug_t} lines. '
             f'DEBUG includes all INFO lines PLUS snapshot/queue debug entries. '
             f'Snapshot polling (every 1.5 s) is logged at DEBUG since v10.2. '
             f'debug({debug_t}) > info({info_t}): {ok}.',
             ok)

    R.finish_test(name, passed)
    return passed


def run_content_changes(driver):
    name = 'Test 2 — UI content changes when switching selector from INFO to DEBUG'
    passed = True
    print(f'\n  {name}')

    open_log_tab(driver)
    time.sleep(1.0)

    info_html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
    R.record(driver, name, 1,
             f'Log tab open at INFO level. '
             f'#log-output shows last 500 INFO-level lines '
             f'(innerHTML length={len(info_html)} chars).',
             bool(info_html.strip()), '#log-output')

    Select(driver.find_element(By.ID, 'log-level')).select_by_value('DEBUG')
    R.record(driver, name, 2,
             'Changed #log-level select to "DEBUG (all)". '
             'The change event fires loadLog() → fetches /api/logs?level=DEBUG → '
             're-renders #log-output with the last 500 DEBUG lines.',
             True, '#log-level')

    time.sleep(2.5)
    debug_html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
    ok_filled  = bool(debug_html.strip())
    ok_changed = info_html != debug_html
    ok_all     = ok_filled and ok_changed
    passed     = ok_all

    R.record(driver, name, 3,
             f'#log-output at DEBUG level '
             f'(innerHTML length={len(debug_html)} chars). '
             f'Content must differ from INFO — the last 500 DEBUG lines '
             f'are a different set (includes debug-only snapshot/queue entries). '
             f'non_empty={ok_filled} | content_changed={ok_changed}.',
             ok_all, '#log-output')

    R.finish_test(name, passed)
    return passed


def run_count_present(driver):
    name = 'Test 3 — #log-line-count still shows N lines after switching to DEBUG'
    passed = True
    print(f'\n  {name}')

    open_log_tab(driver)
    time.sleep(0.5)
    Select(driver.find_element(By.ID, 'log-level')).select_by_value('DEBUG')
    time.sleep(2.0)

    text   = driver.find_element(By.ID, 'log-line-count').text.strip()
    ok_lbl = 'lines' in text
    count  = int(text.split()[0]) if text.split() and text.split()[0].isdigit() else 0
    ok_pos = count > 0
    ok     = ok_lbl and ok_pos
    passed = ok

    R.record(driver, name, 1,
             f'#log-line-count after DEBUG switch: {text!r}. '
             f'loadLog() always updates this via '
             f'setText("log-line-count", lines.length + " lines"). '
             f'has_label={ok_lbl} | count={count} | positive={ok_pos}.',
             ok, '#log-line-count')

    R.finish_test(name, passed)
    return passed


print(f'\nLegion US-41 Report Generator | Server: {BASE}')
try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ {e}'); sys.exit(1)

driver = R.make_driver()
try:
    all_ok = run_api_totals(driver)
    all_ok = run_content_changes(driver) and all_ok
    all_ok = run_count_present(driver)   and all_ok
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} passed')
R.render_and_save(
    title='Log Level INFO→DEBUG Increases Line Count',
    us_id='US-41',
    description=(
        'Switching the #log-level selector from INFO to DEBUG (all) must cause '
        'more log lines to be shown. Snapshot polling is logged at DEBUG '
        'so the DEBUG total always exceeds the INFO total. '
        'The last-500 set also differs between levels.'
    ),
)
sys.exit(0 if all_ok else 1)
