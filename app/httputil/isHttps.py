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

import ssl



def defaultUserAgent() -> str:
    return "Mozilla/5.0 (X11; Linux x86_64; rv:22.0) Gecko/20100101 Firefox/22.0 Iceweasel/22.0"

def isHttps(host, port) -> bool:
    import socket
    from urllib.error import URLError
    
    try:
        # Check if host is valid before making connections
        try:
            socket.inet_aton(host)
        except socket.error:
            try:
                socket.gethostbyname(host)
            except socket.gaierror:
                print(f"Cannot resolve host {host}")
                return False
        
        try:
            from urllib.request import Request, urlopen
            headers = {"User-Agent": defaultUserAgent()}
            req = Request(f"https://{host}:{port}", headers=headers)
            urlopen(req, timeout=5).read()
            return True
        except URLError as e:
            # Check if the underlying reason is an SSLError
            if isinstance(e.reason, ssl.SSLError):
                print(f"ssl.SSLError in URLError: {e.reason}")
                return False
            reason = str(e.reason)
            print("urlerror: " + reason)
            if 'Forbidden' in reason or 'certificate verify failed' in reason:
                return True
            return False
        except ssl.CertificateError:
            print("ssl")
            return True
        except Exception as e:
            print(f"isHttps exception: {type(e).__name__}: {e}")
            return False
    except Exception as e:
        print(f"isHttps outer exception: {type(e).__name__}: {e}")
        return False
