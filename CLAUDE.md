# Legion Project Context for Claude Code

## User Preferences
- User's database refactoring and features TAKE PRECEDENCE over upstream code
- Tests for every method before building — prove one element works before doing the whole thing
- Host is always the key — never mix data from different hosts in views
- Version number must be bumped in `index.html` with every change set, BEFORE restarting server
- Prefers comprehensive explanations and step-by-step guidance

## Project Overview
- **Repo:** https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
- **Primary Branch:** `flask-clean` (branched from `visualUpgrades` — your pure code, no upstream)
- **Type:** Network penetration testing framework (fork of Sparta/Hackman238 Legion)
- **Stack:** Python 3.10+, PyQt6 (being replaced by Flask), SQLAlchemy ORM, SQLite
- **Current Flask version:** v4.2-flask

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
# Start Flask (v4.2)
sudo python3 legion.py --web          # http://127.0.0.1:5000
# Logs: /tmp/legion-web.log

# Core test suites
sudo python3 tests/test_behavioral.py          # 15 — most critical, run always
sudo python3 tests/test_signal_chains.py       # 28 — scheduler/chain
sudo python3 tests/test_phase1_right_panel.py  # 27 — right panel APIs
```

## Branch History
- `flask-clean` — **CURRENT** — built from visualUpgrades, zero upstream
- `flask-rewrite` — previous attempt, archived
- `visualUpgradesCC` — upstream integration, DO NOT USE for Flask
- `visualUpgrades` — user's pure 77 commits, base for flask-clean
- `master` — upstream Hackman238 code

## Architecture — Critical Files

| File | Purpose |
|------|---------|
| `controller/web_controller.py` | Qt-free WebController: scheduler, _chain_next_stage, screenshooter, process queue |
| `controller/controller.py` | Original Qt6 controller — DO NOT modify |
| `app/web/routes.py` | All Flask API endpoints |
| `app/web/static/js/legion.js` | All UI interactions, rendering, polling |
| `app/web/static/css/legion.css` | Qt6 Fusion Dark palette replica |
| `app/web/templates/index.html` | Qt6 layout — version string is here |
| `db/SqliteDbAdapter.py` | SQLAlchemy adapter — WAL mode enabled |
| `app/importers/nmap_import.py` | Qt-free NmapImporter wrapper |
| `app/importers/NmapImporter.py` | Original Qt6 importer — DO NOT modify |

## Known Critical Bugs & Patterns

### SQLite / Sessions
- **WAL mode is required** — without it, frequent output writes freeze all Flask reads
  - Set in `SqliteDbAdapter.establishSqliteConnection` via `event.listens_for` → `PRAGMA journal_mode=WAL`
- **ORM objects detach after `session.close()`** — never use `getPortsByHostId()` (returns ORM) in scheduler; use `getPortsAndServicesByHostIP()` (returns plain dicts)
- `session.remove()` creates fresh session; `session.close()` just closes connection but keeps session in scoped registry
- NmapImporter uses `self.db.session()` (same scoped_session as scheduler thread) and commits but never removes

### Staged Nmap Chain
- Stage ports: stage1=HTTP, stage2=NSE|vulners (slow, 2-3min), stage3=SMB/DB, stage4=FTP/SSH/RDP, stage5=remaining, stage6=high
- `_chain_next_stage`: polls `_active_processes` until `_popen` is not None (process started), then `wait()`
- After each stage XML import: `self.scheduler(isNmapImport=False)` — this is the correct Qt6 equivalent
- Scheduler calls `session.remove()` before `getHosts` to bypass any cached session state

### Scheduler
- Uses `getPortsAndServicesByHostIP(hip, filters)` → plain dict rows → no ORM detachment
- Duplicate check: queries process DB for same name+hostIp+port before running
- Screenshooter: special case handled before portActions lookup; also guarded by `_screenshots_taken` in-memory set
- `isNmapImport=False` for live scans; `isNmapImport=True` only for file import (respects `enable-scheduler-on-import` setting)

### Process Output
- `_capture_output` flushes every 5s or 100 lines (not 2s — reduces SQLite write frequency)
- `storeProcessOutput` uses `filter_by(id=process_id)` — works by coincidence since process.id == process_output.id (1:1, both auto-increment)
- Dynamic tool output tabs auto-poll every 2s while process status is Running

### startTime Format
- Stored as HUMAN_FORMAT: `'%d %b %Y %H:%M:%S.%f'` (e.g. `17 Mar 2026 19:12:35.171589`)
- Snapshot route tries both `'%d %b %Y %H:%M:%S.%f'` and `'%Y%m%d%H%M%S%f'`

## Unresolved Issues (investigate next session)

### #28 — Hosts table doesn't populate after host discovery
Diagnostic line in log after stage 1:
```
[Chain1] XML=NNNb  raw-DB: X hosts, Y ports, Z services
```
- If `XML=0b` → nmap didn't write output (scan itself failed)
- If `XML>0b, raw-DB: 0 hosts` → NmapImporter ran but parsed no hosts (target down? all ports filtered? XML malformed?)
- If `raw-DB: 1+ hosts` → data IS in DB, issue is SQLAlchemy session isolation (WAL fix may resolve)

### #29 — Screenshooter not firing after port 80 discovered
Depends on #28. Scheduler sees 0 hosts → never reaches screenshooter check. Once #28 resolved, watch for:
```
[Scheduler] hosts visible: N
[Scheduler] 192.168.x.x: N open ports
[Scheduler] checking IP:80/tcp svc='http'
[Scheduler] Screenshot queued: IP:80
```

## Phase 2 Plan (next)
Remaining gap analysis phases:
- **Phase 2**: Host double-click, port right-click/double-click, tool tab close button + context menu (save output)
- **Phase 3**: Table column sorting (host/process), column width localStorage persistence
- **Phase 4**: State restoration (`restoreToolTabs` on project open), advanced filter checkboxes working, host lifecycle (delete clears tabs + dynamic panels)

## Qt Replacement Patterns
```python
# QMenu → JSON
QMenu()                    → list of dicts
menu.addAction("label")    → items.append({"label": "...", "action": "..."})

# QProcess → subprocess
MyQProcess(...)            → WebProcessStub(...)
qProcess.start(cmd)        → subprocess.Popen(cmd, shell=True, stdout=PIPE, stderr=STDOUT)
qProcess.readAllStdout()   → background thread reads stdout line-by-line, flushes to DB

# QTimer → threading
QTimer.singleShot(ms, fn)  → threading.Timer(ms/1000, fn).start()

# self.view.xxx() → no-op
self.view.updateInterface() → no-op (browser polls /api/snapshot every 1.5s)
self.view.createNewTabForHost() → return None (renderDynamicToolTabs in JS handles it)
```

## Key Systems

### Screenshooter
- Configured in `[SchedulerSettings]`: `screenshooter="http,https,ssl,...", tcp`
- Runs via `runCommand` (appears in process table immediately)
- Requires eyewitness at `/usr/bin/eyewitness`
- Output served via `/api/screenshots?path=` (not `<path:filename>` — Flask strips leading slash)
- Screenshot PNG found by walking `{outputfile}-dir/` for first `.png`

### Process Execution Flow
1. `runCommand()` → WebProcessStub → `fastProcessQueue.put()` → `checkProcessQueue()`
2. `checkProcessQueue()` → `subprocess.Popen` → sets `proc._start_mono = time.monotonic()` → starts `_capture_output` thread
3. `_capture_output` → reads stdout → flushes to DB every 5s/100 lines → on finish: stores elapsed, marks Finished, imports XML (if nmap non-staged), calls scheduler, calls checkProcessQueue
4. Browser polls `/api/snapshot` every 1.5s → `renderProcesses` → dynamic tabs auto-refresh

### Services Tab
- Left panel: Name + Port columns, both sortable by clicking header
- `getServiceNames` returns `DISTINCT service.name, ports.portId` already

## Commit Authors
- **ifly53e** (62 commits): Primary developer
- **therearesomewhocallmetimatviasat** (17 commits): Testing + features
- Both are Tim McLean (the user)
