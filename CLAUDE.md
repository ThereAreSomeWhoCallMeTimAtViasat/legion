# Legion Project Context for Claude Code

## User Preferences
- User's database refactoring and features TAKE PRECEDENCE over upstream code
- Tests for every method before building — prove one element works before doing the whole thing
- Host is always the key — never mix data from different hosts in views
- Cache-busting on static files + version indicator in UI
- Prefers comprehensive explanations and step-by-step guidance

## Project Overview
- **Repo:** https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
- **Primary Branch:** `flask-rewrite` (branched from `visualUpgradesCC`)
- **Type:** Network penetration testing framework (fork of Sparta/Hackman238 Legion)
- **Stack:** Python 3.10+, PyQt6 (being replaced by Flask), SQLAlchemy ORM, SQLite
- **Size:** ~18,000 lines across 150 Python files
- **Tests:** 122/122 passing (run: see "Running" section below)

## CRITICAL ARCHITECTURE DECISION (2026-03-17)
**DO NOT USE upstream runtime.py.** The user's logic in controller.py IS the source of truth.

The upstream Flask `runtime.py` (6559 lines) is someone else's REIMPLEMENTATION of the user's controller.py logic. It has known gaps (scheduler doesn't match, service name mismatches, missing tool triggers). Instead:

```
YOUR code (controller.py + logic.py)  →  WebController wraps it Qt-free
    QProcess → subprocess.Popen          QTableView → HTML table
    QTimer → threading.Timer             QMenu → JSON list of dicts
    self.view.xxx() → state dict         Qt signals → JS polling
    Everything else stays EXACTLY the same
```

## Current State (2026-03-17)
- **Branch:** `flask-rewrite` (last commit: 940be3e)
- **Tests:** 122/122 passing across 4 test files, zero failures
- **WebController:** `controller/web_controller.py` (990 lines)
  - ALL 43 Qt-dependent methods ported — wraps your 3956-line controller.py
  - QProcess → subprocess.Popen, QMenu → JSON, QTimer → threading, self.view → no-op
- **Routes:** 6 new routes wired: context menus + host/service actions
- **Frontend:** Rewritten from scratch (Qt6 Fusion Dark 1:1 replica)
  - `legion.css` — QPalette colors (#353535/#191919/#2a82da), monospace 10pt
  - `index.html` — Qt6 layout (gui.py replica) + upstream modals preserved
  - `legion.js` — fresh JS: host-click, tab switch, ANSI render, polling
- **Backend:** routes.py for API endpoints, WebController replaces runtime.py for logic

## Branch History
- `flask-rewrite` — **CURRENT** fresh branch for Qt6→Flask rewrite
- `visualUpgradesCC` — has Session 1 bolted-on patches (committed at d94d5af)
- `visualUpgrades` — 77 commits of custom work by ifly53e/therearesomewhocallmetimatviasat
- `master` — upstream Hackman238 code

## Test Status — 122/122 PASSING

### test_webcontroller.py (28/28) — Core WebController
- **Tier 1 (21):** Pure logic — imports, project, DB queries, settings without Qt
- **Tier 2 (4):** Context menus → JSON (host/service/port/process menus)
- **Tier 3 (3):** runCommand with subprocess, output captured in DB

### test_webcontroller_remaining.py (31/31) — All Methods
- **Group A (15):** Lifecycle — start, project CRUD, save, cleanup, import, screenshot
- **Group B (11):** Process execution — addHosts, handleHostAction (mark/delete/purge), handleServiceNameAction, handlePortAction, handleProcessAction (kill/retry/clear), runStagedNmap, killAll, checkQueue
- **Group C (5):** Match/UI — handleMatch, handleHydraFindings, markAsInteractive, saveOutputs, scheduler

### test_routes_webcontroller.py (21/21) — Route Wiring
- **R1 (7):** Query routes — health, snapshot, host detail, settings
- **R2 (3):** Action routes — new project, save note, clear processes
- **R3 (4):** Context menu routes — GET /api/menus/{host,service,port,process}
- **R4 (3):** Host action routes — POST action dispatch, tool run, service action
- **R5 (3):** Process mgmt — run→output, kill via route, snapshot shows processes
- **R6 (1):** Nmap scan route

### test_flask_integration.py (42/42) — End-to-End
- **E1 (8):** Page load — HTML structure, menubar, panels, CSS palette, JS logic
- **E2 (5):** Host workflow — snapshot hosts, detail ports, service names, mark action
- **E3 (4):** Service workflow — services listed, HTTP/SSH/MySQL menus correct
- **E4 (4):** Tool workflow — run tool, get output, kill, appears in snapshot
- **E5 (5):** Process lifecycle — Running/Finished/Killed status, retry, clear
- **E6 (5):** Context menus match Qt6 — structure, submenus, checked/unchecked
- **E7 (3):** Project lifecycle — new, details, save note
- **E8 (3):** Settings — load legion.conf, has StagedNmap, has Scheduler
- **E9 (3):** Staged nmap — method exists, settings loaded, scan route works
- **E10 (2):** Data integrity — host isolation, delete doesn't affect others

## Qt Replacement Patterns (proven by tests)
```python
# QMenu → JSON (Tier 2)
QMenu()                    → list of dicts
menu.addAction("label")    → items.append({"label": "...", "action": "..."})

# QProcess → subprocess (Tier 3)
MyQProcess(...)            → WebProcessStub(...)
qProcess.start(cmd)        → subprocess.Popen(cmd, shell=True, stdout=PIPE, stderr=STDOUT)
qProcess.readAllStdout()   → background thread reads stdout line-by-line, flushes to DB

# QTimer → threading
QTimer.singleShot(ms, fn)  → threading.Timer(ms/1000, fn).start()

# self.view.xxx() → no-op or state update
self.view.updateInterface() → no-op (browser polls /api/snapshot every 3s)
self.view.createNewTabForHost() → return None
```

## Architecture (MVC)

### Critical Files Map
| File | Lines | Purpose | Qt-free? |
|------|-------|---------|----------|
| `controller/web_controller.py` | 420 | Qt-free wrapper around controller.py | ✓ NEW |
| `controller/controller.py` | ~3956 | Process queue, scheduling, UI orchestration | 54 pure / 43 need wrapping |
| `app/logic.py` | | Business logic, project lifecycle | ✓ zero Qt |
| `app/settings.py` | ~450 | AppSettings + Settings classes | ✓ zero Qt (uses config_store.py) |
| `app/auxiliary.py` | ~490 | MyQProcess (166 lines), Filters, match detection | MyQProcess → WebProcessStub |
| `db/repositories/*` | | All DB operations | ✓ zero Qt |
| `db/SqliteDbAdapter.py` | | SQLAlchemy DB adapter | QSemaphore → threading.Semaphore needed |
| `app/ProjectManager.py` | | Project create/open/save | ✓ zero Qt |
| `legion.conf` | ~360 | All configuration (INI format) | ✓ |

### Flask Frontend Files (rewritten from scratch)
| File | Lines | Purpose |
|------|-------|---------|
| `app/web/static/css/legion.css` | ~450 | Qt6 Fusion Dark palette replica |
| `app/web/static/js/legion.js` | ~500 | Fresh JS: view logic from view.py |
| `app/web/templates/index.html` | ~1050 | Qt6 gui.py layout + upstream modals |
| `app/web/templates/base.html` | ~17 | Minimal shell |

### Upstream Flask Files (kept for API endpoints only)
| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `app/web/runtime.py` | 6559 | Upstream reimplementation | **BEING REPLACED by WebController** |
| `app/web/routes.py` | 1153 | Flask endpoint handlers | Keep API endpoints |
| `app/web/jobs.py` | 286 | Background job queue | Keep |
| `app/web/ws.py` | 18 | WebSocket support | Keep |
| `app/web/bootstrap.py` | 20 | App factory | Keep |

## Process Execution Flow (WebController — the new way)
1. User right-clicks host/port → JS sends action to Flask route
2. Flask route calls WebController.handleHostAction/handlePortAction
3. WebController.runCommand() creates WebProcessStub + subprocess.Popen
4. ProcessRepository.storeProcess() saves to DB with status='Waiting'
5. storeProcessRunningStatus() updates with PID
6. Background thread (_capture_output) reads stdout, flushes to DB periodically
7. Process finishes → storeProcessOutput() with preserve_status=False → status='Finished'
8. Browser polls /api/snapshot every 3s → sees new process → renders in table
9. User clicks process row → JS fetches /api/processes/{id}/output → renders ANSI inline

## Key Systems to Preserve in WebController

### Deduplication System
- general_tool_duplication setting: append/newTab/skip/askMe
- checkProcessQueue() must check is_appending property BEFORE clearing output
- findExistingTabIndex() logic → becomes a DB query for existing processes with same tool+host+port

### Match Detection & Highlighting
- [MatchSettings] in legion.conf: global-positive, global-negative, {tool}-positive, {tool}-negative
- Negative check first, then positive. Substring filtering for overlapping ranges.
- In WebController: handleMatch() stores match data in state dict, browser renders highlights

### Staged Nmap
- 6 stages in [StagedNmapSettings]: HTTP → SMB/DB → FTP/SSH → vulners → remaining → high ports
- Stage N completion triggers Stage N+1 via process finished callback
- runStagedNmap() chains runCommand() calls

### 18 Fragile Areas — items relevant to WebController
- **#1 Process timer:** Must check BOTH queue empty AND no Running processes
- **#6 DB sessions:** get session, use, close in try/except/finally
- **#7 Match substring filtering:** positive inside negative must not highlight
- **#8 Purge 10-step:** cancel screenshots → kill processes → delete DB records, delayed validation
- **#10 Interactive detection:** isInteractive flag survives lifecycle, 10-second msfconsole delay
- **#12 Output persistence:** saveRunningProcessOutputs() BEFORE closing DB
- **#15 OS discovery flag:** -O flag in BOTH discovery=True AND discovery=False paths

## legion.conf
- Installed at `/root/.local/share/legion/legion.conf` (Flask reads this with sudo)
- Repo copy at `legion.conf` — keep in sync
- Merged config: best staged order (HTTP→SMB/DB→FTP/SSH→vulners), best match settings
- SchedulerSettings auto-runs ~12 tools; nikto/whatweb are manual via PortActions
- Known issues: smbenum service name mismatch (microsoft-ds vs netbios-ssn), screenshooter empty command

## Running
```bash
# Start Flask
sudo python3 legion.py --web          # http://127.0.0.1:5000

# Run ALL 122 tests
sudo python3 tests/test_webcontroller.py && \
sudo python3 tests/test_webcontroller_remaining.py && \
sudo python3 tests/test_routes_webcontroller.py && \
sudo python3 tests/test_flask_integration.py

# Run individual test suites
sudo python3 tests/test_webcontroller.py           # 28 — core WebController
sudo python3 tests/test_webcontroller_remaining.py  # 31 — all methods
sudo python3 tests/test_routes_webcontroller.py     # 21 — route wiring
sudo python3 tests/test_flask_integration.py        # 42 — end-to-end
```

## Commit Authors
- **ifly53e** (62 commits): Primary developer - color system, dedup, terminal, DB refactoring, splitters, purge, match filtering, tab reordering, process context menu
- **therearesomewhocallmetimatviasat** (17 commits): Testing infrastructure, terminal, output persistence, Ctrl+B, PTY config, match filtering, OS discovery, sorting fix
- Both are Tim McLean (the user)
