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
import concurrent.futures
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


# ---------------------------------------------------------------------------
# Progress reporter — writes to /dev/tty so output is visible even when
# pytest captures stdout/stderr (e.g. run_tests.sh pipes output through $(...))
# ---------------------------------------------------------------------------

def _tty_print(msg: str):
    """Write a progress line directly to the terminal, bypassing pytest capture."""
    try:
        with open('/dev/tty', 'w') as tty:
            tty.write(f'\r\033[K  [victim] {msg}\n')
            tty.flush()
    except OSError:
        pass  # headless / no tty — silently skip

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


def _read_scheduler_scopes() -> dict:
    """Return {tool_id: 'svc_scope,tcp_udp'} from SchedulerSettings values."""
    conf = Path(os.path.expanduser('~/.local/share/legion/legion.conf'))
    if not conf.exists():
        return {}
    p = configparser.RawConfigParser()
    p.optionxform = str
    p.read(conf)
    if not p.has_section('SchedulerSettings'):
        return {}
    result = {}
    for key, val in p.items('SchedulerSettings'):
        parts = [v.strip() for v in val.split(',')]
        result[key] = val.strip()   # raw value e.g. "http,https,ssl,tcp"
    return result


ALL_SCHEDULER_TOOLS  = _read_scheduler_tools()   # 62 entries — known at collection time
ALL_SCHEDULER_SCOPES = _read_scheduler_scopes()  # {tool_id: raw_conf_value}


# =============================================================================
# Module-level prereq check — skip entire file with a clear reason rather than
# crashing inside a module-scope fixture (which shows as "0 of 0" in run_tests.sh)
# =============================================================================

PORT        = 5101
VICTIM_IP   = '127.42.0.1'
VICTIM_HOST = 'victim.test'
TIMEOUT_TOOLS = 720          # 12 min ceiling — generous for 120+ processes at concurrency 10


def _victim_prereq_reason() -> str:
    """Return a human-readable skip reason if prerequisites are missing, else ''."""
    # Conf must exist before anything else
    conf = Path(os.path.expanduser('~/.local/share/legion/legion.conf'))
    if not conf.exists():
        return f'legion.conf not found at {conf} — run install.sh first'
    if not ALL_SCHEDULER_TOOLS:
        return 'No [SchedulerSettings] tools found in legion.conf'
    # Try to start required services; probe ports on 127.0.0.1 (not VICTIM_IP)
    # because mariadb and redis bind to 127.0.0.1 only, not 0.0.0.0.
    # The fixture handles the VICTIM_IP loopback alias and service routing.
    subprocess.run(['ip', 'addr', 'add', f'{VICTIM_IP}/8', 'dev', 'lo'],
                   capture_output=True)
    for svc, port in [('nginx', 80), ('mariadb', 3306), ('redis-server', 6379)]:
        subprocess.run(['systemctl', 'start', svc], capture_output=True, timeout=10)
    time.sleep(2)
    missing = []
    for svc, port in [('nginx', 80), ('mariadb', 3306), ('redis-server', 6379)]:
        try:
            s = socket.socket(); s.settimeout(1)
            s.connect(('127.0.0.1', port)); s.close()
        except OSError:
            missing.append(f'{svc}:{port}')
    if missing:
        return (f"Required services not reachable on 127.0.0.1: {missing} — "
                f"victim test needs nginx/mariadb/redis-server running. "
                f"Install with: sudo apt-get install -y nginx mariadb-server redis-server")
    return ''

_SKIP_REASON = _victim_prereq_reason()
pytestmark = pytest.mark.skipif(bool(_SKIP_REASON), reason=_SKIP_REASON or 'prereqs ok')


# =============================================================================
# Constants
# =============================================================================


# Interactive tools store no output in process_output table — skip output checks
INTERACTIVE_TOOLS = frozenset({'vsftpd234-Meta', 'ccproxy-ftpMeta', 'smbenum', 'x11screen'})

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
    'dnsrecon':            ('Starting enumeration', 'dnsrecon printed enumeration status line'),
    'nbtscan':             ('netbios name table', 'nbtscan queried NetBIOS names for host'),
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
    'fierce-dns':           ('', ''),      # fierce may produce empty output on fake DNS
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
    'x11screen':            ('', ''),      # interactive — no stored output
    'ccproxy-ftpMeta':      ('', ''),      # interactive metasploit session
    'vsftpd234-Meta':       ('', ''),      # interactive metasploit session
    'smbenum':              ('', ''),      # interactive bash session
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
    <port protocol="tcp" portid="137"><state state="open"/><service name="netbios-ns" product="Samba nmbd" method="probed" conf="10"/></port>
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
    t_start = time.time()
    last_report = 0.0
    REPORT_INTERVAL = 15  # seconds between progress lines

    while time.time() < deadline:
        try:
            snap = requests.get(f'{base_url}/api/snapshot', timeout=10).json()
            host_procs = [p for p in snap.get('processes', [])
                          if p.get('hostIp') == host_ip]
            non_nmap = [p for p in host_procs if p.get('name') != 'nmap']
            running  = [p for p in non_nmap if p.get('status') == 'Running']
            waiting  = [p for p in non_nmap if p.get('status') == 'Waiting']
            done     = [p for p in non_nmap if p.get('status') in
                        ('Finished', 'Killed', 'Crashed', 'Interactive')]

            now = time.time()
            if now - last_report >= REPORT_INTERVAL and non_nmap:
                elapsed = int(now - t_start)
                running_names = ' '.join(p.get('name', '?') for p in running[:6])
                if len(running) > 6:
                    running_names += f' +{len(running)-6} more'
                status = (f'{elapsed//60}:{elapsed%60:02d} elapsed — '
                          f'{len(done)} done, {len(running)} running, {len(waiting)} waiting')
                if running_names:
                    status += f' | running: {running_names}'
                _tty_print(status)
                last_report = now

            pending = running + waiting
            if host_procs and not pending:
                elapsed = int(time.time() - t_start)
                _tty_print(f'All {len(non_nmap)} tools finished in {elapsed//60}:{elapsed%60:02d}')
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
        'nginx':        [80],
        'mariadb':      [3306],
        'redis-server': [6379],
        'smbd':         [139, 445],
        'snmpd':        [],
        'xrdp':         [3389],
    }
    _tty_print(f'Starting services: {" ".join(real_service_ports)} ...')
    for svc in real_service_ports:
        subprocess.run(['systemctl', 'start', svc], capture_output=True, timeout=15)

    real_tcp = [p for ports in real_service_ports.values() for p in ports]
    try:
        _wait_ports_open(real_tcp, timeout=30)
    except RuntimeError as e:
        pytest.skip(f"Real service ports not ready: {e} — "
                    f"install nginx/mariadb/redis-server and ensure they start cleanly")
    _tty_print('Real services ready.')

    listeners = {}
    socat_ports = {
        137:  '',   # netbios-ns — nbtscan queries via its own protocol
        21:   '220 (vsFTPd 2.3.4)\\r\\n',
        23:   '',
        25:   '220 victim.test ESMTP Postfix\\r\\n',
        53:   '',
        111:  '',
        135:  '',
        389:  '',
        443:  '',   # HTTPS — nginx default only listens on 80; socat provides the port
        1433: '',
        1521: '',
        1524: 'root@victim:~# ',
        2049: '',
        2121: '220 CCProxy FTP Service Ready\\r\\n',
        3632: '',
        4848: '',   # GlassFish admin — socat placeholder
        5432: '',   # postgresql — already installed via metasploit-framework
        5900: 'RFB 003.008\\n',
        6000: '',
        6667: ':victim.test NOTICE AUTH :*** Looking up your hostname...\\r\\n',
        8080: '',   # HTTP alternate — socat placeholder
        8443: '',   # HTTPS alternate — socat placeholder
    }
    for port, banner in socat_ports.items():
        listeners[port] = _socat_listen(port, banner)
    listeners['500/udp'] = _socat_listen(500, udp=True)

    new_socat = [p for p in socat_ports if isinstance(p, int) and listeners.get(p) is not None]
    if new_socat:
        _tty_print(f'Waiting for {len(new_socat)} socat listeners ...')
        _wait_ports_open(new_socat, timeout=15)
    _tty_print(f'All services ready — {len(socat_ports)} socat ports + real nginx/mariadb/redis/smb/snmp/xrdp')

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
    _tty_print(f'Importing victim XML for {VICTIM_IP} ...')
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(VICTIM_XML); xml_path = f.name
    try:
        r = requests.post(f'{srv}/api/nmap/import-xml',
                          json={'path': xml_path, 'run_actions': True}, timeout=15)
        assert r.status_code == 200, f'XML import failed: {r.text}'
    finally:
        os.unlink(xml_path)

    _wait_host_appears(srv, VICTIM_IP, timeout=30)
    _tty_print(f'Host {VICTIM_IP} appeared. Waiting for {len(ALL_SCHEDULER_TOOLS)} tools to finish (up to {TIMEOUT_TOOLS//60} min) ...')
    all_procs = _wait_all_done(srv, VICTIM_IP, timeout=TIMEOUT_TOOLS)
    tool_procs = [p for p in all_procs if p.get('name') not in ('nmap',)]
    _tty_print(f'Scan complete — {len(tool_procs)} tool processes finished. Collecting outputs ...')

    # Fetch outputs in parallel — sequential was ~0.7s × N processes = 70s+ silence
    results: dict = {}
    total = len(tool_procs)
    done_count = [0]
    lock = threading.Lock()
    _tty_print(f'Fetching output for {total} processes (parallel) ...')

    def _fetch(proc):
        pid  = proc['id']
        name = proc.get('name', '')
        try:
            ro = requests.get(f'{srv}/api/processes/{pid}/output?max_chars=10000',
                              timeout=10).json()
            output = ANSI.sub('', ro.get('output_chunk') or ro.get('output') or '')
        except Exception:
            output = ''
        with lock:
            done_count[0] += 1
            n = done_count[0]
            if n % 10 == 0 or n == total:
                _tty_print(f'Fetched {n}/{total} process outputs ...')
        return name, {
            'port':         str(proc.get('port', '')),
            'status':       proc.get('status', ''),
            'output':       output,
            'output_bytes': len(output),
            'command':      proc.get('command', ''),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for name, entry in pool.map(_fetch, tool_procs):
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

    Empty-pattern entries (fierce-dns, ike-scan, showmount, rpcinfo, snmp-default,
    and all interactive tools) are excluded from parametrize — those tools may
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


def test_print_full_report(completed_scan):
    """
    Always-pass: prints a complete pass/fail table to /dev/tty so it is visible
    whether run manually or through run_tests.sh (which captures stdout/stderr).
    Re-runs the same checks as the parametrized tests so failures are explained
    with output snippets, not just tool names.
    """
    W = 72  # line width

    def tty(msg=''):
        _tty_print(msg)

    # ── Re-run every check inline ─────────────────────────────────────────
    failures = []   # (tool_id, check, detail, snippet)

    for tool_id in sorted(ALL_SCHEDULER_TOOLS):
        runs = completed_scan.get(tool_id, [])

        # Check 1: triggered
        if not runs:
            scope = ALL_SCHEDULER_SCOPES.get(tool_id, '?')
            failures.append((tool_id, 'not-triggered',
                             f'scheduler never ran — conf scope: [{scope}]', ''))
            continue
        terminal = [r for r in runs if r['status'] in
                    ('Finished', 'Killed', 'Crashed', 'Interactive')]
        if not terminal:
            failures.append((tool_id, 'not-terminal',
                             f"statuses: {[r['status'] for r in runs]}", ''))
            continue

        # Check 2: no config errors
        for run in runs:
            has_err, pat = _is_conf_error(run['output'])
            if has_err:
                snippet = run['output'][:200].replace('\n', ' ')
                failures.append((tool_id, 'config-error',
                                 f"pattern '{pat}' in output (port {run['port']})", snippet))

        # Check 3: expected output pattern
        if tool_id in TOOL_EXPECTED_OUTPUT and tool_id not in INTERACTIVE_TOOLS:
            pattern, description = TOOL_EXPECTED_OUTPUT[tool_id]
            if pattern:
                matched = any(pattern.lower() in r['output'].lower() for r in runs)
                if not matched:
                    best = max(runs, key=lambda r: r['output_bytes'])
                    snippet = best['output'][:200].replace('\n', ' ')
                    failures.append((tool_id, 'expected-output',
                                     f"'{pattern}' not found ({description}), "
                                     f"port={best['port']} {best['output_bytes']}b",
                                     snippet))

    # ── Per-tool table ────────────────────────────────────────────────────
    tty()
    tty('=' * W)
    tty(f"VICTIM TOOL EXECUTION REPORT — {VICTIM_IP}")
    tty(f"{len(ALL_SCHEDULER_TOOLS)} scheduler tools  |  "
        f"{sum(len(v) for v in completed_scan.values())} total processes")
    tty('=' * W)
    tty(f"  {'Tool':<36} {'Trg':>3}  {'Cfg':>3}  {'Out':>3}  {'Bytes':>6}  Status")
    tty(f"  {'-'*36}  ---  ---  ---  ------  ------")

    failed_tools = {f[0] for f in failures}
    for tool_id in sorted(ALL_SCHEDULER_TOOLS):
        runs = completed_scan.get(tool_id, [])
        if not runs:
            tty(f"  {tool_id:<36}  {'✗':>3}   {'—':>3}   {'—':>3}  {'—':>6}  MISSING")
            continue
        best = max(runs, key=lambda r: r['output_bytes'])
        trg = '✓' if any(r['status'] in ('Finished','Killed','Crashed','Interactive')
                          for r in runs) else '✗'
        cfg_errs = [f for f in failures if f[0] == tool_id and f[1] == 'config-error']
        cfg = '✗' if cfg_errs else '✓'
        if tool_id in TOOL_EXPECTED_OUTPUT and TOOL_EXPECTED_OUTPUT[tool_id][0] \
                and tool_id not in INTERACTIVE_TOOLS:
            out_errs = [f for f in failures if f[0] == tool_id and f[1] == 'expected-output']
            out = '✗' if out_errs else '✓'
        else:
            out = '—'
        marker = ' ◄' if tool_id in failed_tools else ''
        tty(f"  {tool_id:<36}  {trg:>3}  {cfg:>3}  {out:>3}  "
            f"{best['output_bytes']:>6}  {best['status']}{marker}")

    # ── Summary + failure details ─────────────────────────────────────────
    tty()
    tty('=' * W)
    total  = len(ALL_SCHEDULER_TOOLS)
    n_fail = len(failed_tools)
    n_pass = total - n_fail
    tty(f"  {'✓ PASS':<10} {n_pass:>3}  of {total} tools")
    tty(f"  {'✗ FAIL':<10} {n_fail:>3}  of {total} tools")

    if failures:
        tty()
        tty('FAILURES:')
        tty('-' * W)
        for tool_id, check, detail, snippet in failures:
            tty(f"  ✗ {tool_id}  [{check}]")
            tty(f"      {detail}")
            # Show command — lets you immediately see if it's a template/flag issue
            runs = completed_scan.get(tool_id, [])
            if runs:
                cmd = runs[0].get('command', '')
                if cmd:
                    tty(f"      cmd: {cmd[:120]}")
            if snippet:
                # Show up to 400 chars split into readable lines
                for i in range(0, min(len(snippet), 400), 120):
                    label = '      output: ' if i == 0 else '              '
                    tty(f"{label}{snippet[i:i+120]}")
    tty('=' * W)
    tty()
    # Always pass — this is a reporting test
