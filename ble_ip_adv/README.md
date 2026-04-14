This program checks the Raspberry Pi's local IP address (every 1s) and creates a BLE (Bluetooth Low Energy) advertisement that includes the IP address in the device name. This way, we can find out what the IP address of the Raspberry Pi is if we are physically near the Raspberry Pi. The program advertises the Raspberry Pi as if it were a connectable device (even though it's not connectable) so that on any device you can just open the Bluetooth settings to pair a new device and it will show up.

This program uses the `bluer` library, which works on Linux only.
