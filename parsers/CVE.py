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

class CVE:
    name = ''
    product = ''
    version = ''
    url = ''
    source = ''
    severity = ''
    exploitId = ''
    exploit = ''
    exploitUrl = ''

    def __init__(self, cveData):
        self.name = cveData.get('id', 'unknown')
        self.product = cveData.get('product', 'unknown')
        self.version = cveData.get('version', 'unknown')
        self.url = cveData.get('url', 'unknown')
        self.source = cveData.get('source', 'unknown')
        self.severity = cveData.get('severity', 'unknown')
        self.exploitId = cveData.get('exploitId', '')
        self.exploit = cveData.get('exploit', '')
        self.exploitUrl = cveData.get('exploitUrl', '')
