#!/usr/bin/env bash
# Legion test runner — clean environment, colour summary, spinner, timer, progress
#
# Usage:
#   sudo bash run_tests.sh [OPTIONS] [VM_IP]
#
#   (no args)                  offline: unit + selenium + user-stories
#   --unit                     unit / API tests only
#   --selenium                 selenium offline suites only
#   --stories                  user-story tests only (ports 5085/5086)
#   --offline                  unit + selenium + user-stories (same as no args)
#   --live   192.168.85.11     live terminal + live selenium + live user-stories
#   --all    192.168.85.11     everything
#   --no-report                skip HTML report generation (default: generate)
#   192.168.85.11              offline + live (bare IP)

set -uo pipefail

# ── Colours ────────────────────────────────────────────────────────────────────
GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m';  BOLD=$'\033[1m';  DIM=$'\033[2m'; NC=$'\033[0m'

# ── Parse arguments ────────────────────────────────────────────────────────────
RUN_UNIT=false; RUN_SELENIUM=false; RUN_LIVE=false; RUN_STORIES=false
LIVE_TARGET=""; GEN_REPORTS=true

if [[ $# -eq 0 ]]; then
    RUN_UNIT=true; RUN_SELENIUM=true; RUN_STORIES=true
else
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --unit)      RUN_UNIT=true ;;
            --selenium)  RUN_SELENIUM=true ;;
            --stories)   RUN_STORIES=true ;;
            --no-report) GEN_REPORTS=false ;;
            --offline)   RUN_UNIT=true; RUN_SELENIUM=true; RUN_STORIES=true ;;
            --live)
                RUN_LIVE=true; shift
                LIVE_TARGET="${1:-${LEGION_TEST_TARGET:-}}"
                [[ -z "$LIVE_TARGET" ]] && { echo "ERROR: --live requires a VM IP" >&2; exit 1; }
                ;;
            --all)
                RUN_UNIT=true; RUN_SELENIUM=true; RUN_STORIES=true; RUN_LIVE=true; shift
                LIVE_TARGET="${1:-${LEGION_TEST_TARGET:-}}"
                [[ -z "$LIVE_TARGET" ]] && { echo "ERROR: --all requires a VM IP" >&2; exit 1; }
                ;;
            -*)
                echo "Unknown option: $1" >&2
                echo "Usage: sudo bash run_tests.sh [--unit|--selenium|--stories|--offline|--live IP|--all IP] [--no-report] [IP]" >&2
                exit 1 ;;
            *)  # bare IP
                LIVE_TARGET="$1"; RUN_UNIT=true; RUN_SELENIUM=true; RUN_STORIES=true; RUN_LIVE=true ;;
        esac
        shift
    done
fi
$RUN_UNIT || $RUN_SELENIUM || $RUN_LIVE || $RUN_STORIES || { RUN_UNIT=true; RUN_SELENIUM=true; RUN_STORIES=true; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Sync repo legion.conf → live conf before any test run ─────────────────────
# Tests that use create_test_app() / Settings(AppSettings()) read from the live
# conf at ~/.local/share/legion/legion.conf.  Without this sync, tests run
# against a stale conf that may be missing new tools or still have banned tools.
_LIVE_CONF="$HOME/.local/share/legion/legion.conf"
_REPO_CONF="$SCRIPT_DIR/legion.conf"
if [[ -f "$_REPO_CONF" ]]; then
    mkdir -p "$(dirname "$_LIVE_CONF")"
    cp "$_REPO_CONF" "$_LIVE_CONF"
    # Also sync the 'default' config profile — test_ui_wiring.py P6 activates it,
    # copying it to the working conf. If default.conf is stale (missing new tools),
    # it silently downgrades the live conf and breaks later selenium tests.
    _PROFILES_DIR="$(dirname "$_LIVE_CONF")/profiles"
    mkdir -p "$_PROFILES_DIR"
    cp "$_REPO_CONF" "$_PROFILES_DIR/default.conf"
fi

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
# Section-level counters — reset at each ══ section ══ header
SECTION_PASS=0; SECTION_FAIL=0; SECTION_SKIP=0; SECTION_START=$SCRIPT_START

# Count total suites up front so we can show X/N progress.
# When RUN_LIVE=true, test_terminal.py is skipped in the unit loop
# (the T7 live section runs it with LEGION_TEST_TARGET instead), so subtract 1.
_count_suites() {
    local n=0
    if $RUN_UNIT; then
        n=$(( n + 24 ))               # 24 unit files (includes test_export_and_hydra)
        $RUN_LIVE && n=$(( n - 1 ))   # test_terminal.py skipped; covered by T7
    fi
    $RUN_LIVE     && n=$(( n + 1 ))   # T7 live terminal
    $RUN_LIVE     && n=$(( n + 1 ))   # Hydra live (SSH + MySQL)
    $RUN_SELENIUM && n=$(( n + 5 ))
    $RUN_LIVE     && n=$(( n + 1 ))   # live scan
    if $RUN_STORIES; then
        n=$(( n + 2 ))                # user_stories: match-first + everything-else
        $RUN_LIVE && n=$(( n + 1 ))   # user_stories live (US-09/39)
    fi
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
    _us_stop_servers
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

# ── Free a TCP port and wait until it is confirmed free ───────────────────────
free_port() {
    local port="$1"
    # Extract PID directly from ss (most reliable on Linux)
    local pid
    pid=$(ss -tlnp "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)
    [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true
    # Fallback: fuser and lsof
    fuser -k "${port}/tcp" 2>/dev/null || true
    pid=$(lsof -ti :"$port" 2>/dev/null | head -1 || true)
    [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true
    # Wait (up to 10s) until ss confirms the port is released
    local i=0
    while ss -tlnp 2>/dev/null | grep -q ":${port}\b" && [[ $i -lt 20 ]]; do
        sleep 0.5
        i=$(( i + 1 ))
    done
    sleep 0.3
}

# ── User-story server management ───────────────────────────────────────────────
US_PORT_A=5085   # primary user-story server
US_PORT_B=5086   # second instance (US-55 two-instance isolation)
US_PID_A=""
US_PID_B=""
US_HB_PID=""     # heartbeat keeper PID

_us_start_servers() {
    echo -e "  Starting user-story servers on :${US_PORT_A} and :${US_PORT_B}..."
    # Kill any stale legion.py processes to avoid the "other server" interactive prompt
    pkill -f "legion.py.*--port.*${US_PORT_A}" 2>/dev/null || true
    pkill -f "legion.py.*--port.*${US_PORT_B}" 2>/dev/null || true
    sleep 1
    free_port "$US_PORT_A"
    free_port "$US_PORT_B"

    # --no-prompt: skip the interactive "kill/continue/abort" dialog if another
    # instance is somehow still detected (e.g. from a previous interrupted run)
    python3 legion.py --web --port "$US_PORT_A" --no-prompt > /tmp/legion-us-a.log 2>&1 &
    US_PID_A=$!
    python3 legion.py --web --port "$US_PORT_B" --no-prompt > /tmp/legion-us-b.log 2>&1 &
    US_PID_B=$!

    # Wait for both to bind (up to 15 s)
    local waited=0 ok_a="" ok_b=""
    while [[ $waited -lt 15 ]]; do
        sleep 1; waited=$(( waited + 1 ))
        ok_a=$(curl -s --max-time 2 "http://127.0.0.1:${US_PORT_A}/api/snapshot" \
               | python3 -c "import sys,json; json.load(sys.stdin); print('ok')" 2>/dev/null || true)
        ok_b=$(curl -s --max-time 2 "http://127.0.0.1:${US_PORT_B}/api/snapshot" \
               | python3 -c "import sys,json; json.load(sys.stdin); print('ok')" 2>/dev/null || true)
        [[ "$ok_a" == "ok" && "$ok_b" == "ok" ]] && break
    done
    [[ "$ok_a" != "ok" ]] && echo "  ${YELLOW}WARNING: :${US_PORT_A} did not start in time${NC}" >&2
    [[ "$ok_b" != "ok" ]] && echo "  ${YELLOW}WARNING: :${US_PORT_B} did not start in time${NC}" >&2

    # Seed 5085 with a test host
    python3 - <<'PYEOF' 2>/dev/null
import requests, tempfile, os
xml = '''<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
</nmaprun>'''
with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
    f.write(xml); path = f.name
try:
    requests.post('http://127.0.0.1:5085/api/nmap/import-xml',
                  json={'path': path}, timeout=15)
finally:
    os.unlink(path)
PYEOF

    # Heartbeat keeper — pings both servers every 8 s so the 20 s watchdog
    # never fires between consecutive pytest runs (was 15 s — only 5 s margin)
    ( while true; do
        curl -s -X POST "http://127.0.0.1:${US_PORT_A}/api/heartbeat" \
             -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
        curl -s -X POST "http://127.0.0.1:${US_PORT_B}/api/heartbeat" \
             -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
        sleep 8
    done ) &
    US_HB_PID=$!
    echo -e "  ${GREEN}✓${NC} :${US_PORT_A} and :${US_PORT_B} ready (heartbeat PID $US_HB_PID)"
}

_us_stop_servers() {
    [[ -n "$US_HB_PID" ]] && kill "$US_HB_PID" 2>/dev/null || true
    [[ -n "$US_PID_A"  ]] && kill "$US_PID_A"  2>/dev/null || true
    [[ -n "$US_PID_B"  ]] && kill "$US_PID_B"  2>/dev/null || true
    US_PID_A=""; US_PID_B=""; US_HB_PID=""
}

# ── HTML report generation ──────────────────────────────────────────────────────
_gen_reports() {
    local live_target="${1:-}"
    local report_dir="testreport"
    mkdir -p "$report_dir"
    echo -e "\n  ${CYAN}Generating HTML test reports → ${report_dir}/${NC}"
    echo -e "  ${DIM}(screenshots captured for every step)${NC}"

    # Offline reports — no live target needed
    local offline_scripts=(
        tests/generate_report_US04.py
        tests/generate_report_US03.py
        tests/generate_report_US02.py
        tests/generate_report_US25.py
        tests/generate_report_US26.py
        tests/generate_report_US40.py
        tests/generate_report_US41.py
        tests/generate_report_US42.py
        tests/generate_report_US44_45_46.py
        tests/generate_report_US31.py
        tests/generate_report_US54.py
        tests/generate_report_US16.py
        tests/generate_report_US18.py
        tests/generate_report_US55.py
        tests/generate_report_US32.py
    )

    local failed_reports=0
    for script in "${offline_scripts[@]}"; do
        [[ -f "$script" ]] || continue
        local us; us=$(basename "$script" .py | sed 's/generate_report_//')
        printf "    %-32s " "$us"
        # Drain both servers before each report — earlier reports call /api/nmap/scan
        # whose auto-tool cascade refills the fast-process queue between reports.
        curl -s -X POST "http://127.0.0.1:${US_PORT_A}/api/processes/drain" \
             -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
        curl -s -X POST "http://127.0.0.1:${US_PORT_B}/api/processes/drain" \
             -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
        # Poll until queue empty — drain takes 10-15 s with many processes
        local _t=0
        while [[ $_t -lt 20 ]]; do
            local _running
            _running=$(curl -s "http://127.0.0.1:${US_PORT_A}/api/snapshot" \
                | python3 -c "import sys,json; d=json.load(sys.stdin);
                print(sum(1 for p in d.get('processes',[]) if p.get('status') in ('Running','Waiting')))" \
                2>/dev/null || echo "0")
            [[ "$_running" == "0" ]] && break
            sleep 1; _t=$(( _t + 1 ))
        done
        sleep 5   # let killed-process threads finish their DB writes (was 2 s — too short)
        # US55 uses --port-a/--port-b (two-instance test); all others use --port
        local out
        if [[ "$us" == "US55" ]]; then
            out=$(python3 "$script" --port-a "$US_PORT_A" --port-b "$US_PORT_B" 2>&1)
        else
            out=$(python3 "$script" --port "$US_PORT_A" 2>&1)
        fi
        if [[ $? -eq 0 ]]; then
            local html; html=$(echo "$out" | grep "^Report:" | tail -1 | awk '{print $2}')
            printf "${GREEN}✓${NC} %s\n" "${html##*/}"
        else
            printf "${RED}✗ FAILED${NC}\n"
            echo "$out" | tail -3 | sed 's/^/         /'
            failed_reports=$(( failed_reports + 1 ))
        fi
    done

    # Live-only reports — US-09 (nmap %) and US-39 (screenshot) need a real target
    if [[ -n "$live_target" ]]; then
        for script in tests/generate_report_US09.py tests/generate_report_US39.py; do
            [[ -f "$script" ]] || continue
            local us; us=$(basename "$script" .py | sed 's/generate_report_//')
            printf "    %-32s " "${us} (live:${live_target})"
            local out; out=$(python3 "$script" --port "$US_PORT_A" \
                             --target "$live_target" 2>&1)
            if [[ $? -eq 0 ]]; then
                local html; html=$(echo "$out" | grep "^Report:" | tail -1 | awk '{print $2}')
                printf "${GREEN}✓${NC} %s\n" "${html##*/}"
            else
                printf "${RED}✗ FAILED${NC}\n"
                echo "$out" | tail -3 | sed 's/^/         /'
                failed_reports=$(( failed_reports + 1 ))
            fi
        done
    fi

    if [[ $failed_reports -eq 0 ]]; then
        echo -e "\n  ${GREEN}✓ All HTML reports written to ${report_dir}/${NC}"
    else
        echo -e "\n  ${YELLOW}${failed_reports} report(s) failed${NC}"
    fi
}

# ── Initial prep ───────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}Preparing clean environment...${NC}"
pkill -f "legion.py --web" 2>/dev/null && echo "  Killed existing legion server" || true
pkill -f "geckodriver"     2>/dev/null || true
pkill -f "nmap"            2>/dev/null || true
pkill -f "eyewitness"      2>/dev/null || true
# Kill any stale test Flask servers on known test ports
for _p in 5072 5073 5074 5075 5076 5077 5078 5079 5080 5081 5082 5083 5085 5086 5094 5096 5097 5098 5099; do free_port "$_p"; done
sleep 1
rm -rf /tmp/legion/legion-* /tmp/legion-* 2>/dev/null || true
echo "  Cleared /tmp/legion* artefacts"

# ── Helpers ────────────────────────────────────────────────────────────────────
_extract() { echo "$1" | grep -oP "\\d+(?= $2)" 2>/dev/null | head -1 || echo "0"; }

_section_subtotal() {
    local sec_total=$(( SECTION_PASS + SECTION_FAIL + SECTION_SKIP ))
    [[ $sec_total -eq 0 ]] && return
    local sec_elapsed=$(( $(date +%s) - SECTION_START ))
    local sc="${GREEN}${SECTION_PASS} passed${NC}"
    [[ $SECTION_FAIL -gt 0 ]] && sc="${sc}  ${RED}${SECTION_FAIL} failed${NC}" \
                               || sc="${sc}  ${DIM}0 failed${NC}"
    [[ $SECTION_SKIP -gt 0 ]] && sc="${sc}  ${YELLOW}${SECTION_SKIP} skipped${NC}" \
                               || sc="${sc}  ${DIM}0 skipped${NC}"
    printf "  ${DIM}────────────────────────────────────────────────────────────${NC}\n"
    printf "  ${DIM}Section total: %b  of %d  [%dm%ds]${NC}\n\n" \
        "$sc" "$sec_total" $(( sec_elapsed/60 )) $(( sec_elapsed%60 ))
}

section() {
    _section_subtotal          # print previous section's totals (if any ran)
    SECTION_PASS=0; SECTION_FAIL=0; SECTION_SKIP=0; SECTION_START=$(date +%s)
    echo -e "\n${CYAN}${BOLD}══ $1 ══${NC}"
}

_skip_note() { printf "               ${DIM}↳ %s${NC}\n" "$1"; }

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

    # Accumulate into grand total and section total
    SUITE_DONE=$(( SUITE_DONE + 1 ))
    GRAND_PASS=$(( GRAND_PASS + p ))
    GRAND_FAIL=$(( GRAND_FAIL + f ))
    GRAND_SKIP=$(( GRAND_SKIP + s ))
    SECTION_PASS=$(( SECTION_PASS + p ))
    SECTION_FAIL=$(( SECTION_FAIL + f ))
    SECTION_SKIP=$(( SECTION_SKIP + s ))
    # Progress indicator on a dim line (suite count only — no carried failure totals)
    local elapsed=$(( $(date +%s) - SCRIPT_START ))
    printf "  ${DIM}  [%02d:%02d  suite %d/%d]${NC}\n" \
        $(( elapsed/60 )) $(( elapsed%60 )) "$SUITE_DONE" "$SUITE_TOTAL"
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

    if [[ "$f" -eq 0 && "$s" -eq 0 ]]; then
        print_result "$name" "pass" "$p" "$f" "$s" "$secs"
    else
        [[ "$f" -gt 0 ]] && print_result "$name" "fail" "$p" "$f" "$s" "$secs" \
                         || print_result "$name" "pass" "$p" "$f" "$s" "$secs"
        # Print failed test names
        echo "$out" | grep "^  ✗" | sed "s/^/      ${RED}FAILED${NC} /"
        # Print skipped test names with context
        if [[ "$s" -gt 0 ]]; then
            echo "$out" | grep "^  ⊘" | sed "s/^/      ${YELLOW}SKIPPED${NC} /"
            # Annotate skip reason based on which file is running
            if [[ "$file" == *"test_export_and_hydra"* ]]; then
                if $RUN_LIVE; then
                    _skip_note "PERMANENT: Hydra libssh2 MAC incompatibility with Metasploitable OpenSSH 4.7 (T9)"
                    _skip_note "FTP (H3) and MySQL (H2) confirm the Hydra pipeline — already ran in Live Hydra section"
                else
                    _skip_note "No live VM target — all ${s} rerun in 'Live Hydra tests' with --live or --all 192.168.85.11"
                fi
            elif [[ "$file" == *"test_terminal"* ]]; then
                if $RUN_LIVE; then
                    _skip_note "Live tests require LEGION_TEST_TARGET — set on the T7 section which already ran above"
                else
                    _skip_note "No live VM target — T7 tests rerun in 'Live terminal tests' with --live or --all 192.168.85.11"
                fi
            fi
        fi
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
            echo "      ${err:-rc=$rc}"
            echo "$out" | tail -8 | sed "s/^/      /"
        fi
        return
    fi

    p=$(_extract "$sl" "passed")
    f=$(_extract "$sl" "failed")
    s=$(echo "$sl" | grep -oP '\d+(?= (skipped|deselected))' 2>/dev/null | head -1 || echo "0")

    if [[ "$rc" -eq 0 ]]; then
        print_result "$name" "pass" "$p" "$f" "$s" "$secs"
        # Print skipped test names (deselected by -m marker don't show here)
        echo "$out" | grep "^SKIPPED" | sed "s/^/      ${YELLOW}SKIPPED${NC} /" || true
        if [[ "$s" -gt 0 ]]; then
            _skip_note "${_SKIP_NOTE:-pytest skipTest() stubs — implement or delete (see test_CriticalPaths.py)}"
        fi
    else
        print_result "$name" "fail" "$p" "$f" "$s" "$secs"
        # Print every failed test name
        echo "$out" | grep "^FAILED" | sed "s/^FAILED /      ${RED}FAILED${NC} /"
        # Print skipped test names
        echo "$out" | grep "^SKIPPED" | sed "s/^/      ${YELLOW}SKIPPED${NC} /" || true
        if [[ "$s" -gt 0 ]]; then
            _skip_note "${_SKIP_NOTE:-pytest skipTest() stubs — implement or delete (see test_CriticalPaths.py)}"
        fi
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
        tests/test_qt6_gaps.py \
        tests/test_export_and_hydra.py
    do
        # test_terminal.py: T7 live tests skip without LEGION_TEST_TARGET.
        # When a live target is given, skip it here — the T7 section runs it
        # with LEGION_TEST_TARGET so all 45 tests pass with no skips.
        if [[ "$f" == "tests/test_terminal.py" ]] && $RUN_LIVE; then
            continue
        fi
        run_unit "$f"
    done

    # Integration tests (pytest-style unittest classes) — shared DB/repository layer
    # used by both Qt6 and Flask. These catch API regressions like renamed methods,
    # changed constructor signatures, and missing attributes.
    run_pytest "integration/core_workflows" \
        tests/integration/test_CoreWorkflows.py \
        tests/integration/test_SmokeTests.py \
        tests/integration/test_CriticalPaths.py
    run_pytest "features/db_and_model" \
        tests/features/test_ConfigSyntaxValidation.py \
        tests/features/test_HtmlOutputStorage.py \
        tests/features/test_NotesSaveFix.py \
        tests/features/test_TabSwitchingDataIntegrity.py \
        tests/features/test_ToolTabOutputPersistence.py
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
    _t7_secs=$(( $(date +%s) - t0 ))
    if [[ "$t7_f" -eq 0 && "$t7_s" -eq 0 ]]; then
        print_result "$local_name" "pass" "$t7_p" "$t7_f" "$t7_s" "$_t7_secs"
    else
        [[ "$t7_f" -gt 0 ]] \
            && print_result "$local_name" "fail" "$t7_p" "$t7_f" "$t7_s" "$_t7_secs" \
            || print_result "$local_name" "pass" "$t7_p" "$t7_f" "$t7_s" "$_t7_secs"
        echo "$t7_out" | grep "^  ✗" | sed "s/^/      ${RED}FAILED${NC} /"
        echo "$t7_out" | grep "^  ⊘" | sed "s/^/      ${YELLOW}SKIPPED${NC} /"
    fi
fi

if $RUN_LIVE; then
    section "Live Hydra tests  (SSH + MySQL brute-force)"
    hydra_name="test_export_and_hydra (Hydra live)"
    t0=$(date +%s)
    spinner_start "$hydra_name"
    hydra_out=$(sudo env LEGION_TEST_TARGET="$LIVE_TARGET" \
                         LEGION_SSH_PORT=22 \
                         LEGION_MYSQL_PORT=3306 \
                         LEGION_FTP_PORT=21 \
                    python3 tests/test_export_and_hydra.py 2>&1) || true
    spinner_stop
    hydra_line=$(echo "$hydra_out" | grep "^Results:" | tail -1)
    hydra_p=$(_extract "$hydra_line" "passed")
    hydra_f=$(_extract "$hydra_line" "failed")
    hydra_s=$(_extract "$hydra_line" "skipped")
    _hydra_secs=$(( $(date +%s) - t0 ))
    if [[ "$hydra_f" -eq 0 && "$hydra_s" -eq 0 ]]; then
        print_result "$hydra_name" "pass" "$hydra_p" "$hydra_f" "$hydra_s" "$_hydra_secs"
    else
        [[ "$hydra_f" -gt 0 ]] \
            && print_result "$hydra_name" "fail" "$hydra_p" "$hydra_f" "$hydra_s" "$_hydra_secs" \
            || print_result "$hydra_name" "pass" "$hydra_p" "$hydra_f" "$hydra_s" "$_hydra_secs"
        echo "$hydra_out" | grep "^  ✗" | sed "s/^/      ${RED}FAILED${NC} /"
        echo "$hydra_out" | grep "^  ⊘" | sed "s/^/      ${YELLOW}SKIPPED${NC} /"
        if [[ "$hydra_s" -gt 0 ]]; then
            _skip_note "PERMANENT: Hydra libssh2 MAC incompatibility with Metasploitable OpenSSH 4.7"
            _skip_note "FTP (H3) and MySQL (H2) above confirm the Hydra pipeline works — see T9"
        fi
    fi
fi

if $RUN_SELENIUM; then
    # Re-sync conf + default profile before selenium section.
    # test_ui_wiring.py P6 activates the 'default' profile (copies it over the
    # working conf). If default.conf is stale, it silently downgrades the live conf.
    if [[ -f "$_REPO_CONF" ]]; then
        cp "$_REPO_CONF" "$_LIVE_CONF"
        cp "$_REPO_CONF" "$_PROFILES_DIR/default.conf"
    fi
    section "Selenium offline  (headless Firefox)"
    # Free each port before binding — a daemon Flask thread from a prior run
    # may linger briefly after pytest exits, causing "Address already in use".
    free_port 5099; run_pytest "test_selenium_ui (offline)"  tests/test_selenium_ui.py -m "not live"
    free_port 5098; run_pytest "test_selenium_project"       tests/test_selenium_project.py
    free_port 5097; run_pytest "test_selenium_multihost"     tests/test_selenium_multihost.py
    free_port 5096; run_pytest "test_selenium_gaps"          tests/test_selenium_gaps.py
    free_port 5094; run_pytest "test_selenium_terminal"      tests/test_selenium_terminal.py
    free_port 5072; run_pytest "ui_session_features (v10.59-63)" tests/test_ui_session_features.py
    free_port 5073; run_pytest "save_open_data (v10.65-66)" tests/test_save_open_data.py
    free_port 5074
    run_pytest "multiinstance_detection (v10.64)" tests/test_multiinstance_detection.py
    free_port 5075; run_pytest "ui_v10_features (v10.69-73)" tests/test_ui_v10_features.py
    free_port 5076; run_pytest "ui_new_features (v10.67-71)" tests/test_ui_new_features.py
    free_port 5077; run_pytest "ui_new_features2 (v10.76-82)" tests/test_ui_new_features2.py
    free_port 5078; run_pytest "ui_v10b_features (v10.75-83)" tests/test_ui_v10b_features.py
    free_port 5079; run_pytest "ui_v10c_features (v10.98-110)" tests/test_ui_v10c_features.py
    free_port 5080; run_pytest "ui_session_tweaks (v10.85-103)" tests/test_ui_session_tweaks.py
    free_port 5081; run_pytest "ui_v10d_features (v10.128-133)" tests/test_ui_v10d_features.py
    free_port 5082; run_pytest "ui_v10e_features (v10.137-143)" tests/test_ui_v10e_features.py
    free_port 5082; run_pytest "ui_new_clear_checkbox (v10.136-143)" tests/test_ui_new_clear_checkbox.py
fi

if $RUN_LIVE; then
    section "Selenium live scan  (nmap + eyewitness + CVEs)"
    pkill -f "nmap" 2>/dev/null || true
    pkill -f "eyewitness" 2>/dev/null || true
    rm -rf /tmp/legion/legion-* 2>/dev/null || true
    echo -e "  target: ${BOLD}$LIVE_TARGET${NC}  (~10 min — 6 nmap stages + NSE + eyewitness)"
    echo -e "  ${DIM}output is streamed live — each dot = 1 test passing${NC}"
    echo ""

    free_port 5099
    _live_name="test_selenium_ui (live scan)"
    _live_log=$(mktemp /tmp/legion-live-scan-XXXXXX.log)
    _live_t0=$(date +%s)

    # Run pytest with -v --tb=short so each test result prints immediately.
    # tee streams to terminal AND saves to log for summary parsing.
    sudo env LEGION_TEST_TARGET="$LIVE_TARGET" \
        python3 -m pytest tests/test_selenium_ui.py -m live \
        -v --tb=short --no-header 2>&1 | tee "$_live_log"
    _live_rc=${PIPESTATUS[0]}

    _live_secs=$(( $(date +%s) - _live_t0 ))
    _live_sl=$(grep -E "passed|failed|error" "$_live_log" | tail -1 || true)
    _live_p=$(_extract "$_live_sl" "passed")
    _live_f=$(_extract "$_live_sl" "failed")
    _live_s=$(echo "$_live_sl" | grep -oP '\d+(?= (skipped|deselected))' | head -1 || echo "0")
    rm -f "$_live_log"

    echo ""
    if [[ "$_live_rc" -eq 0 ]]; then
        print_result "$_live_name" "pass" "$_live_p" "$_live_f" "$_live_s" "$_live_secs"
    else
        print_result "$_live_name" "fail" "$_live_p" "$_live_f" "$_live_s" "$_live_secs"
    fi
fi

if $RUN_STORIES; then
    section "User Story Tests  (US-02–US-55, ports 5085/5086)"
    _us_start_servers

    # ── Offline user story tests ───────────────────────────────────────────────
    # Match-logic tests (Group 4) run FIRST while the process queue is empty.
    # US-02/US-03 submit 6+ nmap scans that fill the fast-process queue; the
    # printf commands in the match tests would time out if those scans are running.
    _SKIP_NOTE="pytest skipTest() stubs — implement or delete (see test_CriticalPaths.py)"
    run_pytest "user_stories - match+CSS logic" \
        tests/test_user_stories.py \
        -k "US44 or US45US46 or US31"

    # Brief pause so Firefox from the match-test run fully releases locks
    sleep 2

    # Everything else (scan-heavy tests run after match tests finish)
    # Exclude live-only classes that need LEGION_TEST_TARGET (US-09, US-39).
    _SKIP_NOTE="Live-only tests (US-09 nmap %, US-32 CVEs, US-39 screenshot) skipped — run with --all 192.168.85.11 to include them"
    run_pytest "user_stories (offline)" \
        tests/test_user_stories.py \
        -k "not NmapProgress and not ScreenshotTab and not US44 and not US45US46 and not US31"
    unset _SKIP_NOTE

    # ── Live user story tests ──────────────────────────────────────────────────
    if $RUN_LIVE; then
        # Kill existing Firefox instances so the driver can start cleanly
        pkill -f "firefox" 2>/dev/null || true; sleep 2

        # Reseed the server (may have been reset during offline run)
        python3 - <<'PYEOF' 2>/dev/null
import requests, tempfile, os
xml = '''<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/>
    <address addr="10.10.10.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
    </ports>
  </host>
</nmaprun>'''
with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
    f.write(xml); path = f.name
try:
    requests.post('http://127.0.0.1:5085/api/nmap/import-xml',
                  json={'path': path}, timeout=15)
finally:
    os.unlink(path)
PYEOF

        _us_live_name="user_stories (live: $LIVE_TARGET)"
        _us_live_t0=$(date +%s)
        spinner_start "$_us_live_name"
        _us_live_out=$(
            sudo env LEGION_TEST_TARGET="$LIVE_TARGET" \
                python3 -m pytest tests/test_user_stories.py \
                -k "NmapProgress or ScreenshotTab" \
                --tb=no -q 2>&1) || true
        spinner_stop
        _us_live_secs=$(( $(date +%s) - _us_live_t0 ))
        _us_live_sl=$(echo "$_us_live_out" | grep -E "passed|failed|error" | tail -1 || true)
        _us_live_p=$(_extract "$_us_live_sl" "passed")
        _us_live_f=$(_extract "$_us_live_sl" "failed")
        _us_live_s=$(echo "$_us_live_sl" | grep -oP '\d+(?= (skipped|deselected))' | head -1 || echo "0")
        if [[ "$_us_live_f" -eq 0 ]]; then
            print_result "$_us_live_name" "pass" "$_us_live_p" "$_us_live_f" "$_us_live_s" "$_us_live_secs"
        else
            print_result "$_us_live_name" "fail" "$_us_live_p" "$_us_live_f" "$_us_live_s" "$_us_live_secs"
            echo "$_us_live_out" | grep "^FAILED" | sed "s/^FAILED /      ${RED}FAILED${NC} /"
        fi
    fi

    # ── HTML reports ────────────────────────────────────────────────────────────
    if $GEN_REPORTS; then
        # Only generate reports when all tests passed (no point capturing failures)
        if [[ $SECTION_FAIL -eq 0 ]]; then
            pkill -f "firefox" 2>/dev/null || true; sleep 2
            # Drain background nmap/auto-tool queue so the report generators'
            # API calls don't block on DB locks held by running process threads.
            curl -s -X POST "http://127.0.0.1:${US_PORT_A}/api/processes/drain" \
                 -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
            curl -s -X POST "http://127.0.0.1:${US_PORT_B}/api/processes/drain" \
                 -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1
            sleep 2
            _gen_reports "${LIVE_TARGET:-}"
        else
            echo -e "  ${YELLOW}Skipping HTML reports — ${SECTION_FAIL} test(s) failed${NC}"
            echo -e "  ${DIM}Fix failures first, then run:${NC}"
            echo -e "  ${DIM}  sudo bash run_tests.sh --stories${NC}"
        fi
    fi

    _us_stop_servers
fi

# Print the last section's subtotal before the final summary
_section_subtotal
SECTION_PASS=0; SECTION_FAIL=0; SECTION_SKIP=0

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
echo -e "    ${BOLD}sudo bash run_tests.sh${NC}                         offline (unit+selenium+stories)"
echo -e "    ${BOLD}sudo bash run_tests.sh --unit${NC}                  unit only"
echo -e "    ${BOLD}sudo bash run_tests.sh --selenium${NC}              selenium offline only"
echo -e "    ${BOLD}sudo bash run_tests.sh --stories${NC}               user-story tests only"
echo -e "    ${BOLD}sudo bash run_tests.sh --live 192.168.85.11${NC}    live only"
echo -e "    ${BOLD}sudo bash run_tests.sh --all  192.168.85.11${NC}    everything + reports"
echo -e "    ${BOLD}sudo bash run_tests.sh --no-report${NC}             skip HTML report generation"
if $GEN_REPORTS && $RUN_STORIES; then
    echo -e "\n  ${CYAN}HTML reports:${NC} testreport/US*.html"
fi
echo -e "${CYAN}══════════════════════════════════════════════════════${NC}"
echo ""

[[ $GRAND_FAIL -eq 0 ]]
