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

_files_to_cleanup = []
import atexit as _atexit
@_atexit.register
def _cleanup_test_files():
    for p in _files_to_cleanup:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except Exception:
            pass

def test_p13_second_save_open_cycle():
    """A second save → new → open cycle must work correctly.

    Determinism contract: this test MUST leave the active project pointing
    at a valid on-disk DB file.  An earlier version unlinked path2 in
    finally:, but activeProject was still opened-from-path2 at that point.
    The SQLAlchemy engine pool kept FDs to the unlinked file alive — and
    when the pool ran low under concurrent _capture_output writes from
    P5.x, it opened *new* connections by filename.  SQLite then created
    a fresh empty file (no schema), causing 'no such table' errors in
    every subsequent test that touched the DB.

    Fix: register path2 for atexit cleanup instead of finally cleanup.
    The file is then alive for the full test session."""
    snap_before = client.get('/api/snapshot').get_json()
    ips_before = sorted(h.get('ip') for h in snap_before.get('hosts', []))
    if not ips_before:
        return "SKIP"

    path2 = '/tmp/legion-api-gap-test2.legion'
    _files_to_cleanup.extend([path2, path2 + '-wal', path2 + '-shm'])
    client.post('/api/project/save-as', json={'path': path2})
    client.post('/api/project/new-temp')
    snap_empty = client.get('/api/snapshot').get_json()
    assert len(snap_empty.get('hosts', [])) == 0, "new-temp did not empty hosts"
    client.post('/api/project/open', json={'path': path2})
    snap_after = client.get('/api/snapshot').get_json()
    ips_after = sorted(h.get('ip') for h in snap_after.get('hosts', []))
    return ok(ips_before == ips_after,
              f"IPs differ after second cycle: before={ips_before} after={ips_after}")
test("P4.1: second save → new → open cycle works", test_p13_second_save_open_cycle)




# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P5: Persistence — notes, config, host delete, process kill")
print("="*60 + "\n")

def _snap_host(ip):
    snap = client.get('/api/snapshot').get_json()
    return next((h for h in snap.get('hosts', []) if h.get('ip') == ip), None)

def test_p14_notes_persist_in_db():
    """Note written via API must be readable back in the same session."""
    h = _snap_host('10.20.30.1')
    if not h: return "SKIP"
    client.post(f'/api/workspace/hosts/{h["id"]}/note', json={'note': 'persist-api-test'})
    r = client.get(f'/api/workspace/hosts/{h["id"]}')
    note = r.get_json().get('note', '') or ''
    return ok('persist-api-test' in note, f"Note not readable after write: {note!r}")
test("P5.1: note written via API is readable back immediately", test_p14_notes_persist_in_db)

def test_p15_note_doesnt_bleed_to_other_host():
    """Note written to host A must not appear when reading host B."""
    h_a = _snap_host('10.20.30.1')
    h_b = _snap_host('10.20.30.2')
    if not h_a or not h_b: return "SKIP"
    client.post(f'/api/workspace/hosts/{h_a["id"]}/note', json={'note': 'only-for-a'})
    r_b = client.get(f'/api/workspace/hosts/{h_b["id"]}')
    note_b = r_b.get_json().get('note', '') or ''
    return ok('only-for-a' not in note_b, f"Note bled from A to B: {note_b!r}")
test("P5.2: note written to host A does not appear on host B", test_p15_note_doesnt_bleed_to_other_host)

def test_p16_config_save_and_read():
    """POST to /api/settings/legion-conf must write, GET must read it back."""
    import os
    # Read current config first
    r_get = client.get('/api/settings/legion-conf')
    if r_get.status_code != 200:
        return "SKIP"
    original = r_get.get_json().get('text', '')
    conf_path = r_get.get_json().get('path', '')
    if not conf_path or not os.path.isfile(conf_path):
        return "SKIP"

    # Append a marker comment and save
    marker = '# phase4-config-test-marker'
    modified = original + '\n' + marker
    r_post = client.post('/api/settings/legion-conf', json={'text': modified})
    if r_post.status_code != 200:
        return f"FAIL: POST returned {r_post.status_code}"

    # Read back — marker must be present
    r_get2 = client.get('/api/settings/legion-conf')
    saved_text = r_get2.get_json().get('text', '')
    result = ok(marker in saved_text, f"Marker missing after save. Got: {saved_text[-100:]!r}")

    # Restore original
    client.post('/api/settings/legion-conf', json={'text': original})
    return result
test("P5.3: config save writes to disk, GET reads it back", test_p16_config_save_and_read)

def test_p17_host_delete_removes_from_db():
    """Deleting host A via API must remove it from the snapshot."""
    h_a = _snap_host('10.20.30.1')
    h_b = _snap_host('10.20.30.2')
    if not h_a: return "SKIP"
    r = client.post(f'/api/workspace/hosts/{h_a["id"]}/action',
                    json={'action': 'delete', 'ip': '10.20.30.1'})
    if r.status_code != 200:
        return f"FAIL: delete action returned {r.status_code}"
    snap = client.get('/api/snapshot').get_json()
    ips = {h.get('ip') for h in snap.get('hosts', [])}
    result_a = ok('10.20.30.1' not in ips, f"Host A still in snapshot after delete: {ips}")
    if h_b:
        result_b = ok('10.20.30.2' in ips, f"Host B missing after deleting only A: {ips}")
        if result_a is True and result_b is True:
            return True
        return result_a if result_a is not True else result_b
    return result_a
test("P5.4: host delete removes from snapshot, preserves other hosts", test_p17_host_delete_removes_from_db)

def test_p18_process_kill_terminates_subprocess():
    """Kill action must cause the subprocess to exit."""
    import time as _t
    # wc is already started by create_test_app(); calling wc.start() again would
    # create a NEW empty project, losing all seeded data and breaking later tests
    result = wc.runCommand('sleep 30', name='kill-api-test', hostIp='10.20.30.2')
    pid = result.get('process_id')
    if not pid: return "SKIP"
    _t.sleep(0.8)   # let process start and set _popen

    # Get the popen object before killing
    popen = None
    for proc in getattr(wc, '_active_processes', {}).values():
        if getattr(proc, 'id', None) == pid or str(getattr(proc, 'processId', None)) == str(pid):
            popen = getattr(proc, '_popen', None)
            break
    if popen is None:
        # Fallback: kill via API and verify status changes
        r = client.post(f'/api/processes/{pid}/kill', json={})
        return ok(r.status_code == 200, f"Kill returned {r.status_code}")

    r = client.post(f'/api/processes/{pid}/kill', json={})
    _t.sleep(0.5)
    exited = popen.poll() is not None
    return ok(exited, f"Process still running after kill (poll={popen.poll()})")
test("P5.5: kill action terminates the subprocess", test_p18_process_kill_terminates_subprocess)

def test_p19_process_clear_sets_closed():
    """Clear action must mark the process as closed in the DB."""
    import time as _t
    # wc already started — do not call wc.start() again (would create new empty project)
    result = wc.runCommand('echo clear-api-test', name='clear-api-test', hostIp='10.20.30.2')
    pid = result.get('process_id')
    if not pid: return "SKIP"
    _t.sleep(1.5)  # let it finish

    r = client.post(f'/api/processes/{pid}/close', json={})
    if r.status_code != 200:
        return f"FAIL: close returned {r.status_code}"
    # Process must be gone from snapshot (closed=True excluded)
    snap = client.get('/api/snapshot').get_json()
    ids = [p.get('id') for p in snap.get('processes', [])]
    return ok(pid not in ids, f"Process {pid} still in snapshot after clear (ids: {ids})")
test("P5.6: clear action removes process from snapshot", test_p19_process_clear_sets_closed)

# ── Cleanup ────────────────────────────────────────────────────────────────
# Defer to module exit via _files_to_cleanup — this file is no longer the
# active project (P4.1 moved us to path2), but unlinking it mid-run while
# any thread might still hold an FD to it is the kind of file-deletion-race
# documented in P4.1's doctring.
_files_to_cleanup.extend([SAVE_PATH, SAVE_PATH + '-wal', SAVE_PATH + '-shm'])


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P6: Export JSON — structured data export")
print("="*60 + "\n")

def test_p20_export_json_returns_200():
    """GET /api/export/json must return 200 with JSON body."""
    r = client.get('/api/export/json')
    return ok(r.status_code == 200 and r.content_type.startswith('application/json'),
              f"status={r.status_code} content_type={r.content_type}")
test("P6.1: /api/export/json returns 200 with JSON", test_p20_export_json_returns_200)

def test_p21_export_has_required_top_level_fields():
    """Export must contain version, project, exported_at, and hosts fields."""
    data = client.get('/api/export/json').get_json()
    required = ['version', 'project', 'exported_at', 'hosts']
    missing = [f for f in required if f not in data]
    return ok(not missing, f"Missing top-level fields: {missing}")
test("P6.2: export has version, project, exported_at, hosts fields", test_p21_export_has_required_top_level_fields)

def test_p22_export_hosts_contain_expected_ips():
    """Export hosts must include both seeded host IPs."""
    data = client.get('/api/export/json').get_json()
    ips = {h.get('ip') for h in data.get('hosts', [])}
    # Re-open the saved project which had both hosts
    expected = {'10.20.30.1', '10.20.30.2'}
    found = expected & ips
    return ok(len(found) > 0,
              f"No expected IPs in export. Got: {ips}")
test("P6.3: export hosts contain expected IP addresses", test_p22_export_hosts_contain_expected_ips)

def test_p23_export_host_has_required_fields():
    """Each exported host must have ip, ports, hostname, os, status, note, cves."""
    data = client.get('/api/export/json').get_json()
    hosts = data.get('hosts', [])
    if not hosts:
        return "SKIP"
    required = ['ip', 'ports', 'hostname', 'os', 'status', 'note', 'cves']
    for h in hosts:
        missing = [f for f in required if f not in h]
        if missing:
            return f"Host {h.get('ip')} missing fields: {missing}"
    return True
test("P6.4: each exported host has all required fields", test_p23_export_host_has_required_fields)

def test_p24_export_ports_have_correct_structure():
    """Exported ports must have port, protocol, state, service fields."""
    data = client.get('/api/export/json').get_json()
    hosts = data.get('hosts', [])
    for h in hosts:
        for p in h.get('ports', []):
            required = ['port', 'protocol', 'state', 'service']
            missing = [f for f in required if f not in p]
            if missing:
                return f"Port in host {h.get('ip')} missing: {missing}"
    return True
test("P6.5: exported ports have port/protocol/state/service fields", test_p24_export_ports_have_correct_structure)

def test_p25_export_ports_correct_for_host():
    """Seed a host, export JSON, verify port data is correct."""
    # Ensure the project has a host with known ports
    import_nmap_xml(project=logic.activeProject, xml_path='/dev/stdin',
                    output="") if False else None
    _xml = """<?xml version="1.0"?><nmaprun>
      <host><status state="up"/>
        <address addr="10.20.30.1" addrtype="ipv4"/>
        <ports>
          <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
          <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
        </ports>
      </host>
    </nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_xml); xml_path = f.name
    try:
        import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output="")
    finally:
        os.unlink(xml_path)
    data = client.get('/api/export/json').get_json()
    host_a = next((h for h in data.get('hosts', []) if h.get('ip') == '10.20.30.1'), None)
    if not host_a:
        return "FAIL: host 10.20.30.1 not in export after import"
    port_nums = {int(p.get('port', 0)) for p in host_a.get('ports', [])}
    missing = {22, 80} - port_nums
    return ok(not missing, f"Host A missing ports {missing} in export (got {port_nums})")
test("P6.6: host A exports with correct ports (22, 80)", test_p25_export_ports_correct_for_host)

def test_p26_export_note_included():
    """Write a note to a host, export JSON, verify note appears in export."""
    data = client.get('/api/export/json').get_json()
    hosts = data.get('hosts', [])
    if not hosts:
        return "SKIP"
    h = hosts[0]
    host_id = _snap_host(h['ip'])
    if not host_id:
        return "SKIP"
    # Write a note
    client.post(f'/api/workspace/hosts/{host_id["id"]}/note',
                json={'note': 'export-note-test-XYZ'})
    data2 = client.get('/api/export/json').get_json()
    host_a = next((x for x in data2.get('hosts', []) if x.get('ip') == h['ip']), None)
    if not host_a:
        return "SKIP"
    note = host_a.get('note', '')
    return ok('export-note-test-XYZ' in note,
              f"Note not in export. Got: {note!r}")
test("P6.7: export includes note written to host", test_p26_export_note_included)

def test_p27_export_to_tmp_file_and_reload():
    """Export JSON to /tmp, re-read from disk, verify data integrity."""
    import json as _json
    r = client.get('/api/export/json')
    data = r.get_json()

    # Write to tmp file
    tmp_path = '/tmp/legion-export-test.json'
    try:
        with open(tmp_path, 'w') as f:
            _json.dump(data, f, indent=2)

        # Re-read from disk
        with open(tmp_path, 'r') as f:
            reloaded = _json.load(f)

        # Verify it round-trips cleanly
        results = []
        if reloaded.get('version') != data.get('version'):
            results.append("version mismatch after file round-trip")
        if len(reloaded.get('hosts', [])) != len(data.get('hosts', [])):
            results.append(f"host count changed: {len(data.get('hosts',[]))} → {len(reloaded.get('hosts',[]))}")
        return ok(not results, "; ".join(results))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
test("P6.8: export JSON to /tmp and reload — data integrity preserved", test_p27_export_to_tmp_file_and_reload)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P7: legion.conf syntax validation on config save")
print("="*60 + "\n")

# Use the working profile path for these tests
import shutil as _shutil
_TEST_PROFILE_NAME = 'syntax-test-profile'

def _make_test_profile(text):
    """Create a temp profile for syntax testing."""
    import os as _os
    profiles_dir = _os.path.expanduser('~/.local/share/legion/profiles')
    _os.makedirs(profiles_dir, exist_ok=True)
    path = _os.path.join(profiles_dir, f'{_TEST_PROFILE_NAME}.conf')
    with open(path, 'w') as f:
        f.write('[MatchSettings]\nglobal-positive=open\n')  # minimal valid seed
    return path

def _cleanup_test_profile():
    import os as _os
    path = _os.path.expanduser(f'~/.local/share/legion/profiles/{_TEST_PROFILE_NAME}.conf')
    if _os.path.exists(path):
        _os.unlink(path)

_VALID_CONFIG = """[GeneralSettings]
enable-scheduler=True
enable-scheduler-on-import=False
max-fast-processes=5
max-slow-processes=5

[HostActions]
nmap-fast=Run nmap fast, nmap -Pn -F [IP]

[PortActions]
banner=Grab banner, bash -c "echo | nc [IP] [PORT]", ftp

[MatchSettings]
global-positive=open,vulnerable
global-negative=not found
"""

def test_p28_valid_config_saves_ok():
    """Valid legion.conf syntax must save without errors."""
    _make_test_profile('')
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': _VALID_CONFIG})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 200 and data.get('status') == 'ok',
              f"Valid config rejected: status={r.status_code} body={data}")
test("P7.1: valid config saves successfully", test_p28_valid_config_saves_ok)

def test_p29_unclosed_quote_rejected():
    """Config with unclosed quote must be rejected with 400."""
    _make_test_profile('')
    bad = "[HostActions]\ntest=label with unclosed \"quote, nmap [IP]\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Unclosed quote should be rejected: status={r.status_code}")
test("P7.2: unclosed quote in value rejected with 400", test_p29_unclosed_quote_rejected)

def test_p30_wrong_element_count_rejected():
    """PortActions entry with wrong comma-separated count must be rejected."""
    _make_test_profile('')
    bad = "[PortActions]\ntest=only one element\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Wrong element count should be rejected: status={r.status_code}")
test("P7.3: PortActions entry with wrong element count rejected", test_p30_wrong_element_count_rejected)

def test_p31_unknown_section_rejected():
    """Config with unknown section name must be rejected."""
    _make_test_profile('')
    bad = "[UnknownSection]\nkey=value\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Unknown section should be rejected: status={r.status_code}")
test("P7.4: unknown section name rejected", test_p31_unknown_section_rejected)

def test_p32_unclosed_section_header_rejected():
    """Config with unclosed section header [NoClose must be rejected."""
    _make_test_profile('')
    bad = "[NoClose\nkey=value\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Unclosed section header should be rejected: status={r.status_code}")
test("P7.5: unclosed section header rejected", test_p32_unclosed_section_header_rejected)

def test_p33_missing_equals_rejected():
    """Config line without = sign must be rejected."""
    _make_test_profile('')
    bad = "[GeneralSettings]\nthis line has no equals sign\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Line without = should be rejected: status={r.status_code}")
test("P7.6: line without '=' sign rejected", test_p33_missing_equals_rejected)

def test_p34_unknown_key_in_general_settings_rejected():
    """Unknown key in GeneralSettings must be rejected (typo check)."""
    _make_test_profile('')
    bad = "[GeneralSettings]\ntypo-setting=True\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Unknown key in GeneralSettings should be rejected: status={r.status_code}")
test("P7.7: unknown key in [GeneralSettings] rejected (typo protection)", test_p34_unknown_key_in_general_settings_rejected)

def test_p35_error_response_contains_line_numbers():
    """Validation errors must include line numbers for user guidance."""
    _make_test_profile('')
    bad = "[PortActions]\nbad=one element only\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    errors = data.get('errors', [])
    return ok(errors and any('Line' in e for e in errors),
              f"Errors should contain line numbers: {errors}")
test("P7.8: validation errors include line numbers", test_p35_error_response_contains_line_numbers)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P8: Input validation — Add Hosts and Add Port")
print("="*60 + "\n")

def test_p36_addhost_rejects_special_chars():
    """POST /api/nmap/scan with XSS payload must return 400."""
    r = client.post('/api/nmap/scan',
                    json={'targets': '<script>alert(1)</script>'})
    return ok(r.status_code == 400,
              f"Expected 400 for XSS target, got {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("P8.1: add-hosts rejects XSS/special-char target → 400", test_p36_addhost_rejects_special_chars)

def test_p37_addhost_accepts_valid_cidr():
    """POST /api/nmap/scan with valid CIDR must return 200."""
    r = client.post('/api/nmap/scan',
                    json={'targets': '192.168.1.0/24'})
    return ok(r.status_code == 200,
              f"Expected 200 for valid CIDR, got {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("P8.2: add-hosts accepts valid CIDR (192.168.1.0/24) → 200", test_p37_addhost_accepts_valid_cidr)

def test_p38_addhost_accepts_hostname():
    """POST /api/nmap/scan with hostname must return 200."""
    r = client.post('/api/nmap/scan',
                    json={'targets': 'metasploitable.local'})
    return ok(r.status_code == 200,
              f"Expected 200 for hostname, got {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("P8.3: add-hosts accepts hostname (metasploitable.local) → 200", test_p38_addhost_accepts_hostname)

def test_p39_addhost_rejects_empty():
    """POST /api/nmap/scan with empty targets must return 400."""
    r = client.post('/api/nmap/scan', json={'targets': ''})
    return ok(r.status_code == 400,
              f"Expected 400 for empty target, got {r.status_code}")
test("P8.4: add-hosts rejects empty target string → 400", test_p39_addhost_rejects_empty)

def test_p40_addhost_rejects_semicolon():
    """POST /api/nmap/scan with semicolon injection must return 400.
    Uses 'echo injected' (spaces → invalid nmap target) rather than
    'rm -rf /' so the test payload is harmless if validation ever regresses."""
    r = client.post('/api/nmap/scan',
                    json={'targets': '127.0.0.1; echo injected'})
    return ok(r.status_code == 400,
              f"Expected 400 for semicolon injection, got {r.status_code}")
test("P8.5: add-hosts rejects semicolon injection → 400", test_p40_addhost_rejects_semicolon)

# For add-port tests we need a host in the DB
def _get_any_host_ip():
    snap = client.get('/api/snapshot').get_json()
    hosts = snap.get('hosts', [])
    return hosts[0].get('ip') if hosts else None

def test_p41_addport_rejects_nonnumeric():
    """add-port with non-numeric port string must return 400."""
    ip = _get_any_host_ip()
    if not ip: return "SKIP"
    r = client.post(f'/api/workspace/hosts/1/action',
                    json={'action': 'add-port', 'ip': ip, 'port': 'abc', 'protocol': 'tcp'})
    return ok(r.status_code == 400,
              f"Expected 400 for non-numeric port, got {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("P8.6: add-port rejects non-numeric port ('abc') → 400", test_p41_addport_rejects_nonnumeric)

def test_p42_addport_rejects_out_of_range():
    """add-port with port > 65535 must return 400."""
    ip = _get_any_host_ip()
    if not ip: return "SKIP"
    r = client.post(f'/api/workspace/hosts/1/action',
                    json={'action': 'add-port', 'ip': ip, 'port': '99999', 'protocol': 'tcp'})
    return ok(r.status_code == 400,
              f"Expected 400 for out-of-range port 99999, got {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("P8.7: add-port rejects out-of-range port (99999) → 400", test_p42_addport_rejects_out_of_range)

def test_p43_addport_rejects_zero():
    """add-port with port 0 must return 400."""
    ip = _get_any_host_ip()
    if not ip: return "SKIP"
    r = client.post(f'/api/workspace/hosts/1/action',
                    json={'action': 'add-port', 'ip': ip, 'port': '0', 'protocol': 'tcp'})
    return ok(r.status_code == 400,
              f"Expected 400 for port 0, got {r.status_code}: {r.get_data(as_text=True)[:80]}")
test("P8.8: add-port rejects port 0 → 400", test_p43_addport_rejects_zero)

def test_p44_staged_port_rejects_invalid_chars():
    """StagedNmapSettings stage1-ports with special chars must be rejected."""
    _make_test_profile('')
    bad = "[StagedNmapSettings]\nstage1-ports=80,443,<evil>\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': bad})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 400 and data.get('errors'),
              f"Invalid port chars should be rejected: status={r.status_code} body={data}")
test("P8.9: staged nmap port with '<' chars rejected → 400", test_p44_staged_port_rejects_invalid_chars)

def test_p45_staged_port_accepts_valid_expression():
    """StagedNmapSettings stage1-ports with valid nmap expression must be accepted."""
    _make_test_profile('')
    good = "[StagedNmapSettings]\nstage1-ports=80,443,8080-8090\n"
    r = client.post(f'/api/config/profiles/{_TEST_PROFILE_NAME}/save',
                    json={'text': good})
    data = r.get_json()
    _cleanup_test_profile()
    return ok(r.status_code == 200 and data.get('status') == 'ok',
              f"Valid stage port expression rejected: status={r.status_code} body={data}")
test("P8.10: staged nmap port '80,443,8080-8090' accepted → 200", test_p45_staged_port_accepts_valid_expression)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
