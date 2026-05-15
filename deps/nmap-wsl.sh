#!/bin/bash
# -----------------------------------------------------------------------
# LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
# Author: Tim McLean (Viasat, Inc.)
# Copyright (c) 2025-2026 Viasat, Inc.
# Copyright (c) 2025 Shane William Scott (original Legion)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
# IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE.
# -----------------------------------------------------------------------

if [ ! -f "/mnt/c/Program Files (x86)/Nmap/nmap.exe" ]
then
    echo "Install Windows NMAP for NMAP support in WSL. Linux NMAP will not work."
    exit 1
fi

"/mnt/c/Program Files (x86)/Nmap/nmap.exe" "$@"
