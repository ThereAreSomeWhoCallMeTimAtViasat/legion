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

echo "Checking Apt..."
# runAptGetUpdate
apt-get update -m

echo "Installing bcs..."
export DEBIAN_FRONTEND="noninteractive"
apt-get -yqqqm --allow-unauthenticated -o DPkg::Options::="--force-overwrite" -o DPkg::Options::="--force-confdef" install bc

# Check if python or python3 is installed
if command -v python &> /dev/null || command -v python3 &> /dev/null
then
    # Get the python or python3 version and path
    if command -v python &> /dev/null
    then
        python_version=$(python --version | awk -F '[ ]' '{print $2}' | awk -F '[.]' '{print $1"."$2}')
        python_path=$(which python)
    else
        python_version=$(python3 --version | awk -F '[ ]' '{print $2}' | awk -F '[.]' '{print $1"."$2}')
        python_path=$(which python3)
    fi
    echo "Python version: $python_version"
    echo "Python path: $python_path"

    # Check if the python version is 3.8 or later
    if (( $(echo "$python_version >= 3.8" |bc -l) ))
    then
        export PYTHON3BIN=$python_path
        echo "PYTHON3BIN is set to $PYTHON3BIN"
    else
        echo "Your Python version is below 3.8, which may cause compatibility issues with some packages."
    fi
else
    echo "Python is not installed."
fi

# Check if pip or pip3 is installed
if command -v pip &> /dev/null || command -v pip3 &> /dev/null
then
    # Get the pip or pip3 version and path
    if command -v pip &> /dev/null
    then
        pip_version=$(pip --version)
        pip_path=$(which pip)
    else
        pip_version=$(pip3 --version)
        pip_path=$(which pip3)
    fi
    echo "Pip version: $pip_version"
    echo "Pip path: $pip_path"

    export PIP3BIN=$pip_path
    echo "PIP3BIN is set to $PIP3BIN"
else
    echo "Pip is not installed."
fi
