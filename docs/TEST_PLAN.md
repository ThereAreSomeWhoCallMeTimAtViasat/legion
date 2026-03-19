# Legion Flask — Comprehensive Test Plan

**Generated:** 2026-03-18
**Version:** v7.6-flask
**Branch:** flask-clean

---

## Overview

Legion has three test layers:

| Layer | Files | Tests | How to run |
|-------|-------|-------|------------|
| **Unit / API** | 18 × `tests/test_*.py` | 502 | `sudo python3 tests/<file>.py` |
| **Selenium offline** | `test_selenium_ui.py` | 92 | `sudo python3 -m pytest tests/test_selenium_ui.py -m "not live"` |
| **Selenium live scan** | `test_selenium_ui.py` | 15 | `sudo env LEGION_TEST_TARGET=192.168.85.11 python3 -m pytest tests/test_selenium_ui.py -m live` |

**All 609 tests pass as of v7.6-flask.**

---

## What Selenium Actually Tested

Selenium drives a real headless Firefox browser against a real Flask server (port 5099). It verifies that **the browser UI works end-to-end** — not just that the server responds, but that the user can click things and see the right results.

### Offline tests (92) — seeded data, no network scan needed

#### App Load (6 tests)
- ✅ Page loads without error
- ✅ Version string visible in header
- ✅ Project name shown in status bar
- ✅ Seeded host (10.10.10.1 with ports 22/80/443) appears in Hosts table after first snapshot poll
- ✅ Processes table present
- ✅ Status bar visible

#### File Menu (10 tests)
- ✅ Clicking "File" opens dropdown
- ✅ All items visible: New, Open, Save, Add hosts, Import nmap, Export JSON
- ✅ "Add host(s) to scope" opens `add-hosts-modal`
- ✅ "Import nmap" opens `import-nmap-modal`
- ✅ Clicking outside the menu closes it

#### Help Menu (5 tests)
- ✅ Clicking "Help" opens dropdown
- ✅ "Config" item visible
- ✅ "Help" item visible
- ✅ Config → opens `config-modal`
- ✅ Help → opens `help-modal`

#### Keyboard Shortcuts (5 tests)
- ✅ Ctrl+H → add-hosts-modal opens
- ✅ Ctrl+I → import-nmap-modal opens
- ✅ F2 → config-modal opens
- ✅ F1 → help-modal opens
- ✅ Ctrl+N button wired in DOM (not triggered — would reset project)

#### Modals (13 tests)
- ✅ Add hosts modal opens, first input auto-focused
- ✅ Required fields present (targets textarea, Submit, Cancel)
- ✅ Modal closes with × button
- ✅ Modal closes with Cancel button
- ✅ Modal closes on overlay click
- ✅ Import nmap modal opens, has path text input
- ✅ **Import actually works**: enter XML path → server imports → host 10.10.10.2 appears in table
- ✅ Import modal closes with ×
- ✅ Config modal opens, has Save button and profile selector
- ✅ Config modal closes
- ✅ Help modal opens, has content text
- ✅ Help modal closes

#### Left Panel Tabs (5 tests)
- ✅ Hosts tab active by default
- ✅ Services tab switches
- ✅ Tools tab switches
- ✅ OS tab switches
- ✅ Returns to Hosts tab

#### Right Panel Tabs (6 tests)
- ✅ Services tab default when host selected
- ✅ Scripts, Information, CVEs, Notes tabs all switch correctly
- ✅ Returns to Services tab

#### Host Selection (5 tests)
- ✅ Clicking host row selects it (`.selected` class applied)
- ✅ Selecting host loads its ports into Services right tab
- ✅ Seeded host has expected ports (22, 80, 443)
- ✅ Information tab shows the host's IP
- ✅ Clicking a tab clears the orange `tab-unread` indicator

#### Context Menus (8 tests)
- ✅ Right-click host row → context menu appears at cursor
- ✅ Host menu contains "Delete"
- ✅ Menu dismisses on outside click
- ✅ Right-click process row → menu appears with Kill/Retry/Clear items
- ✅ Right-click port row (Services right tab) → port action menu appears
- ✅ Port menu has at least one action item
- ✅ Right-click dynamic tool tab → "Save Output" and "Close Tab" in menu
- ✅ Menu dismisses on outside click

#### Column Sorting (5 tests)
- ✅ Clicking Hosts table OS header → sort arrow appears
- ✅ Clicking again → sort direction toggles (▲ → ▼)
- ✅ Processes table status column sorts
- ✅ Services left table sorts
- ✅ Ports (right panel) table sorts

#### Process Output (3 tests)
- ✅ Running `echo` command → process row appears → clicking row loads output in upper panel
- ✅ Output panel scrolled to bottom after load
- ✅ Process status filter (Running / All) filters process table correctly

#### Dynamic Tool Tabs (3 tests)
- ✅ Running a process → dynamic tab button appears in right panel tab bar
- ✅ Clicking dynamic tab → output panel shown in `#dynamic-tabs-container`
- ✅ Clicking × on tab → tab removed from bar

#### Tab Indicators (3 tests)
- ✅ `tab-unread` CSS class applies orange color to tab button
- ✅ Clicking a tab that has `tab-unread` removes the class
- ✅ `tab-match` CSS class exists (red star for match processes)

#### OS Tab (4 tests)
- ✅ OS tab shows grouped OS names from seeded host
- ✅ Clicking an OS row filters the OS hosts panel
- ✅ OS list does NOT re-render on every 1.5s poll (hash gate working)
- ✅ Switching back to Hosts tab works

#### Brute Tab (5 tests)
- ✅ Clicking Brute main tab switches to it
- ✅ IP, Port, username wordlist, password wordlist fields present
- ✅ Returns to Scan tab

#### Snapshot Performance (2 tests)
- ✅ `/api/snapshot` responds in under 500ms
- ✅ Snapshot includes `os_groups` field

---

### Live scan tests (15) — real nmap against 192.168.85.11

Run time: ~3:30 for full staged scan (6 stages including NSE/vulners)

- ✅ **test_01**: Add host 192.168.85.11 via Add Hosts modal → modal status shows "Scan started!", modal auto-closes
- ✅ **test_02**: Host row 192.168.85.11 appears in Hosts table within 20s
- ✅ **test_03**: At least one process appears with status Running or Waiting within 45s
- ✅ **test_04**: Clicking a Running process → output appears in upper panel
- ✅ **test_05**: At least one process reaches Finished within 120s (stage 1 done)
- ✅ **test_06**: After scan, clicking 192.168.85.11 → Services tab shows open ports
- ✅ **test_07**: Port 80 confirmed present in discovered ports
- ✅ **test_08**: ALL 6 nmap stages complete (all processes Finished) within 900s
- ✅ **test_09**: Information tab shows 192.168.85.11 after scan
- ✅ **test_10**: Information tab has content (OS, hostname, etc.)
- ✅ **test_11**: HTTP ports found (80, 8180) → screenshooter process shows Finished
- ✅ **test_12**: Clicking screenshooter row → dynamic tab → screenshot PNG loads (naturalWidth > 0)
- ✅ **test_13**: CVEs tab renders without error after NSE stage
- ✅ **test_14**: No duplicate screenshooter processes for 192.168.85.11
- ✅ **test_15**: `tab-unread` CSS mechanism confirmed (orange colour verified via JS)

---

## What Selenium Did NOT Test

These are gaps — things that require additional testing (manual or future automation).

### Functional gaps (Selenium confirmed the UI exists but not that the action works)

| Feature | What Selenium checked | What it didn't verify |
|---------|----------------------|----------------------|
| File → New | Button exists in DOM | Actually creates new empty project |
| File → Open | Opens file-browser-modal | Actually loading a saved `.legion` file |
| File → Save / Save As | Button exists | File written to disk, reopenable |
| File → Export JSON | Button exists | JSON file downloaded, correct content |
| File → Send selection to notes (Ctrl+B) | Button exists | Selected text actually appended to Notes |
| Host delete | "Delete" in context menu | Confirm dialog fires, host removed from DB and UI |
| Host double-click | — | Copy IP to clipboard |
| Port double-click | — | Switches left panel to Hosts tab |
| Port context menu actions | Menu appears, has items | Actually running nmap/hydra/nikto against port |
| Send to Brute | — | Port right-click → fills Brute tab fields + switches tab |
| Run Hydra | — | Brute tab submit actually runs hydra |
| Manual Tool Run modal | — | Selecting tool + running it |
| Nmap Scan modal | — | Custom scan options work |
| Config save | Save button exists | Settings actually written to `legion.conf` |
| Notes save | Notes tab accessible | Text saved to DB and persists after restart |
| Script output | Scripts tab switches | Clicking script row shows output |
| CVE detail | CVEs tab accessible | Clicking CVE shows detail / mark reviewed |
| Column width resize | — | Drag to resize, persists in localStorage |
| Process → Kill | Menu item exists | Process actually killed (signal sent) |
| Process → Retry | Menu item exists | Process re-queued and runs again |
| Process → Clear | Menu item exists | Process removed from active view |
| Dynamic tab Save Output | Menu appears with Save item | Blob download triggers, file content correct |
| Screenshot modal | — | Clicking screenshot thumbnail opens full-size modal |
| Add Port modal | — | Manually adding a port to a host |
| Filters modal | — | Applying port/service/OS filters to hosts table |
| Host selection / notes modal | — | Saving notes via modal |
| Scheduler settings | — | Modifying scheduler prefs via Config modal |
| Provider logs | — | Viewing logs in modal |

### Persistence gaps (nothing tested across server restart)
- Notes survive server restart
- Process output readable after restart
- Hosts and ports persist after restart
- Project save → reopen restores all data

### Network scan gaps (live test confirms scan works, but not every code path)
- Stage 1–6 chain verified to complete, but individual stage commands not inspected
- vulners.nse CVE data not asserted (test_13 only checks tab renders)
- Screenshooter image content not verified (only that PNG loads, not what it shows)
- Hydra brute-force results and credential extraction untested
- IPv6 scan untested
- Custom nmap options (Hard mode, FIN/NULL/Xmas scans) untested

---

## How to Verify Functional Gaps

### Quick manual checklist after any server restart

Open http://127.0.0.1:5000 and verify:

**Project persistence**
- [ ] Add a host, add a note, restart server → host and note still present

**File menu actions**
- [ ] File → Save → check file created at shown path
- [ ] File → Export JSON → file downloads with host/port data

**Host lifecycle**
- [ ] Right-click host → Delete → confirm → host gone from table
- [ ] Double-click host → IP copied to clipboard (paste to verify)

**Port actions**
- [ ] Right-click port in Services right tab → select an nmap NSE scan → process appears in table
- [ ] Double-click port → left panel switches to Hosts tab

**Send to Brute**
- [ ] Right-click an SSH port → Send to Brute → Brute tab opens with IP/port pre-filled

**Process actions**
- [ ] Right-click a Running process → Kill → status changes to Killed
- [ ] Right-click a Finished process → Retry → process re-appears as Running

**Output save**
- [ ] Right-click a dynamic tool tab → Save Output → `.txt` file downloads with process output

**Notes**
- [ ] Click host → Notes tab → type text → restart server → text still there

**Filters**
- [ ] Click Filters button → apply OS filter → only matching hosts shown → clear → all hosts back

---

## Running All Tests

```bash
# Unit tests (all 18 files)
for f in tests/test_*.py; do
  echo -n "$f: "
  sudo python3 $f 2>&1 | grep "^Results:"
done

# Selenium offline (headless, ~65s)
sudo python3 -m pytest tests/test_selenium_ui.py -v -m "not live"

# Selenium live scan (~3:30, requires VM)
sudo env LEGION_TEST_TARGET=192.168.85.11 python3 -m pytest tests/test_selenium_ui.py -v -m live

# Core unit tests only (fastest CI check)
sudo python3 tests/test_behavioral.py
sudo python3 tests/test_signal_chains.py
sudo python3 tests/test_phase1_right_panel.py
```

---

## Unit Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `test_behavioral.py` | 15 | Core import, scheduler, process lifecycle, WAL mode |
| `test_signal_chains.py` | 28 | Scheduler → chain → stage → XML import signal flow |
| `test_phase1_right_panel.py` | 27 | Right panel API routes (info, CVEs, scripts, services) |
| `test_flask_integration.py` | 42 | All API endpoints: snapshot, processes, hosts, output |
| `test_routes_webcontroller.py` | 21 | Route → WebController wiring |
| `test_webcontroller.py` | 28 | WebController internal: queue, capture, match |
| `test_webcontroller_remaining.py` | 31 | Staged nmap, duplicate check, screenshot dedup |
| `test_ui_wiring.py` | 42 | JS function presence, event wiring, DOM expectations |
| `test_ui_fixes.py` | 42 | Phase 2–5 UI fixes verified in JS/CSS source |
| `test_phase5_polish.py` | 20 | Scroll, animations, tab indicators |
| `test_phase1_settings.py` | 11 | Settings API: read, write, sections |
| `test_phase2_auxiliary.py` | 8 | Aux: filters, getServiceNames, getOS |
| `test_phase2_interactions.py` | 23 | Host click, port right-click, tab close |
| `test_phase3_sorting.py` | 23 | Column sorting: hosts, processes, services |
| `test_phase4_state.py` | 29 | Filters, host lifecycle |
| `test_v6_v7_fixes.py` | 34 | All v6.0–v7.4 server + JS fixes |
| `test_new_dialogs.py` | 55 | Modals, dialog focus, error handling |
| `test_visualupgrades_features.py` | 23 | Match banner, OS groups |

---

## Known Limitations

- **NSE/vulners**: ~6.8s per port × N ports — inherent to vulners.com API rate limiting. `--min-parallelism` applied but doesn't reduce total time.
- **eyewitness**: Requires `/usr/bin/eyewitness` installed. Tested against live VM only.
- **Qt6 GUI**: Not tested (replaced by Flask). `controller.py` must not be modified.
- **Multi-project**: One active project at a time. Not tested.
- **IPv6**: Code path exists, not tested.
