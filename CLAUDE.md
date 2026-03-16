# Legion Project Context for Claude Code

## User Preferences
- User is new to Claude Code - prefers comprehensive explanations and step-by-step guidance
- User's database refactoring and features TAKE PRECEDENCE over upstream code
- Use Sonnet for Session 1 (diagnostic), Opus for Sessions 2-5 (feature porting)

## Project Overview
- **Repo:** https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
- **Primary Branch:** visualUpgradesCC
- **Type:** Network penetration testing framework (fork of Sparta/Hackman238 Legion)
- **Stack:** Python 3.10+, PyQt6 (being replaced by Flask), SQLAlchemy ORM, SQLite
- **Size:** ~18,000 lines across 150 Python files

## Current Direction
- **MOVING FROM Qt6 TO FLASK WEB UI** - Qt6 bugs are not worth fixing
- The upstream maintainer (Hackman238) has confirmed Qt sunset (see docs/qt-sunset-phased-plan.md)
- Flask migration plan is in docs/web-replatform-plan.md
- Qt6 TROUBLESHOOTING.md issues are NOT being fixed - effort goes to Flask instead

## Branch History
- `master` - upstream Hackman238 code
- `visualUpgrades` - 77 commits of custom work by ifly53e/therearesomewhocallmetimatviasat (Tim McLean)
- `visualUpgradesCC` - visualUpgrades + upstream integration (Phase 1-3) ← CURRENT BRANCH
- `backup-visualUpgrades-before-merge` - safety backup before upstream integration

## What Was Done in Upstream Integration (Already Completed)
- **Phase 1:** Added try/except/finally guardrails to ProcessRepository.py (10 methods)
- **Phase 2:** Added "Loading saved session..." statusbar feedback to view.py
- **Phase 3:** Brought in 66 new upstream files (app/core/, app/scheduler/, app/web/, tests/, docs/)
- **NOT modified:** controller.py, settings.py, auxiliary.py, gui.py, existing repositories
- Upstream remote added: `upstream` -> https://github.com/Hackman238/legion.git

## Architecture (MVC)

### Critical Files Map
| File | Lines | Purpose |
|------|-------|---------|
| `legion.py` | ~330 | Entry point, mode selection (GUI/headless/MCP, planned: --web) |
| `controller/controller.py` | ~2600 | Process queue, scheduling, UI orchestration |
| `ui/view.py` | ~3000+ | GUI management, tab system, highlighting |
| `ui/gui.py` | ~400 | Qt Designer generated layout (setupUi) |
| `ui/models/processmodels.py` | ~300 | Process table model, elapsed time formatting |
| `ui/models/hostmodels.py` | | Hosts table model |
| `ui/models/servicemodels.py` | | Service table model + ToolHostsTableModel |
| `ui/ViewState.py` | | UI state persistence (hostTabs dict) |
| `app/logic.py` | | Business logic, project lifecycle |
| `app/auxiliary.py` | ~400 | MyQProcess, BrowserOpener, match detection |
| `app/settings.py` | ~450 | AppSettings + Settings classes (Qt-dependent) |
| `app/Screenshooter.py` | | QThread for EyeWitness screenshots |
| `app/ProjectManager.py` | | Project create/open/save lifecycle |
| `db/SqliteDbAdapter.py` | | SQLAlchemy DB with QSemaphore writes |
| `db/entities/process.py` | | Process ORM entity |
| `db/repositories/ProcessRepository.py` | ~550 | Process DB queries (guardrailed) |
| `legion.conf` | ~360 | All configuration (INI format) |

### Flask Web UI Files
| File | Lines | Purpose |
|------|-------|---------|
| `app/web/runtime.py` | 6559 | Flask backend - all business logic (193 methods) |
| `app/web/routes.py` | 1153 | Flask endpoint handlers (~50 endpoints) |
| `app/web/jobs.py` | 286 | Background job queue (WebJobManager) |
| `app/web/ws.py` | 18 | WebSocket snapshot streaming |
| `app/web/bootstrap.py` | 20 | App factory (create_default_logic) |
| `app/web/templates/index.html` | 1218 | Main HTML template (10+ modals) |
| `app/web/static/js/legion.js` | 4137 | Client-side JS (state, rendering, ANSI) |
| `app/web/static/css/legion.css` | 1189 | Dark purple theme styling |

## Process Execution Flow (Qt - for reference when porting)
1. User action -> Controller builds command with [IP]/[PORT]/[OUTPUT] placeholders
2. MyQProcess created -> added to fastProcessQueue
3. processTableUiUpdateTimer (500ms) triggers checkProcessQueue()
4. Dequeued when concurrency limits allow (max_fast_processes=5, max_concurrent_scans=3)
5. QProcess.start() called, PID stored in DB
6. readyReadStandardOutput -> display + match detection
7. finished signal -> handleProcStop() -> elapsed stored in DB

## Process Execution Flow (Flask)
1. POST /api/workspace/tools/run or scheduler triggers runtime._run_manual_tool()
2. subprocess.Popen spawns process, tracked in runtime._active_processes dict
3. Output captured to database via processRepository
4. Progress tracking for nmap via regex extraction of % and ETA
5. Polling via /api/processes/<id>/output with offset/chunking
6. Kill via SIGTERM -> SIGKILL fallback

## Key Systems in visualUpgrades (Custom Work to Preserve)

### Deduplication System
- Tab-level dedup via findExistingTabIndex() in controller.py:3746-3789
- Controlled by general_tool_duplication setting: append/newTab/skip/askMe
- getHighestRunNumber(): finds highest run number for base tab title
- formatTabTitleWithRunNumber(): formats as tool->N (port/protocol)
- promptDuplicateToolAction(): user dialog for dedup decisions
- Screenshot dedup: deterministic filename check ({ip}-{port}-screenshot.png)

### Match Detection & Highlighting
- [MatchSettings] in legion.conf: global-positive, global-negative, {tool}-positive, {tool}-negative
- MyQProcess.handleMatches() in auxiliary.py:285-331: negative check first, then positive
- Substring filtering: if "open" is positive but "is already open" is negative, "open" must NOT highlight
- MatchHighlighter class in gui.py: QSyntaxHighlighter for colored output
- sigHasMatch signal -> controller.handleMatch() -> tab reorder + color update

### Interactive Terminal
- createTerminalTabForHost() in view.py:4871+: SSH terminal via PTY
- _startInteractiveTerminal() in view.py:5681+: pyte-based terminal emulation
- TerminalEventFilter: captures keyboard input, sends as raw bytes via os.write()
- PTY init: termios.tcsetattr() with ECHO, ICANON, ISIG BEFORE Popen()
- SSH flags: -o HostKeyAlgorithms=+ssh-rsa,ssh-dss for legacy hosts
- Interactive processes DON'T count against running limit
- 10-second delay before marking msfconsole as interactive (tuned timing)

### Tab Color / Notification System
- unread_tabs dict: tracks orange state for Services/Scripts/Information/CVEs/Notes
- highlightTab(name): sets orange color on tab bar
- resetTabHighlight(index): clears on user click
- preserveFixedTabColors(): reapplies after tab switches
- Flags interact: suppress_reset_highlight, in_dynamic_tab_redraw
- Match tabs: red font for positive matches in tool output

### Purge Results (10-step cleanup)
- Order: cancel screenshots -> kill processes -> close tabs -> delete DB records
- Delayed validation checks at 2s, 3s, 4s
- Preserves: host record and user notes (host ready for rescan)
- Skipping steps = orphaned records

### HTML Output Storage
- Data saved as HTML (not plaintext) to preserve ANSI colors
- Uses ansi2html library for conversion
- saveRunningProcessOutputs() called BEFORE closing DB connections
- preserve_status=True prevents premature "Finished" marking

### Config Profile System
- Multiple legion.conf versions (profile creation/switching)
- Profile management UI in configDialog.py
- Config syntax validation before saving

### Database Refactoring (CRITICAL - Must Preserve)
- Fixed "Universal Session-Per-Method Anti-Pattern" (commit f4ef3da)
- All repository methods: get session, use, close in try/except/finally
- updateProcessState(): atomic multi-field updates (commit by visualUpgrades)
- deleteProcess(), deleteProcessesByHostIp(): cascade delete with rollback
- storeProcessInteractiveStatus(): interactive state management
- hideProcesses(): selective process hiding
- ProcessRepository has OperationalError guardrails on all methods (Phase 1 work)

### Ctrl+B Note Capture
- Select text in any output -> Ctrl+B -> copies to host notes as HTML
- Signal connected in __init__(), NOT start() (double-fire bug)
- Uses viewport().setStyleSheet() for orange flash (HTML compatibility)

## Flask Web UI - What's Already Working
- Project management (create/open/save/export as ZIP)
- Nmap scanning (easy/hard/legacy/staged modes)
- Process management (run/kill/retry/clear with output streaming)
- All workspace views (hosts, services, tools, host details)
- AI scheduler (deterministic + LLM modes with feedback loops)
- Dangerous action approval workflow (classify, queue, approve/reject)
- Decision audit trail
- Screenshots, notes, scripts, CVEs (manual entry + display)
- AI reports (per-host and project-wide, Markdown export, webhook delivery)
- JSON/CSV export
- ANSI output rendering in browser (256-color)
- Job queue system with cancellation
- Settings editor (legion.conf read/write)
- Dark purple responsive UI with 10+ modals

## Flask Web UI - What's MISSING (Needs Porting)

### HIGH Priority
1. **Interactive terminal** - No PTY/terminal support in browser. Needs xterm.js + WebSocket PTY proxy
2. **Deduplication system** - Tools run without checking for duplicates. Needs dedup check in runtime + confirmation modal
3. **Match detection & highlighting** - Match settings exist in config but no runtime pattern matching or UI highlighting
4. **Purge results workflow** - Host delete exists but no purge-and-rescan. Needs purge endpoint with 10-step cleanup

### MEDIUM Priority
5. **Unread data indicators** - No equivalent to orange tab system. Needs badge counts via JS polling state
6. **Ctrl+B quick note capture** - Only manual note editing. Needs JS selection + keyboard handler
7. **Config profile system** - Single legion.conf only. Needs profile management endpoints

### LOW Priority
8. **Layout state persistence** - No localStorage for panel sizes
9. **Screenshot inline viewer** - Files served as downloads, no inline display
10. **Process confirmation dialogs** - Kill/retry without confirmation

## Known Flask Startup Issues (Session 1 Problems)
- legion.py may not have `--web` flag yet - needs argparse addition
- runtime.py imports from upstream's refactored settings.py - may conflict with our Qt-dependent version
- SqliteDbAdapter.py uses QSemaphore from PyQt6 - needs threading.Semaphore fallback for non-Qt mode
- Missing pip packages: flask, flask-sock
- app/core/config_store.py exists (from Phase 3) but settings.py may not use it yet

## Flask Migration Session Plan

### Session 1: Get Flask Running (Do First)
**Goal:** `python3 legion.py --web` starts and shows UI in browser

Steps:
1. Install deps: `pip install flask flask-sock`
2. Try `python3 legion.py --web` - expect import failures
3. Fix likely issues:
   - Add `--web` flag to legion.py argparse if missing
   - runtime.py may import from upstream's refactored settings.py - fix compatibility
   - SqliteDbAdapter.py uses QSemaphore - add `threading.Semaphore` fallback for non-Qt mode
4. Verify: page loads at http://127.0.0.1:5000 with dark purple theme
5. Test: run a scan, verify processes/hosts/services populate
6. Test: open an existing .legion file, verify data loads
7. Document what works and what doesn't for Session 2

### Session 2: Match Detection
**Goal:** Tool output highlights matches based on legion.conf MatchSettings

Steps:
1. Add pattern matching to runtime.py process output handling
   - Port logic from auxiliary.py handleMatches() and getMatches()
   - Implement negative-first checking, then positive
   - Implement substring filtering (positive inside negative = skip)
2. Add match CSS classes to legion.js ANSI output renderer
3. Add match badge counts to workspace panels
4. Store match state in process records for persistence
5. Test: run a scan, verify positive matches highlight, negatives are excluded

### Session 3: Dedup + Purge
**Goal:** Prevent duplicate tool runs, enable host data purge

Steps:
1. Add dedup check to runtime._run_manual_tool() and scheduler
   - Query processRepository for existing runs with same tool+host+port
   - Compare against general_tool_duplication setting
2. Add confirmation modal to index.html (append/new/skip choices)
3. Add /api/processes/check-duplicate endpoint to routes.py
4. Add purge_host() method to runtime.py
   - Port 10-step cleanup: cancel screenshots -> kill processes -> delete DB records
5. Add /api/workspace/hosts/<id>/purge endpoint to routes.py
6. Test: run same tool twice, verify dedup prompt appears
7. Test: purge host, verify clean state, rescan works

### Session 4: Quick Notes + Indicators
**Goal:** Ctrl+B captures text to notes, panels show unread data badges

Steps:
1. Add JS keyboard handler for Ctrl+B in process output modal
2. Capture selected text, POST to /api/workspace/hosts/<id>/note
3. Add visual flash feedback on capture
4. Track "last seen" timestamps in JS state for unread indicators
5. Add badge counts to panel headers when new data arrives
6. Test: select text in output, Ctrl+B, verify note saved

### Session 5: Interactive Terminal
**Goal:** Run msfconsole/bash interactively in the browser

Steps:
1. Add xterm.js library to static assets
2. Add WebSocket PTY proxy endpoint to ws.py
3. Port termios/pyte logic to server-side PTY management
   - Keep ECHO/ICANON/ISIG flags
   - Keep SSH algorithm flags for legacy hosts
4. Add terminal modal to index.html
5. Handle interactive process lifecycle (don't count against limit)
6. Test: open terminal to host, run commands interactively

## 18 Fragile Areas - DO NOT BREAK

These were carefully tuned by ifly53e and therearesomewhocallmetimatviasat. Many are Qt-specific
but the underlying patterns may need to be preserved when porting to Flask.

1. **Process timer** (commit bc6682c): Must check BOTH queue empty AND no Running processes. If either removed, timer stops prematurely or runs forever. File: controller/controller.py
2. **PTY termios** (commit 4c11640): ECHO/ICANON/ISIG flags MUST run BEFORE Popen(). Must close slave_fd after spawning child. File: ui/view.py
3. **Signal connection** (commit 6614b54): actionNoteSelection in __init__(), NOT start(). Moving to start() causes double-fire. File: ui/view.py
4. **Viewport stylesheet** (commit 6614b54): Must use viewport().setStyleSheet() for HTML tabs. File: ui/view.py
5. **Splitter defaults** (commits 1fea753, f451f6a): Tuned values '290,1243,0', '343,149', '319,1214,0'. Lambda removal was intentional. File: ui/view.py, app/settings.py
6. **DB sessions** (commit f4ef3da): All repository methods must get session, use, close. Leaving open = memory leaks. Files: db/repositories/*.py
7. **Match substring filtering** (commit 6b1cd1b): If "open" is positive but "is already open" is negative, "open" must NOT highlight. Checks overlapping ranges. Files: app/auxiliary.py, ui/gui.py
8. **Purge multi-step** (commit 3875fa9): 10 steps with delayed validation at 2s, 3s, 4s. Order: cancel screenshots -> kill processes -> close tabs -> delete DB records. File: controller/controller.py
9. **Tab color state machine** (multiple commits): unread_tabs, suppress_reset_highlight, in_dynamic_tab_redraw flags interact. File: ui/view.py
10. **Interactive detection** (multiple commits): isInteractive flag survives lifecycle, doesn't count against limit, 10-second msfconsole delay. Files: controller/controller.py, app/auxiliary.py
11. **HTML output storage** (commit ee39adf): Data saved as HTML not plaintext via ansi2html. Database size tradeoff accepted. Files: controller/controller.py, ui/view.py
12. **Output persistence** (commit e46ca2c): saveRunningProcessOutputs() BEFORE closing DB. preserve_status=True prevents premature "Finished". Files: controller/controller.py, db/repositories/ProcessRepository.py
13. **Host selection invariant** (commit 606d5d0): Single host cannot be deselected. File: controller/controller.py
14. **SSH algorithm flags** (commit 6dba8a1): -o HostKeyAlgorithms=+ssh-rsa,ssh-dss essential for legacy hosts. File: ui/view.py
15. **OS discovery flag** (commit bf5ebf9): -O flag in BOTH discovery=True AND discovery=False paths. File: controller/controller.py
16. **Graceful shutdown** (visualUpgrades): stop QTimers -> kill processes -> stop QThreads -> close DB -> block signals. _cleanup_done prevents re-entry. File: legion.py
17. **Dedup append mode** (commit 4b31ef1): is_appending property checked in checkProcessQueue() BEFORE process writes output. File: controller/controller.py
18. **Sort selection** (commit b7d31dd): All table models maintain selection through sort. Track original data indices not display indices. Files: ui/models/*.py

**For Flask porting:** Items 2, 6, 7, 8, 10, 11, 12, 14, 15 have direct relevance. The others are Qt-specific and don't need porting.

## Staged Nmap Configuration
- 6 stages defined in [StagedNmapSettings] in legion.conf
- stage1-ports="PORTS|T:80,81,443,4443,8080,8081,8082"
- stage2-ports=NSE|vulners
- stage3-ports="PORTS|T:25,135,137,139,445,1433,3306,5432,U:137,161,162,1434"
- stage4-ports through stage6-ports cover remaining ports
- Stage N completion triggers Stage N+1
- Stage types: PORTS|port_spec or NSE|script_name

## Match Settings Format
```ini
[MatchSettings]
global-negative="Enumerating vulnerable,valid password not found,0 valid password found,is already open"
global-positive="valid pair found,valid password found,open,exists,Netbios,supported,vulnerable,Command shell session 1 opened"
nikto-negative=asdf
nikto-positive="Server leaks inodes via ETags,X-Frame-Options"
```
Format: tool-specific `{tool}-positive` and `{tool}-negative`, plus `global-positive` and `global-negative`. Comma-separated values.

## TROUBLESHOOTING.md
- Located at repo root on visualUpgradesCC branch
- Contains ~38 open issues and ~40 completed issues
- Most are Qt6 GUI bugs - NOT being fixed (moving to Flask instead)
- Process/DB issues may still apply to Flask (timer, dedup, match detection)
- The completed items document features that WERE built and need Flask equivalents

## Commit Authors
- **ifly53e** (62 commits): Primary developer - color system, dedup, terminal, DB refactoring, splitters, purge, match filtering, tab reordering, process context menu
- **therearesomewhocallmetimatviasat** (17 commits): Testing infrastructure, terminal, output persistence, Ctrl+B, PTY config, match filtering, OS discovery, sorting fix
- Both are Tim McLean (the user)
