"""
LEGION (https://shanewilliamscott.com)
Copyright (c) 2025 Shane William Scott

    This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
    License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
    version.

    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
    details.

    You should have received a copy of the GNU General Public License along with this program.
    If not, see <http://www.gnu.org/licenses/>.

Author(s): Shane Scott (sscott@shanewilliamscott.com), Dmitriy Dubson (d.dubson@gmail.com)
"""
import sys
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

from app.Project import Project


class ProjectManagerTest(unittest.TestCase):
    @patch('os.makedirs')  # Patch os.makedirs globally to prevent module-level getTempFolder() issues
    @patch('os.path.isdir', return_value=True)  # Pretend temp directory already exists
    @patch('db.repositories.HostRepository')
    @patch('app.auxiliary.Wordlist')
    @patch('db.SqliteDbAdapter.Database')
    def setUp(self, hostRepository, wordlist, database, mock_isdir, mock_makedirs) -> None:
        mock_makedirs.return_value = None  # No-op for temp directory creation at import time
        # Remove ProjectManager from cache to ensure clean import
        if 'app.ProjectManager' in sys.modules:
            del sys.modules['app.ProjectManager']
        from app.ProjectManager import ProjectManager
        self.mockShell = MagicMock()
        self.mockRepositoryFactory = MagicMock()
        self.project = MagicMock()
        self.mockDatabase = database
        mockLogger = MagicMock()
        self.projectManager = ProjectManager(self.mockShell, self.mockRepositoryFactory, mockLogger)

    def test_createNewProject_WhenProvidedProjectDetails_ReturnsANewProject(self):
        projectType = "legion"
        isTemporary = True
        self.mockDatabase.name = "newTemporaryProject"
        self.mockShell.get_current_working_directory.return_value = "workingDir/"
        self.mockShell.create_temporary_directory.side_effect = ["/outputFolder", "/runningFolder"]

        project = self.projectManager.createNewProject(projectType, isTemporary)
        self.mockShell.create_named_temporary_file.assert_called_once_with(
            suffix=".legion", prefix="legion-", directory=mock.ANY, delete_on_close=False
        )
        self.mockShell.create_temporary_directory.assert_has_calls([
            mock.call(prefix="legion-", suffix="-tool-output", directory=mock.ANY),
            mock.call(prefix="legion-", suffix="-running", directory=mock.ANY),
        ])
        self.mockShell.create_directory_recursively.assert_has_calls([
            mock.call("/outputFolder/screenshots"),
            mock.call("/runningFolder/nmap"),
            mock.call("/runningFolder/hydra"),
            mock.call("/runningFolder/dnsmap"),
        ])
        self.assertIsNotNone(project.properties.projectName)
        self.assertEqual(project.properties.projectType, "legion")
        self.assertEqual(project.properties.workingDirectory, "workingDir/")
        self.assertEqual(project.properties.isTemporary, True)
        self.assertEqual(project.properties.outputFolder, "/outputFolder")
        self.assertEqual(project.properties.runningFolder, "/runningFolder")
        self.assertEqual(project.properties.storeWordListsOnExit, True)
        self.mockRepositoryFactory.buildRepositories.assert_called_once_with(mock.ANY)

    @patch('os.path.exists', return_value=True)
    def test_closeProject_WhenProvidedAnOpenTemporaryProject_ClosesTheProject(self, mock_exists):
        self.project.properties.isTemporary = True
        self.project.properties.storeWordListsOnExit = True
        self.project.properties.projectName = "project-name"
        self.project.properties.runningFolder = "./running/folder"
        self.project.properties.outputFolder = "./output/folder"

        self.projectManager.closeProject(self.project)
        self.mockShell.remove_file.assert_called_once_with("project-name")
        self.mockShell.remove_directory.assert_has_calls([mock.call("./output/folder"), mock.call("./running/folder")])

    @patch('os.path.exists', return_value=True)
    def test_closeProject_WhenProvidedAnOpenNonTemporaryProject_ClosesTheProject(self, mock_exists):
        self.project.properties.isTemporary = False
        self.project.properties.storeWordListsOnExit = False
        self.project.properties.runningFolder = "./running/folder"
        self.project.properties.usernamesWordList = MagicMock()
        self.project.properties.usernamesWordList.filename = "UsernamesList.txt"
        self.project.properties.passwordWordList = MagicMock()
        self.project.properties.passwordWordList.filename = "PasswordsList.txt"

        self.projectManager.closeProject(self.project)
        self.mockShell.remove_file.assert_has_calls([mock.call("UsernamesList.txt"), mock.call("PasswordsList.txt")])
        self.mockShell.remove_directory.assert_called_once_with("./running/folder")

    def test_openExistingProject_WhenProvidedProjectNameAndType_OpensAnExistingProjectSuccessfully(self):
        from app.Project import Project

        projectName = "some-existing-project"
        self.mockShell.create_temporary_directory.return_value = "/running/folder"
        openedExistingProject: Project = self.projectManager.openExistingProject(projectName, "legion")
        self.assertFalse(openedExistingProject.properties.isTemporary)
        self.assertEqual(openedExistingProject.properties.projectName, "some-existing-project")
        self.assertEqual(openedExistingProject.properties.workingDirectory, "/")
        self.assertEqual(openedExistingProject.properties.projectType, "legion")
        self.assertFalse(openedExistingProject.properties.isTemporary)
        self.assertEqual(openedExistingProject.properties.outputFolder, "some-existing-project-tool-output")
        self.assertEqual(openedExistingProject.properties.runningFolder, "/running/folder")
        self.assertIsNotNone(openedExistingProject.properties.usernamesWordList)
        self.assertIsNotNone(openedExistingProject.properties.passwordWordList)
        self.assertTrue(openedExistingProject.properties.storeWordListsOnExit)
        self.mockShell.create_temporary_directory.assert_called_once_with(suffix="-running", prefix="legion-",
                                                                          directory=mock.ANY)
        self.mockRepositoryFactory.buildRepositories.assert_called_once()

    @patch('shutil.copytree')
    @patch('os.path.exists', return_value=False)
    def test_saveProjectAs_WhenProvidedAnActiveTemporaryProjectAndASaveFileName_SavesProjectSuccessfully(self,
                                                                                                         mock_exists,
                                                                                                         mock_copytree):
        expectedFileName = "my-test-project"
        self.project.properties.projectName = "some-running-temporary-project"
        self.project.properties.outputFolder = "some-temporary-output-folder"
        self.project.properties.isTemporary = True
        self.project.database.verify_integrity = MagicMock()
        self.project.database.backup_to = MagicMock()

        savedProject: Project = self.projectManager.saveProjectAs(self.project, expectedFileName, replace=1,
                                                                  projectType="legion")
        self.project.database.backup_to.assert_called_once_with("my-test-project.legion")
        mock_copytree.assert_called_once()
        self.mockShell.remove_file.assert_called_once_with("some-running-temporary-project")
        self.mockShell.remove_directory.assert_called_once_with("some-temporary-output-folder")
        self.assertEqual(savedProject.properties.projectName, "my-test-project.legion")
        self.assertEqual(savedProject.properties.projectType, "legion")

    @patch('os.system')
    def test_saveProjectAs_WhenReplaceFlagIsFalse_DoesNotSaveProject(self, osSystem):
        self.projectManager.saveProjectAs(self.project, "some-project-that-cannot-be-replaced", replace=0,
                                          projectType="legion")
        self.mockShell.copy.assert_not_called()
        osSystem.assert_not_called()
