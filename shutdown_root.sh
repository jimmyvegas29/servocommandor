#!/bin/bash

# Executes the shutdown command immediately.
# Note: We use 'systemctl poweroff' as it's the modern Linux standard.
# The -i flag will be ignored since the script is executed by the system.
/usr/bin/systemctl poweroff