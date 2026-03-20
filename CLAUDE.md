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
- **Current Flask version:** v6.4-flask
- **Tests:** 468/468 across 17 test files

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
# Start Flask (v6.4)
sudo python3 legion.py --web          # http://127.0.0.1:5000
# Logs: /tmp/legion-web.log

# Run all 17 test files (468 tests)
for f in tests/test_*.py; do sudo python3 $f 2>&1 | grep Results; done

# Key suites
sudo python3 tests/test_behavioral.py          # 15 — most critical, run always
sudo python3 tests/test_signal_chains.py       # 28 — scheduler/chain
sudo python3 tests/test_phase1_right_panel.py  # 27 — right panel APIs
sudo python3 tests/test_ui_fixes.py            # 42 — all session fixes regression
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

## Unresolved Issues (STILL OPEN — DO NOT MARK RESOLVED)

### #30 — nmap stage 2 freezes everything while running
**Symptom**: While nmap stage 2 (NSE|vulners) actively runs (~2-3 min), the entire UI
appears frozen — UI doesn't update, tabs don't refresh, nothing progresses. Everything
resumes when stage 2 finishes. User confirmed STILL HAPPENING after all fixes below.

**Attempted fixes — all insufficient**:
- v6.1: Removed dynActive guard from 6s periodic refresh
- v6.2: Eliminated SQLite writes during capture (temp file approach)
- v6.4: Fixed auto-poll Waiting→Running (separate issue, not the freeze)

**True root cause NOT YET IDENTIFIED.** See full troubleshooting log in conversation.
Do not close this issue until user confirms the freeze no longer occurs.

## Completed Phases
- **Phase 2**: Close tab [X], host double-click, port right-click/double-click, save output
- **Phase 3**: All tables sortable, column width drag+localStorage
- **Phase 4**: Advanced filters working, host checked indicator, tab highlights, delete host
- **Phase 5**: Log level filter, brute tab full (hydra via runCommand, send-to-brute)

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

## Pending Features — Approved Design Decisions

### Percent Column (nmap real-time progress)
- **Goal**: Populate the percent + ETC columns in the process table for nmap processes
- **How**: Add `--stats-every 5s` to all nmap commands; parse `About X.X% done; ETC: HH:MM` from `_capture_output` per line; call `storeProcessPercent(dbId, "X% ETC:HH:MM")`
- **Non-nmap tools**: percent stays blank — acceptable
- **Snapshot**: already returns `p.percent`; JS line 688 already renders it — no UI changes needed beyond populating the field
- **nmap commands to update**: `runStagedNmap`, `addHosts` nmap path, `handleHostToolAction` nmap actions

### LLM Host Analysis (Anthropic Claude)
- **Model**: `claude-sonnet-4-6` (1M context window)
- **API key**: Session-only (never persisted to disk). Check `ANTHROPIC_API_KEY` env var first; if absent, `window.prompt()` the user on first use, store in `L.anthropicKey` JS variable for the session
- **UI placement**: New "AI" tab in the right-panel tab bar (alongside Info, Services, Scripts, CVEs, Notes)
- **Route**: `POST /api/ai/analyze-host/<id>` — queries all host data (ports, CVEs, scripts, OS, notes via existing repos), builds prompt, calls Anthropic API, returns response text
- **System prompt**:
  ```
  You are a senior penetration tester analyzing network scan data from Legion.
  Given the following host data from an authorized security assessment, provide:
  1. Key vulnerabilities to investigate based on discovered services and CVEs
  2. Specific tools to run next (with exact commands where helpful)
  3. Attack vectors most likely to yield access
  4. Any misconfigurations evident from service versions
  Be specific and actionable. Reference exact port numbers and service versions.
  ```
- **Dependencies**: `anthropic` Python package (`pip install anthropic`)
- **Error handling**: If API call fails (no key, network error, rate limit), show error in the AI tab
- **No streaming**: one-shot response (1-2s wait acceptable at Sonnet pricing)

### Pending Feature Backlog
| # | Feature | Difficulty | Status | Notes |
|---|---------|-----------|--------|-------|
| 1 | Port state filter on Services table | Low | ✅ Done v10.0 | Hide closed/filtered by default; quick toggle |
| 2 | Comma/newline multi-host + parallel nmap processes | Low | ✅ Done v10.0 | Split input, one runCommand per host |
| 3 | Font size control in output windows | Low | ✅ Done v10.1 | +/− buttons, localStorage, CSS container inheritance |
| 4 | Config editor find/search (F2) | Low–Med | ❌ Not started | Find bar, prev/next, match count |
| 5 | Terminal notes Ctrl+B | Med | ❌ Not started | `xterm.getSelection()` → append to host notes via POST |
| 6 | Parallel nmap stages | High | ⏸ Deferred | Wait for Issue #30 (stage 2 freeze) to be resolved first |
| 7 | LLM host analysis (AI tab) | Med | ❌ Not started | Anthropic Claude sonnet-4-6, session-key, new AI right-panel tab — design approved, see above |
| 8 | Save-on-exit prompt | Low | ✅ Done v10.3 | 3-button modal (Save/Don't Save/Cancel) + beforeunload warning |

### legion.conf Settings — Not Yet Wired in Flask

#### High priority (functional impact)
| Setting | Current state | Fix needed |
|---------|--------------|------------|
| `nmap-path` (`/usr/bin/nmap`) | `runStagedNmap` and `addHosts` hardcode `nmap` | Use `self.settings.tools_path_nmap` in all nmap commands |
| `hydra-path` (`/usr/bin/hydra`) | `brute_run` route hardcodes `hydra` | Use `self.settings.tools_path_hydra` |
| `pyshodan-api-key` | Script has API key hardcoded; setting ignored | Pass as env var `SHODAN_API_KEY` when invoking `pyShodan.py` |
| `default-username` / `default-password` | Brute tab starts empty | Pre-fill brute tab on page load from settings |
| `username-wordlist-path` / `password-wordlist-path` | Brute tab starts empty | Pre-fill brute tab userlist/passlist fields |
| `no-username-services` (cisco,snmp,vnc…) | Username field always shown | Hide/disable username field when selected service is in this list |
| `no-password-services` (oracle-sid,rsh…) | Password field always shown | Hide/disable password field when selected service is in this list |
| `store-cleartext-passwords-on-exit` | Wordlist files never deleted | Check flag in `closeProject()` — delete wordlist files if False |

#### Low priority (cosmetic / edge case)
| Setting | Current state | Fix needed |
|---------|--------------|------------|
| `screenshooter-timeout` (15000ms) | eyewitness `--delay 5` hardcoded | Use `general_screenshooter_timeout / 1000` as delay |
| `tool-output-black-background` | Output area uses `var(--base)` always | If True, force `#000` background on `.tool-output-area` |
| `default-terminal` | Flask always uses PTY in-app | N/A by design — Flask PTY replaces external terminal |
