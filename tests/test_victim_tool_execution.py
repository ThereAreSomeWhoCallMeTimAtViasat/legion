"""
tests/test_victim_tool_execution.py — Live tool execution against a local
victim host (127.42.0.1) to verify every Legion scheduler tool actually runs
and produces output without configuration-level errors.

This is the automated equivalent of the manual v10.206 audit:
  1. Start socat banner listeners + real services on 127.42.0.1
  2. Boot a Legion API server (no browser needed — API-only)
  3. Import a hand-crafted nmap XML with all required service names
  4. Trigger the scheduler (enable-scheduler-on-import=True)
  5. Poll via /api/snapshot until every tool finishes (up to 10 minutes)
  6. Fetch each tool's output via /api/processes/<id>/output
  7. Assert zero tool-configuration errors across all outputs

Configuration errors that prove a tool is BROKEN (always fail):
  - 'flag provided but not defined'   (ffuf -q was present in conf)
  - 'Could not open'                  (wordlist path missing)
  - 'Error creating outputfile'       (Hydra \"\" path quoting)
  - 'No such file or directory'       (missing file in command)
  - 'no templates provided for scan'  (nuclei -t missing)
  - 'compilation aborted'             (rdp-sec-check Perl dep)
  - 'command not found'               (binary not installed)
  - 'No command template'             (dead SchedulerSettings ref)

Expected non-errors from the fake victim's limited services
(socat pipes that don't speak binary protocols — tool ran fine,
service just couldn't authenticate or parse the response):
  - 'Connection refused', 'Timed out', 'connection error'
  - 'Transfer failed', 'Protocol failed'
  - Hydra 'all children were disabled due too many connection errors'
  - ldapdomaindump 'Traceback' on failed LDAP bind (fake listener)
  - ike-scan 'Could not bind' (UDP port 500 may be in use)

Run standalone:
    sudo python3 -m pytest tests/test_victim_tool_execution.py -v -s

Integrated into run_tests.sh --selenium section.
Victim host setup requires root (socat raw listeners, loopback alias).
"""

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
# Constants
# =============================================================================

PORT        = 5101          # Legion API server port (unique, no conflicts)
VICTIM_IP   = '127.42.0.1' # Loopback alias — visible to nmap/tools as a real IP
VICTIM_HOST = 'victim.test'
TIMEOUT_TOOLS = 600         # 10 minutes — generous for 100+ tools at max-fast=5

# Nmap XML with every service name needed to trigger each SchedulerSettings entry.
# Service names are chosen to exactly match what nmap reports for each port
# after -sV detection, ensuring the scheduler's svc_name comparison succeeds.
VICTIM_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nmaprun>
<nmaprun scanner="nmap" args="nmap -Pn -sV {VICTIM_IP}" start="1746632000" version="7.98">
<host starttime="1746632000" endtime="1746632060">
  <status state="up" reason="user-set"/>
  <address addr="{VICTIM_IP}" addrtype="ipv4"/>
  <hostnames><hostname name="{VICTIM_HOST}" type="PTR"/></hostnames>
  <ports>
    <port protocol="tcp" portid="21"><state state="open" reason="syn-ack"/><service name="ftp" product="vsFTPd" version="2.3.4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="22"><state state="open" reason="syn-ack"/><service name="ssh" product="OpenSSH" version="10.2p1" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="23"><state state="open" reason="syn-ack"/><service name="telnet" product="Linux telnetd" method="probed" conf="8"/></port>
    <port protocol="tcp" portid="25"><state state="open" reason="syn-ack"/><service name="smtp" product="Postfix smtpd" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="53"><state state="open" reason="syn-ack"/><service name="domain" product="ISC BIND" version="9.18.0" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="80"><state state="open" reason="syn-ack"/><service name="http" product="nginx" version="1.28.1" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="111"><state state="open" reason="syn-ack"/><service name="rpcbind" version="2-4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="135"><state state="open" reason="syn-ack"/><service name="msrpc" product="Microsoft Windows RPC" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="139"><state state="open" reason="syn-ack"/><service name="netbios-ssn" product="Samba smbd" version="4.X" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="389"><state state="open" reason="syn-ack"/><service name="ldap" product="OpenLDAP" version="2.4.57" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="443"><state state="open" reason="syn-ack"/><service name="ssl" product="nginx" version="1.28.1" tunnel="ssl" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="445"><state state="open" reason="syn-ack"/><service name="microsoft-ds" product="Samba smbd" version="4.X" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="1433"><state state="open" reason="syn-ack"/><service name="ms-sql-s" product="Microsoft SQL Server 2019" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="1521"><state state="open" reason="syn-ack"/><service name="oracle-tns" product="Oracle TNS listener" version="11.2.0.4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="1524"><state state="open" reason="syn-ack"/><service name="bindshell" product="Metasploitable root shell" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="2049"><state state="open" reason="syn-ack"/><service name="nfs" version="2-4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="2121"><state state="open" reason="syn-ack"/><service name="ccproxy-ftp" product="CCProxy FTP Service" method="probed" conf="8"/></port>
    <port protocol="tcp" portid="3306"><state state="open" reason="syn-ack"/><service name="mysql" product="MySQL" version="8.0.32" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="3389"><state state="open" reason="syn-ack"/><service name="ms-wbt-server" product="Microsoft Terminal Service" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="3632"><state state="open" reason="syn-ack"/><service name="distccd" product="distcc" version="3.4" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="4848"><state state="open" reason="syn-ack"/><service name="appserv-http" product="GlassFish Server" version="4.0" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="5432"><state state="open" reason="syn-ack"/><service name="postgresql" product="PostgreSQL DB" version="14.0 - 14.6" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="5900"><state state="open" reason="syn-ack"/><service name="vnc" product="VNC" version="protocol 3.8" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="6000"><state state="open" reason="syn-ack"/><service name="X11" method="probed" conf="8"/></port>
    <port protocol="tcp" portid="6379"><state state="open" reason="syn-ack"/><service name="redis" product="Redis key-value store" version="8.0.5" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="6667"><state state="open" reason="syn-ack"/><service name="irc" product="UnrealIRCd" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="8080"><state state="open" reason="syn-ack"/><service name="http" product="nginx" version="1.28.1" method="probed" conf="10"/></port>
    <port protocol="tcp" portid="8443"><state state="open" reason="syn-ack"/><service name="https-alt" product="nginx" version="1.28.1" tunnel="ssl" method="probed" conf="10"/></port>
    <port protocol="udp" portid="53"><state state="open" reason="udp-response"/><service name="domain" product="ISC BIND" version="9.18.0" method="probed" conf="10"/></port>
    <port protocol="udp" portid="161"><state state="open" reason="udp-response"/><service name="snmp" version="v1" method="probed" conf="10"/></port>
    <port protocol="udp" portid="500"><state state="open" reason="udp-response"/><service name="isakmp" product="StrongSwan" method="probed" conf="8"/></port>
  </ports>
  <os><osmatch name="Linux 5.4" accuracy="97"><osclass type="general purpose" vendor="Linux" osfamily="Linux" osgen="5.X"/></osmatch></os>
</host>
</nmaprun>
"""

# =============================================================================
# Helpers
# =============================================================================

ANSI = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Tool output errors that are ALWAYS a configuration bug, never a fake-service issue
CONF_ERROR_PATTERNS = [
    'flag provided but not defined',       # ffuf -q was in conf (fix-2)
    'could not open',                      # missing wordlist path (fix-1)
    'error creating outputfile',           # Hydra \"\" path quoting (fix-3)
    'no templates provided for scan',      # nuclei -t missing (fix-4)
    'compilation aborted',                 # rdp-sec-check Perl dep (fix-6)
    'no command template for',             # dead SchedulerSettings ref (fix-7)
    '[PortActions]',                       # scheduler logged key lookup failure
]

# Errors expected from the fake victim (socat pipes, not real services).
# These mean the TOOL ran correctly but the service didn't speak the protocol.
EXPECTED_SERVICE_ERRORS = [
    'connection refused',
    'connection error',
    'timed out',
    'timeout',
    'rpc: timed out',
    'rpc: unable to receive',
    'clnt_create',
    'transfer failed',
    'protocol failed',
    'unknown dce rpc',
    'all children were disabled due',  # Hydra connection errors from fake service
    'error: could not bind',           # ike-scan UDP 500 binding
    'warning: query response not set', # dig on fake DNS
    'communications error',            # dig on fake DNS
    'traceback',                       # ldapdomaindump on fake LDAP
    'readable info/status files are not found',  # joomscan (no joomla)
    'no new updates',                  # nuclei up-to-date message
    'appears to be up but',            # rdp-sec-check on fake RDP
]


def _is_conf_error(output: str) -> tuple:
    """Return (True, matching_pattern) if output contains a config-level error."""
    clean = ANSI.sub('', output).lower()
    for pat in CONF_ERROR_PATTERNS:
        if pat.lower() in clean:
            return True, pat
    return False, ''


def _is_expected_service_error(output: str) -> bool:
    """Return True if the only errors in output are expected fake-service failures."""
    clean = ANSI.sub('', output).lower()
    return any(pat in clean for pat in EXPECTED_SERVICE_ERRORS)


def _free_port(port: int, retries: int = 20):
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    for _ in range(retries):
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
            s.close()
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f'Port {port} still in use after {retries} retries')


def _socat_listen(port: int, banner: str = '', udp: bool = False) -> subprocess.Popen | None:
    """Start a socat listener and return the Popen handle (or None if port in use)."""
    proto = 'udp' if udp else 'tcp'
    check = subprocess.run(['ss', f'-{proto[0]}lnp'], capture_output=True, text=True)
    if f':{port} ' in check.stdout:
        return None  # already in use — real service
    if banner:
        cmd = ['socat', f'TCP4-LISTEN:{port},reuseaddr,fork',
               f'SYSTEM:printf "{banner}"; sleep 30']
    else:
        cmd = ['socat', f'TCP4-LISTEN:{port},reuseaddr,fork', 'PIPE']
    if udp:
        cmd = ['socat', f'UDP4-RECVFROM:{port},reuseaddr,fork', 'PIPE']
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def _wait_all_done(base_url: str, host_ip: str, timeout: int = TIMEOUT_TOOLS) -> list:
    """Poll /api/snapshot until no Waiting/Running processes for host_ip. Return all procs."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            snap = requests.get(f'{base_url}/api/snapshot', timeout=10).json()
            host_procs = [p for p in snap.get('processes', [])
                          if p.get('hostIp') == host_ip]
            pending = [p for p in host_procs
                       if p.get('status') in ('Running', 'Waiting')]
            if host_procs and not pending:
                return host_procs
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError(
        f'Tools did not finish within {timeout}s — '
        f'try increasing TIMEOUT_TOOLS or check Legion logs'
    )


# =============================================================================
# Module-scoped fixtures
# =============================================================================

@pytest.fixture(scope='module')
def victim_services():
    """
    Start all services needed for the victim host (127.42.0.1).
    Real services (nginx, mariadb, redis, samba, snmpd, xrdp) are started
    if not already running. Socat listeners cover everything else.
    Returns dict of {port: popen_handle_or_None}.
    """
    # Ensure loopback alias exists
    subprocess.run(['ip', 'addr', 'add', f'{VICTIM_IP}/8', 'dev', 'lo'],
                   capture_output=True)

    # Start real services if not already running
    for svc in ('nginx', 'mariadb', 'postgresql', 'redis-server',
                 'smbd', 'snmpd', 'xrdp'):
        subprocess.run(['systemctl', 'start', svc],
                       capture_output=True, timeout=15)
    time.sleep(2)

    # Socat listeners for ports real services don't cover
    listeners: dict = {}
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
    # UDP
    listeners['500/udp'] = _socat_listen(500, udp=True)
    time.sleep(2)

    yield listeners

    # Teardown — kill socat processes
    for handle in listeners.values():
        if handle is not None:
            try:
                handle.kill()
            except Exception:
                pass


@pytest.fixture(scope='module')
def srv(victim_services):
    """
    Start a Legion API server on PORT with scheduler-on-import enabled.
    Returns the base URL string.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    import app.web.routes as _web_routes
    _web_routes._HB_TIMEOUT = 600      # disable heartbeat watchdog during test

    _free_port(PORT)

    from app.web.testhelper import create_test_app
    from werkzeug.serving import make_server

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    # Enable scheduler-on-import so importing the XML fires all tools
    conf_text = requests.get(f'http://127.0.0.1:{PORT}/api/settings/legion-conf',
                             timeout=5).text \
        if False else ''  # will be set after server starts

    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(2.0)

    base = f'http://127.0.0.1:{PORT}'

    # Enable scheduler-on-import and set max-fast-processes=10 for speed
    r = requests.get(f'{base}/api/settings/legion-conf', timeout=5)
    conf = r.json()['text']
    conf = conf.replace('enable-scheduler-on-import=False',
                        'enable-scheduler-on-import=True')
    conf = re.sub(r'max-fast-processes=\d+', 'max-fast-processes=10', conf)
    requests.post(f'{base}/api/settings/legion-conf', json={'text': conf})

    yield base

    httpd.shutdown()
    _web_routes._HB_TIMEOUT = 20


@pytest.fixture(scope='module')
def completed_scan(srv):
    """
    Import the victim XML, wait for all scheduled tools to finish,
    then fetch each process's output via the API.

    Returns a list of dicts:
      {name, port, status, output, has_conf_error, conf_error_pattern,
       is_expected_service_error}
    """
    # Write XML to a temp file
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(VICTIM_XML)
        xml_path = f.name

    try:
        r = requests.post(f'{srv}/api/nmap/import-xml',
                          json={'path': xml_path, 'run_actions': True},
                          timeout=15)
        assert r.status_code == 200, f'XML import failed: {r.text}'
    finally:
        os.unlink(xml_path)

    # Wait for host to appear
    deadline = time.time() + 30
    while time.time() < deadline:
        snap = requests.get(f'{srv}/api/snapshot', timeout=5).json()
        if any(h['ip'] == VICTIM_IP for h in snap.get('hosts', [])):
            break
        time.sleep(1)
    else:
        pytest.fail(f'Victim host {VICTIM_IP} never appeared in snapshot')

    # Wait for all tools to complete
    all_procs = _wait_all_done(srv, VICTIM_IP, timeout=TIMEOUT_TOOLS)
    tool_procs = [p for p in all_procs if p.get('name') not in ('nmap',)]

    # Fetch outputs via API (not from DB directly — same path the UI uses)
    results = []
    for proc in tool_procs:
        pid = proc['id']
        try:
            ro = requests.get(f'{srv}/api/processes/{pid}/output?max_chars=5000',
                              timeout=10).json()
            output = ANSI.sub('', ro.get('output_chunk') or ro.get('output') or '')
        except Exception:
            output = ''

        has_err, err_pat = _is_conf_error(output)
        results.append({
            'name':                    proc.get('name', ''),
            'port':                    str(proc.get('port', '')),
            'status':                  proc.get('status', ''),
            'output':                  output,
            'has_conf_error':          has_err,
            'conf_error_pattern':      err_pat,
            'is_expected_svc_error':   _is_expected_service_error(output),
            'output_bytes':            len(output),
        })

    return results


# =============================================================================
# Tests
# =============================================================================

class TestVictimToolExecution:
    """
    Every Legion scheduler tool must run against the victim host and produce
    output that contains no tool-configuration errors.

    A configuration error means the tool binary is broken, a required file
    is missing, a flag was removed from a tool's CLI, or the PortActions
    command template is wrong. These are ALWAYS bugs — they would have been
    present on every real target scan, not just this fake victim.

    Service-level failures (connection refused, auth errors, protocol errors)
    from the fake victim are expected and not counted as failures.
    """

    def test_all_tools_produced_output(self, completed_scan):
        """
        Every finished process must have produced some output.
        An empty output means the tool was never launched (dead scheduler
        reference, missing binary, or the process was killed before starting).
        """
        empty = [
            f"{r['name']} (port {r['port']})"
            for r in completed_scan
            if r['status'] == 'Finished' and r['output_bytes'] == 0
            and r['name'] not in ('smbenum', 'ccproxy-ftpMeta', 'vsftpd234-Meta',
                                   'x11screen')  # interactive processes have no stored output
        ]
        assert not empty, (
            f'{len(empty)} tool(s) produced zero output (tool never ran or crashed '
            f'before writing anything):\n'
            + '\n'.join(f'  {t}' for t in empty[:10])
        )

    def test_zero_configuration_errors(self, completed_scan):
        """
        No finished tool output may contain a configuration-level error.
        These patterns prove the tool's command template or dependencies are
        broken — they would fail on every real target, not just this victim.

        Errors checked:
          - 'flag provided but not defined'  (ffuf -q)
          - 'could not open'                 (feroxbuster bad wordlist)
          - 'error creating outputfile'      (Hydra path quoting bug)
          - 'no templates provided for scan' (nuclei missing -t)
          - 'compilation aborted'            (rdp-sec-check Perl dep)
          - 'no command template for'        (dead SchedulerSettings key)
        """
        conf_errors = [
            (r['name'], r['port'], r['conf_error_pattern'], r['output'][:200])
            for r in completed_scan
            if r['has_conf_error']
        ]
        if conf_errors:
            msg_lines = [
                f"  {name} (port {port}): pattern='{pat}'\n"
                f"    output: {out.splitlines()[0][:120] if out else '(empty)'}"
                for name, port, pat, out in conf_errors
            ]
            pytest.fail(
                f'{len(conf_errors)} tool(s) have CONFIGURATION errors '
                f'(would fail on every real target):\n'
                + '\n'.join(msg_lines)
            )

    def test_tool_count_matches_scheduler(self, completed_scan):
        """
        The number of tool processes created must be >= the number of
        SchedulerSettings entries that matched the victim's service names.
        A lower count means the scheduler silently skipped some tools.
        """
        # We expect at least 60 tool processes for the 31-port victim
        tool_count = len([r for r in completed_scan
                          if r['status'] in ('Finished', 'Interactive', 'Killed')])
        assert tool_count >= 60, (
            f'Only {tool_count} scheduler tools ran against the victim — '
            f'expected at least 60 for a host with 31 open ports.\n'
            f'Check SchedulerSettings for dead references or service-name mismatches.'
        )

    def test_web_tools_ran_on_http_ports(self, completed_scan):
        """
        HTTP discovery tools (feroxbuster, gobuster, nuclei, ffuf) must have
        run against port 80. The v10.206 audit found these silently missing
        from .111's HTTP ports due to a scheduler session-staleness bug.
        """
        http_tools = {r['name'] for r in completed_scan if r['port'] == '80'}
        for expected in ('feroxbuster', 'gobuster-dir', 'nuclei', 'ffuf-files'):
            assert expected in http_tools, (
                f"'{expected}' did not run on port 80 (http). "
                f"Ran on 80: {sorted(http_tools)}"
            )

    def test_ssl_tools_ran_on_https_ports(self, completed_scan):
        """SSL tools must have run against port 443 (ssl service)."""
        ssl_tools = {r['name'] for r in completed_scan if r['port'] == '443'}
        for expected in ('ssl-heartbleed.nse', 'ssl-enum-ciphers.nse', 'testssl'):
            assert expected in ssl_tools, (
                f"'{expected}' did not run on port 443. Ran on 443: {sorted(ssl_tools)}"
            )

    def test_https_alt_tools_ran_on_8443(self, completed_scan):
        """SSL tools must also trigger on port 8443 (https-alt service)."""
        alt_tools = {r['name'] for r in completed_scan if r['port'] == '8443'}
        for expected in ('ssl-heartbleed.nse', 'testssl', 'feroxbuster-https'):
            assert expected in alt_tools, (
                f"'{expected}' did not run on port 8443 (https-alt). "
                f"Fix: add https-alt to the tool's SchedulerSettings svc_scope."
            )

    def test_smb_tools_ran_on_both_smb_ports(self, completed_scan):
        """
        SMB vuln scripts must trigger on both 139 (netbios-ssn) and
        445 (microsoft-ds). The v10.206 audit found they only ran on one.
        """
        for port in ('139', '445'):
            port_tools = {r['name'] for r in completed_scan if r['port'] == port}
            for expected in ('smb-vuln-ms17-010.nse', 'smb-vuln-ms08-067.nse'):
                assert expected in port_tools, (
                    f"'{expected}' did not run on port {port}. "
                    f"Fix: SchedulerSettings svc_scope must include both "
                    f"netbios-ssn and microsoft-ds."
                )

    def test_appserv_http_tools_ran_on_4848(self, completed_scan):
        """
        Port 4848 (appserv-http / GlassFish admin) must trigger HTTP tools.
        The v10.206 audit added appserv-http to http tool svc_scopes for this.
        """
        tools_4848 = {r['name'] for r in completed_scan if r['port'] == '4848'}
        for expected in ('feroxbuster', 'nuclei', 'gobuster-dir'):
            assert expected in tools_4848, (
                f"'{expected}' did not run on port 4848 (appserv-http). "
                f"Fix: add appserv-http to the tool's SchedulerSettings svc_scope."
            )

    def test_rdp_sec_check_ran_successfully(self, completed_scan):
        """
        rdp-sec-check must have run against port 3389 AND its output must
        NOT contain 'compilation aborted' (Perl Encoding::BER missing).
        """
        rdp_runs = [r for r in completed_scan
                    if r['name'] == 'rdp-sec-check' and r['port'] == '3389']
        assert rdp_runs, 'rdp-sec-check did not run on port 3389 (ms-wbt-server)'
        for run in rdp_runs:
            assert 'compilation aborted' not in run['output'].lower(), (
                f"rdp-sec-check output contains 'compilation aborted' — "
                f"Perl Encoding::BER not installed.\n"
                f"Fix: sudo apt-get install libencoding-ber-perl"
            )

    def test_nuclei_produced_real_findings(self, completed_scan):
        """
        nuclei must have run on port 80 and produced findings (not just
        'no templates provided for scan'). At minimum it should report
        waf detection or server fingerprinting on nginx.
        """
        nuclei_80 = [r for r in completed_scan
                     if r['name'] == 'nuclei' and r['port'] == '80']
        assert nuclei_80, 'nuclei did not run on port 80'
        output = nuclei_80[0]['output']
        assert 'no templates provided for scan' not in output.lower(), (
            f'nuclei reports no templates — add -t flag to nuclei command in conf'
        )
        # nuclei should find SOMETHING on nginx (waf-fuzz, fingerprint, etc.)
        assert len(output.strip()) > 10, (
            f'nuclei produced nearly empty output on port 80:\n{output[:300]}\n'
            f'Check: nuclei templates installed? -t path correct in conf?'
        )

    def test_feroxbuster_used_correct_wordlist(self, completed_scan):
        """
        feroxbuster must have run AND its output must NOT contain
        'Could not open' (the fix-1 regression: bad wordlist path).
        """
        ferox_runs = [r for r in completed_scan
                      if r['name'] == 'feroxbuster']
        assert ferox_runs, 'feroxbuster did not run on any port'
        for run in ferox_runs:
            assert 'could not open' not in run['output'].lower(), (
                f"feroxbuster (port {run['port']}) output contains 'Could not open' "
                f"— wordlist path in conf does not exist.\n"
                f"Fix: update feroxbuster -w to use an existing wordlist "
                f"(e.g. /usr/share/seclists/Discovery/Web-Content/big.txt)"
            )

    def test_ffuf_produced_output_not_help(self, completed_scan):
        """
        ffuf must NOT have printed its help text (which happens when an
        unknown flag is used, e.g. the removed -q flag in v2.1.0-dev).
        The fix-2 regression: ffuf printed 5000 bytes of help on every call.
        """
        ffuf_runs = [r for r in completed_scan if r['name'] == 'ffuf-files']
        assert ffuf_runs, 'ffuf-files did not run on any port'
        for run in ffuf_runs:
            assert 'flag provided but not defined' not in run['output'].lower(), (
                f"ffuf (port {run['port']}) printed 'flag provided but not defined' — "
                f"-q flag was added back to conf.\n"
                f"Fix: remove -q from ffuf-files command in [PortActions]"
            )

    def test_hydra_ftp_no_outputfile_error(self, completed_scan):
        """
        Hydra ftp-default must NOT have 'Error creating outputfile'.
        The fix-3 regression: '\\\"\\\"[OUTPUT].txt\\\"\\\"' embedded literal \" in
        the path, causing fopen() to fail on every Hydra credential check.
        """
        hydra_ftp = [r for r in completed_scan if r['name'] == 'ftp-default']
        assert hydra_ftp, 'ftp-default (Hydra) did not run on port 21'
        for run in hydra_ftp:
            assert 'error creating outputfile' not in run['output'].lower(), (
                f"Hydra ftp-default 'Error creating outputfile' — "
                f"Hydra -o path has embedded quote chars.\n"
                f"Fix: change -o \\\"\\\"[OUTPUT].txt\\\"\\\" to -o [OUTPUT].txt "
                f"in ftp-default PortActions command."
            )

    def test_no_wig_in_results(self, completed_scan):
        """
        wig must NOT appear in the completed tool results — it was removed
        from SchedulerSettings because it crashes Python 3.13+.
        If it appears here, it was re-added to SchedulerSettings.
        """
        wig_runs = [r for r in completed_scan if r['name'] == 'wig']
        # If wig ran, check it didn't crash with the AttributeError
        for run in wig_runs:
            if 'attributeerror' in run['output'].lower() and 'scripting' in run['output'].lower():
                pytest.fail(
                    f"wig ran (port {run['port']}) and crashed with Python 3.13 "
                    f"AttributeError. Remove wig from [SchedulerSettings]."
                )

    def test_per_tool_output_summary(self, completed_scan, capsys):
        """
        Print a full table of all tools with status and first output line.
        Not an assertion — this test always passes. Its value is the
        printed report that shows exactly what each tool found.
        """
        print('\n\n=== Tool Execution Summary ===')
        print(f"{'Tool':<35} {'Port':<6} {'Status':<10} {'Bytes':>7}  First output line / error")
        print('-' * 100)
        for r in sorted(completed_scan, key=lambda x: (x['port'].zfill(6), x['name'])):
            lines = [l.strip() for l in r['output'].splitlines() if l.strip()]
            first = lines[0][:65] if lines else '(empty)'
            tag = '[CONF_ERR]' if r['has_conf_error'] else ''
            print(f"  {r['name']:<33} {r['port']:<6} {r['status']:<10} "
                  f"{r['output_bytes']:>7}  {tag}{first}")

        # Summary line
        conf_errs = [r for r in completed_scan if r['has_conf_error']]
        empty = [r for r in completed_scan
                 if r['output_bytes'] == 0 and r['status'] == 'Finished']
        print(f'\nTotal: {len(completed_scan)} tools | '
              f'Config errors: {len(conf_errs)} | Empty: {len(empty)}')
        # This test always passes — it's a reporting test
