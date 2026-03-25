#!/usr/bin/env python3
"""
Ctrl+B colour preservation tests — self-contained, atomic select+dispatch.
Run:  sudo python3 -m pytest tests/test_ctrl_b_color.py -v -s
"""
import os, sys, time, threading, tempfile
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PORT = 5092
IP   = '10.99.99.1'

_SEED_XML = f"""<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/>
        <service name="ssh"/></port>
    </ports>
  </host>
</nmaprun>"""


@pytest.fixture(scope="module")
def cb_server():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED_XML); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)
    t = threading.Thread(target=app.run,
        kwargs={'host': '127.0.0.1', 'port': PORT,
                'use_reloader': False, 'threaded': True}, daemon=True)
    t.start()
    time.sleep(2)
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}


@pytest.fixture(scope="module")
def cb_driver(cb_server):
    import os as _os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service
    _os.environ.pop('XAUTHORITY', None); _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions(); opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900); d.implicitly_wait(0)
    d.get(cb_server['url']); time.sleep(2)
    yield d
    d.quit()


def js(d, s, *a):   return d.execute_script(s, *a)
def W(d, t=8):      return WebDriverWait(d, t)


def ensure_host_selected(driver):
    row = W(driver).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(driver, 'arguments[0].click()', row)
    time.sleep(0.8)


def run_and_click_process(driver, wc, cmd, name, expected_word):
    """Run cmd, wait for specific word to appear in plain-output, return pid."""
    r = wc.runCommand(cmd, name=name, hostIp=IP, run_actions=False)
    pid = r['process_id']

    def _fin(d):
        for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
            if name in row.text:
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() == 'Finished':
                    return row
        return False
    proc_row = W(driver, 20).until(_fin)
    js(driver, 'arguments[0].click()', proc_row)

    # Wait until plain-output contains the SPECIFIC word from this command
    W(driver, 8).until(lambda d:
        js(d, "var e=document.getElementById('plain-output');"
               "return e && e.textContent.indexOf(arguments[0]) >= 0;",
           expected_word))
    time.sleep(0.2)
    return pid


def select_all_and_ctrl_b(driver):
    """Select all plain-output content and dispatch Ctrl+B in ONE JS call.

    Doing both in a single executeScript avoids Python-level timing gaps
    between setting the selection and dispatching the event — any timer
    (snapshot, procPollTimer) that fires between two separate executeScript
    calls could clear the browser selection or replace innerHTML.
    """
    raw_note = js(driver, """
        var el = document.getElementById('plain-output');
        if (!el) return 'NO_EL';
        // Select all content
        var r = document.createRange();
        r.selectNodeContents(el);
        var s = window.getSelection();
        s.removeAllRanges();
        s.addRange(r);
        // Dispatch Ctrl+B synchronously (same JS tick — selection still active)
        document.dispatchEvent(new KeyboardEvent('keydown',
            {key:'b', ctrlKey:true, bubbles:true, cancelable:true}));
        // Clear selection so the loadProcessOutput skip-on-active-selection
        // guard does not block subsequent tests from loading their output.
        window.getSelection().removeAllRanges();
        // Return the raw note value so the test can inspect ANSI codes
        return document.getElementById('notes-text').value || '';
    """)
    time.sleep(0.5)   # let _showNotesDisplay render
    return raw_note


def open_notes_tab(driver):
    btn = W(driver).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(driver, 'arguments[0].click()', btn)
    time.sleep(0.4)


def notes_display_html(driver):
    open_notes_tab(driver)
    return js(driver, "return document.getElementById('notes-display').innerHTML") or ''


def clear_notes_api(driver, server):
    host_id = js(driver, f"""
        var r = document.querySelector('#hosts-body tr[data-host-ip="{IP}"]');
        return r ? r.dataset.hostId : null;
    """)
    if host_id:
        import urllib.request, json as _j
        try:
            req = urllib.request.Request(
                f'http://127.0.0.1:{PORT}/api/workspace/hosts/{host_id}/note',
                data=_j.dumps({'note': ''}).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────

class TestDomColour:

    def test_c1_output_renders_ansi_colour(self, cb_driver, cb_server):
        """printf with ANSI → plain-output has ansi-fg-green span."""
        ensure_host_selected(cb_driver)
        run_and_click_process(cb_driver, cb_server['wc'],
                              r'printf "\033[32mGREEN_WORD\033[0m extra"',
                              'c1-colour', 'GREEN_WORD')
        html = js(cb_driver, "return document.getElementById('plain-output').innerHTML")
        assert 'ansi-fg-green' in html, f"plain-output missing colour span:\n{html[:300]}"

    def test_c2_ctrl_b_brings_colour_to_notes(self, cb_driver, cb_server):
        """Coloured output → select+Ctrl+B (atomic) → notes has ansi-fg-green span."""
        ensure_host_selected(cb_driver)
        clear_notes_api(cb_driver, cb_server)
        run_and_click_process(cb_driver, cb_server['wc'],
                              r'printf "\033[32mGREEN_COPY\033[0m text"',
                              'c2-colour', 'GREEN_COPY')

        raw = select_all_and_ctrl_b(cb_driver)
        print(f"\nRAW NOTE (first 100 chars repr): {repr(raw[:100])}")

        html = notes_display_html(cb_driver)
        assert 'GREEN_COPY' in html,     f"Notes missing GREEN_COPY:\n{html[:400]}"
        assert 'ansi-fg-green' in html,  f"Notes missing colour span:\n{html[:400]}"

    def test_c3_colour_survives_snapshot_refresh(self, cb_driver, cb_server):
        """Colour persists through 3 snapshot poll cycles (4.5 s)."""
        ensure_host_selected(cb_driver)
        clear_notes_api(cb_driver, cb_server)
        run_and_click_process(cb_driver, cb_server['wc'],
                              r'printf "\033[31mRED_PERSIST\033[0m"',
                              'c3-colour', 'RED_PERSIST')
        select_all_and_ctrl_b(cb_driver)
        time.sleep(4.5)
        html = notes_display_html(cb_driver)
        assert 'RED_PERSIST' in html,  f"Text lost after refresh:\n{html[:400]}"
        assert 'ansi-fg-red' in html,  f"Colour lost after refresh:\n{html[:400]}"

    def test_c4_colour_survives_host_navigate_away_and_back(self, cb_driver, cb_server):
        """Colour persists after clicking away and back."""
        ensure_host_selected(cb_driver)
        clear_notes_api(cb_driver, cb_server)
        run_and_click_process(cb_driver, cb_server['wc'],
                              r'printf "\033[33mYELLOW_NAV\033[0m"',
                              'c4-colour', 'YELLOW_NAV')
        select_all_and_ctrl_b(cb_driver)
        cb_driver.find_element(By.TAG_NAME, 'body').click()
        time.sleep(1.5)
        ensure_host_selected(cb_driver)
        html = notes_display_html(cb_driver)
        assert 'YELLOW_NAV' in html,      f"Text lost after nav:\n{html[:400]}"
        assert 'ansi-fg-yellow' in html,  f"Colour lost after nav:\n{html[:400]}"

    def test_c5_plain_text_copied_to_notes(self, cb_driver, cb_server):
        """Plain text (no ANSI) copies correctly."""
        ensure_host_selected(cb_driver)
        clear_notes_api(cb_driver, cb_server)
        run_and_click_process(cb_driver, cb_server['wc'],
                              'echo PLAIN_MARKER', 'c5-plain', 'PLAIN_MARKER')
        select_all_and_ctrl_b(cb_driver)
        html = notes_display_html(cb_driver)
        txt = js(cb_driver, "return document.getElementById('notes-display').textContent") or ''
        assert 'PLAIN_MARKER' in txt, f"Text missing from notes: {txt!r}"


class TestInteractiveTerminal:

    def test_c6_interactive_terminal_ctrl_b(self, cb_driver, cb_server):
        """xterm selectAll → Ctrl+B copies terminal text to notes."""
        import urllib.request, json as _j
        ensure_host_selected(cb_driver)
        clear_notes_api(cb_driver, cb_server)

        req = urllib.request.Request(
            f'http://127.0.0.1:{PORT}/api/terminal/start',
            data=_j.dumps({'label': 'test-term', 'host_ip': IP,
                           'command': None}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        resp = _j.loads(urllib.request.urlopen(req).read())
        session_id = resp.get('session_id')
        assert session_id, f"No session_id: {resp}"

        time.sleep(1.5)
        urllib.request.urlopen(urllib.request.Request(
            f'http://127.0.0.1:{PORT}/api/terminal/{session_id}/input',
            data=_j.dumps({'data': 'echo TERM_OUTPUT_WORD\n'}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'))
        time.sleep(1.5)

        out = _j.loads(urllib.request.urlopen(
            f'http://127.0.0.1:{PORT}/api/terminal/{session_id}/output').read())
        assert 'TERM_OUTPUT_WORD' in out.get('data', ''), \
            f"Not in terminal: {out.get('data','')[:200]}"

        def _find_interactive(d):
            for row in d.find_elements(By.CSS_SELECTOR, '#processes-body tr'):
                cells = row.find_elements(By.TAG_NAME, 'td')
                if len(cells) >= 5 and cells[4].text.strip() == 'Interactive':
                    return row
            return False
        proc_row = W(cb_driver, 10).until(_find_interactive)
        js(cb_driver, 'arguments[0].click()', proc_row)
        time.sleep(1.5)

        selected = js(cb_driver, """
            if (typeof _termState === 'undefined' || !_termState.xterm) return 'NO_XTERM';
            _termState.xterm.selectAll();
            return _termState.xterm.getSelection() || 'EMPTY';
        """)
        assert selected not in ('NO_XTERM', 'EMPTY', ''), \
            f"Could not select xterm text: {selected!r}"
        assert 'TERM_OUTPUT_WORD' in selected, \
            f"Not in xterm selection: {selected!r}"

        raw = js(cb_driver, """
            if (typeof _termState === 'undefined' || !_termState.xterm) return 'NO_XTERM';
            _termState.xterm.selectAll();
            var s = window.getSelection(); s.removeAllRanges();
            document.dispatchEvent(new KeyboardEvent('keydown',
                {key:'b', ctrlKey:true, bubbles:true, cancelable:true}));
            return document.getElementById('notes-text').value || '';
        """)
        time.sleep(0.5)

        txt = js(cb_driver, "return document.getElementById('notes-display').textContent") or ''
        open_notes_tab(cb_driver)
        txt = js(cb_driver, "return document.getElementById('notes-display').textContent") or ''
        assert 'TERM_OUTPUT_WORD' in txt, \
            f"Missing from notes after terminal Ctrl+B: {txt!r}"
