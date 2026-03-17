/* ================================================================
   LEGION – Flask frontend JS
   1:1 replica of Qt6 ui/view.py + controller/controller.py logic
   ================================================================ */
'use strict';

/* ── State (mirrors ui/ViewState.py) ── */
var L = {
    hosts: [],
    services: [],
    tools: [],
    processes: [],
    selectedHostId: null,
    selectedHostIp: null,
    selectedService: null,
    selectedTool: null,
    selectedProcessId: null,
    hostCache: {},
    pollTimer: null,
    procPollTimer: null,
    snapshot: null,
    version: 'v1.0-rewrite',
};

/* ── Utilities ── */
function $(id) { return document.getElementById(id); }
function esc(s) { var d = document.createElement('div'); d.textContent = String(s||''); return d.innerHTML; }
function setText(id, t) { var el = $(id); if (el) el.textContent = String(t||''); }

function fetchJson(url) {
    return fetch(url).then(function(r) {
        if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
        return r.json();
    });
}
function postJson(url, body) {
    return fetch(url, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body||{})
    }).then(function(r) { return r.json(); });
}

/* ── ANSI parser (simplified from upstream) ── */
function ansiToHtml(raw) {
    var text = String(raw||'');
    var result = '';
    var i = 0;
    var openSpan = false;
    var fgColors = {30:'black',31:'red',32:'green',33:'yellow',34:'blue',35:'magenta',36:'cyan',37:'white',
                    90:'bright-black',91:'bright-red',92:'bright-green',93:'bright-yellow',
                    94:'bright-blue',95:'bright-magenta',96:'bright-cyan',97:'bright-white'};
    while (i < text.length) {
        if (text[i] === '\x1b' && text[i+1] === '[') {
            var j = i+2;
            while (j < text.length && text[j] !== 'm' && j - i < 20) j++;
            if (text[j] === 'm') {
                var codes = text.substring(i+2, j).split(';');
                if (openSpan) { result += '</span>'; openSpan = false; }
                var cls = [];
                for (var c = 0; c < codes.length; c++) {
                    var code = parseInt(codes[c], 10);
                    if (code === 0) { /* reset */ }
                    else if (code === 1) cls.push('ansi-bold');
                    else if (fgColors[code]) cls.push('ansi-fg-' + fgColors[code]);
                    else if (code >= 40 && code <= 47) {
                        var bgName = fgColors[code-10];
                        if (bgName) cls.push('ansi-bg-' + bgName);
                    }
                }
                if (cls.length) { result += '<span class="' + cls.join(' ') + '">'; openSpan = true; }
                i = j + 1;
                continue;
            }
        }
        var ch = text[i];
        if (ch === '<') result += '&lt;';
        else if (ch === '>') result += '&gt;';
        else if (ch === '&') result += '&amp;';
        else result += ch;
        i++;
    }
    if (openSpan) result += '</span>';
    return result;
}

/* ── Tab switching (generic — matches QTabWidget behavior) ── */
function initTabBar(barId) {
    var bar = $(barId);
    if (!bar) return;
    bar.addEventListener('click', function(e) {
        var btn = e.target.closest('.tab-btn');
        if (!btn || !btn.dataset.tab) return;
        bar.querySelectorAll('.tab-btn').forEach(function(t) { t.classList.remove('active'); });
        btn.classList.add('active');
        var widget = bar.closest('.tab-widget') || bar.parentElement;
        widget.querySelectorAll(':scope > .tab-content').forEach(function(c) { c.classList.remove('active'); });
        var panel = $(btn.dataset.tab);
        if (panel) panel.classList.add('active');
    });
}

/* ── Menu bar dropdowns ── */
function initMenuBar() {
    document.querySelectorAll('#menubar .menu-item').forEach(function(item) {
        item.querySelector('.menu-btn').addEventListener('click', function(e) {
            e.stopPropagation();
            var wasOpen = item.classList.contains('open');
            document.querySelectorAll('#menubar .menu-item.open').forEach(function(m) { m.classList.remove('open'); });
            if (!wasOpen) item.classList.add('open');
        });
    });
    document.addEventListener('click', function() {
        document.querySelectorAll('#menubar .menu-item.open').forEach(function(m) { m.classList.remove('open'); });
    });
}

/* ── Splitter drag ── */
function initSplitter(splitterId, target, prop, min, max) {
    var sp = $(splitterId);
    if (!sp) return;
    var el = typeof target === 'string' ? $(target) : target;
    if (!el) return;
    var dragging = false, startPos = 0, startSize = 0;
    var isH = sp.classList.contains('hsplitter');

    sp.addEventListener('mousedown', function(e) {
        dragging = true; startPos = isH ? e.clientY : e.clientX;
        startSize = isH ? el.offsetHeight : el.offsetWidth;
        sp.classList.add('dragging');
        document.body.style.cursor = isH ? 'ns-resize' : 'ew-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        var delta = (isH ? e.clientY : e.clientX) - startPos;
        var newSize = Math.max(min||80, Math.min(max||800, startSize + (isH ? delta : delta)));
        el.style[prop] = newSize + 'px';
    });
    document.addEventListener('mouseup', function() {
        if (!dragging) return;
        dragging = false; sp.classList.remove('dragging');
        document.body.style.cursor = ''; document.body.style.userSelect = '';
    });
}

/* ================================================================
   RENDERING (mirrors view.py update methods)
   ================================================================ */

/* ── Hosts table (view.py:updateHostsTableView → gui.py:HostsTableView) ── */
function renderHosts(hosts) {
    L.hosts = hosts || [];
    var body = $('hosts-body');
    if (!body) return;
    body.innerHTML = '';
    var overlay = $('add-hosts-overlay');
    if (overlay) overlay.classList.toggle('visible', L.hosts.length === 0);
    var tableWrap = $('hosts-table-wrap');
    if (tableWrap) tableWrap.style.display = L.hosts.length ? '' : 'none';

    L.hosts.forEach(function(h) {
        var tr = document.createElement('tr');
        tr.dataset.hostId = h.id || '';
        tr.dataset.hostIp = h.ip || '';
        if (L.selectedHostId && parseInt(h.id) === L.selectedHostId) tr.classList.add('selected');
        tr.style.cursor = 'pointer';
        tr.innerHTML = '<td>' + esc(h.os||'') + '</td><td>' + esc(h.ip||'') + (h.hostname && h.hostname !== h.ip ? ' ('+esc(h.hostname)+')' : '') + '</td>';
        body.appendChild(tr);
    });
    setText('stat-hosts', L.hosts.length);
}

/* ── Services table (left) (view.py:updateServiceNamesTableView) ── */
function renderServiceNames(services) {
    L.services = services || [];
    var body = $('services-body');
    if (!body) return;
    body.innerHTML = '';
    L.services.forEach(function(s) {
        var tr = document.createElement('tr');
        tr.dataset.service = s.service || '';
        tr.style.cursor = 'pointer';
        if (L.selectedService === s.service) tr.classList.add('selected');
        tr.innerHTML = '<td>' + esc(s.service||'') + '</td>';
        body.appendChild(tr);
    });
}

/* ── Tools table (left) — only tools that actually ran (view.py:updateToolsTableView) ── */
function renderTools(tools) {
    /* Show all tools — Qt6 shows all available tools in the left panel,
       not just ones that ran. run_count shown in the table so user knows. */
    L.tools = tools || [];
    var body = $('tools-body');
    if (!body) return;
    body.innerHTML = '';
    L.tools.forEach(function(t) {
        var tr = document.createElement('tr');
        tr.dataset.toolId = t.tool_id || '';
        tr.style.cursor = 'pointer';
        if (L.selectedTool === t.tool_id) tr.classList.add('selected');
        var runCount = t.run_count || 0;
        var style = runCount > 0 ? 'font-weight:600' : 'color:var(--disabled,#808080)';
        tr.innerHTML = '<td style="' + style + '">' + esc(t.label || t.tool_id || '') + (runCount > 0 ? ' (' + runCount + ')' : '') + '</td>';
        body.appendChild(tr);
    });
}

/* ── Processes table (view.py:updateProcessesTableView) ── */
function renderProcesses(processes) {
    L.processes = processes || [];
    var filter = ($('process-status-filter')||{}).value || '';
    var body = $('processes-body');
    if (!body) return;
    body.innerHTML = '';
    var running = 0, finished = 0;
    L.processes.forEach(function(p) {
        if (p.status === 'Running') running++;
        else finished++;
        if (filter && p.status !== filter) return;
        var tr = document.createElement('tr');
        tr.dataset.processId = p.id || '';
        tr.style.cursor = 'pointer';
        if (L.selectedProcessId && parseInt(p.id) === L.selectedProcessId) tr.classList.add('selected');
        var statusClass = p.status === 'Running' ? 'proc-running' : p.status === 'Crashed' ? 'proc-crashed' : p.status === 'Waiting' ? 'proc-waiting' : 'proc-finished';
        var spinnerHtml = p.status === 'Running' ? '<span class="spinner"></span>' : '';
        var target = (p.hostIp||'') + (p.port ? ':'+p.port : '');
        var pct = p.percent || '';
        tr.innerHTML =
            '<td>' + esc(p.id) + '</td>' +
            '<td>' + esc(p.name||'') + '</td>' +
            '<td>' + esc(target) + '</td>' +
            '<td>' + esc(p.pid||'') + '</td>' +
            '<td class="' + statusClass + '">' + spinnerHtml + esc(p.status||'') + '</td>' +
            '<td>' + esc(pct) + '</td>' +
            '<td>' + esc(p.elapsed||'') + '</td>';
        body.appendChild(tr);
    });
    setText('stat-running', running);
    setText('stat-finished', finished);
    setText('process-count', L.processes.length);
}

/* ── OS table ── */
function renderOsList() {
    var groups = {};
    L.hosts.forEach(function(h) {
        var os = h.os || 'Unknown';
        if (!groups[os]) groups[os] = [];
        groups[os].push(h);
    });
    var body = $('os-list-body');
    if (!body) return;
    body.innerHTML = '';
    Object.keys(groups).sort().forEach(function(os) {
        var tr = document.createElement('tr');
        tr.dataset.os = os;
        tr.style.cursor = 'pointer';
        tr.innerHTML = '<td>' + esc(os) + '</td><td>' + groups[os].length + '</td>';
        body.appendChild(tr);
    });
}

/* ── Host detail (view.py:updateRightPanel) ── */
function loadHostDetail(hostId) {
    fetchJson('/api/workspace/hosts/' + hostId).then(function(data) {
        L.hostCache[hostId] = data;
        var host = data.host || {};
        L.selectedHostIp = host.ip || '';

        /* Services tab (right) */
        var ports = $('host-detail-ports');
        ports.innerHTML = '';
        (data.ports || []).forEach(function(p) {
            var svc = p.service || {};
            var tr = document.createElement('tr');
            tr.innerHTML =
                '<td>' + esc(host.ip) + '</td>' +
                '<td>' + esc(p.port) + '</td>' +
                '<td>' + esc(p.protocol) + '</td>' +
                '<td>' + esc(p.state) + '</td>' +
                '<td>' + esc(svc.name||'') + '</td>' +
                '<td>' + esc((svc.product||'') + ' ' + (svc.version||'')).trim() + '</td>';
            ports.appendChild(tr);
        });

        /* Scripts tab */
        var scripts = $('host-detail-scripts');
        scripts.innerHTML = '';
        (data.scripts || []).forEach(function(s) {
            var tr = document.createElement('tr');
            tr.dataset.scriptId = s.id || '';
            tr.style.cursor = 'pointer';
            tr.innerHTML = '<td>' + esc(s.scriptId||s.script_id||'') + '</td><td>' + esc(s.port||'') + '</td>';
            scripts.appendChild(tr);
        });

        /* Information tab */
        var info = $('host-info-body');
        info.innerHTML = '';
        [['IP', host.ip], ['Hostname', host.hostname], ['OS', host.os], ['Status', host.status],
         ['Open Ports', (data.ports||[]).length], ['Scripts', (data.scripts||[]).length],
         ['CVEs', (data.cves||[]).length]].forEach(function(row) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td style="color:var(--disabled);width:120px">' + esc(row[0]) + '</td><td>' + esc(row[1]) + '</td>';
            info.appendChild(tr);
        });

        /* CVEs tab */
        var cves = $('host-detail-cves');
        cves.innerHTML = '';
        (data.cves || []).forEach(function(c) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + esc(c.name||'') + '</td><td>' + esc(c.severity||'') + '</td><td>' + esc(c.product||'') + '</td><td></td>';
            cves.appendChild(tr);
        });

        /* Notes */
        var notes = $('notes-text');
        if (notes) notes.value = data.note || '';

        /* Window title */
        var title = host.ip + (host.hostname && host.hostname !== host.ip ? ' ('+host.hostname+')' : '');
        setText('window-title', 'LEGION – ' + title);

        /* Dynamic tool output tabs for this host */
        renderDynamicToolTabs(host.ip);

    }).catch(function(err) {
        console.error('loadHostDetail error:', err);
    });
}

/* ── Dynamic tool output tabs (view.py:restoreToolTabsForHost) ── */
function renderDynamicToolTabs(hostIp) {
    var bar = $('right-tab-bar');
    var container = $('dynamic-tabs-container');
    /* Remove old dynamic tabs */
    bar.querySelectorAll('.dynamic-tab').forEach(function(b) { b.remove(); });
    container.innerHTML = '';

    /* Find processes for this host */
    var hostProcs = L.processes.filter(function(p) { return p.hostIp === hostIp; });
    hostProcs.forEach(function(proc) {
        var tabId = 'dyntab-' + proc.id;
        var btn = document.createElement('button');
        btn.className = 'tab-btn dynamic-tab';
        btn.type = 'button';
        btn.dataset.tab = tabId;
        btn.textContent = (proc.name||'?') + (proc.port ? ' '+proc.port : '');
        bar.appendChild(btn);

        var panel = document.createElement('div');
        panel.className = 'tab-content';
        panel.id = tabId;
        panel.innerHTML = '<div class="tool-output-area ansi" id="dyn-output-' + proc.id + '">Loading...</div>';
        container.appendChild(panel);
    });
}

/* ── Load process output inline (view.py tool output display) ── */
function loadProcessOutput(processId, targetEl) {
    fetchJson('/api/processes/' + processId + '/output?max_chars=50000').then(function(data) {
        var text = data.output_chunk || data.output || '';
        targetEl.innerHTML = ansiToHtml(text);
        targetEl.scrollTop = targetEl.scrollHeight;
    }).catch(function() {
        targetEl.textContent = 'Error loading output';
    });
}

/* ================================================================
   INTERACTIONS (mirrors view.py signal connections)
   ================================================================ */

function initInteractions() {
    /* ── Host click (view.py:hostTableClick) ── */
    $('hosts-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostId) return;
        var hostId = parseInt(tr.dataset.hostId);
        L.selectedHostId = hostId;
        /* highlight */
        $('hosts-body').querySelectorAll('tr').forEach(function(r) {
            r.classList.toggle('selected', r === tr);
        });
        /* Show right panel tabs (not tools display) */
        $('right-tabs').style.display = '';
        $('tools-display').style.display = 'none';
        /* Activate Services tab */
        var svcTab = $('right-tab-bar').querySelector('[data-tab="services-right"]');
        if (svcTab) svcTab.click();
        /* Load detail */
        loadHostDetail(hostId);
    });

    /* ── Service click (left) (view.py:serviceNamesTableClick) ── */
    $('services-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        L.selectedService = tr.dataset.service || '';
        $('services-body').querySelectorAll('tr').forEach(function(r) {
            r.classList.toggle('selected', r === tr);
        });
        /* Update right panel to show ports for this service across all hosts */
        updatePortsByService(L.selectedService);
        /* Show right panel */
        $('right-tabs').style.display = '';
        $('tools-display').style.display = 'none';
        var svcTab = $('right-tab-bar').querySelector('[data-tab="services-right"]');
        if (svcTab) svcTab.click();
    });

    /* ── Tools click (left) (view.py:toolsTableClick) ── */
    $('tools-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        L.selectedTool = tr.dataset.toolId || '';
        $('tools-body').querySelectorAll('tr').forEach(function(r) {
            r.classList.toggle('selected', r === tr);
        });
        /* Switch to tools display panel */
        $('right-tabs').style.display = 'none';
        $('tools-display').style.display = 'flex';
        updateToolHosts(L.selectedTool);
    });

    /* ── Tool hosts click → show output (view.py:toolHostsClick) ── */
    $('tool-hosts-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.processId) return;
        $('tool-hosts-body').querySelectorAll('tr').forEach(function(r) {
            r.classList.toggle('selected', r === tr);
        });
        loadProcessOutput(tr.dataset.processId, $('tool-output-text'));
    });

    /* ── OS list click ── */
    $('os-list-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        var os = tr.dataset.os || '';
        $('os-list-body').querySelectorAll('tr').forEach(function(r) { r.classList.toggle('selected', r === tr); });
        var body = $('os-hosts-body');
        body.innerHTML = '';
        L.hosts.filter(function(h) { return (h.os||'Unknown') === os; }).forEach(function(h) {
            var row = document.createElement('tr');
            row.dataset.hostId = h.id;
            row.style.cursor = 'pointer';
            row.innerHTML = '<td>' + esc(h.ip) + '</td><td>' + esc(h.hostname||'') + '</td>';
            body.appendChild(row);
        });
    });

    /* ── OS hosts click → load host detail ── */
    $('os-hosts-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostId) return;
        L.selectedHostId = parseInt(tr.dataset.hostId);
        loadHostDetail(L.selectedHostId);
        /* Switch to Hosts tab in left panel to show the selected host */
        var hostsTab = $('left-tab-bar').querySelector('[data-tab="hosts-panel"]');
        if (hostsTab) hostsTab.click();
        renderHosts(L.hosts); /* re-render to show selection */
        /* Show right panel */
        $('right-tabs').style.display = '';
        $('tools-display').style.display = 'none';
    });

    /* ── Left tab switch → update right panel mode ── */
    $('left-tab-bar').addEventListener('click', function(e) {
        var btn = e.target.closest('.tab-btn');
        if (!btn) return;
        var tab = btn.dataset.tab;
        if (tab === 'tools-panel-left' || tab === 'tools-panel') {
            /* Show tools display instead of right tabs */
            if (L.selectedTool) {
                $('right-tabs').style.display = 'none';
                $('tools-display').style.display = 'flex';
            }
        } else {
            /* Show normal right tabs */
            $('right-tabs').style.display = '';
            $('tools-display').style.display = 'none';
        }
        /* Render OS data when OS tab is selected */
        if (tab === 'os-panel') renderOsList();
    });

    /* ── Process row click → show output inline ── */
    $('processes-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.processId) return;
        L.selectedProcessId = parseInt(tr.dataset.processId);
        $('processes-body').querySelectorAll('tr').forEach(function(r) {
            r.classList.toggle('selected', r === tr);
        });
        loadProcessOutput(tr.dataset.processId, $('process-output-inline'));
        /* Start auto-polling for running processes */
        if (L.procPollTimer) clearInterval(L.procPollTimer);
        L.procPollTimer = setInterval(function() {
            var proc = L.processes.find(function(p) { return parseInt(p.id) === L.selectedProcessId; });
            if (!proc || proc.status !== 'Running') { clearInterval(L.procPollTimer); L.procPollTimer = null; return; }
            loadProcessOutput(L.selectedProcessId, $('process-output-inline'));
        }, 2000);
    });

    /* ── Process status filter ── */
    var pf = $('process-status-filter');
    if (pf) pf.addEventListener('change', function() { renderProcesses(L.processes); });

    /* ── Script click → show output ── */
    $('host-detail-scripts').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.scriptId) return;
        $('host-detail-scripts').querySelectorAll('tr').forEach(function(r) { r.classList.toggle('selected', r === tr); });
        var scriptData = L.hostCache[L.selectedHostId];
        if (scriptData) {
            var script = (scriptData.scripts||[]).find(function(s) { return String(s.id) === tr.dataset.scriptId; });
            if (script) $('script-output-inline').innerHTML = ansiToHtml(script.output || script.script_output || '');
        }
    });

    /* ── Dynamic tab click → load process output ── */
    $('right-tab-bar').addEventListener('click', function(e) {
        var btn = e.target.closest('.dynamic-tab');
        if (!btn) return;
        var tabId = btn.dataset.tab;
        if (!tabId) return;
        var procId = tabId.replace('dyntab-', '');
        var outputEl = $('dyn-output-' + procId);
        if (outputEl && !outputEl.dataset.loaded) {
            outputEl.dataset.loaded = '1';
            loadProcessOutput(procId, outputEl);
        }
    });

    /* ── Add hosts overlay click ── */
    var overlay = $('add-hosts-overlay');
    if (overlay) overlay.addEventListener('click', function() {
        /* trigger the upstream add-hosts/scan modal if available */
        var addBtn = $('action-add-hosts');
        if (addBtn) addBtn.click();
    });

    /* ── Filter bar ── */
    var filterInput = $('filter-keyword');
    var filterBtn = $('filter-apply');
    if (filterInput && filterBtn) {
        var doFilter = function() {
            var q = filterInput.value.toLowerCase();
            $('hosts-body').querySelectorAll('tr').forEach(function(r) {
                r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
        };
        filterBtn.addEventListener('click', doFilter);
        filterInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') doFilter(); });
    }

    /* (upstream ribbon delegation removed — all handlers are direct now) */
}

/* ── Update ports-by-service (view.py:updatePortsByServiceTableView) ── */
function updatePortsByService(serviceName) {
    var body = $('host-detail-ports');
    body.innerHTML = '';
    /* We need port data for all hosts — use cache or fetch */
    var hostIds = L.hosts.map(function(h) { return h.id; });
    var promises = hostIds.map(function(id) {
        if (L.hostCache[id]) return Promise.resolve(L.hostCache[id]);
        return fetchJson('/api/workspace/hosts/' + id).then(function(d) { L.hostCache[id] = d; return d; });
    });
    Promise.all(promises).then(function(allData) {
        allData.forEach(function(hd) {
            var host = hd.host || {};
            (hd.ports || []).forEach(function(p) {
                var svc = p.service || {};
                if ((svc.name||'').toLowerCase() !== serviceName.toLowerCase()) return;
                var tr = document.createElement('tr');
                tr.dataset.hostId = host.id;
                tr.style.cursor = 'pointer';
                tr.innerHTML =
                    '<td>' + esc(host.ip) + '</td><td>' + esc(p.port) + '</td>' +
                    '<td>' + esc(p.protocol) + '</td><td>' + esc(p.state) + '</td>' +
                    '<td>' + esc(svc.name||'') + '</td>' +
                    '<td>' + esc((svc.product||'') + ' ' + (svc.version||'')).trim() + '</td>';
                tr.addEventListener('click', function() {
                    L.selectedHostId = parseInt(host.id);
                    loadHostDetail(L.selectedHostId);
                    renderHosts(L.hosts);
                });
                body.appendChild(tr);
            });
        });
    });
}

/* ── Update tool hosts (view.py:updateToolHostsTableView) ── */
function updateToolHosts(toolId) {
    var body = $('tool-hosts-body');
    body.innerHTML = '';
    $('tool-output-text').textContent = 'Select a host to view output';
    /* Find processes with this tool name */
    var toolProcs = L.processes.filter(function(p) { return (p.name||'') === toolId; });
    toolProcs.forEach(function(p) {
        var tr = document.createElement('tr');
        tr.dataset.processId = p.id;
        tr.style.cursor = 'pointer';
        tr.innerHTML = '<td>' + esc(p.hostIp||'') + '</td><td>' + esc(p.port||'') + '</td>';
        body.appendChild(tr);
    });
}

/* ================================================================
   SNAPSHOT POLLING (mirrors processTableUiUpdateTimer)
   ================================================================ */
function pollSnapshot() {
    fetchJson('/api/snapshot').then(function(snap) {
        L.snapshot = snap;
        renderHosts(snap.hosts || []);
        renderServiceNames(snap.services || []);
        renderTools(snap.tools || []);
        renderProcesses(snap.processes || []);
        setText('project-name', (snap.project||{}).name || '*untitled');
        setText('project-output-folder', (snap.project||{}).output_folder || '');
        setText('stat-open-ports', (snap.summary||{}).open_ports || 0);
    }).catch(function(err) {
        console.error('Snapshot poll error:', err);
    });
}

/* ================================================================
   INIT
   ================================================================ */
document.addEventListener('DOMContentLoaded', function() {
    initTabBar('main-tab-bar');
    initTabBar('left-tab-bar');
    initTabBar('right-tab-bar');
    initTabBar('bottom-tab-bar');
    initMenuBar();
    initSplitter('main-vsplitter', 'left-panel', 'width', 120, 600);
    initSplitter('main-hsplitter', 'bottom-section', 'height', 80, 500);
    initInteractions();

    /* Initial render from embedded snapshot */
    try {
        var snap = JSON.parse($('initial-snapshot').textContent);
        L.snapshot = snap;
        renderHosts(snap.hosts || []);
        renderServiceNames(snap.services || []);
        renderTools(snap.tools || []);
        renderProcesses(snap.processes || []);
        setText('project-name', (snap.project||{}).name || '*untitled');
        setText('project-output-folder', (snap.project||{}).output_folder || '');
        setText('stat-open-ports', (snap.summary||{}).open_ports || 0);
    } catch(e) { console.error('Initial snapshot parse error:', e); }

    /* Start polling every 3 seconds */
    L.pollTimer = setInterval(pollSnapshot, 3000);

    /* ════════════════════════════════════════════════
       MODAL WIRING — connect menu buttons to dialogs
       ════════════════════════════════════════════════ */

    function openModal(id) {
        var el = $(id);
        if (el) { el.classList.add('is-open'); el.style.display = 'flex'; }
    }
    function closeModal(id) {
        var el = $(id);
        if (el) { el.classList.remove('is-open'); el.style.display = 'none'; }
    }

    /* ── Add Hosts ── */
    var addHostsBtn = $('action-add-hosts');
    if (addHostsBtn) addHostsBtn.addEventListener('click', function() { openModal('add-hosts-modal'); });
    var addOverlay = $('add-hosts-overlay');
    if (addOverlay) addOverlay.addEventListener('click', function() { openModal('add-hosts-modal'); });
    var filterAdd = $('filter-add-host');
    if (filterAdd) filterAdd.addEventListener('click', function() { openModal('add-hosts-modal'); });

    var addClose = $('add-hosts-close');
    if (addClose) addClose.addEventListener('click', function() { closeModal('add-hosts-modal'); });

    var addStart = $('add-hosts-start');
    if (addStart) addStart.addEventListener('click', function() {
        var targets = ($('add-hosts-targets') || {}).value || '';
        if (!targets.trim()) { setText('add-hosts-status', 'Enter at least one target'); return; }
        var mode = ($('add-hosts-mode') || {}).value || 'staged';
        var discovery = ($('add-hosts-discovery') || {}).checked;
        var runActions = ($('add-hosts-actions') || {}).checked;

        setText('add-hosts-status', 'Starting scan...');
        addStart.disabled = true;

        var scanMode = 'easy';
        var staged = false;
        if (mode === 'staged') { staged = true; }
        else if (mode === 'list') { discovery = false; }

        postJson('/api/nmap/scan', {
            targets: targets.trim(),
            scan_mode: scanMode,
            discovery: discovery,
            staged: staged,
            run_actions: runActions
        }).then(function(data) {
            setText('add-hosts-status', 'Scan started! Job: ' + ((data.job||{}).id || '?'));
            addStart.disabled = false;
            setTimeout(function() { closeModal('add-hosts-modal'); }, 1500);
            pollSnapshot();
        }).catch(function(err) {
            setText('add-hosts-status', 'Error: ' + err.message);
            addStart.disabled = false;
        });
    });

    /* ── Import Nmap (with file browser for XML path) ── */
    var importBtn = $('action-import-nmap');
    if (importBtn) importBtn.addEventListener('click', function() { openModal('import-nmap-modal'); });
    var importClose = $('import-nmap-close');
    if (importClose) importClose.addEventListener('click', function() { closeModal('import-nmap-modal'); });
    /* Browse button for import path */
    var importPathInput = $('import-nmap-path');
    if (importPathInput) {
        var browseBtn = document.createElement('button');
        browseBtn.type = 'button';
        browseBtn.textContent = 'Browse...';
        browseBtn.style.marginLeft = '4px';
        importPathInput.parentNode.appendChild(browseBtn);
        browseBtn.addEventListener('click', function() {
            closeModal('import-nmap-modal');
            fbOpen('Select Nmap XML', '.xml', 'open', '/root').then(function(path) {
                if (path) importPathInput.value = path;
                openModal('import-nmap-modal');
            });
        });
    }
    var importStart = $('import-nmap-start');
    if (importStart) importStart.addEventListener('click', function() {
        var path = ($('import-nmap-path') || {}).value || '';
        if (!path.trim()) { setText('import-nmap-status', 'Enter XML path'); return; }
        var runActions = ($('import-nmap-actions') || {}).checked;
        setText('import-nmap-status', 'Importing...');
        postJson('/api/nmap/import-xml', { path: path.trim(), run_actions: runActions })
        .then(function(data) {
            setText('import-nmap-status', 'Import complete!');
            setTimeout(function() { closeModal('import-nmap-modal'); }, 1500);
            pollSnapshot();
        }).catch(function(err) {
            setText('import-nmap-status', 'Error: ' + err.message);
        });
    });

    /* ── Config Manager — Multiple Profiles (from configDialog.py) ── */
    var cfgState = { profiles: [], active: 'default', selectedTab: null };

    function cfgLoadProfiles() {
        fetchJson('/api/config/profiles').then(function(data) {
            cfgState.profiles = data.profiles || [];
            cfgState.active = data.active || 'default';
            cfgRender();
        });
    }

    function cfgRender() {
        var tabBar = $('config-tab-bar');
        var editors = $('config-editors');
        var selector = $('config-profile-selector');
        if (!tabBar || !editors || !selector) return;

        /* Tab bar */
        tabBar.innerHTML = '';
        editors.querySelectorAll('textarea').forEach(function(t) { t.remove(); });

        /* Selector dropdown */
        selector.innerHTML = '';

        cfgState.profiles.forEach(function(p) {
            /* Tab button */
            var btn = document.createElement('button');
            btn.className = 'tab-btn' + (p.name === (cfgState.selectedTab || cfgState.active) ? ' active' : '');
            btn.type = 'button';
            btn.textContent = (p.active ? '★ ' : '') + p.name;
            btn.dataset.profile = p.name;
            btn.addEventListener('click', function() {
                cfgState.selectedTab = p.name;
                tabBar.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                editors.querySelectorAll('textarea').forEach(function(t) {
                    t.style.display = t.dataset.profile === p.name ? '' : 'none';
                });
            });
            tabBar.appendChild(btn);

            /* Editor textarea */
            var ta = document.createElement('textarea');
            ta.dataset.profile = p.name;
            ta.value = p.text || '';
            ta.style.cssText = 'width:100%;flex:1;min-height:400px;background:var(--base);color:var(--text);font:inherit;border:1px solid var(--border);padding:6px;resize:vertical;display:' +
                (p.name === (cfgState.selectedTab || cfgState.active) ? '' : 'none');
            editors.appendChild(ta);

            /* Selector option */
            var opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = p.name;
            if (p.name === cfgState.active) opt.selected = true;
            selector.appendChild(opt);
        });

        /* Active label */
        setText('config-active-label', 'Currently Active: ' + cfgState.active);

        if (!cfgState.selectedTab && cfgState.profiles.length) {
            cfgState.selectedTab = cfgState.active;
        }
    }

    function cfgGetCurrentText() {
        var name = cfgState.selectedTab || cfgState.active;
        var ta = document.querySelector('#config-editors textarea[data-profile="' + name + '"]');
        return ta ? ta.value : '';
    }

    function cfgGetCurrentName() {
        return cfgState.selectedTab || cfgState.active;
    }

    var configBtn = $('action-config');
    if (configBtn) configBtn.addEventListener('click', function() {
        openModal('config-modal');
        cfgLoadProfiles();
    });
    var configClose = $('config-close');
    if (configClose) configClose.addEventListener('click', function() { closeModal('config-modal'); });

    /* Save */
    var configSave = $('config-save');
    if (configSave) configSave.addEventListener('click', function() {
        var name = cfgGetCurrentName();
        postJson('/api/config/profiles/' + encodeURIComponent(name) + '/save', { text: cfgGetCurrentText() })
        .then(function() { setText('config-status', 'Saved ' + name); })
        .catch(function(err) { setText('config-status', 'Error: ' + err.message); });
    });

    /* Activate */
    var configActivate = $('config-activate');
    if (configActivate) configActivate.addEventListener('click', function() {
        var name = ($('config-profile-selector') || {}).value || '';
        if (!name) return;
        postJson('/api/config/profiles/' + encodeURIComponent(name) + '/activate', {})
        .then(function() {
            setText('config-status', name + ' activated!');
            cfgState.active = name;
            cfgLoadProfiles();
        })
        .catch(function(err) { setText('config-status', 'Error: ' + err.message); });
    });

    /* New Profile */
    var configNew = $('config-new');
    if (configNew) configNew.addEventListener('click', function() {
        var name = prompt('New profile name:');
        if (!name || !name.trim()) return;
        var copyFrom = cfgGetCurrentName();
        postJson('/api/config/profiles/create', { name: name.trim(), copy_from: copyFrom })
        .then(function() {
            setText('config-status', 'Created ' + name.trim());
            cfgState.selectedTab = name.trim();
            cfgLoadProfiles();
        })
        .catch(function(err) { setText('config-status', 'Error: ' + err.message); });
    });

    /* Rename */
    var configRename = $('config-rename');
    if (configRename) configRename.addEventListener('click', function() {
        var oldName = cfgGetCurrentName();
        if (oldName === 'default') { setText('config-status', 'Cannot rename default'); return; }
        var newName = prompt('New name for "' + oldName + '":', oldName);
        if (!newName || !newName.trim() || newName.trim() === oldName) return;
        postJson('/api/config/profiles/' + encodeURIComponent(oldName) + '/rename', { new_name: newName.trim() })
        .then(function() {
            setText('config-status', 'Renamed to ' + newName.trim());
            cfgState.selectedTab = newName.trim();
            cfgLoadProfiles();
        })
        .catch(function(err) { setText('config-status', 'Error: ' + err.message); });
    });

    /* Duplicate */
    var configDuplicate = $('config-duplicate');
    if (configDuplicate) configDuplicate.addEventListener('click', function() {
        var srcName = cfgGetCurrentName();
        var newName = prompt('Name for copy of "' + srcName + '":', srcName + '_copy');
        if (!newName || !newName.trim()) return;
        postJson('/api/config/profiles/' + encodeURIComponent(srcName) + '/duplicate', { new_name: newName.trim() })
        .then(function() {
            setText('config-status', 'Duplicated as ' + newName.trim());
            cfgState.selectedTab = newName.trim();
            cfgLoadProfiles();
        })
        .catch(function(err) { setText('config-status', 'Error: ' + err.message); });
    });

    /* Delete */
    var configDelete = $('config-delete');
    if (configDelete) configDelete.addEventListener('click', function() {
        var name = cfgGetCurrentName();
        if (name === 'default') { setText('config-status', 'Cannot delete default'); return; }
        if (!confirm('Delete profile "' + name + '"? This cannot be undone.')) return;
        postJson('/api/config/profiles/' + encodeURIComponent(name) + '/delete', {})
        .then(function() {
            setText('config-status', 'Deleted ' + name);
            cfgState.selectedTab = 'default';
            cfgLoadProfiles();
        })
        .catch(function(err) { setText('config-status', 'Error: ' + err.message); });
    });

    /* ── Process management buttons ── */
    var clearFinished = $('process-clear-finished-button');
    if (clearFinished) clearFinished.addEventListener('click', function() {
        postJson('/api/processes/clear', { reset_all: false }).then(function() { pollSnapshot(); });
    });
    var clearAll = $('process-clear-all-button');
    if (clearAll) clearAll.addEventListener('click', function() {
        postJson('/api/processes/clear', { reset_all: true }).then(function() { pollSnapshot(); });
    });

    /* ── Notes save button ── */
    var notesSaveBtn = $('workspace-save-note-button');
    if (notesSaveBtn) notesSaveBtn.addEventListener('click', function() {
        var hostSelect = $('workspace-host-select');
        var noteText = $('workspace-note');
        if (!hostSelect || !noteText) return;
        var hostId = hostSelect.value;
        if (!hostId) return;
        postJson('/api/workspace/hosts/' + hostId + '/note', { note: noteText.value })
        .then(function() { alert('Note saved'); });
    });

    /* ── Notes save in right panel ── */
    var notesSave2 = $('notes-text');
    if (notesSave2) {
        notesSave2.addEventListener('blur', function() {
            if (!L.selectedHostId) return;
            postJson('/api/workspace/hosts/' + L.selectedHostId + '/note', { note: notesSave2.value });
        });
    }

    /* ── Scheduler run button ── */
    var schedulerBtn = $('workspace-run-scheduler-button');
    if (schedulerBtn) schedulerBtn.addEventListener('click', function() {
        postJson('/api/scheduler/run', {}).then(function(d) {
            alert('Scheduler run: ' + JSON.stringify(d));
            pollSnapshot();
        });
    });

    /* ── Workspace refresh button ── */
    var refreshBtn = $('workspace-refresh-button');
    if (refreshBtn) refreshBtn.addEventListener('click', function() { pollSnapshot(); });

    /* ═══════════════════════════════════════════
       File Browser (replaces QFileDialog / prompt())
       ═══════════════════════════════════════════ */
    var fb = {
        resolve: null,
        mode: 'open',
        filter: '',
        current: '',
    };

    function fbOpen(title, filter, mode, startPath) {
        return new Promise(function(resolve) {
            fb.resolve = resolve;
            fb.mode = mode || 'open';
            fb.filter = filter || '';
            setText('fb-title', title || (mode === 'save' ? 'Save File' : 'Open File'));
            $('fb-filter-display').textContent = filter ? 'Filter: *' + filter : 'All files';
            var fnInput = $('fb-filename');
            if (fnInput) {
                fnInput.value = '';
                fnInput.style.display = mode === 'save' ? '' : 'none';
            }
            openModal('file-browser-modal');
            fbNavigate(startPath || fb.current || '/root');
        });
    }

    function fbNavigate(path) {
        var hidden = ($('fb-hidden') || {}).checked || false;
        var url = '/api/files/browse?path=' + encodeURIComponent(path) +
                  '&filter=' + encodeURIComponent(fb.filter) +
                  '&hidden=' + hidden;
        fetchJson(url).then(function(data) {
            fb.current = data.current;
            $('fb-path').value = data.current;
            var list = $('fb-list');
            list.innerHTML = '';
            if (data.parent) {
                var up = document.createElement('div');
                up.textContent = '\uD83D\uDCC1 ..';
                up.style.cssText = 'padding:4px 8px;cursor:pointer;';
                up.addEventListener('click', function() { fbNavigate(data.parent); });
                up.addEventListener('mouseenter', function() { this.style.background='var(--highlight,#2a82da)';this.style.color='#fff'; });
                up.addEventListener('mouseleave', function() { this.style.background='';this.style.color=''; });
                list.appendChild(up);
            }
            data.entries.forEach(function(entry) {
                var row = document.createElement('div');
                var icon = entry.is_dir ? '\uD83D\uDCC1 ' : '\uD83D\uDCC4 ';
                var size = entry.is_dir ? '' : ' (' + Math.round(entry.size/1024) + ' KB)';
                row.textContent = icon + entry.name + size;
                row.dataset.path = entry.path;
                row.dataset.name = entry.name;
                row.style.cssText = 'padding:3px 8px;cursor:pointer;';
                row.addEventListener('click', function() {
                    list.querySelectorAll('div').forEach(function(d) { d.classList.remove('selected'); d.style.background=''; d.style.color=''; });
                    row.style.background = 'var(--highlight,#2a82da)';
                    row.style.color = '#fff';
                    if (!entry.is_dir) $('fb-filename').value = entry.name;
                });
                row.addEventListener('dblclick', function() {
                    if (entry.is_dir) fbNavigate(entry.path);
                    else fbSelect(entry.path);
                });
                row.addEventListener('mouseenter', function() {
                    if (this.style.background !== 'var(--highlight,#2a82da)')
                        this.style.background = 'var(--midlight,#3e3e3e)';
                });
                row.addEventListener('mouseleave', function() {
                    if (this.style.background === 'var(--midlight,#3e3e3e)')
                        this.style.background = '';
                });
                list.appendChild(row);
            });
        });
    }

    function fbSelect(fullPath) {
        closeModal('file-browser-modal');
        if (fb.resolve) { fb.resolve(fullPath || null); fb.resolve = null; }
    }

    if ($('fb-close')) $('fb-close').addEventListener('click', function() { fbSelect(null); });
    if ($('fb-cancel')) $('fb-cancel').addEventListener('click', function() { fbSelect(null); });
    if ($('fb-up')) $('fb-up').addEventListener('click', function() {
        fbNavigate(fb.current.replace(/\/[^\/]+\/?$/, '') || '/');
    });
    if ($('fb-go')) $('fb-go').addEventListener('click', function() { fbNavigate($('fb-path').value || '/'); });
    if ($('fb-path')) $('fb-path').addEventListener('keydown', function(e) { if (e.key === 'Enter') fbNavigate(this.value || '/'); });
    if ($('fb-hidden')) $('fb-hidden').addEventListener('change', function() { fbNavigate(fb.current); });
    if ($('fb-select')) $('fb-select').addEventListener('click', function() {
        var fn = ($('fb-filename') || {}).value || '';
        if (fn.trim()) {
            var found = $('fb-list').querySelector('[data-name="' + fn.trim() + '"]');
            fbSelect(found ? found.dataset.path : fb.current + '/' + fn.trim());
        }
    });

    /* ── File → Open (with file browser) ── */
    var openBtn = $('action-open');
    if (openBtn) openBtn.addEventListener('click', function() {
        fbOpen('Open Project', '.legion', 'open', '/root').then(function(path) {
            if (!path) return;
            postJson('/api/project/open', { path: path })
            .then(function() {
                setText('window-title', 'LEGION v2.2-flask – ' + path.split('/').pop());
                pollSnapshot();
            })
            .catch(function(err) { alert('Open failed: ' + err.message); });
        });
    });

    /* ── File → Save (with file browser) ── */
    var saveBtn = $('action-save');
    if (saveBtn) saveBtn.addEventListener('click', function() {
        fbOpen('Save Project', '.legion', 'save', '/root').then(function(path) {
            if (!path) return;
            if (!path.endsWith('.legion')) path += '.legion';
            postJson('/api/project/save-as', { path: path })
            .then(function() { setText('window-title', 'LEGION v2.2-flask – ' + path.split('/').pop()); })
            .catch(function(err) { alert('Save failed: ' + err.message); });
        });
    });

    /* ── File → Save As (with file browser) ── */
    var saveAsBtn = $('action-save-as');
    if (saveAsBtn) saveAsBtn.addEventListener('click', function() {
        fbOpen('Save Project As', '.legion', 'save', '/root').then(function(path) {
            if (!path) return;
            if (!path.endsWith('.legion')) path += '.legion';
            postJson('/api/project/save-as', { path: path })
            .then(function() { setText('window-title', 'LEGION v2.2-flask – ' + path.split('/').pop()); })
            .catch(function(err) { alert('Save As failed: ' + err.message); });
        });
    });

    /* ── File → Exit ── */
    var exitBtn = $('action-exit');
    if (exitBtn) exitBtn.addEventListener('click', function() {
        if (confirm('Exit Legion?')) window.close();
    });

    /* ── Help ── */
    var helpBtn = $('action-help');
    if (helpBtn) helpBtn.addEventListener('click', function() {
        alert('LEGION v2.2-flask\\nNetwork penetration testing framework\\n\\nHelp: F2 for Config Manager\\nCtrl+H to add hosts');
    });

    /* ── Ctrl+B note capture ── */
    var noteSelBtn = $('action-note-selection');
    if (noteSelBtn) noteSelBtn.addEventListener('click', function() {
        var sel = window.getSelection().toString();
        if (!sel || !L.selectedHostId) { alert('Select text first, then press Ctrl+B'); return; }
        postJson('/api/workspace/hosts/' + L.selectedHostId + '/note', { note: sel })
        .then(function() { alert('Selection sent to notes'); });
    });
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            var sel = window.getSelection().toString();
            if (!sel || !L.selectedHostId) return;
            postJson('/api/workspace/hosts/' + L.selectedHostId + '/note', { note: sel });
        }
    });

    /* ── Keyboard shortcuts ── */
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey || e.metaKey) {
            if (e.key === 'n') { e.preventDefault(); $('action-new') && $('action-new').click(); }
            if (e.key === 'o') { e.preventDefault(); $('action-open') && $('action-open').click(); }
            if (e.key === 's') { e.preventDefault(); $('action-save') && $('action-save').click(); }
            if (e.key === 'h') { e.preventDefault(); $('action-add-hosts') && $('action-add-hosts').click(); }
            if (e.key === 'i') { e.preventDefault(); $('action-import-nmap') && $('action-import-nmap').click(); }
            if (e.key === 'e') { e.preventDefault(); $('action-export-json') && $('action-export-json').click(); }
        }
        if (e.key === 'F1') { e.preventDefault(); $('action-help') && $('action-help').click(); }
        if (e.key === 'F2') { e.preventDefault(); $('action-config') && $('action-config').click(); }
    });

    /* ── New Project ── */
    var newBtn = $('action-new');
    if (newBtn) newBtn.addEventListener('click', function() {
        if (confirm('Create new project? Current data will be lost.')) {
            postJson('/api/project/new-temp', {}).then(function() {
                setText('window-title', 'LEGION v2.2-flask – *untitled');
                pollSnapshot();
            });
        }
    });

    /* ── Export JSON ── */
    var exportBtn = $('action-export-json');
    if (exportBtn) exportBtn.addEventListener('click', function() {
        window.open('/api/export/json', '_blank');
    });

    /* ── Close modals on overlay click ── */
    document.querySelectorAll('.legion-modal-overlay').forEach(function(overlay) {
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) {
                overlay.classList.remove('is-open');
                overlay.style.display = 'none';
            }
        });
    });

    /* ── Right-click context menus ── */
    function showContextMenu(items, x, y, onAction) {
        var old = $('ctx-menu');
        if (old) old.remove();
        var menu = document.createElement('div');
        menu.id = 'ctx-menu';
        menu.style.cssText = 'position:fixed;left:'+x+'px;top:'+y+'px;z-index:300;background:var(--midlight);border:1px solid var(--border);box-shadow:2px 4px 8px rgba(0,0,0,.5);min-width:180px;padding:2px 0;';
        items.forEach(function(item) {
            if (item.separator) {
                var sep = document.createElement('div');
                sep.style.cssText = 'height:1px;background:var(--border);margin:2px 6px;';
                menu.appendChild(sep);
            } else if (item.submenu) {
                var sub = document.createElement('div');
                sub.style.cssText = 'position:relative;';
                var btn = document.createElement('button');
                btn.textContent = item.label + ' ▸';
                btn.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font:inherit;padding:4px 12px;cursor:pointer;';
                btn.addEventListener('mouseenter', function() {
                    var subMenu = sub.querySelector('.ctx-sub');
                    if (subMenu) subMenu.style.display = 'block';
                });
                sub.addEventListener('mouseleave', function() {
                    var subMenu = sub.querySelector('.ctx-sub');
                    if (subMenu) subMenu.style.display = 'none';
                });
                var subDiv = document.createElement('div');
                subDiv.className = 'ctx-sub';
                subDiv.style.cssText = 'display:none;position:absolute;left:100%;top:0;background:var(--midlight);border:1px solid var(--border);min-width:180px;box-shadow:2px 4px 8px rgba(0,0,0,.5);';
                item.submenu.forEach(function(si) {
                    var sbtn = document.createElement('button');
                    sbtn.textContent = si.label;
                    sbtn.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font:inherit;padding:4px 12px;cursor:pointer;';
                    sbtn.addEventListener('click', function() { menu.remove(); onAction(si); });
                    sbtn.addEventListener('mouseenter', function() { this.style.background='var(--highlight)'; this.style.color='#fff'; });
                    sbtn.addEventListener('mouseleave', function() { this.style.background='none'; this.style.color='var(--text)'; });
                    subDiv.appendChild(sbtn);
                });
                sub.appendChild(btn);
                sub.appendChild(subDiv);
                menu.appendChild(sub);
            } else {
                var btn2 = document.createElement('button');
                btn2.textContent = item.label;
                btn2.style.cssText = 'display:block;width:100%;text-align:left;background:none;border:none;color:var(--text);font:inherit;padding:4px 12px;cursor:pointer;';
                btn2.addEventListener('click', function() { menu.remove(); onAction(item); });
                btn2.addEventListener('mouseenter', function() { this.style.background='var(--highlight)'; this.style.color='#fff'; });
                btn2.addEventListener('mouseleave', function() { this.style.background='none'; this.style.color='var(--text)'; });
                menu.appendChild(btn2);
            }
        });
        document.body.appendChild(menu);
        document.addEventListener('click', function rm() { menu.remove(); document.removeEventListener('click', rm); }, {once: true});
    }

    /* Host right-click */
    $('hosts-body').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostId) return;
        e.preventDefault();
        var hostId = tr.dataset.hostId;
        var hostIp = tr.dataset.hostIp || '';
        fetchJson('/api/menus/host?checked=False').then(function(data) {
            showContextMenu(data.items, e.clientX, e.clientY, function(action) {
                if (action.action === 'delete' && !confirm('Delete host ' + hostIp + '?')) return;
                postJson('/api/workspace/hosts/' + hostId + '/action', {
                    action: action.action, ip: hostIp, action_index: action.action_index || 0
                }).then(function() { pollSnapshot(); });
            });
        });
    });

    /* Service right-click */
    $('services-body').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        e.preventDefault();
        var svcName = tr.dataset.service || (tr.cells[0]||{}).textContent || '';
        fetchJson('/api/menus/service?name=' + encodeURIComponent(svcName)).then(function(data) {
            showContextMenu(data.items, e.clientX, e.clientY, function(action) {
                if (action.action === 'port-action' && L.selectedHostIp) {
                    postJson('/api/workspace/service-action', {
                        targets: [[L.selectedHostIp, '80', 'tcp']],
                        action_index: action.action_index || 0
                    }).then(function() { pollSnapshot(); });
                }
            });
        });
    });

    /* Process right-click */
    $('processes-body').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.processId) return;
        e.preventDefault();
        var pid = tr.dataset.processId;
        fetchJson('/api/menus/process').then(function(data) {
            showContextMenu(data.items, e.clientX, e.clientY, function(action) {
                if (action.action === 'kill') {
                    postJson('/api/processes/' + pid + '/kill', {}).then(function() { pollSnapshot(); });
                } else if (action.action === 'retry') {
                    postJson('/api/processes/' + pid + '/retry', {}).then(function() { pollSnapshot(); });
                } else if (action.action === 'clear') {
                    postJson('/api/processes/' + pid + '/close', {}).then(function() { pollSnapshot(); });
                }
            });
        });
    });

    /* Port right-click (in host detail services table) */
    $('host-detail-ports').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        e.preventDefault();
        var port = (tr.cells[1]||{}).textContent || '';
        var protocol = (tr.cells[2]||{}).textContent || 'tcp';
        var svcName = (tr.cells[4]||{}).textContent || '*';
        fetchJson('/api/menus/service?name=' + encodeURIComponent(svcName)).then(function(data) {
            showContextMenu(data.items, e.clientX, e.clientY, function(action) {
                if (action.action === 'port-action' && L.selectedHostIp) {
                    postJson('/api/workspace/service-action', {
                        targets: [[L.selectedHostIp, port, protocol]],
                        action_index: action.action_index || 0
                    }).then(function() { pollSnapshot(); });
                }
            });
        });
    });

});
