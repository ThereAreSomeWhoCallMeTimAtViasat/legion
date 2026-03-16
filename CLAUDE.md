# Legion Project Context for Claude Code

## Project Overview
- **Repo:** https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
- **Primary Branch:** visualUpgradesCC
- **Type:** Network penetration testing framework (fork of Sparta/Hackman238 Legion)
- **Stack:** Python 3.10+, PyQt6 (being replaced by Flask), SQLAlchemy ORM, SQLite

## Current Direction
- **MOVING FROM Qt6 TO FLASK WEB UI** - Qt6 bugs are not worth fixing
- The upstream maintainer (Hackman238) has confirmed Qt sunset (see docs/qt-sunset-phased-plan.md)
- User's database refactoring and features TAKE PRECEDENCE over upstream code
- Flask migration plan is in docs/web-replatform-plan.md

## Branch History
- `master` - upstream Hackman238 code
- `visualUpgrades` - 77 commits of custom work by ifly53e/therearesomewhocallmetimatviasat
- `visualUpgradesCC` - visualUpgrades + upstream integration (Phase 1-3)
- `backup-visualUpgrades-before-merge` - safety backup

## What Was Done in Upstream Integration
- **Phase 1:** Added try/except/finally guardrails to ProcessRepository.py (10 methods)
- **Phase 2:** Added "Loading saved session..." statusbar feedback to view.py
- **Phase 3:** Brought in 66 new upstream files (app/core/, app/scheduler/, app/web/, tests/, docs/)
- **NOT modified:** controller.py, settings.py, auxiliary.py, gui.py, existing repositories

## Architecture (MVC)
- **Entry:** legion.py (GUI, headless CLI, MCP server, planned: --web)
- **Controller:** controller/controller.py (~2600 lines)
- **View:** ui/view.py (~3000+ lines)
- **Logic:** app/logic.py
- **Database:** db/SqliteDbAdapter.py (SQLAlchemy + QSemaphore)
- **Entities:** db/entities/ (host, port, service, process, processOutput, note, cve, os, l1script)
- **Repositories:** db/repositories/ (Host, Port, Process, Service, CVE, Note, Script, Credential)
- **Config:** app/settings.py + legion.conf (QSettings INI format)
- **Flask Web UI:** app/web/ (runtime.py, routes.py, jobs.py, ws.py, templates/, static/)

## Flask Migration Status
### Working in Flask (from upstream)
- Project management (create/open/save/export)
- Nmap scanning (easy/hard/legacy/staged modes)
- Process management (run/kill/retry/clear)
- All workspace views (hosts, services, tools, details)
- AI scheduler (deterministic + LLM modes)
- Dangerous action approval workflow
- Screenshots, notes, scripts, CVEs
- JSON/CSV export
- ANSI output rendering in browser

### Missing in Flask (needs porting from visualUpgrades)
- HIGH: Interactive terminal (PTY/pyte/msfconsole) - needs xterm.js + WebSocket
- HIGH: Deduplication system (append/newTab/skip choices)
- HIGH: Match detection & highlighting (positive/negative patterns)
- HIGH: Purge results workflow (10-step cleanup)
- MEDIUM: Unread data indicators (orange tab equivalent)
- MEDIUM: Ctrl+B quick note capture
- MEDIUM: Config profile system (multiple legion.conf versions)
- LOW: Layout state persistence, screenshot inline viewer

### Known Startup Issues for Flask
- legion.py may not have --web flag yet
- runtime.py imports from upstream's refactored settings.py (may conflict)
- SqliteDbAdapter.py uses QSemaphore (needs threading.Semaphore fallback for Flask)
- Missing pip packages: flask, flask-sock

## 18 Fragile Areas - DO NOT BREAK
1. Process timer: must check BOTH queue empty AND no Running processes
2. PTY termios: ECHO/ICANON/ISIG flags BEFORE Popen()
3. Signal connection: actionNoteSelection in __init__(), NOT start()
4. Viewport stylesheet: use viewport().setStyleSheet() for HTML tabs
5. Splitter defaults: '290,1243,0', '343,149', '319,1214,0'
6. DB sessions: get session, use, close (anti-pattern fixed)
7. Match substring filtering: positive inside negative must not highlight
8. Purge: 10 steps with delayed validation at 2s, 3s, 4s
9. Tab color flags: unread_tabs, suppress_reset_highlight, in_dynamic_tab_redraw interact
10. Interactive: isInteractive survives lifecycle, doesn't count against limit
11. HTML output: saved as HTML not plaintext (ansi2html conversion)
12. Output persistence: saveRunningProcessOutputs() BEFORE closing DB
13. Host selection: single host cannot be deselected
14. SSH flags: -o HostKeyAlgorithms=+ssh-rsa,ssh-dss for legacy hosts
15. OS discovery: -O flag in BOTH discovery=True AND discovery=False paths
16. Shutdown: stop QTimers → kill processes → stop QThreads → close DB → block signals
17. Dedup append: is_appending property checked in checkProcessQueue()
18. Sort selection: all models maintain selection through sort

## TROUBLESHOOTING.md
- Located at repo root on visualUpgradesCC branch
- Contains ~38 open issues and ~40 completed issues
- Most are Qt6 GUI bugs - NOT worth fixing if moving to Flask
- Some process/DB issues may still apply to Flask

## Key Files for Flask Work
| File | Lines | Purpose |
|------|-------|---------|
| app/web/runtime.py | 6559 | Flask backend - all business logic |
| app/web/routes.py | 1153 | Flask endpoint handlers |
| app/web/jobs.py | 286 | Background job queue |
| app/web/ws.py | 18 | WebSocket support |
| app/web/bootstrap.py | 20 | App factory |
| app/web/templates/index.html | 1218 | Main HTML template |
| app/web/static/js/legion.js | 4137 | Client-side JavaScript |
| app/web/static/css/legion.css | 1189 | Styling |
| db/repositories/ProcessRepository.py | ~550 | Process DB operations (guardrailed) |
| app/settings.py | ~450 | Config management (Qt-dependent) |
| db/SqliteDbAdapter.py | | DB adapter (Qt-dependent) |
