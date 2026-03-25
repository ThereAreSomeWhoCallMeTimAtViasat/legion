#!/usr/bin/env python3
"""US-42 Report — Log tab renders ANSI codes as coloured spans.
Usage: sudo python3 tests/generate_report_US42.py [--port 5085]
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


def open_log_tab(driver):
    btn = driver.find_element(By.CSS_SELECTOR,
                              '#bottom-tab-bar [data-tab="log-panel"]')
    driver.execute_script('arguments[0].click()', btn)
    WebDriverWait(driver, 8).until(
        lambda d: bool(d.find_element(By.ID, 'log-output')
                        .get_attribute('innerHTML').strip()))


# ---------------------------------------------------------------------------
def run_spans_present(driver):
    name = 'Test 1 — #log-output contains <span elements (ANSI → HTML spans)'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)
    open_log_tab(driver)
    time.sleep(0.5)
    R.record(driver, name, 1,
             'Log tab open. log output div (#log-output) is now populated. '
             'ansiToHtml() was called on the raw ANSI lines from _InMemoryLogHandler.',
             True, '#log-output')

    html = driver.find_element(By.ID, 'log-output').get_attribute('innerHTML')
    ok   = '<span' in html
    passed = ok

    # Highlight a span inside log-output by injecting a border
    try:
        driver.execute_script("""
            var span = document.querySelector('#log-output span');
            if (span) {
                span.dataset._rhlsave = span.style.outline;
                span.style.outline = '2px solid #f90';
            }
        """)
        time.sleep(0.25)
    except Exception:
        pass

    R.record(driver, name, 2,
             f'#log-output innerHTML {"contains" if ok else "does NOT contain"} '
             f'<span elements. ansiToHtml() converts ANSI codes like \\x1b[34m '
             f'(blue) to <span class="ansi-fg-blue">. '
             f'Orange outline on first span (if present).',
             ok, '#log-output')

    try:
        driver.execute_script("""
            var span = document.querySelector('#log-output span');
            if (span && span.dataset._rhlsave !== undefined) {
                span.style.outline = span.dataset._rhlsave;
                delete span.dataset._rhlsave;
            }
        """)
    except Exception:
        pass

    R.finish_test(name, passed)
    return passed


def run_no_raw_ansi(driver):
    name = 'Test 2 — #log-output has NO raw \\x1b[ escape sequences'
    passed = True
    print(f'\n  {name}')

    open_log_tab(driver)
    time.sleep(0.5)

    # Use JS to get innerHTML as a string — avoids Python string decode issues
    html   = driver.execute_script(
        "return document.getElementById('log-output').innerHTML")
    ok_esc = '\x1b[' not in html
    ok_esc2 = 'ESC[' not in html
    ok = ok_esc and ok_esc2
    passed = ok

    R.record(driver, name, 1,
             f'#log-output innerHTML checked for raw ANSI escape sequences. '
             f'No \\x1b[ (ESC + left-bracket): {ok_esc}. '
             f'No literal "ESC[": {ok_esc2}. '
             f'ansiToHtml() strips all ANSI codes — either converting them to '
             f'spans or discarding reset/unknown codes.',
             ok, '#log-output')

    R.finish_test(name, passed)
    return passed


def run_ansi_classes(driver):
    name = 'Test 3 — #log-output has ansi-fg-* or ansi-bold CSS classes'
    passed = True
    print(f'\n  {name}')

    open_log_tab(driver)
    time.sleep(0.5)

    html      = driver.execute_script(
        "return document.getElementById('log-output').innerHTML")
    has_fg    = 'ansi-fg-' in html
    has_bold  = 'ansi-bold' in html

    # Count distinct class names present
    import re
    classes_found = sorted(set(re.findall(r'ansi-(?:fg|bg|bold)[a-z-]*', html)))

    ok     = has_fg or has_bold
    passed = ok

    # Highlight first coloured span
    try:
        driver.execute_script("""
            var span = document.querySelector('#log-output [class*="ansi-fg-"]')
                    || document.querySelector('#log-output [class*="ansi-bold"]');
            if (span) {
                span.dataset._rhlsave = span.style.outline;
                span.style.outline = '2px solid #f90';
            }
        """)
        time.sleep(0.25)
    except Exception:
        pass

    R.record(driver, name, 1,
             f'CSS classes found in #log-output: {classes_found}. '
             f'has ansi-fg-*: {has_fg} | has ansi-bold: {has_bold}. '
             f'These classes are produced by ansiToHtml() for codes like '
             f'\\x1b[34m (ansi-fg-blue), \\x1b[1m (ansi-bold), '
             f'\\x1b[32m (ansi-fg-green). Orange outline on first coloured span.',
             ok, '#log-output')

    try:
        driver.execute_script("""
            var span = document.querySelector('#log-output [class*="ansi-fg-"]')
                    || document.querySelector('#log-output [class*="ansi-bold"]');
            if (span && span.dataset._rhlsave !== undefined) {
                span.style.outline = span.dataset._rhlsave;
                delete span.dataset._rhlsave;
            }
        """)
    except Exception:
        pass

    R.finish_test(name, passed)
    return passed


print(f'\nLegion US-42 Report Generator | Server: {BASE}')
try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ {e}'); sys.exit(1)

driver = R.make_driver()
try:
    all_ok = run_spans_present(driver)
    all_ok = run_no_raw_ansi(driver) and all_ok
    all_ok = run_ansi_classes(driver) and all_ok
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} passed')
R.render_and_save(
    title='Log Tab Renders ANSI Codes as Coloured Spans',
    us_id='US-42',
    description=(
        'Log lines from _InMemoryLogHandler contain ANSI escape sequences '
        '(e.g. \\x1b[34m for blue, \\x1b[1m for bold). '
        'ansiToHtml() in legion.js converts these to '
        '<span class="ansi-fg-blue"> etc. '
        'Raw escape codes must not appear in the rendered output.'
    ),
)
sys.exit(0 if all_ok else 1)
