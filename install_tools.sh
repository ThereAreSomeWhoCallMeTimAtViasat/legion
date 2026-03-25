#!/usr/bin/env bash
# Legion tool installer — installs tools missing from this Kali system.
# Run as root: sudo bash install_tools.sh
#
# Already installed (no action needed):
#   feroxbuster, gobuster, ffuf, nuclei, testssl, netexec, smbmap,
#   enum4linux-ng, ldapdomaindump, evil-winrm, redis-cli, masscan,
#   amass, dnsrecon, dnsenum, wpscan, nikto, whatweb, wafw00f,
#   sslyze, sslscan, sqlmap, seclists

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
                # Install the one CPAN dep (Encoding::BER) if cpanm is available
                if command -v cpanm &>/dev/null; then
                    info "Installing Perl dependency Encoding::BER..."
                    cpanm --quiet Encoding::BER 2>/dev/null || true
                fi
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

# ---------------------------------------------------------------------------
# nuclei templates — required before nuclei can scan for anything.
# The -duc flag in legion.conf commands suppresses per-scan update checks,
# but templates must be present. They install to ~/.local/nuclei-templates.
# ---------------------------------------------------------------------------
NUCLEI_TEMPLATES_DIR="$HOME/.local/nuclei-templates"
if [[ -d "$NUCLEI_TEMPLATES_DIR" ]] && [[ -n "$(ls -A "$NUCLEI_TEMPLATES_DIR" 2>/dev/null)" ]]; then
    skip "nuclei templates already present at $NUCLEI_TEMPLATES_DIR"
else
    info "Downloading nuclei templates (this may take a moment)..."
    if nuclei -update-templates 2>&1 | tee /tmp/nuclei-update.log | grep -qE "Successfully installed|up.to.date|No new updates"; then
        ok "nuclei templates ready at $NUCLEI_TEMPLATES_DIR"
    elif [[ -d "$NUCLEI_TEMPLATES_DIR" ]]; then
        ok "nuclei templates present at $NUCLEI_TEMPLATES_DIR"
    else
        warn "nuclei template download may have failed — check: nuclei -update-templates"
    fi
fi

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

echo ""
echo "Pre-existing tools confirmed present:"
ALL_TOOLS=(feroxbuster gobuster ffuf nuclei testssl netexec smbmap
           enum4linux-ng ldapdomaindump evil-winrm redis-cli masscan
           amass dnsrecon dnsenum wpscan nikto whatweb wafw00f
           sslyze sslscan sqlmap)
for tool in "${ALL_TOOLS[@]}"; do
    if command -v "$tool" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $tool"
    else
        echo -e "  ${RED}✗${NC} $tool — MISSING (unexpected)"
    fi
done

if [[ ${#NEWLY_MISSING[@]} -gt 0 ]]; then
    echo ""
    warn "Some tools could not be installed: ${NEWLY_MISSING[*]}"
    warn "Install them manually before using the corresponding legion menu entries."
fi

echo ""
echo "Done."
