import unittest
from unittest.mock import MagicMock

from tests.db.helpers.db_helpers import mockExecuteFetchAll


class ScriptRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        from db.repositories.ScriptRepository import ScriptRepository
        self.mockDbAdapter = MagicMock()
        self.mockDbSession = MagicMock()
        # session is a property
        self.mockDbAdapter.session = self.mockDbSession
        self.scriptRepository = ScriptRepository(self.mockDbAdapter)

    def test_getScriptsByHostIP_WhenProvidedAHostIP_ReturnsAllScripts(self):
        # Mock execute().fetchall() to return tuples - implementation converts to dicts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('some-script1',), ('some-script2',)]
        mock_result.keys.return_value = ['id']
        self.mockDbSession.execute.return_value = mock_result
        
        scripts = self.scriptRepository.getScriptsByHostIP("some-host-ip")
        self.assertEqual([{'id': 'some-script1'}, {'id': 'some-script2'}], scripts)
        self.mockDbSession.execute.assert_called_once()

    def test_getScriptOutputById_WhenProvidedAScriptId_ReturnsScriptOutput(self):
        # Mock execute().fetchall() to return tuples - implementation converts to dicts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [('some-script-output1',), ('some-script-output2',)]
        mock_result.keys.return_value = ['output']
        self.mockDbSession.execute.return_value = mock_result

        scripts = self.scriptRepository.getScriptOutputById("some-id")
        self.assertEqual([{'output': 'some-script-output1'}, {'output': 'some-script-output2'}], scripts)
        self.mockDbSession.execute.assert_called_once()
