#!/usr/bin/env python3
"""
Behavioral Tests — end-to-end execution, not just source inspection
====================================================================
Run with: sudo python3 tests/test_behavioral.py

These tests actually EXECUTE code and verify the DB results.
They catch errors that source-inspection tests miss, such as:
  - Wrong module names in imports
  - Runtime failures in spawned threads
  - Data not actually appearing in DB

Slower than unit tests (~30s) but essential for correctness.
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
        if r is None or r is True: PASS += 1; print(f"  \u2713 {name}"); return True
        elif r == 'SKIP': SKIP += 1; print(f"  \u2298 {name} (SKIP)"); return False
        else: FAIL += 1; print(f"  \u2717 {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""): return True if v else f"FAIL: {msg}"
def gt(a, t, msg=""): return True if a > t else f"expected > {t}, got {a} ({msg})"

# Setup
from app.web.testhelper import create_test_app
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()


# ══════════════════════════════════════════════════════════════
# B1: nmap XML import actually populates the DB
# This is the test that would have caught the nmap_runner bug.
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("B1: nmap XML import actually runs and populates DB")
print("="*60 + "\n")

def test_b1_xml_import_runs():
    """import_nmap_xml() actually executes without error"""
    import tempfile
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
<address addr="10.1.1.1" addrtype="ipv4"/>
<hostnames><hostname name="behavioral-test" type="PTR"/></hostnames>
<ports><port protocol="tcp" portid="22">
  <state state="open"/>
  <service name="ssh" product="OpenSSH" version="8.9"/>
</port></ports></host></nmaprun>"""
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml)
        xml_path = f.name
    try:
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output="")
        return True
    except Exception as e:
        return f"import_nmap_xml raised: {e}"
    finally:
        os.unlink(xml_path)
test("B1.1: import_nmap_xml() runs without exception", test_b1_xml_import_runs)

def test_b1_host_in_db():
    """After XML import, host actually appears in DB"""
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    ips = [(h.get('ip') if isinstance(h,dict) else getattr(h,'ipv4','') or getattr(h,'ip',''))
           for h in (hosts or [])]
    return ok('10.1.1.1' in ips, f"10.1.1.1 not in DB, got: {ips}")
test("B1.2: Imported host appears in DB", test_b1_host_in_db)

def test_b1_port_in_db():
    """After XML import, port 22 appears for the host"""
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    host = next((h for h in (hosts or []) if
                 (h.get('ip') if isinstance(h,dict) else getattr(h,'ipv4','')) == '10.1.1.1'), None)
    if not host:
        return "host not found"
    hid = host.get('id') if isinstance(host,dict) else getattr(host,'id',None)
    ports = logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(hid)
    port_nums = [str(getattr(p,'portId','')) for p in (ports or [])]
    return ok('22' in port_nums, f"port 22 not found, got: {port_nums}")
test("B1.3: Port 22 appears in DB after import", test_b1_port_in_db)

def test_b1_via_snapshot_api():
    """Imported host visible via /api/snapshot"""
    data = client.get('/api/snapshot').get_json()
    hosts = data.get('hosts', [])
    ips = [h.get('ip','') for h in hosts]
    return ok('10.1.1.1' in ips, f"10.1.1.1 not in snapshot, got: {ips}")
test("B1.4: Imported host visible in /api/snapshot", test_b1_via_snapshot_api)


# ══════════════════════════════════════════════════════════════
# B2: runCommand actually executes and captures output
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("B2: runCommand actually executes and captures output")
print("="*60 + "\n")

def test_b2_command_runs():
    """runCommand actually spawns a process"""
    wc.start()
    result = wc.runCommand(command='echo behavioral_test_output',
                           name='behavioral-echo', hostIp='127.0.0.1')
    return ok(result.get('process_id') is not None, f"no process_id: {result}")
test("B2.1: runCommand spawns process", test_b2_command_runs)

def test_b2_output_captured():
    """Process output actually appears in DB after completion"""
    wc.start()
    result = wc.runCommand(command='echo unique_behavioral_marker_12345',
                           name='behavioral-capture', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    time.sleep(3)  # wait for process to finish and output to flush

    from sqlalchemy import text
    session = logic.activeProject.database.session()
    try:
        row = session.execute(
            text("SELECT output FROM process_output WHERE processId = :pid"),
            {"pid": proc_id}).fetchone()
        output = str(row[0] or '') if row else ''
    finally:
        session.close()

    return ok('unique_behavioral_marker_12345' in output,
              f"marker not in output (len={len(output)}): {output[:100]!r}")
test("B2.2: Process output captured in DB", test_b2_output_captured)

def test_b2_status_finished():
    """Process status becomes Finished after completion"""
    wc.start()
    result = wc.runCommand(command='echo status_test',
                           name='behavioral-status', hostIp='127.0.0.1')
    proc_id = result.get('process_id')
    time.sleep(3)

    repo = logic.activeProject.repositoryContainer.processRepository
    proc = repo.getProcessById(proc_id)
    return ok(proc and proc.get('status') == 'Finished',
              f"status={proc.get('status') if proc else 'NOT FOUND'}")
test("B2.3: Process status becomes Finished", test_b2_status_finished)


# ══════════════════════════════════════════════════════════════
# B3: Staged nmap chain — each stage actually imports XML
# This is THE test that would have caught the nmap_runner bug.
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("B3: Staged nmap XML import chain (the critical path)")
print("="*60 + "\n")

def test_b3_stage_chain_import_callable():
    """The function called by runStagedNmap's chain is importable"""
    try:
        from app.importers.nmap_import import import_nmap_xml
        return ok(callable(import_nmap_xml))
    except ImportError as e:
        return f"IMPORT ERROR: {e} — this is the bug that was missed!"
test("B3.1: runStagedNmap chain import is callable (not nmap_runner!)", test_b3_stage_chain_import_callable)

def test_b3_chain_uses_correct_module():
    """runStagedNmap chain actually calls nmap_import, not nmap_runner.
    nmap_import may live in the helper methods (_launch_ports_stage / _launch_nse_stage)
    after the parallel refactor, so check all staged-nmap methods."""
    import inspect
    methods = [wc.runStagedNmap]
    for name in ('_launch_ports_stage', '_launch_nse_stage', '_stage_completed'):
        m = getattr(wc, name, None)
        if m:
            methods.append(m)
    combined = '\n'.join(inspect.getsource(m) for m in methods)
    if 'nmap_runner' in combined:
        return "FAIL: staged nmap chain still references nmap_runner (upstream module)"
    return ok('nmap_import' in combined, "staged nmap chain should reference nmap_import")
test("B3.2: runStagedNmap uses nmap_import not nmap_runner", test_b3_chain_uses_correct_module)

def test_b3_capture_output_uses_correct_module():
    """_capture_output calls nmap_import, not nmap_runner"""
    import inspect
    src = inspect.getsource(wc._capture_output)
    if 'nmap_runner' in src:
        return "FAIL: _capture_output still references nmap_runner"
    return ok('nmap_import' in src, "_capture_output should reference nmap_import")
test("B3.3: _capture_output uses nmap_import not nmap_runner", test_b3_capture_output_uses_correct_module)

def test_b3_stage_xml_import_actually_works():
    """Simulate what the stage chain does: import XML, verify hosts appear"""
    import tempfile
    xml = """<?xml version="1.0"?>
<nmaprun><host><status state="up"/>
<address addr="10.2.2.2" addrtype="ipv4"/>
<ports><port protocol="tcp" portid="80">
  <state state="open"/>
  <service name="http" product="nginx" version="1.22"/>
</port></ports></host></nmaprun>"""

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(xml); xml_path = f.name

    try:
        # This is exactly what _chain_next_stage does
        from app.importers.nmap_import import import_nmap_xml
        import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output="")
    except Exception as e:
        return f"Stage chain import failed: {e}"
    finally:
        os.unlink(xml_path)

    # Verify host appeared
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    ips = [(h.get('ip') if isinstance(h,dict) else getattr(h,'ipv4','') or getattr(h,'ip',''))
           for h in (hosts or [])]
    return ok('10.2.2.2' in ips, f"Stage chain host not in DB: {ips}")
test("B3.4: Stage chain XML import actually populates DB", test_b3_stage_xml_import_actually_works)


# ══════════════════════════════════════════════════════════════
# B4: No references to upstream-only modules anywhere
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("B4: No upstream-only module references")
print("="*60 + "\n")

UPSTREAM_ONLY = [
    'nmap_runner',          # upstream Qt-free nmap runner (not in flask-clean)
    'app.web.runtime',      # upstream 6500-line reimplementation
    'app.web.bootstrap',    # upstream app factory
    'WebRuntime',           # upstream runtime class
]

FLASK_CLEAN_FILES = [
    'controller/web_controller.py',
    'app/web/routes.py',
    'app/importers/nmap_import.py',
    'app/settings.py',
    'app/core/ini_settings.py',
]

def make_upstream_test(module_name):
    def fn():
        for filepath in FLASK_CLEAN_FILES:
            full = os.path.join(PROJECT_ROOT, filepath)
            if not os.path.exists(full):
                continue
            with open(full) as f:
                content = f.read()
            # Skip comments and docstrings (rough check: look for actual imports)
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if module_name in stripped and ('import' in stripped or 'from' in stripped):
                    return f"Found '{module_name}' import in {filepath}: {stripped!r}"
        return True
    return fn

for mod in UPSTREAM_ONLY:
    test(f"B4: No '{mod}' import in Flask-clean files", make_upstream_test(mod))


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
