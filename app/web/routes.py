"""
Flask routes — calls YOUR controller.py logic via WebController.
No runtime.py. No upstream reimplementation.
"""

import datetime
import json
import os
import shutil
import stat
import threading
import time

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from app.settings import AppSettings, Settings
from app.auxiliary import Filters
from app.validation import validateNmapInput, validateNmapPorts

web_bp = Blueprint("web", __name__)

def _wc():
    return current_app.config['LEGION_WC']

def _logic():
    return current_app.config['LEGION_LOGIC']

def _err(msg, code=400):
    return jsonify({"status": "error", "error": str(msg)}), code

def _filters():
    return Filters()

# ── Heartbeat / browser-close watchdog ────────────────────────────────────────
# JS pings /api/heartbeat every 5 s.  If pings stop for _HB_TIMEOUT seconds
# (browser window closed, File→Exit in Firefox, crash) the watchdog calls
# os._exit(0) so this Legion instance terminates automatically.
# Timeout is long enough that a page refresh (F5 / Ctrl+Shift+R, ~2–5 s gap)
# does NOT trigger a shutdown.
_HB_TIMEOUT  = 20        # seconds without a ping → browser is gone
_hb_lock     = threading.Lock()
_hb_last     = None      # float timestamp; None = no heartbeat yet received
_hb_started  = False     # True once the watchdog thread is running


# ═══════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════

@web_bp.get("/")
def index():
    wc = _wc()
    logic = _logic()
    filters = _filters()
    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    def _h(h, k, d=''):
        return h.get(k, d) if isinstance(h, dict) else getattr(h, k, d)
    snapshot = {
        "hosts": [{"id": _h(h,"id"), "ip": _h(h,"ipv4") or _h(h,"ip"),
                    "hostname": _h(h,"hostname"), "os": _h(h,"osMatch"),
                    "status": _h(h,"status"), "open_ports": 0} for h in (hosts or [])],
        "services": [],
        "tools": [],
        "processes": [],
        "summary": {"hosts": len(hosts or []), "open_ports": 0, "services": 0, "cves": 0,
                     "running_processes": 0, "finished_processes": 0},
        "project": {"name": getattr(logic.activeProject.properties, "projectName", "*untitled"),
                     "output_folder": getattr(logic.activeProject.properties, "outputFolder", ""),
                     "is_temporary": getattr(logic.activeProject.properties, "isTemporary", True)},
    }
    return render_template("index.html", snapshot=snapshot, ws_enabled=False)

@web_bp.get("/health")
def health():
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════
# Snapshot (polled by JS every 3s)
# ═══════════════════════════════════════════

@web_bp.get("/api/snapshot")
def snapshot():
    import time as _snap_time
    _t0 = _snap_time.monotonic()
    wc = _wc()
    logic = _logic()
    filters = _filters()

    # ── Hosts: single SQL query with port counts (no ORM, no N+1 queries) ──
    # Previous: getHosts() + portRepository.getPortsByHostId per host = N+1 ORM queries
    # Fix: one raw SQL with LEFT JOIN count — eliminates the per-host query loop
    from sqlalchemy import text as _st
    _sess = logic.activeProject.database.session()
    try:
        _host_rows = _sess.execute(_st(
            "SELECT h.id, h.ip, h.ipv4, h.hostname, h.osMatch, h.status, h.checked, "
            "  (SELECT COUNT(*) FROM portObj p WHERE p.hostId = h.id) AS port_count "
            "FROM hostObj h WHERE h.status != 'down'"
        )).fetchall()
        _host_keys = ['id','ip','ipv4','hostname','osMatch','status','checked','port_count']
        hosts_raw = [dict(zip(_host_keys, r)) for r in _host_rows]
    finally:
        _sess.close()

    hosts = []
    total_ports = 0
    for h in hosts_raw:
        hid = h.get('id', '')
        hip = h.get('ipv4', '') or h.get('ip', '')
        port_count = int(h.get('port_count', 0) or 0)
        total_ports += port_count
        hosts.append({"id": hid, "ip": hip,
                       "hostname": h.get('hostname', ''),
                       "os": h.get('osMatch', ''),
                       "status": h.get('status', ''),
                       "open_ports": port_count,
                       "checked": str(h.get('checked', 'False')) == 'True'})

    # ── Services ──
    services_raw = logic.activeProject.repositoryContainer.serviceRepository.getServiceNames(filters)
    services = []
    for s in (services_raw or []):
        if isinstance(s, dict):
            services.append({"service": s.get('name', ''), "port": str(s.get('port', '') or '')})
        else:
            sname = str(s[0]) if hasattr(s, '__getitem__') else str(s)
            sport = str(s[1]) if hasattr(s, '__getitem__') and len(s) > 1 else ''
            services.append({"service": sname, "port": sport})

    # ── Tools + Processes: single getProcesses call, derive both ──
    # Previous: getProcesses called TWICE (once for tools, once for processes)
    from collections import OrderedDict
    procs_raw = logic.activeProject.repositoryContainer.processRepository.getProcesses(filters)
    tool_counts = OrderedDict()
    tool_matches = {}
    processes = []
    running = 0
    finished = 0
    import time as _time
    from datetime import datetime as _dt
    for p in (procs_raw or []):
        if isinstance(p, dict):
            proc = dict(p)
        else:
            proc = {"name": getattr(p, 'name', ''), "hostIp": getattr(p, 'hostIp', ''),
                     "port": getattr(p, 'port', ''), "protocol": getattr(p, 'protocol', ''),
                     "status": getattr(p, 'status', ''), "pid": getattr(p, 'pid', ''),
                     "command": getattr(p, 'command', '')}
        if 'id' not in proc:
            proc['id'] = proc.get('pid', proc.get('progress', ''))
        status = proc.get("status", "")
        name = proc.get("name", "")

        # Tools aggregate (was a separate getProcesses call)
        if name:
            tool_counts[name] = tool_counts.get(name, 0) + 1
            match_key_tool = f"{proc.get('hostIp','')}:{proc.get('tabTitle','')}"
            if getattr(wc, '_matches', {}).get(match_key_tool):
                tool_matches[name] = True

        if status == "Running":
            running += 1
            start_str = str(proc.get('startTime', '') or '')
            start_ts = None
            for fmt in ('%d %b %Y %H:%M:%S.%f', '%Y%m%d%H%M%S%f'):
                try:
                    start_ts = _dt.strptime(start_str, fmt).timestamp()
                    break
                except Exception:
                    pass
            proc['elapsed_secs'] = int(_time.time() - start_ts) if start_ts else 0
        else:
            finished += 1
            proc['elapsed_secs'] = None

        match_key = f"{proc.get('hostIp', '')}:{proc.get('tabTitle', '')}"
        match_list = getattr(wc, '_matches', {}).get(match_key) or []
        proc['has_match'] = bool(match_list)
        proc['match_text'] = ', '.join(str(m) for m in match_list) if match_list else ''
        # Terminal session_id (null for regular processes, set for Interactive PTY sessions)
        proc['session_id'] = _terminal_process_sessions.get(proc.get('id') or proc.get('pid'))
        processes.append(proc)

    tool_list = [{"label": n, "tool_id": n, "run_count": c,
                  "has_match": tool_matches.get(n, False)}
                 for n, c in tool_counts.items()]

    # ── OS groups ──
    os_groups = logic.activeProject.repositoryContainer.hostRepository.getOperatingSystemsSummary() or []

    _elapsed_ms = int((_snap_time.monotonic() - _t0) * 1000)
    import logging as _logging
    # DEBUG not INFO — snapshot fires every 1.5s and would flood the log buffer
    _logging.getLogger('legion').debug(
        f"[Snapshot] {_elapsed_ms}ms  hosts={len(hosts)} procs={len(processes)} "
        f"running={running} tools={len(tool_list)}"
    )

    return jsonify({
        "hosts": hosts,
        "services": services,
        "tools": tool_list,
        "processes": processes,
        "summary": {"hosts": len(hosts), "open_ports": total_ports,
                     "services": len(services), "cves": 0,
                     "running_processes": running, "finished_processes": finished},
        "project": {"name": getattr(logic.activeProject.properties, "projectName", "*untitled"),
                     "output_folder": getattr(logic.activeProject.properties, "outputFolder", ""),
                     "is_temporary": getattr(logic.activeProject.properties, "isTemporary", True),
                     "exit_requested": getattr(wc, '_exit_requested', False)},
        "os_groups": os_groups,
        "scheduler_decisions": [],
        "scheduler_approvals": [],
        "jobs": [],
    })


# ═══════════════════════════════════════════
# Host detail
# ═══════════════════════════════════════════

@web_bp.get("/api/workspace/hosts/<int:host_id>")
def host_detail(host_id):
    logic = _logic()
    repo = logic.activeProject.repositoryContainer
    session = logic.activeProject.database.session()
    try:
        from db.entities.host import hostObj
        host = session.query(hostObj).filter_by(id=host_id).first()
        if not host:
            return _err(f"Host {host_id} not found", 404)
        ports_raw = repo.portRepository.getPortsByHostId(host_id)
        ports = []
        for p in (ports_raw or []):
            svc = repo.serviceRepository.getServiceById(p.serviceId) if p.serviceId else None
            ports.append({
                "port": str(p.portId), "protocol": str(p.protocol), "state": str(p.state),
                "service": {"name": getattr(svc, "name", ""), "product": getattr(svc, "product", ""),
                             "version": getattr(svc, "version", ""), "extrainfo": getattr(svc, "extrainfo", "")} if svc else {}
            })
        note = ""
        try:
            n = repo.noteRepository.getNoteByHostId(host_id)
            note = getattr(n, "text", "") if n else ""
        except Exception:
            pass
        return jsonify({
            "host": {"id": host.id, "ip": getattr(host, "ipv4", "") or getattr(host, "ip", ""),
                      "hostname": getattr(host, "hostname", ""), "os": getattr(host, "osMatch", ""),
                      "status": getattr(host, "status", "")},
            "ports": ports, "scripts": [], "cves": [], "screenshots": [],
            "note": note, "ai_analysis": {},
        })
    finally:
        session.close()


@web_bp.get("/api/workspace/hosts/<int:host_id>/information")
def host_information(host_id):
    """G1: Information tab — Qt6: view.py:updateInformationView + buildInformationText"""
    wc = _wc()
    logic = _logic()
    session = logic.activeProject.database.session()
    try:
        from db.entities.host import hostObj
        host = session.query(hostObj).filter_by(id=host_id).first()
        if not host:
            return _err(f"Host {host_id} not found", 404)
        ip = getattr(host, 'ipv4', '') or getattr(host, 'ip', '')
        # Count port states (Qt6: getPortStatesForHost)
        states = wc.getPortStatesForHost(host_id) or []
        # Rows can be SQLAlchemy Row, tuple, dict or plain str — normalise to str
        def _state(s):
            if isinstance(s, dict): return str(s.get('state', ''))
            try: return str(s[0])
            except Exception: return str(s)
        open_c = sum(1 for s in states if _state(s) == 'open')
        closed_c = sum(1 for s in states if _state(s) == 'closed')
        filtered_c = sum(1 for s in states if _state(s) not in ('open', 'closed'))
        return jsonify({
            "ip": ip,
            "ipv6": getattr(host, 'ipv6', '') or '',
            "hostname": getattr(host, 'hostname', '') or '',
            "status": getattr(host, 'status', '') or '',
            "os": getattr(host, 'osMatch', '') or '',
            "os_accuracy": getattr(host, 'osAccuracy', '') or '',
            "mac": getattr(host, 'macaddr', '') or '',
            "vendor": getattr(host, 'vendor', '') or '',
            "open_ports": open_c,
            "closed_ports": closed_c,
            "filtered_ports": filtered_c,
            "asn": getattr(host, 'asn', '') or '',
            "isp": getattr(host, 'isp', '') or '',
            "country_code": getattr(host, 'countryCode', '') or '',
            "city": getattr(host, 'city', '') or '',
            "latitude": getattr(host, 'latitude', '') or '',
            "longitude": getattr(host, 'longitude', '') or '',
        })
    finally:
        session.close()


@web_bp.get("/api/workspace/hosts/<int:host_id>/cves-list")
def host_cves_list(host_id):
    """G2: CVEs tab — Qt6: view.py:updateCvesByHostView"""
    wc = _wc()
    logic = _logic()
    session = logic.activeProject.database.session()
    try:
        from db.entities.host import hostObj
        host = session.query(hostObj).filter_by(id=host_id).first()
        if not host:
            return _err(f"Host {host_id} not found", 404)
        ip = getattr(host, 'ipv4', '') or getattr(host, 'ip', '')
    finally:
        session.close()
    cves_raw = wc.getCvesFromDB(ip) or []
    cves = []
    for c in cves_raw:
        if isinstance(c, dict):
            cves.append({"name": c.get('name',''), "severity": c.get('severity',''),
                         "product": c.get('product',''), "version": c.get('version',''),
                         "url": c.get('url',''), "source": c.get('source',''),
                         "exploit_id": c.get('exploitId',''), "exploit_url": c.get('exploitUrl','')})
        else:
            cves.append({"name": getattr(c,'name',''), "severity": str(getattr(c,'severity','')),
                         "product": getattr(c,'product',''), "version": getattr(c,'version',''),
                         "url": getattr(c,'url',''), "source": getattr(c,'source',''),
                         "exploit_id": getattr(c,'exploitId',''), "exploit_url": getattr(c,'exploitUrl','')})
    return jsonify({"cves": cves})


@web_bp.get("/api/workspace/hosts/<int:host_id>/scripts-list")
def host_scripts_list(host_id):
    """G3: Scripts tab — Qt6: view.py:updateScriptsView"""
    wc = _wc()
    logic = _logic()
    session = logic.activeProject.database.session()
    try:
        from db.entities.host import hostObj
        host = session.query(hostObj).filter_by(id=host_id).first()
        if not host:
            return _err(f"Host {host_id} not found", 404)
        ip = getattr(host, 'ipv4', '') or getattr(host, 'ip', '')
    finally:
        session.close()
    scripts_raw = wc.getScriptsFromDB(ip) or []
    scripts = []
    for s in scripts_raw:
        if isinstance(s, dict):
            scripts.append({"id": s.get('id',''), "script_id": s.get('scriptId',''),
                            "port": str(s.get('portId','') or ''), "protocol": s.get('protocol','')})
        else:
            scripts.append({"id": getattr(s,'id',''), "script_id": getattr(s,'scriptId',''),
                            "port": str(getattr(s,'portId','') or ''), "protocol": getattr(s,'protocol','')})
    return jsonify({"scripts": scripts})


@web_bp.get("/api/workspace/scripts/<int:script_id>/output")
def script_output(script_id):
    """G3: Script output — Qt6: view.py:updateScriptsOutputView"""
    wc = _wc()
    rows = wc.getScriptOutputFromDB(script_id) or []
    output = ''.join(r.get('output','') if isinstance(r,dict) else getattr(r,'output','')
                     for r in rows)
    return jsonify({"id": script_id, "output": output})


@web_bp.get("/api/workspace/os/<path:os_name>/hosts")
def os_hosts(os_name):
    """G4: OS hosts table — Qt6: view.py:updateOsHostsTableView"""
    wc = _wc()
    hosts_raw = wc.getHostsForOperatingSystem(os_name) or []
    hosts = []
    for h in hosts_raw:
        if isinstance(h, dict):
            hosts.append({"id": h.get('id',''), "ip": h.get('ip','') or h.get('ipv4',''),
                          "hostname": h.get('hostname',''), "os": h.get('osMatch','') or h.get('os',''),
                          "status": h.get('status','')})
        else:
            hosts.append({"id": getattr(h,'id',''), "ip": getattr(h,'ipv4','') or getattr(h,'ip',''),
                          "hostname": getattr(h,'hostname',''), "os": getattr(h,'osMatch',''),
                          "status": getattr(h,'status','')})
    return jsonify({"os": os_name, "hosts": hosts})


# ═══════════════════════════════════════════
# Process management
# ═══════════════════════════════════════════

@web_bp.get("/api/processes/<int:process_id>/output")
def process_output(process_id):
    logic = _logic()
    repo = logic.activeProject.repositoryContainer.processRepository
    proc = repo.getProcessById(process_id)
    if not proc:
        return _err(f"Process {process_id} not found", 404)
    # Check for live temp file first (written by _capture_output without SQLite overhead).
    # While a process is Running, output is in {outputfile}.live_output (near-zero latency).
    # After process finishes, the final output is in SQLite and the temp file is cleaned up.
    outputfile = proc.get("outputfile", "") or ""
    live_path = outputfile + '.live_output' if outputfile else ''
    output = ""
    if live_path and os.path.isfile(live_path):
        try:
            with open(live_path, 'r', encoding='ISO-8859-1', errors='replace') as _f:
                output = _f.read()
        except Exception:
            pass
    if not output:
        from sqlalchemy import text
        session = logic.activeProject.database.session()
        try:
            row = session.execute(text("SELECT output FROM process_output WHERE processId = :pid"),
                                  {"pid": process_id}).fetchone()
            output = str(row[0] or "") if row else ""
        finally:
            session.close()
    offset = int(request.args.get("offset", 0) or 0)
    max_chars = int(request.args.get("max_chars", 24000) or 24000)
    status = proc.get("status", "")
    # Screenshooter: find the PNG eyewitness put in {outputfile}-dir/ and serve as image
    proc_name = proc.get("name", "")
    outputfile = proc.get("outputfile", "") or ""
    if proc_name == "screenshooter" and outputfile:
        outdir = outputfile + '-dir'
        if os.path.isdir(outdir):
            for _root, _dirs, _files in os.walk(outdir):
                for _fname in _files:
                    if _fname.endswith('.png'):
                        output = f"screenshot:{os.path.join(_root, _fname)}"
                        break
                if output.startswith('screenshot:'):
                    break
    chunk = output[offset:offset + max_chars]
    return jsonify({
        "id": process_id, "name": proc_name, "hostIp": proc.get("hostIp", ""),
        "port": proc.get("port", ""), "command": proc.get("command", ""), "status": status,
        "output_chunk": chunk, "output_length": len(output),
        "offset": offset, "next_offset": offset + len(chunk),
        "completed": status not in ("Running", "Waiting"),
    })

@web_bp.get("/api/screenshots")
def serve_screenshot():
    """Serve a screenshot image by absolute path (query param avoids Flask path-stripping)."""
    path = request.args.get('path', '')
    if not path or not os.path.isfile(path):
        return _err("screenshot not found", 404)
    return send_from_directory(os.path.dirname(path), os.path.basename(path))

@web_bp.post("/api/processes/<int:process_id>/kill")
def process_kill(process_id):
    _wc().killProcess(process_id)
    return jsonify({"status": "ok"})

@web_bp.post("/api/processes/<int:process_id>/retry")
def process_retry(process_id):
    result = _wc().handleProcessAction(process_id, 'retry')
    return jsonify({"status": "ok", "result": result})

@web_bp.post("/api/processes/<int:process_id>/close")
def process_close(process_id):
    """Qt6: storeCloseTabStatusInDB → updateProcessState(closed='True').
    Sets closed='True' so the process is filtered from snapshot queries
    (WHERE process.closed='False'). Previously used hideProcesses which
    set display='False' only — process stayed in snapshot."""
    from sqlalchemy import text as _t
    session = _logic().activeProject.database.session()
    try:
        session.execute(_t("UPDATE process SET closed='True' WHERE id=:pid"),
                        {"pid": process_id})
        session.commit()
    finally:
        session.close()
    return jsonify({"status": "ok"})

@web_bp.post("/api/processes/clear")
def processes_clear():
    logic = _logic()
    repo = logic.activeProject.repositoryContainer.processRepository
    reset_all = request.get_json(silent=True) or {}
    # Hide finished processes
    from sqlalchemy import text
    session = logic.activeProject.database.session()
    try:
        if reset_all.get("reset_all"):
            session.execute(text("UPDATE process SET closed = 'True' WHERE status != 'Running'"))
        else:
            session.execute(text("UPDATE process SET closed = 'True' WHERE status IN ('Finished','Crashed','Cancelled','Killed')"))
        session.commit()
    finally:
        session.close()
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════
# Scan / Tool execution
# ═══════════════════════════════════════════

@web_bp.post("/api/nmap/scan")
def nmap_scan():
    """Matches view.py:callAddHosts → controller.addHosts.
    Comma, semicolon, and newline all separate multiple targets — each gets
    its own parallel nmap process (Qt6: one process per host)."""
    import re as _re
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    raw = str(payload.get("targets", "")).strip()
    if not raw:
        return _err("targets required")

    # Split on newline or semicolon — each becomes a separate parallel nmap process.
    # Commas are NOT split here — they remain invalid per validateNmapInput so any
    # comma-containing input is rejected before reaching nmap.
    parts = [t.strip() for t in _re.split(r'[\n;]+', raw) if t.strip()]
    if not parts:
        return _err("targets required")

    # Validate every part before starting any scan
    for part in parts:
        if not validateNmapInput(part):
            return _err(f"Invalid target: only IPs, CIDRs, and hostnames are accepted — rejected: {part!r}")

    scan_mode = str(payload.get("scan_mode", "Easy"))
    staged     = payload.get("staged", False)
    discovery  = payload.get("discovery", True)
    timing     = str(payload.get("timing", "4"))
    nmap_options = payload.get("nmap_options", [])
    enable_ipv6  = payload.get("enable_ipv6", False)
    if not isinstance(nmap_options, list):
        nmap_options = []

    results = []
    for target in parts:
        r = wc.addHosts(
            targetHosts=target,
            runHostDiscovery=discovery,
            runStagedNmap=staged,
            nmapSpeed=timing,
            scanMode=scan_mode,
            nmapOptions=nmap_options,
            enableIPv6=enable_ipv6,
        )
        results.append(r)

    return jsonify({"status": "ok", "result": results if len(results) > 1 else results[0]})


@web_bp.post("/api/workspace/hosts/import-file")
def import_hosts_from_file():
    """Import target hosts from a text file (one target per line).
    Qt6/CLI gap: cli_utils.import_targets_from_textfile was only reachable via --input-file.
    Accepts JSON body: {"path": "/path/to/targets.txt"}
    OR multipart form upload with field name "file".
    Lines starting with # are skipped. Hosts already in DB are skipped."""
    from app.cli_utils import import_targets_from_textfile
    logic = _logic()

    # Support both JSON path and multipart file upload
    tmp_path = None
    if request.content_type and 'multipart' in request.content_type:
        f = request.files.get('file')
        if not f:
            return _err("file field required for multipart upload")
        import tempfile
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as tmp:
            f.save(tmp)
            tmp_path = tmp.name
        path = tmp_path
    else:
        payload = request.get_json(silent=True) or {}
        path = str(payload.get("path", "")).strip()
        if not path:
            return _err("path required")
        if not os.path.isfile(path):
            return _err(f"file not found: {path}", 404)

    try:
        session = logic.activeProject.database.session()
        host_repo = logic.activeProject.repositoryContainer.hostRepository
        added = import_targets_from_textfile(session, host_repo, path)
        return jsonify({"status": "ok", "added": added})
    except Exception as e:
        return _err(f"import failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@web_bp.post("/api/nmap/import-xml")
def nmap_import_xml():
    """Import an nmap XML file via the UI modal (legion.js → import-nmap-modal)."""
    from app.importers.nmap_import import import_nmap_xml
    logic = _logic()
    payload = request.get_json(silent=True) or {}
    path = str(payload.get("path", "")).strip()
    if not path:
        return _err("path required")
    if not os.path.isfile(path):
        return _err(f"file not found: {path}")
    run_actions = bool(payload.get("run_actions", False))
    result = import_nmap_xml(project=logic.activeProject, xml_path=path, output="")
    hosts = result.get("hosts", 0) if isinstance(result, dict) else 0
    ports = result.get("ports", 0) if isinstance(result, dict) else 0
    if run_actions:
        _wc().scheduler(isNmapImport=True)
    return jsonify({"status": "ok", "hosts": hosts, "ports": ports})

@web_bp.post("/api/workspace/tools/run")
def tool_run():
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    host_ip = str(payload.get("host_ip", ""))
    port = str(payload.get("port", ""))
    tool_id = str(payload.get("tool_id", ""))
    if not host_ip or not port or not tool_id:
        return _err("host_ip, port, tool_id required")
    targets = [[host_ip, port, payload.get("protocol", "tcp")]]
    # Find the tool index
    for i, a in enumerate(wc.settings.portActions):
        if a[1] == tool_id:
            result = wc.handleServiceNameAction(targets, action_index=i)
            return jsonify({"status": "ok", "result": result})
    return _err(f"Tool {tool_id} not found", 404)

@web_bp.post("/api/workspace/service-action")
def service_action():
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    targets = payload.get("targets", [])
    action_index = int(payload.get("action_index", 0))
    if not targets:
        return _err("targets required")
    result = wc.handleServiceNameAction(targets, action_index=action_index)
    return jsonify({"status": "ok", "result": result})


# ═══════════════════════════════════════════
# Context menus
# ═══════════════════════════════════════════

@web_bp.get("/api/menus/host")
def menu_host():
    checked = str(request.args.get("checked", "False"))
    return jsonify({"items": _wc().getContextMenuForHost(isChecked=checked)})

@web_bp.get("/api/menus/service")
def menu_service():
    name = str(request.args.get("name", "*"))
    return jsonify({"items": _wc().getContextMenuForServiceName(serviceName=name)})

@web_bp.get("/api/menus/port")
def menu_port():
    service = str(request.args.get("service", "*"))
    return jsonify(_wc().getContextMenuForPort(serviceName=service))

@web_bp.get("/api/menus/process")
def menu_process():
    return jsonify({"items": _wc().getContextMenuForProcess()})


# ═══════════════════════════════════════════
# Host actions
# ═══════════════════════════════════════════

@web_bp.post("/api/workspace/hosts/<int:host_id>/action")
def host_action(host_id):
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", ""))
    ip = str(payload.get("ip", ""))
    if not action:
        return _err("action required")
    if action == 'host-action':
        result = wc.handleHostToolAction(ip, int(payload.get("action_index", -1)))
    elif action == 'add-port':
        port_str = str(payload.get('port', ''))
        if not port_str.isdigit():
            return _err("port must be a number")
        port_num = int(port_str)
        if port_num < 1 or port_num > 65535:
            return _err("port must be between 1 and 65535")
        port_data = {
            'port': port_str,
            'state': str(payload.get('state', 'open')),
            'protocol': str(payload.get('protocol', 'tcp')),
            'service': str(payload.get('service', '')),
        }
        wc.addPortToHost(ip, port_data)
        result = {'action': 'add-port', 'port': port_data}
    else:
        result = wc.handleHostAction(ip, host_id, action)
    return jsonify({"status": "ok", "result": result})

@web_bp.post("/api/workspace/hosts/<int:host_id>/scripts")
def host_add_script(host_id):
    logic = _logic()
    payload = request.get_json(silent=True) or {}
    script_id = str(payload.get("script_id", ""))
    port = str(payload.get("port", ""))
    output = str(payload.get("output", ""))
    if not script_id:
        return _err("script_id required")
    try:
        from db.entities.l1script import l1ScriptObj
        session = logic.activeProject.database.session()
        try:
            script = l1ScriptObj(scriptId=script_id, output=output, portId=port, hostId=host_id)
            session.add(script)
            session.commit()
        finally:
            session.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return _err(str(e), 500)

@web_bp.post("/api/workspace/hosts/<int:host_id>/cves")
def host_add_cve(host_id):
    logic = _logic()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", ""))
    severity = str(payload.get("severity", ""))
    if not name:
        return _err("name required")
    try:
        from db.entities.cve import cve as cveObj
        product = str(payload.get("product", ""))
        url = str(payload.get("url", ""))
        session = logic.activeProject.database.session()
        try:
            c = cveObj(name=name, url=url, product=product, hostId=host_id)
            c.severity = severity
            session.add(c)
            session.commit()
        finally:
            session.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return _err(str(e), 500)

@web_bp.post("/api/workspace/hosts/<int:host_id>/note")
def host_note(host_id):
    payload = request.get_json(silent=True) or {}
    note = str(payload.get("note", ""))
    _wc().saveProject(host_id, note)
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════
# Project management
# ═══════════════════════════════════════════

@web_bp.get("/api/project")
def project_details():
    logic = _logic()
    p = logic.activeProject.properties
    return jsonify({"name": getattr(p, "projectName", ""), "project": {
        "name": getattr(p, "projectName", ""), "output_folder": getattr(p, "outputFolder", ""),
        "is_temporary": getattr(p, "isTemporary", True)}})

@web_bp.post("/api/project/new-temp")
def project_new():
    _wc().createNewProject()
    return jsonify({"status": "ok"})

@web_bp.post("/api/project/open")
def project_open():
    payload = request.get_json(silent=True) or {}
    path = str(payload.get("path", ""))
    if not path or not os.path.isfile(path):
        return _err(f"File not found: {path}", 404)
    result = _wc().openExistingProject(path)
    return jsonify({"status": "ok", "opened": result})

@web_bp.post("/api/project/save-as")
def project_save_as():
    payload = request.get_json(silent=True) or {}
    path = str(payload.get("path", ""))
    if not path:
        return _err("path required")
    result = _wc().saveProjectAs(path)
    return jsonify({"status": "ok", "saved": result})


# ═══════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════

@web_bp.post("/api/scheduler/run")
def scheduler_run():
    wc = _wc()
    wc.scheduler()
    return jsonify({"status": "ok"})

@web_bp.get("/api/scheduler/preferences")
def scheduler_prefs_get():
    return jsonify({"mode": "deterministic", "goal_profile": "internal_asset_discovery"})

@web_bp.post("/api/scheduler/preferences")
def scheduler_prefs_save():
    return jsonify({"status": "ok"})

@web_bp.post("/api/scheduler/provider/test")
def scheduler_provider_test():
    return jsonify({"status": "ok", "message": "Provider test not yet implemented"})

@web_bp.get("/api/scheduler/provider/logs")
def scheduler_provider_logs():
    return jsonify({"logs": "No provider logs yet"})

@web_bp.post("/api/heartbeat")
def heartbeat():
    """Browser keepalive ping sent every 5 s by legion.js.
    Starts the browser-close watchdog on the very first call (wc captured
    from the request context so the watchdog thread needs no app context).
    When pings stop for _HB_TIMEOUT seconds the watchdog exits the process."""
    global _hb_last, _hb_started
    with _hb_lock:
        _hb_last = time.time()
        if not _hb_started:
            _hb_started = True
            wc_ref = _wc()
            def _watchdog(wc=wc_ref):
                while True:
                    time.sleep(5)
                    with _hb_lock:
                        last = _hb_last
                    if last is not None and (time.time() - last) > _HB_TIMEOUT:
                        try:
                            wc.saveRunningProcessOutputs()
                            wc.killRunningProcesses()
                        except Exception:
                            pass
                        os._exit(0)
            threading.Thread(target=_watchdog, name='hb-watchdog',
                             daemon=True).start()
    return jsonify({"ok": True})

@web_bp.post("/api/shutdown")
def shutdown():
    """Flush live output on browser unload (beforeunload beacon).
    Does NOT kill processes — the server is still running and the browser may
    just be refreshing (Ctrl+Shift+R, F5, navigation).  Killing here would
    destroy in-progress nmap scans on every page refresh.
    Actual process termination only happens on explicit File→Exit (/api/exit)
    or double Ctrl+C (SIGINT handler in legion.py)."""
    wc = _wc()
    wc.saveRunningProcessOutputs()
    return jsonify({"status": "ok", "message": "Output flushed"})

@web_bp.post("/api/cancel-exit")
def cancel_exit():
    """Browser cancel button — user chose not to exit (e.g. cancelled save dialog)."""
    wc = _wc()
    wc._exit_requested = False
    return jsonify({"status": "ok"})

@web_bp.post("/api/exit")
def exit_server():
    """Full exit — called by File → Exit.  Flushes output, closes project
    (handles storeWordListsOnExit), then schedules os._exit(0) so the Flask
    server terminates after the response is sent."""
    import threading, os as _os
    wc = _wc()
    wc._exit_requested = False
    wc.saveRunningProcessOutputs()
    wc.closeProject()
    def _stop():
        import time
        time.sleep(0.5)     # let response reach the browser
        _os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"status": "ok", "message": "Server stopping"})

@web_bp.get("/api/settings/ui-prefs")
def settings_ui_prefs():
    """Return UI-affecting settings so the browser can apply them at page load."""
    s = _wc().settings
    raw = getattr(s, 'general_tool_output_black_background', 'False')
    return jsonify({
        "tool_output_black_background": str(raw).strip().lower() == 'true',
    })


@web_bp.get("/api/settings/legion-conf")
def settings_get():
    s = AppSettings()
    path = str(s.actions.fileName() or "")
    if not os.path.isfile(path):
        return _err("legion.conf not found", 404)
    with open(path, "r", encoding="utf-8") as f:
        return jsonify({"path": path, "text": f.read()})

@web_bp.post("/api/settings/legion-conf")
def settings_save():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    if not isinstance(text, str):
        return _err("text required")
    s = AppSettings()
    path = str(s.actions.fileName() or "")
    # Qt6: saveSettings(saveBackup=True) — write .bak before overwriting
    if os.path.isfile(path):
        try:
            shutil.copy2(path, path + '.bak')
        except Exception:
            pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # Qt6: applySettings() — hot-reload running WebController state from new file
    _wc().applySettings()
    return jsonify({"status": "ok", "path": path})

@web_bp.get("/api/logs")
def get_logs():
    """Qt6: reloadLogFile reads log file and filters by INFO/DEBUG level.
    Primary source: in-memory handler (_mem_handler) — works without any
    stdout redirect. Falls back to /tmp/legion-web.log if it exists and
    the in-memory buffer is empty (e.g. server restarted mid-session)."""
    from app.logging.legionLog import _mem_handler
    level = request.args.get('level', 'INFO').upper()

    # In-memory lines (always available when loggers are initialised)
    lines = _mem_handler.get_lines(level)

    # Fallback: also read the legacy file if it exists and in-memory is empty
    if not lines:
        log_path = '/tmp/legion-web.log'
        if os.path.isfile(log_path):
            try:
                with open(log_path, 'r', errors='replace') as f:
                    for line in f:
                        stripped = line.rstrip()
                        if not stripped:
                            continue
                        if level == 'DEBUG':
                            lines.append(stripped)
                        else:
                            if any(lvl in stripped for lvl in
                                   (' INFO ', ' WARNING ', ' ERROR ', ' CRITICAL ')):
                                if ' DEBUG ' not in stripped:
                                    lines.append(stripped)
            except Exception as e:
                lines = [f"Error reading log file: {e}"]

    return jsonify({'lines': lines[-500:], 'level': level, 'total': len(lines)})


@web_bp.post("/api/processes/custom")
def run_custom_command():
    """Qt6: 'Run custom command' from port right-click menu.
    Substitutes [IP] and [PORT] in the command string, then runs via runCommand."""
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip()
    host_ip  = str(payload.get("host_ip", ""))
    port     = str(payload.get("port", ""))
    protocol = str(payload.get("protocol", "tcp"))
    if not command:
        return _err("command required")
    command = command.replace('[IP]', host_ip).replace('[PORT]', port)
    result = wc.runCommand(command=command, name='custom-command',
                           tabTitle=f'custom ({port}/{protocol})',
                           hostIp=host_ip, port=port, protocol=protocol)
    pid = result.get('process_id') if isinstance(result, dict) else None
    return jsonify({"status": "ok", "process_id": pid, "result": result})


@web_bp.get("/api/check-duplicate")
def check_duplicate():
    """Qt6: checkDuplicate preflight for user-triggered tool actions.
    JS calls this before running a tool to decide skip/run/prompt."""
    wc = _wc()
    tool     = request.args.get('tool', '')
    host_ip  = request.args.get('host_ip', '')
    port     = request.args.get('port', '')
    protocol = request.args.get('protocol', 'tcp')
    if not tool or not host_ip:
        return _err("tool and host_ip required")
    result = wc.checkDuplicate(tool, host_ip, port, protocol)
    return jsonify({"result": result})


@web_bp.get("/api/brute/defaults")
def brute_defaults():
    """Return brute-force defaults from legion.conf for pre-filling the UI."""
    wc = _wc()
    s = wc.settings
    def _split_services(val):
        return [x.strip() for x in str(val).split(',') if x.strip()]
    return jsonify({
        "default_username":     getattr(s, 'brute_default_username', ''),
        "default_password":     getattr(s, 'brute_default_password', ''),
        "username_wordlist":    getattr(s, 'brute_username_wordlist_path', ''),
        "password_wordlist":    getattr(s, 'brute_password_wordlist_path', ''),
        "no_username_services": _split_services(getattr(s, 'brute_no_username_services', '')),
        "no_password_services": _split_services(getattr(s, 'brute_no_password_services', '')),
    })


@web_bp.post("/api/brute/run")
def brute_run():
    """Qt6: callHydra → buildHydraCommand → controller.runCommand('hydra').
    Builds the hydra command and runs it via wc.runCommand so the process
    appears in the process table and output is captured."""
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    ip       = str(payload.get('ip', '')).strip()
    port     = str(payload.get('port', '')).strip()
    service  = str(payload.get('service', '')).strip()
    userlist = str(payload.get('userlist', '')).strip()
    passlist = str(payload.get('passlist', '')).strip()
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', '')).strip()
    combo    = str(payload.get('combo', '')).strip()
    options  = str(payload.get('options', '')).strip()

    if not ip or not port or not service:
        return _err("ip, port, and service are required")

    from app.timing import getTimestamp
    output_folder = wc.logic.activeProject.properties.outputFolder
    outputfile = os.path.join(output_folder, f"{getTimestamp()}-hydra-{ip}-{port}")

    # Qt6: bWidget.buildHydraCommand(runningFolder, userlistPath, passlistPath)
    hydra_bin = getattr(wc.settings, 'tools_path_hydra', '').strip() or 'hydra'
    parts = [hydra_bin, '-s', port]

    if combo:
        # Combo file: colon-separated user:pass lines → hydra -C
        parts += ['-C', combo]
    else:
        # Username: wordlist (-L) takes priority over single (-l)
        if userlist:
            parts += ['-L', userlist]
        elif username:
            parts += ['-l', username]

        # Password: wordlist (-P) takes priority over single (-p)
        if passlist:
            parts += ['-P', passlist]
        elif password:
            parts += ['-p', password]

    if not combo and not userlist and not username and not passlist and not password:
        return _err("at least a username, password, wordlist, or combo file is required")

    if options:
        parts += options.split()
    parts += ['-u', '-o', outputfile + '.txt', '-f', ip, service]

    command = ' '.join(parts)
    tab_title = f"hydra ({port}/tcp)"
    result = wc.runCommand(command=command, name='hydra',
                           tabTitle=tab_title, hostIp=ip,
                           port=port, protocol='tcp',
                           outputfile=outputfile, run_actions=False)
    return jsonify({"status": "ok", "process_id": result.get('process_id'),
                    "command": command})


@web_bp.get("/api/export/json")
def export_json():
    """Export all project data as a structured JSON document.
    Includes hosts, ports, services, notes, CVEs, scripts, and processes.
    Suitable for archiving, reporting, or importing into other tools."""
    logic = _logic()
    wc = _wc()
    filters = Filters()

    session = logic.activeProject.database.session()
    try:
        from db.entities.host import hostObj
        hosts_raw = session.query(hostObj).filter(hostObj.status != 'down').all()

        export = {
            "version": "1.0",
            "project": getattr(logic.activeProject.properties, 'projectName', ''),
            "exported_at": str(__import__('datetime').datetime.utcnow()),
            "hosts": [],
        }

        repo = logic.activeProject.repositoryContainer
        for h in hosts_raw:
            host_ip = getattr(h, 'ipv4', '') or getattr(h, 'ip', '')
            host_id = h.id

            # Ports
            ports_raw = repo.portRepository.getPortsByHostId(host_id) or []
            ports = []
            for p in ports_raw:
                svc = repo.serviceRepository.getServiceById(p.serviceId) if p.serviceId else None
                ports.append({
                    "port": str(p.portId),
                    "protocol": str(p.protocol),
                    "state": str(p.state),
                    "service": getattr(svc, 'name', '') if svc else '',
                    "product": getattr(svc, 'product', '') if svc else '',
                    "version": getattr(svc, 'version', '') if svc else '',
                })

            # Note
            note_obj = repo.noteRepository.getNoteByHostId(host_id)
            note_text = getattr(note_obj, 'text', '') if note_obj else ''

            # CVEs
            cves_raw = wc.getCvesFromDB(host_ip) or []
            cves = [{"name": c.get('name', '') if isinstance(c, dict) else getattr(c, 'name', ''),
                     "severity": str(c.get('severity', '') if isinstance(c, dict) else getattr(c, 'severity', ''))}
                    for c in cves_raw]

            export["hosts"].append({
                "ip": host_ip,
                "hostname": getattr(h, 'hostname', '') or '',
                "os": getattr(h, 'osMatch', '') or '',
                "status": getattr(h, 'status', '') or '',
                "checked": str(getattr(h, 'checked', 'False')) == 'True',
                "note": note_text,
                "ports": ports,
                "cves": cves,
            })

        return jsonify(export)
    finally:
        session.close()

@web_bp.get("/api/export/csv")
def export_csv():
    """Qt6: CSV export — one row per host+port combination.
    Columns: ip, hostname, os, port, protocol, state, service, product, version."""
    import csv, io, datetime
    logic = _logic()
    filters = _filters()

    hosts = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ip', 'hostname', 'os', 'port', 'protocol', 'state', 'service', 'product', 'version'])

    for h in (hosts or []):
        ip       = h.get('ip', '')       if isinstance(h, dict) else getattr(h, 'ip', '')
        hostname = h.get('hostname', '') if isinstance(h, dict) else getattr(h, 'hostname', '')
        os_name  = h.get('os', '')       if isinstance(h, dict) else getattr(h, 'osMatch', '')
        host_id  = h.get('id')           if isinstance(h, dict) else getattr(h, 'id', None)
        ports = logic.activeProject.repositoryContainer.portRepository.getPortsAndServicesByHostIP(ip, filters)
        if ports:
            for p in ports:
                writer.writerow([
                    ip, hostname, os_name,
                    p.get('portId', ''), p.get('protocol', ''),
                    p.get('state', ''), p.get('name', ''),
                    p.get('product', ''), p.get('version', ''),
                ])
        else:
            writer.writerow([ip, hostname, os_name, '', '', '', '', '', ''])

    csv_text = output.getvalue()
    filename = f"legion-export-{datetime.date.today()}.csv"
    from flask import Response
    return Response(
        csv_text,
        status=200,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ═══════════════════════════════════════════
# File browser (replaces QFileDialog)
# ═══════════════════════════════════════════

@web_bp.get("/api/files/browse")
def files_browse():
    path = str(request.args.get("path", os.path.expanduser("~")))
    file_filter = str(request.args.get("filter", ""))
    show_hidden = request.args.get("hidden", "false") == "true"
    if not os.path.isdir(path):
        path = os.path.dirname(path) if os.path.isdir(os.path.dirname(path)) else os.path.expanduser("~")
    entries = []
    try:
        for name in sorted(os.listdir(path), key=str.lower):
            if not show_hidden and name.startswith('.'):
                continue
            full = os.path.join(path, name)
            try:
                st = os.stat(full)
                is_dir = stat.S_ISDIR(st.st_mode)
                if not is_dir and file_filter and not name.endswith(file_filter):
                    continue
                entries.append({"name": name, "path": full, "is_dir": is_dir,
                                "size": st.st_size if not is_dir else 0})
            except (PermissionError, OSError):
                continue
    except PermissionError:
        pass
    parent = os.path.dirname(path)
    return jsonify({"current": path, "parent": parent if parent != path else None, "entries": entries})


# ═══════════════════════════════════════════
# Config profiles (from configDialog.py)
# ═══════════════════════════════════════════

_PROFILES_DIR = os.path.expanduser('~/.local/share/legion/profiles')
_ACTIVE_FILE = os.path.expanduser('~/.local/share/legion/active_profile.txt')
_WORKING_CONF = os.path.expanduser('~/.local/share/legion/legion.conf')

def _ensure_profiles():
    os.makedirs(_PROFILES_DIR, exist_ok=True)
    default = os.path.join(_PROFILES_DIR, 'default.conf')
    if not os.path.exists(default) and os.path.exists(_WORKING_CONF):
        shutil.copy(_WORKING_CONF, default)

@web_bp.get("/api/config/profiles")
def config_profiles():
    _ensure_profiles()
    active = 'default'
    if os.path.exists(_ACTIVE_FILE):
        try:
            active = open(_ACTIVE_FILE).read().strip() or 'default'
        except Exception:
            pass
    profiles = []
    for fn in sorted(os.listdir(_PROFILES_DIR)):
        if fn.endswith('.conf'):
            name = fn[:-5]
            path = os.path.join(_PROFILES_DIR, fn)
            try:
                text = open(path, 'r', encoding='utf-8').read()
            except Exception:
                text = ''
            profiles.append({"name": name, "path": path, "active": name == active, "text": text})
    return jsonify({"profiles": profiles, "active": active})

def _validate_legion_conf(config_text):
    """Port of configDialog.py validateConfigSyntax + validateSettingNames.
    Returns list of error strings. Empty list = valid."""
    # Section element counts (Qt6: section_element_counts)
    section_element_counts = {
        'HostActions': 2, 'PortActions': 3, 'PortTerminalActions': 3, 'SchedulerSettings': 2,
    }
    # Fixed valid keys per section (Qt6: valid_settings)
    fixed_section_keys = {
        'GeneralSettings': {'log-directory','default-terminal','tool-output-black-background',
                            'screenshooter-timeout','web-services','enable-scheduler',
                            'enable-scheduler-on-import','max-fast-processes','max-slow-processes','tool-duplication'},
        'BruteSettings': {'store-cleartext-passwords-on-exit','username-wordlist-path','password-wordlist-path',
                          'default-username','default-password','services','no-username-services','no-password-services'},
        'ToolSettings': {'nmap-path','hydra-path','cutycapt-path','texteditor-path','pyshodan-api-key'},
        'StagedNmapSettings': {'stage1-ports','stage2-ports','stage3-ports','stage4-ports','stage5-ports','stage6-ports'},
    }
    dynamic_sections = {'HostActions','PortActions','PortTerminalActions','SchedulerSettings','MatchSettings','GUISettings'}
    all_valid_sections = set(fixed_section_keys.keys()) | dynamic_sections

    def parse_csv(value):
        """Parse comma-separated values respecting quotes."""
        elements, current, in_quotes, qchar = [], [], False, None
        for ch in value:
            if ch in ('"', "'"):
                if not in_quotes: in_quotes, qchar = True, ch
                elif ch == qchar: in_quotes, qchar = False, None
                current.append(ch)
            elif ch == ',' and not in_quotes:
                elements.append(''.join(current).strip()); current = []
            else:
                current.append(ch)
        last = ''.join(current).strip()
        # Always include the last element when preceding elements exist —
        # a trailing comma with empty value (e.g. "label,command,") is intentional:
        # it means no service-filter restriction (applies to all services).
        if last or elements:
            elements.append(last)
        return elements

    errors = []
    current_section = None
    for line_num, line in enumerate(config_text.split('\n'), 1):
        s = line.strip()
        if not s or s.startswith('#') or s.startswith(';'):
            continue
        if s.startswith('['):
            if not s.endswith(']'):
                errors.append(f"Line {line_num}: Unclosed section header — {s}")
                continue
            current_section = s[1:-1].strip()
            if not current_section:
                errors.append(f"Line {line_num}: Empty section name []")
            elif current_section not in all_valid_sections:
                errors.append(f"Line {line_num}: Unknown section [{current_section}] — "
                               f"valid: {', '.join(sorted(all_valid_sections))}")
            continue
        if '=' not in s:
            errors.append(f"Line {line_num}: Missing '=' — {s}")
            continue
        key, value = s[:s.index('=')].strip(), s[s.index('=')+1:].strip()
        if not key:
            errors.append(f"Line {line_num}: Empty key before '='")
            continue
        if current_section is None:
            errors.append(f"Line {line_num}: Key=value outside any section — {s}")
            continue
        # Quote balance check
        if value.count('"') % 2 != 0:
            errors.append(f"Line {line_num}: Unbalanced double quotes in key '{key}'")
        if value.count("'") % 2 != 0:
            errors.append(f"Line {line_num}: Unbalanced single quotes in key '{key}'")
        # Fixed section key validation
        if current_section in fixed_section_keys and key not in fixed_section_keys[current_section]:
            errors.append(f"Line {line_num}: Unknown setting '{key}' in [{current_section}] — "
                           f"valid: {', '.join(sorted(fixed_section_keys[current_section]))}")
        # Staged nmap port value validation
        # Format: KEYWORD or KEYWORD|spec  (e.g. PORTS|T:80,443 or NSE|vulners)
        # The pipe is only valid as a separator after an uppercase keyword —
        # validateNmapPorts is applied to the spec part only, not the full raw value.
        if current_section == 'StagedNmapSettings' and key in fixed_section_keys.get('StagedNmapSettings', set()):
            if value:
                raw = value.strip('"\'')          # strip surrounding quotes
                valid_keywords = {'PORTS', 'NSE', 'NOOP', 'SKIP'}
                if '|' in raw:
                    keyword, spec = raw.split('|', 1)
                    if keyword not in valid_keywords:
                        errors.append(
                            f"Line {line_num}: Unknown keyword '{keyword}' in '{key}': {value!r} "
                            f"— valid keywords before '|' are: {', '.join(sorted(valid_keywords))}")
                    elif keyword == 'PORTS' and spec and not validateNmapPorts(spec):
                        errors.append(
                            f"Line {line_num}: Invalid port spec after 'PORTS|' in '{key}': {spec!r} "
                            f"— only digits, commas, hyphens, colons, T:/U: prefixes, and wildcards allowed")
                    # NSE|scriptname: script name is always alphanumeric — no further check needed
                else:
                    # No pipe: bare keyword or legacy plain port spec
                    if raw not in valid_keywords and not validateNmapPorts(raw):
                        errors.append(
                            f"Line {line_num}: Invalid staged nmap value in '{key}': {value!r} "
                            f"— use PORTS|T:ports or NSE|script format, or a bare keyword")
        # Element count validation for dynamic sections
        if current_section in section_element_counts:
            expected = section_element_counts[current_section]
            actual = len(parse_csv(value))
            if actual != expected:
                errors.append(f"Line {line_num}: [{current_section}] key '{key}' has {actual} "
                               f"comma-separated elements, expected {expected}")
    return errors


@web_bp.post("/api/config/profiles/<name>/save")
def config_save(name):
    _ensure_profiles()
    text = (request.get_json(silent=True) or {}).get("text")
    if not isinstance(text, str): return _err("text required")
    path = os.path.join(_PROFILES_DIR, f'{name}.conf')
    if not os.path.exists(path): return _err(f"Profile '{name}' not found", 404)

    # Validate syntax before saving (Qt6: configDialog.py validateConfigSyntax + validateSettingNames)
    errors = _validate_legion_conf(text)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400

    open(path, 'w', encoding='utf-8').write(text)

    # If saving the active profile, hot-reload settings immediately
    active = 'default'
    if os.path.exists(_ACTIVE_FILE):
        try: active = open(_ACTIVE_FILE).read().strip() or 'default'
        except Exception: pass
    applied = False
    if name == active:
        import shutil as _shutil
        _shutil.copy(path, _WORKING_CONF)
        _wc().applySettings()
        applied = True
    return jsonify({"status": "ok", "applied": applied})

@web_bp.post("/api/config/profiles/<name>/activate")
def config_activate(name):
    _ensure_profiles()
    path = os.path.join(_PROFILES_DIR, f'{name}.conf')
    if not os.path.exists(path): return _err(f"Profile '{name}' not found", 404)
    shutil.copy(path, _WORKING_CONF)
    open(_ACTIVE_FILE, 'w').write(name)
    _wc().applySettings()
    return jsonify({"status": "ok", "active": name})

@web_bp.post("/api/config/profiles/create")
def config_create():
    _ensure_profiles()
    p = request.get_json(silent=True) or {}
    name = str(p.get("name", "")).strip()
    if not name: return _err("name required")
    dest = os.path.join(_PROFILES_DIR, f'{name}.conf')
    if os.path.exists(dest): return _err(f"'{name}' exists")
    src = os.path.join(_PROFILES_DIR, f'{p.get("copy_from", "default")}.conf')
    if not os.path.exists(src): src = _WORKING_CONF
    shutil.copy(src, dest)
    return jsonify({"status": "ok"})

@web_bp.post("/api/config/profiles/<name>/rename")
def config_rename(name):
    if name == 'default': return _err("Cannot rename default")
    new = str((request.get_json(silent=True) or {}).get("new_name", "")).strip()
    if not new: return _err("new_name required")
    old_p = os.path.join(_PROFILES_DIR, f'{name}.conf')
    new_p = os.path.join(_PROFILES_DIR, f'{new}.conf')
    if not os.path.exists(old_p): return _err("Not found", 404)
    if os.path.exists(new_p): return _err(f"'{new}' exists")
    os.rename(old_p, new_p)
    return jsonify({"status": "ok"})

@web_bp.post("/api/config/profiles/<name>/duplicate")
def config_duplicate(name):
    new = str((request.get_json(silent=True) or {}).get("new_name", f"{name}_copy")).strip()
    src = os.path.join(_PROFILES_DIR, f'{name}.conf')
    dest = os.path.join(_PROFILES_DIR, f'{new}.conf')
    if not os.path.exists(src): return _err("Not found", 404)
    if os.path.exists(dest): return _err(f"'{new}' exists")
    shutil.copy(src, dest)
    return jsonify({"status": "ok"})

@web_bp.post("/api/config/profiles/<name>/delete")
def config_delete(name):
    if name == 'default': return _err("Cannot delete default")
    active = open(_ACTIVE_FILE).read().strip() if os.path.exists(_ACTIVE_FILE) else 'default'
    if name == active: return _err("Cannot delete active profile")
    path = os.path.join(_PROFILES_DIR, f'{name}.conf')
    if not os.path.exists(path): return _err("Not found", 404)
    os.remove(path)
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════
# PTY Terminal sessions
# ═══════════════════════════════════════════

import pty as _pty
import uuid as _uuid
import select as _select
import struct as _struct
import fcntl as _fcntl
import termios as _termios
import threading as _threading
import subprocess as _subprocess
import logging as _logging

_term_log = _logging.getLogger('legion')

# Maps session_id → _TerminalSession
_terminal_sessions: dict = {}
# Maps process_id (int) → session_id (str) — so snapshot can attach session_id to processes
_terminal_process_sessions: dict = {}


class _TerminalSession:
    """Manages a PTY bash session. Bash always hosts the PTY; the tool command
    (if any) is written to bash's stdin after 500ms — exactly as Qt6 does."""

    def __init__(self, session_id: str, command: str = None):
        self.id = session_id
        self.command = command
        self._buf = bytearray()
        self._lock = _threading.Lock()
        self._alive = True

        master_fd, slave_fd = _pty.openpty()

        # Set initial terminal size BEFORE starting bash (Qt6: view.py:5769-5779)
        # Without this bash thinks terminal is 0 cols → readline breaks
        try:
            winsize = _struct.pack('HHHH', 24, 80, 0, 0)
            _fcntl.ioctl(slave_fd, _termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

        # Set proper terminal attributes on slave PTY (Qt6: view.py:5769-5779)
        try:
            attrs = _termios.tcgetattr(slave_fd)
            attrs[0] = attrs[0] | _termios.BRKINT | _termios.ICRNL | _termios.IXON
            attrs[1] = attrs[1] | _termios.OPOST
            attrs[3] = (attrs[3] | _termios.ECHO | _termios.ECHOE | _termios.ECHOK
                        | _termios.ICANON | _termios.ISIG)
            _termios.tcsetattr(slave_fd, _termios.TCSANOW, attrs)
        except Exception:
            pass

        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        env['COLUMNS'] = '80'
        env['LINES'] = '24'
        self.proc = _subprocess.Popen(
            ['bash', '--login'],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            preexec_fn=os.setsid, env=env
        )
        os.close(slave_fd)
        self.master_fd = master_fd

        # Background reader thread
        t = _threading.Thread(target=self._reader, daemon=True, name=f'term-{session_id[:8]}')
        t.start()

        # Dispatch command after 500ms (mirrors Qt6 QTimer.singleShot(500, sendCommand))
        if command:
            _threading.Timer(0.5, self._send_command).start()

    def _reader(self):
        while self._alive and self.proc.poll() is None:
            try:
                r, _, _ = _select.select([self.master_fd], [], [], 0.05)
                if r:
                    data = os.read(self.master_fd, 4096)
                    if data:
                        with self._lock:
                            self._buf.extend(data)
            except OSError:
                break
        self._alive = False

    def _send_command(self):
        if self.command and self._alive:
            try:
                os.write(self.master_fd, (self.command + '\n').encode('utf-8'))
                _term_log.info(f'[Terminal {self.id[:8]}] Dispatched: {self.command[:80]}')
            except OSError as e:
                _term_log.error(f'[Terminal {self.id[:8]}] Command dispatch failed: {e}')

    def write(self, data: bytes):
        os.write(self.master_fd, data)

    def read_from(self, offset: int) -> bytes:
        with self._lock:
            return bytes(self._buf[offset:])

    def resize(self, rows: int, cols: int):
        try:
            winsize = _struct.pack('HHHH', rows, cols, 0, 0)
            _fcntl.ioctl(self.master_fd, _termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        return self._alive and self.proc.poll() is None

    def close(self):
        self._alive = False
        try:
            self.proc.terminate()
        except Exception:
            pass
        try:
            os.close(self.master_fd)
        except Exception:
            pass


@web_bp.post("/api/terminal/start")
def terminal_start():
    """Start a new PTY bash session, optionally with a command to execute."""
    payload = request.get_json(silent=True) or {}
    label = str(payload.get('label', 'terminal'))
    host_ip = str(payload.get('host_ip', ''))
    command = payload.get('command')  # None = plain bash; string = dispatched after 500ms

    session_id = str(_uuid.uuid4())
    session = _TerminalSession(session_id, command=command)
    _terminal_sessions[session_id] = session

    # Create a process row in the DB with status='Interactive'
    wc = _wc()
    logic = _logic()
    from app.timing import getTimestamp
    from controller.web_controller import WebProcessStub

    start_time = getTimestamp(True)
    output_folder = logic.activeProject.properties.outputFolder
    outputfile = os.path.join(output_folder, f'{getTimestamp()}-terminal')

    proc_stub = WebProcessStub(
        name=label, tabTitle=label, hostIp=host_ip,
        port='', protocol='tcp',
        command=command or 'bash --login',
        startTime=start_time, outputfile=outputfile
    )

    processRepo = logic.activeProject.repositoryContainer.processRepository
    db_id = str(processRepo.storeProcess(proc_stub))
    processRepo.storeProcessInteractiveStatus(db_id)

    _terminal_process_sessions[int(db_id)] = session_id

    _term_log.info(f'[Terminal] Started session {session_id[:8]} process_id={db_id} label={label}')

    return jsonify({
        "status": "ok",
        "session_id": session_id,
        "process_id": int(db_id),
    })


@web_bp.get("/api/terminal/<session_id>/output")
def terminal_output(session_id):
    session = _terminal_sessions.get(session_id)
    if not session:
        return _err("Session not found", 404)
    offset = int(request.args.get('offset', 0))
    data = session.read_from(offset)
    return jsonify({
        "data": data.decode('utf-8', errors='replace'),
        "offset": offset,
        "next_offset": offset + len(data),   # byte length — NOT string length
        "alive": session.alive,
    })


@web_bp.post("/api/terminal/<session_id>/input")
def terminal_input(session_id):
    session = _terminal_sessions.get(session_id)
    if not session:
        return _err("Session not found", 404)
    payload = request.get_json(silent=True) or {}
    data = payload.get('data', '')
    if data:
        session.write(data.encode('utf-8'))
    return jsonify({"status": "ok"})


@web_bp.post("/api/terminal/<session_id>/resize")
def terminal_resize(session_id):
    session = _terminal_sessions.get(session_id)
    if not session:
        return _err("Session not found", 404)
    payload = request.get_json(silent=True) or {}
    rows = int(payload.get('rows', 24))
    cols = int(payload.get('cols', 80))
    session.resize(rows, cols)
    return jsonify({"status": "ok"})


@web_bp.delete("/api/terminal/<session_id>")
def terminal_delete(session_id):
    session = _terminal_sessions.pop(session_id, None)
    if not session:
        return _err("Session not found", 404)
    session.close()
    # Remove from process→session map and mark process as Killed in DB
    to_remove = [pid for pid, sid in _terminal_process_sessions.items() if sid == session_id]
    for pid in to_remove:
        del _terminal_process_sessions[pid]
        try:
            logic = _logic()
            processRepo = logic.activeProject.repositoryContainer.processRepository
            processRepo.storeProcessKillStatus(str(pid))
        except Exception as e:
            _term_log.error(f'[Terminal] Failed to mark process {pid} as killed: {e}')
    _term_log.info(f'[Terminal] Deleted session {session_id[:8]}')
    return jsonify({"status": "ok"})
