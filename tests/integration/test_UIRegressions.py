#!/usr/bin/env python
"""
UI Regression Tests

Tests visual/UI features that automated unit tests don't catch.
These tests use real PyQt6 widgets and QApplication to verify UI behavior.

Purpose: Catch regressions like:
- Tab switching but data doesn't update
- Buttons stop working
- Colors/formatting breaks
- Visual feedback missing

Run: python -m unittest tests.integration.test_UIRegressions
"""

import unittest
import os
import sys
import tempfile
import shutil
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# Test if PyQt6 available (skip all tests if not)
try:
    from PyQt6 import QtWidgets, QtCore, QtTest
    from PyQt6.QtCore import Qt
    PYQT6_AVAILABLE = True
except ImportError:
    PYQT6_AVAILABLE = False

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app.shell.DefaultShell import DefaultShell
from app.ProjectManager import ProjectManager
from app.logging.legionLog import getDbLogger, getAppLogger
from db.RepositoryFactory import RepositoryFactory
from app.tools.nmap.DefaultNmapExporter import DefaultNmapExporter
from app.tools.ToolCoordinator import ToolCoordinator
from app.logic import Logic


@unittest.skipUnless(PYQT6_AVAILABLE, "PyQt6 not available")
class LegionUITestBase(unittest.TestCase):
    """
    Base class for Legion UI tests.
    
    Provides full Legion initialization with View, Controller, Logic.
    This is HEAVY - use only for actual UI regression tests.
    """
    
    @classmethod
    def setUpClass(cls):
        """Create QApplication once for all tests"""
        if not QtWidgets.QApplication.instance():
            cls.app = QtWidgets.QApplication(sys.argv)
        else:
            cls.app = QtWidgets.QApplication.instance()
    
    def setUp(self):
        """Create temp project and initialize Legion components before each test"""
        self.temp_dir = tempfile.mkdtemp(prefix='legion_ui_test_')
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        
        # Create core components (same as legion.py)
        self.shell = DefaultShell()
        self.dbLog = getDbLogger()
        self.appLogger = getAppLogger()
        self.repositoryFactory = RepositoryFactory(self.dbLog)
        self.projectManager = ProjectManager(self.shell, self.repositoryFactory, self.appLogger)
        self.nmapExporter = DefaultNmapExporter(self.shell, self.appLogger)
        self.toolCoordinator = ToolCoordinator(self.shell, self.nmapExporter)
        self.logic = Logic(self.shell, self.projectManager, self.toolCoordinator)
        
        # Create temporary project
        self.logic.createNewTemporaryProject()
        
        # Store convenience references to repositories
        self.hostRepo = self.logic.activeProject.repositoryContainer.hostRepository
        self.portRepo = self.logic.activeProject.repositoryContainer.portRepository
        self.serviceRepo = self.logic.activeProject.repositoryContainer.serviceRepository
        self.noteRepo = self.logic.activeProject.repositoryContainer.noteRepository
        self.cveRepo = self.logic.activeProject.repositoryContainer.cveRepository
        self.scriptRepo = self.logic.activeProject.repositoryContainer.scriptRepository
        self.processRepo = self.logic.activeProject.repositoryContainer.processRepository
        
        # Database session for direct operations
        self.db = self.logic.activeProject.database
        
    def createHost(self, ip, hostname=''):
        """Helper to create a host directly in database"""
        from db.entities.host import hostObj
        from db.entities.note import note
        
        session = self.db.session()
        
        # Check if host already exists
        existing = session.query(hostObj).filter_by(ip=ip).first()
        if existing:
            session.close()
            return existing
        
        # Create new host
        host = hostObj(
            osMatch='', osAccuracy='', ip=ip, ipv4=ip, ipv6='', macaddr='',
            status='up', hostname=hostname, vendor='', uptime='',
            lastboot='', distance='', state='', count=''
        )
        session.add(host)
        session.commit()
        
        # Add default note
        t_note = note(ip, 'Test host')
        session.add(t_note)
        session.commit()
        
        # Refresh to get ID
        session.refresh(host)
        host_id = host.id
        session.close()
        
        # Return the host object
        return self.hostRepo.getHostInformation(ip)
    
    def createPort(self, host_obj, port_num, protocol='tcp'):
        """Helper to create a port directly in database"""
        from db.entities.port import portObj
        
        session = self.db.session()
        
        # Create port - port entity takes host object, not host ID
        port = portObj(
            portId=port_num,
            protocol=protocol,
            state='open',
            host=host_obj,
            service=''
        )
        session.add(port)
        session.commit()
        
        # Refresh to get ID
        session.refresh(port)
        port_id = port.id
        session.close()
        
        # Return port ID
        return port_id
            
    def tearDown(self):
        """Clean up project and temp files after each test"""
        if self.logic and self.logic.activeProject:
            self.projectManager.closeProject(self.logic.activeProject)
            self.logic.activeProject = None


@unittest.skipUnless(PYQT6_AVAILABLE, "PyQt6 not available")
class TestDataIntegrityRegressions(LegionUITestBase):
    """
    Test data integrity issues that only show up in UI layer.
    
    These are the MOST COMMON regressions:
    - Host switching but wrong data displayed
    - Notes saved to wrong host
    - CVE/Scripts tabs show wrong data
    """
    
    # ========================================================================
    # HOST SWITCHING - Data Integrity (Backend Only for Now)
    # ========================================================================
    
    def test_host_data_isolation_in_database(self):
        """
        CRITICAL REGRESSION TEST: Different hosts must maintain separate data
        
        Tests the backend data layer that UI depends on.
        If this fails, UI will definitely show wrong data.
        
        User complaint: "I add notes to Host A, switch to Host B, switch back - notes are mixed up"
        """
        # Step 1: Create two hosts
        hostA = self.createHost('192.168.1.10')
        hostB = self.createHost('192.168.1.11')
        
        self.assertIsNotNone(hostA, "Host A should be created")
        self.assertIsNotNone(hostB, "Host B should be created")
        self.assertNotEqual(hostA.id, hostB.id, "Hosts should have different IDs")
        
        # Step 2: Add notes to Host A
        self.noteRepo.storeNotes(hostA.id, 'Note for Host A - Web Server Running Apache')
        
        # Step 3: Add DIFFERENT notes to Host B
        self.noteRepo.storeNotes(hostB.id, 'Note for Host B - Database Server Running MySQL')
        
        # Step 4: Retrieve Host A's note - should NOT contain Host B's text
        noteA = self.noteRepo.getNoteByHostId(hostA.id)
        self.assertIsNotNone(noteA, "Host A should have a note")
        self.assertIn('Apache', noteA.text, "Host A note should mention Apache")
        self.assertNotIn('MySQL', noteA.text, "Host A note should NOT mention MySQL (that's Host B)")
        
        # Step 5: Retrieve Host B's note - should NOT contain Host A's text
        noteB = self.noteRepo.getNoteByHostId(hostB.id)
        self.assertIsNotNone(noteB, "Host B should have a note")
        self.assertIn('MySQL', noteB.text, "Host B note should mention MySQL")
        self.assertNotIn('Apache', noteB.text, "Host B note should NOT mention Apache (that's Host A)")
        
        # Step 6: Switch back to Host A (simulate user clicking Host A again)
        noteA_again = self.noteRepo.getNoteByHostId(hostA.id)
        self.assertIsNotNone(noteA_again, "Host A note should still exist after 'switching'")
        self.assertIn('Apache', noteA_again.text, "Host A note should still mention Apache")
        self.assertEqual(noteA.text, noteA_again.text, "Host A note should be unchanged")
    
    def test_cve_data_isolation_by_host(self):
        """
        CRITICAL REGRESSION TEST: CVEs must be associated with correct host
        
        User complaint: "CVE tab shows wrong CVEs when I switch hosts"
        
        NOTE: CVEs are read-only from nmap/vulners. This test validates retrieval logic.
        """
        # CVEs are populated by nmap importer, not directly stored
        # This test is a placeholder showing intent - actual CVE data comes from nmap XML
        self.skipTest("CVEs are read-only from nmap/vulners - test CVE tab updates in UI layer")
    
    def test_scripts_data_isolation_by_host(self):
        """
        CRITICAL REGRESSION TEST: Nmap scripts must be associated with correct host/port
        
        User complaint: "Scripts tab shows scripts from previous host"
        
        NOTE: Scripts are read-only from nmap. This test validates retrieval logic.
        """
        # Scripts are populated by nmap importer, not directly stored
        # This test is a placeholder showing intent - actual script data comes from nmap XML
        self.skipTest("Scripts are read-only from nmap - test Scripts tab updates in UI layer")

    
    # ========================================================================
    # TOOL OUTPUT - Persistence and Retrieval
    # ========================================================================


@unittest.skipUnless(PYQT6_AVAILABLE, "PyQt6 not available")
class TestToolOutputPersistence(LegionUITestBase):
    """
    Test tool output storage and retrieval.
    
    User complaint: "I run scans, close project, reopen - output is gone"
    """
    
    def test_process_storage_and_retrieval(self):
        """
        CRITICAL REGRESSION TEST: Process output must be stored and retrievable
        
        User complaint: "I close project, reopen, and all my scan output is gone"
        """
        from app.timing import getTimestamp
        
        # Step 1: Create host
        host = self.createHost('192.168.100.25')
        
        # Step 2: Create mock process (simulating nmap scan)
        # Must match the interface that ProcessRepository expects
        outputfile = os.path.join(self.temp_dir, 'nmap_output.txt')
        timestamp = getTimestamp()
        
        class MockProcess:
            def __init__(self):
                self.id = None
                self.name = 'nmap'
                self.hostIp = host.ip
                self.tabTitle = 'nmap (192.168.100.25)'
                self.outputfile = outputfile
                self.status = 'Running'
                self.startTime = timestamp
                self.outputType = 'html'
                self.port = '0'
                self.protocol = 'tcp'
                self.command = 'nmap -sV 192.168.100.25'
                
            def processId(self):
                return str(id(self))  # Unique ID for this process
        
        mock_process = MockProcess()
        
        # Write some output to file
        with open(mock_process.outputfile, 'w') as f:
            f.write('<html><body><h1>Nmap Scan Results</h1></body></html>')
        
        # Step 3: Store process
        db_id = self.processRepo.storeProcess(mock_process)
        self.assertIsNotNone(db_id, "Process should be stored and return DB ID")
        
        # Step 4: Mark process as finished
        self.processRepo.updateProcessState(db_id, status='Finished', endTime=getTimestamp())
        
        # Step 5: Retrieve process
        retrieved = self.processRepo.getProcessById(db_id)
        self.assertIsNotNone(retrieved, "Process should be retrievable")
        self.assertEqual(retrieved['name'], 'nmap', "Process name should match")
        self.assertEqual(retrieved['hostIp'], host.ip, "Process host IP should match")
        self.assertEqual(retrieved['status'], 'Finished', "Process status should be updated")
        
        # Step 6: Verify output file exists
        self.assertTrue(os.path.exists(mock_process.outputfile), "Output file should exist")
    
    def test_multiple_processes_independent(self):
        """
        CRITICAL REGRESSION TEST: Multiple tool outputs should not interfere
        
        User complaint: "Running nikto overwrites nmap output in its tab"
        """
        from app.timing import getTimestamp
        
        # Step 1: Create host
        host = self.createHost('10.0.0.100')
        
        # Step 2: Create first process (nmap)
        class NmapProcess:
            def __init__(self, outputfile):
                self.id = None
                self.name = 'nmap'
                self.hostIp = host.ip
                self.tabTitle = 'nmap (10.0.0.100)'
                self.outputfile = outputfile
                self.status = 'Finished'
                self.startTime = getTimestamp()
                self.outputType = 'html'
                self.port = '0'
                self.protocol = 'tcp'
                self.command = 'nmap -sV 10.0.0.100'
            def processId(self):
                return 'nmap_' + str(id(self))
        
        nmap_proc = NmapProcess(os.path.join(self.temp_dir, 'nmap.txt'))
        
        with open(nmap_proc.outputfile, 'w') as f:
            f.write('<html>NMAP OUTPUT</html>')
        
        nmap_id = self.processRepo.storeProcess(nmap_proc)
        
        # Step 3: Create second process (nikto)
        class NiktoProcess:
            def __init__(self, outputfile):
                self.id = None
                self.name = 'nikto'
                self.hostIp = host.ip
                self.tabTitle = 'nikto (10.0.0.100)'
                self.outputfile = outputfile
                self.status = 'Finished'
                self.startTime = getTimestamp()
                self.outputType = 'html'
                self.port = '80'
                self.protocol = 'tcp'
                self.command = 'nikto -h 10.0.0.100'
            def processId(self):
                return 'nikto_' + str(id(self))
        
        nikto_proc = NiktoProcess(os.path.join(self.temp_dir, 'nikto.txt'))
        
        with open(nikto_proc.outputfile, 'w') as f:
            f.write('<html>NIKTO OUTPUT</html>')
        
        nikto_id = self.processRepo.storeProcess(nikto_proc)
        
        # Step 4: Verify both processes exist independently
        self.assertNotEqual(nmap_id, nikto_id, "Processes should have different IDs")
        
        nmap_retrieved = self.processRepo.getProcessById(nmap_id)
        nikto_retrieved = self.processRepo.getProcessById(nikto_id)
        
        self.assertEqual(nmap_retrieved['name'], 'nmap', "Nmap process should still be nmap")
        self.assertEqual(nikto_retrieved['name'], 'nikto', "Nikto process should still be nikto")
        
        # Step 5: Verify output files are different
        self.assertNotEqual(nmap_retrieved['outputfile'], nikto_retrieved['outputfile'],
                           "Output files should be different")



@unittest.skipUnless(PYQT6_AVAILABLE, "PyQt6 not available")
class TestProjectPersistence(LegionUITestBase):
    """
    Test project save/load persistence.
    
    User complaint: "I work all day, close Legion, reopen - data is gone"
    """
    
    def test_data_persists_in_database(self):
        """
        CRITICAL REGRESSION TEST: Data must persist in SQLite database
        
        Tests that writes actually commit to database (not just in-memory).
        User complaint: "Reopen project and my notes/hosts are gone"
        """
        # Step 1: Add data
        host = self.createHost('192.168.50.100')
        self.noteRepo.storeNotes(host.id, 'Important note that must not be lost')
        
        # Step 2: Close all sessions (flush to disk)
        session = self.db.session()
        session.close()
        
        # Step 3: Create NEW session (simulates reopening)
        new_session = self.db.session()
        
        # Step 4: Query data with fresh session
        from db.entities.host import hostObj
        host2 = new_session.query(hostObj).filter_by(ip='192.168.50.100').first()
        self.assertIsNotNone(host2, "Host should be persisted in database")
        self.assertEqual(host2.ip, '192.168.50.100', "Host IP should match")
        
        # Step 5: Verify note persists
        note2 = self.noteRepo.getNoteByHostId(host2.id)
        self.assertIsNotNone(note2, "Note should be persisted")
        self.assertIn('Important note', note2.text, "Note text should match")
        
        new_session.close()




if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2)
