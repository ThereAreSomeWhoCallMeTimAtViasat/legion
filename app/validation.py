"""
LEGION (https://shanewilliamscott.com)
Copyright (c) 2025 Shane William Scott

    This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
    License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
    version.

    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
    warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
    details.

    You should have received a copy of the GNU General Public License along with this program.
    If not, see <http://www.gnu.org/licenses/>.

Author(s): Shane Scott (sscott@shanewilliamscott.com), Dmitriy Dubson (d.dubson@gmail.com)
"""

import re

def validateNmapInput(text):
    """Validate nmap input entered in Add Hosts dialog.
    Allowed: letters, digits, colon, dot, slash, hyphen, comma.
    Spaces excluded (T12 — shell injection).
    Comma is allowed only for nmap octet-shorthand (e.g. 192.168.85.11,111)
    where every post-comma token is digits-only.  A comma followed by a dot
    or slash (i.e. a full IP or CIDR) is rejected."""
    if re.search(r'[^a-zA-Z0-9:.\/\-,]', text) is not None:
        return False
    if ',' in text:
        parts = text.split(',')
        for part in parts[1:]:
            if not part.isdigit():
                return False
    return True

def validateCommandFormat(text):
    """Used by settings dialog to validate commands."""
    if text != '' and text != ' ':
        return True
    return False

def validateNumeric(text):
    """Only allows numbers."""
    if text.isdigit():
        return True
    return False

def validateString(text):
    """Only allows alphanumeric characters, '_' and '-'."""
    if text != '' and re.search(r"[^A-Za-z0-9_-]+", text) is None:
        return True
    return False

def validateStringWithSpace(text):
    """Only allows alphanumeric characters, '_', '-' and space."""
    if text != '' and re.search(r"[^A-Za-z0-9_() -]+", text) is None:
        return True
    return False

def validateNmapPorts(text):
    """Only allows alphanumeric characters and the following: ./-'"*,:[any kind of space]"""
    if re.search(r'[^a-zA-Z0-9\.\/\-\'\"\*\,\:\s]', text) is not None:
        return False
    return True
