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

from datetime import datetime
from functools import wraps
from time import time

from app.logging.legionLog import getAppLogger

timestampFormats = {
    "HUMAN_FORMAT": "%d %b %Y %H:%M:%S.%f",
    "STANDARD_TIMESTAMP": '%Y%m%d%H%M%S%f'
}


def timing(f):
    log = getAppLogger()

    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        tr = te - ts
        log.debug('Function:%r args:[%r, %r] took: %2.4f sec' % (f.__name__, args, kw, tr))
        return result

    return wrap


def getTimestamp(human: bool = False) -> str:
    timeFormat = timestampFormats["HUMAN_FORMAT"] if human else timestampFormats["STANDARD_TIMESTAMP"]
    return datetime.fromtimestamp(time()).strftime(timeFormat)
