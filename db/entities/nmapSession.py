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

from sqlalchemy import String, Column

from db.database import Base


class nmapSessionObj(Base):
    __tablename__ = 'nmapSessionObj'
    filename = Column(String, primary_key=True)
    startTime = Column(String)
    finish_time = Column(String)
    nmapVersion = Column(String)
    scanArgs = Column(String)
    totalHosts = Column(String)
    upHosts = Column(String)
    downHosts = Column(String)

    def __init__(
        self,
        filename,
        startTime='',
        finish_time='',
        nmapVersion='unknown',
        scanArgs='',
        totalHosts='0',
        upHosts='0',
        downHosts='0',
        **kwargs
    ):
        self.filename = filename
        self.startTime = kwargs.get('startTime', startTime) or ''
        self.finish_time = kwargs.get('finish_time', finish_time) or ''
        self.nmapVersion = kwargs.get('nmapVersion', nmapVersion) or 'unknown'
        self.scanArgs = kwargs.get('scanArgs', scanArgs) or ''
        # Some legacy code may use the old 'total_host' key name
        legacy_total = kwargs.get('total_host')
        self.totalHosts = kwargs.get('totalHosts', legacy_total if legacy_total is not None else totalHosts) or '0'
        self.upHosts = kwargs.get('upHosts', upHosts) or '0'
        self.downHosts = kwargs.get('downHosts', downHosts) or '0'
