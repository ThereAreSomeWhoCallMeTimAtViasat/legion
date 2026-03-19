# Legion Flask — Master Test Plan

**Version:** v9.1-flask
**Branch:** flask-clean
**Total tests:** 804 all passing
**Last updated:** 2026-03-19

This document is the single source of truth for what is tested, how it is tested,
and what requires manual verification. It supersedes TEST_PLAN.md, NEXT_TEST_PLAN.md,
and TERMINAL_TEST_PLAN.md.

---

## How to Run Everything

```bash
# All unit tests
for f in tests/test_*.py; do echo -n "$f: "; sudo python3 $f 2>&1 | grep "^Results:"; done

# Selenium offline (no network, ~2 min)
sudo python3 -m pytest tests/test_selenium_ui.py -v -m "not live"
sudo python3 -m pytest tests/test_selenium_project.py tests/test_selenium_multihost.py \
    tests/test_selenium_gaps.py tests/test_selenium_terminal.py -v

# Selenium live scan (~4 min, requires VM)
sudo rm -rf /tmp/legion/legion-*   # clean stale temp dirs first
sudo env LEGION_TEST_TARGET=192.168.85.11 python3 -m pytest tests/test_selenium_ui.py -v -m live
```

---

## Test Suite Summary

| File | Tests | Method | What It Covers |
|------|-------|--------|---------------|
| `test_behavioral.py` | 15 | Unit (Flask test client) | Core lifecycle: scheduler, WAL mode, process queue, DB sessions |
| `test_signal_chains.py` | 28 | Unit | Nmap stage chain: stage1→2→3→4→5→6 signal flow, XML import |
| `test_phase1_right_panel.py` | 27 | Unit | Right panel API routes: info, CVEs, scripts, services per-host |
| `test_flask_integration.py` | 42 | Unit | All API endpoints: snapshot, processes, hosts, output |
| `test_routes_webcontroller.py` | 21 | Unit | Route→WebController wiring: runCommand, cancel, delete |
| `test_webcontroller.py` | 28 | Unit | WebController internals: queue, capture, match handling |
| `test_webcontroller_remaining.py` | 31 | Unit | Staged nmap, duplicate check, screenshot dedup |
| `test_ui_wiring.py` | 42 | Unit (JS source) | JS function presence, event wiring, DOM structure |
| `test_ui_fixes.py` | 42 | Unit (JS/CSS source) | Phase 2–5 UI fixes: live output, snapshot N+1, poll timers |
| `test_phase5_polish.py` | 20 | Unit (JS/CSS source) | Scroll, animations, tab indicators |
| `test_phase1_settings.py` | 11 | Unit | Settings API: read, write, section handling |
| `test_phase2_auxiliary.py` | 8 | Unit | Aux methods: filters, getServiceNames, getOS |
| `test_phase2_interactions.py` | 23 | Unit | Host click, port right-click, tab close |
| `test_phase3_sorting.py` | 23 | Unit | Column sorting: hosts, processes, services |
| `test_phase4_state.py` | 29 | Unit | State restoration, filters, host lifecycle |
| `test_v6_v7_fixes.py` | 34 | Unit | All v6.0–v8.x server + JS regressions |
| `test_new_dialogs.py` | 55 | Unit | Modals, dialog focus, error handling |
| `test_visualupgrades_features.py` | 23 | Unit | Match banner, OS groups |
| `test_api_gaps.py` | 19 | Unit (Flask test client) | Save/open round-trip, notes, config save, host delete, kill/clear |
| `test_multihost_isolation.py` | 14 | Unit | Ports, notes, processes, OS — all per-host at API level |
| `test_terminal.py` | 32 | Unit | PTY session lifecycle, interactive detection, port menus, snapshot integrity |
| `test_selenium_ui.py` | 92+19 | Selenium (headless) | Full UI: menus, modals, context menus, tabs, sorting, output, live scan |
| `test_selenium_project.py` | 12 | Selenium (headless) | File→Save/Open via file browser modal, New clears project |
| `test_selenium_multihost.py` | 26 | Selenium (headless) | UI isolation: ports, info, notes, dynamic tabs, OS tab per-host |
| `test_selenium_gaps.py` | 32 | Selenium (headless) | Host delete, port actions, process kill/retry/clear, filters, notes, resize, clipboard, checked, Ctrl+B |
| `test_selenium_terminal.py` | 16 | Selenium (headless) | xterm.js lower panel, xterm.js upper panel, Open Terminal, independence |

---

## What Is Tested and How

### Core Application Logic

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Nmap staged scan chain (6 stages) | ✅ | Unit: signal chain simulation | `test_signal_chains.py` |
| Nmap XML import and host/port storage | ✅ | Unit | `test_behavioral.py`, `test_phase1_right_panel.py` |
| Process queue: concurrency limits, dedup | ✅ | Unit | `test_webcontroller.py` |
| Process output capture (buffering=1, temp file) | ✅ | Unit: source inspection + E2E | `test_v6_v7_fixes.py`, `test_api_gaps.py` |
| Scheduler: auto-run tools after scan | ✅ | Unit: signal chain | `test_signal_chains.py` |
| SQLite WAL mode enabled | ✅ | Unit: pragma check | `test_behavioral.py` |
| ORM session management (no detachment) | ✅ | Unit | `test_behavioral.py` |
| Screenshot deduplication | ✅ | Unit | `test_webcontroller_remaining.py` |
| Match detection and deduplication | ✅ | Unit | `test_webcontroller.py`, `test_v6_v7_fixes.py` |

### Project Save / Open / New

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Save project creates .legion file on disk | ✅ | Unit API | `test_api_gaps.py` |
| New project empties hosts + processes | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| Open restores hosts by IP | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| Open restores ports for each host | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| Open restores notes | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| Two consecutive save/open cycles work | ✅ | Unit API | `test_api_gaps.py` |
| File browser modal opens for Save | ✅ | Selenium | `test_selenium_project.py` |
| File browser modal opens for Open | ✅ | Selenium | `test_selenium_project.py` |
| Title bar shows project filename | ✅ | Selenium | `test_selenium_project.py` |
| File → Export JSON (server-side content) | ✅ | Unit API | `test_api_gaps.py` |
| File → Export JSON download in browser | ❌ | Cannot automate | Blob download not accessible in headless |

### Multi-Host Data Isolation

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Ports are per-host (no bleed) | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Notes are per-host | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Processes are per-host | ✅ | Unit API | `test_multihost_isolation.py` |
| OS shown is per-host | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Dynamic tabs are per-host | ✅ | Selenium | `test_selenium_multihost.py` |
| Tab indicators are per-host | ✅ | Selenium | `test_selenium_multihost.py` |
| OS tab filters to correct host | ✅ | Selenium | `test_selenium_multihost.py` |
| Notes blur race condition fixed | ✅ | Selenium | `test_selenium_multihost.py` |

### User Interface — Menus and Modals

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| File menu opens, all items visible | ✅ | Selenium | `test_selenium_ui.py` |
| Help menu opens, all items visible | ✅ | Selenium | `test_selenium_ui.py` |
| Keyboard shortcuts (Ctrl+H/I/S, F1/F2) | ✅ | Selenium | `test_selenium_ui.py` |
| Add Hosts modal: open/close/autofocus/submit | ✅ | Selenium | `test_selenium_ui.py` |
| Import Nmap modal: open/path/submit/close | ✅ | Selenium | `test_selenium_ui.py` |
| Config modal: open/save button/profile/close | ✅ | Selenium | `test_selenium_ui.py` |
| Help modal: open/content/close | ✅ | Selenium | `test_selenium_ui.py` |
| Filters modal: opens, keyword filter hides hosts | ✅ | Selenium | `test_selenium_gaps.py` |
| Add Port modal: opens, port 9999 added to Services | ✅ | Selenium | `test_selenium_gaps.py` |
| File browser modal (Save/Open) | ✅ | Selenium | `test_selenium_project.py` |
| Nmap Scan modal | ❌ | Not wired | Modal exists but no trigger button |
| Manual Tool Run modal | ❌ | Not wired | Modal exists but no trigger button |
| Scheduler settings modal | ❌ | Manual | Complex state, no automated test |
| Provider logs modal | ❌ | Manual | No automated test |

### User Interface — Host Actions

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Host right-click menu appears | ✅ | Selenium | `test_selenium_ui.py` |
| Host delete: confirm dialog, row removed, DB cleared | ✅ | Selenium + Unit | `test_selenium_gaps.py`, `test_api_gaps.py` |
| Host double-click copies IP to clipboard | ✅ | Selenium (JS clipboard intercept) | `test_selenium_gaps.py` |
| Mark as checked: host-checked CSS class | ✅ | Selenium | `test_selenium_gaps.py` |
| Mark as unchecked: class removed | ✅ | Selenium | `test_selenium_gaps.py` |
| Open Terminal: Interactive process created | ✅ | Selenium + Unit | `test_selenium_terminal.py`, `test_terminal.py` |
| Checked indicator in snapshot | ✅ | Selenium | `test_selenium_gaps.py` |
| Add port via host right-click context | ❌ | Not in menu | "Add Port" not in host context menu |

### User Interface — Port Actions

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Port right-click menu appears | ✅ | Selenium | `test_selenium_ui.py` |
| Port right-click menu has actions | ✅ | Selenium | `test_selenium_ui.py` |
| Port double-click switches to Hosts tab | ✅ | Selenium | `test_selenium_gaps.py` |
| Send to Brute: tab switches, fields filled | ✅ | Selenium | `test_selenium_gaps.py` |
| [term] actions appear in port menu | ✅ | Unit API | `test_terminal.py` |
| [term] actions start terminal session | ✅ | Unit API + Selenium | `test_terminal.py`, `test_selenium_terminal.py` |
| Dynamic tab right-click: Save Output/Close Tab | ✅ | Selenium | `test_selenium_ui.py` |

### User Interface — Process Actions

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Process Kill: status changes, subprocess terminated | ✅ | Selenium + Unit | `test_selenium_gaps.py`, `test_api_gaps.py` |
| Process Retry: new row appears | ✅ | Selenium | `test_selenium_gaps.py` |
| Process Retry of Interactive: stays Interactive | ✅ | Unit | `test_terminal.py` |
| Process Clear: row removed from table | ✅ | Selenium | `test_selenium_gaps.py` |
| Process output shows in lower panel | ✅ | Selenium | `test_selenium_ui.py` |
| Process output scrolls to bottom | ✅ | Selenium | `test_selenium_ui.py` |
| Process status filter (Running/All) | ✅ | Selenium | `test_selenium_ui.py` |
| Auto-select new Running/Interactive process row | ✅ | Unit (JS source) | `test_v6_v7_fixes.py` |

### User Interface — Notes

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Notes save to DB (same session) | ✅ | Unit API | `test_api_gaps.py` |
| Notes don't bleed between hosts | ✅ | Unit API + Selenium | `test_multihost_isolation.py`, `test_selenium_multihost.py` |
| Notes persist across host switch | ✅ | Selenium | `test_selenium_multihost.py` |
| Notes persist after project save/open | ✅ | Unit API + Selenium | `test_api_gaps.py`, `test_selenium_project.py` |
| Ctrl+B appends selection to Notes tab | ✅ | Selenium (programmatic selection) | `test_selenium_gaps.py` |
| Notes blur race condition (_noteHostId fix) | ✅ | Selenium | `test_selenium_multihost.py` |
| Notes persist across server restart | ❌ | Manual | Requires stop/restart server in test |

### User Interface — Column Sorting and Resize

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Column sort arrow appears on click | ✅ | Selenium | `test_selenium_ui.py` |
| Sort toggles direction on second click | ✅ | Selenium | `test_selenium_ui.py` |
| Hosts, Processes, Services, Ports tables all sort | ✅ | Selenium | `test_selenium_ui.py` |
| Column resize sets localStorage | ✅ | Selenium (drag simulation) | `test_selenium_gaps.py` |
| Resize persists after page reload | ✅ | Selenium | `test_selenium_gaps.py` |
| Column rendered at saved width after reload | ✅ | Selenium | `test_selenium_gaps.py` |

### User Interface — Tabs and Indicators

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Left panel tabs switch correctly | ✅ | Selenium | `test_selenium_ui.py` |
| Right panel tabs switch correctly | ✅ | Selenium | `test_selenium_ui.py` |
| Orange tab-unread indicator applies | ✅ | Selenium | `test_selenium_ui.py` |
| Clicking tab clears orange indicator | ✅ | Selenium | `test_selenium_ui.py` |
| Orange indicators are per-host | ✅ | Selenium | `test_selenium_multihost.py` |
| OS tab groups both OS types | ✅ | Selenium | `test_selenium_multihost.py` |
| OS tab filters to correct host | ✅ | Selenium | `test_selenium_multihost.py` |
| OS list hash prevents cascade re-render | ✅ | Unit (JS source) + Selenium | `test_v6_v7_fixes.py`, `test_selenium_ui.py` |

### User Interface — Dynamic Tool Tabs (upper right panel)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Process creates dynamic tab | ✅ | Selenium | `test_selenium_ui.py` |
| Clicking dynamic tab shows output | ✅ | Selenium | `test_selenium_ui.py` |
| × closes dynamic tab | ✅ | Selenium | `test_selenium_ui.py` |
| Dynamic tabs only render for selected host | ✅ | Unit (JS source) | `test_v6_v7_fixes.py` |
| Interactive process tab shows xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| Plain process tab shows plain text | ✅ | Selenium | `test_selenium_terminal.py` |
| Upper and lower output panels are independent | ✅ | Selenium | `test_selenium_terminal.py` |

### Interactive Terminal (xterm.js)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| PTY session starts (bash with initial size) | ✅ | Unit API | `test_terminal.py` |
| Session appears as Interactive in snapshot | ✅ | Unit API | `test_terminal.py` |
| Output readable within 2s (bash prompt) | ✅ | Unit API | `test_terminal.py` |
| Byte-correct offset (handles multi-byte UTF-8) | ✅ | Unit API | `test_terminal.py` |
| Command dispatched to bash after 500ms | ✅ | Unit API | `test_terminal.py` |
| Input (keystrokes) sent via POST | ✅ | Unit API | `test_terminal.py` |
| Ctrl+C does not crash session | ✅ | Unit API | `test_terminal.py` |
| Resize sends TIOCSWINSZ | ✅ | Unit API | `test_terminal.py` |
| DELETE terminates process, marks Killed | ✅ | Unit API | `test_terminal.py` |
| Two sessions are independent | ✅ | Unit API | `test_terminal.py` |
| bash command → Interactive in runCommand | ✅ | Unit API | `test_terminal.py` |
| msfconsole command → Interactive | ✅ | Unit API | `test_terminal.py` |
| Interactive excluded from process queue | ✅ | Unit API | `test_terminal.py` |
| Kill also cleans up terminal session | ✅ | Unit API | `test_terminal.py` |
| Retry Interactive → new Interactive | ✅ | Unit API | `test_terminal.py` |
| [term] port menu items exist and have correct structure | ✅ | Unit API | `test_terminal.py` |
| [term] command dispatched correctly | ✅ | Unit API | `test_terminal.py` |
| session_id UUID format | ✅ | Unit API | `test_terminal.py` |
| #plain-output / #terminal-output divs exist | ✅ | Selenium | `test_selenium_terminal.py` |
| Clicking Interactive row shows xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| Clicking plain row shows text (not xterm.js) | ✅ | Selenium | `test_selenium_terminal.py` |
| Switching between plain and terminal rows | ✅ | Selenium | `test_selenium_terminal.py` |
| Open Terminal in host menu | ✅ | Selenium | `test_selenium_terminal.py` |
| Open Terminal creates Interactive row | ✅ | Selenium | `test_selenium_terminal.py` |
| Upper dynamic tab mounts xterm.js | ✅ | Selenium | `test_selenium_terminal.py` |
| msfconsole typing works (no echo corruption) | ✅ | Manual (confirmed by user) | — |
| SSH session fully interactive | ❌ | Manual only | Needs real SSH service |
| mysql/psql/netcat sessions | ❌ | Manual only | Needs real listening services |
| msfconsole exploit + sessions command | ❌ | Manual only | Needs vulnerable target |
| Tab completion (Tab key) | ❌ | Manual only | Keyboard events unreliable in headless |
| Arrow key command history | ❌ | Manual only | Same reason |
| Ctrl+D logout | ❌ | Manual only | Same reason |
| Terminal resize on window resize | ❌ | Manual only | Visual verification needed |
| ANSI colour rendering | ❌ | Manual only | Canvas pixel comparison not implemented |
| msfconsole 10-second Interactive delay | ❌ | Manual only | Timing-sensitive |

### Live Network Scan (against 192.168.85.11)

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Add host via Add Hosts modal | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Host row appears in table | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Scan process starts (Running/Waiting) | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Process output visible during scan | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Stage 1 (HTTP ports) completes | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Ports discovered (port 80 confirmed) | ✅ | Selenium (live) | `test_selenium_ui.py` |
| All 6 nmap stages complete | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Information tab populated after scan | ✅ | Selenium (live) | `test_selenium_ui.py` |
| OS field populated | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Eyewitness screenshooter runs for HTTP | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Screenshot PNG loads in dynamic tab | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Screenshot modal opens on image click | ✅ | Selenium (live) | `test_selenium_ui.py` |
| CVEs populated after NSE stage | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Scripts tab has rows after scan | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Script row click shows inline output | ✅ | Selenium (live) | `test_selenium_ui.py` |
| No duplicate screenshooters per port | ✅ | Selenium (live) | `test_selenium_ui.py` |
| Orange tab indicators fire | ✅ | Selenium (live) | `test_selenium_ui.py` |
| IPv6 scanning | ❌ | Manual | No IPv6 test network |
| Custom nmap modes (Hard, FIN, etc.) | ❌ | Manual | No automated verification |
| Hydra brute-force | ❌ | Manual | Needs vulnerable target |

### Snapshot and API Performance

| Capability | Tested? | Method | Test File |
|-----------|---------|--------|-----------|
| Snapshot responds < 500ms | ✅ | Selenium | `test_selenium_ui.py` |
| Snapshot uses single SQL (not N+1 ORM) | ✅ | Unit (source) | `test_v6_v7_fixes.py` |
| Snapshot includes os_groups | ✅ | Selenium | `test_selenium_ui.py` |
| Snapshot includes session_id per process | ✅ | Unit API | `test_terminal.py` |

---

## What Is NOT Tested (Manual Only)

### Requires real external tools or network

| Item | How to test manually |
|------|---------------------|
| **Run Hydra** | Brute tab: fill IP/port/wordlists → Run Hydra → process appears, credentials extracted |
| **SSH interactive session** | Right-click SSH port → "Open with ssh client" → type commands, verify responses |
| **mysql/psql client** | Right-click mysql/postgres port → open with client → run SQL queries |
| **msfconsole exploit + sessions** | Right-click FTP port → vsftpd234-Meta → wait for exploit → type `sessions` |
| **IPv6 scan** | Add an IPv6 host → scan → verify ports discovered |
| **Custom nmap modes** | Config: set Hard mode → scan → verify nmap flags used |
| **Eyewitness image content** | Verify screenshot shows correct web page (PNG loads is tested, content is not) |

### Requires keyboard/visual interaction

| Item | How to test manually |
|------|---------------------|
| **Tab completion in terminal** | Open Terminal → type `ls /us` → Tab → `/usr/` should complete |
| **Arrow key history** | Run command in terminal → press ↑ → previous command appears |
| **Ctrl+C interrupt** | `sleep 100` → Ctrl+C → `^C` shown, new prompt |
| **Ctrl+D logout** | Empty prompt → Ctrl+D → session closes |
| **Terminal resize** | Drag browser window → xterm.js reflows to fill |
| **ANSI colours** | `ls --color` → verify colours rendered |
| **Paste into terminal** | Ctrl+V → clipboard text pasted |
| **File → Export JSON download** | Click Export JSON → file downloads to disk with correct content |

### Requires server restart

| Item | How to test manually |
|------|---------------------|
| **Notes survive restart** | Add note → restart server → note still present |
| **Hosts survive restart** | Add host → restart server → host still in table |
| **Process output after restart** | Run process → restart → output still readable |

### Not implemented (features incomplete in UI)

| Item | Status |
|------|--------|
| **Nmap Scan modal** | Modal HTML exists, no trigger button wired |
| **Manual Tool Run modal** | Modal HTML exists, no trigger button wired |
| **Scheduler settings modal** | Accessible via config but complex state, no test |
| **Add Port via host right-click** | Not in host context menu |
| **CVE row click → detail** | No click handler on CVE rows |

---

## Manual Verification Checklist

Run after any significant code change:

```
SERVER: sudo python3 legion.py --web > /tmp/legion-web.log 2>&1 &
OPEN: http://127.0.0.1:5000
```

### Core workflow
- [ ] Add host → scan starts → ports discovered → all 6 stages complete
- [ ] Information tab shows host data after scan
- [ ] CVEs tab shows CVE data after NSE stage
- [ ] Scripts tab shows nmap script output

### Project persistence
- [ ] File → Save → confirm file created
- [ ] File → New → hosts table empty
- [ ] File → Open → hosts, ports, notes all restored
- [ ] Restart server → all data still present

### Terminal
- [ ] Right-click host → Open Terminal → xterm.js appears in lower panel, full-width, typing works
- [ ] Right-click FTP port → vsftpd234-Meta → msfconsole starts, `msf6 >` prompt appears
- [ ] Type `sessions` in msfconsole → response shown
- [ ] Right-click SSH port → Open with ssh client → SSH prompt appears (if SSH open)
- [ ] Tab completion, arrow key history, Ctrl+C all work in terminal

### UI actions
- [ ] Host delete → confirm → gone from table
- [ ] Double-click host → IP in clipboard
- [ ] Send to Brute → Brute tab opens with correct fields
- [ ] Process Kill → status changes
- [ ] Dynamic tab Save Output → .txt file downloads
- [ ] Column resize → drag → reload → width preserved
- [ ] Filters → keyword filter → only matching hosts shown

---

## Known Limitations

| Limitation | Impact |
|-----------|--------|
| NSE/vulners takes ~6.8s/port | Stage 2 takes 2–3 minutes; not reducible |
| eyewitness requires /usr/bin/eyewitness | Screenshot tests skip if not installed |
| Live tests require 192.168.85.11 to be up | All 19 live tests fail if VM is down |
| xterm.js from CDN | Headless tests skip canvas check if CDN unreachable |
| /tmp/legion/ accumulates | Run `sudo rm -rf /tmp/legion/legion-*` before live tests |
| Orphaned nmap processes | `live_target` fixture kills stray PIDs before tests |
