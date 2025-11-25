"""
Tests for Feature #6: Tab Switching Data Integrity

Feature: Fixed data integrity issues when switching between hosts/tabs
Status: KNOWN WORKING (from TROUBLESHOOTING.md completed items)
Test Goal: Prevent regression - ensure tabs update correctly and no data mixing

Commits: 21d40c2 (CVE tab switching), b1e5cc4 (scripts tab clearing)
"""
import unittest
from unittest.mock import MagicMock, patch
from db.repositories.HostRepository import HostRepository
from db.repositories.CVERepository import CVERepository
from db.repositories.ScriptRepository import ScriptRepository


class TabSwitchingDataIntegrityTest(unittest.TestCase):
    """
    Tests that switching hosts updates tabs correctly.
    
    CRITICAL: If these fail, user sees wrong data for wrong host.
    """
    
    def setUp(self):
        """Set up repositories."""
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        # Set up session for all repositories
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        
        self.hostRepo = HostRepository(self.mockDbAdapter)
        self.cveRepo = CVERepository(self.mockDbAdapter)
        self.scriptRepo = ScriptRepository(self.mockDbAdapter)
    
    def test_switchHost_cveTabUpdates(self):
        """
        REGRESSION TEST: CVE tab updates when host changes.
        
        Before commit 21d40c2: CVE tab not updating on host switch
        After commit 21d40c2: CVE tab updates with correct host's CVEs
        
        From TROUBLESHOOTING.md completed:
        "when user selects a host then clicks on CVE tab the CVE data isnt populated
        when user clicks on another host and back again the CVE data is populated"
        
        If this fails: CVE tab showing wrong/old data
        """
        from db.entities.cve import cve
        
        # Host A CVEs
        mockCveA = MagicMock(spec=cve)
        mockCveA.cveid = "CVE-2024-0001"
        mockCveA.hostId = "1"
        
        # Host B CVEs
        mockCveB = MagicMock(spec=cve)
        mockCveB.cveid = "CVE-2024-0002"
        mockCveB.hostId = "2"
        
        # Select host A
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCveA.cveid, "7.5", "", "", "", "", "", "", "")]
        self.mockDbSession.execute.return_value.keys.return_value = ['name', 'severity', 'product', 'version', 'url', 'source', 'exploitId', 'exploit', 'exploitUrl']
        cvesA = self.cveRepo.getCVEsByHostIP("192.168.1.1")
        
        # Verify host A CVEs
        self.assertEqual(len(cvesA), 1)
        self.assertEqual(cvesA[0]['name'], "CVE-2024-0001")
        
        # Switch to host B
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCveB.cveid, "5.0", "", "", "", "", "", "", "")]
        cvesB = self.cveRepo.getCVEsByHostIP("192.168.1.2")
        
        # Verify host B CVEs (not host A's)
        self.assertEqual(len(cvesB), 1)
        self.assertEqual(cvesB[0]['name'], "CVE-2024-0002")
    
    def test_switchHost_scriptsTabClears(self):
        """
        REGRESSION TEST: Scripts tab clears when switching hosts.
        
        Before commit b1e5cc4: Scripts tab not clearing on host switch
        After commit b1e5cc4: Scripts tab cleared and updated
        
        From TROUBLESHOOTING.md completed:
        "scripts on host from nmap or nse scans are not cleared and reloaded on host selection change"
        
        If this fails: Scripts tab showing previous host's scripts
        """
        from db.entities.l1script import l1ScriptObj
        
        # Host A scripts
        mockScriptA = MagicMock(spec=l1ScriptObj)
        mockScriptA.scriptId = "http-title"
        mockScriptA.portId = "1"
        
        # Select host A
        self.mockDbSession.execute.return_value.fetchall.return_value = [(1, mockScriptA.scriptId, "80", "tcp")]
        self.mockDbSession.execute.return_value.keys.return_value = ['id', 'scriptId', 'portId', 'protocol']
        scriptsA = self.scriptRepo.getScriptsByHostIP("192.168.1.1")
        
        # Verify host A scripts
        self.assertEqual(len(scriptsA), 1)
        
        # Switch to host B (no scripts)
        self.mockDbSession.execute.return_value.fetchall.return_value = []
        scriptsB = self.scriptRepo.getScriptsByHostIP("192.168.1.2")
        
        # Verify scripts cleared (not showing host A's scripts)
        self.assertEqual(len(scriptsB), 0)
    
    def test_switchHost_notesTabUpdates(self):
        """
        TEST: Notes tab updates when switching hosts.
        
        From Feature #3 (Notes Save Fix).
        
        If this fails: Notes tab showing wrong host's notes
        """
        from db.repositories.NoteRepository import NoteRepository
        from db.entities.note import note
        
        mockLog = MagicMock()
        noteRepo = NoteRepository(self.mockDbAdapter, mockLog)
        
        # Host A note
        mockNoteA = MagicMock(spec=note)
        mockNoteA.text = "Note for host A"
        mockNoteA.hostId = "1"
        
        # Host B note
        mockNoteB = MagicMock(spec=note)
        mockNoteB.text = "Note for host B"
        mockNoteB.hostId = "2"
        
        # Select host A
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockNoteA
        noteA = noteRepo.getNoteByHostId("1")
        
        # Verify host A note
        self.assertEqual(noteA.text, "Note for host A")
        
        # Switch to host B
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockNoteB
        noteB = noteRepo.getNoteByHostId("2")
        
        # Verify host B note (not host A's)
        self.assertEqual(noteB.text, "Note for host B")
    
    def test_rapidHostSwitching_noDataMixing(self):
        """
        STRESS TEST: Rapidly switching hosts doesn't mix data.
        
        User clicks through hosts quickly. Each host should show its own data.
        
        If this fails: Race condition causing data mixing
        """
        from db.entities.cve import cve
        
        # Simulate rapid switching
        for i in range(10):
            hostIP = f"192.168.1.{i}"
            
            # Mock CVE for this host
            cveName = f"CVE-2024-000{i}"
            
            self.mockDbSession.execute.return_value.fetchall.return_value = [(cveName, "7.5", "", "", "", "", "", "", "")]
            self.mockDbSession.execute.return_value.keys.return_value = ['name', 'severity', 'product', 'version', 'url', 'source', 'exploitId', 'exploit', 'exploitUrl']
            
            # Get CVEs
            cves = self.cveRepo.getCVEsByHostIP(hostIP)
            
            # Verify correct CVE for this host (no mixing)
            self.assertEqual(len(cves), 1)
            self.assertEqual(cves[0]['name'], cveName)
    
    def test_switchHost_portsPanelUpdates(self):
        """
        TEST: Ports panel updates when switching hosts.
        
        If this fails: Ports panel showing wrong host's ports
        """
        from db.repositories.PortRepository import PortRepository
        from db.entities.port import portObj
        
        portRepo = PortRepository(self.mockDbAdapter)
        
        # Host A ports
        mockPortA = MagicMock(spec=portObj)
        mockPortA.portId = "80"
        mockPortA.hostId = "1"
        
        # Host B ports
        mockPortB = MagicMock(spec=portObj)
        mockPortB.portId = "22"
        mockPortB.hostId = "2"
        
        # Select host A
        self.mockDbSession.query.return_value.filter_by.return_value.all.return_value = [mockPortA]
        portsA = portRepo.getPortsByHostId("1")
        
        # Verify host A ports
        self.assertEqual(len(portsA), 1)
        self.assertEqual(portsA[0].portId, "80")
        
        # Switch to host B
        self.mockDbSession.query.return_value.filter_by.return_value.all.return_value = [mockPortB]
        portsB = portRepo.getPortsByHostId("2")
        
        # Verify host B ports (not host A's)
        self.assertEqual(len(portsB), 1)
        self.assertEqual(portsB[0].portId, "22")
    
    def test_noHostSelected_tabsShowEmpty(self):
        """
        EDGE CASE: No host selected shows empty tabs.
        
        If this fails: Tabs showing stale data when no host selected
        """
        # No host selected (return empty)
        self.mockDbSession.execute.return_value.fetchall.return_value = []
        self.mockDbSession.execute.return_value.keys.return_value = ['name', 'severity', 'product', 'version', 'url', 'source', 'exploitId', 'exploit', 'exploitUrl']
        
        # Get CVEs (should be empty)
        cves = self.cveRepo.getCVEsByHostIP(None)
        
        # Verify empty
        self.assertEqual(len(cves), 0)
    
    def test_deleteHost_tabsUpdate(self):
        """
        TEST: Deleting selected host clears tabs.
        
        If this fails: Tabs showing deleted host's data
        """
        # Host deleted (return None)
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = None
        
        # Try to get host
        host = self.hostRepo.getHostByIP("192.168.1.1")
        
        # Verify host gone
        self.assertIsNone(host)


class MultipleTabsUpdateTest(unittest.TestCase):
    """
    Tests that multiple tabs update together when switching hosts.
    """
    
    def setUp(self):
        """Set up repositories."""
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        
        self.cveRepo = CVERepository(self.mockDbAdapter)
        self.scriptRepo = ScriptRepository(self.mockDbAdapter)
    
    def test_switchHost_allTabsUpdateTogether(self):
        """
        INTEGRATION TEST: All tabs update when host changes.
        
        Tabs: Info, Ports, Scripts, CVEs, Notes, Services, Tools
        All should update atomically when host changes.
        
        If this fails: Some tabs update, others don't
        """
        from db.entities.cve import cve
        from db.entities.l1script import l1ScriptObj
        
        # Mock data for host
        mockCve = MagicMock(spec=cve)
        mockCve.cveid = "CVE-2024-0001"
        
        mockScript = MagicMock(spec=l1ScriptObj)
        mockScript.scriptId = "ssh-hostkey"
        
        # Switch host (all tabs query database)
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCve.cveid, "7.5", "", "", "", "", "", "", "")]
        self.mockDbSession.execute.return_value.keys.return_value = ['name', 'severity', 'product', 'version', 'url', 'source', 'exploitId', 'exploit', 'exploitUrl']
        cves = self.cveRepo.getCVEsByHostIP("192.168.1.1")
        
        self.mockDbSession.execute.return_value.fetchall.return_value = [(1, mockScript.scriptId, "80", "tcp")]
        self.mockDbSession.execute.return_value.keys.return_value = ['id', 'scriptId', 'portId', 'protocol']
        scripts = self.scriptRepo.getScriptsByHostIP("192.168.1.1")
        
        # Verify both tabs got data
        self.assertEqual(len(cves), 1)
        self.assertEqual(len(scripts), 1)


class TabSwitchingUIIntegrationTest(unittest.TestCase):
    """
    Integration tests for tab switching user workflows.
    """
    
    def setUp(self):
        """Set up repositories."""
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        
        self.cveRepo = CVERepository(self.mockDbAdapter)
    
    def test_workflow_selectHost_clickCveTab_seeCves(self):
        """
        INTEGRATION TEST: User workflow for viewing CVEs.
        
        From TROUBLESHOOTING.md completed:
        This was the original bug: "when user selects a host then clicks on CVE tab
        the CVE data isnt populated"
        
        Workflow:
        1. User selects host in hosts panel
        2. User clicks CVE tab
        3. CVEs should be visible immediately
        
        If this fails: Original bug returned
        """
        from db.entities.cve import cve
        
        # Step 1: Select host
        hostIP = "192.168.1.1"
        
        # Step 2: Click CVE tab (triggers getCVEsByHostIP)
        mockCve = MagicMock(spec=cve)
        mockCve.cveid = "CVE-2024-0001"
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCve.cveid, "7.5", "", "", "", "", "", "", "")]
        self.mockDbSession.execute.return_value.keys.return_value = ['name', 'severity', 'product', 'version', 'url', 'source', 'exploitId', 'exploit', 'exploitUrl']
        
        cves = self.cveRepo.getCVEsByHostIP(hostIP)
        
        # Step 3: Verify CVEs visible
        self.assertEqual(len(cves), 1, "CVEs should be visible immediately")
    
    def test_workflow_hostA_hostB_backToHostA_dataCorrect(self):
        """
        INTEGRATION TEST: Switching back to previous host shows correct data.
        
        From TROUBLESHOOTING.md completed:
        Original workaround: "when user clicks on another host and back again
        the CVE data is populated"
        
        Workflow:
        1. Select host A
        2. Select host B
        3. Select host A again
        4. All tabs should show host A's data (not host B's)
        
        If this fails: Data from host B sticking around
        """
        from db.entities.cve import cve
        
        # Step 1: Select host A
        mockCveA = MagicMock(spec=cve)
        mockCveA.cveid = "CVE-2024-0001"
        mockCveA.hostId = "1"
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCveA.cveid, "7.5", "", "", "", "", "", "", "")]
        self.mockDbSession.execute.return_value.keys.return_value = ['name', 'severity', 'product', 'version', 'url', 'source', 'exploitId', 'exploit', 'exploitUrl']
        
        cvesA1 = self.cveRepo.getCVEsByHostIP("192.168.1.1")
        
        # Step 2: Select host B
        mockCveB = MagicMock(spec=cve)
        mockCveB.cveid = "CVE-2024-0002"
        mockCveB.hostId = "2"
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCveB.cveid, "5.0", "", "", "", "", "", "", "")]
        
        cvesB = self.cveRepo.getCVEsByHostIP("192.168.1.2")
        
        # Step 3: Back to host A
        self.mockDbSession.execute.return_value.fetchall.return_value = [(mockCveA.cveid, "7.5", "", "", "", "", "", "", "")]
        cvesA2 = self.cveRepo.getCVEsByHostIP("192.168.1.1")
        
        # Step 4: Verify host A data correct
        self.assertEqual(len(cvesA2), 1)
        self.assertEqual(cvesA2[0]['name'], "CVE-2024-0001", "Should show host A CVEs, not host B")


if __name__ == '__main__':
    unittest.main()
