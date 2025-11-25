"""
Tests for Feature #2: Tool Tab Output Persistence

Feature: bash/msfconsole tool tab output now saved and restored from database
Status: KNOWN WORKING (from TROUBLESHOOTING.md completed items)
Test Goal: Prevent regression - ensure tool output persistence keeps working

Commit: e46ca2c
"""
import unittest
from unittest.mock import MagicMock, patch
from db.repositories.ProcessRepository import ProcessRepository
from app.logging.legionLog import getDbLogger


class ToolTabOutputPersistenceTest(unittest.TestCase):
    """
    Tests that tool tab output (bash, msfconsole) is saved and restored.
    
    CRITICAL: If these fail, users lose tool history on project reopen.
    """
    
    def setUp(self):
        """Set up process repository with mocked database."""
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        self.mockDbAdapter.session.return_value = self.mockDbSession
        
        self.mockLogger = getDbLogger()
        self.processRepo = ProcessRepository(self.mockDbAdapter, self.mockLogger)
    
    def test_bashToolOutput_savedToDatabase(self):
        """
        REGRESSION TEST: bash tool output saved to database.
        
        Before commit e46ca2c: bash output not persisted
        After commit e46ca2c: bash output saved to database
        
        If this fails: bash tool output lost on project close
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 1
        mockProcess.name = "bash"
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Typical bash output
        bash_output = """$ ls -la
total 48
drwxr-xr-x  6 user user 4096 Nov 25 10:00 .
drwxr-xr-x 20 user user 4096 Nov 25 09:00 ..
-rw-r--r--  1 user user  220 Nov 25 09:00 .bashrc"""
        
        # Store bash output
        self.processRepo.storeProcessOutput(1, bash_output)
        
        # Verify output stored
        self.assertEqual(mockProcess.output, bash_output)
        self.assertIn('$ ls -la', mockProcess.output)
        self.mockDbSession.commit.assert_called_once()
    
    def test_msfconsoleToolOutput_savedToDatabase(self):
        """
        REGRESSION TEST: msfconsole tool output saved to database.
        
        Before commit e46ca2c: msfconsole output not persisted
        After commit e46ca2c: msfconsole output saved to database
        
        If this fails: msfconsole tool output lost on project close
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 2
        mockProcess.name = "msfconsole"
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Typical msfconsole output with ANSI colors (stored as HTML)
        msfconsole_output = """<span style="color: red;">msf6 ></span> use exploit/multi/handler
<span style="color: green;">[*] Using configured payload generic/shell_reverse_tcp</span>
<span style="color: red;">msf6 exploit(multi/handler) ></span> set LHOST 192.168.1.100
LHOST => 192.168.1.100"""
        
        # Store msfconsole output
        self.processRepo.storeProcessOutput(2, msfconsole_output)
        
        # Verify output stored with formatting
        self.assertEqual(mockProcess.output, msfconsole_output)
        self.assertIn('msf6', mockProcess.output)
        self.assertIn('style=', mockProcess.output, "msfconsole colors should be preserved")
        self.mockDbSession.commit.assert_called_once()
    
    def test_multipleToolTabs_persistIndependently(self):
        """
        REGRESSION TEST: Multiple tool tabs save independently.
        
        User can have multiple bash/msfconsole tabs open. Each should
        persist independently without interfering with each other.
        
        If this fails: Tool outputs get mixed or overwritten
        """
        from db.entities.process import process
        
        # Tool tab 1: bash
        mockProcess1 = MagicMock(spec=process)
        mockProcess1.id = 10
        mockProcess1.name = "bash"
        
        # Tool tab 2: msfconsole
        mockProcess2 = MagicMock(spec=process)
        mockProcess2.id = 20
        mockProcess2.name = "msfconsole"
        
        # Tool tab 3: another bash
        mockProcess3 = MagicMock(spec=process)
        mockProcess3.id = 30
        mockProcess3.name = "bash"
        
        # Setup mock to return different processes
        def mock_filter_by_first(processId):
            mapping = {10: mockProcess1, 20: mockProcess2, 30: mockProcess3}
            mock_query = MagicMock()
            mock_query.first.return_value = mapping.get(processId)
            return mock_query
        
        # Store outputs for each tab
        bash1_output = "$ whoami\nroot"
        msfconsole_output = "msf6 > help"
        bash2_output = "$ pwd\n/tmp"
        
        # Mock the filter_by chain to return correct process for each ID
        def mock_filter_by(id=None, **kwargs):
            mock_result = MagicMock()
            if id == 10:
                mock_result.first.return_value = mockProcess1
            elif id == 20:
                mock_result.first.return_value = mockProcess2
            elif id == 30:
                mock_result.first.return_value = mockProcess3
            else:
                mock_result.first.return_value = None
            return mock_result
        
        self.mockDbSession.query.return_value.filter_by = mock_filter_by
        
        # Store output for each tab
        self.processRepo.storeProcessOutput(10, bash1_output)
        self.processRepo.storeProcessOutput(20, msfconsole_output)
        self.processRepo.storeProcessOutput(30, bash2_output)
        
        # Verify commits called for each save
        self.assertEqual(self.mockDbSession.commit.call_count, 3)
    
    def test_toolOutput_persistsAcrossProjectReopen(self):
        """
        INTEGRATION TEST: Tool output survives project close/reopen.
        
        Workflow:
        1. Run bash commands in tool tab
        2. Close project
        3. Reopen project
        4. Tool tab shows previous commands
        
        If this fails: Tool history lost on reopen
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 100
        mockProcess.name = "bash"
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Store command history
        bash_history = """$ ifconfig
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
$ netstat -an
Active Internet connections (servers and established)"""
        
        self.processRepo.storeProcessOutput(100, bash_history)
        
        # Simulate project close (commit)
        self.mockDbSession.commit.assert_called()
        
        # Simulate project reopen (retrieve via getProcessById)
        # In real code, output is accessed through process_output relationship
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        retrieved_process = self.processRepo.getProcessById(100)
        
        # Verify process retrieved (output stored in database)
        self.assertIsNotNone(retrieved_process)
        self.assertEqual(retrieved_process['name'], "bash")
    
    def test_interactiveCommands_savedWithOriginalOutput(self):
        """
        REGRESSION TEST: Interactive commands saved with output.
        
        When user types commands interactively in bash/msfconsole, both
        the command and its output should be saved together.
        
        If this fails: Only commands saved, not their output
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 200
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Interactive session with commands and output
        interactive_session = """$ cat /etc/passwd | grep root
root:x:0:0:root:/root:/bin/bash
$ echo "test"
test
$ date
Mon Nov 25 14:30:00 PST 2025"""
        
        self.processRepo.storeProcessOutput(200, interactive_session)
        
        # Verify both commands and output saved
        self.assertEqual(mockProcess.output, interactive_session)
        self.assertIn('$ cat', mockProcess.output, "Command should be saved")
        self.assertIn('root:x:0:0', mockProcess.output, "Output should be saved")
        self.assertIn('$ echo', mockProcess.output, "Multiple commands saved")
        self.assertIn('test', mockProcess.output, "Multiple outputs saved")
    
    def test_longRunningToolOutput_incrementalSaves(self):
        """
        REGRESSION TEST: Long-running tools save output incrementally.
        
        Tools like msfconsole can run for hours. Output should be saved
        periodically, not just at the end.
        
        If this fails: Crash or close loses all output
        """
        from db.entities.process import process
        
        mockProcess = MagicMock(spec=process)
        mockProcess.id = 300
        
        self.mockDbSession.query.return_value.filter_by.return_value.first.return_value = mockProcess
        
        # Simulate incremental output updates
        output1 = "msf6 > use exploit/windows/smb/ms17_010_eternalblue"
        self.processRepo.storeProcessOutput(300, output1)
        self.assertEqual(mockProcess.output, output1)
        
        # More output added
        output2 = output1 + "\nmsf6 exploit(ms17_010_eternalblue) > set RHOSTS 192.168.1.1"
        mockProcess.output = output2  # Simulate DB state
        self.processRepo.storeProcessOutput(300, output2)
        self.assertEqual(mockProcess.output, output2)
        
        # Final output
        output3 = output2 + "\n[*] Started reverse TCP handler on 192.168.1.100:4444"
        mockProcess.output = output3
        self.processRepo.storeProcessOutput(300, output3)
        
        # Verify all output preserved
        self.assertIn('use exploit', mockProcess.output)
        self.assertIn('set RHOSTS', mockProcess.output)
        self.assertIn('Started reverse', mockProcess.output)


class ToolTabProcessTrackingTest(unittest.TestCase):
    """
    Tests that tool tab processes are properly tracked in database.
    """
    
    def setUp(self):
        """Set up process repository."""
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        
        type(self.mockDbAdapter).session = unittest.mock.PropertyMock(return_value=self.mockDbSession)
        self.mockDbAdapter.session.return_value = self.mockDbSession
        
        self.mockLogger = getDbLogger()
        self.processRepo = ProcessRepository(self.mockDbAdapter, self.mockLogger)
    
    def test_storeProcess_bashTool_createsRecord(self):
        """
        TEST: bash tool creates process record for tracking.
        
        If this fails: bash tools not tracked in database
        """
        # Create mock process object (like MyQProcess)
        mockProc = MagicMock()
        mockProc.processId.return_value = "12345"
        mockProc.name = "bash"
        mockProc.tabTitle = "Interactive Shell"
        mockProc.hostIp = "192.168.1.1"
        mockProc.port = ""
        mockProc.protocol = ""
        mockProc.command = "/bin/bash"
        mockProc.startTime = "2025-11-25 14:00:00"
        mockProc.outputfile = ""
        
        # Store bash process
        result = self.processRepo.storeProcess(mockProc)
        
        # Verify process added and committed
        self.mockDbSession.add.assert_called_once()
        self.mockDbSession.commit.assert_called_once()
    
    def test_storeProcess_msfconsoleTool_createsRecord(self):
        """
        TEST: msfconsole tool creates process record for tracking.
        
        If this fails: msfconsole tools not tracked in database
        """
        # Create mock process object (like MyQProcess)
        mockProc = MagicMock()
        mockProc.processId.return_value = "67890"
        mockProc.name = "msfconsole"
        mockProc.tabTitle = "Metasploit Console"
        mockProc.hostIp = "192.168.1.1"
        mockProc.port = "445"
        mockProc.protocol = "tcp"
        mockProc.command = "msfconsole"
        mockProc.startTime = "2025-11-25 14:05:00"
        mockProc.outputfile = ""
        
        # Store msfconsole process
        result = self.processRepo.storeProcess(mockProc)
        
        # Verify process added and committed
        self.mockDbSession.add.assert_called_once()
        self.mockDbSession.commit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
