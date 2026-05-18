#!/usr/bin/env bash
# -----------------------------------------------------------------------
# LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
# Author: Tim McLean (Viasat, Inc.)
# Copyright (c) 2025-2026 Viasat, Inc.
# Copyright (c) 2025 Shane William Scott (original Legion)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
# IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE.
# -----------------------------------------------------------------------

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

# Prevent dpkg debconf dialogs (keyboard-configuration, etc.) from blocking
# the install — especially in WSL where whiptail cannot read stdin through
# the tee pipe on line 45.
export DEBIAN_FRONTEND=noninteractive

# Accept all defaults in CPAN/MakeMaker without prompting (first-run
# "Would you like to configure automatically?" dialog blocks on tee pipe).
export PERL_MM_USE_DEFAULT=1

# In Docker / root-only environments, sudo is not installed — define a shim
# so every 'sudo cmd' in this script just runs 'cmd' directly.
# On real systems, wrap sudo to pass DEBIAN_FRONTEND through — sudo's
# env_reset strips exported vars, and minimal Kali installs (WSL) may not
# have env_keep configured for DEBIAN_FRONTEND in sudoers.
if ! command -v sudo &>/dev/null; then
    sudo() { "$@"; }
    export -f sudo
    info "sudo not found — running as root, shim active"
else
    _REAL_SUDO="$(command -v sudo)"
    sudo() { $_REAL_SUDO DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}" PERL_MM_USE_DEFAULT="${PERL_MM_USE_DEFAULT:-1}" "$@"; }
    export -f sudo
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
    elif [[ "${CURRENT_BRANCH}" != "flask-clean" && "${CURRENT_BRANCH}" != "flask-clean-prod" ]]; then
        echo -e "${RED}"
        echo "  ╔═══════════════════════════════════════════════════════════════════╗"
        echo "  ║  WRONG BRANCH: you are on '${CURRENT_BRANCH}'                          "
        echo "  ║  Use 'flask-clean' (dev) or 'flask-clean-prod' (production).     ║"
        echo "  ║  Fix:  sudo git checkout flask-clean-prod && sudo bash install.sh║"
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
            }
            # Perl dependency: Encoding::BER — required by rdp-sec-check.pl
            # Without this, rdp-sec-check fails: "Can't locate Encoding/BER.pm"
            if ! perl -e 'use Encoding::BER' 2>/dev/null; then
                info "  Installing Perl Encoding::BER for rdp-sec-check…"
                sudo apt-get install -y libencoding-ber-perl 2>/dev/null \
                    && ok "  libencoding-ber-perl installed via apt" \
                    || {
                        command -v cpanm &>/dev/null \
                            && sudo cpanm --quiet Encoding::BER 2>/dev/null \
                            || sudo cpan -i Encoding::BER 2>/dev/null
                        perl -e 'use Encoding::BER' 2>/dev/null \
                            && ok "  Encoding::BER installed via CPAN" \
                            || warn "  Encoding::BER install failed — run: sudo apt-get install libencoding-ber-perl"
                    }
            fi
            ;;
        ssh-audit)
            sudo apt-get install -y ssh-audit 2>/dev/null || {
                sudo "${VENV}/bin/pip" install ssh-audit 2>/dev/null \
                    && sudo ln -sf "${VENV}/bin/ssh-audit" /usr/local/bin/ssh-audit
            } ;;
        # Binary name differs from apt package name
        snmpwalk|snmpcheck)  sudo apt-get install -y snmp 2>/dev/null || true ;;
        rpcinfo)             sudo apt-get install -y rpcbind 2>/dev/null || true ;;
        ldapdomaindump)      sudo apt-get install -y python3-ldapdomaindump 2>/dev/null || true ;;
        mysql)               sudo apt-get install -y default-mysql-client 2>/dev/null || true ;;
        psql)                sudo apt-get install -y postgresql-client 2>/dev/null || true ;;
        redis-cli)           sudo apt-get install -y redis-tools 2>/dev/null || true ;;
        searchsploit)        sudo apt-get install -y exploitdb 2>/dev/null || true ;;
        testssl)             sudo apt-get install -y testssl.sh 2>/dev/null || true ;;
        ldapsearch)          sudo apt-get install -y ldap-utils 2>/dev/null || true ;;
        rpcclient)           sudo apt-get install -y smbclient 2>/dev/null || true ;;
        bloodhound-python)   sudo apt-get install -y bloodhound.py 2>/dev/null || true ;;
        ldeep)               sudo "${VENV_PIP:-pip3}" install --root-user-action=ignore -q ldeep 2>/dev/null \
                                 && sudo ln -sf "${LEGION_VENV:-/opt/legion-venv}/bin/ldeep" /usr/local/bin/ldeep 2>/dev/null || true ;;
        windapsearch)
            local _ws_arch="amd64"; [[ "$(uname -m)" == "aarch64" ]] && _ws_arch="arm64"
            sudo curl -fsSL \
                "https://github.com/ropnop/go-windapsearch/releases/download/v0.3.0/windapsearch-linux-${_ws_arch}" \
                -o /usr/local/bin/windapsearch 2>/dev/null \
                && sudo chmod +x /usr/local/bin/windapsearch || true ;;
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

# ── Ensure Kali rolling repos are configured ──────────────────────────────────
# Minimal Kali installs (WSL, cloud images, containers) may ship with an empty
# or commented-out sources.list.  Without the full kali-rolling repo, most
# security tools (feroxbuster, gobuster, nuclei, netexec, etc.) are unavailable
# via apt.  This block ensures the repo line is present and the signing key is
# installed before we run apt-get update.
SOURCES="/etc/apt/sources.list"
KALI_REPO="deb http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware"

if grep -qsE '^\s*ID(_LIKE)?=.*kali' /etc/os-release 2>/dev/null; then
    # This is a Kali system — ensure the repo is configured
    if ! grep -qs '^deb.*kali-rolling' "$SOURCES" 2>/dev/null; then
        info "Kali rolling repository not found in ${SOURCES} — adding it…"
        echo "$KALI_REPO" | sudo tee -a "$SOURCES" > /dev/null
        ok "Added kali-rolling to ${SOURCES}"
    else
        ok "Kali rolling repository already configured"
    fi

    # Ensure the archive keyring is installed (needed to verify packages)
    if ! dpkg -l kali-archive-keyring &>/dev/null 2>&1; then
        info "Installing kali-archive-keyring…"
        # Bootstrap: fetch the keyring .deb directly since apt can't verify
        # packages without it.  wget/curl are in Block A but may already be
        # present on minimal installs.
        if command -v wget &>/dev/null; then
            _KR_DEB=$(mktemp /tmp/kali-keyring-XXXX.deb)
            wget -q "https://http.kali.org/kali/pool/main/k/kali-archive-keyring/kali-archive-keyring_2024.1_all.deb" \
                -O "$_KR_DEB" 2>/dev/null \
                && sudo dpkg -i "$_KR_DEB" 2>/dev/null \
                && ok "kali-archive-keyring installed" \
                || warn "kali-archive-keyring bootstrap failed — apt may show GPG warnings"
            rm -f "$_KR_DEB"
        elif command -v curl &>/dev/null; then
            _KR_DEB=$(mktemp /tmp/kali-keyring-XXXX.deb)
            curl -fsSL "https://http.kali.org/kali/pool/main/k/kali-archive-keyring/kali-archive-keyring_2024.1_all.deb" \
                -o "$_KR_DEB" 2>/dev/null \
                && sudo dpkg -i "$_KR_DEB" 2>/dev/null \
                && ok "kali-archive-keyring installed" \
                || warn "kali-archive-keyring bootstrap failed — apt may show GPG warnings"
            rm -f "$_KR_DEB"
        else
            warn "Neither wget nor curl available — cannot bootstrap kali-archive-keyring"
        fi
    else
        ok "kali-archive-keyring present"
    fi
else
    info "Not a Kali system — skipping Kali repo check"
fi

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

# Ensure all packages are fully configured — if a previous install was
# interrupted (e.g. by keyboard-configuration dialog freeze), some packages
# may be left in a half-configured state where the binary exists but
# post-install scripts never ran (e.g. firefox-esr can't create profiles).
sudo dpkg --configure -a 2>/dev/null || true

ok "Critical packages installed  (Python $(python3 --version | grep -oP '[\d.]+')  Go $(go version | grep -oP 'go[\d.]+'))"

for req in python3 go git curl; do
    command -v "$req" &>/dev/null \
        && ok "  $req → $(command -v $req)" \
        || die "$req missing after apt — check network / apt sources and retry"
done

# nmap is Legion's core dependency — install separately with explicit verification
info "Installing nmap (Legion core dependency)…"
if ! command -v nmap &>/dev/null; then
    sudo apt-get install -y nmap \
        && ok "nmap installed at $(command -v nmap)" \
        || {
            warn "nmap apt install failed — trying with --fix-missing…"
            sudo apt-get install -y --fix-missing nmap 2>/dev/null \
                && ok "nmap installed via --fix-missing" \
                || die "nmap could not be installed. Legion requires nmap. Try: sudo apt-get install nmap"
        }
else
    ok "nmap already at $(command -v nmap)"
fi

# Block B — required security tools: used by legion.conf scheduler, port
# actions, or core workflows.  Each is installed individually so a failure
# is reported clearly instead of being swallowed by --ignore-missing.
info "Installing required security tools…"

_REQUIRED_TOOLS=(
    # Web scanning (SchedulerSettings + PortActions)
    feroxbuster gobuster ffuf nikto whatweb wafw00f wpscan nuclei
    # Brute force
    hydra medusa
    # SMB / Windows
    netexec smbmap enum4linux-ng smbclient impacket-scripts
    # Recon / enumeration
    dnsrecon masscan hping3 fierce
    # SSL/TLS
    sslscan sslyze testssl.sh
    # SSH
    ssh-audit
    # Screenshotter
    eyewitness
    # Exploit research
    exploitdb
    # Database clients (scheduler output parsing)
    redis-tools default-mysql-client postgresql-client
    # SNMP / RPC / NFS (snmp provides snmpwalk+snmpcheck; rpcbind provides rpcinfo)
    snmp onesixtyone rpcbind nfs-common
    # LDAP (python3-ldapdomaindump is the apt package name)
    ldap-utils python3-ldapdomaindump
    # Protocol tools
    swaks smtp-user-enum finger nbtscan
    # Wordlists
    seclists
)

REQUIRED_FAIL=0
for _pkg in "${_REQUIRED_TOOLS[@]}"; do
    if dpkg -l "$_pkg" &>/dev/null 2>&1; then
        ok "  $_pkg"
    else
        if sudo apt-get install -y "$_pkg" 2>/dev/null; then
            ok "  $_pkg installed"
        else
            fail "  $_pkg — install failed"
            REQUIRED_FAIL=$((REQUIRED_FAIL + 1))
        fi
    fi
done

if [[ $REQUIRED_FAIL -gt 0 ]]; then
    warn "${REQUIRED_FAIL} required tool(s) failed to install — check apt sources and retry"
    warn "These tools are used by legion.conf and scans will be incomplete without them"
fi

# Block C — optional tools: useful but not in the core scheduler/actions.
# Missing packages are warned, not fatal.
info "Installing optional tools…"

_OPTIONAL_TOOLS=(
    ike-scan joomscan davtest sqlmap dnsenum
    theharvester bloodhound.py
    net-tools
    gpp-decrypt python3-impacket responder hashcat john
)

for _pkg in "${_OPTIONAL_TOOLS[@]}"; do
    if dpkg -l "$_pkg" &>/dev/null 2>&1; then
        ok "  $_pkg"
    else
        sudo apt-get install -y "$_pkg" 2>/dev/null \
            && ok "  $_pkg installed" \
            || warn "  $_pkg — not available (optional, scans will still work)"
    fi
done

# Victim test infrastructure — servers that test_victim_tool_execution.py scans
# against locally.  These are NOT Legion runtime deps; they are the target services
# that let the test verify every scheduler tool actually runs and produces output.
info "  Installing victim test server dependencies (nginx, mariadb, redis, samba, snmpd, xrdp)…"
if sudo apt-get install -y nginx mariadb-server redis-server samba snmpd xrdp; then
    ok "  Victim test server packages installed"
else
    warn "  Some victim test server packages failed — victim tool execution test may skip"
fi

ok "Security tool packages done (some may be skipped on non-Kali)"

# AD enumeration tools (pip) — installed into the Legion venv in step 5.
# System pip conflicts with apt-managed packages (e.g. termcolor), so these
# MUST go into the venv. Deferred to after step 5 creates LEGION_VENV.
_AD_PIP_TOOLS=(certipy-ad adidnsdump ldeep pywerview)

# windapsearch (GitHub binary — go install doesn't work, build uses magefile)
if command -v windapsearch &>/dev/null; then
    ok "windapsearch already installed at $(command -v windapsearch)"
else
    info "Installing windapsearch from GitHub release…"
    _ws_arch="amd64"; [[ "$(uname -m)" == "aarch64" ]] && _ws_arch="arm64"
    sudo curl -fsSL \
        "https://github.com/ropnop/go-windapsearch/releases/download/v0.3.0/windapsearch-linux-${_ws_arch}" \
        -o /usr/local/bin/windapsearch 2>/dev/null \
        && sudo chmod +x /usr/local/bin/windapsearch \
        && ok "windapsearch installed" \
        || warn "windapsearch download failed"
fi

# subfinder (Go binary)
if command -v subfinder &>/dev/null; then
    ok "subfinder already installed at $(command -v subfinder)"
else
    _go_install_bin "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest" "subfinder"
fi

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

# rsh — 'rsh-client' is a virtual package on Kali, provided by rsh-redone-client.
# On older Debian/Ubuntu, rsh-client is the real package name.
if dpkg -l rsh-redone-client 2>/dev/null | grep -q '^ii' || dpkg -l rsh-client 2>/dev/null | grep -q '^ii'; then
    ok "rsh-client already installed"
else
    info "Installing rsh (rsh-redone-client)…"
    sudo apt-get install -y rsh-redone-client 2>/dev/null \
        && ok "rsh-redone-client installed" \
        || { sudo apt-get install -y rsh-client 2>/dev/null \
            && ok "rsh-client installed" \
            || warn "rsh-client install failed — optional legacy tool"; }
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

PIP_OUTPUT=$(sudo "${VENV_PIP}" install \
        --root-user-action=ignore \
        -r requirements.txt 2>&1)
PIP_RC=$?
echo "$PIP_OUTPUT" | grep -E "^Collecting|Installing collected|Successfully installed|error:|ERROR:|Requirement already" || true
if [[ $PIP_RC -eq 0 ]]; then
    ok "requirements.txt installed into ${LEGION_VENV}"
else
    echo "$PIP_OUTPUT" | tail -20
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

# AD enumeration pip tools (deferred from step 1 — need the venv to avoid
# conflicts with apt-managed packages like termcolor)
info "Installing AD enumeration pip packages into venv…"
for _ad_pip in "${_AD_PIP_TOOLS[@]}"; do
    if "${VENV_PIP}" show "$_ad_pip" &>/dev/null 2>&1; then
        ok "  $_ad_pip already in venv"
    else
        sudo "${VENV_PIP}" install --root-user-action=ignore -q "$_ad_pip" 2>/dev/null \
            && ok "  $_ad_pip installed into venv" \
            || warn "  $_ad_pip pip install failed"
    fi
done
# Symlink AD tool binaries from venv into PATH
for _ad_bin in certipy-ad adidnsdump ldeep pywerview windapsearch; do
    _venv_bin="${LEGION_VENV}/bin/${_ad_bin}"
    if [[ -f "$_venv_bin" ]] && ! command -v "$_ad_bin" &>/dev/null; then
        sudo ln -sf "$_venv_bin" "/usr/local/bin/${_ad_bin}" 2>/dev/null \
            && ok "  Symlink: ${_ad_bin} → ${_venv_bin}"
    fi
done

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

# Fix ownership — templates downloaded as root but should be owned by the real user
if [[ -d "$NUCLEI_DIR" && "${REAL_USER}" != "root" ]]; then
    sudo chown -R "${REAL_USER}:${REAL_USER}" "$NUCLEI_DIR" 2>/dev/null \
        && ok "nuclei templates ownership set to ${REAL_USER}" \
        || warn "could not chown nuclei templates — run: sudo chown -R ${REAL_USER}:${REAL_USER} ${NUCLEI_DIR}"
fi

# Create nuclei config directory for the real user so nuclei can write its
# .templates-config.json when invoked as root (e.g. sudo legion-python3 legion.py).
# Without this, nuclei logs 'failed to write config file: permission denied'
# on every scan call, which pollutes output and slows startup.
NUCLEI_CONF_DIR="${REAL_HOME}/.config/nuclei"
if [[ ! -d "${NUCLEI_CONF_DIR}" ]]; then
    sudo mkdir -p "${NUCLEI_CONF_DIR}"
    ok "nuclei config directory created at ${NUCLEI_CONF_DIR}"
fi
if [[ "${REAL_USER}" != "root" ]]; then
    sudo chown -R "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.config/nuclei" 2>/dev/null \
        && ok "nuclei config dir ownership set to ${REAL_USER}" \
        || warn "could not chown nuclei config dir — run: sudo chown -R ${REAL_USER}:${REAL_USER} ${NUCLEI_CONF_DIR}"
fi

# wpscan vulnerability database — without this, wpscan --no-update fails with
# "No WPScan database found" on the first run. The --no-update flag in the
# legion.conf command prevents network calls during scans (correct for runtime),
# but the initial DB must exist.
if command -v wpscan &>/dev/null; then
    if wpscan --update 2>&1 | grep -q "Update completed"; then
        ok "wpscan database updated"
    else
        warn "wpscan --update failed — wpscan will error on first scan"
    fi
fi

# Patch eyewitness selenium_module.py for Selenium 4 compatibility.
# The Kali apt package still uses the Selenium 3 DesiredCapabilities API
# which was removed in Selenium 4.  The venv installs selenium>=4.9.0 so
# without this patch eyewitness fails with WebDriverError on every screenshot.
# Changes: DesiredCapabilities → options.accept_insecure_certs; remove
# service_log_path kwarg (also gone in Selenium 4).
EW_MOD="/usr/share/eyewitness/modules/selenium_module.py"
if [[ -f "$EW_MOD" ]]; then
    if grep -q "DesiredCapabilities" "$EW_MOD"; then
        info "Patching eyewitness for Selenium 4 API…"
        sudo python3 - "$EW_MOD" << 'PYEOF'
import sys, re
path = sys.argv[1]
src  = open(path).read()
# Remove deprecated import
src = re.sub(r'\n[ \t]*from selenium\.webdriver\.common\.desired_capabilities import DesiredCapabilities\n', '\n', src)
# Replace driver construction block — handles variations in whitespace/ordering
src = re.sub(
    r'capabilities\s*=\s*DesiredCapabilities\.FIREFOX\.copy\(\).*?'
    r'driver\s*=\s*webdriver\.Firefox\([^)]*service_log_path[^)]*\)',
    'options = Options()\n        options.add_argument("--headless")\n'
    '        options.accept_insecure_certs = True\n'
    '        profile.update_preferences()\n'
    '        driver = webdriver.Firefox(profile, options=options)',
    src, flags=re.DOTALL
)
# Fallback: remove service_log_path kwarg if still present
src = re.sub(r',\s*service_log_path\s*=\s*[^\)]+', '', src)
open(path, 'w').write(src)
print('ok')
PYEOF
        [[ $? -eq 0 ]] \
            && ok "eyewitness selenium_module.py patched for Selenium 4" \
            || warn "eyewitness patch failed — screenshots may not work"
    else
        ok "eyewitness already patched (no DesiredCapabilities found)"
    fi
else
    warn "eyewitness not found at ${EW_MOD} — skipping patch (install eyewitness first)"
fi

# Patch wig HTMLStripper for Python 3.13+ compatibility.
# Python 3.13 added a 'scripting' attribute to HTMLParser.__init__().
# wig's HTMLStripper calls self.reset() instead of super().__init__(),
# so self.scripting is never set → AttributeError on every page parse.
WIG_REQ="/usr/share/wig/classes/request2.py"
if [[ -f "$WIG_REQ" ]]; then
    if grep -q 'self\.reset()' "$WIG_REQ" 2>/dev/null; then
        sudo sed -i 's/self\.reset()/super().__init__()/' "$WIG_REQ" \
            && ok "wig patched for Python 3.13+ (HTMLStripper.__init__)" \
            || warn "wig patch failed"
    else
        ok "wig already patched (no self.reset() found)"
    fi
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

# Firefox clean state — the initial apt install of firefox-esr (running as
# root) leaves the browser in a broken state where it cannot create or load
# profiles.  The only proven fix is a full purge → delete user data → reinstall
# cycle.  This adds ~30s but guarantees Firefox works on first launch.
info "Ensuring Firefox is in a clean state…"
pkill -9 firefox 2>/dev/null || true
sleep 1
sudo apt-get purge -y firefox-esr 2>/dev/null || true
sudo rm -rf "${REAL_HOME}/.cache/mozilla" "${REAL_HOME}/.mozilla"
sudo apt-get install -y firefox-esr
if [[ "${REAL_USER}" != "root" ]]; then
    sudo chown -R "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.mozilla" "${REAL_HOME}/.cache" 2>/dev/null || true
    sudo chmod 700 "${REAL_HOME}/.mozilla" 2>/dev/null || true
fi
ok "Firefox purged and reinstalled clean"

# =============================================================================
# 8. Verification + auto-remediation (standalone — no pytest required)
# =============================================================================
step "8/10  Verification + auto-remediation"

cd "${SCRIPT_DIR}"
set +e

_V_PASS=0; _V_FAIL=0
_v_ok()   { ok   "$*"; _V_PASS=$((_V_PASS + 1)); }
_v_fail() { fail "$*"; _V_FAIL=$((_V_FAIL + 1)); }

# ── 8a. Required tool binaries ────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Required tool binaries ──────────────────────${NC}"

_VERIFY_BINS=(
    nmap masscan hping3
    feroxbuster gobuster ffuf nikto whatweb wafw00f wpscan nuclei
    hydra medusa
    netexec smbmap enum4linux-ng smbclient
    dnsrecon fierce
    sslscan sslyze testssl
    ssh-audit
    eyewitness searchsploit
    redis-cli mysql psql
    snmpwalk snmpcheck onesixtyone rpcinfo
    ldapsearch
    swaks smtp-user-enum finger nbtscan
    pd-httpx katana gau waybackurls nomore403 urlfinder kerbrute
    rdp-sec-check geckodriver
)

_BIN_MISSING=()
for _b in "${_VERIFY_BINS[@]}"; do
    if command -v "$_b" &>/dev/null; then
        _v_ok "  $_b"
    else
        _v_fail "  $_b — NOT FOUND"
        _BIN_MISSING+=("$_b")
    fi
done

# Auto-remediate missing binaries (up to 2 rounds)
if [[ ${#_BIN_MISSING[@]} -gt 0 ]]; then
    info "Attempting to install ${#_BIN_MISSING[@]} missing tool(s)…"
    for _b in "${_BIN_MISSING[@]}"; do
        _install_tool "$_b"
    done
    # Re-check
    _STILL_MISSING=()
    for _b in "${_BIN_MISSING[@]}"; do
        if command -v "$_b" &>/dev/null; then
            ok "  $_b — HEALED"
            _V_FAIL=$((_V_FAIL - 1)); _V_PASS=$((_V_PASS + 1))
        else
            _STILL_MISSING+=("$_b")
        fi
    done
    if [[ ${#_STILL_MISSING[@]} -gt 0 ]]; then
        warn "${#_STILL_MISSING[@]} tool(s) still missing after remediation:"
        for _b in "${_STILL_MISSING[@]}"; do warn "    $_b"; done
    fi
fi

# ── 8b. Python package imports (in venv) ──────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Python package imports (venv) ───────────────${NC}"

_PY_IMPORTS=(
    "flask"
    "werkzeug"
    "sqlalchemy"
    "requests"
    "anthropic"
    "openai"
    "google.auth"
    "selenium"
    "pyfiglet"
    "colorama"
    "termcolor"
    "neotermcolor"
)

for _mod in "${_PY_IMPORTS[@]}"; do
    if "${VENV_PY}" -c "import ${_mod}" 2>/dev/null; then
        _v_ok "  import $_mod"
    else
        _v_fail "  import $_mod — FAILED"
        # Try to fix
        _pip_name="$_mod"
        case "$_mod" in google.auth) _pip_name="google-auth" ;; esac
        sudo "${VENV_PIP}" install --root-user-action=ignore -q "$_pip_name" 2>/dev/null || true
        if "${VENV_PY}" -c "import ${_mod}" 2>/dev/null; then
            ok "  import $_mod — HEALED"
            _V_FAIL=$((_V_FAIL - 1)); _V_PASS=$((_V_PASS + 1))
        fi
    fi
done

# ── 8c. Legion core modules ──────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── LegionnAIre core modules ────────────────────${NC}"

_CORE_RESULT=$( cd "${SCRIPT_DIR}" && "${VENV_PY}" -c "
import sys; sys.path.insert(0, '.')
errors = []
for stmt, label in [
    ('from db.SqliteDbAdapter import Database',            'Database'),
    ('from controller.web_controller import WebController','WebController'),
    ('from app.web.routes import web_bp',                  'web_bp'),
    ('from app.settings import AppSettings',               'AppSettings'),
]:
    try: exec(stmt)
    except Exception as e: errors.append(f'{label}: {e}')
print('OK' if not errors else '|'.join(errors))
" 2>&1 )

if [[ "$_CORE_RESULT" == "OK" ]]; then
    _v_ok "  LegionnAIre core modules importable (Database, WebController, web_bp, AppSettings)"
else
    IFS='|' read -ra _errs <<< "$_CORE_RESULT"
    for _e in "${_errs[@]}"; do _v_fail "  $_e"; done
fi

# ── 8d. /opt tools ────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── /opt tools ─────────────────────────────────${NC}"

for _opt_check in "/opt/jexboss/jexboss.py:jexboss" "/opt/LeakSearch/LeakSearch.py:LeakSearch"; do
    _path="${_opt_check%%:*}"; _name="${_opt_check##*:}"
    if [[ -f "$_path" ]]; then
        _v_ok "  $_name at $_path"
    else
        _v_fail "  $_name not found at $_path"
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Verification summary ────────────────────────${NC}"
if [[ $_V_FAIL -eq 0 ]]; then
    ok "All ${_V_PASS} checks passed"
else
    warn "${_V_PASS} passed, ${_V_FAIL} failed"
    warn "LegionnAIre may still work but some tools will be missing from scans"
fi

set -e

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
# 10. Final environment health check + self-healing
# =============================================================================
step "10/10  Final environment health check"
set +e   # never abort — check and heal everything, then summarise

_CHECK_PASS=0
_CHECK_WARN=0
_CHECK_FAIL=0
_HEAL_COUNT=0

_chk_ok()   { ok   "$*"; (( _CHECK_PASS++ )) || true; }
_chk_warn() { warn "$*"; (( _CHECK_WARN++ )) || true; }
_chk_fail() { fail "$*"; (( _CHECK_FAIL++ )) || true; }
_healed()   { ok   "  HEALED: $*"; (( _HEAL_COUNT++ )) || true; (( _CHECK_FAIL-- )) || true; (( _CHECK_PASS++ )) || true; }

_in_docker() { [[ -f /.dockerenv ]]; }
_on_kali()   { [[ -f /etc/os-release ]] && grep -qi kali /etc/os-release; }

# ── Venv structure ────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Venv structure ──────────────────────────────${NC}"

# 1. Venv directory + python3 + pip — if missing, recreate the whole venv
if [[ ! -d "${LEGION_VENV}" ]] || [[ ! -f "${LEGION_VENV}/bin/python3" ]] || [[ ! -f "${LEGION_VENV}/bin/pip" ]]; then
    _chk_fail "Venv incomplete or missing at ${LEGION_VENV} — rebuilding…"
    sudo apt-get install -y python3-venv -q 2>/dev/null || true
    sudo rm -rf "${LEGION_VENV}"
    if sudo python3 -m venv "${LEGION_VENV}" 2>/dev/null; then
        sudo "${LEGION_VENV}/bin/pip" install --root-user-action=ignore -q --upgrade pip 2>/dev/null || true
        sudo "${LEGION_VENV}/bin/pip" install --root-user-action=ignore -q -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null \
            && _healed "Venv rebuilt and packages reinstalled" \
            || _chk_fail "Venv rebuild: pip install failed — run: sudo bash install.sh"
    else
        _chk_fail "Venv rebuild failed — run: sudo apt-get install python3-venv && sudo bash install.sh"
    fi
else
    _chk_ok "Venv directory, python3, pip all present"
fi

# 2. sys.prefix is the venv (not system python sneaking through)
if [[ -f "${VENV_PY}" ]]; then
    _venv_prefix=$("${VENV_PY}" -c "import sys; print(sys.prefix)" 2>/dev/null || true)
    if [[ "${_venv_prefix}" == "${LEGION_VENV}" ]]; then
        _chk_ok  "Venv python sys.prefix correct"
    else
        _chk_fail "Venv python sys.prefix is '${_venv_prefix}' — expected '${LEGION_VENV}'"
    fi
fi

# 3. Venv is isolated (system site-packages must NOT leak in)
if [[ -f "${LEGION_VENV}/pyvenv.cfg" ]]; then
    if grep -q "include-system-site-packages = false" "${LEGION_VENV}/pyvenv.cfg"; then
        _chk_ok "Venv is isolated (include-system-site-packages = false)"
    else
        _chk_fail "Venv is NOT isolated — rebuilding with isolation…"
        sudo rm -rf "${LEGION_VENV}"
        sudo python3 -m venv "${LEGION_VENV}" 2>/dev/null \
            && _healed "Venv rebuilt with isolation" \
            || _chk_fail "Venv rebuild failed"
    fi
fi

# 4. legion-python3 symlink
if [[ -L /usr/local/bin/legion-python3 ]]; then
    _link_target=$(readlink /usr/local/bin/legion-python3)
    if [[ "${_link_target}" == "${LEGION_VENV}/bin/python3" ]]; then
        _chk_ok  "legion-python3 symlink correct"
    else
        _chk_fail "legion-python3 symlink wrong target '${_link_target}' — fixing…"
        sudo ln -sf "${VENV_PY}" /usr/local/bin/legion-python3 \
            && _healed "legion-python3 symlink corrected" \
            || _chk_fail "Could not fix symlink"
    fi
else
    _chk_fail "legion-python3 symlink missing — creating…"
    sudo ln -sf "${VENV_PY}" /usr/local/bin/legion-python3 \
        && _healed "legion-python3 symlink created" \
        || _chk_fail "Could not create symlink"
fi

# ── Python packages ───────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Python packages (venv) ──────────────────────${NC}"

# 5. pip check — zero broken requirements
if [[ -f "${VENV_PIP}" ]]; then
    _pip_check_out=$("${VENV_PIP}" check 2>&1)
    if echo "${_pip_check_out}" | grep -q "No broken requirements"; then
        _chk_ok "pip check: No broken requirements in venv"
    else
        _chk_warn "pip check found issues — attempting reinstall of requirements…"
        sudo "${VENV_PIP}" install --root-user-action=ignore -q -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null || true
        _pip_check_out2=$("${VENV_PIP}" check 2>&1)
        if echo "${_pip_check_out2}" | grep -q "No broken requirements"; then
            _healed "pip check now clean after reinstall"
        else
            echo "${_pip_check_out2}" | while IFS= read -r ln; do [[ -n "$ln" ]] && warn "  ${ln}"; done
            _chk_warn "pip check still has issues — may be benign on Kali with system tools"
        fi
    fi
fi

# 6. Package imports — check each group, pip-install any that fail
# Format: "import_name|alt_import:pip_package_name"
# alt_import handles case where pip and apt install under different module names
# e.g. pyExploitDb (apt CamelCase) vs pyexploitdb (pip lowercase)
_can_import() {
    local mod
    for mod in $(echo "$1" | tr '|' ' '); do
        "${VENV_PY}" -c "import ${mod}" 2>/dev/null && return 0
    done
    return 1
}

_try_import_heal() {
    local pkg_spec="$1" pip_name="$2"
    if ! _can_import "${pkg_spec}"; then
        local display="${pkg_spec%%|*}"
        warn "  import ${display} failed — installing ${pip_name}…"
        sudo "${VENV_PIP}" install --root-user-action=ignore -q "${pip_name}" 2>/dev/null || true
        if _can_import "${pkg_spec}"; then
            _healed "import ${display} now works"
        else
            _chk_fail "import ${display} still failing after pip install ${pip_name}"
        fi
    fi
}

if [[ -f "${VENV_PY}" ]]; then
    # pkg_spec:pip_name — use | in pkg_spec for alternative import names
    _PKG_PAIRS=(
        "flask:flask"
        "werkzeug:werkzeug"
        "anthropic:anthropic"
        "google.auth:google-auth"
        "PyQt6.QtCore:PyQt6"
        "qasync:qasync"
        "pandas:pandas"
        "git:GitPython"
        "sqlalchemy:sqlalchemy"
        "six:six"
        "requests:requests"
        "urllib3:urllib3"
        "selenium:selenium"
        "pyfiglet:pyfiglet"
        "colorama:colorama"
        "termcolor:termcolor"
        "rich:rich"
        "neotermcolor:neotermcolor"
        "pyExploitDb|pyexploitdb:pyExploitDb"
        "pyShodan:pyShodan"
    )

    for _pkg_pair in "${_PKG_PAIRS[@]}"; do
        _spec="${_pkg_pair%%:*}"
        _pip="${_pkg_pair##*:}"
        _can_import "${_spec}" || _try_import_heal "${_spec}" "${_pip}"
    done

    # Final pass — report any still failing
    _still_fail=()
    for _pkg_pair in "${_PKG_PAIRS[@]}"; do
        _spec="${_pkg_pair%%:*}"
        _display="${_spec%%|*}"
        _can_import "${_spec}" || _still_fail+=("${_display}")
    done
    if [[ ${#_still_fail[@]} -eq 0 ]]; then
        _chk_ok "All required Python packages importable from venv"
    else
        for _p in "${_still_fail[@]}"; do
            _chk_fail "import ${_p} still failing — run: sudo /opt/legion-venv/bin/pip install ${_p}"
        done
    fi
fi

# 7. Legion core modules importable (using correct class names from the source)
if [[ -f "${VENV_PY}" && -f "${SCRIPT_DIR}/legion.py" ]]; then
    _legion_out=$( cd "${SCRIPT_DIR}" && "${VENV_PY}" -c "
import sys, traceback
sys.path.insert(0, '.')
errors = []
tests = [
    ('from db.SqliteDbAdapter import Database',           'db.SqliteDbAdapter.Database'),
    ('from controller.web_controller import WebController','controller.web_controller.WebController'),
    ('from app.web.routes import web_bp',                 'app.web.routes.web_bp'),
]
for stmt, label in tests:
    try:
        exec(stmt)
    except Exception as e:
        errors.append(f'{label}: {e}')
if errors:
    for e in errors: print(f'FAIL: {e}')
else:
    print('OK')
" 2>&1 )
    if [[ "${_legion_out}" == "OK" ]]; then
        _chk_ok "Legion core modules importable (Database, WebController, web_bp)"
    else
        # Attempt self-heal: reinstall requirements and retry once
        _chk_fail "Legion core module import failed:"
        echo "${_legion_out}" | while IFS= read -r ln; do [[ -n "$ln" ]] && fail "    ${ln}"; done
        info "  Attempting heal: reinstalling requirements into venv…"
        sudo "${VENV_PIP}" install --root-user-action=ignore -q -r "${SCRIPT_DIR}/requirements.txt" 2>/dev/null || true
        _legion_out2=$( cd "${SCRIPT_DIR}" && "${VENV_PY}" -c "
import sys
sys.path.insert(0, '.')
errors = []
for stmt in [
    'from db.SqliteDbAdapter import Database',
    'from controller.web_controller import WebController',
    'from app.web.routes import web_bp',
]:
    try: exec(stmt)
    except Exception as e: errors.append(str(e))
print('OK' if not errors else 'FAIL: ' + '; '.join(errors))
" 2>&1 )
        if [[ "${_legion_out2}" == "OK" ]]; then
            _healed "Legion core modules now importable after reinstall"
        else
            _chk_fail "Legion core modules still failing: ${_legion_out2}"
            _chk_fail "  Check: cd ${SCRIPT_DIR} && sudo /opt/legion-venv/bin/python3 -c \"import sys; sys.path.insert(0,'.'); from db.SqliteDbAdapter import Database\""
        fi
    fi
fi

# 8. Nuclei templates present and owned by real user
echo ""
echo -e "  ${BOLD}── Nuclei templates ────────────────────────────${NC}"
NUCLEI_CHK_DIR="${REAL_HOME}/.local/nuclei-templates"
if [[ -d "${NUCLEI_CHK_DIR}" ]]; then
    _tmpl_count=$(find "${NUCLEI_CHK_DIR}" -name "*.yaml" 2>/dev/null | wc -l)
    if [[ "${_tmpl_count}" -gt 1000 ]]; then
        _chk_ok "nuclei templates present (${_tmpl_count} yaml files)"
    else
        _chk_warn "nuclei template count low (${_tmpl_count}) — re-downloading…"
        HOME="${REAL_HOME}" nuclei -update-templates 2>/dev/null \
            && _healed "nuclei templates updated" \
            || _chk_warn "nuclei template download failed — run: nuclei -update-templates"
    fi
    # Fix ownership
    if [[ "${REAL_USER}" != "root" ]]; then
        _owner=$(stat -c '%U' "${NUCLEI_CHK_DIR}" 2>/dev/null || true)
        if [[ "${_owner}" != "${REAL_USER}" ]]; then
            _chk_fail "nuclei templates owned by '${_owner}' not '${REAL_USER}' — fixing…"
            sudo chown -R "${REAL_USER}:${REAL_USER}" "${NUCLEI_CHK_DIR}" \
                && _healed "nuclei templates ownership corrected to ${REAL_USER}" \
                || _chk_fail "chown failed — run: sudo chown -R ${REAL_USER}:${REAL_USER} ${NUCLEI_CHK_DIR}"
        else
            _chk_ok "nuclei templates owned by ${REAL_USER}"
        fi
    else
        _chk_ok "Running as root — nuclei templates ownership not applicable"
    fi
else
    _chk_fail "nuclei templates directory missing — downloading…"
    HOME="${REAL_HOME}" nuclei -update-templates 2>/dev/null \
        && _healed "nuclei templates downloaded" \
        || _chk_fail "nuclei template download failed — run: nuclei -update-templates"
fi

# ── Tools (Kali only) ─────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Tools ───────────────────────────────────────${NC}"

if _in_docker; then
    _chk_warn "Docker container detected — tool binary checks skipped"
elif _on_kali; then
    _CRITICAL_TOOLS=(
        nmap masscan hping3
        feroxbuster gobuster ffuf nikto whatweb wafw00f wpscan
        sqlmap sslyze sslscan
        netexec smbmap enum4linux-ng ldapsearch rpcclient smbclient
        hydra searchsploit eyewitness
        fierce kerbrute
        dnsrecon dnsenum nbtscan
        snmpwalk onesixtyone
        impacket-rpcdump
        ssh-audit
        redis-cli mysql psql
        dig finger
        nginx redis-server
    )
    _missing_tools=()
    # Check victim server packages via dpkg (binaries in /usr/sbin, not on PATH)
    for _pkg in mariadb-server samba snmpd xrdp; do
        if ! dpkg -l "$_pkg" 2>/dev/null | grep -q "^ii"; then
            warn "  Victim test server package not installed: $_pkg"
            warn "  Run: sudo apt-get install -y $_pkg"
        fi
    done

    for _t in "${_CRITICAL_TOOLS[@]}"; do
        command -v "${_t}" &>/dev/null || _missing_tools+=("${_t}")
    done
    if [[ ${#_missing_tools[@]} -gt 0 ]]; then
        info "  Missing tools — attempting self-heal via apt…"
        for _t in "${_missing_tools[@]}"; do
            _install_tool "${_t}"
        done
        # Re-check after heal attempt
        _still_missing=()
        for _t in "${_missing_tools[@]}"; do
            command -v "${_t}" &>/dev/null || _still_missing+=("${_t}")
        done
        if [[ ${#_still_missing[@]} -eq 0 ]]; then
            _healed "All missing tools installed"
        else
            for _t in "${_still_missing[@]}"; do
                _chk_fail "Tool still missing after heal attempt: ${_t}"
            done
        fi
    else
        _chk_ok "All critical tool binaries present in PATH"
    fi

    # rsh — virtual package on Kali, real package is rsh-redone-client
    if dpkg -l rsh-redone-client 2>/dev/null | grep -q '^ii' || dpkg -l rsh-client 2>/dev/null | grep -q '^ii'; then
        _chk_ok "rsh-client installed"
    else
        _chk_fail "rsh-client missing — installing rsh-redone-client…"
        sudo apt-get install -y rsh-redone-client 2>/dev/null \
            && _healed "rsh-redone-client installed" \
            || _chk_fail "rsh install failed — run: sudo apt-get install rsh-redone-client"
    fi

    # fierce — DNS brute-force tool required by fierce-dns SchedulerSettings entry
    if command -v fierce &>/dev/null; then
        _chk_ok "fierce present at $(command -v fierce)"
    else
        _chk_fail "fierce missing — installing…"
        sudo apt-get install -y fierce 2>/dev/null \
            && _healed "fierce installed" \
            || _chk_fail "fierce install failed — run: sudo apt-get install fierce"
    fi

    # seclists — wordlist package required by feroxbuster, ffuf, gobuster, fierce
    # Key files used in legion.conf commands:
    #   DNS:  /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt
    #   Web:  /usr/share/seclists/Discovery/Web-Content/big.txt
    #         /usr/share/seclists/Discovery/Web-Content/raft-medium-files.txt
    _SECLISTS_DNS="/usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt"
    _SECLISTS_WEB="/usr/share/seclists/Discovery/Web-Content/big.txt"
    if [[ -f "$_SECLISTS_DNS" && -f "$_SECLISTS_WEB" ]]; then
        _chk_ok "seclists present (DNS + Web wordlists confirmed)"
    else
        _chk_fail "seclists missing — fierce-dns and feroxbuster wordlists not found — installing…"
        sudo apt-get install -y seclists 2>/dev/null \
            && _healed "seclists installed" \
            || _chk_fail "seclists install failed — run: sudo apt-get install seclists"
    fi

    # testssl — package is testssl.sh, binary is testssl
    if command -v testssl &>/dev/null; then
        _chk_ok "testssl present"
    else
        _chk_fail "testssl missing (apt package is testssl.sh) — installing…"
        sudo apt-get install -y testssl.sh 2>/dev/null \
            && _healed "testssl.sh installed" \
            || _chk_fail "testssl.sh install failed — try: sudo apt-get install testssl.sh"
    fi

    # Perl Encoding::BER — required by rdp-sec-check.pl (fails silently without it)
    if perl -e 'use Encoding::BER' 2>/dev/null; then
        _chk_ok "Perl Encoding::BER module present (rdp-sec-check dependency)"
    else
        _chk_fail "Perl Encoding::BER missing — rdp-sec-check will fail — installing…"
        sudo apt-get install -y libencoding-ber-perl 2>/dev/null \
            && _healed "libencoding-ber-perl installed" \
            || {
                command -v cpanm &>/dev/null \
                    && sudo cpanm --quiet Encoding::BER 2>/dev/null \
                    || sudo cpan -i Encoding::BER 2>/dev/null
                perl -e 'use Encoding::BER' 2>/dev/null \
                    && _healed "Encoding::BER installed via CPAN" \
                    || _chk_fail "Encoding::BER install failed — run: sudo apt-get install libencoding-ber-perl"
            }
    fi

    # Go tools — heal individually
    _GO_TOOLS=( pd-httpx katana gau waybackurls nomore403 urlfinder )
    _missing_go=()
    for _t in "${_GO_TOOLS[@]}"; do
        command -v "${_t}" &>/dev/null || _missing_go+=("${_t}")
    done
    if [[ ${#_missing_go[@]} -gt 0 ]]; then
        info "  Missing Go tools — reinstalling…"
        for _t in "${_missing_go[@]}"; do _install_tool "${_t}"; done
        _still_missing_go=()
        for _t in "${_missing_go[@]}"; do
            command -v "${_t}" &>/dev/null || _still_missing_go+=("${_t}")
        done
        [[ ${#_still_missing_go[@]} -eq 0 ]] \
            && _healed "All Go tools installed" \
            || { for _t in "${_still_missing_go[@]}"; do _chk_warn "Go tool still missing: ${_t}"; done; }
    else
        _chk_ok "All Go tools present"
    fi

    # /opt scripts
    if [[ -f /opt/LeakSearch/LeakSearch.py ]]; then
        _chk_ok "/opt/LeakSearch/LeakSearch.py present"
    else
        _chk_fail "/opt/LeakSearch/LeakSearch.py missing — cloning…"
        sudo git clone --depth 1 https://github.com/JoelGMSec/LeakSearch.git /opt/LeakSearch 2>/dev/null \
            && _healed "LeakSearch cloned" \
            || _chk_fail "LeakSearch clone failed"
    fi
    if [[ -f /opt/jexboss/jexboss.py ]]; then
        _chk_ok "/opt/jexboss/jexboss.py present"
    else
        _chk_fail "/opt/jexboss/jexboss.py missing — cloning…"
        sudo git clone --depth 1 https://github.com/joaomatosf/jexboss.git /opt/jexboss 2>/dev/null \
            && _healed "jexboss cloned" \
            || _chk_fail "jexboss clone failed"
    fi
else
    _chk_warn "Not a Kali install — tool binary checks skipped"
fi

# ── Install log pattern analysis ──────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Install log analysis ────────────────────────${NC}"
echo    "     Log file: ${INSTALL_LOG}"
echo ""

_LOG_ISSUES=0
_log_check() {
    local description="$1" pattern="$2" fix="$3"
    if grep -qE "${pattern}" "${INSTALL_LOG}" 2>/dev/null; then
        _chk_warn "LOG: ${description}"
        warn      "     Fix: ${fix}"
        (( _LOG_ISSUES++ )) || true
    fi
}

_log_check \
    "ensurepip not available — python3-venv was missing during install" \
    "ensurepip is not available|No module named ensurepip" \
    "sudo apt-get install python3-venv && sudo bash install.sh"

_log_check \
    "pip dependency resolver conflict (mitmproxy/Kali tool version pins)" \
    "dependency resolver does not currently|ResolutionImpossible|Cannot install.*and.*because" \
    "Run: /opt/legion-venv/bin/pip check  (should be clean — system conflicts don't affect the venv)"

_log_check \
    "pip uninstall-no-record-file (Debian-managed package)" \
    "uninstall-no-record-file|no-record-file" \
    "Use venv (already done) — this error only appears on system-python installs"

_log_check \
    "No module named pytest — pytest missing from venv during step 8" \
    "No module named pytest" \
    "sudo /opt/legion-venv/bin/pip install pytest"

_log_check \
    "rsh-client install conflict" \
    "rsh-client.*referred by|referred by.*rsh-client" \
    "sudo apt-get install rsh-redone-client"

_log_check \
    "testssl package not found (correct name is testssl.sh)" \
    "Unable to locate package testssl[^.]" \
    "sudo apt-get install testssl.sh"

_log_check \
    "Go not installed — Go tools skipped" \
    "go: command not found|golang.*not installed" \
    "sudo apt-get install golang-go"

_log_check \
    "Address already in use — another Legion instance was on that port" \
    "Address already in use|OSError.*98.*address already" \
    "sudo pkill -f legion.py"

_log_check \
    "geckodriver not found — Selenium tests will fail" \
    "geckodriver.*not found|No such file.*geckodriver" \
    "Check: ls -la /usr/local/bin/geckodriver  (step 7 attempted install)"

_log_check \
    "Wrong git branch — should be flask-clean" \
    "WARNING.*not on flask-clean|wrong branch" \
    "sudo git checkout flask-clean && sudo bash install.sh"

_log_check \
    "process_matches wrong column — old bug (fixed in current code)" \
    "no such column: process_id.*process_matches|OperationalError.*process_id" \
    "sudo git pull  (update to latest flask-clean)"

[[ $_LOG_ISSUES -eq 0 ]] && _chk_ok "No known error patterns found in install log"

# ── Server verification (final check — after all healing is done) ─────────────
echo ""
echo -e "  ${BOLD}── LegionnAIre server verification ─────────────${NC}"

# Quick headless test: start server, verify /api/snapshot responds, kill it.
# The real launch (left running) happens after the summary.
_TEST_PORT=5199
_SRV_LOG=$(mktemp)
_SRV_PID=""

info "  Starting server on port ${_TEST_PORT}…"
cd "${SCRIPT_DIR}"
"${VENV_PY}" legion.py --web --port ${_TEST_PORT} --no-browser --no-prompt > "$_SRV_LOG" 2>&1 &
_SRV_PID=$!

_srv_ok=false
_spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
for _i in $(seq 1 30); do
    _sc=${_spin:$(( (_i - 1) % ${#_spin} )):1}
    printf "\r  %s  Waiting for server to respond… %ds" "$_sc" "$_i" >&2
    sleep 1
    if curl -sf "http://127.0.0.1:${_TEST_PORT}/api/snapshot" -o /dev/null 2>/dev/null; then
        _srv_ok=true
        break
    fi
    if ! kill -0 "$_SRV_PID" 2>/dev/null; then
        break
    fi
done
printf "\r%-60s\r" "" >&2

if $_srv_ok; then
    _chk_ok "Server started and /api/snapshot responded"
else
    _chk_fail "Server failed to start"
    tail -30 "$_SRV_LOG" | while IFS= read -r _ln; do [[ -n "$_ln" ]] && warn "    $_ln"; done
fi

# Kill the test server
if [[ -n "$_SRV_PID" ]] && kill -0 "$_SRV_PID" 2>/dev/null; then
    kill "$_SRV_PID" 2>/dev/null
    wait "$_SRV_PID" 2>/dev/null || true
fi
rm -f "$_SRV_LOG"

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}── Health check summary ────────────────────────${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} Passed   : ${_CHECK_PASS}"
[[ $_HEAL_COUNT -gt 0 ]] && echo -e "  ${GREEN}⚕${NC} Healed   : ${_HEAL_COUNT}"
[[ $_CHECK_WARN -gt 0 ]] && echo -e "  ${YELLOW}!${NC} Warnings : ${_CHECK_WARN}"
[[ $_CHECK_FAIL -gt 0 ]] && echo -e "  ${RED}✗${NC} Failed   : ${_CHECK_FAIL}"
echo ""
if [[ $_CHECK_FAIL -eq 0 && $_CHECK_WARN -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}Environment is fully healthy.${NC}"
elif [[ $_CHECK_FAIL -eq 0 ]]; then
    echo -e "  ${YELLOW}${BOLD}Environment is functional with minor warnings.${NC}"
else
    echo -e "  ${RED}${BOLD}${_CHECK_FAIL} check(s) failed — review items above before running Legion.${NC}"
fi
echo ""
echo -e "  Full install log saved to: ${INSTALL_LOG}"

set -e

# =============================================================================
# Done — launch LegionnAIre
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║      LegionnAIre installation complete         ║${NC}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Python venv:${NC}  ${LEGION_VENV}"
echo -e "  ${BOLD}Symlink:${NC}      /usr/local/bin/legion-python3"
echo -e "  ${BOLD}Install log:${NC}  ${INSTALL_LOG}"
echo ""
echo -e "  ${BOLD}Next time, start with:${NC}"
echo    "    sudo legion-python3 legion.py --web"
echo    "    sudo legion-python3 legion.py --web --port 8080"
echo    "    sudo legion-python3 legion.py --web --no-browser"
echo ""

# Detect display availability
_HAS_DISPLAY=false
if [[ -n "${DISPLAY:-}" ]]; then
    xdpyinfo &>/dev/null 2>&1 && _HAS_DISPLAY=true
fi

# Launch LegionnAIre for real — left running so the user sees it immediately
cd "${SCRIPT_DIR}"
if $_HAS_DISPLAY; then
    echo -e "  ${BOLD}${GREEN}Starting LegionnAIre with Firefox…${NC}"
    echo ""
    "${VENV_PY}" legion.py --web --no-prompt &
    _LAUNCH_PID=$!
    # Wait for server to be ready before exiting the script
    for _i in $(seq 1 15); do
        sleep 1
        curl -sf "http://127.0.0.1:5000/api/snapshot" -o /dev/null 2>/dev/null && break
    done
    echo -e "  ${GREEN}✓${NC}  LegionnAIre is running at ${BOLD}http://127.0.0.1:5000${NC}"
    echo -e "  ${GREEN}✓${NC}  Firefox should be opening now"
    echo ""
    echo -e "  To stop:  ${BOLD}sudo pkill -f legion.py${NC}"
    echo ""
else
    echo -e "  ${BOLD}${YELLOW}No display detected — starting in headless mode.${NC}"
    echo ""
    "${VENV_PY}" legion.py --web --no-browser --no-prompt &
    _LAUNCH_PID=$!
    for _i in $(seq 1 15); do
        sleep 1
        curl -sf "http://127.0.0.1:5000/api/snapshot" -o /dev/null 2>/dev/null && break
    done
    echo -e "  ${GREEN}✓${NC}  LegionnAIre is running at ${BOLD}http://127.0.0.1:5000${NC}"
    echo -e "  ${YELLOW}!${NC}  Open that URL in your browser (Windows browser for WSL)"
    echo ""
    echo -e "  To stop:  ${BOLD}sudo pkill -f legion.py${NC}"
    echo ""
fi
