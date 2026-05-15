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

# EyeWitness install directory (for manual install)
EYEWITNESS_DIR="/usr/local/EyeWitness"
EYEWITNESS_SCRIPT="$EYEWITNESS_DIR/Python/EyeWitness.py"

# 1. Check for native install
if command -v eyewitness >/dev/null 2>&1; then
    echo "[+] EyeWitness is already installed natively."
    exit 0
fi

# 2. Try to install via apt
echo "[*] EyeWitness not found. Trying to install via apt..."
sudo apt update
sudo apt install -y eyewitness

if command -v eyewitness >/dev/null 2>&1; then
    echo "[+] EyeWitness installed via apt."
    exit 0
fi

# 3. Fallback to manual install (current logic)
if [ ! -f "$EYEWITNESS_SCRIPT" ]; then
    echo "[*] EyeWitness not available via apt. Installing manually..."
    sudo apt install -y git python3 python3-pip xvfb chromium-browser
    git clone https://github.com/FortyNorthSecurity/EyeWitness.git "$EYEWITNESS_DIR"
    python3 -m pip install fuzzywuzzy selenium==4.9.1 python-Levenshtein pyvirtualdisplay netaddr
    echo 'python3 $EYEWITNESS_SCRIPT $@' | sudo tee /usr/local/bin/eyewitness > /dev/null
    sudo chmod +x /usr/local/bin/eyewitness
    sudo chmod +x "$EYEWITNESS_SCRIPT"
    echo "[+] EyeWitness installed at $EYEWITNESS_SCRIPT"
else
    echo "[+] EyeWitness is already installed at $EYEWITNESS_SCRIPT"
fi
