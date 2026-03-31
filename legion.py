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

Author(s): Shane Scott (sscott@shanewilliamscott.com), Dmitriy Dubson (d.dubson@gmail.com)
"""
import shutil

from app.ApplicationInfo import getConsoleLogo
from app.ProjectManager import ProjectManager
from app.logging.legionLog import getStartupLogger, getDbLogger, getAppLogger
from app.shell.DefaultShell import DefaultShell
from app.tools.nmap.DefaultNmapExporter import DefaultNmapExporter
from db.RepositoryFactory import RepositoryFactory
from app.tools.ToolCoordinator import ToolCoordinator
from app.logic import Logic
import os
import sys
import subprocess

startupLog = getStartupLogger()
startupLog.info("=" * 80)
startupLog.info("LEGION APPLICATION STARTED")
startupLog.info("=" * 80)


def doPathSetup():
    import os
    if not os.path.isdir(os.path.expanduser("~/.local/share/legion/backup")):
        os.makedirs(os.path.expanduser("~/.local/share/legion/backup"))

    if not os.path.exists(os.path.expanduser('~/.local/share/legion/legion.conf')):
        shutil.copy('./legion.conf', os.path.expanduser('~/.local/share/legion/legion.conf'))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Start Legion")
    parser.add_argument("--mcp-server", action="store_true", help="Start MCP server for AI integration")
    parser.add_argument("--headless", action="store_true", help="Run Legion in headless (CLI) mode")
    parser.add_argument("--input-file", type=str, help="Text file with targets (hostnames, subnets, IPs, etc.)")
    parser.add_argument("--discovery", action="store_true", help="Enable host discovery (default: enabled)")
    parser.add_argument("--staged-scan", action="store_true", help="Enable staged scan")
    parser.add_argument("--output-file", type=str, help="Output file (.legion or .json)")
    parser.add_argument(
        "--run-actions",
        action="store_true",
        help="Run scripted actions/automated attacks after scan/import"
    )
    parser.add_argument("--web", action="store_true", help="Start Legion web UI (Flask)")
    parser.add_argument("--port", type=int, default=5000, help="Port for the web UI (default: 5000)")
    parser.add_argument("--no-prompt", action="store_true",
                        help="Skip interactive startup prompts (continue alongside other instances)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Skip auto-opening Firefox (headless / CI use)")
    args = parser.parse_args()

    if args.mcp_server:
        # Start MCP server as a subprocess (separate stdio)
        mcp_proc = subprocess.Popen(
            [sys.executable, "app/mcpServer.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    from colorama import init
    from termcolor import cprint
    init(strip=not sys.stdout.isatty())
    cprint(getConsoleLogo())

    doPathSetup()

    if args.headless:
        # --- HEADLESS CLI MODE ---
        from app.cli_utils import import_targets_from_textfile, run_nmap_scan
        from app.importers.NmapImporter import NmapImporter
        import time

        shell = DefaultShell()
        dbLog = getDbLogger()
        appLogger = getAppLogger()
        repositoryFactory = RepositoryFactory(dbLog)
        projectManager = ProjectManager(shell, repositoryFactory, appLogger)
        nmapExporter = DefaultNmapExporter(shell, appLogger)
        toolCoordinator = ToolCoordinator(shell, nmapExporter)
        logic = Logic(shell, projectManager, toolCoordinator)
        startupLog.info("Creating temporary project for headless mode...")
        logic.createNewTemporaryProject()

        # Import targets from input file
        if not args.input_file or not os.path.isfile(args.input_file):
            print("Error: --input-file is required and must exist in headless mode.", file=sys.stderr)
            sys.exit(1)
        session = logic.activeProject.database.session()
        hostRepository = logic.activeProject.repositoryContainer.hostRepository
        import_targets_from_textfile(session, hostRepository, args.input_file)

        # Run nmap scan if requested
        nmap_xml = None
        if args.staged_scan or args.discovery:
            # Build targets string for nmap (space-separated)
            targets = []
            with open(args.input_file, "r") as f:
                for line in f:
                    t = line.strip()
                    if t and not t.startswith("#"):
                        targets.append(t)
            targets_str = " ".join(targets)
            output_prefix = os.path.join(logic.activeProject.properties.runningFolder, f"cli-nmap-{int(time.time())}")
            nmap_xml = run_nmap_scan(
                targets_str,
                output_prefix,
                discovery=args.discovery,
                staged=args.staged_scan
            )
            # Import nmap XML results into the project
            nmapImporter = NmapImporter(None, hostRepository)
            nmapImporter.setDB(logic.activeProject.database)
            nmapImporter.setHostRepository(hostRepository)
            nmapImporter.setFilename(nmap_xml)
            nmapImporter.setOutput("")
            nmapImporter.run()

        # Run scripted actions/automated attacks if requested
        if args.run_actions:
            # Placeholder: will call logic.run_scripted_actions() after implementation
            print("Running scripted actions/automated attacks (CLI)...")
            logic.run_scripted_actions()

        # Export results
        if args.output_file:
            if args.output_file.endswith(".json"):
                # Export directly from the current activeProject (no temp .legion file)
                import json
                import base64
                hostRepository = logic.activeProject.repositoryContainer.hostRepository
                hosts = hostRepository.getAllHostObjs()
                hosts_data = []
                for host in hosts:
                    host_dict = host.__dict__.copy()
                    host_dict.pop('_sa_instance_state', None)
                    # Ports/services for this host
                    try:
                        ports = logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(host.id)
                    except Exception:
                        ports = []
                    ports_data = []
                    for port in ports:
                        port_dict = port.__dict__.copy()
                        port_dict.pop('_sa_instance_state', None)
                        # Service for this port
                        try:
                            service = (
                                logic.activeProject.repositoryContainer.serviceRepository.getServiceById(port.serviceId)
                                if hasattr(port, 'serviceId') and port.serviceId
                                else None
                            )
                        except Exception:
                            service = None
                        if service:
                            service_dict = service.__dict__.copy()
                            service_dict.pop('_sa_instance_state', None)
                            port_dict['service'] = service_dict
                        # Scripts for this port
                        try:
                            scripts = (
                                logic.activeProject.repositoryContainer.scriptRepository.getScriptsByPortId(port.id)
                                if hasattr(logic.activeProject.repositoryContainer, 'scriptRepository')
                                else []
                            )
                        except Exception:
                            scripts = []
                        scripts_data = []
                        for script in scripts:
                            script_dict = script.__dict__.copy()
                            script_dict.pop('_sa_instance_state', None)
                            scripts_data.append(script_dict)
                        port_dict['scripts'] = scripts_data
                        ports_data.append(port_dict)
                    host_dict['ports'] = ports_data
                    # Notes for this host
                    try:
                        note = logic.activeProject.repositoryContainer.noteRepository.getNoteByHostId(host.id)
                        host_dict['note'] = note.text if note else ""
                    except Exception:
                        host_dict['note'] = ""
                    # CVEs for this host
                    try:
                        cves = logic.activeProject.repositoryContainer.cveRepository.getCVEsByHostIP(host.ip)
                    except Exception:
                        cves = []
                    cves_data = []
                    for cve in cves:
                        cve_dict = cve.__dict__.copy()
                        cve_dict.pop('_sa_instance_state', None)
                        cves_data.append(cve_dict)
                    host_dict['cves'] = cves_data
                    hosts_data.append(host_dict)
                # Gather screenshots
                screenshots_dir = os.path.join(logic.activeProject.properties.outputFolder, "screenshots")
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
                                screenshots_data[fname] = f"ERROR: {e}"
                export = {
                    "hosts": hosts_data,
                    "screenshots": screenshots_data
                }
                with open(args.output_file, "w", encoding="utf-8") as f:
                    json.dump(export, f, indent=2)
                print(f"Exported results as JSON to {args.output_file}")
            elif args.output_file.endswith(".legion"):
                # Save project as .legion file
                projectManager.saveProjectAs(logic.activeProject, args.output_file, replace=1, projectType="legion")
                print(f"Exported project as .legion to {args.output_file}")
            else:
                print("Error: --output-file must end with .json or .legion", file=sys.stderr)
                sys.exit(1)
        else:
            print("No --output-file specified, skipping export.")

        print("Headless Legion run complete.")
        sys.exit(0)

    # ── Multi-instance helpers ────────────────────────────────────────────────

    def _find_other_legion_servers(current_port):
        """Scan /proc for other legion.py --web processes on a different port."""
        my_pid = os.getpid()
        found = []
        try:
            for entry in os.listdir('/proc'):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                if pid == my_pid:
                    continue
                try:
                    with open(f'/proc/{pid}/cmdline', 'rb') as _f:
                        raw = _f.read().decode(errors='replace')
                    parts = raw.split('\x00')
                    is_python = any('python' in p.lower() for p in parts[:2])
                    has_legion = any('legion.py' in p for p in parts)
                    has_web   = '--web' in parts
                    if not (is_python and has_legion and has_web):
                        continue
                    port = 5000
                    for i, p in enumerate(parts):
                        if p == '--port' and i + 1 < len(parts):
                            try:
                                port = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass
                    if port == current_port:
                        continue   # same port — will fail to bind, not our concern
                    alive = _server_is_alive(port)
                    found.append({'pid': pid, 'port': port, 'alive': alive})
                except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
                    continue
        except (FileNotFoundError, PermissionError):
            pass
        return found

    def _server_is_alive(port):
        """Return True if a Legion server is responding on the given port."""
        try:
            import urllib.request as _ur
            _ur.urlopen(f'http://127.0.0.1:{port}/health', timeout=1)
            return True
        except Exception:
            return False

    def _kill_server_tree(pid):
        """SIGKILL a Legion server and every descendant via /proc BFS.

        Mirrors _kill_all_descendants() in web_controller.py but operates on
        an external PID rather than os.getpid().
        """
        import signal as _sig
        # Build ppid→[children] map
        children = {}
        try:
            for entry in os.listdir('/proc'):
                if not entry.isdigit():
                    continue
                try:
                    with open(f'/proc/{entry}/stat', 'rb') as _f:
                        data = _f.read().decode(errors='replace')
                    comm_end = data.rfind(')')
                    if comm_end < 0:
                        continue
                    rest = data[comm_end + 2:].split()
                    if len(rest) < 2:
                        continue
                    ppid = int(rest[1])
                    children.setdefault(ppid, []).append(int(entry))
                except (FileNotFoundError, PermissionError, ValueError):
                    continue
        except (FileNotFoundError, PermissionError):
            pass
        # BFS from target pid
        to_kill = []
        queue = [pid]
        while queue:
            p = queue.pop(0)
            to_kill.append(p)
            queue.extend(children.get(p, []))
        # Kill descendants first, then the root
        for p in reversed(to_kill):
            try:
                os.kill(p, _sig.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _prompt_other_servers(servers, no_prompt):
        """Show found servers, prompt for K/C/A.  Returns True to continue, False to abort."""
        import time as _t
        print()
        print("┌──────────────────────────────────────────────────────────────────┐")
        print("│   Other Legion web server(s) already running                     │")
        print("├───────────┬────────┬─────────────────────────────────────────────┤")
        print("│   PID     │  Port  │  Status                                     │")
        print("├───────────┼────────┼─────────────────────────────────────────────┤")
        for s in servers:
            status = "● responding" if s['alive'] else "○ no response"
            print(f"│  {s['pid']:<8} │  :{s['port']:<4} │  {status:<43}│")
        print("└───────────┴────────┴─────────────────────────────────────────────┘")

        if no_prompt:
            print()
            print("  [--no-prompt] Continuing alongside existing server(s).")
            print("  Each instance uses its own isolated database and temp folders.")
            print("  Scans and deduplication do not cross instances.")
            print()
            return True

        print()
        print("  [K]  Kill other server(s) and all their running scans, then start")
        print("  [C]  Continue alongside  (instances share nothing — fully isolated)")
        print("  [A]  Abort")
        print()
        while True:
            try:
                choice = input("  Choice [K/c/a]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                return False
            if choice in ('k', ''):
                print()
                for s in servers:
                    print(f"  Stopping PID {s['pid']} on :{s['port']} ...", end=' ', flush=True)
                    _kill_server_tree(s['pid'])
                    print("killed")
                _t.sleep(1.0)   # allow sockets to release
                print()
                return True
            elif choice == 'c':
                print()
                print("  Continuing alongside. Isolation guarantees:")
                print("  • Separate temp SQLite DB per instance  (/tmp/legion/legion-*.legion)")
                print("  • Separate running + tool-output folders (unique mkdtemp each start)")
                print("  • Orphan cleanup uses /proc FD scanning — skips any file held open")
                print("    by a live instance, so this server will not delete the other's data.")
                print("  • Dedup check only sees processes in this instance's own database.")
                print()
                return True
            elif choice == 'a':
                print("\n  Aborted.")
                return False
            else:
                print("  Enter K to kill, C to continue, or A to abort.")

    if args.web:
        # --- WEB MODE (uses YOUR controller.py logic via WebController) ---
        from controller.web_controller import WebController
        from app.settings import AppSettings, Settings
        from flask import Flask, jsonify, request, render_template, send_from_directory

        doPathSetup()

        # Create logic (same as Qt6 controller.__init__)
        shell = DefaultShell()
        from app.logging.legionLog import getDbLogger, getAppLogger
        dbLog = getDbLogger()
        appLogger = getAppLogger()
        repositoryFactory = RepositoryFactory(dbLog)
        projectManager = ProjectManager(shell, repositoryFactory, appLogger)
        nmapExporter = DefaultNmapExporter(shell, appLogger)
        toolCoordinator = ToolCoordinator(shell, nmapExporter)
        logic = Logic(shell, projectManager, toolCoordinator)
        logic.createNewTemporaryProject()

        # ── Multi-instance detection (before wc.start() so cleanup doesn't run first) ──
        _other = _find_other_legion_servers(args.port)
        if _other:
            if not _prompt_other_servers(_other, args.no_prompt):
                sys.exit(0)

        # Create WebController (YOUR logic, Qt-free)
        settings = Settings(AppSettings())
        wc = WebController(logic, settings)
        wc.start()

        # Create Flask app
        app = Flask(__name__,
                    template_folder='app/web/templates',
                    static_folder='app/web/static')
        app.config['LEGION_WC'] = wc
        app.config['LEGION_LOGIC'] = logic

        # Import and register routes
        from app.web.routes import web_bp
        app.register_blueprint(web_bp)

        import signal as _signal

        def _web_shutdown(signum=None, frame=None):
            """SIGINT/SIGTERM handler for Flask mode.
            First press: set _exit_requested flag — JS detects it via snapshot and
            shows the save dialog in the browser.  A 60-second timeout force-exits
            if the browser never responds.  Second press force-exits immediately."""
            import os as _os, threading as _threading
            if getattr(wc, '_exit_requested', False):
                # Second Ctrl+C — user is insistent, force exit now
                print("\n[Legion] Force exit.")
                try:
                    wc.saveRunningProcessOutputs()
                    wc.closeProject()
                except Exception:
                    pass
                import time as _time
                _time.sleep(0.5)   # let daemon threads notice kill status before _exit
                _os._exit(0)

            wc._exit_requested = True
            print("\n[Legion] Exit requested — respond in the browser to save your project.")
            print("[Legion] Press Ctrl+C again to force-quit without saving.")

            def _force_exit_timeout():
                import time
                time.sleep(60)
                if getattr(wc, '_exit_requested', False):
                    print("\n[Legion] No browser response after 60s — force exiting.")
                    try:
                        wc.saveRunningProcessOutputs()
                        wc.closeProject()
                    except Exception:
                        pass
                    # Brief pause: lets daemon threads notice kill status written by
                    # closeProject/killRunningProcesses before _exit tears them down.
                    time.sleep(0.5)
                    _os._exit(0)
            _threading.Thread(target=_force_exit_timeout, daemon=True).start()

        # Register BOTH signals before app.run().
        # IMPORTANT: Werkzeug swallows KeyboardInterrupt internally in serve_forever(),
        # so 'except KeyboardInterrupt' around app.run() never fires.
        # Explicit signal handlers run before Werkzeug sees the signal.
        _signal.signal(_signal.SIGINT,  _web_shutdown)
        _signal.signal(_signal.SIGTERM, _web_shutdown)

        import re as _re, os as _os
        _idx = _os.path.join(_os.path.dirname(__file__), 'app/web/templates/index.html')
        try:
            _m = _re.search(r'LEGION (v[\d.]+-flask)', open(_idx).read())
            _ver = _m.group(1) if _m else 'v??'
        except Exception:
            _ver = 'v??'
        _port = args.port
        print(f"LEGION {_ver} — web UI starting at http://127.0.0.1:{_port}")

        # Open a new Firefox window after Flask has had 1.5 s to bind.
        # Using --new-window guarantees a fresh window rather than a new tab
        # in an existing session.
        def _open_browser():
            import subprocess as _sp
            _url = f'http://127.0.0.1:{_port}'
            _env = _os.environ.copy()
            _sudo_user = _env.get('SUDO_USER', '')
            _display   = _env.get('DISPLAY', ':0')
            _xauth     = _env.get('XAUTHORITY',
                                  f'/home/{_sudo_user}/.Xauthority' if _sudo_user else '')

            # Dedicated Legion profile so Firefox never conflicts with an
            # existing session (--no-remote skips IPC with the running instance;
            # --profile points at an isolated directory).
            #
            # Single shared profile 'legion-profile' — per-port profiles
            # (legion-profile-5085, etc.) bloat ~/.mozilla at ~100 MB each.
            # When two Legion instances run simultaneously, Firefox locks the
            # profile dir and the second open would fail.  Instead: check
            # whether the profile is already locked by another Firefox instance
            # (lock symlink or .parentlock file).  If locked, skip auto-open —
            # the user already has a Legion browser window from the first
            # instance.  If free, proceed normally.
            _home = f'/home/{_sudo_user}' if _sudo_user else _os.path.expanduser('~')
            _profile = _os.path.join(_home, '.mozilla', 'firefox', 'legion-profile')
            if not _os.path.isdir(_profile):
                _os.makedirs(_profile, exist_ok=True)
                # Profile dir must be owned by the user, not root
                if _sudo_user:
                    try:
                        import pwd as _pwd
                        _pi = _pwd.getpwnam(_sudo_user)
                        _os.chown(_profile, _pi.pw_uid, _pi.pw_gid)
                        _os.chown(_os.path.dirname(_profile), _pi.pw_uid, _pi.pw_gid)
                    except Exception:
                        pass

            # Check Firefox profile lock — present when a Firefox process
            # already holds the profile open.  On Linux this is a symlink
            # named 'lock'; Firefox also writes '.parentlock'.
            _lock   = _os.path.join(_profile, 'lock')
            _plock  = _os.path.join(_profile, '.parentlock')
            _locked = _os.path.lexists(_lock) or _os.path.exists(_plock)
            if _locked:
                print(f"[Legion] legion-profile already open — skipping auto-browser "
                      f"(another Legion instance has it).  Navigate to {_url} manually.")
                return

            # Write user.js on every launch — Firefox reads it at startup and
            # it overrides prefs.js, so session-restore is always suppressed
            # even if Firefox previously crashed and wrote recovery state.
            _userjs = _os.path.join(_profile, 'user.js')
            _userjs_content = (
                '// Legion profile — managed automatically, do not edit\n'
                'user_pref("browser.sessionstore.resume_from_crash", false);\n'
                'user_pref("browser.sessionstore.resume_session_once", false);\n'
                'user_pref("browser.startup.page", 0);\n'  # blank page, not "restore"
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            )
            try:
                with open(_userjs, 'w') as _f:
                    _f.write(_userjs_content)
                if _sudo_user:
                    import pwd as _pwd2
                    _pi2 = _pwd2.getpwnam(_sudo_user)
                    _os.chown(_userjs, _pi2.pw_uid, _pi2.pw_gid)
            except Exception:
                pass

            try:
                _cmd = ['firefox', '--no-remote',
                        '--profile', _profile,
                        '--new-window', _url]
                if _sudo_user:
                    _sp.Popen(
                        ['sudo', '-u', _sudo_user,
                         'env',
                         f'DISPLAY={_display}',
                         f'XAUTHORITY={_xauth}'] + _cmd,
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL
                    )
                else:
                    _sp.Popen(_cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, env=_env)
            except Exception as _be:
                print(f"[Legion] Could not open Firefox automatically: {_be}")
        if not args.no_browser:
            import threading as _threading
            _threading.Timer(1.5, _open_browser).start()

        app.run(host="127.0.0.1", port=_port, debug=False, threaded=True)
        sys.exit(0)

    # --- GUI MODE ---
    from ui.eventfilter import MyEventFilter
    from ui.ViewState import ViewState
    from ui.gui import *
    from ui.gui import Ui_MainWindow
    import qasync
    import asyncio

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    MainWindow = QtWidgets.QMainWindow()
    Screen = QGuiApplication.primaryScreen()
    app.setWindowIcon(QIcon('./images/icons/Legion-N_128x128.svg'))
    app.setStyleSheet("* { font-family: \"monospace\"; font-size: 10pt; }")

    from ui.view import *
    from controller.controller import *

    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)

    # Platform-independent privilege check
    if hasattr(os, "geteuid"):
        if os.geteuid() != 0:
            startupLog.error("Legion must run as root for raw socket access. Please start legion using sudo.")
            notice = QMessageBox()
            notice.setIcon(QMessageBox.Icon.Critical)
            notice.setText("Legion must run as root for raw socket access. Please start legion using sudo.")
            notice.exec()
            exit(1)
    elif os.name == "nt":
        # On Windows, warn but do not exit
        startupLog.warning("Legion may require Administrator privileges for some features on Windows.")
        notice = QMessageBox()
        notice.setIcon(QMessageBox.Icon.Warning)
        notice.setText("Legion may require Administrator privileges for some features on Windows.")
        notice.exec()

    shell = DefaultShell()
    dbLog = getDbLogger()
    appLogger = getAppLogger()
    repositoryFactory = RepositoryFactory(dbLog)
    projectManager = ProjectManager(shell, repositoryFactory, appLogger)
    nmapExporter = DefaultNmapExporter(shell, appLogger)
    toolCoordinator = ToolCoordinator(shell, nmapExporter)
    logic = Logic(shell, projectManager, toolCoordinator)

    startupLog.info("Creating temporary project at application start...")
    logic.createNewTemporaryProject()

    viewState = ViewState()
    view = View(viewState, ui, MainWindow, shell, app, loop)  # View prep (gui)
    controller = Controller(view, logic)  # Controller prep (communication between model and view)

    myFilter = MyEventFilter(view, MainWindow)  # to capture events
    app.installEventFilter(myFilter)

    # Center the application in screen
    screenCenter = Screen.availableGeometry().center()
    MainWindow.move(screenCenter - MainWindow.rect().center())

    import signal

    # CRITICAL: Flag to prevent multiple cleanup calls
    _cleanup_done = False

    def graceful_shutdown(*args):
        """
        Comprehensive cleanup before application exit.
        """
        global _cleanup_done
        
        if _cleanup_done:
            return
        
        _cleanup_done = True
        startupLog.info("=" * 80)
        startupLog.info("LEGION APPLICATION GRACEFUL SHUTDOWN INITIATED")
        startupLog.info("=" * 80)

        
        try:
            # STEP 1: Stop all QTimers
            startupLog.info("Step 1: Stopping QTimers...")
            try:
                if hasattr(controller, '_timers'):
                    for timer in controller._timers:
                        if timer and timer.isActive():
                            timer.stop()
                            try:
                                timer.timeout.disconnect()
                            except (TypeError, RuntimeError):
                                pass
                
                if hasattr(view, '__dict__'):
                    for attr_name in list(view.__dict__.keys()):
                        try:
                            attr = getattr(view, attr_name, None)
                            if isinstance(attr, QTimer):
                                if attr.isActive():
                                    attr.stop()
                                    try:
                                        attr.timeout.disconnect()
                                    except (TypeError, RuntimeError):
                                        pass
                        except (RuntimeError, AttributeError):
                            pass
                startupLog.info("  Timers stopped")
            except Exception as e:
                startupLog.error(f"Error stopping timers: {e}")
            
            # STEP 2: Kill all running processes
            startupLog.info("Step 2: Killing processes...")
            try:
                if hasattr(controller, 'killRunningProcesses'):
                    controller.killRunningProcesses()
                
                if hasattr(controller, 'qProcess') and controller.qProcess:
                    try:
                        controller.qProcess.blockSignals(True)
                        if controller.qProcess.state() != QProcess.ProcessState.NotRunning:
                            controller.qProcess.terminate()
                            controller.qProcess.waitForFinished(2000)
                        controller.qProcess.close()
                    except Exception:
                        pass
                
                startupLog.info("  Processes killed")
            except Exception as e:
                startupLog.error(f"Error killing processes: {e}")
            
            # STEP 3: Stop QThreads
            startupLog.info("Step 3: Stopping threads...")
            try:
                if hasattr(controller, "screenshooter") and controller.screenshooter:
                    if controller.screenshooter.isRunning():
                        controller.screenshooter.requestInterruption()
                        controller.screenshooter.quit()
                        controller.screenshooter.wait(3000)
                startupLog.info("  Threads stopped")
            except Exception as e:
                startupLog.error(f"Error stopping threads: {e}")
            
            # STEP 4: Close database
            startupLog.info("Step 4: Closing database...")
            try:
                if hasattr(logic, 'activeProject') and logic.activeProject:
                    if hasattr(logic.activeProject, 'database') and logic.activeProject.database:
                        try:
                            if hasattr(logic.activeProject.database, 'close'):
                                logic.activeProject.database.close()
                            startupLog.info("  Database closed")
                        except Exception:
                            pass
            except Exception as e:
                startupLog.error(f"Error closing database: {e}")
            
            # STEP 5: Block widget signals
            startupLog.info("Step 5: Blocking signals...")
            try:
                if MainWindow:
                    MainWindow.blockSignals(True)
                startupLog.info("  Signals blocked")
            except Exception as e:
                startupLog.error(f"Error blocking signals: {e}")
            
            # STEP 6: Process pending events
            startupLog.info("Step 6: Processing events...")
            try:
                QApplication.processEvents()
                startupLog.info("  Events processed")
            except Exception:
                pass


            
        except Exception as e:
            startupLog.error(f"ERROR during shutdown: {e}")
            import traceback
            startupLog.error(traceback.format_exc())

    # Connect to aboutToQuit
    startupLog.info("Connecting graceful_shutdown to aboutToQuit")
    app.aboutToQuit.connect(graceful_shutdown)

    # Handle signals
    def signal_handler(signum, frame):
        startupLog.info(f"Received signal {signum}")
        app.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    MainWindow.show()
    startupLog.info("Legion started successfully.")
    
    # Run event loop and properly clean up to prevent segfault
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        startupLog.info("KeyboardInterrupt received")
    finally:
        # STEP 1: Clean up event loop
        startupLog.info("Cleaning up event loop...")
        try:
            # Cancel all pending asyncio tasks
            pending = asyncio.all_tasks(loop)
            if pending:
                startupLog.info(f"Cancelling {len(pending)} pending tasks...")
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                startupLog.info("All tasks cancelled")
        except Exception as e:
            startupLog.warning(f"Error during task cancellation: {e}")
        
        try:
            # Close the event loop
            if not loop.is_closed():
                loop.close()
                startupLog.info("Event loop closed")
        except Exception as e:
            startupLog.error(f"Error closing event loop: {e}")
        
        # STEP 2: Clean up Qt widgets WITHOUT triggering close events
        startupLog.info("Cleaning up Qt widgets...")
        try:
            if 'app' in locals() and app is not None:
                # CRITICAL: Block signals first to prevent close events from firing
                for widget in app.topLevelWidgets():
                    try:
                        if widget:
                            widget.blockSignals(True)  # Prevent closeEvent from firing
                            widget.deleteLater()       # Schedule deletion without triggering events
                    except (RuntimeError, AttributeError):
                        pass
                
                # Process deleteLater() calls while QApplication still exists
                app.processEvents()
                startupLog.info("  All widgets cleaned up")
        except Exception as e:
            startupLog.error(f"Error cleaning up widgets: {e}")
        
        # STEP 3: Process final Qt events
        startupLog.info("Processing final events...")
        try:
            if 'app' in locals() and app is not None:
                app.processEvents()
        except Exception:
            pass
        
        # STEP 4: CRITICAL - Do NOT explicitly delete QApplication
        # Let Python's garbage collector handle it naturally to prevent crashes
        startupLog.info("Allowing QApplication to exit naturally...")
        startupLog.info("Python garbage collection will handle cleanup in correct order")
        
        # Clear references to allow GC to work properly
        try:
            if 'MainWindow' in locals():
                MainWindow = None
            if 'view' in locals():
                view = None
            if 'controller' in locals():
                controller = None
            if 'ui' in locals():
                ui = None
        except Exception as e:
            startupLog.warning(f"Error clearing references: {e}")
    
    startupLog.info("=" * 80)
    startupLog.info("LEGION APPLICATION GRACEFUL SHUTDOWN COMPLETED")
    startupLog.info("=" * 80)

    
