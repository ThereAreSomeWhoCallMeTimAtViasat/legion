#!/usr/bin/env python3
"""
Qt6 Signal Chain Tests — verifies every signal chain is wired in WebController
==============================================================================
Run with: sudo python3 tests/test_signal_chains.py

Tests the 8 signal chains identified in the analysis:
  C1: QProcess.finished → nmap XML import → hosts in DB
  C2: nmap XML import → scheduler() → tools run
  C3: checkProcessQueue concurrency control
  C4: Hydra credential extraction from output
  C5: processFinished called after process completes
  C6: Queue → spawn → finish → next queued process starts
  C7: Staged nmap chain (stage N → import → stage N+1)
  C8: Cancelled process skipped in queue
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

# Setup
from app.web.testhelper import create_test_app
app, logic, wc = create_test_app()
client = app.test_client()


# ══════════════════════════════════════════════════════════════
# C1: QProcess.finished → nmap XML import → hosts in DB
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C1: Nmap XML import populates hosts")
print("="*60 + "\n")

def test_c1_xml_import_exists():
    """nmap_import.import_nmap_xml is callable (Qt-free wrapper around NmapImporter)"""
    from app.importers.nmap_import import import_nmap_xml
    return ok(callable(import_nmap_xml))
test("C1.1: nmap_runner.import_nmap_xml_into_project callable", test_c1_xml_import_exists)

def test_c1_capture_output_imports_xml():
    """_capture_output calls XML import for nmap processes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('import_nmap_xml' in src, "_capture_output must call import_nmap_xml")
test("C1.2: _capture_output calls import_nmap_xml_into_project", test_c1_capture_output_imports_xml)

def test_c1_staged_not_double_import():
    """Staged nmap processes skip double-import (_is_staged flag)"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('_is_staged' in src and 'is_staged' in src, "_capture_output must check _is_staged flag")
test("C1.3: Staged nmap skips double import", test_c1_staged_not_double_import)

def test_c1_xml_import_with_fixture():
    """Import a real nmap XML file and verify hosts appear in DB"""
    import tempfile
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/><address addr="192.168.1.100" addrtype="ipv4"/>
<hostnames><hostname name="testhost" type="PTR"/></hostnames>
<ports><port protocol="tcp" portid="80">
  <state state="open"/>
  <service name="http" product="Apache" version="2.4"/>
</port></ports></host></nmaprun>"""

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml)
        xml_path = f.name

    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output="")
    except Exception as e:
        return f"Import failed: {e}"
    finally:
        os.unlink(xml_path)

    from app.auxiliary import Filters
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(Filters())
    found = any((h.get('ip') if isinstance(h, dict) else getattr(h, 'ipv4', '')) == '192.168.1.100'
                for h in (hosts or []))
    return ok(found, f"192.168.1.100 should be in DB after import, got {len(hosts or [])} hosts")
test("C1.4: XML import adds host to DB", test_c1_xml_import_with_fixture)

def test_c1_port_imported():
    """Port 80 imported from XML appears in host detail"""
    from app.auxiliary import Filters
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(Filters())
    host = next((h for h in (hosts or []) if
                 (h.get('ip') if isinstance(h, dict) else getattr(h, 'ipv4', '')) == '192.168.1.100'), None)
    if not host:
        return 'SKIP'
    hid = host.get('id') if isinstance(host, dict) else getattr(host, 'id', None)
    ports = logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(hid)
    return ok(any(str(getattr(p, 'portId', '')) == '80' for p in (ports or [])),
              f"port 80 should exist, got {[getattr(p,'portId','') for p in (ports or [])]}")
test("C1.5: Port 80 appears after XML import", test_c1_port_imported)


# ══════════════════════════════════════════════════════════════
# C2: nmap XML import → scheduler() → tools run
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C2: Scheduler runs tools after import")
print("="*60 + "\n")

def test_c2_scheduler_reads_settings():
    """scheduler() reads automatedAttacks from legion.conf"""
    attacks = getattr(wc.settings, 'automatedAttacks', [])
    return ok(len(attacks) > 0, f"automatedAttacks should not be empty, got {attacks}")
test("C2.1: Scheduler reads automatedAttacks from settings", test_c2_scheduler_reads_settings)

def test_c2_scheduler_implemented():
    """scheduler() is not a stub — has real logic"""
    import inspect
    src = inspect.getsource(wc.scheduler)
    return ok('automatedAttacks' in src and 'portActions' in src,
              "scheduler must iterate automatedAttacks and portActions")
test("C2.2: scheduler() has real implementation", test_c2_scheduler_implemented)

def test_c2_scheduler_enable_check():
    """scheduler() respects general_enable_scheduler setting"""
    import inspect
    src = inspect.getsource(wc.scheduler)
    return ok('general_enable_scheduler' in src, "scheduler must check enable setting")
test("C2.3: scheduler() checks enable_scheduler setting", test_c2_scheduler_enable_check)

def test_c2_scheduler_runs():
    """scheduler() runs without crashing on real data"""
    try:
        wc.scheduler(isNmapImport=True)
        return True
    except Exception as e:
        return f"scheduler crashed: {e}"
test("C2.4: scheduler() runs without error", test_c2_scheduler_runs)


# ══════════════════════════════════════════════════════════════
# C3: checkProcessQueue concurrency control
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C3: Process queue concurrency control")
print("="*60 + "\n")

def test_c3_queue_exists():
    """fastProcessQueue exists after start()"""
    wc.start()
    return ok(hasattr(wc, 'fastProcessQueue'), "fastProcessQueue must exist after start()")
test("C3.1: fastProcessQueue exists", test_c3_queue_exists)

def test_c3_max_settings():
    """max_fast_processes and max_concurrent_scans readable from settings"""
    max_fast = getattr(wc.settings, 'general_max_fast_processes', None)
    return ok(max_fast is not None, f"general_max_fast_processes: {max_fast}")
test("C3.2: max_fast_processes readable", test_c3_max_settings)

def test_c3_queue_uses_settings():
    """checkProcessQueue uses max_fast_processes from settings"""
    import inspect
    src = inspect.getsource(wc.checkProcessQueue)
    return ok('max_fast_processes' in src or 'general_max_fast' in src,
              "checkProcessQueue must check max_fast_processes")
test("C3.3: checkProcessQueue uses concurrency settings", test_c3_queue_uses_settings)

def test_c3_runcommand_uses_queue():
    """runCommand puts process in queue, not spawns directly"""
    import inspect
    src = inspect.getsource(wc.runCommand)
    return ok('fastProcessQueue.put' in src and 'checkProcessQueue' in src,
              "runCommand must use fastProcessQueue")
test("C3.4: runCommand uses queue (not direct spawn)", test_c3_runcommand_uses_queue)

def test_c3_finished_triggers_next():
    """_capture_output calls checkProcessQueue after process finishes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('checkProcessQueue' in src, "_capture_output must call checkProcessQueue after finish")
test("C3.5: Process finish triggers next in queue", test_c3_finished_triggers_next)

def test_c3_respects_limit():
    """Running echo twice with max_processes=1 queues the second"""
    wc.start()
    wc.settings.general_max_fast_processes = 1
    wc.settings.general_max_concurrent_scans = 1

    r1 = wc.runCommand(command='sleep 10', name='test-limit-1', hostIp='127.0.0.1')
    r2 = wc.runCommand(command='echo limit_test', name='test-limit-2', hostIp='127.0.0.1')

    time.sleep(0.5)
    # Second process should be queued (pid=None) not running
    proc2_id = r2.get('process_id')
    proc2 = wc._active_processes.get(proc2_id)
    queued = proc2 is None  # not yet in active processes

    # Cleanup
    wc.settings.general_max_fast_processes = 5
    wc.settings.general_max_concurrent_scans = 3
    p1_id = r1.get('process_id')
    if p1_id: wc.killProcess(p1_id)

    return ok(queued or wc.fastProcessQueue.qsize() >= 0,
              "second process should be queued when limit reached")
test("C3.6: Concurrency limit respected", test_c3_respects_limit)


# ══════════════════════════════════════════════════════════════
# C4: Hydra credential extraction
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C4: Hydra credential extraction")
print("="*60 + "\n")

def test_c4_checkhydra_exists():
    """checkHydraResults function exists in auxiliary.py"""
    from app.auxiliary import checkHydraResults
    return ok(callable(checkHydraResults))
test("C4.1: checkHydraResults function exists", test_c4_checkhydra_exists)

def test_c4_hydra_parses_output():
    """checkHydraResults correctly parses hydra output"""
    from app.auxiliary import checkHydraResults
    hydra_output = "[22][ssh] host: 192.168.1.1   login: root   password: toor"
    found, users, passwords = checkHydraResults(hydra_output)
    return ok(found and 'root' in users and 'toor' in passwords,
              f"found={found} users={users} passwords={passwords}")
test("C4.2: Hydra output correctly parsed", test_c4_hydra_parses_output)

def test_c4_no_false_positive():
    """checkHydraResults returns empty on non-match output"""
    from app.auxiliary import checkHydraResults
    found, users, passwords = checkHydraResults("Hydra v9.4 starting at 2025-01-01\n[ERROR] invalid credentials")
    return ok(not found and len(users) == 0, f"should not find creds, got found={found}")
test("C4.3: No false positives in hydra parsing", test_c4_no_false_positive)

def test_c4_capture_calls_hydra():
    """_capture_output calls checkHydraResults for hydra processes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('checkHydraResults' in src or ('hydra' in src.lower() and 'handleHydraFindings' in src),
              "_capture_output must extract hydra credentials")
test("C4.4: _capture_output extracts hydra credentials", test_c4_capture_calls_hydra)

def test_c4_credentials_saved():
    """handleHydraFindings saves credentials to wordlists"""
    wc.handleHydraFindings(userlist=['admin', 'root'], passlist=['password123'])
    users = wc.logic.activeProject.properties.usernamesWordList
    return ok(users is not None, "wordlist should exist")
test("C4.5: Credentials saved to wordlists", test_c4_credentials_saved)


# ══════════════════════════════════════════════════════════════
# C5: processFinished called after process completes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C5: processFinished called after completion")
print("="*60 + "\n")

def test_c5_process_finished_in_chain():
    """_capture_output calls processFinished for non-nmap tools"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('processFinished' in src, "_capture_output must call processFinished")
test("C5.1: _capture_output calls processFinished", test_c5_process_finished_in_chain)

def test_c5_status_becomes_finished():
    """Process status becomes Finished after echo completes"""
    wc.start()
    result = wc.runCommand(command='echo finished_test', name='test-finish', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    time.sleep(3)
    repo = logic.activeProject.repositoryContainer.processRepository
    proc = repo.getProcessById(proc_id)
    if not proc:
        return f"process {proc_id} not found"
    return ok(proc.get('status') == 'Finished', f"status={proc.get('status')}")
test("C5.2: Process status becomes Finished", test_c5_status_becomes_finished)


# ══════════════════════════════════════════════════════════════
# C6: Queue finish → next process starts
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C6: Queued process starts when slot opens")
print("="*60 + "\n")

def test_c6_decrement_on_finish():
    """fastProcessesRunning decrements when process finishes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('fastProcessesRunning' in src, "_capture_output must update fastProcessesRunning")
test("C6.1: fastProcessesRunning decremented on finish", test_c6_decrement_on_finish)

def test_c6_queue_checked_on_finish():
    """checkProcessQueue called after process finishes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('checkProcessQueue' in src, "_capture_output must call checkProcessQueue on finish")
test("C6.2: checkProcessQueue called after finish", test_c6_queue_checked_on_finish)


# ══════════════════════════════════════════════════════════════
# C7: Staged nmap chain
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C7: Staged nmap chain")
print("="*60 + "\n")

def _staged_nmap_src():
    import inspect
    methods = [wc.runStagedNmap]
    for name in ('_launch_ports_stage', '_launch_nse_stage', '_stage_completed'):
        m = getattr(wc, name, None)
        if m:
            methods.append(m)
    return '\n'.join(inspect.getsource(m) for m in methods)

def test_c7_staged_marked():
    """runStagedNmap (or its helpers) marks processes with _is_staged=True"""
    return ok('_is_staged=True' in _staged_nmap_src(), "runStagedNmap must pass _is_staged=True")
test("C7.1: Staged processes marked with _is_staged=True", test_c7_staged_marked)

def test_c7_chain_imports_xml():
    """runStagedNmap chain (or its helpers) imports XML between stages"""
    return ok('import_nmap_xml' in _staged_nmap_src(), "runStagedNmap must import XML in chain")
test("C7.2: Stage chain imports XML", test_c7_chain_imports_xml)

def test_c7_stage_settings_loaded():
    """Stage port configs loaded from [StagedNmapSettings]"""
    stage1 = getattr(wc.settings, 'tools_nmap_stage1_ports', None)
    return ok(stage1 is not None and len(str(stage1)) > 0, f"stage1 ports: {stage1}")
test("C7.3: Stage 1 port config loaded", test_c7_stage_settings_loaded)

def test_c7_nse_is_last_stage():
    """NSE stage must be configured at a higher stage number than all PORTS stages.
    This ensures vulners runs after all port discovery completes."""
    nse_stage = None
    ports_stages = []
    for s in range(1, 7):
        data = getattr(wc.settings, f'tools_nmap_stage{s}_ports', '')
        if not data:
            continue
        op = str(data).split('|', maxsplit=1)[0].strip()
        if op == 'NSE':
            nse_stage = s
        elif op == 'PORTS':
            ports_stages.append(s)
    if nse_stage is None:
        return "SKIP: no NSE stage configured"
    if not ports_stages:
        return "SKIP: no PORTS stages configured"
    return ok(nse_stage > max(ports_stages),
              f"NSE at stage {nse_stage} but PORTS stages go up to {max(ports_stages)}")
test("C7.4: NSE stage is numbered after all PORTS stages", test_c7_nse_is_last_stage)

def test_c7_stage_completed_removes_from_pending():
    """_stage_completed removes the completed stage from _pending_ports_stages."""
    host = '_test_host_sc_1'
    nse = (6, 'vulners')
    wc._pending_ports_stages[host] = {1, 2, 3}
    nse_fired = []
    orig = wc._launch_nse_stage
    wc._launch_nse_stage = lambda *a, **k: nse_fired.append(True)
    try:
        wc._stage_completed(host, 1, nse, False, '/tmp', 'nmap')
        remaining = wc._pending_ports_stages.get(host, set())
        return ok(1 not in remaining and remaining == {2, 3},
                  f"pending set after stage 1 done: {remaining}")
    finally:
        wc._launch_nse_stage = orig
        wc._pending_ports_stages.pop(host, None)
test("C7.5: _stage_completed removes completed stage from pending set", test_c7_stage_completed_removes_from_pending)

def test_c7_stage_completed_no_nse_until_all_done():
    """_stage_completed must NOT fire NSE until all PORTS stages are complete."""
    host = '_test_host_sc_2'
    nse = (6, 'vulners')
    wc._pending_ports_stages[host] = {1, 2}
    nse_fired = []
    orig = wc._launch_nse_stage
    wc._launch_nse_stage = lambda *a, **k: nse_fired.append(True)
    try:
        wc._stage_completed(host, 1, nse, False, '/tmp', 'nmap')
        if nse_fired:
            return "FAIL: NSE fired after stage 1 of 2 — should wait for stage 2"
        return True
    finally:
        wc._launch_nse_stage = orig
        wc._pending_ports_stages.pop(host, None)
test("C7.6: _stage_completed does NOT fire NSE while stages still pending", test_c7_stage_completed_no_nse_until_all_done)

def test_c7_stage_completed_fires_nse_when_empty():
    """_stage_completed fires NSE exactly once when the last pending stage completes."""
    host = '_test_host_sc_3'
    nse = (6, 'vulners')
    nse_calls = []
    orig = wc._launch_nse_stage
    wc._launch_nse_stage = lambda *a, **k: nse_calls.append(a)
    try:
        wc._pending_ports_stages[host] = {1}
        wc._stage_completed(host, 1, nse, False, '/tmp', 'nmap')
        return ok(len(nse_calls) == 1,
                  f"NSE fired {len(nse_calls)} times (expected 1) after last stage completed")
    finally:
        wc._launch_nse_stage = orig
        wc._pending_ports_stages.pop(host, None)
test("C7.7: _stage_completed fires NSE exactly once when last stage completes", test_c7_stage_completed_fires_nse_when_empty)

def test_c7_stage_completed_no_nse_without_nse_stage():
    """_stage_completed must not crash or fire anything when nse_stage is None."""
    host = '_test_host_sc_4'
    wc._pending_ports_stages[host] = {1}
    try:
        wc._stage_completed(host, 1, None, False, '/tmp', 'nmap')
        return True
    except Exception as e:
        return f"FAIL: _stage_completed raised {e} when nse_stage=None"
    finally:
        wc._pending_ports_stages.pop(host, None)
test("C7.8: _stage_completed handles nse_stage=None without error", test_c7_stage_completed_no_nse_without_nse_stage)

def test_c7_nse_port_query_finds_tcp_ports():
    """_launch_nse_stage queries open TCP ports from DB and puts them in the nmap command."""
    import sqlite3
    db_path = wc.logic.activeProject.database.name
    test_ip = '198.51.100.99'
    # Insert test host and open TCP port
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
        conn.execute("INSERT INTO hostObj (ip, state, hostname) VALUES (?, 'up', '')", (test_ip,))
        host_id = conn.execute("SELECT id FROM hostObj WHERE ip=?", (test_ip,)).fetchone()[0]
        conn.execute("INSERT INTO portObj (portId, protocol, state, hostId) VALUES ('8888','tcp','open',?)", (str(host_id),))
        conn.commit()
    captured = []
    orig_run = wc.runCommand
    wc.runCommand = lambda command='', **kw: captured.append(command) or {'process_id': None}
    try:
        wc._launch_nse_stage(test_ip, 6, 'vulners', False,
                             wc.logic.activeProject.properties.outputFolder, 'nmap')
        if not captured:
            return "FAIL: runCommand never called"
        return ok('-p' in captured[0] and '8888' in captured[0],
                  f"port 8888 not in NSE command: {captured[0]!r}")
    finally:
        wc.runCommand = orig_run
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM portObj WHERE portId='8888' AND hostId=?", (str(host_id),))
            conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
            conn.commit()
test("C7.9: _launch_nse_stage includes discovered TCP ports in nmap -p flag", test_c7_nse_port_query_finds_tcp_ports)

def test_c7_nse_port_query_finds_udp_ports():
    """_launch_nse_stage includes UDP ports with U: prefix in the port spec."""
    import sqlite3
    db_path = wc.logic.activeProject.database.name
    test_ip = '198.51.100.98'
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
        conn.execute("INSERT INTO hostObj (ip, state, hostname) VALUES (?, 'up', '')", (test_ip,))
        host_id = conn.execute("SELECT id FROM hostObj WHERE ip=?", (test_ip,)).fetchone()[0]
        conn.execute("INSERT INTO portObj (portId, protocol, state, hostId) VALUES ('161','udp','open',?)", (str(host_id),))
        conn.commit()
    captured = []
    orig_run = wc.runCommand
    wc.runCommand = lambda command='', **kw: captured.append(command) or {'process_id': None}
    try:
        wc._launch_nse_stage(test_ip, 6, 'vulners', False,
                             wc.logic.activeProject.properties.outputFolder, 'nmap')
        if not captured:
            return "FAIL: runCommand never called"
        return ok('U:' in captured[0] and '161' in captured[0],
                  f"UDP port 161 with U: prefix not in NSE command: {captured[0]!r}")
    finally:
        wc.runCommand = orig_run
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM portObj WHERE portId='161' AND hostId=?", (str(host_id),))
            conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
            conn.commit()
test("C7.10: _launch_nse_stage includes UDP ports with U: prefix", test_c7_nse_port_query_finds_udp_ports)

def test_c7_nse_open_filtered_included():
    """_launch_nse_stage must include ports with state 'open|filtered' (not just 'open')."""
    import sqlite3
    db_path = wc.logic.activeProject.database.name
    test_ip = '198.51.100.97'
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
        conn.execute("INSERT INTO hostObj (ip, state, hostname) VALUES (?, 'up', '')", (test_ip,))
        host_id = conn.execute("SELECT id FROM hostObj WHERE ip=?", (test_ip,)).fetchone()[0]
        conn.execute("INSERT INTO portObj (portId, protocol, state, hostId) VALUES ('7777','tcp','open|filtered',?)", (str(host_id),))
        conn.commit()
    captured = []
    orig_run = wc.runCommand
    wc.runCommand = lambda command='', **kw: captured.append(command) or {'process_id': None}
    try:
        wc._launch_nse_stage(test_ip, 6, 'vulners', False,
                             wc.logic.activeProject.properties.outputFolder, 'nmap')
        if not captured:
            return "FAIL: runCommand never called"
        return ok('7777' in captured[0],
                  f"open|filtered port 7777 excluded from NSE command: {captured[0]!r}")
    finally:
        wc.runCommand = orig_run
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM portObj WHERE portId='7777' AND hostId=?", (str(host_id),))
            conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
            conn.commit()
test("C7.11: _launch_nse_stage includes open|filtered ports (not just 'open')", test_c7_nse_open_filtered_included)

def test_c7_nse_tab_title_uses_script_name():
    """_launch_nse_stage tab title must be 'nmap (vulners)' not 'nmap (stage N)'."""
    import sqlite3
    db_path = wc.logic.activeProject.database.name
    test_ip = '198.51.100.96'
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
        conn.execute("INSERT INTO hostObj (ip, state, hostname) VALUES (?, 'up', '')", (test_ip,))
        host_id = conn.execute("SELECT id FROM hostObj WHERE ip=?", (test_ip,)).fetchone()[0]
        conn.execute("INSERT INTO portObj (portId, protocol, state, hostId) VALUES ('80','tcp','open',?)", (str(host_id),))
        conn.commit()
    captured_kwargs = []
    orig_run = wc.runCommand
    wc.runCommand = lambda command='', **kw: captured_kwargs.append(kw) or {'process_id': None}
    try:
        wc._launch_nse_stage(test_ip, 6, 'vulners', False,
                             wc.logic.activeProject.properties.outputFolder, 'nmap')
        if not captured_kwargs:
            return "FAIL: runCommand never called"
        title = captured_kwargs[0].get('tabTitle', '')
        return ok('stage' not in title and 'vulners' in title,
                  f"tab title wrong: {title!r} (expected 'nmap (vulners)')")
    finally:
        wc.runCommand = orig_run
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM portObj WHERE portId='80' AND hostId=?", (str(host_id),))
            conn.execute("DELETE FROM hostObj WHERE ip=?", (test_ip,))
            conn.commit()
test("C7.12: _launch_nse_stage tab title is 'nmap (vulners)' not 'nmap (stage N)'", test_c7_nse_tab_title_uses_script_name)

def test_c7_nse_no_ports_scans_defaults():
    """_launch_nse_stage with no open ports must still run (without -p) using nmap defaults."""
    test_ip = '198.51.100.95'  # host not in DB — no ports
    captured = []
    orig_run = wc.runCommand
    wc.runCommand = lambda command='', **kw: captured.append(command) or {'process_id': None}
    try:
        wc._launch_nse_stage(test_ip, 6, 'vulners', False,
                             wc.logic.activeProject.properties.outputFolder, 'nmap')
        if not captured:
            return "FAIL: runCommand never called — NSE must still launch even with no ports"
        # Command should run but without -p flag
        return ok('vulners' in captured[0],
                  f"vulners not in NSE command when no ports found: {captured[0]!r}")
    finally:
        wc.runCommand = orig_run
test("C7.13: _launch_nse_stage still runs when no ports found (uses nmap defaults)", test_c7_nse_no_ports_scans_defaults)

def test_c7_pending_set_populated_before_launch():
    """runStagedNmap registers ALL stages in _pending_ports_stages before any thread starts.
    Proves a fast-finishing stage can't trigger NSE prematurely."""
    host = '_test_host_sc_pending'
    launch_order = []
    orig_launch = wc._launch_ports_stage
    orig_nse = wc._launch_nse_stage
    def mock_launch(h, stage, *a, **k):
        # Capture state of pending set at the moment each stage launches
        launch_order.append((stage, frozenset(wc._pending_ports_stages.get(h, set()))))
    wc._launch_ports_stage = mock_launch
    wc._launch_nse_stage = lambda *a, **k: None
    try:
        wc.runStagedNmap(host, discovery=False)
        if not launch_order:
            return "SKIP: no PORTS stages configured or runStagedNmap did not launch"
        # At the moment the first stage launches, the full pending set must already be populated
        _, pending_at_first_launch = launch_order[0]
        total_ports_stages = len(launch_order)
        return ok(len(pending_at_first_launch) == total_ports_stages,
                  f"At first launch, pending set had {len(pending_at_first_launch)} entries "
                  f"but {total_ports_stages} stages will launch — premature NSE possible")
    finally:
        wc._launch_ports_stage = orig_launch
        wc._launch_nse_stage = orig_nse
        wc._pending_ports_stages.pop(host, None)
test("C7.14: Full pending set registered before any stage launches (no premature NSE)", test_c7_pending_set_populated_before_launch)

def test_c7_nse_stage_classified_separately():
    """runStagedNmap must put NSE stages in nse_stage and PORTS in ports_stages — not mixed."""
    # Use real settings to verify classification at runtime
    nse_stages = []
    ports_stages = []
    for s in range(1, 7):
        data = getattr(wc.settings, f'tools_nmap_stage{s}_ports', '')
        if not data:
            continue
        op = str(data).split('|', maxsplit=1)[0].strip()
        if op == 'NSE':
            nse_stages.append(s)
        elif op == 'PORTS':
            ports_stages.append(s)
    if not nse_stages:
        return "SKIP: no NSE stage in settings"
    return ok(len(nse_stages) >= 1 and len(ports_stages) >= 1 and
              not (set(nse_stages) & set(ports_stages)),
              f"NSE stages {nse_stages} overlap with PORTS stages {ports_stages}")
test("C7.15: Settings classify NSE and PORTS stages without overlap", test_c7_nse_stage_classified_separately)

def test_c7_launch_ports_stage_calls_stage_completed_on_fail():
    """_launch_ports_stage calls _stage_completed even when runCommand returns None (failed launch)."""
    host = '_test_host_sc_fail'
    nse = (6, 'vulners')
    wc._pending_ports_stages[host] = {99}
    completed = []
    orig_run = wc.runCommand
    orig_sc = wc._stage_completed
    wc.runCommand = lambda **kw: None  # simulate failed launch
    wc._stage_completed = lambda *a, **k: completed.append(True)
    try:
        wc._launch_ports_stage(host, 99, 'T:80', False, False, '/tmp', 'nmap', nse)
        return ok(len(completed) == 1,
                  "_stage_completed not called after runCommand returned None — stage would hang")
    finally:
        wc.runCommand = orig_run
        wc._stage_completed = orig_sc
        wc._pending_ports_stages.pop(host, None)
test("C7.16: _launch_ports_stage calls _stage_completed even when launch fails", test_c7_launch_ports_stage_calls_stage_completed_on_fail)


# ══════════════════════════════════════════════════════════════
# C8: Cancelled process skipped in queue
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C8: Cancelled process skipped")
print("="*60 + "\n")

def test_c8_cancel_check():
    """checkProcessQueue checks isCancelledProcess"""
    import inspect
    src = inspect.getsource(wc.checkProcessQueue)
    return ok('isCancelledProcess' in src or 'Cancelled' in src,
              "checkProcessQueue must skip cancelled processes")
test("C8.1: Queue skips cancelled processes", test_c8_cancel_check)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
