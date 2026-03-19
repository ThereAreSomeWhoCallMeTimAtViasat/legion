# Qt6 Remaining Gaps — Test Plan
**Version:** v9.8-flask
**Date:** 2026-03-19
**Scope:** All remaining ❌/⚠️ items from QT6_VS_FLASK_AUDIT.md that are implementable in Flask

---

## What will NOT be implemented (genuine architecture differences)

| Qt6 feature | Why not implementable in Flask |
|-------------|-------------------------------|
| Process append mode | Flask output model is append-by-default via live file; Qt6 "append" was merging two separate runs into one tab — different concept entirely |
| unicornscan XML import | unicornscan outputs its own binary/text format, not nmap XML; would require a dedicated parser not present in codebase |
| Full Python importer pipeline (initPythonImporter) | Qt6 pipeline passed DB ORM objects to script; Flask runs scripts as subprocess which cannot receive ORM objects |
| Track opened URLs (BrowserOpener queue) | Qt6 internal state with no user-visible effect; `window.open()` is functionally equivalent |
| `cancelProcess` explicit API route | Functionally equivalent — process removed from queue before start; kill works for running processes |
| `general_default_terminal` setting | Qt6 used this to open *external* terminal windows; Flask PTY in-app is superior and the intended replacement |

---

## Gaps Being Implemented

### Gap A1 — Settings backup on save (.bak file)

**Qt6 behaviour:** `saveSettings(saveBackup=True)` wrote a `.bak` copy of `legion.conf`
before overwriting it. This preserved one level of rollback.

**Flask gap:** `settings_save()` route overwrites `legion.conf` directly with no backup.

**Implementation:** Before writing, if the file exists, copy it to `<path>.bak`.

**Tests (file:** `tests/test_qt6_gaps.py` **section A1):**
| ID | Test | Pass criterion |
|----|------|----------------|
| A1.1 | Save settings creates `.bak` file | `legion.conf.bak` exists after POST `/api/settings/legion-conf` |
| A1.2 | `.bak` contains previous content | Content of `.bak` matches what was in `legion.conf` before the save |
| A1.3 | Second save rotates `.bak` | After second save, `.bak` contains content from first save (not original) |
| A1.4 | No `.bak` created if file doesn't yet exist | First save on missing file succeeds without error |

---

### Gap A2 — copyNmapXMLToOutputFolder

**Qt6 behaviour:** After nmap scan completes, Qt6 copied the `.xml` file to the project
output folder for archival. Flask captures output but leaves XML in the running folder.

**Implementation:** In `_capture_output`, after successful nmap XML import, copy the
`.xml` file to `self.logic.activeProject.properties.outputFolder`.

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A2.1 | XML file copied to outputFolder after nmap completes | XML present in outputFolder within 2s of scan finishing |
| A2.2 | Copied filename includes host IP and timestamp | Filename matches expected pattern |
| A2.3 | Original XML in runningFolder still present | Copy does not move, only copies |
| A2.4 | Non-nmap processes do not trigger XML copy | echo process — no XML copy |

---

### Gap A3 — Screenshot host-deletion blacklist

**Qt6 behaviour:** Qt6 maintained a screenshooter blacklist. When a host was deleted,
its IP was added to the blacklist so any in-flight screenshot was discarded.

**Flask gap:** Flask uses `_screenshots_taken` to prevent duplicates but has no
host-deletion guard. A screenshot could arrive after the host was deleted.

**Implementation:** Add `_deleted_hosts` set to WebController. Add IP in `handleHostAction('delete')`. Check `_deleted_hosts` in `_run_screenshot` before starting.

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A3.1 | Delete action adds IP to `_deleted_hosts` | `wc._deleted_hosts` contains deleted IP |
| A3.2 | `_run_screenshot` skips blacklisted IP | Screenshooter not started for deleted host |
| A3.3 | Non-deleted host still screenshottable | Screenshooter starts normally for other hosts |
| A3.4 | Purge does NOT add to deletion blacklist | Purge clears data but host stays active for future scans |

---

### Gap A4 — CSV export

**Qt6 behaviour:** Qt6 had a CSV export that produced a spreadsheet-compatible file
with one row per host+port combination.

**Flask gap:** `/api/export/csv` returns `{"note": "not yet implemented"}`.

**Implementation:** Generate CSV with columns: IP, Hostname, OS, Port, Protocol, State, Service, Product, Version.

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A4.1 | `/api/export/csv` returns 200 | Status code 200 |
| A4.2 | Content-Type is `text/csv` | Response header |
| A4.3 | Content-Disposition attachment with filename | Header contains `attachment; filename=legion-` |
| A4.4 | First row is a header row | `ip,hostname,os,port,...` present |
| A4.5 | Seeded host IP appears in CSV | `10.10.10.1` in CSV body |
| A4.6 | Seeded port numbers appear | `80`, `22` present in rows |
| A4.7 | One row per port per host | Two ports → two data rows |
| A4.8 | Empty project → header only, no data rows | Zero host rows, header only |

---

### Gap A5 — applySettings hot-reload

**Qt6 behaviour:** After saving settings, `applySettings()` pushed new values to all
running components: scheduler port actions, screenshooter service list, max processes.

**Flask gap:** Saving writes to disk, but `wc.settings` still has the old values in
memory until server restart.

**Implementation:** In `settings_save()` route (and profile activate), after writing the
file, call `wc.settings = AppSettings()` to reload from disk. Also notify WebController
so it re-reads `portActions`, `automatedAttacks`, `hostActions` from the new settings.

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A5.1 | After save, `wc.settings` reflects new values immediately | Change a setting, save, read it back from wc.settings |
| A5.2 | Scheduler portActions updated after settings change | wc.settings.portActions reflects new config |
| A5.3 | Profile activate also hot-reloads settings | POST activate → wc.settings updated |
| A5.4 | Hot-reload does not lose active project state | Hosts still in snapshot after reload |
| A5.5 | Bad config (rejected by validator) does not corrupt wc.settings | Invalid save → wc.settings unchanged |

---

### Gap A6 — Run custom command (port right-click)

**Qt6 behaviour:** Port right-click → "Run custom command" opened a dialog with a text
field to enter an arbitrary command. `[IP]` and `[PORT]` were substituted and the
command was run via `runCommand`.

**Flask gap:** Menu item "run-custom" exists but handler does nothing.

**Implementation:**
- API: `POST /api/processes/custom` with `{command, host_ip, port, protocol}` — validates not empty, substitutes [IP]/[PORT], runs via `wc.runCommand`
- JS: When `run-custom` action fires, show a prompt/modal for command input, then POST to API

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A6.1 | Route exists — not 404 | POST returns something other than 404 |
| A6.2 | Valid command creates process in snapshot | `echo test` → process appears |
| A6.3 | `[IP]` substituted with host IP | Process command in snapshot contains IP |
| A6.4 | `[PORT]` substituted with port number | Process command contains port |
| A6.5 | Empty command returns 400 | POST `{"command":""}` → 400 |
| A6.6 | JS has `run-custom` action handler | `legion.js` source contains `run-custom` handler code |
| A6.7 | JS prompts for command input | `legion.js` source contains prompt/modal for custom command |

---

### Gap A7 — Hydra credential persistence (verification)

**Qt6 behaviour:** Hydra finds were stored to wordlist files on disk (not a DB table).
`handleHydraFindings` added found usernames/passwords to the project's wordlist files.

**Flask gap labelled as ⚠️:** Code exists but was never verified to work.

**Verification:** `checkHydraResults` parses hydra output. `handleHydraFindings` calls
`wordList.add()`. `Wordlist.add()` writes to disk file. Need to prove the chain works.

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A7.1 | `checkHydraResults` parses valid hydra output | Returns `(True, ['user'], ['pass'])` for known hydra output format |
| A7.2 | `checkHydraResults` returns False for non-hydra output | No match on plain text |
| A7.3 | `handleHydraFindings` writes username to wordlist file | File contains username after call |
| A7.4 | `handleHydraFindings` writes password to wordlist file | File contains password after call |
| A7.5 | Wordlist file does not contain duplicates | Adding same word twice → appears once in file |
| A7.6 | Wordlist persists after project save/open | Filename in output folder, still there after save |

---

### Gap A8 — Duplicate check for user-triggered tool actions

**Qt6 behaviour:** Qt6 called `checkDuplicate` before running any tool, whether
scheduler-triggered or user-triggered. If a duplicate was found, it showed a modal
(skip/append/new tab).

**Flask gap:** `checkDuplicate` is called by the scheduler but NOT by `handleHostToolAction`
or `handleServiceNameAction` when the user manually triggers them from right-click menus.

**Implementation:**
- Add `checkDuplicate` call at the start of `handleHostToolAction` and `handleServiceNameAction`
- If result is `'skip'`, return a response indicating the duplicate was skipped
- Add `/api/check-duplicate` GET endpoint for JS pre-flight checks

**Tests:**
| ID | Test | Pass criterion |
|----|------|----------------|
| A8.1 | `/api/check-duplicate` route exists | GET returns not 404 |
| A8.2 | Returns `run` for a tool that has not run | Fresh tool → `{"result": "run"}` |
| A8.3 | Returns configured mode for existing process | After running, returns `skip`/`newTab`/`append` |
| A8.4 | `handleHostToolAction` respects duplicate check | Running same host action twice — second call skipped |
| A8.5 | `handleServiceNameAction` respects duplicate check | Running same port action twice — second skipped |
| A8.6 | `checkDuplicate` called in `handleHostToolAction` source | Source inspection confirms call |
| A8.7 | `checkDuplicate` called in `handleServiceNameAction` source | Source inspection confirms call |

---

## Test File

All tests above go in: **`tests/test_qt6_gaps.py`**

Run with: `sudo python3 tests/test_qt6_gaps.py`

---

## Gaps That Cannot Be Fully Automated

| Gap | What can be automated | What requires manual check |
|-----|----------------------|---------------------------|
| CSV export download in browser | Content verified via API (A4.1–A4.8) | Blob download to disk in browser |
| Custom command modal (JS) | Route + substitution tested (A6.1–A6.5); source inspection (A6.6–A6.7) | Visual: modal appears in browser, text field focused |
| Settings hot-reload effect on live scan | Settings object updated (A5.1–A5.5) | Visual: change screenshooter port list → next scan uses new ports |
| Hydra full integration | Chain tested (A7.1–A7.6) | Requires real hydra run against weak-password service |

---

## Regression Plan

After implementation, run in order:
```bash
sudo python3 tests/test_qt6_gaps.py           # all new gap tests
sudo python3 tests/test_behavioral.py         # core regression
sudo python3 tests/test_api_gaps.py           # save/open/config regression
sudo python3 tests/test_gap_implementations.py # previous gap regression
sudo bash run_tests.sh                        # full suite
```
