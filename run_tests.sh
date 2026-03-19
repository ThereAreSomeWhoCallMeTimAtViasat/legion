#!/usr/bin/env bash
# Legion test runner — clean environment, colour summary, spinner, timer, progress
#
# Usage:
#   sudo bash run_tests.sh [OPTIONS] [VM_IP]
#
#   (no args)                  offline: unit + selenium offline
#   --unit                     unit / API tests only
#   --selenium                 selenium offline suites only
#   --offline                  unit + selenium offline (same as no args)
#   --live   192.168.85.11     live terminal + live selenium only
#   --all    192.168.85.11     everything
#   192.168.85.11              offline + live (bare IP)

set -uo pipefail

# ── Colours ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m';  BOLD='\033[1m';   DIM='\033[2m'; NC='\033[0m'

# ── Parse arguments ────────────────────────────────────────────────────────────
RUN_UNIT=false; RUN_SELENIUM=false; RUN_LIVE=false; LIVE_TARGET=""

if [[ $# -eq 0 ]]; then
    RUN_UNIT=true; RUN_SELENIUM=true
else
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --unit)     RUN_UNIT=true ;;
            --selenium) RUN_SELENIUM=true ;;
            --offline)  RUN_UNIT=true; RUN_SELENIUM=true ;;
            --live)
                RUN_LIVE=true; shift
                LIVE_TARGET="${1:-${LEGION_TEST_TARGET:-}}"
                [[ -z "$LIVE_TARGET" ]] && { echo "ERROR: --live requires a VM IP" >&2; exit 1; }
                ;;
            --all)
                RUN_UNIT=true; RUN_SELENIUM=true; RUN_LIVE=true; shift
                LIVE_TARGET="${1:-${LEGION_TEST_TARGET:-}}"
                [[ -z "$LIVE_TARGET" ]] && { echo "ERROR: --all requires a VM IP" >&2; exit 1; }
                ;;
            -*)
                echo "Unknown option: $1" >&2
                echo "Usage: sudo bash run_tests.sh [--unit|--selenium|--offline|--live IP|--all IP] [IP]" >&2
                exit 1 ;;
            *)  # bare IP
                LIVE_TARGET="$1"; RUN_UNIT=true; RUN_SELENIUM=true; RUN_LIVE=true ;;
        esac
        shift
    done
fi
$RUN_UNIT || $RUN_SELENIUM || $RUN_LIVE || { RUN_UNIT=true; RUN_SELENIUM=true; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Tracking ───────────────────────────────────────────────────────────────────
declare -a SUITE_NAMES=()
declare -a SUITE_STATUS=()   # pass | fail | skip
declare -a SUITE_PASSED=()
declare -a SUITE_FAILED=()
declare -a SUITE_SKIPPED=()
declare -a SUITE_ELAPSED=()

GRAND_PASS=0; GRAND_FAIL=0; GRAND_SKIP=0
SUITE_COUNT=0; SUITE_DONE=0
SCRIPT_START=$(date +%s)

# Count total suites up front so we can show X/N progress.
# When RUN_LIVE=true, test_terminal.py is skipped in the unit loop
# (the T7 live section runs it with LEGION_TEST_TARGET instead), so subtract 1.
_count_suites() {
    local n=0
    if $RUN_UNIT; then
        n=$(( n + 23 ))
        $RUN_LIVE && n=$(( n - 1 ))   # test_terminal.py skipped; covered by T7
    fi
    $RUN_LIVE     && n=$(( n + 1 ))   # T7 live terminal
    $RUN_SELENIUM && n=$(( n + 5 ))
    $RUN_LIVE     && n=$(( n + 1 ))   # live scan
    echo $n
}
SUITE_TOTAL=$(_count_suites)

# ── Spinner ────────────────────────────────────────────────────────────────────
SPINNER_PID=""
_frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

spinner_start() {
    local label="$1"
    (
        local i=0
        while true; do
            local f="${_frames[$((i % 10))]}"
            local e=$(( $(date +%s) - SCRIPT_START ))
            printf "\r  ${CYAN}%s${NC} %-45s  ${YELLOW}[%02d:%02d]${NC}  ${DIM}suite %d/%d${NC}  " \
                "$f" "$label" $(( e/60 )) $(( e%60 )) \
                "$SUITE_DONE" "$SUITE_TOTAL" >&2
            sleep 0.1
            i=$(( i+1 ))
        done
    ) &
    SPINNER_PID=$!
}

spinner_stop() {
    [[ -n "$SPINNER_PID" ]] && {
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
        printf "\r\033[K" >&2
    }
}

# ── Cleanup ────────────────────────────────────────────────────────────────────
cleanup() {
    spinner_stop
    echo -e "\n${CYAN}  Cleaning up...${NC}"
    pkill -f "legion.py --web" 2>/dev/null || true
    pkill -f "nmap"            2>/dev/null || true
    pkill -f "eyewitness"      2>/dev/null || true
    pkill -f "geckodriver"     2>/dev/null || true
    pkill -f "firefox"         2>/dev/null || true
    rm -rf /tmp/legion/legion-* /tmp/legion-* 2>/dev/null || true
    rm -f /tmp/test-a2-xml-copy.* /tmp/legion-api-gap-test*.legion \
          /tmp/legion-export-test.json /tmp/rt-test.legion \
          /tmp/legion-api-gap-test2.legion 2>/dev/null || true
    echo -e "${CYAN}  Done.${NC}"
}
trap cleanup EXIT
trap 'spinner_stop; echo -e "\n${RED}Interrupted.${NC}"; exit 130' INT TERM

# ── Free a TCP port (kill whatever process holds it) ─────────────────────────
free_port() {
    local port="$1"
    # fuser -k sends SIGKILL to whatever owns the port
    fuser -k "${port}/tcp" 2>/dev/null || true
    # Also try lsof-based kill as fallback
    local pid
    pid=$(lsof -ti :"$port" 2>/dev/null | head -1 || true)
    [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true
    # Brief wait for OS to release the socket
    sleep 0.5
}

# ── Initial prep ───────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}Preparing clean environment...${NC}"
pkill -f "legion.py --web" 2>/dev/null && echo "  Killed existing legion server" || true
pkill -f "geckodriver"     2>/dev/null || true
pkill -f "nmap"            2>/dev/null || true
pkill -f "eyewitness"      2>/dev/null || true
# Kill any stale test Flask servers on known test ports
for _p in 5094 5096 5097 5098 5099; do free_port "$_p"; done
sleep 1
rm -rf /tmp/legion/legion-* /tmp/legion-* 2>/dev/null || true
echo "  Cleared /tmp/legion* artefacts"

# ── Helpers ────────────────────────────────────────────────────────────────────
_extract() { echo "$1" | grep -oP "\\d+(?= $2)" 2>/dev/null | head -1 || echo "0"; }

section() { echo -e "\n${CYAN}${BOLD}══ $1 ══${NC}"; }

# Print one result row immediately after a suite finishes
print_result() {
    local name="$1" status="$2" p="$3" f="$4" s="$5" secs="$6"
    local mins=$(( secs / 60 )); local rem=$(( secs % 60 ))
    local timestr
    [[ $mins -gt 0 ]] && timestr="${mins}m${rem}s" || timestr="${secs}s"

    local mark total=$(( p + f + s ))
    case "$status" in
        pass) mark="${GREEN}✓${NC}" ;;
        skip) mark="${YELLOW}⊘${NC}" ;;
        *)    mark="${RED}✗${NC}" ;;
    esac

    # Counts column: "N passed  M failed  K skipped  of T"
    local counts="${GREEN}${p} passed${NC}"
    [[ "$f" -gt 0 ]] && counts="${counts}  ${RED}${f} failed${NC}" || counts="${counts}  ${DIM}${f} failed${NC}"
    [[ "$s" -gt 0 ]] && counts="${counts}  ${YELLOW}${s} skipped${NC}" || counts="${counts}  ${DIM}${s} skipped${NC}"
    counts="${counts}  ${DIM}of ${total}${NC}"

    printf "  %b %-42s  %b  ${DIM}%s${NC}\n" "$mark" "$name" "$counts" "$timestr"

    # Running grand total on a dim line
    SUITE_DONE=$(( SUITE_DONE + 1 ))
    GRAND_PASS=$(( GRAND_PASS + p ))
    GRAND_FAIL=$(( GRAND_FAIL + f ))
    GRAND_SKIP=$(( GRAND_SKIP + s ))
    local gtotal=$(( GRAND_PASS + GRAND_FAIL + GRAND_SKIP ))
    local elapsed=$(( $(date +%s) - SCRIPT_START ))
    printf "  ${DIM}  running total: %d passed, %d failed, %d skipped of %d  [%02d:%02d  suite %d/%d]${NC}\n" \
        "$GRAND_PASS" "$GRAND_FAIL" "$GRAND_SKIP" "$gtotal" \
        $(( elapsed/60 )) $(( elapsed%60 )) \
        "$SUITE_DONE" "$SUITE_TOTAL"
}

# ── run_unit ──────────────────────────────────────────────────────────────────
run_unit() {
    local file="$1"
    local name="${file##tests/}"; name="${name%.py}"
    local t0=$(date +%s)

    spinner_start "$name"
    local out rc
    out=$(sudo python3 "$file" 2>&1); rc=$?
    spinner_stop

    local rl secs p f s
    rl=$(echo "$out" | grep "^Results:" | tail -1)
    secs=$(( $(date +%s) - t0 ))

    if [[ -z "$rl" ]]; then
        print_result "$name" "fail" 0 1 0 "$secs"
        echo "$out" | tail -5 | sed "s/^/      /" >&2
        return
    fi

    p=$(_extract "$rl" "passed")
    f=$(_extract "$rl" "failed")
    s=$(_extract "$rl" "skipped")

    if [[ "$f" -eq 0 ]]; then
        print_result "$name" "pass" "$p" "$f" "$s" "$secs"
    else
        print_result "$name" "fail" "$p" "$f" "$s" "$secs"
        echo "$out" | grep "^  ✗" | head -10 | sed "s/^/      /" >&2
    fi
}

# ── run_pytest ────────────────────────────────────────────────────────────────
run_pytest() {
    local name="$1"; shift
    local args=("$@")
    local t0=$(date +%s)

    spinner_start "$name"
    local out rc
    out=$(sudo python3 -m pytest "${args[@]}" --tb=no -q 2>&1); rc=$?
    spinner_stop

    local secs=$(( $(date +%s) - t0 ))
    local sl p f s
    sl=$(echo "$out" | grep -E "passed|failed|error" | tail -1 || true)

    if [[ -z "$sl" ]]; then
        if echo "$out" | grep -q "no tests ran"; then
            print_result "$name" "skip" 0 0 0 "$secs"
        else
            local err
            err=$(echo "$out" | grep -i "error" | head -2 | tr '\n' ' ' || true)
            print_result "$name" "fail" 0 1 0 "$secs"
            echo "      ${err:-rc=$rc}" >&2
            echo "$out" | tail -8 | sed "s/^/      /" >&2
        fi
        return
    fi

    p=$(_extract "$sl" "passed")
    f=$(_extract "$sl" "failed")
    s=$(echo "$sl" | grep -oP '\d+(?= (skipped|deselected))' 2>/dev/null | head -1 || echo "0")

    if [[ "$rc" -eq 0 ]]; then
        print_result "$name" "pass" "$p" "$f" "$s" "$secs"
    else
        print_result "$name" "fail" "$p" "$f" "$s" "$secs"
        echo "$out" | grep "FAILED" | head -10 | sed "s/^/      /" >&2
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
if $RUN_UNIT; then
    section "Unit / API tests"
    for f in \
        tests/test_behavioral.py \
        tests/test_signal_chains.py \
        tests/test_phase1_right_panel.py \
        tests/test_flask_integration.py \
        tests/test_routes_webcontroller.py \
        tests/test_webcontroller.py \
        tests/test_webcontroller_remaining.py \
        tests/test_ui_wiring.py \
        tests/test_ui_fixes.py \
        tests/test_phase5_polish.py \
        tests/test_phase1_settings.py \
        tests/test_phase2_auxiliary.py \
        tests/test_phase2_interactions.py \
        tests/test_phase3_sorting.py \
        tests/test_phase4_state.py \
        tests/test_v6_v7_fixes.py \
        tests/test_new_dialogs.py \
        tests/test_visualupgrades_features.py \
        tests/test_api_gaps.py \
        tests/test_multihost_isolation.py \
        tests/test_terminal.py \
        tests/test_gap_implementations.py \
        tests/test_qt6_gaps.py
    do
        # test_terminal.py: T7 live tests skip without LEGION_TEST_TARGET.
        # When a live target is given, skip it here — the T7 section runs it
        # with LEGION_TEST_TARGET so all 45 tests pass with no skips.
        if [[ "$f" == "tests/test_terminal.py" ]] && $RUN_LIVE; then
            continue
        fi
        run_unit "$f"
    done
fi

if $RUN_LIVE; then
    section "Live terminal tests  (SSH / MySQL / msfconsole)"
    local_name="test_terminal T7  target=$LIVE_TARGET"
    t0=$(date +%s)
    spinner_start "$local_name"
    t7_out=$(sudo env LEGION_TEST_TARGET="$LIVE_TARGET" python3 tests/test_terminal.py 2>&1) || true
    spinner_stop
    t7_line=$(echo "$t7_out" | grep "^Results:" | tail -1)
    t7_p=$(_extract "$t7_line" "passed")
    t7_f=$(_extract "$t7_line" "failed")
    t7_s=$(_extract "$t7_line" "skipped")
    [[ "$t7_f" -eq 0 ]] \
        && print_result "$local_name" "pass" "$t7_p" "$t7_f" "$t7_s" "$(( $(date +%s) - t0 ))" \
        || print_result "$local_name" "fail" "$t7_p" "$t7_f" "$t7_s" "$(( $(date +%s) - t0 ))"
fi

if $RUN_SELENIUM; then
    section "Selenium offline  (headless Firefox)"
    # Free each port before binding — a daemon Flask thread from a prior run
    # may linger briefly after pytest exits, causing "Address already in use".
    free_port 5099; run_pytest "test_selenium_ui (offline)"  tests/test_selenium_ui.py -m "not live"
    free_port 5098; run_pytest "test_selenium_project"       tests/test_selenium_project.py
    free_port 5097; run_pytest "test_selenium_multihost"     tests/test_selenium_multihost.py
    free_port 5096; run_pytest "test_selenium_gaps"          tests/test_selenium_gaps.py
    free_port 5094; run_pytest "test_selenium_terminal"      tests/test_selenium_terminal.py
fi

if $RUN_LIVE; then
    section "Selenium live scan  (nmap + eyewitness + CVEs)"
    pkill -f "nmap" 2>/dev/null || true
    pkill -f "eyewitness" 2>/dev/null || true
    rm -rf /tmp/legion/legion-* 2>/dev/null || true
    echo -e "  target: ${BOLD}$LIVE_TARGET${NC}  (~10 min — 6 nmap stages + NSE + eyewitness)"
    free_port 5099; run_pytest "test_selenium_ui (live scan)" tests/test_selenium_ui.py -m live
fi

# ── Final summary ──────────────────────────────────────────────────────────────
TOTAL_ELAPSED=$(( $(date +%s) - SCRIPT_START ))

echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Legion Test Report  —  $(date '+%Y-%m-%d %H:%M')${NC}"
echo -e "${BOLD}  Total time: $((TOTAL_ELAPSED/60))m$((TOTAL_ELAPSED%60))s  |  $SUITE_DONE suites run${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""

GRAND_TOTAL=$(( GRAND_PASS + GRAND_FAIL + GRAND_SKIP ))

if [[ $GRAND_FAIL -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}ALL PASSED${NC}"
else
    echo -e "  ${RED}${BOLD}FAILURES DETECTED${NC}"
fi
echo ""
printf "  ${GREEN}%d passed${NC}   ${RED}%d failed${NC}   ${YELLOW}%d skipped${NC}   ${DIM}of %d total tests${NC}\n" \
    "$GRAND_PASS" "$GRAND_FAIL" "$GRAND_SKIP" "$GRAND_TOTAL"
echo ""
echo -e "  ${CYAN}Options:${NC}"
echo -e "    ${BOLD}sudo bash run_tests.sh${NC}                     offline"
echo -e "    ${BOLD}sudo bash run_tests.sh --unit${NC}              unit only"
echo -e "    ${BOLD}sudo bash run_tests.sh --selenium${NC}          selenium offline only"
echo -e "    ${BOLD}sudo bash run_tests.sh --live 192.168.85.11${NC}  live only"
echo -e "    ${BOLD}sudo bash run_tests.sh --all  192.168.85.11${NC}  everything"
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""

[[ $GRAND_FAIL -eq 0 ]]
