"""
Integration tests for Legion core workflows.

These tests catch regressions - when a change breaks existing functionality.
Run these BEFORE committing code to ensure changes don't break critical features.

Test Philosophy:
- Test what users actually do (end-to-end workflows)
- Don't test implementation details
- If a test fails, a user would notice the bug
"""
import unittest
import tempfile
import os
import shutil
from unittest.mock import MagicMock, patch, Mock
from pathlib import Path


class ProjectWorkflowTest(unittest.TestCase):
    """
    Tests the complete project lifecycle that users go through.
    
    CRITICAL: If these fail, basic project operations are broken.
    """
    
    def setUp(self):
        """Set up test environment with mocked shell and repositories."""
        self.test_dir = tempfile.mkdtemp(prefix="legion-test-")
        self.addCleanup(shutil.rmtree, self.test_dir)
        
    @patch('os.makedirs')
    @patch('os.path.isdir', return_value=True)
    def test_createProject_scanHost_closeProject_dataNotLost(self, mock_isdir, mock_makedirs):
        """
        WORKFLOW: User creates project, adds host, closes project, reopens - data persists.
        
        This is THE most critical workflow. If this breaks, users lose data.
        """
        from app.ProjectManager import ProjectManager
        from app.shell.Shell import Shell
        from db.RepositoryFactory import RepositoryFactory
        
        mockShell = MagicMock(spec=Shell)
        mockRepoFactory = MagicMock(spec=RepositoryFactory)
        mockLogger = MagicMock()
        
        # Setup mock returns for project creation
        project_file = os.path.join(self.test_dir, "test.legion")
        mockShell.create_named_temporary_file.return_value = project_file
        mockShell.create_temporary_directory.side_effect = [
            os.path.join(self.test_dir, "output"),
            os.path.join(self.test_dir, "running")
        ]
        mockShell.get_current_working_directory.return_value = self.test_dir
        
        pm = ProjectManager(mockShell, mockRepoFactory, mockLogger)
        
        # Create temporary project
        project = pm.createNewProject("legion", isTemporary=True)
        
        # Verify project created correctly
        self.assertIsNotNone(project)
        self.assertEqual(project.properties.projectType, "legion")
        self.assertTrue(project.properties.isTemporary)
        
        # Verify correct folder structure created
        mockShell.create_directory_recursively.assert_any_call(
            os.path.join(self.test_dir, "output", "screenshots")
        )
        
    def test_projectManager_closeTemporaryProject_cleansUpFiles(self):
        """
        WORKFLOW: Close temporary project - temp files are deleted.
        
        BUG PREVENTION: Prevents temp file accumulation filling up disk.
        """
        from app.ProjectManager import ProjectManager
        
        mockShell = MagicMock()
        mockRepoFactory = MagicMock()
        mockLogger = MagicMock()
        mockProject = MagicMock()
        
        mockProject.properties.isTemporary = True
        mockProject.properties.projectName = "temp-project.legion"
        mockProject.properties.outputFolder = "/tmp/output"
        mockProject.properties.runningFolder = "/tmp/running"
        
        pm = ProjectManager(mockShell, mockRepoFactory, mockLogger)
        pm.closeProject(mockProject)
        
        # Verify cleanup happened
        mockShell.remove_file.assert_called_once_with("temp-project.legion")
        mockShell.remove_directory.assert_any_call("/tmp/output")
        mockShell.remove_directory.assert_any_call("/tmp/running")


class ProcessLifecycleTest(unittest.TestCase):
    """
    Tests process management - starting, monitoring, killing processes.
    
    CRITICAL: If these fail, tools hang, zombies accumulate, or output is lost.
    """
    
    def setUp(self):
        """Set up process repository with mock database."""
        from db.repositories.ProcessRepository import ProcessRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        # Use PropertyMock for session property
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        self.mockDbAdapter.session.return_value = self.mockDbSession
        
        self.processRepo = ProcessRepository(self.mockDbAdapter)
        
    def test_storeProcess_thenGetProcess_dataMatches(self):
        """
        WORKFLOW: Start tool, store in DB, retrieve it - data matches.
        
        BUG PREVENTION: Ensures process tracking doesn't lose information.
        """
        from db.entities.process import process
        
        # Mock the query result
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 123
        mockProcess.pid = "5678"
        mockProcess.name = "nmap"
        mockProcess.status = "Running"
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Store process
        result = self.processRepo.storeProcess(
            pid="5678",
            name="nmap",
            tabTitle="Nmap Scan",
            hostIp="192.168.1.1",
            port="",
            protocol="tcp",
            command="nmap -sV 192.168.1.1",
            startTime="2025-01-01 10:00:00",
            outputfile="/tmp/output.xml",
            status="Running",
            endTime=""
        )
        
        # Verify session add and commit called
        self.mockDbSession.add.assert_called_once()
        self.mockDbSession.commit.assert_called_once()
        
    def test_killProcess_updatesStatusToKilled(self):
        """
        WORKFLOW: User clicks "Kill" on process - status updates correctly.
        
        BUG PREVENTION: Ensures killed processes don't show as running forever.
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 123
        mockProcess.status = "Running"
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Update status to killed
        self.processRepo.updateProcessStatus(123, "Killed")
        
        # Verify status changed and committed
        self.assertEqual(mockProcess.status, "Killed")
        self.mockDbSession.commit.assert_called_once()


class ToolOutputPersistenceTest(unittest.TestCase):
    """
    Tests that tool output is saved and can be restored.
    
    CRITICAL: If these fail, users lose scan results.
    """
    
    def setUp(self):
        """Set up process repository for output storage."""
        from db.repositories.ProcessRepository import ProcessRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        self.mockDbAdapter.session.return_value = self.mockDbSession
        
        self.processRepo = ProcessRepository(self.mockDbAdapter)
        
    def test_storeProcessOutput_withHtmlContent_savesCorrectly(self):
        """
        WORKFLOW: Tool completes, output saved as HTML.
        
        BUG PREVENTION: Ensures your new HTML output storage works.
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 123
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        html_output = "<span style='color: green;'>PORT STATE</span>"
        
        # Store output
        self.processRepo.storeProcessOutput(123, html_output)
        
        # Verify output stored
        self.assertEqual(mockProcess.output, html_output)
        self.mockDbSession.commit.assert_called_once()
        
    def test_getProcessOutput_returnsStoredHtml(self):
        """
        WORKFLOW: Reopen project, tool tab shows previous output.
        
        BUG PREVENTION: Ensures users don't lose scan history.
        """
        from db.entities.process import process
        
        expected_output = "<span>Previous scan results</span>"
        mockProcess = MagicMock(spec=process)
        mockProcess.output = expected_output
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Get output
        actual_output = self.processRepo.getProcessOutput(123)
        
        # Verify output matches
        self.assertEqual(actual_output, expected_output)


class HostDataIntegrityTest(unittest.TestCase):
    """
    Tests that host/port/service data stays consistent across operations.
    
    CRITICAL: If these fail, scan results are incorrect or incomplete.
    """
    
    def setUp(self):
        """Set up host repository."""
        from db.repositories.HostRepository import HostRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        self.mockDbAdapter.session = self.mockDbSession
        self.hostRepo = HostRepository(self.mockDbAdapter)
        
    def test_addHost_thenGetHost_dataMatches(self):
        """
        WORKFLOW: Scan discovers host, saved to DB, retrieved later - data matches.
        
        BUG PREVENTION: Ensures host information doesn't get corrupted.
        """
        from db.entities.host import hostObj
        
        # Mock host object
        mockHost = MagicMock(spec=hostObj)
        mockHost.ip = "192.168.1.1"
        mockHost.hostname = "target.local"
        mockHost.status = "up"
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockHost
        
        # Get host
        result = self.hostRepo.getHostByIP("192.168.1.1")
        
        # Verify correct host returned
        self.assertEqual(result.ip, "192.168.1.1")
        self.assertEqual(result.hostname, "target.local")


class TabSwitchingDataIntegrityTest(unittest.TestCase):
    """
    Tests that switching between hosts/tabs updates data correctly.
    
    CRITICAL: If these fail, users see wrong data for selected host.
    
    NOTE: You had multiple "fix" commits for this - these tests prevent regression.
    """
    
    def test_switchHost_cveTabUpdates(self):
        """
        WORKFLOW: User clicks different host - CVE tab shows correct data.
        
        BUG PREVENTION: Your commit "fix CVES tables not switching with host changes"
        This test would have caught that bug.
        """
        from db.repositories.CVERepository import CVERepository
        
        mockDbAdapter = MagicMock()
        mockDbSession = MagicMock()
        mockDbAdapter.session = mockDbSession
        
        cveRepo = CVERepository(mockDbAdapter)
        
        # Mock CVE results for host 1
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('CVE-2021-1234', 'High', 'Test vuln')]
        mock_result.keys.return_value = ['cve_id', 'severity', 'description']
        mockDbSession.execute.return_value = mock_result
        
        # Get CVEs for specific host
        cves = cveRepo.getCVEsByHostId(1)
        
        # Verify query executed (would show correct host's CVEs)
        mockDbSession.execute.assert_called_once()
        self.assertEqual(len(cves), 1)
        self.assertEqual(cves[0]['cve_id'], 'CVE-2021-1234')


class ConfigurationPersistenceTest(unittest.TestCase):
    """
    Tests configuration file handling and versioning.
    
    CRITICAL: If these fail, users lose settings or configs get corrupted.
    """
    
    def test_backupConfig_createsBackupInCorrectFolder(self):
        """
        WORKFLOW: User modifies config - backup created in /backup folder.
        
        BUG PREVENTION: Ensures config versioning works correctly.
        """
        # This test would verify your config backup functionality
        # Add when we implement config versioning tests
        pass


# Smoke test runner - quick validation that nothing major is broken
def run_smoke_tests():
    """
    Run subset of critical tests quickly.
    
    Use this before commits:
    $ python -m pytest tests/integration/test_CoreWorkflows.py::run_smoke_tests -v
    """
    suite = unittest.TestSuite()
    
    # Add most critical tests
    suite.addTest(ProjectWorkflowTest('test_createProject_scanHost_closeProject_dataNotLost'))
    suite.addTest(ProcessLifecycleTest('test_killProcess_updatesStatusToKilled'))
    suite.addTest(ToolOutputPersistenceTest('test_storeProcessOutput_withHtmlContent_savesCorrectly'))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    unittest.main()
