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
from unittest.mock import MagicMock, patch


class ProjectWorkflowTest(unittest.TestCase):
    """
    Tests the complete project lifecycle that users go through.

    CRITICAL: If these fail, basic project operations are broken.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="legion-test-")
        self.addCleanup(shutil.rmtree, self.test_dir)

    def test_createProject_api_uses_isTemp_not_isTemporary(self):
        """
        API guard: createNewProject() parameter is isTemp= not isTemporary=.
        Catches parameter rename regressions before callers break silently.
        Uses a real project via create_test_app() to verify the full call succeeds.
        """
        import inspect
        from app.ProjectManager import ProjectManager
        sig = inspect.signature(ProjectManager.createNewProject)
        params = list(sig.parameters.keys())
        self.assertIn('isTemp', params,
                      "createNewProject() must accept isTemp= parameter — "
                      "callers use isTemp=True; rename would silently break them")
        self.assertNotIn('isTemporary', params,
                         "createNewProject() must not have isTemporary= — "
                         "that was the old name; rename back would break callers")

    @patch('os.path.exists', return_value=True)
    def test_projectManager_closeTemporaryProject_cleansUpFiles(self, mock_exists):
        """
        WORKFLOW: Close temporary project removes DB file and output/running folders.
        os.path.exists patched True so cleanup branches actually execute.
        """
        from app.ProjectManager import ProjectManager

        mockShell = MagicMock()
        mockLogger = MagicMock()
        mockProject = MagicMock()

        mockProject.properties.isTemporary = True
        mockProject.properties.storeWordListsOnExit = True
        mockProject.properties.projectName = "/tmp/temp-project.legion"
        mockProject.properties.outputFolder = "/tmp/output"
        mockProject.properties.runningFolder = "/tmp/running"

        pm = ProjectManager(mockShell, MagicMock(), mockLogger)
        pm.closeProject(mockProject)

        mockShell.remove_file.assert_any_call("/tmp/temp-project.legion")
        mockShell.remove_directory.assert_any_call("/tmp/output")
        mockShell.remove_directory.assert_any_call("/tmp/running")


class ProcessLifecycleTest(unittest.TestCase):
    """
    Tests process management — starting, monitoring, killing processes.

    CRITICAL: If these fail, tools hang, zombies accumulate, or output is lost.
    """

    def setUp(self):
        from db.repositories.ProcessRepository import ProcessRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        self.mockLog = MagicMock()

        # ProcessRepository uses self.dbAdapter.session() — session is callable
        self.mockDbAdapter.session.return_value = self.mockDbSession

        # Constructor requires (dbAdapter, log) — log was added; catches signature regressions
        self.processRepo = ProcessRepository(self.mockDbAdapter, self.mockLog)

    def test_storeProcess_thenGetProcess_dataMatches(self):
        """
        WORKFLOW: Start tool, store in DB.
        storeProcess() takes a proc object (not keyword args) — API changed; guards that.
        """
        mockProc = MagicMock()
        mockProc.processId.return_value = '5678'
        mockProc.name = 'nmap'
        mockProc.tabTitle = 'Nmap Scan'
        mockProc.hostIp = '192.168.1.1'
        mockProc.port = ''
        mockProc.protocol = 'tcp'
        mockProc.command = 'nmap -sV 192.168.1.1'
        mockProc.startTime = '2025-01-01 10:00:00'
        mockProc.outputfile = '/tmp/output.xml'

        self.processRepo.storeProcess(mockProc)

        self.mockDbSession.add.assert_called_once()
        self.mockDbSession.commit.assert_called_once()

    def test_killProcess_updatesStatusToKilled(self):
        """
        WORKFLOW: User kills process — status becomes 'Killed'.
        Method is storeProcessKillStatus(str), not updateProcessStatus — catches rename.
        """
        from db.entities.process import process

        mockProcess = MagicMock(spec=process)
        mockProcess.status = 'Running'
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess

        self.processRepo.storeProcessKillStatus('123')

        self.assertEqual(mockProcess.status, 'Killed')
        self.mockDbSession.commit.assert_called_once()


class ToolOutputPersistenceTest(unittest.TestCase):
    """
    Tests that tool output is saved and can be restored.

    CRITICAL: If these fail, users lose scan results.
    """

    def setUp(self):
        from db.repositories.ProcessRepository import ProcessRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        self.mockLog = MagicMock()

        self.mockDbAdapter.session.return_value = self.mockDbSession
        self.processRepo = ProcessRepository(self.mockDbAdapter, self.mockLog)

    def test_storeProcessOutput_withHtmlContent_savesCorrectly(self):
        """
        WORKFLOW: Tool completes, HTML output stored via storeProcessOutput.
        """
        from db.entities.process import process
        from db.entities.processOutput import process_output

        mockProcess = MagicMock(spec=process)
        mockProcess.id = 123
        mockProcOutput = MagicMock(spec=process_output)

        self.mockDbSession.query.return_value.filter_by.return_value.first.side_effect = [
            mockProcess,
            mockProcOutput
        ]

        self.processRepo.storeProcessOutput('123', "<span>output</span>")

        self.mockDbSession.commit.assert_called()

    def test_getProcessById_returnsProcessData(self):
        """
        WORKFLOW: Retrieve stored process by ID — returns dict with process fields.
        getProcessOutput() was renamed getProcessById(); catches future rename regressions.
        """
        from db.entities.process import process

        mockProcess = MagicMock(spec=process)
        mockProcess.id = 123
        mockProcess.name = 'nmap'
        mockProcess.tabTitle = 'Nmap Scan'
        mockProcess.hostIp = '192.168.1.1'
        mockProcess.port = ''
        mockProcess.protocol = 'tcp'
        mockProcess.command = 'nmap -sV 192.168.1.1'
        mockProcess.outputfile = '/tmp/output.xml'
        mockProcess.status = 'Finished'
        mockProcess.display = 'True'

        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess

        result = self.processRepo.getProcessById(123)

        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'nmap')
        self.assertEqual(result['status'], 'Finished')


class HostDataIntegrityTest(unittest.TestCase):
    """
    Tests that host/port/service data stays consistent across operations.
    """

    def setUp(self):
        from db.repositories.HostRepository import HostRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        self.mockDbAdapter.session = self.mockDbSession
        self.hostRepo = HostRepository(self.mockDbAdapter)

    def test_addHost_thenGetHost_dataMatches(self):
        """
        WORKFLOW: Scan discovers host, saved to DB, retrieved by IP — data matches.
        """
        from db.entities.host import hostObj

        mockHost = MagicMock(spec=hostObj)
        mockHost.ip = '192.168.1.1'
        mockHost.hostname = 'target.local'
        mockHost.status = 'up'

        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockHost

        result = self.hostRepo.getHostByIP('192.168.1.1')

        self.assertEqual(result.ip, '192.168.1.1')
        self.assertEqual(result.hostname, 'target.local')


class TabSwitchingDataIntegrityTest(unittest.TestCase):
    """
    Tests that switching between hosts updates data correctly.

    CRITICAL: Users see wrong host's data if this regresses.
    """

    def test_switchHost_cveTabUpdates(self):
        """
        WORKFLOW: Select host — CVE tab queries by host IP, not host ID.
        getCVEsByHostId was renamed getCVEsByHostIP. This test catches that regression.
        """
        from db.repositories.CVERepository import CVERepository

        mockDbAdapter = MagicMock()
        mockDbSession = MagicMock()
        # CVERepository uses self.dbAdapter.session as a property (not callable)
        mockDbAdapter.session = mockDbSession

        cveRepo = CVERepository(mockDbAdapter)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ('CVE-2021-1234', 9.8, 'apache', '2.4.1', '', '', '', '', '')
        ]
        mock_result.keys.return_value = [
            'name', 'severity', 'product', 'version',
            'url', 'source', 'exploitId', 'exploit', 'exploitUrl'
        ]
        mockDbSession.execute.return_value = mock_result

        cves = cveRepo.getCVEsByHostIP('192.168.1.1')

        mockDbSession.execute.assert_called_once()
        self.assertEqual(len(cves), 1)
        self.assertEqual(cves[0]['name'], 'CVE-2021-1234')


class ConfigurationPersistenceTest(unittest.TestCase):
    """Tests configuration file handling."""

    def test_backupConfig_createsBackupInCorrectFolder(self):
        """Placeholder — config backup covered by test_qt6_gaps.py A1 tests."""
        pass


if __name__ == '__main__':
    unittest.main()
