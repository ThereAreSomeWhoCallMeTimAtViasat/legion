# Legion Project Context for Claude Code

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
- **Current Flask version:** v10.23-flask
- **Static asset cache:** `?v=32` in `base.html`
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
| `app/logging/legionLog.py` | Logger setup — _InMemoryLogHandler for log tab |
| `tests/conftest.py` | Selenium fixtures (ports 5094–5099) |
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

### LLM Host Analysis (Anthropic Claude)
- **Model**: `claude-sonnet-4-6` (1M context window)
- **API key**: Session-only. Check `ANTHROPIC_API_KEY` env var first; else `window.prompt()`; store in `L.anthropicKey`
- **UI placement**: New "AI" tab in right-panel tab bar
- **Route**: `POST /api/ai/analyze-host/<id>` — assembles all host context, calls Anthropic, returns analysis text
- **System prompt**: Senior pentester framing — vulnerabilities, recommended tools, attack vectors, misconfigurations
- **Dependencies**: `pip install anthropic`
- **No streaming**: one-shot response

#### Data included in the prompt (in order)
| Data | Source | Notes |
|------|---------|-------|
| Host (IP, hostname, OS, status) | `hostObj` | Always included |
| Open ports + services | `getPortsAndServicesByHostIP` | Core findings |
| CVEs | `getCVEsByHostIP` | Known vulnerabilities from vulners NSE |
| NSE scripts + output | `getScriptsByHostIP` | Detailed per-port script results |
| Notes | `getNoteByHostId` | Analyst observations |
| **Tool process output** | `getProcesses(hostIp=ip)` with output join | Nikto, dirbuster, hydra, custom commands |

#### Tool output prioritization
- **Matched processes first**: processes where `has_match=True` or `match_text` is non-empty are included at the top — these had positive findings per the match patterns (global-positive in legion.conf)
- **Then remaining processes**: ordered by most recent (highest id) first
- **Truncate each**: max 2000 chars per tool output — prevents context overflow; prepend with tool name and status
- **Skip empty outputs**: omit processes with no output or only the tool banner/header
- **Include tabTitle and name**: so the LLM knows what tool produced each result

### Pending Feature Backlog
| # | Feature | Difficulty | Status | Notes |
|---|---------|-----------|--------|-------|
| 1 | Port state filter on Services table | Low | ✅ Done v10.0 | |
| 2 | Comma/newline multi-host + parallel nmap processes | Low | ✅ Done v10.0 | |
| 3 | Font size control in output windows | Low | ✅ Done v10.1 | |
| 4 | Config editor find/search (F2) | Low–Med | ✅ Done v10.8 | |
| 5 | Terminal notes Ctrl+B | Med | ✅ Done v10.9 | |
| 6 | Parallel nmap stages | High | ✅ Done v10.19 | PORTS parallel; NSE last with all ports |
| 7 | LLM host analysis (AI tab) | Med | ❌ Not started | Design approved above |
| 8 | Save-on-exit prompt | Low | ✅ Done v10.3 | |
| 9 | Auto per-service NSE scripts after discovery | Med | ❌ Not started | Flask only; after #7 |
| 10 | Tool manager GUI — add/remove tools from legion.conf | Med | ❌ Not started | Form-based; no direct conf editing |
| 11 | Settings GUI — change GeneralSettings/BruteSettings/etc in a form | Med | ❌ Not started | Replaces direct legion.conf editing for settings |

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
