#!/usr/bin/env python3
"""
WebController Test Plan
=======================
Tests that your Qt6 controller logic works when called from Flask
WITHOUT any Qt dependencies. Run with:

    sudo python3 tests/test_webcontroller.py

Three tiers:
  Tier 1: Pure logic (DB queries, settings) — no Qt needed at all
  Tier 2: QMenu → JSON (context menus as data, not Qt widgets)
  Tier 3: QProcess → subprocess (tool execution without Qt)
"""

import os
import sys
import traceback

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# ── Test infrastructure ──

PASS = 0
FAIL = 0
SKIP = 0

def test(name, fn):
    """Run a single test, print result."""
    global PASS, FAIL, SKIP
    try:
        result = fn()
        if result is None or result is True:
            PASS += 1
            print(f"  ✓ {name}")
            return True
        elif result == 'SKIP':
            SKIP += 1
            print(f"  ⊘ {name} (SKIPPED)")
            return False
        else:
            FAIL += 1
            print(f"  ✗ {name}: {result}")
            return False
    except Exception as e:
        FAIL += 1
        print(f"  ✗ {name}: EXCEPTION: {e}")
        traceback.print_exc()
        return False

def assert_eq(actual, expected, msg=""):
    if actual != expected:
        return f"expected {expected!r}, got {actual!r}" + (f" ({msg})" if msg else "")
    return True

def assert_true(val, msg=""):
    if not val:
        return f"expected truthy, got {val!r}" + (f" ({msg})" if msg else "")
    return True

def assert_gt(actual, threshold, msg=""):
    if actual <= threshold:
        return f"expected > {threshold}, got {actual}" + (f" ({msg})" if msg else "")
    return True

def summary():
    total = PASS + FAIL + SKIP
    print(f"\n{'='*60}")
    print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
    print(f"{'='*60}")
    return FAIL == 0


# ══════════════════════════════════════════════════════════════
# TIER 1: Pure Logic — your code works without Qt
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("TIER 1: Pure Logic (zero Qt dependencies)")
print("="*60 + "\n")

# ── 1.1: Core imports work without Qt ──

_shell = None
_logic = None
_settings = None
_app_settings = None
_filters = None

def test_import_shell():
    global _shell
    from app.shell.DefaultShell import DefaultShell
    _shell = DefaultShell()
    return assert_true(_shell is not None, "DefaultShell created")

def test_import_repository_factory():
    from db.RepositoryFactory import RepositoryFactory
    return assert_true(RepositoryFactory is not None)

def test_import_project_manager():
    from app.ProjectManager import ProjectManager
    return assert_true(ProjectManager is not None)

def test_import_logic():
    from app.logic import Logic
    return assert_true(Logic is not None)

def test_import_settings():
    global _app_settings, _settings
    from app.settings import AppSettings, Settings
    _app_settings = AppSettings()
    _settings = Settings(_app_settings)
    return assert_true(_settings is not None)

def test_import_filters():
    global _filters
    from app.auxiliary import Filters
    _filters = Filters()
    return assert_true(_filters is not None)

test("Import DefaultShell", test_import_shell)
test("Import RepositoryFactory", test_import_repository_factory)
test("Import ProjectManager", test_import_project_manager)
test("Import Logic", test_import_logic)
test("Import AppSettings + Settings", test_import_settings)
test("Import Filters", test_import_filters)

# ── 1.2: Create a temporary project (same as controller.__init__ does) ──

def test_create_project():
    global _logic
    from app.shell.DefaultShell import DefaultShell
    from db.RepositoryFactory import RepositoryFactory
    from app.ProjectManager import ProjectManager
    from app.tools.ToolCoordinator import ToolCoordinator
    from app.tools.nmap.DefaultNmapExporter import DefaultNmapExporter
    from app.logic import Logic
    from app.logging.legionLog import getDbLogger, getAppLogger

    shell = DefaultShell()
    dbLog = getDbLogger()
    appLog = getAppLogger()
    repoFactory = RepositoryFactory(dbLog)
    pm = ProjectManager(shell, repoFactory, appLog)
    nmapExporter = DefaultNmapExporter(shell, appLog)
    tc = ToolCoordinator(shell, nmapExporter)
    _logic = Logic(shell, pm, tc)
    _logic.createNewTemporaryProject()
    return assert_true(_logic.activeProject is not None, "activeProject exists")

test("Create temporary project", test_create_project)

# ── 1.3: Query hosts from DB (controller.py:getHostsFromDB) ──

def test_get_hosts_empty():
    """controller.py:1376 — getHostsFromDB returns empty list for fresh project"""
    hosts = _logic.activeProject.repositoryContainer.hostRepository.getHosts(_filters)
    return assert_eq(len(hosts), 0, "fresh project has 0 hosts")

test("getHostsFromDB (empty project)", test_get_hosts_empty)

# ── 1.4: Settings loaded correctly (controller.py:loadSettings) ──

def test_settings_host_actions():
    """controller.py:292 — settings.hostActions loaded from legion.conf"""
    return assert_gt(len(_settings.hostActions), 0, "hostActions should not be empty")

def test_settings_port_actions():
    """controller.py:295 — settings.portActions loaded from legion.conf"""
    return assert_gt(len(_settings.portActions), 0, "portActions should not be empty")

def test_settings_port_action_structure():
    """Each portAction should be [label, tool_id, command, service_scope]"""
    action = _settings.portActions[0]
    return assert_true(len(action) >= 3, f"portAction has {len(action)} fields, need >= 3")

def test_settings_automated_attacks():
    """controller.py uses settings.automatedAttacks for scheduler"""
    return assert_gt(len(_settings.automatedAttacks), 0, "automatedAttacks should not be empty")

test("Settings: hostActions loaded", test_settings_host_actions)
test("Settings: portActions loaded", test_settings_port_actions)
test("Settings: portAction structure", test_settings_port_action_structure)
test("Settings: automatedAttacks loaded", test_settings_automated_attacks)

# ── 1.5: Repository methods work (the DB query methods controller.py delegates to) ──

def test_get_service_names():
    """controller.py:1379 — getServiceNamesFromDB"""
    services = _logic.activeProject.repositoryContainer.serviceRepository.getServiceNames(_filters)
    return assert_eq(len(services), 0, "fresh project has 0 services")

def test_get_processes():
    """controller.py:289 — process repository accessible"""
    repo = _logic.activeProject.repositoryContainer.processRepository
    return assert_true(repo is not None, "processRepository exists")

test("getServiceNamesFromDB (empty)", test_get_service_names)
test("processRepository accessible", test_get_processes)

# ── 1.6: Pure logic helper methods ──

def test_resolve_host():
    """controller.py:56 — _resolve_host_and_ip works without Qt"""
    # This is a pure logic method from Controller, test it standalone
    from controller.controller import Controller
    # Can't instantiate Controller (needs view), but we can test the static method
    result = Controller._has_ipv6_connectivity()
    # We just care that it runs without Qt error, not the result
    return assert_true(isinstance(result, bool), f"returned bool: {result}")

test("Controller._has_ipv6_connectivity (pure logic)", test_resolve_host)

# ── 1.7: Can import host data into the project (simulates nmap import) ──

def test_add_host_to_db():
    """Simulate what nmap import does: add a host to the DB, then query it back"""
    from db.entities.host import hostObj
    session = _logic.activeProject.database.session()
    try:
        host = hostObj(
            ip='10.0.0.1',
            ipv4='10.0.0.1',
            hostname='testhost',
            osMatch='Linux',
            status='up',
            state='up',
        )
        session.add(host)
        session.commit()
    finally:
        session.close()

    # Now query it back using YOUR repository code
    hosts = _logic.activeProject.repositoryContainer.hostRepository.getHosts(_filters)
    if len(hosts) < 1:
        return f"expected >= 1 host, got {len(hosts)}"
    return True

def test_query_host_by_ip():
    """controller.py uses hostRepository.getHostByIP extensively"""
    host = _logic.activeProject.repositoryContainer.hostRepository.getHostByIP('10.0.0.1')
    if host is None:
        return "getHostByIP returned None"
    return assert_eq(host.ip, '10.0.0.1')

def test_get_host_information():
    """controller.py:1404 — getHostInformation"""
    info = _logic.activeProject.repositoryContainer.hostRepository.getHostInformation('10.0.0.1')
    return assert_true(info is not None, "host info returned")

test("Add host to DB", test_add_host_to_db)
test("getHostByIP", test_query_host_by_ip)
test("getHostInformation", test_get_host_information)

# ── 1.8: Add a port/service and query it ──

def test_add_port_and_service():
    """Simulate nmap finding a port — add port+service, query back"""
    from db.entities.port import portObj
    from db.entities.service import serviceObj

    host = _logic.activeProject.repositoryContainer.hostRepository.getHostByIP('10.0.0.1')
    if host is None:
        return "host 10.0.0.1 not found — previous test failed"

    session = _logic.activeProject.database.session()
    try:
        # Create service (constructor requires name and host)
        svc = serviceObj(name='http', host=str(host.id), product='Apache', version='2.4.41')
        session.add(svc)
        session.flush()

        # Create port (constructor: portId, protocol, state, host, service)
        port = portObj(portId='80', protocol='tcp', state='open', host=host.id, service=svc.id)
        session.add(port)
        session.commit()
    finally:
        session.close()

    # Query back via YOUR repository
    ports = _logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(host.id)
    if len(ports) < 1:
        return f"expected >= 1 port, got {len(ports)}"
    return assert_eq(str(ports[0].portId), '80')

def test_get_services():
    """Query services after adding port+service"""
    services = _logic.activeProject.repositoryContainer.serviceRepository.getServiceNames(_filters)
    return assert_gt(len(services), 0, "should have at least 1 service")

def test_get_ports_for_host():
    """controller.py:1397 — getPortsAndServicesForHostFromDB"""
    host = _logic.activeProject.repositoryContainer.hostRepository.getHostByIP('10.0.0.1')
    ports = _logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(host.id)
    return assert_gt(len(ports), 0, "host should have ports")

test("Add port+service to DB", test_add_port_and_service)
test("getServiceNames (after add)", test_get_services)
test("getPortsByHostId", test_get_ports_for_host)


# ══════════════════════════════════════════════════════════════
# TIER 2: QMenu → JSON (not yet implemented)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("TIER 2: QMenu → JSON (WebController required)")
print("="*60 + "\n")

def test_tier2_placeholder():
    """Will test getContextMenuForHost returns JSON instead of QMenu"""
    try:
        from controller.web_controller import WebController
        return True  # If it imports, we can test it
    except ImportError:
        return 'SKIP'

test("WebController import", test_tier2_placeholder)

def test_context_menu_host():
    """controller.py:559 — getContextMenuForHost returns menu data as JSON"""
    try:
        from controller.web_controller import WebController
        wc = WebController(_logic, _settings)
        menu_data = wc.getContextMenuForHost(isChecked='False')
        if not isinstance(menu_data, (list, dict)):
            return f"expected list/dict, got {type(menu_data)}"
        return assert_gt(len(menu_data), 0, "menu should have items")
    except ImportError:
        return 'SKIP'

def test_context_menu_service():
    """controller.py:1058 — getContextMenuForServiceName returns menu data"""
    try:
        from controller.web_controller import WebController
        wc = WebController(_logic, _settings)
        menu_data = wc.getContextMenuForServiceName('http')
        if not isinstance(menu_data, (list, dict)):
            return f"expected list/dict, got {type(menu_data)}"
        return True
    except ImportError:
        return 'SKIP'

def test_context_menu_process():
    """controller.py:1242 — getContextMenuForProcess returns menu data"""
    try:
        from controller.web_controller import WebController
        wc = WebController(_logic, _settings)
        menu_data = wc.getContextMenuForProcess()
        if not isinstance(menu_data, (list, dict)):
            return f"expected list/dict, got {type(menu_data)}"
        return True
    except ImportError:
        return 'SKIP'

test("getContextMenuForHost → JSON", test_context_menu_host)
test("getContextMenuForServiceName → JSON", test_context_menu_service)
test("getContextMenuForProcess → JSON", test_context_menu_process)


# ══════════════════════════════════════════════════════════════
# TIER 3: QProcess → subprocess (not yet implemented)
# ══════════════════════════════════════════════════════════════

print("\n" + "="*60)
print("TIER 3: QProcess → subprocess (WebController required)")
print("="*60 + "\n")

def test_run_simple_command():
    """Can we run 'echo hello' via WebController and capture output?"""
    try:
        from controller.web_controller import WebController
        wc = WebController(_logic, _settings)
        result = wc.runCommand(
            command='echo hello_from_webcontroller',
            name='test-echo',
            hostIp='127.0.0.1',
            port='',
            protocol='tcp',
        )
        if not result:
            return "runCommand returned None"
        return assert_true(result.get('process_id') is not None, "should have process_id")
    except ImportError:
        return 'SKIP'

def test_process_appears_in_db():
    """After running a command, the process should be in the DB"""
    try:
        from controller.web_controller import WebController
        import time
        wc = WebController(_logic, _settings)
        result = wc.runCommand(
            command='echo tier3_test',
            name='test-echo-db',
            hostIp='127.0.0.1',
            port='',
            protocol='tcp',
        )
        time.sleep(2)  # let it finish
        # Query process from DB using getProcessById (your repository method)
        proc_id = result.get('process_id')
        repo = _logic.activeProject.repositoryContainer.processRepository
        proc_data = repo.getProcessById(proc_id)
        if proc_data is None:
            return f"process {proc_id} not found in DB"
        return assert_eq(proc_data['name'], 'test-echo-db')
    except ImportError:
        return 'SKIP'

def test_process_output_captured():
    """The output of the command should be stored in the DB"""
    try:
        from controller.web_controller import WebController
        import time
        wc = WebController(_logic, _settings)
        result = wc.runCommand(
            command='echo output_capture_test',
            name='test-echo-output',
            hostIp='127.0.0.1',
            port='',
            protocol='tcp',
        )
        time.sleep(2)  # let it finish and flush output
        proc_id = result.get('process_id')
        # Query output via the process_output table
        from sqlalchemy import text as sa_text
        session = _logic.activeProject.database.session()
        try:
            row = session.execute(
                sa_text("SELECT output FROM process_output WHERE processId = :pid"),
                {"pid": proc_id}
            ).fetchone()
            if not row:
                return f"no process_output row for process {proc_id}"
            output = str(row[0] or '')
            return assert_true('output_capture_test' in output,
                               f"output should contain test string, got: {output[:200]}")
        finally:
            session.close()
    except ImportError:
        return 'SKIP'

test("runCommand (echo test)", test_run_simple_command)
test("Process appears in DB after run", test_process_appears_in_db)
test("Process output captured in DB", test_process_output_captured)


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

success = summary()
sys.exit(0 if success else 1)
