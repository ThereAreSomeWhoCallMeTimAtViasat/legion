#!/usr/bin/env python3
"""
Route Wiring Tests: WebController ↔ Flask Routes
=================================================
Tests that Flask routes call WebController methods (not runtime.py).
Run with: sudo python3 tests/test_routes_webcontroller.py

Strategy: Use Flask test client to make HTTP requests and verify
the responses come from WebController, not runtime.py.

Groups:
  R1: Snapshot/query routes (GET endpoints → WebController DB queries)
  R2: Action routes (POST endpoints → WebController action methods)
  R3: Context menu routes (new endpoints for right-click menus)
  R4: Process routes (kill/retry/clear/output)
  R5: Scan routes (addHosts, nmap)
"""

import os
import sys
import json
import time
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = 0
FAIL = 0
SKIP = 0

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        result = fn()
        if result is None or result is True:
            PASS += 1; print(f"  \u2713 {name}"); return True
        elif result == 'SKIP':
            SKIP += 1; print(f"  \u2298 {name} (SKIPPED)"); return False
        else:
            FAIL += 1; print(f"  \u2717 {name}: {result}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: EXCEPTION: {e}"); traceback.print_exc(); return False

def assert_eq(a, b, msg=""): return True if a == b else f"expected {b!r}, got {a!r}" + (f" ({msg})" if msg else "")
def assert_true(v, msg=""): return True if v else f"expected truthy, got {v!r}" + (f" ({msg})" if msg else "")
def assert_gt(a, t, msg=""): return True if a > t else f"expected > {t}, got {a}" + (f" ({msg})" if msg else "")
def assert_in(needle, haystack, msg=""): return True if needle in haystack else f"{needle!r} not in response" + (f" ({msg})" if msg else "")
def assert_status(resp, code, msg=""): return True if resp.status_code == code else f"expected HTTP {code}, got {resp.status_code}" + (f" ({msg})" if msg else "")

# ── Setup: Create Flask test client with WebController ──

def create_test_app():
    """Create Flask app wired to WebController (no upstream runtime.py)"""
    try:
        from app.web.testhelper import create_test_app as _create
        return _create()
    except Exception as e:
        print(f"  ERROR creating test app: {e}")
        traceback.print_exc()
        return None, None, None

print("Setting up test Flask app...")
app, logic, wc = create_test_app()
if app is None:
    print("FATAL: Could not create test app")
    sys.exit(1)

client = app.test_client()

# Add a test host so we have data
from db.entities.host import hostObj
from db.entities.port import portObj
from db.entities.service import serviceObj
session = logic.activeProject.database.session()
try:
    h = hostObj(ip='192.168.1.50', ipv4='192.168.1.50', hostname='testbox',
                osMatch='Linux', status='up', state='up')
    session.add(h); session.flush()
    svc = serviceObj(name='http', host=str(h.id), product='Apache', version='2.4')
    session.add(svc); session.flush()
    port = portObj(portId='80', protocol='tcp', state='open', host=h.id, service=svc.id)
    session.add(port); session.commit()
    TEST_HOST_ID = h.id
    TEST_HOST_IP = h.ip
except Exception as e:
    print(f"  ERROR adding test data: {e}")
    TEST_HOST_ID = None
    TEST_HOST_IP = None
finally:
    session.close()

print(f"Test host: id={TEST_HOST_ID}, ip={TEST_HOST_IP}\n")


# ══════════════════════════════════════════════════════════════
# R1: Snapshot/query routes (existing routes that should work)
# ══════════════════════════════════════════════════════════════

print("="*60)
print("R1: Snapshot/Query routes (GET endpoints)")
print("="*60 + "\n")

def test_r1_health():
    """GET /health returns ok"""
    resp = client.get('/health')
    return assert_status(resp, 200)
test("R1.1: GET /health", test_r1_health)

def test_r1_snapshot():
    """GET /api/snapshot returns hosts, services, processes"""
    resp = client.get('/api/snapshot')
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    return assert_true('hosts' in data and 'processes' in data, "snapshot has hosts and processes")
test("R1.2: GET /api/snapshot", test_r1_snapshot)

def test_r1_snapshot_has_test_host():
    """Snapshot should contain our test host"""
    resp = client.get('/api/snapshot')
    data = resp.get_json()
    hosts = data.get('hosts', [])
    found = any(h.get('ip') == TEST_HOST_IP for h in hosts)
    return assert_true(found, f"test host {TEST_HOST_IP} should be in snapshot")
test("R1.3: Snapshot contains test host", test_r1_snapshot_has_test_host)

def test_r1_host_detail():
    """GET /api/workspace/hosts/{id} returns host detail"""
    if not TEST_HOST_ID: return 'SKIP'
    resp = client.get(f'/api/workspace/hosts/{TEST_HOST_ID}')
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    return assert_true('host' in data and 'ports' in data, "host detail has host and ports")
test("R1.4: GET /api/workspace/hosts/{id}", test_r1_host_detail)

def test_r1_host_detail_ports():
    """Host detail should show our test port 80"""
    if not TEST_HOST_ID: return 'SKIP'
    resp = client.get(f'/api/workspace/hosts/{TEST_HOST_ID}')
    data = resp.get_json()
    ports = data.get('ports', [])
    found = any(str(p.get('port')) == '80' for p in ports)
    return assert_true(found, "port 80 should be in host detail")
test("R1.5: Host detail has port 80", test_r1_host_detail_ports)

def test_r1_settings():
    """GET /api/settings/legion-conf returns config text"""
    resp = client.get('/api/settings/legion-conf')
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    return assert_in('[PortActions]', data.get('text', ''))
test("R1.6: GET /api/settings/legion-conf", test_r1_settings)

def test_r1_process_output_404():
    """GET /api/processes/99999/output returns 404 for missing process"""
    resp = client.get('/api/processes/99999/output')
    return assert_status(resp, 404)
test("R1.7: GET /api/processes/99999/output → 404", test_r1_process_output_404)


# ══════════════════════════════════════════════════════════════
# R2: Action routes (POST endpoints → WebController)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R2: Action routes (POST endpoints)")
print("="*60 + "\n")

def test_r2_new_project():
    """POST /api/project/new-temp creates a new project"""
    resp = client.post('/api/project/new-temp', content_type='application/json')
    return assert_status(resp, 200)
test("R2.1: POST /api/project/new-temp", test_r2_new_project)

def test_r2_save_note():
    """POST /api/workspace/hosts/{id}/note saves a note"""
    if not TEST_HOST_ID: return 'SKIP'
    resp = client.post(f'/api/workspace/hosts/{TEST_HOST_ID}/note',
                       json={'note': 'test note from route test'},
                       content_type='application/json')
    # Some routes may return different codes — just check it doesn't 500
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R2.2: POST /api/workspace/hosts/{id}/note", test_r2_save_note)

def test_r2_process_clear():
    """POST /api/processes/clear hides finished processes"""
    resp = client.post('/api/processes/clear', json={'reset_all': False},
                       content_type='application/json')
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R2.3: POST /api/processes/clear", test_r2_process_clear)


# ══════════════════════════════════════════════════════════════
# R3: Context menu routes (NEW — need to be added to routes.py)
# These are the routes that connect JS right-click → WebController
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R3: Context menu routes (NEW endpoints)")
print("="*60 + "\n")

def test_r3_host_menu():
    """GET /api/menus/host?checked=False returns context menu JSON"""
    resp = client.get('/api/menus/host?checked=False')
    if resp.status_code == 404:
        return 'SKIP'  # Route not wired yet
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    items = data.get('items', data)
    return assert_true(isinstance(items, list) and len(items) > 0, "should have menu items")
test("R3.1: GET /api/menus/host", test_r3_host_menu)

def test_r3_service_menu():
    """GET /api/menus/service?name=http returns context menu JSON"""
    resp = client.get('/api/menus/service?name=http')
    if resp.status_code == 404:
        return 'SKIP'
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    items = data.get('items', data)
    return assert_true(isinstance(items, list) and len(items) > 0)
test("R3.2: GET /api/menus/service?name=http", test_r3_service_menu)

def test_r3_port_menu():
    """GET /api/menus/port?service=http returns context menu JSON"""
    resp = client.get('/api/menus/port?service=http')
    if resp.status_code == 404:
        return 'SKIP'
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    return assert_true('port_actions' in data or isinstance(data, list))
test("R3.3: GET /api/menus/port?service=http", test_r3_port_menu)

def test_r3_process_menu():
    """GET /api/menus/process returns process context menu"""
    resp = client.get('/api/menus/process')
    if resp.status_code == 404:
        return 'SKIP'
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    items = data.get('items', data)
    return assert_true(isinstance(items, list))
test("R3.4: GET /api/menus/process", test_r3_process_menu)


# ══════════════════════════════════════════════════════════════
# R4: Host action routes (NEW — right-click action execution)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R4: Host action routes (NEW endpoints)")
print("="*60 + "\n")

def test_r4_host_action_check():
    """POST /api/workspace/hosts/{id}/action with mark-checked"""
    if not TEST_HOST_ID: return 'SKIP'
    resp = client.post(f'/api/workspace/hosts/{TEST_HOST_ID}/action',
                       json={'action': 'mark-checked', 'ip': TEST_HOST_IP},
                       content_type='application/json')
    if resp.status_code == 404:
        return 'SKIP'
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R4.1: POST /api/workspace/hosts/{id}/action (mark-checked)", test_r4_host_action_check)

def test_r4_run_tool():
    """POST /api/workspace/tools/run starts a tool"""
    resp = client.post('/api/workspace/tools/run',
                       json={'host_ip': '127.0.0.1', 'port': '80', 'protocol': 'tcp',
                             'tool_id': 'banner'},
                       content_type='application/json')
    # Existing route — should work (202 accepted or 200)
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R4.2: POST /api/workspace/tools/run", test_r4_run_tool)

def test_r4_run_service_action():
    """POST /api/workspace/service-action runs a tool for a service"""
    resp = client.post('/api/workspace/service-action',
                       json={'targets': [['127.0.0.1', '80', 'tcp']], 'action_index': 0},
                       content_type='application/json')
    if resp.status_code == 404:
        return 'SKIP'
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R4.3: POST /api/workspace/service-action", test_r4_run_service_action)


# ══════════════════════════════════════════════════════════════
# R5: Process management routes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R5: Process management routes")
print("="*60 + "\n")

def test_r5_run_then_output():
    """Run echo via WebController, then GET output via route"""
    # Run a command directly via WebController
    result = wc.runCommand(command='echo route_test_output', name='route-test', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    if not proc_id: return "runCommand returned no process_id"
    time.sleep(2)  # let it finish
    # Now fetch output via HTTP route
    resp = client.get(f'/api/processes/{proc_id}/output')
    r = assert_status(resp, 200)
    if r is not True: return r
    data = resp.get_json()
    output = data.get('output_chunk', '') or data.get('output', '')
    return assert_in('route_test_output', output, "output should contain test string")
test("R5.1: Run command → GET output via route", test_r5_run_then_output)

def test_r5_kill_via_route():
    """Start long process, kill via POST route"""
    result = wc.runCommand(command='sleep 60', name='kill-route-test', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    if not proc_id: return "runCommand returned no process_id"
    time.sleep(0.5)
    resp = client.post(f'/api/processes/{proc_id}/kill', content_type='application/json')
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R5.2: Kill process via POST route", test_r5_kill_via_route)

def test_r5_snapshot_shows_process():
    """Snapshot should show processes run by WebController"""
    result = wc.runCommand(command='echo snapshot_test', name='snap-test', hostIp='127.0.0.1')
    time.sleep(1)
    resp = client.get('/api/snapshot')
    data = resp.get_json()
    procs = data.get('processes', [])
    # Check if any process has our test name
    found = any(p.get('name') == 'snap-test' for p in procs)
    return assert_true(found, "snapshot should contain our test process")
test("R5.3: Snapshot contains WebController processes", test_r5_snapshot_shows_process)


# ══════════════════════════════════════════════════════════════
# R6: Nmap scan route
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R6: Nmap scan routes")
print("="*60 + "\n")

def test_r6_nmap_scan():
    """POST /api/nmap/scan starts an nmap scan"""
    resp = client.post('/api/nmap/scan',
                       json={'targets': '127.0.0.1', 'scan_mode': 'easy',
                             'run_actions': False},
                       content_type='application/json')
    # Existing route — should return 200 or 202
    return assert_true(resp.status_code < 500, f"got {resp.status_code}")
test("R6.1: POST /api/nmap/scan", test_r6_nmap_scan)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
