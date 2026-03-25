#!/usr/bin/env python3
"""
Goal 6: Ctrl+B from interactive terminal copies text to Notes tab.

Key insight from test run: ActionChains.click(xterm_input) before key dispatch
clears the xterm selection. Fix: dispatch the keydown directly on the xterm
element (no preceding click) so selection is intact when our capture-phase
listener saves it.

Steps:
  1. Open interactive terminal, run coloured command
  2. xterm.selectAll() — select all terminal content  [CALL A]
  3. Dispatch Ctrl+B on xterm element (no click) so capture-phase fires first
  4. notes-text must be non-empty                     [CALL B]
  5. Notes tab visible — check notes-display
  6. Click CVE tab
  7. Click Notes tab back — note must persist         [CALL C]
"""
import os, sys, time, threading, tempfile
import pytest
import urllib.request, json as _j

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
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
    # ── Select host ──────────────────────────────────────────────────────────
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

    # ── Start interactive terminal ────────────────────────────────────────────
    resp = _j.loads(urllib.request.urlopen(urllib.request.Request(
        f'{BASE}/api/terminal/start',
        data=_j.dumps({'label': 'goal6-term', 'host_ip': IP,
                       'command': None}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')).read())
    session_id = resp.get('session_id')
    assert session_id, f'No session_id: {resp}'

    time.sleep(1.5)

    # Write coloured command
    urllib.request.urlopen(urllib.request.Request(
        f'{BASE}/api/terminal/{session_id}/input',
        data=_j.dumps({'data': 'echo -e "\\033[32mGREEN_TERM_TEXT\\033[0m"\n'}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST'))
    time.sleep(1.5)

    buf = _j.loads(urllib.request.urlopen(
        f'{BASE}/api/terminal/{session_id}/output').read()).get('data', '')
    assert 'GREEN_TERM_TEXT' in buf, f'GREEN_TERM_TEXT not in terminal: {buf[:200]}'

    # ── Click Interactive process row → xterm renders in page ─────────────────
    def _find_interactive(d):
        for r in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            cells = r.find_elements(By.TAG_NAME, 'td')
            if len(cells) >= 5 and cells[4].text.strip() == 'Interactive':
                return r
        return False
    proc_row = W(drv, 10).until(_find_interactive)
    js(drv, 'arguments[0].click()', proc_row)
    time.sleep(1.5)

    xterm_ready = js(drv, """
        return typeof _termState !== 'undefined' &&
               _termState.xterm !== null;
    """)
    assert xterm_ready, 'xterm not initialised'

    # ── CALL A: select all terminal content ───────────────────────────────────
    sel_text = js(drv, """
        _termState.xterm.selectAll();
        return _termState.xterm.getSelection() || '';
    """)
    assert sel_text.strip(), 'xterm.selectAll() produced empty selection'
    print(f'\nxterm selection: {sel_text[:80]!r}')

    # ── Dispatch Ctrl+B on xterm ELEMENT (no click before it) ─────────────────
    # Dispatching on the xterm element — not document — ensures the event
    # travels capture→target→bubble exactly as a physical keypress does.
    # Our capture-phase listener (useCapture:true on document) fires BEFORE
    # xterm's target handler and saves the selection in _savedXtermSel.
    # No preceding click means the selection set by selectAll() is intact.
    dispatch_result = js(drv, """
        var xEl = document.querySelector('#terminal-output .xterm-screen')
                  || document.querySelector('#terminal-output .xterm');
        if (!xEl) return 'NO_XTERM_EL';
        xEl.dispatchEvent(new KeyboardEvent('keydown',
            {key:'b', ctrlKey:true, bubbles:true, cancelable:true}));
        return 'OK';
    """)
    print(f'dispatch: {dispatch_result!r}')
    time.sleep(1.0)

    saved = js(drv, "return typeof _savedXtermSel !== 'undefined' ? (_savedXtermSel || 'EMPTY_STR') : 'UNDEFINED'")
    print(f'_savedXtermSel: {saved!r}')

    # ── CALL B: notes-text must be non-empty ──────────────────────────────────
    notes_raw = js(drv, "return document.getElementById('notes-text').value") or ''
    print(f'notes-text: {notes_raw[:120]!r}')

    assert notes_raw.strip(), (
        f'GOAL 6 FAILED: notes-text empty after Ctrl+B.\n'
        f'  xterm sel was: {sel_text[:80]!r}\n'
        f'  _savedXtermSel: {saved!r}\n'
        f'  dispatch: {dispatch_result!r}')

    # ── Show Notes tab and verify content ─────────────────────────────────────
    notes_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.5)
    html1 = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert html1.strip() not in ('', '\u200b'), f'notes-display empty: {html1[:200]}'
    print('Notes present after Ctrl+B.')

    # ── Click CVE tab ──────────────────────────────────────────────────────────
    cve_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="cves-right"]')))
    js(drv, 'arguments[0].click()', cve_btn)
    time.sleep(2)

    # ── CALL C: click Notes tab back — note must persist ──────────────────────
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.5)
    html2 = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    print(f'notes-display after CVE->Notes: {html2[:120]!r}')

    assert html2.strip() not in ('', '\u200b'), (
        f'GOAL 6 FAILED: note lost after CVE->Notes navigation.\n'
        f'  Before nav: {html1[:200]}\n'
        f'  After nav:  {html2[:200]}')

    print('\nGOAL 6 PASS: note present and persistent.')
