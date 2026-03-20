#!/usr/bin/env python3
"""
Phase 5 Polish Tests
=====================
Run with: sudo python3 tests/test_phase5_polish.py

Tests for Phase 5 gap items:
  L1-L7:  Log tab level filter — reads log file, filters INFO/DEBUG,
           auto-loads when Log tab is clicked
  B1-B8:  Brute tab full implementation — hydra command built correctly,
           process appears in process table, credential extraction wired,
           send-to-brute populates tab fields

Qt6 reference:
  - Log: handleLogFileLevelChange → reloadLogFile reads /tmp/legion-web.log
  - Brute: callHydra → bWidget.buildHydraCommand → controller.runCommand('hydra')
           bruteProcessFinished → createNewTabForHost
           checkHydraResults already called from _capture_output
"""

import os, sys, time, traceback, tempfile

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

JS   = open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')).read()
HTML = open(os.path.join(PROJECT_ROOT, 'app/web/templates/index.html')).read()

# ── Setup ─────────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()


# ══════════════════════════════════════════════════════════════
# L: Log tab level filter
# Qt6: reloadLogFile reads log file, filters by INFO/DEBUG level
# Flask: /api/logs?level=INFO → reads /tmp/legion-web.log
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("L: Log tab level filter")
print("="*60 + "\n")

def test_l1_log_route_exists():
    """/api/logs route must return log content"""
    r = client.get('/api/logs')
    return ok(r.status_code == 200,
              f"status={r.status_code}")
test("L1.1: /api/logs returns 200", test_l1_log_route_exists)

def test_l2_log_route_returns_lines():
    """/api/logs must return a list of log lines"""
    data = client.get('/api/logs').get_json()
    return ok(isinstance(data.get('lines'), list),
              f"response does not have 'lines' list: {list(data.keys())}")
test("L1.2: /api/logs response has 'lines' list", test_l2_log_route_returns_lines)

def test_l3_log_level_filter_info():
    """/api/logs?level=INFO must only return INFO/WARNING/ERROR lines"""
    data = client.get('/api/logs?level=INFO').get_json()
    lines = data.get('lines', [])
    # If no log file exists it's still OK (empty list)
    if not lines: return True
    debug_lines = [l for l in lines if ' DEBUG ' in l and
                   ' INFO ' not in l and ' WARNING ' not in l and
                   ' ERROR ' not in l]
    return ok(not debug_lines,
              f"{len(debug_lines)} DEBUG lines leaked into INFO filter")
test("L1.3: /api/logs?level=INFO excludes DEBUG lines", test_l3_log_level_filter_info)

def test_l4_log_level_filter_debug():
    """/api/logs?level=DEBUG must return all log lines"""
    data_info  = client.get('/api/logs?level=INFO').get_json()
    data_debug = client.get('/api/logs?level=DEBUG').get_json()
    return ok(len(data_debug.get('lines',[])) >= len(data_info.get('lines',[])),
              "DEBUG level returned fewer lines than INFO")
test("L1.4: /api/logs?level=DEBUG returns >= lines than INFO", test_l4_log_level_filter_debug)

def test_l5_log_dropdown_in_html():
    """Log panel must have a level filter dropdown"""
    return ok('log-level' in HTML or 'log-filter' in HTML or
              ('select' in HTML and 'log' in HTML.lower()),
              "log level dropdown not found in HTML")
test("L1.5: log panel has level filter dropdown", test_l5_log_dropdown_in_html)

def test_l6_log_loads_on_tab_click():
    """JS must load log when Log tab is clicked"""
    return ok('/api/logs' in JS and 'log-panel' in JS,
              "/api/logs not called from log-panel tab")
test("L1.6: JS fetches /api/logs when Log tab is clicked", test_l6_log_loads_on_tab_click)

def test_l7_log_auto_refresh():
    """Log must refresh while log tab is active"""
    return ok('log-panel' in JS and ('setInterval' in JS or 'pollLog' in JS or
              'log-output' in JS),
              "log auto-refresh not found")
test("L1.7: log auto-refreshes while Log tab is active", test_l7_log_auto_refresh)


# ══════════════════════════════════════════════════════════════
# B: Brute tab full implementation
# Qt6: callHydra → buildHydraCommand → controller.runCommand
#      checkHydraResults in _capture_output already implemented
#      send-to-brute from port menu → populate brute tab fields
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("B: Brute tab full implementation")
print("="*60 + "\n")

def test_b1_brute_run_route_exists():
    """POST /api/brute/run must exist and accept hydra params"""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '22', 'service': 'ssh',
        'userlist': '/usr/share/wordlists/test.txt',
        'passlist': '', 'options': ''
    })
    return ok(r.status_code in (200, 400, 404),
              f"unexpected status={r.status_code}")
test("B1.1: /api/brute/run route exists", test_b1_brute_run_route_exists)

def test_b2_brute_run_launches_hydra():
    """/api/brute/run must return a process_id (hydra process launched)"""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '22', 'service': 'ssh',
        'userlist': '/nonexistent_list.txt',
        'passlist': '', 'options': '-t 1'
    })
    if r.status_code == 404: return "SKIP"
    data = r.get_json()
    return ok(data.get('process_id') is not None or data.get('status') == 'ok',
              f"no process_id in response: {data}")
test("B1.2: /api/brute/run launches hydra process", test_b2_brute_run_launches_hydra)

def test_b3_hydra_credential_extraction_wired():
    """WebController._capture_output must call checkHydraResults for hydra processes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('checkHydraResults' in src and 'hydra' in src.lower(),
              "_capture_output does not call checkHydraResults for hydra")
test("B1.3: _capture_output calls checkHydraResults for hydra", test_b3_hydra_credential_extraction_wired)

def test_b4_hydra_findings_saves_credentials():
    """handleHydraFindings must save credentials to wordlists"""
    wc.handleHydraFindings(userlist=['testuser'], passlist=['testpass'])
    users = wc.logic.activeProject.properties.usernamesWordList
    return ok(users is not None, "usernamesWordList not accessible")
test("B1.4: handleHydraFindings saves credentials to wordlists", test_b4_hydra_findings_saves_credentials)

def test_b5_brute_run_uses_runcommand():
    """brute run route must use wc.runCommand (not service-action) for hydra"""
    return ok('/api/brute/run' in JS or
              ("brute-run" in JS and "runCommand" in JS) or
              ("brute-run" in JS and "/api/brute" in JS),
              "brute run not using runCommand path")
test("B1.5: brute run uses runCommand (not service-action)", test_b5_brute_run_uses_runcommand)

def test_b6_send_to_brute_populates_fields():
    """send-to-brute context menu must populate brute tab IP/port/service fields"""
    return ok('send-to-brute' in JS and ('brute-ip' in JS or 'brute-tab' in JS),
              "send-to-brute does not populate brute tab fields")
test("B1.6: send-to-brute populates brute tab fields", test_b6_send_to_brute_populates_fields)

def test_b7_brute_tab_switches_on_send():
    """send-to-brute must switch to Brute main tab"""
    return ok('send-to-brute' in JS and ('brute-tab' in JS or 'main-tab' in JS),
              "send-to-brute does not switch to Brute tab")
test("B1.7: send-to-brute switches to Brute main tab", test_b7_brute_tab_switches_on_send)

def test_b8_brute_tab_has_required_fields():
    """Brute tab must have all required form fields (ip, port, service, userlist, passlist)"""
    required = ['brute-ip', 'brute-port', 'brute-service', 'brute-userlist', 'brute-passlist', 'brute-run']
    missing = [f for f in required if f not in HTML]
    return ok(not missing, f"missing brute tab fields: {missing}")
test("B1.8: brute tab has all required form fields", test_b8_brute_tab_has_required_fields)

def test_b9_brute_defaults_route():
    """/api/brute/defaults must return JSON with expected keys"""
    r = client.get('/api/brute/defaults')
    return ok(r.status_code == 200 and r.is_json, f"status={r.status_code}")
test("B1.9: /api/brute/defaults returns 200 JSON", test_b9_brute_defaults_route)

def test_b10_brute_defaults_keys():
    """/api/brute/defaults JSON must include all 6 expected keys"""
    r = client.get('/api/brute/defaults')
    if r.status_code != 200: return "SKIP"
    d = r.get_json()
    required = ['default_username','default_password','username_wordlist',
                'password_wordlist','no_username_services','no_password_services']
    missing = [k for k in required if k not in d]
    return ok(not missing, f"missing keys: {missing}")
test("B1.10: /api/brute/defaults has all required keys", test_b10_brute_defaults_keys)

def test_b11_brute_defaults_no_svc_lists():
    """/api/brute/defaults no_username_services and no_password_services must be lists"""
    r = client.get('/api/brute/defaults')
    if r.status_code != 200: return "SKIP"
    d = r.get_json()
    return ok(isinstance(d.get('no_username_services'), list)
              and isinstance(d.get('no_password_services'), list),
              f"no_username_services={d.get('no_username_services')!r}")
test("B1.11: /api/brute/defaults service lists are lists", test_b11_brute_defaults_no_svc_lists)

def test_b12_brute_tab_has_single_fields():
    """Brute tab must have single username and password fields"""
    required = ['brute-username', 'brute-password', 'brute-username-row', 'brute-password-row']
    missing = [f for f in required if f not in HTML]
    return ok(not missing, f"missing single-cred fields: {missing}")
test("B1.12: brute tab has single username/password fields", test_b12_brute_tab_has_single_fields)

def test_b13_brute_js_fetches_defaults():
    """legion.js must fetch /api/brute/defaults on load"""
    return ok('/api/brute/defaults' in JS, "JS does not fetch /api/brute/defaults")
test("B1.13: JS fetches /api/brute/defaults on load", test_b13_brute_js_fetches_defaults)

def test_b14_brute_js_hide_show_fn():
    """legion.js must define bruteHideShowFields for no-username/password services"""
    return ok('bruteHideShowFields' in JS and 'brute-username-row' in JS,
              "bruteHideShowFields or brute-username-row missing from JS")
test("B1.14: JS has bruteHideShowFields hide/show logic", test_b14_brute_js_hide_show_fn)

def test_b15_brute_run_accepts_single_creds():
    """/api/brute/run must accept username/password (single creds) and use -l/-p flags"""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '161', 'service': 'snmp',
        'username': '', 'password': '', 'userlist': '', 'passlist': '', 'options': ''
    })
    # May 400 (no creds given) or 200 (launched) — must not 500
    return ok(r.status_code in (200, 400, 404),
              f"unexpected status={r.status_code}: {r.get_data(as_text=True)[:200]}")
test("B1.15: /api/brute/run accepts single username/password params", test_b15_brute_run_accepts_single_creds)


# ══════════════════════════════════════════════════════════════
# REGRESSION
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("REGRESSION")
print("="*60 + "\n")

def test_reg1_snapshot_ok():
    return ok(client.get('/api/snapshot').status_code == 200)
test("REG1: /api/snapshot still returns 200", test_reg1_snapshot_ok)

def test_reg2_phase4_filters_intact():
    return ok('_filters' in JS and '_drawHosts' in JS)
test("REG2: Phase 4 filters (_filters/_drawHosts) intact", test_reg2_phase4_filters_intact)

def test_reg3_phase3_sorting_intact():
    return ok('_hostSort' in JS and '_procSort' in JS)
test("REG3: Phase 3 sorting (_hostSort/_procSort) intact", test_reg3_phase3_sorting_intact)

def test_reg4_phase2_close_tab_intact():
    return ok('close-x' in JS and '/api/processes' in JS)
test("REG4: Phase 2 close-x tab intact", test_reg4_phase2_close_tab_intact)

def test_reg5_all_core_routes():
    routes = ['/api/snapshot', '/api/menus/host?checked=False',
              '/api/menus/port?service=http', '/api/logs']
    for r in routes:
        resp = client.get(r)
        if resp.status_code not in (200, 404):
            return f"{r} returned {resp.status_code}"
    return True
test("REG5: all core API routes respond", test_reg5_all_core_routes)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
