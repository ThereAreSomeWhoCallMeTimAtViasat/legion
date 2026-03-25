#!/usr/bin/env python3
"""
US-25 Test Report — Upper Panel Font Size Control
==================================================
Usage:
    sudo python3 tests/generate_report_US25.py [--port 5095]

Verifies US-25: clicking A+ in the RIGHT-PANEL TAB BAR increases the font
size of #dynamic-tabs-container (upper output panel) WITHOUT changing the
font size of #process-output-inline (lower output panel).

Button IDs (index.html line 95-97):
    #upper-font-inc  — increases upper panel font
    #upper-font-dec  — decreases upper panel font (used for cleanup)

Target containers:
    #dynamic-tabs-container  — upper panel (font size must change)
    #process-output-inline   — lower panel (font size must NOT change)

Three scenarios:
    1. Initial state captured — both panels have their current font sizes.
    2. Click A+ once — upper panel font increases; lower panel unchanged.
    3. Click A+ again — upper panel increases again; lower panel still unchanged.
    Cleanup: click A− twice to restore the original font size.
"""

import argparse
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import requests
import tempfile
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import tests.generate_report as R

# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5095)
args  = parser.parse_args()
R.configure(args.port)
BASE  = R.base_url()

# ---------------------------------------------------------------------------
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
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4.51"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


def seed_server():
    snap = requests.get(f'{BASE}/api/snapshot').json()
    if any(h['ip'] == HOST_IP for h in snap.get('hosts', [])):
        return
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML)
        path = f.name
    requests.post(f'{BASE}/api/nmap/import-xml', json={'path': path})
    time.sleep(1.5)
    os.unlink(path)


def select_host(driver):
    """Click the seed host row so the right panel becomes active."""
    driver.execute_script(f"""
        var row = document.querySelector(
            '#hosts-body tr[data-host-ip="{HOST_IP}"]');
        if (row) row.click();
    """)
    time.sleep(1.0)


def get_font_px(driver, element_id):
    """Return computed font-size in px as a float for the given element ID."""
    return driver.execute_script(f"""
        var el = document.getElementById('{element_id}');
        if (!el) return null;
        return parseFloat(window.getComputedStyle(el).fontSize);
    """)


def get_font_label(driver):
    """Return the text of #upper-font-label (the displayed pt value)."""
    return driver.execute_script(
        "var el = document.getElementById('upper-font-label');"
        "return el ? el.textContent.trim() : null;")


def click_upper_inc(driver):
    driver.execute_script(
        "document.getElementById('upper-font-inc').click()")
    time.sleep(0.3)


def click_upper_dec(driver):
    driver.execute_script(
        "document.getElementById('upper-font-dec').click()")
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# Scenario 1 — capture initial state
# ---------------------------------------------------------------------------
def run_initial_state(driver):
    name   = 'Test 1 — Initial font sizes captured before any button click'
    passed = True
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)
    select_host(driver)

    upper_px = get_font_px(driver, 'dynamic-tabs-container')
    lower_px = get_font_px(driver, 'process-output-inline')
    label    = get_font_label(driver)

    ok_upper = upper_px is not None and upper_px > 0
    ok_lower = lower_px is not None and lower_px > 0
    passed   = ok_upper and ok_lower

    R.record(driver, name, 1,
             f'Page loaded at {BASE}. Host {HOST_IP} selected — right panel active. '
             f'Upper panel (#dynamic-tabs-container) font-size: {upper_px}px. '
             f'Lower panel (#process-output-inline) font-size: {lower_px}px. '
             f'Upper font label shows: {label}pt.',
             passed,
             '#dynamic-tabs-container, #process-output-inline')

    R.finish_test(name, passed)
    # Return sizes for subsequent tests
    return passed, upper_px, lower_px


# ---------------------------------------------------------------------------
# Scenario 2 — click A+ once; upper increases, lower unchanged
# ---------------------------------------------------------------------------
def run_one_click(driver, upper_before, lower_before):
    name   = 'Test 2 — One click of A+ increases upper font; lower panel unchanged'
    passed = True
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Before click: upper={upper_before}px, lower={lower_before}px. '
             f'About to click #upper-font-inc once.',
             True,
             '#upper-font-inc')

    click_upper_inc(driver)
    time.sleep(0.3)

    upper_after = get_font_px(driver, 'dynamic-tabs-container')
    lower_after = get_font_px(driver, 'process-output-inline')
    label_after = get_font_label(driver)

    ok_upper_grew    = upper_after is not None and upper_after > upper_before
    ok_lower_same    = abs((lower_after or 0) - lower_before) < 1.0  # unchanged
    passed           = ok_upper_grew and ok_lower_same

    R.record(driver, name, 2,
             f'After one A+ click: upper={upper_after}px (was {upper_before}px, '
             f'{"↑ GREW" if ok_upper_grew else "✗ DID NOT GROW"}), '
             f'lower={lower_after}px (was {lower_before}px, '
             f'{"✓ UNCHANGED" if ok_lower_same else "✗ CHANGED — FAIL"}). '
             f'Upper label now: {label_after}pt.',
             passed,
             '#dynamic-tabs-container, #process-output-inline')

    R.finish_test(name, passed)
    return passed, upper_after, lower_after


# ---------------------------------------------------------------------------
# Scenario 3 — click A+ again; upper increases again, lower still unchanged
# ---------------------------------------------------------------------------
def run_second_click(driver, upper_before, lower_original):
    name   = 'Test 3 — Second A+ click increases upper further; lower still unchanged'
    passed = True
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Before second click: upper={upper_before}px. '
             f'Clicking #upper-font-inc again.',
             True,
             '#upper-font-inc')

    click_upper_inc(driver)
    time.sleep(0.3)

    upper_after = get_font_px(driver, 'dynamic-tabs-container')
    lower_after = get_font_px(driver, 'process-output-inline')
    label_after = get_font_label(driver)

    ok_upper_grew = upper_after is not None and upper_after > upper_before
    ok_lower_same = abs((lower_after or 0) - lower_original) < 1.0
    passed        = ok_upper_grew and ok_lower_same

    R.record(driver, name, 2,
             f'After second A+ click: upper={upper_after}px (was {upper_before}px, '
             f'{"↑ GREW" if ok_upper_grew else "✗ DID NOT GROW"}). '
             f'Lower={lower_after}px (original {lower_original}px, '
             f'{"✓ STILL UNCHANGED" if ok_lower_same else "✗ CHANGED — FAIL"}). '
             f'Upper label: {label_after}pt.',
             passed,
             '#dynamic-tabs-container, #process-output-inline')

    # Restore original state — click A− twice
    click_upper_dec(driver)
    click_upper_dec(driver)
    upper_restored = get_font_px(driver, 'dynamic-tabs-container')

    ok_restored = abs((upper_restored or 0) - (upper_before - (upper_after - upper_before))) < 2.0
    R.record(driver, name, 3,
             f'Cleanup: clicked A− twice to restore original size. '
             f'Upper now {upper_restored}px.',
             True,   # cleanup is informational, not a pass/fail assertion
             '#upper-font-dec')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-25 Report Generator')
print(f'Server : {BASE}')
print(f'US-25  : Upper panel A+ increases font; lower panel unchanged')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable at {BASE}\n'
          f'  Start it: sudo python3 legion.py --web --port {args.port} &\n'
          f'  Error: {e}')
    sys.exit(1)

seed_server()
print('✓ Seed host present')

driver = R.make_driver()
try:
    all_passed = True

    ok1, upper0, lower0 = run_initial_state(driver)
    all_passed = all_passed and ok1

    ok2, upper1, lower1 = run_one_click(driver, upper0, lower0)
    all_passed = all_passed and ok2

    ok3 = run_second_click(driver, upper1, lower0)
    all_passed = all_passed and ok3

finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Upper Panel Font Size Control (A+ / A−)',
    us_id='US-25',
    description=(
        'Clicking A+ in the right-panel tab bar must increase the font size of '
        '#dynamic-tabs-container (upper output panel) without changing the font '
        'size of #process-output-inline (lower output panel). '
        'Font sizes are measured via window.getComputedStyle().fontSize in pixels '
        'before and after each button click. '
        'Buttons: #upper-font-inc / #upper-font-dec (index.html line 95-97).'
    ),
)
sys.exit(0 if all_passed else 1)
