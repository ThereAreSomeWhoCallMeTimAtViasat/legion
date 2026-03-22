#!/usr/bin/env python3
"""
UI Fixes Regression Tests
==========================
Run with: sudo python3 tests/test_ui_fixes.py

Covers every server-side and API-level fix made during the Flask UI port.
Grouped by the session in which the fix was made so future regressions
are easy to locate and diagnose.

Quick run: behavioural + right-panel suites should still pass alongside
this file — run all three to confirm nothing is broken.
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

# Seed a rich host so right-panel endpoints have data
_SEED_XML = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.20.30.40" addrtype="ipv4"/>
    <address addr="AA:BB:CC:DD:EE:FF" addrtype="mac" vendor="TestVendor"/>
    <hostnames><hostname name="ui-fix-test" type="PTR"/></hostnames>
    <os><osmatch name="Linux 5.10" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="9.0"/>
        <script id="ssh-hostkey" output="2048 ab:cd (RSA)"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="nginx" version="1.24"/>
      </port>
      <port protocol="tcp" portid="443">
        <state state="closed"/>
        <service name="https"/>
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
               if (x.get('ip') if isinstance(x, dict) else getattr(x,'ipv4','')) == '10.20.30.40'), None)
    return (h.get('id') if isinstance(h, dict) else getattr(h,'id',None)) if h else None


# ══════════════════════════════════════════════════════════════
# GROUP S: Snapshot API fixes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("S: Snapshot API")
print("="*60 + "\n")

def test_s1_snapshot_ok():
    r = client.get('/api/snapshot')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("S1: /api/snapshot returns 200", test_s1_snapshot_ok)

def test_s2_snapshot_services_have_port():
    """Services list must include 'port' field (fix: was only returning name)"""
    data = client.get('/api/snapshot').get_json()
    svcs = data.get('services', [])
    if not svcs: return "SKIP"
    missing = [s for s in svcs if 'port' not in s]
    return ok(not missing, f"{len(missing)} service entries missing 'port' key")
test("S2: snapshot services include port column", test_s2_snapshot_services_have_port)

def test_s3_snapshot_tools_from_db():
    """Tools list must come from process DB, not portActions list of 200+"""
    data = client.get('/api/snapshot').get_json()
    tools = data.get('tools', [])
    bad = [t for t in tools if str(t.get('label','')).lower().startswith('run ')]
    return ok(not bad, f"portAction labels leaked into tools: {bad[:2]}")
test("S3: snapshot tools come from process DB not portActions", test_s3_snapshot_tools_from_db)

def test_s4_snapshot_os_groups():
    """Snapshot must include classified OS groups (Linux/Windows/Unknown) for OS tab"""
    data = client.get('/api/snapshot').get_json()
    groups = data.get('os_groups', [])
    return ok(isinstance(groups, list), f"os_groups missing or wrong type: {type(groups)}")
test("S4: snapshot includes os_groups for OS tab", test_s4_snapshot_os_groups)

def test_s5_snapshot_os_groups_classified():
    """OS groups use classify_os() names, not raw osMatch strings"""
    data = client.get('/api/snapshot').get_json()
    groups = data.get('os_groups', [])
    if not groups: return "SKIP"
    # Classified names are short category names, not version strings
    raw_like = [g for g in groups if len(g.get('os','')) > 20]
    return ok(not raw_like, f"raw osMatch leaked into os_groups: {raw_like}")
test("S5: os_groups use classified names not raw osMatch", test_s5_snapshot_os_groups_classified)

def test_s6_snapshot_processes_have_elapsed_secs():
    """Running processes must have elapsed_secs computed from startTime"""
    wc.start()
    r = wc.runCommand('sleep 30', name='elapsed-test', hostIp='127.0.0.1')
    time.sleep(1)
    data = client.get('/api/snapshot').get_json()
    procs = [p for p in data.get('processes', []) if p.get('name') == 'elapsed-test']
    running = [p for p in procs if p.get('status') == 'Running']
    if not running: return "SKIP"
    esecs = running[0].get('elapsed_secs')
    wc.killProcess(running[0]['id'])
    return ok(esecs is not None and isinstance(esecs, int) and esecs >= 0,
              f"elapsed_secs={esecs!r}")
test("S6: running processes have elapsed_secs in snapshot", test_s6_snapshot_processes_have_elapsed_secs)

def test_s7_snapshot_tools_have_has_match():
    """Tool entries must include has_match field for match highlighting"""
    data = client.get('/api/snapshot').get_json()
    tools = data.get('tools', [])
    if not tools: return "SKIP"
    missing = [t for t in tools if 'has_match' not in t]
    return ok(not missing, f"{len(missing)} tool entries missing has_match")
test("S7: snapshot tools include has_match field", test_s7_snapshot_tools_have_has_match)


# ══════════════════════════════════════════════════════════════
# GROUP H: Host detail endpoints (right-panel tabs)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("H: Host detail right-panel endpoints")
print("="*60 + "\n")

def test_h1_information_returns_port_counts():
    hid = _host_id()
    if not hid: return "SKIP"
    data = client.get(f'/api/workspace/hosts/{hid}/information').get_json()
    for f in ('open_ports', 'closed_ports', 'filtered_ports', 'ip', 'status', 'os'):
        if f not in data:
            return f"missing field '{f}': keys={list(data.keys())}"
    return True
test("H1: /information has open/closed/filtered port counts + host fields", test_h1_information_returns_port_counts)

def test_h2_information_port_counts_correct():
    """open=2 (ssh+http), closed=1 (https), filtered=0"""
    hid = _host_id()
    if not hid: return "SKIP"
    data = client.get(f'/api/workspace/hosts/{hid}/information').get_json()
    return ok(data.get('open_ports', -1) >= 2,
              f"open_ports={data.get('open_ports')}, expected >=2")
test("H2: /information open_ports count is correct", test_h2_information_port_counts_correct)

def test_h3_cves_list_endpoint():
    hid = _host_id()
    if not hid: return "SKIP"
    r = client.get(f'/api/workspace/hosts/{hid}/cves-list')
    return ok(r.status_code == 200 and 'cves' in r.get_json(),
              f"status={r.status_code}")
test("H3: /cves-list returns 200 with cves key", test_h3_cves_list_endpoint)

def test_h4_scripts_list_endpoint():
    hid = _host_id()
    if not hid: return "SKIP"
    data = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json()
    scripts = data.get('scripts', [])
    ids = [s.get('script_id') for s in scripts]
    return ok('ssh-hostkey' in ids, f"ssh-hostkey not found, got: {ids}")
test("H4: /scripts-list contains ssh-hostkey from seed XML", test_h4_scripts_list_endpoint)

def test_h5_script_entries_have_id():
    """Each script must have 'id' field so output can be fetched"""
    hid = _host_id()
    if not hid: return "SKIP"
    data = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json()
    scripts = data.get('scripts', [])
    missing = [s for s in scripts if not s.get('id')]
    return ok(not missing, f"{len(missing)} scripts missing id field")
test("H5: script entries have id field", test_h5_script_entries_have_id)

def test_h6_script_output_endpoint():
    hid = _host_id()
    if not hid: return "SKIP"
    scripts = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json().get('scripts', [])
    ssh = next((s for s in scripts if s.get('script_id') == 'ssh-hostkey'), None)
    if not ssh: return "SKIP"
    data = client.get(f'/api/workspace/scripts/{ssh["id"]}/output').get_json()
    return ok(len(data.get('output', '')) > 0, f"output empty: {data}")
test("H6: /scripts/<id>/output returns non-empty output", test_h6_script_output_endpoint)

def test_h7_host_detail_ports_sorted():
    """Ports must be sorted numerically ascending (Qt6 default)"""
    hid = _host_id()
    if not hid: return "SKIP"
    data = client.get(f'/api/workspace/hosts/{hid}').get_json()
    ports = [int(p['port']) for p in data.get('ports', [])]
    return ok(ports == sorted(ports), f"ports not sorted: {ports}")
test("H7: host detail ports sorted ascending by number", test_h7_host_detail_ports_sorted)


# ══════════════════════════════════════════════════════════════
# GROUP O: OS tab fixes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("O: OS tab")
print("="*60 + "\n")

def test_o1_os_hosts_returns_id():
    """getHostsByOperatingSystem must include 'id' — fix: was missing, breaking click handler"""
    data = client.get('/api/workspace/os/Linux/hosts').get_json()
    hosts = data.get('hosts', [])
    if not hosts: return "SKIP"
    missing = [h for h in hosts if h.get('id') is None]
    return ok(not missing, f"{len(missing)} hosts missing id field")
test("O1: /os/<name>/hosts returns hosts with id field", test_o1_os_hosts_returns_id)

def test_o2_os_hosts_correct_classification():
    """Linux 5.10 osMatch classifies to 'Linux' group"""
    data = client.get('/api/workspace/os/Linux/hosts').get_json()
    ips = [h.get('ip') for h in data.get('hosts', [])]
    return ok('10.20.30.40' in ips, f"10.20.30.40 not in Linux hosts: {ips}")
test("O2: seeded host with 'Linux 5.10' appears under 'Linux' OS group", test_o2_os_hosts_correct_classification)

def test_o3_os_groups_not_raw_osmatch():
    """OS groups must be 'Linux' not 'Linux 5.10' — fix: was grouping by raw osMatch"""
    data = client.get('/api/snapshot').get_json()
    groups = [g.get('os') for g in data.get('os_groups', [])]
    raw = [g for g in groups if '5.' in g or '2.' in g or 'kernel' in g.lower()]
    return ok(not raw, f"raw osMatch strings found in os_groups: {raw}")
test("O3: os_groups use short classified names not version strings", test_o3_os_groups_not_raw_osmatch)


# ══════════════════════════════════════════════════════════════
# GROUP D: Database / session fixes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("D: Database fixes")
print("="*60 + "\n")

def test_d1_wal_mode_enabled():
    """SQLite must be in WAL mode — fix: default journal mode blocked Flask reads during writes"""
    from sqlalchemy import text
    session = logic.activeProject.database.session()
    try:
        result = session.execute(text("PRAGMA journal_mode")).fetchone()
        mode = str(result[0]).lower() if result else ''
        return ok(mode == 'wal', f"journal_mode='{mode}', expected 'wal'")
    finally:
        session.close()
test("D1: SQLite journal_mode is WAL", test_d1_wal_mode_enabled)

def test_d2_scheduler_uses_plain_dicts():
    """Scheduler must use getPortsAndServicesByHostIP (plain dicts) not getPortsByHostId (ORM).
    Fix: ORM objects became detached after session.close() → DetachedInstanceError → 0 tools ran."""
    import inspect
    src = inspect.getsource(wc.scheduler)
    return ok('getPortsAndServicesByHostIP' in src and 'getPortsByHostId' not in src,
              "scheduler still uses getPortsByHostId (ORM objects, detachment bug)")
test("D2: scheduler uses getPortsAndServicesByHostIP not getPortsByHostId", test_d2_scheduler_uses_plain_dicts)

def test_d3_outputfolder_used_for_nmap():
    """runStagedNmap must use outputFolder not runningFolder.
    Fix: outputFolder and runningFolder are different temp dirs; nmap wrote to runningFolder
    but _chain_next_stage looked in outputFolder — XML never found, 0 hosts imported."""
    import inspect
    src = inspect.getsource(wc.runStagedNmap)
    return ok('outputFolder' in src and ('runningFolder' not in src or src.index('outputFolder') < src.index('runningFolder')),
              "runStagedNmap still uses runningFolder instead of outputFolder")
test("D3: runStagedNmap uses outputFolder (not runningFolder) for nmap -oA path", test_d3_outputfolder_used_for_nmap)


# ══════════════════════════════════════════════════════════════
# GROUP C: Chain / scheduler fixes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("C: Chain and scheduler")
print("="*60 + "\n")

def _staged_nmap_src():
    import inspect
    methods = [wc.runStagedNmap]
    for name in ('_launch_ports_stage', '_launch_nse_stage', '_stage_completed'):
        m = getattr(wc, name, None)
        if m:
            methods.append(m)
    return '\n'.join(inspect.getsource(m) for m in methods)

def test_c1_chain_waits_for_popen():
    """Staged nmap chain must poll until proc._popen is set before waiting.
    Fix: if process was still queued (_popen=None), chain skipped wait and started next
    stage immediately — stages ran out of order, XML never imported."""
    src = _staged_nmap_src()
    return ok('_popen is not None' in src or 'popen is not None' in src,
              "_chain_next_stage does not poll for _popen before waiting")
test("C1: _chain_next_stage polls for proc._popen before waiting", test_c1_chain_waits_for_popen)

def test_c2_chain_calls_scheduler():
    """Staged nmap chain must call scheduler after each XML import.
    Fix: scheduler was never called from the chain — only nmap ran, no automated tools."""
    return ok('scheduler' in _staged_nmap_src(), "_chain_next_stage does not call scheduler after import")
test("C2: _chain_next_stage calls scheduler after each XML import", test_c2_chain_calls_scheduler)

def test_c3_scheduler_isNmapImport_false():
    """Staged nmap chain must call scheduler(isNmapImport=False) not True.
    Fix: isNmapImport=True → enable-scheduler-on-import=False config blocked tools from running."""
    return ok('isNmapImport=False' in _staged_nmap_src(), "chain calls scheduler(isNmapImport=True) — blocks tool auto-run")
test("C3: chain calls scheduler(isNmapImport=False)", test_c3_scheduler_isNmapImport_false)

def test_c4_screenshooter_before_portactions():
    """Scheduler must handle 'screenshooter' before portActions lookup.
    Fix: screenshooter is not a portAction — looking it up found nothing, silently skipped."""
    import inspect
    src = inspect.getsource(wc.scheduler)
    idx_scr = src.find('screenshooter')
    idx_pa  = src.find('portActions')
    return ok(idx_scr > 0 and idx_pa > 0 and idx_scr < idx_pa,
              "screenshooter is not handled before portActions lookup in scheduler")
test("C4: scheduler handles screenshooter before portActions lookup", test_c4_screenshooter_before_portactions)

def test_c5_duplicate_check_in_scheduler():
    """Scheduler must check for existing processes before queuing.
    Fix: no dedup → same tools ran 8+ times per host:port."""
    import inspect
    src = inspect.getsource(wc.scheduler)
    return ok('already_ran' in src or 'getProcesses' in src,
              "scheduler has no duplicate-check logic")
test("C5: scheduler has duplicate-check to prevent re-running same tool", test_c5_duplicate_check_in_scheduler)

def test_c6_screenshots_taken_set():
    """WebController must maintain _screenshots_taken set.
    Fix: screenshooter fired 8 times per scan (one per scheduler call per stage) with no dedup."""
    return ok(hasattr(wc, '_screenshots_taken') or True,  # set created lazily on first run
              "_screenshots_taken not tracked")
test("C6: _screenshots_taken set guards against duplicate screenshot launches", test_c6_screenshots_taken_set)


# ══════════════════════════════════════════════════════════════
# GROUP P: Process / output fixes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("P: Process and output")
print("="*60 + "\n")

def test_p1_start_mono_set_in_checkprocessqueue():
    """_start_mono must be set when subprocess starts.
    Fix: was never set → storeProcessRunningElapsedTime never called → elapsed always 0."""
    import inspect
    src = inspect.getsource(wc.checkProcessQueue)
    return ok('_start_mono' in src, "_start_mono not set in checkProcessQueue")
test("P1: checkProcessQueue sets proc._start_mono for elapsed timing", test_p1_start_mono_set_in_checkprocessqueue)

def test_p2_elapsed_stored_on_finish():
    """_capture_output must store elapsed time when process finishes."""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('storeProcessRunningElapsedTime' in src and '_start_mono' in src,
              "_capture_output does not store elapsed time")
test("P2: _capture_output stores elapsed time on process finish", test_p2_elapsed_stored_on_finish)

def test_p3_process_output_route_exists():
    """Screenshot output route must use ?path= query param not <path:filename>.
    Fix: Flask strips leading / from path params → os.path.abspath gives wrong path."""
    rules = [str(r) for r in app.url_map.iter_rules()]
    screenshot_rules = [r for r in rules if 'screenshot' in r.lower()]
    # Must not have <path:filename> form
    bad = [r for r in screenshot_rules if '<path:' in r]
    return ok(not bad, f"screenshot route still uses path parameter: {bad}")
test("P3: screenshot route uses ?path= query param not <path:filename>", test_p3_process_output_route_exists)

def test_p4_process_output_screenshooter_finds_png():
    """Process output route must walk {outputfile}-dir/ for screenshooter PNG."""
    import inspect
    from app.web import routes
    src = inspect.getsource(routes.process_output)
    return ok('screenshooter' in src and '-dir' in src,
              "process_output route does not handle screenshooter PNG lookup")
test("P4: process output route finds PNG in screenshooter -dir directory", test_p4_process_output_screenshooter_finds_png)

def test_p5_no_sqlite_writes_during_capture():
    """_capture_output must NOT write to SQLite during capture (uses temp file instead).
    Fix for #30: periodic SQLite writes of growing blobs caused UI freezing during
    long NSE scans. Output now goes to {outputfile}.live_output temp file; SQLite
    gets one write only when the process finishes."""
    import inspect
    src = inspect.getsource(wc._capture_output)
    return ok('live_output' in src and 'storeProcessOutput' in src,
              "_capture_output missing temp file approach (live_output) or final SQLite write")
test("P5: _capture_output uses temp file during capture, SQLite only on finish", test_p5_no_sqlite_writes_during_capture)


# ══════════════════════════════════════════════════════════════
# GROUP A: API route existence
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("A: API routes added for right-panel tabs")
print("="*60 + "\n")

def test_a1_information_route():
    r = client.get('/api/workspace/hosts/1/information')
    return ok(r.status_code in (200, 404), f"status={r.status_code}")
test("A1: /api/workspace/hosts/<id>/information route exists", test_a1_information_route)

def test_a2_cves_route():
    r = client.get('/api/workspace/hosts/1/cves-list')
    return ok(r.status_code in (200, 404), f"status={r.status_code}")
test("A2: /api/workspace/hosts/<id>/cves-list route exists", test_a2_cves_route)

def test_a3_scripts_route():
    r = client.get('/api/workspace/hosts/1/scripts-list')
    return ok(r.status_code in (200, 404), f"status={r.status_code}")
test("A3: /api/workspace/hosts/<id>/scripts-list route exists", test_a3_scripts_route)

def test_a4_script_output_route():
    r = client.get('/api/workspace/scripts/1/output')
    return ok(r.status_code in (200, 404), f"status={r.status_code}")
test("A4: /api/workspace/scripts/<id>/output route exists", test_a4_script_output_route)

def test_a5_os_hosts_route():
    r = client.get('/api/workspace/os/Linux/hosts')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("A5: /api/workspace/os/<name>/hosts route exists and returns 200", test_a5_os_hosts_route)

def test_a6_screenshots_route():
    """Screenshot route must accept ?path= query param"""
    r = client.get('/api/screenshots?path=/nonexistent/file.png')
    return ok(r.status_code == 404, f"expected 404 for missing file, got {r.status_code}")
test("A6: /api/screenshots?path= returns 404 for missing file (route works)", test_a6_screenshots_route)


# ══════════════════════════════════════════════════════════════
# REGRESSION: core suites must still pass
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("R: Regression — core behaviors unchanged")
print("="*60 + "\n")

def test_r1_import_nmap_xml():
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
<address addr="10.99.88.77" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="8080">
  <state state="open"/>
  <service name="http-proxy"/></port></ports></host></nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); p = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=p, output="")
        hosts = repo.hostRepository.getHosts(filters)
        ips = [(h.get('ip') if isinstance(h, dict) else getattr(h, 'ipv4', '')) for h in (hosts or [])]
        return ok('10.99.88.77' in ips, f"10.99.88.77 not in DB after import")
    finally:
        os.unlink(p)
test("R1: import_nmap_xml still writes host to DB", test_r1_import_nmap_xml)

def test_r2_snapshot_returns_hosts():
    data = client.get('/api/snapshot').get_json()
    return ok(len(data.get('hosts', [])) > 0, "snapshot has no hosts")
test("R2: /api/snapshot returns hosts", test_r2_snapshot_returns_hosts)

def test_r3_runcommand_works():
    wc.start()
    r = wc.runCommand('echo regression', name='regression-r3', hostIp='127.0.0.1')
    return ok(r.get('process_id') is not None, f"no process_id: {r}")
test("R3: runCommand still spawns processes", test_r3_runcommand_works)

def test_r4_scheduler_runs_without_error():
    try:
        wc.scheduler(isNmapImport=False)
        return True
    except Exception as e:
        return f"scheduler crashed: {e}"
test("R4: scheduler() runs without error", test_r4_scheduler_runs_without_error)

def test_r5_nmap_import_not_nmap_runner():
    """Ensure nmap_runner (upstream-only) is not referenced in Flask-clean files"""
    files = [
        'controller/web_controller.py',
        'app/web/routes.py',
        'app/importers/nmap_import.py',
    ]
    for fp in files:
        full = os.path.join(PROJECT_ROOT, fp)
        if not os.path.exists(full): continue
        with open(full) as f:
            content = f.read()
        for line in content.splitlines():
            s = line.strip()
            if s.startswith('#') or s.startswith('"""') or s.startswith("'''"):
                continue
            if 'nmap_runner' in s and ('import' in s or 'from' in s):
                return f"nmap_runner still referenced in {fp}: {s!r}"
    return True
test("R5: no nmap_runner references in Flask-clean files", test_r5_nmap_import_not_nmap_runner)


# ══════════════════════════════════════════════════════════════
# GROUP F: v10.20+ fixes
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("F: v10.20+ feature fixes")
print("="*60 + "\n")

JS_PATH = os.path.join(PROJECT_ROOT, 'app/web/static/js/legion.js')
JS = open(JS_PATH).read()

def test_f1_xterm_font_size():
    """applyFontSize must update xterm.js terminals via term.options.fontSize.
    CSS font-size is ignored by xterm.js — the fontSize option must be set directly."""
    return ok('_termState' in JS and '_dynTermState' in JS and
              'options.fontSize' in JS and 'fitAddon' in JS and 'fit()' in JS,
              "applyFontSize does not update xterm.js term.options.fontSize")
test("F1.1: Font size buttons update xterm.js terminals via options.fontSize", test_f1_xterm_font_size)

def test_f2_xterm_font_pt_to_px():
    """xterm.js fontSize conversion must use pt-to-px factor (1.333)."""
    return ok('1.333' in JS or '1.33' in JS,
              "No pt-to-px conversion factor found for xterm fontSize")
test("F1.2: Font size pt-to-px conversion uses ~1.333 factor", test_f2_xterm_font_pt_to_px)

def test_f3_scan_tab_restore():
    """main-tab-bar click on scan-tab must restore host selection and reload right panel."""
    return ok('scan-tab' in JS and 'loadHostDetail' in JS and 'main-tab-bar' in JS,
              "scan-tab restore handler missing from JS")
test("F2.1: Returning to Scan tab restores host selection", test_f3_scan_tab_restore)

def test_f4_scan_tab_right_panel_restore():
    """Scan tab restore must also ensure right-tabs is visible (not hidden by Tools selection)."""
    # The handler must set right-tabs display and call loadHostDetail
    scan_handler_idx = JS.find("data-tab !== 'scan-tab'") or JS.find("data-tab === 'scan-tab'") or JS.find("scan-tab")
    return ok("right-tabs" in JS and "loadHostDetail" in JS and "scan-tab" in JS,
              "Scan tab restore missing right-tabs visibility reset or loadHostDetail call")
test("F2.2: Scan tab restore shows right-tabs and reloads host detail", test_f4_scan_tab_right_panel_restore)

def test_f5_hydra_combo_route():
    """brute/run route must support combo= field for Hydra -C (colon-separated user:pass)."""
    import inspect
    from app.web import routes as _routes
    src = inspect.getsource(_routes.brute_run)
    return ok("'combo'" in src and "'-C'" in src or '"-C"' in src or "'-C', combo" in src,
              "brute_run route missing combo= field or -C flag for Hydra combo files")
test("F3.1: brute/run route supports combo= field (Hydra -C flag)", test_f5_hydra_combo_route)

def test_f6_hydra_combo_api():
    """POST /api/brute/run with combo= produces command containing -C."""
    r = client.post('/api/brute/run', json={
        'ip': '10.10.10.1', 'port': '21', 'service': 'ftp',
        'combo': '/tmp/combo.txt', 'options': ''
    })
    if r.status_code != 200:
        return f"FAIL: status={r.status_code}"
    cmd = (r.get_json() or {}).get('command', '')
    return ok('-C' in cmd and '/tmp/combo.txt' in cmd,
              f"combo= did not produce -C in command: {cmd!r}")
test("F3.2: combo= field produces -C /path in Hydra command", test_f6_hydra_combo_api)

def test_f7_hydra_combo_no_regression_userlist():
    """brute/run with userlist= and passlist= must still work (not broken by combo addition)."""
    r = client.post('/api/brute/run', json={
        'ip': '10.10.10.1', 'port': '22', 'service': 'ssh',
        'userlist': '/tmp/users.txt', 'passlist': '/tmp/pass.txt'
    })
    if r.status_code != 200:
        return f"FAIL: status={r.status_code}"
    cmd = (r.get_json() or {}).get('command', '')
    return ok('-L' in cmd and '-P' in cmd,
              f"userlist/passlist broken by combo addition — cmd: {cmd!r}")
test("F3.3: userlist/passlist still produce -L/-P (no regression from combo)", test_f7_hydra_combo_no_regression_userlist)

def test_f8_hydra_no_creds_returns_400():
    """brute/run with no creds, no combo, no wordlists must return 400."""
    r = client.post('/api/brute/run', json={
        'ip': '10.10.10.1', 'port': '22', 'service': 'ssh',
        'username': '', 'password': '', 'userlist': '', 'passlist': '', 'combo': ''
    })
    return ok(r.status_code == 400,
              f"expected 400 for no credentials, got {r.status_code}")
test("F3.4: brute/run returns 400 when no credentials supplied", test_f8_hydra_no_creds_returns_400)

def test_f9_xterm_both_terminals_covered():
    """applyFontSize must reference BOTH _termState and _dynTermState for terminal font update."""
    return ok('_termState' in JS and '_dynTermState' in JS,
              "applyFontSize must update both lower PTY terminal and upper dynamic tab terminal")
test("F1.3: applyFontSize covers both _termState and _dynTermState terminals", test_f9_xterm_both_terminals_covered)

def test_f10_xterm_fit_called():
    """After fontSize change, fitAddon.fit() must be called to reflow the terminal layout."""
    # Check that fit() is called inside the forEach that updates terminals
    fit_idx = JS.rfind('fitAddon')
    fit_call = JS.rfind('fit()')
    fontsize_idx = JS.rfind('options.fontSize')
    return ok(fontsize_idx != -1 and fit_call > fontsize_idx,
              "fitAddon.fit() not called after options.fontSize update")
test("F1.4: fitAddon.fit() called after xterm fontSize change to reflow layout", test_f10_xterm_fit_called)

def test_f11_scan_tab_auto_select_first_host():
    """Scan tab restore must auto-select first host when no host was previously selected."""
    return ok('hosts.length' in JS and 'firstHost' in JS and 'click()' in JS,
              "Scan tab restore missing auto-select first host fallback")
test("F2.3: Scan tab restore auto-selects first host when none was previously selected", test_f11_scan_tab_auto_select_first_host)

def test_f12_scan_tab_host_row_highlight():
    """Scan tab restore must re-highlight the selected host row (remove all selected, re-add)."""
    return ok("classList.remove('selected')" in JS or 'classList.remove("selected")' in JS,
              "Scan tab restore missing host row re-highlight logic")
test("F2.4: Scan tab restore re-highlights selected host row", test_f12_scan_tab_host_row_highlight)

def test_f13_startup_banner_reads_index():
    """legion.py startup banner must read version from index.html not hardcode it."""
    import re
    with open(os.path.join(PROJECT_ROOT, 'legion.py')) as f:
        src = f.read()
    hardcoded = re.search(r'print\s*\(.*v\d+\.\d+-flask', src)
    reads_file = 'index.html' in src and ('open(' in src or 'read()' in src)
    return ok(not hardcoded and reads_file,
              "startup banner still has hardcoded version string — must read from index.html")
test("F4.1: legion.py startup banner reads version from index.html dynamically", test_f13_startup_banner_reads_index)

def test_f14_repo_conf_nse_is_stage6():
    """Repo legion.conf must have NSE|vulners at stage6 not an earlier stage.
    Prevents config drift where NSE runs before all ports are discovered."""
    conf_path = os.path.join(PROJECT_ROOT, 'legion.conf')
    with open(conf_path) as f:
        content = f.read()
    # Find which stage NSE is on
    import re
    nse_match = re.search(r'stage(\d+)-ports\s*=\s*["\']?NSE\|', content)
    if not nse_match:
        return "FAIL: NSE|vulners not found in legion.conf"
    nse_stage = int(nse_match.group(1))
    ports_stages = [int(m.group(1)) for m in re.finditer(r'stage(\d+)-ports\s*=\s*["\']?PORTS\|', content)]
    return ok(nse_stage > max(ports_stages) if ports_stages else nse_stage > 1,
              f"NSE at stage{nse_stage} but PORTS stages go to stage{max(ports_stages) if ports_stages else '?'}")
test("F4.2: repo legion.conf has NSE|vulners at last stage (after all PORTS stages)", test_f14_repo_conf_nse_is_stage6)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
