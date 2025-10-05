#!/bin/bash

# $1 refers to the first command-line argument: 'poweroff' or 'reboot'

if [ -z "$1" ]; then
    COMMAND="poweroff" # Default action if nothing is passed
else
    COMMAND="$1"
fi

# ? EXECUTE COMMAND DIRECTLY (as script is already running as root from Python)
/usr/bin/systemctl "$COMMAND"