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

import threading

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.scoping import scoped_session

from app.logging.legionLog import getDbLogger

# Import all entity classes so their tables are registered with Base
from db.entities.host import hostObj        # noqa: F401
from db.entities.note import note           # noqa: F401
from db.entities.os import osObj            # noqa: F401
from db.entities.port import portObj        # noqa: F401
from db.entities.service import serviceObj  # noqa: F401
from db.entities.nmapSession import nmapSessionObj  # noqa: F401
from db.entities.l1script import l1ScriptObj        # noqa: F401


class Database:
    """PostgreSQL adapter — interface matches SqliteDbAdapter.Database.

    Construct with a full SQLAlchemy URL:
        db = Database("postgresql://user:pass@localhost:5432/legion")
    """

    def __init__(self, db_url: str):
        from db.database import Base
        self.log = getDbLogger()
        self.base = Base
        self._lock = threading.Lock()
        try:
            self._establish_connection(db_url)
        except Exception as e:
            self.log.error(f'[PostgresAdapter] Could not connect: {e}')
            raise

    def _establish_connection(self, db_url: str):
        self.db_url = db_url
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,   # reconnect on stale connections
            pool_size=5,
            max_overflow=10,
        )
        self.session = scoped_session(sessionmaker(bind=self.engine, autoflush=False))
        # Create all tables that don't exist yet
        self.base.metadata.create_all(self.engine)
        self.log.info(f"[PostgresAdapter] Connected to {db_url.split('@')[-1]}")

    def openDB(self, db_url: str):
        """Re-open with a different URL (e.g. after project switch)."""
        try:
            self.session.remove()
            self.engine.dispose()
        except Exception:
            pass
        self._establish_connection(db_url)

    def commit(self):
        with self._lock:
            try:
                self.session().commit()
            except Exception as e:
                self.log.error(f'[PostgresAdapter] Commit failed: {e}')
                self.session().rollback()
