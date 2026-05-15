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

# smbenum 0.3 - This script will enumerate SMB using every tool in the arsenal
# SECFORCE - Antonio Quina

IFACE="eth0"

if [ $# -eq 0 ]
	then
		echo "Usage: $0 <IP>"
		echo "eg: $0 10.10.10.10"
		exit
	else
		IP="$1"
fi

echo -e "\n########## Getting Netbios name ##########"
nbtscan -v -h $IP

echo -e "\n########## Checking for NULL sessions ##########"
output=`bash -c "echo 'srvinfo' | rpcclient $IP -U%"`
echo $output

echo -e "\n########## Enumerating domains ##########"
bash -c "echo 'enumdomains' | rpcclient $IP -U%"

echo -e "\n########## Enumerating users ##########"
nmap -Pn -T4 -sS -p139,445 --script=smb-enum-users $IP
bash -c "echo 'enumdomusers' | rpcclient $IP -U%"

echo -e "\n########## Enumerating Administrators ##########"
net rpc group members "Administrators" -I $IP -U%

echo -e "\n########## Enumerating Domain Admins ##########"
net rpc group members "Domain Admins" -I $IP -U%

echo -e "\n########## Enumerating groups ##########"
nmap -Pn -T4 -sS -p139,445 --script=smb-enum-groups $IP

echo -e "\n########## Enumerating shares ##########"
nmap -Pn -T4 -sS -p139,445 --script=smb-enum-shares $IP
