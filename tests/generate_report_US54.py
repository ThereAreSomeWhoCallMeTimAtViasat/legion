#!/usr/bin/env python3
"""
US-54 Test Report — Ctrl+F Opens Find Bar Inside Config Manager
===============================================================
Usage:
    sudo python3 tests/generate_report_US54.py [--port 5095]

Verifies US-54: while the Config Manager (F2) is open, pressing Ctrl+F
opens a find/search bar, typing a term highlights matches in the config
textarea, and Escape closes the bar.

Implementation verified:
  - #action-config click → openModal('config-modal') + cfgLoadProfiles()
  - Ctrl+F → document keydown listener checks config-modal.classList.contains('is-open')
             → calls cfgFindShow() → sets #cfg-find-bar display=''; focuses input
  - Typing in #cfg-find-input → cfgFindRun(query) → searches ta.value case-insensitively
             → updates #cfg-find-count to "N / M"; builds <mark> in .cfg-find-overlay
  - Escape in #cfg-find-input → cfgFindHide() → hides bar, clears state

Four scenarios, run in order:
  1. F2 / #action-config click opens Config Manager (modal has is-open class).
  2. Ctrl+F (ActionChains, isTrusted=true) opens #cfg-find-bar.
  3. Typing "nmap" finds matches — #cfg-find-count shows "1 / N", mark present.
  4. Escape closes #cfg-find-bar.
"""

import argparse
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import tests.generate_report as R

# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5095)
args  = parser.parse_args()
R.configure(args.port)
BASE  = R.base_url()


def W(driver, t=8):
    return WebDriverWait(driver, t)


def find_bar_visible(driver):
    """True if #cfg-find-bar is displayed (not display:none)."""
    return driver.execute_script("""
        var bar = document.getElementById('cfg-find-bar');
        if (!bar) return null;
        return bar.style.display !== 'none' &&
               window.getComputedStyle(bar).display !== 'none';
    """)


def config_modal_open(driver):
    return driver.execute_script("""
        var m = document.getElementById('config-modal');
        return m ? m.classList.contains('is-open') : false;
    """)


def textarea_has_content(driver):
    return driver.execute_script("""
        var ta = document.querySelector('#config-editors textarea');
        return ta ? ta.value.length > 0 : false;
    """)


# ---------------------------------------------------------------------------
# Scenario 1 — Config Manager opens on #action-config click
# ---------------------------------------------------------------------------
def run_open_config_manager(driver):
    name = 'Test 1 — Config Manager opens (#action-config click = same as F2)'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Navigated to {BASE}. About to open Config Manager via JS click '
             f'on #action-config (same code path as F2 keydown handler: '
             f'"if e.key===F2 → action-config.click()"). '
             f'Expects: #config-modal gets class is-open; config text loads.',
             True, '#main-menu, #action-config')

    # Open via JS click — same code path as F2
    driver.execute_script("document.getElementById('action-config').click()")
    time.sleep(0.5)

    ok_open = config_modal_open(driver)
    R.record(driver, name, 2,
             f'config-modal.classList.contains("is-open") = {ok_open}. '
             f'cfgLoadProfiles() was called — waiting for textarea content.',
             ok_open,
             '#config-modal')

    # Wait for config content to load into the textarea
    deadline = time.time() + 8
    while time.time() < deadline:
        if textarea_has_content(driver):
            break
        time.sleep(0.3)

    content_len = driver.execute_script("""
        var ta = document.querySelector('#config-editors textarea');
        return ta ? ta.value.length : 0;
    """)
    ok_content = content_len > 0

    R.record(driver, name, 3,
             f'Config textarea content length: {content_len} chars. '
             f'cfgLoadProfiles() fetched /api/settings/legion-conf and '
             f'populated the textarea. Must be > 0 to enable search.',
             ok_content,
             '#config-editors')

    passed = ok_open and ok_content
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 2 — Ctrl+F opens find bar
# ---------------------------------------------------------------------------
def run_ctrlf_opens_findbar(driver):
    name = 'Test 2 — Ctrl+F (ActionChains, isTrusted=true) opens #cfg-find-bar'
    print(f'\n  {name}')

    before_visible = find_bar_visible(driver)
    R.record(driver, name, 1,
             f'Config Manager is open. #cfg-find-bar currently visible: {before_visible} '
             f'(must be False/hidden before Ctrl+F). '
             f'About to press Ctrl+F via ActionChains.',
             before_visible is False,
             '#cfg-find-bar')

    # Focus something inside the modal so ActionChains has a target
    driver.execute_script("""
        var ta = document.querySelector('#config-editors textarea');
        if (ta) ta.focus();
    """)
    time.sleep(0.2)

    # Real Ctrl+F via ActionChains — isTrusted=true
    # Document keydown listener: if config-modal.is-open → cfgFindShow()
    ActionChains(driver).key_down(Keys.CONTROL).send_keys('f') \
                        .key_up(Keys.CONTROL).perform()
    time.sleep(0.4)

    after_visible = find_bar_visible(driver)
    input_focused = driver.execute_script("""
        return document.activeElement &&
               document.activeElement.id === 'cfg-find-input';
    """)

    ok_visible = after_visible is True
    R.record(driver, name, 2,
             f'After Ctrl+F: #cfg-find-bar visible={after_visible} (must be True). '
             f'#cfg-find-input focused={input_focused}. '
             f'cfgFindShow() set bar.style.display="" and called inp.focus().',
             ok_visible,
             '#cfg-find-bar, #cfg-find-input')

    R.finish_test(name, ok_visible)
    return ok_visible


# ---------------------------------------------------------------------------
# Scenario 3 — Typing search term shows match count and mark highlight
# ---------------------------------------------------------------------------
def run_search_term_finds_matches(driver):
    name = 'Test 3 — Typing "nmap" shows match count and <mark> highlight'
    print(f'\n  {name}')

    TERM = 'nmap'

    R.record(driver, name, 1,
             f'Find bar is open. About to type {TERM!r} into #cfg-find-input. '
             f'cfgFindRun() searches ta.value.toLowerCase() for the query. '
             f'"nmap" appears in legion.conf (nmap-path, nmap commands, etc.).',
             True,
             '#cfg-find-input, #cfg-find-count')

    # Type directly — cfgFindInp has 'input' listener calling cfgFindRun
    find_input = driver.find_element(By.ID, 'cfg-find-input')
    find_input.clear()
    find_input.send_keys(TERM)
    time.sleep(0.5)

    count_text = driver.execute_script(
        "return document.getElementById('cfg-find-count').textContent.trim()")
    mark_exists = driver.execute_script("""
        var mark = document.querySelector('#config-editors .cfg-find-overlay mark');
        return mark ? mark.textContent.toLowerCase() : null;
    """)

    # Count text should be "1 / N" where N >= 1
    ok_count = '/' in (count_text or '') and not count_text.startswith('0')
    ok_mark  = mark_exists is not None and TERM in (mark_exists or '')

    R.record(driver, name, 2,
             f'#cfg-find-count text: {count_text!r} (must contain "/" and not start with 0). '
             f'.cfg-find-overlay mark text: {mark_exists!r} (must contain "nmap"). '
             f'cfgFindSelect(0) called cfgFindHighlight() which wrote <mark> to overlay '
             f'and synced overlay.scrollTop = ta.scrollTop.',
             ok_count and ok_mark,
             '#cfg-find-count, #config-editors .cfg-find-overlay')

    passed = ok_count and ok_mark
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Scenario 4 — Escape closes find bar
# ---------------------------------------------------------------------------
def run_escape_closes_findbar(driver):
    name = 'Test 4 — Escape (in #cfg-find-input) closes #cfg-find-bar'
    print(f'\n  {name}')

    R.record(driver, name, 1,
             f'Find bar is open with "nmap" query active. '
             f'About to press Escape — #cfg-find-input keydown listener: '
             f'if e.key==="Escape" → cfgFindHide(). '
             f'cfgFindHide() sets bar.style.display="none", clears query and '
             f'match state, blanks #cfg-find-count, clears overlay.',
             True,
             '#cfg-find-bar, #cfg-find-input')

    find_input = driver.find_element(By.ID, 'cfg-find-input')
    find_input.send_keys(Keys.ESCAPE)
    time.sleep(0.3)

    after_visible = find_bar_visible(driver)
    count_after   = driver.execute_script(
        "return document.getElementById('cfg-find-count').textContent.trim()")
    mark_after = driver.execute_script("""
        var mark = document.querySelector('#config-editors .cfg-find-overlay mark');
        return mark ? mark.textContent : null;
    """)

    ok_hidden    = after_visible is False
    ok_cleared   = count_after == ''
    ok_no_mark   = mark_after is None

    R.record(driver, name, 2,
             f'After Escape: #cfg-find-bar visible={after_visible} (must be False). '
             f'#cfg-find-count text={count_after!r} (must be empty). '
             f'mark element present: {mark_after is not None} (must be None). '
             f'cfgFindHide() cleared all state and hid the bar.',
             ok_hidden and ok_cleared and ok_no_mark,
             '#cfg-find-bar')

    # Close config manager cleanly for test isolation
    driver.execute_script("""
        var btn = document.getElementById('config-close');
        if (btn) btn.click();
    """)
    time.sleep(0.3)

    passed = ok_hidden and ok_cleared and ok_no_mark
    R.finish_test(name, passed)
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f'\nLegion US-54 Report Generator')
print(f'Server : {BASE}')

try:
    requests.get(f'{BASE}/api/snapshot', timeout=5).raise_for_status()
    print('✓ Server reachable')
except Exception as e:
    print(f'✗ Server not reachable: {e}'); sys.exit(1)

driver = R.make_driver()
driver.get(BASE)
time.sleep(2)

try:
    ok1 = run_open_config_manager(driver)
    ok2 = run_ctrlf_opens_findbar(driver)   if ok1 else False
    ok3 = run_search_term_finds_matches(driver) if ok2 else False
    ok4 = run_escape_closes_findbar(driver)     if ok3 else False
    all_passed = ok1 and ok2 and ok3 and ok4
finally:
    driver.quit()

passed = sum(1 for t in R._test_summaries if t['passed'])
print(f'\nResults: {passed}/{len(R._test_summaries)} tests passed')

R.render_and_save(
    title='Config Manager Find Bar (Ctrl+F opens, search highlights, Esc closes)',
    us_id='US-54',
    description=(
        'US-54: While the Config Manager modal is open, Ctrl+F opens a find bar '
        '(#cfg-find-bar). Typing a search term updates #cfg-find-count and creates '
        'a &lt;mark&gt; element in .cfg-find-overlay to highlight the match in the '
        'config textarea. Pressing Escape hides the bar and clears all state. '
        'Ctrl+F is sent via ActionChains (isTrusted=true) so it goes through the '
        'real document keydown listener path, not a synthetic dispatchEvent.'
    ),
)
sys.exit(0 if all_passed else 1)
