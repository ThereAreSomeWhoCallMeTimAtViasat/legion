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
print("T2: Interactive detection in runCommand")
print("="*60 + "\n")

def test_t2_bash_command_starts_terminal():
    """runCommand with bash in command must create an Interactive process with session_id."""
    wc.start()
    result = wc.runCommand('bash -c "echo bash_detect_test"', name='bash-detect',
                           hostIp='10.99.99.1')
    pid = result.get('process_id')
    sid = result.get('session_id')
    if not pid:
        return "no process_id"
    return ok(sid is not None and len(str(sid)) > 10,
              f"Expected session_id for bash command, got: {sid!r}")
test("T2.1: bash command creates terminal session", test_t2_bash_command_starts_terminal)

def test_t2_msfconsole_command_starts_terminal():
    """runCommand with msfconsole in command must create a terminal session."""
    result = wc.runCommand(
        'msfconsole -q -x "echo msfconsole_detect_test; exit"',
        name='msf-detect', hostIp='10.99.99.1')
    sid = result.get('session_id')
    return ok(sid is not None, f"msfconsole command should produce session_id, got: {sid!r}")
test("T2.2: msfconsole command creates terminal session", test_t2_msfconsole_command_starts_terminal)

def test_t2_plain_command_no_terminal():
    """runCommand with nmap/nikto/etc. must NOT create a terminal session."""
    result = wc.runCommand('echo no_terminal_test', name='plain-detect', hostIp='10.99.99.1')
    sid = result.get('session_id')
    return ok(sid is None, f"Plain echo should NOT have session_id, got: {sid!r}")
test("T2.3: plain command has no terminal session", test_t2_plain_command_no_terminal)

def test_t2_interactive_excluded_from_queue():
    """Interactive processes must not count against process queue limits."""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    interactive = [p for p in procs if p.get('status') == 'Interactive']
    if not interactive:
        return "SKIP"
    # The interactive process should exist but NOT block queue from starting regular processes
    result = wc.runCommand('echo queue_check', name='queue-test', hostIp='10.99.99.1')
    pid = result.get('process_id')
    time.sleep(1.5)
    snap2 = client.get('/api/snapshot').get_json()
    proc = next((p for p in snap2.get('processes', []) if p.get('id') == pid), None)
    return ok(proc and proc.get('status') == 'Finished',
              f"Regular process should have finished despite interactive sessions. status={proc.get('status') if proc else 'not found'}")
test("T2.4: interactive processes excluded from queue count", test_t2_interactive_excluded_from_queue)

def test_t2_interactive_process_has_correct_snapshot_status():
    """Interactive process created by runCommand must appear in snapshot with status=Interactive."""
    result = wc.runCommand('bash -c "sleep 2"', name='status-check', hostIp='10.99.99.1')
    pid = result.get('process_id')
    sid = result.get('session_id')
    if not pid or not sid:
        return "SKIP"
    time.sleep(0.5)
    snap = client.get('/api/snapshot').get_json()
    proc = next((p for p in snap.get('processes', []) if p.get('id') == pid), None)
    if not proc:
        return f"process {pid} not in snapshot"
    results = []
    if proc.get('status') != 'Interactive':
        results.append(f"status={proc.get('status')}, expected Interactive")
    if proc.get('session_id') != sid:
        results.append(f"session_id mismatch: snapshot={proc.get('session_id')}, expected={sid}")
    return ok(not results, "; ".join(results))
test("T2.5: interactive process has correct status and session_id in snapshot", test_t2_interactive_process_has_correct_snapshot_status)

def test_t2_kill_interactive_cleans_terminal():
    """Killing an Interactive process must also close its terminal session."""
    result = wc.runCommand('bash -c "sleep 60"', name='kill-term-check', hostIp='10.99.99.1')
    pid = result.get('process_id')
    sid = result.get('session_id')
    if not pid or not sid:
        return "SKIP"
    time.sleep(0.5)
    # Kill it
    wc.killProcess(pid)
    time.sleep(0.5)
    # Terminal session should be gone
    r = client.get(f'/api/terminal/{sid}/output?offset=0')
    return ok(r.status_code == 404,
              f"Terminal session should be cleaned up after kill, got status={r.status_code}")
test("T2.6: killing interactive process cleans up terminal session", test_t2_kill_interactive_cleans_terminal)

def test_t2_retry_interactive_stays_interactive():
    """Retrying an Interactive process must create a new Interactive session."""
    result = wc.runCommand('bash -c "echo retry_source"', name='retry-int-check', hostIp='10.99.99.1')
    pid = result.get('process_id')
    sid = result.get('session_id')
    if not pid or not sid:
        return "SKIP"
    time.sleep(2)  # let it finish
    # Retry via the process action handler
    retry_result = wc.handleProcessAction(pid, 'retry')
    if not retry_result or not retry_result.get('new_result'):
        return f"retry returned: {retry_result}"
    new_result = retry_result['new_result']
    new_sid = new_result.get('session_id')
    return ok(new_sid is not None and new_sid != sid,
              f"Retry of interactive should create new session. new_sid={new_sid!r}, old_sid={sid!r}")
test("T2.7: retrying interactive process creates new interactive session", test_t2_retry_interactive_stays_interactive)


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
print("\n" + "="*60)
print("T4: Port menu terminal actions ([term] wiring)")
print("="*60 + "\n")

def test_t4_ssh_service_has_terminal_actions():
    """Port menu for ssh service must include terminal_actions."""
    r = client.get('/api/menus/port?service=ssh')
    data = r.get_json()
    term_actions = data.get('terminal_actions', [])
    return ok(len(term_actions) > 0,
              f"Expected terminal_actions for ssh, got: {term_actions}")
test("T4.1: ssh service has terminal_actions in port menu", test_t4_ssh_service_has_terminal_actions)

def test_t4_terminal_actions_have_correct_structure():
    """terminal_actions must have label, action='terminal-action', and command fields."""
    r = client.get('/api/menus/port?service=ssh')
    data = r.get_json()
    term_actions = data.get('terminal_actions', [])
    if not term_actions:
        return "SKIP"
    missing = []
    for a in term_actions:
        if not a.get('label'): missing.append(f"no label: {a}")
        if a.get('action') != 'terminal-action': missing.append(f"wrong action: {a}")
        if not a.get('command'): missing.append(f"no command: {a}")
    return ok(not missing, "; ".join(missing))
test("T4.2: terminal_actions have label/action/command fields", test_t4_terminal_actions_have_correct_structure)

def test_t4_ssh_action_command_contains_ssh():
    """The ssh terminal action command must contain 'ssh'."""
    r = client.get('/api/menus/port?service=ssh')
    data = r.get_json()
    term_actions = data.get('terminal_actions', [])
    ssh_actions = [a for a in term_actions if 'ssh' in a.get('label', '').lower()
                   or 'ssh' in a.get('command', '').lower()]
    return ok(len(ssh_actions) > 0,
              f"No ssh-related terminal action found. Actions: {[a.get('label') for a in term_actions]}")
test("T4.3: ssh service has an ssh terminal action", test_t4_ssh_action_command_contains_ssh)

def test_t4_ftp_service_has_terminal_actions():
    """Port menu for ftp service must include terminal_actions."""
    r = client.get('/api/menus/port?service=ftp')
    data = r.get_json()
    term_actions = data.get('terminal_actions', [])
    return ok(len(term_actions) > 0,
              f"Expected terminal_actions for ftp, got empty list")
test("T4.4: ftp service has terminal_actions in port menu", test_t4_ftp_service_has_terminal_actions)

def test_t4_wildcard_service_has_all_terminal_actions():
    """Port menu for service='*' must return all terminal_actions."""
    r_ssh = client.get('/api/menus/port?service=ssh')
    r_all = client.get('/api/menus/port?service=*')
    ssh_count = len(r_ssh.get_json().get('terminal_actions', []))
    all_count = len(r_all.get_json().get('terminal_actions', []))
    return ok(all_count >= ssh_count,
              f"Wildcard should have >= ssh actions. ssh={ssh_count} all={all_count}")
test("T4.5: wildcard service returns all terminal_actions", test_t4_wildcard_service_has_all_terminal_actions)

def test_t4_start_with_term_command_creates_session():
    """Starting a terminal with a [term] command (e.g. ssh) correctly creates a PTY session."""
    r = client.post('/api/terminal/start', json={
        'label': 'Open with ssh client',
        'host_ip': '10.99.99.1',
        'command': 'ssh root@10.99.99.1 -p 22',
    })
    data = r.get_json()
    sid = data.get('session_id')
    pid = data.get('process_id')
    return ok(r.status_code == 200 and sid and pid,
              f"status={r.status_code}, session_id={sid}, process_id={pid}")
test("T4.6: terminal/start with ssh command creates session", test_t4_start_with_term_command_creates_session)

def test_t4_term_command_dispatched_after_delay():
    """Command passed to /api/terminal/start is dispatched to bash after delay."""
    r = client.post('/api/terminal/start', json={
        'label': 'netcat-test',
        'host_ip': '10.99.99.1',
        'command': 'echo TERM_CMD_DISPATCH_TEST',
    })
    sid = r.get_json().get('session_id')
    if not sid:
        return "start failed"
    # Wait for command to be dispatched (500ms delay) and output to appear
    output = ''
    for _ in range(30):
        time.sleep(0.1)
        r2 = client.get(f'/api/terminal/{sid}/output?offset=0')
        if r2.status_code == 200:
            output = r2.get_json().get('data', '')
            if 'TERM_CMD_DISPATCH_TEST' in output:
                break
    return ok('TERM_CMD_DISPATCH_TEST' in output,
              f"Command not dispatched. Output ({len(output)}b): {output[:200]!r}")
test("T4.7: command is dispatched to bash stdin after 500ms", test_t4_term_command_dispatched_after_delay)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("T5: Snapshot — session_id correctly present/absent")
print("="*60 + "\n")

def test_t5_interactive_in_snapshot_has_session_id():
    """Every Interactive process in snapshot must have a non-null session_id."""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    interactive = [p for p in procs if p.get('status') == 'Interactive']
    if not interactive:
        return "SKIP"
    missing_sid = [p.get('name') for p in interactive if not p.get('session_id')]
    return ok(not missing_sid,
              f"Interactive processes without session_id: {missing_sid}")
test("T5.1: all Interactive processes have session_id in snapshot", test_t5_interactive_in_snapshot_has_session_id)

def test_t5_finished_processes_no_session_id():
    """Finished processes must have session_id=null."""
    snap = client.get('/api/snapshot').get_json()
    procs = snap.get('processes', [])
    finished = [p for p in procs if p.get('status') == 'Finished']
    with_sid = [p.get('name') for p in finished if p.get('session_id')]
    return ok(not with_sid,
              f"Finished processes should not have session_id: {with_sid}")
test("T5.2: Finished processes have no session_id", test_t5_finished_processes_no_session_id)

def test_t5_session_id_format():
    """session_id must be a valid UUID format."""
    import re
    r = client.post('/api/terminal/start', json={
        'label': 'uuid-check',
        'host_ip': '10.99.99.1',
    })
    sid = r.get_json().get('session_id', '')
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
    return ok(bool(uuid_pattern.match(sid)),
              f"session_id not a valid UUID: {sid!r}")
test("T5.3: session_id is a valid UUID", test_t5_session_id_format)

def test_t5_delete_removes_session_from_snapshot():
    """After DELETE, the Interactive process must be gone from snapshot."""
    r = client.post('/api/terminal/start', json={
        'label': 'snapshot-delete-check',
        'host_ip': '10.99.99.1',
    })
    pid = r.get_json().get('process_id')
    sid = r.get_json().get('session_id')
    if not pid or not sid:
        return "SKIP"
    # Verify it's in snapshot
    snap = client.get('/api/snapshot').get_json()
    found = any(p.get('session_id') == sid for p in snap.get('processes', []))
    if not found:
        return "FAIL: process not in snapshot before delete"
    # Delete
    client.delete(f'/api/terminal/{sid}')
    time.sleep(0.3)
    # Should be gone from snapshot (closed)
    snap2 = client.get('/api/snapshot').get_json()
    still_there = any(p.get('session_id') == sid for p in snap2.get('processes', []))
    return ok(not still_there,
              f"Process with session_id={sid} still in snapshot after delete")
test("T5.4: delete removes terminal session from snapshot", test_t5_delete_removes_session_from_snapshot)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
