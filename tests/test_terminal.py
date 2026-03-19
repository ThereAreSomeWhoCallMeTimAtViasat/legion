#!/usr/bin/env python3
"""
Terminal Feature Tests — PTY session lifecycle + interactive detection
=======================================================================
Run with: sudo python3 tests/test_terminal.py

Step 1: T1.x  — Terminal session lifecycle (start, output, input, resize, delete)
Step 2: T2.x  — Port/host action interactive detection
         T3.x  — Regression (regular processes unaffected)
"""

import os
import sys
import time
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


# ── Setup ──────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.importers.nmap_import import import_nmap_xml
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

# Seed one host so we have something to work with
_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.99.99.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="21"><state state="open"/><service name="ftp"/></port>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
    </ports>
  </host>
</nmaprun>"""
with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _seed_path = _f.name
import_nmap_xml(project=logic.activeProject, xml_path=_seed_path, output="")
os.unlink(_seed_path)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("T1: Terminal session lifecycle")
print("="*60 + "\n")

def test_t1_start_returns_session_and_process_id():
    """POST /api/terminal/start must return session_id and process_id."""
    r = client.post('/api/terminal/start', json={
        'label': 'test-terminal',
        'host_ip': '10.99.99.1',
    })
    data = r.get_json()
    return ok(r.status_code == 200
              and data.get('session_id')
              and data.get('process_id'),
              f"status={r.status_code}, body={data}")
test("T1.1: start returns session_id and process_id", test_t1_start_returns_session_and_process_id)

def test_t1_start_creates_interactive_process():
    """After start, snapshot must include a process with status='Interactive'."""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    interactive = [p for p in procs if p.get('status') == 'Interactive']
    return ok(len(interactive) > 0,
              f"No Interactive process in snapshot. Statuses: {[p.get('status') for p in procs]}")
test("T1.2: start creates Interactive process in snapshot", test_t1_start_creates_interactive_process)

def test_t1_session_id_in_snapshot():
    """The Interactive process in snapshot must have session_id matching the start response."""
    # Start a fresh session to get a known session_id
    r = client.post('/api/terminal/start', json={
        'label': 'snapshot-check',
        'host_ip': '10.99.99.1',
    })
    data = r.get_json()
    sid = data.get('session_id')
    if not sid:
        return "start did not return session_id"
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    matching = [p for p in procs if p.get('session_id') == sid]
    return ok(len(matching) == 1,
              f"Expected 1 process with session_id={sid}, found {len(matching)}. "
              f"Process session_ids: {[p.get('session_id') for p in procs]}")
test("T1.3: session_id appears in snapshot process", test_t1_session_id_in_snapshot)

def test_t1_output_has_bash_prompt():
    """GET output at offset 0 must eventually contain a bash prompt ($ or #)."""
    r = client.post('/api/terminal/start', json={
        'label': 'prompt-check',
        'host_ip': '10.99.99.1',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    # Poll for up to 3s
    output = ''
    for _ in range(30):
        time.sleep(0.1)
        r2 = client.get(f'/api/terminal/{sid}/output?offset=0')
        if r2.status_code == 200:
            output = r2.get_json().get('data', '')
            if '$' in output or '#' in output:
                break
    return ok('$' in output or '#' in output,
              f"No bash prompt found in output ({len(output)} bytes): {output[:200]!r}")
test("T1.4: output contains bash prompt", test_t1_output_has_bash_prompt)

def test_t1_output_offset_no_duplication():
    """Reading with offset should not return data already consumed."""
    r = client.post('/api/terminal/start', json={
        'label': 'offset-check',
        'host_ip': '10.99.99.1',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    time.sleep(1)
    r1 = client.get(f'/api/terminal/{sid}/output?offset=0')
    d1 = r1.get_json()
    first_data = d1.get('data', '')
    next_offset = d1.get('offset', 0) + len(first_data)
    # Read again at the new offset — should be empty or very short (new prompt chars)
    r2 = client.get(f'/api/terminal/{sid}/output?offset={next_offset}')
    d2 = r2.get_json()
    second_data = d2.get('data', '')
    # The second read must NOT contain all of the first data
    if len(first_data) > 10 and first_data in second_data:
        return f"FAIL: second read duplicates first data ({len(first_data)} bytes)"
    return True
test("T1.5: output offset prevents duplication", test_t1_output_offset_no_duplication)

def test_t1_command_executed():
    """Start with a command — output must contain the command's result."""
    r = client.post('/api/terminal/start', json={
        'label': 'cmd-check',
        'host_ip': '10.99.99.1',
        'command': 'echo TERMINAL_MARKER_12345',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    # Wait for the command to be dispatched (500ms delay) and output to appear
    output = ''
    for _ in range(40):
        time.sleep(0.1)
        r2 = client.get(f'/api/terminal/{sid}/output?offset=0')
        if r2.status_code == 200:
            output = r2.get_json().get('data', '')
            if 'TERMINAL_MARKER_12345' in output:
                break
    return ok('TERMINAL_MARKER_12345' in output,
              f"Command output not found in {len(output)} bytes: {output[:300]!r}")
test("T1.6: command dispatched and executed in terminal", test_t1_command_executed)

def test_t1_input_interactive():
    """Write to stdin via /input — output must reflect it."""
    r = client.post('/api/terminal/start', json={
        'label': 'input-check',
        'host_ip': '10.99.99.1',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    time.sleep(1)  # let bash start
    # Send a command via input
    r2 = client.post(f'/api/terminal/{sid}/input', json={
        'data': 'echo INPUT_CHECK_67890\n',
    })
    if r2.status_code != 200:
        return f"input POST returned {r2.status_code}"
    # Wait for output
    output = ''
    for _ in range(30):
        time.sleep(0.1)
        r3 = client.get(f'/api/terminal/{sid}/output?offset=0')
        if r3.status_code == 200:
            output = r3.get_json().get('data', '')
            if 'INPUT_CHECK_67890' in output:
                break
    return ok('INPUT_CHECK_67890' in output,
              f"Input echo not in output: {output[:300]!r}")
test("T1.7: input posted to terminal appears in output", test_t1_input_interactive)

def test_t1_input_ctrl_c():
    """Ctrl+C (\\x03) must not crash the session; session must stay alive."""
    r = client.post('/api/terminal/start', json={
        'label': 'ctrlc-check',
        'host_ip': '10.99.99.1',
        'command': 'sleep 30',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    time.sleep(1.5)
    # Send Ctrl+C
    r2 = client.post(f'/api/terminal/{sid}/input', json={'data': '\x03'})
    if r2.status_code != 200:
        return f"Ctrl+C input returned {r2.status_code}"
    time.sleep(0.5)
    # Session should still be alive
    r3 = client.get(f'/api/terminal/{sid}/output?offset=0')
    alive = r3.get_json().get('alive', False)
    return ok(r3.status_code == 200 and alive,
              f"Session died after Ctrl+C. status={r3.status_code}, alive={alive}")
test("T1.8: Ctrl+C does not kill session", test_t1_input_ctrl_c)

def test_t1_resize():
    """POST resize must return 200."""
    r = client.post('/api/terminal/start', json={
        'label': 'resize-check',
        'host_ip': '10.99.99.1',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    time.sleep(0.3)
    r2 = client.post(f'/api/terminal/{sid}/resize', json={'rows': 30, 'cols': 120})
    return ok(r2.status_code == 200, f"resize returned {r2.status_code}")
test("T1.9: resize accepted", test_t1_resize)

def test_t1_delete_terminates():
    """DELETE session must terminate the bash process."""
    r = client.post('/api/terminal/start', json={
        'label': 'delete-check',
        'host_ip': '10.99.99.1',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start did not return session_id"
    time.sleep(0.5)
    r2 = client.delete(f'/api/terminal/{sid}')
    if r2.status_code != 200:
        return f"DELETE returned {r2.status_code}"
    time.sleep(0.3)
    # Subsequent request should 404
    r3 = client.get(f'/api/terminal/{sid}/output?offset=0')
    return ok(r3.status_code == 404, f"Expected 404 after delete, got {r3.status_code}")
test("T1.10: delete terminates session", test_t1_delete_terminates)

def test_t1_nonexistent_404():
    """Requests to nonexistent session_id must 404."""
    fake_id = 'nonexistent-session-id-12345'
    r1 = client.get(f'/api/terminal/{fake_id}/output?offset=0')
    r2 = client.post(f'/api/terminal/{fake_id}/input', json={'data': 'x'})
    r3 = client.delete(f'/api/terminal/{fake_id}')
    codes = (r1.status_code, r2.status_code, r3.status_code)
    return ok(all(c == 404 for c in codes),
              f"Expected (404,404,404), got {codes}")
test("T1.11: nonexistent session returns 404", test_t1_nonexistent_404)

def test_t1_two_sessions_independent():
    """Two sessions must have independent output."""
    r1 = client.post('/api/terminal/start', json={
        'label': 'session-A',
        'host_ip': '10.99.99.1',
        'command': 'echo SESSION_A_MARKER',
    })
    r2 = client.post('/api/terminal/start', json={
        'label': 'session-B',
        'host_ip': '10.99.99.1',
        'command': 'echo SESSION_B_MARKER',
    })
    sid_a = r1.get_json().get('session_id')
    sid_b = r2.get_json().get('session_id')
    if not sid_a or not sid_b:
        return "SKIP"
    time.sleep(2)
    out_a = client.get(f'/api/terminal/{sid_a}/output?offset=0').get_json().get('data', '')
    out_b = client.get(f'/api/terminal/{sid_b}/output?offset=0').get_json().get('data', '')
    results = []
    if 'SESSION_A_MARKER' not in out_a:
        results.append(f"A missing its marker in {len(out_a)}b")
    if 'SESSION_B_MARKER' in out_a:
        results.append(f"B marker leaked into A")
    if 'SESSION_B_MARKER' not in out_b:
        results.append(f"B missing its marker in {len(out_b)}b")
    if 'SESSION_A_MARKER' in out_b:
        results.append(f"A marker leaked into B")
    return ok(not results, "; ".join(results))
test("T1.12: two sessions are independent", test_t1_two_sessions_independent)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("T3: Regression — regular processes unaffected")
print("="*60 + "\n")

def test_t3_echo_still_plain():
    """echo command must still produce plain output, status=Finished, no session_id."""
    wc.start()
    result = wc.runCommand('echo plain_test_output', name='plain-echo', hostIp='10.99.99.1')
    pid = result.get('process_id')
    if not pid:
        return "no process_id"
    time.sleep(1.5)
    snap = client.get('/api/snapshot').get_json()
    proc = next((p for p in snap.get('processes', []) if p.get('id') == pid), None)
    if not proc:
        return f"process {pid} not in snapshot"
    results = []
    if proc.get('status') != 'Finished':
        results.append(f"status={proc.get('status')}, expected Finished")
    if proc.get('session_id'):
        results.append(f"has session_id={proc.get('session_id')} (should be null)")
    # Check output is accessible the old way
    r = client.get(f'/api/processes/{pid}/output')
    out = r.get_json().get('output_chunk', '') or r.get_json().get('output', '')
    if 'plain_test_output' not in out:
        results.append(f"output missing expected text")
    return ok(not results, "; ".join(results))
test("T3.1: echo process is plain, Finished, no session_id", test_t3_echo_still_plain)

def test_t3_snapshot_no_session_id_for_regular():
    """Regular processes in snapshot must have session_id=null/None."""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    regular = [p for p in procs if p.get('status') in ('Finished', 'Running', 'Waiting')]
    bad = [p.get('name') for p in regular if p.get('session_id')]
    return ok(not bad, f"Regular processes with session_id: {bad}")
test("T3.2: regular processes have no session_id", test_t3_snapshot_no_session_id_for_regular)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
