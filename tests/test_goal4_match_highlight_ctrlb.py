#!/usr/bin/env python3
"""
Goal 4: Match-highlighted text selected in output window → Ctrl+B → notes
        has the match colour (bold bright-yellow / ansi-fg-bright-yellow span).

Two separate executeScript calls: CALL A sets selection, real browser time
passes, CALL B dispatches Ctrl+B and checks notes.
"""
import os, sys, time, threading, tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PORT = 5088
IP   = '10.99.99.1'

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
    t = threading.Thread(target=app.run,
        kwargs={'host': '127.0.0.1', 'port': PORT,
                'use_reloader': False, 'threaded': True}, daemon=True)
    t.start(); time.sleep(2)
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}


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


def test_goal4_match_highlight_in_notes(drv, srv):
    """
    Run a command that outputs MATCH_WORD, configure match pattern so
    plain-output gets a match-positive span, select all, Ctrl+B, verify
    notes-display has ansi-fg-bright-yellow span (from match-positive CSS).
    """
    import urllib.request, json as _j
    wc = srv['wc']

    # Select host
    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    host_id = js(drv, f"""
        var r = document.querySelector('#hosts-body tr[data-host-ip="{IP}"]');
        return r ? r.dataset.hostId : null;
    """)

    # Clear notes
    if host_id:
        urllib.request.urlopen(urllib.request.Request(
            f'http://127.0.0.1:{PORT}/api/workspace/hosts/{host_id}/note',
            data=_j.dumps({'note': ''}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'))

    # Inject a positive match pattern for MATCH_WORD via JS
    js(drv, """
        if (!window.matchPositive) window.matchPositive = [];
        if (matchPositive.indexOf('MATCH_WORD') < 0)
            matchPositive.push('MATCH_WORD');
    """)

    # Run command that outputs MATCH_WORD
    r = wc.runCommand('echo MATCH_WORD extra_text', name='match-cmd',
                      hostIp=IP, run_actions=False)
    pid = r['process_id']

    def _fin(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            if 'match-cmd' in row.text:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() == 'Finished':
                    return row
        return False
    proc_row = W(drv, 20).until(_fin)
    js(drv, 'arguments[0].click()', proc_row)

    # Wait for plain-output to have the match-positive span
    W(drv, 8).until(lambda d:
        'match-positive' in (js(d, "return document.getElementById('plain-output').innerHTML") or ''))

    out_html = js(drv, "return document.getElementById('plain-output').innerHTML")
    assert 'match-positive' in out_html, \
        f"match-positive span not in plain-output: {out_html[:300]}"
    print(f"\nplain-output has match-positive span ✓")

    # ── CALL A: select all of plain-output ───────────────────────────────────
    js(drv, """
        var el = document.getElementById('plain-output');
        var r = document.createRange(); r.selectNodeContents(el);
        var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    """)
    sel = js(drv, "return window.getSelection().toString()")
    assert 'MATCH_WORD' in sel, f"MATCH_WORD not in selection: {sel!r}"
    print(f"Selection set: {sel[:60]!r}")

    # ── CALL B: dispatch Ctrl+B (separate call, real browser time) ───────────
    js(drv, """
        document.dispatchEvent(new KeyboardEvent('keydown',
            {key:'b', ctrlKey:true, bubbles:true, cancelable:true}));
        window.getSelection().removeAllRanges();
    """)
    time.sleep(0.8)

    # Click Notes tab
    notes_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.4)

    html = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    txt  = js(drv, "return document.getElementById('notes-display').textContent") or ''
    print(f"notes-display snippet: {html[:300]!r}")

    assert 'MATCH_WORD' in txt, f"MATCH_WORD missing from notes: {txt!r}"
    assert 'ansi-fg-bright-yellow' in html, \
        (f"GOAL 4 FAILED: match-positive highlight not in notes.\n"
         f"  Expected ansi-fg-bright-yellow span.\n"
         f"  notes-display: {html[:400]}")

    print("\nGOAL 4 PASS: match highlight preserved in notes ✓")
