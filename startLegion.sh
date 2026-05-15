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

echo "Strap yourself in, we're starting Legion..."

# Set everything we might need as executable
chmod a+x -R ./deps/*
chmod a+x -R ./scripts/*

# Determine OS, version and if WSL
source ./deps/detectOs.sh

# Determine and set the Python and Pip paths
source ./deps/detectPython.sh

# Figure if fist run or recloned and install deps 
if [ ! -f ".initialized" ] | [ -f ".justcloned" ]
then
    echo "First run here (or you did a pull to update). Let's try to automatically install all the dependancies..."
    if [ ! -d "tmp" ]
    then
        mkdir tmp
    fi

    # Setup WSL bits if needed
    if [ ! -z $ISWSL ]
    then
        echo "WSL Setup..."
        bash ./deps/setupWsl.sh
    fi

    # Install dependancies from package manager
    echo "Installing Packages from APT..."
    ./deps/installDeps.sh

    # Install python dependancies
    echo "Installing Python Libraries..."
    ./deps/installPythonLibs.sh

    # Patch Qt
    echo "Stripping some ABIs from Qt libraries..."
    ./deps/fixQt.sh

    # Determine if additional Sparta scripts are installed
    bash ./deps/detectScripts.sh

    touch .initialized
    rm .justcloned -f
fi

export QT_XCB_NATIVE_PAINTING=0
export QT_AUTO_SCREEN_SCALE_FACTOR=1.5

# Verify X can be reached
source ./deps/checkXserver.sh

if [[ $1 != 'setup' ]]
then
    /usr/bin/env python3 legion.py
fi
