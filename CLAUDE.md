# Legion Project Context for Claude Code

## ABSOLUTE RULE — NO GUESSING
**Before writing ANY code that references a schema, API, column, function, or data structure:**
1. **Read the definition** — find the CREATE TABLE, class definition, or function signature in the actual source files
2. **Read existing usages** — grep for INSERT, SELECT, or call sites to confirm column/parameter names
3. **Never infer from naming conventions** — a table called `process_matches` might not have a `process_id` column; read `db/SqliteDbAdapter.py` to know for certain
4. **If uncertain, ask** — the user explicitly requires this; guessing wastes time and introduces bugs that are hard to diagnose

**How this rule was learned (v10.157):** `DELETE FROM process_matches WHERE process_id IN (...)` was written by convention rather than by reading the schema. The actual table has no `process_id` column — it is keyed by `hostIp`. This one wrong column name aborted the entire delete/purge transaction on every call, leaving host data fully intact while returning `status: ok`. The correct SQL (`WHERE hostIp = :ip`) was visible in 4 places already in the codebase. Two seconds of grep would have caught it.

---

## User Preferences
- User's database refactoring and features TAKE PRECEDENCE over upstream code
- Tests for every method before building — prove one element works before doing the whole thing
- Host is always the key — never mix data from different hosts in views
- Version number must be bumped in `index.html` with every change set, BEFORE restarting server
- Stay on version 10.x until user says go to 11
- Version bump format: `LEGION v10.X-flask` — increment the point version each fix/feature
- Static asset cache buster in `base.html` (`?v=N`) — bump when CSS or JS changes

## Cost Management Strategy
**One conversation per feature. Start fresh. Use `/compact` mid-task if needed.**

### Conversation commands
- `/compact` — compress current conversation history in place (use mid-session before big implementation)
- `/clear` — wipe history, stay in same terminal session
- `exit` then `claude` — full fresh start (best between separate features)

### Remaining work
| Conv | Work | Est. cost |
|------|------|-----------|
| A | LLM AI tab (backlog #7) | Med |
| B | pyShodan API key wiring | Cheap |
| C | Auto per-service NSE scripts (backlog #9) | Med |

**Rule:** CLAUDE.md + MEMORY.md auto-load in every new session — full project context is warm instantly.
**Rule:** Update CLAUDE.md and MEMORY.md as part of completing every task — not after the fact.

---

## Project Overview
- **Repo:** https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
- **Primary Branch:** `flask-clean` (branched from `visualUpgrades` — pure code, no upstream)
- **Type:** Network penetration testing framework (fork of Sparta/Hackman238 Legion)
- **Stack:** Python 3.10+, PyQt6 (replaced by Flask), SQLAlchemy ORM, SQLite
- **Current Flask version:** v10.161-flask
- **Static asset cache:** CSS `?v=87`, JS `?v=106` in `base.html`
- **legion.conf path:** `/root/.local/share/legion/legion.conf` (app reads this at runtime)

## CRITICAL ARCHITECTURE DECISION
**DO NOT USE upstream runtime.py.** The user's logic in controller.py IS the source of truth.

```
YOUR code (controller.py + logic.py)  →  WebController wraps it Qt-free
    QProcess → subprocess.Popen          QTableView → HTML table
    QTimer → threading.Timer             QMenu → JSON list of dicts
    self.view.xxx() → state dict         Qt signals → JS polling
    Everything else stays EXACTLY the same
```

## Running
```bash
# Start Flask
sudo python3 legion.py --web &
# http://127.0.0.1:5000

# Run full test suite with colour report
sudo bash run_tests.sh                          # offline only
sudo bash run_tests.sh 192.168.85.11            # + live (SSH/MySQL/msfconsole + nmap scan)
sudo bash run_tests.sh --unit                   # unit only
sudo bash run_tests.sh --stories               # user story tests (ports 5085/5086) + HTML reports
sudo bash run_tests.sh --no-report             # skip HTML report generation
sudo bash run_tests.sh --live 192.168.85.11     # live tests only

# Minimum before every commit
sudo python3 tests/test_behavioral.py
```

## Architecture — Critical Files

| File | Purpose |
|------|---------|
| `controller/web_controller.py` | Qt-free WebController: scheduler, parallel staged nmap (_launch_ports_stage/_launch_nse_stage), screenshooter, process queue |
| `controller/controller.py` | Original Qt6 controller — DO NOT modify |
| `app/web/routes.py` | All Flask API endpoints |
| `app/web/static/js/legion.js` | All UI interactions, rendering, polling |
| `app/web/static/css/legion.css` | Qt6 Fusion Dark palette replica |
| `app/web/templates/index.html` | Qt6 layout — version string lives here |
| `app/web/templates/base.html` | JS/CSS includes with `?v=N` cache-bust |
| `db/SqliteDbAdapter.py` | SQLAlchemy adapter — WAL mode enabled |
| `app/importers/nmap_import.py` | Qt-free NmapImporter wrapper |
| `app/importers/NmapImporter.py` | Original Qt6 importer — DO NOT modify |
| `app/logging/legionLog.py` | Logger setup — _InMemoryLogHandler for log tab; RotatingFileHandler (10MB/3 backups) |
| `tests/conftest.py` | Selenium fixtures (ports 5094–5099) |
| `tests/test_session_isolation.py` | 25 behavioral tests: shutdown safety, scan generation, startup checks, file isolation |
| `run_tests.sh` | Full suite runner with spinner/timer/options |

---

## Known Critical Bugs & Patterns

### SQLite / Sessions
- **WAL mode is required** — without it, frequent output writes freeze all Flask reads
- **ORM objects detach after `session.close()`** — never use `getPortsByHostId()` in scheduler; use `getPortsAndServicesByHostIP()` (returns plain dicts)
- `session.remove()` creates fresh session; `session.close()` just closes connection
- NmapImporter uses `self.db.session()` and commits but never removes

### Staged Nmap Chain (parallel — v10.19)
- Stage order: 1=HTTP, 2=SMB/DB, 3=FTP/SSH/RDP, 4=remaining, 5=high, 6=NSE|vulners (last)
- Stages 1–5 (PORTS) launch **simultaneously** via `_launch_ports_stage`
- Stage 6 (NSE) runs **after all PORTS stages finish** via `_launch_nse_stage`
- NSE gets `-p <all_open_tcp_ports>` queried from raw sqlite3 (bypasses ORM cache)
- Completion tracked: `_pending_ports_stages[hostIp]` set + `_pending_stages_lock`
- Each PORTS stage: polls `_active_processes` until `_popen` not None → `wait()` → import XML → `scheduler(isNmapImport=False)`
- Scheduler calls `session.remove()` before `getHosts` to bypass cached session state

### Scan Generation Counter (v10.24)
- `_scan_generation[hostIp]` (int dict) — bumped atomically inside `_pending_stages_lock` at the top of `runStagedNmap()` BEFORE stages launch
- Every `_wait_and_import` and `_wait_nse` closure captures `generation` at launch time
- On wakeup (after `proc._popen.wait()`): compare captured gen to `_scan_generation[hostIp]`; if mismatch, exit silently — stale thread from a killed scan cannot corrupt the new scan's `_pending_ports_stages`
- `_stage_completed()` also checks generation before modifying state
- Reset in `start()` so project switches start clean

### Shutdown Safety (v10.24–v10.25)
- **`/api/shutdown`** (triggered by `beforeunload` on EVERY browser refresh) must only call `saveRunningProcessOutputs()` — NEVER `killRunningProcesses()`. Killing here destroys active nmap scans on Ctrl+Shift+R.
- **`killRunningProcesses()`** must: (1) call `storeProcessKillStatus()` per process so `_wait_and_import` threads see `isKilledProcess()=True` and skip importing partial XML; (2) drain `fastProcessQueue` and mark queued procs Killed — without this, capture threads call `checkProcessQueue()` on finish and ghost scans restart.
- **`closeProject()`** runs `PRAGMA wal_checkpoint(TRUNCATE)` then `database.dispose()` before handing off to `ProjectManager.closeProject()` which deletes the files.
- SIGINT handler (`_web_shutdown` in `legion.py`): 0.5s sleep before `_os._exit()` so daemon threads notice kill status.

### Startup Check (_startup_check — v10.25)
Called automatically from `start()` on every project open/create:
1. Mark any Running/Waiting processes as Crashed (orphans from SIGKILL'd previous session)
2. Delete stale `.live_output` files in running and output folders
3. Call `_cleanup_orphaned_temp_files()` (see below)

### Orphaned Temp File Cleanup (_cleanup_orphaned_temp_files — v10.26–v10.27)
- **DB files**: scan `/tmp/legion/legion-*.legion`; skip current session's DB; for each candidate, scan `/proc/PID/fd` symlinks across ALL running processes — if any FD points at the file, it's live (skip); otherwise delete + companion `-wal`/`-shm`.
  - **Why /proc not flock**: SQLite uses POSIX `fcntl` advisory locks (not BSD `flock`). `flock(LOCK_EX|LOCK_NB)` returns success even on an active SQLAlchemy DB — false positive. `/proc/PID/fd` checks actual open file descriptors, which is definitive.
- **Folder cleanup**: scan `legion-*-running` and `legion-*-tool-output` dirs; skip current session's folders; read `.legion_session_pid` sentinel (written by `start()`); use `os.kill(pid, 0)` to test liveness; delete if process is dead.
  - **Why PID sentinel not name matching**: DB and running/output folders are independently named by separate `mkdtemp`/`NamedTemporaryFile` calls — their random suffixes don't match, so name-based DB↔folder correlation is impossible.

### File Isolation Between Instances (v10.26)
- **DB, output folder, running folder**: unique per instance via `NamedTemporaryFile`/`mkdtemp` — no sharing
- **Log files** (`legion.log`, `legion-db.log`, `legion-startup.log`): shared path but now use `RotatingFileHandler(maxBytes=10MB, backupCount=3)`; session-start separator (`===SESSION START===`) written to file on logger init
- **`_screenshots_taken`**: reset to `set()` in `start()` — was lazily init'd via `hasattr`, leaked across project switches
- **PID sentinel**: `{running_folder}/.legion_session_pid` — written in `start()`, read by folder cleanup
- **Intentionally shared**: `~/.local/share/legion/legion.conf`, profiles, `active_profile.txt` — config, not data

### Scheduler / Process Queue
- `checkProcessQueue()` respects `general_max_fast_processes` (all tools) and `general_max_slow_processes` (nmap only)
- Both read from `self.settings` — attribute names are `general_max_fast_processes` and `general_max_slow_processes` (NOT `general_max_concurrent_scans` — that attribute does not exist)
- Queue re-triggers when a process finishes via `_capture_output` → `checkProcessQueue()`
- Interactive (PTY) processes are excluded from queue counting

### Process Output
- `_capture_output` writes to `{outputfile}.live_output` temp file (buffering=1 for immediate flush)
- `/api/processes/<id>/output` reads temp file first (live), falls back to SQLite
- SQLite written ONCE at process completion (not during)
- nmap progress: `--stats-every 5s` on all nmap commands; parsed in `_capture_output` via regex `About ([\d.]+)% done(?:.*?ETC: ([\d:]+))?`; stored via `storeProcessPercent()`

### startTime Format
- Stored as: `'%d %b %Y %H:%M:%S.%f'` (e.g. `17 Mar 2026 19:12:35.171589`)
- Snapshot route tries both formats

---

## Completed Phases Summary
- **All Qt6 gaps closed** (v9.6–v9.9): input validation, python-script routing, file import, PostgreSQL adapter, ORDER BY whitelist, dup check layer 2, .bak, XML archive, screenshot blacklist, CSV export, applySettings, custom command, hydra, dup check for user actions, 3 UI buttons
- **v10.0**: percent column, multi-host parallel, in-memory log, font size, port state filter
- **v10.1**: font size tab-switch fix (CSS container inheritance)
- **v10.2**: log buffer 10k, snapshot log demoted to DEBUG
- **v10.3**: save-on-exit prompt, orange tab state preserved across host switches
- **v10.4**: max_scans attribute name fixed, Queue logs demoted to DEBUG
- **v10.6**: brute tab pre-fill defaults, hide/show for no-user/no-pass services
- **v10.7**: store-cleartext-passwords-on-exit, screenshooter-timeout, black-background wired
- **v10.8**: Config editor find/search (F2, Ctrl+F) — backlog #4
- **v10.9**: Terminal Ctrl+B → Notes — backlog #5
- **v10.10–v10.16**: settings live-apply, config find overlay, graceful shutdown
- **v10.17**: Hydra combo file support (`-C` flag); live Hydra tests fixed
- **v10.18**: NSE|vulners moved to stage 6 (last); closes Issue #30
- **v10.19**: Parallel PORTS stages (1–5 simultaneous); NSE runs against all discovered ports
- **v10.20**: Font size buttons now resize xterm.js terminals (pt→px via ×1.333; fitAddon.fit() after)
- **v10.21**: Scan tab restore — returning from Brute re-selects host row and reloads right panel
- **v10.24**: 4 shutdown/scan-restart bugs: (1) /api/shutdown no longer kills processes on browser refresh; (2) killRunningProcesses stores kill status in DB; (3) drains fastProcessQueue on kill; (4) scan generation counter prevents stale _wait_and_import threads from corrupting new scans
- **v10.25**: Startup/shutdown defensive checks: _startup_check() marks orphan Running/Waiting→Crashed + cleans .live_output files; closeProject() WAL checkpoint + database.dispose(); SIGINT settle sleep
- **v10.26**: File isolation: RotatingFileHandler (10MB/3 backups) + session separator; _cleanup_orphaned_temp_files() with /proc FD scanning + PID sentinel; _screenshots_taken reset in start(); database.dispose() before file deletion
- **v10.27**: 25-test session isolation suite (tests/test_session_isolation.py); fixed flock→/proc FD scanning; fixed name-based folder cleanup→PID sentinel approach
- **v10.28**: settings.py stage defaults fixed (PORTS| prefix, stage3 was wrong "Vulners,CVE", stage6 now NSE|vulners); scroll preservation in loadProcessOutput + loadLog; split font size controls (upper/lower panels independent, `legion_upper_font_pt` key, `upper-font-dec`/`upper-font-inc` buttons)
- **v10.29**: `legion.py --web` opens Firefox automatically (`--no-remote --profile ~/.mozilla/firefox/legion-profile`, runs as SUDO_USER via `sudo -u`, 1.5s Timer delay)
- **v10.30**: upper-panel scroll position survives tab rebuilds (`_procScrollPos` map, saved before `container.innerHTML=''`, restored in `loadProcessOutput` on fresh elements)
- **v10.50**: Ctrl+B source tracking — `_lastNonXtermSelSource` (mousedown capture listener) fixes wrong-panel flash when both panels have selections; `match-positive` in `domSelectionToAnsi()` am map → `'1;93;43'` adds yellow background (was foreground-only)
- **v10.51**: Selection confinement — `_confineTo(el)` sets `user-select:none` on `<html>` + `user-select:text` on target panel during drag; restored on mouseup. Prevents dragging outside output panel boundaries into tab bar / host list / chrome.
- **v10.52**: Heartbeat watchdog — `/api/heartbeat` (POST, every 5 s from JS); `hb-watchdog` daemon thread fires `killRunningProcesses()` + `os._exit(0)` when gap > `_HB_TIMEOUT` (20 s). Multi-instance safe: each Legion process has its own watchdog. Handles Firefox File→Exit and window close.
- **v10.53**: `_kill_all_descendants()` in `web_controller.py` — scans `/proc/*/stat` BFS from `os.getpid()` to find every descendant; SIGKILL all of them. Called from `killRunningProcesses()`. Fixes shell=True grandchild orphan problem (nmap, gobuster survive shell death without this).
- **v10.54**: Sticky processes table header — `position:sticky` moved from `th` to `thead`; `border-collapse:collapse` breaks per-cell sticky.
- **v10.59**: Splitter centre start — bottom-section defaults to `offsetHeight/2` on first load (JS default branch in restoreSplitterPos when no localStorage entry).
- **v10.60**: All splitters wired — proc-vsplitter, tools-vsplitter, os-vsplitter, scripts-vsplitter: IDs added to target elements, `initSplitter()` calls added, flex-pinning (`flexGrow:0; flexShrink:0`) on mousedown, localStorage save/restore. Splitter max raised to 900px.
- **v10.61**: Tab bar scrollbar always visible — `.tab-bar` changed from `overflow-x:auto` + `height:0` hide to `overflow-x:scroll` with explicit 8px track, `#888` thumb, Firefox `scrollbar-color`. Global scrollbar thumb brightened `#454545→#777`.
- **v10.62**: Scan tab state restoration — `initTabBar` now uses `c.closest('.tab-widget') === widget` guard so only same-level `.active` classes are stripped when switching main tabs. Previously wiped nested panels (right-panel tabs, left-panel tabs) on every Scan↔Brute switch.
- **v10.63**: Match navigation arrows — `_matchNavState{}` (per-process idx), `_matchNavInit()` (re-highlights on poll), `_matchNav()` (scrolls to span); match banner is `position:sticky;top:0`; `.match-current` is solid yellow vs dimmer `.match-positive`. Works in both upper (dyn-output-*) and lower (plain-output) panels.
- **v10.66**: Scan commands saved to host notes — `runStagedNmap()` writes a dated block to each host's Notes tab at scan start (all PORTS stage commands without `-oA`; NSE template with `<discovered-ports>` note); `_launch_nse_stage()` appends the actual NSE command (with real `-p` arg, `-oA` stripped) once open ports are known. `_append_to_host_notes()` helper handles comma-separated multi-host targets, skips gracefully if host not yet in DB (first scan).
- **v10.65**: Save/Open data completeness — four bugs fixed: (1) `ProjectManager.saveProjectAs()` rewrites all `outputfile` AND `command` paths in the saved DB from old temp prefix to new `<name>-tool-output` prefix after copytree, so screenshots, process output files, and displayed commands resolve correctly after open; (2) `process_matches` table added to DB schema (created on connect via `CREATE TABLE IF NOT EXISTS`); `saveMatchState()` writes `_matches` dict to DB on every save/shutdown; `loadMatchState()` restores it in `start()` so keyword match highlighting survives project open; (3) `saveRunningProcessOutputs()` now reads PTY buffer (`session._buf` from `_TerminalSession`) for interactive processes and saves to `process_output` table, so interactive terminal history is preserved on save; (4) on project open, Interactive processes with no live PTY session fall through JS `session_id` check and display their saved `process_output` as static text — no blank panel. Full audit confirms all other state (host/port/service/OS/CVE/NSE/notes/AI/wordlists/nmap files) is already correctly saved.
- **Test suite**: `tests/test_ui_session_features.py` — 30 non-hollow Selenium tests (port 5072) covering all v10.59–v10.63 changes. Key patterns: `_HB_TIMEOUT=600` watchdog disable, class-scoped `match_setup` fixture (one page load for 13 match-nav tests), `_wait_proc_done_api` (Python requests, not DOM), `set_script_timeout(30)`. Integrated into `run_tests.sh --selenium`.
- **Stories fix**: `generate_report.py` `make_driver()` and `test_user_stories.py` `driver` fixture both gain `set_script_timeout(30)`. Heartbeat keeper interval 15s→8s (was 5s margin under 20s watchdog). Drain settle sleep 2s→5s.
- **Test additions**: test_goal2_lower_selection (port 5086), test_goal3_ansi_ctrlb (port 5087), test_goal_selection_confinement (port 5085), test_shutdown_subprocess (ports 5083/5084 — subprocess server for os._exit tests). All goal tests converted from `app.run()` daemon threads to `make_server()` + `httpd.shutdown()`.
- **User story tests**: 56 user stories written; 37 offline + 6 live pytest tests in `tests/test_user_stories.py`; 18 generate_report_USxx.py scripts producing dated HTML reports in `testreport/`; integrated into `run_tests.sh` via `--stories` flag with auto server management and heartbeat keeper.
- **Test fixes**: test_08 notes (storeNotes in _ensure_seeded_host); test_09 project name (check snapshot API not DOM title); test_clear retry loop (safe — Clear uses postJson, no window.confirm); NEVER add retry loops to actions that trigger window.confirm() — pending dialog blocks Selenium with UnexpectedAlertPresentException
- **v10.69/71**: Upper font controls now apply to all right-panel text areas: `#script-output-inline`, `#notes-right`, `#tool-output-text`, AI content elements. Previously only `#dynamic-tabs-container` was covered. CSS `flex-basis` must be set alongside `width` — flex-basis always wins in flex containers.
- **v10.72**: Context menu viewport clamping — `showContextMenu()` appends hidden, measures dimensions, clamps `left`/`top` to viewport before making visible. Prevents menus from spilling off-screen at window edges.
- **v10.73**: Go to Tab — tab button scrolled into view via `scrollIntoView()`; cross-host navigation: `_pendingGotoTab` stores pid, host row clicked, `renderDynamicToolTabs` picks it up after async `loadHostDetail` resolves.
- **v10.75**: Context menu scrollable — `max-height:calc(100vh - 16px);overflow-y:auto` added so long port-action lists scroll instead of overflowing.
- **v10.77**: Process filter label "Waiting" (was "Queued"). Value attribute was already correct; only display text changed.
- **v10.79**: All nmap stage commands in Notes for first-time scans — `_pending_scan_notes[hostIp]` dict defers the write until `_stage_completed` (after first XML import guarantees host in DB). Re-scans write immediately.
- **v10.81**: Process timeout — `general_process_timeout` in `[GeneralSettings]` (default 300s). Watchdog daemon thread in `_capture_output` calls `_kill_subtree(proc._popen.pid)` + `proc._popen.kill()` on timeout; appends `[Legion] Process killed` to output. nmap excluded. 0 = disabled. Bug fixed: watchdog was calling `_kill_all_descendants(proc._popen.pid)` (wrong — that function takes 0 args); fixed to `_kill_subtree(proc._popen.pid)`.
- **v10.83**: Impacket credential-requiring tools removed from `[SchedulerSettings]`: `impacket-getnpusers`, `impacket-getuserspns`, `impacket-lookupsid`, `impacket-secretsdump`. `impacket-rpcdump` kept (no credentials needed). Live `/root/.local/share/legion/legion.conf` also updated.
- **v10.85**: Splitter snap-to-zero fix — `initSplitter` mousedown now reads `startSize = el.offsetWidth` BEFORE setting flex properties, and sets `el.style.flexBasis = startSize + 'px'` alongside flexGrow/flexShrink. Without this, CSS `flex-basis:0%` from `.table-wrap` class collapsed the element to 0 on every click. Also `mousemove` now updates `flexBasis` alongside `width`.
- **v10.86**: Horizontal splitter direction — negated delta for `isH` case so dragging down shrinks the bottom section (expanding top) instead of growing it.
- **v10.87**: Clearing a process also clears the lower output panel (`plain-output.textContent = ''`) if that process is currently selected.
- **v10.88/89**: Host input validation — comma allowed only for nmap octet shorthand (e.g. `192.168.85.11,111`). After a comma, every subsequent token must be `isdigit()`. Full IPs or CIDRs after comma (e.g. `192.168.85.11,192.168.85.111`) are rejected. Error shown in dialog without closing it.
- **v10.90/91**: All nmap scan types write commands to host Notes — Easy (discovery + list) and Hard paths now store note in `_pending_scan_notes[target]` before launching; `_capture_output` writes it after XML import (host guaranteed in DB). Staged nmap path unchanged (already had deferred write).
- **v10.92**: Add hosts dialog error display — `postJson` resolves even on 400; `.then()` now checks `data.error`, shows message in red validation element without closing the dialog. Validation element gets `white-space:pre-wrap` for multi-line hint.
- **v10.93**: AI tab redesigned — Phase 1 (synthesizer) and Phase 2 (attack planner) split into separate routes and calls. Phase 2 is on-demand via "Get Attack Advice" button. Running state persists when clicking away and back (`_aiRunning` + `_aiRunningHostId` flags). Re-analyze confirmation when existing analysis found. New routes: `POST /api/ai/analyze-host/<id>/phase1` and `/phase2`. New functions: `run_phase1()` and `run_phase2()` in `analyzer.py`.
- **v10.94**: Ctrl+B most-recent-selection wins — xterm fallback reads (`_termState.xterm.getSelection()`) now guarded by `&& !_lastNonXtermSelSource`. xterm maintains its own selection state independently of `window.getSelection()`; the old code used the stale xterm selection even after the user made a fresh DOM selection in the upper panel.
- **v10.95**: Config manager backup + validation — `_backup_conf(src, label)` helper writes to `~/.local/share/legion/backup/{label}-{YYYYMMDD_HHMMSS}.conf` (timestamped, never overwrites). All three save paths now use it: raw legion.conf save, profile save, and profile activate. Profile activate also validates with `_validate_legion_conf` before copying — broken profiles can't become active.
- **Tests**: `tests/test_ui_v10_features.py` (port 5075, 10 tests): context menu clamping, font size all panels, goto-tab same+cross-host. `tests/test_ui_v10b_features.py` (port 5078, 14 tests): context menu scroll, filter label, notes all stages, process timeout (API+DOM+duration+output panel+nmap-exempt), scheduler no impacket. Skill registered at `~/.claude/skills/legion-selenium-test.md`.
- **v10.117**: Easy Mode Config Editor (backlog #10 + #11) — `⊞ Easy Edit` button in F2 Config Manager modal. Parses the active profile's conf text client-side, shows structured section editors, serializes back on close. Sections: GeneralSettings/BruteSettings/ToolSettings (labeled forms with typed inputs), StagedNmapSettings (per-stage type+spec rows), HostActions (searchable table, 2-col CSV), PortActions (searchable table, 3-col CSV, [IP]/[PORT] validation), PortTerminalActions (same + terminal checkbox), SchedulerSettings (tool dropdown from known keys, service + tcp/udp), MatchSettings (tag chip editor with add/delete per keyword). Inline red-border validation blocks save when [IP]/[PORT] missing. `✓ Apply to Config` serializes without closing; `← Back to Advanced` applies and returns to raw textarea.
- **v10.137**: `--disabled` CSS color #808080 → #b8b8b8 (dark mode, luminance 184 vs old 128); `@media (prefers-color-scheme:light)` block maps to #333 + inverted palette. CSS `?v=87`.
- **v10.138**: AI Phase 1 findings table sorted by port ascending before DOM insert. Fixed JS bug: `_aiSevOrder['critical']` = 0 was falsy (`0 || 4` = 4), so critical sorted last. Fixed with `!== undefined` guard. Secondary sort by severity within same port. No-port findings sort last (port = 999999).
- **v10.139**: Easy Mode MatchSettings spaces preserved. Old `split(',').map(k=>k.trim())` stripped `" PUT "` leading space (conf format `, PUT ,` — comma+space consumed by trim). New: `split(',')` only. `white-space:pre` on chip inner span. No trim on add handler. `title` attribute carries exact keyword for hover inspection.
- **v10.140-143**: File→New production fixes — `renderProcesses` stale guard (like `renderHosts`): discards old-project process data within 2s of switch, prevents auto-click → `loadProcessOutput` → 'Error loading output'. `loadHostDetail` project-switch guard: in-flight fetches bail when `_projectSwitchTime` changes, prevents `markTabUnread` re-adding after clear. `loadProcessOutput` project-switch guard: `.catch()` skips 'Error loading output' on stale fetches. `_clearAllUI` now removes `.tab-btn.tab-unread` from DOM (not just the dict). `L._clearAllUI` exposed via `L` for testing. JS `?v=99`.
- **Tests**: `tests/test_ui_v10e_features.py` (port 5082, 19 tests): disabled color brighter (dark+light mode, luminance), AI Phase 1 port sort (all 6 assertions), Easy Mode match spaces (7 assertions). `tests/test_ui_new_clear_checkbox.py` (port 5082, 26 tests): File→New clear (all output panels, tabs, state), process checkbox column (DB persistence, sort, toggle). Both fully passing. Key test lesson: headless Firefox `window.confirm` blocks — use `requests.post` from Python + inline JS instead of button-click injection; `_clearAllUI` is inside `initInteractions` closure so `L.procPollTimer` must be cleared via `L` namespace.
- **v10.144**: File→Exit DB race — `_capture_output` threads crash with `no such table: process` because `closeProject()` disposes the DB while threads still write. Fix: call `killRunningProcesses()` first in `/api/exit`, sleep 1s for threads to drain, then save/close. Wrapped fallback `storeProcessOutput` call in try/except so a disposed-DB exception doesn't cascade.
- **v10.145**: `highlightMatches` HTML-escaping bug — `ansiToHtml()` escapes `<`, `>`, `&` to HTML entities before `highlightMatches` runs its regex on the result. Keywords `==> DIRECTORY` (gobuster/feroxbuster) and `<ACTIVE>` never matched in JS even though Python backend correctly set `has_match=True`. Fix: HTML-escape the pattern before building the regex so it matches entities. Pre-existing bug (not a regression). JS `?v=100`.
- **v10.146**: Three fixes: (1) `checkDuplicate` layer-2 script-check bug — any port that had nmap NSE results stored was permanently blocking all user-triggered tool actions (`user_triggered=False` default caused layer-2 to return `skip`). Fix: `handleServiceNameAction` passes `user_triggered=True`, bypassing the script-level check for explicit right-click actions. Verified via full context-menu audit (9,774 items; only `Take screenshot` on left panel remains as known architectural gap). (2) `_emergency_autosave` `NameError: name 'logging'` — `logging` was never imported at module level in `routes.py`; added `import logging as _logging` inside the function. (3) `app.run()` "Address already in use" crash handled gracefully — catches `OSError errno 98`, checks if a Legion server is already alive at the port, and offers `[O]pen Firefox / [K]ill and restart / [A]bort` prompt (or auto-opens with `--no-prompt`).
- **Skill**: `legion-ctx-menu-audit` — `scripts/legion_ctx_menu_audit.py` + `.claude/skills/legion-ctx-menu-audit/SKILL.md`. Audits every right-click menu item on every service row for all hosts; classifies as WIRED / NOT_WIRED / SKIP_DUP / BEHAVIOURAL. Invoke via `/legion-ctx-menu-audit [port]`.
- **v10.148**: Right-click "Take screenshot" on right-panel port rows was calling `/api/terminal/start` — spawning an interactive PTY instead of a regular `runCommand()` process. Output went to `/tmp/screenshot-...-dir` (wrong directory, bypassed project screenshots folder and DB result capture). URL also hardcoded `http://` regardless of service. Fix: new `POST /api/screenshot/take` route calls `wc._run_screenshot(host_ip, port, svc_name)` properly; JS handler updated to call it passing `svcName` for correct scheme derivation. JS `?v=101`.
- **v10.149**: Two screenshooter fixes: (1) `--no-verify` flag removed — eyewitness does not have this option; Selenium handles self-signed certs internally. (2) Scheduler: screenshooter check moved BEFORE `checkDuplicate` — the layer-2 script-count check was blocking screenshooter on any port where the vulners NSE stage had stored scripts (i.e., every scanned port), causing 8 of 11 open HTTP/HTTPS ports to silently miss screenshots. Screenshooter now uses `user_triggered=True` for its own layer-1 dedup check, bypassing layer-2 entirely.
- **v10.150**: eyewitness WebDriverError fixes: (1) Pre-flight TCP socket check added to `_run_screenshot` — if the target port is unreachable (connection refused/timeout) eyewitness is skipped entirely instead of producing a useless WebDriverError in the output. (2) Patched `/usr/share/eyewitness/modules/selenium_module.py` to use Selenium 4 API (`options.accept_insecure_certs = True` instead of deprecated `DesiredCapabilities` dict) so self-signed HTTPS certs are actually accepted by the browser. Also wrapped `service_log_path` arg in try/except since it was removed in Selenium 4.
- **v10.151**: TLS fallback for old servers — after pre-flight TCP check passes, `_run_screenshot` now does a quick TLS handshake probe using `ssl.CERT_NONE` (accepts self-signed certs but not protocol failures). If TLS negotiation fails (e.g. TLS 1.0 with weak DH ciphers on old Java app servers like GlassFish 2.x / Tomcat 5), falls back to `http://` instead of `https://`. Self-signed certs still use `https://` correctly.
- **v10.152**: AI Phase 1 findings table sortable — clicking "Severity" or "Port" column headers sorts the table; clicking again reverses direction. Default sort is severity ascending. Sort state persists per session; secondary sort is always the opposite column asc. Works for both the main analysis table and the historical comparison table. JS `?v=102`.
- **v10.153**: AI export report sortable — the exported HTML report now embeds findings as JSON and includes a self-contained inline sort script. Clicking "Severity" or "Port" in the exported `.html` file re-sorts the table client-side with no server needed. Default sort is severity ascending; arrows indicate active column and direction. JS `?v=103`.
- **v10.154**: Delete host now cleanly removes all processes: (1) Queue drained BEFORE killing active processes so `checkProcessQueue()` inside `killProcess()` cannot start a newly-queued process for the deleted host mid-kill. (2) `_active_processes` evicted immediately for each killed process so the snapshot never shows stale data. (3) `process_matches` table deleted alongside `process`/`process_output`. (4) `_capture_output` thread checks `_deleted_hosts` on wake-up and skips all DB writes (output, elapsed, processFinished, nmap XML import) if the host was deleted while the process was running — prevents re-creating data after the host row is gone.
- **v10.155**: Tab scroll arrows — two ◀/▶ buttons added to the main tab bar next to the Font A−/A+ controls. Clicking scrolls the right-panel tab bar (Services/Scripts/Info/CVEs/Notes/AI + dynamic tool tabs) by 160px per click. Arrow opacity dims to 0.3 at each end so the user can see when there is nothing more to scroll. Opacity updates on every bar scroll event and on every `renderDynamicToolTabs` call. JS `?v=104`.
- **v10.156**: Purge and Delete host UI clearing fixed — Qt6 `clearViewsForHost` was never ported. Both actions now explicitly: clear `plain-output` (lower window), reset `L.selectedProcessId`, remove all dynamic tool tabs from the tab bar and container, delete `_hostUnreadTabs` for the host. Delete additionally deselects `L.selectedHostIp`/`Id` and resets the right panel to the first static tab. Purge server-side brought in line with v10.154 delete fixes: queue drained first, `_active_processes` evicted immediately, `process_matches` deleted. JS `?v=105`.
- **v10.157**: Two critical fixes to delete and purge: (1) `process_matches` table has no `process_id` column — it is keyed by `hostIp`. The `DELETE FROM process_matches WHERE process_id IN (...)` query threw `OperationalError: no such column: process_id`, aborting the entire transaction and leaving all host data intact. Fixed to `DELETE FROM process_matches WHERE hostIp = :ip`. (2) `_deleted_hosts.add(ip)` was called before the DB transaction, permanently blacklisting the host even when the delete failed. Moved to after successful commit.
- **v10.158**: 29 non-hollow Selenium tests for session fixes v10.146–v10.157. Port 5100, four classes: `TestCheckDuplicateUserTriggered` (layer-2 bypass), `TestTabScrollArrows` (◀/▶ scroll), `TestPurgeHostUI` (10 assertions across DOM/API/DB), `TestDeleteHostUI` (13 assertions). Integrated into `run_tests.sh --selenium`.
- **v10.159**: Rescan now clears all duplicate-blocking data before starting the new scan. Previously `runStagedNmap` was called raw — old `process`, `l1ScriptObj`, `portObj`, `cve`, and `process_matches` rows caused `checkDuplicate` to return `skip` for every scheduler tool and the screenshooter. Rescan now: drain queue, kill active processes, clear `_screenshots_taken` for the host, delete old scan rows (keeping hostObj + notes), then start staged nmap — identical to purge-then-scan.
- **v10.160**: Portscan submenu fix — two bugs: (1) the submenu `<div>` used `position:absolute` inside `list` which has `overflow-y:auto`; CSS overflow clips absolutely-positioned children that extend beyond the element boundary, making the submenu invisible. Fixed with `position:fixed` and `document.body` attachment so it renders above the clipping context. (2) clicking "Portscan ▸" bubbled to the document dismiss-handler and removed the whole menu before the submenu could be used. Fixed by adding a click handler that stops propagation and toggles the submenu. JS `?v=106`.
- **v10.161**: Three host right-click action fixes: (1) python-script-* routing checked `command` (action[2]) for the python-script- prefix, but conf entries have `/bin/echo` placeholder as the command — the prefix is on the key (action[1]). Added name-first detection + case-insensitive filesystem search so `python-script-PyShodan` correctly maps to `pyShodan.py`. (2) `leaksearch` had missing Python dependency `neotermcolor` — installed. (3) Audit of all 17 host-action items via live Selenium + API testing confirmed all create processes correctly; output appears in dynamic tabs when host is selected.
- **v10.147**: Screenshooter protocol bug — `_run_screenshot` was calling `isHttps(ip, port)` (a live SSL probe) to decide `http://` vs `https://`. Self-signed certs caused the probe to return `False`, so HTTPS services were always shot with `http://` (wrong URL, eyewitness fails). Fix: derive scheme from `svc_name` passed in from the scheduler (`'https' in svc` or `svc == 'ssl'` → `https://`). Also added `--no-verify` to the eyewitness command for HTTPS targets so self-signed certs don't block the screenshot.
- **conf fix**: 8 match keywords dropped in commit `2a065bf` ("global-positive match keywords for all new tools") were never restored: `exists`, `Command shell session`, `Got answer`, `[high]`, `(Status: 200)`, `[*] Received`, `(Status: 302)`, `valid password found`, `Netbios`. Not a code bug — a data/conf overwrite. Both repo `legion.conf` and live conf updated.
- **Test suite fixes** (commits 0b57e08→dced0ac): process table column shift from v10.136 checkbox — 12 test files updated from `cells[4]` (Status) to `cells[5]`, and `cells[1]` (Name) to `cells[2]`. User stories server startup fixed with `--no-prompt` flag. Conf drift root cause found: `test_ui_wiring.py` P6 activates the `default` profile, which copies `default.conf` → working conf; if `default.conf` is stale, it silently downgrades the live conf. Fix: `run_tests.sh` now syncs both `legion.conf` AND `profiles/default.conf` from the repo at startup AND before the selenium section. `B6 killProcess` race fixed: `storeProcessKillStatus` now committed BEFORE `os.kill()` so `_capture_output` threads see 'Killed' via `isKilledProcess()` before they run. `T1.2/REG3` window sizes increased (3000→5000, 200→1000 chars). `A1.x` tests updated for timestamped backup format. `ai_history.db` cleaned at test fixture start so accumulated entries don't break "no history" tests.

---

## Qt Replacement Patterns
```python
QMenu()                    → list of dicts
qProcess.start(cmd)        → subprocess.Popen(cmd, shell=True, stdout=PIPE, stderr=STDOUT)
QTimer.singleShot(ms, fn)  → threading.Timer(ms/1000, fn).start()
self.view.updateInterface() → no-op (browser polls /api/snapshot every 1.5s)
```

---

## Key Systems

### Screenshooter
- Configured in `[SchedulerSettings]`: `screenshooter="http,https,ssl,...", tcp`
- Runs via `runCommand`; requires eyewitness at `/usr/bin/eyewitness`
- Output served via `/api/screenshots?path=` (not `<path:filename>`)
- Screenshot PNG found by walking `{outputfile}-dir/` for first `.png`
- `_deleted_hosts` set — hosts added on delete; `_run_screenshot` skips blacklisted IPs

### Firefox Auto-Open (v10.29)
- `legion.py --web` fires `threading.Timer(1.5, _open_browser)` before `app.run()`
- Uses `sudo -u $SUDO_USER env DISPLAY=... XAUTHORITY=... firefox --no-remote --profile PATH`
- Profile: `~/.mozilla/firefox/legion-profile` — created + chown'd to SUDO_USER on first run
- `--no-remote`: prevents IPC with existing kali Firefox session (avoids "already running" error)
- Root cannot use kali's Xauthority cookie directly — must run as the original user

### Upper-Panel Scroll Preservation (v10.30)
- `renderDynamicToolTabs()` does `container.innerHTML=''` every 1.5s poll, destroying all `scrollTop`
- Fix: `_procScrollPos = {}` (module-level) maps processId → `'bottom'` | integer scrollTop
- Before wipe: iterate `dyn-output-*` elements, save `scrollHeight - scrollTop - clientHeight < 40 ? 'bottom' : scrollTop`
- `loadProcessOutput()` distinguishes: element has content (read actual scrollTop) vs. empty/fresh (read `_procScrollPos`)
- After innerHTML set: if saved position was a number, `setTimeout(() => el.scrollTop = saved, 0)` restores it

### Font Size Controls
- **Lower panel** (`legion_output_font_pt`): controls `#process-output-inline`, `#log-panel`, `_termState` xterm; buttons `output-font-dec`/`output-font-inc`, `log-font-dec`/`log-font-inc`
- **Upper panel** (`legion_upper_font_pt`): controls `#dynamic-tabs-container`, `_dynTermState` xterm; buttons `upper-font-dec`/`upper-font-inc` in right-panel tab bar

### Log Tab
- `_InMemoryLogHandler` in `app/logging/legionLog.py` — captures up to 10,000 lines
- Attached to `legion` logger automatically — works WITHOUT stdout redirect
- `/api/logs?level=INFO` reads in-memory buffer; falls back to `/tmp/legion-web.log`
- Switch to DEBUG level in Log tab to see snapshot/queue debug lines

### Font Size Control
- Buttons: `#output-font-dec` / `#output-font-inc` (lower panel), `#log-font-dec` / `#log-font-inc` (log panel)
- Set `font-size` on STABLE CONTAINER ELEMENTS (`#process-output-inline`, `#log-panel`, `#dynamic-tabs-container`)
- Children use `font:inherit` so cascade applies automatically to dynamic elements
- **Do NOT use `querySelectorAll('.tool-output-area')` or CSS `var()`** — both fail after tab switches

### Orange Tab Indicators
- `L._hostUnreadTabs` = `{hostId: {tabId: true}}` — persists across host switches
- `markTabUnread(tabId)` → adds CSS class AND saves to `_hostUnreadTabs[selectedHostId]`
- Host click → restores orange from `_hostUnreadTabs[newHostId]` before clearing
- Tab click → removes CSS class AND deletes from `_hostUnreadTabs[selectedHostId]`

### Version String
- `_VERSION` JS constant reads from `#window-title` DOM text at page load
- All places that update the title use `_VERSION` — **never hardcode version in JS**
- `legion.py` startup banner also reads version dynamically from `index.html` — never hardcode there either
- Only `index.html` needs updating for a version bump

### Process Queue Limits
- `max-fast-processes` → `general_max_fast_processes` → total concurrent non-interactive
- `max-slow-processes` → `general_max_slow_processes` → concurrent nmap only
- Wrong attr name was `general_max_concurrent_scans` (does not exist) — fixed in v10.4

---

## Pending Features — Approved Design Decisions

### Backlog #17 — ANSI Colour in Log Window

**Problem:** The Log tab shows raw ANSI escape codes (e.g. `\x1b[32m`) as literal text instead of rendering them as colour. The original bash terminal rendered these naturally.

**Scope:** Strip or render ANSI codes in the Log tab's output div. Same approach as #16.

**Implementation:** Same ANSI-to-HTML conversion used for #16 — apply to `/api/logs` response rendering in `legion.js`. The log lines come from `_InMemoryLogHandler` which captures Python logger output; tool subprocess output goes through `_capture_output` which also sends lines with ANSI codes.

**Key files:** `app/web/static/js/legion.js` (log tab render), `app/web/routes.py` (`/api/logs`), `app/logging/legionLog.py`

---

### Backlog #16 — ANSI Colour in Ctrl+B Notes

**Problem:** Notes captured via Ctrl+B (terminal copy-to-notes) contain raw ANSI escape sequences. The original Qt terminal rendered colour; the Flask notes panel shows raw codes.

**Scope:** When rendering note content in the notes panel, convert ANSI escape sequences to styled HTML spans before inserting into the DOM.

**Implementation options:**
- Use the `ansi_up` JS library (MIT, CDN or bundled) — `AnsiUp.ansi_to_html(text)` converts ANSI codes to `<span style="color:...">` HTML
- Or write a minimal ANSI-to-HTML converter for the subset of codes used by common terminals (30-37 foreground, 40-47 background, 1 bold, 0 reset)

**Key files:** `app/web/static/js/legion.js` (notes render function), `app/web/templates/base.html` (add ansi_up script tag if using library)

---

### Backlog #15 — Move Font Size Controls

**Problem:** The A+/A- font size buttons currently appear before the tab bar. They should be repositioned to after the Brute tab for better visual grouping with the content they control.

**Scope:** Move the `#output-font-dec` / `#output-font-inc` buttons in `index.html` to after the Brute tab button in the tab bar. Verify JS references still work (they use IDs, not position).

**Key files:** `app/web/templates/index.html`, `app/web/static/css/legion.css` (button styling may need adjustment)

---

### Backlog #19 — Kill Nmap Subprocesses on Exit

**Problem:** When Legion exits (SIGINT, SIGTERM, or browser close), nmap processes launched during staged scans keep running as orphaned OS processes. They consume CPU/bandwidth, write to temp files nobody is reading, and may interfere with the next Legion session (startup check marks them Crashed but the OS processes are still live).

**Scope:** On shutdown, kill every nmap (and other tool) subprocess that was spawned by this Legion instance. Must not kill nmap processes from other Legion instances running on a different port.

**Implementation:**
- `WebController` already has `_active_processes` dict (key = processId, value = `Process` object with `._popen`). On shutdown, iterate it and call `proc._popen.kill()` (SIGKILL) or `proc._popen.terminate()` (SIGTERM) for any process whose `._popen` is not None and `.poll()` is None (still running).
- `killRunningProcesses()` already does per-process kill + `storeProcessKillStatus()` — extend it to also `os.killpg(os.getpgid(proc._popen.pid), signal.SIGTERM)` so child processes of nmap (e.g. NSE scripts) are also killed.
- Call `killRunningProcesses()` from `_web_shutdown` (SIGINT/SIGTERM handler in `legion.py`) — **but NOT from `/api/shutdown`** (that fires on every browser refresh; see T16/v10.24).
- Also drain `fastProcessQueue` (already done in `killRunningProcesses()` per v10.24).
- Use process groups (`os.killpg`) not just the direct PID — nmap spawned with `shell=True` creates a shell child, so `proc._popen.pid` is the shell; the actual nmap binary is a grandchild. `os.killpg` kills the whole group.

**Key constraint:** Only kill processes belonging to THIS instance. Each Legion instance has its own `WebController` with its own `_active_processes` — there is no cross-instance leakage risk as long as we iterate our own dict.

**Key files:** `controller/web_controller.py` (`killRunningProcesses`, `_web_shutdown` signal handler), `legion.py` (`_web_shutdown`).

---

### Backlog #14 — Taller Tabs

**Problem:** The right-panel tab bar tabs are too short/thin, making them hard to click and visually cramped.

**Scope:** CSS-only change. Increase `min-height` / `padding` on the `.tab-btn` or equivalent tab button selector in `legion.css`.

**Key files:** `app/web/static/css/legion.css` — find `.tab-btn`, `#right-tabs button`, or similar selector; bump `padding-top`/`padding-bottom` or set explicit `height`.

---

### Backlog #13 — Update legion.conf Tool List

**Goal:** Retire unmaintained tools, fix broken command syntax for tools with new CLI APIs, and add modern tools that leading automated frameworks (AutoRecon, sn1per, reconFTW) use by default. The existing structure (HostActions, PortActions, PortTerminalActions, SchedulerSettings) stays intact — this is purely a conf update.

---

#### Tools to REMOVE (deprecated / unmaintained)

| Key | Reason |
|-----|--------|
| `dirbuster` | Last release 2012; Java GUI; replaced by feroxbuster/gobuster/ffuf. Remove from PortActions + SchedulerSettings |
| `enum4linux` | Replaced by `enum4linux-ng` (Python3 rewrite, actively maintained, better output) |
| `unicornscan-full-udp` | Barely maintained; nmap `-sU` with `--min-rate` covers this adequately |
| `cloudfail` | Unmaintained; depends on dead APIs; remove from PortActions |
| `dnsmap` | Replaced by `dnsrecon` and `amass`; confusingly named for IP targets |
| `cutycapt-path` in ToolSettings | eyewitness is already used for screenshooter; cutycapt is X11-only and unmaintained |
| `rdp-sec-check` (Perl `./scripts/rdp-sec-check.pl`) | Replace with `rdp-sec-check` Kali package (`/usr/bin/rdp-sec-check`) |
| `http-wapiti` / `https-wapiti` | Wapiti v3+ CLI changed completely; old command format breaks silently |
| `theharvester` | Command syntax changed significantly in v4+; `-n/-c/-t/-h` flags removed |

---

#### Tools to UPDATE (still valid, command syntax changed)

| Key | Old command issue | New command |
|-----|------------------|-------------|
| `wpscan` | Missing `--no-update` (network call on every run, slow/fails offline) | `wpscan --url http://[IP]:[PORT] --no-update --enumerate p,u,t` |
| `sslyze` | `--regular` flag removed in v5+ | `sslyze [IP]:[PORT]` (auto-scans all protocols) |
| `sslscan` | `--no-failed` still valid; add `--show-certificate` | `sslscan --show-certificate [IP]:[PORT]` |
| `whatweb` | Still valid; add aggression flag | `whatweb -a 3 [IP]:[PORT] --color=never --log-brief=[OUTPUT].txt` |
| `theharvester` (if kept) | Old flags `-n -c -t -h` removed | `theHarvester -d [IP] -b all -f [OUTPUT]` |
| `smtp-user-enum` (EXPN/RCPT/VRFY) | Still valid; add `-v` for output | add `-v` flag |
| StagedNmapSettings | stage2/stage6 numbering swapped from NSE to vulners (already fixed in v10.18/v10.19) | verify ordering in conf matches CLAUDE.md |

---

#### Tools to ADD (HostActions)

| Key | Command | Service filter | Why |
|-----|---------|---------------|-----|
| `masscan-fast` | `masscan [IP] -p1-65535 --rate=1000 --open-only -oG [OUTPUT].txt` | `""` | Top-speed TCP port sweep; pairs with nmap for confirmation |
| `dnsrecon` | `dnsrecon -d [IP] -a -s -g -b -k -w -z --xml [OUTPUT].xml` | `""` | Replaces dnsmap; covers zone transfer, SRV, bruteforce, Google |
| `amass-passive` | `amass enum -passive -d [IP] -o [OUTPUT].txt` | `""` | Passive subdomain discovery (OSINT sources only, no active probing) |

---

#### Tools to ADD (PortActions)

**Web / HTTP:**
| Key | Command | Service filter |
|-----|---------|---------------|
| `feroxbuster` | `feroxbuster -u http://[IP]:[PORT] -w /usr/share/wordlists/dirb/big.txt -o [OUTPUT].txt --no-state` | `"http,https,ssl,soap,http-proxy,http-alt,https-alt"` |
| `feroxbuster-https` | `feroxbuster -u https://[IP]:[PORT] -w /usr/share/wordlists/dirb/big.txt -k -o [OUTPUT].txt --no-state` | `"https,ssl,https-alt"` |
| `gobuster-dir` | `gobuster dir -u http://[IP]:[PORT] -w /usr/share/wordlists/dirb/common.txt -o [OUTPUT].txt` | `"http,https,ssl,soap,http-proxy,http-alt,https-alt"` |
| `ffuf-vhosts` | `ffuf -u http://[IP]:[PORT] -H "Host: FUZZ.[IP]" -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt -o [OUTPUT].txt` | `"http,https,ssl"` |
| `nuclei` | `nuclei -u http://[IP]:[PORT] -o [OUTPUT].txt -silent` | `"http,https,ssl,soap,http-proxy,http-alt,https-alt"` |
| `nuclei-https` | `nuclei -u https://[IP]:[PORT] -o [OUTPUT].txt -silent` | `"https,ssl,https-alt"` |
| `testssl` | `testssl --quiet --color 0 [IP]:[PORT] > [OUTPUT].txt 2>&1` | `"https,ssl,https-alt"` |

**SMB / Windows:**
| Key | Command | Service filter |
|-----|---------|---------------|
| `netexec-smb` | `netexec smb [IP] -u '' -p '' --shares 2>&1 \| tee [OUTPUT].txt` | `"netbios-ssn,microsoft-ds"` |
| `smbmap` | `smbmap -H [IP] -P [PORT] 2>&1 \| tee [OUTPUT].txt` | `"netbios-ssn,microsoft-ds"` |
| `enum4linux-ng` | `enum4linux-ng -A [IP] 2>&1 \| tee [OUTPUT].txt` | `"netbios-ssn,microsoft-ds"` |
| `ldapdomaindump` | `ldapdomaindump -u '' -p '' ldap://[IP]:[PORT] -o [OUTPUT]-ldapdump 2>&1` | `"ldap,ldaps"` |
| `kerbrute-users` | `kerbrute userenum -d DOMAIN --dc [IP] /usr/share/seclists/Usernames/xato-net-10-million-usernames-dup.txt -o [OUTPUT].txt` | `"kerberos,kerberos-sec"` |

**SSH:**
| Key | Command | Service filter |
|-----|---------|---------------|
| `ssh-audit` | `ssh-audit [IP] -p [PORT] > [OUTPUT].txt 2>&1` | `"ssh"` |

**DNS:**
| Key | Command | Service filter |
|-----|---------|---------------|
| `dnsrecon-port` | `dnsrecon -d [IP] -a -z --xml [OUTPUT].xml` | `"domain"` |
| `dnsenum` | `dnsenum --noreverse -o [OUTPUT].xml [IP]` | `"domain"` |

**Databases (new services):**
| Key | Command | Service filter |
|-----|---------|---------------|
| `redis-info` | `redis-cli -h [IP] -p [PORT] info > [OUTPUT].txt 2>&1` | `"redis"` |
| `redis-unauth` | `redis-cli -h [IP] -p [PORT] CONFIG GET maxmemory > [OUTPUT].txt 2>&1` | `"redis"` |
| `mongodump-list` | `mongo [IP]:[PORT] --eval "db.adminCommand({listDatabases:1})" --quiet > [OUTPUT].txt 2>&1` | `"mongod"` |

**WinRM:**
| Key | Command | Service filter |
|-----|---------|---------------|
| `winrm-check` | `netexec winrm [IP] -u administrator -p '' 2>&1 \| tee [OUTPUT].txt` | `"wsman,ms-wbt-server"` |

---

#### PortTerminalActions to ADD

| Key | Command | Service filter |
|-----|---------|---------------|
| `evil-winrm` | `[term] evil-winrm -i [IP] -P [PORT]` | `"wsman"` |
| `netexec-shell` | `[term] netexec smb [IP] -u administrator -p ''` | `"netbios-ssn,microsoft-ds"` |
| `redis-cli` | `[term] redis-cli -h [IP] -p [PORT]` | `"redis"` |
| `mongo-shell` | `[term] mongo [IP]:[PORT]` | `"mongod"` |

---

#### SchedulerSettings to ADD (auto-run on service discovery)

| Key | Service | Protocol |
|-----|---------|----------|
| `feroxbuster` | `"http,https,ssl"` | tcp |
| `nuclei` | `"http,https,ssl"` | tcp |
| `enum4linux-ng` | `microsoft-ds` | tcp |
| `ssh-audit` | `ssh` | tcp |
| `netexec-smb` | `microsoft-ds` | tcp |

---

#### Implementation Notes

- **SecLists dependency**: several new commands reference `/usr/share/seclists/` — add install check or use `dirb` wordlists as fallback. On Kali: `apt install seclists`.
- **netexec vs crackmapexec**: `crackmapexec` was renamed to `netexec` in Kali 2024.1+. Add both keys, detect which is present (`which netexec || which crackmapexec`), or just use `netexec` (Kali default).
- **nuclei templates**: first run downloads templates to `~/.local/nuclei-templates`; add `--no-update-templates` flag after initial download to avoid network calls during scans.
- **kerbrute**: requires a domain name, not just an IP — the `DOMAIN` placeholder needs either a legion.conf setting or a prompt; skip adding to SchedulerSettings until domain discovery is wired.
- **RDP**: existing `rdp-sec-check` Perl script → replace with `rdp-sec-check [IP]:[PORT]` (Kali package at `/usr/bin/rdp-sec-check`).
- **conf file vs runtime**: changes go to `/root/.local/share/legion/legion.conf` AND to the repo's default conf (if one exists). Use the Backlog #10 Tool Manager GUI when that's built.
- **Order of implementation**: (1) removals + syntax fixes first (no new deps), (2) web tools (feroxbuster/gobuster/nuclei), (3) SMB tools (netexec/smbmap/enum4linux-ng), (4) SSH audit + SSL (testssl), (5) databases (redis/mongo), (6) SchedulerSettings wiring.

---

### Backlog #12 — Fix Hydra SSH Against Legacy Targets (libssh2 MAC Incompatibility)

**Problem:** Hydra's bundled libssh2 only offers modern MACs (`hmac-sha2-256-etm`, etc.). Targets running OpenSSH ≤ 5.x (e.g. Metasploitable's OpenSSH 4.7) only accept legacy MACs (`hmac-md5`, `hmac-sha1`). Hydra has no flag to configure this — it's compiled into libssh2. Result: Hydra SSH silently fails with `kex error: no match for method mac algo`.

**Scope:**
- Rebuild Hydra's libssh2 with legacy MAC support enabled, OR
- Add a fallback SSH brute-force path using `medusa -M ssh` (supports legacy targets) when Hydra SSH fails with a MAC error, OR
- Allow the brute tab to select between Hydra and Medusa per-service

**Recommended approach (option B — medusa fallback):**
- Detect `kex error` / MAC negotiation failure in `_capture_output` for SSH Hydra runs
- Re-queue the same brute job using `medusa -h [IP] -u [user] -P [wordlist] -M ssh` (medusa uses OpenSSH libs, respects system SSH config)
- Add `medusa-path` to `[ToolSettings]` in legion.conf (default: `/usr/bin/medusa`)
- Fallback is transparent — same result parsing, same DB storage

**Test coverage needed:**
- H1.1/H1.2: currently `skipIf(kex error)` — after fix they should pass against Metasploitable SSH
- Verify medusa is installed: `which medusa` (kali: `apt install medusa`)

**Notes:**
- OpenSSH CLIENT flags (`-oHostKeyAlgorithms=+ssh-rsa`) do NOT help — Hydra does not use the OpenSSH binary for SSH brute forcing
- Medusa SSH module uses the system's OpenSSH libraries, which support `+ssh-rsa` and legacy MACs via config
- FTP (H3) and MySQL (H2) remain reliable Hydra targets and are unaffected

### LLM AI Tab — Full Design Spec (Backlog #7)

#### Authentication — Vertex AI (NOT direct Anthropic API)
- **SDK**: `anthropic[vertex]` — `from anthropic import AnthropicVertex`
- **Credentials**: ADC (Application Default Credentials) via `gcloud auth application-default login` — already done daily, no prompt needed
- **Config source**: Read `~/.claude/settings.json` at analysis time
  - `ANTHROPIC_VERTEX_PROJECT_ID` → `project_id` (e.g., `"viasat-claude-code"`)
  - `CLOUD_ML_REGION` → `region` (e.g., `"global"`)
  - `model` → strip `[1m]` suffix → e.g., `"claude-sonnet-4-6"`
- **No API key storage anywhere** — ADC handles auth transparently

#### UI Placement
- New **"AI"** tab in right-panel tab bar (alongside Info, Ports, Scripts, Notes, CVEs)
- Tab contains: blocking-conditions banner OR analyze button + cost estimate, then Phase 1 table + Phase 2 markdown side-by-side with historical match

#### Routes
- `POST /api/ai/analyze-host/<host_id>` — runs Phase 1 + Phase 2, saves results, returns JSON
- `GET /api/ai/history/similar/<host_id>` — returns Jaccard-ranked list of similar hosts from persistent DB
- `GET /api/ai/host/<host_id>/latest` — returns most recent saved analysis for this host from project DB

#### Blocking conditions (shown in AI tab before Analyze button)
- Button is disabled and conditions are listed when:
  - Any process for this host has status `Running` or `Waiting`
  - Interactive (PTY) processes are **ignored** — only Regular processes count
- When all non-interactive processes are Finished/Crashed: show Analyze button with estimated cost

#### User flow
1. User selects host → AI tab shows blocking status OR Analyze button
2. User clicks **"Analyze (~$X.XX)"** button
3. Server searches persistent history DB for hosts with ≥95% Jaccard similarity
4. If matches found: dropdown appears — `"192.168.85.11 — 2026-03-10 — 97% match — Linux, 22 ports"` — user picks one (or "None") for side-by-side
5. Spinner shown, Phase 1 runs (Synthesizer), Phase 2 runs (Attack Planner)
6. Results displayed + saved to both DBs
7. If comparison selected: left panel = current analysis, right panel = historical match

#### Similarity fingerprint (Jaccard)
- **Fingerprint**: sorted list of `"port/protocol:service:version"` tuples + OS family string
  - Example: `["22/tcp:ssh:OpenSSH 4.7p1", "80/tcp:http:Apache 2.2.8", ...]` + `"Linux"`
- **Similarity**: `|intersection| / |union|` of the two fingerprint sets
- **Threshold**: ≥ 0.95 to appear in dropdown
- Stored as JSON in the persistent history DB

#### Two-phase pipeline

**Why two phases**: Raw tool output is noisy. Phase 1 normalizes and deduplicates findings across all tools before Phase 2 reasons about exploitation — preventing the planner from wasting context on verbose output headers.

**Phase 1 — Synthesizer**
Input assembled in order:
| Data | Source | Notes |
|------|---------|-------|
| Host (IP, hostname, OS, status) | `hostObj` | Always included |
| Open ports + services | `getPortsAndServicesByHostIP` | Core findings |
| CVEs | `getCVEsByHostIP` | From vulners NSE |
| NSE scripts + output | `getScriptsByHostIP` | Per-port detail |
| Analyst notes | `getNoteByHostId` | Human observations |
| Tool outputs | `getProcesses(hostIp=ip)` | Matched processes first, then by id desc; 2000 chars max each; skip empty |

System prompt: *"You are a data extraction assistant. Extract all significant security findings from this raw penetration test data. Output structured JSON only: an array of findings, each with fields: source (tool name), port (if applicable), severity (critical/high/medium/low/info), finding (one sentence), evidence (brief quote from output). Deduplicate. Omit informational noise."*

Output: `[{source, port, severity, finding, evidence}, ...]`

**Phase 2 — Attack Planner**
Input: compact Phase 1 JSON (no raw output noise)

System prompt: *"You are a senior penetration tester. Given these confirmed findings from a target host, identify: 1) exploitable vulnerabilities with specific CVEs or techniques, 2) recommended next tools and exact commands, 3) likely attack paths ranked by probability of success, 4) misconfigurations to investigate. Be specific and actionable."*

Output: Markdown attack plan

#### Phase 1 display — sortable findings table
Columns: **Severity** (colour-coded) | **Source** | **Port** | **Finding** | **Evidence**
- Critical = red, High = orange, Medium = yellow, Low = blue, Info = grey
- "View as JSON" toggle shows raw JSON in a `<pre>` block
- Default sort: Severity desc

#### Phase 2 display — rendered Markdown
- Standard Markdown rendering (bold, bullets, code blocks)

#### Side-by-side comparison layout
```
┌─────────────────────┬─────────────────────┐
│  Current Host       │  Historical Match   │
│  192.168.1.10       │  192.168.85.11      │
│  (just analyzed)    │  97% match, 2026-03 │
├─────────────────────┼─────────────────────┤
│  Phase 1 table      │  Phase 1 table      │
│  Phase 2 markdown   │  Phase 2 markdown   │
└─────────────────────┴─────────────────────┘
```
Historical match selected from dropdown; "No similar hosts in history" shown greyed-out when none found.

#### Cost display
- **Before**: button label shows `"Analyze (~$X.XX)"` — estimated from assembled input size × 0.25 tokens/char × sonnet-4-6 pricing ($3/MTok input, $15/MTok output, assuming ~1k output tokens)
- **After**: tab header shows `"Cost: $X.XX | 24k tokens"` using actual usage from API response
- **Cached (historical)**: shows `"Previously cost $X.XX — no charge for this view"`

#### Concurrent analyses
Multiple hosts can be analyzed simultaneously — each `POST /api/ai/analyze-host/<id>` runs in its own Flask thread. No global lock.

#### Databases

**Persistent AI history DB** — `~/.local/share/legion/ai_history.db` (SQLite, never deleted, survives project switches)
```sql
CREATE TABLE ai_sessions (
  id INTEGER PRIMARY KEY,
  timestamp TEXT,
  host_ip TEXT,
  project_name TEXT,
  fingerprint_json TEXT,   -- sorted port:service:version list + OS
  phase1_json TEXT,        -- synthesizer output
  phase2_markdown TEXT,    -- planner output
  tokens_input INTEGER,
  tokens_output INTEGER,
  cost_usd REAL
);
```

**Project DB** — new `ai_analysis` table in the `.legion` SQLite file (loaded when project opens)
```sql
CREATE TABLE ai_analysis (
  id INTEGER PRIMARY KEY,
  host_id INTEGER,
  timestamp TEXT,
  phase1_json TEXT,
  phase2_markdown TEXT,
  tokens_input INTEGER,
  tokens_output INTEGER,
  cost_usd REAL,
  history_session_id INTEGER   -- FK into persistent DB for cross-reference
);
```
Both writes happen atomically after both API calls complete successfully.

#### Dependencies
```bash
pip install "anthropic[vertex]"
```

### Pending Feature Backlog
| # | Feature | Difficulty | Status | Notes |
|---|---------|-----------|--------|-------|
| 1 | Port state filter on Services table | Low | ✅ Done v10.0 | |
| 2 | Comma/newline multi-host + parallel nmap processes | Low | ✅ Done v10.0 | |
| 3 | Font size control in output windows | Low | ✅ Done v10.1 | |
| 4 | Config editor find/search (F2) | Low–Med | ✅ Done v10.8 | |
| 5 | Terminal notes Ctrl+B | Med | ✅ Done v10.9 | |
| 6 | Parallel nmap stages | High | ✅ Done v10.19 | PORTS parallel; NSE last with all ports |
| 7 | LLM host analysis (AI tab) | Med | ✅ Done v10.55 | Vertex AI, two-phase, history DB, Jaccard similarity, side-by-side |
| 8 | Save-on-exit prompt | Low | ✅ Done v10.3 | |
| 9 | Auto per-service NSE scripts after discovery | Med | ❌ Not started | Flask only; after #7 |
| 10 | Tool manager GUI — add/remove tools from legion.conf | Med | ✅ Done v10.117 | Easy Mode in F2: searchable tables for HostActions/PortActions/PortTerminalActions/SchedulerSettings; inline [IP]/[PORT] validation |
| 11 | Settings GUI — change GeneralSettings/BruteSettings/etc in a form | Med | ✅ Done v10.117 | Easy Mode in F2: labeled forms for General/Brute/Tool/StagedNmap settings; typed inputs per field |
| 12 | Fix Hydra SSH against legacy targets (libssh2 MAC incompatibility) | Med | ❌ Not started | See design below |
| 13 | Update legion.conf tool list — retire deprecated tools, add modern equivalents | Med | ✅ Done v10.28 | install_tools.sh + update script; both confs updated |
| 14 | Taller tabs — increase height of the right-panel tab bar tabs | Low | ✅ Done v10.31 | .tab-btn padding 12px → 15px top/bottom |
| 15 | Move font size controls — relocate A+/A- buttons to after the Brute tab | Low | ✅ Done v10.31 | upper-font controls moved to main-tab-bar after Brute button |
| 16 | ANSI colour in Ctrl+B notes — render terminal colour codes in the notes panel | Med | ✅ Done v10.31/v10.50 | renderNotes() uses ansiToHtml(); domSelectionToAnsi() for DOM selections |
| 17 | ANSI colour in log window — render colour codes in the Log tab output | Med | ✅ Done v10.31 | loadLog() uses ansiToHtml() instead of textContent |
| 18 | Sticky processes table header — keep column headers visible during scroll | Low | ✅ Done v10.54 | moved sticky from `th` to `thead` — border-collapse:collapse breaks per-cell sticky |
| 19 | Kill nmap subprocesses on exit — orphaned nmap scans survive Legion shutdown | Med | ✅ Done v10.53 | _kill_all_descendants() via /proc BFS scan; called from killRunningProcesses() |
| 20 | Splitter centre start — bottom splitter defaults to 50% height on first load | Low | ✅ Done v10.59 | JS sets offsetHeight/2 when no localStorage value exists |
| 21 | All splitters draggable — proc/os/scripts/tools vsplitters were wired cursor-only | Low | ✅ Done v10.60 | IDs added to targets; initSplitter calls + flex-pinning on mousedown; localStorage persistence |
| 22 | Tab bar scrollbar always visible — right-panel tab bar scrollbar was hidden | Low | ✅ Done v10.61 | overflow-x:scroll; 8px track; #888 thumb; global thumb brightened #454545→#777 |
| 23 | Scan tab state restoration — active right-panel tab reset to Services on Brute→Scan | Low | ✅ Done v10.62 | initTabBar: c.closest('.tab-widget')===widget guard; only same-level .active stripped |
| 24 | Match navigation arrows — ▲/▼ in output banner to jump between match spans | Med | ✅ Done v10.63 | _matchNavState{}, _matchNavInit(), _matchNav(); sticky banner; .match-current; upper+lower panels |
| 25 | Font size all output panels — upper A+/A- applies to script/notes/tool/AI panels | Low | ✅ Done v10.69/71 | Added to applyFontSize() array; flex-basis must be set alongside width |
| 26 | Context menu stays in viewport — clamped to window.innerHeight/Width | Low | ✅ Done v10.72 | Append hidden, measure, clamp, then show; submenus flip left/up if overflowing |
| 27 | Go to Tab improvements — scrollIntoView + cross-host navigation | Med | ✅ Done v10.73 | _pendingGotoTab; renderDynamicToolTabs picks up after async loadHostDetail |
| 28 | Context menu scrollable — port action lists no longer clip at viewport bottom | Low | ✅ Done v10.75 | max-height:calc(100vh-16px);overflow-y:auto on menu element |
| 29 | Filter label "Waiting" not "Queued" | Low | ✅ Done v10.77 | Display text only; value="Waiting" was already correct |
| 30 | All nmap stage commands in Notes — deferred write for first-time scans | Med | ✅ Done v10.79 | _pending_scan_notes dict; _stage_completed writes after XML import |
| 31 | Process timeout — kill non-nmap processes after N seconds | Med | ✅ Done v10.81 | general_process_timeout in legion.conf; watchdog in _capture_output; _kill_subtree fix |
| 32 | Remove credential-requiring impacket from scheduler | Low | ✅ Done v10.83 | getnpusers/getuserspns/lookupsid/secretsdump removed; rpcdump kept |
| 33 | Splitter snap-to-zero fix — flex-basis must be set with width | Low | ✅ Done v10.85 | startSize read before flex pin; flexBasis set in mousedown + mousemove + restore |
| 34 | Horizontal splitter direction — drag down expands top | Low | ✅ Done v10.86 | Negated delta for isH case |
| 35 | Clear process clears lower output window | Low | ✅ Done v10.87 | plain-output.textContent='' when cleared process is selected |
| 36 | Host input comma validation — octet shorthand only | Low | ✅ Done v10.88/89 | post-comma tokens must be isdigit(); error shown in dialog without closing |
| 37 | All nmap scan types write to Notes (Easy + Hard) | Low | ✅ Done v10.90/91 | _pending_scan_notes in addHosts; written in _capture_output after XML import |
| 38 | Add hosts dialog shows server errors | Low | ✅ Done v10.92 | .then() checks data.error; validation element shown; dialog stays open |
| 39 | AI Phase 1/2 split — Phase 2 on-demand | Med | ✅ Done v10.93 | run_phase1/run_phase2 in analyzer.py; /phase1 /phase2 routes; _aiRunning state |
| 40 | Ctrl+B most-recent-selection wins | Low | ✅ Done v10.94 | xterm fallbacks guarded by !_lastNonXtermSelSource |
| 41 | Config manager timestamped backups + activation validation | Med | ✅ Done v10.95 | _backup_conf() → backup/; profile validate before activate |
| 42 | Professional README.md — full feature docs, install, usage, architecture | Med | ❌ Not started | Replace the GoVanguard stub; cover Flask web UI, all major features, screenshots |
| 43 | Animated GIF demos — screen-captured walkthroughs of key workflows | Med | ❌ Not started | Suggest: scan→results, AI analysis, Ctrl+B, match navigation, Tools tab, config manager |
| 44 | Capability difference tables — GoVanguard legacy vs Tim McLean additions | Low | ❌ Not started | HTML + Markdown versions; three-tier value ranking; already drafted in legion_features.html and legion_value_ranking.html |

### Backlog #42 — Professional README.md

**Goal:** Replace the current minimal GoVanguard stub with a complete, professional README that a new user can follow to install, run, and understand Legion.

**Sections to include:**
- Hero section: what Legion is, who it is for, key differentiators from upstream
- Screenshot / GIF banner (placeholder until #43 is done)
- Features list — link to the capability table from #44
- Requirements (Python 3.10+, Kali Linux recommended, geckodriver for tests)
- Installation: `git clone`, `pip install -r requirements.txt`, `sudo python3 legion.py --web`
- Quick-start walkthrough (add host → scan → view results → AI analysis)
- Configuration: legion.conf sections, key settings, profiles
- Architecture overview: Flask web server, WebController, staged nmap, scheduler
- Test suite: `sudo bash run_tests.sh` options
- Credits: GoVanguard / Sparta upstream, ifly53e Qt5 work, Tim McLean Flask rewrite

**Key files:**
- `README.md` (rewrite entirely)
- `docs/` folder for screenshots if needed

---

### Backlog #43 — Animated GIF Demos

**Goal:** Short (15–30 second) screen-captured GIFs embedded in README.md showing the most visually compelling workflows.

**Suggested demos:**
1. **Scan workflow** — Add host → nmap stages run with progress % → ports/services appear → vulners CVEs populate → AI analysis
2. **AI tab** — Click Analyze → Phase 1 findings table → Get Attack Advice → Phase 2 attack plan
3. **Match detection** — feroxbuster finds /proof → red highlight in tool list → navigation arrows jump to match
4. **Ctrl+B notes** — Select terminal output → Ctrl+B → note appears in correct host's Notes tab with ANSI colour
5. **Config manager** — Open F2 → edit profile → save → live-apply confirms settings hot-reloaded
6. **Tools tab** — Click Tools → auto-selects first tool → all three panes populate → scroll host list

**Tooling:** `peek` or `byzanz-record` on Kali, crop to relevant region, keep < 5 MB each.

**Key files:**
- `docs/demos/` — GIF files
- `README.md` — embed with `![demo](docs/demos/scan-workflow.gif)`

---

### Backlog #44 — Capability Difference Tables

**Goal:** Formal Markdown and HTML tables comparing GoVanguard legacy Legion to Tim McLean's Flask rewrite, suitable for README and standalone reference.

**Already drafted:**
- `legion_features.html` — full capability matrix (GoVanguard vs Tim McLean columns, ✓ marks, NEW/RETIRED badges, dark-themed HTML)
- `legion_value_ranking.html` — three-tier value ranking (High / Medium / Low) with category badges

**Remaining work:**
- Convert HTML tables to clean Markdown for README embed
- Add a concise summary card (e.g. "86 legacy features carried forward, 149 new additions")
- Publish to a `docs/` folder alongside the GIFs
- Link from README features section

**Key files:**
- `docs/capabilities.md` — Markdown version
- `legion_features.html` / `legion_value_ranking.html` — existing HTML (already complete)

---

### Backlog #10 — Tool Manager GUI
Allows adding and removing tool entries (HostActions, PortActions, PortTerminalActions, SchedulerSettings) via a form instead of raw conf editing.

**Scope:**
- Add a new tool: label, command template (with [IP]/[PORT]/[OUTPUT] placeholders), service filter, target section
- Remove an existing tool: select from list, confirm, delete
- Edit an existing tool: load into form, modify, save
- Validate command format (`validateCommandFormat`) and service filter before saving
- Writes changes to `legion.conf` via the existing `/api/settings/legion-conf` save route
- Does NOT replace the Config Manager raw editor — both coexist

**UI placement:** New tab or modal accessible from the Config Manager (F2) — e.g. "Tools" tab alongside the raw editor

**Sections managed:** `[HostActions]`, `[PortActions]`, `[PortTerminalActions]`, `[SchedulerSettings]`

---

### Backlog #11 — Settings GUI
Allows changing `[GeneralSettings]`, `[BruteSettings]`, `[ToolSettings]`, and `[StagedNmapSettings]` via labeled form controls instead of raw legion.conf editing.

**Scope:**
- Each known setting gets a typed control: text input, checkbox, number input, or dropdown
- GeneralSettings: max-fast-processes, max-slow-processes, screenshooter-timeout, tool-duplication (dropdown: skip/newTab/append/askMe), web-services, enable-scheduler, etc.
- BruteSettings: default-username, default-password, wordlist paths, no-username/password-services, store-cleartext-passwords-on-exit
- ToolSettings: nmap-path, hydra-path, pyshodan-api-key
- StagedNmapSettings: stage1-6 port specs (text inputs, validated with the PORTS|/NSE| format check)
- Live validation before save (reuse `_validate_legion_conf`)
- Saves via `/api/settings/legion-conf` and triggers `applySettings()`
- Does NOT replace the raw Config Manager editor — both coexist

**UI placement:** New "Settings" tab in the Config Manager (F2) alongside the raw editor tab

### legion.conf Settings
#### Already wired
| Setting | Where |
|---------|-------|
| `nmap-path` | `tools_path_nmap` — used in all nmap commands |
| `hydra-path` | `tools_path_hydra` — used in `brute_run` route |
| `default-username` / `default-password` | Pre-fill brute tab — ✅ v10.6 |
| `username-wordlist-path` / `password-wordlist-path` | Pre-fill brute tab — ✅ v10.6 |
| `no-username-services` / `no-password-services` | Hide brute fields — ✅ v10.6 |
| `store-cleartext-passwords-on-exit` | Delete wordlist files on close — ✅ v10.7 |
| `screenshooter-timeout` | eyewitness delay — ✅ v10.7 |
| `tool-output-black-background` | black-bg CSS toggle — ✅ v10.7 |

#### Still unwired
| Setting | Fix needed |
|---------|-----------|
| `pyshodan-api-key` | Pass as env var `SHODAN_API_KEY` when invoking `pyShodan.py` |

---

## Comprehensive Troubleshooting Log

### T1 — Stale port sockets causing Selenium test failures
**Symptom**: `test_selenium_gaps` or `test_selenium_ui` fail with `OSError: [Errno 98] Address already in use`. 31/32 tests pass, 1 fails intermittently. Different test fails each run.
**Root cause**: When a pytest session ends, the daemon Flask thread takes time to die, leaving the socket in LISTEN state briefly. Next pytest session tries to bind the same port and fails. The driver connects to the OLD server (different WebController), so `wc.runCommand()` processes never appear in the UI.
**Fix**: `free_port()` in `run_tests.sh` — uses `ss -tlnp "sport = :PORT"` to get PID directly, kills it, polls `ss` until port is confirmed free (up to 10s).
**Prevention**: `run_tests.sh` calls `free_port NNNN` before each Selenium suite. Also kills all test ports (5094–5099) in initial prep.
**Key file**: `run_tests.sh` — `free_port()` function

### T2 — checkDuplicate (Gap A8) silently blocking all user-triggered port actions
**Symptom**: After a scan, right-clicking a port and running nikto/dirbuster/etc does nothing — no process appears, no tab opens.
**Root cause**: Gap A8 added `checkDuplicate()` to `handleHostToolAction` and `handleServiceNameAction`. The condition was `if dup_mode != 'run': skip` which blocked ALL modes including `newTab`, `append`, and `askMe`. In Qt6, these modes showed a dialog; in Flask they silently did nothing.
**Fix**: Change to `if dup_mode == 'skip': skip`. Only the explicit `skip` mode blocks. `newTab` and `append` run (creating a new process, which is the Flask equivalent). `askMe` runs (user's explicit right-click is sufficient intent).
**Prevention**: Always test port action right-click after implementing any `checkDuplicate` changes.
**Commit**: `0bf2770`

### T3 — Stale version strings in legion.js
**Symptom**: Title bar shows `v7.4-flask` after clicking a host, `v2.9-flask` after Save/Open.
**Root cause**: 6 hardcoded version strings in `legion.js` — `loadHostDetail`, Save, Open, Save As, New, Help alert all had old versions hardcoded.
**Fix**: `_VERSION` JS constant reads correct version from `#window-title` DOM text at page load. All 6 strings replaced with `_VERSION + ' – ' + suffix`.
**Prevention**: NEVER hardcode version in JS. Only update `index.html`. JS reads it automatically.
**Commit**: `59ce9a3`

### T4 — Font size buttons stop working after tab switch
**Symptom**: A+/A- buttons work initially. After switching to Log tab, increasing font, then switching back to Processes — buttons appear to do nothing.
**Root cause (attempt 1)**: `querySelectorAll('.tool-output-area')` only catches elements in DOM at call time. After snapshot poll rebuilds dynamic tab elements, the inline style is lost.
**Root cause (attempt 2)**: CSS `var(--output-font-size)` on `:root` conflicts with `font:inherit` in `.tool-output-area`. Also requires server restart to pick up new CSS rule.
**Final fix**: Set `font-size` on three STABLE CONTAINER elements (`#process-output-inline`, `#log-panel`, `#dynamic-tabs-container`). Children use `font:inherit` — change cascades automatically to all output areas including dynamically created ones. No CSS changes needed.
**Prevention**: Font control must target containers, not leaf elements. Dynamic tabs are recreated every 1.5s.
**Commit**: `eed2345`

### T5 — Orange tab indicators lost when switching hosts
**Symptom**: Tabs turn orange (tab-unread) when data changes. Switching to another host and back — orange is gone even though the content was never viewed.
**Root cause**: Host click handler stripped ALL `tab-unread` classes on every host switch. `markTabUnread` only re-fires when data changes again — if nothing changed since last visit, orange never returns.
**Fix**: `L._hostUnreadTabs = {hostId: {tabId: true}}`. `markTabUnread()` saves state; host click restores orange from the dict for the new host; tab click deletes from the dict.
**Commit**: `9c9188a`

### T6 — nmap --stats-every 10s → 5s: sed missed list format
**Symptom**: After running `sed -i 's/--stats-every 10s/--stats-every 5s/g'`, test F1.1 still failed showing `runStagedNmap=False`.
**Root cause**: `addHosts` uses f-string format `'--stats-every 10s'` (caught by sed). `runStagedNmap` uses list format `['--stats-every', '10s']` (not caught by simple string sed).
**Fix**: Second `sed -i "s/'--stats-every', '10s'/'--stats-every', '5s'/g"` for the list format. Test updated to check for both forms.
**Prevention**: When searching for string patterns in Python code, check both f-string and list/tuple forms.

### T7 — max_scans attribute name wrong (general_max_concurrent_scans doesn't exist)
**Symptom**: `max-slow-processes` in `legion.conf` had no effect on nmap concurrency. Always used fallback of 3.
**Root cause**: `checkProcessQueue()` read `general_max_concurrent_scans` but the Settings attribute is `general_max_slow_processes`. Wrong attribute always triggered the fallback.
**Fix**: Change to `getattr(self.settings, 'general_max_slow_processes', 3)`.
**Commit**: `4b69879`

### T8 — xsltproc HTML export floods log with ERROR
**Symptom**: Every nmap stage completion logged two ERROR lines: "nmap output export to html attempted, but failed" and "Could not convert nmap XML to HTML. Try: apt-get install xsltproc".
**Root cause**: `DefaultNmapExporter.exportOutputToHtml()` tries to run xsltproc to generate HTML from nmap XML. xsltproc is not installed. Flask never uses the HTML output.
**Fix**: Downgrade from `logger.error()` to `logger.debug()` with explanation. Install xsltproc with `apt-get install xsltproc` if HTML files are desired.
**Commit**: `7e81e97`

### T9 — Hydra SSH fails against Metasploitable (libssh2 MAC negotiation)
**Symptom**: H1.1 (Hydra SSH test) fails with `kex error: no match for method mac algo client->server`.
**Root cause**: Hydra's libssh2 only offers modern MACs (hmac-sha2-256-etm etc.). Metasploitable's OpenSSH 4.7 only accepts legacy MACs (hmac-md5, hmac-sha1). No Hydra flag can configure this — it's compiled into libssh2.
**Fix**: H1.1 and H1.2 detect the `kex error` string and skip gracefully. H3 (FTP) and H2 (MySQL) prove the Hydra pipeline works. Note: `-oHostKeyAlgorithms=+ssh-rsa` flags are OpenSSH CLIENT flags — Hydra does not accept them.
**Prevention**: FTP and MySQL are reliable targets for Hydra testing against Metasploitable. SSH requires a modern server.

### T10 — Log tab empty without stdout redirect
**Symptom**: Log tab shows "0 lines" unless server was started with `> /tmp/legion-web.log 2>&1`.
**Root cause**: `/api/logs` route hardcoded to read `/tmp/legion-web.log`. The actual logger writes to `~/.local/share/legion/legion.log`, not that path.
**Fix**: `_InMemoryLogHandler` (deque, maxlen=10000) added to `app/logging/legionLog.py`, attached to `legion` logger. `/api/logs` reads in-memory buffer first, falls back to file.
**Commit**: `6eaf7e3` (buffer), `eed2345` (handler)

### T11 — Snapshot polling floods log with INFO noise
**Symptom**: Log tab fills with `[Snapshot] 1ms hosts=N...` every 1.5s, pushing real events out of the 2000-line buffer.
**Fix**: Downgrade `[Snapshot]` log from INFO to DEBUG. Increase buffer from 2000 to 10000. Also downgraded `[Queue] running=N/max...` and `[Queue] Started pid=N` to DEBUG.
**Commit**: `6eaf7e3`

### T12 — Comma separator introduced semicolon injection vulnerability
**Symptom**: After adding comma splitting for multi-host, test P8.5 (`127.0.0.1; rm -rf /` must be rejected) failed with status 200.
**Root cause**: Initial split used `[\n,;]+` which treated `;` as a separator. `rm -rf /` then became a separate target that passed `validateNmapInput` (all chars are alphanumeric/dash/slash).
**Fix**: Split only on `[\n,]+`. Semicolons remain injection-protection characters rejected by `validateNmapInput`.
**Prevention**: Semicolon is a shell metacharacter. Never split on it when the split parts get passed to shell commands.

### T13 — H3.3 Hydra FTP test timing race
**Symptom**: `test_h3_hydra_ftp_password_in_wordlist` fails with `FileNotFoundError` — password wordlist file doesn't exist.
**Root cause**: `_wait_for_process()` returns when the process DB status hits `Finished`. But `handleHydraFindings()` runs AFTER the status update in `_capture_output`. The test reads the wordlist file before it's been written.
**Fix**: `time.sleep(1)` in `_run_hydra()` helper after `_wait_for_process()` returns.
**Prevention**: After any process finishes, allow 1s for post-processing (hydra extraction, XML import, etc.) before reading side-effects.

### T14 — Multiple legacy server processes
**Symptom**: Browser shows stale data, old version strings, or processes from current wc don't appear.
**Root cause**: Old `python3 legion.py` processes from previous sessions still running on port 5000.
**Fix**: `sudo pkill -f "legion.py"` before starting new server. Verify with `ps aux | grep legion.py`.
**Prevention**: `run_tests.sh` kills existing legion servers in initial prep.

### T15 — wc.start() resets fastProcessQueue mid-session
**Symptom**: In Selenium tests, `_ensure_process()` calls `wc.start()` which resets `fastProcessQueue = queue.Queue()`. Processes queued before the call are lost.
**Root cause**: `wc.start()` is designed for project initialization, not mid-session use. Calling it resets the queue, process counters, and process list — but NOT `_active_processes`.
**Prevention**: Do not call `wc.start()` in test helpers unless you intend to reset queue state. Use `wc.runCommand()` directly.

### T16 — Browser refresh kills active nmap scans (v10.24)
**Symptom**: Ctrl+Shift+R while a staged scan is running → on reload, hosts missing, wrong OS, no vulners.
**Root cause**: `beforeunload` fires on EVERY page navigation including refresh. `/api/shutdown` was calling `killRunningProcesses()`. Killed stages left partial XML; `_wait_and_import` threads (not marked killed) imported garbage; `_pending_ports_stages` corrupted by stale threads.
**Fix**: Remove `killRunningProcesses()` from `/api/shutdown` (only flush output). Add scan generation counter. Add kill status + queue drain to `killRunningProcesses()`.
**Commits**: `d2def44` (v10.24), `2d61891` (v10.25)

### T17 — flock gives false positive on SQLite DB files (v10.27)
**Symptom**: `_cleanup_orphaned_temp_files()` deleted the current session's DB and running folder.
**Root cause**: Used `flock(LOCK_EX|LOCK_NB)` to test if a .legion file was in use. SQLite uses POSIX `fcntl` advisory locks (not BSD flock) — flock acquired successfully even on an active database.
**Fix**: Replaced with `/proc/PID/fd` symlink scanning — reads actual open FDs across all running processes.
**Commit**: `1f6e942` (v10.27)

### T18 — Folder cleanup used wrong name-derivation (v10.27)
**Symptom**: Same as T17 — running folder deleted because cleanup assumed DB and folder share a random suffix.
**Root cause**: DB (`legion-k_ne1jmx.legion`) and running folder (`legion-kbb34rnt-running`) are independently named by separate `mkdtemp`/`NamedTemporaryFile` calls. Name-based correlation always fails.
**Fix**: Write `.legion_session_pid` sentinel in running/output folders on `start()`; use `os.kill(pid, 0)` for liveness.
**Commit**: `1f6e942` (v10.27)

### T19 — Selenium retry loops broke tests that trigger window.confirm()
**Symptom**: After adding retry loops to TestHostDelete/TestHostChecked, those tests started failing. TestHostDelete had been passing before.
**Root cause**: If `ctx_menu_click('Delete')` triggers `window.confirm()` and then raises an exception (any reason), the retry loop catches it and tries again. But the `confirm()` dialog is still pending — Selenium cannot interact with the DOM while a JS dialog is open. The next `wait_row()` in the retry raises `UnexpectedAlertPresentException`, which is NOT in the except clause, and the test fails.
**Rule**: Only add retry loops to actions that call `postJson()` with NO `window.confirm()` (e.g. Clear). NEVER add retries to Delete, Mark as checked/unchecked, Open Terminal, or any other action that shows a JS dialog.
**Fix**: Reverted all retry loops except test_clear; commit `1c302b6`

### T20 — test_09 read host name from title bar instead of project name
**Symptom**: `test_09_title_bar_shows_project_name_after_open` always failed — title showed `10.50.60.1 (unknown)`.
**Root cause**: test_08 clicks a host row, which updates `#window-title` to the host name. test_09 then reads that DOM element and doesn't find the project filename.
**Fix**: Check `project.name` from `/api/snapshot` instead of `#window-title`. The snapshot value is authoritative and unaffected by host selection.

### T21 — Upper-panel scroll reset on every snapshot poll
**Symptom**: Scrolling up in a Running process tab to read earlier output gets hijacked back to the bottom every 1.5 seconds.
**Root cause**: `renderDynamicToolTabs()` calls `container.innerHTML = ''` on every poll, destroying all `dyn-output-*` elements and their `scrollTop`. The rebuilt element is empty (`scrollHeight ≈ clientHeight`), which `loadProcessOutput` reads as `atBottom = true`, so it auto-scrolls to the bottom.
**Fix**: `_procScrollPos = {}` map saves positions before the wipe; `loadProcessOutput` checks `_hasContent` to distinguish fresh elements from elements with real content, then restores the saved scroll position.
**Commit**: `eb00195` (v10.30)

---

## Selenium Test Infrastructure

### Port Assignments
| Port | Suite |
|------|-------|
| 5099 | test_selenium_ui.py |
| 5098 | test_selenium_project.py |
| 5097 | test_selenium_multihost.py |
| 5096 | test_selenium_gaps.py |
| 5094 | test_selenium_terminal.py |
| 5091 | test_goal1_upper_selection.py |
| 5090 | test_goal5_notes_formatting.py |
| 5089 | test_goal6_terminal_ctrlb.py |
| 5088 | test_goal4_match_highlight_ctrlb.py |
| 5087 | test_goal3_ansi_ctrlb.py |
| 5086 | test_goal2_lower_selection.py |
| 5085 | test_goal_selection_confinement.py / test_user_stories.py (live server) |
| 5084 | test_shutdown_subprocess.py (heartbeat watchdog) |
| 5083 | test_shutdown_subprocess.py (kill descendants) |

### User Story Tests (tests/test_user_stories.py)
Run against a **real** `legion.py --web --port 5085` server (not a test-app fixture).
Seed: `curl -X POST http://127.0.0.1:5085/api/nmap/import-xml -d '{"path":"/tmp/seed.xml"}'`

| Class | US | What is verified |
|-------|----|-----------------|
| `TestUS04_InvalidHostInput` | US-04 | Empty → JS validation visible; pipe/backtick → zero new processes (server 400); valid IP → process created |
| `TestUS34_CtrlBExactTextMatch` | US-34 | Single-line: `terminal.select(col,row,len)` selects exact marker; `xterm.getSelection()` == notes body after Ctrl+B. Multi-line: span from first to last marker; same equality check |

**Key implementation details for US-34:**
- `_select_marker_in_buffer(driver, marker)` — scans xterm buffer via JS, calls `terminal.select(col, row, len)`, returns `getSelection()`
- `_select_markers_range(driver, start, end)` — finds start/end rows, computes span length across `terminal.cols`, calls `terminal.select()`
- `_ctrlb(driver)` — JS `.focus()` on `.xterm-helper-textarea` (NOT `.click()` — click clears selection), then ActionChains Ctrl+B
- `_parse_notes_body(notes_raw, marker)` — splits on `=== Selection from`, finds last block containing marker, returns body text
- Comparison: `selection.strip() == body.strip()` — exact match of what xterm reported selected vs what landed in notes

### HTML Test Report Generator (tests/generate_test1_report.py)
Generates a self-contained HTML report with inline base64 screenshots for US-04.
```bash
sudo python3 tests/generate_test1_report.py --port 5085 --out /tmp/legion_report/us04.html
firefox /tmp/legion_report/us04.html
```
Each step has: step number, annotation text, pass/fail indicator, screenshot with orange outline on the relevant element.

### Test Audit — Real vs Hollow
| Category | Files | Verdict |
|----------|-------|---------|
| **Real** | test_behavioral.py, test_session_isolation.py, test_selenium_*.py, test_phase1-5_*.py, test_routes_webcontroller.py, test_goal*.py, test_user_stories.py | Execute live code, check DB/DOM |
| **Hollow** | tests/integration/test_SmokeTests.py, test_CoreWorkflows.py, test_UIRegressions.py, test_CriticalPaths.py, tests/features/test_Tab*.py, test_Notes*.py, test_Html*.py, test_Tool*.py | MagicMock everything; zero real assertions |
| **Qt6 only** | tests/ui/observers/, tests/ui/test_eventfilter.py, test_qt6_gaps.py, test_visualupgrades_features.py, test_v6_v7_fixes.py | Skipped in Flask mode |

### Known Gotchas
- **Firefox as root**: must `os.environ.pop('XAUTHORITY', None); os.environ.pop('DISPLAY', None)` before starting driver
- **Geckodriver path**: specify `Service('/usr/bin/geckodriver')` explicitly
- **Dynamic tabs**: only render for `L.selectedHostIp` — must select host before checking tabs
- **Stale elements**: use JS `querySelectorAll` for process table — snapshot re-renders every 1.5s
- **all_processes_done()**: uses JS, requires ≥1 Finished process (all-Crashed ≠ done)

### Test VM (192.168.85.11 — Metasploitable)
- SSH: port 22, msfadmin:msfadmin (needs `-oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa` for OpenSSH client; Hydra libssh2 cannot connect — MAC incompatibility)
- MySQL: port 3306, root with no password
- FTP: port 21, msfadmin:msfadmin (works with Hydra)
- HTTP: ports 80, 81, 443, 4443, 8080, 8081, 8082, 8180
- Has CVEs from vulners.nse after stage 2

---

## Commit Authors
- **ifly53e** (62 commits): Primary developer
- **therearesomewhocallmetimatviasat** (17 commits): Testing + features
- Both are Tim McLean (the user)
