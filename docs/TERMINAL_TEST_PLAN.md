# Legion Flask — Interactive Terminal Test Plan

**Status:** Implemented and tested
**Version:** v9.0-flask
**Total new tests:** 48 (32 unit/API + 16 Selenium)

---

## Feature Overview

The interactive terminal provides a full PTY bash session in the browser using xterm.js.
It is used for commands requiring interactive input: msfconsole exploits, SSH sessions,
mysql/psql/netcat connections, and plain bash terminals.

**When it fires:** commands containing 'bash' or 'msfconsole' in the name (PortActions),
OR actions with `[term]` marker (PortTerminalActions), OR "Open Terminal" host right-click.

**Where it appears:**
- **Lower output panel** (`#process-output-inline`): clicking an Interactive process row
  switches from plain text to xterm.js terminal
- **Upper dynamic tabs** (right panel): clicking an Interactive process's dynamic tab
  mounts xterm.js in that tab's output area
- Both panels are **independent** — can show two different terminals simultaneously

---

## Automated Tests

### Unit/API tests — `tests/test_terminal.py` (32 tests)

#### T1: Session lifecycle (12 tests)
| Test | Verifies |
|------|---------|
| T1.1 | POST /api/terminal/start → 200, returns session_id and process_id |
| T1.2 | Snapshot includes Interactive process after start |
| T1.3 | Snapshot process has session_id matching returned value |
| T1.4 | GET output within 2s contains bash prompt |
| T1.5 | Output offset prevents duplicate data |
| T1.6 | Command dispatched to bash after 500ms delay |
| T1.7 | Input posted via /input appears in output |
| T1.8 | Ctrl+C (\\x03) does not crash session |
| T1.9 | POST resize returns 200 |
| T1.10 | DELETE terminates bash process |
| T1.11 | All requests to nonexistent id return 404 |
| T1.12 | Two sessions buffer independently |

#### T2: Interactive detection in runCommand (7 tests)
| Test | Verifies |
|------|---------|
| T2.1 | Command with 'bash' → session_id returned |
| T2.2 | Command with 'msfconsole' → session_id returned |
| T2.3 | Plain echo → no session_id |
| T2.4 | Interactive processes excluded from queue count |
| T2.5 | Interactive process has correct status and session_id in snapshot |
| T2.6 | Killing interactive process cleans up terminal session |
| T2.7 | Retrying interactive process creates new interactive session |

#### T3: Regression (2 tests)
| Test | Verifies |
|------|---------|
| T3.1 | echo process: plain output, Finished, no session_id |
| T3.2 | Regular processes in snapshot have session_id=null |

#### T4: Port menu terminal actions (7 tests)
| Test | Verifies |
|------|---------|
| T4.1 | /api/menus/port?service=ssh has terminal_actions |
| T4.2 | terminal_actions have label, action='terminal-action', command fields |
| T4.3 | ssh service has an ssh terminal action |
| T4.4 | ftp service has terminal_actions |
| T4.5 | Wildcard service returns all terminal_actions |
| T4.6 | /api/terminal/start with ssh command creates PTY session |
| T4.7 | Command is dispatched to bash stdin after 500ms |

#### T5: Snapshot session_id integrity (4 tests)
| Test | Verifies |
|------|---------|
| T5.1 | All Interactive processes have non-null session_id in snapshot |
| T5.2 | Finished processes have session_id=null |
| T5.3 | session_id is a valid UUID |
| T5.4 | DELETE removes terminal session from snapshot (process marked Killed) |

---

### Selenium tests — `tests/test_selenium_terminal.py` (16 tests)

#### S1: Lower output panel switching (7 tests)
| Test | Verifies |
|------|---------|
| S1.1 | #plain-output div exists in DOM |
| S1.2 | #terminal-output div exists in DOM |
| S1.3 | Regular process row click → #plain-output visible, #terminal-output hidden |
| S1.4 | Interactive process row click → #terminal-output visible, #plain-output hidden |
| S1.5 | xterm.js mounts content in #terminal-output when terminal shown |
| S1.6 | Clicking regular process after terminal → #plain-output returns |
| S1.7 | Plain output shows expected text content |

#### S2: Interactive detection from runCommand (2 tests)
| Test | Verifies |
|------|---------|
| S2.1 | bash process row click → #terminal-output shown |
| S2.2 | echo process row click → #plain-output shown |

#### S3: "Open Terminal" from host right-click (3 tests)
| Test | Verifies |
|------|---------|
| S3.1 | "Open Terminal" appears in host context menu |
| S3.2 | Starting terminal → process row with status Interactive appears |
| S3.3 | Clicking Terminal process row → #terminal-output visible |

#### S4: Upper dynamic tab xterm.js (4 tests)
| Test | Verifies |
|------|---------|
| S4.1 | Interactive process creates dynamic tab in right panel |
| S4.2 | Clicking Interactive dynamic tab mounts xterm.js content |
| S4.3 | Clicking regular dynamic tab does NOT mount terminal session |
| S4.4 | Upper and lower panels are independent (different processes) |

---

## Manual Tests Required

These require real network targets, keyboard interaction, or visual inspection:

| Scenario | How to test | Pass criteria |
|----------|-------------|---------------|
| **vsftpd msfconsole exploit** | Right-click FTP port → "Run metasploit on vsftpd" | msfconsole starts, `msf6 >` prompt in lower output, `run -j` output visible |
| **Type msfconsole commands** | After exploit, type `sessions` in terminal | Session list shown, cursor works correctly |
| **SSH session** | Right-click SSH port → "Open with ssh client" | SSH prompt appears, can log in and run commands |
| **mysql session** | Right-click mysql port → "Open with mysql client" | mysql `>` prompt, can run SQL |
| **netcat** | Right-click port → "Open with netcat" | nc connects, bidirectional data |
| **Open Terminal (host)** | Right-click host → "Open Terminal" | bash prompt, auto-selects in process table, fills lower output |
| **Tab completion** | Type `ls /us`, press Tab | `/usr/` auto-completes |
| **Arrow key history** | Run command, press ↑ | Previous command appears |
| **Ctrl+C** | Start `sleep 100`, press Ctrl+C | `^C` shown, new prompt |
| **Ctrl+D logout** | Empty prompt, press Ctrl+D | Session closes |
| **Colour output** | `ls --color` | ANSI colours rendered by xterm.js |
| **Paste** | Ctrl+V in terminal | Clipboard text pasted |
| **Scroll history** | Long output, scroll up | Previous output accessible |
| **msfconsole 10s delay** | Run msfconsole with `run -j` | Status stays Running for ~10s then becomes Interactive |
| **Retry interactive** | Right-click Interactive row → Retry | New interactive session created |
| **Upper tab terminal** | Create interactive process, click its tab in upper panel | xterm.js fills tab, typing works |
| **Two independent terminals** | Interactive proc in upper tab + different proc in lower | Each shows different output |
| **Terminal resize** | Resize browser window | xterm.js reflows to fit |

---

## What is NOT Automated

| Feature | Reason |
|---------|--------|
| Actual SSH/mysql/netcat connectivity | Requires real listening service |
| msfconsole exploit execution | Requires vulnerable target |
| Keyboard interaction (Tab, ↑, Ctrl+C) | Browser keyboard events in headless unreliable |
| Visual terminal rendering quality | Requires human eye |
| Colour/ANSI rendering | Canvas pixel comparison not implemented |
| msfconsole 10-second Interactive delay | Timing-sensitive, not reliably testable in automation |
| Clipboard paste | Browser security blocks headless clipboard |

---

## Implementation Notes

### Why bash hosts the PTY (not the tool directly)
bash is always the PTY process. The tool command (ssh, msfconsole, etc.) is written
to bash's stdin after 500ms — mirrors Qt6's `QTimer.singleShot(500, sendCommand)`.
This gives proper environment, signal handling, and job control. When the tool exits,
bash prompt returns.

### UTF-8 offset bug (fixed)
The server returns `next_offset` (byte count). The JS MUST use `d.next_offset` not
`d.data.length` — Kali's prompt contains multi-byte chars (┌└─㉿) where JS string
length ≠ byte length, causing offset drift and garbage characters.

### PTY initial size
Must be set to 80x24 on the slave_fd BEFORE bash starts. Without this bash thinks
terminal is 0 columns → readline breaks, cursor jumps to line start.

### xterm.js fit timing
Must delay fit+resize with `requestAnimationFrame` + `setTimeout(100ms)` after
showing `#terminal-output`. Container has zero dimensions until browser reflows.
