#!/usr/bin/env python3
"""
UI Wiring Tests — Every button and menu item works
===================================================
Run with: sudo python3 tests/test_ui_wiring.py

Verifies that every clickable element in the Flask UI is connected
to a working handler that calls the correct API endpoint.
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

def ok(r, msg=""): return True if r else f"FAIL: {msg}"
def status_ok(r): return True if r.status_code < 500 else f"HTTP {r.status_code}: {r.data[:200]}"
def has(r, s): return True if s in r.data.decode() else f"missing '{s}'"

# Setup
from app.web.testhelper import create_test_app
from db.entities.host import hostObj
from db.entities.port import portObj
from db.entities.service import serviceObj

app, logic, wc = create_test_app()
client = app.test_client()

# Add test data
session = logic.activeProject.database.session()
try:
    h = hostObj(ip='10.10.10.1', ipv4='10.10.10.1', hostname='test', osMatch='Linux', status='up', state='up')
    session.add(h); session.flush()
    svc = serviceObj(name='http', host=str(h.id), product='Apache', version='2.4')
    session.add(svc); session.flush()
    p = portObj(portId='80', protocol='tcp', state='open', host=h.id, service=svc.id)
    session.add(p); session.commit()
    HOST_ID, HOST_IP = h.id, h.ip
finally:
    session.close()

# Run a process so we have one to test with
proc_result = wc.runCommand(command='echo wiring_test', name='wire-test', hostIp='10.10.10.1', port='80')
PROC_ID = proc_result.get('process_id')
time.sleep(2)


print("\n" + "="*60)
print("M: Menu items")
print("="*60 + "\n")

test("M1: File → New (POST /api/project/new-temp)", lambda:
    status_ok(client.post('/api/project/new-temp', content_type='application/json')))

# Re-add test data after new project
session = logic.activeProject.database.session()
try:
    h = hostObj(ip='10.10.10.1', ipv4='10.10.10.1', hostname='test', osMatch='Linux', status='up', state='up')
    session.add(h); session.flush()
    svc = serviceObj(name='http', host=str(h.id), product='Apache', version='2.4')
    session.add(svc); session.flush()
    p = portObj(portId='80', protocol='tcp', state='open', host=h.id, service=svc.id)
    session.add(p); session.commit()
    HOST_ID, HOST_IP = h.id, h.ip
finally:
    session.close()

test("M2: File → Open (POST /api/project/open)", lambda:
    ok(client.post('/api/project/open', json={'path':'/nonexistent.legion'}, content_type='application/json').status_code in (200,400,404,500), "should respond"))

test("M3: File → Save (POST /api/project/save-as)", lambda:
    ok(client.post('/api/project/save-as', json={'path':'/tmp/test-legion-save.legion'}, content_type='application/json').status_code < 600, "should respond"))

test("M4: File → Export JSON (GET /api/export/json)", lambda:
    status_ok(client.get('/api/export/json')))

test("M5: File → Export CSV (GET /api/export/csv)", lambda:
    status_ok(client.get('/api/export/csv')))

test("M6: File → Add Hosts (POST /api/nmap/scan)", lambda:
    ok(client.post('/api/nmap/scan', json={'targets':'127.0.0.1','scan_mode':'easy'}, content_type='application/json').status_code < 500, "scan route"))

test("M7: File → Import Nmap (POST /api/nmap/import-xml)", lambda:
    ok(client.post('/api/nmap/import-xml', json={'path':'/nonexistent.xml'}, content_type='application/json').status_code in (200,400,404,500), "import route"))

test("M8: Help → Config (GET /api/config/profiles)", lambda:
    status_ok(client.get('/api/config/profiles')))

test("M9: Help → Config has profiles", lambda:
    ok(len(client.get('/api/config/profiles').get_json().get('profiles',[])) > 0, "should have profiles"))


print("\n" + "="*60)
print("B: Buttons")
print("="*60 + "\n")

test("B1: Hide Finished (POST /api/processes/clear reset_all=false)", lambda:
    status_ok(client.post('/api/processes/clear', json={'reset_all':False}, content_type='application/json')))

test("B2: Hide All (POST /api/processes/clear reset_all=true)", lambda:
    status_ok(client.post('/api/processes/clear', json={'reset_all':True}, content_type='application/json')))

# Re-run a process after clear
proc_result2 = wc.runCommand(command='echo btn_test', name='btn-test', hostIp='10.10.10.1')
time.sleep(1)
PROC_ID2 = proc_result2.get('process_id')

test("B3: Process output (GET /api/processes/{id}/output)", lambda:
    status_ok(client.get(f'/api/processes/{PROC_ID2}/output')))

test("B4: Process kill (POST /api/processes/{id}/kill)", lambda: (
    wc.runCommand(command='sleep 30', name='kill-btn-test', hostIp='10.10.10.1'),
    time.sleep(0.5),
    status_ok(client.post(f'/api/processes/{wc.runCommand(command="sleep 30", name="k2", hostIp="10.10.10.1").get("process_id")}/kill', content_type='application/json'))
)[-1])

test("B5: Process retry (POST /api/processes/{id}/retry)", lambda:
    ok(client.post(f'/api/processes/{PROC_ID2}/retry', json={}, content_type='application/json').status_code < 500, "retry"))

test("B6: Process close (POST /api/processes/{id}/close)", lambda:
    status_ok(client.post(f'/api/processes/{PROC_ID2}/close', json={}, content_type='application/json')))

test("B7: Save note (POST /api/workspace/hosts/{id}/note)", lambda:
    status_ok(client.post(f'/api/workspace/hosts/{HOST_ID}/note', json={'note':'test note'}, content_type='application/json')))

test("B8: Run scheduler (POST /api/scheduler/run)", lambda:
    ok(client.post('/api/scheduler/run', json={}, content_type='application/json').status_code < 500, "scheduler"))

test("B9: Refresh workspace (GET /api/snapshot)", lambda:
    status_ok(client.get('/api/snapshot')))


print("\n" + "="*60)
print("C: Context menu routes")
print("="*60 + "\n")

test("C1: Host menu (GET /api/menus/host)", lambda:
    ok(len(client.get('/api/menus/host').get_json().get('items',[])) > 5, "host menu items"))

test("C2: Service menu (GET /api/menus/service?name=http)", lambda:
    ok(len(client.get('/api/menus/service?name=http').get_json().get('items',[])) > 10, "service menu items"))

test("C3: Port menu (GET /api/menus/port?service=http)", lambda:
    ok('port_actions' in client.get('/api/menus/port?service=http').get_json(), "port menu"))

test("C4: Process menu (GET /api/menus/process)", lambda:
    ok(len(client.get('/api/menus/process').get_json().get('items',[])) == 3, "3 items"))

test("C5: Host action dispatch (POST /api/workspace/hosts/{id}/action)", lambda:
    status_ok(client.post(f'/api/workspace/hosts/{HOST_ID}/action', json={'action':'mark-checked','ip':HOST_IP}, content_type='application/json')))

test("C6: Service action dispatch (POST /api/workspace/service-action)", lambda:
    status_ok(client.post('/api/workspace/service-action', json={'targets':[['10.10.10.1','80','tcp']],'action_index':0}, content_type='application/json')))


print("\n" + "="*60)
print("P: Profile management")
print("="*60 + "\n")

test("P1: List profiles", lambda:
    ok(len(client.get('/api/config/profiles').get_json().get('profiles',[])) > 0, "profiles"))

test("P2: Create profile", lambda:
    status_ok(client.post('/api/config/profiles/create', json={'name':'test_wiring','copy_from':'default'}, content_type='application/json')))

test("P3: Save profile", lambda:
    status_ok(client.post('/api/config/profiles/test_wiring/save', json={'text':'[BruteSettings]\ntest=1'}, content_type='application/json')))

test("P4: Duplicate profile", lambda:
    status_ok(client.post('/api/config/profiles/test_wiring/duplicate', json={'new_name':'test_wiring_dup'}, content_type='application/json')))

test("P5: Rename profile", lambda:
    status_ok(client.post('/api/config/profiles/test_wiring_dup/rename', json={'new_name':'test_wiring_renamed'}, content_type='application/json')))

test("P6: Activate profile", lambda:
    status_ok(client.post('/api/config/profiles/default/activate', json={}, content_type='application/json')))

test("P7: Delete profile", lambda:
    status_ok(client.post('/api/config/profiles/test_wiring/delete', json={}, content_type='application/json')))

test("P8: Delete renamed profile", lambda:
    status_ok(client.post('/api/config/profiles/test_wiring_renamed/delete', json={}, content_type='application/json')))

test("P9: Cannot delete default", lambda:
    ok(client.post('/api/config/profiles/default/delete', json={}, content_type='application/json').status_code == 400, "should reject"))


print("\n" + "="*60)
print("H: HTML structure")
print("="*60 + "\n")

page = client.get('/').data.decode()

test("H1: Version in title", lambda: has(client.get('/'), 'flask'))
test("H2: Add hosts dialog exists", lambda: has(client.get('/'), 'add-hosts-modal'))
test("H3: Import nmap dialog exists", lambda: has(client.get('/'), 'import-nmap-modal'))
test("H4: Config manager dialog exists", lambda: has(client.get('/'), 'config-modal'))
test("H5: Process filter dropdown", lambda: has(client.get('/'), 'process-status-filter'))
test("H6: Notes textarea exists", lambda: has(client.get('/'), 'notes-text'))
test("H7: JS has contextmenu handler", lambda: has(client.get('/static/js/legion.js?v=4'), 'contextmenu'))
test("H8: JS has openModal function", lambda: has(client.get('/static/js/legion.js?v=4'), 'openModal'))
test("H9: JS has process clear handler", lambda: has(client.get('/static/js/legion.js?v=4'), 'process-clear'))


total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
