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

import xml

from app.auxiliary import log
from parsers.OS import OS

if __name__ == '__main__':
    dom = xml.dom.minidom.parse('test.xml')
    osclass = dom.getElementsByTagName('osclass')[0]
    osmatch = dom.getElementsByTagName('osmatch')[0]

    os = OS(osclass)
    log.info(os.name)
    log.info(os.family)
    log.info(os.generation)
    log.info(os.osType)
    log.info(os.vendor)
    log.info(str(os.accuracy))

    os = OS(osmatch)
    log.info(os.name)
    log.info(os.family)
    log.info(os.generation)
    log.info(os.osType)
    log.info(os.vendor)
    log.info(str(os.accuracy))
