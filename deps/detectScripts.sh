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

echo "Checking for additional Sparta scripts..."
curPath=`pwd`

scripts=("smbenum.sh" "snmpbrute.py" "ms08-067_check.py" "rdp-sec-check.pl", "ndr.py", "installDeps.sh", "snmpcheck.rb", "smtp-user-enum.pl")

for script in "${scripts[@]}"; do
  if [ -a "scripts/$script" ]; then
    echo "$script is already installed"
  else
    wget -v -P scripts/ "https://raw.githubusercontent.com/Hackman238/sparta-scripts/master/$script"
  fi
done

declare -A externalRepos
externalRepos["CloudFail"]="https://github.com/m0rtem/CloudFail.git"

for externalRepo in "${!externalRepos[@]}"; do
  if [ -d "scripts/$externalRepos" ]; then
    echo "$externalRepo is already installed"
  else
    git clone "${externalRepos[$externalRepo]}" scripts/$externalRepo
  fi
done

if [ ! -f ".initialized" ]
  then
    chmod a+x scripts/installDeps.sh
    ./scripts/installDeps.sh
fi

cd ${curPath}
