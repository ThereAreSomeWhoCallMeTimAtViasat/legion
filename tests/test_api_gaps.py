#!/usr/bin/env python3
"""
Phase 1 API Gap Tests — Project Save / Open / New
===================================================
Run with: sudo python3 tests/test_api_gaps.py

Tests the save → new → open round-trip at the API level using the Flask
test client. No browser required. Verifies hosts, ports, and notes all
survive the full cycle.
"""

import os
import sys
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


# ── Setup ──────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.importers.nmap_import import import_nmap_xml
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

# Seed two hosts with distinct ports
_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.20.30.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="10.20.30.2" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
      <port protocol="tcp" portid="3389"><state state="open"/><service name="ms-wbt-server"/></port>
    </ports>
  </host>
</nmaprun>"""

import tempfile as _tmp
with _tmp.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _seed_path = _f.name
import_nmap_xml(project=logic.activeProject, xml_path=_seed_path, output="")
os.unlink(_seed_path)

# Add a note to host A
_hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
_host_a = next((h for h in _hosts if (h.get('ip') if isinstance(h, dict) else getattr(h, 'ip', '')) == '10.20.30.1'), None)
if _host_a:
    _host_a_id = _host_a.get('id') if isinstance(_host_a, dict) else getattr(_host_a, 'id')
    logic.activeProject.repositoryContainer.noteRepository.storeNotes(_host_a_id, 'round-trip-note')


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P1: Project Save")
print("="*60 + "\n")

SAVE_PATH = '/tmp/legion-api-gap-test.legion'

def test_p1_save_returns_ok():
    """POST /api/project/save-as returns {"status": "ok"}"""
    if os.path.exists(SAVE_PATH):
        os.unlink(SAVE_PATH)
    r = client.post('/api/project/save-as', json={'path': SAVE_PATH})
    data = r.get_json()
    return ok(r.status_code == 200 and data.get('status') == 'ok',
              f"status={r.status_code} body={data}")
test("P1.1: save-as returns 200 and status:ok", test_p1_save_returns_ok)

def test_p2_save_creates_file():
    """.legion file must exist on disk after save"""
    return ok(os.path.exists(SAVE_PATH) and os.path.getsize(SAVE_PATH) > 0,
              f"File missing or empty: {SAVE_PATH}")
test("P1.2: .legion file created on disk", test_p2_save_creates_file)

def test_p3_save_missing_path_errors():
    """save-as with no path must return an error"""
    r = client.post('/api/project/save-as', json={})
    return ok(r.status_code != 200 or 'error' in r.get_data(as_text=True).lower(),
              f"Expected error for missing path, got {r.status_code}")
test("P1.3: save-as with no path returns error", test_p3_save_missing_path_errors)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P2: Project New")
print("="*60 + "\n")

def test_p4_new_returns_ok():
    """POST /api/project/new-temp returns {"status": "ok"}"""
    r = client.post('/api/project/new-temp')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("P2.1: new-temp returns 200", test_p4_new_returns_ok)

def test_p5_new_empties_hosts():
    """After new-temp, snapshot must return 0 hosts"""
    snap = client.get('/api/snapshot').get_json()
    hosts = snap.get('hosts', [])
    return ok(len(hosts) == 0, f"Expected 0 hosts after new-temp, got {len(hosts)}")
test("P2.2: new-temp: snapshot shows 0 hosts", test_p5_new_empties_hosts)

def test_p6_new_empties_processes():
    """After new-temp, snapshot must return 0 processes"""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    return ok(len(procs) == 0, f"Expected 0 processes after new-temp, got {len(procs)}")
test("P2.3: new-temp: snapshot shows 0 processes", test_p6_new_empties_processes)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P3: Project Open (round-trip)")
print("="*60 + "\n")

def test_p7_open_returns_ok():
    """POST /api/project/open returns {"status": "ok"}"""
    if not os.path.exists(SAVE_PATH):
        return "SKIP"
    r = client.post('/api/project/open', json={'path': SAVE_PATH})
    data = r.get_json()
    return ok(r.status_code == 200 and data.get('status') == 'ok',
              f"status={r.status_code} body={data}")
test("P3.1: open returns 200 and status:ok", test_p7_open_returns_ok)

def test_p8_open_restores_both_hosts():
    """After open, snapshot must contain both original host IPs"""
    snap = client.get('/api/snapshot').get_json()
    ips = [h.get('ip') for h in snap.get('hosts', [])]
    missing = [ip for ip in ['10.20.30.1', '10.20.30.2'] if ip not in ips]
    return ok(not missing, f"Missing hosts after open: {missing} (found: {ips})")
test("P3.2: open restores both host IPs", test_p8_open_restores_both_hosts)

def test_p9_open_restores_host_a_ports():
    """After open, host A (10.20.30.1) must have ports 22 and 80"""
    snap = client.get('/api/snapshot').get_json()
    host_a = next((h for h in snap.get('hosts', []) if h.get('ip') == '10.20.30.1'), None)
    if not host_a:
        return "FAIL: host A not found after open"
    r = client.get(f'/api/workspace/hosts/{host_a["id"]}')
    if r.status_code != 200:
        return f"FAIL: /api/workspace/hosts/{host_a['id']} returned {r.status_code}"
    ports = [int(p.get('port', 0)) for p in r.get_json().get('ports', [])]
    missing = [p for p in [22, 80] if p not in ports]
    return ok(not missing, f"Host A missing ports {missing} after open (found: {ports})")
test("P3.3: open restores host A ports (22, 80)", test_p9_open_restores_host_a_ports)

def test_p10_open_restores_host_b_ports():
    """After open, host B (10.20.30.2) must have ports 443 and 3389"""
    snap = client.get('/api/snapshot').get_json()
    host_b = next((h for h in snap.get('hosts', []) if h.get('ip') == '10.20.30.2'), None)
    if not host_b:
        return "FAIL: host B not found after open"
    r = client.get(f'/api/workspace/hosts/{host_b["id"]}')
    if r.status_code != 200:
        return f"FAIL: /api/workspace/hosts/{host_b['id']} returned {r.status_code}"
    ports = [int(p.get('port', 0)) for p in r.get_json().get('ports', [])]
    missing = [p for p in [443, 3389] if p not in ports]
    return ok(not missing, f"Host B missing ports {missing} after open (found: {ports})")
test("P3.4: open restores host B ports (443, 3389)", test_p10_open_restores_host_b_ports)

def test_p11_open_restores_notes():
    """After open, host A must still have its note"""
    snap = client.get('/api/snapshot').get_json()
    host_a = next((h for h in snap.get('hosts', []) if h.get('ip') == '10.20.30.1'), None)
    if not host_a:
        return "FAIL: host A not found after open"
    r = client.get(f'/api/workspace/hosts/{host_a["id"]}')
    if r.status_code != 200:
        return f"FAIL: host detail route returned {r.status_code}"
    note = r.get_json().get('note', '') or ''
    return ok('round-trip-note' in note,
              f"Note missing after open. Got: {note!r}")
test("P3.5: open restores notes for host A", test_p11_open_restores_notes)

def test_p12_open_nonexistent_file_errors():
    """open with a path that doesn't exist must return an error"""
    r = client.post('/api/project/open', json={'path': '/tmp/does-not-exist.legion'})
    return ok(r.status_code in (400, 404, 500),
              f"Expected error status, got {r.status_code}: {r.get_data(as_text=True)[:100]}")
test("P3.6: open with nonexistent path returns error", test_p12_open_nonexistent_file_errors)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P4: Second round-trip (verify repeatable)")
print("="*60 + "\n")

def test_p13_second_save_open_cycle():
    """A second save → new → open cycle must work correctly"""
    snap_before = client.get('/api/snapshot').get_json()
    ips_before = sorted(h.get('ip') for h in snap_before.get('hosts', []))
    if not ips_before:
        return "SKIP"

    path2 = '/tmp/legion-api-gap-test2.legion'
    try:
        client.post('/api/project/save-as', json={'path': path2})
        client.post('/api/project/new-temp')
        snap_empty = client.get('/api/snapshot').get_json()
        assert len(snap_empty.get('hosts', [])) == 0, "new-temp did not empty hosts"
        client.post('/api/project/open', json={'path': path2})
        snap_after = client.get('/api/snapshot').get_json()
        ips_after = sorted(h.get('ip') for h in snap_after.get('hosts', []))
        return ok(ips_before == ips_after,
                  f"IPs differ after second cycle: before={ips_before} after={ips_after}")
    finally:
        if os.path.exists(path2):
            os.unlink(path2)
test("P4.1: second save → new → open cycle works", test_p13_second_save_open_cycle)


# ── Cleanup ────────────────────────────────────────────────────────────────
if os.path.exists(SAVE_PATH):
    os.unlink(SAVE_PATH)

# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
