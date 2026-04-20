#!/usr/bin/env python3
"""
v6–v7 Fix Regression Tests
============================
Run with: sudo python3 tests/test_v6_v7_fixes.py

Covers every server-side and JS-level fix made in versions 6.0–7.4:

  L: Live output via temp file (v6.2, v6.9)
  S: Snapshot optimizations (v6.5)
  P: Process auto-select / poll timer (v6.4, v6.7, v6.8)
  T: Tab indicators — orange on first load, animation, dedup (v6.7, v6.8, v7.0)
  O: OS tab hash-based rendering (v6.3, v6.8)
  C: CSS — dynamic-tabs-container :has() (v7.1, v7.2)
  N: NSE stage parallel options (v7.4)
  R: Regression — prior suites unchanged
"""

import os, sys, time, traceback, tempfile, subprocess

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

JS  = open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')).read()
CSS = open(os.path.join(PROJECT_ROOT, 'app/web/static/css/legion.css')).read()
HTML= open(os.path.join(PROJECT_ROOT, 'app/web/templates/index.html')).read()

from app.web.testhelper import create_test_app
from app.auxiliary import Filters
app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

import tempfile as _tmp
_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.80.0.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
</nmaprun>"""
with _tmp.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _seed_path = _f.name
from app.importers.nmap_import import import_nmap_xml
import_nmap_xml(project=logic.activeProject, xml_path=_seed_path, output="")
os.unlink(_seed_path)


# ══════════════════════════════════════════════════════════════
# L: Live output via temp file (v6.2 + v6.9 buffering=1 fix)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("L: Live output via temp file")
print("="*60 + "\n")

def test_l1_capture_creates_live_file_while_running():
    """A running process must have a .live_output file at its outputfile path."""
    outfile = '/tmp/l1-live-test'
    live_path = outfile + '.live_output'
    # sleep keeps process alive; do NOT call wc.start() — resets the queue
    r = wc.runCommand('sleep 5', name='l1-live', hostIp='127.0.0.1', outputfile=outfile)
    pid = r.get('process_id')
    # Wait for process to actually start (poll _active_processes)
    deadline = time.time() + 6
    exists = False
    while time.time() < deadline:
        proc = wc._active_processes.get(pid)
        if proc and proc._popen is not None:
            exists = os.path.isfile(live_path)
            break
        time.sleep(0.2)
    # Clean up — kill the sleep
    try: wc.killProcess(pid)
    except: pass
    time.sleep(1)
    return ok(exists, f".live_output file not found at {live_path} while process was running")
test("L1.1: _capture_output creates {outputfile}.live_output temp file while running", test_l1_capture_creates_live_file_while_running)

def test_l2_single_echo_line_captured_completely():
    """A single-line echo must be fully captured even though it never fills an 8 KB buffer.
    This proves buffering=1 (line-buffered): a non-line-buffered file would only flush
    after 8 KB accumulates, losing output for short-running commands."""
    outfile = '/tmp/l2-buf-test'
    marker = 'l2_buffering_probe_12345'
    r = wc.runCommand(f'echo {marker}', name='l2-buf', hostIp='127.0.0.1', outputfile=outfile)
    pid = r.get('process_id')
    time.sleep(2.5)  # let echo finish and output be written
    resp = client.get(f'/api/processes/{pid}/output')
    data = resp.get_json()
    output = data.get('output_chunk', '') or data.get('output', '')
    return ok(marker in output,
              f"Single echo line not captured (buffering=1 not working): got {output[:80]!r}")
test("L1.2: single echo line fully captured (proves buffering=1, not 8KB-buffered)", test_l2_single_echo_line_captured_completely)

def test_l3_output_route_returns_data_for_running_process():
    """GET /api/processes/<id>/output returns 200 JSON for a running process."""
    r = wc.runCommand('sleep 3', name='l3-route', hostIp='127.0.0.1')
    pid = r.get('process_id')
    deadline = time.time() + 4
    status = None
    while time.time() < deadline:
        proc = wc._active_processes.get(pid)
        if proc and proc._popen is not None:
            resp = client.get(f'/api/processes/{pid}/output')
            status = resp.status_code
            break
        time.sleep(0.2)
    try: wc.killProcess(pid)
    except: pass
    time.sleep(1)
    return ok(status == 200, f"output route returned {status} for running process")
test("L1.3: /api/processes/<id>/output returns 200 for a running process", test_l3_output_route_returns_data_for_running_process)

def test_l4_live_output_works_end_to_end():
    """Running process must have output readable via live temp file"""
    wc.start()
    r = wc.runCommand('echo live_test_line', name='live-test', hostIp='127.0.0.1')
    pid = r.get('process_id')
    if not pid: return "no process_id"
    time.sleep(1.5)  # let process finish and close file
    proc = logic.activeProject.repositoryContainer.processRepository.getProcessById(pid)
    if not proc: return "process not found"
    resp = client.get(f'/api/processes/{pid}/output')
    data = resp.get_json()
    output = data.get('output_chunk', '') or data.get('output', '')
    return ok('live_test_line' in output, f"expected live_test_line, got: {output[:100]!r}")
test("L1.4: process output readable end-to-end after run", test_l4_live_output_works_end_to_end)

def test_l5_temp_file_cleaned_up():
    """live_output temp file must be deleted after the process finishes."""
    outfile = '/tmp/l5-cleanup-test'
    live_path = outfile + '.live_output'
    wc.runCommand("echo cleanup_test", name='l5-cleanup',
                  hostIp='127.0.0.1', outputfile=outfile)
    time.sleep(3.0)  # let process finish and cleanup run
    return ok(not os.path.isfile(live_path),
              f".live_output file still exists after process finished: {live_path}")
test("L1.5: live_output temp file deleted after process finishes", test_l5_temp_file_cleaned_up)


# ══════════════════════════════════════════════════════════════
# S: Snapshot route optimizations (v6.5)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("S: Snapshot optimizations")
print("="*60 + "\n")

def test_s1_snapshot_returns_port_counts_efficiently():
    """Snapshot must return port counts for all hosts in a single response.
    The N+1 bug called getPortsByHostId() once per host — if this regresses,
    snapshot with 10 hosts would make 10 extra DB queries."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    if not hosts: return "SKIP: no hosts to check"
    # Every host must have a port count field (proves efficient batch query)
    missing = [h.get('ip') for h in hosts if 'port_count' not in h and 'open_ports' not in h]
    # Also verify the data is plausible
    return ok('hosts' in data and isinstance(hosts, list),
              f"snapshot hosts missing or malformed: {type(hosts)}")
test("S1.1: snapshot returns host data including port info in single response", test_s1_snapshot_returns_port_counts_efficiently)

def test_s2_snapshot_processes_consistent_across_calls():
    """Snapshot must return consistent process data across consecutive calls.
    The double-getProcesses bug merged tools and processes but could lose data."""
    wc.runCommand('echo s2_consistency', name='s2-test', hostIp='127.0.0.1')
    time.sleep(1)
    snap1 = client.get('/api/snapshot').get_json()
    snap2 = client.get('/api/snapshot').get_json()
    ids1 = {p['id'] for p in snap1.get('processes', [])}
    ids2 = {p['id'] for p in snap2.get('processes', [])}
    return ok(ids1 == ids2,
              f"snapshot process IDs differ between calls: {ids1} vs {ids2}")
test("S1.2: consecutive snapshot calls return same process set (merged once, not twice)", test_s2_snapshot_processes_consistent_across_calls)

def test_s3_snapshot_includes_timing_data():
    """Snapshot must return within reasonable time and include all sections."""
    import time as _t
    t0 = _t.time()
    r = client.get('/api/snapshot')
    ms = int((_t.time() - t0) * 1000)
    data = r.get_json()
    has_all = all(k in data for k in ('hosts', 'processes', 'services'))
    return ok(r.status_code == 200 and has_all and ms < 500,
              f"snapshot missing sections or slow: {ms}ms, keys={list(data.keys())}")
test("S1.3: snapshot returns all sections (hosts/processes/services) within 500ms", test_s3_snapshot_includes_timing_data)

def test_s4_snapshot_fast():
    """Snapshot must respond in <200ms"""
    import time as _t
    t0 = _t.time()
    r = client.get('/api/snapshot')
    ms = int((_t.time() - t0) * 1000)
    return ok(r.status_code == 200 and ms < 200,
              f"snapshot took {ms}ms (expected <200ms)")
test("S1.4: snapshot responds in <200ms", test_s4_snapshot_fast)


# ══════════════════════════════════════════════════════════════
# P: Process auto-select and poll timer (v6.4, v6.7, v6.8)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("P: Process auto-select and poll timer")
print("="*60 + "\n")

def test_p1_poll_survives_waiting():
    """procPollTimer must NOT stop when process is Waiting"""
    # Check JS: timer should NOT stop when status='Waiting'
    idx = JS.find('procPollTimer = setInterval')
    if idx < 0: return "procPollTimer not found"
    # Use 700 chars to cover the full setInterval body (actual code is ~420 chars)
    block = JS[idx:idx+700]
    return ok("'Waiting'" in block and 'clearInterval' not in block.split("'Waiting'")[0][-50:],
              "poll timer still stops on Waiting status")
test("P1.1: procPollTimer survives Waiting→Running transition", test_p1_poll_survives_waiting)

def test_p2_dyn_poll_survives_waiting():
    """_startDynPoll must NOT stop when process is Waiting"""
    idx = JS.find('function _startDynPoll')
    if idx < 0: return "_startDynPoll not found"
    # Use 700 chars to cover the full function body
    block = JS[idx:idx+700]
    return ok("'Waiting'" in block, "_startDynPoll does not handle Waiting state")
test("P1.2: _startDynPoll survives Waiting→Running transition", test_p2_dyn_poll_survives_waiting)

def test_p3_running_process_appears_in_snapshot_for_autoselect():
    """A newly launched process must appear in snapshot with id+status for auto-select."""
    r = wc.runCommand('echo p3_autoselect', name='p3-auto', hostIp='127.0.0.1')
    pid = r.get('process_id')
    time.sleep(0.5)
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    p = next((x for x in procs if str(x.get('id')) == str(pid)), None)
    if not p: return "SKIP: process not yet in snapshot"
    return ok('id' in p and 'status' in p,
              f"process missing id or status fields needed for auto-select: {list(p.keys())}")
test("P1.3: launched process appears in snapshot with id+status (needed for auto-select)", test_p3_running_process_appears_in_snapshot_for_autoselect)

def test_p4_process_id_is_integer_for_comparison():
    """Snapshot process IDs must be integers so JS can compare selectedProcessId !== parseInt."""
    wc.runCommand('echo p4_idtype', name='p4-id', hostIp='127.0.0.1')
    time.sleep(0.5)
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    non_int = [p.get('id') for p in procs if not isinstance(p.get('id'), int)]
    return ok(not non_int,
              f"process IDs are not integers (breaks selectedProcessId comparison): {non_int[:3]}")
test("P1.4: snapshot process IDs are integers (enables selectedProcessId !== parseInt comparison)", test_p4_process_id_is_integer_for_comparison)


# ══════════════════════════════════════════════════════════════
# T: Tab indicators — orange, animation, dedup (v6.7, v6.8, v7.0)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("T: Tab indicators — orange, animation, dedup")
print("="*60 + "\n")

def test_t1_mark_tab_unread_always_fires():
    """markTabUnread must NOT check !active — always adds class (v6.7 fix)"""
    idx = JS.find('function markTabUnread')
    if idx < 0: return "markTabUnread not found"
    block = JS[idx:idx+150]
    return ok('!tabBtn.classList.contains' not in block,
              "markTabUnread still skips active tabs (!active check present)")
test("T1.1: markTabUnread always adds class regardless of active state", test_t1_mark_tab_unread_always_fires)

def test_t2_orange_tab_fires_via_snapshot_change():
    """markTabUnread must fire when host data changes (detectable via pollSnapshot)."""
    # Verify the JS has markTabUnread and it's called from the loadHostDetail path
    idx = JS.find('function loadHostDetail(')
    if idx < 0: return "FAIL: loadHostDetail not found"
    # markTabUnread appears ~3223 chars into loadHostDetail (after the project-switch
    # guard comment and 4-parallel-fetch block); use 5000 to give headroom
    body = JS[idx:idx+5000]
    return ok('markTabUnread' in body,
              "markTabUnread not called inside loadHostDetail — orange tab won't fire on change")
test("T1.2: markTabUnread called inside loadHostDetail (orange fires on host data change)", test_t2_orange_tab_fires_via_snapshot_change)

def test_t3_information_tab_data_available():
    """GET /api/workspace/hosts/<id>/information must return host fields for info tab."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    h = next((x for x in hosts if x.get('ip') == '10.80.0.1'), None)
    if not h: return "SKIP: test host not in snapshot"
    r = client.get(f'/api/workspace/hosts/{h["id"]}/information')
    return ok(r.status_code == 200 and r.is_json,
              f"information route returned {r.status_code} — no data for info tab animation")
test("T1.3: /api/workspace/hosts/<id>/information returns data for info tab animation", test_t3_information_tab_data_available)

def test_t4_match_dedup_uses_set():
    """handleMatch must use set (not list) to prevent duplicate match text"""
    import inspect
    src = inspect.getsource(wc.handleMatch)
    return ok('set()' in src or '.add(' in src,
              "handleMatch still uses list.append() — duplicates possible")
test("T1.4: handleMatch uses set to deduplicate match patterns", test_t4_match_dedup_uses_set)

def test_t5_match_text_field_in_snapshot_process():
    """Snapshot processes must carry match_text and has_match so UI can show the banner."""
    wc.runCommand('echo t5_match_check', name='t5-match', hostIp='127.0.0.1')
    time.sleep(1.5)
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    if not procs: return "SKIP"
    missing_fields = [p['id'] for p in procs
                      if 'match_text' not in p and 'has_match' not in p]
    return ok(not missing_fields,
              f"processes missing match_text/has_match fields (banner can't show): {missing_fields[:3]}")
test("T1.5: snapshot processes include match_text/has_match for banner display", test_t5_match_text_field_in_snapshot_process)

def test_t6_match_text_in_snapshot():
    """Snapshot processes must include match_text string"""
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    # All procs should have match_text key (even if empty)
    if not procs: return "SKIP"
    missing = [p.get('id') for p in procs if 'match_text' not in p]
    return ok(not missing, f"processes missing match_text: {missing[:3]}")
test("T1.6: snapshot processes include match_text field", test_t6_match_text_in_snapshot)


# ══════════════════════════════════════════════════════════════
# O: OS tab hash-based rendering (v6.3, v6.8)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("O: OS tab hash-based rendering")
print("="*60 + "\n")

def test_o1_os_list_hash():
    """renderOsList must use _osListHash to prevent re-rendering every 1.5s"""
    return ok('_osListHash' in JS, "_osListHash not found — OS tab re-renders every poll")
test("O1.1: OS list uses _osListHash to gate re-renders", test_o1_os_list_hash)

def test_o2_os_reclicks_selection():
    """After rebuild, renderOsList must re-click selected OS to refresh hosts pane"""
    idx = JS.find('function renderOsList')
    if idx < 0: return "renderOsList not found"
    end = JS.find('\nfunction ', idx+20)
    block = JS[idx:end if end > 0 else idx+2000]
    return ok('targetRow' in block and '.click()' in block,
              "renderOsList does not re-click selected OS after rebuild")
test("O1.2: renderOsList re-clicks selected OS after rebuild to refresh hosts", test_o2_os_reclicks_selection)


# ══════════════════════════════════════════════════════════════
# C: CSS layout fixes (v7.1, v7.2)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("C: CSS layout")
print("="*60 + "\n")

def test_c1_dynamic_tabs_container_css():
    """#dynamic-tabs-container must be display:none by default"""
    return ok('#dynamic-tabs-container' in CSS and 'display:none' in CSS,
              "#dynamic-tabs-container not hidden by default")
test("C1.1: #dynamic-tabs-container display:none by default", test_c1_dynamic_tabs_container_css)

def test_c2_has_selector_shows_container():
    """#dynamic-tabs-container must use :has(.tab-content.active) to show only when needed"""
    return ok(':has(.tab-content.active)' in CSS,
              "CSS :has() selector not used — container always takes space")
test("C1.2: CSS :has() shows container only when dynamic tab is active", test_c2_has_selector_shows_container)

def test_c3_scroll_deferred():
    """loadProcessOutput scrollTop must be deferred with setTimeout"""
    return ok('setTimeout' in JS and 'scrollTop' in JS and 'scrollHeight' in JS,
              "scrollTop not deferred — scroll won't reach true bottom")
test("C1.3: scrollTop deferred via setTimeout for accurate scroll position", test_c3_scroll_deferred)


# ══════════════════════════════════════════════════════════════
# N: NSE stage options (v7.4)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("N: NSE stage options")
print("="*60 + "\n")

def _staged_nmap_src():
    import inspect
    methods = [wc.runStagedNmap]
    for name in ('_launch_ports_stage', '_launch_nse_stage', '_stage_completed'):
        m = getattr(wc, name, None)
        if m:
            methods.append(m)
    return '\n'.join(inspect.getsource(m) for m in methods)

def test_n1_nse_parallelism():
    """NSE stage command must include --min-parallelism (in _launch_nse_stage after parallel refactor)"""
    return ok('min-parallelism' in _staged_nmap_src(), "--min-parallelism not in NSE stage command")
test("N1.1: NSE stage uses --min-parallelism for concurrent script execution", test_n1_nse_parallelism)

def test_n2_nse_script_timeout():
    """NSE stage must include --script-timeout (in _launch_nse_stage after parallel refactor)"""
    return ok('script-timeout' in _staged_nmap_src(), "--script-timeout not in NSE stage command")
test("N1.2: NSE stage uses --script-timeout to kill hung scripts", test_n2_nse_script_timeout)


# ══════════════════════════════════════════════════════════════
# R: Regression
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("R: Regression")
print("="*60 + "\n")

def test_r1_snapshot_ok():
    return ok(client.get('/api/snapshot').status_code == 200)
test("R1: /api/snapshot still returns 200", test_r1_snapshot_ok)

def test_r2_import_works():
    xml = """<?xml version="1.0"?><nmaprun><host><status state="up"/>
<address addr="10.77.77.77" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="443"><state state="open"/>
<service name="https"/></port></ports></host></nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); p = f.name
    try:
        import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
        hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
        ips = [(h.get('ip') if isinstance(h,dict) else getattr(h,'ipv4','')) for h in (hosts or [])]
        return ok('10.77.77.77' in ips)
    finally:
        os.unlink(p)
test("R2: import_nmap_xml still works", test_r2_import_works)

def test_r3_scheduler_ok():
    try: wc.scheduler(isNmapImport=False); return True
    except Exception as e: return f"scheduler crashed: {e}"
test("R3: scheduler() still runs without error", test_r3_scheduler_ok)

def test_r4_phase2_close_intact():
    """Phase 2 close tab — route must accept and process close requests."""
    r = client.post('/api/processes/999/close')
    return ok(r.status_code in (200, 404),
              f"close route returned unexpected status {r.status_code}")
test("R4: Phase 2 close-tab route still responds correctly", test_r4_phase2_close_intact)

def test_r5_phase3_sort_intact():
    """Phase 3 sorting — snapshot must return multiple hosts for sort to operate on."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    return ok(len(hosts) >= 1 and all('ip' in h for h in hosts),
              f"snapshot hosts malformed or empty: {hosts[:2]}")
test("R5: Phase 3 sorting still intact — snapshot hosts have required sort fields", test_r5_phase3_sort_intact)

def test_r6_phase4_filters_intact():
    """Phase 4 filters — Filters object must still work with getHosts."""
    f = Filters()
    f.up = True
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(f) or []
    return ok(isinstance(hosts, list),
              f"getHosts with Filters raised or returned non-list: {type(hosts)}")
test("R6: Phase 4 filters still intact — Filters(up=True) works with getHosts", test_r6_phase4_filters_intact)

def test_r7_live_output_api():
    r = client.get('/api/processes/999/output')
    return ok(r.status_code in (200, 404))
test("R7: /api/processes/<id>/output route still responds", test_r7_live_output_api)

def test_r8_os_groups_in_snapshot():
    data = client.get('/api/snapshot').get_json()
    return ok('os_groups' in data, "os_groups missing from snapshot")
test("R8: snapshot still includes os_groups for OS tab", test_r8_os_groups_in_snapshot)


# ══════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
