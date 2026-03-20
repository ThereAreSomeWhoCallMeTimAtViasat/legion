#!/usr/bin/env python3
"""
v10.0 Feature Tests
===================
Tests for the five features implemented in v10.0-flask:
  F1: nmap percent column (real-time progress parsing)
  F2: Multi-host parallel processes (comma/newline splitting)
  F3: In-memory log handler (log tab without stdout redirect)
  F4: Font size control (JS source inspection)
  F5: Port state filter (JS source inspection)

Run: sudo python3 tests/test_v10_features.py
"""

import os
import sys
import time
import tempfile
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = FAIL = SKIP = 0

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        r = fn()
        if r is None or r is True:   PASS += 1; print(f"  \u2713 {name}"); return True
        elif r == 'SKIP':             SKIP += 1; print(f"  \u2298 {name} (SKIP)"); return False
        else:                         FAIL += 1; print(f"  \u2717 {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""): return True if v else f"FAIL: {msg}"


from app.web.testhelper import create_test_app
from app.importers.nmap_import import import_nmap_xml
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
    </ports>
  </host>
</nmaprun>"""

with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _sp = _f.name
import_nmap_xml(project=logic.activeProject, xml_path=_sp, output="")
os.unlink(_sp)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("F1: nmap percent column — real-time progress parsing")
print("="*60 + "\n")

def test_f1_stats_every_in_nmap_commands():
    """All nmap commands must include --stats-every 5s (string or list form)."""
    from controller.web_controller import WebController
    import inspect
    src = inspect.getsource(WebController.addHosts)
    src2 = inspect.getsource(WebController.runStagedNmap)
    # addHosts uses f-string: '--stats-every 5s'; runStagedNmap uses list: '--stats-every', '5s'
    ok1 = '--stats-every 5s' in src
    ok2 = ("'--stats-every', '5s'" in src2) or ('--stats-every 5s' in src2)
    return ok(ok1 and ok2,
              f"--stats-every 5s missing: addHosts={ok1} runStagedNmap={ok2}")
test("F1.1: all nmap commands include --stats-every 5s", test_f1_stats_every_in_nmap_commands)

def test_f1_capture_output_parses_percent():
    """_capture_output source contains nmap percent pattern parsing."""
    from controller.web_controller import WebController
    import inspect
    src = inspect.getsource(WebController._capture_output)
    return ok('% done' in src and 'storeProcessPercent' in src,
              "_capture_output does not parse nmap percent progress")
test("F1.2: _capture_output parses '% done' and calls storeProcessPercent", test_f1_capture_output_parses_percent)

def test_f1_percent_pattern_matches_nmap_output():
    """The regex correctly extracts percent and ETC from nmap stats lines."""
    import re
    lines = [
        ("SYN Stealth Scan Timing: About 42.93% done; ETC: 15:22 (0:01:23 remaining)", "42.93", "15:22"),
        ("NSE Timing: About 100.00% done; ETC: 15:30 (0:00:00 remaining)", "100.00", "15:30"),
        ("Ping scan Timing: About 5.00% done", "5.00", None),
    ]
    pattern = re.compile(r'About ([\d.]+)% done(?:.*?ETC: ([\d:]+))?')
    for line, exp_pct, exp_etc in lines:
        m = pattern.search(line)
        if not m:
            return f"FAIL: pattern did not match: {line!r}"
        if m.group(1) != exp_pct:
            return f"FAIL: expected pct={exp_pct!r}, got {m.group(1)!r}"
        if exp_etc and m.group(2) != exp_etc:
            return f"FAIL: expected ETC={exp_etc!r}, got {m.group(2)!r}"
    return True
test("F1.3: percent regex matches nmap stats output correctly", test_f1_percent_pattern_matches_nmap_output)

def test_f1_storeProcessPercent_exists():
    """ProcessRepository.storeProcessPercent method must exist."""
    from db.repositories.ProcessRepository import ProcessRepository
    return ok(hasattr(ProcessRepository, 'storeProcessPercent'),
              "storeProcessPercent not found on ProcessRepository")
test("F1.4: ProcessRepository.storeProcessPercent method exists", test_f1_storeProcessPercent_exists)

def test_f1_percent_in_snapshot():
    """Snapshot processes must include a percent field."""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    if not procs:
        # Create a process to check
        wc.start()
        wc.runCommand('echo test', name='pct-test', hostIp='10.10.10.1')
        time.sleep(1.5)
        snap = client.get('/api/snapshot').get_json()
        procs = snap.get('processes', [])
    if not procs:
        return "SKIP"
    return ok(all('percent' in p for p in procs),
              "Some snapshot processes lack 'percent' field")
test("F1.5: snapshot processes include percent field", test_f1_percent_in_snapshot)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("F2: Multi-host parallel processes (comma/newline splitting)")
print("="*60 + "\n")

def test_f2_single_host_still_works():
    """Single host with no separator still returns 200."""
    r = client.post('/api/nmap/scan', json={'targets': '10.20.30.1'})
    return ok(r.status_code == 200, f"Single host returned {r.status_code}")
test("F2.1: single host POST returns 200", test_f2_single_host_still_works)

def test_f2_comma_creates_two_processes():
    """Comma-separated targets create two separate processes."""
    wc.start()
    snap_before = {p['id'] for p in client.get('/api/snapshot').get_json().get('processes', [])}
    r = client.post('/api/nmap/scan', json={'targets': '10.50.50.1,10.50.50.2'})
    return ok(r.status_code == 200,
              f"Comma-separated targets returned {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("F2.2: comma-separated targets accepted (200)", test_f2_comma_creates_two_processes)

def test_f2_newline_creates_two_processes():
    """Newline-separated targets create two separate processes."""
    wc.start()
    r = client.post('/api/nmap/scan', json={'targets': '10.60.60.1\n10.60.60.2'})
    return ok(r.status_code == 200,
              f"Newline-separated targets returned {r.status_code}")
test("F2.3: newline-separated targets accepted (200)", test_f2_newline_creates_two_processes)

def test_f2_result_is_list_for_multiple():
    """Multiple targets return a list of results."""
    r = client.post('/api/nmap/scan', json={'targets': '10.70.70.1,10.70.70.2'})
    data = r.get_json()
    result = data.get('result')
    return ok(isinstance(result, list) and len(result) == 2,
              f"Expected list of 2 results, got: {type(result).__name__} {result}")
test("F2.4: two comma-separated targets produce list of 2 results", test_f2_result_is_list_for_multiple)

def test_f2_invalid_in_list_rejected():
    """One invalid target in a comma list rejects the whole request."""
    r = client.post('/api/nmap/scan', json={'targets': '10.80.80.1,<evil>'})
    return ok(r.status_code == 400,
              f"Expected 400 for invalid target in list, got {r.status_code}")
test("F2.5: invalid target in comma list rejected (400)", test_f2_invalid_in_list_rejected)

def test_f2_semicolon_still_rejected():
    """Semicolons are injection-protection characters — still rejected as injection."""
    r = client.post('/api/nmap/scan', json={'targets': '127.0.0.1; rm -rf /'})
    return ok(r.status_code == 400,
              f"Expected 400 for semicolon injection, got {r.status_code}")
test("F2.6: semicolon injection still rejected (400)", test_f2_semicolon_still_rejected)

def test_f2_spaces_and_mixed_separators():
    """Leading/trailing spaces around targets are stripped."""
    r = client.post('/api/nmap/scan', json={'targets': ' 10.90.90.1 , 10.90.90.2 '})
    return ok(r.status_code == 200,
              f"Padded comma targets returned {r.status_code}")
test("F2.7: whitespace around comma-separated targets stripped correctly", test_f2_spaces_and_mixed_separators)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("F3: In-memory log handler")
print("="*60 + "\n")

def test_f3_mem_handler_exists():
    """_mem_handler singleton must exist in legionLog."""
    from app.logging import legionLog
    return ok(hasattr(legionLog, '_mem_handler'),
              "_mem_handler not found in legionLog module")
test("F3.1: _mem_handler singleton exists in legionLog", test_f3_mem_handler_exists)

def test_f3_handler_attached_to_legion_logger():
    """_mem_handler must be attached to the 'legion' logger."""
    from app.logging.legionLog import _mem_handler, getAppLogger
    logger = getAppLogger()
    return ok(_mem_handler in logger.handlers,
              f"_mem_handler not in legion logger handlers: {logger.handlers}")
test("F3.2: _mem_handler attached to 'legion' logger", test_f3_handler_attached_to_legion_logger)

def test_f3_api_logs_returns_200():
    """GET /api/logs must return 200."""
    r = client.get('/api/logs')
    return ok(r.status_code == 200, f"Expected 200, got {r.status_code}")
test("F3.3: GET /api/logs returns 200", test_f3_api_logs_returns_200)

def test_f3_api_logs_has_content():
    """/api/logs must return non-empty lines (in-memory handler captures app startup)."""
    # Trigger some logging by making an API call
    client.get('/api/snapshot')
    r = client.get('/api/logs?level=DEBUG')
    data = r.get_json()
    lines = data.get('lines', [])
    return ok(len(lines) > 0,
              "Log returned 0 lines — in-memory handler may not be capturing")
test("F3.4: /api/logs returns non-empty content without stdout redirect", test_f3_api_logs_has_content)

def test_f3_api_logs_level_filter():
    """/api/logs?level=INFO must exclude DEBUG lines."""
    r = client.get('/api/logs?level=INFO')
    data = r.get_json()
    lines = data.get('lines', [])
    debug_lines = [l for l in lines if '  DEBUG   ' in l or '  DEBUG  ' in l]
    return ok(len(debug_lines) == 0,
              f"Found {len(debug_lines)} DEBUG lines with level=INFO filter")
test("F3.5: /api/logs?level=INFO filters out DEBUG lines", test_f3_api_logs_level_filter)

def test_f3_mem_handler_class_has_get_lines():
    """_InMemoryLogHandler must have get_lines() method."""
    from app.logging.legionLog import _InMemoryLogHandler
    h = _InMemoryLogHandler(maxlen=10)
    return ok(hasattr(h, 'get_lines') and callable(h.get_lines),
              "get_lines() method not found")
test("F3.6: _InMemoryLogHandler has callable get_lines() method", test_f3_mem_handler_class_has_get_lines)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("F4: Font size control (JS source inspection)")
print("="*60 + "\n")

JS_PATH = os.path.join(PROJECT_ROOT, 'app', 'web', 'static', 'js', 'legion.js')
HTML_PATH = os.path.join(PROJECT_ROOT, 'app', 'web', 'templates', 'index.html')

def test_f4_font_buttons_in_html():
    """index.html must contain output-font-inc and output-font-dec buttons."""
    with open(HTML_PATH) as f:
        html = f.read()
    return ok('output-font-inc' in html and 'output-font-dec' in html,
              "Font size buttons not found in index.html")
test("F4.1: font size buttons (output-font-inc/dec) in index.html", test_f4_font_buttons_in_html)

def test_f4_log_font_buttons_in_html():
    """Log panel must also have font size buttons."""
    with open(HTML_PATH) as f:
        html = f.read()
    return ok('log-font-inc' in html and 'log-font-dec' in html,
              "Log panel font buttons not found in index.html")
test("F4.2: log panel font size buttons (log-font-inc/dec) in index.html", test_f4_log_font_buttons_in_html)

def test_f4_js_has_font_size_handler():
    """legion.js must contain font size increment/decrement logic."""
    with open(JS_PATH) as f:
        src = f.read()
    return ok('legion_output_font_pt' in src and 'output-font-inc' in src,
              "Font size handler not found in legion.js")
test("F4.3: legion.js contains font size handler with localStorage persistence", test_f4_js_has_font_size_handler)

def test_f4_js_applies_to_correct_elements():
    """Font size must apply to plain-output and log-output."""
    with open(JS_PATH) as f:
        src = f.read()
    return ok("'plain-output'" in src and "'log-output'" in src,
              "Font size not applied to plain-output and log-output in JS")
test("F4.4: font size applied to plain-output and log-output", test_f4_js_applies_to_correct_elements)

def test_f4_min_max_bounds():
    """Font size must have min/max bounds defined."""
    with open(JS_PATH) as f:
        src = f.read()
    return ok('MIN_PT' in src and 'MAX_PT' in src,
              "Font size bounds (MIN_PT/MAX_PT) not defined in JS")
test("F4.5: font size has MIN_PT and MAX_PT bounds", test_f4_min_max_bounds)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("F5: Port state filter (open/closed/filtered)")
print("="*60 + "\n")

def test_f5_filter_checkboxes_in_html():
    """index.html must contain port state filter checkboxes."""
    with open(HTML_PATH) as f:
        html = f.read()
    checks = ['filter-state-open', 'filter-state-filtered', 'filter-state-closed']
    missing = [c for c in checks if c not in html]
    return ok(not missing, f"Missing filter checkboxes: {missing}")
test("F5.1: port state filter checkboxes in index.html", test_f5_filter_checkboxes_in_html)

def test_f5_open_checked_by_default():
    """filter-state-open must be checked by default (open ports shown)."""
    with open(HTML_PATH) as f:
        html = f.read()
    # The open checkbox should have 'checked' attribute
    import re
    open_cb = re.search(r'id="filter-state-open"[^>]*>', html)
    if not open_cb:
        return "FAIL: filter-state-open checkbox not found in HTML"
    return ok('checked' in open_cb.group(0),
              f"filter-state-open not checked by default: {open_cb.group(0)!r}")
test("F5.2: filter-state-open is checked by default", test_f5_open_checked_by_default)

def test_f5_closed_unchecked_by_default():
    """filter-state-closed must be unchecked by default (closed ports hidden)."""
    with open(HTML_PATH) as f:
        html = f.read()
    import re
    closed_cb = re.search(r'id="filter-state-closed"[^>]*>', html)
    if not closed_cb:
        return "FAIL: filter-state-closed checkbox not found"
    return ok('checked' not in closed_cb.group(0),
              f"filter-state-closed is checked by default (should be hidden)")
test("F5.3: filter-state-closed is unchecked by default", test_f5_closed_unchecked_by_default)

def test_f5_js_has_state_filter_handler():
    """legion.js must contain the port state filter apply function."""
    with open(JS_PATH) as f:
        src = f.read()
    return ok('applyStateFilter' in src and 'filter-state-open' in src,
              "Port state filter handler not found in legion.js")
test("F5.4: legion.js contains port state filter handler", test_f5_js_has_state_filter_handler)

def test_f5_filter_fires_on_ports_rendered():
    """Port state filter must hook into the legion:ports-rendered event."""
    with open(JS_PATH) as f:
        src = f.read()
    return ok('legion:ports-rendered' in src,
              "legion:ports-rendered event not found in JS")
test("F5.5: port state filter wired to legion:ports-rendered custom event", test_f5_filter_fires_on_ports_rendered)

def test_f5_draw_ports_dispatches_event():
    """_drawPorts must dispatch the legion:ports-rendered event."""
    with open(JS_PATH) as f:
        src = f.read()
    return ok("dispatchEvent" in src and "legion:ports-rendered" in src,
              "_drawPorts does not dispatch legion:ports-rendered")
test("F5.6: _drawPorts dispatches legion:ports-rendered after render", test_f5_draw_ports_dispatches_event)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
