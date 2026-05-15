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

import requests
import sys

class macvendorsScript():
    def __init__(self):
        self.dbHost = None
        self.session = None

    def setDbHost(self, dbHost):
        self.dbHost = dbHost

    def setSession(self, session):
        self.session = session

    def run(self):
        if not self.dbHost or not hasattr(self.dbHost, "macaddr"):
            print("No dbHost or macaddr provided.")
            return "unknown"
        mac = str(self.dbHost.macaddr)
        return self.lookup(mac)

    def lookup(self, mac):
        url = "https://api.macvendors.com/" + mac
        try:
            r = requests.get(url, timeout=10)
            result = str(r.text)
            if not result or "error" in result.lower():
                result = "unknown"
            if self.dbHost and self.session:
                self.dbHost.vendor = result
                self.session.add(self.dbHost)
                self.session.commit()
                self.session.close()
            print(result)
            return result
        except Exception as e:
            print(f"Error: {e}")
            return "unknown"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: macvendors.py <MAC_ADDRESS>")
        sys.exit(1)
    mac = sys.argv[1]
    script = macvendorsScript()
    script.lookup(mac)
