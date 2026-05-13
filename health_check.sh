#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Legion Health Check — verify install is complete and functional
# Usage: sudo bash health_check.sh
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

VENV="/opt/legion-venv"
VENV_PY="${VENV}/bin/python3"
CONF="${HOME}/.local/share/legion/legion.conf"
REAL_USER="${SUDO_USER:-$(whoami)}"
REAL_HOME=$(eval echo "~${REAL_USER}")

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

ok()   { ((PASS++)); echo -e "  ${GREEN}✓${NC}  $1"; }
fail() { ((FAIL++)); echo -e "  ${RED}✗${NC}  $1"; }
warn() { ((WARN++)); echo -e "  ${YELLOW}!${NC}  $1"; }

echo ""
echo "══════════════════════════════════════════════"
echo "  Legion Health Check"
echo "══════════════════════════════════════════════"
echo ""

# ── 1. Python venv ──────────────────────────────────────────────────
echo "── Python Environment ──"
if [[ -x "$VENV_PY" ]]; then
    VER=$("$VENV_PY" --version 2>&1 | awk '{print $2}')
    ok "Python venv: $VER ($VENV_PY)"
else
    fail "Python venv not found at $VENV_PY"
fi

if "$VENV_PY" -c "import flask, sqlalchemy, requests, anthropic" 2>/dev/null; then
    ok "Critical imports: flask, sqlalchemy, requests, anthropic"
else
    fail "Missing Python packages — run: sudo ${VENV}/bin/pip install -r requirements.txt"
fi

if [[ -L /usr/local/bin/legion-python3 ]]; then
    ok "legion-python3 symlink present"
else
    warn "legion-python3 symlink missing — run: sudo ln -sf $VENV_PY /usr/local/bin/legion-python3"
fi
echo ""

# ── 2. Tool binaries ───────────────────────────────────────────────
echo "── Tool Binaries ──"
CRITICAL_TOOLS=(
    nmap hydra nikto wpscan whatweb wafw00f feroxbuster gobuster ffuf
    nuclei sslscan sslyze sqlmap masscan searchsploit
    smbmap enum4linux-ng netexec impacket-rpcdump
    ssh-audit rdp-sec-check testssl onesixtyone snmpwalk swaks
    eyewitness theharvester bloodhound-python
)
MISSING_TOOLS=()
for tool in "${CRITICAL_TOOLS[@]}"; do
    if ! command -v "$tool" &>/dev/null; then
        MISSING_TOOLS+=("$tool")
    fi
done
if [[ ${#MISSING_TOOLS[@]} -eq 0 ]]; then
    ok "All ${#CRITICAL_TOOLS[@]} critical tool binaries found"
else
    fail "Missing tools: ${MISSING_TOOLS[*]}"
fi

GO_TOOLS=(katana nomore403 gau waybackurls kerbrute)
MISSING_GO=()
for tool in "${GO_TOOLS[@]}"; do
    if ! command -v "$tool" &>/dev/null; then
        MISSING_GO+=("$tool")
    fi
done
if [[ ${#MISSING_GO[@]} -eq 0 ]]; then
    ok "All ${#GO_TOOLS[@]} Go tools found"
else
    fail "Missing Go tools: ${MISSING_GO[*]}"
fi
echo ""

# ── 3. Configuration ──────────────────────────────────────────────
echo "── Configuration ──"
if [[ -f "$CONF" ]]; then
    SCHED_COUNT=$("$VENV_PY" -c "
import configparser; p=configparser.RawConfigParser(); p.optionxform=str
p.read('$CONF')
print(len(p.options('SchedulerSettings')) if p.has_section('SchedulerSettings') else 0)
" 2>/dev/null)
    PORT_COUNT=$("$VENV_PY" -c "
import configparser; p=configparser.RawConfigParser(); p.optionxform=str
p.read('$CONF')
print(len(p.options('PortActions')) if p.has_section('PortActions') else 0)
" 2>/dev/null)
    ok "legion.conf: ${SCHED_COUNT} scheduler tools, ${PORT_COUNT} port actions"
else
    fail "legion.conf not found at $CONF"
fi

MASTER="$(cd "$(dirname "$0")" && pwd)/app/masterLegion.conf"
if [[ -f "$MASTER" ]]; then
    ok "masterLegion.conf bundled (--reset-conf available)"
else
    warn "masterLegion.conf not found — --reset-conf will not work"
fi
echo ""

# ── 4. Nuclei templates ──────────────────────────────────────────
echo "── Nuclei Templates ──"
NUCLEI_DIR="${REAL_HOME}/.local/nuclei-templates"
if [[ -d "$NUCLEI_DIR" ]]; then
    YAML_COUNT=$(find "$NUCLEI_DIR" -name "*.yaml" 2>/dev/null | wc -l)
    if [[ $YAML_COUNT -gt 1000 ]]; then
        ok "Nuclei templates: ${YAML_COUNT} yaml files"
    else
        warn "Nuclei templates: only ${YAML_COUNT} yaml files (expected >1000)"
    fi
else
    fail "Nuclei templates not found at $NUCLEI_DIR — run: nuclei -update-templates"
fi
echo ""

# ── 5. Wordlists ────────────────────────────────────────────────
echo "── Wordlists ──"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MISSING_WL=()
for wl in \
    wordlists/vnc-betterdefaultpasslist.txt \
    wordlists/ftp-betterdefaultpasslist.txt \
    wordlists/mysql-betterdefaultpasslist.txt \
    wordlists/oracle-passwords.txt \
    wordlists/postgres-betterdefaultpasslist.txt \
    wordlists/ssh-betterdefaultpasslist.txt \
    wordlists/telnet-betterdefaultpasslist.txt \
    wordlists/snmp-default.txt; do
    [[ ! -f "${SCRIPT_DIR}/${wl}" ]] && MISSING_WL+=("$wl")
done
if [[ ${#MISSING_WL[@]} -eq 0 ]]; then
    ok "All wordlist files present"
else
    fail "Missing wordlists: ${MISSING_WL[*]}"
fi
echo ""

# ── 6. Server start test ────────────────────────────────────────
echo "── Server Start Test ──"
TEST_PORT=5199
if sudo "$VENV_PY" -c "
import sys, os, threading, time
sys.path.insert(0, '${SCRIPT_DIR}')
os.chdir('${SCRIPT_DIR}')
os.environ.pop('DISPLAY', None)
import app.web.routes as _wr
_wr._HB_TIMEOUT = 9999
from app.web.testhelper import create_test_app
from werkzeug.serving import make_server
app, logic, wc = create_test_app()
httpd = make_server('127.0.0.1', ${TEST_PORT}, app, threaded=True)
t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
time.sleep(2)
import requests
r = requests.get('http://127.0.0.1:${TEST_PORT}/api/snapshot', timeout=5)
httpd.shutdown()
sys.exit(0 if r.status_code == 200 else 1)
" 2>/dev/null; then
    ok "Flask server starts and /api/snapshot responds 200"
else
    fail "Flask server failed to start or respond"
fi
echo ""

# ── 7. Perl dependencies ────────────────────────────────────────
echo "── Perl Dependencies ──"
if perl -MEncoding::BER -e 1 2>/dev/null; then
    ok "Perl Encoding::BER module present (rdp-sec-check)"
else
    warn "Perl Encoding::BER missing — rdp-sec-check may fail"
fi
echo ""

# ── Summary ─────────────────────────────────────────────────────
echo "══════════════════════════════════════════════"
echo -e "  ${GREEN}Passed${NC}: ${PASS}"
[[ $WARN -gt 0 ]] && echo -e "  ${YELLOW}Warnings${NC}: ${WARN}"
[[ $FAIL -gt 0 ]] && echo -e "  ${RED}Failed${NC}: ${FAIL}"
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo -e "  ${GREEN}Legion is healthy.${NC}"
else
    echo -e "  ${RED}Some checks failed — review above.${NC}"
fi
echo "══════════════════════════════════════════════"
echo ""

exit $FAIL
