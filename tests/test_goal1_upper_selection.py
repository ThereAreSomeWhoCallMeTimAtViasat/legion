#!/usr/bin/env python3
"""
Goal 1: Selected text must survive a refresh in the upper output window.

Two separate executeScript calls with real time between them so the
browser event loop and snapshot poll actually run between selection and check.
"""
import os, sys, time, threading, tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PORT = 5091
IP   = '10.99.99.1'

_SEED = f"""<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22">
      <state state="open"/><service name="ssh"/>
    </port></ports>
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
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}
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
    d.get(srv['url']); time.sleep(2)
    yield d
    d.quit()


def js(d, s, *a): return d.execute_script(s, *a)
def W(d, t=10):   return WebDriverWait(d, t)


def test_upper_selection_survives_snapshot_refresh(drv, srv):
    """
    Functional Goal 1 test.

    CALL A: set selection in dyn-output-* element.
    WAIT:   4 real seconds — snapshot fires twice, renderDynamicToolTabs runs.
    CALL B: verify selection still contains expected text.
    """
    wc = srv['wc']

    # Select the host so dynamic tabs are associated with it
    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(1.0)

    # Run command and wait for Finished
    result = wc.runCommand('echo UPPER_SELECTION_WORD',
                           name='upper-sel', hostIp=IP, run_actions=False)
    pid = result['process_id']

    def _fin(d):
        for r in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            if 'upper-sel' in r.text:
                cells = r.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 6 and cells[5].text.strip() == 'Finished':
                    return r
        return False
    W(drv, 20).until(_fin)
    time.sleep(0.5)  # let snapshot render the dynamic tab button

    # Click the DYNAMIC TAB BUTTON (dyntab-{pid}) in the right-panel tab bar
    # to load the process output into dyn-output-{pid} in the upper panel.
    dyn_btn = W(drv, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#right-tab-bar [data-tab="dyntab-{pid}"]')))
    js(drv, 'arguments[0].click()', dyn_btn)

    # Wait for dyn-output-{pid} to have the expected text
    W(drv, 8).until(lambda d:
        js(d, f"var e=document.getElementById('dyn-output-{pid}');"
               "return e && e.textContent.indexOf('UPPER_SELECTION_WORD') >= 0;"))

    # ── CALL A: set browser selection inside the dyn-output element ──────────
    js(drv, f"""
        var el = document.getElementById('dyn-output-{pid}');
        var r = document.createRange(); r.selectNodeContents(el);
        var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    """)

    sel_before = js(drv, "return window.getSelection().toString()")
    assert 'UPPER_SELECTION_WORD' in sel_before, \
        f"Selection not set before refresh: {sel_before!r}"

    # ── WAIT: real browser time — snapshot fires, renderDynamicToolTabs runs ─
    time.sleep(4)

    # ── CALL B: verify selection survived (completely separate JS call) ───────
    sel_after = js(drv, "return window.getSelection().toString()")
    assert 'UPPER_SELECTION_WORD' in sel_after, \
        (f"GOAL 1 FAILED: selection was destroyed by renderDynamicToolTabs.\n"
         f"  Before refresh: {sel_before!r}\n"
         f"  After  refresh: {sel_after!r}")

    print(f"\nGOAL 1 PASS: selection survived snapshot refresh.\n"
          f"  Before: {sel_before!r}\n  After:  {sel_after!r}")
