"""
Anti-pattern guard tests
========================
Block known-broken patterns from re-entering the codebase.  Each test
documents the bug it prevents and the safe alternative.

Run with: sudo python3 -m pytest tests/test_anti_patterns.py -v

These tests use ripgrep-style file scanning (no production code import)
so they're fast (<1 s) and have no fixture dependencies — safe to run
first in run_tests.sh as a smoke gate.
"""

import os
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _walk_py(*subdirs):
    """Yield (path, line_no, line) for every .py file under given subdirs."""
    for sub in subdirs:
        root = os.path.join(PROJECT_ROOT, sub)
        for dirpath, _dirs, files in os.walk(root):
            if '__pycache__' in dirpath:
                continue
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                path = os.path.join(dirpath, fname)
                rel = os.path.relpath(path, PROJECT_ROOT)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        for i, line in enumerate(f, 1):
                            yield rel, i, line.rstrip('\n')
                except Exception:
                    continue


# ── Guard 1: Don't unlink .legion files mid-run ───────────────────────────────
#
# v10.188 bug: tests/test_api_gaps.py P4.1 unlinked path2 in finally:
# while activeProject was still opened-from-path2.  SQLAlchemy kept FDs
# to the unlinked file alive in its pool.  When the pool ran low under
# concurrent _capture_output writes, it opened *new* connections by
# filename.  SQLite then created a fresh empty file (no schema), and
# every subsequent test got "no such table".
#
# Safe alternative: register cleanup paths in a module-level list and
# delete via atexit, OR delete only after switching to a different project.

_UNLINK_LEGION_RE = re.compile(r'os\.(unlink|remove)\([^)]*\.legion')


def test_no_unlink_of_legion_files_in_finally_blocks():
    """No test may unlink a .legion file while it might still be the active project.
    Register cleanup via atexit instead (see test_api_gaps._files_to_cleanup)."""
    violations = []
    for path, line_no, line in _walk_py('tests'):
        if not _UNLINK_LEGION_RE.search(line):
            continue
        # Re-read file with context to check for atexit / _files_to_cleanup
        with open(os.path.join(PROJECT_ROOT, path)) as f:
            src = f.read().splitlines()
        ctx = '\n'.join(src[max(0, line_no - 6):line_no + 2])
        if '@atexit' in ctx or '_files_to_cleanup' in ctx:
            continue
        # Also walk backwards within the same file to find the enclosing def;
        # if it's named *_cleanup* and is registered with atexit anywhere, allow.
        enclosing_def = None
        for back in range(line_no - 1, -1, -1):
            m = re.match(r'^(def|class)\s+(\w+)', src[back])
            if m:
                enclosing_def = m.group(2)
                break
        if enclosing_def and f'atexit.register({enclosing_def})' in '\n'.join(src):
            continue
        violations.append(f"{path}:{line_no}: {line.strip()}")

    assert not violations, (
        "Found os.unlink/remove on .legion file outside an atexit cleanup. "
        "This was the v10.188 bug - SQLAlchemy holds FDs to the file in its "
        "pool; deleting it mid-run causes 'no such table' under load.\n"
        "Defer to atexit via a _files_to_cleanup list, OR delete only after "
        "switching to a different project.\n\n"
        "Violations:\n  " + "\n  ".join(violations)
    )


# ── Guard 2: killRunningProcesses() is only safe from shutdown handlers ───────
#
# v10.188 lesson: WebController.killRunningProcesses() invokes
# _kill_all_descendants() which walks /proc and SIGKILLs every descendant
# of os.getpid().  In production that's the user's nmap/gobuster
# grandchildren spawned via shell=True.  In Selenium tests it's also
# geckodriver and Firefox spawned by pytest - sweeping them aborts the
# test.  It belongs only in shutdown paths.

_KILL_PROCESSES_RE = re.compile(r'\.killRunningProcesses\s*\(')


def test_kill_running_processes_only_from_shutdown_handlers():
    """killRunningProcesses() / _kill_all_descendants() may only be called
    from shutdown handlers (heartbeat watchdog, SIGINT, /api/exit, /api/processes/drain).
    Calling from any other route SIGKILLs the test browser in Selenium runs."""
    # Allowlist: each entry is the enclosing def name in routes.py.
    # Add to this when introducing a new shutdown path - with justification.
    ALLOWED_FUNCTIONS = {
        'processes_drain',  # explicit drain endpoint for tests
        '_watchdog',        # heartbeat browser-close watchdog
        'exit_server',      # File->Exit
    }

    violations = []
    src_path = os.path.join(PROJECT_ROOT, 'app/web/routes.py')
    with open(src_path) as f:
        src = f.read().splitlines()

    for i, line in enumerate(src, 1):
        if not _KILL_PROCESSES_RE.search(line):
            continue
        enclosing = None
        for back in range(i - 1, -1, -1):
            m = re.match(r'\s*def\s+(\w+)\s*\(', src[back])
            if m:
                enclosing = m.group(1)
                break
        if enclosing in ALLOWED_FUNCTIONS:
            continue
        violations.append(
            f"app/web/routes.py:{i}: in {enclosing}(): {line.strip()}")

    assert not violations, (
        "killRunningProcesses() called from a non-shutdown route handler. "
        "It SIGKILLs every descendant of the Legion process - including "
        "geckodriver/Firefox in Selenium tests.\n"
        "If you really need to stop a single process, use killProcess(pid) "
        "instead. If you need to drain the queue, call /api/processes/drain.\n\n"
        "Violations:\n  " + "\n  ".join(violations)
    )


# ── Guard 3: Long fixed sleeps as synchronization ─────────────────────────────
#
# Sleeps >= 5s are usually a sign that the test is waiting for a poll cycle
# or a background process.  Use WebDriverWait or Python requests polling
# instead - see legion-selenium-test skill for templates.
#
# Some legitimate cases exist (typewriter-effect tests, deliberate timeout
# verification, demo recordings).  Tag them with `# DETERMINISM-EXEMPT:`
# on the same line and explain why.

_LONG_SLEEP_RE = re.compile(r'(?<![\'"])time\.sleep\(\s*([\d.]+)')


def test_no_unjustified_long_sleeps():
    """Sleeps >= 5s are forbidden in tests unless tagged DETERMINISM-EXEMPT
    with a one-line justification."""
    violations = []
    for path, line_no, line in _walk_py('tests'):
        # Skip lines where time.sleep appears inside a string literal.
        # Heuristic: count quote chars before the match position; if odd, we're in a string.
        m = _LONG_SLEEP_RE.search(line)
        if not m:
            continue
        prefix = line[:m.start()]
        # If the prefix has unbalanced quotes, the match is inside a string
        if (prefix.count('"') - prefix.count('\\"')) % 2 == 1:
            continue
        if (prefix.count("'") - prefix.count("\\'")) % 2 == 1:
            continue
        try:
            secs = float(m.group(1))
        except ValueError:
            continue
        if secs < 5.0:
            continue
        if 'DETERMINISM-EXEMPT' in line:
            continue
        # Allow generate_report_*.py - those produce demo HTML and need
        # to wait for visible-in-recording effects.
        if os.path.basename(path).startswith('generate_report'):
            continue
        violations.append(f"{path}:{line_no}: sleep({secs}s)  {line.strip()}")

    assert not violations, (
        "Found time.sleep() >= 5s without justification. Use WebDriverWait "
        "or Python requests polling. If the long sleep is intentional, add "
        "`# DETERMINISM-EXEMPT: <reason>` on the same line.\n\n"
        "Violations:\n  " + "\n  ".join(violations)
    )
