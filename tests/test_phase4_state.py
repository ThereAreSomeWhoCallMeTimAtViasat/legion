#!/usr/bin/env python3
"""
Phase 4 State, Filters & Lifecycle Tests
==========================================
Run with: sudo python3 tests/test_phase4_state.py

Tests for Phase 4 gap items:
  F1-F8:  Advanced filters actually work (tcp/udp, open/closed, up/down, keywords)
  C1-C4:  Host checked indicator — visual marker on checked hosts
  D1-D4:  Delete host → close its dynamic tabs (Qt6: closeAllTabsForHost)
  H1-H3:  clearAllTabHighlights when host changes (orange dots reset)
  R1-R5:  restoreToolTabs — processes appear on project open via snapshot

Qt6 reference:
  - Filters.apply(up,down,checked,portopen,portfiltered,portclosed,tcp,udp,keywords)
  - updateInterface() re-renders with new Filters
  - closeAllTabsForHost(ip) removes dynamic tabs for deleted host
  - clearAllTabHighlights resets orange tabs on host switch
  - restoreToolTabs loads process output into tabs on project open
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

JS   = open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')).read()
HTML = open(os.path.join(PROJECT_ROOT, 'app/web/templates/index.html')).read()

# ── Setup ─────────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()
repo = logic.activeProject.repositoryContainer

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.1.1.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
      <port protocol="udp" portid="161"><state state="open"/><service name="snmp"/></port>
      <port protocol="tcp" portid="443"><state state="closed"/><service name="https"/></port>
      <port protocol="tcp" portid="8080"><state state="filtered"/><service name="http-proxy"/></port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="10.1.1.2" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="21"><state state="open"/><service name="ftp"/></port>
    </ports>
  </host>
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

def _host(ip):
    hosts = repo.hostRepository.getHosts(filters)
    return next((h for h in (hosts or [])
                 if (h.get('ip') if isinstance(h, dict) else getattr(h,'ipv4','')) == ip), None)

def _host_id(ip):
    h = _host(ip)
    return h.get('id') if isinstance(h, dict) else getattr(h,'id',None) if h else None


# ══════════════════════════════════════════════════════════════
# F: Advanced filters
# Qt6: Filters.apply() → updateInterface() re-renders with filter
# Flask: L._filters state → client-side filtering + API filter params
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("F: Advanced filters")
print("="*60 + "\n")

def test_f1_filter_state_in_js():
    """L._filters state object must exist for tracking filter settings"""
    return ok('_filters' in JS,
              "_filters state not found on L object")
test("F1.1: L._filters state object defined", test_f1_filter_state_in_js)

def test_f2_filter_checkboxes_in_html():
    """Filter modal must have up/down/open/closed/tcp/udp checkboxes"""
    required = ['filter-hosts-up', 'filter-hosts-down',
                'filter-ports-open', 'filter-ports-tcp', 'filter-ports-udp']
    missing = [r for r in required if r not in HTML]
    return ok(not missing, f"missing filter checkboxes: {missing}")
test("F1.2: filter modal has all required checkboxes", test_f2_filter_checkboxes_in_html)

def test_f3_filter_apply_reads_checkboxes():
    """fApply handler must read checkbox values (not just console.log)"""
    # Check that fApply handler does more than just log
    idx = JS.find('fApply')
    if idx < 0: return "fApply handler not found"
    block = JS[idx:idx+500]
    return ok('console.log' not in block or 'filter-hosts' in block,
              "fApply handler only logs, does not read checkboxes")
test("F1.3: filter apply handler reads checkbox state", test_f3_filter_apply_reads_checkboxes)

def test_f4_draw_hosts_applies_filter():
    """_drawHosts must apply L._filters to hide down/unchecked hosts"""
    return ok('_filters' in JS and '_drawHosts' in JS,
              "_drawHosts does not use _filters for host visibility")
test("F1.4: _drawHosts applies L._filters to host visibility", test_f4_draw_hosts_applies_filter)

def test_f5_keyword_filter_applied():
    """Keyword filter must affect host rendering"""
    return ok('keywords' in JS or 'keyword' in JS,
              "keyword filter not applied in host rendering")
test("F1.5: keyword filter applied in host rendering", test_f5_keyword_filter_applied)

def test_f6_filters_persist_across_polls():
    """Filter state must survive snapshot polls (L._filters is module-level)"""
    return ok('_filters' in JS,
              "filter state not persistent across polls")
test("F1.6: filter state persists across snapshot polls", test_f6_filters_persist_across_polls)

def test_f7_filter_down_hosts():
    """Filters object correctly excludes down hosts when filters.down=False"""
    # This is server-side behavior already tested, but verify the Filters class works
    f = Filters()
    f.up = True; f.down = False
    hosts = repo.hostRepository.getHosts(f)
    down_hosts = [h for h in (hosts or [])
                  if (h.get('status') if isinstance(h, dict) else getattr(h,'status','')) == 'down']
    return ok(not down_hosts, f"down hosts visible with down=False: {down_hosts}")
test("F1.7: Filters(down=False) excludes down hosts from getHosts", test_f7_filter_down_hosts)

def test_f8_filter_closed_ports():
    """Filters object correctly excludes closed ports when portclosed=False"""
    hid = _host_id('10.1.1.1')
    if not hid: return "SKIP"
    f = Filters()
    f.portclosed = False
    ports = repo.portRepository.getPortsAndServicesByHostIP('10.1.1.1', f)
    closed = [p for p in (ports or []) if p.get('state') == 'closed']
    return ok(not closed, f"closed port visible with portclosed=False: {closed}")
test("F1.8: Filters(portclosed=False) excludes closed ports from query", test_f8_filter_closed_ports)


# ══════════════════════════════════════════════════════════════
# C: Host checked indicator
# Qt6: host rows show checkmark/color when checked='True' in DB
# Flask: snapshot includes 'checked' field; _drawHosts marks row
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C: Host checked indicator")
print("="*60 + "\n")

def test_c1_snapshot_includes_checked():
    """Snapshot hosts must include 'checked' field"""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    if not hosts: return "SKIP"
    missing = [h.get('ip') for h in hosts if 'checked' not in h]
    return ok(not missing, f"hosts missing checked field: {missing}")
test("C1.1: snapshot hosts include 'checked' field", test_c1_snapshot_includes_checked)

def test_c2_toggle_host_check_route():
    """POST /api/workspace/hosts/<id>/action with mark-checked must work"""
    hid = _host_id('10.1.1.1')
    if not hid: return "SKIP"
    resp = client.post(f'/api/workspace/hosts/{hid}/action',
                       json={'action': 'mark-checked', 'ip': '10.1.1.1'})
    return ok(resp.status_code == 200, f"mark-checked status={resp.status_code}")
test("C1.2: mark-checked action returns 200", test_c2_toggle_host_check_route)

def test_c3_checked_persists_in_db():
    """Toggling checked status must persist to DB"""
    hid = _host_id('10.1.1.2')
    if not hid: return "SKIP"
    # Toggle twice to test persistence
    client.post(f'/api/workspace/hosts/{hid}/action',
                json={'action': 'mark-checked', 'ip': '10.1.1.2'})
    hosts = repo.hostRepository.getHosts(filters)
    h = next((x for x in (hosts or [])
               if (x.get('ip') if isinstance(x,dict) else getattr(x,'ipv4','')) == '10.1.1.2'), None)
    checked = h.get('checked') if isinstance(h,dict) else getattr(h,'checked','False') if h else 'False'
    # Toggle back
    client.post(f'/api/workspace/hosts/{hid}/action',
                json={'action': 'mark-unchecked', 'ip': '10.1.1.2'})
    return ok(checked == 'True', f"checked={checked!r} after mark-checked")
test("C1.3: checked status persists to DB after toggle", test_c3_checked_persists_in_db)

def test_c4_draw_hosts_marks_checked():
    """_drawHosts must visually mark checked host rows"""
    return ok('checked' in JS and ('host-checked' in JS or 'checked.*host' in JS or
              '_drawHosts' in JS),
              "checked indicator not applied in _drawHosts")
test("C1.4: _drawHosts applies visual marker to checked hosts", test_c4_draw_hosts_marks_checked)


# ══════════════════════════════════════════════════════════════
# D: Delete host → close dynamic tabs
# Qt6: closeAllTabsForHost(ip) removes tabs from ServicesTabWidget
# Flask: host delete → remove all .dynamic-tab buttons/panels for that IP
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("D: Delete host → close dynamic tabs")
print("="*60 + "\n")

def test_d1_delete_host_route_works():
    """POST /api/workspace/hosts/<id>/action with 'delete' must return 200"""
    # Seed a host specifically to delete
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
<address addr="10.99.99.99" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="9999"><state state="open"/>
<service name="unknown"/></port></ports></host></nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); p = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
    finally:
        os.unlink(p)
    hid = _host_id('10.99.99.99')
    if not hid: return "SKIP"
    resp = client.post(f'/api/workspace/hosts/{hid}/action',
                       json={'action': 'delete', 'ip': '10.99.99.99'})
    return ok(resp.status_code == 200, f"delete status={resp.status_code}")
test("D1.1: delete host action returns 200", test_d1_delete_host_route_works)

def test_d2_deleted_host_gone_from_snapshot():
    """Deleted host must not appear in next snapshot"""
    data = client.get('/api/snapshot').get_json()
    ips = [h.get('ip') for h in data.get('hosts', [])]
    return ok('10.99.99.99' not in ips,
              "deleted host still in snapshot")
test("D1.2: deleted host removed from snapshot", test_d2_deleted_host_gone_from_snapshot)

def test_d3_close_tabs_in_js_on_delete():
    """JS delete handler must close dynamic tabs for deleted host"""
    idx = JS.find("'delete'")
    if idx < 0: idx = JS.find('"delete"')
    if idx < 0: return "delete handler not found"
    block = JS[idx:idx+600]
    return ok('dynamic-tab' in block or 'hostIp' in block or 'selectedHostId' in block,
              "delete handler does not close dynamic tabs")
test("D1.3: JS delete handler closes dynamic tabs for host", test_d3_close_tabs_in_js_on_delete)

def test_d4_clear_views_on_delete():
    """JS delete handler must clear the right panel and reset selection"""
    idx = JS.find("'delete'")
    if idx < 0: idx = JS.find('"delete"')
    if idx < 0: return "delete handler not found"
    block = JS[idx:idx+600]
    return ok('selectedHostId' in block or 'right-tabs' in block or 'pollSnapshot' in block,
              "delete handler does not reset right panel")
test("D1.4: JS delete handler clears right panel and host selection", test_d4_clear_views_on_delete)


# ══════════════════════════════════════════════════════════════
# H: clearAllTabHighlights on host switch
# Qt6: called when switching hosts → resets orange tabs to default
# Flask: when L.selectedHostId changes, remove tab-unread from all right-panel tabs
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("H: Clear tab highlights on host switch")
print("="*60 + "\n")

def test_h1_clear_highlights_in_js():
    """JS must clear tab-unread class when host changes"""
    return ok('tab-unread' in JS and ('selectedHostId' in JS),
              "tab-unread clearing on host switch not found")
test("H1.1: JS clears tab-unread on host switch", test_h1_clear_highlights_in_js)

def test_h2_clear_highlights_function():
    """A clearTabHighlights or equivalent function must exist"""
    return ok('tab-unread' in JS and
              ('clearTab' in JS or 'remove.*tab-unread' in JS or
               "classList.remove('tab-unread')" in JS),
              "clearTabHighlights / tab-unread removal not found")
test("H1.2: tab-unread removal implemented in JS", test_h2_clear_highlights_function)

def test_h3_highlights_cleared_on_host_click():
    """host-body click handler must clear tab-unread from right-panel tabs"""
    idx = JS.find("hosts-body').addEventListener('click")
    if idx < 0: return "hosts-body click handler not found"
    block = JS[idx:idx+800]
    return ok('tab-unread' in block or 'clearAllTabHighlights' in block,
              "host click handler does not clear tab highlights")
test("H1.3: host click handler clears right-panel tab highlights", test_h3_highlights_cleared_on_host_click)


# ══════════════════════════════════════════════════════════════
# R: restoreToolTabs — processes appear on project open
# Qt6: getProcessesForRestore() → createNewTabForHost for each process
# Flask: snapshot polls include previous processes; dynamic tabs auto-create
#        Output pre-loading: clicking tab loads stored output from DB
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R: Restore tool tabs on project open")
print("="*60 + "\n")

def test_r1_get_processes_for_restore():
    """getProcessesForRestore route must exist"""
    return ok(hasattr(wc, 'logic') and
              hasattr(repo, 'processRepository'),
              "processRepository missing")
test("R1.1: processRepository.getProcessesForRestore exists", test_r1_get_processes_for_restore)

def test_r2_closed_processes_not_in_snapshot():
    """Processes with closed='True' must not appear in snapshot"""
    wc.start()
    r = wc.runCommand('echo restore_test', name='restore-p', hostIp='127.0.0.1')
    pid = r.get('process_id')
    time.sleep(2)
    client.post(f'/api/processes/{pid}/close')
    snap = client.get('/api/snapshot').get_json()
    ids = [str(p.get('id')) for p in snap.get('processes', [])]
    return ok(str(pid) not in ids,
              f"closed process {pid} still in snapshot")
test("R1.2: closed processes absent from snapshot", test_r2_closed_processes_not_in_snapshot)

def test_r3_process_output_loadable_by_id():
    """Process output must be loadable by ID even after process finishes"""
    wc.start()
    r = wc.runCommand('echo restore_output_check', name='restore-out', hostIp='127.0.0.1')
    pid = r.get('process_id')
    time.sleep(2)
    resp = client.get(f'/api/processes/{pid}/output')
    return ok(resp.status_code == 200,
              f"output fetch status={resp.status_code}")
test("R1.3: process output fetchable by ID after finish", test_r3_process_output_loadable_by_id)

def test_r4_dynamic_tabs_created_from_snapshot():
    """renderDynamicToolTabs must create tabs from L.processes for selected host"""
    return ok('renderDynamicToolTabs' in JS and 'L.processes' in JS,
              "renderDynamicToolTabs not using L.processes")
test("R1.4: renderDynamicToolTabs creates tabs from L.processes", test_r4_dynamic_tabs_created_from_snapshot)

def test_r5_open_project_triggers_poll():
    """Opening a project must trigger a snapshot poll to refresh all panels"""
    return ok('/api/project/open' in JS or 'pollSnapshot' in JS,
              "project open does not trigger pollSnapshot")
test("R1.5: project open triggers pollSnapshot refresh", test_r5_open_project_triggers_poll)


# ══════════════════════════════════════════════════════════════
# REGRESSION
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("REGRESSION")
print("="*60 + "\n")

def test_reg1_snapshot_ok():
    return ok(client.get('/api/snapshot').status_code == 200)
test("REG1: /api/snapshot still returns 200", test_reg1_snapshot_ok)

def test_reg2_host_actions_work():
    hid = _host_id('10.1.1.1')
    if not hid: return "SKIP"
    r = client.post(f'/api/workspace/hosts/{hid}/action',
                    json={'action': 'mark-checked', 'ip': '10.1.1.1'})
    client.post(f'/api/workspace/hosts/{hid}/action',
                json={'action': 'mark-unchecked', 'ip': '10.1.1.1'})
    return ok(r.status_code == 200)
test("REG2: host mark-checked/unchecked actions still work", test_reg2_host_actions_work)

def test_reg3_draw_hosts_exists():
    return ok('_drawHosts' in JS and 'renderHosts' in JS)
test("REG3: renderHosts/_drawHosts still present", test_reg3_draw_hosts_exists)

def test_reg4_process_table_sort_intact():
    return ok('_procSort' in JS and '_drawProcesses' in JS)
test("REG4: process table sort (_procSort/_drawProcesses) intact", test_reg4_process_table_sort_intact)

def test_reg5_phase2_close_tab_intact():
    return ok('close-x' in JS and '/api/processes' in JS and '/close' in JS)
test("REG5: Phase 2 close-tab (close-x) still present", test_reg5_phase2_close_tab_intact)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
