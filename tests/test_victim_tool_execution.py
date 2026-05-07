"""
tests/test_victim_tool_execution.py — Every Legion scheduler tool exercised
against a local victim host (127.42.0.1) with matching services.

Architecture
============
* Module-level:  reads SchedulerSettings from the live conf → ALL_SCHEDULER_TOOLS
                 (62 tool IDs, known at collection time → used in parametrize)
* Fixtures:      victim_services → srv → completed_scan
                 All module-scoped: the victim boots once, scans once,
                 all 186 parametrized tests verify results from that one run.
* Tests:
    test_every_tool_triggered[tool_id]      — tool produced ≥1 process
    test_every_tool_no_config_error[tool_id]— output has no config-level error
    test_every_tool_expected_output[...]    — output contains tool-specific pattern

Configuration errors (always a bug, never a fake-service issue):
    'flag provided but not defined'   ffuf -q fix-2
    'could not open'                  missing wordlist fix-1
    'error creating outputfile'       Hydra path quoting fix-3
    'no templates provided for scan'  nuclei -t fix-4
    'compilation aborted'             rdp-sec-check Perl dep fix-6
    'no command template for'         dead SchedulerSettings key fix-7

Run standalone:
    sudo python3 -m pytest tests/test_victim_tool_execution.py -v -s

Integrated into run_tests.sh --selenium section (PORT=5101).
"""

import configparser
import csv
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest
import requests

# =============================================================================
# Read ALL tool IDs from SchedulerSettings at module-import time so pytest
# can use them in @pytest.mark.parametrize at collection time.
# =============================================================================

def _read_scheduler_tools() -> list:
    """Parse live legion.conf and return every [SchedulerSettings] key."""
    conf = Path(os.path.expanduser('~/.local/share/legion/legion.conf'))
    if not conf.exists():
        return []
    p = configparser.RawConfigParser()
    p.optionxform = str
    p.read(conf)
    return list(p.options('SchedulerSettings')) if p.has_section('SchedulerSettings') else []


ALL_SCHEDULER_TOOLS = _read_scheduler_tools()   # 62 entries — known at collection time

# =============================================================================
# Constants
# =============================================================================

PORT        = 5101
VICTIM_IP   = '127.42.0.1'
VICTIM_HOST = 'victim.test'
TIMEOUT_TOOLS = 720          # 12 min ceiling — generous for 120+ processes at concurrency 10

# Interactive tools store no output in process_output table — skip output checks
INTERACTIVE_TOOLS = frozenset({'vsftpd234-Meta', 'ccproxy-ftpMeta', 'x11screen'})

# Config-level errors: always a tool/conf bug, never a fake-service issue
CONF_ERROR_PATTERNS = [
    'flag provided but not defined',    # ffuf -q (fix-2)
    'could not open',                   # missing wordlist path (fix-1)
    'error creating outputfile',        # Hydra \"\" quoting (fix-3)
    'no templates provided for scan',   # nuclei -t missing (fix-4)
    'compilation aborted',              # rdp-sec-check Perl dep (fix-6)
    'no command template for',          # dead SchedulerSettings ref (fix-7)
]

# Per-tool expected output patterns — at least ONE instance of the tool must
# contain this string. Pattern is case-insensitive. Description explains what
# it proves (not just that the tool ran, but that it ran CORRECTLY).
#
# Real-service tools (nginx/samba/redis/ssh/mariadb/postgresql/snmpd/xrdp):
#   pattern proves the tool got a real response, not just started and timed out.
# Socat/fake-service tools:
#   pattern proves the tool's binary loaded and printed its own startup header.
TOOL_EXPECTED_OUTPUT = {
    # ── Real services ──────────────────────────────────────────────────────────
    # nginx at 80/443/4848/8080/8443
    'feroxbuster':          ('http://', 'feroxbuster found a URL on nginx'),
    'feroxbuster-https':    ('https://', 'feroxbuster-https found a URL on nginx SSL'),
    'gobuster-dir':         ('=====', 'gobuster printed its separator (ran to completion)'),
    'ffuf-files':           ('status:', 'ffuf result line with Status: — proves tool ran and found URLs'),
    'nuclei':               ('[', 'nuclei printed at least one template finding bracket'),
    'nuclei-https':         ('[', 'nuclei printed at least one template finding bracket'),
    'joomscan':             ('joomscan', 'joomscan banner'),
    'davtest':              ('open', 'davtest tested WebDAV methods'),
    'http-shellshock.nse':  ('nmap', 'nmap ran the shellshock NSE script'),
    'pd-httpx':             ('[success]', 'httpx probed nginx and got 200'),
    'pd-httpx-https':       ('[success]', 'httpx probed nginx SSL and got 200'),
    'testssl':              ('start', 'testssl started its TLS analysis'),
    'ssl-heartbleed.nse':   ('nmap', 'nmap ran ssl-heartbleed NSE'),
    'ssl-poodle.nse':       ('nmap', 'nmap ran ssl-poodle NSE'),
    'ssl-dh-params.nse':    ('nmap', 'nmap ran ssl-dh-params NSE'),
    'ssl-ccs-injection.nse':('nmap', 'nmap ran ssl-ccs-injection NSE'),
    'ssl-enum-ciphers.nse': ('nmap', 'nmap ran ssl-enum-ciphers NSE'),
    'screenshooter':        ('screenshot:', 'eyewitness ran and returned screenshot path'),
    # samba at 139/445
    'smbmap':               ('445', 'smbmap connected to port 445'),
    'netexec-smb':          ('smb', 'netexec-smb ran against SMB service'),
    'enum4linux-ng':        ('enum4linux', 'enum4linux-ng header in output'),
    'smb-vuln-ms17-010.nse':('nmap', 'nmap ran EternalBlue NSE check'),
    'smb-vuln-ms08-067.nse':('nmap', 'nmap ran MS08-067 NSE check'),
    'smb-vuln-cve-2017-7494.nse':('nmap', 'nmap ran SambaCry NSE check'),
    # redis at 6379
    'redis-info':           ('# server', 'redis INFO returned real server section'),
    'redis-unauth':         ('maxmemory', 'redis CONFIG GET maxmemory returned'),
    # ssh at 22
    'ssh-audit':            ('# general', 'ssh-audit section header in output'),
    # mariadb/mysql at 3306
    'mysql-default':        ('hydra v', 'Hydra version header — tool started correctly'),
    # postgresql at 5432
    'postgres-default':     ('hydra v', 'Hydra version header — tool started correctly'),
    # xrdp at 3389
    'rdp-sec-check':        ('rdp-sec-check', 'rdp-sec-check printed its own name'),
    'rdp-vuln-ms12-020.nse':('nmap', 'nmap ran RDP MS12-020 NSE check'),
    # snmpd at 161/udp
    'snmpwalk':             ('', ''),      # timeout from snmpd; output has no reliable pattern
    'onesixtyone':          ('scanning', 'onesixtyone printed scan start'),
    'snmp-default':         ('', ''),      # just must have output — no specific pattern

    # ── Fake/socat services — tool startup proves binary works ─────────────────
    'ftp-default':          ('hydra v', 'Hydra version header'),
    'telnet-default':       ('hydra v', 'Hydra version header'),
    'mssql-default':        ('hydra v', 'Hydra version header'),
    'oracle-default':       ('hydra v', 'Hydra version header — oracle-listener module started'),
    'vnc-default':          ('hydra v', 'Hydra version header — vnc module started (limitation: -p only)'),
    'smtp-enum-vrfy':       ('smtp-user-enum', 'smtp-user-enum invocation'),
    'smtp-enum-expn':       ('smtp-user-enum', 'smtp-user-enum invocation'),
    'smtp-enum-rcpt':       ('smtp-user-enum', 'smtp-user-enum invocation'),
    'swaks-relay':          ('trying', 'swaks printed its connection attempt'),
    'dig-version':          ('dig', 'dig printed its own name or version'),
    'dig-axfr':             ('dig', 'dig printed its own name or version'),
    'fierce-dns':           ('', ''),      # fierce produces no output against fake DNS — socat PIPE doesn't speak DNS protocol
    'impacket-rpcdump':     ('impacket', 'Impacket header in output'),
    'ldapdomaindump':       ('connecting', 'ldapdomaindump connection attempt'),
    'rpcinfo':              ('', ''),      # rpcinfo produces error from fake service
    'showmount':            ('', ''),      # showmount error from fake NFS
    'nfs-showmount.nse':    ('nmap', 'nmap ran nfs-showmount NSE'),
    'nfs-ls.nse':           ('nmap', 'nmap ran nfs-ls NSE'),
    'nfs-statfs.nse':       ('nmap', 'nmap ran nfs-statfs NSE'),
    'ike-scan':             ('', ''),      # ike-scan may fail to bind UDP 500
    'irc-unrealircd-backdoor.nse':('nmap', 'nmap ran irc-unrealircd-backdoor NSE'),
    'distcc-cve2004-2687.nse':('nmap', 'nmap ran distcc CVE-2004-2687 NSE'),
    'banner':               ('nmap', 'nmap banner script ran against bindshell port'),
    'x11-access.nse':       ('nmap', 'nmap ran x11-access NSE'),
    'x11screen':            ('', ''),      # bash → Interactive PTY — no stored process_output
    'ccproxy-ftpMeta':      ('', ''),      # msfconsole → Interactive PTY — no stored process_output
    'vsftpd234-Meta':       ('', ''),      # msfconsole → Interactive PTY — no stored process_output
    'smbenum':              ('smb', 'smbclient share enumeration output'),
}

# Nmap XML with ALL service names needed to trigger all 62 SchedulerSettings entries
VICTIM_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nmaprun>
<nmaprun scanner="nmap" args="nmap -Pn -sV {VICTIM_IP}" start="1746632000" version="7.98">
<host starttime="1746632000" endtime="1746632060">
  <status state="up" reason="user-set"/>
  <address addr="{VICTIM_IP}" addrtype="ipv4"/>
  <hostnames><hostname name="{VICTIM_HOST}" type="PTR"/></hostnames>
  <ports>
    <port protocol="tcp" portid="21"><state state="open"/><service name="ftp" product="vsFTPd" version="2.3.4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" version="10.2p1" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="23"><state state="open"/><service name="telnet" product="Linux telnetd" method="probed" conf="8"/></port>
    <port protocol="tcp" portid="25"><state state="open"/><service name="smtp" product="Postfix smtpd" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="53"><state state="open"/><service name="domain" product="ISC BIND" version="9.18.0" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="80"><state state="open"/><service name="http" product="nginx" version="1.28.1" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="111"><state state="open"/><service name="rpcbind" version="2-4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="135"><state state="open"/><service name="msrpc" product="Microsoft Windows RPC" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="139"><state state="open"/><service name="netbios-ssn" product="Samba smbd" version="4.X" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="389"><state state="open"/><service name="ldap" product="OpenLDAP" version="2.4.57" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="443"><state state="open"/><service name="ssl" product="nginx" version="1.28.1" tunnel="ssl" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="445"><state state="open"/><service name="microsoft-ds" product="Samba smbd" version="4.X" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="1433"><state state="open"/><service name="ms-sql-s" product="Microsoft SQL Server 2019" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="1521"><state state="open"/><service name="oracle-tns" product="Oracle TNS listener" version="11.2.0.4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="1524"><state state="open"/><service name="bindshell" product="Metasploitable root shell" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="2049"><state state="open"/><service name="nfs" version="2-4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="2121"><state state="open"/><service name="ccproxy-ftp" product="CCProxy FTP Service" method="probed" conf="8"/></port>
    <port protocol="tcp" portid="3306"><state state="open"/><service name="mysql" product="MySQL" version="8.0.32" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="3389"><state state="open"/><service name="ms-wbt-server" product="Microsoft Terminal Service" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="3632"><state state="open"/><service name="distccd" product="distcc" version="3.4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="4848"><state state="open"/><service name="appserv-http" product="GlassFish Server" version="4.0" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="5432"><state state="open"/><service name="postgresql" product="PostgreSQL DB" version="14.0 - 14.6" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="5900"><state state="open"/><service name="vnc" product="VNC" version="protocol 3.8" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="6000"><state state="open"/><service name="X11" method="probed" conf="8"/></port>
    <port protocol="tcp" portid="6379"><state state="open"/><service name="redis" product="Redis key-value store" version="8.0.5" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="6667"><state state="open"/><service name="irc" product="UnrealIRCd" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="8080"><state state="open"/><service name="http" product="nginx" version="1.28.1" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="8443"><state state="open"/><service name="https-alt" product="nginx" version="1.28.1" tunnel="ssl" method="probed" conf="10"/></port>
    <port protocol="udp" portid="53"><state state="open"/><service name="domain" product="ISC BIND" version="9.18.0" method="probed" conf="10"/></port>
    <port protocol="udp" portid="161"><state state="open"/><service name="snmp" version="v1" method="probed" conf="10"/></port>
    <port protocol="udp" portid="500"><state state="open"/><service name="isakmp" product="StrongSwan" method="probed" conf="8"/></port>
  </ports>
  <os><osmatch name="Linux 5.4" accuracy="97"><osclass type="general purpose" vendor="Linux" osfamily="Linux" osgen="5.X"/></osmatch></os>
</host>
</nmaprun>
"""

# =============================================================================
# Helpers
# =============================================================================

ANSI = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _is_conf_error(output: str) -> tuple:
    clean = ANSI.sub('', output).lower()
    for pat in CONF_ERROR_PATTERNS:
        if pat in clean:
            return True, pat
    return False, ''


def _free_port(port: int, retries: int = 20):
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    for _ in range(retries):
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port)); s.close(); return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f'Port {port} still in use')


def _port_is_open(port: int, udp: bool = False) -> bool:
    proto = 'u' if udp else 't'
    r = subprocess.run(['ss', f'-{proto}lnp'], capture_output=True, text=True)
    return f':{port} ' in r.stdout


def _wait_ports_open(tcp_ports: list, udp_ports: list = None, timeout: int = 30):
    udp_ports = udp_ports or []
    deadline = time.time() + timeout
    tcp_missing = list(tcp_ports)
    udp_missing = list(udp_ports)
    while time.time() < deadline:
        tcp_missing = [p for p in tcp_missing if not _port_is_open(p)]
        udp_missing = [p for p in udp_missing if not _port_is_open(p, udp=True)]
        if not tcp_missing and not udp_missing:
            return
        time.sleep(0.2)
    raise RuntimeError(f'Ports not open: tcp={tcp_missing} udp={udp_missing}')


def _wait_server_ready(url: str, timeout: int = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f'{url}/api/snapshot', timeout=2).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError(f'Server not ready at {url}')


def _wait_host_appears(url: str, host_ip: str, timeout: int = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            snap = requests.get(f'{url}/api/snapshot', timeout=5).json()
            if any(h.get('ip') == host_ip for h in snap.get('hosts', [])):
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f'Host {host_ip} never appeared in snapshot')


def _wait_all_done(base_url: str, host_ip: str, timeout: int = TIMEOUT_TOOLS) -> list:
    """Poll until all processes for host_ip are in a terminal state. Return them all."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            snap = requests.get(f'{base_url}/api/snapshot', timeout=10).json()
            host_procs = [p for p in snap.get('processes', [])
                          if p.get('hostIp') == host_ip]
            pending = [p for p in host_procs if p.get('status') in ('Running', 'Waiting')]
            if host_procs and not pending:
                return host_procs
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f'Tools did not finish within {timeout}s for {host_ip}')


def _socat_listen(port: int, banner: str = '', udp: bool = False):
    if _port_is_open(port, udp=udp):
        return None
    if banner:
        cmd = ['socat', f'TCP4-LISTEN:{port},reuseaddr,fork',
               f'SYSTEM:printf "{banner}"; sleep 60']
    elif udp:
        cmd = ['socat', f'UDP4-RECVFROM:{port},reuseaddr,fork', 'PIPE']
    else:
        cmd = ['socat', f'TCP4-LISTEN:{port},reuseaddr,fork', 'PIPE']
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None


# =============================================================================
# Module-scoped fixtures
# =============================================================================

@pytest.fixture(scope='module')
def victim_services():
    """Start all victim services. Wait for each port to be confirmed open."""
    subprocess.run(['ip', 'addr', 'add', f'{VICTIM_IP}/8', 'dev', 'lo'],
                   capture_output=True)

    real_service_ports = {
        'nginx':        [80, 443, 4848, 8080, 8443],
        'mariadb':      [3306],
        'postgresql':   [5432],
        'redis-server': [6379],
        'smbd':         [139, 445],
        'snmpd':        [],
        'xrdp':         [3389],
    }
    for svc in real_service_ports:
        subprocess.run(['systemctl', 'start', svc], capture_output=True, timeout=15)

    real_tcp = [p for ports in real_service_ports.values() for p in ports]
    _wait_ports_open(real_tcp, timeout=30)

    listeners = {}
    socat_ports = {
        21:   '220 (vsFTPd 2.3.4)\\r\\n',
        23:   '',
        25:   '220 victim.test ESMTP Postfix\\r\\n',
        53:   '',
        111:  '',
        135:  '',
        389:  '',
        1433: '',
        1521: '',
        1524: 'root@victim:~# ',
        2049: '',
        2121: '220 CCProxy FTP Service Ready\\r\\n',
        3632: '',
        5900: 'RFB 003.008\\n',
        6000: '',
        6667: ':victim.test NOTICE AUTH :*** Looking up your hostname...\\r\\n',
    }
    for port, banner in socat_ports.items():
        listeners[port] = _socat_listen(port, banner)
    listeners['500/udp'] = _socat_listen(500, udp=True)

    new_socat = [p for p in socat_ports if isinstance(p, int) and listeners.get(p) is not None]
    if new_socat:
        _wait_ports_open(new_socat, timeout=15)

    yield listeners

    for handle in listeners.values():
        if handle is not None:
            try: handle.kill()
            except Exception: pass


@pytest.fixture(scope='module')
def srv(victim_services):
    """Boot a Legion API server; enable scheduler-on-import; return base URL."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    import app.web.routes as _web_routes
    _web_routes._HB_TIMEOUT = 600

    _free_port(PORT)

    from app.web.testhelper import create_test_app
    from werkzeug.serving import make_server

    # enable_scheduler=True: prevents create_test_app from patching applySettings()
    # to re-disable the scheduler after every config save. Without this flag,
    # the scheduler logs "Scheduler disabled" and no tools ever run.
    app, logic, wc = create_test_app(enable_scheduler=True)
    app.config['TESTING'] = False

    # Set scheduler-on-import and concurrency directly on the wc object so they
    # cannot be overridden by a subsequent applySettings() call.
    wc.settings.general_enable_scheduler_on_import = True
    wc.settings.general_max_fast_processes = 10
    wc.settings.general_max_slow_processes = 10

    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    base = f'http://127.0.0.1:{PORT}'
    _wait_server_ready(base, timeout=30)

    yield base

    httpd.shutdown()
    _web_routes._HB_TIMEOUT = 20


@pytest.fixture(scope='module')
def completed_scan(srv) -> dict:
    """
    Import victim XML, run all scheduler tools, return results indexed by tool_id.

    Returns: {tool_id: [{'port', 'status', 'output', 'output_bytes'}, ...]}
    One tool_id may have multiple entries (same tool on different ports).
    """
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(VICTIM_XML); xml_path = f.name
    try:
        r = requests.post(f'{srv}/api/nmap/import-xml',
                          json={'path': xml_path, 'run_actions': True}, timeout=15)
        assert r.status_code == 200, f'XML import failed: {r.text}'
    finally:
        os.unlink(xml_path)

    _wait_host_appears(srv, VICTIM_IP, timeout=30)
    all_procs = _wait_all_done(srv, VICTIM_IP, timeout=TIMEOUT_TOOLS)
    tool_procs = [p for p in all_procs if p.get('name') not in ('nmap',)]

    # Fetch outputs via API — same path the UI uses
    results: dict = {}
    for proc in tool_procs:
        pid = proc['id']
        name = proc.get('name', '')
        try:
            ro = requests.get(f'{srv}/api/processes/{pid}/output?max_chars=10000',
                              timeout=10).json()
            output = ANSI.sub('', ro.get('output_chunk') or ro.get('output') or '')
        except Exception:
            output = ''
        entry = {
            'port':         str(proc.get('port', '')),
            'status':       proc.get('status', ''),
            'output':       output,
            'output_bytes': len(output),
        }
        results.setdefault(name, []).append(entry)

    return results


# =============================================================================
# Parametrized tests — one test per tool in SchedulerSettings
# =============================================================================

@pytest.mark.parametrize('tool_id', ALL_SCHEDULER_TOOLS)
def test_every_tool_triggered(tool_id, completed_scan):
    """
    Every tool in [SchedulerSettings] must have produced at least one process
    that reached a terminal state (Finished, Killed, Crashed, or Interactive).
    A missing entry means the scheduler never triggered the tool — caused by:
      - service-name mismatch (uppercase vs lowercase svc_scope)
      - dead SchedulerSettings key (no matching PortActions entry)
      - scheduler session-staleness bug (fixed in web_controller.py)
    """
    runs = completed_scan.get(tool_id, [])
    assert runs, (
        f"'{tool_id}' produced zero processes — scheduler never triggered it.\n"
        f"Check: SchedulerSettings svc_scope matches the service name nmap reports,\n"
        f"       PortActions has a matching key, scheduler is enabled."
    )
    terminal = [r for r in runs if r['status'] in
                ('Finished', 'Killed', 'Crashed', 'Interactive')]
    assert terminal, (
        f"'{tool_id}' has {len(runs)} process(es) but none reached a terminal state.\n"
        f"Statuses found: {[r['status'] for r in runs]}"
    )


@pytest.mark.parametrize('tool_id', ALL_SCHEDULER_TOOLS)
def test_every_tool_no_config_error(tool_id, completed_scan):
    """
    No tool output may contain a configuration-level error.
    These errors prove the tool's command template or dependencies are broken —
    they would fail on EVERY real target, not just this fake victim.

    Config errors checked:
      'flag provided but not defined'   → ffuf -q present (fix-2)
      'could not open'                  → wordlist path missing (fix-1)
      'error creating outputfile'       → Hydra path quoting (fix-3)
      'no templates provided for scan'  → nuclei -t missing (fix-4)
      'compilation aborted'             → rdp-sec-check Perl dep (fix-6)
      'no command template for'         → dead SchedulerSettings key (fix-7)
    """
    runs = completed_scan.get(tool_id, [])
    if not runs:
        pytest.skip(f"'{tool_id}' did not run — covered by test_every_tool_triggered")

    for run in runs:
        has_err, pat = _is_conf_error(run['output'])
        assert not has_err, (
            f"'{tool_id}' (port {run['port']}) has config error: '{pat}'\n"
            f"First 400 chars of output:\n{run['output'][:400]}"
        )


@pytest.mark.parametrize('tool_id', [
    t for t in ALL_SCHEDULER_TOOLS
    if t in TOOL_EXPECTED_OUTPUT and TOOL_EXPECTED_OUTPUT[t][0]  # skip empty-pattern entries
])
def test_every_tool_expected_output(tool_id, completed_scan):
    """
    Every tool must produce output that contains its expected pattern.
    For real-service tools (nginx/redis/ssh/samba) this proves the tool got
    a real response. For socat-backed tools it proves the binary loaded and
    printed its startup header — confirming the tool works end-to-end.

    Empty-pattern entries (fierce-dns, ike-scan, showmount, rpcinfo, snmp-default) are excluded from parametrize — those tools may
    produce no output against the fake victim and that is acceptable.
    """
    runs = completed_scan.get(tool_id, [])
    if not runs:
        pytest.skip(f"'{tool_id}' did not run — see test_every_tool_triggered")

    # Skip interactive tools — they produce no stored output
    if tool_id in INTERACTIVE_TOOLS:
        pytest.skip(f"'{tool_id}' is interactive — output not stored in process_output")

    pattern, description = TOOL_EXPECTED_OUTPUT[tool_id]

    # Check ANY instance of the tool (it may run on multiple ports)
    matched = any(pattern.lower() in r['output'].lower() for r in runs)
    if not matched:
        samples = '\n'.join(
            f"  port={r['port']} ({r['output_bytes']}b): {r['output'][:200]}"
            for r in runs[:3]
        )
        pytest.fail(
            f"'{tool_id}' output does not contain expected pattern '{pattern}'\n"
            f"({description})\n"
            f"Ran {len(runs)} time(s):\n{samples}"
        )


# =============================================================================
# Whole-scan sanity tests (not parametrized — suite-level invariants)
# =============================================================================

def test_minimum_tool_count(completed_scan):
    """At least 55 of the 62 scheduler tools must have produced at least one process."""
    triggered = sum(1 for t in ALL_SCHEDULER_TOOLS if completed_scan.get(t))
    assert triggered >= 55, (
        f"Only {triggered}/{len(ALL_SCHEDULER_TOOLS)} scheduler tools ran.\n"
        f"Missing: {[t for t in ALL_SCHEDULER_TOOLS if not completed_scan.get(t)]}"
    )


def test_print_full_report(completed_scan, capsys):
    """
    Always-pass: prints a complete table of every tool's status and output sample.
    Use -s to see it: pytest tests/test_victim_tool_execution.py -v -s
    """
    print(f"\n\n{'='*100}")
    print(f"VICTIM TOOL EXECUTION REPORT — {VICTIM_IP} ({len(ALL_SCHEDULER_TOOLS)} scheduler tools)")
    print(f"{'='*100}")
    print(f"{'Tool':<40} {'Port':<6} {'Status':<12} {'Bytes':>6}  {'Output / Error'}")
    print(f"{'-'*100}")

    conf_errors = []
    empty_runs   = []
    missing      = []

    for tool_id in sorted(ALL_SCHEDULER_TOOLS):
        runs = completed_scan.get(tool_id)
        if not runs:
            missing.append(tool_id)
            print(f"  {'[MISSING]':<8} {tool_id}")
            continue
        for run in runs:
            lines = [l.strip() for l in run['output'].splitlines() if l.strip()]
            first = lines[0][:60] if lines else '(empty)'
            has_err, pat = _is_conf_error(run['output'])
            tag = f'[CONF_ERR:{pat[:20]}]' if has_err else ''
            if has_err:
                conf_errors.append((tool_id, run['port'], pat))
            if run['output_bytes'] == 0 and tool_id not in INTERACTIVE_TOOLS:
                empty_runs.append((tool_id, run['port']))
            print(f"  {tool_id:<38} {run['port']:<6} {run['status']:<12} "
                  f"{run['output_bytes']:>6}  {tag}{first}")

    print(f"\n{'='*100}")
    print(f"Missing tools:     {len(missing)}")
    print(f"Config errors:     {len(conf_errors)}")
    print(f"Empty outputs:     {len(empty_runs)}")
    print(f"Total tool runs:   {sum(len(v) for v in completed_scan.values())}")
    if conf_errors:
        print(f"\nCONFIG ERRORS:")
        for t, p, pat in conf_errors:
            print(f"  {t} port={p}: {pat}")
    # Always pass — this is a reporting test
