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

# X11screenshot- This script will take a screenshot over X11, save it to an output folder and open it
# SECFORCE - Antonio Quina

if [ $# -eq 0 ]
	then
		echo "Usage: $0 <IP> <DISPLAY>"
		echo "eg: $0 10.10.10.10 0 /outputfolder"
		exit
	else
		IP="$1"
fi

if [ "$2" == "" ]
	then
		DSP="0"
	else
		DSP="$2"
fi

if [ "$3" == "" ]
	then
		OUTFOLDER="/tmp"
	else
		OUTFOLDER="$3"
        if [ ! -d "$OUTFOLDER" ]
        then
            mkdir $OUTFOLDER
        fi
fi

echo "xwd -root -screen -silent -display $IP:$DSP > $OUTFOLDER/x11screenshot-$IP.xwd"
xwd -root -screen -silent -display $IP:$DSP > $OUTFOLDER/x11screenshot-$IP.xwd

echo "convert $OUTFOLDER/x11screenshot-$IP.xwd $OUTFOLDER/x11screenshot-$IP.jpg"
convert $OUTFOLDER/x11screenshot-$IP.xwd $OUTFOLDER/x11screenshot-$IP.jpg

if [ -f "$OUTFOLDER/x11screenshot-$IP.jpg" ]
then
    echo "xdg-open $OUTFOLDER/x11screenshot-$IP.jpg"
    xdg-open $OUTFOLDER/x11screenshot-$IP.jpg
fi
