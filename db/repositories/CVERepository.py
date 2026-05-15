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

from sqlalchemy import text
from db.SqliteDbAdapter import Database

class CVERepository:
    def __init__(self, dbAdapter: Database):
        self.dbAdapter = dbAdapter

    def getCVEsByHostIP(self, hostIP):
        session = self.dbAdapter.session
        # Cast severity to REAL (float) and order by it descending (highest CVSS first)
        query = text('SELECT DISTINCT cves.name, CAST(cves.severity AS REAL) as severity, cves.product, cves.version, cves.url, cves.source, '
                     'cves.exploitId, cves.exploit, cves.exploitUrl FROM cve AS cves '
                     'INNER JOIN hostObj AS hosts ON hosts.id = cves.hostId '
                     'WHERE hosts.ip = :hostIP '
                     'ORDER BY CAST(cves.severity AS REAL) DESC')
        result = session.execute(query, {'hostIP': str(hostIP)})
        rows = result.fetchall()
        keys = result.keys()
        cves = [dict(zip(keys, row)) for row in rows]
        session.close()
        return cves
