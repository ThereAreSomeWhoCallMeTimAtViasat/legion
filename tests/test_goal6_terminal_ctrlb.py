#!/usr/bin/env python3
"""
Goal 6: Ctrl+B from interactive terminal copies text to Notes tab.

Uses ActionChains for Ctrl+B — generates real browser keyboard events
(isTrusted=true) that go through xterm's actual event handling path,
the same as a physical keypress.

Critical detail: focus the xterm input via JS .focus() NOT ActionChains.click().
A click clears the xterm selection; .focus() does not.
"""
import os, sys, time, threading, tempfile
import pytest
import urllib.request, json as _j

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PORT = 5089
IP   = '10.99.99.1'
BASE = f'http://127.0.0.1:{PORT}'

_SEED = f"""<?xml version="1.0"?><nmaprun>
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
    t = threading.Thread(target=app.run,
        kwargs={'host': '127.0.0.1', 'port': PORT,
                'use_reloader': False, 'threaded': True}, daemon=True)
    t.start(); time.sleep(2)
    yield {'url': BASE}


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


def test_goal6_ctrlb_from_interactive_terminal(drv, srv):
    """
    Real keyboard event path:
      1. xterm.selectAll()            [CALL A — separate JS call]
      2. .focus() on xterm textarea   [JS, no click, preserves selection]
      3. ActionChains Ctrl+B          [isTrusted=true, goes through xterm handlers]
      4. Check _savedXtermSel set     [capture-phase listener must have fired]
      5. Check notes-text populated   [CALL B — separate JS call, real browser time]
      6. CVE tab → Notes tab
      7. Note persists                [CALL C]
    """
    # ── Setup ────────────────────────────────────────────────────────────────
    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    host_id = js(drv, f"""
        var r = document.querySelector('#hosts-body tr[data-host-ip="{IP}"]');
        return r ? r.dataset.hostId : null;
    """)
    assert host_id, 'Could not get host_id'

    urllib.request.urlopen(urllib.request.Request(
        f'{BASE}/api/workspace/hosts/{host_id}/note',
        data=_j.dumps({'note': ''}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST'))

    # ── Start terminal ────────────────────────────────────────────────────────
    resp = _j.loads(urllib.request.urlopen(urllib.request.Request(
        f'{BASE}/api/terminal/start',
        data=_j.dumps({'label': 'goal6-term', 'host_ip': IP,
                       'command': None}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')).read())
    session_id = resp.get('session_id')
    assert session_id, f'No session_id: {resp}'

    time.sleep(1.5)

    urllib.request.urlopen(urllib.request.Request(
        f'{BASE}/api/terminal/{session_id}/input',
        data=_j.dumps({'data': 'echo -e "\\033[32mGREEN_TERM_TEXT\\033[0m"\n'}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST'))
    time.sleep(1.5)

    buf = _j.loads(urllib.request.urlopen(
        f'{BASE}/api/terminal/{session_id}/output').read()).get('data', '')
    assert 'GREEN_TERM_TEXT' in buf, f'Not in terminal: {buf[:200]}'

    def _find_interactive(d):
        for r in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            cells = r.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 5 and cells[4].text.strip() == 'Interactive':
                return r
        return False
    js(drv, 'arguments[0].click()', W(drv, 10).until(_find_interactive))
    time.sleep(1.5)

    assert js(drv, "return typeof _termState!=='undefined' && _termState.xterm!==null"), \
        'xterm not initialised'

    # ── CALL A: select all terminal content ───────────────────────────────────
    sel_text = js(drv, """
        _termState.xterm.selectAll();
        return _termState.xterm.getSelection() || '';
    """)
    assert sel_text.strip(), 'xterm.selectAll() produced empty selection'
    print(f'\nxterm selection ({len(sel_text)} chars): {sel_text[:60]!r}')

    # ── Focus xterm via JS (NOT click — click clears the selection) ───────────
    xterm_textarea = None
    for sel in ['#terminal-output .xterm-helper-textarea',
                '#terminal-output textarea']:
        try:
            xterm_textarea = drv.find_element(By.CSS_SELECTOR, sel)
            break
        except Exception:
            pass
    assert xterm_textarea, 'xterm-helper-textarea not found'

    # JS .focus() does not send mouse events — selection stays intact
    js(drv, 'arguments[0].focus()', xterm_textarea)
    time.sleep(0.1)

    # Confirm selection still present after focus (not cleared by click)
    sel_after_focus = js(drv, "return _termState.xterm.getSelection() || ''")
    assert sel_after_focus.strip(), \
        f'Selection cleared by .focus() — got: {sel_after_focus!r}'
    print(f'Selection after .focus(): still set ✓')

    # ── ActionChains Ctrl+B — isTrusted=true, real browser keyboard events ────
    # Goes through: document capture (our listener) → xterm handler → document bubble
    ActionChains(drv).key_down(Keys.CONTROL).send_keys('b') \
                     .key_up(Keys.CONTROL).perform()
    time.sleep(1.0)

    saved = js(drv, "return typeof _savedXtermSel!=='undefined' ? (_savedXtermSel||'EMPTY') : 'UNDEFINED'")
    print(f'_savedXtermSel: {saved[:60]!r}')

    # ── CALL B ────────────────────────────────────────────────────────────────
    notes_raw = js(drv, "return document.getElementById('notes-text').value") or ''
    print(f'notes-text ({len(notes_raw)} chars): {notes_raw[:80]!r}')

    assert notes_raw.strip(), (
        f'GOAL 6 FAILED: notes empty after real Ctrl+B.\n'
        f'  xterm sel:       {sel_text[:60]!r}\n'
        f'  after .focus():  {sel_after_focus[:60]!r}\n'
        f'  _savedXtermSel:  {saved[:60]!r}')

    # ── Notes tab → check display ─────────────────────────────────────────────
    notes_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.5)
    html1 = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert html1.strip() not in ('', '\u200b'), f'notes-display empty: {html1[:200]}'
    print('Note visible in Notes tab ✓')

    # ── CVE tab → Notes tab (persistence) ─────────────────────────────────────
    cve_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="cves-right"]')))
    js(drv, 'arguments[0].click()', cve_btn)
    time.sleep(2)
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.5)

    html2 = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert html2.strip() not in ('', '\u200b'), (
        f'GOAL 6 FAILED: note lost after CVE→Notes.\n'
        f'  Before: {html1[:200]}\n  After: {html2[:200]}')

    print(f'\nGOAL 6 PASS: note present and persistent.')
