#!/bin/bash
# snmpwalk_discovered.sh — walk SNMP using community strings discovered by onesixtyone
# Usage: snmpwalk_discovered.sh <IP> <OUTPUT_DIR> <OUTPUT>
IP="$1"; ODIR="$2"; OUT="$3"

STRINGS=$(grep -rh '\[' "$ODIR"/*onesixtyone*"$IP"* 2>/dev/null | sed 's/.*\[//;s/\].*//' | sort -u)

if [ -z "$STRINGS" ]; then
    echo "No community strings discovered by onesixtyone for $IP" | tee "$OUT.txt"
    exit 0
fi

for cs in $STRINGS; do
    echo "=== Community: $cs ==="
    snmpwalk -c "$cs" -v2c "$IP" 2>&1
done | tee "$OUT.txt"
