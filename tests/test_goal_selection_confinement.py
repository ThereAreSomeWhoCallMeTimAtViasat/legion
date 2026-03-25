#!/usr/bin/env python3
"""
Selection confinement: dragging past an output panel boundary must not select
text from surrounding chrome (toolbar buttons, tab labels, table headers).

How _confineTo() works:
  mousedown inside an output panel → user-select:none on <html> (entire page
  becomes non-selectable) + user-select:text on only the target panel element.
  mouseup → both styles restored.

What these tests prove:
  A) Lower panel (plain-output): drag upward past the top of plain-output into
     the font-size toolbar above it.  The "A−" / "A+" button labels must NOT
     appear in the selection even though the drag endpoint is on them.
  B) Upper panel (dyn-output-{pid}): drag upward past the top of the dynamic
     tab panel into the right-panel tab bar.  The tab-button labels (e.g.
     "Info", "Notes") must NOT appear in the selection.
  C) Positive case: dragging WITHIN a panel must still select the output text.

Tests use ActionChains for real mouse events (isTrusted=true).  The drag is:
  click_and_hold inside the output element → move_by_offset to exit it →
  release → inspect window.getSelection().toString().
"""
import os, sys, time, threading, tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PORT = 5085
IP   = '10.99.99.1'
BASE = f'http://127.0.0.1:{PORT}'

_SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22">
      <state state="open"/><service name="ssh"/></port></ports>
  </host>
</nmaprun>"""


@pytest.fixture(scope="module")
def srv():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)
    from werkzeug.serving import make_server
    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start(); time.sleep(2)
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': BASE}
    httpd.shutdown()


@pytest.fixture(scope="module")
def drv(srv):
    import os as _os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service
    _os.environ.pop('XAUTHORITY', None); _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions(); opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900); d.implicitly_wait(0)
    d.get(BASE); time.sleep(2)
    yield d
    d.quit()


def js(d, s, *a): return d.execute_script(s, *a)
def W(d, t=10):   return WebDriverWait(d, t)


def _run_and_load_lower(drv, wc, cmd, name, word):
    """Run cmd, click the process row so output loads in plain-output, return pid."""
    r = wc.runCommand(cmd, name=name, hostIp=IP, run_actions=False)
    pid = r['process_id']

    def _fin(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            if name in row.text:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() == 'Finished':
                    return row
        return False
    proc_row = W(drv, 20).until(_fin)
    js(drv, 'arguments[0].click()', proc_row)

    W(drv, 8).until(lambda d:
        word in (js(d, "return document.getElementById('plain-output').textContent") or ''))
    time.sleep(0.3)
    return pid


def _run_and_load_upper(drv, wc, cmd, name, word):
    """Run cmd, click its dyntab button so output loads in dyn-output-{pid}."""
    r = wc.runCommand(cmd, name=name, hostIp=IP, run_actions=False)
    pid = r['process_id']

    def _fin(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            if name in row.text:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() == 'Finished':
                    return row
        return False
    W(drv, 20).until(_fin)
    time.sleep(0.5)  # let snapshot render the dyntab button

    dyn_btn = W(drv, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#right-tab-bar [data-tab="dyntab-{pid}"]')))
    js(drv, 'arguments[0].click()', dyn_btn)

    W(drv, 8).until(lambda d:
        word in (js(d, f"var e=document.getElementById('dyn-output-{pid}');"
                       "return e ? e.textContent : ''") or ''))
    time.sleep(0.3)
    return pid


# ─── Sub-test A: lower panel (plain-output) ───────────────────────────────────

def test_lower_panel_drag_confined(drv, srv):
    """
    Drag from inside plain-output upward past its top boundary into the
    font-size toolbar (A− / A+ buttons).  The toolbar labels must NOT appear
    in the selection; the output text must still be selected.

    Layout context:
      #process-output-inline
        [toolbar: "Font"  "A−"  "10"  "A+"]   ← drag endpoint lands here
        #plain-output                           ← drag start point (here)
    """
    wc = srv['wc']

    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    _run_and_load_lower(drv, wc,
        'echo CONFINE_LOWER_WORD_UNIQUE',
        'confine-lower', 'CONFINE_LOWER_WORD_UNIQUE')

    output_el = drv.find_element(By.ID, 'plain-output')
    h = output_el.size['height']

    # Confirm the toolbar exists and has the text we're checking against
    dec_btn = drv.find_element(By.ID, 'output-font-dec')
    assert 'A' in dec_btn.text, f"output-font-dec text unexpected: {dec_btn.text!r}"
    outside_text = dec_btn.text.strip()   # "A−"

    # Confirm the output contains our word before the drag
    assert 'CONFINE_LOWER_WORD_UNIQUE' in (output_el.text or ''), \
        'Output word not in plain-output before drag'

    # ── Real mouse drag: start inside plain-output, exit upward into toolbar ──
    # move_to_element centres the mouse over output_el, then we hold and drag
    # upward by (h/2 + 60) px — enough to clear the element top and land on
    # the toolbar above it.
    ActionChains(drv)\
        .move_to_element(output_el)\
        .click_and_hold()\
        .move_by_offset(0, -(h // 2 + 60))\
        .release()\
        .perform()
    time.sleep(0.3)

    sel = js(drv, "return window.getSelection().toString()") or ''
    print(f'\nSel after lower-panel drag ({len(sel)} chars): {sel[:120]!r}')
    print(f'outside_text (toolbar label): {outside_text!r}')

    # The confinement must prevent the selection from reaching the toolbar
    assert outside_text not in sel, (
        f'LOWER CONFINEMENT FAILED: toolbar label {outside_text!r} appeared '
        f'in selection — user-select:none did not confine the drag.\n'
        f'  Full selection: {sel!r}')

    # Positive check: the output content must still be selected
    assert 'CONFINE_LOWER_WORD_UNIQUE' in sel, (
        f'LOWER CONFINEMENT: output text not selected — drag may have missed '
        f'the element entirely.\n  Full selection: {sel!r}')

    print('LOWER PANEL CONFINEMENT PASS: selection stayed inside plain-output ✓')


# ─── Sub-test B: upper panel (dyn-output-{pid}) ───────────────────────────────

def test_upper_panel_drag_confined(drv, srv):
    """
    Drag from inside dyn-output-{pid} upward past its top into the
    right-panel tab bar (Info / Ports / Scripts / Notes buttons).
    The tab-button labels must NOT appear in the selection.

    Layout context:
      #right-tab-bar  [Info] [Ports] [Scripts] [Notes] …  ← drag endpoint
      #dynamic-tabs-container
        .tab-content
          #dyn-output-{pid}                               ← drag start
    """
    wc = srv['wc']

    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    pid = _run_and_load_upper(drv, wc,
        'echo CONFINE_UPPER_WORD_UNIQUE',
        'confine-upper', 'CONFINE_UPPER_WORD_UNIQUE')

    dyn_el = drv.find_element(By.ID, f'dyn-output-{pid}')
    h = dyn_el.size['height']

    # Grab a tab-bar label to use as the "escaped" marker
    info_btn = drv.find_element(By.CSS_SELECTOR,
        '#right-tab-bar [data-tab="info-right"]')
    outside_text = info_btn.text.strip()   # e.g. "Info"
    assert outside_text, 'Info tab button has no text — test cannot proceed'

    assert 'CONFINE_UPPER_WORD_UNIQUE' in (dyn_el.text or ''), \
        'Output word not in dyn-output before drag'

    # ── Real mouse drag: start inside dyn-output, exit upward into tab bar ────
    ActionChains(drv)\
        .move_to_element(dyn_el)\
        .click_and_hold()\
        .move_by_offset(0, -(h // 2 + 60))\
        .release()\
        .perform()
    time.sleep(0.3)

    sel = js(drv, "return window.getSelection().toString()") or ''
    print(f'\nSel after upper-panel drag ({len(sel)} chars): {sel[:120]!r}')
    print(f'outside_text (tab label): {outside_text!r}')

    assert outside_text not in sel, (
        f'UPPER CONFINEMENT FAILED: tab label {outside_text!r} appeared in '
        f'selection — user-select:none did not confine the drag.\n'
        f'  Full selection: {sel!r}')

    assert 'CONFINE_UPPER_WORD_UNIQUE' in sel, (
        f'UPPER CONFINEMENT: output text not selected — drag may have missed '
        f'the element entirely.\n  Full selection: {sel!r}')

    print('UPPER PANEL CONFINEMENT PASS: selection stayed inside dyn-output ✓')


# ─── Sub-test C: confinement cleans up — normal selection works after drag ────

def test_confinement_restores_on_mouseup(drv, srv):
    """
    After a confined drag (mouseup releases the lock), selecting text outside
    an output panel (e.g. a tab button label) must work normally.
    This confirms _restore() on mouseup removes user-select:none from <html>.
    """
    # Perform a confined drag first so the cleanup path runs
    output_el = drv.find_element(By.ID, 'plain-output')
    ActionChains(drv)\
        .move_to_element(output_el)\
        .click_and_hold()\
        .move_by_offset(0, -80)\
        .release()\
        .perform()
    time.sleep(0.2)

    # After mouseup the confinement must be gone — verify via computed style
    html_user_select = js(drv,
        "return window.getComputedStyle(document.documentElement).userSelect")
    # When restored, userSelect on html should be the browser default ('auto' or 'text'),
    # NOT 'none'.
    assert html_user_select != 'none', (
        f'CONFINEMENT CLEANUP FAILED: html.userSelect is still "none" after mouseup.\n'
        f'  Got: {html_user_select!r}')

    # Also verify the output element itself is restored
    output_user_select = js(drv,
        "return document.getElementById('plain-output').style.userSelect")
    assert output_user_select == '', (
        f'CONFINEMENT CLEANUP FAILED: plain-output.style.userSelect not cleared.\n'
        f'  Got: {output_user_select!r}')

    print('\nCONFINEMENT CLEANUP PASS: user-select styles restored after mouseup ✓')
