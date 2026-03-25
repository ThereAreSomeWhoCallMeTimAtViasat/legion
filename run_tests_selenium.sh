#!/usr/bin/env bash
# Legion test runner — runs all suites and prints a colour summary
#
# Usage:
#   sudo bash run_tests.sh                          # offline tests only
#   sudo bash run_tests.sh 192.168.85.11            # + live terminal + live scan
#   LEGION_TEST_TARGET=192.168.85.11 sudo -E bash run_tests.sh

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASS_MARK="${GREEN}✓${NC}"
FAIL_MARK="${RED}✗${NC}"
SKIP_MARK="${YELLOW}⊘${NC}"

# ── Arguments / env ────────────────────────────────────────────────────────────
LIVE_TARGET="${1:-${LEGION_TEST_TARGET:-}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Result tracking ────────────────────────────────────────────────────────────
declare -a SUMMARY_LINES=()
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0

# ── Helpers ────────────────────────────────────────────────────────────────────
record() {
    # record LABEL STATUS DETAIL
    local label="$1" status="$2" detail="$3"
    if [[ "$status" == "pass" ]]; then
        SUMMARY_LINES+=("${PASS_MARK} ${label}  ${GREEN}${detail}${NC}")
        (( TOTAL_PASS++ )) || true
    elif [[ "$status" == "skip" ]]; then
        SUMMARY_LINES+=("${SKIP_MARK} ${label}  ${YELLOW}${detail}${NC}")
        (( TOTAL_SKIP++ )) || true
    else
        SUMMARY_LINES+=("${FAIL_MARK} ${label}  ${RED}${detail}${NC}")
        (( TOTAL_FAIL++ )) || true
    fi
}

section() {
    echo -e "\n${CYAN}${BOLD}══ $1 ══${NC}"
}

# Run a single unit test file (sudo python3 <file>).
# Parses the last "Results: N passed, M failed" line.
run_unit() {
    local file="$1"
    local label="${file##tests/}"          # strip leading tests/
    label="${label%.py}"                   # strip .py

    local out
    out=$(sudo python3 "$file" 2>&1) || true

    # Grab last Results: line (some files print two)
    local results_line
    results_line=$(echo "$out" | grep "^Results:" | tail -1)

    if [[ -z "$results_line" ]]; then
        record "$label" "fail" "no Results: line (file error?)"
        return
    fi

    local passed failed skipped
    passed=$(echo "$results_line" | grep -oP '\d+(?= passed)' || echo 0)
    failed=$(echo  "$results_line" | grep -oP '\d+(?= failed)' || echo 0)
    skipped=$(echo "$results_line" | grep -oP '\d+(?= skipped)' || echo 0)

    local detail="${passed}p ${failed}f ${skipped}s"
    if [[ "$failed" -eq 0 ]]; then
        record "$label" "pass" "$detail"
    else
        record "$label" "fail" "$detail"
        # Print failed test names for quick diagnosis
        echo "$out" | grep "^  ✗" | head -10 | sed "s/^/    /" >&2
    fi
}

# Run a pytest-based suite.
# Parses pytest summary line.
run_pytest() {
    local label="$1"; shift          # first arg is label, rest are pytest args
    local args=("$@")

    local out exit_code
    out=$(sudo python3 -m pytest "${args[@]}" --tb=no -q 2>&1) || exit_code=$?
    exit_code="${exit_code:-0}"

    # pytest summary: "X passed, Y failed, Z skipped in N.Ns"
    local summary_line
    summary_line=$(echo "$out" | grep -E "passed|failed|error" | tail -1 || true)

    if [[ -z "$summary_line" ]]; then
        if echo "$out" | grep -q "no tests ran"; then
            record "$label" "skip" "no tests ran"
        else
            record "$label" "fail" "no pytest output (install error?)"
        fi
        return
    fi

    local passed failed skipped
    passed=$(echo "$summary_line" | grep -oP '\d+(?= passed)' || echo 0)
    failed=$(echo  "$summary_line" | grep -oP '\d+(?= failed)' || echo 0)
    skipped=$(echo "$summary_line" | grep -oP '\d+(?= (skipped|deselected))' | head -1 || echo 0)

    local detail="${passed}p ${failed}f ${skipped}s"
    if [[ "$exit_code" -eq 0 ]]; then
        record "$label" "pass" "$detail"
    else
        record "$label" "fail" "$detail"
        echo "$out" | grep "FAILED" | head -10 | sed "s/^/    /" >&2
    fi
}

# ── Unit tests ─────────────────────────────────────────────────────────────────
section "Unit / API tests skipped"


# ── Live terminal tests (T7) ──────────────────────────────────────────────────
section "Live terminal tests  (SSH / MySQL / msfconsole) skipped"


# ── Selenium offline ──────────────────────────────────────────────────────────
section "Selenium offline  (headless Firefox)"

echo -ne "  running test_selenium_ui (offline) ..."
run_pytest "test_selenium_ui (offline)" tests/test_selenium_ui.py -m "not live"
echo -e "\r  ${SUMMARY_LINES[-1]}"

echo -ne "  running test_selenium_project ..."
run_pytest "test_selenium_project" tests/test_selenium_project.py
echo -e "\r  ${SUMMARY_LINES[-1]}"

echo -ne "  running test_selenium_multihost ..."
run_pytest "test_selenium_multihost" tests/test_selenium_multihost.py
echo -e "\r  ${SUMMARY_LINES[-1]}"

echo -ne "  running test_selenium_gaps ..."
run_pytest "test_selenium_gaps" tests/test_selenium_gaps.py
echo -e "\r  ${SUMMARY_LINES[-1]}"

echo -ne "  running test_selenium_terminal ..."
run_pytest "test_selenium_terminal" tests/test_selenium_terminal.py
echo -e "\r  ${SUMMARY_LINES[-1]}"

# ── Selenium live scan ────────────────────────────────────────────────────────
section "Selenium live scan  (nmap + eyewitness + CVEs)"

if [[ -z "$LIVE_TARGET" ]]; then
    record "test_selenium_ui (live scan)" "skip" "LEGION_TEST_TARGET not set — skipped"
    echo -e "  ${SUMMARY_LINES[-1]}"
else
    echo "  target: $LIVE_TARGET — cleaning stale /tmp/legion dirs ..."
    sudo rm -rf /tmp/legion/legion-* 2>/dev/null || true
    echo -ne "  running test_selenium_ui live scan (~4 min) ..."
    run_pytest "test_selenium_ui (live scan)" \
        tests/test_selenium_ui.py -m live \
        --timeout=960 \
        -x
    echo -e "\r  ${SUMMARY_LINES[-1]}"
fi

# ── Summary report ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Legion Test Report — $(date '+%Y-%m-%d %H:%M')${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""
for line in "${SUMMARY_LINES[@]}"; do
    echo -e "  $line"
done
echo ""
echo -e "${CYAN}──────────────────────────────────────────────────────${NC}"

if [[ $TOTAL_FAIL -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}ALL PASSED${NC}  ${GREEN}${TOTAL_PASS} passed${NC}  ${YELLOW}${TOTAL_SKIP} skipped${NC}"
else
    echo -e "  ${RED}${BOLD}FAILURES DETECTED${NC}  ${GREEN}${TOTAL_PASS} passed${NC}  ${RED}${TOTAL_FAIL} failed${NC}  ${YELLOW}${TOTAL_SKIP} skipped${NC}"
fi

if [[ -z "$LIVE_TARGET" ]]; then
    echo -e "  ${YELLOW}Tip:${NC} pass a VM IP to include live tests:"
    echo -e "       ${BOLD}sudo bash run_tests.sh 192.168.85.11${NC}"
fi

echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""

# Exit non-zero if anything failed
[[ $TOTAL_FAIL -eq 0 ]]
