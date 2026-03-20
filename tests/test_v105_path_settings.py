#!/usr/bin/env python3
"""
v10.5 Path Settings Tests
=========================
Regression tests proving nmap-path, hydra-path, and pyshodan-api-key
are read from settings rather than hardcoded.

Run: sudo python3 tests/test_v105_path_settings.py
"""

import os
import sys
import traceback
import tempfile

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


from app.web.testhelper import create_test_app
from app.importers.nmap_import import import_nmap_xml
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
</nmaprun>"""

with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _sp = _f.name

with app.app_context():
    import_nmap_xml(project=logic.activeProject, xml_path=_sp)
os.unlink(_sp)


# ── N1: nmap-path in addHosts ──────────────────────────────────────────────────

print("\nN1: addHosts uses tools_path_nmap")

def test_n1_1_default_nmap_used():
    """When tools_path_nmap is empty/default, command starts with 'nmap'."""
    captured = []
    orig = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run
    try:
        orig_val = getattr(wc.settings, 'tools_path_nmap', '')
        wc.settings.tools_path_nmap = ''
        wc.addHosts('10.0.0.1', runStagedNmap=False, runHostDiscovery=True)
        wc.settings.tools_path_nmap = orig_val
    finally:
        wc.runCommand = orig
    cmd = captured[0] if captured else ''
    return ok(cmd.startswith('nmap '), f"expected 'nmap ...', got: {cmd!r}")

test("N1.1: empty nmap-path falls back to plain 'nmap'", test_n1_1_default_nmap_used)

def test_n1_2_custom_nmap_path_used():
    """When tools_path_nmap is set to /custom/nmap, command starts with that path."""
    captured = []
    orig = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run
    try:
        orig_val = getattr(wc.settings, 'tools_path_nmap', '')
        wc.settings.tools_path_nmap = '/custom/nmap'
        wc.addHosts('10.0.0.1', runStagedNmap=False, runHostDiscovery=True)
        wc.settings.tools_path_nmap = orig_val
    finally:
        wc.runCommand = orig
    cmd = captured[0] if captured else ''
    return ok(cmd.startswith('/custom/nmap '), f"expected '/custom/nmap ...', got: {cmd!r}")

test("N1.2: custom nmap-path used in addHosts (discovery)", test_n1_2_custom_nmap_path_used)

def test_n1_3_custom_nmap_path_list_mode():
    """addHosts list mode also uses custom nmap-path."""
    captured = []
    orig = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run
    try:
        orig_val = getattr(wc.settings, 'tools_path_nmap', '')
        wc.settings.tools_path_nmap = '/opt/nmap'
        wc.addHosts('10.0.0.1', runStagedNmap=False, runHostDiscovery=False)
        wc.settings.tools_path_nmap = orig_val
    finally:
        wc.runCommand = orig
    cmd = captured[0] if captured else ''
    return ok(cmd.startswith('/opt/nmap '), f"expected '/opt/nmap ...', got: {cmd!r}")

test("N1.3: custom nmap-path used in addHosts (list mode)", test_n1_3_custom_nmap_path_list_mode)

def test_n1_4_hard_mode_nmap_path():
    """addHosts Hard mode also uses custom nmap-path."""
    captured = []
    orig = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run
    try:
        orig_val = getattr(wc.settings, 'tools_path_nmap', '')
        wc.settings.tools_path_nmap = '/sbin/nmap'
        wc.addHosts('10.0.0.1', runStagedNmap=False, scanMode='Hard', nmapOptions=['-sV'])
        wc.settings.tools_path_nmap = orig_val
    finally:
        wc.runCommand = orig
    cmd = captured[0] if captured else ''
    return ok(cmd.startswith('/sbin/nmap '), f"expected '/sbin/nmap ...', got: {cmd!r}")

test("N1.4: custom nmap-path used in addHosts (Hard mode)", test_n1_4_hard_mode_nmap_path)


# ── N2: nmap-path in runStagedNmap ────────────────────────────────────────────

print("\nN2: runStagedNmap uses tools_path_nmap")

def test_n2_1_staged_uses_custom_path():
    """runStagedNmap stage 1 command starts with custom nmap-path."""
    captured = []
    orig = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run
    try:
        orig_val = getattr(wc.settings, 'tools_path_nmap', '')
        wc.settings.tools_path_nmap = '/custom/nmap'
        wc.runStagedNmap('10.0.0.1', discovery=False, stage=1)
        wc.settings.tools_path_nmap = orig_val
    finally:
        wc.runCommand = orig
    cmd = captured[0] if captured else ''
    return ok(cmd.startswith('/custom/nmap '), f"expected '/custom/nmap ...', got: {cmd!r}")

test("N2.1: custom nmap-path used in runStagedNmap stage 1", test_n2_1_staged_uses_custom_path)

def test_n2_2_staged_nse_uses_custom_path():
    """runStagedNmap NSE stage also uses custom nmap-path."""
    captured = []
    orig = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run
    try:
        orig_val = getattr(wc.settings, 'tools_path_nmap', '')
        wc.settings.tools_path_nmap = '/custom/nmap'
        wc.runStagedNmap('10.0.0.1', discovery=False, stage=2)
        wc.settings.tools_path_nmap = orig_val
    finally:
        wc.runCommand = orig
    cmd = captured[0] if captured else ''
    return ok(cmd.startswith('/custom/nmap '), f"expected '/custom/nmap ...', got: {cmd!r}")

test("N2.2: custom nmap-path used in runStagedNmap NSE stage", test_n2_2_staged_nse_uses_custom_path)


# ── H1: hydra-path in brute_run ───────────────────────────────────────────────

print("\nH1: brute_run uses tools_path_hydra")

def test_h1_1_default_hydra():
    """When tools_path_hydra is empty, brute_run uses plain 'hydra'."""
    orig_val = getattr(wc.settings, 'tools_path_hydra', '')
    wc.settings.tools_path_hydra = ''
    with app.app_context():
        resp = client.post('/api/brute/run', json={
            'ip': '10.10.10.1', 'port': '22', 'service': 'ssh',
            'userlist': '/tmp/users.txt', 'passlist': '/tmp/pass.txt'
        })
    wc.settings.tools_path_hydra = orig_val
    data = resp.get_json()
    cmd = data.get('command', '') if data else ''
    return ok(cmd.startswith('hydra '), f"expected 'hydra ...', got: {cmd!r}")

test("H1.1: empty hydra-path falls back to plain 'hydra'", test_h1_1_default_hydra)

def test_h1_2_custom_hydra_path():
    """When tools_path_hydra is set, brute_run command uses that path."""
    orig_val = getattr(wc.settings, 'tools_path_hydra', '')
    wc.settings.tools_path_hydra = '/usr/local/bin/hydra'
    with app.app_context():
        resp = client.post('/api/brute/run', json={
            'ip': '10.10.10.1', 'port': '22', 'service': 'ssh',
            'userlist': '/tmp/users.txt', 'passlist': '/tmp/pass.txt'
        })
    wc.settings.tools_path_hydra = orig_val
    data = resp.get_json()
    cmd = data.get('command', '') if data else ''
    return ok(cmd.startswith('/usr/local/bin/hydra '), f"expected '/usr/local/bin/hydra ...', got: {cmd!r}")

test("H1.2: custom hydra-path used in brute_run command", test_h1_2_custom_hydra_path)


# ── S1: pyshodan-api-key ──────────────────────────────────────────────────────

print("\nS1: pyShodan reads SHODAN_API_KEY from environment")

def test_s1_1_pyshodan_reads_env():
    """pyShodan.py reads API key from SHODAN_API_KEY env var, not hardcoded."""
    with open(os.path.join(PROJECT_ROOT, 'scripts', 'python', 'pyShodan.py')) as f:
        src = f.read()
    return ok(
        'SHODAN_API_KEY' in src and 'os.environ' in src,
        "pyShodan.py does not read SHODAN_API_KEY from os.environ"
    )

test("S1.1: pyShodan.py reads key from os.environ.get('SHODAN_API_KEY')", test_s1_1_pyshodan_reads_env)

def test_s1_2_no_hardcoded_key():
    """pyShodan.py must NOT contain the old hardcoded API key."""
    with open(os.path.join(PROJECT_ROOT, 'scripts', 'python', 'pyShodan.py')) as f:
        src = f.read()
    # Old hardcoded key from upstream
    return ok(
        'SNYEkE0gdwNu9BRURVDjWPXePCquXqht' not in src,
        "pyShodan.py still contains hardcoded API key"
    )

test("S1.2: pyShodan.py has no hardcoded API key", test_s1_2_no_hardcoded_key)

def test_s1_3_web_controller_injects_key():
    """handleHostToolAction injects SHODAN_API_KEY env var when key is set."""
    with open(os.path.join(PROJECT_ROOT, 'controller', 'web_controller.py')) as f:
        src = f.read()
    return ok(
        'SHODAN_API_KEY' in src and 'tools_pyshodan_api_key' in src,
        "web_controller.py does not inject SHODAN_API_KEY for pyShodan dispatch"
    )

test("S1.3: web_controller injects SHODAN_API_KEY for pyShodan subprocess", test_s1_3_web_controller_injects_key)

def test_s1_4_key_injected_in_command():
    """When pyshodan-api-key is set in settings, the dispatched command includes SHODAN_API_KEY=."""
    captured = []
    orig_run = wc.runCommand
    def fake_run(command, **kw):
        captured.append(command)
        return {'process_id': 0}
    wc.runCommand = fake_run

    orig_key = getattr(wc.settings, 'tools_pyshodan_api_key', '')
    wc.settings.tools_pyshodan_api_key = 'TEST_KEY_XYZ'

    # Simulate handleHostToolAction dispatch for pyShodan
    script_path = os.path.join(PROJECT_ROOT, 'scripts', 'python', 'pyShodan.py')
    if not os.path.isfile(script_path):
        wc.settings.tools_pyshodan_api_key = orig_key
        wc.runCommand = orig_run
        return 'SKIP'

    # Build the command as handleHostToolAction would
    import shlex
    api_key = wc.settings.tools_pyshodan_api_key
    base_cmd = f'python3 {script_path} 10.10.10.1'
    expected_prefix = f"SHODAN_API_KEY={shlex.quote(api_key)} {base_cmd}"

    # Patch settings.hostActions to inject a pyShodan action
    orig_actions = wc.settings.hostActions
    wc.settings.hostActions = [('PyShodan', 'python-script-pyShodan', 'python-script-pyShodan [IP]')]
    try:
        wc.handleHostToolAction('10.10.10.1', 0)
    finally:
        wc.settings.hostActions = orig_actions
        wc.settings.tools_pyshodan_api_key = orig_key
        wc.runCommand = orig_run

    cmd = captured[0] if captured else ''
    return ok(
        cmd.startswith('SHODAN_API_KEY=') and 'pyShodan.py' in cmd,
        f"expected SHODAN_API_KEY= prefix, got: {cmd!r}"
    )

test("S1.4: SHODAN_API_KEY env var prepended when key is configured", test_s1_4_key_injected_in_command)


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n  Passed: {PASS}  Failed: {FAIL}  Skipped: {SKIP}\n")
if FAIL:
    sys.exit(1)
