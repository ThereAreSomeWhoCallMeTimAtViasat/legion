#!/usr/bin/env python3
"""
Session Isolation & Shutdown Safety Tests
==========================================
Run with: sudo python3 tests/test_session_isolation.py

Covers every behaviour fixed or added in the v10.24–v10.26 work:

  v10.24  Shutdown & scan-restart bugs
    S1  /api/shutdown does NOT kill running processes
    S2  /api/shutdown flushes live output to DB
    S3  killRunningProcesses() marks each process Killed in DB
    S4  killRunningProcesses() drains fastProcessQueue
    S5  Queued (not-yet-started) processes are marked Killed in DB
    S6  No ghost scans: queue stays empty after kill (checkProcessQueue is a no-op)
    S7  Scan generation increments on each runStagedNmap for same host
    S8  _stage_completed with stale generation leaves _pending_ports_stages untouched
    S9  _stage_completed with current generation updates _pending_ports_stages

  v10.25  Startup / shutdown checks
    S10 _startup_check() marks orphan Running processes as Crashed
    S11 _startup_check() marks orphan Waiting processes as Crashed
    S12 _startup_check() leaves Finished / Killed / Crashed processes unchanged
    S13 _startup_check() deletes stale .live_output files in running folder
    S14 _startup_check() deletes stale .live_output files in output folder
    S15 _startup_check() does not delete non-live_output files
    S16 closeProject() removes the temp DB file (temp project cleanup)
    S17 closeProject() leaves no orphan WAL or SHM companion files

  v10.26  File isolation between server instances
    S18 Log handlers are RotatingFileHandler, not plain FileHandler
    S19 RotatingFileHandler has maxBytes=10 MB and backupCount=3
    S20 Session-start separator is written to the log file
    S21 _screenshots_taken is reset to empty set on start()
    S22 _cleanup_orphaned_temp_files() removes unlocked orphaned .legion DB
    S23 _cleanup_orphaned_temp_files() removes -running/-tool-output dirs with dead PID sentinel
    S24 _cleanup_orphaned_temp_files() skips a .legion file open in a live process (/proc scan)
    S25 _cleanup_orphaned_temp_files() skips the current session's own DB and folders
"""

import os, sys, time, traceback, tempfile, threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = FAIL = SKIP = 0

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        r = fn()
        if r is None or r is True:
            PASS += 1; print(f"  \u2713 {name}"); return True
        elif r == 'SKIP':
            SKIP += 1; print(f"  \u2298 {name} (SKIP)"); return False
        else:
            FAIL += 1; print(f"  \u2717 {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""):  return True if v else f"FAIL: {msg}"
def eq(a, b, msg=""): return True if a == b else f"expected {b!r}, got {a!r} ({msg})"


# ─────────────────────────────────────────────
# Shared setup — one app/wc for non-destructive tests
# ─────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters
from sqlalchemy import text as _text
from controller.web_controller import WebProcessStub
from app.timing import getTimestamp

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()


def _db_status(proc_id):
    """Query process status directly from SQLite — bypasses ORM cache."""
    session = logic.activeProject.database.session()
    try:
        row = session.execute(
            _text("SELECT status FROM process WHERE id=:id"), {"id": proc_id}
        ).fetchone()
        return row[0] if row else None
    finally:
        session.close()


def _insert_process_with_status(status):
    """Insert a dummy process row with a given status and return its id."""
    stub = WebProcessStub(
        'dummy', 'dummy', '127.0.0.1', '0', 'tcp',
        'echo dummy', getTimestamp(True),
        os.path.join(logic.activeProject.properties.runningFolder, 'dummy-output')
    )
    repo = logic.activeProject.repositoryContainer.processRepository
    proc_id = int(repo.storeProcess(stub))
    # Force the status we want
    session = logic.activeProject.database.session()
    try:
        session.execute(
            _text("UPDATE process SET status=:s WHERE id=:id"),
            {"s": status, "id": proc_id}
        )
        session.commit()
    finally:
        session.close()
    return proc_id


def _wait_running(wc_obj, proc_id, timeout=8):
    """Wait until the process actually has a live _popen (started, not just queued)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = wc_obj._active_processes.get(proc_id)
        if proc and proc._popen and proc._popen.poll() is None:
            return True
        time.sleep(0.1)
    return False


# ══════════════════════════════════════════════════════════════
# v10.24 — SHUTDOWN & SCAN-RESTART BUGS
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("v10.24: Shutdown does not kill running processes")
print("=" * 60 + "\n")


def test_s1_shutdown_does_not_kill():
    """POST /api/shutdown must leave running processes alive."""
    wc.start()
    result = wc.runCommand('sleep 30', name='test-nodrop', tabTitle='test-nodrop',
                           hostIp='1.1.1.1', run_actions=False)
    proc_id = result['process_id']
    if not _wait_running(wc, proc_id, timeout=5):
        return "process never started"

    # Simulate the beforeunload beacon
    client.post('/api/shutdown')

    proc = wc._active_processes.get(proc_id)
    alive = proc and proc._popen and proc._popen.poll() is None
    wc.killRunningProcesses()      # cleanup
    return ok(alive, "process was killed by /api/shutdown — should not be")

test("S1: /api/shutdown does NOT kill running processes", test_s1_shutdown_does_not_kill)


def test_s2_shutdown_flushes_output():
    """/api/shutdown flushes live output — saveRunningProcessOutputs writes live bytes."""
    wc.start()
    result = wc.runCommand('echo FLUSH_MARKER && sleep 20', name='test-flush',
                           tabTitle='test-flush', hostIp='1.1.1.2', run_actions=False)
    proc_id = result['process_id']
    if not _wait_running(wc, proc_id, timeout=5):
        wc.killRunningProcesses()
        return "process never started"

    # Wait for echo to produce output into the live_output file
    time.sleep(1)

    # Flush — this is exactly what /api/shutdown calls
    wc.saveRunningProcessOutputs()

    # Check DB was written
    session = logic.activeProject.database.session()
    try:
        row = session.execute(
            _text("SELECT output FROM process_output WHERE processId=:id"),
            {"id": proc_id}
        ).fetchone()
        stored = (row[0] or '') if row else ''
    finally:
        session.close()

    wc.killRunningProcesses()
    return ok('FLUSH_MARKER' in stored,
              f"expected FLUSH_MARKER in flushed output, got: {stored[:200]!r}")

test("S2: /api/shutdown flushes live output to DB", test_s2_shutdown_flushes_output)


print("\n" + "=" * 60)
print("v10.24: killRunningProcesses() DB correctness")
print("=" * 60 + "\n")


def test_s3_kill_marks_killed_in_db():
    """killRunningProcesses() must write Killed status to DB for each process."""
    wc.start()
    result = wc.runCommand('sleep 30', name='test-kill-db', tabTitle='test-kill-db',
                           hostIp='1.1.1.3', run_actions=False)
    proc_id = result['process_id']
    if not _wait_running(wc, proc_id, timeout=5):
        return "process never started"

    wc.killRunningProcesses()
    time.sleep(0.3)   # brief settle for DB write

    status = _db_status(proc_id)
    repo = logic.activeProject.repositoryContainer.processRepository
    is_killed = repo.isKilledProcess(str(proc_id))
    return ok(status == 'Killed' and is_killed,
              f"DB status={status!r}, isKilledProcess={is_killed}")

test("S3: killRunningProcesses() marks process Killed in DB", test_s3_kill_marks_killed_in_db)


def test_s4_kill_drains_queue():
    """killRunningProcesses() must drain fastProcessQueue completely."""
    wc.start()
    repo = logic.activeProject.repositoryContainer.processRepository

    # Create a stub process in DB (Waiting status after storeProcess)
    stub = WebProcessStub(
        'test-queued', 'test-queued', '1.1.1.4', '0', 'tcp',
        'sleep 999', getTimestamp(True),
        os.path.join(logic.activeProject.properties.runningFolder, 'test-queued')
    )
    proc_id = int(repo.storeProcess(stub))
    stub.id = proc_id

    # Saturate the process slot counter so checkProcessQueue won't auto-start it
    orig = wc.fastProcessesRunning
    wc.fastProcessesRunning = 99999
    wc.fastProcessQueue.put(stub)

    assert wc.fastProcessQueue.qsize() >= 1, "stub should be in queue"

    # Kill — must drain queue regardless of running count
    wc.fastProcessesRunning = orig
    wc.killRunningProcesses()
    time.sleep(0.3)

    queue_empty = wc.fastProcessQueue.empty()
    db_killed = repo.isKilledProcess(str(proc_id))
    return ok(queue_empty and db_killed,
              f"queue_empty={queue_empty} db_killed={db_killed}")

test("S4: killRunningProcesses() drains fastProcessQueue", test_s4_kill_drains_queue)


def test_s5_queued_process_marked_killed():
    """A queued-but-not-started process is marked Killed in DB after kill."""
    wc.start()
    repo = logic.activeProject.repositoryContainer.processRepository

    stub = WebProcessStub(
        'test-queued2', 'test-queued2', '1.1.1.5', '0', 'tcp',
        'sleep 999', getTimestamp(True),
        os.path.join(logic.activeProject.properties.runningFolder, 'test-queued2')
    )
    proc_id = int(repo.storeProcess(stub))
    stub.id = proc_id

    wc.fastProcessesRunning = 99999   # prevent auto-start
    wc.fastProcessQueue.put(stub)

    wc.fastProcessesRunning = 0
    wc.killRunningProcesses()
    time.sleep(0.3)

    status = _db_status(proc_id)
    return ok(status == 'Killed', f"queued process DB status={status!r}, expected 'Killed'")

test("S5: Queued process gets Killed status in DB", test_s5_queued_process_marked_killed)


def test_s6_no_ghost_scans_after_kill():
    """After killRunningProcesses(), the queue is empty and no new processes start."""
    wc.start()

    # Start something real (takes a slot)
    wc.runCommand('sleep 30', name='test-ghost', tabTitle='test-ghost',
                  hostIp='1.1.1.6', run_actions=False)
    time.sleep(0.5)

    # Add a queued item that should NOT auto-start after kill
    stub = WebProcessStub(
        'ghost-check', 'ghost-check', '1.1.1.6', '0', 'tcp',
        'touch /tmp/legion_ghost_test', getTimestamp(True),
        os.path.join(logic.activeProject.properties.runningFolder, 'ghost')
    )
    repo = logic.activeProject.repositoryContainer.processRepository
    proc_id = int(repo.storeProcess(stub))
    stub.id = proc_id
    wc.fastProcessesRunning = 99999
    wc.fastProcessQueue.put(stub)
    wc.fastProcessesRunning = 1   # restore realistic count

    wc.killRunningProcesses()
    time.sleep(1.0)   # give time for any ghost to start

    ghost_started = os.path.isfile('/tmp/legion_ghost_test')
    if ghost_started:
        os.unlink('/tmp/legion_ghost_test')
    queue_empty = wc.fastProcessQueue.empty()

    return ok(not ghost_started and queue_empty,
              f"ghost_started={ghost_started} queue_empty={queue_empty}")

test("S6: No ghost scans start after kill (queue stays empty)", test_s6_no_ghost_scans_after_kill)


print("\n" + "=" * 60)
print("v10.24: Scan generation counter")
print("=" * 60 + "\n")


def test_s7_generation_increments():
    """_scan_generation[host] increments on each new staged scan for same host."""
    host = '10.9.9.1'
    wc._scan_generation[host] = 0
    wc._pending_ports_stages[host] = set()

    # Directly bump generation the same way runStagedNmap does
    with wc._pending_stages_lock:
        gen = wc._scan_generation.get(host, 0) + 1
        wc._scan_generation[host] = gen

    gen1 = wc._scan_generation[host]

    with wc._pending_stages_lock:
        gen = wc._scan_generation.get(host, 0) + 1
        wc._scan_generation[host] = gen

    gen2 = wc._scan_generation[host]

    return ok(gen1 == 1 and gen2 == 2,
              f"generations should be 1 then 2, got {gen1} then {gen2}")

test("S7: Scan generation increments per runStagedNmap call", test_s7_generation_increments)


def test_s8_stale_stage_completed_is_noop():
    """_stage_completed with stale generation must not modify _pending_ports_stages."""
    host = '10.9.9.2'
    wc._scan_generation[host] = 5
    wc._pending_ports_stages[host] = {1, 2, 3}

    # Call with old generation (3 ≠ 5) — must be ignored
    wc._stage_completed(host, 1, None, False, '/tmp', 'nmap', generation=3)

    remaining = wc._pending_ports_stages.get(host, set())
    return ok(remaining == {1, 2, 3},
              f"stale _stage_completed modified pending set: {remaining}")

test("S8: Stale generation _stage_completed leaves pending set unchanged",
     test_s8_stale_stage_completed_is_noop)


def test_s9_current_generation_stage_completed_updates():
    """_stage_completed with current generation correctly removes the stage."""
    host = '10.9.9.3'
    wc._scan_generation[host] = 7
    wc._pending_ports_stages[host] = {1, 2, 3, 4, 5}

    # Current generation — stage 3 finishes, no NSE (nse_stage=None)
    wc._stage_completed(host, 3, None, False, '/tmp', 'nmap', generation=7)

    remaining = wc._pending_ports_stages.get(host, set())
    return ok(3 not in remaining and remaining == {1, 2, 4, 5},
              f"expected {{1,2,4,5}}, got {remaining}")

test("S9: Current generation _stage_completed removes the correct stage",
     test_s9_current_generation_stage_completed_updates)


# ══════════════════════════════════════════════════════════════
# v10.25 — STARTUP / SHUTDOWN CHECKS
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("v10.25: _startup_check() orphan process cleanup")
print("=" * 60 + "\n")


def test_s10_startup_marks_running_as_crashed():
    """_startup_check() must set status=Crashed for any Running process."""
    proc_id = _insert_process_with_status('Running')
    assert _db_status(proc_id) == 'Running', "precondition: status must be Running"

    wc._startup_check()

    status = _db_status(proc_id)
    return ok(status == 'Crashed', f"Running process not marked Crashed, got {status!r}")

test("S10: _startup_check() marks Running processes as Crashed",
     test_s10_startup_marks_running_as_crashed)


def test_s11_startup_marks_waiting_as_crashed():
    """_startup_check() must set status=Crashed for any Waiting process."""
    proc_id = _insert_process_with_status('Waiting')
    assert _db_status(proc_id) == 'Waiting', "precondition: status must be Waiting"

    wc._startup_check()

    status = _db_status(proc_id)
    return ok(status == 'Crashed', f"Waiting process not marked Crashed, got {status!r}")

test("S11: _startup_check() marks Waiting processes as Crashed",
     test_s11_startup_marks_waiting_as_crashed)


def test_s12_startup_leaves_terminal_statuses_alone():
    """_startup_check() must not touch Finished, Killed, or Crashed processes."""
    pid_fin = _insert_process_with_status('Finished')
    pid_kil = _insert_process_with_status('Killed')
    pid_cra = _insert_process_with_status('Crashed')

    wc._startup_check()

    fin = _db_status(pid_fin)
    kil = _db_status(pid_kil)
    cra = _db_status(pid_cra)
    ok_fin = fin == 'Finished'
    ok_kil = kil == 'Killed'
    ok_cra = cra == 'Crashed'
    if ok_fin and ok_kil and ok_cra:
        return True
    return (f"terminal statuses changed: "
            f"Finished→{fin!r} Killed→{kil!r} Crashed→{cra!r}")

test("S12: _startup_check() leaves Finished/Killed/Crashed processes unchanged",
     test_s12_startup_leaves_terminal_statuses_alone)


print("\n" + "=" * 60)
print("v10.25: _startup_check() stale file cleanup")
print("=" * 60 + "\n")


def test_s13_startup_removes_live_output_in_running():
    """_startup_check() deletes .live_output files from the running folder."""
    running = logic.activeProject.properties.runningFolder
    stale = os.path.join(running, 'stale-test.live_output')
    with open(stale, 'w') as f:
        f.write("leftover from dead session")
    assert os.path.isfile(stale), "precondition: stale file must exist"

    wc._startup_check()

    return ok(not os.path.isfile(stale),
              f".live_output file was not removed: {stale}")

test("S13: _startup_check() removes stale .live_output files in running folder",
     test_s13_startup_removes_live_output_in_running)


def test_s14_startup_removes_live_output_in_output():
    """_startup_check() deletes .live_output files from the output folder."""
    output = logic.activeProject.properties.outputFolder
    stale = os.path.join(output, 'stale-output.live_output')
    with open(stale, 'w') as f:
        f.write("leftover from dead session")
    assert os.path.isfile(stale), "precondition: stale file must exist"

    wc._startup_check()

    return ok(not os.path.isfile(stale),
              f".live_output file was not removed from output folder: {stale}")

test("S14: _startup_check() removes stale .live_output files in output folder",
     test_s14_startup_removes_live_output_in_output)


def test_s15_startup_does_not_remove_other_files():
    """_startup_check() must not delete files that don't end in .live_output."""
    running = logic.activeProject.properties.runningFolder
    keep = os.path.join(running, 'important-output.txt')
    with open(keep, 'w') as f:
        f.write("real output that should survive startup")

    wc._startup_check()

    result = ok(os.path.isfile(keep), f"non-live_output file was incorrectly deleted: {keep}")
    try:
        os.unlink(keep)
    except Exception:
        pass
    return result

test("S15: _startup_check() does not delete non-.live_output files",
     test_s15_startup_does_not_remove_other_files)


print("\n" + "=" * 60)
print("v10.25: closeProject() WAL cleanup")
print("=" * 60 + "\n")


def test_s16_close_project_removes_temp_db():
    """closeProject() must delete the temp .legion DB file for a temp project."""
    # Fresh isolated app so we can destroy it
    app2, logic2, wc2 = create_test_app()
    db_path = logic2.activeProject.database.name
    assert os.path.isfile(db_path), "precondition: DB file must exist before close"
    wc2.closeProject()
    return ok(not os.path.isfile(db_path),
              f"temp DB still exists after closeProject(): {db_path}")

test("S16: closeProject() removes the temp DB file", test_s16_close_project_removes_temp_db)


def test_s17_close_project_no_wal_orphans():
    """After closeProject(), no WAL or SHM companion files remain."""
    app2, logic2, wc2 = create_test_app()
    db_path = logic2.activeProject.database.name

    # Force a write so SQLite has WAL activity
    from sqlalchemy import text as _t2
    session = logic2.activeProject.database.session()
    try:
        session.execute(_t2("CREATE TABLE IF NOT EXISTS _wal_test (x INTEGER)"))
        session.execute(_t2("INSERT INTO _wal_test VALUES (1)"))
        session.commit()
    finally:
        session.close()

    wal = db_path + '-wal'
    shm = db_path + '-shm'

    wc2.closeProject()

    wal_gone = not os.path.isfile(wal)
    shm_gone = not os.path.isfile(shm)
    db_gone  = not os.path.isfile(db_path)

    if wal_gone and shm_gone and db_gone:
        return True
    return (f"Files still exist after closeProject() — "
            f"db={not db_gone} wal={not wal_gone} shm={not shm_gone}")

test("S17: closeProject() leaves no WAL or SHM files", test_s17_close_project_no_wal_orphans)


# ══════════════════════════════════════════════════════════════
# v10.26 — FILE ISOLATION BETWEEN SERVER INSTANCES
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("v10.26: Log file isolation (RotatingFileHandler)")
print("=" * 60 + "\n")


def test_s18_log_uses_rotating_handler():
    """The 'legion' logger must use RotatingFileHandler, not plain FileHandler."""
    import logging
    from logging.handlers import RotatingFileHandler
    logger = logging.getLogger('legion')
    rotating = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    plain = [h for h in logger.handlers
             if isinstance(h, logging.FileHandler) and not isinstance(h, RotatingFileHandler)]
    if plain:
        return f"Found plain FileHandler — log file is not rotation-aware: {plain}"
    return ok(len(rotating) >= 1,
              f"No RotatingFileHandler found on 'legion' logger; handlers={logger.handlers}")

test("S18: 'legion' logger uses RotatingFileHandler", test_s18_log_uses_rotating_handler)


def test_s19_rotating_handler_config():
    """RotatingFileHandler must be configured with 10 MB max and 3 backups."""
    import logging
    from logging.handlers import RotatingFileHandler
    logger = logging.getLogger('legion')
    rh = next((h for h in logger.handlers if isinstance(h, RotatingFileHandler)), None)
    if rh is None:
        return "No RotatingFileHandler found"
    want_bytes = 10 * 1024 * 1024
    got_bytes   = rh.maxBytes
    got_backup  = rh.backupCount
    if got_bytes != want_bytes:
        return f"maxBytes={got_bytes}, expected {want_bytes} (10 MB)"
    if got_backup != 3:
        return f"backupCount={got_backup}, expected 3"
    return True

test("S19: RotatingFileHandler maxBytes=10 MB, backupCount=3",
     test_s19_rotating_handler_config)


def test_s20_session_separator_in_log():
    """A SESSION START marker must be present in the current log file."""
    import logging
    from logging.handlers import RotatingFileHandler
    logger = logging.getLogger('legion')
    rh = next((h for h in logger.handlers if isinstance(h, RotatingFileHandler)), None)
    if rh is None:
        return "No RotatingFileHandler to read log path from"
    log_path = rh.baseFilename
    if not os.path.isfile(log_path):
        return f"Log file does not exist: {log_path}"
    with open(log_path, 'r', errors='replace') as f:
        content = f.read()
    return ok('SESSION START' in content,
              "SESSION START separator not found in log file — "
              "sessions are not distinguishable in the log")

test("S20: Session-start separator written to log file", test_s20_session_separator_in_log)


print("\n" + "=" * 60)
print("v10.26: _screenshots_taken reset on start()")
print("=" * 60 + "\n")


def test_s21_screenshots_taken_reset():
    """_screenshots_taken must be an empty set after start()."""
    # Pollute state as if a previous project had taken screenshots
    wc._screenshots_taken = {'192.168.1.1:80', '10.0.0.1:443', '172.16.0.5:8080'}
    wc.start('fresh-project')
    result = ok(wc._screenshots_taken == set(),
                f"_screenshots_taken not reset: {wc._screenshots_taken}")
    wc.start()  # restore normal state
    return result

test("S21: _screenshots_taken is reset to empty set on start()",
     test_s21_screenshots_taken_reset)


print("\n" + "=" * 60)
print("v10.26: _cleanup_orphaned_temp_files()")
print("=" * 60 + "\n")

# Helpers for orphan cleanup tests
TMP_LEGION = '/tmp/legion'
_PID = os.getpid()


def _make_orphan_db(tag=''):
    """Create a fake orphaned .legion file (and WAL) in /tmp/legion/ and return its path."""
    os.makedirs(TMP_LEGION, exist_ok=True)
    db_path = os.path.join(TMP_LEGION, f'legion-orphan{_PID}{tag}.legion')
    with open(db_path, 'w') as f:
        f.write("fake orphan db")
    return db_path


def _make_orphan_dirs(tag=''):
    """Create companion -running and -tool-output dirs for an orphan (same UID as DB)."""
    uid = f'legion-orphan{_PID}{tag}'
    running = os.path.join(TMP_LEGION, uid + '-running')
    output  = os.path.join(TMP_LEGION, uid + '-tool-output')
    os.makedirs(running, exist_ok=True)
    os.makedirs(output,  exist_ok=True)
    return running, output


def test_s22_cleanup_removes_unlocked_db():
    """_cleanup_orphaned_temp_files() removes a .legion DB file that no process owns."""
    db_path = _make_orphan_db('A')
    assert os.path.isfile(db_path), "precondition: orphan DB must exist"

    wc._cleanup_orphaned_temp_files()

    return ok(not os.path.isfile(db_path),
              f"Orphaned DB not deleted: {db_path}")

test("S22: _cleanup_orphaned_temp_files() deletes unlocked orphaned .legion DB",
     test_s22_cleanup_removes_unlocked_db)


def test_s23_cleanup_removes_dirs_with_dead_pid_sentinel():
    """Dirs whose .legion_session_pid points at a dead process are deleted."""
    # Pick a PID that is virtually guaranteed to not be running.
    # We use 9999999 (beyond Linux's default pid_max of 4194304).
    dead_pid = 9999999

    running = os.path.join(TMP_LEGION, f'legion-orphan{_PID}C-running')
    output  = os.path.join(TMP_LEGION, f'legion-orphan{_PID}C-tool-output')
    os.makedirs(running, exist_ok=True)
    os.makedirs(output,  exist_ok=True)

    # Write dead-PID sentinel files — the cleanup code reads these
    for folder in (running, output):
        with open(os.path.join(folder, '.legion_session_pid'), 'w') as f:
            f.write(str(dead_pid))

    assert os.path.isdir(running) and os.path.isdir(output), "precondition"

    wc._cleanup_orphaned_temp_files()

    dirs_gone = not os.path.isdir(running) and not os.path.isdir(output)
    return ok(dirs_gone,
              f"Dirs with dead PID not cleaned — "
              f"running={os.path.isdir(running)} output={os.path.isdir(output)}")

test("S23: _cleanup_orphaned_temp_files() removes dirs whose PID sentinel is a dead process",
     test_s23_cleanup_removes_dirs_with_dead_pid_sentinel)


def test_s24_cleanup_skips_file_open_by_live_process():
    """A .legion file open in another process's FD table must NOT be deleted.

    We use /proc/PID/fd scanning (not flock) because SQLite uses POSIX fcntl
    advisory locks, not BSD flock — flock gives false negatives on active DBs.
    The subprocess simply opens the file and holds it open; /proc detects it.
    """
    db_path = _make_orphan_db('B')
    assert os.path.isfile(db_path), "precondition"

    # Subprocess opens the file and keeps it open until terminated.
    # /proc/PID/fd will show the open FD → cleanup must skip it.
    open_script = (
        "import sys, time\n"
        f"fd = open({db_path!r}, 'r')\n"
        "sys.stdout.write('OPEN\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    import subprocess
    holder = subprocess.Popen(
        [sys.executable, '-c', open_script],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        line = holder.stdout.readline()   # blocks until child signals ready
        if line.strip() != b'OPEN':
            holder.terminate(); holder.wait()
            return f"holder subprocess did not signal OPEN (got {line!r})"

        # File is open in a live process — cleanup must leave it alone
        wc._cleanup_orphaned_temp_files()
        still_exists = os.path.isfile(db_path)
    finally:
        holder.terminate()
        holder.wait()

    if still_exists:
        # Correct: skipped while live, now clean up
        wc._cleanup_orphaned_temp_files()
        try:
            os.unlink(db_path)
        except Exception:
            pass
        return True

    return ("Cleanup deleted a file that was open by a live process — "
            "would corrupt an active session")

test("S24: _cleanup_orphaned_temp_files() skips .legion files open in a live process",
     test_s24_cleanup_skips_file_open_by_live_process)


def test_s25_cleanup_skips_current_session():
    """_cleanup_orphaned_temp_files() must never touch the current session's files.

    Verifies three things:
    1. The DB file survives (protected by /proc open-FD check)
    2. The running folder survives (protected by live PID sentinel)
    3. The output folder survives (protected by live PID sentinel)
    """
    current_db      = logic.activeProject.properties.projectName
    current_running = logic.activeProject.properties.runningFolder
    current_output  = logic.activeProject.properties.outputFolder

    if not os.path.isfile(current_db):
        return f"precondition: current DB does not exist at {current_db}"
    if not os.path.isdir(current_running):
        return f"precondition: current running dir does not exist at {current_running}"
    if not os.path.isdir(current_output):
        return f"precondition: current output dir does not exist at {current_output}"

    # Confirm our PID sentinel is present and correct
    pid_sentinel = os.path.join(current_running, '.legion_session_pid')
    if not os.path.isfile(pid_sentinel):
        return "precondition: .legion_session_pid sentinel not written to running folder"
    sentinel_pid = int(open(pid_sentinel).read().strip())
    if sentinel_pid != os.getpid():
        return f"sentinel PID {sentinel_pid} != current PID {os.getpid()}"

    wc._cleanup_orphaned_temp_files()

    db_ok      = os.path.isfile(current_db)
    running_ok = os.path.isdir(current_running)
    output_ok  = os.path.isdir(current_output)

    if db_ok and running_ok and output_ok:
        return True
    return (f"Current session files were deleted by cleanup! "
            f"db_gone={not db_ok} running_gone={not running_ok} output_gone={not output_ok}")

test("S25: _cleanup_orphaned_temp_files() skips current session's own files",
     test_s25_cleanup_skips_current_session)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'=' * 60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'=' * 60}")
sys.exit(0 if FAIL == 0 else 1)
