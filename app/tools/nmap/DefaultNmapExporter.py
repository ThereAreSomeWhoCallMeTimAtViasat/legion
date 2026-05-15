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

import subprocess
from logging import Logger

from app.shell.Shell import Shell
from app.timing import timing
from app.tools.nmap.NmapExporter import NmapExporter
import os


class DefaultNmapExporter(NmapExporter):
    def __init__(self, shell: Shell, logger: Logger):
        self.logger = logger
        self.shell = shell

    @timing
    def exportOutputToHtml(self, fileName: str, outputFolder: str) -> None:
        try:
            command = f"xsltproc -o {fileName}.html /usr/share/nmap/nmap.xsl {fileName}.xml"
            p = subprocess.Popen(command, shell=True)
            p.wait()
            self.shell.move(f"{fileName}.html", outputFolder)
        except:
            # HTML export is a Qt6 display feature not used by the Flask web UI.
            # xsltproc missing is expected and not an error in this context.
            self.logger.debug("nmap HTML export skipped (xsltproc not available — not needed for Flask UI)")
