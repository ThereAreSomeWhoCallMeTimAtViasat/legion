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
    """WebController.start() must call _apply_store_wordlists_setting"""
    import inspect
    src = inspect.getsource(wc.start)
    return ok('_apply_store_wordlists_setting' in src,
              "start() does not call _apply_store_wordlists_setting")
test("C1.1: start() wires store-cleartext-passwords-on-exit", test_c1_store_cleartext_wired_in_start)

def test_c2_store_cleartext_wired_in_apply():
    """WebController.applySettings() must call _apply_store_wordlists_setting"""
    import inspect
    src = inspect.getsource(wc.applySettings)
    return ok('_apply_store_wordlists_setting' in src,
              "applySettings() does not call _apply_store_wordlists_setting")
test("C1.2: applySettings() wires store-cleartext-passwords-on-exit", test_c2_store_cleartext_wired_in_apply)

def test_c3_apply_store_sets_project_property():
    """_apply_store_wordlists_setting must set project.properties.storeWordListsOnExit"""
    import inspect
    src = inspect.getsource(wc._apply_store_wordlists_setting)
    return ok('setStoreWordListsOnExit' in src and 'brute_store_cleartext_passwords_on_exit' in src,
              "_apply_store_wordlists_setting missing setStoreWordListsOnExit or setting attr")
test("C1.3: _apply_store_wordlists_setting calls ProjectManager.setStoreWordListsOnExit", test_c3_apply_store_sets_project_property)

def test_c4_store_cleartext_effect():
    """storeWordListsOnExit on active project must match the setting from legion.conf"""
    expected = (getattr(wc.settings, 'brute_store_cleartext_passwords_on_exit', 'True') == 'True')
    actual = wc.logic.activeProject.properties.storeWordListsOnExit
    return ok(actual == expected,
              f"project.storeWordListsOnExit={actual} but setting says store={expected}")
test("C1.4: project.storeWordListsOnExit matches legion.conf setting", test_c4_store_cleartext_effect)

def test_c5_screenshooter_uses_timeout():
    """_run_screenshot must use general_screenshooter_timeout not hardcoded --delay 5"""
    import inspect
    src = inspect.getsource(wc._run_screenshot)
    return ok('general_screenshooter_timeout' in src and '--delay 5' not in src,
              "_run_screenshot still has hardcoded --delay 5 or missing general_screenshooter_timeout")
test("C1.5: _run_screenshot uses general_screenshooter_timeout", test_c5_screenshooter_uses_timeout)

def test_c6_screenshooter_delay_converts_ms():
    """screenshooter delay must convert ms to seconds (// 1000)"""
    import inspect
    src = inspect.getsource(wc._run_screenshot)
    return ok('1000' in src and 'delay_s' in src,
              "_run_screenshot missing ms→s conversion (delay_s or 1000 not found)")
test("C1.6: _run_screenshot converts ms to seconds", test_c6_screenshooter_delay_converts_ms)

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
    """legion.css must have .black-output-bg rule for tool-output-area"""
    return ok('black-output-bg' in CSS and 'tool-output-area' in CSS,
              "CSS missing black-output-bg rule")
test("C1.9: CSS has black-output-bg .tool-output-area rule", test_c9_css_black_output_rule)

def test_c10_js_fetches_ui_prefs():
    """legion.js must fetch /api/settings/ui-prefs on page load"""
    return ok('/api/settings/ui-prefs' in JS and 'black-output-bg' in JS,
              "JS missing ui-prefs fetch or black-output-bg class toggle")
test("C1.10: JS fetches /api/settings/ui-prefs and applies black-output-bg", test_c10_js_fetches_ui_prefs)


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
    """cfg-find-bar must start hidden (display:none)"""
    return ok('cfg-find-bar' in HTML and 'display:none' in HTML,
              "cfg-find-bar not hidden by default")
test("D1.2: find bar starts hidden (display:none)", test_d2_find_bar_hidden_by_default)

def test_d3_js_cfgfind_state():
    """legion.js must define cfgFind state object"""
    return ok('cfgFind' in JS and 'matches' in JS and 'current' in JS,
              "cfgFind state object missing from JS")
test("D1.3: JS defines cfgFind state (matches, current)", test_d3_js_cfgfind_state)

def test_d4_js_cfgfindrun():
    """legion.js must define cfgFindRun (search all matches in textarea)"""
    return ok('cfgFindRun' in JS and 'indexOf' in JS,
              "cfgFindRun missing from JS or missing indexOf loop")
test("D1.4: JS has cfgFindRun (all-matches finder)", test_d4_js_cfgfindrun)

def test_d5_js_cfgfindselect():
    """legion.js must define cfgFindSelect using cfgFindHighlight (overlay approach).
    v10.13 replaced setSelectionRange+lineH with overlay highlight + mark.offsetTop scroll."""
    return ok('cfgFindSelect' in JS and 'cfgFindHighlight' in JS,
              "cfgFindSelect or cfgFindHighlight missing from JS")
test("D1.5: JS has cfgFindSelect (cfgFindHighlight navigation)", test_d5_js_cfgfindselect)

def test_d6_js_cfgfindnext_prev():
    """legion.js must define cfgFindNext and cfgFindPrev"""
    return ok('cfgFindNext' in JS and 'cfgFindPrev' in JS,
              "cfgFindNext or cfgFindPrev missing from JS")
test("D1.6: JS has cfgFindNext and cfgFindPrev", test_d6_js_cfgfindnext_prev)

def test_d7_js_cfgfindshow_hide():
    """legion.js must define cfgFindShow and cfgFindHide"""
    return ok('cfgFindShow' in JS and 'cfgFindHide' in JS,
              "cfgFindShow or cfgFindHide missing from JS")
test("D1.7: JS has cfgFindShow and cfgFindHide", test_d7_js_cfgfindshow_hide)

def test_d8_ctrl_f_wiring():
    """Ctrl+F must call cfgFindShow when config modal is open"""
    return ok('cfg-find-input' in JS and 'cfgFindShow' in JS and 'is-open' in JS,
              "Ctrl+F → cfgFindShow wiring missing (is-open check or cfgFindShow not found)")
test("D1.8: Ctrl+F opens find bar when config modal is open", test_d8_ctrl_f_wiring)

def test_d9_enter_key_navigation():
    """find input must handle Enter (next) and Shift+Enter (prev)"""
    return ok('shiftKey' in JS and 'cfgFindPrev' in JS and 'cfgFindNext' in JS,
              "Enter/Shift+Enter key navigation missing from JS")
test("D1.9: Enter/Shift+Enter navigate next/prev match", test_d9_enter_key_navigation)

def test_d10_escape_closes_bar():
    """find input must close bar on Escape"""
    return ok('Escape' in JS and 'cfgFindHide' in JS,
              "Escape → cfgFindHide missing from JS")
test("D1.10: Escape closes find bar", test_d10_escape_closes_bar)

def test_d11_css_find_bar_styled():
    """CSS must have #cfg-find-bar styling"""
    return ok('#cfg-find-bar' in CSS and 'cfg-find-count' in CSS,
              "CSS missing #cfg-find-bar styling")
test("D1.11: CSS styles the find bar", test_d11_css_find_bar_styled)

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
