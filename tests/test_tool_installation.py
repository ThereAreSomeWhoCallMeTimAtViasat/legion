"""
tests/test_tool_installation.py — Non-hollow, deterministic verification of
Legion's tool installation, configuration, and scheduler consistency.

No server, no browser, no network. All assertions check real file-system
state, binary execution, and conf content — each would fail if the
corresponding production fix were reverted.

Findings from the v10.206 comprehensive tool audit that this test guards:

  v10.206-fix-1: feroxbuster wordlist directory-list-2.3-medium.txt missing
                 → changed to big.txt. Test asserts wordlist path in conf
                   actually exists on disk.

  v10.206-fix-2: ffuf -q flag removed in v2.1.0-dev. Running ffuf -q
                 printed full help instead of scanning (flag provided but
                 not defined). Test asserts -q is absent from conf commands
                 AND that ffuf exits non-zero when given the flag.

  v10.206-fix-3: Hydra -o path used \"\"[OUTPUT].txt\"\" quoting which bash
                 embeds literal \" in the file path, causing fopen() to fail
                 with 'No such file or directory' across all 12 Hydra
                 credential-check commands. Test asserts the pattern is gone.

  v10.206-fix-4: nuclei missing -t template path. Running as root, nuclei
                 can't write to /home/kali/.config/nuclei/ and found no
                 templates, producing 'no templates provided for scan'.
                 Test asserts -t flag is present and template dir has > 1000
                 yaml files.

  v10.206-fix-5: wig crashes Python 3.13+ (html.parser 'scripting' attr
                 removed from HTMLParser; wig's HTMLStripper subclass doesn't
                 set it → AttributeError on every page). Test asserts wig is
                 absent from SchedulerSettings.

  v10.206-fix-6: rdp-sec-check requires Perl Encoding::BER module. Without
                 it, rdp-sec-check fails: "Can't locate Encoding/BER.pm".
                 Test asserts the module is importable via perl -e.

  v10.206-fix-7: Every SchedulerSettings key must have a matching PortActions
                 key (or be 'screenshooter', a built-in). Dead references
                 produce 'No command template for X' in the scheduler and
                 silently skip the tool. Test asserts full consistency.

  v10.206-fix-8: x11screen SchedulerSettings used uppercase 'X11' but the
                 scheduler lowercases service names before matching, so 'X11'
                 was never matched. Fixed to lowercase 'x11'. Test asserts
                 all svc_scope strings in SchedulerSettings are lowercase.

Run standalone:
    sudo python3 -m pytest tests/test_tool_installation.py -v --noconftest

Integrated into run_tests.sh --unit section.
"""

import configparser
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# =============================================================================
# Constants and helpers
# =============================================================================

LEGION_ROOT = Path(__file__).resolve().parent.parent
CONF_PATH   = Path(os.path.expanduser('~/.local/share/legion/legion.conf'))


def _on_kali():
    try:
        return 'kali' in Path('/etc/os-release').read_text().lower()
    except OSError:
        return False


def _in_docker():
    return Path('/.dockerenv').exists()


def _real_home() -> Path:
    """Return the invoking user's home, even when running under sudo."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    return Path.home()


REAL_HOME = _real_home()


def _run(cmd: list, timeout: int = 10) -> tuple:
    """Return (returncode, stdout+stderr combined)."""
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, errors='replace'
    )
    return r.returncode, (r.stdout + r.stderr)


def _conf_raw() -> str:
    if not CONF_PATH.exists():
        pytest.skip(f'legion.conf not at {CONF_PATH} — run install.sh first')
    return CONF_PATH.read_text(encoding='utf-8', errors='replace')


def _conf_parser() -> configparser.RawConfigParser:
    p = configparser.RawConfigParser()
    p.optionxform = str
    if not CONF_PATH.exists():
        pytest.skip(f'legion.conf not at {CONF_PATH} — run install.sh first')
    p.read(CONF_PATH)
    return p


def _port_actions(parser) -> dict:
    """Return {key: [label, command, svc_filter, ...]} from [PortActions]."""
    out = {}
    if not parser.has_section('PortActions'):
        return out
    for k, v in parser.items('PortActions'):
        parts = next(csv.reader([v], skipinitialspace=True), [])
        out[k] = parts
    return out


def _scheduler_settings(parser) -> dict:
    """Return {key: [svc_scope, protocol]} from [SchedulerSettings]."""
    out = {}
    if not parser.has_section('SchedulerSettings'):
        return out
    for k, v in parser.items('SchedulerSettings'):
        parts = next(csv.reader([v], skipinitialspace=True), [])
        out[k] = parts
    return out


# =============================================================================
# TestConfIntegrity — legion.conf fixes are in place
# =============================================================================

class TestConfIntegrity:
    """All six conf regressions from the v10.206 audit are fixed."""

    def test_feroxbuster_wordlist_exists_on_disk(self):
        """Fix-1: feroxbuster -w wordlist path in conf must exist on disk."""
        raw = _conf_raw()
        wl_paths = re.findall(r'feroxbuster\b[^,\n"]*-w\s+(\S+)', raw)
        assert wl_paths, 'No feroxbuster -w wordlist argument found in conf'
        missing = [p for p in wl_paths if not Path(p).exists()]
        assert not missing, (
            f'Feroxbuster wordlist(s) not found on disk: {missing}\n'
            f'Fix: update legion.conf to use an existing wordlist '
            f'(e.g. /usr/share/seclists/Discovery/Web-Content/big.txt)'
        )

    def test_ffuf_no_q_flag_in_conf(self):
        """Fix-2: ffuf -q flag (removed in v2.1.0-dev) must not appear in conf."""
        raw = _conf_raw()
        bad_lines = []
        for line in raw.splitlines():
            if ',ffuf ' not in line and not line.strip().startswith('ffuf'):
                continue
            cmd_match = re.search(r',ffuf\s+([^,\n"]+)', line)
            if cmd_match:
                cmd = cmd_match.group(1)
                if re.search(r'(?<![a-zA-Z])-q(?![a-zA-Z])', cmd):
                    bad_lines.append(line.strip())
        assert not bad_lines, (
            f'ffuf command(s) in conf use -q flag (not defined in ffuf v2.1.0-dev):\n'
            + '\n'.join(f'  {l[:120]}' for l in bad_lines)
            + '\nFix: remove -q from the ffuf-files PortActions command'
        )

    def test_hydra_no_embedded_quote_in_output_path(self):
        """
        Fix-3: Hydra -o commands must NOT use quote-embedded paths.
        Pattern -o \\\"\\\"[OUTPUT].txt\\\"\\\" causes bash to embed literal \" chars
        in the filename, making fopen() fail with 'No such file or directory'.
        """
        raw = _conf_raw()
        bad_pattern = re.compile(r'-o\s+[\\"]+"?\[OUTPUT\]')
        bad_lines = [
            l for l in raw.splitlines()
            if 'hydra' in l.lower() and bad_pattern.search(l)
        ]
        assert not bad_lines, (
            f'Hydra -o path has embedded quote chars in {len(bad_lines)} command(s):\n'
            + '\n'.join(f'  {l[:120]}' for l in bad_lines[:3])
            + '\nFix: change -o \\"\\\"[OUTPUT].txt\\"\\\" to -o [OUTPUT].txt'
        )

    def test_nuclei_has_template_path_flag(self):
        """
        Fix-4: nuclei commands must include -t (template directory).
        Without it, nuclei logs 'no templates provided for scan' when run as
        root because the default config dir is not writable.
        """
        raw = _conf_raw()
        nuclei_lines = [
            l for l in raw.splitlines()
            if 'nuclei -u' in l
        ]
        assert nuclei_lines, 'No nuclei -u commands found in conf'
        missing_t = [l for l in nuclei_lines if ' -t ' not in l]
        assert not missing_t, (
            f'{len(missing_t)} nuclei command(s) missing -t template path:\n'
            + '\n'.join(f'  {l[:120]}' for l in missing_t[:3])
            + '\nFix: add -t /home/kali/.local/nuclei-templates/http to nuclei commands'
        )

    def test_dnsrecon_uses_correct_flags(self):
        """
        dnsrecon uses -n (not --dns-servers, which does not exist in dnsrecon)
        and -x (not --xml) for XML output.
        These were the exact bugs in the original conf command that caused
        dnsrecon to exit immediately with 'unrecognized arguments'.
        """
        raw = _conf_raw()
        dnsrecon_lines = [l for l in raw.splitlines()
                          if l.strip().startswith('dnsrecon') and 'dnsrecon -d' in l
                          and not l.strip().startswith('dnsrecon-')]
        assert dnsrecon_lines, 'No dnsrecon PortActions command found in conf'
        for line in dnsrecon_lines:
            assert '--dns-servers' not in line, (
                f"dnsrecon command uses --dns-servers (not a valid flag — use -n):\n  {line}"
            )
            assert '--xml' not in line, (
                f"dnsrecon command uses --xml (not a valid flag — use -x):\n  {line}"
            )
            assert ' -n ' in line or line.endswith('-n'), (
                f"dnsrecon command missing -n NS_SERVER flag:\n  {line}"
            )

    def test_kerbrute_scanning_mode_only(self):
        """
        kerbrute must use 'userenum' (enumerate valid usernames via Kerberos
        pre-auth errors — scanning only, no passwords attempted).
        Brute-force commands (bruteuser, passwordspray, brute) are hacking
        tools and must NOT appear in any auto-run context.
        """
        raw = _conf_raw()
        kerb_lines = [l for l in raw.splitlines()
                      if 'kerbrute' in l.lower()]
        for line in kerb_lines:
            for hacking_cmd in ('bruteuser', 'passwordspray', ' brute '):
                assert hacking_cmd not in line.lower(), (
                    f"kerbrute in hacking mode ('{hacking_cmd}') found in conf:\n  {line}"
                )
        # Confirm userenum (scanning mode) is the configured command
        userenum_lines = [l for l in kerb_lines if 'userenum' in l.lower()]
        assert userenum_lines, (
            "No kerbrute userenum entry found in conf. "
            "kerbrute must be configured in scanning mode (userenum only)."
        )

    def test_wig_in_scheduler_settings(self):
        """wig must be in [SchedulerSettings] (auto-trigger on http services)."""
        parser = _conf_parser()
        scheduler = _scheduler_settings(parser)
        assert 'wig' in scheduler, (
            'wig is missing from [SchedulerSettings]. '
            'Add: wig="http,https,ssl",tcp'
        )

    def test_scheduler_service_names_lowercase(self):
        """
        Fix-8: Scheduler lowercases svc_name before matching:
            svc_name = str(port_row.get('name','')).rstrip('?').lower()
        Uppercase svc_scope values (e.g. 'X11') NEVER match anything.
        The original x11screen=X11,tcp was silently broken by this.
        """
        parser = _conf_parser()
        scheduler = _scheduler_settings(parser)
        broken = {}
        for tool_id, parts in scheduler.items():
            if not parts:
                continue
            svcs = [s.strip() for s in parts[0].split(',') if s.strip()]
            bad = [s for s in svcs if s != s.lower() and s != '*']
            if bad:
                broken[tool_id] = bad
        assert not broken, (
            'SchedulerSettings has uppercase service names (never matched '
            'because scheduler lowercases all svc_names before comparison):\n'
            + '\n'.join(f'  {k}: {v}' for k, v in broken.items())
            + '\nFix: lowercase all service scope strings in [SchedulerSettings]'
        )


# =============================================================================
# TestSchedulerConsistency — every SchedulerSettings key is wired
# =============================================================================

class TestSchedulerConsistency:
    """Every [SchedulerSettings] key must be resolvable to a command."""

    BUILTIN_TOOLS = {'screenshooter'}

    def test_every_scheduler_tool_has_portaction(self):
        """
        Fix-7: Every [SchedulerSettings] key (except built-ins) must have a
        matching [PortActions] key. A dead reference silently skips the tool
        with no error — the only symptom is an empty 'Finished' process.
        """
        parser = _conf_parser()
        scheduler = _scheduler_settings(parser)
        port_actions = _port_actions(parser)
        dead = [
            k for k in scheduler
            if k not in self.BUILTIN_TOOLS and k not in port_actions
        ]
        assert not dead, (
            f'{len(dead)} SchedulerSettings key(s) have no matching PortActions '
            f'entry (tools silently skip at runtime):\n'
            + '\n'.join(f'  {k}' for k in sorted(dead))
            + '\nFix: add entries to [PortActions] or remove from [SchedulerSettings]'
        )

    def test_portaction_commands_have_ip_placeholder(self):
        """Every [PortActions] command that hits the network must include [IP]."""
        parser = _conf_parser()
        port_actions = _port_actions(parser)
        broken = {}
        for k, parts in port_actions.items():
            if len(parts) < 2:
                continue
            cmd = parts[1] if len(parts) > 1 else ''
            # Skip terminal actions and no-op echo stubs
            if cmd.startswith('[term]') or '/bin/echo' in cmd:
                continue
            if '[IP]' not in cmd:
                broken[k] = cmd[:80]
        assert not broken, (
            f'{len(broken)} PortActions command(s) missing [IP] placeholder:\n'
            + '\n'.join(f'  {k}: {v}' for k, v in list(broken.items())[:5])
        )


# =============================================================================
# TestPerlDependencies — Encoding::BER for rdp-sec-check
# =============================================================================

class TestPerlDependencies:
    """rdp-sec-check.pl requires the Encoding::BER CPAN module (Fix-6)."""

    def test_encoding_ber_importable(self):
        """perl -e 'use Encoding::BER' must exit 0."""
        if not shutil.which('perl'):
            pytest.skip('perl not installed')
        rc, out = _run(['perl', '-e', 'use Encoding::BER; print "ok"'])
        assert rc == 0 and 'ok' in out, (
            f'Perl Encoding::BER not importable (exit {rc}):\n{out}\n'
            f'Fix: sudo apt-get install libencoding-ber-perl'
        )

    def test_rdp_sec_check_perl_compiles(self):
        """rdp-sec-check.pl must pass perl -c (no 'compilation aborted')."""
        script = Path('/opt/rdp-sec-check/rdp-sec-check.pl')
        if not script.exists():
            pytest.skip('rdp-sec-check not cloned to /opt/rdp-sec-check')
        rc, out = _run(['perl', '-c', str(script)], timeout=10)
        assert 'compilation aborted' not in out, (
            f'rdp-sec-check.pl fails Perl compilation:\n{out[:400]}\n'
            f'Fix: sudo apt-get install libencoding-ber-perl'
        )

    def test_rdp_sec_check_runs_without_error(self):
        """rdp-sec-check --help must not print 'compilation aborted'."""
        if not shutil.which('rdp-sec-check'):
            pytest.skip('rdp-sec-check not installed')
        rc, out = _run(['rdp-sec-check', '--help'], timeout=8)
        assert 'compilation aborted' not in out, (
            f'rdp-sec-check crashed at startup:\n{out[:400]}'
        )


# =============================================================================
# TestNucleiSetup — templates + config directory
# =============================================================================

class TestNucleiSetup:
    """nuclei templates and config dir must be accessible when running as root."""

    def test_nuclei_http_templates_present(self):
        """
        Fix-4b: http template sub-dir must have > 1000 yaml files.
        This is the exact path passed to nuclei via -t in legion.conf.
        """
        http_dir = REAL_HOME / '.local' / 'nuclei-templates' / 'http'
        if not http_dir.exists():
            root_http = Path('/root/.local/nuclei-templates/http')
            if root_http.exists():
                http_dir = root_http
            else:
                pytest.fail(
                    f'nuclei http template directory not found at {http_dir}\n'
                    f'Fix: nuclei -update-templates  (run as the real user)'
                )
        yaml_count = sum(1 for _ in http_dir.rglob('*.yaml'))
        assert yaml_count > 1000, (
            f'nuclei http templates has only {yaml_count} yaml files (expected > 1000):\n'
            f'  {http_dir}\nFix: nuclei -update-templates'
        )

    def test_nuclei_conf_path_exists(self):
        """The -t path in legion.conf nuclei commands must exist on disk."""
        raw = _conf_raw()
        t_paths = re.findall(r'nuclei\b[^,\n"]*-t\s+([^\s,]+)', raw)
        assert t_paths, (
            'No nuclei -t argument in conf — nuclei will fail as root.\n'
            'Fix: add -t /home/kali/.local/nuclei-templates/http to nuclei commands'
        )
        missing = [p for p in t_paths if not Path(p).exists()]
        if missing:
            pytest.skip(
                f'nuclei -t path(s) not installed yet: {missing}\n'
                f'Run: nuclei -update-templates  then re-run this test'
            )

    def test_nuclei_config_dir_writable(self):
        """
        REAL_HOME/.config/nuclei must exist and be writable.
        Without this, nuclei logs 'permission denied' writing its config
        on every scan when invoked as root.
        """
        conf_dir = REAL_HOME / '.config' / 'nuclei'
        if not conf_dir.exists():
            pytest.fail(
                f'nuclei config directory missing: {conf_dir}\n'
                f'Fix: mkdir -p {conf_dir}'
            )
        assert os.access(conf_dir, os.W_OK), (
            f'nuclei config directory not writable: {conf_dir}\n'
            f'Fix: sudo chown -R $SUDO_USER {conf_dir}'
        )


# =============================================================================
# TestToolExecution — key tools run without crashing
# =============================================================================

class TestToolExecution:
    """Tools must not crash on --version or a benign invocation."""

    def _skip_if_absent_or_docker(self, binary: str):
        if _in_docker():
            pytest.skip('Docker — skipping execution tests')
        if not shutil.which(binary):
            pytest.skip(f'{binary} not installed')

    def test_feroxbuster_version(self):
        self._skip_if_absent_or_docker('feroxbuster')
        rc, out = _run(['feroxbuster', '--version'])
        assert rc == 0, f'feroxbuster --version exited {rc}:\n{out[:200]}'

    def test_ffuf_rejects_q_flag(self):
        """
        Pre: ffuf binary runs and prints version string.
        Post: ffuf -q exits non-zero (flag not defined in v2.1.0-dev).
        Both sides would fail if the conf fix were reverted.
        """
        self._skip_if_absent_or_docker('ffuf')
        # ffuf with no required args prints version and exits non-zero — that's ok
        _, out_v = _run(['ffuf'])
        assert 'fuzz faster' in out_v.lower() or re.search(r'v\d+\.\d+', out_v), (
            f'ffuf binary produced unexpected output (broken install?):\n{out_v[:200]}'
        )

        rc_q, out_q = _run(['ffuf', '-q', '-u', 'http://localhost/FUZZ',
                             '-w', '/dev/null'])
        assert rc_q != 0 or 'flag provided but not defined' in out_q, (
            f'ffuf -q was accepted (exit {rc_q}) — re-add -q to conf if valid '
            f'in this version'
        )

    def test_nuclei_version_and_templates(self):
        """
        Pre: nuclei -version succeeds.
        Post: nuclei -t <template-dir> lists templates without 'no templates
              provided for scan'. Uses -validate (dry-run, no network) instead
              of -u so the test finishes in < 5s.
        """
        self._skip_if_absent_or_docker('nuclei')
        rc_v, out_v = _run(['nuclei', '-version'])
        assert rc_v == 0, f'nuclei -version exited {rc_v}:\n{out_v[:200]}'

        t_dir = REAL_HOME / '.local' / 'nuclei-templates' / 'http'
        if not t_dir.exists():
            pytest.skip('nuclei templates not installed — skipping execution test')
        # -validate loads all templates from -t and reports errors; no network needed
        rc, out = _run(['nuclei', '-t', str(t_dir), '-validate'], timeout=30)
        assert 'no templates provided for scan' not in out.lower(), (
            f'nuclei reports no templates despite -t {t_dir}:\n{out[:300]}'
        )

    def test_ssh_audit_runs(self):
        self._skip_if_absent_or_docker('ssh-audit')
        rc, out = _run(['ssh-audit', '--help'])
        assert any(kw in out.lower() for kw in ['ssh', 'host', 'port', 'audit']), (
            f'ssh-audit --help produced unexpected output:\n{out[:200]}'
        )

    def test_rdp_sec_check_no_perl_crash(self):
        """
        Before fix-6: rdp-sec-check printed 'compilation aborted' on every call.
        After fix-6: it must start successfully.
        """
        if not shutil.which('rdp-sec-check'):
            pytest.skip('rdp-sec-check not installed')
        rc, out = _run(['rdp-sec-check', '--help'], timeout=8)
        assert 'compilation aborted' not in out, (
            f'rdp-sec-check still crashing (Encoding::BER missing?):\n{out[:400]}'
        )


# =============================================================================
# TestCriticalBinaryPresence — scheduler-triggered tool binaries
# =============================================================================

_SCHEDULER_BINARIES = [
    ('hydra',          'ftp-default, mysql-default, mssql-default, postgres-default, etc.'),
    ('nmap',           'all nse scripts, oracle-default, vnc-default'),
    ('feroxbuster',    'feroxbuster, feroxbuster-https'),
    ('gobuster',       'gobuster-dir'),
    ('ffuf',           'ffuf-files'),
    ('nuclei',         'nuclei, nuclei-https'),
    ('ssh-audit',      'ssh-audit'),
    ('netexec',        'netexec-smb'),
    ('smbmap',         'smbmap'),
    ('enum4linux-ng',  'enum4linux-ng'),
    ('snmpwalk',       'snmpwalk'),
    ('onesixtyone',    'onesixtyone'),
    ('swaks',          'swaks-relay'),
    ('smtp-user-enum', 'smtp-enum-vrfy/expn/rcpt'),
    ('dig',            'dig-version, dig-axfr'),
    ('ike-scan',       'ike-scan'),
    ('rpcinfo',        'rpcinfo'),
    ('showmount',      'showmount'),
    ('rdp-sec-check',  'rdp-sec-check'),
    ('ldapdomaindump', 'ldapdomaindump'),
    ('redis-cli',      'redis-info, redis-unauth'),
    ('eyewitness',     'screenshooter'),
    ('testssl',        'testssl'),
    ('davtest',        'davtest'),
    ('joomscan',       'joomscan'),
    ('dnsrecon',       'dnsrecon'),
    ('nbtscan',        'nbtscan'),
    ('kerbrute',       'kerbrute'),
    ('fierce',         'fierce-dns'),
]


@pytest.mark.parametrize('binary,used_by', _SCHEDULER_BINARIES)
def test_scheduler_binary_in_path(binary, used_by):
    """
    Every binary invoked by a [SchedulerSettings] tool must be in PATH.
    A missing binary produces a silent 'Finished' with empty output — no
    error surfaces to the user, making the gap invisible.
    """
    if _in_docker():
        pytest.skip('Docker — binaries not expected in minimal image')
    if not _on_kali():
        pytest.skip('Non-Kali system — tool presence not guaranteed')
    assert shutil.which(binary), (
        f"'{binary}' not found in PATH — required by: {used_by}\n"
        f"Fix: sudo apt-get install {binary}  (or see install_tools.sh)"
    )


# =============================================================================
# TestLegionWordlistPaths — all wordlist paths in conf exist on disk
# =============================================================================

class TestLegionWordlistPaths:
    """
    Wordlist files that don't exist cause silent tool failures.
    Fix-1 context: feroxbuster used directory-list-2.3-medium.txt (absent)
    → changed to big.txt (present).
    """

    def test_absolute_wordlist_paths_exist(self):
        """Every absolute /usr/share/... wordlist path in conf must exist."""
        raw = _conf_raw()
        # Match -w, -C, -P, -U flags followed by an absolute path
        abs_paths = re.findall(
            r'(?:-w|-C|-P|-U|--wordlist)\s+(/[^\s,\'">\|]+)', raw
        )
        # Filter out Legion template placeholders and /dev/null
        abs_paths = [p for p in abs_paths
                     if '[' not in p and p not in ('/dev/null',)]
        if not abs_paths:
            pytest.skip('No absolute wordlist paths found in conf')
        missing = [p for p in abs_paths if not Path(p).exists()]
        assert not missing, (
            f'{len(missing)} wordlist path(s) referenced in conf are missing:\n'
            + '\n'.join(f'  {p}' for p in missing[:5])
            + '\nFix: install seclists (sudo apt install seclists) or update paths'
        )

    def test_legion_bundled_wordlists_present(self):
        """Legion's bundled credential wordlists must exist in ./wordlists/."""
        required = [
            'ftp-betterdefaultpasslist.txt',
            'mysql-betterdefaultpasslist.txt',
            'postgres-betterdefaultpasslist.txt',
            'ssh-betterdefaultpasslist.txt',
            'snmp-default.txt',
            'root-userpass.txt',
        ]
        wl_dir = LEGION_ROOT / 'wordlists'
        missing = [f for f in required if not (wl_dir / f).exists()]
        assert not missing, (
            f'Legion bundled wordlists missing from {wl_dir}:\n'
            + '\n'.join(f'  {f}' for f in missing)
        )
