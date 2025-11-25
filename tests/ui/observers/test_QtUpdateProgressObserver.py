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
from unittest.mock import patch


class QtUpdateProgressObserverTest(unittest.TestCase):
    @patch("ui.ancillaryDialog.ProgressWidget")
    def setUp(self, mockProgressWidget) -> None:
        from ui.observers.QtUpdateProgressObserver import QtUpdateProgressObserver
        self.mockProgressWidget = mockProgressWidget
        self.qtUpdateProgressObserver = QtUpdateProgressObserver(self.mockProgressWidget)

    @patch("PyQt6.QtCore.QMetaObject.invokeMethod")
    def test_onStart_callsShowOnProgressWidget(self, mock_invoke):
        self.qtUpdateProgressObserver.onStart()
        mock_invoke.assert_called_once()

    @patch("PyQt6.QtCore.QMetaObject.invokeMethod")
    def test_onFinished_callsHideOnProgressWidget(self, mock_invoke):
        self.qtUpdateProgressObserver.onFinished()
        mock_invoke.assert_called_once()

    def test_onProgressUpdate_callsSetProgressAndShow(self):
        self.qtUpdateProgressObserver.onProgressUpdate(25, "Test Title")
        self.mockProgressWidget.setText.assert_called_once_with("Test Title")
        self.mockProgressWidget.setProgress.assert_called_once_with(25)
        self.mockProgressWidget.show.assert_called_once()
