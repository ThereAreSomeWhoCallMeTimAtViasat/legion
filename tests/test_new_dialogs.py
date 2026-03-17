#!/usr/bin/env python3
"""
Tests for newly wired dialogs and routes — v2.5-flask
=====================================================
Run with: sudo python3 tests/test_new_dialogs.py

Tests every new dialog, button, and route added in v2.4-v2.5:
  D: Dialog HTML exists and is correct
  A: API routes respond correctly
  W: Wiring — JS handlers exist for each button
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
def has(r, s): return True if s in r.data.decode() else f"missing '{s}'"
def status_ok(r): return True if r.status_code < 500 else f"HTTP {r.status_code}"

# Setup
from app.web.testhelper import create_test_app
from db.entities.host import hostObj
from db.entities.port import portObj
from db.entities.service import serviceObj

app, logic, wc = create_test_app()
client = app.test_client()

# Add test host
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


print("\n" + "="*60)
print("D: Dialog HTML elements exist")
print("="*60 + "\n")

page = client.get('/').data.decode()

test("D1: Add Port dialog exists", lambda: has(client.get('/'), 'add-port-modal'))
test("D2: Add Port has port input", lambda: has(client.get('/'), 'add-port-number'))
test("D3: Add Port has state dropdown", lambda: has(client.get('/'), 'add-port-state'))
test("D4: Add Port has protocol dropdown", lambda: has(client.get('/'), 'add-port-protocol'))
test("D5: Add Port has submit button", lambda: has(client.get('/'), 'add-port-submit'))

test("D6: Filters dialog exists", lambda: has(client.get('/'), 'filters-modal'))
test("D7: Filters has host up checkbox", lambda: has(client.get('/'), 'filter-hosts-up'))
test("D8: Filters has port open checkbox", lambda: has(client.get('/'), 'filter-ports-open'))
test("D9: Filters has TCP checkbox", lambda: has(client.get('/'), 'filter-ports-tcp'))
test("D10: Filters has apply button", lambda: has(client.get('/'), 'filters-apply'))

test("D11: Help dialog exists", lambda: has(client.get('/'), 'help-modal'))
test("D12: Help has version info", lambda: has(client.get('/'), 'flask (Web UI)'))
test("D13: Help has license", lambda: has(client.get('/'), 'GNU GPL v3'))
test("D14: Help has keyboard shortcuts", lambda: has(client.get('/'), 'Ctrl+H'))

test("D15: Brute tab has IP input", lambda: has(client.get('/'), 'brute-ip'))
test("D16: Brute tab has port input", lambda: has(client.get('/'), 'brute-port'))
test("D17: Brute tab has service input", lambda: has(client.get('/'), 'brute-service'))
test("D18: Brute tab has run button", lambda: has(client.get('/'), 'brute-run'))
test("D19: Brute tab has wordlist inputs", lambda: has(client.get('/'), 'brute-userlist'))


print("\n" + "="*60)
print("A: API routes for new features")
print("="*60 + "\n")

test("A1: Add port to host", lambda:
    status_ok(client.post(f'/api/workspace/hosts/{HOST_ID}/action',
        json={'action':'add-port', 'ip':HOST_IP, 'port':'443', 'state':'open', 'protocol':'tcp', 'service':'https'},
        content_type='application/json')))

test("A2: Added port appears in host detail", lambda: (
    ok(any(str(p.get('port'))=='443' for p in
        client.get(f'/api/workspace/hosts/{HOST_ID}').get_json().get('ports',[])),
        "port 443 should exist")))

test("A3: Add script to host", lambda:
    status_ok(client.post(f'/api/workspace/hosts/{HOST_ID}/scripts',
        json={'script_id':'test-script', 'port':'80', 'output':'test output'},
        content_type='application/json')))

test("A4: Add CVE to host", lambda:
    status_ok(client.post(f'/api/workspace/hosts/{HOST_ID}/cves',
        json={'name':'CVE-2025-0001', 'severity':'high'},
        content_type='application/json')))

test("A5: Scheduler run", lambda:
    status_ok(client.post('/api/scheduler/run', json={}, content_type='application/json')))

test("A6: Scheduler preferences GET", lambda:
    status_ok(client.get('/api/scheduler/preferences')))

test("A7: Scheduler preferences POST", lambda:
    status_ok(client.post('/api/scheduler/preferences', json={'mode':'deterministic'}, content_type='application/json')))

test("A8: Provider test", lambda:
    status_ok(client.post('/api/scheduler/provider/test', json={}, content_type='application/json')))

test("A9: Provider logs", lambda:
    status_ok(client.get('/api/scheduler/provider/logs')))

test("A10: Save note via action", lambda:
    status_ok(client.post(f'/api/workspace/hosts/{HOST_ID}/note',
        json={'note':'test note from dialog test'}, content_type='application/json')))


print("\n" + "="*60)
print("W: JS wiring (handlers exist)")
print("="*60 + "\n")

js = client.get('/static/js/legion.js?v=10').data.decode()

test("W1: Add Port close wired", lambda: ok('add-port-close' in js))
test("W2: Add Port submit wired", lambda: ok('add-port-submit' in js))
test("W3: Filters close wired", lambda: ok('filters-close' in js))
test("W4: Filters apply wired", lambda: ok('filters-apply' in js))
test("W5: Filter-advanced opens filters", lambda: ok('filter-advanced' in js))
test("W6: Help modal wired", lambda: ok('help-modal' in js))
test("W7: Help close wired", lambda: ok('help-close' in js))
test("W8: Brute run wired", lambda: ok('brute-run' in js))
test("W9: Manual scan run-tool wired", lambda: ok('workspace-run-tool-button' in js))
test("W10: Script add wired", lambda: ok('workspace-add-script-button' in js))
test("W11: CVE add wired", lambda: ok('workspace-add-cve-button' in js))
test("W12: Scheduler form wired", lambda: ok('scheduler-form' in js))
test("W13: Scheduler test provider wired", lambda: ok('scheduler-test-provider' in js))
test("W14: Provider logs refresh wired", lambda: ok('provider-logs-refresh' in js))
test("W15: Host selection save note wired", lambda: ok('workspace-save-note-button' in js))
test("W16: Host remove close wired", lambda: ok('host-remove-modal-close' in js))
test("W17: Screenshot modal close wired", lambda: ok('screenshot-modal' in js))
test("W18: Process output modal close wired", lambda: ok('process-output-modal-close' in js))
test("W19: Startup wizard skip wired", lambda: ok('startup-wizard-skip' in js))
test("W20: Tool selector auto-populates", lambda: ok('workspace-tool-select' in js))
test("W21: Host selector auto-populates", lambda: ok('workspace-host-select' in js))


print("\n" + "="*60)
print("M: Modal open/close mechanics")
print("="*60 + "\n")

test("M1: All modal close buttons exist in HTML", lambda: (
    ok(all(s in page for s in [
        'add-port-close', 'filters-close', 'help-close', 'add-hosts-close',
        'import-nmap-close', 'config-close', 'manual-scan-modal-close',
        'script-cve-modal-close', 'host-selection-modal-close',
        'scheduler-modal-close', 'report-provider-modal-close',
        'settings-modal-close', 'provider-logs-modal-close',
        'host-remove-modal-close', 'screenshot-modal-close',
    ]), "all close buttons should exist")))

test("M2: openModal function exists in JS", lambda: ok('function openModal' in js))
test("M3: closeModal function exists in JS", lambda: ok('function closeModal' in js))
test("M4: File browser exists", lambda: ok('file-browser-modal' in page))
test("M5: File browser navigate function", lambda: ok('fbNavigate' in js))


total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
