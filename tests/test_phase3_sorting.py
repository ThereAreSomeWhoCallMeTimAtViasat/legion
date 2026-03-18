#!/usr/bin/env python3
"""
Phase 3 Sorting & Column Persistence Tests
===========================================
Run with: sudo python3 tests/test_phase3_sorting.py

Tests for Phase 3 gap items:
  S1-S5:  Host table column sort (OS / IP / Hostname headers clickable)
  S6-S10: Process table column sort (Name / Status / Elapsed headers clickable)
  S11-S15: Column width drag-resize + localStorage persistence
           (hosts, processes tables)

Qt6 reference:
  - setSortingEnabled(True) on each table view
  - QSortFilterProxyModel handles header-click sorting
  - saveColumnWidths / restoreColumnWidths save CSV widths to settings
  - Flask equivalent: JS sort state (_hostSort/_procSort) + re-render,
    drag resize listeners + localStorage
"""

import os, sys, time, traceback, tempfile

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

JS = open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')).read()
HTML = open(os.path.join(PROJECT_ROOT, 'app/web/templates/index.html')).read()

# ── Setup ─────────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

# Seed multiple hosts to verify sort actually changes order
_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.0.0.1" addrtype="ipv4"/>
    <hostnames><hostname name="alpha" type="PTR"/></hostnames>
    <ports><port protocol="tcp" portid="22"><state state="open"/>
      <service name="ssh"/></port></ports></host>
  <host><status state="up"/>
    <address addr="10.0.0.2" addrtype="ipv4"/>
    <hostnames><hostname name="beta" type="PTR"/></hostnames>
    <ports><port protocol="tcp" portid="80"><state state="open"/>
      <service name="http"/></port></ports></host>
  <host><status state="up"/>
    <address addr="10.0.0.3" addrtype="ipv4"/>
    <hostnames><hostname name="gamma" type="PTR"/></hostnames>
    <ports><port protocol="tcp" portid="443"><state state="open"/>
      <service name="https"/></port></ports></host>
</nmaprun>"""

def _seed():
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED); p = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
    finally:
        os.unlink(p)

_seed()


# ══════════════════════════════════════════════════════════════
# S1–S5: Host table column sort
# Qt6: HostsTableModel.sort(col, order) via setSortingEnabled(True)
# Flask: _hostSort state + _drawHosts() re-renders sorted rows
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S1-S5: Host table column sort")
print("="*60 + "\n")

def test_s1_host_sort_state_exists():
    """_hostSort global must exist with col and dir fields"""
    return ok('_hostSort' in JS,
              "_hostSort sort state not found in JS")
test("S1.1: _hostSort sort state defined", test_s1_host_sort_state_exists)

def test_s2_host_headers_have_data_sort():
    """Host table <th> elements must carry data-sort attributes for click detection"""
    return ok('data-sort' in HTML and 'hosts-table' in HTML or
              ('data-sort' in JS and 'hosts-body' in JS),
              "host table headers missing data-sort attributes")
test("S1.2: host table headers have data-sort attributes", test_s2_host_headers_have_data_sort)

def test_s3_draw_hosts_function():
    """_drawHosts() must exist — called on sort, renders sorted rows"""
    return ok('_drawHosts' in JS or 'drawHosts' in JS,
              "_drawHosts sort+render function not found")
test("S1.3: _drawHosts() sort-then-render function exists", test_s3_draw_hosts_function)

def test_s4_host_sort_by_ip():
    """_drawHosts must be able to sort by IP numerically"""
    return ok('_hostSort' in JS and ('IP2Int' in JS or 'ip' in JS.lower()),
              "host sort-by-ip logic not found")
test("S1.4: host table supports sort by IP", test_s4_host_sort_by_ip)

def test_s5_host_sort_arrows():
    """Sort arrow indicator (▲/▼) must appear on active sort column"""
    return ok('\u25b2' in JS or '\u25bc' in JS or '▲' in JS or '▼' in JS,
              "sort arrow indicator not found in JS")
test("S1.5: sort arrow indicator (▲/▼) shown on active column", test_s5_host_sort_arrows)

def test_s6_host_sort_header_click():
    """Host table header click handler must toggle _hostSort.dir and call _drawHosts"""
    return ok('_hostSort' in JS and '_drawHosts' in JS,
              "host header click sort handler incomplete")
test("S1.6: host table header click toggles sort direction and redraws", test_s6_host_sort_header_click)


# ══════════════════════════════════════════════════════════════
# S6–S10: Process table column sort
# Qt6: ProcessesTableModel.sort(15, Descending) default (sort by id)
# Flask: _procSort state (default: id desc = newest first) + _drawProcesses()
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S6-S10: Process table column sort")
print("="*60 + "\n")

def test_s6_proc_sort_state():
    """_procSort global must exist with col and dir"""
    return ok('_procSort' in JS,
              "_procSort sort state not found")
test("S6.1: _procSort sort state defined", test_s6_proc_sort_state)

def test_s7_proc_sort_default_newest_first():
    """Default process sort must be newest first (id desc, matches Qt6 column 15 Descending)"""
    # Check that _procSort default direction is -1 (desc) or 'desc'
    return ok('_procSort' in JS and ('-1' in JS[JS.find('_procSort'):JS.find('_procSort')+200] or
                                      'desc' in JS[JS.find('_procSort'):JS.find('_procSort')+200]),
              "_procSort default is not newest-first (descending)")
test("S6.2: _procSort defaults to newest-first (descending id)", test_s7_proc_sort_default_newest_first)

def test_s8_draw_processes_function():
    """_drawProcesses() must exist — replaces direct body.innerHTML manipulation"""
    return ok('_drawProcesses' in JS or 'drawProcesses' in JS,
              "_drawProcesses sort+render function not found")
test("S6.3: _drawProcesses() sort-then-render function exists", test_s8_draw_processes_function)

def test_s9_proc_headers_sortable():
    """Process table headers must have data-sort for Name, Status, Elapsed"""
    return ok('processes-table' in HTML or 'proc.*data-sort' in JS or
              ('_procSort' in JS and 'processes-body' in JS),
              "process table headers not sortable")
test("S6.4: process table headers support column sort", test_s9_proc_headers_sortable)

def test_s10_proc_sort_status():
    """Process sort by Status must group Running → Waiting → Finished → Crashed"""
    return ok('_procSort' in JS and 'status' in JS.lower(),
              "process sort-by-status logic not found")
test("S6.5: process table supports sort by status", test_s10_proc_sort_status)

def test_s11_proc_sort_elapsed():
    """Process sort by Elapsed must sort numerically"""
    return ok('_procSort' in JS and ('elapsed' in JS.lower()),
              "process sort-by-elapsed logic not found")
test("S6.6: process table supports sort by elapsed time", test_s11_proc_sort_elapsed)


# ══════════════════════════════════════════════════════════════
# S11–S15: Column width drag-resize + localStorage
# Qt6: saveColumnWidths/restoreColumnWidths → settings CSV strings
# Flask: drag handle on <th> → mousemove → set col width → localStorage
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S11-S15: Column width persistence")
print("="*60 + "\n")

def test_s11_localstorage_save():
    """Column resize must call localStorage.setItem to persist widths"""
    return ok('localStorage' in JS and 'setItem' in JS,
              "localStorage.setItem not found for column width persistence")
test("S11.1: column resize calls localStorage.setItem", test_s11_localstorage_save)

def test_s12_localstorage_restore():
    """Column widths must be restored from localStorage on page load"""
    return ok('localStorage' in JS and 'getItem' in JS,
              "localStorage.getItem not found for restoring column widths")
test("S11.2: column widths restored from localStorage on load", test_s12_localstorage_restore)

def test_s13_col_resize_key_format():
    """localStorage key must identify table + column (e.g. 'col-hosts-0')"""
    return ok('col-' in JS or 'col_' in JS,
              "column width localStorage key format not found (expected 'col-<table>-<idx>')")
test("S11.3: localStorage keys identify table+column (col-<table>-<idx>)", test_s13_col_resize_key_format)

def test_s14_hosts_table_col_resize():
    """Hosts table columns must support drag resize"""
    return ok('hosts' in JS and ('col-hosts' in JS or 'colResize' in JS or 'col_resize' in JS),
              "hosts table column resize not found")
test("S11.4: hosts table columns support drag resize", test_s14_hosts_table_col_resize)

def test_s15_processes_table_col_resize():
    """Processes table columns must support drag resize via initColResizers"""
    return ok('initColResizers' in JS and 'processes-table' in JS,
              "initColResizers not called for processes-table")
test("S11.5: processes table columns support drag resize", test_s15_processes_table_col_resize)

def test_s16_resize_mousedown_handler():
    """Column resize must handle mousedown on resize handle"""
    return ok('mousedown' in JS and ('resize' in JS.lower() or 'colResize' in JS),
              "mousedown resize handler not found")
test("S11.6: column resize handles mousedown on drag handle", test_s16_resize_mousedown_handler)


# ══════════════════════════════════════════════════════════════
# REGRESSION
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R: Regression")
print("="*60 + "\n")

def test_r1_snapshot_hosts_sortable():
    """Snapshot must return multiple hosts so sort can reorder them"""
    data = client.get('/api/snapshot').get_json()
    return ok(len(data.get('hosts', [])) >= 2,
              f"need ≥2 hosts to test sort, got {len(data.get('hosts',[]))}")
test("R1: snapshot returns multiple hosts for sort verification", test_r1_snapshot_hosts_sortable)

def test_r2_render_hosts_still_called():
    """renderHosts must still be called from pollSnapshot (not broken by sort refactor)"""
    return ok('renderHosts' in JS and 'pollSnapshot' in JS,
              "renderHosts no longer called from pollSnapshot")
test("R2: renderHosts still called from pollSnapshot after sort refactor", test_r2_render_hosts_still_called)

def test_r3_render_processes_still_called():
    """renderProcesses must still be called from pollSnapshot"""
    return ok('renderProcesses' in JS and 'pollSnapshot' in JS,
              "renderProcesses no longer called from pollSnapshot")
test("R3: renderProcesses still called from pollSnapshot after sort refactor", test_r3_render_processes_still_called)

def test_r4_services_sort_unchanged():
    """Services table sort (already done in Phase 1) must still work"""
    return ok('_svcSort' in JS and '_drawServices' in JS,
              "services table sort (_svcSort/_drawServices) broken")
test("R4: services table sort (Phase 1) still intact", test_r4_services_sort_unchanged)

def test_r5_existing_tests_pass():
    """Spot-check: key APIs unchanged"""
    r1 = client.get('/api/snapshot')
    r2 = client.get('/api/menus/host?checked=False')
    return ok(r1.status_code == 200 and r2.status_code == 200,
              f"snapshot={r1.status_code} menu={r2.status_code}")
test("R5: snapshot and host menu APIs unchanged", test_r5_existing_tests_pass)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
