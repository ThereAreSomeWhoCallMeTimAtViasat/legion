#!/usr/bin/env python
"""
LEGION (https://shanewilliamscott.com)
Copyright (c) 2025 Shane William Scott

    This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
    License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
    version.

    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
    details.

    You should have received a copy of the GNU General Public License along with this program.
    If not, see <http://www.gnu.org/licenses/>.

"""

import signal  # for file operations, to kill processes, for regex, for subprocesses
import subprocess
import tempfile
import os
import socket
import re
from PyQt6.QtCore import QTimer, QElapsedTimer, QVariant
from PyQt6 import sip, QtWidgets

from app.ApplicationInfo import applicationInfo
from app.Screenshooter import Screenshooter
from app.actions.updateProgress.UpdateProgressObservable import UpdateProgressObservable
from app.importers.NmapImporter import NmapImporter
from app.importers.PythonImporter import PythonImporter
from app.tools.nmap.NmapPaths import getNmapRunningFolder
from app.auxiliary import unixPath2Win, winPath2Unix, getPid, formatCommandQProcess, isWsl
from app.timing import getTimestamp
from ui.observers.QtUpdateProgressObserver import QtUpdateProgressObserver
import os

try:
    import queue
except Exception:
    log.exception("Failed to import queue module")
    #import Queue as queue
from app.logic import *
from app.settings import *
from db.entities.port import portObj
from db.SqliteDbAdapter import DatabaseIntegrityError

log = getAppLogger()

def normalize_path(path):
    """Normalize a path to use forward slashes, regardless of input."""
    return os.path.normpath(path).replace("\\", "/")

class Controller:
    def _resolve_host_and_ip(self, host_value: str):
        display_host = host_value
        ip_value = host_value
        try:
            repo_container = getattr(self.logic.activeProject, "repositoryContainer", None)
            if repo_container and hasattr(repo_container, "hostRepository"):
                host_repo = repo_container.hostRepository
                host_obj = host_repo.getHostByIP(host_value)
                if not host_obj:
                    host_obj = host_repo.getHostByHostname(host_value)
                if host_obj:
                    hostname = getattr(host_obj, 'hostname', None)
                    if hostname:
                        display_host = hostname.strip()
                    candidate_ip = getattr(host_obj, 'ip', None) or getattr(host_obj, 'ipv4', None)
                    if candidate_ip:
                        ip_value = candidate_ip.strip()
        except Exception:
            log.debug(f"Failed to resolve hostname for {host_value}", exc_info=True)
        return display_host or host_value, ip_value or host_value

    def _resolve_host_record(self, identifier: str):
        """Return the hostObj matching the provided identifier (IP, hostname, or 'ip (hostname)')."""
        repo_container = self.logic.activeProject.repositoryContainer
        host_repo = getattr(repo_container, "hostRepository", None)
        if not host_repo or not identifier:
            return None

        candidates = []
        token = identifier.strip()
        if token:
            candidates.append(token)
        if '(' in token and ')' in token:
            prefix = token.split('(', 1)[0].strip()
            suffix = token.split('(', 1)[1].strip(' )')
            if prefix:
                candidates.append(prefix)
            if suffix:
                candidates.append(suffix)

        # Ensure uniqueness while preserving order
        seen = set()
        normalized_candidates = []
        for cand in candidates:
            if cand and cand not in seen:
                normalized_candidates.append(cand)
                seen.add(cand)

        for cand in normalized_candidates:
            host = host_repo.getHostByIP(cand)
            if host:
                return host
            host = host_repo.getHostByHostname(cand)
            if host:
                return host
        return None
    @staticmethod
    def _has_ipv6_connectivity():
        try:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
            sock.settimeout(1)
            sock.connect(("2606:4700:4700::1111", 53))
            sock.close()
            return True
        except OSError as exc:
            log.debug(f"IPv6 connectivity probe failed: {exc}")
            return False

    # initialisations that will happen once - when the program is launched
    @timing
    def __init__(self, view, logic):
        self.logic = logic
        self.view = view
        self.view.setController(self)
        self.view.startOnce()
        self.view.startConnections()

        self.loadSettings()  # creation of context menu actions from settings file and set up of various settings
        updateProgressObservable = UpdateProgressObservable()

        self.initNmapImporter(updateProgressObservable)
        self.initPythonImporter()
        self.initScreenshooter()
        self.initBrowserOpener()
        self.start()                                                    # initialisations (globals, etc)
        self.initTimers()
        self.processTimers = {}
        self.processMeasurements = {}



    # initialisations that will happen everytime we create/open a project - can happen several times in the
    # program's lifetime
    def start(self, title='*untitled'):
        self.processes = []                    # to store all the processes we run (nmaps, niktos, etc)
        self.fastProcessQueue = queue.Queue()  # to manage fast processes (banner, snmpenum, etc)
        self.fastProcessesRunning = 0          # counts the number of fast processes currently running
        self.slowProcessesRunning = 0          # counts the number of slow processes currently running
        activeProject = self.logic.activeProject
        self.nmapImporter.setDB(activeProject.database)  # tell nmap importer which db to use
        self.nmapImporter.setHostRepository(activeProject.repositoryContainer.hostRepository)
        self.pythonImporter.setDB(activeProject.database)
        self.updateOutputFolder()                                       # tell screenshooter where the output folder is
        self.view.start(title)

    def initNmapImporter(self, updateProgressObservable: UpdateProgressObservable):
        self.nmapImporter = NmapImporter(updateProgressObservable,
                                         self.logic.activeProject.repositoryContainer.hostRepository)
        self.nmapImporter.done.connect(self.importFinished)
        self.nmapImporter.done.connect(self.view.updateInterface)
        self.nmapImporter.done.connect(self.view.updateToolsTableView)
        self.nmapImporter.done.connect(self.view.updateProcessesTableView)
        self.nmapImporter.schedule.connect(self.scheduler)              # run automated attacks
        self.nmapImporter.log.connect(self.view.ui.LogOutputTextView.append)
        # Connect progressUpdated signal to view's progress bar update slot
        self.nmapImporter.progressUpdated.connect(self.view.updateImportProgress)

    def initPythonImporter(self):
        self.pythonImporter = PythonImporter()
        self.pythonImporter.done.connect(self.importFinished)
        self.pythonImporter.done.connect(self.view.updateInterface)
        self.pythonImporter.done.connect(self.view.updateToolsTableView)
        self.pythonImporter.done.connect(self.view.updateProcessesTableView)
        self.pythonImporter.schedule.connect(self.scheduler)              # run automated attacks
        self.pythonImporter.log.connect(self.view.ui.LogOutputTextView.append)

    def initScreenshooter(self):
        # screenshot taker object (different thread)
        self.screenshooter = Screenshooter(self.settings.general_screenshooter_timeout)
        self.screenshooter.done.connect(self.screenshotFinished)
        self.screenshooter.log.connect(self.view.ui.LogOutputTextView.append)

    def initBrowserOpener(self):
        self.browser = BrowserOpener()                                  # browser opener object (different thread)
        self.browser.log.connect(self.view.ui.LogOutputTextView.append)

    # these timers are used to prevent from updating the UI several times within a short time period -
    # which freezes the UI
    def initTimers(self):
        self.updateUITimer = QTimer()
        self.updateUITimer.setSingleShot(True)

        self.updateUI2Timer = QTimer()
        self.updateUI2Timer.setSingleShot(True)

        self.processTableUiUpdateTimer = QTimer()
        self.processTableUiUpdateTimer.timeout.connect(self.view.updateProcessesTableView)
        self.processTableUiUpdateTimer.start(500) # Faster than this doesn't make anything smoother

    # this function fetches all the settings from the conf file. Among other things it populates the actions lists
    # that will be used in the context menus.
    def loadSettings(self):
        self.settingsFile = AppSettings()
        # load settings from conf file (create conf file first if necessary)
        self.settings = Settings(self.settingsFile)
        # save the original state so that we can know if something has changed when we exit LEGION
        self.originalSettings = Settings(self.settingsFile)
        self.logic.projectManager.setStoreWordListsOnExit(self.logic.activeProject,
            self.settings.brute_store_cleartext_passwords_on_exit == 'True')
        self.view.settingsWidget.setSettings(Settings(self.settingsFile))

    # call this function when clicking 'apply' in the settings menu (after validation)
    def applySettings(self, newSettings):
        self.settings = newSettings

    def cancelSettings(self):  # called when the user presses cancel in the Settings dialog
        # resets the dialog's settings to the current application settings to forget any changes made by the user
        self.view.settingsWidget.setSettings(self.settings)

    @timing
    def saveSettings(self, saveBackup = True):
        if not self.settings == self.originalSettings:
            log.info('Settings have been changed.')
            self.settingsFile.backupAndSave(self.settings, saveBackup)
        else:
            log.info('Settings have NOT been changed.')
        
        # === ADD THIS DEBUG CODE ===
        import threading
        import sys
        import traceback
        
        log.info("=== POST-SAVESETTINGS DIAGNOSTIC ===")
        log.info(f"saveSettings() about to return")
        log.info(f"Active threads: {threading.active_count()}")
        for t in threading.enumerate():
            log.info(f"  Thread: {t.name}, daemon={t.daemon}")
        
        # Check what's in the call stack
        log.info("=== CALL STACK ===")
        for line in traceback.format_stack():
            log.info(line.strip())
        
        log.info("saveSettings() returning NOW")
        # === END DEBUG CODE ===


    def getSettings(self):
        return self.settings

    #################### AUXILIARY ####################

    def getCWD(self):
        return self.logic.activeProject.properties.workingDirectory

    def getProjectName(self):
        return self.logic.activeProject.properties.projectName

    def getRunningFolder(self):
        return self.logic.activeProject.properties.runningFolder

    def getOutputFolder(self):
        return self.logic.activeProject.properties.outputFolder

    def getUserlistPath(self):
        return self.logic.activeProject.properties.usernamesWordList.filename

    def getPasslistPath(self):
        return self.logic.activeProject.properties.passwordWordList.filename

    def updateOutputFolder(self):
        self.screenshooter.updateOutputFolder(
            self.logic.activeProject.properties.outputFolder + '/screenshots')  # update screenshot folder

    def copyNmapXMLToOutputFolder(self, filename):
        self.logic.copyNmapXMLToOutputFolder(filename)

    def isTempProject(self):
        return self.logic.activeProject.properties.isTemporary

    def getDB(self):
        return self.logic.activeProject.database

    def getRunningProcesses(self):
        return self.processes

    def getHostActions(self):
        return self.settings.hostActions

    def getPortActions(self):
        return self.settings.portActions

    def getPortTerminalActions(self):
        return self.settings.portTerminalActions

    #################### ACTIONS ####################

    def createNewProject(self):
        self.view.closeProject()  # removes temp folder (if any)
        self.logic.createNewTemporaryProject()
        self.start()  # initialisations (globals, etc)

    def openExistingProject(self, filename, projectType='legion'):
        self.view.closeProject()
        try:
            self.logic.openExistingProject(filename, projectType)
        except DatabaseIntegrityError as exc:
            log.error(f"Failed to open project {filename}: {exc}")
            QtWidgets.QMessageBox.critical(
                self.view.ui.centralwidget,
                'Corrupted Project',
                f"Legion detected corruption while opening '{filename}'.\n\n"
                f"Details: {exc}\n\n"
                "The project was not loaded. A new temporary session has been created."
            )
            self.logic.createNewTemporaryProject()
            self.start()
            return False
        except Exception as exc:
            log.exception(f"Unexpected error opening project {filename}")
            QtWidgets.QMessageBox.critical(
                self.view.ui.centralwidget,
                'Error Opening Project',
                f"Failed to open project '{filename}'.\n\nDetails: {exc}"
            )
            self.logic.createNewTemporaryProject()
            self.start()
            return False
        # initialisations (globals, signals, etc)
        self.start(os.path.basename(self.logic.activeProject.properties.projectName))
        self.view.restoreToolTabs() # restores the tool tabs for each host
        self.view.hostTableClick() # click on first host to restore his host tool tabs
        try:
            repo_container = getattr(self.logic.activeProject, "repositoryContainer", None)
            if repo_container and hasattr(repo_container, "processRepository"):
                repo_container.processRepository.resetDisplayStatusForOpenProcesses()
                self.view.refreshToolsTableModel()
                self.view.viewState.lazy_update_tools = True
        except Exception:
            log.exception("Failed to reset process display status when opening project")
        return True

    def saveProject(self, lastHostIdClicked, notes):
        """
        Save project with notes for the specified host ID
        
        FIXED: Added validation to handle None/"None"/empty values after host deletion
        """
        # Early validation: Skip if lastHostIdClicked is invalid
        if not lastHostIdClicked or lastHostIdClicked in ['None', '']:
            log.debug(f"Skipping saveProject: lastHostIdClicked is invalid ({lastHostIdClicked})")
            return
        
        try:
            # Ensure we're passing the numeric host ID, not an IP address
            if isinstance(lastHostIdClicked, str) and '.' in lastHostIdClicked:
                # If lastHostIdClicked is an IP address, resolve it to host ID
                host = self.logic.activeProject.repositoryContainer.hostRepository.getHostByIP(lastHostIdClicked)
                if host:
                    hostId = host.id
                    log.debug(f"Resolved IP {lastHostIdClicked} to hostId {hostId}")
                else:
                    log.warning(f"Cannot save notes: host {lastHostIdClicked} not found in database")
                    return
            else:
                # Convert to integer - will fail gracefully if invalid
                try:
                    hostId = int(lastHostIdClicked)
                    log.debug(f"Using hostId {hostId} directly")
                except (ValueError, TypeError) as e:
                    log.warning(f"Cannot save notes: invalid hostId '{lastHostIdClicked}' - {e}")
                    return
            
            # Save the notes
            log.debug(f"Calling storeNotes for hostId={hostId}, notes length={len(notes)}")
            self.logic.activeProject.repositoryContainer.noteRepository.storeNotes(hostId, notes)
            
        except Exception as e:
            log.error(f"Error saving notes for {lastHostIdClicked}: {e}")
            import traceback
            log.debug(traceback.format_exc())



    def saveProjectAs(self, filename, replace=0):
        try:
            success = self.logic.saveProjectAs(filename, replace)
        except DatabaseIntegrityError as exc:
            log.error(f"Failed to save project '{filename}': {exc}")
            QtWidgets.QMessageBox.critical(
                self.view.ui.centralwidget,
                'Error Saving Project',
                f"Legion was unable to save the project because the database failed an integrity check.\n\n"
                f"Details: {exc}"
            )
            return False
        except Exception as exc:
            log.exception(f"Unexpected error saving project '{filename}'")
            QtWidgets.QMessageBox.critical(
                self.view.ui.centralwidget,
                'Error Saving Project',
                f"Unexpected error while saving project: {exc}"
            )
            return False
        if success:
            self.nmapImporter.setDB(self.logic.activeProject.database) # tell nmap importer which db to use
        return success

    def closeProject(self):
        self.saveSettings()  # backup and save config file, if necessary
        
        # Terminate screenshooter with timeout
        if hasattr(self, 'screenshooter') and self.screenshooter:
            try:
                log.info("Terminating screenshooter thread...")
                if self.screenshooter.isRunning():
                    self.screenshooter.requestInterruption()
                    self.screenshooter.quit()
                    if not self.screenshooter.wait(3000):  # 3 second timeout
                        log.warning("Screenshooter thread did not terminate in time")
                log.info("Screenshooter terminated")
            except Exception as e:
                log.error(f"Error terminating screenshooter: {e}")
        
        self.initScreenshooter()
        self.view.updateProcessesTableView()  # clear process table
        self.logic.projectManager.closeProject(self.logic.activeProject)


    def copyToClipboard(self, data):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(data) # Assuming item.text() contains the IP or hostname

    @timing
    def addHosts(self, targetHosts, runHostDiscovery, runStagedNmap, nmapSpeed, scanMode,
                 nmapOptions=None, enableIPv6=False):
        if targetHosts == '':
            log.info('No hosts entered..')
            return

        if nmapOptions is None:
            nmapOptions = []
        else:
            nmapOptions = [opt for opt in nmapOptions if opt]

        # Normalize whitespace
        nmapOptions = [opt.strip() for opt in nmapOptions if opt and opt.strip()]

        if enableIPv6 and not self._has_ipv6_connectivity():
            log.warning("IPv6 connectivity test failed. Falling back to IPv4-only scanning.")
            try:
                self.view.ui.statusbar.showMessage('IPv6 connectivity unavailable; falling back to IPv4', 5000)
            except Exception:
                pass
            enableIPv6 = False

        incompatible_prefixes = ('-f', '--randomize-hosts', '--data-length')
        if enableIPv6:
            filtered_options = []
            removed = []
            for opt in nmapOptions:
                lower = opt.lower()
                if lower.startswith(incompatible_prefixes):
                    removed.append(opt)
                    continue
                filtered_options.append(opt)
            if removed:
                log.info(f"Removing IPv6-incompatible nmap options: {', '.join(removed)}")
            nmapOptions = filtered_options

        import os
        runningFolder = normalize_path(self.logic.activeProject.properties.runningFolder)
        # Use the session directory for temp files
        session_path = getattr(self.logic.activeProject, "sessionFile", None)
        if session_path:
            session_dir = normalize_path(os.path.dirname(session_path))
        else:
            session_dir = runningFolder
        # Use the tool output directory directly, not a subdirectory
        tool_output_dir = session_dir
        ipv6_flag = enableIPv6

        target_hosts_str = str(targetHosts).strip()
        if not target_hosts_str:
            log.warning("addHosts: target host string is empty, skipping scan.")
            return

        if scanMode == 'Easy':
            if runStagedNmap:
                self.runStagedNmap(target_hosts_str, discovery=runHostDiscovery, enable_ipv6=ipv6_flag)
            elif runHostDiscovery:
                outputfile = normalize_path(os.path.join(tool_output_dir, f"{getTimestamp()}-host-discover"))
                easy_mode_flags = ['-f', '--data-length 5', '--randomize-hosts', '--max-retries 2']
                if ipv6_flag:
                    removed_easy = [flag for flag in easy_mode_flags if flag.startswith('-f') or flag.startswith('--randomize-hosts') or flag.startswith('--data-length')]
                    if removed_easy:
                        log.info(f"Removing IPv6-incompatible easy-mode options: {', '.join(removed_easy)}")
                    easy_mode_flags = [flag for flag in easy_mode_flags if flag not in removed_easy]

                command_tokens = ["nmap"]
                if ipv6_flag:
                    command_tokens.append("-6")
                command_tokens.extend(nmapOptions)
                command_tokens.extend(easy_mode_flags)
                command_tokens.extend([
                    "-sV", "-O", "--version-light", f"-T{str(nmapSpeed)}",
                    target_hosts_str, "--stats-every", "10s", "-oA", outputfile
                ])
                command = ' '.join(token for token in command_tokens if token)
                self.runCommand('nmap', 'nmap (discovery)', target_hosts_str, '', '', command, getTimestamp(True),
                                outputfile, self.view.createNewTabForHost(str(targetHosts), 'nmap (discovery)', True),
                                enable_ipv6=ipv6_flag)
            else:
                outputfile = normalize_path(os.path.join(tool_output_dir, f"{getTimestamp()}-nmap-list"))
                command_tokens = ["nmap"]
                if ipv6_flag:
                    command_tokens.append("-6")
                command_tokens.extend(nmapOptions)
                command_tokens.extend([
                    "-sL", f"-T{str(nmapSpeed)}", target_hosts_str, "--stats-every", "10s", "-oA", outputfile
                ])
                command = ' '.join(token for token in command_tokens if token)
                self.runCommand('nmap', 'nmap (list)', target_hosts_str, '', '', command, getTimestamp(True),
                                outputfile,
                                self.view.createNewTabForHost(str(targetHosts), 'nmap (list)', True),
                                enable_ipv6=ipv6_flag)
        elif scanMode == 'Hard':
            outputfile = normalize_path(os.path.join(tool_output_dir, f"{getTimestamp()}-nmap-custom"))
            options_tokens = list(nmapOptions)
            if not any('randomize' in opt.lower() for opt in options_tokens):
                options_tokens.append(f"-T{str(nmapSpeed)}")
            if ipv6_flag and not any(opt.strip().startswith('-6') for opt in options_tokens):
                options_tokens.insert(0, '-6')
            options_tokens = [opt for opt in options_tokens if opt]
            options_str = ' '.join(options_tokens).strip()
            command_tokens = ["nmap"]
            command_tokens.extend(options_tokens)
            command_tokens.extend([target_hosts_str, "--stats-every", "10s", "-oA", outputfile])
            command = ' '.join(token for token in command_tokens if token)
            display_label = options_str
            self.runCommand('nmap', 'nmap (custom ' + display_label + ')', target_hosts_str, '', '', command,
                            getTimestamp(True), outputfile,
                            self.view.createNewTabForHost(
                                str(targetHosts), 'nmap (custom ' + display_label + ')', True),
                            enable_ipv6=ipv6_flag)

    #################### CONTEXT MENUS ####################

    # showAll exists because in some cases we only want to show host tools excluding portscans and 'mark as checked'
    @timing
    def getContextMenuForHost(self, isChecked, showAll=True):
        menu = QMenu()
        self.nmapSubMenu = QMenu('Portscan')
        actions = []

        for a in self.settings.hostActions:
            if "nmap" in a[1] or "unicornscan" in a[1]:
                actions.append(self.nmapSubMenu.addAction(a[0]))
            else:
                actions.append(menu.addAction(a[0]))

        if showAll:
            actions.append(self.nmapSubMenu.addAction("Run nmap (staged)"))

            menu.addMenu(self.nmapSubMenu)
            menu.addSeparator()

            if isChecked == 'True':
                menu.addAction('Mark as unchecked')
            else:
                menu.addAction('Mark as checked')
            menu.addAction('Rescan')
            menu.addAction('Purge Results')
            menu.addAction('Delete')

        return menu, actions

    @timing
    def handleHostAction(self, ip, hostid, actions, action):
        repositoryContainer = self.logic.activeProject.repositoryContainer
        runningFolder = self.logic.activeProject.properties.runningFolder
        # Use the session directory for temp files
        sessionpath = getattr(self.logic.activeProject, 'sessionFile', None)
        if sessionpath:
            sessiondir = os.path.dirname(sessionpath)
        else:
            sessiondir = runningFolder
        # Use the tool output directory directly, not a subdirectory
        tooloutputdir = sessiondir

        if action.text() == 'Mark as checked' or action.text() == 'Mark as unchecked':
            repositoryContainer.hostRepository.toggleHostCheckStatus(ip)
            self.view.updateInterface()
            return

        if action.text() == 'Run nmap (staged)':
            # Do not purge previous portscan data; preserve previously discovered ports/services.
            log.info('Running nmap (staged) scan for ' + str(ip))
            self.runStagedNmap(ip, False)
            return

        if action.text() == 'Rescan':
            log.info(f'Rescanning host {str(ip)}')
            self.runStagedNmap(ip, False)
            return

        if action.text() == 'Purge Results':
            log.info("=" * 80)
            log.info(f"PURGE RESULTS START: {ip}")
            log.info("=" * 80)

            # STEP 1: Cancel screenshots
            log.info("STEP 1: Cancelling screenshots...")
            try:
                if hasattr(self, 'screenshooter') and self.screenshooter:
                    log.info(f"  - Screenshooter exists, calling cancelScreenshotsForIp({ip})")
                    removed = self.screenshooter.cancelScreenshotsForIp(ip)
                    log.info(f"  - Cancelled {removed} queued screenshots and blacklisted {ip}")
                else:
                    log.info("  - No screenshooter found, skipping")
            except Exception as e:
                log.error(f"  - ERROR cancelling screenshots: {e}")

            # STEP 2: Mark processes as killed
            log.info("STEP 2: Marking processes as killed...")
            try:
                processRepo = repositoryContainer.processRepository
                running_processes = [p for p in self.processes if hasattr(p, 'hostIp') and p.hostIp == ip]
                log.info(f"  - Found {len(running_processes)} running processes")
                for proc in running_processes:
                    procid = getattr(proc, 'id', None)
                    if procid:
                        processRepo.storeProcessKillStatus(str(procid))
                        log.info(f"  - Marked process {procid} as killed")
            except Exception as e:
                log.error(f"  - ERROR marking processes as killed: {e}")

            # STEP 3: Kill running processes
            log.info("STEP 3: Killing running processes...")
            try:
                running_processes = [p for p in self.processes if hasattr(p, 'hostIp') and p.hostIp == ip]
                log.info(f"  - Processing {len(running_processes)} processes")
                for proc in running_processes:
                    procid = getattr(proc, 'id', None)
                    pid = getPid(proc)
                    log.info(f"  - Processing procid={procid}, pid={pid}")

                    # Stop timer
                    if procid and procid in self.processTimers:
                        timer = self.processTimers[procid]
                        if timer and timer.isActive():
                            timer.stop()
                        del self.processTimers[procid]
                        log.info(f"    Stopped and removed timer")

                    # Disconnect ALL signals
                    for signalname in ['finished', 'errorOccurred', 'readyReadStandardOutput', 'readyReadStandardError']:
                        try:
                            getattr(proc, signalname).disconnect()
                            log.info(f"    Disconnected {signalname}")
                        except:
                            pass

                    # Kill process
                    if pid:
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            log.info(f"    Sent SIGKILL to pid {pid}")
                        except:
                            pass

                    # Remove from list
                    if proc in self.processes:
                        self.processes.remove(proc)
                        log.info(f"    Removed from self.processes")

                log.info(f"  - Completed killing {len(running_processes)} processes")
            except Exception as e:
                log.error(f"  - ERROR killing processes: {e}")

            # STEP 4: Clear process queue
            log.info("STEP 4: Clearing process queue...")
            try:
                tempqueue = queue.Queue()
                removed_count = 0
                original_size = self.fastProcessQueue.qsize()
                log.info(f"  - Original queue size: {original_size}")

                while not self.fastProcessQueue.empty():
                    try:
                        proc = self.fastProcessQueue.get_nowait()
                        prochost = getattr(proc, 'hostIp', 'unknown')
                        if hasattr(proc, 'hostIp') and proc.hostIp == ip:
                            removed_count += 1
                            log.info(f"  - Removed queued process for {prochost}")
                        else:
                            tempqueue.put(proc)
                    except:
                        break

                while not tempqueue.empty():
                    try:
                        self.fastProcessQueue.put(tempqueue.get_nowait())
                    except:
                        break

                log.info(f"  - Removed {removed_count} queued processes")
            except Exception as e:
                log.error(f"  - ERROR clearing queue: {e}")

            # STEP 4.5: Close all tool tabs for this host
            log.info("STEP 4.5: Closing tool tabs...")
            try:
                closed_count = self.view.closeAllTabsForHost(ip)
                log.info(f"  - Closed {closed_count} tool tabs for {ip}")
            except Exception as e:
                log.error(f"  - ERROR closing tool tabs: {e}")

            # STEP 5: Delete ports, scripts, and CVEs from database (but keep host and notes)
            log.info("STEP 5: Purging scan results from database...")
            try:
                # Get host object for deletions
                from db.entities.host import hostObj
                session = repositoryContainer.hostRepository.dbAdapter.session()
                host = session.query(hostObj).filter_by(ip=str(ip)).first()
                session.close()

                if not host:
                    log.error(f"  ❌ ERROR: Host {ip} not found in database!")
                    raise Exception(f"Host {ip} not found")

                # Delete process records FIRST (before updateProcessesTableView is called)
                try:
                    from sqlalchemy import text
                    session = repositoryContainer.processRepository.dbAdapter.session()
                    
                    # Delete process output first (foreign key)
                    result1 = session.execute(
                        text("DELETE FROM process_output WHERE id IN (SELECT id FROM process WHERE hostIp = :ip)"),
                        {"ip": str(ip)}
                    )
                    deleted_output = result1.rowcount
                    
                    # Delete process records
                    result2 = session.execute(
                        text("DELETE FROM process WHERE hostIp = :ip"),
                        {"ip": str(ip)}
                    )
                    deleted_processes = result2.rowcount
                    
                    session.commit()
                    session.close()
                    
                    if deleted_processes > 0:
                        log.info(f"  - Deleted {deleted_processes} process records (and {deleted_output} output records)")
                    else:
                        log.info("  - No process records to delete")
                except Exception as e:
                    log.error(f"  ❌ ERROR deleting processes: {e}")


                # Delete TCP ports and scripts
                if repositoryContainer.portRepository.getPortsByIPAndProtocol(ip, 'tcp'):
                    repositoryContainer.portRepository.deleteAllPortsAndScriptsByHostId(hostid, 'tcp')
                    log.info("  - Deleted TCP ports and scripts")

                # Delete UDP ports and scripts
                if repositoryContainer.portRepository.getPortsByIPAndProtocol(ip, 'udp'):
                    repositoryContainer.portRepository.deleteAllPortsAndScriptsByHostId(hostid, 'udp')
                    log.info("  - Deleted UDP ports and scripts")

                # Delete CVEs
                try:
                    from db.entities.cve import cve
                    from sqlalchemy import text
                    session = repositoryContainer.cveRepository.dbAdapter.session()
                    result = session.execute(
                        text("DELETE FROM cve WHERE hostId = :hostId"),
                        {"hostId": host.id}
                    )
                    session.commit()
                    deleted_cves = result.rowcount
                    session.close()
                    if deleted_cves > 0:
                        log.info(f"  - Deleted {deleted_cves} CVE records")
                    else:
                        log.info("  - No CVEs to delete")
                except Exception as e:
                    log.error(f"  ❌ ERROR deleting CVEs: {e}")

                # NOTES ARE PRESERVED - user notes remain intact
                log.info("  - User notes preserved")

                log.info("  ✓ Scan results purged from database (host and notes preserved)")
            except Exception as e:
                log.error(f"  - ERROR purging from database: {e}")

            # STEP 6: Clear tab highlights
            log.info("STEP 6: Clearing tab highlights...")
            try:
                self.view.clearAllTabHighlights()
                log.info("  - Tab highlights cleared")
            except Exception as e:
                log.error(f"  - ERROR clearing highlights: {e}")

            # STEP 7: Update interface
            log.info("STEP 7: Updating interface...")
            self.view.updateInterface()
            log.info("  - Interface updated")

            # STEP 7.5: Clear views for the purged host
            log.info("STEP 7.5 Clearing views for purged host...")
            try:
                self.view.clearViewsForHost(ip)
                log.info(" - Views cleared for purged host")
            except Exception as e:
                log.error(f"  - ERROR clearing views: {e}")


            log.info("=" * 80)
            log.info(f"PURGE RESULTS END: {ip}")
            log.info("=" * 80)

            # STEP 8: Schedule cleanup validation (2 seconds)
            log.info("STEP 8: Scheduling cleanup validation in 2 seconds...")
            QTimer.singleShot(2000, lambda: self.cleanupPurgedHost(ip))

            # STEP 9: Schedule verification check (3 seconds)
            log.info("STEP 9: Scheduling verification in 3 seconds...")
            QTimer.singleShot(3000, lambda: self.verifyHostPurged(ip, hostid))

            # STEP 10: Schedule complete database dump (4 seconds)
            log.info("STEP 10: Scheduling database dump in 4 seconds...")
            QTimer.singleShot(4000, lambda: self.dumpDatabaseAfterPurge(ip))

            return

        if action.text() == "Delete":
            log.info("=" * 80)
            log.info(f"DELETE HOST START: {ip}")
            log.info("=" * 80)
            
            # STEP 1: Cancel screenshots
            log.info("STEP 1: Cancelling screenshots...")
            try:
                if hasattr(self, 'screenshooter') and self.screenshooter:
                    log.info(f"  - Screenshooter exists, calling cancelScreenshotsForIp({ip})")
                    removed = self.screenshooter.cancelScreenshotsForIp(ip)
                    log.info(f"  - Cancelled {removed} queued screenshots and blacklisted {ip}")
                else:
                    log.info("  - No screenshooter found, skipping")
            except Exception as e:
                log.error(f"  - ERROR cancelling screenshots: {e}")
            
            # STEP 2: Mark processes as killed
            log.info("STEP 2: Marking processes as killed...")
            try:
                processRepo = repositoryContainer.processRepository
                running_processes = [p for p in self.processes if hasattr(p, 'hostIp') and p.hostIp == ip]
                log.info(f"  - Found {len(running_processes)} running processes")
                for proc in running_processes:
                    procid = getattr(proc, 'id', None)
                    if procid:
                        processRepo.storeProcessKillStatus(str(procid))
                        log.info(f"  - Marked process {procid} as killed")
            except Exception as e:
                log.error(f"  - ERROR marking processes as killed: {e}")
            
            # STEP 3: Kill running processes
            log.info("STEP 3: Killing running processes...")
            try:
                running_processes = [p for p in self.processes if hasattr(p, 'hostIp') and p.hostIp == ip]
                log.info(f"  - Processing {len(running_processes)} processes")
                for proc in running_processes:
                    procid = getattr(proc, 'id', None)
                    pid = getPid(proc)
                    log.info(f"  - Processing procid={procid}, pid={pid}")
                    
                    # Stop timer
                    if procid and procid in self.processTimers:
                        timer = self.processTimers[procid]
                        if timer and timer.isActive():
                            timer.stop()
                        del self.processTimers[procid]
                        log.info(f"    Stopped and removed timer")
                    
                    # Disconnect ALL signals
                    for signalname in ['finished', 'errorOccurred', 'readyReadStandardOutput', 'readyReadStandardError']:
                        try:
                            getattr(proc, signalname).disconnect()
                            log.info(f"    Disconnected {signalname}")
                        except:
                            pass
                    
                    # Kill process
                    if pid:
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            log.info(f"    Sent SIGKILL to pid {pid}")
                        except:
                            pass
                    
                    # Remove from list
                    if proc in self.processes:
                        self.processes.remove(proc)
                        log.info(f"    Removed from self.processes")
                
                log.info(f"  - Completed killing {len(running_processes)} processes")
            except Exception as e:
                log.error(f"  - ERROR killing processes: {e}")
            
            # STEP 4: Clear process queue
            log.info("STEP 4: Clearing process queue...")
            try:
                tempqueue = queue.Queue()
                removed_count = 0
                original_size = self.fastProcessQueue.qsize()
                log.info(f"  - Original queue size: {original_size}")
                
                while not self.fastProcessQueue.empty():
                    try:
                        proc = self.fastProcessQueue.get_nowait()
                        prochost = getattr(proc, 'hostIp', 'unknown')
                        if hasattr(proc, 'hostIp') and proc.hostIp == ip:
                            removed_count += 1
                            log.info(f"  - Removed queued process for {prochost}")
                        else:
                            tempqueue.put(proc)
                    except:
                        break
                
                while not tempqueue.empty():
                    try:
                        self.fastProcessQueue.put(tempqueue.get_nowait())
                    except:
                        break
                
                log.info(f"  - Removed {removed_count} queued processes")
            except Exception as e:
                log.error(f"  - ERROR clearing queue: {e}")
            
            # STEP 4.5: Close all tool tabs for this host
            log.info("STEP 4.5: Closing tool tabs...")
            try:
                closed_count = self.view.closeAllTabsForHost(ip)
                log.info(f"  - Closed {closed_count} tool tabs for {ip}")
            except Exception as e:
                log.error(f"  - ERROR closing tool tabs: {e}")
            
            # STEP 5: Delete from database
            log.info("STEP 5: Deleting from database...")
            repositoryContainer.hostRepository.deleteHost(ip)
            log.info("  - Host deleted from database")
            
            # STEP 6: Clear tab highlights
            log.info("STEP 6: Clearing tab highlights...")
            try:
                self.view.clearAllTabHighlights()
                log.info("  - Tab highlights cleared")
            except Exception as e:
                log.error(f"  - ERROR clearing highlights: {e}")
            
            # STEP 7: Update interface
            log.info("STEP 7: Updating interface...")
            self.view.updateInterface()
            log.info("  - Interface updated")
            
            # STEP 7.5: Clear the Information tab for the deleted host
            log.info("STEP 7.5 Clearing right panel...")
            if hasattr(self.view.viewState, 'ip_clicked') and self.view.viewState.ip_clicked == ip:
                log.info(f" - Deleted host {ip} was currently selected, clearing ALL right panel views")
                #self.view.updateRightPanel('')  # ← When '' is passed, it Clears ALL views, not just Information
                self.view.clearViewsForHost(ip)
                log.info(" - Right panel cleared")
            else:
                log.info(f" - Deleted host {ip} was not currently selected, no clear needed")

            
            log.info("=" * 80)
            log.info(f"DELETE HOST END: {ip}")
            log.info("=" * 80)
            
            # STEP 8: Schedule cleanup validation (2 seconds)
            log.info("STEP 8: Scheduling cleanup validation in 2 seconds...")
            QTimer.singleShot(2000, lambda: self.cleanupDeletedHost(ip))
            
            # STEP 9: Schedule verification check (3 seconds)
            log.info("STEP 9: Scheduling verification in 3 seconds...")
            QTimer.singleShot(3000, lambda: self.verifyHostDeleted(ip))
            
            # STEP 10: Schedule complete database dump (4 seconds)
            log.info("STEP 10: Scheduling database dump in 4 seconds...")
            QTimer.singleShot(4000, lambda: self.dumpDatabaseAfterDelete(ip))
            
            return



        # Handle other actions (tool execution)
        for i in range(0, len(actions)):
            if action == actions[i]:
                name = self.settings.hostActions[i][1]
                invisibleTab = False
                # to make sure different nmap scans appear under the same tool name
                if 'nmap' in name:
                    name = 'nmap'
                    invisibleTab = True
                elif 'python-script' in name:
                    invisibleTab = True

                outputfile = normalize_path(os.path.join(
                    tooloutputdir,
                    f"{getTimestamp()}-{re.sub('[^0-9a-zA-Z]', '', str(self.settings.hostActions[i][1]))}-{ip}"
                ))

                command = str(self.settings.hostActions[i][2])
                command = command.replace('[IP]', ip).replace('[OUTPUT]', outputfile)
                command = f"{command} -oA {outputfile}"
                tabTitle = self.settings.hostActions[i][1]

                self.runCommand(name, tabTitle, ip, '', '', command, getTimestamp(True),
                               outputfile, self.view.createNewTabForHost(ip, tabTitle, invisibleTab))
                break




















    @timing
    def getContextMenuForServiceName(self, serviceName='*', menu=None):
        if menu == None:  # if no menu was given, create a new one
            menu = QMenu()

        if serviceName == '*' or serviceName in self.settings.general_web_services.split(","):
            menu.addAction("Open in browser")
            menu.addAction("Take screenshot")

        actions = []
        for a in self.settings.portActions:
            # if the service name exists in the portActions list show the command in the context menu
            if serviceName is None or serviceName == '*' or serviceName in a[3].split(",") or a[3] == '':
                # in actions list write the service and line number that corresponds to it in portActions
                actions.append([self.settings.portActions.index(a), menu.addAction(a[0])])

        # if the user pressed SHIFT+Right-click show full menu
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers == QtCore.Qt.KeyboardModifier.ShiftModifier:
            shiftPressed = True
        else:
            shiftPressed = False

        return menu, actions, shiftPressed

    @timing
    def handleServiceNameAction(self, targets, actions, action, restoring=True):

        if action.text() == 'Take screenshot':
            for target in targets:
                host_value = str(target[0])
                port_value = str(target[1])
                display_host, resolved_ip = self._resolve_host_and_ip(host_value)
                url = f"{display_host}:{port_value}"
                self.screenshooter.addToQueue(resolved_ip, port_value, url)
            self.screenshooter.start()
            return

        elif action.text() == 'Open in browser':
            for target in targets:
                host_value = str(target[0])
                port_value = str(target[1])
                display_host, _ = self._resolve_host_and_ip(host_value)
                url = f"{display_host}:{port_value}"
                self.browser.addToQueue(url)
            self.browser.start()
            return

        for i in range(0,len(actions)):
            if action == actions[i][1]:
                srvc_num = actions[i][0]
                for ip in targets:
                    tool = self.settings.portActions[srvc_num][1]
                    tabTitle = self.settings.portActions[srvc_num][1]+" ("+ip[1]+"/"+ip[2]+")"
                    import os
                    # Use the same tool_output_dir logic as runStagedNmap for manual tool runs
                    runningFolder = normalize_path(self.logic.activeProject.properties.runningFolder)
                    session_path = getattr(self.logic.activeProject, "sessionFile", None)
                    if session_path:
                        tool_output_dir = normalize_path(os.path.dirname(session_path))
                    else:
                        tool_output_dir = runningFolder
                    outputfile = normalize_path(os.path.join(
                        tool_output_dir,
                        f"{getTimestamp()}-{tool}-{ip[0]}-{ip[1]}"
                    ))

                    command = str(self.settings.portActions[srvc_num][2])
                    # Insert normalized outputfile into command
                    command = command.replace('[IP]', ip[0]).replace('[PORT]', ip[1]).replace('[OUTPUT]', outputfile)
                    if 'nmap' in command:
                        command = f"{command} -oA {outputfile}"

                    if 'nmap' in command and ip[2] == 'udp':
                        command = command.replace("-sV", "-sVU")

                    if 'nmap' in tabTitle:                              # we don't want to show nmap tabs
                        restoring = True
                    elif 'python-script' in tabTitle:                              # we don't want to show nmap tabs
                        restoring = True

                    self.runCommand(tool, tabTitle, ip[0], ip[1], ip[2], command, getTimestamp(True), outputfile,
                                    self.view.createNewTabForHost(ip[0], tabTitle, restoring))
                break

    @timing
    def getContextMenuForPort(self, serviceName='*'):

        menu = QMenu()

        modifiers = QtWidgets.QApplication.keyboardModifiers()  # if the user pressed SHIFT+Right-click show full menu
        if modifiers == QtCore.Qt.KeyboardModifier.ShiftModifier:
            serviceName='*'

        terminalActions = []  # custom terminal actions from settings file
        # if wildcard or the command is valid for this specific service or if the command is valid for all services
        for a in self.settings.portTerminalActions:
            if serviceName is None or serviceName == '*' or serviceName in a[3].split(",") or a[3] == '':
                terminalActions.append([self.settings.portTerminalActions.index(a), menu.addAction(a[0])])

        menu.addSeparator()
        menu.addAction("Send to Brute")
        # Add Take screenshot action for all ports
        menu.addAction("Take screenshot")
        menu.addSeparator()  # dummy is there because we don't need the third return value
        menu, actions, dummy = self.getContextMenuForServiceName(serviceName, menu)
        menu.addSeparator()
        menu.addAction("Run custom command")
        # Add Delete Port action
        # deletePortAction = menu.addAction("Delete Port")  # Unused variable removed

        return menu, actions, terminalActions

    @timing
    def handlePortAction(self, targets, *args):
        actions = args[0]
        terminalActions = args[1]
        action = args[2]
        restoring = args[3]

        if action.text() == 'Delete Port':
            # targets: list of [ip, port, protocol, serviceName]
            repo_container = self.logic.activeProject.repositoryContainer
            host_repo = repo_container.hostRepository
            port_repo = repo_container.portRepository
            for t in targets:
                ip, port, protocol, _ = t
                host = self._resolve_host_record(ip)
                if not host:
                    log.warning(f"Delete Port: host '{ip}' could not be resolved.")
                    continue
                # Attempt to delete the port by host id, port, and protocol
                if hasattr(port_repo, "deletePortByHostIdAndPort"):
                    port_repo.deletePortByHostIdAndPort(host.id, port, protocol)
                else:
                    # Fallback: try to find and delete the port manually
                    session = self.logic.activeProject.database.session()
                    try:
                        port_obj = session.query(portObj).filter_by(
                            hostId=host.id, port=port, protocol=protocol
                        ).first()
                        if port_obj:
                            session.delete(port_obj)
                            session.commit()
                    finally:
                        session.close()
            self.view.updateInterface()
            return

        if action.text() == 'Send to Brute':
            for ip in targets:
                # ip[0] is the IP, ip[1] is the port number and ip[3] is the service name
                self.view.createNewBruteTab(ip[0], ip[1], ip[3])
            return

        if action.text() == 'Take screenshot':
            for target in targets:
                host_value = str(target[0])
                port_value = str(target[1])
                display_host, resolved_ip = self._resolve_host_and_ip(host_value)
                url = f"{display_host}:{port_value}"
                self.screenshooter.addToQueue(resolved_ip, port_value, url)
            self.screenshooter.start()
            return

        if action.text() == 'Run custom command':
            log.info('custom command')
            return

        terminal = self.settings.general_default_terminal               # handle terminal actions
        for i in range(0,len(terminalActions)):
            if action == terminalActions[i][1]:
                srvc_num = terminalActions[i][0]
                for ip in targets:
                    command = str(self.settings.portTerminalActions[srvc_num][2])
                    command = command.replace('[IP]', ip[0]).replace('[PORT]', ip[1])
                    if "[term]" in command:
                        command = command.replace("[term]", "")
                        subprocess.Popen(terminal + " -e './scripts/exec-in-shell " + command + "'", shell=True)
                    else:
                        subprocess.Popen("bash -c \"" + command + "; exec bash\"", shell=True)
                return

        self.handleServiceNameAction(targets, actions, action, restoring)

    def getContextMenuForProcess(self):
        menu = QMenu()
        menu.addAction("Kill")
        menu.addAction("Retry")
        menu.addAction("Clear")
        return menu

    # selectedProcesses is a list of tuples (pid, status, procId)
    def handleProcessAction(self, selectedProcesses, action):
        if action.text() == 'Kill':
            if self.view.killProcessConfirmation():
                for p in selectedProcesses:
                    if p[1] != "Running":
                        if p[1] == "Waiting":
                            if str(self.logic.activeProject.repositoryContainer.processRepository.getStatusByProcessId(
                                    p[2])) == 'Running':
                                self.killProcess(self.view.ProcessesTableModel.getProcessPidForId(p[2]), p[2])
                            self.logic.activeProject.repositoryContainer.processRepository.storeProcessCancelStatus(
                                str(p[2]))
                        else:
                            log.info("This process has already been terminated. Skipping.")
                    else:
                        self.killProcess(p[0], p[2])
                self.view.updateProcessesTableView()
            return

        if action.text() == 'Clear':  # hide all the processes that are not running
            self.logic.activeProject.repositoryContainer.processRepository.toggleProcessDisplayStatus()
            self.view.updateProcessesTableView()
            return

        if action.text() == 'Retry':
            process_repo = self.logic.activeProject.repositoryContainer.processRepository
            for pid, status, proc_id in selectedProcesses:
                if status in ('Running', 'Waiting'):
                    log.info(f"Process {proc_id} is currently {status}; skipping retry.")
                    continue
                process_details = process_repo.getProcessById(proc_id)
                if not process_details:
                    log.warning(f"Unable to locate process details for id {proc_id}; skipping retry.")
                    continue
                command = process_details.get('command')
                if not command:
                    log.warning(f"Process id {proc_id} has no recorded command; skipping retry.")
                    continue
                name = process_details.get('name') or 'process'
                tab_title = process_details.get('tabTitle') or name
                host_ip = process_details.get('hostIp') or ''
                port = process_details.get('port') or ''
                protocol = process_details.get('protocol') or ''
                outputfile = process_details.get('outputfile') or ''

                host_key = host_ip if host_ip else tab_title
                textbox = self.view.createNewTabForHost(host_key, tab_title, False)

                kwargs = {}
                stage_match = re.search(r'stage\s*(\d+)', tab_title, re.IGNORECASE)
                if stage_match:
                    try:
                        stage_number = int(stage_match.group(1))
                    except ValueError:
                        stage_number = 0
                else:
                    stage_number = 0

                if stage_number:
                    discovery_flag = '-Pn' not in command
                    enable_ipv6_flag = '-6' in command
                    kwargs['stage'] = stage_number
                    kwargs['discovery'] = discovery_flag
                    kwargs['enable_ipv6'] = enable_ipv6_flag

                self.runCommand(
                    name,
                    tab_title,
                    host_ip,
                    str(port) if port is not None else '',
                    protocol,
                    command,
                    getTimestamp(True),
                    outputfile,
                    textbox,
                    **kwargs
                )
            self.view.updateProcessesTableView()
            return

    #################### LEFT PANEL INTERFACE UPDATE FUNCTIONS ####################

    def isHostInDB(self, host):
        return self.logic.activeProject.repositoryContainer.hostRepository.exists(host)

    def getHostsFromDB(self, filters):
        return self.logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)

    def getServiceNamesFromDB(self, filters):
        return self.logic.activeProject.repositoryContainer.serviceRepository.getServiceNames(filters)

    def getProcessStatusForDBId(self, dbId):
        return self.logic.activeProject.repositoryContainer.processRepository.getStatusByProcessId(dbId)

    def getPidForProcess(self, dbId):
        return self.logic.activeProject.repositoryContainer.processRepository.getPIDByProcessId(dbId)

    def storeCloseTabStatusInDB(self, pid):
        return self.logic.activeProject.repositoryContainer.processRepository.storeCloseStatus(pid)

    def getServiceNameForHostAndPort(self, hostIP, port):
        return self.logic.activeProject.repositoryContainer.serviceRepository.getServiceNamesByHostIPAndPort(hostIP,
                                                                                                             port)

    #################### RIGHT PANEL INTERFACE UPDATE FUNCTIONS ####################

    def getPortsAndServicesForHostFromDB(self, hostIP, filters):
        return self.logic.activeProject.repositoryContainer.portRepository.getPortsAndServicesByHostIP(hostIP, filters)

    def getHostsAndPortsForServiceFromDB(self, serviceName, filters):
        return self.logic.activeProject.repositoryContainer.hostRepository.getHostsAndPortsByServiceName(serviceName,
                                                                                                         filters)

    def getHostInformation(self, hostIP):
        return self.logic.activeProject.repositoryContainer.hostRepository.getHostInformation(hostIP)

    def getPortStatesForHost(self, hostid):
        return self.logic.activeProject.repositoryContainer.portRepository.getPortStatesByHostId(hostid)

    def getScriptsFromDB(self, hostIP):
        return self.logic.activeProject.repositoryContainer.scriptRepository.getScriptsByHostIP(hostIP)

    def getCvesFromDB(self, hostIP):
        return self.logic.activeProject.repositoryContainer.cveRepository.getCVEsByHostIP(hostIP)

    def getScriptOutputFromDB(self, scriptDBId):
        return self.logic.activeProject.repositoryContainer.scriptRepository.getScriptOutputById(scriptDBId)

    def getNoteFromDB(self, hostid):
        return self.logic.activeProject.repositoryContainer.noteRepository.getNoteByHostId(hostid)

    def getHostsForTool(self, toolName, closed='False'):
        return self.logic.activeProject.repositoryContainer.processRepository.getHostsByToolName(toolName, closed)

    def exportAsJson(self, filename):
        import json
        import base64

        try:
            # Gather all hosts
            hosts = self.logic.activeProject.repositoryContainer.hostRepository.getAllHostObjs()
        except Exception as e:
            log.error(f"Failed to fetch hosts from DB: {e}")
            hosts = []

        hosts_data = []
        for host in hosts:
            try:
                host_dict = host.__dict__.copy()
                host_dict.pop('_sa_instance_state', None)
                # Ports/services for this host
                try:
                    ports = self.logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(host.id)
                except Exception as e:
                    log.error(f"Failed to fetch ports for host {host.id}: {e}")
                    ports = []
                ports_data = []
                for port in ports:
                    try:
                        port_dict = port.__dict__.copy()
                        port_dict.pop('_sa_instance_state', None)
                        # Service for this port
                        try:
                            service_repo = self.logic.activeProject.repositoryContainer.serviceRepository
                            service = service_repo.getServiceById(port.serviceId) \
                                if hasattr(port, 'serviceId') and port.serviceId else None
                        except Exception as e:
                            log.error(f"Failed to fetch service for port {port.id}: {e}")
                            service = None
                        if service:
                            service_dict = service.__dict__.copy()
                            service_dict.pop('_sa_instance_state', None)
                            port_dict['service'] = service_dict
                        # Scripts for this port
                        try:
                            script_repo = self.logic.activeProject.repositoryContainer.scriptRepository
                            scripts = script_repo.getScriptsByPortId(port.id) \
                                if hasattr(self.logic.activeProject.repositoryContainer, 'scriptRepository') else []
                        except Exception as e:
                            log.error(f"Failed to fetch scripts for port {port.id}: {e}")
                            scripts = []
                        scripts_data = []
                        for script in scripts:
                            try:
                                script_dict = script.__dict__.copy()
                                script_dict.pop('_sa_instance_state', None)
                                scripts_data.append(script_dict)
                            except Exception as e:
                                log.error(f"Failed to process script for port {port.id}: {e}")
                        port_dict['scripts'] = scripts_data
                        ports_data.append(port_dict)
                    except Exception as e:
                        log.error(f"Failed to process port for host {host.id}: {e}")
                host_dict['ports'] = ports_data
                # Notes for this host
                try:
                    note = self.logic.activeProject.repositoryContainer.noteRepository.getNoteByHostId(host.id)
                    host_dict['note'] = note.text if note else ""
                except Exception as e:
                    log.error(f"Failed to fetch note for host {host.id}: {e}")
                    host_dict['note'] = ""
                # CVEs for this host
                try:
                    cves = self.logic.activeProject.repositoryContainer.cveRepository.getCVEsByHostIP(host.ip)
                except Exception as e:
                    log.error(f"Failed to fetch CVEs for host {host.ip}: {e}")
                    cves = []
                cves_data = []
                for cve in cves:
                    try:
                        if hasattr(cve, "__dict__"):
                            cve_dict = cve.__dict__.copy()
                            cve_dict.pop('_sa_instance_state', None)
                        else:
                            # Likely a Row object, convert to dict
                            cve_dict = dict(cve)
                        cves_data.append(cve_dict)
                    except Exception as e:
                        log.error(f"Failed to process CVE for host {host.ip}: {e}")
                host_dict['cves'] = cves_data
                hosts_data.append(host_dict)
            except Exception as e:
                log.error(f"Failed to process host {getattr(host, 'id', '?')}: {e}")

        # Gather screenshots
        screenshots_dir = os.path.join(self.logic.activeProject.properties.outputFolder, "screenshots")
        screenshots_data = {}
        if os.path.isdir(screenshots_dir):
            for fname in os.listdir(screenshots_dir):
                if fname.lower().endswith(".png"):
                    fpath = os.path.join(screenshots_dir, fname)
                    try:
                        with open(fpath, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("utf-8")
                        screenshots_data[fname] = b64
                    except Exception as e:
                        log.error(f"Failed to read screenshot {fname}: {e}")
                        screenshots_data[fname] = f"ERROR: {e}"

        # Attach screenshots to ports if available
        for host in hosts_data:
            ip = host.get("ip")
            for port in host.get("ports", []):
                port_num = str(port.get("port"))
                screenshot_fname = f"{ip}-{port_num}-screenshot.png"
                if screenshot_fname in screenshots_data:
                    port["screenshot"] = screenshots_data[screenshot_fname]

        # Compose final export
        export = {
            "hosts": hosts_data,
            "screenshots": screenshots_data
        }

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(export, f, indent=2)
            log.info(f"Exported results as JSON to {filename}")
        except Exception as e:
            log.error(f"Failed to export JSON: {e}")

    #################### BOTTOM PANEL INTERFACE UPDATE FUNCTIONS ####################

    def getProcessesFromDB(self, filters, showProcesses='noNmap', sort='desc', ncol='id', status_filter=None):
        return self.logic.activeProject.repositoryContainer.processRepository.getProcesses(
            filters, showProcesses, sort, ncol, status_filter=status_filter
        )

    def getProcessesForRestore(self):
        return self.logic.activeProject.repositoryContainer.processRepository.getProcessesForRestore()

    def getOperatingSystemsSummary(self):
        return self.logic.activeProject.repositoryContainer.hostRepository.getOperatingSystemsSummary()

    def getHostsForOperatingSystem(self, os_name: str):
        return self.logic.activeProject.repositoryContainer.hostRepository.getHostsByOperatingSystem(os_name)

    #################### PROCESSES ####################

    def checkProcessQueue(self):
        maxconcurrentscans = getattr(self.settings, 'general_max_concurrent_scans', 3)
        try:
            maxconcurrentscans = int(maxconcurrentscans)
        except Exception:
            maxconcurrentscans = 3
        
        log.debug(f"[Queue] maximum concurrent scans: {str(maxconcurrentscans)}")
        log.debug(f"[Queue] maximum concurrent processes: {str(self.settings.general_max_fast_processes)}")
        log.debug(f"[Queue] processes running: {str(self.fastProcessesRunning)}")
        log.debug(f"[Queue] processes waiting: {str(self.fastProcessQueue.qsize())}")
        
        from PyQt6.QtCore import QProcess
        
        # Count running nmap or other scan processes
        runningscans = sum(1 for p in self.processes if hasattr(p, 'name') and 'nmap' in str(p.name).lower())
        
        # Allow up to maxconcurrentscans nmap processes, and up to max_fast_processes for others
        while (self.fastProcessesRunning < int(self.settings.general_max_fast_processes) and 
               runningscans < maxconcurrentscans) or self.fastProcessQueue.empty():
            
            if self.fastProcessQueue.empty():
                log.debug("[Queue] Queue is empty, breaking")
                break
            
            nextproc = self.fastProcessQueue.get()
            log.debug(f"[Queue] Got process from queue: {nextproc.name if hasattr(nextproc, 'name') else 'unknown'}")
            
            # Check if it's a scan process
            isscan = hasattr(nextproc, 'name') and 'nmap' in str(nextproc.name).lower()
            
            # Check if process was cancelled
            if self.logic.activeProject.repositoryContainer.processRepository.isCancelledProcess(str(nextproc.id)):
                log.debug("[Queue] Process was canceled, checking queue again..")
                continue
            
            # Check ACTUALLY running processes, not just queue status
            actuallyrunning = [p for p in self.processes if p.state() == QProcess.ProcessState.Running]
            log.debug(f"[Queue] Actually running processes: {len(actuallyrunning)}")
            
            if len(actuallyrunning) == 0 and self.fastProcessQueue.empty():
                # Only stop timer if BOTH queue empty AND no processes actively running
                if self.processTableUiUpdateTimer.isActive():
                    log.debug("Halting process panel update timer as all processes are finished.")
                    self.processTableUiUpdateTimer.stop()
            elif len(actuallyrunning) > 0:
                # Ensure timer is running if we have active processes
                if not self.processTableUiUpdateTimer.isActive():
                    log.debug(f"Restarting process panel update timer - {len(actuallyrunning)} processes still running")
                    self.processTableUiUpdateTimer.start(1000)
            
            # Start the process
            if not self.logic.activeProject.repositoryContainer.processRepository.isCancelledProcess(str(nextproc.id)):
                log.debug("Running " + str(nextproc.command))
                
                # CRITICAL FIX: Don't clear if we're in append mode!
                log.debug(f"[Queue] Checking display for append mode...")
                log.debug(f"[Queue] Display object: {nextproc.display}")
                log.debug(f"[Queue] Display type: {type(nextproc.display)}")
                
                is_appending = nextproc.display.property("is_appending")
                log.debug(f"[Queue] is_appending property value: {is_appending} (type: {type(is_appending)})")
                
                if is_appending:
                    # Get current content length before NOT clearing
                    current_content = nextproc.display.toPlainText()
                    log.debug(f"[Queue] *** APPEND MODE ACTIVE *** - NOT clearing display")
                    log.debug(f"[Queue] Current display content length: {len(current_content)} chars")
                    log.debug(f"[Queue] First 200 chars of content: {current_content[:200]}")
                else:
                    log.debug(f"[Queue] NORMAL MODE - clearing display")
                    log.debug(f"[Queue] Display content before clear: {len(nextproc.display.toPlainText())} chars")
                    nextproc.display.clear()
                    log.debug(f"[Queue] Display cleared")
                
                self.processes.append(nextproc)
                self.fastProcessesRunning += 1
                if isscan:
                    runningscans += 1
                
                log.debug(f"[Queue] About to start process...")
                # Actually start the process
                nextproc.waitForFinished(10)
                formattedCommand = formatCommandQProcess(nextproc.command)
                log.debug(f"[Queue] Formatted command: {formattedCommand[0]}, args: {str(formattedCommand[1])[:100]}")
                
                nextproc.start(formattedCommand[0], formattedCommand[1])
                log.debug(f"[Queue] Process started with PID: {getPid(nextproc)}")
                
                self.logic.activeProject.repositoryContainer.processRepository.storeProcessRunningStatus(
                    nextproc.id, getPid(nextproc))
                
                # Debug: Verify content is still there after process start
                if is_appending:
                    after_start_content = nextproc.display.toPlainText()
                    log.debug(f"[Queue] After process start, display has {len(after_start_content)} chars")
                    if len(after_start_content) == 0:
                        log.error(f"[Queue] ERROR: Display was cleared despite append mode!")
                    else:
                        log.debug(f"[Queue] SUCCESS: Display content preserved in append mode")
            else:
                # Put back and break
                log.debug("[Queue] Process cancelled, putting back in queue")
                self.fastProcessQueue.put(nextproc)
                break




    def cancelProcess(self, dbId):
        log.info('Canceling process: ' + str(dbId))
        self.logic.activeProject.repositoryContainer.processRepository.storeProcessCancelStatus(
            str(dbId))  # mark it as cancelled
        self.updateUITimer.stop()
        self.updateUITimer.start(1500)                                  # update the interface soon

    def killProcess(self, pid, dbId):
        log.info('Killing process: ' + str(pid))
        self.logic.activeProject.repositoryContainer.processRepository.storeProcessKillStatus(str(dbId))
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            log.info('This process has already been terminated.')
        except:
            log.info("Unexpected error:", sys.exc_info()[0])

    def killRunningProcesses(self):
        """
        Safely terminate all running processes.
        """
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QProcess
        
        log.info('=== killRunningProcesses: START ===')
        log.info(f'Processes to kill: {len(self.processes)}')
        
        if not self.processes:
            log.info('No processes to kill')
            return
        
        # Create safe copy
        processes_copy = list(self.processes)
        
        for idx, p in enumerate(processes_copy):
            try:
                pid = getattr(p, 'id', 'unknown')
                state = p.state()
                
                log.info(f'Process {idx+1}/{len(processes_copy)} (ID: {pid}), State: {state}')
                
                # Skip if not running
                if state == QProcess.ProcessState.NotRunning:
                    log.info(f'  Process {pid} not running, skipping')
                    continue
                
                # Block signals
                log.info(f'  Blocking signals for process {pid}')
                p.blockSignals(True)
                
                # Disconnect all signals
                signals = ['finished', 'readyReadStandardOutput', 'errorOccurred', 'stateChanged', 'started']

                for sig_name in signals:
                    try:
                        sig = getattr(p, sig_name, None)
                        if sig:
                            sig.disconnect()
                            log.info(f'  Disconnected {sig_name}')
                    except (TypeError, RuntimeError):
                        pass
                
                # Terminate gracefully
                log.info(f'  Terminating process {pid}')
                p.terminate()
                
                # Wait for termination
                if p.waitForFinished(2000):
                    log.info(f'  Process {pid} terminated gracefully')
                else:
                    log.warning(f'  Process {pid} did not terminate, killing forcefully')
                    p.kill()
                    p.waitForFinished(1000)
                
                # Close process
                p.close()
                log.info(f'  Process {pid} closed')
                
            except Exception as e:
                log.error(f'Error killing process: {e}')
        
        # Clear process list
        self.processes.clear()
        
        # Process events
        QApplication.processEvents()
        
        log.info('=== killRunningProcesses: END ===')


    # this function creates a new process, runs the command and takes care of displaying the ouput. returns the PID
    # the last 3 parameters are only used when the command is a staged nmap
    def runCommand(self, *args, discovery=True, stage=0, stop=False, enable_ipv6=False):
        def handleProcStop(*vargs):
            updateElapsed.stop()
            self.processTimers[qProcess.id] = None
            procTime = timer.elapsed() / 1000
            qProcess.elapsed = procTime
            self.logic.activeProject.repositoryContainer.processRepository.storeProcessRunningElapsedTime(qProcess.id, procTime)

        def handleProcUpdate(*vargs):
            procTime = timer.elapsed() / 1000
            self.processMeasurements[getPid(qProcess)] = procTime

        name = args[0]
        tabTitle = args[1]
        hostIp = args[2]
        port = args[3]
        protocol = args[4]
        command = args[5]
        startTime = args[6]
        outputfile = args[7]
        textbox = args[8]
        
        log.debug(f"[runCommand] Called with:")
        log.debug(f"  name={name}, tabTitle={tabTitle}, hostIp={hostIp}, port={port}")
        log.debug(f"  textbox={textbox}, type={type(textbox)}")
        
        timer = QElapsedTimer()
        updateElapsed = QTimer()

        if 'python-script' in name:
            log.info(f'Running python script {name}')
            import subprocess
            import shlex
            script_path = None
            arg = None
            output = ""

            if "macvendors" in name.lower():
                script_path = "scripts/python/macvendors.py"
                mac = hostIp if hostIp and ":" in hostIp else ""
                if not mac and hasattr(self, "view"):
                    try:
                        selected_row = self.view.ui.HostsTableView.selectionModel().selectedRows()[0].row()
                        mac = self.view.HostsTableModel.getMacForRow(selected_row)
                    except Exception:
                        mac = ""
                arg = mac
            elif "shodan" in name.lower():
                script_path = "scripts/python/pyShodan.py"
                arg = hostIp

            if script_path and arg:
                try:
                    cmd = f"python3 {shlex.quote(script_path)} {shlex.quote(str(arg))}"
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
                except Exception as e:
                    log.exception(f"Error running script: {script_path} with arg: {arg}")
                    output = f"Error running script: {e}"
            else:
                output = "No valid script or argument found."

            if textbox:
                textbox.setPlainText(output)
            return 0

        self.logic.createFolderForTool(name)

        # FIX FOR BASH SCRIPTS: Check if script exists and wrap with stdbuf
        if 'bash' in str(command).lower() and '.sh' in str(command).lower():
            import re
            script_match = re.search(r'(\./scripts/[^\s]+\.sh)', str(command))
            if script_match:
                script_path = script_match.group(1)
                if not os.path.exists(script_path):
                    error_msg = f"ERROR: Script does not exist: {script_path}\n"
                    log.error(error_msg.strip())
                    if textbox and not sip.isdeleted(textbox):
                        textbox.setPlainText(error_msg)
                    return 0
                log.info(f"Detected bash script, wrapping with stdbuf for unbuffered output: {command}")
                command = f"stdbuf -o0 -e0 {command}"

        # Create MyQProcess
        qProcess = MyQProcess(name, tabTitle, hostIp, port, protocol, command, startTime, outputfile, textbox, self.settings)
        qProcess.sigHasMatch.connect(lambda matchStr: self.handleMatch(hostIp, tabTitle, matchStr))
        qProcess.started.connect(timer.start)
        qProcess.finished.connect(handleProcStop)
        updateElapsed.timeout.connect(handleProcUpdate)

        processRepository = self.logic.activeProject.repositoryContainer.processRepository
        dbId = str(processRepository.storeProcess(qProcess))
        textbox.setProperty('dbId', dbId)
        if textbox.parentWidget():
            textbox.parentWidget().setProperty('dbId', dbId)

        updateElapsed.start(1000)
        self.processTimers[qProcess.id] = updateElapsed
        self.processMeasurements[getPid(qProcess)] = 0

        log.info('Queuing: ' + str(command))
        self.fastProcessQueue.put(qProcess)
        self.checkProcessQueue()

        self.updateUITimer.stop()
        self.updateUITimer.start(900)

        # Set MergedChannels mode
        qProcess.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)

        # KEEP YOUR ORIGINAL HANDLER - it already works correctly!
        # insertPlainText preserves existing HTML formatting
        qProcess.readyReadStandardOutput.connect(lambda: qProcess.display.insertPlainText(
            str(qProcess.readAllStandardOutput().data().decode('ISO-8859-1'))))

        qProcess.sigHydra.connect(self.handleHydraFindings)
        qProcess.finished.connect(lambda: self.processFinished(qProcess))
        qProcess.errorOccurred.connect(lambda error, proc=qProcess: self.processCrashed(proc, error))

        log.info(f"runCommand called for stage {str(stage)}")
        
        if stage > 0 and stage < 6:
            log.info(f"runCommand connected for stage {str(stage)}")
            nextStage = stage + 1
            qProcess.finished.connect(
                lambda exitCode, exitStatus, host=str(hostIp).strip(), discovery_flag=discovery,
                next_stage=nextStage, enable_ipv6_flag=enable_ipv6, process_id=qProcess.id:
                self.runStagedNmap(
                    host,
                    discovery=discovery_flag,
                    stage=next_stage,
                    stop=processRepository.isKilledProcess(str(process_id)),
                    enable_ipv6=enable_ipv6_flag
                )
            )

        return getPid(qProcess)












    def runPython(self):
        textbox = self.view.createNewConsole("python")
        name = 'python'
        tabTitle = name
        hostIp = '127.0.0.1'
        port = '22'
        protocol = 'tcp'
        command = 'python3 --version'
        startTime = getTimestamp(True)
        outputfile = tempfile.NamedTemporaryFile(delete=False).name

        #new MyQProcess for the updated class
        qProcess = MyQProcess(name, tabTitle, hostIp, port, protocol, command, startTime, outputfile, textbox, self.settings)
        qProcess.sigHasMatch.connect(lambda matchStr: self.handleMatch(hostIp, tabTitle, matchStr))

        processRepository = self.logic.activeProject.repositoryContainer.processRepository
        textbox.setProperty('dbId', str(processRepository.storeProcess(qProcess)))

        log.info('Queuing: ' + str(command))
        self.fastProcessQueue.put(qProcess)

        self.checkProcessQueue()

        qProcess.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        qProcess.readyReadStandardOutput.connect(lambda: qProcess.display.insertPlainText(
            str(qProcess.readAllStandardOutput().data().decode('ISO-8859-1'))))

        qProcess.sigHydra.connect(self.handleHydraFindings)
        qProcess.finished.connect(lambda: self.processFinished(qProcess))
        qProcess.error.connect(lambda: self.processCrashed(qProcess))

        return getPid(qProcess)

    # recursive function used to run nmap in different stages for quick results
    def runStagedNmap(self, targetHosts, discovery=True, stage=1, stop=False, enable_ipv6=False):
        import os
        host_arg = str(targetHosts).strip()
        if not host_arg:
            log.warning(f"runStagedNmap stage {stage}: empty target host received, aborting stage.")
            return
        log.info(f"runStagedNmap called for stage {str(stage)} targeting {host_arg}")
        runningFolder = self.logic.activeProject.properties.runningFolder
        # Use the session directory for temp files
        session_path = getattr(self.logic.activeProject, "sessionFile", None)
        if session_path:
            session_dir = os.path.dirname(session_path)
        else:
            session_dir = runningFolder
        # Use the tool output directory directly, not a subdirectory
        tool_output_dir = session_dir
        if not stop:
            textbox = self.view.createNewTabForHost(host_arg, 'nmap (stage ' + str(stage) + ')', True)
            outputfile = os.path.join(tool_output_dir, f"{getTimestamp()}-nmapstage{str(stage)}")

            if stage == 1:
                stageData = self.settings.tools_nmap_stage1_ports
            elif stage == 2:
                stageData = self.settings.tools_nmap_stage2_ports
            elif stage == 3:
                stageData = self.settings.tools_nmap_stage3_ports
            elif stage == 4:
                stageData = self.settings.tools_nmap_stage4_ports
            elif stage == 5:
                stageData = self.settings.tools_nmap_stage5_ports
            elif stage == 6:
                stageData = self.settings.tools_nmap_stage6_ports
            stageDataSplit = str(stageData).split('|', maxsplit=1)
            stageOp = stageDataSplit[0]
            stageOpValues = stageDataSplit[1] if len(stageDataSplit) > 1 else ''
            log.debug(f"Stage {str(stage)} stageOp {str(stageOp)}")
            log.debug(f"Stage {str(stage)} stageOpValues {str(stageOpValues)}")

            if stageOp == "" or stageOp == "NOOP" or stageOp == "SKIP":
                log.debug(f"Skipping stage {str(stage)} as stageOp is {str(stageOp)}")
                return

            command_tokens = ["nmap"]
            if enable_ipv6:
                command_tokens.append("-6")

            if discovery:
                command_tokens.extend(["-T4", "-sV", "-sSU", "-O"])
            else:
                command_tokens.extend(["-Pn", "-sSU"])

            stage_command_tokens = list(command_tokens)
            if stageOp == 'PORTS':
                port_values = str(stageOpValues).strip()
                if port_values:
                    stage_command_tokens.extend(["-p", port_values])
                stage_command_tokens.extend(["-vvvv", host_arg, "--stats-every", "10s", "-oA", outputfile])
            elif stageOp == 'NSE':
                stage_command_tokens = ["nmap"]
                if enable_ipv6:
                    stage_command_tokens.append("-6")
                stage_command_tokens.extend([
                    "-sV",
                    f"--script={str(stageOpValues).strip()}",
                    "-vvvv",
                    host_arg,
                    "--stats-every",
                    "10s",
                    "-oA",
                    outputfile
                ])
            else:
                stage_command_tokens.extend(["-vvvv", host_arg, "--stats-every", "10s", "-oA", outputfile])

            command = ' '.join(token for token in stage_command_tokens if token)
            log.debug(f"Stage {str(stage)} command: {str(command)}")

            self.runCommand('nmap', 'nmap (stage ' + str(stage) + ')', host_arg, '', '', command,
                            getTimestamp(True), outputfile, textbox, discovery=discovery, stage=stage, stop=stop,
                            enable_ipv6=enable_ipv6)

    def importFinished(self):
        # if nmap import was the first action, we need to hide the overlay (note: we shouldn't need to do this
        # every time. this can be improved)
        self.view.displayAddHostsOverlay(False)
        # Ensure DB session is refreshed so new hosts are visible
        try:
            if hasattr(self.logic.activeProject, "database") and hasattr(self.logic.activeProject.database, "session"):
                session = self.logic.activeProject.database.session()
                session.expire_all()
        except Exception:
            log.exception(f"Failed to refresh DB session after import: error")
        # Ensure UI update is queued on main thread
        from PyQt6 import QtCore
        QtCore.QMetaObject.invokeMethod(self.view, "updateInterface", QtCore.Qt.ConnectionType.QueuedConnection)

    def screenshotFinished(self, ip, port, filename):
        log.info(f"---------------Screenshoot done. Args {ip}, {port}, {filename}")
        
        # FIRST: Check if this IP is blacklisted (host was deleted)
        if hasattr(self, 'screenshooter') and self.screenshooter and ip in self.screenshooter.blacklisted_ips:
            log.info(f"Ignoring screenshot for blacklisted IP {ip} - host was deleted")
            return
        
        # SECOND: Check if filename is empty (screenshot was cancelled or failed)
        if not filename or filename.strip() == "":
            log.info(f"Screenshot for {ip}:{port} was cancelled or failed - no file saved")
            return
        
        # THIRD: Verify host still exists in database before storing screenshot
        try:
            repositoryContainer = self.logic.activeProject.repositoryContainer
            from db.entities.host import hostObj
            session = repositoryContainer.hostRepository.dbAdapter.session()
            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            session.close()
            
            if not host:
                log.info(f"Host {ip} no longer exists in database - ignoring screenshot")
                return
        except Exception as e:
            log.error(f"Error checking if host exists: {e}")
            return
        
        # Finally: Store the screenshot and create UI tab
        outputFolder = self.logic.activeProject.properties.outputFolder
        dbId = self.logic.activeProject.repositoryContainer.processRepository.storeScreenshot(ip, port, filename)
        
        imageviewer = self.view.createNewTabForHost(ip, f'screenshot ({port}) [tcp]', True, '', f'{outputFolder}/screenshots/{filename}')
        imageviewer.setProperty('dbId', QVariant(str(dbId)))


    def processCrashed(self, proc, error=None):
        if proc is None or sip.isdeleted(proc):
            log.warning("Received crash notification for a destroyed process object.")
            return
        processRepository = self.logic.activeProject.repositoryContainer.processRepository
        processRepository.storeProcessCrashStatus(str(proc.id))
        log.info(f'Process {proc.id} Crashed!')
        qProcessOutput = ""
        if hasattr(proc, "display") and not sip.isdeleted(proc.display):
            try:
                qProcessOutput = "\n\t" + str(proc.display.toPlainText()).replace('\n', '').replace("b'", "")
            except Exception:
                qProcessOutput = ""
        # self.view.closeHostToolTab(self, index))
        self.view.findFinishedServiceTab(str(processRepository.getPIDByProcessId(str(proc.id))))
        log.info(f'Process {proc.id} Output: {qProcessOutput}')
        error_string = ""
        try:
            error_string = proc.errorString()
        except Exception:
            error_string = str(error) if error else ""
        log.info(f'Process {proc.id} Crash Output: {error_string}')
        # --- User notification for scan crash ---
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Scan Crashed")
        msg.setText(
            f"Scan process '{proc.name}' crashed!\n\nCommand: {proc.command}\n\nError: {error_string}\n\n"
            "Check the log for more details."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    # this function handles everything after a process ends
    # def processFinished(self, qProcess, crashed=False):
    def processFinished(self, qProcess):
        processRepository = self.logic.activeProject.repositoryContainer.processRepository
        try:
            if not processRepository.isKilledProcess(str(qProcess.id)):
                log.debug(
                    f'Process: {str(qProcess.id)}\n'
                    f'Command: {str(qProcess.command)}\n'
                    f'outputfile: {str(qProcess.outputfile)}'
                )
                if not qProcess.outputfile == '':
                    outputfile = winPath2Unix(qProcess.outputfile)
                    try:
                        self.logic.toolCoordinator.saveToolOutput(
                            self.logic.activeProject.properties.outputFolder, outputfile
                        )
                    except Exception:
                        log.exception(f"Error saving tool output: {outputfile}")
                    if 'nmap' in qProcess.command:
                        if qProcess.exitCode() == 0:
                            log.debug(f"qProcess.outputfile {str(outputfile)}")
                            log.debug(
                                f"self.logic.activeProject.properties.runningFolder "
                                f"{str(self.logic.activeProject.properties.runningFolder)}"
                            )
                            log.debug(
                                f"self.logic.activeProject.properties.outputFolder "
                                f"{str(self.logic.activeProject.properties.outputFolder)}"
                            )
                            newoutputfile = outputfile.replace(
                                self.logic.activeProject.properties.runningFolder,
                                self.logic.activeProject.properties.outputFolder
                            )
                            try:
                                self.nmapImporter.setFilename(str(newoutputfile) + '.xml')
                                self.nmapImporter.setOutput(str(qProcess.display.toPlainText()))
                                self.nmapImporter.start()
                            except Exception:
                                log.exception(f"Error starting nmapImporter for {newoutputfile}")
                    elif 'PythonScript' in qProcess.command:
                        pythonScript = str(qProcess.command).split(' ')[2]
                        print(f'PythonImporter running for script: {pythonScript}')
                        if qProcess.exitCode() == 0:
                            try:
                                self.pythonImporter.setOutput(str(qProcess.display.toPlainText()))
                                self.pythonImporter.setHostIp(str(qProcess.hostIp))
                                self.pythonImporter.setPythonScript(pythonScript)
                                self.pythonImporter.start()
                            except Exception:
                                log.exception(f"Error starting pythonImporter for {pythonScript}")
                log.info(f"Process {qProcess.id} is done!")

            try:
                processRepository.storeProcessOutput(str(qProcess.id), qProcess.display.toPlainText())
            except Exception:
                log.exception(f"Error storing process output for {qProcess.id}")

            try:
                self.view.refreshToolsTableModel()
                self.view.viewState.lazy_update_tools = True
            except Exception:
                log.exception("Failed to refresh tools table after process completion")

            if 'hydra' in qProcess.name:
                try:
                    self.view.findFinishedBruteTab(
                        str(processRepository.getPIDByProcessId(str(qProcess.id)))
                    )
                except Exception:
                    log.exception(f"Error updating brute tab for process {qProcess.id}")

            try:
                self.fastProcessesRunning -= 1
                self.checkProcessQueue()
                self.processes.remove(qProcess)
                self.updateUITimer.stop()
                self.updateUITimer.start(1000)
            except Exception:
                log.exception("Process Finished Cleanup Exception")
        except Exception:
            log.exception("Process Finished Exception")
            raise

    # when hydra finds valid credentials we need to save them and change the brute tab title to red
    def handleHydraFindings(self, bWidget, userlist, passlist):
        self.view.blinkBruteTab(bWidget)
        for username in userlist:
            self.logic.activeProject.properties.usernamesWordList.add(username)
        for password in passlist:
            self.logic.activeProject.properties.passwordWordList.add(password)

    # this function parses nmap's output looking for open ports to run automated attacks on
    def scheduler(self, parser, isNmapImport):
        try:
            if isNmapImport and self.settings.general_enable_scheduler_on_import == 'False':
                return
            if self.settings.general_enable_scheduler == 'True':
                log.info('Scheduler started!')

                for h in parser.getAllHosts():
                    try:
                        for p in h.all_ports():
                            try:
                                if p.state == 'open':
                                    s = p.getService()
                                    if not (s is None):
                                        self.runToolsFor(s.name, h.hostname, h.ip, p.portId, p.protocol)
                            except Exception as port_exc:
                                log.error(f"Scheduler error for port {getattr(p, 'portId', '?')}: {port_exc}")
                    except Exception as host_exc:
                        log.error(f"Scheduler error for host {getattr(h, 'ip', '?')}: {host_exc}")

                log.info('-----------------------------------------------')
            log.info('Scheduler ended!')
        except Exception as sched_exc:
            log.error(f"Scheduler encountered a fatal error: {sched_exc}")
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Scheduler Error")
            msg.setText(
                "An error occurred during scheduling of automated attacks.\n\n"
                f"Error: {sched_exc}\n\nCheck the log for more details."
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()

    #def findDuplicateTab(self, tabWidget, tabName):
    #    for i in range(tabWidget.count()):
    #        log.debug(f"Tab text for {str(i)}: {str(tabWidget.tabText(i))}")
    #        if tabWidget.tabText(i) == tabName:
    #            return True
    #    return False

    def runToolsFor(self, service, hostname, ip, port, protocol='tcp'):
        log.info('Running tools for: ' + service + ' on ' + ip + ':' + port)
        import os
        
        if service.endswith("?"):
            service = service[:-1]
        
        repo_container = self.logic.activeProject.repositoryContainer
        script_repo = getattr(repo_container, "scriptRepository", None)
        port_repo = getattr(repo_container, "portRepository", None)
        host_repo = getattr(repo_container, "hostRepository", None)
        
        for tool in self.settings.automatedAttacks:
            if service in tool[1].split(",") and protocol == tool[2]:
                if tool[0] == "screenshooter":
                    display_host, resolved_ip = self._resolve_host_and_ip(hostname or ip)
                    url = f"{display_host}:{port}"
                    
                    screenshots_dir = os.path.join(self.logic.activeProject.properties.outputFolder, "screenshots")
                    deterministic_screenshot = f"{resolved_ip}-{port}-screenshot.png"
                    screenshot_exists = False
                    
                    if os.path.isdir(screenshots_dir):
                        if deterministic_screenshot in os.listdir(screenshots_dir):
                            screenshot_exists = True
                    
                    if screenshot_exists:
                        log.info(f"Skipping screenshot for {resolved_ip}:{port} (already exists)")
                    else:
                        log.info("Screenshooter of URL: %s" % str(url))
                        self.screenshooter.addToQueue(resolved_ip, port, url)
                        self.screenshooter.start()
                
                else:
                    for a in self.settings.portActions:
                        if tool[0] == a[1]:
                            tabTitle = a[1] + " (" + port + "/" + protocol + ")"
                            log.info(f"[runToolsFor] Processing tool '{a[1]}', original tab title: '{tabTitle}'")
                            textbox = None
                            
                            # Check if script already ran
                            skip_script = False
                            if script_repo and port_repo and host_repo:
                                db_host = host_repo.getHostByIP(ip)
                                db_port = None
                                if db_host:
                                    db_port = port_repo.getPortByHostIdAndPort(db_host.id, port, protocol)
                                
                                if db_host and db_port:
                                    existing_scripts = script_repo.getScriptsByPortId(db_port.id)
                                    for s in existing_scripts:
                                        if hasattr(s, "scriptId") and s.scriptId == a[1]:
                                            skip_script = True
                                            log.info(f"[runToolsFor] Script '{a[1]}' found in database")
                                            break
                            
                            if skip_script:
                                log.info(f"[runToolsFor] Script was run before, checking for existing tab")
                                existing_tab_index, existing_run_num = self.findExistingTabIndex(
                                    self.view.ui.ServicesTabWidget,
                                    tabTitle
                                )
                                log.info(f"[runToolsFor] Script check result: index={existing_tab_index}, run={existing_run_num}")
                                
                                if existing_tab_index is not None:
                                    action = self.promptDuplicateToolAction(a[1], tabTitle)
                                    
                                    if action == 'cancel' or action == 'skip':
                                        log.info(f"User cancelled/skipped re-running script '{a[1]}' for {ip}:{port}")
                                        break
                                    
                                    elif action == 'append':
                                        log.info(f"[APPEND MODE] Appending script output to existing tab at index {existing_tab_index}")
                                        existing_widget = self.view.ui.ServicesTabWidget.widget(existing_tab_index)
                                        
                                        if hasattr(existing_widget, 'display'):
                                            textbox = existing_widget.display
                                        else:
                                            from PyQt6.QtWidgets import QTextEdit
                                            textbox = existing_widget.findChild(QTextEdit)
                                        
                                        if textbox:
                                            # Get existing content FIRST
                                            existing_html = textbox.toHtml()
                                            
                                            # Create separator as HTML with proper formatting
                                            separator_html = "<br><br><pre>"
                                            separator_html += "=" * 80 + "<br>\n"
                                            separator_html += f"[{getTimestamp()}] Re-running script: {a[1]}<br>\n"
                                            separator_html += "=" * 80 + "<br>\n"
                                            separator_html += "</pre><br>"
                                            
                                            # Combine existing + separator
                                            combined_html = existing_html.replace('</body>', f'{separator_html}</body>')
                                            
                                            # Set the combined content
                                            textbox.setHtml(combined_html)
                                            
                                            log.info(f"[APPEND MODE] Added separator, content now: {len(textbox.toPlainText())} chars")
                                            
                                            # NOW mark it for append mode (so checkProcessQueue won't clear it)
                                            textbox.setProperty("is_appending", True)
                                            
                                            # Switch to tab
                                            self.view.ui.ServicesTabWidget.setCurrentIndex(existing_tab_index)
                                            skip_script = False
                                        else:
                                            log.error(f"[runToolsFor] Could not find textbox in existing widget!")
                                            skip_script = False
                                            textbox = None
                                    
                                    else:  # new_tab
                                        log.info(f"[runToolsFor] Creating new numbered tab for script")
                                        highest_script_run = self.getHighestRunNumber(
                                            self.view.ui.ServicesTabWidget, 
                                            tabTitle
                                        )
                                        
                                        if highest_script_run is None:
                                            log.error(f"[runToolsFor] ERROR: getHighestRunNumber returned None! Using 0")
                                            highest_script_run = 0
                                        
                                        new_script_run = highest_script_run + 1
                                        tabTitle = self.formatTabTitleWithRunNumber(tabTitle, new_script_run)
                                        log.info(f"Creating new script tab '{tabTitle}' (run #{new_script_run})")
                                        skip_script = False
                                        textbox = None
                                else:
                                    log.warning(f"Script {a[1]} database record exists but no tab found")
                                    skip_script = False
                            
                            if skip_script:
                                log.info(f"Skipping script {a[1]} for {ip}:{port}/{protocol}")
                                break
                            
                            # Check for duplicate tab if textbox not set
                            if textbox is None:
                                log.debug(f"[runToolsFor] Textbox is None, checking for duplicate tab")
                                existing_tab_index, existing_run_num = self.findExistingTabIndex(
                                    self.view.ui.ServicesTabWidget, 
                                    tabTitle
                                )
                                log.debug(f"[runToolsFor] Duplicate check: index={existing_tab_index}, run={existing_run_num}")
                                
                                if existing_tab_index is not None:
                                    action = self.promptDuplicateToolAction(tool[0], tabTitle)
                                    
                                    if action == 'cancel' or action == 'skip':
                                        log.info(f"User cancelled/skipped re-running tool '{tool[0]}' for {ip}:{port}")
                                        break
                                    
                                    elif action == 'append':
                                        log.info(f"[APPEND MODE] Appending output to existing tab '{tabTitle}'")
                                        existing_widget = self.view.ui.ServicesTabWidget.widget(existing_tab_index)
                                        
                                        if hasattr(existing_widget, 'display'):
                                            textbox = existing_widget.display
                                        else:
                                            from PyQt6.QtWidgets import QTextEdit
                                            textbox = existing_widget.findChild(QTextEdit)
                                        
                                        if textbox:
                                            # Get existing content FIRST
                                            existing_html = textbox.toHtml()
                                            
                                            # Create separator as HTML with proper formatting
                                            separator_html = "<br><br><pre>"
                                            separator_html += "=" * 80 + "<br>\n"
                                            separator_html += f"[{getTimestamp()}] Re-running: {tool[0]}<br>\n"
                                            separator_html += "=" * 80 + "<br>\n"
                                            separator_html += "</pre><br>"
                                            
                                            # Combine existing + separator
                                            combined_html = existing_html.replace('</body>', f'{separator_html}</body>')
                                            
                                            # Set the combined content
                                            textbox.setHtml(combined_html)
                                            
                                            log.debug(f"[APPEND MODE] Added separator, content now: {len(textbox.toPlainText())} chars")
                                            
                                            # NOW mark it for append mode (so checkProcessQueue won't clear it)
                                            textbox.setProperty("is_appending", True)
                                            
                                            # Switch to tab
                                            self.view.ui.ServicesTabWidget.setCurrentIndex(existing_tab_index)
                                        else:
                                            log.error(f"[runToolsFor] Could not find textbox, creating new tab")
                                            tab = self.view.ui.HostsTabWidget.tabText(self.view.ui.HostsTabWidget.currentIndex())
                                            textbox = self.view.createNewTabForHost(ip, tabTitle, not (tab == "Hosts"))
                                    
                                    else:  # new_tab
                                        highest_run = self.getHighestRunNumber(self.view.ui.ServicesTabWidget, tabTitle)
                                        
                                        if highest_run is None:
                                            log.error(f"[runToolsFor] ERROR: getHighestRunNumber returned None! Using 0")
                                            highest_run = 0
                                        
                                        new_run_number = highest_run + 1
                                        tabTitle = self.formatTabTitleWithRunNumber(tabTitle, new_run_number)
                                        log.info(f"Creating new tab '{tabTitle}' (run #{new_run_number})")
                                        tab = self.view.ui.HostsTabWidget.tabText(self.view.ui.HostsTabWidget.currentIndex())
                                        textbox = self.view.createNewTabForHost(ip, tabTitle, not (tab == "Hosts"))
                                        
                                        if textbox and hasattr(textbox, 'append'):
                                            textbox.append(f"[Run #{new_run_number} - {getTimestamp()}]")
                                            textbox.append("="*80 + "\n")
                                else:
                                    log.debug(f"[runToolsFor] No existing tab, creating new")
                                    tab = self.view.ui.HostsTabWidget.tabText(self.view.ui.HostsTabWidget.currentIndex())
                                    textbox = self.view.createNewTabForHost(ip, tabTitle, not (tab == "Hosts"))
                            
                            # Prepare command
                            outputfile = os.path.join(
                                self.logic.activeProject.properties.runningFolder,
                                f"{getTimestamp()}-{a[1]}-{ip}-{port}"
                            )
                            
                            outputfile = os.path.normpath(outputfile).replace("\\", "/")
                            command = str(a[2])
                            command = command.replace('[IP]', ip).replace('[PORT]', port).replace('[OUTPUT]', outputfile)
                            
                            log.debug(f"[runToolsFor] About to call runCommand")
                            log.debug(f"[runToolsFor]   Textbox: {textbox}")
                            log.info(f"[runToolsFor]   Command: {command}")
                            
                            # Run command
                            self.runCommand(tool[0], tabTitle, ip, port, protocol, command,
                                            getTimestamp(True),
                                            outputfile,
                                            textbox)
                            
                            log.debug(f"[runToolsFor] runCommand called successfully")
                            break









    def addPortToHost(self, host_ip, port_data):
        """
        Manually add a port to an existing host.
        :param host_ip: IP address of the host (string)
        :param port_data: dict with keys 'port', 'state', 'protocol'
        """
        host = self._resolve_host_record(host_ip)
        if not host:
            log.error(f"Host '{host_ip}' not found.")
            return

        # Create and add the port
        try:
            port_id = str(port_data.get('port', '')).strip()
            protocol = port_data.get('protocol', '').strip()
            state = port_data.get('state', '').strip()
            host_id = host.id
            new_port = portObj(port_id, protocol, state, host_id)
            session = self.logic.activeProject.database.session()
            try:
                session.add(new_port)
                session.commit()
            finally:
                session.close()
            host_label = getattr(host, 'hostname', '') or getattr(host, 'ip', '')
            log.info(f"Added port {port_id}/{protocol} ({state}) to host {host_label}")
            self.view.updateInterface()
        except Exception as e:
            log.error(f"Failed to add port to host {host_ip}: {e}")

    def handleMatch(self, hostIp, tabTitle, matchStr):
        if hasattr(self.view, 'viewState') and hasattr(self.view.viewState, 'hostTabs'):
            if hostIp in self.view.viewState.hostTabs:
                tabs = self.view.viewState.hostTabs[hostIp]
                for tab in tabs:
                    if tab.objectName() == tabTitle:
                        tab.setProperty('matches', matchStr)
                        self.view.updateTabHighlight(hostIp, tabTitle)
                        break


    def cleanupDeletedHost(self, ip):
        """
        Delayed cleanup to catch any processes that finished after host deletion.
        """
        from sqlalchemy import text
        
        log.info("=" * 80)
        log.info(f"=== CLEANUP VALIDATION START for {ip} ===")
        log.info("=" * 80)
        
        repositoryContainer = self.logic.activeProject.repositoryContainer
        
        # STEP 1: Check if host still exists
        try:
            from db.entities.host import hostObj
            session = repositoryContainer.hostRepository.dbAdapter.session()
            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            session.close()
            
            if host:
                log.warning(f"  - WARNING: Host {ip} still exists in database!")
            else:
                log.info(f"  - Host {ip} confirmed deleted from database")
        except Exception as e:
            log.error(f"  - Error checking host: {e}")
        
        # STEP 2: Delete any orphaned processes
        try:
            all_processes = repositoryContainer.processRepository.getProcesses(filters='', showProcesses='', sort='desc', ncol='id')
            orphaned = [p for p in all_processes if getattr(p, 'hostIp', None) == ip]
            
            if orphaned:
                log.warning(f"  - Found {len(orphaned)} orphaned process records for deleted host {ip}")
                for proc in orphaned:
                    proc_id = getattr(proc, 'id', None)
                    if proc_id:
                        try:
                            session = repositoryContainer.processRepository.dbAdapter.session()
                            session.execute(text("DELETE FROM process_output WHERE id = :id"), {"id": str(proc_id)})
                            session.execute(text("DELETE FROM process WHERE id = :id"), {"id": str(proc_id)})
                            session.commit()
                            session.close()
                            log.info(f"    * Deleted orphaned process {proc_id}")
                        except Exception as e:
                            log.error(f"    * Failed to delete process {proc_id}: {e}")
            else:
                log.info(f"  - No orphaned processes found for {ip}")
        except Exception as e:
            log.error(f"  - Error cleaning orphaned processes: {e}")
        
        # STEP 3: Delete any other orphaned data
        try:
            from db.entities.port import portObj
            session = repositoryContainer.portRepository.dbAdapter.session()
            orphaned_ports = session.query(portObj).filter_by(hostId=ip).all()
            if orphaned_ports:
                log.warning(f"  - Found {len(orphaned_ports)} orphaned ports")
                for port in orphaned_ports:
                    session.delete(port)
                session.commit()
            session.close()
        except Exception as e:
            log.error(f"  - Error cleaning orphaned ports: {e}")
        
        # STEP 4: Remove IP from screenshooter blacklist
        try:
            if hasattr(self, 'screenshooter') and self.screenshooter:
                removed = self.screenshooter.removeFromBlacklist(ip)
                if removed:
                    log.info(f"  - Removed {ip} from screenshooter blacklist")
                else:
                    log.info(f"  - {ip} was not in screenshooter blacklist")
        except Exception as e:
            log.error(f"  - Error removing from blacklist: {e}")
        
        # STEP 5: Force UI refresh
        log.info("  - Forcing UI refresh...")
        self.view.updateInterface()
        
        # STEP 6: Clear tab highlights AGAIN after UI refresh
        log.info("  - Clearing tab highlights after refresh...")
        try:
            self.view.clearAllTabHighlights()
            log.info("  - Tab highlights cleared after refresh")
        except Exception as e:
            log.error(f"  - Error clearing tab highlights: {e}")
        
        log.info("=" * 80)
        log.info(f"=== CLEANUP VALIDATION END for {ip} ===")
        log.info("=" * 80)


    def cleanupPurgedHost(self, ip):
        """
        Delayed cleanup to catch any processes or orphaned data after host purge.
        Unlike cleanupDeletedHost, this keeps the host record intact.
        """
        from sqlalchemy import text

        log.info("=" * 80)
        log.info(f"=== CLEANUP VALIDATION START for purged host {ip} ===")
        log.info("=" * 80)

        repositoryContainer = self.logic.activeProject.repositoryContainer

        # STEP 1: Verify host still exists (it should!)
        try:
            from db.entities.host import hostObj
            session = repositoryContainer.hostRepository.dbAdapter.session()
            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            session.close()

            if host:
                log.info(f"  ✓ Host {ip} still exists in database (GOOD - host should be preserved)")
            else:
                log.error(f"  ❌ ERROR: Host {ip} was deleted! Should have been preserved!")
        except Exception as e:
            log.error(f"  - Error checking host: {e}")

        # STEP 2: Delete any orphaned processes
        try:
            all_processes = repositoryContainer.processRepository.getProcesses(filters='', showProcesses='', sort='desc', ncol='id')
            orphaned = [p for p in all_processes if getattr(p, 'hostIp', None) == ip]

            if orphaned:
                log.warning(f"  - Found {len(orphaned)} orphaned process records for purged host {ip}")
                for proc in orphaned:
                    proc_id = getattr(proc, 'id', None)
                    if proc_id:
                        try:
                            session = repositoryContainer.processRepository.dbAdapter.session()
                            session.execute(text("DELETE FROM process_output WHERE id = :id"), {"id": str(proc_id)})
                            session.execute(text("DELETE FROM process WHERE id = :id"), {"id": str(proc_id)})
                            session.commit()
                            session.close()
                            log.info(f"    * Deleted orphaned process {proc_id}")
                        except Exception as e:
                            log.error(f"    * Failed to delete process {proc_id}: {e}")
            else:
                log.info(f"  ✓ No orphaned processes found for {ip}")
        except Exception as e:
            log.error(f"  - Error cleaning orphaned processes: {e}")

        # STEP 3: Verify all ports are deleted
        try:
            from db.entities.port import portObj
            session = repositoryContainer.portRepository.dbAdapter.session()
            remaining_ports = session.query(portObj).join(hostObj).filter(hostObj.ip == str(ip)).all()
            if remaining_ports:
                log.warning(f"  ❌ Found {len(remaining_ports)} orphaned ports after purge")
                for port in remaining_ports:
                    log.warning(f"    - Port {port.portId}/{port.protocol} (ID: {port.id})")
                    session.delete(port)
                session.commit()
                log.info(f"  - Deleted {len(remaining_ports)} orphaned ports")
            else:
                log.info(f"  ✓ No orphaned ports found")
            session.close()
        except Exception as e:
            log.error(f"  - Error cleaning orphaned ports: {e}")

        # STEP 4: Remove IP from screenshooter blacklist
        try:
            if hasattr(self, 'screenshooter') and self.screenshooter:
                removed = self.screenshooter.removeFromBlacklist(ip)
                if removed:
                    log.info(f"  - Removed {ip} from screenshooter blacklist")
                else:
                    log.info(f"  - {ip} was not in screenshooter blacklist")
        except Exception as e:
            log.error(f"  - Error removing from blacklist: {e}")

        # STEP 5: Force UI refresh
        log.info("  - Forcing UI refresh...")
        self.view.updateInterface()

        # STEP 6: Clear tab highlights AGAIN after UI refresh
        log.info("  - Clearing tab highlights after refresh...")
        try:
            self.view.clearAllTabHighlights()
            log.info("  - Tab highlights cleared after refresh")
        except Exception as e:
            log.error(f"  - Error clearing tab highlights: {e}")

        log.info("=" * 80)
        log.info(f"=== CLEANUP VALIDATION END for purged host {ip} ===")
        log.info("=" * 80)

    def verifyHostDeleted(self, ip):
        """
        Comprehensive verification that host and ALL related data is deleted.
        Call this after deletion to confirm complete removal.
        """
        from sqlalchemy import text
        log.info("=" * 80)
        log.info(f"VERIFICATION START - Checking if {ip} is completely deleted")
        log.info("=" * 80)
        
        repositoryContainer = self.logic.activeProject.repositoryContainer
        issues_found = []
        
        # 1. Check Host Table
        try:
            from db.entities.host import hostObj
            session = repositoryContainer.hostRepository.dbAdapter.session
            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            session.close()
            
            if host:
                issues_found.append(f"❌ FAILED: Host {ip} still exists in host table (ID: {host.id})")
                log.error(f"❌ Host {ip} still exists in database!")
            else:
                log.info(f"✓ Host {ip} NOT found in host table (GOOD)")
        except Exception as e:
            log.error(f"❌ Error checking host table: {e}")
            issues_found.append(f"Error checking host: {e}")
        
        # 2. Check Ports Table
        try:
            from db.entities.port import portObj
            session = repositoryContainer.portRepository.dbAdapter.session
            
            # Direct SQL query to find orphaned ports
            result = session.execute(
                text("SELECT COUNT(*) as cnt, GROUP_CONCAT(id) as ids FROM portObj WHERE hostId IN (SELECT id FROM hostObj WHERE ip = :ip)"),
                {"ip": str(ip)}
            ).first()
            
            count = result[0] if result else 0
            port_ids = result[1] if result and len(result) > 1 else ""
            
            if count > 0:
                issues_found.append(f"❌ FAILED: {count} orphaned ports found (IDs: {port_ids})")
                log.error(f"❌ Found {count} orphaned ports for {ip}: {port_ids}")
            else:
                log.info(f"✓ No orphaned ports found for {ip} (GOOD)")
            
            session.close()
        except Exception as e:
            log.error(f"❌ Error checking ports: {e}")
            issues_found.append(f"Error checking ports: {e}")
        
        # 3. Check Scripts Table
        try:
            from db.entities.l1script import l1ScriptObj
            session = repositoryContainer.scriptRepository.dbAdapter.session
            
            result = session.execute(
                text("SELECT COUNT(*) as cnt FROM l1ScriptObj WHERE hostId IN (SELECT id FROM hostObj WHERE ip = :ip)"),
                {"ip": str(ip)}
            ).first()
            
            count = result[0] if result else 0
            
            if count > 0:
                issues_found.append(f"❌ FAILED: {count} orphaned scripts found")
                log.error(f"❌ Found {count} orphaned scripts for {ip}")
            else:
                log.info(f"✓ No orphaned scripts found for {ip} (GOOD)")
            
            session.close()
        except Exception as e:
            log.error(f"❌ Error checking scripts: {e}")
            issues_found.append(f"Error checking scripts: {e}")
        
        # 4. Check Process Table
        try:
            session = repositoryContainer.processRepository.dbAdapter.session
            
            result = session.execute(
                text("SELECT COUNT(*) as cnt, GROUP_CONCAT(id) as ids FROM process WHERE hostIp = :ip"),
                {"ip": str(ip)}
            ).first()
            
            count = result[0] if result else 0
            proc_ids = result[1] if result and len(result) > 1 else ""
            
            if count > 0:
                issues_found.append(f"❌ FAILED: {count} orphaned process records (IDs: {proc_ids})")
                log.error(f"❌ Found {count} orphaned processes for {ip}: {proc_ids}")
            else:
                log.info(f"✓ No orphaned process records for {ip} (GOOD)")
            
            session.close()
        except Exception as e:
            log.error(f"❌ Error checking processes: {e}")
            issues_found.append(f"Error checking processes: {e}")
        
        # 5. Check ProcessOutput Table
        try:
            session = repositoryContainer.processRepository.dbAdapter.session
            
            result = session.execute(
                text("SELECT COUNT(*) as cnt FROM process_output WHERE id IN (SELECT id FROM process WHERE hostIp = :ip)"),
                {"ip": str(ip)}
            ).first()
            
            count = result[0] if result else 0
            
            if count > 0:
                issues_found.append(f"❌ FAILED: {count} orphaned processoutput records")
                log.error(f"❌ Found {count} orphaned processoutput records for {ip}")
            else:
                log.info(f"✓ No orphaned processoutput records for {ip} (GOOD)")
            
            session.close()
        except Exception as e:
            log.error(f"❌ Error checking processoutput: {e}")
            issues_found.append(f"Error checking processoutput: {e}")
        
        # 6. Check CVE Table
        try:
            from db.entities.cve import cve
            session = repositoryContainer.cveRepository.dbAdapter.session
            
            result = session.execute(
                text("SELECT COUNT(*) as cnt FROM cve WHERE hostId IN (SELECT id FROM hostObj WHERE ip = :ip)"),
                {"ip": str(ip)}
            ).first()
            
            count = result[0] if result else 0
            
            if count > 0:
                issues_found.append(f"❌ FAILED: {count} orphaned CVE records")
                log.error(f"❌ Found {count} orphaned CVE records for {ip}")
            else:
                log.info(f"✓ No orphaned CVE records for {ip} (GOOD)")
            
            session.close()
        except Exception as e:
            log.error(f"❌ Error checking CVEs: {e}")
            issues_found.append(f"Error checking CVEs: {e}")
        
        # 7. Check Note Table (check both numeric ID and IP string)
        try:
            from db.entities.note import note
            session = repositoryContainer.noteRepository.dbAdapter.session
            
            # Check for notes with numeric hostId
            result = session.execute(
                text("SELECT COUNT(*) as cnt FROM note WHERE hostId IN (SELECT id FROM hostObj WHERE ip = :ip)"),
                {"ip": str(ip)}
            ).first()
            
            count_numeric = result[0] if result else 0
            
            # Check for notes with IP string in hostId field
            result2 = session.execute(
                text("SELECT COUNT(*) as cnt FROM note WHERE hostId = :ip"),
                {"ip": str(ip)}
            ).first()
            
            count_string = result2[0] if result2 else 0
            count_total = count_numeric + count_string
            
            if count_total > 0:
                issues_found.append(f"❌ FAILED: {count_total} orphaned note records (numeric: {count_numeric}, string: {count_string})")
                log.error(f"❌ Found {count_total} orphaned note records for {ip}")
            else:
                log.info(f"✓ No orphaned note records for {ip} (GOOD)")
            
            session.close()
        except Exception as e:
            log.error(f"❌ Error checking notes: {e}")
            issues_found.append(f"Error checking notes: {e}")
        
        # 8. Check In-Memory Processes List
        try:
            running_processes = [p for p in self.processes if hasattr(p, 'hostIp') and p.hostIp == ip]
            
            if running_processes:
                issues_found.append(f"❌ FAILED: {len(running_processes)} processes still in self.processes")
                log.error(f"❌ Found {len(running_processes)} processes still in memory for {ip}")
                for proc in running_processes:
                    procid = getattr(proc, 'id', 'unknown')
                    log.error(f"  - Process ID: {procid}")
            else:
                log.info(f"✓ No processes in self.processes for {ip} (GOOD)")
        except Exception as e:
            log.error(f"❌ Error checking in-memory processes: {e}")
            issues_found.append(f"Error checking in-memory processes: {e}")
        
        # 9. Check Process Queue
        try:
            import queue
            temp_queue = queue.Queue()
            queued_count = 0
            
            while not self.fastProcessQueue.empty():
                try:
                    proc = self.fastProcessQueue.get_nowait()
                    if hasattr(proc, 'hostIp') and proc.hostIp == ip:
                        queued_count += 1
                    else:
                        temp_queue.put(proc)
                except:
                    break
            
            # Restore queue
            while not temp_queue.empty():
                try:
                    self.fastProcessQueue.put(temp_queue.get_nowait())
                except:
                    break
            
            if queued_count > 0:
                issues_found.append(f"❌ FAILED: {queued_count} processes still queued")
                log.error(f"❌ Found {queued_count} queued processes for {ip}")
            else:
                log.info(f"✓ No queued processes for {ip} (GOOD)")
        except Exception as e:
            log.error(f"❌ Error checking process queue: {e}")
            issues_found.append(f"Error checking process queue: {e}")
        
        # 10. Check Screenshooter Blacklist (FIXED attribute name)
        try:
            if hasattr(self, 'screenshooter') and self.screenshooter:
                # Check correct attribute name - it's blacklisted_ips, not blacklistedips
                if hasattr(self.screenshooter, 'blacklisted_ips'):
                    if ip in self.screenshooter.blacklisted_ips:
                        issues_found.append(f"❌ FAILED: IP still in screenshooter blacklist")
                        log.error(f"❌ IP {ip} still in screenshooter blacklist")
                    else:
                        log.info(f"✓ IP {ip} not in screenshooter blacklist (GOOD)")
                else:
                    log.info(f"✓ Screenshooter blacklist attribute not found (GOOD)")
            else:
                log.info(f"✓ No screenshooter to check (GOOD)")
        except Exception as e:
            log.error(f"❌ Error checking screenshooter: {e}")
            issues_found.append(f"Error checking screenshooter: {e}")
        
        # Final Summary
        log.info("=" * 80)
        if issues_found:
            log.error(f"❌❌❌ VERIFICATION FAILED - {len(issues_found)} issues found:")
            for issue in issues_found:
                log.error(f"  {issue}")
            log.error(f"❌❌❌ Host {ip} was NOT completely deleted!")
        else:
            log.info(f"✓✓✓ VERIFICATION PASSED - Host {ip} is completely deleted!")
            log.info("✓✓✓ All database tables and in-memory structures are clean!")
        log.info("=" * 80)
        
        return len(issues_found) == 0




    def verifyHostPurged(self, ip, hostid):
        """
        Comprehensive verification that all results are purged but host remains.
        """
        from sqlalchemy import text
        log.info("=" * 80)
        log.info(f"VERIFICATION START - Checking if {ip} results are completely purged")
        log.info("=" * 80)

        repositoryContainer = self.logic.activeProject.repositoryContainer
        issues_found = []

        # 1. Check Host Table (should EXIST)
        try:
            from db.entities.host import hostObj
            session = repositoryContainer.hostRepository.dbAdapter.session()
            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            session.close()

            if host:
                log.info(f"✓ Host {ip} still exists in host table (GOOD - host preserved)")
            else:
                issues_found.append(f"❌ FAILED: Host {ip} was deleted! Should have been preserved")
                log.error(f"❌ Host {ip} was deleted when it should have been kept!")
        except Exception as e:
            log.error(f"❌ Error checking host table: {e}")
            issues_found.append(f"Error checking host: {e}")

        # 2. Check Ports Table (should be EMPTY for this host)
        try:
            from db.entities.port import portObj
            session = repositoryContainer.portRepository.dbAdapter.session()

            # Get host ID first
            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            if host:
                ports = session.query(portObj).filter_by(hostId=host.id).all()

                if len(ports) > 0:
                    issues_found.append(f"❌ FAILED: {len(ports)} ports still exist after purge")
                    log.error(f"❌ Found {len(ports)} remaining ports for {ip}")
                    for port in ports:
                        log.error(f"    - Port {port.portId}/{port.protocol} (ID: {port.id})")
                else:
                    log.info(f"✓ No ports found for {ip} (GOOD - all purged)")

            session.close()
        except Exception as e:
            log.error(f"❌ Error checking ports: {e}")
            issues_found.append(f"Error checking ports: {e}")

        # 3. Check Scripts Table (should be EMPTY for this host)
        try:
            from db.entities.l1script import l1ScriptObj
            session = repositoryContainer.scriptRepository.dbAdapter.session()

            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            if host:
                scripts = session.query(l1ScriptObj).filter_by(hostId=host.id).all()

                if len(scripts) > 0:
                    issues_found.append(f"❌ FAILED: {len(scripts)} scripts still exist after purge")
                    log.error(f"❌ Found {len(scripts)} remaining scripts for {ip}")
                else:
                    log.info(f"✓ No scripts found for {ip} (GOOD - all purged)")

            session.close()
        except Exception as e:
            log.error(f"❌ Error checking scripts: {e}")
            issues_found.append(f"Error checking scripts: {e}")

        # 4. Check Process Table (should be EMPTY for this host)
        try:
            all_processes = repositoryContainer.processRepository.getProcesses(filters='', showProcesses='', sort='desc', ncol='id')
            remaining = [p for p in all_processes if getattr(p, 'hostIp', None) == ip]

            if len(remaining) > 0:
                issues_found.append(f"❌ FAILED: {len(remaining)} processes still exist after purge")
                log.error(f"❌ Found {len(remaining)} remaining processes for {ip}")
                for proc in remaining:
                    log.error(f"    - Process ID: {getattr(proc, 'id', 'unknown')}")
            else:
                log.info(f"✓ No processes found for {ip} (GOOD - all purged)")
        except Exception as e:
            log.error(f"❌ Error checking processes: {e}")
            issues_found.append(f"Error checking processes: {e}")

        # 5. Check Notes Table (should STILL EXIST - notes are preserved)
        try:
            from db.entities.note import note
            session = repositoryContainer.noteRepository.dbAdapter.session()

            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            if host:
                # Check for notes with numeric hostId
                notes_numeric = session.query(note).filter_by(hostId=host.id).all()

                # Check for notes with IP string in hostId field (legacy format)
                result = session.execute(
                    text("SELECT COUNT(*) as cnt FROM note WHERE hostId = :ip"),
                    {"ip": str(ip)}
                ).first()
                notes_string_count = result[0] if result else 0

                total_notes = len(notes_numeric) + notes_string_count

                if total_notes > 0:
                    log.info(f"✓ Found {total_notes} notes for {ip} (GOOD - notes preserved)")
                else:
                    log.info(f"✓ No notes found for {ip} (acceptable)")

            session.close()
        except Exception as e:
            log.error(f"❌ Error checking notes: {e}")
            issues_found.append(f"Error checking notes: {e}")

        # 6. Check CVE Table (should be EMPTY for this host)
        try:
            from db.entities.cve import cve
            session = repositoryContainer.cveRepository.dbAdapter.session()

            host = session.query(hostObj).filter_by(ip=str(ip)).first()
            if host:
                cves = session.query(cve).filter_by(hostId=host.id).all()

                if len(cves) > 0:
                    issues_found.append(f"❌ FAILED: {len(cves)} CVEs still exist after purge")
                    log.error(f"❌ Found {len(cves)} remaining CVEs for {ip}")
                    for cve_obj in cves:
                        log.error(f"    - CVE: {getattr(cve_obj, 'name', 'unknown')}")
                else:
                    log.info(f"✓ No CVEs found for {ip} (GOOD - all purged)")

            session.close()
        except Exception as e:
            log.error(f"❌ Error checking CVEs: {e}")
            issues_found.append(f"Error checking CVEs: {e}")

        # Summary
        log.info("=" * 80)
        if issues_found:
            log.error("❌ PURGE VERIFICATION FAILED!")
            log.error(f"Found {len(issues_found)} issues:")
            for issue in issues_found:
                log.error(f"  - {issue}")
        else:
            log.info("✓✓✓ PURGE VERIFICATION PASSED!")
            log.info(f"Host {ip} preserved, all results successfully purged")
        log.info("=" * 80)

    def dumpDatabaseAfterDelete(self, deleted_ip):
        """
        Print ALL database records after a host deletion.
        This provides complete visibility into what remains in the database.
        """
        from sqlalchemy import text
        log.info("\n" + "=" * 100)
        log.info(f"DATABASE DUMP AFTER DELETING HOST: {deleted_ip}")
        log.info("=" * 100 + "\n")
        
        repositoryContainer = self.logic.activeProject.repositoryContainer
        session = repositoryContainer.hostRepository.dbAdapter.session
        
        try:
            # 1. DUMP HOSTS TABLE
            log.info("─" * 100)
            log.info("TABLE: hostObj")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM hostObj"))
            hosts = result.fetchall()
            keys = result.keys()
            
            if hosts:
                log.info(f"Total hosts: {len(hosts)}")
                log.info("")
                for idx, host in enumerate(hosts, 1):
                    log.info(f"Host #{idx}:")
                    for key, value in zip(keys, host):
                        log.info(f"  {key}: {value}")
                    log.info("")
                    # HIGHLIGHT if deleted IP still exists
                    host_dict = dict(zip(keys, host))
                    if str(host_dict.get('ip', '')) == str(deleted_ip):
                        log.error(f"  ⚠️  WARNING: DELETED HOST {deleted_ip} STILL EXISTS!")
                        log.error(f"  ⚠️  Host ID: {host_dict.get('id')}")
                        log.error("")
            else:
                log.info("✓ No hosts in database")
            log.info("")
            
            # 2. DUMP PORTS TABLE
            log.info("─" * 100)
            log.info("TABLE: portObj")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM portObj"))
            ports = result.fetchall()
            keys = result.keys()
            
            if ports:
                log.info(f"Total ports: {len(ports)}")
                log.info("")
                
                # Check for orphaned ports
                orphaned_ports = []
                for idx, port in enumerate(ports, 1):
                    port_dict = dict(zip(keys, port))
                    hostId = port_dict.get('hostId')
                    
                    # Check if this port's host still exists
                    host_check = session.execute(
                        text("SELECT ip FROM hostObj WHERE id = :hostid"),
                        {"hostid": hostId}
                    ).first()
                    
                    log.info(f"Port #{idx}:")
                    for key, value in zip(keys, port):
                        log.info(f"  {key}: {value}")
                    
                    if host_check:
                        log.info(f"  → Belongs to host: {host_check[0]}")
                        if str(host_check[0]) == str(deleted_ip):
                            log.error(f"  ⚠️  WARNING: Port belongs to DELETED host {deleted_ip}!")
                            orphaned_ports.append(port_dict.get('id'))
                    else:
                        log.error(f"  ⚠️  WARNING: ORPHANED PORT - No matching host found!")
                        orphaned_ports.append(port_dict.get('id'))
                    log.info("")
                
                if orphaned_ports:
                    log.error(f"⚠️  FOUND {len(orphaned_ports)} ORPHANED PORTS: {orphaned_ports}")
                    log.error("")
            else:
                log.info("✓ No ports in database")
            log.info("")
            
            # 3. DUMP SCRIPTS TABLE
            log.info("─" * 100)
            log.info("TABLE: l1ScriptObj")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM l1ScriptObj"))
            scripts = result.fetchall()
            keys = result.keys()
            
            if scripts:
                log.info(f"Total scripts: {len(scripts)}")
                log.info("")
                
                orphaned_scripts = []
                for idx, script in enumerate(scripts, 1):
                    script_dict = dict(zip(keys, script))
                    hostId = script_dict.get('hostId')
                    
                    log.info(f"Script #{idx}:")
                    for key, value in zip(keys, script):
                        # Truncate long script output
                        if key == 'scriptOutput' and value and len(str(value)) > 100:
                            log.info(f"  {key}: {str(value)[:100]}... (truncated)")
                        else:
                            log.info(f"  {key}: {value}")
                    
                    # Check if host exists
                    if hostId:
                        host_check = session.execute(
                            text("SELECT ip FROM hostObj WHERE id = :hostid"),
                            {"hostid": hostId}
                        ).first()
                        
                        if host_check:
                            log.info(f"  → Belongs to host: {host_check[0]}")
                            if str(host_check[0]) == str(deleted_ip):
                                log.error(f"  ⚠️  WARNING: Script belongs to DELETED host {deleted_ip}!")
                                orphaned_scripts.append(script_dict.get('id'))
                        else:
                            log.error(f"  ⚠️  WARNING: ORPHANED SCRIPT - No matching host found!")
                            orphaned_scripts.append(script_dict.get('id'))
                    log.info("")
                
                if orphaned_scripts:
                    log.error(f"⚠️  FOUND {len(orphaned_scripts)} ORPHANED SCRIPTS: {orphaned_scripts}")
                    log.error("")
            else:
                log.info("✓ No scripts in database")
            log.info("")
            
            # 4. DUMP PROCESS TABLE
            log.info("─" * 100)
            log.info("TABLE: process")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM process"))
            processes = result.fetchall()
            keys = result.keys()
            
            if processes:
                log.info(f"Total processes: {len(processes)}")
                log.info("")
                
                orphaned_procs = []
                for idx, proc in enumerate(processes, 1):
                    proc_dict = dict(zip(keys, proc))
                    hostIp = proc_dict.get('hostIp')
                    
                    log.info(f"Process #{idx}:")
                    for key, value in zip(keys, proc):
                        log.info(f"  {key}: {value}")
                    
                    if str(hostIp) == str(deleted_ip):
                        log.error(f"  ⚠️  WARNING: Process belongs to DELETED host {deleted_ip}!")
                        orphaned_procs.append(proc_dict.get('id'))
                    log.info("")
                
                if orphaned_procs:
                    log.error(f"⚠️  FOUND {len(orphaned_procs)} ORPHANED PROCESSES: {orphaned_procs}")
                    log.error("")
            else:
                log.info("✓ No processes in database")
            log.info("")
            
            # 5. DUMP PROCESS_OUTPUT TABLE
            log.info("─" * 100)
            log.info("TABLE: process_output")
            log.info("─" * 100)
            result = session.execute(text("SELECT id, LENGTH(output) as output_length FROM process_output"))
            outputs = result.fetchall()
            
            if outputs:
                log.info(f"Total process outputs: {len(outputs)}")
                log.info("")
                
                orphaned_outputs = []
                for idx, output in enumerate(outputs, 1):
                    output_id = output[0]
                    output_len = output[1]
                    
                    log.info(f"ProcessOutput #{idx}:")
                    log.info(f"  id: {output_id}")
                    log.info(f"  output_length: {output_len} bytes")
                    
                    # Check if process exists
                    proc_check = session.execute(
                        text("SELECT hostIp FROM process WHERE id = :id"),
                        {"id": output_id}
                    ).first()
                    
                    if proc_check:
                        log.info(f"  → Process hostIp: {proc_check[0]}")
                        if str(proc_check[0]) == str(deleted_ip):
                            log.error(f"  ⚠️  WARNING: Output belongs to process for DELETED host {deleted_ip}!")
                            orphaned_outputs.append(output_id)
                    else:
                        log.error(f"  ⚠️  WARNING: ORPHANED OUTPUT - No matching process found!")
                        orphaned_outputs.append(output_id)
                    log.info("")
                
                if orphaned_outputs:
                    log.error(f"⚠️  FOUND {len(orphaned_outputs)} ORPHANED OUTPUTS: {orphaned_outputs}")
                    log.error("")
            else:
                log.info("✓ No process outputs in database")
            log.info("")
            
            # 6. DUMP CVE TABLE
            log.info("─" * 100)
            log.info("TABLE: cve")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM cve"))
            cves = result.fetchall()
            keys = result.keys()
            
            if cves:
                log.info(f"Total CVEs: {len(cves)}")
                log.info("")
                
                orphaned_cves = []
                for idx, cve in enumerate(cves, 1):
                    cve_dict = dict(zip(keys, cve))
                    hostId = cve_dict.get('hostId')
                    
                    log.info(f"CVE #{idx}:")
                    for key, value in zip(keys, cve):
                        log.info(f"  {key}: {value}")
                    
                    # Check if host exists
                    if hostId:
                        host_check = session.execute(
                            text("SELECT ip FROM hostObj WHERE id = :hostid"),
                            {"hostid": hostId}
                        ).first()
                        
                        if host_check:
                            log.info(f"  → Belongs to host: {host_check[0]}")
                            if str(host_check[0]) == str(deleted_ip):
                                log.error(f"  ⚠️  WARNING: CVE belongs to DELETED host {deleted_ip}!")
                                orphaned_cves.append(cve_dict.get('id'))
                        else:
                            log.error(f"  ⚠️  WARNING: ORPHANED CVE - No matching host found!")
                            orphaned_cves.append(cve_dict.get('id'))
                    log.info("")
                
                if orphaned_cves:
                    log.error(f"⚠️  FOUND {len(orphaned_cves)} ORPHANED CVES: {orphaned_cves}")
                    log.error("")
            else:
                log.info("✓ No CVEs in database")
            log.info("")
            
            # 7. DUMP NOTE TABLE
            log.info("─" * 100)
            log.info("TABLE: note")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM note"))
            notes = result.fetchall()
            keys = result.keys()
            
            if notes:
                log.info(f"Total notes: {len(notes)}")
                log.info("")
                
                orphaned_notes = []
                for idx, note in enumerate(notes, 1):
                    note_dict = dict(zip(keys, note))
                    hostId = note_dict.get('hostId')
                    
                    log.info(f"Note #{idx}:")
                    for key, value in zip(keys, note):
                        log.info(f"  {key}: {value}")
                    
                    # Check if host exists
                    if hostId:
                        host_check = session.execute(
                            text("SELECT ip FROM hostObj WHERE id = :hostid"),
                            {"hostid": hostId}
                        ).first()
                        
                        if host_check:
                            log.info(f"  → Belongs to host: {host_check[0]}")
                            if str(host_check[0]) == str(deleted_ip):
                                log.error(f"  ⚠️  WARNING: Note belongs to DELETED host {deleted_ip}!")
                                orphaned_notes.append(note_dict.get('id'))
                        else:
                            log.error(f"  ⚠️  WARNING: ORPHANED NOTE - No matching host found!")
                            orphaned_notes.append(note_dict.get('id'))
                    log.info("")
                
                if orphaned_notes:
                    log.error(f"⚠️  FOUND {len(orphaned_notes)} ORPHANED NOTES: {orphaned_notes}")
                    log.error("")
            else:
                log.info("✓ No notes in database")
            log.info("")
            
            # 8. DUMP SERVICE TABLE (for completeness)
            log.info("─" * 100)
            log.info("TABLE: serviceObj")
            log.info("─" * 100)
            result = session.execute(text("SELECT * FROM serviceObj"))
            services = result.fetchall()
            keys = result.keys()
            
            if services:
                log.info(f"Total services: {len(services)}")
                log.info("")
                for idx, service in enumerate(services, 1):
                    log.info(f"Service #{idx}:")
                    for key, value in zip(keys, service):
                        log.info(f"  {key}: {value}")
                    log.info("")
            else:
                log.info("✓ No services in database")
            log.info("")
            
        except Exception as e:
            log.error(f"Error dumping database: {e}")
            import traceback
            log.error(traceback.format_exc())
        finally:
            session.close()
        
        log.info("=" * 100)
        log.info(f"END DATABASE DUMP FOR DELETED HOST: {deleted_ip}")
        log.info("=" * 100 + "\n")

    def dumpDatabaseAfterPurge(self, purged_ip):
        """
        Print relevant database records after a host purge.
        Focus on the purged host to verify it still exists with no associated data.
        """
        from sqlalchemy import text
        log.info("\n" + "=" * 100)
        log.info(f"DATABASE DUMP AFTER PURGING HOST: {purged_ip}")
        log.info("=" * 100 + "\n")

        repositoryContainer = self.logic.activeProject.repositoryContainer
        session = repositoryContainer.hostRepository.dbAdapter.session()

        try:
            # 1. Check the purged host
            log.info("─" * 100)
            log.info(f"PURGED HOST: {purged_ip}")
            log.info("─" * 100)

            from db.entities.host import hostObj
            host = session.query(hostObj).filter_by(ip=str(purged_ip)).first()

            if host:
                log.info(f"✓ Host {purged_ip} exists (GOOD)")
                log.info(f"  Host ID: {host.id}")
                log.info(f"  Hostname: {getattr(host, 'hostname', 'N/A')}")
                log.info(f"  OS: {getattr(host, 'os', 'N/A')}")
                log.info(f"  Checked: {getattr(host, 'checked', 'N/A')}")
            else:
                log.error(f"❌ Host {purged_ip} does NOT exist (BAD - should be preserved!)")
            log.info("")

            # 2. Check ports for this host
            log.info("─" * 100)
            log.info(f"PORTS for {purged_ip}")
            log.info("─" * 100)

            if host:
                from db.entities.port import portObj
                ports = session.query(portObj).filter_by(hostId=host.id).all()

                if ports:
                    log.error(f"❌ Found {len(ports)} ports (BAD - should be purged)")
                    for port in ports:
                        log.error(f"  - Port {port.portId}/{port.protocol} - {port.state}")
                else:
                    log.info(f"✓ No ports found (GOOD - all purged)")
            log.info("")

            # 3. Check scripts for this host
            log.info("─" * 100)
            log.info(f"SCRIPTS for {purged_ip}")
            log.info("─" * 100)

            if host:
                from db.entities.l1script import l1ScriptObj
                scripts = session.query(l1ScriptObj).filter_by(hostId=host.id).all()

                if scripts:
                    log.error(f"❌ Found {len(scripts)} scripts (BAD - should be purged)")
                else:
                    log.info(f"✓ No scripts found (GOOD - all purged)")
            log.info("")

            # 4. Check processes for this host
            log.info("─" * 100)
            log.info(f"PROCESSES for {purged_ip}")
            log.info("─" * 100)

            all_processes = repositoryContainer.processRepository.getProcesses(filters='', showProcesses='', sort='desc', ncol='id')
            host_processes = [p for p in all_processes if getattr(p, 'hostIp', None) == purged_ip]

            if host_processes:
                log.error(f"❌ Found {len(host_processes)} processes (BAD - should be purged)")
                for proc in host_processes:
                    log.error(f"  - Process ID: {getattr(proc, 'id', 'unknown')}")
            else:
                log.info(f"✓ No processes found (GOOD - all purged)")
            log.info("")

            # 5. Check CVEs for this host
            log.info("─" * 100)
            log.info(f"CVEs for {purged_ip}")
            log.info("─" * 100)

            if host:
                from db.entities.cve import cve
                cves = session.query(cve).filter_by(hostId=host.id).all()

                if cves:
                    log.error(f"❌ Found {len(cves)} CVEs (BAD - should be purged)")
                    for cve_obj in cves:
                        log.error(f"  - CVE: {getattr(cve_obj, 'name', 'unknown')}")
                else:
                    log.info(f"✓ No CVEs found (GOOD - all purged)")
            log.info("")

            # 6. Check notes for this host (should still exist)
            log.info("─" * 100)
            log.info(f"NOTES for {purged_ip} (PRESERVED)")
            log.info("─" * 100)

            if host:
                from db.entities.note import note
                notes = session.query(note).filter_by(hostId=host.id).all()

                if notes:
                    log.info(f"✓ Found {len(notes)} notes (GOOD - notes preserved)")
                    for note_obj in notes:
                        note_text = getattr(note_obj, 'text', 'unknown')
                        log.info(f"  - Note: {note_text[:80]}...")
                else:
                    log.info(f"✓ No notes found (acceptable)")
            log.info("")

            session.close()

        except Exception as e:
            log.error(f"Error during database dump: {e}")
            session.close()

        log.info("=" * 100)
        log.info(f"DATABASE DUMP COMPLETE")
        log.info("=" * 100 + "\n")

    def findExistingTabIndex(self, tabWidget, baseTabTitle):
        """
        Find the index of an existing tab by base name.
        Returns tuple: (index, run_number) or (None, 0) if not found
        """
        import re
        
        log.debug(f"[findExistingTabIndex] Searching for tab: '{baseTabTitle}'")
        log.debug(f"[findExistingTabIndex] Total tabs in widget: {tabWidget.count()}")
        
        # Extract base tool name and port from title
        base_pattern = r'^(.+?)(->(\d+))?\s+(\(.+\))$'
        
        base_match = re.match(base_pattern, baseTabTitle)
        if not base_match:
            log.debug(f"[findExistingTabIndex] Could not parse title with pattern, looking for exact match")
            for i in range(tabWidget.count()):
                tab_text = tabWidget.tabText(i)
                log.debug(f"[findExistingTabIndex]   Tab {i}: '{tab_text}'")
                if tab_text == baseTabTitle:
                    log.debug(f"[findExistingTabIndex] Found exact match at index {i}")
                    return (i, 1)
            log.debug(f"[findExistingTabIndex] No match found")
            return (None, 0)
        
        base_tool = base_match.group(1).strip()
        base_port = base_match.group(4)
        log.debug(f"[findExistingTabIndex] Parsed - tool: '{base_tool}', port: '{base_port}'")
        
        # Search for any tab with this tool and port
        search_pattern = f"^{re.escape(base_tool)}(?:->\\d+)?\\s+{re.escape(base_port)}$"
        log.debug(f"[findExistingTabIndex] Search pattern: {search_pattern}")
        
        for i in range(tabWidget.count()):
            tabText = tabWidget.tabText(i)
            log.debug(f"[findExistingTabIndex]   Checking tab {i}: '{tabText}'")
            if re.match(search_pattern, tabText):
                run_match = re.search(r'->(\d+)', tabText)
                run_num = int(run_match.group(1)) if run_match else 1
                log.debug(f"[findExistingTabIndex] MATCH found at index {i}, run number: {run_num}")
                return (i, run_num)
        
        log.debug(f"[findExistingTabIndex] No matching tab found")
        return (None, 0)


    def getHighestRunNumber(self, tabWidget, baseTabTitle):
        """
        Find the highest run number for tabs with the given base title.
        Returns the highest run number found (starting at 1 for first run).
        """
        import re
        
        log.debug(f"[getHighestRunNumber] Finding highest run for: '{baseTabTitle}'")
        
        # Extract base tool name and port from title
        base_pattern = r'^(.+?)(->(\d+))?\s+(\(.+\))$'
        base_match = re.match(base_pattern, baseTabTitle)
        
        if not base_match:
            log.warning(f"[getHighestRunNumber] Could not parse title, returning 0")
            return 0
        
        base_tool = base_match.group(1).strip()
        base_port = base_match.group(4)
        log.debug(f"[getHighestRunNumber] Parsed - tool: '{base_tool}', port: '{base_port}'")
        
        highest_run = 0
        search_pattern = f"^{re.escape(base_tool)}(?:->(\\d+))?\\s+{re.escape(base_port)}$"
        
        for i in range(tabWidget.count()):
            tabText = tabWidget.tabText(i)
            match = re.match(search_pattern, tabText)
            
            if match:
                run_num_match = re.search(r'->(\d+)', tabText)
                run_num = int(run_num_match.group(1)) if run_num_match else 1
                log.debug(f"[getHighestRunNumber]   Tab {i} '{tabText}' -> run number: {run_num}")
                highest_run = max(highest_run, run_num)
        
        log.debug(f"[getHighestRunNumber] Highest run number found: {highest_run}")
        return highest_run


    def formatTabTitleWithRunNumber(self, baseTabTitle, runNumber):
        """
        Format a tab title with a run number in the format: "tool->N (port/protocol)"
        """
        import re
        
        log.debug(f"[formatTabTitleWithRunNumber] Input: '{baseTabTitle}', run: {runNumber}")
        
        base_pattern = r'^(.+?)(->(\d+))?\s+(\(.+\))$'
        match = re.match(base_pattern, baseTabTitle)
        
        if not match:
            log.warning(f"[formatTabTitleWithRunNumber] Could not parse title, using fallback")
            if runNumber > 1:
                result = f"{baseTabTitle}->{runNumber}"
            else:
                result = baseTabTitle
            log.debug(f"[formatTabTitleWithRunNumber] Output (fallback): '{result}'")
            return result
        
        base_tool = match.group(1).strip()
        base_port = match.group(4)
        
        if runNumber == 1:
            result = f"{base_tool} {base_port}"
        else:
            result = f"{base_tool}->{runNumber} {base_port}"
        
        log.debug(f"[formatTabTitleWithRunNumber] Output: '{result}'")
        return result


    def promptDuplicateToolAction(self, toolName, tabTitle):
        """
        Prompt user to choose action when a tool/script has already been run.
        Returns: 'append', 'new_tab', 'skip', or 'cancel'
        
        Behavior is controlled by settings.general_tool_duplication setting:
        - 'append': Always append to existing tab
        - 'newTab': Always create new numbered tab
        - 'skip': Skip re-running (don't execute again)
        - 'askMe': Show dialog to ask user (default)
        """
        # DEBUG: Log ALL settings attributes
        log.debug(f"[promptDuplicateToolAction] DEBUG: All settings attributes: {dir(self.settings)}")
        
        # DEBUG: Log attributes that contain 'tool' or 'dup'
        tool_attrs = [attr for attr in dir(self.settings) if 'tool' in attr.lower() or 'dup' in attr.lower()]
        log.debug(f"[promptDuplicateToolAction] DEBUG: Attributes with 'tool' or 'dup': {tool_attrs}")
        
        # Check the setting - try multiple possible attribute names
        duplication_mode = None
        
        # Try different possible attribute name formats
        possible_names = [
            'general_tool_duplication',
            'generaltoolduplication', 
            'generalToolDuplication',
            'tool_duplication',
            'toolduplication',
            'toolDuplication'
        ]
        
        for attr_name in possible_names:
            if hasattr(self.settings, attr_name):
                duplication_mode = getattr(self.settings, attr_name, 'askMe')
                log.debug(f"[promptDuplicateToolAction] Found setting attribute '{attr_name}': '{duplication_mode}'")
                break
        
        # Fallback to askMe if no setting found
        if duplication_mode is None:
            duplication_mode = 'askMe'
            log.debug(f"[promptDuplicateToolAction] No setting found, defaulting to 'askMe'")
        
        # Normalize the mode value (handle case variations)
        duplication_mode = str(duplication_mode).strip()
        log.debug(f"[promptDuplicateToolAction] Final duplication mode: '{duplication_mode}'")
        
        # If mode is set to a specific action, return directly without showing dialog
        if duplication_mode.lower() == 'append':
            log.debug(f"[promptDuplicateToolAction] Auto-returning 'append' based on setting")
            return 'append'
        elif duplication_mode.lower() == 'newtab':
            log.debug(f"[promptDuplicateToolAction] Auto-returning 'new_tab' based on setting")
            return 'new_tab'
        elif duplication_mode.lower() == 'skip':
            log.debug(f"[promptDuplicateToolAction] Auto-returning 'skip' based on setting")
            return 'skip'
        
        # Otherwise show the dialog (askMe mode or any other value)
        log.debug(f"[promptDuplicateToolAction] Mode is '{duplication_mode}', showing dialog for user choice")
        
        from PyQt6.QtWidgets import QMessageBox
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Tool/Script Already Run")
        msg.setText(f"The tool/script '{toolName}' has already been executed for this target.")
        msg.setInformativeText("How would you like to proceed?")
        
        appendBtn = msg.addButton("Append to Existing Tab", QMessageBox.ButtonRole.AcceptRole)
        newTabBtn = msg.addButton("Create New Tab", QMessageBox.ButtonRole.ActionRole)
        skipBtn = msg.addButton("Skip (Don't Run)", QMessageBox.ButtonRole.DestructiveRole)
        cancelBtn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        msg.setDefaultButton(appendBtn)
        msg.exec()
        
        clickedButton = msg.clickedButton()
        
        if clickedButton == appendBtn:
            log.debug(f"[promptDuplicateToolAction] User chose: APPEND")
            return 'append'
        elif clickedButton == newTabBtn:
            log.debug(f"[promptDuplicateToolAction] User chose: NEW TAB")
            return 'new_tab'
        elif clickedButton == skipBtn:
            log.debug(f"[promptDuplicateToolAction] User chose: SKIP")
            return 'skip'
        else:
            log.debug(f"[promptDuplicateToolAction] User chose: CANCEL")
            return 'cancel'





