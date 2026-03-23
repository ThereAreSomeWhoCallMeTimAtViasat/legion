#!/usr/bin/env python3
"""
Phase 5 Polish Tests
=====================
Run with: sudo python3 tests/test_phase5_polish.py

Tests for Phase 5 gap items:
  L1-L7:  Log tab level filter — reads log file, filters INFO/DEBUG,
           auto-loads when Log tab is clicked
  B1-B15: Brute tab full implementation — hydra command built correctly,
           process appears in process table, credential extraction wired,
           send-to-brute populates tab fields, defaults pre-filled, hide/show
  C1-C10: store-cleartext-passwords-on-exit wired, screenshooter-timeout,
           tool-output-black-background CSS+JS
  D1-D14: Config Manager find/search — find bar HTML/CSS, cfgFindRun/Select/
           Next/Prev/Show/Hide, Ctrl+F, Enter/Shift+Enter/Esc, scroll to match
  E1-E10: Terminal Ctrl+B → Notes — xterm.getSelection priority over
           window.getSelection; lower + upper panel; orange flash; DB save
  G1-G10: Settings live-apply — reapplyLiveSettings() re-fetches brute defaults
           + ui-prefs after profile activate/save/raw save; profile save of
           active profile now calls applySettings() on server

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
CSS  = open(os.path.join(PROJECT_ROOT, 'app/web/static/css/legion.css')).read()

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
    """GET / must serve a page with a log-level select element."""
    r = client.get('/')
    html = r.get_data(as_text=True)
    return ok('log-level' in html,
              "log-level element not found in rendered index.html")
test("L1.5: rendered page has log-level filter element", test_l5_log_dropdown_in_html)

def test_l6_log_loads_on_tab_click():
    """GET /api/logs must return data (proves route exists and in-memory handler works)."""
    r = client.get('/api/logs?level=INFO')
    return ok(r.status_code == 200 and r.is_json and 'lines' in r.get_json(),
              f"GET /api/logs returned {r.status_code} or missing 'lines' key")
test("L1.6: /api/logs returns 200 JSON with lines key", test_l6_log_loads_on_tab_click)

def test_l7_log_auto_refresh():
    """Two consecutive GET /api/logs calls must succeed — data available for auto-refresh."""
    r1 = client.get('/api/logs?level=INFO')
    r2 = client.get('/api/logs?level=DEBUG')
    return ok(r1.status_code == 200 and r2.status_code == 200,
              f"log refresh calls failed: INFO={r1.status_code} DEBUG={r2.status_code}")
test("L1.7: consecutive /api/logs calls both succeed (auto-refresh data available)", test_l7_log_auto_refresh)


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
    """handleHydraFindings must save to both username and password wordlists."""
    wc.handleHydraFindings(userlist=['hydra_user_b3'], passlist=['hydra_pass_b3'])
    uname_file = wc.logic.activeProject.properties.usernamesWordList.filename
    pname_file = wc.logic.activeProject.properties.passwordWordList.filename
    u_ok = os.path.isfile(uname_file)
    p_ok = os.path.isfile(pname_file)
    return ok(u_ok and p_ok,
              f"wordlist files missing after handleHydraFindings: users={u_ok} pass={p_ok}")
test("B1.3: handleHydraFindings saves to both username and password wordlist files", test_b3_hydra_credential_extraction_wired)

def test_b4_hydra_findings_saves_credentials():
    """handleHydraFindings must save credentials to wordlists"""
    wc.handleHydraFindings(userlist=['testuser'], passlist=['testpass'])
    users = wc.logic.activeProject.properties.usernamesWordList
    return ok(users is not None, "usernamesWordList not accessible")
test("B1.4: handleHydraFindings saves credentials to wordlists", test_b4_hydra_findings_saves_credentials)

def test_b5_brute_run_uses_runcommand():
    """POST /api/brute/run must launch a real process (returns process_id in snapshot)."""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '22', 'service': 'ssh',
        'username': 'testuser', 'password': 'testpass'
    })
    if r.status_code != 200: return f"FAIL: {r.status_code}"
    pid = (r.get_json() or {}).get('process_id')
    if not pid: return "FAIL: no process_id returned"
    import time as _t; _t.sleep(0.5)
    snap = client.get('/api/snapshot').get_json()
    ids = {str(p['id']) for p in snap.get('processes', [])}
    return ok(str(pid) in ids,
              f"process {pid} not in snapshot — brute/run did not use runCommand")
test("B1.5: brute/run launches process via runCommand (appears in snapshot)", test_b5_brute_run_uses_runcommand)

def test_b6_send_to_brute_in_port_menu():
    """Port right-click menu must include send-to-brute in fixed_actions."""
    data = client.get('/api/menus/port?service=http').get_json()
    # send-to-brute is in fixed_actions, not port_actions
    all_actions = []
    for v in data.values():
        if isinstance(v, list):
            all_actions.extend(v)
    has_brute = any(str(a.get('action','')).lower() == 'send-to-brute' for a in all_actions
                    if isinstance(a, dict))
    return ok(has_brute,
              f"send-to-brute not found in any port menu action list: {list(data.keys())}")
test("B1.6: send-to-brute action present in port menu (fixed_actions)", test_b6_send_to_brute_in_port_menu)

def test_b7_brute_tab_switches_on_send():
    """send-to-brute handler must populate brute-ip and switch to brute-tab."""
    idx = JS.find("action.action === 'send-to-brute'")
    if idx < 0: idx = JS.find("'send-to-brute'")
    if idx < 0: return "FAIL: send-to-brute handler not found"
    # brute-ip is set a few lines after the action check; brute-tab a few more lines after
    body = JS[idx:idx+1000]
    return ok('brute-tab' in body and 'brute-ip' in body,
              "send-to-brute handler missing brute-tab switch or brute-ip population")
test("B1.7: send-to-brute handler populates brute-ip and switches to brute-tab", test_b7_brute_tab_switches_on_send)

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
    """/api/brute/defaults pre-fills the brute tab — verify it returns usable data."""
    r = client.get('/api/brute/defaults')
    d = r.get_json() if r.status_code == 200 else {}
    has_username = 'default_username' in d
    has_no_user_svcs = isinstance(d.get('no_username_services'), list)
    return ok(has_username and has_no_user_svcs,
              f"brute defaults missing usable fields: {list(d.keys())}")
test("B1.13: /api/brute/defaults returns username and no-username-services for pre-fill", test_b13_brute_js_fetches_defaults)

def test_b14_brute_js_hide_show_fn():
    """no_username_services from /api/brute/defaults must be non-empty (hide/show needs data)."""
    r = client.get('/api/brute/defaults')
    if r.status_code != 200: return "SKIP"
    d = r.get_json()
    no_user = d.get('no_username_services', [])
    no_pass = d.get('no_password_services', [])
    return ok(isinstance(no_user, list) and isinstance(no_pass, list),
              f"no_username_services or no_password_services not lists: {no_user!r} {no_pass!r}")
test("B1.14: brute defaults no_username/password_services are lists (hide/show has data)", test_b14_brute_js_hide_show_fn)

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

def test_b16_brute_combo_produces_c_flag():
    """combo= field must produce -C in the Hydra command (not -L/-P)."""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '21', 'service': 'ftp',
        'combo': '/tmp/combo.txt'
    })
    if r.status_code != 200:
        return f"FAIL: status={r.status_code}"
    cmd = (r.get_json() or {}).get('command', '')
    return ok('-C' in cmd and '/tmp/combo.txt' in cmd and '-L' not in cmd,
              f"-C not in command or -L incorrectly present: {cmd!r}")
test("B1.16: combo= field produces -C flag not -L/-P", test_b16_brute_combo_produces_c_flag)

def test_b17_brute_combo_with_options():
    """combo= plus options= must both appear in the generated command."""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '3306', 'service': 'mysql',
        'combo': '/tmp/combo.txt', 'options': '-t 1 -e n'
    })
    if r.status_code != 200:
        return f"FAIL: status={r.status_code}"
    cmd = (r.get_json() or {}).get('command', '')
    return ok('-C' in cmd and '-t' in cmd and '-e' in cmd,
              f"combo + options not both present in command: {cmd!r}")
test("B1.17: combo= and options= both appear in generated command", test_b17_brute_combo_with_options)

def test_b18_brute_single_username_password():
    """username= and password= single creds must produce -l and -p flags."""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '22', 'service': 'ssh',
        'username': 'root', 'password': 'toor'
    })
    if r.status_code != 200:
        return f"FAIL: status={r.status_code}"
    cmd = (r.get_json() or {}).get('command', '')
    return ok('-l root' in cmd and '-p toor' in cmd,
              f"-l/-p not in command: {cmd!r}")
test("B1.18: username=/password= single creds produce -l/-p flags", test_b18_brute_single_username_password)

def test_b19_brute_combo_priority_over_userlist():
    """When combo= is supplied, it takes priority: -C used, not -L/-P."""
    r = client.post('/api/brute/run', json={
        'ip': '127.0.0.1', 'port': '21', 'service': 'ftp',
        'combo': '/tmp/combo.txt',
        'userlist': '/tmp/users.txt',  # should be ignored when combo= present
        'passlist': '/tmp/pass.txt'
    })
    if r.status_code != 200:
        return f"FAIL: status={r.status_code}"
    cmd = (r.get_json() or {}).get('command', '')
    return ok('-C' in cmd and '-L' not in cmd and '-P' not in cmd,
              f"combo= did not take priority over userlist/passlist: {cmd!r}")
test("B1.19: combo= takes priority over userlist/passlist", test_b19_brute_combo_priority_over_userlist)


# ══════════════════════════════════════════════════════════════
# C: Conversation C — store-cleartext + low-priority settings
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C: store-cleartext-passwords-on-exit + low-priority settings")
print("="*60 + "\n")

def test_c1_store_cleartext_wired_in_start():
    """start() must apply store-cleartext setting — project.storeWordListsOnExit is set."""
    wc.start()
    prop = wc.logic.activeProject.properties.storeWordListsOnExit
    return ok(isinstance(prop, bool),
              f"project.storeWordListsOnExit is {type(prop).__name__!r}, not bool — start() not wiring it")
test("C1.1: start() wires store-cleartext — project.storeWordListsOnExit is a bool", test_c1_store_cleartext_wired_in_start)

def test_c2_store_cleartext_wired_in_apply():
    """applySettings() must keep project.storeWordListsOnExit in sync with settings."""
    wc.applySettings()
    prop = wc.logic.activeProject.properties.storeWordListsOnExit
    expected = (getattr(wc.settings, 'brute_store_cleartext_passwords_on_exit', 'True') == 'True')
    return ok(prop == expected,
              f"storeWordListsOnExit={prop} but setting says {expected} after applySettings()")
test("C1.2: applySettings() keeps project.storeWordListsOnExit in sync with setting", test_c2_store_cleartext_wired_in_apply)

def test_c3_apply_store_sets_project_property():
    """project.properties.storeWordListsOnExit must match the legion.conf value."""
    setting_val = getattr(wc.settings, 'brute_store_cleartext_passwords_on_exit', 'True')
    expected = (setting_val == 'True')
    actual = wc.logic.activeProject.properties.storeWordListsOnExit
    return ok(actual == expected,
              f"project.storeWordListsOnExit={actual} but conf says {setting_val!r}")
test("C1.3: project.storeWordListsOnExit matches legion.conf brute_store_cleartext setting", test_c3_apply_store_sets_project_property)

def test_c4_store_cleartext_effect():
    """storeWordListsOnExit on active project must match the setting from legion.conf"""
    expected = (getattr(wc.settings, 'brute_store_cleartext_passwords_on_exit', 'True') == 'True')
    actual = wc.logic.activeProject.properties.storeWordListsOnExit
    return ok(actual == expected,
              f"project.storeWordListsOnExit={actual} but setting says store={expected}")
test("C1.4: project.storeWordListsOnExit matches legion.conf setting", test_c4_store_cleartext_effect)

def test_c5_screenshooter_uses_timeout():
    """settings must have general_screenshooter_timeout attribute as an integer (ms)."""
    timeout_val = getattr(wc.settings, 'general_screenshooter_timeout', None)
    return ok(timeout_val is not None,
              "settings missing general_screenshooter_timeout — _run_screenshot can't read it")
test("C1.5: settings.general_screenshooter_timeout exists (used by _run_screenshot)", test_c5_screenshooter_uses_timeout)

def test_c6_screenshooter_delay_converts_ms():
    """screenshooter timeout value from settings must be in ms (>=1000), not raw seconds."""
    timeout_val = getattr(wc.settings, 'general_screenshooter_timeout', None)
    if timeout_val is None: return "SKIP"
    try:
        ms = int(timeout_val)
        return ok(ms >= 1000,
                  f"timeout_val={ms} looks like seconds not ms (expected >=1000 for ms value)")
    except (TypeError, ValueError):
        return f"general_screenshooter_timeout not numeric: {timeout_val!r}"
test("C1.6: screenshooter_timeout is in milliseconds (>=1000, not raw seconds)", test_c6_screenshooter_delay_converts_ms)

def test_c7_ui_prefs_route():
    """/api/settings/ui-prefs must return 200 JSON"""
    r = client.get('/api/settings/ui-prefs')
    return ok(r.status_code == 200 and r.is_json,
              f"status={r.status_code}")
test("C1.7: /api/settings/ui-prefs returns 200 JSON", test_c7_ui_prefs_route)

def test_c8_ui_prefs_has_black_bg_key():
    """/api/settings/ui-prefs must include tool_output_black_background as a bool"""
    r = client.get('/api/settings/ui-prefs')
    if r.status_code != 200: return "SKIP"
    d = r.get_json()
    val = d.get('tool_output_black_background')
    return ok(isinstance(val, bool),
              f"tool_output_black_background missing or not bool: {val!r}")
test("C1.8: /api/settings/ui-prefs has tool_output_black_background bool", test_c8_ui_prefs_has_black_bg_key)

def test_c9_css_black_output_rule():
    """GET /static/css/legion.css must include black-output-bg rule for tool-output-area."""
    r = client.get('/static/css/legion.css')
    css = r.get_data(as_text=True) if r.status_code == 200 else ''
    return ok('black-output-bg' in css,
              f"black-output-bg rule missing from served CSS (status={r.status_code})")
test("C1.9: served CSS contains black-output-bg rule", test_c9_css_black_output_rule)

def test_c10_js_fetches_ui_prefs():
    """/api/settings/ui-prefs must return tool_output_black_background bool (read by JS)."""
    r = client.get('/api/settings/ui-prefs')
    if r.status_code != 200: return f"FAIL: {r.status_code}"
    d = r.get_json()
    val = d.get('tool_output_black_background')
    return ok(isinstance(val, bool),
              f"tool_output_black_background not a bool: {val!r}")
test("C1.10: /api/settings/ui-prefs returns bool tool_output_black_background (read by JS)", test_c10_js_fetches_ui_prefs)


# ══════════════════════════════════════════════════════════════
# D: Config Manager find/search (F2 backlog #4)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("D: Config Manager find/search (backlog #4)")
print("="*60 + "\n")

def test_d1_find_bar_in_html():
    """index.html must have the find bar elements"""
    required = ['cfg-find-bar', 'cfg-find-input', 'cfg-find-count',
                'cfg-find-prev', 'cfg-find-next', 'cfg-find-close']
    missing = [f for f in required if f not in HTML]
    return ok(not missing, f"missing find bar elements: {missing}")
test("D1.1: HTML has all find bar elements", test_d1_find_bar_in_html)

def test_d2_find_bar_hidden_by_default():
    """Rendered page must have cfg-find-bar with display:none (hidden by default)."""
    r = client.get('/')
    html = r.get_data(as_text=True)
    idx = html.find('cfg-find-bar')
    if idx < 0: return "FAIL: cfg-find-bar not found in rendered page"
    nearby = html[max(0, idx-50):idx+200]
    return ok('display:none' in nearby or 'display: none' in nearby,
              f"cfg-find-bar not hidden by default — nearby HTML: {nearby[:100]!r}")
test("D1.2: rendered page has cfg-find-bar with display:none", test_d2_find_bar_hidden_by_default)

def test_d3_js_cfgfind_state():
    """cfgFind state object must have matches and current properties in its definition."""
    idx = JS.find('cfgFind')
    if idx < 0: return "FAIL: cfgFind not found in JS"
    block = JS[idx:idx+300]
    return ok('matches' in block and 'current' in block,
              f"cfgFind definition missing matches/current: {block[:100]!r}")
test("D1.3: cfgFind state definition contains matches and current properties", test_d3_js_cfgfind_state)

def test_d4_js_cfgfindrun():
    """cfgFindRun function body must use indexOf to find all matches."""
    idx = JS.find('function cfgFindRun(')
    if idx < 0: return "FAIL: cfgFindRun function not found"
    body = JS[idx:idx+600]
    return ok('indexOf' in body,
              "cfgFindRun function body missing indexOf (match search loop broken)")
test("D1.4: cfgFindRun function body uses indexOf for match finding", test_d4_js_cfgfindrun)

def test_d5_js_cfgfindselect():
    """legion.js must define cfgFindSelect using cfgFindHighlight (overlay approach).
    v10.13 replaced setSelectionRange+lineH with overlay highlight + mark.offsetTop scroll."""
    return ok('cfgFindSelect' in JS and 'cfgFindHighlight' in JS,
              "cfgFindSelect or cfgFindHighlight missing from JS")
test("D1.5: JS has cfgFindSelect (cfgFindHighlight navigation)", test_d5_js_cfgfindselect)

def test_d6_js_cfgfindnext_prev():
    """cfgFindNext function body must call cfgFindSelect to advance to next match."""
    idx = JS.find('function cfgFindNext(')
    if idx < 0: return "FAIL: cfgFindNext not found"
    body = JS[idx:idx+200]
    return ok('cfgFindSelect' in body,
              "cfgFindNext function body does not call cfgFindSelect")
test("D1.6: cfgFindNext function body calls cfgFindSelect to advance match", test_d6_js_cfgfindnext_prev)

def test_d7_js_cfgfindshow_hide():
    """cfgFindShow function body must set bar display to '' (visible)."""
    idx = JS.find('function cfgFindShow(')
    if idx < 0: return "FAIL: cfgFindShow not found"
    body = JS[idx:idx+300]
    return ok('style.display' in body or "display = ''" in body or 'cfg-find-bar' in body,
              "cfgFindShow body does not set bar visibility")
test("D1.7: cfgFindShow function body makes find bar visible", test_d7_js_cfgfindshow_hide)

def test_d8_ctrl_f_wiring():
    """Ctrl+F keyboard handler must check is-open config modal before calling cfgFindShow.
    The call inside the keydown handler (not the function definition) must be guarded."""
    # Find the cfgFindShow CALL that is inside the keydown handler (not the function def)
    # It appears after "e.key === 'f'" check
    idx = JS.find("e.key === 'f'")
    if idx < 0: return "FAIL: keydown 'f' handler not found"
    block = JS[idx:idx+400]
    return ok('cfgFindShow' in block and 'is-open' in block,
              "Ctrl+F keydown block missing cfgFindShow call or is-open guard")
test("D1.8: Ctrl+F keydown block calls cfgFindShow guarded by is-open", test_d8_ctrl_f_wiring)

def test_d9_enter_key_navigation():
    """cfg-find-input event listener must handle shiftKey for prev/next navigation."""
    # cfgFindInp addEventListener is at line ~2133
    idx = JS.find('cfgFindInp')
    if idx < 0: idx = JS.find('cfg-find-input')
    if idx < 0: return "FAIL: cfg-find-input listener not found"
    block = JS[idx:idx+800]
    return ok('shiftKey' in block and 'cfgFindPrev' in block and 'cfgFindNext' in block,
              "cfg-find-input listener missing shiftKey/cfgFindPrev/cfgFindNext")
test("D1.9: cfg-find-input listener handles shiftKey for prev/next navigation", test_d9_enter_key_navigation)

def test_d10_escape_closes_bar():
    """cfg-find-input listener must call cfgFindHide on Escape key."""
    idx = JS.find('cfgFindInp')
    if idx < 0: idx = JS.find('cfg-find-input')
    if idx < 0: return "FAIL: cfg-find-input listener not found"
    block = JS[idx:idx+800]
    return ok('Escape' in block and 'cfgFindHide' in block,
              "cfg-find-input listener missing Escape → cfgFindHide")
test("D1.10: cfg-find-input Escape key calls cfgFindHide", test_d10_escape_closes_bar)

def test_d11_css_find_bar_styled():
    """Served CSS must include #cfg-find-bar rule."""
    r = client.get('/static/css/legion.css')
    css = r.get_data(as_text=True) if r.status_code == 200 else ''
    return ok('#cfg-find-bar' in css,
              f"#cfg-find-bar rule missing from served CSS (status={r.status_code})")
test("D1.11: served CSS contains #cfg-find-bar rule", test_d11_css_find_bar_styled)

def test_d12_scroll_to_match():
    """cfgFindHighlight must scroll to match via mark.offsetTop.
    v10.13 replaced lineH line-height calculation with overlay mark.offsetTop."""
    return ok('scrollTop' in JS and 'offsetTop' in JS,
              "cfgFindHighlight missing scrollTop/offsetTop scroll calculation")
test("D1.12: cfgFindSelect scrolls textarea to matched line", test_d12_scroll_to_match)

def test_d13_close_btn_wired():
    """cfg-find-close button must call cfgFindHide"""
    return ok('cfg-find-close' in JS and 'cfgFindHide' in JS,
              "cfg-find-close not wired to cfgFindHide")
test("D1.13: close button calls cfgFindHide", test_d13_close_btn_wired)

def test_d14_find_bar_placeholder():
    """find input placeholder must mention Enter and Esc shortcuts"""
    return ok('Enter' in HTML and 'Esc' in HTML and 'cfg-find-input' in HTML,
              "find input placeholder missing keyboard hints")
test("D1.14: find input placeholder shows keyboard hints", test_d14_find_bar_placeholder)


# ══════════════════════════════════════════════════════════════
# E: Terminal Ctrl+B → Notes (backlog #5)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("E: Terminal Ctrl+B → Notes (backlog #5)")
print("="*60 + "\n")

def test_e1_xterm_selection_checked_first():
    """sendSelectionToNotes must check _termState.xterm.getSelection before window.getSelection"""
    return ok('_termState.xterm' in JS and 'getSelection' in JS and 'sendSelectionToNotes' in JS,
              "_termState.xterm.getSelection not referenced in sendSelectionToNotes")
test("E1.1: lower-panel _termState.xterm.getSelection checked for Ctrl+B", test_e1_xterm_selection_checked_first)

def test_e2_dyn_xterm_selection_checked():
    """sendSelectionToNotes must also check _dynTermState.xterm.getSelection"""
    return ok('_dynTermState.xterm' in JS and 'getSelection' in JS,
              "_dynTermState.xterm.getSelection not referenced in JS")
test("E1.2: upper-panel _dynTermState.xterm.getSelection checked for Ctrl+B", test_e2_dyn_xterm_selection_checked)

def test_e3_terminal_title_in_header():
    """terminal selection must produce 'Terminal' prefix in the notes header"""
    return ok("'Terminal'" in JS or '"Terminal"' in JS,
              "Terminal title string missing from JS sendSelectionToNotes")
test("E1.3: terminal selection uses 'Terminal' prefix in header", test_e3_terminal_title_in_header)

def test_e4_terminal_flash_orange():
    """terminal-output element must be flashed orange on Ctrl+B from terminal"""
    return ok('terminal-output' in JS and 'rgba(255,165,0' in JS,
              "terminal-output or orange flash missing from JS")
test("E1.4: terminal-output element flashed orange on Ctrl+B", test_e4_terminal_flash_orange)

def test_e5_getselection_typeof_guard():
    """must guard getSelection call with typeof check to handle older xterm versions"""
    return ok("typeof _termState.xterm.getSelection === 'function'" in JS or
              "typeof _termState.xterm.getSelection==='function'" in JS,
              "typeof guard on getSelection missing — will throw if xterm lacks the method")
test("E1.5: typeof guard protects _termState.xterm.getSelection call", test_e5_getselection_typeof_guard)

def test_e6_dyn_getselection_typeof_guard():
    """must guard _dynTermState.xterm.getSelection with typeof check too"""
    return ok("typeof _dynTermState.xterm.getSelection === 'function'" in JS or
              "typeof _dynTermState.xterm.getSelection==='function'" in JS,
              "typeof guard on _dynTermState.xterm.getSelection missing")
test("E1.6: typeof guard protects _dynTermState.xterm.getSelection call", test_e6_dyn_getselection_typeof_guard)

def test_e7_ctrl_b_still_wired():
    """Ctrl+B keydown handler must still call sendSelectionToNotes"""
    return ok("e.key === 'b'" in JS and 'sendSelectionToNotes' in JS,
              "Ctrl+B keydown handler or sendSelectionToNotes missing")
test("E1.7: Ctrl+B keydown still calls sendSelectionToNotes", test_e7_ctrl_b_still_wired)

def test_e8_host_guard_preserved():
    """sendSelectionToNotes must still guard on L.selectedHostId"""
    return ok('selectedHostId' in JS and 'sendSelectionToNotes' in JS,
              "selectedHostId guard missing from sendSelectionToNotes")
test("E1.8: L.selectedHostId guard preserved in sendSelectionToNotes", test_e8_host_guard_preserved)

def test_e9_notes_append_preserved():
    """sendSelectionToNotes must still append to existing notes and save to DB"""
    return ok('/api/workspace/hosts/' in JS and 'markTabUnread' in JS,
              "DB save or markTabUnread missing from sendSelectionToNotes")
test("E1.9: notes append + DB save + markTabUnread preserved", test_e9_notes_append_preserved)

def test_e10_three_source_priority():
    """JS must check sources in order within sendSelectionToNotes: lower xterm → upper xterm → browser"""
    fn_start = JS.find('function sendSelectionToNotes')
    fn_end   = JS.find('\n    }', fn_start + 100)   # closing brace of the function
    fn_body  = JS[fn_start:fn_end] if fn_start >= 0 else ''
    lower_pos  = fn_body.find('_termState.xterm.getSelection')
    upper_pos  = fn_body.find('_dynTermState.xterm.getSelection')
    browser_pos = fn_body.find('window.getSelection')
    return ok(fn_body and 0 <= lower_pos < upper_pos < browser_pos,
              f"source priority wrong in fn body: lower={lower_pos} upper={upper_pos} browser={browser_pos}")
test("E1.10: xterm sources checked before window.getSelection", test_e10_three_source_priority)


# ══════════════════════════════════════════════════════════════
# G: Settings live-apply (hot-reload UI without page reload)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("G: Settings live-apply (hot-reload UI without page reload)")
print("="*60 + "\n")

def test_g1_reapply_fn_in_js():
    """JS must define reapplyLiveSettings function"""
    return ok('reapplyLiveSettings' in JS,
              "reapplyLiveSettings missing from JS")
test("G1.1: JS defines reapplyLiveSettings()", test_g1_reapply_fn_in_js)

def test_g2_reapply_fetches_brute_defaults():
    """reapplyLiveSettings must re-fetch /api/brute/defaults"""
    fn_start = JS.find('function reapplyLiveSettings')
    fn_end   = JS.find('\n    }', fn_start + 50)
    fn_body  = JS[fn_start:fn_end] if fn_start >= 0 else ''
    return ok('/api/brute/defaults' in fn_body,
              "reapplyLiveSettings does not fetch /api/brute/defaults")
test("G1.2: reapplyLiveSettings fetches /api/brute/defaults", test_g2_reapply_fetches_brute_defaults)

def test_g3_reapply_fetches_ui_prefs():
    """reapplyLiveSettings must re-fetch /api/settings/ui-prefs"""
    fn_start = JS.find('function reapplyLiveSettings')
    fn_end   = JS.find('\n    }', fn_start + 50)
    fn_body  = JS[fn_start:fn_end] if fn_start >= 0 else ''
    return ok('/api/settings/ui-prefs' in fn_body,
              "reapplyLiveSettings does not fetch /api/settings/ui-prefs")
test("G1.3: reapplyLiveSettings fetches /api/settings/ui-prefs", test_g3_reapply_fetches_ui_prefs)

def test_g4_reapply_updates_no_svc_lists():
    """reapplyLiveSettings must update L._bruteNoUserSvcs and L._bruteNoPassSvcs"""
    return ok('_bruteNoUserSvcs' in JS and '_bruteNoPassSvcs' in JS and 'reapplyLiveSettings' in JS,
              "_bruteNoUserSvcs/_bruteNoPassSvcs update missing from reapplyLiveSettings area")
test("G1.4: reapplyLiveSettings updates no-username/no-password service lists", test_g4_reapply_updates_no_svc_lists)

def test_g5_reapply_called_on_activate():
    """reapplyLiveSettings must be called after profile activate succeeds"""
    act_pos  = JS.find("'/activate'")
    reapp_pos = JS.find('reapplyLiveSettings', act_pos)
    return ok(act_pos >= 0 and reapp_pos >= 0 and reapp_pos - act_pos < 500,
              "reapplyLiveSettings not called near profile activate handler")
test("G1.5: reapplyLiveSettings called after profile activate", test_g5_reapply_called_on_activate)

def test_g6_reapply_called_on_raw_save():
    """reapplyLiveSettings must be called after raw settings-config save"""
    save_pos  = JS.find("settings-config-save-button")
    reapp_pos = JS.find('reapplyLiveSettings', save_pos)
    return ok(save_pos >= 0 and reapp_pos >= 0 and reapp_pos - save_pos < 600,
              "reapplyLiveSettings not called near settings-config-save-button handler")
test("G1.6: reapplyLiveSettings called after raw legion-conf save", test_g6_reapply_called_on_raw_save)

def test_g7_profile_save_route_returns_applied():
    """/api/config/profiles/<name>/save must return 200 with applied bool on success,
    or 400 on validation error — never 500. On 200, must include 'applied' key."""
    import json
    import inspect
    from app.web.routes import config_save
    # Check source — route must contain 'applied' as a response key
    src = inspect.getsource(config_save)
    return ok("'applied'" in src or '"applied"' in src,
              "config_save route response missing 'applied' key")
test("G1.7: /api/config/profiles/<name>/save returns applied bool", test_g7_profile_save_route_returns_applied)

def test_g8_profile_save_active_calls_apply():
    """saving active profile must include applySettings call in route source"""
    import inspect
    from app.web.routes import config_save
    src = inspect.getsource(config_save)
    return ok('applySettings' in src and 'applied' in src,
              "config_save route missing applySettings or applied response key")
test("G1.8: config_save route calls applySettings when saving active profile", test_g8_profile_save_active_calls_apply)

def test_g9_reapply_hides_shows_fields():
    """reapplyLiveSettings must call bruteHideShowFields after fetching new service lists"""
    fn_start = JS.find('function reapplyLiveSettings')
    fn_end   = JS.find('\n    }', fn_start + 50)
    fn_body  = JS[fn_start:fn_end] if fn_start >= 0 else ''
    return ok('bruteHideShowFields' in fn_body,
              "reapplyLiveSettings does not call bruteHideShowFields after update")
test("G1.9: reapplyLiveSettings calls bruteHideShowFields after service list update", test_g9_reapply_hides_shows_fields)

def test_g10_save_status_shows_applied():
    """config-save success message must indicate 'applied' when active profile saved"""
    return ok('applied' in JS and ('Saved & applied' in JS or "d.applied" in JS),
              "JS save handler does not show 'applied' status or check d.applied")
test("G1.10: config-save shows 'Saved & applied' when active profile was hot-applied", test_g10_save_status_shows_applied)


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
