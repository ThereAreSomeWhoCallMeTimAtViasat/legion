#!/usr/bin/env bash
# =============================================================================
# Legion — Full Automated Installer
# =============================================================================
# Installs everything needed to run Legion in web mode (--web) on Kali Linux
# or Ubuntu 22.04+.  Safe to run more than once — all steps are idempotent.
#
# Usage:
#   sudo bash install.sh              # install everything
#   sudo bash install.sh --no-tools   # skip system tools (Python only)
#   sudo bash install.sh --no-ai      # skip Vertex AI setup prompt
#
# What this script does:
#   1. Checks prerequisites (OS, Python version, sudo)
#   2. Installs Python runtime dependencies (requirements.txt)
#   3. Installs system security tools (apt + Go + GitHub + /opt)
#   4. Installs geckodriver for Selenium tests and screenshooter
#   5. Creates the Firefox profile directory used by Legion --web
#   6. Verifies the installation with the built-in test suite
#   7. Optionally walks through Vertex AI setup for the AI tab
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; }
warn() { echo -e "  ${YELLOW}!${NC}  $*"; }
info() { echo -e "  ${BLUE}→${NC}  $*"; }
step() { echo -e "\n${BOLD}${BLUE}══ $* ${NC}"; }
die()  { echo -e "\n${RED}ERROR: $*${NC}" >&2; exit 1; }

# ── Argument parsing ──────────────────────────────────────────────────────────
SKIP_TOOLS=false
SKIP_AI=false
for arg in "$@"; do
    case "$arg" in
        --no-tools) SKIP_TOOLS=true ;;
        --no-ai)    SKIP_AI=true ;;
        -h|--help)
            echo "Usage: sudo bash install.sh [--no-tools] [--no-ai]"
            echo "  --no-tools   skip system security tools (install Python only)"
            echo "  --no-ai      skip Vertex AI setup prompt"
            exit 0
            ;;
    esac
done

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash $0"

# Detect the non-root user who invoked sudo (for Firefox profile ownership)
SUDO_USER_HOME="${HOME}"
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    SUDO_USER_HOME=$(getent passwd "${SUDO_USER}" | cut -d: -f6)
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}Legion — Automated Installer${NC}"
echo "Working directory: ${SCRIPT_DIR}"
echo ""

# =============================================================================
# Step 1 — Prerequisites
# =============================================================================
step "Prerequisites"

# OS check
if grep -qi kali /etc/os-release 2>/dev/null; then
    ok "OS: Kali Linux"
elif grep -qi ubuntu /etc/os-release 2>/dev/null; then
    ok "OS: Ubuntu"
    warn "Kali is recommended — many tools may not be in apt on Ubuntu"
else
    warn "OS not recognised — continuing anyway, but YMMV"
fi

# Python version
PY=$(python3 --version 2>/dev/null | grep -oP '[\d.]+' | head -1)
PY_MAJOR=$(echo "$PY" | cut -d. -f1)
PY_MINOR=$(echo "$PY" | cut -d. -f2)
if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]]; then
    ok "Python $PY"
else
    die "Python 3.10+ required (found $PY). Install it first."
fi

# pip
python3 -m pip --version &>/dev/null || die "pip not found — install python3-pip first"
ok "pip available"

# Go (for Go-based tools)
if command -v go &>/dev/null; then
    ok "Go $(go version | grep -oP 'go[\d.]+' | head -1)"
else
    warn "Go not found — Go-based tools will be skipped (pd-httpx, katana, gau, etc.)"
    warn "Install Go: sudo apt-get install golang-go"
fi

# =============================================================================
# Step 2 — Python packages
# =============================================================================
step "Python packages  (requirements.txt)"

cd "${SCRIPT_DIR}"
if [[ ! -f requirements.txt ]]; then
    die "requirements.txt not found in ${SCRIPT_DIR}"
fi

info "Installing all Python dependencies (Flask + Qt6 + shared)…"
if python3 -m pip install --break-system-packages -r requirements.txt -q; then
    ok "requirements.txt installed"
else
    fail "pip install failed — check the output above"
    exit 1
fi

# Verify critical imports work
info "Verifying critical imports…"
IMPORT_ERRORS=()
for pkg in flask sqlalchemy PyQt6.QtCore anthropic; do
    if python3 -c "import ${pkg}" 2>/dev/null; then
        ok "  import ${pkg}"
    else
        IMPORT_ERRORS+=("${pkg}")
        fail "  import ${pkg} — FAILED"
    fi
done
[[ ${#IMPORT_ERRORS[@]} -gt 0 ]] && warn "Some imports failed — the app may still run in web mode"

# =============================================================================
# Step 3 — System security tools
# =============================================================================
if $SKIP_TOOLS; then
    warn "Skipping system tools (--no-tools specified)"
else
    step "System security tools  (install_tools.sh)"
    if [[ -f "${SCRIPT_DIR}/install_tools.sh" ]]; then
        bash "${SCRIPT_DIR}/install_tools.sh"
    else
        warn "install_tools.sh not found — skipping tool installation"
    fi
fi

# =============================================================================
# Step 4 — geckodriver (screenshooter + Selenium tests)
# =============================================================================
step "geckodriver"

if command -v geckodriver &>/dev/null; then
    ok "geckodriver already at $(command -v geckodriver)  ($(geckodriver --version 2>&1 | head -1))"
else
    info "Installing geckodriver…"
    GECKODRIVER_URL=""
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  GECKODRIVER_URL="https://github.com/mozilla/geckodriver/releases/latest/download/geckodriver-v0.35.0-linux64.tar.gz" ;;
        aarch64) GECKODRIVER_URL="https://github.com/mozilla/geckodriver/releases/latest/download/geckodriver-v0.35.0-linux-aarch64.tar.gz" ;;
        *)       warn "Unknown arch $ARCH — download geckodriver manually from https://github.com/mozilla/geckodriver/releases" ;;
    esac

    if [[ -n "$GECKODRIVER_URL" ]]; then
        TMP_DIR=$(mktemp -d)
        if curl -fsSL "$GECKODRIVER_URL" | tar xz -C "$TMP_DIR" 2>/dev/null; then
            mv "$TMP_DIR/geckodriver" /usr/local/bin/geckodriver
            chmod +x /usr/local/bin/geckodriver
            rm -rf "$TMP_DIR"
            ok "geckodriver installed at /usr/local/bin/geckodriver"
        else
            warn "Failed to download geckodriver — install manually"
            rm -rf "$TMP_DIR"
        fi
    fi
fi

# =============================================================================
# Step 5 — Firefox profile for Legion --web
# =============================================================================
step "Firefox profile"

PROFILE_DIR="${SUDO_USER_HOME}/.mozilla/firefox/legion-profile"
if [[ -d "$PROFILE_DIR" ]]; then
    ok "Legion Firefox profile already exists: ${PROFILE_DIR}"
else
    info "Creating dedicated Firefox profile for Legion --web…"
    mkdir -p "$PROFILE_DIR"
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        chown -R "${SUDO_USER}:${SUDO_USER}" "${SUDO_USER_HOME}/.mozilla" 2>/dev/null || true
    fi
    ok "Firefox profile created: ${PROFILE_DIR}"
fi

# =============================================================================
# Step 6 — Verify the installation
# =============================================================================
step "Verification"

info "Running install verification tests (this takes ~30 seconds)…"
cd "${SCRIPT_DIR}"
if python3 -m pytest tests/test_requirements.py --noconftest -q --tb=short 2>&1 | tail -5; then
    ok "All tests passed"
else
    warn "Some tests failed — check the output above. Legion may still run."
fi

# =============================================================================
# Step 7 — AI tab setup (optional)
# =============================================================================
if ! $SKIP_AI; then
    step "AI tab setup (optional)"
    echo ""
    echo "  The AI tab uses Anthropic Claude via Google Cloud Vertex AI."
    echo "  You need a GCP project with the Vertex AI API enabled."
    echo ""
    read -r -p "  Configure AI tab now? [y/N] " SETUP_AI
    if [[ "${SETUP_AI,,}" == "y" ]]; then
        echo ""
        read -r -p "  GCP project ID (e.g. my-project-123): " GCP_PROJECT
        read -r -p "  Vertex AI region [global]: " GCP_REGION
        GCP_REGION="${GCP_REGION:-global}"

        CLAUDE_SETTINGS="${SUDO_USER_HOME}/.claude/settings.json"
        mkdir -p "$(dirname "$CLAUDE_SETTINGS")"

        # Merge into existing settings.json or create new
        if [[ -f "$CLAUDE_SETTINGS" ]]; then
            python3 - "$CLAUDE_SETTINGS" "$GCP_PROJECT" "$GCP_REGION" <<'PYEOF'
import sys, json
path, project, region = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f: cfg = json.load(f)
cfg['ANTHROPIC_VERTEX_PROJECT_ID'] = project
cfg['CLOUD_ML_REGION'] = region
with open(path, 'w') as f: json.dump(cfg, f, indent=2)
print(f"  Updated {path}")
PYEOF
        else
            cat > "$CLAUDE_SETTINGS" <<EOF
{
  "ANTHROPIC_VERTEX_PROJECT_ID": "${GCP_PROJECT}",
  "CLOUD_ML_REGION": "${GCP_REGION}"
}
EOF
            info "Created ${CLAUDE_SETTINGS}"
        fi
        [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]] && \
            chown -R "${SUDO_USER}:${SUDO_USER}" "$(dirname "$CLAUDE_SETTINGS")" 2>/dev/null || true

        echo ""
        info "Next: authenticate with Google Cloud:"
        echo ""
        echo "      gcloud auth application-default login"
        echo ""
        ok "AI tab configuration written to ${CLAUDE_SETTINGS}"
    else
        info "Skipped — run 'gcloud auth application-default login' and set"
        info "ANTHROPIC_VERTEX_PROJECT_ID in ~/.claude/settings.json when ready."
    fi
fi

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}Installation complete.${NC}"
echo ""
echo "  Start Legion (web mode, opens Firefox automatically):"
echo -e "    ${BOLD}sudo python3 legion.py --web${NC}"
echo ""
echo "  Custom port:"
echo -e "    ${BOLD}sudo python3 legion.py --web --port 8080${NC}"
echo ""
echo "  No automatic browser:"
echo -e "    ${BOLD}sudo python3 legion.py --web --no-browser${NC}"
echo "    then open  http://127.0.0.1:5000  in Firefox"
echo ""
echo "  Qt6 GUI mode (requires X11 display):"
echo -e "    ${BOLD}sudo python3 legion.py${NC}"
echo ""
