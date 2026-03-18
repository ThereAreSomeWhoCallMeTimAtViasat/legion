# Legion Flask — Comprehensive Test Plan

**Generated:** 2026-03-18
**Version:** v7.4-flask
**Branch:** flask-clean

---

## Overview

Legion's test suite has **18 automated test files** covering **502 tests** across all layers.
All tests run with: `sudo python3 tests/<file>.py`
All must pass before any commit or server restart.

---

## Automated Test Files

### Core / Critical (run always before commit)

| File | Tests | Coverage |
|------|-------|----------|
| `test_behavioral.py` | 15 | Core import, scheduler, process lifecycle, WAL mode |
| `test_signal_chains.py` | 28 | Scheduler → chain → stage → XML import signal flow |
| `test_phase1_right_panel.py` | 27 | Right panel API routes (info, CVEs, scripts, services) |

### Flask Integration

| File | Tests | Coverage |
|------|-------|----------|
| `test_flask_integration.py` | 42 | All API endpoints: snapshot, processes, hosts, output |
| `test_routes_webcontroller.py` | 21 | Route → WebController wiring; runCommand, cancel, delete |
| `test_webcontroller.py` | 28 | WebController internal logic: queue, capture, match |
| `test_webcontroller_remaining.py` | 31 | Edge cases: staged nmap, duplicate check, screenshot dedup |

### UI / JS / CSS

| File | Tests | Coverage |
|------|-------|----------|
| `test_ui_wiring.py` | 42 | JS function presence, event wiring, DOM expectations |
| `test_ui_fixes.py` | 42 | Phase 2–5 UI fixes verified in JS/CSS source |
| `test_phase5_polish.py` | 20 | Polish fixes: scrolling, animations, tab indicators |

### Feature Phases

| File | Tests | Coverage |
|------|-------|----------|
| `test_phase1_settings.py` | 11 | Settings API: read, write, section handling |
| `test_phase2_auxiliary.py` | 8 | Aux methods: filters, getServiceNames, getOS |
| `test_phase2_interactions.py` | 23 | Host click, port right-click, tool tab close |
| `test_phase3_sorting.py` | 23 | Column sorting: hosts, processes, services |
| `test_phase4_state.py` | 29 | State restoration, filters, host lifecycle |

### Regression / v6–v7 Fixes

| File | Tests | Coverage |
|------|-------|----------|
| `test_v6_v7_fixes.py` | 34 | All v6.0–v7.4 server + JS fixes (see sections below) |
| `test_new_dialogs.py` | 55 | Add host dialog, modal focus, error handling |
| `test_visualupgrades_features.py` | 23 | Visual upgrade features: match banner, OS groups |

---

## v6–v7 Fix Test Coverage (test_v6_v7_fixes.py)

### L: Live Output (v6.2, v6.9)
- `L1.1` `_capture_output` creates `.live_output` temp file
- `L1.2` Temp file opened with `buffering=1` (line-buffered — flushes every newline)
- `L1.3` `/api/processes/<id>/output` reads live file before SQLite
- `L1.4` End-to-end: process output readable after run
- `L1.5` Temp file deleted after process finishes

### S: Snapshot Optimization (v6.5)
- `S1.1` Uses single SQL + `COUNT(*)`, NOT `getPortsByHostId()` N+1 ORM
- `S1.2` Calls `getProcesses` once (merged tools+processes)
- `S1.3` Response time logged (`_elapsed_ms`)
- `S1.4` Responds in <200ms

### P: Process Poll Timer (v6.4, v6.7, v6.8)
- `P1.1` `procPollTimer` survives `Waiting→Running` state transition
- `P1.2` `_startDynPoll` survives `Waiting→Running` transition
- `P1.3` Auto-select tracks `_prevRunningIds` for new process detection
- `P1.4` Auto-select skips click if process already selected (no poll restart)

### T: Tab Indicators (v6.7, v6.8, v7.0)
- `T1.1` `markTabUnread` always fires regardless of active state
- `T1.2` Orange indicator fires on first host discovery
- `T1.3` Information tab flashes all fields on first host load
- `T1.4` `handleMatch` uses `set` (deduplicates match patterns)
- `T1.5` Match banner shown in process output when match exists
- `T1.6` Snapshot processes include `match_text` field

### O: OS Tab (v6.3, v6.8)
- `O1.1` `_osListHash` gates re-renders (prevents cascade every 1.5s)
- `O1.2` `renderOsList` re-clicks selected OS after rebuild

### C: CSS Layout (v7.1, v7.2)
- `C1.1` `#dynamic-tabs-container` is `display:none` by default
- `C1.2` CSS `:has(.tab-content.active)` shows container only when needed
- `C1.3` `scrollTop` deferred via `setTimeout` for accurate bottom position

### N: NSE Options (v7.4)
- `N1.1` NSE stage uses `--min-parallelism`
- `N1.2` NSE stage uses `--script-timeout`

### R: Regression (8 tests)
- Snapshot 200, import works, scheduler runs, Phase 2–4 intact, output route responds, `os_groups` present

---

## Running All Tests

```bash
# Quick: 3 core suites (most critical)
sudo python3 tests/test_behavioral.py
sudo python3 tests/test_signal_chains.py
sudo python3 tests/test_phase1_right_panel.py

# Full suite (all 18 files, ~502 tests, ~90s)
for f in tests/test_*.py; do
  echo -n "$f: "
  sudo python3 $f 2>&1 | grep "^Results:"
done
```

---

## Manual Test Checklist

The following capabilities require a running server (`sudo python3 legion.py --web`).
Visit `http://127.0.0.1:5000`.

### Startup & Project
- [ ] App loads without error; version string shows in header
- [ ] `*untitled` project shown; no crash on startup
- [ ] Settings page loads (hamburger → Settings)

### Host Discovery (requires network)
- [ ] Add host dialog opens on `+` button; first input auto-focused
- [ ] Host appears in Hosts table after add
- [ ] IP is the key — no data from other hosts bleeds in

### Nmap Scanning
- [ ] Port scan launches on host; appears in Processes table with status `Running`
- [ ] Stage 1 (HTTP ports) output visible in real-time in upper output window
- [ ] Stage 2 (NSE) output appears continuously — NOT blocked during long script runs
- [ ] Stage 3–6 auto-chain after each XML import
- [ ] Process status transitions: `Waiting → Running → Finished`

### Process Output Display
- [ ] Clicking a process in the table loads output in upper panel
- [ ] Output scrolls to bottom automatically
- [ ] Auto-poll updates output every 2s while status = `Running`
- [ ] Poll keeps running through `Waiting → Running` transition (no stale blank panel)
- [ ] `Finished` status: one final load, then poll stops

### Tab Indicators (Orange)
- [ ] Host selected for first time: Information, Services, CVEs tabs turn orange
- [ ] Information tab: all fields flash green on first open
- [ ] Port change on existing host: relevant tabs turn orange
- [ ] Clicking orange tab clears the indicator

### Match Banner
- [ ] Process with match pattern shows highlighted banner at top of output
- [ ] No duplicate match lines (set dedup)
- [ ] No match → no banner shown

### OS Tab
- [ ] OS tab shows grouped OS names
- [ ] Clicking OS name filters hosts panel to that OS
- [ ] OS tab does not cause cascading re-renders every 1.5s poll
- [ ] Selecting OS then polling: host selection is preserved

### Dynamic Tool Tabs (right panel)
- [ ] Tool output tab opens on double-click host or tool name
- [ ] Tab auto-polls while process `Running`; stops on `Finished`
- [ ] Close `×` on tab removes it
- [ ] Multiple tool tabs open simultaneously — each shows own process output
- [ ] Upper output window visible when dynamic tab is active; hidden otherwise

### Column Sorting
- [ ] Hosts table: click IP, Hostname, OS, Status, Ports columns to sort
- [ ] Processes table: click Name, Host, Port, Status, Start columns to sort
- [ ] Services table: click Name, Port columns to sort
- [ ] Sort direction toggles (asc → desc → asc)

### Filters
- [ ] Status filter dropdown on Processes (Running / Finished / All)
- [ ] Port filter on Hosts panel (show open ports only)

### Screenshots (requires eyewitness at /usr/bin/eyewitness)
- [ ] HTTP host discovered → screenshooter queued automatically
- [ ] Screenshooter appears in Processes table
- [ ] Screenshot tab shows PNG image
- [ ] No duplicate screenshooter for same IP:port

### Import / Export
- [ ] File → Import Nmap XML imports hosts and ports
- [ ] Imported hosts appear in Hosts table
- [ ] Existing host data is merged, not duplicated

### Persistence
- [ ] Close browser, reopen: all hosts, ports, processes still present
- [ ] Notes survive session restart
- [ ] Process output readable after server restart (stored in SQLite)

---

## Performance Benchmarks

| Metric | Target | Measured by |
|--------|--------|-------------|
| Snapshot response | <200ms | S1.4 automated test |
| Host table render | <100ms | Browser DevTools |
| Process poll cycle | 2s interval | JS `setInterval` |
| Live output delay | <1s | L1.4 end-to-end test |
| Stage 2 (NSE/vulners) | ~150s for 20+ ports | inherent to vulners API |

---

## Known Limitations / Not Tested Automatically

- **NSE vulners slowness**: ~6.8s per port × N ports — inherent to vulners.com rate limiting. `--min-parallelism` and `--script-timeout` applied but do not reduce total time significantly.
- **eyewitness screenshots**: Requires `/usr/bin/eyewitness`. Tested manually only.
- **Qt6 GUI**: Not tested (replaced by Flask). Original `controller.py` must not be modified.
- **Multi-project**: Legion currently uses one active project. Multi-project not tested.

---

## Adding New Tests

All test files follow the same pattern:

```python
#!/usr/bin/env python3
import os, sys, traceback
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = FAIL = SKIP = 0

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        r = fn()
        if r is None or r is True:   PASS += 1; print(f"  \u2713 {name}"); return True
        elif r == 'SKIP':            SKIP += 1; print(f"  \u2298 {name} (SKIP)"); return False
        else:                        FAIL += 1; print(f"  \u2717 {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""): return True if v else f"FAIL: {msg}"

from app.web.testhelper import create_test_app
app, logic, wc = create_test_app()
client = app.test_client()

# ... your tests here ...

total = PASS + FAIL + SKIP
print(f"\n{'='*60}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
```
