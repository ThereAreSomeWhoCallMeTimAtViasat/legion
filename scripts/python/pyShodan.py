#!/usr/bin/env python3

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

from pyShodan import PyShodan
import os
import sys

class PyShodanScript():
    def __init__(self):
        self.dbHost = None
        self.session = None

    def setDbHost(self, dbHost):
        self.dbHost = dbHost

    def setSession(self, session):
        self.session = session

    def run(self):
        if not self.dbHost or not hasattr(self.dbHost, "ipv4"):
            print("No dbHost or ipv4 provided.")
            return {}
        ip = str(self.dbHost.ipv4)
        return self.lookup(ip)

    def lookup(self, ip):
        try:
            pyShodanObj = PyShodan()
            pyShodanObj.apiKey = os.environ.get('SHODAN_API_KEY', '')
            pyShodanObj.createSession()
            pyShodanResults = pyShodanObj.searchIp(ip, allData=True)
            if isinstance(pyShodanResults, dict) and pyShodanResults:
                if self.dbHost and self.session:
                    self.dbHost.latitude = pyShodanResults.get('latitude', 'unknown')
                    self.dbHost.longitude = pyShodanResults.get('longitude', 'unknown')
                    self.dbHost.asn = pyShodanResults.get('asn', 'unknown')
                    self.dbHost.isp = pyShodanResults.get('isp', 'unknown')
                    self.dbHost.city = pyShodanResults.get('city', 'unknown')
                    self.dbHost.countryCode = pyShodanResults.get('country_code', 'unknown')
                    self.session.add(self.dbHost)
                print(pyShodanResults)
                return pyShodanResults
            else:
                print("No results found or error in response.")
                return {}
        except Exception as e:
            print(f"Error: {e}")
            return {}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: pyShodan.py <IP_ADDRESS>")
        sys.exit(1)
    ip = sys.argv[1]
    script = PyShodanScript()
    script.lookup(ip)
