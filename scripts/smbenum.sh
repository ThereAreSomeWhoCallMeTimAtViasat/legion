#!/bin/sh
# smbenum.sh — SMB enumeration via smbclient + rpcclient
# Usage: smbenum.sh <IP>
IP="$1"
if [ -z "$IP" ]; then echo "Usage: $0 <IP>"; exit 1; fi

echo "=== SMB Share Enumeration: $IP ==="
smbclient -L "//$IP" -N -p 445 2>&1

echo ""
echo "=== RPC Null Session Users ==="
rpcclient -U "" "$IP" -N -c "enumdomusers" 2>&1 | head -20

echo ""
echo "=== RPC Null Session Groups ==="
rpcclient -U "" "$IP" -N -c "enumalsgroups domain" 2>&1 | head -10
