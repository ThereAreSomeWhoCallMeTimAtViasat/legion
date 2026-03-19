# Full Python File Audit — Flask Implementation Status

**Date:** 2026-03-19
**Version:** v9.5-flask
**Method:** Every .py file reviewed individually

---

## Summary

| Category | Count |
|----------|-------|
| Flask equivalent already implemented | 47 |
| Qt6/UI only — no Flask equivalent needed | 22 |
| Missing Flask implementation | 8 |
| Partial / Stub | 5 |

---

## File-by-File Audit

### `app/` directory

| File | Flask needed? | Status | Notes |
|------|-------------|--------|-------|
| `app/__init__.py` | No | ✅ N/A | Empty init |
| `app/actions/AbstractObservable.py` | No | ✅ N/A | Observer pattern base; Flask uses polling instead |
| `app/actions/AbstractObserver.py` | No | ✅ N/A | Same |
| `app/actions/updateProgress/*.py` | No | ✅ N/A | Qt progress signals; Flask uses snapshot polling |
| `app/ApplicationInfo.py` | No | ✅ N/A | App metadata constants only |
| `app/auxiliary.py` | Yes | ✅ Implemented | `Filters`, `getTimestamp`, `sortArrayWithArray`, etc. all used by Flask |
| `app/cli_utils.py` | Partial | ⚠️ Missing route | `import_targets_from_textfile` used in `--headless` CLI mode and MCP server but **no Flask API endpoint** for importing hosts from a text file — the Add Hosts modal only accepts typed text, not file upload |
| `app/core/__init__.py` | No | ✅ N/A | Empty |
| `app/core/ini_settings.py` | Yes | ✅ Implemented | Qt-free `IniSettingsStore` used by `AppSettings` |
| `app/httputil/__init__.py` | No | ✅ N/A | Empty |
| `app/httputil/isHttps.py` | Yes | ✅ Used | `isHttps()` called by web_controller screenshooter |
| `app/importers/__init__.py` | No | ✅ N/A | Empty |
| `app/importers/NmapImporter.py` | Yes | ✅ Used | Original Qt6 importer; wrapped by `nmap_import.py` |
| `app/importers/nmap_import.py` | Yes | ✅ Implemented | Qt-free wrapper; used everywhere |
| `app/importers/PythonImporter.py` | ❌ No equivalent | ❌ Missing | Qt6 thread that ran pyShodan/macvendors scripts and stored results in DB. Flask `python-script-*` host actions just echo stub text — **no real script execution or DB storage of results** |
| `app/logging/legionLog.py` | Yes | ✅ Used | `getAppLogger()` etc. used throughout Flask |
| `app/logic.py` | Yes | ✅ Used | Core business logic; WebController wraps it |
| `app/mcpServer.py` | No | ✅ N/A | MCP AI server; separate subprocess, not part of Flask UI |
| `app/ModelHelpers.py` | No | ✅ N/A | Qt model helpers (`itemInteractive`, etc.); pure Qt6 |
| `app/osclassification.py` | Yes | ✅ Used | `classify_os()` used by `HostRepository.getOperatingSystemsSummary()` which feeds the snapshot OS tab |
| `app/Project.py` | Yes | ✅ Used | `Project` class; used by ProjectManager |
| `app/ProjectManager.py` | Yes | ✅ Used | `createNewProject`, `saveProjectAs`, `openExistingProject` |
| `app/Screenshooter.py` | No | ✅ N/A | Qt6 QThread screenshooter; Flask uses subprocess eyewitness directly in `_run_screenshot()` |
| `app/settings.py` | Yes | ✅ Used | `AppSettings`, `Settings` classes; used everywhere |
| `app/shell/DefaultShell.py` | Yes | ✅ Used | File system operations |
| `app/shell/Shell.py` | Yes | ✅ Used | Shell base class |
| `app/timing.py` | Yes | ✅ Used | `getTimestamp()` |
| `app/tools/` | Yes | ✅ Used | NmapExporter, ToolCoordinator |
| `app/validation.py` | **❌ Not used in Flask** | ❌ Missing | `validateNmapInput()`, `validateCommandFormat()`, `validateNmapPorts()` — used in Qt6 UI to validate inputs before submission. **The Flask Add Hosts route accepts any string with no validation; a malformed target string is passed raw to nmap.** |
| `app/web/__init__.py` | N/A | ✅ N/A | Empty |
| `app/web/routes.py` | Yes | ✅ Core Flask file | All API endpoints |
| `app/web/testhelper.py` | Yes | ✅ Used | Test fixture |

---

### `controller/` directory

| File | Flask needed? | Status | Notes |
|------|-------------|--------|-------|
| `controller/__init__.py` | No | ✅ N/A | Empty |
| `controller/controller.py` | No | ✅ N/A | Qt6 source of truth — DO NOT modify |
| `controller/web_controller.py` | Yes | ✅ Core Flask file | WebController — primary Flask implementation |

---

### `db/` directory

| File | Flask needed? | Status | Notes |
|------|-------------|--------|-------|
| `db/__init__.py` | No | ✅ N/A | Empty |
| `db/database.py` | Yes | ✅ Used | SQLite `Database` class |
| `db/entities/*.py` | Yes | ✅ Used | ORM entity models (host, port, process, note, cve, script, etc.) |
| `db/filters.py` | Yes | ✅ Used | `Filters` class |
| `db/postgresDbAdapter.py` | **Not used** | ❌ Missing | PostgreSQL alternative to SQLiteDbAdapter. Exists but **Flask always uses SQLite**. No configuration option to switch to PostgreSQL. |
| `db/RepositoryContainer.py` | Yes | ✅ Used | Wires all repositories together |
| `db/RepositoryFactory.py` | Yes | ✅ Used | Creates `RepositoryContainer` |
| `db/repositories/CVERepository.py` | Yes | ✅ Used | CVE queries |
| `db/repositories/HostRepository.py` | Yes | ✅ Used | Host queries; uses `classify_os()` |
| `db/repositories/NoteRepository.py` | Yes | ✅ Used | Note queries |
| `db/repositories/PortRepository.py` | Yes | ✅ Used | Port queries |
| `db/repositories/ProcessRepository.py` | Yes | ✅ Used | Process queries; full status lifecycle |
| `db/repositories/ScriptRepository.py` | **Partial** | ⚠️ Partial | `getScriptsByHostIP` and `getScriptOutputById` called from Flask. **`getScriptsByPortId` not called** — Qt6 used it to check duplicate tool runs before re-executing; Flask never checks per-port script history |
| `db/repositories/ServiceRepository.py` | Yes | ✅ Used | Service queries |
| `db/SqliteDbAdapter.py` | Yes | ✅ Used | WAL mode + scoped sessions |
| `db/validation.py` | **Not used in Flask** | ❌ Missing | `sanitise()` SQL string escaper. **SQLAlchemy parameterized queries mean direct SQL injection protection is handled, but string concatenations in raw SQL queries should use this.** |

---

### `parsers/` directory

| File | Flask needed? | Status | Notes |
|------|-------------|--------|-------|
| `parsers/CVE.py` | Yes | ✅ Used | CVE data model for NmapImporter |
| `parsers/Host.py` | Yes | ✅ Used | Host parser |
| `parsers/OS.py` | Yes | ✅ Used | OS parser |
| `parsers/Parser.py` | Yes | ✅ Used | Main nmap XML parser |
| `parsers/Port.py` | Yes | ✅ Used | Port parser |
| `parsers/Script.py` | Yes | ✅ Used | Script parser |
| `parsers/Service.py` | Yes | ✅ Used | Service parser |
| `parsers/Session.py` | Yes | ✅ Used | Session parser |
| `parsers/examples/` | No | ✅ N/A | Documentation/example files |

---

### `ui/` directory

All Qt6 UI files — **no Flask equivalent needed** since the entire UI is replaced by HTML/JS. Logic extracted from these files has been ported case-by-case.

| File | Contains logic needing Flask port? | Status |
|------|-----------------------------------|--------|
| `ui/addHostDialog.py` | Yes — input validation with `validateNmapInput` | ❌ Flask Add Hosts accepts any string (see `app/validation.py` gap) |
| `ui/AddPortDialog.py` | Yes — port number validation | ❌ Flask Add Port accepts any string |
| `ui/ancillaryDialog.py` | No | ✅ N/A — pure Qt widgets |
| `ui/configDialog.py` | **Yes — extensive validation** | ✅ Ported this session (`_validate_legion_conf`) |
| `ui/dialogs.py` | Partial — `FiltersDialog.getFilters()`, `BruteWidget` logic | ✅ Mostly ported via JS filter state |
| `ui/eventfilter.py` | No | ✅ N/A |
| `ui/gui.py` | No | ✅ N/A |
| `ui/helpDialog.py` | No — display only | ✅ N/A |
| `ui/models/*.py` | No — Qt table models | ✅ N/A — replaced by JSON snapshot + JS rendering |
| `ui/observers/` | No | ✅ N/A |
| `ui/settingsDialog.py` | Yes — validates staged nmap port strings, command formats | ❌ Flask saves staged nmap port settings but **does not validate them** (e.g., ensure stage1-ports is a valid nmap port expression) |
| `ui/view.py` | Yes — extensive process/tab management | ✅ Mostly ported via web_controller + JS |
| `ui/ViewHeaders.py` | No | ✅ N/A |
| `ui/ViewState.py` | No | ✅ N/A |

---

### `scripts/python/` directory

| File | Flask needed? | Status | Notes |
|------|-------------|--------|-------|
| `scripts/python/dummy.py` | No | ✅ N/A | Placeholder |
| `scripts/python/macvendors.py` | Yes | ❌ Missing | Looks up MAC vendor via API. Qt6 ran this when `python-script-macvendors` host action fired. Flask config has the action entry but web_controller **does not detect `python-script-*` commands** — they run as plain shell commands which just echo "PythonScript macvendors" |
| `scripts/python/pyShodan.py` | Yes | ❌ Missing | Same — PyShodan lookup. Flask echoes stub text |
| `scripts/python/repair_legion_db.py` | No | ✅ N/A | Admin utility, not a runtime feature |
| `scripts/snmpbrute.py` | No | ✅ N/A | Standalone script, not called by controller |

---

## Gaps Summary — What Still Needs Flask Implementation

### 1. Input validation on Add Hosts (`app/validation.py` not used) — ✅ FIXED v9.6-flask

**Qt6 behaviour:** `addHostDialog.py` called `validateNmapInput(text)` before submitting. Only valid nmap target strings (IPs, CIDRs, hostnames) were accepted. Invalid characters were rejected with a UI warning.

**Fix:** `validateNmapInput` now called in `/api/nmap/scan` before passing to nmap. XSS, semicolons, and other special chars → 400. Tested in P8.1–P8.5.

---

### 2. Staged nmap port setting validation (`ui/settingsDialog.py` not ported) — ✅ FIXED v9.6-flask

**Qt6 behaviour:** `settingsDialog.py` called `validateNmapPorts(text)` on each stage1–stage6 port field before saving. Invalid nmap port expressions were rejected.

**Fix:** `validateNmapPorts` now called in `_validate_legion_conf` for `[StagedNmapSettings]` keys. Invalid chars (e.g. `<>`) → 400. Valid expressions (`80,443,8080-8090`) accepted. Tested in P8.9–P8.10.

---

### 3. Python script host actions not executed (`scripts/python/`)

**Qt6 behaviour:** When `python-script-pyShodan` or `python-script-macvendors` host action fired, `PythonImporter` ran the corresponding script and stored results in the DB.

**Flask gap:** These commands run as shell commands which echo stub text. No real script execution. `handleHostToolAction` never detects `python-script-*` in the command name.

**Fix needed:** In `handleHostToolAction`, detect `'python-script' in name` and route to script runner.

---

### 4. Per-port script duplicate check missing (`ScriptRepository.getScriptsByPortId`)

**Qt6 behaviour:** Before running a tool from the scheduler, checked `scriptRepository.getScriptsByPortId(port.id)` to see if that specific script already ran for that port. If yes, prompted user (skip/append/new).

**Flask gap:** `checkDuplicate` only checks process table (name+hostIp+port) — not the script table. No user prompt for duplicates.

---

### 5. Text file import not exposed in Flask UI (`cli_utils.import_targets_from_textfile`)

**Qt6/CLI behaviour:** `--input-file` CLI flag and `import_targets_from_textfile` import hosts from a text file (one target per line).

**Flask gap:** No API endpoint. The Add Hosts modal accepts typed text only, not file upload. Users cannot import a target list file through the web UI.

---

### 6. PostgreSQL adapter not configurable (`db/postgresDbAdapter.py`)

**Status:** File exists and has a full `Database` class. Flask always uses SQLite. No configuration option to switch to PostgreSQL.

**Impact:** Low — most users use SQLite. But the capability exists in the codebase and is inaccessible.

---

### 7. Add Port modal — no port number validation — ✅ FIXED v9.6-flask

**Qt6 behaviour:** `AddPortDialog.py` validated the port number is numeric before submitting.

**Fix:** The `add-port` action in `/api/workspace/hosts/<id>/action` now validates the port is numeric and in range 1–65535. Non-numeric or out-of-range → 400. Tested in P8.6–P8.8.

---

### 8. `db/validation.py sanitise()` not used in raw SQL

**Status:** Minor — SQLAlchemy parameterized queries handle injection for most queries. However, some raw SQL strings in repositories use string formatting rather than parameters. `sanitise()` exists but is never called.

---

## Test Plan for Gaps

### Priority 1 — Input validation — ✅ IMPLEMENTED (v9.6-flask, P8.1–P8.10 all passing)

| Test | Status | Verifies |
|------|--------|---------|
| P8.1 `add-hosts rejects XSS target` | ✅ | POST `/api/nmap/scan` with `<script>` → 400 |
| P8.2 `add-hosts accepts valid CIDR` | ✅ | `192.168.1.0/24` → 200 |
| P8.3 `add-hosts accepts hostname` | ✅ | `metasploitable.local` → 200 |
| P8.4 `add-hosts rejects empty` | ✅ | `""` → 400 |
| P8.5 `add-hosts rejects semicolon injection` | ✅ | `127.0.0.1; rm -rf /` → 400 |
| P8.6 `add-port rejects non-numeric` | ✅ | Port `"abc"` → 400 |
| P8.7 `add-port rejects out-of-range` | ✅ | Port `"99999"` → 400 |
| P8.8 `add-port rejects port 0` | ✅ | Port `"0"` → 400 |
| P8.9 `staged port rejects invalid chars` | ✅ | `stage1-ports=80,443,<evil>` → 400 |
| P8.10 `staged port accepts valid expression` | ✅ | `stage1-ports=80,443,8080-8090` → 200 |

### Priority 2 — Python scripts

| Test | Verifies |
|------|---------|
| `test_python_script_macvendors_runs` | `python-script-macvendors` host action runs real `macvendors.py` script (needs network) |
| `test_python_script_pyshodan_runs` | `python-script-pyShodan` host action runs real `pyShodan.py` (needs API key) |

### Priority 3 — File import

| Test | Verifies |
|------|---------|
| `test_import_targets_from_file_api` | POST `/api/workspace/hosts/import-file` with multipart file → hosts added |
| `test_import_targets_skips_comments` | Lines starting with `#` not imported |
| `test_import_targets_skips_duplicates` | Already-present host not re-added |

---

## Files That Are Pure Qt6 (No Flask Equivalent Needed)

These files exist only for the Qt6 GUI and have no Flask relevance:

- `ui/models/*.py` — Qt table models (replaced by JS rendering)
- `ui/observers/` — Qt observer pattern (replaced by polling)
- `ui/gui.py`, `ui/ViewState.py`, `ui/ViewHeaders.py` — Qt GUI scaffolding
- `ui/ancillaryDialog.py` — Qt progress/image widgets
- `ui/eventfilter.py` — Qt keyboard event filter
- `app/actions/` — Qt observable/observer base classes
- `app/ModelHelpers.py` — Qt model helpers
- `app/Screenshooter.py` — Qt QThread (Flask uses subprocess directly)
- `app/importers/PythonImporter.py` — Qt QThread (Flask needs non-Qt replacement)
- `parsers/examples/` — Documentation only
- `scripts/python/repair_legion_db.py` — Admin utility
- `scripts/snmpbrute.py` — Standalone script
