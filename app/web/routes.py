"""
Flask routes — calls YOUR controller.py logic via WebController.
No runtime.py. No upstream reimplementation.
"""

import datetime
import json
import os
import shutil
import stat

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory
from app.settings import AppSettings, Settings
from app.auxiliary import Filters

web_bp = Blueprint("web", __name__)

def _wc():
    return current_app.config['LEGION_WC']

def _logic():
    return current_app.config['LEGION_LOGIC']

def _err(msg, code=400):
    return jsonify({"status": "error", "error": str(msg)}), code

def _filters():
    return Filters()


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
    wc = _wc()
    logic = _logic()
    filters = _filters()

    hosts_raw = logic.activeProject.repositoryContainer.hostRepository.getHosts(filters)
    hosts = []
    total_ports = 0
    for h in (hosts_raw or []):
        hid = h.get('id', '') if isinstance(h, dict) else getattr(h, 'id', '')
        hip = h.get('ipv4', '') or h.get('ip', '') if isinstance(h, dict) else getattr(h, 'ipv4', '') or getattr(h, 'ip', '')
        hostname = h.get('hostname', '') if isinstance(h, dict) else getattr(h, 'hostname', '')
        osm = h.get('osMatch', '') if isinstance(h, dict) else getattr(h, 'osMatch', '')
        status = h.get('status', '') if isinstance(h, dict) else getattr(h, 'status', '')
        ports = logic.activeProject.repositoryContainer.portRepository.getPortsByHostId(hid) if hid else []
        port_count = len(ports) if ports else 0
        total_ports += port_count
        hosts.append({"id": hid, "ip": hip, "hostname": hostname, "os": osm,
                       "status": status, "open_ports": port_count})

    services_raw = logic.activeProject.repositoryContainer.serviceRepository.getServiceNames(filters)
    services = []
    for s in (services_raw or []):
        if isinstance(s, dict):
            sname = s.get('name', '')
        elif hasattr(s, 'name'):
            sname = s.name
        elif hasattr(s, '__getitem__'):
            sname = str(s[0])
        else:
            sname = str(s)
        services.append({"service": sname, "host_count": 1, "port_count": 1, "protocols": ["tcp"]})

    tools = wc.getContextMenuForServiceName('*')
    tool_list = [{"label": t.get("label", ""), "tool_id": t.get("tool_id", t.get("label", "")),
                   "run_count": 0, "last_status": "", "runnable": True,
                   "danger_categories": []} for t in tools if t.get("action") == "port-action"]

    procs_raw = logic.activeProject.repositoryContainer.processRepository.getProcesses(filters)
    processes = []
    running = 0
    finished = 0
    for p in (procs_raw or []):
        if isinstance(p, dict):
            proc = dict(p)
        else:
            proc = {"name": getattr(p, 'name', ''), "hostIp": getattr(p, 'hostIp', ''),
                     "port": getattr(p, 'port', ''), "protocol": getattr(p, 'protocol', ''),
                     "status": getattr(p, 'status', ''), "pid": getattr(p, 'pid', ''),
                     "command": getattr(p, 'command', '')}
        # Ensure 'id' key exists (some returns use 'pid' or 'progress' as pseudo-id)
        if 'id' not in proc:
            proc['id'] = proc.get('pid', proc.get('progress', ''))
        status = proc.get("status", "")
        if status == "Running":
            running += 1
        else:
            finished += 1
        processes.append(proc)

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
                     "is_temporary": getattr(logic.activeProject.properties, "isTemporary", True)},
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
    chunk = output[offset:offset + max_chars]
    status = proc.get("status", "")
    return jsonify({
        "id": process_id, "name": proc.get("name", ""), "hostIp": proc.get("hostIp", ""),
        "port": proc.get("port", ""), "command": proc.get("command", ""), "status": status,
        "output_chunk": chunk, "output_length": len(output),
        "offset": offset, "next_offset": offset + len(chunk),
        "completed": status not in ("Running", "Waiting"),
    })

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
    _wc().handleProcessAction(process_id, 'clear')
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
    wc = _wc()
    payload = request.get_json(silent=True) or {}
    targets = str(payload.get("targets", "")).strip()
    if not targets:
        return _err("targets required")
    scan_mode = str(payload.get("scan_mode", "easy"))
    staged = payload.get("staged", False)
    discovery = payload.get("discovery", True)
    mode = 'Easy'
    if staged:
        result = wc.runStagedNmap(targets, discovery=discovery)
    else:
        result = wc.addHosts(targets, runHostDiscovery=discovery, runStagedNmap=staged,
                              nmapSpeed='4', scanMode=mode)
    return jsonify({"status": "ok", "result": result})

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
    else:
        result = wc.handleHostAction(ip, host_id, action)
    return jsonify({"status": "ok", "result": result})

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
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return jsonify({"status": "ok", "path": path})

@web_bp.get("/api/export/json")
def export_json():
    # Reuse snapshot
    from flask import redirect
    return redirect("/api/snapshot")

@web_bp.get("/api/export/csv")
def export_csv():
    return jsonify({"status": "ok", "note": "CSV export not yet implemented"})


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

@web_bp.post("/api/config/profiles/<name>/save")
def config_save(name):
    _ensure_profiles()
    text = (request.get_json(silent=True) or {}).get("text")
    if not isinstance(text, str): return _err("text required")
    path = os.path.join(_PROFILES_DIR, f'{name}.conf')
    if not os.path.exists(path): return _err(f"Profile '{name}' not found", 404)
    open(path, 'w', encoding='utf-8').write(text)
    return jsonify({"status": "ok"})

@web_bp.post("/api/config/profiles/<name>/activate")
def config_activate(name):
    _ensure_profiles()
    path = os.path.join(_PROFILES_DIR, f'{name}.conf')
    if not os.path.exists(path): return _err(f"Profile '{name}' not found", 404)
    shutil.copy(path, _WORKING_CONF)
    open(_ACTIVE_FILE, 'w').write(name)
    _wc().settings = Settings(AppSettings())
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
