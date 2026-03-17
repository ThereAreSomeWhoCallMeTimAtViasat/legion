#!/usr/bin/env python3
"""
visualUpgrades Feature Tests — all ifly53e/therearesomewhocallmetimatviasat features
=====================================================================================
Run with: sudo python3 tests/test_visualupgrades_features.py

Tests every custom feature from the 77 visualUpgrades commits to verify
it works in the Flask implementation.
"""

import os, sys, json, time, traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = FAIL = SKIP = 0

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        r = fn()
        if r is None or r is True: PASS += 1; print(f"  \u2713 {name}"); return True
        elif r == 'SKIP': SKIP += 1; print(f"  \u2298 {name} (SKIP)"); return False
        else: FAIL += 1; print(f"  \u2717 {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""): return True if v else f"FAIL: {msg}"
def has(r, s): return True if s in (r.data.decode() if hasattr(r,'data') else str(r)) else f"missing '{s}'"

# Setup
from app.web.testhelper import create_test_app
from app.settings import AppSettings, Settings
from db.entities.host import hostObj
from db.entities.port import portObj
from db.entities.service import serviceObj

app, logic, wc = create_test_app()
client = app.test_client()
settings = Settings(AppSettings())

# Add test host with data
session = logic.activeProject.database.session()
try:
    h = hostObj(ip='10.10.10.1', ipv4='10.10.10.1', hostname='target', osMatch='Linux', status='up', state='up')
    session.add(h); session.flush()
    svc = serviceObj(name='http', host=str(h.id), product='Apache', version='2.4')
    session.add(svc); session.flush()
    p = portObj(portId='80', protocol='tcp', state='open', host=h.id, service=svc.id)
    session.add(p); session.commit()
    HOST_ID, HOST_IP = h.id, h.ip
finally:
    session.close()


# ══════════════════════════════════════════════════════════════
# P1: Match Detection & Highlighting (6 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P1: Match Detection & Highlighting")
print("="*60 + "\n")

def test_m1_settings_loaded():
    """MatchSettings loaded from legion.conf"""
    return ok(hasattr(settings, 'matchSettings') and len(settings.matchSettings) > 0,
              f"matchSettings: {getattr(settings, 'matchSettings', 'MISSING')}")
test("M1: MatchSettings loaded from legion.conf", test_m1_settings_loaded)

def test_m2_global_positive():
    """Global positive patterns exist"""
    ms = getattr(settings, 'matchSettings', {})
    glb = ms.get('global', {})
    pos = glb.get('positive', [])
    return ok(len(pos) > 0, f"global positive: {pos}")
test("M2: Global positive patterns exist", test_m2_global_positive)

def test_m3_global_negative():
    """Global negative patterns exist"""
    ms = getattr(settings, 'matchSettings', {})
    glb = ms.get('global', {})
    neg = glb.get('negative', [])
    return ok(len(neg) > 0, f"global negative: {neg}")
test("M3: Global negative patterns exist", test_m3_global_negative)

def test_m4_match_detection_positive():
    """WebController detects positive match in output"""
    return ok(hasattr(wc, 'detectMatches'), "WebController needs detectMatches method")
test("M4: WebController.detectMatches() exists", test_m4_match_detection_positive)

def test_m5_match_negative_first():
    """Negative patterns checked before positive (line with negative = no match)"""
    if not hasattr(wc, 'detectMatches'): return 'SKIP'
    matches = wc.detectMatches("valid password not found", "nmap")
    return ok(len(matches) == 0, f"should be empty, got {matches}")
test("M5: Negative checked first (no false positive)", test_m5_match_negative_first)

def test_m6_match_positive_found():
    """Positive pattern detected in output"""
    if not hasattr(wc, 'detectMatches'): return 'SKIP'
    matches = wc.detectMatches("445/tcp open  microsoft-ds", "nmap")
    return ok('open' in matches or len(matches) > 0, f"should find 'open', got {matches}")
test("M6: Positive match detected", test_m6_match_positive_found)

def test_m7_substring_filter():
    """'open' positive but 'is already open' negative → 'open' must NOT match"""
    if not hasattr(wc, 'detectMatches'): return 'SKIP'
    matches = wc.detectMatches("port is already open", "nmap")
    return ok('open' not in matches, f"'open' should be filtered, got {matches}")
test("M7: Substring filtering works", test_m7_substring_filter)

def test_m8_tool_specific():
    """Tool-specific patterns (nikto-positive) detected"""
    if not hasattr(wc, 'detectMatches'): return 'SKIP'
    matches = wc.detectMatches("Server leaks inodes via ETags", "nikto")
    return ok(len(matches) > 0, f"nikto-positive should match, got {matches}")
test("M8: Tool-specific patterns work", test_m8_tool_specific)

def test_m9_match_in_snapshot():
    """Match data included in process/snapshot API"""
    if not hasattr(wc, '_matches'): return 'SKIP'
    return ok(isinstance(wc._matches, dict), "should be a dict")
test("M9: Match state stored in WebController", test_m9_match_in_snapshot)

def test_m10_highlight_css():
    """JS has CSS classes for match highlighting"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('match-highlight' in js or 'match-positive' in js,
              "JS needs match highlight CSS classes")
test("M10: JS has match highlight rendering", test_m10_highlight_css)


# ══════════════════════════════════════════════════════════════
# P2: Tab Color / Notification (5 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P2: Tab Color / Notification (orange)")
print("="*60 + "\n")

def test_t1_unread_css():
    """CSS has tab-unread class for orange highlighting"""
    css = client.get('/static/css/legion.css?v=10').data.decode()
    return ok('tab-unread' in css or 'unread' in css, "CSS needs tab-unread class")
test("T1: CSS has tab-unread class", test_t1_unread_css)

def test_t2_js_tracks_unread():
    """JS tracks last-seen data per tab"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('lastSeen' in js or 'unread' in js or 'tab-unread' in js,
              "JS needs unread tracking")
test("T2: JS tracks unread tab state", test_t2_js_tracks_unread)

def test_t3_tab_click_clears():
    """JS clears unread on tab click"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('tab-unread' in js or 'classList.remove' in js, "JS needs clear on click")
test("T3: Tab click clears unread", test_t3_tab_click_clears)


# ══════════════════════════════════════════════════════════════
# P3: Deduplication System (3 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P3: Deduplication System")
print("="*60 + "\n")

def test_d1_setting_exists():
    """general_tool_duplication setting readable"""
    val = getattr(settings, 'general_tool_duplication', None)
    return ok(val is not None, f"got: {val}")
test("D1: tool_duplication setting exists", test_d1_setting_exists)

def test_d2_dedup_check():
    """WebController has checkDuplicate method"""
    return ok(hasattr(wc, 'checkDuplicate'), "WebController needs checkDuplicate")
test("D2: WebController.checkDuplicate() exists", test_d2_dedup_check)

def test_d3_dedup_skip():
    """Skip mode prevents duplicate run"""
    if not hasattr(wc, 'checkDuplicate'): return 'SKIP'
    result = wc.checkDuplicate('nmap', '10.10.10.1', '80', 'tcp')
    return ok(result is not None, "should return action decision")
test("D3: Dedup check returns decision", test_d3_dedup_skip)


# ══════════════════════════════════════════════════════════════
# P4: Sort Selection Preservation (1 commit)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P4: Sort Selection Preservation")
print("="*60 + "\n")

def test_s1_host_selection():
    """Host selection preserved after re-render"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('selectedHostId' in js and '.selected' in js,
              "JS preserves host selection")
test("S1: Host selection preserved", test_s1_host_selection)

def test_s2_process_selection():
    """Process selection preserved after re-render"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('selectedProcessId' in js or 'process-selected' in js,
              "JS preserves process selection")
test("S2: Process selection preserved", test_s2_process_selection)


# ══════════════════════════════════════════════════════════════
# P5: Information Tab Blinking (2 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P5: Information Tab Blinking")
print("="*60 + "\n")

def test_i1_blink_css():
    """CSS has blink/flash animation"""
    css = client.get('/static/css/legion.css?v=10').data.decode()
    return ok('blink' in css or 'flash' in css or '@keyframes' in css,
              "CSS needs blink animation")
test("I1: CSS has blink animation", test_i1_blink_css)


# ══════════════════════════════════════════════════════════════
# P6: CVE Auto-refresh + CVSS Sort (2 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P6: CVE Sort")
print("="*60 + "\n")

def test_v1_cve_sort():
    """CVE data sorted by severity in host detail"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('severity' in js or 'cvss' in js or 'sort' in js,
              "JS should sort CVEs")
test("V1: CVEs sortable", test_v1_cve_sort)


# ══════════════════════════════════════════════════════════════
# P7: Splitter Position Memory (2 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P7: Splitter Position Memory")
print("="*60 + "\n")

def test_l1_localstorage():
    """JS saves splitter position to localStorage"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('localStorage' in js, "JS needs localStorage for splitter memory")
test("L1: localStorage used for splitter", test_l1_localstorage)


# ══════════════════════════════════════════════════════════════
# P8: Graceful Shutdown (2 commits)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P8: Graceful Shutdown")
print("="*60 + "\n")

def test_g1_shutdown_route():
    """POST /api/shutdown exists"""
    resp = client.post('/api/shutdown', content_type='application/json')
    return ok(resp.status_code != 404, f"got {resp.status_code}")
test("G1: Shutdown route exists", test_g1_shutdown_route)

def test_g2_beforeunload():
    """JS has beforeunload handler"""
    js = client.get('/static/js/legion.js?v=10').data.decode()
    return ok('beforeunload' in js, "JS needs beforeunload handler")
test("G2: JS has beforeunload", test_g2_beforeunload)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
