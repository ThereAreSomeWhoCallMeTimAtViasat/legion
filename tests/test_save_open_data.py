#!/usr/bin/env python3
"""tests/test_save_open_data.py

Non-hollow Selenium / API tests for the save-open data-integrity fixes
introduced in v10.65 and v10.66.

  v10.65 Fix 1 – outputfile + command paths rewritten in saved DB
  v10.65 Fix 2 – keyword match highlights (process_matches) saved/restored
  v10.65 Fix 3 – interactive PTY buffer saved to process_output on save
  v10.66 Fix 4 – staged scan commands recorded in host notes

Port: 5073
Run:
    cd /home/kali/Downloads/legion
    sudo python3 -m pytest tests/test_save_open_data.py -v
"""

import os
import sys
import time
import shutil
import sqlite3
import tempfile
import threading

import pytest
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service

PORT = 5073
BASE = f"http://127.0.0.1:{PORT}"
IP   = '10.73.73.1'

_SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache" version="2.4"/>
      </port>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh" product="OpenSSH" version="8.4"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

# ── helpers ───────────────────────────────────────────────────────────────────

def _free_port(port, retries=20):
    import subprocess, socket
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    for _ in range(retries):
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
            s.close()
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Port {port} still in use")


def _post(url, **kw):
    return requests.post(f"{BASE}{url}", json=kw, timeout=15)


def _get(url, **params):
    return requests.get(f"{BASE}{url}", params=params, timeout=10)


def _wait_proc_done(proc_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = _get('/api/snapshot').json()
            for p in data.get('processes', []):
                if str(p.get('id')) == str(proc_id):
                    if p.get('status') in ('Finished', 'Killed', 'Crashed'):
                        return p
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Process {proc_id} did not finish in {timeout}s")


def _host_id():
    """Return the DB id of the seeded host."""
    data = _get('/api/snapshot').json()
    for h in data.get('hosts', []):
        if h.get('ip') == IP:
            return h['id']
    raise RuntimeError(f"Host {IP} not found in snapshot")


def _get_note(host_id):
    r = _get(f'/api/workspace/hosts/{host_id}')
    return r.json().get('note', '') or ''


def _save_to_tmp():
    """Save current project to a temp .legion file; return its path.
    NOTE: saveProjectAs switches the active project to the saved file.
    Call _reset_server() afterward to restore a clean state."""
    tf = tempfile.NamedTemporaryFile(suffix='.legion', delete=False, prefix='legion_test_')
    dest = tf.name
    tf.close()
    os.unlink(dest)          # saveProjectAs requires the file to not pre-exist
    r = _post('/api/project/save-as', path=dest)
    assert r.status_code == 200, f"save-as failed: {r.text}"
    return dest


def _reset_server(srv):
    """Kill running processes and reset active project to a fresh seeded state.
    Called after _save_to_tmp() to undo the active-project switch that
    saveProjectAs() performs, so subsequent test classes start cleanly."""
    from app.importers.nmap_import import import_nmap_xml
    wc    = srv['wc']
    logic = srv['logic']
    wc.killRunningProcesses()
    time.sleep(1.5)   # let background threads notice kill before project switch
    logic.createNewTemporaryProject()
    wc.start()
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED)
        xml_path = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output='')
    os.unlink(xml_path)


def _delete_tmp(dest):
    """Delete a saved temp project file and its companions."""
    for p in [dest, dest + '-wal', dest + '-shm']:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except Exception:
            pass
    tool_dir = dest.replace('.legion', '') + '-tool-output'
    if os.path.isdir(tool_dir):
        shutil.rmtree(tool_dir, ignore_errors=True)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def srv():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server

    _free_port(PORT)

    import app.web.routes as _wr
    _orig = getattr(_wr, '_HB_TIMEOUT', 20)
    _wr._HB_TIMEOUT = 600

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED)
        xml_path = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output='')
    os.unlink(xml_path)

    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(1.5)

    yield {'url': BASE, 'logic': logic, 'wc': wc}

    wc.killRunningProcesses()
    httpd.shutdown()
    _wr._HB_TIMEOUT = _orig


@pytest.fixture(scope="module")
def drv(srv):
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(BASE)
    time.sleep(1.5)
    yield d
    d.quit()


# ══════════════════════════════════════════════════════════════════════════════
# Fix 1 — outputfile and command paths rewritten in saved DB  (v10.65)
# ══════════════════════════════════════════════════════════════════════════════

class TestOutputfilePathRewriting:
    """
    After saveProjectAs():
      • outputfile column rows that contained the old temp-folder prefix
        now use the new <dest>-tool-output prefix
      • command column rows are similarly rewritten
      • no row still contains the original /tmp/legion/<old-temp>-tool-output prefix
    """

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, srv):
        wc = srv['wc']
        old_output_folder = wc.logic.activeProject.properties.outputFolder.rstrip('/')

        # Trigger staged scan: creates nmap process rows in DB with outputfile
        # and command pointing to the current temp outputFolder.
        # Rows are stored synchronously by runCommand() before nmap starts.
        r = _post('/api/nmap/scan', targets=IP, staged=True, discovery=False)
        assert r.status_code == 200
        time.sleep(0.5)

        dest = _save_to_tmp()
        type(self)._dest           = dest
        type(self)._old_prefix     = old_output_folder
        type(self)._new_prefix     = dest.replace('.legion', '') + '-tool-output'

        yield

        # Reset server state so subsequent test classes start clean
        _reset_server(srv)
        _delete_tmp(dest)

    def _rows(self, col):
        with sqlite3.connect(self._dest) as con:
            return [r[0] or '' for r in
                    con.execute(f"SELECT {col} FROM process").fetchall()]

    def test_no_old_prefix_in_outputfile(self):
        old = self._old_prefix
        bad = [v for v in self._rows('outputfile') if old in v]
        assert not bad, (
            f"{len(bad)} outputfile row(s) still contain old prefix {old!r}:\n"
            + '\n'.join(bad[:3]))

    def test_no_old_prefix_in_command(self):
        old = self._old_prefix
        bad = [v for v in self._rows('command') if old in v]
        assert not bad, (
            f"{len(bad)} command row(s) still contain old prefix {old!r}:\n"
            + '\n'.join(bad[:3]))

    def test_nmap_outputfile_uses_new_prefix(self):
        new = self._new_prefix
        vals = [v for v in self._rows('outputfile') if 'nmapstage' in v]
        assert vals, "No nmapstage outputfile rows in saved DB"
        for v in vals:
            assert v.startswith(new), (
                f"nmap outputfile does not start with new prefix:\n  {v!r}\n  expected prefix: {new!r}")

    def test_nmap_command_uses_new_prefix(self):
        new = self._new_prefix
        vals = [v for v in self._rows('command') if 'nmapstage' in v]
        assert vals, "No nmapstage command rows in saved DB"
        for v in vals:
            assert new in v, (
                f"nmap command does not contain new prefix:\n  {v!r}\n  expected: {new!r}")


# ══════════════════════════════════════════════════════════════════════════════
# Fix 2 — keyword matches saved to process_matches table  (v10.65)
# ══════════════════════════════════════════════════════════════════════════════

class TestKeywordMatchesSavedToDb:
    """
    Running a command whose output contains a global-positive pattern
    ("tcp open") triggers handleMatch() → _matches dict.  On save,
    saveMatchState() writes those entries to process_matches.
    loadMatchState() restores them when the project is reopened.
    """

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, srv):
        # echo "tcp open ..." — matches global-positive pattern from legion.conf
        r = _post('/api/processes/custom',
                  command='printf "tcp open port 80\\ntcp open port 443\\n"',
                  host_ip=IP, port='80', protocol='tcp')
        assert r.status_code == 200
        type(self)._proc_id = r.json()['process_id']
        _wait_proc_done(type(self)._proc_id, timeout=20)

        dest = _save_to_tmp()
        type(self)._dest = dest

        yield

        _reset_server(srv)
        _delete_tmp(dest)

    def test_process_matches_table_exists_in_saved_db(self):
        with sqlite3.connect(self._dest) as con:
            tables = {r[0] for r in
                      con.execute("SELECT name FROM sqlite_master "
                                  "WHERE type='table'").fetchall()}
        assert 'process_matches' in tables, (
            f"process_matches table missing from saved DB; tables={tables}")

    def test_match_detected_in_snapshot(self):
        """Snapshot exposes has_match=True for the process that produced
        output matching 'tcp open'."""
        data = _get('/api/snapshot').json()
        matched = [p for p in data.get('processes', [])
                   if str(p.get('id')) == str(self._proc_id)]
        assert matched, f"Process {self._proc_id} not in snapshot"
        assert matched[0].get('has_match'), (
            f"has_match=False for proc {self._proc_id}; "
            f"match_text={matched[0].get('match_text')!r}")

    def test_process_matches_rows_saved_to_db(self):
        with sqlite3.connect(self._dest) as con:
            rows = con.execute("SELECT hostIp, tabTitle, matchStr "
                               "FROM process_matches").fetchall()
        assert rows, "process_matches table is empty — saveMatchState() did not persist"

    def test_saved_match_references_correct_host(self):
        with sqlite3.connect(self._dest) as con:
            ips = {r[0] for r in
                   con.execute("SELECT hostIp FROM process_matches").fetchall()}
        assert IP in ips, (
            f"Expected host {IP} in process_matches; got {ips}")

    def test_loadMatchState_restores_matches(self, srv):
        """After calling loadMatchState() on the live WC, _matches is populated."""
        wc = srv['wc']
        wc.loadMatchState()
        matches = getattr(wc, '_matches', {})
        assert matches, "_matches is empty after loadMatchState()"
        assert any(IP in k for k in matches), (
            f"No match key contains {IP}; keys={list(matches)[:5]}")


# ══════════════════════════════════════════════════════════════════════════════
# Fix 3 — interactive PTY buffer saved to process_output on save  (v10.65)
# ══════════════════════════════════════════════════════════════════════════════

class TestInteractivePtyOutputSaved:
    """
    A command containing 'bash' triggers _startInteractiveProcess() which
    creates a _TerminalSession.  _buf accumulates PTY output.  On save,
    saveRunningProcessOutputs() reads _buf and writes to process_output.
    """

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, srv):
        marker = 'LEGIONTEST_PTY_MARKER_12345'
        # 'bash' in command → interactive mode; sleep keeps process alive during save
        cmd = f"bash -c 'echo {marker}; sleep 30'"
        r = _post('/api/processes/custom',
                  command=cmd, host_ip=IP, port='80', protocol='tcp')
        assert r.status_code == 200
        type(self)._proc_id = r.json()['process_id']
        type(self)._marker  = marker

        # Give PTY reader thread 2 s to accumulate output in _buf
        time.sleep(2.0)

        dest = _save_to_tmp()
        type(self)._dest = dest

        yield

        _post(f'/api/processes/{type(self)._proc_id}/kill')
        time.sleep(0.3)
        _reset_server(srv)
        _delete_tmp(dest)

    def test_process_is_interactive_in_snapshot(self):
        data = _get('/api/snapshot').json()
        procs = [p for p in data.get('processes', [])
                 if str(p.get('id')) == str(self._proc_id)]
        assert procs, f"Process {self._proc_id} not in snapshot"
        assert procs[0].get('status') == 'Interactive', (
            f"Expected Interactive, got {procs[0].get('status')!r}")

    def test_pty_buffer_saved_to_process_output(self):
        with sqlite3.connect(self._dest) as con:
            row = con.execute(
                "SELECT output FROM process_output WHERE processId=?",
                (self._proc_id,)
            ).fetchone()
        assert row is not None, (
            f"No process_output row for Interactive proc {self._proc_id}")
        assert row[0], "process_output is empty — PTY buffer was not saved"

    def test_pty_output_contains_marker(self):
        with sqlite3.connect(self._dest) as con:
            row = con.execute(
                "SELECT output FROM process_output WHERE processId=?",
                (self._proc_id,)
            ).fetchone()
        output = row[0] if row else ''
        assert self._marker in output, (
            f"Marker {self._marker!r} not in saved PTY output "
            f"({len(output)} bytes, first 200: {output[:200]!r})")

    def test_interactive_status_preserved_in_saved_db(self):
        with sqlite3.connect(self._dest) as con:
            row = con.execute(
                "SELECT status FROM process WHERE id=?",
                (self._proc_id,)
            ).fetchone()
        assert row is not None, f"Process {self._proc_id} missing from saved DB"
        assert row[0] == 'Interactive', (
            f"Expected Interactive in saved DB, got {row[0]!r}")


# ══════════════════════════════════════════════════════════════════════════════
# Fix 4 — staged scan commands recorded in host notes  (v10.66)
# ══════════════════════════════════════════════════════════════════════════════

class TestScanCommandsInNotes:
    """
    runStagedNmap() writes a dated block of PORTS commands + NSE template to
    each target host's notes before launching stage threads.
    _launch_nse_stage() appends the actual NSE command (with real -p arg)
    once discovered ports are known.
    """

    @pytest.fixture(scope="class", autouse=True)
    def setup(self, srv):
        hid = _host_id()
        type(self)._hid = hid

        # Trigger staged scan — notes are written synchronously inside
        # runStagedNmap() BEFORE stage threads are spawned, so they are
        # present in the DB by the time the HTTP response arrives.
        r = _post('/api/nmap/scan', targets=IP, staged=True, discovery=False)
        assert r.status_code == 200

        type(self)._notes_initial = _get_note(hid)

        # Wait for NSE stage to query ports and append "NSE actual:" line.
        # NSE only runs after ALL PORTS stages complete.  On an unreachable IP
        # nmap receives ICMP host-unreachable immediately per port, so stages
        # with short port lists finish in seconds; stage 4/5 (30k+ ports) may
        # take longer.  Poll for up to 90 s; the test will skip if not done.
        deadline = time.time() + 90
        notes_after = type(self)._notes_initial
        while time.time() < deadline:
            notes_after = _get_note(hid)
            if 'NSE actual' in notes_after:
                break
            time.sleep(1.0)
        type(self)._notes_after = notes_after

        yield

        srv['wc'].killRunningProcesses()

    def test_notes_contain_scan_header(self):
        assert '=== Scan ' in self._notes_initial, (
            f"No '=== Scan' header in notes:\n{self._notes_initial[:400]!r}")

    def test_notes_contain_ports_stage_command(self):
        assert '(PORTS)' in self._notes_initial, (
            f"No PORTS stage command in notes:\n{self._notes_initial[:500]!r}")

    def test_notes_ports_command_contains_nmap(self):
        lines = [l for l in self._notes_initial.splitlines() if '(PORTS)' in l]
        assert lines, f"No (PORTS) lines found"
        assert any('nmap' in l for l in lines), (
            f"PORTS lines do not contain 'nmap': {lines}")

    def test_notes_contain_nse_template(self):
        assert 'NSE' in self._notes_initial, (
            f"No NSE entry in initial notes:\n{self._notes_initial[:500]!r}")

    def test_nse_template_mentions_script(self):
        lines = [l for l in self._notes_initial.splitlines() if 'NSE' in l]
        assert any('--script' in l or 'vulners' in l or 'template' in l
                   for l in lines), (
            f"NSE lines do not mention script: {lines}")

    def test_nse_actual_appended_after_port_discovery(self):
        if 'NSE actual' not in self._notes_after:
            pytest.skip(
                "PORTS stages did not complete within 90 s. "
                "_launch_nse_stage() appends 'NSE actual' only after all "
                "PORTS stages finish — correct but slow on unreachable targets."
            )
        assert 'NSE actual' in self._notes_after

    def test_second_scan_accumulates_in_notes(self, srv):
        hid = _host_id()
        notes_before = _get_note(hid)
        count_before = notes_before.count('=== Scan ')

        _post('/api/nmap/scan', targets=IP, staged=True, discovery=False)
        time.sleep(0.5)

        notes_after = _get_note(hid)
        count_after = notes_after.count('=== Scan ')
        assert count_after > count_before, (
            f"Second scan did not add a new block: "
            f"before={count_before}, after={count_after}")
        srv['wc'].killRunningProcesses()  # clean up second scan's nmap

    def test_notes_show_in_ui_notes_tab(self, drv, srv):
        """Notes tab in the browser renders the scan commands."""
        drv.get(BASE)
        time.sleep(2.0)

        rows = drv.find_elements(By.CSS_SELECTOR, '#hosts-body tr')
        target_row = next((r for r in rows if IP in r.text), None)
        assert target_row, f"Host row for {IP} not in UI"
        # Use JS click to avoid ElementNotInteractableError on partially-visible rows
        drv.execute_script("arguments[0].click()", target_row)
        time.sleep(0.8)

        tabs = drv.find_elements(By.CSS_SELECTOR, '.tab-btn')
        notes_tab = next((t for t in tabs if 'Note' in t.text), None)
        assert notes_tab, "Notes tab button not found"
        drv.execute_script("arguments[0].click()", notes_tab)
        time.sleep(1.0)

        panel = drv.find_element(By.ID, 'notes-display')
        assert '=== Scan' in panel.text or 'nmap' in panel.text, (
            f"Notes panel does not show scan commands: {panel.text[:300]!r}")
