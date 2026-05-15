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

__author__ = 'SECFORCE'
__version__ = '0.1'

from typing import Optional

import parsers.Service as Service
import parsers.Script as Script


class Port:
    portId: str = ''
    protocol: str = ''
    state: str = ''

    def __init__(self, PortNode):
        if not (PortNode is None):
            self.portNode = PortNode
            self.portId = PortNode.getAttribute('portid')
            self.protocol = PortNode.getAttribute('protocol')
            state_nodes = PortNode.getElementsByTagName('state')
            if state_nodes:
                self.state = state_nodes[0].getAttribute('state')
            else:
                self.state = 'unknown'

    def getService(self) -> Optional[Service.Service]:
        service_node = self.portNode.getElementsByTagName('service')

        if len(service_node) > 0:
            return Service.Service(service_node[0])

        return None

    # def get_cpe(self):

    #     cpes = []
    #     cpe = self.portNode.getElementsByTagName('cpe')
    #     print(cpe)

    #     if len(cpe) > 0:
    #        return CPE.CPE(cpe[0])

    #     return None

    def getScripts(self):
        scripts = []
        for scriptNode in self.portNode.getElementsByTagName('script'):
            scr = Script.Script(scriptNode)
            scripts.append(scr)

        return scripts
