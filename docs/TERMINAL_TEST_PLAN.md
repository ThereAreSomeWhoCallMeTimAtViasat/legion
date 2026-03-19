# Legion Flask — Interactive Terminal Test Plan

**Status:** Planning — no implementation yet
**Depends on:** v8.4-flask baseline (756 tests passing)

---

## Where the terminal appears

The terminal goes **inside `#process-output-inline`** — the upper output panel
that already shows process output when you click a process row. No modal,
no popup, no separate panel.

Current behaviour:
- Click any process row → `#process-output-inline` shows plain stdout text

New behaviour:
- Click a regular process (nmap, nikto, hydra) → plain text as before
- Click a terminal process (bash, msfconsole, `[term]` action) → the same
  area shows an xterm.js terminal you can type into directly

The `#process-output-inline` div becomes a container that holds either:
- `#plain-output` div — current plain text display (default)
- `#terminal-output` div — xterm.js mounts here for interactive processes

Both children exist in the DOM at all times; JS shows one and hides the other
based on the selected process type.

---

## When the terminal fires (from Qt6)

**Only** for these three cases:

### 1. Port right-click `[term]` actions
Commands in `[PortTerminalActions]` with `[term]` marker:
```
ssh, mysql, netcat, rdesktop, psql, msfconsole, bash, telnet, rlogin...
```
These are fully interactive sessions (REPL, shell). Qt6 opened an external
xterm window. Flask: creates a PTY session, adds a process row, clicking
that row shows xterm.js in the upper output panel.

### 2. "Open Terminal" from host right-click
Plain bash session for the selected host's IP. Creates a process row with
name "Terminal - <ip>". Clicking it shows xterm.js in the upper panel.

### 3. msfconsole / bash commands
Any command containing 'bash' or 'msfconsole' in the name. When you click
that process row, the upper panel switches to xterm.js.

**Everything else stays exactly as is** — stdin=DEVNULL, plain text output.

---

## Architecture

### Backend

```
_TerminalSession:
  master_fd  — PTY master (write input here, read output from here)
  proc       — subprocess.Popen(['bash'] or [tool command])
  buffer     — bytearray of all output so far
  session_id — UUID

_terminal_sessions: dict[str, _TerminalSession]

New routes:
  POST /api/terminal/start        {command, host_ip, port}  → {session_id, process_id}
  POST /api/terminal/<id>/input   {data}                    → 200
  GET  /api/terminal/<id>/output  ?offset=N                 → {data, alive, offset}
  POST /api/terminal/<id>/resize  {rows, cols}              → 200
  DELETE /api/terminal/<id>                                 → 200
```

`/api/terminal/start` also inserts a process row into the DB (with
`status='Interactive'`) so the process appears in the processes table and
clicking it selects the xterm.js terminal.

### Frontend

`#process-output-inline` becomes:
```html
<div id="process-output-inline" style="flex:1;min-width:0">
  <div id="plain-output" class="tool-output-area ansi">Click a process...</div>
  <div id="terminal-output" style="display:none;flex:1;min-height:0"></div>
</div>
```

`loadProcessOutput(processId)` already fires when a process row is clicked.
It will check if the process is Interactive:
- If yes: hide `#plain-output`, show `#terminal-output`, mount/connect xterm.js
- If no: hide `#terminal-output`, show `#plain-output`, load text as now

xterm.js polls `/api/terminal/<session_id>/output` every 50ms and writes
characters to the terminal. User keystrokes POST to `/api/terminal/<session_id>/input`.

The `session_id` is stored on the process record (or returned alongside the
snapshot process data) so the JS knows which terminal session to connect to.

---

## Test Plan

### Category 1 — Unit/API (`tests/test_terminal.py`)

#### T1: Terminal session lifecycle

| Test | Verifies |
|------|---------|
| `test_start_returns_session_id_and_process_id` | POST /api/terminal/start → 200, body has both `session_id` and `process_id` |
| `test_start_creates_process_row_in_snapshot` | After start, `/api/snapshot` processes list includes the terminal process with status 'Interactive' |
| `test_output_has_content_after_start` | GET output at offset 0 within 2s → non-empty (bash prompt) |
| `test_output_offset_no_duplication` | Read at offset=0, then offset=len(first) → no repeated bytes |
| `test_input_echo` | Write `echo test123\n` → GET output contains 'test123' |
| `test_input_ctrl_c` | Write `\x03` → session still alive, prompt returns |
| `test_resize_accepted` | POST resize {rows:30, cols:120} → 200 |
| `test_delete_terminates_process` | DELETE → proc.poll() is not None |
| `test_delete_removes_from_snapshot` | After DELETE, terminal process gone from snapshot |
| `test_nonexistent_session_404` | GET/POST/DELETE unknown id → 404 |
| `test_two_sessions_independent` | Two sessions, different echo outputs don't mix |
| `test_bash_version_in_output` | Write `echo $BASH_VERSION\n` → output contains version string |

#### T2: Port `[term]` action wiring

| Test | Verifies |
|------|---------|
| `test_term_action_starts_terminal_session` | Service action with `[term]` command index → response has `session_id` |
| `test_non_term_action_has_no_session_id` | Service action without `[term]` → response has `process_id`, no `session_id` |
| `test_open_terminal_host_action` | POST /api/workspace/hosts/<id>/action with action='open-terminal' → starts bash terminal session |

#### T3: Regression

| Test | Verifies |
|------|---------|
| `test_echo_process_unchanged` | echo command: stdout captured, status → Finished, no terminal session created |
| `test_nmap_scan_completes` | nmap stage1: XML import succeeds, no terminal session created |
| `test_snapshot_regular_process_no_session_id` | Regular process in snapshot has no `session_id` field |

---

### Category 2 — Selenium (`tests/test_selenium_terminal.py`)

Module-scoped server on port 5095. Seed one host.

#### S1: Upper output panel switches between plain and terminal

| Test | Verifies |
|------|---------|
| `test_regular_process_shows_plain_output` | Click echo process row → `#plain-output` visible, `#terminal-output` hidden |
| `test_terminal_process_shows_xterm` | Click Interactive process row → `#terminal-output` visible, `#plain-output` hidden |
| `test_switch_back_to_plain` | Click regular process after terminal → `#plain-output` back |
| `test_xterm_canvas_present` | When terminal selected → `<canvas>` element inside `#terminal-output` |
| `test_xterm_has_visible_content` | After 2s, xterm.js canvas has non-zero pixel content |

#### S2: "Open Terminal" from host right-click

| Test | Verifies |
|------|---------|
| `test_open_terminal_in_host_menu` | Right-click host → "Open Terminal" item in context menu |
| `test_open_terminal_creates_process_row` | Click "Open Terminal" → new row in processes table with name containing 'Terminal' |
| `test_open_terminal_selects_xterm` | Clicking the Terminal process row → `#terminal-output` visible with xterm canvas |

#### S3: Terminal correctly identified vs regular process

| Test | Verifies |
|------|---------|
| `test_bash_process_uses_xterm` | `wc.runCommand('bash', ...)` → process row click shows xterm, not plain text |
| `test_echo_process_uses_plain` | `wc.runCommand('echo test', ...)` → process row click shows plain text, not xterm |

---

### Category 3 — Manual tests

| Item | Pass criteria |
|------|---------------|
| Tab completion | Type `ls /us`, Tab → `/usr/` completes |
| Arrow key history | Run command, press ↑ → previous command appears |
| Ctrl+C interrupt | `sleep 100`, Ctrl+C → `^C` shown, new prompt |
| Ctrl+D logout | Empty prompt, Ctrl+D → session closes |
| SSH session | Port right-click SSH → "Open with ssh client" → SSH prompt in upper panel |
| msfconsole | msfconsole [term] action → msfconsole banner in upper panel |
| Colour output | `ls --color` → ANSI colours rendered correctly |
| Paste | Ctrl+V in terminal → clipboard text appears |
| Scroll | Long output → can scroll up through history |
| Resize | Resize browser → xterm.js reflows |

---

## Implementation Steps (test-first every step)

### Step 1 — Backend: terminal session manager + routes
Write T1.x tests first (all failing). Implement `_TerminalSession` + routes.
All T1.x pass before Step 2.

### Step 2 — Backend: wire [term] actions + host "Open Terminal"
Write T2.x + T3.x tests first. Modify service action route and host action handler.
All T2.x + T3.x pass before Step 3.

### Step 3 — Full existing regression check
Run all 756 tests. Zero regressions before touching any frontend.

### Step 4 — Frontend: split `#process-output-inline` into plain + terminal containers
Write S1.x Selenium tests first (all failing).
Change HTML: add `#plain-output` and `#terminal-output` inside `#process-output-inline`.
Add xterm.js CDN to `base.html`.
Modify `loadProcessOutput` in JS: check process status, show correct container, mount xterm.js.
All S1.x pass.

### Step 5 — Frontend: "Open Terminal" from host right-click
Write S2.x tests first. Wire host right-click "Open Terminal" action.
All S2.x pass.

### Step 6 — Frontend: bash/msfconsole process detection
Write S3.x tests. JS detects Interactive status and routes to xterm.js.
S3.x pass.

### Step 7 — Version bump + full regression + commit

---

## What does NOT change

- `stdin=subprocess.DEVNULL` stays for all non-interactive processes
- `#process-output-inline` still works for regular processes (text display)
- All dynamic tool tabs in the right panel: unchanged
- All 756 existing tests pass throughout every step
