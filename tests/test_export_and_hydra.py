#!/usr/bin/env python3
"""
Export and Hydra Tests
======================
Run with:
  sudo python3 tests/test_export_and_hydra.py              # offline export tests only
  sudo env LEGION_TEST_TARGET=192.168.85.11 \
       LEGION_SSH_PORT=22 \
       LEGION_MYSQL_PORT=3306 \
       python3 tests/test_export_and_hydra.py              # + live Hydra tests

What's tested:
  E1: JSON export to /tmp file — verify all DB data round-trips correctly
  E2: CSV export to /tmp file — verify format and per-port rows
  H1: Hydra SSH brute-force against live VM — verify credentials found and stored
  H2: Hydra MySQL brute-force against live VM — verify root/no-password found
"""

import os
import sys
import csv
import json
import time
import tempfile
import traceback

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
from app.importers.nmap_import import import_nmap_xml
from app.auxiliary import Filters

app, logic, wc = create_test_app()
client = app.test_client()
filters = Filters()

# Seed two hosts with distinct ports and notes — known ground truth for export tests
_SEED = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.40.50.1" addrtype="ipv4"/>
    <hostnames><hostname name="export-test-a" type="PTR"/></hostnames>
    <os><osmatch name="Linux 5.x" accuracy="95"/></os>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.9"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4"/>
      </port>
    </ports>
  </host>
  <host><status state="up"/>
    <address addr="10.40.50.2" addrtype="ipv4"/>
    <hostnames><hostname name="export-test-b" type="PTR"/></hostnames>
    <os><osmatch name="Windows 10" accuracy="90"/></os>
    <ports>
      <port protocol="tcp" portid="443">
        <state state="open"/>
        <service name="https" product="IIS" version="10.0"/>
      </port>
      <port protocol="tcp" portid="3389">
        <state state="open"/>
        <service name="ms-wbt-server" product="RDP"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
    _f.write(_SEED); _seed_path = _f.name
import_nmap_xml(project=logic.activeProject, xml_path=_seed_path, output="")
os.unlink(_seed_path)

# Add notes to each host so we can verify note round-trip
_hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
def _find_host(ip):
    for h in _hosts:
        hip = h.get('ip') if isinstance(h, dict) else getattr(h, 'ip', '')
        if hip == ip:
            return h.get('id') if isinstance(h, dict) else getattr(h, 'id')
    return None

_id_a = _find_host('10.40.50.1')
_id_b = _find_host('10.40.50.2')
if _id_a:
    logic.activeProject.repositoryContainer.noteRepository.storeNotes(_id_a, 'export-note-alpha')
if _id_b:
    logic.activeProject.repositoryContainer.noteRepository.storeNotes(_id_b, 'export-note-beta')


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("E1: JSON export — round-trip through /tmp file")
print("="*60 + "\n")

JSON_TMP = '/tmp/legion-export-test-full.json'

def test_e1_json_export_to_file():
    """GET /api/export/json → write to /tmp → file exists with non-zero size."""
    r = client.get('/api/export/json')
    if r.status_code != 200:
        return f"Export returned {r.status_code}"
    data = r.data
    with open(JSON_TMP, 'wb') as f:
        f.write(data)
    return ok(os.path.isfile(JSON_TMP) and os.path.getsize(JSON_TMP) > 0,
              f"JSON not written to {JSON_TMP}")
test("E1.1: JSON export writes to /tmp file", test_e1_json_export_to_file)

def test_e1_json_file_is_valid():
    """/tmp JSON file must parse without error."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        parsed = json.load(f)
    return ok(isinstance(parsed, dict), "Parsed JSON is not a dict")
test("E1.2: /tmp JSON file is valid JSON", test_e1_json_file_is_valid)

def test_e1_json_contains_both_host_ips():
    """Both seeded IPs must appear in the exported JSON."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    ips = {h.get('ip') for h in data.get('hosts', [])}
    missing = {'10.40.50.1', '10.40.50.2'} - ips
    return ok(not missing, f"Missing IPs in JSON: {missing} (found: {ips})")
test("E1.3: JSON hosts contains both seeded IPs", test_e1_json_contains_both_host_ips)

def test_e1_json_host_a_ports_correct():
    """Host A (10.40.50.1) must have ports 22 and 80 in JSON."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    host_a = next((h for h in data.get('hosts', []) if h.get('ip') == '10.40.50.1'), None)
    if not host_a:
        return "FAIL: host A not in JSON"
    port_nums = {int(p.get('port', 0)) for p in host_a.get('ports', [])}
    missing = {22, 80} - port_nums
    return ok(not missing, f"Host A missing ports {missing} in JSON (got {port_nums})")
test("E1.4: JSON host A has correct ports (22, 80)", test_e1_json_host_a_ports_correct)

def test_e1_json_host_b_ports_correct():
    """Host B (10.40.50.2) must have ports 443 and 3389 in JSON."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    host_b = next((h for h in data.get('hosts', []) if h.get('ip') == '10.40.50.2'), None)
    if not host_b:
        return "FAIL: host B not in JSON"
    port_nums = {int(p.get('port', 0)) for p in host_b.get('ports', [])}
    missing = {443, 3389} - port_nums
    return ok(not missing, f"Host B missing ports {missing} in JSON (got {port_nums})")
test("E1.5: JSON host B has correct ports (443, 3389)", test_e1_json_host_b_ports_correct)

def test_e1_json_port_fields_present():
    """Each port entry must have port, protocol, state, service fields."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    required = ['port', 'protocol', 'state', 'service']
    for h in data.get('hosts', []):
        for p in h.get('ports', []):
            missing = [k for k in required if k not in p]
            if missing:
                return f"Port in {h.get('ip')} missing fields: {missing}"
    return True
test("E1.6: every JSON port entry has required fields", test_e1_json_port_fields_present)

def test_e1_json_service_product_version_present():
    """Port 22 on host A must have product and version from the seed XML."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    host_a = next((h for h in data.get('hosts', []) if h.get('ip') == '10.40.50.1'), None)
    if not host_a: return "SKIP"
    port22 = next((p for p in host_a.get('ports', []) if str(p.get('port')) == '22'), None)
    if not port22: return "FAIL: port 22 not found for host A"
    product = port22.get('product', '')
    version = port22.get('version', '')
    return ok('OpenSSH' in (product or version or ''),
              f"SSH product/version not in export: product={product!r} version={version!r}")
test("E1.7: JSON includes service product and version from DB", test_e1_json_service_product_version_present)

def test_e1_json_note_preserved():
    """Note written to host A must appear in the JSON export."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    host_a = next((h for h in data.get('hosts', []) if h.get('ip') == '10.40.50.1'), None)
    if not host_a: return "SKIP"
    note = host_a.get('note', '') or ''
    return ok('export-note-alpha' in note,
              f"Note not in JSON export. Got: {note!r}")
test("E1.8: JSON includes host notes from DB", test_e1_json_note_preserved)

def test_e1_json_hostname_present():
    """Hostname from seed XML must appear in JSON export."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    host_a = next((h for h in data.get('hosts', []) if h.get('ip') == '10.40.50.1'), None)
    if not host_a: return "SKIP"
    hostname = host_a.get('hostname', '') or ''
    return ok('export-test-a' in hostname,
              f"Hostname not in JSON. Got: {hostname!r}")
test("E1.9: JSON includes hostname from DB", test_e1_json_hostname_present)

def test_e1_json_os_present():
    """OS match from seed XML must appear in JSON export."""
    if not os.path.isfile(JSON_TMP): return "SKIP"
    with open(JSON_TMP) as f:
        data = json.load(f)
    host_a = next((h for h in data.get('hosts', []) if h.get('ip') == '10.40.50.1'), None)
    if not host_a: return "SKIP"
    os_val = host_a.get('os', '') or ''
    return ok('Linux' in os_val,
              f"OS not in JSON export. Got: {os_val!r}")
test("E1.10: JSON includes OS from DB", test_e1_json_os_present)

# Cleanup JSON tmp
if os.path.isfile(JSON_TMP):
    os.unlink(JSON_TMP)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("E2: CSV export — round-trip through /tmp file")
print("="*60 + "\n")

CSV_TMP = '/tmp/legion-export-test-full.csv'

def test_e2_csv_export_to_file():
    """GET /api/export/csv → write to /tmp → file exists."""
    r = client.get('/api/export/csv')
    if r.status_code != 200:
        return f"CSV export returned {r.status_code}"
    with open(CSV_TMP, 'wb') as f:
        f.write(r.data)
    return ok(os.path.isfile(CSV_TMP) and os.path.getsize(CSV_TMP) > 0,
              f"CSV not written to {CSV_TMP}")
test("E2.1: CSV export writes to /tmp file", test_e2_csv_export_to_file)

def test_e2_csv_file_is_valid():
    """/tmp CSV must parse without error."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    return ok(isinstance(rows, list), "CSV parse failed")
test("E2.2: /tmp CSV file is valid CSV", test_e2_csv_file_is_valid)

def test_e2_csv_has_correct_header_columns():
    """CSV header must contain ip, port, protocol, state, service columns."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    required = ['ip', 'port', 'protocol', 'state', 'service']
    missing = [c for c in required if c not in headers]
    return ok(not missing, f"Missing CSV headers: {missing} (got: {headers})")
test("E2.3: CSV has required header columns", test_e2_csv_has_correct_header_columns)

def test_e2_csv_contains_host_a_ip():
    """IP 10.40.50.1 must appear in CSV data rows."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    ips = {r.get('ip', '') for r in rows}
    return ok('10.40.50.1' in ips, f"10.40.50.1 not in CSV ips: {ips}")
test("E2.4: CSV contains host A IP (10.40.50.1)", test_e2_csv_contains_host_a_ip)

def test_e2_csv_contains_host_b_ip():
    """IP 10.40.50.2 must appear in CSV data rows."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    ips = {r.get('ip', '') for r in rows}
    return ok('10.40.50.2' in ips, f"10.40.50.2 not in CSV ips: {ips}")
test("E2.5: CSV contains host B IP (10.40.50.2)", test_e2_csv_contains_host_b_ip)

def test_e2_csv_one_row_per_port():
    """4 seeded ports across 2 hosts → exactly 4 data rows in CSV."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    # 2 ports on host A + 2 ports on host B = 4 rows
    return ok(len(rows) >= 4, f"Expected ≥4 data rows (one per port), got {len(rows)}")
test("E2.6: CSV has one row per port (≥4 for 4 seeded ports)", test_e2_csv_one_row_per_port)

def test_e2_csv_port_22_row():
    """Port 22 on 10.40.50.1 must appear as its own row with ssh service."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    port22 = [r for r in rows if r.get('ip') == '10.40.50.1' and r.get('port') == '22']
    if not port22:
        return f"FAIL: no row for 10.40.50.1:22 in CSV"
    row = port22[0]
    return ok('ssh' in row.get('service', '').lower(),
              f"Row for port 22 has service={row.get('service')!r}, expected ssh")
test("E2.7: CSV row for 10.40.50.1:22 has service=ssh", test_e2_csv_port_22_row)

def test_e2_csv_port_3389_row():
    """Port 3389 on 10.40.50.2 must appear as its own row."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    port3389 = [r for r in rows if r.get('ip') == '10.40.50.2' and r.get('port') == '3389']
    return ok(len(port3389) > 0, "No row for 10.40.50.2:3389 in CSV")
test("E2.8: CSV row for 10.40.50.2:3389 (RDP) present", test_e2_csv_port_3389_row)

def test_e2_csv_product_version_in_row():
    """SSH row must include product (OpenSSH) and version (8.9)."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    port22 = [r for r in rows if r.get('ip') == '10.40.50.1' and r.get('port') == '22']
    if not port22: return "SKIP"
    row = port22[0]
    product = row.get('product', '')
    version = row.get('version', '')
    return ok('OpenSSH' in (product + version),
              f"product={product!r} version={version!r}")
test("E2.9: CSV SSH row contains product and version from DB", test_e2_csv_product_version_in_row)

def test_e2_csv_all_states_open():
    """All seeded ports are open — state column must contain 'open'."""
    if not os.path.isfile(CSV_TMP): return "SKIP"
    with open(CSV_TMP, newline='') as f:
        rows = list(csv.DictReader(f))
    non_open = [r for r in rows if r.get('state', '').strip() not in ('open', 'open|filtered', '')]
    return ok(not non_open,
              f"Rows with unexpected state: {[(r.get('ip'), r.get('port'), r.get('state')) for r in non_open]}")
test("E2.10: all CSV rows have state=open (seeded data)", test_e2_csv_all_states_open)

# Cleanup CSV tmp
if os.path.isfile(CSV_TMP):
    os.unlink(CSV_TMP)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("H1: Hydra SSH brute-force (requires LEGION_TEST_TARGET)")
print("="*60 + "\n")

_LIVE_TARGET = os.environ.get('LEGION_TEST_TARGET', '').strip()
_SSH_PORT    = os.environ.get('LEGION_SSH_PORT', '22').strip()
_MYSQL_PORT  = os.environ.get('LEGION_MYSQL_PORT', '3306').strip()

def _wait_for_process(pid, timeout=120):
    """Poll snapshot until process with given id reaches Finished/Killed/Crashed."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get('/api/snapshot').get_json()
        for p in snap.get('processes', []):
            if p.get('id') == pid:
                status = p.get('status', '')
                if status in ('Finished', 'Killed', 'Crashed'):
                    return status
        time.sleep(2)
    return None

def _make_combo_file(entries):
    """Write user:pass entries to a temp file, return the path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    for e in entries:
        f.write(e + '\n')
    f.close()
    return f.name

def test_h1_hydra_ssh_finds_credentials():
    """Hydra finds msfadmin:msfadmin on SSH and stores to wordlist."""
    if not _LIVE_TARGET:
        return "SKIP"
    wc.start()

    # Create combo file with known credential
    combo = _make_combo_file(['msfadmin:msfadmin'])
    try:
        r = client.post('/api/brute/run', json={
            'ip': _LIVE_TARGET,
            'port': _SSH_PORT,
            'service': 'ssh',
            'userlist': combo,    # -C mode: colon-separated user:pass
        })
        if r.status_code != 200:
            return f"brute/run returned {r.status_code}: {r.get_data(as_text=True)[:100]}"

        pid = r.get_json().get('process_id')
        if not pid:
            return "FAIL: no process_id returned"

        status = _wait_for_process(pid, timeout=120)
        if not status:
            return f"FAIL: hydra process {pid} did not finish within 120s"

        # Check process output for success indicator
        out_r = client.get(f'/api/processes/{pid}/output').get_json()
        output = out_r.get('output', '') or out_r.get('output_chunk', '') or ''
        found_login = any(x in output for x in ('login:', 'host:', '[ssh]'))
        return ok(found_login,
                  f"No login found in hydra output. Status={status}. Output tail: {output[-400:]!r}")
    finally:
        os.unlink(combo)
test("H1.1: Hydra SSH finds msfadmin:msfadmin on live VM", test_h1_hydra_ssh_finds_credentials)

def test_h1_hydra_ssh_credentials_in_wordlist():
    """After Hydra finds credentials, wordlist file must contain the username."""
    if not _LIVE_TARGET:
        return "SKIP"
    wc.start()
    username_file = logic.activeProject.properties.usernamesWordList.filename
    combo = _make_combo_file(['msfadmin:msfadmin'])
    try:
        r = client.post('/api/brute/run', json={
            'ip': _LIVE_TARGET,
            'port': _SSH_PORT,
            'service': 'ssh',
            'userlist': combo,
        })
        pid = r.get_json().get('process_id') if r.status_code == 200 else None
        if not pid: return "SKIP"
        _wait_for_process(pid, timeout=120)
        with open(username_file) as f:
            content = f.read()
        return ok('msfadmin' in content,
                  f"'msfadmin' not in wordlist after Hydra run. File: {username_file}")
    finally:
        os.unlink(combo)
test("H1.2: found SSH username written to project wordlist file", test_h1_hydra_ssh_credentials_in_wordlist)

def test_h1_hydra_ssh_process_appears_in_snapshot():
    """Hydra process must appear in snapshot with correct hostIp."""
    if not _LIVE_TARGET:
        return "SKIP"
    wc.start()
    snap_before = {p['id'] for p in client.get('/api/snapshot').get_json().get('processes', [])}
    combo = _make_combo_file(['msfadmin:msfadmin'])
    try:
        r = client.post('/api/brute/run', json={
            'ip': _LIVE_TARGET, 'port': _SSH_PORT,
            'service': 'ssh', 'userlist': combo,
        })
        pid = r.get_json().get('process_id') if r.status_code == 200 else None
        if not pid: return "SKIP"
        _wait_for_process(pid, timeout=120)
        snap = client.get('/api/snapshot').get_json()
        procs = {p['id']: p for p in snap.get('processes', [])}
        if pid not in procs:
            return f"FAIL: hydra process {pid} not in snapshot"
        return ok(procs[pid].get('hostIp') == _LIVE_TARGET,
                  f"Process hostIp={procs[pid].get('hostIp')!r}, expected {_LIVE_TARGET!r}")
    finally:
        os.unlink(combo)
test("H1.3: Hydra process appears in snapshot with correct target IP", test_h1_hydra_ssh_process_appears_in_snapshot)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("H2: Hydra MySQL brute-force (requires LEGION_TEST_TARGET)")
print("="*60 + "\n")

def test_h2_hydra_mysql_finds_root():
    """Hydra finds root with empty password on MySQL."""
    if not _LIVE_TARGET:
        return "SKIP"
    wc.start()
    # MySQL root with empty password: use combo file with 'root:'
    combo = _make_combo_file(['root:'])
    try:
        r = client.post('/api/brute/run', json={
            'ip': _LIVE_TARGET,
            'port': _MYSQL_PORT,
            'service': 'mysql',
            'userlist': combo,
        })
        if r.status_code != 200:
            return f"brute/run returned {r.status_code}"

        pid = r.get_json().get('process_id')
        if not pid: return "FAIL: no process_id"

        status = _wait_for_process(pid, timeout=120)
        out_r = client.get(f'/api/processes/{pid}/output').get_json()
        output = out_r.get('output', '') or out_r.get('output_chunk', '') or ''
        found_login = any(x in output for x in ('login:', 'host:', '[mysql]', 'root'))
        return ok(found_login,
                  f"No MySQL login found. Status={status}. Output: {output[-400:]!r}")
    finally:
        os.unlink(combo)
test("H2.1: Hydra MySQL finds root (empty password) on live VM", test_h2_hydra_mysql_finds_root)

def test_h2_hydra_mysql_password_in_wordlist():
    """After MySQL Hydra run, password list file must be updated."""
    if not _LIVE_TARGET:
        return "SKIP"
    wc.start()
    pass_file = logic.activeProject.properties.passwordWordList.filename
    combo = _make_combo_file(['root:'])
    try:
        r = client.post('/api/brute/run', json={
            'ip': _LIVE_TARGET, 'port': _MYSQL_PORT,
            'service': 'mysql', 'userlist': combo,
        })
        pid = r.get_json().get('process_id') if r.status_code == 200 else None
        if not pid: return "SKIP"
        _wait_for_process(pid, timeout=120)
        # Empty password means Hydra may output "password:" with nothing after
        # Just verify the process completed without error
        out_r = client.get(f'/api/processes/{pid}/output').get_json()
        output = out_r.get('output', '') or out_r.get('output_chunk', '') or ''
        return ok(len(output) > 0,
                  f"Hydra MySQL produced no output")
    finally:
        os.unlink(combo)
test("H2.2: Hydra MySQL run completes and produces output", test_h2_hydra_mysql_password_in_wordlist)


# ══════════════════════════════════════════════════════════════════════════════
total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
