"""
WebController — Qt-free wrapper around controller.py logic.

This translates Qt types to plain Python equivalents:
  QMenu → list of dicts
  QProcess → subprocess.Popen  (Tier 3)
  QTimer → threading.Timer     (Tier 3)
  self.view.xxx() → self.state dict (polled by browser via JSON)

All LOGIC comes from the original controller.py — nothing is reimplemented.
"""

import logging
import os
import signal
import subprocess
import threading
import time

log = logging.getLogger('legion')


def _kill_all_descendants():
    """Kill every descendant process of the current Legion instance.

    Why this is needed:
      subprocess.Popen(cmd, shell=True) creates a /bin/sh shell whose pid is
      stored in proc._popen.pid.  The actual tool (nmap, gobuster, etc.) is a
      CHILD of that shell, not a direct child of Legion.  Sending SIGKILL to
      the shell pid re-parents its children to PID 1 — they keep running as
      orphans.  os.killpg() is unsafe here because shell=True inherits Legion's
      own process group, so killpg would kill the server itself.

    This function:
      1. Reads /proc/*/stat to build a parent→[children] map.
         The comm field (field 2) may contain spaces, so we find the last ')'
         and parse PPID from the fields that follow.
      2. BFS from os.getpid() to collect every descendant PID.
      3. Sends SIGKILL to each descendant (skipping our own PID).

    Called by killRunningProcesses() so it runs on every controlled shutdown
    (File→Exit, heartbeat timeout, SIGINT) in addition to the per-process
    SIGTERM/SIGKILL loop that marks processes Killed in the DB.
    """
    my_pid = os.getpid()
    try:
        # Build ppid → [child_pids] map
        parent_map: dict = {}
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            try:
                with open(f'/proc/{entry}/stat', 'r') as f:
                    data = f.read()
                # The comm field is enclosed in () and may contain spaces.
                # Everything after the last ')' is: state ppid pgrp ...
                comm_end = data.rfind(')')
                if comm_end < 0:
                    continue
                rest = data[comm_end + 2:].split()
                # rest[0] = state, rest[1] = ppid
                child_pid = int(entry)
                ppid = int(rest[1])
                parent_map.setdefault(ppid, []).append(child_pid)
            except Exception:
                pass

        # BFS to collect all descendants
        descendants = []
        queue = [my_pid]
        seen = {my_pid}
        while queue:
            p = queue.pop(0)
            for child in parent_map.get(p, []):
                if child not in seen:
                    seen.add(child)
                    descendants.append(child)
                    queue.append(child)

        killed = 0
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, OSError):
                pass  # already gone

        if killed:
            log.info(f"[WebController] _kill_all_descendants: sent SIGKILL to "
                     f"{killed} descendant process(es)")
    except Exception as e:
        log.error(f"[WebController] _kill_all_descendants error: {e}")


def _kill_subtree(root_pid):
    """Kill all descendants of root_pid (NOT root_pid itself).

    Used by killProcess() to kill the actual tool (nmap, nikto, etc.) after
    killing its parent shell.  shell=True means proc._popen.pid is /bin/sh;
    the real tool is a child of that shell.  Killing only the shell leaves the
    tool running as an orphan, holding the write end of the stdout pipe open —
    which keeps _capture_output blocked on readline() indefinitely.

    Scoped to root_pid's subtree rather than all of Legion's descendants so
    that killing one process doesn't accidentally kill other tool processes.
    """
    try:
        parent_map: dict = {}
        for entry in os.listdir('/proc'):
            if not entry.isdigit():
                continue
            try:
                with open(f'/proc/{entry}/stat', 'r') as f:
                    data = f.read()
                comm_end = data.rfind(')')
                if comm_end < 0:
                    continue
                rest = data[comm_end + 2:].split()
                child_pid = int(entry)
                ppid = int(rest[1])
                parent_map.setdefault(ppid, []).append(child_pid)
            except Exception:
                pass

        to_kill = []
        queue: list = [root_pid]
        seen = {root_pid}
        while queue:
            p = queue.pop(0)
            for child in parent_map.get(p, []):
                if child not in seen:
                    seen.add(child)
                    to_kill.append(child)
                    queue.append(child)

        killed = 0
        for pid in to_kill:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, OSError):
                pass

        if killed:
            log.info(f"[WebController] _kill_subtree({root_pid}): sent SIGKILL to {killed} child process(es)")
    except Exception as e:
        log.warning(f"[WebController] _kill_subtree({root_pid}) error: {e}")


class WebProcessStub:
    """
    Qt-free stand-in for MyQProcess.
    Provides the same attributes that ProcessRepository.storeProcess() reads:
      proc.processId(), proc.name, proc.tabTitle, proc.hostIp,
      proc.port, proc.protocol, proc.command, proc.startTime, proc.outputfile
    """

    def __init__(self, name, tabTitle, hostIp, port, protocol, command, startTime, outputfile):
        self.id = -1           # set by storeProcess after DB insert
        self.name = str(name)
        self.tabTitle = str(tabTitle)
        self.hostIp = str(hostIp)
        self.port = str(port)
        self.protocol = str(protocol)
        self.command = str(command)
        self.startTime = str(startTime)
        self.outputfile = str(outputfile)
        self.elapsed = -1
        self.pid = None        # real OS pid, set after Popen
        self._popen = None     # the subprocess.Popen object

    def processId(self):
        """Called by ProcessRepository.storeProcess()"""
        return self.pid or 0


class WebController:
    """
    Tier 2: Replaces QMenu-returning methods with JSON-returning equivalents.
    Uses the same settings and logic objects as the Qt6 Controller.

    Usage:
        wc = WebController(logic, settings)
        menu = wc.getContextMenuForHost(isChecked='False')
        # menu is a list of dicts, not a QMenu
    """

    def __init__(self, logic, settings):
        import queue
        self.logic = logic
        self.settings = settings
        self._active_processes = {}
        self.processes = []
        self.processTimers = {}
        self.processMeasurements = {}
        self.fastProcessQueue = queue.Queue()
        self.fastProcessesRunning = 0
        self.slowProcessesRunning = 0
        self._pending_ports_stages = {}    # hostIp -> set of stage nums still running
        self._pending_stages_lock = threading.Lock()
        self._scheduler_lock      = threading.Lock()  # serialise concurrent scheduler() calls (race fix)
        self._scan_generation = {}         # hostIp -> int; bumped each new scan so stale threads self-cancel
        self._pending_scan_notes = {}      # hostIp -> note text deferred until host exists in DB
        self._state_changed = False
        self._matches = {}
        self._deleted_hosts = set()   # Qt6: screenshooter blacklist for deleted hosts
        self._exit_requested = False  # set True by SIGINT; JS detects via snapshot → shows save dialog
        log.info("[WebController] initialized")

    def applySettings(self):
        """Qt6: applySettings() — hot-reload settings from disk into running state.
        Called after saving legion.conf or activating a config profile so the
        scheduler, screenshooter, and other components see new values immediately
        without a server restart."""
        from app.settings import AppSettings, Settings
        try:
            self.settings = Settings(AppSettings())
            log.info("[WebController] applySettings: settings reloaded from disk")
        except Exception as e:
            log.error(f"[WebController] applySettings error: {e}")
        # Qt6: controller.py:213 — wire store-cleartext-passwords-on-exit after settings reload
        self._apply_store_wordlists_setting()

    def _apply_store_wordlists_setting(self):
        """Wire brute_store_cleartext_passwords_on_exit from settings to the active project.
        Qt6: controller.py:213 — called in applySettings and after project creation/open."""
        try:
            store = getattr(self.settings, 'brute_store_cleartext_passwords_on_exit', 'True') == 'True'
            from app.ProjectManager import ProjectManager
            ProjectManager.setStoreWordListsOnExit(self.logic.activeProject, store)
            log.debug(f"[WebController] storeWordListsOnExit set to {store}")
        except Exception as e:
            log.debug(f"[WebController] _apply_store_wordlists_setting: {e}")

    # ──────────────────────────────────────────────────────────────
    # GROUP A: Lifecycle methods
    # Qt6 ref: controller.py lines noted per method
    # self.view.xxx() calls → no-ops (browser polls state via JSON)
    # ──────────────────────────────────────────────────────────────

    def start(self, title='*untitled'):
        """controller.py:149 — init process tracking for a project."""
        import queue
        self.processes = []
        self.fastProcessQueue = queue.Queue()
        self.fastProcessesRunning = 0
        self.slowProcessesRunning = 0
        self._pending_ports_stages = {}
        self._scan_generation = {}
        self._screenshots_taken = set()   # reset per project — was lazily init'd, leaked across project switches
        self._checked_process_ids = set() # process IDs selected via checkbox column
        self._deleted_hosts = set()       # reset per project — deletions must not blacklist re-seeded hosts
        self._scan_uptime_start = None    # wall time when first non-interactive process started
        self._scan_uptime_end   = None    # wall time when last non-interactive process finished
        self._shutting_down     = False   # set True in killRunningProcesses() to block scheduler
        self._state_changed = True
        log.info(f"[WebController] start('{title}')")
        # Qt6: controller.py:213 — apply store-cleartext setting on project init
        self._apply_store_wordlists_setting()
        # Write a PID sentinel so _cleanup_orphaned_temp_files() can determine
        # whether this running folder belongs to a live server instance.
        # The DB and running/output folders are independently named (separate
        # mkdtemp calls), so PID-based liveness is the only reliable signal.
        try:
            pid_file = os.path.join(
                self.logic.activeProject.properties.runningFolder, '.legion_session_pid')
            with open(pid_file, 'w') as _pf:
                _pf.write(str(os.getpid()))
        except Exception as _pe:
            log.debug(f"[WebController] Could not write session PID file: {_pe}")
        # Defensive startup: clean up any state left by an unclean previous shutdown
        self._startup_check()
        # Restore keyword match state saved by the previous session
        self.loadMatchState()
        # Restore process checkbox selections
        self.loadCheckedState()

    def _startup_check(self):
        """Clean up state left by an unclean previous shutdown (SIGKILL, power loss, etc.).

        Two things can be wrong at startup:
        1. Processes with status='Running' or 'Waiting' in the DB — they were active
           when the server died and were never marked Killed/Crashed.  If left as-is
           they appear Running forever in the UI and block process-queue slot counting.
        2. Stale .live_output temp files in the output/running folders — the process
           output API serves these as live data; leftover files from the previous session
           would serve old output for new process IDs or cause the API to return wrong data.
        """
        from app.timing import getTimestamp
        # Mark orphan Running/Waiting processes as Crashed
        try:
            from sqlalchemy import text as _t
            session = self.logic.activeProject.database.session()
            try:
                result = session.execute(_t(
                    "UPDATE process SET status='Crashed', endTime=:ts "
                    "WHERE status IN ('Running', 'Waiting')"
                ), {"ts": getTimestamp(True)})
                count = result.rowcount
                session.commit()
                if count:
                    log.warning(
                        f"[WebController] Startup: marked {count} orphan process(es) as Crashed "
                        f"(server was killed before previous session could clean up)"
                    )
                else:
                    log.info("[WebController] Startup check: no orphan processes found")
            finally:
                session.close()
        except Exception as e:
            log.error(f"[WebController] _startup_check: orphan process cleanup failed: {e}")

        # Clean up stale .live_output temp files
        try:
            cleaned = 0
            for folder in [
                self.logic.activeProject.properties.runningFolder,
                self.logic.activeProject.properties.outputFolder,
            ]:
                if os.path.isdir(folder):
                    for fname in os.listdir(folder):
                        if fname.endswith('.live_output'):
                            try:
                                os.unlink(os.path.join(folder, fname))
                                cleaned += 1
                            except Exception:
                                pass
            if cleaned:
                log.info(f"[WebController] Startup: removed {cleaned} stale .live_output file(s)")
        except Exception as e:
            log.error(f"[WebController] _startup_check: live_output cleanup failed: {e}")

        # Clean up orphaned temp files from previous server instances killed without
        # running closeProject() (e.g. SIGKILL, power loss).  Each new instance gets
        # unique paths so there is no data reuse, but the leftovers accumulate.
        #
        # Strategy for DB files: try flock(LOCK_EX|LOCK_NB) — if we can grab an
        # exclusive lock, no other process holds the file open and it is safe to delete.
        # For companion -running/-tool-output folders we delete those whose matching
        # .legion DB is gone (meaning the session that owned them is dead).
        self._cleanup_orphaned_temp_files()

    @staticmethod
    def _file_is_open_by_any_process(filepath):
        """Return True if any running process currently has filepath open.

        Uses /proc/PID/fd symlinks (Linux) — accurate regardless of lock type.
        SQLite uses POSIX fcntl advisory locks (not BSD flock), so flock-based
        liveness tests give false negatives against SQLAlchemy pool connections.
        /proc scanning checks actual open file descriptors, which is definitive:
        a live server keeps its .legion file open in the SQLAlchemy connection pool;
        a dead session's file has zero open FDs from any process.
        """
        try:
            realpath = os.path.realpath(filepath)
            proc_dir = '/proc'
            if not os.path.isdir(proc_dir):
                return False   # non-Linux fallback: assume in-use (safe default)
            for pid_entry in os.listdir(proc_dir):
                if not pid_entry.isdigit():
                    continue
                fd_dir = os.path.join(proc_dir, pid_entry, 'fd')
                try:
                    for fd_name in os.listdir(fd_dir):
                        try:
                            link = os.readlink(os.path.join(fd_dir, fd_name))
                            if link == realpath:
                                return True
                        except OSError:
                            pass
                except (PermissionError, FileNotFoundError):
                    pass
        except Exception:
            pass
        return False

    def _cleanup_orphaned_temp_files(self):
        """Remove /tmp/legion/ leftovers from dead server instances.

        Liveness test: scan /proc/PID/fd for open file descriptors pointing at
        each candidate .legion file.  A live server keeps its DB open via the
        SQLAlchemy connection pool, so an orphaned file (dead session) is the
        only one with zero open FDs across all running processes.
        """
        import glob as _glob
        import shutil as _sh

        tmp_base = '/tmp/legion'
        if not os.path.isdir(tmp_base):
            return

        current_db      = self.logic.activeProject.properties.projectName
        current_running = self.logic.activeProject.properties.runningFolder
        current_output  = self.logic.activeProject.properties.outputFolder

        removed_files = 0
        removed_dirs = 0
        live_db_paths = set()

        # Pass 1: identify and delete orphaned .legion DB files
        for db_path in _glob.glob(os.path.join(tmp_base, 'legion-*.legion')):
            if db_path == current_db:
                live_db_paths.add(db_path)
                continue
            if self._file_is_open_by_any_process(db_path):
                # Another live server instance owns this file — leave it alone
                live_db_paths.add(db_path)
                continue
            try:
                os.unlink(db_path)
                # Remove companion WAL and SHM files if present
                for suffix in ('-wal', '-shm'):
                    companion = db_path + suffix
                    if os.path.isfile(companion):
                        os.unlink(companion)
                removed_files += 1
            except Exception as e:
                log.debug(f"[WebController] cleanup: could not remove {db_path}: {e}")
                live_db_paths.add(db_path)

        # Pass 2: remove -running and -tool-output dirs whose owner process is dead.
        #
        # We cannot derive which .legion DB owns which folder from the filename —
        # each is created by an independent mkdtemp/NamedTemporaryFile call with a
        # different random suffix.  Instead we rely on a .legion_session_pid sentinel
        # file written by start().  If the PID in that file is no longer running,
        # the session is dead.  Folders without a PID file are skipped (conservative).
        for pattern in ('legion-*-running', 'legion-*-tool-output'):
            for folder in _glob.glob(os.path.join(tmp_base, pattern)):
                if folder in (current_running, current_output):
                    continue
                pid_file = os.path.join(folder, '.legion_session_pid')
                if not os.path.isfile(pid_file):
                    # No sentinel — older installation or folder not yet started.
                    # Skip conservatively to avoid deleting live session folders.
                    continue
                try:
                    pid = int(open(pid_file).read().strip())
                    os.kill(pid, 0)    # signal 0: raises OSError if process is dead
                    # Process is alive — this folder belongs to a live server; skip
                    continue
                except (ValueError, OSError):
                    pass   # PID file corrupt, or process dead → orphaned
                try:
                    _sh.rmtree(folder, ignore_errors=True)
                    removed_dirs += 1
                except Exception:
                    pass

        if removed_files or removed_dirs:
            log.info(
                f"[WebController] Startup: cleaned {removed_files} orphaned DB file(s) "
                f"and {removed_dirs} orphaned folder(s) from /tmp/legion/"
            )

    def _release_outgoing_session(self):
        """Release the SQLAlchemy scoped_session of the OUTGOING project before
        switching to a new one.

        Why this is needed:
          The scoped_session is thread-local.  After `logic.activeProject` is
          reassigned, the request thread (and any other thread that touched
          the OLD scoped_session) keeps a stale registry entry pointing at the
          OLD engine.  The next write through that registry hits the OLD
          engine, raising OperationalError: no such table when the new
          project's path is queried via the wrong connection.

          session.remove() pops the thread-local entry; the next session()
          call creates a fresh session bound to whatever engine
          activeProject.database currently has.

        What we DO NOT do here:
          - We do NOT call killRunningProcesses() / _kill_all_descendants().
            That sweeps /proc and SIGKILLs every descendant of os.getpid().
            In production that's nmap/gobuster grandchildren spawned via
            shell=True (correct).  In tests pytest spawns geckodriver and
            Firefox as descendants — sweeping them aborts the test.
            Subprocess cleanup belongs to the heartbeat watchdog / SIGINT
            handler / File→Exit, not to a routine project switch.
          - We do NOT SIGTERM tracked _active_processes.  That would kill
            Interactive PTY sessions that the user wants to preserve through
            save-as (test_save_open_data::TestInteractivePtyOutputSaved).

        How _capture_output threads avoid stale-engine writes:
          They hold a captured `processRepo` bound to the OUTGOING dbAdapter.
          The OUTGOING engine is still alive after the switch (we only release
          its scoped_session, not dispose it), so writes go to the OLD DB
          file.  As long as the OLD file exists on disk (which is the
          production contract — only closeProject() deletes files), those
          writes are valid.  The current project's snapshot reads use the
          NEW activeProject's repos, so cross-project bleed is prevented.

        Called by createNewProject, openExistingProject, and saveProjectAs
        (which all reassign logic.activeProject)."""
        try:
            old_proj = self.logic.activeProject
        except Exception:
            return
        try:
            old_proj.database.session.remove()
        except Exception:
            log.debug("[WebController] _release_outgoing_session: session.remove() failed")

    def createNewProject(self):
        """controller.py:303"""
        self._release_outgoing_session()
        self.logic.createNewTemporaryProject()
        self.start()

    def openExistingProject(self, filename, projectType='legion'):
        """controller.py:308 — open .legion file, no Qt dialogs."""
        self._release_outgoing_session()
        try:
            self.logic.openExistingProject(filename, projectType)
        except Exception as exc:
            log.error(f"[WebController] Failed to open project {filename}: {exc}")
            self.logic.createNewTemporaryProject()
            self.start()
            return False
        self.start(os.path.basename(self.logic.activeProject.properties.projectName))
        try:
            repo = self.logic.activeProject.repositoryContainer.processRepository
            repo.resetDisplayStatusForOpenProcesses()
        except Exception:
            log.exception("Failed to reset process display status")
        return True

    def closeProject(self):
        """controller.py:417 — cleanup without Qt threads."""
        self.killRunningProcesses()
        # WAL checkpoint: flush all WAL writes into the main DB file before closing.
        # Skipping this on unclean exit is safe (WAL is replayed on next open), but
        # doing it explicitly on a clean shutdown speeds up the next open and prevents
        # the main DB file from being stale relative to the WAL.
        try:
            from sqlalchemy import text as _t
            db = self.logic.activeProject.database
            db.session.remove()   # release scoped session before raw checkpoint
            with db.engine.connect() as _conn:
                _conn.execute(_t("PRAGMA wal_checkpoint(TRUNCATE)"))
            log.info("[WebController] WAL checkpoint completed")
        except Exception as e:
            log.error(f"[WebController] WAL checkpoint failed: {e}")
        # Dispose the SQLAlchemy engine so all connection pool connections are
        # closed before ProjectManager deletes the underlying DB file.
        # Without this the engine pool holds open FDs to a file that is about
        # to be unlinked — harmless on Linux (inode stays until FD closes) but
        # leaves WAL/SHM companion files behind if SQLite flushes after unlink.
        try:
            self.logic.activeProject.database.dispose()
            log.info("[WebController] Database engine disposed")
        except Exception as e:
            log.error(f"[WebController] database.dispose() failed: {e}")
        self.logic.projectManager.closeProject(self.logic.activeProject)
        log.info("[WebController] closeProject done")

    def saveProject(self, lastHostIdClicked, notes):
        """controller.py:348 — save notes for a host. Pure logic, zero Qt."""
        if not lastHostIdClicked or lastHostIdClicked in ['None', '']:
            return
        try:
            if isinstance(lastHostIdClicked, str) and '.' in lastHostIdClicked:
                host = self.logic.activeProject.repositoryContainer.hostRepository.getHostByIP(lastHostIdClicked)
                if host:
                    hostId = host.id
                else:
                    return
            else:
                hostId = int(lastHostIdClicked)
            self.logic.activeProject.repositoryContainer.noteRepository.storeNotes(hostId, notes)
        except Exception as e:
            log.error(f"[WebController] saveProject error: {e}")

    def _append_to_host_notes(self, host_arg, text):
        """Append text to the notes of each host in host_arg (comma-separated IPs).
        Skips silently if a host is not yet in the DB (e.g. first-time scan)."""
        ips = [ip.strip() for ip in str(host_arg).split(',') if ip.strip()]
        try:
            repo = self.logic.activeProject.repositoryContainer
            for ip in ips:
                try:
                    host = repo.hostRepository.getHostByIP(ip)
                    if not host:
                        log.debug(f"[WebController] _append_to_host_notes: {ip} not in DB yet — skipping")
                        continue
                    note = repo.noteRepository.getNoteByHostId(host.id)
                    existing = (getattr(note, 'text', '') or '') if note else ''
                    new_text = (existing.rstrip('\n') + '\n\n' + text).lstrip('\n')
                    repo.noteRepository.storeNotes(host.id, new_text)
                    log.debug(f"[WebController] Appended scan commands to notes for {ip}")
                except Exception as _ne:
                    log.warning(f"[WebController] Could not append notes for {ip}: {_ne}")
        except Exception as e:
            log.error(f"[WebController] _append_to_host_notes error: {e}")

    def saveProjectAs(self, filename, replace=0):
        """controller.py:390 — save project to file.
        saveProjectAs reassigns logic.activeProject to the saved file's project
        (per ProjectManager.saveProjectAs), so we must release the OUTGOING
        session for the same reason as createNewProject/openExistingProject."""
        self.saveRunningProcessOutputs()
        self._release_outgoing_session()
        try:
            return self.logic.saveProjectAs(filename, replace)
        except Exception as exc:
            log.error(f"[WebController] saveProjectAs error: {exc}")
            return False

    def importFinished(self):
        """controller.py:2136 — refresh DB session after nmap import."""
        try:
            if hasattr(self.logic.activeProject, "database"):
                session = self.logic.activeProject.database.session()
                session.expire_all()
                session.close()
        except Exception:
            log.exception("importFinished: failed to refresh DB session")
        self._state_changed = True

    def addPortToHost(self, host_ip, port_data):
        """controller.py:2621 — add a port to a host. Pure DB logic."""
        from db.entities.port import portObj
        host = self.logic.activeProject.repositoryContainer.hostRepository.getHostByIP(host_ip)
        if not host:
            log.error(f"[WebController] addPortToHost: host {host_ip} not found")
            return
        try:
            port_id = str(port_data.get('port', '')).strip()
            protocol = str(port_data.get('protocol', 'tcp')).strip()
            state = str(port_data.get('state', 'open')).strip()
            new_port = portObj(port_id, protocol, state, host.id)
            session = self.logic.activeProject.database.session()
            try:
                session.add(new_port)
                session.commit()
            finally:
                session.close()
            log.info(f"[WebController] Added port {port_id}/{protocol} to {host_ip}")
        except Exception as e:
            log.error(f"[WebController] addPortToHost error: {e}")

    # ──────────────────────────────────────────────────────────────
    # P1: Match Detection (from auxiliary.py:262-331)
    # Exact port of MyQProcess.getMatches() + handleMatches()
    # ──────────────────────────────────────────────────────────────

    def detectMatches(self, line, toolName=''):
        """Port of auxiliary.py:262-323 — detect matches in a line of output.
        Returns set of matched patterns (empty if negative pattern hit first).

        Substring filtering only applies when the ACTUAL negative pattern
        text appears in the line. If the line says 'open' and the negative
        is 'is already open', we only filter if 'is already open' is in the line."""
        ms = getattr(self.settings, 'matchSettings', {})
        if not ms:
            return set()

        # Check global patterns (negative first, then positive)
        globalMatches = self._getMatches(line, ms, 'global')
        # Check tool-specific patterns
        toolMatches = self._getMatches(line, ms, toolName) if toolName else set()

        matches = globalMatches.union(toolMatches)

        # Substring filtering (auxiliary.py:312-323)
        # Only filter if the negative pattern itself appears in THIS line
        negativePatterns = []
        if 'global' in ms and 'negative' in ms['global']:
            negativePatterns.extend(ms['global']['negative'])
        if toolName in ms and 'negative' in ms[toolName]:
            negativePatterns.extend(ms[toolName]['negative'])

        patternsToRemove = set()
        for pattern in matches:
            for negPattern in negativePatterns:
                # Only remove if the negative pattern is actually IN this line
                if pattern in negPattern and pattern != negPattern and negPattern in line:
                    patternsToRemove.add(pattern)
                    break

        return matches - patternsToRemove

    @staticmethod
    def _pattern_matches(pattern, line):
        """Case-sensitive pattern match respecting space-based word-boundary guards.

        If the stored keyword has a leading space, the character immediately before
        the keyword text in the line must NOT be a word character (\w = [a-zA-Z0-9_]).
        If it has a trailing space, the character immediately after must not be \w.
        This prevents ' PUT ' from matching 'outputfile', 'INPUT', 'OUTPUT', etc.

        Keywords without leading/trailing spaces use plain substring matching
        (backward-compatible with all existing multi-word phrases like
        'State: VULNERABLE', 'Dumping local SAM hashes', etc.).
        """
        import re
        stripped = pattern.strip(' ')
        if not stripped:
            return False
        if pattern == stripped:
            # No boundary spaces — fast path, plain case-sensitive substring match
            return stripped in line
        # Build a regex that anchors on word boundaries where spaces were present
        core    = re.escape(stripped)
        prefix  = r'(?<!\w)' if pattern[0]  == ' ' else ''
        suffix  = r'(?!\w)'  if pattern[-1] == ' ' else ''
        return bool(re.search(prefix + core + suffix, line))

    def _getMatches(self, line, settings, name):
        """Port of auxiliary.py:262-282 — check one line against one settings group.
        Negative patterns checked FIRST — if any match, return empty."""
        matches = set()
        if name not in settings:
            return matches
        current = settings[name]
        # Check negative patterns FIRST
        if 'negative' in current:
            for pattern in current['negative']:
                if self._pattern_matches(pattern, line):
                    return matches  # Negative hit → no matches for this line
        # Check positive patterns
        if 'positive' in current:
            for pattern in current['positive']:
                if self._pattern_matches(pattern, line):
                    matches.add(pattern)
        return matches

    # ──────────────────────────────────────────────────────────────
    # P3: Deduplication (from controller.py:3746-3789)
    # ──────────────────────────────────────────────────────────────

    def checkDuplicate(self, toolName, hostIp, port, protocol='tcp', user_triggered=False):
        """Check if this tool was already run on this host:port.
        Returns: 'run' | 'skip' | 'newTab' | 'append' | 'askMe'

        Checks two layers (Qt6: controller.py:checkDuplicate):
        1. Process table — same name+hostIp+port already ran
        2. Script table — nmap NSE scripts already stored for this port
           (Qt6: scriptRepository.getScriptsByPortId before running scheduler tools)
           Only applied when user_triggered=False (scheduler context).
        """
        mode = getattr(self.settings, 'general_tool_duplication', 'skip')
        if mode not in ('skip', 'newTab', 'append', 'askMe'):
            mode = 'skip'

        # Layer 1: Process-level duplicate check
        try:
            from sqlalchemy import text
            session = self.logic.activeProject.database.session()
            try:
                result = session.execute(text(
                    "SELECT COUNT(*) FROM process WHERE name = :name AND hostIp = :ip AND port = :port "
                    "AND closed = 'False'"
                ), {"name": toolName, "ip": hostIp, "port": port}).fetchone()
                existing = int(result[0]) if result else 0
            finally:
                session.close()
        except Exception:
            existing = 0

        if existing > 0:
            return mode  # Process-level duplicate found

        # Layer 2: Script-level duplicate check (Qt6: scriptRepository.getScriptsByPortId)
        # If nmap NSE scripts exist for this port, the port has already been fully scanned.
        # Apply the duplicate mode so scheduler tools don't re-run against already-scanned ports.
        try:
            from sqlalchemy import text as _text
            session2 = self.logic.activeProject.database.session()
            try:
                result2 = session2.execute(_text(
                    "SELECT COUNT(*) FROM l1ScriptObj AS s "
                    "INNER JOIN portObj AS p ON p.id = s.portId "
                    "INNER JOIN hostObj AS h ON h.id = p.hostId "
                    "WHERE h.ip = :ip AND p.portId = :port AND p.protocol = :protocol"
                ), {"ip": hostIp, "port": str(port), "protocol": protocol}).fetchone()
                script_count = int(result2[0]) if result2 else 0
            finally:
                session2.close()
        except Exception:
            script_count = 0

        if script_count > 0 and not user_triggered:
            # Only block if a process already exists for this tool+host+port.
            # If NSE scripts exist but no process ran (existing == 0), the tool was
            # never triggered — most likely because the port's service name was only
            # properly resolved by stage-6 -sV, which also stores NSE scripts.
            # Blocking here permanently prevents the tool from ever running.
            # Layer-1 (existing > 0) already handles the true re-run case.
            log.debug(f"[checkDuplicate] {toolName} on {hostIp}:{port} — {script_count} NSE scripts exist but no prior process — allowing")
            # Fall through to 'run'

        return 'run'  # No duplicate at either level

    def cleanupPurgedHost(self, ip):
        """controller.py:2783 — delayed validation after purge. No QTimer."""
        log.info(f"[WebController] cleanupPurgedHost({ip})")
        self._state_changed = True

    def cleanupDeletedHost(self, ip):
        """controller.py:2691 — delayed validation after delete. No QTimer."""
        log.info(f"[WebController] cleanupDeletedHost({ip})")
        self._state_changed = True

    def processFinished(self, proc):
        """controller.py:2223 — handle process completion without Qt."""
        if proc is None:
            return
        try:
            processRepo = self.logic.activeProject.repositoryContainer.processRepository
            proc_id = getattr(proc, 'id', None)
            if proc_id and not processRepo.isKilledProcess(str(proc_id)):
                outputfile = getattr(proc, 'outputfile', '')
                if outputfile:
                    try:
                        self.logic.toolCoordinator.saveToolOutput(
                            self.logic.activeProject.properties.outputFolder, outputfile)
                    except Exception:
                        pass
                log.info(f"[WebController] Process {proc_id} finished")
            if proc in self.processes:
                self.processes.remove(proc)
            self.fastProcessesRunning = max(0, self.fastProcessesRunning - 1)
            # NOTE: slowProcessesRunning is decremented in _capture_output (which calls
            # this function), NOT here — decrementing in both places causes a double-
            # decrement that makes max-slow-processes completely ineffective.
        except Exception:
            log.exception("[WebController] processFinished error")

    def processCrashed(self, proc, error=None):
        """controller.py:2187 — handle crash without Qt MessageBox."""
        if proc is None:
            return
        try:
            processRepo = self.logic.activeProject.repositoryContainer.processRepository
            proc_id = getattr(proc, 'id', None)
            if proc_id:
                processRepo.storeProcessCrashStatus(str(proc_id))
                log.error(f"[WebController] Process {proc_id} crashed: {error}")
        except Exception:
            log.exception("[WebController] processCrashed error")

    def screenshotFinished(self, ip=None, port=None, filename=None):
        """controller.py:2151 — store screenshot in DB without Qt."""
        if not ip or not filename:
            return
        try:
            host = self.logic.activeProject.repositoryContainer.hostRepository.getHostByIP(str(ip))
            if not host:
                return
            self.logic.activeProject.repositoryContainer.processRepository.storeScreenshot(ip, port, filename)
            log.info(f"[WebController] Screenshot stored: {ip}:{port} → {filename}")
        except Exception as e:
            log.error(f"[WebController] screenshotFinished error: {e}")

    def _run_screenshot(self, ip, port, svc_name=''):
        """Run eyewitness via runCommand so the process appears in the Processes/Tools
        table immediately (Waiting → Running → Finished), matching Qt6 visibility.
        Qt6 used a QThread (Screenshooter); Flask uses the normal subprocess pipeline.
        Qt6: Screenshooter blacklist — skip if host was deleted mid-scan."""
        from app.timing import getTimestamp
        from app.auxiliary import isKali

        # Qt6: screenshooter blacklist — do not screenshot deleted hosts
        if ip in getattr(self, '_deleted_hosts', set()):
            log.info(f"[WebController] Screenshot skipped — {ip} is in deletion blacklist")
            return False

        # Check eyewitness is installed before queuing anything
        eyewitness = '/usr/bin/eyewitness' if isKali() else '/usr/local/bin/eyewitness'
        if not os.path.isfile(eyewitness):
            log.warning(f"[WebController] eyewitness not found at {eyewitness} — screenshot skipped for {ip}:{port}")
            return False

        # Pre-flight TCP check — skip if the port is not reachable.
        # eyewitness raises WebDriverError on connection-refused which clutters
        # the output without producing a screenshot.
        import socket as _socket
        try:
            _s = _socket.create_connection((ip, int(port)), timeout=5)
            _s.close()
        except (OSError, ValueError):
            log.info(f"[WebController] Screenshot skipped — {ip}:{port} unreachable (connection refused/timeout)")
            return False

        output_folder = self.logic.activeProject.properties.outputFolder
        screenshots_dir = os.path.join(output_folder, 'screenshots')
        try:
            os.makedirs(screenshots_dir, exist_ok=True)
        except Exception:
            pass

        # Derive protocol from service name — reliable and instant vs live probe.
        # Service names that imply HTTPS/SSL: https, ssl, https-alt, ssl/http, ssl/https.
        _svc = (svc_name or '').lower().strip()
        _is_https = 'https' in _svc or (_svc == 'ssl') or _svc.startswith('ssl/')

        if _is_https:
            # Verify the TLS handshake actually succeeds before committing to https://.
            # CERT_NONE accepts self-signed certs; we only fall back if the TLS protocol
            # itself is rejected (e.g. TLS 1.0 with weak ciphers on old Java servers).
            import ssl as _ssl
            _ctx = _ssl.create_default_context()
            _ctx.check_hostname = False
            _ctx.verify_mode = _ssl.CERT_NONE
            try:
                with _socket.create_connection((ip, int(port)), timeout=5) as _raw:
                    with _ctx.wrap_socket(_raw, server_hostname=ip):
                        pass  # TLS handshake succeeded — keep https://
            except (_ssl.SSLError, OSError):
                log.info(f"[WebController] TLS negotiation failed for {ip}:{port} — falling back to http://")
                _is_https = False

        proto = 'https' if _is_https else 'http'
        url = f"{proto}://{ip}:{port}"

        outputfile = os.path.join(screenshots_dir, f"{getTimestamp()}-{ip}-{port}")
        # Qt6: screenshooter-timeout is in ms; eyewitness --delay takes seconds
        try:
            delay_s = max(1, int(getattr(self.settings, 'general_screenshooter_timeout', '15000')) // 1000)
        except (ValueError, TypeError):
            delay_s = 15
        cmd = (f"xvfb-run -a {eyewitness} --single {url} --no-prompt --web --delay {delay_s}"
               f" -d {outputfile}-dir")

        log.info(f"[WebController] Screenshot: {url}")
        self.runCommand(command=cmd, name='screenshooter',
                        tabTitle=f'screenshooter ({port}/tcp)',
                        hostIp=ip, port=str(port), protocol='tcp',
                        outputfile=outputfile, run_actions=False)
        return True

    def saveRunningProcessOutputs(self):
        """controller.py:2305 — flush active process output to DB before save/shutdown.
        Reads the .live_output temp file for each still-running non-interactive process,
        and reads the PTY buffer for interactive processes, then writes to SQLite
        (preserve_status=True so status stays 'Running'/'Interactive')."""
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        saved = 0
        for proc in list(self._active_processes.values()):
            try:
                if proc._popen and proc._popen.poll() is None:
                    live_path = getattr(proc, '_live_output_path', None)
                    content = ''
                    if live_path and os.path.isfile(live_path):
                        # Non-interactive: read .live_output temp file
                        try:
                            with open(live_path, 'r', encoding='ISO-8859-1', errors='replace') as f:
                                content = f.read()
                        except Exception as read_err:
                            log.warning(f"[WebController] Could not read live output for {proc.id}: {read_err}")
                    elif getattr(proc, 'isInteractive', False):
                        # Interactive PTY: read accumulated buffer from _TerminalSession._buf
                        try:
                            from app.web.routes import _terminal_sessions, _terminal_process_sessions
                            sid = _terminal_process_sessions.get(int(proc.id))
                            if sid:
                                session = _terminal_sessions.get(sid)
                                if session:
                                    content = bytes(session._buf).decode('ISO-8859-1', errors='replace')
                        except Exception as _ie:
                            log.warning(f"[WebController] Could not read PTY buffer for {proc.id}: {_ie}")
                    if content:
                        processRepo.storeProcessOutput(proc.id, content, preserve_status=True)
                        log.info(f"[WebController] Flushed {len(content)} bytes for process {proc.id}")
                    else:
                        log.info(f"[WebController] No output to flush for process {proc.id}")
                    saved += 1
            except Exception as e:
                log.error(f"[WebController] saveRunningProcessOutputs error: {e}")
        if saved:
            log.info(f"[WebController] Flushed output for {saved} running processes")
        self.saveMatchState()
        self.saveCheckedState()

    def saveCheckedState(self):
        """Persist _checked_process_ids set to process_checked table."""
        ids = getattr(self, '_checked_process_ids', set())
        try:
            from sqlalchemy import text as _t
            db = self.logic.activeProject.database
            session = db.session()
            try:
                session.execute(_t("DELETE FROM process_checked"))
                for pid in ids:
                    session.execute(_t(
                        "INSERT OR IGNORE INTO process_checked (processId) VALUES (:pid)"
                    ), {'pid': str(pid)})
                session.commit()
            finally:
                session.close()
        except Exception as e:
            log.error(f"[WebController] saveCheckedState error: {e}")

    def loadCheckedState(self):
        """Restore _checked_process_ids set from process_checked table."""
        self._checked_process_ids = set()
        try:
            from sqlalchemy import text as _t
            db = self.logic.activeProject.database
            session = db.session()
            try:
                rows = session.execute(
                    _t("SELECT processId FROM process_checked")
                ).fetchall()
                self._checked_process_ids = {str(r[0]) for r in rows}
                if rows:
                    log.info(f"[WebController] Loaded {len(rows)} checked process IDs from DB")
            finally:
                session.close()
        except Exception as e:
            log.debug(f"[WebController] loadCheckedState (no saved state or old DB): {e}")

    def saveMatchState(self):
        """Persist _matches dict to process_matches table so it survives save/open."""
        if not hasattr(self, '_matches'):
            return
        try:
            from sqlalchemy import text as _t
            db = self.logic.activeProject.database
            session = db.session()
            try:
                session.execute(_t("DELETE FROM process_matches"))
                for key, match_set in self._matches.items():
                    parts = key.split(':', 1)
                    hostIp = parts[0]
                    tabTitle = parts[1] if len(parts) > 1 else ''
                    for matchStr in match_set:
                        session.execute(_t(
                            "INSERT INTO process_matches (hostIp, tabTitle, matchStr) "
                            "VALUES (:h, :t, :m)"
                        ), {'h': hostIp, 't': tabTitle, 'm': str(matchStr)})
                session.commit()
                total = sum(len(v) for v in self._matches.values())
                log.info(f"[WebController] Saved {total} match entries to DB")
            finally:
                session.close()
        except Exception as e:
            log.error(f"[WebController] saveMatchState error: {e}")

    def loadMatchState(self):
        """Restore _matches dict from process_matches table after project open."""
        self._matches = {}
        try:
            from sqlalchemy import text as _t
            db = self.logic.activeProject.database
            session = db.session()
            try:
                rows = session.execute(
                    _t("SELECT hostIp, tabTitle, matchStr FROM process_matches")
                ).fetchall()
                for row in rows:
                    hostIp, tabTitle, matchStr = str(row[0]), str(row[1]), str(row[2])
                    key = f"{hostIp}:{tabTitle}"
                    if key not in self._matches:
                        self._matches[key] = set()
                    self._matches[key].add(matchStr)
                if rows:
                    log.info(f"[WebController] Loaded {len(rows)} match entries from DB")
            finally:
                session.close()
        except Exception as e:
            log.debug(f"[WebController] loadMatchState (no saved matches or old DB): {e}")

    def killRunningProcesses(self):
        """controller.py:1700 — kill all active subprocesses.
        Also marks each process as Killed in DB (so _wait_and_import threads
        know not to import their XML) and drains fastProcessQueue (so queued-but-
        not-yet-started processes don't auto-restart via checkProcessQueue)."""
        import queue as _queue
        processRepo = self.logic.activeProject.repositoryContainer.processRepository

        # Set shutdown flag FIRST so scheduler() and _wait_and_import threads
        # see it immediately and skip launching new tools.  Without this, a
        # _wait_and_import thread whose nmap finished naturally (exit=0, not killed)
        # will call scheduler() AFTER the queue drain, adding gobuster/nuclei/etc.
        # that then start via checkProcessQueue() and survive exit.
        self._shutting_down = True

        # Brief settle: give in-flight scheduler() calls time to check the flag
        # before we sweep descendants (avoids a tiny window where a process is
        # started by checkProcessQueue between flag-set and the kill sweep).
        time.sleep(0.15)

        # Sweep ALL descendants FIRST — while grandchildren (real nmap/gobuster binary
        # launched via shell=True) are still children of their parent shells and
        # therefore still in Legion's process tree.  If we kill the shells first,
        # Linux re-parents those grandchildren to PID 1 before the sweep runs,
        # making them invisible to the BFS and leaving them as orphans.
        _kill_all_descendants()

        # Now kill the shells themselves and mark them Killed in DB
        for proc_id, proc in list(self._active_processes.items()):
            try:
                if proc._popen and proc._popen.poll() is None:
                    os.kill(proc._popen.pid, signal.SIGTERM)
                    time.sleep(0.1)
                    if proc._popen.poll() is None:
                        os.kill(proc._popen.pid, signal.SIGKILL)
                    log.info(f"[WebController] Killed process {proc_id}")
            except (ProcessLookupError, OSError):
                pass
            except Exception as e:
                log.error(f"[WebController] killRunningProcesses error: {e}")
            # Mark Killed in DB so _wait_and_import threads see isKilledProcess()=True
            # and skip importing incomplete/partial XML.
            try:
                processRepo.storeProcessKillStatus(str(proc_id))
            except Exception as e:
                log.error(f"[WebController] killRunningProcesses: failed to store kill status for {proc_id}: {e}")

        self._active_processes.clear()
        self.processes.clear()
        self.fastProcessesRunning = 0
        self.slowProcessesRunning = 0

        # Drain the queue: queued-but-not-yet-started processes must not auto-restart.
        # Without this, _capture_output threads from just-killed processes call
        # checkProcessQueue() on finish, which starts the queued processes — ghost scans.
        drained = 0
        while True:
            try:
                proc = self.fastProcessQueue.get_nowait()
                proc_id = getattr(proc, 'id', None)
                if proc_id:
                    try:
                        processRepo.storeProcessKillStatus(str(proc_id))
                    except Exception:
                        pass
                drained += 1
            except _queue.Empty:
                break
        if drained:
            log.info(f"[WebController] Drained {drained} queued process(es) from fastProcessQueue")

        # Second sweep: catch any processes that slipped through between the first
        # sweep and the queue drain (scheduler() calls that beat the _shutting_down flag).
        time.sleep(0.1)
        _kill_all_descendants()

    def handleMatch(self, hostIp, tabTitle, matchStr):
        """controller.py:2651 — store match data without Qt view calls."""
        log.info(f"[WebController] Match: {hostIp} / {tabTitle} / {matchStr}")
        # Store in a match dict that the browser can poll
        if not hasattr(self, '_matches'):
            self._matches = {}
        key = f"{hostIp}:{tabTitle}"
        if key not in self._matches:
            self._matches[key] = set()
        # Use set to deduplicate — same pattern from 50 lines shouldn't show 50 times
        self._matches[key].add(str(matchStr))

    def handleHydraFindings(self, bWidget=None, userlist=None, passlist=None):
        """controller.py:2336 — store credentials without Qt view calls."""
        try:
            for username in (userlist or []):
                self.logic.activeProject.properties.usernamesWordList.add(username)
            for password in (passlist or []):
                self.logic.activeProject.properties.passwordWordList.add(password)
        except Exception as e:
            log.error(f"[WebController] handleHydraFindings error: {e}")

    def markAsInteractive(self, proc_id):
        """controller.py:1958 — mark process as interactive using threading.Timer."""
        try:
            processRepo = self.logic.activeProject.repositoryContainer.processRepository
            processRepo.storeProcessInteractiveStatus(str(proc_id))
            proc = self._active_processes.get(int(proc_id))
            if proc:
                proc.isInteractive = True
            log.info(f"[WebController] Marked process {proc_id} as interactive")
        except Exception as e:
            log.error(f"[WebController] markAsInteractive error: {e}")

    def scheduler(self, parser=None, isNmapImport=False):
        """controller.py:2344 — run automated attacks after nmap import.
        Reads SchedulerSettings from legion.conf and runs configured tools
        against discovered hosts/ports."""
        # Serialise concurrent scheduler() calls from parallel _wait_and_import threads.
        # Without this lock, 5 PORTS stages finishing simultaneously all pass the
        # already_ran check before any of them commits their runCommand() row →
        # duplicate feroxbuster/gobuster/nuclei processes for the same port.
        self._scheduler_lock.acquire()
        try:
            # Exit/shutdown in progress — do not start any new tools.
            # _wait_and_import threads whose nmap finished naturally (exit=0)
            # before killRunningProcesses() ran will still reach here; this
            # guard ensures they don't spawn gobuster/nuclei/etc. after exit.
            if getattr(self, '_shutting_down', False):
                log.debug('[WebController] Scheduler suppressed — shutdown in progress')
                return
            if isNmapImport and str(getattr(self.settings, 'general_enable_scheduler_on_import', 'False')) == 'False':
                log.info('[WebController] Scheduler on import disabled')
                return
            if str(getattr(self.settings, 'general_enable_scheduler', 'True')) != 'True':
                log.info('[WebController] Scheduler disabled')
                return

            log.info('[WebController] Scheduler started — running automated attacks')

            from app.auxiliary import Filters
            from app.timing import getTimestamp
            from sqlalchemy import text as _text
            filters = Filters()
            repo = self.logic.activeProject.repositoryContainer

            # Force a fresh read: expire any cached session state so we see
            # data just committed by NmapImporter in the same thread
            try:
                self.logic.activeProject.database.session.remove()
            except Exception:
                pass

            hosts = repo.hostRepository.getHosts(filters)
            log.info(f'[Scheduler] hosts visible: {len(hosts or [])}')
            runningFolder = self.logic.activeProject.properties.outputFolder

            # For each host, check each port against SchedulerSettings.
            # Use getPortsAndServicesByHostIP (SQL JOIN → plain dicts, no ORM detachment).
            for host in (hosts or []):
                hip = host.get('ipv4', '') or host.get('ip', '') if isinstance(host, dict) else getattr(host, 'ipv4', '') or getattr(host, 'ip', '')
                if not hip:
                    continue

                # Fresh session per host: runCommand() calls for the previous host
                # dirty the thread-local scoped_session, causing subsequent
                # getPortsAndServicesByHostIP() calls to see a stale snapshot
                # (0 ports) even after NmapImporter committed new rows.
                try:
                    self.logic.activeProject.database.session.remove()
                except Exception:
                    pass
                port_rows = repo.portRepository.getPortsAndServicesByHostIP(hip, filters)
                log.info(f'[Scheduler] {hip}: {len(port_rows or [])} open ports')
                for port_row in (port_rows or []):
                    port_num = str(port_row.get('portId', '') or '')
                    protocol = str(port_row.get('protocol', 'tcp') or 'tcp').lower()
                    state = str(port_row.get('state', '') or '')
                    if state not in ('open', 'open|filtered'):
                        continue

                    svc_name = str(port_row.get('name', '') or '').rstrip('?').lower()
                    log.info(f'[Scheduler] checking {hip}:{port_num}/{protocol} svc={svc_name!r}')

                    # Check each SchedulerSettings entry
                    for auto in (self.settings.automatedAttacks or []):
                        try:
                            tool_id = str(auto[0]).strip()
                            svc_scope_raw = str(auto[1]).strip()
                            tool_protocol = str(auto[2] if len(auto) > 2 else 'tcp').strip().lower()

                            if tool_protocol != protocol:
                                continue

                            svc_scope = [s.strip() for s in svc_scope_raw.split(',') if s.strip()]
                            if svc_name not in svc_scope and '*' not in svc_scope:
                                continue

                            # Screenshooter is a built-in special tool — not a portAction.
                            # Handled BEFORE checkDuplicate so layer-2 (NSE scripts exist)
                            # does not block it: the vulners stage stores scripts for every
                            # open port, which would permanently suppress screenshooter via
                            # the script-count check. The in-memory _screenshots_taken set
                            # is the dedup guard; layer-1 (process table) is sufficient too.
                            if tool_id == 'screenshooter':
                                if not hasattr(self, '_screenshots_taken'):
                                    self._screenshots_taken = set()
                                scr_key = f"{hip}:{port_num}"
                                if scr_key in self._screenshots_taken:
                                    log.debug(f'[Scheduler] Screenshot already in progress: {scr_key}')
                                    continue
                                # Layer-1 only: has a screenshooter process already finished?
                                dup_scr = self.checkDuplicate('screenshooter', hip, str(port_num), protocol, user_triggered=True)
                                if dup_scr == 'skip':
                                    log.debug(f'[Scheduler] Screenshot already done for {scr_key}')
                                    continue
                                self._screenshots_taken.add(scr_key)
                                if not self._run_screenshot(hip, port_num, svc_name=svc_name):
                                    # Pre-flight failed (port unreachable, eyewitness missing,
                                    # etc.) — remove from set so it can be retried on the
                                    # next scheduler call instead of being permanently locked.
                                    self._screenshots_taken.discard(scr_key)
                                continue

                            # Duplicate check — use checkDuplicate() which reads
                            # tool-duplication from settings and checks both
                            # in-progress (Waiting/Running) AND completed (Finished)
                            # processes so that tool-duplication=skip prevents tools
                            # from firing twice when multiple nmap stages complete
                            # (e.g., stage 2 triggers enum4linux-ng, then vulners
                            # stage 6 fires the scheduler again and would re-run it).
                            dup_result = self.checkDuplicate(tool_id, hip, str(port_num), protocol)
                            if dup_result == 'skip':
                                log.debug(f'[Scheduler] Skipping {tool_id} on {hip}:{port_num} — tool-duplication=skip')
                                continue
                            # newTab / append — run regardless (creates a new process entry)
                            # askMe — scheduler runs automatically, treat as skip to avoid UI prompts
                            if dup_result == 'askMe':
                                log.debug(f'[Scheduler] Skipping {tool_id} on {hip}:{port_num} — askMe treated as skip in scheduler')
                                continue

                            # Find command from portActions
                            command_template = ''
                            for action in (self.settings.portActions or []):
                                if str(action[1]).strip() == tool_id:
                                    command_template = str(action[2]) if len(action) > 2 else ''
                                    break

                            if not command_template:
                                log.debug(f'[Scheduler] No command template for {tool_id}')
                                continue

                            outputfile = os.path.join(runningFolder, f"{getTimestamp()}-{tool_id}-{hip}-{port_num}")
                            command = command_template.replace('[IP]', hip).replace('[PORT]', port_num).replace('[OUTPUT]', outputfile)
                            if 'nmap' in command and protocol == 'udp':
                                command = command.replace('-sV', '-sVU')

                            log.info(f'[Scheduler] Running {tool_id} on {hip}:{port_num}')
                            self.runCommand(command=command, name=tool_id,
                                            tabTitle=f'{tool_id} ({port_num}/{protocol})',
                                            hostIp=hip, port=port_num, protocol=protocol,
                                            outputfile=outputfile, run_actions=False)
                        except Exception as e:
                            log.error(f'[Scheduler] Error processing {auto}: {e}')

        except Exception as e:
            log.error(f"[WebController] scheduler error: {e}")
        finally:
            self._scheduler_lock.release()

    def checkProcessQueue(self):
        """controller.py:1570 — dequeue and start processes respecting concurrency limits.
        Qt6 used QProcess.state() to check running. We use _popen.poll() instead."""
        if not hasattr(self, 'fastProcessQueue') or self.fastProcessQueue.empty():
            return

        try:
            max_fast  = int(getattr(self.settings, 'general_max_fast_processes', 5))
            # Qt6: max-slow-processes controls concurrent nmap scans
            # was wrongly reading non-existent 'general_max_concurrent_scans'
            max_scans = int(getattr(self.settings, 'general_max_slow_processes', 3))
        except Exception:
            max_fast, max_scans = 5, 3

        # Use the atomic slowProcessesRunning counter rather than counting from
        # _active_processes.  The list comprehension has a race condition: two threads
        # calling checkProcessQueue() simultaneously both see the same count and both
        # start a process, exceeding max_scans.  The atomic counter is updated inside
        # this method before the lock is released so the next call sees the correct value.
        running_all = [p for p in self._active_processes.values()
                       if p._popen and p._popen.poll() is None
                       and not getattr(p, 'isInteractive', False)]
        running_scans_count = self.slowProcessesRunning   # atomic integer, no race

        log.debug(f"[Queue] running={len(running_all)}/{max_fast} scans={running_scans_count}/{max_scans} queued={self.fastProcessQueue.qsize()}")

        # Start processes while under limits (controller.py:1590-1591)
        while not self.fastProcessQueue.empty():
            if len(running_all) >= max_fast:
                break
            if running_scans_count >= max_scans and not self.fastProcessQueue.empty():
                # Peek: if next is a scan, stop
                try:
                    next_item = self.fastProcessQueue.queue[0]
                    if 'nmap' in str(getattr(next_item, 'name', '')).lower():
                        break
                except Exception:
                    pass

            try:
                proc = self.fastProcessQueue.get_nowait()
            except Exception:
                break

            proc_id = getattr(proc, 'id', None)

            # Skip cancelled processes
            try:
                if proc_id and self.logic.activeProject.repositoryContainer.processRepository.isCancelledProcess(str(proc_id)):
                    log.debug(f"[Queue] Process {proc_id} was cancelled, skipping")
                    continue
            except Exception:
                pass

            # Start the process
            command = getattr(proc, 'command', '')
            if not command:
                continue

            try:
                popen = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                proc.pid = popen.pid
                proc._popen = popen
                proc._start_mono = time.monotonic()  # for elapsed time calculation
                proc._start_wall = time.time()        # wall-clock start for snapshot elapsed
                # Global uptime: start clock on first non-interactive process;
                # reset if a new batch starts after everything previously finished.
                if not getattr(proc, 'isInteractive', False):
                    if (not hasattr(self, '_scan_uptime_start')
                            or self._scan_uptime_start is None
                            or getattr(self, '_scan_uptime_end', None) is not None):
                        self._scan_uptime_start = proc._start_wall
                        self._scan_uptime_end = None
                processRepo = self.logic.activeProject.repositoryContainer.processRepository
                processRepo.storeProcessRunningStatus(str(proc_id), str(popen.pid))
                self._active_processes[int(proc_id)] = proc
                self.fastProcessesRunning += 1
                if 'nmap' in str(proc.name).lower():
                    self.slowProcessesRunning += 1   # atomic — prevents race in next checkProcessQueue call
                    running_scans_count += 1
                running_all.append(proc)

                t = threading.Thread(target=self._capture_output, args=(proc, processRepo),
                                      daemon=True, name=f"capture-{proc_id}")
                t.start()
                log.debug(f"[Queue] Started {proc.name} pid={popen.pid}")
            except Exception as e:
                log.error(f"[Queue] Failed to start {getattr(proc, 'name', '?')}: {e}")

    # ──────────────────────────────────────────────────────────────
    # Tier 2a: getContextMenuForHost → JSON
    # Qt6 ref: controller.py:559-586
    # Qt6 returns: (QMenu, [QAction, ...])
    # Web returns: list of dicts with keys: label, action, submenu, separator
    # ──────────────────────────────────────────────────────────────
    def getContextMenuForHost(self, isChecked='False', showAll=True):
        """
        Build host right-click menu as JSON data.
        Maps 1:1 to controller.py:getContextMenuForHost.
        """
        items = []
        portscan_submenu = []

        # controller.py:564-568 — iterate hostActions from settings
        for a in self.settings.hostActions:
            label = a[0]
            command = a[1]
            if "nmap" in command or "unicornscan" in command:
                portscan_submenu.append({
                    'label': label,
                    'action': 'host-action',
                    'action_index': self.settings.hostActions.index(a),
                    'command': command,
                })
            else:
                items.append({
                    'label': label,
                    'action': 'host-action',
                    'action_index': self.settings.hostActions.index(a),
                    'command': command,
                })

        if showAll:
            # controller.py:571 — Run nmap (staged)
            portscan_submenu.append({
                'label': 'Run nmap (staged)',
                'action': 'nmap-staged',
            })

            # controller.py:573 — add Portscan submenu
            items.append({
                'label': 'Portscan',
                'submenu': portscan_submenu,
            })
            items.append({'separator': True})

            # controller.py:576-579 — check/uncheck toggle
            if isChecked == 'True':
                items.append({'label': 'Mark as unchecked', 'action': 'mark-unchecked'})
            else:
                items.append({'label': 'Mark as checked', 'action': 'mark-checked'})

            # controller.py:581-584
            items.append({'label': 'Open Terminal', 'action': 'open-terminal'})
            items.append({'label': 'Rescan', 'action': 'rescan'})
            items.append({'label': 'Purge Results', 'action': 'purge'})
            items.append({'label': 'Delete', 'action': 'delete'})

        return items

    # ──────────────────────────────────────────────────────────────
    # Tier 2b: getContextMenuForServiceName → JSON
    # Qt6 ref: controller.py:1058-1080
    # Qt6 returns: (QMenu, [(index, QAction), ...], shiftPressed)
    # Web returns: list of dicts
    # ──────────────────────────────────────────────────────────────
    def getContextMenuForServiceName(self, serviceName='*'):
        """
        Build service-name right-click menu as JSON data.
        Maps 1:1 to controller.py:getContextMenuForServiceName.
        """
        items = []

        # controller.py:1062-1064 — web services get browser/screenshot options
        web_services = self.settings.general_web_services.split(",")
        if serviceName == '*' or serviceName in web_services:
            items.append({'label': 'Open in browser', 'action': 'open-browser'})
            items.append({'label': 'Take screenshot', 'action': 'take-screenshot'})

        # controller.py:1067-1071 — port actions matching this service
        for i, a in enumerate(self.settings.portActions):
            service_scope = a[3] if len(a) > 3 else ''
            if (serviceName is None or serviceName == '*'
                    or serviceName in service_scope.split(",")
                    or service_scope == ''):
                items.append({
                    'label': a[0],
                    'action': 'port-action',
                    'action_index': i,
                    'tool_id': a[1],
                    'command': a[2] if len(a) > 2 else '',
                })

        return items

    # ──────────────────────────────────────────────────────────────
    # Tier 2c: getContextMenuForPort → JSON
    # Qt6 ref: controller.py:1143-1168
    # Qt6 returns: (QMenu, [(index, QAction)], [(index, QAction)])
    # Web returns: dict with terminal_actions and port_actions
    # ──────────────────────────────────────────────────────────────
    def getContextMenuForPort(self, serviceName='*'):
        """
        Build port right-click menu as JSON data.
        Maps 1:1 to controller.py:getContextMenuForPort.
        """
        terminal_actions = []
        for i, a in enumerate(self.settings.portTerminalActions):
            service_scope = a[3] if len(a) > 3 else ''
            if (serviceName is None or serviceName == '*'
                    or serviceName in service_scope.split(",")
                    or service_scope == ''):
                terminal_actions.append({
                    'label': a[0],
                    'action': 'terminal-action',
                    'action_index': i,
                    'command': a[2] if len(a) > 2 else '',
                })

        # controller.py:1158-1160 — fixed actions
        fixed = [
            {'separator': True},
            {'label': 'Send to Brute', 'action': 'send-to-brute'},
            {'label': 'Take screenshot', 'action': 'take-screenshot'},
            {'separator': True},
        ]

        # controller.py:1162 — get service name actions
        port_actions = self.getContextMenuForServiceName(serviceName)

        # controller.py:1164
        suffix = [
            {'separator': True},
            {'label': 'Run custom command', 'action': 'run-custom'},
        ]

        return {
            'terminal_actions': terminal_actions,
            'fixed_actions': fixed,
            'port_actions': port_actions,
            'suffix_actions': suffix,
        }

    # ──────────────────────────────────────────────────────────────
    # Tier 2d: getContextMenuForProcess → JSON
    # Qt6 ref: controller.py:1242-1247
    # Qt6 returns: QMenu
    # Web returns: list of dicts
    # ──────────────────────────────────────────────────────────────
    def getContextMenuForProcess(self):
        """
        Build process right-click menu as JSON data.
        Maps 1:1 to controller.py:getContextMenuForProcess.
        """
        return [
            {'label': 'Kill',      'action': 'kill'},
            {'label': 'Retry',     'action': 'retry'},
            {'label': 'Clear',     'action': 'clear'},
            {'label': 'Go to Tab', 'action': 'goto-tab'},
        ]

    # ──────────────────────────────────────────────────────────────
    # Passthrough methods — these call your logic directly, no Qt
    # ──────────────────────────────────────────────────────────────

    def getHostsFromDB(self, filters):
        """controller.py:1376"""
        return self.logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)

    def getServiceNamesFromDB(self, filters):
        """controller.py:1379"""
        return self.logic.activeProject.repositoryContainer.serviceRepository.getServiceNames(filters)

    def getHostsAndPortsForServiceFromDB(self, serviceName, filters):
        """controller.py:1400"""
        return self.logic.activeProject.repositoryContainer.hostRepository.getHostsAndPortsByServiceName(
            serviceName, filters)

    def getPortsAndServicesForHostFromDB(self, hostIP, filters):
        """controller.py:1397"""
        return self.logic.activeProject.repositoryContainer.portRepository.getPortsAndServicesByHostIP(
            hostIP, filters)

    def getHostInformation(self, hostIP):
        """controller.py:1404"""
        return self.logic.activeProject.repositoryContainer.hostRepository.getHostInformation(hostIP)

    def getScriptsFromDB(self, hostIP):
        """controller.py:1410"""
        return self.logic.activeProject.repositoryContainer.scriptRepository.getScriptsByHostIP(hostIP)

    def getCvesFromDB(self, hostIP):
        """controller.py:1413"""
        return self.logic.activeProject.repositoryContainer.cveRepository.getCVEsByHostIP(hostIP)

    def getNoteFromDB(self, hostid):
        """controller.py:1419"""
        return self.logic.activeProject.repositoryContainer.noteRepository.getNoteByHostId(hostid)

    def getScriptOutputFromDB(self, scriptDBId):
        """controller.py:1416"""
        return self.logic.activeProject.repositoryContainer.scriptRepository.getScriptOutputById(scriptDBId)

    def getHostsForOperatingSystem(self, os_name):
        """controller.py:1565"""
        return self.logic.activeProject.repositoryContainer.hostRepository.getHostsByOperatingSystem(os_name)

    def getPortStatesForHost(self, hostid):
        """controller.py:1407"""
        return self.logic.activeProject.repositoryContainer.portRepository.getPortStatesByHostId(hostid)

    def getHostsForTool(self, toolName, closed='False'):
        """controller.py:1422"""
        return self.logic.activeProject.repositoryContainer.processRepository.getHostsByToolName(
            toolName, closed)

    # ──────────────────────────────────────────────────────────────
    # Tier 3: runCommand — QProcess → subprocess.Popen
    # Qt6 ref: controller.py:1775-2003
    # Qt6 uses: MyQProcess(QProcess) → QProcess.start(command)
    # Web uses: WebProcessStub + subprocess.Popen
    # ──────────────────────────────────────────────────────────────
    def runCommand(self, command, name='process', tabTitle=None, hostIp='', port='',
                   protocol='tcp', startTime=None, outputfile='', run_actions=True,
                   _is_staged=False, force_interactive=False, _bypass_queue=False):
        """
        Run a system command, store it in the DB, capture output in a background thread.
        Returns dict with process_id, pid, and optionally session_id.

        Maps to controller.py:runCommand but uses subprocess instead of QProcess.

        Interactive detection (controller.py:1921):
        If the command contains 'bash' or 'msfconsole', it is started as a PTY
        terminal session instead of a plain Popen. This lets the user interact
        with msfconsole prompts, SSH sessions, etc. via xterm.js.
        """
        from app.timing import getTimestamp

        if not tabTitle:
            tabTitle = name
        if not startTime:
            startTime = getTimestamp(True)
        if not outputfile:
            runningFolder = self.logic.activeProject.properties.runningFolder
            outputfile = os.path.join(runningFolder, f"{getTimestamp()}-{name}-{hostIp}-{port}")

        log.info(f"[WebController] runCommand: {command}")
        log.info(f"  name={name}, host={hostIp}, port={port}")

        # controller.py:1921 — detect interactive commands
        is_interactive = ('bash' in str(command).lower() or 'msfconsole' in str(command).lower())
        if force_interactive:
            is_interactive = True

        if is_interactive:
            log.info(f"[WebController] Interactive command detected — starting PTY terminal session")
            return self._startInteractiveProcess(
                command=command, name=name, tabTitle=tabTitle, hostIp=hostIp,
                port=port, protocol=protocol, startTime=startTime, outputfile=outputfile,
                force_interactive=force_interactive,
            )

        # ── Non-interactive path (unchanged) ──

        # Create process stub (replaces MyQProcess)
        proc = WebProcessStub(name, tabTitle, hostIp, port, protocol, command, startTime, outputfile)

        # Store in DB (same call as controller.py:1881)
        # Note: createNewProject/openExistingProject/saveProjectAs all call
        # _release_outgoing_session() before switching, so the scoped_session
        # registry is always pointing at the CURRENT project's engine here.
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        dbId = str(processRepo.storeProcess(proc))
        proc.id = int(dbId)
        log.info(f"[WebController] Stored process in DB, id={dbId}")

        # Create tool folder (same as controller.py:1856)
        try:
            self.logic.createFolderForTool(name)
        except Exception:
            pass

        proc._run_actions = run_actions
        proc._is_staged = _is_staged
        if not hasattr(self, '_active_processes'):
            self._active_processes = {}

        if _bypass_queue:
            # Start immediately without entering the queue — used for the NSE/vulners
            # stage so it launches as soon as all PORTS stages complete rather than
            # waiting behind scheduler-triggered tools (feroxbuster, nikto, etc.)
            # that may have filled the concurrency slots.
            try:
                popen = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                proc.pid = popen.pid
                proc._popen = popen
                proc._start_mono = time.monotonic()
                proc._start_wall = time.time()
                # Update global uptime clock
                if not getattr(proc, 'isInteractive', False):
                    if (not hasattr(self, '_scan_uptime_start')
                            or self._scan_uptime_start is None
                            or getattr(self, '_scan_uptime_end', None) is not None):
                        self._scan_uptime_start = proc._start_wall
                        self._scan_uptime_end = None
                processRepo.storeProcessRunningStatus(str(dbId), str(popen.pid))
                self._active_processes[int(dbId)] = proc
                self.fastProcessesRunning += 1
                t = threading.Thread(target=self._capture_output, args=(proc, processRepo),
                                     daemon=True, name=f"capture-{dbId}")
                t.start()
                log.info(f"[WebController] NSE/bypass-queue started pid={popen.pid}: {command[:80]}")
            except Exception as e:
                log.error(f"[WebController] bypass-queue start failed for {name}: {e}")
        else:
            # Add to queue then let checkProcessQueue decide when to start
            self.fastProcessQueue.put(proc)
            self.checkProcessQueue()

        return {'process_id': int(dbId), 'pid': proc.pid}

    def _startInteractiveProcess(self, command, name, tabTitle, hostIp, port,
                                  protocol, startTime, outputfile, force_interactive=False):
        """Start a PTY terminal session for an interactive command (bash/msfconsole).

        Creates a _TerminalSession via the /api/terminal/start route logic,
        and applies the Qt6 interactive rules:
        - msfconsole with 'run -j': mark as Interactive after 10s (controller.py:1956-1969)
        - force_interactive: mark immediately (controller.py:1973-1977)
        - All interactive processes are excluded from process queue counting
        """
        import uuid
        from app.web.routes import _terminal_sessions, _terminal_process_sessions, _TerminalSession

        session_id = str(uuid.uuid4())
        session = _TerminalSession(session_id, command=command)
        _terminal_sessions[session_id] = session

        # Create the DB process row
        proc = WebProcessStub(name, tabTitle, hostIp, port, protocol, command, startTime, outputfile)
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        dbId = str(processRepo.storeProcess(proc))
        proc.id = int(dbId)
        proc.isInteractive = True

        # controller.py:1956-1969 — msfconsole with 'run -j': delay 10s then mark Interactive
        # controller.py:1973-1977 — force_interactive: mark immediately
        if force_interactive:
            processRepo.storeProcessInteractiveStatus(dbId)
            log.info(f"[WebController] Force-marked process {dbId} as Interactive (retry)")
        elif 'msfconsole' in str(command).lower() and 'run -j' in str(command).lower():
            # Wait 10 seconds for exploit to start, then mark as Interactive
            def _delayed_mark():
                try:
                    processRepo.storeProcessInteractiveStatus(dbId)
                    log.info(f"[WebController] Marked msfconsole process {dbId} as Interactive after 10s delay")
                except Exception as e:
                    log.error(f"[WebController] delayed markAsInteractive error: {e}")
            import threading
            threading.Timer(10.0, _delayed_mark).start()
            # Store as Running initially (will become Interactive after 10s)
            processRepo.storeProcessRunningStatus(dbId, str(session.proc.pid))
            log.info(f"[WebController] msfconsole process {dbId} starts as Running, will be Interactive in 10s")
        else:
            processRepo.storeProcessInteractiveStatus(dbId)
            log.info(f"[WebController] Marked process {dbId} as Interactive")

        # Track in active processes (excluded from queue counting via isInteractive flag)
        proc._popen = session.proc  # so killProcess can terminate it
        self._active_processes[int(dbId)] = proc

        # Map process_id → session_id for snapshot
        _terminal_process_sessions[int(dbId)] = session_id

        log.info(f"[WebController] Interactive session {session_id[:8]} process_id={dbId} label={name}")

        return {'process_id': int(dbId), 'pid': session.proc.pid, 'session_id': session_id}

    def _capture_output(self, proc, processRepo):
        """
        Background thread: reads subprocess stdout, stores output in DB.
        Replaces QProcess.readyReadStandardOutput signal + handleOutputAndScroll.
        """
        dbId = str(proc.id)
        output_parts = []
        start_time = time.monotonic()

        # Write live output to a temp file during capture to avoid SQLite writes
        # entirely during long-running processes (NSE|vulners 2-3 min).
        # Previous approach: periodic SQLite writes grew to megabytes, causing
        # potential lock contention and GIL pressure that froze the UI.
        # New approach: append to temp file (OS-level, near-zero overhead),
        # read temp file directly from the output API, write to SQLite only on finish.
        live_output_path = getattr(proc, 'outputfile', '') + '.live_output'
        live_file = None
        try:
            live_file = open(live_output_path, 'w', encoding='ISO-8859-1', errors='replace', buffering=1)
            # Store the path so the API can read it
            proc._live_output_path = live_output_path
        except Exception:
            live_file = None
            live_output_path = None

        try:
            toolName = getattr(proc, 'name', '')
            hostIp = getattr(proc, 'hostIp', '')
            tabTitle = getattr(proc, 'tabTitle', '')
            all_matches = set()
            line_count = 0
            last_line_time = time.monotonic()

            import threading as _thr
            log.info(f"[Capture:{dbId}] STARTED reading output for {toolName} ({tabTitle}) thread={_thr.current_thread().name}")

            # ── Process timeout watchdog ──────────────────────────────────────────
            # Kill any non-nmap process that runs longer than process-timeout seconds.
            # nmap is excluded because staged scans can legitimately run for hours.
            # Tools with slow startup (nuclei downloads templates, eyewitness spins up
            # a browser, gobuster with large wordlists) get 3× the base timeout so
            # they are not killed before they finish their initialisation phase.
            # Set process-timeout = 0 in legion.conf to disable entirely.
            _timeout_secs = int(getattr(self.settings, 'general_process_timeout', '300') or '300')
            _is_nmap = 'nmap' in str(toolName).lower()
            # Tools that legitimately run long — give them extra breathing room
            _timed_out = _thr.Event()

            if _timeout_secs > 0 and not _is_nmap:
                def _timeout_watchdog():
                    time.sleep(_timeout_secs)
                    if proc._popen and proc._popen.poll() is None:
                        _timed_out.set()
                        log.warning(f"[Capture:{dbId}] {toolName} exceeded {_timeout_secs}s timeout — killing")
                        try:
                            processRepo.storeProcessKillStatus(dbId)
                        except Exception:
                            pass
                        try:
                            _kill_subtree(proc._popen.pid)
                        except Exception:
                            pass
                        try:
                            proc._popen.kill()
                        except Exception:
                            pass
                _tw = _thr.Thread(target=_timeout_watchdog, daemon=True,
                                  name=f"timeout-{dbId}-{toolName}")
                _tw.start()

            for line in iter(proc._popen.stdout.readline, b''):
                now = time.monotonic()
                gap = now - last_line_time
                last_line_time = now
                text = line.decode('ISO-8859-1', errors='replace')
                output_parts.append(text)
                line_count += 1

                # Log every 100 lines or if readline blocked for >10s
                if line_count % 100 == 0 or gap > 10:
                    log.info(f"[Capture:{dbId}] line={line_count} gap={gap:.1f}s total_chars={sum(len(p) for p in output_parts)}")

                # Write to temp file immediately — line-buffered (buffering=1) so
                # every line is flushed to disk instantly for the API to read.
                # Previous bug: default 8KB buffer meant 44 lines of nmap output
                # stayed in memory, API read empty file, user saw no output.
                if live_file:
                    try:
                        live_file.write(text)
                    except Exception:
                        pass

                # P1: Match detection on every line (auxiliary.py:285-331)
                # Strip ANSI escape codes before matching — tools like nuclei wrap
                # severity in ANSI color ([\x1b[31mhigh\x1b[0m]) which breaks the
                # plain substring match for patterns like [high].
                try:
                    import re as _re
                    _clean = _re.sub(r'\x1b\[[0-9;]*m', '', text)
                    line_matches = self.detectMatches(_clean, toolName)
                    if line_matches:
                        all_matches.update(line_matches)
                        self.handleMatch(hostIp, tabTitle, ', '.join(line_matches))
                except Exception:
                    pass

                # P2: nmap real-time progress (--stats-every 5s output)
                # Lines look like: "SYN Scan Timing: About 42.93% done; ETC: 15:22 (0:01:23 remaining)"
                if 'nmap' in str(toolName).lower() and '% done' in text:
                    try:
                        import re as _re
                        m = _re.search(r'About ([\d.]+)% done(?:.*?ETC: ([\d:]+))?', text)
                        if m:
                            pct = m.group(1)
                            etc = m.group(2) or ''
                            pct_str = f"{pct}%" + (f" ETC:{etc}" if etc else "")
                            processRepo.storeProcessPercent(dbId, pct_str)
                    except Exception:
                        pass

            # Append timeout notice to output if the watchdog killed this process
            if _timed_out.is_set():
                _tmsg = f'\n\n[Legion] Process killed: exceeded {_timeout_secs}s timeout\n'
                output_parts.append(_tmsg)
                if live_file:
                    try:
                        live_file.write(_tmsg)
                    except Exception:
                        pass

            # Process finished — close temp file and write final output to SQLite once
            if live_file:
                try:
                    live_file.flush()
                    live_file.close()
                    live_file = None
                except Exception:
                    pass

            proc._popen.wait()
            finish_mono = time.monotonic()
            log.info(f"[Capture:{dbId}] FINISHED reading. lines={line_count} writing {sum(len(p) for p in output_parts)} bytes to SQLite...")
            _write_t0 = time.monotonic()
            combined = ''.join(output_parts)
            # If the timeout watchdog (or an explicit kill) already set status=Killed
            # in its own thread/session, storeProcessOutput must NOT overwrite it to
            # Finished.  storeProcessOutput reads proc.status from the current thread's
            # SQLAlchemy session identity-map cache which may still show 'Running'
            # (the watchdog committed in a different session).  Use isKilledProcess()
            # which opens a fresh session, sees the committed value, and returns the
            # definitive answer.  preserve_status=True skips the status→Finished write.
            # If the host was deleted while this process was running, skip all
            # DB writes — the process row is already gone and _deleted_hosts guards
            # against re-creating it via processFinished / nmap import below.
            _host_deleted = hostIp in getattr(self, '_deleted_hosts', set())
            if _host_deleted:
                log.info(f"[Capture:{dbId}] Host {hostIp} deleted — skipping DB write")
            else:
                _already_killed = processRepo.isKilledProcess(str(dbId))
                processRepo.storeProcessOutput(dbId, combined,
                                               preserve_status=_already_killed)
            log.info(f"[Capture:{dbId}] SQLite write done in {int((time.monotonic()-_write_t0)*1000)}ms")

            # Store elapsed time in seconds (controller.py:handleProcStop)
            if not _host_deleted and hasattr(proc, '_start_mono'):
                elapsed_secs = finish_mono - proc._start_mono
                processRepo.storeProcessRunningElapsedTime(dbId, round(elapsed_secs, 1))

            exit_code = proc._popen.returncode
            log.info(f"[WebController] Process {dbId} finished, exit={exit_code}, output={len(combined)} bytes")

            if _host_deleted:
                # Host was deleted — skip all post-process work to avoid re-creating data
                pass
            else:
                # Hydra credential extraction (auxiliary.py:178-195 + controller.py:2285)
                if 'hydra' in str(toolName).lower():
                    try:
                        from app.auxiliary import checkHydraResults
                        found, userlist, passlist = checkHydraResults(combined)
                        if found:
                            self.handleHydraFindings(userlist=userlist, passlist=passlist)
                            log.info(f"[WebController] Hydra found {len(userlist)} users, {len(passlist)} passwords")
                    except Exception as e:
                        log.error(f"[WebController] Hydra extraction error: {e}")

                # Call processFinished chain for non-nmap tools
                if not processRepo.isKilledProcess(str(dbId)):
                    try:
                        self.processFinished(proc)
                    except Exception:
                        pass

            # Import nmap XML if this was an nmap process (controller.py:2240-2260)
            # This is the CRITICAL step that adds hosts/ports/services to the DB
            # Skip for staged nmap — runStagedNmap() handles its own chained imports
            outputfile = getattr(proc, 'outputfile', '')
            is_staged = getattr(proc, '_is_staged', False)
            if not _host_deleted and 'nmap' in str(toolName).lower() and outputfile and exit_code == 0 and not is_staged:
                xml_path = outputfile + '.xml'
                if not os.path.isfile(xml_path):
                    # Try without extension
                    xml_path = outputfile if outputfile.endswith('.xml') else None
                if xml_path and os.path.isfile(xml_path):
                    try:
                        from app.importers.nmap_import import import_nmap_xml
                        import_nmap_xml(
                            project=self.logic.activeProject,
                            xml_path=xml_path,
                            output=combined,
                        )
                        log.info(f"[WebController] Nmap XML imported: {xml_path}")
                        # Qt6: copyNmapXMLToOutputFolder — archive XML in project output dir
                        try:
                            import shutil as _shutil
                            dest_name = os.path.basename(xml_path)
                            dest = os.path.join(
                                self.logic.activeProject.properties.outputFolder, dest_name)
                            if xml_path != dest:
                                _shutil.copy2(xml_path, dest)
                                log.info(f"[WebController] Nmap XML archived to {dest}")
                        except Exception as _e:
                            log.warning(f"[WebController] copyNmapXMLToOutputFolder: {_e}")
                        # Run automated attacks after import (scheduler)
                        # isNmapImport=False because this is a live nmap run (has output),
                        # matching Qt6: NmapImporter.schedule.emit(parser, self.output == '')
                        # isNmapImport=True is only for XML-only file imports with no terminal output
                        run_actions = getattr(proc, '_run_actions', True)
                        if run_actions:
                            self.scheduler(isNmapImport=False)
                        # Write deferred scan note — host is now in DB after import
                        _deferred = self._pending_scan_notes.pop(hostIp, None)
                        if _deferred:
                            try:
                                self._append_to_host_notes(hostIp, _deferred)
                            except Exception as _nn:
                                log.warning(f"[WebController] Could not write deferred scan note for {hostIp}: {_nn}")
                    except Exception as e:
                        log.error(f"[WebController] Nmap XML import failed: {e}")
                else:
                    log.warning(f"[WebController] Nmap XML not found: {outputfile}.xml")

            # Clean up temp live output file (output now safely in SQLite)
            if live_output_path and os.path.isfile(live_output_path):
                try:
                    os.unlink(live_output_path)
                except Exception:
                    pass

            # Clean up tracking
            if hasattr(self, '_active_processes') and int(dbId) in self._active_processes:
                del self._active_processes[int(dbId)]
            self.fastProcessesRunning = max(0, self.fastProcessesRunning - 1)
            if 'nmap' in str(toolName).lower():
                self.slowProcessesRunning = max(0, self.slowProcessesRunning - 1)

            # Stop the global uptime clock when the last non-interactive process finishes
            if not getattr(proc, 'isInteractive', False):
                still_running = [
                    p for p in self._active_processes.values()
                    if p._popen and p._popen.poll() is None
                    and not getattr(p, 'isInteractive', False)
                ]
                if not still_running and getattr(self, '_scan_uptime_start', None) is not None:
                    self._scan_uptime_end = time.time()

            # Check queue — a slot just freed up, start next process if any waiting
            try:
                self.checkProcessQueue()
            except Exception:
                pass

        except Exception as e:
            log.error(f"[WebController] _capture_output error for {dbId}: {e}")
            if live_file:
                try: live_file.close()
                except Exception: pass
            try:
                processRepo.storeProcessOutput(dbId, ''.join(output_parts) + f"\n[capture error: {e}]")
            except Exception:
                pass  # DB may already be disposed (e.g. File→Exit during capture)

    def killProcess(self, process_id):
        """Kill a running process by DB id. Replaces controller.py:killProcess.
        Also cleans up any associated PTY terminal session (Interactive processes)."""
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        proc = self._active_processes.get(int(process_id)) if hasattr(self, '_active_processes') else None

        if proc and proc._popen and proc._popen.poll() is None:
            shell_pid = proc._popen.pid
            # Mark Killed in DB BEFORE sending the signal so _capture_output's
            # isKilledProcess() call (which fires immediately on EOF) sees the
            # committed status and uses preserve_status=True.  Without this,
            # _capture_output can race ahead and write 'Finished' over 'Killed'.
            processRepo.storeProcessKillStatus(str(process_id))
            # Kill grandchildren FIRST — while they are still children of the shell
            # and therefore visible to the /proc BFS.  If we kill the shell first,
            # Linux re-parents its children to PID 1 before _kill_subtree runs,
            # making them invisible and leaving nmap/gobuster running as orphans.
            _kill_subtree(shell_pid)
            try:
                os.kill(shell_pid, signal.SIGTERM)
                time.sleep(0.1)
                if proc._popen.poll() is None:
                    os.kill(shell_pid, signal.SIGKILL)
                log.info(f"[WebController] Killed process {process_id} (pid {shell_pid})")
            except ProcessLookupError:
                pass
            except Exception as e:
                log.error(f"[WebController] Error killing process: {e}")

        # Clean up terminal session if this was an Interactive process
        try:
            from app.web.routes import _terminal_sessions, _terminal_process_sessions
            session_id = _terminal_process_sessions.pop(int(process_id), None)
            if session_id:
                session = _terminal_sessions.pop(session_id, None)
                if session:
                    session.close()
                    log.info(f"[WebController] Cleaned up terminal session {session_id[:8]} for process {process_id}")
        except Exception as e:
            log.error(f"[WebController] Error cleaning up terminal session: {e}")

        processRepo.storeProcessKillStatus(str(process_id))

        # Immediately check the queue — a slot has freed up.
        # checkProcessQueue() uses p._popen.poll() is None to count running
        # processes, so the now-dead process is not counted as a running slot.
        # Without this call, the queue only advances when _capture_output's
        # readline() finally unblocks (which required the tool to finish naturally).
        try:
            self.checkProcessQueue()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # GROUP B: Process execution methods
    # Qt6 ref: controller.py lines noted per method
    # QProcess → subprocess, self.view.createNewTabForHost → no-op
    # ──────────────────────────────────────────────────────────────

    def addHosts(self, targetHosts, runHostDiscovery=True, runStagedNmap=False,
                 nmapSpeed='4', scanMode='Easy', nmapOptions=None, enableIPv6=False):
        """controller.py:443 — build nmap command and run it."""
        from app.timing import getTimestamp

        if not targetHosts or str(targetHosts).strip() == '':
            log.info('[WebController] addHosts: no targets')
            return

        target = str(targetHosts).strip()
        tool_output_dir = self.logic.activeProject.properties.outputFolder
        outputfile = os.path.join(tool_output_dir, f"{getTimestamp()}-nmap-scan")

        nmap_bin = getattr(self.settings, 'tools_path_nmap', '').strip() or 'nmap'

        def _store_scan_note(label, cmd):
            """Store a dated scan note in _pending_scan_notes[target].
            Written to the host's Notes tab after the XML import guarantees the
            host exists in the DB — see _capture_output nmap-import block."""
            try:
                from datetime import datetime as _dt
                _ts = _dt.now().strftime('%Y-%m-%d %H:%M')
                _cmd_clean = cmd.replace(f' -oA {outputfile}', '')
                self._pending_scan_notes[target] = f'=== Scan {_ts} ===\n  {label}: {_cmd_clean}'
            except Exception as _ne:
                log.warning(f"[WebController] Could not prepare scan note: {_ne}")

        if scanMode == 'Easy':
            if runStagedNmap:
                return self.runStagedNmap(target, discovery=runHostDiscovery, enable_ipv6=enableIPv6)
            elif runHostDiscovery:
                command = f"{nmap_bin} -sV -O --version-light -T{nmapSpeed} {target} --stats-every 5s -oA {outputfile}"
                _store_scan_note('Easy (discovery)', command)
                return self.runCommand(command=command, name='nmap', tabTitle='nmap (discovery)',
                                       hostIp=target, outputfile=outputfile)
            else:
                command = f"{nmap_bin} -sL -T{nmapSpeed} {target} --stats-every 5s -oA {outputfile}"
                _store_scan_note('Easy (list)', command)
                return self.runCommand(command=command, name='nmap', tabTitle='nmap (list)',
                                       hostIp=target, outputfile=outputfile)
        elif scanMode == 'Hard':
            opts = ' '.join(nmapOptions or [])
            command = f"{nmap_bin} {opts} -T{nmapSpeed} {target} --stats-every 5s -oA {outputfile}"
            _store_scan_note('Hard (custom)', command)
            return self.runCommand(command=command, name='nmap', tabTitle=f'nmap (custom {opts})',
                                   hostIp=target, outputfile=outputfile)

    def handleHostAction(self, ip, hostid, action_name):
        """controller.py:589 — dispatch host right-click action by name (not QAction)."""
        import queue as queue_module
        from app.timing import getTimestamp
        repositoryContainer = self.logic.activeProject.repositoryContainer

        if action_name in ('mark-checked', 'mark-unchecked'):
            repositoryContainer.hostRepository.toggleHostCheckStatus(ip)
            return {'action': action_name, 'ip': ip}

        if action_name == 'nmap-staged':
            self.runStagedNmap(ip, discovery=False)
            return {'action': 'nmap-staged', 'ip': ip}

        if action_name == 'rescan':
            # Clear all duplicate-blocking data before rescanning so checkDuplicate
            # does not skip any scheduler tools or screenshooter on the new scan.
            # Rescan = purge scan data (keep host + notes) + start new staged nmap.

            # 1. Drain queue first
            if hasattr(self, 'fastProcessQueue'):
                temp = queue_module.Queue()
                while not self.fastProcessQueue.empty():
                    try:
                        p = self.fastProcessQueue.get_nowait()
                        if getattr(p, 'hostIp', '') != ip:
                            temp.put(p)
                    except Exception:
                        break
                while not temp.empty():
                    self.fastProcessQueue.put(temp.get_nowait())

            # 2. Kill and evict active processes for this host
            for proc_id, proc in list(self._active_processes.items()):
                if getattr(proc, 'hostIp', '') == ip:
                    self.killProcess(proc_id)
                    self._active_processes.pop(proc_id, None)

            # 3. Clear _screenshots_taken so screenshooter re-runs on new ports
            if hasattr(self, '_screenshots_taken'):
                self._screenshots_taken = {
                    k for k in self._screenshots_taken
                    if not k.startswith(f"{ip}:")
                }

            # 4. Delete old scan data — keep hostObj and note rows
            try:
                from sqlalchemy import text
                session = repositoryContainer.hostRepository.dbAdapter.session()
                try:
                    session.execute(text(
                        "DELETE FROM process_matches WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM process_output WHERE id IN "
                        "(SELECT id FROM process WHERE hostIp = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM process WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM l1ScriptObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM cve WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM portObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.commit()
                finally:
                    session.close()
                log.info(f"[WebController] Rescan: cleared old scan data for {ip}")
            except Exception as e:
                log.error(f"[WebController] Rescan pre-clear error: {e}")

            # 5. Start fresh staged nmap
            self.runStagedNmap(ip, discovery=False)
            return {'action': 'rescan', 'ip': ip}

        if action_name == 'delete':
            # _deleted_hosts added AFTER successful DB transaction — if the delete
            # fails the host must not be permanently blacklisted.
            pass

            # 1. Drain the queue FIRST so killProcess()'s internal checkProcessQueue()
            #    call cannot start a newly-queued process for this host.
            if hasattr(self, 'fastProcessQueue'):
                temp = queue_module.Queue()
                while not self.fastProcessQueue.empty():
                    try:
                        p = self.fastProcessQueue.get_nowait()
                        if getattr(p, 'hostIp', '') != ip:
                            temp.put(p)
                    except Exception:
                        break
                while not temp.empty():
                    self.fastProcessQueue.put(temp.get_nowait())

            # 2. Kill running/interactive processes and evict from _active_processes
            #    immediately so the snapshot never shows them again.
            for proc_id, proc in list(self._active_processes.items()):
                if getattr(proc, 'hostIp', '') == ip:
                    self.killProcess(proc_id)
                    # Evict now; _capture_output will skip its own del gracefully
                    self._active_processes.pop(proc_id, None)

            # 3. Delete all process and host data from DB in one transaction.
            #    process_matches is keyed by hostIp (not process_id).
            try:
                from sqlalchemy import text
                session = repositoryContainer.hostRepository.dbAdapter.session()
                try:
                    session.execute(text(
                        "DELETE FROM process_matches WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM process_output WHERE id IN "
                        "(SELECT id FROM process WHERE hostIp = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM process WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM l1ScriptObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM cve WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM portObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM note WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM osObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM hostObj WHERE ip = :ip"), {"ip": ip})
                    session.commit()
                finally:
                    session.close()
                # Add to screenshooter blacklist only after successful delete
                self._deleted_hosts.add(ip)
                log.info(f"[WebController] Deleted host {ip} and all related data")
            except Exception as e:
                log.error(f"[WebController] Delete host error: {e}")
            return {'action': 'delete', 'ip': ip}

        if action_name == 'purge':
            # Purge: delete scan data but keep host row + notes (ready for rescan).
            # Apply same robustness fixes as delete (v10.154).

            # 1. Drain queue first — killProcess() calls checkProcessQueue() internally
            if hasattr(self, 'fastProcessQueue'):
                temp = queue_module.Queue()
                while not self.fastProcessQueue.empty():
                    try:
                        p = self.fastProcessQueue.get_nowait()
                        if getattr(p, 'hostIp', '') != ip:
                            temp.put(p)
                    except Exception:
                        break
                while not temp.empty():
                    self.fastProcessQueue.put(temp.get_nowait())

            # 2. Kill and immediately evict from _active_processes
            for proc_id, proc in list(self._active_processes.items()):
                if getattr(proc, 'hostIp', '') == ip:
                    self.killProcess(proc_id)
                    self._active_processes.pop(proc_id, None)

            # 3. Delete scan data — keep hostObj and note rows
            try:
                from sqlalchemy import text
                session = repositoryContainer.hostRepository.dbAdapter.session()
                try:
                    session.execute(text(
                        "DELETE FROM process_matches WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM process_output WHERE id IN "
                        "(SELECT id FROM process WHERE hostIp = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM process WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM l1ScriptObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM cve WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text(
                        "DELETE FROM portObj WHERE hostId = "
                        "(SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    # Keep hostObj + note rows
                    session.commit()
                finally:
                    session.close()
                log.info(f"[WebController] Purged scan data for {ip} (host+notes preserved)")
            except Exception as e:
                log.error(f"[WebController] Purge error: {e}")
            return {'action': 'purge', 'ip': ip}

        # Host action from settings.hostActions — run the tool
        if action_name == 'host-action':
            # This is handled via handleHostToolAction with an index
            pass

        return {'action': action_name, 'ip': ip}

    def handleHostToolAction(self, ip, action_index):
        """Run a host action from settings.hostActions by index.
        For nmap commands that lack -oA, appends -oA [outputfile] so
        _capture_output can import the XML and populate the Services table.
        For python-script-* actions, routes to the actual Python script file
        instead of echoing a stub (Qt6: PythonImporter)."""
        from app.timing import getTimestamp
        if action_index < 0 or action_index >= len(self.settings.hostActions):
            return None
        action = self.settings.hostActions[action_index]
        name = action[1]  # tool command name
        command = action[2] if len(action) > 2 else action[1]
        command = str(command).replace('[IP]', ip)
        runningFolder = self.logic.activeProject.properties.runningFolder
        outputfile = os.path.join(runningFolder, f"{getTimestamp()}-{name}-{ip}")
        command = command.replace('[OUTPUT]', outputfile)

        # Qt6: checkDuplicate before running user-triggered host actions.
        # Only 'skip' actually blocks the run. Qt6's other modes ('newTab',
        # 'append', 'askMe') all resulted in the tool running — via a new tab,
        # appended output, or a user-confirmation dialog respectively.
        # Flask has no Qt dialog, so 'askMe' falls through to run (user's
        # explicit right-click is intent enough). 'newTab' and 'append' both
        # run — Flask's process model treats every run as a new process anyway.
        dup_mode = self.checkDuplicate(name, ip, '')
        if dup_mode == 'skip':
            log.info(f"[WebController] handleHostToolAction: duplicate {name} on {ip} — mode=skip, not running")
            return {'skipped': True, 'reason': 'skip', 'tool': name, 'ip': ip}

        # Detect python-script-* host actions and route to real Python scripts
        # Qt6: PythonImporter.run() ran scripts/python/<name>.py with dbHost + session
        # Flask: run the script as a subprocess so it appears in the process table
        # The conf key (name/action[1]) carries the python-script- prefix; the
        # command field (action[2]) may contain a legacy echo placeholder — check
        # the key first so routing works even with old conf entries.
        first_word = command.strip().split()[0] if command.strip() else ''
        _py_prefix = 'python-script-'
        if first_word.startswith(_py_prefix):
            script_slug = first_word[len(_py_prefix):]
        elif name.startswith(_py_prefix):
            script_slug = name[len(_py_prefix):]
        else:
            script_slug = None
        if script_slug is not None:
            # re-assign first_word so the nmap check below works correctly
            first_word = f'python-script-{script_slug}'
            _scripts_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'scripts', 'python'
            )
            script_path = os.path.join(_scripts_dir, f'{script_slug}.py')
            if not os.path.isfile(script_path):
                # Conf key casing may not match file name (e.g. PyShodan→pyShodan.py).
                # Walk the directory for a case-insensitive match.
                _slug_lc = script_slug.lower()
                for _fn in os.listdir(_scripts_dir):
                    if _fn.lower() == f'{_slug_lc}.py':
                        script_path = os.path.join(_scripts_dir, _fn)
                        script_slug = _fn[:-3]   # strip .py, preserve actual casing
                        break
            if os.path.isfile(script_path):
                if script_slug == 'macvendors':
                    # macvendors.py takes MAC address — look up from host record
                    arg = ip  # fallback to IP if no MAC recorded
                    try:
                        h = self.logic.activeProject.repositoryContainer.hostRepository.getHostInformation(ip)
                        mac = ''
                        if h:
                            mac = (h.get('macaddr') if isinstance(h, dict)
                                   else getattr(h, 'macaddr', '')) or ''
                        if mac.strip():
                            arg = mac.strip()
                    except Exception:
                        pass
                else:
                    arg = ip
                command = f'python3 {script_path} {arg}'
                if script_slug == 'pyShodan':
                    api_key = getattr(self.settings, 'tools_pyshodan_api_key', '').strip()
                    if api_key:
                        import shlex
                        command = f"SHODAN_API_KEY={shlex.quote(api_key)} {command}"
                log.info(f"[WebController] python-script-{script_slug} → {command}")
            else:
                log.warning(f"[WebController] python-script-{script_slug}: script not found at {script_path}")

        # If nmap and no -oA flag, append it so results get imported into DB
        if 'nmap' in command.lower() and '-oA' not in command:
            command = command + f' -oA {outputfile}'
            log.info(f"[WebController] Added -oA {outputfile} to nmap host action")
        return self.runCommand(command=command, name=name, tabTitle=f'{action[0]}',
                               hostIp=ip, outputfile=outputfile)

    def handleServiceNameAction(self, targets, action_index=0):
        """controller.py:1083 — run a tool from portActions against targets."""
        from app.timing import getTimestamp
        if action_index < 0 or action_index >= len(self.settings.portActions):
            return None
        action = self.settings.portActions[action_index]
        tool = action[1]
        results = []
        for target in targets:
            ip, port, protocol = target[0], target[1], target[2] if len(target) > 2 else 'tcp'
            # Qt6: checkDuplicate before running user-triggered port actions.
            # Only block on 'skip' — all other modes run the tool:
            #   'newTab'  → Qt6 created "tool (80/tcp) [2]"; Flask runs a new process (same effect)
            #   'append'  → Qt6 appended output to existing tab; Flask runs a new process
            #   'askMe'   → Qt6 showed a dialog; Flask has no dialog so we run (user intent is clear)
            dup_mode = self.checkDuplicate(tool, ip, port, protocol, user_triggered=True)
            if dup_mode == 'skip':
                log.info(f"[WebController] handleServiceNameAction: duplicate {tool} on {ip}:{port} — mode=skip, not running")
                results.append({'skipped': True, 'reason': 'skip', 'tool': tool, 'ip': ip, 'port': port})
                continue
            command = str(action[2])
            runningFolder = self.logic.activeProject.properties.runningFolder
            outputfile = os.path.join(runningFolder, f"{getTimestamp()}-{tool}-{ip}-{port}")
            command = command.replace('[IP]', ip).replace('[PORT]', port).replace('[OUTPUT]', outputfile)
            if 'nmap' in command and protocol == 'udp':
                command = command.replace("-sV", "-sVU")
            tabTitle = f"{tool} ({port}/{protocol})"
            result = self.runCommand(command=command, name=tool, tabTitle=tabTitle,
                                     hostIp=ip, port=port, protocol=protocol, outputfile=outputfile)
            results.append(result)
        return results

    def handlePortAction(self, targets, action_type='port-action', action_index=0):
        """controller.py:1171 — run tool from portActions or terminalActions."""
        if action_type == 'terminal-action':
            if action_index < 0 or action_index >= len(self.settings.portTerminalActions):
                return None
            action = self.settings.portTerminalActions[action_index]
        else:
            if action_index < 0 or action_index >= len(self.settings.portActions):
                return None
            action = self.settings.portActions[action_index]
        return self.handleServiceNameAction(targets, action_index)

    def handleProcessAction(self, process_id, action_name):
        """controller.py:1250 — kill/retry/clear a process by DB id."""
        processRepo = self.logic.activeProject.repositoryContainer.processRepository

        if action_name == 'kill':
            self.killProcess(process_id)
            return {'action': 'kill', 'process_id': process_id}

        if action_name == 'clear':
            processRepo.hideProcesses([process_id])
            log.info(f"[WebController] Cleared process {process_id}")
            return {'action': 'clear', 'process_id': process_id}

        if action_name == 'retry':
            proc_data = processRepo.getProcessById(process_id)
            if not proc_data or not proc_data.get('command'):
                log.warning(f"[WebController] Cannot retry process {process_id}: no command")
                return None
            # Kill if still running (controller.py:1279 — handles Running, Waiting, Interactive)
            original_status = proc_data.get('status', '')
            if process_id in self._active_processes:
                self.killProcess(process_id)
                time.sleep(0.5)
            # controller.py:1351-1353 — if original was Interactive, force retry to be Interactive too
            force_interactive = (original_status == 'Interactive')
            if force_interactive:
                log.info(f"[WebController] Retry of Interactive process {process_id} — will force_interactive")
            # Re-run the same command
            result = self.runCommand(
                command=proc_data['command'],
                name=proc_data.get('name', 'process'),
                tabTitle=proc_data.get('tabTitle', ''),
                hostIp=proc_data.get('hostIp', ''),
                port=proc_data.get('port', ''),
                protocol=proc_data.get('protocol', 'tcp'),
                outputfile=proc_data.get('outputfile', ''),
                force_interactive=force_interactive,
            )
            return {'action': 'retry', 'old_id': process_id, 'new_result': result}

        return None

    def runStagedNmap(self, targetHosts, discovery=True, stage=1, stop=False, enable_ipv6=False):
        """Flask-only parallel staged nmap (Qt6 controller.py is unchanged).

        All PORTS stages run simultaneously; the NSE stage runs last against
        every open TCP port discovered by all PORTS stages combined.
        The stage/stop params are kept for API compatibility but stage is always 1
        from external callers; the parallel launcher handles sequencing internally.
        """
        # A new scan means we are NOT shutting down.  killRunningProcesses() sets
        # _shutting_down=True but never resets it — without this line every
        # subsequent scheduler() call after a kill is silently suppressed, causing
        # automated tools (feroxbuster, nuclei, etc.) to never launch.
        self._shutting_down = False

        host_arg = str(targetHosts).strip()
        if not host_arg or stop:
            return

        log.info(f"[WebController] runStagedNmap starting parallel scan for {host_arg}")
        tool_output_dir = self.logic.activeProject.properties.outputFolder
        nmap_bin = getattr(self.settings, 'tools_path_nmap', '').strip() or 'nmap'

        # Seed host(s) into the DB immediately so they appear in the UI hosts table
        # before any nmap stage finishes importing its XML.  Without this, the hosts
        # table stays empty for 5–30 minutes when discovery=False, making the UI
        # appear broken (clicking hosts / processes has no visible effect).
        try:
            repo = self.logic.activeProject.repositoryContainer
            for _ip in [ip.strip() for ip in str(host_arg).split(',') if ip.strip()]:
                if not repo.hostRepository.getHostByIP(_ip):
                    _seed_xml = (
                        '<?xml version="1.0"?><nmaprun>'
                        f'<host><status state="up"/>'
                        f'<address addr="{_ip}" addrtype="ipv4"/>'
                        f'</host></nmaprun>'
                    )
                    import tempfile as _tf, os as _os2
                    with _tf.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as _f:
                        _f.write(_seed_xml); _seed_path = _f.name
                    try:
                        from app.importers.nmap_import import import_nmap_xml
                        import_nmap_xml(project=self.logic.activeProject,
                                        xml_path=_seed_path, output='')
                        log.debug(f"[WebController] Seeded host {_ip} into DB for immediate UI visibility")
                    finally:
                        try: _os2.unlink(_seed_path)
                        except Exception: pass
        except Exception as _se:
            log.debug(f"[WebController] Host pre-seed skipped: {_se}")

        # Classify all configured stages into PORTS (parallel) and NSE (serial, last)
        ports_stages = []   # [(stage_num, stageOpValues), ...]
        nse_stage = None    # (stage_num, stageOpValues)
        for s in range(1, 7):
            data = getattr(self.settings, f'tools_nmap_stage{s}_ports', '')
            if not data:
                continue
            parts = str(data).split('|', maxsplit=1)
            op = parts[0].strip()
            values = parts[1] if len(parts) > 1 else ''
            if op in ('', 'NOOP', 'SKIP'):
                continue
            if op == 'NSE':
                nse_stage = (s, values)
            elif op == 'PORTS':
                ports_stages.append((s, values))

        if not ports_stages and not nse_stage:
            log.info(f"[WebController] No stage data configured for {host_arg}")
            return

        # Record scan commands in host notes so they can be reproduced later.
        # Build each PORTS command using the same logic as _launch_ports_stage
        # but without the timestamped -oA path (user would supply their own).
        try:
            from datetime import datetime as _dt
            _ts = _dt.now().strftime('%Y-%m-%d %H:%M')
            _lines = [f'=== Scan {_ts} ===']
            for (_s, _vals) in ports_stages:
                _tok = [nmap_bin]
                if enable_ipv6:
                    _tok.append('-6')
                if discovery:
                    _tok.extend(['-T4', '-sV', '-sSU', '-O'])
                else:
                    _tok.extend(['-Pn', '-sS', '-O'])
                _pv = _vals.strip()
                if _pv:
                    _tok.extend(['-p', _pv])
                _tok.extend(['-vvvv', host_arg, '--stats-every', '5s'])
                _lines.append(f'  S{_s} (PORTS): ' + ' '.join(t for t in _tok if t))
            if nse_stage:
                _ns, _nv = nse_stage
                _ntok = [nmap_bin]
                if enable_ipv6:
                    _ntok.append('-6')
                _ntok.extend(['-Pn', '-sV', f'--script={_nv.strip()}', '-vvvv',
                               '--min-parallelism', '20', '--max-parallelism', '50',
                               '--script-timeout', '60s',
                               host_arg, '--stats-every', '5s'])
                _lines.append(f'  S{_ns} (NSE template, -p from discovered): '
                               + ' '.join(t for t in _ntok if t))
            _note_text = '\n'.join(_lines)
            # On a first-time scan the host doesn't exist in the DB yet — writing
            # immediately would silently skip.  Check first; if any target host is
            # absent, defer the write to the first _stage_completed callback where
            # the XML import guarantees the host is present.  On re-scans every
            # host is already in the DB so we write immediately as before.
            try:
                _ips = [ip.strip() for ip in str(host_arg).split(',') if ip.strip()]
                _repo = self.logic.activeProject.repositoryContainer
                _all_in_db = all(_repo.hostRepository.getHostByIP(ip) for ip in _ips)
            except Exception:
                _all_in_db = False
            if _all_in_db:
                self._append_to_host_notes(host_arg, _note_text)
            else:
                self._pending_scan_notes[host_arg] = _note_text
        except Exception as _ne:
            log.warning(f"[WebController] Could not record scan commands in notes: {_ne}")

        if ports_stages:
            # Bump generation BEFORE registering pending stages so any still-running
            # _wait_and_import threads from a previous scan on the same host see a
            # mismatched generation and bail out without touching the new scan's state.
            with self._pending_stages_lock:
                gen = self._scan_generation.get(host_arg, 0) + 1
                self._scan_generation[host_arg] = gen
                self._pending_ports_stages[host_arg] = {s for s, _ in ports_stages}
            for (s, values) in ports_stages:
                self._launch_ports_stage(host_arg, s, values, discovery, enable_ipv6,
                                         tool_output_dir, nmap_bin, nse_stage, gen)
        elif nse_stage:
            # No PORTS stages configured — run NSE immediately
            with self._pending_stages_lock:
                gen = self._scan_generation.get(host_arg, 0) + 1
                self._scan_generation[host_arg] = gen
            self._launch_nse_stage(host_arg, nse_stage[0], nse_stage[1],
                                   enable_ipv6, tool_output_dir, nmap_bin, gen)

    def _launch_ports_stage(self, host_arg, stage, stageOpValues, discovery, enable_ipv6,
                             tool_output_dir, nmap_bin, nse_stage, generation=0):
        """Launch one PORTS stage and monitor it in a background thread.
        Calls _stage_completed when done (whether success, empty XML, or error).
        generation: snapshot of _scan_generation[host_arg] at launch time; if the
        generation has been bumped by a newer scan, the thread silently exits."""
        from app.timing import getTimestamp
        outputfile = os.path.join(tool_output_dir, f"{getTimestamp()}-nmapstage{stage}")

        tokens = [nmap_bin]
        if enable_ipv6:
            tokens.append('-6')
        if discovery:
            tokens.extend(['-T4', '-sV', '-sSU', '-O'])
        else:
            tokens.extend(['-Pn', '-sS', '-O'])
        port_values = stageOpValues.strip()
        if port_values:
            tokens.extend(['-p', port_values])
        # Rate-limit each stage so concurrent scans don't saturate the network.
        # Without this, stages 4+5 (29k/35k ports) drop probes and self-throttle,
        # causing slow scans.  2000 pps × 5 concurrent = 10k pps total — safe for
        # a gigabit LAN.  --min-rate prevents nmap from backing off unnecessarily.
        tokens.extend(['--min-rate', '500', '--max-rate', '2000'])
        tokens.extend(['-vvvv', host_arg, '--stats-every', '5s', '-oA', outputfile])

        command = ' '.join(t for t in tokens if t)
        log.info(f"[WebController] Stage {stage} command: {command}")

        result = self.runCommand(command=command, name='nmap', tabTitle=f'nmap (stage {stage})',
                                 hostIp=host_arg, outputfile=outputfile, _is_staged=True)

        if not result or not result.get('process_id'):
            log.warning(f"[WebController] Stage {stage} failed to launch for {host_arg}")
            self._stage_completed(host_arg, stage, nse_stage, enable_ipv6, tool_output_dir, nmap_bin, generation)
            return

        proc_id = result['process_id']

        def _wait_and_import():
            log.info(f"[Chain{stage}] Waiting for process {proc_id} to start...")
            deadline = time.monotonic() + 600
            proc = None
            while time.monotonic() < deadline:
                proc = self._active_processes.get(proc_id)
                if proc and proc._popen is not None:
                    break
                time.sleep(0.5)

            # Generation check: if a newer scan for this host has started, this
            # thread is stale — do NOT touch _pending_ports_stages or launch NSE.
            with self._pending_stages_lock:
                current_gen = self._scan_generation.get(host_arg, 0)
            if current_gen != generation:
                log.info(f"[Chain{stage}] Stale generation ({generation} vs {current_gen}) for {host_arg} — exiting")
                return

            if not proc or proc._popen is None:
                log.warning(f"[Chain{stage}] Stage {stage} never started for {host_arg}")
                self._stage_completed(host_arg, stage, nse_stage, enable_ipv6, tool_output_dir, nmap_bin, generation)
                return

            log.info(f"[Chain{stage}] Process {proc_id} started (pid={proc.pid}), waiting...")
            proc._popen.wait()
            log.info(f"[Chain{stage}] Process {proc_id} finished (exit={proc._popen.returncode})")

            # Generation check again after wait — a kill + new scan may have started
            with self._pending_stages_lock:
                current_gen = self._scan_generation.get(host_arg, 0)
            if current_gen != generation:
                log.info(f"[Chain{stage}] Stale generation ({generation} vs {current_gen}) after wait for {host_arg} — exiting")
                return

            # Check if host was deleted while this stage was running
            if host_arg in getattr(self, '_deleted_hosts', set()):
                log.info(f"[Chain{stage}] Host {host_arg} deleted — skipping import")
                return

            processRepo = self.logic.activeProject.repositoryContainer.processRepository
            if processRepo.isKilledProcess(str(proc_id)):
                log.info(f"[Chain{stage}] Stage {stage} was killed")
                self._stage_completed(host_arg, stage, nse_stage, enable_ipv6, tool_output_dir, nmap_bin, generation)
                return

            xml_path = outputfile + '.xml'
            xml_exists = os.path.isfile(xml_path)
            xml_size = os.path.getsize(xml_path) if xml_exists else -1
            log.info(f"[Chain{stage}] xml={xml_path} exists={xml_exists} size={xml_size}b")

            if xml_exists and xml_size > 0:
                try:
                    from app.importers.nmap_import import import_nmap_xml
                    import_nmap_xml(project=self.logic.activeProject,
                                    xml_path=xml_path, output="")
                    log.info(f"[WebController] Stage {stage} XML imported: {xml_path}")
                    try:
                        import sqlite3 as _sq3
                        _db_path = self.logic.activeProject.database.name
                        with _sq3.connect(_db_path) as _rc:
                            _hc = _rc.execute("SELECT COUNT(*) FROM hostObj").fetchone()[0]
                            _pc = _rc.execute("SELECT COUNT(*) FROM portObj").fetchone()[0]
                            _sc = _rc.execute("SELECT COUNT(*) FROM serviceObj").fetchone()[0]
                        log.info(f"[Chain{stage}] raw-DB: {_hc} hosts, {_pc} ports, {_sc} services")
                    except Exception as _ve:
                        log.error(f"[Chain{stage}] DB verify failed: {_ve}")
                    self.scheduler(isNmapImport=False)
                except Exception as e:
                    log.error(f"[WebController] Stage {stage} import error: {e}")
            else:
                log.warning(f"[WebController] Stage {stage} XML not found: {xml_path}")

            self._stage_completed(host_arg, stage, nse_stage, enable_ipv6, tool_output_dir, nmap_bin, generation)

        t = threading.Thread(target=_wait_and_import, daemon=True,
                             name=f"stage-chain-{stage}-{host_arg}")
        t.start()

    def _stage_completed(self, host_arg, stage, nse_stage, enable_ipv6, tool_output_dir, nmap_bin, generation=0):
        """Remove a finished PORTS stage from the pending set.
        When the set empties, launch the NSE stage.
        generation: guards against stale threads from a killed scan modifying the
        pending set of a new scan that started for the same host."""
        with self._pending_stages_lock:
            current_gen = self._scan_generation.get(host_arg, 0)
            if current_gen != generation:
                log.info(f"[WebController] _stage_completed: stale gen {generation} vs {current_gen} for {host_arg} — ignoring")
                return
            pending = self._pending_ports_stages.get(host_arg, set())
            pending.discard(stage)
            self._pending_ports_stages[host_arg] = pending
            all_done = len(pending) == 0
            # Pop deferred note inside the lock so only the first completing stage
            # writes it (the other parallel stages get None and skip the write).
            _deferred_note = self._pending_scan_notes.pop(host_arg, None)
        log.info(f"[WebController] Stage {stage} done for {host_arg}, remaining={pending}")
        # Write scan commands for first-time scans — host is now in DB after import.
        if _deferred_note:
            try:
                self._append_to_host_notes(host_arg, _deferred_note)
            except Exception as _ne:
                log.warning(f"[WebController] Could not write deferred scan notes for {host_arg}: {_ne}")
        if host_arg in getattr(self, '_deleted_hosts', set()):
            log.info(f"[WebController] _stage_completed: host {host_arg} deleted — skipping NSE launch")
            return
        if all_done and nse_stage:
            nse_stage_num, nse_values = nse_stage
            self._launch_nse_stage(host_arg, nse_stage_num, nse_values,
                                   enable_ipv6, tool_output_dir, nmap_bin, generation)

    def _launch_nse_stage(self, host_arg, stage, nse_values, enable_ipv6, tool_output_dir, nmap_bin, generation=0):
        """Query all discovered open ports for host, then run NSE against them.
        Runs after all PORTS stages complete so vulners sees every discovered port.
        generation: if a new scan supersedes this one, _wait_nse exits without importing."""
        if host_arg in getattr(self, '_deleted_hosts', set()):
            log.info(f"[WebController] _launch_nse_stage: host {host_arg} deleted — skipping")
            return
        from app.timing import getTimestamp
        import sqlite3 as _sq3

        # Flush ORM session pool so any pending state is released before raw sqlite3 reads.
        try:
            self.logic.activeProject.database.session.remove()
        except Exception:
            pass

        # Expand nmap comma shorthand (e.g. '192.168.85.11,111') into individual
        # IPs for the DB lookup.  The DB stores hosts as plain IPs after XML import,
        # so 'WHERE ip = 192.168.85.11,111' finds nothing.  The nmap command itself
        # still receives the original host_arg — nmap handles the notation natively.
        def _expand_nmap_target(t):
            """Expand '192.168.85.11,111' → ['192.168.85.11','192.168.85.111'].
            Works for commas in any octet position.  Plain IPs pass through unchanged."""
            if ',' not in t:
                return [t]
            parts = t.split('.')
            expanded = ['']
            for part in parts:
                if ',' in part:
                    expanded = [
                        (prev + '.' + sv).lstrip('.')
                        for prev in expanded
                        for sv in part.split(',')
                    ]
                else:
                    expanded = [(prev + '.' + part).lstrip('.') for prev in expanded]
            return expanded

        lookup_ips = _expand_nmap_target(host_arg)
        if len(lookup_ips) > 1:
            log.info(f"[NSE] Expanded {host_arg!r} → {lookup_ips} for DB port lookup")

        # Query open ports using raw sqlite3 (bypasses ORM cache).
        # Use a subquery keyed on hostObj.id to avoid TEXT/INTEGER JOIN type mismatch
        # (portObj.hostId is Column(String) but hostObj.id is Column(Integer)).
        # state LIKE 'open%' catches both 'open' and 'open|filtered'.
        tcp_ports = []
        udp_ports = []
        try:
            _db_path = self.logic.activeProject.database.name
            with _sq3.connect(_db_path) as _rc:
                ph_ips = ','.join('?' * len(lookup_ips))
                host_rows = _rc.execute(
                    f"SELECT id FROM hostObj WHERE ip IN ({ph_ips})", lookup_ips
                ).fetchall()
                log.info(f"[NSE] DB host lookup for {lookup_ips}: {len(host_rows)} row(s) found")
                if host_rows:
                    host_ids = [str(r[0]) for r in host_rows]
                    ph = ','.join('?' * len(host_ids))
                    all_ports = _rc.execute(
                        f"SELECT portId, protocol, state FROM portObj "
                        f"WHERE hostId IN ({ph}) AND state LIKE 'open%'",
                        host_ids
                    ).fetchall()
                    log.info(f"[NSE] Found {len(all_ports)} open port(s): {all_ports[:30]}")
                    tcp_ports = [str(r[0]) for r in all_ports if r[1] == 'tcp']
                    udp_ports = [str(r[0]) for r in all_ports if r[1] == 'udp']
                else:
                    log.warning(f"[NSE] No hosts found in DB for {lookup_ips}")
        except Exception as e:
            log.error(f"[WebController] NSE port query failed: {e}")

        # Build -p argument: T:<tcp_ports>,U:<udp_ports> if both present
        port_list = ''
        if tcp_ports and udp_ports:
            port_list = f"T:{','.join(tcp_ports)},U:{','.join(udp_ports)}"
        elif tcp_ports:
            port_list = ','.join(tcp_ports)
        elif udp_ports:
            port_list = f"U:{','.join(udp_ports)}"

        if port_list:
            log.info(f"[NSE] Port spec: {port_list[:200]}")
        else:
            log.warning(f"[NSE] No open ports found — NSE will scan nmap defaults")

        outputfile = os.path.join(tool_output_dir, f"{getTimestamp()}-nmapstage{stage}")

        tokens = [nmap_bin]
        if enable_ipv6:
            tokens.append('-6')
        # -Pn: skip host discovery — the PORTS stages already confirmed the host
        # is up (they found open ports). Without -Pn, nmap re-pings the host and
        # if ICMP is blocked it marks it "down" and runs no scripts at all.
        # --min-parallelism: run multiple NSE script instances concurrently so
        # scripts like vulners (which make external HTTP calls) don't block each
        # other sequentially. --script-timeout caps any single script that hangs.
        tokens.extend(['-Pn', '-sV', f'--script={nse_values.strip()}', '-vvvv',
                       '--min-parallelism', '20', '--max-parallelism', '50',
                       '--script-timeout', '60s'])
        if port_list:
            tokens.extend(['-p', port_list])
        tokens.extend([host_arg, '--stats-every', '5s', '-oA', outputfile])

        command = ' '.join(t for t in tokens if t)
        log.info(f"[WebController] NSE command: {command}")

        # Append the actual NSE command (real -p arg now known) to host notes
        try:
            import re as _re
            _cmd_clean = _re.sub(r'\s+-oA\s+\S+', '', command)
            self._append_to_host_notes(host_arg, f'  S{stage} (NSE actual):   {_cmd_clean}')
        except Exception as _nne:
            log.warning(f"[WebController] Could not append NSE command to notes: {_nne}")

        script_name = nse_values.strip().split(',')[0]  # e.g. 'vulners'
        # _bypass_queue=True: start immediately after all PORTS stages finish.
        # Without this, scheduler-triggered tools (feroxbuster, nikto, etc.) launched
        # by stage 1-5 completions can fill the concurrency slots and delay vulners
        # by minutes — or indefinitely if max_fast_processes is low.
        #
        result = self.runCommand(command=command, name='nmap', tabTitle=f'nmap ({script_name})',
                                 hostIp=host_arg, outputfile=outputfile, _is_staged=True,
                                 _bypass_queue=True)

        if not result or not result.get('process_id'):
            with self._pending_stages_lock:
                self._pending_ports_stages.pop(host_arg, None)
            return

        proc_id = result['process_id']

        def _wait_nse():
            deadline = time.monotonic() + 1800  # NSE can be slow (vulners makes HTTP calls)
            proc = None
            while time.monotonic() < deadline:
                proc = self._active_processes.get(proc_id)
                if proc and proc._popen is not None:
                    break
                time.sleep(0.5)

            # Generation check: bail out if a new scan superseded this NSE run
            with self._pending_stages_lock:
                current_gen = self._scan_generation.get(host_arg, 0)
            if current_gen != generation:
                log.info(f"[NSE] Stale generation ({generation} vs {current_gen}) for {host_arg} — exiting")
                return

            if not proc or proc._popen is None:
                log.warning(f"[NSE] NSE stage never started for {host_arg}")
                with self._pending_stages_lock:
                    self._pending_ports_stages.pop(host_arg, None)
                return

            proc._popen.wait()
            log.info(f"[NSE] NSE finished (exit={proc._popen.returncode})")

            # Generation check again after wait
            with self._pending_stages_lock:
                current_gen = self._scan_generation.get(host_arg, 0)
            if current_gen != generation:
                log.info(f"[NSE] Stale generation ({generation} vs {current_gen}) after wait for {host_arg} — exiting")
                return

            # Check if host was deleted while NSE was running
            if host_arg in getattr(self, '_deleted_hosts', set()):
                log.info(f"[NSE] Host {host_arg} deleted — skipping import")
                return

            processRepo = self.logic.activeProject.repositoryContainer.processRepository
            if processRepo.isKilledProcess(str(proc_id)):
                with self._pending_stages_lock:
                    self._pending_ports_stages.pop(host_arg, None)
                return

            xml_path = outputfile + '.xml'
            if os.path.isfile(xml_path) and os.path.getsize(xml_path) > 0:
                try:
                    from app.importers.nmap_import import import_nmap_xml
                    import_nmap_xml(project=self.logic.activeProject,
                                    xml_path=xml_path, output="")
                    log.info(f"[WebController] NSE XML imported: {xml_path}")
                    self.scheduler(isNmapImport=False)
                except Exception as e:
                    log.error(f"[WebController] NSE import error: {e}")
            else:
                log.warning(f"[WebController] NSE XML not found: {xml_path}")

            with self._pending_stages_lock:
                self._pending_ports_stages.pop(host_arg, None)

        t = threading.Thread(target=_wait_nse, daemon=True, name=f"nse-chain-{host_arg}")
        t.start()

    def getSettings(self):
        """controller.py:253"""
        return self.settings

    def getHostActions(self):
        """controller.py:292"""
        return self.settings.hostActions

    def getPortActions(self):
        """controller.py:295"""
        return self.settings.portActions

    def getPortTerminalActions(self):
        """controller.py:298"""
        return self.settings.portTerminalActions
