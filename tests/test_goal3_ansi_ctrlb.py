#!/usr/bin/env python3
"""
Goal 3: ANSI colour is preserved when copying from a non-xterm output window
        via Ctrl+B into the Notes tab.

Covers two sources:
  A) plain-output (lower panel) — process output loaded by clicking a process row
  B) dyn-output  (upper panel) — process output loaded via a dynamic tab button

What makes these tests non-hollow:
  1. A real command runs through WebController and produces ANSI output stored
     in SQLite.  The output is fetched live by the poll and rendered by ansiToHtml()
     into real <span class="ansi-fg-*"> nodes in the DOM.
  2. The selection is set in a SEPARATE JS call (CALL A), and the Ctrl+B is fired
     by ActionChains in a SEPARATE Python call — real browser time passes between
     them and the snapshot poll may fire in between.
  3. ActionChains generates isTrusted=true keyboard events that go through the
     browser's actual keyboard dispatch path, the same as a physical keypress.
     dispatchEvent() generates isTrusted=false — not used here.
  4. domSelectionToAnsi() (called by sendSelectionToNotes() inside the browser)
     must walk the live DOM, find ansi-fg-* CSS classes on span nodes, and
     reconstruct ANSI escape sequences from them.  The ESC codes land in
     notes-text.value, and _showNotesDisplay() converts them back to HTML spans.
     Every step is the real program code, not a stub.

Critical detail:
  After setting selection via JS, focus a neutral element with JS .focus()
  (NOT ActionChains.click()) so the keyboard event lands somewhere that bubbles
  to document.  A real click clears window.getSelection(); .focus() does not.
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

PORT = 5087
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


def _clear_notes(host_id):
    req = urllib.request.Request(
        f'{BASE}/api/workspace/hosts/{host_id}/note',
        data=_j.dumps({'note': ''}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    urllib.request.urlopen(req)


def _get_host_id(drv):
    return js(drv, f"""
        var r = document.querySelector('#hosts-body tr[data-host-ip="{IP}"]');
        return r ? r.dataset.hostId : null;
    """)


def _wait_for_finished(drv, name, timeout=20):
    """Poll processes table until the named process shows Finished, return the row."""
    def _fin(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            if name in row.text:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() == 'Finished':
                    return row
        return False
    return W(drv, timeout).until(_fin)


# ─── Sub-test A: plain-output (lower panel) ───────────────────────────────────

def test_goal3a_plain_output_ansi_preserved_in_notes(drv, srv):
    """
    Lower panel → Ctrl+B → notes retains ANSI colour.

    Real program path exercised:
      runCommand → _capture_output writes ANSI bytes to SQLite →
      /api/processes/<id>/output returns them →
      loadProcessOutput calls ansiToHtml() → plain-output has ansi-fg-green spans →
      JS selectNodeContents selects them →
      ActionChains Ctrl+B fires isTrusted=true keydown →
      bubble-phase listener calls sendSelectionToNotes() →
      domSelectionToAnsi() walks the live DOM, finds ansi-fg-green class,
        emits \x1b[32m...  \x1b[0m into notes-text.value →
      _showNotesDisplay() renders notes-text back through ansiToHtml() →
      notes-display contains <span class="ansi-fg-green">.
    """
    wc = srv['wc']

    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    host_id = _get_host_id(drv)
    assert host_id, 'Could not get host_id'
    _clear_notes(host_id)

    # Run a real command — printf with ANSI green escape sequence
    r = wc.runCommand(
        r'printf "\033[32mGREEN_LOWER_ANSI\033[0m trailing text"',
        name='goal3a', hostIp=IP, run_actions=False)

    proc_row = _wait_for_finished(drv, 'goal3a')
    js(drv, 'arguments[0].click()', proc_row)

    # Wait for the rendered ANSI span to appear in plain-output
    W(drv, 8).until(lambda d:
        'ansi-fg-green' in (
            js(d, "return document.getElementById('plain-output').innerHTML") or ''))

    html_out = js(drv, "return document.getElementById('plain-output').innerHTML")
    assert 'GREEN_LOWER_ANSI' in html_out, \
        f"Expected text missing from plain-output: {html_out[:300]}"
    assert 'ansi-fg-green' in html_out, \
        f"ansi-fg-green span missing from plain-output: {html_out[:300]}"
    print(f'\nplain-output has ansi-fg-green span ✓')

    # ── CALL A: dispatch synthetic mousedown (sets _lastNonXtermSelSource)
    #           then select all content — separate JS call from Ctrl+B ─────────
    # The mousedown on plain-output triggers the document capture listener that
    # sets _lastNonXtermSelSource = 'plain-output', which sendSelectionToNotes()
    # uses to identify the correct flash target.
    js(drv, """
        var el = document.getElementById('plain-output');
        el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
        var r = document.createRange();
        r.selectNodeContents(el);
        var s = window.getSelection();
        s.removeAllRanges();
        s.addRange(r);
    """)

    sel_text = js(drv, "return window.getSelection().toString()")
    assert 'GREEN_LOWER_ANSI' in sel_text, \
        f"Selection does not contain expected text: {sel_text!r}"
    print(f'Selection set ({len(sel_text)} chars): {sel_text[:60]!r}')

    # Focus plain-output via JS so ActionChains keyboard event lands on it and
    # bubbles to document.  JS .focus() does NOT clear window.getSelection().
    js(drv, """
        var el = document.getElementById('plain-output');
        if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
        el.focus();
    """)

    # Brief real-time settle — short enough that no snapshot fires
    time.sleep(0.3)

    # ── ActionChains Ctrl+B — isTrusted=true, real browser keyboard event ─────
    ActionChains(drv).key_down(Keys.CONTROL).send_keys('b') \
                     .key_up(Keys.CONTROL).perform()
    time.sleep(0.8)

    # ── CALL B: verify notes-display has ansi-fg-green span ──────────────────
    notes_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.4)

    raw_note = js(drv, "return document.getElementById('notes-text').value") or ''
    html     = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    print(f'notes-text  ({len(raw_note)} chars): {repr(raw_note[:100])}')
    print(f'notes-display snippet: {html[:300]!r}')

    assert 'GREEN_LOWER_ANSI' in (html + raw_note), \
        f"GOAL 3A FAILED: text not in notes at all.\n  raw: {raw_note[:200]}"
    assert 'ansi-fg-green' in html, (
        f"GOAL 3A FAILED: ANSI colour lost — domSelectionToAnsi() did not "
        f"reconstruct ESC codes from ansi-fg-green span.\n"
        f"  raw note:      {repr(raw_note[:200])}\n"
        f"  notes-display: {html[:400]}")

    print('\nGOAL 3A PASS: plain-output ANSI colour preserved in notes via Ctrl+B ✓')


# ─── Sub-test B: dyn-output (upper panel dynamic tab) ─────────────────────────

def test_goal3b_dyn_output_ansi_preserved_in_notes(drv, srv):
    """
    Upper panel (dynamic tab) → Ctrl+B → notes retains ANSI colour.

    Same pipeline as 3A, but output is loaded into dyn-output-{pid} (upper panel)
    by clicking the dynamic tab button rather than a process row in the lower panel.
    The domSelectionToAnsi() walk must find the ansi-fg-cyan class in the
    dyn-output-* element and emit the correct ESC sequence.
    """
    wc = srv['wc']

    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    host_id = _get_host_id(drv)
    _clear_notes(host_id)

    # Run a real command — printf with ANSI cyan escape sequence
    r = wc.runCommand(
        r'printf "\033[36mCYAN_UPPER_ANSI\033[0m dyn tab"',
        name='goal3b', hostIp=IP, run_actions=False)
    pid = r['process_id']

    _wait_for_finished(drv, 'goal3b')
    time.sleep(0.5)   # let snapshot render the dynamic tab button

    # Click the DYNAMIC TAB BUTTON in the right-panel tab bar — this is a
    # different UI path from clicking the process row.  The output loads into
    # dyn-output-{pid} in the upper panel (not plain-output).
    dyn_btn = W(drv, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#right-tab-bar [data-tab="dyntab-{pid}"]')))
    js(drv, 'arguments[0].click()', dyn_btn)

    # Wait for the ANSI span in dyn-output-{pid}
    W(drv, 8).until(lambda d:
        'ansi-fg-cyan' in (
            js(d, f"var e=document.getElementById('dyn-output-{pid}');"
                   "return e ? e.innerHTML : ''") or ''))

    html_out = js(drv, f"return document.getElementById('dyn-output-{pid}').innerHTML")
    assert 'CYAN_UPPER_ANSI' in html_out, \
        f"Text missing from dyn-output: {html_out[:300]}"
    assert 'ansi-fg-cyan' in html_out, \
        f"ansi-fg-cyan span missing from dyn-output: {html_out[:300]}"
    print(f'\ndyn-output-{pid} has ansi-fg-cyan span ✓')

    # ── CALL A: dispatch mousedown in dyn-output (sets _lastNonXtermSelSource)
    #           then select all content ──────────────────────────────────────
    js(drv, f"""
        var el = document.getElementById('dyn-output-{pid}');
        el.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, cancelable: true}}));
        var r = document.createRange();
        r.selectNodeContents(el);
        var s = window.getSelection();
        s.removeAllRanges();
        s.addRange(r);
    """)

    sel_text = js(drv, "return window.getSelection().toString()")
    assert 'CYAN_UPPER_ANSI' in sel_text, \
        f"Selection does not contain expected text: {sel_text!r}"
    print(f'Selection set ({len(sel_text)} chars): {sel_text[:60]!r}')

    # Focus the dyn-output element so the keyboard event lands on it and
    # bubbles to document.  JS .focus() does NOT clear window.getSelection().
    js(drv, f"""
        var el = document.getElementById('dyn-output-{pid}');
        if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
        el.focus();
    """)

    time.sleep(0.3)

    # ── ActionChains Ctrl+B — isTrusted=true ─────────────────────────────────
    ActionChains(drv).key_down(Keys.CONTROL).send_keys('b') \
                     .key_up(Keys.CONTROL).perform()
    time.sleep(0.8)

    # ── CALL B: verify notes-display has ansi-fg-cyan span ────────────────────
    notes_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.4)

    raw_note = js(drv, "return document.getElementById('notes-text').value") or ''
    html     = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    print(f'notes-text  ({len(raw_note)} chars): {repr(raw_note[:100])}')
    print(f'notes-display snippet: {html[:300]!r}')

    assert 'CYAN_UPPER_ANSI' in (html + raw_note), \
        f"GOAL 3B FAILED: text not in notes at all.\n  raw: {raw_note[:200]}"
    assert 'ansi-fg-cyan' in html, (
        f"GOAL 3B FAILED: ANSI colour lost — domSelectionToAnsi() did not "
        f"reconstruct ESC codes from ansi-fg-cyan span in dyn-output.\n"
        f"  raw note:      {repr(raw_note[:200])}\n"
        f"  notes-display: {html[:400]}")

    print('\nGOAL 3B PASS: dyn-output ANSI colour preserved in notes via Ctrl+B ✓')
