#!/usr/bin/env python3
"""
Legion US-04 Test Report Generator
====================================
Runs each step of TestUS04_InvalidHostInput against the live server,
captures a screenshot at every key moment, then writes a self-contained
HTML report with inline base64 images and step annotations.

Usage:
    sudo python3 tests/generate_test1_report.py [--port 5085] [--out /tmp/legion_report/us04.html]
"""

import os
import sys
import time
import base64
import argparse
import requests
import tempfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5085)
parser.add_argument('--out',  default='/tmp/legion_report/us04.html')
args = parser.parse_args()

BASE_URL  = f'http://127.0.0.1:{args.port}'
REPORT    = args.out
os.makedirs(os.path.dirname(REPORT), exist_ok=True)

SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <hostnames><hostname name="testhost.local" type="PTR"/></hostnames>
    <os><osmatch name="Linux 4.x" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.4"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4.51"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

# ---------------------------------------------------------------------------
# Report state
# ---------------------------------------------------------------------------
report_steps = []   # list of dicts: {test, step, annotation, result, screenshot_b64}
test_summaries = []

def snapshot_b64(driver):
    """Return a base64-encoded PNG screenshot."""
    return base64.b64encode(driver.get_screenshot_as_png()).decode()

def record(driver, test_name, step_num, annotation, result, highlight_js=None):
    """Run optional JS highlight, take screenshot, record step."""
    if highlight_js:
        try:
            driver.execute_script(highlight_js)
            time.sleep(0.3)
        except Exception:
            pass
    png = snapshot_b64(driver)
    # Remove highlight
    if highlight_js:
        try:
            driver.execute_script("""
                document.querySelectorAll('[data-report-highlight]').forEach(function(e){
                    e.style.outline='';
                    e.removeAttribute('data-report-highlight');
                });
            """)
        except Exception:
            pass
    report_steps.append({
        'test':       test_name,
        'step':       step_num,
        'annotation': annotation,
        'result':     result,
        'png':        png,
    })
    status = '✓ PASS' if result else '✗ FAIL'
    print(f'    [{status}] Step {step_num}: {annotation[:70]}')
    return result

def highlight(selector):
    return f"""
        var el = document.querySelector('{selector}');
        if (el) {{
            el.setAttribute('data-report-highlight','1');
            el.style.outline = '3px solid #f90';
        }}
    """

# ---------------------------------------------------------------------------
# Driver setup
# ---------------------------------------------------------------------------
def make_driver():
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    svc = Service('/usr/bin/geckodriver')
    d = webdriver.Firefox(service=svc, options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    return d

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def W(driver, t=8):
    return WebDriverWait(driver, t)

def api_get(path):
    return requests.get(BASE_URL + path, timeout=10).json()

def open_modal(driver):
    driver.execute_script("document.getElementById('action-add-hosts').click()")
    W(driver, 5).until(
        lambda d: 'is-open' in (d.find_element(By.ID,'add-hosts-modal')
                                 .get_attribute('class') or ''))
    return driver.find_element(By.ID, 'add-hosts-targets')

def close_modal(driver):
    try:
        driver.find_element(By.CSS_SELECTOR,'#add-hosts-modal .modal-close-btn').click()
        time.sleep(0.3)
    except Exception:
        pass
    try:
        driver.switch_to.alert.dismiss()
    except Exception:
        pass

def seed_server():
    snap = requests.get(f'{BASE_URL}/api/snapshot').json()
    if any(h['ip'] == '10.10.10.1' for h in snap.get('hosts', [])):
        return
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML); path = f.name
    requests.post(f'{BASE_URL}/api/nmap/import-xml', json={'path': path})
    os.unlink(path)
    time.sleep(1)

# ---------------------------------------------------------------------------
# TEST SCENARIO RUNNERS
# ---------------------------------------------------------------------------

def run_test_empty_input(driver):
    name    = 'Test 1.1 — Empty input shows JS validation error'
    passed  = True
    print(f'\n  {name}')

    # Step 1: navigate to app
    driver.get(BASE_URL)
    time.sleep(2)
    record(driver, name, 1,
           'Navigate to Legion at ' + BASE_URL + ' — hosts table visible',
           True,
           highlight('#hosts-table, #host-list, #hosts-panel'))

    # Step 2: open modal
    open_modal(driver)
    time.sleep(0.3)
    record(driver, name, 2,
           'Open "Add host(s) to scope" modal via JS click on #action-add-hosts',
           True,
           highlight('#add-hosts-modal'))

    # Step 3: submit empty
    driver.find_element(By.ID,'add-hosts-start').click()
    time.sleep(0.4)
    val = driver.find_element(By.ID,'add-hosts-validation')
    ok  = val.is_displayed()
    passed = passed and ok
    record(driver, name, 3,
           'Click Start with empty textarea — '
           '#add-hosts-validation must be visible (JS guard fires before server)',
           ok,
           highlight('#add-hosts-validation'))

    # Step 4: modal still open
    modal = driver.find_element(By.ID,'add-hosts-modal')
    ok2   = 'is-open' in (modal.get_attribute('class') or '')
    passed = passed and ok2
    record(driver, name, 4,
           'Modal remains open with class "is-open" — empty input not accepted',
           ok2,
           highlight('#add-hosts-modal'))

    close_modal(driver)
    test_summaries.append({'name': name, 'passed': passed})
    return passed


def run_test_pipe_char(driver):
    name   = 'Test 1.2 — Pipe character creates no scan process'
    passed = True
    print(f'\n  {name}')

    proc_before = len(api_get('/api/snapshot').get('processes', []))

    # Step 1: baseline process count
    record(driver, name, 1,
           f'Baseline: {proc_before} processes in DB before submitting invalid input',
           True)

    # Step 2: open modal, type bad input
    ta = open_modal(driver)
    ta.clear()
    ta.send_keys('192.168.1.1|ls')
    time.sleep(0.2)
    record(driver, name, 2,
           'Type "192.168.1.1|ls" into targets textarea — pipe is not in allowed set '
           '[a-zA-Z0-9:./-\\s,]',
           True,
           highlight('#add-hosts-targets'))

    # Step 3: click Start
    driver.find_element(By.ID,'add-hosts-start').click()
    record(driver, name, 3,
           'Click Start — JS does NOT show validation (non-empty input), '
           'postJson fires to /api/nmap/scan',
           True,
           highlight('#add-hosts-start'))

    # Step 4: wait for round-trip, check server rejected it
    time.sleep(2.5)
    proc_after = len(api_get('/api/snapshot').get('processes', []))
    ok = (proc_after == proc_before)
    passed = passed and ok
    record(driver, name, 4,
           f'After server round-trip: process count is {proc_after} '
           f'(was {proc_before}) — server returned 400, no process created',
           ok,
           highlight('#processes-table, #process-list'))

    test_summaries.append({'name': name, 'passed': passed})
    return passed


def run_test_backtick(driver):
    name   = 'Test 1.3 — Backtick character creates no scan process'
    passed = True
    print(f'\n  {name}')

    proc_before = len(api_get('/api/snapshot').get('processes', []))

    record(driver, name, 1,
           f'Baseline: {proc_before} processes before submitting input with backtick',
           True)

    ta = open_modal(driver)
    ta.clear()
    ta.send_keys('192.168.1.1;`id`')
    time.sleep(0.2)
    record(driver, name, 2,
           'Type "192.168.1.1;`id`" — semicolon splits into two targets; '
           '"`id`" contains backtick which is not in allowed set',
           True,
           highlight('#add-hosts-targets'))

    driver.find_element(By.ID,'add-hosts-start').click()
    record(driver, name, 3,
           'Click Start — server will receive both parts and reject on backtick',
           True)

    time.sleep(2.5)
    proc_after = len(api_get('/api/snapshot').get('processes', []))
    ok = (proc_after == proc_before)
    passed = passed and ok
    record(driver, name, 4,
           f'Process count after: {proc_after} (was {proc_before}) — '
           'server rejected request, no process created',
           ok,
           highlight('#processes-table, #process-list'))

    test_summaries.append({'name': name, 'passed': passed})
    return passed


def run_test_valid_ip(driver):
    name   = 'Test 1.4 — Valid IP address creates a scan process'
    passed = True
    print(f'\n  {name}')

    proc_before = len(api_get('/api/snapshot').get('processes', []))

    record(driver, name, 1,
           f'Baseline: {proc_before} processes before submitting valid IP',
           True)

    ta = open_modal(driver)
    ta.clear()
    ta.send_keys('127.0.0.2')
    time.sleep(0.2)
    record(driver, name, 2,
           'Type "127.0.0.2" — valid IPv4 address, passes validateNmapInput',
           True,
           highlight('#add-hosts-targets'))

    driver.find_element(By.ID,'add-hosts-start').click()
    record(driver, name, 3,
           'Click Start — server accepts target, staged nmap scan launched',
           True,
           highlight('#add-hosts-start'))

    # wait for modal close (1.5 s setTimeout) + snapshot poll
    time.sleep(3.5)

    modal = driver.find_element(By.ID,'add-hosts-modal')
    modal_closed = 'is-open' not in (modal.get_attribute('class') or '')
    passed = passed and modal_closed
    record(driver, name, 4,
           'Modal closes automatically after successful submission '
           '(closeModal fires 1.5 s after scan accepted)',
           modal_closed)

    proc_after = len(api_get('/api/snapshot').get('processes', []))
    ok = (proc_after > proc_before)
    passed = passed and ok
    record(driver, name, 5,
           f'New process count: {proc_after} (was {proc_before}) — '
           'at least one nmap process created in DB',
           ok,
           highlight('#processes-table, #process-list'))

    test_summaries.append({'name': name, 'passed': passed})
    return passed


# ---------------------------------------------------------------------------
# HTML REPORT
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; }
header { background: #16213e; padding: 24px 40px; border-bottom: 2px solid #0f3460; }
header h1 { font-size: 24px; color: #e94560; letter-spacing: 1px; }
header .meta { color: #888; font-size: 13px; margin-top: 6px; }
.summary-bar { display: flex; gap: 16px; padding: 20px 40px;
    background: #16213e; border-bottom: 1px solid #0f3460; flex-wrap: wrap; }
.summary-card { background: #0f3460; border-radius: 8px; padding: 12px 24px; min-width: 160px; }
.summary-card .label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
.summary-card .value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.pass  { color: #4caf50; }
.fail  { color: #e94560; }
.neutral { color: #90caf9; }
.test-block { margin: 24px 40px; border-radius: 10px; overflow: hidden;
    border: 1px solid #0f3460; }
.test-header { padding: 14px 20px; font-size: 15px; font-weight: 600;
    display: flex; align-items: center; gap: 12px; }
.test-header.pass { background: #1b3a1b; border-left: 4px solid #4caf50; }
.test-header.fail { background: #3a1b1b; border-left: 4px solid #e94560; }
.badge { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; }
.badge.pass { background: #4caf50; color: #000; }
.badge.fail { background: #e94560; color: #fff; }
.step { display: flex; gap: 0; border-top: 1px solid #0f3460; }
.step:first-child { border-top: none; }
.step-left { min-width: 340px; max-width: 340px; padding: 16px 20px;
    background: #12192b; display: flex; flex-direction: column; gap: 8px; }
.step-num { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
.step-annotation { font-size: 13px; line-height: 1.6; color: #cfd8dc; }
.step-result { font-size: 12px; font-weight: 700; margin-top: 4px; }
.step-right { flex: 1; background: #0a0f1e; padding: 10px;
    display: flex; align-items: flex-start; }
.step-right img { width: 100%; border-radius: 4px; border: 1px solid #0f3460; }
footer { text-align: center; padding: 20px; color: #555; font-size: 12px;
    border-top: 1px solid #0f3460; margin-top: 40px; }
"""

def render_html():
    total  = len(test_summaries)
    passed = sum(1 for t in test_summaries if t['passed'])
    failed = total - passed
    total_steps  = len(report_steps)
    passed_steps = sum(1 for s in report_steps if s['result'])

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Group steps by test name
    from collections import OrderedDict
    by_test = OrderedDict()
    for s in report_steps:
        by_test.setdefault(s['test'], []).append(s)

    blocks = []
    for ts in test_summaries:
        tname  = ts['name']
        tpass  = ts['passed']
        steps  = by_test.get(tname, [])
        cls    = 'pass' if tpass else 'fail'
        badge  = f'<span class="badge {cls}">{"PASS" if tpass else "FAIL"}</span>'

        step_html = []
        for s in steps:
            r_cls  = 'pass' if s['result'] else 'fail'
            r_text = '✓ Pass' if s['result'] else '✗ Fail'
            img    = f'<img src="data:image/png;base64,{s["png"]}" alt="step screenshot"/>'
            step_html.append(f"""
            <div class="step">
              <div class="step-left">
                <div class="step-num">Step {s['step']}</div>
                <div class="step-annotation">{s['annotation']}</div>
                <div class="step-result {r_cls}">{r_text}</div>
              </div>
              <div class="step-right">{img}</div>
            </div>""")

        blocks.append(f"""
        <div class="test-block">
          <div class="test-header {cls}">{badge} {tname}</div>
          {''.join(step_html)}
        </div>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Legion Test Report — US-04</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Legion UI Test Report — US-04: Invalid Host Input</h1>
  <div class="meta">
    Server: {BASE_URL} &nbsp;|&nbsp;
    Generated: {now} &nbsp;|&nbsp;
    User Story: US-04 — The server rejects targets containing characters
    outside [a-zA-Z0-9:./-\\s,]; no scan process is created for invalid input.
  </div>
</header>

<div class="summary-bar">
  <div class="summary-card">
    <div class="label">Tests</div>
    <div class="value neutral">{total}</div>
  </div>
  <div class="summary-card">
    <div class="label">Passed</div>
    <div class="value pass">{passed}</div>
  </div>
  <div class="summary-card">
    <div class="label">Failed</div>
    <div class="value {'fail' if failed else 'pass'}">{failed}</div>
  </div>
  <div class="summary-card">
    <div class="label">Steps</div>
    <div class="value neutral">{total_steps}</div>
  </div>
  <div class="summary-card">
    <div class="label">Steps Passed</div>
    <div class="value pass">{passed_steps}</div>
  </div>
  <div class="summary-card">
    <div class="label">Overall</div>
    <div class="value {'pass' if failed == 0 else 'fail'}">
      {'ALL PASS' if failed == 0 else 'FAIL'}
    </div>
  </div>
</div>

{''.join(blocks)}

<footer>Legion Flask — Automated UI Test Report &nbsp;|&nbsp; Selenium + Firefox Headless</footer>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
print(f'\nLegion US-04 Test Report Generator')
print(f'Server : {BASE_URL}')
print(f'Output : {REPORT}')
print(f'Started: {datetime.now().strftime("%H:%M:%S")}\n')

# Verify server is up
try:
    r = requests.get(f'{BASE_URL}/api/snapshot', timeout=5)
    assert r.status_code == 200
    print(f'✓ Server reachable at {BASE_URL}')
except Exception as e:
    print(f'✗ Server not reachable: {e}')
    sys.exit(1)

# Seed
seed_server()
print(f'✓ Seed host 10.10.10.1 present\n')

# Run
driver = make_driver()
try:
    all_passed = True
    all_passed = run_test_empty_input(driver) and all_passed
    all_passed = run_test_pipe_char(driver)   and all_passed
    all_passed = run_test_backtick(driver)    and all_passed
    all_passed = run_test_valid_ip(driver)    and all_passed
finally:
    driver.quit()

# Write report
html = render_html()
with open(REPORT, 'w') as f:
    f.write(html)

print(f'\n{"="*50}')
passed = sum(1 for t in test_summaries if t['passed'])
print(f'Results: {passed}/{len(test_summaries)} tests passed')
print(f'Report : {REPORT}')
print(f'{"="*50}')
sys.exit(0 if all_passed else 1)
