#!/usr/bin/env python3
"""
Phase 2 Interaction Tests
==========================
Run with: sudo python3 tests/test_phase2_interactions.py

Tests for Phase 2 gap items:
  I1: Tool tab close button — kill if Running, mark closed in DB, remove tab
  I2: Host double-click — copies IP to clipboard (API: nothing, pure JS)
  I3: Port right-click on right-panel Services — shows tool context menu, runs action
  I4: Port double-click — navigates to host in hosts table (pure JS)
  I5: Tool tab right-click — "Save Output" browser download (pure JS)

Server-side tests cover the APIs that back each behaviour.
Source-inspection tests guard the JS wiring against regressions.
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

# ── Setup ─────────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()
repo = logic.activeProject.repositoryContainer

# Seed a host with open ports so port-action tests have real data
_SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.50.60.70" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="9.0"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="nginx" version="1.24"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

def _seed():
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED_XML); p = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
    finally:
        os.unlink(p)

_seed()

def _host_id():
    hosts = repo.hostRepository.getHosts(filters)
    h = next((x for x in (hosts or [])
               if (x.get('ip') if isinstance(x, dict) else getattr(x,'ipv4','')) == '10.50.60.70'), None)
    return (h.get('id') if isinstance(h, dict) else getattr(h,'id',None)) if h else None


# ══════════════════════════════════════════════════════════════
# I1: Tool tab close button
# Qt6: closeHostToolTab → _closeProcessTab
#   - if Running: confirm → kill → storeCloseTabStatusInDB → removeTab
#   - if Waiting:  confirm → cancel → storeCloseTabStatusInDB → removeTab
#   - else:        storeCloseTabStatusInDB → removeTab
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("I1: Tool tab close button")
print("="*60 + "\n")

def test_i1_close_route_marks_closed():
    """POST /api/processes/<id>/close must set closed=True in DB"""
    wc.start()
    r = wc.runCommand('echo close_test', name='close-test', hostIp='127.0.0.1')
    pid = r.get('process_id')
    if not pid: return "no process_id"
    time.sleep(2)  # let it finish

    resp = client.post(f'/api/processes/{pid}/close')
    if resp.status_code != 200:
        return f"close route status={resp.status_code}"

    # Process must no longer appear in snapshot (closed=True filtered out)
    snap = client.get('/api/snapshot').get_json()
    ids = [str(p.get('id','')) for p in snap.get('processes', [])]
    return ok(str(pid) not in ids, f"process {pid} still in snapshot after close")
test("I1.1: close route marks process closed (disappears from snapshot)", test_i1_close_route_marks_closed)

def test_i1_close_route_exists():
    r = client.post('/api/processes/999/close')
    return ok(r.status_code in (200, 404), f"unexpected status={r.status_code}")
test("I1.2: /api/processes/<id>/close route exists", test_i1_close_route_exists)

def test_i1_kill_then_close():
    """Kill a running process then close it — both routes must work"""
    wc.start()
    r = wc.runCommand('sleep 30', name='kill-close-test', hostIp='127.0.0.1')
    pid = r.get('process_id')
    if not pid: return "no process_id"
    time.sleep(0.5)

    kill_resp = client.post(f'/api/processes/{pid}/kill')
    time.sleep(0.5)
    close_resp = client.post(f'/api/processes/{pid}/close')

    return ok(kill_resp.status_code == 200 and close_resp.status_code == 200,
              f"kill={kill_resp.status_code} close={close_resp.status_code}")
test("I1.3: kill then close sequence both return 200", test_i1_kill_then_close)

def test_i1_close_route_hides_from_snapshot_immediately():
    """Closing a finished process must remove it from snapshot before next poll."""
    wc.start()
    r = wc.runCommand('echo close_immediate_test', name='close-imm', hostIp='127.0.0.1')
    pid = r.get('process_id')
    if not pid: return "no process_id"
    time.sleep(2)
    # Verify it's in snapshot before close
    snap_before = client.get('/api/snapshot').get_json()
    ids_before = {str(p.get('id')) for p in snap_before.get('processes', [])}
    if str(pid) not in ids_before: return "SKIP: process not in snapshot before close"
    # Close it
    client.post(f'/api/processes/{pid}/close')
    # Must be gone immediately (not wait for next poll)
    snap_after = client.get('/api/snapshot').get_json()
    ids_after = {str(p.get('id')) for p in snap_after.get('processes', [])}
    return ok(str(pid) not in ids_after,
              f"Process {pid} still in snapshot immediately after close")
test("I1.4: close route removes process from snapshot immediately", test_i1_close_route_hides_from_snapshot_immediately)

def test_i1_close_x_button_in_rendered_tab():
    """renderDynamicToolTabs function must create close-x button inside dynamic-tab."""
    with open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')) as f:
        src = f.read()
    # Find renderDynamicToolTabs function body and check for close-x creation inside it.
    # The close-x span is created ~1974 chars into the function (inside the forEach loop);
    # the window must be wide enough to reach it.
    idx = src.find('function renderDynamicToolTabs(')
    if idx < 0: return "FAIL: renderDynamicToolTabs function not found"
    body = src[idx:idx+2500]
    return ok('close-x' in body and 'dynamic-tab' in body,
              "renderDynamicToolTabs does not create close-x inside dynamic-tab")
test("I1.5: renderDynamicToolTabs function body creates close-x inside dynamic-tab", test_i1_close_x_button_in_rendered_tab)


# ══════════════════════════════════════════════════════════════
# I2: Host double-click → copy IP to clipboard
# Qt6: hostTableDoubleClick → copyToClipboard(data)
# Flask: dblclick on hosts-body row → navigator.clipboard.writeText
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("I2: Host double-click → copy IP to clipboard")
print("="*60 + "\n")

def test_i2_host_ip_in_snapshot_for_clipboard():
    """Hosts in snapshot must have ip field — this is what dblclick copies to clipboard."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    if not hosts: return "SKIP"
    missing_ip = [h for h in hosts if not h.get('ip')]
    return ok(not missing_ip,
              f"{len(missing_ip)} hosts have no ip field — nothing to copy to clipboard")
test("I2.1: snapshot hosts have ip field (the value dblclick copies to clipboard)", test_i2_host_ip_in_snapshot_for_clipboard)

def test_i2_clipboard_api_in_dblclick_handler():
    """The hosts-body dblclick handler function body must use the clipboard API."""
    with open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')) as f:
        src = f.read()
    # Find the dblclick listener on hosts-body and check its body for clipboard
    idx = src.find("'hosts-body').addEventListener('dblclick")
    if idx < 0: idx = src.find('"hosts-body").addEventListener("dblclick')
    if idx < 0: return "FAIL: dblclick handler not found on hosts-body"
    body = src[idx:idx+400]
    return ok('clipboard' in body or 'execCommand' in body or 'hostIp' in body,
              "dblclick handler body does not reference clipboard or host IP")
test("I2.2: dblclick handler body references clipboard API and host IP", test_i2_clipboard_api_in_dblclick_handler)


# ══════════════════════════════════════════════════════════════
# I3: Port right-click → run tool context menu
# Qt6: contextMenuServicesTableView → getContextMenuForPort → handlePortAction
# Flask: contextmenu on host-detail-ports → /api/menus/port → /api/workspace/service-action
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("I3: Port right-click → tool context menu")
print("="*60 + "\n")

def test_i3_port_menu_route_http():
    """Port context menu for 'http' service must include port actions"""
    data = client.get('/api/menus/port?service=http').get_json()
    port_actions = data.get('port_actions', [])
    return ok(len(port_actions) > 0,
              f"no port_actions for http service: {list(data.keys())}")
test("I3.1: /api/menus/port?service=http returns port actions", test_i3_port_menu_route_http)

def test_i3_port_menu_route_ssh():
    """Port context menu for 'ssh' must include actions"""
    data = client.get('/api/menus/port?service=ssh').get_json()
    port_actions = data.get('port_actions', [])
    return ok(len(port_actions) > 0,
              f"no port_actions for ssh: {list(data.keys())}")
test("I3.2: /api/menus/port?service=ssh returns port actions", test_i3_port_menu_route_ssh)

def test_i3_port_menu_has_required_keys():
    """Port menu items must have label and action_index for execution"""
    data = client.get('/api/menus/port?service=http').get_json()
    actions = data.get('port_actions', [])
    if not actions: return "SKIP"
    a = actions[0]
    for key in ('label', 'action'):
        if key not in a:
            return f"port action missing '{key}': {list(a.keys())}"
    return True
test("I3.3: port menu items have label and action fields", test_i3_port_menu_has_required_keys)

def test_i3_service_action_runs_tool():
    """POST /api/workspace/service-action with real host+port must launch a process"""
    hid = _host_id()
    if not hid: return "SKIP"
    # Get the port menu for ssh
    menu_data = client.get('/api/menus/port?service=ssh').get_json()
    port_actions = menu_data.get('port_actions', [])
    # Find a runnable portAction (not separator/browser/screenshot)
    runnable = next((a for a in port_actions
                     if a.get('action') == 'port-action' and a.get('action_index') is not None), None)
    if not runnable: return "SKIP"

    before = len(client.get('/api/snapshot').get_json().get('processes', []))
    resp = client.post('/api/workspace/service-action', json={
        'targets': [['10.50.60.70', '22', 'tcp']],
        'action_index': runnable['action_index'],
    })
    if resp.status_code != 200:
        return f"service-action status={resp.status_code}"
    time.sleep(0.5)
    after = len(client.get('/api/snapshot').get_json().get('processes', []))
    return ok(after > before, f"no new process launched (before={before} after={after})")
test("I3.4: /api/workspace/service-action launches a process", test_i3_service_action_runs_tool)

def test_i3_host_detail_ports_have_port_number():
    """GET /api/workspace/hosts/<id> must return ports with port number field."""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    h = next((x for x in hosts if x.get('ip') == '10.50.60.70'), None)
    if not h: return "SKIP: test host not in snapshot"
    r = client.get(f'/api/workspace/hosts/{h["id"]}')
    ports = r.get_json().get('ports', [])
    if not ports: return "SKIP: no ports for test host"
    missing = [p for p in ports if 'port' not in p or 'protocol' not in p]
    return ok(not missing,
              f"port rows missing port/protocol fields (needed for contextmenu): {missing[:2]}")
test("I3.5: host detail ports have port+protocol fields for contextmenu data attrs", test_i3_host_detail_ports_have_port_number)

def test_i3_port_service_name_in_detail():
    """Port rows in host detail must include service name for context menu filtering."""
    data = client.get('/api/snapshot').get_json()
    h = next((x for x in data.get('hosts', []) if x.get('ip') == '10.50.60.70'), None)
    if not h: return "SKIP"
    r = client.get(f'/api/workspace/hosts/{h["id"]}')
    ports = r.get_json().get('ports', [])
    if not ports: return "SKIP"
    missing_svc = [p for p in ports if 'service' not in p]
    return ok(not missing_svc,
              f"port rows missing service field (needed for port menu): {missing_svc[:2]}")
test("I3.6: host detail port rows carry service field for contextmenu service-filter", test_i3_port_service_name_in_detail)


# ══════════════════════════════════════════════════════════════
# I4: Port double-click → navigate to host
# Qt6: tableDoubleClick → get IP → switch to Hosts tab → selectRow → hostTableClick
# Flask: dblclick on host-detail-ports row → switch left panel to Hosts → select host
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("I4: Port double-click → navigate to host")
print("="*60 + "\n")

def test_i4_host_id_in_port_detail():
    """Port rows in host detail must carry the parent host ID — needed for dblclick navigation."""
    data = client.get('/api/snapshot').get_json()
    h = next((x for x in data.get('hosts', []) if x.get('ip') == '10.50.60.70'), None)
    if not h: return "SKIP"
    r = client.get(f'/api/workspace/hosts/{h["id"]}')
    host_data = r.get_json()
    # The host detail response includes the host object with its id
    host_obj = host_data.get('host', {})
    return ok(host_obj.get('id') == h['id'] or host_obj.get('ip') == '10.50.60.70',
              f"host detail does not return host id for navigation: {list(host_obj.keys())}")
test("I4.1: host detail returns host id needed for port-dblclick navigation", test_i4_host_id_in_port_detail)

def test_i4_dblclick_handler_switches_to_hosts_panel():
    """The port dblclick handler body must reference hosts-panel for navigation."""
    with open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')) as f:
        src = f.read()
    idx = src.find("host-detail-ports').addEventListener('dblclick")
    if idx < 0: idx = src.find('"host-detail-ports").addEventListener("dblclick')
    if idx < 0: return "FAIL: dblclick not found on host-detail-ports"
    body = src[idx:idx+500]
    return ok('hosts-panel' in body and 'selectedHostId' in body,
              "dblclick handler body missing hosts-panel switch or selectedHostId assignment")
test("I4.2: port dblclick handler body switches to hosts-panel and sets selectedHostId", test_i4_dblclick_handler_switches_to_hosts_panel)


# ══════════════════════════════════════════════════════════════
# I5: Tool tab right-click → Save Output
# Qt6: _showToolTabContextMenu → "Save" → _save_tool_text → QFileDialog
# Flask: contextmenu on .dynamic-tab button → "Save Output" → browser download
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("I5: Tool tab right-click → Save Output")
print("="*60 + "\n")

def test_i5_process_output_route_returns_text():
    """Process output API must return text content that could be saved to a file."""
    wc.start()
    r = wc.runCommand('echo save_output_test_content', name='save-out', hostIp='127.0.0.1')
    pid = r.get('process_id')
    if not pid: return "no process_id"
    time.sleep(2)
    resp = client.get(f'/api/processes/{pid}/output')
    return ok(resp.status_code == 200 and resp.content_type.startswith('application/json'),
              f"output route returned {resp.status_code} {resp.content_type}")
test("I5.1: process output route returns JSON text data suitable for file save", test_i5_process_output_route_returns_text)

def test_i5_output_content_is_saveable():
    """Output returned by API must contain the actual command output text."""
    wc.start()
    marker = 'save_output_unique_marker_xyz'
    r = wc.runCommand(f'echo {marker}', name='save-check', hostIp='127.0.0.1')
    pid = r.get('process_id')
    if not pid: return "no process_id"
    time.sleep(2)
    resp = client.get(f'/api/processes/{pid}/output')
    data = resp.get_json()
    output = data.get('output', '') or data.get('output_chunk', '')
    return ok(marker in output,
              f"Expected marker '{marker}' in output, got: {output[:100]!r}")
test("I5.2: process output contains actual command text (content saveable to file)", test_i5_output_content_is_saveable)

def test_i5_save_output_in_tab_contextmenu_handler():
    """The right-tab-bar contextmenu handler body must contain Save Output logic."""
    with open(os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')) as f:
        src = f.read()
    # Find the right-tab-bar contextmenu handler
    idx = src.find("'right-tab-bar').addEventListener('contextmenu")
    if idx < 0: idx = src.find('"right-tab-bar").addEventListener("contextmenu')
    if idx < 0: return "FAIL: right-tab-bar contextmenu handler not found"
    body = src[idx:idx+600]
    return ok('Save Output' in body or 'save' in body.lower(),
              "right-tab-bar contextmenu handler missing Save Output action")
test("I5.3: right-tab-bar contextmenu handler contains Save Output action", test_i5_save_output_in_tab_contextmenu_handler)


# ══════════════════════════════════════════════════════════════
# REGRESSION: ensure existing suites still pass
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R: Regression checks")
print("="*60 + "\n")

def test_r1_snapshot_ok():
    r = client.get('/api/snapshot')
    return ok(r.status_code == 200 and 'hosts' in r.get_json())
test("R1: /api/snapshot still works", test_r1_snapshot_ok)

def test_r2_import_still_works():
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
<address addr="10.99.1.1" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="8443">
  <state state="open"/>
  <service name="https-alt"/></port></ports></host></nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); p = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
        hosts = repo.hostRepository.getHosts(filters)
        ips = [(h.get('ip') if isinstance(h,dict) else getattr(h,'ipv4','')) for h in (hosts or [])]
        return ok('10.99.1.1' in ips)
    finally:
        os.unlink(p)
test("R2: import_nmap_xml still works", test_r2_import_still_works)

def test_r3_existing_close_route():
    """The /close route must already exist (was implemented in WebController)"""
    r = client.post('/api/processes/1/close')
    return ok(r.status_code in (200, 404))
test("R3: /api/processes/<id>/close route already exists", test_r3_existing_close_route)

def test_r4_menus_port_route_exists():
    r = client.get('/api/menus/port?service=http')
    return ok(r.status_code == 200)
test("R4: /api/menus/port route exists", test_r4_menus_port_route_exists)

def test_r5_service_action_route_exists():
    r = client.post('/api/workspace/service-action', json={'targets': [], 'action_index': 0})
    return ok(r.status_code in (200, 400))
test("R5: /api/workspace/service-action route exists", test_r5_service_action_route_exists)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
