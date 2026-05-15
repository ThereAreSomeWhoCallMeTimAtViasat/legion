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

# Setup linked Windows NMAP
if [ -f "/usr/bin/nmap" ]
then
    nmapBinCheck=$(cat /usr/bin/nmap | grep -c "nmap.exe")
else
    nmapBinCheck=1
fi

if [ ! -f "/sbin/nmap" ] | [ ${nmapBinCheck} -eq 0 ]
then
    echo "Installing Link to Windows NMAP..."
    today=$(date +%s)
    mv /usr/bin/nmap /usr/bin/nmap_lin_${today}
    cp ./deps/nmap-wsl.sh /sbin/nmap
    chmod a+x /sbin/nmap
    if [ ! -f "/sbin/nmap" ]
    then
        ln -s /sbin/nmap /usr/bin/nmap
    fi
else
    echo "Link to Windows NMAP already exists; skipping."
fi
