/* ================================================================
   LEGION – Flask frontend JS
   1:1 replica of Qt6 ui/view.py + controller/controller.py logic
   ================================================================ */
'use strict';

/* ── Notes rendering: headers + ANSI colour ── */
/* Qt6: notesCursor.insertText(header, headerFormat) — orange bg, black text.
   Lines may contain ANSI codes when inserted via Ctrl+B from terminal output;
   ansiToHtml() handles both ANSI stripping and HTML escaping. */
function renderNotes(text) {
    return (text || '').split('\n').map(function(line) {
        if (/^===.*===$/.test(line.trim())) {
            return '<span class="note-header">' + esc(line) + '</span>';
        }
        return ansiToHtml(line) || '\u200B'; /* zero-width space keeps empty lines visible */
    }).join('\n');
}
/* True while the user is actively editing notes (textarea visible).
   _showNotesDisplay() respects this flag so that snapshot refreshes and
   tab switches don't pull the user out of edit mode mid-edit. */
var _notesEditMode = false;

function _showNotesDisplay(text) {
    var disp = $('notes-display'), ta = $('notes-text');
    if (!disp || !ta) return;
    if (_notesEditMode) {
        /* User is editing — refresh the textarea value with the latest server
           text only if it differs from what they have (avoids clobbering
           in-progress edits but keeps the textarea in sync with saved content). */
        return;
    }
    /* Keep the textarea value in sync with the raw text (including ANSI codes)
       so that entering edit mode always has the correct raw string available. */
    ta.value = (text || '');
    disp.innerHTML = renderNotes(text);
    disp.style.display = '';
    ta.style.display = 'none';
}
/* Tracks which host was being edited when notes edit mode started.
   Prevents the blur handler from saving to the wrong host when the user
   clicks a different host row (L.selectedHostId updates before blur fires). */
var _noteHostId = null;

function _showNotesEdit(text) {
    var disp = $('notes-display'), ta = $('notes-text');
    if (!disp || !ta) return;
    _noteHostId = L.selectedHostId;
    _notesEditMode = true;
    ta.value = text !== undefined ? text : (ta.value || '');
    disp.style.display = 'none';
    ta.style.display = '';
    ta.focus();
}

/* ── Per-host info field tracker for blink animation ── */
var _prevInfoValues = {};
var _pendingInfoAnimations = {};  /* hostKey → [field labels that changed, waiting for tab view] */

/* Apply the green blink animation to changed info rows (Qt6: toggle_style 500ms timer) */
function _applyInfoAnimation(fields) {
    var body = $('host-info-body');
    if (!body || !fields || !fields.length) return;
    fields.forEach(function(label) {
        /* Use direct attribute selector — field labels are plain text, no CSS escaping needed.
           CSS.escape() was previously used here but it escapes spaces incorrectly for
           attribute value selectors, causing querySelector to always return null. */
        var tr = body.querySelector('[data-info-label="' + label + '"]');
        if (tr) {
            tr.classList.remove('info-changed');
            void tr.offsetWidth;  /* force reflow to restart CSS animation */
            tr.classList.add('info-changed');
            (function(el) { setTimeout(function() { el.classList.remove('info-changed'); }, 1800); })(tr);
        }
    });
}

/* ── Match patterns (global so highlightMatches() can access them) ── */
var matchPositive = [];
var matchNegative = [];

/* ── Tab unread helper (global so loadHostDetail can call it) ── */
var _prevHostData = {};  /* per-host data hashes for unread detection */
function markTabUnread(tabId) {
    /* Qt6: highlightTab ALWAYS colors the tab orange, even if it's the active tab.
       Previous code skipped active tabs → user never saw orange when watching Services tab. */
    var tabBtn = document.querySelector('[data-tab="' + tabId + '"]');
    if (tabBtn) tabBtn.classList.add('tab-unread');
    /* Persist unread state per host so orange survives host switches */
    if (L.selectedHostId) {
        if (!L._hostUnreadTabs[L.selectedHostId]) L._hostUnreadTabs[L.selectedHostId] = {};
        L._hostUnreadTabs[L.selectedHostId][tabId] = true;
    }
}

/* ── Version string — read once from the DOM so JS never has a stale hardcoded value ── */
var _VERSION = (function() {
    var el = document.getElementById('window-title');
    if (!el) return 'LEGION';
    /* Initial text is "LEGION vX.Y-flask – *untitled" — take everything before the dash */
    var txt = el.textContent || el.innerText || '';
    var dash = txt.indexOf(' \u2013 ');
    return dash > 0 ? txt.slice(0, dash).trim() : txt.split('–')[0].trim() || 'LEGION';
})();

/* ── State (mirrors ui/ViewState.py) ── */
var L = {
    hosts: [],
    services: [],
    tools: [],
    processes: [],
    selectedHostId: null,
    selectedHostIp: null,
    selectedService: null,
    _hostProcSig: null,
    _nmapSig: null,
    _hostUnreadTabs: {},   /* hostId → {tabId: true} — persists orange indicators across host switches */
    _lastProcCount: 0,
    _pollCount: 0,
    _hostSort: {col: 'ip', dir: 1},   /* Qt6: sort(3, Descending) = by Host/IP */
    _procSort: {col: 'id', dir: -1},  /* Qt6: sort(15, Descending) = newest first */
    /* Qt6: Filters.apply(up,down,checked,portopen,portfiltered,portclosed,tcp,udp,keywords) */
    _filters: {up:true, down:false, checked:true, portopen:true, portfiltered:false,
               portclosed:false, tcp:true, udp:true, keywords:[]},
    selectedTool: null,
    selectedProcessId: null,
    hostCache: {},
    pollTimer: null,
    procPollTimer: null,
    snapshot: null,
    version: 'v1.0-rewrite',
};

/* ── xterm.js terminal manager ──
   Manages the xterm.js instance in #terminal-output for Interactive processes.
   Only one terminal is displayed at a time (the selected process). */
var _termState = {
    xterm: null,         /* Terminal instance */
    fitAddon: null,      /* FitAddon instance */
    sessionId: null,     /* Current terminal session_id */
    pollTimer: null,     /* Output polling interval */
    offset: 0,           /* Read offset into PTY buffer */
};

function _showPlainOutput() {
    var p = $('plain-output'), t = $('terminal-output');
    if (p) p.style.display = '';
    if (t) t.style.display = 'none';
    _stopTerminal();
}

function _showTerminalOutput(sessionId) {
    var p = $('plain-output'), t = $('terminal-output');
    if (p) p.style.display = 'none';
    if (t) t.style.display = '';
    _connectTerminal(sessionId);
}

function _connectTerminal(sessionId) {
    /* If already connected to this session, do nothing */
    if (_termState.sessionId === sessionId && _termState.xterm) return;
    _stopTerminal();

    var container = $('terminal-output');
    if (!container) return;
    container.innerHTML = '';

    /* Bail if xterm.js not loaded (CDN failed) */
    if (typeof Terminal === 'undefined') {
        container.textContent = 'xterm.js not loaded — check network/CDN';
        return;
    }

    _termState.sessionId = sessionId;
    _termState.offset = 0;

    var term = new Terminal({
        cursorBlink: true,
        fontSize: 13,
        fontFamily: "'Courier New', monospace",
        theme: {
            background: '#191919',
            foreground: '#d4d4d4',
            cursor: '#d4d4d4',
        },
        scrollback: 5000,
    });

    var fitAddon = null;
    if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
    }

    term.open(container);

    _termState.xterm = term;
    _termState.fitAddon = fitAddon;

    /* Send user keystrokes to the PTY backend */
    term.onData(function(data) {
        postJson('/api/terminal/' + sessionId + '/input', { data: data });
    });

    /* Delay fit + resize until after browser reflow so the container has real dimensions.
       Without this, xterm.js only fills half the space and bash cursor breaks. */
    function _doFitAndResize() {
        if (!fitAddon || !_termState.xterm || _termState.sessionId !== sessionId) return;
        try { fitAddon.fit(); } catch(e) {}
        try {
            var dims = fitAddon.proposeDimensions();
            if (dims && dims.cols > 0 && dims.rows > 0) {
                postJson('/api/terminal/' + sessionId + '/resize',
                         { rows: dims.rows, cols: dims.cols });
            }
        } catch(e) {}
    }
    /* First fit after reflow */
    requestAnimationFrame(function() { setTimeout(_doFitAndResize, 100); });
    /* Second fit after content starts arriving (xterm.js may adjust after first write) */
    setTimeout(_doFitAndResize, 800);

    /* Poll for output every 50ms */
    _termState.pollTimer = setInterval(function() {
        fetchJson('/api/terminal/' + sessionId + '/output?offset=' + _termState.offset)
        .then(function(d) {
            if (d.data && d.data.length > 0) {
                term.write(d.data);
                /* Use byte-based next_offset from server — NOT d.data.length which
                   counts JS string chars (wrong for multi-byte UTF-8 like ┌└─㉿) */
                _termState.offset = d.next_offset;
            }
        }).catch(function() {});
    }, 50);

    /* Resize on window resize */
    window.addEventListener('resize', _onTermResize);
}

function _onTermResize() {
    if (_termState.fitAddon && _termState.xterm) {
        try {
            _termState.fitAddon.fit();
            var dims = _termState.fitAddon.proposeDimensions();
            if (dims && _termState.sessionId) {
                postJson('/api/terminal/' + _termState.sessionId + '/resize',
                         { rows: dims.rows, cols: dims.cols });
            }
        } catch(e) {}
    }
}

function _stopTerminal() {
    if (_termState.pollTimer) {
        clearInterval(_termState.pollTimer);
        _termState.pollTimer = null;
    }
    if (_termState.xterm) {
        _termState.xterm.dispose();
        _termState.xterm = null;
    }
    _termState.fitAddon = null;
    _termState.sessionId = null;
    _termState.offset = 0;
    window.removeEventListener('resize', _onTermResize);
}

/* ── Upper panel (dynamic tool tabs) terminal — independent from the lower one ── */
var _dynTermState = {
    xterm: null, fitAddon: null, sessionId: null, pollTimer: null, offset: 0, containerId: null,
};

function _connectDynTerminal(sessionId, container) {
    /* If already connected to this session in this container, skip */
    if (_dynTermState.sessionId === sessionId && _dynTermState.xterm) return;
    _stopDynTerminal();

    if (!container) return;
    container.innerHTML = '';
    /* Keep flex:1 + height:100% from .tool-output-area but override incompatible styles */
    container.style.overflow = 'hidden';
    container.style.padding = '0';
    container.style.whiteSpace = '';
    container.style.wordBreak = '';

    if (typeof Terminal === 'undefined') {
        container.textContent = 'xterm.js not loaded';
        return;
    }

    _dynTermState.sessionId = sessionId;
    _dynTermState.offset = 0;
    _dynTermState.containerId = container.id;

    var term = new Terminal({
        cursorBlink: true, fontSize: 13,
        fontFamily: "'Courier New', monospace",
        theme: { background: '#191919', foreground: '#d4d4d4', cursor: '#d4d4d4' },
        scrollback: 5000,
    });
    var fitAddon = null;
    if (typeof FitAddon !== 'undefined') {
        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
    }
    term.open(container);
    _dynTermState.xterm = term;
    _dynTermState.fitAddon = fitAddon;

    term.onData(function(data) {
        postJson('/api/terminal/' + sessionId + '/input', { data: data });
    });

    function _doDynFit() {
        if (!fitAddon || !_dynTermState.xterm || _dynTermState.sessionId !== sessionId) return;
        try { fitAddon.fit(); } catch(e) {}
        try {
            var dims = fitAddon.proposeDimensions();
            if (dims && dims.cols > 0 && dims.rows > 0) {
                postJson('/api/terminal/' + sessionId + '/resize',
                         { rows: dims.rows, cols: dims.cols });
            }
        } catch(e) {}
    }
    requestAnimationFrame(function() { setTimeout(_doDynFit, 100); });
    setTimeout(_doDynFit, 800);

    _dynTermState.pollTimer = setInterval(function() {
        fetchJson('/api/terminal/' + sessionId + '/output?offset=' + _dynTermState.offset)
        .then(function(d) {
            if (d.data && d.data.length > 0) {
                term.write(d.data);
                _dynTermState.offset = d.next_offset;
            }
        }).catch(function() {});
    }, 50);
}

function _stopDynTerminal() {
    if (_dynTermState.pollTimer) { clearInterval(_dynTermState.pollTimer); _dynTermState.pollTimer = null; }
    if (_dynTermState.xterm) { _dynTermState.xterm.dispose(); _dynTermState.xterm = null; }
    /* Restore original styles on the container */
    if (_dynTermState.containerId) {
        var c = $(_dynTermState.containerId);
        if (c) { c.style.overflow = ''; c.style.padding = ''; c.style.whiteSpace = ''; c.style.wordBreak = ''; }
    }
    _dynTermState.fitAddon = null;
    _dynTermState.sessionId = null;
    _dynTermState.offset = 0;
    _dynTermState.containerId = null;
}

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
function highlightMatches(html) {
    /* P1: Apply match-positive CSS to known positive patterns in rendered output */
    if (!matchPositive || matchPositive.length === 0) return html;
    var result = html;
    matchPositive.forEach(function(pattern) {
        if (!pattern) return;
        /* Only highlight if not inside a negative context */
        var escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        var re = new RegExp('(' + escaped + ')', 'gi');
        result = result.replace(re, '<span class="match-positive">$1</span>');
    });
    return result;
}

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
        /* Deactivate any currently-active panel (including dynamic panels nested in containers) */
        widget.querySelectorAll('.tab-content.active').forEach(function(c) { c.classList.remove('active'); });
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

/* ── Column resize + localStorage persistence ──────────────────────────
   Qt6: saveColumnWidths/restoreColumnWidths store CSV widths to settings.
   Flask: drag handle on <th> right edge → mousemove → localStorage.
   Key format: col-<tableId>-<colIndex>  (e.g. 'col-hosts-table-0')
   ──────────────────────────────────────────────────────────────────── */
function initColResizers(tableId) {
    var tbl = $(tableId);
    if (!tbl) return;
    var headers = Array.from(tbl.querySelectorAll('thead th'));
    headers.forEach(function(th, idx) {
        /* Restore saved width */
        var saved = localStorage.getItem('col-' + tableId + '-' + idx);
        if (saved) th.style.width = saved + 'px';

        /* Add resize handle div */
        var handle = document.createElement('div');
        handle.style.cssText = 'position:absolute;right:0;top:0;bottom:0;width:5px;cursor:col-resize;z-index:1';
        th.style.position = 'relative';
        th.appendChild(handle);

        var startX, startW;
        handle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            e.stopPropagation();
            startX = e.clientX;
            startW = th.offsetWidth;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';

            function onMove(ev) {
                var newW = Math.max(40, startW + ev.clientX - startX);
                th.style.width = newW + 'px';
            }
            function onUp(ev) {
                var newW = Math.max(40, startW + ev.clientX - startX);
                localStorage.setItem('col-' + tableId + '-' + idx, newW);
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            }
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    });
}

/* ================================================================
   RENDERING (mirrors view.py update methods)
   ================================================================ */

/* ── Hosts table (view.py:updateHostsTableView) — with column sort ── */
/* Qt6: setSortingEnabled(True) + HostsTableModel.sort(3, Descending) by default */
function _ipToNum(ip) {
    return (ip||'').split('.').reduce(function(a,o){ return a*256 + (parseInt(o,10)||0); }, 0);
}
function renderHosts(hosts) {
    L.hosts = hosts || [];
    _drawHosts();
}
function _drawHosts() {
    var body = $('hosts-body');
    if (!body) return;
    var overlay = $('add-hosts-overlay');
    if (overlay) overlay.classList.toggle('visible', L.hosts.length === 0);
    var tableWrap = $('hosts-table-wrap');
    if (tableWrap) tableWrap.style.display = L.hosts.length ? '' : 'none';

    /* Apply host-level filters (Qt6: Filters.apply → updateInterface) */
    var f = L._filters;
    var filtered = L.hosts.filter(function(h) {
        if (!f.up   && h.status === 'up')   return false;
        if (!f.down && h.status === 'down')  return false;
        /* checked=False means "hide hosts already marked as checked" */
        if (!f.checked && h.checked === true) return false;
        if (f.keywords && f.keywords.length) {
            var text = ((h.ip||'') + ' ' + (h.hostname||'') + ' ' + (h.os||'')).toLowerCase();
            if (!f.keywords.every(function(kw) { return text.includes(kw.toLowerCase()); }))
                return false;
        }
        return true;
    });

    /* Sort hosts */
    var col = L._hostSort.col, dir = L._hostSort.dir;
    var sorted = filtered.slice().sort(function(a, b) {
        var av, bv;
        if (col === 'ip') { av = _ipToNum(a.ip); bv = _ipToNum(b.ip); }
        else { av = (a[col]||'').toLowerCase(); bv = (b[col]||'').toLowerCase(); }
        return av < bv ? -dir : av > bv ? dir : 0;
    });

    body.innerHTML = '';
    sorted.forEach(function(h) {
        var tr = document.createElement('tr');
        tr.dataset.hostId = h.id || '';
        tr.dataset.hostIp = h.ip || '';
        if (L.selectedHostId && parseInt(h.id) === L.selectedHostId) tr.classList.add('selected');
        /* Qt6: checked hosts shown with visual indicator (checkmark prefix) */
        if (h.checked) tr.classList.add('host-checked');
        tr.style.cursor = 'pointer';
        var checkMark = h.checked ? '\u2713 ' : '';
        tr.innerHTML = '<td>' + esc(h.os||'') + '</td><td>' + checkMark + esc(h.ip||'') +
                       (h.hostname && h.hostname !== h.ip ? ' ('+esc(h.hostname)+')' : '') + '</td>';
        body.appendChild(tr);
    });
    setText('stat-hosts', L.hosts.length);

    /* Update sort arrows */
    var tbl = $('hosts-table');
    if (tbl) tbl.querySelectorAll('th[data-sort]').forEach(function(th) {
        var isActive = th.dataset.sort === col;
        _setThText(th, (th.dataset.sort === 'os' ? 'OS' : 'Host') +
                         (isActive ? (dir === 1 ? ' \u25b2' : ' \u25bc') : ''));
    });

    /* Auto-click first host when none selected */
    if (!L.selectedHostId && L.hosts.length > 0) {
        var firstRow = body.querySelector('tr[data-host-id]');
        if (firstRow) firstRow.click();
    }
}

/* ── Services table (left) — with sortable Port column ── */
var _svcSort = {col: 'service', dir: 1};  // 1=asc, -1=desc

function renderServiceNames(services) {
    L.services = services || [];
    _drawServices();
}

function _drawServices() {
    var body = $('services-body');
    if (!body) return;
    /* Sort */
    var col = _svcSort.col, dir = _svcSort.dir;
    var sorted = L.services.slice().sort(function(a, b) {
        var av = a[col] || '', bv = b[col] || '';
        if (col === 'port') { av = parseInt(av)||0; bv = parseInt(bv)||0; }
        return av < bv ? -dir : av > bv ? dir : 0;
    });
    body.innerHTML = '';
    sorted.forEach(function(s) {
        var tr = document.createElement('tr');
        tr.dataset.service = s.service || '';
        tr.dataset.port = s.port || '';
        tr.style.cursor = 'pointer';
        if (L.selectedService === s.service) tr.classList.add('selected');
        tr.innerHTML = '<td>' + esc(s.service||'') + '</td><td>' + esc(s.port||'') + '</td>';
        body.appendChild(tr);
    });
    /* Update sort arrows in headers */
    var tbl = $('services-table');
    if (tbl) tbl.querySelectorAll('th[data-sort]').forEach(function(th) {
        var isActive = th.dataset.sort === col;
        _setThText(th, (th.dataset.sort === 'service' ? 'Name' : 'Port') +
                         (isActive ? (dir === 1 ? ' ▲' : ' ▼') : ''));
    });
}

/* ── Tools table (left) — tools that actually ran (view.py:updateToolsTableView + _dedupeTools) ── */
function renderTools(tools) {
    /* Shows unique tool names from process DB — matches Qt6 behavior.
       tool_id == process.name (e.g. "nmap", "ssh-enum"), label == same.
       run_count = number of times this tool has been run. */
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
        var countStr = runCount > 1 ? ' (' + runCount + ')' : '';
        /* Colour tool entry red if any of its processes found a match (Qt6: tab-goes-red) */
        var matchStyle = t.has_match ? ' style="color:#f44;font-weight:700"' : '';
        var matchStar  = t.has_match ? '<span title="Match found">★ </span>' : '';
        tr.innerHTML = '<td' + matchStyle + '>' + matchStar + esc(t.label || t.tool_id || '') + countStr + '</td>';
        body.appendChild(tr);
    });
}

/* ── Processes table (view.py:updateProcessesTableView) — with column sort ── */
/* Qt6: setSortingEnabled(True) + ProcessesTableModel.sort(15, Descending) = newest first */
var _statusOrder = {Running:0, Waiting:1, Finished:2, Crashed:3, Killed:3, Cancelled:3};
function renderProcesses(processes) {
    L.processes = processes || [];
    _drawProcesses();
}
function _drawProcesses() {
    var filter = ($('process-status-filter')||{}).value || '';
    var body = $('processes-body');
    if (!body) return;

    /* Sort processes */
    var col = L._procSort.col, dir = L._procSort.dir;
    var sorted = L.processes.slice().sort(function(a, b) {
        var av, bv;
        if (col === 'id') { av = parseInt(a.id)||0; bv = parseInt(b.id)||0; }
        else if (col === 'elapsed') {
            av = parseFloat(a.elapsed_secs != null ? a.elapsed_secs : a.elapsed)||0;
            bv = parseFloat(b.elapsed_secs != null ? b.elapsed_secs : b.elapsed)||0;
        } else if (col === 'status') {
            av = _statusOrder[a.status] !== undefined ? _statusOrder[a.status] : 9;
            bv = _statusOrder[b.status] !== undefined ? _statusOrder[b.status] : 9;
        } else if (col === 'target') {
            av = ((a.hostIp||'') + ':' + (a.port||'')).toLowerCase();
            bv = ((b.hostIp||'') + ':' + (b.port||'')).toLowerCase();
        } else {
            av = (a[col]||'').toLowerCase(); bv = (b[col]||'').toLowerCase();
        }
        return av < bv ? -dir : av > bv ? dir : 0;
    });

    body.innerHTML = '';
    var running = 0, finished = 0;
    sorted.forEach(function(p) {
        if (p.status === 'Running') running++;
        else finished++;
        if (filter && p.status !== filter) return;
        var tr = document.createElement('tr');
        tr.dataset.processId = p.id || '';
        tr.style.cursor = 'pointer';
        if (L.selectedProcessId && parseInt(p.id) === L.selectedProcessId) tr.classList.add('selected');
        if (p.has_match) tr.classList.add('proc-match');
        var statusClass = p.status === 'Running' ? 'proc-running' : p.status === 'Crashed' ? 'proc-crashed' : p.status === 'Waiting' ? 'proc-waiting' : 'proc-finished';
        var spinnerHtml = p.status === 'Running' ? '<span class="spinner"></span>' : '';
        var matchIcon = p.has_match ? '<span title="Match found" style="color:var(--match-positive,#ff0)">★</span> ' : '';
        var target = (p.hostIp||'') + (p.port ? ':'+p.port : '');
        var pct = p.percent || '';
        /* Elapsed: live seconds from snapshot for Running; stored seconds for Finished */
        var elapsedStr = '';
        function fmtSecs(s) {
            s = Math.round(parseFloat(s) || 0);
            var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
            return (h ? h + 'h ' : '') + (h || m ? m + 'm ' : '') + sec + 's';
        }
        if (p.status === 'Running' && p.elapsed_secs != null) {
            elapsedStr = fmtSecs(p.elapsed_secs);
        } else if (p.elapsed && parseFloat(p.elapsed) > 0) {
            elapsedStr = fmtSecs(p.elapsed);
        }
        /* Show tabTitle (e.g. "nmap (stage 1)") when available, fall back to name */
        var displayName = p.tabTitle && p.tabTitle !== p.name ? p.tabTitle : p.name || '';
        tr.innerHTML =
            '<td>' + esc(p.id) + '</td>' +
            '<td>' + matchIcon + esc(displayName) + '</td>' +
            '<td>' + esc(target) + '</td>' +
            '<td>' + esc(p.pid||'') + '</td>' +
            '<td class="' + statusClass + '">' + spinnerHtml + esc(p.status||'') + '</td>' +
            '<td>' + esc(pct) + '</td>' +
            '<td>' + esc(elapsedStr) + '</td>';
        body.appendChild(tr);
    });
    setText('stat-running', running);
    setText('stat-finished', finished);
    setText('process-count', L.processes.length);

    /* Update sort arrows */
    var ptbl = $('processes-table');
    var colLabels = {id:'ID', name:'Name', target:'Target', status:'Status', elapsed:'Elapsed'};
    if (ptbl) ptbl.querySelectorAll('th[data-sort]').forEach(function(th) {
        var isActive = th.dataset.sort === col;
        _setThText(th, (colLabels[th.dataset.sort] || th.dataset.sort) +
                         (isActive ? (dir === 1 ? ' \u25b2' : ' \u25bc') : ''));
    });

    /* Auto-select: when a new Running or Interactive process appears, click its row
       so the output panel shows it. Include Interactive so terminal sessions auto-display.
       Fix: track active process IDs; when a NEW one appears, click its row. */
    var curActiveIds = L.processes.filter(function(p){return p.status==='Running' || p.status==='Interactive';})
                                   .map(function(p){return String(p.id);}).sort().join(',');
    if (!L._prevRunningIds) L._prevRunningIds = '';
    if (curActiveIds !== L._prevRunningIds) {
        /* Find newly-active process IDs */
        var prevSet = L._prevRunningIds ? L._prevRunningIds.split(',') : [];
        var newActive = curActiveIds.split(',').filter(function(id){
            return id && prevSet.indexOf(id) < 0;
        });
        if (newActive.length > 0) {
            /* Only auto-select when nothing is currently selected (initial load).
               After the first selection the user controls which process they view —
               auto-switching every time a new process starts is disruptive. */
            if (!L.selectedProcessId) {
                var newest = newActive[newActive.length-1];
                var newRow = body.querySelector('tr[data-process-id="' + newest + '"]');
                if (newRow) newRow.click();
            }
        } else if (!L.selectedProcessId && L.processes.length > 0) {
            var firstProc = body.querySelector('tr[data-process-id]');
            if (firstProc) firstProc.click();
        }
    }
    L._prevRunningIds = curActiveIds;
    L._lastProcCount = L.processes.length;
}

function _drawOsHosts() {
    var body = $('os-hosts-body');
    if (!body) return;
    var col=_osHostsSort.col, dir=_osHostsSort.dir;
    var sorted = _osHostsData.slice().sort(function(a,b) {
        var av=col==='ip'?_ipToNum(a.ip):(a[col]||'').toLowerCase();
        var bv=col==='ip'?_ipToNum(b.ip):(b[col]||'').toLowerCase();
        return av<bv?-dir:av>bv?dir:0;
    });
    body.innerHTML='';
    sorted.forEach(function(h) {
        var row=document.createElement('tr');
        row.dataset.hostId=h.id; row.style.cursor='pointer';
        row.innerHTML='<td>'+esc(h.ip||'')+'</td><td>'+esc(h.hostname||'')+'</td>';
        body.appendChild(row);
    });
    _updateSortHeaders('os-hosts-table',_osHostsSort,{ip:'IP',hostname:'Hostname'});
    /* Auto-click first row if none selected */
    if (!body.querySelector('tr.selected')) {
        var firstRow = body.querySelector('tr[data-host-id]');
        if (firstRow) firstRow.click();
    }
}

/* ── OS table (view.py:updateOsListView → getOperatingSystemsSummary) ── */
var _osListHash = '';  /* track changes so we don't re-render every 1.5s poll */
function renderOsList() {
    var groups = (L.snapshot && L.snapshot.os_groups) || [];
    var hash = groups.map(function(g){return g.os+':'+g.count;}).join('|');
    if (hash === _osListHash && $('os-list-body').querySelector('tr')) return; /* no change */
    _osListHash = hash;

    var body = $('os-list-body');
    if (!body) return;
    /* Remember selected OS before clearing */
    var selectedOs = '';
    var selRow = body.querySelector('tr.selected');
    if (selRow) selectedOs = selRow.dataset.os || '';

    var col=_osSort.col, dir=_osSort.dir;
    var sorted = groups.slice().sort(function(a,b) {
        var av=col==='count'?parseInt(a.count)||0:(a[col]||'').toLowerCase();
        var bv=col==='count'?parseInt(b.count)||0:(b[col]||'').toLowerCase();
        return av<bv?-dir:av>bv?dir:0;
    });
    body.innerHTML = '';
    sorted.forEach(function(g) {
        var tr = document.createElement('tr');
        tr.dataset.os = g.os || 'Unknown';
        tr.style.cursor = 'pointer';
        tr.innerHTML = '<td>' + esc(g.os || 'Unknown') + '</td><td>' + (g.count || 0) + '</td>';
        if ((g.os||'Unknown') === selectedOs) tr.classList.add('selected');
        body.appendChild(tr);
    });
    _updateSortHeaders('os-list-table', _osSort, {os:'OS', count:'#'});
    /* If nothing was selected, auto-click first row. If something WAS selected,
       re-click it to refresh the hosts pane with potentially new data. */
    var targetRow = selectedOs
        ? body.querySelector('tr[data-os="' + selectedOs + '"]')
        : body.querySelector('tr[data-os]');
    if (targetRow) targetRow.click();
}

/* ── Host detail (view.py:updateRightPanel) ── */
/* ── Render Information tab (view.py:updateInformationView + buildInformationText) ── */
/* Qt6: HostInformationWidget.updateFields tracks changed fields → onTabViewed blinks them
   green (500ms, 3 cycles). Flask: detect changed fields and apply .info-changed CSS class. */
function renderInformation(info) {
    var body = $('host-info-body');
    if (!body) return;
    var hostKey = info.ip || 'unknown';
    var prev = _prevInfoValues[hostKey] || {};
    var newPrev = {};
    body.innerHTML = '';
    var rows = [
        ['Status',          info.status],
        ['IP',              info.ip],
        ['IPv6',            info.ipv6],
        ['Hostname',        info.hostname],
        ['MAC Address',     info.mac],
        ['Vendor',          info.vendor],
        ['OS Match',        info.os],
        ['OS Accuracy',     info.os_accuracy ? info.os_accuracy + '%' : ''],
        ['Open Ports',      info.open_ports],
        ['Closed Ports',    info.closed_ports],
        ['Filtered Ports',  info.filtered_ports],
        ['ASN',             info.asn],
        ['ISP',             info.isp],
        ['Country',         info.country_code],
        ['City',            info.city],
        ['Latitude',        info.latitude],
        ['Longitude',       info.longitude],
    ];
    var changedFields = [];
    var hasPrev = Object.keys(prev).length > 0;
    rows.forEach(function(r) {
        var label = r[0], val = (r[1] != null && r[1] !== '') ? String(r[1]) : null;
        newPrev[label] = val || '';
        if (val == null) return; // skip truly empty fields for display
        var tr = document.createElement('tr');
        tr.dataset.infoLabel = label;
        tr.innerHTML = '<td style="color:var(--disabled);width:130px;white-space:nowrap">' + esc(label) +
                       '</td><td>' + esc(val) + '</td>';
        /* Flash: value changed, field newly appeared, OR first load for this host.
           Qt6: updateInformationView compares against blank initial state,
           so ALL fields flash when a host is first discovered. */
        if (hasPrev) {
            if (label in prev && prev[label] !== val) changedFields.push(label);
            else if (!(label in prev) || prev[label] === '') changedFields.push(label);
        } else if (val) {
            /* First load for this host — ALL fields with values should flash */
            changedFields.push(label);
        }
        body.appendChild(tr);
    });
    _prevInfoValues[hostKey] = newPrev;

    if (changedFields.length > 0) {
        /* Check if Information tab is currently the active right-panel tab */
        var infoBtn = $('right-tab-bar') && $('right-tab-bar').querySelector('[data-tab="info-right"]');
        if (infoBtn && infoBtn.classList.contains('active')) {
            /* Tab is visible — animate immediately */
            _applyInfoAnimation(changedFields);
        } else {
            /* Tab not visible — queue for when user clicks it (Qt6: pending_blink_labels) */
            _pendingInfoAnimations[hostKey] = (_pendingInfoAnimations[hostKey] || []).concat(changedFields);
        }
    }
}

/* ── Sortable right-panel tables ── */
var _portsSort   = {col:'port',     dir:1};
var _scriptsSort = {col:'script_id',dir:1};
var _cvesSort    = {col:'severity', dir:-1};  /* highest severity first */
var _osSort      = {col:'os',       dir:1};
var _osHostsSort = {col:'ip',       dir:1};
var _portsData=[], _scriptsData=[], _cvesData=[], _osHostsData=[];

function _sortArrow(sort, col, label) {
    return label + (sort.col===col ? (sort.dir===1?' \u25b2':' \u25bc') : '');
}
/* Update a th's label text without destroying child elements (e.g. resize handles).
   Using th.textContent would wipe the handle divs appended by initColResizers. */
function _setThText(th, text) {
    /* Find the first text node and update it, or prepend a new one */
    for (var i = 0; i < th.childNodes.length; i++) {
        if (th.childNodes[i].nodeType === 3) {   /* TEXT_NODE */
            th.childNodes[i].textContent = text;
            return;
        }
    }
    th.insertBefore(document.createTextNode(text), th.firstChild);
}

function _updateSortHeaders(tblId, sort, colMap) {
    var tbl = $(tblId);
    if (!tbl) return;
    tbl.querySelectorAll('th[data-sort]').forEach(function(th) {
        _setThText(th, _sortArrow(sort, th.dataset.sort, colMap[th.dataset.sort] || th.dataset.sort));
    });
}
function _sortClick(sort, col, drawFn) {
    if (sort.col===col) sort.dir*=-1; else { sort.col=col; sort.dir=1; }
    drawFn();
}

/* Ports (Services right panel) */
function renderPorts(ports, hostIp) {
    _portsData = (ports||[]).map(function(p){ p._hostIp=hostIp; return p; });
    _drawPorts();
}
function _drawPorts() {
    var body = $('host-detail-ports');
    if (!body) return;
    var col=_portsSort.col, dir=_portsSort.dir;
    var sorted = _portsData.slice().sort(function(a,b) {
        var av,bv;
        if (col==='port') { av=parseInt(a.port)||0; bv=parseInt(b.port)||0; }
        else { av=(a[col]||'').toLowerCase(); bv=(b[col]||'').toLowerCase(); }
        return av<bv?-dir:av>bv?dir:0;
    });
    body.innerHTML='';
    sorted.forEach(function(p) {
        var svc=p.service||{};
        var stateStyle=p.state==='open'?'color:#4c4':p.state==='filtered'?'color:#fa0':'color:var(--disabled)';
        var tr=document.createElement('tr');
        tr.dataset.port=p.port||''; tr.dataset.protocol=p.protocol||'tcp';
        tr.dataset.service=(svc.name||'');
        tr.innerHTML='<td>'+esc(p._hostIp||'')+'</td><td>'+esc(p.port)+'</td><td>'+esc(p.protocol)+
                     '</td><td style="'+stateStyle+'">'+esc(p.state)+'</td>'+
                     '<td>'+esc(svc.name||'')+'</td>'+
                     '<td>'+esc(((svc.product||'')+' '+(svc.version||'')).trim())+'</td>';
        body.appendChild(tr);
    });
    _updateSortHeaders('ports-table',_portsSort,{port:'Port',protocol:'Proto',state:'State',name:'Service'});
    /* Notify port state filter to re-apply after each render */
    document.dispatchEvent(new CustomEvent('legion:ports-rendered'));
}

/* Scripts tab */
function renderScripts(scripts) {
    _scriptsData = scripts || [];
    _drawScripts();
}
function _drawScripts() {
    var body = $('host-detail-scripts');
    if (!body) return;
    var col=_scriptsSort.col, dir=_scriptsSort.dir;
    var sorted = _scriptsData.slice().sort(function(a,b) {
        var av=parseInt(col==='port'?a.port:0)||((a[col]||'').toLowerCase());
        var bv=parseInt(col==='port'?b.port:0)||((b[col]||'').toLowerCase());
        if(col==='port'){av=parseInt(a.port)||0;bv=parseInt(b.port)||0;}
        return av<bv?-dir:av>bv?dir:0;
    });
    body.innerHTML='';
    sorted.forEach(function(s) {
        var tr=document.createElement('tr');
        tr.dataset.scriptId=s.id||''; tr.style.cursor='pointer';
        tr.innerHTML='<td>'+esc(s.script_id||'')+'</td><td>'+esc(s.port||'')+'</td>';
        body.appendChild(tr);
    });
    _updateSortHeaders('scripts-table',_scriptsSort,{script_id:'Script',port:'Port'});
}

/* CVEs tab */
function renderCves(cves) {
    _cvesData = cves || [];
    _drawCves();
}
function _drawCves() {
    var body = $('host-detail-cves');
    if (!body) return;
    var col=_cvesSort.col, dir=_cvesSort.dir;
    var sorted = _cvesData.slice().sort(function(a,b) {
        var av,bv;
        if(col==='severity'){av=parseFloat(a.severity)||0;bv=parseFloat(b.severity)||0;}
        else{av=(a[col]||'').toLowerCase();bv=(b[col]||'').toLowerCase();}
        return av<bv?-dir:av>bv?dir:0;
    });
    body.innerHTML='';
    sorted.forEach(function(c) {
        var tr=document.createElement('tr');
        var sevStyle=parseFloat(c.severity||0)>=7?'color:#f44':parseFloat(c.severity||0)>=4?'color:#fa0':'';
        tr.innerHTML='<td>'+esc(c.name||'')+'</td>'+
                     '<td style="'+sevStyle+'">'+esc(c.severity||'')+'</td>'+
                     '<td>'+esc(c.product||'')+'</td>' +
                       '<td>'+esc(c.source||'')+'</td>';
        body.appendChild(tr);
    });
    _updateSortHeaders('cves-table',_cvesSort,{name:'CVE',severity:'Score',product:'Product',source:'Source'});
}

function loadHostDetail(hostId) {
    /* Fire all 4 requests in parallel — Qt6 updates each tab independently */
    var baseUrl = '/api/workspace/hosts/' + hostId;
    Promise.all([
        fetchJson(baseUrl),
        fetchJson(baseUrl + '/information'),
        fetchJson(baseUrl + '/scripts-list'),
        fetchJson(baseUrl + '/cves-list'),
    ]).then(function(results) {
        var data    = results[0];
        var info    = results[1];
        var scripts = results[2].scripts || [];
        var cves    = results[3].cves    || [];

        L.hostCache[hostId] = data;
        var host = data.host || {};
        L.selectedHostIp = host.ip || '';

        /* Services tab (right) — sortable by column click */
        renderPorts(data.ports || [], host.ip || '');

        /* Information tab — full host stats from dedicated endpoint */
        renderInformation(info);

        /* Scripts tab */
        renderScripts(scripts);

        /* CVEs tab */
        renderCves(cves);

        /* Notes — show styled display div (=== headers highlighted) */
        _showNotesDisplay(data.note || '');

        /* Window title — don't override project name during post-open auto-select.
           L._suppressTitleUpdate is set by the openProject handler so the title
           shows the project filename until the user explicitly clicks a host. */
        if (L._suppressTitleUpdate) {
            L._suppressTitleUpdate = false;
        } else {
            var title = host.ip + (host.hostname && host.hostname !== host.ip ? ' ('+host.hostname+')' : '');
            setText('window-title', _VERSION + ' – ' + title);
        }

        /* Dynamic tool output tabs for this host */
        renderDynamicToolTabs(host.ip);

        /* ── Tab unread detection (Qt6: highlightTab fires on data change) ──
           Compare current data against previous load for this host.
           Mark the tab orange if new data arrived since last load. */
        var hkey = 'h' + hostId;
        /* Comprehensive inf hash — any change in any field triggers orange + animation.
           Previously only tracked os/open_ports/hostname; closed_ports, MAC, etc. missed. */
        var cur = {
            svc:  (data.ports||[]).map(function(p){return p.port+'/'+p.state+'/'+(p.service||{}).name;}).join(','),
            scr:  String((scripts||[]).length),
            cve:  String((cves||[]).length),
            inf:  [info.status,info.ip,info.ipv6,info.hostname,info.mac,info.vendor,
                   info.os,info.os_accuracy,info.open_ports,info.closed_ports,
                   info.filtered_ports,info.asn,info.isp,info.country_code,info.city].join('|'),
            note: String((data.note||'').length)
        };
        var prev = _prevHostData[hkey];
        if (prev) {
            /* Data changed since last load — mark changed tabs orange */
            if (cur.svc  !== prev.svc)  markTabUnread('services-right');
            if (cur.scr  !== prev.scr)  markTabUnread('scripts-right');
            if (cur.cve  !== prev.cve)  markTabUnread('cves-right');
            if (cur.inf  !== prev.inf)  markTabUnread('info-right');
            if (cur.note !== prev.note) markTabUnread('notes-right');
        } else {
            /* First load for this host — Qt6: highlightTab fires when new data appears.
               Mark all tabs with data as orange so user knows there's info to see. */
            if (cur.svc)              markTabUnread('services-right');
            if (cur.inf)              markTabUnread('info-right');
            if (cur.scr !== '0')      markTabUnread('scripts-right');
            if (cur.cve !== '0')      markTabUnread('cves-right');
        }
        _prevHostData[hkey] = cur;

    }).catch(function(err) {
        console.error('loadHostDetail error:', err);
    });
}

/* ── Dynamic tool output tabs (view.py:restoreToolTabsForHost) ── */
/* Per-process scroll position memory: 'bottom' | integer scrollTop.
   Survives the container.innerHTML='' wipe in renderDynamicToolTabs so the
   user's scroll position is honoured on every 1.5 s poll cycle. */
var _procScrollPos = {};

/* True while the user has text selected inside #dynamic-tabs-container
   (set on mousedown, maintained by selectionchange, cleared when selection
   goes away).  Both renderDynamicToolTabs and loadProcessOutput check this
   before any DOM mutation so selections survive refreshes and live output. */
var _dynSelLocked = false;

/* Xterm selection saved in the capture phase of Ctrl+B, before xterm's
   element-level keydown handler fires and clears the internal selection. */
var _savedXtermSel = '';

function renderDynamicToolTabs(hostIp) {
    /* Check lock BEFORE any DOM change.  If the user is selecting (or has
       selected) text in the upper output area, skip this rebuild entirely.
       The next poll will run normally once the selection is released. */
    if (_dynSelLocked) return;

    var bar = $('right-tab-bar');
    var container = $('dynamic-tabs-container');

    /* Remember which dynamic tab was active before we wipe everything */
    var activeBtn = bar.querySelector('.dynamic-tab.active');
    var prevActiveTabId = activeBtn ? activeBtn.dataset.tab : null;

    /* Save scroll positions of all output elements BEFORE wiping.
       container.innerHTML='' destroys the DOM nodes and their scrollTop. */
    container.querySelectorAll('[id^="dyn-output-"]').forEach(function(el) {
        var pid = el.id.replace('dyn-output-', '');
        var gap = el.scrollHeight - el.scrollTop - el.clientHeight;
        _procScrollPos[pid] = (gap < 40) ? 'bottom' : el.scrollTop;
    });

    /* Remove old dynamic tabs */
    bar.querySelectorAll('.dynamic-tab').forEach(function(b) { b.remove(); });
    container.innerHTML = '';

    /* Find processes for this host — matched ones sort first (Qt6: tab turns red) */
    var hostProcs = L.processes.filter(function(p) { return p.hostIp === hostIp; });
    hostProcs.sort(function(a, b) { return (b.has_match ? 1 : 0) - (a.has_match ? 1 : 0); });
    hostProcs.forEach(function(proc) {
        var tabId = 'dyntab-' + proc.id;
        var btn = document.createElement('button');
        btn.className = 'tab-btn dynamic-tab' + (proc.has_match ? ' tab-match' : '');
        btn.type = 'button';
        btn.dataset.tab = tabId;
        /* Use tabTitle when it adds info (e.g. "nmap (stage 1)"), else name+port */
        var label = proc.tabTitle && proc.tabTitle !== proc.name
            ? proc.tabTitle
            : (proc.name||'?') + (proc.port ? ' '+proc.port : '');
        /* Qt6: closeHostToolTab — close-x button on every dynamic tab */
        btn.innerHTML = esc(label) + '<span class="close-x" title="Close tab">\u00d7</span>';
        bar.appendChild(btn);

        var panel = document.createElement('div');
        panel.className = 'tab-content';  /* CSS provides: display:none, flex:1, min-height:0, flex-direction:column */
        panel.id = tabId;
        panel.innerHTML = '<div class="tool-output-area ansi" id="dyn-output-' + proc.id + '"></div>';
        /* Font size applied automatically via CSS --output-font-size variable */
        container.appendChild(panel);
    });

    /* Restore the previously active dynamic tab so the user's view is preserved */
    if (prevActiveTabId) {
        var restoredBtn = bar.querySelector('[data-tab="' + prevActiveTabId + '"]');
        if (restoredBtn) {
            restoredBtn.click();  /* re-activates tab and reloads its output */
        }
    }
}

/* ── Load process output inline (view.py tool output display) ── */
/* Qt6: updateTabHighlight → QLabel 'Matches: ...' yellow banner above output */
function loadProcessOutput(processId, targetEl) {
    /* Determine scroll intent before the async fetch.
       Two cases:
       A) Element has real content (scrollHeight > clientHeight): read and save
          the actual scroll position into _procScrollPos.
       B) Element is empty/fresh (just rebuilt by renderDynamicToolTabs):
          _procScrollPos[processId] holds the position from before the wipe.
          Use that instead of trusting scrollTop=0 on a brand-new empty node,
          which would incorrectly read as atBottom=true every time.       */
    var _hasContent = targetEl.scrollHeight > targetEl.clientHeight;
    var _saved = _procScrollPos[processId];
    var atBottom;
    if (_hasContent) {
        atBottom = targetEl.scrollHeight - targetEl.scrollTop - targetEl.clientHeight < 40;
        _procScrollPos[processId] = atBottom ? 'bottom' : targetEl.scrollTop;
    } else if (_saved !== undefined) {
        atBottom = (_saved === 'bottom');
    } else {
        atBottom = true;   /* first load — default to follow */
    }
    fetchJson('/api/processes/' + processId + '/output?max_chars=50000').then(function(data) {
        /* For dynamic-tab output (dyn-output-*): honour the container-level lock.
           _dynSelLocked is set on mousedown in the container and maintained by
           selectionchange, so it is already true before the first DOM rebuild
           attempt — even during a mid-drag selection. */
        var _isDynTab = targetEl.id && targetEl.id.indexOf('dyn-output-') === 0;
        if (_isDynTab && _dynSelLocked) return;

        /* For the lower panel (plain-output): skip if a selection is anchored
           inside the element and it already has content. */
        if (!_isDynTab) {
            try {
                var _ds = window.getSelection();
                if (_ds && _ds.toString() && _ds.rangeCount > 0 && targetEl.childNodes.length > 1) {
                    var _dr = _ds.getRangeAt(0);
                    if (targetEl.contains(_dr.startContainer) || targetEl.contains(_dr.endContainer)) {
                        return;
                    }
                }
            } catch(e) {}
        }

        var text = data.output_chunk || data.output || '';
        /* Prepend match banner when process has match hits (Qt6: yellow QLabel at top) */
        var matchBanner = '';
        var proc = L.processes.find(function(p) { return String(p.id) === String(processId); });
        if (proc && proc.has_match && proc.match_text) {
            matchBanner = '<div class="match-banner">\u2605 Matches: ' + esc(proc.match_text) + '</div>';
        }
        /* Screenshooter: output is "screenshot:/path/to/file.png" — render as image */
        if (text.startsWith('screenshot:')) {
            var imgPath = text.slice('screenshot:'.length).trim();
            var imgUrl = '/api/screenshots?path=' + encodeURIComponent(imgPath);
            targetEl.innerHTML = matchBanner + '<img src="' + imgUrl + '" style="max-width:100%;max-height:100%;object-fit:contain" alt="screenshot"/>';
        } else {
            var html = matchBanner + highlightMatches(ansiToHtml(text));
            /* If process is Running but output hasn't changed, show activity indicator */
            if (proc && proc.status === 'Running' && text.length > 0) {
                var elapsed = proc.elapsed_secs || 0;
                var fmtE = Math.floor(elapsed/60) + 'm ' + (elapsed%60) + 's';
                html += '\n<div style="color:var(--disabled);margin-top:8px;font-style:italic">'
                      + '\u23f3 Running... ' + fmtE + ' elapsed</div>';
            }
            targetEl.innerHTML = html;
        }
        /* Restore scroll position after the innerHTML reflow. */
        if (atBottom) {
            setTimeout(function() { targetEl.scrollTop = targetEl.scrollHeight; }, 0);
        } else if (typeof _saved === 'number') {
            /* Restore the exact pixel offset the user was at before the tab rebuild. */
            setTimeout(function() { targetEl.scrollTop = _saved; }, 0);
        }
    }).catch(function() {
        targetEl.textContent = 'Error loading output';
    });
}

/* ================================================================
   INTERACTIONS (mirrors view.py signal connections)
   ================================================================ */

/* ── Modal open/close helpers (global scope — used by JS and execute_script) ── */
function openModal(id) {
    var el = $(id);
    if (!el) return;
    el.classList.add('is-open'); el.style.display = 'flex';
    setTimeout(function() {
        var inp = el.querySelector('input[type="text"]:not([disabled]),textarea:not([disabled])');
        if (inp) inp.focus();
    }, 50);
}
function closeModal(id) {
    var el = $(id);
    if (el) { el.classList.remove('is-open'); el.style.display = 'none'; }
}

function initInteractions() {
    /* ── Host click (view.py:hostTableClick) ── */
    $('hosts-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostId) return;
        var hostId = parseInt(tr.dataset.hostId);
        /* Qt6: clearAllTabHighlights then restore per-host unread state.
           Tabs that were unread for the new host get orange back; tabs for
           the previous host had their state already saved in L._hostUnreadTabs. */
        if (L.selectedHostId !== hostId) {
            var unreadForNewHost = L._hostUnreadTabs[hostId] || {};
            $('right-tab-bar').querySelectorAll('.tab-btn').forEach(function(btn) {
                btn.classList.remove('tab-unread');
                var tabId = btn.dataset.tab || '';
                if (tabId && unreadForNewHost[tabId]) {
                    btn.classList.add('tab-unread');
                }
            });
        }
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

    /* ── Host double-click → copy IP to clipboard (Qt6: hostTableDoubleClick → copyToClipboard) ── */
    $('hosts-body').addEventListener('dblclick', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostIp) return;
        var ip = tr.dataset.hostIp || '';
        if (!ip) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(ip).catch(function() {});
        } else {
            /* Fallback for environments without clipboard API */
            var ta = document.createElement('textarea');
            ta.value = ip; document.body.appendChild(ta);
            ta.select(); document.execCommand('copy');
            document.body.removeChild(ta);
        }
        /* Brief visual feedback */
        var origBg = tr.style.background;
        tr.style.background = 'var(--highlight,#2a82da)';
        setTimeout(function() { tr.style.background = origBg; }, 200);
    });

    /* ── Hosts table header click → sort (Qt6: setSortingEnabled(True)) ── */
    var hostsTable = $('hosts-table');
    if (hostsTable) hostsTable.querySelector('thead').addEventListener('click', function(e) {
        var th = e.target.closest('th[data-sort]');
        if (!th) return;
        var col = th.dataset.sort;
        if (L._hostSort.col === col) { L._hostSort.dir *= -1; }
        else { L._hostSort.col = col; L._hostSort.dir = 1; }
        _drawHosts();
    });

    /* ── Processes table header click → sort (Qt6: setSortingEnabled(True)) ── */
    var procTable = $('processes-table');
    if (procTable) procTable.querySelector('thead').addEventListener('click', function(e) {
        var th = e.target.closest('th[data-sort]');
        if (!th) return;
        var col = th.dataset.sort;
        if (L._procSort.col === col) { L._procSort.dir *= -1; }
        else { L._procSort.col = col; L._procSort.dir = col === 'id' ? -1 : 1; }
        _drawProcesses();
    });

    /* ── Services table header click → sort ── */
    var svcTable = $('services-table');
    if (svcTable) svcTable.querySelector('thead').addEventListener('click', function(e) {
        var th = e.target.closest('th[data-sort]');
        if (!th) return;
        var col = th.dataset.sort;
        if (_svcSort.col === col) { _svcSort.dir *= -1; }
        else { _svcSort.col = col; _svcSort.dir = col === 'port' ? 1 : 1; }
        _drawServices();
    });

    /* ── Sort headers for right-panel tables ── */
    function _wireSort(tblId, sort, drawFn) {
        var tbl = $(tblId);
        if (tbl) tbl.querySelector('thead') && tbl.querySelector('thead').addEventListener('click', function(e) {
            var th = e.target.closest('th[data-sort]');
            if (!th) return;
            _sortClick(sort, th.dataset.sort, drawFn);
        });
    }
    _wireSort('ports-table',    _portsSort,    _drawPorts);
    _wireSort('scripts-table',  _scriptsSort,  _drawScripts);
    _wireSort('cves-table',     _cvesSort,     _drawCves);
    _wireSort('os-list-table',  _osSort,       renderOsList);
    _wireSort('os-hosts-table', _osHostsSort,  _drawOsHosts);

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
        /* Auto-select first host/process in middle pane so output shows immediately */
        var firstHostRow = $('tool-hosts-body').querySelector('tr[data-process-id]');
        if (firstHostRow) firstHostRow.click();
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
        /* G4: fetch matching hosts from server (view.py:updateOsHostsTableView) */
        var body = $('os-hosts-body');
        body.innerHTML = '<tr><td colspan="2" style="color:var(--disabled)">Loading...</td></tr>';
        fetchJson('/api/workspace/os/' + encodeURIComponent(os) + '/hosts').then(function(d) {
            _osHostsData = d.hosts || [];
            _drawOsHosts();
        }).catch(function() { body.innerHTML = ''; });
    });

    /* ── OS hosts click → load host detail ── */
    $('os-hosts-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostId) return;
        L.selectedHostId = parseInt(tr.dataset.hostId);
        $('os-hosts-body').querySelectorAll('tr').forEach(function(r) { r.classList.toggle('selected', r === tr); });
        loadHostDetail(L.selectedHostId);
        renderHosts(L.hosts); /* re-render hosts pane to show selection */
        /* Show right panel and activate Services tab */
        $('right-tabs').style.display = '';
        $('tools-display').style.display = 'none';
        var svcTab = $('right-tab-bar').querySelector('[data-tab="services-right"]');
        if (svcTab) svcTab.click();
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
        /* Auto-select first service when Services tab is clicked */
        if (tab === 'services-left-panel') {
            setTimeout(function() {
                var firstSvc = $('services-body').querySelector('tr');
                if (firstSvc && !firstSvc.classList.contains('selected')) firstSvc.click();
            }, 0);
        }
        /* Auto-select first host when Hosts tab is clicked (if none selected) */
        if (tab === 'hosts-panel' && !L.selectedHostId) {
            setTimeout(function() {
                var firstHost = $('hosts-body').querySelector('tr[data-host-id]');
                if (firstHost) firstHost.click();
            }, 0);
        }
    });

    /* ── Main tab switch → restore Scan tab state when returning to it ── */
    $('main-tab-bar').addEventListener('click', function(e) {
        var btn = e.target.closest('.tab-btn');
        if (!btn || btn.dataset.tab !== 'scan-tab') return;
        /* Ensure right panel is in correct state (not hidden by a previous Tools selection) */
        $('right-tabs').style.display = '';
        $('tools-display').style.display = 'none';
        if (L.selectedHostId) {
            /* Re-highlight selected row (in case table was re-rendered while scan-tab was hidden) */
            var row = $('hosts-body').querySelector('tr[data-host-id="' + L.selectedHostId + '"]');
            if (row) {
                $('hosts-body').querySelectorAll('tr').forEach(function(r) { r.classList.remove('selected'); });
                row.classList.add('selected');
            }
            /* Reload right panel content so it reflects current DB state */
            loadHostDetail(L.selectedHostId);
        } else if (L.hosts.length > 0) {
            /* No host was selected — auto-select first */
            setTimeout(function() {
                var firstHost = $('hosts-body').querySelector('tr[data-host-id]');
                if (firstHost) firstHost.click();
            }, 0);
        }
    });

    /* ── Process row click → show output inline (plain or xterm.js terminal) ── */
    $('processes-body').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.processId) return;
        L.selectedProcessId = parseInt(tr.dataset.processId);
        $('processes-body').querySelectorAll('tr').forEach(function(r) {
            r.classList.toggle('selected', r === tr);
        });

        /* Check if this is an Interactive process with a terminal session */
        var proc = L.processes.find(function(p) { return String(p.id) === tr.dataset.processId; });
        var sessionId = proc ? proc.session_id : null;

        if (sessionId && proc.status === 'Interactive') {
            /* ── Interactive process → show xterm.js terminal ── */
            _showTerminalOutput(sessionId);
            /* No procPollTimer needed — the terminal polls its own output */
            if (L.procPollTimer) { clearInterval(L.procPollTimer); L.procPollTimer = null; }
        } else {
            /* ── Regular process → show plain text output ── */
            _showPlainOutput();
            loadProcessOutput(tr.dataset.processId, $('plain-output'));
            /* Auto-poll output — keep running through Waiting→Running transition. */
            if (L.procPollTimer) clearInterval(L.procPollTimer);
            L.procPollTimer = setInterval(function() {
                var proc = L.processes.find(function(p) { return parseInt(p.id) === L.selectedProcessId; });
                if (!proc) { clearInterval(L.procPollTimer); L.procPollTimer = null; return; }
                if (proc.status === 'Running') {
                    loadProcessOutput(L.selectedProcessId, $('plain-output'));
                } else if (proc.status !== 'Waiting') {
                    loadProcessOutput(L.selectedProcessId, $('plain-output'));
                    clearInterval(L.procPollTimer); L.procPollTimer = null;
                }
            }, 2000);
        }
    });

    /* ── Process status filter ── */
    var pf = $('process-status-filter');
    if (pf) pf.addEventListener('change', function() { renderProcesses(L.processes); });

    /* ── Script click → show output ── */
    $('host-detail-scripts').addEventListener('click', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.scriptId) return;
        $('host-detail-scripts').querySelectorAll('tr').forEach(function(r) { r.classList.toggle('selected', r === tr); });
        var sid = tr.dataset.scriptId;
        var outEl = $('script-output-inline');
        if (sid && outEl) {
            outEl.textContent = 'Loading...';
            fetchJson('/api/workspace/scripts/' + sid + '/output').then(function(d) {
                outEl.innerHTML = ansiToHtml(d.output || '');
            }).catch(function() {
                outEl.textContent = 'Error loading script output';
            });
        }
    });

    /* ── Dynamic tab click → reload output; auto-poll if process is Running ── */
    var _dynPollTimer = null;
    var _dynPollProcId = null;
    function _stopDynPoll() {
        if (_dynPollTimer) { clearInterval(_dynPollTimer); _dynPollTimer = null; }
        _dynPollProcId = null;
    }
    function _startDynPoll(procId, outputEl) {
        _stopDynPoll();
        _dynPollProcId = procId;
        _dynPollTimer = setInterval(function() {
            var proc = L.processes.find(function(p) { return String(p.id) === String(_dynPollProcId); });
            if (!proc) { _stopDynPoll(); return; }
            if (proc.status === 'Running') {
                loadProcessOutput(_dynPollProcId, outputEl);
            } else if (proc.status !== 'Waiting') {
                /* Finished — final load then stop */
                loadProcessOutput(_dynPollProcId, outputEl);
                _stopDynPoll();
            }
            /* Waiting: keep polling until process starts */
        }, 2000);
    }
    /* ── Information tab click → fire queued field animations (Qt6: onTabViewed) ── */
    $('right-tab-bar').addEventListener('click', function(e) {
        var infoBtn = e.target.closest('[data-tab="info-right"]');
        if (infoBtn) {
            setTimeout(function() {  /* wait for panel to become visible */
                var hostKey = L.selectedHostIp || 'unknown';
                var pending = _pendingInfoAnimations[hostKey];
                if (pending && pending.length) {
                    _pendingInfoAnimations[hostKey] = [];
                    _applyInfoAnimation(pending);
                }
            }, 60);
        }
    });

    /* ── Dynamic tab close-x (Qt6: closeHostToolTab / _closeProcessTab) ── */
    $('right-tab-bar').addEventListener('click', function(e) {
        var x = e.target.closest('.close-x');
        if (!x) return;
        e.stopPropagation();  /* don't activate the tab */
        var btn = x.closest('.dynamic-tab');
        if (!btn) return;
        var tabId = btn.dataset.tab;
        var procId = tabId ? tabId.replace('dyntab-', '') : null;
        if (!procId) return;

        var proc = L.processes.find(function(p) { return String(p.id) === String(procId); });
        var status = proc ? proc.status : '';

        function doClose() {
            _stopDynPoll();
            postJson('/api/processes/' + procId + '/close', {}).then(function() {
                /* Remove button and panel from DOM */
                var panel = $(tabId);
                btn.remove();
                if (panel) panel.remove();
                /* Activate the Notes tab (last static tab) so something is shown */
                var fallback = $('right-tab-bar').querySelector('[data-tab="notes-right"]');
                if (fallback) fallback.click();
                pollSnapshot();
            });
        }

        if (status === 'Running') {
            if (confirm('This process is still running. Kill it and close the tab?')) {
                postJson('/api/processes/' + procId + '/kill', {}).then(function() {
                    setTimeout(doClose, 300);
                });
            }
        } else if (status === 'Waiting') {
            if (confirm('This process is queued. Cancel and close the tab?')) {
                postJson('/api/processes/' + procId + '/kill', {}).then(function() {
                    setTimeout(doClose, 300);
                });
            }
        } else {
            doClose();
        }
    });

    /* ── Dynamic tab click → reload output; auto-poll if process is Running ── */
    $('right-tab-bar').addEventListener('click', function(e) {
        if (e.target.closest('.close-x')) return;  /* handled above */
        var btn = e.target.closest('.dynamic-tab');
        if (!btn) return;
        _stopDynPoll();
        _stopDynTerminal();
        var tabId = btn.dataset.tab;
        if (!tabId) return;
        var procId = tabId.replace('dyntab-', '');
        var outputEl = $('dyn-output-' + procId);
        if (!outputEl) return;

        /* Check if this is an Interactive process with a terminal session */
        var proc = L.processes.find(function(p) { return String(p.id) === String(procId); });
        var sessionId = proc ? proc.session_id : null;

        if (sessionId && proc.status === 'Interactive') {
            /* Mount xterm.js in the dynamic tab output area */
            _connectDynTerminal(sessionId, outputEl);
        } else {
            outputEl.textContent = 'Loading...';
            loadProcessOutput(procId, outputEl);
            /* Auto-refresh while Running or Waiting (survives Waiting→Running transition) */
            if (proc && (proc.status === 'Running' || proc.status === 'Waiting')) {
                _startDynPoll(procId, outputEl);
            }
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
            /* Store keywords in L._filters then re-render via _drawHosts */
            var q = (filterInput.value || '').trim();
            L._filters.keywords = q ? q.split(/\s+/) : [];
            _drawHosts();
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
        /* Show tabTitle in port column if port is empty (e.g. staged nmap shows stage info) */
        var portCol = p.port || p.tabTitle || '';
        var statusClass = p.status === 'Running' ? 'proc-running' : p.status === 'Finished' ? '' : 'proc-crashed';
        tr.innerHTML = '<td>' + esc(p.hostIp||'') + '</td>' +
                       '<td>' + esc(portCol) + '</td>' +
                       '<td class="' + statusClass + '">' + esc(p.status||'') + '</td>';
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

        /* ── Dynamic right-panel refresh (Qt6: signal-driven, Flask: poll-driven) ──
           Three triggers that reload the right panel without requiring a host click:
           1. Process set for selected host changes (start/finish) → immediate reload
           2. Any scan is running → periodic reload every ~6s (catches nmap XML imports)
           3. OS tab active → re-render OS list from latest snapshot classified groups */

        if (L.selectedHostIp) {
            /* Trigger 1: processes for the exact selected host IP changed */
            var sig = (snap.processes || [])
                .filter(function(p) { return p.hostIp === L.selectedHostIp; })
                .map(function(p) { return p.id + ':' + p.status; })
                .sort().join(',');
            if (sig !== L._hostProcSig) {
                L._hostProcSig = sig;
                renderDynamicToolTabs(L.selectedHostIp);
                if (L.selectedHostId && $('tools-display').style.display !== 'flex') {
                    loadHostDetail(L.selectedHostId);
                }
            }
        }

        /* Trigger 2: any nmap process changed status (stage completions).
           _hostProcSig misses staged nmap because its hostIp = scan target
           (e.g. "192.168.85.0/24") not the discovered host IP. This catches
           stage finishes and imports that add new ports/OS/scripts to the DB. */
        if (L.selectedHostId) {
            var nmapSig = (snap.processes || [])
                .filter(function(p) { return p.name === 'nmap'; })
                .map(function(p) { return p.id + ':' + p.status; })
                .sort().join(',');
            if (nmapSig !== L._nmapSig) {
                L._nmapSig = nmapSig;
                if ($('tools-display').style.display !== 'flex') {
                    loadHostDetail(L.selectedHostId);
                }
            }
        }

        /* Periodic right-panel refresh while scans are running (nmap imports ports
           without changing process status, so _hostProcSig alone misses those) */
        var anyRunning = ((snap.summary || {}).running_processes || 0) > 0;
        L._pollCount = (L._pollCount || 0) + 1;
        if (L.selectedHostId && anyRunning && L._pollCount % 4 === 0) {
            /* Every ~6s — reload right-panel tabs unconditionally while any process runs.
               Root cause of #30: during nmap stage 2 (2-3 min), _nmapSig and _hostProcSig
               never change (nmap stays "Running"), so loadHostDetail is NEVER triggered
               from those paths. With dynActive guard, the periodic refresh was also blocked
               when the user watched the stage 2 output tab → complete UI freeze.
               renderDynamicToolTabs already restores the active dynamic tab, so removing
               the dynActive guard is safe — no permanent blank screen. */
            if ($('tools-display').style.display !== 'flex') {
                loadHostDetail(L.selectedHostId);
            }
        }

        /* Keep OS list current when OS tab is active */
        var osPanel = $('os-panel');
        if (osPanel && osPanel.classList.contains('active')) renderOsList();

        /* Ctrl+C in terminal — server sets exit_requested flag; show save dialog here.
           NOTE: _exitFlow is defined inside DOMContentLoaded so it is not in this
           scope — access it via L._exitFlow which is set once DOMContentLoaded runs. */
        if ((snap.project || {}).exit_requested && !L._exitDialogShown) {
            L._exitDialogShown = true;
            if (typeof L._exitFlow === 'function') L._exitFlow();
        }
        if (!(snap.project || {}).exit_requested) {
            L._exitDialogShown = false;   /* reset if server cancelled */
        }
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
    /* Column resize + width persistence (Qt6: saveColumnWidths/restoreColumnWidths) */
    initColResizers('hosts-table');
    initColResizers('processes-table');
    initColResizers('services-table');
    initInteractions();

    /* ── Dynamic-tab selection lock ──────────────────────────────────────────
       _dynSelLocked gates ALL DOM mutations in #dynamic-tabs-container.
       mousedown: lock immediately so the very first rebuild attempt after
         the button-press is already blocked (selectionchange is async and
         would be too late to prevent a mid-drag corruption).
       selectionchange: keep locked while selection exists; clear when gone.
       This combination covers: drag in progress, completed selection while
       tool is running, and the mid-drag page-top artefact. */
    var _dynContainer = $('dynamic-tabs-container');
    if (_dynContainer) {
        _dynContainer.addEventListener('mousedown', function() {
            _dynSelLocked = true;
        });
    }
    document.addEventListener('selectionchange', function() {
        try {
            var _sc = $('dynamic-tabs-container');
            if (!_sc) return;
            var _ss = window.getSelection();
            if (_ss && _ss.toString() && _ss.rangeCount > 0) {
                var _sr = _ss.getRangeAt(0);
                _dynSelLocked = _sc.contains(_sr.startContainer) ||
                                _sc.contains(_sr.endContainer);
            } else {
                _dynSelLocked = false;
            }
        } catch(e) { _dynSelLocked = false; }
    });

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

    /* Start polling every 1.5 seconds */
    L.pollTimer = setInterval(pollSnapshot, 1500);

    /* ════════════════════════════════════════════════
       MODAL WIRING — connect menu buttons to dialogs
       (openModal/closeModal defined at global scope above)
       ════════════════════════════════════════════════ */

    /* ── Add Hosts ── */
    var addHostsBtn = $('action-add-hosts');
    if (addHostsBtn) addHostsBtn.addEventListener('click', function() { openModal('add-hosts-modal'); });
    var addOverlay = $('add-hosts-overlay');
    if (addOverlay) addOverlay.addEventListener('click', function() { openModal('add-hosts-modal'); });
    var filterAdd = $('filter-add-host');
    if (filterAdd) filterAdd.addEventListener('click', function() { openModal('add-hosts-modal'); });

    var addClose = $('add-hosts-close');
    if (addClose) addClose.addEventListener('click', function() { closeModal('add-hosts-modal'); });
    var addCancel = $('add-hosts-cancel');
    if (addCancel) addCancel.addEventListener('click', function() { closeModal('add-hosts-modal'); });

    /* Easy/Hard mode toggle (matches addHostDialog.py:329-336) */
    var modeEasy = $('add-hosts-mode-easy');
    var modeHard = $('add-hosts-mode-hard');
    function updateModeGroups() {
        var isHard = modeHard && modeHard.checked;
        var easyGrp = $('add-hosts-easy-group');
        var portGrp = $('add-hosts-portscan-group');
        var pingGrp = $('add-hosts-ping-group');
        var custGrp = $('add-hosts-custom-group');
        if (easyGrp) { easyGrp.style.opacity = isHard ? '0.4' : '1'; easyGrp.style.pointerEvents = isHard ? 'none' : ''; }
        if (portGrp) { portGrp.style.opacity = isHard ? '1' : '0.4'; portGrp.style.pointerEvents = isHard ? '' : 'none'; }
        if (pingGrp) { pingGrp.style.opacity = isHard ? '1' : '0.4'; pingGrp.style.pointerEvents = isHard ? '' : 'none'; }
        if (custGrp) { custGrp.style.opacity = isHard ? '1' : '0.4'; custGrp.style.pointerEvents = isHard ? '' : 'none'; }
    }
    if (modeEasy) modeEasy.addEventListener('change', updateModeGroups);
    if (modeHard) modeHard.addEventListener('change', updateModeGroups);

    /* Submit — matches view.py:callAddHosts (lines 1075-1133) */
    var addStart = $('add-hosts-start');
    if (addStart) addStart.addEventListener('click', function() {
        var targets = ($('add-hosts-targets') || {}).value || '';
        targets = targets.trim();
        if (!targets) {
            var v = $('add-hosts-validation');
            if (v) v.style.display = '';
            return;
        }
        var v2 = $('add-hosts-validation');
        if (v2) v2.style.display = 'none';

        var isHard = modeHard && modeHard.checked;
        var scanMode = isHard ? 'Hard' : 'Easy';
        var discovery = ($('add-hosts-discovery') || {}).checked;
        var staged = ($('add-hosts-staged') || {}).checked;
        var timing = ($('add-hosts-timing') || {}).value || '4';
        var resolve = ($('add-hosts-resolve') || {}).checked;
        var ipv6 = ($('add-hosts-ipv6') || {}).checked;

        /* Build nmap options (matches view.py:1091-1118) */
        var nmapOptions = [];
        if (isHard) {
            var scanOpt = document.querySelector('input[name="add-hosts-scanopt"]:checked');
            if (scanOpt) nmapOptions.push(scanOpt.value);
            var pingOpt = document.querySelector('input[name="add-hosts-pingopt"]:checked');
            if (pingOpt) nmapOptions.push(pingOpt.value);
            if (($('add-hosts-fragment') || {}).checked) nmapOptions.push('-f');
            var custom = ($('add-hosts-custom') || {}).value || '';
            if (custom.trim()) nmapOptions.push(custom.trim());
        }
        nmapOptions = nmapOptions.filter(function(o) { return o !== '-n' && o !== '-R'; });
        nmapOptions.push(resolve ? '-R' : '-n');

        setText('add-hosts-status', 'Starting scan...');
        addStart.disabled = true;

        postJson('/api/nmap/scan', {
            targets: targets,
            scan_mode: scanMode,
            discovery: discovery,
            staged: staged,
            timing: timing,
            nmap_options: nmapOptions,
            enable_ipv6: ipv6
        }).then(function(data) {
            setText('add-hosts-status', 'Scan started!');
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
        editors.querySelectorAll('.cfg-editor-wrap').forEach(function(w) { w.remove(); });

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
                editors.querySelectorAll('.cfg-editor-wrap').forEach(function(w) {
                    w.style.display = w.dataset.profile === p.name ? '' : 'none';
                });
            });
            tabBar.appendChild(btn);

            /* Editor wrapper + textarea + highlight overlay */
            var visible = p.name === (cfgState.selectedTab || cfgState.active);
            var wrap = document.createElement('div');
            wrap.className = 'cfg-editor-wrap';
            wrap.dataset.profile = p.name;
            wrap.style.display = visible ? '' : 'none';

            var ta = document.createElement('textarea');
            ta.dataset.profile = p.name;
            ta.value = p.text || '';
            ta.spellcheck = false;
            ta.style.cssText = 'width:100%;min-height:400px;background:var(--base);color:var(--text);font:inherit;border:1px solid var(--border);padding:6px;resize:vertical;box-sizing:border-box';

            var overlay = document.createElement('div');
            overlay.className = 'cfg-find-overlay';
            overlay.setAttribute('aria-hidden', 'true');
            /* Keep overlay scroll in sync when user scrolls the textarea */
            ta.addEventListener('scroll', function() { overlay.scrollTop = ta.scrollTop; });

            wrap.appendChild(ta);
            wrap.appendChild(overlay);
            editors.appendChild(wrap);

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

    /* ── Config Manager Find/Search (Ctrl+F, backlog #4) ── */
    var cfgFind = { matches: [], current: -1, query: '' };

    function cfgFindGetTA() {
        var name = cfgGetCurrentName();
        return document.querySelector('#config-editors textarea[data-profile="' + name + '"]');
    }

    function cfgFindRun(query) {
        cfgFind.query = query;
        cfgFind.matches = [];
        cfgFind.current = -1;
        var ta = cfgFindGetTA();
        if (!ta || !query) {
            setText('cfg-find-count', query ? '0 matches' : '');
            cfgFindClearHighlight();
            return;
        }
        var text = ta.value.toLowerCase();
        var q = query.toLowerCase();
        var idx = 0;
        while ((idx = text.indexOf(q, idx)) !== -1) {
            cfgFind.matches.push(idx);
            idx += q.length || 1;
        }
        if (cfgFind.matches.length) {
            cfgFind.current = 0;
            cfgFindSelect(0);
        } else {
            setText('cfg-find-count', '0 matches');
            cfgFindClearHighlight();
        }
    }

    function cfgFindEsc(s) {
        return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    function cfgFindHighlight(ta, start, end) {
        var overlay = ta.parentNode && ta.parentNode.querySelector('.cfg-find-overlay');
        if (!overlay) return;
        var text = ta.value;
        overlay.innerHTML = cfgFindEsc(text.substring(0, start)) +
            '<mark>' + cfgFindEsc(text.substring(start, end)) + '</mark>' +
            cfgFindEsc(text.substring(end));
        /* Use mark.offsetTop to scroll reliably — overlay must be overflow:auto */
        var mark = overlay.querySelector('mark');
        if (mark) {
            overlay.scrollTop = Math.max(0, mark.offsetTop - overlay.clientHeight / 2);
            ta.scrollTop = overlay.scrollTop;
        }
    }

    function cfgFindClearHighlight() {
        document.querySelectorAll('#config-editors .cfg-find-overlay').forEach(function(o) {
            o.innerHTML = '';
        });
    }

    function cfgFindSelect(i) {
        var ta = cfgFindGetTA();
        if (!ta || i < 0 || i >= cfgFind.matches.length) return;
        var start = cfgFind.matches[i];
        var end   = start + cfgFind.query.length;
        /* cfgFindHighlight scrolls both overlay and textarea via mark.offsetTop */
        cfgFindHighlight(ta, start, end);
        setText('cfg-find-count', (i + 1) + ' / ' + cfgFind.matches.length);
    }

    function cfgFindNext() {
        if (!cfgFind.matches.length) return;
        cfgFind.current = (cfgFind.current + 1) % cfgFind.matches.length;
        cfgFindSelect(cfgFind.current);
    }

    function cfgFindPrev() {
        if (!cfgFind.matches.length) return;
        cfgFind.current = (cfgFind.current - 1 + cfgFind.matches.length) % cfgFind.matches.length;
        cfgFindSelect(cfgFind.current);
    }

    function cfgFindShow() {
        var bar = $('cfg-find-bar');
        if (bar) bar.style.display = '';
        var inp = $('cfg-find-input');
        if (inp) { inp.focus(); inp.select(); }
        /* Re-run with current query so results appear immediately */
        if (cfgFind.query) cfgFindRun(cfgFind.query);
    }

    function cfgFindHide() {
        var bar = $('cfg-find-bar');
        if (bar) bar.style.display = 'none';
        cfgFind.matches = []; cfgFind.current = -1; cfgFind.query = '';
        setText('cfg-find-count', '');
        var inp = $('cfg-find-input');
        if (inp) inp.value = '';
        cfgFindClearHighlight();
        var ta = cfgFindGetTA();
        if (ta) ta.focus();
    }

    var cfgFindInp = $('cfg-find-input');
    if (cfgFindInp) {
        cfgFindInp.addEventListener('input', function() { cfgFindRun(this.value); });
        cfgFindInp.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowDown' || (e.key === 'Enter' && !e.shiftKey))  { e.preventDefault(); cfgFindNext(); }
            else if (e.key === 'ArrowUp' || (e.key === 'Enter' && e.shiftKey)) { e.preventDefault(); cfgFindPrev(); }
            else if (e.key === 'Escape') { cfgFindHide(); }
        });
    }
    var cfgFPrev = $('cfg-find-prev');
    if (cfgFPrev) cfgFPrev.addEventListener('click', cfgFindPrev);
    var cfgFNext = $('cfg-find-next');
    if (cfgFNext) cfgFNext.addEventListener('click', cfgFindNext);
    var cfgFClose = $('cfg-find-close');
    if (cfgFClose) cfgFClose.addEventListener('click', cfgFindHide);

    /* Re-run find when profile tab switches while bar is open */
    document.addEventListener('click', function(e) {
        var btn = e.target.closest && e.target.closest('#config-tab-bar .tab-btn');
        if (btn && cfgFind.query) {
            setTimeout(function() { cfgFindRun(cfgFind.query); }, 0);
        }
    });

    var configBtn = $('action-config');
    if (configBtn) configBtn.addEventListener('click', function() {
        openModal('config-modal');
        cfgLoadProfiles();
    });
    var configClose = $('config-close');
    if (configClose) configClose.addEventListener('click', function() {
        cfgFindHide();
        closeModal('config-modal');
    });

    /* Save */
    /* ── Settings live-apply: re-fetch brute defaults + ui-prefs after any config save/activate ──
       Keeps the running UI in sync without requiring a page reload. */
    function reapplyLiveSettings() {
        /* Re-fetch brute defaults — update service lists and re-run hide/show */
        fetch('/api/brute/defaults').then(function(r){ return r.json(); }).then(function(d) {
            L._bruteNoUserSvcs = (d.no_username_services || []).map(function(s){ return s.toLowerCase(); });
            L._bruteNoPassSvcs = (d.no_password_services || []).map(function(s){ return s.toLowerCase(); });
            bruteHideShowFields(($('brute-service')||{}).value||'');
        }).catch(function(){});
        /* Re-fetch UI prefs — re-apply tool-output-black-background */
        fetch('/api/settings/ui-prefs').then(function(r){ return r.json(); }).then(function(d) {
            if (d.tool_output_black_background) {
                document.body.classList.add('black-output-bg');
            } else {
                document.body.classList.remove('black-output-bg');
            }
        }).catch(function(){});
    }

    var configSave = $('config-save');
    if (configSave) configSave.addEventListener('click', function() {
        var name = cfgGetCurrentName();
        postJson('/api/config/profiles/' + encodeURIComponent(name) + '/save', { text: cfgGetCurrentText() })
        .then(function(d) {
            if (d && d.errors && d.errors.length > 0) {
                /* Validation errors — show them (mirrors Qt6 showScrollableErrorDialog) */
                setText('config-status', '❌ ' + d.errors.length + ' syntax error(s) — not saved');
                alert('Cannot save — ' + d.errors.length + ' syntax error(s):\n\n' + d.errors.join('\n\n'));
            } else {
                setText('config-status', d.applied ? '✓ Saved & applied ' + name : '✓ Saved ' + name);
                if (d.applied) reapplyLiveSettings();
            }
        })
        .catch(function(err) {
            /* HTTP 400 response includes errors array */
            var msg = err.message || 'Save failed';
            setText('config-status', '❌ ' + msg);
            if (err.errors && err.errors.length > 0) {
                alert('Cannot save — syntax errors:\n\n' + err.errors.join('\n\n'));
            }
        });
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
            reapplyLiveSettings();
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

    /* ── Notes display/edit toggle ── */
    var notesDisp = $('notes-display');
    var notesTa   = $('notes-text');
    /* Click display div → switch to textarea for editing */
    /* Double-click to edit: single click just navigates/reads the notes.
       Previously single-click switched to the textarea which showed raw
       ANSI escape codes (\x1b[32m...) — a jarring visual transition.
       Double-click is the intentional "I want to edit" gesture. */
    if (notesDisp) notesDisp.addEventListener('dblclick', function() {
        _showNotesEdit(notesTa ? notesTa.value : notesDisp.innerText);
    });
    /* Textarea blur → save to the host that was being edited (_noteHostId),
       NOT L.selectedHostId which may already point to a newly-clicked host. */
    if (notesTa) notesTa.addEventListener('blur', function() {
        _notesEditMode = false;   /* leave edit mode before calling _showNotesDisplay */
        var saveId = _noteHostId || L.selectedHostId;
        _noteHostId = null;
        if (!saveId) { _showNotesDisplay(notesTa.value); return; }
        postJson('/api/workspace/hosts/' + saveId + '/note', { note: notesTa.value });
        _showNotesDisplay(notesTa.value);
    });

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
                setText('window-title', _VERSION + ' – ' + path.split('/').pop());
                /* Suppress the first auto-selected host from overwriting the
                   project name in the title. Cleared by loadHostDetail after
                   the first auto-select fires, so subsequent user clicks work. */
                L._suppressTitleUpdate = true;
                L.selectedHostId = null;
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
            .then(function() { setText('window-title', _VERSION + ' – ' + path.split('/').pop()); })
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
            .then(function() { setText('window-title', _VERSION + ' – ' + path.split('/').pop()); })
            .catch(function(err) { alert('Save As failed: ' + err.message); });
        });
    });

    /* ── File → Import hosts from file (Qt6: --input-file / cli_utils) ── */
    var importFileBtn = $('action-import-file');
    if (importFileBtn) importFileBtn.addEventListener('click', function() {
        fbOpen('Import Hosts from File', '.txt', 'open', '/root').then(function(path) {
            if (!path) return;
            postJson('/api/workspace/hosts/import-file', { path: path })
            .then(function(d) {
                var n = d.added !== undefined ? d.added : '?';
                alert('Imported ' + n + ' host(s) from file.');
                pollSnapshot();
            })
            .catch(function(err) { alert('Import failed: ' + err.message); });
        });
    });

    /* ── File → Run Nmap Scan (upstream nmap-scan-modal) ── */
    var nmapScanBtn = $('action-nmap-scan');
    if (nmapScanBtn) nmapScanBtn.addEventListener('click', function() {
        openModal('nmap-scan-modal');
    });

    /* ── File → Manual Tool Run (upstream manual-scan-modal) ── */
    var manualToolBtn = $('action-manual-tool');
    if (manualToolBtn) manualToolBtn.addEventListener('click', function() {
        openModal('manual-scan-modal');
    });

    /* ── File → Exit — prompt to save if project is unsaved ── */
    function _doExit() {
        /* Tell the server to clean up and stop, then try to close the tab.
           window.close() only works when the tab was opened by script (window.open).
           If it is blocked we show an alert so the user knows the server is stopped. */
        function _afterShutdown() {
            window.close();
            setTimeout(function() {
                if (!window.closed) {
                    alert('The Legion server has been stopped.\nPlease close this browser tab manually.');
                }
            }, 300);
        }
        L._exitDialogShown = false;
        fetch('/api/exit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})
            .then(_afterShutdown)
            .catch(_afterShutdown);   /* server already stopping — still close/alert */
    }

    function _exitFlow() {
        var hasData = L.hosts && L.hosts.length > 0;
        if (hasData) {
            openModal('save-on-exit-modal');
        } else {
            _doExit();
        }
    }
    /* Expose on L so pollSnapshot() (top-level scope) can call it */
    L._exitFlow = _exitFlow;

    var exitBtn = $('action-exit');
    if (exitBtn) exitBtn.addEventListener('click', _exitFlow);

    /* Save-on-exit modal button handlers */
    var exitSaveBtn   = $('exit-save-btn');
    var exitNosaveBtn = $('exit-nosave-btn');
    var exitCancelBtn = $('exit-cancel-btn');

    if (exitSaveBtn) exitSaveBtn.addEventListener('click', function() {
        closeModal('save-on-exit-modal');
        fbOpen('Save Project', '.legion', 'save', '/root').then(function(path) {
            if (!path) return;   /* user cancelled file browser — don't exit */
            if (!path.endsWith('.legion')) path += '.legion';
            postJson('/api/project/save-as', { path: path })
                .then(function() {
                    setText('window-title', _VERSION + ' \u2013 ' + path.split('/').pop());
                    _doExit();
                })
                .catch(function(err) { alert('Save failed: ' + err.message); });
        });
    });

    if (exitNosaveBtn) exitNosaveBtn.addEventListener('click', function() {
        closeModal('save-on-exit-modal');
        _doExit();
    });

    if (exitCancelBtn) exitCancelBtn.addEventListener('click', function() {
        closeModal('save-on-exit-modal');
        /* If exit was triggered by Ctrl+C in terminal, tell server to cancel it */
        fetch('/api/cancel-exit', {method:'POST'}).catch(function(){});
    });

    /* ── Help ── */
    var helpBtn = $('action-help');
    if (helpBtn) helpBtn.addEventListener('click', function() {
        alert(_VERSION + '\\nNetwork penetration testing framework\\n\\nHelp: F2 for Config Manager\\nCtrl+H to add hosts');
    });

    /* ── xterm buffer → ANSI string ─────────────────────────────────────────────
       xterm.getSelection() returns plain text — all colour information is
       stripped at the API level.  This function walks the buffer cell-by-cell
       over the selected range and reconstructs ANSI escape sequences from the
       stored fg-colour mode and colour value of each character cell.
       Falls back to plain getSelection() if the buffer API is unavailable.
       Handles both xterm.js 5.x naming (startRow/startColumn) and older
       naming (start.x / start.y) defensively. */
    function xtermSelectionToAnsi(xterm) {
        if (!xterm) return '';
        var pos;
        try { pos = xterm.getSelectionPosition(); } catch(e) {}
        if (!pos) return xterm.getSelection() || '';

        /* Normalise field names across xterm.js versions */
        var startRow = pos.startRow !== undefined ? pos.startRow
                     : (pos.start   !== undefined ? pos.start.y : undefined);
        var startCol = pos.startColumn !== undefined ? pos.startColumn
                     : (pos.start      !== undefined ? pos.start.x : undefined);
        var endRow   = pos.endRow !== undefined ? pos.endRow
                     : (pos.end   !== undefined ? pos.end.y : undefined);
        var endCol   = pos.endColumn !== undefined ? pos.endColumn
                     : (pos.end      !== undefined ? pos.end.x : undefined);
        if (startRow === undefined) return xterm.getSelection() || '';

        /* Wrap buffer access in try/catch — an unhandled exception here would
           propagate through sendSelectionToNotes (no outer try/catch) and abort
           before the DOM-selection branch, so nothing would be copied at all. */
        try {
        var buf = xterm.buffer.active;
        var result = '';
        var prevEsc = '';   /* last escape written — skip if unchanged */

        for (var row = startRow; row <= endRow; row++) {
            var line = buf.getLine(row);
            if (!line) { if (row < endRow) result += '\n'; continue; }

            var colFrom = (row === startRow) ? startCol : 0;
            var colTo   = (row === endRow)   ? endCol   : line.length;

            for (var col = colFrom; col < colTo; col++) {
                var cell = line.getCell(col);
                if (!cell) continue;
                var ch = cell.getChars();
                if (!ch) continue;

                /* Reconstruct fg colour escape for this cell.
                   mode 0 = default, 1 = 16-colour ANSI, 2 = 256-colour, 3 = RGB */
                var esc = '';
                var mode  = cell.getFgColorMode();
                var color = cell.getFgColor();
                /* getFgColorMode() returns the raw xterm.js bitmask constant,
                   not normalized 0/1/2/3 as the docs imply.
                   CM_P16=0x1000000, CM_P256=0x2000000, CM_RGB=0x3000000 */
                if      (mode === 0x1000000 && color < 8)  esc = '\x1b[3' + color + 'm';
                else if (mode === 0x1000000)               esc = '\x1b[9' + (color - 8) + 'm';
                else if (mode === 0x2000000)               esc = '\x1b[38;5;' + color + 'm';
                else if (mode === 0x3000000) {
                    var r = (color >> 16) & 0xff;
                    var g = (color >> 8)  & 0xff;
                    var b =  color        & 0xff;
                    esc = '\x1b[38;2;' + r + ';' + g + ';' + b + 'm';
                }
                if (cell.isBold()) esc = '\x1b[1m' + esc;
                if (cell.isDim())  esc = '\x1b[2m' + esc;

                if (esc !== prevEsc) {
                    result += esc || '\x1b[0m';
                    prevEsc = esc;
                }
                result += ch;
            }
            if (row < endRow) {
                if (prevEsc) { result += '\x1b[0m'; prevEsc = ''; }
                result += '\n';
            }
        }
        if (prevEsc) result += '\x1b[0m';
        return result || (xterm.getSelection() || '');
        } catch(e) { return xterm.getSelection() || ''; }
    }

    /* ── DOM selection → ANSI string ────────────────────────────────────────────
       Browser getSelection().toString() strips HTML tags and returns plain text.
       For output areas rendered with ansi-fg-* spans, we can reconstruct the
       ANSI codes by walking the cloned selection fragment and reading class names.
       Returns plain text (no escapes) for uncoloured spans. */
    var _ansiClassMap = {
        'ansi-fg-black':30, 'ansi-fg-red':31, 'ansi-fg-green':32, 'ansi-fg-yellow':33,
        'ansi-fg-blue':34, 'ansi-fg-magenta':35, 'ansi-fg-cyan':36, 'ansi-fg-white':37,
        'ansi-fg-bright-black':90, 'ansi-fg-bright-red':91, 'ansi-fg-bright-green':92,
        'ansi-fg-bright-yellow':93, 'ansi-fg-bright-blue':94, 'ansi-fg-bright-magenta':95,
        'ansi-fg-bright-cyan':96, 'ansi-fg-bright-white':97
    };

    /* ── DOM selection → ANSI string ──────────────────────────────────────────
       Walks every text node that is a descendant of the selection's common
       ancestor, checking whether it falls within the selection range and
       climbing its parent chain to reconstruct ansi-fg-* ANSI escape codes.
       Uses a simple recursive walk instead of TreeWalker+compareBoundaryPoints
       to avoid browser-specific issues with those APIs inside event handlers. */
    function domSelectionToAnsi() {
        var sel = window.getSelection();
        if (!sel || !sel.rangeCount || !sel.toString()) return '';

        /* Local colour map (not a closure reference) so it's always reachable
           from inside dispatched-event callbacks regardless of scope quirks. */
        var am = {
            'ansi-fg-black':30,'ansi-fg-red':31,'ansi-fg-green':32,'ansi-fg-yellow':33,
            'ansi-fg-blue':34,'ansi-fg-magenta':35,'ansi-fg-cyan':36,'ansi-fg-white':37,
            'ansi-fg-bright-black':90,'ansi-fg-bright-red':91,'ansi-fg-bright-green':92,
            'ansi-fg-bright-yellow':93,'ansi-fg-bright-blue':94,'ansi-fg-bright-magenta':95,
            'ansi-fg-bright-cyan':96,'ansi-fg-bright-white':97
        };

        var range  = sel.getRangeAt(0);
        var result = [];

        try {
            var root = range.commonAncestorContainer;
            if (root.nodeType === 3) root = root.parentElement;

            /* Recursive walk — no TreeWalker, no compareBoundaryPoints.
               For text nodes we use startOffset/endOffset when the node is
               a range boundary; otherwise we take the full text.  All text
               nodes that are descendants of root are visited; ones outside
               the selection produce empty text (substring 0→0 or len→len)
               and are silently skipped by the `if (!txt)` guard. */
            function walk(node) {
                if (node.nodeType === 3) {
                    var off0 = (node === range.startContainer) ? range.startOffset : 0;
                    var off1 = (node === range.endContainer)   ? range.endOffset   : node.length;
                    var txt  = node.textContent.substring(off0, off1);
                    if (!txt) return;

                    /* Climb parent chain to find the nearest colour class */
                    var esc = '', bold = false, p = node.parentElement;
                    while (p && p !== root) {
                        var cls = (p.className || '').split(' ');
                        for (var i = 0; i < cls.length; i++) {
                            var code = am[cls[i]];
                            if (code) { esc = '\x1b[' + code + 'm'; break; }
                            if (cls[i] === 'ansi-bold') bold = true;
                        }
                        if (esc) break;
                        p = p.parentElement;
                    }
                    if (bold) esc = '\x1b[1m' + esc;
                    result.push(esc ? esc + txt + '\x1b[0m' : txt);

                } else if (node.nodeType === 1) {
                    for (var j = 0; j < node.childNodes.length; j++) {
                        walk(node.childNodes[j]);
                    }
                }
            }

            for (var k = 0; k < root.childNodes.length; k++) {
                walk(root.childNodes[k]);
            }
        } catch(e) { return sel.toString(); }

        return result.join('') || sel.toString();
    }

    /* ── Ctrl+B / Send selection to notes (Qt6: view.py:sendSelectionToNotes) ──
       Gets selected text + title from active output area, APPENDS to notes with
       an orange header "=== Selection from {title} ===", flashes source orange,
       activates Notes tab. Matches Qt6 behavior exactly.
       xterm.js terminals use their own selection API (not window.getSelection),
       so we check both terminal states before falling back to browser selection. */
    function sendSelectionToNotes() {
        if (!L.selectedHostId) return;

        var text = '';
        var title = 'Output';
        var sourceEl = null;

        /* ── 1 & 2. Xterm selection (lower or upper panel) ──────────────────
           _savedXtermSel was captured in the capture-phase listener BEFORE
           xterm's element-level keydown handler cleared the selection.
           We use it here (bubble phase) when it is available. */
        if (!text && _savedXtermSel) {
            text = _savedXtermSel;
            /* Determine which terminal it came from for the title */
            if (_termState.xterm) {
                var procRow = $('processes-body').querySelector('tr.selected');
                var procLabel = procRow ? (procRow.cells[1]||{}).textContent.trim() : '';
                title = 'Terminal' + (procLabel ? ' - ' + procLabel : '');
                sourceEl = $('terminal-output');
            } else {
                var dynTabBtn = $('right-tab-bar') && $('right-tab-bar').querySelector('.dynamic-tab.active, .tab-btn.active');
                title = 'Terminal - ' + (dynTabBtn ? dynTabBtn.textContent.trim() : 'Tab');
                sourceEl = _dynTermState.containerId ? $(_dynTermState.containerId) : null;
            }
        }

        /* Fallback: re-read getSelection() in case capture phase didn't save
           (e.g. button click rather than keyboard shortcut). */
        if (!text && _termState.xterm && typeof _termState.xterm.getSelection === 'function') {
            var xtSel = _termState.xterm.getSelection();
            if (xtSel) {
                text = xtSel;
                var procRow2 = $('processes-body').querySelector('tr.selected');
                var procLabel2 = procRow2 ? (procRow2.cells[1]||{}).textContent.trim() : '';
                title = 'Terminal' + (procLabel2 ? ' - ' + procLabel2 : '');
                sourceEl = $('terminal-output');
            }
        }
        if (!text && _dynTermState.xterm && typeof _dynTermState.xterm.getSelection === 'function') {
            var dynSel = _dynTermState.xterm.getSelection();
            if (dynSel) {
                text = dynSel;
                var dynTabBtn2 = $('right-tab-bar') && $('right-tab-bar').querySelector('.dynamic-tab.active, .tab-btn.active');
                title = 'Terminal - ' + (dynTabBtn2 ? dynTabBtn2.textContent.trim() : 'Tab');
                sourceEl = _dynTermState.containerId ? $(_dynTermState.containerId) : null;
            }
        }

        /* ── 3. Fall back to browser text selection (non-terminal areas) ── */
        if (!text) {
            /* domSelectionToAnsi walks the cloned selection fragment and
               reconstructs ANSI codes from ansi-fg-* span class names, so
               colour is preserved for selections in plain-output / dyn-output-*
               areas that are rendered with ansiToHtml().  Falls back to
               plain toString() for uncoloured text. */
            var _brSel = window.getSelection();
            text = domSelectionToAnsi();
            if (text) {
                try {
                    var node = _brSel && _brSel.anchorNode;
                    while (node && node !== document.body) {
                        if (node.id === 'script-output-inline') {
                            var scriptRow = $('host-detail-scripts').querySelector('tr.selected');
                            var scriptName = scriptRow ? (scriptRow.cells[0]||{}).textContent : '';
                            var scriptPort = scriptRow ? (scriptRow.cells[1]||{}).textContent : '';
                            title = 'Scripts - ' + (scriptName || 'Script') + (scriptPort ? ' (Port ' + scriptPort + ')' : '');
                            sourceEl = $('script-output-inline');
                            break;
                        }
                        if (node.id === 'process-output-inline' || node.id === 'plain-output') {
                            var procRow2 = $('processes-body').querySelector('tr.selected');
                            var procName2 = procRow2 ? (procRow2.cells[1]||{}).textContent : '';
                            title = 'Process ' + (procName2 || String(L.selectedProcessId || ''));
                            sourceEl = $('plain-output');
                            break;
                        }
                        if (node.id === 'tool-output-text') {
                            var toolHostRow = $('tool-hosts-body').querySelector('tr.selected');
                            var toolHost = toolHostRow ? (toolHostRow.cells[0]||{}).textContent : '';
                            title = (L.selectedTool || 'Tool') + (toolHost ? ' - ' + toolHost : '');
                            sourceEl = $('tool-output-text');
                            break;
                        }
                        if (node.classList && node.classList.contains('tool-output-area')) {
                            var activeTabBtn = $('right-tab-bar').querySelector('.dynamic-tab.active, .tab-btn.active');
                            title = activeTabBtn ? activeTabBtn.textContent.trim() : 'Tool Output';
                            sourceEl = node;
                            break;
                        }
                        node = node.parentElement;
                    }
                } catch(e) {}
            }
        }

        if (!text) return;

        /* Flash the Notes tab button orange — always visible regardless of
           what the source element is.  Flashing sourceEl directly fails for
           xterm terminals because xterm renders with an opaque background on
           top of its container div, hiding the colour change. */
        var _notesTabBtn = $('right-tab-bar') &&
            $('right-tab-bar').querySelector('[data-tab="notes-right"]');
        if (_notesTabBtn) {
            var _origBtnBg = _notesTabBtn.style.background;
            _notesTabBtn.style.background = 'rgba(255,165,0,0.6)';
            setTimeout(function() { _notesTabBtn.style.background = _origBtnBg; }, 400);
        }
        /* Flash the source element background with a positioned overlay so the
           flash is visible even when xterm or other content renders on top.
           The overlay sits at z-index 9999, is pointer-events:none so it
           doesn't block interaction, and removes itself after 250 ms. */
        if (sourceEl) {
            try {
                var _ov = document.createElement('div');
                _ov.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;'
                    + 'background:rgba(255,165,0,0.4);z-index:9999;'
                    + 'pointer-events:none;border-radius:inherit';
                var _pos = window.getComputedStyle(sourceEl).position;
                if (_pos === 'static') sourceEl.style.position = 'relative';
                sourceEl.appendChild(_ov);
                setTimeout(function() {
                    if (_ov.parentNode) _ov.parentNode.removeChild(_ov);
                    if (_pos === 'static') sourceEl.style.position = '';
                }, 250);
            } catch(e2) {}
        }

        /* Build formatted block: orange header + selection + spacing */
        var header = '=== Selection from ' + title + ' ===';
        var notesEl = $('notes-text');
        if (notesEl) {
            var existing = notesEl.value;
            var newText = existing + (existing ? '\n' : '') + header + '\n' + text + '\n\n';
            notesEl.value = newText;
            _showNotesDisplay(newText);
            /* Save to DB and mark Notes tab unread — stay on current tab */
            postJson('/api/workspace/hosts/' + L.selectedHostId + '/note', { note: newText });
            markTabUnread('notes-right');
        }
    }

    var noteSelBtn = $('action-note-selection');
    if (noteSelBtn) noteSelBtn.addEventListener('click', sendSelectionToNotes);

    /* Capture-phase Ctrl+B.
       Problem: xterm calls stopPropagation() in its target handler, so the
       event never reaches our bubble-phase listener and sendSelectionToNotes()
       is never called when focus is inside the terminal.
       Solution: handle the xterm case entirely in the capture phase:
         1. Read the selection before xterm clears it.
         2. Call sendSelectionToNotes() right here.
         3. stopPropagation() so xterm never sees the key at all (no \x02 to PTY).
       When there is no xterm selection the event is left alone and the
       bubble-phase listener handles it for DOM selections. */
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            _savedXtermSel = '';
            try {
                if (_termState.xterm && typeof _termState.xterm.getSelection === 'function') {
                    /* Try ANSI colour extraction first (buffer API, capture phase —
                       selection position and cell colours are still valid here).
                       Fall back to plain text if buffer API fails or returns empty. */
                    _savedXtermSel = xtermSelectionToAnsi(_termState.xterm)
                                     || _termState.xterm.getSelection() || '';
                }
                if (!_savedXtermSel && _dynTermState.xterm &&
                        typeof _dynTermState.xterm.getSelection === 'function') {
                    _savedXtermSel = xtermSelectionToAnsi(_dynTermState.xterm)
                                     || _dynTermState.xterm.getSelection() || '';
                }
            } catch(e2) {
                /* Any buffer API failure: fall back to plain text */
                try {
                    if (_termState.xterm) _savedXtermSel = _termState.xterm.getSelection() || '';
                    else if (_dynTermState.xterm) _savedXtermSel = _dynTermState.xterm.getSelection() || '';
                } catch(e3) {}
            }

            if (_savedXtermSel) {
                /* xterm has a selection: handle here, before xterm sees the key */
                e.preventDefault();
                e.stopPropagation();
                sendSelectionToNotes();
            }
            /* No xterm selection: fall through to bubble-phase for DOM selections */
        }
    }, true /* useCapture */);

    /* Bubble-phase Ctrl+B: handles DOM text selections (plain-output, dyn-output-*).
       Only reached when the capture phase did NOT stopPropagation()
       (i.e. no xterm selection was active). */
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            sendSelectionToNotes();
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
            /* Ctrl+F: open find bar when Config Manager is open */
            if (e.key === 'f') {
                var cm = $('config-modal');
                if (cm && cm.classList.contains('is-open')) {
                    e.preventDefault();
                    cfgFindShow();
                }
            }
        }
        if (e.key === 'F1') { e.preventDefault(); $('action-help') && $('action-help').click(); }
        if (e.key === 'F2') { e.preventDefault(); $('action-config') && $('action-config').click(); }
    });

    /* ── New Project ── */
    var newBtn = $('action-new');
    if (newBtn) newBtn.addEventListener('click', function() {
        if (confirm('Create new project? Current data will be lost.')) {
            postJson('/api/project/new-temp', {}).then(function() {
                setText('window-title', _VERSION + ' – *untitled');
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


    /* ── Dynamic tab right-click → Save Output (Qt6: _showToolTabContextMenu) ── */
    $('right-tab-bar').addEventListener('contextmenu', function(e) {
        var btn = e.target.closest('.dynamic-tab');
        if (!btn) return;
        e.preventDefault();
        var tabId = btn.dataset.tab;
        var procId = tabId ? tabId.replace('dyntab-', '') : null;
        var tabLabel = (btn.textContent || 'output').replace(/×$/, '').trim();
        showContextMenu(
            [{label: 'Save Output', action: 'save-output'},
             {separator: true},
             {label: 'Close Tab', action: 'close-tab'}],
            e.clientX, e.clientY,
            function(action) {
                if (action.action === 'save-output') {
                    var outputEl = $('dyn-output-' + procId);
                    var text = outputEl ? (outputEl.innerText || outputEl.textContent) : '';
                    var blob = new Blob([text], {type: 'text/plain'});
                    var url = URL.createObjectURL(blob);
                    var a = document.createElement('a');
                    a.href = url; a.download = tabLabel.replace(/[\/\:]/g,'_') + '.txt';
                    document.body.appendChild(a); a.click();
                    document.body.removeChild(a); URL.revokeObjectURL(url);
                } else if (action.action === 'close-tab') {
                    var x = btn.querySelector('.close-x');
                    if (x) x.click();
                }
            }
        );
    });

    /* Host right-click */
    $('hosts-body').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr || !tr.dataset.hostId) return;
        e.preventDefault();
        var hostId = tr.dataset.hostId;
        var hostIp = tr.dataset.hostIp || '';
        fetchJson('/api/menus/host?checked=' + (tr.classList.contains('host-checked') ? 'True' : 'False')).then(function(data) {
            showContextMenu(data.items, e.clientX, e.clientY, function(action) {
                if (action.action === 'delete' && !confirm('Delete host ' + hostIp + '?')) return;
                /* Open Terminal → start PTY bash session, auto-click the process row
                   so it goes through the same path as msfconsole (which works correctly) */
                if (action.action === 'open-terminal') {
                    postJson('/api/terminal/start', {
                        label: 'Terminal - ' + hostIp,
                        host_ip: hostIp,
                    }).then(function(d) {
                        pollSnapshot();
                        if (d.process_id) {
                            setTimeout(function() {
                                var rows = document.querySelectorAll('#processes-body tr');
                                for (var r of rows) {
                                    if (r.dataset.processId === String(d.process_id)) {
                                        r.click();
                                        break;
                                    }
                                }
                            }, 2000);
                        }
                    });
                    return;
                }
                postJson('/api/workspace/hosts/' + hostId + '/action', {
                    action: action.action, ip: hostIp, action_index: action.action_index || 0
                }).then(function() { pollSnapshot(); });
            });
        });
    });

    /* Service right-click (left panel) */
    $('services-body').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        e.preventDefault();
        var svcName = tr.dataset.service || (tr.cells[0]||{}).textContent || '';
        /* Use actual port from the row — was hardcoded to '80' (bug) */
        var svcPort = tr.dataset.port || (tr.cells[1]||{}).textContent || '80';
        fetchJson('/api/menus/service?name=' + encodeURIComponent(svcName)).then(function(data) {
            showContextMenu(data.items, e.clientX, e.clientY, function(action) {
                if (action.action === 'port-action' && L.selectedHostIp) {
                    postJson('/api/workspace/service-action', {
                        targets: [[L.selectedHostIp, svcPort, 'tcp']],
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

    /* Port right-click → full port context menu (Qt6: contextMenuServicesTableView) */
    $('host-detail-ports').addEventListener('contextmenu', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        e.preventDefault();
        var port = tr.dataset.port || (tr.cells[1]||{}).textContent || '';
        var protocol = tr.dataset.protocol || (tr.cells[2]||{}).textContent || 'tcp';
        var svcName = tr.dataset.service || (tr.cells[4]||{}).textContent || '*';
        /* Use /api/menus/port for the richer port menu (terminal + port actions) */
        fetchJson('/api/menus/port?service=' + encodeURIComponent(svcName)).then(function(data) {
            var items = (data.terminal_actions || []).concat(data.port_actions || []).concat(data.fixed_actions || []).concat(data.suffix_actions || []);
            showContextMenu(items, e.clientX, e.clientY, function(action) {
                /* [term] terminal actions → start PTY session, auto-click process row */
                if (action.action === 'terminal-action' && L.selectedHostIp) {
                    var cmd = (action.command || '').replace('[term]','').trim()
                        .replace(/\[IP\]/g, L.selectedHostIp)
                        .replace(/\[PORT\]/g, port);
                    postJson('/api/terminal/start', {
                        label: action.label || cmd.split(' ')[0],
                        host_ip: L.selectedHostIp,
                        command: cmd,
                    }).then(function(d) {
                        pollSnapshot();
                        if (d.process_id) {
                            setTimeout(function() {
                                var rows = document.querySelectorAll('#processes-body tr');
                                for (var r of rows) {
                                    if (r.dataset.processId === String(d.process_id)) {
                                        r.click();
                                        break;
                                    }
                                }
                            }, 2000);
                        }
                    });
                    return;
                }
                if (action.action === 'open-browser' && L.selectedHostIp) {
                    /* Open the service URL in a new browser tab */
                    var proto = svcName.includes('https') ? 'https' : 'http';
                    window.open(proto + '://' + L.selectedHostIp + ':' + port, '_blank');
                } else if (action.action === 'take-screenshot' && L.selectedHostIp) {
                    /* Trigger eyewitness screenshot via the screenshooter mechanism */
                    postJson('/api/terminal/start', {
                        label: 'screenshooter (' + port + '/tcp)',
                        host_ip: L.selectedHostIp,
                        command: 'xvfb-run -a /usr/bin/eyewitness --single http://' + L.selectedHostIp + ':' + port + ' --no-prompt --web --delay 5 -d /tmp/screenshot-' + L.selectedHostIp + '-' + port + '-dir',
                    }).then(function() { pollSnapshot(); });
                } else if (action.action === 'run-custom' && L.selectedHostIp) {
                    /* Qt6: "Run custom command" — prompt user for command string,
                       substitute [IP] and [PORT], run via /api/processes/custom */
                    var cmd = prompt('Enter command ([IP] and [PORT] will be substituted):');
                    if (cmd && cmd.trim()) {
                        postJson('/api/processes/custom', {
                            command: cmd.trim(),
                            host_ip: L.selectedHostIp,
                            port: port,
                            protocol: protocol
                        }).then(function() { pollSnapshot(); });
                    }
                } else if (action.action === 'port-action' && L.selectedHostIp) {
                    postJson('/api/workspace/service-action', {
                        targets: [[L.selectedHostIp, port, protocol]],
                        action_index: action.action_index || 0
                    }).then(function() { pollSnapshot(); });
                } else if (action.action === 'send-to-brute') {
                    /* Qt6: createNewBruteTab(ip, port, service) → switches to Brute tab */
                    var brutIp = $('brute-ip'), brutPort = $('brute-port'), brutSvc = $('brute-service');
                    if (brutIp) brutIp.value = L.selectedHostIp || '';
                    if (brutPort) brutPort.value = port;
                    var svcForBrute = svcName !== '*' ? svcName : '';
                    if (brutSvc) brutSvc.value = svcForBrute;
                    bruteHideShowFields(svcForBrute);
                    /* Switch to Brute main tab */
                    var bruteBtn = $('main-tab-bar') && $('main-tab-bar').querySelector('[data-tab="brute-tab"]');
                    if (bruteBtn) bruteBtn.click();
                    setText('brute-status', 'Ready — fill in wordlist and click Run Hydra');
                }
            });
        });
    });

    /* Port double-click → switch to Hosts tab and select that host
       (Qt6: tableDoubleClick → HostsTabWidget.setCurrentIndex(0) → hostTableClick) */
    $('host-detail-ports').addEventListener('dblclick', function(e) {
        var tr = e.target.closest('tr');
        if (!tr) return;
        /* Switch left panel to Hosts tab */
        var hostsTab = $('left-tab-bar').querySelector('[data-tab="hosts-panel"]');
        if (hostsTab) hostsTab.click();
        /* Select the current host in the hosts table */
        if (L.selectedHostId) {
            var hostRow = $('hosts-body').querySelector('tr[data-host-id="' + L.selectedHostId + '"]');
            if (hostRow) {
                $('hosts-body').querySelectorAll('tr').forEach(function(r) { r.classList.remove('selected'); });
                hostRow.classList.add('selected');
            }
        }
    });

    /* ═══════════════════════════════════════════
       Wire ALL upstream modals that exist in HTML
       Priority 1: blocks testing
       Priority 2: core workflow
       ═══════════════════════════════════════════ */

    /* ── Host delete confirmation (host-remove-modal) ── */
    /* Already handled by right-click context menu with confirm() —
       but wire the modal close buttons in case it gets opened */
    var rmClose = $('host-remove-modal-close');
    if (rmClose) rmClose.addEventListener('click', function() { closeModal('host-remove-modal'); });
    var rmCancel = $('host-remove-modal-cancel');
    if (rmCancel) rmCancel.addEventListener('click', function() { closeModal('host-remove-modal'); });

    /* ── Manual scan modal ── */
    var manClose = $('manual-scan-modal-close');
    if (manClose) manClose.addEventListener('click', function() { closeModal('manual-scan-modal'); });
    var manRunTool = $('workspace-run-tool-button');
    if (manRunTool) manRunTool.addEventListener('click', function() {
        var ip = ($('workspace-tool-host-ip')||{}).value||'';
        var port = ($('workspace-tool-port')||{}).value||'';
        var proto = ($('workspace-tool-protocol')||{}).value||'tcp';
        var toolSel = $('workspace-tool-select');
        var toolId = toolSel ? toolSel.value : '';
        if (!ip||!port||!toolId) { alert('Fill in host, port, and tool'); return; }
        postJson('/api/workspace/tools/run', {host_ip:ip, port:port, protocol:proto, tool_id:toolId})
        .then(function() { closeModal('manual-scan-modal'); pollSnapshot(); })
        .catch(function(e) { alert('Error: '+e.message); });
    });

    /* ── Script/CVE modal ── */
    var scClose = $('script-cve-modal-close');
    if (scClose) scClose.addEventListener('click', function() { closeModal('script-cve-modal'); });
    var addScriptBtn = $('workspace-add-script-button');
    if (addScriptBtn) addScriptBtn.addEventListener('click', function() {
        if (!L.selectedHostId) { alert('Select a host first'); return; }
        var scriptId = ($('workspace-script-id')||{}).value||'';
        var port = ($('workspace-script-port')||{}).value||'';
        var proto = ($('workspace-script-protocol')||{}).value||'tcp';
        var output = ($('workspace-script-output')||{}).value||'';
        if (!scriptId) { alert('Enter script ID'); return; }
        postJson('/api/workspace/hosts/'+L.selectedHostId+'/scripts', {
            script_id:scriptId, port:port, protocol:proto, output:output
        }).then(function() { closeModal('script-cve-modal'); pollSnapshot(); })
        .catch(function(e) { alert('Error: '+e.message); });
    });
    var addCveBtn = $('workspace-add-cve-button');
    if (addCveBtn) addCveBtn.addEventListener('click', function() {
        if (!L.selectedHostId) { alert('Select a host first'); return; }
        var name = ($('workspace-cve-name')||{}).value||'';
        var severity = ($('workspace-cve-severity')||{}).value||'';
        if (!name) { alert('Enter CVE name'); return; }
        postJson('/api/workspace/hosts/'+L.selectedHostId+'/cves', {
            name:name, severity:severity
        }).then(function() { closeModal('script-cve-modal'); pollSnapshot(); })
        .catch(function(e) { alert('Error: '+e.message); });
    });

    /* ── Host selection / notes modal ── */
    var hsClose = $('host-selection-modal-close');
    if (hsClose) hsClose.addEventListener('click', function() { closeModal('host-selection-modal'); });
    var saveNoteBtn = $('workspace-save-note-button');
    if (saveNoteBtn) saveNoteBtn.addEventListener('click', function() {
        var hostSel = $('workspace-host-select');
        var noteText = $('workspace-note');
        if (!hostSel||!noteText) return;
        var hostId = hostSel.value;
        if (!hostId) { alert('Select a host'); return; }
        postJson('/api/workspace/hosts/'+hostId+'/note', {note:noteText.value})
        .then(function() { alert('Note saved'); })
        .catch(function(e) { alert('Error: '+e.message); });
    });
    var wsRefresh = $('workspace-refresh-button');
    if (wsRefresh) wsRefresh.addEventListener('click', function() { pollSnapshot(); });

    /* ── Scheduler settings modal ── */
    var schClose = $('scheduler-modal-close');
    if (schClose) schClose.addEventListener('click', function() { closeModal('scheduler-settings-modal'); });
    var schForm = $('scheduler-form');
    if (schForm) schForm.addEventListener('submit', function(e) {
        e.preventDefault();
        var formData = {};
        new FormData(schForm).forEach(function(v,k) { formData[k]=v; });
        postJson('/api/scheduler/preferences', formData)
        .then(function() { setText('scheduler-save-status','Saved!'); })
        .catch(function(e) { setText('scheduler-save-status','Error: '+e.message); });
    });
    var schTest = $('scheduler-test-provider-button');
    if (schTest) schTest.addEventListener('click', function() {
        postJson('/api/scheduler/provider/test', {})
        .then(function(d) { alert('Provider test: '+JSON.stringify(d)); })
        .catch(function(e) { alert('Error: '+e.message); });
    });

    /* ── Report provider modal ── */
    var rpClose = $('report-provider-modal-close');
    if (rpClose) rpClose.addEventListener('click', function() { closeModal('report-provider-modal'); });
    var rpForm = $('report-provider-form');
    if (rpForm) rpForm.addEventListener('submit', function(e) {
        e.preventDefault();
        var formData = {};
        new FormData(rpForm).forEach(function(v,k) { formData[k]=v; });
        postJson('/api/settings/legion-conf', {text: JSON.stringify(formData)})
        .then(function() { setText('report-provider-save-status','Saved!'); })
        .catch(function(e) { setText('report-provider-save-status','Error: '+e.message); });
    });

    /* ── App settings modal (raw config — old style, kept as fallback) ── */
    var asClose = $('settings-modal-close');
    if (asClose) asClose.addEventListener('click', function() { closeModal('app-settings-modal'); });
    var asRefresh = $('settings-config-refresh-button');
    if (asRefresh) asRefresh.addEventListener('click', function() {
        fetchJson('/api/settings/legion-conf').then(function(d) {
            $('settings-config-text').value = d.text||'';
            setText('settings-config-status','Reloaded');
        });
    });
    var asSave = $('settings-config-save-button');
    if (asSave) asSave.addEventListener('click', function() {
        postJson('/api/settings/legion-conf', {text:$('settings-config-text').value})
        .then(function() {
            setText('settings-config-status','Saved!');
            reapplyLiveSettings();
        })
        .catch(function(e) { setText('settings-config-status','Error: '+e.message); });
    });

    /* ── Provider logs modal ── */
    var plClose = $('provider-logs-modal-close');
    if (plClose) plClose.addEventListener('click', function() { closeModal('provider-logs-modal'); });
    var plRefresh = $('provider-logs-refresh-button');
    if (plRefresh) plRefresh.addEventListener('click', function() {
        fetchJson('/api/scheduler/provider/logs').then(function(d) {
            var logs = d.logs || d;
            $('provider-logs-text').textContent = typeof logs === 'string' ? logs : JSON.stringify(logs,null,2);
            setText('provider-logs-meta', 'Loaded');
        }).catch(function(e) { setText('provider-logs-meta','Error: '+e.message); });
    });

    /* ── Screenshot modal ── */
    var ssClose = $('screenshot-modal-close');
    if (ssClose) ssClose.addEventListener('click', function() { closeModal('screenshot-modal'); });

    /* Click a screenshot image in any dynamic tab → open full-size in modal */
    document.addEventListener('click', function(e) {
        var img = e.target.closest('img');
        if (!img) return;
        /* Only fire for images inside the dynamic tabs output area */
        if (!img.closest('#dynamic-tabs-container')) return;
        var src = img.src || '';
        if (!src.includes('/api/screenshots')) return;
        var modalImg = $('screenshot-modal-image');
        var modalMeta = $('screenshot-modal-meta');
        if (modalImg) modalImg.src = src;
        if (modalMeta) {
            /* Extract host:port from URL param for display */
            try {
                var path = decodeURIComponent(src.split('path=')[1] || '');
                modalMeta.textContent = path || 'Screenshot';
            } catch(e2) {
                modalMeta.textContent = 'Screenshot';
            }
        }
        openModal('screenshot-modal');
    });

    /* ── Process output modal (fallback — we use inline, but wire close) ── */
    var poClose = $('process-output-modal-close');
    if (poClose) poClose.addEventListener('click', function() { closeModal('process-output-modal'); });

    /* ── Script output modal ── */
    var soClose = $('script-output-modal-close');
    if (soClose) soClose.addEventListener('click', function() { closeModal('script-output-modal'); });

    /* ── Nmap scan modal close (upstream wizard — our Add Hosts replaces it) ── */
    var nsClose = $('nmap-scan-modal-close');
    if (nsClose) nsClose.addEventListener('click', function() { closeModal('nmap-scan-modal'); });

    /* ── Startup wizard ── */
    var swSkip = $('startup-wizard-skip');
    if (swSkip) swSkip.addEventListener('click', function() { closeModal('startup-wizard-overlay'); });

    /* ── Add Port dialog ── */
    var apClose = $('add-port-close');
    if (apClose) apClose.addEventListener('click', function() { closeModal('add-port-modal'); });
    var apCancel = $('add-port-cancel');
    if (apCancel) apCancel.addEventListener('click', function() { closeModal('add-port-modal'); });
    var apSubmit = $('add-port-submit');
    if (apSubmit) apSubmit.addEventListener('click', function() {
        if (!L.selectedHostId) { alert('Select a host first'); return; }
        var portNum = ($('add-port-number')||{}).value||'';
        if (!portNum.trim()) { alert('Enter port number'); return; }
        postJson('/api/workspace/hosts/'+L.selectedHostId+'/action', {
            action:'add-port', ip:L.selectedHostIp||'',
            port:portNum.trim(),
            state:($('add-port-state')||{}).value||'open',
            protocol:($('add-port-protocol')||{}).value||'tcp',
            service:($('add-port-service')||{}).value||''
        }).then(function() {
            closeModal('add-port-modal');
            if (L.selectedHostId) loadHostDetail(L.selectedHostId);
            pollSnapshot();
        }).catch(function(e) { alert('Error: '+e.message); });
    });

    /* ── Filters dialog ── */
    var fClose = $('filters-close');
    if (fClose) fClose.addEventListener('click', function() { closeModal('filters-modal'); });
    var fCancel = $('filters-cancel');
    if (fCancel) fCancel.addEventListener('click', function() { closeModal('filters-modal'); });
    var fApply = $('filters-apply');
    if (fApply) fApply.addEventListener('click', function() {
        closeModal('filters-modal');
        /* Qt6: Filters.apply(up,down,checked,portopen,portfiltered,portclosed,tcp,udp,keywords)
           Read all checkboxes and store in L._filters, then re-render. */
        L._filters.up         = !!($('filter-hosts-up')||{}).checked;
        L._filters.down       = !!($('filter-hosts-down')||{}).checked;
        L._filters.portopen   = !!($('filter-ports-open')||{}).checked;
        L._filters.portclosed = !!($('filter-ports-closed')||{}).checked;
        L._filters.portfiltered = !!($('filter-ports-filtered')||{}).checked;
        L._filters.tcp        = !!($('filter-ports-tcp')||{}).checked;
        L._filters.udp        = !!($('filter-ports-udp')||{}).checked;
        /* Sync filter checkboxes to their current state on open */
        _drawHosts();  /* immediately re-renders with new filters */
        pollSnapshot();
    });
    /* Wire filter-advanced button to open filters dialog */
    var fAdvBtn = $('filter-advanced');
    if (fAdvBtn) fAdvBtn.addEventListener('click', function() { openModal('filters-modal'); });

    /* ── Help dialog ── */
    var helpBtn2 = $('action-help');
    if (helpBtn2) {
        /* Remove old alert handler and replace with modal */
        helpBtn2.removeEventListener('click', helpBtn2._handler);
        helpBtn2._handler = function() { openModal('help-modal'); };
        helpBtn2.addEventListener('click', helpBtn2._handler);
    }
    var helpClose = $('help-close');
    if (helpClose) helpClose.addEventListener('click', function() { closeModal('help-modal'); });

    /* ── Log tab — load, filter and auto-refresh (Qt6: reloadLogFile) ── */
    var _logTimer = null;
    function loadLog() {
        var level = ($('log-level')||{}).value || 'INFO';
        fetchJson('/api/logs?level=' + encodeURIComponent(level)).then(function(d) {
            var out = $('log-output');
            if (out) {
                var logAtBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
                /* _InMemoryLogHandler now stores Rich-formatted lines with ANSI
                   escape codes (same colours as the server console).  ansiToHtml()
                   converts them to coloured <span>s and HTML-escapes everything else. */
                out.innerHTML = ansiToHtml((d.lines || []).join('\n'));
                if (logAtBottom) out.scrollTop = out.scrollHeight;
            }
            setText('log-line-count', (d.lines||[]).length + ' lines');
        }).catch(function() {});
    }
    /* Load and start refresh timer when Log tab becomes active */
    $('bottom-tab-bar').addEventListener('click', function(e) {
        var btn = e.target.closest('[data-tab="log-panel"]');
        if (btn) {
            loadLog();
            if (_logTimer) clearInterval(_logTimer);
            _logTimer = setInterval(loadLog, 5000);
        } else {
            if (_logTimer) { clearInterval(_logTimer); _logTimer = null; }
        }
    });
    var logLevel = $('log-level');
    if (logLevel) logLevel.addEventListener('change', loadLog);
    var logRefresh = $('log-refresh');
    if (logRefresh) logRefresh.addEventListener('click', loadLog);

    /* ── Font size control — lower panel (process output + log) ── */
    (function() {
        var MIN_PT = 7, MAX_PT = 24;
        var LS_KEY = 'legion_output_font_pt';
        var _pt = parseInt(localStorage.getItem(LS_KEY)) || 10;

        function applyFontSize() {
            var px = _pt + 'pt';
            /* Stable container elements — children use font:inherit so cascade applies
               automatically to dynamic elements created after this call. */
            ['process-output-inline', 'log-panel'].forEach(function(id) {
                var el = $(id);
                if (el) el.style.fontSize = px;
            });
            var lbl = $('output-font-label');
            if (lbl) lbl.textContent = _pt;
            localStorage.setItem(LS_KEY, _pt);

            /* xterm in lower panel (Notes terminal) */
            var termPx = Math.max(8, Math.round(_pt * 1.333));
            if (_termState && _termState.xterm) {
                _termState.xterm.options.fontSize = termPx;
                if (_termState.fitAddon) { try { _termState.fitAddon.fit(); } catch(e) {} }
            }
        }
        applyFontSize();

        function changeFontSize(delta) {
            _pt = Math.max(MIN_PT, Math.min(MAX_PT, _pt + delta));
            applyFontSize();
        }

        var fdec = $('output-font-dec'), finc = $('output-font-inc');
        if (fdec) fdec.addEventListener('click', function() { changeFontSize(-1); });
        if (finc) finc.addEventListener('click', function() { changeFontSize(+1); });

        /* Log panel buttons share the lower font size */
        var lfdec = $('log-font-dec'), lfinc = $('log-font-inc');
        if (lfdec) lfdec.addEventListener('click', function() { changeFontSize(-1); });
        if (lfinc) lfinc.addEventListener('click', function() { changeFontSize(+1); });
    })();

    /* ── Font size control — upper panel (dynamic tool output tabs) ── */
    (function() {
        var MIN_PT = 7, MAX_PT = 24;
        var LS_KEY = 'legion_upper_font_pt';
        var _pt = parseInt(localStorage.getItem(LS_KEY)) || 10;

        function applyFontSize() {
            var px = _pt + 'pt';
            var el = $('dynamic-tabs-container');
            if (el) el.style.fontSize = px;
            var lbl = $('upper-font-label');
            if (lbl) lbl.textContent = _pt;
            localStorage.setItem(LS_KEY, _pt);

            /* xterm in upper panel (dynamic terminal tab) */
            var termPx = Math.max(8, Math.round(_pt * 1.333));
            if (_dynTermState && _dynTermState.xterm) {
                _dynTermState.xterm.options.fontSize = termPx;
                if (_dynTermState.fitAddon) { try { _dynTermState.fitAddon.fit(); } catch(e) {} }
            }
        }
        applyFontSize();

        function changeFontSize(delta) {
            _pt = Math.max(MIN_PT, Math.min(MAX_PT, _pt + delta));
            applyFontSize();
        }

        var udec = $('upper-font-dec'), uinc = $('upper-font-inc');
        if (udec) udec.addEventListener('click', function() { changeFontSize(-1); });
        if (uinc) uinc.addEventListener('click', function() { changeFontSize(+1); });
    })();

    /* ── Port state filter (Services right tab) ── */
    (function() {
        function getStateFilter() {
            return {
                open:     ($('filter-state-open')     || {}).checked !== false,
                filtered: !!($('filter-state-filtered') || {}).checked,
                closed:   !!($('filter-state-closed')   || {}).checked
            };
        }
        function applyStateFilter() {
            /* Re-draw ports table with current filter applied */
            var sf = getStateFilter();
            var body = $('host-detail-ports');
            if (!body) return;
            body.querySelectorAll('tr').forEach(function(tr) {
                var stateCell = tr.cells[3];
                if (!stateCell) return;
                var state = stateCell.textContent.trim().toLowerCase();
                var show = false;
                if (state === 'open' && sf.open) show = true;
                if ((state === 'filtered' || state === 'open|filtered') && sf.filtered) show = true;
                if (state === 'closed' && sf.closed) show = true;
                tr.style.display = show ? '' : 'none';
            });
        }
        /* Wire checkboxes */
        ['filter-state-open','filter-state-filtered','filter-state-closed'].forEach(function(id) {
            var el = $(id);
            if (el) el.addEventListener('change', applyStateFilter);
        });
        /* Re-apply after each ports render (renderPorts is called from loadHostDetail) */
        var _origDrawPorts = window._drawPortsOrig;
        /* Hook into _drawPorts — called after render so we filter the new rows */
        document.addEventListener('legion:ports-rendered', applyStateFilter);
    })();

    /* ── UI preferences (tool-output-black-background etc.) — applied once at load ── */
    fetch('/api/settings/ui-prefs').then(function(r){ return r.json(); }).then(function(d) {
        if (d.tool_output_black_background) {
            document.body.classList.add('black-output-bg');
        } else {
            document.body.classList.remove('black-output-bg');
        }
    }).catch(function(){});

    /* ── Brute force tab (Qt6: callHydra → buildHydraCommand → runCommand) ── */

    /* Brute defaults: loaded once, used for hide/show and pre-fill */
    L._bruteNoUserSvcs = [];
    L._bruteNoPassSvcs = [];

    function bruteHideShowFields(service) {
        var svc = (service || '').toLowerCase().trim();
        var uRow = $('brute-username-row');
        var pRow = $('brute-password-row');
        if (uRow) uRow.style.display = L._bruteNoUserSvcs.indexOf(svc) !== -1 ? 'none' : '';
        if (pRow) pRow.style.display = L._bruteNoPassSvcs.indexOf(svc) !== -1 ? 'none' : '';
    }

    /* Fetch defaults from legion.conf and pre-fill fields */
    fetch('/api/brute/defaults').then(function(r){ return r.json(); }).then(function(d) {
        L._bruteNoUserSvcs = (d.no_username_services || []).map(function(s){ return s.toLowerCase(); });
        L._bruteNoPassSvcs = (d.no_password_services || []).map(function(s){ return s.toLowerCase(); });
        /* Pre-fill wordlist paths and single credentials if fields are still empty */
        var ul = $('brute-userlist'), pl = $('brute-passlist');
        var un = $('brute-username'), pw = $('brute-password');
        if (ul && !ul.value && d.username_wordlist) ul.value = d.username_wordlist;
        if (pl && !pl.value && d.password_wordlist) pl.value = d.password_wordlist;
        if (un && !un.value && d.default_username) un.value = d.default_username;
        if (pw && !pw.value && d.default_password) pw.value = d.default_password;
        /* Apply hide/show for current service value */
        bruteHideShowFields(($('brute-service')||{}).value||'');
    }).catch(function(){});

    /* Re-apply hide/show whenever service field changes */
    var bruteSvcEl = $('brute-service');
    if (bruteSvcEl) bruteSvcEl.addEventListener('input', function() {
        bruteHideShowFields(this.value);
    });

    var bruteRun = $('brute-run');
    if (bruteRun) bruteRun.addEventListener('click', function() {
        var ip       = ($('brute-ip')||{}).value||'';
        var port     = ($('brute-port')||{}).value||'';
        var service  = ($('brute-service')||{}).value||'';
        var userlist = ($('brute-userlist')||{}).value||'';
        var passlist = ($('brute-passlist')||{}).value||'';
        var username = ($('brute-username')||{}).value||'';
        var password = ($('brute-password')||{}).value||'';
        var options  = ($('brute-options')||{}).value||'';
        if (!ip||!port||!service) { setText('brute-status','Fill in IP, port, and service'); return; }
        /* Need at least a username source unless it's a no-username service */
        var noUser = L._bruteNoUserSvcs.indexOf(service.toLowerCase()) !== -1;
        if (!noUser && !userlist && !username) { setText('brute-status','Enter a username or wordlist'); return; }
        setText('brute-status','Starting Hydra...');
        /* Qt6: buildHydraCommand → controller.runCommand('hydra', ...) */
        postJson('/api/brute/run', {ip:ip, port:port, service:service,
                                    userlist:userlist, passlist:passlist,
                                    username:username, password:password, options:options})
        .then(function(d) {
            setText('brute-status', d.process_id
                ? 'Hydra started (process ' + d.process_id + ')'
                : 'Hydra started');
            pollSnapshot();
        }).catch(function(e) { setText('brute-status','Error: '+e.message); });
    });

    /* ── Add port from context menu ── */
    /* When right-click host menu has "Add Port", open the dialog */

    /* ═══════════════════════════════════════════
       visualUpgrades features
       ═══════════════════════════════════════════ */

    /* P1: Match highlighting — load positive/negative patterns from legion.conf once at startup.
       matchPositive/matchNegative are global; highlightMatches() uses them when rendering output. */
    fetchJson('/api/settings/legion-conf').then(function(d) {
        var text = d.text || '';
        var inMatch = false;
        text.split('\n').forEach(function(line) {
            if (line.trim() === '[MatchSettings]') { inMatch = true; return; }
            if (line.trim().startsWith('[') && inMatch) { inMatch = false; return; }
            if (!inMatch) return;
            var eq = line.indexOf('=');
            if (eq < 0) return;
            var key = line.substring(0, eq).trim();
            var val = line.substring(eq+1).trim().replace(/^"|"$/g, '');
            if (key.endsWith('-positive')) {
                val.split(',').forEach(function(v) { if (v.trim()) matchPositive.push(v.trim()); });
            } else if (key.endsWith('-negative')) {
                val.split(',').forEach(function(v) { if (v.trim()) matchNegative.push(v.trim()); });
            }
        });
    }).catch(function() {});

    /* P2: Tab unread tracking */
    var lastSeenData = {};
    function checkTabUnread(tabId, dataHash) {
        if (lastSeenData[tabId] === undefined) { lastSeenData[tabId] = dataHash; return; }
        if (lastSeenData[tabId] !== dataHash) {
            var tabBtn = document.querySelector('[data-tab="' + tabId + '"]');
            if (tabBtn && !tabBtn.classList.contains('active')) {
                tabBtn.classList.add('tab-unread');
            }
        }
    }
    /* Clear unread on tab click — also remove from per-host persistent state */
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.tab-btn');
        if (btn) {
            btn.classList.remove('tab-unread');
            var tabId = btn.dataset.tab || '';
            if (tabId && L.snapshot) lastSeenData[tabId] = JSON.stringify(L.snapshot).length;
            /* Remove from host's persisted unread set so it doesn't come back on host switch */
            if (tabId && L.selectedHostId && L._hostUnreadTabs[L.selectedHostId]) {
                delete L._hostUnreadTabs[L.selectedHostId][tabId];
            }
        }
    });

    /* P4: Selection preservation — store selectedHostId for re-highlight */
    /* Already implemented via L.selectedHostId + MutationObserver */

    /* P7: Splitter position memory via localStorage */
    function saveSplitterPos(key, el) {
        if (el) localStorage.setItem('legion-splitter-' + key, el.style.width || el.style.height || '');
    }
    function restoreSplitterPos(key, el, prop) {
        var saved = localStorage.getItem('legion-splitter-' + key);
        if (saved && el) el.style[prop] = saved;
    }
    /* Restore on load */
    var leftPane = $('left-panel');
    if (leftPane) restoreSplitterPos('left', leftPane, 'width');
    var bottomSec = $('bottom-section');
    if (bottomSec) restoreSplitterPos('bottom', bottomSec, 'height');
    /* Save on mouseup after drag */
    document.addEventListener('mouseup', function() {
        if (leftPane) saveSplitterPos('left', leftPane);
        if (bottomSec) saveSplitterPos('bottom', bottomSec);
    });

    /* P8: Graceful shutdown on page unload.
       Also warn if the project has unsaved data (tab close, browser nav, refresh). */
    window.addEventListener('beforeunload', function(e) {
        try {
            navigator.sendBeacon('/api/shutdown', '{}');
        } catch(e2) {}
        /* Warn about unsaved data — browser shows its own generic dialog */
        var proj = (L.snapshot && L.snapshot.project) || {};
        var isTemp = proj.is_temporary !== false;
        var hasData = L.hosts && L.hosts.length > 0;
        if (isTemp && hasData) {
            e.preventDefault();
            e.returnValue = 'Your project has unsaved changes.';
            return e.returnValue;
        }
    });

    /* ── Populate manual scan tool selector when snapshot updates ── */
    var origPoll = pollSnapshot;
    pollSnapshot = function() {
        origPoll();
        /* Update tool selector in manual scan modal */
        setTimeout(function() {
            var sel = $('workspace-tool-select');
            if (!sel) return;
            var current = sel.value;
            sel.innerHTML = '';
            (L.tools || []).forEach(function(t) {
                var opt = document.createElement('option');
                opt.value = t.tool_id || t.label || '';
                opt.textContent = (t.label || t.tool_id || '') + ' (' + (t.tool_id || '') + ')';
                sel.appendChild(opt);
            });
            if (current) sel.value = current;

            /* Update host selector in host-selection modal */
            var hsel = $('workspace-host-select');
            if (!hsel) return;
            var hcur = hsel.value;
            hsel.innerHTML = '';
            (L.snapshot && L.snapshot.hosts || []).forEach(function(h) {
                var opt = document.createElement('option');
                opt.value = h.id || '';
                opt.textContent = (h.ip||'') + (h.hostname ? ' ('+h.hostname+')' : '');
                hsel.appendChild(opt);
            });
            if (hcur) hsel.value = hcur;
        }, 100);
    };

});
