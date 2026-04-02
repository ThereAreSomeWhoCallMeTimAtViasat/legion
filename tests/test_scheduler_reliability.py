#!/usr/bin/env python3
"""
Scheduler Reliability Tests
============================
Run with: sudo python3 tests/test_scheduler_reliability.py

Proves and protects against three intermittent scheduler bugs identified in
analysis committed alongside these tests:

  Bug 1 — _shutting_down flag never resets between scans
    R01  killRunningProcesses() sets _shutting_down=True  [baseline]
    R02  scheduler() is a no-op when _shutting_down=True  [baseline - proves mechanism]
    R03  scheduler() launches tools when _shutting_down=False  [baseline]
    R04  runStagedNmap() resets _shutting_down=False before launching stages
         FAILS on current code — PASSES after fix

  Bug 2 — already_ran dedup blocks tools on rescan
    R05  scheduler skips a Waiting tool (correct within-scan dedup)  [baseline]
    R06  scheduler skips a Running tool (correct within-scan dedup)  [baseline]
    R07  scheduler re-launches a Finished tool for the same port
         FAILS on current code — PASSES after fix (check only Waiting/Running)

  Bug 3 — concurrent scheduler calls race on the dedup query
    R08  5 concurrent scheduler() calls produce at most 1 process per tool per port
         Flaky on current code — always passes with _scheduler_lock fix
"""

import os, sys, time, traceback, tempfile, threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = FAIL = SKIP = 0

HOST_IP = '192.168.200.1'   # RFC documentation range — never routes to a real host

# Minimal nmap XML with one open HTTP port (port 80 / service 'http').
# The scheduler has feroxbuster + gobuster-dir + nuclei wired to 'http' service
# so importing this XML gives the scheduler real work to do without nmap running.
SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.200.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache httpd" version="2.4.52"/>
      </port>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.9p1"/>
      </port>
    </ports>
  </host>
</nmaprun>"""


# ─────────────────────────────────────────────────────────────────────────────
# Test harness helpers
# ─────────────────────────────────────────────────────────────────────────────

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        r = fn()
        if r is None or r is True:
            PASS += 1; print(f"  ✓ {name}"); return True
        elif r == 'SKIP':
            SKIP += 1; print(f"  ⊘ {name} (SKIP)"); return False
        else:
            FAIL += 1; print(f"  ✗ {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  ✗ {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""):    return True if v else f"FAIL: {msg}"
def eq(a, b, msg=""): return True if a == b else f"expected {b!r}, got {a!r} ({msg})"


# ─────────────────────────────────────────────────────────────────────────────
# Shared setup
# ─────────────────────────────────────────────────────────────────────────────

from app.web.testhelper import create_test_app
from app.auxiliary import Filters
from sqlalchemy import text as _text
from controller.web_controller import WebProcessStub
from app.timing import getTimestamp

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()


def _seed_host():
    """Import SEED_XML so HOST_IP has port 80/http and 22/ssh in DB."""
    from app.importers.nmap_import import import_nmap_xml
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED_XML)
        xml_path = f.name
    try:
        import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output="")
    finally:
        os.unlink(xml_path)


def _non_nmap_processes(host_ip=None):
    """Return all non-closed, non-nmap processes, optionally filtered to one host."""
    session = logic.activeProject.database.session()
    try:
        logic.activeProject.database.session.remove()
        session = logic.activeProject.database.session()
        rows = session.execute(_text(
            "SELECT id, name, hostIp, port, status FROM process "
            "WHERE closed='False' AND name NOT LIKE 'nmap%'"
        )).fetchall()
    finally:
        session.close()
    if host_ip:
        return [dict(r._mapping) for r in rows if r.hostIp == host_ip]
    return [dict(r._mapping) for r in rows]


def _count_tool_processes(tool_name, host_ip, port):
    """Count DB rows for a specific tool on a specific host:port (any status, not closed)."""
    session = logic.activeProject.database.session()
    try:
        logic.activeProject.database.session.remove()
        session = logic.activeProject.database.session()
        row = session.execute(_text(
            "SELECT COUNT(*) FROM process "
            "WHERE name=:n AND hostIp=:h AND port=:p AND closed='False'"
        ), {'n': tool_name, 'h': host_ip, 'p': str(port)}).fetchone()
        return int(row[0]) if row else 0
    finally:
        session.close()


def _set_process_status(proc_id, status):
    """Force a process to a specific status in DB."""
    session = logic.activeProject.database.session()
    try:
        session.execute(_text("UPDATE process SET status=:s WHERE id=:id"),
                        {'s': status, 'id': proc_id})
        session.commit()
    finally:
        session.close()


def _fresh_start():
    """Reset wc state and seed DB with one HTTP host.
    Kills any in-flight processes (and their _capture_output threads) from
    prior tests before resetting, so background scheduler() calls from those
    threads don't race with the new test's scheduler calls."""
    wc.killRunningProcesses()
    time.sleep(0.8)   # let _capture_output threads notice kill status and exit
    wc.start()        # resets _shutting_down=False, queues, scan_generation
    _seed_host()


# ══════════════════════════════════════════════════════════════════════════════
# Bug 1: _shutting_down flag never resets between scans
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 66)
print("Bug 1: _shutting_down flag never resets between scans")
print("=" * 66 + "\n")


def test_r01_kill_sets_shutting_down():
    """Baseline: killRunningProcesses() sets _shutting_down=True."""
    wc.start()
    assert not wc._shutting_down, "pre-condition: flag should be False after start()"
    wc.killRunningProcesses()
    return ok(wc._shutting_down is True,
              f"_shutting_down should be True after kill, got {wc._shutting_down!r}")

test("R01: killRunningProcesses() sets _shutting_down=True", test_r01_kill_sets_shutting_down)


def test_r02_scheduler_blocked_when_shutting_down():
    """Baseline: scheduler() is a no-op when _shutting_down=True — no new processes."""
    _fresh_start()
    # Verify host is seeded
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if not hosts:
        return 'SKIP'

    # Count processes before — should be 0 in fresh project
    before = len(_non_nmap_processes(HOST_IP))

    # Set flag and call scheduler
    wc._shutting_down = True
    wc.scheduler(isNmapImport=False)
    time.sleep(0.3)  # brief settle

    after = len(_non_nmap_processes(HOST_IP))
    wc._shutting_down = False  # restore for subsequent tests
    return ok(after == before,
              f"scheduler should be blocked: before={before}, after={after} processes")

test("R02: scheduler() is no-op when _shutting_down=True", test_r02_scheduler_blocked_when_shutting_down)


def test_r03_scheduler_launches_tools_when_not_shutting_down():
    """Baseline: scheduler() creates processes when _shutting_down=False."""
    _fresh_start()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if not hosts:
        return 'SKIP'

    before = len(_non_nmap_processes(HOST_IP))
    wc._shutting_down = False
    wc.scheduler(isNmapImport=False)
    time.sleep(0.5)

    after = len(_non_nmap_processes(HOST_IP))
    # Kill any started processes so they don't interfere with later tests
    wc.killRunningProcesses()
    time.sleep(0.3)
    wc._shutting_down = False

    return ok(after > before,
              f"scheduler should launch tools: before={before}, after={after}")

test("R03: scheduler() launches tools when _shutting_down=False", test_r03_scheduler_launches_tools_when_not_shutting_down)


def test_r04_new_scan_resets_shutting_down():
    """
    THE BUG TEST — currently FAILS, will PASS after fix.

    After killRunningProcesses() sets _shutting_down=True, calling
    runStagedNmap() for a new scan should reset it to False so the
    subsequent scheduler() calls (from _wait_and_import threads) can
    actually run tools.

    Fix: add `self._shutting_down = False` at the top of runStagedNmap(),
    before any stages are launched.
    """
    wc.start()
    wc.killRunningProcesses()
    assert wc._shutting_down is True, "pre-condition: kill must set flag"

    # Monkey-patch _launch_ports_stage to be a no-op so no real nmap runs.
    # We only need runStagedNmap() to execute its preamble (where the fix lives).
    orig_launch = wc._launch_ports_stage
    wc._launch_ports_stage = lambda *a, **kw: None
    try:
        wc.runStagedNmap(HOST_IP)
        time.sleep(0.1)  # preamble is synchronous; threads haven't started
    finally:
        wc._launch_ports_stage = orig_launch

    result = ok(wc._shutting_down is False,
                f"_shutting_down should be False after new scan, got {wc._shutting_down!r}"
                " — fix: add `self._shutting_down = False` at top of runStagedNmap()")
    wc._shutting_down = False  # restore regardless
    return result

test("R04: runStagedNmap() resets _shutting_down=False [FAILS until fix]",
     test_r04_new_scan_resets_shutting_down)


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2: already_ran dedup blocks tools even when they are Finished
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 66)
print("Bug 2: already_ran dedup too broad — blocks Finished tools on rescan")
print("=" * 66 + "\n")


def test_r05_scheduler_skips_waiting_tool():
    """Correct dedup: a Waiting process for the same tool+host+port is not duplicated."""
    _fresh_start()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if not hosts:
        return 'SKIP'

    # Run scheduler once to queue tools
    wc._shutting_down = False
    wc.scheduler(isNmapImport=False)
    time.sleep(0.3)

    # Find a Waiting process (should exist — feroxbuster/gobuster queued but not started)
    procs = _non_nmap_processes(HOST_IP)
    if not procs:
        return 'SKIP'
    waiting = [p for p in procs if p['status'] == 'Waiting']
    if not waiting:
        return 'SKIP'

    target = waiting[0]
    before_count = _count_tool_processes(target['name'], HOST_IP, target['port'])

    # Run scheduler again — should NOT add a duplicate for the Waiting process
    wc.scheduler(isNmapImport=False)
    time.sleep(0.3)

    after_count = _count_tool_processes(target['name'], HOST_IP, target['port'])

    wc.killRunningProcesses(); time.sleep(0.2); wc._shutting_down = False
    return ok(after_count == before_count,
              f"Waiting {target['name']}:{target['port']} duplicated: "
              f"before={before_count}, after={after_count}")

test("R05: scheduler skips a Waiting tool (correct within-scan dedup)", test_r05_scheduler_skips_waiting_tool)


def test_r06_scheduler_skips_running_tool():
    """Correct dedup: a Running process is not duplicated."""
    _fresh_start()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if not hosts:
        return 'SKIP'

    # Run scheduler to create a process, then manually force it to Running
    wc._shutting_down = False
    wc.scheduler(isNmapImport=False)
    time.sleep(0.5)

    procs = _non_nmap_processes(HOST_IP)
    if not procs:
        return 'SKIP'

    target = procs[0]
    _set_process_status(target['id'], 'Running')
    before_count = _count_tool_processes(target['name'], HOST_IP, target['port'])

    # Scheduler again — must not duplicate a Running process
    wc.scheduler(isNmapImport=False)
    time.sleep(0.3)

    after_count = _count_tool_processes(target['name'], HOST_IP, target['port'])
    wc.killRunningProcesses(); time.sleep(0.2); wc._shutting_down = False
    return ok(after_count == before_count,
              f"Running {target['name']}:{target['port']} duplicated: "
              f"before={before_count}, after={after_count}")

test("R06: scheduler skips a Running tool (correct within-scan dedup)", test_r06_scheduler_skips_running_tool)


def test_r07_scheduler_relaunches_finished_tool():
    """
    THE BUG TEST — currently FAILS, will PASS after fix.

    A Finished tool is not Running or Waiting — it has completed.  On a
    rescan the scheduler should treat it as eligible to run again.

    Current code: `getProcesses(showProcesses='noNmap')` returns ALL
    non-closed processes including Finished → already_ran=True → skipped.

    Fix: pass `status_filter=['Waiting', 'Running']` to getProcesses so
    only in-flight processes are considered — a Finished tool does not
    block re-launching on a new scan.
    """
    _fresh_start()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if not hosts:
        return 'SKIP'

    # Run scheduler to create tool processes
    wc._shutting_down = False
    wc.scheduler(isNmapImport=False)
    time.sleep(0.5)

    procs = _non_nmap_processes(HOST_IP)
    if not procs:
        return 'SKIP'

    # Pick a non-screenshooter tool — screenshooter has its own separate in-memory
    # dedup (_screenshots_taken set) which is NOT the DB already_ran check being
    # tested here.  Feroxbuster goes through the DB path we're fixing.
    candidates = [p for p in procs if p['name'] not in ('screenshooter',)]
    if not candidates:
        return 'SKIP'
    target = candidates[0]
    tool_name = target['name']
    tool_port  = target['port']

    # Force every instance of this tool to Finished (fresh_start may have
    # left multiple from prior test cleanup — we own all of them)
    session = logic.activeProject.database.session()
    try:
        session.execute(_text(
            "UPDATE process SET status='Finished' "
            "WHERE name=:n AND hostIp=:h AND port=:p AND closed='False'"
        ), {'n': tool_name, 'h': HOST_IP, 'p': str(tool_port)})
        session.commit()
    finally:
        session.close()

    before_count = _count_tool_processes(tool_name, HOST_IP, tool_port)

    # Run scheduler again — Finished tool should be re-launchable on rescan
    wc.scheduler(isNmapImport=False)
    time.sleep(0.5)

    after_count = _count_tool_processes(tool_name, HOST_IP, tool_port)
    wc.killRunningProcesses(); time.sleep(0.2); wc._shutting_down = False

    return ok(after_count > before_count,
              f"{tool_name}:{tool_port} should have been re-launched after Finished "
              f"(before={before_count}, after={after_count})"
              " — fix: status_filter=['Waiting','Running'] in scheduler already_ran check")

test("R07: scheduler re-launches Finished tool on rescan [FAILS until fix]",
     test_r07_scheduler_relaunches_finished_tool)


# ══════════════════════════════════════════════════════════════════════════════
# Bug 3: concurrent scheduler calls race on the dedup query
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 66)
print("Bug 3: concurrent scheduler() calls race on dedup — possible duplicates")
print("=" * 66 + "\n")


def test_r08_concurrent_scheduler_no_duplicates():
    """
    5 threads all call scheduler() simultaneously using a Barrier.
    Each thread races through the already_ran check for the same port.

    Without a _scheduler_lock: two threads can both pass the check before
    either commits its runCommand() → duplicate processes for the same tool.

    With a _scheduler_lock (threading.Lock around the scheduler body):
    threads serialise — only the first one launches; the rest find it.

    The test is probabilistic without the lock (may not always race) but
    deterministic with it (always passes).  If it fails, it proves the race.
    """
    _fresh_start()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    if not hosts:
        return 'SKIP'

    # Saturate process slots so scheduler creates DB rows (Waiting) but
    # nothing actually executes — keeps test fast and avoids real tool runs
    orig_running = wc.fastProcessesRunning
    wc.fastProcessesRunning = 999   # make checkProcessQueue never dequeue

    errors = []
    barrier = threading.Barrier(5)

    def _run():
        try:
            barrier.wait(timeout=5)
            wc.scheduler(isNmapImport=False)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=_run, daemon=True) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=10)

    wc.fastProcessesRunning = orig_running

    if errors:
        wc.killRunningProcesses(); time.sleep(0.2); wc._shutting_down = False
        return f"scheduler raised: {errors}"

    # Check for duplicates — count ONLY Waiting/Running (in-flight) instances.
    # Killed/Finished rows from prior tests accumulate in the same DB; counting
    # those would give false positives.  A genuine race produces multiple
    # Waiting or Running rows for the same tool+host+port in a single call batch.
    session = logic.activeProject.database.session()
    try:
        logic.activeProject.database.session.remove()
        session = logic.activeProject.database.session()
        dupes = session.execute(_text(
            "SELECT name, hostIp, port, COUNT(*) as cnt FROM process "
            "WHERE closed='False' AND name NOT LIKE 'nmap%' "
            "AND hostIp=:h AND status IN ('Waiting','Running') "
            "GROUP BY name, hostIp, port HAVING cnt > 1"
        ), {'h': HOST_IP}).fetchall()
    finally:
        session.close()

    wc.killRunningProcesses(); time.sleep(0.2); wc._shutting_down = False

    if dupes:
        dupe_str = ', '.join(f"{r.name}:{r.port}×{r.cnt}" for r in dupes)
        return (f"Race produced duplicate Waiting/Running processes: {dupe_str}"
                " — fix: add _scheduler_lock = threading.Lock() to scheduler()")
    return True

test("R08: 5 concurrent scheduler() calls produce no duplicate processes [may fail without lock]",
     test_r08_concurrent_scheduler_no_duplicates)


# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 66)
print(f"Results: {PASS} passed  {FAIL} failed  {SKIP} skipped")
print("=" * 66)
print()
print("Tests that FAIL on current code (expected until fixes applied):")
print("  R04 — _shutting_down not reset by runStagedNmap()")
print("  R07 — Finished tools blocked by already_ran on rescan")
print("  R08 — concurrent scheduler() may produce duplicates (probabilistic)")
print()
if FAIL > 0:
    sys.exit(1)
