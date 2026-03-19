# Legion Flask — Terminal Feature Test Plan

**Status:** Planning — no implementation yet
**Depends on:** v8.4-flask baseline (756 tests passing)
**Feature:** Process stdin input + PTY bash terminal (Flask equivalent of Qt6 interactive terminal)

---

## What Qt6 Had

1. **Input bar** — `QLineEdit` at bottom of every process tab. Type text, Enter → `proc.write(text + "\n")` to QProcess stdin.
2. **Interactive mode checkbox** — switches the tab to a full PTY terminal using `pty.openpty()` + `pyte` for ANSI rendering. Full bash session with Ctrl+C, arrow keys, tab completion.

---

## What Flask Will Have

### Part A — Process stdin input bar
A text input at the bottom of every dynamic tool tab. When the process is Running, typing text and pressing Enter writes it to the process's stdin pipe. Useful for: msfconsole commands, hydra interaction, any tool that reads stdin.

### Part B — PTY bash terminal
A "Terminal" button that opens a modal containing a full xterm.js terminal connected to a bash session. The backend manages PTY sessions. Useful for: running commands interactively, post-exploitation shells, any full terminal need.

---

## Architecture

### Backend components

```
WebController._active_processes[id]._popen.stdin  ← PIPE for Part A
TerminalSession (new)                              ← PTY for Part B
  .master_fd  = pty master file descriptor
  .proc       = subprocess.Popen(['bash'])
  .buffer     = bytearray of all output so far

New API routes:
  POST /api/processes/<id>/stdin    ← write to process stdin pipe
  POST /api/terminal/start          ← create new PTY session → returns session_id
  POST /api/terminal/<id>/input     ← write bytes to PTY master_fd
  GET  /api/terminal/<id>/output    ← read buffered output since offset
  POST /api/terminal/<id>/resize    ← TIOCSWINSZ ioctl (rows, cols)
  DELETE /api/terminal/<id>         ← terminate and cleanup
```

### Frontend components

```
Dynamic tool tab:            input bar at bottom (Part A)
Terminal modal:              xterm.js div + resize logic (Part B)
  #terminal-modal            the modal overlay
  #terminal-container        xterm.js mounts here
  action-open-terminal       toolbar button that opens modal
```

---

## Test Plan

### Category 1 — Unit/API tests (no browser)

File: `tests/test_terminal.py`

#### Part A: Process stdin pipe

| Test | What it verifies |
|------|-----------------|
| `test_process_starts_with_stdin_pipe` | After `wc.runCommand(...)`, `proc._popen.stdin` is not None and is writable |
| `test_stdin_write_reaches_process` | Run `cat` process, POST to stdin, verify output contains what was written |
| `test_stdin_write_to_finished_process_errors` | POST to stdin of Finished process → 400/409 error |
| `test_stdin_write_to_nonexistent_process_errors` | POST to stdin of unknown id → 404 |
| `test_stdin_route_requires_text_field` | POST with no body → 400 error |
| `test_stdin_newline_appended` | Writing "hello" (no newline) → process sees "hello\n" |
| `test_nmap_still_works_with_stdin_pipe` | Full nmap stage 1 scan completes correctly with stdin=PIPE |
| `test_echo_output_unchanged` | echo command output unchanged from baseline after stdin change |

#### Part B: PTY terminal sessions

| Test | What it verifies |
|------|-----------------|
| `test_terminal_start_returns_session_id` | POST /api/terminal/start → 200 with `{"session_id": "..."}` |
| `test_terminal_output_initially_has_prompt` | GET /api/terminal/<id>/output → contains bash prompt |
| `test_terminal_input_executed` | POST input "echo hello\n" → GET output contains "hello" |
| `test_terminal_input_ctrl_c` | POST input "\x03" → no crash, new prompt appears |
| `test_terminal_resize_accepted` | POST resize {rows:24, cols:80} → 200 ok |
| `test_terminal_delete_terminates_session` | DELETE terminal → process terminated, subsequent requests 404 |
| `test_terminal_nonexistent_session_errors` | GET/POST on unknown id → 404 |
| `test_terminal_output_offset` | Multiple reads with increasing offset → no data duplication |
| `test_terminal_multiple_sessions_independent` | Two sessions run independently, output doesn't mix |
| `test_terminal_bash_login_shell` | Session runs bash (not sh); `echo $BASH_VERSION` returns a version string |

#### Regression: existing tests must still pass

After stdin=PIPE change:
- All 18 unit test files: `for f in tests/test_*.py; do sudo python3 $f 2>&1 | grep "^Results:"; done`
- All 18 live scan tests: `sudo env LEGION_TEST_TARGET=192.168.85.11 python3 -m pytest tests/test_selenium_ui.py -m live`

Key regression risks:
- `test_signal_chains.py` — nmap chain must still complete correctly
- `test_behavioral.py` — process lifecycle unchanged
- Live scan tests 01–08 — full staged nmap must still work

---

### Category 2 — Selenium tests (browser UI)

File: additions to `tests/test_selenium_gaps.py`

#### Part A: Input bar in dynamic tabs

| Test | What it verifies |
|------|-----------------|
| `test_input_bar_visible_when_process_running` | While a process has status Running, `#proc-stdin-input-<pid>` is visible |
| `test_input_bar_hidden_when_process_finished` | After process Finished, input bar is hidden or disabled |
| `test_input_bar_send_writes_to_process` | Type text in input bar, press Enter → text appears in process output (use `cat` process) |
| `test_input_bar_clears_after_send` | After sending, the input field is empty |
| `test_send_button_works_as_alternative_to_enter` | Click Send button → same result as pressing Enter |

#### Part B: Terminal modal (xterm.js)

| Test | What it verifies |
|------|-----------------|
| `test_terminal_button_exists_in_toolbar` | `#action-open-terminal` button is visible |
| `test_terminal_modal_opens_on_click` | Click terminal button → `#terminal-modal` has `is-open` class |
| `test_terminal_container_rendered` | `#terminal-container` contains the xterm.js canvas after open |
| `test_terminal_modal_closes_with_x` | × button closes the modal |
| `test_terminal_receives_output` | After open, xterm.js canvas has visible content (bash prompt) |
| `test_terminal_modal_cleans_up_on_close` | Closing the modal terminates the backend session (DELETE called) |

---

### Category 3 — Manual tests (cannot automate)

These require human eyes and keyboard interaction:

| Item | How to test |
|------|-------------|
| Tab completion (`Tab` key) | Open terminal modal, type `ls /us`, press Tab, verify `/usr/` completes |
| Arrow key history | Run a command, press Up, verify previous command appears |
| Ctrl+C interrupts | Start `sleep 100`, press Ctrl+C in terminal, verify `^C` and new prompt |
| Ctrl+D closes session | Press Ctrl+D in empty prompt, verify "bash: logout" or session closes |
| Terminal resize | Drag modal larger, verify xterm.js reflowed content correctly |
| msfconsole interaction | Start msfconsole via port right-click, type `version`, verify response |
| Copy/paste in terminal | Select text in terminal, Ctrl+C to copy, Ctrl+V to paste |
| Colour output | Run `ls --color`, verify ANSI colours rendered correctly by xterm.js |

---

## Implementation Order

### Step 1: Prove stdin=PIPE doesn't break anything (before any UI work)
1. Change `stdin=subprocess.DEVNULL` → `stdin=subprocess.PIPE` in `checkProcessQueue`
2. Run ALL unit tests + live scan tests
3. Only proceed to Step 2 if all pass

### Step 2: API routes for process stdin (Part A backend)
1. Add `POST /api/processes/<id>/stdin` route
2. Write `test_terminal.py` Part A tests
3. All tests pass before touching JS

### Step 3: Input bar in dynamic tabs (Part A frontend)
1. Add input bar below output area in `renderDynamicToolTabs`
2. Wire Enter/send to the stdin route
3. Write Selenium tests for input bar
4. All tests pass

### Step 4: PTY terminal backend (Part B backend)
1. Add `_TerminalSession` class to routes.py
2. Add `/api/terminal/*` routes
3. Write `test_terminal.py` Part B tests
4. All tests pass before touching UI

### Step 5: xterm.js terminal modal (Part B frontend)
1. Add xterm.js from CDN to `base.html`
2. Add `#terminal-modal` HTML to `index.html`
3. Add `action-open-terminal` toolbar button
4. Wire JS: open modal → start session → xterm.js → poll output → POST input
5. Write Selenium tests for modal existence and basic open/close
6. Run all 756 existing tests to confirm no regression

### Step 6: Version bump + commit

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| `stdin=PIPE` causes tools to block waiting for input | Test all existing process types (nmap, nikto, hydra) before proceeding |
| PTY not available on all systems | Check `import pty` at startup, disable terminal feature gracefully if missing |
| xterm.js CDN unavailable | Bundle locally as fallback; test with network disabled |
| PTY sessions not cleaned up (leak) | Session manager stores all sessions; DELETE route + timeout cleanup |
| Browser security blocks xterm.js clipboard | Handle `navigator.clipboard` permission denied gracefully |
| Terminal output polling too slow | Start with 50ms interval; tune based on testing |

---

## Definition of Done

- [ ] All existing 756 tests still pass after each step
- [ ] `test_terminal.py` Part A: 8 API tests pass
- [ ] `test_terminal.py` Part B: 10 API tests pass
- [ ] Selenium input bar: 5 tests pass
- [ ] Selenium terminal modal: 6 tests pass
- [ ] Manual checklist signed off (tab complete, Ctrl+C, colours, msfconsole)
- [ ] Version bumped, committed

Total new tests: ~29 automated + manual checklist
