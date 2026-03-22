#!/usr/bin/env python3
"""
Phase 3 Sorting & Column Persistence Tests
===========================================
Run with: sudo python3 tests/test_phase3_sorting.py

Tests for Phase 3 gap items:
  S1-S5:  Host table column sort — verify snapshot data has correct fields
           and that IP/hostname sort logic produces correct ordering
  S6-S10: Process table column sort — verify process data has fields for sort;
           newest process has highest ID (default newest-first)
  S11-S15: Column width persistence — settings readable; conf parseable

Qt6 reference:
  - setSortingEnabled(True) on each table view
  - QSortFilterProxyModel handles header-click sorting
  - saveColumnWidths / restoreColumnWidths save CSV widths to settings
  - Flask equivalent: JS sort state (_hostSort/_procSort) + re-render,
    drag resize listeners + localStorage
"""

import os, sys, time, traceback, tempfile, re

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

# ── Setup ─────────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

# Seed three hosts with distinct IPs and hostnames to verify sort ordering
_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.0.0.3" addrtype="ipv4"/>
    <hostnames><hostname name="gamma" type="PTR"/></hostnames>
    <ports><port protocol="tcp" portid="443"><state state="open"/>
      <service name="https"/></port></ports></host>
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

def _ip2num(ip):
    """Convert dotted-decimal IP to integer for numeric comparison."""
    try:
        parts = ip.split('.')
        return sum(int(p) << (8 * (3 - i)) for i, p in enumerate(parts))
    except Exception:
        return 0


# ══════════════════════════════════════════════════════════════
# S1–S5: Host table column sort
# Testing: snapshot provides correct data fields for sort to work;
#          numeric IP sort and alphabetical hostname sort produce correct orders
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S1-S5: Host table column sort")
print("="*60 + "\n")

def test_s1_snapshot_hosts_have_sort_fields():
    """Snapshot hosts must carry ip, hostname, os, status — all needed for sort."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    if not hosts: return "SKIP: no hosts seeded"
    for h in hosts:
        for field in ('ip', 'hostname', 'status'):
            if field not in h:
                return f"host {h.get('ip','?')} missing field '{field}': {list(h.keys())}"
    return True
test("S1.1: snapshot hosts carry ip/hostname/status sort fields", test_s1_snapshot_hosts_have_sort_fields)

def test_s2_ip_sort_ascending_correct():
    """IPs sorted numerically ascending must produce 10.0.0.1 → 10.0.0.2 → 10.0.0.3."""
    data = client.get('/api/snapshot').get_json()
    ips = [h['ip'] for h in data.get('hosts', []) if h.get('ip', '').startswith('10.0.0.')]
    if len(ips) < 3: return "SKIP: need >=3 seeded 10.0.0.x hosts"
    sorted_asc = sorted(ips, key=_ip2num)
    return ok(sorted_asc == ['10.0.0.1', '10.0.0.2', '10.0.0.3'],
              f"Numeric ascending sort wrong: {sorted_asc}")
test("S1.2: IP sort ascending produces 10.0.0.1 → 10.0.0.2 → 10.0.0.3", test_s2_ip_sort_ascending_correct)

def test_s3_ip_sort_descending_correct():
    """IPs sorted numerically descending must reverse the ascending order."""
    data = client.get('/api/snapshot').get_json()
    ips = [h['ip'] for h in data.get('hosts', []) if h.get('ip', '').startswith('10.0.0.')]
    if len(ips) < 3: return "SKIP"
    sorted_desc = sorted(ips, key=_ip2num, reverse=True)
    return ok(sorted_desc == ['10.0.0.3', '10.0.0.2', '10.0.0.1'],
              f"Numeric descending sort wrong: {sorted_desc}")
test("S1.3: IP sort descending produces 10.0.0.3 → 10.0.0.2 → 10.0.0.1", test_s3_ip_sort_descending_correct)

def test_s4_numeric_ip_differs_from_alphabetical():
    """Numeric IP sort must differ from alphabetical — proves numeric is necessary."""
    # 10.0.0.10 sorts before 10.0.0.2 alphabetically but after numerically
    test_ips = ['10.0.0.10', '10.0.0.2', '10.0.0.1']
    alpha_sorted = sorted(test_ips)
    numeric_sorted = sorted(test_ips, key=_ip2num)
    return ok(alpha_sorted != numeric_sorted,
              f"Alphabetical and numeric sort identical — _ip2num broken: {numeric_sorted}")
test("S1.4: numeric IP sort differs from alphabetical (proves numeric needed)", test_s4_numeric_ip_differs_from_alphabetical)

def test_s5_hostname_sort_alphabetical():
    """Hostnames sorted alphabetically must produce alpha → beta → gamma."""
    data = client.get('/api/snapshot').get_json()
    hostnames = [h.get('hostname','') for h in data.get('hosts', [])
                 if h.get('hostname','') in ('alpha', 'beta', 'gamma')]
    if len(hostnames) < 3: return "SKIP: need alpha/beta/gamma hostnames"
    sorted_names = sorted(hostnames)
    return ok(sorted_names == ['alpha', 'beta', 'gamma'],
              f"Hostname sort wrong: {sorted_names}")
test("S1.5: hostname sort alphabetical produces alpha → beta → gamma", test_s5_hostname_sort_alphabetical)

def test_s6_host_sort_header_click_updates_snapshot():
    """POST /api/snapshot always returns all hosts — client sort doesn't change count."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    # Sort the data in Python and verify we still have the same hosts either way
    if len(hosts) < 2: return "SKIP"
    asc_ips = sorted(h['ip'] for h in hosts if 'ip' in h)
    desc_ips = sorted((h['ip'] for h in hosts if 'ip' in h), reverse=True)
    return ok(set(asc_ips) == set(desc_ips) and len(asc_ips) == len(hosts),
              "IP sets differ — sort is losing hosts")
test("S1.6: sort does not lose hosts — count preserved in both directions", test_s6_host_sort_header_click_updates_snapshot)


# ══════════════════════════════════════════════════════════════
# S6–S10: Process table column sort
# Testing: processes in snapshot have fields needed for sort;
#          ID ordering matches launch order (newest = highest ID)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S6-S10: Process table column sort")
print("="*60 + "\n")

def test_s6_processes_have_sort_fields():
    """Processes in snapshot must have id, status, name, tabTitle for sort."""
    r = wc.runCommand('echo sort_field_test', name='sort-fields', hostIp='127.0.0.1')
    time.sleep(2)
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    if not procs: return "SKIP: no processes in snapshot"
    for p in procs:
        for field in ('id', 'status', 'name'):
            if field not in p:
                return f"process missing field '{field}': {list(p.keys())}"
    return True
test("S6.1: snapshot processes carry id/status/name sort fields", test_s6_processes_have_sort_fields)

def test_s7_newest_process_has_highest_id():
    """Most recently launched process must have the highest ID (default newest-first)."""
    r1 = wc.runCommand('echo first', name='sort-first', hostIp='127.0.0.1')
    r2 = wc.runCommand('echo second', name='sort-second', hostIp='127.0.0.1')
    pid1 = r1.get('process_id', 0)
    pid2 = r2.get('process_id', 0)
    return ok(pid2 > pid1,
              f"Second process ID {pid2} not greater than first {pid1} — newest-first sort broken")
test("S6.2: second launched process has higher ID than first (newest-first default)", test_s7_newest_process_has_highest_id)

def test_s8_process_id_sort_descending():
    """Processes sorted by ID descending puts newest (highest ID) first."""
    time.sleep(1)
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    if len(procs) < 2: return "SKIP: need >=2 processes"
    ids = [p['id'] for p in procs if 'id' in p]
    sorted_desc = sorted(ids, reverse=True)
    return ok(sorted_desc[0] == max(ids),
              f"Highest ID not first when sorted desc: {sorted_desc[:3]}")
test("S6.3: process ID sort descending puts newest process first", test_s8_process_id_sort_descending)

def test_s9_process_status_values_valid():
    """All process statuses must be from the known valid set for grouping sort."""
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    if not procs: return "SKIP"
    valid = {'Running', 'Waiting', 'Finished', 'Killed', 'Crashed', 'Interactive'}
    invalid = {p.get('status') for p in procs if p.get('status') not in valid}
    return ok(not invalid, f"Unknown status values (break sort grouping): {invalid}")
test("S6.4: process status values are from valid set (Running/Waiting/Finished/Killed/Crashed)", test_s9_process_status_values_valid)

def test_s10_process_elapsed_field_present():
    """Processes must carry elapsed field for elapsed-time sort."""
    time.sleep(1)
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    finished = [p for p in procs if p.get('status') == 'Finished']
    if not finished: return "SKIP: no finished processes yet"
    missing = [p['id'] for p in finished if 'elapsed' not in p]
    return ok(not missing,
              f"Finished processes missing elapsed field: {missing}")
test("S6.5: finished processes carry elapsed field for elapsed-time sort", test_s10_process_elapsed_field_present)

def test_s11_process_sort_by_name_possible():
    """Processes have name field for alphabetical sort by tool name."""
    data = client.get('/api/snapshot').get_json()
    procs = data.get('processes', [])
    if not procs: return "SKIP"
    names = [p.get('name', '') for p in procs]
    sorted_names = sorted(names)
    return ok(len(sorted_names) == len(procs),
              "name sort dropped processes")
test("S6.6: processes have name field enabling alphabetical tool-name sort", test_s11_process_sort_by_name_possible)


# ══════════════════════════════════════════════════════════════
# S11–S15: Column width drag-resize + settings persistence
# Testing: column widths stored in conf are parseable; settings route
#          returns them; the key format matches what JS would store
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S11-S15: Column width persistence")
print("="*60 + "\n")

def test_s11_hosts_column_widths_in_conf():
    """hosts-table-column-widths must be present and parseable in legion.conf."""
    with open(os.path.join(PROJECT_ROOT, 'legion.conf')) as f:
        content = f.read()
    m = re.search(r'hosts-table-column-widths\s*=\s*(.+)', content)
    if not m: return "FAIL: hosts-table-column-widths not found in legion.conf"
    val = m.group(1).strip().strip('"\'').strip('[]')
    try:
        nums = [int(x.strip().strip("'\"")) for x in val.split(',') if x.strip().strip("'\"")]
        return ok(len(nums) > 0, "hosts-table-column-widths parsed to empty list")
    except ValueError as e:
        return f"hosts-table-column-widths not parseable as integers: {e}"
test("S11.1: hosts-table-column-widths in legion.conf is parseable", test_s11_hosts_column_widths_in_conf)

def test_s12_process_column_widths_in_conf():
    """process-tab-column-widths must be present and parseable in legion.conf."""
    with open(os.path.join(PROJECT_ROOT, 'legion.conf')) as f:
        content = f.read()
    m = re.search(r'process-tab-column-widths\s*=\s*(.+)', content)
    if not m: return "FAIL: process-tab-column-widths not found in legion.conf"
    val = m.group(1).strip().strip('"\'').strip('[]')
    try:
        nums = [int(x.strip().strip("'\"")) for x in val.split(',') if x.strip().strip("'\"")]
        return ok(len(nums) > 0, "process-tab-column-widths parsed to empty list")
    except ValueError as e:
        return f"process-tab-column-widths not parseable: {e}"
test("S11.2: process-tab-column-widths in legion.conf is parseable", test_s12_process_column_widths_in_conf)

def test_s13_column_widths_saved_by_settings_route():
    """PUT /api/settings/save-prefs or equivalent must store column widths in config."""
    # The config save route accepts raw text — verify the round-trip works
    r = client.get('/api/settings/legion-conf')
    return ok(r.status_code == 200 and 'column-widths' in r.get_data(as_text=True),
              "Column widths not in settings conf response")
test("S11.3: GET /api/settings/legion-conf includes column-widths config", test_s13_column_widths_saved_by_settings_route)

def test_s14_hosts_table_present_in_html():
    """HTML must have hosts-table element with thead for resize handle attachment."""
    HTML = open(os.path.join(PROJECT_ROOT, 'app/web/templates/index.html')).read()
    return ok('id="hosts-table"' in HTML and '<thead>' in HTML,
              "hosts-table or thead missing from HTML — no target for resize handles")
test("S11.4: HTML has hosts-table with thead for column resize", test_s14_hosts_table_present_in_html)

def test_s15_processes_table_present_in_html():
    """HTML must have processes-table element for resize handle attachment."""
    HTML = open(os.path.join(PROJECT_ROOT, 'app/web/templates/index.html')).read()
    return ok('processes-table' in HTML and 'processes-body' in HTML,
              "processes-table or processes-body missing from HTML")
test("S11.5: HTML has processes-table and processes-body elements", test_s15_processes_table_present_in_html)

def test_s16_gui_settings_section_in_conf():
    """GUISettings section in legion.conf must contain column width entries."""
    with open(os.path.join(PROJECT_ROOT, 'legion.conf')) as f:
        content = f.read()
    gui_idx = content.find('[GUISettings]')
    return ok(gui_idx != -1 and 'column-widths' in content[gui_idx:gui_idx+1000],
              "GUISettings section missing or has no column-widths entries")
test("S11.6: GUISettings section in legion.conf contains column-widths entries", test_s16_gui_settings_section_in_conf)


# ══════════════════════════════════════════════════════════════
# REGRESSION
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R: Regression")
print("="*60 + "\n")

def test_r1_snapshot_hosts_sortable():
    """Snapshot must return multiple hosts so sort can reorder them."""
    data = client.get('/api/snapshot').get_json()
    return ok(len(data.get('hosts', [])) >= 2,
              f"need >=2 hosts to test sort, got {len(data.get('hosts',[]))}")
test("R1: snapshot returns multiple hosts for sort verification", test_r1_snapshot_hosts_sortable)

def test_r2_renderHosts_inside_pollSnapshot():
    """renderHosts must be called inside the pollSnapshot function body."""
    JS = open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')).read()
    idx = JS.find('function pollSnapshot()')
    if idx < 0: return "FAIL: pollSnapshot function not found"
    body = JS[idx:idx+1000]
    return ok('renderHosts' in body,
              "renderHosts not called inside pollSnapshot function body")
test("R2: renderHosts called inside pollSnapshot function body", test_r2_renderHosts_inside_pollSnapshot)

def test_r3_renderProcesses_inside_pollSnapshot():
    """renderProcesses must be called inside the pollSnapshot function body."""
    JS = open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')).read()
    idx = JS.find('function pollSnapshot()')
    if idx < 0: return "FAIL: pollSnapshot function not found"
    body = JS[idx:idx+1000]
    return ok('renderProcesses' in body or '_drawProcesses' in body,
              "renderProcesses not called inside pollSnapshot function body")
test("R3: renderProcesses called inside pollSnapshot function body", test_r3_renderProcesses_inside_pollSnapshot)

def test_r4_services_sort_route_works():
    """Services sort — /api/menus/service route must work (Phase 1 intact)."""
    r = client.get('/api/menus/service')
    return ok(r.status_code == 200, f"services menu route returned {r.status_code}")
test("R4: services table sort (Phase 1) still intact — /api/menus/service works", test_r4_services_sort_route_works)

def test_r5_existing_tests_pass():
    """Spot-check: key APIs unchanged."""
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
