#!/usr/bin/python

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

__author__ =  'yunshu(wustyunshu@hotmail.com)'
__version__=  '0.2'

class Session:
    def __init__(self, SessionHT):
        self.startTime = SessionHT.get('startTime', '')
        self.finish_time = SessionHT.get('finish_time', '')
        self.nmapVersion = SessionHT.get('nmapVersion', '')
        self.scanArgs = SessionHT.get('scanArgs', '')
        self.totalHosts = SessionHT.get('totalHosts', '')
        self.upHosts = SessionHT.get('upHosts', '')
        self.downHosts = SessionHT.get('downHosts', '')
        # List of progress snapshots, each is a dict with keys: percent, remaining, elapsed, task, etc.
        self.progress_data = []

    def add_progress(self, progress_dict):
        """Add a progress snapshot (dict) to the session."""
        self.progress_data.append(progress_dict)

    def get_latest_progress(self):
        """Return the most recent progress snapshot, or None if none exist."""
        if self.progress_data:
            return self.progress_data[-1]
        return None
