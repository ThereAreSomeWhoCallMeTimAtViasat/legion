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

unameOutput=`uname -a`
releaseVersion=`grep 'VERSION_ID' /etc/os-release | cut -d '"' -f 2`
releaseName=`grep "^NAME=\"" /etc/os-release | cut -d '"' -f 2`
wslEnv=""

# Detect WSL and enable XForwaridng to Xming
if [[ ${unameOutput} == *"Microsoft"* ]]
then
    export DISPLAY=localhost:0.0
    wslEnv="WSL"
fi

echo "Detected ${releaseName} ${releaseVersion} ${wslEnv}"

# Figure Linux Version
if [[ ${releaseName} == *"Ubuntu"* ]]
then
    if [[ ${releaseVersion} != *"20.04"* ]] && [[ ${releaseVersion} != *"20.10"* ]] && [[ ${releaseVersion} != *"21."* ]] && [[ ${releaseVersion} != *"22."* ]] && [[ ${releaseVersion} != *"23."* ]] && [[ ${releaseVersion} != *"24."* ]]
    then
        echo "Unsupported Ubuntu version. Please use Ubuntu 20.04 or later."
        exit 1
    else
        echo "Some tools are not available under Ubuntu. Run under Kali if you're missing something."
    fi
elif [[ ${releaseName} == *"Kali"* ]]
then
    if [[ ${releaseVersion} != *"2024"* ]] && [[ ${releaseVersion} != *"2025"* ]]
    then
        echo "Unsupported Kali version. Please use Kali 2022 or later."
        exit 1
    fi
else
    echo "Unsupported distrubution, version or both."
    exit 1
fi

export OS_RELEASE=${releaseName}
export OS_RELEASE_VERSION=${releaseVersion}
export ISWSL=${wslEnv}
