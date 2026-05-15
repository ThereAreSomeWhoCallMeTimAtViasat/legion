"""
LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
Author: Tim McLean (Viasat, Inc.)
Copyright (c) 2025-2026 Viasat, Inc.
Copyright (c) 2025 Shane William Scott (original Legion)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful, but
    WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
    General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
"""

import os

from db.RepositoryContainer import RepositoryContainer
from db.SqliteDbAdapter import Database as SqliteDatabase
from db.repositories.CVERepository import CVERepository
from db.repositories.HostRepository import HostRepository
from db.repositories.NoteRepository import NoteRepository
from db.repositories.PortRepository import PortRepository
from db.repositories.ProcessRepository import ProcessRepository
from db.repositories.ScriptRepository import ScriptRepository
from db.repositories.ServiceRepository import ServiceRepository


class RepositoryFactory:
    def __init__(self, logger):
        self.logger = logger

    def buildRepositories(self, database) -> RepositoryContainer:
        """Wire all repositories to the supplied database adapter.

        The adapter must expose a `session` scoped_session (same interface as
        SqliteDbAdapter.Database).  Pass a SqliteDbAdapter.Database or
        postgresDbAdapter.Database — repositories work unchanged with both.
        """
        hostRepository = HostRepository(database)
        processRepository = ProcessRepository(database, self.logger)
        serviceRepository = ServiceRepository(database)
        portRepository: PortRepository = PortRepository(database)
        cveRepository: CVERepository = CVERepository(database)
        noteRepository: NoteRepository = NoteRepository(database, self.logger)
        scriptRepository: ScriptRepository = ScriptRepository(database)
        return RepositoryContainer(serviceRepository, processRepository, hostRepository,
                                   portRepository, cveRepository, noteRepository, scriptRepository)

    @staticmethod
    def create_database(sqlite_path: str, db_url: str = None):
        """Factory: create the appropriate Database adapter.

        Args:
            sqlite_path: Path to the .legion SQLite file (used when no db_url).
            db_url:      Full SQLAlchemy URL.  If None, falls back to the
                         LEGION_DB_URL environment variable, then SQLite.

        Returns:
            A Database adapter instance compatible with all repositories.
        """
        url = db_url or os.environ.get('LEGION_DB_URL', '').strip()
        if url and url.startswith('postgresql'):
            from db.postgresDbAdapter import Database as PgDatabase
            return PgDatabase(url)
        return SqliteDatabase(sqlite_path)
