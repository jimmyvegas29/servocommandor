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
