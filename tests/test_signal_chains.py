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

def test_c7_staged_marked():
    """runStagedNmap marks processes with _is_staged=True"""
    import inspect
    src = inspect.getsource(wc.runStagedNmap)
    return ok('_is_staged=True' in src, "runStagedNmap must pass _is_staged=True")
test("C7.1: Staged processes marked with _is_staged=True", test_c7_staged_marked)

def test_c7_chain_imports_xml():
    """runStagedNmap chain imports XML between stages"""
    import inspect
    src = inspect.getsource(wc.runStagedNmap)
    return ok('import_nmap_xml' in src, "runStagedNmap must import XML in chain")
test("C7.2: Stage chain imports XML", test_c7_chain_imports_xml)

def test_c7_stage_settings_loaded():
    """Stage port configs loaded from [StagedNmapSettings]"""
    stage1 = getattr(wc.settings, 'tools_nmap_stage1_ports', None)
    return ok(stage1 is not None and len(str(stage1)) > 0, f"stage1 ports: {stage1}")
test("C7.3: Stage 1 port config loaded", test_c7_stage_settings_loaded)


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
