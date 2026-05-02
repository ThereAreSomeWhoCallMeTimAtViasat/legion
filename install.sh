#!/usr/bin/env bash
# =============================================================================
# Legion — Full Automated Installer
# =============================================================================
# Installs EVERYTHING needed to run Legion on Kali Linux or Ubuntu 22.04+.
# Run with: sudo bash install.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; }
warn() { echo -e "  ${YELLOW}!${NC}  $*"; }
info() { echo -e "  ${BLUE}→${NC}  $*"; }
step() { echo -e "\n${BOLD}${BLUE}══ $* ${NC}"; }
die()  { echo -e "\n${RED}FATAL: $*${NC}" >&2; exit 1; }

SKIP_AI=false
for arg in "$@"; do
    case "$arg" in
        --no-ai)   SKIP_AI=true ;;
        -h|--help) echo "Usage: sudo bash install.sh [--no-ai]"; exit 0 ;;
    esac
done

[[ $EUID -eq 0 ]] || die "Run with sudo:  sudo bash $0"

# In Docker / root-only environments, sudo is not installed — define a shim
# so every 'sudo cmd' in this script just runs 'cmd' directly.
if ! command -v sudo &>/dev/null; then
    sudo() { "$@"; }
    export -f sudo
    info "sudo not found — running as root, shim active"
fi

REAL_USER="${SUDO_USER:-root}"
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6 2>/dev/null || echo "${HOME}")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Install log — capture everything to a file for the final health check ──────
INSTALL_LOG="/tmp/legion-install-$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "${INSTALL_LOG}") 2>&1
echo "Install log: ${INSTALL_LOG}"

echo ""
echo -e "${BOLD}Legion — Automated Installer${NC}"
echo -e "  Working directory : ${SCRIPT_DIR}"
echo -e "  Running as        : root  (real user: ${REAL_USER})"
echo -e "  Install log       : ${INSTALL_LOG}"
echo ""

# ── Branch guard ──────────────────────────────────────────────────────────────
# git may not be installed yet in a fresh container — skip the check if absent.
if ! command -v git &>/dev/null; then
    warn "git not installed yet — skipping branch check (will install in step 1)"
else
    CURRENT_BRANCH=$(git -C "${SCRIPT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    if [[ "${CURRENT_BRANCH}" == "unknown" ]]; then
        warn "Cannot determine git branch — skipping branch check"
    elif [[ "${CURRENT_BRANCH}" != "flask-clean" ]]; then
        echo -e "${RED}"
        echo "  ╔═══════════════════════════════════════════════════════════════════╗"
        echo "  ║  WRONG BRANCH: you are on '${CURRENT_BRANCH}'                          "
        echo "  ║  The Flask web UI lives on the 'flask-clean' branch.             ║"
        echo "  ║  Fix:  sudo git checkout flask-clean && sudo bash install.sh     ║"
        echo "  ╚═══════════════════════════════════════════════════════════════════╝"
        echo -e "${NC}"
        exit 1
    else
        ok "Branch: ${CURRENT_BRANCH}"
    fi
fi

# =============================================================================
# Shared helpers (declared early so step 8 can call them too)
# =============================================================================

_go_install_bin() {
    # Usage: _go_install_bin <go-pkg@version> <dest-binary-name>
    local pkg="$1" dest="$2"
    local tmpdir; tmpdir=$(mktemp -d)
    info "  go install ${pkg} → /usr/local/bin/${dest}…"
    if GOPATH="$tmpdir" HOME=/root go install "$pkg" 2>/dev/null; then
        local bin; bin=$(find "$tmpdir/bin" -maxdepth 1 -type f | head -1)
        if [[ -f "$bin" ]]; then
            sudo cp "$bin" "/usr/local/bin/$dest"
            sudo chmod +x "/usr/local/bin/$dest"
            ok "  ${dest} installed"
        else
            warn "  ${dest}: no binary produced"
        fi
    else
        warn "  ${dest}: go install failed"
    fi
    sudo rm -rf "$tmpdir"
}

_apt_install() {
    # Install a single package; warn on failure (never die)
    local pkg="$1"
    info "  apt-get install ${pkg}…"
    sudo apt-get install -y --ignore-missing "$pkg" 2>/dev/null \
        && ok "  ${pkg} installed" \
        || warn "  ${pkg}: apt install failed"
}

_install_tool() {
    # Install a single tool binary by name — tries apt, then Go, then GitHub
    local tool="$1"
    info "  Installing ${tool}…"
    case "$tool" in
        pd-httpx)    _go_install_bin "github.com/projectdiscovery/httpx/cmd/httpx@latest"    "pd-httpx"    ;;
        katana)      _go_install_bin "github.com/projectdiscovery/katana/cmd/katana@latest"   "katana"      ;;
        gau)         _go_install_bin "github.com/lc/gau/v2/cmd/gau@latest"                   "gau"         ;;
        waybackurls) _go_install_bin "github.com/tomnomnom/waybackurls@latest"                "waybackurls" ;;
        nomore403)   _go_install_bin "github.com/devploit/nomore403@latest"                   "nomore403"   ;;
        urlfinder)   _go_install_bin "github.com/projectdiscovery/urlfinder/cmd/urlfinder@latest" "urlfinder" ;;
        nuclei)
            sudo apt-get install -y nuclei 2>/dev/null || \
                _go_install_bin "github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest" "nuclei" ;;
        kerbrute)
            local arch; arch=$(uname -m)
            local kf="kerbrute_linux_amd64"
            [[ "$arch" == "aarch64" ]] && kf="kerbrute_linux_arm64"
            sudo curl -fsSL \
                "https://github.com/ropnop/kerbrute/releases/latest/download/${kf}" \
                -o /usr/local/bin/kerbrute 2>/dev/null \
            && sudo chmod +x /usr/local/bin/kerbrute ;;
        rdp-sec-check)
            sudo apt-get install -y rdp-sec-check 2>/dev/null || {
                sudo git clone --depth 1 \
                    https://github.com/CiscoCXSecurity/rdp-sec-check.git \
                    /opt/rdp-sec-check 2>/dev/null
                printf '#!/bin/bash\nexec perl /opt/rdp-sec-check/rdp-sec-check.pl "$@"\n' \
                    | sudo tee /usr/local/bin/rdp-sec-check > /dev/null
                sudo chmod +x /usr/local/bin/rdp-sec-check
            } ;;
        *)  sudo apt-get install -y --ignore-missing "$tool" 2>/dev/null || true ;;
    esac
    if command -v "$tool" &>/dev/null; then
        ok "  ${tool} → $(command -v $tool)"
    else
        warn "  ${tool} could not be installed — install manually then re-run"
    fi
}

_install_pkg() {
    # pip-install a Python package that failed to import
    local import_name="$1" pip_name="$2"
    info "  pip install ${pip_name}…"
    sudo "${VENV_PIP:-python3 -m pip}" install "${pip_name}" 2>/dev/null \
        && ok "  ${pip_name} installed" \
        || warn "  ${pip_name}: pip install failed — try manually: sudo pip3 install ${pip_name}"
}

# =============================================================================
# 1. apt-get update + install all packages
# =============================================================================
step "1/10  apt-get update + install packages"

info "Updating package index…"
sudo apt-get update -q
ok "Package index updated"

info "Installing critical runtime packages (Python, Go, libs, Firefox)…"

# Block A — critical: must succeed or script aborts
sudo apt-get install -y \
    curl wget git ca-certificates unzip build-essential \
    python3 python3-pip python3-dev \
    golang-go \
    libssl3 openssl \
    libgl1 libegl1 libglib2.0-0 libdbus-1-3 \
    libfontconfig1 libfreetype6 libx11-6 libxext6 libxrender1 \
    libxcb1 libxkbcommon0 libxcb-cursor0 \
    xvfb x11-utils \
    firefox-esr

ok "Critical packages installed  (Python $(python3 --version | grep -oP '[\d.]+')  Go $(go version | grep -oP 'go[\d.]+'))"

for req in python3 go git curl; do
    command -v "$req" &>/dev/null \
        && ok "  $req → $(command -v $req)" \
        || die "$req missing after apt — check network / apt sources and retry"
done

info "Installing security tools (--ignore-missing — individual gaps are OK)…"

# Block B — security tools: individual failures are tolerated
sudo apt-get install -y --ignore-missing \
    nmap masscan hping3 ike-scan \
    feroxbuster gobuster ffuf nikto whatweb wafw00f \
    wpscan joomscan davtest sqlmap sslyze sslscan testssl.sh \
    dnsrecon dnsenum nbtscan onesixtyone \
    snmpwalk snmpcheck rpcinfo nfs-common ldap-utils \
    netexec smbmap enum4linux-ng ldapdomaindump smbclient \
    impacket-scripts \
    hydra medusa \
    eyewitness \
    exploitdb theharvester bloodhound-python \
    nuclei \
    ssh-audit \
    redis-tools default-mysql-client postgresql-client \
    swaks smtp-user-enum \
    finger \
    net-tools nbtscan \
    2>/dev/null || true

ok "Security tool packages done (some may be skipped on non-Kali)"

# testssl.sh — dedicated install step so it is never silently dropped by --ignore-missing
if command -v testssl &>/dev/null; then
    ok "testssl already installed at $(command -v testssl)"
else
    info "Installing testssl.sh (apt package name: testssl.sh, binary: testssl)…"
    if sudo apt-get install -y testssl.sh 2>/dev/null; then
        ok "testssl.sh installed — binary at $(command -v testssl)"
    else
        warn "testssl.sh apt install failed — run manually: sudo apt-get install testssl.sh"
    fi
fi

# rsh-client — own call with 3-stage fallback (has dep conflicts on some systems)
if dpkg -l rsh-client &>/dev/null 2>&1; then
    ok "rsh-client already installed"
else
    info "Installing rsh-client + rlogin (Legion terminal actions for rsh)…"
    if sudo apt-get install -y rsh-client rlogin 2>/dev/null; then
        ok "rsh-client + rlogin installed"
    else
        info "Standard install failed — trying apt -f (fix-broken) first…"
        sudo apt-get install -f -y 2>/dev/null || true
        if sudo apt-get install -y rsh-client 2>/dev/null; then
            ok "rsh-client installed after fix-broken"
        elif sudo apt-get install -y rsh-redone-client 2>/dev/null; then
            ok "rsh-redone-client installed as rsh-client alternative"
        else
            warn "rsh-client unavailable — fix manually: sudo apt-get install -f && sudo apt-get install rsh-client"
        fi
    fi
fi

# =============================================================================
# 2. Go-based tools
# =============================================================================
step "2/10  Go-based tools"

declare -A GO_TOOLS=(
    [pd-httpx]="github.com/projectdiscovery/httpx/cmd/httpx@latest"
    [katana]="github.com/projectdiscovery/katana/cmd/katana@latest"
    [gau]="github.com/lc/gau/v2/cmd/gau@latest"
    [waybackurls]="github.com/tomnomnom/waybackurls@latest"
    [nomore403]="github.com/devploit/nomore403@latest"
    [urlfinder]="github.com/projectdiscovery/urlfinder/cmd/urlfinder@latest"
)

for dest in "${!GO_TOOLS[@]}"; do
    if command -v "$dest" &>/dev/null; then
        ok "$dest already at $(command -v $dest)"
    else
        _go_install_bin "${GO_TOOLS[$dest]}" "$dest"
    fi
done

# =============================================================================
# 3. GitHub binary tools
# =============================================================================
step "3/10  GitHub binary tools"

if command -v kerbrute &>/dev/null; then
    ok "kerbrute already at $(command -v kerbrute)"
else
    _install_tool kerbrute
fi

if command -v rdp-sec-check &>/dev/null; then
    ok "rdp-sec-check already at $(command -v rdp-sec-check)"
else
    _install_tool rdp-sec-check
fi

# =============================================================================
# 4. /opt tools
# =============================================================================
step "4/10  /opt tools  (jexboss, LeakSearch)"

if [[ -f /opt/jexboss/jexboss.py ]]; then
    ok "jexboss already at /opt/jexboss"
else
    info "Cloning jexboss…"
    if sudo git clone --depth 1 https://github.com/joaomatosf/jexboss.git /opt/jexboss 2>/dev/null; then
        [[ -f /opt/jexboss/requires.txt ]] && \
            sudo python3 -m pip install --break-system-packages -q \
                -r /opt/jexboss/requires.txt 2>/dev/null || true
        ok "jexboss installed at /opt/jexboss/jexboss.py"
    else
        warn "jexboss clone failed — install manually from https://github.com/joaomatosf/jexboss"
    fi
fi

if [[ -f /opt/LeakSearch/LeakSearch.py ]]; then
    ok "LeakSearch already at /opt/LeakSearch"
else
    info "Cloning LeakSearch…"
    if sudo git clone --depth 1 https://github.com/JoelGMSec/LeakSearch.git /opt/LeakSearch 2>/dev/null; then
        [[ -f /opt/LeakSearch/requirements.txt ]] && \
            sudo python3 -m pip install --break-system-packages -q \
                -r /opt/LeakSearch/requirements.txt 2>/dev/null || true
        ok "LeakSearch installed at /opt/LeakSearch/LeakSearch.py"
    else
        warn "LeakSearch clone failed — install manually from https://github.com/JoelGMSec/LeakSearch"
    fi
fi

if python3 -c "import neotermcolor" 2>/dev/null; then
    ok "neotermcolor already installed"
else
    info "Installing neotermcolor (LeakSearch dependency)…"
    sudo python3 -m pip install --break-system-packages -q neotermcolor \
        && ok "neotermcolor installed" \
        || warn "neotermcolor install failed — run: sudo pip3 install neotermcolor"
fi

# =============================================================================
# 5. Python packages — installed into a dedicated virtual environment
# =============================================================================
# WHY A VENV?
# A full Kali installation contains 30+ security tools (mitmproxy, awscli,
# theharvester, impacket, ciphey, pacu, pyppeteer, faradaysec, etc.) that
# each declare strict version pins for shared packages like urllib3, requests,
# rich, flask, werkzeug, click, and greenlet.  These pins are contradictory —
# no single set of globally-installed package versions can satisfy all of them.
#
# Installing Legion's packages into the system site-packages (--break-system-
# packages) upgrades shared libraries and breaks those Kali tools; downgrading
# to their versions breaks Legion.
#
# A virtual environment at LEGION_VENV gives Legion its own isolated copy of
# every package.  The system Python and all Kali tools are completely
# unaffected.  `pip check` on either side reports zero conflicts.
# =============================================================================
step "5/10  Python virtual environment + packages"

LEGION_VENV=/opt/legion-venv
cd "${SCRIPT_DIR}"
[[ -f requirements.txt ]] || die "requirements.txt not found in ${SCRIPT_DIR}"

# Ensure python3-venv is available.
# NOTE: "python3 -m venv --help" exits 0 even WITHOUT python3-venv installed
# because --help is handled before ensurepip is needed.  The correct test is
# whether ensurepip (the piece that's missing) can be imported.
if ! python3 -c "import ensurepip" &>/dev/null 2>&1; then
    info "Installing python3-venv (ensurepip not found)…"
    sudo apt-get install -y python3-venv \
        && ok "python3-venv installed" \
        || die "python3-venv unavailable — cannot create virtual environment.\nTry: sudo apt-get install python3-venv"
fi

# Create (or reuse) the venv
if [[ -f "${LEGION_VENV}/bin/python3" ]]; then
    ok "Virtual environment already exists at ${LEGION_VENV}"
else
    info "Creating virtual environment at ${LEGION_VENV}…"
    sudo python3 -m venv "${LEGION_VENV}" \
        || die "Failed to create virtual environment at ${LEGION_VENV}.\nTry: sudo apt-get install python3-venv python3-pip"
    ok "Virtual environment created"
fi

VENV_PY="${LEGION_VENV}/bin/python3"
VENV_PIP="${LEGION_VENV}/bin/pip"

# Upgrade pip inside the venv first
info "Upgrading pip inside venv…"
sudo "${VENV_PY}" -m pip install --quiet --upgrade pip 2>/dev/null || true

# Install all requirements into the venv
info "Installing Flask + Qt6 + shared + AI dependencies into venv…"
echo ""

if sudo "${VENV_PIP}" install \
        --root-user-action=ignore \
        -r requirements.txt 2>&1 \
        | grep -E "^Collecting|Installing collected|Successfully installed|Successfully uninstalled|error:|ERROR:"; then
    ok "requirements.txt installed into ${LEGION_VENV}"
else
    die "pip install into venv failed.\nRun manually:\n  sudo ${VENV_PIP} install -r requirements.txt"
fi

echo ""

# Verify no conflicts inside the venv
info "Running pip check inside venv (should be zero conflicts)…"
CONFLICT_OUTPUT=$(sudo "${VENV_PIP}" check 2>&1)
if echo "${CONFLICT_OUTPUT}" | grep -q "No broken requirements"; then
    ok "pip check: No broken requirements — zero conflicts in Legion venv"
else
    warn "pip check found issues inside the venv:"
    echo "${CONFLICT_OUTPUT}" | head -20
    warn "These may need attention — Legion may still run correctly"
fi

# Verify critical imports using the VENV python
info "Verifying critical imports inside venv…"
for pkg in flask sqlalchemy requests PyQt6.QtCore anthropic; do
    if sudo "${VENV_PY}" -c "import ${pkg}" 2>/dev/null; then
        ok "  import ${pkg}"
    else
        warn "  import ${pkg} FAILED inside venv — attempting fix…"
        case "$pkg" in PyQt6.QtCore) pip_name="PyQt6" ;; *) pip_name="$pkg" ;; esac
        sudo "${VENV_PIP}" install "${pip_name}" 2>/dev/null || true
        sudo "${VENV_PY}" -c "import ${pkg}" 2>/dev/null \
            && ok "  import ${pkg} — fixed" \
            || die "  Cannot import ${pkg} in venv.  Check output above."
    fi
done

# Create a convenience symlink so 'legion-python3' always uses the venv
sudo ln -sf "${VENV_PY}" /usr/local/bin/legion-python3 2>/dev/null || true
ok "Symlink: /usr/local/bin/legion-python3 → ${VENV_PY}"

# =============================================================================
# 6. nuclei + templates
# =============================================================================
step "6/10  nuclei + templates"

if command -v nuclei &>/dev/null; then
    ok "nuclei already at $(command -v nuclei)"
else
    info "nuclei not found — installing…"
    if sudo apt-get install -y nuclei 2>/dev/null; then
        ok "nuclei installed via apt"
    else
        info "nuclei not in apt — building from Go source…"
        _go_install_bin "github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest" "nuclei"
    fi
    command -v nuclei &>/dev/null \
        || die "nuclei could not be installed.  Try: sudo apt-get install nuclei"
fi

NUCLEI_DIR="${REAL_HOME}/.local/nuclei-templates"
if [[ -d "$NUCLEI_DIR" && -n "$(ls -A "$NUCLEI_DIR" 2>/dev/null)" ]]; then
    ok "nuclei templates already present at ${NUCLEI_DIR}"
else
    info "Downloading nuclei templates (may take a few minutes)…"
    HOME="${REAL_HOME}" nuclei -update-templates 2>/dev/null \
        && ok "nuclei templates ready" \
        || warn "nuclei template download failed — run: nuclei -update-templates"
fi

# =============================================================================
# 7. geckodriver + Firefox profile
# =============================================================================
step "7/10  geckodriver + Firefox profile"

if command -v geckodriver &>/dev/null; then
    ok "geckodriver already at $(command -v geckodriver)  ($(geckodriver --version 2>&1 | head -1))"
else
    info "Installing geckodriver…"
    ARCH=$(uname -m)
    GD_ARCH="linux64"; [[ "$ARCH" == "aarch64" ]] && GD_ARCH="linux-aarch64"
    GD_URL="https://github.com/mozilla/geckodriver/releases/download/v0.35.0/geckodriver-v0.35.0-${GD_ARCH}.tar.gz"
    TMP=$(mktemp -d)
    if sudo curl -fsSL "$GD_URL" | sudo tar xz -C "$TMP" 2>/dev/null && [[ -f "$TMP/geckodriver" ]]; then
        sudo mv "$TMP/geckodriver" /usr/local/bin/geckodriver
        sudo chmod +x /usr/local/bin/geckodriver
        ok "geckodriver installed at /usr/local/bin/geckodriver"
    else
        warn "geckodriver download failed — Selenium tests will not work"
    fi
    sudo rm -rf "$TMP"
fi

PROFILE_DIR="${REAL_HOME}/.mozilla/firefox/legion-profile"
if [[ -d "$PROFILE_DIR" ]]; then
    ok "Legion Firefox profile already exists"
else
    sudo mkdir -p "$PROFILE_DIR"
    [[ "$REAL_USER" != "root" ]] && \
        sudo chown -R "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.mozilla" 2>/dev/null || true
    ok "Firefox profile created at ${PROFILE_DIR}"
fi

# =============================================================================
# 8. Verification + auto-remediation
# =============================================================================
step "8/10  Verification + auto-remediation"

# pytest is needed for the verification tests but is not in requirements.txt
# (it is a test-only tool, not a Legion runtime dependency).
if ! "${VENV_PY}" -m pytest --version &>/dev/null 2>&1; then
    info "Installing pytest for verification tests…"
    sudo "${VENV_PIP}" install --root-user-action=ignore pytest -q 2>/dev/null \
        && ok "pytest installed" \
        || warn "pytest install failed — skipping verification (non-fatal)"
fi

cd "${SCRIPT_DIR}"

# ── Disable errexit for the whole step — failures here must be handled, not abort ──
set +e

VERIFY_LOG=$(mktemp)
MAX_ROUNDS=3
ROUND=0
ALL_PASS=false

while [[ $ROUND -lt $MAX_ROUNDS ]]; do
    ROUND=$(( ROUND + 1 ))
    info "Verification round ${ROUND}/${MAX_ROUNDS}…"

    # Run tests — capture output without letting a non-zero exit kill the script
    sudo "${VENV_PY}" -m pytest tests/test_requirements.py --noconftest -q --tb=line \
        > "$VERIFY_LOG" 2>&1
    pytest_exit=$?

    cat "$VERIFY_LOG"   # always show the output

    if [[ $pytest_exit -eq 0 ]]; then
        ALL_PASS=true
        break
    fi

    [[ $ROUND -ge $MAX_ROUNDS ]] && break
    info "Failures detected — remediating before round $(( ROUND + 1 ))…"
    echo ""

    # ── Fix: missing Python import — format: "Cannot import 'X' (package 'Y')" ──
    while IFS= read -r line; do
        import_name=$(echo "$line" | grep -oP "import '\K[^']+")
        pkg_name=$(echo "$line"    | grep -oP "package '\K[^']+")
        [[ -z "$import_name" ]] && continue
        [[ -z "$pkg_name"    ]] && pkg_name="$import_name"
        fail "  Python import '${import_name}' (package '${pkg_name}') missing — installing…"
        _install_pkg "$import_name" "$pkg_name"
    done < <(grep "Cannot import" "$VERIFY_LOG")

    # ── Fix: missing tool binary — format: "'tool' not found in PATH" ──
    while IFS= read -r line; do
        tool=$(echo "$line" | grep -oP "'\K[^']+(?=' not found in PATH)")
        [[ -z "$tool" ]] && continue
        fail "  Binary '${tool}' not found in PATH — installing…"
        _install_tool "$tool"
    done < <(grep "not found in PATH" "$VERIFY_LOG")

    # ── Fix: missing /opt script — format: assertion about /opt/X/Y.py ──
    while IFS= read -r line; do
        script=$(echo "$line" | grep -oP "/opt/[^ '\"]+\.py")
        [[ -z "$script" || -f "$script" ]] && continue
        repo=$(basename "$(dirname "$script")")
        fail "  ${script} missing — cloning ${repo}…"
        case "$repo" in
            LeakSearch)
                sudo git clone --depth 1 \
                    https://github.com/JoelGMSec/LeakSearch.git /opt/LeakSearch 2>/dev/null
                sudo python3 -m pip install --break-system-packages neotermcolor -q 2>/dev/null || true
                ;;
            jexboss)
                sudo git clone --depth 1 \
                    https://github.com/joaomatosf/jexboss.git /opt/jexboss 2>/dev/null
                ;;
        esac
    done < <(grep -i "AssertionError\|assert.*jexboss\|assert.*LeakSearch\|/opt/" "$VERIFY_LOG")

    echo ""
done

rm -f "$VERIFY_LOG"

# Re-enable errexit
set -e

if $ALL_PASS; then
    ok "All verification tests passed"
else
    warn "Some tests still failing after ${MAX_ROUNDS} remediation rounds."
    warn "Run this to see what remains:"
    warn "  sudo "${VENV_PY}" -m pytest tests/test_requirements.py --noconftest -v"
    warn "The installer will continue — Legion --web may still work."
fi

# =============================================================================
# 9. AI tab setup (optional)
# =============================================================================
if ! $SKIP_AI; then
    step "9/10  AI tab  (Vertex AI — optional)"
    echo ""
    echo "  The AI tab uses Anthropic Claude via Google Cloud Vertex AI."
    echo "  Requires a GCP project with the Vertex AI API enabled."
    echo "  Auth uses Application Default Credentials — no API key stored."
    echo ""
    read -r -p "  Configure AI tab now? [y/N] " SETUP_AI
    if [[ "${SETUP_AI,,}" == "y" ]]; then
        read -r -p "  GCP project ID (e.g. my-project-123): " GCP_PROJECT
        read -r -p "  Vertex AI region [global]: "             GCP_REGION
        GCP_REGION="${GCP_REGION:-global}"

        CLAUDE_SETTINGS="${REAL_HOME}/.claude/settings.json"
        sudo mkdir -p "$(dirname "$CLAUDE_SETTINGS")"

        if [[ -f "$CLAUDE_SETTINGS" ]]; then
            python3 - "$CLAUDE_SETTINGS" "$GCP_PROJECT" "$GCP_REGION" <<'PYEOF'
import sys, json
path, project, region = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f: cfg = json.load(f)
except Exception:
    cfg = {}
cfg['ANTHROPIC_VERTEX_PROJECT_ID'] = project
cfg['CLOUD_ML_REGION'] = region
with open(path, 'w') as f: json.dump(cfg, f, indent=2)
PYEOF
        else
            cat > "$CLAUDE_SETTINGS" <<EOF
{
  "ANTHROPIC_VERTEX_PROJECT_ID": "${GCP_PROJECT}",
  "CLOUD_ML_REGION": "${GCP_REGION}"
}
EOF
        fi
        [[ "$REAL_USER" != "root" ]] && \
            sudo chown -R "${REAL_USER}:${REAL_USER}" "$(dirname "$CLAUDE_SETTINGS")" 2>/dev/null || true

        ok "AI settings written to ${CLAUDE_SETTINGS}"
        info "Authenticate with Google Cloud (as your normal user, not root):"
        echo "      gcloud auth application-default login"
    else
        info "Skipped — edit ~/.claude/settings.json and run:"
        info "  gcloud auth application-default login"
    fi
fi

# =============================================================================
# 10. Final environment health check
# =============================================================================
step "10/10  Final environment health check"
set +e   # never abort on a check failure — report everything, let user decide

_CHECK_PASS=0
_CHECK_WARN=0
_CHECK_FAIL=0

_chk_ok()   { ok   "$*";   (( _CHECK_PASS++ )) || true; }
_chk_warn() { warn "$*";   (( _CHECK_WARN++ )) || true; }
_chk_fail() { fail "$*";   (( _CHECK_FAIL++ )) || true; }

# ── Helper: is this a Docker container? ──────────────────────────────────────
_in_docker() { [[ -f /.dockerenv ]]; }

# ── Helper: is this a real Kali install? ─────────────────────────────────────
_on_kali() {
    [[ -f /etc/os-release ]] && grep -qi kali /etc/os-release
}

echo ""
echo -e "  ${BOLD}── Venv structure ──────────────────────────────${NC}"

# 1. Venv directory exists
if [[ -d "${LEGION_VENV}" ]]; then
    _chk_ok  "Venv directory exists: ${LEGION_VENV}"
else
    _chk_fail "Venv directory MISSING: ${LEGION_VENV}"
    _chk_fail "  → Re-run: sudo bash install.sh"
fi

# 2. Venv python3 binary
if [[ -f "${LEGION_VENV}/bin/python3" ]]; then
    _chk_ok  "Venv python3 binary present"
else
    _chk_fail "Venv python3 binary MISSING: ${LEGION_VENV}/bin/python3"
fi

# 3. Venv pip binary
if [[ -f "${LEGION_VENV}/bin/pip" ]]; then
    _chk_ok  "Venv pip binary present"
else
    _chk_fail "Venv pip binary MISSING: ${LEGION_VENV}/bin/pip"
fi

# 4. sys.prefix is actually the venv (not system python)
if [[ -f "${VENV_PY}" ]]; then
    _venv_prefix=$("${VENV_PY}" -c "import sys; print(sys.prefix)" 2>/dev/null || true)
    if [[ "${_venv_prefix}" == "${LEGION_VENV}" ]]; then
        _chk_ok  "Venv python sys.prefix = ${LEGION_VENV}"
    else
        _chk_fail "Venv python sys.prefix is wrong: '${_venv_prefix}' (expected '${LEGION_VENV}')"
    fi
fi

# 5. include-system-site-packages must be false (isolation)
if [[ -f "${LEGION_VENV}/pyvenv.cfg" ]]; then
    if grep -q "include-system-site-packages = false" "${LEGION_VENV}/pyvenv.cfg"; then
        _chk_ok  "Venv is isolated (include-system-site-packages = false)"
    else
        _chk_fail "Venv is NOT isolated — system site-packages leak in (pyvenv.cfg)"
    fi
fi

# 6. legion-python3 symlink
if [[ -L /usr/local/bin/legion-python3 ]]; then
    _link_target=$(readlink /usr/local/bin/legion-python3)
    if [[ "${_link_target}" == "${LEGION_VENV}/bin/python3" ]]; then
        _chk_ok  "legion-python3 symlink → ${LEGION_VENV}/bin/python3"
    else
        _chk_warn "legion-python3 symlink points to wrong target: ${_link_target}"
    fi
else
    _chk_warn "legion-python3 symlink missing at /usr/local/bin/legion-python3"
fi

echo ""
echo -e "  ${BOLD}── Python packages (venv) ──────────────────────${NC}"

# 7. pip check inside venv — zero broken requirements
if [[ -f "${VENV_PIP}" ]]; then
    _pip_check_out=$("${VENV_PIP}" check 2>&1)
    if echo "${_pip_check_out}" | grep -q "No broken requirements"; then
        _chk_ok  "pip check: No broken requirements in Legion venv"
    else
        _chk_warn "pip check found issues in venv:"
        echo "${_pip_check_out}" | grep -v "^$" | while IFS= read -r ln; do
            echo "         ${YELLOW}!${NC} ${ln}"
        done
    fi
fi

# 8. Critical package imports from venv
_FLASK_PKGS=( flask werkzeug anthropic "google.auth" )
_QT6_PKGS=(  "PyQt6.QtCore" qasync pandas git )
_SHARED_PKGS=( sqlalchemy six requests urllib3 selenium pyfiglet colorama termcolor rich neotermcolor )

_check_imports() {
    local label="$1"; shift
    local pkgs=("$@")
    local all_ok=true
    for pkg in "${pkgs[@]}"; do
        if "${VENV_PY}" -c "import ${pkg}" 2>/dev/null; then
            : # silent pass
        else
            _chk_fail "  import ${pkg} FAILED (${label})"
            all_ok=false
        fi
    done
    $all_ok && _chk_ok "${label} packages all importable"
}

[[ -f "${VENV_PY}" ]] && {
    _check_imports "Flask web mode"  "${_FLASK_PKGS[@]}"
    _check_imports "Qt6 GUI mode"    "${_QT6_PKGS[@]}"
    _check_imports "Shared"          "${_SHARED_PKGS[@]}"
}

# 9. Legion's own modules importable from venv
if [[ -f "${VENV_PY}" && -f "${SCRIPT_DIR}/legion.py" ]]; then
    _legion_import_err=$( cd "${SCRIPT_DIR}" && \
        "${VENV_PY}" -c "
import sys
sys.path.insert(0, '.')
try:
    from app.web.routes import web_bp
    from controller.web_controller import WebController
    from db.SqliteDbAdapter import SqliteDbAdapter
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>&1 )
    if [[ "${_legion_import_err}" == "OK" ]]; then
        _chk_ok  "Legion core modules importable (routes, WebController, SqliteDbAdapter)"
    else
        _chk_fail "Legion core module import failed: ${_legion_import_err}"
    fi
fi

echo ""
echo -e "  ${BOLD}── Tools ───────────────────────────────────────${NC}"

if _in_docker; then
    _chk_warn "Docker container detected — tool binary checks skipped"
elif _on_kali; then
    # Tools that have been specifically problematic this session
    _CRITICAL_TOOLS=(
        nmap masscan hping3
        feroxbuster gobuster ffuf nikto whatweb
        sqlmap sslyze sslscan
        netexec smbmap enum4linux-ng ldapsearch rpcclient smbclient
        hydra searchsploit eyewitness
        dnsrecon dnsenum nbtscan
        snmpwalk onesixtyone
        impacket-rpcdump
        ssh-audit
        redis-cli mysql psql
        dig finger
    )
    _missing_tools=()
    for _t in "${_CRITICAL_TOOLS[@]}"; do
        command -v "${_t}" &>/dev/null || _missing_tools+=("${_t}")
    done
    if [[ ${#_missing_tools[@]} -eq 0 ]]; then
        _chk_ok "All critical tool binaries present in PATH"
    else
        for _t in "${_missing_tools[@]}"; do
            _chk_fail "Tool not found in PATH: ${_t}"
        done
    fi

    # rsh-client specifically — was a troublesome install this session
    if command -v rsh &>/dev/null && command -v rlogin &>/dev/null; then
        _chk_ok  "rsh and rlogin present (rsh-client)"
    else
        _chk_warn "rsh / rlogin not found — rsh-client or rsh-redone-client may be missing"
        _chk_warn "  → sudo apt-get install rsh-redone-client"
    fi

    # testssl — package is testssl.sh, binary is testssl
    if command -v testssl &>/dev/null; then
        _chk_ok  "testssl present (package: testssl.sh)"
    else
        _chk_fail "testssl not found — package name is testssl.sh (not testssl)"
        _chk_fail "  → sudo apt-get install testssl.sh"
    fi

    # Go tools
    _GO_TOOLS=( pd-httpx katana gau waybackurls nomore403 urlfinder )
    _missing_go=()
    for _t in "${_GO_TOOLS[@]}"; do
        command -v "${_t}" &>/dev/null || _missing_go+=("${_t}")
    done
    if [[ ${#_missing_go[@]} -eq 0 ]]; then
        _chk_ok  "All Go tools present in PATH"
    else
        for _t in "${_missing_go[@]}"; do
            _chk_warn "Go tool not found: ${_t} (run: sudo bash install.sh to reinstall Go tools)"
        done
    fi

    # /opt scripts
    [[ -f /opt/LeakSearch/LeakSearch.py ]] \
        && _chk_ok  "/opt/LeakSearch/LeakSearch.py present" \
        || _chk_warn "/opt/LeakSearch/LeakSearch.py missing — run: sudo bash install.sh"
    [[ -f /opt/jexboss/jexboss.py ]] \
        && _chk_ok  "/opt/jexboss/jexboss.py present" \
        || _chk_warn "/opt/jexboss/jexboss.py missing — run: sudo bash install.sh"
else
    _chk_warn "Not a Kali install — tool binary checks skipped"
fi

echo ""
echo -e "  ${BOLD}── Install log analysis ────────────────────────${NC}"
echo    "     Log file: ${INSTALL_LOG}"
echo ""

# Scan the install log for known error patterns from this session's troubleshooting
_LOG_ISSUES=0

_log_check() {
    local description="$1"
    local pattern="$2"
    local fix="$3"
    if grep -qE "${pattern}" "${INSTALL_LOG}" 2>/dev/null; then
        _chk_warn "LOG: ${description}"
        _chk_warn "     Fix: ${fix}"
        (( _LOG_ISSUES++ )) || true
    fi
}

_log_check \
    "ensurepip not available — python3-venv was missing during install" \
    "ensurepip is not available|No module named ensurepip" \
    "sudo apt-get install python3-venv"

_log_check \
    "pip dependency resolver conflict (likely mitmproxy/Kali tool)" \
    "dependency resolver does not currently|ResolutionImpossible|Cannot install.*and.*because" \
    "Conflicts are expected on Kali — Legion venv isolates them. Run: /opt/legion-venv/bin/pip check"

_log_check \
    "pip uninstall-no-record-file (Debian-managed package conflict)" \
    "uninstall-no-record-file|no-record-file" \
    "Use --ignore-installed flag or install into the venv instead of system Python"

_log_check \
    "'No module named pytest' — pytest missing from venv during verification" \
    "No module named pytest" \
    "sudo /opt/legion-venv/bin/pip install pytest"

_log_check \
    "rsh-client install conflict" \
    "rsh-client.*referred by|referred by.*rsh-client" \
    "sudo apt-get install rsh-redone-client"

_log_check \
    "testssl package not found (correct name is testssl.sh)" \
    "Unable to locate package testssl[^.]|testssl: command not found" \
    "sudo apt-get install testssl.sh"

_log_check \
    "Go not installed — Go tools (pd-httpx, katana, gau, etc.) were skipped" \
    "go: command not found|golang.*not installed|go install.*failed" \
    "sudo apt-get install golang-go  # or snap install go --classic"

_log_check \
    "Address already in use — another Legion instance was running on that port" \
    "Address already in use|OSError.*98.*address already" \
    "sudo pkill -f legion.py  # then retry"

_log_check \
    "geckodriver not found — Selenium tests will fail" \
    "geckodriver.*not found|No such file.*geckodriver" \
    "Install was attempted in step 7; check: ls -la /usr/local/bin/geckodriver"

_log_check \
    "Branch check failed — wrong git branch (should be flask-clean)" \
    "WARNING.*not on flask-clean|wrong branch" \
    "sudo git checkout flask-clean"

_log_check \
    "process_matches wrong column — old bug, should be fixed in current code" \
    "no such column: process_id.*process_matches|OperationalError.*process_id" \
    "Update to latest flask-clean branch: sudo git pull"

if [[ $_LOG_ISSUES -eq 0 ]]; then
    _chk_ok "No known error patterns found in install log"
fi

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Health check summary ────────────────────────${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} Passed  : ${_CHECK_PASS}"
if [[ $_CHECK_WARN -gt 0 ]]; then
    echo -e "  ${YELLOW}!${NC} Warnings: ${_CHECK_WARN}"
fi
if [[ $_CHECK_FAIL -gt 0 ]]; then
    echo -e "  ${RED}✗${NC} Failed  : ${_CHECK_FAIL}"
fi
echo ""
if [[ $_CHECK_FAIL -eq 0 && $_CHECK_WARN -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}Environment is fully healthy.${NC}"
elif [[ $_CHECK_FAIL -eq 0 ]]; then
    echo -e "  ${YELLOW}${BOLD}Environment is functional with warnings — review items above.${NC}"
else
    echo -e "  ${RED}${BOLD}${_CHECK_FAIL} check(s) failed — review items above before running Legion.${NC}"
fi
echo ""
echo -e "  Full install log saved to: ${INSTALL_LOG}"

set -e

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║      Legion installation complete          ║${NC}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Legion uses a dedicated Python venv at:${NC}  ${LEGION_VENV}"
echo    "  The 'legion-python3' symlink always points to it."
echo ""
echo -e "  ${BOLD}Start (opens Firefox automatically):${NC}"
echo    "    sudo legion-python3 legion.py --web"
echo ""
echo -e "  ${BOLD}Custom port:${NC}"
echo    "    sudo legion-python3 legion.py --web --port 8080"
echo ""
echo -e "  ${BOLD}Headless (open http://127.0.0.1:5000 yourself):${NC}"
echo    "    sudo legion-python3 legion.py --web --no-browser"
echo ""
echo -e "  ${BOLD}Qt6 desktop GUI (requires X11 display):${NC}"
echo    "    sudo legion-python3 legion.py"
echo ""
