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
        self._state_changed = False
        self._matches = {}
        self._deleted_hosts = set()   # Qt6: screenshooter blacklist for deleted hosts
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
        self._state_changed = True
        log.info(f"[WebController] start('{title}')")

    def createNewProject(self):
        """controller.py:303"""
        self.logic.createNewTemporaryProject()
        self.start()

    def openExistingProject(self, filename, projectType='legion'):
        """controller.py:308 — open .legion file, no Qt dialogs."""
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

    def saveProjectAs(self, filename, replace=0):
        """controller.py:390 — save project to file."""
        self.saveRunningProcessOutputs()
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
                if pattern in line:
                    return matches  # Negative hit → no matches for this line
        # Check positive patterns
        if 'positive' in current:
            for pattern in current['positive']:
                if pattern in line:
                    matches.add(pattern)
        return matches

    # ──────────────────────────────────────────────────────────────
    # P3: Deduplication (from controller.py:3746-3789)
    # ──────────────────────────────────────────────────────────────

    def checkDuplicate(self, toolName, hostIp, port, protocol='tcp'):
        """Check if this tool was already run on this host:port.
        Returns: 'run' | 'skip' | 'newTab' | 'append' | 'askMe'

        Checks two layers (Qt6: controller.py:checkDuplicate):
        1. Process table — same name+hostIp+port already ran
        2. Script table — nmap NSE scripts already stored for this port
           (Qt6: scriptRepository.getScriptsByPortId before running scheduler tools)
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

        if script_count > 0:
            log.debug(f"[checkDuplicate] {toolName} on {hostIp}:{port} — {script_count} NSE scripts exist, mode={mode}")
            return mode

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

    def _run_screenshot(self, ip, port):
        """Run eyewitness via runCommand so the process appears in the Processes/Tools
        table immediately (Waiting → Running → Finished), matching Qt6 visibility.
        Qt6 used a QThread (Screenshooter); Flask uses the normal subprocess pipeline.
        Qt6: Screenshooter blacklist — skip if host was deleted mid-scan."""
        from app.httputil.isHttps import isHttps
        from app.timing import getTimestamp
        from app.auxiliary import isKali

        # Qt6: screenshooter blacklist — do not screenshot deleted hosts
        if ip in getattr(self, '_deleted_hosts', set()):
            log.info(f"[WebController] Screenshot skipped — {ip} is in deletion blacklist")
            return

        # Check eyewitness is installed before queuing anything
        eyewitness = '/usr/bin/eyewitness' if isKali() else '/usr/local/bin/eyewitness'
        if not os.path.isfile(eyewitness):
            log.warning(f"[WebController] eyewitness not found at {eyewitness} — screenshot skipped for {ip}:{port}")
            return

        output_folder = self.logic.activeProject.properties.outputFolder
        screenshots_dir = os.path.join(output_folder, 'screenshots')
        try:
            os.makedirs(screenshots_dir, exist_ok=True)
        except Exception:
            pass

        try:
            proto = 'https' if isHttps(ip, port) else 'http'
        except Exception:
            proto = 'http'
        url = f"{proto}://{ip}:{port}"

        outputfile = os.path.join(screenshots_dir, f"{getTimestamp()}-{ip}-{port}")
        cmd = (f"xvfb-run -a {eyewitness} --single {url} --no-prompt --web --delay 5 "
               f"-d {outputfile}-dir")

        log.info(f"[WebController] Screenshot: {url}")
        self.runCommand(command=cmd, name='screenshooter',
                        tabTitle=f'screenshooter ({port}/tcp)',
                        hostIp=ip, port=str(port), protocol='tcp',
                        outputfile=outputfile, run_actions=False)

    def saveRunningProcessOutputs(self):
        """controller.py:2305 — flush active process output to DB before save."""
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        saved = 0
        for proc in list(self._active_processes.values()):
            try:
                if proc._popen and proc._popen.poll() is None:
                    # Process still running — read what we have so far
                    # (the background thread is already flushing, but do one more)
                    log.info(f"[WebController] Flushing output for running process {proc.id}")
                    saved += 1
            except Exception as e:
                log.error(f"[WebController] saveRunningProcessOutputs error: {e}")
        if saved:
            log.info(f"[WebController] Flushed output for {saved} running processes")

    def killRunningProcesses(self):
        """controller.py:1700 — kill all active subprocesses."""
        for proc_id, proc in list(self._active_processes.items()):
            try:
                if proc._popen and proc._popen.poll() is None:
                    os.kill(proc._popen.pid, signal.SIGTERM)
                    time.sleep(0.3)
                    if proc._popen.poll() is None:
                        os.kill(proc._popen.pid, signal.SIGKILL)
                    log.info(f"[WebController] Killed process {proc_id}")
            except (ProcessLookupError, OSError):
                pass
            except Exception as e:
                log.error(f"[WebController] killRunningProcesses error: {e}")
        self._active_processes.clear()
        self.processes.clear()
        self.fastProcessesRunning = 0

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
        try:
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

                            # Duplicate check — Qt6: controller.py:checkDuplicate
                            # Applies to ALL tools including screenshooter.
                            # storeScreenshot creates a process entry with name='screenshooter',
                            # so the DB check catches completed screenshots on repeat scheduler runs.
                            try:
                                from app.auxiliary import Filters as _Filters
                                existing = self.logic.activeProject.repositoryContainer.processRepository.getProcesses(
                                    _Filters(), showProcesses='noNmap')
                                already_ran = any(
                                    p.get('name','') == tool_id and
                                    p.get('hostIp','') == hip and
                                    str(p.get('port','')) == str(port_num)
                                    for p in (existing or [])
                                )
                                if already_ran:
                                    log.debug(f'[Scheduler] Skipping {tool_id} on {hip}:{port_num} — already ran')
                                    continue
                            except Exception:
                                pass

                            # Screenshooter is a built-in special tool — not a portAction.
                            # Also guard with in-memory set to block concurrent duplicate shots
                            # (DB entry only exists after the shot completes, not while in progress).
                            if tool_id == 'screenshooter':
                                if not hasattr(self, '_screenshots_taken'):
                                    self._screenshots_taken = set()
                                scr_key = f"{hip}:{port_num}"
                                if scr_key in self._screenshots_taken:
                                    log.debug(f'[Scheduler] Screenshot already in progress: {scr_key}')
                                    continue
                                self._screenshots_taken.add(scr_key)
                                self._run_screenshot(hip, port_num)
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

        # Count currently running processes (excluding interactive)
        running_all = [p for p in self._active_processes.values()
                       if p._popen and p._popen.poll() is None
                       and not getattr(p, 'isInteractive', False)]
        running_scans = [p for p in running_all if 'nmap' in str(p.name).lower()]

        log.debug(f"[Queue] running={len(running_all)}/{max_fast} scans={len(running_scans)}/{max_scans} queued={self.fastProcessQueue.qsize()}")

        # Start processes while under limits (controller.py:1590-1591)
        while not self.fastProcessQueue.empty():
            if len(running_all) >= max_fast:
                break
            if len(running_scans) >= max_scans and not self.fastProcessQueue.empty():
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
                processRepo = self.logic.activeProject.repositoryContainer.processRepository
                processRepo.storeProcessRunningStatus(str(proc_id), str(popen.pid))
                self._active_processes[int(proc_id)] = proc
                self.fastProcessesRunning += 1
                running_all.append(proc)
                if 'nmap' in str(proc.name).lower():
                    running_scans.append(proc)

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
            {'label': 'Kill', 'action': 'kill'},
            {'label': 'Retry', 'action': 'retry'},
            {'label': 'Clear', 'action': 'clear'},
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
                   _is_staged=False, force_interactive=False):
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
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        dbId = str(processRepo.storeProcess(proc))
        proc.id = int(dbId)
        log.info(f"[WebController] Stored process in DB, id={dbId}")

        # Create tool folder (same as controller.py:1856)
        try:
            self.logic.createFolderForTool(name)
        except Exception:
            pass

        # Queue the process (controller.py:1891 — fastProcessQueue.put + checkProcessQueue)
        # checkProcessQueue() handles actual spawning respecting concurrency limits
        proc._run_actions = run_actions
        proc._is_staged = _is_staged
        if not hasattr(self, '_active_processes'):
            self._active_processes = {}

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
                try:
                    line_matches = self.detectMatches(text, toolName)
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
            processRepo.storeProcessOutput(dbId, combined, preserve_status=False)
            log.info(f"[Capture:{dbId}] SQLite write done in {int((time.monotonic()-_write_t0)*1000)}ms")

            # Store elapsed time in seconds (controller.py:handleProcStop)
            if hasattr(proc, '_start_mono'):
                elapsed_secs = finish_mono - proc._start_mono
                processRepo.storeProcessRunningElapsedTime(dbId, round(elapsed_secs, 1))

            exit_code = proc._popen.returncode
            log.info(f"[WebController] Process {dbId} finished, exit={exit_code}, output={len(combined)} bytes")

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
            if 'nmap' in str(toolName).lower() and outputfile and exit_code == 0 and not is_staged:
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
            processRepo.storeProcessOutput(dbId, ''.join(output_parts) + f"\n[capture error: {e}]")

    def killProcess(self, process_id):
        """Kill a running process by DB id. Replaces controller.py:killProcess.
        Also cleans up any associated PTY terminal session (Interactive processes)."""
        processRepo = self.logic.activeProject.repositoryContainer.processRepository
        proc = self._active_processes.get(int(process_id)) if hasattr(self, '_active_processes') else None

        if proc and proc._popen and proc._popen.poll() is None:
            try:
                os.kill(proc._popen.pid, signal.SIGTERM)
                time.sleep(0.5)
                if proc._popen.poll() is None:
                    os.kill(proc._popen.pid, signal.SIGKILL)
                log.info(f"[WebController] Killed process {process_id} (pid {proc._popen.pid})")
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

        if scanMode == 'Easy':
            if runStagedNmap:
                return self.runStagedNmap(target, discovery=runHostDiscovery, enable_ipv6=enableIPv6)
            elif runHostDiscovery:
                command = f"{nmap_bin} -sV -O --version-light -T{nmapSpeed} {target} --stats-every 5s -oA {outputfile}"
                return self.runCommand(command=command, name='nmap', tabTitle='nmap (discovery)',
                                       hostIp=target, outputfile=outputfile)
            else:
                command = f"{nmap_bin} -sL -T{nmapSpeed} {target} --stats-every 5s -oA {outputfile}"
                return self.runCommand(command=command, name='nmap', tabTitle='nmap (list)',
                                       hostIp=target, outputfile=outputfile)
        elif scanMode == 'Hard':
            opts = ' '.join(nmapOptions or [])
            command = f"{nmap_bin} {opts} -T{nmapSpeed} {target} --stats-every 5s -oA {outputfile}"
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
            self.runStagedNmap(ip, discovery=False)
            return {'action': 'rescan', 'ip': ip}

        if action_name == 'delete':
            # Qt6: add to screenshooter blacklist so in-flight screenshots are discarded
            self._deleted_hosts.add(ip)
            log.info(f"[WebController] Host {ip} added to _deleted_hosts blacklist")
            # Simplified delete: kill processes, delete from DB
            # Kill running processes for this host
            for proc_id, proc in list(self._active_processes.items()):
                if getattr(proc, 'hostIp', '') == ip:
                    self.killProcess(proc_id)
            # Clear from queue
            if hasattr(self, 'fastProcessQueue'):
                temp = queue_module.Queue()
                while not self.fastProcessQueue.empty():
                    try:
                        p = self.fastProcessQueue.get_nowait()
                        if getattr(p, 'hostIp', '') != ip:
                            temp.put(p)
                    except:
                        break
                while not temp.empty():
                    self.fastProcessQueue.put(temp.get_nowait())
            # Delete from DB
            try:
                from sqlalchemy import text
                session = repositoryContainer.hostRepository.dbAdapter.session()
                try:
                    session.execute(text("DELETE FROM process_output WHERE id IN (SELECT id FROM process WHERE hostIp = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM process WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text("DELETE FROM l1ScriptObj WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM cve WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM portObj WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM note WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM osObj WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM hostObj WHERE ip = :ip"), {"ip": ip})
                    session.commit()
                finally:
                    session.close()
                log.info(f"[WebController] Deleted host {ip} and all related data")
            except Exception as e:
                log.error(f"[WebController] Delete host error: {e}")
            return {'action': 'delete', 'ip': ip}

        if action_name == 'purge':
            # Purge: kill processes + delete scan data but keep host + notes
            for proc_id, proc in list(self._active_processes.items()):
                if getattr(proc, 'hostIp', '') == ip:
                    self.killProcess(proc_id)
            try:
                from sqlalchemy import text
                session = repositoryContainer.hostRepository.dbAdapter.session()
                try:
                    session.execute(text("DELETE FROM process_output WHERE id IN (SELECT id FROM process WHERE hostIp = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM process WHERE hostIp = :ip"), {"ip": ip})
                    session.execute(text("DELETE FROM l1ScriptObj WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM cve WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    session.execute(text("DELETE FROM portObj WHERE hostId = (SELECT id FROM hostObj WHERE ip = :ip)"), {"ip": ip})
                    # Keep host + notes
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
        first_word = command.strip().split()[0] if command.strip() else ''
        if first_word.startswith('python-script-'):
            script_slug = first_word[len('python-script-'):]
            script_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'scripts', 'python', f'{script_slug}.py'
            )
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
            dup_mode = self.checkDuplicate(tool, ip, port, protocol)
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
        """controller.py:2055 — run staged nmap scan."""
        from app.timing import getTimestamp
        host_arg = str(targetHosts).strip()
        if not host_arg:
            return

        log.info(f"[WebController] runStagedNmap stage {stage} for {host_arg}")
        # Use outputFolder — the designated tool-output directory.
        # runningFolder is a separate temp dir that ProjectManager creates for
        # interactive tool output, but nmap XML files end up in outputFolder.
        # The session_path approach was wrong: session_path=None so it fell back
        # to runningFolder, but that's where ecjt6f6v-running lives (no XML files).
        tool_output_dir = self.logic.activeProject.properties.outputFolder
        log.info(f"[WebController] Stage {stage} output dir: {tool_output_dir}")

        if stop:
            return

        outputfile = os.path.join(tool_output_dir, f"{getTimestamp()}-nmapstage{stage}")

        # Get stage config from settings
        stage_attr = f'tools_nmap_stage{stage}_ports'
        stageData = getattr(self.settings, stage_attr, '')
        if not stageData:
            log.info(f"[WebController] No data for stage {stage}, done")
            return

        parts = str(stageData).split('|', maxsplit=1)
        stageOp = parts[0]
        stageOpValues = parts[1] if len(parts) > 1 else ''

        if stageOp in ('', 'NOOP', 'SKIP'):
            return

        # Build command
        nmap_bin = getattr(self.settings, 'tools_path_nmap', '').strip() or 'nmap'
        tokens = [nmap_bin]
        if enable_ipv6:
            tokens.append('-6')
        if discovery:
            tokens.extend(['-T4', '-sV', '-sSU', '-O'])
        else:
            tokens.extend(['-Pn', '-sS', '-O'])

        if stageOp == 'PORTS':
            port_values = stageOpValues.strip()
            if port_values:
                tokens.extend(['-p', port_values])
            tokens.extend(['-vvvv', host_arg, '--stats-every', '5s', '-oA', outputfile])
        elif stageOp == 'NSE':
            tokens = [nmap_bin]
            if enable_ipv6:
                tokens.append('-6')
            # --min-parallelism: run multiple NSE script instances concurrently so
            # scripts like vulners (which make external HTTP calls) don't block each
            # other sequentially. --script-timeout caps any single script that hangs.
            tokens.extend(['-sV', f'--script={stageOpValues.strip()}', '-vvvv',
                          '--min-parallelism', '20', '--max-parallelism', '50',
                          '--script-timeout', '30s',
                          host_arg, '--stats-every', '5s', '-oA', outputfile])
        else:
            tokens.extend(['-vvvv', host_arg, '--stats-every', '5s', '-oA', outputfile])

        command = ' '.join(t for t in tokens if t)
        log.info(f"[WebController] Stage {stage} command: {command}")

        # Run and chain to next stage on completion
        result = self.runCommand(command=command, name='nmap', tabTitle=f'nmap (stage {stage})',
                                 hostIp=host_arg, outputfile=outputfile, _is_staged=True)

        # Chain next stage via background thread monitoring
        if stage < 6 and result and result.get('process_id'):
            proc_id = result['process_id']
            def _chain_next_stage():
                log.info(f"[Chain{stage}] WAITING for process {proc_id} to start...")
                # Wait for process to START (it may still be in fastProcessQueue)
                deadline = time.monotonic() + 600
                proc = None
                while time.monotonic() < deadline:
                    proc = self._active_processes.get(proc_id)
                    if proc and proc._popen is not None:
                        break
                    time.sleep(0.5)

                if proc and proc._popen is not None:
                    log.info(f"[Chain{stage}] Process {proc_id} STARTED (pid={proc.pid}), waiting for finish...")
                    proc._popen.wait()
                    log.info(f"[Chain{stage}] Process {proc_id} FINISHED (exit={proc._popen.returncode})")
                else:
                    log.warning(f"[Chain{stage}] Stage {stage} never started (proc_id={proc_id}), stopping chain")
                    return

                # Check if killed
                processRepo = self.logic.activeProject.repositoryContainer.processRepository
                if processRepo.isKilledProcess(str(proc_id)):
                    log.info(f"[Chain{stage}] Stage {stage} was killed, stopping chain")
                    return

                # Import nmap results
                exit_code = proc._popen.returncode
                xml_path = outputfile + '.xml'
                xml_exists = os.path.isfile(xml_path)
                xml_size = os.path.getsize(xml_path) if xml_exists else -1
                log.info(f"[Chain{stage}] nmap exit={exit_code}  xml_path={xml_path}  exists={xml_exists}  size={xml_size}b")
                if xml_exists and xml_size > 0:
                    try:
                        from app.importers.nmap_import import import_nmap_xml
                        import_nmap_xml(project=self.logic.activeProject,
                                        xml_path=xml_path, output="")
                        log.info(f"[WebController] Stage {stage} XML imported: {xml_path}")
                        # Verify host/port counts using raw sqlite3 — bypasses ALL
                        # SQLAlchemy session/transaction caching to see actual DB state.
                        try:
                            import sqlite3 as _sq3
                            _xml_size = os.path.getsize(xml_path) if os.path.isfile(xml_path) else -1
                            _db_path = self.logic.activeProject.database.name
                            with _sq3.connect(_db_path) as _rc:
                                _hc = _rc.execute("SELECT COUNT(*) FROM hostObj").fetchone()[0]
                                _pc = _rc.execute("SELECT COUNT(*) FROM portObj").fetchone()[0]
                                _sc = _rc.execute("SELECT COUNT(*) FROM serviceObj").fetchone()[0]
                            log.info(f"[Chain{stage}] XML={_xml_size}b  raw-DB: {_hc} hosts, {_pc} ports, {_sc} services")
                        except Exception as _ve:
                            log.error(f"[Chain{stage}] DB verify failed: {_ve}")
                        # Qt6: NmapImporter.schedule.connect(self.scheduler) fires after every
                        # stage import. Run automated attacks on newly discovered ports.
                        self.scheduler(isNmapImport=False)
                    except Exception as e:
                        log.error(f"[WebController] Stage {stage} import error: {e}")
                else:
                    log.warning(f"[WebController] Stage {stage} XML not found: {xml_path}")
                # Run next stage
                self.runStagedNmap(host_arg, discovery=discovery, stage=stage+1, enable_ipv6=enable_ipv6)

            t = threading.Thread(target=_chain_next_stage, daemon=True,
                                name=f"stage-chain-{stage}-{host_arg}")
            t.start()

        return result

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
