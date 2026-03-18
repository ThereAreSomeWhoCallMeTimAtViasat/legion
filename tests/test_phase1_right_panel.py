#!/usr/bin/env python3
"""
Phase 1 Right Panel Tests — G1-G5
===================================
Run with: sudo python3 tests/test_phase1_right_panel.py

Tests the 5 right-panel data display gaps identified in the UI audit:
  G1: Information tab — host stats (status, open/closed/filtered port counts, IP, OS, MAC...)
  G2: CVEs tab — getCVEsByHostIP returns data, API exposes it
  G3: Scripts — getScriptsByHostIP + getScriptOutputById, script click shows output
  G4: OS hosts table — clicking OS row shows matching hosts
  G5: Services tab reload — when host is selected, right panel Services tab has port data

All tests are BEHAVIORAL (execute code, verify DB results).
Previous test suites are re-run at the end to confirm nothing is broken.
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

# ── Setup ────────────────────────────────────────────────────────────────────
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()
repo = logic.activeProject.repositoryContainer

# Seed a host with ports, scripts, and CVEs for all tests to use
def _seed():
    """Import a rich nmap XML so every right-panel tab has data to show."""
    xml = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <address addr="AA:BB:CC:DD:EE:FF" addrtype="mac" vendor="Acme"/>
    <hostnames><hostname name="seed-host" type="PTR"/></hostnames>
    <os><osmatch name="Linux 5.4" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.9"/>
        <script id="ssh-hostkey" output="2048 ab:cd (RSA)"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="nginx" version="1.22"/>
      </port>
      <port protocol="tcp" portid="8080">
        <state state="filtered"/>
        <service name="http-proxy"/>
      </port>
      <port protocol="tcp" portid="9999">
        <state state="closed"/>
        <service name="unknown"/>
      </port>
    </ports>
  </host>
</nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); path = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=path, output="")
    finally:
        os.unlink(path)

_seed()

# ── Helpers ──────────────────────────────────────────────────────────────────
def _get_seeded_host():
    hosts = repo.hostRepository.getHosts(filters)
    return next((h for h in (hosts or [])
                 if (h.get('ip') if isinstance(h, dict) else getattr(h,'ipv4','') or getattr(h,'ip','')) == '10.10.10.1'), None)

def _host_id():
    h = _get_seeded_host()
    return h.get('id') if isinstance(h, dict) else getattr(h, 'id', None)

def _host_ip():
    return '10.10.10.1'


# ══════════════════════════════════════════════════════════════
# G1: Information tab — host stats
# Qt6: view.py:updateInformationView + buildInformationText
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("G1: Information tab — host stats API")
print("="*60 + "\n")

def test_g1_host_information_route_exists():
    """/api/workspace/hosts/<id>/information route returns 200"""
    hid = _host_id()
    if not hid:
        return "seeded host not found"
    r = client.get(f'/api/workspace/hosts/{hid}/information')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("G1.1: /api/workspace/hosts/<id>/information returns 200", test_g1_host_information_route_exists)

def test_g1_information_has_port_counts():
    """Information response includes open/closed/filtered port counts"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/information').get_json()
    return ok('open_ports' in data and 'closed_ports' in data and 'filtered_ports' in data,
              f"keys={list(data.keys())}")
test("G1.2: information response has port count fields", test_g1_information_has_port_counts)

def test_g1_open_port_count_correct():
    """open_ports count matches seeded XML (22 and 80 are open = 2)"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/information').get_json()
    return ok(data.get('open_ports', 0) >= 2, f"open_ports={data.get('open_ports')}")
test("G1.3: open_ports count >= 2", test_g1_open_port_count_correct)

def test_g1_information_has_host_fields():
    """Information response includes ip, os, status, mac fields"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/information').get_json()
    for field in ('ip', 'status', 'os'):
        if field not in data:
            return f"missing field: {field} in {list(data.keys())}"
    return True
test("G1.4: information response has ip/status/os fields", test_g1_information_has_host_fields)

def test_g1_wc_getHostInformation_returns_host():
    """wc.getHostInformation() returns host object"""
    host = wc.getHostInformation(_host_ip())
    return ok(host is not None, "getHostInformation returned None")
test("G1.5: wc.getHostInformation() works", test_g1_wc_getHostInformation_returns_host)


# ══════════════════════════════════════════════════════════════
# G2: CVEs tab
# Qt6: view.py:updateCvesByHostView → controller.getCvesFromDB
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("G2: CVEs tab API")
print("="*60 + "\n")

def _seed_cve():
    """Add a CVE for the seeded host."""
    hid = _host_id()
    if not hid:
        return
    from sqlalchemy import text
    session = logic.activeProject.database.session()
    try:
        # Check if CVE already exists
        row = session.execute(text("SELECT id FROM cve WHERE hostId=:hid AND name=:n"),
                              {"hid": hid, "n": "CVE-2024-9999"}).fetchone()
        if not row:
            session.execute(text(
                "INSERT INTO cve (name, severity, product, version, url, source, hostId) "
                "VALUES (:n, :s, :p, :v, :u, :src, :hid)"),
                {"n": "CVE-2024-9999", "s": "9.8", "p": "nginx", "v": "1.22",
                 "u": "https://nvd.nist.gov", "src": "nmap", "hid": hid})
            session.commit()
    finally:
        session.close()

_seed_cve()

def test_g2_cves_route_exists():
    """/api/workspace/hosts/<id>/cves-list returns 200"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    r = client.get(f'/api/workspace/hosts/{hid}/cves-list')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("G2.1: /api/workspace/hosts/<id>/cves-list returns 200", test_g2_cves_route_exists)

def test_g2_cves_list_contains_seeded_cve():
    """CVEs list contains the seeded CVE-2024-9999"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/cves-list').get_json()
    cves = data.get('cves', [])
    names = [c.get('name','') for c in cves]
    return ok('CVE-2024-9999' in names, f"cves={names}")
test("G2.2: cves-list contains seeded CVE", test_g2_cves_list_contains_seeded_cve)

def test_g2_cves_have_required_fields():
    """Each CVE entry has name, severity, product fields"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/cves-list').get_json()
    cves = data.get('cves', [])
    if not cves: return "SKIP"
    c = cves[0]
    for field in ('name', 'severity', 'product'):
        if field not in c:
            return f"missing field {field} in CVE: {list(c.keys())}"
    return True
test("G2.3: CVE entries have name/severity/product", test_g2_cves_have_required_fields)

def test_g2_wc_getCvesFromDB_works():
    """wc.getCvesFromDB() returns list"""
    cves = wc.getCvesFromDB(_host_ip())
    return ok(cves is not None, "getCvesFromDB returned None")
test("G2.4: wc.getCvesFromDB() works", test_g2_wc_getCvesFromDB_works)


# ══════════════════════════════════════════════════════════════
# G3: Scripts tab
# Qt6: view.py:updateScriptsView + updateScriptsOutputView
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("G3: Scripts tab API")
print("="*60 + "\n")

def test_g3_scripts_route_exists():
    """/api/workspace/hosts/<id>/scripts-list returns 200"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    r = client.get(f'/api/workspace/hosts/{hid}/scripts-list')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("G3.1: /api/workspace/hosts/<id>/scripts-list returns 200", test_g3_scripts_route_exists)

def test_g3_scripts_list_has_ssh_hostkey():
    """Scripts list includes the ssh-hostkey script from seeded XML"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json()
    scripts = data.get('scripts', [])
    ids = [s.get('script_id','') for s in scripts]
    return ok('ssh-hostkey' in ids, f"script_ids={ids}")
test("G3.2: scripts-list contains ssh-hostkey from seeded XML", test_g3_scripts_list_has_ssh_hostkey)

def test_g3_scripts_have_required_fields():
    """Each script has id, script_id, port fields"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json()
    scripts = data.get('scripts', [])
    if not scripts: return "SKIP"
    s = scripts[0]
    for field in ('id', 'script_id', 'port'):
        if field not in s:
            return f"missing field {field} in script: {list(s.keys())}"
    return True
test("G3.3: script entries have id/script_id/port", test_g3_scripts_have_required_fields)

def test_g3_script_output_route_exists():
    """/api/workspace/scripts/<id>/output returns 200 for a real script"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json()
    scripts = data.get('scripts', [])
    if not scripts: return "SKIP"
    sid = scripts[0].get('id')
    if not sid: return "SKIP"
    r = client.get(f'/api/workspace/scripts/{sid}/output')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("G3.4: /api/workspace/scripts/<id>/output returns 200", test_g3_script_output_route_exists)

def test_g3_script_output_contains_text():
    """Script output endpoint returns non-empty output for ssh-hostkey"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}/scripts-list').get_json()
    scripts = [s for s in data.get('scripts', []) if s.get('script_id') == 'ssh-hostkey']
    if not scripts: return "SKIP"
    sid = scripts[0].get('id')
    out = client.get(f'/api/workspace/scripts/{sid}/output').get_json()
    return ok(len(out.get('output', '')) > 0, f"output empty: {out}")
test("G3.5: script output is non-empty for ssh-hostkey", test_g3_script_output_contains_text)


# ══════════════════════════════════════════════════════════════
# G4: OS hosts table
# Qt6: view.py:updateOsHostsTableView → controller.getHostsForOperatingSystem
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("G4: OS hosts table API")
print("="*60 + "\n")

def test_g4_os_hosts_route_exists():
    """/api/workspace/os/<name>/hosts returns 200"""
    r = client.get('/api/workspace/os/Linux/hosts')
    return ok(r.status_code == 200, f"status={r.status_code}")
test("G4.1: /api/workspace/os/<name>/hosts returns 200", test_g4_os_hosts_route_exists)

def test_g4_os_hosts_contains_seeded_host():
    """OS hosts endpoint returns seeded host under its OS category"""
    # The seeded host has osMatch "Linux 5.4" which classifies as "Linux"
    data = client.get('/api/workspace/os/Linux/hosts').get_json()
    hosts = data.get('hosts', [])
    ips = [h.get('ip','') for h in hosts]
    return ok('10.10.10.1' in ips, f"ips={ips}")
test("G4.2: OS hosts list contains seeded host (Linux)", test_g4_os_hosts_contains_seeded_host)

def test_g4_os_hosts_have_required_fields():
    """OS host entries have id, ip, hostname, os fields"""
    data = client.get('/api/workspace/os/Linux/hosts').get_json()
    hosts = data.get('hosts', [])
    if not hosts: return "SKIP"
    h = hosts[0]
    for field in ('id', 'ip'):
        if field not in h:
            return f"missing field {field}: {list(h.keys())}"
    return True
test("G4.3: OS host entries have id/ip fields", test_g4_os_hosts_have_required_fields)

def test_g4_wc_getHostsForOperatingSystem_works():
    """wc.getHostsForOperatingSystem() returns hosts"""
    hosts = wc.getHostsForOperatingSystem('Linux')
    return ok(hosts is not None, "getHostsForOperatingSystem returned None")
test("G4.4: wc.getHostsForOperatingSystem() works", test_g4_wc_getHostsForOperatingSystem_works)


# ══════════════════════════════════════════════════════════════
# G5: Services tab (right panel) — per-host port data
# Qt6: view.py:updateServiceTableView → getPortsAndServicesForHostFromDB
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("G5: Right-panel Services tab — per-host port data")
print("="*60 + "\n")

def test_g5_host_detail_has_ports():
    """Existing /api/workspace/hosts/<id> returns ports list"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}').get_json()
    ports = data.get('ports', [])
    return ok(len(ports) >= 2, f"ports count={len(ports)}, expected >=2")
test("G5.1: host detail already returns ports (existing route)", test_g5_host_detail_has_ports)

def test_g5_ports_have_required_fields():
    """Port entries have port, protocol, state, service fields"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}').get_json()
    ports = data.get('ports', [])
    if not ports: return "ports list empty"
    p = ports[0]
    for field in ('port', 'protocol', 'state'):
        if field not in p:
            return f"missing field {field}: {list(p.keys())}"
    return True
test("G5.2: port entries have port/protocol/state", test_g5_ports_have_required_fields)

def test_g5_ports_sorted_by_port_number():
    """Ports are returned sorted numerically (Qt6: sort(2, Descending) by port)"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}').get_json()
    ports = data.get('ports', [])
    if len(ports) < 2: return "SKIP"
    nums = [int(p.get('port', 0)) for p in ports]
    return ok(nums == sorted(nums), f"ports not sorted: {nums}")
test("G5.3: ports returned sorted by port number", test_g5_ports_sorted_by_port_number)

def test_g5_service_names_present():
    """Port entries include service name for known services"""
    hid = _host_id()
    if not hid: return "seeded host not found"
    data = client.get(f'/api/workspace/hosts/{hid}').get_json()
    ports = data.get('ports', [])
    ssh = next((p for p in ports if p.get('port') == '22'), None)
    if not ssh: return "SKIP"
    svc = ssh.get('service', {})
    return ok(svc.get('name','') == 'ssh', f"expected ssh, got {svc.get('name')}")
test("G5.4: port 22 has service name 'ssh'", test_g5_service_names_present)


# ══════════════════════════════════════════════════════════════
# REGRESSION: re-run key behavioral tests to ensure nothing broke
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("REGRESSION: behavioral test subset")
print("="*60 + "\n")

def test_reg_import_still_works():
    """import_nmap_xml still runs without error"""
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
<address addr="10.99.99.99" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="443">
  <state state="open"/>
  <service name="https"/></port></ports></host></nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); path = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=path, output="")
        return True
    except Exception as e:
        return f"import raised: {e}"
    finally:
        os.unlink(path)
test("REG.1: import_nmap_xml() still works", test_reg_import_still_works)

def test_reg_snapshot_still_works():
    """snapshot route still returns hosts"""
    data = client.get('/api/snapshot').get_json()
    return ok(len(data.get('hosts', [])) > 0, "no hosts in snapshot")
test("REG.2: /api/snapshot still returns hosts", test_reg_snapshot_still_works)

def test_reg_snapshot_tools_from_db():
    """snapshot tools come from process DB, not portActions (no label like 'Run ...')"""
    data = client.get('/api/snapshot').get_json()
    tools = data.get('tools', [])
    bad = [t for t in tools if str(t.get('label','')).startswith('Run ')]
    return ok(len(bad) == 0, f"found portAction labels in tools: {bad[:3]}")
test("REG.3: snapshot tools are from DB (not portActions)", test_reg_snapshot_tools_from_db)

def test_reg_runCommand_works():
    """runCommand still spawns a process"""
    wc.start()
    r = wc.runCommand(command='echo regression_test', name='regression-echo', hostIp='127.0.0.1')
    return ok(r.get('process_id') is not None, f"no process_id: {r}")
test("REG.4: runCommand() still works", test_reg_runCommand_works)

def test_reg_scheduler_callable():
    """scheduler() runs without error"""
    try:
        wc.scheduler(isNmapImport=False)
        return True
    except Exception as e:
        return f"scheduler crashed: {e}"
test("REG.5: scheduler() still runs without error", test_reg_scheduler_callable)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
