#!/usr/bin/env bash
# Legion tool installer — installs tools missing from this Kali system.
# Run as root: sudo bash install_tools.sh
#
# Already installed on Kali (no action needed):
#   nmap, masscan, feroxbuster, gobuster, ffuf, nuclei, testssl,
#   netexec, smbmap, enum4linux-ng, ldapdomaindump, evil-winrm,
#   redis-cli, amass, dnsrecon, dnsenum, wpscan, nikto, whatweb,
#   wafw00f, sslyze, sslscan, sqlmap, seclists, wig,
#   impacket-*, hydra, nbtscan, onesixtyone, snmpwalk,
#   ldapsearch, swaks, davtest, joomscan, ike-scan, finger,
#   hping3, eyewitness, bloodhound-python, searchsploit (apt)
#
# Installed by this script:
#   ssh-audit     — SSH configuration auditor (apt)
#   kerbrute      — Kerberos user enum/brute (GitHub binary)
#   rdp-sec-check — RDP security scanner (apt or GitHub Perl)
#   pd-httpx      — ProjectDiscovery httpx tech-detect probe (Go)
#   katana        — ProjectDiscovery web crawler (Go)
#   gau           — GetAllURLs passive URL collection (Go)
#   waybackurls   — Wayback Machine URL fetcher (Go)
#   nomore403     — 403 bypass checker (Go)
#   jexboss       — JBoss/Java app server scanner (/opt/jexboss, Python)
#   LeakSearch    — Credential leak search (/opt/LeakSearch, Python)
#   urlfinder     — URL extraction from JS/HTML (Go)
#   nuclei templates — Required before nuclei can scan
#   neotermcolor  — Python dep for LeakSearch (pip)
#   mongosh       — MongoDB shell (optional, for mongo terminal actions)
#
# Not added (unavailable / deprecated):
#   arachni     — Officially discontinued 2016; use nuclei instead
#   dirdar      — Superseded by nomore403 and nuclei fuzzing
#   servicelens — Sn1per-internal tool, no standalone release

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
skip() { echo -e "${YELLOW}[SKIP]${NC} $*"; }
warn() { echo -e "${RED}[WARN]${NC} $*"; }
info() { echo "       --> $*"; }

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo bash $0"
    exit 1
fi

# Resolve the real (non-root) user and their home directory.
# When run via 'sudo bash install_tools.sh', SUDO_USER is the invoking user.
# This is needed so nuclei templates and config dirs land in the right home.
REAL_USER="${SUDO_USER:-root}"
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6 2>/dev/null || echo "${HOME}")

echo "=== Legion Tool Installer ==="
echo ""

# ---------------------------------------------------------------------------
# ssh-audit — SSH server/client configuration auditor (apt)
# ---------------------------------------------------------------------------
if command -v ssh-audit &>/dev/null; then
    skip "ssh-audit already installed"
else
    info "apt install ssh-audit..."
    apt-get install -y ssh-audit
    ok "ssh-audit installed"
fi

# ---------------------------------------------------------------------------
# kerbrute — Kerberos user enumeration / brute-force (GitHub binary)
# Not in Kali apt repos; download the pre-built Go binary from ropnop/kerbrute.
# ---------------------------------------------------------------------------
KERBRUTE_BIN=/usr/local/bin/kerbrute
if command -v kerbrute &>/dev/null; then
    skip "kerbrute already installed at $(command -v kerbrute)"
else
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  KERB_FILE="kerbrute_linux_amd64" ;;
        aarch64) KERB_FILE="kerbrute_linux_arm64" ;;
        *)        warn "Unknown arch $ARCH — cannot auto-install kerbrute"; KERB_FILE="" ;;
    esac

    if [[ -n "$KERB_FILE" ]]; then
        KERB_URL="https://github.com/ropnop/kerbrute/releases/latest/download/${KERB_FILE}"
        info "Downloading kerbrute from GitHub..."
        if curl -fsSL "$KERB_URL" -o "$KERBRUTE_BIN" 2>/dev/null; then
            chmod +x "$KERBRUTE_BIN"
            ok "kerbrute installed at $KERBRUTE_BIN"
        else
            warn "Download failed — install manually:"
            warn "  https://github.com/ropnop/kerbrute/releases/latest"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# rdp-sec-check — RDP security scanner
# Try apt first (available in newer Kali). Fall back to cloning from
# CiscoCXSecurity and creating a wrapper at /usr/local/bin/rdp-sec-check.
# ---------------------------------------------------------------------------
if command -v rdp-sec-check &>/dev/null; then
    skip "rdp-sec-check already installed"
else
    info "Trying apt install rdp-sec-check..."
    if apt-get install -y rdp-sec-check 2>/dev/null; then
        ok "rdp-sec-check installed via apt"
    else
        info "Not in apt — cloning CiscoCXSecurity/rdp-sec-check..."
        RDP_DIR=/opt/rdp-sec-check
        if [[ ! -d "$RDP_DIR" ]]; then
            if git clone --depth 1 https://github.com/CiscoCXSecurity/rdp-sec-check.git "$RDP_DIR" 2>/dev/null; then
                # Wrapper so 'rdp-sec-check HOST:PORT' works from anywhere
                cat > /usr/local/bin/rdp-sec-check << 'WRAPPER'
#!/bin/bash
exec perl /opt/rdp-sec-check/rdp-sec-check.pl "$@"
WRAPPER
                chmod +x /usr/local/bin/rdp-sec-check
                ok "rdp-sec-check installed at /usr/local/bin/rdp-sec-check"
            else
                warn "git clone failed — check network."
                warn "Keeping existing: perl ./scripts/rdp-sec-check.pl in legion.conf"
            fi
        fi
    fi
fi

# Perl dependency: Encoding::BER — required by rdp-sec-check.pl at runtime.
# Without it rdp-sec-check fails: "Can't locate Encoding/BER.pm in @INC".
# Try apt (libencoding-ber-perl) first; fall back to CPAN.
if perl -e 'use Encoding::BER' 2>/dev/null; then
    skip "Perl Encoding::BER already installed"
else
    info "Installing Perl Encoding::BER (rdp-sec-check dependency)..."
    if apt-get install -y libencoding-ber-perl 2>/dev/null; then
        ok "libencoding-ber-perl installed via apt"
    elif command -v cpanm &>/dev/null; then
        cpanm --quiet Encoding::BER 2>/dev/null \
            && ok "Encoding::BER installed via cpanm" \
            || warn "cpanm install failed — try: sudo apt-get install libencoding-ber-perl"
    else
        cpan -i Encoding::BER 2>/dev/null \
            && ok "Encoding::BER installed via cpan" \
            || warn "CPAN install failed — try: sudo apt-get install libencoding-ber-perl"
    fi
fi

# ---------------------------------------------------------------------------
# nuclei templates — required before nuclei can scan for anything.
# The -duc flag in legion.conf commands suppresses per-scan update checks,
# but templates must be present. They install to ~/.local/nuclei-templates.
# ---------------------------------------------------------------------------
# Use the real user's home so templates land in /home/kali/.local not /root/.local
# when this script is invoked via sudo. legion.conf uses -t REAL_HOME/.local/nuclei-templates/http
NUCLEI_TEMPLATES_DIR="${REAL_HOME}/.local/nuclei-templates"
if [[ -d "$NUCLEI_TEMPLATES_DIR" ]] && [[ -n "$(ls -A "$NUCLEI_TEMPLATES_DIR" 2>/dev/null)" ]]; then
    skip "nuclei templates already present at $NUCLEI_TEMPLATES_DIR"
else
    info "Downloading nuclei templates (this may take a moment)..."
    HOME="${REAL_HOME}" nuclei -update-templates 2>&1 | tee /tmp/nuclei-update.log | grep -qE "Successfully|up.to.date|No new" || true
    if [[ -d "$NUCLEI_TEMPLATES_DIR" ]] && [[ -n "$(ls -A "$NUCLEI_TEMPLATES_DIR" 2>/dev/null)" ]]; then
        ok "nuclei templates ready at $NUCLEI_TEMPLATES_DIR"
        [[ "${REAL_USER}" != "root" ]] && chown -R "${REAL_USER}:${REAL_USER}" "$NUCLEI_TEMPLATES_DIR" 2>/dev/null || true
    else
        warn "nuclei template download may have failed — check: nuclei -update-templates"
    fi
fi

# Create nuclei config directory so nuclei can write its .templates-config.json
# without 'permission denied' when Legion runs as root (sudo legion-python3 legion.py)
NUCLEI_CONF="${REAL_HOME}/.config/nuclei"
if [[ ! -d "$NUCLEI_CONF" ]]; then
    mkdir -p "$NUCLEI_CONF"
    ok "nuclei config directory created at $NUCLEI_CONF"
fi
[[ "${REAL_USER}" != "root" ]] && chown -R "${REAL_USER}:${REAL_USER}" "$NUCLEI_CONF" 2>/dev/null || true

# ---------------------------------------------------------------------------
# mongosh — MongoDB shell (optional; needed for mongo terminal actions)
# ---------------------------------------------------------------------------
if command -v mongosh &>/dev/null || command -v mongo &>/dev/null; then
    skip "mongo shell already installed"
else
    info "Trying apt install mongodb-mongosh..."
    if apt-get install -y mongodb-mongosh 2>/dev/null || apt-get install -y mongodb-org-shell 2>/dev/null; then
        ok "mongosh installed"
    else
        warn "mongosh not in apt repos — skipping (optional, only needed for mongo terminal actions)"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Summary ==="
NEWLY_MISSING=()
for tool in ssh-audit kerbrute rdp-sec-check nuclei; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool: $(command -v $tool)"
    else
        warn "$tool: NOT installed"
        NEWLY_MISSING+=("$tool")
    fi
done

# ---------------------------------------------------------------------------
# Go-based tools — ProjectDiscovery httpx, katana, gau, waybackurls, nomore403
# These are installed via 'go install' then copied to /usr/local/bin.
# pd-httpx is used instead of 'httpx' to avoid overwriting /usr/bin/httpx
# (the Python kaeferjaeger httpx already present on Kali).
# ---------------------------------------------------------------------------
_go_install_and_link() {
    local pkg="$1" bin_name="$2" dest_name="${3:-$2}"
    if command -v "$dest_name" &>/dev/null; then
        skip "$dest_name already at $(command -v "$dest_name")"
        return
    fi
    info "go install $pkg ..."
    # Install to a temp GOPATH under /tmp so we don't need write access to system dirs during build
    local tmp_gopath; tmp_gopath=$(mktemp -d)
    if GOPATH="$tmp_gopath" HOME=/root go install "$pkg" 2>/dev/null; then
        if [[ -f "$tmp_gopath/bin/$bin_name" ]]; then
            cp "$tmp_gopath/bin/$bin_name" "/usr/local/bin/$dest_name"
            chmod +x "/usr/local/bin/$dest_name"
            ok "$dest_name installed at /usr/local/bin/$dest_name"
        else
            warn "$bin_name binary not found after go install"
            NEWLY_MISSING+=("$dest_name")
        fi
    else
        warn "go install failed for $pkg"
        NEWLY_MISSING+=("$dest_name")
    fi
    rm -rf "$tmp_gopath"
}

_go_install_and_link "github.com/projectdiscovery/httpx/cmd/httpx@latest" "httpx" "pd-httpx"
_go_install_and_link "github.com/projectdiscovery/katana/cmd/katana@latest" "katana" "katana"
_go_install_and_link "github.com/lc/gau/v2/cmd/gau@latest"                "gau"    "gau"
_go_install_and_link "github.com/tomnomnom/waybackurls@latest"             "waybackurls" "waybackurls"
_go_install_and_link "github.com/devploit/nomore403@latest"                "nomore403"   "nomore403"

# ---------------------------------------------------------------------------
# jexboss — JBoss / Java app server vulnerability scanner (Python, GitHub)
# ---------------------------------------------------------------------------
JEXBOSS_DIR=/opt/jexboss
if [[ -f "$JEXBOSS_DIR/jexboss.py" ]]; then
    skip "jexboss already at $JEXBOSS_DIR"
else
    info "Cloning jexboss from GitHub..."
    if git clone --depth 1 https://github.com/joaomatosf/jexboss.git "$JEXBOSS_DIR" 2>/dev/null; then
        if [[ -f "$JEXBOSS_DIR/requires.txt" ]]; then
            pip3 install --break-system-packages -r "$JEXBOSS_DIR/requires.txt" -q 2>/dev/null || true
        fi
        ok "jexboss installed at $JEXBOSS_DIR/jexboss.py"
    else
        warn "jexboss clone failed — install manually:"
        warn "  git clone https://github.com/joaomatosf/jexboss.git /opt/jexboss"
        NEWLY_MISSING+=("jexboss")
    fi
fi

# ---------------------------------------------------------------------------
# LeakSearch — Credential leak search (Python, GitHub)
# ---------------------------------------------------------------------------
LEAKSEARCH_DIR=/opt/LeakSearch
if [[ -f "$LEAKSEARCH_DIR/LeakSearch.py" ]]; then
    skip "LeakSearch already at $LEAKSEARCH_DIR"
else
    info "Cloning LeakSearch from GitHub..."
    if git clone --depth 1 https://github.com/JoelGMSec/LeakSearch.git "$LEAKSEARCH_DIR" 2>/dev/null; then
        if [[ -f "$LEAKSEARCH_DIR/requirements.txt" ]]; then
            pip3 install --break-system-packages -r "$LEAKSEARCH_DIR/requirements.txt" -q 2>/dev/null || true
        fi
        # neotermcolor is a hard dependency not always in requirements.txt
        pip3 install --break-system-packages neotermcolor -q 2>/dev/null || true
        ok "LeakSearch installed at $LEAKSEARCH_DIR/LeakSearch.py"
    else
        warn "LeakSearch clone failed — install manually:"
        warn "  git clone https://github.com/JoelGMSec/LeakSearch.git /opt/LeakSearch"
        NEWLY_MISSING+=("LeakSearch")
    fi
fi

# ---------------------------------------------------------------------------
# wig — WebApp Information Gatherer (apt, already on Kali by default)
# NOTE: wig is BROKEN on Python 3.13+ due to html.parser API change.
# HTMLParser gained a 'scripting' attribute in 3.12; wig's HTMLStripper
# subclass does not set it → AttributeError on every page fetch.
# wig is therefore NOT in SchedulerSettings (auto-run) but remains in
# PortActions so it can be run manually on Python 3.12 systems.
# ---------------------------------------------------------------------------
if command -v wig &>/dev/null; then
    skip "wig already installed at $(command -v wig)"
    python3 -c "import html.parser; p=html.parser.HTMLParser(); getattr(p,'scripting',None)" 2>/dev/null \
        || warn "wig is installed but broken on Python 3.13+ (html.parser API change) — disabled in SchedulerSettings"
else
    info "apt install wig..."
    if apt-get install -y wig 2>/dev/null; then
        ok "wig installed (note: disabled in SchedulerSettings on Python 3.13+)"
    else
        warn "wig not available via apt — try: pip3 install --break-system-packages wig"
        NEWLY_MISSING+=("wig")
    fi
fi

# ---------------------------------------------------------------------------
# urlfinder — URL extractor from HTTP responses (used in Tools tab)
# ---------------------------------------------------------------------------
_go_install_and_link "github.com/projectdiscovery/urlfinder/cmd/urlfinder@latest" "urlfinder" "urlfinder"

# ---------------------------------------------------------------------------
# neotermcolor — Python dep for LeakSearch (always ensure it is installed)
# ---------------------------------------------------------------------------
if python3 -c "import neotermcolor" 2>/dev/null; then
    skip "neotermcolor already installed"
else
    info "pip3 install neotermcolor..."
    pip3 install --break-system-packages neotermcolor -q 2>/dev/null && ok "neotermcolor installed" || warn "neotermcolor install failed"
fi

# ---------------------------------------------------------------------------
# Python requirements (flask, sqlalchemy, anthropic, etc.)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
    info "pip3 install -r requirements.txt..."
    pip3 install --break-system-packages -r "$SCRIPT_DIR/requirements.txt" -q 2>/dev/null && ok "Python requirements installed" || warn "Some Python requirements may have failed — check pip output"
fi

echo ""
echo "Pre-existing tools confirmed present:"
ALL_TOOLS=(nmap masscan feroxbuster gobuster ffuf nuclei testssl netexec smbmap
           enum4linux-ng ldapdomaindump evil-winrm redis-cli amass dnsrecon
           dnsenum wpscan nikto whatweb wafw00f sslyze sslscan sqlmap wig
           hping3 eyewitness searchsploit hydra nbtscan onesixtyone snmpwalk
           swaks davtest joomscan ike-scan finger ldapsearch)
for tool in "${ALL_TOOLS[@]}"; do
    if command -v "$tool" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $tool"
    else
        echo -e "  ${RED}✗${NC} $tool — MISSING (unexpected)"
    fi
done

echo ""
echo "New tools installed by this script:"
NEW_TOOLS=(ssh-audit kerbrute rdp-sec-check pd-httpx katana gau waybackurls nomore403 urlfinder)
for tool in "${NEW_TOOLS[@]}"; do
    if command -v "$tool" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $tool"
    else
        echo -e "  ${RED}✗${NC} $tool — not found in PATH"
    fi
done
[[ -f /opt/jexboss/jexboss.py ]]       && echo -e "  ${GREEN}✓${NC} jexboss (/opt/jexboss/jexboss.py)"         || echo -e "  ${RED}✗${NC} jexboss — missing"
[[ -f /opt/LeakSearch/LeakSearch.py ]] && echo -e "  ${GREEN}✓${NC} LeakSearch (/opt/LeakSearch/LeakSearch.py)" || echo -e "  ${RED}✗${NC} LeakSearch — missing"
python3 -c "import neotermcolor" 2>/dev/null && echo -e "  ${GREEN}✓${NC} neotermcolor (Python)" || echo -e "  ${RED}✗${NC} neotermcolor — pip3 install --break-system-packages neotermcolor"

if [[ ${#NEWLY_MISSING[@]} -gt 0 ]]; then
    echo ""
    warn "Some tools could not be installed: ${NEWLY_MISSING[*]}"
    warn "Install them manually before using the corresponding legion menu entries."
fi

echo ""
echo "Done."
