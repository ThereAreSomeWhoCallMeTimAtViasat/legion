#!/usr/bin/env python
"""
Critical Path Tests

Tests end-to-end user workflows that represent the most common and critical
usage patterns. These are the "happy paths" that users rely on daily —
if these break, the app is unusable.

Uses create_test_app() for full Flask + WebController + SQLite initialization.
"""

import unittest
import os
import sys
import time
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Nmap XML fixture — real scan result used across tests
FIXTURE_XML = os.path.join(os.path.dirname(__file__),
                           '../parsers/nmap-fixtures/valid-nmap-report.xml')

# Second host XML for isolation tests
_HOST_B_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nmaprun>
<nmaprun scanner="nmap" args="nmap -sV 10.0.0.1" start="1586997400"
         startstr="Wed Apr 15 20:36:40 2020" version="7.80" xmloutputversion="1.04">
    <scaninfo type="syn" protocol="tcp" numservices="1000" services="1-1000"/>
    <host starttime="1586997400" endtime="1586997400">
        <status state="up" reason="syn-ack" reason_ttl="0"/>
        <address addr="10.0.0.1" addrtype="ipv4"/>
        <hostnames/>
        <ports>
            <port protocol="tcp" portid="22">
                <state state="open" reason="syn-ack" reason_ttl="0"/>
                <service name="ssh" product="OpenSSH" version="8.0" conf="10"/>
            </port>
            <port protocol="tcp" portid="3306">
                <state state="open" reason="syn-ack" reason_ttl="0"/>
                <service name="mysql" product="MySQL" version="5.7" conf="10"/>
            </port>
        </ports>
        <times srtt="1000" rttvar="100" to="100000"/>
    </host>
    <runstats>
        <finished time="1586997401" elapsed="1.00" exit="success"/>
        <hosts up="1" down="0" total="1"/>
    </runstats>
</nmaprun>"""


def _import_xml(logic, xml_path):
    """Import an nmap XML file into the active project."""
    from app.importers.nmap_import import import_nmap_xml
    import_nmap_xml(project=logic.activeProject, xml_path=xml_path, output="")


def _wait_for_process(client, pid, timeout=30):
    """Poll snapshot until process reaches a terminal status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get('/api/snapshot').get_json()
        for p in snap.get('processes', []):
            if str(p.get('id')) == str(pid):
                if p.get('status') in ('Finished', 'Killed', 'Crashed'):
                    return p.get('status')
        time.sleep(0.5)
    return None


class TestCriticalPath_NewProjectWorkflow(unittest.TestCase):
    """
    CRITICAL PATH 1: New Project → Add Hosts → Scan → View Results

    User story: "I start Legion, create project, add targets, run nmap, see results"
    If this breaks, the entire app is unusable.
    """

    @classmethod
    def setUpClass(cls):
        from app.web.testhelper import create_test_app
        cls.app, cls.logic, cls.wc = create_test_app()
        cls.client = cls.app.test_client()

    def test_workflow_create_project_add_hosts_scan(self):
        """
        Import nmap XML (simulates scan completing) → host appears in snapshot
        with correct IP and ports discoverable via the host detail API.
        """
        _import_xml(self.logic, FIXTURE_XML)

        snap = self.client.get('/api/snapshot').get_json()
        hosts = snap.get('hosts', [])
        ips = [h['ip'] for h in hosts]
        self.assertIn('192.168.1.1', ips,
                      f"Host 192.168.1.1 not in snapshot after XML import. hosts={ips}")

        host_id = next(h['id'] for h in hosts if h['ip'] == '192.168.1.1')
        r = self.client.get(f'/api/workspace/hosts/{host_id}')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        ports = [str(p['port']) for p in data.get('ports', [])]
        self.assertIn('80', ports, f"Port 80 missing from host detail. ports={ports}")
        self.assertIn('443', ports, f"Port 443 missing from host detail. ports={ports}")


class TestCriticalPath_ProjectPersistence(unittest.TestCase):
    """
    CRITICAL PATH 2: Save Project → Close → Reopen → Data Intact

    User story: "I work on project all day, close Legion, reopen next day — all data there"
    If this breaks, users lose their work.
    """

    @classmethod
    def setUpClass(cls):
        from app.web.testhelper import create_test_app
        cls.app, cls.logic, cls.wc = create_test_app()
        cls.client = cls.app.test_client()
        cls.save_dir = tempfile.mkdtemp(prefix='legion_persist_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.save_dir, ignore_errors=True)

    def test_workflow_save_close_reopen_data_intact(self):
        """
        Add host via XML import → save project → reopen same file → host still present.
        """
        _import_xml(self.logic, FIXTURE_XML)

        # Verify host present before save
        snap = self.client.get('/api/snapshot').get_json()
        self.assertTrue(any(h['ip'] == '192.168.1.1' for h in snap.get('hosts', [])),
                        "Host not in project before save")

        # Save project to a real file
        save_path = os.path.join(self.save_dir, 'persist_test.legion')
        r = self.client.post('/api/project/save-as', json={'path': save_path})
        self.assertEqual(r.status_code, 200, f"save-as failed: {r.get_data(as_text=True)}")
        self.assertTrue(os.path.isfile(save_path), "Saved project file not found on disk")

        # Reopen the saved file
        r = self.client.post('/api/project/open', json={'path': save_path})
        self.assertEqual(r.status_code, 200, f"open failed: {r.get_data(as_text=True)}")

        # Verify host survived the save/reopen cycle
        snap = self.client.get('/api/snapshot').get_json()
        self.assertTrue(any(h['ip'] == '192.168.1.1' for h in snap.get('hosts', [])),
                        "Host 192.168.1.1 lost after save → reopen. Data persistence broken.")


class TestCriticalPath_MultiHostSwitching(unittest.TestCase):
    """
    CRITICAL PATH 3: Multiple Hosts → Switch Between → Data Doesn't Mix

    User story: "I work on multiple hosts, ports/notes stay with the right host"
    This is the most common regression source.
    """

    @classmethod
    def setUpClass(cls):
        from app.web.testhelper import create_test_app
        cls.app, cls.logic, cls.wc = create_test_app()
        cls.client = cls.app.test_client()

        # Import host A (192.168.1.1 — ports 53, 80, 139, 443, 445)
        _import_xml(cls.logic, FIXTURE_XML)

        # Import host B (10.0.0.1 — ports 22, 3306)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(_HOST_B_XML)
            cls.host_b_xml = f.name
        _import_xml(cls.logic, cls.host_b_xml)

        snap = cls.client.get('/api/snapshot').get_json()
        cls.hosts = {h['ip']: h['id'] for h in snap.get('hosts', [])}

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'host_b_xml') and os.path.exists(cls.host_b_xml):
            os.unlink(cls.host_b_xml)

    def test_workflow_switch_hosts_data_isolated(self):
        """
        Host A's ports must not appear in host B's detail, and vice versa.
        """
        self.assertIn('192.168.1.1', self.hosts, "Host A not in project")
        self.assertIn('10.0.0.1', self.hosts, "Host B not in project")

        # Host A should have web ports, not SSH/MySQL
        r_a = self.client.get(f'/api/workspace/hosts/{self.hosts["192.168.1.1"]}')
        self.assertEqual(r_a.status_code, 200)
        ports_a = {str(p['port']) for p in r_a.get_json().get('ports', [])}
        self.assertIn('80', ports_a, "Host A missing port 80")
        self.assertNotIn('22', ports_a, "Host A has host B's port 22 — DATA MIXING BUG")
        self.assertNotIn('3306', ports_a, "Host A has host B's port 3306 — DATA MIXING BUG")

        # Host B should have SSH/MySQL, not web ports
        r_b = self.client.get(f'/api/workspace/hosts/{self.hosts["10.0.0.1"]}')
        self.assertEqual(r_b.status_code, 200)
        ports_b = {str(p['port']) for p in r_b.get_json().get('ports', [])}
        self.assertIn('22', ports_b, "Host B missing port 22")
        self.assertIn('3306', ports_b, "Host B missing port 3306")
        self.assertNotIn('80', ports_b, "Host B has host A's port 80 — DATA MIXING BUG")
        self.assertNotIn('443', ports_b, "Host B has host A's port 443 — DATA MIXING BUG")

    def test_workflow_notes_isolated_by_host(self):
        """
        Notes saved for host A must not appear when querying host B.
        """
        self.assertIn('192.168.1.1', self.hosts)
        self.assertIn('10.0.0.1', self.hosts)

        note_a = "Critical finding on host A — do not mix"
        r = self.client.post(
            f'/api/workspace/hosts/{self.hosts["192.168.1.1"]}/note',
            json={'note': note_a}
        )
        self.assertEqual(r.status_code, 200, "Failed to save note for host A")

        # Host A's detail should reflect the note
        r_a = self.client.get(f'/api/workspace/hosts/{self.hosts["192.168.1.1"]}')
        host_a_data = r_a.get_json()
        self.assertIn(note_a, str(host_a_data),
                      "Note not found in host A detail after saving")

        # Host B must not have host A's note
        r_b = self.client.get(f'/api/workspace/hosts/{self.hosts["10.0.0.1"]}')
        self.assertNotIn(note_a, str(r_b.get_json()),
                         "Host A's note appeared in host B detail — DATA MIXING BUG")


class TestCriticalPath_ToolExecution(unittest.TestCase):
    """
    CRITICAL PATH 4: Run Tool → Output Stored → Output Retrievable

    User story: "I run a tool, output shows in the tab, I can come back to it later"
    If this breaks, all tool output is lost.
    """

    @classmethod
    def setUpClass(cls):
        from app.web.testhelper import create_test_app
        cls.app, cls.logic, cls.wc = create_test_app()
        cls.client = cls.app.test_client()

    def test_workflow_run_tool_output_persists(self):
        """
        Run echo via wc.runCommand → process appears in snapshot →
        output is retrievable via /api/processes/{id}/output.
        """
        marker = 'critical_path_tool_output_marker_12345'
        outfile = tempfile.mktemp(prefix='legion_cp4_')

        result = self.wc.runCommand(
            command=f'echo {marker}',
            name='echo',
            tabTitle='CP4 echo test',
            hostIp='127.0.0.1',
            port='',
            protocol='tcp',
            outputfile=outfile
        )
        self.assertIsNotNone(result, "runCommand returned None")
        pid = result.get('process_id')
        self.assertIsNotNone(pid, "No process_id returned from runCommand")

        # Wait for completion
        status = _wait_for_process(self.client, pid, timeout=20)
        self.assertIn(status, ('Finished', 'Crashed'),
                      f"Process {pid} did not finish within timeout (status={status})")

        # Output must be retrievable
        r = self.client.get(f'/api/processes/{pid}/output')
        self.assertEqual(r.status_code, 200)
        output = r.get_json().get('output', '') or r.get_json().get('output_chunk', '')
        self.assertIn(marker, output,
                      f"Tool output not retrievable. Got: {output[:200]!r}")


class TestCriticalPath_ErrorRecovery(unittest.TestCase):
    """
    CRITICAL PATH 5: Invalid Input → Graceful Handling → No Data Corruption

    User story: "I accidentally enter bad input, app shows error but doesn't crash
    and my existing scan data is still intact"
    """

    @classmethod
    def setUpClass(cls):
        from app.web.testhelper import create_test_app
        cls.app, cls.logic, cls.wc = create_test_app()
        cls.client = cls.app.test_client()
        # Pre-populate with valid data to verify it survives bad input
        _import_xml(cls.logic, FIXTURE_XML)

    def test_workflow_invalid_ip_rejected_data_intact(self):
        """
        POST /api/nmap/scan with shell-injection IP → 400 response →
        existing host still in snapshot (no data corruption).
        """
        # Verify baseline — valid host exists
        snap_before = self.client.get('/api/snapshot').get_json()
        self.assertTrue(any(h['ip'] == '192.168.1.1' for h in snap_before.get('hosts', [])),
                        "Test setup failed: 192.168.1.1 not in snapshot before bad-input test")

        # Submit invalid/injection IP
        bad_inputs = [
            '192.168.1.1; rm -rf /',
            'not-an-ip',
            '999.999.999.999',
            '',
            '../etc/passwd',
        ]
        for bad_ip in bad_inputs:
            r = self.client.post('/api/nmap/scan', json={'target': bad_ip})
            self.assertIn(r.status_code, (400, 422),
                          f"Bad IP {bad_ip!r} was not rejected (status={r.status_code})")

        # Existing data must be intact
        snap_after = self.client.get('/api/snapshot').get_json()
        self.assertTrue(any(h['ip'] == '192.168.1.1' for h in snap_after.get('hosts', [])),
                        "Valid host 192.168.1.1 disappeared after invalid input submissions")

    def test_workflow_invalid_brute_input_rejected(self):
        """
        POST /api/brute/run with no credentials → 400 →
        route validates input before launching Hydra.
        """
        r = self.client.post('/api/brute/run', json={
            'ip': '192.168.1.1', 'port': '22', 'service': 'ssh',
            'username': '', 'password': '', 'userlist': '', 'passlist': '', 'combo': ''
        })
        self.assertEqual(r.status_code, 400,
                         "brute/run must return 400 when no credentials supplied")

    def test_workflow_snapshot_always_returns(self):
        """
        /api/snapshot must return 200 even after bad requests have been made.
        If the server crashes or returns 500 on snapshot, the entire UI breaks.
        """
        r = self.client.get('/api/snapshot')
        self.assertEqual(r.status_code, 200, "/api/snapshot returned non-200 after error tests")
        data = r.get_json()
        self.assertIn('hosts', data, "snapshot missing 'hosts' key")
        self.assertIn('processes', data, "snapshot missing 'processes' key")


if __name__ == '__main__':
    unittest.main(verbosity=2)
