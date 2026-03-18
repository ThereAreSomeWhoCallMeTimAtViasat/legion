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

def test_l1_capture_uses_live_file():
    """_capture_output must open a .live_output temp file"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('live_output' in src and 'live_file' in src,
              "_capture_output does not use live_output temp file")
test("L1.1: _capture_output creates {outputfile}.live_output temp file", test_l1_capture_uses_live_file)

def test_l2_temp_file_line_buffered():
    """Temp file must be line-buffered (buffering=1) so every line flushes immediately"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('buffering=1' in src,
              "temp file not line-buffered — output only visible after 8KB buffer fills")
test("L1.2: temp file opened with buffering=1 (line-buffered)", test_l2_temp_file_line_buffered)

def test_l3_output_route_reads_live_file():
    """Process output route must check for live_output file before SQLite"""
    from app.web import routes
    import inspect
    src = inspect.getsource(routes.process_output)
    return ok('live_output' in src and 'os.path.isfile' in src,
              "output route does not check live temp file first")
test("L1.3: /api/processes/<id>/output reads live_output file when present", test_l3_output_route_reads_live_file)

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
    """live_output temp file must be deleted after process finishes"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('os.unlink' in src or 'unlink' in src,
              "temp file not cleaned up on process finish")
test("L1.5: live_output temp file deleted on process finish", test_l5_temp_file_cleaned_up)


# ══════════════════════════════════════════════════════════════
# S: Snapshot route optimizations (v6.5)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("S: Snapshot optimizations")
print("="*60 + "\n")

def test_s1_snapshot_no_orm_port_count():
    """Snapshot must NOT call getPortsByHostId() (N+1 ORM) — use raw SQL COUNT instead"""
    from app.web import routes
    import inspect
    src = inspect.getsource(routes.snapshot)
    # Check there is no actual *call* to getPortsByHostId (comments are ok)
    # and that COUNT(*) is present in the raw SQL approach
    has_call = 'getPortsByHostId(' in src
    has_count = 'COUNT(*)' in src
    return ok(not has_call and has_count,
              "snapshot still calls getPortsByHostId() (N+1 ORM queries per host)")
test("S1.1: snapshot uses single SQL with COUNT(*) not N+1 getPortsByHostId", test_s1_snapshot_no_orm_port_count)

def test_s2_snapshot_single_getprocesses():
    """Snapshot must call getProcesses ONCE (was called twice — once for tools, once for procs)"""
    from app.web import routes
    import inspect
    src = inspect.getsource(routes.snapshot)
    count = src.count('getProcesses(')
    return ok(count <= 1, f"snapshot calls getProcesses {count} times (expected 1)")
test("S1.2: snapshot calls getProcesses only once (merged tools+processes)", test_s2_snapshot_single_getprocesses)

def test_s3_snapshot_timing_logged():
    """Snapshot must log timing for performance monitoring"""
    from app.web import routes
    import inspect
    src = inspect.getsource(routes.snapshot)
    return ok('_elapsed_ms' in src or 'monotonic' in src, "snapshot timing not logged")
test("S1.3: snapshot route logs response time", test_s3_snapshot_timing_logged)

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

def test_p3_auto_select_tracks_running_ids():
    """Auto-select must track _prevRunningIds to detect NEW running processes"""
    return ok('_prevRunningIds' in JS, "_prevRunningIds not found — auto-select won't work")
test("P1.3: auto-select tracks _prevRunningIds for new process detection", test_p3_auto_select_tracks_running_ids)

def test_p4_auto_select_same_process_no_restart():
    """Auto-select must NOT restart poll when already-selected process is running"""
    idx = JS.find('_prevRunningIds')
    if idx < 0: return "_prevRunningIds not found"
    block = JS[JS.find("selectedProcessId !== parseInt"):JS.find("selectedProcessId !== parseInt")+200]
    return ok('selectedProcessId !== parseInt' in JS,
              "auto-select restarts poll even for already-selected process")
test("P1.4: auto-select skips click if process already selected (no poll restart)", test_p4_auto_select_same_process_no_restart)


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

def test_t2_orange_on_first_load():
    """Orange must fire on first host load (prev=undefined) when data exists"""
    return ok('else {' in JS and 'markTabUnread' in JS and
              '/* First load' in JS or '!prev' in JS or 'prev is undefined' in JS or
              'else {\n            /* Qt6' in JS or 'First load for this host' in JS,
              "orange not marked on first host load")
test("T1.2: orange tab indicator fires on first host discovery", test_t2_orange_on_first_load)

def test_t3_info_animation_first_load():
    """renderInformation must queue ALL fields for animation on first host load"""
    return ok('hasPrev' in JS and 'changedFields.push' in JS and
              'First load for this host' in JS or ('} else if (val)' in JS),
              "info animation missing first-load flash")
test("T1.3: information tab flashes all fields on first host discovery", test_t3_info_animation_first_load)

def test_t4_match_dedup_uses_set():
    """handleMatch must use set (not list) to prevent duplicate match text"""
    import inspect
    src = inspect.getsource(wc.handleMatch)
    return ok('set()' in src or '.add(' in src,
              "handleMatch still uses list.append() — duplicates possible")
test("T1.4: handleMatch uses set to deduplicate match patterns", test_t4_match_dedup_uses_set)

def test_t5_match_banner_in_output():
    """loadProcessOutput must show match banner when process has match"""
    return ok('match-banner' in JS and 'match_text' in JS and
              'has_match' in JS, "match banner not implemented in loadProcessOutput")
test("T1.5: match banner shown at top of process output when match exists", test_t5_match_banner_in_output)

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

def test_n1_nse_parallelism():
    """NSE stage command must include --min-parallelism"""
    import inspect
    src = inspect.getsource(wc.runStagedNmap)
    return ok('min-parallelism' in src, "--min-parallelism not in NSE stage command")
test("N1.1: NSE stage uses --min-parallelism for concurrent script execution", test_n1_nse_parallelism)

def test_n2_nse_script_timeout():
    """NSE stage must include --script-timeout to prevent hanging scripts"""
    import inspect
    src = inspect.getsource(wc.runStagedNmap)
    return ok('script-timeout' in src, "--script-timeout not in NSE stage command")
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
    return ok('close-x' in JS and '/api/processes' in JS)
test("R4: Phase 2 close-tab (close-x) still present", test_r4_phase2_close_intact)

def test_r5_phase3_sort_intact():
    return ok('_hostSort' in JS and '_procSort' in JS and '_drawHosts' in JS)
test("R5: Phase 3 sorting still intact", test_r5_phase3_sort_intact)

def test_r6_phase4_filters_intact():
    return ok('_filters' in JS and '_drawHosts' in JS)
test("R6: Phase 4 filters still intact", test_r6_phase4_filters_intact)

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
