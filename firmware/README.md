# DRO tap board firmware (MicroPython)

Counts the two Sino glass scales with the RP2350 PIO and publishes raw
counts 20 times a second.

- `main_usb.py`  - RP2350-Plus (no radio): USB serial only
- `main_ble.py`  - Pico 2 W: USB serial + Bluetooth LE (advertises
  `SERVOCOM-DRO-xxxx`, service 5e7a0001-...)
- `encoder_rp2.py` - Peter Hinch's PIO X4 quadrature decoder (hard IRQ)
- `deploy.sh` - copies the files with mpremote and prints the stream

Flash MicroPython first (RPI_PICO2 or RPI_PICO2_W UF2), then copy the
chosen main_*.py to the board as `main.py` plus `encoder_rp2.py`.

Pins: X A/B = GP6/GP7, Z A/B = GP2/GP3, scale 5V from VBUS.

## Machine node (Pico 2 W in the lathe box)

- `launcher.py` -> copy to the board as `main.py` once.  It runs `node.py`,
  installs a staged `node_new.py`, and rolls back if a new image never
  confirms.  Never updated over the air.
- `main_node.py` -> copy as `node.py`.  `VERSION` at the top is what the
  panel compares against; bump it on every change.

First flash (USB):

    mpremote connect /dev/ttyACM0 fs cp firmware/encoder_rp2.py :encoder_rp2.py
    mpremote connect /dev/ttyACM0 fs cp firmware/launcher.py :main.py
    mpremote connect /dev/ttyACM0 fs cp firmware/main_node.py :node.py
    mpremote connect /dev/ttyACM0 reset

After that: Settings > Connection > UPDATE NODE pushes the panel's
`firmware/main_node.py` over Bluetooth (servo must be disabled).  The node
verifies the crc, resets, runs the new image as a trial and confirms it
after 30 s online and linked; otherwise the launcher puts the old one back.

First-connect lock: the node remembers the first panel that connects
(`panel.lock`) and drops any other central.  Power the node on with the
lever in REV to forget the panel.
