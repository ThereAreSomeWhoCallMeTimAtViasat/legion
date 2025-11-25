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
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch


class ToolCoordinatorTest(unittest.TestCase):
    @patch("app.tools.nmap.NmapHelpers.nmapFileExists")
    def setUp(self, nmapFileExists) -> None:
        from app.tools.ToolCoordinator import ToolCoordinator
        # Create fresh mocks for each test to prevent side_effect pollution
        self.mockShell = MagicMock()
        self.mockNmapExporter = MagicMock()
        self.nmapFileExists = nmapFileExists
        self.outputFolder = "some-output-folder"
        # Store reference to avoid recreation issues
        self.toolCoordinator = ToolCoordinator(self.mockShell, self.mockNmapExporter)

    @patch("os.path.basename")
    @patch("os.path.dirname")
    def test_saveToolOutput_WhenGivenProjectOutputFolderAndNmapFileNameToSaveOutputIn_SavesOutputSuccessfully(self,
                                                                                                              mock_dirname,
                                                                                                              mock_basename):
        fileName = "some-running-folder/nmap/some-output-nmap-file"

        mock_dirname.return_value = "some-running-folder/nmap"
        mock_basename.return_value = "nmap"
        # Reset mock to clear any exhausted side_effect from previous tests
        self.mockShell.directoryOrFileExists.reset_mock(side_effect=True)
        # Calls: check folder exists, check if it's directory (True), check if it's NOT file (True)
        self.mockShell.directoryOrFileExists.side_effect = [True, False, False, True, True, True]
        self.mockShell.isFile.return_value = False
        self.nmapFileExists.return_value = True

        self.toolCoordinator.saveToolOutput(self.outputFolder, fileName)
        self.mockNmapExporter.exportOutputToHtml.assert_called_once_with(fileName,
                                                                         "some-output-folder/nmap")
        self.mockShell.move.assert_has_calls([
            mock.call(fileName + ".xml", "some-output-folder/nmap"),
            mock.call(fileName + ".nmap", "some-output-folder/nmap"),
            mock.call(fileName + ".gnmap", "some-output-folder/nmap"),
        ])

    @patch("ntpath.basename")
    def test_saveToolOutput_WhenGivenProjectOutputDirAndGenericFileNameToSaveOutputIn_SavesOutputSuccessfully(self,
                                                                                                              basename):
        fileName = "some-output-file"
        basename.return_value = "some-tool"
        # Reset mock to clear any exhausted side_effect from previous tests
        self.mockShell.directoryOrFileExists.reset_mock(side_effect=True)
        # Calls: 1) check if output folder exists, 2) check if outputFileName is directory, 3) fileExists check
        self.mockShell.directoryOrFileExists.side_effect = [False, False, True]
        # Only 1 call: fileExists check (the directory check short-circuits because directoryOrFileExists is False)
        self.mockShell.isFile.return_value = True

        self.toolCoordinator.saveToolOutput(self.outputFolder, fileName)
        self.mockShell.move.assert_called_once_with("some-output-file", "some-output-folder")

    @patch("app.tools.ToolCoordinator.nmapFileExists")
    @patch("os.path.basename")
    @patch("os.path.dirname")
    def test_saveToolOutput_WhenGivenProjectOutputFolderAndXmlFileNameToSaveOutputIn_SavesOutputSuccessfully(self,
                                                                                                             mock_dirname,
                                                                                                             mock_basename,
                                                                                                             mock_nmapFileExists):
        fileName = "some-output-xml-file"
        mock_dirname.return_value = ""
        mock_basename.return_value = ""
        # Reset mocks to clear any previous test calls
        self.mockShell.move.reset_mock()
        self.mockShell.directoryOrFileExists.reset_mock(side_effect=True)
        # Calls: check folder exists, check if directory, fileExists, nmapFileExists (False), xmlFileExists (True)
        self.mockShell.directoryOrFileExists.side_effect = [False, False, False, True]
        self.mockShell.isFile.return_value = True
        mock_nmapFileExists.return_value = False  # So it doesn't take nmap path

        self.toolCoordinator.saveToolOutput(self.outputFolder, fileName)
        self.mockShell.move.assert_called_once_with("some-output-xml-file.xml", "some-output-folder")

    @patch("app.tools.ToolCoordinator.nmapFileExists")
    @patch("os.path.basename")
    @patch("os.path.dirname")
    def test_saveToolOutput_WhenGivenProjectOutputFolderAndTxtFileNameToSaveOutputIn_SavesOutputSuccessfully(self,
                                                                                                             mock_dirname,
                                                                                                             mock_basename,
                                                                                                             mock_nmapFileExists):
        fileName = "some-output-txt-file"
        mock_dirname.return_value = ""
        mock_basename.return_value = ""
        # Reset mocks to clear any previous test calls
        self.mockShell.move.reset_mock()
        self.mockShell.directoryOrFileExists.reset_mock(side_effect=True)
        # Calls: check folder exists, check if directory, fileExists, nmapFileExists, xmlFileExists, textFileExists
        self.mockShell.directoryOrFileExists.side_effect = [False, False, False, False, True]
        self.mockShell.isFile.return_value = True
        mock_nmapFileExists.return_value = False  # So it doesn't take nmap path

        self.toolCoordinator.saveToolOutput(self.outputFolder, fileName)
        self.mockShell.move.assert_called_once_with("some-output-txt-file.txt", "some-output-folder")
