#!/usr/bin/env python3
"""Run a quick probe: connect to a device, send inverter kick-start, print telemetry."""
import sys
import time

from bluetooth_manager import BluetoothManager


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_inverter_probe.py <BLE_ADDRESS>")
        sys.exit(2)
    addr = sys.argv[1]
    m = BluetoothManager()

    # simple debug parser to print binary frames
    def dbg(raw: bytes):
        print("BINARY IN:", raw.hex())
        return None

    m.register_binary_parser(dbg)

    ok, msg = m.connect(addr, send_inverter_kick=True)
    print(ok, msg)
    if not ok:
        sys.exit(1)
    # allow a few seconds for notifies to arrive (or use provided timeout)
    timeout = float(sys.argv[2]) if len(sys.argv) >= 3 else 8.0
    print(f"Listening for {timeout} seconds for binary notifies...")
    time.sleep(timeout)
    tel = m.get_telemetry()
    print("Telemetry:")
    for k, v in sorted(tel.items()):
        print(f"  {k}: {v}")

    m.disconnect()


if __name__ == '__main__':
    main()
