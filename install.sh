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

echo ""
echo -e "${BOLD}Legion — Automated Installer${NC}"
echo -e "  Working directory : ${SCRIPT_DIR}"
echo -e "  Running as        : root  (real user: ${REAL_USER})"
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
step "1/9  apt-get update + install packages"

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
step "2/9  Go-based tools"

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
step "3/9  GitHub binary tools"

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
step "4/9  /opt tools  (jexboss, LeakSearch)"

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
step "5/9  Python virtual environment + packages"

LEGION_VENV=/opt/legion-venv
cd "${SCRIPT_DIR}"
[[ -f requirements.txt ]] || die "requirements.txt not found in ${SCRIPT_DIR}"

# Ensure python3-venv is available
if ! python3 -m venv --help &>/dev/null 2>&1; then
    info "Installing python3-venv…"
    sudo apt-get install -y python3-venv 2>/dev/null \
        && ok "python3-venv installed" \
        || die "python3-venv unavailable — cannot create virtual environment"
fi

# Create (or reuse) the venv
if [[ -f "${LEGION_VENV}/bin/python3" ]]; then
    ok "Virtual environment already exists at ${LEGION_VENV}"
else
    info "Creating virtual environment at ${LEGION_VENV}…"
    sudo python3 -m venv "${LEGION_VENV}"
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
step "6/9  nuclei + templates"

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
step "7/9  geckodriver + Firefox profile"

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
step "8/9  Verification + auto-remediation"

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
    step "9/9  AI tab  (Vertex AI — optional)"
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
