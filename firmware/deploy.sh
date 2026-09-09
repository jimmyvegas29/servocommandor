#!/bin/bash
# Deploy the DRO tap firmware to the RP2350-Plus on /dev/ttyACM0 and show
# a few seconds of its output.
set -e
cd /home/nocuser/dro_tap
M=/home/nocuser/dro_dev/venv/bin/mpremote
$M connect /dev/ttyACM0 fs cp encoder_rp2.py :encoder_rp2.py
$M connect /dev/ttyACM0 fs cp main.py :main.py
$M connect /dev/ttyACM0 fs ls
$M connect /dev/ttyACM0 reset
sleep 2
timeout 6 /home/nocuser/dro_dev/venv/bin/python /home/nocuser/dro_dev/fw/read_stream.py "${1:-3}"
