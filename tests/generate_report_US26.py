#!/usr/bin/env python3
"""
US-26 Test Report — Lower Panel Font Size Control
==================================================
Usage:
    sudo python3 tests/generate_report_US26.py [--port 5095]

Verifies US-26: clicking A+ in the LOWER PANEL toolbar increases the font
size of #process-output-inline (lower output panel) WITHOUT changing the
font size of #dynamic-tabs-container (upper panel).

Button IDs (index.html line 351-353):
    #output-font-inc  — increases lower panel font
    #output-font-dec  — decreases lower panel font (used for cleanup)

Target containers:
    #process-output-inline   — lower panel (font size must change)
    #dynamic-tabs-container  — upper panel (font size must NOT change)

Three scenarios:
    1. Initial state — capture both panel font sizes.
    2. Click A+ once — lower panel grows; upper panel unchanged.
    3. Click A+ again — lower panel grows again; upper still unchanged.
    Cleanup: click A− twice to restore original.
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
        f.write(SEED_XML); path = f.name
    requests.post(f'{BASE}/api/nmap/import-xml', json={'path': path})
    time.sleep(1.5)
    os.unlink(path)


def select_host(driver):
    driver.execute_script(f"""
        var row = document.querySelector(
            '#hosts-body tr[data-host-ip="{HOST_IP}"]');
        if (row) row.click();
    """)
    time.sleep(1.0)


def get_font_px(driver, element_id):
    return driver.execute_script(f"""
        var el = document.getElementById('{element_id}');
        if (!el) return null;
        return parseFloat(window.getComputedStyle(el).fontSize);
    """)


def get_lower_label(driver):
    return driver.execute_script(
        "var el = document.getElementById('output-font-label');"
        "return el ? el.textContent.trim() : null;")


def click_lower_inc(driver):
    driver.execute_script("document.getElementById('output-font-inc').click()")
    time.sleep(0.3)


def click_lower_dec(driver):
    driver.execute_script("document.getElementById('output-font-dec').click()")
    time.sleep(0.3)


# ---------------------------------------------------------------------------
def run_initial_state(driver):
    name = 'Test 1 — Initial font sizes captured before any button click'
    print(f'\n  {name}')

    driver.get(BASE)
    time.sleep(2)
    select_host(driver)

    upper_px = get_font_px(driver, 'dynamic-tabs-container')
    lower_px = get_font_px(driver, 'process-output-inline')
    label    = get_lower_label(driver)

    ok = (upper_px is not None and upper_px > 0 and
          lower_px is not None and lower_px > 0)

    R.record(driver, name, 1,
             f'Page loaded. Host {HOST_IP} selected. '
             f'Upper (#dynamic-tabs-container): {upper_px}px. '
             f'Lower (#process-output-inline): {lower_px}px. '
             f'Lower font label: {label}pt.',
             ok,
             '#process-output-inline, #dynamic-tabs-container')

    R.finish_test(name, ok)
    return ok, upper_px, lower_px


def run_one_click(driver, upper_before, lower_before):
    name = 'Test 2 — One click of A+ increases lower font; upper panel unchanged'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Before click: lower={lower_before}px, upper={upper_before}px. '
             f'About to click #output-font-inc (lower panel A+ button).',
             True,
             '#output-font-inc')

    click_lower_inc(driver)

    lower_after = get_font_px(driver, 'process-output-inline')
    upper_after = get_font_px(driver, 'dynamic-tabs-container')
    label_after = get_lower_label(driver)

    ok_lower_grew = lower_after is not None and lower_after > lower_before
    ok_upper_same = abs((upper_after or 0) - upper_before) < 1.0
    passed        = ok_lower_grew and ok_upper_same

    R.record(driver, name, 2,
             f'After one A+ click: lower={lower_after}px (was {lower_before}px, '
             f'{"↑ GREW" if ok_lower_grew else "✗ DID NOT GROW"}), '
             f'upper={upper_after}px (was {upper_before}px, '
             f'{"✓ UNCHANGED" if ok_upper_same else "✗ CHANGED — FAIL"}). '
             f'Lower label: {label_after}pt.',
             passed,
             '#process-output-inline, #dynamic-tabs-container')

    R.finish_test(name, passed)
    return passed, lower_after, upper_after


def run_second_click(driver, lower_before, upper_original):
    name = 'Test 3 — Second A+ click increases lower further; upper still unchanged'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Before second click: lower={lower_before}px. '
             f'Clicking #output-font-inc again.',
             True,
             '#output-font-inc')

    click_lower_inc(driver)

    lower_after = get_font_px(driver, 'process-output-inline')
    upper_after = get_font_px(driver, 'dynamic-tabs-container')
    label_after = get_lower_label(driver)

    ok_lower_grew = lower_after is not None and lower_after > lower_before
    ok_upper_same = abs((upper_after or 0) - upper_original) < 1.0
    passed        = ok_lower_grew and ok_upper_same

    R.record(driver, name, 2,
             f'After second A+ click: lower={lower_after}px (was {lower_before}px, '
             f'{"↑ GREW" if ok_lower_grew else "✗ DID NOT GROW"}). '
             f'Upper={upper_after}px (original {upper_original}px, '
             f'{"✓ STILL UNCHANGED" if ok_upper_same else "✗ CHANGED — FAIL"}). '
             f'Lower label: {label_after}pt.',
             passed,
             '#process-output-inline, #dynamic-tabs-container')

    # Restore
    click_lower_dec(driver)
    click_lower_dec(driver)
    lower_restored = get_font_px(driver, 'process-output-inline')

    R.record(driver, name, 3,
             f'Cleanup: clicked A− twice. Lower now {lower_restored}px.',
             True,
             '#output-font-dec')

    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
print(f'\nLegion US-26 Report Generator')
print(f'Server : {BASE}')
print(f'US-26  : Lower panel A+ increases font; upper panel unchanged')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable: {e}'); sys.exit(1)

seed_server()
print('✓ Seed host present')

driver = R.make_driver()
try:
    ok1, upper0, lower0 = run_initial_state(driver)
    ok2, lower1, upper1 = run_one_click(driver, upper0, lower0)
    ok3                  = run_second_click(driver, lower1, upper0)
    all_passed           = ok1 and ok2 and ok3
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Lower Panel Font Size Control (A+ / A−)',
    us_id='US-26',
    description=(
        'Clicking A+ in the lower panel toolbar must increase the font size of '
        '#process-output-inline (lower output panel) without changing the font '
        'size of #dynamic-tabs-container (upper panel). '
        'Font sizes measured via window.getComputedStyle().fontSize in pixels. '
        'Buttons: #output-font-inc / #output-font-dec (index.html line 351-353).'
    ),
)
sys.exit(0 if all_passed else 1)
