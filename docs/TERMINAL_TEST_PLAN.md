# Legion Flask — Interactive Terminal Test Plan

**Status:** Planning — no implementation yet
**Depends on:** v8.4-flask baseline (756 tests passing)

---

## Where the terminal appears

The terminal replaces `#process-output-inline` — the upper output panel that
shows when you click a process row in the processes table. No modal, no popup.

The panel holds two children, only one visible at a time:
- `#plain-output` — current plain text div (nmap, nikto, hydra, etc.)
- `#terminal-output` — xterm.js mounts here for interactive processes

`loadProcessOutput(processId)` already fires on every process row click.
It checks process status:
- `Interactive` → show `#terminal-output`, connect xterm.js to the PTY session
- anything else → show `#plain-output`, load text as today

---

## When the interactive terminal fires

**Trigger condition (same as Qt6):** the command being run contains
`'bash'` or `'msfconsole'` in it (case-insensitive), OR the action
comes from `[PortTerminalActions]` with a `[term]` marker.

### Group 1 — PortActions with bash or msfconsole in command

These come from port right-click tool actions. Legion runs them through the
existing `handlePortAction` path. If the resolved command contains
'bash' or 'msfconsole', it gets a PTY terminal instead of plain capture.

**Core msfconsole use case (why this feature exists):**
```
vsftpd234-Meta = Run metasploit on vsftpd,
  "msfconsole -q -x 'use exploit/unix/ftp/vsftpd_234_backdoor; setg RHOSTS [IP]; run -j;'",
  ftp
```
Flow:
1. User right-clicks an FTP port → "Run metasploit on vsftpd"
2. PTY starts bash, process row appears as "Run metasploit on vsftpd" with status Interactive
3. After 500ms bash receives: `msfconsole -q -x 'use exploit/...; setg RHOSTS 192.168.85.11; run -j;'\n`
4. msfconsole starts, sets up the exploit, runs it as a background job (`-j`)
5. msfconsole stays open at its `msf6 exploit(...) >` prompt
6. xterm.js in the upper panel shows all of this
7. User types: `sessions`, `sessions -i 1`, `whoami`, etc.

Other msfconsole examples:
```
ccproxy-ftpMeta = Run metasploit on ccproxy,
  "msfconsole -q -x 'use unix/ftp/proftpd_133c_backdoor; ...; run -j;'", ccproxy-ftp

oracle-sid = Oracle SID enumeration,
  "msfconsole -q -n -L -x \"... exit -y\"", oracle-tns   ← auto-exits
```

bash examples (run and exit, output visible in terminal):
```
banner       = Grab banner, bash -c "echo "" | nc -v -n -w1 [IP] [PORT]"
smb-null     = Check for null sessions, bash -c "echo 'srvinfo' | rpcclient [IP] -U%"
smbenum      = Run smbenum, bash ./scripts/smbenum.sh [IP]
snmp-brute   = Bruteforce community strings, bash -c "medusa -h [IP] ..."
```

### Group 2 — PortTerminalActions with `[term]` marker

These are explicitly interactive sessions:
```
ssh    = [term] ssh root@[IP] -p [PORT]           ← SSH session
mysql  = [term] mysql -u root -h [IP] --port=[PORT] -p
netcat = [term] nc -v [IP] [PORT]
psql   = [term] psql -h [IP] -p [PORT] -U postgres
rdesktop, telnet, rpcclient, mssql, ...
```

### Group 3 — "Open Terminal" from host right-click

Plain bash session for the selected host. No initial command — user gets a
bash prompt immediately.

---

## Mechanism: bash PTY + command dispatch (mirrors Qt6 exactly)

```python
# _TerminalSession.__init__:
master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(['bash', '--login'],
                        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                        preexec_fn=os.setsid, env={...TERM: xterm-256color})
os.close(slave_fd)

# After 500ms (if command provided):
os.write(master_fd, (resolved_command + "\n").encode())
# e.g.: msfconsole -q -x 'use exploit/...; run -j;'\n
#   or: ssh root@192.168.85.11 -p 22\n
#   or: mysql -u root -h 192.168.85.11 --port=3306 -p\n
```

- Bash always hosts the PTY (proper environment, signal handling, job control)
- The tool command runs inside bash
- When the command exits (or for msfconsole: when user types `exit`), bash prompt returns
- User can run further commands in the resulting bash shell

---

## Architecture

### Backend routes

```
POST   /api/terminal/start        {command, label, host_ip}  → {session_id, process_id}
POST   /api/terminal/<id>/input   {data}                     → 200
GET    /api/terminal/<id>/output  ?offset=N                  → {data, alive, offset}
POST   /api/terminal/<id>/resize  {rows, cols}               → 200
DELETE /api/terminal/<id>                                    → 200
```

`/api/terminal/start`:
- Creates `_TerminalSession` (bash PTY)
- Inserts a process row with `status='Interactive'` and `name=label`
- Stores `session_id` on the process record so the snapshot returns it
- After 500ms, writes `command\n` to bash stdin (if command provided)
- Returns `{session_id, process_id}`

### Snapshot change

Each process in the snapshot gets a `session_id` field (null for regular processes).
JS uses this to know which terminal session to connect when that process row is clicked.

### What triggers interactive mode

In `handlePortAction` (or the equivalent service action route):
```python
command = resolved_command   # e.g. "msfconsole -q -x '...'"
is_interactive = ('bash' in command.lower() or 'msfconsole' in command.lower())

if is_interactive:
    # start PTY terminal session, return session_id
else:
    # existing Popen path, plain output capture
```

For `[term]` PortTerminalActions: always interactive (the `[term]` marker IS the flag).

---

## Test Plan

### Category 1 — Unit/API (`tests/test_terminal.py`)

#### T1: Terminal session lifecycle

| Test | Verifies |
|------|---------|
| `test_start_returns_session_and_process_id` | POST start → 200, body has `session_id` and `process_id` |
| `test_start_creates_interactive_process_in_snapshot` | `/api/snapshot` includes process with status='Interactive' |
| `test_start_session_id_in_snapshot_process` | The Interactive process in snapshot has `session_id` matching returned value |
| `test_output_has_bash_prompt` | GET output offset=0 within 2s → contains `$` or `#` (bash prompt) |
| `test_output_offset_no_duplication` | Read at offset=0 then offset=len → no repeated bytes |
| `test_command_executed_in_terminal` | Start with command `echo vsftpd_test` → output contains 'vsftpd_test' |
| `test_input_interactive` | Write `echo interactive_input\n` → output contains 'interactive_input' |
| `test_input_ctrl_c` | Write `\x03` to `sleep 30` started via command → session still alive |
| `test_resize_accepted` | POST resize {rows:30, cols:120} → 200 |
| `test_delete_terminates` | DELETE → proc.poll() not None |
| `test_delete_removes_from_snapshot` | After DELETE, Interactive process gone from snapshot |
| `test_nonexistent_404` | GET/POST/DELETE unknown id → 404 |
| `test_two_sessions_independent` | Two sessions, commands echo different strings, outputs don't mix |

#### T2: Port action interactive detection

| Test | Verifies |
|------|---------|
| `test_msfconsole_command_starts_terminal` | Service action with msfconsole command → response has `session_id`, process status=Interactive |
| `test_bash_command_starts_terminal` | Service action with `bash -c "..."` → same |
| `test_plain_command_no_terminal` | Service action with `nmap -sV [IP]` → response has `process_id`, NO `session_id` |
| `test_term_action_starts_terminal` | PortTerminalAction (ssh, netcat, etc.) → response has `session_id` |
| `test_open_terminal_host_action` | POST host action 'open-terminal' → starts bash session, returns `session_id` |

#### T3: Regression — regular processes unaffected

| Test | Verifies |
|------|---------|
| `test_echo_process_still_plain` | echo command → stdout captured as text, status=Finished, no session_id |
| `test_nmap_still_completes` | nmap stage 1 → XML imported, processes Finished, no session_id in snapshot |
| `test_snapshot_no_session_id_for_regular` | Regular process in snapshot has `session_id: null` |

---

### Category 2 — Selenium (`tests/test_selenium_terminal.py`)

Module-scoped server on port 5095. Seed one host.

#### S1: Upper panel switches correctly

| Test | Verifies |
|------|---------|
| `test_regular_process_shows_plain` | Click echo process → `#plain-output` visible, `#terminal-output` hidden |
| `test_interactive_process_shows_xterm` | Click Interactive process → `#terminal-output` visible, `#plain-output` hidden |
| `test_xterm_canvas_present` | `<canvas>` element inside `#terminal-output` when terminal shown |
| `test_switch_back_to_plain` | Click echo process after terminal → `#plain-output` back |

#### S2: msfconsole/bash commands get terminal (unit-level, no real msfconsole needed)

| Test | Verifies |
|------|---------|
| `test_bash_cmd_process_row_shows_xterm` | `wc.runCommand('bash -c "sleep 5"', ...)` → clicking row shows xterm.js, not plain text |
| `test_echo_process_row_shows_plain` | `wc.runCommand('echo test', ...)` → clicking row shows plain text |

#### S3: "Open Terminal" from host right-click

| Test | Verifies |
|------|---------|
| `test_open_terminal_in_host_menu` | Right-click host → "Open Terminal" in menu |
| `test_open_terminal_creates_interactive_row` | Click "Open Terminal" → process row with status Interactive appears |
| `test_open_terminal_row_shows_xterm` | Click the Terminal process row → `#terminal-output` visible with canvas |

---

### Category 3 — Manual tests

| Scenario | Steps | Pass criteria |
|----------|-------|---------------|
| **vsftpd msfconsole** | Right-click FTP port → "Run metasploit on vsftpd" | msfconsole starts, exploit runs as job, `msf6 >` prompt appears in upper panel |
| **msfconsole interaction** | After exploit, type `sessions` | Session list shown in xterm.js |
| **SSH session** | Right-click SSH port → "Open with ssh client" | SSH prompt appears, can log in and run commands |
| **mysql** | Right-click mysql port → "Open with mysql client" | mysql `>` prompt appears, can run SQL |
| **netcat** | Right-click port → "Open with netcat" | nc connects, can send/receive data |
| **Open Terminal** | Right-click host → "Open Terminal" | Bash prompt, can run any command |
| **Tab completion** | Type `ls /us` + Tab | `/usr/` completes |
| **Arrow key history** | Run command, press ↑ | Previous command appears |
| **Ctrl+C** | Start `sleep 100`, press Ctrl+C | `^C` + new prompt |
| **Colour output** | `ls --color` | ANSI colours rendered |

---

## Implementation Steps (test-first, every step)

### Step 1 — Backend: `_TerminalSession` + routes
Write T1.x tests (all failing). Implement session manager + API routes.
**All T1.x pass before Step 2.**

### Step 2 — Backend: interactive detection in port/host actions
Write T2.x + T3.x tests (all failing). Modify `handlePortAction` route and host action handler.
**All T2.x + T3.x pass before Step 3.**

### Step 3 — Existing regression check
Run all 756 tests. **Zero failures before touching any frontend.**

### Step 4 — Frontend: split output panel + xterm.js
Write S1.x Selenium tests (all failing).
- HTML: split `#process-output-inline` into `#plain-output` + `#terminal-output`
- `base.html`: add xterm.js CDN
- JS: `loadProcessOutput` detects Interactive, mounts xterm.js, polls output, POSTs input
**All S1.x + S2.x pass.**

### Step 5 — Frontend: "Open Terminal" host right-click
Write S3.x tests. Wire host right-click "Open Terminal" → start session → process row.
**All S3.x pass.**

### Step 6 — Full regression + version bump + commit

---

## What does NOT change

- `stdin=subprocess.DEVNULL` for all non-interactive tool processes
- `#process-output-inline` plain text mode for nmap, nikto, hydra, eyewitness, etc.
- Dynamic tool tabs in the right panel: completely unchanged
- All 756 existing tests pass at every step
