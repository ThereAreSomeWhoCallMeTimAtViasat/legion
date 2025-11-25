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
from unittest.mock import patch, MagicMock

from tests.db.helpers.db_helpers import mockExecuteFetchAll


class CVERepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_db_adapter = MagicMock()
        self.mockDbSession = MagicMock()
        # session is a property
        self.mock_db_adapter.session = self.mockDbSession

    def test_getCVEsByHostIP_WhenProvidedAHostIp_ReturnsCVEs(self):
        from db.repositories.CVERepository import CVERepository
        # Mock execute().fetchall() to return tuples - implementation converts to dicts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('cve1',), ('cve2',)]
        mock_result.keys.return_value = ['name']
        self.mockDbSession.execute.return_value = mock_result
        
        cveRepository = CVERepository(self.mock_db_adapter)
        result = cveRepository.getCVEsByHostIP("some_host")
        self.assertEqual([{'name': 'cve1'}, {'name': 'cve2'}], result)
        self.mockDbSession.execute.assert_called_once()
