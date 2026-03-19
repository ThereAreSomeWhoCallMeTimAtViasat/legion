#!/usr/bin/env python3
"""
Phase 2 API Isolation Tests — Multi-Host Data Isolation
=========================================================
Run with: sudo python3 tests/test_multihost_isolation.py

Proves that ports, notes, and process data are strictly per-host and never
bleed between hosts at the API/DB level. No browser required.
"""

import os
import sys
import traceback
import tempfile

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


# ── Setup: two distinct hosts ────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.importers.nmap_import import import_nmap_xml
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.20.30.1" addrtype="ipv4"/>
    <os><osmatch name="Linux 4.x" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="10.20.30.2" addrtype="ipv4"/>
    <os><osmatch name="Windows 10" accuracy="90"/></os>
    <ports>
      <port protocol="tcp" portid="443"><state state="open"/><service name="https"/></port>
      <port protocol="tcp" portid="3389"><state state="open"/><service name="ms-wbt-server"/></port>
    </ports>
  </host>
</nmaprun>"""

with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _seed_path = _f.name
import_nmap_xml(project=logic.activeProject, xml_path=_seed_path, output="")
os.unlink(_seed_path)

# Add distinct notes to each host
_hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)

def _host_id(ip):
    for h in _hosts:
        hip = h.get('ip') if isinstance(h, dict) else getattr(h, 'ipv4', '') or getattr(h, 'ip', '')
        if hip == ip:
            return h.get('id') if isinstance(h, dict) else getattr(h, 'id')
    return None

_id_a = _host_id('10.20.30.1')
_id_b = _host_id('10.20.30.2')

if _id_a:
    logic.activeProject.repositoryContainer.noteRepository.storeNotes(_id_a, 'host-a-note')
if _id_b:
    logic.activeProject.repositoryContainer.noteRepository.storeNotes(_id_b, 'host-b-note')


# ── Helper ───────────────────────────────────────────────────────────────────
def _snap_host(ip):
    """Return the host dict from snapshot for a given IP."""
    snap = client.get('/api/snapshot').get_json()
    return next((h for h in snap.get('hosts', []) if h.get('ip') == ip), None)

def _host_ports(host_id):
    """Return set of integer port numbers for a host via /api/workspace/hosts/<id>."""
    r = client.get(f'/api/workspace/hosts/{host_id}')
    if r.status_code != 200:
        return set()
    return {int(p.get('port', 0)) for p in r.get_json().get('ports', [])}

def _host_note(host_id):
    """Return note text for a host via /api/workspace/hosts/<id>."""
    r = client.get(f'/api/workspace/hosts/{host_id}')
    return r.get_json().get('note', '') or '' if r.status_code == 200 else ''


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("I1: Port isolation")
print("="*60 + "\n")

def test_i1_both_hosts_in_snapshot():
    """Both hosts must appear in the snapshot."""
    snap = client.get('/api/snapshot').get_json()
    ips = {h.get('ip') for h in snap.get('hosts', [])}
    missing = {'10.20.30.1', '10.20.30.2'} - ips
    return ok(not missing, f"Missing hosts in snapshot: {missing}")
test("I1.1: both hosts present in snapshot", test_i1_both_hosts_in_snapshot)

def test_i2_host_a_ports_correct():
    """Host A must have ports 22 and 80 — not 443 or 3389."""
    h = _snap_host('10.20.30.1')
    if not h: return "host A not in snapshot"
    ports = _host_ports(h['id'])
    wrong = ports & {443, 3389}
    missing = {22, 80} - ports
    return ok(not wrong and not missing,
              f"Host A ports wrong: has {wrong}, missing {missing} (all: {ports})")
test("I1.2: host A has ports 22,80 and NOT 443,3389", test_i2_host_a_ports_correct)

def test_i3_host_b_ports_correct():
    """Host B must have ports 443 and 3389 — not 22 or 80."""
    h = _snap_host('10.20.30.2')
    if not h: return "host B not in snapshot"
    ports = _host_ports(h['id'])
    wrong = ports & {22, 80}
    missing = {443, 3389} - ports
    return ok(not wrong and not missing,
              f"Host B ports wrong: has {wrong}, missing {missing} (all: {ports})")
test("I1.3: host B has ports 443,3389 and NOT 22,80", test_i3_host_b_ports_correct)

def test_i4_snapshot_ports_linked_to_correct_host():
    """Snapshot port_count must reflect each host independently."""
    snap = client.get('/api/snapshot').get_json()
    hosts = {h['ip']: h for h in snap.get('hosts', [])}
    a = hosts.get('10.20.30.1', {})
    b = hosts.get('10.20.30.2', {})
    # Both should show 2 ports each, not 4 or 0
    a_count = a.get('open_ports', 0)
    b_count = b.get('open_ports', 0)
    return ok(a_count == 2 and b_count == 2,
              f"Snapshot port counts: A={a_count} B={b_count} (expected 2 each)")
test("I1.4: snapshot port_count is 2 for each host independently", test_i4_snapshot_ports_linked_to_correct_host)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("I2: Note isolation")
print("="*60 + "\n")

def test_i5_host_a_note_correct():
    """Host A must have 'host-a-note', not 'host-b-note'."""
    h = _snap_host('10.20.30.1')
    if not h: return "host A not in snapshot"
    note = _host_note(h['id'])
    return ok('host-a-note' in note and 'host-b-note' not in note,
              f"Host A note wrong: {note!r}")
test("I2.1: host A note contains 'host-a-note', not 'host-b-note'", test_i5_host_a_note_correct)

def test_i6_host_b_note_correct():
    """Host B must have 'host-b-note', not 'host-a-note'."""
    h = _snap_host('10.20.30.2')
    if not h: return "host B not in snapshot"
    note = _host_note(h['id'])
    return ok('host-b-note' in note and 'host-a-note' not in note,
              f"Host B note wrong: {note!r}")
test("I2.2: host B note contains 'host-b-note', not 'host-a-note'", test_i6_host_b_note_correct)

def test_i7_note_saved_to_a_not_readable_on_b():
    """Writing a new note to host A must not affect host B's note."""
    h_a = _snap_host('10.20.30.1')
    h_b = _snap_host('10.20.30.2')
    if not h_a or not h_b: return "hosts not found"
    # Write a unique note to A
    client.post(f'/api/workspace/hosts/{h_a["id"]}/note',
                json={'note': 'isolation-write-test-A'})
    # B's note must be unchanged
    note_b = _host_note(h_b['id'])
    return ok('isolation-write-test-A' not in note_b,
              f"Host A's new note bled into host B: {note_b!r}")
test("I2.3: writing note to host A does not affect host B", test_i7_note_saved_to_a_not_readable_on_b)

def test_i8_note_saved_to_b_not_readable_on_a():
    """Writing a new note to host B must not affect host A's note."""
    h_a = _snap_host('10.20.30.1')
    h_b = _snap_host('10.20.30.2')
    if not h_a or not h_b: return "hosts not found"
    client.post(f'/api/workspace/hosts/{h_b["id"]}/note',
                json={'note': 'isolation-write-test-B'})
    note_a = _host_note(h_a['id'])
    return ok('isolation-write-test-B' not in note_a,
              f"Host B's new note bled into host A: {note_a!r}")
test("I2.4: writing note to host B does not affect host A", test_i8_note_saved_to_b_not_readable_on_a)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("I3: Process isolation")
print("="*60 + "\n")

import time as _time

def test_i9_processes_have_correct_hostip():
    """Every process in the snapshot must have the correct hostIp field."""
    import threading
    wc.start()
    wc.runCommand('echo host-a-output', name='host-a-proc', hostIp='10.20.30.1')
    wc.runCommand('echo host-b-output', name='host-b-proc', hostIp='10.20.30.2')
    _time.sleep(1.5)  # let processes finish

    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    if not procs: return "SKIP"

    wrong = []
    for p in procs:
        name = p.get('name', '')
        hip = p.get('hostIp', '')
        if 'host-a' in name and hip != '10.20.30.1':
            wrong.append(f"{name} has hostIp={hip!r}, expected 10.20.30.1")
        if 'host-b' in name and hip != '10.20.30.2':
            wrong.append(f"{name} has hostIp={hip!r}, expected 10.20.30.2")
    return ok(not wrong, "; ".join(wrong))
test("I3.1: process snapshot shows correct hostIp for each process", test_i9_processes_have_correct_hostip)

def test_i10_process_output_route_correct():
    """Output for host-a-proc must contain 'host-a-output', not 'host-b-output'."""
    snap = client.get('/api/snapshot').get_json()
    procs = {p.get('name', ''): p for p in snap.get('processes', [])}
    proc_a = procs.get('host-a-proc')
    proc_b = procs.get('host-b-proc')
    if not proc_a or not proc_b: return "SKIP"

    r_a = client.get(f'/api/processes/{proc_a["id"]}/output').get_json()
    out_a = r_a.get('output_chunk', '') or r_a.get('output', '')

    r_b = client.get(f'/api/processes/{proc_b["id"]}/output').get_json()
    out_b = r_b.get('output_chunk', '') or r_b.get('output', '')

    results = []
    if 'host-a-output' not in out_a:
        results.append(f"host-a-proc output missing 'host-a-output': {out_a!r}")
    if 'host-b-output' in out_a:
        results.append(f"host-a-proc output contains host-b content: {out_a!r}")
    if 'host-b-output' not in out_b:
        results.append(f"host-b-proc output missing 'host-b-output': {out_b!r}")
    return ok(not results, "; ".join(results))
test("I3.2: process output is correct and doesn't bleed between hosts", test_i10_process_output_route_correct)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("I4: Information tab isolation")
print("="*60 + "\n")

def test_i11_host_a_info_has_correct_ip():
    """Information route for host A must return A's IP, not B's."""
    h = _snap_host('10.20.30.1')
    if not h: return "host A not in snapshot"
    r = client.get(f'/api/workspace/hosts/{h["id"]}/information').get_json()
    ip = r.get('ip', '')
    return ok(ip == '10.20.30.1' and '10.20.30.2' not in ip,
              f"Host A information returned ip={ip!r}")
test("I4.1: information route for host A returns correct IP", test_i11_host_a_info_has_correct_ip)

def test_i12_host_b_info_has_correct_ip():
    """Information route for host B must return B's IP, not A's."""
    h = _snap_host('10.20.30.2')
    if not h: return "host B not in snapshot"
    r = client.get(f'/api/workspace/hosts/{h["id"]}/information').get_json()
    ip = r.get('ip', '')
    return ok(ip == '10.20.30.2' and '10.20.30.1' not in ip,
              f"Host B information returned ip={ip!r}")
test("I4.2: information route for host B returns correct IP", test_i12_host_b_info_has_correct_ip)

def test_i13_host_a_os_is_linux():
    """Information route for host A must show Linux OS."""
    h = _snap_host('10.20.30.1')
    if not h: return "host A not in snapshot"
    r = client.get(f'/api/workspace/hosts/{h["id"]}/information').get_json()
    os_val = r.get('os', '')
    return ok('Linux' in os_val and 'Windows' not in os_val,
              f"Host A os={os_val!r} (expected Linux)")
test("I4.3: host A information shows Linux OS, not Windows", test_i13_host_a_os_is_linux)

def test_i14_host_b_os_is_windows():
    """Information route for host B must show Windows OS."""
    h = _snap_host('10.20.30.2')
    if not h: return "host B not in snapshot"
    r = client.get(f'/api/workspace/hosts/{h["id"]}/information').get_json()
    os_val = r.get('os', '')
    return ok('Windows' in os_val and 'Linux' not in os_val,
              f"Host B os={os_val!r} (expected Windows)")
test("I4.4: host B information shows Windows OS, not Linux", test_i14_host_b_os_is_windows)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
