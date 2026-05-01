"""
tests/test_requirements.py — verify all declared dependencies are satisfied.

Tests:
  1. Every Python package in requirements.txt can be imported.
  2. Both runtime modes (Flask web + Qt6 GUI) can initialise their
     respective core objects without error.
  3. Every external tool binary declared in install_tools.sh is
     present in PATH (skipped automatically when not on Kali).

Run standalone:
    sudo python3 -m pytest tests/test_requirements.py -v

Integrated into run_tests.sh --unit section.
"""

import importlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import json
import pytest

# ── Helpers ───────────────────────────────────────────────────────────────

def _on_kali():
    """True if running on a full Kali install (not a minimal Docker image)."""
    try:
        with open('/etc/os-release') as f:
            return 'kali' in f.read().lower()
    except OSError:
        return False


def _in_docker():
    """True if running inside a Docker container."""
    return os.path.isfile('/.dockerenv')


def _import_ok(module_name):
    """Try importing module_name (or any '|'-separated alternative); return (True, '') or (False, error)."""
    for name in module_name.split('|'):
        try:
            importlib.import_module(name.strip())
            return True, ''
        except ImportError:
            pass
        except Exception as e:
            return False, str(e)
    return False, f"No module named '{module_name}'"


# ── 1. Python package imports ─────────────────────────────────────────────

# (package_label, importable_name)
SHARED_PACKAGES = [
    ("sqlalchemy",    "sqlalchemy"),
    ("six",           "six"),
    ("requests",      "requests"),
    ("urllib3",       "urllib3"),
    ("pyExploitDb",   "pyExploitDb|pyexploitdb"),  # apt=CamelCase, pip=lowercase
    ("pyShodan",      "pyShodan"),
    ("neotermcolor",  "neotermcolor"),
    ("pyfiglet",      "pyfiglet"),
    ("colorama",      "colorama"),
    ("termcolor",     "termcolor"),
    ("rich",          "rich"),
    ("selenium",      "selenium"),
]

FLASK_PACKAGES = [
    ("flask",         "flask"),
    ("werkzeug",      "werkzeug"),
    ("anthropic",     "anthropic"),
    ("google-auth",   "google.auth"),
]

QT6_PACKAGES = [
    ("PyQt6",         "PyQt6.QtCore"),
    ("qasync",        "qasync"),
    ("pandas",        "pandas"),
    ("GitPython",     "git"),
]


@pytest.mark.parametrize("label,module", SHARED_PACKAGES)
def test_shared_package_imports(label, module):
    """Shared packages (needed by both Flask and Qt6 modes) must import."""
    ok, err = _import_ok(module)
    assert ok, (
        f"Cannot import '{module}' (package '{label}'): {err}\n"
        f"Fix: pip3 install --break-system-packages {label}"
    )


@pytest.mark.parametrize("label,module", FLASK_PACKAGES)
def test_flask_mode_package_imports(label, module):
    """Flask web mode packages must import cleanly."""
    ok, err = _import_ok(module)
    assert ok, (
        f"Cannot import '{module}' (package '{label}'): {err}\n"
        f"Fix: pip3 install --break-system-packages {label}"
    )


@pytest.mark.parametrize("label,module", QT6_PACKAGES)
def test_qt6_mode_package_imports(label, module):
    """Qt6 GUI mode packages must import (no display required for basic import)."""
    # Set offscreen platform so Qt6 does not need a real X11 display
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ok, err = _import_ok(module)
    assert ok, (
        f"Cannot import '{module}' (package '{label}'): {err}\n"
        f"Fix: pip3 install --break-system-packages {label}"
    )


# ── 2. Flask runtime: legion starts and API responds ─────────────────────

TEST_PORT = 15099   # dedicated port unlikely to be in use

def test_flask_web_mode_starts_and_responds():
    """
    python3 legion.py --web --port TEST_PORT starts and /api/snapshot
    returns a valid JSON response within 20 seconds.
    """
    import requests as _req

    legion_py = os.path.join(os.path.dirname(__file__), '..', 'legion.py')
    legion_py = os.path.abspath(legion_py)

    if not os.path.isfile(legion_py):
        pytest.skip("legion.py not found relative to tests/")

    proc = subprocess.Popen(
        [sys.executable, legion_py, '--web',
         f'--port={TEST_PORT}', '--no-browser', '--no-prompt'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    started = False
    last_err = ''
    deadline = time.time() + 20
    try:
        while time.time() < deadline:
            time.sleep(1)
            try:
                r = _req.get(
                    f'http://127.0.0.1:{TEST_PORT}/api/snapshot', timeout=3
                )
                if r.status_code == 200 and 'hosts' in r.json():
                    started = True
                    break
            except Exception as e:
                last_err = str(e)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert started, (
        f"Flask web mode did not respond on port {TEST_PORT} within 20s. "
        f"Last error: {last_err}. "
        "Check flask is installed and the port is free."
    )


# ── 3. Qt6 QApplication initialises without a real display ────────────────

def test_qt6_qapplication_offscreen():
    """
    PyQt6.QtWidgets.QApplication can be constructed with the offscreen
    platform — no real X11 display is required.
    """
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is None:
            app = QApplication([])
        assert app is not None
    except ImportError as e:
        pytest.skip(f"PyQt6 not installed: {e}")
    except Exception as e:
        pytest.fail(f"Qt6 offscreen init failed: {e}")


# ── 4. Tool binary checks (Kali only) ─────────────────────────────────────

# Complete list of external binaries that legion.conf references.
# Grouped by origin so failures point to the right fix.
KALI_APT_TOOLS = [
    # Core scanning
    "nmap", "masscan", "hping3", "ike-scan",
    # Web
    "feroxbuster", "gobuster", "ffuf", "nikto", "whatweb", "wafw00f",
    "wpscan", "joomscan", "davtest", "sqlmap", "sslyze", "sslscan", "testssl",
    # Network recon
    "dnsrecon", "dnsenum", "fierce", "nbtscan", "onesixtyone",
    "snmpwalk", "snmpcheck", "rpcinfo", "showmount", "ldapsearch",
    # SMB / Windows
    "netexec", "smbmap", "enum4linux-ng", "ldapdomaindump", "polenum",
    "rpcclient", "smbclient",
    # Impacket suite
    "impacket-rpcdump", "impacket-samrdump", "impacket-secretsdump",
    "impacket-lookupsid", "impacket-GetNPUsers",
    "impacket-smbclient", "impacket-mssqlclient", "impacket-psexec",
    # Auth / brute
    "hydra",
    # Host recon
    "searchsploit", "theHarvester", "bloodhound-python",
    # Network tools
    "dig", "finger", "rsh", "rlogin",
    # Database clients
    "redis-cli", "mysql", "psql",
    # Mail
    "swaks", "smtp-user-enum",
    # Screenshot / browser
    "eyewitness",
    # SSH / misc
    "ssh-audit", "vncviewer", "rdesktop",
    # Other
    "wig", "net",
]

GO_TOOLS = [
    "pd-httpx", "katana", "gau", "waybackurls", "nomore403", "urlfinder",
]

GITHUB_TOOLS = [
    "kerbrute", "rdp-sec-check",
]


@pytest.mark.skipif(not _on_kali() or _in_docker(), reason="Tool binary checks only run on full Kali install (not Docker)")
@pytest.mark.parametrize("tool", KALI_APT_TOOLS)
def test_kali_apt_tool_present(tool):
    """Kali apt-installed tool must be in PATH."""
    assert shutil.which(tool), (
        f"'{tool}' not found in PATH. "
        f"Fix: sudo apt-get install -y {tool.split('-')[0]}"
    )


@pytest.mark.skipif(not _on_kali() or _in_docker(), reason="Tool binary checks only run on full Kali install (not Docker)")
@pytest.mark.parametrize("tool", GO_TOOLS)
def test_go_tool_present(tool):
    """Go-installed tool (via install_tools.sh) must be in PATH."""
    assert shutil.which(tool), (
        f"'{tool}' not found in PATH. "
        f"Fix: sudo bash install_tools.sh  (installs via go install)"
    )


@pytest.mark.skipif(not _on_kali() or _in_docker(), reason="Tool binary checks only run on full Kali install (not Docker)")
@pytest.mark.parametrize("tool", GITHUB_TOOLS)
def test_github_tool_present(tool):
    """GitHub-released tool (via install_tools.sh) must be in PATH."""
    assert shutil.which(tool), (
        f"'{tool}' not found in PATH. "
        f"Fix: sudo bash install_tools.sh"
    )


@pytest.mark.skipif(not _on_kali() or _in_docker(), reason="Tool binary checks only run on full Kali install (not Docker)")
def test_leaksearch_python_script_present():
    """/opt/LeakSearch/LeakSearch.py must exist."""
    assert os.path.isfile("/opt/LeakSearch/LeakSearch.py"), (
        "LeakSearch not found at /opt/LeakSearch/LeakSearch.py. "
        "Fix: sudo bash install_tools.sh"
    )


@pytest.mark.skipif(not _on_kali() or _in_docker(), reason="Tool binary checks only run on full Kali install (not Docker)")
def test_jexboss_python_script_present():
    """/opt/jexboss/jexboss.py must exist."""
    assert os.path.isfile("/opt/jexboss/jexboss.py"), (
        "jexboss not found at /opt/jexboss/jexboss.py. "
        "Fix: sudo bash install_tools.sh"
    )
