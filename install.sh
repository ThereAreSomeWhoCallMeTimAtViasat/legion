#!/usr/bin/env bash
# =============================================================================
# Legion — Full Automated Installer
# =============================================================================
# Installs EVERYTHING needed to run Legion in web mode (--web) on Kali Linux
# or Ubuntu 22.04+.  Completely self-contained — does not depend on any other
# script in the repo.  Safe to run more than once (idempotent).
#
# Usage:
#   sudo bash install.sh           # full install
#   sudo bash install.sh --no-ai  # skip Vertex AI setup prompt
#
# What this installs:
#   1.  apt packages  — system libs, python3, Go, Firefox, geckodriver, and
#                       all 40+ security tools Legion calls (nmap, masscan,
#                       feroxbuster, netexec, eyewitness, hydra, etc.)
#   2.  Go binaries   — pd-httpx, katana, gau, waybackurls, nomore403, urlfinder
#   3.  GitHub tools  — kerbrute (binary), rdp-sec-check (Perl)
#   4.  /opt tools    — jexboss, LeakSearch (Python, cloned from GitHub)
#   5.  Python pkgs   — requirements.txt (Flask + Qt6 + shared + AI)
#   6.  nuclei tmpl   — template update so nuclei can actually scan
#   7.  Firefox prof  — dedicated legion-profile so --web never conflicts
#   8.  Verification  — runs tests/test_requirements.py to confirm everything
#   9.  AI tab        — optional Vertex AI / gcloud setup prompt
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { echo -e "  ${GREEN}✓${NC}  $*"; }
fail()  { echo -e "  ${RED}✗${NC}  $*"; }
warn()  { echo -e "  ${YELLOW}!${NC}  $*"; }
info()  { echo -e "  ${BLUE}→${NC}  $*"; }
step()  { echo -e "\n${BOLD}${BLUE}══ $* ${NC}"; }
die()   { echo -e "\n${RED}FATAL: $*${NC}" >&2; exit 1; }
try()   {   # try DESCRIPTION COMMAND…
    local desc="$1"; shift
    if "$@" &>/dev/null; then ok "$desc"; else warn "$desc (non-fatal, continuing)"; fi
}

# ── Args ──────────────────────────────────────────────────────────────────────
SKIP_AI=false
for arg in "$@"; do
    case "$arg" in
        --no-ai)   SKIP_AI=true ;;
        -h|--help)
            echo "Usage: sudo bash install.sh [--no-ai]"
            echo "  --no-ai   skip Vertex AI / gcloud setup prompt at the end"
            exit 0 ;;
    esac
done

# ── Root ──────────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run with sudo:  sudo bash $0"

# Non-root caller (for profile/settings ownership)
REAL_USER="${SUDO_USER:-root}"
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6 2>/dev/null || echo "${HOME}")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}Legion — Automated Installer${NC}"
echo -e "  Working directory : ${SCRIPT_DIR}"
echo -e "  Running as        : root (real user: ${REAL_USER})"
echo ""

# ── Branch guard ──────────────────────────────────────────────────────────────
CURRENT_BRANCH=$(git -C "${SCRIPT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
if [[ "${CURRENT_BRANCH}" != "flask-clean" ]]; then
    echo -e "${RED}"
    echo "  ╔═══════════════════════════════════════════════════════════════════╗"
    echo "  ║  WRONG BRANCH  —  you are on '${CURRENT_BRANCH}'                         "
    echo "  ║                                                                   ║"
    echo "  ║  The Flask web UI (--web mode) lives on the 'flask-clean' branch.║"
    echo "  ║  'master' is the original upstream Qt5 desktop app and will not  ║"
    echo "  ║  work with this installer.                                        ║"
    echo "  ║                                                                   ║"
    echo "  ║  Fix:                                                             ║"
    echo "  ║    git checkout flask-clean                                       ║"
    echo "  ║    sudo bash install.sh                                           ║"
    echo "  ╚═══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    exit 1
fi
ok "Branch: ${CURRENT_BRANCH}"

# =============================================================================
# 1. APT — update, then install EVERYTHING in one pass
# =============================================================================
step "1/9  apt-get update + install all packages"

info "Updating package index…"
apt-get update -q
ok "Package index updated"

info "Installing critical runtime packages (Python, Go, libs, Firefox)…"
info "This block must succeed — if it fails the rest cannot continue."

# ── Block A: Critical — must all be available; fail loud if not ──────────────
# These are packages that legion.py itself needs at startup.
# No --ignore-missing here: we want a clear failure if Go or Python cannot install.
apt-get install -y \
    curl wget git ca-certificates unzip build-essential \
    python3 python3-pip python3-dev \
    golang-go \
    libssl3 openssl \
    libgl1 libegl1 libglib2.0-0 libdbus-1-3 \
    libfontconfig1 libfreetype6 libx11-6 libxext6 libxrender1 \
    libxcb1 libxkbcommon0 libxcb-cursor0 \
    xvfb x11-utils \
    firefox-esr

ok "Critical packages installed (Python $(python3 --version | grep -oP '[\d.]+'), Go $(go version | grep -oP 'go[\d.]+'))"

# Verify the non-negotiables came through before continuing
for req in python3 go git curl; do
    command -v "$req" &>/dev/null \
        && ok "  $req → $(command -v $req)" \
        || die "$req still missing after apt install — check apt sources and network, then retry"
done

# ── Block B: Security tools — install with --ignore-missing ─────────────────
# Any individual package may be unavailable on older/different distros.
# apt-get --ignore-missing skips missing packages and installs the rest.
# This block never causes the script to abort.
info "Installing security tools (--ignore-missing — individual failures are OK)…"

apt-get install -y --ignore-missing \
    `# Core scanning` \
    nmap masscan hping3 ike-scan \
    `# Web tools` \
    feroxbuster gobuster ffuf nikto whatweb wafw00f \
    wpscan joomscan davtest sqlmap sslyze sslscan testssl \
    `# Network recon` \
    dnsrecon dnsenum nbtscan onesixtyone \
    snmpwalk snmpcheck \
    rpcinfo nfs-common \
    ldap-utils \
    `# SMB / Windows` \
    netexec smbmap enum4linux-ng ldapdomaindump \
    smbclient \
    `# Impacket` \
    impacket-scripts \
    `# Auth / brute` \
    hydra medusa \
    `# Screenshooter` \
    eyewitness \
    `# Host recon` \
    exploitdb theharvester bloodhound-python \
    `# Vulnerability scanning` \
    nuclei \
    `# SSH / RDP` \
    ssh-audit \
    `# Database clients` \
    redis-tools default-mysql-client postgresql-client \
    `# Mail` \
    swaks smtp-user-enum \
    `# Network legacy (rsh-client may not exist on all distros — OK to skip)` \
    finger \
    `# Misc` \
    net-tools nbtscan \
    2>/dev/null || true   # apt exit code is ignored — missing packages are expected

ok "Security tool packages installed (some may have been skipped on this distro)"

# =============================================================================
# 2. Go-based tools
# =============================================================================
step "2/9  Go-based tools  (pd-httpx, katana, gau, waybackurls, nomore403, urlfinder)"

GO_TOOLS=(
    "github.com/projectdiscovery/httpx/cmd/httpx@latest:pd-httpx"
    "github.com/projectdiscovery/katana/cmd/katana@latest:katana"
    "github.com/lc/gau/v2/cmd/gau@latest:gau"
    "github.com/tomnomnom/waybackurls@latest:waybackurls"
    "github.com/devploit/nomore403@latest:nomore403"
    "github.com/projectdiscovery/urlfinder/cmd/urlfinder@latest:urlfinder"
)

for pkg_dest in "${GO_TOOLS[@]}"; do
    pkg="${pkg_dest%%:*}"
    dest="${pkg_dest##*:}"
    if command -v "$dest" &>/dev/null; then
        ok "$dest already installed at $(command -v $dest)"
        continue
    fi
    info "go install $pkg → $dest…"
    tmpdir=$(mktemp -d)
    if GOPATH="$tmpdir" HOME=/root go install "$pkg" 2>/dev/null; then
        bin=$(find "$tmpdir/bin" -maxdepth 1 -type f | head -1)
        if [[ -f "$bin" ]]; then
            cp "$bin" "/usr/local/bin/$dest"
            chmod +x "/usr/local/bin/$dest"
            ok "$dest installed at /usr/local/bin/$dest"
        else
            warn "$dest: binary not found after go install — skipping"
        fi
    else
        warn "$dest: go install failed — skipping (non-fatal)"
    fi
    rm -rf "$tmpdir"
done

# =============================================================================
# 3. GitHub binary tools
# =============================================================================
step "3/9  GitHub binary tools  (kerbrute, rdp-sec-check)"

# kerbrute
if command -v kerbrute &>/dev/null; then
    ok "kerbrute already at $(command -v kerbrute)"
else
    info "Downloading kerbrute…"
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  KERB_FILE="kerbrute_linux_amd64" ;;
        aarch64) KERB_FILE="kerbrute_linux_arm64" ;;
        *)        warn "Unknown arch $ARCH — skipping kerbrute"; KERB_FILE="" ;;
    esac
    if [[ -n "$KERB_FILE" ]]; then
        URL="https://github.com/ropnop/kerbrute/releases/latest/download/${KERB_FILE}"
        if curl -fsSL "$URL" -o /usr/local/bin/kerbrute 2>/dev/null; then
            chmod +x /usr/local/bin/kerbrute
            ok "kerbrute installed at /usr/local/bin/kerbrute"
        else
            warn "kerbrute download failed — skipping (non-fatal)"
        fi
    fi
fi

# rdp-sec-check
if command -v rdp-sec-check &>/dev/null; then
    ok "rdp-sec-check already at $(command -v rdp-sec-check)"
else
    info "Installing rdp-sec-check…"
    if apt-get install -y rdp-sec-check 2>/dev/null; then
        ok "rdp-sec-check installed via apt"
    else
        info "Not in apt — cloning from GitHub…"
        RDP_DIR=/opt/rdp-sec-check
        if git clone --depth 1 https://github.com/CiscoCXSecurity/rdp-sec-check.git \
                "$RDP_DIR" 2>/dev/null; then
            command -v cpanm &>/dev/null && \
                cpanm --quiet Encoding::BER 2>/dev/null || true
            printf '#!/bin/bash\nexec perl /opt/rdp-sec-check/rdp-sec-check.pl "$@"\n' \
                > /usr/local/bin/rdp-sec-check
            chmod +x /usr/local/bin/rdp-sec-check
            ok "rdp-sec-check installed at /usr/local/bin/rdp-sec-check"
        else
            warn "rdp-sec-check clone failed — skipping (non-fatal)"
        fi
    fi
fi

# =============================================================================
# 4. /opt tools  (jexboss, LeakSearch)
# =============================================================================
step "4/9  /opt tools  (jexboss, LeakSearch)"

# jexboss
if [[ -f /opt/jexboss/jexboss.py ]]; then
    ok "jexboss already at /opt/jexboss"
else
    info "Cloning jexboss…"
    if git clone --depth 1 https://github.com/joaomatosf/jexboss.git \
            /opt/jexboss 2>/dev/null; then
        [[ -f /opt/jexboss/requires.txt ]] && \
            python3 -m pip install --break-system-packages -q \
                -r /opt/jexboss/requires.txt 2>/dev/null || true
        ok "jexboss installed at /opt/jexboss/jexboss.py"
    else
        warn "jexboss clone failed — skipping (non-fatal)"
    fi
fi

# LeakSearch
if [[ -f /opt/LeakSearch/LeakSearch.py ]]; then
    ok "LeakSearch already at /opt/LeakSearch"
else
    info "Cloning LeakSearch…"
    if git clone --depth 1 https://github.com/JoelGMSec/LeakSearch.git \
            /opt/LeakSearch 2>/dev/null; then
        [[ -f /opt/LeakSearch/requirements.txt ]] && \
            python3 -m pip install --break-system-packages -q \
                -r /opt/LeakSearch/requirements.txt 2>/dev/null || true
        ok "LeakSearch installed at /opt/LeakSearch/LeakSearch.py"
    else
        warn "LeakSearch clone failed — skipping (non-fatal)"
    fi
fi

# neotermcolor — required by LeakSearch at runtime
if python3 -c "import neotermcolor" 2>/dev/null; then
    ok "neotermcolor already installed"
else
    info "Installing neotermcolor (LeakSearch dependency)…"
    python3 -m pip install --break-system-packages -q neotermcolor && \
        ok "neotermcolor installed" || warn "neotermcolor install failed (non-fatal)"
fi

# =============================================================================
# 5. Python packages  (requirements.txt)
# =============================================================================
step "5/9  Python packages  (requirements.txt)"

cd "${SCRIPT_DIR}"
[[ -f requirements.txt ]] || die "requirements.txt not found in ${SCRIPT_DIR}"

info "Installing Flask + Qt6 + shared + AI Python dependencies…"
python3 -m pip install --break-system-packages -q -r requirements.txt \
    && ok "requirements.txt installed" \
    || die "pip install -r requirements.txt failed — check the error above"

info "Verifying critical imports…"
ALL_OK=true
for pkg in flask sqlalchemy requests PyQt6.QtCore anthropic; do
    if python3 -c "import ${pkg}" 2>/dev/null; then
        ok "  import ${pkg}"
    else
        fail "  import ${pkg} — FAILED"
        ALL_OK=false
    fi
done
$ALL_OK || warn "Some imports failed — check pip output above; web mode may still work"

# =============================================================================
# 6. nuclei templates
# =============================================================================
step "6/9  nuclei templates"

if command -v nuclei &>/dev/null; then
    NUCLEI_DIR="${REAL_HOME}/.local/nuclei-templates"
    if [[ -d "$NUCLEI_DIR" && -n "$(ls -A "$NUCLEI_DIR" 2>/dev/null)" ]]; then
        ok "nuclei templates already present at ${NUCLEI_DIR}"
    else
        info "Downloading nuclei templates (may take a minute)…"
        HOME="${REAL_HOME}" nuclei -update-templates 2>/dev/null && \
            ok "nuclei templates ready" || \
            warn "nuclei template download failed — run 'nuclei -update-templates' manually"
    fi
else
    warn "nuclei not found — skipping template download"
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
    case "$ARCH" in
        x86_64)  GD_ARCH="linux64" ;;
        aarch64) GD_ARCH="linux-aarch64" ;;
        *)        GD_ARCH="linux64"; warn "Assuming linux64 for geckodriver" ;;
    esac
    GD_URL="https://github.com/mozilla/geckodriver/releases/download/v0.35.0/geckodriver-v0.35.0-${GD_ARCH}.tar.gz"
    TMP=$(mktemp -d)
    if curl -fsSL "$GD_URL" | tar xz -C "$TMP" 2>/dev/null && [[ -f "$TMP/geckodriver" ]]; then
        mv "$TMP/geckodriver" /usr/local/bin/geckodriver
        chmod +x /usr/local/bin/geckodriver
        ok "geckodriver installed at /usr/local/bin/geckodriver"
    else
        warn "geckodriver download failed — Selenium tests will not work"
    fi
    rm -rf "$TMP"
fi

PROFILE_DIR="${REAL_HOME}/.mozilla/firefox/legion-profile"
if [[ -d "$PROFILE_DIR" ]]; then
    ok "Legion Firefox profile already exists"
else
    mkdir -p "$PROFILE_DIR"
    [[ "$REAL_USER" != "root" ]] && \
        chown -R "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.mozilla" 2>/dev/null || true
    ok "Firefox profile created at ${PROFILE_DIR}"
fi

# =============================================================================
# 8. Verification
# =============================================================================
step "8/9  Verification"

info "Running install verification tests (~45 seconds)…"
cd "${SCRIPT_DIR}"

if python3 -m pytest tests/test_requirements.py --noconftest -q --tb=line 2>&1; then
    ok "All verification tests passed"
else
    warn "Some tests failed — see output above"
    warn "Legion --web may still work; tool binary failures are non-fatal"
fi

echo ""
info "Tool binary presence check:"
MISSING=()
for tool in nmap masscan feroxbuster gobuster nuclei netexec eyewitness hydra \
            ssh-audit pd-httpx katana gau waybackurls nomore403 urlfinder \
            kerbrute dnsrecon snmpwalk ldapsearch impacket-rpcdump; do
    if command -v "$tool" &>/dev/null; then
        ok "  $tool"
    else
        fail "  $tool — NOT FOUND"
        MISSING+=("$tool")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    warn "${#MISSING[@]} tool(s) not found: ${MISSING[*]}"
    warn "Run 'sudo apt-get install ${MISSING[*]}' or re-run this installer"
else
    ok "All checked tools are in PATH"
fi

# =============================================================================
# 9. AI tab setup (optional)
# =============================================================================
if ! $SKIP_AI; then
    step "9/9  AI tab  (Vertex AI — optional)"
    echo ""
    echo "  The AI tab uses Anthropic Claude via Google Cloud Vertex AI."
    echo "  You need a GCP project with the Vertex AI API enabled."
    echo "  Authentication uses Application Default Credentials (no API key stored)."
    echo ""
    read -r -p "  Configure AI tab now? [y/N] " SETUP_AI
    if [[ "${SETUP_AI,,}" == "y" ]]; then
        echo ""
        read -r -p "  GCP project ID (e.g. my-project-123): " GCP_PROJECT
        read -r -p "  Vertex AI region [global]: " GCP_REGION
        GCP_REGION="${GCP_REGION:-global}"

        CLAUDE_SETTINGS="${REAL_HOME}/.claude/settings.json"
        mkdir -p "$(dirname "$CLAUDE_SETTINGS")"

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
            chown -R "${REAL_USER}:${REAL_USER}" "$(dirname "$CLAUDE_SETTINGS")" 2>/dev/null || true

        echo ""
        ok "AI settings written to ${CLAUDE_SETTINGS}"
        echo ""
        info "Next — authenticate with Google Cloud (run as your normal user, not root):"
        echo ""
        echo "      gcloud auth application-default login"
        echo ""
    else
        info "Skipped — configure later by editing ~/.claude/settings.json"
        info "and running: gcloud auth application-default login"
    fi
fi

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║       Legion installation complete        ║${NC}"
echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Start (opens Firefox automatically):${NC}"
echo    "    sudo python3 legion.py --web"
echo ""
echo -e "  ${BOLD}Custom port:${NC}"
echo    "    sudo python3 legion.py --web --port 8080"
echo ""
echo -e "  ${BOLD}Headless (open http://127.0.0.1:5000 yourself):${NC}"
echo    "    sudo python3 legion.py --web --no-browser"
echo ""
echo -e "  ${BOLD}Qt6 desktop GUI (requires X11 display):${NC}"
echo    "    sudo python3 legion.py"
echo ""
