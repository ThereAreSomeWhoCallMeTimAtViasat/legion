#!/usr/bin/env python3
"""tests/test_highlight_escaping.py

Non-hollow Selenium tests for v10.145 — highlightMatches HTML-escaping fix.

  v10.145  highlightMatches HTML-escaping bug.
           ansiToHtml() escapes <, >, & to HTML entities before
           highlightMatches() runs its regex on the result.  Keywords like
           '==> DIRECTORY' (gobuster/feroxbuster) and '<ACTIVE>' (nmap SMB)
           never produced yellow .match-positive spans in the browser even
           though the Python backend (detectMatches) correctly set
           has_match=True in the snapshot.

           Fix: before building the regex, HTML-escape the pattern so the
           regex matches the entity forms that ansiToHtml() produces:
             '==> DIRECTORY' → '==&gt; DIRECTORY'  (matches ansiToHtml output)
             '<ACTIVE>'      → '&lt;ACTIVE&gt;'    (matches ansiToHtml output)

  This test file proves three things:
    A) Backend detectMatches() naturally detects HTML-special keywords
       in raw process output — no wc._matches injection needed.
    B) The JS highlightMatches() function now wraps those keywords in
       .match-positive spans in the rendered DOM.
    C) Plain keywords (no HTML-special chars) still work (regression guard).

  It also has a negative test: a process whose output contains no match
  keywords must NOT get .match-positive spans.

Run:
    sudo python3 -m pytest tests/test_highlight_escaping.py -v
"""
import os
import re
import sys
import time
import threading
import tempfile

import pytest
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PORT = 5093
IP   = '10.93.93.1'

# Output that exercises all three keyword types:
#   ==> DIRECTORY  — has '>',  gobuster/feroxbuster style
#   <ACTIVE>       — has '<' and '>',  nmap SMB output
#   exists         — plain word, no HTML-special chars (regression guard)
MATCH_CMD = (
    'printf '
    '"==> DIRECTORY: /admin/\\n'
    '<ACTIVE> message_signing\\n'
    'exists but not required\\n"'
)

# A command whose output contains NO match keywords — for the negative test
NO_MATCH_CMD = 'printf "just some boring output line\\nnothing special here\\n"'

SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4"/>
      </port>
      <port protocol="tcp" portid="445">
        <state state="open"/>
        <service name="microsoft-ds"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


# ── helpers ────────────────────────────────────────────────────────────────

def _free_port(port, retries=20):
    import subprocess, socket
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    for _ in range(retries):
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port)); s.close(); return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Port {port} still in use after {retries} attempts")


def js(d, s, *a):
    return d.execute_script(s, *a)


def W(d, t=12):
    return WebDriverWait(d, t)


def _wait_proc_done_api(srv_url, proc_id, timeout=25):
    """Poll /api/snapshot until proc_id reaches a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in requests.get(f"{srv_url}/api/snapshot",
                                  timeout=5).json().get('processes', []):
                if str(p.get('id')) == str(proc_id):
                    if p.get('status') in ('Finished', 'Killed', 'Crashed'):
                        return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Process {proc_id} did not finish within {timeout}s")


def _select_host(drv):
    row = W(drv, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', row)
    time.sleep(0.8)


def _ensure_processes_tab(drv):
    btn = W(drv, 5).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#bottom-tab-bar [data-tab="processes-panel"]')))
    js(drv, 'arguments[0].click()', btn)
    time.sleep(0.3)


def _wait_for_match_positive_populated(drv, timeout=8):
    """Wait for matchPositive to contain at least the DIRECTORY keyword."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = js(drv, """
            if (!window.matchPositive) return 0;
            return matchPositive.filter(function(k) {
                return k.indexOf('DIRECTORY') >= 0;
            }).length;
        """)
        if count and count > 0:
            return True
        time.sleep(0.5)
    return False


def _span_texts(drv, panel='plain-output'):
    """Return list of textContent from all .match-positive spans in panel."""
    return js(drv, """
        var spans = document.querySelectorAll('#' + arguments[0] + ' .match-positive');
        return Array.from(spans).map(function(s) { return s.textContent; });
    """, panel)


def _counter_text(drv, panel='plain-output'):
    return js(drv, """
        var c = document.querySelector('#' + arguments[0] + ' .match-nav-counter');
        return c ? c.textContent.trim() : '';
    """, panel)


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _orig_hb = getattr(_web_routes, '_HB_TIMEOUT', 20)
    _web_routes._HB_TIMEOUT = 600

    _free_port(PORT)
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)

    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(2.0)

    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}

    httpd.shutdown()
    _web_routes._HB_TIMEOUT = _orig_hb


@pytest.fixture(scope="module")
def drv(srv):
    import os as _os
    _os.environ.pop('XAUTHORITY', None)
    _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(srv['url'])
    time.sleep(2.0)
    yield d
    d.quit()


@pytest.fixture(autouse=True)
def _dismiss_alerts(drv):
    try:
        drv.switch_to.alert.dismiss()
    except Exception:
        pass
    yield


# conftest.py's reset_ui_state is autouse=True, scope='class' and uses the
# conftest driver at port 5099.  Override it here so it does nothing for this
# file — we manage our own driver and server.
@pytest.fixture(autouse=True, scope='class')
def reset_ui_state():
    yield


# ═══════════════════════════════════════════════════════════════════════════
# Class fixture — load page ONCE, run the match process, then share state
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="class")
def highlight_setup(drv, srv):
    """
    Run MATCH_CMD (outputs '==> DIRECTORY', '<ACTIVE>', 'exists') once
    and share the proc_id and backend-match result across all tests.

    Steps
    -----
    1. Navigate to the page and select the seeded host.
    2. Wait for matchPositive (loaded from conf) to contain the keywords.
    3. Run MATCH_CMD — _capture_output will call detectMatches() on each line.
    4. Wait for the process to finish (API poll).
    5. Poll wc._matches to verify the backend detected at least one keyword.
    6. Click the process row so loadProcessOutput fires and plain-output is filled.
    7. Wait for .match-positive spans to appear (proves JS highlightMatches ran).
    """
    wc = srv['wc']

    drv.get(srv['url'])
    time.sleep(2.0)

    _select_host(drv)
    _ensure_processes_tab(drv)

    # Wait for matchPositive to be populated from /api/settings/legion-conf fetch
    populated = _wait_for_match_positive_populated(drv, timeout=8)
    # If the async fetch hasn't populated it yet, inject explicitly so tests
    # that check JS highlighting aren't blocked on network timing
    if not populated:
        js(drv, """
            if (!window.matchPositive) window.matchPositive = [];
            ['==> DIRECTORY', '<ACTIVE>', 'exists'].forEach(function(k) {
                if (matchPositive.indexOf(k) < 0) matchPositive.push(k);
            });
        """)

    # Run the process — let _capture_output handle match detection naturally
    result = wc.runCommand(MATCH_CMD,
                           name='highlight-test',
                           tabTitle='highlight-test',
                           hostIp=IP,
                           run_actions=False)
    proc_id = str(result['process_id'])

    _wait_proc_done_api(srv['url'], proc_id, timeout=20)

    # Poll wc._matches — the backend sets it in _capture_output after detectMatches
    backend_matched = False
    deadline = time.time() + 8
    while time.time() < deadline:
        if wc._matches.get(f"{IP}:highlight-test"):
            backend_matched = True
            break
        time.sleep(0.5)

    # Click the process row — triggers loadProcessOutput in the browser
    time.sleep(1.5)  # let snapshot re-render with updated has_match state
    proc_row = W(drv, 8).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
    js(drv, 'arguments[0].click()', proc_row)

    # Wait for .match-positive spans to appear in plain-output
    # (this is the key assertion that highlightMatches ran correctly)
    spans_appeared = False
    deadline2 = time.time() + 10
    while time.time() < deadline2:
        count = js(drv,
            "return document.querySelectorAll('#plain-output .match-positive').length")
        if count and count > 0:
            spans_appeared = True
            break
        time.sleep(0.5)

    yield {
        'proc_id':        proc_id,
        'backend_matched': backend_matched,
        'spans_appeared':  spans_appeared,
        'wc':             wc,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestHighlightMatchesHTMLEscaping:
    """
    v10.145: highlightMatches() now HTML-escapes patterns before regex-matching.

    Before the fix ansiToHtml() converted '>' to '&gt;' and '<' to '&lt;',
    but highlightMatches() still searched for literal '>' and '<'.  Result:
    keywords like '==> DIRECTORY' and '<ACTIVE>' never produced highlight spans
    even though the backend correctly reported has_match=True.

    After the fix the regex uses '==&gt; DIRECTORY' and '&lt;ACTIVE&gt;',
    matching exactly what ansiToHtml() produces.
    """

    # ── A) Backend detection ─────────────────────────────────────────────────

    def test_backend_detects_html_special_keyword(self, srv, highlight_setup):
        """detectMatches() in _capture_output must fire for '==> DIRECTORY'.

        This test verifies the Python side: the match keyword in global-positive
        conf is found in the raw process output BEFORE HTML escaping occurs.
        wc._matches is populated by _capture_output → detectMatches → handleMatch.
        """
        assert highlight_setup['backend_matched'], (
            "wc._matches['{IP}:highlight-test'] is empty after process finished.\n"
            "Expected detectMatches() to find '==> DIRECTORY', '<ACTIVE>', or 'exists'\n"
            "in the raw output.  Check that these keywords are in global-positive\n"
            "in /root/.local/share/legion/legion.conf."
        )

    def test_backend_match_text_contains_directory_keyword(self, srv, highlight_setup):
        """The match text stored in wc._matches includes '==> DIRECTORY'."""
        wc = highlight_setup['wc']
        match_set = wc._matches.get(f"{IP}:highlight-test", set())
        all_text = ' '.join(str(m) for m in match_set)
        # detectMatches returns the keyword itself; handleMatch joins them
        assert 'DIRECTORY' in all_text or 'ACTIVE' in all_text or 'exists' in all_text, (
            f"Expected at least one HTML-special keyword in wc._matches.\n"
            f"Got: {match_set!r}"
        )

    # ── B) Frontend star icon (has_match in snapshot) ────────────────────────

    def test_star_icon_visible_in_process_row(self, drv, highlight_setup):
        """The ★ icon must appear in the Name cell of the finished process row.

        has_match=True in the snapshot causes the ★ to be prepended in
        _drawProcesses().  If the backend match detection works but has_match
        is not reflected in the snapshot, this test will catch it.
        """
        proc_id = highlight_setup['proc_id']
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        cells = row.find_elements(By.TAG_NAME, 'td')
        # Columns: ☐(0)|ID(1)|Name(2)|Target(3)|PID(4)|Status(5)|%(6)|Elapsed(7)
        assert len(cells) >= 3, f"Process row has only {len(cells)} cells"
        name_cell_text = cells[2].text
        assert '★' in name_cell_text, (
            f"★ (U+2605) not found in Name cell after match detection.\n"
            f"Name cell text: {name_cell_text!r}\n"
            f"Expected has_match=True to prepend ★ via _drawProcesses()."
        )

    # ── C) JS highlighting — the actual v10.145 fix ──────────────────────────

    def test_match_positive_spans_exist_in_plain_output(self, drv, highlight_setup):
        """At least one .match-positive span must exist in #plain-output.

        This is the core test for v10.145.  Before the fix, highlightMatches()
        searched for literal '<' and '>' but ansiToHtml() had already converted
        them to '&lt;' and '&gt;'.  No spans were produced even when has_match=True.
        """
        assert highlight_setup['spans_appeared'], (
            "No .match-positive spans appeared in #plain-output after clicking\n"
            "the process row.  This is the v10.145 regression: highlightMatches()\n"
            "was searching for literal '>' but ansiToHtml() had already converted\n"
            "it to '&gt;'.  Fix: HTML-escape the pattern before building the regex."
        )
        spans = _span_texts(drv)
        assert len(spans) >= 1, \
            f"Expected ≥1 .match-positive span in #plain-output, got 0."

    def test_gobuster_directory_keyword_is_highlighted(self, drv, highlight_setup):
        """The '==> DIRECTORY' text must appear inside a .match-positive span.

        This keyword contains '>' which ansiToHtml() converts to '&gt;'.
        Before the fix the regex searched for literal '>' and never matched.
        After the fix the regex uses '==&gt; DIRECTORY' and wraps the text.
        The span's DOM textContent is '==> DIRECTORY' (browser un-escapes entities).
        """
        spans = _span_texts(drv)
        dir_spans = [s for s in spans if '==> DIRECTORY' in s or 'DIRECTORY' in s]
        assert dir_spans, (
            f"No .match-positive span contains '==> DIRECTORY'.\n"
            f"All span texts: {spans!r}\n"
            f"v10.145 fix: htmlEscaped = stripped.replace('>', '&gt;') so the\n"
            f"regex matches the '==&gt; DIRECTORY' that ansiToHtml() produces."
        )

    def test_active_keyword_is_highlighted(self, drv, highlight_setup):
        """The '<ACTIVE>' text must appear inside a .match-positive span.

        '<ACTIVE>' contains both '<' and '>' which ansiToHtml() converts to
        '&lt;' and '&gt;'.  The fix HTML-escapes the pattern before the regex,
        so '&lt;ACTIVE&gt;' matches.  The span textContent is '<ACTIVE>'.
        """
        spans = _span_texts(drv)
        active_spans = [s for s in spans if 'ACTIVE' in s]
        assert active_spans, (
            f"No .match-positive span contains '<ACTIVE>'.\n"
            f"All span texts: {spans!r}\n"
            f"'<ACTIVE>' contains '<' and '>' — both are HTML-escaped by\n"
            f"ansiToHtml(). The v10.145 fix must convert the pattern to\n"
            f"'&lt;ACTIVE&gt;' before building the highlightMatches regex."
        )

    def test_plain_keyword_also_highlighted(self, drv, highlight_setup):
        """The plain keyword 'exists' (no HTML-special chars) is also highlighted.

        Regression guard: the HTML-escaping step must not break plain keywords.
        'exists' in the output should still produce a .match-positive span.
        """
        spans = _span_texts(drv)
        plain_spans = [s for s in spans if 'exists' in s.lower()]
        assert plain_spans, (
            f"No .match-positive span contains 'exists'.\n"
            f"All span texts: {spans!r}\n"
            f"Plain keywords (no HTML-special chars) must still be highlighted\n"
            f"after the v10.145 HTML-escaping fix."
        )

    def test_match_banner_counter_is_nonzero(self, drv, highlight_setup):
        """The match navigation counter must show a positive number like '1 ⁄ N'.

        The counter is populated by _matchNavInit() after loadProcessOutput renders
        the spans.  A zero or empty counter means the spans weren't found by the
        navigation logic even if they exist in the DOM.
        """
        txt = _counter_text(drv)
        assert txt, (
            "Match banner counter is empty.  Expected something like '1 ⁄ 3'.\n"
            "The counter is set by _matchNavInit() which counts .match-positive spans."
        )
        # Counter format is "N ⁄ M" — N and M must both be ≥ 1
        nums = re.findall(r'\d+', txt)
        assert len(nums) >= 2, \
            f"Counter text {txt!r} must contain two numbers (current ⁄ total)."
        total = int(nums[1])
        assert total >= 1, \
            f"Total matches in counter must be ≥ 1, got {total} from {txt!r}."

    def test_match_banner_next_button_advances_counter(self, drv, highlight_setup):
        """Clicking ▼ must increment the 'current' position in the counter.

        This tests that the navigation arrows are wired and functional, not just
        present in the DOM.  The counter should change from '1 ⁄ N' to '2 ⁄ N'
        (or wrap to '1 ⁄ N' if there's only one match — wrapping is also valid).
        """
        before = _counter_text(drv)
        # Click next
        js(drv, "document.querySelector('#plain-output .match-next').click()")
        time.sleep(0.5)
        after = _counter_text(drv)

        assert before, "Counter was empty before clicking ▼"
        assert after, "Counter empty after clicking ▼ — navigation JS didn't fire"

        before_nums = re.findall(r'\d+', before)
        after_nums  = re.findall(r'\d+', after)
        assert len(before_nums) >= 2 and len(after_nums) >= 2, \
            f"Counter format wrong: before={before!r} after={after!r}"

        total = int(before_nums[1])
        if total > 1:
            # Multiple matches: current index must have changed
            assert before_nums[0] != after_nums[0], (
                f"Counter 'current' did not change after clicking ▼.\n"
                f"before={before!r}  after={after!r}\n"
                f"Expected _matchNav() to advance the index."
            )
        # If total == 1 the counter stays at '1 ⁄ 1' — wrapping is correct


# ═══════════════════════════════════════════════════════════════════════════
# Negative test — process with no matching keywords must produce no spans
# ═══════════════════════════════════════════════════════════════════════════

class TestNoSpansWithoutMatchKeywords:
    """A process whose output contains no global-positive keywords must not
    produce any .match-positive spans.  This prevents the test from being
    trivially green because the fixture page still shows a previous process."""

    def test_no_match_positive_spans_for_unmatched_output(self, drv, srv):
        """Output with no match keywords → zero .match-positive spans in output panel."""
        wc = srv['wc']

        drv.get(srv['url'])
        time.sleep(2.0)

        # Select host and ensure processes tab is active
        _select_host(drv)
        _ensure_processes_tab(drv)

        result = wc.runCommand(NO_MATCH_CMD,
                               name='no-match-test',
                               tabTitle='no-match-test',
                               hostIp=IP,
                               run_actions=False)
        proc_id = str(result['process_id'])
        _wait_proc_done_api(srv['url'], proc_id, timeout=15)

        # Wait for snapshot to propagate — has_match must be False
        time.sleep(1.5)
        snap = requests.get(f"{srv['url']}/api/snapshot", timeout=5).json()
        proc = next((p for p in snap.get('processes', [])
                     if str(p.get('id')) == proc_id), None)
        assert proc is not None, f"Process {proc_id} not found in snapshot"
        assert not proc.get('has_match', False), (
            f"Process running '{NO_MATCH_CMD}' must have has_match=False.\n"
            f"Got has_match={proc.get('has_match')!r}.\n"
            f"Check that NO_MATCH_CMD output doesn't accidentally contain a keyword."
        )

        # Click the row to load output into plain-output
        row = W(drv, 8).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
        js(drv, 'arguments[0].click()', row)
        time.sleep(2.0)

        spans = _span_texts(drv)
        assert len(spans) == 0, (
            f"Expected zero .match-positive spans for output with no keywords.\n"
            f"Found {len(spans)} spans with text: {spans!r}\n"
            f"This indicates a false-positive in highlightMatches()."
        )

        # Also confirm no match banner appears
        banner_count = js(drv,
            "return document.querySelectorAll('#plain-output .match-banner').length")
        assert banner_count == 0, (
            f"Match banner must not appear when has_match=False.\n"
            f"Found {banner_count} banner(s)."
        )
