# Qt6 vs Flask — Complete Feature Audit

**Date:** 2026-03-19
**Branch:** flask-clean (v9.4-flask)
**Purpose:** Identify every Qt6 capability and its status in the Flask version.

Legend:
- ✅ Implemented and working
- ⚠️ Partial — stub exists, logic incomplete or wrong
- ❌ Missing — exists in Qt6, not in Flask
- 🔴 Bug — implemented but broken
- N/A — Qt6-only concept (UI widget, Qt signals) with no Flask equivalent needed

---

## 1. Project Management

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| `createNewProject()` | ✅ | Via `/api/project/new-temp` |
| `openExistingProject(filename)` | ✅ | Via `/api/project/open` + file browser modal |
| `saveProject(lastHostId, notes)` | ✅ | Notes saved per-host via `/api/workspace/hosts/<id>/note` |
| `saveProjectAs(filename)` | ✅ | Via `/api/project/save-as` + file browser modal |
| `closeProject()` | ✅ | Called on server shutdown |
| `loadSettings()` | ✅ | Loaded at startup from `legion.conf` |
| `applySettings(newSettings)` | ⚠️ | Settings can be saved via `/api/settings/legion-conf` but `applySettings` logic (applying to running state) not implemented |
| `saveSettings(saveBackup)` | ⚠️ | Raw text save works; backup copy not implemented |
| `exportAsJson(filename)` | ✅ | Implemented in `/api/export/json` (fixed this session) — includes hosts, ports, notes, CVEs |
| CSV export | ❌ | Stub returns "not yet implemented" |
| `copyToClipboard(data)` | N/A | Done in browser JS via `navigator.clipboard` |
| `isTempProject()` | ✅ | Used internally |
| `updateOutputFolder()` | ❌ | Qt6 tells screenshooter to update its output folder; Flask screenshooter uses current folder directly |
| `copyNmapXMLToOutputFolder(filename)` | ❌ | Qt6 copies nmap XML to the project output folder after import; Flask does not |

---

## 2. Host Management

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| `addHosts(targets, discovery, staged, speed, mode, ...)` | ✅ | Via `/api/nmap/scan` |
| Host right-click → **Mark as checked/unchecked** | ✅ | `toggleHostCheckStatus` |
| Host right-click → **Portscan → Run nmap (staged)** | ✅ | `runStagedNmap` |
| Host right-click → **Portscan → Rescan** | ✅ | `runStagedNmap` |
| Host right-click → **Portscan → nmap fast TCP** | 🔴→✅ | Fixed: now adds `-oA` so results import |
| Host right-click → **Portscan → nmap fast UDP** | 🔴→✅ | Fixed |
| Host right-click → **Portscan → nmap full TCP** | 🔴→✅ | Fixed |
| Host right-click → **Portscan → nmap full UDP** | 🔴→✅ | Fixed |
| Host right-click → **Portscan → nmap top 1000 UDP** | 🔴→✅ | Fixed |
| Host right-click → **Portscan → nmap script Vulners** | 🔴→✅ | Fixed |
| Host right-click → **Portscan → nmap-discover** | 🔴→✅ | Fixed |
| Host right-click → **Portscan → unicornscan** | ⚠️ | No `-oA` fix (unicornscan, not nmap) — output shows but no import |
| Host right-click → **Portscan → ICMP timestamp** (hping3) | ⚠️ | Runs but output only, no import (not nmap) |
| Host right-click → **Portscan → PyShodan** | ❌ | Qt6 had special python-script handling; Flask runs the echo stub only |
| Host right-click → **Portscan → macvendors** | ❌ | Same — echo stub only |
| Host right-click → **Open Terminal** | ✅ | PTY bash session via xterm.js |
| Host right-click → **Purge Results** | ✅ | Kills processes + deletes scan data, keeps host+notes |
| Host right-click → **Delete** | ✅ | Full cascade delete |
| Add host manually (via modal) | ✅ | Add Hosts modal |
| Add port manually (via modal) | ✅ | Add Port modal |
| Double-click host → copy IP | ✅ | Via JS clipboard API |

---

## 3. Port / Service Actions

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Services panel (left) right-click → port actions | 🔴→✅ | Fixed: was hardcoded port=80, now uses actual service port |
| Services panel (left) right-click → **Open in browser** | 🔴→✅ | Fixed: now opens `window.open()` |
| Services panel (left) right-click → **Take screenshot** | 🔴→✅ | Fixed: now runs eyewitness via terminal |
| Port row (right panel) right-click → **port actions** | ✅ | `handleServiceNameAction` with correct IP/port/protocol |
| Port row right-click → **[term] terminal actions** | ✅ | PTY session started for ssh, mysql, netcat, etc. |
| Port row right-click → **Send to Brute** | ✅ | Fills Brute tab fields |
| Port row right-click → **Take screenshot** | ⚠️ | In fixed_actions list but JS `take-screenshot` handler in port context goes via terminal (eyewitness) |
| Port row right-click → **Open in browser** | ✅ | Fixed: `window.open()` |
| Port row right-click → **Run custom command** | ❌ | Appears in menu, does nothing — needs a command input modal |
| Port row double-click → switch to Hosts tab | ✅ | |

---

## 4. Process Actions

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Process right-click → **Kill** | ✅ | `/api/processes/<id>/kill` |
| Process right-click → **Retry** | ✅ | Re-runs same command; Interactive retry creates new PTY |
| Process right-click → **Clear** (hide) | ✅ | Sets closed=True |
| `cancelProcess(dbId)` | ⚠️ | `storeProcessCancelStatus` called in queue; no explicit cancel route |
| Process auto-select (new Running/Interactive) | ✅ | Fixed to include Interactive |
| Duplicate tool detection (skip/append/new tab) | ❌ | Qt6 prompts user when same tool runs again for same host:port; Flask silently runs duplicate |
| Process output append mode | ❌ | Qt6 can append to existing tab output when retrying; Flask always replaces |

---

## 5. Python Scripts (PyShodan, macvendors)

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| `runPython()` — python console tab | ❌ | Qt6 had a Python console; no equivalent in Flask |
| `python-script-PyShodan` host action | ❌ | Qt6 ran `scripts/python/pyShodan.py [IP]`; Flask config has the action but `handleHostToolAction` runs it as a shell command which just echoes "PythonScript pyShodan" |
| `python-script-macvendors` host action | ❌ | Same — Flask config action echoes stub text; no real script execution |
| Python importer (`initPythonImporter`) | ❌ | Qt6 had a full Python results importer pipeline; Flask has no equivalent |

---

## 6. Screenshots

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Auto-screenshooter via scheduler | ✅ | eyewitness runs automatically for HTTP ports |
| `screenshotFinished` (store + create tab) | ✅ | Flask: `storeScreenshot` + process output serves image |
| Screenshot deduplication (`_screenshots_taken`) | ✅ | |
| Screenshot blacklist (deleted host) | ⚠️ | Qt6 checks screenshooter blacklist; Flask checks `_screenshots_taken` set but no host-deletion blacklist |
| Manual take-screenshot from port menu | 🔴→✅ | Fixed this session |
| Screenshot modal (full-size view) | ✅ | Opens on image click in dynamic tab |

---

## 7. Scheduler / Automated Attacks

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| `scheduler(parser, isNmapImport)` — auto-run tools | ✅ | Flask scheduler iterates hosts/ports from DB |
| `runToolsFor(service, hostname, ip, port, protocol)` | ✅ | Flask: `scheduler()` calls `runCommand` for each matching port action |
| Duplicate script check (skip if already ran) | ❌ | Qt6: checks `scriptRepository.getScriptsByPortId` before running; Flask: uses `checkDuplicate` on process table (different — checks process name+host+port, not script table) |
| Append mode (re-run appends to existing output) | ❌ | Qt6 only |
| New numbered tab for re-runs | ❌ | Qt6 creates "tool (80/tcp) [2]" tabs; Flask just creates another process |
| `enable-scheduler` setting respected | ✅ | |
| `enable-scheduler-on-import` respected | ✅ | |

---

## 8. Browser Opener

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| `initBrowserOpener()` | N/A | Qt6 used a Qt worker thread; Flask uses `window.open()` in JS |
| Open service URL in browser | ✅ | Fixed this session — `window.open()` |
| Track which URLs were opened | ❌ | Qt6 had a BrowserOpener queue that tracked opened URLs; Flask opens immediately with no tracking |

---

## 9. Terminal / Interactive Processes

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Interactive PTY bash session (xterm.js) | ✅ | Full implementation this session |
| `[term]` port actions → open terminal | ✅ | PTY session starts, command dispatched after 500ms |
| msfconsole → Interactive after 10s | ✅ | `threading.Timer(10, markAsInteractive)` |
| Ctrl+C, arrow keys, Tab completion | ✅ | Tested via T6 keyboard tests |
| Terminal in lower panel (process row click) | ✅ | |
| Terminal in upper panel (dynamic tab click) | ✅ | |
| Input widget (QLineEdit) at bottom of tab | ✅ | xterm.js handles input |
| Resize on window resize | ✅ | `_onTermResize` handler |

---

## 10. Settings Management

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Load settings from `legion.conf` | ✅ | |
| Save raw `legion.conf` text | ✅ | `/api/settings/legion-conf` |
| Config profiles (save/load/activate/rename/duplicate/delete) | ✅ | `/api/config/profiles/*` routes |
| `applySettings` — apply new settings to running app | ❌ | Qt6 called `applySettings(newSettings)` which updated live scheduler, screenshooter, etc. Flask saves to disk but doesn't hot-reload running components |
| Settings backup on save | ❌ | Qt6 wrote a `.bak` file; Flask does not |
| `general_default_terminal` setting | ❌ | Qt6 used this for opening external terminal windows; Flask opens PTY in-app regardless |

---

## 11. Nmap Import

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Import nmap XML via file browser | ✅ | `/api/nmap/import-xml` |
| Import via `importFinished()` after scan | ✅ | Called by `_capture_output` after nmap exits |
| Import from host actions (Portscan submenu) | 🔴→✅ | Fixed this session — now adds `-oA` |
| `copyNmapXMLToOutputFolder` | ❌ | Qt6 copies the nmap XML to the project output dir for later reference; Flask does not |
| Python importer (custom results parsers) | ❌ | Qt6 had `initPythonImporter` for community scripts; Flask has no equivalent |

---

## 12. Hydra / Brute Force

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| Brute tab UI (IP, port, service, wordlists) | ✅ | |
| Run Hydra via brute tab | ✅ | `/api/brute/run` → `runCommand` |
| `handleHydraFindings` (extract credentials) | ✅ | `_capture_output` calls `detectMatches` → hydra credential extraction |
| Auto-populate brute tab from port right-click | ✅ | "Send to Brute" |
| Credential storage in DB | ⚠️ | `handleHydraFindings` updates wordlists but credential persistence to DB not verified |

---

## 13. Data Access / DB

| Qt6 Capability | Flask Status | Notes |
|----------------|-------------|-------|
| `getHostsFromDB(filters)` | ✅ | |
| `getServiceNamesFromDB(filters)` | ✅ | |
| `getPortsAndServicesForHostFromDB` | ✅ | |
| `getHostsAndPortsForServiceFromDB` | ✅ | |
| `getHostInformation(hostIP)` | ✅ | |
| `getScriptsFromDB(hostIP)` | ✅ | |
| `getCvesFromDB(hostIP)` | ✅ | |
| `getScriptOutputFromDB(scriptDBId)` | ✅ | |
| `getNoteFromDB(hostid)` | ✅ | |
| `getHostsForTool(toolName, closed)` | ✅ | |
| `getPortStatesForHost(hostid)` | ✅ | |
| `getProcessesFromDB(filters, ...)` | ✅ | |
| `getProcessesForRestore()` | ✅ | |
| `getOperatingSystemsSummary()` | ✅ | |
| `getHostsForOperatingSystem(os_name)` | ✅ | |
| `storeProcessInteractiveStatus` | ✅ | |
| `scriptRepository.getScriptsByPortId` | ❌ | Flask never queries scripts per port (used in Qt6 for duplicate tool check and scheduler) |
| `isHostInDB(host)` | ⚠️ | Used in Qt6 addHosts; Flask equivalent via snapshot |

---

## 14. UI / View Logic (no Flask equivalent needed — pure Qt6)

These are Qt6-specific UI concerns with no direct Flask equivalent:

| Qt6 Capability | Flask Equivalent |
|----------------|-----------------|
| `initTimers()` — QTimer for UI updates | Snapshot polling every 1.5s |
| `updateInterface()` — refresh all Qt views | pollSnapshot() in JS |
| `displayAddHostsOverlay(bool)` | Hosts table shows/hides naturally |
| `createNewTabForHost(ip, title)` | `renderDynamicToolTabs` in JS |
| `findExistingTabIndex(widget, name)` | Not needed (no tab widget) |
| `promptDuplicateToolAction(name, title)` | Not implemented — needs modal |
| `closeHostToolTab(index)` | Dynamic tab × button |
| Tab reordering by match status | CSS tab-match class |
| `BrowserOpener` Qt worker thread | `window.open()` in JS |
| Qt signals (sigHasMatch, sigHydra, etc.) | Polling + DB |

---

## Summary: Critical Gaps

### 🔴 Bugs fixed this session
1. Portscan submenu nmap results not imported (no `-oA` flag)
2. Services panel right-click hardcoded port=80
3. "Open in browser" / "Take screenshot" actions unhandled

### ❌ Missing functionality (not implemented in Flask)

| Gap | Impact |
|-----|--------|
| **PyShodan / macvendors scripts** | `python-script-*` host actions echo stub text instead of running real scripts |
| **Duplicate tool detection** | Same tool can be run multiple times for same host:port; Qt6 prompted user to skip/append/new |
| **Run custom command** | Port menu item exists, does nothing — no command input modal |
| **Settings hot-reload** | Changing settings via Config modal saves to disk but doesn't update running scheduler/screenshooter |
| **Settings backup on save** | Qt6 wrote `.bak` files; Flask does not |
| **CSV export** | Stub only |
| **copyNmapXMLToOutputFolder** | XML files not archived to project output folder |
| **scriptRepository.getScriptsByPortId** | Scheduler duplicate check uses different mechanism; may miss script-level dedup |
| **unicornscan results import** | Unicornscan output captured but never imported (no XML) |
| **Python importer pipeline** | Qt6 community script results pipeline; Flask has no equivalent |
| **Screenshot host-deletion blacklist** | If host deleted mid-scan, screenshot may still arrive; Flask has partial protection |
| **Process append mode** | Retry always creates new output; Qt6 could append to existing |
| **Hydra credential DB persistence** | Credentials extracted but unclear if persisted correctly |

### ⚠️ Partial implementations (stubs or incomplete logic)

| Item | What's missing |
|------|---------------|
| `applySettings` | Save works, live application to running components doesn't |
| `cancelProcess` | No explicit API route; handled via queue skip only |
| unicornscan host action | Runs but no result import |
| hping3 / ICMP host action | Runs but no result import |
| Take screenshot (port menu) | Works via terminal but loses eyewitness dedup logic |

---

## Test Coverage of Gaps

| Gap | Automated test? |
|-----|----------------|
| Portscan submenu nmap (now fixed) | ❌ No test — should add |
| Services panel port bug (now fixed) | ❌ No test — should add |
| Python scripts | ❌ No test |
| Duplicate tool detection | ❌ No test |
| Run custom command | ❌ No test |
| Settings hot-reload | ❌ No test |
| CSV export stub | ❌ No test |
