# Legion Flask — Master Test Plan

**Version:** v9.7-flask
**Branch:** flask-clean
**Last updated:** 2026-03-19

This document is the single source of truth for what is tested, what is not tested,
and how every test is executed. It supersedes `TEST_PLAN.md`, `NEXT_TEST_PLAN.md`,
and `TERMINAL_TEST_PLAN.md`.

---

## Test Counts at a Glance

| Layer | Tests | Method |
|-------|-------|--------|
| Unit / API (no live target) | 627 passing, 7 skipped | Flask test client + source inspection |
| Unit / API (with LEGION_TEST_TARGET) | 634 passing | Same + T7 live terminal tests |
| Selenium offline | 178 | Headless Firefox via geckodriver |
| Selenium live scan | 19 | Headless Firefox + real nmap against 192.168.85.11 |
| **Total (offline)** | **805 passing, 7 skipped** | |
| **Total (with live VM)** | **831 passing** | |

All passing on `flask-clean` at v9.7-flask. The 7 "skipped" unit tests are T7.1–7.7
— they skip automatically when `LEGION_TEST_TARGET` is not set and pass when it is.

---

## How to Run Everything

```bash
# All unit tests (one line)
for f in tests/test_*.py; do echo -n "$f: "; sudo python3 $f 2>&1 | grep "^Results:" | tail -1; done

# Selenium offline suites (no network needed)
sudo python3 -m pytest tests/test_selenium_ui.py -v -m "not live"
sudo python3 -m pytest tests/test_selenium_project.py tests/test_selenium_multihost.py \
    tests/test_selenium_gaps.py tests/test_selenium_terminal.py -v

# Live terminal tests: SSH, MySQL, msfconsole against 192.168.85.11
sudo env LEGION_TEST_TARGET=192.168.85.11 python3 tests/test_terminal.py

# Selenium live scan (~4 min, requires VM at 192.168.85.11)
sudo rm -rf /tmp/legion/legion-*    # clear stale temp dirs
sudo env LEGION_TEST_TARGET=192.168.85.11 \
    python3 -m pytest tests/test_selenium_ui.py -v -m live

# Minimum sanity check (run before every server restart)
sudo python3 tests/test_behavioral.py
```

---

## Unit Test Files

| File | Tests | What It Covers |
|------|-------|----------------|
| `test_behavioral.py` | 15 | Core lifecycle: scheduler, WAL mode, process queue, ORM sessions |
| `test_signal_chains.py` | 28 | Nmap stage chain: stage1→6 signal flow, XML import, scheduler trigger |
| `test_phase1_right_panel.py` | 27 | Right panel API: info, CVEs, scripts, services per-host |
| `test_flask_integration.py` | 42 | All API endpoints: snapshot, processes, hosts, output, export |
| `test_routes_webcontroller.py` | 21 | Route→WebController wiring: runCommand, cancel, delete |
| `test_webcontroller.py` | 28 | WebController internals: queue, capture, match handling |
| `test_webcontroller_remaining.py` | 31 | Staged nmap, duplicate check, screenshot dedup |
| `test_ui_wiring.py` | 42 | JS function presence, event wiring, DOM structure |
| `test_ui_fixes.py` | 42 | Phase 2–5 UI fixes: live output, snapshot, poll timers, source inspection |
| `test_phase5_polish.py` | 20 | Scroll, animations, tab indicators |
| `test_phase1_settings.py` | 11 | Settings API: read, write, section handling |
| `test_phase2_auxiliary.py` | 8 | Auxiliary methods: filters, getServiceNames, getOS |
| `test_phase2_interactions.py` | 23 | Host click, port right-click, tab close |
| `test_phase3_sorting.py` | 23 | Column sorting: hosts, processes, services, ports |
| `test_phase4_state.py` | 29 | State restoration, filter persistence, host lifecycle |
| `test_v6_v7_fixes.py` | 34 | All v6.0–v8.x server and JS regressions |
| `test_new_dialogs.py` | 55 | Modals, dialog focus, autofocus, error handling |
| `test_visualupgrades_features.py` | 23 | Match banner, OS group snapshot |
| `test_api_gaps.py` | 45 | Save/open round-trip, notes, config syntax validation, host delete, kill/clear, input validation (P1–P8) |
| `test_multihost_isolation.py` | 14 | Ports, notes, processes, OS — per-host at API/DB level |
| `test_terminal.py` | 38+7 | PTY session lifecycle, interactive detection, port menus, snapshot integrity, keyboard (7 live skipped) |
| `test_gap_implementations.py` | 28 | Python script routing, dup check layer 2, file import, PostgreSQL adapter, ORDER BY whitelist |

---

## Selenium Test Files

| File | Tests | What It Covers |
|------|-------|----------------|
| `test_selenium_ui.py` | 92 offline + 19 live | Full UI: menus, modals, context menus, tabs, sorting, output, live scan |
| `test_selenium_project.py` | 12 | File→Save/Open via file browser modal, New clears project |
| `test_selenium_multihost.py` | 26 | UI isolation: ports, info, notes, dynamic tabs, OS tab, per-host |
| `test_selenium_gaps.py` | 32 | Host delete, port actions, process kill/retry/clear, filters, notes, resize, clipboard, host-checked, Ctrl+B |
| `test_selenium_terminal.py` | 16 | xterm.js in lower panel + upper panel, Open Terminal, independence |

---

## Capability Coverage Matrix

### Core Application Logic

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Nmap staged scan chain (6 stages) | ✅ | Unit: signal chain simulation | `test_signal_chains.py` |
| Nmap XML import → host/port storage | ✅ | Unit | `test_behavioral.py`, `test_phase1_right_panel.py` |
| Process queue: concurrency limits, dedup | ✅ | Unit | `test_webcontroller.py` |
| Process output capture (temp file, 5s flush) | ✅ | Unit: source + E2E | `test_v6_v7_fixes.py`, `test_api_gaps.py` |
| Scheduler: auto-run tools after scan | ✅ | Unit: signal chain | `test_signal_chains.py` |
| Duplicate check: process level (name+host+port) | ✅ | Unit | `test_webcontroller_remaining.py` |
| Duplicate check: script level (l1ScriptObj) | ✅ | Unit source inspection | `test_gap_implementations.py` |
| SQLite WAL mode enabled | ✅ | Unit: pragma check | `test_behavioral.py` |
| ORM session management (no detachment) | ✅ | Unit | `test_behavioral.py` |
| Screenshot deduplication (_screenshots_taken) | ✅ | Unit | `test_webcontroller_remaining.py` |
| Match detection (hydra credentials) | ✅ | Unit | `test_webcontroller.py`, `test_v6_v7_fixes.py` |
| nmap -oA flag appended for host actions | ✅ | Unit source inspection | `test_v6_v7_fixes.py` |

### Input Validation (Security)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Add Hosts: rejects XSS / special chars | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.1 |
| Add Hosts: accepts valid IP/CIDR | ✅ | Unit API (200 response) | `test_api_gaps.py` P8.2 |
| Add Hosts: accepts hostname | ✅ | Unit API (200 response) | `test_api_gaps.py` P8.3 |
| Add Hosts: rejects empty string | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.4 |
| Add Hosts: rejects semicolon injection | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.5 |
| Add Port: rejects non-numeric port | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.6 |
| Add Port: rejects port 0 | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.7 |
| Add Port: rejects port > 65535 | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.8 |
| Staged nmap port: rejects invalid chars | ✅ | Unit API (400 response) | `test_api_gaps.py` P8.9 |
| Staged nmap port: accepts valid expression | ✅ | Unit API (200 response) | `test_api_gaps.py` P8.10 |
| ORDER BY injection prevention (whitelist) | ✅ | Unit: whitelist check | `test_gap_implementations.py` G8.1–G8.4 |
| LIKE clause injection (sanitise()) | ✅ | Unit source inspection | `test_gap_implementations.py` G8.5 |

### Config Validation

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Valid config saves successfully | ✅ | Unit API | `test_api_gaps.py` P7.1 |
| Unclosed quote rejected (400) | ✅ | Unit API | `test_api_gaps.py` P7.2 |
| Wrong element count rejected (400) | ✅ | Unit API | `test_api_gaps.py` P7.3 |
| Unknown section name rejected (400) | ✅ | Unit API | `test_api_gaps.py` P7.4 |
| Unclosed section header rejected (400) | ✅ | Unit API | `test_api_gaps.py` P7.5 |
| Line without '=' rejected (400) | ✅ | Unit API | `test_api_gaps.py` P7.6 |
| Unknown key in [GeneralSettings] rejected | ✅ | Unit API | `test_api_gaps.py` P7.7 |
| Validation errors include line numbers | ✅ | Unit API | `test_api_gaps.py` P7.8 |
| Config save writes to disk / GET reads back | ✅ | Unit API | `test_api_gaps.py` P5.3 |

### Project Save / Open / New

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| save-as creates .legion file on disk | ✅ | Unit API | `test_api_gaps.py` P1.1–1.2 |
| save-as with missing path returns error | ✅ | Unit API | `test_api_gaps.py` P1.3 |
| new-temp empties hosts and processes | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| open restores hosts by IP | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| open restores ports for each host | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| open restores notes | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| open of nonexistent file returns error | ✅ | Unit API | `test_api_gaps.py` P3.6 |
| Two consecutive save/open cycles work | ✅ | Unit API | `test_api_gaps.py` P4.1 |
| File browser modal opens for Save | ✅ | Selenium | `test_selenium_project.py` |
| File browser modal opens for Open | ✅ | Selenium | `test_selenium_project.py` |
| Title bar shows project filename after save/open | ✅ | Selenium | `test_selenium_project.py` |
| Export JSON: 200, correct structure | ✅ | Unit API | `test_api_gaps.py` P6.1–6.8 |
| Export JSON download in browser | ❌ | Not automatable | Blob download inaccessible in headless Firefox |
| Notes persist across server restart | ❌ | Manual | Requires stop/restart server mid-test |
| Hosts persist across server restart | ❌ | Manual | Same reason |

### Text File Import (Gap #5)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Route exists (not 404) | ✅ | Unit API | `test_gap_implementations.py` G5.1 |
| JSON path import: 200 + status:ok | ✅ | Unit API | `test_gap_implementations.py` G5.2 |
| Imported hosts appear in snapshot | ✅ | Unit API | `test_gap_implementations.py` G5.3 |
| Comment lines (#) skipped | ✅ | Unit API | `test_gap_implementations.py` G5.4 |
| Empty lines skipped | ✅ | Unit API | `test_gap_implementations.py` G5.5 |
| Nonexistent file returns 404 | ✅ | Unit API | `test_gap_implementations.py` G5.6 |
| Missing path returns 400 | ✅ | Unit API | `test_gap_implementations.py` G5.7 |
| Multipart file upload works | ✅ | Unit API | `test_gap_implementations.py` G5.8 |
| Duplicate targets skipped | ✅ | Inherent (getHostInformation guard) | `cli_utils.import_targets_from_textfile` |
| File import UI button in web interface | ❌ | Not yet wired | No "Import from file" button in Add Hosts modal |

### Python Script Host Actions (Gap #3)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| macvendors.py exists | ✅ | Unit: file existence | `test_gap_implementations.py` G3.1 |
| pyShodan.py exists | ✅ | Unit: file existence | `test_gap_implementations.py` G3.2 |
| handleHostToolAction routes python-script-* | ✅ | Unit source inspection | `test_gap_implementations.py` G3.3 |
| pyShodan action builds python3 command | ✅ | Unit: mock capture | `test_gap_implementations.py` G3.4 |
| macvendors action builds python3 command | ✅ | Unit: mock capture | `test_gap_implementations.py` G3.5 |
| Unknown script name does not crash | ✅ | Unit | `test_gap_implementations.py` G3.6 |
| macvendors.py actually runs and returns vendor | ❌ | Needs network + MAC address | External API call to api.macvendors.com |
| pyShodan.py actually runs and returns data | ❌ | Needs Shodan API key + network | External API; key embedded in script |

### Database Adapters (Gap #6)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Default (no env var) uses SQLite | ✅ | Unit | `test_gap_implementations.py` G6.1 |
| Empty db_url uses SQLite | ✅ | Unit | `test_gap_implementations.py` G6.2 |
| LEGION_DB_URL env var routes to PostgreSQL | ✅ | Unit source inspection | `test_gap_implementations.py` G6.3 |
| postgresDbAdapter imports without NameError | ✅ | Unit import | `test_gap_implementations.py` G6.4 |
| postgresDbAdapter has correct interface | ✅ | Unit source inspection | `test_gap_implementations.py` G6.5 |
| postgresDbAdapter has no syntax errors | ✅ | Unit: ast.parse | `test_gap_implementations.py` G6.6 |
| Full PostgreSQL connection and queries | ❌ | Needs PostgreSQL server | No PostgreSQL installed in test environment |

### Multi-Host Data Isolation

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Ports are per-host (no bleed between hosts) | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Notes are per-host | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Processes are per-host | ✅ | Unit API | `test_multihost_isolation.py` |
| OS shown is per-host | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Dynamic tabs are per-host | ✅ | Selenium | `test_selenium_multihost.py` |
| Tab indicators are per-host | ✅ | Selenium | `test_selenium_multihost.py` |
| OS tab filters to correct host only | ✅ | Selenium | `test_selenium_multihost.py` |
| Notes blur race condition fixed | ✅ | Selenium | `test_selenium_multihost.py` |
| Writing note on A does not affect B | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |

### User Interface — Menus and Modals

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| File menu opens, all items visible | ✅ | Selenium | `test_selenium_ui.py` |
| Help menu opens, all items visible | ✅ | Selenium | `test_selenium_ui.py` |
| Keyboard shortcuts (Ctrl+H/I/S, F1/F2) | ✅ | Selenium | `test_selenium_ui.py` |
| Add Hosts modal: open/close/autofocus/submit | ✅ | Selenium | `test_selenium_ui.py` |
| Import Nmap modal: open/path/submit/close | ✅ | Selenium | `test_selenium_ui.py` |
| Config modal: open/save/profile/close | ✅ | Selenium | `test_selenium_ui.py` |
| Help modal: open/content/close | ✅ | Selenium | `test_selenium_ui.py` |
| Filters modal: opens, keyword filter works | ✅ | Selenium | `test_selenium_gaps.py` |
| Add Port modal: opens, port appears in Services | ✅ | Selenium | `test_selenium_gaps.py` |
| File browser modal (Save / Open) | ✅ | Selenium | `test_selenium_project.py` |
| Nmap Scan modal | ❌ | Not triggered | Modal HTML exists, no UI trigger button wired |
| Manual Tool Run modal | ❌ | Not triggered | Modal HTML exists, no UI trigger button wired |
| Scheduler settings | ❌ | Manual | Complex state, no automated test |

### User Interface — Host Actions

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Host right-click menu appears | ✅ | Selenium | `test_selenium_ui.py` |
| Host delete: confirm, row removed, DB cleared | ✅ | Selenium + Unit API | `test_selenium_gaps.py`, `test_api_gaps.py` |
| Host double-click copies IP to clipboard | ✅ | Selenium (JS intercept) | `test_selenium_gaps.py` |
| Mark as checked: CSS class applied | ✅ | Selenium | `test_selenium_gaps.py` |
| Mark as unchecked: class removed | ✅ | Selenium | `test_selenium_gaps.py` |
| Checked status in snapshot | ✅ | Selenium | `test_selenium_gaps.py` |
| Open Terminal creates Interactive process | ✅ | Selenium + Unit API | `test_selenium_terminal.py`, `test_terminal.py` |
| Host action python-script-* routes to real script | ✅ | Unit: mock capture | `test_gap_implementations.py` |
| Portscan submenu nmap actions import XML | ✅ | Unit source inspection | `test_v6_v7_fixes.py` |
| Add Port via host right-click menu | ❌ | Not in host menu | Feature tested via Add Port modal only |

### User Interface — Port Actions

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Port right-click menu appears with actions | ✅ | Selenium | `test_selenium_ui.py` |
| Port double-click switches left panel to Hosts | ✅ | Selenium | `test_selenium_gaps.py` |
| Send to Brute: tab switches, IP/port/service filled | ✅ | Selenium | `test_selenium_gaps.py` |
| [term] actions appear in port menu | ✅ | Unit API | `test_terminal.py` |
| [term] actions start terminal session | ✅ | Unit API + Selenium | `test_terminal.py`, `test_selenium_terminal.py` |
| Dynamic tab: right-click → Save Output / Close Tab | ✅ | Selenium | `test_selenium_ui.py` |
| Run custom nmap/nikto/etc. from port menu | ✅ (process starts) | Selenium confirms menu item exists + starts | `test_selenium_ui.py` |
| Actual tool output correct | ❌ | Manual or live | Requires network and open port |

### User Interface — Process Actions

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Process Kill: subprocess terminated | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_gaps.py` |
| Process Kill: status changes to Killed | ✅ | Selenium | `test_selenium_gaps.py` |
| Process Retry: new row appears | ✅ | Selenium | `test_selenium_gaps.py` |
| Process Retry of Interactive: new Interactive | ✅ | Unit API | `test_terminal.py` |
| Process Clear: row removed from view | ✅ | Selenium | `test_selenium_gaps.py` |
| Process Clear: closed=True in DB | ✅ | Unit API | `test_api_gaps.py` |
| Process output shows in lower panel | ✅ | Selenium | `test_selenium_ui.py` |
| Process output scrolls to bottom | ✅ | Selenium | `test_selenium_ui.py` |
| Process status filter (Running / All) | ✅ | Selenium | `test_selenium_ui.py` |
| Auto-select new Running/Interactive process | ✅ | Unit source inspection | `test_v6_v7_fixes.py` |
| Dynamic tab Save Output download | ❌ | Manual | Blob download not accessible in headless |

### User Interface — Notes

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Notes save to DB (same session) | ✅ | Unit API | `test_api_gaps.py` |
| Notes do not bleed between hosts | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Notes persist across host switch | ✅ | Selenium | `test_selenium_multihost.py` |
| Notes persist after project save/open | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| Ctrl+B appends selected text to Notes | ✅ | Selenium | `test_selenium_gaps.py` |
| Notes blur race condition fixed (_noteHostId) | ✅ | Selenium | `test_selenium_multihost.py` |
| Notes persist across server restart | ❌ | Manual | Requires stop/restart server mid-test |

### User Interface — Column Sorting and Resize

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Sort arrow appears on column header click | ✅ | Selenium | `test_selenium_ui.py` |
| Sort toggles direction on second click | ✅ | Selenium | `test_selenium_ui.py` |
| Hosts, Processes, Services, Ports all sort | ✅ | Selenium | `test_selenium_ui.py` |
| Column resize drag sets localStorage | ✅ | Selenium (ActionChains drag) | `test_selenium_gaps.py` |
| Resize persists after page reload | ✅ | Selenium | `test_selenium_gaps.py` |
| Column renders at saved width after reload | ✅ | Selenium | `test_selenium_gaps.py` |
| Resize handles not destroyed by sort updates | ✅ | Unit source (_setThText) | `test_v6_v7_fixes.py` |

### User Interface — Tabs and Indicators

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Left panel tabs switch correctly | ✅ | Selenium | `test_selenium_ui.py` |
| Right panel tabs switch correctly | ✅ | Selenium | `test_selenium_ui.py` |
| Orange tab-unread indicator applies | ✅ | Selenium | `test_selenium_ui.py` |
| Clicking tab clears orange indicator | ✅ | Selenium | `test_selenium_ui.py` |
| Orange indicators are per-host | ✅ | Selenium | `test_selenium_multihost.py` |
| OS tab lists both OS types | ✅ | Selenium | `test_selenium_multihost.py` |
| OS tab filters to correct host | ✅ | Selenium | `test_selenium_multihost.py` |
| OS list hash prevents cascade re-render | ✅ | Unit source + Selenium | `test_v6_v7_fixes.py`, `test_selenium_ui.py` |

### User Interface — Dynamic Tool Tabs

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Process creates dynamic tab in right panel | ✅ | Selenium | `test_selenium_ui.py` |
| Clicking dynamic tab shows output | ✅ | Selenium | `test_selenium_ui.py` |
| × closes dynamic tab | ✅ | Selenium | `test_selenium_ui.py` |
| Dynamic tabs only render for selected host | ✅ | Unit source inspection | `test_v6_v7_fixes.py` |
| Interactive process tab shows xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| Plain process tab shows text (not xterm.js) | ✅ | Selenium | `test_selenium_terminal.py` |
| Upper and lower panels are independent | ✅ | Selenium | `test_selenium_terminal.py` |

### Interactive Terminal (xterm.js PTY)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| PTY session starts with correct initial size (80×24) | ✅ | Unit API | `test_terminal.py` |
| Session appears as Interactive in snapshot | ✅ | Unit API | `test_terminal.py` |
| Bash prompt readable within 2s | ✅ | Unit API | `test_terminal.py` |
| Byte-correct offset (multi-byte UTF-8 safe) | ✅ | Unit API | `test_terminal.py` |
| Command dispatched to bash stdin after 500ms | ✅ | Unit API | `test_terminal.py` |
| Keystroke input via POST | ✅ | Unit API | `test_terminal.py` |
| Ctrl+C does not crash session | ✅ | Unit API | `test_terminal.py` |
| Resize sends TIOCSWINSZ to PTY | ✅ | Unit API | `test_terminal.py` |
| DELETE terminates bash, marks process Killed | ✅ | Unit API | `test_terminal.py` |
| Two sessions buffer independently | ✅ | Unit API | `test_terminal.py` |
| bash command → Interactive in runCommand | ✅ | Unit API | `test_terminal.py` |
| msfconsole command → Interactive | ✅ | Unit API | `test_terminal.py` |
| Interactive excluded from concurrency queue | ✅ | Unit API | `test_terminal.py` |
| Kill also cleans up terminal session map | ✅ | Unit API | `test_terminal.py` |
| Retry Interactive → new Interactive session | ✅ | Unit API | `test_terminal.py` |
| [term] port menu items: correct structure | ✅ | Unit API | `test_terminal.py` |
| session_id is valid UUID format | ✅ | Unit API | `test_terminal.py` |
| #plain-output / #terminal-output divs exist | ✅ | Selenium | `test_selenium_terminal.py` |
| Clicking Interactive row mounts xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| Clicking plain row shows text, not xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| Switching between plain and terminal rows | ✅ | Selenium | `test_selenium_terminal.py` |
| Open Terminal in host context menu | ✅ | Selenium | `test_selenium_terminal.py` |
| Open Terminal creates Interactive row | ✅ | Selenium | `test_selenium_terminal.py` |
| Upper dynamic tab mounts xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| msfconsole typing works (confirmed by user) | ✅ | Manual (confirmed) | — |
| Tab key completion | ✅ | Unit API (POST /input with \t) | `test_terminal.py` T6.1 |
| Arrow key command history | ✅ | Unit API (POST /input with \x1b[A) | `test_terminal.py` T6.2 |
| Ctrl+C interrupts running command | ✅ | Unit API (POST /input with \x03) | `test_terminal.py` T6.3 |
| Ctrl+D exits subshell | ✅ | Unit API (POST /input with \x04) | `test_terminal.py` T6.4 |
| Terminal resize updates dimensions (stty) | ✅ | Unit API (POST /resize) | `test_terminal.py` T6.5 |
| Ctrl+L clears screen | ✅ | Unit API (POST /input with \x0c) | `test_terminal.py` T6.6 |
| SSH connects + authenticates (msfadmin) | ✅ | Live terminal API (LEGION_TEST_TARGET) | `test_terminal.py` T7.1 |
| SSH shell executes whoami → msfadmin | ✅ | Live terminal API | `test_terminal.py` T7.2 |
| MySQL connects as root (no password) | ✅ | Live terminal API (LEGION_TEST_TARGET) | `test_terminal.py` T7.3 |
| MySQL SELECT VERSION() returns version | ✅ | Live terminal API | `test_terminal.py` T7.4 |
| msfconsole starts and shows msf6 prompt | ✅ | Live terminal API (LEGION_TEST_TARGET) | `test_terminal.py` T7.5 |
| vsftpd exploit runs, shows session output | ✅ | Live terminal API | `test_terminal.py` T7.6 |
| msfconsole sessions command works | ✅ | Live terminal API | `test_terminal.py` T7.7 |
| Terminal resize on browser window resize | ❌ | Manual only | Visual verification required |
| ANSI colour rendering | ❌ | Manual only | Canvas pixel comparison not implemented |
| msfconsole 10-second Interactive delay | ❌ | Manual only | Timing-sensitive |
| netcat session | ❌ | Manual only | Requires real listener |
| Clipboard paste into terminal | ❌ | Manual only | Browser security blocks headless clipboard |

### Live Network Scan (192.168.85.11)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Add host via Add Hosts modal | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Host row appears in table within 20s | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Scan process starts (Running / Waiting) | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Process output visible during scan | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Stage 1 completes within 120s | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Ports discovered (port 80 confirmed) | ✅ | Selenium (live) | `test_selenium_ui.py` |
| All 6 nmap stages complete within 900s | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Information tab populated after scan | ✅ | Selenium (live) | `test_selenium_ui.py` |
| OS field populated | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Eyewitness screenshooter runs for HTTP ports | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Screenshot PNG loads (naturalWidth > 0) | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Screenshot modal opens on image click | ✅ | Selenium (live) | `test_selenium_ui.py` |
| CVEs tab has rows after NSE stage | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Scripts tab has rows after scan | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Script row click shows inline output | ✅ | Selenium (live) | `test_selenium_ui.py` |
| No duplicate screenshooter processes | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Orange tab indicator mechanism fires | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Screenshot image shows correct web page | ❌ | Manual | PNG loads confirmed; content requires visual |
| Hydra brute-force + credential extraction | ❌ | Manual | Needs vulnerable target with weak creds |
| IPv6 host scanning | ❌ | Manual | No IPv6 test network |
| Hard / FIN / NULL / Xmas nmap modes | ❌ | Manual | No automated verification of flags used |
| unicornscan results import | ❌ | Manual | Not nmap; no XML output to import |

### Snapshot and API Performance

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Snapshot responds < 500ms | ✅ | Selenium | `test_selenium_ui.py` |
| Snapshot uses single SQL (not N+1 ORM) | ✅ | Unit source inspection | `test_v6_v7_fixes.py` |
| Snapshot includes os_groups | ✅ | Selenium | `test_selenium_ui.py` |
| Snapshot includes session_id per process | ✅ | Unit API | `test_terminal.py` |

---

## What Is NOT Tested — Summary

### Requires live VM (automated when LEGION_TEST_TARGET is set)

These run as part of `test_terminal.py` T7 tests when `LEGION_TEST_TARGET=192.168.85.11`
is set. They are skipped (not failed) when the env var is absent.

| Item | Test | Run command |
|------|------|-------------|
| SSH login + shell command (whoami) | T7.1, T7.2 | `sudo env LEGION_TEST_TARGET=192.168.85.11 python3 tests/test_terminal.py` |
| MySQL connect + SELECT VERSION() | T7.3, T7.4 | Same |
| msfconsole vsftpd exploit + sessions | T7.5, T7.6, T7.7 | Same |

### Requires live external services (no substitute)

| Item | Reason not automated |
|------|---------------------|
| Run Hydra (real brute-force) | Needs vulnerable target with weak creds |
| netcat session | Needs real listener on target |
| macvendors.py real API lookup | External HTTPS call to api.macvendors.com; host MAC rarely populated |
| pyShodan.py real lookup | Shodan API key + external network |
| Full PostgreSQL connection | No PostgreSQL server in test env |
| IPv6 scanning | No IPv6 test network |

### Requires visual inspection

| Item | Reason not automated |
|------|---------------------|
| Screenshot shows correct web page | PNG loads confirmed; content requires human eye |
| ANSI colour rendering in terminal | Canvas pixel comparison not implemented |
| Terminal resize reflows correctly | Visual verification required |
| Export JSON file saves to user's download folder | Blob download inaccessible in headless |

### Requires server restart

| Item | How to verify manually |
|------|----------------------|
| Notes survive restart | Add note → stop server → start server → confirm note present |
| Hosts survive restart | Same pattern |
| Process output readable after restart | Run process → restart → check output via API |

### Features not yet wired in UI

| Item | Status |
|------|--------|
| Import from file button in Add Hosts modal | API endpoint exists; no UI button |
| Nmap Scan modal trigger | Modal HTML exists; no button to open it |
| Manual Tool Run modal trigger | Modal HTML exists; no button to open it |
| CSV export | Stub returns "not yet implemented" |

---

## Manual Verification Checklist

Run after any significant code change or before release:

```
sudo python3 /home/kali/Downloads/legion/legion.py --web > /tmp/legion-web.log 2>&1 &
open http://127.0.0.1:5000
```

### Core scan workflow
- [ ] Add host → staged scan starts → all 6 stages complete
- [ ] Information tab shows host IP, OS after scan
- [ ] CVEs tab has rows after NSE stage (vulners.nse)
- [ ] Scripts tab has rows; clicking a row shows script output
- [ ] Screenshooter runs for HTTP ports → screenshot visible in dynamic tab
- [ ] Clicking screenshot thumbnail opens full-size modal

### Project persistence
- [ ] File → Save → file created at shown path
- [ ] File → New → hosts table empty
- [ ] File → Open → hosts, ports, notes all restored
- [ ] Restart server → all data still present

### Terminal
- [ ] Right-click host → Open Terminal → xterm.js fills lower panel, full-width, typing works
- [ ] Right-click FTP port → vsftpd234-Meta → `msf6 >` prompt appears in lower panel
- [ ] Type `sessions` → response shown
- [ ] Right-click SSH port (if open) → SSH prompt appears, can log in
- [ ] Tab completion, arrow key history, Ctrl+C all work

### UI actions
- [ ] Host right-click → Delete → confirm → row gone from table, absent from DB
- [ ] Host double-click → IP copied to clipboard (paste to confirm)
- [ ] Port right-click → Send to Brute → Brute tab opens with IP/port/service pre-filled
- [ ] Process right-click → Kill → status changes to Killed
- [ ] Process right-click → Retry → new row appears
- [ ] Dynamic tab right-click → Save Output → .txt file downloads
- [ ] Filters modal → keyword filter → only matching hosts shown → clear → all restored
- [ ] Column resize → drag handle → reload page → column at same width
- [ ] F2 → Config modal → edit staging ports → save → no error

---

## Known Limitations

| Limitation | Impact |
|-----------|--------|
| NSE/vulners takes ~6.8s/port | Stage 2 is 2–3 min; cannot be reduced without skipping CVE detection |
| eyewitness required at /usr/bin/eyewitness | Screenshot tests skip if not installed |
| Live tests require 192.168.85.11 to be reachable | All 19 live tests fail if VM is down |
| xterm.js served from CDN | Headless tests skip canvas check if CDN unreachable |
| /tmp/legion/ accumulates | Run `sudo rm -rf /tmp/legion/legion-*` before live test runs |
| Orphaned nmap/eyewitness processes | live_target fixture kills stray PIDs; still possible if VM disconnects mid-scan |
| One active project at a time | Multi-project switching not tested |
| Qt6 GUI completely replaced | Original controller.py is DO NOT MODIFY; Flask is the sole interface |
