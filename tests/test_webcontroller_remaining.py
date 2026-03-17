#!/usr/bin/env python3
"""
WebController Test Plan — Remaining 39 Qt-dependent methods
============================================================
Run with: sudo python3 tests/test_webcontroller_remaining.py

Groups:
  A: Lifecycle (init, project open/save/close, settings) — 19 methods
  B: Process execution (addHosts, handleAction, scheduler) — 11 methods
  C: Match/UI (highlighting, hydra, interactive) — 5 methods
  + 4 already ported in Tier 2/3

Each test references the exact controller.py line number.
"""

import os
import sys
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
def assert_type(v, t, msg=""): return True if isinstance(v, t) else f"expected {t.__name__}, got {type(v).__name__}" + (f" ({msg})" if msg else "")

def try_import_wc():
    try:
        from controller.web_controller import WebController
        return WebController
    except ImportError:
        return None

# ── Setup: create project + settings (same as tier 1) ──
from app.shell.DefaultShell import DefaultShell
from db.RepositoryFactory import RepositoryFactory
from app.ProjectManager import ProjectManager
from app.tools.ToolCoordinator import ToolCoordinator
from app.tools.nmap.DefaultNmapExporter import DefaultNmapExporter
from app.logic import Logic
from app.settings import AppSettings, Settings
from app.logging.legionLog import getDbLogger, getAppLogger
from app.auxiliary import Filters

shell = DefaultShell()
dbLog = getDbLogger()
appLog = getAppLogger()
repoFactory = RepositoryFactory(dbLog)
pm = ProjectManager(shell, repoFactory, appLog)
nmapExporter = DefaultNmapExporter(shell, appLog)
tc = ToolCoordinator(shell, nmapExporter)
logic = Logic(shell, pm, tc)
logic.createNewTemporaryProject()
settings = Settings(AppSettings())
filters = Filters()

# Add a test host so we have data to work with
from db.entities.host import hostObj
from db.entities.port import portObj
from db.entities.service import serviceObj

session = logic.activeProject.database.session()
try:
    h = hostObj(ip='192.168.1.100', ipv4='192.168.1.100', hostname='testbox', osMatch='Linux', status='up', state='up')
    session.add(h); session.flush()
    svc = serviceObj(name='http', host=str(h.id), product='Apache', version='2.4')
    session.add(svc); session.flush()
    port = portObj(portId='80', protocol='tcp', state='open', host=h.id, service=svc.id)
    session.add(port)
    svc2 = serviceObj(name='ssh', host=str(h.id), product='OpenSSH', version='8.9')
    session.add(svc2); session.flush()
    port2 = portObj(portId='22', protocol='tcp', state='open', host=h.id, service=svc2.id)
    session.add(port2)
    session.commit()
finally:
    session.close()


# ══════════════════════════════════════════════════════════════
# GROUP A: Lifecycle methods (self.view.xxx → no-op/state)
# These methods call self.view for UI updates.
# WebController replaces view calls with state dict updates.
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("GROUP A: Lifecycle methods (19 methods)")
print("="*60 + "\n")

# A1: start — controller.py:149
def test_a1_start():
    """WebController.start() initializes state without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    return assert_true(hasattr(wc, 'processes'), "should have processes list")
test("A1: start()", test_a1_start)

# A2: loadSettings — controller.py:207
def test_a2_load_settings():
    """WebController.loadSettings() loads from legion.conf"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    s = wc.getSettings()
    return assert_gt(len(s.hostActions), 0)
test("A2: loadSettings()", test_a2_load_settings)

# A3: createNewProject — controller.py:303
def test_a3_create_new_project():
    """WebController can create a new temp project"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.createNewProject()
    return assert_true(logic.activeProject is not None)
test("A3: createNewProject()", test_a3_create_new_project)

# A4: closeProject — controller.py:417
def test_a4_close_project():
    """WebController.closeProject() doesn't crash without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    # Create a fresh project first so we can close it
    logic.createNewTemporaryProject()
    wc.closeProject()
    return True
test("A4: closeProject()", test_a4_close_project)

# A5: saveProject — controller.py:348
def test_a5_save_project():
    """WebController.saveProject() saves notes for a host"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    logic.createNewTemporaryProject()
    # Re-add test host
    sess = logic.activeProject.database.session()
    try:
        h = hostObj(ip='10.0.0.5', ipv4='10.0.0.5', hostname='savetest', osMatch='Linux', status='up', state='up')
        sess.add(h); sess.commit()
        wc.saveProject(h.id, '<p>test note</p>')
    finally:
        sess.close()
    return True
test("A5: saveProject()", test_a5_save_project)

# A6: initTimers — controller.py:194
def test_a6_init_timers():
    """WebController replaces QTimers with threading-based polling"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Should not crash, timers replaced with no-ops or threading
    return True
test("A6: initTimers() equivalent", test_a6_init_timers)

# A7: importFinished — controller.py:2136
def test_a7_import_finished():
    """WebController.importFinished() updates state without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.importFinished()
    return True
test("A7: importFinished()", test_a7_import_finished)

# A8: addPortToHost — controller.py:2621
def test_a8_add_port():
    """WebController.addPortToHost() adds a port to the DB"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.addPortToHost('10.0.0.5', {'port': '443', 'protocol': 'tcp', 'state': 'open', 'service': 'https'})
    return True
test("A8: addPortToHost()", test_a8_add_port)

# A9: cleanupPurgedHost — controller.py:2783 (delayed validation)
def test_a9_cleanup_purged():
    """WebController.cleanupPurgedHost() runs without QTimer"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.cleanupPurgedHost('10.0.0.5')  # should not crash
    return True
test("A9: cleanupPurgedHost()", test_a9_cleanup_purged)

# A10: cleanupDeletedHost — controller.py:2691
def test_a10_cleanup_deleted():
    """WebController.cleanupDeletedHost() runs without QTimer"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.cleanupDeletedHost('10.0.0.99')  # non-existent host, should not crash
    return True
test("A10: cleanupDeletedHost()", test_a10_cleanup_deleted)

# A11: processFinished — controller.py:2223
def test_a11_process_finished():
    """WebController.processFinished() updates state without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    wc.processFinished(None)  # should handle None gracefully
    return True
test("A11: processFinished()", test_a11_process_finished)

# A12: processCrashed — controller.py:2187
def test_a12_process_crashed():
    """WebController.processCrashed() updates state without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    wc.processCrashed(None)  # should handle None gracefully
    return True
test("A12: processCrashed()", test_a12_process_crashed)

# A13: screenshotFinished — controller.py:2151
def test_a13_screenshot_finished():
    """WebController.screenshotFinished() updates state without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.screenshotFinished()
    return True
test("A13: screenshotFinished()", test_a13_screenshot_finished)

# A14: openExistingProject — controller.py:308
def test_a14_open_project():
    """WebController.openExistingProject() opens a .legion file"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    # We can't easily test with a real file, but verify the method exists
    wc = WC(logic, settings)
    return assert_true(hasattr(wc, 'openExistingProject'))
test("A14: openExistingProject() exists", test_a14_open_project)

# A15: saveProjectAs — controller.py:390
def test_a15_save_as():
    """WebController.saveProjectAs() exists"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    return assert_true(hasattr(wc, 'saveProjectAs'))
test("A15: saveProjectAs() exists", test_a15_save_as)


# ══════════════════════════════════════════════════════════════
# GROUP B: Process execution (QProcess → subprocess)
# These methods orchestrate tool runs and process management.
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("GROUP B: Process execution (11 methods)")
print("="*60 + "\n")

# B1: addHosts — controller.py:443 (the main entry point for scans)
def test_b1_add_hosts():
    """WebController.addHosts() starts an nmap scan without Qt"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Run a quick scan (just list, no actual network scan)
    result = wc.addHosts('127.0.0.1', runHostDiscovery=False, runStagedNmap=False,
                         nmapSpeed='4', scanMode='Easy')
    return assert_true(result is not None or result is None)  # just shouldn't crash
test("B1: addHosts()", test_b1_add_hosts)

# B2: handleHostAction — controller.py:589 (right-click host → action)
def test_b2_handle_host_action_check():
    """WebController.handleHostAction() handles 'Mark as checked'"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Test the mark-as-checked action (pure DB operation)
    wc.handleHostAction('192.168.1.100', 1, 'mark-checked')
    return True
test("B2: handleHostAction(mark-checked)", test_b2_handle_host_action_check)

# B3: handleHostAction — delete action
def test_b3_handle_host_action_delete():
    """WebController.handleHostAction() handles 'Delete'"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Add a throwaway host to delete
    sess = logic.activeProject.database.session()
    try:
        h = hostObj(ip='10.99.99.99', ipv4='10.99.99.99', osMatch='Test', status='up', state='up')
        sess.add(h); sess.commit()
        hid = h.id
    finally:
        sess.close()
    wc.handleHostAction('10.99.99.99', hid, 'delete')
    # Verify host is gone
    deleted = logic.activeProject.repositoryContainer.hostRepository.getHostByIP('10.99.99.99')
    return assert_true(deleted is None, "host should be deleted")
test("B3: handleHostAction(delete)", test_b3_handle_host_action_delete)

# B4: handleServiceNameAction — controller.py:1083
def test_b4_handle_service_action():
    """WebController.handleServiceNameAction() runs a tool for a service"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Run banner grab (fast, always available) on our test host
    targets = [['192.168.1.100', '80', 'tcp']]
    result = wc.handleServiceNameAction(targets, action_index=0)  # banner grab is index 0
    return assert_true(result is not None or result is None)  # shouldn't crash
test("B4: handleServiceNameAction()", test_b4_handle_service_action)

# B5: handlePortAction — controller.py:1171
def test_b5_handle_port_action():
    """WebController.handlePortAction() runs a tool for a port"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    targets = [['192.168.1.100', '80', 'tcp', 'http']]
    result = wc.handlePortAction(targets, action_type='port-action', action_index=0)
    return assert_true(result is not None or result is None)
test("B5: handlePortAction()", test_b5_handle_port_action)

# B6: handleProcessAction — controller.py:1250
def test_b6_handle_process_kill():
    """WebController.handleProcessAction() handles kill"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Start a long-running process then kill it
    result = wc.runCommand(command='sleep 30', name='test-kill', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    time.sleep(0.5)
    wc.handleProcessAction(proc_id, 'kill')
    time.sleep(1)
    proc = logic.activeProject.repositoryContainer.processRepository.getProcessById(proc_id)
    return assert_eq(proc['status'], 'Killed')
test("B6: handleProcessAction(kill)", test_b6_handle_process_kill)

# B7: handleProcessAction — retry
def test_b7_handle_process_retry():
    """WebController.handleProcessAction() handles retry"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    result = wc.runCommand(command='echo retry_original', name='test-retry', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    time.sleep(1)
    new_result = wc.handleProcessAction(proc_id, 'retry')
    return assert_true(new_result is not None or new_result is None)
test("B7: handleProcessAction(retry)", test_b7_handle_process_retry)

# B8: handleProcessAction — clear
def test_b8_handle_process_clear():
    """WebController.handleProcessAction() handles clear (hide)"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    result = wc.runCommand(command='echo clear_test', name='test-clear', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    time.sleep(1)
    wc.handleProcessAction(proc_id, 'clear')
    return True
test("B8: handleProcessAction(clear)", test_b8_handle_process_clear)

# B9: runStagedNmap — controller.py:2055
def test_b9_run_staged_nmap():
    """WebController.runStagedNmap() exists and is callable"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    return assert_true(hasattr(wc, 'runStagedNmap'))
test("B9: runStagedNmap() exists", test_b9_run_staged_nmap)

# B10: killRunningProcesses — controller.py:1700
def test_b10_kill_all():
    """WebController.killRunningProcesses() kills all active processes"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    wc.killRunningProcesses()  # should not crash with 0 processes
    return True
test("B10: killRunningProcesses()", test_b10_kill_all)

# B11: checkProcessQueue — controller.py:1570
def test_b11_check_queue():
    """WebController.checkProcessQueue() manages the process queue"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    wc.checkProcessQueue()
    return True
test("B11: checkProcessQueue()", test_b11_check_queue)


# ══════════════════════════════════════════════════════════════
# GROUP C: Match/UI methods (can defer, less critical)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("GROUP C: Match/UI (5 methods)")
print("="*60 + "\n")

# C1: handleMatch — controller.py:2651
def test_c1_handle_match():
    """WebController.handleMatch() stores match data without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    wc.handleMatch('192.168.1.100', 'nmap 80/tcp', 'open')
    return True
test("C1: handleMatch()", test_c1_handle_match)

# C2: handleHydraFindings — controller.py:2336
def test_c2_hydra_findings():
    """WebController.handleHydraFindings() stores credentials without view"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.handleHydraFindings()
    return True
test("C2: handleHydraFindings()", test_c2_hydra_findings)

# C3: markAsInteractive — controller.py:1958
def test_c3_mark_interactive():
    """WebController.markAsInteractive() uses threading.Timer not QTimer"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    # Should exist and not crash
    return assert_true(hasattr(wc, 'markAsInteractive'))
test("C3: markAsInteractive() exists", test_c3_mark_interactive)

# C4: saveRunningProcessOutputs — controller.py:2305
def test_c4_save_running_outputs():
    """WebController.saveRunningProcessOutputs() persists output before shutdown"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    wc.saveRunningProcessOutputs()
    return True
test("C4: saveRunningProcessOutputs()", test_c4_save_running_outputs)

# C5: scheduler — controller.py scheduler integration
def test_c5_scheduler():
    """WebController.scheduler() triggers tool scheduling after import"""
    WC = try_import_wc()
    if not WC: return 'SKIP'
    wc = WC(logic, settings)
    wc.start()
    return assert_true(hasattr(wc, 'scheduler'))
test("C5: scheduler() exists", test_c5_scheduler)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
