"""
Non-hollow Selenium tests for session fixes v10.146 – v10.157.

v10.146  checkDuplicate user_triggered — right-click tools on scanned ports no
         longer blocked by layer-2 NSE-script check.
v10.154  Delete host — processes evicted from _active_processes, queue drained
         first, process_matches deleted.
v10.155  Tab scroll arrows — ◀/▶ buttons visible and functional.
v10.156  Purge/Delete UI clearing — plain-output cleared, dynamic tabs removed,
         L.selectedProcessId and L.selectedHostIp reset.
v10.157  process_matches uses hostIp column (not process_id) — delete and purge
         transactions no longer abort silently.

Each class proves a distinct behavioural capability:
  TestCheckDuplicateUserTriggered  — layer-2 bypass for user-triggered actions
  TestTabScrollArrows              — ◀/▶ scroll the right tab bar
  TestPurgeHostUI                  — purge clears UI and DB data, keeps host+notes
  TestDeleteHostUI                 — delete clears UI and removes host entirely
"""

import os
import socket
import subprocess
import tempfile
import threading
import time

import pytest
import requests as _requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ── Constants ─────────────────────────────────────────────────────────────────

PORT = 5100

# Two hosts — A is deleted, B is purged, both used for independence verification
IP_A = '10.50.50.1'   # delete tests
IP_B = '10.50.50.2'   # purge tests

SEED = f"""<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="{IP_A}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http" product="Apache"/>
      </port>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh"/>
      </port>
      <port protocol="tcp" portid="3306">
        <state state="open"/>
        <service name="mysql"/>
      </port>
    </ports>
  </host>
  <host>
    <status state="up"/>
    <address addr="{IP_B}" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http"/>
      </port>
      <port protocol="tcp" portid="443">
        <state state="open"/>
        <service name="https"/>
      </port>
    </ports>
  </host>
</nmaprun>"""

BASE = f'http://127.0.0.1:{PORT}'

# ── Helpers ───────────────────────────────────────────────────────────────────

def js(d, script, *args):
    return d.execute_script(script, *args)

def W(d, timeout):
    return WebDriverWait(d, timeout)

def _free_port(port, retries=20):
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
    raise RuntimeError(f'Port {port} still in use after {retries} retries')


def _wait_proc_done_api(proc_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in _requests.get(f'{BASE}/api/snapshot', timeout=5).json().get('processes', []):
                if str(p.get('id')) == str(proc_id) and p.get('status') in ('Finished', 'Killed', 'Crashed'):
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f'Process {proc_id} not done within {timeout}s')


def _snapshot():
    return _requests.get(f'{BASE}/api/snapshot', timeout=5).json()


def _select_host(drv, ip):
    """Click the host row for the given IP via JS."""
    js(drv, """
        var rows = document.querySelectorAll('#hosts-body tr');
        for (var r of rows) {
            if ((r.dataset.hostIp || '') === arguments[0]) {
                r.querySelector('td').click();
                return;
            }
        }
    """, ip)
    time.sleep(2.0)


def _fire_ctx_on_host(drv, ip):
    """Dispatch contextmenu event on the host row for ip."""
    js(drv, """
        var rows = document.querySelectorAll('#hosts-body tr');
        for (var r of rows) {
            if ((r.dataset.hostIp || '') === arguments[0]) {
                var rect = r.getBoundingClientRect();
                r.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles: true, cancelable: true,
                    clientX: rect.left + 5, clientY: rect.top + 5
                }));
                return;
            }
        }
    """, ip)
    time.sleep(0.6)


def _click_ctx_menu_item(drv, label):
    """Click a button in #ctx-menu by its text label."""
    js(drv, """
        var btns = document.querySelectorAll('#ctx-menu button');
        for (var b of btns) {
            if (b.textContent.trim() === arguments[0]) { b.click(); return; }
        }
    """, label)


def _inject_nse_scripts(srv, ip, port_num):
    """Inject an l1ScriptObj row so the layer-2 dup check can see scripts."""
    from db.entities.l1script import l1ScriptObj
    repo = srv['logic'].activeProject.repositoryContainer
    host = repo.hostRepository.getHostByIP(ip)
    if not host:
        return
    from sqlalchemy import text
    session = srv['logic'].activeProject.database.session()
    port_row = session.execute(
        text("SELECT id FROM portObj WHERE hostId=:hid AND portId=:pid"),
        {'hid': host.id, 'pid': str(port_num)}
    ).fetchone()
    if not port_row:
        session.close()
        return
    script = l1ScriptObj(
        scriptId='vulners',
        output='vulners NSE output',
        portId=str(port_row[0]),
        hostId=str(host.id)
    )
    session.add(script)
    session.commit()
    session.close()


def _create_process(srv, ip, port='80', name='test-tool'):
    """Create and run a fast process for ip:port via the API, return proc_id."""
    r = _requests.post(f'{BASE}/api/processes/custom', json={
        'command': f'echo legion-test-output-{ip}',
        'host_ip': ip,
        'port': port,
        'protocol': 'tcp',
    }, timeout=10)
    proc_id = r.json().get('process_id')
    if proc_id:
        _wait_proc_done_api(proc_id, timeout=15)
    return proc_id

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def srv():
    import app.web.routes as _web_routes
    _web_routes._HB_TIMEOUT = 600
    _free_port(PORT)

    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server

    app, logic, wc = create_test_app()
    app.config['TESTING'] = False

    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED)
        xml_path = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output='')
    os.unlink(xml_path)

    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(2.0)

    yield {'app': app, 'logic': logic, 'wc': wc, 'url': BASE}

    httpd.shutdown()
    _web_routes._HB_TIMEOUT = 20


@pytest.fixture(scope='module')
def drv(srv):
    os.environ.pop('XAUTHORITY', None)
    os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)
    d.get(srv['url'])
    time.sleep(2.0)
    yield d
    d.quit()


# ══════════════════════════════════════════════════════════════════════════════
# 1. checkDuplicate user_triggered — v10.146
#    Right-clicking a tool on a port that has NSE script results stored must
#    still create a process (layer-2 bypass for user_triggered=True).
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckDuplicateUserTriggered:

    @pytest.fixture(scope='class', autouse=True)
    def setup(self, drv, srv):
        # Inject NSE script rows for IP_A port 80 — simulates a completed vulners scan
        _inject_nse_scripts(srv, IP_A, 80)
        drv.get(srv['url'])
        time.sleep(1.5)
        yield

    def test_nse_scripts_present_in_db(self, srv):
        """Confirm layer-2 condition exists: l1ScriptObj rows for IP_A:80."""
        from sqlalchemy import text
        session = srv['logic'].activeProject.database.session()
        count = session.execute(
            text("SELECT COUNT(*) FROM l1ScriptObj s "
                 "JOIN portObj p ON p.id=s.portId "
                 "JOIN hostObj h ON h.id=p.hostId "
                 "WHERE h.ip=:ip AND p.portId='80'"),
            {'ip': IP_A}
        ).fetchone()[0]
        session.close()
        assert count > 0, (
            f'No l1ScriptObj rows for {IP_A}:80 — test setup failed. '
            f'Layer-2 condition cannot be verified.'
        )

    def test_user_triggered_action_creates_process_despite_nse_scripts(self, srv):
        """
        POST /api/workspace/service-action with a valid action_index for IP_A:80/http.
        Before v10.146 this returned {reason:'skip'} because layer-2 saw NSE scripts.
        After the fix it must return a process_id.
        """
        # Resolve the action_index for 'Grab banner' on service 'http'
        items = _requests.get(
            f'{BASE}/api/menus/service?name=http', timeout=5
        ).json().get('items', [])
        banner_item = next((i for i in items if i.get('label') == 'Grab banner'), None)
        assert banner_item is not None, (
            "'Grab banner' not in /api/menus/service?name=http — "
            "check legion.conf PortActions include 'banner' for http service"
        )
        action_idx = banner_item['action_index']

        resp = _requests.post(f'{BASE}/api/workspace/service-action', json={
            'targets': [[IP_A, '80', 'tcp']],
            'action_index': action_idx,
        }, timeout=10).json()

        results = resp.get('result') or []
        assert results, f'No results in response: {resp}'
        result = results[0]
        assert result.get('reason') != 'skip', (
            f'Server returned skip — layer-2 is still blocking user-triggered actions. '
            f'Full result: {result}'
        )
        assert result.get('process_id') or result.get('pid'), (
            f'No process_id in result — action did not create a process. '
            f'Full result: {result}'
        )

        proc_id = result.get('process_id')
        if proc_id:
            # The tool runs against a test IP that may not respond — just verify
            # the process was created and is tracked by the server (not rejected).
            deadline = time.time() + 5
            while time.time() < deadline:
                procs = {p['id']: p for p in _snapshot().get('processes', [])}
                if proc_id in procs:
                    break
                time.sleep(0.5)
            procs = {p['id']: p for p in _snapshot().get('processes', [])}
            assert proc_id in procs, (
                f'Process {proc_id} not found in snapshot within 5s — '
                f'server may not have started it'
            )


# ══════════════════════════════════════════════════════════════════════════════
# 2. Tab scroll arrows — v10.155
#    ◀ and ▶ buttons exist in the DOM, clicking ▶ increases scrollLeft on
#    the right tab bar.
# ══════════════════════════════════════════════════════════════════════════════

class TestTabScrollArrows:

    @pytest.fixture(scope='class', autouse=True)
    def setup(self, drv, srv):
        drv.get(srv['url'])
        time.sleep(1.5)
        yield

    def test_left_arrow_present_in_dom(self, drv):
        """◀ button must exist in the DOM."""
        btn = drv.find_element(By.ID, 'right-tab-scroll-left')
        assert btn is not None, '◀ scroll button not found in DOM'

    def test_right_arrow_present_in_dom(self, drv):
        """▶ button must exist in the DOM."""
        btn = drv.find_element(By.ID, 'right-tab-scroll-right')
        assert btn is not None, '▶ scroll button not found in DOM'

    def test_left_arrow_initially_dimmed(self, drv):
        """At page load the bar is at leftmost position — ◀ opacity must be 0.3."""
        opacity = js(drv, """
            var b = document.getElementById('right-tab-scroll-left');
            return window.getComputedStyle(b).opacity;
        """)
        assert float(opacity) < 0.5, (
            f'◀ arrow opacity={opacity} at start, expected ~0.3 (dimmed at left edge)'
        )

    def test_right_arrow_click_scrolls_bar(self, drv, srv):
        """
        Create enough dynamic tabs to overflow the bar, then click ▶ and confirm
        scrollLeft increased. Uses processes so tabs are real (not injected HTML).
        """
        # Create several processes to generate dynamic tabs
        proc_ids = []
        for port in ('80', '22', '3306', '443', '8080', '8443'):
            r = _requests.post(f'{BASE}/api/processes/custom', json={
                'command': f'echo tab-overflow-test-{port}',
                'host_ip': IP_A,
                'port': port,
                'protocol': 'tcp',
            }, timeout=10).json()
            if r.get('process_id'):
                proc_ids.append(r['process_id'])

        for pid in proc_ids:
            _wait_proc_done_api(pid, timeout=15)

        # Select host A so dynamic tabs render
        _select_host(drv, IP_A)
        time.sleep(2.5)  # wait for renderDynamicToolTabs + snapshot poll

        scroll_before = js(drv, "return document.getElementById('right-tab-bar').scrollLeft;")

        # Click ▶
        js(drv, "document.getElementById('right-tab-scroll-right').click();")
        time.sleep(0.3)

        scroll_after = js(drv, "return document.getElementById('right-tab-bar').scrollLeft;")

        assert scroll_after > scroll_before, (
            f'▶ click did not scroll the tab bar: '
            f'scrollLeft before={scroll_before} after={scroll_after}. '
            f'Tab bar may not be overflowing — check that enough dynamic tabs exist.'
        )

    def test_left_arrow_click_scrolls_back(self, drv):
        """After scrolling right, clicking ◀ must decrease scrollLeft."""
        scroll_before = js(drv, "return document.getElementById('right-tab-bar').scrollLeft;")
        assert scroll_before > 0, 'Bar is at 0 — run after test_right_arrow_click_scrolls_bar'

        js(drv, "document.getElementById('right-tab-scroll-left').click();")
        time.sleep(0.3)

        scroll_after = js(drv, "return document.getElementById('right-tab-bar').scrollLeft;")
        assert scroll_after < scroll_before, (
            f'◀ click did not scroll left: '
            f'scrollLeft before={scroll_before} after={scroll_after}'
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Purge host UI — v10.156 + v10.157
#    Right-click → Purge Results → host row stays, ports/processes gone from DB
#    and from the UI immediately (plain-output cleared, dynamic tabs removed).
# ══════════════════════════════════════════════════════════════════════════════

class TestPurgeHostUI:

    @pytest.fixture(scope='class', autouse=True)
    def setup(self, drv, srv):
        drv.get(srv['url'])
        time.sleep(1.5)

        # Create a process for IP_B so a dynamic tab exists
        r = _requests.post(f'{BASE}/api/processes/custom', json={
            'command': 'echo purge-test-process',
            'host_ip': IP_B,
            'port': '80',
            'protocol': 'tcp',
        }, timeout=10).json()
        type(self)._proc_id = r.get('process_id')
        if type(self)._proc_id:
            _wait_proc_done_api(type(self)._proc_id, timeout=15)

        # Select IP_B so dynamic tabs render and plain-output can be populated
        _select_host(drv, IP_B)
        time.sleep(2.5)

        # JS click — process rows may be scroll-clipped (ElementNotInteractableException)
        if type(self)._proc_id:
            js(drv, """
                var tr = document.querySelector(
                    '#processes-body tr[data-process-id="' + arguments[0] + '"]');
                if (tr) tr.click();
            """, str(type(self)._proc_id))
            time.sleep(1.5)

        # Trigger purge via right-click on host row
        _fire_ctx_on_host(drv, IP_B)
        _click_ctx_menu_item(drv, 'Purge Results')
        time.sleep(2.5)  # wait for server + pollSnapshot

        yield

    def test_purge_host_row_still_present(self, drv):
        """Purge keeps the host row — only scan data is deleted."""
        rows = drv.find_elements(
            By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_B}"]'
        )
        assert len(rows) == 1, (
            f'Host row for {IP_B} should still be present after purge, '
            f'found {len(rows)} rows'
        )

    def test_purge_host_shows_zero_ports_in_snapshot(self):
        """Snapshot must show 0 open_ports for the purged host."""
        hosts = {h['ip']: h for h in _snapshot().get('hosts', [])}
        assert IP_B in hosts, f'{IP_B} not in snapshot hosts after purge'
        open_ports = hosts[IP_B].get('open_ports', -1)
        assert open_ports == 0, (
            f'{IP_B} still shows open_ports={open_ports} after purge; '
            f'portObj rows were not deleted'
        )

    def test_purge_processes_absent_from_snapshot(self):
        """Snapshot must have no processes for the purged host."""
        procs = [p for p in _snapshot().get('processes', []) if p['hostIp'] == IP_B]
        assert len(procs) == 0, (
            f'{len(procs)} processes for {IP_B} still in snapshot after purge: '
            f'{[p["name"] for p in procs]}'
        )

    def test_purge_plain_output_cleared(self, drv):
        """plain-output must be empty immediately after purge."""
        text = js(drv, "return (document.getElementById('plain-output') || {}).textContent || '';")
        assert text.strip() == '', (
            f'plain-output not cleared after purge; contains: {text[:100]!r}'
        )

    def test_purge_dynamic_tabs_removed(self, drv):
        """All dynamic tool tabs must be gone from the right tab bar."""
        dyn_tabs = drv.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        assert len(dyn_tabs) == 0, (
            f'{len(dyn_tabs)} dynamic tab(s) remain in tab bar after purge: '
            f'{[t.text for t in dyn_tabs]}'
        )

    def test_purge_selected_process_id_reset(self, drv):
        """L.selectedProcessId must be null — deselecting the process is part of the clear."""
        selected = js(drv, 'return L.selectedProcessId;')
        assert selected is None, (
            f'L.selectedProcessId={selected} after purge; expected null'
        )

    def test_purge_does_not_null_host_selection(self, drv):
        """Purge must not null L.selectedHostIp — only delete does that.
        The snapshot auto-select may pick either host; the key property is
        that a host is still selected (not null) after purge."""
        selected_ip = js(drv, 'return L.selectedHostIp;')
        assert selected_ip is not None, (
            f'L.selectedHostIp is null after purge — purge should not clear '
            f'the host selection (only delete does). Check the JS purge handler.'
        )

    def test_purge_db_portobj_deleted(self, srv):
        """portObj rows for IP_B must be gone from the DB."""
        from sqlalchemy import text
        session = srv['logic'].activeProject.database.session()
        host = srv['logic'].activeProject.repositoryContainer.hostRepository.getHostByIP(IP_B)
        if not host:
            session.close()
            pytest.skip(f'Host {IP_B} not found in DB — already deleted')
        count = session.execute(
            text('SELECT COUNT(*) FROM portObj WHERE hostId=:hid'),
            {'hid': host.id}
        ).fetchone()[0]
        session.close()
        assert count == 0, (
            f'{count} portObj rows remain for {IP_B} after purge; '
            f'the SQL transaction may have aborted (check for OperationalError in logs)'
        )

    def test_purge_db_process_deleted(self, srv):
        """process rows for IP_B must be gone from the DB."""
        from sqlalchemy import text
        session = srv['logic'].activeProject.database.session()
        count = session.execute(
            text("SELECT COUNT(*) FROM process WHERE hostIp=:ip"),
            {'ip': IP_B}
        ).fetchone()[0]
        session.close()
        assert count == 0, (
            f'{count} process rows remain for {IP_B} after purge; '
            f'DELETE FROM process WHERE hostIp=? may have been skipped'
        )

    def test_purge_db_hostobj_preserved(self, srv):
        """hostObj row for IP_B must still exist — purge keeps the host."""
        host = srv['logic'].activeProject.repositoryContainer.hostRepository.getHostByIP(IP_B)
        assert host is not None, (
            f'hostObj for {IP_B} was deleted — purge should NOT delete the host row'
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. Delete host UI — v10.154 + v10.156 + v10.157
#    Right-click → Delete → confirm → host row gone, all DB data gone,
#    UI cleared immediately (plain-output, dynamic tabs, host selection).
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteHostUI:

    @pytest.fixture(scope='class', autouse=True)
    def setup(self, drv, srv):
        drv.get(srv['url'])
        time.sleep(1.5)

        # Create a process for IP_A so a dynamic tab exists before delete
        r = _requests.post(f'{BASE}/api/processes/custom', json={
            'command': 'echo delete-test-process',
            'host_ip': IP_A,
            'port': '80',
            'protocol': 'tcp',
        }, timeout=10).json()
        type(self)._proc_id = r.get('process_id')
        if type(self)._proc_id:
            _wait_proc_done_api(type(self)._proc_id, timeout=15)

        # Select IP_A — makes dynamic tabs render and loads detail
        _select_host(drv, IP_A)
        time.sleep(2.5)

        # JS click — process rows may be scroll-clipped (ElementNotInteractableException)
        if type(self)._proc_id:
            js(drv, """
                var tr = document.querySelector(
                    '#processes-body tr[data-process-id="' + arguments[0] + '"]');
                if (tr) tr.click();
            """, str(type(self)._proc_id))
            time.sleep(1.5)

        # Right-click → Delete → accept confirm dialog
        _fire_ctx_on_host(drv, IP_A)
        _click_ctx_menu_item(drv, 'Delete')

        W(drv, 5).until(EC.alert_is_present())
        drv.switch_to.alert.accept()
        time.sleep(2.5)  # wait for server response + pollSnapshot

        yield

    def test_delete_host_row_gone(self, drv):
        """Host row for IP_A must not appear in #hosts-body after delete."""
        rows = drv.find_elements(
            By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_A}"]'
        )
        assert len(rows) == 0, (
            f'{len(rows)} host row(s) for {IP_A} still in DOM after delete'
        )

    def test_delete_other_host_unaffected(self, drv):
        """IP_B host row must still be present — delete is host-scoped."""
        rows = drv.find_elements(
            By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP_B}"]'
        )
        assert len(rows) == 1, (
            f'IP_B host row missing after deleting IP_A — '
            f'delete should not affect other hosts. Found {len(rows)} rows.'
        )

    def test_delete_absent_from_snapshot(self):
        """Snapshot must not list IP_A in hosts."""
        ips = {h['ip'] for h in _snapshot().get('hosts', [])}
        assert IP_A not in ips, (
            f'{IP_A} still in snapshot hosts after delete: {ips}'
        )

    def test_delete_processes_absent_from_snapshot(self):
        """Snapshot must have no processes with hostIp == IP_A."""
        procs = [p for p in _snapshot().get('processes', []) if p['hostIp'] == IP_A]
        assert len(procs) == 0, (
            f'{len(procs)} processes for {IP_A} still in snapshot: '
            f'{[p["name"] for p in procs]}'
        )

    def test_delete_plain_output_cleared(self, drv):
        """plain-output must be empty — v10.156 JS fix."""
        text = js(drv, "return (document.getElementById('plain-output') || {}).textContent || '';")
        assert text.strip() == '', (
            f'plain-output not cleared after delete; contains: {text[:120]!r}'
        )

    def test_delete_dynamic_tabs_removed(self, drv):
        """No dynamic tabs should remain in the right tab bar — v10.156 JS fix."""
        dyn_tabs = drv.find_elements(By.CSS_SELECTOR, '#right-tab-bar .dynamic-tab')
        assert len(dyn_tabs) == 0, (
            f'{len(dyn_tabs)} dynamic tab(s) remain after delete: '
            f'{[t.text for t in dyn_tabs]}'
        )

    def test_delete_selected_host_ip_not_deleted_host(self, drv):
        """L.selectedHostIp must not be the deleted host's IP after delete.
        The UI clears the selection on delete; the snapshot poll may then
        auto-select another remaining host — that is correct behaviour."""
        selected_ip = js(drv, 'return L.selectedHostIp;')
        assert selected_ip != IP_A, (
            f'L.selectedHostIp={selected_ip!r} after delete — '
            f'deleted host {IP_A} is still selected. '
            f'The JS delete handler must clear L.selectedHostIp.'
        )

    def test_delete_selected_process_id_reset(self, drv):
        """L.selectedProcessId must be null after delete — v10.156 JS fix."""
        selected_proc = js(drv, 'return L.selectedProcessId;')
        assert selected_proc is None, (
            f'L.selectedProcessId={selected_proc} after delete; expected null'
        )

    def test_delete_db_hostobj_gone(self, srv):
        """hostObj for IP_A must not exist in DB — v10.157 SQL fix."""
        host = srv['logic'].activeProject.repositoryContainer.hostRepository.getHostByIP(IP_A)
        assert host is None, (
            f'hostObj for {IP_A} still in DB after delete. '
            f'The DELETE transaction may have aborted (check for OperationalError — '
            f'this was the v10.157 process_matches column bug).'
        )

    def test_delete_db_portobj_gone(self, srv):
        """portObj rows for IP_A must be gone — confirms transaction completed."""
        from sqlalchemy import text
        session = srv['logic'].activeProject.database.session()
        count = session.execute(
            text("SELECT COUNT(*) FROM portObj p "
                 "JOIN hostObj h ON h.id=p.hostId WHERE h.ip=:ip"),
            {'ip': IP_A}
        ).fetchone()[0]
        session.close()
        assert count == 0, (
            f'{count} portObj rows for {IP_A} remain after delete. '
            f'If this fails alongside test_delete_db_hostobj_gone it confirms '
            f'the entire transaction aborted.'
        )

    def test_delete_db_process_gone(self, srv):
        """process rows for IP_A must be gone from DB."""
        from sqlalchemy import text
        session = srv['logic'].activeProject.database.session()
        count = session.execute(
            text("SELECT COUNT(*) FROM process WHERE hostIp=:ip"),
            {'ip': IP_A}
        ).fetchone()[0]
        session.close()
        assert count == 0, (
            f'{count} process rows for {IP_A} remain in DB after delete'
        )

    def test_delete_db_process_matches_gone(self, srv):
        """process_matches rows for IP_A must be gone — v10.157 column fix."""
        from sqlalchemy import text
        session = srv['logic'].activeProject.database.session()
        count = session.execute(
            text("SELECT COUNT(*) FROM process_matches WHERE hostIp=:ip"),
            {'ip': IP_A}
        ).fetchone()[0]
        session.close()
        assert count == 0, (
            f'{count} process_matches rows for {IP_A} remain after delete. '
            f'DELETE FROM process_matches WHERE hostIp=? was not executed. '
            f'(v10.157 fix: column is hostIp, not process_id)'
        )
