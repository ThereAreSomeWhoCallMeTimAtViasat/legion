"""
LEGION (https://shanewilliamscott.com)
Copyright (c) 2018-2025 Shane William Scott

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
from unittest.mock import patch, MagicMock

from tests.db.helpers.db_helpers import mockFirstByReturnValue, mockExecuteFetchAll


class PortRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        from db.repositories.PortRepository import PortRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        # session is a property, not a method, so use direct assignment
        self.mockDbAdapter.session = self.mockDbSession
        self.repository = PortRepository(self.mockDbAdapter)

    def test_getPortsByIPAndProtocol_ReturnsPorts(self):
        # Mock execute().first() to return a single tuple
        mock_result = MagicMock()
        mock_result.first.return_value = ('port-id1',)
        self.mockDbSession.execute.return_value = mock_result
        
        ports = self.repository.getPortsByIPAndProtocol("some_host_ip", "tcp")

        self.mockDbSession.execute.assert_called_once()
        self.assertEqual(('port-id1',), ports)

    def test_getPortStatesByHostId_ReturnsPortsStates(self):
        # Mock execute().fetchall() to return tuples
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('port-state1',), ('port-state2',)]
        self.mockDbSession.execute.return_value = mock_result
        
        port_states = self.repository.getPortStatesByHostId("some_host_id")

        self.mockDbSession.execute.assert_called_once()
        self.assertEqual([('port-state1',), ('port-state2',)], port_states)

    def test_getPortsAndServicesByHostIP_InvokedWithNoFilters_ReturnsPortsAndServices(self):
        from app.auxiliary import Filters

        # Mock the result object with keys and rows - returns dicts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('ip1',), ('ip2',)]
        mock_result.keys.return_value = ['ip']
        self.mockDbSession.execute.return_value = mock_result

        filters: Filters = Filters()
        filters.apply(up=True, down=True, checked=True, portopen=True, portfiltered=True, portclosed=True,
                      tcp=True, udp=True)
        results = self.repository.getPortsAndServicesByHostIP("some_host_ip", filters)

        self.mockDbSession.execute.assert_called_once()
        self.assertEqual([{'ip': 'ip1'}, {'ip': 'ip2'}], results)

    def test_getPortsAndServicesByHostIP_InvokedWithFewFilters_ReturnsPortsAndServices(self):
        from app.auxiliary import Filters

        # Mock the result object with keys and rows - returns dicts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('ip1',), ('ip2',)]
        mock_result.keys.return_value = ['ip']
        self.mockDbSession.execute.return_value = mock_result

        filters: Filters = Filters()
        filters.apply(up=True, down=True, checked=True, portopen=True, portfiltered=True, portclosed=True,
                      tcp=False, udp=False)
        results = self.repository.getPortsAndServicesByHostIP("some_host_ip", filters)

        self.mockDbSession.execute.assert_called_once()
        self.assertEqual([{'ip': 'ip1'}, {'ip': 'ip2'}], results)

    def test_deleteAllPortsAndScriptsByHostId_WhenProvidedByHostIDAndProtocol_DeletesAllPortsAndScripts(self):
        mockFilterHost = mockProtocolFilter = mockReturnAll = MagicMock()
        mockPort1 = mockPort2 = MagicMock()
        mockReturnAll.all.return_value = [mockPort1, mockPort2]
        mockProtocolFilter.filter.return_value = mockReturnAll
        mockFilterHost.filter.return_value = mockProtocolFilter

        mockFilterScript = mockReturnAllScripts = MagicMock()
        mockReturnAllScripts.all.return_value = ['some-script1', 'some-script2']
        mockFilterScript.filter.return_value = mockReturnAllScripts

        self.mockDbSession.query.side_effect = [mockFilterHost, mockFilterScript, mockFilterScript]

        self.repository.deleteAllPortsAndScriptsByHostId("some-host-id", "some-protocol")
        self.mockDbSession.delete.assert_has_calls([
            mock.call('some-script1'), mock.call('some-script2'),
            mock.call('some-script1'), mock.call('some-script2'),
            mock.call(mockPort1), mock.call(mockPort2)
        ])
        self.mockDbSession.commit.assert_called_once()
