# Legion Flask — Interactive Terminal Test Plan

**Status:** Planning — no implementation yet
**Depends on:** v8.4-flask baseline (756 tests passing)

---

## When the interactive terminal is used in Qt6

Three specific situations, **not** a general feature for all processes:

### 1. Port right-click `[term]` actions
From `[PortTerminalActions]` in `legion.conf`. Commands marked with `[term]`:
```
ssh=Open with ssh client (as root), [term] ssh root@[IP] -p [PORT], ssh
mysql=Open with mysql client (as root), [term] mysql -u root -h [IP] --port=[PORT] -p, mysql
netcat=Open with netcat, [term] nc -v [IP] [PORT],
psql=Open with postgres client, [term] psql -h [IP] -p [PORT] -U postgres, postgres
rdesktop=Open with rdesktop, [term] rdesktop [IP]:[PORT], ms-wbt-server
mssql=Open with mssql client, [term] impacket-mssqlclient -p [PORT] sa@[IP],
xterm=Open terminal, [term] bash,    ← plain bash shell for that host/port
... etc
```
In Qt6: these open an **external terminal window** (e.g., `xterm -e 'ssh root@...'`).
In Flask: must open a **PTY terminal in the browser** (xterm.js) with the command pre-loaded.

### 2. "Open Terminal" from host right-click
`createTerminalTabForHost(ip, tabTitle)` — opens a bash PTY session **inside Legion's own tab panel**.
In Qt6: a dedicated in-app terminal tab with pyte rendering.
In Flask: an xterm.js terminal embedded in the dynamic tool tabs area.

### 3. msfconsole / bash processes
When a tool action runs a command containing 'bash' or 'msfconsole', the process tab gets an interactive mode. In Qt6: a `QLineEdit` input widget at the bottom + optional pyte terminal switch.
In Flask: the dynamic tool tab for that process shows an xterm.js terminal instead of the plain output panel.

---

## What does NOT get an interactive terminal

- nmap (all stages)
- nikto, dirb, gobuster
- hydra (runs non-interactively)
- eyewitness
- All other scanner/tool processes

These continue using the existing stdout capture → display approach unchanged.

---

## Flask Implementation Design

### Single mechanism: PTY session + xterm.js

All three use cases above converge on the same backend mechanism:

```
Browser xterm.js  ←→  POST /api/terminal/<id>/input   ←→  PTY master_fd
                  ←→  GET  /api/terminal/<id>/output   ←→  PTY output buffer
```

Backend:
```
POST /api/terminal/start         { command, host_ip, port }
  → creates TerminalSession (pty.openpty() + subprocess.Popen)
  → returns { session_id }

POST /api/terminal/<id>/input    { data: "<raw bytes as string>" }
  → writes to PTY master_fd

GET  /api/terminal/<id>/output   ?offset=N
  → returns { data: "<bytes since offset>", alive: bool }

POST /api/terminal/<id>/resize   { rows, cols }
  → TIOCSWINSZ ioctl

DELETE /api/terminal/<id>
  → terminate process, close fd, remove from session store
```

Frontend: xterm.js embedded in a **modal** that opens when:
- User selects a `[term]` port action → command pre-loaded in the terminal
- User clicks "Open Terminal" from host right-click → plain bash
- A msfconsole/bash process tab is active → xterm.js replaces the output panel

---

## Test Plan

### Category 1 — Unit/API tests (`tests/test_terminal.py`)

#### Part A: Terminal session lifecycle

| ID | Test | Verifies |
|----|------|----------|
| T1.1 | `test_start_returns_session_id` | POST /api/terminal/start → 200, body has `session_id` |
| T1.2 | `test_start_with_command` | Start with `echo hello && sleep 1` → output contains 'hello' |
| T1.3 | `test_start_plain_bash` | Start with no command → output contains bash prompt (`$` or `#`) |
| T1.4 | `test_output_initial_has_content` | GET output at offset 0 → non-empty within 2s |
| T1.5 | `test_output_offset_no_duplication` | Read twice with correct offset → no repeated content |
| T1.6 | `test_input_echo` | Write `echo test123\n` → GET output contains 'test123' |
| T1.7 | `test_input_ctrl_c` | Write `\x03` to running `sleep 30` → session still alive, new prompt |
| T1.8 | `test_resize_accepted` | POST resize {rows:30, cols:120} → 200 |
| T1.9 | `test_delete_terminates` | DELETE session → process poll() is not None (exited) |
| T1.10 | `test_delete_then_404` | DELETE then GET output → 404 |
| T1.11 | `test_nonexistent_session_404` | GET/POST/DELETE unknown id → 404 |
| T1.12 | `test_two_sessions_independent` | Start two sessions, echo different strings → each output correct |

#### Part B: Port terminal action wiring

| ID | Test | Verifies |
|----|------|----------|
| T2.1 | `test_term_actions_in_port_menu` | `/api/menus/port?service=ssh` response includes items with `action: 'terminal-action'` |
| T2.2 | `test_term_action_starts_session` | POST to `/api/workspace/service-action` with `[term]` action index → response contains `session_id` |
| T2.3 | `test_non_term_action_no_session` | Port action without `[term]` marker → response has `process_id`, no `session_id` |

#### Part C: Regression (stdin=DEVNULL unchanged, no PTY for regular tools)

| ID | Test | Verifies |
|----|------|----------|
| T3.1 | `test_nmap_runs_correctly` | Full nmap stage 1 still completes, XML imported |
| T3.2 | `test_echo_output_unchanged` | echo process output unchanged |
| T3.3 | `test_process_status_normal` | Regular process goes Running → Finished normally |

---

### Category 2 — Selenium tests (`tests/test_selenium_terminal.py`)

Module-scoped fixtures, separate server on port 5095.

#### Part A: Terminal modal (xterm.js)

| ID | Test | Verifies |
|----|------|----------|
| S1.1 | `test_open_terminal_in_host_menu` | Right-click host → "Open Terminal" in context menu |
| S1.2 | `test_open_terminal_opens_modal` | Click "Open Terminal" → `#terminal-modal` has `is-open` class |
| S1.3 | `test_terminal_container_rendered` | xterm.js canvas element exists inside `#terminal-container` |
| S1.4 | `test_terminal_has_content_after_start` | After open, xterm.js canvas has visible content (bash prompt) |
| S1.5 | `test_terminal_close_button_closes_modal` | Click × → modal closed |
| S1.6 | `test_terminal_close_calls_delete` | After close, GET /api/terminal/<id>/output → 404 (session cleaned up) |

#### Part B: Port terminal actions open modal (live scan only)

| ID | Test | Verifies |
|----|------|----------|
| S2.1 | `test_ssh_port_term_action_opens_terminal` | Right-click SSH port → "Open with ssh client" → terminal modal opens with ssh command |
| S2.2 | `test_terminal_preloaded_command` | xterm.js shows the command being run |

*Note: S2.x tests require `LEGION_TEST_TARGET` and an SSH port to be open.*

#### Part C: msfconsole/bash process tab uses xterm.js

| ID | Test | Verifies |
|----|------|----------|
| S3.1 | `test_bash_process_tab_shows_xterm` | `wc.runCommand('bash', ...)` → dynamic tab contains xterm.js canvas, not plain `#dyn-output-*` div |
| S3.2 | `test_regular_process_tab_shows_plain` | `wc.runCommand('echo test', ...)` → dynamic tab uses plain output div (no xterm.js) |

---

### Category 3 — Manual tests

| Item | How to test | Pass criteria |
|------|-------------|---------------|
| Tab completion | Type `ls /us`, press Tab | `/usr/` auto-completes |
| Arrow key history | Run command, press ↑ | Previous command appears |
| Ctrl+C interrupt | Start `sleep 100`, press Ctrl+C | `^C` shown, new prompt appears |
| Ctrl+D logout | Empty prompt, press Ctrl+D | "bash: logout" / session closes |
| Terminal resize | Drag modal corners | xterm.js content reflows |
| SSH session | Right-click SSH port → "Open with ssh client" | SSH prompt appears in terminal |
| msfconsole | Right-click msf port action → terminal opens | msfconsole banner appears |
| Colour output | `ls --color` | ANSI colours rendered by xterm.js |
| Paste | Ctrl+V in terminal | Clipboard text pasted to process |
| Long output scroll | Run `find /` | Can scroll up through output history |

---

## Implementation Steps (test-first)

### Step 1 — Backend terminal session manager
Write `test_terminal.py` Part A tests (T1.1–T1.12) FIRST, all failing.
Implement `_TerminalSession` class + `/api/terminal/*` routes.
All T1.x tests pass before proceeding.

### Step 2 — Wire port `[term]` actions to terminal sessions
Write Part B tests (T2.1–T2.3) FIRST, all failing.
Modify `handlePortAction` and `/api/workspace/service-action` route:
  - If action has `[term]` marker → start terminal session instead of process
  - Return `session_id` in response
All T2.x tests pass before proceeding.

### Step 3 — Regression check
Run all 756 existing tests. Confirm zero regressions.

### Step 4 — xterm.js frontend (terminal modal)
Write S1.x Selenium tests FIRST, all failing.
Add to `base.html`: xterm.js CDN links.
Add to `index.html`: `#terminal-modal` HTML.
Add to `legion.js`:
  - "Open Terminal" host right-click → `openModal('terminal-modal')` + start session
  - xterm.js init, output poll, input POST, resize on modal resize, DELETE on close
All S1.x tests pass before proceeding.

### Step 5 — msfconsole/bash process tabs use xterm.js
Write S3.x tests FIRST.
Modify `renderDynamicToolTabs`: if process name contains 'bash' or 'msfconsole' → render xterm.js instead of `#dyn-output-*` div.
The session was already started in Step 2.
S3.x tests pass.

### Step 6 — Port terminal action → opens terminal modal (live scan)
Wire S2.x in live scan test.
When user clicks a `[term]` port action from the port right-click → JS starts terminal session, opens modal, xterm.js shows the command output.

### Step 7 — Full regression + version bump + commit

---

## What does NOT change

- `stdin=subprocess.DEVNULL` stays for all non-interactive tools (nmap, nikto, hydra, etc.)
- Existing dynamic tabs for regular tools are unchanged (plain stdout display)
- All 756 existing tests continue passing throughout

---

## Definition of Done

- [ ] T1.1–T1.12: 12 terminal session API tests pass
- [ ] T2.1–T2.3: 3 port action wiring tests pass
- [ ] T3.1–T3.3: 3 regression tests pass
- [ ] S1.1–S1.6: 6 terminal modal Selenium tests pass
- [ ] S3.1–S3.2: 2 msfconsole/bash tab tests pass
- [ ] All 756 existing tests still pass
- [ ] Manual checklist signed off
- [ ] Version bumped, committed
